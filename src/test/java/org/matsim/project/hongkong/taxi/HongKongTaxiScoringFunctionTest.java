package org.matsim.project.hongkong.taxi;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.events.PersonMoneyEvent;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.core.config.Config;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.router.TripStructureUtils;
import org.matsim.core.scoring.ScoringFunction;
import org.matsim.core.scoring.ScoringFunctionFactory;
import org.matsim.project.hongkong.scoring.HongKongComposableScoringFunction;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HongKongTaxiScoringFunctionTest {

	private static final double TOLERANCE = 1e-12;

	@Test
	void wrapperForwardsEveryStandardScoringCall() {
		Person person = personWithTaxiRoutes("forwarding-person", 9_000.0);
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
		assertEquals(6.875, scoring.getScore(), TOLERANCE);

		StringBuilder explanation = new StringBuilder();
		scoring.explainScore(explanation);
		assertTrue(explanation.toString().contains("delegateScore=12.0"));
		assertTrue(explanation.toString().contains("hongKongTaxiFare"));
	}

	@Test
	void totalScoreIsExactlyDelegatePlusFareScore() {
		Person person = personWithTaxiRoutes("total-score-person", 8_600.0);
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

		Person lowPerson = personWithTaxiRoutes("low-money", 9_000.0);
		Person highPerson = personWithTaxiRoutes("high-money", 9_000.0);
		ScoringFunction low = new HongKongTaxiScoringFunctionFactory(
				zeroDelegate,
				lowMoneyUtility,
				parameters,
				new HongKongTaxiFareCalculator()
		).createNewScoringFunction(lowPerson);
		ScoringFunction high = new HongKongTaxiScoringFunctionFactory(
				zeroDelegate,
				highMoneyUtility,
				parameters,
				new HongKongTaxiFareCalculator()
		).createNewScoringFunction(highPerson);

		low.handleLeg(experiencedTaxiLeg());
		high.handleLeg(experiencedTaxiLeg());
		assertEquals(-5.125, low.getScore(), TOLERANCE);
		assertEquals(low.getScore(), high.getScore(), 0.0);
	}

	@Test
	void factoryCreatesIndependentFareStateForEachPerson() {
		Config config = HongKongTaxiTestFixtures.safeConfig();
		ScoringFunctionFactory zeroDelegate = person -> new RecordingScoringFunction(0.0);
		HongKongTaxiScoringFunctionFactory factory = new HongKongTaxiScoringFunctionFactory(
				zeroDelegate,
				config,
				HongKongTaxiScoringParameters.centralV1(),
				new HongKongTaxiFareCalculator()
		);
		ScoringFunction first = factory.createNewScoringFunction(
				personWithTaxiRoutes("first", 9_000.0)
		);
		ScoringFunction second = factory.createNewScoringFunction(
				personWithTaxiRoutes("second", 2_000.0)
		);
		assertNotSame(first, second);

		first.handleLeg(experiencedTaxiLeg());
		assertEquals(-5.125, first.getScore(), TOLERANCE);
		assertEquals(0.0, second.getScore(), 0.0);
		second.handleLeg(experiencedTaxiLeg());
		assertEquals(-1.45, second.getScore(), TOLERANCE);
		assertEquals(-5.125, first.getScore(), TOLERANCE);
	}

	@Test
	void factoryCreatesFreshFareCursorForRepeatedScorerCreation() {
		Config config = HongKongTaxiTestFixtures.safeConfig();
		ScoringFunctionFactory zeroDelegate = person -> new RecordingScoringFunction(0.0);
		HongKongTaxiScoringFunctionFactory factory = new HongKongTaxiScoringFunctionFactory(
				zeroDelegate,
				config,
				HongKongTaxiScoringParameters.centralV1(),
				new HongKongTaxiFareCalculator()
		);
		Person person = personWithTaxiRoutes("repeat-person", 9_000.0);

		ScoringFunction first = factory.createNewScoringFunction(person);
		first.handleLeg(experiencedTaxiLeg());
		first.finish();
		ScoringFunction second = factory.createNewScoringFunction(person);
		second.handleLeg(experiencedTaxiLeg());
		second.finish();

		assertNotSame(first, second);
		assertEquals(-5.125, first.getScore(), TOLERANCE);
		assertEquals(-5.125, second.getScore(), TOLERANCE);
	}

	@Test
	void factoryReadsOnlySelectedPlanAndValidatesItAtCreation() {
		Config config = HongKongTaxiTestFixtures.safeConfig();
		ScoringFunctionFactory zeroDelegate = person -> new RecordingScoringFunction(0.0);
		HongKongTaxiScoringFunctionFactory factory = new HongKongTaxiScoringFunctionFactory(
				zeroDelegate,
				config,
				HongKongTaxiScoringParameters.centralV1(),
				new HongKongTaxiFareCalculator()
		);
		Person person = HongKongTaxiTestFixtures.person("selected-plan-person");
		Plan invalidUnselectedPlan = PopulationUtils.createPlan();
		invalidUnselectedPlan.addLeg(PopulationUtils.createLeg("taxi"));
		Plan validSelectedPlan = PopulationUtils.createPlan();
		validSelectedPlan.addLeg(HongKongTaxiTestFixtures.taxiLegForRoute(
				2_000.0, "lantau_taxi", 24.0));
		person.addPlan(invalidUnselectedPlan);
		person.addPlan(validSelectedPlan);
		person.setSelectedPlan(validSelectedPlan);

		ScoringFunction scoring = factory.createNewScoringFunction(person);
		scoring.handleLeg(experiencedTaxiLeg());
		scoring.finish();
		assertEquals(-1.2, scoring.getScore(), TOLERANCE);

		person.setSelectedPlan(invalidUnselectedPlan);
		assertThrows(
				IllegalStateException.class,
				() -> factory.createNewScoringFunction(person)
		);
	}

	@Test
	void eventAndTripInterfacesDoNotDuplicateExperiencedLegFareCharge() {
		Person person = personWithTaxiRoutes("single-interface-person", 9_000.0);
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

		assertEquals(-5.125, scoring.getScore(), TOLERANCE);
	}

	@Test
	void taxiDistanceMoneyAndPersonMoneyEventCannotDuplicateCustomFare() {
		Person person = personWithTaxiRoutes("no-double-money-person", 9_000.0);
		HongKongTaxiScoringFunction scoring = new HongKongTaxiScoringFunction(
				new RecordingScoringFunction(0.0),
				fareScoringFor(person));

		scoring.handleEvent(new PersonMoneyEvent(
				100.0,
				person.getId(),
				-102.5,
				"taxi-fare-test",
				"none",
				"none"));
		assertEquals(0.0, scoring.getScore(), 0.0);
		scoring.handleLeg(experiencedTaxiLeg());
		scoring.finish();

		assertEquals(-5.125, scoring.getScore(), TOLERANCE);
	}

	@Test
	void composableTaxiAdapterIsExactlyEquivalentToPreStage5Wrapper() {
		Person baselinePerson = personWithTaxiRoutes(
				"composition-equivalence-person", 2_000.0, 9_000.0);
		Person composedPerson = personWithTaxiRoutes(
				"composition-equivalence-person", 2_000.0, 9_000.0);
		RecordingScoringFunction baselineDelegate =
				new RecordingScoringFunction(7.25);
		RecordingScoringFunction composedDelegate =
				new RecordingScoringFunction(7.25);
		ScoringFunction baseline = new HongKongTaxiScoringFunction(
				baselineDelegate,
				fareScoringFor(baselinePerson));
		ScoringFunction composed = new HongKongComposableScoringFunction(
				composedDelegate,
				List.of(fareScoringFor(composedPerson)));

		exerciseCompleteScoringSurface(baseline, baselinePerson);
		exerciseCompleteScoringSurface(composed, composedPerson);

		assertEquals(baseline.getScore(), composed.getScore(), 0.0);
		assertEquals(baselineDelegate.activityCalls, composedDelegate.activityCalls);
		assertEquals(baselineDelegate.legCalls, composedDelegate.legCalls);
		assertEquals(baselineDelegate.moneyCalls, composedDelegate.moneyCalls);
		assertEquals(baselineDelegate.addScoreCalls, composedDelegate.addScoreCalls);
		assertEquals(baselineDelegate.stuckCalls, composedDelegate.stuckCalls);
		assertEquals(baselineDelegate.eventCalls, composedDelegate.eventCalls);
		assertEquals(baselineDelegate.tripCalls, composedDelegate.tripCalls);
		assertEquals(baselineDelegate.finishCalls, composedDelegate.finishCalls);

		StringBuilder baselineExplanation = new StringBuilder();
		StringBuilder composedExplanation = new StringBuilder();
		baseline.explainScore(baselineExplanation);
		composed.explainScore(composedExplanation);
		assertEquals(baselineExplanation.toString(), composedExplanation.toString());
	}

	private static void exerciseCompleteScoringSurface(
			ScoringFunction scoring,
			Person person) {
		scoring.handleActivity(PopulationUtils.createActivityFromCoord(
				"home", new Coord(0.0, 0.0)));
		scoring.handleLeg(experiencedTaxiLeg());
		scoring.handleLeg(PopulationUtils.createLeg("walk"));
		scoring.handleEvent(new PersonMoneyEvent(
				100.0,
				person.getId(),
				-29.0,
				"taxi-fare-equivalence",
				"none",
				"none"));
		scoring.handleEvent(new Event(101.0) {
			@Override
			public String getEventType() {
				return "taxi-composition-equivalence";
			}
		});
		scoring.handleTrip(syntheticTrip());
		scoring.addMoney(-3.0);
		scoring.addScore(1.5);
		scoring.agentStuck(500.0);
		scoring.handleLeg(experiencedTaxiLeg());
		scoring.finish();
	}

	private static HongKongTaxiFareScoring fareScoringFor(Person person) {
		HongKongTaxiScoringParameters parameters = HongKongTaxiScoringParameters.centralV1();
		return new HongKongTaxiFareScoring(
				HongKongTaxiPersonFareSchedule.fromSelectedPlan(
						person, new HongKongTaxiFareCalculator()),
				parameters
		);
	}

	private static Person personWithTaxiRoutes(String id, double... distancesMeters) {
		Person person = HongKongTaxiTestFixtures.person(id);
		Plan selectedPlan = PopulationUtils.createPlan();
		for (double distance : distancesMeters) {
			selectedPlan.addLeg(HongKongTaxiTestFixtures.taxiLegForRoute(
					distance, "urban_taxi", 999.9));
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
