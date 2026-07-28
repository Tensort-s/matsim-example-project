package org.matsim.project.hongkong.taxi;

import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.scoring.SumScoringFunction;

import java.util.Objects;

/** Adds only the embedded distance-only taxi fare disutility. */
public final class HongKongTaxiFareScoring implements SumScoringFunction.LegScoring {

	private final Id<Person> personId;
	private final HongKongTaxiScoringParameters parameters;
	private double score;
	private int scoredTaxiLegs;

	public HongKongTaxiFareScoring(
			Id<Person> personId,
			HongKongTaxiScoringParameters parameters) {
		this.personId = Objects.requireNonNull(personId, "personId");
		this.parameters = Objects.requireNonNull(parameters, "parameters");
	}

	@Override
	public void handleLeg(Leg leg) {
		if (!HongKongTaxiScoringParameters.TAXI_MODE.equals(leg.getMode())) {
			return;
		}
		HongKongTaxiLegAttributes.Metadata metadata =
				HongKongTaxiLegAttributes.readAndValidate(leg, personId, parameters);
		score += parameters.fareScore(metadata.fareBaselineHkd());
		scoredTaxiLegs++;
	}

	@Override
	public void finish() {
		// Fare is charged exactly when each taxi leg is handled.
	}

	@Override
	public double getScore() {
		return score;
	}

	@Override
	public void explainScore(StringBuilder out) {
		out.append("hongKongTaxiFare[person_id=")
				.append(personId)
				.append(",taxiLegs=")
				.append(scoredTaxiLegs)
				.append(",fareUtilityPerHkd=")
				.append(parameters.fareUtilityPerHkd())
				.append(",fareShareFactor=")
				.append(parameters.fareShareFactor())
				.append(",score=")
				.append(score)
				.append(']');
	}
}
