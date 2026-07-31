package org.matsim.project.hongkong.pt;

import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.api.core.v01.events.PersonStuckEvent;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.api.core.v01.population.Population;
import org.matsim.api.core.v01.population.Route;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.router.TripStructureUtils;
import org.matsim.core.utils.misc.OptionalTime;
import org.matsim.pt.routes.TransitPassengerRoute;
import org.matsim.pt.transitSchedule.api.Departure;
import org.matsim.pt.transitSchedule.api.TransitLine;
import org.matsim.pt.transitSchedule.api.TransitRoute;
import org.matsim.pt.transitSchedule.api.TransitRouteStop;
import org.matsim.pt.transitSchedule.api.TransitSchedule;
import org.matsim.pt.transitSchedule.api.TransitStopFacility;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.IdentityHashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.TreeMap;

/**
 * Read-only, fail-closed audit of prepared Hong Kong PT itineraries.
 *
 * <p>This class does not route, rewrite, price, score, impute, or otherwise
 * mutate plans or the transit schedule. It distinguishes structural itinerary
 * defects that can be proven before QSim from runtime stuck causes that require
 * event-linked execution evidence.</p>
 */
public final class HongKongPtItineraryAudit {

	public static final String VERSION =
			"hong_kong_pt_itinerary_and_stuck_governance_v1";

	private static final Set<String> WALK_MODES =
			Collections.unmodifiableSet(new LinkedHashSet<>(List.of(
					TransportMode.walk,
					TransportMode.transit_walk,
					TransportMode.access_walk,
					TransportMode.egress_walk,
					TransportMode.non_network_walk
			)));
	private static final int EXAMPLE_LIMIT = 20;
	private static final double TIME_TOLERANCE_SECONDS = 1.0e-6;

	private HongKongPtItineraryAudit() {
	}

	public static AuditResult audit(Scenario scenario) {
		Objects.requireNonNull(scenario, "scenario");
		return audit(scenario.getPopulation(), scenario.getTransitSchedule());
	}

	static AuditResult audit(
			Population population,
			TransitSchedule schedule) {
		Objects.requireNonNull(population, "population");
		Objects.requireNonNull(schedule, "schedule");

		Counters counters = new Counters();
		Map<String, Long> reasonCounts = new TreeMap<>();
		List<Map<String, Object>> invalidExamples = new ArrayList<>();
		Map<String, PersonStatus> personStatuses = new TreeMap<>();
		MessageDigest digest = sha256();

		for (Person person : PopulationUtils.getSortedPersons(population).values()) {
			counters.persons++;
			Plan plan = person.getSelectedPlan();
			if (plan == null) {
				addReason(reasonCounts, "SELECTED_PLAN_MISSING");
				personStatuses.put(person.getId().toString(),
						new PersonStatus(false, false,
								List.of("SELECTED_PLAN_MISSING")));
				update(digest, person.getId() + "\tSELECTED_PLAN_MISSING\n");
				continue;
			}
			counters.selectedPlans++;

			int tripOrdinal = 0;
			boolean personHasPt = false;
			LinkedHashSet<String> personReasons = new LinkedHashSet<>();
			for (TripStructureUtils.Trip trip : TripStructureUtils.getTrips(plan)) {
				if (!isPtTrip(trip)) {
					tripOrdinal++;
					continue;
				}
				personHasPt = true;
				counters.ptMainTrips++;
				LinkedHashSet<String> tripReasons = new LinkedHashSet<>();
				auditTrip(
						person,
						tripOrdinal,
						trip,
						schedule,
						counters,
						tripReasons,
						digest);
				if (tripReasons.isEmpty()) {
					counters.validPtMainTrips++;
				} else {
					counters.invalidPtMainTrips++;
					personReasons.addAll(tripReasons);
					tripReasons.forEach(reason ->
							addReason(reasonCounts, reason));
					if (invalidExamples.size() < EXAMPLE_LIMIT) {
						invalidExamples.add(ordered(
								"person_id", person.getId().toString(),
								"trip_ordinal", tripOrdinal,
								"reasons", List.copyOf(tripReasons)
						));
					}
				}
				tripOrdinal++;
			}
			if (personHasPt) {
				counters.ptPersons++;
				List<String> sortedReasons = personReasons.stream()
						.sorted()
						.toList();
				personStatuses.put(person.getId().toString(),
						new PersonStatus(true, sortedReasons.isEmpty(),
								sortedReasons));
			}
		}

		return new AuditResult(
				counters,
				reasonCounts,
				invalidExamples,
				personStatuses,
				hex(digest.digest())
		);
	}

