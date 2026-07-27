package org.matsim.project;

import org.matsim.api.core.v01.Scenario;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.network.io.MatsimNetworkReader;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.pt.transitSchedule.api.TransitScheduleReader;
import org.matsim.vehicles.MatsimVehicleReader;

/** Loads Hong Kong network and transit supply without requiring population plans. */
public final class ValidateHongKongTransitSupply {

	private ValidateHongKongTransitSupply() {
	}

	public static void main(String[] args) {
		if (args.length != 3) {
			throw new IllegalArgumentException(
				"Usage: ValidateHongKongTransitSupply <network> <schedule> <vehicles>"
			);
		}

		Scenario scenario = ScenarioUtils.createScenario(ConfigUtils.createConfig());
		MatsimNetworkReader networkReader = new MatsimNetworkReader(scenario.getNetwork());
		networkReader.setValidating(false);
		networkReader.readFile(args[0]);
		TransitScheduleReader scheduleReader = new TransitScheduleReader(scenario);
		scheduleReader.readFile(args[1]);
		MatsimVehicleReader vehicleReader = new MatsimVehicleReader(scenario.getTransitVehicles());
		vehicleReader.readFile(args[2]);

		long routes = scenario.getTransitSchedule().getTransitLines().values().stream()
			.mapToLong(line -> line.getRoutes().size())
			.sum();
		long departures = scenario.getTransitSchedule().getTransitLines().values().stream()
			.flatMap(line -> line.getRoutes().values().stream())
			.mapToLong(route -> route.getDepartures().size())
			.sum();

		System.out.printf(
			"MATSIM_SUPPLY_LOAD_OK nodes=%d links=%d facilities=%d lines=%d routes=%d "
				+ "departures=%d vehicleTypes=%d vehicles=%d%n",
			scenario.getNetwork().getNodes().size(),
			scenario.getNetwork().getLinks().size(),
			scenario.getTransitSchedule().getFacilities().size(),
			scenario.getTransitSchedule().getTransitLines().size(),
			routes,
			departures,
			scenario.getTransitVehicles().getVehicleTypes().size(),
			scenario.getTransitVehicles().getVehicles().size()
		);
	}
}
