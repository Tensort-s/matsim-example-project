package org.matsim.project.hongkong.household;

import org.junit.jupiter.api.Test;

import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HouseholdJointPlanSelectionScheduleTest {
	@Test
	void targetsQsimIterationsFiveTenAndFifteen() {
		var schedule = HouseholdJointPlanSelectionSchedule.targetIterations5_10_15();
		assertEquals(Set.of(5, 10, 15), schedule.sourceIterations());
		assertTrue(schedule.rebuildWithoutTemplates());
	}

	@Test
	void supportsFourExplicitSelectionsAndFreezesAfterThirtyFive() {
		var schedule = HouseholdJointPlanSelectionSchedule.targetIterations(Set.of(5, 15, 25, 35));

		assertEquals(Set.of(5, 15, 25, 35), schedule.sourceIterations());
		for (int iteration : Set.of(5, 15, 25, 35)) {
			assertTrue(schedule.sourceIterations().contains(iteration));
		}
		for (int iteration = 36; iteration <= 49; iteration++) {
			assertFalse(schedule.sourceIterations().contains(iteration));
		}
	}
}
