package org.matsim.project.hongkong.car;

import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.network.Network;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.population.routes.NetworkRoute;
import org.matsim.core.router.util.TravelTime;
import org.matsim.vehicles.Vehicle;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/**
 * Shared base-scenario rules for dynamic Hong Kong private-car energy, toll,
 * and destination-parking costs.
 *
 * <p>This object deliberately has no person/leg lookup. Every network-route
 * quote is reconstructed from its links, and every parking quote is built
 * from destination identity plus experienced arrival/departure times.</p>
 */
public final class HongKongDynamicCarCostRules {

	private static final String ENERGY_RULES = "car_energy_cost_parameters.csv";
	private static final String TOLL_RULES = "car_toll_rules.csv";
	private static final String TOLL_MAPPING =
			"toll_network_mapping_v1/toll_facility_network_mapping.csv";
	private static final String PARKING_RULES =
			"parking_event_application_v1/parking_cost_rules_repository_relative.csv";
	private static final String FEASIBILITY =
			"input_feasibility/car_leg_input_feasibility.parquet";
	private static final String PARKING_ZONE_REPAIRS =
			"dynamic_runtime_v1/facility_tcs_zone_repairs.csv";

	public record LinkCost(double energyHkd, double tollHkd, String tollFacilityId) {
		public LinkCost {
			if (!finiteNonnegative(energyHkd) || !finiteNonnegative(tollHkd)) {
				throw new IllegalArgumentException("Dynamic link costs must be finite and nonnegative.");
			}
			tollFacilityId = tollFacilityId == null ? "" : tollFacilityId;
		}

		public double totalHkd() {
			return energyHkd + tollHkd;
		}
	}

	public record RouteCost(double energyHkd, double tollHkd, int pricedLinks) {
		public RouteCost {
			if (!finiteNonnegative(energyHkd) || !finiteNonnegative(tollHkd)
					|| pricedLinks < 0) {
				throw new IllegalArgumentException("Invalid dynamic NetworkRoute quote.");
			}
		}

		public double totalHkd() {
			return energyHkd + tollHkd;
		}
	}

	public record ParkingCost(
			String destinationFacilityId,
			int destinationTcsZone,
			String activityGroup,
			double arrivalTimeS,
			double departureTimeS,
			double durationS,
			double costHkd,
			int billingUnits,
			String pricingMethod) {
		public ParkingCost {
			if (destinationFacilityId == null || destinationFacilityId.isBlank()
					|| destinationTcsZone < 1 || destinationTcsZone > 26
					|| activityGroup == null || activityGroup.isBlank()
					|| !Double.isFinite(arrivalTimeS)
					|| !Double.isFinite(departureTimeS)
					|| departureTimeS < arrivalTimeS
					|| !finiteNonnegative(durationS)
					|| !finiteNonnegative(costHkd)
					|| billingUnits < 0
					|| pricingMethod == null || pricingMethod.isBlank()) {
				throw new IllegalArgumentException("Invalid dynamic parking quote.");
			}
		}
	}

	record TollRate(double startTimeS, double endTimeS, double costHkd) {
		TollRate {
			if (!finiteNonnegative(startTimeS) || !finiteNonnegative(endTimeS)
					|| endTimeS < startTimeS || !finiteNonnegative(costHkd)) {
				throw new IllegalArgumentException("Invalid toll interval.");
			}
		}
	}

	record ParkingRule(
			String method,
			double hourlyDayHkd,
			double hourlyNightHkd,
			double dailyCapHkd,
			double minimumChargeHkd,
			double billingIncrementS,
			double dayStartS,
			double dayEndS) {
		ParkingRule {
			Objects.requireNonNull(method, "method");
			if (method.isBlank() || !finiteNonnegative(hourlyDayHkd)
					|| !finiteNonnegative(hourlyNightHkd)
					|| !finiteNonnegative(dailyCapHkd)
					|| !finiteNonnegative(minimumChargeHkd)
					|| !Double.isFinite(billingIncrementS) || billingIncrementS <= 0.0
					|| !finiteNonnegative(dayStartS) || !finiteNonnegative(dayEndS)
					|| dayEndS <= dayStartS) {
				throw new IllegalArgumentException("Invalid parking rule.");
			}
		}
	}

