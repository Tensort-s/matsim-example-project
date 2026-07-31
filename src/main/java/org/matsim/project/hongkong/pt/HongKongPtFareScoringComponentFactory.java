package org.matsim.project.hongkong.pt;

import com.google.inject.Inject;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.config.Config;
import org.matsim.pt.transitSchedule.api.TransitSchedule;
import org.matsim.project.hongkong.scoring.HongKongScoringComponent;
import org.matsim.project.hongkong.scoring.HongKongScoringComponentFactory;

import java.util.Objects;
import java.util.Set;

/** Canonical adapter from the five strict PT fare layers to scoring. */
public final class HongKongPtFareScoringComponentFactory
		implements HongKongScoringComponentFactory {

	public static final String COMPONENT_ID = "pt_fare_layered_v1";

	private final TransitSchedule transitSchedule;
	private final HongKongPtFareRuntimeCatalog catalog;
	private final double marginalUtilityOfMoney;

	@Inject
	public HongKongPtFareScoringComponentFactory(
			Scenario scenario,
			HongKongPtFareRuntimeCatalog catalog) {
		this(
				requireScenario(scenario).getTransitSchedule(),
				catalog,
				scenario.getConfig().scoring().getMarginalUtilityOfMoney());
		requireNoStandardPtMonetaryDistanceCharge(scenario.getConfig());
	}

	HongKongPtFareScoringComponentFactory(
			TransitSchedule transitSchedule,
			HongKongPtFareRuntimeCatalog catalog,
			double marginalUtilityOfMoney) {
		this.transitSchedule =
				Objects.requireNonNull(transitSchedule, "transitSchedule");
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
		return Set.of("pt");
	}

	@Override
	public HongKongScoringComponent createComponent(Person person) {
		return new HongKongPtFareScoring(
				fareScheduleFor(Objects.requireNonNull(person, "person")),
				marginalUtilityOfMoney);
	}

	HongKongPtPersonFareSchedule fareScheduleFor(Person person) {
		return HongKongPtPersonFareSchedule.fromSelectedPlan(
				Objects.requireNonNull(person, "person"),
				transitSchedule,
				catalog);
	}

	HongKongPtFareRuntimeCatalog catalog() {
		return catalog;
	}

	static void requireNoStandardPtMonetaryDistanceCharge(Config config) {
		Objects.requireNonNull(config, "config");
		var pt = config.scoring().getModes().get("pt");
		if (pt != null && pt.getMonetaryDistanceRate() != 0.0) {
			throw new IllegalStateException(
					"Canonical PT fare scoring requires the existing standard "
							+ "pt monetaryDistanceRate to be exactly zero; "
							+ "the component will not mutate it.");
		}
	}

	private static Scenario requireScenario(Scenario scenario) {
		return Objects.requireNonNull(scenario, "scenario");
	}
}
