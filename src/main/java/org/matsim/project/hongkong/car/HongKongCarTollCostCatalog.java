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
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.TreeMap;

/**
 * Immutable lookup for the canonical base-scenario confirmed Hong Kong Car
 * toll component.
 *
 * <p>The catalog verifies the Stage 3 canonical interface, component table,
 * component registry, toll candidate, toll-identification table, and physical
 * passage-event table before loading. Only explicit confirmed charges and
 * confirmed full-route no-charge records are resolved. Motorcycles remain
 * null/out of scope and every other status fails closed.</p>
 */
public final class HongKongCarTollCostCatalog {

	public static final String COMPONENT_ID = "toll";
	public static final String SCENARIO = "base";

	private static final String CANONICAL_MANIFEST_PATH =
			"canonical_car_cost_interface_manifest.json";
	private static final String COMPONENT_TABLE_PATH =
			"unified_marginal_cost_interface_v1/"
					+ "car_leg_marginal_cost_components_base.parquet";
	private static final String COMPONENT_REGISTRY_PATH =
			"unified_marginal_cost_interface_v1/"
					+ "marginal_cost_component_registry.csv";
	private static final String TOLL_CANDIDATE_RELATIVE_PATH =
			"toll_rate_application_v1/"
					+ "car_leg_toll_cost_estimates_base.parquet";
	private static final String TOLL_IDENTIFICATION_RELATIVE_PATH =
			"toll_network_mapping_v1/"
					+ "car_leg_toll_identification.parquet";
	private static final String TOLL_EVENTS_RELATIVE_PATH =
			"toll_rate_application_v1/car_toll_passage_events.parquet";
	private static final String SOURCE_CANDIDATE_PATH =
			"data/transport_costs/hongkong/car_cost_v1/"
					+ TOLL_CANDIDATE_RELATIVE_PATH;
	private static final String SOURCE_SNAPSHOT_SHA256 =
			"2b01ceaa2fc1d9683162142940802e278318a2bda9a2bb40660649ef6f0ca943";

	private static final Map<String, String> EXPECTED_SHA256 = Map.of(
			CANONICAL_MANIFEST_PATH,
			"515d15df43a269da5f060338fcaf91cf004abfeb98ee4332e4172964f64be31d",
			COMPONENT_TABLE_PATH,
			"0337469ca99d61650f782f273b7b275cee124449e01037f95e15f978f94e742b",
			COMPONENT_REGISTRY_PATH,
			"ae2fd61342413b586aef1149f5221db0ffa04d994e1b415d6c7bccf077855580",
			TOLL_CANDIDATE_RELATIVE_PATH,
			"7d70b7144c87805d3b3bce3db0dcaa9b87f20e5e4ee7ae1a5a155c3ff8eb2342",
			TOLL_IDENTIFICATION_RELATIVE_PATH,
			"c4f1c997a2d48084bd1f51a54d584447de9cdcd22a0a2eebd2f9d21d845fb735",
			TOLL_EVENTS_RELATIVE_PATH,
			"5cb70822f55fa5fa21c8e43c80d598f83f4e0c5964e4160b07c1859422b7c392");
	private static final String EXPECTED_SOURCE_CANDIDATE_SHA256 =
			EXPECTED_SHA256.get(TOLL_CANDIDATE_RELATIVE_PATH);
	private static final double SUM_TOLERANCE_HKD = 1.0e-9;

	public enum Resolution {
		CONFIRMED_CHARGE,
		CONFIRMED_NO_CHARGE,
		OUT_OF_SCOPE,
		UNRESOLVED
	}

