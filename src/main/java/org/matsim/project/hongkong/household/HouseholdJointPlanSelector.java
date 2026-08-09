package org.matsim.project.hongkong.household;

import ch.sbb.matsim.routing.pt.raptor.SwissRailRaptor;
import ch.sbb.matsim.routing.pt.raptor.RaptorRoute;
import com.google.inject.Inject;
import com.google.inject.Provider;
import com.google.inject.name.Named;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.core.config.Config;
import org.matsim.core.config.groups.ScoringConfigGroup;
import org.matsim.core.controler.events.ReplanningEvent;
import org.matsim.core.controler.listener.ReplanningListener;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.population.routes.NetworkRoute;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.router.DefaultRoutingRequest;
import org.matsim.core.router.TripRouter;
import org.matsim.core.router.TripStructureUtils;
import org.matsim.core.router.util.TravelTime;
import org.matsim.facilities.ActivityFacilities;
import org.matsim.facilities.FacilitiesUtils;
import org.matsim.pt.routes.TransitPassengerRoute;
import org.matsim.pt.routes.DefaultTransitPassengerRoute;
import org.matsim.pt.transitSchedule.api.Departure;
import org.matsim.pt.transitSchedule.api.TransitLine;
import org.matsim.pt.transitSchedule.api.TransitRoute;
import org.matsim.pt.transitSchedule.api.TransitRouteStop;
import org.matsim.pt.transitSchedule.api.TransitStopFacility;
import org.matsim.project.hongkong.car.HongKongDynamicCarCostRules;
import org.matsim.project.hongkong.pt.HongKongPtFareRuntimeCatalog;
import org.matsim.project.hongkong.schoolbus.StudentSchoolModeCandidateCatalog;
import org.matsim.project.hongkong.taxi.HongKongTaxiFareCalculator;
import org.matsim.project.hongkong.taxi.HongKongTaxiLegAttributes;
import org.matsim.project.hongkong.taxi.HongKongTaxiScoringParameters;
import org.matsim.utils.objectattributes.attributable.Attributes;
import org.matsim.utils.objectattributes.attributable.AttributesImpl;
import org.matsim.vehicles.Vehicle;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.IdentityHashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * One-shot household-level maximum-utility selector applied after MATSim's
 * ordinary replanning callback for iteration 1. Baseline plans therefore run
 * unchanged in iteration 0, while the selected household composites cannot be
 * replaced again before iteration 1. The selector may
 * bind screened household pairs physically, and it releases every original
 * {@code car_passenger} trip to its best routed PT, Taxi, or Walk alternative
 * when that trip is not selected for a real household vehicle binding.
 */
public final class HouseholdJointPlanSelector implements ReplanningListener {

	private static final Logger LOG = LogManager.getLogger(HouseholdJointPlanSelector.class);
	private static final double DRIVER_CONSTANT = -0.5;
	private static final double PASSENGER_CONSTANT = -1.5;
	private static final double TRAVEL_UTILITY_PER_HOUR = -6.0;
	private static final double SCHOOL_BUS_BOARDING_READY_MARGIN_S = 5.0;
	private static final String RELEASED_MODE_ATTRIBUTE = "hkHouseholdEscortReleasedPassengerMode";
	private static final String RELEASED_TRIP_INDEX_ATTRIBUTE = "hkHouseholdEscortOriginalPassengerLegIndex";

	record PersonTripKey(Id<Person> personId, int tripIndex) {
	}

	private record MainTrip(Activity origin, Activity destination, List<PlanElement> elements) {
		MainTrip {
			elements = List.copyOf(elements);
		}
	}

	private record PassengerModeCandidate(
			String mode, List<PlanElement> elements, double utility,
			double travelTimeS, double fareHkd, boolean available,
			double originEndTimeS, String sourceCandidateId) {
		PassengerModeCandidate {
			elements = List.copyOf(elements);
		}
	}

	private record CarMetric(
			NetworkRoute route, double travelTimeS, double arrivalTimeS,
			double energyHkd, double tollHkd, double parkingHkd) {
		double utility() {
			return DRIVER_CONSTANT + TRAVEL_UTILITY_PER_HOUR * travelTimeS / 3_600.0
					- energyHkd - tollHkd - parkingHkd;
		}
	}

	private record WaypointRoute(CarMetric car, double passengerArrivalTimeS) {
	}

	private record CandidateEvaluation(
			HouseholdJointPlanCandidateCatalog.Candidate candidate,
			CarMetric waypointCar,
			Map<Integer, CarMetric> switchedDayCar,
			double passengerDepartureTimeS,
			double passengerJointTravelTimeS,
			double delta,
			boolean scheduleFeasible) {
		CandidateEvaluation {
			switchedDayCar = Map.copyOf(switchedDayCar);
		}
	}

	private static final class BestSelection {
		double utilityGain = Double.NEGATIVE_INFINITY;
		List<CandidateEvaluation> candidates = List.of();
	}

	private final HouseholdJointPlanCandidateCatalog candidates;
	private final HouseholdEscortBindingCatalog bindings;
	private final HouseholdJointPlanAlternativeGenerator alternativeGenerator;
	private final StudentSchoolModeCandidateCatalog studentCandidates;
	private final Scenario scenario;
	private final ActivityFacilities facilities;
	private final Provider<TripRouter> tripRouterProvider;
	private final SwissRailRaptor ptRouter;
	private final TravelTime carTravelTime;
	private final HongKongDynamicCarCostRules costRules;
	private final HongKongPtFareRuntimeCatalog ptFareCatalog;
	private final HongKongTaxiFareCalculator taxiFareCalculator;
	private final HongKongTaxiScoringParameters taxiParameters;
	private final Config config;
	private final double qsimEndTimeS;
	private boolean applied;

	@Inject
	public HouseholdJointPlanSelector(
			HouseholdJointPlanCandidateCatalog candidates,
			HouseholdEscortBindingCatalog bindings,
			HouseholdJointPlanAlternativeGenerator alternativeGenerator,
			StudentSchoolModeCandidateCatalog studentCandidates,
			Scenario scenario,
			ActivityFacilities facilities,
			Provider<TripRouter> tripRouterProvider,
			SwissRailRaptor ptRouter,
			@Named(TransportMode.car) TravelTime carTravelTime,
			HongKongDynamicCarCostRules costRules,
			HongKongPtFareRuntimeCatalog ptFareCatalog,
			HongKongTaxiFareCalculator taxiFareCalculator,
			Config config) {
		this.candidates = candidates;
		this.bindings = bindings;
		this.alternativeGenerator = alternativeGenerator;
		this.studentCandidates = studentCandidates;
		this.scenario = scenario;
		this.facilities = facilities;
		this.tripRouterProvider = tripRouterProvider;
		this.ptRouter = ptRouter;
		this.carTravelTime = carTravelTime;
		this.costRules = costRules;
		this.ptFareCatalog = ptFareCatalog;
		this.taxiFareCalculator = taxiFareCalculator;
		this.taxiParameters = HongKongTaxiScoringParameters.centralV1();
		this.config = config;
		this.qsimEndTimeS = config.qsim().getEndTime().orElse(30.0 * 3_600.0);
	}

