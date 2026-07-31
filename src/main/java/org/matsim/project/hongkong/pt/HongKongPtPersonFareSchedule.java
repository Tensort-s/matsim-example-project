package org.matsim.project.hongkong.pt;

import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.pt.routes.TransitPassengerRoute;
import org.matsim.pt.transitSchedule.api.TransitSchedule;

import java.util.ArrayList;
import java.util.Collections;
import java.util.IdentityHashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.OptionalDouble;
import java.util.Set;
import java.util.TreeMap;

/**
 * Immutable, selected-plan-ordered PT fare schedule.
 *
 * <p>Each prepared {@code mode=pt,routingMode=pt} leg is consumed exactly once
 * by the scoring component. A chained transit route is quoted segment by
 * segment in chain order. Unresolved segments retain null fare and an explicit
 * reason; resolved segments are never inferred or duplicated.</p>
 */
public final class HongKongPtPersonFareSchedule {

	public record LegFare(
			int ptLegOrdinal,
			String routeFingerprint,
			List<HongKongPtFareRuntimeCatalog.FareQuote> segmentQuotes,
			List<String> structuralUnresolvedReasons) {

		public LegFare {
			if (ptLegOrdinal < 0) {
				throw new IllegalArgumentException(
						"ptLegOrdinal must be nonnegative.");
			}
			routeFingerprint = requireText(
					routeFingerprint, "routeFingerprint");
			segmentQuotes = List.copyOf(segmentQuotes);
			structuralUnresolvedReasons =
					List.copyOf(structuralUnresolvedReasons);
			if (segmentQuotes.isEmpty()
					&& structuralUnresolvedReasons.isEmpty()) {
				throw new IllegalArgumentException(
						"PT leg fare requires a quote or unresolved reason.");
			}
		}

		public double resolvedFareHkd() {
			double sum = 0.0;
			for (HongKongPtFareRuntimeCatalog.FareQuote quote :
					segmentQuotes) {
				if (quote.resolved()) {
					sum += quote.costHkd();
				}
			}
			if (!Double.isFinite(sum) || sum < 0.0) {
				throw new IllegalStateException(
						"Resolved PT fare sum is invalid.");
			}
			return sum;
		}

		public OptionalDouble completeFareHkd() {
			if (!structuralUnresolvedReasons.isEmpty()
					|| segmentQuotes.stream().anyMatch(
							quote -> !quote.resolved())) {
				return OptionalDouble.empty();
			}
			return OptionalDouble.of(resolvedFareHkd());
		}

		public long resolvedSegments() {
			return segmentQuotes.stream()
					.filter(HongKongPtFareRuntimeCatalog.FareQuote::resolved)
					.count();
		}

		public long unresolvedSegments() {
			return segmentQuotes.size() - resolvedSegments()
					+ structuralUnresolvedReasons.size();
		}
	}

	public record Audit(
			long ptLegs,
			long ptSegments,
			long resolvedSegments,
			long unresolvedSegments,
			double resolvedFareHkd,
			Map<String, Long> resolvedByLayer,
			Map<String, Long> unresolvedByLayer,
			Map<String, Long> unresolvedReasons,
			long moneyEventsEmitted,
			long tripCallbackCharges) {

		public Audit {
			if (ptLegs < 0 || ptSegments < 0
					|| resolvedSegments < 0 || unresolvedSegments < 0
					|| !Double.isFinite(resolvedFareHkd)
					|| resolvedFareHkd < 0.0) {
				throw new IllegalArgumentException(
						"Invalid PT fare-schedule audit values.");
			}
			resolvedByLayer = Collections.unmodifiableMap(
					new TreeMap<>(resolvedByLayer));
			unresolvedByLayer = Collections.unmodifiableMap(
					new TreeMap<>(unresolvedByLayer));
			unresolvedReasons = Collections.unmodifiableMap(
					new TreeMap<>(unresolvedReasons));
			if (moneyEventsEmitted != 0 || tripCallbackCharges != 0) {
				throw new IllegalArgumentException(
						"PT fare schedule must not emit money events or charge trips.");
			}
		}
	}

	private final Id<Person> personId;
	private final List<LegFare> legFares;
	private final Audit audit;

	private HongKongPtPersonFareSchedule(
			Id<Person> personId,
			List<LegFare> legFares) {
		this.personId = Objects.requireNonNull(personId, "personId");
		this.legFares = List.copyOf(legFares);
		this.audit = audit(this.legFares);
	}

