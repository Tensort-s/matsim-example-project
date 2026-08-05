package org.matsim.project.hongkong.car;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.population.routes.NetworkRoute;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.router.TripStructureUtils;
import org.matsim.facilities.ActivityFacility;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HongKongCarParkingScoringTest {

	private static final String CANDIDATE_PATH =
			"data/transport_costs/hongkong/car_cost_v1/"
					+ "parking_event_application_v1/"
					+ "car_leg_parking_cost_estimates_base.parquet";
	private static final String CANDIDATE_SHA =
			"c2270353c3276691a7a55c77d2576b228ab68ed3c935b64f68419299f438b753";

	@Test
	void resolvedDestinationParkingChargesExactlyOnceAndCallbacksAreInert() {
		Fixture fixture = fixture(
				"charge", resolvedCharge("charge", 0, 40.0));
		var scoring = new HongKongCarParkingScoring(
				HongKongCarParkingPersonSchedule.fromSelectedPlan(
						fixture.person, fixture.catalog),
				2.0);
		scoring.handleLeg(fixture.carLeg);
		assertEquals(-80.0, scoring.getScore(), 0.0);
		assertEquals(40.0, scoring.chargedParkingHkd(), 0.0);
		assertEquals(1, scoring.resolvedChargeLegs());

		scoring.addMoney(-40.0);
		scoring.addScore(100.0);
		scoring.agentStuck(500.0);
		scoring.handleEvent(new Event(500.0) {
			@Override
			public String getEventType() {
				return "stage8c_duplicate_probe";
			}
		});
		scoring.handleTrip(TripStructureUtils.getTrips(
				fixture.person.getSelectedPlan()).getFirst());
		assertEquals(-80.0, scoring.getScore(), 0.0);
		assertThrows(IllegalStateException.class,
				() -> scoring.handleLeg(fixture.carLeg));
		scoring.finish();
		StringBuilder explanation = new StringBuilder();
		scoring.explainScore(explanation);
		assertTrue(explanation.toString().contains("nearestLocationInferences=0"));
		assertTrue(explanation.toString().contains("facilityCandidateFallbacks=0"));
		assertTrue(explanation.toString().contains("distanceInferences=0"));
		assertTrue(explanation.toString().contains("fixedOwnershipCharges=0"));
	}

	@Test
	void homeMarginalZeroIsResolvedLegalZeroNotUnresolvedFill() {
		Fixture fixture = fixture("home-zero", legalHomeZero("home-zero", 0));
		var scoring = new HongKongCarParkingScoring(
				HongKongCarParkingPersonSchedule.fromSelectedPlan(
						fixture.person, fixture.catalog), 1.0);
		scoring.handleLeg(fixture.carLeg);
		scoring.finish();
		assertEquals(0.0, scoring.getScore(), 0.0);
		assertEquals(1, scoring.resolvedLegalZeroLegs());
		assertEquals(0, scoring.unresolvedNullLegs());
	}

	@Test
	void knownAmbiguousParkingRemainsExplicitNullWithoutCharge() {
		Fixture fixture = fixture(
				"ambiguous", unresolved("ambiguous", 0,
						"unresolved_next_departure_facility_mismatch",
						"next_departure_facility_differs_from_parking_destination"));
		var schedule = HongKongCarParkingPersonSchedule.fromSelectedPlan(
				fixture.person, fixture.catalog);
		assertEquals(1, schedule.audit().unresolvedLegs());
		assertNull(schedule.parkingAt(0).quote().costHkd());
		var scoring = new HongKongCarParkingScoring(schedule, 1.0);
		scoring.handleLeg(fixture.carLeg);
		scoring.finish();
		assertEquals(0.0, scoring.getScore(), 0.0);
		assertEquals(1, scoring.unresolvedNullLegs());
		assertEquals(0.0, scoring.chargedParkingHkd(), 0.0);
	}

	@Test
	void missingKeyAndDestinationIdentityDriftFailClosedWithoutInference() {
		Person missing = person("missing", "work", "destination");
		assertThrows(IllegalStateException.class,
				() -> HongKongCarParkingPersonSchedule.fromSelectedPlan(
						missing,
						HongKongCarParkingCostCatalog.builder().buildForTests()));

		Fixture mismatch = fixture(
				"mismatch", resolvedCharge("mismatch", 0, 40.0));
		Activity destination = (Activity) mismatch.person.getSelectedPlan()
				.getPlanElements().get(2);
		destination.setFacilityId(
				Id.create("nearest-but-not-canonical", ActivityFacility.class));
		IllegalStateException error = assertThrows(
				IllegalStateException.class,
				() -> HongKongCarParkingPersonSchedule.fromSelectedPlan(
						mismatch.person, mismatch.catalog));
		assertTrue(error.getMessage().contains("destination facility mismatch"));
	}

	@Test
	void selectedPlanTimeAndActivityTypeMustMatchCanonicalSource() {
		Fixture fixture = fixture(
				"time", resolvedCharge("time", 0, 40.0));
		fixture.carLeg.setDepartureTime(101.0);
		assertThrows(IllegalStateException.class,
				() -> HongKongCarParkingPersonSchedule.fromSelectedPlan(
						fixture.person, fixture.catalog));

		Fixture type = fixture(
				"type", resolvedCharge("type", 0, 40.0));
		Activity destination = (Activity) type.person.getSelectedPlan()
				.getPlanElements().get(2);
		destination.setType("shopping");
		assertThrows(IllegalStateException.class,
				() -> HongKongCarParkingPersonSchedule.fromSelectedPlan(
						type.person, type.catalog));
	}

	@Test
	void vehicleNextDepartureIsNotTheArrivingPersonsActivityEndTime() {
		Fixture fixture = fixture(
				"nonconsecutive-car-use",
				resolvedCharge("nonconsecutive-car-use", 0, 40.0));
		Activity destination = (Activity) fixture.person.getSelectedPlan()
				.getPlanElements().get(2);
		destination.setEndTime(700.0);

		var schedule = HongKongCarParkingPersonSchedule.fromSelectedPlan(
				fixture.person, fixture.catalog);

		assertEquals(1, schedule.size());
		assertEquals(500.0,
				schedule.parkingAt(0).quote().nextDepartureTimeS(), 0.0);
	}

	@Test
	void preparedRouteReplacementKeepsDestinationParkingOrdinal() {
		Fixture fixture = fixture(
				"runtime-reroute", resolvedCharge("runtime-reroute", 0, 40.0));
		var scoring = new HongKongCarParkingScoring(
				HongKongCarParkingPersonSchedule.fromSelectedPlan(
						fixture.person, fixture.catalog), 1.0);
		fixture.carLeg.getRoute().setDistance(1_001.0);
		scoring.handleLeg(fixture.carLeg);
		scoring.finish();
		assertEquals(-40.0, scoring.getScore(), 0.0);
		assertEquals(1, scoring.consumedCarLegs());
	}

	@Test
	void stuckAgentMayLeaveUnreachedParkingUnconsumed() {
		Fixture fixture = fixture(
				"stuck", resolvedCharge("stuck", 0, 40.0));
		var scoring = new HongKongCarParkingScoring(
				HongKongCarParkingPersonSchedule.fromSelectedPlan(
						fixture.person, fixture.catalog), 1.0);
		scoring.agentStuck(10_000.0);
		scoring.finish();
		assertEquals(0, scoring.consumedCarLegs());
		assertEquals(0.0, scoring.getScore(), 0.0);
	}

	@Test
	void motorcycleRemainsOutOfScopeAndFixedOwnershipAbsent() {
		Fixture fixture = fixture(
				"motorcycle", motorcycle("motorcycle", 0));
		var schedule = HongKongCarParkingPersonSchedule.fromSelectedPlan(
				fixture.person, fixture.catalog);
		var scoring = new HongKongCarParkingScoring(schedule, 1.0);
		scoring.handleLeg(fixture.carLeg);
		scoring.finish();
		assertEquals(0.0, scoring.getScore(), 0.0);
		assertEquals(1, scoring.motorcycleOutOfScopeLegs());
		assertEquals(0, schedule.audit().fixedOwnershipCharges());
	}

	@Test
	void invalidNumericAndDuplicateParkingRecordsFailClosed() {
		assertThrows(IllegalArgumentException.class,
				() -> quote("invalid", 0, "private_car", Double.NaN,
						"resolved_proxy_charge",
						HongKongCarParkingCostCatalog.Resolution.RESOLVED_CHARGE,
						"work", ""));
		var duplicate = legalHomeZero("duplicate", 0);
		assertThrows(IllegalStateException.class,
				() -> HongKongCarParkingCostCatalog.builder()
						.quote(duplicate).quote(duplicate));
	}

	private static Fixture fixture(
			String id,
			HongKongCarParkingCostCatalog.ParkingQuote quote) {
		Person person = person(
				id, quote.destinationActivityType(), quote.destinationFacilityId());
		Leg leg = (Leg) person.getSelectedPlan().getPlanElements().get(1);
		return new Fixture(
				person,
				leg,
				HongKongCarParkingCostCatalog.builder()
						.quote(quote).buildForTests());
	}

	static Person person(String id, String destinationType, String facilityId) {
		Person person = PopulationUtils.getFactory().createPerson(
				Id.createPersonId(id));
		Plan plan = PopulationUtils.createPlan(person);
		Activity origin = PopulationUtils.createActivityFromCoord(
				"home", new Coord(0.0, 0.0));
		origin.setFacilityId(Id.create("origin", ActivityFacility.class));
		origin.setEndTime(100.0);
		plan.addActivity(origin);
		Leg leg = PopulationUtils.createLeg("car");
		leg.setRoutingMode("car");
		leg.setDepartureTime(100.0);
		leg.setTravelTime(50.0);
		NetworkRoute route = RouteUtils.createLinkNetworkRouteImpl(
				Id.createLinkId("from"), Id.createLinkId("to"));
		route.setLinkIds(
				Id.createLinkId("from"),
				List.of(Id.createLinkId("toll")),
				Id.createLinkId("to"));
		route.setDistance(1_000.0);
		route.setTravelTime(50.0);
		leg.setRoute(route);
		plan.addLeg(leg);
		Activity destination = PopulationUtils.createActivityFromCoord(
				destinationType, new Coord(1.0, 1.0));
		destination.setFacilityId(
				Id.create(facilityId, ActivityFacility.class));
		destination.setEndTime(500.0);
		plan.addActivity(destination);
		person.addPlan(plan);
		person.setSelectedPlan(plan);
		return person;
	}

	static HongKongCarParkingCostCatalog.ParkingQuote resolvedCharge(
			String personId,
			int legSequence,
			double costHkd) {
		return quote(
				personId, legSequence, "private_car", costHkd,
				"resolved_proxy_charge",
				HongKongCarParkingCostCatalog.Resolution.RESOLVED_CHARGE,
				"work", "");
	}

	static HongKongCarParkingCostCatalog.ParkingQuote legalHomeZero(
			String personId,
			int legSequence) {
		return quote(
				personId, legSequence, "private_car", 0.0,
				"resolved_home_marginal_zero_fixed_separate",
				HongKongCarParkingCostCatalog.Resolution.RESOLVED_LEGAL_ZERO,
				"home", "");
	}

	private static HongKongCarParkingCostCatalog.ParkingQuote unresolved(
			String personId,
			int legSequence,
			String status,
			String reason) {
		return quote(
				personId, legSequence, "private_car", null, status,
				HongKongCarParkingCostCatalog.Resolution.UNRESOLVED,
				"work", reason);
	}

	private static HongKongCarParkingCostCatalog.ParkingQuote motorcycle(
			String personId,
			int legSequence) {
		return quote(
				personId, legSequence, "motorcycle", null,
				"out_of_scope_motorcycle",
				HongKongCarParkingCostCatalog.Resolution.OUT_OF_SCOPE,
				"work", "vehicle_class_motorcycle");
	}

	private static HongKongCarParkingCostCatalog.ParkingQuote quote(
			String personId,
			int legSequence,
			String vehicleClass,
			Double costHkd,
			String status,
			HongKongCarParkingCostCatalog.Resolution resolution,
			String activityGroup,
			String unresolvedReason) {
		boolean unresolved = resolution
				== HongKongCarParkingCostCatalog.Resolution.UNRESOLVED;
		boolean outOfScope = resolution
				== HongKongCarParkingCostCatalog.Resolution.OUT_OF_SCOPE;
		String activityType = "home".equals(activityGroup) ? "home" : "work";
		String facility = "destination";
		return new HongKongCarParkingCostCatalog.ParkingQuote(
				personId, legSequence, "vehicle-" + personId, vehicleClass,
				"parking-" + personId, facility, 8, "kowloon_urban",
				activityType, activityGroup,
				100.0, 50.0, 150.0,
				personId, 1, "vehicle-" + personId, facility,
				500.0, 350.0,
				unresolved
				? "unresolved_chain" : "resolved_same_vehicle_same_facility_time_order",
				unresolved, unresolved, false, status,
				"home".equals(activityGroup)
				? "home_marginal_zero_residential_fixed_separate"
				: "hourly_or_part_by_arrival_clock",
				costHkd != null && costHkd > 0.0 ? 1 : 0,
				costHkd,
				"data/transport_costs/hongkong/car_cost_v1/"
						+ "parking_event_application_v1/"
						+ "parking_cost_rules_repository_relative.csv",
				"2026-03-01",
				(unresolved || outOfScope)
				? "unresolved" : "official_rate_bounded_zone_activity_proxy",
				"snapshot", CANDIDATE_PATH, CANDIDATE_SHA,
				1_000.0, false, resolution, unresolvedReason);
	}

	private record Fixture(
			Person person,
			Leg carLeg,
			HongKongCarParkingCostCatalog catalog) {
	}
}