	record ParkingKey(String zoneGroup, String activityGroup) {
	}

	private final Network network;
	private final double energyHkdPerKm;
	private final Map<Id<Link>, String> tollFacilityByLink;
	private final Map<String, List<TollRate>> tollRatesByFacility;
	private final Map<String, Integer> tcsZoneByFacility;
	private final Map<String, String> vehicleClassById;
	private final Map<ParkingKey, ParkingRule> parkingRules;

	HongKongDynamicCarCostRules(
			Network network,
			double energyHkdPerKm,
			Map<Id<Link>, String> tollFacilityByLink,
			Map<String, List<TollRate>> tollRatesByFacility,
			Map<String, Integer> tcsZoneByFacility,
			Map<String, String> vehicleClassById,
			Map<ParkingKey, ParkingRule> parkingRules) {
		this.network = Objects.requireNonNull(network, "network");
		if (!Double.isFinite(energyHkdPerKm) || energyHkdPerKm < 0.0) {
			throw new IllegalArgumentException("Energy rate must be finite and nonnegative.");
		}
		this.energyHkdPerKm = energyHkdPerKm;
		this.tollFacilityByLink = Map.copyOf(tollFacilityByLink);
		Map<String, List<TollRate>> rates = new LinkedHashMap<>();
		tollRatesByFacility.forEach((facility, values) -> rates.put(facility, List.copyOf(values)));
		this.tollRatesByFacility = Map.copyOf(rates);
		this.tcsZoneByFacility = Map.copyOf(tcsZoneByFacility);
		this.vehicleClassById = Map.copyOf(vehicleClassById);
		this.parkingRules = Map.copyOf(parkingRules);
	}

	public static HongKongDynamicCarCostRules load(Path carCostRoot, Network network) {
		Path root = Objects.requireNonNull(carCostRoot, "carCostRoot")
				.toAbsolutePath().normalize();
		double energyRate = loadEnergyRate(root.resolve(ENERGY_RULES));
		Map<Id<Link>, String> mapping = loadTollMapping(root.resolve(TOLL_MAPPING), network);
		Map<String, List<TollRate>> tollRates = loadTollRates(root.resolve(TOLL_RULES));
		Map<ParkingKey, ParkingRule> parking = loadParkingRules(root.resolve(PARKING_RULES));
		Map<String, Integer> zones = new HashMap<>();
		Map<String, String> vehicleClasses = new HashMap<>();
		Set<String> missingZoneFacilities = new HashSet<>();
		loadDynamicLookups(
				root.resolve(FEASIBILITY), zones, vehicleClasses, missingZoneFacilities);
		loadParkingZoneRepairs(
				root.resolve(PARKING_ZONE_REPAIRS), zones, missingZoneFacilities);
		for (String facility : mapping.values()) {
			if (!tollRates.containsKey(facility)) {
				throw new IllegalStateException("Mapped toll facility has no base weekday rule: " + facility);
			}
		}
		return new HongKongDynamicCarCostRules(
				network, energyRate, mapping, tollRates, zones, vehicleClasses, parking);
	}

	public LinkCost quoteLink(Link link, double entryTimeS) {
		Objects.requireNonNull(link, "link");
		if (!Double.isFinite(entryTimeS)) {
			throw new IllegalArgumentException("Link entry time must be finite.");
		}
		double energy = link.getLength() * energyHkdPerKm / 1_000.0;
		String facility = tollFacilityByLink.getOrDefault(link.getId(), "");
		double toll = facility.isBlank() ? 0.0 : tollAt(facility, entryTimeS);
		return new LinkCost(energy, toll, facility);
	}

