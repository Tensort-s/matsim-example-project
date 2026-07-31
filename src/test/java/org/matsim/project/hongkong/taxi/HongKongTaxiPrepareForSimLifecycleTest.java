package org.matsim.project.hongkong.taxi;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.network.Network;
import org.matsim.api.core.v01.network.Node;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.core.config.Config;
import org.matsim.core.controler.Controler;
import org.matsim.core.controler.PrepareForSim;
import org.matsim.core.controler.PrepareForSimImpl;
import org.matsim.core.network.NetworkUtils;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.project.hongkong.car.HongKongCarMarginalCostScoringComponentFactory;
import org.matsim.project.hongkong.pt.HongKongPtFareScoringComponentFactory;
import org.matsim.project.hongkong.scoring.HongKongMultimodalCostScoringModule;
import org.matsim.project.hongkong.scoring.HongKongMultimodalScoringFunctionFactory;

import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HongKongTaxiPrepareForSimLifecycleTest {

	@Test
	void stage8cCombinedModuleHasExactlyTaxiPtAndOneCarMarginalCostOwner() {
		Config config = HongKongTaxiTestFixtures.safeConfig();
		config.transit().setUseTransit(false);
		config.controller().setOutputDirectory(
				"target/stage8c-combined-module-" + UUID.randomUUID());
		Scenario scenario = ScenarioUtils.createScenario(config);
		addNetwork(scenario.getNetwork());

		Controler controler = new Controler(scenario);
		controler.addOverridingModule(
				new HongKongMultimodalCostScoringModule());
		controler.getInjector();
		HongKongMultimodalScoringFunctionFactory scoringFactory =
				(HongKongMultimodalScoringFunctionFactory)
						controler.getScoringFunctionFactory();

		assertEquals(
				List.of(
						HongKongCarMarginalCostScoringComponentFactory.COMPONENT_ID,
						HongKongPtFareScoringComponentFactory.COMPONENT_ID,
						HongKongTaxiFareScoringComponentFactory.COMPONENT_ID),
				scoringFactory.componentIds());
		assertEquals(
				Map.of(
						"car",
						HongKongCarMarginalCostScoringComponentFactory.COMPONENT_ID,
						"pt",
						HongKongPtFareScoringComponentFactory.COMPONENT_ID,
						"taxi",
						HongKongTaxiFareScoringComponentFactory.COMPONENT_ID),
				scoringFactory.activeModeOwners());
		HongKongCarMarginalCostScoringComponentFactory carFactory =
				controler.getInjector().getInstance(
						HongKongCarMarginalCostScoringComponentFactory.class);
		assertEquals(
				List.of(
						"car_fuel_or_electricity_v1",
						"car_confirmed_toll_v1",
						"car_destination_parking_v1"),
				carFactory.subcomponentIds());
	}

	@Test
	void defaultPrepareForSimUpdatesRouteBeforeScoringFactoryBuildsFareSchedule() {
		Config config = HongKongTaxiTestFixtures.safeConfig();
		config.transit().setUseTransit(false);
		config.global().setNumberOfThreads(2);
		config.controller().setOutputDirectory(
				"target/taxi-prepare-lifecycle-" + UUID.randomUUID());
		HongKongTaxiRoutingModule.configure(config);

		Scenario scenario = ScenarioUtils.createScenario(config);
		addNetwork(scenario.getNetwork());
		Person person = addTaxiPerson(scenario);
		Leg taxiBefore = (Leg) person.getSelectedPlan().getPlanElements().get(1);
		assertEquals(null, taxiBefore.getRoute());

		Controler controler = new Controler(scenario);
		controler.addOverridingModule(new HongKongTaxiRoutingModule());
		controler.addOverridingModule(new HongKongTaxiScoringModule());

		PrepareForSim prepareForSim =
				controler.getInjector().getInstance(PrepareForSim.class);
		assertInstanceOf(PrepareForSimImpl.class, prepareForSim);
		long customBefore =
				HongKongTaxiPtRoutePreparation.customStartupRebuildInvocationCount();

		prepareForSim.run();

		assertEquals(
				customBefore,
				HongKongTaxiPtRoutePreparation.customStartupRebuildInvocationCount());
		Leg preparedTaxi =
				(Leg) person.getSelectedPlan().getPlanElements().get(1);
		assertEquals("taxi", preparedTaxi.getMode());
		assertEquals("taxi", preparedTaxi.getRoutingMode());
		assertNotEquals("ride", preparedTaxi.getMode());
		assertNotNull(preparedTaxi.getRoute());
		assertTrue(Double.isFinite(preparedTaxi.getRoute().getDistance()));
		assertTrue(preparedTaxi.getRoute().getDistance() >= 0.0);
		assertTrue(preparedTaxi.getRoute().getTravelTime().isDefined());
		assertTrue(Double.isFinite(
				preparedTaxi.getRoute().getTravelTime().seconds()));
		assertTrue(preparedTaxi.getRoute().getTravelTime().seconds() >= 0.0);

		HongKongMultimodalScoringFunctionFactory scoringFactory =
				(HongKongMultimodalScoringFunctionFactory)
						controler.getScoringFunctionFactory();
		assertEquals(
				List.of(HongKongTaxiFareScoringComponentFactory.COMPONENT_ID),
				scoringFactory.componentIds());
		assertEquals(
				Map.of(
						HongKongTaxiScoringParameters.TAXI_MODE,
						HongKongTaxiFareScoringComponentFactory.COMPONENT_ID),
				scoringFactory.activeModeOwners());
		HongKongTaxiFareScoringComponentFactory taxiComponentFactory =
				controler.getInjector().getInstance(
						HongKongTaxiFareScoringComponentFactory.class);
		HongKongTaxiPersonFareSchedule schedule =
				taxiComponentFactory.routeFareScheduleFor(person);
		HongKongTaxiPersonFareSchedule.RouteFare scheduledFare =
				schedule.fareAt(0);
		double expectedFare = new HongKongTaxiFareCalculator()
				.calculate(
						preparedTaxi.getRoute().getDistance(),
						HongKongTaxiFareCalculator.URBAN_TAXI)
				.fareHkd();

		assertEquals(1, schedule.size());
		assertEquals(
				preparedTaxi.getRoute().getDistance(),
				scheduledFare.routeContext().distanceMeters());
		assertEquals(expectedFare, scheduledFare.calculation().fareHkd());
		assertNotEquals(
				999.9,
				scheduledFare.calculation().fareHkd(),
				"historical hkTaxiFareBaselineHkd must remain comparison-only");
	}

	private static Person addTaxiPerson(Scenario scenario) {
		Person person = PopulationUtils.getFactory()
				.createPerson(Id.createPersonId("prepare-lifecycle"));
		Plan plan = PopulationUtils.createPlan(person);
		Activity home = PopulationUtils.createActivityFromCoordAndLinkId(
				"home", new Coord(0, 0), Id.createLinkId("outbound"));
		home.setEndTime(8 * 3_600);
		plan.addActivity(home);
		Leg taxi = HongKongTaxiTestFixtures.taxiLeg(999.9);
		taxi.setRoute(null);
		for (String attribute : HongKongTaxiLegAttributes.NAMES) {
			home.getAttributes().putAttribute(
					attribute, taxi.getAttributes().getAttribute(attribute));
		}
		plan.addLeg(taxi);
		plan.addActivity(PopulationUtils.createActivityFromCoordAndLinkId(
				"work", new Coord(6_500, 0), Id.createLinkId("return")));
		person.addPlan(plan);
		person.setSelectedPlan(plan);
		scenario.getPopulation().addPerson(person);
		return person;
	}

	private static void addNetwork(Network network) {
		Node from = NetworkUtils.createAndAddNode(
				network, Id.createNodeId("from"), new Coord(0, 0));
		Node to = NetworkUtils.createAndAddNode(
				network, Id.createNodeId("to"), new Coord(6_500, 0));
		Link outbound = NetworkUtils.createAndAddLink(
				network,
				Id.createLinkId("outbound"),
				from,
				to,
				6_500,
				15,
				3_600,
				1);
		outbound.setAllowedModes(Set.of("car"));
		Link reverse = NetworkUtils.createAndAddLink(
				network,
				Id.createLinkId("return"),
				to,
				from,
				6_500,
				15,
				3_600,
				1);
		reverse.setAllowedModes(Set.of("car"));
	}
}
