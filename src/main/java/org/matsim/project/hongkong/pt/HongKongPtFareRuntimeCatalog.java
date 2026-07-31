package org.matsim.project.hongkong.pt;

import org.matsim.api.core.v01.Id;
import org.matsim.pt.routes.TransitPassengerRoute;
import org.matsim.pt.transitSchedule.api.TransitLine;
import org.matsim.pt.transitSchedule.api.TransitRoute;
import org.matsim.pt.transitSchedule.api.TransitSchedule;
import org.matsim.pt.transitSchedule.api.TransitStopFacility;

import java.io.BufferedReader;
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
import java.util.ArrayList;
import java.util.Collections;
import java.util.EnumMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.TreeMap;

/**
 * Immutable runtime lookup over the five strict canonical Hong Kong PT fare
 * layers.
 *
 * <p>The catalog reads the locked Parquet tables directly, verifies their
 * SHA-256 identities, and uses only exact schedule-facility crosswalks. It
 * never uses distance, reverse lookup, path sums, nearest neighbours, route
 * full-fare references, the Bus simulation candidate layer, or a numeric
 * replacement for an unresolved fare.</p>
 */
public final class HongKongPtFareRuntimeCatalog {

	public static final Path DEFAULT_RELEASE_ROOT = Path.of(
			"data", "transport_costs", "hongkong", "pt_fare_v1");

	public enum Layer {
		MTR_DOMESTIC("mtr_domestic_station_od_v1", "train"),
		LIGHT_RAIL("light_rail_station_od_v1", "light_rail"),
		GMB("gmb_fare_v1", "gmb"),
		FERRY("ferry_fare_v1", "ferry"),
		BUS_CORE("bus_fare_v1", "bus");

		private final String layerId;
		private final String actualMode;

		Layer(String layerId, String actualMode) {
			this.layerId = layerId;
			this.actualMode = actualMode;
		}

		public String layerId() {
			return layerId;
		}

		public String actualMode() {
			return actualMode;
		}

		static Layer forActualMode(String actualMode) {
			for (Layer layer : values()) {
				if (layer.actualMode.equals(actualMode)) {
					return layer;
				}
			}
			return null;
		}
	}

	public record FareQuote(
			Layer layer,
			String actualMode,
			String matsimLineId,
			String matsimRouteId,
			String boardingFacilityId,
			String alightingFacilityId,
			String boardingOfficialId,
			String alightingOfficialId,
			Double costHkd,
			String costQuality,
			String mappingStatus,
			String costApplicabilityStatus,
			String costSource,
			String sourceRecordId,
			String sourcePath,
			String sourceSha256,
			String matchingMethod,
			String unresolvedReason) {

		public FareQuote {
			Objects.requireNonNull(layer, "layer");
			actualMode = requireText(actualMode, "actualMode");
			matsimLineId = requireText(matsimLineId, "matsimLineId");
			matsimRouteId = requireText(matsimRouteId, "matsimRouteId");
			boardingFacilityId =
					requireText(boardingFacilityId, "boardingFacilityId");
			alightingFacilityId =
					requireText(alightingFacilityId, "alightingFacilityId");
			boardingOfficialId = clean(boardingOfficialId);
			alightingOfficialId = clean(alightingOfficialId);
			costQuality = requireText(costQuality, "costQuality");
			mappingStatus = requireText(mappingStatus, "mappingStatus");
			costApplicabilityStatus = clean(costApplicabilityStatus);
			costSource = clean(costSource);
			sourceRecordId = clean(sourceRecordId);
			sourcePath = requireText(sourcePath, "sourcePath");
			sourceSha256 = requireText(sourceSha256, "sourceSha256");
			matchingMethod = clean(matchingMethod);
			unresolvedReason = clean(unresolvedReason);
			if (costHkd != null
					&& (!Double.isFinite(costHkd) || costHkd < 0.0)) {
				throw new IllegalArgumentException(
						"PT fare must be finite and nonnegative.");
			}
			if (costHkd == null && unresolvedReason.isBlank()) {
				throw new IllegalArgumentException(
						"Unresolved PT fare requires an explicit reason.");
			}
			if (costHkd != null && !unresolvedReason.isBlank()) {
				throw new IllegalArgumentException(
						"Resolved PT fare cannot carry an unresolved reason.");
			}
		}

		public boolean resolved() {
			return costHkd != null;
		}

		public Double transferConcessionHkd() {
			return null;
		}

		public String transferConcessionStatus() {
			return "not_modelled";
		}
	}

