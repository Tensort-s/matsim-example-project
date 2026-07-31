package org.matsim.project.hongkong.car;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.TreeMap;

/**
 * Immutable lookup for hash-locked, base-scenario destination parking.
 *
 * <p>Only canonical resolved destination records can carry a value. Known
 * unresolved records retain a null value and their source reason; motorcycles
 * remain out of scope. No location, distance, nearest-facility, or tariff
 * inference is performed at runtime.</p>
 */
public final class HongKongCarParkingCostCatalog {

	public static final String COMPONENT_ID = "destination_parking";
	public static final String SCENARIO = "base";

	private static final String CANONICAL_MANIFEST_PATH =
			"canonical_car_cost_interface_manifest.json";
	private static final String COMPONENT_TABLE_PATH =
			"unified_marginal_cost_interface_v1/"
					+ "car_leg_marginal_cost_components_base.parquet";
	private static final String COMPONENT_REGISTRY_PATH =
			"unified_marginal_cost_interface_v1/"
					+ "marginal_cost_component_registry.csv";
	private static final String PARKING_CANDIDATE_RELATIVE_PATH =
			"parking_event_application_v1/"
					+ "car_leg_parking_cost_estimates_base.parquet";
	private static final String PARKING_RULES_RELATIVE_PATH =
			"parking_event_application_v1/"
					+ "parking_cost_rules_repository_relative.csv";
	private static final String PARKING_EVENTS_RELATIVE_PATH =
			"parking_event_application_v1/car_parking_events.parquet";
	private static final String SOURCE_CANDIDATE_PATH =
			"data/transport_costs/hongkong/car_cost_v1/"
					+ PARKING_CANDIDATE_RELATIVE_PATH;
	private static final String SOURCE_RULES_PATH =
			"data/transport_costs/hongkong/car_cost_v1/"
					+ PARKING_RULES_RELATIVE_PATH;
	private static final String EXPECTED_COST_QUALITY =
			"official_rate_bounded_zone_activity_proxy";
	private static final double TIME_TOLERANCE_S = 1.0e-6;

	private static final Map<String, String> EXPECTED_SHA256 = Map.of(
			CANONICAL_MANIFEST_PATH,
			"515d15df43a269da5f060338fcaf91cf004abfeb98ee4332e4172964f64be31d",
			COMPONENT_TABLE_PATH,
			"0337469ca99d61650f782f273b7b275cee124449e01037f95e15f978f94e742b",
			COMPONENT_REGISTRY_PATH,
			"ae2fd61342413b586aef1149f5221db0ffa04d994e1b415d6c7bccf077855580",
			PARKING_CANDIDATE_RELATIVE_PATH,
			"c2270353c3276691a7a55c77d2576b228ab68ed3c935b64f68419299f438b753",
			PARKING_RULES_RELATIVE_PATH,
			"e1decd3b9d07f8c13cb9f3d5494b6b6fd61887348bc3ddac53918f758b79d8fa",
			PARKING_EVENTS_RELATIVE_PATH,
			"c69b9941769a72e7a015be6d6dc8c673a013ea85794d1601b95cb3110317445e");

	public enum Resolution {
		RESOLVED_CHARGE,
		RESOLVED_LEGAL_ZERO,
		UNRESOLVED,
		OUT_OF_SCOPE
	}

