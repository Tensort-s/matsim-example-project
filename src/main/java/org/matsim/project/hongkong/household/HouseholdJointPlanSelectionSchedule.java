package org.matsim.project.hongkong.household;

import java.util.Set;

/**
 * Explicit iteration schedule for protected deterministic selection.
 * ReplanningStarts is emitted before the QSim with the same iteration number.
 */
public record HouseholdJointPlanSelectionSchedule(
		Set<Integer> sourceIterations,
		boolean rebuildWithoutTemplates) {
	public HouseholdJointPlanSelectionSchedule {
		sourceIterations = Set.copyOf(sourceIterations);
		if (sourceIterations.isEmpty()) throw new IllegalArgumentException("Empty selector schedule");
	}

	public static HouseholdJointPlanSelectionSchedule historicalOneShot() {
		return new HouseholdJointPlanSelectionSchedule(Set.of(1), false);
	}

	public static HouseholdJointPlanSelectionSchedule targetIterations5_10_15() {
		return new HouseholdJointPlanSelectionSchedule(Set.of(5, 10, 15), true);
	}

	public static HouseholdJointPlanSelectionSchedule targetIterations(Set<Integer> iterations) {
		return new HouseholdJointPlanSelectionSchedule(iterations, true);
	}
}
