package org.matsim.project.hongkong.taxi;

import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Route;

import java.util.Objects;

/**
 * Route-derived inputs for current distance-only fare calculation and future
 * time-aware extensions.
 *
 * <p>Fare v1 consumes only {@link #distanceMeters()} and {@link #taxiType()}.
 * Travel time, departure time, and classification source are captured but are
 * deliberately not charged.</p>
 */
public record HongKongTaxiRouteContext(
		double distanceMeters,
		double travelTimeSeconds,
		double departureTimeSeconds,
		String taxiType,
		String classificationSource) {

	public static HongKongTaxiRouteContext from(Leg leg) {
		Objects.requireNonNull(leg, "leg");
		HongKongTaxiRouting.requireLegalRoute(leg);
		if (leg.getDepartureTime().isUndefined()) {
			throw new IllegalStateException(
					"Taxi departure time is undefined");
		}
		double departureTime = leg.getDepartureTime().seconds();
		if (!Double.isFinite(departureTime) || departureTime < 0.0) {
			throw new IllegalStateException(
					"Taxi departure time is illegal: " + departureTime);
		}
		Route route = leg.getRoute();
		return new HongKongTaxiRouteContext(
				route.getDistance(),
				route.getTravelTime().seconds(),
				departureTime,
				requireStringAttribute(leg, HongKongTaxiLegAttributes.TAXI_TYPE),
				requireStringAttribute(
						leg, HongKongTaxiLegAttributes.CLASSIFICATION_SOURCE));
	}

	private static String requireStringAttribute(Leg leg, String name) {
		Object value = leg.getAttributes().getAttribute(name);
		if (!(value instanceof String text) || text.isBlank()) {
			throw new IllegalStateException(
					"Taxi route context requires non-blank attribute " + name);
		}
		return text;
	}
}
