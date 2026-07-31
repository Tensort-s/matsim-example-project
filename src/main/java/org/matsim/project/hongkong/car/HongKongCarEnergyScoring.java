package org.matsim.project.hongkong.car;

import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.project.hongkong.scoring.HongKongScoringComponent;

import java.util.Objects;

/**
 * Exactly-once scorer for the Stage 8A Car fuel-or-electricity component.
 *
 * <p>Only {@link #handleLeg(Leg)} can add a cost. Money, event, trip and
 * external-score callbacks remain inert through the component interface.</p>
 */
public final class HongKongCarEnergyScoring
		implements HongKongScoringComponent {

	private final Id<Person> personId;
	private final HongKongCarEnergyPersonSchedule energySchedule;
	private final double marginalUtilityOfMoney;
	private double score;
	private double chargedEnergyHkd;
	private long resolvedPrivateCarLegs;
	private long motorcycleOutOfScopeLegs;
	private int consumedCarLegs;
	private boolean finished;

	public HongKongCarEnergyScoring(
			HongKongCarEnergyPersonSchedule energySchedule,
			double marginalUtilityOfMoney) {
		this.energySchedule =
				Objects.requireNonNull(energySchedule, "energySchedule");
		this.personId = energySchedule.personId();
		if (!Double.isFinite(marginalUtilityOfMoney)
				|| marginalUtilityOfMoney < 0.0) {
			throw new IllegalArgumentException(
					"Existing MATSim marginalUtilityOfMoney must be finite and nonnegative.");
		}
		this.marginalUtilityOfMoney = marginalUtilityOfMoney;
	}

	@Override
	public String componentId() {
		return HongKongCarEnergyScoringComponentFactory.COMPONENT_ID;
	}

	@Override
	public void handleLeg(Leg leg) {
		Objects.requireNonNull(leg, "leg");
		if (!"car".equals(leg.getMode())) {
			return;
		}
		if (finished) {
			throw mismatch(
					leg,
					"experienced Car leg received after scoring was finished");
		}
		if (!"car".equals(leg.getRoutingMode())) {
			throw mismatch(
					leg,
					"experienced Car leg must have routingMode=car");
		}
		if (consumedCarLegs >= energySchedule.size()) {
			throw mismatch(
					leg,
					"experienced Car leg has no selected-plan energy record");
		}
		HongKongCarEnergyPersonSchedule.LegEnergy expected =
				energySchedule.energyAt(consumedCarLegs);
		String actualFingerprint =
				HongKongCarEnergyPersonSchedule.fingerprint(leg);
		if (!expected.routeFingerprint().equals(actualFingerprint)) {
			throw mismatch(
					leg,
					"experienced Car route fingerprint differs from selected-plan source mapping");
		}

		var quote = expected.quote();
		if (quote.resolved()) {
			double contribution =
					-quote.costHkd() * marginalUtilityOfMoney;
			if (!Double.isFinite(contribution)) {
				throw mismatch(
						leg,
						"Car energy cost produced a non-finite score");
			}
			score += contribution;
			chargedEnergyHkd += quote.costHkd();
			resolvedPrivateCarLegs++;
		} else if (quote.outOfScope()) {
			motorcycleOutOfScopeLegs++;
		} else {
			throw mismatch(
					leg,
					"unresolved canonical Car energy record reached scoring");
		}
		if (!Double.isFinite(score)
				|| !Double.isFinite(chargedEnergyHkd)) {
			throw mismatch(
					leg,
					"cumulative Car energy score or cost became non-finite");
		}
		consumedCarLegs++;
	}

	@Override
	public void finish() {
		if (consumedCarLegs != energySchedule.size()) {
			throw mismatch(
					null,
					"scoring finished before every selected-plan Car energy record was consumed");
		}
		finished = true;
	}

	@Override
	public double getScore() {
		if (!Double.isFinite(score)) {
			throw new IllegalStateException(
					"Hong Kong Car energy score is non-finite for person "
							+ personId);
		}
		return score;
	}

	@Override
	public void explainScore(StringBuilder out) {
		out.append("hongKongCarEnergy[person_id=")
				.append(personId)
				.append(",consumedCarLegs=")
				.append(consumedCarLegs)
				.append(",expectedCarLegs=")
				.append(energySchedule.size())
				.append(",resolvedPrivateCarLegs=")
				.append(resolvedPrivateCarLegs)
				.append(",motorcycleOutOfScopeLegs=")
				.append(motorcycleOutOfScopeLegs)
				.append(",chargedEnergyHkd=")
				.append(chargedEnergyHkd)
				.append(",marginalUtilityOfMoney=")
				.append(marginalUtilityOfMoney)
				.append(",tollCharges=0")
				.append(",parkingCharges=0")
				.append(",fixedOwnershipCharges=0")
				.append(",moneyEventsEmitted=0")
				.append(",tripCallbackCharges=0")
				.append(",score=")
				.append(score)
				.append(']');
	}

	public int consumedCarLegs() {
		return consumedCarLegs;
	}

	public long resolvedPrivateCarLegs() {
		return resolvedPrivateCarLegs;
	}

	public long motorcycleOutOfScopeLegs() {
		return motorcycleOutOfScopeLegs;
	}

	public double chargedEnergyHkd() {
		return chargedEnergyHkd;
	}

	private IllegalStateException mismatch(Leg actualLeg, String reason) {
		return new IllegalStateException(
				"Hong Kong Car energy schedule mismatch: person_id="
						+ personId + ", car_ordinal=" + consumedCarLegs
						+ ", expected_count=" + energySchedule.size()
						+ ", actual_mode="
						+ (actualLeg == null
						? "<finish>"
						: String.valueOf(actualLeg.getMode()))
						+ ", actual_routingMode="
						+ (actualLeg == null
						? "<none>"
						: String.valueOf(actualLeg.getRoutingMode()))
						+ ", reason=" + reason);
	}
}
