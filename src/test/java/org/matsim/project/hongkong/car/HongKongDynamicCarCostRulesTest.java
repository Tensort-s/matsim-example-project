package org.matsim.project.hongkong.car;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.events.ActivityStartEvent;
import org.matsim.api.core.v01.events.LinkEnterEvent;
import org.matsim.api.core.v01.events.PersonArrivalEvent;
import org.matsim.api.core.v01.events.VehicleEntersTrafficEvent;
import org.matsim.api.core.v01.events.VehicleLeavesTrafficEvent;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.network.Network;
import org.matsim.api.core.v01.network.Node;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.network.NetworkUtils;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.router.costcalculators.RandomizingTimeDistanceTravelDisutilityFactory;
import org.matsim.core.router.util.TravelTime;
import org.matsim.facilities.ActivityFacility;
import org.matsim.vehicles.Vehicle;

import java.util.List;
import java.util.Map;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.assertEquals;

class HongKongDynamicCarCostRulesTest {

	@Test
	void productionRuleFilesLoadSemanticallyWithoutStaticLegTables() throws Exception {
		Network network = NetworkUtils.createNetwork();
		List<String> mapping = Files.readAllLines(Path.of(
				"data/transport_costs/hongkong/car_cost_v1/toll_network_mapping_v1/"
						+ "toll_facility_network_mapping.csv"));
		int ordinal = 0;
		for (String row : mapping.subList(1, mapping.size())) {
			String[] values = row.split(",", -1);
			String linkId = values[5];
			if (network.getLinks().containsKey(Id.createLinkId(linkId))) continue;
			Node from = node(network, "map_from_" + ordinal, ordinal * 2.0);
			Node to = node(network, "map_to_" + ordinal, ordinal * 2.0 + 1.0);
			link(network, linkId, from, to);
			ordinal++;
		}
		var rules = HongKongDynamicCarCostRules.load(
				Path.of("data/transport_costs/hongkong/car_cost_v1"), network);
		assertEquals(2.3260259843327398, rules.energyHkdPerKm(), 0.0);
		assertEquals(34, rules.mappedTollLinks());
		assertEquals(44_546, rules.parkingFacilities());
		assertEquals(44.0, rules.quoteLink(
				network.getLinks().get(Id.createLinkId("road_3345_0_f")),
				28_439.015).tollHkd(), 0.0);
		assertEquals(0.0, rules.quoteParking(
				"home_hk_hh_0000251", "home", 1_000.0, 10_000.0).costHkd(), 0.0);
	}

	@Test
	void arbitraryNetworkRouteAndRoutingDisutilityUseTheSameLinkRules() {
		Fixture fixture = fixture();
		var route = RouteUtils.createLinkNetworkRouteImpl(
				fixture.l1.getId(), List.of(fixture.l2.getId()), fixture.l3.getId());
		TravelTime travelTime = (link, time, person, vehicle) -> 10.0;
		var quote = fixture.rules.quoteNetworkRoute(route, 100.0, travelTime, fixture.person, null);
		assertEquals(4.0, quote.energyHkd(), 0.0);
		assertEquals(20.0, quote.tollHkd(), 0.0);
		assertEquals(2, quote.pricedLinks());

		Config config = ConfigUtils.createConfig();
		config.routing().setRoutingRandomness(0.0);
		config.scoring().setMarginalUtilityOfMoney(2.0);
		config.scoring().getModes().get("car").setMonetaryDistanceRate(0.0);
		var dynamic = new HongKongDynamicCarTravelDisutilityFactory(config, fixture.rules)
				.createTravelDisutility(travelTime);
		var standard = new RandomizingTimeDistanceTravelDisutilityFactory("car", config)
				.createTravelDisutility(travelTime);
		double added = dynamic.getLinkTravelDisutility(fixture.l2, 100.0, fixture.person, null)
				- standard.getLinkTravelDisutility(fixture.l2, 100.0, fixture.person, null);
		assertEquals((2.0 + 20.0) * 2.0, added, 1.0e-12);
	}