	public record CatalogAudit(
			Map<String, Long> ruleCounts,
			Map<String, Long> exactFacilityMappingCounts,
			Map<String, String> sourceSha256,
			List<String> activeLayerIds,
			List<String> prohibitedFallbacks) {

		public CatalogAudit {
			ruleCounts = Collections.unmodifiableMap(
					new TreeMap<>(ruleCounts));
			exactFacilityMappingCounts = Collections.unmodifiableMap(
					new TreeMap<>(exactFacilityMappingCounts));
			sourceSha256 = Collections.unmodifiableMap(
					new TreeMap<>(sourceSha256));
			activeLayerIds = List.copyOf(activeLayerIds);
			prohibitedFallbacks = List.copyOf(prohibitedFallbacks);
		}
	}

	private static final List<String> PROHIBITED_FALLBACKS = List.of(
			"distance_median",
			"cross_mode_aggregation",
			"nearest_neighbor",
			"reverse_lookup",
			"path_sum",
			"route_fullFare_substitution",
			"bus_simulation_candidate",
			"unresolved_to_zero");

	private static final Map<String, String> EXPECTED_SHA256 = Map.ofEntries(
			Map.entry(
					"mtr_station_od_v1/mtr_station_od_fare_rules.parquet",
					"0829574983542c8178a562463d1711f93fe8381dfda7a7ad88bb7a8c7c2701fa"),
			Map.entry(
					"mtr_station_od_v1/mtr_station_crosswalk.csv",
					"f566103c1529f18fe39f92e41601a1e77ba00e4b77d35fb5a5b8ff77ecaf7926"),
			Map.entry(
					"light_rail_station_od_v1/light_rail_station_od_fare_rules.parquet",
					"92596e56342eeffe5374aa4ed7dba9a5b57986ab3257623e64e04cb837a64004"),
			Map.entry(
					"light_rail_station_od_v1/light_rail_stop_crosswalk.csv",
					"448f921cd1eac9338f883ef3f3d94ce2f04047ca3687f15a712d70b86e905942"),
			Map.entry(
					"gmb_fare_v1/gmb_fare_rules.parquet",
					"edc794e0940985b64056041e1449d26a8bc3d3331f37df3475d04726c86e14f7"),
			Map.entry(
					"gmb_fare_v1/gmb_stop_crosswalk.csv",
					"71ccdb344f0379f27dc315efbb527f7ea02c853afa7a166879ce956531d06b58"),
			Map.entry(
					"ferry_fare_v1/ferry_fare_rules.parquet",
					"8d79774373f9de9b086382fce611a13750e63c664444fe7eb15555e44c6d189d"),
			Map.entry(
					"ferry_fare_v1/ferry_stop_crosswalk.csv",
					"76cf3d2f0020f9cc78dff00e3acb26081f4a63017b8d52d1d1e5546fc31d3cfa"),
			Map.entry(
					"bus_fare_v1/bus_fare_rules.parquet",
					"6a67270cc996dfc9217380e17cb1ed662daccd3f4c74fb52e766f321646237b4"),
			Map.entry(
					"bus_scope_direction_audit_v1/bus_stop_crosswalk.csv",
					"3915dc5bbe724ba0527cb5faa4a8196e6724c8137038cdb817f00d1a5d7d12f5"));

	private final Map<Layer, Map<String, String>> officialStopByFacility;
	private final Map<FareKey, FareRule> rules;
	private final CatalogAudit audit;

	private HongKongPtFareRuntimeCatalog(Builder builder) {
		Map<Layer, Map<String, String>> mappings =
				new EnumMap<>(Layer.class);
		for (Layer layer : Layer.values()) {
			mappings.put(
					layer,
					Collections.unmodifiableMap(new LinkedHashMap<>(
							builder.officialStopByFacility.get(layer))));
		}
		this.officialStopByFacility =
				Collections.unmodifiableMap(mappings);
		this.rules = Collections.unmodifiableMap(
				new LinkedHashMap<>(builder.rules));

		Map<String, Long> ruleCounts = new LinkedHashMap<>();
		Map<String, Long> mappingCounts = new LinkedHashMap<>();
		for (Layer layer : Layer.values()) {
			ruleCounts.put(
					layer.layerId,
					this.rules.keySet().stream()
							.filter(key -> key.layer == layer)
							.count());
			mappingCounts.put(
					layer.layerId,
					(long) this.officialStopByFacility.get(layer).size());
		}
		this.audit = new CatalogAudit(
				ruleCounts,
				mappingCounts,
				builder.sourceSha256,
				List.of(Layer.values()).stream().map(Layer::layerId).toList(),
				PROHIBITED_FALLBACKS);
	}

