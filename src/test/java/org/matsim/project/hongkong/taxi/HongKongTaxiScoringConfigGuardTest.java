package org.matsim.project.hongkong.taxi;

import org.junit.jupiter.api.Test;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.ScoringConfigGroup;

import java.util.List;
import java.util.function.Consumer;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HongKongTaxiScoringConfigGuardTest {

	private static final HongKongTaxiScoringParameters PARAMETERS =
			HongKongTaxiScoringParameters.centralV1();

	@Test
	void safeTaxiModeConfigPasses() {
		assertDoesNotThrow(() -> PARAMETERS.validateConfig(HongKongTaxiTestFixtures.safeConfig()));
	}

	@Test
	void finiteTaxiAscCanChangeWithoutAffectingGuard() {
		Config config = HongKongTaxiTestFixtures.safeConfig();
		config.scoring().getModes().get("taxi").setConstant(-12.0);
		assertDoesNotThrow(() -> PARAMETERS.validateConfig(config));
		config.scoring().getModes().get("taxi").setConstant(-6.0);
		assertDoesNotThrow(() -> PARAMETERS.validateConfig(config));
	}

	@Test
	void missingTaxiModeParametersAreRejected() {
		IllegalArgumentException error = assertThrows(
				IllegalArgumentException.class,
				() -> PARAMETERS.validateConfig(ConfigUtils.createConfig())
		);
		assertTrue(error.getMessage().contains("Missing scoring parameters"));
		assertTrue(error.getMessage().contains("taxi"));
	}

	@Test
	void nonzeroTaxiMonetaryDistanceRateIsRejected() {
		Config config = HongKongTaxiTestFixtures.safeConfig();
		config.scoring().getModes().get("taxi").setMonetaryDistanceRate(-0.0015);
		IllegalArgumentException error = assertThrows(
				IllegalArgumentException.class,
				() -> PARAMETERS.validateConfig(config)
		);
		assertTrue(error.getMessage().contains("monetaryDistanceRate"));
		assertTrue(error.getMessage().contains("0.0"));
	}

	@Test
	void nonzeroTaxiMarginalUtilityOfDistanceIsRejected() {
		Config config = HongKongTaxiTestFixtures.safeConfig();
		config.scoring().getModes().get("taxi").setMarginalUtilityOfDistance(-0.5);
		IllegalArgumentException error = assertThrows(
				IllegalArgumentException.class,
				() -> PARAMETERS.validateConfig(config)
		);
		assertTrue(error.getMessage().contains("marginalUtilityOfDistance"));
		assertTrue(error.getMessage().contains("0.0"));
	}

	@Test
	void everyNonfiniteTaxiScoringValueIsRejected() {
		List<Consumer<ScoringConfigGroup.ModeParams>> invalidSetters = List.of(
				mode -> mode.setConstant(Double.NaN),
				mode -> mode.setMarginalUtilityOfTraveling(Double.POSITIVE_INFINITY),
				mode -> mode.setMarginalUtilityOfDistance(Double.NEGATIVE_INFINITY),
				mode -> mode.setMonetaryDistanceRate(Double.NaN),
				mode -> mode.setDailyMonetaryConstant(Double.POSITIVE_INFINITY),
				mode -> mode.setDailyUtilityConstant(Double.NEGATIVE_INFINITY)
		);
		for (Consumer<ScoringConfigGroup.ModeParams> invalidSetter : invalidSetters) {
			Config config = HongKongTaxiTestFixtures.safeConfig();
			invalidSetter.accept(config.scoring().getModes().get("taxi"));
			assertThrows(IllegalArgumentException.class, () -> PARAMETERS.validateConfig(config));
		}
	}

	@Test
	void nonfiniteGlobalMarginalUtilityOfMoneyIsRejected() {
		Config config = HongKongTaxiTestFixtures.safeConfig();
		config.scoring().setMarginalUtilityOfMoney(Double.NaN);
		assertThrows(IllegalArgumentException.class, () -> PARAMETERS.validateConfig(config));
	}

	@Test
	void invalidCustomParametersAreRejected() {
		assertThrows(
				IllegalArgumentException.class,
				() -> new HongKongTaxiScoringParameters(
						-0.05,
						1.0,
						"distance_only_v1",
						"hong_kong_taxi_fare_model_v1"
				)
		);
		assertThrows(
				IllegalArgumentException.class,
				() -> new HongKongTaxiScoringParameters(
						0.05,
						Double.POSITIVE_INFINITY,
						"distance_only_v1",
						"hong_kong_taxi_fare_model_v1"
				)
		);
	}
}
