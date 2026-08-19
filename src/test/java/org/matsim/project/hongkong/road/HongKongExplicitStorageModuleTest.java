package org.matsim.project.hongkong.road;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.network.Node;
import org.matsim.contrib.signals.SignalSystemsConfigGroup;
import org.matsim.contrib.signals.builder.Signals;
import org.matsim.contrib.signals.controller.fixedTime.DefaultPlanbasedSignalSystemController;
import org.matsim.contrib.signals.data.SignalsData;
import org.matsim.contrib.signals.data.signalcontrol.v20.SignalGroupSettingsData;
import org.matsim.contrib.signals.model.Signal;
import org.matsim.contrib.signals.model.SignalGroup;
import org.matsim.contrib.signals.model.SignalPlan;
import org.matsim.contrib.signals.model.SignalSystem;
import org.matsim.contrib.signals.utils.SignalUtils;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.ScoringConfigGroup;
import org.matsim.core.controler.Controler;
import org.matsim.core.controler.OutputDirectoryHierarchy;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.population.routes.RouteUtils;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

final class HongKongExplicitStorageModuleTest {
	private static final int LINK_COUNT = 7;

	@Test
	void installsRegistrySizedDirectPcuCapacitiesWithoutChangingPhysicalLinks() throws Exception {
		Config config = ConfigUtils.createConfig();
		Path temporary = Path.of("target", "test-fixture",
				"HongKongExplicitStorageModuleTest").toAbsolutePath();
		Files.createDirectories(temporary);
		Path output = Path.of("target", "test-output",
				"HongKongExplicitStorageModuleTest").toAbsolutePath();
		SignalSystemsConfigGroup signalsConfig = ConfigUtils.addOrGetModule(
				config, SignalSystemsConfigGroup.class);
		signalsConfig.setUseSignalSystems(true);
		config.controller().setLastIteration(0);
		config.controller().setOutputDirectory(output.toString());
		config.controller().setOverwriteFileSetting(
				OutputDirectoryHierarchy.OverwriteFileSetting.deleteDirectoryIfExists);
		config.qsim().setFlowCapFactor(0.1);
		config.qsim().setStorageCapFactor(0.1);
		config.qsim().setTimeStepSize(1.0);
		config.qsim().setUsingFastCapacityUpdate(false);
		config.qsim().setStartTime(0.0);
		config.qsim().setEndTime(120.0);
		for (String activityType : List.of("home", "work")) {
			ScoringConfigGroup.ActivityParams params =
					new ScoringConfigGroup.ActivityParams(activityType);
			params.setTypicalDuration(3600.0);
			config.scoring().addActivityParams(params);
		}
		Scenario scenario = ScenarioUtils.createScenario(config);
		scenario.getNetwork().setEffectiveCellSize(7.5);
		var factory = scenario.getNetwork().getFactory();
		for (int index = 0; index < LINK_COUNT; index++) {
			Node node = factory.createNode(Id.createNodeId("n" + index), new Coord(index * 100.0, 0));
			scenario.getNetwork().addNode(node);
		}
		for (int index = 0; index < LINK_COUNT; index++) {
			Link link = factory.createLink(Id.createLinkId("l" + index),
					scenario.getNetwork().getNodes().get(Id.createNodeId("n" + index)),
					scenario.getNetwork().getNodes().get(Id.createNodeId("n" + ((index + 1) % LINK_COUNT))));
			link.setLength(100.0);
			link.setFreespeed(10.0);
			link.setNumberOfLanes(1.0);
			link.setCapacity(3600.0);
			link.setAllowedModes(java.util.Set.of("car"));
			scenario.getNetwork().addLink(link);
		}
		var person = PopulationUtils.getFactory().createPerson(Id.createPersonId("p"));
		var personPlan = PopulationUtils.createPlan(person);
		var home = PopulationUtils.createActivityFromLinkId("home", Id.createLinkId("l6"));
		home.setEndTime(1.0);
		personPlan.addActivity(home);
		var car = PopulationUtils.createLeg(TransportMode.car);
		car.setRoute(RouteUtils.createLinkNetworkRouteImpl(
				Id.createLinkId("l6"), List.of(Id.createLinkId("l0")), Id.createLinkId("l1")));
		personPlan.addLeg(car);
		personPlan.addActivity(PopulationUtils.createActivityFromLinkId("work", Id.createLinkId("l1")));
		person.addPlan(personPlan);
		scenario.getPopulation().addPerson(person);
		SignalsData signalsData = SignalUtils.createSignalsData(signalsConfig);
		scenario.addScenarioElement(SignalsData.ELEMENT_NAME, signalsData);
		var system = signalsData.getSignalSystemsData().getFactory()
				.createSignalSystemData(Id.create("system", SignalSystem.class));
		signalsData.getSignalSystemsData().addSignalSystemData(system);
		var signal = signalsData.getSignalSystemsData().getFactory()
				.createSignalData(Id.create("signal", Signal.class));
		signal.setLinkId(Id.createLinkId("l0"));
		system.addSignalData(signal);
		SignalUtils.createAndAddSignalGroups4Signals(signalsData.getSignalGroupsData(), system);
		var controller = signalsData.getSignalControlData().getFactory()
				.createSignalSystemControllerData(system.getId());
		controller.setControllerIdentifier(DefaultPlanbasedSignalSystemController.IDENTIFIER);
		signalsData.getSignalControlData().addSignalSystemControllerData(controller);
		var plan = signalsData.getSignalControlData().getFactory()
				.createSignalPlanData(Id.create("plan", SignalPlan.class));
		plan.setStartTime(0.0);
		plan.setEndTime(120.0);
		plan.setCycleTime(60);
		plan.setOffset(0);
		SignalGroupSettingsData settings = signalsData.getSignalControlData().getFactory()
				.createSignalGroupSettingsData(Id.create("signal", SignalGroup.class));
		settings.setOnset(0);
		settings.setDropping(30);
		plan.addSignalGroupSettings(settings);
		controller.addSignalPlanData(plan);

		Path networkEvidence = temporary.resolve("network.xml.gz");
		Files.writeString(networkEvidence, "immutable-network-evidence", StandardCharsets.UTF_8);
		String sha = HexFormat.of().formatHex(
				MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(networkEvidence)));
		Path registryPath = temporary.resolve("road_supply_parameters_v2.csv");
		var lines = new java.util.ArrayList<String>();
		lines.add("link_id,physical_length_m,physical_lanes,freespeed_m_s,physical_flow_capacity_vph,flow_capacity_vph,flow_capacity_source,flow_capacity_override,storage_capacity_qsim_pcu,storage_capacity_source,storage_capacity_override,storage_floor_pcu,continuity_candidate,storage_lane_floor_x_pcu,continuity_lane_floor_x_pcu,continuity_relationship_ids,parameter_version,source_network_sha256");
		for (int index = 0; index < LINK_COUNT; index++) {
			double qsimFlow = index == 0 ? 7200.0 : 3600.0;
			boolean flowOverride = index == 0;
			lines.add("l" + index + ",100,1,10,3600," + qsimFlow + ",tpdm,"
					+ flowOverride + ",2,direct,true,2,true,1,1,u->l"
					+ index + ",test," + sha);
		}
		Files.write(registryPath, lines, StandardCharsets.UTF_8);
		HongKongRoadSupplyRegistry registry = HongKongRoadSupplyRegistry.load(
				registryPath, networkEvidence, scenario, 0.05);
		assertEquals(LINK_COUNT, registry.overrides().size());