	public record ParkingQuote(
			String personId,
			int legSequence,
			String vehicleRefId,
			String vehicleClass,
			String parkingEventKey,
			String destinationFacilityId,
			Integer destinationTcsZone,
			String destinationZoneGroup,
			String destinationActivityType,
			String destinationActivityGroup,
			double departureTimeS,
			double routeTravelTimeS,
			double arrivalTimeS,
			String nextDeparturePersonId,
			Integer nextDepartureLegSequence,
			String nextDepartureVehicleRefId,
			String nextDepartureFacilityId,
			Double nextDepartureTimeS,
			Double parkingDurationS,
			String vehicleChainStatus,
			boolean vehicleChainTimeOverlap,
			boolean nextDepartureFacilityMismatch,
			boolean terminalEvent,
			String parkingStatus,
			String pricingMethod,
			int billingUnitCount,
			Double costHkd,
			String costSource,
			String costEffectiveDate,
			String costQuality,
			String sourceSnapshotSha256,
			String sourceCandidatePath,
			String sourceCandidateSha256,
			double sourceRouteDistanceM,
			boolean fixedVehicleOwnershipCostIncluded,
			Resolution resolution,
			String unresolvedReason) {

		public ParkingQuote {
			personId = requireText(personId, "personId");
			if (legSequence < 0 || billingUnitCount < 0) {
				throw new IllegalArgumentException(
						"Parking leg sequence and billing units must be nonnegative.");
			}
			vehicleRefId = requireText(vehicleRefId, "vehicleRefId");
			vehicleClass = requireText(vehicleClass, "vehicleClass");
			parkingEventKey = requireText(parkingEventKey, "parkingEventKey");
			destinationFacilityId = requireText(
					destinationFacilityId, "destinationFacilityId");
			destinationZoneGroup = clean(destinationZoneGroup);
			destinationActivityType = requireText(
					destinationActivityType, "destinationActivityType");
			destinationActivityGroup = requireText(
					destinationActivityGroup, "destinationActivityGroup");
			if (!finiteNonnegative(departureTimeS)
					|| !finiteNonnegative(routeTravelTimeS)
					|| !finiteNonnegative(arrivalTimeS)
					|| Math.abs(departureTimeS + routeTravelTimeS - arrivalTimeS)
					> TIME_TOLERANCE_S
					|| !finiteNonnegative(sourceRouteDistanceM)) {
				throw new IllegalArgumentException(
						"Parking source timing and route values must be finite and consistent.");
			}
			nextDeparturePersonId = clean(nextDeparturePersonId);
			nextDepartureVehicleRefId = clean(nextDepartureVehicleRefId);
			nextDepartureFacilityId = clean(nextDepartureFacilityId);
			validateNullableNonnegative(nextDepartureTimeS, "nextDepartureTimeS");
			validateNullableNonnegative(parkingDurationS, "parkingDurationS");
			vehicleChainStatus = requireText(
					vehicleChainStatus, "vehicleChainStatus");
			parkingStatus = requireText(parkingStatus, "parkingStatus");
			pricingMethod = clean(pricingMethod);
			costSource = clean(costSource);
			costEffectiveDate = clean(costEffectiveDate);
			costQuality = requireText(costQuality, "costQuality");
			sourceSnapshotSha256 = requireText(
					sourceSnapshotSha256, "sourceSnapshotSha256");
			sourceCandidatePath = requireText(
					sourceCandidatePath, "sourceCandidatePath");
			sourceCandidateSha256 = requireText(
					sourceCandidateSha256, "sourceCandidateSha256");
			resolution = Objects.requireNonNull(resolution, "resolution");
			unresolvedReason = clean(unresolvedReason);
			if (fixedVehicleOwnershipCostIncluded) {
				throw new IllegalArgumentException(
						"Fixed ownership cannot appear in a parking leg record.");
			}
			switch (resolution) {
				case RESOLVED_CHARGE -> {
					if (!"private_car".equals(vehicleClass)
							|| costHkd == null
							|| !Double.isFinite(costHkd)
							|| costHkd <= 0.0
							|| !"resolved_proxy_charge".equals(parkingStatus)
							|| !EXPECTED_COST_QUALITY.equals(costQuality)
							|| pricingMethod.isBlank()
							|| !SOURCE_RULES_PATH.equals(costSource)
							|| costEffectiveDate.isBlank()
							|| destinationTcsZone == null
							|| vehicleChainTimeOverlap
							|| nextDepartureFacilityMismatch
							|| !unresolvedReason.isBlank()) {
						throw new IllegalArgumentException(
								"Resolved destination parking charge contract failed.");
					}
				}
				case RESOLVED_LEGAL_ZERO -> {
					if (!"private_car".equals(vehicleClass)
							|| costHkd == null
							|| Double.doubleToLongBits(costHkd)
							!= Double.doubleToLongBits(0.0)
							|| !"resolved_home_marginal_zero_fixed_separate"
							.equals(parkingStatus)
							|| !"home".equals(destinationActivityGroup)
							|| !EXPECTED_COST_QUALITY.equals(costQuality)
							|| pricingMethod.isBlank()
							|| !SOURCE_RULES_PATH.equals(costSource)
							|| costEffectiveDate.isBlank()
							|| vehicleChainTimeOverlap
							|| nextDepartureFacilityMismatch
							|| !unresolvedReason.isBlank()) {
						throw new IllegalArgumentException(
								"Resolved home marginal parking zero contract failed.");
					}
				}
				case UNRESOLVED -> {
					if (!"private_car".equals(vehicleClass)
							|| costHkd != null
							|| !parkingStatus.startsWith("unresolved_")
							|| !"unresolved".equals(costQuality)
							|| unresolvedReason.isBlank()) {
						throw new IllegalArgumentException(
								"Unresolved destination parking must remain null with a reason.");
					}
				}
				case OUT_OF_SCOPE -> {
					if (!"motorcycle".equals(vehicleClass)
							|| costHkd != null
							|| !"out_of_scope_motorcycle".equals(parkingStatus)
							|| !"unresolved".equals(costQuality)
							|| unresolvedReason.isBlank()) {
						throw new IllegalArgumentException(
								"Motorcycle parking exclusion contract failed.");
					}
				}
			}
		}

		public boolean resolved() {
			return resolution == Resolution.RESOLVED_CHARGE
					|| resolution == Resolution.RESOLVED_LEGAL_ZERO;
		}

		public boolean chargeable() {
			return resolution == Resolution.RESOLVED_CHARGE;
		}

		public boolean outOfScope() {
			return resolution == Resolution.OUT_OF_SCOPE;
		}
	}

