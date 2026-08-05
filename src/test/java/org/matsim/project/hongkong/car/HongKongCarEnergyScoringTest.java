package org.matsim.project.hongkong.car;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.api.core.v01.population.Route;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.router.TripStructureUtils;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HongKongCarEnergyScoringTest {

	private static final String SOURCE_PATH =
			"data/transport_costs/hongkong/car_cost_v1/energy_application_v1/"
					+ "car_leg_energy_cost_estimates_base.parquet";
	private static final String SOURCE_SHA =
			"0e0cc3fdd3440b4be8e51ad98289de590af1b479222c8e29b15845055d82f5da";

	@Test
	void privateCarEnergyChargesExactlyOnceAndOtherCallbacksAreInert() {
		Fixture fixture = fixture(
				"private", resolvedQuote("private", 0, 1_000.0, 2.5));
		var factory = new HongKongCarEnergyScoringComponentFactory(
				fixture.catalog, 2.0);
		assertEquals(
				HongKongCarEnergyScoringComponentFactory.COMPONENT_ID,
				factory.componentId());
		assertEquals(java.util.Set.of("car"), factory.activeModes());

		var scoring = (HongKongCarEnergyScoring)
				factory.createComponent(fixture.person);
		scoring.handleLeg(fixture.carLeg);
		assertEquals(-5.0, scoring.getScore(), 0.0);
		assertEquals(2.5, scoring.chargedEnergyHkd(), 0.0);
		assertEquals(1, scoring.resolvedPrivateCarLegs());

		scoring.addMoney(-2.5);
		scoring.addScore(100.0);
		scoring.agentStuck(1_000.0);
		scoring.handleEvent(new Event(1_000.0) {
			@Override
			public String getEventType() {
				return "stage8a_duplicate_probe";
			}
		});
		scoring.handleTrip(TripStructureUtils.getTrips(
				fixture.person.getSelectedPlan()).getFirst());
		assertEquals(-5.0, scoring.getScore(), 0.0);
		assertThrows(
				IllegalStateException.class,
				() -> scoring.handleLeg(fixture.carLeg));
		assertEquals(-5.0, scoring.getScore(), 0.0);
		scoring.finish();

		StringBuilder explanation = new StringBuilder();
		scoring.explainScore(explanation);
		assertTrue(explanation.toString().contains("tollCharges=0"));
		assertTrue(explanation.toString().contains("parkingCharges=0"));
		assertTrue(explanation.toString()
				.contains("fixedOwnershipCharges=0"));
		assertTrue(explanation.toString()
				.contains("moneyEventsEmitted=0"));
		assertTrue(explanation.toString()
				.contains("tripCallbackCharges=0"));
		assertTrue(Double.isFinite(scoring.getScore()));
	}

	@Test
	void motorcycleIsConsumedAsExplicitOutOfScopeWithoutPrivateCarCost() {
		Fixture fixture = fixture(
				"motorcycle",
				motorcycleQuote("motorcycle", 0, 1_000.0));
		var scoring = new HongKongCarEnergyScoring(
				HongKongCarEnergyPersonSchedule.fromSelectedPlan(
						fixture.person, fixture.catalog),
				1.0);
		scoring.handleLeg(fixture.carLeg);
		scoring.finish();
		assertEquals(0.0, scoring.getScore(), 0.0);
		assertEquals(0.0, scoring.chargedEnergyHkd(), 0.0);
		assertEquals(0, scoring.resolvedPrivateCarLegs());
		assertEquals(1, scoring.motorcycleOutOfScopeLegs());
	}

	@Test
	void missingSourceAndRouteDistanceDriftFailClosed() {
		Person missing = personWithCarLeg("missing", 1_000.0);
		var emptyCatalog = HongKongCarEnergyCostCatalog.builder()
				.buildForTests();
		IllegalStateException missingError = assertThrows(
				IllegalStateException.class,
				() -> HongKongCarEnergyPersonSchedule.fromSelectedPlan(
						missing, emptyCatalog));
		assertTrue(missingError.getMessage().contains("unresolved"));

		Fixture mismatch = fixture(
				"mismatch",
				resolvedQuote("mismatch", 0, 2_000.0, 5.0));
		IllegalStateException distanceError = assertThrows(
				IllegalStateException.class,
				() -> HongKongCarEnergyPersonSchedule.fromSelectedPlan(
						mismatch.person, mismatch.catalog));
		assertTrue(distanceError.getMessage()
				.contains("route distance mismatch"));
	}

	@Test
	void sourceLegSequenceMatchesMainActivitiesNotInteractionStages() {
		Person person = PopulationUtils.getFactory().createPerson(
				Id.createPersonId("sequence"));
		Plan plan = PopulationUtils.createPlan(person);
		plan.addActivity(activity("home"));
		plan.addLeg(walkLeg());
		plan.addActivity(activity("pt interaction"));
		plan.addLeg(walkLeg());
		plan.addActivity(activity("work"));
		Leg car = carLeg(750.0);
		plan.addLeg(car);
		plan.addActivity(activity("shop"));
		person.addPlan(plan);
		person.setSelectedPlan(plan);
		var catalog = HongKongCarEnergyCostCatalog.builder()
				.quote(resolvedQuote("sequence", 1, 750.0, 1.5))
				.buildForTests();

		var schedule =
				HongKongCarEnergyPersonSchedule.fromSelectedPlan(
						person, catalog);
		assertEquals(1, schedule.size());
		assertEquals(1, schedule.energyAt(0).sourceLegSequence());
		assertEquals(1.5, schedule.audit().resolvedCostHkd(), 0.0);
	}

	@Test
	void nonzeroStandardCarMonetaryDistanceChargeIsRejectedNotMutated() {
		var config = ConfigUtils.createConfig();
		config.scoring().getOrCreateModeParams("car")
				.setMonetaryDistanceRate(-0.0007);
		IllegalStateException error = assertThrows(
				IllegalStateException.class,
				() -> HongKongCarEnergyScoringComponentFactory
						.requireNoStandardCarMonetaryDistanceCharge(config));
		assertTrue(error.getMessage()
				.contains("neither reinterpret nor mutate"));
		assertEquals(
				-0.0007,
				config.scoring().getModes().get("car")
						.getMonetaryDistanceRate(),
				0.0);

		config.scoring().getModes().get("car")
				.setMonetaryDistanceRate(0.0);
		HongKongCarEnergyScoringComponentFactory
				.requireNoStandardCarMonetaryDistanceCharge(config);
	}

	@Test
	void duplicateKeysAndInvalidCostsFailClosed() {
		var builder = HongKongCarEnergyCostCatalog.builder();
		var quote = resolvedQuote("duplicate", 0, 1_000.0, 2.5);
		builder.quote(quote);
		assertThrows(
				IllegalStateException.class,
				() -> builder.quote(quote));
		assertThrows(
				IllegalArgumentException.class,
				() -> new HongKongCarEnergyCostCatalog.EnergyQuote(
						"invalid", 0, "vehicle", "private_car",
						Double.NaN, "resolved_representative_fleet_average",
						"B", "source", "hash", SOURCE_PATH, SOURCE_SHA,
						1_000.0, false,
						HongKongCarEnergyCostCatalog.Resolution.RESOLVED,
						""));
	}

	@Test
	void untraveledSuffixIsUnchargedAndPreparedRouteReplacementKeepsOrdinalCost() {
		Fixture fixture = fixture(
				"consumption",
				resolvedQuote("consumption", 0, 1_000.0, 2.5));
		var incomplete = new HongKongCarEnergyScoring(
				HongKongCarEnergyPersonSchedule.fromSelectedPlan(
						fixture.person, fixture.catalog),
				1.0);
		incomplete.finish();
		assertEquals(0.0, incomplete.getScore(), 0.0);
		var stuck = new HongKongCarEnergyScoring(
				HongKongCarEnergyPersonSchedule.fromSelectedPlan(
						fixture.person, fixture.catalog), 1.0);

		var rerouted = new HongKongCarEnergyScoring(
				HongKongCarEnergyPersonSchedule.fromSelectedPlan(
						fixture.person, fixture.catalog),
				1.0);
		fixture.carLeg.getRoute().setDistance(1_001.0);
		rerouted.handleLeg(fixture.carLeg);
		rerouted.finish();
		assertEquals(1, rerouted.consumedCarLegs());
		assertEquals(-2.5, rerouted.getScore(), 0.0);

		stuck.agentStuck(10_000.0);
		stuck.finish();
		assertEquals(0, stuck.consumedCarLegs());
		assertEquals(0.0, stuck.getScore(), 0.0);
	}

	private static Fixture fixture(
			String personId,
			HongKongCarEnergyCostCatalog.EnergyQuote quote) {
		Person person = personWithCarLeg(personId, 1_000.0);
		var catalog = HongKongCarEnergyCostCatalog.builder()
				.quote(quote)
				.buildForTests();
		Leg car = (Leg) person.getSelectedPlan()
				.getPlanElements().get(1);
		return new Fixture(person, car, catalog);
	}

	private static Person personWithCarLeg(
			String id,
			double distanceM) {
		Person person = PopulationUtils.getFactory().createPerson(
				Id.createPersonId(id));
		Plan plan = PopulationUtils.createPlan(person);
		plan.addActivity(activity("home"));
		plan.addLeg(carLeg(distanceM));
		plan.addActivity(activity("work"));
		person.addPlan(plan);
		person.setSelectedPlan(plan);
		return person;
	}

	private static Activity activity(String type) {
		return PopulationUtils.createActivityFromCoord(
				type, new Coord(0.0, 0.0));
	}

	private static Leg carLeg(double distanceM) {
		Leg leg = PopulationUtils.createLeg(TransportMode.car);
		leg.setRoutingMode(TransportMode.car);
		Route route = RouteUtils.createGenericRouteImpl(
				Id.createLinkId("from"), Id.createLinkId("to"));
		route.setDistance(distanceM);
		route.setTravelTime(100.0);
		leg.setRoute(route);
		return leg;
	}

	private static Leg walkLeg() {
		Leg leg = PopulationUtils.createLeg(TransportMode.walk);
		leg.setRoutingMode(TransportMode.walk);
		return leg;
	}

	private static HongKongCarEnergyCostCatalog.EnergyQuote resolvedQuote(
			String personId,
			int legSequence,
			double distanceM,
			double costHkd) {
		return new HongKongCarEnergyCostCatalog.EnergyQuote(
				personId,
				legSequence,
				"vehicle-" + personId,
				"private_car",
				costHkd,
				"resolved_representative_fleet_average",
				"official_sources_representative_licensed_fleet_average_proxy_no_individual_powertrain",
				"energy_parameters_repository_relative.csv",
				"snapshot-hash",
				SOURCE_PATH,
				SOURCE_SHA,
				distanceM,
				false,
				HongKongCarEnergyCostCatalog.Resolution.RESOLVED,
				"");
	}

	private static HongKongCarEnergyCostCatalog.EnergyQuote motorcycleQuote(
			String personId,
			int legSequence,
			double distanceM) {
		return new HongKongCarEnergyCostCatalog.EnergyQuote(
				personId,
				legSequence,
				"vehicle-" + personId,
				"motorcycle",
				null,
				"out_of_scope_motorcycle",
				"out_of_scope",
				"",
				"snapshot-hash",
				SOURCE_PATH,
				SOURCE_SHA,
				distanceM,
				false,
				HongKongCarEnergyCostCatalog.Resolution.OUT_OF_SCOPE,
				"vehicle_class_motorcycle");
	}

	private record Fixture(
			Person person,
			Leg carLeg,
			HongKongCarEnergyCostCatalog catalog) {
	}
}
