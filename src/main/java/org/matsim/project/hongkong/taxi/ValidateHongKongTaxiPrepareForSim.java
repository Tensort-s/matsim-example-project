package org.matsim.project.hongkong.taxi;

import ch.sbb.matsim.routing.pt.raptor.SwissRailRaptorModule;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.controler.Controler;
import org.matsim.core.controler.PrepareForSim;
import org.matsim.core.controler.PrepareForSimImpl;
import org.matsim.core.scenario.ScenarioUtils;

import java.net.InetAddress;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

import static org.matsim.project.hongkong.taxi.HongKongTaxiSmokeOutputAudit.ordered;

/**
 * Runs MATSim's bound {@link PrepareForSimImpl} once on the complete scenario
 * and performs route/fare audits without starting Controler iterations or a
 * Mobsim.
 */
public final class ValidateHongKongTaxiPrepareForSim {

	private ValidateHongKongTaxiPrepareForSim() {
	}

	public static void main(String[] args) {
		if (args.length != 4) {
			System.err.println("Usage: ValidateHongKongTaxiPrepareForSim "
					+ "<base-config> <native-taxi-plans> "
					+ "<validation-json> <checkpoint-sha>");
			System.exit(64);
		}

		Path validation = Path.of(args[2]).toAbsolutePath().normalize();
		Map<String, Object> report = initialReport(args);
		int exitCode;
		try {
			execute(
					Path.of(args[0]).toAbsolutePath().normalize(),
					Path.of(args[1]).toAbsolutePath().normalize(),
					validation,
					args[3],
					report);
			exitCode = Boolean.TRUE.equals(report.get("all_checks_passed")) ? 0 : 2;
		} catch (Throwable error) {
			report.put("status", "failed");
			report.put("all_checks_passed", false);
			report.put("failed_checks", List.of("prepare_for_sim_execution_completed"));
			report.put("error", ordered(
					"class", error.getClass().getName(),
					"message", String.valueOf(error.getMessage()),
					"stack_trace", List.of(error.getStackTrace()).stream()
							.map(StackTraceElement::toString)
							.limit(60)
							.toList()));
			exitCode = 1;
		}
		report.put("finished_utc", Instant.now().toString());
		report.put("peak_resident_set_kib",
				HongKongTaxiSmokeOutputAudit.linuxPeakResidentSetKib());
		report.put("process_exit_code", exitCode);
		HongKongTaxiSmokeOutputAudit.writeJsonAtomically(validation, report);
		System.out.println("PrepareForSim validation JSON: " + validation);
		System.out.println("Status: " + report.get("status"));
		if (exitCode != 0) {
			System.exit(exitCode);
		}
	}

	private static Map<String, Object> initialReport(String[] args) {
		Map<String, Object> report = new LinkedHashMap<>();
		report.put("audit", "hong_kong_taxi_default_prepare_for_sim_v1");
		report.put("status", "running");
		report.put("all_checks_passed", false);
		report.put("started_utc", Instant.now().toString());
		report.put("hostname", hostname());
		report.put("checkpoint_sha", args[3]);
		report.put("java", HongKongTaxiSmokeOutputAudit.runtimeJavaDetails());
		report.put("maven_version",
				System.getProperty("hkTaxiPrepare.mavenVersion", "<not-supplied>"));
		report.put("matsim_version", HongKongTaxiSmokeOutputAudit.matsimVersion());
		return report;
	}

