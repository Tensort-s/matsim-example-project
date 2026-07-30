package org.matsim.project.hongkong.taxi;

import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.api.core.v01.population.Population;
import org.matsim.api.core.v01.population.Route;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigGroup;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.ScoringConfigGroup;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.core.scoring.ScoringFunction;
import org.matsim.utils.objectattributes.attributable.Attributes;

import java.io.IOException;
import java.io.InputStream;
import java.lang.management.ManagementFactory;
import java.net.InetAddress;
import java.net.URI;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Properties;
import java.util.Set;
import java.util.TreeMap;

/**
 * Loads the complete Hong Kong MATSim scenario with the real taxi plans and
 * performs read-only structural, attribute, route, fare, and scoring-factory
 * audits. It intentionally never creates a Controler or QSim.
 */
public final class HongKongTaxiScenarioLoadAudit {

	private static final String EXPECTED_TAXI_PLANS_SHA256 =
			"9100cb58ce268d9f62771039eaa80d4da11bf200ceb8426130ef272c05de8f1f";
	private static final String EXPECTED_MATSIM_VERSION = "2026.0";
	private static final double TAXI_ASC = -9.0;
	private static final double TAXI_TRAVEL_UTILITY_PER_HOUR = -6.0;
	private static final double NUMERIC_TOLERANCE = 1.0e-9;

	private static final List<String> TAXI_ATTRIBUTE_NAMES = List.of(
			HongKongTaxiLegAttributes.FARE_BASELINE_HKD,
			HongKongTaxiLegAttributes.TAXI_TYPE,
			HongKongTaxiLegAttributes.FARE_SCOPE,
			HongKongTaxiLegAttributes.FARE_MODEL_VERSION,
			HongKongTaxiLegAttributes.CLASSIFICATION_SOURCE,
			HongKongTaxiLegAttributes.MAIN_TRIP_INDEX
	);

	private HongKongTaxiScenarioLoadAudit() {
	}

	public static void main(String[] args) {
		if (args.length != 4) {
			System.err.println(
					"Usage: HongKongTaxiScenarioLoadAudit "
							+ "<base-config> <taxi-plans> <validation-json> <checkpoint-sha>"
			);
			System.exit(64);
		}

		Path validationPath = Path.of(args[2]).toAbsolutePath().normalize();
		Map<String, Object> report;
		int exitCode;
		try {
			report = runAudit(
					Path.of(args[0]).toAbsolutePath().normalize(),
					Path.of(args[1]).toAbsolutePath().normalize(),
					validationPath,
					args[3]
			);
			exitCode = "validated".equals(report.get("status")) ? 0 : 2;
		} catch (Throwable error) {
			report = failureReport(args, error);
			exitCode = 1;
		}

		report.put("load_exit_code", exitCode);
		report.put("process_exit_code", exitCode);
		try {
			writeJsonAtomically(validationPath, report);
		} catch (IOException writeError) {
			writeError.printStackTrace(System.err);
			System.exit(74);
		}
		System.out.println("Validation JSON: " + validationPath);
		System.out.println("Status: " + report.get("status"));
		if (exitCode != 0) {
			System.err.println("Hong Kong taxi scenario load audit failed.");
			System.exit(exitCode);
		}
	}

