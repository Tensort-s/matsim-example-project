package org.matsim.project.hongkong.scoring;

import org.matsim.api.core.v01.TransportMode;
import org.matsim.core.config.Config;
import org.matsim.core.config.groups.ScoringConfigGroup;
import org.matsim.project.hongkong.taxi.HongKongTaxiFareUtilityPolicy;
import org.matsim.project.hongkong.taxi.HongKongTaxiScoringParameters;
import org.matsim.project.hongkong.walk.HongKongWalkScoringParameters;

/**
 * Immutable, named Hong Kong scoring snapshots used by formal calibration runs.
 * Taxi fare disutility deliberately stays outside MATSim's global money term.
 */
public enum HongKongScoringGrade {
	GradeV1(1.0, 0.5, 0.6, -1.5, -1.5,
			HongKongWalkScoringParameters.calibrationV4()),
	GradeV2(0.28, 0.28, 0.4, 0.0, 0.0,
			HongKongWalkScoringParameters.calibrationV5());

	public static final double CAR_CONSTANT = -0.5;
	public static final double TAXI_CONSTANT = -9.6;
	public static final double TRAVEL_UTILITY_PER_HOUR = -6.0;
	public static final double TAXI_WAIT_UTILITY_PER_HOUR = -6.0;

	private final double marginalUtilityOfMoney;
	private final double adultTaxiFareUtilityPerHkd;
	private final double studentTaxiFareUtilityPerHkd;
	private final double carPassengerConstant;
	private final double schoolBusConstant;
	private final HongKongWalkScoringParameters walkParameters;

	HongKongScoringGrade(
			double marginalUtilityOfMoney,
			double adultTaxiFareUtilityPerHkd,
			double studentTaxiFareUtilityPerHkd,
			double carPassengerConstant,
			double schoolBusConstant,
			HongKongWalkScoringParameters walkParameters) {
		this.marginalUtilityOfMoney = marginalUtilityOfMoney;
		this.adultTaxiFareUtilityPerHkd = adultTaxiFareUtilityPerHkd;
		this.studentTaxiFareUtilityPerHkd = studentTaxiFareUtilityPerHkd;
		this.carPassengerConstant = carPassengerConstant;
		this.schoolBusConstant = schoolBusConstant;
		this.walkParameters = walkParameters;
	}

	public static HongKongScoringGrade parse(String value) {
		for (HongKongScoringGrade grade : values()) {
			if (grade.name().equals(value)) return grade;
		}
		throw new IllegalArgumentException(
				"Unsupported scoring grade " + value + "; expected GradeV1 or GradeV2");
	}

	public double marginalUtilityOfMoney() {
		return marginalUtilityOfMoney;
	}

	public double adultTaxiFareUtilityPerHkd() {
		return adultTaxiFareUtilityPerHkd;
	}

	public double studentTaxiFareUtilityPerHkd() {
		return studentTaxiFareUtilityPerHkd;
	}

	public double carPassengerConstant() {
		return carPassengerConstant;
	}

	public double schoolBusConstant() {
		return schoolBusConstant;
	}

	public HongKongWalkScoringParameters walkParameters() {
		return walkParameters;
	}

	public HongKongTaxiFareUtilityPolicy taxiFarePolicy() {
		return new HongKongTaxiFareUtilityPolicy(
				adultTaxiFareUtilityPerHkd, studentTaxiFareUtilityPerHkd);
	}

	/** Applies the complete grade to a loaded MATSim configuration. */
	public void applyTo(Config config) {
		ScoringConfigGroup scoring = config.scoring();
		scoring.setMarginalUtilityOfMoney(marginalUtilityOfMoney);
		setMode(scoring, TransportMode.car, CAR_CONSTANT, TRAVEL_UTILITY_PER_HOUR);
		setMode(scoring, TransportMode.pt, 0.0, TRAVEL_UTILITY_PER_HOUR);
		setMode(scoring, TransportMode.walk, 0.0, TRAVEL_UTILITY_PER_HOUR);
		setMode(scoring, "car_passenger", carPassengerConstant, TRAVEL_UTILITY_PER_HOUR);
		setMode(scoring, "school_bus", schoolBusConstant, TRAVEL_UTILITY_PER_HOUR);
		ScoringConfigGroup.ModeParams taxi = setMode(
				scoring, HongKongTaxiScoringParameters.TAXI_MODE,
				TAXI_CONSTANT, TRAVEL_UTILITY_PER_HOUR);
		// Taxi fare is scored exclusively by HongKongTaxiFareUtilityPolicy.
		taxi.setMarginalUtilityOfDistance(0.0);
		taxi.setMonetaryDistanceRate(0.0);
		validateTaxiMoneyIsolation(config);
	}

	public void validateTaxiMoneyIsolation(Config config) {
		ScoringConfigGroup.ModeParams taxi = config.scoring().getModes()
				.get(HongKongTaxiScoringParameters.TAXI_MODE);
		if (taxi == null) throw new IllegalStateException("Missing Taxi scoring mode");
		if (Math.abs(taxi.getMarginalUtilityOfDistance()) > 1e-12
				|| Math.abs(taxi.getMonetaryDistanceRate()) > 1e-12) {
			throw new IllegalStateException(
					"Scoring grades require zero standard Taxi distance rates; fare is independent");
		}
	}

	private static ScoringConfigGroup.ModeParams setMode(
			ScoringConfigGroup scoring, String mode, double constant,
			double travelUtilityPerHour) {
		ScoringConfigGroup.ModeParams params = scoring.getOrCreateModeParams(mode);
		params.setConstant(constant);
		params.setMarginalUtilityOfTraveling(travelUtilityPerHour);
		return params;
	}
}
