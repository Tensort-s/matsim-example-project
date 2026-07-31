package org.matsim.project.hongkong.scoring;

import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.core.router.TripStructureUtils;
import org.matsim.core.scoring.ScoringFunction;

/**
 * One person-local contribution to the Hong Kong multimodal scoring
 * composition.
 *
 * <p>Default methods are intentionally inert. A mode component receives only
 * the scoring callbacks it explicitly overrides, so adding an extension seam
 * cannot silently create a charge path.</p>
 */
public interface HongKongScoringComponent extends ScoringFunction {

	String componentId();

	@Override
	default void handleActivity(Activity activity) {
	}

	@Override
	default void handleLeg(Leg leg) {
	}

	@Override
	default void agentStuck(double time) {
	}

	@Override
	default void addMoney(double amount) {
	}

	@Override
	default void addScore(double amount) {
	}

	@Override
	default void finish() {
	}

	@Override
	default void handleEvent(Event event) {
	}

	@Override
	default void handleTrip(TripStructureUtils.Trip trip) {
	}

	@Override
	default void explainScore(StringBuilder out) {
		out.append(componentId()).append("[score=").append(getScore()).append(']');
	}
}
