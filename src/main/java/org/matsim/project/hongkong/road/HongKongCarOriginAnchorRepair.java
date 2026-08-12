package org.matsim.project.hongkong.road;

import com.google.inject.Inject;
import com.google.inject.Provider;
import com.google.inject.name.Named;
import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.matsim.api.core.v01.Coord;
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
import org.matsim.core.controler.events.BeforeMobsimEvent;
import org.matsim.core.controler.listener.BeforeMobsimListener;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.population.routes.NetworkRoute;
import org.matsim.core.router.TripRouter;
import org.matsim.core.router.util.TravelTime;
import org.matsim.facilities.ActivityFacilities;
import org.matsim.facilities.ActivityFacility;
import org.matsim.facilities.FacilitiesUtils;
import org.matsim.project.hongkong.car.HongKongDynamicCarCostRules;
import org.matsim.project.hongkong.household.HouseholdEscortBindingCatalog;
import org.matsim.vehicles.Vehicle;

import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Bounded private-Car activity-link direction repair.
 *
 * <p>The event catalog identifies trips whose MATSim start link was followed
 * immediately by its exact reverse. At iteration 1 this listener evaluates the
 * current and reverse-direction anchors with the production Car router. It
 * jointly reroutes the preceding Car leg when one exists, and otherwise only
 * the departure leg. Active household waypoint legs are never rewritten.</p>
 */
public final class HongKongCarOriginAnchorRepair implements BeforeMobsimListener {

	public static final String FACILITY_PROXY_DELIMITER = "__hk_car_anchor__";
	private static final Logger LOG = LogManager.getLogger(HongKongCarOriginAnchorRepair.class);
	private static final double MAX_ACCESS_DISTANCE_M = 150.0;
	private static final double MAX_ENTRY_FREESPEED_M_S = 80.0 / 3.6;
	private static final double WALK_SPEED_M_S = 1.34;
	private static final double MAX_RAW_GENERALIZED_INCREASE_S = 300.0;
	private static final double IMMEDIATE_REVERSE_PENALTY_S = 1_800.0;
	private static final Set<Id<Link>> KNOWN_RESTRICTED_SERVICE_LINKS = Set.of(
			Id.createLinkId("road_261323_0_f"), Id.createLinkId("road_261308_0_f"));

	private record CarLegRef(
			int carOrdinal, int allLegIndex, int elementIndex, Leg leg,
			Activity origin, Activity destination) {
	}

	private record AccessWalkRef(int allLegIndex, Leg leg, Activity origin) {
	}

	private record Routed(
			NetworkRoute route, double travelTimeS, double distanceM,
			double energyHkd, double tollHkd, boolean initialReverse,
			boolean terminalReverse) {
		double generalizedSeconds(double hkdToSeconds) {
			return travelTimeS + (energyHkd + tollHkd) * hkdToSeconds;
		}
	}

	private record RoutedAccess(NetworkRoute route, double travelTimeS, double distanceM) {
	}

	private record Evaluation(
			Routed previous, RoutedAccess access, Routed next, double accessDistanceM,
			double rawGeneralizedSeconds, double objectiveSeconds) {
	}

	private final HongKongCarOriginAnchorObservationCatalog observations;
	private final HouseholdEscortBindingCatalog householdBindings;
	private final Scenario scenario;
	private final ActivityFacilities facilities;
	private final Provider<TripRouter> tripRouterProvider;
	private final TravelTime carTravelTime;
	private final HongKongDynamicCarCostRules costRules;
	private final Config config;
	private final double hkdToGeneralizedSeconds;
	private boolean applied;

