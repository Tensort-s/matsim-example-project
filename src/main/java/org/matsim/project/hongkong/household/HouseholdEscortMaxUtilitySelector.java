package org.matsim.project.hongkong.household;

import ch.sbb.matsim.routing.pt.raptor.SwissRailRaptor;
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
import org.matsim.core.controler.events.StartupEvent;
import org.matsim.core.controler.listener.StartupListener;
import org.matsim.core.population.routes.NetworkRoute;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.router.DefaultRoutingRequest;
import org.matsim.core.router.TripRouter;
import org.matsim.core.router.util.TravelTime;
import org.matsim.facilities.ActivityFacilities;
import org.matsim.facilities.FacilitiesUtils;
import org.matsim.pt.routes.TransitPassengerRoute;
import org.matsim.project.hongkong.car.HongKongDynamicCarCostRules;
import org.matsim.project.hongkong.pt.HongKongPtFareRuntimeCatalog;
import org.matsim.project.hongkong.taxi.HongKongTaxiFareCalculator;
import org.matsim.project.hongkong.taxi.HongKongTaxiLegAttributes;
import org.matsim.project.hongkong.taxi.HongKongTaxiScoringParameters;
import org.matsim.utils.objectattributes.attributable.Attributes;
import org.matsim.utils.objectattributes.attributable.AttributesImpl;
import org.matsim.vehicles.Vehicle;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.IdentityHashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * One-shot deterministic household selector over a persistent registry of
 * existing and newly screened passenger-driver candidates. Candidate bundles
 * are selected atomically subject to driver-leg vehicle-resource conflicts.
 */
public final class HouseholdEscortMaxUtilitySelector implements StartupListener {

	private static final Logger LOG = LogManager.getLogger(HouseholdEscortMaxUtilitySelector.class);
	private static final double DRIVER_CONSTANT = -0.5;
	private static final double PASSENGER_CONSTANT = -1.5;
	private static final double TRAVEL_UTILITY_PER_HOUR = -6.0;
	private static final String RELEASED_MODE_ATTRIBUTE =
			"hkHouseholdEscortReleasedPassengerMode";
	private static final String RELEASED_LEG_INDEX_ATTRIBUTE =
			"hkHouseholdEscortOriginalPassengerLegIndex";

	private record PlanTrip(Leg leg, Activity origin, Activity destination, int elementIndex) {
	}

	private record RouteMetric(
			NetworkRoute route,
			double travelTimeS,
			double arrivalTimeS,
			double energyHkd,
			double tollHkd,
			double parkingHkd) {
		double driverUtility() {
			return DRIVER_CONSTANT + TRAVEL_UTILITY_PER_HOUR * travelTimeS / 3_600.0
					- energyHkd - tollHkd - parkingHkd;
		}
	}

	private record WaypointCandidate(
			RouteMetric metric,
			double passengerPickupTimeS,
			double passengerArrivalTimeS,
			boolean scheduleFeasible) {
	}

	private record PassengerModeCandidate(
			String mode,
			List<PlanElement> trip,
			double utility,
			double travelTimeS,
			double fareHkd,
			int unresolvedFareSegments,
			boolean available) {
		PassengerModeCandidate {
			trip = List.copyOf(trip);
		}
	}

	private record EvaluatedBundle(
			String candidateGroupId,
			String householdId,
			Person passenger,
			List<HouseholdEscortBindingCatalog.Binding> bindings,
			List<PlanTrip> passengerTrips,
			List<PassengerModeCandidate> unboundModeCandidates,
			List<WaypointCandidate> waypointCandidates,
			double boundUtility,
			double unboundUtility,
			boolean scheduleFeasible,
			boolean newCandidate) {
		EvaluatedBundle {
			bindings = List.copyOf(bindings);
			passengerTrips = List.copyOf(passengerTrips);
			unboundModeCandidates = List.copyOf(unboundModeCandidates);
			waypointCandidates = List.copyOf(waypointCandidates);
		}

		double delta() {
			return boundUtility - unboundUtility;
		}

		Set<String> resourceKeys() {
			Set<String> keys = new LinkedHashSet<>();
			for (var binding : bindings) {
				keys.add(binding.vehicleId() + "/" + binding.driverId() + "/" + binding.driverLegIndex());
			}
			return keys;
		}
	}

	private static final class BestSelection {
		private double delta = Double.NEGATIVE_INFINITY;
		private List<String> candidateIds = List.of();
	}

	static record ResourceCandidate(String candidateId, double delta, Set<String> resourceKeys) {
		ResourceCandidate {
			resourceKeys = Set.copyOf(resourceKeys);
		}
	}

	private final HouseholdEscortBindingCatalog catalog;
	private final Scenario scenario;
	private final ActivityFacilities facilities;
	private final Provider<TripRouter> tripRouterProvider;
	private final SwissRailRaptor physicalPtRouter;
	private final TravelTime carTravelTime;
	private final HongKongDynamicCarCostRules costRules;
	private final HongKongPtFareRuntimeCatalog ptFareCatalog;
	private final HongKongTaxiFareCalculator taxiFareCalculator;
	private final HongKongTaxiScoringParameters taxiParameters;
	private final Config config;
	private final double qsimEndTimeS;
	private boolean applied;

