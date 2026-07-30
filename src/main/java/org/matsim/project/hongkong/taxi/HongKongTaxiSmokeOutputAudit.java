package org.matsim.project.hongkong.taxi;

import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.api.core.v01.population.Population;
import org.matsim.api.core.v01.population.Route;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.population.io.PopulationReader;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.core.utils.misc.OptionalTime;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.lang.management.ManagementFactory;
import java.nio.charset.StandardCharsets;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Properties;
import java.util.TreeMap;

/** Read-only output plans, hash, score, provenance, and JSON utilities. */
public final class HongKongTaxiSmokeOutputAudit {

	private HongKongTaxiSmokeOutputAudit() {
	}

	public static PlanAudit auditPopulationFile(Path plansFile) {
		requireRegularFile(plansFile, "plans output");
		Scenario scenario = ScenarioUtils.createScenario(ConfigUtils.createConfig());
		new PopulationReader(scenario).readFile(plansFile.toString());
		return auditPopulation(scenario.getPopulation());
	}

	public static PlanAudit auditPopulation(Population population) {
		PlanAudit audit = new PlanAudit();
		MessageDigest taxiDigest = sha256Digest();
		MessageDigest routeDigest = sha256Digest();
		MessageDigest strictTaxiDigest = sha256Digest();
		MessageDigest mainActivityDigest = sha256Digest();
		MessageDigest fixedNonPtDigest = sha256Digest();
		HongKongTaxiScoringParameters parameters = HongKongTaxiScoringParameters.centralV1();
		List<Double> allScores = new ArrayList<>();
		List<Double> taxiPersonScores = new ArrayList<>();
		List<Double> nonTaxiPersonScores = new ArrayList<>();

		audit.persons = population.getPersons().size();
		for (Person person : population.getPersons().values()) {
			Plan selected = person.getSelectedPlan();
			boolean selectedHasTaxi = selected != null && selected.getPlanElements().stream()
					.anyMatch(element -> element instanceof Leg leg && "taxi".equals(leg.getMode()));
			auditPlanScore(audit, selected, selectedHasTaxi,
					allScores, taxiPersonScores, nonTaxiPersonScores);

			for (Plan plan : person.getPlans()) {
				audit.plans++;
				int elementIndex = 0;
				int taxiOrdinal = 0;
				int mainActivityOrdinal = 0;
				int fixedNonPtOrdinal = 0;
				for (PlanElement element : plan.getPlanElements()) {
					if (element instanceof Activity activity) {
						audit.activities++;
						if (!"pt interaction".equals(activity.getType())) {
							audit.mainActivities++;
							update(mainActivityDigest, mainActivityFingerprint(
									person, mainActivityOrdinal++, activity));
						}
					} else if (element instanceof Leg leg) {
						audit.legs++;
						audit.modeCounts.merge(leg.getMode(), 1L, Long::sum);
						updateRouteFingerprint(routeDigest, person, elementIndex, leg);
						if (!"pt".equals(leg.getMode())
								&& !"pt".equals(leg.getRoutingMode())) {
							audit.fixedNonPtMainLegs++;
							update(fixedNonPtDigest, fixedNonPtFingerprint(
									person, fixedNonPtOrdinal++, leg));
						}
						Route route = leg.getRoute();
						if (route != null) {
							audit.routes++;
							if (!Double.isFinite(route.getDistance())
									|| route.getDistance() < 0.0) {
								audit.invalidRouteDistances++;
							}
							if (route.getTravelTime().isUndefined()
									|| !Double.isFinite(route.getTravelTime().seconds())
									|| route.getTravelTime().seconds() < 0.0) {
								audit.invalidRouteTravelTimes++;
							}
						}
						if ("taxi".equals(leg.getMode())) {
							auditTaxiLeg(audit, taxiDigest, strictTaxiDigest,
									taxiOrdinal++, leg, person, parameters);
						}
					}
					elementIndex++;
				}
			}
		}
		audit.allScoreStatistics = summarize(allScores);
		audit.taxiPersonScoreStatistics = summarize(taxiPersonScores);
		audit.nonTaxiPersonScoreStatistics = summarize(nonTaxiPersonScores);
		audit.taxiAttributeFingerprintSha256 = hex(taxiDigest.digest());
		audit.strictTaxiFingerprintSha256 = hex(strictTaxiDigest.digest());
		audit.mainActivityFingerprintSha256 = hex(mainActivityDigest.digest());
		audit.fixedNonPtMainLegFingerprintSha256 =
				hex(fixedNonPtDigest.digest());
		audit.planRouteFingerprintSha256 = hex(routeDigest.digest());
		return audit;
	}