	@Inject
	public HongKongCarOriginAnchorRepair(
			HongKongCarOriginAnchorObservationCatalog observations,
			HouseholdEscortBindingCatalog householdBindings,
			Scenario scenario,
			ActivityFacilities facilities,
			Provider<TripRouter> tripRouterProvider,
			@Named(TransportMode.car) TravelTime carTravelTime,
			HongKongDynamicCarCostRules costRules,
			Config config) {
		this.observations = observations;
		this.householdBindings = householdBindings;
		this.scenario = scenario;
		this.facilities = facilities;
		this.tripRouterProvider = tripRouterProvider;
		this.carTravelTime = carTravelTime;
		this.costRules = costRules;
		this.config = config;
		double travelUtilityPerHour = Math.abs(config.scoring().getModes().get(TransportMode.car)
				.getMarginalUtilityOfTraveling());
		double marginalUtilityOfMoney = config.scoring().getMarginalUtilityOfMoney();
		if (!(travelUtilityPerHour > 0.0) || !Double.isFinite(marginalUtilityOfMoney)
				|| marginalUtilityOfMoney < 0.0) {
			throw new IllegalArgumentException("Car anchor repair requires finite Car time/money utilities.");
		}
		this.hkdToGeneralizedSeconds = marginalUtilityOfMoney * 3_600.0 / travelUtilityPerHour;
	}

	@Override
	public void notifyBeforeMobsim(BeforeMobsimEvent event) {
		if (event.getIteration() != 1 || applied) return;
		TripRouter router = tripRouterProvider.get();
		Set<String> activeHouseholdLegs = activeHouseholdLegs();
		int bindingsBefore = householdBindings.activeBindingCount();
		List<Map<String, Object>> rows = new ArrayList<>(observations.observations().size());
		Map<String, Integer> statusCounts = new LinkedHashMap<>();
		int repaired = 0;
		for (var observation : observations.observations()) {
			Map<String, Object> row = baseRow(observation);
			String status;
			try {
				status = evaluateAndMaybeRepair(router, observation, activeHouseholdLegs, row);
			} catch (RuntimeException error) {
				status = "route_evaluation_failed";
				row.put("detail", concise(error));
			}
			row.put("status", status);
			if ("repaired_high_confidence".equals(status)) repaired++;
			statusCounts.merge(status, 1, Integer::sum);
			rows.add(row);
		}
		if (bindingsBefore != householdBindings.activeBindingCount()) {
			throw new IllegalStateException("Car anchor repair changed active household binding count.");
		}
		writeAudit(rows, statusCounts, repaired, bindingsBefore);
		applied = true;
		LOG.info("Private-Car origin-anchor repair: observations={}, repaired={}, statuses={}, "
				+ "active_household_bindings_preserved={}", observations.observations().size(),
				repaired, statusCounts, bindingsBefore);
	}

