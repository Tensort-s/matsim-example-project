package org.matsim.project.hongkong.taxi;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.contrib.dvrp.fleet.DvrpVehicleSpecificationWithMatsimVehicle;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.vehicles.Vehicle;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.*;

class HongKongPhysicalTaxiFleetLoaderTest {
	private final Path temp = Path.of("target", "taxi-fleet-loader-test-"
			+ java.util.UUID.randomUUID());

	@Test
	void loadsFleetAsPcuAwareMatsimVehicles() throws Exception {
		Files.createDirectories(temp);
		var scenario = ScenarioUtils.createScenario(ConfigUtils.createConfig());
		var factory = scenario.getNetwork().getFactory();
		var from = factory.createNode(Id.createNodeId("n0"), new Coord(0, 0));
		var to = factory.createNode(Id.createNodeId("n1"), new Coord(100, 0));
		scenario.getNetwork().addNode(from);
		scenario.getNetwork().addNode(to);
		var link = factory.createLink(Id.createLinkId("road_1"), from, to);
		link.setAllowedModes(Set.of(TransportMode.car));
		scenario.getNetwork().addLink(link);
		Path fleet = temp.resolve("fleet.xml");
		Files.writeString(fleet, """
				<?xml version="1.0" encoding="UTF-8"?>
				<!DOCTYPE vehicles SYSTEM "http://matsim.org/files/dtd/dvrp_vehicles_v1.dtd">
				<vehicles>
				  <vehicle id="hk_taxi_00001" start_link="road_1" t_0="3600" t_1="68400" capacity="4"/>
				</vehicles>
				""");

		var stats = HongKongPhysicalTaxiFleetLoader.load(scenario, fleet, 0.05);
		assertEquals(1, stats.vehicles());
		assertEquals(0.05, stats.pcu());
		Vehicle vehicle = scenario.getVehicles().getVehicles().get(Id.createVehicleId("hk_taxi_00001"));
		assertNotNull(vehicle);
		assertEquals(0.05, vehicle.getType().getPcuEquivalents());
		assertEquals(4, vehicle.getType().getCapacity().getSeats());
		assertEquals("taxi", vehicle.getAttributes().getAttribute(
				DvrpVehicleSpecificationWithMatsimVehicle.DVRP_MODE));
		assertEquals(3600.0, vehicle.getAttributes().getAttribute(
				DvrpVehicleSpecificationWithMatsimVehicle.SERVICE_BEGIN_TIME));
	}

	@Test
	void rejectsUnapprovedPcu() {
		var scenario = ScenarioUtils.createScenario(ConfigUtils.createConfig());
		assertThrows(IllegalArgumentException.class,
				() -> HongKongPhysicalTaxiFleetLoader.load(scenario, temp.resolve("missing.xml"), 0.2));
	}
}
