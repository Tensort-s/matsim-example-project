package org.matsim.project.hongkong.taxi;

import org.matsim.api.core.v01.Id;
import org.matsim.vehicles.Vehicle;

import java.util.Map;

/** Exact physical fleet identity and service windows used by Taxi-only event audits. */
public record HongKongPhysicalTaxiFleetRegistry(
		Map<Id<Vehicle>, HongKongPhysicalTaxiFleetLoader.ServiceWindow> serviceWindows) {
	public HongKongPhysicalTaxiFleetRegistry {
		serviceWindows = Map.copyOf(serviceWindows);
		if (serviceWindows.isEmpty()) throw new IllegalArgumentException("Physical Taxi registry is empty");
	}

	public boolean contains(Id<Vehicle> vehicleId) {
		return serviceWindows.containsKey(vehicleId);
	}
}
