package org.matsim.project.hongkong.car;

import com.google.inject.Inject;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.Person;
import org.matsim.project.hongkong.scoring.HongKongScoringComponent;
import org.matsim.project.hongkong.scoring.HongKongScoringComponentFactory;

import java.util.List;
import java.util.Objects;
import java.util.Set;

/** Canonical single Car mode owner for Stage 8A/8B marginal components. */
public final class HongKongCarMarginalCostScoringComponentFactory
		implements HongKongScoringComponentFactory {

	public static final String COMPONENT_ID = "car_marginal_cost_v1";

	private final HongKongCarEnergyScoringComponentFactory energyFactory;
	private final HongKongCarTollScoringComponentFactory tollFactory;

	@Inject
	public HongKongCarMarginalCostScoringComponentFactory(
			Scenario scenario,
			HongKongCarEnergyCostCatalog energyCatalog,
			HongKongCarTollCostCatalog tollCatalog) {
		Objects.requireNonNull(scenario, "scenario");
		double marginalUtilityOfMoney =
				scenario.getConfig().scoring().getMarginalUtilityOfMoney();
		HongKongCarEnergyScoringComponentFactory
				.requireNoStandardCarMonetaryDistanceCharge(
						scenario.getConfig());
		this.energyFactory = new HongKongCarEnergyScoringComponentFactory(
				Objects.requireNonNull(energyCatalog, "energyCatalog"),
				marginalUtilityOfMoney);
		this.tollFactory = new HongKongCarTollScoringComponentFactory(
				Objects.requireNonNull(tollCatalog, "tollCatalog"),
				marginalUtilityOfMoney);
	}

	HongKongCarMarginalCostScoringComponentFactory(
			HongKongCarEnergyScoringComponentFactory energyFactory,
			HongKongCarTollScoringComponentFactory tollFactory) {
		this.energyFactory = Objects.requireNonNull(
				energyFactory, "energyFactory");
		this.tollFactory = Objects.requireNonNull(tollFactory, "tollFactory");
	}

	@Override
	public String componentId() {
		return COMPONENT_ID;
	}

	@Override
	public Set<String> activeModes() {
		return Set.of("car");
	}

	public List<String> subcomponentIds() {
		return List.of(
				energyFactory.componentId(),
				tollFactory.componentId());
	}

	@Override
	public HongKongScoringComponent createComponent(Person person) {
		Objects.requireNonNull(person, "person");
		return new HongKongCarMarginalCostScoring(
				(HongKongCarEnergyScoring)
						energyFactory.createComponent(person),
				(HongKongCarTollScoring)
						tollFactory.createComponent(person));
	}
}
