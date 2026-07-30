package org.matsim.project.hongkong.taxi;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.events.PersonStuckEvent;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.api.core.v01.population.Population;
import org.matsim.api.core.v01.population.Route;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.controler.events.AfterMobsimEvent;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.population.routes.RouteUtils;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HongKongTaxiSmokeIntegrationTest {

	@Test
	void fixedTaxiScoringPreservesExistingModes() {
		Config config = ConfigUtils.createConfig();
		config.scoring().getOrCreateModeParams("ride").setConstant(-1.5);
		config.scoring().getModes().get("ride").setMonetaryDistanceRate(-0.0015);
		Map<String, Map<String, Double>> before =
				RunHongKongTaxiBehavioralPilot.snapshotScoring(config);

		RunHongKongTaxiBehavioralPilot.configureTaxiScoring(config);

		assertEquals(before.get("ride"),
				RunHongKongTaxiBehavioralPilot.snapshotScoring(config).get("ride"));
		assertEquals(-9.0, config.scoring().getModes().get("taxi").getConstant());
		assertEquals(-6.0, config.scoring().getModes().get("taxi")
				.getMarginalUtilityOfTraveling());
		assertEquals(0.0, config.scoring().getModes().get("taxi")
				.getMarginalUtilityOfDistance());
		assertEquals(0.0, config.scoring().getModes().get("taxi")
				.getMonetaryDistanceRate());
	}

	@Test
	void afterMobsimWithoutLiveAuditDoesNotMaskTheFirstFailure() {
		HongKongTaxiSmokeRuntimeGuard guard =
				new HongKongTaxiSmokeRuntimeGuard(
						ConfigUtils.createConfig(),
						new HongKongTaxiPtRoutePreparation.PreparationAudit(
								0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
						new HongKongTaxiPtRoutePreparation.TaxiSnapshot(
								0, 0, 0, Map.of(), Map.of(), "empty")
				);

		assertDoesNotThrow(() -> guard.notifyAfterMobsim(
				new AfterMobsimEvent(null, 0, false)));
		assertEquals(
				1L,
				guard.ptPreparationAudit().get(
						"after_mobsim_without_live_audit"));
	}

	@Test
	void eventGuardDefersTaxiViolationsAndOnlyObservesNonTaxiStuck() {
		HongKongTaxiSmokeRuntimeGuard.IterationEvents clean =
				new HongKongTaxiSmokeRuntimeGuard.IterationEvents(0);
		clean.startedNanos = System.nanoTime();
		clean.taxiDepartures = HongKongTaxiSmokeRuntimeGuard.EXPECTED_TAXI_LEGS;
		clean.taxiArrivals = HongKongTaxiSmokeRuntimeGuard.EXPECTED_TAXI_LEGS;
		clean.finish();
		assertTrue(clean.passed);
		assertTrue(clean.finished);
		assertEquals(0L, clean.toMap().get("total_stuck_events"));

		HongKongTaxiSmokeRuntimeGuard.IterationEvents nonTaxiStuck =
				new HongKongTaxiSmokeRuntimeGuard.IterationEvents(1);
		nonTaxiStuck.startedNanos = System.nanoTime();
		nonTaxiStuck.taxiDepartures =
				HongKongTaxiSmokeRuntimeGuard.EXPECTED_TAXI_LEGS;
		nonTaxiStuck.taxiArrivals =
				HongKongTaxiSmokeRuntimeGuard.EXPECTED_TAXI_LEGS;
		nonTaxiStuck.handleStuck(new PersonStuckEvent(
				3600.0,
				Id.createPersonId("stuck-person"),
				Id.createLinkId("link"),
				"car",
				"test"
		));
		nonTaxiStuck.finish();
		assertTrue(nonTaxiStuck.passed);
		assertEquals(1L, nonTaxiStuck.toMap().get("total_stuck_events"));
		assertEquals(
				java.util.List.of("non_taxi_stuck_observed"),
				nonTaxiStuck.toMap().get("observations"));

		HongKongTaxiSmokeRuntimeGuard.IterationEvents taxiStuck =
				new HongKongTaxiSmokeRuntimeGuard.IterationEvents(1);
		taxiStuck.startedNanos = System.nanoTime();
		taxiStuck.taxiDepartures =
				HongKongTaxiSmokeRuntimeGuard.EXPECTED_TAXI_LEGS;
		taxiStuck.taxiArrivals =
				HongKongTaxiSmokeRuntimeGuard.EXPECTED_TAXI_LEGS;
		taxiStuck.handleStuck(new PersonStuckEvent(
				3600.0,
				Id.createPersonId("taxi-stuck-person"),
				Id.createLinkId("link"),
				"taxi",
				"test"
		));
		taxiStuck.finish();
		assertTrue(taxiStuck.finished);
		assertFalse(taxiStuck.passed);
		assertEquals(
				java.util.List.of("no_taxi_stuck"),
				taxiStuck.toMap().get("violations"));
	}

	@Test
	void plansAuditChecksTypedTaxiMetadataRoutesAndFiniteScores() {
		Config config = ConfigUtils.createConfig();
		Population population = PopulationUtils.createPopulation(config);
		population.addPerson(personWithLeg("taxi-person", taxiLeg(), -12.5));
		population.addPerson(personWithLeg(
				"walk-person", PopulationUtils.createLeg("walk"), -2.0));

		HongKongTaxiSmokeOutputAudit.PlanAudit first =
				HongKongTaxiSmokeOutputAudit.auditPopulation(population);
		HongKongTaxiSmokeOutputAudit.PlanAudit second =
				HongKongTaxiSmokeOutputAudit.auditPopulation(population);

		assertEquals(2, first.persons);
		assertEquals(2, first.plans);
		assertEquals(4, first.activities);
		assertEquals(2, first.legs);
		assertEquals(1, first.routes);
		assertEquals(Map.of("taxi", 1L, "walk", 1L), first.modeCounts);
		assertEquals(Map.of("ride", 1L), first.taxiRoutingModeCounts);
		assertEquals(1, first.taxiPersons);
		assertEquals(0, first.invalidTaxiAttributes);
		assertTrue(first.allSelectedScoresFinite());
		assertTrue(HongKongTaxiSmokeOutputAudit
				.sameStructureModesAttributesAndRoutes(first, second));
		assertTrue(HongKongTaxiSmokeOutputAudit.toJson(first.toMap(), 0)
				.contains("\"taxi_attribute_fingerprint_sha256\""));
	}

	private static Person personWithLeg(String id, Leg leg, double score) {
		Person person = HongKongTaxiTestFixtures.person(id);
		Plan plan = PopulationUtils.createPlan(person);
		Activity origin =
				PopulationUtils.createActivityFromCoord("home", new Coord(0.0, 0.0));
		Activity destination =
				PopulationUtils.createActivityFromCoord("work", new Coord(1.0, 1.0));
		plan.addActivity(origin);
		plan.addLeg(leg);
		plan.addActivity(destination);
		plan.setScore(score);
		person.addPlan(plan);
		person.setSelectedPlan(plan);
		return person;
	}

	private static Leg taxiLeg() {
		Leg leg = HongKongTaxiTestFixtures.taxiLegWithValues(
				98.3,
				"urban_taxi",
				HongKongTaxiScoringParameters.DISTANCE_ONLY_SCOPE,
				HongKongTaxiScoringParameters.FARE_MODEL_VERSION,
				"resident_discretionary_ride_assignment",
				0
		);
		leg.setRoutingMode("ride");
		leg.setDepartureTime(100.0);
		Route route = RouteUtils.createGenericRouteImpl(
				Id.createLinkId("from"), Id.createLinkId("to"));
		route.setDistance(8_000.0);
		route.setTravelTime(600.0);
		leg.setRoute(route);
		return leg;
	}
}
