package org.matsim.project.hongkong.car;

import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HongKongCarParkingCostCatalogTest {

	private static HongKongCarParkingCostCatalog catalog;

	@BeforeAll
	static void loadCatalog() {
		catalog = HongKongCarParkingCostCatalog.load(
				HongKongCarEnergyCostCatalog.DEFAULT_CAR_COST_ROOT);
	}

	@Test
	void loadsOnlyHashLockedCanonicalBaseDestinationParking() {
		var audit = catalog.audit();
		assertEquals(67_718L, audit.parkingRows());
		assertEquals(35_564L, audit.resolvedChargeRows());
		assertEquals(28_390L, audit.resolvedLegalZeroRows());
		assertEquals(835L, audit.unresolvedRows());
		assertEquals(2_929L, audit.motorcycleOutOfScopeRows());
		assertEquals(466L, audit.unresolvedTimeOverlapRows());
		assertEquals(269L, audit.unresolvedFacilityMismatchRows());
		assertEquals(98L, audit.unresolvedMissingZoneRows());
		assertEquals(2L, audit.unresolvedTerminalNonHomeRows());
		assertEquals(2_624_827.0, audit.resolvedCostTotalHkd(), 0.0);
		assertEquals(41.04242111517653, audit.resolvedMeanHkd(), 1.0e-12);
		assertEquals(32.0, audit.resolvedMedianHkd(), 0.0);
		assertEquals(110.0, audit.resolvedP90Hkd(), 0.0);
		assertEquals(210.0, audit.resolvedMaxHkd(), 0.0);
		assertEquals(6, audit.sourceSha256().size());
		assertEquals(0, audit.nearestLocationInferenceRows());
		assertEquals(0, audit.facilityCandidateFallbackRows());
		assertEquals(0, audit.distanceInferenceRows());
		assertEquals(0, audit.fixedOwnershipLegRows());
	}

	@Test
	void resolvedChargeAndHomeZeroRetainDistinctDestinationEvidence() {
		var charge = catalog.quote("hk_person_00000552", 0);
		assertTrue(charge.chargeable());
		assertEquals(72.0, charge.costHkd(), 0.0);
		assertEquals("resident_social_osm_missing_52047",
				charge.destinationFacilityId());
		assertEquals("social", charge.destinationActivityType());
		assertEquals("leisure", charge.destinationActivityGroup());

		var home = catalog.quote("hk_person_00000552", 2);
		assertTrue(home.resolved());
		assertFalse(home.chargeable());
		assertEquals(0.0, home.costHkd(), 0.0);
		assertEquals("home", home.destinationActivityGroup());
		assertEquals(
				HongKongCarParkingCostCatalog.Resolution.RESOLVED_LEGAL_ZERO,
				home.resolution());
	}

	@Test
	void unresolvedMotorcycleAndMissingKeysNeverBecomeNumericZero() {
		var ambiguous = catalog.quote("hk_person_00009089", 0);
		assertEquals(HongKongCarParkingCostCatalog.Resolution.UNRESOLVED,
				ambiguous.resolution());
		assertNull(ambiguous.costHkd());
		assertEquals(
				"next_departure_facility_differs_from_parking_destination",
				ambiguous.unresolvedReason());

		var motorcycle = catalog.quote("hk_person_00001299", 0);
		assertTrue(motorcycle.outOfScope());
		assertNull(motorcycle.costHkd());
		assertEquals("vehicle_class_motorcycle",
				motorcycle.unresolvedReason());

		assertThrows(IllegalStateException.class,
				() -> catalog.quote("missing-person", 0));
	}
}