	public record PassageEvidence(
			String tollEventId,
			String canonicalFacilityId,
			int routeMatchStartIndex,
			int routeMatchEndIndex,
			List<String> matchedLinkIds,
			double costHkd,
			String rateSource,
			String rateSourceSha256,
			String rateEffectiveDate,
			String matchedRateInterval,
			String eventConstructionStatus,
			String rateQuality) {

		public PassageEvidence {
			tollEventId = requireText(tollEventId, "tollEventId");
			canonicalFacilityId = requireText(
					canonicalFacilityId, "canonicalFacilityId");
			matchedLinkIds = List.copyOf(
					Objects.requireNonNull(matchedLinkIds, "matchedLinkIds"));
			if (routeMatchStartIndex < 0
					|| routeMatchEndIndex < routeMatchStartIndex
					|| matchedLinkIds.isEmpty()
					|| matchedLinkIds.size()
					> routeMatchEndIndex - routeMatchStartIndex + 1
					|| !Double.isFinite(costHkd)
					|| costHkd <= 0.0) {
				throw new IllegalArgumentException(
						"Invalid confirmed physical toll-passage evidence.");
			}
			matchedLinkIds.forEach(link -> requireText(link, "matchedLinkId"));
			rateSource = requireText(rateSource, "rateSource");
			rateSourceSha256 = requireText(
					rateSourceSha256, "rateSourceSha256");
			rateEffectiveDate = requireText(
					rateEffectiveDate, "rateEffectiveDate");
			matchedRateInterval = requireText(
					matchedRateInterval, "matchedRateInterval");
			if (!"confirmed_charge".equals(requireText(
					eventConstructionStatus, "eventConstructionStatus"))) {
				throw new IllegalArgumentException(
						"Physical toll event is not explicitly confirmed.");
			}
			rateQuality = requireText(rateQuality, "rateQuality");
		}
	}

	public record TollQuote(
			String personId,
			int legSequence,
			String vehicleRefId,
			String vehicleClass,
			Double costHkd,
			String costStatus,
			String costQuality,
			String costSource,
			String sourceSnapshotSha256,
			String sourceCandidatePath,
			String sourceCandidateSha256,
			double sourceRouteDistanceM,
			int sourceFullLinkCount,
			List<PassageEvidence> passageEvidence,
			boolean fixedVehicleOwnershipCostIncluded,
			Resolution resolution,
			String unresolvedReason) {

		public TollQuote {
			personId = requireText(personId, "personId");
			if (legSequence < 0 || sourceFullLinkCount < 0) {
				throw new IllegalArgumentException(
						"Toll leg sequence and source link count must be nonnegative.");
			}
			vehicleRefId = clean(vehicleRefId);
			vehicleClass = requireText(vehicleClass, "vehicleClass");
			costStatus = requireText(costStatus, "costStatus");
			costQuality = requireText(costQuality, "costQuality");
			costSource = clean(costSource);
			sourceSnapshotSha256 = clean(sourceSnapshotSha256);
			sourceCandidatePath = requireText(
					sourceCandidatePath, "sourceCandidatePath");
			sourceCandidateSha256 = requireText(
					sourceCandidateSha256, "sourceCandidateSha256");
			if (!Double.isFinite(sourceRouteDistanceM)
					|| sourceRouteDistanceM < 0.0) {
				throw new IllegalArgumentException(
						"Source route distance must be finite and nonnegative.");
			}
			passageEvidence = List.copyOf(
					Objects.requireNonNull(passageEvidence, "passageEvidence"));
			resolution = Objects.requireNonNull(resolution, "resolution");
			unresolvedReason = clean(unresolvedReason);
			if (fixedVehicleOwnershipCostIncluded) {
				throw new IllegalArgumentException(
						"Fixed ownership cannot appear in a toll leg record.");
			}
			switch (resolution) {
				case CONFIRMED_CHARGE -> {
					if (!"private_car".equals(vehicleClass)
							|| costHkd == null
							|| !Double.isFinite(costHkd)
							|| costHkd <= 0.0
							|| !"confirmed_charge".equals(costStatus)
							|| passageEvidence.isEmpty()
							|| !unresolvedReason.isBlank()) {
						throw new IllegalArgumentException(
								"Confirmed toll charge contract failed.");
					}
					double eventSum = passageEvidence.stream()
							.mapToDouble(PassageEvidence::costHkd).sum();
					if (Math.abs(eventSum - costHkd) > SUM_TOLERANCE_HKD) {
						throw new IllegalArgumentException(
								"Physical toll-event sum differs from the leg toll.");
					}
				}
				case CONFIRMED_NO_CHARGE -> {
					if (!"private_car".equals(vehicleClass)
							|| costHkd == null
							|| Double.doubleToLongBits(costHkd)
							!= Double.doubleToLongBits(0.0)
							|| !"confirmed_no_charge".equals(costStatus)
							|| !passageEvidence.isEmpty()
							|| !unresolvedReason.isBlank()) {
						throw new IllegalArgumentException(
								"Confirmed no-charge toll contract failed.");
					}
				}
				case OUT_OF_SCOPE -> {
					if (!"motorcycle".equals(vehicleClass)
							|| costHkd != null
							|| !"out_of_scope".equals(costStatus)
							|| !passageEvidence.isEmpty()
							|| unresolvedReason.isBlank()) {
						throw new IllegalArgumentException(
								"Motorcycle toll exclusion contract failed.");
					}
				}
				case UNRESOLVED -> {
					if (costHkd != null
							|| !passageEvidence.isEmpty()
							|| unresolvedReason.isBlank()) {
						throw new IllegalArgumentException(
								"Unresolved toll must remain null with a reason.");
					}
				}
			}
		}

		public boolean confirmed() {
			return resolution == Resolution.CONFIRMED_CHARGE
					|| resolution == Resolution.CONFIRMED_NO_CHARGE;
		}

		public boolean chargeable() {
			return resolution == Resolution.CONFIRMED_CHARGE;
		}

		public boolean outOfScope() {
			return resolution == Resolution.OUT_OF_SCOPE;
		}
	}

