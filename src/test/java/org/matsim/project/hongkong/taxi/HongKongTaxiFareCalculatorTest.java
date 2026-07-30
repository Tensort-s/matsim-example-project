package org.matsim.project.hongkong.taxi;

import org.junit.jupiter.api.Test;

import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HongKongTaxiFareCalculatorTest {

	private static final double TOLERANCE = 1.0e-12;
	private final HongKongTaxiFareCalculator calculator =
			new HongKongTaxiFareCalculator();

	@Test
	void threeTaxiTypesUseTheirOwnFlagfallThroughTwoKilometres() {
		assertFare(0.0, "urban_taxi", 29.0);
		assertFare(2_000.0, "urban_taxi", 29.0);
		assertFare(2_000.0, "new_territories_taxi", 25.5);
		assertFare(2_000.0, "lantau_taxi", 24.0);
	}

	@Test
	void firstPartialTwoHundredMetresIsCeiledToOneIncrement() {
		assertFare(2_000.000_001, "urban_taxi", 31.1);
		assertFare(2_001.0, "new_territories_taxi", 27.4);
		assertFare(2_199.999, "lantau_taxi", 25.9);
	}

	@Test
	void firstTierEndAndSecondTierAreChargedExactly() {
		assertFare(9_000.0, "urban_taxi", 102.5);
		assertFare(9_000.001, "urban_taxi", 103.9);
		assertFare(9_200.0, "urban_taxi", 103.9);
		assertFare(8_000.0, "new_territories_taxi", 82.5);
		assertFare(8_001.0, "new_territories_taxi", 83.9);
		assertFare(20_000.0, "lantau_taxi", 195.0);
		assertFare(20_001.0, "lantau_taxi", 196.6);
	}

	@Test
	void unresolvedUsesRecordedUrbanFallback() {
		HongKongTaxiFareCalculator.FareResult result =
				calculator.calculate(2_001.0, "unresolved");
		assertEquals(31.1, result.fareHkd(), TOLERANCE);
		assertEquals("unresolved", result.requestedTaxiType());
		assertEquals("urban_taxi", result.appliedTaxiType());
		assertTrue(result.unresolvedUrbanFallback());

		assertFalse(calculator.calculate(2_001.0, "urban_taxi")
				.unresolvedUrbanFallback());
	}

	@Test
	void negativeNanAndInfiniteDistanceAreRejected() {
		for (double invalid : new double[] {
				-0.001,
				Double.NaN,
				Double.POSITIVE_INFINITY,
				Double.NEGATIVE_INFINITY}) {
			assertThrows(
					IllegalArgumentException.class,
					() -> calculator.calculate(invalid, "urban_taxi"));
		}
	}

	@Test
	void fareNeverFallsAsRouteDistanceIncreases() {
		for (String type : new String[] {
				"urban_taxi", "new_territories_taxi", "lantau_taxi", "unresolved"}) {
			double previous = -1.0;
			for (int distance = 0; distance <= 30_000; distance += 37) {
				double current = calculator.calculate(distance, type).fareHkd();
				assertTrue(current >= previous, type + " at " + distance);
				previous = current;
			}
		}
	}

	@Test
	void trackedCsvIdentityAndRuntimeFieldsMatchJavaRules() {
		calculator.requireMatchesRuleCsv(Path.of(
				"data/taxi/hongkong/processed/taxi_fare_model_v1/taxi_fare_rules.csv"));
	}

	private void assertFare(double distance, String type, double expectedFare) {
		assertEquals(
				expectedFare,
				calculator.calculate(distance, type).fareHkd(),
				TOLERANCE);
	}
}
