package org.matsim.project.hongkong.taxi;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.network.Node;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.vehicles.VehicleUtils;

import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HongKongNetworkTaxiRoutingModuleTest {
	@Test
	void configuresRoadModeAndOnePcuVehiclePerPersonWithoutChangingIds() {
		var config = ConfigUtils.createConfig();
		HongKongNetworkTaxiRoutingModule.configure(config);
		assertTrue(config.routing().getNetworkModes().contains("taxi"));
		assertTrue(config.qsim().getMainModes().contains("taxi"));

		var scenario = ScenarioUtils.createScenario(config);
		Node from = scenario.getNetwork().getFactory().createNode(Id.createNodeId("n1"), new Coord(0, 0));
		Node to = scenario.getNetwork().getFactory().createNode(Id.createNodeId("n2"), new Coord(100, 0));
		scenario.getNetwork().addNode(from);
		scenario.getNetwork().addNode(to);
		Link link = scenario.getNetwork().getFactory().createLink(Id.createLinkId("l1"), from, to);
		link.setAllowedModes(Set.of(TransportMode.car));
		scenario.getNetwork().addLink(link);
		var person = scenario.getPopulation().getFactory().createPerson(Id.createPersonId("p1"));
		scenario.getPopulation().addPerson(person);

		var stats = HongKongNetworkTaxiRoutingModule.prepareScenario(scenario);
		assertEquals(1, stats.taxiEnabledCarLinks());
		assertEquals(1, stats.personTaxiVehicles());
		assertTrue(link.getAllowedModes().contains("taxi"));
		var taxiVehicle = scenario.getVehicles().getVehicles().get(
				VehicleUtils.getVehicleIds(person).get("taxi"));
		assertEquals(1.0, taxiVehicle.getType().getPcuEquivalents());
		assertEquals("taxi", taxiVehicle.getType().getNetworkMode());
	}
}