	public record CatalogAudit(
			long parkingRows,
			long resolvedChargeRows,
			long resolvedLegalZeroRows,
			long unresolvedRows,
			long motorcycleOutOfScopeRows,
			long unresolvedTimeOverlapRows,
			long unresolvedFacilityMismatchRows,
			long unresolvedMissingZoneRows,
			long unresolvedTerminalNonHomeRows,
			double resolvedCostTotalHkd,
			double resolvedMeanHkd,
			double resolvedMedianHkd,
			double resolvedP90Hkd,
			double resolvedMaxHkd,
			Map<String, String> sourceSha256,
			long nearestLocationInferenceRows,
			long facilityCandidateFallbackRows,
			long distanceInferenceRows,
			long fixedOwnershipLegRows) {

		public CatalogAudit {
			if (parkingRows < 0 || resolvedChargeRows < 0
					|| resolvedLegalZeroRows < 0 || unresolvedRows < 0
					|| motorcycleOutOfScopeRows < 0
					|| unresolvedTimeOverlapRows < 0
					|| unresolvedFacilityMismatchRows < 0
					|| unresolvedMissingZoneRows < 0
					|| unresolvedTerminalNonHomeRows < 0
					|| !finiteNonnegative(resolvedCostTotalHkd)
					|| !finiteNonnegative(resolvedMeanHkd)
					|| !finiteNonnegative(resolvedMedianHkd)
					|| !finiteNonnegative(resolvedP90Hkd)
					|| !finiteNonnegative(resolvedMaxHkd)
					|| nearestLocationInferenceRows != 0
					|| facilityCandidateFallbackRows != 0
					|| distanceInferenceRows != 0
					|| fixedOwnershipLegRows != 0) {
				throw new IllegalArgumentException(
						"Canonical destination-parking audit contract failed.");
			}
			sourceSha256 = Collections.unmodifiableMap(
					new TreeMap<>(sourceSha256));
		}
	}

	private final Map<PersonLegKey, ParkingQuote> quotes;
	private final CatalogAudit audit;

	private HongKongCarParkingCostCatalog(
			Map<PersonLegKey, ParkingQuote> quotes,
			CatalogAudit audit) {
		this.quotes = Collections.unmodifiableMap(new LinkedHashMap<>(quotes));
		this.audit = Objects.requireNonNull(audit, "audit");
	}

	public static HongKongCarParkingCostCatalog load(Path carCostRoot) {
		Path root = Objects.requireNonNull(carCostRoot, "carCostRoot")
				.toAbsolutePath().normalize();
		Map<String, String> hashes = verifySources(root);
		verifyRegistry(root.resolve(COMPONENT_REGISTRY_PATH));
		return loadTables(root, hashes);
	}

	public ParkingQuote quote(String personId, int legSequence) {
		PersonLegKey key = new PersonLegKey(
				requireText(personId, "personId"), legSequence);
		ParkingQuote quote = quotes.get(key);
		if (quote == null) {
			throw new IllegalStateException(
					"Canonical destination-parking key is missing: " + key);
		}
		return quote;
	}

