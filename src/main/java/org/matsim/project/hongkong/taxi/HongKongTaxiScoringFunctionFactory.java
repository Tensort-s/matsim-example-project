package org.matsim.project.hongkong.taxi;

import com.google.inject.Inject;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.config.Config;
import org.matsim.core.scoring.ScoringFunction;
import org.matsim.core.scoring.ScoringFunctionFactory;
import org.matsim.core.scoring.functions.CharyparNagelScoringFunctionFactory;

import java.util.Objects;

/**
 * Creates a standard Charypar-Nagel delegate plus person-local taxi fare
 * state.
 */
public final class HongKongTaxiScoringFunctionFactory implements ScoringFunctionFactory {

	private final ScoringFunctionFactory delegateFactory;
	private final HongKongTaxiScoringParameters parameters;
	private final HongKongTaxiFareCalculator fareCalculator;

	@Inject
	public HongKongTaxiScoringFunctionFactory(
			Scenario scenario,
			HongKongTaxiScoringParameters parameters,
			HongKongTaxiFareCalculator fareCalculator) {
		this(
				new CharyparNagelScoringFunctionFactory(
						Objects.requireNonNull(scenario, "scenario")
				),
				scenario.getConfig(),
				parameters,
				fareCalculator
		);
	}

	HongKongTaxiScoringFunctionFactory(
			ScoringFunctionFactory delegateFactory,
			Config config,
			HongKongTaxiScoringParameters parameters,
			HongKongTaxiFareCalculator fareCalculator) {
		this.delegateFactory = Objects.requireNonNull(delegateFactory, "delegateFactory");
		this.parameters = Objects.requireNonNull(parameters, "parameters");
		this.fareCalculator = Objects.requireNonNull(fareCalculator, "fareCalculator");
		this.parameters.validateConfig(Objects.requireNonNull(config, "config"));
	}

	@Override
	public ScoringFunction createNewScoringFunction(Person person) {
		Objects.requireNonNull(person, "person");
		HongKongTaxiPersonFareSchedule fareSchedule =
				HongKongTaxiPersonFareSchedule.fromSelectedPlan(person, fareCalculator);
		return new HongKongTaxiScoringFunction(
				delegateFactory.createNewScoringFunction(person),
				new HongKongTaxiFareScoring(fareSchedule, parameters)
		);
	}
}
