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

/**
 * Selected-plan-ordered Car energy schedule keyed to the canonical
 * {@code person_id + leg_sequence} source contract.
 */
public final class HongKongCarEnergyPersonSchedule {

	private static final double SOURCE_DISTANCE_TOLERANCE_M = 1.0e-6;

	public record LegEnergy(
			int carOrdinal,
			int sourceLegSequence,
			String routeFingerprint,
			HongKongCarEnergyCostCatalog.EnergyQuote quote) {

		public LegEnergy {
			if (carOrdinal < 0 || sourceLegSequence < 0) {
				throw new IllegalArgumentException(
						"Car ordinals and source leg sequences must be nonnegative.");
			}
			routeFingerprint = requireText(
					routeFingerprint, "routeFingerprint");
			quote = Objects.requireNonNull(quote, "quote");
		}
	}

	public record Audit(
			long carLegs,
			long resolvedPrivateCarLegs,
			long motorcycleOutOfScopeLegs,
			long unresolvedLegs,
			double resolvedCostHkd,
			long fixedOwnershipCharges,
			long tollCharges,
			long parkingCharges,
			long moneyEvents,
			long tripCallbackCharges) {

		public Audit {
			if (carLegs < 0
					|| resolvedPrivateCarLegs < 0
					|| motorcycleOutOfScopeLegs < 0
					|| unresolvedLegs < 0
					|| !Double.isFinite(resolvedCostHkd)
					|| resolvedCostHkd < 0.0
					|| fixedOwnershipCharges != 0
					|| tollCharges != 0
					|| parkingCharges != 0
					|| moneyEvents != 0
					|| tripCallbackCharges != 0) {
				throw new IllegalArgumentException(
						"Invalid Stage 8A Car energy schedule audit.");
			}
		}
	}

	private final Id<Person> personId;
	private final List<LegEnergy> legEnergies;
	private final Audit audit;

	private HongKongCarEnergyPersonSchedule(
			Id<Person> personId,
			List<LegEnergy> legEnergies) {
		this.personId = Objects.requireNonNull(personId, "personId");
		this.legEnergies = List.copyOf(legEnergies);
		this.audit = audit(this.legEnergies);
		if (audit.unresolvedLegs() != 0) {
			throw new IllegalStateException(
					"Stage 8A Car energy source mapping is incomplete for person "
							+ personId + "; unresolved legs="
							+ audit.unresolvedLegs()
							+ ". Missing source is not scored as zero.");
		}
	}

	public static HongKongCarEnergyPersonSchedule fromSelectedPlan(
			Person person,
			HongKongCarEnergyCostCatalog catalog) {
		Objects.requireNonNull(person, "person");
		Objects.requireNonNull(catalog, "catalog");
		if (person.getSelectedPlan() == null) {
			throw new IllegalArgumentException(
					"Person has no selected plan: " + person.getId());
		}
		List<LegEnergy> energies = new ArrayList<>();
		int mainActivityIndex = -1;
		int carOrdinal = 0;
		for (PlanElement element :
				person.getSelectedPlan().getPlanElements()) {
			if (element instanceof Activity activity) {
				if (!isInteraction(activity)) {
					mainActivityIndex++;
				}
				continue;
			}
			if (!(element instanceof Leg leg)
					|| !"car".equals(leg.getMode())) {
				continue;
			}
			if (mainActivityIndex < 0) {
				throw new IllegalStateException(
						"Car leg precedes the first main activity for person "
								+ person.getId());
			}
			if (!"car".equals(leg.getRoutingMode())) {
				throw new IllegalStateException(
						"Stage 8A requires mode=car,routingMode=car: person="
								+ person.getId() + ", source_leg_sequence="
								+ mainActivityIndex);
			}
			Route route = Objects.requireNonNull(
					leg.getRoute(),
					"Stage 8A requires a prepared route for every Car leg.");
			double distance = route.getDistance();
			if (!Double.isFinite(distance) || distance < 0.0) {
				throw new IllegalStateException(
						"Stage 8A Car route distance must be finite and nonnegative.");
			}
			HongKongCarEnergyCostCatalog.EnergyQuote quote =
					catalog.quote(
							person.getId().toString(),
							mainActivityIndex);
			if (!quote.resolved() && !quote.outOfScope()) {
				throw new IllegalStateException(
						"Canonical Car energy source is unresolved: person="
								+ person.getId() + ", source_leg_sequence="
								+ mainActivityIndex + ", reason="
								+ quote.unresolvedReason());
			}
			if (Math.abs(distance - quote.sourceRouteDistanceM())
					> SOURCE_DISTANCE_TOLERANCE_M) {
				throw new IllegalStateException(
						"Canonical Car energy source route distance mismatch: person="
								+ person.getId() + ", source_leg_sequence="
								+ mainActivityIndex + ", route_m="
								+ distance + ", source_m="
								+ quote.sourceRouteDistanceM());
			}
			energies.add(new LegEnergy(
					carOrdinal,
					mainActivityIndex,
					fingerprint(leg),
					quote));
			carOrdinal++;
		}
		return new HongKongCarEnergyPersonSchedule(
				person.getId(), energies);
	}

	static String fingerprint(Leg leg) {
		Objects.requireNonNull(leg, "leg");
		Route route = leg.getRoute();
		StringBuilder result = new StringBuilder()
				.append(String.valueOf(leg.getMode()))
				.append('|')
				.append(String.valueOf(leg.getRoutingMode()));
		if (route == null) {
			return result.append("|<missing-route>").toString();
		}
		result.append('|')
				.append(String.valueOf(route.getStartLinkId()))
				.append('>')
				.append(String.valueOf(route.getEndLinkId()))
				.append("|distance_bits=")
				.append(Double.doubleToLongBits(route.getDistance()));
		if (route instanceof NetworkRoute networkRoute) {
			result.append("|links=");
			for (Id<?> linkId : networkRoute.getLinkIds()) {
				result.append(linkId).append(',');
			}
			result.append("|vehicle=")
					.append(String.valueOf(networkRoute.getVehicleId()));
		} else {
			result.append("|description=")
					.append(String.valueOf(route.getRouteDescription()));
		}
		return result.toString();
	}

	public Id<Person> personId() {
		return personId;
	}

	public int size() {
		return legEnergies.size();
	}

	public LegEnergy energyAt(int ordinal) {
		return legEnergies.get(ordinal);
	}

	public List<LegEnergy> legEnergies() {
		return legEnergies;
	}

	public Audit audit() {
		return audit;
	}

	private static Audit audit(List<LegEnergy> energies) {
		long resolved = 0L;
		long outOfScope = 0L;
		long unresolved = 0L;
		double total = 0.0;
		for (LegEnergy energy : energies) {
			var quote = energy.quote();
			if (quote.resolved()) {
				resolved++;
				total += quote.costHkd();
			} else if (quote.outOfScope()) {
				outOfScope++;
			} else {
				unresolved++;
			}
		}
		return new Audit(
				energies.size(),
				resolved,
				outOfScope,
				unresolved,
				total,
				0L,
				0L,
				0L,
				0L,
				0L);
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
