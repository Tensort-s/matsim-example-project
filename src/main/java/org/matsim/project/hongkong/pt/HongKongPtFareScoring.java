package org.matsim.project.hongkong.pt;

import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.project.hongkong.scoring.HongKongScoringComponent;

import java.util.Objects;

/**
 * Consumes the selected-plan PT fare schedule exactly once in experienced-leg
 * order.
 *
 * <p>The component charges only resolved canonical segment fares during
 * {@link #handleLeg(Leg)}. Money-event, event, trip and external-money
 * callbacks remain inert through {@link HongKongScoringComponent} defaults,
 * so they cannot create a second charge path.</p>
 */
public final class HongKongPtFareScoring
		implements HongKongScoringComponent {

	private final Id<Person> personId;
	private final HongKongPtPersonFareSchedule fareSchedule;
	private final double marginalUtilityOfMoney;
	private double score;
	private double chargedFareHkd;
	private long resolvedSegments;
	private long unresolvedSegments;
	private int consumedPtLegs;
	private boolean finished;

	public HongKongPtFareScoring(
			HongKongPtPersonFareSchedule fareSchedule,
			double marginalUtilityOfMoney) {
		this.fareSchedule =
				Objects.requireNonNull(fareSchedule, "fareSchedule");
		this.personId = fareSchedule.personId();
		if (!Double.isFinite(marginalUtilityOfMoney)
				|| marginalUtilityOfMoney < 0.0) {
			throw new IllegalArgumentException(
					"Existing MATSim marginalUtilityOfMoney must be finite and nonnegative.");
		}
		this.marginalUtilityOfMoney = marginalUtilityOfMoney;
	}

	@Override
	public String componentId() {
		return HongKongPtFareScoringComponentFactory.COMPONENT_ID;
	}

	@Override
	public void handleLeg(Leg leg) {
		Objects.requireNonNull(leg, "leg");
		if (!"pt".equals(leg.getMode())) {
			return;
		}
		if (finished) {
			throw mismatch(
					leg,
					"experienced PT leg received after scoring was finished");
		}
		if (!"pt".equals(leg.getRoutingMode())) {
			throw mismatch(
					leg,
					"experienced PT leg must have routingMode=pt");
		}
		if (consumedPtLegs >= fareSchedule.size()) {
			throw mismatch(
					leg,
					"experienced PT leg has no selected-plan fare record");
		}

		HongKongPtPersonFareSchedule.LegFare expected =
				fareSchedule.fareAt(consumedPtLegs);
		String actualFingerprint =
				HongKongPtPersonFareSchedule.fingerprint(leg);
		if (!expected.routeFingerprint().equals(actualFingerprint)) {
			throw mismatch(
					leg,
					"experienced PT route fingerprint differs from selected-plan schedule");
		}

		double legFare = expected.resolvedFareHkd();
		double legScore = -legFare * marginalUtilityOfMoney;
		if (!Double.isFinite(legScore)) {
			throw mismatch(
					leg,
					"resolved PT fare produced a non-finite score");
		}
		score += legScore;
		if (!Double.isFinite(score)) {
			throw mismatch(
					leg,
					"cumulative PT fare score became non-finite");
		}
		chargedFareHkd += legFare;
		resolvedSegments += expected.resolvedSegments();
		unresolvedSegments += expected.unresolvedSegments();
		consumedPtLegs++;
	}

	@Override
	public void finish() {
		if (consumedPtLegs != fareSchedule.size()) {
			throw mismatch(
					null,
					"scoring finished before every selected-plan PT fare record was consumed");
		}
		finished = true;
	}

	@Override
	public double getScore() {
		if (!Double.isFinite(score)) {
			throw new IllegalStateException(
					"Hong Kong PT fare score is non-finite for person "
							+ personId);
		}
		return score;
	}

	@Override
	public void explainScore(StringBuilder out) {
		out.append("hongKongPtFare[person_id=")
				.append(personId)
				.append(",consumedPtLegs=")
				.append(consumedPtLegs)
				.append(",expectedPtLegs=")
				.append(fareSchedule.size())
				.append(",resolvedSegments=")
				.append(resolvedSegments)
				.append(",unresolvedSegments=")
				.append(unresolvedSegments)
				.append(",chargedFareHkd=")
				.append(chargedFareHkd)
				.append(",marginalUtilityOfMoney=")
				.append(marginalUtilityOfMoney)
				.append(",moneyEventsEmitted=0")
				.append(",tripCallbackCharges=0")
				.append(",score=")
				.append(score)
				.append(']');
	}

	public int consumedPtLegs() {
		return consumedPtLegs;
	}

	public long resolvedSegments() {
		return resolvedSegments;
	}

	public long unresolvedSegments() {
		return unresolvedSegments;
	}

	public double chargedFareHkd() {
		return chargedFareHkd;
	}

	private IllegalStateException mismatch(Leg actualLeg, String reason) {
		return new IllegalStateException(
				"Hong Kong PT fare schedule mismatch: person_id=" + personId
						+ ", pt_ordinal=" + consumedPtLegs
						+ ", expected_count=" + fareSchedule.size()
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
