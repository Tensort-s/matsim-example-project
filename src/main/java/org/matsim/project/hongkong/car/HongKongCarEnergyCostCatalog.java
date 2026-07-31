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
 * Immutable lookup for the canonical base-scenario Hong Kong private-car
 * {@code fuel_or_electricity} marginal-cost component.
 *
 * <p>The catalog verifies the Stage 3 canonical manifest, component table and
 * registry bytes before loading. It loads no toll, parking or fixed-ownership
 * amount. The source contains no individual powertrain, so the resolved value
 * remains the published representative licensed-fleet average and
 * motorcycles remain explicit null/out-of-scope records.</p>
 */
public final class HongKongCarEnergyCostCatalog {

	public static final Path DEFAULT_CAR_COST_ROOT = Path.of(
			"data", "transport_costs", "hongkong", "car_cost_v1");
	public static final String COMPONENT_ID = "fuel_or_electricity";
	public static final String SCENARIO = "base";

	private static final String CANONICAL_MANIFEST_PATH =
			"canonical_car_cost_interface_manifest.json";
	private static final String COMPONENT_TABLE_PATH =
			"unified_marginal_cost_interface_v1/"
					+ "car_leg_marginal_cost_components_base.parquet";
	private static final String COMPONENT_REGISTRY_PATH =
			"unified_marginal_cost_interface_v1/"
					+ "marginal_cost_component_registry.csv";
	private static final String SOURCE_CANDIDATE_PATH =
			"data/transport_costs/hongkong/car_cost_v1/energy_application_v1/"
					+ "car_leg_energy_cost_estimates_base.parquet";

	private static final Map<String, String> EXPECTED_SHA256 = Map.of(
			CANONICAL_MANIFEST_PATH,
			"515d15df43a269da5f060338fcaf91cf004abfeb98ee4332e4172964f64be31d",
			COMPONENT_TABLE_PATH,
			"0337469ca99d61650f782f273b7b275cee124449e01037f95e15f978f94e742b",
			COMPONENT_REGISTRY_PATH,
			"ae2fd61342413b586aef1149f5221db0ffa04d994e1b415d6c7bccf077855580");
	private static final String EXPECTED_SOURCE_CANDIDATE_SHA256 =
			"0e0cc3fdd3440b4be8e51ad98289de590af1b479222c8e29b15845055d82f5da";
	private static final double BASE_ENERGY_HKD_PER_KM =
			2.3260259843327393;
	private static final double FORMULA_TOLERANCE_HKD = 1.0e-9;

	public enum Resolution {
		RESOLVED,
		OUT_OF_SCOPE,
		UNRESOLVED
	}