	public CatalogAudit audit() {
		return audit;
	}

	static Builder builder() {
		return new Builder();
	}

	static final class Builder {
		private final Map<PersonLegKey, ParkingQuote> quotes =
				new LinkedHashMap<>();

		Builder quote(ParkingQuote quote) {
			Objects.requireNonNull(quote, "quote");
			PersonLegKey key = new PersonLegKey(
					quote.personId(), quote.legSequence());
			if (quotes.putIfAbsent(key, quote) != null) {
				throw new IllegalStateException(
						"Duplicate canonical Car parking key: " + key);
			}
			return this;
		}

		HongKongCarParkingCostCatalog buildForTests() {
			return new HongKongCarParkingCostCatalog(
					quotes, audit(quotes, EXPECTED_SHA256, false));
		}
	}

	private static HongKongCarParkingCostCatalog loadTables(
			Path root,
			Map<String, String> hashes) {
		try {
			Class.forName("org.duckdb.DuckDBDriver");
		} catch (ClassNotFoundException error) {
			throw new IllegalStateException(
					"DuckDB JDBC is required for canonical Car parking loading.",
					error);
		}
		Path componentTable = root.resolve(COMPONENT_TABLE_PATH);
		Path candidateTable = root.resolve(PARKING_CANDIDATE_RELATIVE_PATH);
		Map<PersonLegKey, ParkingQuote> quotes = new LinkedHashMap<>();
		String sql = "SELECT c.person_id, c.leg_sequence, c.mode, "
				+ "c.vehicle_ref_id, c.vehicle_class, c.scenario, "
				+ "c.cost_hkd AS component_cost_hkd, "
				+ "c.cost_status AS component_cost_status, "
				+ "c.cost_source AS component_cost_source, "
				+ "c.cost_effective_date AS component_effective_date, "
				+ "c.cost_quality AS component_quality, "
				+ "c.source_snapshot_sha256 AS component_snapshot_sha256, "
				+ "c.unresolved_reason AS component_unresolved_reason, "
				+ "c.source_candidate_path, c.source_candidate_sha256, "
				+ "c.route_distance_m, c.record_scope, c.cost_nature, "
				+ "c.incremental_if_car_leg_chosen, "
				+ "c.behavioral_inclusion_current_model, "
				+ "c.fixed_vehicle_ownership_cost_included, "
				+ "p.parking_event_key, p.destination_facility_id, "
				+ "p.destination_tcs_zone, p.destination_zone_group, "
				+ "p.destination_activity_type, p.destination_activity_group, "
				+ "p.departure_time_s, p.route_travel_time_s, p.arrival_time_s, "
				+ "p.next_departure_person_id, p.next_departure_leg_sequence, "
				+ "p.next_departure_vehicle_ref_id, "
				+ "p.next_departure_facility_id, p.next_departure_time_s, "
				+ "p.parking_duration_s, p.vehicle_chain_status, "
				+ "p.vehicle_chain_time_overlap, "
				+ "p.next_departure_facility_mismatch, p.terminal_event, "
				+ "p.parking_status, p.pricing_method, p.billing_unit_count, "
				+ "p.cost_hkd AS candidate_cost_hkd, "
				+ "p.cost_source AS candidate_cost_source, "
				+ "p.cost_effective_date AS candidate_effective_date, "
				+ "p.cost_quality AS candidate_quality, "
				+ "p.unresolved_reason AS candidate_unresolved_reason "
				+ "FROM read_parquet('" + sqlLiteral(componentTable) + "') c "
				+ "JOIN read_parquet('" + sqlLiteral(candidateTable) + "') p "
				+ "USING (person_id, leg_sequence) "
				+ "WHERE c.cost_component = 'destination_parking'";
		try (Connection connection = DriverManager.getConnection("jdbc:duckdb:");
			 Statement statement = connection.createStatement();
			 ResultSet row = statement.executeQuery(sql)) {
			while (row.next()) {
				ParkingQuote quote = readQuote(row);
				PersonLegKey key = new PersonLegKey(
						quote.personId(), quote.legSequence());
				if (quotes.putIfAbsent(key, quote) != null) {
					throw new IllegalStateException(
							"Duplicate canonical Car parking key: " + key);
				}
			}
		} catch (SQLException error) {
			throw new IllegalStateException(
					"Failed to load canonical destination parking.", error);
		}
		CatalogAudit audit = audit(quotes, hashes, true);
		return new HongKongCarParkingCostCatalog(quotes, audit);
	}