	@Test
	void experiencedLinksAndActualVehicleDwellProduceOneConsistentScore() {
		Fixture fixture = fixture();
		Id<Vehicle> vehicle = Id.createVehicleId("private-1");
		var scoring = new HongKongDynamicCarCostScoring(
				fixture.person, fixture.network, fixture.rules,
				new HongKongDynamicCarCostRunAudit(), 2.0, 10_800.0);

		scoring.handleEvent(new VehicleEntersTrafficEvent(
				100.0, fixture.person.getId(), fixture.l1.getId(), vehicle, "car", 1.0));
		scoring.handleEvent(new LinkEnterEvent(110.0, vehicle, fixture.l2.getId()));
		scoring.handleEvent(new LinkEnterEvent(120.0, vehicle, fixture.l3.getId()));
		scoring.handleEvent(new VehicleLeavesTrafficEvent(
				130.0, fixture.person.getId(), fixture.l3.getId(), vehicle, "car", 1.0));
		scoring.handleEvent(new PersonArrivalEvent(
				130.0, fixture.person.getId(), fixture.l3.getId(), "car"));
		scoring.handleEvent(new ActivityStartEvent(
				130.0, fixture.person.getId(), fixture.l3.getId(),
				Id.create("destination", ActivityFacility.class), "work"));
		scoring.handleEvent(new VehicleEntersTrafficEvent(
				3_730.0, fixture.person.getId(), fixture.l3.getId(), vehicle, "car", 1.0));
		scoring.finish();

		assertEquals(4.0, scoring.energyHkd(), 0.0);
		assertEquals(20.0, scoring.tollHkd(), 0.0);
		assertEquals(100.0, scoring.parkingHkd(), 0.0);
		assertEquals(2, scoring.linkEntries());
		assertEquals(1, scoring.tollEntries());
		assertEquals(1, scoring.parkingEvents());
		assertEquals(-248.0, scoring.getScore(), 0.0);
	}

	private static Fixture fixture() {
		Network network = NetworkUtils.createNetwork();
		Node n1 = node(network, "n1", 0.0);
		Node n2 = node(network, "n2", 1.0);
		Node n3 = node(network, "n3", 2.0);
		Node n4 = node(network, "n4", 3.0);
		Link l1 = link(network, "l1", n1, n2);
		Link l2 = link(network, "l2", n2, n3);
		Link l3 = link(network, "l3", n3, n4);
		var rules = new HongKongDynamicCarCostRules(
				network,
				2.0,
				Map.of(l2.getId(), "test_tunnel"),
				Map.of("test_tunnel", List.of(
						new HongKongDynamicCarCostRules.TollRate(0.0, 86_399.0, 20.0))),
				Map.of("destination", 5),
				Map.of("private-1", "private_car"),
				Map.of(
						new HongKongDynamicCarCostRules.ParkingKey("kowloon_urban", "work"),
						new HongKongDynamicCarCostRules.ParkingRule(
								"representative_day_pass", 0.0, 0.0, 100.0, 0.0,
								3_600.0, 25_200.0, 82_800.0)));
		Person person = PopulationUtils.getFactory().createPerson(Id.createPersonId("person"));
		person.getAttributes().putAttribute("assignedVehicleId", "private-1");
		return new Fixture(network, l1, l2, l3, rules, person);
	}

	private static Node node(Network network, String id, double x) {
		Node node = network.getFactory().createNode(Id.createNodeId(id), new Coord(x, 0.0));
		network.addNode(node);
		return node;
	}

	private static Link link(Network network, String id, Node from, Node to) {
		Link link = network.getFactory().createLink(Id.createLinkId(id), from, to);
		link.setLength(1_000.0);
		link.setFreespeed(10.0);
		link.setCapacity(1_000.0);
		link.setNumberOfLanes(1.0);
		network.addLink(link);
		return link;
	}

	private record Fixture(
			Network network,
			Link l1,
			Link l2,
			Link l3,
			HongKongDynamicCarCostRules rules,
			Person person) {
	}
}