	/** Quotes the links that a network route enters: intermediate links plus end link. */
	public RouteCost quoteNetworkRoute(
			NetworkRoute route,
			double departureTimeS,
			TravelTime travelTime,
			Person person,
			Vehicle vehicle) {
		Objects.requireNonNull(route, "route");
		Objects.requireNonNull(travelTime, "travelTime");
		if (!Double.isFinite(departureTimeS)) {
			throw new IllegalArgumentException("Route departure time must be finite.");
		}
		List<Id<Link>> entered = new ArrayList<>(route.getLinkIds());
		if (route.getEndLinkId() != null
				&& (entered.isEmpty() || !route.getEndLinkId().equals(entered.getLast()))) {
			entered.add(route.getEndLinkId());
		}
		double time = departureTimeS;
		double energy = 0.0;
		double toll = 0.0;
		for (Id<Link> linkId : entered) {
			Link link = network.getLinks().get(linkId);
			if (link == null) {
				throw new IllegalArgumentException("NetworkRoute references missing link " + linkId);
			}
			LinkCost cost = quoteLink(link, time);
			energy += cost.energyHkd();
			toll += cost.tollHkd();
			double seconds = travelTime.getLinkTravelTime(link, time, person, vehicle);
			if (!Double.isFinite(seconds) || seconds < 0.0) {
				throw new IllegalStateException("TravelTime returned an invalid value for " + linkId);
			}
			time += seconds;
		}
		return new RouteCost(energy, toll, entered.size());
	}

	public ParkingCost quoteParking(
			String destinationFacilityId,
			String activityType,
			double arrivalTimeS,
			double departureTimeS) {
		String facility = requireText(destinationFacilityId, "destinationFacilityId");
		String group = activityGroup(activityType);
		Integer zone = tcsZoneByFacility.get(facility);
		if (zone == null) {
			throw new IllegalStateException("No TCS zone for dynamic parking destination " + facility);
		}
		ParkingRule rule = parkingRules.get(new ParkingKey(zoneGroup(zone), group));
		if (rule == null) {
			throw new IllegalStateException(
					"No resolved base parking rule for zone=" + zone + ", activity=" + activityType);
		}
		if (!Double.isFinite(arrivalTimeS) || !Double.isFinite(departureTimeS)
				|| departureTimeS < arrivalTimeS) {
			throw new IllegalArgumentException("Dynamic parking times are invalid.");
		}
		double duration = departureTimeS - arrivalTimeS;
		double cost;
		int units = 0;
		switch (rule.method()) {
			case "home_temporary_cost_zero_fixed_parking_separate" -> cost = 0.0;
			case "representative_day_pass", "representative_night_pass" -> cost = rule.dailyCapHkd();
			case "hourly_or_part_by_arrival_clock", "hourly_or_part_capped_at_ten_hours" -> {
				units = (int) Math.ceil(duration / rule.billingIncrementS());
				double uncapped = 0.0;
				for (int unit = 0; unit < units; unit++) {
					double clock = moduloDay(arrivalTimeS + unit * rule.billingIncrementS());
					uncapped += clock >= rule.dayStartS() && clock < rule.dayEndS()
							? rule.hourlyDayHkd() : rule.hourlyNightHkd();
				}
				cost = Math.max(rule.minimumChargeHkd(), Math.min(uncapped, rule.dailyCapHkd()));
			}
			default -> throw new IllegalStateException("Unsupported dynamic parking method " + rule.method());
		}
		return new ParkingCost(
				facility, zone, group, arrivalTimeS, departureTimeS, duration, cost, units, rule.method());
	}

	public boolean isPrivateCar(Person person, Vehicle vehicle) {
		String vehicleId = vehicle == null ? "" : vehicle.getId().toString();
		if (vehicleId.isBlank() && person != null) {
			Object assigned = person.getAttributes().getAttribute("assignedVehicleId");
			vehicleId = assigned == null ? "" : assigned.toString();
		}
		String vehicleClass = vehicleClassById.get(vehicleId);
		return !"motorcycle".equals(vehicleClass);
	}

	public boolean isPrivateCarVehicleId(String vehicleId) {
		return !"motorcycle".equals(vehicleClassById.get(vehicleId));
	}