	@Inject
	public HouseholdEscortMaxUtilitySelector(
			HouseholdEscortBindingCatalog catalog,
			Scenario scenario,
			ActivityFacilities facilities,
			Provider<TripRouter> tripRouterProvider,
			SwissRailRaptor physicalPtRouter,
			@Named(TransportMode.car) TravelTime carTravelTime,
			HongKongDynamicCarCostRules costRules,
			HongKongPtFareRuntimeCatalog ptFareCatalog,
			HongKongTaxiFareCalculator taxiFareCalculator,
			Config config) {
		this.catalog = catalog;
		this.scenario = scenario;
		this.facilities = facilities;
		this.tripRouterProvider = tripRouterProvider;
		this.physicalPtRouter = physicalPtRouter;
		this.carTravelTime = carTravelTime;
		this.costRules = costRules;
		this.ptFareCatalog = ptFareCatalog;
		this.taxiFareCalculator = taxiFareCalculator;
		this.taxiParameters = HongKongTaxiScoringParameters.centralV1();
		this.config = config;
		this.qsimEndTimeS = config.qsim().getEndTime().orElse(30.0 * 3_600.0);
	}

	@Override
	public void notifyStartup(StartupEvent event) {
		if (applied) {
			throw new IllegalStateException("Household maximum-utility selector may run only once.");
		}
		TripRouter router = tripRouterProvider.get();
		List<EvaluatedBundle> evaluatedBundles = new ArrayList<>();
		int unavailablePtCandidates = 0;
		int generatedWaypointLegs = 0;
		int infeasibleBoundHouseholds = 0;

		for (var entry : catalog.candidateGroups().entrySet()) {
			List<HouseholdEscortBindingCatalog.Binding> bindings = entry.getValue().stream()
					.sorted(Comparator.comparingInt(HouseholdEscortBindingCatalog.Binding::passengerLegIndex))
					.toList();
			Id<Person> passengerId = bindings.getFirst().passengerId();
			String householdId = bindings.getFirst().householdId();
			if (bindings.stream().anyMatch(binding -> !binding.passengerId().equals(passengerId)
					|| !binding.householdId().equals(householdId))) {
				throw new IllegalStateException("Candidate group mixes passengers or households: " + entry.getKey());
			}
			Person passenger = requiredPerson(passengerId);

			double boundUtility = 0.0;
			double unboundUtility = 0.0;
			List<WaypointCandidate> waypointCandidates = new ArrayList<>();
			List<PlanTrip> passengerTrips = new ArrayList<>();
			List<PassengerModeCandidate> unboundModeCandidates = new ArrayList<>();
			boolean boundScheduleFeasible = true;
			for (HouseholdEscortBindingCatalog.Binding binding : bindings) {
				Person driver = requiredPerson(binding.driverId());
				PlanTrip passengerTrip = selectedTrip(passenger, binding.passengerLegIndex());
				passengerTrips.add(passengerTrip);
				PlanTrip driverTrip = selectedTrip(driver, binding.driverLegIndex());
				NetworkRoute original = copyRoute(requiredDriverRoute(driverTrip.leg(), binding));
				RouteMetric unboundRoute = evaluate(
						original, binding.driverPlannedDepartureTimeSeconds(), driver,
						driverTrip, binding.vehicleId());
				WaypointCandidate waypoint = buildWaypointCandidate(
						router, binding, driver, driverTrip, passengerTrip);
				waypointCandidates.add(waypoint);
				boundScheduleFeasible &= waypoint.scheduleFeasible();
				generatedWaypointLegs++;

				PassengerModeCandidate ptCandidate = buildPtCandidate(
						passenger, passengerTrip, binding.passengerLegIndex(),
						binding.passengerPlannedDepartureTimeSeconds());
				PassengerModeCandidate taxiCandidate = buildTaxiCandidate(
						router, passenger, passengerTrip, binding.passengerLegIndex(),
						binding.passengerPlannedDepartureTimeSeconds());
				PassengerModeCandidate walkCandidate = buildWalkCandidate(
						router, passenger, passengerTrip, binding.passengerLegIndex(),
						binding.passengerPlannedDepartureTimeSeconds());
				if (!ptCandidate.available()) unavailablePtCandidates++;
				PassengerModeCandidate unboundMode = bestUnboundMode(
						ptCandidate, taxiCandidate, walkCandidate);
				unboundModeCandidates.add(unboundMode);
				double boundPassengerTime = waypoint.passengerArrivalTimeS()
						- binding.passengerPlannedDepartureTimeSeconds();
				if (boundPassengerTime < 0.0) {
					boundScheduleFeasible = false;
				}
				LOG.info("HK_HOUSEHOLD_ESCORT_REAL_MODE_CANDIDATE candidate_group={} household={} "
						+ "new_candidate={} passenger={} passenger_leg={} "
						+ "pt_available={} pt_utility={} pt_time_s={} pt_fare_hkd={} "
						+ "pt_unresolved_fare_segments={} "
						+ "taxi_utility={} taxi_time_s={} taxi_fare_hkd={} "
						+ "walk_utility={} walk_time_s={} selected_mode={}",
						binding.candidateGroupId(), binding.householdId(), binding.newCandidate(),
						binding.passengerId(), binding.passengerLegIndex(), ptCandidate.available(),
						ptCandidate.utility(), ptCandidate.travelTimeS(), ptCandidate.fareHkd(),
						ptCandidate.unresolvedFareSegments(), taxiCandidate.utility(),
						taxiCandidate.travelTimeS(), taxiCandidate.fareHkd(),
						walkCandidate.utility(), walkCandidate.travelTimeS(), unboundMode.mode());
				unboundUtility += unboundRoute.driverUtility() + unboundMode.utility();
				boundUtility += waypoint.metric().driverUtility()
						+ passengerUtility(Math.max(0.0, boundPassengerTime));
			}
			if (!boundScheduleFeasible) infeasibleBoundHouseholds++;
			evaluatedBundles.add(new EvaluatedBundle(
					entry.getKey(), householdId, passenger, bindings, passengerTrips,
					unboundModeCandidates, waypointCandidates, boundUtility, unboundUtility,
					boundScheduleFeasible, bindings.stream().anyMatch(
							HouseholdEscortBindingCatalog.Binding::newCandidate)));
		}

		Map<String, List<EvaluatedBundle>> byHousehold = new LinkedHashMap<>();
		for (EvaluatedBundle bundle : evaluatedBundles) {
			byHousehold.computeIfAbsent(bundle.householdId(), ignored -> new ArrayList<>()).add(bundle);
		}
		Set<String> selectedBoundIds = new LinkedHashSet<>();
		for (List<EvaluatedBundle> householdBundles : byHousehold.values()) {
			selectedBoundIds.addAll(bestCompatibleSelection(householdBundles));
		}

		int selectedBound = 0;
		int selectedUnbound = 0;
		int selectedBoundLegs = 0;
		int selectedUnboundLegs = 0;
		int selectedUnboundPtLegs = 0;
		int selectedUnboundTaxiLegs = 0;
		int selectedUnboundWalkLegs = 0;
		int selectedNewBound = 0;
		int selectedNewUnbound = 0;
		int resourceConflictUnbound = 0;
		double totalBoundUtility = 0.0;
		double totalUnboundUtility = 0.0;
		double minimumDelta = Double.POSITIVE_INFINITY;
		double maximumDelta = Double.NEGATIVE_INFINITY;
		for (EvaluatedBundle bundle : evaluatedBundles) {
			boolean chooseBound = selectedBoundIds.contains(bundle.candidateGroupId());
			catalog.setCandidateGroupBound(bundle.candidateGroupId(), chooseBound);
			Person passenger = bundle.passenger();
			passenger.getAttributes().putAttribute("hkHouseholdEscortSelection",
					chooseBound ? "bound" : "unbound_real_mode");
			passenger.getAttributes().putAttribute("hkHouseholdEscortCandidateGroupId",
					bundle.candidateGroupId());
			passenger.getAttributes().putAttribute("hkHouseholdEscortNewCandidate", bundle.newCandidate());
			passenger.getAttributes().putAttribute("hkHouseholdEscortBoundMinusUnboundUtility", bundle.delta());
			passenger.getAttributes().putAttribute("hkHouseholdEscortUnboundLegModes",
					String.join(",", bundle.unboundModeCandidates().stream()
							.map(PassengerModeCandidate::mode).toList()));
			LOG.info("HK_HOUSEHOLD_ESCORT_SELECTION candidate_group={} household={} passenger={} "
					+ "new_candidate={} candidate_legs={} choice={} "
					+ "bound_minus_unbound_utility={} schedule_feasible={}",
					bundle.candidateGroupId(), bundle.householdId(), passenger.getId(),
					bundle.newCandidate(), bundle.bindings().size(),
					chooseBound ? "bound" : "unbound", bundle.delta(), bundle.scheduleFeasible());
			if (chooseBound) {
				selectedBound++;
				selectedBoundLegs += bundle.bindings().size();
				if (bundle.newCandidate()) selectedNewBound++;
				for (int index = 0; index < bundle.bindings().size(); index++) {
					var binding = bundle.bindings().get(index);
					binding.passengerLeg().getAttributes().putAttribute(
							HouseholdEscortBindingCatalog.BINDING_KEY_ATTRIBUTE,
							HouseholdEscortBindingCatalog.bindingKey(binding));
					installRoute(binding, bundle.waypointCandidates().get(index).metric());
				}
			} else {
				selectedUnbound++;
				selectedUnboundLegs += bundle.bindings().size();
				if (bundle.newCandidate()) selectedNewUnbound++;
				if (bundle.scheduleFeasible() && bundle.delta() >= 0.0) resourceConflictUnbound++;
				installUnboundTrips(passenger, bundle.passengerTrips(), bundle.unboundModeCandidates());
				selectedUnboundPtLegs += bundle.unboundModeCandidates().stream()
						.filter(candidate -> TransportMode.pt.equals(candidate.mode())).count();
				selectedUnboundTaxiLegs += bundle.unboundModeCandidates().stream()
						.filter(candidate -> HongKongTaxiScoringParameters.TAXI_MODE.equals(candidate.mode())).count();
				selectedUnboundWalkLegs += bundle.unboundModeCandidates().stream()
						.filter(candidate -> TransportMode.walk.equals(candidate.mode())).count();
			}
			totalBoundUtility += bundle.boundUtility();
			totalUnboundUtility += bundle.unboundUtility();
			minimumDelta = Math.min(minimumDelta, bundle.delta());
			maximumDelta = Math.max(maximumDelta, bundle.delta());
		}
		Map<Id<Person>, List<EvaluatedBundle>> bundlesByPassenger = new LinkedHashMap<>();
		for (EvaluatedBundle bundle : evaluatedBundles) {
			bundlesByPassenger.computeIfAbsent(bundle.passenger().getId(), ignored -> new ArrayList<>())
					.add(bundle);
		}
		for (List<EvaluatedBundle> passengerBundles : bundlesByPassenger.values()) {
			passengerBundles.sort(Comparator.comparingInt(bundle -> bundle.bindings().stream()
					.mapToInt(HouseholdEscortBindingCatalog.Binding::passengerLegIndex).min().orElseThrow()));
			Person passenger = passengerBundles.getFirst().passenger();
			long boundCount = passengerBundles.stream()
					.filter(bundle -> selectedBoundIds.contains(bundle.candidateGroupId())).count();
			String aggregateSelection = boundCount == passengerBundles.size()
					? "bound"
					: (boundCount == 0 ? "unbound_real_mode" : "mixed");
			passenger.getAttributes().putAttribute("hkHouseholdEscortSelection", aggregateSelection);
			passenger.getAttributes().putAttribute("hkHouseholdEscortCandidateGroupId",
					String.join(",", passengerBundles.stream()
							.map(EvaluatedBundle::candidateGroupId).toList()));
			passenger.getAttributes().putAttribute("hkHouseholdEscortNewCandidate",
					passengerBundles.stream().anyMatch(EvaluatedBundle::newCandidate));
			passenger.getAttributes().putAttribute("hkHouseholdEscortBoundMinusUnboundUtility",
					passengerBundles.stream().mapToDouble(EvaluatedBundle::delta).sum());
			List<String> legSelections = new ArrayList<>();
			List<String> unboundModes = new ArrayList<>();
			for (EvaluatedBundle bundle : passengerBundles) {
				String choice = selectedBoundIds.contains(bundle.candidateGroupId()) ? "bound" : "unbound";
				for (int index = 0; index < bundle.bindings().size(); index++) {
					int legIndex = bundle.bindings().get(index).passengerLegIndex();
					legSelections.add(legIndex + ":" + choice);
					unboundModes.add(legIndex + ":" + bundle.unboundModeCandidates().get(index).mode());
				}
			}
			passenger.getAttributes().putAttribute("hkHouseholdEscortLegSelections",
					String.join(",", legSelections));
			passenger.getAttributes().putAttribute("hkHouseholdEscortUnboundLegModes",
					String.join(",", unboundModes));
		}
		applied = true;
		long newCandidateBundles = evaluatedBundles.stream().filter(EvaluatedBundle::newCandidate).count();
		LOG.info("Household escort maximum-utility selector: candidate_bundles={}, alternatives_per_candidate=2, "
				+ "selected_bound={}, selected_unbound={}, active_bindings={}, generated_waypoint_legs={}, "
				+ "infeasible_bound_households={}, selected_unbound_pt_legs={}, "
				+ "selected_unbound_taxi_legs={}, selected_unbound_walk_legs={}, "
				+ "selected_unbound_car_passenger_legs=0, "
				+ "unavailable_physical_pt_candidates={}, candidate_households={}, candidate_legs={}, "
				+ "new_candidate_bundles={}, selected_new_bound_bundles={}, "
				+ "selected_new_unbound_bundles={}, selected_bound_legs={}, selected_unbound_legs={}, "
				+ "resource_conflict_unbound_bundles={}, "
				+ "total_bound_utility={}, total_unbound_utility={}, minimum_bound_minus_unbound={}, "
				+ "maximum_bound_minus_unbound={}, probability_choice=false, driver_constraint=false, "
				+ "new_joint_pairs={}",
				evaluatedBundles.size(), selectedBound, selectedUnbound, catalog.activeBindingCount(),
				generatedWaypointLegs, infeasibleBoundHouseholds,
				selectedUnboundPtLegs, selectedUnboundTaxiLegs, selectedUnboundWalkLegs,
				unavailablePtCandidates,
				byHousehold.size(), catalog.bindings().size(), newCandidateBundles,
				selectedNewBound, selectedNewUnbound, selectedBoundLegs, selectedUnboundLegs,
				resourceConflictUnbound,
				totalBoundUtility, totalUnboundUtility, minimumDelta, maximumDelta,
				selectedNewBound);
	}