	static Map<String, Object> runAudit(
			Path baseConfig,
			Path taxiPlans,
			Path validationPath,
			String checkpointSha) throws Exception {
		Instant startedUtc = Instant.now();
		long auditStartedNanos = System.nanoTime();
		Map<String, Object> report = new LinkedHashMap<>();
		report.put("audit", "hong_kong_taxi_scenario_load_audit_v1");
		report.put("status", "running");
		report.put("started_utc", startedUtc.toString());
		report.put("hostname", InetAddress.getLocalHost().getHostName());
		report.put("checkpoint_sha", checkpointSha);
		report.put("java", runtimeJavaDetails());
		report.put("matsim_version", readMatsimVersion());
		report.put("maven_version", System.getProperty("hkTaxiAudit.mavenVersion", "<not-supplied>"));
		report.put("paths", ordered(
				"base_config", baseConfig.toString(),
				"taxi_plans", taxiPlans.toString(),
				"validation_json", validationPath.toString()
		));

		requireRegularFile(baseConfig, "base config");
		requireRegularFile(taxiPlans, "taxi plans");

		Config config = ConfigUtils.loadConfig(baseConfig.toString());
		Map<String, Map<String, Double>> scoringBefore = snapshotScoringModes(config);
		boolean taxiModePresentBefore = scoringBefore.containsKey(HongKongTaxiScoringParameters.TAXI_MODE);

		config.plans().setInputFile(taxiPlans.toString());
		configureTaxiScoring(config);
		Map<String, Map<String, Double>> scoringAfter = snapshotScoringModes(config);
		boolean existingModesUnchanged = existingModesUnchanged(scoringBefore, scoringAfter);

		Map<String, Path> inputPaths = configuredInputPaths(config, baseConfig, taxiPlans);
		Map<String, Object> inputsBefore = snapshotInputFiles(inputPaths);
		report.put("input_files_before_load", inputsBefore);
		report.put("scoring_config", ordered(
				"taxi_mode_present_before", taxiModePresentBefore,
				"existing_modes_before", scoringBefore,
				"modes_after_in_memory_override", scoringAfter,
				"existing_non_taxi_modes_unchanged", existingModesUnchanged,
				"taxi_mode_expected", expectedTaxiModeSnapshot()
		));

		long loadStartedNanos = System.nanoTime();
		Scenario scenario = ScenarioUtils.loadScenario(config);
		double scenarioLoadSeconds = elapsedSeconds(loadStartedNanos);
		report.put("scenario_load_completed", true);
		report.put("scenario_load_duration_seconds", scenarioLoadSeconds);
		report.put("scenario_supply_counts", scenarioSupplyCounts(scenario));

		HongKongTaxiScoringParameters parameters = HongKongTaxiScoringParameters.centralV1();
		PopulationAudit populationAudit = auditPopulation(scenario.getPopulation(), parameters);
		report.put("population_audit", populationAudit.toMap());

		Map<String, Object> factoryAudit = auditScoringFactory(scenario, populationAudit, parameters);
		report.put("scoring_factory_audit", factoryAudit);

		Map<String, Object> inputsAfter = snapshotInputFiles(inputPaths);
		report.put("input_files_after_audit", inputsAfter);
		boolean inputHashesStable = inputSnapshotsEqual(inputsBefore, inputsAfter);

		List<String> forbiddenOutputs = findForbiddenSimulationOutputs(validationPath.getParent());
		report.put("forbidden_simulation_outputs", forbiddenOutputs);
		report.put("run_flags", ordered(
				"matsim_run", false,
				"controler_run", false,
				"qsim_run", false,
				"routing_run", false,
				"asc_experiment", false,
				"fleet_simulation", false,
				"controler_created", false,
				"qsim_started", false,
				"iterations_run", false,
				"asc_calibration_run", false,
				"fleet_model_run", false
		));

		Map<String, Boolean> requiredChecks = requiredChecks(
				report,
				checkpointSha,
				taxiModePresentBefore,
				existingModesUnchanged,
				scoringAfter,
				populationAudit,
				factoryAudit,
				inputsBefore,
				inputHashesStable,
				forbiddenOutputs
		);
		List<String> failedChecks = requiredChecks.entrySet().stream()
				.filter(entry -> !entry.getValue())
				.map(Map.Entry::getKey)
				.toList();
		report.put("required_checks", requiredChecks);
		report.put("failed_checks", failedChecks);
		report.put("all_checks_passed", failedChecks.isEmpty());
		report.put("finished_utc", Instant.now().toString());
		report.put("total_audit_duration_seconds", elapsedSeconds(auditStartedNanos));
		report.put("status", failedChecks.isEmpty() ? "validated" : "failed");
		return report;
	}

	static void configureTaxiScoring(Config config) {
		ScoringConfigGroup.ModeParams taxi =
				config.scoring().getOrCreateModeParams(HongKongTaxiScoringParameters.TAXI_MODE);
		taxi.setConstant(TAXI_ASC);
		taxi.setMarginalUtilityOfTraveling(TAXI_TRAVEL_UTILITY_PER_HOUR);
		taxi.setMarginalUtilityOfDistance(0.0);
		taxi.setMonetaryDistanceRate(0.0);
		taxi.setDailyMonetaryConstant(0.0);
		taxi.setDailyUtilityConstant(0.0);
	}

	static PopulationAudit auditPopulation(
			Population population,
			HongKongTaxiScoringParameters parameters) {
		PopulationAudit audit = new PopulationAudit();
		audit.persons = population.getPersons().size();
		Set<String> taxiPersonIds = new LinkedHashSet<>();
		Set<String> personsWithTaxi = new LinkedHashSet<>();

		for (Person person : population.getPersons().values()) {
			boolean personHasTaxi = false;
			for (Plan plan : person.getPlans()) {
				audit.plans++;
				for (PlanElement element : plan.getPlanElements()) {
					if (element instanceof Activity) {
						audit.activities++;
					} else if (element instanceof Leg leg) {
						audit.legs++;
						audit.modeCounts.merge(leg.getMode(), 1L, Long::sum);
						if (leg.getRoute() != null) {
							audit.routes++;
						}
						if (HongKongTaxiScoringParameters.TAXI_MODE.equals(leg.getMode())) {
							personHasTaxi = true;
							auditTaxiLeg(audit, leg, person, parameters);
						} else {
							auditNonTaxiLeg(audit, leg);
						}
					}
				}
			}
			if (personHasTaxi) {
				personsWithTaxi.add(person.getId().toString());
				if (audit.representativeTaxiPersonId == null) {
					audit.representativeTaxiPersonId = person.getId().toString();
				}
			} else if (audit.representativeNonTaxiPersonId == null) {
				audit.representativeNonTaxiPersonId = person.getId().toString();
			}
		}

		taxiPersonIds.addAll(personsWithTaxi);
		audit.taxiPersons = taxiPersonIds.size();
		audit.fareStatistics = summarize(audit.fares);
		return audit;
	}

