package org.matsim.project.hongkong.car;

import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.api.core.v01.population.Route;
import org.matsim.core.population.routes.NetworkRoute;

import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

/** Selected-plan confirmed-toll schedule with exact route evidence checks. */
public final class HongKongCarTollPersonSchedule {

	private static final double SOURCE_DISTANCE_TOLERANCE_M = 1.0e-6;

	public record LegToll(
			int carOrdinal,
			int sourceLegSequence,
			String routeFingerprint,
			HongKongCarTollCostCatalog.TollQuote quote) {

		public LegToll {
			if (carOrdinal < 0 || sourceLegSequence < 0) {
				throw new IllegalArgumentException(
						"Car ordinals and toll source sequences must be nonnegative.");
			}
			routeFingerprint = requireText(
					routeFingerprint, "routeFingerprint");
			quote = Objects.requireNonNull(quote, "quote");
		}
	}

	public record Audit(
			long carLegs,
			long confirmedChargeLegs,
			long confirmedNoChargeLegs,
			long motorcycleOutOfScopeLegs,
			long unresolvedLegs,
			long physicalPassageEvents,
			double confirmedTollHkd,
			long inferredFromDistance,
			long candidateFallbacks,
			long fixedOwnershipCharges,
			long parkingCharges) {

		public Audit {
			if (carLegs < 0
					|| confirmedChargeLegs < 0
					|| confirmedNoChargeLegs < 0
					|| motorcycleOutOfScopeLegs < 0
					|| unresolvedLegs < 0
					|| physicalPassageEvents < 0
					|| !Double.isFinite(confirmedTollHkd)
					|| confirmedTollHkd < 0.0
					|| inferredFromDistance != 0
					|| candidateFallbacks != 0
					|| fixedOwnershipCharges != 0
					|| parkingCharges != 0) {
				throw new IllegalArgumentException(
						"Invalid Stage 8B confirmed-toll schedule audit.");
			}
		}
	}

	private final Id<Person> personId;
	private final List<LegToll> legTolls;
	private final Audit audit;

	private HongKongCarTollPersonSchedule(
			Id<Person> personId,
			List<LegToll> legTolls) {
		this.personId = Objects.requireNonNull(personId, "personId");
		this.legTolls = List.copyOf(legTolls);
		this.audit = audit(this.legTolls);
		if (audit.unresolvedLegs() != 0) {
			throw new IllegalStateException(
					"Stage 8B confirmed-toll source mapping is incomplete for person "
							+ personId + "; unresolved legs="
							+ audit.unresolvedLegs()
							+ ". Unconfirmed toll is not scored as zero.");
		}
	}

	public static HongKongCarTollPersonSchedule fromSelectedPlan(
			Person person,
			HongKongCarTollCostCatalog catalog) {
		Objects.requireNonNull(person, "person");
		Objects.requireNonNull(catalog, "catalog");
		if (person.getSelectedPlan() == null) {
			throw new IllegalArgumentException(
					"Person has no selected plan: " + person.getId());
		}
		List<LegToll> tolls = new ArrayList<>();
		int mainActivityIndex = -1;
		int carOrdinal = 0;
		for (PlanElement element : person.getSelectedPlan().getPlanElements()) {
			if (element instanceof Activity activity) {
				if (!isInteraction(activity)) {
					mainActivityIndex++;
				}
				continue;
			}
			if (!(element instanceof Leg leg) || !"car".equals(leg.getMode())) {
				continue;
			}
			if (mainActivityIndex < 0) {
				throw new IllegalStateException(
						"Car leg precedes the first main activity for person "
								+ person.getId());
			}
			if (!"car".equals(leg.getRoutingMode())) {
				throw new IllegalStateException(
						"Stage 8B requires mode=car,routingMode=car: person="
								+ person.getId() + ", source_leg_sequence="
								+ mainActivityIndex);
			}
			Route route = Objects.requireNonNull(
					leg.getRoute(),
					"Stage 8B requires a prepared route for every Car leg.");
			double distance = route.getDistance();
			if (!Double.isFinite(distance) || distance < 0.0) {
				throw new IllegalStateException(
						"Stage 8B Car route distance must be finite and nonnegative.");
			}
			var quote = catalog.quote(
					person.getId().toString(), mainActivityIndex);
			if (!quote.confirmed() && !quote.outOfScope()) {
				throw new IllegalStateException(
						"Canonical Car toll source is unconfirmed or unresolved: person="
								+ person.getId() + ", source_leg_sequence="
								+ mainActivityIndex + ", reason="
								+ quote.unresolvedReason());
			}
			if (Math.abs(distance - quote.sourceRouteDistanceM())
					> SOURCE_DISTANCE_TOLERANCE_M) {
				throw new IllegalStateException(
						"Canonical Car toll source route distance mismatch: person="
								+ person.getId() + ", source_leg_sequence="
								+ mainActivityIndex + ", route_m=" + distance
								+ ", source_m=" + quote.sourceRouteDistanceM());
			}
			validateRouteEvidence(route, quote);
			tolls.add(new LegToll(
					carOrdinal,
					mainActivityIndex,
					HongKongCarEnergyPersonSchedule.fingerprint(leg),
					quote));
			carOrdinal++;
		}
		return new HongKongCarTollPersonSchedule(person.getId(), tolls);
	}

