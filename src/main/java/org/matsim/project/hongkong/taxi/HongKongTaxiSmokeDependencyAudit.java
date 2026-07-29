package org.matsim.project.hongkong.taxi;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.events.HasPersonId;
import org.matsim.api.core.v01.events.PersonArrivalEvent;
import org.matsim.api.core.v01.events.PersonDepartureEvent;
import org.matsim.api.core.v01.events.PersonStuckEvent;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.api.core.v01.population.Route;
import org.matsim.api.core.v01.Scenario;
import org.matsim.core.api.experimental.events.EventsManager;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.events.EventsUtils;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.population.routes.GenericRouteImpl;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.core.utils.misc.OptionalTime;
import org.matsim.pt.routes.DefaultTransitPassengerRoute;
import org.matsim.pt.routes.TransitPassengerRoute;
import org.matsim.pt.transitSchedule.api.TransitLine;
import org.matsim.pt.transitSchedule.api.TransitRoute;
import org.matsim.pt.transitSchedule.api.TransitStopFacility;
import org.matsim.utils.objectattributes.attributable.Attributes;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Instant;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Comparator;
import java.util.Deque;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.TreeMap;
import java.util.function.Function;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

/**
 * Read-only upstream attribution audit for the failed Hong Kong Taxi smoke.
 *
 * <p>This entry point loads plans through MATSim 2026, reads an existing
 * events file and run log, and writes only compact audit products. It never
 * creates a Controler, QSim, router, replanning strategy, or fleet.
 */
public final class HongKongTaxiSmokeDependencyAudit {

	private static final ObjectMapper JSON = new ObjectMapper()
			.enable(SerializationFeature.INDENT_OUTPUT);
	private static final String ORIGINAL_PLANS_SHA =
			"c73ee48e792e7aebd55b7a2691664ae7f3f4f27d307aef2a6bf58263b3aaafea";
	private static final String TAXI_PLANS_SHA =
			"f4631ab00c6f5027160314f7357e32d969b7588192008c17ac79bf0b3208ce27";
	private static final int EXPECTED_TAXI_LEGS = 37_286;
	private static final int REPORTED_TAXI_EVENTS = 30_230;
	private static final int REPORTED_MISSING_TAXI = 7_056;
	private static final int REPORTED_STUCK = 12_387;
	private static final int REPORTED_PT_REMOVAL_LINES = 237_950;
	private static final Set<String> REQUIRED_CHECK_SCHEMA = Set.of(
			"audit_checkpoint_is_full_sha",
			"matsim_version_is_2026_0",
			"smoke_status_remains_failed",
			"load_validation_is_validated",
			"input_hashes_unchanged",
			"original_pt_categories_close",
			"taxi_pt_categories_close",
			"pt_mapping_unique_and_closed",
			"pt_log_route_rows_complete",
			"pt_log_person_sets_equal",
			"pt_log_person_counts_equal",
			"pt_log_mappings_available",
			"pt_log_route_classes_match_plans",
			"pt_log_lines_match_report",
			"expected_taxi_exact",
			"observed_taxi_departures_match_validation",
			"observed_taxi_arrivals_match_validation",
			"missing_taxi_exact",
			"taxi_departure_arithmetic_closes",
			"taxi_event_unmatched_matches_validation",
			"stuck_events_match_validation",
			"stuck_mode_categories_close",
			"attribution_categories_close",
			"event_collector_counts_close",
			"fare_schedule_mismatch_absent",
			"source_taxi_attributes_valid"
	);

	private static final Pattern PT_REMOVAL = Pattern.compile(
			"^(\\S+)\\s+ERROR\\s+TransitAgentImpl:\\d+ "
					+ "pt-leg has no TransitRoute\\. Removing agent from simulation\\. "
					+ "Agent (\\S+)\\s*$"
	);
	private static final Pattern PT_ROUTE_INFO = Pattern.compile(
			"^\\S+\\s+INFO\\s+TransitAgentImpl:\\d+ route: (\\S+)(?:\\s+(.*))?$"
	);
	private static final Pattern PT_NO_STOP = Pattern.compile(
			"^(\\S+)\\s+ERROR\\s+TransitQSimEngine:\\d+ "
					+ "pt-agent doesn't know to what transit stop to go\\. "
					+ "Removing agent from simulation\\. Agent (\\S+)\\s*$"
	);

	private HongKongTaxiSmokeDependencyAudit() {
	}

	public static void main(String[] args) {
		Options options = Options.parse(args);
		if (Files.exists(options.outputDirectory())) {
			System.err.println("Audit output directory already exists: "
					+ options.outputDirectory());
			System.exit(73);
			return;
		}
		Map<String, Object> report = initialReport(options);
		int exitCode = 1;
		try {
			run(options, report);
			exitCode = Boolean.TRUE.equals(report.get("all_audit_integrity_checks_passed"))
					? 0 : 2;
		} catch (Throwable error) {
			report.put("audit_status", "failed");
			report.put("all_audit_integrity_checks_passed", false);
			report.put("error", errorMap(error));
		}
		report.put("finished_utc", Instant.now().toString());
		report.put("process_exit_code", exitCode);
		writeValidation(options.outputDirectory(), report);
		if (exitCode != 0) {
			System.exit(exitCode);
		}
	}

	private static Map<String, Object> initialReport(Options options) {
		Map<String, Object> report = new LinkedHashMap<>();
		report.put("audit", "hong_kong_taxi_smoke_dependency_audit_v1");
		report.put("audit_status", "running");
		report.put("all_audit_integrity_checks_passed", false);
		report.put("started_utc", Instant.now().toString());
		report.put("audit_checkpoint_sha", options.auditCheckpoint());
		report.put("matsim_version", HongKongTaxiSmokeOutputAudit.matsimVersion());
		report.put("java_version", System.getProperty("java.version"));
		report.put("run_flags", ordered(
				"controler_run", false,
				"qsim_run", false,
				"routing_run", false,
				"replanning_run", false,
				"asc_experiment", false,
				"fleet_run", false
		));
		return report;
	}

	private static void run(Options options, Map<String, Object> report) throws IOException {
		if (Files.exists(options.outputDirectory())) {
			throw new IllegalArgumentException(
					"Audit output directory already exists: " + options.outputDirectory());
		}
		Files.createDirectories(options.outputDirectory());
		validateInputs(options);

		Map<String, Path> inputs = inputPaths(options);
		Map<String, FileSnapshot> before = snapshotFiles(inputs);
		requireSha(before, "original_plans", ORIGINAL_PLANS_SHA);
		requireSha(before, "taxi_plans", TAXI_PLANS_SHA);
		report.put("input_files_before", snapshotsToMap(before));
		report.put("paths", pathsToMap(inputs, options.outputDirectory()));

		Map<String, Object> failedSmoke = readJson(options.failedValidation());
		Map<String, Object> loadValidation = readJson(options.loadValidation());
		requireEquals("failed", failedSmoke.get("status"), "failed smoke status");
		requireEquals("validated", loadValidation.get("status"), "load validation status");
		report.put("smoke_status", failedSmoke.get("status"));
		report.put("smoke_process_exit_code", failedSmoke.get("process_exit_code"));

		Config originalConfig = configuredScenario(options, options.originalPlans());
		validateConfiguredPaths(originalConfig, options);
		Scenario originalScenario = ScenarioUtils.loadScenario(originalConfig);
		SupplyIndex supply = SupplyIndex.from(originalScenario);
		PlanAudit original = auditPlans(
				"original",
				originalScenario,
				supply,
				false
		);
		originalScenario.getPopulation().getPersons().clear();
		originalScenario = null;
		System.gc();

		Config taxiConfig = configuredScenario(options, options.taxiPlans());
		validateConfiguredPaths(taxiConfig, options);
		Scenario taxiScenario = ScenarioUtils.loadScenario(taxiConfig);
		PlanAudit taxi = auditPlans("taxi", taxiScenario, supply, true);

		PtComparison comparison = comparePtRecords(original.ptRecords(), taxi.ptRecords());
		if (comparison.missing() != 0
				|| comparison.extra() != 0
				|| comparison.ambiguous() != 0) {
			throw new IllegalStateException(
					"Cannot establish unique original/Taxi PT mapping: " + comparison.toMap());
		}

		LogAudit logAudit = parseRunLog(options.runLog(), taxi.invalidPtByPerson());
		EventAudit eventAudit = readEvents(
				options.events(),
				taxi.expectedTaxiPersons()
		);
		TaxiReconciliation reconciliation = reconcileTaxiEvents(
				taxi.expectedTaxiByPerson(),
				eventAudit
		);
		List<MissingAttribution> attributions = attributeMissing(
				reconciliation.missing(),
				taxi.invalidPtByPerson(),
				logAudit.mappedRemovalsByPerson(),
				eventAudit.stuckByPerson(),
				eventAudit.lastTaxiPersonEvent()
		);
		Map<String, Long> attributionCounts = countBy(
				attributions,
				MissingAttribution::category
		);
		StuckAudit stuckAudit = auditStuck(
				eventAudit.stuckEvents(),
				taxi.expectedTaxiByPerson(),
				logAudit.removalPersons(),
				supply.networkLinkIds()
		);

		writePtTypeSummary(options.outputDirectory(), original, taxi);
		writePtComparison(options.outputDirectory(), comparison);
		writePtRemovalPersonCounts(options.outputDirectory(), logAudit);
		writeExpectedTaxiLegs(
				options.outputDirectory(),
				taxi.expectedTaxiLegs(),
				eventAudit,
				attributions
		);
		writeMissingAttributions(options.outputDirectory(), attributions);
		writeStuckSummary(options.outputDirectory(), stuckAudit);
		writeRepresentativeExamples(
				options.outputDirectory(),
				original,
				taxi,
				logAudit,
				taxiScenario
		);

		report.put("pt_route_runtime_type_audit", ordered(
				"original", original.summaryMap(),
				"taxi", taxi.summaryMap()
		));
		report.put("pt_route_conversion_comparison", comparison.toMap());
		report.put("pt_removal_log_audit", logAudit.toMap());
		report.put("taxi_event_reconciliation", reconciliation.toMap());
		report.put("missing_taxi_departure_attribution", ordered(
				"total", attributions.size(),
				"category_counts", attributionCounts
		));
		report.put("stuck_event_audit", stuckAudit.toMap());
		report.put("baseline_runtime_comparison", ordered(
				"status", "unavailable",
				"reason", "Existing historical base logs/events lack a verified "
						+ "checkpoint and complete input-SHA manifest; they are not used "
						+ "for causal conclusions."
		));
		report.put("conversion_causality_conclusion", ordered(
				"pt_mapping_unique", true,
				"route_type_changes", comparison.routeTypeChanged(),
				"route_content_changes", comparison.routeContentChanged(),
				"leg_attribute_changes", comparison.legAttributesChanged(),
				"taxi_conversion_changed_pt_routes",
						comparison.routeTypeChanged() != 0
								|| comparison.routeContentChanged() != 0
								|| comparison.legAttributesChanged() != 0
		));

		Map<String, FileSnapshot> after = snapshotFiles(inputs);
		report.put("input_files_after", snapshotsToMap(after));
		Map<String, Boolean> checks = integrityChecks(
				options,
				failedSmoke,
				loadValidation,
				before,
				after,
				original,
				taxi,
				comparison,
				logAudit,
				reconciliation,
				attributions,
				attributionCounts,
				eventAudit,
				stuckAudit
		);
		List<String> failedChecks = checks.entrySet().stream()
				.filter(entry -> !entry.getValue())
				.map(Map.Entry::getKey)
				.toList();
		report.put("required_checks", checks);
		report.put("failed_checks", failedChecks);
		report.put("all_audit_integrity_checks_passed", failedChecks.isEmpty());
		report.put("audit_status", failedChecks.isEmpty() ? "validated" : "failed");
		report.put("output_files", outputSnapshots(options.outputDirectory()));
	}