	@Override
	public void notifyReplanning(ReplanningEvent event) {
		if (event.getIteration() != 1 || applied) return;
		alternativeGenerator.generate();
		TripRouter router = tripRouterProvider.get();
		Map<PersonTripKey, PassengerModeCandidate> releases = buildIndependentChoices(router);
		Map<PersonTripKey, Double> originalPassengerUtilities = new HashMap<>();
		List<CandidateEvaluation> evaluations = new ArrayList<>();
		int infeasible = 0;
		int switchCandidates = 0;
		for (HouseholdJointPlanCandidateCatalog.Candidate candidate : candidates.candidates()) {
			CandidateEvaluation evaluation = evaluateCandidate(
					router, candidate, releases, originalPassengerUtilities);
			evaluations.add(evaluation);
			if (!evaluation.scheduleFeasible()) infeasible++;
			if (candidate.driverRequiresCarSwitch()) switchCandidates++;
			LOG.info("HK_HOUSEHOLD_JOINT_CANDIDATE candidate={} household={} passenger={} "
					+ "passenger_trip={} passenger_original_mode={} driver={} driver_trip={} "
					+ "driver_original_mode={} driver_switch={} schedule_feasible={} "
					+ "joint_minus_fallback_utility={} passenger_joint_time_s={}",
					candidate.candidateId(), candidate.householdId(), candidate.passengerPersonId(),
					candidate.passengerTripIndex(), candidate.passengerOriginalMode(),
					candidate.driverPersonId(), candidate.driverTripIndex(),
					candidate.driverOriginalMode(), candidate.driverRequiresCarSwitch(),
					evaluation.scheduleFeasible(), evaluation.delta(),
					evaluation.passengerJointTravelTimeS());
		}

		Map<String, List<CandidateEvaluation>> byHousehold = new LinkedHashMap<>();
		for (CandidateEvaluation evaluation : evaluations) {
			byHousehold.computeIfAbsent(evaluation.candidate().householdId(), ignored -> new ArrayList<>())
					.add(evaluation);
		}
		List<CandidateEvaluation> selected = new ArrayList<>();
		for (List<CandidateEvaluation> household : byHousehold.values()) {
			selected.addAll(selectHousehold(household));
		}
		selected.sort(Comparator.comparing(evaluation -> evaluation.candidate().candidateId()));
		Set<String> selectedIds = selected.stream()
				.map(value -> value.candidate().candidateId()).collect(java.util.stream.Collectors.toSet());
		for (CandidateEvaluation evaluation : evaluations) {
			LOG.info("HK_HOUSEHOLD_JOINT_SELECTION candidate={} household={} passenger={} "
					+ "passenger_trip={} driver={} driver_trip={} choice={} utility_delta={} "
					+ "schedule_feasible={}",
					evaluation.candidate().candidateId(), evaluation.candidate().householdId(),
					evaluation.candidate().passengerPersonId(),
					evaluation.candidate().passengerTripIndex(),
					evaluation.candidate().driverPersonId(),
					evaluation.candidate().driverTripIndex(),
					selectedIds.contains(evaluation.candidate().candidateId()) ? "joint" : "fallback",
					evaluation.delta(), evaluation.scheduleFeasible());
		}

		Installation installation = installSelections(releases, selected);
		studentCandidates.snapshotSelectedSchoolBusPlans(scenario);
		int repairedSelectedTaxiTrips = repairSelectedTaxiRoutes(router);
		bindings.replaceWithActiveBindings(installation.bindings());
		applied = true;

		long releasedPt = releases.values().stream()
				.filter(value -> TransportMode.pt.equals(value.mode())).count();
		long releasedTaxi = releases.values().stream()
				.filter(value -> HongKongJointPlanModes.TAXI.equals(value.mode())).count();
		long releasedWalk = releases.values().stream()
				.filter(value -> TransportMode.walk.equals(value.mode())).count();
		long selectedSchoolBus = releases.values().stream()
				.filter(value -> "school_bus".equals(value.mode())).count();
		long selectedSwitch = selected.stream()
				.filter(value -> value.candidate().driverRequiresCarSwitch()).count();
		long selectedExistingCar = selected.size() - selectedSwitch;
		LOG.info("Household joint-plan selector: source_iteration=0, candidate_pairs={}, "
				+ "candidate_households={}, driver_switch_candidates={}, infeasible_candidates={}, "
				+ "selected_joint_pairs={}, selected_existing_car_pairs={}, selected_driver_switch_pairs={}, "
				+ "active_physical_bindings={}, original_car_passenger_trips={}, "
				+ "fallback_best_pt={}, fallback_best_taxi={}, fallback_best_walk={}, "
				+ "independent_best_school_bus={}, "
				+ "selected_plans_added={}, repaired_selected_taxi_trips={}, "
				+ "initial_selected_plans_preserved_through_iteration_0=true, "
				+ "school_bus_candidates={}, school_bus_capacity_constraint=false, "
				+ "probability_choice=false, driver_constraint=false",
				 evaluations.size(), byHousehold.size(), switchCandidates, infeasible,
				 selected.size(), selectedExistingCar, selectedSwitch, bindings.activeBindingCount(),
				 releases.size(), releasedPt, releasedTaxi, releasedWalk, selectedSchoolBus,
				 installation.selectedPlansAdded(), repairedSelectedTaxiTrips,
				 studentCandidates.physicalSchoolBusOptionCount());
	}

	private int repairSelectedTaxiRoutes(TripRouter router) {
		int repaired = 0;
		for (Person person : scenario.getPopulation().getPersons().values()) {
			Plan plan = requiredSelectedPlan(person);
			List<TripStructureUtils.Trip> trips = List.copyOf(TripStructureUtils.getTrips(plan));
			for (int tripIndex = trips.size() - 1; tripIndex >= 0; tripIndex--) {
				MainTrip trip = mainTrip(plan, tripIndex);
				List<Leg> taxiLegs = trip.elements().stream()
						.filter(Leg.class::isInstance).map(Leg.class::cast)
						.filter(leg -> HongKongJointPlanModes.TAXI.equals(leg.getMode())).toList();
				if (taxiLegs.isEmpty() || taxiLegs.stream().allMatch(HouseholdJointPlanSelector::hasLegalTaxiRoute)) {
					continue;
				}
				PassengerModeCandidate routed = buildTaxiCandidate(
						router, person, trip, tripIndex, tripDeparture(trip));
				replaceMainTrip(plan, tripIndex, routed.elements());
				copyTaxiAttributesToOrigin(plan, tripIndex, routed);
				repaired++;
				LOG.info("HK_HOUSEHOLD_SELECTED_TAXI_ROUTE_REPAIR person={} trip={} plan_role={}",
						person.getId(), tripIndex, plan.getAttributes().getAttribute(
								HouseholdJointPlanAlternativeGenerator.ROLE_ATTRIBUTE));
			}
		}
		return repaired;
	}

	private static boolean hasLegalTaxiRoute(Leg leg) {
		return HongKongJointPlanModes.TAXI.equals(leg.getRoutingMode())
				&& leg.getRoute() != null
				&& Double.isFinite(leg.getRoute().getDistance())
				&& leg.getRoute().getDistance() >= 0.0
				&& leg.getRoute().getTravelTime().isDefined()
				&& leg.getTravelTime().isDefined();
	}

	private Map<PersonTripKey, PassengerModeCandidate> buildIndependentChoices(TripRouter router) {
		Map<PersonTripKey, PassengerModeCandidate> result = new LinkedHashMap<>();
		for (Person person : scenario.getPopulation().getPersons().values()) {
			Plan plan = requiredSelectedPlan(person);
			List<TripStructureUtils.Trip> trips = List.copyOf(TripStructureUtils.getTrips(plan));
			for (int tripIndex = 0; tripIndex < trips.size(); tripIndex++) {
				int currentTripIndex = tripIndex;
				MainTrip trip = mainTrip(plan, tripIndex);
				if (!"car_passenger".equals(mainMode(trip))) continue;
				double departure = tripDeparture(trip);
				PassengerModeCandidate pt = buildPtCandidate(person, trip, tripIndex, departure);
				PassengerModeCandidate taxi = buildTaxiCandidate(router, person, trip, tripIndex, departure);
				PassengerModeCandidate walk = buildWalkCandidate(router, person, trip, tripIndex, departure);
				PassengerModeCandidate best = List.of(pt, taxi, walk).stream()
						.filter(PassengerModeCandidate::available)
						.max(Comparator.comparingDouble(PassengerModeCandidate::utility)
								.thenComparingInt(value -> releaseTiePriority(value.mode())))
						.orElseThrow(() -> new IllegalStateException(
								"No real release mode for " + person.getId() + "/" + currentTripIndex));
				result.put(new PersonTripKey(person.getId(), tripIndex), best);
				LOG.info("HK_CAR_PASSENGER_RELEASE_CANDIDATE passenger={} trip={} "
						+ "pt_available={} pt_utility={} taxi_utility={} walk_utility={} selected_mode={}",
						person.getId(), tripIndex, pt.available(), pt.utility(), taxi.utility(),
						walk.utility(), best.mode());
			}
		}
		if (!studentCandidates.enabled()) return result;

		for (StudentSchoolModeCandidateCatalog.TripCandidate candidate : studentCandidates.trips().values()) {
			Person person = requiredPerson(candidate.key().personId());
			Plan plan = requiredSelectedPlan(person);
			MainTrip trip = mainTrip(plan, candidate.key().tripIndex());
			double departure = tripDeparture(trip);
			PassengerModeCandidate pt = buildPtCandidate(person, trip, candidate.key().tripIndex(), departure);
			PassengerModeCandidate taxi = buildTaxiCandidate(
					router, person, trip, candidate.key().tripIndex(), departure);
			PassengerModeCandidate walk = candidate.walkAvailable()
					? buildWalkCandidate(router, person, trip, candidate.key().tripIndex(), departure)
					: unavailable(TransportMode.walk, "walk_distance_ineligible");
			List<PassengerModeCandidate> choices = new ArrayList<>(List.of(pt, taxi, walk));
			for (StudentSchoolModeCandidateCatalog.SchoolBusOption option : candidate.schoolBusOptions()) {
				choices.add(buildSchoolBusCandidate(
						router, person, trip, candidate.key().tripIndex(), option));
			}
			PassengerModeCandidate best = choices.stream()
					.filter(PassengerModeCandidate::available)
					.max(Comparator.comparingDouble(PassengerModeCandidate::utility)
							.thenComparingInt(value -> releaseTiePriority(value.mode()))
							.thenComparing(PassengerModeCandidate::sourceCandidateId,
									Comparator.reverseOrder()))
					.orElseThrow(() -> new IllegalStateException(
							"No independent student mode for " + candidate.key()));
			PersonTripKey key = new PersonTripKey(person.getId(), candidate.key().tripIndex());
			result.put(key, best);
			String schoolBusUtilities = choices.stream().filter(value -> "school_bus".equals(value.mode()))
					.map(value -> value.sourceCandidateId() + ":" + value.utility())
					.collect(java.util.stream.Collectors.joining("|"));
			LOG.info("HK_STUDENT_SCHOOL_MODE_SELECTION person={} trip={} direction={} stage={} "
					+ "original_mode_audit={} pt_available={} pt_utility={} taxi_utility={} "
					+ "walk_available={} walk_utility={} school_bus_options={} "
					+ "school_bus_utilities={} selected_mode={} selected_source={} selected_utility={}",
					person.getId(), candidate.key().tripIndex(), candidate.direction(),
					candidate.studentStage(), candidate.originalModeAuditOnly(), pt.available(), pt.utility(),
					taxi.utility(), walk.available(), walk.utility(), candidate.schoolBusOptions().size(),
					schoolBusUtilities, best.mode(), best.sourceCandidateId(), best.utility());
		}
		return result;
	}

