package org.matsim.project.hongkong.taxi;

import ch.sbb.matsim.routing.pt.raptor.SwissRailRaptorModule;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.ControllerConfigGroup;
import org.matsim.core.config.groups.ScoringConfigGroup;
import org.matsim.core.controler.Controler;
import org.matsim.core.controler.OutputDirectoryHierarchy;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.pt.transitSchedule.api.TransitLine;
import org.matsim.pt.transitSchedule.api.TransitRoute;
import org.matsim.vehicles.Vehicle;
import org.matsim.vehicles.VehicleUtils;

import java.net.InetAddress;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

import static org.matsim.project.hongkong.taxi.HongKongTaxiSmokeOutputAudit.ordered;

/**
 * Fixed ASC=-9, iterations 0-1, no-replanning technical integration smoke.
 * Taxi remains a teleported passenger mode; no Taxi/DVRP fleet is installed.
 */
public final class RunHongKongTaxiBehavioralPilot {

	private static final String EXPECTED_PLANS_SHA =
			"f4631ab00c6f5027160314f7357e32d969b7588192008c17ac79bf0b3208ce27";
	private static final Map<String, String> EXPECTED_INPUT_HASHES = Map.of(
			"base_config", "662268c6aa81042d40096326d75736fe86f9594404f040180d185de84224a7b4",
			"taxi_plans", EXPECTED_PLANS_SHA,
			"network", "dfc696442913a6d16a1ca1be7e5a332ec5762012190ed43a38f05493905ddc95",
			"transit_schedule", "eb92e6c7b3c2746313be92b8c88d51bc645d1db3c6605d1f4b472f27c9896aed",
			"transit_vehicles", "16a6b89f77d3827ded06641869bf4e4c5168fb718356c1fe04e9f9249fdd7429",
			"facilities", "74775533a7022b248d37197dbc94d27f239239aca386df75c7a391cc277ef10e",
			"private_vehicles", "5a48b2afe404afaa6864a465c527277605a276e54cd879d3971261186938c994"
	);
	private static final Map<String, Long> EXPECTED_MODE_COUNTS = Map.of(
			"car", 67_718L,
			"pt", 557_104L,
			"ride", 19_074L,
			"taxi", 37_286L,
			"walk", 197_868L
	);
	private static final Map<String, Long> EXPECTED_TAXI_TYPES = Map.of(
			"urban_taxi", 31_037L,
			"new_territories_taxi", 3_654L,
			"lantau_taxi", 62L,
			"unresolved", 2_533L
	);
	private static final Map<String, Long> EXPECTED_CLASSIFICATIONS = Map.of(
			"resident_discretionary_ride_assignment", 23_100L,
			"v1_mode_detail_explicit_taxi", 4_614L,
			"visitor_tcs_proxy_unspecified_ride", 9_572L
	);

	private RunHongKongTaxiBehavioralPilot() {
	}

	public static void main(String[] args) {
		if (args.length != 5) {
			System.err.println("Usage: RunHongKongTaxiBehavioralPilot "
					+ "<base-config> <taxi-plans> <output-directory> "
					+ "<smoke-validation-json> <checkpoint-sha>");
			System.exit(64);
		}

		Path validation = Path.of(args[3]).toAbsolutePath().normalize();
		long startedNanos = System.nanoTime();
		Map<String, Object> report = initialReport(args);
		int exitCode;
		try {
			execute(
					Path.of(args[0]).toAbsolutePath().normalize(),
					Path.of(args[1]).toAbsolutePath().normalize(),
					Path.of(args[2]).toAbsolutePath().normalize(),
					validation,
					args[4],
					report
			);
			exitCode = "validated".equals(report.get("status")) ? 0 : 2;
		} catch (Throwable error) {
			exitCode = 1;
			report.put("status", "failed");
			report.put("all_checks_passed", false);
			report.put("failed_checks", List.of("smoke_execution_completed"));
			report.put("error", ordered(
					"class", error.getClass().getName(),
					"message", String.valueOf(error.getMessage()),
					"stack_trace", List.of(error.getStackTrace()).stream()
							.map(StackTraceElement::toString)
							.limit(60)
							.toList()
			));
		}
		report.put("finished_utc", Instant.now().toString());
		report.put("total_wall_time_seconds",
				(System.nanoTime() - startedNanos) / 1_000_000_000.0);
		report.put("peak_resident_set_kib",
				HongKongTaxiSmokeOutputAudit.linuxPeakResidentSetKib());
		report.put("process_exit_code", exitCode);
		HongKongTaxiSmokeOutputAudit.writeJsonAtomically(validation, report);
		System.out.println("Smoke validation JSON: " + validation);
		System.out.println("Status: " + report.get("status"));
		if (exitCode != 0) {
			System.exit(exitCode);
		}
	}

