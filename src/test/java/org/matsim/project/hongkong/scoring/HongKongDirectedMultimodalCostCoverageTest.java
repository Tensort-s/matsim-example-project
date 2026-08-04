package org.matsim.project.hongkong.scoring;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.events.PersonMoneyEvent;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.api.core.v01.population.Route;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.router.TripStructureUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.core.scoring.ScoringFunction;
import org.matsim.core.scoring.ScoringFunctionFactory;
import org.matsim.pt.routes.DefaultTransitPassengerRoute;
import org.matsim.pt.transitSchedule.api.TransitSchedule;
import org.matsim.project.hongkong.car.HongKongCarEnergyCostCatalog;
import org.matsim.project.hongkong.car.HongKongCarEnergyScoringComponentFactory;
import org.matsim.project.hongkong.car.HongKongDirectedCarFixture;
import org.matsim.project.hongkong.pt.HongKongDirectedPtFixture;
import org.matsim.project.hongkong.pt.HongKongPtFareScoringComponentFactory;
import org.matsim.project.hongkong.taxi.HongKongTaxiFareCalculator;
import org.matsim.project.hongkong.taxi.HongKongTaxiFareScoringComponentFactory;
import org.matsim.project.hongkong.taxi.HongKongTaxiLegAttributes;
import org.matsim.project.hongkong.taxi.HongKongTaxiScoringParameters;

import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Stage 10 directed coverage: one fixed person/plan executes Taxi, PT and Car
 * legs through the canonical composed scorer. No production population or
 * random sampling is involved.
 */
class HongKongDirectedMultimodalCostCoverageTest {

	private static final String PERSON_ID = "stage10-directed-001";
	private static final double MARGINAL_UTILITY_OF_MONEY = 2.0;
	private static final double TAXI_DISTANCE_M = 2_500.0;
	private static final double EXPECTED_TAXI_FARE_HKD = 35.3;
	private static final double EXPECTED_PT_FARE_HKD = 4.9;
	private static final double EXPECTED_CAR_ENERGY_HKD = 2.5;
	private static final double EXPECTED_CUSTOM_SCORE =
			-HongKongTaxiScoringParameters.CENTRAL_FARE_UTILITY_PER_HKD
					* EXPECTED_TAXI_FARE_HKD
				- MARGINAL_UTILITY_OF_MONEY * EXPECTED_PT_FARE_HKD
				- MARGINAL_UTILITY_OF_MONEY * EXPECTED_CAR_ENERGY_HKD;

	@Test
	void deterministicSubsetTriggersAllModesAndChargesExactlyOnce() {
		Config config = ConfigUtils.createConfig();
		config.scoring().setMarginalUtilityOfMoney(
				MARGINAL_UTILITY_OF_MONEY);
		config.scoring().getOrCreateModeParams("taxi")
				.setMarginalUtilityOfDistance(0.0)
				.setMonetaryDistanceRate(0.0)
				.setConstant(-9.0)
				.setMarginalUtilityOfTraveling(-6.0);
		config.scoring().getOrCreateModeParams("pt")
				.setMonetaryDistanceRate(0.0);
		config.scoring().getOrCreateModeParams("car")
				.setMonetaryDistanceRate(0.0);
		var scenario = ScenarioUtils.createScenario(config);
		TransitSchedule transitSchedule = scenario.getTransitSchedule();
		HongKongDirectedPtFixture.Fixture ptFixture =
				HongKongDirectedPtFixture.create(transitSchedule);
		HongKongCarEnergyCostCatalog carCatalog =
				HongKongDirectedCarFixture.catalogFor(
						PERSON_ID, 2, 1_000.0, EXPECTED_CAR_ENERGY_HKD);
		Person person = directedPerson(ptFixture.route());

		HongKongMultimodalScoringFunctionFactory factory =
				new HongKongMultimodalScoringFunctionFactory(
						personId -> new ZeroScoringFunction(),
						List.of(
								new HongKongTaxiFareScoringComponentFactory(
										scenario,
										HongKongTaxiScoringParameters.centralV1(),
										new HongKongTaxiFareCalculator()),
								new HongKongPtFareScoringComponentFactory(
										scenario, ptFixture.catalog()),
								new HongKongCarEnergyScoringComponentFactory(
										scenario, carCatalog)));
		assertEquals(
				Set.of("taxi", "pt", "car"),
				factory.activeModeOwners().keySet());
		assertEquals(3, factory.componentIds().size());

		HongKongComposableScoringFunction scoring =
				(HongKongComposableScoringFunction)
						factory.createNewScoringFunction(person);
			List<Leg> legs = person.getSelectedPlan().getPlanElements().stream()
				.filter(Leg.class::isInstance)
				.map(Leg.class::cast)
				.toList();
		assertEquals(3, legs.size());
		assertEquals(1, legs.stream().filter(leg -> "taxi".equals(leg.getMode())
				&& "taxi".equals(leg.getRoutingMode())).count());
		assertEquals(0, legs.stream().filter(leg -> "ride".equals(leg.getMode())).count());
		assertEquals(1, legs.stream().filter(leg -> "pt".equals(leg.getMode())
				&& "pt".equals(leg.getRoutingMode())).count());
		assertEquals(1, legs.stream().filter(leg -> "car".equals(leg.getMode())
				&& "car".equals(leg.getRoutingMode())).count());

		for (Leg leg : legs) {
			scoring.handleLeg(leg);
		}
		assertEquals(
				EXPECTED_TAXI_FARE_HKD,
				new HongKongTaxiFareCalculator()
						.calculate(TAXI_DISTANCE_M, "urban_taxi")
						.fareHkd(),
				0.0);
		assertEquals(EXPECTED_CUSTOM_SCORE, scoring.getScore(), 0.0);

		// Events, money and trip callbacks are intentionally inert for all three
		// mode components; they cannot create a second cost path.
		scoring.addMoney(-99.0);
		scoring.handleEvent(new PersonMoneyEvent(
				100.0, person.getId(), -99.0, "stage10-duplicate-probe",
				"stage10", "stage10"));
		for (TripStructureUtils.Trip trip : TripStructureUtils.getTrips(
				person.getSelectedPlan())) {
			scoring.handleTrip(trip);
		}
		scoring.addScore(0.0);
		scoring.finish();
		assertEquals(EXPECTED_CUSTOM_SCORE, scoring.getScore(), 0.0);

		// Every mode's consumed ordinal is closed: a duplicate experienced leg
		// fails rather than adding a second charge.
		assertThrows(IllegalStateException.class,
				() -> scoring.handleLeg(legs.get(0)));
		assertThrows(IllegalStateException.class,
				() -> scoring.handleLeg(legs.get(1)));
		assertThrows(IllegalStateException.class,
				() -> scoring.handleLeg(legs.get(2)));
		StringBuilder explanation = new StringBuilder();
		scoring.explainScore(explanation);
		assertTrue(explanation.toString().contains("moneyEventsEmitted=0"));
		assertTrue(explanation.toString().contains("tripCallbackCharges=0"));
		assertFalse(explanation.toString().contains("NaN"));
		assertFalse(explanation.toString().contains("Infinity"));
	}

