package org.matsim.project.hongkong.walk;

import org.matsim.api.core.v01.TransportMode;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.PlanElement;

import java.util.List;

/** One-per-main-trip penalty for cumulative Walk above ten minutes. */
public final class HongKongWalkOvertimeUtility {
	public static final double THRESHOLD_SECONDS = 600.0;
	public static final double OVERTIME_UTILITY_PER_HOUR = 3.278342;

	private HongKongWalkOvertimeUtility() { }

	public static double penaltyForWalkSeconds(double walkSeconds) {
		if (!Double.isFinite(walkSeconds) || walkSeconds < 0.0) {
			throw new IllegalArgumentException("Invalid cumulative Walk time " + walkSeconds);
		}
		if (walkSeconds <= THRESHOLD_SECONDS) return 0.0;
		return -OVERTIME_UTILITY_PER_HOUR
				* Math.max(0.0, (walkSeconds - THRESHOLD_SECONDS) / 3_600.0);
	}

	public static double penaltyForTrip(List<? extends PlanElement> elements) {
		double seconds = 0.0;
		for (PlanElement element : elements) {
			if (!(element instanceof Leg leg) || !isWalkLeg(leg)) continue;
			seconds += requiredTravelTime(leg);
		}
		return penaltyForWalkSeconds(seconds);
	}

	public static boolean isWalkLeg(Leg leg) {
		return TransportMode.walk.equals(leg.getMode())
				|| TransportMode.non_network_walk.equals(leg.getMode());
	}

	private static double requiredTravelTime(Leg leg) {
		if (leg.getTravelTime().isDefined()) return leg.getTravelTime().seconds();
		if (leg.getRoute() != null && leg.getRoute().getTravelTime().isDefined()) {
			return leg.getRoute().getTravelTime().seconds();
		}
		throw new IllegalStateException("Walk leg lacks travel time");
	}
}
