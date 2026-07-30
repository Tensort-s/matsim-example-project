package org.matsim.project.hongkong.taxi;

import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.population.io.StreamingPopulationReader;
import org.matsim.core.scenario.ScenarioUtils;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/**
 * Streaming, read-only parity audit of comparison baseline fares against the
 * Java route-distance fare calculator. This class never creates a Controler or
 * QSim.
 */
public final class HongKongTaxiRouteFareParityAudit {

	private static final double EQUIVALENCE_TOLERANCE_HKD = 1.0e-9;

	private HongKongTaxiRouteFareParityAudit() {
	}

	public static void main(String[] args) throws Exception {
		if (args.length != 4) {
			System.err.println(
					"Usage: HongKongTaxiRouteFareParityAudit "
							+ "<native-taxi-plans> <fare-rules-csv> "
							+ "<summary-csv> <validation-json>");
			System.exit(64);
		}

		Path plans = Path.of(args[0]).toAbsolutePath().normalize();
		Path ruleCsv = Path.of(args[1]).toAbsolutePath().normalize();
		Path summaryCsv = Path.of(args[2]).toAbsolutePath().normalize();
		Path validationJson = Path.of(args[3]).toAbsolutePath().normalize();
		Map<String, Object> report;
		int exitCode;
		try {
			report = run(plans, ruleCsv, summaryCsv);
			exitCode = Boolean.TRUE.equals(report.get("all_checks_passed")) ? 0 : 2;
		} catch (Throwable error) {
			report = new LinkedHashMap<>();
			report.put("audit", "hong_kong_taxi_route_fare_parity_v1");
			report.put("status", "failed");
			report.put("error_class", error.getClass().getName());
			report.put("error_message", String.valueOf(error.getMessage()));
			report.put("all_checks_passed", false);
			exitCode = 1;
		}
		report.put("process_exit_code", exitCode);
		HongKongTaxiSmokeOutputAudit.writeJsonAtomically(validationJson, report);
		if (exitCode != 0) {
			System.exit(exitCode);
		}
	}

	static Map<String, Object> run(
			Path plans,
			Path ruleCsv,
			Path summaryCsv) throws Exception {
		if (!Files.isRegularFile(plans)) {
			throw new IllegalArgumentException("Native taxi plans are not a regular file: " + plans);
		}
		if (!Files.isRegularFile(ruleCsv)) {
			throw new IllegalArgumentException("Fare rules are not a regular file: " + ruleCsv);
		}

		HongKongTaxiFareCalculator calculator = new HongKongTaxiFareCalculator();
		calculator.requireMatchesRuleCsv(ruleCsv);
		Audit audit = new Audit(calculator);
		Scenario scenario = ScenarioUtils.createScenario(ConfigUtils.createConfig());
		StreamingPopulationReader reader = new StreamingPopulationReader(scenario);
		reader.addAlgorithm(audit::accept);
		reader.readFile(plans.toString());

		Map<String, TypeSummary> summaries = audit.summaries();
		writeSummaryCsv(summaryCsv, summaries);
		boolean passed = audit.taxiLegs == 37_286
				&& audit.equivalentCount == audit.taxiLegs
				&& audit.mismatchCount == 0
				&& audit.invalidBaselineCount == 0
				&& audit.contextFailureCount == 0;

		Map<String, Object> report = new LinkedHashMap<>();
		report.put("audit", "hong_kong_taxi_route_fare_parity_v1");
		report.put("status", passed ? "validated" : "failed");
		report.put("generated_utc", Instant.now().toString());
		report.put("formula",
				"flagfall + ceil(first_tier_excess_m/200m)*first_rate"
						+ " + ceil(second_tier_excess_m/200m)*second_rate");
		report.put("fare_rounding_hkd", 0.1);
		report.put("fare_rule_version", HongKongTaxiFareCalculator.RULE_VERSION);
		report.put("fare_rule_effective_date",
				HongKongTaxiFareCalculator.RULE_EFFECTIVE_DATE);
		report.put("fare_rule_csv_sha256", sha256(ruleCsv));
		report.put("native_plans_sha256", sha256(plans));
		report.put("persons_streamed", audit.persons);
		report.put("taxi_legs", audit.taxiLegs);
		report.put("exact_count", audit.exactCount);
		report.put("equivalent_count", audit.equivalentCount);
		report.put("equivalence_tolerance_hkd", EQUIVALENCE_TOLERANCE_HKD);
		report.put("mismatch_count", audit.mismatchCount);
		report.put("maximum_absolute_difference_hkd", audit.maxAbsoluteDifference);
		report.put("invalid_baseline_count", audit.invalidBaselineCount);
		report.put("route_context_failure_count", audit.contextFailureCount);
		report.put("unresolved_count", audit.unresolvedCount);
		report.put("unresolved_fallback",
				"Urban Taxi distance fare rule; requested type remains recorded as unresolved");
		Map<String, Object> byType = new TreeMap<>();
		for (Map.Entry<String, TypeSummary> entry : summaries.entrySet()) {
			byType.put(entry.getKey(), entry.getValue().toMap());
		}
		report.put("by_requested_taxi_type", byType);
		report.put("summary_csv", summaryCsv.toString());
		report.put("simulation_run", false);
		report.put("controler_created", false);
		report.put("qsim_started", false);
		report.put("all_checks_passed", passed);
		return report;
	}

