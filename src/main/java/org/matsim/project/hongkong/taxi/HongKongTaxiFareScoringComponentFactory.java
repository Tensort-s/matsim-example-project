package org.matsim.project.hongkong.taxi;

import com.google.inject.Inject;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.config.Config;
import org.matsim.project.hongkong.scoring.HongKongScoringComponent;
import org.matsim.project.hongkong.scoring.HongKongScoringComponentFactory;

import java.util.Objects;
import java.util.Set;

/** Taxi-only adapter from the established ordinal route-fare scorer. */
public final class HongKongTaxiFareScoringComponentFactory
		implements HongKongScoringComponentFactory {

	public static final String COMPONENT_ID = "taxi_route_fare_v1";

	private final HongKongTaxiScoringParameters parameters;
	private final HongKongTaxiFareCalculator fareCalculator;

	@Inject
	public HongKongTaxiFareScoringComponentFactory(
			Scenario scenario,
			HongKongTaxiScoringParameters parameters,
			HongKongTaxiFareCalculator fareCalculator) {
		this(
				Objects.requireNonNull(scenario, "scenario").getConfig(),
				parameters,
				fareCalculator);
	}

	HongKongTaxiFareScoringComponentFactory(
			Config config,
			HongKongTaxiScoringParameters parameters,
			HongKongTaxiFareCalculator fareCalculator) {
		this.parameters = Objects.requireNonNull(parameters, "parameters");
		this.fareCalculator = Objects.requireNonNull(fareCalculator, "fareCalculator");
		this.parameters.validateConfig(Objects.requireNonNull(config, "config"));
	}

	@Override
	public String componentId() {
		return COMPONENT_ID;
	}

	@Override
	public Set<String> activeModes() {
		return Set.of(HongKongTaxiScoringParameters.TAXI_MODE);
	}

	@Override
	public HongKongScoringComponent createComponent(Person person) {
		return new HongKongTaxiFareScoring(
				routeFareScheduleFor(Objects.requireNonNull(person, "person")),
				parameters);
	}

	HongKongTaxiPersonFareSchedule routeFareScheduleFor(Person person) {
		return HongKongTaxiPersonFareSchedule.fromSelectedPlan(
				Objects.requireNonNull(person, "person"), fareCalculator);
	}
}
