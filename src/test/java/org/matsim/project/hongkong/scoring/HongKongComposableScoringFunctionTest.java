package org.matsim.project.hongkong.scoring;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.router.TripStructureUtils;
import org.matsim.core.scoring.ScoringFunction;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;

class HongKongComposableScoringFunctionTest {

	@Test
	void standardDelegateUsesSchoolBusModeForPhysicalPtExperiencedLeg() {
		RecordingScoring delegate = new RecordingScoring();
		RecordingComponent component = new RecordingComponent();
		HongKongComposableScoringFunction scoring = new HongKongComposableScoringFunction(
				delegate, List.of(component));
		Leg leg = PopulationUtils.createLeg("pt");
		leg.setRoutingMode("school_bus");

		scoring.handleLeg(leg);

		assertEquals("pt", component.mode);
		assertEquals("school_bus", delegate.mode);
		assertEquals("pt", leg.getMode());
	}

	private static final class RecordingComponent implements HongKongScoringComponent {
		private String mode;

		@Override public String componentId() { return "recording"; }
		@Override public void handleLeg(Leg leg) { mode = leg.getMode(); }
		@Override public double getScore() { return 0.0; }
	}

	private static final class RecordingScoring implements ScoringFunction {
		private String mode;

		@Override public void handleActivity(Activity activity) { }
		@Override public void handleLeg(Leg leg) { mode = leg.getMode(); }
		@Override public void agentStuck(double time) { }
		@Override public void addMoney(double amount) { }
		@Override public void addScore(double amount) { }
		@Override public void finish() { }
		@Override public double getScore() { return 0.0; }
		@Override public void handleEvent(Event event) { }
		@Override public void handleTrip(TripStructureUtils.Trip trip) { }
		@Override public void explainScore(StringBuilder out) { }
	}
}
