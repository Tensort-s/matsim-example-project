package org.matsim.project.hongkong.car;

import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.PlanElement;

import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

/** Selected-plan destination-parking schedule with exact destination identity. */
public final class HongKongCarParkingPersonSchedule {

	private static final double TIME_TOLERANCE_S = 1.0e-6;

	public record LegParking(
			int carOrdinal,
			int sourceLegSequence,
			String routeFingerprint,
			String destinationFingerprint,
			HongKongCarParkingCostCatalog.ParkingQuote quote) {

		public LegParking {
			if (carOrdinal < 0 || sourceLegSequence < 0) {
				throw new IllegalArgumentException(
						"Car ordinals and parking source sequences must be nonnegative.");
			}
			routeFingerprint = requireText(
					routeFingerprint, "routeFingerprint");
			destinationFingerprint = requireText(
					destinationFingerprint, "destinationFingerprint");
			quote = Objects.requireNonNull(quote, "quote");
		}
	}

	public record Audit(
			long carLegs,
			long resolvedChargeLegs,
			long resolvedLegalZeroLegs,
			long unresolvedLegs,
			long motorcycleOutOfScopeLegs,
			double resolvedParkingHkd,
			long nearestLocationInferences,
			long facilityCandidateFallbacks,
			long distanceInferences,
			long fixedOwnershipCharges) {

		public Audit {
			if (carLegs < 0 || resolvedChargeLegs < 0
					|| resolvedLegalZeroLegs < 0 || unresolvedLegs < 0
					|| motorcycleOutOfScopeLegs < 0
					|| !Double.isFinite(resolvedParkingHkd)
					|| resolvedParkingHkd < 0.0
					|| nearestLocationInferences != 0
					|| facilityCandidateFallbacks != 0
					|| distanceInferences != 0
					|| fixedOwnershipCharges != 0) {
				throw new IllegalArgumentException(
						"Invalid Stage 8C destination-parking schedule audit.");
			}
		}
	}

	private final Id<Person> personId;
	private final List<LegParking> legParkings;
	private final Audit audit;

	private HongKongCarParkingPersonSchedule(
			Id<Person> personId,
			List<LegParking> legParkings) {
		this.personId = Objects.requireNonNull(personId, "personId");
		this.legParkings = List.copyOf(legParkings);
		this.audit = audit(this.legParkings);
	}