	private CandidateEvaluation evaluateCandidate(
			TripRouter router,
			HouseholdJointPlanCandidateCatalog.Candidate candidate,
			Map<PersonTripKey, PassengerModeCandidate> releases,
			Map<PersonTripKey, Double> originalPassengerUtilities) {
		Person passenger = requiredPerson(candidate.passengerPersonId());
		Person driver = requiredPerson(candidate.driverPersonId());
		Plan passengerPlan = requiredSelectedPlan(passenger);
		Plan driverPlan = requiredSelectedPlan(driver);
		MainTrip passengerTrip = mainTrip(passengerPlan, candidate.passengerTripIndex());
		MainTrip driverTrip = mainTrip(driverPlan, candidate.driverTripIndex());
		if (!hasParkingZone(driverTrip.destination())
				|| (candidate.driverRequiresCarSwitch()
				&& TripStructureUtils.getTrips(driverPlan).stream()
				.map(TripStructureUtils.Trip::getDestinationActivity)
				.anyMatch(destination -> !hasParkingZone(destination)))) {
			return new CandidateEvaluation(candidate, null, Map.of(), Double.NaN, Double.NaN,
					-Double.MAX_VALUE, false);
		}
		Id<Vehicle> vehicleId = Id.createVehicleId(candidate.vehicleId());
		Vehicle vehicle = scenario.getVehicles().getVehicles().get(vehicleId);
		if (vehicle == null) throw new IllegalStateException("Missing joint candidate vehicle " + vehicleId);

		double nextDeparture = candidate.driverRequiresCarSwitch()
				? nextMainTripDeparture(driverPlan, candidate.driverTripIndex())
				: nextCarTripDeparture(driverPlan, candidate.driverTripIndex());
		WaypointRoute waypointRoute = routeWaypoint(
				router, candidate, driver, driverTrip, passengerTrip, vehicleId, nextDeparture);
		CarMetric waypoint = waypointRoute.car();
		boolean feasible = waypoint.arrivalTimeS() <= nextDeparture + 1e-9;
		// A waypoint-only NetworkRoute cannot make the driver's QVehicle wait at pickup.
		// Make the passenger ready before the bound driver leg starts, so an unexpectedly
		// early vehicle can never pass the pickup before the passenger enters QSim.  The
		// resulting wait is deliberately included in passenger generalized time/utility.
		double passengerDeparture = Math.max(0.0, Math.min(
				candidate.passengerDepartureTimeS(), candidate.driverDepartureTimeS() - 1.0));
		double passengerJointTime = waypointRoute.passengerArrivalTimeS() - passengerDeparture;
		feasible &= passengerJointTime >= 0.0;

		double fallbackPassenger;
		PersonTripKey passengerKey = new PersonTripKey(passenger.getId(), candidate.passengerTripIndex());
		PassengerModeCandidate independent = releases.get(passengerKey);
		if (independent != null) {
			fallbackPassenger = independent.utility();
		} else {
			fallbackPassenger = originalPassengerUtilities.computeIfAbsent(
					passengerKey, ignored -> originalTripUtility(passengerTrip));
		}
		double jointPassenger = passengerUtility(Math.max(0.0, passengerJointTime));

		Map<Integer, CarMetric> switchedDay = Map.of();
		double driverDelta;
		if (candidate.driverRequiresCarSwitch()) {
			Map<Integer, CarMetric> routedDay = new LinkedHashMap<>();
				double baseline = 0.0;
			double joint = 0.0;
			int tripCount = TripStructureUtils.getTrips(driverPlan).size();
			for (int tripIndex = 0; tripIndex < tripCount; tripIndex++) {
				MainTrip trip = mainTrip(driverPlan, tripIndex);
				baseline += baselineDriverTripUtility(
						driverPlan, tripIndex, trip, driver, vehicleId);
				CarMetric metric;
				if (tripIndex == candidate.driverTripIndex()) {
					metric = waypoint;
				} else {
					double departure = tripDeparture(trip);
					NetworkRoute route = routeCar(router, trip.origin(), trip.destination(),
							departure, driver, firstLeg(trip).getAttributes(), vehicleId);
					metric = evaluateCar(route, departure, driver, vehicleId, trip.destination(),
							nextMainTripDeparture(driverPlan, tripIndex));
				}
				routedDay.put(tripIndex, metric);
				joint += metric.utility();
				feasible &= metric.arrivalTimeS() <= nextMainTripDeparture(driverPlan, tripIndex) + 1e-9;
			}
			switchedDay = routedDay;
			driverDelta = joint - baseline;
		} else {
			NetworkRoute original = originalCarRoute(driverTrip, vehicleId);
			CarMetric baseline = evaluateCar(
					copyRoute(original), candidate.driverDepartureTimeS(), driver, vehicleId,
					driverTrip.destination(), nextDeparture);
			driverDelta = waypoint.utility() - baseline.utility();
		}
		return new CandidateEvaluation(
				candidate, waypoint, switchedDay, passengerDeparture, passengerJointTime,
				driverDelta + jointPassenger - fallbackPassenger, feasible);
	}

	private boolean hasParkingZone(Activity destination) {
		return destination.getFacilityId() != null
				&& costRules.hasParkingZone(destination.getFacilityId().toString());
	}

	private List<CandidateEvaluation> selectHousehold(List<CandidateEvaluation> household) {
		List<CandidateEvaluation> eligible = household.stream()
				.filter(CandidateEvaluation::scheduleFeasible)
				.filter(value -> value.delta() >= 0.0)
				.sorted(Comparator.comparing(value -> value.candidate().candidateId()))
				.toList();
		if (eligible.size() > 20) {
			throw new IllegalStateException("Household candidate set exceeds exact selector bound: "
					+ eligible.size());
		}
		BestSelection best = new BestSelection();
		search(eligible, 0, new ArrayList<>(), 0.0, best);
		return best.candidates;
	}

	private static void search(
			List<CandidateEvaluation> eligible, int index,
			List<CandidateEvaluation> chosen, double gain, BestSelection best) {
		if (index == eligible.size()) {
			if (gain > best.utilityGain + 1e-9
					|| (Math.abs(gain - best.utilityGain) <= 1e-9
					&& chosenIds(chosen).compareTo(chosenIds(best.candidates)) < 0)) {
				best.utilityGain = gain;
				best.candidates = List.copyOf(chosen);
			}
			return;
		}
		search(eligible, index + 1, chosen, gain, best);
		CandidateEvaluation candidate = eligible.get(index);
		if (chosen.stream().anyMatch(existing -> conflicts(existing, candidate))) return;
		chosen.add(candidate);
		search(eligible, index + 1, chosen, gain + candidate.delta(), best);
		chosen.removeLast();
	}

