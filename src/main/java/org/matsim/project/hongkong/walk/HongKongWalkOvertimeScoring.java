package org.matsim.project.hongkong.walk;

import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.core.router.TripStructureUtils;
import org.matsim.project.hongkong.scoring.HongKongScoringComponent;

/** Runtime implementation of the cumulative per-main-trip Walk penalty. */
public final class HongKongWalkOvertimeScoring implements HongKongScoringComponent {
	private final HongKongWalkScoringParameters parameters;
	private double score;
	private double currentTripWalkSeconds;
	private boolean currentTripHasNonWalkLeg;
	private boolean sawMainActivity;

	public HongKongWalkOvertimeScoring() {
		this(HongKongWalkScoringParameters.legacyV1());
	}

	public HongKongWalkOvertimeScoring(HongKongWalkScoringParameters parameters) {
		this.parameters = parameters;
	}

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
		if (!HongKongWalkOvertimeUtility.isWalkLeg(leg)) {
			currentTripHasNonWalkLeg = true;
			return;
		}
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
		if (!parameters.mainWalkTripsOnly() || !currentTripHasNonWalkLeg) {
			score += HongKongWalkOvertimeUtility.penaltyForWalkSeconds(
					currentTripWalkSeconds, parameters);
		}
		currentTripWalkSeconds = 0.0;
		currentTripHasNonWalkLeg = false;
	}
}