	public record EnergyQuote(
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
			boolean fixedVehicleOwnershipCostIncluded,
			Resolution resolution,
			String unresolvedReason) {

		public EnergyQuote {
			personId = requireText(personId, "personId");
			if (legSequence < 0) {
				throw new IllegalArgumentException(
						"legSequence must be nonnegative.");
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
			resolution = Objects.requireNonNull(resolution, "resolution");
			unresolvedReason = clean(unresolvedReason);
			if (fixedVehicleOwnershipCostIncluded) {
				throw new IllegalArgumentException(
						"Fixed ownership cannot appear in a Car energy leg record.");
			}
			if (resolution == Resolution.RESOLVED) {
				if (costHkd == null
						|| !Double.isFinite(costHkd)
						|| costHkd < 0.0) {
					throw new IllegalArgumentException(
							"Resolved Car energy cost must be finite and nonnegative.");
				}
				if (!"private_car".equals(vehicleClass)
						|| !unresolvedReason.isBlank()) {
					throw new IllegalArgumentException(
							"Resolved Car energy record must be a private car without an unresolved reason.");
				}
			} else {
				if (costHkd != null || unresolvedReason.isBlank()) {
					throw new IllegalArgumentException(
							"Non-resolved Car energy record must preserve null cost and an explicit reason.");
				}
			}
			if (resolution == Resolution.OUT_OF_SCOPE
					&& !"motorcycle".equals(vehicleClass)) {
				throw new IllegalArgumentException(
						"Only canonical motorcycle records may be out of scope.");
			}
		}

		public boolean resolved() {
			return resolution == Resolution.RESOLVED;
		}

		public boolean outOfScope() {
			return resolution == Resolution.OUT_OF_SCOPE;
		}
	}

	public record CatalogAudit(
			long componentTableRows,
			long fuelRows,
			long tollRows,
			long parkingRows,
			long privateCarResolvedRows,
			long motorcycleOutOfScopeRows,
			long legalZeroRows,
			double resolvedCostTotalHkd,
			double resolvedCostMeanHkd,
			double resolvedCostMedianHkd,
			double resolvedCostP90Hkd,
			double formulaMaxAbsErrorHkd,
			Map<String, String> sourceSha256,
			boolean individualPowertrainAvailable,
			long fixedOwnershipLegRows,
			long tollRuntimeRowsLoaded,
			long parkingRuntimeRowsLoaded) {

		public CatalogAudit {
			if (componentTableRows < 0L
					|| fuelRows < 0L
					|| tollRows < 0L
					|| parkingRows < 0L
					|| privateCarResolvedRows < 0L
					|| motorcycleOutOfScopeRows < 0L
					|| legalZeroRows < 0L
					|| !Double.isFinite(resolvedCostTotalHkd)
					|| resolvedCostTotalHkd < 0.0
					|| !Double.isFinite(resolvedCostMeanHkd)
					|| resolvedCostMeanHkd < 0.0
					|| !Double.isFinite(resolvedCostMedianHkd)
					|| resolvedCostMedianHkd < 0.0
					|| !Double.isFinite(resolvedCostP90Hkd)
					|| resolvedCostP90Hkd < 0.0
					|| !Double.isFinite(formulaMaxAbsErrorHkd)
					|| formulaMaxAbsErrorHkd > FORMULA_TOLERANCE_HKD
					|| individualPowertrainAvailable
					|| fixedOwnershipLegRows != 0L
					|| tollRuntimeRowsLoaded != 0L
					|| parkingRuntimeRowsLoaded != 0L) {
				throw new IllegalArgumentException(
						"Canonical Car energy catalog audit contract failed.");
			}
			sourceSha256 = Collections.unmodifiableMap(
					new TreeMap<>(sourceSha256));
		}
	}

	private final Map<PersonLegKey, EnergyQuote> quotes;
	private final CatalogAudit audit;

	private HongKongCarEnergyCostCatalog(
			Map<PersonLegKey, EnergyQuote> quotes,
			CatalogAudit audit) {
		this.quotes = Collections.unmodifiableMap(
				new LinkedHashMap<>(quotes));
		this.audit = Objects.requireNonNull(audit, "audit");
	}

	public static HongKongCarEnergyCostCatalog load(Path carCostRoot) {
		Path root = Objects.requireNonNull(carCostRoot, "carCostRoot")
				.toAbsolutePath().normalize();
		Map<String, String> sourceHashes = verifySources(root);
		verifyRegistry(root.resolve(COMPONENT_REGISTRY_PATH));
		return loadComponentTable(root, sourceHashes);
	}

	public EnergyQuote quote(String personId, int legSequence) {
		String person = requireText(personId, "personId");
		if (legSequence < 0) {
			throw new IllegalArgumentException(
					"legSequence must be nonnegative.");
		}
		EnergyQuote quote = quotes.get(
				new PersonLegKey(person, legSequence));
		if (quote != null) {
			return quote;
		}
		return new EnergyQuote(
				person,
				legSequence,
				"",
				"unresolved",
				null,
				"unresolved_missing_canonical_person_leg_key",
				"U",
				"",
				"",
				COMPONENT_TABLE_PATH,
				EXPECTED_SHA256.get(COMPONENT_TABLE_PATH),
				0.0,
				false,
				Resolution.UNRESOLVED,
				"person_leg_key_not_in_canonical_base_energy_component");
	}

	public CatalogAudit audit() {
		return audit;
	}

	static Builder builder() {
		return new Builder();
	}

	static final class Builder {
		private final Map<PersonLegKey, EnergyQuote> quotes =
				new LinkedHashMap<>();

		Builder quote(EnergyQuote quote) {
			Objects.requireNonNull(quote, "quote");
			PersonLegKey key = new PersonLegKey(
					quote.personId(), quote.legSequence());
			if (quotes.putIfAbsent(key, quote) != null) {
				throw new IllegalStateException(
						"Duplicate canonical Car energy key: " + key);
			}
			return this;
		}

		HongKongCarEnergyCostCatalog buildForTests() {
			long resolved = quotes.values().stream()
					.filter(EnergyQuote::resolved).count();
			long outOfScope = quotes.values().stream()
					.filter(EnergyQuote::outOfScope).count();
			long zero = quotes.values().stream()
					.filter(quote -> quote.resolved()
							&& quote.costHkd() == 0.0).count();
			double total = quotes.values().stream()
					.filter(EnergyQuote::resolved)
					.mapToDouble(EnergyQuote::costHkd)
					.sum();
			return new HongKongCarEnergyCostCatalog(
					quotes,
					new CatalogAudit(
							quotes.size(),
							quotes.size(),
							0L,
							0L,
							resolved,
							outOfScope,
							zero,
							total,
							resolved == 0 ? 0.0 : total / resolved,
							0.0,
							0.0,
							0.0,
							EXPECTED_SHA256,
							false,
							0L,
							0L,
							0L));
		}
	}

	private static HongKongCarEnergyCostCatalog loadComponentTable(
			Path root,
			Map<String, String> sourceHashes) {
		try {
			Class.forName("org.duckdb.DuckDBDriver");
		} catch (ClassNotFoundException error) {
			throw new IllegalStateException(
					"DuckDB JDBC is required for canonical Car Parquet loading.",
					error);
		}
		Path table = root.resolve(COMPONENT_TABLE_PATH);
		Map<PersonLegKey, EnergyQuote> quotes = new LinkedHashMap<>();
		long componentRows;
		long fuelRows = 0L;
		long tollRows = 0L;
		long parkingRows = 0L;
		long resolvedRows = 0L;
		long outOfScopeRows = 0L;
		long zeroRows = 0L;
		double totalHkd = 0.0;
		double formulaMaxError = 0.0;
		double meanHkd;
		double medianHkd;
		double p90Hkd;
		try (Connection connection =
					 DriverManager.getConnection("jdbc:duckdb:");
			 Statement statement = connection.createStatement()) {
			String parquet = sqlLiteral(table);
			componentRows = scalarLong(
					statement,
					"SELECT COUNT(*) FROM read_parquet('" + parquet + "')");
			try (ResultSet counts = statement.executeQuery(
					"SELECT cost_component, COUNT(*) AS row_count "
							+ "FROM read_parquet('" + parquet + "') "
							+ "GROUP BY cost_component")) {
				while (counts.next()) {
					switch (counts.getString("cost_component")) {
						case COMPONENT_ID ->
								fuelRows = counts.getLong("row_count");
						case "toll" ->
								tollRows = counts.getLong("row_count");
						case "destination_parking" ->
								parkingRows = counts.getLong("row_count");
						default -> throw new IllegalStateException(
								"Unexpected canonical Car component: "
										+ counts.getString("cost_component"));
					}
				}
			}
			try (ResultSet statistics = statement.executeQuery(
					"SELECT AVG(cost_hkd), MEDIAN(cost_hkd), "
							+ "QUANTILE_CONT(cost_hkd, 0.9) "
							+ "FROM read_parquet('" + parquet + "') "
							+ "WHERE cost_component = 'fuel_or_electricity' "
							+ "AND cost_hkd IS NOT NULL")) {
				if (!statistics.next()) {
					throw new IllegalStateException(
							"Canonical Car energy statistics query returned no row.");
				}
				meanHkd = statistics.getDouble(1);
				medianHkd = statistics.getDouble(2);
				p90Hkd = statistics.getDouble(3);
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
					WHERE cost_component = 'fuel_or_electricity'
					ORDER BY person_id, leg_sequence
					""".formatted(parquet);
			try (ResultSet rows = statement.executeQuery(query)) {
				while (rows.next()) {
					EnergyQuote quote = rowToQuote(rows);
					validateCanonicalRow(rows, quote);
					PersonLegKey key = new PersonLegKey(
							quote.personId(), quote.legSequence());
					if (quotes.putIfAbsent(key, quote) != null) {
						throw new IllegalStateException(
								"Duplicate canonical Car energy key: " + key);
					}
					if (quote.resolved()) {
						resolvedRows++;
						totalHkd += quote.costHkd();
						if (quote.costHkd() == 0.0) {
							zeroRows++;
						}
						double expected = quote.sourceRouteDistanceM()
								* BASE_ENERGY_HKD_PER_KM / 1_000.0;
						formulaMaxError = Math.max(
								formulaMaxError,
								Math.abs(expected - quote.costHkd()));
					} else if (quote.outOfScope()) {
						outOfScopeRows++;
					}
				}
			}
		} catch (SQLException error) {
			throw new IllegalStateException(
					"Failed to load canonical Car energy component.", error);
		}
		if (quotes.size() != 67_718) {
			throw new IllegalStateException(
					"Canonical Car energy key count mismatch: "
							+ quotes.size());
		}
		if (componentRows != 203_154L
				|| fuelRows != 67_718L
				|| tollRows != 67_718L
				|| parkingRows != 67_718L
				|| resolvedRows != 64_789L
				|| outOfScopeRows != 2_929L
				|| zeroRows != 33L) {
			throw new IllegalStateException(
					"Canonical Car component counts violate the Stage 8A contract.");
		}
		CatalogAudit audit = new CatalogAudit(
				componentRows,
				fuelRows,
				tollRows,
				parkingRows,
				resolvedRows,
				outOfScopeRows,
				zeroRows,
				totalHkd,
				meanHkd,
				medianHkd,
				p90Hkd,
				formulaMaxError,
				sourceHashes,
				false,
				0L,
				0L,
				0L);
		return new HongKongCarEnergyCostCatalog(quotes, audit);
	}

	private static EnergyQuote rowToQuote(ResultSet row)
			throws SQLException {
		String vehicleClass = row.getString("vehicle_class");
		Double cost = row.getObject("cost_hkd", Double.class);
		Resolution resolution;
		if ("private_car".equals(vehicleClass)) {
			resolution = Resolution.RESOLVED;
		} else if ("motorcycle".equals(vehicleClass)) {
			resolution = Resolution.OUT_OF_SCOPE;
		} else {
			resolution = Resolution.UNRESOLVED;
		}
		return new EnergyQuote(
				row.getString("person_id"),
				row.getInt("leg_sequence"),
				row.getString("vehicle_ref_id"),
				vehicleClass,
				cost,
				row.getString("cost_status"),
				row.getString("cost_quality"),
				row.getString("cost_source"),
				row.getString("source_snapshot_sha256"),
				row.getString("source_candidate_path"),
				row.getString("source_candidate_sha256"),
				row.getDouble("route_distance_m"),
				row.getBoolean("fixed_vehicle_ownership_cost_included"),
				resolution,
				row.getString("unresolved_reason"));
	}

	private static void validateCanonicalRow(
			ResultSet row,
			EnergyQuote quote) throws SQLException {
		if (!"car".equals(row.getString("mode"))
				|| !SCENARIO.equals(row.getString("scenario"))
				|| !COMPONENT_ID.equals(row.getString("cost_component"))
				|| !"leg_marginal_cost_component".equals(
						row.getString("record_scope"))
				|| !"trip_conditional_marginal_cost".equals(
						row.getString("cost_nature"))
				|| !row.getBoolean("incremental_if_car_leg_chosen")
				|| !SOURCE_CANDIDATE_PATH.equals(
						quote.sourceCandidatePath())
				|| !EXPECTED_SOURCE_CANDIDATE_SHA256.equals(
						quote.sourceCandidateSha256())) {
			throw new IllegalStateException(
					"Canonical Car energy row violates the Stage 8A source contract: person="
							+ quote.personId() + ", leg="
							+ quote.legSequence());
		}
		if (quote.resolved()) {
			if (!row.getBoolean("behavioral_inclusion_current_model")
					|| !row.getBoolean(
							"eligible_for_future_scoring_pilot")
					|| !List.of(
							"resolved_representative_fleet_average",
							"resolved_zero_distance_energy_zero")
							.contains(quote.costStatus())) {
				throw new IllegalStateException(
						"Resolved Car energy row has invalid inclusion/status.");
			}
		} else if (quote.outOfScope()) {
			if (row.getBoolean("behavioral_inclusion_current_model")
					|| row.getBoolean("eligible_for_future_scoring_pilot")
					|| !"out_of_scope_motorcycle".equals(
							quote.costStatus())
					|| !"vehicle_class_motorcycle".equals(
							quote.unresolvedReason())) {
				throw new IllegalStateException(
						"Motorcycle row violates the null/out-of-scope contract.");
			}
		}
	}

	private static Map<String, String> verifySources(Path root) {
		Map<String, String> actual = new LinkedHashMap<>();
		for (Map.Entry<String, String> entry :
				EXPECTED_SHA256.entrySet()) {
			Path path = root.resolve(entry.getKey()).normalize();
			if (!Files.isRegularFile(path)) {
				throw new IllegalArgumentException(
						"Canonical Car source is missing: " + path);
			}
			String hash = sha256(path);
			if (!entry.getValue().equals(hash)) {
				throw new IllegalStateException(
						"Canonical Car source SHA-256 mismatch: path="
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
					"Failed to read canonical Car component registry.",
					error);
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
		String[] fuel = null;
		String[] fixed = null;
		for (String line : lines.subList(1, lines.size())) {
			String[] values = line.split(",", -1);
			String component = value(
					values, columns, "cost_component");
			if (COMPONENT_ID.equals(component)) {
				fuel = values;
			} else if ("fixed_vehicle_ownership_cost".equals(component)) {
				fixed = values;
			}
		}
		if (fuel == null
				|| !"True".equals(value(
						fuel, columns,
						"behavioral_inclusion_current_model"))
				|| !"True".equals(value(
						fuel, columns,
						"incremental_if_car_leg_chosen"))
				|| fixed == null
				|| !"False".equals(value(
						fixed, columns,
						"behavioral_inclusion_current_model"))
				|| !"False".equals(value(
						fixed, columns,
						"incremental_if_car_leg_chosen"))) {
			throw new IllegalStateException(
					"Canonical Car component registry inclusion contract failed.");
		}
	}

	private static long scalarLong(Statement statement, String sql)
			throws SQLException {
		try (ResultSet result = statement.executeQuery(sql)) {
			if (!result.next()) {
				throw new IllegalStateException(
						"Canonical Car count query returned no row.");
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
					"Failed to hash canonical Car source: " + path,
					error);
		}
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
}
