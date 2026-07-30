package org.matsim.project.hongkong.taxi;

import com.google.inject.Inject;
import com.google.inject.name.Named;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.api.core.v01.population.Route;
import org.matsim.core.router.RoutingModule;
import org.matsim.core.router.RoutingRequest;

import java.util.List;

/**
 * Taxi-facing wrapper around MATSim's standard teleported routing algorithm.
 */
public final class HongKongTaxiRouting implements RoutingModule {

	private static final String TAXI_MODE = HongKongTaxiRoutingModule.TAXI_MODE;
	private final RoutingModule delegate;

	@Inject
	public HongKongTaxiRouting(@Named("ride") RoutingModule rideDelegate) {
		this.delegate = rideDelegate;
	}

	@Override
	public List<? extends PlanElement> calcRoute(RoutingRequest request) {
		List<? extends PlanElement> result = delegate.calcRoute(request);
		if (result.size() != 1 || !(result.getFirst() instanceof Leg leg)) {
			throw new IllegalStateException(
					"Taxi teleported router must return exactly one leg");
		}

		for (String name : HongKongTaxiLegAttributes.NAMES) {
			if (!request.getAttributes().getAsMap().containsKey(name)) {
				throw new IllegalStateException(
						"Taxi routing request is missing trip attribute " + name);
			}
			leg.getAttributes().putAttribute(
					name, request.getAttributes().getAttribute(name));
		}
		leg.setMode(TAXI_MODE);
		leg.setRoutingMode(TAXI_MODE);
		requireLegalRoute(leg);
		return List.of(leg);
	}

	static void requireLegalRoute(Leg leg) {
		if (!TAXI_MODE.equals(leg.getMode())
				|| !TAXI_MODE.equals(leg.getRoutingMode())) {
			throw new IllegalStateException(
					"Taxi router returned a non-Taxi leg: mode=" + leg.getMode()
							+ ", routingMode=" + leg.getRoutingMode());
		}
		Route route = leg.getRoute();
		if (route == null) {
			throw new IllegalStateException("Taxi router returned a null route");
		}
		requireFiniteNonNegative("route distance", route.getDistance());
		if (route.getTravelTime().isUndefined()) {
			throw new IllegalStateException(
					"Taxi router returned an undefined route travel time");
		}
		requireFiniteNonNegative(
				"route travel time", route.getTravelTime().seconds());
		if (leg.getTravelTime().isUndefined()) {
			throw new IllegalStateException(
					"Taxi router returned an undefined leg travel time");
		}
		requireFiniteNonNegative(
				"leg travel time", leg.getTravelTime().seconds());
	}

	private static void requireFiniteNonNegative(String field, double value) {
		if (!Double.isFinite(value) || value < 0.0) {
			throw new IllegalStateException(
					"Taxi router returned illegal " + field + ": " + value);
		}
	}
}
