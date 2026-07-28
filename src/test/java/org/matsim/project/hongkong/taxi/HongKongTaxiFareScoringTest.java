package org.matsim.project.hongkong.taxi;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
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
	void multipleTaxiLegsSumWithoutIntermediateRounding() {
		HongKongTaxiFareScoring scoring = newScoring();
		scoring.handleLeg(HongKongTaxiTestFixtures.taxiLeg(24.0));
		scoring.handleLeg(HongKongTaxiTestFixtures.taxiLeg(98.3));
		scoring.handleLeg(HongKongTaxiTestFixtures.taxiLeg(491.7));
		assertEquals(-30.7, scoring.getScore(), TOLERANCE);
	}

	@Test
	void repeatedGetScoreIsIdempotent() {
		HongKongTaxiFareScoring scoring = scored(100.0);
		double first = scoring.getScore();
		double second = scoring.getScore();
		double third = scoring.getScore();
		assertEquals(-5.0, first, TOLERANCE);
		assertEquals(first, second, 0.0);
		assertEquals(second, third, 0.0);
	}

	@Test
	void finishDoesNotChargeAgain() {
		HongKongTaxiFareScoring scoring = scored(98.3);
		scoring.finish();
		scoring.finish();
		assertEquals(-4.915, scoring.getScore(), TOLERANCE);
	}

	@Test
	void taxiModeWithRideRoutingModeIsChargedOnce() {
		Leg leg = HongKongTaxiTestFixtures.taxiLeg(100.0);
		leg.setRoutingMode("ride");
		HongKongTaxiFareScoring scoring = newScoring();
		scoring.handleLeg(leg);
		assertEquals("taxi", leg.getMode());
		assertEquals("ride", leg.getRoutingMode());
		assertEquals(-5.0, scoring.getScore(), TOLERANCE);
	}

	@Test
	void nonTaxiModeIsNotChargedEvenWithTaxiRoutingModeAndNoAttributes() {
		Leg leg = PopulationUtils.createLeg("ride");
		leg.setRoutingMode("taxi");
		HongKongTaxiFareScoring scoring = newScoring();
		scoring.handleLeg(leg);
		assertEquals(0.0, scoring.getScore(), 0.0);
	}

	@Test
	void unresolvedTaxiTypeIsAccepted() {
		Leg leg = HongKongTaxiTestFixtures.taxiLegWithValues(
				24.0,
				"unresolved",
				HongKongTaxiScoringParameters.DISTANCE_ONLY_SCOPE,
				HongKongTaxiScoringParameters.FARE_MODEL_VERSION,
				"resident_discretionary_ride_assignment",
				7
		);
		HongKongTaxiFareScoring scoring = newScoring();
		scoring.handleLeg(leg);
		assertEquals(-1.2, scoring.getScore(), TOLERANCE);
	}

	@Test
	void missingAnyRequiredAttributeFailsWithContext() {
		List<String> names = List.of(
				HongKongTaxiLegAttributes.FARE_BASELINE_HKD,
				HongKongTaxiLegAttributes.TAXI_TYPE,
				HongKongTaxiLegAttributes.FARE_SCOPE,
				HongKongTaxiLegAttributes.FARE_MODEL_VERSION,
				HongKongTaxiLegAttributes.CLASSIFICATION_SOURCE,
				HongKongTaxiLegAttributes.MAIN_TRIP_INDEX
		);
		for (String name : names) {
			Leg leg = HongKongTaxiTestFixtures.taxiLeg(24.0);
			leg.getAttributes().removeAttribute(name);
			IllegalArgumentException error = assertThrows(
					IllegalArgumentException.class,
					() -> newScoring().handleLeg(leg)
			);
			assertErrorContext(error, name, "<missing>");
		}
	}

	@Test
	void everyNonDoubleFareRuntimeTypeIsRejected() {
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
			Leg leg = HongKongTaxiTestFixtures.taxiLegWithValues(
					invalidFare.value(),
					"urban_taxi",
					HongKongTaxiScoringParameters.DISTANCE_ONLY_SCOPE,
					HongKongTaxiScoringParameters.FARE_MODEL_VERSION,
					"test_classification",
					0
			);
			IllegalArgumentException error = assertThrows(
					IllegalArgumentException.class,
					() -> newScoring().handleLeg(leg)
			);
			assertTypedErrorContext(
					error,
					HongKongTaxiLegAttributes.FARE_BASELINE_HKD,
					invalidFare.runtimeType(),
					"java.lang.Double"
			);
		}
	}

	@Test
	void negativeNanAndInfiniteFaresFail() {
		for (double invalidFare : List.of(
				-0.01,
				Double.NaN,
				Double.POSITIVE_INFINITY,
				Double.NEGATIVE_INFINITY
		)) {
			Leg leg = HongKongTaxiTestFixtures.taxiLeg(invalidFare);
			IllegalArgumentException error = assertThrows(
					IllegalArgumentException.class,
					() -> newScoring().handleLeg(leg)
			);
			assertTypedErrorContext(
					error,
					HongKongTaxiLegAttributes.FARE_BASELINE_HKD,
					"java.lang.Double",
					"java.lang.Double"
			);
		}
	}

	@Test
	void fareScopeMismatchFails() {
		Leg leg = HongKongTaxiTestFixtures.taxiLegWithValues(
				24.0,
				"urban_taxi",
				"congestion_proxy_v1",
				HongKongTaxiScoringParameters.FARE_MODEL_VERSION,
				"test_classification",
				0
		);
		IllegalArgumentException error = assertThrows(
				IllegalArgumentException.class,
				() -> newScoring().handleLeg(leg)
		);
		assertErrorContext(error, HongKongTaxiLegAttributes.FARE_SCOPE, "congestion_proxy_v1");
	}

	@Test
	void fareModelVersionMismatchFails() {
		Leg leg = HongKongTaxiTestFixtures.taxiLegWithValues(
				24.0,
				"urban_taxi",
				HongKongTaxiScoringParameters.DISTANCE_ONLY_SCOPE,
				"hong_kong_taxi_fare_model_v2",
				"test_classification",
				0
		);
		IllegalArgumentException error = assertThrows(
				IllegalArgumentException.class,
				() -> newScoring().handleLeg(leg)
		);
		assertErrorContext(
				error,
				HongKongTaxiLegAttributes.FARE_MODEL_VERSION,
				"hong_kong_taxi_fare_model_v2"
		);
	}

	@Test
	void doubleAndLongMainTripIndicesFail() {
		record InvalidIndex(Object value, String runtimeType) {
		}
		List<InvalidIndex> invalidIndices = List.of(
				new InvalidIndex(2.0, "java.lang.Double"),
				new InvalidIndex(2L, "java.lang.Long")
		);
		for (InvalidIndex invalidIndex : invalidIndices) {
			Leg leg = HongKongTaxiTestFixtures.taxiLegWithValues(
					24.0,
					"urban_taxi",
					HongKongTaxiScoringParameters.DISTANCE_ONLY_SCOPE,
					HongKongTaxiScoringParameters.FARE_MODEL_VERSION,
					"test_classification",
					invalidIndex.value()
			);
			IllegalArgumentException error = assertThrows(
					IllegalArgumentException.class,
					() -> newScoring().handleLeg(leg)
			);
			assertTypedErrorContext(
					error,
					HongKongTaxiLegAttributes.MAIN_TRIP_INDEX,
					invalidIndex.runtimeType(),
					"java.lang.Integer"
			);
		}
	}

	@Test
	void negativeMainTripIndexFails() {
		Leg leg = HongKongTaxiTestFixtures.taxiLegWithValues(
				24.0,
				"urban_taxi",
				HongKongTaxiScoringParameters.DISTANCE_ONLY_SCOPE,
				HongKongTaxiScoringParameters.FARE_MODEL_VERSION,
				"test_classification",
				-1
		);
		IllegalArgumentException error = assertThrows(
				IllegalArgumentException.class,
				() -> newScoring().handleLeg(leg)
		);
		assertErrorContext(error, HongKongTaxiLegAttributes.MAIN_TRIP_INDEX, "-1");
	}

	@Test
	void blankTaxiTypeAndClassificationSourceFail() {
		Leg blankType = HongKongTaxiTestFixtures.taxiLegWithValues(
				24.0,
				" ",
				HongKongTaxiScoringParameters.DISTANCE_ONLY_SCOPE,
				HongKongTaxiScoringParameters.FARE_MODEL_VERSION,
				"test_classification",
				0
		);
		assertThrows(IllegalArgumentException.class, () -> newScoring().handleLeg(blankType));

		Leg blankSource = HongKongTaxiTestFixtures.taxiLegWithValues(
				24.0,
				"urban_taxi",
				HongKongTaxiScoringParameters.DISTANCE_ONLY_SCOPE,
				HongKongTaxiScoringParameters.FARE_MODEL_VERSION,
				"",
				0
		);
		assertThrows(IllegalArgumentException.class, () -> newScoring().handleLeg(blankSource));
	}

	@Test
	void nonStringTextAttributesAreRejectedWithExactTypeContext() {
		record InvalidTextAttribute(String name, Object value) {
		}
		List<InvalidTextAttribute> invalidAttributes = List.of(
				new InvalidTextAttribute(HongKongTaxiLegAttributes.TAXI_TYPE, 1),
				new InvalidTextAttribute(HongKongTaxiLegAttributes.FARE_SCOPE, 2L),
				new InvalidTextAttribute(HongKongTaxiLegAttributes.FARE_MODEL_VERSION, 3.0F),
				new InvalidTextAttribute(HongKongTaxiLegAttributes.CLASSIFICATION_SOURCE, 4.0)
		);
		for (InvalidTextAttribute invalid : invalidAttributes) {
			Leg leg = HongKongTaxiTestFixtures.taxiLeg(24.0);
			leg.getAttributes().putAttribute(invalid.name(), invalid.value());
			IllegalArgumentException error = assertThrows(
					IllegalArgumentException.class,
					() -> newScoring().handleLeg(leg)
			);
			assertTypedErrorContext(
					error,
					invalid.name(),
					invalid.value().getClass().getName(),
					"java.lang.String"
			);
		}
	}

	@Test
	void scoreExplanationIdentifiesFareContribution() {
		HongKongTaxiFareScoring scoring = scored(100.0);
		StringBuilder explanation = new StringBuilder();
		scoring.explainScore(explanation);
		assertTrue(explanation.toString().contains("hongKongTaxiFare"));
		assertTrue(explanation.toString().contains("taxiLegs=1"));
		assertTrue(explanation.toString().contains("score=-5.0"));
	}

	private static void assertFareScore(double fare, double expected) {
		assertEquals(expected, scored(fare).getScore(), TOLERANCE);
	}

	private static HongKongTaxiFareScoring scored(double fare) {
		HongKongTaxiFareScoring scoring = newScoring();
		scoring.handleLeg(HongKongTaxiTestFixtures.taxiLeg(fare));
		return scoring;
	}

	private static HongKongTaxiFareScoring newScoring() {
		return new HongKongTaxiFareScoring(PERSON_ID, PARAMETERS);
	}

	private static void assertErrorContext(
			IllegalArgumentException error,
			String attributeName,
			String actualFragment) {
		assertTrue(error.getMessage().contains("person_id=" + PERSON_ID));
		assertTrue(error.getMessage().contains("leg_mode=taxi"));
		assertTrue(error.getMessage().contains("attribute=" + attributeName));
		assertTrue(error.getMessage().contains(actualFragment));
		assertTrue(error.getMessage().contains("expected="));
	}

	private static void assertTypedErrorContext(
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
}