	private static void auditPlanScore(
			PlanAudit audit,
			Plan selected,
			boolean selectedHasTaxi,
			List<Double> allScores,
			List<Double> taxiScores,
			List<Double> nonTaxiScores) {
		if (selectedHasTaxi) {
			audit.taxiPersons++;
		}
		if (selected == null || selected.getScore() == null) {
			audit.missingSelectedPlanScores++;
			return;
		}
		double score = selected.getScore();
		if (Double.isNaN(score)) {
			audit.nanSelectedPlanScores++;
		} else if (!Double.isFinite(score)) {
			audit.infiniteSelectedPlanScores++;
		} else {
			audit.finiteSelectedPlanScores++;
			allScores.add(score);
			(selectedHasTaxi ? taxiScores : nonTaxiScores).add(score);
			if (selectedHasTaxi) {
				audit.finiteTaxiPersonSelectedPlanScores++;
			}
		}
	}

	private static void auditTaxiLeg(
			PlanAudit audit,
			MessageDigest digest,
			MessageDigest strictDigest,
			int taxiOrdinal,
			Leg leg,
			Person person,
			HongKongTaxiScoringParameters parameters) {
		audit.taxiLegs++;
		HongKongTaxiLegAttributes.Metadata metadata;
		try {
			metadata = HongKongTaxiLegAttributes.readAndValidate(
					leg, person.getId(), parameters);
		} catch (IllegalArgumentException error) {
			audit.invalidTaxiAttributes++;
			if (audit.attributeFailureExamples.size() < 10) {
				audit.attributeFailureExamples.add(error.getMessage());
			}
			return;
		}
		audit.fareSumHkd += metadata.fareBaselineHkd();
		audit.mainTripIndexSum += metadata.mainTripIndex();
		audit.taxiTypeCounts.merge(metadata.taxiType(), 1L, Long::sum);
		audit.classificationSourceCounts.merge(
				metadata.classificationSource(), 1L, Long::sum);
		audit.taxiRoutingModeCounts.merge(
				String.valueOf(leg.getRoutingMode()), 1L, Long::sum);

		update(digest, person.getId() + "\t"
				+ Double.toHexString(metadata.fareBaselineHkd()) + "\t"
				+ metadata.taxiType() + "\t"
				+ metadata.fareScope() + "\t"
				+ metadata.fareModelVersion() + "\t"
				+ metadata.classificationSource() + "\t"
				+ metadata.mainTripIndex() + "\n");
		update(strictDigest, person.getId() + "\t" + taxiOrdinal + "\t"
				+ leg.getMode() + "\t" + String.valueOf(leg.getRoutingMode()) + "\t"
				+ optionalTime(leg.getDepartureTime()) + "\t"
				+ strictRoute(leg.getRoute()) + "\t"
				+ strictTaxiAttributes(leg) + "\n");
	}

	private static String mainActivityFingerprint(
			Person person,
			int ordinal,
			Activity activity) {
		String coordinate = activity.getCoord() == null ? "<null>"
				: Double.toHexString(activity.getCoord().getX()) + ","
						+ Double.toHexString(activity.getCoord().getY());
		return person.getId() + "\t" + ordinal + "\t"
				+ activity.getType() + "\t"
				+ String.valueOf(activity.getLinkId()) + "\t"
				+ String.valueOf(activity.getFacilityId()) + "\t"
				+ coordinate + "\t"
				+ optionalTime(activity.getStartTime()) + "\t"
				+ optionalTime(activity.getEndTime()) + "\t"
				+ optionalTime(activity.getMaximumDuration()) + "\n";
	}

