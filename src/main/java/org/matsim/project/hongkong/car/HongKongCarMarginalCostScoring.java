package org.matsim.project.hongkong.car;

import org.matsim.api.core.v01.population.Leg;
import org.matsim.project.hongkong.scoring.HongKongScoringComponent;

import java.util.List;
import java.util.Objects;

/** One Car mode owner composing the approved energy and toll subcomponents. */
public final class HongKongCarMarginalCostScoring
		implements HongKongScoringComponent {

	private final HongKongCarEnergyScoring energy;
	private final HongKongCarTollScoring toll;

	public HongKongCarMarginalCostScoring(
			HongKongCarEnergyScoring energy,
			HongKongCarTollScoring toll) {
		this.energy = Objects.requireNonNull(energy, "energy");
		this.toll = Objects.requireNonNull(toll, "toll");
	}

	@Override
	public String componentId() {
		return HongKongCarMarginalCostScoringComponentFactory.COMPONENT_ID;
	}

	public List<String> subcomponentIds() {
		return List.of(energy.componentId(), toll.componentId());
	}

	@Override
	public void handleLeg(Leg leg) {
		energy.handleLeg(leg);
		toll.handleLeg(leg);
	}

	@Override
	public void finish() {
		energy.finish();
		toll.finish();
	}

	@Override
	public double getScore() {
		double score = energy.getScore() + toll.getScore();
		if (!Double.isFinite(score)) {
			throw new IllegalStateException(
					"Combined Car marginal-cost score is non-finite.");
		}
		return score;
	}

	@Override
	public void explainScore(StringBuilder out) {
		out.append("hongKongCarMarginalCost[subcomponents=")
				.append(subcomponentIds())
				.append(",score=").append(getScore()).append("]{");
		energy.explainScore(out);
		out.append(';');
		toll.explainScore(out);
		out.append('}');
	}

	HongKongCarEnergyScoring energy() {
		return energy;
	}

	HongKongCarTollScoring toll() {
		return toll;
	}
}