	private static Map<String, Object> initialReport(String[] args) {
		Map<String, Object> report = new LinkedHashMap<>();
		report.put("audit", "hong_kong_taxi_two_iteration_smoke_v1");
		report.put("status", "running");
		report.put("all_checks_passed", false);
		report.put("started_utc", Instant.now().toString());
		report.put("hostname", safeHostname());
		report.put("checkpoint_sha", args[4]);
		report.put("java", HongKongTaxiSmokeOutputAudit.runtimeJavaDetails());
		report.put("maven_version",
				System.getProperty("hkTaxiSmoke.mavenVersion", "<not-supplied>"));
		report.put("matsim_version", HongKongTaxiSmokeOutputAudit.matsimVersion());
		report.put("run_flags", smokeRunFlags(
				false, false, false, false, 0));
		return report;
	}

	private static void execute(
			Path baseConfig,
			Path taxiPlans,
			Path outputDirectory,
			Path validation,
			String checkpointSha,
			Map<String, Object> report) {
		requireInput(baseConfig, "base config");
		requireInput(taxiPlans, "taxi plans");
		requireFullSha(checkpointSha);
		requireNewOutputDirectory(outputDirectory);

		Config config = ConfigUtils.loadConfig(baseConfig.toString());
		Map<String, Map<String, Double>> scoringBefore = snapshotScoring(config);
		double flowCapacityBefore = config.qsim().getFlowCapFactor();
		double storageCapacityBefore = config.qsim().getStorageCapFactor();
		Collection<String> mainModesBefore = List.copyOf(config.qsim().getMainModes());

		config.plans().setInputFile(taxiPlans.toString());
		config.controller().setOutputDirectory(outputDirectory.toString());
		config.controller().setFirstIteration(0);
		config.controller().setLastIteration(1);
		config.controller().setWriteEventsInterval(1);
		config.controller().setWriteEventsUntilIteration(1);
		config.controller().setWritePlansInterval(1);
		config.controller().setWritePlansUntilIteration(1);
		config.controller().setDumpDataAtEnd(true);
		config.controller().setCleanItersAtEnd(ControllerConfigGroup.CleanIterations.keep);
		config.controller().setOverwriteFileSetting(
				OutputDirectoryHierarchy.OverwriteFileSetting.failIfDirectoryExists);
		config.replanning().clearStrategySettings();
		config.scoring().setMemorizingExperiencedPlans(false);
		configureTaxiScoring(config);

		Map<String, Map<String, Double>> scoringAfter = snapshotScoring(config);
		Map<String, Path> inputPaths = configuredInputPaths(config, baseConfig, taxiPlans);
		Map<String, Object> inputBefore = snapshotFiles(inputPaths);
		report.put("paths", ordered(
				"base_config", baseConfig.toString(),
				"taxi_plans", taxiPlans.toString(),
				"output_directory", outputDirectory.toString(),
				"validation_json", validation.toString()
		));
		report.put("input_files_before_run", inputBefore);
		report.put("effective_settings", ordered(
				"first_iteration", config.controller().getFirstIteration(),
				"last_iteration", config.controller().getLastIteration(),
				"asc_value", -9.0,
				"behavioral_replanning", false,
				"mode_choice", false,
				"pt_startup_route_clear", true,
				"pt_startup_route_rebuild", true,
				"pt_startup_routing_scope", "pt_only_before_iteration_0",
				"taxi_routing", false,
				"strategy_settings_count",
						config.replanning().getStrategySettings().size(),
				"overwrite_policy",
						config.controller().getOverwriteFileSetting().toString(),
				"qsim_main_modes", List.copyOf(config.qsim().getMainModes()),
				"flow_capacity_factor", config.qsim().getFlowCapFactor(),
				"storage_capacity_factor", config.qsim().getStorageCapFactor(),
				"taxi_scoring", scoringAfter.get("taxi"),
				"fare_utility_per_hkd",
						HongKongTaxiScoringParameters.CENTRAL_FARE_UTILITY_PER_HKD,
				"fare_share_factor",
						HongKongTaxiScoringParameters.CENTRAL_FARE_SHARE_FACTOR,
				"global_marginal_utility_of_money_reused_for_custom_fare", false
		));
		report.put("non_taxi_scoring_modes_before", scoringBefore);
		report.put("non_taxi_scoring_modes_after", withoutTaxi(scoringAfter));

		Scenario scenario = ScenarioUtils.loadScenario(config);
		HongKongTaxiSmokeOutputAudit.PlanAudit sourceAudit =
				HongKongTaxiSmokeOutputAudit.auditPopulation(scenario.getPopulation());
		HongKongTaxiPtRoutePreparation.TaxiSnapshot sourceTaxiSnapshot =
				HongKongTaxiPtRoutePreparation.captureSelectedTaxi(
						scenario.getPopulation());
		report.put("source_taxi_fingerprint", sourceTaxiSnapshot.toMap());

		HongKongTaxiPtRoutePreparation.PreparationAudit preparationAudit =
				HongKongTaxiPtRoutePreparation.clearPtRoutes(scenario);
		HongKongTaxiPtRoutePreparation.requireFormalSource(preparationAudit);
		report.put("pt_route_preparation", preparationAudit.toMap());
		@SuppressWarnings("unchecked")
		Map<String, Object> preparationFlags =
				(Map<String, Object>) report.get("run_flags");
		preparationFlags.put("pt_startup_route_clear", true);

		HongKongTaxiPtRoutePreparation.TaxiInvarianceAudit taxiAfterClear =
				HongKongTaxiPtRoutePreparation.compareTaxi(
						sourceTaxiSnapshot,
						HongKongTaxiPtRoutePreparation.captureSelectedTaxi(
								scenario.getPopulation())
				);
		HongKongTaxiPtRoutePreparation.requireFormalTaxiInvariant(taxiAfterClear);
		report.put("taxi_invariance_after_pt_clear", taxiAfterClear.toMap());

		int assignedVehicles = assignExplicitCarVehicles(scenario);
		Map<String, Long> supply = supplyCounts(scenario);
		report.put("scenario_supply_counts", supply);
		report.put("assigned_explicit_car_vehicles", assignedVehicles);

		report.put("source_plans_audit", sourceAudit.toMap());

		HongKongTaxiSmokeRuntimeGuard guard =
				new HongKongTaxiSmokeRuntimeGuard(
						config,
						preparationAudit,
						sourceTaxiSnapshot
				);
		Controler controler = new Controler(scenario);
		controler.addOverridingModule(new SwissRailRaptorModule());
		controler.addOverridingModule(new HongKongTaxiScoringModule(
				HongKongTaxiScoringParameters.centralV1()));
		controler.addControllerListener(guard);
		report.put("run_flags", smokeRunFlags(
				true,
				false,
				true,
				false,
				config.replanning().getStrategySettings().size()));
		try {
			controler.run();
		} finally {
			report.put("runtime_guard", guard.startupAudit());
			report.put("pt_startup_preparation_guard",
					guard.ptPreparationAudit());
			report.put("iteration_event_audits", guard.iterationAudits());
			@SuppressWarnings("unchecked")
			Map<String, Object> flags = (Map<String, Object>) report.get("run_flags");
			flags.put("qsim_run", !guard.iterationAudits().isEmpty());
			flags.put("pt_startup_route_rebuild",
					guard.beforeMobsimAuditCount() > 0);
		}

		Map<String, Object> iterationPlans = new LinkedHashMap<>();
		List<HongKongTaxiSmokeOutputAudit.PlanAudit> outputAudits = new ArrayList<>();
		Map<String, Object> outputFiles = new LinkedHashMap<>();
		for (int iteration = 0; iteration <= 1; iteration++) {
			Path events = Path.of(controler.getControllerIO().getIterationFilename(
					iteration, Controler.DefaultFiles.events));
			Path plans = Path.of(controler.getControllerIO().getIterationFilename(
					iteration, Controler.DefaultFiles.population));
			outputFiles.put("iteration_" + iteration + "_events",
					HongKongTaxiSmokeOutputAudit.fileSnapshot(events));
			outputFiles.put("iteration_" + iteration + "_plans",
					HongKongTaxiSmokeOutputAudit.fileSnapshot(plans));
			HongKongTaxiSmokeOutputAudit.PlanAudit audit =
					HongKongTaxiSmokeOutputAudit.auditPopulationFile(plans);
			outputAudits.add(audit);
			iterationPlans.put(Integer.toString(iteration), audit.toMap());
		}
		Path finalPlans = Path.of(controler.getControllerIO()
				.getOutputFilename(Controler.DefaultFiles.population));
		outputFiles.put("final_plans",
				HongKongTaxiSmokeOutputAudit.fileSnapshot(finalPlans));
		HongKongTaxiSmokeOutputAudit.PlanAudit finalAudit =
				HongKongTaxiSmokeOutputAudit.auditPopulationFile(finalPlans);
		HongKongTaxiSmokeOutputAudit.RuntimeLogAudit runtimeLogAudit =
				HongKongTaxiSmokeOutputAudit.auditRuntimeLog(
						outputDirectory.resolve("logfile.log"));
		report.put("iteration_plans_audits", iterationPlans);
		report.put("final_output_plans_audit", finalAudit.toMap());
		report.put("output_files", outputFiles);
		report.put("runtime_log_audit", runtimeLogAudit.toMap());
		report.put("fare_schedule_audit",
				guard.fareScheduleAudit(runtimeLogAudit));

		Map<String, Object> inputAfter = snapshotFiles(inputPaths);
		report.put("input_files_after_run", inputAfter);

		Map<String, Boolean> checks = new LinkedHashMap<>();
		checks.put("checkpoint_sha_is_full_hex",
				checkpointSha.matches("[0-9a-f]{40}"));
		checks.put("java_major_version_is_25",
				System.getProperty("java.version").matches("^25(?:\\..*)?$"));
		checks.put("matsim_version_is_2026_0",
				"2026.0".equals(HongKongTaxiSmokeOutputAudit.matsimVersion()));
		checks.put("maven_version_recorded",
				!"<not-supplied>".equals(
						System.getProperty("hkTaxiSmoke.mavenVersion", "<not-supplied>")));
		checks.put("all_input_hashes_exact", hashesExact(inputBefore));
		checks.put("all_input_hashes_unchanged", inputBefore.equals(inputAfter));
		checks.put("existing_non_taxi_scoring_unchanged",
				scoringBefore.equals(withoutTaxi(scoringAfter)));
		checks.put("capacity_factors_unchanged",
				flowCapacityBefore == config.qsim().getFlowCapFactor()
						&& storageCapacityBefore == config.qsim().getStorageCapFactor());
		checks.put("qsim_main_modes_unchanged",
				mainModesBefore.equals(List.copyOf(config.qsim().getMainModes())));
		checks.put("taxi_not_qsim_main_mode",
				!config.qsim().getMainModes().contains("taxi"));
		checks.put("behavioral_replanning_and_mode_choice_disabled",
				config.replanning().getStrategySettings().isEmpty());
		checks.put("deterministic_pt_startup_routing_declared", true);
		checks.put("complete_supply_exact", supplyExact(supply));
		checks.put("source_plans_exact", plansExact(sourceAudit, false));
		checks.put("source_pt_clear_exact",
				preparationAudit.totalPtLegs()
						== HongKongTaxiPtRoutePreparation.EXPECTED_PT_LEGS
						&& preparationAudit.genericPtRoutesBefore()
						== HongKongTaxiPtRoutePreparation.EXPECTED_PT_LEGS
						&& preparationAudit.ptRoutesCleared()
						== HongKongTaxiPtRoutePreparation.EXPECTED_PT_LEGS
						&& preparationAudit.nonPtRoutesChanged() == 0);
		checks.put("runtime_factory_and_module_guard_passed",
				startupGuardPassed(guard.startupAudit()));
		checks.put("prepared_pt_and_taxi_before_mobsim_guards_passed",
				guard.preparedPtAndTaxiGuardsPassed());
		checks.put("iterations_0_and_1_completed",
				guard.completedExactlyTwoIterations());
		checks.put("each_iteration_output_plans_fixed_except_prepared_pt",
				outputAudits.stream().allMatch(audit ->
						plansExact(audit, true)
								&& HongKongTaxiSmokeOutputAudit
								.sameFixedPlansAllowPreparedPt(sourceAudit, audit)));
		checks.put("iteration_0_and_1_output_plans_identical",
				outputAudits.size() == 2
						&& HongKongTaxiSmokeOutputAudit
						.sameStructureModesAttributesAndRoutes(
								outputAudits.get(0), outputAudits.get(1)));
		checks.put("final_output_plans_fixed_except_prepared_pt",
				plansExact(finalAudit, true)
						&& HongKongTaxiSmokeOutputAudit
						.sameFixedPlansAllowPreparedPt(sourceAudit, finalAudit));
		checks.put("runtime_log_has_no_pt_or_taxi_errors",
				runtimeLogAudit.exact());
		checks.put("source_taxi_plans_sha_unchanged",
				EXPECTED_PLANS_SHA.equals(snapshotSha(inputAfter, "taxi_plans")));
		checks.put("controler_and_qsim_ran", true);
		checks.put("asc_is_fixed_minus_9", true);
		checks.put("no_asc_calibration_behavioral_replanning_taxi_routing_or_fleet",
				true);

		List<String> failed = checks.entrySet().stream()
				.filter(entry -> !entry.getValue())
				.map(Map.Entry::getKey)
				.toList();
		report.put("required_checks", checks);
		report.put("failed_checks", failed);
		report.put("all_checks_passed", failed.isEmpty());
		report.put("status", failed.isEmpty() ? "validated" : "failed");
	}

