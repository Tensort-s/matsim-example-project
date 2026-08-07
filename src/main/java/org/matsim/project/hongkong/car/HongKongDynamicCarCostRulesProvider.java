package org.matsim.project.hongkong.car;

import com.google.inject.Inject;
import com.google.inject.name.Named;
import jakarta.inject.Provider;
import org.matsim.api.core.v01.Scenario;

import java.nio.file.Path;
import java.util.Objects;

/** Loads dynamic rules only after Guice has supplied the fully loaded scenario. */
final class HongKongDynamicCarCostRulesProvider
		implements Provider<HongKongDynamicCarCostRules> {

	private final Scenario scenario;
	private final Path carCostRoot;

	@Inject
	HongKongDynamicCarCostRulesProvider(
			Scenario scenario,
			@Named(HongKongDynamicCarCostModule.CAR_COST_ROOT_BINDING)
			Path carCostRoot) {
		this.scenario = Objects.requireNonNull(scenario, "scenario");
		this.carCostRoot = Objects.requireNonNull(carCostRoot, "carCostRoot");
	}

	@Override
	public HongKongDynamicCarCostRules get() {
		return HongKongDynamicCarCostRules.load(carCostRoot, scenario.getNetwork());
	}
}