	private static Set<String> bestCompatibleSelection(List<EvaluatedBundle> householdBundles) {
		List<ResourceCandidate> eligible = householdBundles.stream()
				.filter(EvaluatedBundle::scheduleFeasible)
				.filter(bundle -> bundle.delta() >= 0.0)
				.map(bundle -> new ResourceCandidate(
						bundle.candidateGroupId(), bundle.delta(), bundle.resourceKeys()))
				.toList();
		return selectCompatibleCandidateIds(eligible);
	}

	static Set<String> selectCompatibleCandidateIds(List<ResourceCandidate> candidates) {
		List<ResourceCandidate> eligible = candidates.stream()
				.filter(candidate -> candidate.delta() >= 0.0)
				.sorted(Comparator.comparing(ResourceCandidate::candidateId))
				.toList();
		if (eligible.size() > 20) {
			throw new IllegalStateException("Household candidate set is too large for exact selection: "
					+ eligible.size());
		}
		BestSelection best = new BestSelection();
		searchCompatibleSelection(eligible, 0, new HashSet<>(), new ArrayList<>(), 0.0, best);
		return new LinkedHashSet<>(best.candidateIds);
	}

	private static void searchCompatibleSelection(
			List<ResourceCandidate> eligible,
			int index,
			Set<String> usedResources,
			List<String> chosen,
			double delta,
			BestSelection best) {
		if (index == eligible.size()) {
			if (betterSelection(delta, chosen, best)) {
				best.delta = delta;
				best.candidateIds = List.copyOf(chosen);
			}
			return;
		}
		searchCompatibleSelection(eligible, index + 1, usedResources, chosen, delta, best);
		ResourceCandidate candidate = eligible.get(index);
		Set<String> resources = candidate.resourceKeys();
		if (resources.stream().anyMatch(usedResources::contains)) return;
		usedResources.addAll(resources);
		chosen.add(candidate.candidateId());
		searchCompatibleSelection(
				eligible, index + 1, usedResources, chosen, delta + candidate.delta(), best);
		chosen.removeLast();
		usedResources.removeAll(resources);
	}

