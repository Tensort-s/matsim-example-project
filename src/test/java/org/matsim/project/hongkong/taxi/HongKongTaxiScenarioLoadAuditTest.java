package org.matsim.project.hongkong.taxi;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.api.core.v01.population.Population;
import org.matsim.api.core.v01.population.Route;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.ScoringConfigGroup;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.population.routes.RouteUtils;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HongKongTaxiScenarioLoadAuditTest {

	@Test
	void syntheticPopulationExercisesTypedTaxiAndNonTaxiTraversal() {
		Config config = ConfigUtils.createConfig();
		Population population = PopulationUtils.createPopulation(config);
		population.addPerson(personWithLeg("taxi-person", taxiLeg(), "taxi"));
		population.addPerson(personWithLeg("walk-person", PopulationUtils.createLeg("walk"), "walk"));

		HongKongTaxiScenarioLoadAudit.PopulationAudit audit =
				HongKongTaxiScenarioLoadAudit.auditPopulation(
						population,
						HongKongTaxiScoringParameters.centralV1()
				);

		assertEquals(2, audit.persons);
		assertEquals(2, audit.plans);
		assertEquals(4, audit.activities);
		assertEquals(2, audit.legs);
		assertEquals(1, audit.routes);
		assertEquals(Map.of("taxi", 1L, "walk", 1L), audit.modeCounts);
		assertEquals(1, audit.taxiLegs);
		assertEquals(1, audit.taxiPersons);
		assertEquals(Map.of("taxi", 1L), audit.taxiRoutingModeCounts);
		assertEquals(98.3, audit.fareSumHkd);
		assertEquals(92.0, audit.routeFareSumHkd);
		assertEquals(-4.6, audit.fareOnlyScoreSum, 1.0e-12);
		assertEquals(0, audit.missingTaxiAttributeValues);
		assertEquals(0, audit.invalidTaxiAttributeRuntimeTypes);
		assertEquals(0, audit.invalidTaxiAttributeValues);
		assertEquals(0, audit.invalidFareScope);
		assertEquals(0, audit.invalidFareModelVersion);
		assertEquals(0, audit.negativeOrNonfiniteFare);
		assertEquals(0, audit.invalidMainTripIndex);
		assertEquals(0, audit.blankClassificationSource);
		assertEquals(0, audit.attributeValidationFailures);
		assertEquals(0, audit.nonTaxiLegsWithTaxiAttributes);
		Map<String, Object> auditMap = audit.toMap();
		assertEquals(Map.of("taxi", 1L), auditMap.get("taxi_actual_mode_counts"));
		assertEquals(0L, auditMap.get("invalid_scope"));
		assertEquals(0L, auditMap.get("invalid_model_version"));
		assertEquals(0L, auditMap.get("negative_or_non_finite_fare"));
		assertEquals(0L, auditMap.get("invalid_main_trip_index"));
		assertEquals(0L, auditMap.get("blank_classification_source"));
		assertEquals("taxi-person", audit.representativeTaxiPersonId);
		assertEquals("walk-person", audit.representativeNonTaxiPersonId);
	}

	@Test
	void taxiOverridePreservesExistingModeParameters() {
		Config config = ConfigUtils.createConfig();
		ScoringConfigGroup.ModeParams ride = config.scoring().getOrCreateModeParams("ride");
		ride.setConstant(-1.5);
		ride.setMarginalUtilityOfTraveling(-6.0);
		ride.setMonetaryDistanceRate(-0.0015);

		HongKongTaxiScenarioLoadAudit.configureTaxiScoring(config);

		assertEquals(-1.5, ride.getConstant());
		assertEquals(-6.0, ride.getMarginalUtilityOfTraveling());
		assertEquals(-0.0015, ride.getMonetaryDistanceRate());
		ScoringConfigGroup.ModeParams taxi = config.scoring().getModes().get("taxi");
		assertEquals(-9.0, taxi.getConstant());
		assertEquals(-6.0, taxi.getMarginalUtilityOfTraveling());
		assertEquals(0.0, taxi.getMarginalUtilityOfDistance());
		assertEquals(0.0, taxi.getMonetaryDistanceRate());
		assertEquals(0.0, taxi.getDailyMonetaryConstant());
		assertEquals(0.0, taxi.getDailyUtilityConstant());
	}

	@Test
	void quantilesUseLinearInterpolationAndJsonEscapesControlCharacters() {
		List<Double> sorted = List.of(1.0, 2.0, 5.0, 10.0);
		assertEquals(3.5, HongKongTaxiScenarioLoadAudit.quantile(sorted, 0.50));
		assertEquals(1.3, HongKongTaxiScenarioLoadAudit.quantile(sorted, 0.10), 1.0e-12);

		String json = HongKongTaxiScenarioLoadAudit.toJson(
				Map.of("quoted", "a\"b", "line", "x\ny"),
				0
		);
		assertTrue(json.contains("a\\\"b"));
		assertTrue(json.contains("x\\ny"));
		assertFalse(json.contains("x\ny"));
	}

	private static Person personWithLeg(String id, Leg leg, String expectedMode) {
		Person person = HongKongTaxiTestFixtures.person(id);
		Plan plan = PopulationUtils.createPlan(person);
		Activity origin = PopulationUtils.createActivityFromCoord("home", new Coord(0.0, 0.0));
		Activity destination =
				PopulationUtils.createActivityFromCoord("work", new Coord(1.0, 1.0));
		assertEquals(expectedMode, leg.getMode());
		plan.addActivity(origin);
		plan.addLeg(leg);
		plan.addActivity(destination);
		person.addPlan(plan);
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
		leg.setRoutingMode("taxi");
		Route route = RouteUtils.createGenericRouteImpl(
				Id.createLinkId("from"),
				Id.createLinkId("to")
		);
		route.setDistance(8_000.0);
		route.setTravelTime(600.0);
		leg.setRoute(route);
		leg.setDepartureTime(3_600.0);
		leg.setTravelTime(600.0);
		return leg;
	}
}
