package org.matsim.project.hongkong.taxi;

import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.events.PersonArrivalEvent;
import org.matsim.api.core.v01.events.PersonDepartureEvent;
import org.matsim.api.core.v01.events.PersonMoneyEvent;
import org.matsim.api.core.v01.events.PersonStuckEvent;
import org.matsim.api.core.v01.events.VehicleEntersTrafficEvent;
import org.matsim.core.config.Config;
import org.matsim.core.controler.events.AfterMobsimEvent;
import org.matsim.core.controler.events.BeforeMobsimEvent;
import org.matsim.core.controler.events.StartupEvent;
import org.matsim.core.controler.PrepareForSim;
import org.matsim.core.controler.PrepareForSimImpl;
import org.matsim.core.controler.listener.AfterMobsimListener;
import org.matsim.core.controler.listener.BeforeMobsimListener;
import org.matsim.core.controler.listener.StartupListener;
import org.matsim.core.events.handler.BasicEventHandler;
import org.matsim.core.scoring.ScoringFunctionFactory;
import org.matsim.pt.transitSchedule.api.TransitLine;
import org.matsim.pt.transitSchedule.api.TransitRoute;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Proves the actual scoring binding at startup and fails the smoke run at the
 * end of an iteration if QSim emits any forbidden Taxi/fleet/stuck condition.
 */