	private static boolean betterSelection(double delta, List<String> chosen, BestSelection best) {
		if (delta > best.delta + 1e-9) return true;
		if (Math.abs(delta - best.delta) > 1e-9) return false;
		if (chosen.size() != best.candidateIds.size()) {
			return chosen.size() > best.candidateIds.size();
		}
		return String.join("\n", chosen).compareTo(String.join("\n", best.candidateIds)) < 0;
	}

	private PassengerModeCandidate buildPtCandidate(
			Person passenger,
			PlanTrip passengerTrip,
			int passengerLegIndex,
			double departureTimeS) {
		List<? extends PlanElement> routed = physicalPtRouter.calcRoute(
				DefaultRoutingRequest.of(
				FacilitiesUtils.toFacility(passengerTrip.origin(), facilities),
				FacilitiesUtils.toFacility(passengerTrip.destination(), facilities),
				departureTimeS,
				passenger,
				passengerTrip.leg().getAttributes()));
		if (routed == null || routed.isEmpty()) {
			return unavailablePtCandidate();
		}
		List<PlanElement> trip = new ArrayList<>(routed);
		for (PlanElement element : trip) {
			if (element instanceof Leg leg) {
				leg.setRoutingMode(TransportMode.pt);
				setReleasedModeAttributes(leg.getAttributes(), TransportMode.pt, passengerLegIndex);
			}
		}
		int ptLegs = 0;
		int unresolvedSegments = 0;
		double fareHkd = 0.0;
		for (PlanElement element : trip) {
			if (!(element instanceof Leg leg) || !TransportMode.pt.equals(leg.getMode())) continue;
			ptLegs++;
			if (!(leg.getRoute() instanceof TransitPassengerRoute first)) {
				LOG.warn("Physical PT candidate unavailable for passenger={}: leg_mode={}, "
						+ "routing_mode={}, route_class={}, route={}",
						passenger.getId(), leg.getMode(), leg.getRoutingMode(),
						leg.getRoute() == null ? "<null>" : leg.getRoute().getClass().getName(),
						String.valueOf(leg.getRoute()));
				return unavailablePtCandidate();
			}
			Set<TransitPassengerRoute> visited = Collections.newSetFromMap(new IdentityHashMap<>());
			TransitPassengerRoute current = first;
			while (current != null) {
				if (!visited.add(current)) {
					throw new IllegalStateException("Unbound PT candidate has a chained-route cycle: "
							+ passenger.getId());
				}
				HongKongPtFareRuntimeCatalog.FareQuote quote =
						ptFareCatalog.quote(current, scenario.getTransitSchedule());
				if (quote.resolved()) fareHkd += quote.costHkd();
				else unresolvedSegments++;
				current = current.getChainedRoute();
			}
		}
		if (ptLegs == 0) {
			return unavailablePtCandidate();
		}
		double utility = standardTripUtility(trip)
				- fareHkd * config.scoring().getMarginalUtilityOfMoney();
		return new PassengerModeCandidate(
				TransportMode.pt, trip, utility, tripTravelTime(trip), fareHkd,
				unresolvedSegments, true);
	}