	public record CatalogAudit(
			long tollRows,
			long confirmedChargeRows,
			long confirmedNoChargeRows,
			long unresolvedRows,
			long motorcycleOutOfScopeRows,
			long physicalPassageEvents,
			double confirmedTollTotalHkd,
			double resolvedMeanHkd,
			double resolvedMedianHkd,
			double resolvedP90Hkd,
			double resolvedMaxHkd,
			double eventLegSumMaxAbsErrorHkd,
			Map<String, String> sourceSha256,
			long distanceInferredRows,
			long candidateFallbackRows,
			long fixedOwnershipLegRows,
			long parkingRuntimeRowsLoaded) {

		public CatalogAudit {
			if (tollRows < 0
					|| confirmedChargeRows < 0
					|| confirmedNoChargeRows < 0
					|| unresolvedRows < 0
					|| motorcycleOutOfScopeRows < 0
					|| physicalPassageEvents < 0
					|| !finiteNonnegative(confirmedTollTotalHkd)
					|| !finiteNonnegative(resolvedMeanHkd)
					|| !finiteNonnegative(resolvedMedianHkd)
					|| !finiteNonnegative(resolvedP90Hkd)
					|| !finiteNonnegative(resolvedMaxHkd)
					|| !finiteNonnegative(eventLegSumMaxAbsErrorHkd)
					|| eventLegSumMaxAbsErrorHkd > SUM_TOLERANCE_HKD
					|| distanceInferredRows != 0
					|| candidateFallbackRows != 0
					|| fixedOwnershipLegRows != 0
					|| parkingRuntimeRowsLoaded != 0) {
				throw new IllegalArgumentException(
						"Canonical confirmed-toll audit contract failed.");
			}
			sourceSha256 = Collections.unmodifiableMap(
					new TreeMap<>(sourceSha256));
		}
	}

	private final Map<PersonLegKey, TollQuote> quotes;
	private final CatalogAudit audit;

	private HongKongCarTollCostCatalog(
			Map<PersonLegKey, TollQuote> quotes,
			CatalogAudit audit) {
		this.quotes = Collections.unmodifiableMap(
				new LinkedHashMap<>(quotes));
		this.audit = Objects.requireNonNull(audit, "audit");
	}

	public static HongKongCarTollCostCatalog load(Path carCostRoot) {
		Path root = Objects.requireNonNull(carCostRoot, "carCostRoot")
				.toAbsolutePath().normalize();
		Map<String, String> hashes = verifySources(root);
		verifyRegistry(root.resolve(COMPONENT_REGISTRY_PATH));
		return loadTables(root, hashes);
	}

