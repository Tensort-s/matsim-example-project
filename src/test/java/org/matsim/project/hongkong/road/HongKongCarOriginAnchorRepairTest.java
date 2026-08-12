package org.matsim.project.hongkong.road;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.network.Network;
import org.matsim.api.core.v01.network.NetworkFactory;
import org.matsim.api.core.v01.network.Node;
import org.matsim.core.network.NetworkUtils;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.project.hongkong.car.HongKongDynamicCarCostRules;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertTrue;

final class HongKongCarOriginAnchorRepairTest {

	@Test
	void loadsEventObservationCatalogByPersonAndCarOrdinal() throws Exception {
		Path csv = Path.of("target/test-car-origin-anchor/observations.csv");
		Files.createDirectories(csv.getParent());
		Files.writeString(csv, "\uFEFFperson_id,vehicle_id,private_car_trip_ordinal,"
				+ "vehicle_enters_traffic_time_s,uturn_transition_time_s,start_link_id,"
				+ "observed_reverse_link_id\n"
				+ "p1,v1,2,28800,28801,ab,ba\n", StandardCharsets.UTF_8);

		var catalog = HongKongCarOriginAnchorObservationCatalog.load(csv);

		assertEquals(1, catalog.observations().size());
		assertEquals(2, catalog.observations().getFirst().privateCarTripOrdinal());
		assertEquals(Id.createLinkId("ba"),
				catalog.observations().getFirst().observedReverseLinkId());
	}

	@Test
	void exactReverseAndSegmentDistanceAreGeometricNotIdHeuristics() {
		Network network = NetworkUtils.createNetwork();
		NetworkFactory factory = network.getFactory();
		Node a = factory.createNode(Id.createNodeId("a"), new Coord(0, 0));
		Node b = factory.createNode(Id.createNodeId("b"), new Coord(100, 0));
		network.addNode(a);
		network.addNode(b);
		Link forward = factory.createLink(Id.createLinkId("unrelated-forward"), a, b);
		Link reverse = factory.createLink(Id.createLinkId("unrelated-reverse"), b, a);
		network.addLink(forward);
		network.addLink(reverse);

		assertTrue(HongKongCarOriginAnchorRepair.areExactReverse(forward, reverse));
		assertEquals(12.0,
				HongKongCarOriginAnchorRepair.pointSegmentDistance(new Coord(40, 12), forward),
				1e-9);
	}

	@Test
	void routingProxyKeepsCanonicalParkingFacilityIdentity() {
		String proxy = "facility_17" + HongKongCarOriginAnchorRepair.FACILITY_PROXY_DELIMITER
				+ "person_4_e3";
		assertEquals("facility_17", HongKongDynamicCarCostRules.canonicalParkingFacilityId(proxy));
		assertEquals("facility_17", HongKongDynamicCarCostRules
				.canonicalParkingFacilityId("facility_17"));
	}

	@Test
	void guardsBothCurrentDriverAndPrecedingPassengerBindingLegs() {
		Id<org.matsim.api.core.v01.population.Person> person = Id.createPersonId("p1");
		assertTrue(HongKongCarOriginAnchorRepair.touchesActiveHouseholdLeg(
				Set.of("p1/3"), person, 3));
		assertTrue(HongKongCarOriginAnchorRepair.touchesActiveHouseholdLeg(
				Set.of("p1/2"), person, 3));
	}

	@Test
	void installingAccessWalkRoutePreservesEnclosingCarRoutingMode() {
		var leg = PopulationUtils.createLeg("walk");
		leg.setRoutingMode("car");
		var route = RouteUtils.createLinkNetworkRouteImpl(
				Id.createLinkId("a"), Id.createLinkId("b"));
		route.setTravelTime(42.0);

		HongKongCarOriginAnchorRepair.installWalkRoute(leg, route);

		assertSame(route, leg.getRoute());
		assertEquals("car", leg.getRoutingMode());
		assertEquals(42.0, leg.getTravelTime().seconds());
	}
}
