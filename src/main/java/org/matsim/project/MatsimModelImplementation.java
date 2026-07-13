/* *********************************************************************** *
 * project: org.matsim.*												   *
 *                                                                         *
 * *********************************************************************** *
 *                                                                         *
 * copyright       : (C) 2008 by the members listed in the COPYING,        *
 *                   LICENSE and WARRANTY file.                            *
 * email           : info at matsim dot org                                *
 *                                                                         *
 * *********************************************************************** *
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *   See also COPYING, LICENSE and WARRANTY file                           *
 *                                                                         *
 * *********************************************************************** */
package org.matsim.project;

import org.apache.logging.log4j.core.tools.picocli.CommandLine;
import org.matsim.api.core.v01.Scenario;
import org.matsim.application.MATSimApplication;
import org.matsim.contrib.drt.routing.DrtRoute;
import org.matsim.contrib.drt.routing.DrtRouteFactory;
import org.matsim.contrib.dvrp.run.DvrpConfigGroup;
import org.matsim.contrib.dvrp.run.DvrpModule;
import org.matsim.contrib.dvrp.run.DvrpQSimComponents;
import org.matsim.contrib.taxi.fare.TaxiFareParams;
import org.matsim.contrib.taxi.optimizer.rules.RuleBasedRequestInserter;
import org.matsim.contrib.taxi.optimizer.rules.RuleBasedTaxiOptimizerParams;
import org.matsim.contrib.taxi.run.MultiModeTaxiConfigGroup;
import org.matsim.contrib.taxi.run.MultiModeTaxiModule;
import org.matsim.contrib.taxi.run.TaxiConfigGroup;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigGroup;
import org.matsim.core.config.groups.ScoringConfigGroup;
import org.matsim.core.controler.Controler;
import org.matsim.core.controler.AbstractModule;
import org.matsim.core.controler.OutputDirectoryHierarchy.OverwriteFileSetting;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.router.AnalysisMainModeIdentifier;
import org.matsim.simwrapper.SimWrapperModule;

import java.nio.file.Path;

/**
 * @author nagel
 *
 */
@CommandLine.Command( header = ":: MyScenario ::", version = "1.0")
public class MatsimModelImplementation extends MATSimApplication {

	private static final String RIDE_HAILING_MODE = "ride_hailing";
	private static final String RIDE_HAILING_FLEET_FILE = Path.of(
			"data",
			"ride_hailing",
			"fuzhou_ride_hailing_2pct_20260712",
			"ride_hailing_fleet.xml.gz" ).toAbsolutePath().toString();

	public MatsimModelImplementation() {
		super();
	}

	public static void main(String[] args) {
		MATSimApplication.execute(MatsimModelImplementation.class, "--config", "scenarios/equil/config-2026.xml");
	}

	@Override
	protected Config prepareConfig(Config config) {

		config.controller().setOverwriteFileSetting( OverwriteFileSetting.deleteDirectoryIfExists );

		if ( config.controller().getOutputDirectory().contains( "waitpenalty-metroprefer" ) ) {
			config.scoring().setMarginalUtlOfWaitingPt_utils_hr( -12.0 );
		}

		if ( isRideHailingConfig( config ) ) {
			configureRideHailing( config );
		}

		// ---

		return config;
	}

	@Override
	protected Scenario createScenario(Config config) {
		Scenario scenario = super.createScenario( config );
		if ( isRideHailingConfig( config ) ) {
			scenario.getPopulation().getFactory().getRouteFactories().setRouteFactory(
					DrtRoute.class, new DrtRouteFactory() );
		}
		return scenario;
	}

	@Override
	protected void prepareScenario(Scenario scenario) {

		// possibly modify scenario here

		scenario.getPopulation().getPersons().values().forEach(person -> {
			if (PopulationUtils.getSubpopulation(person) == null) {
				PopulationUtils.putSubpopulation(person, "default");
			}
		});

		// ---

	}

