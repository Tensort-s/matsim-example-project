package org.matsim.project.hongkong.pt;

import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import java.nio.file.Path;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HongKongPtFareRuntimeCatalogTest {

	private static HongKongPtFareRuntimeCatalog catalog;

	@BeforeAll
	static void loadCatalog() {
		catalog = HongKongPtFareRuntimeCatalog.load(Path.of(
				"data", "transport_costs", "hongkong", "pt_fare_v1"));
	}

	@Test
	void loadsExactLockedSourcesAndQuotesAllFiveStrictLayers() {
		assertEquals(
				Map.of(
						"mtr_domestic_station_od_v1", 9_216L,
						"light_rail_station_od_v1", 4_624L,
						"gmb_fare_v1", 97_521L,
						"ferry_fare_v1", 60L,
						"bus_fare_v1", 754_133L),
				catalog.audit().ruleCounts());
		assertEquals(10, catalog.audit().sourceSha256().size());
		assertEquals(
				Map.of(
						"mtr_domestic_station_od_v1", 314L,
						"light_rail_station_od_v1", 377L,
						"gmb_fare_v1", 13_100L,
						"ferry_fare_v1", 74L,
						"bus_fare_v1", 56_056L),
				catalog.audit().exactFacilityMappingCounts());
		assertEquals(5, catalog.audit().activeLayerIds().size());
		assertTrue(catalog.audit().prohibitedFallbacks()
				.contains("bus_simulation_candidate"));
		assertTrue(catalog.audit().prohibitedFallbacks()
				.contains("unresolved_to_zero"));

		assertQuote(
				catalog.quote(
						"train", "line_mtr_fixture", "route_mtr_fixture",
						"pt_mtr_ISL_DT_CEN__8371e9640e_012",
						"pt_mtr_ISL_DT_ADM__8371e9640e_011"),
				HongKongPtFareRuntimeCatalog.Layer.MTR_DOMESTIC,
				4.9);
		assertQuote(
				catalog.quote(
						"light_rail", "line_lrt_fixture", "route_lrt_fixture",
						"pt_lrt_507_1_FEP__f3c4ef233d_000",
						"pt_lrt_610_1_MEG__0d338bb9cb_001"),
				HongKongPtFareRuntimeCatalog.Layer.LIGHT_RAIL,
				5.1);
		assertQuote(
				catalog.quote(
						"gmb", "line_gmb_2000511", "gmb_2000511_1",
						"pt_gmb_20003337_7cc8c4185c__4eb197ed9e_042",
						"pt_gmb_20006944_5577943da9__1edd3e2c22_014"),
				HongKongPtFareRuntimeCatalog.Layer.GMB,
				12.5);
		assertQuote(
				catalog.quote(
						"ferry", "ferry_line_7000003",
						"ferry_7000003_1911228024",
						"ferry_stop_ferry_7000003_1911228024_00",
						"ferry_stop_ferry_7000003_1911228024_01"),
				HongKongPtFareRuntimeCatalog.Layer.FERRY,
				16.2);
		assertQuote(
				catalog.quote(
						"bus", "line_bus_1000001", "bus_1000001_1",
						"pt_bus_10000016_7f827b65e0__040837c4b9_004",
						"pt_bus_12406_ac359ecce9__040837c4b9_005"),
				HongKongPtFareRuntimeCatalog.Layer.BUS_CORE,
				7.4);
	}

	@Test
	void strictBusCoreAndExactCrosswalkFailClosedWithoutFallback() {
		HongKongPtFareRuntimeCatalog.FareQuote absentOd = catalog.quote(
				"bus", "line_bus_1000001", "bus_1000001_1",
				"pt_bus_10000016_7f827b65e0__040837c4b9_004",
				"pt_bus_10000016_7f827b65e0__040837c4b9_004");
		assertFalse(absentOd.resolved());
		assertEquals(null, absentOd.costHkd());
		assertEquals("U", absentOd.costQuality());
		assertTrue(absentOd.unresolvedReason()
				.contains("no_simulation_fallback"));

		HongKongPtFareRuntimeCatalog.FareQuote unknownStop = catalog.quote(
				"gmb", "line_gmb_2000511", "gmb_2000511_1",
				"not-a-canonical-facility",
				"pt_gmb_20006944_5577943da9__1edd3e2c22_014");
		assertFalse(unknownStop.resolved());
		assertTrue(unknownStop.unresolvedReason()
				.contains("no_exact_canonical_crosswalk"));
	}

	@Test
	void unresolvedPublishedGmbDuplicateRemainsNullWithoutCandidateSelection() {
		HongKongPtFareRuntimeCatalog.FareQuote unresolved = catalog.quote(
				"gmb", "line_gmb_2000993", "gmb_2000993_1",
				"pt_gmb_20001162_7028c2b53d__0b73e64222_006",
				"pt_gmb_20001163_ef9ef13c7d__377ede34c2_001");
		assertFalse(unresolved.resolved());
		assertEquals(null, unresolved.costHkd());
		assertEquals("U", unresolved.costQuality());
		assertTrue(unresolved.unresolvedReason()
				.contains("multiple_identical_source_records"));
	}

	private static void assertQuote(
			HongKongPtFareRuntimeCatalog.FareQuote quote,
			HongKongPtFareRuntimeCatalog.Layer layer,
			double expectedFare) {
		assertTrue(quote.resolved());
		assertEquals(layer, quote.layer());
		assertEquals(expectedFare, quote.costHkd(), 0.0);
		assertEquals("", quote.unresolvedReason());
		assertFalse(quote.sourceRecordId().isBlank());
		assertEquals(64, quote.sourceSha256().length());
	}
}