	public static HongKongPtFareRuntimeCatalog load(Path releaseRoot) {
		Path root = Objects.requireNonNull(releaseRoot, "releaseRoot")
				.toAbsolutePath().normalize();
		Builder builder = builder();
		verifySources(root, builder);
		loadCrosswalks(root, builder);
		loadRules(root, builder);
		return builder.build();
	}

	public FareQuote quote(
			TransitPassengerRoute passengerRoute,
			TransitSchedule schedule) {
		Objects.requireNonNull(passengerRoute, "passengerRoute");
		Objects.requireNonNull(schedule, "schedule");
		String lineId = id(passengerRoute.getLineId());
		String routeId = id(passengerRoute.getRouteId());
		String boarding = id(passengerRoute.getAccessStopId());
		String alighting = id(segmentEgressStopId(passengerRoute));
		if (lineId.isBlank() || routeId.isBlank()
				|| boarding.isBlank() || alighting.isBlank()) {
			return unresolved(
					Layer.MTR_DOMESTIC,
					"<missing>",
					lineId,
					routeId,
					boarding.isBlank() ? "<missing>" : boarding,
					alighting.isBlank() ? "<missing>" : alighting,
					"",
					"",
					"transit_passenger_route_reference_missing");
		}
		TransitLine line = schedule.getTransitLines().get(
				passengerRoute.getLineId());
		if (line == null) {
			return unresolved(
					Layer.MTR_DOMESTIC,
					"<unresolved>",
					lineId,
					routeId,
					boarding,
					alighting,
					"",
					"",
					"matsim_line_not_in_schedule");
		}
		TransitRoute route = line.getRoutes().get(passengerRoute.getRouteId());
		if (route == null) {
			return unresolved(
					Layer.MTR_DOMESTIC,
					"<unresolved>",
					lineId,
					routeId,
					boarding,
					alighting,
					"",
					"",
					"matsim_route_not_in_schedule_line");
		}
		return quote(
				route.getTransportMode(),
				lineId,
				routeId,
				boarding,
				alighting);
	}

	public FareQuote quote(
			String actualMode,
			String matsimLineId,
			String matsimRouteId,
			String boardingFacilityId,
			String alightingFacilityId) {
		String mode = requireText(actualMode, "actualMode");
		String lineId = requireText(matsimLineId, "matsimLineId");
		String routeId = requireText(matsimRouteId, "matsimRouteId");
		String boardingFacility =
				requireText(boardingFacilityId, "boardingFacilityId");
		String alightingFacility =
				requireText(alightingFacilityId, "alightingFacilityId");
		Layer layer = Layer.forActualMode(mode);
		if (layer == null) {
			return unresolved(
					Layer.MTR_DOMESTIC,
					mode,
					lineId,
					routeId,
					boardingFacility,
					alightingFacility,
					"",
					"",
					"actual_transport_mode_not_in_stage7_layers");
		}

		Map<String, String> crosswalk = officialStopByFacility.get(layer);
		String boardingOfficial = clean(crosswalk.get(boardingFacility));
		String alightingOfficial = clean(crosswalk.get(alightingFacility));
		if (boardingOfficial.isBlank()) {
			return unresolved(
					layer, mode, lineId, routeId,
					boardingFacility, alightingFacility,
					"", alightingOfficial,
					"boarding_facility_has_no_exact_canonical_crosswalk");
		}
		if (alightingOfficial.isBlank()) {
			return unresolved(
					layer, mode, lineId, routeId,
					boardingFacility, alightingFacility,
					boardingOfficial, "",
					"alighting_facility_has_no_exact_canonical_crosswalk");
		}

		FareKey key = FareKey.forRequest(
				layer,
				lineId,
				routeId,
				boardingOfficial,
				alightingOfficial);
		FareRule rule = rules.get(key);
		if (rule == null) {
			return unresolved(
					layer, mode, lineId, routeId,
					boardingFacility, alightingFacility,
					boardingOfficial, alightingOfficial,
					missingRuleReason(layer));
		}
		if (!rule.available()) {
			return new FareQuote(
					layer, mode, lineId, routeId,
					boardingFacility, alightingFacility,
					boardingOfficial, alightingOfficial,
					null,
					rule.costQuality,
					rule.mappingStatus,
					rule.costApplicabilityStatus,
					rule.costSource,
					rule.sourceRecordId,
					rule.sourcePath,
					rule.sourceSha256,
					rule.matchingMethod,
					rule.unresolvedReason.isBlank()
							? "canonical_rule_unresolved"
							: rule.unresolvedReason);
		}
		return new FareQuote(
				layer, mode, lineId, routeId,
				boardingFacility, alightingFacility,
				boardingOfficial, alightingOfficial,
				rule.costHkd,
				rule.costQuality,
				rule.mappingStatus,
				rule.costApplicabilityStatus,
				rule.costSource,
				rule.sourceRecordId,
				rule.sourcePath,
				rule.sourceSha256,
				rule.matchingMethod,
				"");
	}

