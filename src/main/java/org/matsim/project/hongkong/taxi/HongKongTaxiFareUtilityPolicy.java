package org.matsim.project.hongkong.taxi;

import org.matsim.api.core.v01.population.Person;

import java.util.Objects;
import java.util.Set;

/** Selects the Taxi fare disutility from stable person attributes. */
public record HongKongTaxiFareUtilityPolicy(
		double adultFareUtilityPerHkd,
		double studentFareUtilityPerHkd) {

	private static final Set<String> STUDENT_ROLES = Set.of(
			"day_school_student", "tertiary_student");

	public HongKongTaxiFareUtilityPolicy {
		if (!Double.isFinite(adultFareUtilityPerHkd) || adultFareUtilityPerHkd < 0.0) {
			throw new IllegalArgumentException("Invalid adult Taxi fare utility coefficient");
		}
		if (!Double.isFinite(studentFareUtilityPerHkd) || studentFareUtilityPerHkd < 0.0) {
			throw new IllegalArgumentException("Invalid student Taxi fare utility coefficient");
		}
	}

	public static HongKongTaxiFareUtilityPolicy historicalCentralV1() {
		return new HongKongTaxiFareUtilityPolicy(
				HongKongTaxiScoringParameters.CENTRAL_FARE_UTILITY_PER_HKD,
				HongKongTaxiScoringParameters.CENTRAL_FARE_UTILITY_PER_HKD);
	}

	public static HongKongTaxiFareUtilityPolicy openInnovationV1() {
		return new HongKongTaxiFareUtilityPolicy(0.10, 0.15);
	}

	public boolean isStudent(Person person) {
		Object role = Objects.requireNonNull(person, "person")
				.getAttributes().getAttribute("role");
		return role != null && STUDENT_ROLES.contains(role.toString());
	}

	public HongKongTaxiScoringParameters parametersFor(Person person) {
		return parameters(isStudent(person)
				? studentFareUtilityPerHkd : adultFareUtilityPerHkd);
	}

	private static HongKongTaxiScoringParameters parameters(double coefficient) {
		return new HongKongTaxiScoringParameters(
				coefficient,
				HongKongTaxiScoringParameters.CENTRAL_FARE_SHARE_FACTOR,
				HongKongTaxiScoringParameters.DISTANCE_ONLY_SCOPE,
				HongKongTaxiScoringParameters.FARE_MODEL_VERSION);
	}
}
