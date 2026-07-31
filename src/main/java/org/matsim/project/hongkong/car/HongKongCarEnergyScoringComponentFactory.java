package org.matsim.project.hongkong.car;

import com.google.inject.Inject;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.config.Config;
import org.matsim.project.hongkong.scoring.HongKongScoringComponent;
import org.matsim.project.hongkong.scoring.HongKongScoringComponentFactory;

import java.util.Objects;
import java.util.Set;

/** Canonical Stage 8A adapter for Car fuel-or-electricity scoring. */
public final class HongKongCarEnergyScoringComponentFactory
		implements HongKongScoringComponentFactory {

	public static final String COMPONENT_ID =
			"car_fuel_or_electricity_v1";

	private final HongKongCarEnergyCostCatalog catalog;
	private final double marginalUtilityOfMoney;

	@Inject
	public HongKongCarEnergyScoringComponentFactory(
			Scenario scenario,
			HongKongCarEnergyCostCatalog catalog) {
		this(
				catalog,
				requireScenario(scenario).getConfig().scoring()
						.getMarginalUtilityOfMoney());
		requireNoStandardCarMonetaryDistanceCharge(
				scenario.getConfig());
	}

	HongKongCarEnergyScoringComponentFactory(
			HongKongCarEnergyCostCatalog catalog,
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
		return new HongKongCarEnergyScoring(
				energyScheduleFor(Objects.requireNonNull(person, "person")),
				marginalUtilityOfMoney);
	}

	HongKongCarEnergyPersonSchedule energyScheduleFor(Person person) {
		return HongKongCarEnergyPersonSchedule.fromSelectedPlan(
				Objects.requireNonNull(person, "person"),
				catalog);
	}

	HongKongCarEnergyCostCatalog catalog() {
		return catalog;
	}

	static void requireNoStandardCarMonetaryDistanceCharge(Config config) {
		Objects.requireNonNull(config, "config");
		var car = config.scoring().getModes().get("car");
		if (car != null && car.getMonetaryDistanceRate() != 0.0) {
			throw new IllegalStateException(
					"Stage 8A Car energy scoring requires the existing standard "
							+ "car monetaryDistanceRate to be exactly zero; "
							+ "its currency and economic meaning remain unverified, "
							+ "and this component will neither reinterpret nor mutate it.");
		}
	}

	private static Scenario requireScenario(Scenario scenario) {
		return Objects.requireNonNull(scenario, "scenario");
	}
}
