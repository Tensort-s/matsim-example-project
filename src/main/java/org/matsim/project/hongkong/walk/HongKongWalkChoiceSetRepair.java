package org.matsim.project.hongkong.walk;

import org.matsim.api.core.v01.TransportMode;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.router.TripRouter;
import org.matsim.core.router.TripStructureUtils;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Repairs the Hong Kong Walk choice set before a calibration run.
 *
 * <p>The policy is deliberately city-wide and purpose-neutral: a physical-network
 * Walk route of at most 15 minutes is a normal alternative, 15--30 minutes stays
 * available but is not proactively added, and a selected Walk above 30 minutes is
 * replaced only when a real PT route is available. Protected household/student
 * plans are changed atomically by complete home-based tour.</p>
 */
public final class HongKongWalkChoiceSetRepair {
	private static final java.util.concurrent.atomic.AtomicInteger WALK_ASSESSMENT_FAILURES_LOGGED =
			new java.util.concurrent.atomic.AtomicInteger();

	public static final double SHORT_WALK_S = 15.0 * 60.0;
	public static final double MAX_WALK_S = 30.0 * 60.0;
	public static final int DEFAULT_MAX_SHORT_ALTERNATIVES_PER_PERSON = 4;
	public static final String ALTERNATIVE_ATTRIBUTE = "hkWalkChoiceSetAlternativeV1";
	public static final String REPAIR_ATTRIBUTE = "hkWalkChoiceSetRepairV1";

	@FunctionalInterface
	public interface RouteProvider {
		List<? extends PlanElement> route(
				String mode, Person person, Activity origin, Activity destination, double departureTimeS);
	}

	@FunctionalInterface
	public interface WalkAssessmentProvider {
		WalkAssessment assess(
				Person person, Activity origin, Activity destination,
				double departureTimeS, String selectedMode);
	}

	public record WalkAssessment(double timeS, double distanceM, String classification) {
		public WalkAssessment {
			if (classification == null || classification.isBlank()) {
				throw new IllegalArgumentException("Walk assessment classification is required.");
			}
		}

		public static WalkAssessment routed(double timeS, double distanceM) {
			return new WalkAssessment(timeS, distanceM, walkClass(timeS));
		}

		public static WalkAssessment notEvaluated(String classification) {
			return new WalkAssessment(Double.NaN, Double.NaN, classification);
		}
	}

	public record AuditRow(
			String personId,
			int tripIndex,
			int tourIndex,
			boolean protectedPerson,
			String selectedModeBefore,
			double networkWalkTimeS,
			double networkWalkDistanceM,
			String walkClass,
			String action,
			String detail) {
	}

	public record Result(
			List<AuditRow> rows,
			int protectedToursRepaired,
			int ordinaryTripsRepaired,
			int shortWalkAlternativesAdded,
			int unresolvedLongWalkTrips) {
		public Map<String, Integer> actionCounts() {
			Map<String, Integer> counts = new LinkedHashMap<>();
			for (AuditRow row : rows) counts.merge(row.action(), 1, Integer::sum);
			return counts;
		}
	}

	private record TripEvaluation(
			int tripIndex,
			int tourIndex,
			TripStructureUtils.Trip trip,
			String selectedMode,
			double departureTimeS,
			double walkTimeS,
			double walkDistanceM,
			String walkClass) {
		boolean selectedWalk() {
			return TransportMode.walk.equals(selectedMode);
		}
		boolean shortWalk() {
			return walkTimeS <= SHORT_WALK_S;
		}
		boolean longWalk() {
			return walkTimeS > MAX_WALK_S;
		}
	}

	private record Replacement(int tripIndex, List<PlanElement> route) {
	}

	private HongKongWalkChoiceSetRepair() {
	}