	private static boolean conflicts(CandidateEvaluation left, CandidateEvaluation right) {
		return candidatesConflict(left.candidate(), right.candidate());
	}

	static boolean candidatesConflict(
			HouseholdJointPlanCandidateCatalog.Candidate a,
			HouseholdJointPlanCandidateCatalog.Candidate b) {
		if (a.passengerPersonId().equals(b.passengerPersonId())
				&& a.passengerTripIndex() == b.passengerTripIndex()) return true;
		if (a.driverPersonId().equals(b.driverPersonId())
				&& a.driverTripIndex() == b.driverTripIndex()) return true;
		if (a.passengerPersonId().equals(b.driverPersonId())
				&& a.passengerTripIndex() == b.driverTripIndex()) return true;
		if (a.driverPersonId().equals(b.passengerPersonId())
				&& a.driverTripIndex() == b.passengerTripIndex()) return true;
		return a.vehicleId().equals(b.vehicleId())
				&& (a.driverRequiresCarSwitch() || b.driverRequiresCarSwitch());
	}

	private record Installation(List<HouseholdEscortBindingCatalog.Binding> bindings,
			int selectedPlansAdded) {
		Installation {
			bindings = List.copyOf(bindings);
		}
	}

	private Installation installSelections(
			Map<PersonTripKey, PassengerModeCandidate> releases,
			List<CandidateEvaluation> selected) {
		Map<Id<Person>, Plan> composites = new LinkedHashMap<>();
		Map<Id<Person>, List<Map.Entry<PersonTripKey, PassengerModeCandidate>>> releasesByPerson =
				new LinkedHashMap<>();
		for (var entry : releases.entrySet()) {
			releasesByPerson.computeIfAbsent(entry.getKey().personId(), ignored -> new ArrayList<>())
					.add(entry);
		}
		for (var entry : releasesByPerson.entrySet()) {
			Person person = scenario.getPopulation().getPersons().get(entry.getKey());
			Plan plan = composite(person, composites);
			entry.getValue().sort(Comparator.comparingInt(
					(Map.Entry<PersonTripKey, PassengerModeCandidate> value) -> value.getKey().tripIndex())
					.reversed());
			for (var release : entry.getValue()) {
				if (Double.isFinite(release.getValue().originEndTimeS())) {
					mainTrip(plan, release.getKey().tripIndex()).origin().setEndTime(
							release.getValue().originEndTimeS());
				}
				replaceMainTrip(plan, release.getKey().tripIndex(), release.getValue().elements());
				copyTaxiAttributesToOrigin(plan, release.getKey().tripIndex(), release.getValue());
			}
		}

		Map<Id<Person>, List<CandidateEvaluation>> selectedByDriver = new LinkedHashMap<>();
		for (CandidateEvaluation evaluation : selected) {
			var candidate = evaluation.candidate();
			Person passenger = requiredPerson(candidate.passengerPersonId());
			Plan passengerPlan = composite(passenger, composites);
			mainTrip(passengerPlan, candidate.passengerTripIndex()).origin().setEndTime(
					evaluation.passengerDepartureTimeS());
			Leg passengerLeg = createBoundPassengerLeg(
					candidate, evaluation.passengerJointTravelTimeS());
			replaceMainTrip(passengerPlan, candidate.passengerTripIndex(), List.of(passengerLeg));
			selectedByDriver.computeIfAbsent(Id.createPersonId(candidate.driverPersonId()),
					ignored -> new ArrayList<>()).add(evaluation);
		}

		for (var entry : selectedByDriver.entrySet()) {
			Person driver = scenario.getPopulation().getPersons().get(entry.getKey());
			Plan driverPlan = composite(driver, composites);
			List<CandidateEvaluation> driverSelections = entry.getValue();
			List<CandidateEvaluation> switches = driverSelections.stream()
					.filter(value -> value.candidate().driverRequiresCarSwitch()).toList();
			if (switches.size() > 1) throw new IllegalStateException("Multiple full-day switches for " + driver.getId());
			if (!switches.isEmpty()) {
				CandidateEvaluation selectedSwitch = switches.getFirst();
				List<Integer> indexes = new ArrayList<>(selectedSwitch.switchedDayCar().keySet());
				indexes.sort(Comparator.reverseOrder());
				for (int tripIndex : indexes) {
					replaceMainTripWithCar(driverPlan, tripIndex,
							selectedSwitch.switchedDayCar().get(tripIndex));
				}
			}
			for (CandidateEvaluation evaluation : driverSelections) {
				installDriverWaypoint(driverPlan, evaluation.candidate().driverTripIndex(),
						evaluation.waypointCar());
			}
		}

		for (var entry : composites.entrySet()) {
			Person person = scenario.getPopulation().getPersons().get(entry.getKey());
			Plan plan = entry.getValue();
			plan.getAttributes().putAttribute(HouseholdJointPlanAlternativeGenerator.ROLE_ATTRIBUTE,
					"household_joint_composite_after_iteration_0");
			plan.getAttributes().putAttribute(HouseholdJointPlanAlternativeGenerator.TEMPLATE_ATTRIBUTE, false);
			person.addPlan(plan);
			person.setSelectedPlan(plan);
		}

		List<HouseholdEscortBindingCatalog.Binding> active = new ArrayList<>();
		for (CandidateEvaluation evaluation : selected) {
			var candidate = evaluation.candidate();
			Person passenger = requiredPerson(candidate.passengerPersonId());
			Person driver = requiredPerson(candidate.driverPersonId());
			MainTrip passengerTrip = mainTrip(passenger.getSelectedPlan(), candidate.passengerTripIndex());
			MainTrip driverTrip = mainTrip(driver.getSelectedPlan(), candidate.driverTripIndex());
			Leg passengerLeg = onlyLeg(passengerTrip, "car_passenger");
			Leg driverLeg = modeLeg(driverTrip, TransportMode.car);
			NetworkRoute driverRoute = (NetworkRoute) driverLeg.getRoute();
			if (!fullLinkSequence(driverRoute).contains(Id.createLinkId(candidate.passengerPickupLinkId()))
					|| !fullLinkSequence(driverRoute).contains(
							Id.createLinkId(candidate.passengerDropoffLinkId()))) {
				throw new IllegalStateException("Installed joint driver route omits passenger waypoint: "
						+ candidate.candidateId());
			}
			HouseholdEscortBindingCatalog.Binding binding = new HouseholdEscortBindingCatalog.Binding(
					candidate.candidateId(), candidate.householdId(),
					"all_car_household_potential_audit_v3",
					!"car_passenger".equals(candidate.passengerOriginalMode()),
					passenger.getId(), allLegIndex(passenger.getSelectedPlan(), passengerLeg), passengerLeg,
					driver.getId(), allLegIndex(driver.getSelectedPlan(), driverLeg), driverLeg,
					HouseholdEscortBindingCatalog.snapshotNetworkRoute(driverRoute),
					Id.createVehicleId(candidate.vehicleId()),
					Id.createLinkId(candidate.passengerPickupLinkId()),
					Id.createLinkId(candidate.passengerDropoffLinkId()),
					driverRoute.getEndLinkId(), evaluation.passengerDepartureTimeS(),
					candidate.driverDepartureTimeS(), candidate.originAccessGapM(),
					candidate.destinationEgressGapM());
			passengerLeg.getAttributes().putAttribute(
					HouseholdEscortBindingCatalog.BINDING_KEY_ATTRIBUTE,
					HouseholdEscortBindingCatalog.bindingKey(binding));
			active.add(binding);
		}
		return new Installation(active, composites.size());
	}

	private Plan composite(Person person, Map<Id<Person>, Plan> composites) {
		return composites.computeIfAbsent(person.getId(), ignored -> {
			Plan copy = PopulationUtils.createPlan(person);
			PopulationUtils.copyFromTo(requiredSelectedPlan(person), copy);
			copy.setScore(null);
			return copy;
		});
	}