	public TollQuote quote(String personId, int legSequence) {
		String person = requireText(personId, "personId");
		if (legSequence < 0) {
			throw new IllegalArgumentException(
					"legSequence must be nonnegative.");
		}
		TollQuote quote = quotes.get(new PersonLegKey(person, legSequence));
		if (quote != null) {
			return quote;
		}
		return new TollQuote(
				person,
				legSequence,
				"",
				"unresolved",
				null,
				"unresolved_missing_canonical_person_leg_key",
				"U",
				"",
				"",
				SOURCE_CANDIDATE_PATH,
				EXPECTED_SOURCE_CANDIDATE_SHA256,
				0.0,
				0,
				List.of(),
				false,
				Resolution.UNRESOLVED,
				"person_leg_key_not_in_canonical_base_toll_component");
	}

	public CatalogAudit audit() {
		return audit;
	}

	static Builder builder() {
		return new Builder();
	}

	static final class Builder {
		private final Map<PersonLegKey, TollQuote> quotes =
				new LinkedHashMap<>();

		Builder quote(TollQuote quote) {
			Objects.requireNonNull(quote, "quote");
			PersonLegKey key = new PersonLegKey(
					quote.personId(), quote.legSequence());
			if (quotes.putIfAbsent(key, quote) != null) {
				throw new IllegalStateException(
						"Duplicate canonical Car toll key: " + key);
			}
			return this;
		}

		HongKongCarTollCostCatalog buildForTests() {
			long charge = quotes.values().stream()
					.filter(TollQuote::chargeable).count();
			long noCharge = quotes.values().stream()
					.filter(quote -> quote.resolution()
							== Resolution.CONFIRMED_NO_CHARGE).count();
			long outOfScope = quotes.values().stream()
					.filter(TollQuote::outOfScope).count();
			long unresolved = quotes.values().stream()
					.filter(quote -> quote.resolution()
							== Resolution.UNRESOLVED).count();
			double total = quotes.values().stream()
					.filter(TollQuote::confirmed)
					.mapToDouble(TollQuote::costHkd).sum();
			long events = quotes.values().stream()
					.mapToLong(quote -> quote.passageEvidence().size()).sum();
			return new HongKongCarTollCostCatalog(
					quotes,
					new CatalogAudit(
							quotes.size(), charge, noCharge, unresolved,
							outOfScope, events, total,
							0.0, 0.0, 0.0, 0.0, 0.0,
							EXPECTED_SHA256, 0L, 0L, 0L, 0L));
		}
	}

