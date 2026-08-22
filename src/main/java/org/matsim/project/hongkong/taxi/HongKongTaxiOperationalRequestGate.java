package org.matsim.project.hongkong.taxi;

import com.google.inject.Inject;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.contrib.dvrp.passenger.PassengerRequestSubmittedEvent;
import org.matsim.contrib.dvrp.passenger.PassengerRequestSubmittedEventHandler;
import org.matsim.core.api.experimental.events.EventsManager;
import org.matsim.core.controler.OutputDirectoryHierarchy;
import org.matsim.core.mobsim.framework.MobsimAgent;
import org.matsim.core.mobsim.qsim.InternalInterface;
import org.matsim.core.mobsim.qsim.interfaces.DepartureHandler;
import org.matsim.core.mobsim.qsim.interfaces.MobsimEngine;
import org.matsim.core.utils.io.IOUtils;

import java.io.BufferedWriter;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.PriorityQueue;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Prevents operational-only Taxi passengers from submitting independently.
 * A shadow is released only after its matching behavioral parent has submitted
 * the corresponding real Taxi request, plus its deterministic 0..899 s delay.
 * Event callbacks never invoke QSim while holding application state, avoiding
 * the lock-order failures seen in the earlier Hong Kong run.
 */
public final class HongKongTaxiOperationalRequestGate implements
		MobsimEngine, DepartureHandler, PassengerRequestSubmittedEventHandler {

	public static final String SHADOW_ATTRIBUTE = "hkTaxiOperationalShadow";
	public static final String PARENT_ATTRIBUTE = "hkTaxiShadowParentPersonId";
	public static final String PARENT_LEG_ATTRIBUTE = "hkTaxiShadowParentLegIndex";
	public static final String RELEASE_DELAY_ATTRIBUTE = "hkTaxiShadowReleaseDelaySeconds";

	private record ParentKey(String personId, int legIndex) { }
	private record Scheduled(Held held, double due, long sequence) { }

	private static final class Held {
		private final MobsimAgent agent;
		private final ParentKey parent;
		private final double delay;
		private final AtomicBoolean scheduled = new AtomicBoolean();

		private Held(MobsimAgent agent, ParentKey parent, double delay) {
			this.agent = agent;
			this.parent = parent;
			this.delay = delay;
		}
	}

	private final Scenario scenario;
	private final EventsManager events;
	private final OutputDirectoryHierarchy output;
	private final Map<Id<Person>, List<Integer>> parentTaxiLegIndices = new ConcurrentHashMap<>();
	private final Map<Id<Person>, AtomicInteger> parentSubmissionOrdinals = new ConcurrentHashMap<>();
	private final Map<ParentKey, Double> parentSubmissionTimes = new ConcurrentHashMap<>();
	private final Map<ParentKey, ConcurrentLinkedQueue<Id<Person>>> heldByParent = new ConcurrentHashMap<>();
	private final Map<Id<Person>, Held> heldByAgent = new ConcurrentHashMap<>();
	private final Set<Id<Person>> released = ConcurrentHashMap.newKeySet();
	private final ConcurrentLinkedQueue<Scheduled> inbound = new ConcurrentLinkedQueue<>();
	private final PriorityQueue<Scheduled> scheduled = new PriorityQueue<>(
			Comparator.comparingDouble(Scheduled::due).thenComparingLong(Scheduled::sequence));
	private final AtomicLong sequence = new AtomicLong();
	private final AtomicLong parentSubmissions = new AtomicLong();
	private final AtomicLong heldDepartures = new AtomicLong();
	private final AtomicLong releasedDepartures = new AtomicLong();
	private InternalInterface internalInterface;

	@Inject
	public HongKongTaxiOperationalRequestGate(
			Scenario scenario, EventsManager events, OutputDirectoryHierarchy output) {
		this.scenario = scenario;
		this.events = events;
		this.output = output;
		indexParentTaxiLegs();
	}

	private void indexParentTaxiLegs() {
		for (Person person : scenario.getPopulation().getPersons().values()) {
			if (isShadow(person)) continue;
			List<Integer> indices = new ArrayList<>();
			int legIndex = 0;
			for (var element : person.getSelectedPlan().getPlanElements()) {
				if (element instanceof Leg leg) {
					if (HongKongTaxiScoringParameters.TAXI_MODE.equals(leg.getMode())) {
						indices.add(legIndex);
					}
					legIndex++;
				}
			}
			if (!indices.isEmpty()) parentTaxiLegIndices.put(person.getId(), List.copyOf(indices));
		}
	}

	@Override
	public boolean handleDeparture(double now, MobsimAgent agent,
			Id<org.matsim.api.core.v01.network.Link> fromLinkId) {
		Person person = scenario.getPopulation().getPersons().get(agent.getId());
		if (person == null || !isShadow(person)) return false;
		if (!HongKongTaxiScoringParameters.TAXI_MODE.equals(agent.getMode())) {
			throw new IllegalStateException("Operational Taxi shadow departed with mode "
					+ agent.getMode() + ": " + agent.getId());
		}
		if (released.remove(agent.getId())) return false;
		ParentKey parent = parentKey(person);
		double delay = number(person, RELEASE_DELAY_ATTRIBUTE);
		Double submitted = parentSubmissionTimes.get(parent);
		if (submitted != null && now >= submitted + delay) return false;

		Held value = new Held(agent, parent, delay);
		Held previous = heldByAgent.putIfAbsent(agent.getId(), value);
		if (previous != null) {
			throw new IllegalStateException("Operational Taxi shadow was held twice: " + agent.getId());
		}
		heldByParent.computeIfAbsent(parent, ignored -> new ConcurrentLinkedQueue<>())
				.add(agent.getId());
		heldDepartures.incrementAndGet();
		submitted = parentSubmissionTimes.get(parent);
		if (submitted != null) schedule(value, submitted + delay);
		return true;
	}

	@Override
	public void handleEvent(PassengerRequestSubmittedEvent event) {
		if (!HongKongTaxiScoringParameters.TAXI_MODE.equals(event.getMode())) return;
		for (Id<Person> personId : event.getPersonIds()) {
			Person person = scenario.getPopulation().getPersons().get(personId);
			if (person == null || isShadow(person)) continue;
			List<Integer> legIndices = parentTaxiLegIndices.get(personId);
			if (legIndices == null) {
				throw new IllegalStateException("Taxi request parent has no selected Taxi leg: " + personId);
			}
			int ordinal = parentSubmissionOrdinals
					.computeIfAbsent(personId, ignored -> new AtomicInteger()).getAndIncrement();
			if (ordinal >= legIndices.size()) {
				throw new IllegalStateException("More Taxi requests than selected Taxi legs: " + personId);
			}
			ParentKey key = new ParentKey(personId.toString(), legIndices.get(ordinal));
			if (parentSubmissionTimes.putIfAbsent(key, event.getTime()) != null) {
				throw new IllegalStateException("Duplicate operational Taxi parent trigger: " + key);
			}
			parentSubmissions.incrementAndGet();
			ConcurrentLinkedQueue<Id<Person>> waiting = heldByParent.get(key);
			if (waiting == null) continue;
			for (Id<Person> shadowId : waiting) {
				Held held = heldByAgent.get(shadowId);
				if (held != null) schedule(held, event.getTime() + held.delay);
			}
		}
	}

	private void schedule(Held held, double due) {
		if (held.scheduled.compareAndSet(false, true)) {
			inbound.add(new Scheduled(held, due, sequence.getAndIncrement()));
		}
	}

	@Override
	public void doSimStep(double now) {
		for (Scheduled value; (value = inbound.poll()) != null;) scheduled.add(value);
		while (!scheduled.isEmpty() && scheduled.peek().due() <= now) {
			Scheduled value = scheduled.poll();
			Held held = value.held();
			if (!heldByAgent.remove(held.agent.getId(), held)) continue;
			released.add(held.agent.getId());
			releasedDepartures.incrementAndGet();
			// This external QSim callback is deliberately outside all maps/queues locks.
			internalInterface.arrangeNextAgentState(held.agent);
		}
	}

	@Override
	public void beforeMobsim() {
		parentSubmissionOrdinals.clear();
		parentSubmissionTimes.clear();
		heldByParent.clear();
		heldByAgent.clear();
		released.clear();
		inbound.clear();
		scheduled.clear();
		parentSubmissions.set(0);
		heldDepartures.set(0);
		releasedDepartures.set(0);
		events.addHandler(this);
	}

	@Override
	public void afterMobsim() {
		events.removeHandler(this);
		writeAudit();
	}

	private void writeAudit() {
		String filename = output.getOutputFilename("taxi_operational_gate_summary.csv");
		try (BufferedWriter writer = IOUtils.getBufferedWriter(filename)) {
			writer.write("parent_submissions,shadow_departures_held,shadow_departures_released,"
					+ "shadow_departures_unreleased,parent_triggers_without_shadows\n");
			long unreleased = heldByAgent.size();
			long triggersWithoutShadows = parentSubmissionTimes.keySet().stream()
					.filter(key -> !heldByParent.containsKey(key)).count();
			writer.write(parentSubmissions.get() + "," + heldDepartures.get() + ","
					+ releasedDepartures.get() + "," + unreleased + ","
					+ triggersWithoutShadows + "\n");
		} catch (IOException error) {
			throw new IllegalStateException("Cannot write operational Taxi gate audit", error);
		}
	}

	@Override
	public void setInternalInterface(InternalInterface internalInterface) {
		this.internalInterface = internalInterface;
	}

	@Override
	public void reset(int iteration) {
		// The handler is installed at beforeMobsim, after EventsManager reset.
	}

	private static ParentKey parentKey(Person person) {
		Object parent = person.getAttributes().getAttribute(PARENT_ATTRIBUTE);
		Object legIndex = person.getAttributes().getAttribute(PARENT_LEG_ATTRIBUTE);
		if (parent == null || legIndex == null) {
			throw new IllegalStateException("Operational Taxi shadow lacks parent identity: "
					+ person.getId());
		}
		return new ParentKey(parent.toString(), Integer.parseInt(legIndex.toString()));
	}

	private static double number(Person person, String attribute) {
		Object raw = person.getAttributes().getAttribute(attribute);
		if (raw == null) throw new IllegalStateException(
				"Operational Taxi shadow lacks " + attribute + ": " + person.getId());
		double value = Double.parseDouble(raw.toString());
		if (!Double.isFinite(value) || value < 0 || value >= 900) {
			throw new IllegalStateException("Illegal operational Taxi release delay: " + value);
		}
		return value;
	}

	public static boolean isShadow(Person person) {
		Object raw = person.getAttributes().getAttribute(SHADOW_ATTRIBUTE);
		return raw instanceof Boolean value ? value : Boolean.parseBoolean(String.valueOf(raw));
	}
}
