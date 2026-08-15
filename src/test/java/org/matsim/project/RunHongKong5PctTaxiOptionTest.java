package org.matsim.project;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.facilities.ActivityFacility;

import java.util.Set;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.ScoringConfigGroup;
import org.matsim.core.config.groups.RoutingConfigGroup;
import org.matsim.contrib.taxi.run.MultiModeTaxiConfigGroup;
import org.matsim.contrib.taxi.optimizer.rules.RuleBasedTaxiOptimizerParams;
import org.matsim.contrib.taxi.optimizer.rules.RuleBasedRequestInserter;

import static org.junit.jupiter.api.Assertions.*;

class RunHongKong5PctTaxiOptionTest {
	@Test
	void restoresEmptyHomeOnlyPlanWithoutCreatingTrips() {
		var scenario = ScenarioUtils.createScenario(ConfigUtils.createConfig());
		var person = PopulationUtils.getFactory().createPerson(Id.createPersonId("p-home"));
		person.getAttributes().putAttribute("householdId", "hh-home");
		var plan = PopulationUtils.createPlan(person);
		person.addPlan(plan);
		person.setSelectedPlan(plan);
		scenario.getPopulation().addPerson(person);
		Id<ActivityFacility> facilityId = Id.create("home_hh-home", ActivityFacility.class);
		var facility = scenario.getActivityFacilities().getFactory()
				.createActivityFacility(
						facilityId, new Coord(10, 20), Id.createLinkId("home-link"));
		scenario.getActivityFacilities().addActivityFacility(facility);

		assertEquals(1, RunHongKong5Pct.normalizeEmptyHomeOnlyPlans(scenario));
		assertEquals(1, plan.getPlanElements().size());
		var home = assertInstanceOf(Activity.class, plan.getPlanElements().getFirst());
		assertEquals("home", home.getType());
		assertEquals(facilityId, home.getFacilityId());
		assertEquals(Id.createLinkId("home-link"), home.getLinkId());
		assertEquals(0, RunHongKong5Pct.normalizeEmptyHomeOnlyPlans(scenario));
	}

	@Test
	void acceptsFourStrictProtectedSelectionIterations() {
		assertEquals(Set.of(5, 15, 25, 35),
				RunHongKong5Pct.parseStrictIterationSchedule("5,15,25,35", 49));
	}

	@Test
	void rejectsDuplicateUnsortedAndOutOfRangeIterations() {
		assertThrows(IllegalArgumentException.class,
				() -> RunHongKong5Pct.parseStrictIterationSchedule("5,15,15,35", 49));
		assertThrows(IllegalArgumentException.class,
				() -> RunHongKong5Pct.parseStrictIterationSchedule("15,5,25,35", 49));
		assertThrows(IllegalArgumentException.class,
				() -> RunHongKong5Pct.parseStrictIterationSchedule("5,15,25,50", 49));
	}

	@Test
	void physicalTaxiSanitizesNetworkProxyAndUsesApprovedOptimizer() {
		var config = ConfigUtils.createConfig();
		var taxiScore = new ScoringConfigGroup.ModeParams("taxi");
		taxiScore.setMarginalUtilityOfTraveling(-6.0);
		config.scoring().addModeParams(taxiScore);
		config.routing().setNetworkModes(Set.of("car", "taxi"));
		config.qsim().setMainModes(Set.of("car", "taxi"));
		var teleported = new RoutingConfigGroup.TeleportedModeParams("taxi");
		teleported.setTeleportedModeSpeed(10.0);
		config.routing().addTeleportedModeParams(teleported);

		RunHongKong5Pct.configurePhysicalTaxi(config, 0.05, -12.0);

		assertFalse(config.routing().getNetworkModes().contains("taxi"));
		assertFalse(config.qsim().getMainModes().contains("taxi"));
		assertFalse(config.routing().getModeRoutingParams().containsKey("taxi"));
		var taxi = MultiModeTaxiConfigGroup.get(config).getModalElements().iterator().next();
		assertFalse(taxi.breakSimulationIfNotAllRequestsServed);
		assertEquals(60, taxi.pickupDuration);
		assertEquals(30, taxi.dropoffDuration);
		var optimizer = assertInstanceOf(RuleBasedTaxiOptimizerParams.class,
				taxi.getTaxiOptimizerParams());
		assertEquals(RuleBasedRequestInserter.Goal.MIN_WAIT_TIME, optimizer.goal);
		assertEquals(30, optimizer.reoptimizationTimeStep);
	}

	@Test
	void physicalFleetKeepsTaxiCandidateInnovationWithoutEnablingPersonProxy() {
		assertFalse(RunHongKong5Pct.usesNetworkTaxiProxy(true, false, true));
		assertTrue(RunHongKong5Pct.usesNetworkTaxiProxy(true, false, false));
		assertTrue(RunHongKong5Pct.usesNetworkTaxiProxy(false, true, true));
	}
}