	private static String fixedNonPtFingerprint(
			Person person,
			int ordinal,
			Leg leg) {
		return person.getId() + "\t" + ordinal + "\t"
				+ leg.getMode() + "\t" + String.valueOf(leg.getRoutingMode()) + "\t"
				+ optionalTime(leg.getDepartureTime()) + "\t"
				+ optionalTime(leg.getTravelTime()) + "\t"
				+ strictRoute(leg.getRoute()) + "\t"
				+ allAttributes(leg) + "\n";
	}

	private static String strictRoute(Route route) {
		if (route == null) {
			return "<null>";
		}
		return route.getClass().getName() + "|"
				+ String.valueOf(route.getStartLinkId()) + "|"
				+ String.valueOf(route.getEndLinkId()) + "|"
				+ Double.toHexString(route.getDistance()) + "|"
				+ optionalTime(route.getTravelTime()) + "|"
				+ String.valueOf(route.getRouteDescription());
	}

	private static String strictTaxiAttributes(Leg leg) {
		List<String> names = List.of(
				HongKongTaxiLegAttributes.FARE_BASELINE_HKD,
				HongKongTaxiLegAttributes.TAXI_TYPE,
				HongKongTaxiLegAttributes.FARE_SCOPE,
				HongKongTaxiLegAttributes.FARE_MODEL_VERSION,
				HongKongTaxiLegAttributes.CLASSIFICATION_SOURCE,
				HongKongTaxiLegAttributes.MAIN_TRIP_INDEX
		);
		StringBuilder result = new StringBuilder();
		for (String name : names) {
			Object value = leg.getAttributes().getAttribute(name);
			result.append(name).append("=")
					.append(value == null ? "<null>" : value.getClass().getName())
					.append(":").append(canonicalValue(value)).append(";");
		}
		return result.toString();
	}

	private static String allAttributes(Leg leg) {
		Map<String, Object> sorted = new TreeMap<>(
				leg.getAttributes().getAsMap());
		StringBuilder result = new StringBuilder();
		for (Map.Entry<String, Object> entry : sorted.entrySet()) {
			Object value = entry.getValue();
			result.append(entry.getKey()).append("=")
					.append(value == null ? "<null>" : value.getClass().getName())
					.append(":").append(canonicalValue(value)).append(";");
		}
		return result.toString();
	}

	private static String canonicalValue(Object value) {
		if (value instanceof Double number) {
			return Double.toHexString(number);
		}
		if (value instanceof Float number) {
			return Float.toHexString(number);
		}
		return String.valueOf(value);
	}

	private static void updateRouteFingerprint(
			MessageDigest digest,
			Person person,
			int elementIndex,
			Leg leg) {
		Route route = leg.getRoute();
		String routeText = route == null ? "<null>" :
				String.valueOf(route.getStartLinkId()) + "\t"
						+ String.valueOf(route.getEndLinkId()) + "\t"
						+ Double.toHexString(route.getDistance()) + "\t"
						+ optionalTime(route.getTravelTime());
		update(digest, person.getId() + "\t" + elementIndex + "\t"
				+ leg.getMode() + "\t" + String.valueOf(leg.getRoutingMode()) + "\t"
				+ optionalTime(leg.getDepartureTime()) + "\t" + routeText + "\n");
	}

	private static String optionalTime(OptionalTime time) {
		return time.isDefined() ? Double.toHexString(time.seconds()) : "<undefined>";
	}

