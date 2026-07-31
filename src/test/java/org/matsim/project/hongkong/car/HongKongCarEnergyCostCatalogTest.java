package org.matsim.project.hongkong.car;

import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import java.nio.file.Path;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HongKongCarEnergyCostCatalogTest {

	private static HongKongCarEnergyCostCatalog catalog;

	@BeforeAll
	static void loadCatalog() {
		catalog = HongKongCarEnergyCostCatalog.load(Path.of(
				"data", "transport_costs", "hongkong", "car_cost_v1"));
	}

	@Test
	void loadsOnlyExactCanonicalBaseEnergyRows() {
		var audit = catalog.audit();
		assertEquals(203_154L, audit.componentTableRows());
		assertEquals(67_718L, audit.fuelRows());
		assertEquals(67_718L, audit.tollRows());
		assertEquals(67_718L, audit.parkingRows());
		assertEquals(64_789L, audit.privateCarResolvedRows());
		assertEquals(2_929L, audit.motorcycleOutOfScopeRows());
		assertEquals(33L, audit.legalZeroRows());
		assertEquals(2_341_793.9504491785,
				audit.resolvedCostTotalHkd(), 1.0e-6);
		assertEquals(36.14493124526044,
				audit.resolvedCostMeanHkd(), 1.0e-12);
		assertEquals(28.861846791369157,
				audit.resolvedCostMedianHkd(), 1.0e-12);
		assertEquals(76.4376128255154,
				audit.resolvedCostP90Hkd(), 1.0e-12);
		assertEquals(0.0, audit.formulaMaxAbsErrorHkd(), 1.0e-9);
		assertEquals(3, audit.sourceSha256().size());
		assertFalse(audit.individualPowertrainAvailable());
		assertEquals(0L, audit.fixedOwnershipLegRows());
		assertEquals(0L, audit.tollRuntimeRowsLoaded());
		assertEquals(0L, audit.parkingRuntimeRowsLoaded());
		assertEquals(
				Map.of(
						"canonical_car_cost_interface_manifest.json",
						"515d15df43a269da5f060338fcaf91cf004abfeb98ee4332e4172964f64be31d",
						"unified_marginal_cost_interface_v1/car_leg_marginal_cost_components_base.parquet",
						"0337469ca99d61650f782f273b7b275cee124449e01037f95e15f978f94e742b",
						"unified_marginal_cost_interface_v1/marginal_cost_component_registry.csv",
						"ae2fd61342413b586aef1149f5221db0ffa04d994e1b415d6c7bccf077855580"),
				audit.sourceSha256());
	}

	@Test
	void exactPrivateCarAndMotorcycleRowsPreserveCanonicalSemantics() {
		var privateCar = catalog.quote("hk_person_00000552", 0);
		assertTrue(privateCar.resolved());
		assertEquals("private_car", privateCar.vehicleClass());
		assertEquals(
				"resolved_representative_fleet_average",
				privateCar.costStatus());
		assertEquals(12.786232290630613,
				privateCar.costHkd(), 0.0);
		assertEquals(5_497.029,
				privateCar.sourceRouteDistanceM(), 0.0);
		assertFalse(privateCar.fixedVehicleOwnershipCostIncluded());

		var motorcycle = catalog.quote("hk_person_00001299", 0);
		assertTrue(motorcycle.outOfScope());
		assertEquals("motorcycle", motorcycle.vehicleClass());
		assertEquals(null, motorcycle.costHkd());
		assertEquals("out_of_scope_motorcycle",
				motorcycle.costStatus());
		assertEquals("vehicle_class_motorcycle",
				motorcycle.unresolvedReason());
	}

	@Test
	void missingPersonLegKeyRemainsExplicitNullAndNeverZero() {
		var missing = catalog.quote("not-in-canonical-source", 0);
		assertFalse(missing.resolved());
		assertFalse(missing.outOfScope());
		assertEquals(null, missing.costHkd());
		assertEquals("U", missing.costQuality());
		assertTrue(missing.unresolvedReason()
				.contains("not_in_canonical"));
	}
}
