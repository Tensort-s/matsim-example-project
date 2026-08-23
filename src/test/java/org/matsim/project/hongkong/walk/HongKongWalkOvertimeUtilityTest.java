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

	@Test
	void calibrationV2AppliesConstantAndTwoHingesToMainWalkTrip() {
		var parameters = HongKongWalkScoringParameters.calibrationV2();
		assertEquals(-0.15,
				HongKongWalkOvertimeUtility.penaltyForWalkSeconds(600.0, parameters), 1e-12);
		assertEquals(-0.42319516666666665,
				HongKongWalkOvertimeUtility.penaltyForWalkSeconds(900.0, parameters), 1e-12);
		assertEquals(-3.4927806666666667,
				HongKongWalkOvertimeUtility.penaltyForWalkSeconds(1_800.0, parameters), 1e-12);
	}

	@Test
	void calibrationV2DoesNotPenalizePtAccessWalk() {
		var access = PopulationUtils.createLeg(TransportMode.non_network_walk);
		access.setTravelTime(12 * 60.0);
		var pt = PopulationUtils.createLeg(TransportMode.pt);
		pt.setTravelTime(20 * 60.0);
		assertEquals(0.0, HongKongWalkOvertimeUtility.penaltyForTrip(
				List.of(access, pt), HongKongWalkScoringParameters.calibrationV2()));
	}

	@Test
	void calibrationV3RewardsShortWalkAndStronglyRejectsLongWalk() {
		var parameters = HongKongWalkScoringParameters.calibrationV3();
		assertEquals(0.20,
				HongKongWalkOvertimeUtility.penaltyForWalkSeconds(5 * 60.0, parameters), 1e-12);
		assertEquals(-3.8927806666666667,
				HongKongWalkOvertimeUtility.penaltyForWalkSeconds(30 * 60.0, parameters), 1e-12);
		assertEquals(-41.53195166666667,
				HongKongWalkOvertimeUtility.penaltyForWalkSeconds(60 * 60.0, parameters), 1e-12);
	}

	@Test
	void calibrationV4RewardsEligibleShortWalkAndSharplyRejectsLongWalk() {
		var parameters = HongKongWalkScoringParameters.calibrationV4();
		assertEquals(2.0,
				HongKongWalkOvertimeUtility.penaltyForWalkSeconds(5 * 60.0, parameters), 1e-12);
		assertEquals(-14.092780666666667,
				HongKongWalkOvertimeUtility.penaltyForWalkSeconds(30 * 60.0, parameters), 1e-12);
		assertEquals(-165.73195166666667,
				HongKongWalkOvertimeUtility.penaltyForWalkSeconds(60 * 60.0, parameters), 1e-12);
	}
}
