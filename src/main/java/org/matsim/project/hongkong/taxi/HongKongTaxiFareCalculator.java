package org.matsim.project.hongkong.taxi;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * Pure distance-only Hong Kong taxi fare calculator.
 *
 * <p>The immutable rules are a Java representation of
 * {@code data/taxi/hongkong/processed/taxi_fare_model_v1/taxi_fare_rules.csv}.
 * {@link #requireMatchesRuleCsv(Path)} is the drift guard between that tracked
 * source table and these runtime values.</p>
 */
public final class HongKongTaxiFareCalculator {

	public static final String RULE_VERSION = "taxi_fare_model_v1";
	public static final String RULE_EFFECTIVE_DATE = "2024-07-14";
	public static final String RULE_CSV_SHA256 =
			"1bf1527702ba5ea2b8f471e78bcfe7a852dc46602b454a3d0115c03f38c6dd7e";
	public static final String UNRESOLVED = "unresolved";
	public static final String URBAN_TAXI = "urban_taxi";
	public static final String NEW_TERRITORIES_TAXI = "new_territories_taxi";
	public static final String LANTAU_TAXI = "lantau_taxi";

	private static final Map<String, FareRule> RULES = buildRules();

	public FareResult calculate(double distanceMeters, String taxiType) {
		if (!Double.isFinite(distanceMeters) || distanceMeters < 0.0) {
			throw new IllegalArgumentException(
					"Taxi fare distance must be finite and non-negative: " + distanceMeters);
		}
		if (taxiType == null || taxiType.isBlank()) {
			throw new IllegalArgumentException("Taxi type must be non-blank");
		}

		boolean unresolvedFallback = UNRESOLVED.equals(taxiType);
		String appliedTaxiType = unresolvedFallback ? URBAN_TAXI : taxiType;
		FareRule rule = RULES.get(appliedTaxiType);
		if (rule == null) {
			throw new IllegalArgumentException("Unsupported Hong Kong taxi type: " + taxiType);
		}

		long firstTierIncrements = 0;
		long secondTierIncrements = 0;
		if (distanceMeters > rule.flagfallDistanceMeters()) {
			firstTierIncrements = ceilingIncrements(
					Math.max(
							Math.min(distanceMeters, rule.firstTierEndDistanceMeters())
									- rule.flagfallDistanceMeters(),
							0.0),
					rule.firstTierIncrementDistanceMeters());
			secondTierIncrements = ceilingIncrements(
					Math.max(distanceMeters - rule.firstTierEndDistanceMeters(), 0.0),
					rule.secondTierIncrementDistanceMeters());
		}

		long fareTenths = Math.addExact(
				rule.flagfallTenths(),
				Math.addExact(
						Math.multiplyExact(firstTierIncrements, rule.firstTierIncrementTenths()),
						Math.multiplyExact(secondTierIncrements, rule.secondTierIncrementTenths())));
		return new FareResult(
				fareTenths / 10.0,
				taxiType,
				appliedTaxiType,
				unresolvedFallback,
				firstTierIncrements,
				secondTierIncrements,
				RULE_VERSION);
	}

	public Map<String, FareRule> rules() {
		return RULES;
	}

	/**
	 * Verifies both file identity and the runtime-relevant values represented by
	 * the Java rules. The audit intentionally rejects a changed CSV until the
	 * Java representation is reviewed and updated.
	 */
	public void requireMatchesRuleCsv(Path csv) {
		Objects.requireNonNull(csv, "csv");
		try {
			String actualSha = sha256(csv);
			if (!RULE_CSV_SHA256.equals(actualSha)) {
				throw new IllegalStateException(
						"Taxi fare rule CSV SHA256 mismatch: expected=" + RULE_CSV_SHA256
								+ ", actual=" + actualSha + ", path=" + csv);
			}
			List<String> lines = Files.readAllLines(csv, StandardCharsets.UTF_8);
			if (lines.size() != 4) {
				throw new IllegalStateException(
						"Taxi fare rule CSV must contain one header and three rules: " + csv);
			}
			String[] header = lines.getFirst().split(",", -1);
			Map<String, Integer> columns = new LinkedHashMap<>();
			for (int index = 0; index < header.length; index++) {
				String name = index == 0
						? header[index].replace("\uFEFF", "")
						: header[index];
				columns.put(name, index);
			}
			for (int row = 1; row < lines.size(); row++) {
				String[] values = lines.get(row).split(",", -1);
				String taxiType = value(values, columns, "taxi_type");
				FareRule expected = RULES.get(taxiType);
				if (expected == null) {
					throw new IllegalStateException("Unexpected taxi type in rule CSV: " + taxiType);
				}
				expected.requireMatchesCsv(values, columns);
			}
		} catch (IOException | NoSuchAlgorithmException error) {
			throw new IllegalStateException("Cannot verify taxi fare rule CSV " + csv, error);
		}
	}

	private static long ceilingIncrements(double excessDistance, int incrementDistance) {
		double count = Math.ceil(excessDistance / incrementDistance);
		if (!Double.isFinite(count) || count < 0.0 || count > Long.MAX_VALUE) {
			throw new IllegalArgumentException(
					"Taxi fare increment count is out of range: " + count);
		}
		return (long) count;
	}

	private static Map<String, FareRule> buildRules() {
		Map<String, FareRule> rules = new LinkedHashMap<>();
		add(rules, new FareRule(
				URBAN_TAXI, 2_000, 290, 9_000, 1_025, 200, 21, 200, 14));
		add(rules, new FareRule(
				NEW_TERRITORIES_TAXI, 2_000, 255, 8_000, 825, 200, 19, 200, 14));
		add(rules, new FareRule(
				LANTAU_TAXI, 2_000, 240, 20_000, 1_950, 200, 19, 200, 16));
		return Map.copyOf(rules);
	}

	private static void add(Map<String, FareRule> rules, FareRule rule) {
		if (rules.put(rule.taxiType(), rule) != null) {
			throw new IllegalStateException("Duplicate taxi fare rule: " + rule.taxiType());
		}
	}

	private static String value(
			String[] values,
			Map<String, Integer> columns,
			String column) {
		Integer index = columns.get(column);
		if (index == null || index >= values.length) {
			throw new IllegalStateException("Missing taxi fare CSV column: " + column);
		}
		return values[index];
	}

	private static String sha256(Path path) throws IOException, NoSuchAlgorithmException {
		MessageDigest digest = MessageDigest.getInstance("SHA-256");
		try (InputStream input = Files.newInputStream(path)) {
			byte[] buffer = new byte[64 * 1024];
			int read;
			while ((read = input.read(buffer)) >= 0) {
				digest.update(buffer, 0, read);
			}
		}
		return java.util.HexFormat.of().formatHex(digest.digest());
	}

	public record FareResult(
			double fareHkd,
			String requestedTaxiType,
			String appliedTaxiType,
			boolean unresolvedUrbanFallback,
			long firstTierIncrementCount,
			long secondTierIncrementCount,
			String ruleVersion) {
	}

	public record FareRule(
			String taxiType,
			int flagfallDistanceMeters,
			int flagfallTenths,
			int firstTierEndDistanceMeters,
			int firstTierEndFareTenths,
			int firstTierIncrementDistanceMeters,
			int firstTierIncrementTenths,
			int secondTierIncrementDistanceMeters,
			int secondTierIncrementTenths) {

		public FareRule {
			Objects.requireNonNull(taxiType, "taxiType");
			if (flagfallDistanceMeters < 0
					|| flagfallTenths < 0
					|| firstTierEndDistanceMeters < flagfallDistanceMeters
					|| firstTierIncrementDistanceMeters <= 0
					|| firstTierIncrementTenths < 0
					|| secondTierIncrementDistanceMeters <= 0
					|| secondTierIncrementTenths < 0) {
				throw new IllegalArgumentException("Illegal taxi fare rule: " + taxiType);
			}
			int firstTierDistance = firstTierEndDistanceMeters - flagfallDistanceMeters;
			if (firstTierDistance % firstTierIncrementDistanceMeters != 0) {
				throw new IllegalArgumentException(
						"First-tier end is not an exact increment boundary: " + taxiType);
			}
			long derivedEndFare = flagfallTenths
					+ (long) (firstTierDistance / firstTierIncrementDistanceMeters)
					* firstTierIncrementTenths;
			if (derivedEndFare != firstTierEndFareTenths) {
				throw new IllegalArgumentException(
						"First-tier end fare is inconsistent for " + taxiType);
			}
		}

		private void requireMatchesCsv(
				String[] values,
				Map<String, Integer> columns) {
			requireCsv(values, columns, "fare_effective_date", RULE_EFFECTIVE_DATE);
			requireCsv(values, columns, "flagfall_distance_m",
					Integer.toString(flagfallDistanceMeters));
			requireCsvDecimal(values, columns, "flagfall_hkd", flagfallTenths);
			requireCsvDecimal(values, columns, "first_tier_end_fare_hkd",
					firstTierEndFareTenths);
			requireCsv(values, columns, "first_tier_end_distance_m",
					Integer.toString(firstTierEndDistanceMeters));
			requireCsv(values, columns, "first_tier_increment_distance_m",
					Integer.toString(firstTierIncrementDistanceMeters));
			requireCsvDecimal(values, columns, "first_tier_increment_hkd",
					firstTierIncrementTenths);
			requireCsv(values, columns, "second_tier_increment_distance_m",
					Integer.toString(secondTierIncrementDistanceMeters));
			requireCsvDecimal(values, columns, "second_tier_increment_hkd",
					secondTierIncrementTenths);
		}

		private static void requireCsv(
				String[] values,
				Map<String, Integer> columns,
				String column,
				String expected) {
			String actual = value(values, columns, column);
			if (!expected.equals(actual)) {
				throw new IllegalStateException(
						"Taxi fare CSV mismatch: column=" + column
								+ ", expected=" + expected + ", actual=" + actual);
			}
		}

		private static void requireCsvDecimal(
				String[] values,
				Map<String, Integer> columns,
				String column,
				int expectedTenths) {
			double actual = Double.parseDouble(value(values, columns, column));
			if (Math.round(actual * 10.0) != expectedTenths) {
				throw new IllegalStateException(
						"Taxi fare CSV mismatch: column=" + column
								+ ", expected_tenths=" + expectedTenths
								+ ", actual=" + actual);
			}
		}
	}
}
