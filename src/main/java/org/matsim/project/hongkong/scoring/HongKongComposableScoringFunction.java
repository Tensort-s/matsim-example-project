package org.matsim.project.hongkong.scoring;

import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.core.router.TripStructureUtils;
import org.matsim.core.scoring.ScoringFunction;

import java.util.HashSet;
import java.util.List;
import java.util.Objects;
import java.util.Set;

/** Standard MATSim scoring plus an ordered, immutable list of mode components. */
public final class HongKongComposableScoringFunction implements ScoringFunction {

	private final ScoringFunction delegate;
	private final List<HongKongScoringComponent> components;

	public HongKongComposableScoringFunction(
			ScoringFunction delegate,
			List<HongKongScoringComponent> components) {
		this.delegate = Objects.requireNonNull(delegate, "delegate");
		this.components = List.copyOf(
				Objects.requireNonNull(components, "components"));
		Set<String> ids = new HashSet<>();
		for (HongKongScoringComponent component : this.components) {
			Objects.requireNonNull(component, "component");
			if (!ids.add(requireIdentifier(component.componentId(), "componentId"))) {
				throw new IllegalArgumentException(
						"Duplicate Hong Kong scoring component id: "
								+ component.componentId());
			}
		}
	}

	public List<String> componentIds() {
		return components.stream()
				.map(HongKongScoringComponent::componentId)
				.toList();
	}

	@Override
	public void handleActivity(Activity activity) {
		delegate.handleActivity(activity);
		components.forEach(component -> component.handleActivity(activity));
	}

	@Override
	public void handleLeg(Leg leg) {
		components.forEach(component -> component.handleLeg(leg));
		delegate.handleLeg(leg);
	}

	@Override
	public void agentStuck(double time) {
		delegate.agentStuck(time);
		components.forEach(component -> component.agentStuck(time));
	}

	@Override
	public void addMoney(double amount) {
		delegate.addMoney(amount);
		components.forEach(component -> component.addMoney(amount));
	}

	@Override
	public void addScore(double amount) {
		delegate.addScore(amount);
		components.forEach(component -> component.addScore(amount));
	}

	@Override
	public void finish() {
		delegate.finish();
		components.forEach(HongKongScoringComponent::finish);
	}

	@Override
	public double getScore() {
		double score = delegate.getScore();
		for (HongKongScoringComponent component : components) {
			score += component.getScore();
		}
		return score;
	}

	@Override
	public void handleEvent(Event event) {
		delegate.handleEvent(event);
		components.forEach(component -> component.handleEvent(event));
	}

	@Override
	public void handleTrip(TripStructureUtils.Trip trip) {
		delegate.handleTrip(trip);
		components.forEach(component -> component.handleTrip(trip));
	}

	@Override
	public void explainScore(StringBuilder out) {
		delegate.explainScore(out);
		for (HongKongScoringComponent component : components) {
			if (!out.isEmpty()) {
				out.append(SCORE_DELIMITER);
			}
			component.explainScore(out);
		}
	}

	private static String requireIdentifier(String value, String name) {
		if (Objects.requireNonNull(value, name).isBlank()) {
			throw new IllegalArgumentException(name + " must not be blank.");
		}
		return value;
	}
}
