package org.matsim.project.hongkong.road;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.network.Network;
import org.matsim.api.core.v01.network.NetworkFactory;
import org.matsim.api.core.v01.network.Node;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.pt.transitSchedule.api.TransitLine;
import org.matsim.pt.transitSchedule.api.TransitRoute;
import org.matsim.pt.transitSchedule.api.TransitStopFacility;

import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;

class HongKongRoadHotspotRepairV1Test {

	@Test
	void replacesAuditedShortcutsWithoutOpeningOrdinaryReplanning() {
		Scenario scenario = ScenarioUtils.createScenario(ConfigUtils.createConfig());
		Network network = scenario.getNetwork();
		Node a = node(network, "a", 0);
		Node b = node(network, "b", 1);
		Node c = node(network, "c", 2);
		Node d = node(network, "d", 3);
		Node e = node(network, "e", 4);
		link(network, "road_261323_0_f", a, b, 10);
		link(network, "road_105124_0_f", a, b, 12);
		link(network, "road_261308_0_f", c, d, 10);
		link(network, "detour1", c, e, 6);
		link(network, "detour2", e, d, 6);

		Person person = PopulationUtils.getFactory().createPerson(Id.createPersonId("p"));
		Plan plan = PopulationUtils.createPlan(person);
		plan.addActivity(PopulationUtils.createActivityFromLinkId(
				"home", Id.createLinkId("road_105124_0_f")));
		Leg leg = PopulationUtils.createLeg(TransportMode.car);
		leg.setRoute(RouteUtils.createLinkNetworkRouteImpl(
				Id.createLinkId("road_261308_0_f"), List.of(), Id.createLinkId("road_261308_0_f")));
		plan.addLeg(leg);
		plan.addActivity(PopulationUtils.createActivityFromLinkId("work", Id.createLinkId("detour2")));
		person.addPlan(plan);
		scenario.getPopulation().addPerson(person);
		var scheduleFactory = scenario.getTransitSchedule().getFactory();
		TransitStopFacility stop = scheduleFactory.createTransitStopFacility(
				Id.create("tunnel-stop", TransitStopFacility.class), new Coord(0.5, 0), false);
		stop.setLinkId(Id.createLinkId("road_261323_0_f"));
		scenario.getTransitSchedule().addStopFacility(stop);
		TransitRoute transitRoute = scheduleFactory.createTransitRoute(
				Id.create("tunnel-route", TransitRoute.class),
				RouteUtils.createLinkNetworkRouteImpl(
						Id.createLinkId("road_261323_0_f"), Id.createLinkId("road_261323_0_f")),
				List.of(scheduleFactory.createTransitRouteStop(stop, 0, 0)), "bus");
		TransitLine line = scheduleFactory.createTransitLine(Id.create("line", TransitLine.class));
		line.addRoute(transitRoute);
		scenario.getTransitSchedule().addTransitLine(line);

		var stats = HongKongRoadHotspotRepairV1.apply(scenario);

		assertEquals(1, stats.repairedPopulationRoutes());
		assertEquals(1, stats.repairedTransitRoutes());
		assertEquals(1, stats.remappedTransitStops());
		assertEquals(Id.createLinkId("road_105124_0_f"), stop.getLinkId());
		assertEquals(List.of(Id.createLinkId("detour1"), Id.createLinkId("detour2")),
				stats.replacementPaths().get(Id.createLinkId("road_261308_0_f")));
		assertEquals(Id.createLinkId("detour1"), leg.getRoute().getStartLinkId());
		assertEquals(Id.createLinkId("detour2"), leg.getRoute().getEndLinkId());
		for (Id<Link> linkId : HongKongRoadHotspotRepairV1.RESTRICTED_LINK_IDS) {
			assertFalse(network.getLinks().get(linkId).getAllowedModes().contains("car"));
		}
	}

	private static Node node(Network network, String id, double x) {
		NetworkFactory factory = network.getFactory();
		Node node = factory.createNode(Id.createNodeId(id), new Coord(x, 0));
		network.addNode(node);
		return node;
	}

	private static void link(Network network, String id, Node from, Node to, double length) {
		Link link = network.getFactory().createLink(Id.createLinkId(id), from, to);
		link.setLength(length);
		link.setFreespeed(1);
		link.setCapacity(1_000);
		link.setAllowedModes(Set.of("car", "pt", "bus"));
		network.addLink(link);
	}
}