	private static Config configuredScenario(Options options, Path plans) {
		Config config = ConfigUtils.loadConfig(options.baseConfig().toString());
		config.plans().setInputFile(plans.toString());
		return config;
	}

	private static void validateConfiguredPaths(Config config, Options options) {
		Path context = options.baseConfig().toAbsolutePath().normalize().getParent();
		requireEquals(
				options.network().toAbsolutePath().normalize(),
				resolve(context, config.network().getInputFile()),
				"configured network path"
		);
		requireEquals(
				options.transitSchedule().toAbsolutePath().normalize(),
				resolve(context, config.transit().getTransitScheduleFile()),
				"configured transit schedule path"
		);
	}

	private static Path resolve(Path context, String configured) {
		Path path = Path.of(configured);
		return (path.isAbsolute() ? path : context.resolve(path))
				.toAbsolutePath().normalize();
	}

	private static PlanAudit auditPlans(
			String label,
			Scenario scenario,
			SupplyIndex supply,
			boolean collectTaxi) {
		Map<PtKey, PtRecord> ptRecords = new LinkedHashMap<>();
		Map<String, List<PtRecord>> invalidPtByPerson = new HashMap<>();
		List<TaxiLegRecord> expectedTaxiLegs = new ArrayList<>();
		Map<String, List<TaxiLegRecord>> expectedTaxiByPerson = new LinkedHashMap<>();
		Map<String, Long> routeClasses = new TreeMap<>();
		Map<String, Long> invalidReasons = new TreeMap<>();
		List<Example> examples = new ArrayList<>();
		long persons = 0;
		long ptLegs = 0;
		long routeNull = 0;
		long transitPassenger = 0;
		long generic = 0;
		long defaultTransit = 0;
		long otherLegal = 0;
		long accessMissing = 0;
		long egressMissing = 0;
		long lineMissing = 0;
		long transitRouteMissing = 0;
		long accessNotSchedule = 0;
		long egressNotSchedule = 0;
		long lineNotSchedule = 0;
		long routeNotSchedule = 0;
		long stopLinkIncompatible = 0;
		long stopLinkUnavailable = 0;

		for (Person person : scenario.getPopulation().getPersons().values()) {
			persons++;
			Plan plan = requireSelectedPlan(person);
			List<PlanElement> elements = plan.getPlanElements();
			int taxiOrdinal = 0;
			List<String> precedingModes = new ArrayList<>();
			for (int elementIndex = 0; elementIndex < elements.size(); elementIndex++) {
				PlanElement element = elements.get(elementIndex);
				if (!(element instanceof Leg leg)) {
					continue;
				}
				Activity before = previousActivity(elements, elementIndex);
				Activity after = nextActivity(elements, elementIndex);
				if ("pt".equals(leg.getMode())) {
					ptLegs++;
					RouteAudit routeAudit = classifyRoute(leg, before, after, supply);
					PtKey key = new PtKey(person.getId().toString(), elementIndex);
					PtRecord record = PtRecord.from(
							key,
							leg,
							before,
							after,
							routeAudit
					);
					if (ptRecords.put(key, record) != null) {
						throw new IllegalStateException("Duplicate PT key " + key);
					}
					routeClasses.merge(record.routeClass(), 1L, Long::sum);
					if (routeAudit.routeNull()) {
						routeNull++;
					}
					if (routeAudit.transitPassenger()) {
						transitPassenger++;
					}
					if (routeAudit.genericRoute()) {
						generic++;
					}
					if (routeAudit.defaultTransitRoute()) {
						defaultTransit++;
					}
					if (routeAudit.otherLegalTransitRoute()) {
						otherLegal++;
					}
					accessMissing += bool(routeAudit.accessStopMissing());
					egressMissing += bool(routeAudit.egressStopMissing());
					lineMissing += bool(routeAudit.lineIdMissing());
					transitRouteMissing += bool(routeAudit.transitRouteIdMissing());
					accessNotSchedule += bool(routeAudit.accessStopNotInSchedule());
					egressNotSchedule += bool(routeAudit.egressStopNotInSchedule());
					lineNotSchedule += bool(routeAudit.lineNotInSchedule());
					routeNotSchedule += bool(routeAudit.routeNotInSchedule());
					stopLinkIncompatible += bool(routeAudit.stopLinkIncompatible());
					stopLinkUnavailable += bool(routeAudit.stopLinkCheckUnavailable());
					if (routeAudit.invalid()) {
						invalidPtByPerson.computeIfAbsent(
								person.getId().toString(),
								ignored -> new ArrayList<>()
						).add(record);
						for (String reason : routeAudit.invalidReasons()) {
							invalidReasons.merge(reason, 1L, Long::sum);
						}
						addExample(examples, "invalid_pt_" + label, record.toExample());
					}
				}
				if (collectTaxi && HongKongTaxiScoringParameters.TAXI_MODE.equals(leg.getMode())) {
					HongKongTaxiLegAttributes.Metadata metadata =
							HongKongTaxiLegAttributes.readAndValidate(
									leg,
									person.getId(),
									HongKongTaxiScoringParameters.centralV1()
							);
					TaxiLegRecord taxi = TaxiLegRecord.from(
							person,
							taxiOrdinal,
							elementIndex,
							leg,
							metadata,
							List.copyOf(precedingModes)
					);
					expectedTaxiLegs.add(taxi);
					expectedTaxiByPerson.computeIfAbsent(
							taxi.personId(),
							ignored -> new ArrayList<>()
					).add(taxi);
					taxiOrdinal++;
				}
				precedingModes.add(leg.getMode());
			}
		}
		invalidPtByPerson.values().forEach(records ->
				records.sort(Comparator.comparingInt(PtRecord::planElementIndex)));
		return new PlanAudit(
				label,
				persons,
				ptLegs,
				routeNull,
				transitPassenger,
				generic,
				defaultTransit,
				otherLegal,
				accessMissing,
				egressMissing,
				lineMissing,
				transitRouteMissing,
				accessNotSchedule,
				egressNotSchedule,
				lineNotSchedule,
				routeNotSchedule,
				stopLinkIncompatible,
				stopLinkUnavailable,
				Map.copyOf(routeClasses),
				Map.copyOf(invalidReasons),
				Map.copyOf(ptRecords),
				Map.copyOf(invalidPtByPerson),
				List.copyOf(expectedTaxiLegs),
				Map.copyOf(expectedTaxiByPerson),
				List.copyOf(examples)
		);
	}