	public static void requireLegal(AuditResult audit) {
		Objects.requireNonNull(audit, "audit");
		if (audit.ptMainTrips() == 0
				|| audit.invalidPtMainTrips() != 0
				|| !audit.reasonCounts().isEmpty()) {
			throw new IllegalStateException(
					"Prepared PT itinerary legality failed: " + audit.toMap());
		}
	}

	private static boolean isPtTrip(TripStructureUtils.Trip trip) {
		for (Leg leg : trip.getLegsOnly()) {
			if (TransportMode.pt.equals(leg.getMode())
					|| TransportMode.pt.equals(TripStructureUtils.getRoutingMode(leg))) {
				return true;
			}
		}
		return false;
	}

	private static void auditTrip(
			Person person,
			int tripOrdinal,
			TripStructureUtils.Trip trip,
			TransitSchedule schedule,
			Counters counters,
			LinkedHashSet<String> reasons,
			MessageDigest digest) {
		List<PlanElement> elements = List.copyOf(trip.getTripElements());
		OptionalTime departure = TripStructureUtils.getDepartureTime(trip);
		double readyTime = departure.isDefined()
				? departure.seconds()
				: Double.NaN;
		if (!finiteNonnegative(readyTime)) {
			reasons.add("TRIP_DEPARTURE_TIME_UNDEFINED_OR_INVALID");
		}
		if (elements.isEmpty() || elements.size() % 2 == 0) {
			reasons.add("TRIP_ELEMENT_SEQUENCE_INVALID");
		}

		long ptLegsInTrip = 0;
		for (int index = 0; index < elements.size(); index++) {
			PlanElement element = elements.get(index);
			if (index % 2 == 0) {
				if (!(element instanceof Leg leg)) {
					reasons.add("TRIP_ELEMENT_SEQUENCE_INVALID");
					continue;
				}
				String routingMode = TripStructureUtils.getRoutingMode(leg);
				if (!TransportMode.pt.equals(routingMode)) {
					reasons.add("PT_TRIP_ROUTING_MODE_NOT_PT");
				}
				double legReadyTime = leg.getDepartureTime().isDefined()
						? leg.getDepartureTime().seconds()
						: readyTime;
				if (leg.getDepartureTime().isDefined()
						&& !finiteNonnegative(legReadyTime)) {
					reasons.add("LEG_DEPARTURE_TIME_INVALID");
				}
				String mode = leg.getMode();
				if (TransportMode.pt.equals(mode)) {
					ptLegsInTrip++;
					counters.ptLegs++;
					auditPtLeg(
							trip,
							elements,
							index,
							leg,
							schedule,
							legReadyTime,
							reasons,
							digest);
				} else if (WALK_MODES.contains(mode)) {
					counters.ptWalkLegs++;
					if (index > 0 && index + 1 < elements.size()) {
						counters.transferWalkLegs++;
					}
					auditWalkLeg(
							trip,
							elements,
							index,
							leg,
							reasons,
							digest);
				} else {
					reasons.add("PT_TRIP_UNSUPPORTED_LEG_MODE");
				}
				double travelTime = routeTravelTime(leg);
				if (finiteNonnegative(legReadyTime)
						&& finiteNonnegative(travelTime)) {
					readyTime = legReadyTime + travelTime;
				} else {
					readyTime = Double.NaN;
				}
			} else {
				if (!(element instanceof Activity activity)
						|| !TripStructureUtils.isStageActivityType(
						activity.getType())) {
					reasons.add("NON_STAGE_ACTIVITY_INSIDE_PT_TRIP");
				} else {
					counters.ptStageActivities++;
				}
			}
		}
		if (ptLegsInTrip == 0) {
			reasons.add("PT_TRIP_WITHOUT_PT_SEGMENT");
		}

		update(digest, person.getId() + "\t" + tripOrdinal + "\t"
				+ optional(departure) + "\t"
				+ canonicalElements(elements) + "\t"
				+ String.join("|", reasons.stream().sorted().toList()) + "\n");
	}

