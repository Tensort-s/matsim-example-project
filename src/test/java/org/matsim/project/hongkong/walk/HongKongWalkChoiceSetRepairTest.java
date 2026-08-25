package org.matsim.project.hongkong.walk;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.router.TripStructureUtils;

import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HongKongWalkChoiceSetRepairTest {

	@Test
	void repairsCompleteProtectedHomeTourAtomically() {
		Person person = person("protected", "walk", "walk");
		var result = HongKongWalkChoiceSetRepair.repair(
				List.of(person), Set.of("protected"),
				assessment(2_100.0, 500.0),
				provider(2_100.0, 500.0, true), 4);

		assertEquals(1, result.protectedToursRepaired());
		assertEquals(0, result.unresolvedLongWalkTrips());
		assertEquals(List.of("pt", "pt"), mainModes(person.getSelectedPlan()));
		assertEquals(1, person.getPlans().size(), "protected plans must remain frozen");
		assertTrue(result.rows().stream().allMatch(row ->
				"protected_tour_walk_to_pt".equals(row.action())));
	}

	@Test
	void rollsBackProtectedTourWhenAnyPtReplacementIsUnavailable() {
		Person person = person("protected", "walk", "walk");
		var result = HongKongWalkChoiceSetRepair.repair(
				List.of(person), Set.of("protected"),
				assessment(2_100.0, 500.0),
				provider(2_100.0, 500.0, false), 4);

		assertEquals(0, result.protectedToursRepaired());
		assertEquals(1, result.unresolvedLongWalkTrips());
		assertEquals(List.of("walk", "walk"), mainModes(person.getSelectedPlan()));
	}

	@Test
	void replacesOrdinaryLongWalkAndAddsRoutedShortAlternative() {
		Person person = person("ordinary", "walk", "pt");
		var result = HongKongWalkChoiceSetRepair.repair(
				List.of(person), Set.of(),
				assessment(2_100.0, 600.0),
				provider(2_100.0, 600.0, true), 4);

		assertEquals(1, result.ordinaryTripsRepaired());
		assertEquals(1, result.shortWalkAlternativesAdded());
		assertEquals(List.of("pt", "pt"), mainModes(person.getSelectedPlan()));
		assertEquals(2, person.getPlans().size());
		Plan alternative = person.getPlans().stream()
				.filter(plan -> plan != person.getSelectedPlan()).findFirst().orElseThrow();
		assertEquals(List.of("pt", "walk"), mainModes(alternative));
		assertEquals("trip_1", alternative.getAttributes().getAttribute(
				HongKongWalkChoiceSetRepair.ALTERNATIVE_ATTRIBUTE));
	}

	private static HongKongWalkChoiceSetRepair.RouteProvider provider(
			double outboundWalkS, double inboundWalkS, boolean ptAvailable) {
		return (mode, person, origin, destination, departure) -> {
			if (TransportMode.pt.equals(mode) && !ptAvailable) return List.of();
			double time = TransportMode.pt.equals(mode)
					? 900.0 : "home".equals(origin.getType()) ? outboundWalkS : inboundWalkS;
			return routedLeg(mode, time);
		};
	}

	private static HongKongWalkChoiceSetRepair.WalkAssessmentProvider assessment(
			double outboundWalkS, double inboundWalkS) {
		return (person, origin, destination, departure, selectedMode) -> {
			double time = "home".equals(origin.getType()) ? outboundWalkS : inboundWalkS;
			return HongKongWalkChoiceSetRepair.WalkAssessment.routed(
					time, time * HongKongPhysicalWalkModule.WALK_SPEED_M_S);
		};
	}

	private static List<? extends PlanElement> routedLeg(String mode, double timeS) {
		Leg leg = PopulationUtils.createLeg(mode);
		leg.setRoutingMode(mode);
		leg.setTravelTime(timeS);
		var route = RouteUtils.createGenericRouteImpl(
				Id.createLinkId("from"), Id.createLinkId("to"));
		route.setTravelTime(timeS);
		route.setDistance(timeS * HongKongPhysicalWalkModule.WALK_SPEED_M_S);
		leg.setRoute(route);
		return List.of(leg);
	}

	private static Person person(String id, String outboundMode, String inboundMode) {
		Person person = PopulationUtils.getFactory().createPerson(Id.createPersonId(id));
		Plan plan = PopulationUtils.createPlan(person);
		Activity home = PopulationUtils.createActivityFromLinkId("home", Id.createLinkId("home"));
		home.setEndTime(8 * 3_600.0);
		plan.addActivity(home);
		plan.addLeg((Leg) routedLeg(outboundMode, 300.0).getFirst());
		Activity work = PopulationUtils.createActivityFromLinkId("work", Id.createLinkId("work"));
		work.setEndTime(17 * 3_600.0);
		plan.addActivity(work);
		plan.addLeg((Leg) routedLeg(inboundMode, 300.0).getFirst());
		plan.addActivity(PopulationUtils.createActivityFromLinkId("home", Id.createLinkId("home")));
		person.addPlan(plan);
		person.setSelectedPlan(plan);
		return person;
	}

	private static List<String> mainModes(Plan plan) {
		return TripStructureUtils.getTrips(plan).stream()
				.map(trip -> TripStructureUtils.getRoutingModeIdentifier()
						.identifyMainMode(trip.getTripElements()))
				.toList();
	}
}