	private static void validateRouteEvidence(
			Route route,
			HongKongCarTollCostCatalog.TollQuote quote) {
		if (!(route instanceof NetworkRoute networkRoute)) {
			throw new IllegalStateException(
					"Confirmed toll requires a prepared NetworkRoute; no distance-only inference is allowed.");
		}
		List<String> fullLinkIds = fullLinkIds(networkRoute);
		if (fullLinkIds.size() != quote.sourceFullLinkCount()) {
			throw new IllegalStateException(
					"Canonical toll source full-link count differs from the prepared route.");
		}
		for (var passage : quote.passageEvidence()) {
			if (passage.routeMatchEndIndex() >= fullLinkIds.size()) {
				throw new IllegalStateException(
						"Confirmed toll passage index is outside the prepared route.");
			}
			List<String> span = fullLinkIds.subList(
					passage.routeMatchStartIndex(),
					passage.routeMatchEndIndex() + 1);
			if (!isOrderedSubsequence(span, passage.matchedLinkIds())) {
				throw new IllegalStateException(
						"Confirmed toll facility links do not match the prepared route: facility="
								+ passage.canonicalFacilityId());
			}
		}
	}

	private static boolean isOrderedSubsequence(
			List<String> routeSpan,
			List<String> matchedLinks) {
		int matchedIndex = 0;
		for (String routeLink : routeSpan) {
			if (routeLink.equals(matchedLinks.get(matchedIndex))) {
				matchedIndex++;
				if (matchedIndex == matchedLinks.size()) {
					return true;
				}
			}
		}
		return false;
	}

	private static List<String> fullLinkIds(NetworkRoute route) {
		List<String> links = new ArrayList<>();
		if (route.getStartLinkId() != null) {
			links.add(route.getStartLinkId().toString());
		}
		route.getLinkIds().forEach(link -> links.add(link.toString()));
		if (route.getEndLinkId() != null
				&& (route.getStartLinkId() == null
				|| !route.getEndLinkId().equals(route.getStartLinkId())
				|| !route.getLinkIds().isEmpty())) {
			links.add(route.getEndLinkId().toString());
		}
		return List.copyOf(links);
	}

	public Id<Person> personId() {
		return personId;
	}

	public int size() {
		return legTolls.size();
	}

	public LegToll tollAt(int ordinal) {
		return legTolls.get(ordinal);
	}

	public List<LegToll> legTolls() {
		return legTolls;
	}

	public Audit audit() {
		return audit;
	}

	private static Audit audit(List<LegToll> tolls) {
		long charge = 0;
		long noCharge = 0;
		long outOfScope = 0;
		long unresolved = 0;
		long events = 0;
		double total = 0.0;
		for (LegToll toll : tolls) {
			var quote = toll.quote();
			switch (quote.resolution()) {
				case CONFIRMED_CHARGE -> {
					charge++;
					events += quote.passageEvidence().size();
					total += quote.costHkd();
				}
				case CONFIRMED_NO_CHARGE -> noCharge++;
				case OUT_OF_SCOPE -> outOfScope++;
				case UNRESOLVED -> unresolved++;
			}
		}
		return new Audit(
				tolls.size(), charge, noCharge, outOfScope, unresolved,
				events, total, 0L, 0L, 0L, 0L);
	}

	private static boolean isInteraction(Activity activity) {
		String type = activity.getType();
		return type != null && type.endsWith("interaction");
	}

	private static String requireText(String value, String label) {
		String cleaned = Objects.requireNonNull(value, label).strip();
		if (cleaned.isBlank()) {
			throw new IllegalArgumentException(label + " must not be blank.");
		}
		return cleaned;
	}
}
