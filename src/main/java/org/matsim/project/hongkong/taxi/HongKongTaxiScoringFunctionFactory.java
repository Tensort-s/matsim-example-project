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

	@Inject
	public HongKongTaxiScoringFunctionFactory(
			Scenario scenario,
			HongKongTaxiScoringParameters parameters) {
		this(
				new CharyparNagelScoringFunctionFactory(
						Objects.requireNonNull(scenario, "scenario")
				),
				scenario.getConfig(),
				parameters
		);
	}

	HongKongTaxiScoringFunctionFactory(
			ScoringFunctionFactory delegateFactory,
			Config config,
			HongKongTaxiScoringParameters parameters) {
		this.delegateFactory = Objects.requireNonNull(delegateFactory, "delegateFactory");
		this.parameters = Objects.requireNonNull(parameters, "parameters");
		this.parameters.validateConfig(Objects.requireNonNull(config, "config"));
	}

	@Override
	public ScoringFunction createNewScoringFunction(Person person) {
		Objects.requireNonNull(person, "person");
		return new HongKongTaxiScoringFunction(
				delegateFactory.createNewScoringFunction(person),
				new HongKongTaxiFareScoring(person.getId(), parameters)
		);
	}
}