	private static void auditWalkLeg(
			TripStructureUtils.Trip trip,
			List<PlanElement> elements,
			int index,
			Leg leg,
			LinkedHashSet<String> reasons,
			MessageDigest digest) {
		Route route = auditLegRoute(leg, reasons);
		Activity before = adjacentActivityBefore(trip, elements, index);
		Activity after = adjacentActivityAfter(trip, elements, index);
		if (before == null || after == null) {
			reasons.add("WALK_ADJACENT_ACTIVITY_MISSING");
			return;
		}
		if (route == null) {
			return;
		}
		requireLinkContinuity(
				"WALK",
				before.getLinkId(),
				route.getStartLinkId(),
				after.getLinkId(),
				route.getEndLinkId(),
				reasons);
		update(digest, "walk\t" + leg.getMode() + "\t"
				+ id(route.getStartLinkId()) + "\t"
				+ id(route.getEndLinkId()) + "\t"
				+ route.getDistance() + "\t"
				+ optional(route.getTravelTime()) + "\n");
	}

	private static void auditPtLeg(
			TripStructureUtils.Trip trip,
			List<PlanElement> elements,
			int index,
			Leg leg,
			TransitSchedule schedule,
			double readyTime,
			LinkedHashSet<String> reasons,
			MessageDigest digest) {
		Route rawRoute = auditLegRoute(leg, reasons);
		if (!(rawRoute instanceof TransitPassengerRoute route)) {
			reasons.add("PT_ROUTE_NOT_TRANSIT_PASSENGER");
			return;
		}

		Activity before = adjacentActivityBefore(trip, elements, index);
		Activity after = adjacentActivityAfter(trip, elements, index);
		if (before == null || after == null) {
			reasons.add("PT_INTERACTION_ACTIVITY_MISSING");
		}

		Set<TransitPassengerRoute> visited =
				Collections.newSetFromMap(new IdentityHashMap<>());
		TransitPassengerRoute current = route;
		boolean first = true;
		while (current != null) {
			if (!visited.add(current)) {
				reasons.add("PT_CHAIN_CYCLE");
				break;
			}
			RouteReferences references =
					resolve(current, schedule, reasons);
			if (references.complete()) {
				auditRouteStopsAndService(
						references,
						first ? readyTime : Double.NaN,
						reasons);
				if (first && before != null && after != null) {
					requireLinkContinuity(
							"PT",
							before.getLinkId(),
							rawRoute.getStartLinkId(),
							after.getLinkId(),
							rawRoute.getEndLinkId(),
							reasons);
					requireStopLink(
							"PT_ACCESS",
							references.access().getLinkId(),
							before.getLinkId(),
							rawRoute.getStartLinkId(),
							reasons);
				}
				if (current.getChainedRoute() == null
						&& before != null && after != null) {
					requireStopLink(
							"PT_EGRESS",
							references.egress().getLinkId(),
							after.getLinkId(),
							rawRoute.getEndLinkId(),
							reasons);
				}
			}
			update(digest, "pt\t" + id(current.getAccessStopId()) + "\t"
					+ id(current.getEgressStopId()) + "\t"
					+ id(current.getLineId()) + "\t"
					+ id(current.getRouteId()) + "\t"
					+ current.getDistance() + "\t"
					+ optional(current.getTravelTime()) + "\t"
					+ (references.complete()
					? scheduleFingerprint(references.route())
					: "<unresolved>") + "\n");
			first = false;
			current = current.getChainedRoute();
		}
	}

