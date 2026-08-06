package org.matsim.project.hongkong.taxi;

import com.google.inject.Inject;
import com.google.inject.name.Named;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.core.router.RoutingModule;
import org.matsim.core.router.RoutingRequest;

import java.util.List;

/** Taxi wrapper around the explicit car-passenger teleported router. */
public final class HongKongNoRideTaxiRouting implements RoutingModule {

	private final RoutingModule delegate;

	@Inject
	public HongKongNoRideTaxiRouting(
			@Named(HongKongNoRideTaxiRoutingModule.PASSENGER_DELEGATE_MODE)
			RoutingModule passengerDelegate) {
		this.delegate = passengerDelegate;
	}

	@Override
	public List<? extends PlanElement> calcRoute(RoutingRequest request) {
		List<? extends PlanElement> result = delegate.calcRoute(request);
		if (result.size() != 1 || !(result.getFirst() instanceof Leg leg)) {
			throw new IllegalStateException(
					"Taxi passenger router must return exactly one leg");
		}
		for (String name : HongKongTaxiLegAttributes.NAMES) {
			if (!request.getAttributes().getAsMap().containsKey(name)) {
				throw new IllegalStateException(
						"Taxi routing request is missing trip attribute " + name);
			}
			leg.getAttributes().putAttribute(
					name, request.getAttributes().getAttribute(name));
		}
		leg.setMode(HongKongNoRideTaxiRoutingModule.TAXI_MODE);
		leg.setRoutingMode(HongKongNoRideTaxiRoutingModule.TAXI_MODE);
		HongKongTaxiRouting.requireLegalRoute(leg);
		return List.of(leg);
	}
}