	public static boolean sameStructureModesAttributesAndRoutes(
			PlanAudit source,
			PlanAudit output) {
		return source.persons == output.persons
				&& source.plans == output.plans
				&& source.activities == output.activities
				&& source.legs == output.legs
				&& source.routes == output.routes
				&& source.modeCounts.equals(output.modeCounts)
				&& source.taxiLegs == output.taxiLegs
				&& source.taxiPersons == output.taxiPersons
				&& source.taxiTypeCounts.equals(output.taxiTypeCounts)
				&& source.classificationSourceCounts.equals(output.classificationSourceCounts)
				&& source.taxiRoutingModeCounts.equals(output.taxiRoutingModeCounts)
				&& source.mainTripIndexSum == output.mainTripIndexSum
				&& close(source.fareSumHkd, output.fareSumHkd)
				&& source.taxiAttributeFingerprintSha256
						.equals(output.taxiAttributeFingerprintSha256)
				&& source.planRouteFingerprintSha256
						.equals(output.planRouteFingerprintSha256);
	}

	/**
	 * Allows only PT route preparation/stage expansion. Main activities, Taxi
	 * legs, and every non-PT main leg remain byte-semantically fixed.
	 */
	public static boolean sameFixedPlansAllowPreparedPt(
			PlanAudit source,
			PlanAudit output) {
		return source.persons == output.persons
				&& source.plans == output.plans
				&& source.mainActivities == output.mainActivities
				&& source.fixedNonPtMainLegs == output.fixedNonPtMainLegs
				&& source.mainActivityFingerprintSha256
						.equals(output.mainActivityFingerprintSha256)
				&& source.fixedNonPtMainLegFingerprintSha256
						.equals(output.fixedNonPtMainLegFingerprintSha256)
				&& source.taxiLegs == output.taxiLegs
				&& source.taxiPersons == output.taxiPersons
				&& source.strictTaxiFingerprintSha256
						.equals(output.strictTaxiFingerprintSha256)
				&& source.taxiTypeCounts.equals(output.taxiTypeCounts)
				&& source.classificationSourceCounts
						.equals(output.classificationSourceCounts)
				&& source.taxiRoutingModeCounts.equals(output.taxiRoutingModeCounts)
				&& source.mainTripIndexSum == output.mainTripIndexSum
				&& close(source.fareSumHkd, output.fareSumHkd);
	}

	public static RuntimeLogAudit auditRuntimeLog(Path logFile) {
		requireRegularFile(logFile, "runtime log");
		long ptMissingTransitRoute = 0;
		long ptUnknownStop = 0;
		long taxiFareMismatch = 0;
		long invalidTaxiAttribute = 0;
		long unknownMode = 0;
		long taxiRouteExecutionError = 0;
		try (BufferedReader reader = Files.newBufferedReader(
				logFile, StandardCharsets.UTF_8)) {
			String line;
			while ((line = reader.readLine()) != null) {
				String lower = line.toLowerCase(Locale.ROOT);
				ptMissingTransitRoute += bool(
						line.contains("pt-leg has no TransitRoute"));
				ptUnknownStop += bool(line.contains(
						"pt-agent doesn't know to what transit stop to go"));
				taxiFareMismatch += bool(line.contains(
						"Hong Kong taxi fare schedule mismatch"));
				invalidTaxiAttribute += bool(line.contains(
						"Invalid Hong Kong taxi leg attribute"));
				unknownMode += bool(lower.contains("unknown mode")
						|| lower.contains("no routing module found for mode"));
				taxiRouteExecutionError += bool(
						lower.contains("taxi-leg has no route")
								|| lower.contains("taxi route execution error"));
			}
		} catch (IOException error) {
			throw new IllegalStateException("Cannot audit runtime log " + logFile,
					error);
		}
		return new RuntimeLogAudit(
				ptMissingTransitRoute,
				ptUnknownStop,
				taxiFareMismatch,
				invalidTaxiAttribute,
				unknownMode,
				taxiRouteExecutionError
		);
	}

	private static long bool(boolean value) {
		return value ? 1L : 0L;
	}

	public static Map<String, Object> fileSnapshot(Path path) {
		requireRegularFile(path, "file");
		try {
			return ordered(
					"path", path.toAbsolutePath().normalize().toString(),
					"size_bytes", Files.size(path),
					"sha256", sha256(path)
			);
		} catch (IOException error) {
			throw new IllegalStateException("Cannot snapshot " + path, error);
		}
	}

