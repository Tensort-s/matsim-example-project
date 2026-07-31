package org.matsim.project.hongkong.scoring;

import org.matsim.core.controler.AbstractModule;
import org.matsim.project.hongkong.pt.HongKongPtFareRuntimeCatalog;
import org.matsim.project.hongkong.pt.HongKongPtFareScoringComponentModule;
import org.matsim.project.hongkong.taxi.HongKongTaxiFareScoringComponentModule;
import org.matsim.project.hongkong.taxi.HongKongTaxiScoringParameters;

import java.nio.file.Path;
import java.util.Objects;

/**
 * Canonical Stage 7 scoring composition: standard MATSim scoring plus the
 * established Taxi route fare and the strict five-layer PT fare component.
 *
 * <p>The older {@code HongKongTaxiScoringModule} remains the Taxi-only
 * equivalence and historical-smoke entry point. Car is deliberately absent.</p>
 */
public final class HongKongMultimodalCostScoringModule
		extends AbstractModule {

	private final HongKongTaxiScoringParameters taxiParameters;
	private final Path ptFareReleaseRoot;

	public HongKongMultimodalCostScoringModule() {
		this(
				HongKongTaxiScoringParameters.centralV1(),
				HongKongPtFareRuntimeCatalog.DEFAULT_RELEASE_ROOT);
	}

	public HongKongMultimodalCostScoringModule(
			HongKongTaxiScoringParameters taxiParameters,
			Path ptFareReleaseRoot) {
		this.taxiParameters =
				Objects.requireNonNull(taxiParameters, "taxiParameters");
		this.ptFareReleaseRoot = Objects.requireNonNull(
						ptFareReleaseRoot, "ptFareReleaseRoot")
				.toAbsolutePath().normalize();
	}

	@Override
	public void install() {
		install(new HongKongMultimodalScoringModule());
		install(new HongKongTaxiFareScoringComponentModule(
				taxiParameters));
		install(new HongKongPtFareScoringComponentModule(
				ptFareReleaseRoot));
	}
}