	public CatalogAudit audit() {
		return audit;
	}

	static Builder builder() {
		return new Builder();
	}

	static final class Builder {
		private final Map<Layer, Map<String, String>>
				officialStopByFacility = new EnumMap<>(Layer.class);
		private final Map<FareKey, FareRule> rules = new LinkedHashMap<>();
		private final Map<String, String> sourceSha256 =
				new LinkedHashMap<>();

		private Builder() {
			for (Layer layer : Layer.values()) {
				officialStopByFacility.put(layer, new LinkedHashMap<>());
			}
		}

		Builder source(String relativePath, String sha256) {
			sourceSha256.put(
					requireText(relativePath, "relativePath"),
					requireText(sha256, "sha256"));
			return this;
		}

		Builder mapStop(
				Layer layer,
				String matsimFacilityId,
				String officialStopId) {
			Map<String, String> mapping = officialStopByFacility.get(
					Objects.requireNonNull(layer, "layer"));
			String facility = requireText(
					matsimFacilityId, "matsimFacilityId");
			String official = requireText(
					officialStopId, "officialStopId");
			String previous = mapping.putIfAbsent(facility, official);
			if (previous != null && !previous.equals(official)) {
				throw new IllegalStateException(
						"Conflicting exact PT stop mapping: layer="
								+ layer.layerId + ", facility=" + facility
								+ ", first=" + previous + ", second=" + official);
			}
			return this;
		}

		Builder rule(
				Layer layer,
				String matsimLineId,
				String matsimRouteId,
				String boardingOfficialId,
				String alightingOfficialId,
				Double costHkd,
				String recordStatus,
				String costQuality,
				String mappingStatus,
				String costApplicabilityStatus,
				String costSource,
				String sourceRecordId,
				String sourcePath,
				String sourceSha256,
				String matchingMethod,
				String unresolvedReason) {
			FareKey key = FareKey.forRequest(
					layer,
					matsimLineId,
					matsimRouteId,
					boardingOfficialId,
					alightingOfficialId);
			FareRule rule = new FareRule(
					costHkd,
					recordStatus,
					costQuality,
					mappingStatus,
					costApplicabilityStatus,
					costSource,
					sourceRecordId,
					sourcePath,
					sourceSha256,
					matchingMethod,
					unresolvedReason);
			FareRule previous = rules.putIfAbsent(key, rule);
			if (previous != null) {
				throw new IllegalStateException(
						"Duplicate canonical PT fare key: " + key);
			}
			return this;
		}

		HongKongPtFareRuntimeCatalog build() {
			return new HongKongPtFareRuntimeCatalog(this);
		}
	}

	private static void verifySources(Path root, Builder builder) {
		for (Map.Entry<String, String> entry : EXPECTED_SHA256.entrySet()) {
			Path path = root.resolve(entry.getKey()).normalize();
			if (!Files.isRegularFile(path)) {
				throw new IllegalArgumentException(
						"Canonical PT runtime source is missing: " + path);
			}
			String actual = sha256(path);
			if (!entry.getValue().equals(actual)) {
				throw new IllegalStateException(
						"Canonical PT runtime source SHA-256 mismatch: path="
								+ path + ", expected=" + entry.getValue()
								+ ", actual=" + actual);
			}
			builder.source(entry.getKey(), actual);
		}
	}