	private static PassengerModeCandidate unavailablePtCandidate() {
		return new PassengerModeCandidate(
				TransportMode.pt, List.of(), Double.NEGATIVE_INFINITY,
				Double.NaN, 0.0, 0, false);
	}

	private PassengerModeCandidate buildTaxiCandidate(
			TripRouter router,
			Person passenger,
			PlanTrip passengerTrip,
			int passengerLegIndex,
			double departureTimeS) {
		AttributesImpl requestAttributes = copyAttributes(passengerTrip.leg().getAttributes());
		setTaxiAttributes(requestAttributes, 0.0, passengerLegIndex);
		List<? extends PlanElement> routed = router.calcRoute(
				HongKongTaxiScoringParameters.TAXI_MODE,
				FacilitiesUtils.toFacility(passengerTrip.origin(), facilities),
				FacilitiesUtils.toFacility(passengerTrip.destination(), facilities),
				departureTimeS,
				passenger,
				requestAttributes);
		List<PlanElement> trip = new ArrayList<>(routed);
		List<Leg> taxiLegs = trip.stream()
				.filter(Leg.class::isInstance)
				.map(Leg.class::cast)
				.filter(leg -> HongKongTaxiScoringParameters.TAXI_MODE.equals(leg.getMode()))
				.toList();
		if (taxiLegs.size() != 1 || taxiLegs.getFirst().getRoute() == null) {
			throw new IllegalStateException("Unbound Taxi candidate must contain one routed Taxi leg: "
					+ passenger.getId() + "/" + passengerLegIndex);
		}
		Leg taxiLeg = taxiLegs.getFirst();
		double distance = taxiLeg.getRoute().getDistance();
		if (!Double.isFinite(distance) || distance < 0.0) {
			throw new IllegalStateException("Unbound Taxi route has invalid distance: "
					+ passenger.getId() + "/" + passengerLegIndex);
		}
		double fareHkd = taxiFareCalculator.calculate(
				distance, HongKongTaxiFareCalculator.UNRESOLVED).fareHkd();
		setTaxiAttributes(taxiLeg.getAttributes(), fareHkd, passengerLegIndex);
		setReleasedModeAttributes(
				taxiLeg.getAttributes(), HongKongTaxiScoringParameters.TAXI_MODE, passengerLegIndex);
		double utility = standardTripUtility(trip) + taxiParameters.fareScore(fareHkd);
		return new PassengerModeCandidate(
				HongKongTaxiScoringParameters.TAXI_MODE,
				trip, utility, tripTravelTime(trip), fareHkd, 0, true);
	}

	private PassengerModeCandidate buildWalkCandidate(
			TripRouter router,
			Person passenger,
			PlanTrip passengerTrip,
			int passengerLegIndex,
			double departureTimeS) {
		List<? extends PlanElement> routed = router.calcRoute(
				TransportMode.walk,
				FacilitiesUtils.toFacility(passengerTrip.origin(), facilities),
				FacilitiesUtils.toFacility(passengerTrip.destination(), facilities),
				departureTimeS,
				passenger,
				passengerTrip.leg().getAttributes());
		List<PlanElement> trip = new ArrayList<>(routed);
		List<Leg> legs = trip.stream()
				.filter(Leg.class::isInstance)
				.map(Leg.class::cast)
				.toList();
		if (legs.isEmpty() || legs.stream().anyMatch(leg -> !TransportMode.walk.equals(leg.getMode()))) {
			throw new IllegalStateException("Unbound Walk candidate must contain only Walk legs: "
					+ passenger.getId() + "/" + passengerLegIndex);
		}
		for (Leg leg : legs) {
			leg.setRoutingMode(TransportMode.walk);
			setReleasedModeAttributes(leg.getAttributes(), TransportMode.walk, passengerLegIndex);
		}
		return new PassengerModeCandidate(
				TransportMode.walk, trip, standardTripUtility(trip),
				tripTravelTime(trip), 0.0, 0, true);
	}