	public static Result repair(
			Iterable<? extends Person> persons,
			Set<String> protectedPersonIds,
			WalkAssessmentProvider walkAssessmentProvider,
			RouteProvider routeProvider,
			int maxShortAlternativesPerPerson) {
		if (maxShortAlternativesPerPerson < 0) {
			throw new IllegalArgumentException("Maximum short-Walk alternatives must be non-negative.");
		}
		List<AuditRow> rows = new ArrayList<>();
		int protectedToursRepaired = 0;
		int ordinaryTripsRepaired = 0;
		int shortAlternativesAdded = 0;
		int unresolved = 0;

		for (Person person : persons) {
			Plan selected = person.getSelectedPlan();
			if (selected == null) {
				throw new IllegalStateException("Person has no selected plan: " + person.getId());
			}
			boolean protectedPerson = protectedPersonIds.contains(person.getId().toString());
			List<TripEvaluation> evaluations = evaluate(
					person, selected, protectedPerson, walkAssessmentProvider);
			Map<Integer, String> action = new HashMap<>();
			Map<Integer, String> detail = new HashMap<>();
			for (TripEvaluation evaluation : evaluations) {
				if (evaluation.selectedWalk() && !Double.isFinite(evaluation.walkTimeS())) {
					action.put(evaluation.tripIndex(), "unresolved_walk_network_assessment");
					detail.put(evaluation.tripIndex(),
							"selected Walk could not be assessed on the physical network");
					unresolved++;
				}
			}

			if (protectedPerson) {
				Map<Integer, List<TripEvaluation>> byTour = new LinkedHashMap<>();
				for (TripEvaluation evaluation : evaluations) {
					byTour.computeIfAbsent(evaluation.tourIndex(), ignored -> new ArrayList<>())
							.add(evaluation);
				}
				for (var entry : byTour.entrySet()) {
					List<TripEvaluation> longWalks = entry.getValue().stream()
							.filter(TripEvaluation::selectedWalk)
							.filter(TripEvaluation::longWalk)
							.toList();
					if (longWalks.isEmpty()) continue;
					List<TripEvaluation> walkTrips = entry.getValue().stream()
							.filter(TripEvaluation::selectedWalk).toList();
					List<Replacement> replacements = ptReplacements(person, walkTrips, routeProvider);
					if (replacements.size() != walkTrips.size()) {
						for (TripEvaluation item : longWalks) {
							action.put(item.tripIndex(), "unresolved_protected_tour");
							detail.put(item.tripIndex(), "PT unavailable; complete tour left unchanged");
							unresolved++;
						}
						continue;
					}
					applyReplacements(selected, replacements);
					selected.getAttributes().putAttribute(REPAIR_ATTRIBUTE,
							"protected_home_tour_" + entry.getKey());
					for (TripEvaluation item : walkTrips) {
						action.put(item.tripIndex(), "protected_tour_walk_to_pt");
						detail.put(item.tripIndex(), "atomic home-based tour repair");
					}
					protectedToursRepaired++;
				}
			} else {
				for (TripEvaluation evaluation : evaluations) {
					if (!evaluation.selectedWalk() || !evaluation.longWalk()) continue;
					List<Replacement> replacement = ptReplacements(
							person, List.of(evaluation), routeProvider);
					if (replacement.isEmpty()) {
						action.put(evaluation.tripIndex(), "unresolved_ordinary_long_walk");
						detail.put(evaluation.tripIndex(), "PT unavailable; selected Walk retained");
						unresolved++;
						continue;
					}
					applyReplacements(selected, replacement);
					action.put(evaluation.tripIndex(), "ordinary_long_walk_to_pt");
					detail.put(evaluation.tripIndex(), "physical Walk above 30 minutes");
					ordinaryTripsRepaired++;
				}

				int addedForPerson = 0;
				for (TripEvaluation evaluation : evaluations) {
					if (addedForPerson >= maxShortAlternativesPerPerson) break;
					if (evaluation.selectedWalk() || !evaluation.shortWalk()) continue;
					Plan alternative = PopulationUtils.createPlan(person);
					PopulationUtils.copyFromTo(selected, alternative);
					alternative.setScore(null);
					List<TripStructureUtils.Trip> copiedTrips = List.copyOf(
							TripStructureUtils.getTrips(alternative));
					if (evaluation.tripIndex() >= copiedTrips.size()) {
						throw new IllegalStateException("Copied plan lost trip " + evaluation.tripIndex());
					}
					TripStructureUtils.Trip copied = copiedTrips.get(evaluation.tripIndex());
					List<? extends PlanElement> rerouted = routeProvider.route(
							TransportMode.walk, person, copied.getOriginActivity(),
							copied.getDestinationActivity(), evaluation.departureTimeS());
					if (!validRoute(rerouted, TransportMode.walk)) {
						action.put(evaluation.tripIndex(), "short_walk_candidate_reroute_failed");
						continue;
					}
					TripRouter.insertTrip(alternative, copied.getOriginActivity(),
							new ArrayList<>(rerouted), copied.getDestinationActivity());
					alternative.getAttributes().putAttribute(ALTERNATIVE_ATTRIBUTE,
							"trip_" + evaluation.tripIndex());
					person.addPlan(alternative);
					action.put(evaluation.tripIndex(), "short_walk_alternative_added");
					detail.put(evaluation.tripIndex(), "network-routed candidate plan");
					addedForPerson++;
					shortAlternativesAdded++;
				}
			}

			for (TripEvaluation evaluation : evaluations) {
				rows.add(new AuditRow(
						person.getId().toString(), evaluation.tripIndex(), evaluation.tourIndex(),
						protectedPerson, evaluation.selectedMode(), evaluation.walkTimeS(),
						evaluation.walkDistanceM(), evaluation.walkClass(),
						action.getOrDefault(evaluation.tripIndex(), "audited_no_change"),
						detail.getOrDefault(evaluation.tripIndex(), "")));
			}
		}
		return new Result(List.copyOf(rows), protectedToursRepaired, ordinaryTripsRepaired,
				shortAlternativesAdded, unresolved);
	}