	private static Route auditLegRoute(
			Leg leg,
			LinkedHashSet<String> reasons) {
		Route route = leg.getRoute();
		if (route == null) {
			reasons.add("LEG_ROUTE_MISSING");
			return null;
		}
		if (!finiteNonnegative(route.getDistance())) {
			reasons.add("LEG_ROUTE_DISTANCE_INVALID");
		}
		if (!finiteNonnegative(optional(route.getTravelTime()))) {
			reasons.add("LEG_ROUTE_TRAVEL_TIME_INVALID");
		}
		if (route.getStartLinkId() == null) {
			reasons.add("LEG_ROUTE_START_LINK_MISSING");
		}
		if (route.getEndLinkId() == null) {
			reasons.add("LEG_ROUTE_END_LINK_MISSING");
		}
		return route;
	}

	private static RouteReferences resolve(
			TransitPassengerRoute passengerRoute,
			TransitSchedule schedule,
			LinkedHashSet<String> reasons) {
		TransitStopFacility access = null;
		TransitStopFacility egress = null;
		TransitLine line = null;
		TransitRoute route = null;
		if (passengerRoute.getAccessStopId() == null) {
			reasons.add("PT_ACCESS_STOP_ID_MISSING");
		} else {
			access = schedule.getFacilities().get(
					passengerRoute.getAccessStopId());
			if (access == null) {
				reasons.add("PT_ACCESS_STOP_NOT_IN_SCHEDULE");
			}
		}
		if (passengerRoute.getEgressStopId() == null) {
			reasons.add("PT_EGRESS_STOP_ID_MISSING");
		} else {
			egress = schedule.getFacilities().get(
					passengerRoute.getEgressStopId());
			if (egress == null) {
				reasons.add("PT_EGRESS_STOP_NOT_IN_SCHEDULE");
			}
		}
		if (passengerRoute.getLineId() == null) {
			reasons.add("PT_LINE_ID_MISSING");
		} else {
			line = schedule.getTransitLines().get(
					passengerRoute.getLineId());
			if (line == null) {
				reasons.add("PT_LINE_NOT_IN_SCHEDULE");
			}
		}
		if (passengerRoute.getRouteId() == null) {
			reasons.add("PT_TRANSIT_ROUTE_ID_MISSING");
		} else if (line != null) {
			route = line.getRoutes().get(passengerRoute.getRouteId());
			if (route == null) {
				reasons.add("PT_TRANSIT_ROUTE_NOT_IN_SCHEDULE");
			}
		}
		return new RouteReferences(access, egress, line, route);
	}

	private static void auditRouteStopsAndService(
			RouteReferences references,
			double readyTime,
			LinkedHashSet<String> reasons) {
		List<TransitRouteStop> stops = references.route().getStops();
		int accessIndex = stopIndex(stops, references.access().getId());
		int egressIndex = stopIndex(stops, references.egress().getId());
		if (accessIndex < 0) {
			reasons.add("PT_ACCESS_STOP_NOT_ON_ROUTE");
		}
		if (egressIndex < 0) {
			reasons.add("PT_EGRESS_STOP_NOT_ON_ROUTE");
		}
		if (accessIndex < 0 || egressIndex < 0) {
			return;
		}
		TransitRouteStop accessStop = stops.get(accessIndex);
		TransitRouteStop egressStop = stops.get(egressIndex);
		if (!accessStop.isAllowBoarding()) {
			reasons.add("PT_ACCESS_BOARDING_FORBIDDEN");
		}
		if (!egressStop.isAllowAlighting()) {
			reasons.add("PT_EGRESS_ALIGHTING_FORBIDDEN");
		}
		if (accessIndex >= egressIndex) {
			reasons.add("PT_STOP_ORDER_INVALID");
		}
		double accessOffset = optional(accessStop.getDepartureOffset());
		double egressOffset = optional(egressStop.getArrivalOffset());
		if (!finiteNonnegative(accessOffset)) {
			reasons.add("PT_ACCESS_DEPARTURE_OFFSET_INVALID");
		}
		if (!finiteNonnegative(egressOffset)
				|| finiteNonnegative(accessOffset)
				&& egressOffset + TIME_TOLERANCE_SECONDS < accessOffset) {
			reasons.add("PT_EGRESS_ARRIVAL_OFFSET_INVALID");
		}

		if (references.route().getDepartures().isEmpty()) {
			reasons.add("PT_ROUTE_DEPARTURES_EMPTY");
			return;
		}
		boolean departureTimeInvalid = false;
		boolean serviceAvailable = !finiteNonnegative(readyTime);
		for (Departure departure : references.route().getDepartures().values()) {
			double departureTime = departure.getDepartureTime();
			if (!finiteNonnegative(departureTime)) {
				departureTimeInvalid = true;
				continue;
			}
			if (finiteNonnegative(accessOffset)
					&& departureTime + accessOffset
					+ TIME_TOLERANCE_SECONDS >= readyTime) {
				serviceAvailable = true;
			}
		}
		if (departureTimeInvalid) {
			reasons.add("PT_ROUTE_DEPARTURE_TIME_INVALID");
		}
		if (!serviceAvailable) {
			reasons.add("PT_NO_SERVICE_AT_OR_AFTER_READY_TIME");
		}
	}