	private static void auditTaxiLeg(
			PopulationAudit audit,
			Leg leg,
			Person person,
			HongKongTaxiScoringParameters parameters) {
		audit.taxiLegs++;
		Attributes attributes = leg.getAttributes();
		for (String name : TAXI_ATTRIBUTE_NAMES) {
			if (!attributes.getAsMap().containsKey(name) || attributes.getAttribute(name) == null) {
				audit.missingTaxiAttributeValues++;
				continue;
			}
			Object value = attributes.getAttribute(name);
			audit.attributeRuntimeTypes
					.computeIfAbsent(name, ignored -> new TreeMap<>())
					.merge(value.getClass().getName(), 1L, Long::sum);
			if (!hasExpectedRuntimeType(name, value)) {
				audit.invalidTaxiAttributeRuntimeTypes++;
			} else if (!hasValidValue(name, value, parameters)) {
				audit.invalidTaxiAttributeValues++;
				recordInvalidTypedValue(audit, name, value, parameters);
			}
		}

		HongKongTaxiLegAttributes.Metadata metadata;
		try {
			metadata = HongKongTaxiLegAttributes.readAndValidate(leg, person.getId(), parameters);
		} catch (IllegalArgumentException error) {
			audit.attributeValidationFailures++;
			if (audit.attributeValidationFailureExamples.size() < 10) {
				audit.attributeValidationFailureExamples.add(error.getMessage());
			}
			return;
		}

		audit.fares.add(metadata.fareBaselineHkd());
		audit.fareSumHkd += metadata.fareBaselineHkd();
		audit.taxiTypeCounts.merge(metadata.taxiType(), 1L, Long::sum);
		audit.classificationSourceCounts.merge(metadata.classificationSource(), 1L, Long::sum);

		HongKongTaxiFareScoring fareScoring =
				new HongKongTaxiFareScoring(person.getId(), parameters);
		fareScoring.handleLeg(leg);
		audit.fareOnlyScorerTaxiLegs++;
		audit.fareOnlyScoreSum += fareScoring.getScore();

		Route route = leg.getRoute();
		if (route == null) {
			audit.taxiLegsMissingRoute++;
		} else {
			double distance = route.getDistance();
			if (!Double.isFinite(distance) || distance < 0.0) {
				audit.taxiRouteInvalidDistance++;
			}
			if (route.getTravelTime().isUndefined()) {
				audit.taxiRouteUndefinedTravelTime++;
			} else {
				double travelTime = route.getTravelTime().seconds();
				if (!Double.isFinite(travelTime) || travelTime < 0.0) {
					audit.taxiRouteInvalidTravelTime++;
				}
			}
		}
		audit.taxiRoutingModeCounts.merge(String.valueOf(leg.getRoutingMode()), 1L, Long::sum);
	}

	private static void auditNonTaxiLeg(PopulationAudit audit, Leg leg) {
		for (String attributeName : TAXI_ATTRIBUTE_NAMES) {
			if (leg.getAttributes().getAsMap().containsKey(attributeName)) {
				audit.nonTaxiLegsWithTaxiAttributes++;
				return;
			}
		}
	}

	private static boolean hasExpectedRuntimeType(String name, Object value) {
		if (HongKongTaxiLegAttributes.FARE_BASELINE_HKD.equals(name)) {
			return value instanceof Double;
		}
		if (HongKongTaxiLegAttributes.MAIN_TRIP_INDEX.equals(name)) {
			return value instanceof Integer;
		}
		return value instanceof String;
	}

	private static boolean hasValidValue(
			String name,
			Object value,
			HongKongTaxiScoringParameters parameters) {
		if (value instanceof Double number) {
			return Double.isFinite(number) && number >= 0.0;
		}
		if (value instanceof Integer number) {
			return number >= 0;
		}
		if (!(value instanceof String text) || text.isBlank()) {
			return false;
		}
		if (HongKongTaxiLegAttributes.FARE_SCOPE.equals(name)) {
			return parameters.fareScope().equals(text);
		}
		if (HongKongTaxiLegAttributes.FARE_MODEL_VERSION.equals(name)) {
			return parameters.fareModelVersion().equals(text);
		}
		return true;
	}

	private static void recordInvalidTypedValue(
			PopulationAudit audit,
			String name,
			Object value,
			HongKongTaxiScoringParameters parameters) {
		if (HongKongTaxiLegAttributes.FARE_BASELINE_HKD.equals(name)) {
			double fare = (Double) value;
			if (!Double.isFinite(fare) || fare < 0.0) {
				audit.negativeOrNonfiniteFare++;
			}
		} else if (HongKongTaxiLegAttributes.MAIN_TRIP_INDEX.equals(name)) {
			if ((Integer) value < 0) {
				audit.invalidMainTripIndex++;
			}
		} else if (HongKongTaxiLegAttributes.FARE_SCOPE.equals(name)) {
			if (!parameters.fareScope().equals(value)) {
				audit.invalidFareScope++;
			}
		} else if (HongKongTaxiLegAttributes.FARE_MODEL_VERSION.equals(name)) {
			if (!parameters.fareModelVersion().equals(value)) {
				audit.invalidFareModelVersion++;
			}
		} else if (HongKongTaxiLegAttributes.CLASSIFICATION_SOURCE.equals(name)
				&& ((String) value).isBlank()) {
			audit.blankClassificationSource++;
		}
	}

