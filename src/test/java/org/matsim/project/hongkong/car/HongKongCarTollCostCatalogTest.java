package org.matsim.project.hongkong.car;

import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HongKongCarTollCostCatalogTest {

	private static HongKongCarTollCostCatalog catalog;

	@BeforeAll
	static void loadCatalog() {
		catalog = HongKongCarTollCostCatalog.load(Path.of(
				"data", "transport_costs", "hongkong", "car_cost_v1"));
	}

	@Test
	void loadsOnlyExactCanonicalConfirmedBaseTolls() {
		var audit = catalog.audit();
		assertEquals(67_718L, audit.tollRows());
		assertEquals(25_858L, audit.confirmedChargeRows());
		assertEquals(38_931L, audit.confirmedNoChargeRows());
		assertEquals(0L, audit.unresolvedRows());
		assertEquals(2_929L, audit.motorcycleOutOfScopeRows());
		assertEquals(30_837L, audit.physicalPassageEvents());
		assertEquals(751_760.0, audit.confirmedTollTotalHkd(), 0.0);
		assertEquals(11.603204247634629, audit.resolvedMeanHkd(), 1.0e-12);
		assertEquals(0.0, audit.resolvedMedianHkd(), 0.0);
		assertEquals(40.0, audit.resolvedP90Hkd(), 0.0);
		assertEquals(141.0, audit.resolvedMaxHkd(), 0.0);
		assertEquals(0.0, audit.eventLegSumMaxAbsErrorHkd(), 0.0);
		assertEquals(6, audit.sourceSha256().size());
		assertEquals(0L, audit.distanceInferredRows());
		assertEquals(0L, audit.candidateFallbackRows());
		assertEquals(0L, audit.fixedOwnershipLegRows());
		assertEquals(0L, audit.parkingRuntimeRowsLoaded());
	}

	@Test
	void exactChargeAndConfirmedNoChargeKeepDistinctEvidence() {
		var noCharge = catalog.quote("hk_person_00000552", 0);
		assertTrue(noCharge.confirmed());
		assertFalse(noCharge.chargeable());
		assertEquals(
				HongKongCarTollCostCatalog.Resolution.CONFIRMED_NO_CHARGE,
				noCharge.resolution());
		assertEquals(0.0, noCharge.costHkd(), 0.0);
		assertEquals(0, noCharge.passageEvidence().size());

		var charge = catalog.quote("hk_person_00000552", 1);
		assertTrue(charge.confirmed());
		assertTrue(charge.chargeable());
		assertEquals(30.0, charge.costHkd(), 0.0);
		assertEquals(58, charge.sourceFullLinkCount());
		assertEquals(1, charge.passageEvidence().size());
		assertEquals("cross_harbour_tunnel",
				charge.passageEvidence().getFirst().canonicalFacilityId());
		assertEquals("road_105137_0_f",
				charge.passageEvidence().getFirst().matchedLinkIds().getFirst());
	}

	@Test
	void motorcycleAndMissingKeysRemainNullNotZero() {
		var motorcycle = catalog.quote("hk_person_00001299", 0);
		assertTrue(motorcycle.outOfScope());
		assertEquals(null, motorcycle.costHkd());
		assertEquals("vehicle_class_motorcycle",
				motorcycle.unresolvedReason());

		var missing = catalog.quote("not-in-canonical-toll-source", 0);
		assertFalse(missing.confirmed());
		assertFalse(missing.outOfScope());
		assertEquals(null, missing.costHkd());
		assertEquals(
				HongKongCarTollCostCatalog.Resolution.UNRESOLVED,
				missing.resolution());
	}
}
