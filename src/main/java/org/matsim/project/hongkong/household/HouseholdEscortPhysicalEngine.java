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
import org.matsim.api.core.v01.events.handler.LinkEnterEventHandler;
import org.matsim.api.core.v01.events.handler.PersonArrivalEventHandler;
import org.matsim.api.core.v01.events.handler.PersonStuckEventHandler;
import org.matsim.api.core.v01.events.handler.VehicleEntersTrafficEventHandler;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.api.experimental.events.EventsManager;
import org.matsim.core.events.MobsimScopeEventHandler;
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

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Boards fixed school passengers into their household driver's actual QVehicle. */
public final class HouseholdEscortPhysicalEngine implements MobsimEngine, DepartureHandler,
		PersonArrivalEventHandler, PersonStuckEventHandler, LinkEnterEventHandler,
		VehicleEntersTrafficEventHandler, MobsimScopeEventHandler {

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

	private final HouseholdEscortBindingCatalog catalog;
	private final EventsManager events;
	private final QSim qsim;
	private final Map<String, Waiting> waiting = new LinkedHashMap<>();
	private final Map<String, Onboard> onboard = new LinkedHashMap<>();
	private final Map<String, String> terminalOutcomes = new LinkedHashMap<>();
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
			return false;
		}
		if (!(agent instanceof MobsimPassengerAgent passenger)) {
			throw new IllegalStateException("Bound passenger is not a MobsimPassengerAgent: " + agent.getId());
		}
		if (!binding.passengerPickupLinkId().equals(fromLinkId)) {
			throw new IllegalStateException("Bound passenger did not depart at the pickup waypoint: " + key(binding));
		}
		String key = key(binding);
		if (waiting.containsKey(key) || onboard.containsKey(key)) {
			throw new IllegalStateException("Duplicate bound passenger departure: " + key);
		}
		internalInterface.registerAdditionalAgentOnLink(passenger);
		waiting.put(key, new Waiting(binding, passenger, fromLinkId));
		departures++;
		return true;
	}

	@Override
	public void doSimStep(double now) {
		// Boarding and alighting are driven by exact vehicle-link events.
	}

	@Override
	public void handleEvent(VehicleEntersTrafficEvent event) {
		handleVehicleAtWaypoint(event.getTime(), event.getVehicleId(), event.getLinkId());
	}

	@Override
	public void handleEvent(LinkEnterEvent event) {
		handleVehicleAtWaypoint(event.getTime(), event.getVehicleId(), event.getLinkId());
	}

	@Override
	public void handleEvent(PersonArrivalEvent event) {
		if (!"car".equals(event.getLegMode()) || onboard.isEmpty()) {
			return;
		}
		List<String> missed = onboard.entrySet().stream()
				.filter(entry -> entry.getValue().binding().driverId().equals(event.getPersonId()))
				.map(Map.Entry::getKey)
				.toList();
		if (!missed.isEmpty()) {
			throw new IllegalStateException("Driver arrived before bound passenger drop-off waypoint: " + missed);
		}
	}

	private void handleVehicleAtWaypoint(double now, Id<org.matsim.vehicles.Vehicle> vehicleId, Id<Link> linkId) {
		List<String> completed = onboard.entrySet().stream()
				.filter(entry -> entry.getValue().vehicle().getId().equals(vehicleId)
						&& entry.getValue().binding().passengerDropoffLinkId().equals(linkId))
				.map(Map.Entry::getKey)
				.toList();
		for (String key : completed) {
			Onboard ride = onboard.remove(key);
			if (!ride.vehicle().removePassenger(ride.passenger())) {
				throw new IllegalStateException("Bound passenger is absent from vehicle at drop-off: "
						+ ride.passenger().getId());
			}
			ride.passenger().setVehicle(null);
			events.processEvent(new PersonLeavesVehicleEvent(now, ride.passenger().getId(), vehicleId));
			ride.passenger().notifyArrivalOnLinkByNonNetworkMode(linkId);
			ride.passenger().endLegAndComputeNextState(now);
			internalInterface.arrangeNextAgentState(ride.passenger());
			terminalOutcomes.put(key, "completed_physical_ride");
			alightings++;
		}

		List<String> pickups = waiting.entrySet().stream()
				.filter(entry -> entry.getValue().binding().vehicleId().equals(vehicleId)
						&& entry.getValue().binding().passengerPickupLinkId().equals(linkId)
						&& isBoundDriverLegActive(entry.getValue().binding()))
				.map(Map.Entry::getKey)
				.toList();
		for (String key : pickups) {
			Waiting candidate = waiting.remove(key);
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
			onboard.put(key, new Onboard(candidate.binding(), candidate.passenger(), vehicle));
			boardings++;
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
	public void handleEvent(PersonStuckEvent event) {
		List<String> onboardFailures = onboard.entrySet().stream()
				.filter(entry -> entry.getValue().passenger().getId().equals(event.getPersonId()))
				.map(Map.Entry::getKey)
				.toList();
		for (String key : onboardFailures) {
			onboard.remove(key);
			terminalOutcomes.putIfAbsent(key, "passenger_stuck_while_onboard");
		}

		List<String> waitingFailures = waiting.entrySet().stream()
				.filter(entry -> entry.getValue().binding().driverId().equals(event.getPersonId()))
				.map(Map.Entry::getKey)
				.toList();
		for (String key : waitingFailures) {
			Waiting failed = waiting.remove(key);
			MobsimAgent removed = internalInterface.unregisterAdditionalAgentOnLink(
					failed.passenger().getId(), failed.registeredLinkId());
			if (removed == null) {
				throw new IllegalStateException("Cannot abort waiting passenger after driver stuck: " + key);
			}
			terminalOutcomes.put(key, "driver_stuck_before_pickup");
			failed.passenger().setStateToAbort(event.getTime());
			internalInterface.arrangeNextAgentState(failed.passenger());
		}
	}

	@Override
	public void beforeMobsim() {
		waiting.clear();
		onboard.clear();
		terminalOutcomes.clear();
		departures = 0;
		boardings = 0;
		alightings = 0;
	}

	@Override
	public void afterMobsim() {
		int expected = catalog.activeBindingCount();
		int simulationEndBeforePickup = waiting.size();
		for (var entry : waiting.entrySet()) {
			terminalOutcomes.putIfAbsent(entry.getKey(), "simulation_end_before_pickup");
		}
		waiting.clear();
		int simulationEndWhileOnboard = onboard.size();
		for (var entry : onboard.entrySet()) {
			terminalOutcomes.putIfAbsent(entry.getKey(), "simulation_end_while_onboard");
		}
		onboard.clear();
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
		long completed = outcomeCount("completed_physical_ride");
		long onboardStuck = outcomeCount("passenger_stuck_while_onboard");
		long pickupStuck = outcomeCount("driver_stuck_before_pickup");
		long downstreamSkipped = outcomeCount("skipped_after_prior_bound_failure");
		LOG.info("Household school-escort physical pilot: departures={}, boardings={}, alightings={}, "
				+ "completed={}, passenger_stuck_onboard={}, driver_stuck_before_pickup={}, "
				+ "skipped_after_prior_failure={}, waiting={}, onboard={}, classified={}, "
				+ "simulation_end_before_pickup={}, simulation_end_while_onboard={}",
				departures, boardings, alightings, completed, onboardStuck, pickupStuck,
				downstreamSkipped, waiting.size(), onboard.size(), terminalOutcomes.size(),
				simulationEndBeforePickup, simulationEndWhileOnboard);
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