	private static Map<String, Object> auditScoringFactory(
			Scenario scenario,
			PopulationAudit populationAudit,
			HongKongTaxiScoringParameters parameters) {
		Map<String, Object> result = new LinkedHashMap<>();
		try {
			Person taxiPerson = scenario.getPopulation().getPersons().values().stream()
					.filter(person -> person.getId().toString()
							.equals(populationAudit.representativeTaxiPersonId))
					.findFirst()
					.orElseThrow();
			Person nonTaxiPerson = scenario.getPopulation().getPersons().values().stream()
					.filter(person -> person.getId().toString()
							.equals(populationAudit.representativeNonTaxiPersonId))
					.findFirst()
					.orElseThrow();
			HongKongTaxiScoringFunctionFactory factory =
					new HongKongTaxiScoringFunctionFactory(scenario, parameters);
			ScoringFunction taxiFunction = factory.createNewScoringFunction(taxiPerson);
			ScoringFunction nonTaxiFunction = factory.createNewScoringFunction(nonTaxiPerson);
			result.put("passed", true);
			result.put("factory_class", factory.getClass().getName());
			result.put("taxi_person_id", taxiPerson.getId().toString());
			result.put("taxi_scoring_function_class", taxiFunction.getClass().getName());
			result.put("non_taxi_person_id", nonTaxiPerson.getId().toString());
			result.put("non_taxi_scoring_function_class", nonTaxiFunction.getClass().getName());
			result.put("scoring_lifecycle_run", false);
		} catch (RuntimeException error) {
			result.put("passed", false);
			result.put("error", error.toString());
		}
		return result;
	}

	private static Map<String, Boolean> requiredChecks(
			Map<String, Object> report,
			String checkpointSha,
			boolean taxiModePresentBefore,
			boolean existingModesUnchanged,
			Map<String, Map<String, Double>> scoringAfter,
			PopulationAudit audit,
			Map<String, Object> factoryAudit,
			Map<String, Object> inputsBefore,
			boolean inputHashesStable,
			List<String> forbiddenOutputs) {
		Map<String, Boolean> checks = new LinkedHashMap<>();
		checks.put("checkpoint_sha_is_full_hex", checkpointSha.matches("[0-9a-f]{40}"));
		checks.put("matsim_version_is_2026_0", EXPECTED_MATSIM_VERSION.equals(report.get("matsim_version")));
		checks.put("java_major_version_is_25",
				String.valueOf(System.getProperty("java.version")).matches("^25(?:\\..*)?$"));
		checks.put("maven_version_recorded", !"<not-supplied>".equals(report.get("maven_version")));
		checks.put("taxi_mode_absent_in_base_config", !taxiModePresentBefore);
		checks.put("existing_non_taxi_scoring_modes_unchanged", existingModesUnchanged);
		checks.put("taxi_scoring_mode_exact", expectedTaxiModeSnapshot()
				.equals(scoringAfter.get(HongKongTaxiScoringParameters.TAXI_MODE)));
		checks.put("input_hashes_stable", inputHashesStable);
		checks.put("taxi_plans_sha256_exact", EXPECTED_TAXI_PLANS_SHA256.equals(
				inputSha(inputsBefore, "taxi_plans")
		));
		checks.put("scenario_structure_exact",
				audit.persons == 385_820
						&& audit.plans == 385_820
						&& audit.activities == 1_264_870
						&& audit.legs == 879_050
						&& audit.routes == 879_050);
		checks.put("leg_modes_exact", expectedModeCounts().equals(audit.modeCounts));
		checks.put("taxi_leg_and_person_counts_exact",
				audit.taxiLegs == 37_286 && audit.taxiPersons == 15_439);
		checks.put("taxi_types_exact", expectedTaxiTypeCounts().equals(audit.taxiTypeCounts));
		checks.put("classification_sources_exact",
				expectedClassificationCounts().equals(audit.classificationSourceCounts));
		checks.put("taxi_attribute_runtime_types_exact",
				expectedAttributeRuntimeTypes().equals(audit.attributeRuntimeTypes));
		checks.put("taxi_attributes_complete_and_valid",
				audit.missingTaxiAttributeValues == 0
						&& audit.invalidTaxiAttributeRuntimeTypes == 0
						&& audit.invalidTaxiAttributeValues == 0
						&& audit.invalidFareScope == 0
						&& audit.invalidFareModelVersion == 0
						&& audit.negativeOrNonfiniteFare == 0
						&& audit.invalidMainTripIndex == 0
						&& audit.blankClassificationSource == 0
						&& audit.attributeValidationFailures == 0);
		checks.put("non_taxi_legs_have_no_taxi_attributes",
				audit.nonTaxiLegsWithTaxiAttributes == 0);
		checks.put("all_taxi_routes_complete",
				audit.taxiLegsMissingRoute == 0
						&& audit.taxiRouteInvalidDistance == 0
						&& audit.taxiRouteUndefinedTravelTime == 0
						&& audit.taxiRouteInvalidTravelTime == 0);
		checks.put("taxi_routing_mode_is_taxi_only",
				Map.of("taxi", 37_286L).equals(audit.taxiRoutingModeCounts));
		checks.put("fare_statistics_exact", fareStatisticsExact(audit.fareStatistics));
		checks.put("fare_only_scorer_visited_every_taxi_leg",
				audit.fareOnlyScorerTaxiLegs == audit.taxiLegs);
		checks.put("fare_score_sum_matches_formula",
				close(audit.fareOnlyScoreSum, -0.05 * audit.fareSumHkd));
		checks.put("scoring_factory_created_for_taxi_and_non_taxi",
				Boolean.TRUE.equals(factoryAudit.get("passed")));
		checks.put("complete_scenario_supply_loaded", completeSupplyLoaded(report));
		checks.put("no_forbidden_simulation_outputs", forbiddenOutputs.isEmpty());
		checks.put("no_controler_qsim_routing_iterations_or_fleet_run", true);
		return checks;
	}

