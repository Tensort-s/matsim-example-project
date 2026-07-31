package org.matsim.project.hongkong.car;

import com.google.inject.Inject;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.Person;
import org.matsim.project.hongkong.scoring.HongKongScoringComponent;
import org.matsim.project.hongkong.scoring.HongKongScoringComponentFactory;

import java.util.Objects;
import java.util.Set;

/** Stage 8B subcomponent factory for confirmed Car toll only. */
public final class HongKongCarTollScoringComponentFactory
		implements HongKongScoringComponentFactory {

	public static final String COMPONENT_ID = "car_confirmed_toll_v1";

	private final HongKongCarTollCostCatalog catalog;
	private final double marginalUtilityOfMoney;

	@Inject
	public HongKongCarTollScoringComponentFactory(
			Scenario scenario,
			HongKongCarTollCostCatalog catalog) {
		this(
				catalog,
				Objects.requireNonNull(scenario, "scenario")
						.getConfig().scoring().getMarginalUtilityOfMoney());
		HongKongCarEnergyScoringComponentFactory
				.requireNoStandardCarMonetaryDistanceCharge(
						scenario.getConfig());
	}

	HongKongCarTollScoringComponentFactory(
			HongKongCarTollCostCatalog catalog,
			double marginalUtilityOfMoney) {
		this.catalog = Objects.requireNonNull(catalog, "catalog");
		if (!Double.isFinite(marginalUtilityOfMoney)
				|| marginalUtilityOfMoney < 0.0) {
			throw new IllegalArgumentException(
					"Existing MATSim marginalUtilityOfMoney must be finite and nonnegative.");
		}
		this.marginalUtilityOfMoney = marginalUtilityOfMoney;
	}

	@Override
	public String componentId() {
		return COMPONENT_ID;
	}

	@Override
	public Set<String> activeModes() {
		return Set.of("car");
	}

	@Override
	public HongKongScoringComponent createComponent(Person person) {
		return new HongKongCarTollScoring(
				HongKongCarTollPersonSchedule.fromSelectedPlan(
						Objects.requireNonNull(person, "person"), catalog),
				marginalUtilityOfMoney);
	}

	HongKongCarTollCostCatalog catalog() {
		return catalog;
	}
}