	private static void loadCrosswalks(Path root, Builder builder) {
		loadStationCrosswalk(
				root.resolve("mtr_station_od_v1/mtr_station_crosswalk.csv"),
				Layer.MTR_DOMESTIC,
				"station_id",
				"schedule_facility_ids_json",
				"in_domestic_fare_matrix",
				builder);
		loadStationCrosswalk(
				root.resolve(
						"light_rail_station_od_v1/light_rail_stop_crosswalk.csv"),
				Layer.LIGHT_RAIL,
				"stop_id",
				"schedule_facility_ids_json",
				"in_fare_matrix",
				builder);
		loadOneFacilityCrosswalk(
				root.resolve("gmb_fare_v1/gmb_stop_crosswalk.csv"),
				Layer.GMB,
				builder);
		loadOneFacilityCrosswalk(
				root.resolve("ferry_fare_v1/ferry_stop_crosswalk.csv"),
				Layer.FERRY,
				builder);
		loadOneFacilityCrosswalk(
				root.resolve(
						"bus_scope_direction_audit_v1/bus_stop_crosswalk.csv"),
				Layer.BUS_CORE,
				builder);
	}

	private static void loadStationCrosswalk(
			Path path,
			Layer layer,
			String officialColumn,
			String facilitiesColumn,
			String inFareMatrixColumn,
			Builder builder) {
		for (Map<String, String> row : readCsv(path)) {
			if (!"exact".equals(row.get("mapping_status"))
					|| !"True".equals(row.get(inFareMatrixColumn))) {
				continue;
			}
			String official = row.get(officialColumn);
			for (String facility : parseJsonStringArray(
					row.get(facilitiesColumn))) {
				builder.mapStop(layer, facility, official);
			}
		}
	}

	private static void loadOneFacilityCrosswalk(
			Path path,
			Layer layer,
			Builder builder) {
		for (Map<String, String> row : readCsv(path)) {
			if (!"exact".equals(row.get("mapping_status"))) {
				continue;
			}
			String facility = clean(row.get("matsim_stop_facility_id"));
			String official = clean(row.get("official_stop_id"));
			if (!facility.isBlank() && !official.isBlank()) {
				builder.mapStop(layer, facility, official);
			}
		}
	}

	private static void loadRules(Path root, Builder builder) {
		try {
			Class.forName("org.duckdb.DuckDBDriver");
		} catch (ClassNotFoundException error) {
			throw new IllegalStateException(
					"DuckDB JDBC is required for canonical PT Parquet loading.",
					error);
		}
		try (Connection connection =
					 DriverManager.getConnection("jdbc:duckdb:")) {
			loadRules(
					connection,
					builder,
					Layer.MTR_DOMESTIC,
					root.resolve(
							"mtr_station_od_v1/mtr_station_od_fare_rules.parquet"),
					"""
					SELECT '' AS matsim_line_id,
					       '' AS matsim_route_id,
					       boarding_station_id AS boarding_official_id,
					       alighting_station_id AS alighting_official_id,
					       adult_octopus_fare_hkd AS cost_hkd,
					       record_status,
					       CASE WHEN cost_effective_date_status = 'local_source_proven'
					            THEN 'A' ELSE 'B' END AS cost_quality,
					       CASE WHEN record_status = 'available' THEN 'exact'
					            WHEN record_status = 'ambiguous' THEN 'ambiguous'
					            ELSE 'unresolved' END AS mapping_status,
					       'adult_octopus_domestic_mtr_station_od' AS cost_applicability_status,
					       cost_source,
					       source_record_id,
					       matching_method,
					       unresolved_reason
					  FROM read_parquet('%s')
					 WHERE fare_network_scope = 'domestic_mtr_station_od'
					 ORDER BY boarding_station_id, alighting_station_id
					""");
			loadRules(
					connection,
					builder,
					Layer.LIGHT_RAIL,
					root.resolve(
							"light_rail_station_od_v1/light_rail_station_od_fare_rules.parquet"),
					"""
					SELECT '' AS matsim_line_id,
					       '' AS matsim_route_id,
					       boarding_stop_id AS boarding_official_id,
					       alighting_stop_id AS alighting_official_id,
					       adult_octopus_fare_hkd AS cost_hkd,
					       record_status,
					       CASE WHEN cost_effective_date_status = 'local_source_proven'
					            THEN 'A' ELSE 'B' END AS cost_quality,
					       CASE WHEN record_status = 'available' THEN 'exact'
					            WHEN record_status = 'ambiguous' THEN 'ambiguous'
					            ELSE 'unresolved' END AS mapping_status,
					       'adult_octopus_light_rail_base_before_unmodelled_concessions'
					            AS cost_applicability_status,
					       cost_source,
					       source_record_id,
					       matching_method,
					       unresolved_reason
					  FROM read_parquet('%s')
					 WHERE fare_network_scope = 'light_rail_station_od'
					 ORDER BY boarding_stop_id, alighting_stop_id
					""");
			loadPublishedRules(
					connection,
					builder,
					Layer.GMB,
					root.resolve("gmb_fare_v1/gmb_fare_rules.parquet"));
			loadPublishedRules(
					connection,
					builder,
					Layer.FERRY,
					root.resolve("ferry_fare_v1/ferry_fare_rules.parquet"));
			loadPublishedRules(
					connection,
					builder,
					Layer.BUS_CORE,
					root.resolve("bus_fare_v1/bus_fare_rules.parquet"));
		} catch (SQLException error) {
			throw new IllegalStateException(
					"Cannot load canonical Hong Kong PT fare Parquet tables.",
					error);
		}
	}