	private static boolean completeSupplyLoaded(Map<String, Object> report) {
		@SuppressWarnings("unchecked")
		Map<String, Object> counts = (Map<String, Object>) report.get("scenario_supply_counts");
		return positive(counts, "network_nodes")
				&& positive(counts, "network_links")
				&& positive(counts, "transit_stop_facilities")
				&& positive(counts, "transit_lines")
				&& positive(counts, "transit_vehicles")
				&& positive(counts, "activity_facilities")
				&& positive(counts, "private_vehicles");
	}

	private static boolean positive(Map<String, Object> values, String key) {
		return values.get(key) instanceof Number number && number.longValue() > 0;
	}

	private static boolean fareStatisticsExact(Map<String, Double> statistics) {
		Map<String, Double> expected = new LinkedHashMap<>();
		expected.put("mean", 109.86560907579253);
		expected.put("median", 98.3);
		expected.put("p10", 29.0);
		expected.put("p90", 222.5);
		expected.put("min", 24.0);
		expected.put("max", 491.7);
		for (Map.Entry<String, Double> entry : expected.entrySet()) {
			if (!close(entry.getValue(), statistics.getOrDefault(entry.getKey(), Double.NaN))) {
				return false;
			}
		}
		return true;
	}

	private static Map<String, Object> scenarioSupplyCounts(Scenario scenario) {
		return ordered(
				"network_nodes", scenario.getNetwork().getNodes().size(),
				"network_links", scenario.getNetwork().getLinks().size(),
				"transit_stop_facilities", scenario.getTransitSchedule().getFacilities().size(),
				"transit_lines", scenario.getTransitSchedule().getTransitLines().size(),
				"transit_vehicle_types", scenario.getTransitVehicles().getVehicleTypes().size(),
				"transit_vehicles", scenario.getTransitVehicles().getVehicles().size(),
				"activity_facilities", scenario.getActivityFacilities().getFacilities().size(),
				"private_vehicle_types", scenario.getVehicles().getVehicleTypes().size(),
				"private_vehicles", scenario.getVehicles().getVehicles().size()
		);
	}

	private static Map<String, Path> configuredInputPaths(
			Config config,
			Path baseConfig,
			Path taxiPlans) throws Exception {
		Map<String, Path> paths = new LinkedHashMap<>();
		paths.put("base_config", baseConfig);
		paths.put("taxi_plans", taxiPlans);
		paths.put("network", resolveConfiguredPath(config, config.network().getInputFile()));
		paths.put("transit_schedule",
				resolveConfiguredPath(config, config.transit().getTransitScheduleFile()));
		paths.put("transit_vehicles",
				resolveConfiguredPath(config, config.transit().getVehiclesFile()));
		paths.put("facilities", resolveConfiguredPath(config, config.facilities().getInputFile()));
		paths.put("private_vehicles",
				resolveConfiguredPath(config, config.vehicles().getVehiclesFile()));
		for (Map.Entry<String, Path> entry : paths.entrySet()) {
			requireRegularFile(entry.getValue(), entry.getKey());
		}
		return paths;
	}

	private static Path resolveConfiguredPath(Config config, String configured) throws Exception {
		if (configured == null || configured.isBlank()) {
			throw new IllegalArgumentException("Required configured input path is missing.");
		}
		URL url = ConfigGroup.getInputFileURL(config.getContext(), configured);
		URI uri = url.toURI();
		if (!"file".equalsIgnoreCase(uri.getScheme())) {
			throw new IllegalArgumentException("Only local file inputs are allowed: " + url);
		}
		return Path.of(uri).toAbsolutePath().normalize();
	}

	private static Map<String, Object> snapshotInputFiles(Map<String, Path> paths)
			throws IOException, NoSuchAlgorithmException {
		Map<String, Object> snapshots = new LinkedHashMap<>();
		for (Map.Entry<String, Path> entry : paths.entrySet()) {
			Path path = entry.getValue();
			snapshots.put(entry.getKey(), ordered(
					"path", path.toString(),
					"size_bytes", Files.size(path),
					"sha256", sha256(path)
			));
		}
		return snapshots;
	}

	private static boolean inputSnapshotsEqual(
			Map<String, Object> before,
			Map<String, Object> after) {
		return before.equals(after);
	}

	private static String inputSha(Map<String, Object> inputs, String name) {
		@SuppressWarnings("unchecked")
		Map<String, Object> snapshot = (Map<String, Object>) inputs.get(name);
		return String.valueOf(snapshot.get("sha256"));
	}

	private static Map<String, Map<String, Double>> snapshotScoringModes(Config config) {
		Map<String, Map<String, Double>> result = new TreeMap<>();
		for (Map.Entry<String, ScoringConfigGroup.ModeParams> entry
				: config.scoring().getModes().entrySet()) {
			result.put(entry.getKey(), snapshotMode(entry.getValue()));
		}
		return result;
	}

