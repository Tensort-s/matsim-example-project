package org.matsim.project.hongkong.walk;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.core.population.PopulationUtils;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;

class HongKongWalkOvertimeUtilityTest {
	@Test
	void appliesThresholdOnceToCumulativeWalkWithinMainTrip() {
		var access = PopulationUtils.createLeg(TransportMode.non_network_walk);
		access.setTravelTime(8 * 60.0);
		var egress = PopulationUtils.createLeg(TransportMode.walk);
		egress.setTravelTime(22 * 60.0);
		assertEquals(-1.0927806666666666,
				HongKongWalkOvertimeUtility.penaltyForTrip(List.of(access, egress)), 1e-12);
	}

	@Test
	void hasNoPenaltyThroughTenMinutesAndExpectedOneHourPenalty() {
		assertEquals(0.0, HongKongWalkOvertimeUtility.penaltyForWalkSeconds(600.0));
		assertEquals(-2.7319516666666667,
				HongKongWalkOvertimeUtility.penaltyForWalkSeconds(3_600.0), 1e-12);
	}
}