	private static void execute(
			Path baseConfig,
			Path taxiPlans,
			Path validation,
			String checkpointSha,
			Map<String, Object> report) {
		requireRegularFile(baseConfig, "base config");
		requireRegularFile(taxiPlans, "native Taxi plans");
		if (!checkpointSha.matches("[0-9a-f]{40}")) {
			throw new IllegalArgumentException(
					"checkpoint SHA must be 40 lowercase hex characters");
		}

		Config config = ConfigUtils.loadConfig(baseConfig.toString());
		Path controllerOutput = validation.resolveSibling("controller_output");
		if (Files.exists(controllerOutput)) {
			throw new IllegalArgumentException(
					"PrepareForSim validation Controler output already exists: "
							+ controllerOutput);
		}
		config.controller().setOutputDirectory(controllerOutput.toString());
		double flowCapacityBefore = config.qsim().getFlowCapFactor();
		double storageCapacityBefore = config.qsim().getStorageCapFactor();
		List<String> mainModesBefore = List.copyOf(config.qsim().getMainModes());
		Map<String, Map<String, Double>> scoringBefore =
				RunHongKongTaxiBehavioralPilot.snapshotScoring(config);
		config.plans().setInputFile(taxiPlans.toString());
		config.replanning().clearStrategySettings();
		config.scoring().setMemorizingExperiencedPlans(false);
		RunHongKongTaxiBehavioralPilot.configureTaxiScoring(config);
		HongKongTaxiRoutingModule.configure(config);

		Map<String, Path> inputPaths =
				RunHongKongTaxiBehavioralPilot.configuredInputPaths(
						config, baseConfig, taxiPlans);
		Map<String, Object> inputSnapshots =
				RunHongKongTaxiBehavioralPilot.snapshotFiles(inputPaths);
		report.put("paths", ordered(
				"base_config", baseConfig.toString(),
				"taxi_plans", taxiPlans.toString(),
				"controller_output", controllerOutput.toString()));
		report.put("input_files", inputSnapshots);

		Scenario scenario = ScenarioUtils.loadScenario(config);
		HongKongTaxiPtRoutePreparation.TaxiSnapshot sourceTaxi =
				HongKongTaxiPtRoutePreparation.captureSelectedTaxi(
						scenario.getPopulation());
		HongKongTaxiPtRoutePreparation.PreparationAudit clearAudit =
				HongKongTaxiPtRoutePreparation.clearPtRoutes(scenario);
		HongKongTaxiPtRoutePreparation.requireFormalSource(clearAudit);
		int assignedVehicles =
				RunHongKongTaxiBehavioralPilot.assignExplicitCarVehicles(scenario);

		Controler controler = new Controler(scenario);
		controler.addOverridingModule(new SwissRailRaptorModule());
		controler.addOverridingModule(new HongKongTaxiRoutingModule());
		controler.addOverridingModule(new HongKongTaxiScoringModule(
				HongKongTaxiScoringParameters.centralV1()));

		PrepareForSim prepareForSim =
				controler.getInjector().getInstance(PrepareForSim.class);
		long customRebuildBefore =
				HongKongTaxiPtRoutePreparation.customStartupRebuildInvocationCount();
		long prepareStarted = System.nanoTime();
		prepareForSim.run();
		double prepareSeconds =
				(System.nanoTime() - prepareStarted) / 1_000_000_000.0;
		long customRebuildAfter =
				HongKongTaxiPtRoutePreparation.customStartupRebuildInvocationCount();

		HongKongTaxiPtRoutePreparation.PtRuntimeAudit ptAudit =
				HongKongTaxiPtRoutePreparation.auditPreparedSelectedPt(scenario);
		HongKongTaxiPtRoutePreparation.TaxiSnapshot preparedTaxi =
				HongKongTaxiPtRoutePreparation.captureSelectedTaxi(
						scenario.getPopulation());
		HongKongTaxiPtRoutePreparation.TaxiInvarianceAudit taxiChanges =
				HongKongTaxiPtRoutePreparation.compareTaxi(
						sourceTaxi, preparedTaxi);
		TaxiFareAudit taxiFareAudit = auditTaxiFares(scenario);

		HongKongTaxiScoringFunctionFactory scoringFactory =
				(HongKongTaxiScoringFunctionFactory)
						controler.getScoringFunctionFactory();
		Person representative = scenario.getPopulation().getPersons().values().stream()
				.filter(person -> person.getSelectedPlan() != null
						&& person.getSelectedPlan().getPlanElements().stream()
						.anyMatch(element -> element instanceof Leg leg
								&& "taxi".equals(leg.getMode())))
				.findFirst()
				.orElseThrow();
		HongKongTaxiPersonFareSchedule representativeSchedule =
				scoringFactory.routeFareScheduleFor(representative);
		boolean representativeScheduleExact =
				representativeSchedule.size() > 0
						&& representativeSchedule.fareAt(0).calculation().fareHkd()
						== new HongKongTaxiFareCalculator().calculate(
								representativeSchedule.fareAt(0)
										.routeContext().distanceMeters(),
								representativeSchedule.fareAt(0)
										.routeContext().taxiType()).fareHkd();

		Map<String, Map<String, Double>> scoringAfter =
				RunHongKongTaxiBehavioralPilot.snapshotScoring(config);
		Map<String, Map<String, Double>> nonTaxiBefore =
				new TreeMap<>(scoringBefore);
		Map<String, Map<String, Double>> nonTaxiAfter =
				new TreeMap<>(scoringAfter);
		nonTaxiBefore.remove("taxi");
		nonTaxiAfter.remove("taxi");

		report.put("prepare_for_sim", ordered(
				"binding_class", prepareForSim.getClass().getName(),
				"default_prepare_for_sim_impl",
						prepareForSim instanceof PrepareForSimImpl,
				"parallel_threads", config.global().getNumberOfThreads(),
				"wall_time_seconds", prepareSeconds,
				"custom_rebuild_invocations_before", customRebuildBefore,
				"custom_rebuild_invocations_after", customRebuildAfter,
				"custom_rebuild_invocation_delta",
						customRebuildAfter - customRebuildBefore));
		report.put("pt_source_clear", clearAudit.toMap());
		report.put("prepared_pt", ptAudit.toMap());
		report.put("taxi_prepare_changes", taxiChanges.toMap());
		report.put("prepared_taxi_route_and_fare", taxiFareAudit.toMap());
		report.put("scoring_lifecycle", ordered(
				"representative_person_id", representative.getId().toString(),
				"representative_taxi_schedule_size",
						representativeSchedule.size(),
				"factory_schedule_matches_prepared_route",
						representativeScheduleExact,
				"scoring_factory_class", scoringFactory.getClass().getName()));
		report.put("assigned_explicit_car_vehicles", assignedVehicles);
		report.put("scenario_supply_counts",
				RunHongKongTaxiBehavioralPilot.supplyCounts(scenario));
		report.put("run_flags", ordered(
				"controler_run", false,
				"qsim_run", false,
				"mobsim_run", false,
				"prepare_for_sim_run", true,
				"custom_pt_rebuild_run", false,
				"behavioral_replanning", false,
				"mode_choice", false,
				"fleet_or_dvrp", false));

		Map<String, Boolean> checks = new LinkedHashMap<>();
		checks.put("checkpoint_sha_full", checkpointSha.matches("[0-9a-f]{40}"));
		checks.put("matsim_2026_0",
				"2026.0".equals(HongKongTaxiSmokeOutputAudit.matsimVersion()));
		checks.put("all_input_hashes_exact",
				RunHongKongTaxiBehavioralPilot.hashesExact(inputSnapshots));
		checks.put("default_prepare_for_sim_impl_completed",
				prepareForSim instanceof PrepareForSimImpl);
		checks.put("custom_rebuild_invocation_delta_zero",
				customRebuildBefore == customRebuildAfter);
		checks.put("pt_routes_legal",
				ptAudit.totalPtLegs() == 557_104
						&& ptAudit.transitPassengerRoute() == 557_104
						&& ptAudit.routeNull() == 0
						&& ptAudit.genericRouteImpl() == 0
						&& ptAudit.accessStopMissing() == 0
						&& ptAudit.egressStopMissing() == 0
						&& ptAudit.lineIdMissing() == 0
						&& ptAudit.transitRouteIdMissing() == 0
						&& ptAudit.accessStopNotInSchedule() == 0
						&& ptAudit.egressStopNotInSchedule() == 0
						&& ptAudit.lineNotInSchedule() == 0
						&& ptAudit.routeNotInSchedule() == 0);
		checks.put("taxi_identity_preserved_allowing_routes",
				taxiChanges.identityExactAllowRouteChanges());
		checks.put("taxi_count_mode_routing_exact",
				taxiFareAudit.taxiLegs == 37_286
						&& taxiFareAudit.routingModeTaxi == 37_286
						&& taxiFareAudit.taxiConvertedToRide == 0);
		checks.put("taxi_routes_legal",
				taxiFareAudit.nullRoutes == 0
						&& taxiFareAudit.invalidRoutes == 0);
		checks.put("route_fares_all_calculated",
				taxiFareAudit.fareFailures == 0
						&& taxiFareAudit.calculatedFares.size() == 37_286);
		checks.put("scoring_factory_reads_prepared_route",
				representativeScheduleExact);
		checks.put("capacity_and_main_modes_unchanged",
				flowCapacityBefore == config.qsim().getFlowCapFactor()
						&& storageCapacityBefore
						== config.qsim().getStorageCapFactor()
						&& mainModesBefore.equals(
								List.copyOf(config.qsim().getMainModes())));
		checks.put("non_taxi_scoring_unchanged",
				nonTaxiBefore.equals(nonTaxiAfter));
		checks.put("taxi_not_network_or_qsim_mode",
				!config.qsim().getMainModes().contains("taxi")
						&& !config.routing().getNetworkModes().contains("taxi"));

		List<String> failed = checks.entrySet().stream()
				.filter(entry -> !entry.getValue())
				.map(Map.Entry::getKey)
				.toList();
		report.put("required_checks", checks);
		report.put("failed_checks", failed);
		report.put("all_checks_passed", failed.isEmpty());
		report.put("status", failed.isEmpty() ? "validated" : "failed");
	}

