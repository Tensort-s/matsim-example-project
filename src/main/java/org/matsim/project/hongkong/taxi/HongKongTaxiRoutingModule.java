package org.matsim.project.hongkong.taxi;

import org.matsim.core.config.Config;
import org.matsim.core.controler.AbstractModule;

import java.util.Objects;

/**
 * Registers {@code taxi} as an independent teleported passenger routing mode.
 *
 * <p>The bound router delegates distance and time calculation to MATSim's
 * existing {@code ride} teleported router. Taxi is deliberately not added to
 * network routing or the QSim main modes.</p>
 */
public final class HongKongTaxiRoutingModule extends AbstractModule {

	public static final String TAXI_MODE = HongKongTaxiScoringParameters.TAXI_MODE;
	private static final String RIDE_MODE = "ride";

	/** Verifies the passenger-only routing configuration before scenario load. */
	public static void configure(Config config) {
		Objects.requireNonNull(config, "config");
		requirePassengerOnly(config);
		if (!config.routing().getModeRoutingParams().containsKey(RIDE_MODE)) {
			throw new IllegalStateException(
					"MATSim ride teleported routing parameters are unavailable");
		}
		if (config.routing().getModeRoutingParams().containsKey(TAXI_MODE)) {
			throw new IllegalStateException(
					"Taxi routing parameters must not shadow the native Taxi binding");
		}
	}

	@Override
	public void install() {
		addRoutingModuleBinding(TAXI_MODE).to(HongKongTaxiRouting.class);
	}

	private static void requirePassengerOnly(Config config) {
		if (config.qsim().getMainModes().contains(TAXI_MODE)) {
			throw new IllegalStateException(
					"Passenger Taxi must not be a QSim main mode");
		}
		if (config.routing().getNetworkModes().contains(TAXI_MODE)) {
			throw new IllegalStateException(
					"Passenger Taxi must not be a network-routed mode");
		}
	}
}
