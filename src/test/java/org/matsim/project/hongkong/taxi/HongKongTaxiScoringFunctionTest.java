package org.matsim.project.hongkong.taxi;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.core.config.Config;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.router.TripStructureUtils;
import org.matsim.core.scoring.ScoringFunction;
import org.matsim.core.scoring.ScoringFunctionFactory;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotSame;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HongKongTaxiScoringFunctionTest {

	private static final double TOLERANCE = 1e-12;

	@Test
	void wrapperForwardsEveryStandardScoringCall() {
		Person person = HongKongTaxiTestFixtures.person("forwarding-person");
		RecordingScoringFunction delegate = new RecordingScoringFunction(10.0);
		HongKongTaxiScoringFunction scoring = new HongKongTaxiScoringFunction(
				delegate,
				new HongKongTaxiFareScoring(
						person.getId(),
						HongKongTaxiScoringParameters.centralV1()
				)
		);
		Activity activity = PopulationUtils.createActivityFromCoord("home", new Coord(0.0, 0.0));
		Leg leg = HongKongTaxiTestFixtures.taxiLeg(100.0);
		Event event = new Event(123.0) {
			@Override
			public String getEventType() {
				return "synthetic-test-event";
			}
		};
		TripStructureUtils.Trip trip = syntheticTrip();

		scoring.handleActivity(activity);
		scoring.handleLeg(leg);
		scoring.addMoney(-7.0);
		scoring.addScore(2.0);
		scoring.agentStuck(456.0);
		scoring.handleEvent(event);
		scoring.handleTrip(trip);
		scoring.finish();

		assertEquals(1, delegate.activityCalls);
		assertEquals(1, delegate.legCalls);
		assertEquals(1, delegate.moneyCalls);
		assertEquals(1, delegate.addScoreCalls);
		assertEquals(1, delegate.stuckCalls);
		assertEquals(1, delegate.eventCalls);
		assertEquals(1, delegate.tripCalls);
		assertEquals(1, delegate.finishCalls);
		assertEquals(7.0, scoring.getScore(), TOLERANCE);

		StringBuilder explanation = new StringBuilder();
		scoring.explainScore(explanation);
		assertTrue(explanation.toString().contains("delegateScore=12.0"));
		assertTrue(explanation.toString().contains("hongKongTaxiFare"));
	}

	@Test
	void totalScoreIsExactlyDelegatePlusFareScore() {
		Person person = HongKongTaxiTestFixtures.person("total-score-person");
		RecordingScoringFunction delegate = new RecordingScoringFunction(7.5);
		HongKongTaxiScoringFunction scoring = new HongKongTaxiScoringFunction(
				delegate,
				new HongKongTaxiFareScoring(
						person.getId(),
						HongKongTaxiScoringParameters.centralV1()
				)
		);
		scoring.handleLeg(HongKongTaxiTestFixtures.taxiLeg(98.3));
		assertEquals(7.5 - 4.915, scoring.getScore(), TOLERANCE);
	}

	@Test
	void globalMarginalUtilityOfMoneyDoesNotChangeCustomFareScore() {
		Config lowMoneyUtility = HongKongTaxiTestFixtures.safeConfig();
		lowMoneyUtility.scoring().setMarginalUtilityOfMoney(0.01);
		Config highMoneyUtility = HongKongTaxiTestFixtures.safeConfig();
		highMoneyUtility.scoring().setMarginalUtilityOfMoney(100.0);
		ScoringFunctionFactory zeroDelegate = person -> new RecordingScoringFunction(0.0);
		HongKongTaxiScoringParameters parameters = HongKongTaxiScoringParameters.centralV1();

		ScoringFunction low = new HongKongTaxiScoringFunctionFactory(
				zeroDelegate,
				lowMoneyUtility,
				parameters
		).createNewScoringFunction(HongKongTaxiTestFixtures.person("low-money"));
		ScoringFunction high = new HongKongTaxiScoringFunctionFactory(
				zeroDelegate,
				highMoneyUtility,
				parameters
		).createNewScoringFunction(HongKongTaxiTestFixtures.person("high-money"));

		low.handleLeg(HongKongTaxiTestFixtures.taxiLeg(100.0));
		high.handleLeg(HongKongTaxiTestFixtures.taxiLeg(100.0));
		assertEquals(-5.0, low.getScore(), TOLERANCE);
		assertEquals(low.getScore(), high.getScore(), 0.0);
	}

	@Test
	void factoryCreatesIndependentFareStateForEachPerson() {
		Config config = HongKongTaxiTestFixtures.safeConfig();
		ScoringFunctionFactory zeroDelegate = person -> new RecordingScoringFunction(0.0);
		HongKongTaxiScoringFunctionFactory factory = new HongKongTaxiScoringFunctionFactory(
				zeroDelegate,
				config,
				HongKongTaxiScoringParameters.centralV1()
		);
		ScoringFunction first = factory.createNewScoringFunction(
				HongKongTaxiTestFixtures.person("first")
		);
		ScoringFunction second = factory.createNewScoringFunction(
				HongKongTaxiTestFixtures.person("second")
		);
		assertNotSame(first, second);

		first.handleLeg(HongKongTaxiTestFixtures.taxiLeg(100.0));
		assertEquals(-5.0, first.getScore(), TOLERANCE);
		assertEquals(0.0, second.getScore(), 0.0);
		second.handleLeg(HongKongTaxiTestFixtures.taxiLeg(24.0));
		assertEquals(-1.2, second.getScore(), TOLERANCE);
		assertEquals(-5.0, first.getScore(), TOLERANCE);
	}

	private static TripStructureUtils.Trip syntheticTrip() {
		Plan plan = PopulationUtils.createPlan();
		plan.addActivity(PopulationUtils.createActivityFromCoord("home", new Coord(0.0, 0.0)));
		plan.addLeg(PopulationUtils.createLeg("walk"));
		plan.addActivity(PopulationUtils.createActivityFromCoord("work", new Coord(1.0, 1.0)));
		return TripStructureUtils.getTrips(plan).getFirst();
	}

	private static final class RecordingScoringFunction implements ScoringFunction {

		private double score;
		private int activityCalls;
		private int legCalls;
		private int moneyCalls;
		private int addScoreCalls;
		private int stuckCalls;
		private int eventCalls;
		private int tripCalls;
		private int finishCalls;

		private RecordingScoringFunction(double score) {
			this.score = score;
		}

		@Override
		public void handleActivity(Activity activity) {
			activityCalls++;
		}

		@Override
		public void handleLeg(Leg leg) {
			legCalls++;
		}

		@Override
		public void agentStuck(double time) {
			stuckCalls++;
		}

		@Override
		public void addMoney(double amount) {
			moneyCalls++;
		}

		@Override
		public void addScore(double amount) {
			addScoreCalls++;
			score += amount;
		}

		@Override
		public void finish() {
			finishCalls++;
		}

		@Override
		public double getScore() {
			return score;
		}

		@Override
		public void handleEvent(Event event) {
			eventCalls++;
		}

		@Override
		public void handleTrip(TripStructureUtils.Trip trip) {
			tripCalls++;
		}

		@Override
		public void explainScore(StringBuilder out) {
			out.append("delegateScore=").append(score);
		}
	}
}
