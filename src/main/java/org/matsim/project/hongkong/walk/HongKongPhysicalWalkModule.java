package org.matsim.project.hongkong.walk;

import org.matsim.api.core.v01.TransportMode;
import org.matsim.core.controler.AbstractModule;
import org.matsim.core.router.NetworkRoutingProvider;
import org.matsim.core.router.costcalculators.TravelDisutilityFactory;
import org.matsim.core.router.util.TravelDisutility;
import org.matsim.core.router.util.TravelTime;

/** Routing time/disutility shared by physical Walk routing and execution. */
public final class HongKongPhysicalWalkModule extends AbstractModule {

	public static final double WALK_SPEED_M_S = 1.34;
	static final String DELEGATE_BINDING = "hongKongPhysicalWalkNetworkDelegate";

	@Override
	public void install() {
		TravelTime travelTime = (link, time, person, vehicle) -> link.getLength() / WALK_SPEED_M_S;
		TravelDisutilityFactory disutilityFactory = suppliedTravelTime -> new TravelDisutility() {
			@Override
			public double getLinkTravelDisutility(
					org.matsim.api.core.v01.network.Link link,
					double time,
					org.matsim.api.core.v01.population.Person person,
					org.matsim.vehicles.Vehicle vehicle) {
				return suppliedTravelTime.getLinkTravelTime(link, time, person, vehicle);
			}

			@Override
			public double getLinkMinimumTravelDisutility(
					org.matsim.api.core.v01.network.Link link) {
				return link.getLength() / WALK_SPEED_M_S;
			}
		};
		addTravelTimeBinding(TransportMode.walk).toInstance(travelTime);
		addTravelDisutilityFactoryBinding(TransportMode.walk).toInstance(disutilityFactory);
		addRoutingModuleBinding(DELEGATE_BINDING)
				.toProvider(new NetworkRoutingProvider(TransportMode.walk));
		addRoutingModuleBinding(TransportMode.walk).to(HongKongPhysicalWalkRouting.class);
	}
}
