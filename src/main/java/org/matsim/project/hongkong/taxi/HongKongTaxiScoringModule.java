package org.matsim.project.hongkong.taxi;

import org.matsim.core.controler.AbstractModule;

import java.util.Objects;

/**
 * Standalone module for a future Hong Kong taxi pilot runner.
 *
 * <p>This module is intentionally not installed in any existing runner.</p>
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
		bind(HongKongTaxiScoringParameters.class).toInstance(parameters);
		bindScoringFunctionFactory().to(HongKongTaxiScoringFunctionFactory.class);
	}
}