	private PassengerModeCandidate buildPtCandidate(
			Person person, MainTrip trip, int tripIndex, double departure) {
		List<? extends PlanElement> routed = ptRouter.calcRoute(
				FacilitiesUtils.toFacility(trip.origin(), facilities),
				FacilitiesUtils.toFacility(trip.destination(), facilities),
				departure, departure, departure, person, firstLeg(trip).getAttributes(),
				(routes, ignored) -> routes.stream()
						.filter(route -> !containsSchoolBus(route))
						.min(Comparator.comparingDouble(RaptorRoute::getTotalCosts)
								.thenComparingDouble(RaptorRoute::getTravelTime))
						.orElse(null));
		if (routed == null || routed.isEmpty()) return unavailablePt();
		List<PlanElement> elements = new ArrayList<>(routed);
		int ptLegs = 0;
		double fare = 0.0;
		for (PlanElement element : elements) {
			if (!(element instanceof Leg leg)) continue;
			leg.setRoutingMode(TransportMode.pt);
			setReleaseAttributes(leg.getAttributes(), TransportMode.pt, tripIndex);
			if (!TransportMode.pt.equals(leg.getMode())) continue;
			ptLegs++;
			if (!(leg.getRoute() instanceof TransitPassengerRoute first)) return unavailablePt();
			Set<TransitPassengerRoute> visited = Collections.newSetFromMap(new IdentityHashMap<>());
			for (TransitPassengerRoute current = first; current != null; current = current.getChainedRoute()) {
				if (!visited.add(current)) throw new IllegalStateException("PT chained route cycle");
				TransitLine line = scenario.getTransitSchedule().getTransitLines().get(current.getLineId());
				TransitRoute transitRoute = line == null ? null : line.getRoutes().get(current.getRouteId());
				if (transitRoute == null || "school_bus".equals(transitRoute.getTransportMode())) {
					return unavailablePt();
				}
				var quote = ptFareCatalog.quote(current, scenario.getTransitSchedule());
				if (quote.resolved()) fare += quote.costHkd();
			}
		}
		if (ptLegs == 0) return unavailablePt();
		return new PassengerModeCandidate(TransportMode.pt, elements,
				standardTripUtility(elements) - fare * config.scoring().getMarginalUtilityOfMoney(),
				tripTravelTime(elements), fare, true, Double.NaN, "pt");
	}

	private static PassengerModeCandidate unavailablePt() {
		return unavailable(TransportMode.pt, "pt_unavailable");
	}

	private PassengerModeCandidate buildTaxiCandidate(
			TripRouter router, Person person, MainTrip trip, int tripIndex, double departure) {
		AttributesImpl attributes = copyAttributes(firstLeg(trip).getAttributes());
		setTaxiAttributes(attributes, 0.0, tripIndex);
		List<PlanElement> elements = new ArrayList<>(router.calcRoute(
				HongKongJointPlanModes.TAXI,
				FacilitiesUtils.toFacility(trip.origin(), facilities),
				FacilitiesUtils.toFacility(trip.destination(), facilities),
				departure, person, attributes));
		Leg taxi = elements.stream().filter(Leg.class::isInstance).map(Leg.class::cast)
				.filter(leg -> HongKongJointPlanModes.TAXI.equals(leg.getMode()))
				.findFirst().orElseThrow();
		if (taxi.getRoute() == null || !Double.isFinite(taxi.getRoute().getDistance())) {
			throw new IllegalStateException("Taxi release lacks route distance: " + person.getId());
		}
		double fare = taxiFareCalculator.calculate(
				taxi.getRoute().getDistance(), HongKongTaxiFareCalculator.UNRESOLVED).fareHkd();
		setTaxiAttributes(taxi.getAttributes(), fare, tripIndex);
		setReleaseAttributes(taxi.getAttributes(), HongKongJointPlanModes.TAXI, tripIndex);
		return new PassengerModeCandidate(HongKongJointPlanModes.TAXI, elements,
				standardTripUtility(elements) + taxiParameters.fareScore(fare),
				tripTravelTime(elements), fare, true, Double.NaN, "taxi");
	}

	private PassengerModeCandidate buildWalkCandidate(
			TripRouter router, Person person, MainTrip trip, int tripIndex, double departure) {
		List<PlanElement> elements = physicalWalkRouteOrNull(() -> router.calcRoute(
				TransportMode.walk,
				FacilitiesUtils.toFacility(trip.origin(), facilities),
				FacilitiesUtils.toFacility(trip.destination(), facilities),
				departure, person, firstLeg(trip).getAttributes()));
		if (elements == null) {
			return unavailable(TransportMode.walk, "walk_network_unreachable");
		}
		for (PlanElement element : elements) {
			if (element instanceof Leg leg) {
				leg.setRoutingMode(TransportMode.walk);
				setReleaseAttributes(leg.getAttributes(), TransportMode.walk, tripIndex);
			}
		}
		return new PassengerModeCandidate(TransportMode.walk, elements,
				standardTripUtility(elements), tripTravelTime(elements), 0.0, true,
				Double.NaN, "walk");
	}

	private PassengerModeCandidate buildSchoolBusCandidate(
			TripRouter router, Person person, MainTrip trip, int tripIndex,
			StudentSchoolModeCandidateCatalog.SchoolBusOption option) {
		TransitLine line = scenario.getTransitSchedule().getTransitLines().get(
				Id.create(option.transitLineId(), TransitLine.class));
		if (line == null) return unavailable("school_bus", option.candidateId() + ":missing_line");
		TransitRoute transitRoute = line.getRoutes().get(Id.create(option.transitRouteId(), TransitRoute.class));
		if (transitRoute == null || !"school_bus".equals(transitRoute.getTransportMode())) {
			return unavailable("school_bus", option.candidateId() + ":missing_physical_route");
		}
		Departure scheduledDeparture = transitRoute.getDepartures().get(
				Id.create(option.departureId(), Departure.class));
		if (scheduledDeparture == null || scheduledDeparture.getVehicleId() == null
				|| !option.vehicleId().equals(scheduledDeparture.getVehicleId().toString())) {
			return unavailable("school_bus", option.candidateId() + ":missing_departure");
		}
		TransitStopFacility boarding = scenario.getTransitSchedule().getFacilities().get(
				Id.create(option.boardingFacilityId(), TransitStopFacility.class));
		TransitStopFacility alighting = scenario.getTransitSchedule().getFacilities().get(
				Id.create(option.alightingFacilityId(), TransitStopFacility.class));
		if (boarding == null || alighting == null
				|| boarding.getLinkId() == null || alighting.getLinkId() == null
				|| !option.boardingLinkId().equals(boarding.getLinkId().toString())
				|| !option.alightingLinkId().equals(alighting.getLinkId().toString())) {
			return unavailable("school_bus", option.candidateId() + ":missing_stop");
		}
		Link boardingLink = scenario.getNetwork().getLinks().get(boarding.getLinkId());
		Link alightingLink = scenario.getNetwork().getLinks().get(alighting.getLinkId());
		if (boardingLink == null || alightingLink == null) {
			return unavailable("school_bus", option.candidateId() + ":missing_stop_link");
		}

		double desiredDeparture = tripDeparture(trip);
		List<PlanElement> provisionalAccess = physicalWalkRouteOrNull(() -> router.calcRoute(
				TransportMode.walk, FacilitiesUtils.toFacility(trip.origin(), facilities),
				FacilitiesUtils.wrapLinkAndCoord(boardingLink, boarding.getCoord()),
				desiredDeparture, person, firstLeg(trip).getAttributes()));
		if (provisionalAccess == null) {
			return unavailable("school_bus", option.candidateId() + ":access_unreachable");
		}
		double accessTime = tripTravelTime(provisionalAccess);
		double readyDeadline = option.scheduledBoardTimeS() - SCHOOL_BUS_BOARDING_READY_MARGIN_S;
		double start = desiredDeparture + accessTime <= readyDeadline + 1e-6
				? desiredDeparture : readyDeadline - accessTime;
		if (!Double.isFinite(start) || start < 0.0) {
			return unavailable("school_bus", option.candidateId() + ":invalid_start");
		}
		List<PlanElement> access = physicalWalkRouteOrNull(() -> router.calcRoute(
				TransportMode.walk, FacilitiesUtils.toFacility(trip.origin(), facilities),
				FacilitiesUtils.wrapLinkAndCoord(boardingLink, boarding.getCoord()),
				start, person, firstLeg(trip).getAttributes()));
		if (access == null) {
			return unavailable("school_bus", option.candidateId() + ":access_unreachable");
		}
		accessTime = tripTravelTime(access);
		double accessArrival = start + accessTime;
		if (accessArrival > readyDeadline + 1e-6
				|| option.scheduledAlightTimeS() < option.scheduledBoardTimeS()) {
			return unavailable("school_bus", option.candidateId() + ":schedule_infeasible");
		}

		List<PlanElement> egress = physicalWalkRouteOrNull(() -> router.calcRoute(
				TransportMode.walk, FacilitiesUtils.wrapLinkAndCoord(alightingLink, alighting.getCoord()),
				FacilitiesUtils.toFacility(trip.destination(), facilities),
				option.scheduledAlightTimeS(), person, firstLeg(trip).getAttributes()));
		if (egress == null) {
			return unavailable("school_bus", option.candidateId() + ":egress_unreachable");
		}
		for (PlanElement element : access) if (element instanceof Leg leg) {
			leg.setRoutingMode("school_bus");
			setReleaseAttributes(leg.getAttributes(), "school_bus", tripIndex);
		}
		for (PlanElement element : egress) if (element instanceof Leg leg) {
			leg.setRoutingMode("school_bus");
			setReleaseAttributes(leg.getAttributes(), "school_bus", tripIndex);
		}

		Activity boardingStage = PopulationUtils.createStageActivityFromCoordLinkIdAndModePrefix(
				boarding.getCoord(), boarding.getLinkId(), TransportMode.pt);
		boardingStage.setMaximumDuration(0.0);
		Activity alightingStage = PopulationUtils.createStageActivityFromCoordLinkIdAndModePrefix(
				alighting.getCoord(), alighting.getLinkId(), TransportMode.pt);
		alightingStage.setMaximumDuration(0.0);
		DefaultTransitPassengerRoute passengerRoute = new DefaultTransitPassengerRoute(
				boarding, line, transitRoute, alighting);
		passengerRoute.setBoardingTime(option.scheduledBoardTimeS());
		passengerRoute.setTravelTime(option.scheduledAlightTimeS() - accessArrival);
		passengerRoute.setDistance(transitSegmentDistance(transitRoute, boarding, alighting));
		Leg schoolBus = PopulationUtils.createLeg(TransportMode.pt);
		schoolBus.setRoutingMode("school_bus");
		schoolBus.setDepartureTime(accessArrival);
		schoolBus.setTravelTime(option.scheduledAlightTimeS() - accessArrival);
		schoolBus.setRoute(passengerRoute);
		setReleaseAttributes(schoolBus.getAttributes(), "school_bus", tripIndex);
		schoolBus.getAttributes().putAttribute("hkSchoolBusCandidateId", option.candidateId());

		List<PlanElement> elements = new ArrayList<>();
		elements.addAll(access);
		elements.add(boardingStage);
		elements.add(schoolBus);
		elements.add(alightingStage);
		elements.addAll(egress);
		double earlyScheduleShift = Math.max(0.0, desiredDeparture - start);
		double utility = standardTripUtility(elements)
				+ TRAVEL_UTILITY_PER_HOUR * earlyScheduleShift / 3_600.0;
		return new PassengerModeCandidate("school_bus", elements, utility,
				tripTravelTime(elements) + earlyScheduleShift, 0.0, true,
				start, option.candidateId());
	}

