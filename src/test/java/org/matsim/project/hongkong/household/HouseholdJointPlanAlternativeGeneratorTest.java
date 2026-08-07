package org.matsim.project.hongkong.household;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.project.hongkong.taxi.HongKongTaxiLegAttributes;

import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertSame;

class HouseholdJointPlanAlternativeGeneratorTest {

	@Test
	void preservesBaselineAndAddsThreeRealUnbindModesPlusJointTemplates() {
		Scenario scenario = ScenarioUtils.createScenario(ConfigUtils.createConfig());
		Person passenger = personWithOneTrip(scenario, "passenger", "car_passenger");
		Person driver = personWithOneTrip(scenario, "driver", TransportMode.car);
		Plan passengerBaseline = passenger.getSelectedPlan();
		Plan driverBaseline = driver.getSelectedPlan();

		var candidate = new HouseholdJointPlanCandidateCatalog.Candidate(
				"joint-1", "hh-1", "passenger", 0, "car_passenger",
				"driver", 0, TransportMode.car, "vehicle-1", false,
				8 * 3_600.0, 8 * 3_600.0, "pickup", "dropoff", "driver-destination",
				0.0, 0.0);
		var catalog = HouseholdJointPlanCandidateCatalog.of(List.of(candidate));

		new HouseholdJointPlanAlternativeGenerator(catalog, scenario).generate();

		assertSame(passengerBaseline, passenger.getSelectedPlan());
		assertSame(driverBaseline, driver.getSelectedPlan());
		assertEquals(5, passenger.getPlans().size());
		assertEquals(2, driver.getPlans().size());
		Set<String> releaseModes = passenger.getPlans().stream()
				.filter(plan -> HouseholdJointPlanAlternativeGenerator.UNBIND_ROLE.equals(
						plan.getAttributes().getAttribute(HouseholdJointPlanAlternativeGenerator.ROLE_ATTRIBUTE)))
				.map(plan -> String.valueOf(plan.getAttributes().getAttribute(
						HouseholdJointPlanAlternativeGenerator.UNBIND_MODE_ATTRIBUTE)))
				.collect(Collectors.toSet());
		assertEquals(Set.of(TransportMode.pt, "taxi", TransportMode.walk), releaseModes);
		Plan taxiTemplate = passenger.getPlans().stream()
				.filter(plan -> "taxi".equals(plan.getAttributes().getAttribute(
						HouseholdJointPlanAlternativeGenerator.UNBIND_MODE_ATTRIBUTE)))
				.findFirst().orElseThrow();
		Leg taxiLeg = (Leg) taxiTemplate.getPlanElements().get(1);
		Activity taxiOrigin = (Activity) taxiTemplate.getPlanElements().getFirst();
		for (String attribute : HongKongTaxiLegAttributes.NAMES) {
			assertNotNull(taxiLeg.getAttributes().getAttribute(attribute));
			assertNotNull(taxiOrigin.getAttributes().getAttribute(attribute));
		}
		assertEquals(HouseholdJointPlanAlternativeGenerator.BASELINE_ROLE,
				passengerBaseline.getAttributes().getAttribute(
						HouseholdJointPlanAlternativeGenerator.ROLE_ATTRIBUTE));
	}

	private static Person personWithOneTrip(Scenario scenario, String id, String mode) {
		Person person = scenario.getPopulation().getFactory().createPerson(Id.createPersonId(id));
		Plan plan = scenario.getPopulation().getFactory().createPlan();
		Activity home = PopulationUtils.createActivityFromLinkId("home", Id.createLinkId(id + "-home"));
		home.setEndTime(8 * 3_600.0);
		Leg leg = PopulationUtils.createLeg(mode);
		leg.setRoutingMode(mode);
		Activity work = PopulationUtils.createActivityFromLinkId("work", Id.createLinkId(id + "-work"));
		plan.addActivity(home);
		plan.addLeg(leg);
		plan.addActivity(work);
		person.addPlan(plan);
		person.setSelectedPlan(plan);
		scenario.getPopulation().addPerson(person);
		return person;
	}
}
