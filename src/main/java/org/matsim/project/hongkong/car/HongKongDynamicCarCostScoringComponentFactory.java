package org.matsim.project.hongkong.car;

import com.google.inject.Inject;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.Person;
import org.matsim.project.hongkong.scoring.HongKongScoringComponent;
import org.matsim.project.hongkong.scoring.HongKongScoringComponentFactory;

import java.util.Objects;
import java.util.Set;

/** Creates person-local experienced-event dynamic Car cost scorers. */
public final class HongKongDynamicCarCostScoringComponentFactory
		implements HongKongScoringComponentFactory {

	public static final String COMPONENT_ID = "car_dynamic_energy_toll_parking_v1";

	private final Scenario scenario;
	private final HongKongDynamicCarCostRules rules;
	private final HongKongDynamicCarCostRunAudit audit;
	private final double marginalUtilityOfMoney;
	private final double simulationEndTimeS;

	@Inject
	public HongKongDynamicCarCostScoringComponentFactory(
			Scenario scenario,
			HongKongDynamicCarCostRules rules,
			HongKongDynamicCarCostRunAudit audit) {
		this.scenario = Objects.requireNonNull(scenario, "scenario");
		this.rules = Objects.requireNonNull(rules, "rules");
		this.audit = Objects.requireNonNull(audit, "audit");
		HongKongCarEnergyScoringComponentFactory.requireNoStandardCarMonetaryDistanceCharge(
				scenario.getConfig());
		this.marginalUtilityOfMoney = scenario.getConfig().scoring().getMarginalUtilityOfMoney();
		this.simulationEndTimeS = scenario.getConfig().qsim().getEndTime().orElse(30.0 * 3_600.0);
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
		return new HongKongDynamicCarCostScoring(
				person, scenario.getNetwork(), rules, audit,
				marginalUtilityOfMoney, simulationEndTimeS);
	}
}