	private double transitSegmentDistance(
			TransitRoute route, TransitStopFacility boarding, TransitStopFacility alighting) {
		List<TransitRouteStop> stops = route.getStops();
		int fromStop = -1;
		int toStop = -1;
		for (int index = 0; index < stops.size(); index++) {
			if (fromStop < 0 && stops.get(index).getStopFacility().getId().equals(boarding.getId())) {
				fromStop = index;
			}
			if (fromStop >= 0 && index > fromStop
					&& stops.get(index).getStopFacility().getId().equals(alighting.getId())) {
				toStop = index;
				break;
			}
		}
		if (fromStop < 0 || toStop < 0) throw new IllegalStateException(
				"School-bus stop order is invalid on " + route.getId());
		List<Id<Link>> links = fullLinkSequence(route.getRoute());
		List<Integer> stopLinkIndexes = new ArrayList<>(stops.size());
		int searchFrom = 0;
		for (TransitRouteStop stop : stops) {
			Id<Link> linkId = stop.getStopFacility().getLinkId();
			int resolved = -1;
			for (int index = searchFrom; index < links.size(); index++) {
				if (links.get(index).equals(linkId)) {
					resolved = index;
					break;
				}
			}
			if (resolved < 0 && searchFrom > 0 && links.get(searchFrom - 1).equals(linkId)) {
				resolved = searchFrom - 1;
			}
			if (resolved < 0) throw new IllegalStateException(
					"School-bus stop link is absent from route " + route.getId() + ": " + linkId);
			stopLinkIndexes.add(resolved);
			searchFrom = Math.min(links.size(), resolved + 1);
		}
		int fromLink = stopLinkIndexes.get(fromStop);
		int toLink = stopLinkIndexes.get(toStop);
		if (fromLink < 0 || toLink < fromLink) throw new IllegalStateException(
				"School-bus stop links are absent or reversed on " + route.getId());
		double distance = 0.0;
		for (int index = fromLink; index <= toLink; index++) {
			Link link = scenario.getNetwork().getLinks().get(links.get(index));
			if (link == null) throw new IllegalStateException("Missing school-bus route link " + links.get(index));
			distance += link.getLength();
		}
		return distance;
	}

	private static PassengerModeCandidate unavailable(String mode, String source) {
		return new PassengerModeCandidate(mode, List.of(), Double.NEGATIVE_INFINITY,
				Double.NaN, 0.0, false, Double.NaN, source);
	}

	private static boolean containsSchoolBus(RaptorRoute route) {
		for (RaptorRoute.RoutePart part : route.getParts()) {
			for (RaptorRoute.RoutePart current = part; current != null; current = current.chainedPart) {
				if (current.route != null && "school_bus".equals(current.route.getTransportMode())) return true;
			}
		}
		return false;
	}

	private WaypointRoute routeWaypoint(
			TripRouter router, HouseholdJointPlanCandidateCatalog.Candidate candidate,
			Person driver, MainTrip driverTrip, MainTrip passengerTrip,
			Id<Vehicle> vehicleId, double parkingEnd) {
		double departure = candidate.driverDepartureTimeS();
		NetworkRoute first = routeCar(router, driverTrip.origin(), passengerTrip.origin(),
				departure, driver, firstLeg(driverTrip).getAttributes(), vehicleId);
		double pickup = departure + routeTravelTime(first, departure, driver, vehicleId);
		NetworkRoute ride = routeCar(router, passengerTrip.origin(), passengerTrip.destination(),
				pickup, driver, firstLeg(driverTrip).getAttributes(), vehicleId);
		double dropoff = pickup + routeTravelTime(ride, pickup, driver, vehicleId);
		NetworkRoute last = routeCar(router, passengerTrip.destination(), driverTrip.destination(),
				dropoff, driver, firstLeg(driverTrip).getAttributes(), vehicleId);
		NetworkRoute route = combine(List.of(first, ride, last), vehicleId);
		if (!fullLinkSequence(route).contains(Id.createLinkId(candidate.passengerPickupLinkId()))
				|| !fullLinkSequence(route).contains(Id.createLinkId(candidate.passengerDropoffLinkId()))) {
			throw new IllegalStateException("Waypoint route omits audited pickup/dropoff: "
					+ candidate.candidateId());
		}
		return new WaypointRoute(
				evaluateCar(route, departure, driver, vehicleId, driverTrip.destination(), parkingEnd),
				dropoff);
	}

	private NetworkRoute routeCar(
			TripRouter router, Activity origin, Activity destination, double departure,
			Person driver, Attributes attributes, Id<Vehicle> vehicleId) {
		List<? extends PlanElement> routed = router.calcRoute(
				TransportMode.car, FacilitiesUtils.toFacility(origin, facilities),
				FacilitiesUtils.toFacility(destination, facilities), departure, driver, attributes);
		Leg car = routed.stream().filter(Leg.class::isInstance).map(Leg.class::cast)
				.filter(leg -> TransportMode.car.equals(leg.getMode())).findFirst()
				.orElseThrow(() -> new IllegalStateException("Car routing returned no Car leg for " + driver.getId()));
		if (!(car.getRoute() instanceof NetworkRoute route)) {
			throw new IllegalStateException("Car routing returned no NetworkRoute for " + driver.getId());
		}
		route.setVehicleId(vehicleId);
		return route;
	}

