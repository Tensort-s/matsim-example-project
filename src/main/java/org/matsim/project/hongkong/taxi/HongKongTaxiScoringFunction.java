package org.matsim.project.hongkong.taxi;

import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.core.router.TripStructureUtils;
import org.matsim.core.scoring.ScoringFunction;

import java.util.Objects;

/**
 * Preserves the complete standard MATSim scoring function and adds one
 * independent taxi fare component.
 */
public final class HongKongTaxiScoringFunction implements ScoringFunction {

	private final ScoringFunction delegate;
	private final HongKongTaxiFareScoring taxiFareScoring;

	public HongKongTaxiScoringFunction(
			ScoringFunction delegate,
			HongKongTaxiFareScoring taxiFareScoring) {
		this.delegate = Objects.requireNonNull(delegate, "delegate");
		this.taxiFareScoring = Objects.requireNonNull(taxiFareScoring, "taxiFareScoring");
	}

	@Override
	public void handleActivity(Activity activity) {
		delegate.handleActivity(activity);
	}

	@Override
	public void handleLeg(Leg leg) {
		taxiFareScoring.handleLeg(leg);
		delegate.handleLeg(leg);
	}

	@Override
	public void agentStuck(double time) {
		delegate.agentStuck(time);
	}

	@Override
	public void addMoney(double amount) {
		delegate.addMoney(amount);
	}

	@Override
	public void addScore(double amount) {
		delegate.addScore(amount);
	}

	@Override
	public void finish() {
		delegate.finish();
		taxiFareScoring.finish();
	}

	@Override
	public double getScore() {
		return delegate.getScore() + taxiFareScoring.getScore();
	}

	@Override
	public void handleEvent(Event event) {
		delegate.handleEvent(event);
	}

	@Override
	public void handleTrip(TripStructureUtils.Trip trip) {
		delegate.handleTrip(trip);
	}

	@Override
	public void explainScore(StringBuilder out) {
		delegate.explainScore(out);
		if (!out.isEmpty()) {
			out.append(SCORE_DELIMITER);
		}
		taxiFareScoring.explainScore(out);
	}
}
