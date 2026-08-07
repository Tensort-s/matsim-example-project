package org.matsim.project.hongkong.household;

import org.junit.jupiter.api.Test;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.network.Link;
import org.matsim.core.population.routes.NetworkRoute;
import org.matsim.core.population.routes.RouteUtils;
import org.matsim.vehicles.Vehicle;

import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;

class HouseholdEscortMaxUtilitySelectorTest {

	@Test
	void combinesThreeSegmentsWithoutDroppingRealWaypoints() {
		Id<Link> driverOrigin = Id.createLinkId("driver-origin");
		Id<Link> approach = Id.createLinkId("approach");
		Id<Link> pickup = Id.createLinkId("pickup");
		Id<Link> passengerRoad = Id.createLinkId("passenger-road");
		Id<Link> dropoff = Id.createLinkId("dropoff");
		Id<Link> finalRoad = Id.createLinkId("final-road");
		Id<Link> driverDestination = Id.createLinkId("driver-destination");
		Id<Vehicle> vehicle = Id.createVehicleId("household-car");

		NetworkRoute first = RouteUtils.createLinkNetworkRouteImpl(
				driverOrigin, List.of(approach), pickup);
		NetworkRoute second = RouteUtils.createLinkNetworkRouteImpl(
				pickup, List.of(passengerRoad), dropoff);
		NetworkRoute third = RouteUtils.createLinkNetworkRouteImpl(
				dropoff, List.of(finalRoad), driverDestination);

		NetworkRoute combined = HouseholdEscortMaxUtilitySelector.combine(
				List.of(first, second, third), vehicle);

		assertEquals(driverOrigin, combined.getStartLinkId());
		assertEquals(driverDestination, combined.getEndLinkId());
		assertEquals(List.of(approach, pickup, passengerRoad, dropoff, finalRoad),
				combined.getLinkIds());
		assertEquals(vehicle, combined.getVehicleId());
	}

	@Test
	void selectsMaximumHouseholdUtilityWithoutReusingDriverLeg() {
		var combinedRide = new HouseholdEscortMaxUtilitySelector.ResourceCandidate(
				"combined", 10.0, Set.of("outbound", "return"));
		var outboundOnly = new HouseholdEscortMaxUtilitySelector.ResourceCandidate(
				"outbound", 6.0, Set.of("outbound"));
		var returnOnly = new HouseholdEscortMaxUtilitySelector.ResourceCandidate(
				"return", 6.0, Set.of("return"));

		Set<String> selected = HouseholdEscortMaxUtilitySelector.selectCompatibleCandidateIds(
				List.of(combinedRide, outboundOnly, returnOnly));

		assertEquals(Set.of("outbound", "return"), selected);
	}

	@Test
	void rejectsNegativeDeltaAndKeepsNonConflictingZeroDeltaCandidate() {
		var negative = new HouseholdEscortMaxUtilitySelector.ResourceCandidate(
				"negative", -0.1, Set.of("driver-leg-1"));
		var zero = new HouseholdEscortMaxUtilitySelector.ResourceCandidate(
				"zero", 0.0, Set.of("driver-leg-2"));

		Set<String> selected = HouseholdEscortMaxUtilitySelector.selectCompatibleCandidateIds(
				List.of(negative, zero));

		assertEquals(Set.of("zero"), selected);
	}
}