	private CarMetric evaluateCar(
			NetworkRoute route, double departure, Person driver, Id<Vehicle> vehicleId,
			Activity destination, double parkingEnd) {
		double travelTime = routeTravelTime(route, departure, driver, vehicleId);
		double arrival = departure + travelTime;
		Vehicle vehicle = scenario.getVehicles().getVehicles().get(vehicleId);
		var routeCost = costRules.quoteNetworkRoute(route, departure, carTravelTime, driver, vehicle);
		if (destination.getFacilityId() == null) {
			throw new IllegalStateException("Car destination lacks parking facility: " + driver.getId());
		}
		double parking = costRules.quoteParking(destination.getFacilityId().toString(),
				destination.getType(), arrival, Math.max(arrival, parkingEnd)).costHkd();
		route.setTravelTime(travelTime);
		route.setDistance(fullLinkSequence(route).stream().map(scenario.getNetwork().getLinks()::get)
				.mapToDouble(Link::getLength).sum());
		return new CarMetric(route, travelTime, arrival, routeCost.energyHkd(),
				routeCost.tollHkd(), parking);
	}

	private double routeTravelTime(
			NetworkRoute route, double departure, Person driver, Id<Vehicle> vehicleId) {
		Vehicle vehicle = scenario.getVehicles().getVehicles().get(vehicleId);
		double time = departure;
		for (Id<Link> linkId : enteredLinkSequence(route)) {
			Link link = scenario.getNetwork().getLinks().get(linkId);
			if (link == null) throw new IllegalStateException("Route references missing link " + linkId);
			double seconds = carTravelTime.getLinkTravelTime(link, time, driver, vehicle);
			if (!Double.isFinite(seconds) || seconds < 0.0) {
				throw new IllegalStateException("Invalid Car travel time on " + linkId);
			}
			time += seconds;
		}
		return time - departure;
	}

	private double originalTripUtility(MainTrip trip) {
		double utility = standardTripUtility(trip.elements());
		for (PlanElement element : trip.elements()) {
			if (!(element instanceof Leg leg)) continue;
			if (HongKongJointPlanModes.TAXI.equals(leg.getMode()) && leg.getRoute() != null
					&& Double.isFinite(leg.getRoute().getDistance())) {
				double fare = taxiFareCalculator.calculate(
						leg.getRoute().getDistance(), HongKongTaxiFareCalculator.UNRESOLVED).fareHkd();
				utility += taxiParameters.fareScore(fare);
			}
			if (TransportMode.pt.equals(leg.getMode()) && leg.getRoute() instanceof TransitPassengerRoute first) {
				Set<TransitPassengerRoute> visited = Collections.newSetFromMap(new IdentityHashMap<>());
				for (TransitPassengerRoute current = first; current != null; current = current.getChainedRoute()) {
					if (!visited.add(current)) throw new IllegalStateException("PT chained route cycle");
					var quote = ptFareCatalog.quote(current, scenario.getTransitSchedule());
					if (quote.resolved()) utility -= quote.costHkd() * config.scoring().getMarginalUtilityOfMoney();
				}
			}
		}
		return utility;
	}

	private double baselineDriverTripUtility(
			Plan plan, int tripIndex, MainTrip trip, Person driver, Id<Vehicle> vehicleId) {
		if (!TransportMode.car.equals(mainMode(trip))) return originalTripUtility(trip);
		NetworkRoute route = copyRoute(originalCarRoute(trip, vehicleId));
		return evaluateCar(route, tripDeparture(trip), driver, vehicleId, trip.destination(),
				nextCarTripDeparture(plan, tripIndex)).utility();
	}

	private double standardTripUtility(List<PlanElement> elements) {
		double utility = 0.0;
		for (PlanElement element : elements) {
			if (!(element instanceof Leg leg)) continue;
			String scoringMode = scoringModeForLeg(leg);
			ScoringConfigGroup.ModeParams params = config.scoring().getModes().get(scoringMode);
			if (params == null) throw new IllegalStateException("Missing scoring mode " + scoringMode);
			double travelTime = requiredTravelTime(leg);
			double distance = leg.getRoute() == null ? 0.0 : leg.getRoute().getDistance();
			if (!Double.isFinite(distance)) distance = 0.0;
			utility += params.getConstant()
					+ params.getMarginalUtilityOfTraveling() * travelTime / 3_600.0
					+ (params.getMarginalUtilityOfDistance()
					+ config.scoring().getMarginalUtilityOfMoney() * params.getMonetaryDistanceRate()) * distance;
		}
		return utility;
	}

	static String scoringModeForLeg(Leg leg) {
		if (TransportMode.pt.equals(leg.getMode())
				&& "school_bus".equals(leg.getRoutingMode())) {
			return "school_bus";
		}
		if (TransportMode.non_network_walk.equals(leg.getMode())) {
			return TransportMode.walk;
		}
		return leg.getMode();
	}

	private static List<PlanElement> physicalWalkRouteOrNull(
			java.util.function.Supplier<List<? extends PlanElement>> routingCall) {
		try {
			return new ArrayList<>(routingCall.get());
		} catch (RuntimeException exception) {
			if (isNoNetworkRouteFailure(exception)) return null;
			throw exception;
		}
	}

	static boolean isNoNetworkRouteFailure(RuntimeException exception) {
		for (Throwable current = exception; current != null; current = current.getCause()) {
			String message = current.getMessage();
			if (message != null && message.startsWith("No route found from node ")) return true;
		}
		return false;
	}

	private static double passengerUtility(double travelTimeS) {
		return PASSENGER_CONSTANT + TRAVEL_UTILITY_PER_HOUR * travelTimeS / 3_600.0;
	}

	private static MainTrip mainTrip(Plan plan, int index) {
		List<TripStructureUtils.Trip> trips = List.copyOf(TripStructureUtils.getTrips(plan));
		if (index < 0 || index >= trips.size()) throw new IllegalStateException("Missing main trip " + index);
		TripStructureUtils.Trip trip = trips.get(index);
		return new MainTrip(trip.getOriginActivity(), trip.getDestinationActivity(), trip.getTripElements());
	}

	private static String mainMode(MainTrip trip) {
		Set<String> routingModes = new LinkedHashSet<>();
		for (PlanElement element : trip.elements()) {
			if (element instanceof Leg leg) routingModes.add(
					leg.getRoutingMode() == null ? leg.getMode() : leg.getRoutingMode());
		}
		if (routingModes.size() == 1) return routingModes.iterator().next();
		for (String preferred : List.of("car_passenger", TransportMode.car,
				HongKongJointPlanModes.TAXI, "school_bus", TransportMode.pt, TransportMode.walk)) {
			if (routingModes.contains(preferred)) return preferred;
		}
		throw new IllegalStateException("Cannot identify trip mode " + routingModes);
	}

	private static Leg firstLeg(MainTrip trip) {
		return trip.elements().stream().filter(Leg.class::isInstance).map(Leg.class::cast)
				.findFirst().orElseThrow(() -> new IllegalStateException("Main trip has no leg"));
	}

	private static Leg onlyLeg(MainTrip trip, String mode) {
		List<Leg> legs = trip.elements().stream().filter(Leg.class::isInstance).map(Leg.class::cast).toList();
		if (legs.size() != 1 || !mode.equals(legs.getFirst().getMode())) {
			throw new IllegalStateException("Expected one " + mode + " leg, found " + legs);
		}
		return legs.getFirst();
	}

	private static Leg modeLeg(MainTrip trip, String mode) {
		List<Leg> legs = trip.elements().stream().filter(Leg.class::isInstance).map(Leg.class::cast)
				.filter(leg -> mode.equals(leg.getMode())).toList();
		if (legs.size() != 1) throw new IllegalStateException("Expected one " + mode + " leg");
		return legs.getFirst();
	}

	private static double tripDeparture(MainTrip trip) {
		for (PlanElement element : trip.elements()) {
			if (element instanceof Leg leg && leg.getDepartureTime().isDefined()) {
				return leg.getDepartureTime().seconds();
			}
		}
		if (trip.origin().getEndTime().isDefined()) return trip.origin().getEndTime().seconds();
		throw new IllegalStateException("Main trip lacks departure time");
	}

	private double nextMainTripDeparture(Plan plan, int tripIndex) {
		int count = TripStructureUtils.getTrips(plan).size();
		return tripIndex + 1 < count ? tripDeparture(mainTrip(plan, tripIndex + 1)) : qsimEndTimeS;
	}

	private double nextCarTripDeparture(Plan plan, int tripIndex) {
		int count = TripStructureUtils.getTrips(plan).size();
		for (int index = tripIndex + 1; index < count; index++) {
			MainTrip trip = mainTrip(plan, index);
			if (TransportMode.car.equals(mainMode(trip))) return tripDeparture(trip);
		}
		return qsimEndTimeS;
	}