	private static void loadPublishedRules(
			Connection connection,
			Builder builder,
			Layer layer,
			Path path) throws SQLException {
		String sql = """
				SELECT matsim_line_id,
				       matsim_route_id,
				       boarding_stop_id AS boarding_official_id,
				       alighting_stop_id AS alighting_official_id,
				       published_fare_hkd AS cost_hkd,
				       record_status,
				       cost_quality,
				       mapping_status,
				       cost_applicability_status,
				       cost_source,
				       source_record_id,
				       matching_method,
				       unresolved_reason
				  FROM read_parquet('%s')
				 ORDER BY matsim_line_id, matsim_route_id,
				          boarding_stop_id, alighting_stop_id
				""";
		loadRules(connection, builder, layer, path, sql);
	}

	private static void loadRules(
			Connection connection,
			Builder builder,
			Layer layer,
			Path path,
			String sqlTemplate) throws SQLException {
		String relativePath = relativeSourcePath(path);
		String sourceSha = EXPECTED_SHA256.get(relativePath);
		String sql = sqlTemplate.formatted(sqlPath(path));
		try (Statement statement = connection.createStatement();
			 ResultSet result = statement.executeQuery(sql)) {
			while (result.next()) {
				Object rawCost = result.getObject("cost_hkd");
				Double cost = rawCost == null
						? null
						: ((Number) rawCost).doubleValue();
				builder.rule(
						layer,
						clean(result.getString("matsim_line_id")),
						clean(result.getString("matsim_route_id")),
						clean(result.getString("boarding_official_id")),
						clean(result.getString("alighting_official_id")),
						cost,
						clean(result.getString("record_status")),
						defaultText(
								result.getString("cost_quality"), "U"),
						defaultText(
								result.getString("mapping_status"),
								cost == null ? "unresolved" : "exact"),
						clean(result.getString(
								"cost_applicability_status")),
						clean(result.getString("cost_source")),
						clean(result.getString("source_record_id")),
						relativePath,
						sourceSha,
						clean(result.getString("matching_method")),
						clean(result.getString("unresolved_reason")));
			}
		}
	}

	private FareQuote unresolved(
			Layer layer,
			String actualMode,
			String lineId,
			String routeId,
			String boardingFacility,
			String alightingFacility,
			String boardingOfficial,
			String alightingOfficial,
			String reason) {
		String path = sourcePath(layer);
		return new FareQuote(
				layer,
				actualMode,
				lineId.isBlank() ? "<missing>" : lineId,
				routeId.isBlank() ? "<missing>" : routeId,
				boardingFacility,
				alightingFacility,
				boardingOfficial,
				alightingOfficial,
				null,
				"U",
				"unresolved",
				"not_applicable_unresolved_request",
				"",
				"",
				path,
				audit.sourceSha256.get(path),
				"",
				reason);
	}

