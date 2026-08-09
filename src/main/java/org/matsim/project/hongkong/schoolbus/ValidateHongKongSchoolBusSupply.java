package org.matsim.project.hongkong.schoolbus;

import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.network.Link;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.population.routes.NetworkRoute;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.pt.transitSchedule.api.TransitLine;
import org.matsim.pt.transitSchedule.api.TransitRoute;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/** Loads and validates the standalone Hong Kong school-bus v6 supply bundle. */
public final class ValidateHongKongSchoolBusSupply {

	private static final String LINE_PREFIX = "line_school_bus_v6_";

	private ValidateHongKongSchoolBusSupply() {
	}

	public static void main(String[] args) {
		if (args.length != 3) {
			System.err.println("Usage: ValidateHongKongSchoolBusSupply <network> <schedule> <vehicles>");
			System.exit(64);
		}
		Path networkPath = Path.of(args[0]).toAbsolutePath().normalize();
		Path schedulePath = Path.of(args[1]).toAbsolutePath().normalize();
		Path vehiclesPath = Path.of(args[2]).toAbsolutePath().normalize();
		for (Path path : List.of(networkPath, schedulePath, vehiclesPath)) {
			if (!Files.isRegularFile(path)) {
				throw new IllegalArgumentException("Missing supply file: " + path);
			}
		}

		Config config = ConfigUtils.createConfig();
		config.network().setInputFile(networkPath.toString());
		config.transit().setUseTransit(true);
		config.transit().setTransitScheduleFile(schedulePath.toString());
		config.transit().setVehiclesFile(vehiclesPath.toString());
		config.transit().setTransitModes(
				Set.of("bus", "gmb", "train", "light_rail", "ferry", "school_bus")
		);
		Scenario scenario = ScenarioUtils.loadScenario(config);

		int lineCount = 0;
		int routeCount = 0;
		int departureCount = 0;
		Set<Id<?>> vehicleIds = new LinkedHashSet<>();
		for (TransitLine line : scenario.getTransitSchedule().getTransitLines().values()) {
			if (!line.getId().toString().startsWith(LINE_PREFIX)) {
				continue;
			}
			lineCount++;
			if (line.getRoutes().size() != 2) {
				throw new IllegalStateException("School-bus line does not have two directions: " + line.getId());
			}
			for (TransitRoute route : line.getRoutes().values()) {
				routeCount++;
				if (!"school_bus".equals(route.getTransportMode())) {
					throw new IllegalStateException("Unexpected route mode: " + route.getId());
				}
				NetworkRoute networkRoute = route.getRoute();
				List<Id<Link>> linkIds = new ArrayList<>();
				linkIds.add(networkRoute.getStartLinkId());
				linkIds.addAll(networkRoute.getLinkIds());
				if (!linkIds.getLast().equals(networkRoute.getEndLinkId())) {
					linkIds.add(networkRoute.getEndLinkId());
				}
				for (int index = 0; index < linkIds.size(); index++) {
					Link link = scenario.getNetwork().getLinks().get(linkIds.get(index));
					if (link == null) {
						throw new IllegalStateException("Missing route link " + linkIds.get(index));
					}
					if (!link.getAllowedModes().contains("school_bus")) {
						throw new IllegalStateException("School bus not allowed on " + link.getId());
					}
					if (index > 0) {
						Link previous = scenario.getNetwork().getLinks().get(linkIds.get(index - 1));
						if (!previous.getToNode().getId().equals(link.getFromNode().getId())) {
							throw new IllegalStateException("Discontinuous route " + route.getId());
						}
					}
				}
				departureCount += route.getDepartures().size();
				route.getDepartures().values().forEach(
						departure -> vehicleIds.add(departure.getVehicleId())
				);
			}
		}

		if (lineCount != 3439 || routeCount != 6878 || departureCount != 6878) {
			throw new IllegalStateException(
					"Unexpected school-bus counts: lines=" + lineCount
							+ ", routes=" + routeCount + ", departures=" + departureCount
			);
		}
		if (vehicleIds.size() != 3439) {
			throw new IllegalStateException("Unexpected school-bus vehicle count: " + vehicleIds.size());
		}
		for (Id<?> vehicleId : vehicleIds) {
			if (!scenario.getTransitVehicles().getVehicles().containsKey(vehicleId)) {
				throw new IllegalStateException("Missing transit vehicle " + vehicleId);
			}
		}

		System.out.println("school_bus_supply_matsim_load=PASS");
		System.out.println("school_bus_lines=" + lineCount);
		System.out.println("school_bus_routes=" + routeCount);
		System.out.println("school_bus_departures=" + departureCount);
		System.out.println("school_bus_vehicles=" + vehicleIds.size());
	}
}
