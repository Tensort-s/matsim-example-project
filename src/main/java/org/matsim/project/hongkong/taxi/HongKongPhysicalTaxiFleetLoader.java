package org.matsim.project.hongkong.taxi;

import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.contrib.dvrp.fleet.DvrpVehicleSpecificationWithMatsimVehicle;
import org.matsim.core.utils.io.MatsimXmlParser;
import org.matsim.vehicles.Vehicle;
import org.matsim.vehicles.VehicleType;
import org.matsim.vehicles.VehicleUtils;
import org.xml.sax.Attributes;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Set;
import java.util.Stack;
import java.util.LinkedHashMap;
import java.util.Map;

/** Loads a DVRP fleet file as standard MATSim vehicles so their PCU is retained by QSim. */
public final class HongKongPhysicalTaxiFleetLoader {

	public static final String VEHICLE_TYPE_ID = "hk_physical_taxi";
	public static final int PASSENGER_CAPACITY = 4;
	public static final Set<Double> ALLOWED_PCU = Set.of(
			1.0, 0.75, 0.5, 0.25, 1.0 / 6.0, 0.1, 0.05);

	private HongKongPhysicalTaxiFleetLoader() {
	}

	public static FleetLoadStats load(Scenario scenario, Path fleetFile, double pcu) {
		if (!Files.isRegularFile(fleetFile)) {
			throw new IllegalArgumentException("Taxi DVRP fleet file does not exist: " + fleetFile);
		}
		if (!ALLOWED_PCU.contains(pcu)) {
			throw new IllegalArgumentException(
					"Taxi PCU must be one of " + ALLOWED_PCU + "; actual=" + pcu);
		}
		LegacyProxyRemoval legacyRemoval = removeLegacyPersonLocalProxy(scenario);
		for (Vehicle vehicle : scenario.getVehicles().getVehicles().values()) {
			if (HongKongTaxiScoringParameters.TAXI_MODE.equals(vehicle.getAttributes()
					.getAttribute(DvrpVehicleSpecificationWithMatsimVehicle.DVRP_MODE))) {
				throw new IllegalStateException(
						"Scenario already contains a physical Taxi DVRP vehicle: " + vehicle.getId());
			}
		}

		Id<VehicleType> typeId = Id.create(VEHICLE_TYPE_ID, VehicleType.class);
		if (scenario.getVehicles().getVehicleTypes().containsKey(typeId)) {
			throw new IllegalStateException("Taxi DVRP vehicle type already exists: " + typeId);
		}
		VehicleType type = VehicleUtils.createVehicleType(typeId)
				.setNetworkMode(org.matsim.api.core.v01.TransportMode.car)
				.setPcuEquivalents(pcu);
		type.getCapacity().setSeats(PASSENGER_CAPACITY).setStandingRoom(0);
		scenario.getVehicles().addVehicleType(type);

		Reader reader = new Reader(scenario, type);
		try (var input = org.matsim.core.utils.io.IOUtils.getInputStream(
				fleetFile.toAbsolutePath().normalize().toUri().toURL())) {
			reader.parse(input);
		} catch (java.io.IOException error) {
			throw new IllegalArgumentException("Cannot read Taxi fleet: " + fleetFile, error);
		}
		if (reader.count == 0) {
			throw new IllegalStateException("Taxi DVRP fleet is empty: " + fleetFile);
		}
		return new FleetLoadStats(reader.count, reader.earliestBegin, reader.latestEnd, pcu,
				Map.copyOf(reader.serviceWindows), legacyRemoval.removedVehicles(),
				legacyRemoval.removedPersonMappings());
	}

	private static LegacyProxyRemoval removeLegacyPersonLocalProxy(Scenario scenario) {
		int mappings = 0;
		for (var person : scenario.getPopulation().getPersons().values()) {
			if (person.getAttributes().getAttribute("vehicles") == null) continue;
			var ids = new LinkedHashMap<>(VehicleUtils.getVehicleIds(person));
			if (ids.remove(HongKongTaxiScoringParameters.TAXI_MODE) != null) {
				VehicleUtils.insertVehicleIdsIntoAttributes(person, ids);
				mappings++;
			}
		}
		var legacyIds = scenario.getVehicles().getVehicles().values().stream()
				.filter(vehicle -> "hk_network_taxi_proxy_v1".equals(vehicle.getType().getId().toString()))
				.map(Vehicle::getId).toList();
		legacyIds.forEach(scenario.getVehicles()::removeVehicle);
		var legacyType = Id.create("hk_network_taxi_proxy_v1", VehicleType.class);
		if (scenario.getVehicles().getVehicleTypes().containsKey(legacyType)) {
			scenario.getVehicles().removeVehicleType(legacyType);
		}
		return new LegacyProxyRemoval(legacyIds.size(), mappings);
	}