	private static int stopIndex(
			List<TransitRouteStop> stops,
			Id<TransitStopFacility> facilityId) {
		for (int index = 0; index < stops.size(); index++) {
			if (facilityId.equals(stops.get(index).getStopFacility().getId())) {
				return index;
			}
		}
		return -1;
	}

	private static String scheduleFingerprint(TransitRoute route) {
		List<String> stops = new ArrayList<>(route.getStops().size());
		for (TransitRouteStop stop : route.getStops()) {
			stops.add(id(stop.getStopFacility().getId())
					+ ":" + optional(stop.getArrivalOffset())
					+ ":" + optional(stop.getDepartureOffset())
					+ ":" + stop.isAllowBoarding()
					+ ":" + stop.isAllowAlighting());
		}
		Map<String, Double> departures = new TreeMap<>();
		route.getDepartures().values().forEach(departure ->
				departures.put(
						departure.getId().toString(),
						departure.getDepartureTime()));
		return String.join(",", stops) + ";" + departures;
	}

	private static Activity adjacentActivityBefore(
			TripStructureUtils.Trip trip,
			List<PlanElement> elements,
			int legIndex) {
		if (legIndex == 0) {
			return trip.getOriginActivity();
		}
		PlanElement previous = elements.get(legIndex - 1);
		return previous instanceof Activity activity ? activity : null;
	}

	private static Activity adjacentActivityAfter(
			TripStructureUtils.Trip trip,
			List<PlanElement> elements,
			int legIndex) {
		if (legIndex == elements.size() - 1) {
			return trip.getDestinationActivity();
		}
		PlanElement next = elements.get(legIndex + 1);
		return next instanceof Activity activity ? activity : null;
	}

	private static void requireLinkContinuity(
			String prefix,
			Id<Link> before,
			Id<Link> routeStart,
			Id<Link> after,
			Id<Link> routeEnd,
			LinkedHashSet<String> reasons) {
		if (before == null || routeStart == null) {
			reasons.add(prefix + "_START_LINK_UNRESOLVED");
		} else if (!before.equals(routeStart)) {
			reasons.add(prefix + "_START_LINK_DISCONTINUITY");
		}
		if (after == null || routeEnd == null) {
			reasons.add(prefix + "_END_LINK_UNRESOLVED");
		} else if (!after.equals(routeEnd)) {
			reasons.add(prefix + "_END_LINK_DISCONTINUITY");
		}
	}

	private static void requireStopLink(
			String prefix,
			Id<Link> stopLink,
			Id<Link> interactionLink,
			Id<Link> routeLink,
			LinkedHashSet<String> reasons) {
		if (stopLink == null || interactionLink == null || routeLink == null) {
			reasons.add(prefix + "_LINK_UNRESOLVED");
			return;
		}
		if (!stopLink.equals(interactionLink)
				|| !stopLink.equals(routeLink)) {
			reasons.add(prefix + "_LINK_MISMATCH");
		}
	}