	private static HongKongCarTollCostCatalog loadTables(
			Path root,
			Map<String, String> hashes) {
		try {
			Class.forName("org.duckdb.DuckDBDriver");
		} catch (ClassNotFoundException error) {
			throw new IllegalStateException(
					"DuckDB JDBC is required for canonical Car toll loading.",
					error);
		}
		Path componentTable = root.resolve(COMPONENT_TABLE_PATH);
		Path identificationTable = root.resolve(
				TOLL_IDENTIFICATION_RELATIVE_PATH);
		Path eventTable = root.resolve(TOLL_EVENTS_RELATIVE_PATH);
		Map<PersonLegKey, Identification> identifications =
				new LinkedHashMap<>();
		Map<PersonLegKey, List<PassageEvidence>> events =
				new LinkedHashMap<>();
		Map<PersonLegKey, TollQuote> quotes = new LinkedHashMap<>();
		long tollRows;
		double meanHkd;
		double medianHkd;
		double p90Hkd;
		double maxHkd;
		try (Connection connection = DriverManager.getConnection("jdbc:duckdb:");
			 Statement statement = connection.createStatement()) {
			loadIdentifications(statement, identificationTable, identifications);
			loadPassageEvents(statement, eventTable, events);
			tollRows = scalarLong(statement,
					"SELECT COUNT(*) FROM read_parquet('"
							+ sqlLiteral(componentTable)
							+ "') WHERE cost_component = 'toll'");
			try (ResultSet statistics = statement.executeQuery(
					"SELECT AVG(cost_hkd), MEDIAN(cost_hkd), "
							+ "QUANTILE_CONT(cost_hkd, 0.9), MAX(cost_hkd) "
							+ "FROM read_parquet('" + sqlLiteral(componentTable)
							+ "') WHERE cost_component = 'toll' "
							+ "AND cost_hkd IS NOT NULL")) {
				if (!statistics.next()) {
					throw new IllegalStateException(
							"Canonical toll statistics returned no row.");
				}
				meanHkd = statistics.getDouble(1);
				medianHkd = statistics.getDouble(2);
				p90Hkd = statistics.getDouble(3);
				maxHkd = statistics.getDouble(4);
			}
			String query = """
					SELECT person_id, leg_sequence, mode, vehicle_ref_id,
					       vehicle_class, scenario, cost_component, cost_hkd,
					       cost_status, cost_source, cost_quality,
					       source_snapshot_sha256, record_scope, cost_nature,
					       incremental_if_car_leg_chosen,
					       behavioral_inclusion_current_model,
					       eligible_for_future_scoring_pilot,
					       unresolved_reason, source_candidate_path,
					       source_candidate_sha256, route_distance_m,
					       fixed_vehicle_ownership_cost_included
					FROM read_parquet('%s')
					WHERE cost_component = 'toll'
					ORDER BY person_id, leg_sequence
					""".formatted(sqlLiteral(componentTable));
			try (ResultSet rows = statement.executeQuery(query)) {
				while (rows.next()) {
					PersonLegKey key = new PersonLegKey(
							rows.getString("person_id"),
							rows.getInt("leg_sequence"));
					Identification identification = identifications.get(key);
					if (identification == null) {
						throw new IllegalStateException(
								"Missing canonical toll identification: " + key);
					}
					TollQuote quote = rowToQuote(
							rows,
							identification,
							events.getOrDefault(key, List.of()));
					validateCanonicalRow(rows, identification, quote);
					if (quotes.putIfAbsent(key, quote) != null) {
						throw new IllegalStateException(
								"Duplicate canonical Car toll key: " + key);
					}
				}
			}
		} catch (SQLException error) {
			throw new IllegalStateException(
					"Failed to load canonical Car toll sources.", error);
		}
		if (tollRows != 67_718L
				|| quotes.size() != 67_718
				|| identifications.size() != 67_718) {
			throw new IllegalStateException(
					"Canonical Car toll key counts mismatch.");
		}
		long charge = quotes.values().stream()
				.filter(TollQuote::chargeable).count();
		long noCharge = quotes.values().stream()
				.filter(quote -> quote.resolution()
						== Resolution.CONFIRMED_NO_CHARGE).count();
		long outOfScope = quotes.values().stream()
				.filter(TollQuote::outOfScope).count();
		long unresolved = quotes.values().stream()
				.filter(quote -> quote.resolution()
						== Resolution.UNRESOLVED).count();
		long eventCount = events.values().stream()
				.mapToLong(List::size).sum();
		double total = quotes.values().stream()
				.filter(TollQuote::confirmed)
				.mapToDouble(TollQuote::costHkd).sum();
		if (charge != 25_858L
				|| noCharge != 38_931L
				|| outOfScope != 2_929L
				|| unresolved != 0L
				|| eventCount != 30_837L) {
			throw new IllegalStateException(
					"Canonical confirmed-toll counts violate Stage 8B.");
		}
		return new HongKongCarTollCostCatalog(
				quotes,
				new CatalogAudit(
						tollRows, charge, noCharge, unresolved,
						outOfScope, eventCount, total,
						meanHkd, medianHkd, p90Hkd, maxHkd, 0.0,
						hashes, 0L, 0L, 0L, 0L));
	}

	private static void loadIdentifications(
			Statement statement,
			Path table,
			Map<PersonLegKey, Identification> target) throws SQLException {
		String query = """
				SELECT person_id, leg_sequence, vehicle_ref_id, vehicle_class,
				       route_status, full_link_count,
				       toll_identification_status,
				       physical_facility_event_count, unresolved_reason
				FROM read_parquet('%s')
				ORDER BY person_id, leg_sequence
				""".formatted(sqlLiteral(table));
		try (ResultSet rows = statement.executeQuery(query)) {
			while (rows.next()) {
				Identification identification = new Identification(
						rows.getString("vehicle_ref_id"),
						rows.getString("vehicle_class"),
						rows.getString("route_status"),
						rows.getInt("full_link_count"),
						rows.getString("toll_identification_status"),
						rows.getInt("physical_facility_event_count"),
						rows.getString("unresolved_reason"));
				PersonLegKey key = new PersonLegKey(
						rows.getString("person_id"),
						rows.getInt("leg_sequence"));
				if (target.putIfAbsent(key, identification) != null) {
					throw new IllegalStateException(
							"Duplicate toll identification key: " + key);
				}
			}
		}
	}

