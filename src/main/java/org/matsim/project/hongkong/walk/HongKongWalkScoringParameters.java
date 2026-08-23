package org.matsim.project.hongkong.walk;

/** Auditable per-main-trip Walk score adjustment parameters. */
public record HongKongWalkScoringParameters(
		double constantPerMainWalkTrip,
		double firstThresholdSeconds,
		double firstOvertimeUtilityPerHour,
		double secondThresholdSeconds,
		double secondOvertimeUtilityPerHour,
		double thirdThresholdSeconds,
		double thirdOvertimeUtilityPerHour,
		boolean mainWalkTripsOnly,
		String version) {

	public HongKongWalkScoringParameters {
		if (!Double.isFinite(constantPerMainWalkTrip)) {
			throw new IllegalArgumentException("Walk constant must be finite");
		}
		if (!Double.isFinite(firstThresholdSeconds) || firstThresholdSeconds < 0.0
				|| !Double.isFinite(secondThresholdSeconds)
				|| secondThresholdSeconds < firstThresholdSeconds
				|| !Double.isFinite(thirdThresholdSeconds)
				|| thirdThresholdSeconds < secondThresholdSeconds) {
			throw new IllegalArgumentException("Invalid Walk scoring thresholds");
		}
		if (!Double.isFinite(firstOvertimeUtilityPerHour) || firstOvertimeUtilityPerHour < 0.0
				|| !Double.isFinite(secondOvertimeUtilityPerHour)
				|| secondOvertimeUtilityPerHour < 0.0
				|| !Double.isFinite(thirdOvertimeUtilityPerHour)
				|| thirdOvertimeUtilityPerHour < 0.0) {
			throw new IllegalArgumentException("Walk overtime disutilities must be finite and non-negative");
		}
		if (version == null || version.isBlank()) {
			throw new IllegalArgumentException("Walk scoring version is required");
		}
	}

	public static HongKongWalkScoringParameters legacyV1() {
		return new HongKongWalkScoringParameters(
				0.0, 600.0, 3.278342, 600.0, 0.0, 600.0, 0.0, false,
				"walk_overtime_per_main_trip_v1");
	}

	public static HongKongWalkScoringParameters calibrationV2() {
		return new HongKongWalkScoringParameters(
				-0.15, 600.0, 3.278342, 900.0, 9.0, 900.0, 0.0, true,
				"walk_main_mode_dual_hinge_v2");
	}

	public static HongKongWalkScoringParameters calibrationV3() {
		return new HongKongWalkScoringParameters(
				0.20, 600.0, 3.278342, 900.0, 12.0, 1_800.0, 60.0, true,
				"walk_main_mode_short_reward_triple_hinge_v3");
	}

	public static HongKongWalkScoringParameters calibrationV4() {
		return new HongKongWalkScoringParameters(
				2.0, 600.0, 3.278342, 900.0, 60.0, 1_800.0, 240.0, true,
				"walk_main_mode_short_reward_strong_long_rejection_v4");
	}
}
