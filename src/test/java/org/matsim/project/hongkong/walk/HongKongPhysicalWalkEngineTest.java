package org.matsim.project.hongkong.walk;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.network.Node;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.ScoringConfigGroup;
import org.matsim.core.controler.AbstractModule;
import org.matsim.core.controler.Controler;
import org.matsim.core.controler.OutputDirectoryHierarchy;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.network.NetworkUtils;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.vehicles.VehicleUtils;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HongKongPhysicalWalkEngineTest {

	@Test
	void advancesWalkOverNetworkLinksWithoutTeleportationArrival() {
		var config = ConfigUtils.createConfig();
		config.transit().setUseTransit(false);
		config.controller().setLastIteration(0);
		config.controller().setOutputDirectory("target/physical-walk-qsim-" + UUID.randomUUID());
		config.controller().setOverwriteFileSetting(
				OutputDirectoryHierarchy.OverwriteFileSetting.deleteDirectoryIfExists);
		config.qsim().setEndTime(1_000);
		config.scoring().addActivityParams(new ScoringConfigGroup.ActivityParams("home")
				.setTypicalDuration(12 * 3_600));
		config.scoring().addActivityParams(new ScoringConfigGroup.ActivityParams("work")
				.setTypicalDuration(8 * 3_600));
		config.routing().removeTeleportedModeParams(TransportMode.walk);
		config.routing().setNetworkModes(Set.of(TransportMode.car));
		HongKongPhysicalWalkQSimModule.activateInConfig(config);

		var scenario = ScenarioUtils.createScenario(config);
		Node a = NetworkUtils.createAndAddNode(scenario.getNetwork(), Id.createNodeId("a"), new Coord(0, 0));
		Node b = NetworkUtils.createAndAddNode(scenario.getNetwork(), Id.createNodeId("b"), new Coord(100, 0));
		Link out = NetworkUtils.createAndAddLink(scenario.getNetwork(), Id.createLinkId("out"),
				a, b, 100, 10, 3_600, 1);
		Link back = NetworkUtils.createAndAddLink(scenario.getNetwork(), Id.createLinkId("back"),
				b, a, 100, 10, 3_600, 1);
		out.setAllowedModes(Set.of(TransportMode.car, TransportMode.walk));
		back.setAllowedModes(Set.of(TransportMode.car, TransportMode.walk));

		var person = PopulationUtils.getFactory().createPerson(Id.createPersonId("walker"));
		Plan plan = PopulationUtils.createPlan(person);
		var home = PopulationUtils.createActivityFromCoordAndLinkId("home", new Coord(0, 0), out.getId());
		home.setEndTime(100);
		plan.addActivity(home);
		Leg walk = PopulationUtils.createLeg(TransportMode.walk);
		walk.setRoute(null);
		walk.setRoutingMode(TransportMode.walk);
		plan.addLeg(walk);
		plan.addActivity(PopulationUtils.createActivityFromCoordAndLinkId(
				"work", new Coord(100, 0), back.getId()));
		person.addPlan(plan);
		person.setSelectedPlan(plan);
		scenario.getPopulation().addPerson(person);
		var walkVehicleType = scenario.getVehicles().addModeVehicleType(TransportMode.walk);
		var walkVehicleId = VehicleUtils.createVehicleId(person, TransportMode.walk);
		scenario.getVehicles().addVehicle(VehicleUtils.createVehicle(walkVehicleId, walkVehicleType));
		VehicleUtils.insertVehicleIdsIntoAttributes(person, java.util.Map.of(
				TransportMode.walk, walkVehicleId));

		List<String> eventTypes = new ArrayList<>();
		BasicEventHandler handler = new BasicEventHandler() {
			@Override
			public void handleEvent(Event event) {
				if (event.getAttributes().get("person") != null
						&& event.getAttributes().get("person").equals("walker")) {
					eventTypes.add(event.getEventType() + "|"
							+ event.getAttributes().getOrDefault("mode", ""));
				}
			}
		};
		Controler controler = new Controler(scenario);
		controler.addOverridingModule(new HongKongPhysicalWalkModule());
		controler.addQSimModule(new HongKongPhysicalWalkQSimModule());
		controler.addOverridingModule(new AbstractModule() {
			@Override
			public void install() {
				addEventHandlerBinding().toInstance(handler);
			}
		});
		controler.run();

		assertEquals(1, eventTypes.stream().filter(value -> value.startsWith(
				PhysicalWalkLinkEvent.ENTER_TYPE + "|")).count());
		assertEquals(1, eventTypes.stream().filter(value -> value.startsWith(
				PhysicalWalkLinkEvent.LEAVE_TYPE + "|")).count());
		assertTrue(eventTypes.stream().anyMatch(value -> value.startsWith("departure|")));
		assertTrue(eventTypes.stream().anyMatch(value -> value.startsWith("arrival|")));
		assertFalse(eventTypes.contains("travelled|walk"));
	}

	@Test
	void preservesContinuousRouteTimeAcrossDiscreteQSimSteps() {
		var config = ConfigUtils.createConfig();
		config.transit().setUseTransit(false);
		config.controller().setLastIteration(0);
		config.controller().setOutputDirectory("target/physical-walk-timing-qsim-" + UUID.randomUUID());
		config.controller().setOverwriteFileSetting(
				OutputDirectoryHierarchy.OverwriteFileSetting.deleteDirectoryIfExists);
		config.qsim().setEndTime(1_000);
		config.scoring().addActivityParams(new ScoringConfigGroup.ActivityParams("home")
				.setTypicalDuration(12 * 3_600));
		config.scoring().addActivityParams(new ScoringConfigGroup.ActivityParams("work")
				.setTypicalDuration(8 * 3_600));
		config.routing().removeTeleportedModeParams(TransportMode.walk);
		config.routing().setNetworkModes(Set.of(TransportMode.car));
		HongKongPhysicalWalkQSimModule.activateInConfig(config);

		var scenario = ScenarioUtils.createScenario(config);
		Node a = NetworkUtils.createAndAddNode(scenario.getNetwork(), Id.createNodeId("a"), new Coord(0, 0));
		Node b = NetworkUtils.createAndAddNode(scenario.getNetwork(), Id.createNodeId("b"), new Coord(1.5, 0));
		Node c = NetworkUtils.createAndAddNode(scenario.getNetwork(), Id.createNodeId("c"), new Coord(3.0, 0));
		Node d = NetworkUtils.createAndAddNode(scenario.getNetwork(), Id.createNodeId("d"), new Coord(4.5, 0));
		Node e = NetworkUtils.createAndAddNode(scenario.getNetwork(), Id.createNodeId("e"), new Coord(6.0, 0));
		Link start = NetworkUtils.createAndAddLink(scenario.getNetwork(), Id.createLinkId("start"),
				a, b, 1.5, 10, 3_600, 1);
		Link middleOne = NetworkUtils.createAndAddLink(scenario.getNetwork(), Id.createLinkId("middleOne"),
				b, c, 1.5, 10, 3_600, 1);
		Link middleTwo = NetworkUtils.createAndAddLink(scenario.getNetwork(), Id.createLinkId("middleTwo"),
				c, d, 1.5, 10, 3_600, 1);
		Link destination = NetworkUtils.createAndAddLink(scenario.getNetwork(), Id.createLinkId("destination"),
				d, e, 1.5, 10, 3_600, 1);
		Link reverseDestination = NetworkUtils.createAndAddLink(scenario.getNetwork(),
				Id.createLinkId("reverseDestination"), e, d, 1.5, 10, 3_600, 1);
		Link reverseMiddleTwo = NetworkUtils.createAndAddLink(scenario.getNetwork(),
				Id.createLinkId("reverseMiddleTwo"), d, c, 1.5, 10, 3_600, 1);
		Link reverseMiddleOne = NetworkUtils.createAndAddLink(scenario.getNetwork(),
				Id.createLinkId("reverseMiddleOne"), c, b, 1.5, 10, 3_600, 1);
		Link reverseStart = NetworkUtils.createAndAddLink(scenario.getNetwork(),
				Id.createLinkId("reverseStart"), b, a, 1.5, 10, 3_600, 1);
		for (Link link : List.of(start, middleOne, middleTwo, destination,
				reverseDestination, reverseMiddleTwo, reverseMiddleOne, reverseStart)) {
			link.setAllowedModes(Set.of(TransportMode.car, TransportMode.walk));
		}

		var person = PopulationUtils.getFactory().createPerson(Id.createPersonId("timed-walker"));
		Plan plan = PopulationUtils.createPlan(person);
		var home = PopulationUtils.createActivityFromCoordAndLinkId("home", new Coord(0, 0), start.getId());
		home.setEndTime(100);
		plan.addActivity(home);
		Leg walk = PopulationUtils.createLeg(TransportMode.walk);
		walk.setRoutingMode(TransportMode.walk);
		plan.addLeg(walk);
		plan.addActivity(PopulationUtils.createActivityFromCoordAndLinkId(
				"work", new Coord(6.0, 0), destination.getId()));
		person.addPlan(plan);
		person.setSelectedPlan(plan);
		scenario.getPopulation().addPerson(person);
		var walkVehicleType = scenario.getVehicles().addModeVehicleType(TransportMode.walk);
		var walkVehicleId = VehicleUtils.createVehicleId(person, TransportMode.walk);
		scenario.getVehicles().addVehicle(VehicleUtils.createVehicle(walkVehicleId, walkVehicleType));
		VehicleUtils.insertVehicleIdsIntoAttributes(person, java.util.Map.of(
				TransportMode.walk, walkVehicleId));

		List<Double> physicalArrivalTimes = new ArrayList<>();
		BasicEventHandler handler = event -> {
			if ("timed-walker".equals(event.getAttributes().get("person"))
					&& "arrival".equals(event.getEventType())
					&& "walk".equals(event.getAttributes().get("legMode"))) {
				physicalArrivalTimes.add(event.getTime());
			}
		};
		Controler controler = new Controler(scenario);
		controler.addOverridingModule(new HongKongPhysicalWalkModule());
		controler.addQSimModule(new HongKongPhysicalWalkQSimModule());
		controler.addOverridingModule(new AbstractModule() {
			@Override
			public void install() {
				addEventHandlerBinding().toInstance(handler);
			}
		});
		controler.run();

		// Three traversed 1.5 m links take 3 * (1.5 / 1.34) = 3.36 seconds.
		// QSim can round the final arrival to second 104, but must not add one
		// rounding second independently at every link (the old result was 106).
		assertEquals(List.of(104.0), physicalArrivalTimes);
	}
}
