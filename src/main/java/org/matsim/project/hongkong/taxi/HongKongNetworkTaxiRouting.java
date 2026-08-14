package org.matsim.project.hongkong.taxi;

import com.google.inject.Inject;
import com.google.inject.name.Named;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.core.router.RoutingModule;
import org.matsim.core.router.RoutingRequest;

import java.util.List;

/** Adds auditable fare metadata to the standard network Taxi route. */
public final class HongKongNetworkTaxiRouting implements RoutingModule {
	private final RoutingModule delegate;
	private final HongKongTaxiFareCalculator fareCalculator = new HongKongTaxiFareCalculator();

	@Inject
	public HongKongNetworkTaxiRouting(
			@Named(HongKongNetworkTaxiRoutingModule.DELEGATE_BINDING) RoutingModule delegate) {
		this.delegate = delegate;
	}

	@Override
	public List<? extends PlanElement> calcRoute(RoutingRequest request) {
		List<? extends PlanElement> result = delegate.calcRoute(request);
		Leg taxi = result.stream().filter(Leg.class::isInstance).map(Leg.class::cast)
				.filter(leg -> HongKongTaxiScoringParameters.TAXI_MODE.equals(leg.getMode()))
				.findFirst().orElseThrow(() -> new IllegalStateException(
						"Network Taxi routing returned no Taxi leg"));
		double distance = taxi.getRoute() == null ? Double.NaN : taxi.getRoute().getDistance();
		if (!Double.isFinite(distance) || distance < 0.0) {
			throw new IllegalStateException("Network Taxi route has invalid distance " + distance);
		}
		String taxiType = stringAttribute(request, HongKongTaxiLegAttributes.TAXI_TYPE,
				HongKongTaxiFareCalculator.UNRESOLVED);
		double fare = fareCalculator.calculate(distance, taxiType).fareHkd();
		put(taxi, HongKongTaxiLegAttributes.FARE_BASELINE_HKD, fare);
		put(taxi, HongKongTaxiLegAttributes.TAXI_TYPE, taxiType);
		put(taxi, HongKongTaxiLegAttributes.FARE_SCOPE,
				HongKongTaxiScoringParameters.DISTANCE_ONLY_SCOPE);
		put(taxi, HongKongTaxiLegAttributes.FARE_MODEL_VERSION,
				HongKongTaxiScoringParameters.FARE_MODEL_VERSION);
		put(taxi, HongKongTaxiLegAttributes.CLASSIFICATION_SOURCE,
				stringAttribute(request, HongKongTaxiLegAttributes.CLASSIFICATION_SOURCE,
						"all_person_network_taxi_proxy_v1"));
		Object index = request.getAttributes().getAttribute(HongKongTaxiLegAttributes.MAIN_TRIP_INDEX);
		put(taxi, HongKongTaxiLegAttributes.MAIN_TRIP_INDEX,
				index instanceof Integer value && value >= 0 ? value : 0);
		taxi.setRoutingMode(HongKongTaxiScoringParameters.TAXI_MODE);
		HongKongTaxiRouting.requireLegalRoute(taxi);
		return result;
	}

	private static String stringAttribute(RoutingRequest request, String name, String fallback) {
		Object value = request.getAttributes().getAttribute(name);
		return value == null || value.toString().isBlank() ? fallback : value.toString();
	}

	private static void put(Leg leg, String name, Object value) {
		leg.getAttributes().putAttribute(name, value);
	}
}