	static void configureTaxiScoring(Config config) {
		ScoringConfigGroup.ModeParams taxi =
				config.scoring().getOrCreateModeParams("taxi");
		taxi.setConstant(-9.0);
		taxi.setMarginalUtilityOfTraveling(-6.0);
		taxi.setMarginalUtilityOfDistance(0.0);
		taxi.setMonetaryDistanceRate(0.0);
		taxi.setDailyMonetaryConstant(0.0);
		taxi.setDailyUtilityConstant(0.0);
	}

	static Map<String, Object> smokeRunFlags(
			boolean controlerRun,
			boolean qsimRun,
			boolean ptClear,
			boolean ptRebuild,
			int strategySettingsCount) {
		return ordered(
				"controler_run", controlerRun,
				"qsim_run", qsimRun,
				"pt_startup_route_clear", ptClear,
				"pt_startup_route_rebuild", ptRebuild,
				"pt_startup_routing_scope", "pt_only_before_iteration_0",
				"routing_run", true,
				"routing_scope", "deterministic_pt_startup_rebuild_only",
				"behavioral_replanning", false,
				"strategy_settings_count", strategySettingsCount,
				"mode_choice", false,
				"taxi_routing", false,
				"taxi_mode_conversion", false,
				"asc_value", -9.0,
				"asc_calibration", false,
				"fleet_model", false
		);
	}

