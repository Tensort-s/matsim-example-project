package org.matsim.project.hongkong.car;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.events.Event;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.population.routes.NetworkRoute;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.router.TripStructureUtils;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HongKongCarMarginalCostScoringTest {

	private static final String ENERGY_PATH =
			"data/transport_costs/hongkong/car_cost_v1/energy_application_v1/"
					+ "car_leg_energy_cost_estimates_base.parquet";
	private static final String ENERGY_SHA =
			"0e0cc3fdd3440b4be8e51ad98289de590af1b479222c8e29b15845055d82f5da";

	@Test
	void singleCarOwnerComposesEnergyAndConfirmedTollExactlyOnce() {
		Person person = person("combined");
		Leg carLeg = (Leg) person.getSelectedPlan().getPlanElements().get(1);
		var energyCatalog = HongKongCarEnergyCostCatalog.builder()
				.quote(energyQuote("combined", 0, 2.5)).buildForTests();
		var tollCatalog = HongKongCarTollCostCatalog.builder()
				.quote(HongKongCarTollScoringTest.chargedQuote(
						"combined", 0, 30.0)).buildForTests();
		var factory = new HongKongCarMarginalCostScoringComponentFactory(
				new HongKongCarEnergyScoringComponentFactory(energyCatalog, 2.0),
				new HongKongCarTollScoringComponentFactory(tollCatalog, 2.0));
		assertEquals("car_marginal_cost_v1", factory.componentId());
		assertEquals(java.util.Set.of("car"), factory.activeModes());
		assertEquals(
				List.of("car_fuel_or_electricity_v1", "car_confirmed_toll_v1"),
				factory.subcomponentIds());

		var scoring = (HongKongCarMarginalCostScoring)
				factory.createComponent(person);
		scoring.handleLeg(carLeg);
		assertEquals(-65.0, scoring.getScore(), 0.0);
		assertEquals(2.5, scoring.energy().chargedEnergyHkd(), 0.0);
		assertEquals(30.0, scoring.toll().chargedTollHkd(), 0.0);
		assertEquals(1, scoring.energy().consumedCarLegs());
		assertEquals(1, scoring.toll().consumedCarLegs());

		scoring.addMoney(-32.5);
		scoring.addScore(100.0);
		scoring.agentStuck(100.0);
		scoring.handleEvent(new Event(100.0) {
			@Override
			public String getEventType() {
				return "stage8b_composite_duplicate_probe";
			}
		});
		scoring.handleTrip(TripStructureUtils.getTrips(
				person.getSelectedPlan()).getFirst());
		assertEquals(-65.0, scoring.getScore(), 0.0);
		assertThrows(IllegalStateException.class,
				() -> scoring.handleLeg(carLeg));
		scoring.finish();
		StringBuilder explanation = new StringBuilder();
		scoring.explainScore(explanation);
		assertTrue(explanation.toString().contains("car_fuel_or_electricity_v1"));
		assertTrue(explanation.toString().contains("car_confirmed_toll_v1"));
	}

	@Test
	void confirmedNoChargePreservesEnergyWithoutAddingToll() {
		Person person = person("no-charge-composite");
		Leg carLeg = (Leg) person.getSelectedPlan().getPlanElements().get(1);
		var factory = new HongKongCarMarginalCostScoringComponentFactory(
				new HongKongCarEnergyScoringComponentFactory(
						HongKongCarEnergyCostCatalog.builder()
								.quote(energyQuote(
										"no-charge-composite", 0, 2.5))
								.buildForTests(),
						1.0),
				new HongKongCarTollScoringComponentFactory(
						HongKongCarTollCostCatalog.builder()
								.quote(HongKongCarTollScoringTest.noChargeQuote(
										"no-charge-composite", 0))
								.buildForTests(),
						1.0));
		var scoring = (HongKongCarMarginalCostScoring)
				factory.createComponent(person);
		scoring.handleLeg(carLeg);
		scoring.finish();
		assertEquals(-2.5, scoring.getScore(), 0.0);
		assertEquals(2.5, scoring.energy().chargedEnergyHkd(), 0.0);
		assertEquals(0.0, scoring.toll().chargedTollHkd(), 0.0);
		assertEquals(1, scoring.toll().confirmedNoChargeLegs());
	}

	private static Person person(String id) {
		Person person = PopulationUtils.getFactory().createPerson(
				Id.createPersonId(id));
		Plan plan = PopulationUtils.createPlan(person);
		plan.addActivity(PopulationUtils.createActivityFromCoord(
				"home", new Coord(0.0, 0.0)));
		Leg leg = PopulationUtils.createLeg("car");
		leg.setRoutingMode("car");
		NetworkRoute route = RouteUtils.createLinkNetworkRouteImpl(
				Id.createLinkId("from"), Id.createLinkId("to"));
		route.setLinkIds(
				Id.createLinkId("from"),
				List.of(Id.createLinkId("toll")),
				Id.createLinkId("to"));
		route.setDistance(1_000.0);
		route.setTravelTime(100.0);
		leg.setRoute(route);
		plan.addLeg(leg);
		plan.addActivity(PopulationUtils.createActivityFromCoord(
				"work", new Coord(1.0, 1.0)));
		person.addPlan(plan);
		person.setSelectedPlan(plan);
		return person;
	}

	private static HongKongCarEnergyCostCatalog.EnergyQuote energyQuote(
			String personId, int legSequence, double costHkd) {
		return new HongKongCarEnergyCostCatalog.EnergyQuote(
				personId, legSequence, "vehicle-" + personId, "private_car",
				costHkd, "resolved_representative_fleet_average",
				"official_sources_representative_licensed_fleet_average_proxy_no_individual_powertrain",
				"energy-source", "snapshot", ENERGY_PATH, ENERGY_SHA,
				1_000.0, false,
				HongKongCarEnergyCostCatalog.Resolution.RESOLVED, "");
	}
}