	@Override
	protected void prepareControler(Controler controler) {

		// possibly modify controler here

		if ( isRideHailingConfig( controler.getConfig() ) ) {
			controler.addOverridingModule( new DvrpModule() );
			controler.addOverridingModule( new MultiModeTaxiModule() );
			controler.configureQSimComponents( DvrpQSimComponents.activateAllModes(
					MultiModeTaxiConfigGroup.get( controler.getConfig() ) ) );
		}

		controler.addOverridingModule( new SimWrapperModule() );
		controler.addOverridingModule( new AbstractModule() {
			@Override
			public void install() {
				bind( AnalysisMainModeIdentifier.class ).to( FuzhouAnalysisMainModeIdentifier.class );
			}
		} );


		// ---
	}

	private static boolean isRideHailingConfig(Config config) {
		String outputDirectory = config.controller().getOutputDirectory();
		String plansFile = config.plans().getInputFile();
		return ( outputDirectory != null && outputDirectory.contains( "ride-hailing" ) )
				|| ( plansFile != null && plansFile.contains( "ride_hailing" ) );
	}

	private static void configureRideHailing(Config config) {
		if ( config.getModules().get( DvrpConfigGroup.GROUP_NAME ) == null ) {
			config.addModule( new DvrpConfigGroup() );
		}

		MultiModeTaxiConfigGroup multiModeTaxiConfig = getOrCreateMultiModeTaxiConfig( config );
		boolean alreadyConfigured = multiModeTaxiConfig.getModalElements().stream()
				.anyMatch( taxiConfig -> RIDE_HAILING_MODE.equals( taxiConfig.getMode() ) );
		if ( !alreadyConfigured ) {
			TaxiConfigGroup taxiConfig = new TaxiConfigGroup();
			taxiConfig.mode = RIDE_HAILING_MODE;
			taxiConfig.taxisFile = RIDE_HAILING_FLEET_FILE;
			taxiConfig.useModeFilteredSubnetwork = false;
			taxiConfig.destinationKnown = true;
			taxiConfig.vehicleDiversion = false;
			taxiConfig.pickupDuration = 60.0;
			taxiConfig.dropoffDuration = 30.0;
			taxiConfig.onlineVehicleTracker = true;
			taxiConfig.breakSimulationIfNotAllRequestsServed = false;
			taxiConfig.numberOfThreads = Math.max( 1, Runtime.getRuntime().availableProcessors() / 2 );

			RuleBasedTaxiOptimizerParams optimizerParams = new RuleBasedTaxiOptimizerParams();
			optimizerParams.goal = RuleBasedRequestInserter.Goal.MIN_WAIT_TIME;
			optimizerParams.nearestVehiclesLimit = 30;
			optimizerParams.nearestRequestsLimit = 30;
			optimizerParams.reoptimizationTimeStep = 30;
			taxiConfig.addParameterSet( optimizerParams );

			TaxiFareParams fareParams = new TaxiFareParams();
			fareParams.setBasefare( 10.0 );
			fareParams.setMinFarePerTrip( 10.0 );
			fareParams.setDistanceFare_m( 0.002 );
			fareParams.setTimeFare_h( 24.0 );
			taxiConfig.addParameterSet( fareParams );

			multiModeTaxiConfig.addParameterSet( taxiConfig );
		}

		ScoringConfigGroup.ModeParams rideHailingModeParams =
				config.scoring().getOrCreateModeParams( RIDE_HAILING_MODE );
		rideHailingModeParams.setConstant( -0.5 );
		rideHailingModeParams.setMarginalUtilityOfTraveling( -6.5 );
		config.scoring().setMarginalUtlOfWaiting_utils_hr( -12.0 );
		config.scoring().setMarginalUtilityOfMoney( 0.1 );
	}

	private static MultiModeTaxiConfigGroup getOrCreateMultiModeTaxiConfig(Config config) {
		ConfigGroup existing = config.getModules().get( MultiModeTaxiConfigGroup.GROUP_NAME );
		if ( existing instanceof MultiModeTaxiConfigGroup multiModeTaxiConfig ) {
			return multiModeTaxiConfig;
		}
		MultiModeTaxiConfigGroup multiModeTaxiConfig = new MultiModeTaxiConfigGroup();
		config.addModule( multiModeTaxiConfig );
		return multiModeTaxiConfig;
	}
}