		Controler controler = new Controler(scenario);
		controler.addOverridingModule(new HongKongExplicitStorageModule(registry));
		Signals.configure(controler);
		// This must be last: the Hong Kong factory composes the signal turn logic
		// with explicit flow/storage instead of allowing either module to win.
		controler.addOverridingQSimModule(new HongKongExplicitStorageQSimModule());
		controler.run();

		Path audit = output.resolve("ITERS/it.0/0.explicit_storage_capacity_audit.csv");
		List<String> auditLines = Files.readAllLines(audit, StandardCharsets.UTF_8);
		assertEquals(LINK_COUNT + 1, auditLines.size());
		assertTrue(auditLines.stream().skip(1).allMatch(line -> line.split(",")[1].equals("2.0")));
		assertTrue(auditLines.stream().skip(1).allMatch(line -> line.split(",")[2].equals("2.0")));
		String[] firstAudit = auditLines.get(1).split(",");
		assertEquals("7200.0", firstAudit[3]);
		assertEquals(0.2, Double.parseDouble(firstAudit[4]), 1e-12);
		assertEquals(0.2, Double.parseDouble(firstAudit[5]), 1e-12);
		assertEquals(100.0, scenario.getNetwork().getLinks().get(Id.createLinkId("l0")).getLength());
		assertEquals(1.0, scenario.getNetwork().getLinks().get(Id.createLinkId("l0")).getNumberOfLanes());
		assertEquals(3600.0, scenario.getNetwork().getLinks().get(Id.createLinkId("l0")).getCapacity());
	}
}