	private String evaluateAndMaybeRepair(
			TripRouter router,
			HongKongCarOriginAnchorObservationCatalog.Observation observation,
			Set<String> activeHouseholdLegs,
			Map<String, Object> row) {
		Person person = scenario.getPopulation().getPersons().get(observation.personId());
		if (person == null || person.getSelectedPlan() == null) return "person_or_selected_plan_missing";
		List<CarLegRef> carLegs = carLegs(person.getSelectedPlan());
		if (observation.privateCarTripOrdinal() >= carLegs.size()) return "car_trip_ordinal_missing";
		CarLegRef next = carLegs.get(observation.privateCarTripOrdinal());
		row.put("selected_plan_car_leg_index", next.carOrdinal());
		row.put("selected_plan_all_leg_index", next.allLegIndex());
		Id<Link> currentId = next.origin().getLinkId();
		if (currentId == null || !currentId.equals(observation.startLinkId())) {
			row.put("selected_origin_link_id", currentId == null ? "" : currentId);
			return "selected_plan_start_link_mismatch";
		}
		Link current = scenario.getNetwork().getLinks().get(currentId);
		Link candidate = scenario.getNetwork().getLinks().get(observation.observedReverseLinkId());
		if (current == null || candidate == null || !areExactReverse(current, candidate)) {
			return "observed_pair_not_exact_network_reverse";
		}
		row.put("candidate_link_id", candidate.getId());
		row.put("candidate_freespeed_km_h", candidate.getFreespeed() * 3.6);
		if (!candidate.getAllowedModes().contains(TransportMode.car)) return "candidate_disallows_car";
		if (KNOWN_RESTRICTED_SERVICE_LINKS.contains(candidate.getId())) return "candidate_restricted_service";
		if (candidate.getFreespeed() >= MAX_ENTRY_FREESPEED_M_S) return "candidate_expressway_or_tunnel_speed";
		if (!costRules.quoteLink(candidate, observation.vehicleEntersTrafficTimeS())
				.tollFacilityId().isBlank()) return "candidate_tolled_mainline";
		Coord activityCoord = activityCoord(next.origin(), current);
		double accessDistance = pointSegmentDistance(activityCoord, candidate);
		row.put("candidate_access_distance_m", accessDistance);
		if (accessDistance > MAX_ACCESS_DISTANCE_M) return "candidate_too_far_from_activity";

		CarLegRef previous = previousCarLeg(person.getSelectedPlan(), next);
		AccessWalkRef access = accessWalk(person.getSelectedPlan(), next);
		row.put("preceding_leg_mode", precedingLegMode(person.getSelectedPlan(), next));
		if (next.origin().getType().endsWith("interaction") && access == null) {
			return "interaction_without_walk_access";
		}
		if (touchesActiveHouseholdLeg(
				activeHouseholdLegs, person.getId(), next.allLegIndex())) {
			return "joint_binding_guarded";
		}
		if (previous == null && next.carOrdinal() > 0) {
			return "nonadjacent_prior_car_continuity_guarded";
		}
		double previousDeparture = 0.0;
		if (previous != null) {
			if (!previous.leg().getDepartureTime().isDefined()) return "previous_car_departure_undefined";
			previousDeparture = previous.leg().getDepartureTime().seconds();
		}
		double accessDeparture = 0.0;
		if (access != null) {
			if (!access.leg().getDepartureTime().isDefined()) {
				return "access_walk_departure_undefined";
			}
			accessDeparture = access.leg().getDepartureTime().seconds();
		}

		Evaluation currentEvaluation = evaluateAnchor(
				router, person, previous, access, next, current, activityCoord,
				previousDeparture, accessDeparture, observation.vehicleEntersTrafficTimeS());
		Evaluation candidateEvaluation = evaluateAnchor(
				router, person, previous, access, next, candidate, activityCoord,
				previousDeparture, accessDeparture, observation.vehicleEntersTrafficTimeS());
		putEvaluation(row, "current", currentEvaluation);
		putEvaluation(row, "candidate", candidateEvaluation);
		if (!currentEvaluation.next().initialReverse()) return "already_resolved_by_current_router";
		if (candidateEvaluation.next().initialReverse()) return "candidate_still_initially_reverses";
		if (candidateEvaluation.previous() != null
				&& candidateEvaluation.previous().terminalReverse()) {
			return "candidate_creates_previous_arrival_reverse";
		}
		if (candidateEvaluation.rawGeneralizedSeconds()
				> currentEvaluation.rawGeneralizedSeconds() + MAX_RAW_GENERALIZED_INCREASE_S) {
			return "candidate_excessive_joint_cost";
		}
		if (candidateEvaluation.objectiveSeconds() >= currentEvaluation.objectiveSeconds()) {
			return "candidate_not_lower_joint_objective";
		}

		installProxyActivityAnchor(person, next, candidate);
		installRoute(next.leg(), candidateEvaluation.next().route());
		if (previous != null) installRoute(previous.leg(), candidateEvaluation.previous().route());
		if (access != null) installWalkRoute(access.leg(), candidateEvaluation.access().route());
		return "repaired_high_confidence";
	}

	private Evaluation evaluateAnchor(
			TripRouter router, Person person, CarLegRef previous, AccessWalkRef access,
			CarLegRef next, Link anchor, Coord activityCoord, double previousDeparture,
			double accessDeparture, double nextDeparture) {
		Activity wrapped = PopulationUtils.createActivityFromCoord(next.origin().getType(), activityCoord);
		wrapped.setLinkId(anchor.getId());
		Routed previousRoute = previous == null ? null : route(
				router, person, previous.origin(), wrapped, previousDeparture,
				previous.leg(), vehicleId(previous.leg(), person));
		RoutedAccess accessRoute = access == null ? null : routeAccessWalk(
				router, person, access.origin(), wrapped, accessDeparture, access.leg());
		Routed nextRoute = route(
				router, person, wrapped, next.destination(), nextDeparture,
				next.leg(), vehicleId(next.leg(), person));
		double accessDistance = accessRoute == null
				? pointSegmentDistance(activityCoord, anchor) : accessRoute.distanceM();
		double accessTime = accessRoute == null
				? accessDistance / WALK_SPEED_M_S : accessRoute.travelTimeS();
		double raw = accessTime
				+ nextRoute.generalizedSeconds(hkdToGeneralizedSeconds)
				+ (previousRoute == null ? 0.0
				: previousRoute.generalizedSeconds(hkdToGeneralizedSeconds));
		double objective = raw + (nextRoute.initialReverse() ? IMMEDIATE_REVERSE_PENALTY_S : 0.0)
				+ (previousRoute != null && previousRoute.terminalReverse()
				? IMMEDIATE_REVERSE_PENALTY_S : 0.0);
		return new Evaluation(previousRoute, accessRoute, nextRoute, accessDistance, raw, objective);
	}

