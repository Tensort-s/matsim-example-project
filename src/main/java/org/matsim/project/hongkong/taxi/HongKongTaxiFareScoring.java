package org.matsim.project.hongkong.taxi;

import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.scoring.SumScoringFunction;
import org.matsim.project.hongkong.scoring.HongKongScoringComponent;

import java.util.Objects;

/** Adds only the selected-plan-scheduled, distance-only taxi fare disutility. */
public final class HongKongTaxiFareScoring
		implements SumScoringFunction.LegScoring, HongKongScoringComponent {

	private final Id<Person> personId;
	private final HongKongTaxiPersonFareSchedule fareSchedule;
	private final HongKongTaxiScoringParameters parameters;
	private double score;
	private int consumedTaxiLegs;
	private boolean finished;

	public HongKongTaxiFareScoring(
			HongKongTaxiPersonFareSchedule fareSchedule,
			HongKongTaxiScoringParameters parameters) {
		this.fareSchedule = Objects.requireNonNull(fareSchedule, "fareSchedule");
		this.personId = fareSchedule.personId();
		this.parameters = Objects.requireNonNull(parameters, "parameters");
	}

	@Override
	public String componentId() {
		return HongKongTaxiFareScoringComponentFactory.COMPONENT_ID;
	}

	@Override
	public void handleLeg(Leg leg) {
		Objects.requireNonNull(leg, "leg");
		if (!HongKongTaxiScoringParameters.TAXI_MODE.equals(leg.getMode())) {
			return;
		}
		if (finished) {
			throw mismatch(
					leg,
					"experienced taxi leg received after scoring was finished"
			);
		}
		if (!HongKongTaxiScoringParameters.TAXI_MODE.equals(
				leg.getRoutingMode())) {
			throw mismatch(
					leg,
					"experienced taxi leg must have routingMode=taxi"
			);
		}
		if (consumedTaxiLegs >= fareSchedule.size()) {
			throw mismatch(
					leg,
					"experienced taxi leg has no corresponding selected-plan fare record"
			);
		}

		HongKongTaxiPersonFareSchedule.RouteFare routeFare =
				fareSchedule.fareAt(consumedTaxiLegs);
		score += parameters.fareScore(routeFare.calculation().fareHkd());
		consumedTaxiLegs++;
	}

	@Override
	public void finish() {
		if (consumedTaxiLegs != fareSchedule.size()) {
			throw mismatch(
					null,
					"scoring finished before every selected-plan taxi fare record was consumed"
			);
		}
		finished = true;
	}

	@Override
	public double getScore() {
		return score;
	}

	@Override
	public void explainScore(StringBuilder out) {
		out.append("hongKongTaxiFare[person_id=")
				.append(personId)
				.append(",consumedTaxiLegs=")
				.append(consumedTaxiLegs)
				.append(",expectedTaxiLegs=")
				.append(fareSchedule.size())
				.append(",fareUtilityPerHkd=")
				.append(parameters.fareUtilityPerHkd())
				.append(",fareShareFactor=")
				.append(parameters.fareShareFactor())
				.append(",score=")
				.append(score)
				.append(']');
	}

	private IllegalStateException mismatch(Leg actualLeg, String reason) {
		String actualMode = actualLeg == null ? "<finish>" : String.valueOf(actualLeg.getMode());
		String actualRoutingMode =
				actualLeg == null ? "<none>" : String.valueOf(actualLeg.getRoutingMode());
		return new IllegalStateException(
				"Hong Kong taxi fare schedule mismatch: person_id=" + personId
						+ ", taxi_ordinal=" + consumedTaxiLegs
						+ ", expected_count=" + fareSchedule.size()
						+ ", consumed_count=" + consumedTaxiLegs
						+ ", actual_mode=" + actualMode
						+ ", actual_routingMode=" + actualRoutingMode
						+ ", reason=" + reason
		);
	}
}