	private static void loadPassageEvents(
			Statement statement,
			Path table,
			Map<PersonLegKey, List<PassageEvidence>> target)
			throws SQLException {
		String query = """
				SELECT toll_event_id, person_id, leg_sequence,
				       canonical_facility_id, route_match_start_index,
				       route_match_end_index, matched_link_ids, cost_hkd,
				       rate_source, rate_source_sha256, rate_effective_date,
				       matched_rate_interval, event_construction_status,
				       rate_quality, unresolved_reason
				FROM read_parquet('%s')
				WHERE scenario = 'base'
				ORDER BY person_id, leg_sequence, route_match_start_index,
				         toll_event_id
				""".formatted(sqlLiteral(table));
		try (ResultSet rows = statement.executeQuery(query)) {
			while (rows.next()) {
				if (!clean(rows.getString("unresolved_reason")).isBlank()) {
					throw new IllegalStateException(
							"Unresolved physical toll event reached canonical base source.");
				}
				PersonLegKey key = new PersonLegKey(
						rows.getString("person_id"),
						rows.getInt("leg_sequence"));
				target.computeIfAbsent(key, ignored -> new ArrayList<>())
						.add(new PassageEvidence(
								rows.getString("toll_event_id"),
								rows.getString("canonical_facility_id"),
								rows.getInt("route_match_start_index"),
								rows.getInt("route_match_end_index"),
								splitPipe(rows.getString("matched_link_ids")),
								rows.getDouble("cost_hkd"),
								rows.getString("rate_source"),
								rows.getString("rate_source_sha256"),
								rows.getString("rate_effective_date"),
								rows.getString("matched_rate_interval"),
								rows.getString("event_construction_status"),
								rows.getString("rate_quality")));
			}
		}
		target.replaceAll((key, value) -> List.copyOf(value));
	}

	private static TollQuote rowToQuote(
			ResultSet row,
			Identification identification,
			List<PassageEvidence> events) throws SQLException {
		String status = row.getString("cost_status");
		String vehicleClass = row.getString("vehicle_class");
		Resolution resolution;
		if ("confirmed_charge".equals(status)) {
			resolution = Resolution.CONFIRMED_CHARGE;
		} else if ("confirmed_no_charge".equals(status)) {
			resolution = Resolution.CONFIRMED_NO_CHARGE;
		} else if ("motorcycle".equals(vehicleClass)
				&& "out_of_scope".equals(status)) {
			resolution = Resolution.OUT_OF_SCOPE;
		} else {
			resolution = Resolution.UNRESOLVED;
		}
		return new TollQuote(
				row.getString("person_id"),
				row.getInt("leg_sequence"),
				row.getString("vehicle_ref_id"),
				vehicleClass,
				row.getObject("cost_hkd", Double.class),
				status,
				row.getString("cost_quality"),
				row.getString("cost_source"),
				row.getString("source_snapshot_sha256"),
				row.getString("source_candidate_path"),
				row.getString("source_candidate_sha256"),
				row.getDouble("route_distance_m"),
				identification.fullLinkCount(),
				events,
				row.getBoolean("fixed_vehicle_ownership_cost_included"),
				resolution,
				row.getString("unresolved_reason"));
	}