	private RoutedAccess routeAccessWalk(
			TripRouter router, Person person, Activity origin, Activity destination,
			double departure, Leg sourceLeg) {
		List<? extends PlanElement> elements = router.calcRoute(
				TransportMode.walk, FacilitiesUtils.toFacility(origin, facilities),
				FacilitiesUtils.wrapActivity(destination), departure, person,
				sourceLeg.getAttributes());
		Leg walk = elements.stream().filter(Leg.class::isInstance).map(Leg.class::cast)
				.filter(leg -> TransportMode.walk.equals(leg.getMode())).findFirst()
				.orElseThrow(() -> new IllegalStateException("Walk router returned no Walk leg"));
		if (!(walk.getRoute() instanceof NetworkRoute route)) {
			throw new IllegalStateException("Walk router returned no NetworkRoute");
		}
		double travelTime;
		if (route.getTravelTime().isDefined()) travelTime = route.getTravelTime().seconds();
		else if (walk.getTravelTime().isDefined()) travelTime = walk.getTravelTime().seconds();
		else throw new IllegalStateException("Walk router returned no travel time");
		double distance = route.getDistance();
		if (!Double.isFinite(travelTime) || travelTime < 0.0
				|| !Double.isFinite(distance) || distance < 0.0) {
			throw new IllegalStateException("Walk router returned invalid time/distance");
		}
		return new RoutedAccess(route, travelTime, distance);
	}

	private Routed route(
			TripRouter router, Person person, Activity origin, Activity destination,
			double departure, Leg sourceLeg, Id<Vehicle> vehicleId) {
		List<? extends PlanElement> elements = router.calcRoute(
				TransportMode.car, FacilitiesUtils.wrapActivity(origin),
				FacilitiesUtils.toFacility(destination, facilities), departure,
				person, sourceLeg.getAttributes());
		Leg car = elements.stream().filter(Leg.class::isInstance).map(Leg.class::cast)
				.filter(leg -> TransportMode.car.equals(leg.getMode())).findFirst()
				.orElseThrow(() -> new IllegalStateException("Car router returned no Car leg"));
		if (!(car.getRoute() instanceof NetworkRoute route)) {
			throw new IllegalStateException("Car router returned no NetworkRoute");
		}
		route.setVehicleId(vehicleId);
		Vehicle vehicle = scenario.getVehicles().getVehicles().get(vehicleId);
		double time = departure;
		double distance = 0.0;
		for (Id<Link> linkId : enteredLinkSequence(route)) {
			Link link = scenario.getNetwork().getLinks().get(linkId);
			if (link == null) throw new IllegalStateException("Routed missing link " + linkId);
			distance += link.getLength();
			double seconds = carTravelTime.getLinkTravelTime(link, time, person, vehicle);
			if (!Double.isFinite(seconds) || seconds < 0.0) {
				throw new IllegalStateException("Invalid Car travel time on " + linkId);
			}
			time += seconds;
		}
		double travelTime = time - departure;
		var cost = costRules.quoteNetworkRoute(route, departure, carTravelTime, person, vehicle);
		route.setTravelTime(travelTime);
		route.setDistance(distance);
		List<Id<Link>> full = fullLinkSequence(route);
		return new Routed(route, travelTime, distance, cost.energyHkd(), cost.tollHkd(),
				isReversePair(full, 0, 1), isReversePair(full, full.size() - 2, full.size() - 1));
	}

