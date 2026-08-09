package org.matsim.project.hongkong.schoolbus;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.router.TripStructureUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.pt.transitSchedule.api.TransitStopFacility;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class StudentSchoolModeCandidateCatalogTest {

	@Test
	void loadsUniverseAndPhysicalOptionsWithoutApplyingSeatCapacity() throws Exception {
		Path directory = Path.of("target", "test-data", "student-school-mode-catalog");
		Files.createDirectories(directory);
		Files.writeString(directory.resolve(StudentSchoolModeCandidateCatalog.UNIVERSE_FILE), """
				person_id,trip_index,direction,student_stage,original_mode_audit_only,crowfly_distance_m
				student,0,inbound_am,primary,pt,1200
				student,1,outbound_pm,primary,taxi,6200
				""");
		Files.writeString(directory.resolve(StudentSchoolModeCandidateCatalog.SCHOOL_BUS_FILE), """
				candidate_id,person_id,trip_index,direction,route_id,transit_line_id,transit_route_id,departure_id,vehicle_id,boarding_facility_id,alighting_facility_id,boarding_link_id,alighting_link_id,scheduled_board_time_s,scheduled_alight_time_s,home_stop_distance_m,campus_stop_distance_m,vehicle_capacity
				candidate-a,student,0,inbound_am,route,line,transit-route,departure,vehicle,home-stop,school-stop,home-link,school-link,27000,28200,200,20,19
				""");

		StudentSchoolModeCandidateCatalog catalog = StudentSchoolModeCandidateCatalog.load(directory);

		assertTrue(catalog.enabled());
		assertEquals(2, catalog.trips().size());
		assertEquals(1, catalog.physicalSchoolBusOptionCount());
		assertTrue(catalog.trips().get(
				new StudentSchoolModeCandidateCatalog.TripKey("student", 0)).walkAvailable());
		assertFalse(catalog.trips().get(
				new StudentSchoolModeCandidateCatalog.TripKey("student", 1)).walkAvailable());
		assertEquals("candidate-a", catalog.trips().get(
				new StudentSchoolModeCandidateCatalog.TripKey("student", 0))
				.schoolBusOptions().getFirst().candidateId());
		assertTrue(catalog.isPhysicalSchoolBusStop(
				Id.create("home-stop", TransitStopFacility.class)));
		assertFalse(catalog.isPhysicalSchoolBusStop(
				Id.create("ordinary-stop", TransitStopFacility.class)));
	}

	@Test
	void restoresOnlySchoolBusTripAndKeepsOtherPreparedRoutes() throws Exception {
		Path directory = Path.of("target", "test-data", "student-school-mode-trip-snapshot");
		Files.createDirectories(directory);
		Files.writeString(directory.resolve(StudentSchoolModeCandidateCatalog.UNIVERSE_FILE), """
				person_id,trip_index,direction,student_stage,original_mode_audit_only,crowfly_distance_m
				student,0,inbound_am,primary,pt,1200
				""");
		Files.writeString(directory.resolve(StudentSchoolModeCandidateCatalog.SCHOOL_BUS_FILE), """
				candidate_id,person_id,trip_index,direction,route_id,transit_line_id,transit_route_id,departure_id,vehicle_id,boarding_facility_id,alighting_facility_id,boarding_link_id,alighting_link_id,scheduled_board_time_s,scheduled_alight_time_s,home_stop_distance_m,campus_stop_distance_m,vehicle_capacity
				candidate-a,student,0,inbound_am,route,line,transit-route,departure,vehicle,home-stop,school-stop,home-link,school-link,27000,28200,200,20,19
				""");
		StudentSchoolModeCandidateCatalog catalog = StudentSchoolModeCandidateCatalog.load(directory);
		Scenario scenario = ScenarioUtils.createScenario(ConfigUtils.createConfig());
		Person person = scenario.getPopulation().getFactory().createPerson(Id.createPersonId("student"));
		Plan plan = scenario.getPopulation().getFactory().createPlan();
		plan.addActivity(PopulationUtils.createActivityFromLinkId("home", Id.createLinkId("home-link")));
		Leg schoolBus = PopulationUtils.createLeg("pt");
		TripStructureUtils.setRoutingMode(schoolBus, "school_bus");
		schoolBus.getAttributes().putAttribute("hkSchoolBusCandidateId", "candidate-a");
		schoolBus.setDepartureTime(27_000.0);
		schoolBus.setRoute(RouteUtils.createGenericRouteImpl(
				Id.createLinkId("school-bus-start"), Id.createLinkId("school-bus-end")));
		plan.addLeg(schoolBus);
		plan.addActivity(PopulationUtils.createActivityFromLinkId("school", Id.createLinkId("school-link")));
		Leg ordinaryPt = PopulationUtils.createLeg("pt");
		TripStructureUtils.setRoutingMode(ordinaryPt, "pt");
		ordinaryPt.setRoute(RouteUtils.createGenericRouteImpl(
				Id.createLinkId("ordinary-start"), Id.createLinkId("ordinary-end")));
		plan.addLeg(ordinaryPt);
		plan.addActivity(PopulationUtils.createActivityFromLinkId("home", Id.createLinkId("home-link")));
		person.addPlan(plan);
		person.setSelectedPlan(plan);
		scenario.getPopulation().addPerson(person);

		catalog.snapshotSelectedSchoolBusPlans(scenario);
		assertTrue(catalog.matchesSelectedSchoolBusDeparture(
				person.getId(), Id.createLinkId("school-bus-start"), 27_000.0));
		assertFalse(catalog.matchesSelectedSchoolBusDeparture(
				person.getId(), Id.createLinkId("ordinary-start"), 27_000.0));
		schoolBus.setRoute(RouteUtils.createGenericRouteImpl(
				Id.createLinkId("rerouted-school-bus"), Id.createLinkId("rerouted-school")));
		ordinaryPt.setRoute(RouteUtils.createGenericRouteImpl(
				Id.createLinkId("prepared-pt-start"), Id.createLinkId("prepared-pt-end")));
		assertEquals(1, catalog.restoreSelectedSchoolBusPlans(scenario));

		var trips = TripStructureUtils.getTrips(plan);
		assertEquals(Id.createLinkId("school-bus-start"),
				trips.get(0).getLegsOnly().getFirst().getRoute().getStartLinkId());
		assertEquals("candidate-a", trips.get(0).getLegsOnly().getFirst()
				.getAttributes().getAttribute("hkSchoolBusCandidateId"));
		assertEquals(Id.createLinkId("prepared-pt-start"),
				trips.get(1).getLegsOnly().getFirst().getRoute().getStartLinkId());
	}
}