	private static ParkingQuote readQuote(ResultSet row) throws SQLException {
		String personId = row.getString("person_id");
		int legSequence = row.getInt("leg_sequence");
		String componentStatus = row.getString("component_cost_status");
		if (!"car".equals(row.getString("mode"))
				|| !SCENARIO.equals(row.getString("scenario"))
				|| !"leg_marginal_cost_component".equals(
						row.getString("record_scope"))
				|| !"trip_conditional_marginal_cost".equals(
						row.getString("cost_nature"))
				|| !row.getBoolean("incremental_if_car_leg_chosen")
				|| row.getBoolean("behavioral_inclusion_current_model")
				!= componentStatus.startsWith("resolved_")
				|| row.getBoolean("fixed_vehicle_ownership_cost_included")
				|| !SOURCE_CANDIDATE_PATH.equals(
						row.getString("source_candidate_path"))
				|| !EXPECTED_SHA256.get(PARKING_CANDIDATE_RELATIVE_PATH)
				.equals(row.getString("source_candidate_sha256"))) {
			throw new IllegalStateException(
					"Canonical destination-parking component metadata mismatch: person="
							+ personId + ", leg_sequence=" + legSequence);
		}
		Double componentCost = nullableDouble(row, "component_cost_hkd");
		Double candidateCost = nullableDouble(row, "candidate_cost_hkd");
		if (!nullableDoubleEquals(componentCost, candidateCost)
				|| !Objects.equals(row.getString("component_cost_status"),
						row.getString("parking_status"))
				|| !Objects.equals(row.getString("component_cost_source"),
						row.getString("candidate_cost_source"))
				|| !Objects.equals(row.getString("component_effective_date"),
						row.getString("candidate_effective_date"))
				|| !Objects.equals(row.getString("component_quality"),
						row.getString("candidate_quality"))
				|| !Objects.equals(row.getString("component_unresolved_reason"),
						row.getString("candidate_unresolved_reason"))) {
			throw new IllegalStateException(
					"Canonical and source-candidate parking rows differ: person="
							+ personId + ", leg_sequence=" + legSequence);
		}
		String status = row.getString("parking_status");
		String vehicleClass = row.getString("vehicle_class");
		Resolution resolution = resolution(status, vehicleClass);
		return new ParkingQuote(
				personId,
				legSequence,
				row.getString("vehicle_ref_id"),
				vehicleClass,
				row.getString("parking_event_key"),
				row.getString("destination_facility_id"),
				nullableInteger(row, "destination_tcs_zone"),
				row.getString("destination_zone_group"),
				row.getString("destination_activity_type"),
				row.getString("destination_activity_group"),
				row.getDouble("departure_time_s"),
				row.getDouble("route_travel_time_s"),
				row.getDouble("arrival_time_s"),
				row.getString("next_departure_person_id"),
				nullableInteger(row, "next_departure_leg_sequence"),
				row.getString("next_departure_vehicle_ref_id"),
				row.getString("next_departure_facility_id"),
				nullableDouble(row, "next_departure_time_s"),
				nullableDouble(row, "parking_duration_s"),
				row.getString("vehicle_chain_status"),
				row.getBoolean("vehicle_chain_time_overlap"),
				row.getBoolean("next_departure_facility_mismatch"),
				row.getBoolean("terminal_event"),
				status,
				row.getString("pricing_method"),
				row.getInt("billing_unit_count"),
				componentCost,
				row.getString("component_cost_source"),
				row.getString("component_effective_date"),
				row.getString("component_quality"),
				row.getString("component_snapshot_sha256"),
				row.getString("source_candidate_path"),
				row.getString("source_candidate_sha256"),
				row.getDouble("route_distance_m"),
				row.getBoolean("fixed_vehicle_ownership_cost_included"),
				resolution,
				row.getString("component_unresolved_reason"));
	}