	private void installProxyActivityAnchor(Person person, CarLegRef next, Link anchor) {
		Activity activity = next.origin();
		boolean interaction = activity.getType().endsWith("interaction");
		if (activity.getFacilityId() == null) {
			if (!interaction) {
				activity.getAttributes().putAttribute(
						"hkOriginalLinkIdBeforeCarAnchor",
						activity.getLinkId() == null ? "" : activity.getLinkId().toString());
				activity.getAttributes().putAttribute("hkCarOriginAnchorRepairVersion", "v1");
			}
			activity.setLinkId(anchor.getId());
			return;
		}
		String original = HongKongDynamicCarCostRules.canonicalParkingFacilityId(
				activity.getFacilityId().toString());
		String proxyText = original + FACILITY_PROXY_DELIMITER + person.getId()
				+ "_e" + next.elementIndex();
		Id<ActivityFacility> proxyId = Id.create(proxyText, ActivityFacility.class);
		if (!facilities.getFacilities().containsKey(proxyId)) {
			Coord coord = activityCoord(activity, anchor);
			facilities.addActivityFacility(facilities.getFactory()
					.createActivityFacility(proxyId, coord, anchor.getId()));
		}
		if (!interaction) {
			activity.getAttributes().putAttribute("hkOriginalFacilityIdBeforeCarAnchor", original);
			activity.getAttributes().putAttribute("hkCarOriginAnchorRepairVersion", "v1");
		}
		activity.setFacilityId(proxyId);
		activity.setLinkId(anchor.getId());
	}

	private Set<String> activeHouseholdLegs() {
		Set<String> result = new HashSet<>();
		for (var binding : householdBindings.bindings()) {
			if (!householdBindings.isActive(binding)) continue;
			result.add(legKey(binding.driverId(), binding.driverLegIndex()));
			result.add(legKey(binding.passengerId(), binding.passengerLegIndex()));
		}
		return result;
	}

	private static String legKey(Id<Person> personId, int allLegIndex) {
		return personId + "/" + allLegIndex;
	}

	static boolean touchesActiveHouseholdLeg(
			Set<String> activeHouseholdLegs, Id<Person> personId, int nextAllLegIndex) {
		return activeHouseholdLegs.contains(legKey(personId, nextAllLegIndex))
				|| nextAllLegIndex > 0 && activeHouseholdLegs.contains(
					legKey(personId, nextAllLegIndex - 1));
	}

	private static String precedingLegMode(Plan plan, CarLegRef next) {
		if (next.elementIndex() < 2) return "";
		PlanElement preceding = plan.getPlanElements().get(next.elementIndex() - 2);
		return preceding instanceof Leg leg ? leg.getMode() : "";
	}

	private static List<CarLegRef> carLegs(Plan plan) {
		List<CarLegRef> result = new ArrayList<>();
		List<PlanElement> elements = plan.getPlanElements();
		int carOrdinal = 0;
		int allLegIndex = 0;
		for (int index = 0; index < elements.size(); index++) {
			if (!(elements.get(index) instanceof Leg leg)) continue;
			if (TransportMode.car.equals(leg.getMode()) && index > 0 && index + 1 < elements.size()
					&& elements.get(index - 1) instanceof Activity origin
					&& elements.get(index + 1) instanceof Activity destination) {
				result.add(new CarLegRef(
						carOrdinal++, allLegIndex, index, leg, origin, destination));
			}
			allLegIndex++;
		}
		return result;
	}

	private static CarLegRef previousCarLeg(Plan plan, CarLegRef next) {
		if (next.elementIndex() < 3) return null;
		List<PlanElement> elements = plan.getPlanElements();
		if (!(elements.get(next.elementIndex() - 2) instanceof Leg leg)
				|| !TransportMode.car.equals(leg.getMode())
				|| !(elements.get(next.elementIndex() - 3) instanceof Activity origin)) return null;
		return new CarLegRef(-1, next.allLegIndex() - 1, next.elementIndex() - 2,
				leg, origin, next.origin());
	}

	private static AccessWalkRef accessWalk(Plan plan, CarLegRef next) {
		if (!next.origin().getType().endsWith("interaction") || next.elementIndex() < 3) return null;
		List<PlanElement> elements = plan.getPlanElements();
		if (!(elements.get(next.elementIndex() - 2) instanceof Leg leg)
				|| !TransportMode.walk.equals(leg.getMode())
				|| !(elements.get(next.elementIndex() - 3) instanceof Activity origin)) return null;
		return new AccessWalkRef(next.allLegIndex() - 1, leg, origin);
	}