	private static String sourcePath(Layer layer) {
		return switch (layer) {
			case MTR_DOMESTIC ->
					"mtr_station_od_v1/mtr_station_od_fare_rules.parquet";
			case LIGHT_RAIL ->
					"light_rail_station_od_v1/light_rail_station_od_fare_rules.parquet";
			case GMB -> "gmb_fare_v1/gmb_fare_rules.parquet";
			case FERRY -> "ferry_fare_v1/ferry_fare_rules.parquet";
			case BUS_CORE -> "bus_fare_v1/bus_fare_rules.parquet";
		};
	}

	private static String missingRuleReason(Layer layer) {
		return switch (layer) {
			case MTR_DOMESTIC ->
					"domestic_mtr_ordered_station_od_unresolved_no_cross_scope_fallback";
			case LIGHT_RAIL ->
					"light_rail_ordered_stop_od_unresolved_no_path_or_mtr_fallback";
			case GMB ->
					"gmb_exact_route_ordered_od_unresolved_no_candidate_selection";
			case FERRY ->
					"ferry_exact_route_ordered_od_unresolved_no_fullfare_fallback";
			case BUS_CORE ->
					"bus_core_exact_route_ordered_od_unresolved_no_simulation_fallback";
		};
	}

	private static String relativeSourcePath(Path absolutePath) {
		String normalized = absolutePath.toString().replace('\\', '/');
		int marker = normalized.indexOf("pt_fare_v1/");
		if (marker < 0) {
			throw new IllegalArgumentException(
					"PT source is outside pt_fare_v1: " + absolutePath);
		}
		return normalized.substring(marker + "pt_fare_v1/".length());
	}

	private static String sqlPath(Path path) {
		return path.toAbsolutePath().normalize().toString()
				.replace('\\', '/')
				.replace("'", "''");
	}

	private static List<Map<String, String>> readCsv(Path path) {
		try (BufferedReader reader = Files.newBufferedReader(
				path, StandardCharsets.UTF_8)) {
			String headerLine = reader.readLine();
			if (headerLine == null) {
				throw new IllegalArgumentException("Empty CSV: " + path);
			}
			List<String> headers = parseCsvLine(headerLine);
			List<Map<String, String>> rows = new ArrayList<>();
			String line;
			while ((line = reader.readLine()) != null) {
				List<String> values = parseCsvLine(line);
				if (values.size() != headers.size()) {
					throw new IllegalArgumentException(
							"CSV column count mismatch: path=" + path
									+ ", expected=" + headers.size()
									+ ", actual=" + values.size());
				}
				Map<String, String> row = new LinkedHashMap<>();
				for (int index = 0; index < headers.size(); index++) {
					row.put(headers.get(index), values.get(index));
				}
				rows.add(row);
			}
			return rows;
		} catch (IOException error) {
			throw new IllegalStateException("Cannot read CSV " + path, error);
		}
	}

	private static List<String> parseCsvLine(String line) {
		List<String> values = new ArrayList<>();
		StringBuilder current = new StringBuilder();
		boolean quoted = false;
		for (int index = 0; index < line.length(); index++) {
			char character = line.charAt(index);
			if (character == '"') {
				if (quoted && index + 1 < line.length()
						&& line.charAt(index + 1) == '"') {
					current.append('"');
					index++;
				} else {
					quoted = !quoted;
				}
			} else if (character == ',' && !quoted) {
				values.add(current.toString());
				current.setLength(0);
			} else {
				current.append(character);
			}
		}
		if (quoted) {
			throw new IllegalArgumentException(
					"Unterminated quoted CSV field.");
		}
		values.add(current.toString());
		return values;
	}

	private static List<String> parseJsonStringArray(String value) {
		String text = clean(value);
		if (text.isBlank() || "[]".equals(text)) {
			return List.of();
		}
		List<String> values = new ArrayList<>();
		boolean escaped = false;
		boolean quoted = false;
		StringBuilder current = new StringBuilder();
		for (int index = 0; index < text.length(); index++) {
			char character = text.charAt(index);
			if (escaped) {
				current.append(character);
				escaped = false;
			} else if (character == '\\') {
				escaped = true;
			} else if (character == '"') {
				if (quoted) {
					values.add(current.toString());
					current.setLength(0);
				}
				quoted = !quoted;
			} else if (quoted) {
				current.append(character);
			}
		}
		if (quoted || escaped) {
			throw new IllegalArgumentException(
					"Invalid JSON string array: " + value);
		}
		return values;
	}