	private static double routeTravelTime(Leg leg) {
		Route route = leg.getRoute();
		if (route != null && route.getTravelTime().isDefined()) {
			return route.getTravelTime().seconds();
		}
		return leg.getTravelTime().isDefined()
				? leg.getTravelTime().seconds()
				: Double.NaN;
	}

	private static double optional(OptionalTime time) {
		return time.isDefined() ? time.seconds() : Double.NaN;
	}

	private static boolean finiteNonnegative(double value) {
		return Double.isFinite(value) && value >= 0.0;
	}

	private static void addReason(Map<String, Long> counts, String reason) {
		counts.merge(reason, 1L, Long::sum);
	}

	private static String canonicalElements(List<PlanElement> elements) {
		List<String> values = new ArrayList<>(elements.size());
		for (PlanElement element : elements) {
			if (element instanceof Leg leg) {
				Route route = leg.getRoute();
				values.add("leg:" + leg.getMode() + ":"
						+ TripStructureUtils.getRoutingMode(leg) + ":"
						+ (route == null ? "<null>"
						: id(route.getStartLinkId()) + ">" + id(route.getEndLinkId())));
			} else if (element instanceof Activity activity) {
				values.add("activity:" + activity.getType() + ":"
						+ id(activity.getLinkId()));
			} else {
				values.add(element.getClass().getName());
			}
		}
		return String.join(",", values);
	}

	private static String id(Id<?> id) {
		return id == null ? "<null>" : id.toString();
	}

	private static Map<String, Object> ordered(Object... entries) {
		Map<String, Object> result = new LinkedHashMap<>();
		for (int index = 0; index < entries.length; index += 2) {
			result.put((String) entries[index], entries[index + 1]);
		}
		return result;
	}

	private static MessageDigest sha256() {
		try {
			return MessageDigest.getInstance("SHA-256");
		} catch (NoSuchAlgorithmException error) {
			throw new IllegalStateException("SHA-256 unavailable", error);
		}
	}

	private static void update(MessageDigest digest, String value) {
		digest.update(value.getBytes(StandardCharsets.UTF_8));
	}

	private static String hex(byte[] bytes) {
		StringBuilder result = new StringBuilder(bytes.length * 2);
		for (byte value : bytes) {
			result.append(String.format(Locale.ROOT, "%02x", value & 0xff));
		}
		return result.toString();
	}

	private record RouteReferences(
			TransitStopFacility access,
			TransitStopFacility egress,
			TransitLine line,
			TransitRoute route) {
		boolean complete() {
			return access != null && egress != null
					&& line != null && route != null;
		}
	}

	public record PersonStatus(
			boolean hasPtTrip,
			boolean legal,
			List<String> reasons) {
		public PersonStatus {
			reasons = List.copyOf(reasons);
		}
	}

	public static final class AuditResult {
		private final long persons;
		private final long selectedPlans;
		private final long ptPersons;
		private final long ptMainTrips;
		private final long validPtMainTrips;
		private final long invalidPtMainTrips;
		private final long ptLegs;
		private final long ptWalkLegs;
		private final long transferWalkLegs;
		private final long ptStageActivities;
		private final Map<String, Long> reasonCounts;
		private final List<Map<String, Object>> invalidExamples;
		private final Map<String, PersonStatus> personStatuses;
		private final String fingerprintSha256;

		private AuditResult(
				Counters counters,
				Map<String, Long> reasonCounts,
				List<Map<String, Object>> invalidExamples,
				Map<String, PersonStatus> personStatuses,
				String fingerprintSha256) {
			this.persons = counters.persons;
			this.selectedPlans = counters.selectedPlans;
			this.ptPersons = counters.ptPersons;
			this.ptMainTrips = counters.ptMainTrips;
			this.validPtMainTrips = counters.validPtMainTrips;
			this.invalidPtMainTrips = counters.invalidPtMainTrips;
			this.ptLegs = counters.ptLegs;
			this.ptWalkLegs = counters.ptWalkLegs;
			this.transferWalkLegs = counters.transferWalkLegs;
			this.ptStageActivities = counters.ptStageActivities;
			this.reasonCounts =
					Collections.unmodifiableMap(new TreeMap<>(reasonCounts));
			this.invalidExamples = List.copyOf(invalidExamples);
			this.personStatuses =
					Collections.unmodifiableMap(new TreeMap<>(personStatuses));
			this.fingerprintSha256 = fingerprintSha256;
		}