	private static Id<Vehicle> vehicleId(Leg leg, Person person) {
		if (leg.getRoute() instanceof NetworkRoute route && route.getVehicleId() != null) {
			return route.getVehicleId();
		}
		Object assigned = person.getAttributes().getAttribute("assignedVehicleId");
		if (assigned == null || assigned.toString().isBlank()) {
			throw new IllegalStateException("Car leg/person lacks assigned vehicle");
		}
		return Id.createVehicleId(assigned.toString());
	}

	private static void installRoute(Leg leg, NetworkRoute route) {
		leg.setRoute(route);
		leg.setRoutingMode(TransportMode.car);
		if (route.getTravelTime().isDefined()) leg.setTravelTime(route.getTravelTime().seconds());
	}

	static void installWalkRoute(Leg leg, NetworkRoute route) {
		leg.setRoute(route);
		if (route.getTravelTime().isDefined()) leg.setTravelTime(route.getTravelTime().seconds());
	}

	private Coord activityCoord(Activity activity, Link fallback) {
		if (activity.getCoord() != null) return activity.getCoord();
		if (activity.getFacilityId() != null) {
			ActivityFacility facility = facilities.getFacilities().get(activity.getFacilityId());
			if (facility != null && facility.getCoord() != null) return facility.getCoord();
		}
		return fallback.getToNode().getCoord();
	}

	static boolean areExactReverse(Link first, Link second) {
		return first.getFromNode().getId().equals(second.getToNode().getId())
				&& first.getToNode().getId().equals(second.getFromNode().getId());
	}

	static double pointSegmentDistance(Coord point, Link link) {
		Coord from = link.getFromNode().getCoord();
		Coord to = link.getToNode().getCoord();
		double dx = to.getX() - from.getX();
		double dy = to.getY() - from.getY();
		double denominator = dx * dx + dy * dy;
		double fraction = denominator == 0.0 ? 0.0
				: ((point.getX() - from.getX()) * dx + (point.getY() - from.getY()) * dy)
				/ denominator;
		fraction = Math.max(0.0, Math.min(1.0, fraction));
		double x = from.getX() + fraction * dx;
		double y = from.getY() + fraction * dy;
		return Math.hypot(point.getX() - x, point.getY() - y);
	}

	private boolean isReversePair(List<Id<Link>> sequence, int firstIndex, int secondIndex) {
		if (firstIndex < 0 || secondIndex < 0 || firstIndex >= sequence.size()
				|| secondIndex >= sequence.size()) return false;
		Link first = scenario.getNetwork().getLinks().get(sequence.get(firstIndex));
		Link second = scenario.getNetwork().getLinks().get(sequence.get(secondIndex));
		return first != null && second != null && areExactReverse(first, second);
	}

	private static List<Id<Link>> fullLinkSequence(NetworkRoute route) {
		List<Id<Link>> result = new ArrayList<>();
		if (route.getStartLinkId() != null) result.add(route.getStartLinkId());
		result.addAll(route.getLinkIds());
		if (route.getEndLinkId() != null
				&& (result.isEmpty() || !route.getEndLinkId().equals(result.getLast()))) {
			result.add(route.getEndLinkId());
		}
		return result;
	}

	private static List<Id<Link>> enteredLinkSequence(NetworkRoute route) {
		List<Id<Link>> result = new ArrayList<>(route.getLinkIds());
		if (route.getEndLinkId() != null
				&& (result.isEmpty() || !route.getEndLinkId().equals(result.getLast()))) {
			result.add(route.getEndLinkId());
		}
		return result;
	}

	private static Map<String, Object> baseRow(
			HongKongCarOriginAnchorObservationCatalog.Observation observation) {
		Map<String, Object> row = new LinkedHashMap<>();
		row.put("person_id", observation.personId());
		row.put("vehicle_id", observation.vehicleId());
		row.put("private_car_trip_ordinal", observation.privateCarTripOrdinal());
		row.put("vehicle_enters_traffic_time_s", observation.vehicleEntersTrafficTimeS());
		row.put("start_link_id", observation.startLinkId());
		row.put("observed_reverse_link_id", observation.observedReverseLinkId());
		return row;
	}