	private static TaxiFareAudit auditTaxiFares(Scenario scenario) {
		TaxiFareAudit audit = new TaxiFareAudit();
		HongKongTaxiFareCalculator calculator = new HongKongTaxiFareCalculator();
		for (Person person : scenario.getPopulation().getPersons().values()) {
			if (person.getSelectedPlan() == null) {
				continue;
			}
			for (PlanElement element :
					person.getSelectedPlan().getPlanElements()) {
				if (!(element instanceof Leg leg)) {
					continue;
				}
				boolean carriesTaxiType = leg.getAttributes().getAsMap()
						.containsKey(HongKongTaxiLegAttributes.TAXI_TYPE);
				if (!"taxi".equals(leg.getMode())) {
					if (carriesTaxiType && "ride".equals(leg.getMode())) {
						audit.taxiConvertedToRide++;
					}
					continue;
				}
				audit.taxiLegs++;
				if ("taxi".equals(leg.getRoutingMode())) {
					audit.routingModeTaxi++;
				}
				if (leg.getRoute() == null) {
					audit.nullRoutes++;
					continue;
				}
				if (!Double.isFinite(leg.getRoute().getDistance())
						|| leg.getRoute().getDistance() < 0.0
						|| leg.getRoute().getTravelTime().isUndefined()
						|| !Double.isFinite(
								leg.getRoute().getTravelTime().seconds())
						|| leg.getRoute().getTravelTime().seconds() < 0.0) {
					audit.invalidRoutes++;
					continue;
				}
				try {
					HongKongTaxiRouteContext context =
							HongKongTaxiRouteContext.from(leg);
					HongKongTaxiFareCalculator.FareResult fare =
							calculator.calculate(
									context.distanceMeters(),
									context.taxiType());
					audit.calculatedFares.add(fare.fareHkd());
					audit.fareSum += fare.fareHkd();
					audit.typeCounts.merge(
							fare.requestedTaxiType(), 1L, Long::sum);
					if (fare.unresolvedUrbanFallback()) {
						audit.unresolvedFallbacks++;
					}
				} catch (RuntimeException error) {
					audit.fareFailures++;
					if (audit.failureExamples.size() < 10) {
						audit.failureExamples.add(
								person.getId() + ": " + error.getMessage());
					}
				}
			}
		}
		return audit;
	}

