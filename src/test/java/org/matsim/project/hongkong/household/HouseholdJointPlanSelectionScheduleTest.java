package org.matsim.project.hongkong.household;

import org.junit.jupiter.api.Test;

import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HouseholdJointPlanSelectionScheduleTest {
	@Test
	void targetsQsimIterationsFiveTenAndFifteen() {
		var schedule = HouseholdJointPlanSelectionSchedule.targetIterations5_10_15();
		assertEquals(Set.of(5, 10, 15), schedule.sourceIterations());
		assertTrue(schedule.rebuildWithoutTemplates());
	}
}