	private static List<TripEvaluation> evaluate(
			Person person, Plan plan, boolean protectedPerson,
			WalkAssessmentProvider assessmentProvider) {
		List<TripStructureUtils.Trip> trips = List.copyOf(TripStructureUtils.getTrips(plan));
		List<TripEvaluation> result = new ArrayList<>(trips.size());
		int tourIndex = 0;
		for (int index = 0; index < trips.size(); index++) {
			TripStructureUtils.Trip trip = trips.get(index);
			String selectedMode = TripStructureUtils.getRoutingModeIdentifier()
					.identifyMainMode(trip.getTripElements());
			double departure = departureTime(trip);
			WalkAssessment assessment;
			if (protectedPerson && !TransportMode.walk.equals(selectedMode)) {
				assessment = WalkAssessment.notEvaluated("protected_nonwalk_not_evaluated");
			} else {
				try {
					assessment = assessmentProvider.assess(person, trip.getOriginActivity(),
							trip.getDestinationActivity(), departure, selectedMode);
				} catch (RuntimeException error) {
					int failureNumber = WALK_ASSESSMENT_FAILURES_LOGGED.incrementAndGet();
					if (failureNumber <= 5) {
						System.err.printf(
								"Physical Walk assessment failure %d for person=%s trip=%d mode=%s: %s%n",
								failureNumber, person.getId(), index, selectedMode, error);
						error.printStackTrace(System.err);
					}
					assessment = WalkAssessment.notEvaluated("network_unreachable");
				}
			}
			result.add(new TripEvaluation(index, tourIndex, trip, selectedMode, departure,
					assessment.timeS(), assessment.distanceM(), assessment.classification()));
			if (isHome(trip.getDestinationActivity())) tourIndex++;
		}
		return result;
	}

	private static List<Replacement> ptReplacements(
			Person person, List<TripEvaluation> trips, RouteProvider provider) {
		List<Replacement> replacements = new ArrayList<>();
		for (TripEvaluation evaluation : trips) {
			List<? extends PlanElement> routed;
			try {
				routed = provider.route(TransportMode.pt, person,
						evaluation.trip().getOriginActivity(), evaluation.trip().getDestinationActivity(),
						evaluation.departureTimeS());
			} catch (RuntimeException error) {
				return List.of();
			}
			if (!validRoute(routed, TransportMode.pt)) return List.of();
			replacements.add(new Replacement(evaluation.tripIndex(), new ArrayList<>(routed)));
		}
		return replacements;
	}

	private static void applyReplacements(Plan plan, List<Replacement> replacements) {
		List<Replacement> descending = replacements.stream()
				.sorted(Comparator.comparingInt(Replacement::tripIndex).reversed()).toList();
		for (Replacement replacement : descending) {
			List<TripStructureUtils.Trip> trips = List.copyOf(TripStructureUtils.getTrips(plan));
			TripStructureUtils.Trip trip = trips.get(replacement.tripIndex());
			TripRouter.insertTrip(plan, trip.getOriginActivity(), replacement.route(),
					trip.getDestinationActivity());
		}
	}

	private static boolean validRoute(List<? extends PlanElement> route, String routingMode) {
		if (route == null || route.isEmpty()) return false;
		boolean hasLeg = false;
		for (PlanElement element : route) {
			if (!(element instanceof Leg leg)) continue;
			hasLeg = true;
			if (leg.getRoute() == null || !leg.getTravelTime().isDefined()
					|| !Double.isFinite(leg.getTravelTime().seconds())) return false;
			if (TransportMode.walk.equals(routingMode)) leg.setRoutingMode(TransportMode.walk);
		}
		if (!hasLeg) return false;
		if (TransportMode.pt.equals(routingMode)) {
			return TransportMode.pt.equals(TripStructureUtils.getRoutingModeIdentifier()
					.identifyMainMode(route));
		}
		return true;
	}

	private static double departureTime(TripStructureUtils.Trip trip) {
		if (trip.getOriginActivity().getEndTime().isDefined()) {
			return trip.getOriginActivity().getEndTime().seconds();
		}
		for (PlanElement element : trip.getTripElements()) {
			if (element instanceof Leg leg && leg.getDepartureTime().isDefined()) {
				return leg.getDepartureTime().seconds();
			}
		}
		return 0.0;
	}

	private static double travelTime(List<? extends PlanElement> elements) {
		double total = 0.0;
		for (PlanElement element : elements) {
			if (element instanceof Leg leg && leg.getTravelTime().isDefined()) {
				total += leg.getTravelTime().seconds();
			}
		}
		return total;
	}

	private static double distance(List<? extends PlanElement> elements) {
		double total = 0.0;
		for (PlanElement element : elements) {
			if (element instanceof Leg leg && leg.getRoute() != null
					&& Double.isFinite(leg.getRoute().getDistance())) {
				total += leg.getRoute().getDistance();
			}
		}
		return total;
	}

	private static boolean isHome(Activity activity) {
		return activity.getType() != null
				&& activity.getType().toLowerCase(java.util.Locale.ROOT).startsWith("home");
	}

	private static String walkClass(double timeS) {
		if (!Double.isFinite(timeS)) return "network_unreachable";
		if (timeS <= SHORT_WALK_S) return "short_feasible_le_15m";
		if (timeS <= MAX_WALK_S) return "discouraged_15_to_30m";
		return "ineligible_over_30m";
	}
}
