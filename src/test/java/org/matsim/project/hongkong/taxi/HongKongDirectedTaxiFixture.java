package org.matsim.project.hongkong.taxi;

import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.api.core.v01.population.Person;

/** Test-only audit bridge for the Stage 10 selected-plan Taxi fixture. */
public final class HongKongDirectedTaxiFixture {

	private HongKongDirectedTaxiFixture() {
	}

	/**
	 * Reads the actual selected-plan Taxi route context and calculates its fare;
	 * this is an observed leg-level value, not a population or mode_detail proxy.
	 */
	public static double observedFareHkd(Person person) {
		for (PlanElement element : person.getSelectedPlan().getPlanElements()) {
			if (element instanceof Leg leg
					&& HongKongTaxiScoringParameters.TAXI_MODE.equals(leg.getMode())) {
				HongKongTaxiRouteContext context =
						HongKongTaxiRouteContext.from(leg);
				return new HongKongTaxiFareCalculator()
						.calculate(context.distanceMeters(), context.taxiType())
						.fareHkd();
			}
		}
		throw new IllegalStateException("Stage 10 fixture has no Taxi leg.");
	}
}
