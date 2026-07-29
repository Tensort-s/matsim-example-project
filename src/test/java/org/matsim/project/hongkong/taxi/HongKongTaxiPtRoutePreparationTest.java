package org.matsim.project.hongkong.taxi;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.api.core.v01.population.Population;
import org.matsim.api.core.v01.population.Route;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.population.routes.GenericRouteImpl;
import org.matsim.core.population.routes.NetworkRoute;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.pt.routes.DefaultTransitPassengerRoute;
import org.matsim.pt.transitSchedule.api.TransitLine;
import org.matsim.pt.transitSchedule.api.TransitRoute;
import org.matsim.pt.transitSchedule.api.TransitSchedule;
import org.matsim.pt.transitSchedule.api.TransitScheduleFactory;
import org.matsim.pt.transitSchedule.api.TransitStopFacility;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HongKongTaxiPtRoutePreparationTest {

	@Test
	void clearsOnlyNonNullPtRoutesAcrossEveryPlanAndPreservesTaxiExactly() {
		Scenario scenario = ScenarioUtils.createScenario(ConfigUtils.createConfig());
		Person person = HongKongTaxiTestFixtures.person("person");

		Leg selectedPt = legWithGenericRoute("pt", "pt-a", "pt-b");
		Leg selectedTaxi = taxiLeg();
		Leg selectedCar = legWithGenericRoute("car", "car-a", "car-b");
		Route taxiRoute = selectedTaxi.getRoute();
		Route carRoute = selectedCar.getRoute();
		Plan selected = plan(person, selectedPt, selectedTaxi, selectedCar);
		person.addPlan(selected);
		person.setSelectedPlan(selected);

		Leg alternatePt = PopulationUtils.createLeg("pt");
		Leg alternateWalk = legWithGenericRoute("walk", "walk-a", "walk-b");
		Route walkRoute = alternateWalk.getRoute();
		Plan alternate = plan(person, alternatePt, alternateWalk);
		person.addPlan(alternate);
		scenario.getPopulation().addPerson(person);

		HongKongTaxiPtRoutePreparation.TaxiSnapshot taxiBefore =
				HongKongTaxiPtRoutePreparation.captureSelectedTaxi(
						scenario.getPopulation());
		HongKongTaxiPtRoutePreparation.PreparationAudit audit =
				HongKongTaxiPtRoutePreparation.clearPtRoutes(scenario);

		assertEquals(2, audit.plansScanned());
		assertEquals(2, audit.totalPtLegs());
		assertEquals(1, audit.ptRoutesNonNullBefore());
		assertEquals(1, audit.ptRoutesNullBefore());
		assertEquals(1, audit.genericPtRoutesBefore());
		assertEquals(1, audit.ptRoutesCleared());
		assertEquals(2, audit.ptRoutesNullAfterClear());
		assertEquals(0, audit.nonPtRoutesChanged());
		assertNull(selectedPt.getRoute());
		assertNull(alternatePt.getRoute());
		assertSame(taxiRoute, selectedTaxi.getRoute());
		assertSame(carRoute, selectedCar.getRoute());
		assertSame(walkRoute, alternateWalk.getRoute());
		assertTrue(HongKongTaxiPtRoutePreparation.compareTaxi(
				taxiBefore,
				HongKongTaxiPtRoutePreparation.captureSelectedTaxi(
						scenario.getPopulation())).exact());
	}

	@Test
	void preparedAuditAcceptsOnlyCompleteScheduleBackedTransitRoutes() {
		Scenario scenario = scenarioWithOnePtLeg();
		TransitIds ids = installSchedule(scenario);
		Leg pt = selectedLeg(scenario.getPopulation(), "pt");

		pt.setRoute(passengerRoute(ids));
		HongKongTaxiPtRoutePreparation.PtRuntimeAudit valid =
				HongKongTaxiPtRoutePreparation.auditPreparedSelectedPt(scenario);
		HongKongTaxiPtRoutePreparation.requirePrepared(valid, 1);
		assertEquals(1, valid.transitPassengerRoute());
		HongKongTaxiSmokeRuntimeGuard.requireStablePreparedPt(valid, valid);
		pt.getRoute().setDistance(321.0);
		HongKongTaxiPtRoutePreparation.PtRuntimeAudit changedBetweenIterations =
				HongKongTaxiPtRoutePreparation.auditPreparedSelectedPt(scenario);
		assertThrows(IllegalStateException.class,
				() -> HongKongTaxiSmokeRuntimeGuard.requireStablePreparedPt(
						valid, changedBetweenIterations));

		pt.setRoute(null);
		assertRejected(scenario, "route_null");

		pt.setRoute(new GenericRouteImpl(
				Id.createLinkId("origin"), Id.createLinkId("destination")));
		assertRejected(scenario, "generic");

		pt.setRoute(passengerRoute(null, ids.egress(), ids.line(), ids.route()));
		HongKongTaxiPtRoutePreparation.PtRuntimeAudit missingAccess =
				assertRejected(scenario, "missing_access");
		assertEquals(1, missingAccess.accessStopMissing());

		pt.setRoute(passengerRoute(ids.access(), null, ids.line(), ids.route()));
		HongKongTaxiPtRoutePreparation.PtRuntimeAudit missingEgress =
				assertRejected(scenario, "missing_egress");
		assertEquals(1, missingEgress.egressStopMissing());

		pt.setRoute(passengerRoute(ids.access(), ids.egress(), null, ids.route()));
		HongKongTaxiPtRoutePreparation.PtRuntimeAudit missingLine =
				assertRejected(scenario, "missing_line");
		assertEquals(1, missingLine.lineIdMissing());

		pt.setRoute(passengerRoute(ids.access(), ids.egress(), ids.line(), null));
		HongKongTaxiPtRoutePreparation.PtRuntimeAudit missingRoute =
				assertRejected(scenario, "missing_route");
		assertEquals(1, missingRoute.transitRouteIdMissing());

		pt.setRoute(passengerRoute(
				Id.create("unknown-access", TransitStopFacility.class),
				ids.egress(), ids.line(), ids.route()));
		HongKongTaxiPtRoutePreparation.PtRuntimeAudit unknownStop =
				assertRejected(scenario, "unknown_stop");
		assertEquals(1, unknownStop.accessStopNotInSchedule());

		pt.setRoute(passengerRoute(
				ids.access(), ids.egress(),
				Id.create("unknown-line", TransitLine.class), ids.route()));
		HongKongTaxiPtRoutePreparation.PtRuntimeAudit unknownLine =
				assertRejected(scenario, "unknown_line");
		assertEquals(1, unknownLine.lineNotInSchedule());

		pt.setRoute(passengerRoute(
				ids.access(), ids.egress(), ids.line(),
				Id.create("unknown-route", TransitRoute.class)));
		HongKongTaxiPtRoutePreparation.PtRuntimeAudit unknownRoute =
				assertRejected(scenario, "unknown_route");
		assertEquals(1, unknownRoute.routeNotInSchedule());
	}

	@Test
	void strictTaxiSnapshotDetectsAttributeTypeRouteAndOrderChanges() {
		Scenario scenario = scenarioWithTaxi();
		Population population = scenario.getPopulation();
		HongKongTaxiPtRoutePreparation.TaxiSnapshot before =
				HongKongTaxiPtRoutePreparation.captureSelectedTaxi(population);
		Leg taxi = selectedLeg(population, "taxi");

		taxi.getAttributes().putAttribute(
				HongKongTaxiLegAttributes.MAIN_TRIP_INDEX, 0.0);
		assertThrows(IllegalArgumentException.class,
				() -> HongKongTaxiPtRoutePreparation.captureSelectedTaxi(population));

		taxi.getAttributes().putAttribute(
				HongKongTaxiLegAttributes.MAIN_TRIP_INDEX, 0);
		taxi.getRoute().setDistance(8_001.0);
		HongKongTaxiPtRoutePreparation.TaxiSnapshot after =
				HongKongTaxiPtRoutePreparation.captureSelectedTaxi(population);
		HongKongTaxiPtRoutePreparation.TaxiInvarianceAudit comparison =
				HongKongTaxiPtRoutePreparation.compareTaxi(before, after);
		assertFalse(comparison.exact());
		assertEquals(1, comparison.routeChanges());
		assertThrows(IllegalStateException.class,
				() -> HongKongTaxiPtRoutePreparation
						.requireFormalTaxiInvariant(comparison));
	}

	@Test
	void outputComparisonAllowsPtExpansionButRejectsTaxiMutation() {
		Population source = sourcePopulation();
		Population prepared = preparedPopulation();
		HongKongTaxiSmokeOutputAudit.PlanAudit sourceAudit =
				HongKongTaxiSmokeOutputAudit.auditPopulation(source);
		HongKongTaxiSmokeOutputAudit.PlanAudit preparedAudit =
				HongKongTaxiSmokeOutputAudit.auditPopulation(prepared);

		assertTrue(HongKongTaxiSmokeOutputAudit.sameFixedPlansAllowPreparedPt(
				sourceAudit, preparedAudit));
		assertFalse(HongKongTaxiSmokeOutputAudit
				.sameStructureModesAttributesAndRoutes(sourceAudit, preparedAudit));

		selectedLeg(prepared, "taxi").getAttributes().putAttribute(
				HongKongTaxiLegAttributes.FARE_BASELINE_HKD, 99.0);
		HongKongTaxiSmokeOutputAudit.PlanAudit mutated =
				HongKongTaxiSmokeOutputAudit.auditPopulation(prepared);
		assertFalse(HongKongTaxiSmokeOutputAudit.sameFixedPlansAllowPreparedPt(
				sourceAudit, mutated));
	}

	@Test
	void flagsDeclareOnlyDeterministicPtStartupRouting() {
		Map<String, Object> flags =
				RunHongKongTaxiBehavioralPilot.smokeRunFlags(
						true, true, true, true, 0);
		assertEquals(true, flags.get("routing_run"));
		assertEquals("deterministic_pt_startup_rebuild_only",
				flags.get("routing_scope"));
		assertEquals("pt_only_before_iteration_0",
				flags.get("pt_startup_routing_scope"));
		assertEquals(false, flags.get("behavioral_replanning"));
		assertEquals(false, flags.get("mode_choice"));
		assertEquals(false, flags.get("taxi_routing"));
		assertEquals(false, flags.get("taxi_mode_conversion"));
		assertEquals(false, flags.get("asc_calibration"));
		assertEquals(false, flags.get("fleet_model"));
		assertEquals(0, flags.get("strategy_settings_count"));
	}

	@Test
	void runtimeLogAuditAndFreshOutputGateAreFailClosed()
			throws Exception {
		Path temp = Path.of("target", "test-generated",
				"taxi-pt-" + UUID.randomUUID());
		Files.createDirectories(temp);
		Path clean = temp.resolve("clean.log");
		Files.writeString(clean, "normal MATSim log\n");
		assertTrue(HongKongTaxiSmokeOutputAudit.auditRuntimeLog(clean).exact());

		Path invalid = temp.resolve("invalid.log");
		Files.writeString(invalid,
				"pt-leg has no TransitRoute\n"
						+ "pt-agent doesn't know to what transit stop to go\n"
						+ "Hong Kong taxi fare schedule mismatch\n"
						+ "Invalid Hong Kong taxi leg attribute\n");
		HongKongTaxiSmokeOutputAudit.RuntimeLogAudit audit =
				HongKongTaxiSmokeOutputAudit.auditRuntimeLog(invalid);
		assertFalse(audit.exact());
		assertEquals(1, audit.ptLegHasNoTransitRoute());
		assertEquals(1, audit.ptAgentUnknownTransitStop());
		assertEquals(1, audit.taxiFareScheduleMismatch());
		assertEquals(1, audit.invalidTaxiLegAttribute());

		Path fresh = temp.resolve("fresh-output");
		RunHongKongTaxiBehavioralPilot.requireNewOutputDirectory(fresh);
		Files.createDirectory(fresh);
		assertThrows(IllegalArgumentException.class,
				() -> RunHongKongTaxiBehavioralPilot
						.requireNewOutputDirectory(fresh));
	}

	private static HongKongTaxiPtRoutePreparation.PtRuntimeAudit assertRejected(
			Scenario scenario, String label) {
		HongKongTaxiPtRoutePreparation.PtRuntimeAudit audit =
				HongKongTaxiPtRoutePreparation.auditPreparedSelectedPt(scenario);
		assertThrows(IllegalStateException.class,
				() -> HongKongTaxiPtRoutePreparation.requirePrepared(audit, 1),
				label);
		return audit;
	}

	private static Scenario scenarioWithOnePtLeg() {
		Scenario scenario = ScenarioUtils.createScenario(ConfigUtils.createConfig());
		Person person = HongKongTaxiTestFixtures.person("pt-person");
		Plan plan = plan(person, PopulationUtils.createLeg("pt"));
		person.addPlan(plan);
		person.setSelectedPlan(plan);
		scenario.getPopulation().addPerson(person);
		return scenario;
	}

	private static Scenario scenarioWithTaxi() {
		Scenario scenario = ScenarioUtils.createScenario(ConfigUtils.createConfig());
		Person person = HongKongTaxiTestFixtures.person("taxi-person");
		Plan plan = plan(person, taxiLeg());
		person.addPlan(plan);
		person.setSelectedPlan(plan);
		scenario.getPopulation().addPerson(person);
		return scenario;
	}

	private static TransitIds installSchedule(Scenario scenario) {
		TransitSchedule schedule = scenario.getTransitSchedule();
		TransitScheduleFactory factory = schedule.getFactory();
		Id<TransitStopFacility> accessId =
				Id.create("access", TransitStopFacility.class);
		Id<TransitStopFacility> egressId =
				Id.create("egress", TransitStopFacility.class);
		TransitStopFacility access = factory.createTransitStopFacility(
				accessId, new Coord(0.0, 0.0), false);
		TransitStopFacility egress = factory.createTransitStopFacility(
				egressId, new Coord(1.0, 1.0), false);
		access.setLinkId(Id.createLinkId("origin"));
		egress.setLinkId(Id.createLinkId("destination"));
		schedule.addStopFacility(access);
		schedule.addStopFacility(egress);

		Id<TransitLine> lineId = Id.create("line", TransitLine.class);
		Id<TransitRoute> routeId = Id.create("route", TransitRoute.class);
		TransitLine line = factory.createTransitLine(lineId);
		NetworkRoute networkRoute = RouteUtils.createLinkNetworkRouteImpl(
				Id.createLinkId("origin"), Id.createLinkId("destination"));
		TransitRoute route = factory.createTransitRoute(
				routeId, networkRoute, List.of(), "bus");
		line.addRoute(route);
		schedule.addTransitLine(line);
		return new TransitIds(accessId, egressId, lineId, routeId);
	}

	private static DefaultTransitPassengerRoute passengerRoute(TransitIds ids) {
		return passengerRoute(
				ids.access(), ids.egress(), ids.line(), ids.route());
	}

	private static DefaultTransitPassengerRoute passengerRoute(
			Id<TransitStopFacility> access,
			Id<TransitStopFacility> egress,
			Id<TransitLine> line,
			Id<TransitRoute> route) {
		return new DefaultTransitPassengerRoute(
				Id.createLinkId("origin"),
				Id.createLinkId("destination"),
				access, egress, line, route);
	}

	private static Population sourcePopulation() {
		Population population = PopulationUtils.createPopulation(
				ConfigUtils.createConfig());
		Person person = HongKongTaxiTestFixtures.person("shared-person");
		Leg pt = legWithGenericRoute("pt", "origin", "destination");
		Plan plan = plan(person, pt, taxiLeg());
		person.addPlan(plan);
		person.setSelectedPlan(plan);
		population.addPerson(person);
		return population;
	}

	private static Population preparedPopulation() {
		Population population = PopulationUtils.createPopulation(
				ConfigUtils.createConfig());
		Person person = HongKongTaxiTestFixtures.person("shared-person");
		Plan plan = PopulationUtils.createPlan(person);
		plan.addActivity(activity("home", 0.0));
		Leg accessWalk = legWithGenericRoute("walk", "origin", "access");
		accessWalk.setRoutingMode("pt");
		plan.addLeg(accessWalk);
		plan.addActivity(activity("pt interaction", 0.25));
		Leg pt = PopulationUtils.createLeg("pt");
		DefaultTransitPassengerRoute route = new DefaultTransitPassengerRoute(
				Id.createLinkId("origin"),
				Id.createLinkId("destination"),
				Id.create("access", TransitStopFacility.class),
				Id.create("egress", TransitStopFacility.class),
				Id.create("line", TransitLine.class),
				Id.create("route", TransitRoute.class));
		route.setDistance(1_000.0);
		route.setTravelTime(300.0);
		pt.setRoute(route);
		plan.addLeg(pt);
		plan.addActivity(activity("pt interaction", 0.75));
		Leg egressWalk = legWithGenericRoute("walk", "egress", "destination");
		egressWalk.setRoutingMode("pt");
		plan.addLeg(egressWalk);
		plan.addActivity(activity("work", 1.0));
		plan.addLeg(taxiLeg());
		plan.addActivity(activity("work", 1.0));
		person.addPlan(plan);
		person.setSelectedPlan(plan);
		population.addPerson(person);
		return population;
	}

	private static Plan plan(Person person, Leg... legs) {
		Plan plan = PopulationUtils.createPlan(person);
		plan.addActivity(activity("home", 0.0));
		for (int index = 0; index < legs.length; index++) {
			plan.addLeg(legs[index]);
			plan.addActivity(activity("work", 1.0));
		}
		return plan;
	}

	private static Activity activity(String type, double coordinate) {
		return PopulationUtils.createActivityFromCoord(
				type, new Coord(coordinate, coordinate));
	}

	private static Leg legWithGenericRoute(
			String mode, String start, String end) {
		Leg leg = PopulationUtils.createLeg(mode);
		Route route = RouteUtils.createGenericRouteImpl(
				Id.createLinkId(start), Id.createLinkId(end));
		route.setDistance(1_000.0);
		route.setTravelTime(300.0);
		leg.setRoute(route);
		return leg;
	}

	private static Leg taxiLeg() {
		Leg leg = HongKongTaxiTestFixtures.taxiLegWithValues(
				98.3,
				"urban_taxi",
				HongKongTaxiScoringParameters.DISTANCE_ONLY_SCOPE,
				HongKongTaxiScoringParameters.FARE_MODEL_VERSION,
				"resident_discretionary_ride_assignment",
				0);
		leg.setRoutingMode("ride");
		Route route = RouteUtils.createGenericRouteImpl(
				Id.createLinkId("taxi-origin"),
				Id.createLinkId("taxi-destination"));
		route.setDistance(8_000.0);
		route.setTravelTime(600.0);
		leg.setRoute(route);
		return leg;
	}

	private static Leg selectedLeg(Population population, String mode) {
		for (Person person : population.getPersons().values()) {
			for (org.matsim.api.core.v01.population.PlanElement element
					: person.getSelectedPlan().getPlanElements()) {
				if (element instanceof Leg leg && mode.equals(leg.getMode())) {
					return leg;
				}
			}
		}
		throw new IllegalArgumentException("Missing selected leg mode " + mode);
	}

	private record TransitIds(
			Id<TransitStopFacility> access,
			Id<TransitStopFacility> egress,
			Id<TransitLine> line,
			Id<TransitRoute> route) {
	}
}