	public static String sha256(Path path) {
		MessageDigest digest = sha256Digest();
		try (InputStream input = Files.newInputStream(path)) {
			byte[] buffer = new byte[1024 * 1024];
			int read;
			while ((read = input.read(buffer)) >= 0) {
				digest.update(buffer, 0, read);
			}
		} catch (IOException error) {
			throw new IllegalStateException("Cannot hash " + path, error);
		}
		return hex(digest.digest());
	}

	public static Map<String, Object> runtimeJavaDetails() {
		return ordered(
				"version", System.getProperty("java.version"),
				"vendor", System.getProperty("java.vendor"),
				"vm_name", System.getProperty("java.vm.name"),
				"max_heap_bytes", Runtime.getRuntime().maxMemory(),
				"input_arguments", ManagementFactory.getRuntimeMXBean().getInputArguments()
		);
	}

	public static String matsimVersion() {
		try (InputStream input = HongKongTaxiSmokeOutputAudit.class.getClassLoader()
				.getResourceAsStream("META-INF/maven/org.matsim/matsim/pom.properties")) {
			if (input == null) {
				return "<unknown>";
			}
			Properties properties = new Properties();
			properties.load(input);
			return properties.getProperty("version", "<unknown>");
		} catch (IOException error) {
			return "<unreadable>";
		}
	}

	public static Long linuxPeakResidentSetKib() {
		Path status = Path.of("/proc/self/status");
		if (!Files.isRegularFile(status)) {
			return null;
		}
		try {
			for (String line : Files.readAllLines(status, StandardCharsets.UTF_8)) {
				if (line.startsWith("VmHWM:")) {
					String number = line.substring("VmHWM:".length())
							.trim().split("\\s+")[0];
					return Long.parseLong(number);
				}
			}
			return null;
		} catch (IOException | NumberFormatException error) {
			return null;
		}
	}

	public static void writeJsonAtomically(Path output, Map<String, Object> report) {
		try {
			Path absolute = output.toAbsolutePath().normalize();
			Files.createDirectories(absolute.getParent());
			Path temporary = absolute.resolveSibling(absolute.getFileName() + ".tmp");
			Files.writeString(temporary, toJson(report, 0) + "\n",
					StandardCharsets.UTF_8);
			try {
				Files.move(temporary, absolute, StandardCopyOption.ATOMIC_MOVE);
			} catch (AtomicMoveNotSupportedException error) {
				Files.move(temporary, absolute, StandardCopyOption.REPLACE_EXISTING);
			}
		} catch (IOException error) {
			throw new IllegalStateException("Cannot write validation JSON " + output, error);
		}
	}

	public static String toJson(Object value, int indent) {
		if (value == null) {
			return "null";
		}
		if (value instanceof String text) {
			return "\"" + escapeJson(text) + "\"";
		}
		if (value instanceof Number || value instanceof Boolean) {
			return value.toString();
		}
		if (value instanceof Map<?, ?> map) {
			if (map.isEmpty()) {
				return "{}";
			}
			StringBuilder builder = new StringBuilder("{\n");
			int index = 0;
			for (Map.Entry<?, ?> entry : map.entrySet()) {
				builder.append(" ".repeat(indent + 2))
						.append(toJson(String.valueOf(entry.getKey()), indent + 2))
						.append(": ")
						.append(toJson(entry.getValue(), indent + 2));
				builder.append(++index < map.size() ? ",\n" : "\n");
			}
			return builder.append(" ".repeat(indent)).append("}").toString();
		}
		if (value instanceof Collection<?> collection) {
			if (collection.isEmpty()) {
				return "[]";
			}
			StringBuilder builder = new StringBuilder("[\n");
			int index = 0;
			for (Object item : collection) {
				builder.append(" ".repeat(indent + 2))
						.append(toJson(item, indent + 2));
				builder.append(++index < collection.size() ? ",\n" : "\n");
			}
			return builder.append(" ".repeat(indent)).append("]").toString();
		}
		return toJson(value.toString(), indent);
	}

