package org.matsim.project.hongkong.taxi;

import com.google.inject.Injector;
import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.network.Network;
import org.matsim.api.core.v01.network.Node;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.network.NetworkUtils;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.population.algorithms.PersonPrepareForSim;
import org.matsim.core.router.DefaultRoutingRequest;
import org.matsim.core.router.PlanRouter;
import org.matsim.core.router.RoutingRequest;
import org.matsim.core.router.TripRouter;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.core.utils.timing.TimeInterpretation;
import org.matsim.facilities.FacilitiesUtils;
import org.matsim.utils.objectattributes.attributable.AttributesImpl;

import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HongKongTaxiRoutingModuleTest {

	@Test
	void singleTaxiTripStaysTaxiAndHasLegalTeleportedRoute() {
		Scenario scenario = scenarioWithTaxiRouting();
		Person person = HongKongTaxiTestFixtures.person("taxi-router");
		AttributesImpl attributes = new AttributesImpl();
		copyTaxiAttributes(
				HongKongTaxiTestFixtures.taxiLeg(100.0).getAttributes(),
				attributes);
		RoutingRequest request = DefaultRoutingRequest.of(
				FacilitiesUtils.wrapActivity(activityOnLink(
						"home", 0, 0, "car-link")),
				FacilitiesUtils.wrapActivity(activityOnLink(
						"work", 3_000, 4_000, "car-link-reverse")),
				8 * 3_600,
				person,
				attributes);

		List<? extends PlanElement> routed =
				tripRouter(scenario).getRoutingModule("taxi").calcRoute(request);

		assertEquals(1, routed.size());
		Leg leg = (Leg) routed.getFirst();
		assertEquals("taxi", leg.getMode());
		assertEquals("taxi", leg.getRoutingMode());
		assertFalse("ride".equals(leg.getMode()));
		assertLegalRoute(leg);
		assertEquals("urban_taxi", leg.getAttributes().getAttribute(
				HongKongTaxiLegAttributes.TAXI_TYPE));
		HongKongTaxiRouteContext context =
				HongKongTaxiRouteContext.from(leg);
		assertEquals(leg.getRoute().getDistance(), context.distanceMeters());
		assertEquals(
				leg.getRoute().getTravelTime().seconds(),
				context.travelTimeSeconds());
		assertEquals(8 * 3_600, context.departureTimeSeconds());
		assertEquals("urban_taxi", context.taxiType());
		assertEquals("test_classification", context.classificationSource());
	}

	@Test
	void standardWholePlanRoutingWithNullPtDoesNotDegradeTaxiToRide() {
		Scenario scenario = scenarioWithTaxiRouting();
		Person person = HongKongTaxiTestFixtures.person("whole-plan");
		Plan plan = PopulationUtils.createPlan(person);
		Activity home = activity("home", 0, 0);
		home.setEndTime(7 * 3_600);
		plan.addActivity(home);
		Leg pt = PopulationUtils.createLeg("pt");
		pt.setRoutingMode("pt");
		assertEquals(null, pt.getRoute());
		plan.addLeg(pt);
		Activity work = activity("work", 2_000, 0);
		work.setEndTime(17 * 3_600);
		plan.addActivity(work);
		Leg taxi = HongKongTaxiTestFixtures.taxiLeg(100.0);
		taxi.setRoute(null);
		copyTaxiAttributes(
				taxi.getAttributes(), work.getAttributes());
		plan.addLeg(taxi);
		plan.addActivity(activity("shop", 5_000, 4_000));
		person.addPlan(plan);
		person.setSelectedPlan(plan);
		scenario.getPopulation().addPerson(person);

		TripRouter tripRouter = tripRouter(scenario);
		PlanRouter planRouter = new PlanRouter(
				tripRouter, TimeInterpretation.create(scenario.getConfig()));
		new PersonPrepareForSim(planRouter, scenario).run(person);

		List<Leg> legs = PopulationUtils.getLegs(person.getSelectedPlan());
		assertEquals(2, legs.size());
		assertEquals("pt", legs.get(0).getRoutingMode());
		Leg routedTaxi = legs.get(1);
		assertEquals("taxi", routedTaxi.getMode());
		assertEquals("taxi", routedTaxi.getRoutingMode());
		assertFalse(legs.stream().anyMatch(leg ->
				"ride".equals(leg.getMode())));
		assertLegalRoute(routedTaxi);
		assertEquals(100.0, routedTaxi.getAttributes().getAttribute(
				HongKongTaxiLegAttributes.FARE_BASELINE_HKD));
	}

	@Test
	void taxiConfigurationRemainsPassengerOnlyWithoutDvrpOrFleet() {
		Config config = ConfigUtils.createConfig();
		List<String> qsimModesBefore = List.copyOf(config.qsim().getMainModes());
		List<String> networkModesBefore =
				List.copyOf(config.routing().getNetworkModes());

		HongKongTaxiRoutingModule.configure(config);

		assertEquals(qsimModesBefore, List.copyOf(config.qsim().getMainModes()));
		assertEquals(
				networkModesBefore,
				List.copyOf(config.routing().getNetworkModes()));
		assertFalse(config.qsim().getMainModes().contains("taxi"));
		assertFalse(config.routing().getNetworkModes().contains("taxi"));
		assertFalse(config.routing().getModeRoutingParams().containsKey("taxi"));
		assertTrue(config.getModules().keySet().stream()
				.map(name -> name.toLowerCase(Locale.ROOT))
				.noneMatch(name -> name.contains("dvrp")
						|| name.contains("fleet")
						|| name.contains("multimodetaxi")));
	}

	private static Scenario scenarioWithTaxiRouting() {
		Config config = ConfigUtils.createConfig();
		config.transit().setUseTransit(false);
		config.controller().setOutputDirectory(
				"target/taxi-routing-test-" + UUID.randomUUID());
		HongKongTaxiRoutingModule.configure(config);
		Scenario scenario = ScenarioUtils.createScenario(config);
		Network network = scenario.getNetwork();
		Node from = NetworkUtils.createAndAddNode(
				network, Id.createNodeId("from"), new Coord(0, 0));
		Node to = NetworkUtils.createAndAddNode(
				network, Id.createNodeId("to"), new Coord(5_000, 4_000));
		Link link = NetworkUtils.createAndAddLink(
				network,
				Id.createLinkId("car-link"),
				from,
				to,
				6_500,
				15.0,
				3_600,
				1.0);
		link.setAllowedModes(Set.of("car"));
		Link reverse = NetworkUtils.createAndAddLink(
				network,
				Id.createLinkId("car-link-reverse"),
				to,
				from,
				6_500,
				15.0,
				3_600,
				1.0);
		reverse.setAllowedModes(Set.of("car"));
		return scenario;
	}

	private static TripRouter tripRouter(Scenario scenario) {
		Injector injector = org.matsim.core.controler.Injector
				.createMinimalMatsimInjector(
						scenario.getConfig(),
						scenario,
						new HongKongTaxiRoutingModule());
		return injector.getInstance(TripRouter.class);
	}

	private static Activity activity(
			String type, double x, double y) {
		return PopulationUtils.createActivityFromCoord(
				type, new Coord(x, y));
	}

	private static Activity activityOnLink(
			String type, double x, double y, String linkId) {
		return PopulationUtils.createActivityFromCoordAndLinkId(
				type, new Coord(x, y), Id.createLinkId(linkId));
	}

	private static void copyTaxiAttributes(
			org.matsim.utils.objectattributes.attributable.Attributes source,
			org.matsim.utils.objectattributes.attributable.Attributes target) {
		for (String name : HongKongTaxiLegAttributes.NAMES) {
			target.putAttribute(name, source.getAttribute(name));
		}
	}

	private static void assertLegalRoute(Leg leg) {
		assertNotNull(leg.getRoute());
		assertTrue(Double.isFinite(leg.getRoute().getDistance()));
		assertTrue(leg.getRoute().getDistance() >= 0.0);
		assertTrue(leg.getRoute().getTravelTime().isDefined());
		assertTrue(Double.isFinite(
				leg.getRoute().getTravelTime().seconds()));
		assertTrue(leg.getRoute().getTravelTime().seconds() >= 0.0);
		assertTrue(leg.getTravelTime().isDefined());
		assertTrue(Double.isFinite(leg.getTravelTime().seconds()));
		assertTrue(leg.getTravelTime().seconds() >= 0.0);
	}
}
