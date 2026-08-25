package org.matsim.project.hongkong.household;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.core.population.PopulationUtils;
import org.matsim.project.hongkong.walk.HongKongWalkScoringParameters;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;

class HouseholdJointPlanWalkScoringTest {
	@Test
	void gradeV2AdjustmentAppliesOnlyToPureMainModeWalk() {
		var walk = PopulationUtils.createLeg(TransportMode.walk);
		walk.setTravelTime(15 * 60.0);
		var parameters = HongKongWalkScoringParameters.calibrationV5();
		assertEquals(1.75,
				HouseholdJointPlanSelector.mainWalkAdjustment(List.of(walk), parameters), 1e-12);

		var pt = PopulationUtils.createLeg(TransportMode.pt);
		pt.setTravelTime(20 * 60.0);
		assertEquals(0.0,
				HouseholdJointPlanSelector.mainWalkAdjustment(List.of(walk, pt), parameters), 1e-12);

		var schoolBus = PopulationUtils.createLeg(TransportMode.pt);
		schoolBus.setRoutingMode("school_bus");
		schoolBus.setTravelTime(20 * 60.0);
		assertEquals(0.0,
				HouseholdJointPlanSelector.mainWalkAdjustment(
						List.of(walk, schoolBus), parameters), 1e-12);
	}
}
