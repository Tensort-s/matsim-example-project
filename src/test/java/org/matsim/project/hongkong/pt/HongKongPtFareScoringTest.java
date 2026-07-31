package org.matsim.project.hongkong.pt;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.router.TripStructureUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.pt.routes.DefaultTransitPassengerRoute;
import org.matsim.pt.transitSchedule.api.Departure;
import org.matsim.pt.transitSchedule.api.TransitLine;
import org.matsim.pt.transitSchedule.api.TransitRoute;
import org.matsim.pt.transitSchedule.api.TransitRouteStop;
import org.matsim.pt.transitSchedule.api.TransitSchedule;
import org.matsim.pt.transitSchedule.api.TransitScheduleFactory;
import org.matsim.pt.transitSchedule.api.TransitStopFacility;

import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HongKongPtFareScoringTest {

	private static final String SOURCE_PATH =
			"mtr_station_od_v1/mtr_station_od_fare_rules.parquet";
	private static final String SOURCE_SHA =
			"0829574983542c8178a562463d1711f93fe8381dfda7a7ad88bb7a8c7c2701fa";
	private static final String LIGHT_RAIL_SOURCE_PATH =
			"light_rail_station_od_v1/light_rail_station_od_fare_rules.parquet";
	private static final String LIGHT_RAIL_SOURCE_SHA =
			"92596e56342eeffe5374aa4ed7dba9a5b57986ab3257623e64e04cb837a64004";

	@Test
	void selectedPlanFareIsChargedOnceAndOtherCallbacksAreInert() {
		Fixture fixture = fixture("resolved", true);
		HongKongPtFareScoringComponentFactory factory =
				new HongKongPtFareScoringComponentFactory(
						fixture.schedule, fixture.catalog, 2.0);
		assertEquals(
				HongKongPtFareScoringComponentFactory.COMPONENT_ID,
				factory.componentId());
		assertEquals(Set.of("pt"), factory.activeModes());

		HongKongPtFareScoring scoring = assertInstanceOf(
				HongKongPtFareScoring.class,
				factory.createComponent(fixture.person));
		scoring.handleLeg(fixture.ptLeg);
		assertEquals(-9.8, scoring.getScore(), 0.0);
		assertEquals(4.9, scoring.chargedFareHkd(), 0.0);
		assertEquals(1, scoring.resolvedSegments());
		assertEquals(0, scoring.unresolvedSegments());

		scoring.addMoney(-4.9);
		scoring.addScore(100.0);
		scoring.agentStuck(1_000.0);
		scoring.handleEvent(new Event(1_000.0) {
			@Override
			public String getEventType() {
				return "stage7_duplicate_probe";
			}
		});
		scoring.handleTrip(TripStructureUtils.getTrips(
				fixture.person.getSelectedPlan()).getFirst());
		assertEquals(-9.8, scoring.getScore(), 0.0);
		scoring.finish();

		StringBuilder explanation = new StringBuilder();
		scoring.explainScore(explanation);
		assertTrue(explanation.toString().contains("moneyEventsEmitted=0"));
		assertTrue(explanation.toString().contains("tripCallbackCharges=0"));
		assertTrue(Double.isFinite(scoring.getScore()));
	}

	@Test
	void duplicateLegCallbackAndIncompleteConsumptionFailClosed() {
		Fixture fixture = fixture("duplicate", true);
		HongKongPtFareScoring first =
				new HongKongPtFareScoring(
						HongKongPtPersonFareSchedule.fromSelectedPlan(
								fixture.person,
								fixture.schedule,
								fixture.catalog),
						1.0);
		first.handleLeg(fixture.ptLeg);
		IllegalStateException duplicate = assertThrows(
				IllegalStateException.class,
				() -> first.handleLeg(fixture.ptLeg));
		assertTrue(duplicate.getMessage().contains("no selected-plan fare"));
		assertEquals(-4.9, first.getScore(), 0.0);

		HongKongPtFareScoring incomplete =
				new HongKongPtFareScoring(
						HongKongPtPersonFareSchedule.fromSelectedPlan(
								fixture.person,
								fixture.schedule,
								fixture.catalog),
						1.0);
		IllegalStateException error =
				assertThrows(IllegalStateException.class, incomplete::finish);
		assertTrue(error.getMessage().contains("before every selected-plan"));
	}

	@Test
	void unresolvedFareRemainsNullExplicitAndFinite() {
		Fixture fixture = fixture("unresolved", false);
		HongKongPtPersonFareSchedule schedule =
				HongKongPtPersonFareSchedule.fromSelectedPlan(
						fixture.person, fixture.schedule, fixture.catalog);
		assertEquals(1, schedule.size());
		HongKongPtPersonFareSchedule.LegFare fare = schedule.fareAt(0);
		assertFalse(fare.completeFareHkd().isPresent());
		assertEquals(0.0, fare.resolvedFareHkd(), 0.0);
		assertEquals(null, fare.segmentQuotes().getFirst().costHkd());
		assertTrue(fare.segmentQuotes().getFirst().unresolvedReason()
				.contains("no_cross_scope_fallback"));

		HongKongPtFareScoring scoring =
				new HongKongPtFareScoring(schedule, 1.0);
		scoring.handleLeg(fixture.ptLeg);
		scoring.finish();
		assertEquals(0.0, scoring.getScore(), 0.0);
		assertEquals(0, scoring.resolvedSegments());
		assertEquals(1, scoring.unresolvedSegments());
		StringBuilder explanation = new StringBuilder();
		scoring.explainScore(explanation);
		assertTrue(explanation.toString()
				.contains("unresolvedSegments=1"));
	}

	@Test
	void nonPtLegsDoNotConsumeOrdinalAndRouteMismatchFailsClosed() {
		Fixture fixture = fixture("ordinal", true);
		HongKongPtFareScoring scoring =
				new HongKongPtFareScoring(
						HongKongPtPersonFareSchedule.fromSelectedPlan(
								fixture.person,
								fixture.schedule,
								fixture.catalog),
						1.0);
		Leg walk = PopulationUtils.createLeg(TransportMode.walk);
		scoring.handleLeg(walk);
		assertEquals(0, scoring.consumedPtLegs());

		Leg wrong = PopulationUtils.createLeg(TransportMode.pt);
		wrong.setRoutingMode(TransportMode.pt);
		IllegalStateException mismatch = assertThrows(
				IllegalStateException.class,
				() -> scoring.handleLeg(wrong));
		assertTrue(mismatch.getMessage().contains("fingerprint"));
		assertEquals(0, scoring.consumedPtLegs());
	}

	@Test
	void duplicateCatalogKeysFailClosed() {
		HongKongPtFareRuntimeCatalog.Builder builder = baseBuilder();
		addResolvedRule(builder);
		assertThrows(
				IllegalStateException.class,
				() -> addResolvedRule(builder));
	}

	@Test
	void chainedTransferChargesEachResolvedSegmentOnceWithoutConcession() {
		Fixture fixture = chainedFixture();
		HongKongPtPersonFareSchedule schedule =
				HongKongPtPersonFareSchedule.fromSelectedPlan(
						fixture.person, fixture.schedule, fixture.catalog);
		assertEquals(1, schedule.size());
		assertEquals(2, schedule.fareAt(0).segmentQuotes().size());
		for (HongKongPtFareRuntimeCatalog.FareQuote quote :
				schedule.fareAt(0).segmentQuotes()) {
			assertTrue(quote.resolved(), quote.unresolvedReason());
		}
		assertEquals(10.0, schedule.fareAt(0).resolvedFareHkd(), 0.0);
		assertTrue(schedule.fareAt(0).completeFareHkd().isPresent());
		for (HongKongPtFareRuntimeCatalog.FareQuote quote :
				schedule.fareAt(0).segmentQuotes()) {
			assertEquals(null, quote.transferConcessionHkd());
			assertEquals("not_modelled", quote.transferConcessionStatus());
		}

		HongKongPtFareScoring scoring =
				new HongKongPtFareScoring(schedule, 1.0);
		scoring.handleLeg(fixture.ptLeg);
		assertEquals(-10.0, scoring.getScore(), 0.0);
		assertEquals(2, scoring.resolvedSegments());
		assertThrows(
				IllegalStateException.class,
				() -> scoring.handleLeg(fixture.ptLeg));
		assertEquals(-10.0, scoring.getScore(), 0.0);
	}

	@Test
	void nonzeroStandardPtMonetaryDistanceChargeIsRejectedNotMutated() {
		var config = ConfigUtils.createConfig();
		config.scoring().getOrCreateModeParams("pt")
				.setMonetaryDistanceRate(-0.25);
		IllegalStateException error = assertThrows(
				IllegalStateException.class,
				() -> HongKongPtFareScoringComponentFactory
						.requireNoStandardPtMonetaryDistanceCharge(config));
		assertTrue(error.getMessage()
				.contains("monetaryDistanceRate"));
		assertEquals(
				-0.25,
				config.scoring().getModes().get("pt")
						.getMonetaryDistanceRate(),
				0.0);

		config.scoring().getModes().get("pt")
				.setMonetaryDistanceRate(0.0);
		HongKongPtFareScoringComponentFactory
				.requireNoStandardPtMonetaryDistanceCharge(config);
	}

	private static Fixture fixture(String personId, boolean addRule) {
		HongKongPtFareRuntimeCatalog.Builder builder = baseBuilder();
		if (addRule) {
			addResolvedRule(builder);
		}
		HongKongPtFareRuntimeCatalog catalog = builder.build();

		TransitSchedule schedule = ScenarioUtils.createScenario(
				ConfigUtils.createConfig()).getTransitSchedule();
		TransitScheduleFactory factory = schedule.getFactory();
		Id<Link> accessLink = Id.createLinkId("access-link");
		Id<Link> egressLink = Id.createLinkId("egress-link");
		TransitStopFacility access = stop(
				factory, "mtr-access", accessLink, 0.0);
		TransitStopFacility egress = stop(
				factory, "mtr-egress", egressLink, 1.0);
		schedule.addStopFacility(access);
		schedule.addStopFacility(egress);
		TransitRouteStop accessStop =
				factory.createTransitRouteStop(access, 0.0, 0.0);
		TransitRouteStop egressStop =
				factory.createTransitRouteStop(egress, 300.0, 300.0);
		TransitRoute transitRoute = factory.createTransitRoute(
				Id.create("mtr-route", TransitRoute.class),
				RouteUtils.createLinkNetworkRouteImpl(
						accessLink, egressLink),
				List.of(accessStop, egressStop),
				"train");
		Departure departure = factory.createDeparture(
				Id.create("departure", Departure.class), 100.0);
		transitRoute.addDeparture(departure);
		TransitLine line = factory.createTransitLine(
				Id.create("mtr-line", TransitLine.class));
		line.addRoute(transitRoute);
		schedule.addTransitLine(line);

		Person person = PopulationUtils.getFactory().createPerson(
				Id.createPersonId(personId));
		Plan plan = PopulationUtils.createPlan(person);
		Activity origin = PopulationUtils.createActivityFromCoord(
				"home", new Coord(0.0, 0.0));
		plan.addActivity(origin);
		Leg pt = PopulationUtils.createLeg(TransportMode.pt);
		pt.setRoutingMode(TransportMode.pt);
		DefaultTransitPassengerRoute route =
				new DefaultTransitPassengerRoute(
						access, line, transitRoute, egress);
		route.setDistance(1_000.0);
		route.setTravelTime(300.0);
		pt.setRoute(route);
		plan.addLeg(pt);
		plan.addActivity(PopulationUtils.createActivityFromCoord(
				"work", new Coord(1.0, 1.0)));
		person.addPlan(plan);
		person.setSelectedPlan(plan);
		return new Fixture(schedule, catalog, person, pt);
	}

	private static Fixture chainedFixture() {
		HongKongPtFareRuntimeCatalog.Builder builder =
				HongKongPtFareRuntimeCatalog.builder()
						.source(SOURCE_PATH, SOURCE_SHA)
						.source(
								LIGHT_RAIL_SOURCE_PATH,
								LIGHT_RAIL_SOURCE_SHA)
						.mapStop(
								HongKongPtFareRuntimeCatalog.Layer.MTR_DOMESTIC,
								"transfer-access", "1")
						.mapStop(
								HongKongPtFareRuntimeCatalog.Layer.MTR_DOMESTIC,
								"transfer-mid", "2")
						.mapStop(
								HongKongPtFareRuntimeCatalog.Layer.LIGHT_RAIL,
								"transfer-mid", "10")
						.mapStop(
								HongKongPtFareRuntimeCatalog.Layer.LIGHT_RAIL,
								"transfer-egress", "20");
		addResolvedRule(builder);
		builder.rule(
				HongKongPtFareRuntimeCatalog.Layer.LIGHT_RAIL,
				"", "", "10", "20", 5.1,
				"available", "B", "exact",
				"adult_octopus_light_rail_base_before_unmodelled_concessions",
				"light_rail_fares",
				"fixture-light-rail-record",
				LIGHT_RAIL_SOURCE_PATH,
				LIGHT_RAIL_SOURCE_SHA,
				"exact_ordered_stop_od",
				"");
		HongKongPtFareRuntimeCatalog catalog = builder.build();

		TransitSchedule schedule = ScenarioUtils.createScenario(
				ConfigUtils.createConfig()).getTransitSchedule();
		TransitScheduleFactory factory = schedule.getFactory();
		TransitStopFacility access = stop(
				factory, "transfer-access",
				Id.createLinkId("transfer-access-link"), 0.0);
		TransitStopFacility mid = stop(
				factory, "transfer-mid",
				Id.createLinkId("transfer-mid-link"), 1.0);
		TransitStopFacility egress = stop(
				factory, "transfer-egress",
				Id.createLinkId("transfer-egress-link"), 2.0);
		schedule.addStopFacility(access);
		schedule.addStopFacility(mid);
		schedule.addStopFacility(egress);

		TransitLine mtrLine = addRoute(
				schedule, "transfer-mtr-line", "transfer-mtr-route",
				"train", access, mid);
		TransitRoute mtrRoute =
				mtrLine.getRoutes().values().iterator().next();
		TransitLine lightRailLine = addRoute(
				schedule, "transfer-lrt-line", "transfer-lrt-route",
				"light_rail", mid, egress);
		TransitRoute lightRailRoute =
				lightRailLine.getRoutes().values().iterator().next();

		DefaultTransitPassengerRoute second =
				new DefaultTransitPassengerRoute(
						mid, lightRailLine, lightRailRoute, egress);
		second.setDistance(500.0);
		second.setTravelTime(180.0);
		DefaultTransitPassengerRoute first =
				new DefaultTransitPassengerRoute(
						access, mtrLine, mtrRoute, mid, second);
		first.setDistance(1_000.0);
		first.setTravelTime(300.0);

		Person person = PopulationUtils.getFactory().createPerson(
				Id.createPersonId("transfer"));
		Plan plan = PopulationUtils.createPlan(person);
		plan.addActivity(PopulationUtils.createActivityFromCoord(
				"home", new Coord(0.0, 0.0)));
		Leg pt = PopulationUtils.createLeg(TransportMode.pt);
		pt.setRoutingMode(TransportMode.pt);
		pt.setRoute(first);
		plan.addLeg(pt);
		plan.addActivity(PopulationUtils.createActivityFromCoord(
				"work", new Coord(2.0, 2.0)));
		person.addPlan(plan);
		person.setSelectedPlan(plan);
		return new Fixture(schedule, catalog, person, pt);
	}

	private static TransitLine addRoute(
			TransitSchedule schedule,
			String lineId,
			String routeId,
			String mode,
			TransitStopFacility access,
			TransitStopFacility egress) {
		TransitScheduleFactory factory = schedule.getFactory();
		TransitRouteStop accessStop =
				factory.createTransitRouteStop(access, 0.0, 0.0);
		TransitRouteStop egressStop =
				factory.createTransitRouteStop(egress, 180.0, 180.0);
		TransitRoute route = factory.createTransitRoute(
				Id.create(routeId, TransitRoute.class),
				RouteUtils.createLinkNetworkRouteImpl(
						access.getLinkId(), egress.getLinkId()),
				List.of(accessStop, egressStop),
				mode);
		route.addDeparture(factory.createDeparture(
				Id.create(routeId + "-departure", Departure.class),
				100.0));
		TransitLine line = factory.createTransitLine(
				Id.create(lineId, TransitLine.class));
		line.addRoute(route);
		schedule.addTransitLine(line);
		return line;
	}

	private static HongKongPtFareRuntimeCatalog.Builder baseBuilder() {
		return HongKongPtFareRuntimeCatalog.builder()
				.source(SOURCE_PATH, SOURCE_SHA)
				.mapStop(
						HongKongPtFareRuntimeCatalog.Layer.MTR_DOMESTIC,
						"mtr-access", "1")
				.mapStop(
						HongKongPtFareRuntimeCatalog.Layer.MTR_DOMESTIC,
						"mtr-egress", "2");
	}

	private static void addResolvedRule(
			HongKongPtFareRuntimeCatalog.Builder builder) {
		builder.rule(
				HongKongPtFareRuntimeCatalog.Layer.MTR_DOMESTIC,
				"", "", "1", "2", 4.9,
				"available", "B", "exact",
				"adult_octopus_domestic_mtr_station_od",
				"mtr_fares",
				"fixture-record",
				SOURCE_PATH,
				SOURCE_SHA,
				"exact_ordered_station_od",
				"");
	}

	private static TransitStopFacility stop(
			TransitScheduleFactory factory,
			String id,
			Id<Link> link,
			double coordinate) {
		TransitStopFacility stop = factory.createTransitStopFacility(
				Id.create(id, TransitStopFacility.class),
				new Coord(coordinate, coordinate),
				false);
		stop.setLinkId(link);
		return stop;
	}

	private record Fixture(
			TransitSchedule schedule,
			HongKongPtFareRuntimeCatalog catalog,
			Person person,
			Leg ptLeg) {
	}
}