	static RouteAudit classifyRoute(
			Leg leg,
			Activity before,
			Activity after,
			SupplyIndex supply) {
		Route route = leg.getRoute();
		boolean routeNull = route == null;
		boolean transitPassenger = route instanceof TransitPassengerRoute;
		boolean generic = route instanceof GenericRouteImpl;
		boolean defaultTransit = route instanceof DefaultTransitPassengerRoute;
		boolean otherLegal = transitPassenger && !defaultTransit;
		Id<TransitStopFacility> access = null;
		Id<TransitStopFacility> egress = null;
		Id<TransitLine> line = null;
		Id<TransitRoute> transitRoute = null;
		if (route instanceof TransitPassengerRoute passengerRoute) {
			access = passengerRoute.getAccessStopId();
			egress = passengerRoute.getEgressStopId();
			line = passengerRoute.getLineId();
			transitRoute = passengerRoute.getRouteId();
		}
		boolean accessMissing = access == null;
		boolean egressMissing = egress == null;
		boolean lineMissing = line == null;
		boolean routeIdMissing = transitRoute == null;
		boolean accessNotSchedule =
				access != null && !supply.stopLinks().containsKey(access.toString());
		boolean egressNotSchedule =
				egress != null && !supply.stopLinks().containsKey(egress.toString());
		boolean lineNotSchedule =
				line != null && !supply.lineRoutes().containsKey(line.toString());
		boolean routeNotSchedule = line != null
				&& transitRoute != null
				&& (!supply.lineRoutes().containsKey(line.toString())
				|| !supply.lineRoutes().get(line.toString()).contains(transitRoute.toString()));
		boolean unavailable = !transitPassenger
				|| accessMissing
				|| egressMissing
				|| accessNotSchedule
				|| egressNotSchedule;
		boolean incompatible = false;
		if (!unavailable) {
			String accessLink = supply.stopLinks().get(access.toString());
			String egressLink = supply.stopLinks().get(egress.toString());
			incompatible = "<null>".equals(accessLink)
					|| "<null>".equals(egressLink)
					|| !supply.networkLinkIds().contains(accessLink)
					|| !supply.networkLinkIds().contains(egressLink);
		}
		List<String> reasons = new ArrayList<>();
		if (routeNull) {
			reasons.add("route_null");
		}
		if (!transitPassenger) {
			reasons.add("not_transit_passenger_route");
		}
		if (accessMissing) {
			reasons.add("access_stop_missing");
		}
		if (egressMissing) {
			reasons.add("egress_stop_missing");
		}
		if (lineMissing) {
			reasons.add("line_id_missing");
		}
		if (routeIdMissing) {
			reasons.add("transit_route_id_missing");
		}
		if (accessNotSchedule) {
			reasons.add("access_stop_not_in_schedule");
		}
		if (egressNotSchedule) {
			reasons.add("egress_stop_not_in_schedule");
		}
		if (lineNotSchedule) {
			reasons.add("line_not_in_schedule");
		}
		if (routeNotSchedule) {
			reasons.add("route_not_in_schedule");
		}
		if (incompatible) {
			reasons.add("stop_link_execution_position_incompatible");
		}
		return new RouteAudit(
				routeNull,
				transitPassenger,
				generic,
				defaultTransit,
				otherLegal,
				accessMissing,
				egressMissing,
				lineMissing,
				routeIdMissing,
				accessNotSchedule,
				egressNotSchedule,
				lineNotSchedule,
				routeNotSchedule,
				incompatible,
				unavailable,
				List.copyOf(reasons)
		);
	}

	static PtComparison comparePtRecords(
			Map<PtKey, PtRecord> original,
			Map<PtKey, PtRecord> taxi) {
		long matched = 0;
		long missing = 0;
		long extra = 0;
		long ambiguous = 0;
		long identical = 0;
		long typeChanged = 0;
		long contentChanged = 0;
		long attributesChanged = 0;
		long modeChanged = 0;
		long routingModeChanged = 0;
		for (Map.Entry<PtKey, PtRecord> entry : original.entrySet()) {
			PtRecord right = taxi.get(entry.getKey());
			if (right == null) {
				missing++;
				continue;
			}
			PtRecord left = entry.getValue();
			if (!left.activitySignature().equals(right.activitySignature())) {
				ambiguous++;
				continue;
			}
			matched++;
			boolean typeSame = left.routeClass().equals(right.routeClass())
					&& left.transitPassenger() == right.transitPassenger();
			boolean contentSame = left.routeContent().equals(right.routeContent());
			boolean attrsSame = left.legAttributes().equals(right.legAttributes());
			boolean modeSame = left.mode().equals(right.mode());
			boolean routingSame = left.routingMode().equals(right.routingMode());
			typeChanged += bool(!typeSame);
			contentChanged += bool(!contentSame);
			attributesChanged += bool(!attrsSame);
			modeChanged += bool(!modeSame);
			routingModeChanged += bool(!routingSame);
			if (typeSame && contentSame && attrsSame && modeSame && routingSame) {
				identical++;
			}
		}
		for (PtKey key : taxi.keySet()) {
			if (!original.containsKey(key)) {
				extra++;
			}
		}
		return new PtComparison(
				original.size(),
				taxi.size(),
				matched,
				missing,
				extra,
				ambiguous,
				identical,
				typeChanged,
				contentChanged,
				attributesChanged,
				modeChanged,
				routingModeChanged
		);
	}

	private static LogAudit parseRunLog(
			Path path,
			Map<String, List<PtRecord>> invalidPtByPerson) throws IOException {
		List<RemovalRecord> removals = new ArrayList<>();
		Map<String, Long> noStopByPerson = new HashMap<>();
		Map<String, Long> removalByPerson = new HashMap<>();
		Map<String, Long> routeClassCounts = new TreeMap<>();
		Map<String, String> routeDescriptionExamples = new TreeMap<>();
		Deque<RemovalRecord> pending = new ArrayDeque<>();
		long lineNumber = 0;
		long noStopLines = 0;
		long fareScheduleMismatchLines = 0;
		long taxiAttributeErrorLines = 0;
		String firstTimestamp = null;
		long firstLine = -1;
		String firstPerson = null;
		try (BufferedReader reader = Files.newBufferedReader(path, StandardCharsets.UTF_8)) {
			String line;
			while ((line = reader.readLine()) != null) {
				lineNumber++;
				if (line.toLowerCase(Locale.ROOT).contains("fare schedule mismatch")) {
					fareScheduleMismatchLines++;
				}
				if (line.contains("Invalid Hong Kong taxi leg attribute")) {
					taxiAttributeErrorLines++;
				}
				Matcher removal = PT_REMOVAL.matcher(line);
				if (removal.matches()) {
					RemovalRecord record = new RemovalRecord(
							removal.group(2),
							removal.group(1),
							lineNumber
					);
					removals.add(record);
					pending.addLast(record);
					removalByPerson.merge(record.personId, 1L, Long::sum);
					if (firstTimestamp == null) {
						firstTimestamp = record.logTimestamp;
						firstLine = lineNumber;
						firstPerson = record.personId;
					}
					continue;
				}
				Matcher routeInfo = PT_ROUTE_INFO.matcher(line);
				if (routeInfo.matches() && !pending.isEmpty()) {
					RemovalRecord record = pending.removeFirst();
					record.routeClass = routeInfo.group(1);
					record.routeDescription = routeInfo.group(2) == null
							? "" : routeInfo.group(2);
					routeClassCounts.merge(record.routeClass, 1L, Long::sum);
					routeDescriptionExamples.putIfAbsent(
							record.routeClass,
							record.routeDescription
					);
					continue;
				}
				Matcher noStop = PT_NO_STOP.matcher(line);
				if (noStop.matches()) {
					noStopLines++;
					noStopByPerson.merge(noStop.group(2), 1L, Long::sum);
				}
			}
		}

		Map<String, List<RemovalRecord>> byPerson = removals.stream()
				.collect(Collectors.groupingBy(
						record -> record.personId,
						LinkedHashMap::new,
						Collectors.toList()
				));
		Map<String, List<RemovalRecord>> mappedByPerson = new LinkedHashMap<>();
		Set<PtKey> mappedKeys = new LinkedHashSet<>();
		long unavailableMappings = 0;
		long routeClassMismatches = 0;
		for (Map.Entry<String, List<RemovalRecord>> entry : byPerson.entrySet()) {
			List<PtRecord> invalid = invalidPtByPerson.getOrDefault(
					entry.getKey(),
					List.of()
			);
			List<RemovalRecord> personRemovals = entry.getValue();
			for (int index = 0; index < personRemovals.size(); index++) {
				RemovalRecord removal = personRemovals.get(index);
				if (index >= invalid.size()) {
					unavailableMappings++;
					continue;
				}
				PtRecord pt = invalid.get(index);
				removal.mappedPt = pt;
				mappedKeys.add(pt.key());
				if (!removal.routeClass.isBlank()
						&& !removal.routeClass.equals(pt.routeClass())) {
					routeClassMismatches++;
				}
			}
			mappedByPerson.put(entry.getKey(), List.copyOf(personRemovals));
		}
		return new LogAudit(
				removals.size(),
				removalByPerson.size(),
				mappedKeys.size(),
				noStopLines,
				noStopByPerson.size(),
				removalByPerson.keySet().equals(noStopByPerson.keySet()),
				pending.size(),
				unavailableMappings,
				routeClassMismatches,
				fareScheduleMismatchLines,
				taxiAttributeErrorLines,
				firstTimestamp,
				firstLine,
				firstPerson,
				Map.copyOf(removalByPerson),
				Map.copyOf(noStopByPerson),
				Map.copyOf(routeClassCounts),
				Map.copyOf(routeDescriptionExamples),
				Map.copyOf(mappedByPerson),
				Set.copyOf(removalByPerson.keySet())
		);
	}

	private static EventAudit readEvents(
			Path events,
			Set<String> taxiPersons) {
		EventCollector collector = new EventCollector(taxiPersons);
		EventsManager manager = EventsUtils.createEventsManager();
		manager.addHandler(collector);
		EventsUtils.readEvents(manager, events.toString());
		return collector.finish();
	}

