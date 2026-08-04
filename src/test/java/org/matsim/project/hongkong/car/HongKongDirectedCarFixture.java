package org.matsim.project.hongkong.car;

/** Deterministic Stage 10 Car energy quote fixture; test scope only. */
public final class HongKongDirectedCarFixture {

	private static final String SOURCE_PATH =
			"data/transport_costs/hongkong/car_cost_v1/energy_application_v1/"
					+ "car_leg_energy_cost_estimates_base.parquet";
	private static final String SOURCE_SHA =
			"0e0cc3fdd3440b4be8e51ad98289de590af1b479222c8e29b15845055d82f5da";

	private HongKongDirectedCarFixture() {
	}

	public static HongKongCarEnergyCostCatalog catalogFor(
			String personId, int sourceLegSequence, double distanceM, double costHkd) {
		HongKongCarEnergyCostCatalog.EnergyQuote quote =
				new HongKongCarEnergyCostCatalog.EnergyQuote(
						personId,
						sourceLegSequence,
						"stage10-vehicle-" + personId,
						"private_car",
						costHkd,
						"resolved_representative_fleet_average",
						"official_sources_representative_licensed_fleet_average_proxy_no_individual_powertrain",
						"energy_parameters_repository_relative.csv",
						"stage10-fixture-snapshot",
						SOURCE_PATH,
						SOURCE_SHA,
						distanceM,
						false,
						HongKongCarEnergyCostCatalog.Resolution.RESOLVED,
						"");
		return HongKongCarEnergyCostCatalog.builder()
				.quote(quote)
				.buildForTests();
	}
}
