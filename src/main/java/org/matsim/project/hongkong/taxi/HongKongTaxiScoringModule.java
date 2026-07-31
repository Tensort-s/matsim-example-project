package org.matsim.project.hongkong.taxi;

import org.matsim.core.controler.AbstractModule;
import org.matsim.project.hongkong.scoring.HongKongMultimodalScoringModule;

import java.util.Objects;

/**
 * Taxi-pilot convenience module that installs the combined scoring factory
 * and contributes only the canonical Taxi route-fare component.
 */
public final class HongKongTaxiScoringModule extends AbstractModule {

	private final HongKongTaxiScoringParameters parameters;

	public HongKongTaxiScoringModule() {
		this(HongKongTaxiScoringParameters.centralV1());
	}

	public HongKongTaxiScoringModule(HongKongTaxiScoringParameters parameters) {
		this.parameters = Objects.requireNonNull(parameters, "parameters");
	}

	@Override
	public void install() {
		install(new HongKongMultimodalScoringModule());
		install(new HongKongTaxiFareScoringComponentModule(parameters));
	}
}
