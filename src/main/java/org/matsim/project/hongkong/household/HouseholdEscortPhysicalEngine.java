package org.matsim.project.hongkong.household;

import com.google.inject.Inject;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.events.PersonArrivalEvent;
import org.matsim.api.core.v01.events.PersonEntersVehicleEvent;
import org.matsim.api.core.v01.events.PersonLeavesVehicleEvent;
import org.matsim.api.core.v01.events.PersonStuckEvent;
import org.matsim.api.core.v01.events.LinkEnterEvent;
import org.matsim.api.core.v01.events.VehicleEntersTrafficEvent;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.api.experimental.events.EventsManager;
import org.matsim.core.mobsim.framework.MobsimAgent;
import org.matsim.core.mobsim.framework.MobsimDriverAgent;
import org.matsim.core.mobsim.framework.MobsimPassengerAgent;
import org.matsim.core.mobsim.framework.PlanAgent;
import org.matsim.core.mobsim.qsim.InternalInterface;
import org.matsim.core.mobsim.qsim.QSim;
import org.matsim.core.mobsim.qsim.interfaces.DepartureHandler;
import org.matsim.core.mobsim.qsim.interfaces.MobsimEngine;
import org.matsim.core.mobsim.qsim.interfaces.MobsimVehicle;
import org.matsim.core.mobsim.qsim.interfaces.Netsim;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Boards fixed school passengers into their household driver's actual QVehicle. */
public final class HouseholdEscortPhysicalEngine implements MobsimEngine, DepartureHandler,
		HouseholdEscortPhysicalEventSink {

	private static final Logger LOG = LogManager.getLogger(HouseholdEscortPhysicalEngine.class);

	private record Waiting(
			HouseholdEscortBindingCatalog.Binding binding,
			MobsimPassengerAgent passenger,
			Id<Link> registeredLinkId) {
	}

	private record Onboard(
			HouseholdEscortBindingCatalog.Binding binding,
			MobsimPassengerAgent passenger,
			MobsimVehicle vehicle) {
	}

	private record VehicleWaypoint(
			Id<org.matsim.vehicles.Vehicle> vehicleId,
			Id<Link> linkId) {
	}

	private final HouseholdEscortBindingCatalog catalog;
	private final EventsManager events;
	private final QSim qsim;
	private final Map<String, Waiting> waiting = new LinkedHashMap<>();
	private final Map<String, Onboard> onboard = new LinkedHashMap<>();
	private final Map<String, String> terminalOutcomes = new LinkedHashMap<>();
	private final Map<VehicleWaypoint, LinkedHashSet<String>> waitingAtWaypoint = new LinkedHashMap<>();
	private final Map<VehicleWaypoint, LinkedHashSet<String>> onboardAtWaypoint = new LinkedHashMap<>();
	private volatile Set<VehicleWaypoint> activeWaypoints = Set.of();
	private volatile Set<Id<Person>> activeDriverIds = Set.of();
	private volatile Set<Id<Person>> activePassengerIds = Set.of();
	private InternalInterface internalInterface;
	private int departures;
	private int boardings;
	private int alightings;

	@Inject
	public HouseholdEscortPhysicalEngine(
			HouseholdEscortBindingCatalog catalog,
			EventsManager events,
			Netsim netsim) {
		this.catalog = catalog;
		this.events = events;
		if (!(netsim instanceof QSim concreteQSim)) {
			throw new IllegalArgumentException("Household escort physical pilot requires QSim");
		}
		this.qsim = concreteQSim;
	}

	@Override
	public boolean handleDeparture(double now, MobsimAgent agent, Id<Link> fromLinkId) {
		if (!"car_passenger".equals(agent.getMode()) || !(agent instanceof PlanAgent planAgent)
				|| !(planAgent.getCurrentPlanElement() instanceof Leg leg)) {
			return false;
		}
		Object persistentKey = leg.getAttributes().getAttribute(
				HouseholdEscortBindingCatalog.BINDING_KEY_ATTRIBUTE);
		HouseholdEscortBindingCatalog.Binding binding = persistentKey == null
				? catalog.activeBindingForPassengerLeg(agent.getId(), currentLegIndex(planAgent))
				: catalog.activeBindingForKey(persistentKey.toString());
		if (binding == null) {
			if (catalog.activeBindingCount() > 0) {
				throw new IllegalStateException("Unbound car_passenger departure after household "
						+ "selection: person=" + agent.getId() + ", leg=" + currentLegIndex(planAgent));
			}
			// Iteration 0 deliberately executes the untouched baseline before the
			// one-shot household selector establishes the physical binding catalog.
			return false;
		}
		if (!(agent instanceof MobsimPassengerAgent passenger)) {
			throw new IllegalStateException("Bound passenger is not a MobsimPassengerAgent: " + agent.getId());
		}
		if (!binding.passengerPickupLinkId().equals(fromLinkId)) {
			throw new IllegalStateException("Bound passenger did not depart at the pickup waypoint: " + key(binding));
		}
		synchronized (this) {
			String key = key(binding);
			if (waiting.containsKey(key) || onboard.containsKey(key)) {
				throw new IllegalStateException("Duplicate bound passenger departure: " + key);
			}
			internalInterface.registerAdditionalAgentOnLink(passenger);
			waiting.put(key, new Waiting(binding, passenger, fromLinkId));
			addIndex(waitingAtWaypoint, pickupWaypoint(binding), key);
			departures++;
		}
		return true;
	}

	@Override
	public void doSimStep(double now) {
		// Boarding and alighting are driven by exact vehicle-link events.
	}

	@Override
	public void onVehicleEntersTraffic(VehicleEntersTrafficEvent event) {
		handleVehicleAtWaypoint(event.getTime(), event.getVehicleId(), event.getLinkId());
	}

	@Override
	public void onLinkEnter(LinkEnterEvent event) {
		handleVehicleAtWaypoint(event.getTime(), event.getVehicleId(), event.getLinkId());
	}

	@Override
	public void onPersonArrival(PersonArrivalEvent event) {
		if (!"car".equals(event.getLegMode()) || !activeDriverIds.contains(event.getPersonId())) {
			return;
		}
		List<VehicleWaypoint> terminalDropoffs;
		synchronized (this) {
			terminalDropoffs = onboard.values().stream()
					.map(Onboard::binding)
					.filter(binding -> binding.driverId().equals(event.getPersonId()))
					.filter(binding -> binding.passengerDropoffLinkId().equals(event.getLinkId()))
					.map(HouseholdEscortPhysicalEngine::dropoffWaypoint)
					.distinct()
					.toList();
		}
		// A QNetwork leg may reach its destination link without a final LinkEnter
		// callback.  PersonArrival is therefore the physical terminal waypoint
		// fallback, not evidence by itself that the passenger was missed.
		for (VehicleWaypoint waypoint : terminalDropoffs) {
			handleVehicleAtWaypoint(event.getTime(), waypoint.vehicleId(), waypoint.linkId());
		}
		// SimStepParallelEventsManager may deliver this arrival to our handler
		// before an earlier LinkEnter for the same vehicle has been processed on
		// another event thread. Do not turn that legal reordering into a false
		// abort. The selected/restored route is validated to contain every active
		// waypoint; the delayed LinkEnter completes the physical alighting, while
		// any genuinely outstanding passenger is classified after all events have
		// drained in afterMobsim().
	}

	private void handleVehicleAtWaypoint(
			double now, Id<org.matsim.vehicles.Vehicle> vehicleId, Id<Link> linkId) {
		VehicleWaypoint waypoint = new VehicleWaypoint(vehicleId, linkId);
		if (!activeWaypoints.contains(waypoint)) {
			return;
		}
		List<Map.Entry<String, Onboard>> dropoffs = new ArrayList<>();
		List<Map.Entry<String, Waiting>> pickupCandidates = new ArrayList<>();
		synchronized (this) {
			for (String key : indexedKeys(onboardAtWaypoint, waypoint)) {
				Onboard ride = onboard.remove(key);
				removeIndex(onboardAtWaypoint, waypoint, key);
				if (ride != null) dropoffs.add(Map.entry(key, ride));
			}
			for (String key : indexedKeys(waitingAtWaypoint, waypoint)) {
				Waiting candidate = waiting.get(key);
				if (candidate != null) pickupCandidates.add(Map.entry(key, candidate));
			}
		}

		// Never call back into QSim while holding this engine's monitor. QSim's
		// main thread invokes departure handlers while holding its own agent-state
		// monitor, whereas event delivery runs on a separate thread.
		for (var entry : dropoffs) {
			String key = entry.getKey();
			Onboard ride = entry.getValue();
			if (!ride.vehicle().removePassenger(ride.passenger())) {
				throw new IllegalStateException("Bound passenger is absent from vehicle at drop-off: "
						+ ride.passenger().getId());
			}
			ride.passenger().setVehicle(null);
			events.processEvent(new PersonLeavesVehicleEvent(now, ride.passenger().getId(), vehicleId));
			ride.passenger().notifyArrivalOnLinkByNonNetworkMode(linkId);
			ride.passenger().endLegAndComputeNextState(now);
			internalInterface.arrangeNextAgentState(ride.passenger());
			synchronized (this) {
				terminalOutcomes.put(key, "completed_physical_ride");
				alightings++;
			}
		}

		for (var entry : pickupCandidates) {
			String key = entry.getKey();
			Waiting candidate = entry.getValue();
			if (!isBoundDriverLegActive(candidate.binding())) continue;
			synchronized (this) {
				if (waiting.get(key) != candidate) continue;
				waiting.remove(key);
				removeIndex(waitingAtWaypoint, waypoint, key);
			}
			MobsimAgent driverAgent = qsim.getAgents().get(candidate.binding().driverId());
			MobsimDriverAgent driver = (MobsimDriverAgent) driverAgent;
			MobsimVehicle vehicle = driver.getVehicle();
			if (vehicle == null || !vehicle.getId().equals(vehicleId)) {
				throw new IllegalStateException("Bound vehicle is unavailable at pickup waypoint: " + key);
			}
			if (vehicle.getPassengers().size() >= vehicle.getPassengerCapacity()) {
				throw new IllegalStateException("Bound private car is full: " + vehicle.getId());
			}
			MobsimAgent removed = internalInterface.unregisterAdditionalAgentOnLink(
					candidate.passenger().getId(), candidate.registeredLinkId());
			if (removed == null || !vehicle.addPassenger(candidate.passenger())) {
				throw new IllegalStateException("Cannot board passenger at the exact pickup waypoint: " + key);
			}
			candidate.passenger().setVehicle(vehicle);
			events.processEvent(new PersonEntersVehicleEvent(now, candidate.passenger().getId(), vehicleId));
			synchronized (this) {
				onboard.put(key, new Onboard(candidate.binding(), candidate.passenger(), vehicle));
				addIndex(onboardAtWaypoint, dropoffWaypoint(candidate.binding()), key);
				boardings++;
			}
		}
	}

	private boolean isBoundDriverLegActive(HouseholdEscortBindingCatalog.Binding binding) {
		MobsimAgent driverAgent = qsim.getAgents().get(binding.driverId());
		return driverAgent instanceof MobsimDriverAgent
				&& driverAgent instanceof PlanAgent planAgent
				&& planAgent.getCurrentPlanElement() instanceof Leg
				&& currentLegIndex(planAgent) == binding.driverLegIndex();
	}

	@Override
	public void onPersonStuck(PersonStuckEvent event) {
		if (!activeDriverIds.contains(event.getPersonId()) && !activePassengerIds.contains(event.getPersonId())) {
			return;
		}
		List<Waiting> abortedWaiting = new ArrayList<>();
		synchronized (this) {
		List<String> onboardFailures = onboard.entrySet().stream()
				.filter(entry -> entry.getValue().passenger().getId().equals(event.getPersonId()))
				.map(Map.Entry::getKey)
				.toList();
		for (String key : onboardFailures) {
			Onboard failed = onboard.remove(key);
			removeIndex(onboardAtWaypoint, dropoffWaypoint(failed.binding()), key);
			terminalOutcomes.putIfAbsent(key, "passenger_stuck_while_onboard");
		}

		List<String> waitingFailures = waiting.entrySet().stream()
				.filter(entry -> entry.getValue().binding().driverId().equals(event.getPersonId()))
				.map(Map.Entry::getKey)
				.toList();
		for (String key : waitingFailures) {
			Waiting failed = waiting.remove(key);
			removeIndex(waitingAtWaypoint, pickupWaypoint(failed.binding()), key);
			terminalOutcomes.put(key, "driver_stuck_before_pickup");
			abortedWaiting.add(failed);
		}
		}
		for (Waiting failed : abortedWaiting) {
			MobsimAgent removed = internalInterface.unregisterAdditionalAgentOnLink(
					failed.passenger().getId(), failed.registeredLinkId());
			if (removed == null) {
				throw new IllegalStateException("Cannot abort waiting passenger after driver stuck: "
						+ key(failed.binding()));
			}
			failed.passenger().setStateToAbort(event.getTime());
			internalInterface.arrangeNextAgentState(failed.passenger());
		}
	}

	@Override
	public synchronized void beforeMobsim() {
		waiting.clear();
		onboard.clear();
		terminalOutcomes.clear();
		waitingAtWaypoint.clear();
		onboardAtWaypoint.clear();
		activeWaypoints = catalog.bindings().stream()
				.filter(catalog::isActive)
				.flatMap(binding -> java.util.stream.Stream.of(
						pickupWaypoint(binding), dropoffWaypoint(binding)))
				.collect(java.util.stream.Collectors.toUnmodifiableSet());
		activeDriverIds = catalog.bindings().stream()
				.filter(catalog::isActive)
				.map(HouseholdEscortBindingCatalog.Binding::driverId)
				.collect(java.util.stream.Collectors.toUnmodifiableSet());
		activePassengerIds = catalog.bindings().stream()
				.filter(catalog::isActive)
				.map(HouseholdEscortBindingCatalog.Binding::passengerId)
				.collect(java.util.stream.Collectors.toUnmodifiableSet());
		departures = 0;
		boardings = 0;
		alightings = 0;
	}

	@Override
	public synchronized void afterMobsim() {
		int expected = catalog.activeBindingCount();
		int simulationEndBeforePickup = waiting.size();
		for (var entry : waiting.entrySet()) {
			terminalOutcomes.putIfAbsent(entry.getKey(), "simulation_end_before_pickup");
		}
		waiting.clear();
		waitingAtWaypoint.clear();
		int simulationEndWhileOnboard = onboard.size();
		for (var entry : onboard.entrySet()) {
			terminalOutcomes.putIfAbsent(entry.getKey(), "simulation_end_while_onboard");
		}
		onboard.clear();
		onboardAtWaypoint.clear();
		var passengersWithFailure = terminalOutcomes.entrySet().stream()
				.filter(entry -> !"completed_physical_ride".equals(entry.getValue()))
				.map(entry -> entry.getKey().substring(0, entry.getKey().lastIndexOf('/')))
				.collect(java.util.stream.Collectors.toSet());
		for (HouseholdEscortBindingCatalog.Binding binding : catalog.bindings()) {
			if (!catalog.isActive(binding)) continue;
			String key = key(binding);
			if (!terminalOutcomes.containsKey(key)
					&& passengersWithFailure.contains(binding.passengerId().toString())) {
				terminalOutcomes.put(key, "skipped_after_prior_bound_failure");
			}
		}
		for (HouseholdEscortBindingCatalog.Binding binding : catalog.bindings()) {
			if (!catalog.isActive(binding)) continue;
			terminalOutcomes.putIfAbsent(key(binding), "simulation_end_before_bound_departure");
		}
		long completed = outcomeCount("completed_physical_ride");
		long onboardStuck = outcomeCount("passenger_stuck_while_onboard");
		long pickupStuck = outcomeCount("driver_stuck_before_pickup");
		long downstreamSkipped = outcomeCount("skipped_after_prior_bound_failure");
		long beforeDeparture = outcomeCount("simulation_end_before_bound_departure");
		LOG.info("Household school-escort physical pilot: departures={}, boardings={}, alightings={}, "
				+ "completed={}, passenger_stuck_onboard={}, driver_stuck_before_pickup={}, "
				+ "skipped_after_prior_failure={}, waiting={}, onboard={}, classified={}, "
				+ "simulation_end_before_pickup={}, simulation_end_while_onboard={}, "
				+ "simulation_end_before_bound_departure={}",
				departures, boardings, alightings, completed, onboardStuck, pickupStuck,
				downstreamSkipped, waiting.size(), onboard.size(), terminalOutcomes.size(),
				simulationEndBeforePickup, simulationEndWhileOnboard, beforeDeparture);
		if (terminalOutcomes.size() != expected || !waiting.isEmpty() || !onboard.isEmpty()) {
			List<String> unclassified = catalog.bindings().stream()
					.filter(catalog::isActive)
					.map(HouseholdEscortPhysicalEngine::key)
					.filter(key -> !terminalOutcomes.containsKey(key))
					.toList();
			throw new IllegalStateException("Unclassified household escort physical pilot outcomes: expected="
					+ expected + ", classified=" + terminalOutcomes.size()
					+ ", waiting=" + waiting.size() + ", onboard=" + onboard.size()
					+ ", unclassified=" + unclassified);
		}
	}

	@Override
	public void setInternalInterface(InternalInterface internalInterface) {
		this.internalInterface = internalInterface;
	}

	@Override
	public void reset(int iteration) {
		// QSim creates a new engine per iteration; beforeMobsim owns its counters.
	}

	@Override
	public void cleanupAfterMobsim(int iteration) {
		// No external resources are retained.
	}

	private static String key(HouseholdEscortBindingCatalog.Binding binding) {
		return binding.passengerId() + "/" + binding.passengerLegIndex();
	}

	private static VehicleWaypoint pickupWaypoint(HouseholdEscortBindingCatalog.Binding binding) {
		return new VehicleWaypoint(binding.vehicleId(), binding.passengerPickupLinkId());
	}

	private static VehicleWaypoint dropoffWaypoint(HouseholdEscortBindingCatalog.Binding binding) {
		return new VehicleWaypoint(binding.vehicleId(), binding.passengerDropoffLinkId());
	}

	private static void addIndex(
			Map<VehicleWaypoint, LinkedHashSet<String>> index, VehicleWaypoint waypoint, String key) {
		index.computeIfAbsent(waypoint, ignored -> new LinkedHashSet<>()).add(key);
	}

	private static void removeIndex(
			Map<VehicleWaypoint, LinkedHashSet<String>> index, VehicleWaypoint waypoint, String key) {
		LinkedHashSet<String> keys = index.get(waypoint);
		if (keys == null) return;
		keys.remove(key);
		if (keys.isEmpty()) index.remove(waypoint);
	}

	private static List<String> indexedKeys(
			Map<VehicleWaypoint, LinkedHashSet<String>> index, VehicleWaypoint waypoint) {
		LinkedHashSet<String> keys = index.get(waypoint);
		return keys == null ? List.of() : List.copyOf(keys);
	}

	private long outcomeCount(String outcome) {
		return terminalOutcomes.values().stream().filter(outcome::equals).count();
	}

	private static int currentLegIndex(PlanAgent planAgent) {
		int legIndex = 0;
		for (var element : planAgent.getCurrentPlan().getPlanElements()) {
			if (element == planAgent.getCurrentPlanElement()) {
				if (!(element instanceof Leg)) {
					throw new IllegalStateException("Current plan element is not a leg");
				}
				return legIndex;
			}
			if (element instanceof Leg) {
				legIndex++;
			}
		}
		throw new IllegalStateException("Current leg is absent from the current plan for "
				+ planAgent.getCurrentPlan().getPerson().getId());
	}
}