	private static final class Reader extends MatsimXmlParser {
		private final Scenario scenario;
		private final VehicleType type;
		private int count;
		private double earliestBegin = Double.POSITIVE_INFINITY;
		private double latestEnd = Double.NEGATIVE_INFINITY;
		private final Map<Id<Vehicle>, ServiceWindow> serviceWindows = new LinkedHashMap<>();

		private Reader(Scenario scenario, VehicleType type) {
			super(ValidationType.DTD_ONLY);
			this.scenario = scenario;
			this.type = type;
		}

		@Override
		public void startTag(String name, Attributes atts, Stack<String> context) {
			if (!"vehicle".equals(name)) return;
			String id = required(atts, "id");
			String startLink = required(atts, "start_link");
			double begin = finiteTime(atts, "t_0", id);
			double end = finiteTime(atts, "t_1", id);
			if (end <= begin) {
				throw new IllegalArgumentException(
						"Taxi service end must be after begin: id=" + id + ", t0=" + begin + ", t1=" + end);
			}
			String capacityText = atts.getValue("capacity");
			int capacity = capacityText == null ? 1 : Integer.parseInt(capacityText);
			if (capacity != PASSENGER_CAPACITY) {
				throw new IllegalArgumentException(
						"Every Hong Kong Taxi must have capacity 4: id=" + id + ", capacity=" + capacity);
			}
			var link = scenario.getNetwork().getLinks().get(Id.createLinkId(startLink));
			if (link == null || !link.getAllowedModes().contains(org.matsim.api.core.v01.TransportMode.car)) {
				throw new IllegalArgumentException(
						"Taxi start link is absent or not Car-drivable: id=" + id + ", link=" + startLink);
			}

			Id<Vehicle> vehicleId = Id.createVehicleId(id);
			if (scenario.getVehicles().getVehicles().containsKey(vehicleId)) {
				throw new IllegalArgumentException("Duplicate Taxi/road vehicle id: " + vehicleId);
			}
			Vehicle vehicle = VehicleUtils.createVehicle(vehicleId, type);
			vehicle.getAttributes().putAttribute(
					DvrpVehicleSpecificationWithMatsimVehicle.DVRP_MODE,
					HongKongTaxiScoringParameters.TAXI_MODE);
			vehicle.getAttributes().putAttribute(
					DvrpVehicleSpecificationWithMatsimVehicle.START_LINK, startLink);
			vehicle.getAttributes().putAttribute(
					DvrpVehicleSpecificationWithMatsimVehicle.SERVICE_BEGIN_TIME, begin);
			vehicle.getAttributes().putAttribute(
					DvrpVehicleSpecificationWithMatsimVehicle.SERVICE_END_TIME, end);
			scenario.getVehicles().addVehicle(vehicle);
			serviceWindows.put(vehicleId, new ServiceWindow(begin, end));
			count++;
			earliestBegin = Math.min(earliestBegin, begin);
			latestEnd = Math.max(latestEnd, end);
		}

		@Override
		public void endTag(String name, String content, Stack<String> context) {
		}

		private static String required(Attributes atts, String name) {
			String value = atts.getValue(name);
			if (value == null || value.isBlank()) {
				throw new IllegalArgumentException("Taxi fleet vehicle is missing attribute " + name);
			}
			return value;
		}

		private static double finiteTime(Attributes atts, String name, String id) {
			double value = Double.parseDouble(required(atts, name));
			if (!Double.isFinite(value) || value < 0) {
				throw new IllegalArgumentException(
						"Illegal Taxi service time: id=" + id + ", " + name + "=" + value);
			}
			return value;
		}
	}

	public record FleetLoadStats(int vehicles, double earliestServiceBegin,
			double latestServiceEnd, double pcu,
			Map<Id<Vehicle>, ServiceWindow> serviceWindows,
			int removedLegacyProxyVehicles,
			int removedLegacyPersonMappings) {
	}

	public record ServiceWindow(double begin, double end) {
	}

	private record LegacyProxyRemoval(int removedVehicles, int removedPersonMappings) {
	}
}
