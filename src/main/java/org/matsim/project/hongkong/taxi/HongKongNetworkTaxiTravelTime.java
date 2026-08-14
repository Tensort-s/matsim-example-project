package org.matsim.project.hongkong.taxi;

import com.google.inject.Inject;
import com.google.inject.name.Named;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.Person;
import org.matsim.core.router.util.TravelTime;
import org.matsim.vehicles.Vehicle;

/** Makes Taxi route choice use the same time field as private Car. */
public final class HongKongNetworkTaxiTravelTime implements TravelTime {
	private final TravelTime carTravelTime;

	@Inject
	public HongKongNetworkTaxiTravelTime(@Named(TransportMode.car) TravelTime carTravelTime) {
		this.carTravelTime = carTravelTime;
	}

	@Override
	public double getLinkTravelTime(Link link, double time, Person person, Vehicle vehicle) {
		return carTravelTime.getLinkTravelTime(link, time, person, vehicle);
	}
}
