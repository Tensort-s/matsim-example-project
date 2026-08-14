package org.matsim.project.hongkong.walk;

import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.core.router.TripStructureUtils;
import org.matsim.project.hongkong.scoring.HongKongScoringComponent;

/** Runtime implementation of the cumulative per-main-trip Walk penalty. */
public final class HongKongWalkOvertimeScoring implements HongKongScoringComponent {
	private double score;
	private double currentTripWalkSeconds;
	private boolean sawMainActivity;

	@Override
	public String componentId() {
		return HongKongWalkOvertimeScoringComponentFactory.COMPONENT_ID;
	}

	@Override
	public void handleActivity(Activity activity) {
		if (TripStructureUtils.isStageActivityType(activity.getType())) return;
		if (sawMainActivity) closeTrip();
		sawMainActivity = true;
	}

	@Override
	public void handleLeg(Leg leg) {
		if (!HongKongWalkOvertimeUtility.isWalkLeg(leg)) return;
		if (leg.getTravelTime().isDefined()) {
			currentTripWalkSeconds += leg.getTravelTime().seconds();
		} else if (leg.getRoute() != null && leg.getRoute().getTravelTime().isDefined()) {
			currentTripWalkSeconds += leg.getRoute().getTravelTime().seconds();
		} else {
			throw new IllegalStateException("Experienced Walk leg lacks travel time");
		}
	}

	@Override
	public void finish() {
		if (currentTripWalkSeconds > 0.0) closeTrip();
	}

	@Override
	public double getScore() {
		return score;
	}

	private void closeTrip() {
		score += HongKongWalkOvertimeUtility.penaltyForWalkSeconds(currentTripWalkSeconds);
		currentTripWalkSeconds = 0.0;
	}
}
