package org.matsim.project.hongkong.pt;

import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.api.core.v01.network.Link;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.pt.routes.DefaultTransitPassengerRoute;
import org.matsim.pt.transitSchedule.api.Departure;
import org.matsim.pt.transitSchedule.api.TransitLine;
import org.matsim.pt.transitSchedule.api.TransitRoute;
import org.matsim.pt.transitSchedule.api.TransitRouteStop;
import org.matsim.pt.transitSchedule.api.TransitSchedule;
import org.matsim.pt.transitSchedule.api.TransitScheduleFactory;
import org.matsim.pt.transitSchedule.api.TransitStopFacility;

import java.util.List;

/**
 * Small deterministic PT fixture used only by the Stage 10 directed-cost
 * coverage test. It does not alter a production schedule or fare input.
 */
public final class HongKongDirectedPtFixture {

	private static final String SOURCE_PATH =
			"mtr_station_od_v1/mtr_station_od_fare_rules.parquet";
	private static final String SOURCE_SHA =
			"0829574983542c8178a562463d1711f93fe8381dfda7a7ad88bb7a8c7c2701fa";

	private HongKongDirectedPtFixture() {
	}

	public record Fixture(
			TransitSchedule schedule,
			HongKongPtFareRuntimeCatalog catalog,
			DefaultTransitPassengerRoute route) {
	}

	public static Fixture create(TransitSchedule schedule) {
		TransitScheduleFactory factory = schedule.getFactory();
		Id<Link> boardingLink = Id.createLinkId("stage10-pt-boarding-link");
		Id<Link> alightingLink = Id.createLinkId("stage10-pt-alighting-link");
		TransitStopFacility boarding = stop(
				factory, "stage10-pt-boarding", boardingLink, 0.0);
		TransitStopFacility alighting = stop(
				factory, "stage10-pt-alighting", alightingLink, 1.0);
		schedule.addStopFacility(boarding);
		schedule.addStopFacility(alighting);
		TransitRouteStop firstStop = factory.createTransitRouteStop(
				boarding, 0.0, 0.0);
		TransitRouteStop lastStop = factory.createTransitRouteStop(
				alighting, 300.0, 300.0);
		TransitRoute transitRoute = factory.createTransitRoute(
				Id.create("stage10-pt-route", TransitRoute.class),
				RouteUtils.createLinkNetworkRouteImpl(boardingLink, alightingLink),
				List.of(firstStop, lastStop), "train");
		Departure departure = factory.createDeparture(
				Id.create("stage10-pt-departure", Departure.class), 100.0);
		transitRoute.addDeparture(departure);
		TransitLine line = factory.createTransitLine(
				Id.create("stage10-pt-line", TransitLine.class));
		line.addRoute(transitRoute);
		schedule.addTransitLine(line);

		HongKongPtFareRuntimeCatalog.Builder builder =
				HongKongPtFareRuntimeCatalog.builder()
						.source(SOURCE_PATH, SOURCE_SHA)
						.mapStop(
								HongKongPtFareRuntimeCatalog.Layer.MTR_DOMESTIC,
								"stage10-pt-boarding", "1")
						.mapStop(
								HongKongPtFareRuntimeCatalog.Layer.MTR_DOMESTIC,
								"stage10-pt-alighting", "2")
						.rule(
								HongKongPtFareRuntimeCatalog.Layer.MTR_DOMESTIC,
								"", "", "1", "2", 4.9,
								"available", "B", "exact",
								"adult_octopus_domestic_mtr_station_od",
								"mtr_fares", "stage10-directed-pt-rule",
								SOURCE_PATH, SOURCE_SHA,
								"exact_ordered_station_od", "");
		return new Fixture(schedule, builder.build(),
			new DefaultTransitPassengerRoute(
					boarding, line, transitRoute, alighting));
	}

	private static TransitStopFacility stop(
			TransitScheduleFactory factory,
			String id,
			Id<Link> link,
			double coordinate) {
		TransitStopFacility stop = factory.createTransitStopFacility(
				Id.create(id, TransitStopFacility.class),
				new Coord(coordinate, coordinate), false);
		stop.setLinkId(link);
		return stop;
	}
}
