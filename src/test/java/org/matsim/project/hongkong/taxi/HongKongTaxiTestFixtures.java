package org.matsim.project.hongkong.taxi;

import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.ScoringConfigGroup;
import org.matsim.core.population.PopulationUtils;

final class HongKongTaxiTestFixtures {

	private HongKongTaxiTestFixtures() {
	}

	static Person person(String id) {
		return PopulationUtils.getFactory().createPerson(Id.createPersonId(id));
	}

	static Leg taxiLeg(double fareHkd) {
		return taxiLegWithValues(
				fareHkd,
				"urban_taxi",
				HongKongTaxiScoringParameters.DISTANCE_ONLY_SCOPE,
				HongKongTaxiScoringParameters.FARE_MODEL_VERSION,
				"test_classification",
				0
		);
	}

	static Leg taxiLegWithValues(
			Object fare,
			Object taxiType,
			Object fareScope,
			Object fareModelVersion,
			Object classificationSource,
			Object mainTripIndex) {
		Leg leg = PopulationUtils.createLeg(HongKongTaxiScoringParameters.TAXI_MODE);
		leg.getAttributes().putAttribute(HongKongTaxiLegAttributes.FARE_BASELINE_HKD, fare);
		leg.getAttributes().putAttribute(HongKongTaxiLegAttributes.TAXI_TYPE, taxiType);
		leg.getAttributes().putAttribute(HongKongTaxiLegAttributes.FARE_SCOPE, fareScope);
		leg.getAttributes().putAttribute(HongKongTaxiLegAttributes.FARE_MODEL_VERSION, fareModelVersion);
		leg.getAttributes().putAttribute(
				HongKongTaxiLegAttributes.CLASSIFICATION_SOURCE,
				classificationSource
		);
		leg.getAttributes().putAttribute(HongKongTaxiLegAttributes.MAIN_TRIP_INDEX, mainTripIndex);
		return leg;
	}

	static Config safeConfig() {
		Config config = ConfigUtils.createConfig();
		ScoringConfigGroup.ModeParams taxi =
				config.scoring().getOrCreateModeParams(HongKongTaxiScoringParameters.TAXI_MODE);
		taxi.setConstant(-9.0);
		taxi.setMarginalUtilityOfTraveling(-6.0);
		taxi.setMarginalUtilityOfDistance(0.0);
		taxi.setMonetaryDistanceRate(0.0);
		taxi.setDailyMonetaryConstant(0.0);
		taxi.setDailyUtilityConstant(0.0);
		return config;
	}
}