	private static Map<String, Double> snapshotMode(ScoringConfigGroup.ModeParams mode) {
		Map<String, Double> result = new LinkedHashMap<>();
		result.put("constant", mode.getConstant());
		result.put("marginalUtilityOfTraveling", mode.getMarginalUtilityOfTraveling());
		result.put("marginalUtilityOfDistance", mode.getMarginalUtilityOfDistance());
		result.put("monetaryDistanceRate", mode.getMonetaryDistanceRate());
		result.put("dailyMonetaryConstant", mode.getDailyMonetaryConstant());
		result.put("dailyUtilityConstant", mode.getDailyUtilityConstant());
		return result;
	}

	private static boolean existingModesUnchanged(
			Map<String, Map<String, Double>> before,
			Map<String, Map<String, Double>> after) {
		for (Map.Entry<String, Map<String, Double>> entry : before.entrySet()) {
			if (HongKongTaxiScoringParameters.TAXI_MODE.equals(entry.getKey())) {
				continue;
			}
			if (!entry.getValue().equals(after.get(entry.getKey()))) {
				return false;
			}
		}
		return true;
	}

	private static Map<String, Double> expectedTaxiModeSnapshot() {
		Map<String, Double> expected = new LinkedHashMap<>();
		expected.put("constant", TAXI_ASC);
		expected.put("marginalUtilityOfTraveling", TAXI_TRAVEL_UTILITY_PER_HOUR);
		expected.put("marginalUtilityOfDistance", 0.0);
		expected.put("monetaryDistanceRate", 0.0);
		expected.put("dailyMonetaryConstant", 0.0);
		expected.put("dailyUtilityConstant", 0.0);
		return expected;
	}

	static Map<String, Double> summarize(List<Double> values) {
		if (values.isEmpty()) {
			return Map.of();
		}
		List<Double> sorted = values.stream().sorted().toList();
		double sum = 0.0;
		for (double value : sorted) {
			sum += value;
		}
		Map<String, Double> result = new LinkedHashMap<>();
		result.put("mean", sum / sorted.size());
		result.put("median", quantile(sorted, 0.50));
		result.put("p10", quantile(sorted, 0.10));
		result.put("p25", quantile(sorted, 0.25));
		result.put("p75", quantile(sorted, 0.75));
		result.put("p90", quantile(sorted, 0.90));
		result.put("p95", quantile(sorted, 0.95));
		result.put("min", sorted.getFirst());
		result.put("max", sorted.getLast());
		return result;
	}

	static double quantile(List<Double> sorted, double probability) {
		if (sorted.isEmpty() || probability < 0.0 || probability > 1.0) {
			throw new IllegalArgumentException("Invalid quantile input.");
		}
		double position = (sorted.size() - 1) * probability;
		int lower = (int) Math.floor(position);
		int upper = (int) Math.ceil(position);
		if (lower == upper) {
			return sorted.get(lower);
		}
		double fraction = position - lower;
		return sorted.get(lower) + fraction * (sorted.get(upper) - sorted.get(lower));
	}

	private static Map<String, Long> expectedModeCounts() {
		Map<String, Long> expected = new TreeMap<>();
		expected.put("car", 67_718L);
		expected.put("pt", 557_104L);
		expected.put("ride", 19_074L);
		expected.put("taxi", 37_286L);
		expected.put("walk", 197_868L);
		return expected;
	}

	private static Map<String, Long> expectedTaxiTypeCounts() {
		Map<String, Long> expected = new TreeMap<>();
		expected.put("lantau_taxi", 62L);
		expected.put("new_territories_taxi", 3_654L);
		expected.put("unresolved", 2_533L);
		expected.put("urban_taxi", 31_037L);
		return expected;
	}

	private static Map<String, Long> expectedClassificationCounts() {
		Map<String, Long> expected = new TreeMap<>();
		expected.put("resident_discretionary_ride_assignment", 23_100L);
		expected.put("v1_mode_detail_explicit_taxi", 4_614L);
		expected.put("visitor_tcs_proxy_unspecified_ride", 9_572L);
		return expected;
	}

	private static Map<String, Map<String, Long>> expectedAttributeRuntimeTypes() {
		Map<String, Map<String, Long>> expected = new TreeMap<>();
		expected.put(HongKongTaxiLegAttributes.FARE_BASELINE_HKD,
				Map.of("java.lang.Double", 37_286L));
		expected.put(HongKongTaxiLegAttributes.TAXI_TYPE,
				Map.of("java.lang.String", 37_286L));
		expected.put(HongKongTaxiLegAttributes.FARE_SCOPE,
				Map.of("java.lang.String", 37_286L));
		expected.put(HongKongTaxiLegAttributes.FARE_MODEL_VERSION,
				Map.of("java.lang.String", 37_286L));
		expected.put(HongKongTaxiLegAttributes.CLASSIFICATION_SOURCE,
				Map.of("java.lang.String", 37_286L));
		expected.put(HongKongTaxiLegAttributes.MAIN_TRIP_INDEX,
				Map.of("java.lang.Integer", 37_286L));
		return expected;
	}

