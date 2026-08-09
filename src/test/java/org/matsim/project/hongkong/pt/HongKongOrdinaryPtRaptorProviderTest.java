package org.matsim.project.hongkong.pt;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.network.Network;
import org.matsim.core.network.NetworkUtils;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.pt.transitSchedule.api.TransitLine;
import org.matsim.pt.transitSchedule.api.TransitRoute;
import org.matsim.pt.transitSchedule.api.TransitSchedule;
import org.matsim.pt.transitSchedule.TransitScheduleFactoryImpl;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertSame;

class HongKongOrdinaryPtRaptorProviderTest {

	@Test
	void excludesSchoolBusRoutesWithoutMutatingFullSchedule() {
		TransitSchedule full = new TransitScheduleFactoryImpl().createTransitSchedule();
		TransitLine mixedLine = full.getFactory().createTransitLine(Id.create("mixed", TransitLine.class));
		TransitRoute ptRoute = route(full, "ordinary", "pt");
		TransitRoute schoolBusRoute = route(full, "school", "school_bus");
		mixedLine.addRoute(ptRoute);
		mixedLine.addRoute(schoolBusRoute);
		full.addTransitLine(mixedLine);

		TransitSchedule filtered = HongKongOrdinaryPtRaptorProvider
				.ordinaryPtRoutingSchedule(full);

		assertEquals(2, full.getTransitLines().get(mixedLine.getId()).getRoutes().size());
		assertEquals(1, filtered.getTransitLines().get(mixedLine.getId()).getRoutes().size());
		assertSame(ptRoute, filtered.getTransitLines().get(mixedLine.getId())
				.getRoutes().get(ptRoute.getId()));
		assertFalse(filtered.getTransitLines().get(mixedLine.getId())
				.getRoutes().containsKey(schoolBusRoute.getId()));
	}

	private static TransitRoute route(TransitSchedule schedule, String id, String mode) {
		Network network = NetworkUtils.createNetwork();
		var from = NetworkUtils.createAndAddNode(network, Id.createNodeId(id + "_from"),
				new org.matsim.api.core.v01.Coord(0, 0));
		var to = NetworkUtils.createAndAddNode(network, Id.createNodeId(id + "_to"),
				new org.matsim.api.core.v01.Coord(1, 0));
		var link = NetworkUtils.createAndAddLink(network, Id.createLinkId(id + "_link"), from, to,
				1, 1, 1, 1);
		return schedule.getFactory().createTransitRoute(
				Id.create(id, TransitRoute.class),
				RouteUtils.createLinkNetworkRouteImpl(link.getId(), link.getId()),
				List.of(),
				mode);
	}
}