	public double energyHkdPerKm() {
		return energyHkdPerKm;
	}

	public int mappedTollLinks() {
		return tollFacilityByLink.size();
	}

	public int parkingFacilities() {
		return tcsZoneByFacility.size();
	}

	private double tollAt(String facility, double timeS) {
		double clock = moduloDay(timeS);
		for (TollRate rate : tollRatesByFacility.getOrDefault(facility, List.of())) {
			// Official tables encode whole-second inclusive endpoints. MATSim
			// routing uses fractional seconds, so [start, end + 1) is the exact
			// continuous-time interpretation without artificial subsecond gaps.
			if (clock >= rate.startTimeS() && clock < rate.endTimeS() + 1.0) {
				return rate.costHkd();
			}
		}
		throw new IllegalStateException(
				"No typical-weekday toll interval for facility=" + facility + ", clock=" + clock);
	}

	private static double loadEnergyRate(Path path) {
		List<Map<String, String>> rows = csv(path);
		return rows.stream().filter(row -> "base".equals(row.get("scenario")))
				.mapToDouble(row -> number(row, "energy_cost_hkd_per_km"))
				.findFirst().orElseThrow(() -> new IllegalStateException("Missing base energy rule: " + path));
	}

	private static Map<Id<Link>, String> loadTollMapping(Path path, Network network) {
		Map<Id<Link>, String> result = new LinkedHashMap<>();
		for (Map<String, String> row : csv(path)) {
			if (!"mapped".equals(row.get("mapping_status"))) {
				continue;
			}
			Id<Link> linkId = Id.createLinkId(row.get("matsim_link_id"));
			if (!network.getLinks().containsKey(linkId)) {
				throw new IllegalStateException("Dynamic toll mapping references missing link " + linkId);
			}
			String previous = result.putIfAbsent(linkId, row.get("canonical_facility_id"));
			if (previous != null && !previous.equals(row.get("canonical_facility_id"))) {
				throw new IllegalStateException("One link maps to multiple toll facilities: " + linkId);
			}
		}
		return result;
	}

	private static Map<String, List<TollRate>> loadTollRates(Path path) {
		Map<String, List<TollRate>> all = new LinkedHashMap<>();
		Map<String, List<TollRate>> weekday = new LinkedHashMap<>();
		for (Map<String, String> row : csv(path)) {
			if (!"private_car".equals(row.get("vehicle_class"))) {
				continue;
			}
			String facility = row.get("toll_facility_id");
			TollRate rate = new TollRate(
					number(row, "start_time_s"), number(row, "end_time_s"), number(row, "toll_hkd"));
			if ("ALL".equals(row.get("day_of_week_code"))) {
				all.computeIfAbsent(facility, ignored -> new ArrayList<>()).add(rate);
			} else if ("A".equals(row.get("day_of_week_code"))) {
				weekday.computeIfAbsent(facility, ignored -> new ArrayList<>()).add(rate);
			}
		}
		Map<String, List<TollRate>> result = new LinkedHashMap<>();
		for (String facility : unionKeys(all, weekday)) {
			List<TollRate> selected = all.containsKey(facility) ? all.get(facility) : weekday.get(facility);
			selected.sort((left, right) -> Double.compare(left.startTimeS(), right.startTimeS()));
			result.put(facility, List.copyOf(selected));
		}
		return result;
	}

	private static Map<ParkingKey, ParkingRule> loadParkingRules(Path path) {
		Map<ParkingKey, ParkingRule> result = new LinkedHashMap<>();
		for (Map<String, String> row : csv(path)) {
			if (!"base".equals(row.get("scenario"))
					|| !"True".equals(row.get("marginal_leg_cost_resolved"))) {
				continue;
			}
			ParkingKey key = new ParkingKey(row.get("zone_group"), row.get("activity_group"));
			ParkingRule rule = new ParkingRule(
					row.get("pricing_method"), optionalNumber(row, "hourly_day_hkd"),
					optionalNumber(row, "hourly_night_hkd"), optionalNumber(row, "daily_cap_hkd"),
					optionalNumber(row, "minimum_charge_hkd"), number(row, "billing_increment_s"),
					number(row, "day_period_start_s"), number(row, "day_period_end_s"));
			if (result.putIfAbsent(key, rule) != null) {
				throw new IllegalStateException("Duplicate base parking rule " + key);
			}
		}
		return result;
	}

