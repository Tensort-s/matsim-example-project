package org.matsim.project.hongkong.scoring;

import org.junit.jupiter.api.Test;
import org.matsim.core.config.ConfigUtils;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class HongKongScoringGradeTest {
	@Test
	void gradeV1MatchesHistoricalRun3Snapshot() {
		var grade = HongKongScoringGrade.GradeV1;
		assertEquals(1.0, grade.marginalUtilityOfMoney());
		assertEquals(0.5, grade.adultTaxiFareUtilityPerHkd());
		assertEquals(0.6, grade.studentTaxiFareUtilityPerHkd());
		assertEquals(-1.5, grade.carPassengerConstant());
		assertEquals(-1.5, grade.schoolBusConstant());
		assertEquals(3.278342, grade.walkParameters().firstOvertimeUtilityPerHour());
	}

	@Test
	void gradeV2AppliesCompleteSnapshotAndKeepsTaxiMoneyIndependent() {
		var config = ConfigUtils.createConfig();
		var grade = HongKongScoringGrade.GradeV2;
		grade.applyTo(config);

		assertEquals(0.28, config.scoring().getMarginalUtilityOfMoney());
		assertEquals(-0.5, config.scoring().getModes().get("car").getConstant());
		assertEquals(0.0, config.scoring().getModes().get("car_passenger").getConstant());
		assertEquals(0.0, config.scoring().getModes().get("school_bus").getConstant());
		assertEquals(-9.6, config.scoring().getModes().get("taxi").getConstant());
		assertEquals(0.0, config.scoring().getModes().get("taxi").getMonetaryDistanceRate());
		assertEquals(0.0, config.scoring().getModes().get("taxi").getMarginalUtilityOfDistance());
		assertEquals(3.0, grade.walkParameters().firstOvertimeUtilityPerHour());

		assertEquals(-28.0, -grade.marginalUtilityOfMoney() * 100.0, 1e-12);
		assertEquals(-28.0, -grade.adultTaxiFareUtilityPerHkd() * 100.0, 1e-12);
		assertEquals(-40.0, -grade.studentTaxiFareUtilityPerHkd() * 100.0, 1e-12);
	}

	@Test
	void rejectsUnknownGradeName() {
		assertThrows(IllegalArgumentException.class,
				() -> HongKongScoringGrade.parse("gradev2"));
	}
}