	private static void validateCanonicalRow(
			ResultSet row,
			Identification identification,
			TollQuote quote) throws SQLException {
		if (!"car".equals(row.getString("mode"))
				|| !SCENARIO.equals(row.getString("scenario"))
				|| !COMPONENT_ID.equals(row.getString("cost_component"))
				|| !"leg_marginal_cost_component".equals(
						row.getString("record_scope"))
				|| !"trip_conditional_marginal_cost".equals(
						row.getString("cost_nature"))
				|| !row.getBoolean("incremental_if_car_leg_chosen")
				|| !SOURCE_CANDIDATE_PATH.equals(quote.sourceCandidatePath())
				|| !EXPECTED_SOURCE_CANDIDATE_SHA256.equals(
						quote.sourceCandidateSha256())
				|| !SOURCE_SNAPSHOT_SHA256.equals(
						quote.sourceSnapshotSha256())
				|| !identification.vehicleRefId().equals(quote.vehicleRefId())
				|| !identification.vehicleClass().equals(quote.vehicleClass())
				|| !"route_ready_for_toll_mapping_audit".equals(
						identification.routeStatus())) {
			throw new IllegalStateException(
					"Canonical toll source contract failed: person="
							+ quote.personId() + ", leg=" + quote.legSequence());
		}
		if (quote.confirmed()) {
			if (!row.getBoolean("behavioral_inclusion_current_model")
					|| !row.getBoolean("eligible_for_future_scoring_pilot")
					|| identification.physicalEventCount()
					!= quote.passageEvidence().size()) {
				throw new IllegalStateException(
						"Confirmed toll row is not eligible in canonical source.");
			}
			String expectedIdentification = quote.chargeable()
					? "confirmed_charge_facility_identified"
					: "confirmed_no_charge_all_facilities_covered";
			if (!expectedIdentification.equals(
					identification.identificationStatus())) {
				throw new IllegalStateException(
						"Toll confirmation differs from mapping evidence.");
			}
		} else if (quote.outOfScope()) {
			if (row.getBoolean("behavioral_inclusion_current_model")
					|| row.getBoolean("eligible_for_future_scoring_pilot")
					|| !"out_of_scope_motorcycle".equals(
						identification.identificationStatus())) {
				throw new IllegalStateException(
						"Motorcycle toll row violates the exclusion contract.");
			}
		} else {
			throw new IllegalStateException(
					"Unconfirmed or unresolved toll source fails closed.");
		}
	}

	private static Map<String, String> verifySources(Path root) {
		Map<String, String> actual = new LinkedHashMap<>();
		for (Map.Entry<String, String> entry : EXPECTED_SHA256.entrySet()) {
			Path path = root.resolve(entry.getKey()).normalize();
			if (!Files.isRegularFile(path)) {
				throw new IllegalArgumentException(
						"Canonical Car toll source is missing: " + path);
			}
			String hash = sha256(path);
			if (!entry.getValue().equals(hash)) {
				throw new IllegalStateException(
						"Canonical Car toll source SHA-256 mismatch: path="
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
		String[] toll = null;
		String[] fixed = null;
		for (String line : lines.subList(1, lines.size())) {
			String[] values = line.split(",", -1);
			String component = value(values, columns, "cost_component");
			if (COMPONENT_ID.equals(component)) {
				toll = values;
			} else if ("fixed_vehicle_ownership_cost".equals(component)) {
				fixed = values;
			}
		}
		if (toll == null
				|| !"True".equals(value(
						toll, columns, "behavioral_inclusion_current_model"))
				|| !"True".equals(value(
						toll, columns, "incremental_if_car_leg_chosen"))
				|| fixed == null
				|| !"False".equals(value(
						fixed, columns, "behavioral_inclusion_current_model"))) {
			throw new IllegalStateException(
					"Canonical toll/fixed registry contract failed.");
		}
	}

	private static long scalarLong(Statement statement, String sql)
			throws SQLException {
		try (ResultSet result = statement.executeQuery(sql)) {
			if (!result.next()) {
				throw new IllegalStateException("Count query returned no row.");
			}
			return result.getLong(1);
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

	private static List<String> splitPipe(String value) {
		String cleaned = requireText(value, "matchedLinkIds");
		return List.of(cleaned.split("\\|", -1));
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
					"Failed to hash canonical Car toll source: " + path,
					error);
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
	}

	private record Identification(
			String vehicleRefId,
			String vehicleClass,
			String routeStatus,
			int fullLinkCount,
			String identificationStatus,
			int physicalEventCount,
			String unresolvedReason) {

		private Identification {
			vehicleRefId = requireText(vehicleRefId, "vehicleRefId");
			vehicleClass = requireText(vehicleClass, "vehicleClass");
			routeStatus = requireText(routeStatus, "routeStatus");
			if (fullLinkCount < 0 || physicalEventCount < 0) {
				throw new IllegalArgumentException(
						"Identification counts must be nonnegative.");
			}
			identificationStatus = requireText(
					identificationStatus, "identificationStatus");
			unresolvedReason = clean(unresolvedReason);
		}
	}
}