	private static Resolution resolution(String status, String vehicleClass) {
		if ("resolved_proxy_charge".equals(status)) {
			return Resolution.RESOLVED_CHARGE;
		}
		if ("resolved_home_marginal_zero_fixed_separate".equals(status)) {
			return Resolution.RESOLVED_LEGAL_ZERO;
		}
		if (status != null && status.startsWith("unresolved_")) {
			return Resolution.UNRESOLVED;
		}
		if ("motorcycle".equals(vehicleClass)
				&& "out_of_scope_motorcycle".equals(status)) {
			return Resolution.OUT_OF_SCOPE;
		}
		throw new IllegalStateException(
				"Unsupported canonical destination-parking status: " + status);
	}

	private static CatalogAudit audit(
			Map<PersonLegKey, ParkingQuote> quotes,
			Map<String, String> hashes,
			boolean enforceCanonicalCounts) {
		long charge = count(quotes, Resolution.RESOLVED_CHARGE);
		long zero = count(quotes, Resolution.RESOLVED_LEGAL_ZERO);
		long unresolved = count(quotes, Resolution.UNRESOLVED);
		long motorcycle = count(quotes, Resolution.OUT_OF_SCOPE);
		long overlap = quotes.values().stream().filter(quote ->
				"unresolved_vehicle_time_overlap".equals(
						quote.parkingStatus())).count();
		long mismatch = quotes.values().stream().filter(quote ->
				"unresolved_next_departure_facility_mismatch".equals(
						quote.parkingStatus())).count();
		long missingZone = quotes.values().stream().filter(quote ->
				"unresolved_missing_destination_zone".equals(
						quote.parkingStatus())).count();
		long terminal = quotes.values().stream().filter(quote ->
				"unresolved_missing_next_departure_non_home".equals(
						quote.parkingStatus())).count();
		List<Double> resolvedValues = quotes.values().stream()
				.filter(ParkingQuote::resolved)
				.map(ParkingQuote::costHkd)
				.sorted()
				.toList();
		double total = resolvedValues.stream().mapToDouble(Double::doubleValue)
				.sum();
		double mean = resolvedValues.isEmpty()
				? 0.0 : total / resolvedValues.size();
		double median = quantile(resolvedValues, 0.5);
		double p90 = quantile(resolvedValues, 0.9);
		double max = resolvedValues.isEmpty()
				? 0.0 : resolvedValues.getLast();
		if (enforceCanonicalCounts
				&& (quotes.size() != 67_718
				|| charge != 35_564
				|| zero != 28_390
				|| unresolved != 835
				|| motorcycle != 2_929
				|| overlap != 466
				|| mismatch != 269
				|| missingZone != 98
				|| terminal != 2
				|| Double.doubleToLongBits(total)
				!= Double.doubleToLongBits(2_624_827.0)
				|| Math.abs(mean - 41.04242111517653) > 1.0e-12
				|| median != 32.0 || p90 != 110.0 || max != 210.0)) {
			throw new IllegalStateException(
					"Canonical base destination-parking counts or distributions drifted.");
		}
		return new CatalogAudit(
				quotes.size(), charge, zero, unresolved, motorcycle,
				overlap, mismatch, missingZone, terminal,
				total, mean, median, p90, max, hashes,
				0L, 0L, 0L, 0L);
	}

	private static long count(
			Map<PersonLegKey, ParkingQuote> quotes,
			Resolution resolution) {
		return quotes.values().stream()
				.filter(quote -> quote.resolution() == resolution).count();
	}

	private static double quantile(List<Double> sorted, double probability) {
		if (sorted.isEmpty()) {
			return 0.0;
		}
		double index = probability * (sorted.size() - 1);
		int lower = (int) Math.floor(index);
		int upper = (int) Math.ceil(index);
		if (lower == upper) {
			return sorted.get(lower);
		}
		double fraction = index - lower;
		return sorted.get(lower)
				+ fraction * (sorted.get(upper) - sorted.get(lower));
	}

	private static Map<String, String> verifySources(Path root) {
		Map<String, String> actual = new LinkedHashMap<>();
		for (Map.Entry<String, String> entry : EXPECTED_SHA256.entrySet()) {
			Path path = root.resolve(entry.getKey()).normalize();
			if (!Files.isRegularFile(path)) {
				throw new IllegalArgumentException(
						"Canonical Car parking source is missing: " + path);
			}
			String hash = sha256(path);
			if (!entry.getValue().equals(hash)) {
				throw new IllegalStateException(
						"Canonical Car parking source SHA-256 mismatch: path="
								+ path + ", expected=" + entry.getValue()
								+ ", actual=" + hash);
			}
			actual.put(entry.getKey(), hash);
		}
		return actual;
	}

