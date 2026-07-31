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

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HongKongCarTollScoringTest {

	private static final String CANDIDATE_PATH =
			"data/transport_costs/hongkong/car_cost_v1/toll_rate_application_v1/"
					+ "car_leg_toll_cost_estimates_base.parquet";
	private static final String CANDIDATE_SHA =
			"7d70b7144c87805d3b3bce3db0dcaa9b87f20e5e4ee7ae1a5a155c3ff8eb2342";

	@Test
	void confirmedTollChargesExactlyOnceAndCallbacksAreInert() {
		Fixture fixture = fixture("charged", chargedQuote("charged", 0, 30.0));
		var scoring = new HongKongCarTollScoring(
				HongKongCarTollPersonSchedule.fromSelectedPlan(
						fixture.person, fixture.catalog),
				2.0);
		scoring.handleLeg(fixture.carLeg);
		assertEquals(-60.0, scoring.getScore(), 0.0);
		assertEquals(30.0, scoring.chargedTollHkd(), 0.0);
		assertEquals(1, scoring.confirmedChargeLegs());
		assertEquals(1, scoring.physicalPassageEvents());

		scoring.addMoney(-30.0);
		scoring.addScore(100.0);
		scoring.agentStuck(100.0);
		scoring.handleEvent(new Event(100.0) {
			@Override
			public String getEventType() {
				return "stage8b_duplicate_probe";
			}
		});
		scoring.handleTrip(TripStructureUtils.getTrips(
				fixture.person.getSelectedPlan()).getFirst());
		assertEquals(-60.0, scoring.getScore(), 0.0);
		assertThrows(IllegalStateException.class,
				() -> scoring.handleLeg(fixture.carLeg));
		scoring.finish();
		StringBuilder explanation = new StringBuilder();
		scoring.explainScore(explanation);
		assertTrue(explanation.toString().contains("distanceInferredCharges=0"));
		assertTrue(explanation.toString().contains("candidateFallbackCharges=0"));
		assertTrue(explanation.toString().contains("parkingCharges=0"));
		assertTrue(explanation.toString().contains("fixedOwnershipCharges=0"));
	}

	@Test
	void confirmedNoChargeIsLegalZeroNotUnresolvedFill() {
		Fixture fixture = fixture("no-charge", noChargeQuote("no-charge", 0));
		var scoring = new HongKongCarTollScoring(
				HongKongCarTollPersonSchedule.fromSelectedPlan(
						fixture.person, fixture.catalog), 1.0);
		scoring.handleLeg(fixture.carLeg);
		scoring.finish();
		assertEquals(0.0, scoring.getScore(), 0.0);
		assertEquals(1, scoring.confirmedNoChargeLegs());
		assertEquals(0, scoring.confirmedChargeLegs());
	}

	@Test
	void missingAndUnconfirmedTollFailClosedWithoutDistanceGuess() {
		Person missing = person("missing");
		assertThrows(IllegalStateException.class,
				() -> HongKongCarTollPersonSchedule.fromSelectedPlan(
						missing,
						HongKongCarTollCostCatalog.builder().buildForTests()));

		var unresolved = unresolvedQuote("unresolved", 0);
		Fixture fixture = fixture("unresolved", unresolved);
		IllegalStateException error = assertThrows(
				IllegalStateException.class,
				() -> HongKongCarTollPersonSchedule.fromSelectedPlan(
						fixture.person, fixture.catalog));
		assertTrue(error.getMessage().contains("unconfirmed or unresolved"));
	}

	@Test
	void facilityLinkAndFullRouteEvidenceMustMatch() {
		Fixture fixture = fixture("route-evidence",
				chargedQuote("route-evidence", 0, 30.0));
		NetworkRoute route = (NetworkRoute) fixture.carLeg.getRoute();
		route.setLinkIds(
				Id.createLinkId("from"),
				List.of(Id.createLinkId("not-toll")),
				Id.createLinkId("to"));
		IllegalStateException error = assertThrows(
				IllegalStateException.class,
				() -> HongKongCarTollPersonSchedule.fromSelectedPlan(
						fixture.person, fixture.catalog));
		assertTrue(error.getMessage().contains("facility links"));
	}

	@Test
	void confirmedFragmentedFacilityLinksMaySpanAuditedRouteGaps() {
		var passage = new HongKongCarTollCostCatalog.PassageEvidence(
				"fragmented", "western_harbour_crossing", 0, 2,
				List.of("from", "to"), 30.0,
				"rate-source", "rate-hash", "2026-07-17", "interval",
				"confirmed_charge", "official_rate");
		var quote = new HongKongCarTollCostCatalog.TollQuote(
				"fragmented", 0, "vehicle-fragmented", "private_car",
				30.0, "confirmed_charge",
				"official_PC_rates_estimated_passage_time_analyst_sensitivity",
				"official-toll-source", "snapshot", CANDIDATE_PATH,
				CANDIDATE_SHA, 1_000.0, 3, List.of(passage), false,
				HongKongCarTollCostCatalog.Resolution.CONFIRMED_CHARGE, "");
		Fixture fixture = fixture("fragmented", quote);
		var schedule = HongKongCarTollPersonSchedule.fromSelectedPlan(
				fixture.person, fixture.catalog);
		assertEquals(1, schedule.audit().confirmedChargeLegs());
		assertEquals(1, schedule.audit().physicalPassageEvents());
	}

	@Test
	void motorcycleRemainsOutOfScopeAndFixedOwnershipAbsent() {
		Fixture fixture = fixture(
				"motorcycle", motorcycleQuote("motorcycle", 0));
		var schedule = HongKongCarTollPersonSchedule.fromSelectedPlan(
				fixture.person, fixture.catalog);
		var scoring = new HongKongCarTollScoring(schedule, 1.0);
		scoring.handleLeg(fixture.carLeg);
		scoring.finish();
		assertEquals(0.0, scoring.getScore(), 0.0);
		assertEquals(1, scoring.motorcycleOutOfScopeLegs());
		assertEquals(0, schedule.audit().fixedOwnershipCharges());
		assertEquals(0, schedule.audit().parkingCharges());
	}

	@Test
	void invalidOrAmbiguousTollValuesAreRejected() {
		assertThrows(IllegalArgumentException.class,
				() -> new HongKongCarTollCostCatalog.TollQuote(
						"invalid", 0, "vehicle", "private_car",
						0.0, "confirmed_charge", "quality", "source",
						"snapshot", CANDIDATE_PATH, CANDIDATE_SHA,
						1_000.0, 3,
						List.of(passage(30.0)), false,
						HongKongCarTollCostCatalog.Resolution.CONFIRMED_CHARGE,
						""));
		assertThrows(IllegalStateException.class,
				() -> HongKongCarTollCostCatalog.builder()
						.quote(noChargeQuote("duplicate", 0))
						.quote(noChargeQuote("duplicate", 0)));
	}

	private static Fixture fixture(
			String id,
			HongKongCarTollCostCatalog.TollQuote quote) {
		Person person = person(id);
		Leg leg = (Leg) person.getSelectedPlan().getPlanElements().get(1);
		return new Fixture(
				person,
				leg,
				HongKongCarTollCostCatalog.builder()
						.quote(quote).buildForTests());
	}

	private static Person person(String id) {
		Person person = PopulationUtils.getFactory().createPerson(
				Id.createPersonId(id));
		Plan plan = PopulationUtils.createPlan(person);
		plan.addActivity(activity("home"));
		plan.addLeg(carLeg());
		plan.addActivity(activity("work"));
		person.addPlan(plan);
		person.setSelectedPlan(plan);
		return person;
	}

	private static Activity activity(String type) {
		return PopulationUtils.createActivityFromCoord(
				type, new Coord(0.0, 0.0));
	}

	private static Leg carLeg() {
		Leg leg = PopulationUtils.createLeg("car");
		leg.setRoutingMode("car");
		NetworkRoute route = RouteUtils.createLinkNetworkRouteImpl(
				Id.createLinkId("from"), Id.createLinkId("to"));
		route.setLinkIds(
				Id.createLinkId("from"),
				List.of(Id.createLinkId("toll")),
				Id.createLinkId("to"));
		route.setDistance(1_000.0);
		route.setTravelTime(100.0);
		leg.setRoute(route);
		return leg;
	}

	static HongKongCarTollCostCatalog.TollQuote chargedQuote(
			String personId, int legSequence, double costHkd) {
		return new HongKongCarTollCostCatalog.TollQuote(
				personId, legSequence, "vehicle-" + personId, "private_car",
				costHkd, "confirmed_charge",
				"official_PC_rates_estimated_passage_time_analyst_sensitivity",
				"official-toll-source", "snapshot", CANDIDATE_PATH,
				CANDIDATE_SHA, 1_000.0, 3, List.of(passage(costHkd)), false,
				HongKongCarTollCostCatalog.Resolution.CONFIRMED_CHARGE, "");
	}

	static HongKongCarTollCostCatalog.TollQuote noChargeQuote(
			String personId, int legSequence) {
		return new HongKongCarTollCostCatalog.TollQuote(
				personId, legSequence, "vehicle-" + personId, "private_car",
				0.0, "confirmed_no_charge",
				"confirmed_full_route_no_audited_toll_facility",
				"mapping", "snapshot", CANDIDATE_PATH, CANDIDATE_SHA,
				1_000.0, 3, List.of(), false,
				HongKongCarTollCostCatalog.Resolution.CONFIRMED_NO_CHARGE, "");
	}

	private static HongKongCarTollCostCatalog.TollQuote motorcycleQuote(
			String personId, int legSequence) {
		return new HongKongCarTollCostCatalog.TollQuote(
				personId, legSequence, "vehicle-" + personId, "motorcycle",
				null, "out_of_scope", "out_of_scope_motorcycle", "", "snapshot",
				CANDIDATE_PATH, CANDIDATE_SHA, 1_000.0, 3, List.of(), false,
				HongKongCarTollCostCatalog.Resolution.OUT_OF_SCOPE,
				"vehicle_class_motorcycle");
	}

	private static HongKongCarTollCostCatalog.TollQuote unresolvedQuote(
			String personId, int legSequence) {
		return new HongKongCarTollCostCatalog.TollQuote(
				personId, legSequence, "vehicle-" + personId, "private_car",
				null, "unconfirmed_ambiguous", "U", "", "snapshot",
				CANDIDATE_PATH, CANDIDATE_SHA, 1_000.0, 3, List.of(), false,
				HongKongCarTollCostCatalog.Resolution.UNRESOLVED,
				"ambiguous_toll_source");
	}

	private static HongKongCarTollCostCatalog.PassageEvidence passage(
			double costHkd) {
		return new HongKongCarTollCostCatalog.PassageEvidence(
				"event", "facility", 1, 1, List.of("toll"), costHkd,
				"rate-source", "rate-hash", "2026-07-17", "interval",
				"confirmed_charge", "official_rate");
	}

	private record Fixture(
			Person person,
			Leg carLeg,
			HongKongCarTollCostCatalog catalog) {
	}
}