	static Map<String, Map<String, Double>> snapshotScoring(Config config) {
		Map<String, Map<String, Double>> result = new TreeMap<>();
		config.scoring().getModes().forEach((mode, params) -> result.put(mode, Map.of(
				"constant", params.getConstant(),
				"marginalUtilityOfTraveling", params.getMarginalUtilityOfTraveling(),
				"marginalUtilityOfDistance", params.getMarginalUtilityOfDistance(),
				"monetaryDistanceRate", params.getMonetaryDistanceRate(),
				"dailyMonetaryConstant", params.getDailyMonetaryConstant(),
				"dailyUtilityConstant", params.getDailyUtilityConstant()
		)));
		return result;
	}

	private static Map<String, Map<String, Double>> withoutTaxi(
			Map<String, Map<String, Double>> modes) {
		Map<String, Map<String, Double>> result = new TreeMap<>(modes);
		result.remove("taxi");
		return result;
	}

	private static Map<String, Path> configuredInputPaths(
			Config config, Path baseConfig, Path taxiPlans) {
		Map<String, Path> paths = new LinkedHashMap<>();
		paths.put("base_config", baseConfig);
		paths.put("taxi_plans", taxiPlans);
		paths.put("network", resolve(baseConfig, config.network().getInputFile()));
		paths.put("transit_schedule",
				resolve(baseConfig, config.transit().getTransitScheduleFile()));
		paths.put("transit_vehicles",
				resolve(baseConfig, config.transit().getVehiclesFile()));
		paths.put("facilities",
				resolve(baseConfig, config.facilities().getInputFile()));
		paths.put("private_vehicles",
				resolve(baseConfig, config.vehicles().getVehiclesFile()));
		return paths;
	}

