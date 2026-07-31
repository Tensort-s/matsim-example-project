package org.matsim.project.hongkong.car;

import com.google.inject.Inject;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.Person;
import org.matsim.project.hongkong.scoring.HongKongScoringComponent;
import org.matsim.project.hongkong.scoring.HongKongScoringComponentFactory;

import java.util.Objects;
import java.util.Set;

/** Stage 8C subcomponent factory for resolved destination parking only. */
public final class HongKongCarParkingScoringComponentFactory
		implements HongKongScoringComponentFactory {

	public static final String COMPONENT_ID = "car_destination_parking_v1";

	private final HongKongCarParkingCostCatalog catalog;
	private final double marginalUtilityOfMoney;

	@Inject
	public HongKongCarParkingScoringComponentFactory(
			Scenario scenario,
			HongKongCarParkingCostCatalog catalog) {
		this(
				catalog,
				Objects.requireNonNull(scenario, "scenario")
						.getConfig().scoring().getMarginalUtilityOfMoney());
		HongKongCarEnergyScoringComponentFactory
				.requireNoStandardCarMonetaryDistanceCharge(
						scenario.getConfig());
	}

	HongKongCarParkingScoringComponentFactory(
			HongKongCarParkingCostCatalog catalog,
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
		return new HongKongCarParkingScoring(
				HongKongCarParkingPersonSchedule.fromSelectedPlan(
						Objects.requireNonNull(person, "person"), catalog),
				marginalUtilityOfMoney);
	}

	HongKongCarParkingCostCatalog catalog() {
		return catalog;
	}
}
