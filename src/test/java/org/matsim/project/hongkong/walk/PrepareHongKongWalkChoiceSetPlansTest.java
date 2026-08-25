package org.matsim.project.hongkong.walk;

import org.junit.jupiter.api.Test;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.project.hongkong.schoolbus.StudentSchoolModeCandidateCatalog;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class PrepareHongKongWalkChoiceSetPlansTest {

	@Test
	void protectsHouseholdAndStudentCatalogPeopleFromWalkAlternatives() throws Exception {
		Path root = Path.of("target", "test-data", "walk-choice-set-protected-people");
		Files.createDirectories(root);
		Path household = root.resolve("household.csv");
		Files.writeString(household, """
				candidate_id,household_id,passenger_person_id,passenger_trip_index,passenger_original_mode,driver_person_id,driver_trip_index,driver_original_mode,driver_vehicle_id,driver_requires_car_switch,passenger_departure_time_s,driver_departure_time_s,passenger_pickup_link,passenger_dropoff_link,driver_destination_link,origin_gap_m,destination_gap_m
				household-candidate,household,passenger,0,pt,driver,0,car,vehicle,false,27000,27000,pickup,dropoff,destination,10,20
				""");
		Path student = root.resolve("student");
		Files.createDirectories(student);
		Files.writeString(student.resolve(StudentSchoolModeCandidateCatalog.UNIVERSE_FILE), """
				person_id,trip_index,direction,student_stage,original_mode_audit_only,crowfly_distance_m
				student,0,inbound_am,primary,school_bus,1200
				student,1,outbound_pm,primary,school_bus,1200
				""");
		Files.writeString(student.resolve(StudentSchoolModeCandidateCatalog.SCHOOL_BUS_FILE), """
				candidate_id,person_id,trip_index,direction,route_id,transit_line_id,transit_route_id,departure_id,vehicle_id,boarding_facility_id,alighting_facility_id,boarding_link_id,alighting_link_id,scheduled_board_time_s,scheduled_alight_time_s,home_stop_distance_m,campus_stop_distance_m,vehicle_capacity
				student-candidate,student,0,inbound_am,route,line,transit-route,departure,school-bus,home-stop,school-stop,home-link,school-link,27000,28200,200,20,19
				""");

		var protectedPeople = PrepareHongKongWalkChoiceSetPlans.protectedPeople(
				ScenarioUtils.createScenario(ConfigUtils.createConfig()), household, student);

		assertEquals(3, protectedPeople.size());
		assertTrue(protectedPeople.contains("passenger"));
		assertTrue(protectedPeople.contains("driver"));
		assertTrue(protectedPeople.contains("student"));
	}
}
