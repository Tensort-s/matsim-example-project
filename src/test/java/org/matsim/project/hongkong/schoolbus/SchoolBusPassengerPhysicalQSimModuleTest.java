package org.matsim.project.hongkong.schoolbus;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Id;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.mobsim.qsim.components.QSimComponentsConfigGroup;
import org.matsim.core.mobsim.qsim.qnetsimengine.QNetsimEngineModule;
import org.matsim.core.scenario.ScenarioUtils;

import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;

class SchoolBusPassengerPhysicalQSimModuleTest {

	@Test
	void activatesBeforeTheConfiguredNetworkComponent() {
		Config config = ConfigUtils.createConfig();
		QSimComponentsConfigGroup components = ConfigUtils.addOrGetModule(
				config, QSimComponentsConfigGroup.class);

		SchoolBusPassengerPhysicalQSimModule.activateInConfig(config);

		int network = components.getActiveComponents().indexOf(
				QNetsimEngineModule.COMPONENT_NAME);
		assertEquals(SchoolBusPassengerPhysicalQSimModule.COMPONENT_NAME,
				components.getActiveComponents().get(network - 1));
	}

	@Test
	void normalizesLegacyTransitPassengerModeBeforeAgentsAreCreated() {
		Config config = ConfigUtils.createConfig();
		config.transit().setTransitModes(Set.of("school_bus"));
		var scenario = ScenarioUtils.createScenario(config);
		var person = scenario.getPopulation().getFactory().createPerson(Id.createPersonId("student"));
		var plan = scenario.getPopulation().getFactory().createPlan();
		plan.addActivity(PopulationUtils.createActivityFromLinkId("home", Id.createLinkId("a")));
		plan.addLeg(PopulationUtils.createLeg("school_bus"));
		plan.addActivity(PopulationUtils.createActivityFromLinkId("school", Id.createLinkId("b")));
		person.addPlan(plan);
		person.setSelectedPlan(plan);
		scenario.getPopulation().addPerson(person);

		assertEquals(1, SchoolBusPassengerPhysicalEngine
				.normalizeGenericPassengerTransitModes(scenario));
		assertEquals("pt", ((org.matsim.api.core.v01.population.Leg)
				plan.getPlanElements().get(1)).getMode());
	}
}