		public long persons() {
			return persons;
		}

		public long selectedPlans() {
			return selectedPlans;
		}

		public long ptPersons() {
			return ptPersons;
		}

		public long ptMainTrips() {
			return ptMainTrips;
		}

		public long validPtMainTrips() {
			return validPtMainTrips;
		}

		public long invalidPtMainTrips() {
			return invalidPtMainTrips;
		}

		public long ptLegs() {
			return ptLegs;
		}

		public long ptWalkLegs() {
			return ptWalkLegs;
		}

		public long transferWalkLegs() {
			return transferWalkLegs;
		}

		public long ptStageActivities() {
			return ptStageActivities;
		}

		public Map<String, Long> reasonCounts() {
			return reasonCounts;
		}

		public List<Map<String, Object>> invalidExamples() {
			return invalidExamples;
		}

		public String fingerprintSha256() {
			return fingerprintSha256;
		}

		public boolean legal() {
			return ptMainTrips > 0 && invalidPtMainTrips == 0
					&& reasonCounts.isEmpty();
		}

		/**
		 * Classifies only what the prepared-plan audit proves. A legal plan
		 * never becomes an inferred capacity, supply, or fare failure.
		 */
		public String classifyStuck(PersonStuckEvent event) {
			Objects.requireNonNull(event, "event");
			String mode = event.getLegMode();
			PersonStatus status =
					personStatuses.get(event.getPersonId().toString());
			if (TransportMode.pt.equals(mode)) {
				if (status == null || !status.hasPtTrip()) {
					return "PT_STUCK_PERSON_WITHOUT_AUDITED_PT_TRIP";
				}
				if (!status.legal()) {
					return "PT_STUCK_INVALID_ITINERARY__"
							+ status.reasons().getFirst();
				}
				return "PT_STUCK_LEGAL_ITINERARY_RUNTIME_CAUSE_UNRESOLVED";
			}
			if (WALK_MODES.contains(mode)) {
				if (status == null || !status.hasPtTrip()) {
					return "WALK_STUCK_OUTSIDE_PT_ITINERARY_SCOPE";
				}
				if (!status.legal()) {
					return "PT_WALK_STUCK_INVALID_ITINERARY__"
							+ status.reasons().getFirst();
				}
				return "PT_WALK_STUCK_LEGAL_ITINERARY_RUNTIME_CAUSE_UNRESOLVED";
			}
			return "STUCK_OUTSIDE_PT_WALK_SCOPE";
		}

		public Map<String, Object> toMap() {
			return ordered(
					"version", VERSION,
					"read_only", true,
					"plans_mutated", false,
					"schedule_mutated", false,
					"fare_or_scoring_used", false,
					"persons", persons,
					"selected_plans", selectedPlans,
					"pt_persons", ptPersons,
					"pt_main_trips", ptMainTrips,
					"valid_pt_main_trips", validPtMainTrips,
					"invalid_pt_main_trips", invalidPtMainTrips,
					"pt_legs", ptLegs,
					"pt_walk_legs", ptWalkLegs,
					"transfer_walk_legs", transferWalkLegs,
					"pt_stage_activities", ptStageActivities,
					"stuck_classifier_person_profiles",
							personStatuses.size(),
					"reason_counts", reasonCounts,
					"invalid_examples", invalidExamples,
					"fingerprint_sha256", fingerprintSha256,
					"legal", legal()
			);
		}
	}

	private static final class Counters {
		long persons;
		long selectedPlans;
		long ptPersons;
		long ptMainTrips;
		long validPtMainTrips;
		long invalidPtMainTrips;
		long ptLegs;
		long ptWalkLegs;
		long transferWalkLegs;
		long ptStageActivities;
	}
}