	static TaxiReconciliation reconcileTaxiEvents(
			Map<String, List<TaxiLegRecord>> expectedByPerson,
			EventAudit events) {
		List<TaxiLegRecord> missing = new ArrayList<>();
		long expected = 0;
		long matchedDepartures = 0;
		long unexpectedDepartures = 0;
		long unmatchedDepartures = 0;
		long unmatchedArrivals = 0;
		for (Map.Entry<String, List<TaxiLegRecord>> entry : expectedByPerson.entrySet()) {
			int expectedCount = entry.getValue().size();
			int departures = events.taxiDeparturesByPerson()
					.getOrDefault(entry.getKey(), List.of()).size();
			int arrivals = events.taxiArrivalsByPerson()
					.getOrDefault(entry.getKey(), List.of()).size();
			expected += expectedCount;
			matchedDepartures += Math.min(expectedCount, departures);
			unexpectedDepartures += Math.max(0, departures - expectedCount);
			unmatchedDepartures += Math.max(0, departures - arrivals);
			unmatchedArrivals += Math.max(0, arrivals - departures);
			for (int ordinal = departures; ordinal < expectedCount; ordinal++) {
				missing.add(entry.getValue().get(ordinal));
			}
		}
		for (Map.Entry<String, List<ObservedTaxiEvent>> entry
				: events.taxiDeparturesByPerson().entrySet()) {
			if (!expectedByPerson.containsKey(entry.getKey())) {
				unexpectedDepartures += entry.getValue().size();
			}
		}
		for (Map.Entry<String, List<ObservedTaxiEvent>> entry
				: events.taxiArrivalsByPerson().entrySet()) {
			if (!expectedByPerson.containsKey(entry.getKey())) {
				unmatchedArrivals += entry.getValue().size();
			}
		}
		return new TaxiReconciliation(
				expected,
				events.taxiDepartureCount(),
				events.taxiArrivalCount(),
				matchedDepartures,
				missing.size(),
				events.duplicateTaxiDepartures(),
				unexpectedDepartures,
				unmatchedDepartures,
				unmatchedArrivals,
				List.copyOf(missing)
		);
	}

	private static List<MissingAttribution> attributeMissing(
			List<TaxiLegRecord> missing,
			Map<String, List<PtRecord>> invalidPtByPerson,
			Map<String, List<RemovalRecord>> removalsByPerson,
			Map<String, List<StuckRecord>> stuckByPerson,
			Map<String, LastEvent> lastEvents) {
		List<MissingAttribution> results = new ArrayList<>();
		for (TaxiLegRecord taxi : missing) {
			List<PtRecord> invalidBefore = invalidPtByPerson
					.getOrDefault(taxi.personId(), List.of()).stream()
					.filter(pt -> pt.planElementIndex() < taxi.planElementIndex())
					.toList();
			List<RemovalRecord> removalsBefore = removalsByPerson
					.getOrDefault(taxi.personId(), List.of()).stream()
					.filter(removal -> removal.mappedPt != null)
					.filter(removal ->
							removal.mappedPt.planElementIndex() < taxi.planElementIndex())
					.toList();
			List<StuckRecord> stuckBefore = stuckByPerson
					.getOrDefault(taxi.personId(), List.of()).stream()
					.filter(stuck -> taxi.departureTimeSeconds() != null
							&& stuck.time() <= taxi.departureTimeSeconds())
					.toList();
			boolean evidenceUnavailable =
					taxi.departureTimeSeconds() == null
							&& !stuckByPerson.getOrDefault(taxi.personId(), List.of()).isEmpty();
			String category = categorizeMissing(
					!removalsBefore.isEmpty(),
					!stuckBefore.isEmpty(),
					stuckBefore.stream().map(StuckRecord::mode).collect(Collectors.toSet()),
					!invalidBefore.isEmpty(),
					evidenceUnavailable,
					lastEvents.containsKey(taxi.personId())
			);
			LastEvent last = lastEvents.get(taxi.personId());
			results.add(new MissingAttribution(
					taxi,
					category,
					invalidBefore.stream()
							.map(pt -> Integer.toString(pt.planElementIndex()))
							.collect(Collectors.joining("|")),
					removalsBefore.stream()
							.map(removal -> Integer.toString(
									removal.mappedPt.planElementIndex()))
							.collect(Collectors.joining("|")),
					stuckBefore.stream()
							.map(stuck -> stuck.mode() + "@" + stuck.time())
							.collect(Collectors.joining("|")),
					last == null ? "" : last.eventType(),
					last == null ? null : last.time()
			));
		}
		return List.copyOf(results);
	}

	static String categorizeMissing(
			boolean ptRemovalBefore,
			boolean stuckBefore,
			Set<String> stuckModes,
			boolean invalidPtBefore,
			boolean unavailableEvidence,
			boolean hasLastEvent) {
		if (ptRemovalBefore && stuckBefore) {
			return "multiple_blockers";
		}
		if (ptRemovalBefore) {
			return "invalid_pt_before_taxi_agent_removed";
		}
		if (stuckBefore) {
			if (stuckModes.size() != 1) {
				return "multiple_blockers";
			}
			return switch (stuckModes.iterator().next()) {
				case "car" -> "car_stuck_before_taxi";
				case "walk" -> "walk_stuck_before_taxi";
				case "<null>" -> "null_mode_stuck_before_taxi";
				default -> "other_mode_stuck_before_taxi";
			};
		}
		if (invalidPtBefore) {
			return "invalid_pt_before_taxi_without_observed_removal";
		}
		if (unavailableEvidence) {
			return "unavailable_evidence";
		}
		return hasLastEvent
				? "taxi_departure_missing_without_observed_upstream_blocker"
				: "unavailable_evidence";
	}

	private static StuckAudit auditStuck(
			List<StuckRecord> stuck,
			Map<String, List<TaxiLegRecord>> taxiByPerson,
			Set<String> removalPersons,
			Set<String> networkLinks) {
		Map<String, Long> modes = countBy(stuck, StuckRecord::mode);
		Map<String, Long> hours = countBy(
				stuck,
				record -> Integer.toString((int) Math.floor(record.time() / 3600.0))
		);
		Map<String, Long> links = countBy(stuck, StuckRecord::linkId);
		Set<String> unique = stuck.stream()
				.map(StuckRecord::personId)
				.collect(Collectors.toSet());
		long taxiPersonEvents = stuck.stream()
				.filter(record -> taxiByPerson.containsKey(record.personId()))
				.count();
		long taxiPersons = unique.stream().filter(taxiByPerson::containsKey).count();
		long beforeTaxi = stuck.stream().filter(record ->
				taxiByPerson.getOrDefault(record.personId(), List.of()).stream()
						.anyMatch(taxi -> taxi.departureTimeSeconds() != null
								&& record.time() <= taxi.departureTimeSeconds())
		).count();
		long removalIntersection =
				unique.stream().filter(removalPersons::contains).count();
		long missingNetworkLinks = stuck.stream()
				.filter(record -> !"<null>".equals(record.linkId()))
				.filter(record -> !networkLinks.contains(record.linkId()))
				.count();
		double maxTime = stuck.stream().mapToDouble(StuckRecord::time).max().orElse(Double.NaN);
		long atMaxTime = stuck.stream().filter(record -> record.time() == maxTime).count();
		return new StuckAudit(
				stuck.size(),
				unique.size(),
				Map.copyOf(modes),
				Map.copyOf(hours),
				Map.copyOf(links),
				taxiPersonEvents,
				taxiPersons,
				beforeTaxi,
				removalIntersection,
				missingNetworkLinks,
				maxTime,
				atMaxTime,
				List.copyOf(stuck.stream().limit(20).toList())
		);
	}

	private static Map<String, Boolean> integrityChecks(
			Options options,
			Map<String, Object> failedSmoke,
			Map<String, Object> loadValidation,
			Map<String, FileSnapshot> before,
			Map<String, FileSnapshot> after,
			PlanAudit original,
			PlanAudit taxi,
			PtComparison comparison,
			LogAudit log,
			TaxiReconciliation reconciliation,
			List<MissingAttribution> attributions,
			Map<String, Long> attributionCounts,
			EventAudit events,
			StuckAudit stuck) {
		Map<String, Boolean> checks = new LinkedHashMap<>();
		checks.put("audit_checkpoint_is_full_sha",
				options.auditCheckpoint().matches("[0-9a-f]{40}"));
		checks.put("matsim_version_is_2026_0",
				"2026.0".equals(HongKongTaxiSmokeOutputAudit.matsimVersion()));
		checks.put("smoke_status_remains_failed",
				"failed".equals(failedSmoke.get("status")));
		checks.put("load_validation_is_validated",
				"validated".equals(loadValidation.get("status")));
		checks.put("input_hashes_unchanged", before.equals(after));
		checks.put("original_pt_categories_close",
				original.routeClassCounts().values().stream()
						.mapToLong(Long::longValue).sum() == original.ptLegs());
		checks.put("taxi_pt_categories_close",
				taxi.routeClassCounts().values().stream()
						.mapToLong(Long::longValue).sum() == taxi.ptLegs());
		checks.put("pt_mapping_unique_and_closed",
				comparison.matched() == original.ptLegs()
						&& comparison.matched() == taxi.ptLegs()
						&& comparison.missing() == 0
						&& comparison.extra() == 0
						&& comparison.ambiguous() == 0);
		checks.put("pt_log_route_rows_complete", log.pendingRouteRows() == 0);
		checks.put("pt_log_person_sets_equal", log.personSetsEqual());
		checks.put("pt_log_person_counts_equal",
				log.removalCountsByPerson().equals(log.noStopCountsByPerson()));
		checks.put("pt_log_mappings_available", log.unavailableMappings() == 0);
		checks.put("pt_log_route_classes_match_plans", log.routeClassMismatches() == 0);
		checks.put("pt_log_lines_match_report",
				log.removalLines() == REPORTED_PT_REMOVAL_LINES);
		checks.put("expected_taxi_exact",
				reconciliation.expected() == EXPECTED_TAXI_LEGS);
		Map<String, Object> iterationZero = nestedMap(
				nestedMap(failedSmoke, "iteration_event_audits"),
				"0"
		);
		checks.put("observed_taxi_departures_match_validation",
				reconciliation.observedDepartures() == REPORTED_TAXI_EVENTS
						&& reconciliation.observedDepartures()
						== nestedLong(iterationZero, "taxi_departures"));
		checks.put("observed_taxi_arrivals_match_validation",
				reconciliation.observedArrivals() == REPORTED_TAXI_EVENTS
						&& reconciliation.observedArrivals()
						== nestedLong(iterationZero, "taxi_arrivals"));
		checks.put("missing_taxi_exact",
				reconciliation.missingDepartures() == REPORTED_MISSING_TAXI);
		checks.put("taxi_departure_arithmetic_closes",
				reconciliation.expected() + reconciliation.unexpectedDepartures()
						== reconciliation.observedDepartures()
						+ reconciliation.missingDepartures());
		checks.put("taxi_event_unmatched_matches_validation",
				reconciliation.unmatchedDepartures() == 0
						&& reconciliation.unmatchedArrivals() == 0
						&& nestedLong(iterationZero, "unmatched_taxi_departures") == 0
						&& nestedLong(iterationZero, "unmatched_taxi_arrivals") == 0);
		checks.put("stuck_events_match_validation",
				stuck.totalEvents() == REPORTED_STUCK
						&& stuck.totalEvents()
						== nestedLong(iterationZero, "total_stuck_events"));
		checks.put("stuck_mode_categories_close",
				stuck.modeCounts().values().stream().mapToLong(Long::longValue).sum()
						== stuck.totalEvents());
		checks.put("attribution_categories_close",
				attributions.size() == reconciliation.missingDepartures()
						&& attributionCounts.values().stream()
						.mapToLong(Long::longValue).sum() == attributions.size());
		checks.put("event_collector_counts_close",
				events.taxiDepartureCount() == reconciliation.observedDepartures()
						&& events.taxiArrivalCount() == reconciliation.observedArrivals()
						&& events.stuckEvents().size() == stuck.totalEvents());
		checks.put("fare_schedule_mismatch_absent",
				log.fareScheduleMismatchLines() == 0
						&& log.taxiAttributeErrorLines() == 0);
		checks.put("source_taxi_attributes_valid",
				taxi.expectedTaxiLegs().size() == EXPECTED_TAXI_LEGS);
		if (!checks.keySet().equals(REQUIRED_CHECK_SCHEMA)) {
			throw new IllegalStateException(
					"Required-check schema drift: actual=" + checks.keySet()
							+ ", expected=" + REQUIRED_CHECK_SCHEMA);
		}
		return checks;
	}

