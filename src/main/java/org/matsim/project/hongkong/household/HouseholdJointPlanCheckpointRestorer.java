package org.matsim.project.hongkong.household;

import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.core.population.routes.NetworkRoute;
import org.matsim.core.router.TripStructureUtils;
import org.matsim.vehicles.Vehicle;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/** Restores frozen physical household bindings from a saved selected-plan checkpoint. */
public final class HouseholdJointPlanCheckpointRestorer {

	private HouseholdJointPlanCheckpointRestorer() { }

	public static int restore(
			Scenario scenario,
			HouseholdJointPlanCandidateCatalog candidates,
			HouseholdEscortBindingCatalog bindings,
			int expectedBindings) {
		if (expectedBindings <= 0) {
			throw new IllegalArgumentException("Expected restored household bindings must be positive");
		}
		List<HouseholdEscortBindingCatalog.Binding> restored = new ArrayList<>();
		Set<String> observedBindingKeys = new HashSet<>();
		Set<String> restoredBindingKeys = new HashSet<>();
		for (HouseholdJointPlanCandidateCatalog.Candidate candidate : candidates.candidates()) {
			Person passenger = requiredPerson(scenario, candidate.passengerPersonId());
			TripStructureUtils.Trip passengerTrip = selectedTrip(
					passenger, candidate.passengerTripIndex());
			List<Leg> passengerLegs = legs(passengerTrip);
			if (passengerLegs.size() != 1
					|| !"car_passenger".equals(passengerLegs.getFirst().getMode())) continue;
			Leg passengerLeg = passengerLegs.getFirst();
			int passengerLegIndex = allLegIndex(passenger.getSelectedPlan(), passengerLeg);
			String bindingKey = passenger.getId() + "/" + passengerLegIndex;
			Object persistentKey = passengerLeg.getAttributes().getAttribute(
					HouseholdEscortBindingCatalog.BINDING_KEY_ATTRIBUTE);
			if (persistentKey == null) continue;
			if (!bindingKey.equals(persistentKey.toString())) {
				throw new IllegalStateException("Checkpoint passenger binding key mismatch: "
						+ passenger.getId() + ", expected=" + bindingKey + ", actual=" + persistentKey);
			}
			observedBindingKeys.add(bindingKey);

			Person driver = requiredPerson(scenario, candidate.driverPersonId());
			TripStructureUtils.Trip driverTrip = selectedTrip(driver, candidate.driverTripIndex());
			List<Leg> driverCarLegs = legs(driverTrip).stream()
					.filter(leg -> TransportMode.car.equals(leg.getMode())).toList();
			if (driverCarLegs.size() != 1) continue;
			Leg driverLeg = driverCarLegs.getFirst();
			if (!(driverLeg.getRoute() instanceof NetworkRoute driverRoute)) continue;
			Id<Vehicle> vehicleId = Id.createVehicleId(candidate.vehicleId());
			Id<Link> pickup = Id.createLinkId(candidate.passengerPickupLinkId());
			Id<Link> dropoff = Id.createLinkId(candidate.passengerDropoffLinkId());
			if (!vehicleId.equals(driverRoute.getVehicleId())
					|| !contains(driverRoute, pickup) || !contains(driverRoute, dropoff)) continue;
			if (!restoredBindingKeys.add(bindingKey)) {
				throw new IllegalStateException("Multiple checkpoint candidates match " + bindingKey);
			}
			restored.add(new HouseholdEscortBindingCatalog.Binding(
					candidate.candidateId(), candidate.householdId(),
					"iteration_checkpoint_selected_plan_v1",
					!"car_passenger".equals(candidate.passengerOriginalMode()),
					passenger.getId(), passengerLegIndex, passengerLeg,
					driver.getId(), allLegIndex(driver.getSelectedPlan(), driverLeg), driverLeg,
					HouseholdEscortBindingCatalog.snapshotNetworkRoute(driverRoute), vehicleId,
					pickup, dropoff, driverRoute.getEndLinkId(),
					passengerTrip.getOriginActivity().getEndTime().orElse(
							candidate.passengerDepartureTimeS()),
					candidate.driverDepartureTimeS(), candidate.originAccessGapM(),
					candidate.destinationEgressGapM()));
		}
		Set<String> missing = new HashSet<>(observedBindingKeys);
		missing.removeAll(restoredBindingKeys);
		if (!missing.isEmpty()) {
			throw new IllegalStateException("Checkpoint bindings lack a matching driver route: " + missing);
		}
		if (restored.size() != expectedBindings) {
			throw new IllegalStateException("Checkpoint household binding count mismatch: expected="
					+ expectedBindings + ", restored=" + restored.size());
		}
		bindings.replaceWithActiveBindings(restored);
		return restored.size();
	}

	private static Person requiredPerson(Scenario scenario, String personId) {
		Person person = scenario.getPopulation().getPersons().get(Id.createPersonId(personId));
		if (person == null || person.getSelectedPlan() == null) {
			throw new IllegalStateException("Checkpoint candidate person/selected plan missing: " + personId);
		}
		return person;
	}

	private static TripStructureUtils.Trip selectedTrip(Person person, int tripIndex) {
		List<TripStructureUtils.Trip> trips = TripStructureUtils.getTrips(person.getSelectedPlan());
		if (tripIndex < 0 || tripIndex >= trips.size()) {
			throw new IllegalStateException("Checkpoint trip index is invalid: person="
					+ person.getId() + ", trip=" + tripIndex + ", trips=" + trips.size());
		}
		return trips.get(tripIndex);
	}

	private static List<Leg> legs(TripStructureUtils.Trip trip) {
		return trip.getTripElements().stream().filter(Leg.class::isInstance)
				.map(Leg.class::cast).toList();
	}

	private static int allLegIndex(Plan plan, Leg target) {
		int index = 0;
		for (PlanElement element : plan.getPlanElements()) {
			if (!(element instanceof Leg leg)) continue;
			if (leg == target) return index;
			index++;
		}
		throw new IllegalStateException("Checkpoint leg is absent from selected plan");
	}

	private static boolean contains(NetworkRoute route, Id<Link> linkId) {
		return linkId.equals(route.getStartLinkId()) || route.getLinkIds().contains(linkId)
				|| linkId.equals(route.getEndLinkId());
	}
}