	public static Map<String, Object> ordered(Object... entries) {
		Map<String, Object> result = new LinkedHashMap<>();
		for (int index = 0; index < entries.length; index += 2) {
			result.put((String) entries[index], entries[index + 1]);
		}
		return result;
	}

	private static Map<String, Double> summarize(List<Double> values) {
		if (values.isEmpty()) {
			return Map.of();
		}
		List<Double> sorted = values.stream().sorted().toList();
		double mean = sorted.stream().mapToDouble(Double::doubleValue).average().orElseThrow();
		return orderedDouble(
				"count", (double) sorted.size(),
				"mean", mean,
				"median", quantile(sorted, 0.50),
				"p10", quantile(sorted, 0.10),
				"p90", quantile(sorted, 0.90),
				"min", sorted.getFirst(),
				"max", sorted.getLast()
		);
	}

	static double quantile(List<Double> sorted, double probability) {
		double position = probability * (sorted.size() - 1);
		int lower = (int) Math.floor(position);
		int upper = (int) Math.ceil(position);
		if (lower == upper) {
			return sorted.get(lower);
		}
		double weight = position - lower;
		return sorted.get(lower) * (1.0 - weight) + sorted.get(upper) * weight;
	}

	private static Map<String, Double> orderedDouble(Object... entries) {
		Map<String, Double> result = new LinkedHashMap<>();
		for (int index = 0; index < entries.length; index += 2) {
			result.put((String) entries[index], (Double) entries[index + 1]);
		}
		return result;
	}

	private static void requireRegularFile(Path path, String label) {
		if (!Files.isRegularFile(path)) {
			throw new IllegalArgumentException(label + " is not a regular file: " + path);
		}
	}

	private static MessageDigest sha256Digest() {
		try {
			return MessageDigest.getInstance("SHA-256");
		} catch (NoSuchAlgorithmException error) {
			throw new IllegalStateException(error);
		}
	}

	private static void update(MessageDigest digest, String text) {
		digest.update(text.getBytes(StandardCharsets.UTF_8));
	}

	private static String hex(byte[] bytes) {
		StringBuilder builder = new StringBuilder(bytes.length * 2);
		for (byte value : bytes) {
			builder.append(String.format(Locale.ROOT, "%02x", value));
		}
		return builder.toString();
	}

	private static boolean close(double left, double right) {
		return Math.abs(left - right) <= 1.0e-8 * Math.max(1.0, Math.abs(left));
	}

	private static String escapeJson(String value) {
		StringBuilder escaped = new StringBuilder();
		for (char character : value.toCharArray()) {
			switch (character) {
				case '"' -> escaped.append("\\\"");
				case '\\' -> escaped.append("\\\\");
				case '\b' -> escaped.append("\\b");
				case '\f' -> escaped.append("\\f");
				case '\n' -> escaped.append("\\n");
				case '\r' -> escaped.append("\\r");
				case '\t' -> escaped.append("\\t");
				default -> {
					if (character < 0x20) {
						escaped.append(String.format(Locale.ROOT,
								"\\u%04x", (int) character));
					} else {
						escaped.append(character);
					}
				}
			}
		}
		return escaped.toString();
	}

	public record RuntimeLogAudit(
			long ptLegHasNoTransitRoute,
			long ptAgentUnknownTransitStop,
			long taxiFareScheduleMismatch,
			long invalidTaxiLegAttribute,
			long unknownMode,
			long taxiRouteExecutionError) {

		public boolean exact() {
			return ptLegHasNoTransitRoute == 0
					&& ptAgentUnknownTransitStop == 0
					&& taxiFareScheduleMismatch == 0
					&& invalidTaxiLegAttribute == 0
					&& unknownMode == 0
					&& taxiRouteExecutionError == 0;
		}

		public Map<String, Object> toMap() {
			return ordered(
					"pt_leg_has_no_transit_route", ptLegHasNoTransitRoute,
					"pt_agent_unknown_transit_stop", ptAgentUnknownTransitStop,
					"taxi_fare_schedule_mismatch", taxiFareScheduleMismatch,
					"invalid_taxi_leg_attribute", invalidTaxiLegAttribute,
					"unknown_mode", unknownMode,
					"taxi_route_execution_error", taxiRouteExecutionError,
					"exact", exact()
			);
		}
	}