	@SuppressWarnings("unchecked")
	private static Map<String, Object> nestedMap(
			Map<String, Object> parent,
			String key) {
		Object value = parent.get(key);
		if (!(value instanceof Map<?, ?>)) {
			throw new IllegalStateException("Missing JSON object " + key);
		}
		return (Map<String, Object>) value;
	}

	private static long nestedLong(Map<String, Object> parent, String key) {
		Object value = parent.get(key);
		if (!(value instanceof Number number)) {
			throw new IllegalStateException("Missing JSON number " + key);
		}
		return number.longValue();
	}

	static Set<String> requiredCheckSchema() {
		return REQUIRED_CHECK_SCHEMA;
	}

	private static void writePtTypeSummary(
			Path output,
			PlanAudit original,
			PlanAudit taxi) throws IOException {
		List<List<?>> rows = new ArrayList<>();
		for (PlanAudit audit : List.of(original, taxi)) {
			audit.summaryMap().forEach((key, value) ->
					rows.add(List.of(audit.label(), key, value)));
			audit.routeClassCounts().forEach((key, value) ->
					rows.add(List.of(audit.label(), "runtime_class:" + key, value)));
			audit.invalidReasonCounts().forEach((key, value) ->
					rows.add(List.of(audit.label(), "invalid_reason:" + key, value)));
		}
		writeCsv(
				output.resolve("pt_route_runtime_type_summary.csv"),
				List.of("plans_version", "metric", "count"),
				rows
		);
	}

	private static void writePtComparison(Path output, PtComparison comparison)
			throws IOException {
		List<? extends List<?>> rows = comparison.toMap().entrySet().stream()
				.map(entry -> (List<?>) List.of(entry.getKey(), entry.getValue()))
				.toList();
		writeCsv(
				output.resolve("pt_route_conversion_comparison.csv"),
				List.of("metric", "count"),
				rows
		);
	}

	private static void writePtRemovalPersonCounts(Path output, LogAudit audit)
			throws IOException {
		List<? extends List<?>> rows = audit.removalCountsByPerson().entrySet().stream()
				.sorted(Map.Entry.comparingByKey())
				.map(entry -> (List<?>) List.of(
						entry.getKey(),
						entry.getValue(),
						audit.noStopCountsByPerson().getOrDefault(entry.getKey(), 0L)
				))
				.toList();
		writeCsv(
				output.resolve("pt_removal_person_counts.csv"),
				List.of("person_id", "pt_no_transit_route_lines", "pt_no_stop_lines"),
				rows
		);
	}

	private static void writeExpectedTaxiLegs(
			Path output,
			List<TaxiLegRecord> expected,
			EventAudit events,
			List<MissingAttribution> attributions) throws IOException {
		Map<TaxiKey, MissingAttribution> missing = attributions.stream()
				.collect(Collectors.toMap(
						item -> item.taxi().key(),
						Function.identity()
				));
		List<List<?>> rows = new ArrayList<>(expected.size());
		for (TaxiLegRecord taxi : expected) {
			int departures = events.taxiDeparturesByPerson()
					.getOrDefault(taxi.personId(), List.of()).size();
			int arrivals = events.taxiArrivalsByPerson()
					.getOrDefault(taxi.personId(), List.of()).size();
			MissingAttribution attribution = missing.get(taxi.key());
			rows.add(List.of(
					taxi.personId(),
					taxi.taxiOrdinal(),
					taxi.mainTripIndex(),
					taxi.planElementIndex(),
					nullable(taxi.departureTimeSeconds()),
					taxi.precedingLegModes(),
					taxi.fareHkd(),
					taxi.taxiType(),
					taxi.classificationSource(),
					taxi.taxiOrdinal() < departures,
					taxi.taxiOrdinal() < arrivals,
					attribution == null ? "" : attribution.category()
			));
		}
		writeCsv(
				output.resolve("expected_taxi_leg_audit.csv"),
				List.of(
						"person_id",
						"taxi_ordinal",
						"hk_taxi_main_trip_index",
						"plan_element_index",
						"departure_time_seconds",
						"preceding_leg_modes",
						"fare_hkd",
						"taxi_type",
						"classification_source",
						"observed_departure",
						"observed_arrival",
						"missing_attribution"
				),
				rows
		);
	}

	private static void writeMissingAttributions(
			Path output,
			List<MissingAttribution> attributions) throws IOException {
		List<? extends List<?>> rows = attributions.stream().map(item -> (List<?>) List.of(
				item.taxi().personId(),
				item.taxi().taxiOrdinal(),
				item.taxi().mainTripIndex(),
				item.taxi().planElementIndex(),
				nullable(item.taxi().departureTimeSeconds()),
				item.taxi().precedingLegModes(),
				item.taxi().fareHkd(),
				item.taxi().taxiType(),
				item.taxi().classificationSource(),
				item.category(),
				item.invalidPtBeforeElementIndexes(),
				item.removedPtBeforeElementIndexes(),
				item.stuckBefore(),
				item.lastEventType(),
				nullable(item.lastEventTime())
		)).toList();
		writeCsv(
				output.resolve("missing_taxi_departure_attribution.csv"),
				List.of(
						"person_id",
						"taxi_ordinal",
						"hk_taxi_main_trip_index",
						"plan_element_index",
						"expected_departure_time_seconds",
						"preceding_leg_modes",
						"fare_hkd",
						"taxi_type",
						"classification_source",
						"attribution_category",
						"invalid_pt_before_element_indexes",
						"removed_pt_before_element_indexes",
						"stuck_before",
						"last_observed_event_type",
						"last_observed_event_time"
				),
				rows
		);
	}

	private static void writeStuckSummary(Path output, StuckAudit audit)
			throws IOException {
		List<List<?>> rows = new ArrayList<>();
		audit.modeCounts().forEach((key, value) ->
				rows.add(List.of("mode", key, value)));
		audit.hourCounts().forEach((key, value) ->
				rows.add(List.of("hour", key, value)));
		audit.linkCounts().forEach((key, value) ->
				rows.add(List.of("link", key, value)));
		rows.add(List.of("metric", "total_events", audit.totalEvents()));
		rows.add(List.of("metric", "unique_persons", audit.uniquePersons()));
		rows.add(List.of("metric", "taxi_person_events", audit.taxiPersonEvents()));
		rows.add(List.of("metric", "taxi_persons", audit.taxiPersons()));
		rows.add(List.of("metric", "stuck_before_expected_taxi", audit.beforeTaxiEvents()));
		rows.add(List.of("metric", "pt_removal_person_intersection",
				audit.ptRemovalPersonIntersection()));
		rows.add(List.of("metric", "missing_network_links", audit.missingNetworkLinks()));
		rows.add(List.of("metric", "max_time_seconds", audit.maxTimeSeconds()));
		rows.add(List.of("metric", "events_at_max_time", audit.eventsAtMaxTime()));
		writeCsv(
				output.resolve("stuck_event_summary.csv"),
				List.of("dimension", "key", "count"),
				rows
		);
	}

	private static void writeRepresentativeExamples(
			Path output,
			PlanAudit original,
			PlanAudit taxi,
			LogAudit log,
			Scenario taxiScenario) throws IOException {
		List<List<?>> rows = new ArrayList<>();
		for (Example example : original.examples()) {
			rows.add(example.toRow());
		}
		for (Example example : taxi.examples()) {
			rows.add(example.toRow());
		}
		if (log.firstPerson() != null) {
			Person person = taxiScenario.getPopulation().getPersons().get(
					Id.createPersonId(log.firstPerson())
			);
			if (person != null) {
				Plan plan = requireSelectedPlan(person);
				for (int index = 0; index < plan.getPlanElements().size(); index++) {
					PlanElement element = plan.getPlanElements().get(index);
					rows.add(List.of(
							"first_pt_removal_person_plan_context",
							person.getId().toString(),
							index,
							element.getClass().getName(),
							describeElement(element)
					));
				}
			}
		}
		rows.add(List.of(
				"first_pt_removal_log",
				nullable(log.firstPerson()),
				log.firstLine(),
				nullable(log.firstTimestamp()),
				""
		));
		writeCsv(
				output.resolve("representative_failure_examples.csv"),
				List.of("category", "person_id", "position", "runtime_class", "details"),
				rows
		);
	}