	private static List<String> findForbiddenSimulationOutputs(Path root) throws IOException {
		if (root == null || !Files.exists(root)) {
			return List.of();
		}
		List<String> forbidden = new ArrayList<>();
		try (var stream = Files.walk(root)) {
			stream.filter(path -> !path.equals(root))
					.filter(HongKongTaxiScenarioLoadAudit::isForbiddenSimulationOutput)
					.map(Path::toString)
					.sorted()
					.forEach(forbidden::add);
		}
		return forbidden;
	}

	private static boolean isForbiddenSimulationOutput(Path path) {
		String name = path.getFileName().toString().toLowerCase(Locale.ROOT);
		return name.contains("output_events")
				|| name.contains("output_plans")
				|| name.contains("output_config")
				|| name.equals("iters")
				|| name.startsWith("it.")
				|| name.contains("qsim")
				|| name.contains("simulation_output");
	}

	private static Map<String, Object> runtimeJavaDetails() {
		return ordered(
				"version", System.getProperty("java.version"),
				"vendor", System.getProperty("java.vendor"),
				"vm_name", System.getProperty("java.vm.name"),
				"max_heap_bytes", Runtime.getRuntime().maxMemory(),
				"input_arguments", ManagementFactory.getRuntimeMXBean().getInputArguments()
		);
	}

	private static String readMatsimVersion() {
		Properties properties = new Properties();
		try (InputStream input = HongKongTaxiScenarioLoadAudit.class.getClassLoader()
				.getResourceAsStream("META-INF/maven/org.matsim/matsim/pom.properties")) {
			if (input == null) {
				return "<unknown>";
			}
			properties.load(input);
			return properties.getProperty("version", "<unknown>");
		} catch (IOException error) {
			return "<unreadable:" + error.getClass().getSimpleName() + ">";
		}
	}

	private static Map<String, Object> failureReport(String[] args, Throwable error) {
		Map<String, Object> report = new LinkedHashMap<>();
		report.put("audit", "hong_kong_taxi_scenario_load_audit_v1");
		report.put("status", "failed");
		report.put("finished_utc", Instant.now().toString());
		report.put("hostname", safeHostname());
		report.put("checkpoint_sha", args.length > 3 ? args[3] : "<missing>");
		report.put("java", runtimeJavaDetails());
		report.put("matsim_version", readMatsimVersion());
		report.put("maven_version", System.getProperty("hkTaxiAudit.mavenVersion", "<not-supplied>"));
		report.put("error", ordered(
				"class", error.getClass().getName(),
				"message", String.valueOf(error.getMessage()),
				"stack_trace", List.of(error.getStackTrace()).stream()
						.map(StackTraceElement::toString)
						.limit(50)
						.toList()
		));
		report.put("required_checks", Map.of("audit_completed", false));
		report.put("failed_checks", List.of("audit_completed"));
		report.put("all_checks_passed", false);
		report.put("run_flags", ordered(
				"matsim_run", false,
				"controler_run", false,
				"qsim_run", false,
				"routing_run", false,
				"asc_experiment", false,
				"fleet_simulation", false,
				"controler_created", false,
				"qsim_started", false,
				"iterations_run", false,
				"asc_calibration_run", false,
				"fleet_model_run", false
		));
		return report;
	}

	private static String safeHostname() {
		try {
			return InetAddress.getLocalHost().getHostName();
		} catch (Exception error) {
			return "<unknown>";
		}
	}

