package org.matsim.project.hongkong.car;

import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.project.hongkong.scoring.HongKongScoringComponent;

import java.util.Objects;

/** Exactly-once scorer for confirmed Stage 8B Car tolls. */
public final class HongKongCarTollScoring implements HongKongScoringComponent {

	private final Id<Person> personId;
	private final HongKongCarTollPersonSchedule tollSchedule;
	private final double marginalUtilityOfMoney;
	private double score;
	private double chargedTollHkd;
	private long confirmedChargeLegs;
	private long confirmedNoChargeLegs;
	private long motorcycleOutOfScopeLegs;
	private long physicalPassageEvents;
	private int consumedCarLegs;
	private boolean finished;

	public HongKongCarTollScoring(
			HongKongCarTollPersonSchedule tollSchedule,
			double marginalUtilityOfMoney) {
		this.tollSchedule = Objects.requireNonNull(tollSchedule, "tollSchedule");
		this.personId = tollSchedule.personId();
		if (!Double.isFinite(marginalUtilityOfMoney)
				|| marginalUtilityOfMoney < 0.0) {
			throw new IllegalArgumentException(
					"Existing MATSim marginalUtilityOfMoney must be finite and nonnegative.");
		}
		this.marginalUtilityOfMoney = marginalUtilityOfMoney;
	}

	@Override
	public String componentId() {
		return HongKongCarTollScoringComponentFactory.COMPONENT_ID;
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
		if (consumedCarLegs >= tollSchedule.size()) {
			throw mismatch(leg, "experienced Car leg has no confirmed-toll record");
		}
		var expected = tollSchedule.tollAt(consumedCarLegs);
		String fingerprint = HongKongCarEnergyPersonSchedule.fingerprint(leg);
		if (!expected.routeFingerprint().equals(fingerprint)) {
			throw mismatch(
					leg,
					"experienced route differs from the confirmed selected-plan toll mapping");
		}
		var quote = expected.quote();
		switch (quote.resolution()) {
			case CONFIRMED_CHARGE -> {
				double contribution =
						-quote.costHkd() * marginalUtilityOfMoney;
				if (!Double.isFinite(contribution)) {
					throw mismatch(leg, "confirmed toll produced a non-finite score");
				}
				score += contribution;
				chargedTollHkd += quote.costHkd();
				confirmedChargeLegs++;
				physicalPassageEvents += quote.passageEvidence().size();
			}
			case CONFIRMED_NO_CHARGE -> confirmedNoChargeLegs++;
			case OUT_OF_SCOPE -> motorcycleOutOfScopeLegs++;
			case UNRESOLVED -> throw mismatch(
					leg, "unconfirmed or unresolved toll reached scoring");
		}
		if (!Double.isFinite(score) || !Double.isFinite(chargedTollHkd)) {
			throw mismatch(leg, "cumulative toll score or cost became non-finite");
		}
		consumedCarLegs++;
	}

	@Override
	public void finish() {
		if (consumedCarLegs != tollSchedule.size()) {
			throw mismatch(
					null,
					"scoring finished before every selected-plan toll record was consumed");
		}
		finished = true;
	}

	@Override
	public double getScore() {
		if (!Double.isFinite(score)) {
			throw new IllegalStateException(
					"Hong Kong Car toll score is non-finite for person " + personId);
		}
		return score;
	}

	@Override
	public void explainScore(StringBuilder out) {
		out.append("hongKongCarConfirmedToll[person_id=")
				.append(personId)
				.append(",consumedCarLegs=").append(consumedCarLegs)
				.append(",expectedCarLegs=").append(tollSchedule.size())
				.append(",confirmedChargeLegs=").append(confirmedChargeLegs)
				.append(",confirmedNoChargeLegs=").append(confirmedNoChargeLegs)
				.append(",motorcycleOutOfScopeLegs=")
				.append(motorcycleOutOfScopeLegs)
				.append(",physicalPassageEvents=").append(physicalPassageEvents)
				.append(",chargedTollHkd=").append(chargedTollHkd)
				.append(",distanceInferredCharges=0")
				.append(",candidateFallbackCharges=0")
				.append(",parkingCharges=0")
				.append(",fixedOwnershipCharges=0")
				.append(",moneyEventsEmitted=0")
				.append(",tripCallbackCharges=0")
				.append(",score=").append(score).append(']');
	}

	public int consumedCarLegs() {
		return consumedCarLegs;
	}

	public double chargedTollHkd() {
		return chargedTollHkd;
	}

	public long confirmedChargeLegs() {
		return confirmedChargeLegs;
	}

	public long confirmedNoChargeLegs() {
		return confirmedNoChargeLegs;
	}

	public long motorcycleOutOfScopeLegs() {
		return motorcycleOutOfScopeLegs;
	}

	public long physicalPassageEvents() {
		return physicalPassageEvents;
	}

	private IllegalStateException mismatch(Leg actualLeg, String reason) {
		return new IllegalStateException(
				"Hong Kong Car confirmed-toll schedule mismatch: person_id="
						+ personId + ", car_ordinal=" + consumedCarLegs
						+ ", expected_count=" + tollSchedule.size()
						+ ", actual_mode="
						+ (actualLeg == null ? "<finish>" : actualLeg.getMode())
						+ ", actual_routingMode="
						+ (actualLeg == null
						? "<none>" : actualLeg.getRoutingMode())
						+ ", reason=" + reason);
	}
}