	private static String describeElement(PlanElement element) {
		if (element instanceof Activity activity) {
			return "activity_type=" + activity.getType()
					+ ";link=" + nullable(activity.getLinkId());
		}
		if (element instanceof Leg leg) {
			Route route = leg.getRoute();
			return "mode=" + leg.getMode()
					+ ";routingMode=" + nullable(leg.getRoutingMode())
					+ ";departure=" + optional(leg.getDepartureTime())
					+ ";routeClass=" + (route == null ? "<null>" : route.getClass().getName())
					+ ";routeDescription=" + (route == null
					? "<null>" : nullable(route.getRouteDescription()));
		}
		return element.toString();
	}

	private static void writeCsv(
			Path path,
			List<String> header,
			Collection<? extends List<?>> rows) throws IOException {
		try (BufferedWriter writer = Files.newBufferedWriter(
				path,
				StandardCharsets.UTF_8,
				StandardOpenOption.CREATE_NEW
		)) {
			writer.write(header.stream().map(HongKongTaxiSmokeDependencyAudit::csv)
					.collect(Collectors.joining(",")));
			writer.newLine();
			for (List<?> row : rows) {
				writer.write(row.stream()
						.map(HongKongTaxiSmokeDependencyAudit::csv)
						.collect(Collectors.joining(",")));
				writer.newLine();
			}
		}
	}

	private static String csv(Object value) {
		String text = value == null ? "" : value.toString();
		return "\"" + text.replace("\"", "\"\"") + "\"";
	}

	private static void writeValidation(Path output, Map<String, Object> report) {
		try {
			Files.createDirectories(output);
			JSON.writeValue(
					output.resolve("taxi_smoke_dependency_validation.json").toFile(),
					report
			);
		} catch (IOException error) {
			throw new IllegalStateException("Cannot write dependency validation", error);
		}
	}

	private static Map<String, Object> readJson(Path path) throws IOException {
		return JSON.readValue(path.toFile(), new TypeReference<>() {
		});
	}

	private static Map<String, FileSnapshot> snapshotFiles(Map<String, Path> paths) {
		Map<String, FileSnapshot> snapshots = new LinkedHashMap<>();
		paths.forEach((name, path) -> snapshots.put(
				name,
				new FileSnapshot(
						path.toAbsolutePath().normalize().toString(),
						size(path),
						HongKongTaxiSmokeOutputAudit.sha256(path)
				)
		));
		return Map.copyOf(snapshots);
	}

	private static long size(Path path) {
		try {
			return Files.size(path);
		} catch (IOException error) {
			throw new IllegalStateException("Cannot size " + path, error);
		}
	}

	private static Map<String, Path> inputPaths(Options options) {
		Config config = ConfigUtils.loadConfig(options.baseConfig().toString());
		Path context = options.baseConfig().toAbsolutePath().normalize().getParent();
		Map<String, Path> paths = new LinkedHashMap<>();
		paths.put("base_config", options.baseConfig());
		paths.put("original_plans", options.originalPlans());
		paths.put("taxi_plans", options.taxiPlans());
		paths.put("network", options.network());
		paths.put("transit_schedule", options.transitSchedule());
		paths.put("transit_vehicles",
				resolve(context, config.transit().getVehiclesFile()));
		paths.put("facilities",
				resolve(context, config.facilities().getInputFile()));
		paths.put("private_vehicles",
				resolve(context, config.vehicles().getVehiclesFile()));
		paths.put("iteration_0_events", options.events());
		paths.put("failed_run_log", options.runLog());
		paths.put("failed_validation", options.failedValidation());
		paths.put("load_validation", options.loadValidation());
		return Map.copyOf(paths);
	}

	private static Map<String, Object> pathsToMap(
			Map<String, Path> paths,
			Path output) {
		Map<String, Object> result = new LinkedHashMap<>();
		paths.forEach((name, path) ->
				result.put(name, path.toAbsolutePath().normalize().toString()));
		result.put("output_directory", output.toAbsolutePath().normalize().toString());
		return result;
	}

	private static Map<String, Object> snapshotsToMap(
			Map<String, FileSnapshot> snapshots) {
		Map<String, Object> result = new LinkedHashMap<>();
		snapshots.forEach((name, snapshot) -> result.put(name, snapshot.toMap()));
		return result;
	}

	private static Map<String, Object> outputSnapshots(Path output) {
		try {
			Map<String, Object> result = new TreeMap<>();
			try (var stream = Files.list(output)) {
				for (Path path : stream.filter(Files::isRegularFile).toList()) {
					if (path.getFileName().toString()
							.equals("taxi_smoke_dependency_validation.json")) {
						continue;
					}
					result.put(
							path.getFileName().toString(),
							ordered(
									"size_bytes", Files.size(path),
									"sha256", HongKongTaxiSmokeOutputAudit.sha256(path)
							)
					);
				}
			}
			return result;
		} catch (IOException error) {
			throw new IllegalStateException("Cannot snapshot outputs", error);
		}
	}

	private static void validateInputs(Options options) {
		for (Path path : List.of(
				options.baseConfig(),
				options.originalPlans(),
				options.taxiPlans(),
				options.transitSchedule(),
				options.network(),
				options.events(),
				options.runLog(),
				options.failedValidation(),
				options.loadValidation()
		)) {
			if (!Files.isRegularFile(path)) {
				throw new IllegalArgumentException("Required input is not a file: " + path);
			}
		}
		if (!options.auditCheckpoint().matches("[0-9a-f]{40}")) {
			throw new IllegalArgumentException("audit checkpoint must be full lowercase SHA");
		}
	}

	private static void requireSha(
			Map<String, FileSnapshot> snapshots,
			String name,
			String expected) {
		String actual = snapshots.get(name).sha256();
		if (!expected.equals(actual)) {
			throw new IllegalStateException(
					"Input SHA mismatch for " + name + ": " + actual);
		}
	}

	private static Plan requireSelectedPlan(Person person) {
		Plan plan = person.getSelectedPlan();
		if (plan == null) {
			throw new IllegalStateException(
					"Missing selected plan for person " + person.getId());
		}
		return plan;
	}

	private static Activity previousActivity(List<PlanElement> elements, int index) {
		for (int current = index - 1; current >= 0; current--) {
			if (elements.get(current) instanceof Activity activity) {
				return activity;
			}
		}
		return null;
	}

	private static Activity nextActivity(List<PlanElement> elements, int index) {
		for (int current = index + 1; current < elements.size(); current++) {
			if (elements.get(current) instanceof Activity activity) {
				return activity;
			}
		}
		return null;
	}

	private static String activitySignature(Activity activity) {
		if (activity == null) {
			return "<none>";
		}
		return activity.getType()
				+ "|" + nullable(activity.getLinkId())
				+ "|" + nullable(activity.getFacilityId())
				+ "|" + (activity.getCoord() == null ? "<null>"
				: Double.toHexString(activity.getCoord().getX())
				+ ":" + Double.toHexString(activity.getCoord().getY()));
	}

	private static String attributes(Attributes attributes) {
		return attributes.getAsMap().entrySet().stream()
				.sorted(Map.Entry.comparingByKey())
				.map(entry -> entry.getKey()
						+ "="
						+ (entry.getValue() == null ? "<null>"
						: entry.getValue().getClass().getName()
						+ ":" + entry.getValue()))
				.collect(Collectors.joining("|"));
	}

	private static String optional(OptionalTime time) {
		return time.isDefined() ? Double.toHexString(time.seconds()) : "<undefined>";
	}

	private static Double optionalDouble(OptionalTime time) {
		return time.isDefined() ? time.seconds() : null;
	}

	private static long bool(boolean value) {
		return value ? 1L : 0L;
	}

	private static <T> Map<String, Long> countBy(
			Collection<T> values,
			Function<T, String> classifier) {
		Map<String, Long> counts = new TreeMap<>();
		for (T value : values) {
			counts.merge(classifier.apply(value), 1L, Long::sum);
		}
		return Map.copyOf(counts);
	}

	private static void addExample(List<Example> examples, String category, Example example) {
		long count = examples.stream()
				.filter(existing -> existing.category().equals(category))
				.count();
		if (count < 5) {
			examples.add(new Example(
					category,
					example.personId(),
					example.position(),
					example.runtimeClass(),
					example.details()
			));
		}
	}

	private static void requireEquals(Object expected, Object actual, String label) {
		if (!Objects.equals(expected, actual)) {
			throw new IllegalStateException(
					label + " mismatch: expected=" + expected + ", actual=" + actual);
		}
	}

	private static Map<String, Object> errorMap(Throwable error) {
		List<String> chain = new ArrayList<>();
		Throwable current = error;
		while (current != null) {
			chain.add(current.getClass().getName() + ": " + current.getMessage());
			current = current.getCause();
		}
		return ordered(
				"class", error.getClass().getName(),
				"message", String.valueOf(error.getMessage()),
				"cause_chain", chain,
				"stack_trace", List.of(error.getStackTrace()).stream()
						.map(StackTraceElement::toString)
						.limit(80)
						.toList()
		);
	}

	private static Map<String, Object> ordered(Object... entries) {
		Map<String, Object> result = new LinkedHashMap<>();
		for (int index = 0; index < entries.length; index += 2) {
			result.put((String) entries[index], entries[index + 1]);
		}
		return result;
	}

