package org.matsim.project.hongkong.taxi;

import com.google.inject.Scopes;
import com.google.inject.multibindings.Multibinder;
import org.matsim.core.controler.AbstractModule;
import org.matsim.project.hongkong.scoring.HongKongScoringComponentFactory;

import java.util.Objects;

/** Contributes only the canonical Taxi route-fare component. */
public final class HongKongTaxiFareScoringComponentModule extends AbstractModule {

	private final HongKongTaxiScoringParameters parameters;

	public HongKongTaxiFareScoringComponentModule() {
		this(HongKongTaxiScoringParameters.centralV1());
	}

	public HongKongTaxiFareScoringComponentModule(
			HongKongTaxiScoringParameters parameters) {
		this.parameters = Objects.requireNonNull(parameters, "parameters");
	}

	@Override
	public void install() {
		bind(HongKongTaxiScoringParameters.class).toInstance(parameters);
		bind(HongKongTaxiFareCalculator.class).toInstance(
				new HongKongTaxiFareCalculator());
		bind(HongKongTaxiFareScoringComponentFactory.class)
				.in(Scopes.SINGLETON);
		Multibinder.newSetBinder(
						binder(), HongKongScoringComponentFactory.class)
				.addBinding()
				.to(HongKongTaxiFareScoringComponentFactory.class);
	}
}
