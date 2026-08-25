package org.matsim.project.hongkong.walk;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.network.Node;
import org.matsim.core.network.NetworkUtils;

import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HongKongPhysicalWalkModuleTest {

	@Test
	void enablesWalkOnCarLinksOnlyAndIsIdempotent() {
		var network = NetworkUtils.createNetwork();
		Node a = network.getFactory().createNode(Id.createNodeId("a"), new Coord(0, 0));
		Node b = network.getFactory().createNode(Id.createNodeId("b"), new Coord(1, 0));
		network.addNode(a);
		network.addNode(b);
		Link car = network.getFactory().createLink(Id.createLinkId("car"), a, b);
		car.setAllowedModes(Set.of(TransportMode.car));
		network.addLink(car);
		Link transit = network.getFactory().createLink(Id.createLinkId("transit"), b, a);
		transit.setAllowedModes(Set.of(TransportMode.pt));
		network.addLink(transit);

		assertEquals(1, HongKongPhysicalWalkModule.enableOnCarLinks(network));
		assertTrue(car.getAllowedModes().contains(TransportMode.walk));
		assertFalse(transit.getAllowedModes().contains(TransportMode.walk));
		assertEquals(0, HongKongPhysicalWalkModule.enableOnCarLinks(network));
	}
}