	private static void writeSummaryCsv(
			Path output,
			Map<String, TypeSummary> summaries) throws IOException {
		StringBuilder csv = new StringBuilder();
		csv.append("requested_taxi_type,applied_taxi_type,count,")
				.append("baseline_mean_hkd,baseline_median_hkd,")
				.append("calculated_mean_hkd,calculated_median_hkd,")
				.append("mean_absolute_difference_hkd,max_absolute_difference_hkd,")
				.append("unresolved_urban_fallback\n");
		for (TypeSummary summary : summaries.values()) {
			csv.append(summary.requestedTaxiType()).append(',')
					.append(summary.appliedTaxiType()).append(',')
					.append(summary.count()).append(',')
					.append(summary.baselineMean()).append(',')
					.append(summary.baselineMedian()).append(',')
					.append(summary.calculatedMean()).append(',')
					.append(summary.calculatedMedian()).append(',')
					.append(summary.meanAbsoluteDifference()).append(',')
					.append(summary.maxAbsoluteDifference()).append(',')
					.append(summary.unresolvedUrbanFallback()).append('\n');
		}
		writeAtomically(output, csv.toString());
	}

	private static void writeAtomically(Path output, String content) throws IOException {
		Path absolute = output.toAbsolutePath().normalize();
		Files.createDirectories(absolute.getParent());
		Path temporary = absolute.resolveSibling(absolute.getFileName() + ".tmp");
		Files.writeString(temporary, content, StandardCharsets.UTF_8);
		try {
			Files.move(temporary, absolute, StandardCopyOption.ATOMIC_MOVE);
		} catch (AtomicMoveNotSupportedException error) {
			Files.move(
					temporary,
					absolute,
					StandardCopyOption.REPLACE_EXISTING);
		}
	}

	private static String sha256(Path path) throws IOException, NoSuchAlgorithmException {
		MessageDigest digest = MessageDigest.getInstance("SHA-256");
		try (InputStream input = Files.newInputStream(path)) {
			byte[] buffer = new byte[1024 * 1024];
			int read;
			while ((read = input.read(buffer)) >= 0) {
				digest.update(buffer, 0, read);
			}
		}
		return java.util.HexFormat.of().formatHex(digest.digest());
	}

	private static final class Audit {

		private final HongKongTaxiFareCalculator calculator;
		private final Map<String, TypeAudit> byType = new TreeMap<>();
		private long persons;
		private long taxiLegs;
		private long exactCount;
		private long equivalentCount;
		private long mismatchCount;
		private long invalidBaselineCount;
		private long contextFailureCount;
		private long unresolvedCount;
		private double maxAbsoluteDifference;

		private Audit(HongKongTaxiFareCalculator calculator) {
			this.calculator = calculator;
		}

