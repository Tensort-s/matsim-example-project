package org.matsim.project.hongkong.taxi;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Id;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.config.ConfigUtils;

import static org.junit.jupiter.api.Assertions.assertEquals;

class HongKongTaxiFareUtilityPolicyTest {
	@Test
	void distinguishesStudentsFromAdultsUsingStableRoleAttribute() {
		var policy = HongKongTaxiFareUtilityPolicy.openInnovationV1();
		var factory = PopulationUtils.createPopulation(ConfigUtils.createConfig()).getFactory();
		var adult = factory.createPerson(Id.createPersonId("adult"));
		adult.getAttributes().putAttribute("role", "fixed_worker");
		var student = factory.createPerson(Id.createPersonId("student"));
		student.getAttributes().putAttribute("role", "day_school_student");
		assertEquals(-10.0, policy.parametersFor(adult).fareScore(100.0));
		assertEquals(-15.0, policy.parametersFor(student).fareScore(100.0));
	}

	@Test
	void historicalPolicyRetainsCentralCoefficientForEveryone() {
		var person = PopulationUtils.createPopulation(ConfigUtils.createConfig()).getFactory()
				.createPerson(Id.createPersonId("student"));
		person.getAttributes().putAttribute("role", "tertiary_student");
		assertEquals(-5.0, HongKongTaxiFareUtilityPolicy.historicalCentralV1()
				.parametersFor(person).fareScore(100.0));
	}
}
