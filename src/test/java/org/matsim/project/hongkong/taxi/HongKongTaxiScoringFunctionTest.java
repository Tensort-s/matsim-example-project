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
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HongKongTaxiScoringFunctionTest {

	private static final double TOLERANCE = 1e-12;

	@Test
	void wrapperForwardsEveryStandardScoringCall() {
		Person person = personWithTaxiFares("forwarding-person", 100.0);
		RecordingScoringFunction delegate = new RecordingScoringFunction(10.0);
		HongKongTaxiScoringFunction scoring = new HongKongTaxiScoringFunction(
				delegate,
				fareScoringFor(person)
		);
		Activity activity = PopulationUtils.createActivityFromCoord("home", new Coord(0.0, 0.0));
		Leg leg = experiencedTaxiLeg();
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
		Person person = personWithTaxiFares("total-score-person", 98.3);
		RecordingScoringFunction delegate = new RecordingScoringFunction(7.5);
		HongKongTaxiScoringFunction scoring = new HongKongTaxiScoringFunction(
				delegate,
				fareScoringFor(person)
		);
		scoring.handleLeg(experiencedTaxiLeg());
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

		Person lowPerson = personWithTaxiFares("low-money", 100.0);
		Person highPerson = personWithTaxiFares("high-money", 100.0);
		ScoringFunction low = new HongKongTaxiScoringFunctionFactory(
				zeroDelegate,
				lowMoneyUtility,
				parameters
		).createNewScoringFunction(lowPerson);
		ScoringFunction high = new HongKongTaxiScoringFunctionFactory(
				zeroDelegate,
				highMoneyUtility,
				parameters
		).createNewScoringFunction(highPerson);

		low.handleLeg(experiencedTaxiLeg());
		high.handleLeg(experiencedTaxiLeg());
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
				personWithTaxiFares("first", 100.0)
		);
		ScoringFunction second = factory.createNewScoringFunction(
				personWithTaxiFares("second", 24.0)
		);
		assertNotSame(first, second);

		first.handleLeg(experiencedTaxiLeg());
		assertEquals(-5.0, first.getScore(), TOLERANCE);
		assertEquals(0.0, second.getScore(), 0.0);
		second.handleLeg(experiencedTaxiLeg());
		assertEquals(-1.2, second.getScore(), TOLERANCE);
		assertEquals(-5.0, first.getScore(), TOLERANCE);
	}

	@Test
	void factoryCreatesFreshFareCursorForRepeatedScorerCreation() {
		Config config = HongKongTaxiTestFixtures.safeConfig();
		ScoringFunctionFactory zeroDelegate = person -> new RecordingScoringFunction(0.0);
		HongKongTaxiScoringFunctionFactory factory = new HongKongTaxiScoringFunctionFactory(
				zeroDelegate,
				config,
				HongKongTaxiScoringParameters.centralV1()
		);
		Person person = personWithTaxiFares("repeat-person", 100.0);

		ScoringFunction first = factory.createNewScoringFunction(person);
		first.handleLeg(experiencedTaxiLeg());
		first.finish();
		ScoringFunction second = factory.createNewScoringFunction(person);
		second.handleLeg(experiencedTaxiLeg());
		second.finish();

		assertNotSame(first, second);
		assertEquals(-5.0, first.getScore(), TOLERANCE);
		assertEquals(-5.0, second.getScore(), TOLERANCE);
	}

	@Test
	void factoryReadsOnlySelectedPlanAndValidatesItAtCreation() {
		Config config = HongKongTaxiTestFixtures.safeConfig();
		ScoringFunctionFactory zeroDelegate = person -> new RecordingScoringFunction(0.0);
		HongKongTaxiScoringFunctionFactory factory = new HongKongTaxiScoringFunctionFactory(
				zeroDelegate,
				config,
				HongKongTaxiScoringParameters.centralV1()
		);
		Person person = HongKongTaxiTestFixtures.person("selected-plan-person");
		Plan invalidUnselectedPlan = PopulationUtils.createPlan();
		invalidUnselectedPlan.addLeg(PopulationUtils.createLeg("taxi"));
		Plan validSelectedPlan = PopulationUtils.createPlan();
		validSelectedPlan.addLeg(HongKongTaxiTestFixtures.taxiLeg(24.0));
		person.addPlan(invalidUnselectedPlan);
		person.addPlan(validSelectedPlan);
		person.setSelectedPlan(validSelectedPlan);

		ScoringFunction scoring = factory.createNewScoringFunction(person);
		scoring.handleLeg(experiencedTaxiLeg());
		scoring.finish();
		assertEquals(-1.2, scoring.getScore(), TOLERANCE);

		person.setSelectedPlan(invalidUnselectedPlan);
		assertThrows(
				IllegalArgumentException.class,
				() -> factory.createNewScoringFunction(person)
		);
	}

	@Test
	void eventAndTripInterfacesDoNotDuplicateExperiencedLegFareCharge() {
		Person person = personWithTaxiFares("single-interface-person", 100.0);
		HongKongTaxiScoringFunction scoring = new HongKongTaxiScoringFunction(
				new RecordingScoringFunction(0.0),
				fareScoringFor(person)
		);
		Event event = new Event(123.0) {
			@Override
			public String getEventType() {
				return "synthetic-test-event";
			}
		};

		scoring.handleEvent(event);
		scoring.handleTrip(syntheticTrip());
		assertEquals(0.0, scoring.getScore(), 0.0);
		scoring.handleLeg(experiencedTaxiLeg());
		scoring.finish();

		assertEquals(-5.0, scoring.getScore(), TOLERANCE);
	}

	private static HongKongTaxiFareScoring fareScoringFor(Person person) {
		HongKongTaxiScoringParameters parameters = HongKongTaxiScoringParameters.centralV1();
		return new HongKongTaxiFareScoring(
				HongKongTaxiPersonFareSchedule.fromSelectedPlan(person, parameters),
				parameters
		);
	}

	private static Person personWithTaxiFares(String id, double... fares) {
		Person person = HongKongTaxiTestFixtures.person(id);
		Plan selectedPlan = PopulationUtils.createPlan();
		for (double fare : fares) {
			selectedPlan.addLeg(HongKongTaxiTestFixtures.taxiLeg(fare));
		}
		person.addPlan(selectedPlan);
		person.setSelectedPlan(selectedPlan);
		return person;
	}

	private static Leg experiencedTaxiLeg() {
		Leg leg = PopulationUtils.createLeg(HongKongTaxiScoringParameters.TAXI_MODE);
		leg.setRoutingMode("taxi");
		return leg;
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