	private static Object nullable(Object value) {
		return value == null ? "" : value;
	}

	record Options(
			Path baseConfig,
			Path originalPlans,
			Path taxiPlans,
			Path transitSchedule,
			Path network,
			Path events,
			Path runLog,
			Path failedValidation,
			Path loadValidation,
			Path outputDirectory,
			String auditCheckpoint) {

		static Options parse(String[] args) {
			if (args.length != 22) {
				throw new IllegalArgumentException(
						"Usage: HongKongTaxiSmokeDependencyAudit "
								+ "--base-config PATH --original-plans PATH "
								+ "--taxi-plans PATH --transit-schedule PATH "
								+ "--network PATH --events PATH --run-log PATH "
								+ "--failed-validation PATH --load-validation PATH "
								+ "--output-dir PATH --audit-checkpoint SHA"
				);
			}
			Map<String, String> values = new LinkedHashMap<>();
			for (int index = 0; index < args.length; index += 2) {
				if (!args[index].startsWith("--")
						|| values.put(args[index], args[index + 1]) != null) {
					throw new IllegalArgumentException(
							"Invalid or duplicate argument " + args[index]);
				}
			}
			return new Options(
					path(values, "--base-config"),
					path(values, "--original-plans"),
					path(values, "--taxi-plans"),
					path(values, "--transit-schedule"),
					path(values, "--network"),
					path(values, "--events"),
					path(values, "--run-log"),
					path(values, "--failed-validation"),
					path(values, "--load-validation"),
					path(values, "--output-dir"),
					required(values, "--audit-checkpoint")
			);
		}

		private static Path path(Map<String, String> values, String name) {
			return Path.of(required(values, name)).toAbsolutePath().normalize();
		}

		private static String required(Map<String, String> values, String name) {
			String value = values.get(name);
			if (value == null || value.isBlank()) {
				throw new IllegalArgumentException("Missing argument " + name);
			}
			return value;
		}
	}

	record SupplyIndex(
			Map<String, String> stopLinks,
			Map<String, Set<String>> lineRoutes,
			Set<String> networkLinkIds) {

		static SupplyIndex from(Scenario scenario) {
			Map<String, String> stops = new HashMap<>();
			scenario.getTransitSchedule().getFacilities().forEach((id, facility) ->
					stops.put(
							id.toString(),
							facility.getLinkId() == null
									? "<null>" : facility.getLinkId().toString()
					));
			Map<String, Set<String>> routes = new HashMap<>();
			scenario.getTransitSchedule().getTransitLines().forEach((id, line) ->
					routes.put(
							id.toString(),
							line.getRoutes().keySet().stream()
									.map(Object::toString)
									.collect(Collectors.toUnmodifiableSet())
					));
			Set<String> links = scenario.getNetwork().getLinks().keySet().stream()
					.map(Object::toString)
					.collect(Collectors.toUnmodifiableSet());
			return new SupplyIndex(Map.copyOf(stops), Map.copyOf(routes), links);
		}
	}

	record RouteAudit(
			boolean routeNull,
			boolean transitPassenger,
			boolean genericRoute,
			boolean defaultTransitRoute,
			boolean otherLegalTransitRoute,
			boolean accessStopMissing,
			boolean egressStopMissing,
			boolean lineIdMissing,
			boolean transitRouteIdMissing,
			boolean accessStopNotInSchedule,
			boolean egressStopNotInSchedule,
			boolean lineNotInSchedule,
			boolean routeNotInSchedule,
			boolean stopLinkIncompatible,
			boolean stopLinkCheckUnavailable,
			List<String> invalidReasons) {

		boolean invalid() {
			return !invalidReasons.isEmpty();
		}
	}

	record PtKey(String personId, int planElementIndex) {
	}

	record PtRecord(
			PtKey key,
			String mode,
			String routingMode,
			String activitySignature,
			String routeClass,
			boolean transitPassenger,
			String routeContent,
			String legAttributes,
			boolean invalid) {

		static PtRecord from(
				PtKey key,
				Leg leg,
				Activity before,
				Activity after,
				RouteAudit audit) {
			Route route = leg.getRoute();
			String access = "";
			String egress = "";
			String line = "";
			String transitRoute = "";
			if (route instanceof TransitPassengerRoute passengerRoute) {
				access = String.valueOf(passengerRoute.getAccessStopId());
				egress = String.valueOf(passengerRoute.getEgressStopId());
				line = String.valueOf(passengerRoute.getLineId());
				transitRoute = String.valueOf(passengerRoute.getRouteId());
			}
			String content = (route == null ? "<null>"
					: nullable(route.getStartLinkId()) + "|"
					+ nullable(route.getEndLinkId()) + "|"
					+ nullable(route.getRouteDescription()) + "|"
					+ Double.toHexString(route.getDistance()) + "|"
					+ optional(route.getTravelTime()))
					+ "|" + access + "|" + egress + "|" + line + "|" + transitRoute;
			return new PtRecord(
					key,
					leg.getMode(),
					String.valueOf(leg.getRoutingMode()),
					HongKongTaxiSmokeDependencyAudit.activitySignature(before)
							+ "->"
							+ HongKongTaxiSmokeDependencyAudit.activitySignature(after),
					route == null ? "<null>" : route.getClass().getName(),
					audit.transitPassenger(),
					content,
					attributes(leg.getAttributes()),
					audit.invalid()
			);
		}

		String personId() {
			return key.personId();
		}

		int planElementIndex() {
			return key.planElementIndex();
		}

		Example toExample() {
			return new Example(
					"",
					personId(),
					planElementIndex(),
					routeClass,
					"activity_signature=" + activitySignature
							+ ";route=" + routeContent
							+ ";invalid=" + invalid
			);
		}
	}

	record TaxiKey(String personId, int ordinal) {
	}

	record TaxiLegRecord(
			TaxiKey key,
			int mainTripIndex,
			int planElementIndex,
			Double departureTimeSeconds,
			String precedingLegModes,
			double fareHkd,
			String taxiType,
			String classificationSource) {

		static TaxiLegRecord from(
				Person person,
				int ordinal,
				int elementIndex,
				Leg leg,
				HongKongTaxiLegAttributes.Metadata metadata,
				List<String> precedingModes) {
			return new TaxiLegRecord(
					new TaxiKey(person.getId().toString(), ordinal),
					metadata.mainTripIndex(),
					elementIndex,
					optionalDouble(leg.getDepartureTime()),
					String.join("|", precedingModes),
					metadata.fareBaselineHkd(),
					metadata.taxiType(),
					metadata.classificationSource()
			);
		}

		String personId() {
			return key.personId();
		}

		int taxiOrdinal() {
			return key.ordinal();
		}
	}

	record PlanAudit(
			String label,
			long persons,
			long ptLegs,
			long routeNull,
			long transitPassengerRoutes,
			long genericRoutes,
			long defaultTransitRoutes,
			long otherLegalTransitRoutes,
			long accessStopMissing,
			long egressStopMissing,
			long lineIdMissing,
			long transitRouteIdMissing,
			long accessStopNotInSchedule,
			long egressStopNotInSchedule,
			long lineNotInSchedule,
			long routeNotInSchedule,
			long stopLinkIncompatible,
			long stopLinkCheckUnavailable,
			Map<String, Long> routeClassCounts,
			Map<String, Long> invalidReasonCounts,
			Map<PtKey, PtRecord> ptRecords,
			Map<String, List<PtRecord>> invalidPtByPerson,
			List<TaxiLegRecord> expectedTaxiLegs,
			Map<String, List<TaxiLegRecord>> expectedTaxiByPerson,
			List<Example> examples) {

		Set<String> expectedTaxiPersons() {
			return expectedTaxiByPerson.keySet();
		}

		Map<String, Object> summaryMap() {
			return ordered(
					"persons", persons,
					"total_pt_legs", ptLegs,
					"route_null", routeNull,
					"implements_transit_passenger_route", transitPassengerRoutes,
					"generic_route_impl", genericRoutes,
					"default_transit_passenger_route", defaultTransitRoutes,
					"other_legal_transit_passenger_route", otherLegalTransitRoutes,
					"access_stop_missing", accessStopMissing,
					"egress_stop_missing", egressStopMissing,
					"line_id_missing", lineIdMissing,
					"transit_route_id_missing", transitRouteIdMissing,
					"access_stop_not_in_schedule", accessStopNotInSchedule,
					"egress_stop_not_in_schedule", egressStopNotInSchedule,
					"line_not_in_schedule", lineNotInSchedule,
					"route_not_in_schedule", routeNotInSchedule,
					"stop_link_execution_position_incompatible", stopLinkIncompatible,
					"stop_link_check_unavailable", stopLinkCheckUnavailable,
					"runtime_class_counts", routeClassCounts,
					"invalid_reason_counts", invalidReasonCounts,
					"expected_taxi_legs", expectedTaxiLegs.size(),
					"expected_taxi_persons", expectedTaxiByPerson.size()
			);
		}
	}

	record PtComparison(
			long originalPtLegs,
			long taxiPtLegs,
			long matched,
			long missing,
			long extra,
			long ambiguous,
			long completelyIdentical,
			long routeTypeChanged,
			long routeContentChanged,
			long legAttributesChanged,
			long modeChanged,
			long routingModeChanged) {

		Map<String, Long> toMap() {
			return orderedLong(
					"original_pt_legs", originalPtLegs,
					"taxi_pt_legs", taxiPtLegs,
					"matched", matched,
					"missing", missing,
					"extra", extra,
					"ambiguous", ambiguous,
					"completely_identical", completelyIdentical,
					"route_type_changed", routeTypeChanged,
					"route_content_changed", routeContentChanged,
					"leg_attributes_changed", legAttributesChanged,
					"mode_changed", modeChanged,
					"routing_mode_changed", routingModeChanged
			);
		}
	}

