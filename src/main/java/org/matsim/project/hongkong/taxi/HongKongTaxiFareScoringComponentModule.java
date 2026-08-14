package org.matsim.project.hongkong.taxi;

import com.google.inject.Scopes;
import com.google.inject.multibindings.Multibinder;
import org.matsim.core.controler.AbstractModule;
import org.matsim.project.hongkong.scoring.HongKongScoringComponentFactory;

import java.util.Objects;

/** Contributes only the canonical Taxi route-fare component. */
public final class HongKongTaxiFareScoringComponentModule extends AbstractModule {

	private final HongKongTaxiFareUtilityPolicy policy;

	public HongKongTaxiFareScoringComponentModule() {
		this(HongKongTaxiFareUtilityPolicy.historicalCentralV1());
	}

	public HongKongTaxiFareScoringComponentModule(
			HongKongTaxiScoringParameters parameters) {
		this(new HongKongTaxiFareUtilityPolicy(
				Objects.requireNonNull(parameters, "parameters").fareUtilityPerHkd(),
				parameters.fareUtilityPerHkd()));
	}

	public HongKongTaxiFareScoringComponentModule(
			HongKongTaxiFareUtilityPolicy policy) {
		this.policy = Objects.requireNonNull(policy, "policy");
	}

	@Override
	public void install() {
		bind(HongKongTaxiFareUtilityPolicy.class).toInstance(policy);
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