	private static void loadDynamicLookups(
			Path parquet,
			Map<String, Integer> zones,
			Map<String, String> vehicleClasses,
			Set<String> missingZoneFacilities) {
		try {
			Class.forName("org.duckdb.DuckDBDriver");
		} catch (ClassNotFoundException error) {
			throw new IllegalStateException("DuckDB JDBC is required for dynamic Car lookup loading.", error);
		}
		String source = parquet.toString().replace("\\", "/").replace("'", "''");
		try (Connection connection = DriverManager.getConnection("jdbc:duckdb:");
			 Statement statement = connection.createStatement()) {
			try (ResultSet rows = statement.executeQuery("""
					SELECT destination_facility_id,
					       MIN(CAST(destination_tcs_zone AS INTEGER)) AS zone,
					       COUNT(DISTINCT destination_tcs_zone) AS variants
					FROM read_parquet('%s')
					WHERE destination_tcs_zone IS NOT NULL
					GROUP BY destination_facility_id
					""".formatted(source))) {
				while (rows.next()) {
					if (rows.getInt("variants") != 1) {
						throw new IllegalStateException("Facility has conflicting TCS zones: " + rows.getString(1));
					}
					zones.put(rows.getString(1), rows.getInt("zone"));
				}
			}
			try (ResultSet rows = statement.executeQuery("""
					SELECT destination_facility_id
					FROM read_parquet('%s')
					GROUP BY destination_facility_id
					HAVING COUNT(destination_tcs_zone) = 0
					""".formatted(source))) {
				while (rows.next()) {
					missingZoneFacilities.add(rows.getString(1));
				}
			}
			try (ResultSet rows = statement.executeQuery("""
					SELECT vehicle_ref_id, MIN(vehicle_class) AS vehicle_class,
					       COUNT(DISTINCT vehicle_class) AS variants
					FROM read_parquet('%s')
					GROUP BY vehicle_ref_id
					""".formatted(source))) {
				while (rows.next()) {
					if (rows.getInt("variants") != 1) {
						throw new IllegalStateException("Vehicle has conflicting classes: " + rows.getString(1));
					}
					vehicleClasses.put(rows.getString(1), rows.getString("vehicle_class"));
				}
			}
		} catch (SQLException error) {
			throw new IllegalStateException("Failed to load dynamic Car facility/vehicle lookups.", error);
		}
	}

	private static void loadParkingZoneRepairs(
			Path path,
			Map<String, Integer> zones,
			Set<String> missingZoneFacilities) {
		Set<String> repaired = new HashSet<>();
		for (Map<String, String> row : csv(path)) {
			String facility = requireText(
					row.get("destination_facility_id"), "destination_facility_id");
			int zone = (int) number(row, "tcs_zone");
			zoneGroup(zone);
			if (!missingZoneFacilities.contains(facility)) {
				throw new IllegalStateException(
						"Dynamic parking zone repair is not an unresolved facility: " + facility);
			}
			if (!"point_within_adopted_study_area_and_dcca_classification".equals(
					row.get("assignment_method"))) {
				throw new IllegalStateException("Unsupported dynamic parking zone repair method.");
			}
			if (zones.putIfAbsent(facility, zone) != null || !repaired.add(facility)) {
				throw new IllegalStateException("Duplicate/conflicting parking zone repair: " + facility);
			}
		}
		if (!repaired.equals(missingZoneFacilities)) {
			Set<String> omitted = new HashSet<>(missingZoneFacilities);
			omitted.removeAll(repaired);
			throw new IllegalStateException(
					"Dynamic parking zone repairs do not cover unresolved facilities: " + omitted);
		}
	}

