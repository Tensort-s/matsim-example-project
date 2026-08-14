package org.matsim.project.hongkong.signals;

import org.matsim.api.core.v01.Scenario;
import org.matsim.contrib.signals.SignalSystemsConfigGroup;
import org.matsim.contrib.signals.builder.Signals;
import org.matsim.contrib.signals.data.SignalsData;
import org.matsim.contrib.signals.data.SignalsDataLoader;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.config.groups.QSimConfigGroup;
import org.matsim.core.controler.Controler;
import org.matsim.core.scenario.ScenarioUtils;

/** Runs QSim with an empty population to exercise signal clocks and TOD plan boundaries. */
public final class RunHongKongTrafficSignalClockSmoke {

	private RunHongKongTrafficSignalClockSmoke() { }

	public static void main(String[] args) {
		if (args.length != 1) {
			throw new IllegalArgumentException(
					"Usage: RunHongKongTrafficSignalClockSmoke <config.xml>");
		}
		Config config = ConfigUtils.loadConfig(args[0], new SignalSystemsConfigGroup());
		// The smoke gate deliberately loads only the network and signals. Clearing
		// demand/supply inputs here prevents an accidental full Hong Kong run.
		config.plans().setInputFile(null);
		config.facilities().setInputFile(null);
		config.vehicles().setVehiclesFile(null);
		config.transit().setUseTransit(false);
		config.transit().setTransitScheduleFile(null);
		config.transit().setVehiclesFile(null);
		config.controller().setFirstIteration(0);
		config.controller().setLastIteration(0);
		// With an empty population, MATSim's default start-time interpretation
		// derives the earliest activity end as +Infinity.  Signal controllers then
		// try forever to advance their finite daily plan times beyond +Infinity.
		// This clock-only smoke must therefore use the configured start time.
		config.qsim().setSimStarttimeInterpretation(
				QSimConfigGroup.StarttimeInterpretation.onlyUseStarttime);
		SignalSystemsConfigGroup signalConfig = ConfigUtils.addOrGetModule(
				config, SignalSystemsConfigGroup.class);
		if (!signalConfig.isUseSignalSystems()) {
			throw new IllegalArgumentException("Signal clock smoke requires useSignalSystems=true.");
		}
		if (config.qsim().isUsingFastCapacityUpdate()) {
			config.qsim().setUsingFastCapacityUpdate(false);
		}
		Scenario scenario = ScenarioUtils.loadScenario(config);
		if (!scenario.getPopulation().getPersons().isEmpty()) {
			throw new IllegalArgumentException("Signal clock smoke requires an empty population.");
		}
		scenario.addScenarioElement(
				SignalsData.ELEMENT_NAME, new SignalsDataLoader(config).loadSignalsData());
		Controler controler = new Controler(scenario);
		Signals.configure(controler);
		controler.run();
	}
}
