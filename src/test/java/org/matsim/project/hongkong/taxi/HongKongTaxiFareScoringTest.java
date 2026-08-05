package org.matsim.project.hongkong.taxi;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.core.population.PopulationUtils;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HongKongTaxiFareScoringTest {

	private static final double TOLERANCE = 1e-12;
	private static final Id<Person> PERSON_ID = Id.createPersonId("taxi-test-person");
	private static final HongKongTaxiScoringParameters PARAMETERS =
			HongKongTaxiScoringParameters.centralV1();
	private static final HongKongTaxiFareCalculator CALCULATOR =
			new HongKongTaxiFareCalculator();

	@Test
	void attributeFreeExperiencedLegConsumesOneRouteBasedFare() {
		HongKongTaxiFareScoring scoring = scoringFor(
				source(2_000.0, "urban_taxi", 999.9));
		Leg experienced = experiencedTaxiLeg();
		assertTrue(experienced.getAttributes().getAsMap().isEmpty());

		scoring.handleLeg(experienced);
		scoring.finish();

		assertEquals(-1.45, scoring.getScore(), TOLERANCE);
		assertTrue(experienced.getAttributes().getAsMap().isEmpty());
	}

	@Test
	void scheduleDoesNotReadComparisonBaselineAndBaselineMayBeMissing() {
		Leg wildlyWrongBaseline = source(9_000.0, "urban_taxi", 1.0);
		Leg missingBaseline = source(2_001.0, "lantau_taxi", 999.0);
		missingBaseline.getAttributes().removeAttribute(
				HongKongTaxiLegAttributes.FARE_BASELINE_HKD);
		HongKongTaxiFareScoring scoring =
				scoringFor(wildlyWrongBaseline, missingBaseline);

		scoring.handleLeg(experiencedTaxiLeg());
		scoring.handleLeg(experiencedTaxiLeg());
		scoring.finish();

		assertEquals(-0.05 * (102.5 + 25.9), scoring.getScore(), TOLERANCE);
	}

	@Test
	void routeChangeChangesFareAndScheduleIsAnImmutableSnapshot() {
		Leg source = source(2_000.0, "urban_taxi", 29.0);
		HongKongTaxiFareScoring beforeChange = scoringFor(source);
		source.getRoute().setDistance(9_000.0);
		HongKongTaxiFareScoring afterChange = scoringFor(source);

		beforeChange.handleLeg(experiencedTaxiLeg());
		afterChange.handleLeg(experiencedTaxiLeg());

		assertEquals(-1.45, beforeChange.getScore(), TOLERANCE);
		assertEquals(-5.125, afterChange.getScore(), TOLERANCE);
	}

	@Test
	void multipleTaxiFaresAreConsumedInSelectedPlanOrder() {
		HongKongTaxiFareScoring scoring = scoringFor(
				source(2_000.0, "lantau_taxi", 24.0),
				source(8_600.0, "urban_taxi", 98.3),
				source(9_001.0, "urban_taxi", 103.9));

		scoring.handleLeg(experiencedTaxiLeg());
		assertEquals(-1.2, scoring.getScore(), TOLERANCE);
		scoring.handleLeg(experiencedTaxiLeg());
		assertEquals(-6.115, scoring.getScore(), TOLERANCE);
		scoring.handleLeg(experiencedTaxiLeg());
		scoring.finish();

		assertEquals(-11.31, scoring.getScore(), TOLERANCE);
	}

	@Test
	void nonTaxiAndPtStagesDoNotConsumeFareOrdinal() {
		HongKongTaxiFareScoring scoring =
				scoringFor(source(8_600.0, "urban_taxi", 0.0));
		Leg ride = PopulationUtils.createLeg("ride");
		ride.setRoutingMode("ride");
		Leg pt = PopulationUtils.createLeg("pt");
		pt.setRoutingMode("pt");

		scoring.handleLeg(ride);
		scoring.handleLeg(pt);
		scoring.handleLeg(experiencedTaxiLeg());
		scoring.finish();

		assertEquals(-4.915, scoring.getScore(), TOLERANCE);
	}

	@Test
	void extraExperiencedTaxiLegFailsImmediatelyWithOrdinalContext() {
		HongKongTaxiFareScoring scoring =
				scoringFor(source(2_000.0, "urban_taxi", 29.0));
		scoring.handleLeg(experiencedTaxiLeg());

		IllegalStateException error = assertThrows(
				IllegalStateException.class,
				() -> scoring.handleLeg(experiencedTaxiLeg()));

		assertMismatchContext(error, 1, 1, 1, "taxi", "taxi");
	}

	@Test
	void untraveledTaxiSuffixIsNotChargedAtFinish() {
		HongKongTaxiFareScoring scoring = scoringFor(
				source(2_000.0, "urban_taxi", 29.0),
				source(2_001.0, "urban_taxi", 31.1));
		scoring.handleLeg(experiencedTaxiLeg());

		scoring.finish();
		assertEquals(-1.45, scoring.getScore(), TOLERANCE);
	}

	@Test
	void wrongExperiencedRoutingModeFailsWithoutConsumingFare() {
		HongKongTaxiFareScoring scoring =
				scoringFor(source(2_000.0, "urban_taxi", 29.0));
		Leg wrong = PopulationUtils.createLeg("taxi");
		wrong.setRoutingMode("ride");

		assertThrows(IllegalStateException.class, () -> scoring.handleLeg(wrong));
		scoring.handleLeg(experiencedTaxiLeg());
		scoring.finish();

		assertEquals(-1.45, scoring.getScore(), TOLERANCE);
	}

	@Test
	void unresolvedFareIsCalculatedWithUrbanFallback() {
		HongKongTaxiFareScoring scoring =
				scoringFor(source(2_001.0, "unresolved", 24.0));
		scoring.handleLeg(experiencedTaxiLeg());
		scoring.finish();
		assertEquals(-1.555, scoring.getScore(), TOLERANCE);
	}

	@Test
	void repeatedScoreReadsAndFinishDoNotChargeAgain() {
		HongKongTaxiFareScoring scoring =
				scoringFor(source(8_600.0, "urban_taxi", 98.3));
		scoring.handleLeg(experiencedTaxiLeg());
		double first = scoring.getScore();
		scoring.finish();
		scoring.finish();

		assertEquals(-4.915, first, TOLERANCE);
		assertEquals(first, scoring.getScore(), 0.0);
	}

	private static Leg source(
			double distanceMeters,
			String taxiType,
			Object comparisonBaselineFareHkd) {
		return HongKongTaxiTestFixtures.taxiLegForRoute(
				distanceMeters, taxiType, comparisonBaselineFareHkd);
	}

	private static HongKongTaxiFareScoring scoringFor(Leg... sourceLegs) {
		Person person = HongKongTaxiTestFixtures.person(PERSON_ID.toString());
		Plan selectedPlan = PopulationUtils.createPlan();
		for (Leg sourceLeg : sourceLegs) {
			selectedPlan.addLeg(sourceLeg);
		}
		person.addPlan(selectedPlan);
		person.setSelectedPlan(selectedPlan);
		HongKongTaxiPersonFareSchedule schedule =
				HongKongTaxiPersonFareSchedule.fromSelectedPlan(person, CALCULATOR);
		return new HongKongTaxiFareScoring(schedule, PARAMETERS);
	}

	private static Leg experiencedTaxiLeg() {
		Leg leg = PopulationUtils.createLeg(HongKongTaxiScoringParameters.TAXI_MODE);
		leg.setRoutingMode(HongKongTaxiScoringParameters.TAXI_MODE);
		return leg;
	}

	private static void assertMismatchContext(
			IllegalStateException error,
			int taxiOrdinal,
			int expectedCount,
			int consumedCount,
			String actualMode,
			String actualRoutingMode) {
		assertTrue(error.getMessage().contains("person_id=" + PERSON_ID));
		assertTrue(error.getMessage().contains("taxi_ordinal=" + taxiOrdinal));
		assertTrue(error.getMessage().contains("expected_count=" + expectedCount));
		assertTrue(error.getMessage().contains("consumed_count=" + consumedCount));
		assertTrue(error.getMessage().contains("actual_mode=" + actualMode));
		assertTrue(error.getMessage().contains("actual_routingMode=" + actualRoutingMode));
	}
}