	private static List<Map<String, String>> csv(Path path) {
		List<String> lines;
		try {
			lines = Files.readAllLines(path, StandardCharsets.UTF_8);
		} catch (IOException error) {
			throw new IllegalStateException("Failed to read dynamic Car rule file " + path, error);
		}
		if (lines.isEmpty()) {
			throw new IllegalStateException("Dynamic Car rule file is empty: " + path);
		}
		List<String> header = csvFields(lines.getFirst());
		List<Map<String, String>> rows = new ArrayList<>();
		for (String line : lines.subList(1, lines.size())) {
			if (line.isBlank()) {
				continue;
			}
			List<String> values = csvFields(line);
			if (values.size() != header.size()) {
				throw new IllegalStateException("Malformed CSV row in " + path);
			}
			Map<String, String> row = new LinkedHashMap<>();
			for (int index = 0; index < header.size(); index++) {
				row.put(header.get(index), values.get(index));
			}
			rows.add(row);
		}
		return rows;
	}

	private static List<String> csvFields(String line) {
		List<String> fields = new ArrayList<>();
		StringBuilder field = new StringBuilder();
		boolean quoted = false;
		for (int index = 0; index < line.length(); index++) {
			char value = line.charAt(index);
			if (value == '"') {
				if (quoted && index + 1 < line.length() && line.charAt(index + 1) == '"') {
					field.append('"');
					index++;
				} else {
					quoted = !quoted;
				}
			} else if (value == ',' && !quoted) {
				fields.add(field.toString());
				field.setLength(0);
			} else {
				field.append(value);
			}
		}
		if (quoted) {
			throw new IllegalStateException("Unterminated quoted CSV field.");
		}
		fields.add(field.toString());
		return fields;
	}

	private static double number(Map<String, String> row, String column) {
		String value = row.get(column);
		if (value == null || value.isBlank()) {
			throw new IllegalStateException("Missing numeric rule column " + column);
		}
		return Double.parseDouble(value);
	}

	private static double optionalNumber(Map<String, String> row, String column) {
		String value = row.get(column);
		return value == null || value.isBlank() ? 0.0 : Double.parseDouble(value);
	}

	private static List<String> unionKeys(
			Map<String, ?> left, Map<String, ?> right) {
		List<String> result = new ArrayList<>(left.keySet());
		for (String key : right.keySet()) {
			if (!result.contains(key)) {
				result.add(key);
			}
		}
		return result;
	}

	private static String activityGroup(String activityType) {
		String value = requireText(activityType, "activityType");
		if ("home".equals(value)) return "home";
		if (List.of("work", "work_mobile", "business").contains(value)) return "work";
		if (value.startsWith("school") || value.startsWith("education")) return "education";
		if ("shopping".equals(value)) return "shopping";
		if (List.of("dining", "leisure", "social", "vfr", "primary_activity", "secondary_activity")
				.contains(value)) return "leisure";
		if (List.of("medical", "personal_business").contains(value)) return "medical_personal_business";
		if ("accommodation".equals(value)) return "visitor_accommodation";
		if (List.of("border", "external_activity").contains(value)) return "border";
		return "other";
	}

	private static String zoneGroup(int zone) {
		if (zone >= 1 && zone <= 4) return "hong_kong_island";
		if (zone >= 5 && zone <= 13) return "kowloon_urban";
		if (zone >= 14 && zone <= 26) return "new_territories_lantau";
		throw new IllegalArgumentException("Unsupported TCS zone " + zone);
	}

	private static double moduloDay(double timeS) {
		double value = timeS % 86_400.0;
		return value < 0.0 ? value + 86_400.0 : value;
	}

	private static String requireText(String value, String label) {
		String result = Objects.requireNonNull(value, label).strip();
		if (result.isBlank()) {
			throw new IllegalArgumentException(label + " must not be blank.");
		}
		return result;
	}

	private static boolean finiteNonnegative(double value) {
		return Double.isFinite(value) && value >= 0.0;
	}
}
