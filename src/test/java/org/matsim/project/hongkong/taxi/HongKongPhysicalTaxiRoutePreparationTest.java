package org.matsim.project.hongkong.taxi;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.contrib.drt.routing.DrtRoute;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.core.scenario.ScenarioUtils;

import static org.junit.jupiter.api.Assertions.*;

class HongKongPhysicalTaxiRoutePreparationTest {
	@Test
	void preparesTaxiLegOutsideStandardTripView() {
		var scenario = ScenarioUtils.createScenario(ConfigUtils.createConfig());
		var person = PopulationUtils.getFactory().createPerson(Id.createPersonId("p-orphan"));
		var plan = PopulationUtils.createPlan(person);
		plan.addActivity(PopulationUtils.createActivityFromLinkId("home", Id.createLinkId("l1")));
		var taxi = PopulationUtils.createLeg("taxi");
		taxi.setDepartureTime(1000);
		taxi.setTravelTime(120);
		var old = RouteUtils.createGenericRouteImpl(Id.createLinkId("l1"), Id.createLinkId("l2"));
		old.setDistance(1400);
		old.setTravelTime(120);
		taxi.setRoute(old);
		plan.addLeg(taxi);
		person.addPlan(plan);
		person.setSelectedPlan(plan);
		scenario.getPopulation().addPerson(person);

		var stats = HongKongPhysicalTaxiRoutePreparation.prepare(scenario);
		assertEquals(1, stats.taxiLegs());
		assertEquals(1, stats.convertedRoutes());
		assertInstanceOf(DrtRoute.class, taxi.getRoute());
		assertDoesNotThrow(() -> HongKongTaxiRouteContext.from(taxi));
	}

	@Test
	void convertsHistoricalRouteAndStampsNewCandidateMetadata() {
		var scenario = ScenarioUtils.createScenario(ConfigUtils.createConfig());
		var person = PopulationUtils.getFactory().createPerson(Id.createPersonId("p1"));
		var plan = PopulationUtils.createPlan(person);
		var home = PopulationUtils.createActivityFromLinkId("home", Id.createLinkId("l1"));
		home.setEndTime(1000);
		var taxi = PopulationUtils.createLeg("taxi");
		taxi.setRoutingMode("taxi");
		taxi.setDepartureTime(1000);
		taxi.setTravelTime(120);
		var old = RouteUtils.createGenericRouteImpl(Id.createLinkId("l1"), Id.createLinkId("l2"));
		old.setDistance(1400);
		old.setTravelTime(120);
		taxi.setRoute(old);
		taxi.getAttributes().putAttribute(HongKongTaxiLegAttributes.TAXI_TYPE, "  ");
		taxi.getAttributes().putAttribute(HongKongTaxiLegAttributes.CLASSIFICATION_SOURCE, "");
		plan.addActivity(home);
		plan.addLeg(taxi);
		plan.addActivity(PopulationUtils.createActivityFromLinkId("work", Id.createLinkId("l2")));
		person.addPlan(plan);
		person.setSelectedPlan(plan);
		scenario.getPopulation().addPerson(person);

		var stats = HongKongPhysicalTaxiRoutePreparation.prepare(scenario);
		assertEquals(1, stats.convertedRoutes());
		assertInstanceOf(DrtRoute.class, taxi.getRoute());
		assertEquals(1400, taxi.getRoute().getDistance());
		assertEquals(HongKongTaxiFareCalculator.UNRESOLVED,
				taxi.getAttributes().getAttribute(HongKongTaxiLegAttributes.TAXI_TYPE));
		assertEquals("physical_taxi_dvrp_v1",
				taxi.getAttributes().getAttribute(HongKongTaxiLegAttributes.CLASSIFICATION_SOURCE));
		assertEquals(0, taxi.getAttributes().getAttribute(HongKongTaxiLegAttributes.MAIN_TRIP_INDEX));
		assertNotNull(home.getAttributes().getAttribute(HongKongTaxiLegAttributes.TAXI_TYPE));
		assertDoesNotThrow(() -> HongKongTaxiRouteContext.from(taxi));
	}
}
