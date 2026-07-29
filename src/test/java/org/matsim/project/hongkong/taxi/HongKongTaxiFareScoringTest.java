package org.matsim.project.hongkong.taxi;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.core.population.PopulationUtils;

import java.math.BigDecimal;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HongKongTaxiFareScoringTest {

	private static final double TOLERANCE = 1e-12;
	private static final Id<Person> PERSON_ID = Id.createPersonId("taxi-test-person");
	private static final HongKongTaxiScoringParameters PARAMETERS =
			HongKongTaxiScoringParameters.centralV1();

	@Test
	void fare24ScoresMinus1Point2() {
		assertFareScore(24.0, -1.2);
	}

	@Test
	void fare98Point3ScoresMinus4Point915() {
		assertFareScore(98.3, -4.915);
	}

	@Test
	void fare100ScoresMinus5() {
		assertFareScore(100.0, -5.0);
	}

	@Test
	void fare491Point7ScoresMinus24Point585() {
		assertFareScore(491.7, -24.585);
	}

	@Test
	void attributedSourceLegScoresAttributeFreeExperiencedLeg() {
		HongKongTaxiFareScoring scoring = scoringFor(HongKongTaxiTestFixtures.taxiLeg(100.0));
		Leg experienced = experiencedTaxiLeg();
		assertTrue(experienced.getAttributes().getAsMap().isEmpty());

		scoring.handleLeg(experienced);
		scoring.finish();

		assertEquals(-5.0, scoring.getScore(), TOLERANCE);
		assertTrue(experienced.getAttributes().getAsMap().isEmpty());
	}

	@Test
	void scheduleKeepsValidatedSnapshotWhenSourceLegIsLaterMutated() {
		Leg source = HongKongTaxiTestFixtures.taxiLeg(24.0);
		HongKongTaxiFareScoring scoring = scoringFor(source);
		source.getAttributes().putAttribute(HongKongTaxiLegAttributes.FARE_BASELINE_HKD, 100.0);

		scoring.handleLeg(experiencedTaxiLeg());
		scoring.finish();

		assertEquals(-1.2, scoring.getScore(), TOLERANCE);
	}

	@Test
	void multipleTaxiFaresAreConsumedInSelectedPlanOrder() {
		HongKongTaxiFareScoring scoring = scoringFor(
				HongKongTaxiTestFixtures.taxiLeg(24.0),
				HongKongTaxiTestFixtures.taxiLeg(98.3),
				HongKongTaxiTestFixtures.taxiLeg(491.7)
		);

		scoring.handleLeg(experiencedTaxiLeg());
		assertEquals(-1.2, scoring.getScore(), TOLERANCE);
		scoring.handleLeg(experiencedTaxiLeg());
		assertEquals(-6.115, scoring.getScore(), TOLERANCE);
		scoring.handleLeg(experiencedTaxiLeg());
		scoring.finish();

		assertEquals(-30.7, scoring.getScore(), TOLERANCE);
	}

	@Test
	void nonTaxiLegDoesNotConsumeFareRecord() {
		HongKongTaxiFareScoring scoring = scoringFor(HongKongTaxiTestFixtures.taxiLeg(100.0));
		Leg ride = PopulationUtils.createLeg("ride");
		ride.setRoutingMode("taxi");

		scoring.handleLeg(ride);
		assertEquals(0.0, scoring.getScore(), 0.0);
		scoring.handleLeg(experiencedTaxiLeg());
		scoring.finish();

		assertEquals(-5.0, scoring.getScore(), TOLERANCE);
	}

	@Test
	void ptStageExpansionDoesNotChangeTaxiFareOrdinal() {
		Person person = HongKongTaxiTestFixtures.person(PERSON_ID.toString());
		Plan selectedPlan = PopulationUtils.createPlan();
		Leg accessWalk = PopulationUtils.createLeg("walk");
		accessWalk.setRoutingMode("pt");
		selectedPlan.addLeg(accessWalk);
		selectedPlan.addLeg(PopulationUtils.createLeg("pt"));
		Leg egressWalk = PopulationUtils.createLeg("walk");
		egressWalk.setRoutingMode("pt");
		selectedPlan.addLeg(egressWalk);
		selectedPlan.addLeg(HongKongTaxiTestFixtures.taxiLeg(98.3));
		person.addPlan(selectedPlan);
		person.setSelectedPlan(selectedPlan);

		HongKongTaxiPersonFareSchedule schedule =
				HongKongTaxiPersonFareSchedule.fromSelectedPlan(person, PARAMETERS);
		HongKongTaxiFareScoring scoring =
				new HongKongTaxiFareScoring(schedule, PARAMETERS);
		scoring.handleLeg(accessWalk);
		scoring.handleLeg(PopulationUtils.createLeg("pt"));
		scoring.handleLeg(egressWalk);
		scoring.handleLeg(experiencedTaxiLeg());
		scoring.finish();

		assertEquals(-4.915, scoring.getScore(), TOLERANCE);
	}

	@Test
	void extraExperiencedTaxiLegFailsImmediatelyWithContext() {
		HongKongTaxiFareScoring scoring = scoringFor(HongKongTaxiTestFixtures.taxiLeg(24.0));
		scoring.handleLeg(experiencedTaxiLeg());

		IllegalStateException error = assertThrows(
				IllegalStateException.class,
				() -> scoring.handleLeg(experiencedTaxiLeg())
		);

		assertMismatchContext(error, 1, 1, 1, "taxi", "ride");
	}

	@Test
	void fewerExperiencedTaxiLegsFailAtFinishWithContext() {
		HongKongTaxiFareScoring scoring = scoringFor(
				HongKongTaxiTestFixtures.taxiLeg(24.0),
				HongKongTaxiTestFixtures.taxiLeg(100.0)
		);
		scoring.handleLeg(experiencedTaxiLeg());

		IllegalStateException error = assertThrows(IllegalStateException.class, scoring::finish);

		assertMismatchContext(error, 1, 2, 1, "<finish>", "<none>");
	}

	@Test
	void experiencedTaxiLegWithoutSourceRecordFailsImmediately() {
		HongKongTaxiFareScoring scoring = scoringFor();

		IllegalStateException error = assertThrows(
				IllegalStateException.class,
				() -> scoring.handleLeg(experiencedTaxiLeg())
		);

		assertMismatchContext(error, 0, 0, 0, "taxi", "ride");
	}

	@Test
	void wrongExperiencedRoutingModeFailsWithFullContextAndDoesNotConsume() {
		HongKongTaxiFareScoring scoring = scoringFor(HongKongTaxiTestFixtures.taxiLeg(100.0));
		Leg wrongRoutingMode = PopulationUtils.createLeg("taxi");
		wrongRoutingMode.setRoutingMode("taxi");

		IllegalStateException error = assertThrows(
				IllegalStateException.class,
				() -> scoring.handleLeg(wrongRoutingMode)
		);

		assertMismatchContext(error, 0, 1, 0, "taxi", "taxi");
		scoring.handleLeg(experiencedTaxiLeg());
		scoring.finish();
		assertEquals(-5.0, scoring.getScore(), TOLERANCE);
	}

	@Test
	void unresolvedTaxiTypeIsAcceptedInSourceSchedule() {
		Leg source = HongKongTaxiTestFixtures.taxiLegWithValues(
				24.0,
				"unresolved",
				HongKongTaxiScoringParameters.DISTANCE_ONLY_SCOPE,
				HongKongTaxiScoringParameters.FARE_MODEL_VERSION,
				"resident_discretionary_ride_assignment",
				7
		);
		HongKongTaxiFareScoring scoring = scoringFor(source);

		scoring.handleLeg(experiencedTaxiLeg());
		scoring.finish();

		assertEquals(-1.2, scoring.getScore(), TOLERANCE);
	}

	@Test
	void missingAnyRequiredSourceAttributeFailsWhileScheduleIsBuilt() {
		List<String> names = List.of(
				HongKongTaxiLegAttributes.FARE_BASELINE_HKD,
				HongKongTaxiLegAttributes.TAXI_TYPE,
				HongKongTaxiLegAttributes.FARE_SCOPE,
				HongKongTaxiLegAttributes.FARE_MODEL_VERSION,
				HongKongTaxiLegAttributes.CLASSIFICATION_SOURCE,
				HongKongTaxiLegAttributes.MAIN_TRIP_INDEX
		);
		for (String name : names) {
			Leg source = HongKongTaxiTestFixtures.taxiLeg(24.0);
			source.getAttributes().removeAttribute(name);
			IllegalArgumentException error = assertThrows(
					IllegalArgumentException.class,
					() -> scoringFor(source)
			);
			assertAttributeErrorContext(error, name, "<missing>");
		}
	}

	@Test
	void everyNonDoubleSourceFareRuntimeTypeIsRejected() {
		record InvalidFare(Object value, String runtimeType) {
		}
		List<InvalidFare> invalidFares = List.of(
				new InvalidFare(98, "java.lang.Integer"),
				new InvalidFare(98L, "java.lang.Long"),
				new InvalidFare(98.3F, "java.lang.Float"),
				new InvalidFare(new BigDecimal("98.3"), "java.math.BigDecimal"),
				new InvalidFare("98.3", "java.lang.String")
		);
		for (InvalidFare invalidFare : invalidFares) {
			Leg source = HongKongTaxiTestFixtures.taxiLegWithValues(
					invalidFare.value(),
					"urban_taxi",
					HongKongTaxiScoringParameters.DISTANCE_ONLY_SCOPE,
					HongKongTaxiScoringParameters.FARE_MODEL_VERSION,
					"test_classification",
					0
			);
			IllegalArgumentException error = assertThrows(
					IllegalArgumentException.class,
					() -> scoringFor(source)
			);
			assertTypedAttributeErrorContext(
					error,
					HongKongTaxiLegAttributes.FARE_BASELINE_HKD,
					invalidFare.runtimeType(),
					"java.lang.Double"
			);
		}
	}

	@Test
	void invalidNumericSourceFaresFail() {
		for (double invalidFare : List.of(
				-0.01,
				Double.NaN,
				Double.POSITIVE_INFINITY,
				Double.NEGATIVE_INFINITY
		)) {
			Leg source = HongKongTaxiTestFixtures.taxiLeg(invalidFare);
			IllegalArgumentException error = assertThrows(
					IllegalArgumentException.class,
					() -> scoringFor(source)
			);
			assertTypedAttributeErrorContext(
					error,
					HongKongTaxiLegAttributes.FARE_BASELINE_HKD,
					"java.lang.Double",
					"java.lang.Double"
			);
		}
	}

	@Test
	void sourceFareScopeMismatchFails() {
		Leg source = HongKongTaxiTestFixtures.taxiLegWithValues(
				24.0,
				"urban_taxi",
				"congestion_proxy_v1",
				HongKongTaxiScoringParameters.FARE_MODEL_VERSION,
				"test_classification",
				0
		);

		IllegalArgumentException error = assertThrows(
				IllegalArgumentException.class,
				() -> scoringFor(source)
		);

		assertAttributeErrorContext(
				error,
				HongKongTaxiLegAttributes.FARE_SCOPE,
				"congestion_proxy_v1"
		);
	}

	@Test
	void sourceFareModelVersionMismatchFails() {
		Leg source = HongKongTaxiTestFixtures.taxiLegWithValues(
				24.0,
				"urban_taxi",
				HongKongTaxiScoringParameters.DISTANCE_ONLY_SCOPE,
				"hong_kong_taxi_fare_model_v2",
				"test_classification",
				0
		);

		IllegalArgumentException error = assertThrows(
				IllegalArgumentException.class,
				() -> scoringFor(source)
		);

		assertAttributeErrorContext(
				error,
				HongKongTaxiLegAttributes.FARE_MODEL_VERSION,
				"hong_kong_taxi_fare_model_v2"
		);
	}

	@Test
	void invalidSourceMainTripIndexTypesAndValuesFail() {
		record InvalidIndex(Object value, String runtimeType) {
		}
		List<InvalidIndex> invalidIndices = List.of(
				new InvalidIndex(2.0, "java.lang.Double"),
				new InvalidIndex(2L, "java.lang.Long"),
				new InvalidIndex(-1, "java.lang.Integer")
		);
		for (InvalidIndex invalidIndex : invalidIndices) {
			Leg source = HongKongTaxiTestFixtures.taxiLegWithValues(
					24.0,
					"urban_taxi",
					HongKongTaxiScoringParameters.DISTANCE_ONLY_SCOPE,
					HongKongTaxiScoringParameters.FARE_MODEL_VERSION,
					"test_classification",
					invalidIndex.value()
			);
			IllegalArgumentException error = assertThrows(
					IllegalArgumentException.class,
					() -> scoringFor(source)
			);
			assertTypedAttributeErrorContext(
					error,
					HongKongTaxiLegAttributes.MAIN_TRIP_INDEX,
					invalidIndex.runtimeType(),
					"java.lang.Integer"
			);
		}
	}

	@Test
	void blankAndNonStringSourceTextAttributesFail() {
		Leg blankType = HongKongTaxiTestFixtures.taxiLegWithValues(
				24.0,
				" ",
				HongKongTaxiScoringParameters.DISTANCE_ONLY_SCOPE,
				HongKongTaxiScoringParameters.FARE_MODEL_VERSION,
				"test_classification",
				0
		);
		assertThrows(IllegalArgumentException.class, () -> scoringFor(blankType));

		Leg blankSource = HongKongTaxiTestFixtures.taxiLegWithValues(
				24.0,
				"urban_taxi",
				HongKongTaxiScoringParameters.DISTANCE_ONLY_SCOPE,
				HongKongTaxiScoringParameters.FARE_MODEL_VERSION,
				"",
				0
		);
		assertThrows(IllegalArgumentException.class, () -> scoringFor(blankSource));

		Leg nonStringScope = HongKongTaxiTestFixtures.taxiLeg(24.0);
		nonStringScope.getAttributes().putAttribute(HongKongTaxiLegAttributes.FARE_SCOPE, 2L);
		IllegalArgumentException error = assertThrows(
				IllegalArgumentException.class,
				() -> scoringFor(nonStringScope)
		);
		assertTypedAttributeErrorContext(
				error,
				HongKongTaxiLegAttributes.FARE_SCOPE,
				"java.lang.Long",
				"java.lang.String"
		);
	}

	@Test
	void repeatedGetScoreAndFinishDoNotChargeAgain() {
		HongKongTaxiFareScoring scoring = scoringFor(HongKongTaxiTestFixtures.taxiLeg(98.3));
		scoring.handleLeg(experiencedTaxiLeg());
		double first = scoring.getScore();
		double second = scoring.getScore();
		scoring.finish();
		scoring.finish();

		assertEquals(-4.915, first, TOLERANCE);
		assertEquals(first, second, 0.0);
		assertEquals(first, scoring.getScore(), 0.0);
	}

	@Test
	void scoreExplanationIdentifiesConsumedAndExpectedFareRecords() {
		HongKongTaxiFareScoring scoring = scoringFor(HongKongTaxiTestFixtures.taxiLeg(100.0));
		scoring.handleLeg(experiencedTaxiLeg());
		StringBuilder explanation = new StringBuilder();
		scoring.explainScore(explanation);

		assertTrue(explanation.toString().contains("hongKongTaxiFare"));
		assertTrue(explanation.toString().contains("consumedTaxiLegs=1"));
		assertTrue(explanation.toString().contains("expectedTaxiLegs=1"));
		assertTrue(explanation.toString().contains("score=-5.0"));
	}

	private static void assertFareScore(double fare, double expected) {
		HongKongTaxiFareScoring scoring = scoringFor(HongKongTaxiTestFixtures.taxiLeg(fare));
		scoring.handleLeg(experiencedTaxiLeg());
		scoring.finish();
		assertEquals(expected, scoring.getScore(), TOLERANCE);
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
				HongKongTaxiPersonFareSchedule.fromSelectedPlan(person, PARAMETERS);
		return new HongKongTaxiFareScoring(schedule, PARAMETERS);
	}

	private static Leg experiencedTaxiLeg() {
		Leg leg = PopulationUtils.createLeg(HongKongTaxiScoringParameters.TAXI_MODE);
		leg.setRoutingMode("ride");
		return leg;
	}

	private static void assertAttributeErrorContext(
			IllegalArgumentException error,
			String attributeName,
			String actualFragment) {
		assertTrue(error.getMessage().contains("person_id=" + PERSON_ID));
		assertTrue(error.getMessage().contains("leg_mode=taxi"));
		assertTrue(error.getMessage().contains("attribute=" + attributeName));
		assertTrue(error.getMessage().contains(actualFragment));
		assertTrue(error.getMessage().contains("expected="));
	}

	private static void assertTypedAttributeErrorContext(
			IllegalArgumentException error,
			String attributeName,
			String actualType,
			String expectedType) {
		assertTrue(error.getMessage().contains("person_id=" + PERSON_ID));
		assertTrue(error.getMessage().contains("leg_mode=taxi"));
		assertTrue(error.getMessage().contains("attribute=" + attributeName));
		assertTrue(error.getMessage().contains("actual_value="));
		assertTrue(error.getMessage().contains("actual_type=" + actualType));
		assertTrue(error.getMessage().contains("expected="));
		assertTrue(error.getMessage().contains(expectedType));
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
		assertTrue(error.getMessage().contains("reason="));
	}
}