	private static String sha256(Path path) {
		MessageDigest digest;
		try {
			digest = MessageDigest.getInstance("SHA-256");
		} catch (NoSuchAlgorithmException error) {
			throw new IllegalStateException(error);
		}
		try (var input = Files.newInputStream(path)) {
			byte[] buffer = new byte[64 * 1024];
			int count;
			while ((count = input.read(buffer)) >= 0) {
				if (count > 0) {
					digest.update(buffer, 0, count);
				}
			}
		} catch (IOException error) {
			throw new IllegalStateException("Cannot hash " + path, error);
		}
		return java.util.HexFormat.of().formatHex(digest.digest())
				.toLowerCase(Locale.ROOT);
	}

	private static String id(Object value) {
		return value == null ? "" : value.toString();
	}

	static Id<TransitStopFacility> segmentEgressStopId(
			TransitPassengerRoute passengerRoute) {
		TransitPassengerRoute chained = passengerRoute.getChainedRoute();
		return chained == null
				? passengerRoute.getEgressStopId()
				: chained.getAccessStopId();
	}

	private static String clean(String value) {
		return value == null ? "" : value.strip();
	}

	private static String defaultText(String value, String defaultValue) {
		String cleaned = clean(value);
		return cleaned.isBlank() ? defaultValue : cleaned;
	}

	private static String requireText(String value, String label) {
		String cleaned = clean(value);
		if (cleaned.isBlank()) {
			throw new IllegalArgumentException(label + " must not be blank.");
		}
		return cleaned;
	}

	private record FareKey(
			Layer layer,
			String matsimLineId,
			String matsimRouteId,
			String boardingOfficialId,
			String alightingOfficialId) {

		private static FareKey forRequest(
				Layer layer,
				String lineId,
				String routeId,
				String boarding,
				String alighting) {
			Objects.requireNonNull(layer, "layer");
			String normalizedLine =
					layer == Layer.MTR_DOMESTIC || layer == Layer.LIGHT_RAIL
							? ""
							: requireText(lineId, "matsimLineId");
			String normalizedRoute =
					layer == Layer.MTR_DOMESTIC || layer == Layer.LIGHT_RAIL
							? ""
							: requireText(routeId, "matsimRouteId");
			return new FareKey(
					layer,
					normalizedLine,
					normalizedRoute,
					requireText(boarding, "boardingOfficialId"),
					requireText(alighting, "alightingOfficialId"));
		}
	}

	private record FareRule(
			Double costHkd,
			String recordStatus,
			String costQuality,
			String mappingStatus,
			String costApplicabilityStatus,
			String costSource,
			String sourceRecordId,
			String sourcePath,
			String sourceSha256,
			String matchingMethod,
			String unresolvedReason) {

		private FareRule {
			recordStatus = defaultText(recordStatus, "unresolved");
			costQuality = defaultText(costQuality, "U");
			mappingStatus = defaultText(mappingStatus, "unresolved");
			costApplicabilityStatus = clean(costApplicabilityStatus);
			costSource = clean(costSource);
			sourceRecordId = clean(sourceRecordId);
			sourcePath = requireText(sourcePath, "sourcePath");
			sourceSha256 = requireText(sourceSha256, "sourceSha256");
			matchingMethod = clean(matchingMethod);
			unresolvedReason = clean(unresolvedReason);
			if (costHkd != null
					&& (!Double.isFinite(costHkd) || costHkd < 0.0)) {
				throw new IllegalArgumentException(
						"Canonical PT fare is not finite/nonnegative.");
			}
			if ("available".equals(recordStatus) && costHkd == null) {
				throw new IllegalArgumentException(
						"Available canonical PT rule has null fare.");
			}
			if (!"available".equals(recordStatus)
					&& unresolvedReason.isBlank()) {
				unresolvedReason = "canonical_rule_status_" + recordStatus;
			}
		}

		private boolean available() {
			return "available".equals(recordStatus) && costHkd != null;
		}
	}
}
