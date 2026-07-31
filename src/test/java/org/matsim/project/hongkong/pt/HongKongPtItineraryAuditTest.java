package org.matsim.project.hongkong.pt;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.api.core.v01.events.PersonStuckEvent;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.api.core.v01.population.Route;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.pt.PtConstants;
import org.matsim.pt.routes.DefaultTransitPassengerRoute;
import org.matsim.pt.transitSchedule.api.Departure;
import org.matsim.pt.transitSchedule.api.TransitLine;
import org.matsim.pt.transitSchedule.api.TransitRoute;
import org.matsim.pt.transitSchedule.api.TransitRouteStop;
import org.matsim.pt.transitSchedule.api.TransitSchedule;
import org.matsim.pt.transitSchedule.api.TransitScheduleFactory;
import org.matsim.pt.transitSchedule.api.TransitStopFacility;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HongKongPtItineraryAuditTest {

	@Test
	void acceptsDeterministicLegalAccessPtEgressItineraryWithoutMutation() {
		Fixture fixture = fixture("legal", true, true, 120.0);
		int elementsBefore = fixture.person().getSelectedPlan()
				.getPlanElements().size();
		int departuresBefore = fixture.transitRoute().getDepartures().size();

		HongKongPtItineraryAudit.AuditResult first =
				HongKongPtItineraryAudit.audit(fixture.scenario());
		HongKongPtItineraryAudit.AuditResult second =
				HongKongPtItineraryAudit.audit(fixture.scenario());

		assertTrue(first.legal(), first.toMap().toString());
		assertEquals(1, first.ptPersons());
		assertEquals(1, first.ptMainTrips());
		assertEquals(1, first.validPtMainTrips());
		assertEquals(0, first.invalidPtMainTrips());
		assertEquals(1, first.ptLegs());
		assertEquals(2, first.ptWalkLegs());
		assertEquals(0, first.transferWalkLegs());
		assertEquals(2, first.ptStageActivities());
		assertEquals(Map.of(), first.reasonCounts());
		assertEquals(first.fingerprintSha256(), second.fingerprintSha256());
		assertEquals(elementsBefore, fixture.person().getSelectedPlan()
				.getPlanElements().size());
		assertEquals(departuresBefore,
				fixture.transitRoute().getDepartures().size());
		assertDoesNotThrow(() -> HongKongPtItineraryAudit.requireLegal(first));

		assertEquals(
				"PT_STUCK_LEGAL_ITINERARY_RUNTIME_CAUSE_UNRESOLVED",
				first.classifyStuck(stuck(fixture.person(), TransportMode.pt)));
		assertEquals(
				"PT_WALK_STUCK_LEGAL_ITINERARY_RUNTIME_CAUSE_UNRESOLVED",
				first.classifyStuck(stuck(fixture.person(), TransportMode.walk)));
		assertEquals(
				"STUCK_OUTSIDE_PT_WALK_SCOPE",
				first.classifyStuck(stuck(fixture.person(), TransportMode.car)));
		assertEquals(false, first.toMap().get("plans_mutated"));
		assertEquals(false, first.toMap().get("fare_or_scoring_used"));
	}

	@Test
	void rejectsWrongStopOrderBoardingAndUnavailableServiceFailClosed() {
		Fixture fixture = fixture("invalid-service", false, false, 90.0);
		TransitLine line = fixture.scenario().getTransitSchedule()
				.getTransitLines().get(
						Id.create("line", TransitLine.class));
		DefaultTransitPassengerRoute passengerRoute =
				new DefaultTransitPassengerRoute(
						fixture.egress(),
						line,
						fixture.transitRoute(),
						fixture.access());
		passengerRoute.setDistance(1_000.0);
		passengerRoute.setTravelTime(300.0);
		ptLeg(fixture.person()).setRoute(passengerRoute);
		fixture.transitRoute().getStops().get(1).setAllowBoarding(false);
		((Leg) fixture.person().getSelectedPlan().getPlanElements().get(1))
				.getRoute().setTravelTime(400.0);
		ptLeg(fixture.person()).setDepartureTime(500.0);

		HongKongPtItineraryAudit.AuditResult result =
				HongKongPtItineraryAudit.audit(fixture.scenario());

		assertFalse(result.legal());
		assertEquals(1, result.invalidPtMainTrips());
		assertEquals(1L,
				result.reasonCounts().get("PT_STOP_ORDER_INVALID"));
		assertEquals(1L,
				result.reasonCounts().get("PT_ACCESS_BOARDING_FORBIDDEN"));
		assertEquals(1L,
				result.reasonCounts().get(
						"PT_NO_SERVICE_AT_OR_AFTER_READY_TIME"));
		assertThrows(IllegalStateException.class,
				() -> HongKongPtItineraryAudit.requireLegal(result));
		assertTrue(result.classifyStuck(
						stuck(fixture.person(), TransportMode.pt))
				.startsWith("PT_STUCK_INVALID_ITINERARY__"));
	}

	@Test
	void rejectsWalkDiscontinuityMissingLinksAndNonFiniteValues() {
		Fixture fixture = fixture("invalid-walk", true, true, 120.0);
		Plan plan = fixture.person().getSelectedPlan();
		Leg accessWalk = (Leg) plan.getPlanElements().get(1);
		accessWalk.getRoute().setEndLinkId(Id.createLinkId("wrong-stop-link"));
		accessWalk.getRoute().setDistance(Double.NaN);
		Activity accessInteraction =
				(Activity) plan.getPlanElements().get(2);
		accessInteraction.setLinkId(null);

		HongKongPtItineraryAudit.AuditResult result =
				HongKongPtItineraryAudit.audit(fixture.scenario());

		assertFalse(result.legal());
		assertEquals(1L,
				result.reasonCounts().get("LEG_ROUTE_DISTANCE_INVALID"));
		assertEquals(1L,
				result.reasonCounts().get("WALK_END_LINK_UNRESOLVED"));
		assertEquals(1L,
				result.reasonCounts().get("PT_START_LINK_UNRESOLVED"));
		assertEquals(1L,
				result.reasonCounts().get("PT_ACCESS_LINK_UNRESOLVED"));
		assertEquals(
				"PT_WALK_STUCK_INVALID_ITINERARY__LEG_ROUTE_DISTANCE_INVALID",
				result.classifyStuck(
						stuck(fixture.person(), TransportMode.walk)));
	}

	@Test
	void validatesExplicitTransferWalkContinuityBetweenPtSegments() {
		Fixture fixture = fixture("transfer", true, true, 120.0);
		TransitSchedule schedule = fixture.scenario().getTransitSchedule();
		TransitScheduleFactory factory = schedule.getFactory();
		TransitStopFacility transferAccess = stop(
				factory,
				"transfer-access-stop",
				Id.createLinkId("transfer-access-link"),
				2.0);
		TransitStopFacility finalEgress = stop(
				factory,
				"final-egress-stop",
				Id.createLinkId("final-egress-link"),
				3.0);
		schedule.addStopFacility(transferAccess);
		schedule.addStopFacility(finalEgress);
		TransitRouteStop transferAccessRouteStop =
				factory.createTransitRouteStop(transferAccess, 0.0, 0.0);
		TransitRouteStop finalEgressRouteStop =
				factory.createTransitRouteStop(finalEgress, 200.0, 200.0);
		TransitRoute secondTransitRoute = factory.createTransitRoute(
				Id.create("route-2", TransitRoute.class),
				RouteUtils.createLinkNetworkRouteImpl(
						transferAccess.getLinkId(),
						finalEgress.getLinkId()),
				java.util.List.of(
						transferAccessRouteStop, finalEgressRouteStop),
				TransportMode.pt);
		secondTransitRoute.addDeparture(factory.createDeparture(
				Id.create("departure-2", Departure.class), 500.0));
		TransitLine secondLine = factory.createTransitLine(
				Id.create("line-2", TransitLine.class));
		secondLine.addRoute(secondTransitRoute);
		schedule.addTransitLine(secondLine);

		Person person = fixture.person();
		Plan plan = PopulationUtils.createPlan(person);
		Activity origin = activity("home", "origin-link");
		origin.setEndTime(100.0);
		plan.addActivity(origin);
		Leg accessWalk = walkLeg(
				"origin-link", "access-link", 10.0);
		accessWalk.setDepartureTime(100.0);
		plan.addLeg(accessWalk);
		plan.addActivity(activity(
				PtConstants.TRANSIT_ACTIVITY_TYPE, "access-link"));
		plan.addLeg(passengerLeg(
				fixture.access(),
				schedule.getTransitLines().get(
						Id.create("line", TransitLine.class)),
				fixture.transitRoute(),
				fixture.egress(),
				110.0,
				300.0));
		plan.addActivity(activity(
				PtConstants.TRANSIT_ACTIVITY_TYPE, "egress-link"));
		Leg transferWalk = walkLeg(
				"egress-link", "transfer-access-link", 20.0);
		transferWalk.setDepartureTime(410.0);
		plan.addLeg(transferWalk);
		plan.addActivity(activity(
				PtConstants.TRANSIT_ACTIVITY_TYPE,
				"transfer-access-link"));
		plan.addLeg(passengerLeg(
				transferAccess,
				secondLine,
				secondTransitRoute,
				finalEgress,
				430.0,
				200.0));
		plan.addActivity(activity(
				PtConstants.TRANSIT_ACTIVITY_TYPE,
				"final-egress-link"));
		Leg egressWalk = walkLeg(
				"final-egress-link", "destination-link", 20.0);
		egressWalk.setDepartureTime(630.0);
		plan.addLeg(egressWalk);
		plan.addActivity(activity("work", "destination-link"));
		person.addPlan(plan);
		person.setSelectedPlan(plan);

		HongKongPtItineraryAudit.AuditResult legal =
				HongKongPtItineraryAudit.audit(fixture.scenario());
		assertTrue(legal.legal(), legal.toMap().toString());
		assertEquals(2, legal.ptLegs());
		assertEquals(3, legal.ptWalkLegs());
		assertEquals(1, legal.transferWalkLegs());
		assertEquals(4, legal.ptStageActivities());

		transferWalk.getRoute().setEndLinkId(
				Id.createLinkId("wrong-transfer-link"));
		HongKongPtItineraryAudit.AuditResult invalid =
				HongKongPtItineraryAudit.audit(fixture.scenario());
		assertEquals(1L,
				invalid.reasonCounts().get(
						"WALK_END_LINK_DISCONTINUITY"));
	}

	@Test
	void separatesNonPtWalkStuckFromAuditedPtWalkScope() {
		Scenario scenario = ScenarioUtils.createScenario(
				ConfigUtils.createConfig());
		Person person = PopulationUtils.getFactory()
				.createPerson(Id.createPersonId("walk-only"));
		Plan plan = PopulationUtils.createPlan(person);
		Activity origin = activity("home", "walk-origin");
		origin.setEndTime(100.0);
		plan.addActivity(origin);
		Leg walkOnly = walkLeg(
				"walk-origin", "walk-destination", 30.0);
		walkOnly.setRoutingMode(TransportMode.walk);
		plan.addLeg(walkOnly);
		plan.addActivity(activity("work", "walk-destination"));
		person.addPlan(plan);
		person.setSelectedPlan(plan);
		scenario.getPopulation().addPerson(person);

		HongKongPtItineraryAudit.AuditResult result =
				HongKongPtItineraryAudit.audit(scenario);

		assertEquals(0, result.ptMainTrips());
		assertEquals(
				"WALK_STUCK_OUTSIDE_PT_ITINERARY_SCOPE",
				result.classifyStuck(stuck(person, TransportMode.walk)));
		assertThrows(IllegalStateException.class,
				() -> HongKongPtItineraryAudit.requireLegal(result));
	}

	private static Fixture fixture(
			String personId,
			boolean boardingAllowed,
			boolean alightingAllowed,
			double departureTime) {
		Scenario scenario = ScenarioUtils.createScenario(
				ConfigUtils.createConfig());
		TransitSchedule schedule = scenario.getTransitSchedule();
		TransitScheduleFactory factory = schedule.getFactory();
		Id<Link> accessLink = Id.createLinkId("access-link");
		Id<Link> egressLink = Id.createLinkId("egress-link");
		TransitStopFacility access = stop(
				factory, "access-stop", accessLink, 0.0);
		TransitStopFacility egress = stop(
				factory, "egress-stop", egressLink, 1.0);
		schedule.addStopFacility(access);
		schedule.addStopFacility(egress);

		TransitRouteStop accessRouteStop =
				factory.createTransitRouteStop(access, 0.0, 0.0);
		accessRouteStop.setAllowBoarding(boardingAllowed);
		accessRouteStop.setAllowAlighting(true);
		TransitRouteStop egressRouteStop =
				factory.createTransitRouteStop(egress, 300.0, 300.0);
		egressRouteStop.setAllowBoarding(true);
		egressRouteStop.setAllowAlighting(alightingAllowed);
		TransitRoute transitRoute = factory.createTransitRoute(
				Id.create("route", TransitRoute.class),
				RouteUtils.createLinkNetworkRouteImpl(
						accessLink, egressLink),
				java.util.List.of(accessRouteStop, egressRouteStop),
				TransportMode.pt);
		Departure departure = factory.createDeparture(
				Id.create("departure", Departure.class), departureTime);
		transitRoute.addDeparture(departure);
		TransitLine line = factory.createTransitLine(
				Id.create("line", TransitLine.class));
		line.addRoute(transitRoute);
		schedule.addTransitLine(line);

		Person person = PopulationUtils.getFactory()
				.createPerson(Id.createPersonId(personId));
		Plan plan = PopulationUtils.createPlan(person);
		Activity origin = activity("home", "origin-link");
		origin.setEndTime(100.0);
		plan.addActivity(origin);
		Leg accessWalk = walkLeg(
				"origin-link", "access-link", 10.0);
		accessWalk.setDepartureTime(100.0);
		plan.addLeg(accessWalk);
		plan.addActivity(activity(
				PtConstants.TRANSIT_ACTIVITY_TYPE, "access-link"));
		Leg pt = PopulationUtils.createLeg(TransportMode.pt);
		pt.setRoutingMode(TransportMode.pt);
		DefaultTransitPassengerRoute passengerRoute =
				new DefaultTransitPassengerRoute(
						access, line, transitRoute, egress);
		passengerRoute.setDistance(1_000.0);
		passengerRoute.setTravelTime(300.0);
		pt.setRoute(passengerRoute);
		pt.setDepartureTime(110.0);
		plan.addLeg(pt);
		plan.addActivity(activity(
				PtConstants.TRANSIT_ACTIVITY_TYPE, "egress-link"));
		Leg egressWalk = walkLeg(
				"egress-link", "destination-link", 20.0);
		egressWalk.setDepartureTime(410.0);
		plan.addLeg(egressWalk);
		plan.addActivity(activity("work", "destination-link"));
		person.addPlan(plan);
		person.setSelectedPlan(plan);
		scenario.getPopulation().addPerson(person);
		return new Fixture(
				scenario, person, access, egress, transitRoute);
	}

	private static TransitStopFacility stop(
			TransitScheduleFactory factory,
			String id,
			Id<Link> link,
			double coordinate) {
		TransitStopFacility stop = factory.createTransitStopFacility(
				Id.create(id, TransitStopFacility.class),
				new Coord(coordinate, coordinate),
				false);
		stop.setLinkId(link);
		return stop;
	}

	private static Activity activity(String type, String link) {
		return PopulationUtils.createActivityFromCoordAndLinkId(
				type, new Coord(0.0, 0.0), Id.createLinkId(link));
	}

	private static Leg walkLeg(String start, String end, double travelTime) {
		Leg leg = PopulationUtils.createLeg(TransportMode.walk);
		leg.setRoutingMode(TransportMode.pt);
		Route route = RouteUtils.createGenericRouteImpl(
				Id.createLinkId(start), Id.createLinkId(end));
		route.setDistance(100.0);
		route.setTravelTime(travelTime);
		leg.setRoute(route);
		return leg;
	}

	private static Leg passengerLeg(
			TransitStopFacility access,
			TransitLine line,
			TransitRoute transitRoute,
			TransitStopFacility egress,
			double departureTime,
			double travelTime) {
		Leg pt = PopulationUtils.createLeg(TransportMode.pt);
		pt.setRoutingMode(TransportMode.pt);
		pt.setDepartureTime(departureTime);
		DefaultTransitPassengerRoute passengerRoute =
				new DefaultTransitPassengerRoute(
						access, line, transitRoute, egress);
		passengerRoute.setDistance(1_000.0);
		passengerRoute.setTravelTime(travelTime);
		pt.setRoute(passengerRoute);
		return pt;
	}

	private static Leg ptLeg(Person person) {
		return (Leg) person.getSelectedPlan().getPlanElements().get(3);
	}

	private static PersonStuckEvent stuck(Person person, String mode) {
		return new PersonStuckEvent(
				1_000.0,
				person.getId(),
				Id.createLinkId("stuck-link"),
				mode,
				"fixture");
	}

	private record Fixture(
			Scenario scenario,
			Person person,
			TransitStopFacility access,
			TransitStopFacility egress,
			TransitRoute transitRoute) {
	}
}