	private static PassengerModeCandidate bestUnboundMode(
			PassengerModeCandidate pt,
			PassengerModeCandidate taxi,
			PassengerModeCandidate walk) {
		List<PassengerModeCandidate> candidates = List.of(pt, taxi, walk);
		return candidates.stream()
				.filter(PassengerModeCandidate::available)
				.max(Comparator.comparingDouble(PassengerModeCandidate::utility)
						.thenComparingInt(candidate -> unboundModeTiePriority(candidate.mode())))
				.orElseThrow(() -> new IllegalStateException("No available unbound passenger mode."));
	}

	private static int unboundModeTiePriority(String mode) {
		return switch (mode) {
			case TransportMode.pt -> 3;
			case HongKongTaxiScoringParameters.TAXI_MODE -> 2;
			case TransportMode.walk -> 1;
			default -> throw new IllegalArgumentException("Unsupported unbound passenger mode " + mode);
		};
	}

	private double standardTripUtility(List<PlanElement> trip) {
		double utility = 0.0;
		for (PlanElement element : trip) {
			if (!(element instanceof Leg leg)) continue;
			ScoringConfigGroup.ModeParams params = config.scoring().getModes().get(leg.getMode());
			if (params == null) {
				throw new IllegalStateException("Missing scoring parameters for candidate mode "
						+ leg.getMode());
			}
			if (params.getDailyMonetaryConstant() != 0.0 || params.getDailyUtilityConstant() != 0.0) {
				throw new IllegalStateException("Household real-mode candidate requires zero daily "
						+ "constants for mode " + leg.getMode());
			}
			double travelTimeS = requiredTravelTime(leg);
			double distanceM = leg.getRoute() == null ? Double.NaN : leg.getRoute().getDistance();
			double distanceCoefficient = params.getMarginalUtilityOfDistance()
					+ config.scoring().getMarginalUtilityOfMoney() * params.getMonetaryDistanceRate();
			if (!Double.isFinite(distanceM)) {
				if (distanceCoefficient != 0.0) {
					throw new IllegalStateException("Candidate route lacks distance for scored mode "
							+ leg.getMode());
				}
				distanceM = 0.0;
			}
			utility += params.getConstant()
					+ params.getMarginalUtilityOfTraveling() * travelTimeS / 3_600.0
					+ distanceCoefficient * distanceM;
		}
		if (!Double.isFinite(utility)) {
			throw new IllegalStateException("Household real-mode candidate utility is non-finite.");
		}
		return utility;
	}

	private static double tripTravelTime(List<PlanElement> trip) {
		double travelTimeS = trip.stream()
				.filter(Leg.class::isInstance)
				.map(Leg.class::cast)
				.mapToDouble(HouseholdEscortMaxUtilitySelector::requiredTravelTime)
				.sum();
		if (!Double.isFinite(travelTimeS) || travelTimeS < 0.0) {
			throw new IllegalStateException("Household real-mode candidate travel time is invalid.");
		}
		return travelTimeS;
	}

	private static double requiredTravelTime(Leg leg) {
		if (leg.getTravelTime().isDefined()) return leg.getTravelTime().seconds();
		if (leg.getRoute() != null && leg.getRoute().getTravelTime().isDefined()) {
			return leg.getRoute().getTravelTime().seconds();
		}
		throw new IllegalStateException("Candidate leg lacks travel time for mode " + leg.getMode());
	}

	private static AttributesImpl copyAttributes(Attributes source) {
		AttributesImpl copy = new AttributesImpl();
		for (Map.Entry<String, Object> entry : source.getAsMap().entrySet()) {
			copy.putAttribute(entry.getKey(), entry.getValue());
		}
		return copy;
	}

	private void setTaxiAttributes(Attributes attributes, double fareHkd, int passengerLegIndex) {
		for (String name : HongKongTaxiLegAttributes.NAMES) attributes.removeAttribute(name);
		attributes.putAttribute(HongKongTaxiLegAttributes.FARE_BASELINE_HKD, fareHkd);
		attributes.putAttribute(HongKongTaxiLegAttributes.TAXI_TYPE,
				HongKongTaxiFareCalculator.UNRESOLVED);
		attributes.putAttribute(HongKongTaxiLegAttributes.FARE_SCOPE, taxiParameters.fareScope());
		attributes.putAttribute(HongKongTaxiLegAttributes.FARE_MODEL_VERSION,
				taxiParameters.fareModelVersion());
		attributes.putAttribute(HongKongTaxiLegAttributes.CLASSIFICATION_SOURCE,
				"household_unbind_real_mode_max_utility_v1");
		attributes.putAttribute(HongKongTaxiLegAttributes.MAIN_TRIP_INDEX, passengerLegIndex);
	}

	private static void setReleasedModeAttributes(
			Attributes attributes, String mode, int passengerLegIndex) {
		attributes.putAttribute(RELEASED_MODE_ATTRIBUTE, mode);
		attributes.putAttribute(RELEASED_LEG_INDEX_ATTRIBUTE, passengerLegIndex);
	}