	public static final class PlanAudit {
		long persons;
		long plans;
		long activities;
		long mainActivities;
		long legs;
		long fixedNonPtMainLegs;
		long routes;
		long taxiLegs;
		long taxiPersons;
		long invalidTaxiAttributes;
		long invalidRouteDistances;
		long invalidRouteTravelTimes;
		long mainTripIndexSum;
		long missingSelectedPlanScores;
		long finiteSelectedPlanScores;
		long nanSelectedPlanScores;
		long infiniteSelectedPlanScores;
		long finiteTaxiPersonSelectedPlanScores;
		double fareSumHkd;
		String taxiAttributeFingerprintSha256;
		String strictTaxiFingerprintSha256;
		String mainActivityFingerprintSha256;
		String fixedNonPtMainLegFingerprintSha256;
		String planRouteFingerprintSha256;
		final Map<String, Long> modeCounts = new TreeMap<>();
		final Map<String, Long> taxiTypeCounts = new TreeMap<>();
		final Map<String, Long> classificationSourceCounts = new TreeMap<>();
		final Map<String, Long> taxiRoutingModeCounts = new TreeMap<>();
		final List<String> attributeFailureExamples = new ArrayList<>();
		Map<String, Double> allScoreStatistics = Map.of();
		Map<String, Double> taxiPersonScoreStatistics = Map.of();
		Map<String, Double> nonTaxiPersonScoreStatistics = Map.of();

		public boolean allSelectedScoresFinite() {
			return missingSelectedPlanScores == 0
					&& nanSelectedPlanScores == 0
					&& infiniteSelectedPlanScores == 0
					&& finiteSelectedPlanScores == persons
					&& finiteTaxiPersonSelectedPlanScores == taxiPersons;
		}

		public Map<String, Object> toMap() {
			return ordered(
					"persons", persons,
					"plans", plans,
					"activities", activities,
					"main_activities", mainActivities,
					"legs", legs,
					"fixed_non_pt_main_legs", fixedNonPtMainLegs,
					"routes", routes,
					"mode_counts", modeCounts,
					"taxi_legs", taxiLegs,
					"taxi_persons", taxiPersons,
					"taxi_type_counts", taxiTypeCounts,
					"classification_source_counts", classificationSourceCounts,
					"taxi_routing_mode_counts", taxiRoutingModeCounts,
					"invalid_taxi_attributes", invalidTaxiAttributes,
					"attribute_failure_examples", attributeFailureExamples,
					"invalid_route_distances", invalidRouteDistances,
					"invalid_route_travel_times", invalidRouteTravelTimes,
					"fare_sum_hkd", fareSumHkd,
					"main_trip_index_sum", mainTripIndexSum,
					"taxi_attribute_fingerprint_sha256",
							taxiAttributeFingerprintSha256,
					"strict_taxi_fingerprint_sha256",
							strictTaxiFingerprintSha256,
					"main_activity_fingerprint_sha256",
							mainActivityFingerprintSha256,
					"fixed_non_pt_main_leg_fingerprint_sha256",
							fixedNonPtMainLegFingerprintSha256,
					"plan_route_fingerprint_sha256", planRouteFingerprintSha256,
					"missing_selected_plan_scores", missingSelectedPlanScores,
					"finite_selected_plan_scores", finiteSelectedPlanScores,
					"nan_selected_plan_scores", nanSelectedPlanScores,
					"infinite_selected_plan_scores", infiniteSelectedPlanScores,
					"finite_taxi_person_selected_plan_scores",
							finiteTaxiPersonSelectedPlanScores,
					"selected_plan_score_statistics", allScoreStatistics,
					"taxi_person_selected_plan_score_statistics",
							taxiPersonScoreStatistics,
					"non_taxi_person_selected_plan_score_statistics",
							nonTaxiPersonScoreStatistics
			);
		}
	}
}
