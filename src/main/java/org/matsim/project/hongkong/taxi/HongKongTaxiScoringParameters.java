package org.matsim.project.hongkong.taxi;

import org.matsim.core.config.Config;
import org.matsim.core.config.groups.ScoringConfigGroup;

import java.util.Objects;

/**
 * Immutable parameters and configuration safety checks for the Hong Kong taxi
 * distance-only fare scorer.
 */
public record HongKongTaxiScoringParameters(
		double fareUtilityPerHkd,
		double fareShareFactor,
		String fareScope,
		String fareModelVersion) {

	public static final String TAXI_MODE = "taxi";
	public static final double CENTRAL_FARE_UTILITY_PER_HKD = 0.05;
	public static final double CENTRAL_FARE_SHARE_FACTOR = 1.0;
	public static final String DISTANCE_ONLY_SCOPE = "distance_only_v1";
	public static final String FARE_MODEL_VERSION = "hong_kong_taxi_fare_model_v1";

	public HongKongTaxiScoringParameters {
		requireFiniteNonNegative("fareUtilityPerHkd", fareUtilityPerHkd);
		requireFiniteNonNegative("fareShareFactor", fareShareFactor);
		if (Objects.requireNonNull(fareScope, "fareScope").isBlank()) {
			throw new IllegalArgumentException("fareScope must not be blank.");
		}
		if (Objects.requireNonNull(fareModelVersion, "fareModelVersion").isBlank()) {
			throw new IllegalArgumentException("fareModelVersion must not be blank.");
		}
	}

	public static HongKongTaxiScoringParameters centralV1() {
		return new HongKongTaxiScoringParameters(
				CENTRAL_FARE_UTILITY_PER_HKD,
				CENTRAL_FARE_SHARE_FACTOR,
				DISTANCE_ONLY_SCOPE,
				FARE_MODEL_VERSION
		);
	}

	public double fareScore(double fareHkd) {
		requireFiniteNonNegative("fareHkd", fareHkd);
		return -fareUtilityPerHkd * fareHkd * fareShareFactor;
	}

	/**
	 * Rejects configurations that could charge taxi distance a second time via
	 * standard MATSim distance scoring.
	 */
	public void validateConfig(Config config) {
		Objects.requireNonNull(config, "config");
		ScoringConfigGroup scoring = config.scoring();
		ScoringConfigGroup.ModeParams taxi = scoring.getModes().get(TAXI_MODE);
		if (taxi == null) {
			throw new IllegalArgumentException(
					"Missing scoring parameters for mode='taxi'; custom fare scoring cannot be installed."
			);
		}

		requireFinite("taxi constant", taxi.getConstant());
		requireFinite("taxi marginalUtilityOfTraveling", taxi.getMarginalUtilityOfTraveling());
		requireFinite("taxi marginalUtilityOfDistance", taxi.getMarginalUtilityOfDistance());
		requireFinite("taxi monetaryDistanceRate", taxi.getMonetaryDistanceRate());
		requireFinite("taxi dailyMonetaryConstant", taxi.getDailyMonetaryConstant());
		requireFinite("taxi dailyUtilityConstant", taxi.getDailyUtilityConstant());
		requireFinite("global marginalUtilityOfMoney", scoring.getMarginalUtilityOfMoney());

		if (taxi.getMonetaryDistanceRate() != 0.0) {
			throw new IllegalArgumentException(
					"taxi monetaryDistanceRate must be 0.0 when custom fare scoring is installed; actual="
							+ taxi.getMonetaryDistanceRate()
			);
		}
		if (taxi.getMarginalUtilityOfDistance() != 0.0) {
			throw new IllegalArgumentException(
					"taxi marginalUtilityOfDistance must be 0.0 when custom fare scoring is installed; actual="
							+ taxi.getMarginalUtilityOfDistance()
			);
		}
	}

	private static void requireFiniteNonNegative(String name, double value) {
		requireFinite(name, value);
		if (value < 0.0) {
			throw new IllegalArgumentException(name + " must be non-negative; actual=" + value);
		}
	}

	private static void requireFinite(String name, double value) {
		if (!Double.isFinite(value)) {
			throw new IllegalArgumentException(name + " must be finite; actual=" + value);
		}
	}
}