		private void accept(Person person) {
			persons++;
			if (person.getSelectedPlan() == null) {
				return;
			}
			for (PlanElement element : person.getSelectedPlan().getPlanElements()) {
				if (!(element instanceof Leg leg)
						|| !HongKongTaxiScoringParameters.TAXI_MODE.equals(leg.getMode())) {
					continue;
				}
				taxiLegs++;
				try {
					Object baselineValue = leg.getAttributes().getAttribute(
							HongKongTaxiLegAttributes.FARE_BASELINE_HKD);
					if (!(baselineValue instanceof Double baseline)
							|| !Double.isFinite(baseline)
							|| baseline < 0.0) {
						invalidBaselineCount++;
						continue;
					}
					HongKongTaxiRouteContext context = HongKongTaxiRouteContext.from(leg);
					HongKongTaxiFareCalculator.FareResult result =
							calculator.calculate(context.distanceMeters(), context.taxiType());
					double difference = Math.abs(baseline - result.fareHkd());
					if (Double.compare(baseline, result.fareHkd()) == 0) {
						exactCount++;
					}
					if (difference <= EQUIVALENCE_TOLERANCE_HKD) {
						equivalentCount++;
					} else {
						mismatchCount++;
					}
					maxAbsoluteDifference = Math.max(maxAbsoluteDifference, difference);
					if (result.unresolvedUrbanFallback()) {
						unresolvedCount++;
					}
					byType.computeIfAbsent(
							context.taxiType(),
							ignored -> new TypeAudit(result.appliedTaxiType(),
									result.unresolvedUrbanFallback()))
							.add(baseline, result.fareHkd(), difference);
				} catch (RuntimeException error) {
					contextFailureCount++;
				}
			}
		}

		private Map<String, TypeSummary> summaries() {
			Map<String, TypeSummary> result = new TreeMap<>();
			for (Map.Entry<String, TypeAudit> entry : byType.entrySet()) {
				result.put(entry.getKey(), entry.getValue().summarize(entry.getKey()));
			}
			return result;
		}
	}

	private static final class TypeAudit {

		private final String appliedTaxiType;
		private final boolean unresolvedUrbanFallback;
		private final List<Double> baselines = new ArrayList<>();
		private final List<Double> calculated = new ArrayList<>();
		private double absoluteDifferenceSum;
		private double maxAbsoluteDifference;

		private TypeAudit(String appliedTaxiType, boolean unresolvedUrbanFallback) {
			this.appliedTaxiType = appliedTaxiType;
			this.unresolvedUrbanFallback = unresolvedUrbanFallback;
		}

		private void add(double baseline, double routeFare, double absoluteDifference) {
			baselines.add(baseline);
			calculated.add(routeFare);
			absoluteDifferenceSum += absoluteDifference;
			maxAbsoluteDifference = Math.max(maxAbsoluteDifference, absoluteDifference);
		}

		private TypeSummary summarize(String requestedTaxiType) {
			return new TypeSummary(
					requestedTaxiType,
					appliedTaxiType,
					baselines.size(),
					mean(baselines),
					median(baselines),
					mean(calculated),
					median(calculated),
					absoluteDifferenceSum / baselines.size(),
					maxAbsoluteDifference,
					unresolvedUrbanFallback);
		}
	}

	private record TypeSummary(
			String requestedTaxiType,
			String appliedTaxiType,
			int count,
			double baselineMean,
			double baselineMedian,
			double calculatedMean,
			double calculatedMedian,
			double meanAbsoluteDifference,
			double maxAbsoluteDifference,
			boolean unresolvedUrbanFallback) {

		private Map<String, Object> toMap() {
			Map<String, Object> result = new LinkedHashMap<>();
			result.put("applied_taxi_type", appliedTaxiType);
			result.put("count", count);
			result.put("baseline_mean_hkd", baselineMean);
			result.put("baseline_median_hkd", baselineMedian);
			result.put("calculated_mean_hkd", calculatedMean);
			result.put("calculated_median_hkd", calculatedMedian);
			result.put("mean_absolute_difference_hkd", meanAbsoluteDifference);
			result.put("max_absolute_difference_hkd", maxAbsoluteDifference);
			result.put("unresolved_urban_fallback", unresolvedUrbanFallback);
			return result;
		}
	}

	private static double mean(List<Double> values) {
		return values.stream().mapToDouble(Double::doubleValue).average().orElseThrow();
	}

	private static double median(List<Double> values) {
		List<Double> sorted = values.stream().sorted(Comparator.naturalOrder()).toList();
		int middle = sorted.size() / 2;
		return sorted.size() % 2 == 1
				? sorted.get(middle)
				: (sorted.get(middle - 1) + sorted.get(middle)) / 2.0;
	}
}
