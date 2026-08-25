package org.matsim.project.hongkong.walk;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.network.Node;
import org.matsim.core.network.NetworkUtils;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.router.DefaultRoutingRequest;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.vehicles.Vehicle;

import java.util.Set;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HongKongPhysicalWalkModuleTest {

	@Test
	void enablesWalkOnCarLinksOnlyAndIsIdempotent() {
		var network = NetworkUtils.createNetwork();
		Node a = network.getFactory().createNode(Id.createNodeId("a"), new Coord(0, 0));
		Node b = network.getFactory().createNode(Id.createNodeId("b"), new Coord(1, 0));
		network.addNode(a);
		network.addNode(b);
		Link car = network.getFactory().createLink(Id.createLinkId("car"), a, b);
		car.setAllowedModes(Set.of(TransportMode.car));
		network.addLink(car);
		Link transit = network.getFactory().createLink(Id.createLinkId("transit"), b, a);
		transit.setAllowedModes(Set.of(TransportMode.pt));
		network.addLink(transit);

		assertEquals(1, HongKongPhysicalWalkModule.enableOnCarLinks(network));
		assertTrue(car.getAllowedModes().contains(TransportMode.walk));
		assertFalse(transit.getAllowedModes().contains(TransportMode.walk));
		assertEquals(0, HongKongPhysicalWalkModule.enableOnCarLinks(network));
	}

	@Test
	void preparationInstallsAndReferencesRoutingOnlyWalkVehicle() {
		var scenario = ScenarioUtils.createScenario(ConfigUtils.createConfig());
		PrepareHongKongWalkChoiceSetPlans.installWalkRoutingVehicle(scenario);
		PrepareHongKongWalkChoiceSetPlans.installWalkRoutingVehicle(scenario);

		Object value = PrepareHongKongWalkChoiceSetPlans
				.routeRequestAttributes(TransportMode.walk)
				.getAttribute(DefaultRoutingRequest.ATTRIBUTE_VEHICLE_ID);
		assertNotNull(value);
		@SuppressWarnings("unchecked")
		Id<Vehicle> vehicleId = (Id<Vehicle>) value;
		var vehicle = scenario.getVehicles().getVehicles().get(vehicleId);
		assertNotNull(vehicle);
		assertEquals(1, scenario.getVehicles().getVehicles().size());
		assertEquals(HongKongPhysicalWalkModule.WALK_SPEED_M_S,
				vehicle.getType().getMaximumVelocity());
		assertEquals(TransportMode.walk, vehicle.getType().getNetworkMode());
		assertNull(PrepareHongKongWalkChoiceSetPlans.routeRequestAttributes(TransportMode.pt)
				.getAttribute(DefaultRoutingRequest.ATTRIBUTE_VEHICLE_ID));
	}

	@Test
	void preparationAcceptsFacilityAccessAroundOnePhysicalWalkLeg() {
		var access = PopulationUtils.createLeg("non_network_walk");
		var accessRoute = RouteUtils.createGenericRouteImpl(
				Id.createLinkId("access-a"), Id.createLinkId("access-b"));
		accessRoute.setDistance(12.0);
		accessRoute.setTravelTime(7.0);
		access.setRoute(accessRoute);
		access.setTravelTime(7.0);

		var walk = PopulationUtils.createLeg(TransportMode.walk);
		var walkRoute = RouteUtils.createLinkNetworkRouteImpl(
				Id.createLinkId("walk-a"), Id.createLinkId("walk-b"));
		walkRoute.setDistance(134.0);
		walkRoute.setTravelTime(100.0);
		walk.setRoute(walkRoute);
		walk.setTravelTime(100.0);

		var assessment = PrepareHongKongWalkChoiceSetPlans.assessRoutedWalk(
				List.of(access, walk));
		assertEquals(107.0, assessment.timeS());
		assertEquals(134.0, assessment.distanceM());
	}
}