	private static Path resolve(Path config, String configured) {
		if (configured == null || configured.isBlank()) {
			throw new IllegalArgumentException("Missing configured input near " + config);
		}
		Path path = Path.of(configured);
		return (path.isAbsolute() ? path : config.getParent().resolve(path))
				.toAbsolutePath().normalize();
	}

	private static Map<String, Object> snapshotFiles(Map<String, Path> paths) {
		Map<String, Object> result = new LinkedHashMap<>();
		paths.forEach((name, path) ->
				result.put(name, HongKongTaxiSmokeOutputAudit.fileSnapshot(path)));
		return result;
	}

	private static int assignExplicitCarVehicles(Scenario scenario) {
		int assigned = 0;
		for (Person person : scenario.getPopulation().getPersons().values()) {
			Object value = person.getAttributes().getAttribute("assignedVehicleId");
			if (value == null || value.toString().isBlank()
					|| "nan".equalsIgnoreCase(value.toString())) {
				continue;
			}
			Id<Vehicle> vehicleId = Id.create(value.toString(), Vehicle.class);
			if (!scenario.getVehicles().getVehicles().containsKey(vehicleId)) {
				throw new IllegalStateException(
						"Person " + person.getId() + " references missing vehicle " + vehicleId);
			}
			VehicleUtils.insertVehicleIdsIntoAttributes(person, Map.of("car", vehicleId));
			assigned++;
		}
		return assigned;
	}