	private static NetworkRoute originalCarRoute(MainTrip trip, Id<Vehicle> vehicleId) {
		Leg car = modeLeg(trip, TransportMode.car);
		if (!(car.getRoute() instanceof NetworkRoute route)) {
			throw new IllegalStateException("Original Car trip lacks NetworkRoute");
		}
		if (!vehicleId.equals(route.getVehicleId())) {
			throw new IllegalStateException("Original Car trip vehicle mismatch");
		}
		return route;
	}

	private static void replaceMainTrip(Plan plan, int tripIndex, List<PlanElement> elements) {
		TripStructureUtils.Trip trip = TripStructureUtils.getTrips(plan).get(tripIndex);
		TripRouter.insertTrip(plan, trip.getOriginActivity(), elements, trip.getDestinationActivity());
	}

	private static void replaceMainTripWithCar(Plan plan, int tripIndex, CarMetric metric) {
		Leg leg = PopulationUtils.createLeg(TransportMode.car);
		leg.setRoutingMode(TransportMode.car);
		leg.setRoute(copyRoute(metric.route()));
		leg.setTravelTime(metric.travelTimeS());
		replaceMainTrip(plan, tripIndex, List.of(leg));
	}

	static Leg createBoundPassengerLeg(
			HouseholdJointPlanCandidateCatalog.Candidate candidate, double travelTimeS) {
		Leg passengerLeg = PopulationUtils.createLeg("car_passenger");
		passengerLeg.setRoutingMode("car_passenger");
		var passengerRoute = RouteUtils.createGenericRouteImpl(
				Id.createLinkId(candidate.passengerPickupLinkId()),
				Id.createLinkId(candidate.passengerDropoffLinkId()));
		passengerRoute.setTravelTime(travelTimeS);
		passengerLeg.setRoute(passengerRoute);
		passengerLeg.setTravelTime(travelTimeS);
		passengerLeg.getAttributes().putAttribute(
				HouseholdJointPlanAlternativeGenerator.CANDIDATE_ID_ATTRIBUTE,
				candidate.candidateId());
		return passengerLeg;
	}

	private static void installDriverWaypoint(Plan plan, int tripIndex, CarMetric metric) {
		MainTrip trip = mainTrip(plan, tripIndex);
		Leg leg = modeLeg(trip, TransportMode.car);
		leg.setRoute(copyRoute(metric.route()));
		leg.setTravelTime(metric.travelTimeS());
	}

	private static int allLegIndex(Plan plan, Leg target) {
		int index = 0;
		for (PlanElement element : plan.getPlanElements()) {
			if (element == target) return index;
			if (element instanceof Leg) index++;
		}
		throw new IllegalStateException("Leg is absent from selected composite plan");
	}

	private static void copyTaxiAttributesToOrigin(
			Plan plan, int tripIndex, PassengerModeCandidate candidate) {
		if (!HongKongJointPlanModes.TAXI.equals(candidate.mode())) return;
		Leg taxi = candidate.elements().stream().filter(Leg.class::isInstance).map(Leg.class::cast)
				.filter(leg -> HongKongJointPlanModes.TAXI.equals(leg.getMode())).findFirst().orElseThrow();
		Activity origin = TripStructureUtils.getTrips(plan).get(tripIndex).getOriginActivity();
		for (String name : HongKongTaxiLegAttributes.NAMES) {
			origin.getAttributes().putAttribute(name, taxi.getAttributes().getAttribute(name));
		}
	}

	private Person requiredPerson(String personId) {
		Person person = scenario.getPopulation().getPersons().get(Id.createPersonId(personId));
		if (person == null) throw new IllegalStateException("Missing person " + personId);
		return person;
	}

	private static Plan requiredSelectedPlan(Person person) {
		if (person.getSelectedPlan() == null) throw new IllegalStateException("No selected plan " + person.getId());
		return person.getSelectedPlan();
	}

	private static double tripTravelTime(List<PlanElement> elements) {
		return elements.stream().filter(Leg.class::isInstance).map(Leg.class::cast)
				.mapToDouble(HouseholdJointPlanSelector::requiredTravelTime).sum();
	}

	private static double requiredTravelTime(Leg leg) {
		if (leg.getTravelTime().isDefined()) return leg.getTravelTime().seconds();
		if (leg.getRoute() != null && leg.getRoute().getTravelTime().isDefined()) {
			return leg.getRoute().getTravelTime().seconds();
		}
		throw new IllegalStateException("Leg lacks travel time for mode " + leg.getMode());
	}

	private void setTaxiAttributes(Attributes attributes, double fare, int tripIndex) {
		for (String name : HongKongTaxiLegAttributes.NAMES) attributes.removeAttribute(name);
		attributes.putAttribute(HongKongTaxiLegAttributes.FARE_BASELINE_HKD, fare);
		attributes.putAttribute(HongKongTaxiLegAttributes.TAXI_TYPE, HongKongTaxiFareCalculator.UNRESOLVED);
		attributes.putAttribute(HongKongTaxiLegAttributes.FARE_SCOPE, taxiParameters.fareScope());
		attributes.putAttribute(HongKongTaxiLegAttributes.FARE_MODEL_VERSION, taxiParameters.fareModelVersion());
		attributes.putAttribute(HongKongTaxiLegAttributes.CLASSIFICATION_SOURCE,
				"household_joint_plan_release_pt_taxi_walk_v1");
		attributes.putAttribute(HongKongTaxiLegAttributes.MAIN_TRIP_INDEX, tripIndex);
	}

	private static void setReleaseAttributes(Attributes attributes, String mode, int tripIndex) {
		attributes.putAttribute(RELEASED_MODE_ATTRIBUTE, mode);
		attributes.putAttribute(RELEASED_TRIP_INDEX_ATTRIBUTE, tripIndex);
	}

	private static AttributesImpl copyAttributes(Attributes source) {
		AttributesImpl copy = new AttributesImpl();
		for (var entry : source.getAsMap().entrySet()) copy.putAttribute(entry.getKey(), entry.getValue());
		return copy;
	}

	private static int releaseTiePriority(String mode) {
		if (TransportMode.pt.equals(mode)) return 4;
		if ("school_bus".equals(mode)) return 3;
		if (HongKongJointPlanModes.TAXI.equals(mode)) return 2;
		if (TransportMode.walk.equals(mode)) return 1;
		throw new IllegalArgumentException("Unsupported release mode " + mode);
	}

	private static String chosenIds(List<CandidateEvaluation> values) {
		return String.join("\n", values.stream().map(value -> value.candidate().candidateId()).toList());
	}

	private static NetworkRoute combine(List<NetworkRoute> segments, Id<Vehicle> vehicleId) {
		List<Id<Link>> full = new ArrayList<>();
		for (NetworkRoute segment : segments) {
			for (Id<Link> linkId : fullLinkSequence(segment)) {
				if (full.isEmpty() || !full.getLast().equals(linkId)) full.add(linkId);
			}
		}
		NetworkRoute result = RouteUtils.createLinkNetworkRouteImpl(
				full.getFirst(), full.size() <= 2 ? List.of() : full.subList(1, full.size() - 1),
				full.getLast());
		result.setVehicleId(vehicleId);
		return result;
	}

	private static NetworkRoute copyRoute(NetworkRoute source) {
		NetworkRoute copy = RouteUtils.createLinkNetworkRouteImpl(
				source.getStartLinkId(), new ArrayList<>(source.getLinkIds()), source.getEndLinkId());
		copy.setVehicleId(source.getVehicleId());
		copy.setDistance(source.getDistance());
		if (source.getTravelTime().isDefined()) copy.setTravelTime(source.getTravelTime().seconds());
		return copy;
	}

	private static List<Id<Link>> fullLinkSequence(NetworkRoute route) {
		List<Id<Link>> result = new ArrayList<>();
		if (route.getStartLinkId() != null) result.add(route.getStartLinkId());
		result.addAll(route.getLinkIds());
		if (route.getEndLinkId() != null && (result.isEmpty() || !result.getLast().equals(route.getEndLinkId()))) {
			result.add(route.getEndLinkId());
		}
		return result;
	}

	private static List<Id<Link>> enteredLinkSequence(NetworkRoute route) {
		List<Id<Link>> result = new ArrayList<>(route.getLinkIds());
		if (route.getEndLinkId() != null && (result.isEmpty() || !result.getLast().equals(route.getEndLinkId()))) {
			result.add(route.getEndLinkId());
		}
		return result;
	}
}
