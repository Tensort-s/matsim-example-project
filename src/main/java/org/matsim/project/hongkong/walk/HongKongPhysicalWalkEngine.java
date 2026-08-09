package org.matsim.project.hongkong.walk;

import com.google.inject.Inject;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.api.core.v01.events.PersonStuckEvent;
import org.matsim.api.core.v01.network.Link;
import org.matsim.core.api.experimental.events.EventsManager;
import org.matsim.core.mobsim.framework.MobsimAgent;
import org.matsim.core.mobsim.framework.PlanAgent;
import org.matsim.core.mobsim.qsim.InternalInterface;
import org.matsim.core.mobsim.qsim.interfaces.DepartureHandler;
import org.matsim.core.mobsim.qsim.interfaces.MobsimEngine;
import org.matsim.core.population.routes.NetworkRoute;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.PriorityQueue;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Advances Walk agents over real network routes without placing pseudo vehicles
 * in the road queue. Link traversal is observable through person-level events,
 * while road flow and storage capacity remain unaffected.
 */
public final class HongKongPhysicalWalkEngine implements MobsimEngine, DepartureHandler {

	private record WalkState(
			MobsimAgent agent,
			List<Id<Link>> traversedLinks,
			int currentIndex,
			double nextTransitionTime,
			long sequence) {
	}

	private static final Comparator<WalkState> ORDER = Comparator
			.comparingDouble(WalkState::nextTransitionTime)
			.thenComparingLong(WalkState::sequence);

	private final Scenario scenario;
	private final EventsManager events;
	private final PriorityQueue<WalkState> active = new PriorityQueue<>(ORDER);
	private final AtomicLong sequence = new AtomicLong();
	private long departures;
	private long arrivals;
	private long linkEnters;
	private long linkLeaves;
	private long peakConcurrent;
	private InternalInterface internalInterface;

	@Inject
	public HongKongPhysicalWalkEngine(Scenario scenario, EventsManager events) {
		this.scenario = scenario;
		this.events = events;
	}

	@Override
	public boolean handleDeparture(double now, MobsimAgent agent, Id<Link> fromLinkId) {
		if (!TransportMode.walk.equals(agent.getMode())) {
			return false;
		}
		if (!(agent instanceof PlanAgent planAgent)
				|| !(planAgent.getCurrentPlanElement() instanceof org.matsim.api.core.v01.population.Leg leg)) {
			throw new IllegalStateException("Walk agent is not backed by a current plan leg: person="
					+ agent.getId());
		}
		if (!(leg.getRoute() instanceof NetworkRoute route)) {
			// Legacy auxiliary access/egress legs can still carry a generic route.
			// The physical engine owns every Walk NetworkRoute, including those
			// generated inside a PT or car trip, and delegates only non-network legs.
			return false;
		}
		if (!route.getStartLinkId().equals(fromLinkId)
				|| !route.getEndLinkId().equals(agent.getDestinationLinkId())) {
			throw new IllegalStateException("Physical Walk route endpoints disagree with the agent: person="
					+ agent.getId() + ", route=" + route.getStartLinkId() + "->"
					+ route.getEndLinkId() + ", agent=" + fromLinkId + "->"
					+ agent.getDestinationLinkId());
		}
		departures++;
		List<Id<Link>> traversed = traversedLinks(route);
		if (traversed.isEmpty()) {
			finish(agent, now);
			return true;
		}
		Id<Link> first = traversed.getFirst();
		emit(now, PhysicalWalkLinkEvent.ENTER_TYPE, agent, first);
		active.add(new WalkState(agent, traversed, 0,
				now + linkTravelTime(first), sequence.getAndIncrement()));
		peakConcurrent = Math.max(peakConcurrent, active.size());
		return true;
	}

	static List<Id<Link>> traversedLinks(NetworkRoute route) {
		if (route.getStartLinkId().equals(route.getEndLinkId()) && route.getLinkIds().isEmpty()) {
			return List.of();
		}
		List<Id<Link>> result = new ArrayList<>(route.getLinkIds());
		if (result.isEmpty() || !result.getLast().equals(route.getEndLinkId())) {
			result.add(route.getEndLinkId());
		}
		return List.copyOf(result);
	}

	private double linkTravelTime(Id<Link> linkId) {
		Link link = scenario.getNetwork().getLinks().get(linkId);
		if (link == null || !link.getAllowedModes().contains(TransportMode.walk)) {
			throw new IllegalStateException("Physical Walk route uses a missing/non-Walk link: " + linkId);
		}
		return Math.max(1.0, link.getLength() / HongKongPhysicalWalkModule.WALK_SPEED_M_S);
	}

	@Override
	public void doSimStep(double now) {
		while (!active.isEmpty() && active.peek().nextTransitionTime() <= now) {
			WalkState state = active.poll();
			Id<Link> current = state.traversedLinks().get(state.currentIndex());
			emit(now, PhysicalWalkLinkEvent.LEAVE_TYPE, state.agent(), current);
			int nextIndex = state.currentIndex() + 1;
			if (nextIndex == state.traversedLinks().size()) {
				finish(state.agent(), now);
				continue;
			}
			Id<Link> next = state.traversedLinks().get(nextIndex);
			emit(now, PhysicalWalkLinkEvent.ENTER_TYPE, state.agent(), next);
			// Keep the continuous route clock used by routing. Anchoring every link
			// to integer QSim 'now' would accumulate up to one rounding second per link.
			active.add(new WalkState(state.agent(), state.traversedLinks(), nextIndex,
					state.nextTransitionTime() + linkTravelTime(next), sequence.getAndIncrement()));
		}
	}

	private void emit(double now, String type, MobsimAgent agent, Id<Link> linkId) {
		events.processEvent(new PhysicalWalkLinkEvent(now, type, agent.getId(), linkId));
		if (PhysicalWalkLinkEvent.ENTER_TYPE.equals(type)) linkEnters++;
		else linkLeaves++;
	}

	private void finish(MobsimAgent agent, double now) {
		agent.notifyArrivalOnLinkByNonNetworkMode(agent.getDestinationLinkId());
		agent.endLegAndComputeNextState(now);
		internalInterface.arrangeNextAgentState(agent);
		arrivals++;
	}

	@Override
	public void beforeMobsim() {
		active.clear();
		departures = 0;
		arrivals = 0;
		linkEnters = 0;
		linkLeaves = 0;
		peakConcurrent = 0;
	}

	@Override
	public void afterMobsim() {
		double now = internalInterface.getMobsim().getSimTimer().getTimeOfDay();
		for (WalkState state : active) {
			events.processEvent(new PersonStuckEvent(now, state.agent().getId(),
					state.agent().getCurrentLinkId(), TransportMode.walk));
		}
		System.out.printf("Physical Walk engine: departures=%,d; arrivals=%,d; stuck=%,d; "
				+ "link-enters=%,d; link-leaves=%,d; peak-concurrent=%,d.%n",
				departures, arrivals, active.size(), linkEnters, linkLeaves, peakConcurrent);
		active.clear();
	}

	@Override
	public void setInternalInterface(InternalInterface internalInterface) {
		this.internalInterface = internalInterface;
	}
}
