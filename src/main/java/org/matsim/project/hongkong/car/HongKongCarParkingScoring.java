package org.matsim.project.hongkong.car;

import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.project.hongkong.scoring.HongKongScoringComponent;

import java.util.Objects;

/** Exactly-once scorer for resolved Stage 8C destination parking. */
public final class HongKongCarParkingScoring
		implements HongKongScoringComponent {

	private final Id<Person> personId;
	private final HongKongCarParkingPersonSchedule parkingSchedule;
	private final double marginalUtilityOfMoney;
	private double score;
	private double chargedParkingHkd;
	private long resolvedChargeLegs;
	private long resolvedLegalZeroLegs;
	private long unresolvedNullLegs;
	private long motorcycleOutOfScopeLegs;
	private int consumedCarLegs;
	private boolean finished;

	public HongKongCarParkingScoring(
			HongKongCarParkingPersonSchedule parkingSchedule,
			double marginalUtilityOfMoney) {
		this.parkingSchedule = Objects.requireNonNull(
				parkingSchedule, "parkingSchedule");
		this.personId = parkingSchedule.personId();
		if (!Double.isFinite(marginalUtilityOfMoney)
				|| marginalUtilityOfMoney < 0.0) {
			throw new IllegalArgumentException(
					"Existing MATSim marginalUtilityOfMoney must be finite and nonnegative.");
		}
		this.marginalUtilityOfMoney = marginalUtilityOfMoney;
	}

	@Override
	public String componentId() {
		return HongKongCarParkingScoringComponentFactory.COMPONENT_ID;
	}

	@Override
	public void handleLeg(Leg leg) {
		Objects.requireNonNull(leg, "leg");
		if (!"car".equals(leg.getMode())) {
			return;
		}
		if (finished) {
			throw mismatch(leg, "experienced Car leg received after finish");
		}
		if (!"car".equals(leg.getRoutingMode())) {
			throw mismatch(leg, "experienced Car leg must have routingMode=car");
		}
		if (consumedCarLegs >= parkingSchedule.size()) {
			throw mismatch(
					leg, "experienced Car leg has no destination-parking record");
		}
		var expected = parkingSchedule.parkingAt(consumedCarLegs);
		String fingerprint = HongKongCarEnergyPersonSchedule.fingerprint(leg);
		if (!expected.routeFingerprint().equals(fingerprint)) {
			throw mismatch(
					leg,
					"experienced route differs from the selected-plan parking mapping");
		}
		var quote = expected.quote();
		switch (quote.resolution()) {
			case RESOLVED_CHARGE -> {
				double contribution =
						-quote.costHkd() * marginalUtilityOfMoney;
				if (!Double.isFinite(contribution)) {
					throw mismatch(
							leg, "resolved parking produced a non-finite score");
				}
				score += contribution;
				chargedParkingHkd += quote.costHkd();
				resolvedChargeLegs++;
			}
			case RESOLVED_LEGAL_ZERO -> resolvedLegalZeroLegs++;
			case UNRESOLVED -> unresolvedNullLegs++;
			case OUT_OF_SCOPE -> motorcycleOutOfScopeLegs++;
		}
		if (!Double.isFinite(score) || !Double.isFinite(chargedParkingHkd)) {
			throw mismatch(
					leg, "cumulative parking score or cost became non-finite");
		}
		consumedCarLegs++;
	}

	@Override
	public void finish() {
		if (consumedCarLegs != parkingSchedule.size()) {
			throw mismatch(
					null,
					"scoring finished before every selected-plan parking record was consumed");
		}
		finished = true;
	}

	@Override
	public double getScore() {
		if (!Double.isFinite(score)) {
			throw new IllegalStateException(
					"Hong Kong destination-parking score is non-finite for person "
							+ personId);
		}
		return score;
	}

	@Override
	public void explainScore(StringBuilder out) {
		out.append("hongKongCarDestinationParking[person_id=")
				.append(personId)
				.append(",consumedCarLegs=").append(consumedCarLegs)
				.append(",expectedCarLegs=").append(parkingSchedule.size())
				.append(",resolvedChargeLegs=").append(resolvedChargeLegs)
				.append(",resolvedLegalZeroLegs=")
				.append(resolvedLegalZeroLegs)
				.append(",unresolvedNullLegs=").append(unresolvedNullLegs)
				.append(",motorcycleOutOfScopeLegs=")
				.append(motorcycleOutOfScopeLegs)
				.append(",chargedParkingHkd=").append(chargedParkingHkd)
				.append(",nearestLocationInferences=0")
				.append(",facilityCandidateFallbacks=0")
				.append(",distanceInferences=0")
				.append(",fixedOwnershipCharges=0")
				.append(",moneyEventsEmitted=0")
				.append(",tripCallbackCharges=0")
				.append(",score=").append(score).append(']');
	}

	public int consumedCarLegs() {
		return consumedCarLegs;
	}

	public double chargedParkingHkd() {
		return chargedParkingHkd;
	}

	public long resolvedChargeLegs() {
		return resolvedChargeLegs;
	}

	public long resolvedLegalZeroLegs() {
		return resolvedLegalZeroLegs;
	}

	public long unresolvedNullLegs() {
		return unresolvedNullLegs;
	}

	public long motorcycleOutOfScopeLegs() {
		return motorcycleOutOfScopeLegs;
	}

	private IllegalStateException mismatch(Leg actualLeg, String reason) {
		return new IllegalStateException(
				"Hong Kong destination-parking schedule mismatch: person_id="
						+ personId + ", car_ordinal=" + consumedCarLegs
						+ ", expected_count=" + parkingSchedule.size()
						+ ", actual_mode="
						+ (actualLeg == null ? "<finish>" : actualLeg.getMode())
						+ ", actual_routingMode="
						+ (actualLeg == null
						? "<none>" : actualLeg.getRoutingMode())
						+ ", reason=" + reason);
	}
}
