package org.matsim.project.hongkong.taxi;

import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.core.config.Config;
import org.matsim.core.controler.AbstractModule;
import org.matsim.core.router.NetworkRoutingProvider;
import org.matsim.core.router.costcalculators.TravelDisutilityFactory;
import org.matsim.core.router.util.TravelDisutility;
import org.matsim.vehicles.Vehicle;
import org.matsim.vehicles.VehicleType;
import org.matsim.vehicles.VehicleUtils;

import java.util.LinkedHashMap;
import java.util.LinkedHashSet;

/** Explicit road-coupled Taxi proxy; no fleet matching, cruising, or deadheading. */
public final class HongKongNetworkTaxiRoutingModule extends AbstractModule {
	public static final String DELEGATE_BINDING = "hongKongNetworkTaxiDelegate";

	public static void configure(Config config) {
		var networkModes = new LinkedHashSet<>(config.routing().getNetworkModes());
		networkModes.add(HongKongTaxiScoringParameters.TAXI_MODE);
		config.routing().setNetworkModes(networkModes);
		var mainModes = new LinkedHashSet<>(config.qsim().getMainModes());
		mainModes.add(HongKongTaxiScoringParameters.TAXI_MODE);
		config.qsim().setMainModes(mainModes);
		config.routing().removeTeleportedModeParams(HongKongTaxiScoringParameters.TAXI_MODE);
	}

	public static ProxyStats prepareScenario(Scenario scenario) {
		int links = 0;
		for (var link : scenario.getNetwork().getLinks().values()) {
			if (!link.getAllowedModes().contains(TransportMode.car)
					|| link.getAllowedModes().contains(HongKongTaxiScoringParameters.TAXI_MODE)) continue;
			var modes = new LinkedHashSet<>(link.getAllowedModes());
			modes.add(HongKongTaxiScoringParameters.TAXI_MODE);
			link.setAllowedModes(modes);
			links++;
		}
		var typeId = org.matsim.api.core.v01.Id.create("hk_network_taxi_proxy_v1", VehicleType.class);
		VehicleType type = scenario.getVehicles().getVehicleTypes().get(typeId);
		if (type == null) {
			type = VehicleUtils.createVehicleType(typeId).setNetworkMode(
					HongKongTaxiScoringParameters.TAXI_MODE).setPcuEquivalents(1.0)
					.setMaximumVelocity(50.0);
			scenario.getVehicles().addVehicleType(type);
		}
		int vehicles = 0;
		for (var person : scenario.getPopulation().getPersons().values()) {
			var vehicleId = VehicleUtils.createVehicleId(person,
					HongKongTaxiScoringParameters.TAXI_MODE);
			if (!scenario.getVehicles().getVehicles().containsKey(vehicleId)) {
				scenario.getVehicles().addVehicle(VehicleUtils.createVehicle(vehicleId, type));
			}
			java.util.Map<String, org.matsim.api.core.v01.Id<Vehicle>> existing =
					person.getAttributes().getAttribute("vehicles") == null
							? java.util.Map.of() : VehicleUtils.getVehicleIds(person);
			var ids = new LinkedHashMap<>(existing);
			ids.put(HongKongTaxiScoringParameters.TAXI_MODE, vehicleId);
			VehicleUtils.insertVehicleIdsIntoAttributes(person, ids);
			vehicles++;
			for (var plan : person.getPlans()) {
				for (var element : plan.getPlanElements()) {
					if (element instanceof org.matsim.api.core.v01.population.Leg leg
							&& HongKongTaxiScoringParameters.TAXI_MODE.equals(leg.getRoutingMode())) {
						leg.setRoute(null);
					}
				}
			}
		}
		return new ProxyStats(links, vehicles);
	}

	@Override
	public void install() {
		addTravelTimeBinding(HongKongTaxiScoringParameters.TAXI_MODE)
				.to(HongKongNetworkTaxiTravelTime.class);
		TravelDisutilityFactory disutilityFactory = supplied -> new TravelDisutility() {
			@Override public double getLinkTravelDisutility(
					org.matsim.api.core.v01.network.Link link, double time,
					org.matsim.api.core.v01.population.Person person, Vehicle vehicle) {
				return supplied.getLinkTravelTime(link, time, person, vehicle);
			}
			@Override public double getLinkMinimumTravelDisutility(
					org.matsim.api.core.v01.network.Link link) {
				return link.getLength() / Math.max(0.1, link.getFreespeed());
			}
		};
		addTravelDisutilityFactoryBinding(HongKongTaxiScoringParameters.TAXI_MODE)
				.toInstance(disutilityFactory);
		addRoutingModuleBinding(DELEGATE_BINDING).toProvider(
				new NetworkRoutingProvider(HongKongTaxiScoringParameters.TAXI_MODE));
		addRoutingModuleBinding(HongKongTaxiScoringParameters.TAXI_MODE)
				.to(HongKongNetworkTaxiRouting.class);
	}

	public record ProxyStats(int taxiEnabledCarLinks, int personTaxiVehicles) { }
}