	public static HongKongPtPersonFareSchedule fromSelectedPlan(
			Person person,
			TransitSchedule transitSchedule,
			HongKongPtFareRuntimeCatalog catalog) {
		Objects.requireNonNull(person, "person");
		Objects.requireNonNull(transitSchedule, "transitSchedule");
		Objects.requireNonNull(catalog, "catalog");
		if (person.getSelectedPlan() == null) {
			throw new IllegalArgumentException(
					"Person has no selected plan: " + person.getId());
		}
		List<LegFare> fares = new ArrayList<>();
		int ptOrdinal = 0;
		for (PlanElement element :
				person.getSelectedPlan().getPlanElements()) {
			if (!(element instanceof Leg leg)
					|| !"pt".equals(leg.getMode())) {
				continue;
			}
			fares.add(quoteLeg(
					ptOrdinal,
					leg,
					transitSchedule,
					catalog));
			ptOrdinal++;
		}
		return new HongKongPtPersonFareSchedule(person.getId(), fares);
	}

	private static LegFare quoteLeg(
			int ordinal,
			Leg leg,
			TransitSchedule transitSchedule,
			HongKongPtFareRuntimeCatalog catalog) {
		List<HongKongPtFareRuntimeCatalog.FareQuote> quotes =
				new ArrayList<>();
		Set<String> reasons = new LinkedHashSet<>();
		if (!"pt".equals(leg.getRoutingMode())) {
			reasons.add("PT_LEG_ROUTING_MODE_NOT_PT");
		}
		if (!(leg.getRoute() instanceof TransitPassengerRoute first)) {
			reasons.add("PT_ROUTE_NOT_TRANSIT_PASSENGER");
			return new LegFare(
					ordinal,
					fingerprint(leg),
					quotes,
					List.copyOf(reasons));
		}

		Set<TransitPassengerRoute> visited =
				Collections.newSetFromMap(new IdentityHashMap<>());
		TransitPassengerRoute current = first;
		while (current != null) {
			if (!visited.add(current)) {
				reasons.add("PT_CHAIN_CYCLE");
				break;
			}
			quotes.add(catalog.quote(current, transitSchedule));
			current = current.getChainedRoute();
		}
		if (quotes.isEmpty()) {
			reasons.add("PT_CHAIN_EMPTY");
		}
		return new LegFare(
				ordinal,
				fingerprint(leg),
				quotes,
				List.copyOf(reasons));
	}

	static String fingerprint(Leg leg) {
		Objects.requireNonNull(leg, "leg");
		StringBuilder result = new StringBuilder()
				.append(String.valueOf(leg.getMode()))
				.append('|')
				.append(String.valueOf(leg.getRoutingMode()));
		if (!(leg.getRoute() instanceof TransitPassengerRoute first)) {
			return result.append("|<non_transit_passenger_route>").toString();
		}
		Set<TransitPassengerRoute> visited =
				Collections.newSetFromMap(new IdentityHashMap<>());
		TransitPassengerRoute current = first;
		while (current != null) {
			if (!visited.add(current)) {
				result.append("|<cycle>");
				break;
			}
			result.append('|')
					.append(id(current.getLineId())).append(':')
					.append(id(current.getRouteId())).append(':')
					.append(id(current.getAccessStopId())).append('>')
					.append(id(HongKongPtFareRuntimeCatalog
							.segmentEgressStopId(current)));
			current = current.getChainedRoute();
		}
		return result.toString();
	}

	private static Audit audit(List<LegFare> legFares) {
		long segments = 0;
		long resolved = 0;
		long unresolved = 0;
		double resolvedFare = 0.0;
		Map<String, Long> resolvedByLayer = new LinkedHashMap<>();
		Map<String, Long> unresolvedByLayer = new LinkedHashMap<>();
		Map<String, Long> reasons = new LinkedHashMap<>();
		for (LegFare legFare : legFares) {
			segments += legFare.segmentQuotes.size();
			resolvedFare += legFare.resolvedFareHkd();
			for (HongKongPtFareRuntimeCatalog.FareQuote quote :
					legFare.segmentQuotes) {
				String layer = quote.layer().layerId();
				if (quote.resolved()) {
					resolved++;
					resolvedByLayer.merge(layer, 1L, Long::sum);
				} else {
					unresolved++;
					unresolvedByLayer.merge(layer, 1L, Long::sum);
					reasons.merge(
							quote.unresolvedReason(), 1L, Long::sum);
				}
			}
			for (String reason : legFare.structuralUnresolvedReasons) {
				unresolved++;
				reasons.merge(reason, 1L, Long::sum);
			}
		}
		return new Audit(
				legFares.size(),
				segments,
				resolved,
				unresolved,
				resolvedFare,
				resolvedByLayer,
				unresolvedByLayer,
				reasons,
				0,
				0);
	}

	public Id<Person> personId() {
		return personId;
	}

	public int size() {
		return legFares.size();
	}

	public LegFare fareAt(int ordinal) {
		return legFares.get(ordinal);
	}

	public List<LegFare> legFares() {
		return legFares;
	}

	public Audit audit() {
		return audit;
	}

	private static String id(Object value) {
		return value == null ? "<missing>" : value.toString();
	}

	private static String requireText(String value, String label) {
		String cleaned = Objects.requireNonNull(value, label).strip();
		if (cleaned.isBlank()) {
			throw new IllegalArgumentException(label + " must not be blank.");
		}
		return cleaned;
	}
}