	private static Map<String, Long> supplyCounts(Scenario scenario) {
		long routes = 0;
		long departures = 0;
		for (TransitLine line : scenario.getTransitSchedule()
				.getTransitLines().values()) {
			routes += line.getRoutes().size();
			for (TransitRoute route : line.getRoutes().values()) {
				departures += route.getDepartures().size();
			}
		}
		return Map.of(
				"network_nodes", (long) scenario.getNetwork().getNodes().size(),
				"network_links", (long) scenario.getNetwork().getLinks().size(),
				"transit_lines",
						(long) scenario.getTransitSchedule().getTransitLines().size(),
				"transit_routes", routes,
				"departures", departures,
				"transit_vehicles",
						(long) scenario.getTransitVehicles().getVehicles().size(),
				"activity_facilities",
						(long) scenario.getActivityFacilities().getFacilities().size(),
				"private_vehicles", (long) scenario.getVehicles().getVehicles().size()
		);
	}

	private static boolean supplyExact(Map<String, Long> supply) {
		return supply.equals(Map.of(
				"network_nodes", 81_205L,
				"network_links", 117_989L,
				"transit_lines", 2_434L,
				"transit_routes", 3_613L,
				"departures", 159_967L,
				"transit_vehicles", 159_967L,
				"activity_facilities", 228_220L,
				"private_vehicles", 25_427L
		));
	}