	private static Map<String, Long> orderedLong(Object... entries) {
		Map<String, Long> result = new LinkedHashMap<>();
		for (int index = 0; index < entries.length; index += 2) {
			result.put((String) entries[index], ((Number) entries[index + 1]).longValue());
		}
		return result;
	}

	static final class RemovalRecord {
		final String personId;
		final String logTimestamp;
		final long logLine;
		String routeClass = "";
		String routeDescription = "";
		PtRecord mappedPt;

		RemovalRecord(String personId, String logTimestamp, long logLine) {
			this.personId = personId;
			this.logTimestamp = logTimestamp;
			this.logLine = logLine;
		}
	}

	record LogAudit(
			long removalLines,
			long uniqueRemovalPersons,
			long uniqueMappedPtLegs,
			long noStopLines,
			long uniqueNoStopPersons,
			boolean personSetsEqual,
			long pendingRouteRows,
			long unavailableMappings,
			long routeClassMismatches,
			long fareScheduleMismatchLines,
			long taxiAttributeErrorLines,
			String firstTimestamp,
			long firstLine,
			String firstPerson,
			Map<String, Long> removalCountsByPerson,
			Map<String, Long> noStopCountsByPerson,
			Map<String, Long> routeClassCounts,
			Map<String, String> routeDescriptionExamples,
			Map<String, List<RemovalRecord>> mappedRemovalsByPerson,
			Set<String> removalPersons) {

		Map<String, Object> toMap() {
			return ordered(
					"pt_no_transit_route_log_lines", removalLines,
					"unique_persons", uniqueRemovalPersons,
					"unique_mapped_pt_legs", uniqueMappedPtLegs,
					"pt_no_stop_log_lines", noStopLines,
					"unique_no_stop_persons", uniqueNoStopPersons,
					"person_sets_equal", personSetsEqual,
					"pending_route_rows", pendingRouteRows,
					"unavailable_plan_leg_mappings", unavailableMappings,
					"route_class_mismatches", routeClassMismatches,
					"fare_schedule_mismatch_log_lines", fareScheduleMismatchLines,
					"taxi_attribute_error_log_lines", taxiAttributeErrorLines,
					"route_runtime_class_counts", routeClassCounts,
					"route_description_examples", routeDescriptionExamples,
					"first_error_timestamp", firstTimestamp,
					"first_error_log_line", firstLine,
					"first_error_person", firstPerson
			);
		}
	}

	record ObservedTaxiEvent(
			String personId,
			int ordinal,
			double time,
			String linkId,
			String eventType) {
	}

	record StuckRecord(
			String personId,
			double time,
			String mode,
			String linkId,
			String reason) {
	}

	record LastEvent(double time, String eventType) {
	}

	record EventAudit(
			long taxiDepartureCount,
			long taxiArrivalCount,
			long duplicateTaxiDepartures,
			Map<String, List<ObservedTaxiEvent>> taxiDeparturesByPerson,
			Map<String, List<ObservedTaxiEvent>> taxiArrivalsByPerson,
			List<StuckRecord> stuckEvents,
			Map<String, List<StuckRecord>> stuckByPerson,
			Map<String, LastEvent> lastTaxiPersonEvent) {
	}

	static final class EventCollector implements BasicEventHandler {
		private final Set<String> taxiPersons;
		private final Map<String, List<ObservedTaxiEvent>> departures = new LinkedHashMap<>();
		private final Map<String, List<ObservedTaxiEvent>> arrivals = new LinkedHashMap<>();
		private final List<StuckRecord> stuck = new ArrayList<>();
		private final Map<String, LastEvent> lastEvents = new HashMap<>();
		private final Map<String, Long> departureFingerprints = new HashMap<>();
		private long duplicateDepartures;

		EventCollector(Set<String> taxiPersons) {
			this.taxiPersons = taxiPersons;
		}

		@Override
		public void handleEvent(Event event) {
			if (event instanceof HasPersonId personEvent) {
				String personId = personEvent.getPersonId().toString();
				if (taxiPersons.contains(personId)) {
					LastEvent current = lastEvents.get(personId);
					if (current == null || event.getTime() >= current.time()) {
						lastEvents.put(
								personId,
								new LastEvent(event.getTime(), event.getEventType())
						);
					}
				}
			}
			if (event instanceof PersonDepartureEvent departure
					&& "taxi".equals(departure.getLegMode())) {
				String personId = departure.getPersonId().toString();
				List<ObservedTaxiEvent> personEvents =
						departures.computeIfAbsent(personId, ignored -> new ArrayList<>());
				String link = String.valueOf(departure.getLinkId());
				String fingerprint = personId + "|" + Double.toHexString(departure.getTime())
						+ "|" + link;
				long count = departureFingerprints.merge(fingerprint, 1L, Long::sum);
				if (count > 1) {
					duplicateDepartures++;
				}
				personEvents.add(new ObservedTaxiEvent(
						personId,
						personEvents.size(),
						departure.getTime(),
						link,
						departure.getEventType()
				));
			} else if (event instanceof PersonArrivalEvent arrival
					&& "taxi".equals(arrival.getLegMode())) {
				String personId = arrival.getPersonId().toString();
				List<ObservedTaxiEvent> personEvents =
						arrivals.computeIfAbsent(personId, ignored -> new ArrayList<>());
				personEvents.add(new ObservedTaxiEvent(
						personId,
						personEvents.size(),
						arrival.getTime(),
						String.valueOf(arrival.getLinkId()),
						arrival.getEventType()
				));
			}
			if (event instanceof PersonStuckEvent personStuck) {
				stuck.add(new StuckRecord(
						personStuck.getPersonId().toString(),
						personStuck.getTime(),
						personStuck.getLegMode() == null
								? "<null>" : personStuck.getLegMode(),
						personStuck.getLinkId() == null
								? "<null>" : personStuck.getLinkId().toString(),
						personStuck.getReason() == null ? "" : personStuck.getReason()
				));
			}
		}

		EventAudit finish() {
			Map<String, List<StuckRecord>> stuckByPerson = stuck.stream()
					.collect(Collectors.groupingBy(
							StuckRecord::personId,
							LinkedHashMap::new,
							Collectors.toList()
					));
			return new EventAudit(
					departures.values().stream().mapToLong(List::size).sum(),
					arrivals.values().stream().mapToLong(List::size).sum(),
					duplicateDepartures,
					immutableLists(departures),
					immutableLists(arrivals),
					List.copyOf(stuck),
					immutableLists(stuckByPerson),
					Map.copyOf(lastEvents)
			);
		}
	}

	private static <T> Map<String, List<T>> immutableLists(Map<String, List<T>> values) {
		Map<String, List<T>> result = new LinkedHashMap<>();
		values.forEach((key, list) -> result.put(key, List.copyOf(list)));
		return Map.copyOf(result);
	}

	record TaxiReconciliation(
			long expected,
			long observedDepartures,
			long observedArrivals,
			long matchedDepartures,
			long missingDepartures,
			long duplicateDepartures,
			long unexpectedDepartures,
			long unmatchedDepartures,
			long unmatchedArrivals,
			List<TaxiLegRecord> missing) {

		Map<String, Object> toMap() {
			return ordered(
					"expected_taxi_legs", expected,
					"observed_departures", observedDepartures,
					"observed_arrivals", observedArrivals,
					"matched_departures", matchedDepartures,
					"missing_departures", missingDepartures,
					"duplicate_departures", duplicateDepartures,
					"unexpected_departures", unexpectedDepartures,
					"unmatched_departures", unmatchedDepartures,
					"unmatched_arrivals", unmatchedArrivals
			);
		}
	}

	record MissingAttribution(
			TaxiLegRecord taxi,
			String category,
			String invalidPtBeforeElementIndexes,
			String removedPtBeforeElementIndexes,
			String stuckBefore,
			String lastEventType,
			Double lastEventTime) {
	}

	record StuckAudit(
			long totalEvents,
			long uniquePersons,
			Map<String, Long> modeCounts,
			Map<String, Long> hourCounts,
			Map<String, Long> linkCounts,
			long taxiPersonEvents,
			long taxiPersons,
			long beforeTaxiEvents,
			long ptRemovalPersonIntersection,
			long missingNetworkLinks,
			double maxTimeSeconds,
			long eventsAtMaxTime,
			List<StuckRecord> examples) {

		Map<String, Object> toMap() {
			List<Map.Entry<String, Long>> topLinks = linkCounts.entrySet().stream()
					.sorted(Map.Entry.<String, Long>comparingByValue().reversed()
							.thenComparing(Map.Entry.comparingByKey()))
					.limit(20)
					.toList();
			return ordered(
					"total_events", totalEvents,
					"unique_persons", uniquePersons,
					"mode_counts", modeCounts,
					"hour_counts", hourCounts,
					"top_links", topLinks.stream()
							.map(entry -> ordered("link_id", entry.getKey(),
									"count", entry.getValue()))
							.toList(),
					"taxi_person_events", taxiPersonEvents,
					"unique_taxi_persons", taxiPersons,
					"events_before_an_expected_taxi", beforeTaxiEvents,
					"unique_person_intersection_with_pt_removal",
							ptRemovalPersonIntersection,
					"stuck_links_missing_from_network", missingNetworkLinks,
					"max_event_time_seconds", maxTimeSeconds,
					"events_at_max_time", eventsAtMaxTime,
					"representative_events", examples
			);
		}
	}

	record FileSnapshot(String path, long sizeBytes, String sha256) {
		Map<String, Object> toMap() {
			return ordered("path", path, "size_bytes", sizeBytes, "sha256", sha256);
		}
	}

	record Example(
			String category,
			String personId,
			int position,
			String runtimeClass,
			String details) {
		List<?> toRow() {
			return List.of(category, personId, position, runtimeClass, details);
		}
	}
}