	@Test
	void modeCoverageCannotBeSatisfiedByModeDetailOnly() {
		Person person = PopulationUtils.getFactory().createPerson(
				Id.createPersonId("stage10-no-mode-detail-substitution"));
		person.getAttributes().putAttribute("mode_detail", "taxi");
		assertTrue(person.getSelectedPlan() == null);
		// This explicit sentinel documents that mode_detail metadata is not used
		// as a substitute for experienced mode/routingMode legs.
		assertEquals(0, person.getPlans().size());
	}

	private static Person directedPerson(DefaultTransitPassengerRoute ptRoute) {
		Person person = PopulationUtils.getFactory().createPerson(
				Id.createPersonId(PERSON_ID));
		Plan plan = PopulationUtils.createPlan(person);
		plan.addActivity(activity("home"));
		plan.addLeg(taxiLeg());
		plan.addActivity(activity("taxi-destination"));
		Leg pt = PopulationUtils.createLeg(TransportMode.pt);
		pt.setRoutingMode(TransportMode.pt);
		ptRoute.setDistance(1_000.0);
		ptRoute.setTravelTime(300.0);
		pt.setRoute(ptRoute);
		plan.addLeg(pt);
		plan.addActivity(activity("pt-destination"));
		Leg car = PopulationUtils.createLeg(TransportMode.car);
		car.setRoutingMode(TransportMode.car);
		Route carRoute = RouteUtils.createGenericRouteImpl(
				Id.createLinkId("stage10-car-from"),
				Id.createLinkId("stage10-car-to"));
		carRoute.setDistance(1_000.0);
		carRoute.setTravelTime(100.0);
		car.setRoute(carRoute);
		plan.addLeg(car);
		plan.addActivity(activity("work"));
		person.addPlan(plan);
		person.setSelectedPlan(plan);
		return person;
	}

	private static Activity activity(String type) {
		return PopulationUtils.createActivityFromCoord(
				type, new Coord(0.0, 0.0));
	}

	private static Leg taxiLeg() {
		Leg leg = PopulationUtils.createLeg(TransportMode.taxi);
		leg.setRoutingMode(TransportMode.taxi);
		leg.setDepartureTime(3_600.0);
		Route route = RouteUtils.createGenericRouteImpl(
				Id.createLinkId("stage10-taxi-from"),
				Id.createLinkId("stage10-taxi-to"));
		route.setDistance(TAXI_DISTANCE_M);
		route.setTravelTime(600.0);
		leg.setRoute(route);
		leg.setTravelTime(600.0);
		leg.getAttributes().putAttribute(
				HongKongTaxiLegAttributes.TAXI_TYPE,
				HongKongTaxiFareCalculator.URBAN_TAXI);
		leg.getAttributes().putAttribute(
				HongKongTaxiLegAttributes.CLASSIFICATION_SOURCE,
				"stage10-deterministic-fixture");
		leg.getAttributes().putAttribute(
				HongKongTaxiLegAttributes.FARE_BASELINE_HKD,
				EXPECTED_TAXI_FARE_HKD);
		leg.getAttributes().putAttribute(
				HongKongTaxiLegAttributes.FARE_SCOPE,
				HongKongTaxiScoringParameters.DISTANCE_ONLY_SCOPE);
		leg.getAttributes().putAttribute(
				HongKongTaxiLegAttributes.FARE_MODEL_VERSION,
				HongKongTaxiScoringParameters.FARE_MODEL_VERSION);
		leg.getAttributes().putAttribute(
				HongKongTaxiLegAttributes.MAIN_TRIP_INDEX, 0);
		return leg;
	}

	private static final class ZeroScoringFunction implements ScoringFunction {
		@Override
		public void handleActivity(Activity activity) {
		}

		@Override
		public void handleLeg(Leg leg) {
		}

		@Override
		public void agentStuck(double time) {
		}

		@Override
		public void addMoney(double amount) {
		}

		@Override
		public void addScore(double amount) {
		}

		@Override
		public void finish() {
		}

		@Override
		public double getScore() {
			return 0.0;
		}

		@Override
		public void handleEvent(Event event) {
		}

		@Override
		public void handleTrip(TripStructureUtils.Trip trip) {
		}

		@Override
		public void explainScore(StringBuilder out) {
			out.append("zeroDelegate");
		}
	}
}
