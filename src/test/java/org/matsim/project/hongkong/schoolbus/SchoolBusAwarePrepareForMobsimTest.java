package org.matsim.project.hongkong.schoolbus;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.router.TripStructureUtils;
import org.matsim.core.scenario.ScenarioUtils;

import static org.junit.jupiter.api.Assertions.assertEquals;

class SchoolBusAwarePrepareForMobsimTest {

	@Test
	void fillsRaptorPtLegRoutingModeFromItsAccessLegs() {
		Scenario scenario = ScenarioUtils.createScenario(ConfigUtils.createConfig());
		var person = PopulationUtils.getFactory().createPerson(
				org.matsim.api.core.v01.Id.createPersonId("person"));
		var plan = PopulationUtils.createPlan(person);
		plan.addActivity(PopulationUtils.createActivityFromCoord("home",
				new org.matsim.api.core.v01.Coord(0, 0)));
		var access = PopulationUtils.createLeg(TransportMode.walk);
		access.setRoutingMode(TransportMode.pt);
		plan.addLeg(access);
		plan.addActivity(PopulationUtils.createActivityFromCoord("pt interaction",
				new org.matsim.api.core.v01.Coord(1, 0)));
		var inVehicle = PopulationUtils.createLeg(TransportMode.pt);
		plan.addLeg(inVehicle);
		plan.addActivity(PopulationUtils.createActivityFromCoord("work",
				new org.matsim.api.core.v01.Coord(2, 0)));
		person.addPlan(plan);
		scenario.getPopulation().addPerson(person);

		assertEquals(1, SchoolBusAwarePrepareForMobsim
				.synchronizeMissingTripRoutingModes(scenario));
		assertEquals(TransportMode.pt, TripStructureUtils.getRoutingMode(inVehicle));
	}
}