	private static void installUnboundTrips(
			Person passenger,
			List<PlanTrip> passengerTrips,
			List<PassengerModeCandidate> candidates) {
		if (passengerTrips.size() != candidates.size()) {
			throw new IllegalArgumentException("Unbound trip and candidate counts differ.");
		}
		List<Integer> indexes = new ArrayList<>();
		for (int index = 0; index < passengerTrips.size(); index++) indexes.add(index);
		indexes.sort(Comparator.comparingInt(
				(Integer index) -> passengerTrips.get(index).elementIndex()).reversed());
		for (int index : indexes) {
			PlanTrip trip = passengerTrips.get(index);
			PassengerModeCandidate candidate = candidates.get(index);
			if (candidate.trip().stream()
					.filter(Leg.class::isInstance)
					.map(Leg.class::cast)
					.anyMatch(leg -> TransportMode.car.equals(leg.getMode()))) {
				throw new IllegalStateException("Unbound passenger candidate illegally contains Car: "
						+ passenger.getId());
			}
			TripRouter.insertTrip(
					passenger.getSelectedPlan(), trip.origin(), candidate.trip(), trip.destination());
			if (HongKongTaxiScoringParameters.TAXI_MODE.equals(candidate.mode())) {
				Leg taxiLeg = candidate.trip().stream()
						.filter(Leg.class::isInstance)
						.map(Leg.class::cast)
						.filter(leg -> HongKongTaxiScoringParameters.TAXI_MODE.equals(leg.getMode()))
						.findFirst().orElseThrow();
				for (String name : HongKongTaxiLegAttributes.NAMES) {
					trip.origin().getAttributes().putAttribute(
							name, taxiLeg.getAttributes().getAttribute(name));
				}
			}
		}
	}

	private WaypointCandidate buildWaypointCandidate(
			TripRouter router,
			HouseholdEscortBindingCatalog.Binding binding,
			Person driver,
			PlanTrip driverTrip,
			PlanTrip passengerTrip) {
		double departure = binding.driverPlannedDepartureTimeSeconds();
		NetworkRoute toPickup = routeSegment(
				router, driverTrip.origin(), passengerTrip.origin(), departure, driver, driverTrip.leg());
		double pickupArrival = departure + routeTravelTime(toPickup, departure, driver, binding.vehicleId());
		NetworkRoute passengerRide = routeSegment(
				router, passengerTrip.origin(), passengerTrip.destination(), pickupArrival,
				driver, driverTrip.leg());
		double passengerArrival = pickupArrival
				+ routeTravelTime(passengerRide, pickupArrival, driver, binding.vehicleId());
		NetworkRoute toDriverDestination = routeSegment(
				router, passengerTrip.destination(), driverTrip.destination(), passengerArrival,
				driver, driverTrip.leg());
		NetworkRoute combined = combine(
				List.of(toPickup, passengerRide, toDriverDestination), binding.vehicleId());
		List<Id<Link>> links = fullLinkSequence(combined);
		if (!links.contains(binding.passengerPickupLinkId())
				|| !links.contains(binding.passengerDropoffLinkId())) {
			throw new IllegalStateException("Combined route omits a passenger waypoint: "
					+ binding.passengerId() + "/" + binding.passengerLegIndex());
		}
		RouteMetric metric = evaluate(
				combined, departure, driver, driverTrip, binding.vehicleId());
		double nextEntry = nextCarDeparture(driver.getSelectedPlan(), driverTrip.elementIndex());
		boolean passengerReadyAtPickup = pickupArrival + 1e-9
				>= binding.passengerPlannedDepartureTimeSeconds();
		return new WaypointCandidate(
				metric, pickupArrival, passengerArrival,
				passengerReadyAtPickup && metric.arrivalTimeS() <= nextEntry);
	}

	private RouteMetric evaluate(
			NetworkRoute route,
			double departureTimeS,
			Person driver,
			PlanTrip driverTrip,
			Id<Vehicle> vehicleId) {
		Vehicle vehicle = scenario.getVehicles().getVehicles().get(vehicleId);
		double travelTimeS = routeTravelTime(route, departureTimeS, driver, vehicleId);
		var routeCost = costRules.quoteNetworkRoute(
				route, departureTimeS, carTravelTime, driver, vehicle);
		double arrival = departureTimeS + travelTimeS;
		Activity parkingActivity = parkingActivity(driver.getSelectedPlan(), driverTrip.elementIndex());
		if (parkingActivity.getFacilityId() == null) {
			throw new IllegalStateException("Driver destination has no parking facility: " + driver.getId());
		}
		double nextEntry = nextCarDeparture(driver.getSelectedPlan(), driverTrip.elementIndex());
		double parking = costRules.quoteParking(
				parkingActivity.getFacilityId().toString(),
				parkingActivity.getType(), arrival, Math.max(arrival, nextEntry)).costHkd();
		return new RouteMetric(
				route, travelTimeS, arrival, routeCost.energyHkd(), routeCost.tollHkd(), parking);
	}

	private double routeTravelTime(
			NetworkRoute route,
			double departureTimeS,
			Person driver,
			Id<Vehicle> vehicleId) {
		Vehicle vehicle = scenario.getVehicles().getVehicles().get(vehicleId);
		double time = departureTimeS;
		for (Id<Link> linkId : enteredLinkSequence(route)) {
			Link link = scenario.getNetwork().getLinks().get(linkId);
			if (link == null) throw new IllegalStateException("Route references missing link " + linkId);
			double seconds = carTravelTime.getLinkTravelTime(link, time, driver, vehicle);
			if (!Double.isFinite(seconds) || seconds < 0.0) {
				throw new IllegalStateException("Invalid Car TravelTime on " + linkId);
			}
			time += seconds;
		}
		return time - departureTimeS;
	}