	private static void requireRegularFile(Path path, String label) {
		if (!Files.isRegularFile(path)) {
			throw new IllegalArgumentException(label + " is not a regular file: " + path);
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

	private static boolean close(double left, double right) {
		double scale = Math.max(1.0, Math.max(Math.abs(left), Math.abs(right)));
		return Math.abs(left - right) <= NUMERIC_TOLERANCE * scale;
	}

	private static double elapsedSeconds(long startedNanos) {
		return (System.nanoTime() - startedNanos) / 1_000_000_000.0;
	}

	private static Map<String, Object> ordered(Object... keyValues) {
		if (keyValues.length % 2 != 0) {
			throw new IllegalArgumentException("keyValues must have even length.");
		}
		Map<String, Object> result = new LinkedHashMap<>();
		for (int index = 0; index < keyValues.length; index += 2) {
			result.put(String.valueOf(keyValues[index]), keyValues[index + 1]);
		}
		return result;
	}

	private static void writeJsonAtomically(Path output, Map<String, Object> report)
			throws IOException {
		Path parent = output.getParent();
		if (parent != null) {
			Files.createDirectories(parent);
		}
		Path temporary = output.resolveSibling(output.getFileName() + ".tmp");
		Files.writeString(temporary, toJson(report, 0) + System.lineSeparator(),
				StandardCharsets.UTF_8);
		try {
			Files.move(temporary, output, StandardCopyOption.REPLACE_EXISTING,
					StandardCopyOption.ATOMIC_MOVE);
		} catch (AtomicMoveNotSupportedException ignored) {
			Files.move(temporary, output, StandardCopyOption.REPLACE_EXISTING);
		}
	}

	static String toJson(Object value, int indent) {
		if (value == null) {
			return "null";
		}
		if (value instanceof String text) {
			return '"' + escapeJson(text) + '"';
		}
		if (value instanceof Boolean || value instanceof Byte || value instanceof Short
				|| value instanceof Integer || value instanceof Long) {
			return value.toString();
		}
		if (value instanceof Number number) {
			double numeric = number.doubleValue();
			if (!Double.isFinite(numeric)) {
				throw new IllegalArgumentException("JSON number must be finite: " + number);
			}
			return number.toString();
		}
		if (value instanceof Map<?, ?> map) {
			if (map.isEmpty()) {
				return "{}";
			}
			List<String> entries = new ArrayList<>();
			for (Map.Entry<?, ?> entry : map.entrySet()) {
				entries.add(" ".repeat(indent + 2)
						+ toJson(String.valueOf(entry.getKey()), indent + 2)
						+ ": "
						+ toJson(entry.getValue(), indent + 2));
			}
			return "{\n" + String.join(",\n", entries) + "\n" + " ".repeat(indent) + "}";
		}
		if (value instanceof Collection<?> collection) {
			if (collection.isEmpty()) {
				return "[]";
			}
			List<String> entries = collection.stream()
					.map(item -> " ".repeat(indent + 2) + toJson(item, indent + 2))
					.toList();
			return "[\n" + String.join(",\n", entries) + "\n" + " ".repeat(indent) + "]";
		}
		throw new IllegalArgumentException("Unsupported JSON type: " + value.getClass().getName());
	}

	private static String escapeJson(String value) {
		StringBuilder escaped = new StringBuilder(value.length() + 16);
		for (int index = 0; index < value.length(); index++) {
			char character = value.charAt(index);
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
						escaped.append(String.format("\\u%04x", (int) character));
					} else {
						escaped.append(character);
					}
				}
			}
		}
		return escaped.toString();
	}

	static final class PopulationAudit {
		long persons;
		long plans;
		long activities;
		long legs;
		long routes;
		long taxiLegs;
		long taxiPersons;
		long missingTaxiAttributeValues;
		long invalidTaxiAttributeRuntimeTypes;
		long invalidTaxiAttributeValues;
		long invalidFareScope;
		long invalidFareModelVersion;
		long negativeOrNonfiniteFare;
		long invalidMainTripIndex;
		long blankClassificationSource;
		long attributeValidationFailures;
		long nonTaxiLegsWithTaxiAttributes;
		long taxiLegsMissingRoute;
		long taxiRouteInvalidDistance;
		long taxiRouteUndefinedTravelTime;
		long taxiRouteInvalidTravelTime;
		long fareOnlyScorerTaxiLegs;
		double fareSumHkd;
		double fareOnlyScoreSum;
		String representativeTaxiPersonId;
		String representativeNonTaxiPersonId;
		final Map<String, Long> modeCounts = new TreeMap<>();
		final Map<String, Long> taxiTypeCounts = new TreeMap<>();
		final Map<String, Long> classificationSourceCounts = new TreeMap<>();
		final Map<String, Map<String, Long>> attributeRuntimeTypes = new TreeMap<>();
		final Map<String, Long> taxiRoutingModeCounts = new TreeMap<>();
		final List<String> attributeValidationFailureExamples = new ArrayList<>();
		final List<Double> fares = new ArrayList<>();
		Map<String, Double> fareStatistics = Map.of();

		Map<String, Object> toMap() {
			return ordered(
					"persons", persons,
					"plans", plans,
					"activities", activities,
					"legs", legs,
					"routes", routes,
					"mode_counts", modeCounts,
					"taxi_legs", taxiLegs,
					"taxi_persons", taxiPersons,
					"taxi_actual_mode_counts", Map.of("taxi", taxiLegs),
					"taxi_type_counts", taxiTypeCounts,
					"classification_source_counts", classificationSourceCounts,
					"attribute_runtime_types", attributeRuntimeTypes,
					"duplicate_taxi_attribute_names", 0,
					"missing_taxi_attribute_values", missingTaxiAttributeValues,
					"invalid_taxi_attribute_runtime_types", invalidTaxiAttributeRuntimeTypes,
					"invalid_taxi_attribute_values", invalidTaxiAttributeValues,
					"invalid_scope", invalidFareScope,
					"invalid_model_version", invalidFareModelVersion,
					"negative_or_non_finite_fare", negativeOrNonfiniteFare,
					"invalid_main_trip_index", invalidMainTripIndex,
					"blank_classification_source", blankClassificationSource,
					"attribute_validation_failures", attributeValidationFailures,
					"attribute_validation_failure_examples", attributeValidationFailureExamples,
					"non_taxi_legs_with_taxi_attributes", nonTaxiLegsWithTaxiAttributes,
					"taxi_legs_missing_route", taxiLegsMissingRoute,
					"taxi_route_invalid_distance", taxiRouteInvalidDistance,
					"taxi_route_undefined_travel_time", taxiRouteUndefinedTravelTime,
					"taxi_route_invalid_travel_time", taxiRouteInvalidTravelTime,
					"taxi_routing_mode_counts", taxiRoutingModeCounts,
					"fare_statistics_hkd", fareStatistics,
					"fare_sum_hkd", fareSumHkd,
					"fare_only_score_sum", fareOnlyScoreSum,
					"fare_only_scorer_taxi_legs", fareOnlyScorerTaxiLegs,
					"expected_fare_only_score_sum", -0.05 * fareSumHkd,
					"representative_taxi_person_id", representativeTaxiPersonId,
					"representative_non_taxi_person_id", representativeNonTaxiPersonId
			);
		}
	}
}