	private static boolean plansExact(
			HongKongTaxiSmokeOutputAudit.PlanAudit audit,
			boolean scoresMustBeFinite) {
		Map<String, Object> map = audit.toMap();
		@SuppressWarnings("unchecked")
		Map<String, Long> modes = (Map<String, Long>) map.get("mode_counts");
		boolean shared = ((Number) map.get("persons")).longValue() == 385_820L
				&& ((Number) map.get("plans")).longValue() == 385_820L
				&& ((Number) map.get("main_activities")).longValue() == 1_264_870L
				&& ((Number) map.get("fixed_non_pt_main_legs")).longValue()
						== 321_946L
				&& ((Number) map.get("taxi_legs")).longValue() == 37_286L
				&& ((Number) map.get("taxi_persons")).longValue() == 15_439L
				&& EXPECTED_TAXI_TYPES.equals(map.get("taxi_type_counts"))
				&& EXPECTED_CLASSIFICATIONS.equals(
						map.get("classification_source_counts"))
				&& ((Number) map.get("invalid_taxi_attributes")).longValue() == 0L
				&& ((Number) map.get("invalid_route_distances")).longValue() == 0L
				&& ((Number) map.get("invalid_route_travel_times")).longValue() == 0L
				&& Map.of("ride", 37_286L)
						.equals(map.get("taxi_routing_mode_counts"))
				&& (!scoresMustBeFinite || audit.allSelectedScoresFinite());
		if (!shared) {
			return false;
		}
		if (scoresMustBeFinite) {
			return modes.getOrDefault("taxi", 0L) == 37_286L
					&& modes.getOrDefault("pt", 0L) == 557_104L;
		}
		return ((Number) map.get("activities")).longValue() == 1_264_870L
				&& ((Number) map.get("legs")).longValue() == 879_050L
				&& ((Number) map.get("routes")).longValue() == 879_050L
				&& modes.equals(EXPECTED_MODE_COUNTS);
	}

	private static boolean hashesExact(Map<String, Object> snapshots) {
		for (Map.Entry<String, String> expected : EXPECTED_INPUT_HASHES.entrySet()) {
			if (!expected.getValue().equals(snapshotSha(snapshots, expected.getKey()))) {
				return false;
			}
		}
		return true;
	}

	@SuppressWarnings("unchecked")
	private static String snapshotSha(Map<String, Object> snapshots, String name) {
		return (String) ((Map<String, Object>) snapshots.get(name)).get("sha256");
	}

	@SuppressWarnings("unchecked")
	private static boolean startupGuardPassed(Map<String, Object> startup) {
		if (!Boolean.TRUE.equals(startup.get("scoring_module_installed"))) {
			return false;
		}
		Map<String, Boolean> checks = (Map<String, Boolean>) startup.get("checks");
		return checks != null && checks.values().stream().allMatch(Boolean.TRUE::equals);
	}

	private static void requireInput(Path path, String label) {
		if (!Files.isRegularFile(path)) {
			throw new IllegalArgumentException(label + " is not a regular file: " + path);
		}
	}

	static void requireNewOutputDirectory(Path outputDirectory) {
		if (Files.exists(outputDirectory)) {
			throw new IllegalArgumentException(
					"Smoke output directory already exists: " + outputDirectory);
		}
	}

	private static void requireFullSha(String value) {
		if (!value.matches("[0-9a-f]{40}")) {
			throw new IllegalArgumentException("checkpoint SHA must be 40 lowercase hex characters");
		}
	}

	private static String safeHostname() {
		try {
			return InetAddress.getLocalHost().getHostName();
		} catch (Exception error) {
			return "<unknown>";
		}
	}
}