	private static void verifyRegistry(Path registry) {
		List<String> lines;
		try {
			lines = Files.readAllLines(registry, StandardCharsets.UTF_8);
		} catch (IOException error) {
			throw new IllegalStateException(
					"Failed to read canonical Car component registry.", error);
		}
		if (lines.size() != 5) {
			throw new IllegalStateException(
					"Canonical Car component registry must contain four rows.");
		}
		String[] header = lines.getFirst().split(",", -1);
		Map<String, Integer> columns = new LinkedHashMap<>();
		for (int index = 0; index < header.length; index++) {
			columns.put(header[index], index);
		}
		String[] parking = null;
		String[] fixed = null;
		for (String line : lines.subList(1, lines.size())) {
			String[] values = line.split(",", -1);
			String component = value(values, columns, "cost_component");
			if (COMPONENT_ID.equals(component)) {
				parking = values;
			} else if ("fixed_vehicle_ownership_cost".equals(component)) {
				fixed = values;
			}
		}
		if (parking == null
				|| !"True".equals(value(parking, columns,
						"behavioral_inclusion_current_model"))
				|| !"True".equals(value(parking, columns,
						"incremental_if_car_leg_chosen"))
				|| fixed == null
				|| !"False".equals(value(fixed, columns,
						"behavioral_inclusion_current_model"))) {
			throw new IllegalStateException(
					"Canonical parking/fixed registry contract failed.");
		}
	}

	private static String value(
			String[] values,
			Map<String, Integer> columns,
			String name) {
		Integer index = columns.get(name);
		if (index == null || index >= values.length) {
			throw new IllegalStateException(
					"Canonical Car registry column is missing: " + name);
		}
		return values[index];
	}

	private static Double nullableDouble(ResultSet row, String column)
			throws SQLException {
		double value = row.getDouble(column);
		return row.wasNull() ? null : value;
	}

	private static Integer nullableInteger(ResultSet row, String column)
			throws SQLException {
		int value = row.getInt(column);
		return row.wasNull() ? null : value;
	}

	private static boolean nullableDoubleEquals(Double left, Double right) {
		if (left == null || right == null) {
			return left == right;
		}
		return Double.doubleToLongBits(left) == Double.doubleToLongBits(right);
	}

	private static String sqlLiteral(Path path) {
		return path.toString().replace("\\", "/").replace("'", "''");
	}

	private static String sha256(Path path) {
		try {
			MessageDigest digest = MessageDigest.getInstance("SHA-256");
			try (var input = Files.newInputStream(path)) {
				byte[] buffer = new byte[1 << 20];
				int read;
				while ((read = input.read(buffer)) >= 0) {
					if (read > 0) {
						digest.update(buffer, 0, read);
					}
				}
			}
			return java.util.HexFormat.of().formatHex(digest.digest());
		} catch (NoSuchAlgorithmException error) {
			throw new IllegalStateException("SHA-256 is unavailable.", error);
		} catch (IOException error) {
			throw new IllegalStateException(
					"Failed to hash canonical Car parking source: " + path,
					error);
		}
	}

	private static void validateNullableNonnegative(
			Double value,
			String label) {
		if (value != null && !finiteNonnegative(value)) {
			throw new IllegalArgumentException(
					label + " must be null or finite and nonnegative.");
		}
	}

	private static boolean finiteNonnegative(double value) {
		return Double.isFinite(value) && value >= 0.0;
	}

	private static String requireText(String value, String label) {
		String cleaned = Objects.requireNonNull(value, label).strip();
		if (cleaned.isBlank()) {
			throw new IllegalArgumentException(label + " must not be blank.");
		}
		return cleaned;
	}

	private static String clean(String value) {
		return value == null ? "" : value.strip();
	}

	private record PersonLegKey(String personId, int legSequence) {
		private PersonLegKey {
			personId = requireText(personId, "personId");
			if (legSequence < 0) {
				throw new IllegalArgumentException(
						"legSequence must be nonnegative.");
			}
		}
	}
}
