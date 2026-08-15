package org.matsim.project.hongkong.household;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.population.routes.RouteUtils;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class HouseholdJointPlanSelectorTest {

	@Test
	void permitsIndependentDirectionsButNotTwoPassengersOnOneDriverLeg() {
		var outbound = candidate("out", "passenger", 0, "driver", 0, false);
		var inbound = candidate("in", "passenger", 1, "driver", 1, false);
		var competingPassenger = candidate("other", "other-passenger", 0, "driver", 0, false);
		var roleConflict = candidate("role-conflict", "driver", 0, "other-driver", 0, false);

		assertFalse(HouseholdJointPlanSelector.candidatesConflict(outbound, inbound));
		assertTrue(HouseholdJointPlanSelector.candidatesConflict(outbound, competingPassenger));
		assertTrue(HouseholdJointPlanSelector.candidatesConflict(outbound, roleConflict));
	}

	@Test
	void fullDayDriverSwitchReservesTheVehicleDay() {
		var switchCandidate = candidate("switch", "passenger", 0, "driver", 0, true);
		var existingCarCandidate = candidate("existing", "other-passenger", 0, "driver", 1, false);

		assertTrue(HouseholdJointPlanSelector.candidatesConflict(
				switchCandidate, existingCarCandidate));
	}

	@Test
	void scoresRaptorAccessWalkWithWalkParameters() {
		var accessLeg = PopulationUtils.createLeg(TransportMode.non_network_walk);

		assertEquals(TransportMode.walk,
				HouseholdJointPlanSelector.scoringModeForLeg(accessLeg));
	}

	@Test
	void recognizesOnlyExplicitNetworkUnreachabilityAsUnavailableCandidate() {
		assertTrue(HouseholdJointPlanSelector.isNoNetworkRouteFailure(
				new RuntimeException("No route found from node a to node b for mode walk.")));
		assertFalse(HouseholdJointPlanSelector.isNoNetworkRouteFailure(
				new RuntimeException("unexpected router failure")));
	}

	@Test
	void treatsCoincidentFacilityTaxiRoutingWithoutTaxiLegAsNoAlternative() {
		assertTrue(HouseholdJointPlanSelector.findTaxiLeg(java.util.List.of()).isEmpty());
		assertTrue(HouseholdJointPlanSelector.findTaxiLeg(java.util.List.of(
				PopulationUtils.createLeg(TransportMode.walk))).isEmpty());
		var taxi = PopulationUtils.createLeg("taxi");
		assertEquals(taxi, HouseholdJointPlanSelector.findTaxiLeg(
				java.util.List.of(taxi)).orElseThrow());
	}

	@Test
	void boundPassengerLegCarriesStableRouteThroughPrepareForMobsim() {
		var candidate = candidate("joint", "passenger", 0, "driver", 0, false);

		var leg = HouseholdJointPlanSelector.createBoundPassengerLeg(candidate, 321.0);

		assertEquals("car_passenger", leg.getMode());
		assertEquals("car_passenger", leg.getRoutingMode());
		assertEquals("pickup", leg.getRoute().getStartLinkId().toString());
		assertEquals("dropoff", leg.getRoute().getEndLinkId().toString());
		assertEquals(321.0, leg.getRoute().getTravelTime().seconds());
		assertEquals(321.0, leg.getTravelTime().seconds());
	}

	@Test
	void restoresDriverWaypointRouteAfterStockPreparationReplacesIt() {
		var passengerLeg = PopulationUtils.createLeg("car_passenger");
		var driverLeg = PopulationUtils.createLeg(TransportMode.car);
		var vehicleId = Id.createVehicleId("vehicle");
		var planned = RouteUtils.createLinkNetworkRouteImpl(
				Id.createLinkId("driver-origin"),
				java.util.List.of(Id.createLinkId("pickup"), Id.createLinkId("dropoff")),
				Id.createLinkId("driver-destination"));
		planned.setVehicleId(vehicleId);
		planned.setTravelTime(600.0);
		driverLeg.setRoute(RouteUtils.createLinkNetworkRouteImpl(
				Id.createLinkId("driver-origin"), java.util.List.of(),
				Id.createLinkId("driver-destination")));

		var catalog = HouseholdEscortBindingCatalog.empty();
		catalog.replaceWithActiveBindings(java.util.List.of(
				new HouseholdEscortBindingCatalog.Binding(
						"joint", "household", "test", true,
						Id.createPersonId("passenger"), 0, passengerLeg,
						Id.createPersonId("driver"), 0, driverLeg,
						HouseholdEscortBindingCatalog.snapshotNetworkRoute(planned), vehicleId,
						Id.createLinkId("pickup"), Id.createLinkId("dropoff"),
						Id.createLinkId("driver-destination"),
						0.0, 0.0, 0.0, 0.0)));

		assertEquals(1, catalog.restoreSelectedDriverWaypointRoutes());
		assertTrue(((org.matsim.core.population.routes.NetworkRoute) driverLeg.getRoute())
				.getLinkIds().contains(Id.createLinkId("pickup")));
		assertTrue(((org.matsim.core.population.routes.NetworkRoute) driverLeg.getRoute())
				.getLinkIds().contains(Id.createLinkId("dropoff")));
		assertEquals(600.0, driverLeg.getTravelTime().seconds());
	}

	private static HouseholdJointPlanCandidateCatalog.Candidate candidate(
			String id, String passenger, int passengerTrip, String driver,
			int driverTrip, boolean switchDriver) {
		return new HouseholdJointPlanCandidateCatalog.Candidate(
				id, "household", passenger, passengerTrip, TransportMode.pt,
				driver, driverTrip, switchDriver ? TransportMode.pt : TransportMode.car,
				"vehicle", switchDriver, 1_000.0, 1_000.0,
				"pickup", "dropoff", "destination", 0.0, 0.0);
	}
}
