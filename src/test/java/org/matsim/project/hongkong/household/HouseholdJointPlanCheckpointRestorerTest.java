package org.matsim.project.hongkong.household;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.network.Node;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.vehicles.VehicleUtils;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;

class HouseholdJointPlanCheckpointRestorerTest {

	@Test
	void restoresTheFrozenBindingWithoutRunningASelectionWindow() {
		Scenario scenario = ScenarioUtils.createScenario(ConfigUtils.createConfig());
		Id<Link> origin = addLink(scenario, "origin", 0);
		Id<Link> pickup = addLink(scenario, "pickup", 1);
		Id<Link> dropoff = addLink(scenario, "dropoff", 2);
		Id<Link> destination = addLink(scenario, "destination", 3);
		Id<org.matsim.vehicles.Vehicle> vehicleId = Id.createVehicleId("car_1");
		var vehicleType = VehicleUtils.createVehicleType(Id.create("private_car",
				org.matsim.vehicles.VehicleType.class));
		scenario.getVehicles().addVehicleType(vehicleType);
		scenario.getVehicles().addVehicle(VehicleUtils.createVehicle(vehicleId, vehicleType));

		Person passenger = scenario.getPopulation().getFactory().createPerson(
				Id.createPersonId("passenger"));
		Plan passengerPlan = PopulationUtils.createPlan(passenger);
		var passengerOrigin = PopulationUtils.createActivityFromLinkId("home", pickup);
		passengerOrigin.setEndTime(100);
		passengerPlan.addActivity(passengerOrigin);
		Leg passengerLeg = PopulationUtils.createLeg("car_passenger");
		passengerLeg.getAttributes().putAttribute(
				HouseholdEscortBindingCatalog.BINDING_KEY_ATTRIBUTE, "passenger/0");
		passengerLeg.getAttributes().putAttribute(
				HouseholdJointPlanAlternativeGenerator.CANDIDATE_ID_ATTRIBUTE, "candidate_1");
		passengerPlan.addLeg(passengerLeg);
		passengerPlan.addActivity(PopulationUtils.createActivityFromLinkId("school", dropoff));
		passenger.addPlan(passengerPlan);
		passenger.setSelectedPlan(passengerPlan);
		scenario.getPopulation().addPerson(passenger);

		Person driver = scenario.getPopulation().getFactory().createPerson(Id.createPersonId("driver"));
		driver.getAttributes().putAttribute("assignedVehicleId", vehicleId.toString());
		Plan driverPlan = PopulationUtils.createPlan(driver);
		var driverOrigin = PopulationUtils.createActivityFromLinkId("home", origin);
		driverOrigin.setEndTime(90);
		driverPlan.addActivity(driverOrigin);
		Leg driverLeg = PopulationUtils.createLeg("car");
		var route = RouteUtils.createLinkNetworkRouteImpl(
				origin, List.of(pickup, dropoff), destination);
		route.setVehicleId(vehicleId);
		driverLeg.setRoute(route);
		driverPlan.addLeg(driverLeg);
		driverPlan.addActivity(PopulationUtils.createActivityFromLinkId("work", destination));
		driver.addPlan(driverPlan);
		driver.setSelectedPlan(driverPlan);
		scenario.getPopulation().addPerson(driver);

		var candidate = new HouseholdJointPlanCandidateCatalog.Candidate(
				"candidate_1", "household_1", "passenger", 0, "pt",
				"driver", 0, "car", vehicleId.toString(), false,
				100, 90, pickup.toString(), dropoff.toString(), destination.toString(), 0, 0);
		var duplicateGeometryCandidate = new HouseholdJointPlanCandidateCatalog.Candidate(
				"candidate_2", "household_1", "passenger", 0, "pt",
				"driver", 0, "car", vehicleId.toString(), false,
				100, 90, pickup.toString(), dropoff.toString(), destination.toString(), 0, 0);
		var candidates = HouseholdJointPlanCandidateCatalog.of(
				List.of(candidate, duplicateGeometryCandidate));
		var bindings = HouseholdEscortBindingCatalog.empty();

		assertEquals(1, HouseholdJointPlanCheckpointRestorer.restore(
				scenario, candidates, bindings, 1));
		assertEquals(1, bindings.activeBindingCount());
		var binding = bindings.activeBindingForKey("passenger/0");
		assertNotNull(binding);
		assertEquals(vehicleId, binding.vehicleId());
		assertEquals(100, binding.passengerPlannedDepartureTimeSeconds());

		// Model PrepareForSim replacing both trip Leg objects, dropping the
		// passenger attributes, shifting its all-leg index, and routing the driver
		// directly without the pickup/drop-off waypoints.
		Plan preparedPassengerPlan = PopulationUtils.createPlan(passenger);
		var preparedPassengerOrigin = PopulationUtils.createActivityFromLinkId("home", pickup);
		preparedPassengerOrigin.setEndTime(100);
		preparedPassengerPlan.addActivity(preparedPassengerOrigin);
		preparedPassengerPlan.addLeg(PopulationUtils.createLeg("walk"));
		preparedPassengerPlan.addActivity(PopulationUtils.createActivityFromLinkId(
				"pt interaction", pickup));
		Leg preparedPassengerLeg = PopulationUtils.createLeg("car_passenger");
		preparedPassengerPlan.addLeg(preparedPassengerLeg);
		preparedPassengerPlan.addActivity(PopulationUtils.createActivityFromLinkId("school", dropoff));
		passenger.addPlan(preparedPassengerPlan);
		passenger.setSelectedPlan(preparedPassengerPlan);

		Plan preparedDriverPlan = PopulationUtils.createPlan(driver);
		var preparedDriverOrigin = PopulationUtils.createActivityFromLinkId("home", origin);
		preparedDriverOrigin.setEndTime(90);
		preparedDriverPlan.addActivity(preparedDriverOrigin);
		Leg preparedDriverLeg = PopulationUtils.createLeg("car");
		var preparedDirectRoute = RouteUtils.createLinkNetworkRouteImpl(
				origin, List.of(), destination);
		preparedDirectRoute.setVehicleId(vehicleId);
		preparedDriverLeg.setRoute(preparedDirectRoute);
		preparedDriverPlan.addLeg(preparedDriverLeg);
		preparedDriverPlan.addActivity(PopulationUtils.createActivityFromLinkId("work", destination));
		driver.addPlan(preparedDriverPlan);
		driver.setSelectedPlan(preparedDriverPlan);

		assertEquals(1, HouseholdJointPlanCheckpointRestorer.refreshAfterPrepare(
				scenario, candidates, bindings, 1));
		assertEquals("passenger/1", preparedPassengerLeg.getAttributes().getAttribute(
				HouseholdEscortBindingCatalog.BINDING_KEY_ATTRIBUTE));
		assertEquals("candidate_1", preparedPassengerLeg.getAttributes().getAttribute(
				HouseholdJointPlanAlternativeGenerator.CANDIDATE_ID_ATTRIBUTE));
		assertNotNull(bindings.activeBindingForKey("passenger/1"));
		var restoredDriverRoute = (org.matsim.core.population.routes.NetworkRoute)
				preparedDriverLeg.getRoute();
		assertEquals(List.of(pickup, dropoff), restoredDriverRoute.getLinkIds());
	}

	private static Id<Link> addLink(Scenario scenario, String id, int index) {
		Id<Node> fromId = Id.createNodeId("n" + index);
		Id<Node> toId = Id.createNodeId("n" + (index + 1));
		Node from = scenario.getNetwork().getNodes().get(fromId);
		if (from == null) {
			from = scenario.getNetwork().getFactory().createNode(fromId, new Coord(index, 0));
			scenario.getNetwork().addNode(from);
		}
		Node to = scenario.getNetwork().getNodes().get(toId);
		if (to == null) {
			to = scenario.getNetwork().getFactory().createNode(toId, new Coord(index + 1, 0));
			scenario.getNetwork().addNode(to);
		}
		Link link = scenario.getNetwork().getFactory().createLink(Id.createLinkId(id), from, to);
		scenario.getNetwork().addLink(link);
		return link.getId();
	}
}
