package org.matsim.project.hongkong.taxi;

import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.contrib.drt.optimizer.constraints.DrtRouteConstraints;
import org.matsim.contrib.drt.routing.DrtRoute;
import org.matsim.contrib.dvrp.load.IntegerLoad;
import org.matsim.contrib.dvrp.load.IntegerLoadType;
import org.matsim.core.router.TripStructureUtils;

import java.util.IdentityHashMap;

/** Converts the historical teleported Taxi routes into request-ready DrtRoute instances. */
public final class HongKongPhysicalTaxiRoutePreparation {
	private static final IntegerLoadType PASSENGER_LOAD = new IntegerLoadType("passengers");

	private HongKongPhysicalTaxiRoutePreparation() {
	}

	public static PreparationStats prepare(Scenario scenario) {
		HongKongTaxiFareCalculator fareCalculator = new HongKongTaxiFareCalculator();
		long taxiLegs = 0;
		long convertedRoutes = 0;
		long copiedTripAttributes = 0;
		for (var person : scenario.getPopulation().getPersons().values()) {
			for (var plan : person.getPlans()) {
				var tripIndexByLeg = new IdentityHashMap<Leg, Integer>();
				var originByLeg = new IdentityHashMap<Leg, org.matsim.api.core.v01.population.Activity>();
				int mainTripIndex = 0;
				for (var trip : TripStructureUtils.getTrips(plan)) {
					for (Leg leg : trip.getLegsOnly()) {
						tripIndexByLeg.put(leg, mainTripIndex);
						originByLeg.put(leg, trip.getOriginActivity());
					}
					mainTripIndex++;
				}
				int fallbackTaxiIndex = mainTripIndex;
				for (var element : plan.getPlanElements()) {
					if (!(element instanceof Leg leg)
							|| !HongKongTaxiScoringParameters.TAXI_MODE.equals(leg.getMode())) continue;
					taxiLegs++;
					leg.setRoutingMode(HongKongTaxiScoringParameters.TAXI_MODE);
					stampMissingFareMetadata(
							leg, tripIndexByLeg.getOrDefault(leg, fallbackTaxiIndex++), fareCalculator);
					var origin = originByLeg.get(leg);
					if (origin != null) {
						for (String name : HongKongTaxiLegAttributes.NAMES) {
							Object value = leg.getAttributes().getAttribute(name);
							if (value != null && origin.getAttributes().getAttribute(name) == null) {
								origin.getAttributes().putAttribute(name, value);
								copiedTripAttributes++;
							}
						}
					}
					if (ensureDrtRoute(leg, person.getId().toString())) convertedRoutes++;
				}
			}
		}
		return new PreparationStats(taxiLegs, convertedRoutes, copiedTripAttributes);
	}

	private static boolean ensureDrtRoute(Leg leg, String personId) {
		if (leg.getRoute() instanceof DrtRoute) return false;
		if (leg.getRoute() == null) {
			throw new IllegalStateException("Physical Taxi leg has no route: person=" + personId);
		}
		var old = leg.getRoute();
		double directTime = old.getTravelTime().isDefined()
				? old.getTravelTime().seconds()
				: leg.getTravelTime().seconds();
		if (!Double.isFinite(directTime) || directTime < 0
				|| !Double.isFinite(old.getDistance()) || old.getDistance() < 0) {
			throw new IllegalStateException("Illegal historical Taxi route: person=" + personId);
		}
		DrtRoute route = new DrtRoute(old.getStartLinkId(), old.getEndLinkId());
		route.setDistance(old.getDistance());
		route.setDirectRideTime(directTime);
		route.setLoad(IntegerLoad.fromValue(1), PASSENGER_LOAD);
		route.setConstraints(new DrtRouteConstraints(
				2 * directTime + 3600,
				Double.MAX_VALUE,
				3600,
				Double.MAX_VALUE,
				0,
				false));
		leg.setRoute(route);
		return true;
	}

	private static void stampMissingFareMetadata(
			Leg leg, int mainTripIndex, HongKongTaxiFareCalculator fareCalculator) {
		if (leg.getRoute() == null || !Double.isFinite(leg.getRoute().getDistance())
				|| leg.getRoute().getDistance() < 0) {
			throw new IllegalStateException("Physical Taxi route lacks a finite distance");
		}
		var attributes = leg.getAttributes();
		String taxiType = attributes.getAttribute(HongKongTaxiLegAttributes.TAXI_TYPE) instanceof String value
				&& !value.isBlank() ? value : HongKongTaxiFareCalculator.UNRESOLVED;
		putIfBlank(attributes, HongKongTaxiLegAttributes.TAXI_TYPE, taxiType);
		putIfMissing(attributes, HongKongTaxiLegAttributes.FARE_BASELINE_HKD,
				fareCalculator.calculate(leg.getRoute().getDistance(), taxiType).fareHkd());
		putIfBlank(attributes, HongKongTaxiLegAttributes.FARE_SCOPE,
				HongKongTaxiScoringParameters.DISTANCE_ONLY_SCOPE);
		putIfBlank(attributes, HongKongTaxiLegAttributes.FARE_MODEL_VERSION,
				HongKongTaxiScoringParameters.FARE_MODEL_VERSION);
		putIfBlank(attributes, HongKongTaxiLegAttributes.CLASSIFICATION_SOURCE,
				"physical_taxi_dvrp_v1");
		putIfMissing(attributes, HongKongTaxiLegAttributes.MAIN_TRIP_INDEX, mainTripIndex);
	}

	private static void putIfMissing(
			org.matsim.utils.objectattributes.attributable.Attributes attributes,
			String name,
			Object value) {
		if (attributes.getAttribute(name) == null) attributes.putAttribute(name, value);
	}

	private static void putIfBlank(
			org.matsim.utils.objectattributes.attributable.Attributes attributes,
			String name,
			String value) {
		Object current = attributes.getAttribute(name);
		if (!(current instanceof String text) || text.isBlank()) {
			attributes.putAttribute(name, value);
		}
	}

	public record PreparationStats(long taxiLegs, long convertedRoutes, long copiedTripAttributes) {
	}
}
