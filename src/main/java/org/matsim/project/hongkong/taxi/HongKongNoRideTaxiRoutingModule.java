package org.matsim.project.hongkong.taxi;

import org.matsim.core.config.Config;
import org.matsim.core.controler.AbstractModule;

import java.util.Objects;

/** Registers Taxi routing without requiring the historical aggregate ride mode. */
public final class HongKongNoRideTaxiRoutingModule extends AbstractModule {

	public static final String TAXI_MODE = HongKongTaxiScoringParameters.TAXI_MODE;
	public static final String PASSENGER_DELEGATE_MODE = "car_passenger";

	/** Verifies that Taxi can delegate to the explicit car-passenger router. */
	public static void configure(Config config) {
		Objects.requireNonNull(config, "config");
		if (config.qsim().getMainModes().contains(TAXI_MODE)) {
			throw new IllegalStateException("Passenger Taxi must not be a QSim main mode");
		}
		if (config.routing().getNetworkModes().contains(TAXI_MODE)) {
			throw new IllegalStateException("Passenger Taxi must not be network-routed");
		}
		if (!config.routing().getModeRoutingParams().containsKey(PASSENGER_DELEGATE_MODE)) {
			throw new IllegalStateException(
					"car_passenger teleported routing parameters are unavailable");
		}
		if (config.routing().getModeRoutingParams().containsKey(TAXI_MODE)) {
			throw new IllegalStateException(
					"Taxi routing parameters must not shadow the native Taxi binding");
		}
	}

	@Override
	public void install() {
		addRoutingModuleBinding(TAXI_MODE).to(HongKongNoRideTaxiRouting.class);
	}
}
