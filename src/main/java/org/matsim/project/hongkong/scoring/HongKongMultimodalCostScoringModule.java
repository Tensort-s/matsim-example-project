package org.matsim.project.hongkong.scoring;

import org.matsim.core.controler.AbstractModule;
import org.matsim.project.hongkong.car.HongKongCarEnergyCostCatalog;
import org.matsim.project.hongkong.car.HongKongCarMarginalCostScoringComponentModule;
import org.matsim.project.hongkong.car.HongKongDynamicCarCostModule;
import org.matsim.project.hongkong.pt.HongKongPtFareRuntimeCatalog;
import org.matsim.project.hongkong.pt.HongKongPtFareScoringComponentModule;
import org.matsim.project.hongkong.taxi.HongKongTaxiFareScoringComponentModule;
import org.matsim.project.hongkong.taxi.HongKongTaxiFareUtilityPolicy;
import org.matsim.project.hongkong.taxi.HongKongTaxiScoringParameters;

import java.nio.file.Path;
import java.util.Objects;

/**
 * Canonical Stage 8C scoring composition: standard MATSim scoring plus the
 * established Taxi route fare, strict five-layer PT fare, and one Car owner
 * containing approved energy, confirmed-toll, and resolved destination
 * parking components.
 *
 * <p>The older {@code HongKongTaxiScoringModule} remains the Taxi-only
 * equivalence and historical-smoke entry point. Unresolved parking, fixed
 * ownership and motorcycles remain null, absent, or out of scope.</p>
 */
public final class HongKongMultimodalCostScoringModule
		extends AbstractModule {

	private final HongKongTaxiFareUtilityPolicy taxiPolicy;
	private final Path ptFareReleaseRoot;
	private final Path carCostRoot;
	private final boolean dynamicCarCosts;

	public HongKongMultimodalCostScoringModule() {
		this(
				HongKongTaxiFareUtilityPolicy.historicalCentralV1(),
				HongKongPtFareRuntimeCatalog.DEFAULT_RELEASE_ROOT,
				HongKongCarEnergyCostCatalog.DEFAULT_CAR_COST_ROOT,
				false);
	}

	public HongKongMultimodalCostScoringModule(
			HongKongTaxiScoringParameters taxiParameters,
			Path ptFareReleaseRoot,
			Path carCostRoot) {
		this(equalPolicy(taxiParameters), ptFareReleaseRoot, carCostRoot, false);
	}

	public HongKongMultimodalCostScoringModule(
			HongKongTaxiScoringParameters taxiParameters,
			Path ptFareReleaseRoot,
			Path carCostRoot,
			boolean dynamicCarCosts) {
		this(equalPolicy(taxiParameters), ptFareReleaseRoot, carCostRoot, dynamicCarCosts);
	}

	public HongKongMultimodalCostScoringModule(
			HongKongTaxiFareUtilityPolicy taxiPolicy,
			Path ptFareReleaseRoot,
			Path carCostRoot,
			boolean dynamicCarCosts) {
		this.taxiPolicy = Objects.requireNonNull(taxiPolicy, "taxiPolicy");
		this.ptFareReleaseRoot = Objects.requireNonNull(
						ptFareReleaseRoot, "ptFareReleaseRoot")
				.toAbsolutePath().normalize();
		this.carCostRoot = Objects.requireNonNull(
						carCostRoot, "carCostRoot")
				.toAbsolutePath().normalize();
		this.dynamicCarCosts = dynamicCarCosts;
	}

	@Override
	public void install() {
		install(new HongKongMultimodalScoringModule());
		install(new HongKongTaxiFareScoringComponentModule(taxiPolicy));
		install(new HongKongPtFareScoringComponentModule(
				ptFareReleaseRoot));
		if (dynamicCarCosts) {
			install(new HongKongDynamicCarCostModule(carCostRoot));
		} else {
			install(new HongKongCarMarginalCostScoringComponentModule(
					carCostRoot));
		}
	}

	private static HongKongTaxiFareUtilityPolicy equalPolicy(
			HongKongTaxiScoringParameters parameters) {
		Objects.requireNonNull(parameters, "parameters");
		return new HongKongTaxiFareUtilityPolicy(
				parameters.fareUtilityPerHkd(), parameters.fareUtilityPerHkd());
	}
}