	private static final class TaxiFareAudit {
		long taxiLegs;
		long routingModeTaxi;
		long taxiConvertedToRide;
		long nullRoutes;
		long invalidRoutes;
		long fareFailures;
		long unresolvedFallbacks;
		double fareSum;
		final List<Double> calculatedFares = new ArrayList<>();
		final Map<String, Long> typeCounts = new TreeMap<>();
		final List<String> failureExamples = new ArrayList<>();

		Map<String, Object> toMap() {
			return ordered(
					"taxi_legs", taxiLegs,
					"routing_mode_taxi", routingModeTaxi,
					"taxi_converted_to_ride", taxiConvertedToRide,
					"null_routes", nullRoutes,
					"invalid_routes", invalidRoutes,
					"route_fare_calculation_failures", fareFailures,
					"calculated_route_fares", calculatedFares.size(),
					"fare_sum_hkd", fareSum,
					"fare_mean_hkd",
							calculatedFares.isEmpty()
									? 0.0
									: fareSum / calculatedFares.size(),
					"fare_median_hkd", median(calculatedFares),
					"taxi_type_counts", typeCounts,
					"unresolved_urban_fallbacks", unresolvedFallbacks,
					"failure_examples", failureExamples);
		}
	}

	private static double median(List<Double> values) {
		if (values.isEmpty()) {
			return 0.0;
		}
		List<Double> sorted = values.stream()
				.sorted(Comparator.naturalOrder())
				.toList();
		int middle = sorted.size() / 2;
		return sorted.size() % 2 == 1
				? sorted.get(middle)
				: (sorted.get(middle - 1) + sorted.get(middle)) / 2.0;
	}

	private static void requireRegularFile(Path path, String label) {
		if (!Files.isRegularFile(path)) {
			throw new IllegalArgumentException(
					label + " is not a regular file: " + path);
		}
	}

	private static String hostname() {
		try {
			return InetAddress.getLocalHost().getHostName();
		} catch (Exception error) {
			return "<unknown>";
		}
	}
}