	private static void putEvaluation(Map<String, Object> row, String prefix, Evaluation value) {
		row.put(prefix + "_access_distance_m", value.accessDistanceM());
		row.put(prefix + "_access_route_time_s", value.access() == null ? ""
				: value.access().travelTimeS());
		row.put(prefix + "_previous_route_time_s", value.previous() == null ? ""
				: value.previous().travelTimeS());
		row.put(prefix + "_previous_route_distance_m", value.previous() == null ? ""
				: value.previous().distanceM());
		row.put(prefix + "_previous_terminal_reverse", value.previous() != null
				&& value.previous().terminalReverse());
		row.put(prefix + "_next_route_time_s", value.next().travelTimeS());
		row.put(prefix + "_next_route_distance_m", value.next().distanceM());
		row.put(prefix + "_next_initial_reverse", value.next().initialReverse());
		row.put(prefix + "_energy_hkd", value.next().energyHkd()
				+ (value.previous() == null ? 0.0 : value.previous().energyHkd()));
		row.put(prefix + "_toll_hkd", value.next().tollHkd()
				+ (value.previous() == null ? 0.0 : value.previous().tollHkd()));
		row.put(prefix + "_raw_generalized_s", value.rawGeneralizedSeconds());
		row.put(prefix + "_joint_objective_s", value.objectiveSeconds());
	}

	private void writeAudit(
			List<Map<String, Object>> rows, Map<String, Integer> statusCounts,
			int repaired, int activeBindings) {
		Path output = Path.of(config.controller().getOutputDirectory()).toAbsolutePath().normalize();
		try {
			Files.createDirectories(output);
			writeCsv(output.resolve("car_origin_anchor_candidate_audit.csv"), rows);
			StringBuilder json = new StringBuilder("{\n")
					.append("  \"status\": \"completed\",\n")
					.append("  \"source_observations\": ").append(rows.size()).append(",\n")
					.append("  \"repaired_high_confidence\": ").append(repaired).append(",\n")
					.append("  \"active_household_bindings_preserved\": ").append(activeBindings).append(",\n")
					.append("  \"hkd_to_generalized_seconds\": ").append(hkdToGeneralizedSeconds).append(",\n")
					.append("  \"status_counts\": {");
			int index = 0;
			for (var entry : statusCounts.entrySet()) {
				if (index++ > 0) json.append(',');
				json.append("\n    \"").append(jsonEscape(entry.getKey())).append("\": ")
						.append(entry.getValue());
			}
			json.append("\n  }\n}\n");
			Files.writeString(output.resolve("car_origin_anchor_repair_summary.json"),
					json.toString(), StandardCharsets.UTF_8);
		} catch (IOException error) {
			throw new IllegalStateException("Failed to write Car origin-anchor audit", error);
		}
	}

	private static void writeCsv(Path path, List<Map<String, Object>> rows) throws IOException {
		List<String> header = new ArrayList<>();
		for (Map<String, Object> row : rows) {
			for (String key : row.keySet()) if (!header.contains(key)) header.add(key);
		}
		try (BufferedWriter writer = Files.newBufferedWriter(path, StandardCharsets.UTF_8)) {
			writer.write(String.join(",", header));
			writer.newLine();
			for (Map<String, Object> row : rows) {
				for (int index = 0; index < header.size(); index++) {
					if (index > 0) writer.write(',');
					writer.write(csvValue(row.get(header.get(index))));
				}
				writer.newLine();
			}
		}
	}

	private static String csvValue(Object value) {
		if (value == null) return "";
		String text = value.toString();
		if (text.indexOf(',') < 0 && text.indexOf('"') < 0 && text.indexOf('\n') < 0) return text;
		return '"' + text.replace("\"", "\"\"") + '"';
	}

	private static String concise(RuntimeException error) {
		String message = error.getMessage();
		return error.getClass().getSimpleName() + (message == null ? "" : ": " + message);
	}

	private static String jsonEscape(String value) {
		return value.replace("\\", "\\\\").replace("\"", "\\\"");
	}
}