public final class HongKongTaxiSmokeRuntimeGuard implements
		StartupListener, BeforeMobsimListener, AfterMobsimListener, BasicEventHandler {

	static final long EXPECTED_TAXI_LEGS = 37_286L;
	private static final String EXPECTED_FACTORY =
			"org.matsim.project.hongkong.taxi.HongKongTaxiScoringFunctionFactory";

	private final Config config;
	private final HongKongTaxiPtRoutePreparation.PreparationAudit preparationAudit;
	private final HongKongTaxiPtRoutePreparation.TaxiSnapshot sourceTaxiSnapshot;
	private final long customRebuildInvocationsAtConstruction;
	private final Map<Integer, IterationEvents> iterations = new LinkedHashMap<>();
	private final Map<Integer, HongKongTaxiPtRoutePreparation.PtRuntimeAudit>
			preparedPtByIteration = new LinkedHashMap<>();
	private final Map<Integer, HongKongTaxiPtRoutePreparation.TaxiInvarianceAudit>
			taxiInvarianceByIteration = new LinkedHashMap<>();
	private final Map<String, Boolean> dangerousEventTypes = new ConcurrentHashMap<>();
	private Map<String, Object> startupAudit = Map.of();
	private HongKongTaxiPtRoutePreparation.TaxiSnapshot preparedTaxiSnapshot;
	private IterationEvents current;
	private long afterMobsimWithoutLiveAudit;

	public HongKongTaxiSmokeRuntimeGuard(
			Config config,
			HongKongTaxiPtRoutePreparation.PreparationAudit preparationAudit,
			HongKongTaxiPtRoutePreparation.TaxiSnapshot sourceTaxiSnapshot) {
		this.config = config;
		this.preparationAudit = preparationAudit;
		this.sourceTaxiSnapshot = sourceTaxiSnapshot;
		this.customRebuildInvocationsAtConstruction =
				HongKongTaxiPtRoutePreparation.customStartupRebuildInvocationCount();
	}

	@Override
	public void notifyStartup(StartupEvent event) {
		ScoringFunctionFactory factory = event.getServices().getScoringFunctionFactory();
		HongKongTaxiScoringParameters parameters = event.getServices().getInjector()
				.getInstance(HongKongTaxiScoringParameters.class);
		PrepareForSim prepareForSim = event.getServices().getInjector()
				.getInstance(PrepareForSim.class);
		String factoryClass = factory.getClass().getName();
		String prepareForSimClass = prepareForSim.getClass().getName();

		List<String> fleetBindings = event.getServices().getInjector().getAllBindings().keySet().stream()
				.map(key -> key.getTypeLiteral().getRawType().getName())
				.filter(HongKongTaxiSmokeRuntimeGuard::isFleetBinding)
				.distinct()
				.sorted()
				.toList();

		Map<String, Boolean> checks = new LinkedHashMap<>();
		checks.put("custom_scoring_factory_bound", EXPECTED_FACTORY.equals(factoryClass));
		checks.put("central_fare_utility_exact",
				parameters.fareUtilityPerHkd()
						== HongKongTaxiScoringParameters.CENTRAL_FARE_UTILITY_PER_HKD);
		checks.put("fare_share_factor_exact",
				parameters.fareShareFactor()
						== HongKongTaxiScoringParameters.CENTRAL_FARE_SHARE_FACTOR);
		checks.put("taxi_scoring_config_guard_passed", taxiConfigIsSafe(config, parameters));
		checks.put("iteration_range_is_0_to_1",
				config.controller().getFirstIteration() == 0
						&& config.controller().getLastIteration() == 1);
		checks.put("replanning_strategies_empty",
				config.replanning().getStrategySettings().isEmpty());
		checks.put("taxi_not_qsim_main_mode",
				!config.qsim().getMainModes().contains(HongKongTaxiScoringParameters.TAXI_MODE));
		checks.put("no_dvrp_or_taxi_fleet_bindings", fleetBindings.isEmpty());
		checks.put("default_prepare_for_sim_impl_bound",
				prepareForSim instanceof PrepareForSimImpl);
		checks.put("custom_pt_rebuild_not_invoked_before_default_prepare",
				HongKongTaxiPtRoutePreparation.customStartupRebuildInvocationCount()
						== customRebuildInvocationsAtConstruction);

		startupAudit = ordered(
				"scoring_module_installed", EXPECTED_FACTORY.equals(factoryClass),
				"actual_scoring_function_factory_class", factoryClass,
				"prepare_for_sim_class", prepareForSimClass,
				"default_prepare_for_sim_impl_bound",
						prepareForSim instanceof PrepareForSimImpl,
				"custom_rebuild_invocations_at_guard_construction",
						customRebuildInvocationsAtConstruction,
				"custom_rebuild_invocations_at_startup",
						HongKongTaxiPtRoutePreparation
								.customStartupRebuildInvocationCount(),
				"fare_utility_per_hkd", parameters.fareUtilityPerHkd(),
				"fare_share_factor", parameters.fareShareFactor(),
				"global_marginal_utility_of_money",
						config.scoring().getMarginalUtilityOfMoney(),
				"taxi_distance_scoring", ordered(
						"marginal_utility_of_distance",
						config.scoring().getModes().get("taxi").getMarginalUtilityOfDistance(),
						"monetary_distance_rate",
						config.scoring().getModes().get("taxi").getMonetaryDistanceRate()
				),
				"qsim_main_modes", List.copyOf(config.qsim().getMainModes()),
				"detected_dvrp_or_taxi_fleet_bindings", fleetBindings,
				"checks", checks
		);

		List<String> failed = checks.entrySet().stream()
				.filter(entry -> !entry.getValue())
				.map(Map.Entry::getKey)
				.toList();
		if (!failed.isEmpty()) {
			throw new IllegalStateException("Taxi smoke startup guard failed: " + failed);
		}
		event.getServices().getEvents().addHandler(this);
	}

	@Override
	public void notifyBeforeMobsim(BeforeMobsimEvent event) {
		int iteration = event.getIteration();
		if (iteration < 0 || iteration > 1) {
			throw new IllegalStateException("Forbidden smoke iteration: " + iteration);
		}
		if (preparedPtByIteration.containsKey(iteration)) {
			throw new IllegalStateException(
					"Duplicate BeforeMobsim PT preparation audit: " + iteration);
		}
		HongKongTaxiPtRoutePreparation.PtRuntimeAudit ptAudit =
				HongKongTaxiPtRoutePreparation.auditPreparedSelectedPt(
						event.getServices().getScenario());
		preparedPtByIteration.put(iteration, ptAudit);
		long currentCustomRebuildInvocations =
				HongKongTaxiPtRoutePreparation.customStartupRebuildInvocationCount();
		if (currentCustomRebuildInvocations != customRebuildInvocationsAtConstruction) {
			throw new IllegalStateException(
					"Custom PT rebuild was invoked on the standard PrepareForSim path: before="
							+ customRebuildInvocationsAtConstruction + ", after="
							+ currentCustomRebuildInvocations);
		}
		HongKongTaxiPtRoutePreparation.TaxiSnapshot currentTaxiSnapshot =
				HongKongTaxiPtRoutePreparation.captureSelectedTaxi(
						event.getServices().getScenario().getPopulation());
		HongKongTaxiPtRoutePreparation.TaxiInvarianceAudit taxiAudit;
		if (iteration == 0) {
			taxiAudit = HongKongTaxiPtRoutePreparation.compareTaxi(
					sourceTaxiSnapshot, currentTaxiSnapshot);
			HongKongTaxiPtRoutePreparation
					.requireFormalTaxiIdentityAllowRouteChanges(taxiAudit);
			preparedTaxiSnapshot = currentTaxiSnapshot;
		} else {
			if (preparedTaxiSnapshot == null) {
				throw new IllegalStateException(
						"Iteration 1 reached BeforeMobsim before prepared Taxi snapshot");
			}
			taxiAudit = HongKongTaxiPtRoutePreparation.compareTaxi(
					preparedTaxiSnapshot, currentTaxiSnapshot);
			HongKongTaxiPtRoutePreparation.requireFormalTaxiInvariant(taxiAudit);
		}
		taxiInvarianceByIteration.put(iteration, taxiAudit);
		HongKongTaxiPtRoutePreparation.requireFormalPrepared(ptAudit);
		if (iteration == 1) {
			HongKongTaxiPtRoutePreparation.PtRuntimeAudit first =
					preparedPtByIteration.get(0);
			if (first == null) {
				throw new IllegalStateException(
						"Iteration 1 reached BeforeMobsim before iteration 0");
			}
		}

		current = new IterationEvents(iteration);
		current.startedNanos = System.nanoTime();
		current.executedPlans = event.getServices().getScenario()
				.getPopulation().getPersons().size();
		iterations.put(iteration, current);
	}

	@Override
	public void handleEvent(Event event) {
		if (current == null) {
			return;
		}
		if (event instanceof PersonDepartureEvent departure) {
			current.handleDeparture(departure);
		} else if (event instanceof PersonArrivalEvent arrival) {
			current.handleArrival(arrival);
		} else if (event instanceof PersonStuckEvent stuck) {
			current.handleStuck(stuck);
		} else if (event instanceof VehicleEntersTrafficEvent entersTraffic) {
			if ("taxi".equals(entersTraffic.getNetworkMode())) {
				current.taxiNetworkVehicleTrafficEvents++;
			}
		} else if (event instanceof PersonMoneyEvent money) {
			current.handleMoney(money);
		}

		if (dangerousEventTypes.computeIfAbsent(
				event.getEventType(),
				HongKongTaxiSmokeRuntimeGuard::isDvrpOrFleetEventType)) {
			current.dvrpTaxiFleetEvents++;
			current.dvrpTaxiFleetEventTypes.merge(event.getEventType(), 1L, Long::sum);
		}
	}

	@Override
	public void notifyAfterMobsim(AfterMobsimEvent event) {
		if (current == null || current.iteration != event.getIteration()) {
			afterMobsimWithoutLiveAudit++;
			return;
		}
		current.finish();
		current = null;
	}

	public Map<String, Object> startupAudit() {
		return startupAudit;
	}

	public Map<String, Object> iterationAudits() {
		Map<String, Object> result = new LinkedHashMap<>();
		iterations.forEach((iteration, audit) ->
				result.put(Integer.toString(iteration), audit.toMap()));
		return result;
	}

	public Map<String, Object> ptPreparationAudit() {
		Map<String, Object> prepared = new LinkedHashMap<>();
		preparedPtByIteration.forEach((iteration, audit) ->
				prepared.put(Integer.toString(iteration), audit.toMap()));
		Map<String, Object> taxi = new LinkedHashMap<>();
		taxiInvarianceByIteration.forEach((iteration, audit) ->
				taxi.put(Integer.toString(iteration), audit.toMap()));
		boolean samePtFingerprint = preparedPtByIteration.size() == 2
				&& preparedPtByIteration.get(0).fingerprintSha256()
				.equals(preparedPtByIteration.get(1).fingerprintSha256());
		return ordered(
				"source_clear_audit", preparationAudit.toMap(),
				"prepare_for_sim",
						"default_parallel_PrepareForSimImpl",
				"custom_startup_rebuild_invocations_before",
						customRebuildInvocationsAtConstruction,
				"custom_startup_rebuild_invocations_after",
						HongKongTaxiPtRoutePreparation
								.customStartupRebuildInvocationCount(),
				"prepared_pt_by_iteration", prepared,
				"taxi_invariance_by_iteration", taxi,
				"before_mobsim_audit_count", preparedPtByIteration.size(),
				"after_mobsim_without_live_audit",
						afterMobsimWithoutLiveAudit,
				"pt_route_fingerprint_unchanged_after_iteration_0",
						samePtFingerprint
		);
	}

	public boolean preparedPtAndTaxiGuardsPassed() {
		return preparedPtByIteration.size() == 2
				&& taxiInvarianceByIteration.size() == 2
				&& HongKongTaxiPtRoutePreparation
						.customStartupRebuildInvocationCount()
						== customRebuildInvocationsAtConstruction
				&& preparedPtByIteration.values().stream().allMatch(audit ->
						audit.totalPtLegs() > 0
								&& audit.routeNull() == 0
								&& audit.genericRouteImpl() == 0
								&& audit.transitPassengerRoute()
								== audit.totalPtLegs()
								&& audit.accessStopMissing() == 0
								&& audit.egressStopMissing() == 0
								&& audit.lineIdMissing() == 0
								&& audit.transitRouteIdMissing() == 0
								&& audit.accessStopNotInSchedule() == 0
								&& audit.egressStopNotInSchedule() == 0
								&& audit.lineNotInSchedule() == 0
								&& audit.routeNotInSchedule() == 0)
				&& taxiInvarianceByIteration.values().stream()
						.skip(1)
						.allMatch(HongKongTaxiPtRoutePreparation
								.TaxiInvarianceAudit::exact)
				&& taxiInvarianceByIteration.get(0)
						.identityExactAllowRouteChanges();
	}

	public int beforeMobsimAuditCount() {
		return preparedPtByIteration.size();
	}

	public boolean startupPtRebuildCompleted() {
		return HongKongTaxiPtRoutePreparation.customStartupRebuildInvocationCount()
				> customRebuildInvocationsAtConstruction;
	}

	static void requireStablePreparedPt(
			HongKongTaxiPtRoutePreparation.PtRuntimeAudit iteration0,
			HongKongTaxiPtRoutePreparation.PtRuntimeAudit laterIteration) {
		if (!iteration0.fingerprintSha256()
				.equals(laterIteration.fingerprintSha256())) {
			throw new IllegalStateException(
					"PT routes changed after the one-shot iteration-0 startup "
							+ "rebuild: iteration0="
							+ iteration0.fingerprintSha256()
							+ ", later_iteration="
							+ laterIteration.fingerprintSha256());
		}
	}

	public boolean completedExactlyTwoIterations() {
		return iterations.size() == 2
				&& iterations.containsKey(0)
				&& iterations.containsKey(1)
				&& iterations.values().stream().allMatch(audit -> audit.finished);
	}

	public boolean allIterationTaxiChecksPassed() {
		return completedExactlyTwoIterations()
				&& iterations.values().stream().allMatch(audit -> audit.passed);
	}

	public Map<String, Object> fareScheduleAudit(
			HongKongTaxiSmokeOutputAudit.RuntimeLogAudit runtimeLogAudit) {
		Map<String, Object> byIteration = new LinkedHashMap<>();
		boolean exact = iterations.size() == 2 && runtimeLogAudit.exact();
		for (Map.Entry<Integer, IterationEvents> entry : iterations.entrySet()) {
			IterationEvents events = entry.getValue();
			boolean iterationExact =
					events.taxiDepartures == EXPECTED_TAXI_LEGS
							&& events.taxiArrivals == EXPECTED_TAXI_LEGS
							&& events.unmatchedTaxiDepartures == 0
							&& events.unmatchedTaxiArrivals == 0
							&& events.passed;
			exact &= iterationExact;
			long consumed = events.taxiDepartures;
			byIteration.put(Integer.toString(entry.getKey()), ordered(
					"scheduled_taxi_legs", EXPECTED_TAXI_LEGS,
					"experienced_taxi_departures", events.taxiDepartures,
					"experienced_taxi_arrivals", events.taxiArrivals,
					"consumed_taxi_fare_entries", consumed,
					"unconsumed_fare_schedule_entries",
							Math.max(0L, EXPECTED_TAXI_LEGS - consumed),
					"extra_experienced_taxi_legs",
							Math.max(0L, consumed - EXPECTED_TAXI_LEGS),
					"exact", iterationExact
			));
		}
		return ordered(
				"by_iteration", byIteration,
				"completion_enforces_exact_consumption", true,
				"runtime_fare_schedule_mismatch_lines",
						runtimeLogAudit.taxiFareScheduleMismatch(),
				"exact", exact
		);
	}

	private static boolean taxiConfigIsSafe(
			Config config,
			HongKongTaxiScoringParameters parameters) {
		try {
			parameters.validateConfig(config);
			return true;
		} catch (RuntimeException error) {
			return false;
		}
	}

	private static boolean isFleetBinding(String className) {
		return className.startsWith("org.matsim.contrib.dvrp.")
				|| className.startsWith("org.matsim.contrib.taxi.");
	}

	private static boolean isDvrpOrFleetEventType(String eventType) {
		String lower = eventType.toLowerCase(Locale.ROOT);
		return lower.contains("dvrp")
				|| lower.contains("passengerrequest")
				|| lower.contains("requestsubmitted")
				|| lower.contains("requestscheduled")
				|| lower.contains("pickedup")
				|| lower.contains("droppedoff")
				|| lower.contains("taxipickup")
				|| lower.contains("taxidropoff")
				|| lower.contains("fleet");
	}

	private static Map<String, Object> ordered(Object... entries) {
		Map<String, Object> result = new LinkedHashMap<>();
		for (int index = 0; index < entries.length; index += 2) {
			result.put((String) entries[index], entries[index + 1]);
		}
		return result;
	}

	static final class IterationEvents {
		final int iteration;
		long startedNanos;
		long executedPlans;
		long taxiDepartures;
		long taxiArrivals;
		long unmatchedTaxiArrivals;
		long unmatchedTaxiDepartures;
		long invalidTaxiTravelTimes;
		long totalStuckEvents;
		long taxiStuckEvents;
		long taxiNetworkVehicleTrafficEvents;
		long dvrpTaxiFleetEvents;
		long taxiFareMoneyEvents;
		long totalPersonMoneyEvents;
		double taxiTravelTimeSumSeconds;
		double wallTimeSeconds;
		boolean finished;
		boolean passed;
		final Map<String, Deque<Double>> openTaxiDepartures = new TreeMap<>();
		final Map<String, Long> stuckByMode = new TreeMap<>();
		final Map<String, Long> stuckByHour = new TreeMap<>();
		final List<Map<String, Object>> stuckExamples = new ArrayList<>();
		final Map<String, Long> dvrpTaxiFleetEventTypes = new TreeMap<>();
		final List<String> violations = new ArrayList<>();
		final List<String> observations = new ArrayList<>();

		IterationEvents(int iteration) {
			this.iteration = iteration;
		}

		void handleDeparture(PersonDepartureEvent event) {
			if (!"taxi".equals(event.getLegMode())) {
				return;
			}
			taxiDepartures++;
			openTaxiDepartures.computeIfAbsent(
					event.getPersonId().toString(),
					ignored -> new ArrayDeque<>()
			).addLast(event.getTime());
		}

		void handleArrival(PersonArrivalEvent event) {
			if (!"taxi".equals(event.getLegMode())) {
				return;
			}
			taxiArrivals++;
			Deque<Double> departures = openTaxiDepartures.get(event.getPersonId().toString());
			if (departures == null || departures.isEmpty()) {
				unmatchedTaxiArrivals++;
				return;
			}
			double travelTime = event.getTime() - departures.removeFirst();
			if (!Double.isFinite(travelTime) || travelTime < 0.0) {
				invalidTaxiTravelTimes++;
			} else {
				taxiTravelTimeSumSeconds += travelTime;
			}
		}

		void handleStuck(PersonStuckEvent event) {
			totalStuckEvents++;
			String mode = event.getLegMode() == null ? "<null>" : event.getLegMode();
			stuckByMode.merge(mode, 1L, Long::sum);
			stuckByHour.merge(Integer.toString((int) Math.floor(event.getTime() / 3600.0)),
					1L, Long::sum);
			if ("taxi".equals(mode)) {
				taxiStuckEvents++;
			}
			if (stuckExamples.size() < 20) {
				stuckExamples.add(ordered(
						"person_id", event.getPersonId().toString(),
						"time", event.getTime(),
						"mode", mode,
						"reason", event.getReason()
				));
			}
		}

		void handleMoney(PersonMoneyEvent event) {
			totalPersonMoneyEvents++;
			String text = String.join(" ",
					String.valueOf(event.getPurpose()),
					String.valueOf(event.getTransactionPartner()),
					String.valueOf(event.getReference())).toLowerCase(Locale.ROOT);
			Deque<Double> openTaxiLegs =
					openTaxiDepartures.get(event.getPersonId().toString());
			if (text.contains("taxi")
					|| (openTaxiLegs != null && !openTaxiLegs.isEmpty())) {
				taxiFareMoneyEvents++;
			}
		}

		void finish() {
			unmatchedTaxiDepartures = openTaxiDepartures.values().stream()
					.mapToLong(Deque::size)
					.sum();
			wallTimeSeconds = (System.nanoTime() - startedNanos) / 1_000_000_000.0;
			List<String> failures = new ArrayList<>();
			require(failures, taxiDepartures == EXPECTED_TAXI_LEGS,
					"taxi_departures_exact");
			require(failures, taxiArrivals == EXPECTED_TAXI_LEGS,
					"taxi_arrivals_exact");
			require(failures, unmatchedTaxiDepartures == 0,
					"no_unmatched_taxi_departures");
			require(failures, unmatchedTaxiArrivals == 0,
					"no_unmatched_taxi_arrivals");
			require(failures, invalidTaxiTravelTimes == 0,
					"all_taxi_travel_times_finite_nonnegative");
			require(failures, taxiStuckEvents == 0, "no_taxi_stuck");
			require(failures, taxiNetworkVehicleTrafficEvents == 0,
					"taxi_not_network_vehicle_mode");
			require(failures, dvrpTaxiFleetEvents == 0,
					"no_dvrp_taxi_fleet_events");
			require(failures, taxiFareMoneyEvents == 0,
					"no_taxi_fare_money_events");
			violations.addAll(failures);
			if (totalStuckEvents > taxiStuckEvents) {
				observations.add("non_taxi_stuck_observed");
			}
			finished = true;
			passed = failures.isEmpty();
		}

		Map<String, Object> toMap() {
			return ordered(
					"iteration", iteration,
					"finished", finished,
					"passed", passed,
					"violations", violations,
					"observations", observations,
					"executed_plans", executedPlans,
					"taxi_departures", taxiDepartures,
					"taxi_arrivals", taxiArrivals,
					"unmatched_taxi_departures", unmatchedTaxiDepartures,
					"unmatched_taxi_arrivals", unmatchedTaxiArrivals,
					"invalid_taxi_travel_times", invalidTaxiTravelTimes,
					"mean_taxi_travel_time_seconds",
							taxiArrivals == 0 ? 0.0 : taxiTravelTimeSumSeconds / taxiArrivals,
					"taxi_stuck_events", taxiStuckEvents,
					"total_stuck_events", totalStuckEvents,
					"stuck_by_mode", stuckByMode,
					"stuck_by_hour", stuckByHour,
					"stuck_examples", stuckExamples,
					"taxi_network_vehicle_traffic_events",
							taxiNetworkVehicleTrafficEvents,
					"dvrp_taxi_request_pickup_dropoff_fleet_events",
							dvrpTaxiFleetEvents,
					"dvrp_taxi_fleet_event_types", dvrpTaxiFleetEventTypes,
					"taxi_fare_person_money_events", taxiFareMoneyEvents,
					"total_person_money_events", totalPersonMoneyEvents,
					"qsim_wall_time_seconds", wallTimeSeconds
			);
		}

		private static void require(List<String> failures, boolean condition, String name) {
			if (!condition) {
				failures.add(name);
			}
		}
	}
}