	private NetworkRoute routeSegment(
			TripRouter router,
			Activity origin,
			Activity destination,
			double departureTimeS,
			Person driver,
			Leg attributesFrom) {
		List<? extends PlanElement> routed = router.calcRoute(
				TransportMode.car,
				FacilitiesUtils.toFacility(origin, facilities),
				FacilitiesUtils.toFacility(destination, facilities),
				departureTimeS,
				driver,
				attributesFrom.getAttributes());
		List<Leg> carLegs = routed.stream()
				.filter(Leg.class::isInstance)
				.map(Leg.class::cast)
				.filter(leg -> TransportMode.car.equals(leg.getMode()))
				.toList();
		if (carLegs.size() != 1 || !(carLegs.getFirst().getRoute() instanceof NetworkRoute route)) {
			throw new IllegalStateException("Waypoint routing did not return one NetworkRoute for " + driver.getId());
		}
		return route;
	}

	static NetworkRoute combine(List<NetworkRoute> segments, Id<Vehicle> vehicleId) {
		List<Id<Link>> full = new ArrayList<>();
		for (NetworkRoute segment : segments) {
			for (Id<Link> linkId : fullLinkSequence(segment)) {
				if (full.isEmpty() || !full.getLast().equals(linkId)) full.add(linkId);
			}
		}
		if (full.isEmpty()) throw new IllegalArgumentException("Cannot combine empty waypoint routes.");
		Id<Link> start = full.getFirst();
		Id<Link> end = full.getLast();
		List<Id<Link>> intermediate = full.size() <= 2
				? List.of() : new ArrayList<>(full.subList(1, full.size() - 1));
		NetworkRoute result = RouteUtils.createLinkNetworkRouteImpl(start, intermediate, end);
		result.setVehicleId(vehicleId);
		return result;
	}

	private void installRoute(
			HouseholdEscortBindingCatalog.Binding binding,
			RouteMetric metric) {
		NetworkRoute route = metric.route();
		route.setTravelTime(metric.travelTimeS());
		route.setDistance(fullLinkSequence(route).stream()
				.map(scenario.getNetwork().getLinks()::get)
				.mapToDouble(Link::getLength).sum());
		binding.driverLeg().setRoute(route);
		binding.driverLeg().setTravelTime(metric.travelTimeS());
	}

	private static double passengerUtility(double travelTimeS) {
		if (!Double.isFinite(travelTimeS) || travelTimeS < 0.0) {
			throw new IllegalArgumentException("Passenger travel time must be finite and nonnegative.");
		}
		return PASSENGER_CONSTANT + TRAVEL_UTILITY_PER_HOUR * travelTimeS / 3_600.0;
	}

	private double nextCarDeparture(Plan plan, int afterElementIndex) {
		List<PlanElement> elements = plan.getPlanElements();
		for (int index = afterElementIndex + 1; index < elements.size(); index++) {
			if (elements.get(index) instanceof Leg leg && TransportMode.car.equals(leg.getMode())
					&& leg.getDepartureTime().isDefined()) {
				return leg.getDepartureTime().seconds();
			}
		}
		return qsimEndTimeS;
	}

	private static Activity parkingActivity(Plan plan, int afterElementIndex) {
		List<PlanElement> elements = plan.getPlanElements();
		for (int index = afterElementIndex + 1; index < elements.size(); index++) {
			PlanElement element = elements.get(index);
			if (element instanceof Leg leg && TransportMode.car.equals(leg.getMode())) break;
			if (element instanceof Activity activity
					&& !activity.getType().endsWith("interaction")) {
				return activity;
			}
		}
		throw new IllegalStateException("Car leg has no downstream non-interaction parking activity.");
	}

	private Person requiredPerson(Id<Person> personId) {
		Person person = scenario.getPopulation().getPersons().get(personId);
		if (person == null || person.getSelectedPlan() == null) {
			throw new IllegalStateException("Selector person or selected plan is absent: " + personId);
		}
		return person;
	}

	private static PlanTrip selectedTrip(Person person, int requestedLegIndex) {
		List<PlanElement> elements = person.getSelectedPlan().getPlanElements();
		int legIndex = 0;
		for (int index = 0; index < elements.size(); index++) {
			if (!(elements.get(index) instanceof Leg leg)) continue;
			if (legIndex++ != requestedLegIndex) continue;
			if (index == 0 || index + 1 >= elements.size()
					|| !(elements.get(index - 1) instanceof Activity origin)
					|| !(elements.get(index + 1) instanceof Activity destination)) {
				throw new IllegalStateException("Selected leg lacks adjacent activities: " + person.getId());
			}
			return new PlanTrip(leg, origin, destination, index);
		}
		throw new IllegalStateException("Selected leg is absent: " + person.getId() + "/" + requestedLegIndex);
	}

	private static NetworkRoute requiredDriverRoute(
			Leg leg, HouseholdEscortBindingCatalog.Binding binding) {
		if (!TransportMode.car.equals(leg.getMode()) || !(leg.getRoute() instanceof NetworkRoute route)
				|| !binding.vehicleId().equals(route.getVehicleId())) {
			throw new IllegalStateException("Unbound driver candidate is invalid: "
					+ binding.driverId() + "/" + binding.driverLegIndex());
		}
		return route;
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
		if (route.getEndLinkId() != null
				&& (result.isEmpty() || !result.getLast().equals(route.getEndLinkId()))) {
			result.add(route.getEndLinkId());
		}
		return result;
	}

	private static List<Id<Link>> enteredLinkSequence(NetworkRoute route) {
		List<Id<Link>> result = new ArrayList<>(route.getLinkIds());
		if (route.getEndLinkId() != null
				&& (result.isEmpty() || !result.getLast().equals(route.getEndLinkId()))) {
			result.add(route.getEndLinkId());
		}
		return result;
	}
}