	public static HongKongCarParkingPersonSchedule fromSelectedPlan(
			Person person,
			HongKongCarParkingCostCatalog catalog) {
		Objects.requireNonNull(person, "person");
		Objects.requireNonNull(catalog, "catalog");
		if (person.getSelectedPlan() == null) {
			throw new IllegalArgumentException(
					"Person has no selected plan: " + person.getId());
		}
		List<PlanElement> elements = person.getSelectedPlan().getPlanElements();
		List<LegParking> parkings = new ArrayList<>();
		int mainActivityIndex = -1;
		int carOrdinal = 0;
		for (int index = 0; index < elements.size(); index++) {
			PlanElement element = elements.get(index);
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
						"Stage 8C requires mode=car,routingMode=car: person="
								+ person.getId() + ", source_leg_sequence="
								+ mainActivityIndex);
			}
			Activity destination = nextMainActivity(elements, index + 1);
			var quote = catalog.quote(
					person.getId().toString(), mainActivityIndex);
			validateDestinationIdentity(person, leg, destination, quote);
			parkings.add(new LegParking(
					carOrdinal,
					mainActivityIndex,
					HongKongCarEnergyPersonSchedule.fingerprint(leg),
					destinationFingerprint(destination),
					quote));
			carOrdinal++;
		}
		return new HongKongCarParkingPersonSchedule(person.getId(), parkings);
	}

	private static void validateDestinationIdentity(
			Person person,
			Leg leg,
			Activity destination,
			HongKongCarParkingCostCatalog.ParkingQuote quote) {
		String facilityId = destination.getFacilityId() == null
				? "" : destination.getFacilityId().toString();
		if (!quote.destinationFacilityId().equals(facilityId)) {
			throw new IllegalStateException(
					"Canonical parking destination facility mismatch: person="
							+ person.getId() + ", source_leg_sequence="
							+ quote.legSequence() + ", plan=" + facilityId
							+ ", source=" + quote.destinationFacilityId());
		}
		if (!quote.destinationActivityType().equals(destination.getType())) {
			throw new IllegalStateException(
					"Canonical parking destination activity mismatch: person="
							+ person.getId() + ", source_leg_sequence="
							+ quote.legSequence());
		}
		if (leg.getDepartureTime().isUndefined()
				|| Math.abs(leg.getDepartureTime().seconds()
				- quote.departureTimeS()) > TIME_TOLERANCE_S) {
			throw new IllegalStateException(
					"Canonical parking departure time differs from the selected plan.");
		}
		double travelTime;
		if (leg.getTravelTime().isDefined()) {
			travelTime = leg.getTravelTime().seconds();
		} else if (leg.getRoute() != null
				&& leg.getRoute().getTravelTime().isDefined()) {
			travelTime = leg.getRoute().getTravelTime().seconds();
		} else {
			throw new IllegalStateException(
					"Stage 8C requires the selected Car travel time used by the parking source.");
		}
		if (!Double.isFinite(travelTime)
				|| Math.abs(travelTime - quote.routeTravelTimeS())
				> TIME_TOLERANCE_S) {
			throw new IllegalStateException(
					"Canonical parking route travel time differs from the selected plan.");
		}
		/*
		 * nextDepartureTimeS belongs to the next departure of the same
		 * physical vehicle.  The current production assignment has one person
		 * per used vehicle, but that person's next Car departure need not
		 * immediately follow this destination activity: intervening non-Car
		 * trips can occur.  It is therefore not the destination-activity end
		 * time.  The catalog validates the vehicle chain; this method validates
		 * the arriving leg and destination identity.
		 */
		if (quote.nextDepartureTimeS() == null && !quote.terminalEvent()) {
			throw new IllegalStateException(
					"A non-terminal parking source is missing its next-departure time.");
		}
	}

	private static Activity nextMainActivity(
			List<PlanElement> elements,
			int start) {
		for (int index = start; index < elements.size(); index++) {
			if (elements.get(index) instanceof Activity activity
					&& !isInteraction(activity)) {
				return activity;
			}
		}
		throw new IllegalStateException(
				"Every Car leg must terminate at an explicit main destination activity.");
	}

	static String destinationFingerprint(Activity activity) {
		Objects.requireNonNull(activity, "activity");
		return String.valueOf(activity.getFacilityId())
				+ "|type=" + String.valueOf(activity.getType())
				+ "|end=" + (activity.getEndTime().isDefined()
				? Double.doubleToLongBits(activity.getEndTime().seconds())
				: "undefined");
	}

	public Id<Person> personId() {
		return personId;
	}

	public int size() {
		return legParkings.size();
	}

	public LegParking parkingAt(int ordinal) {
		return legParkings.get(ordinal);
	}

	public Audit audit() {
		return audit;
	}

	private static Audit audit(List<LegParking> parkings) {
		long charge = 0;
		long zero = 0;
		long unresolved = 0;
		long motorcycle = 0;
		double total = 0.0;
		for (LegParking parking : parkings) {
			var quote = parking.quote();
			switch (quote.resolution()) {
				case RESOLVED_CHARGE -> {
					charge++;
					total += quote.costHkd();
				}
				case RESOLVED_LEGAL_ZERO -> zero++;
				case UNRESOLVED -> unresolved++;
				case OUT_OF_SCOPE -> motorcycle++;
			}
		}
		return new Audit(
				parkings.size(), charge, zero, unresolved, motorcycle,
				total, 0L, 0L, 0L, 0L);
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
