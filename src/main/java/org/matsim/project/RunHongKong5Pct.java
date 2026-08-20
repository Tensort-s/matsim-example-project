package org.matsim.project;

import ch.sbb.matsim.routing.pt.raptor.SwissRailRaptorModule;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.controler.AbstractModule;
import org.matsim.core.controler.Controler;
import org.matsim.core.mobsim.framework.Mobsim;
import org.matsim.core.population.io.PopulationWriter;
import org.matsim.core.population.PopulationUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.contrib.signals.SignalSystemsConfigGroup;
import org.matsim.contrib.signals.builder.Signals;
import org.matsim.contrib.signals.data.SignalsData;
import org.matsim.contrib.signals.data.SignalsDataLoader;
import org.matsim.contrib.drt.run.DrtControlerCreator;
import org.matsim.contrib.dvrp.run.DvrpConfigGroup;
import org.matsim.contrib.dvrp.run.DvrpModule;
import org.matsim.contrib.dvrp.run.DvrpQSimComponents;
import org.matsim.contrib.taxi.optimizer.rules.RuleBasedRequestInserter;
import org.matsim.contrib.taxi.optimizer.rules.RuleBasedTaxiOptimizerParams;
import org.matsim.contrib.taxi.run.MultiModeTaxiConfigGroup;
import org.matsim.contrib.taxi.run.MultiModeTaxiModule;
import org.matsim.contrib.taxi.run.TaxiConfigGroup;
import org.matsim.project.hongkong.scoring.HongKongMultimodalCostScoringModule;
import org.matsim.project.hongkong.household.HouseholdEscortBindingCatalog;
import org.matsim.project.hongkong.household.HouseholdEscortJointReRouteModule;
import org.matsim.project.hongkong.household.HouseholdEscortMaxUtilitySelectorModule;
import org.matsim.project.hongkong.household.HouseholdEscortPhysicalQSimModule;
import org.matsim.project.hongkong.household.HouseholdJointPlanCandidateCatalog;
import org.matsim.project.hongkong.household.HouseholdJointPlanCheckpointRestorer;
import org.matsim.project.hongkong.household.HouseholdJointPlanInnovationModule;
import org.matsim.project.hongkong.household.HouseholdJointPlanSelectionSchedule;
import org.matsim.project.hongkong.pt.HongKongOrdinaryPtRaptorModule;
import org.matsim.project.hongkong.road.HongKongRoadHotspotRepairV1;
import org.matsim.project.hongkong.road.HongKongExplicitStorageModule;
import org.matsim.project.hongkong.road.HongKongExplicitStorageQSimModule;
import org.matsim.project.hongkong.road.HongKongRoadSupplyRegistry;
import org.matsim.project.hongkong.road.HongKongCarOriginAnchorObservationCatalog;
import org.matsim.project.hongkong.road.HongKongCarOriginAnchorRepairModule;
import org.matsim.project.hongkong.schoolbus.StudentSchoolModeCandidateCatalog;
import org.matsim.project.hongkong.schoolbus.SchoolBusAwarePrepareForMobsim;
import org.matsim.project.hongkong.schoolbus.SchoolBusPassengerPhysicalEngine;
import org.matsim.project.hongkong.schoolbus.SchoolBusPassengerPhysicalQSimModule;
import org.matsim.project.hongkong.schoolbus.SchoolBusAwareTransitDriverAgentFactory;
import org.matsim.project.hongkong.taxi.HongKongNoRideTaxiRoutingModule;
import org.matsim.project.hongkong.taxi.HongKongTaxiScoringParameters;
import org.matsim.project.hongkong.taxi.HongKongTaxiFareUtilityPolicy;
import org.matsim.project.hongkong.taxi.HongKongNetworkTaxiRoutingModule;
import org.matsim.project.hongkong.taxi.HongKongPhysicalTaxiAuditModule;
import org.matsim.project.hongkong.taxi.HongKongPhysicalTaxiFleetLoader;
import org.matsim.project.hongkong.taxi.HongKongPhysicalTaxiFleetRegistry;
import org.matsim.project.hongkong.taxi.HongKongPhysicalTaxiParameters;
import org.matsim.project.hongkong.taxi.HongKongPhysicalTaxiRoutePreparation;
import org.matsim.project.hongkong.walk.HongKongPhysicalWalkModule;
import org.matsim.project.hongkong.walk.HongKongPhysicalWalkQSimModule;
import org.matsim.project.hongkong.walk.HongKongWalkOvertimeScoringComponentModule;
import org.matsim.vehicles.Vehicle;
import org.matsim.vehicles.VehicleUtils;

import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

/** Loads and runs the Hong Kong 5% road/PT scenario with explicit car vehicles. */
public final class RunHongKong5Pct {
	private static final String UNPRICED_BORDER_SUBPOPULATION =
			"hk_unpriced_border_no_car_mode_innovation";

	private RunHongKong5Pct() {
	}

	public static void main(String[] args) {
		installFatalMainThreadExitHandler();
		if (args.length < 1) {
			throw new IllegalArgumentException(
				"Usage: RunHongKong5Pct <config.xml> [routed-plans.xml.gz] [--simulate] "
						+ "[--clear-pt-routes] [--multimodal-costs "
						+ "--pt-fare-root=<path> --car-cost-root=<path> [--dynamic-car-costs]] "
						+ "[--household-escort-bindings=<path>] "
						+ "[--household-escort-joint-reroute] [--household-escort-max-utility] "
						+ "[--household-joint-plan-candidates=<path>] "
						+ "[--household-joint-plan-with-ordinary-innovation] "
						+ "[--student-school-mode-candidates=<directory>] "
						+ "[--physical-nontaxi-modes] [--unlimited-ordinary-pt-capacity] "
						+ "[--traffic-signals]"
						+ " [--road-hotspot-repair-v1]"
						+ " [--road-supply-registry=<road_supply_parameters_v2.csv>]"
						+ " [--car-origin-anchor-observations=<path>]"
						+ " [--all-person-network-taxi-innovation] [--walk-overtime-scoring]"
						+ " [--fixed-plans-network-taxi-proxy]"
						+ " [--taxi-dvrp-fleet=<path> [--taxi-dvrp-pcu=<1|.75|.5|.25|.1|.05>]"
						+ " [--taxi-wait-utility-per-hour=-12]]"
						+ " [--household-joint-selection-iterations=5,15,25,35]"
						+ " [--household-joint-restore-selected-bindings=<expected-count>]"
			);
		}
		boolean simulate = Arrays.asList(args).contains("--simulate");
		boolean clearPtRoutes = Arrays.asList(args).contains("--clear-pt-routes");
		boolean multimodalCosts = Arrays.asList(args).contains("--multimodal-costs");
		boolean dynamicCarCosts = Arrays.asList(args).contains("--dynamic-car-costs");
		boolean physicalNonTaxiModes = Arrays.asList(args).contains("--physical-nontaxi-modes");
		boolean unlimitedOrdinaryPtCapacity = Arrays.asList(args)
				.contains("--unlimited-ordinary-pt-capacity");
		boolean trafficSignals = Arrays.asList(args).contains("--traffic-signals");
		boolean roadHotspotRepairV1 = Arrays.asList(args).contains("--road-hotspot-repair-v1");
		boolean householdEscortJointReRoute = Arrays.asList(args)
				.contains("--household-escort-joint-reroute");
		boolean householdEscortMaxUtility = Arrays.asList(args)
				.contains("--household-escort-max-utility");
		boolean householdJointPlanWithOrdinaryInnovation = Arrays.asList(args)
				.contains("--household-joint-plan-with-ordinary-innovation");
		boolean allPersonNetworkTaxiInnovation = Arrays.asList(args)
				.contains("--all-person-network-taxi-innovation");
		boolean fixedPlansNetworkTaxiProxy = Arrays.asList(args)
				.contains("--fixed-plans-network-taxi-proxy");
		boolean walkOvertimeScoring = Arrays.asList(args).contains("--walk-overtime-scoring");
		Path ptFareRoot = optionPath(args, "--pt-fare-root=");
		Path carCostRoot = optionPath(args, "--car-cost-root=");
		Path householdEscortBindings = optionPath(args, "--household-escort-bindings=");
		Path householdJointPlanCandidates = optionPath(args, "--household-joint-plan-candidates=");
		Path studentSchoolModeCandidates = optionPath(args, "--student-school-mode-candidates=");
		Path carOriginAnchorObservations = optionPath(args, "--car-origin-anchor-observations=");
		Path roadSupplyRegistryPath = optionPath(args, "--road-supply-registry=");
		Path taxiDvrpFleet = optionPath(args, "--taxi-dvrp-fleet=");
		Double taxiDvrpPcuOption = optionDouble(args, "--taxi-dvrp-pcu=");
		Double taxiWaitUtilityOption = optionDouble(args, "--taxi-wait-utility-per-hour=");
		String householdSelectionIterationsOption = optionString(
				args, "--household-joint-selection-iterations=");
		String restoreHouseholdBindingsOption = optionString(
				args, "--household-joint-restore-selected-bindings=");
		boolean physicalTaxi = taxiDvrpFleet != null;
		boolean networkTaxiProxy = usesNetworkTaxiProxy(
				allPersonNetworkTaxiInnovation, fixedPlansNetworkTaxiProxy, physicalTaxi);
		double taxiDvrpPcu = taxiDvrpPcuOption == null ? 1.0 : taxiDvrpPcuOption;
		double taxiWaitUtility = taxiWaitUtilityOption == null ? -12.0 : taxiWaitUtilityOption;
		if (!physicalTaxi && (taxiDvrpPcuOption != null || taxiWaitUtilityOption != null)) {
			throw new IllegalArgumentException(
					"Taxi DVRP PCU/wait options require --taxi-dvrp-fleet.");
		}
		if (physicalTaxi && !multimodalCosts) {
			throw new IllegalArgumentException(
					"Physical Taxi requires --multimodal-costs so fare and time are scored exactly once.");
		}
		if (roadSupplyRegistryPath != null && (!physicalTaxi || Math.abs(taxiDvrpPcu - 0.05) > 1e-9)) {
			throw new IllegalArgumentException(
					"Explicit road storage requires physical Taxi with PCU=0.05.");
		}
		if (roadSupplyRegistryPath != null && roadHotspotRepairV1) {
			throw new IllegalArgumentException(
					"Explicit road storage and the historical runtime road-hotspot repair are mutually exclusive.");
		}
		if (physicalTaxi && networkTaxiProxy) {
			throw new IllegalArgumentException(
					"Physical Taxi and the person-local network Taxi proxy are mutually exclusive.");
		}
		if (fixedPlansNetworkTaxiProxy && householdJointPlanWithOrdinaryInnovation) {
			throw new IllegalArgumentException(
					"The fixed-plan Taxi proxy cannot enable household ordinary innovation.");
		}
		if (householdSelectionIterationsOption != null
				&& (!householdJointPlanWithOrdinaryInnovation || householdJointPlanCandidates == null)) {
			throw new IllegalArgumentException(
					"--household-joint-selection-iterations requires protected household ordinary innovation.");
		}
		if (restoreHouseholdBindingsOption != null
				&& (!householdJointPlanWithOrdinaryInnovation || householdJointPlanCandidates == null)) {
			throw new IllegalArgumentException(
					"--household-joint-restore-selected-bindings requires household joint candidates.");
		}
		if (multimodalCosts && (ptFareRoot == null || carCostRoot == null)) {
			throw new IllegalArgumentException(
					"--multimodal-costs requires both --pt-fare-root and --car-cost-root.");
		}
		if (dynamicCarCosts && !multimodalCosts) {
			throw new IllegalArgumentException(
					"--dynamic-car-costs requires --multimodal-costs.");
		}
		if (householdEscortJointReRoute && householdEscortBindings == null) {
			throw new IllegalArgumentException(
					"--household-escort-joint-reroute requires --household-escort-bindings.");
		}
		if (householdEscortMaxUtility && householdEscortBindings == null) {
			throw new IllegalArgumentException(
					"--household-escort-max-utility requires --household-escort-bindings.");
		}
		if (householdEscortMaxUtility && !dynamicCarCosts) {
			throw new IllegalArgumentException(
					"--household-escort-max-utility requires --dynamic-car-costs.");
		}
		if (householdEscortMaxUtility && householdEscortJointReRoute) {
			throw new IllegalArgumentException(
					"Maximum-utility household selection and historical JointReRoute are mutually exclusive.");
		}
		if (householdJointPlanCandidates != null && !dynamicCarCosts) {
			throw new IllegalArgumentException(
					"--household-joint-plan-candidates requires --multimodal-costs --dynamic-car-costs.");
		}
		if (carOriginAnchorObservations != null && !dynamicCarCosts) {
			throw new IllegalArgumentException(
					"--car-origin-anchor-observations requires --multimodal-costs --dynamic-car-costs.");
		}
		if (carOriginAnchorObservations != null && householdJointPlanCandidates == null
				&& householdEscortBindings == null) {
			throw new IllegalArgumentException(
					"Car origin-anchor repair requires a household binding catalog so joint driver legs can be guarded.");
		}
		if (householdJointPlanCandidates != null
				&& (householdEscortBindings != null || householdEscortJointReRoute
				|| householdEscortMaxUtility)) {
			throw new IllegalArgumentException(
					"All-household joint-plan innovation is mutually exclusive with historical escort pilots.");
		}
		if (householdJointPlanWithOrdinaryInnovation && householdJointPlanCandidates == null) {
			throw new IllegalArgumentException(
					"--household-joint-plan-with-ordinary-innovation requires "
							+ "--household-joint-plan-candidates.");
		}
		if ((physicalTaxi || networkTaxiProxy || walkOvertimeScoring) && !multimodalCosts) {
			throw new IllegalArgumentException(
					"Open Taxi/Walk scoring options require --multimodal-costs.");
		}
		if ((physicalTaxi || networkTaxiProxy) != walkOvertimeScoring) {
			throw new IllegalArgumentException(
					"This calibrated run requires network Taxi and Walk overtime scoring together.");
		}
		if (allPersonNetworkTaxiInnovation && !householdJointPlanWithOrdinaryInnovation) {
			throw new IllegalArgumentException(
					"All-person network Taxi innovation requires protected household innovation.");
		}
		if (unlimitedOrdinaryPtCapacity && !physicalNonTaxiModes) {
			throw new IllegalArgumentException(
					"--unlimited-ordinary-pt-capacity requires --physical-nontaxi-modes.");
		}
		if (householdEscortJointReRoute && multimodalCosts && !dynamicCarCosts) {
			throw new IllegalArgumentException(
					"Household JointReRoute cannot reuse the fixed-route Car cost tables; "
							+ "enable --dynamic-car-costs or run the isolated pilot without costs.");
		}
		Path routedPlans = null;
		for (int index = 1; index < args.length; index++) {
			String argument = args[index];
			if (!argument.startsWith("--") && !"unused".equals(argument)) {
				if (routedPlans != null) {
					throw new IllegalArgumentException("Only one routed-plans output may be supplied.");
				}
				routedPlans = Path.of(argument).toAbsolutePath();
			}
		}

		Config config = ConfigUtils.loadConfig(args[0], new SignalSystemsConfigGroup());
		HouseholdJointPlanSelectionSchedule householdSelectionSchedule =
				householdSelectionIterationsOption == null
						? (allPersonNetworkTaxiInnovation
								? HouseholdJointPlanSelectionSchedule.targetIterations5_10_15()
								: HouseholdJointPlanSelectionSchedule.historicalOneShot())
						: HouseholdJointPlanSelectionSchedule.targetIterations(
								parseStrictIterationSchedule(
										householdSelectionIterationsOption,
										config.controller().getLastIteration()));
		if (physicalTaxi) {
			configurePhysicalTaxi(config, taxiDvrpPcu, taxiWaitUtility);
		}
		SignalSystemsConfigGroup signalConfig = ConfigUtils.addOrGetModule(
				config, SignalSystemsConfigGroup.class);
		if (trafficSignals && !signalConfig.isUseSignalSystems()) {
			throw new IllegalArgumentException(
					"--traffic-signals requires signalsystems.useSignalsystems=true in config.");
		}
		if (trafficSignals && config.qsim().isUsingFastCapacityUpdate()) {
			config.qsim().setUsingFastCapacityUpdate(false);
			System.out.println(
					"Disabled QSim fast capacity update because MATSim signals require exact capacity updates.");
		}
		if (physicalNonTaxiModes) {
			configurePhysicalPtAndWalk(config);
			HongKongPhysicalWalkQSimModule.activateInConfig(config);
		}
		if (networkTaxiProxy) {
			HongKongNetworkTaxiRoutingModule.configure(config);
		}
		if (householdJointPlanCandidates != null) {
			if (householdJointPlanWithOrdinaryInnovation) {
				requireHouseholdSelectionWithOrdinaryInnovation(config);
			} else {
				requireHouseholdSelectionOnly(config);
			}
		}
		if (householdEscortBindings != null || householdJointPlanCandidates != null) {
			HouseholdEscortPhysicalQSimModule.activateInConfig(config);
		}
		if (studentSchoolModeCandidates != null || physicalNonTaxiModes) {
			SchoolBusPassengerPhysicalQSimModule.activateInConfig(config);
		}
		if (studentSchoolModeCandidates != null || physicalNonTaxiModes) {
			var mainModes = new java.util.LinkedHashSet<>(config.qsim().getMainModes());
			mainModes.add(SchoolBusAwareTransitDriverAgentFactory.SCHOOL_BUS_VEHICLE_MODE);
			config.qsim().setMainModes(mainModes);
		}
		boolean noRideTaxiRouting = !physicalTaxi && multimodalCosts && !networkTaxiProxy
				&& config.routing().getModeRoutingParams().containsKey(
						HongKongNoRideTaxiRoutingModule.PASSENGER_DELEGATE_MODE);
		if (multimodalCosts) {
			// Fail before loading the large scenario when the joint-scoring
			// configuration is incomplete or would double-charge Taxi distance.
			HongKongTaxiScoringParameters.centralV1().validateConfig(config);
			if (noRideTaxiRouting) {
				HongKongNoRideTaxiRoutingModule.configure(config);
			}
		}
		Scenario scenario = physicalTaxi
				? DrtControlerCreator.createScenarioWithDrtRouteFactory(config)
				: ScenarioUtils.createScenario(config);
		ScenarioUtils.loadScenario(scenario);
		HongKongRoadSupplyRegistry roadSupplyRegistry = null;
		if (roadSupplyRegistryPath != null) {
			String networkInput = config.network().getInputFile();
			if (networkInput == null || networkInput.isBlank()) {
				throw new IllegalArgumentException("Explicit road storage requires a file-backed network input.");
			}
			Path networkPath = Path.of(networkInput);
			if (!networkPath.isAbsolute()) {
				networkPath = Path.of(args[0]).toAbsolutePath().getParent().resolve(networkPath).normalize();
			}
			roadSupplyRegistry = HongKongRoadSupplyRegistry.load(
					roadSupplyRegistryPath, networkPath, scenario, taxiDvrpPcu);
			System.out.printf(
					"Validated explicit road-supply registry: roadLinks=%,d, storageOverrides=%,d, networkSHA=%s.%n",
					roadSupplyRegistry.roadLinkCount(), roadSupplyRegistry.overrides().size(),
					roadSupplyRegistry.sourceNetworkSha256());
		}
		if (physicalTaxi) {
			int restoredHomeOnlyPlans = normalizeEmptyHomeOnlyPlans(scenario);
			System.out.printf(
					"Restored %,d empty home-only plans as one stationary home activity for DVRP agent compatibility.%n",
					restoredHomeOnlyPlans);
		}
		if (networkTaxiProxy) {
			var stats = HongKongNetworkTaxiRoutingModule.prepareScenario(scenario);
			System.out.printf("Enabled road-coupled Taxi proxy on %,d Car links with %,d "
					+ "person-local Taxi vehicles (PCU=1; no cruising/deadheading/fleet matching).%n",
					stats.taxiEnabledCarLinks(), stats.personTaxiVehicles());
		}
		if (trafficSignals) {
			scenario.addScenarioElement(
					SignalsData.ELEMENT_NAME, new SignalsDataLoader(config).loadSignalsData());
			System.out.printf(
					"Loaded explicit MATSim traffic signals; systems=%s; groups=%s; control=%s.%n",
					signalConfig.getSignalSystemFile(),
					signalConfig.getSignalGroupsFile(),
					signalConfig.getSignalControlFile());
		}
		if (unlimitedOrdinaryPtCapacity) {
			int overriddenTypes = 0;
			for (var type : scenario.getTransitVehicles().getVehicleTypes().values()) {
				if (type.getId().toString().startsWith("school_bus_v6_")) continue;
				type.getCapacity().setSeats(1_000_000).setStandingRoom(0);
				overriddenTypes++;
			}
			if (overriddenTypes == 0) {
				throw new IllegalStateException("No ordinary PT vehicle types found for capacity-free gate.");
			}
			System.out.printf("Technical gate only: disabled ordinary-PT passenger capacity on %,d "
					+ "runtime vehicle types; adopted 10%% supply files remain unchanged.%n", overriddenTypes);
		}
		if (physicalNonTaxiModes) {
			int walkLinks = enableWalkOnRoadLinks(scenario);
			WalkRouteNormalizationStats walkStats = clearWalkRoutes(scenario);
			System.out.printf("Enabled capacity-free physical Walk on %,d road links and cleared "
					+ "%,d independent Walk routes for network rerouting; normalized %,d legs "
					+ "in %,d legacy PT/school-bus trip chains.%n",
					walkLinks, walkStats.clearedWalkRoutes(), walkStats.normalizedTransitLegs(),
					walkStats.transitTrips());
		}
		if (roadHotspotRepairV1) {
			var stats = HongKongRoadHotspotRepairV1.apply(scenario);
			System.out.printf(
					"Applied bounded no-signal road-hotspot repair: restrictedLinks=%,d, "
							+ "populationRoutes=%,d, transitRoutes=%,d, remappedStops=%,d, "
							+ "remappedActivities=%,d, "
							+ "replacements=%s.%n",
					stats.restrictedLinks(), stats.repairedPopulationRoutes(),
					stats.repairedTransitRoutes(), stats.remappedTransitStops(),
					stats.activityReferences(), stats.replacementPaths());
		}
		HouseholdEscortBindingCatalog householdEscortCatalog = householdEscortBindings == null
				? (householdJointPlanCandidates == null ? null : HouseholdEscortBindingCatalog.empty())
				: HouseholdEscortBindingCatalog.load(householdEscortBindings, scenario);
		HouseholdJointPlanCandidateCatalog householdJointCatalog = householdJointPlanCandidates == null
				? null : HouseholdJointPlanCandidateCatalog.load(householdJointPlanCandidates);
		if (restoreHouseholdBindingsOption != null) {
			int expected = Integer.parseInt(restoreHouseholdBindingsOption);
			int restored = HouseholdJointPlanCheckpointRestorer.restore(
					scenario, householdJointCatalog, householdEscortCatalog, expected);
			System.out.printf("Restored %,d frozen physical household bindings from selected checkpoint plans.%n",
					restored);
		}
		StudentSchoolModeCandidateCatalog studentSchoolCatalog = studentSchoolModeCandidates == null
				? StudentSchoolModeCandidateCatalog.empty()
				: StudentSchoolModeCandidateCatalog.load(studentSchoolModeCandidates);
		if (householdJointPlanWithOrdinaryInnovation) {
			int protectedPeople = protectHouseholdAndStudentCandidates(
					scenario, householdJointCatalog, studentSchoolCatalog);
			int borderPeople = restrictUnpricedBorderCarModeInnovation(scenario);
			System.out.printf(
					"Protected %,d household joint/escort or student candidate people from ordinary "
							+ "individual replanning; %,d additional people with unpriced border activities "
							+ "retain route and time innovation but cannot generate a new Car mode; all other "
							+ "agents retain route, mode, and time innovation.%n",
					protectedPeople, borderPeople);
		}
		HongKongCarOriginAnchorObservationCatalog carOriginAnchorCatalog =
				carOriginAnchorObservations == null ? null
						: HongKongCarOriginAnchorObservationCatalog.load(carOriginAnchorObservations);
		if (studentSchoolCatalog.enabled()) {
			if (!config.transit().getTransitModes().contains("school_bus")) {
				throw new IllegalArgumentException(
						"Student school-mode candidates require physical transit mode school_bus.");
			}
			int overriddenTypes = 0;
			for (var type : scenario.getTransitVehicles().getVehicleTypes().values()) {
				if (!type.getId().toString().startsWith("school_bus_v6_")) continue;
				type.getCapacity().setSeats(1_000_000).setStandingRoom(0);
				overriddenTypes++;
			}
			if (overriddenTypes == 0) {
				throw new IllegalStateException("No school_bus_v6 vehicle types found for unlimited-capacity run.");
			}
			int schoolBusVehicleLinks = 0;
			for (var link : scenario.getNetwork().getLinks().values()) {
				if (!link.getAllowedModes().contains("school_bus")) continue;
				var allowedModes = new java.util.LinkedHashSet<>(link.getAllowedModes());
				if (allowedModes.add(SchoolBusAwareTransitDriverAgentFactory.SCHOOL_BUS_VEHICLE_MODE)) {
					link.setAllowedModes(allowedModes);
					schoolBusVehicleLinks++;
				}
			}
			System.out.printf(
					"Enabled %,d student school trips with %,d physical school-bus options; "
							+ "school-bus seat constraints are disabled by runtime capacity override on %,d types; "
							+ "school_bus_vehicle enabled on %,d school-bus links.%n",
					studentSchoolCatalog.trips().size(), studentSchoolCatalog.physicalSchoolBusOptionCount(),
					overriddenTypes, schoolBusVehicleLinks);
			int normalizedTransitLegs = SchoolBusPassengerPhysicalEngine
					.normalizeGenericPassengerTransitModes(scenario);
			System.out.printf("Pre-QSim normalized %,d generic passenger transit-mode legs to pt.%n",
					normalizedTransitLegs);
		}
		if (physicalNonTaxiModes) {
			WalkRouteNormalizationStats finalStats = normalizePhysicalTripRoutingModes(scenario);
			int walkVehicleIds = assignPhysicalWalkBookkeepingVehicles(scenario);
			System.out.printf("Final MATSim-trip synchronization normalized %,d legs in %,d "
					+ "PT/school-bus trips and cleared %,d independent Walk routes; assigned %,d "
					+ "non-QNetwork Walk bookkeeping vehicle ids.%n",
					finalStats.normalizedTransitLegs(), finalStats.transitTrips(),
					finalStats.clearedWalkRoutes(), walkVehicleIds);
		}
		if (studentSchoolCatalog.enabled()) {
			int restoredCandidateIds = studentSchoolCatalog
					.restoreMissingSelectedSchoolBusCandidateIds(scenario);
			studentSchoolCatalog.snapshotSelectedSchoolBusPlans(scenario);
			System.out.printf(
					"Restored %,d stable candidate IDs and snapshotted frozen experienced school-bus trips before initial PrepareForSim.%n",
					restoredCandidateIds);
		}
		if (clearPtRoutes) {
			int clearedPtRoutes = clearPtRoutes(scenario);
			System.out.printf("Cleared %,d existing pt routes for SwissRailRaptor rerouting.%n", clearedPtRoutes);
		}
		HongKongPhysicalTaxiFleetLoader.FleetLoadStats physicalTaxiFleetStats = null;
		if (physicalTaxi) {
			physicalTaxiFleetStats = HongKongPhysicalTaxiFleetLoader.load(
					scenario, taxiDvrpFleet, taxiDvrpPcu);
			var routeStats = HongKongPhysicalTaxiRoutePreparation.prepare(scenario);
			System.out.printf(
					"Enabled physical Taxi fleet: vehicles=%,d, pcu=%.2f, service=%.0f..%.0f, "
							+ "taxiLegs=%,d, convertedRoutes=%,d, copiedTripAttributes=%,d, "
							+ "removedLegacyProxyVehicles=%,d, removedLegacyPersonMappings=%,d.%n",
					physicalTaxiFleetStats.vehicles(), physicalTaxiFleetStats.pcu(),
					physicalTaxiFleetStats.earliestServiceBegin(),
					physicalTaxiFleetStats.latestServiceEnd(), routeStats.taxiLegs(),
					routeStats.convertedRoutes(), routeStats.copiedTripAttributes(),
					physicalTaxiFleetStats.removedLegacyProxyVehicles(),
					physicalTaxiFleetStats.removedLegacyPersonMappings());
		}
		int assignedVehicles = 0;
		for (Person person : scenario.getPopulation().getPersons().values()) {
			Object value = person.getAttributes().getAttribute("assignedVehicleId");
			if (value == null || value.toString().isBlank() || "nan".equalsIgnoreCase(value.toString())) {
				continue;
			}
			Id<Vehicle> vehicleId = Id.create(value.toString(), Vehicle.class);
			if (!scenario.getVehicles().getVehicles().containsKey(vehicleId)) {
				throw new IllegalStateException("Person " + person.getId() + " references missing vehicle " + vehicleId);
			}
			var vehicleIds = new java.util.LinkedHashMap<>(VehicleUtils.getVehicleIds(person));
			vehicleIds.put("car", vehicleId);
			VehicleUtils.insertVehicleIdsIntoAttributes(person, vehicleIds);
			assignedVehicles++;
		}

		System.out.printf("Loaded %,d persons; assigned %,d explicit car vehicles.%n",
			scenario.getPopulation().getPersons().size(), assignedVehicles);
		Controler controler = new Controler(scenario);
		if (roadSupplyRegistry != null) {
			controler.addOverridingModule(new HongKongExplicitStorageModule(roadSupplyRegistry));
			System.out.println(
					"Enabled independent explicit QSim storage on "
							+ roadSupplyRegistry.overrides().size()
							+ " road links; physical length, lanes, free speed, and flow capacity remain unchanged.");
		}
		if (physicalTaxi) {
			MultiModeTaxiConfigGroup taxiConfig = MultiModeTaxiConfigGroup.get(config);
			controler.addOverridingModule(new DvrpModule());
			controler.addOverridingModule(new MultiModeTaxiModule());
			controler.addOverridingModule(new HongKongPhysicalTaxiAuditModule(
					physicalTaxiParameters(config, taxiWaitUtility),
					new HongKongPhysicalTaxiFleetRegistry(
							physicalTaxiFleetStats.serviceWindows())));
			controler.configureQSimComponents(
					DvrpQSimComponents.activateAllModes(taxiConfig));
			System.out.println(
					"Enabled official Taxi/DVRP passenger engine and assignment optimizer; "
							+ "person-local Taxi proxy is disabled.");
		}
		if (trafficSignals) {
			Signals.configure(controler);
			System.out.println("Enabled explicit movement-level traffic-signal control.");
		}
		if (roadSupplyRegistry != null) {
			// Signals installs its own QNetworkFactory. Install the combined Hong Kong
			// factory last so signal turn acceptance and explicit per-link road supply
			// are both active in the same QSim network.
			controler.addOverridingQSimModule(new HongKongExplicitStorageQSimModule());
		}
		controler.addOverridingModule(new SwissRailRaptorModule());
		if (physicalNonTaxiModes) {
			controler.addOverridingModule(new HongKongOrdinaryPtRaptorModule());
			System.out.println("Excluded school-bus routes from the ordinary-PT Raptor routing view.");
		}
		if (householdEscortCatalog != null) {
			HouseholdEscortBindingCatalog sharedEscortCatalog = householdEscortCatalog;
			controler.addOverridingModule(new AbstractModule() {
				@Override
				public void install() {
					bind(HouseholdEscortBindingCatalog.class).toInstance(sharedEscortCatalog);
				}
			});
			controler.addQSimModule(new HouseholdEscortPhysicalQSimModule(householdEscortCatalog));
			System.out.printf("Enabled %,d initial household physical bindings%s.%n",
					householdEscortCatalog.bindings().size(), householdEscortBindings == null
						? " (delayed selection after iteration 0)" : " from " + householdEscortBindings);
		}
		if ((studentSchoolCatalog.enabled() || physicalNonTaxiModes)
				&& householdJointCatalog == null) {
			StudentSchoolModeCandidateCatalog sharedStudentCatalog = studentSchoolCatalog;
			HouseholdEscortBindingCatalog sharedEmptyOrExistingEscortCatalog =
					householdEscortCatalog == null
							? HouseholdEscortBindingCatalog.empty()
							: householdEscortCatalog;
			controler.addOverridingModule(new AbstractModule() {
				@Override
				public void install() {
					bind(StudentSchoolModeCandidateCatalog.class).toInstance(sharedStudentCatalog);
					bind(HouseholdEscortBindingCatalog.class)
							.toInstance(sharedEmptyOrExistingEscortCatalog);
					if (sharedStudentCatalog.enabled()) {
						bind(org.matsim.core.controler.PrepareForMobsimImpl.class);
						bind(org.matsim.core.controler.PrepareForMobsim.class)
								.to(SchoolBusAwarePrepareForMobsim.class);
					}
				}
			});
		}
		if (studentSchoolCatalog.enabled() || physicalNonTaxiModes) {
			controler.addQSimModule(new SchoolBusPassengerPhysicalQSimModule());
			System.out.println(physicalNonTaxiModes
					? "Enabled physical regular-PT and guarded school-bus passenger handling."
					: "Enabled school-bus-only physical passenger departure handler; generic pt remains teleported.");
		}
		if (physicalNonTaxiModes) {
			controler.addOverridingModule(new HongKongPhysicalWalkModule());
			controler.addQSimModule(new HongKongPhysicalWalkQSimModule());
			System.out.println(physicalTaxi
					? "Enabled capacity-free network-physical Walk; Taxi uses the finite DVRP fleet."
					: "Enabled capacity-free network-physical Walk; Taxi remains teleported.");
		}
		if (householdJointCatalog != null) {
			HouseholdJointPlanCandidateCatalog sharedJointCatalog = householdJointCatalog;
			controler.addOverridingModule(new AbstractModule() {
				@Override
				public void install() {
					bind(HouseholdJointPlanCandidateCatalog.class).toInstance(sharedJointCatalog);
				}
			});
			controler.addOverridingModule(new HouseholdJointPlanInnovationModule(
					studentSchoolCatalog, householdSelectionSchedule));
			System.out.printf("Enabled %,d all-car-household joint-plan candidates from %s; "
					+ "baseline selection is preserved in iteration 0; independent student choices="
					+ "%s.%n",
					householdJointCatalog.candidates().size(), householdJointPlanCandidates,
					studentSchoolCatalog.enabled() ? "pt|taxi|walk|school_bus(unlimited)" : "disabled");
		}
		if (carOriginAnchorCatalog != null) {
			controler.addOverridingModule(
					new HongKongCarOriginAnchorRepairModule(carOriginAnchorCatalog));
			System.out.printf(
					"Enabled bounded private-Car origin-anchor audit/repair for %,d observed initial reverses; "
							+ "active household waypoint legs are guarded.%n",
					carOriginAnchorCatalog.observations().size());
		}
		if (householdEscortJointReRoute) {
			controler.addOverridingModule(new HouseholdEscortJointReRouteModule(householdEscortCatalog));
			System.out.println(
					"Enabled one-shot fixed-binding household school-escort JointReRoute after it.0.");
		}
		if (householdEscortMaxUtility) {
			controler.addOverridingModule(new HouseholdEscortMaxUtilitySelectorModule());
			System.out.println(
					"Enabled one-shot deterministic household bound-versus-real-PT/Taxi/Walk "
							+ "maximum-utility selection; passenger Car is unavailable.");
		}
		if (noRideTaxiRouting) {
			controler.addOverridingModule(new HongKongNoRideTaxiRoutingModule());
		}
		if (networkTaxiProxy) {
			controler.addOverridingModule(new HongKongNetworkTaxiRoutingModule());
		}
		if (multimodalCosts) {
			controler.addOverridingModule(new HongKongMultimodalCostScoringModule(
					physicalTaxi || networkTaxiProxy
							? HongKongTaxiFareUtilityPolicy.openInnovationV1()
							: HongKongTaxiFareUtilityPolicy.historicalCentralV1(),
					ptFareRoot,
					carCostRoot,
					dynamicCarCosts));
			System.out.printf(
					"Enabled Hong Kong Taxi/PT/Car joint cost scoring; PT root=%s; Car root=%s; dynamicCarCosts=%s.%n",
					ptFareRoot,
					carCostRoot,
					dynamicCarCosts);
		}
		if (walkOvertimeScoring) {
			controler.addOverridingModule(new HongKongWalkOvertimeScoringComponentModule());
			System.out.println("Enabled cumulative per-main-trip Walk overtime scoring: "
					+ "threshold=600 s; slope=3.278342 util/h.");
		}
		if (!simulate) {
			controler.addOverridingModule(new AbstractModule() {
				@Override
				public void install() {
					bind(Mobsim.class).toInstance(() -> { });
				}
			});
		}
		controler.run();

		if (routedPlans != null) {
			new PopulationWriter(scenario.getPopulation(), scenario.getNetwork()).write(routedPlans.toString());
			System.out.println("Wrote routed plans to " + routedPlans);
		}
	}

	static int normalizeEmptyHomeOnlyPlans(Scenario scenario) {
		int restored = 0;
		for (Person person : scenario.getPopulation().getPersons().values()) {
			Plan plan = person.getSelectedPlan();
			if (plan == null || plan.getPlanElements().stream().anyMatch(Activity.class::isInstance)) {
				continue;
			}
			if (!plan.getPlanElements().isEmpty()) {
				throw new IllegalStateException(
						"Selected plan has legs but no activity: person=" + person.getId());
			}
			Object householdValue = person.getAttributes().getAttribute("householdId");
			String householdId = householdValue instanceof String text && !text.isBlank()
					? text : null;
			var facilityId = Id.create(
					"home_" + (householdId == null ? person.getId() : householdId),
					org.matsim.facilities.ActivityFacility.class);
			var facility = scenario.getActivityFacilities().getFacilities().get(facilityId);
			if (facility == null && householdId != null) {
				facilityId = Id.create(
						"home_" + person.getId(), org.matsim.facilities.ActivityFacility.class);
				facility = scenario.getActivityFacilities().getFacilities().get(facilityId);
			}
			if (facility == null || facility.getLinkId() == null) {
				throw new IllegalStateException(
						"Empty home-only plan has no link-referenced home facility: person="
								+ person.getId() + ", facility=" + facilityId);
			}
			Activity home = PopulationUtils.createActivityFromLinkId("home", facility.getLinkId());
			home.setFacilityId(facilityId);
			home.setCoord(facility.getCoord());
			plan.addActivity(home);
			restored++;
		}
		return restored;
	}

	private static void installFatalMainThreadExitHandler() {
		Thread.currentThread().setUncaughtExceptionHandler((thread, failure) -> {
			System.err.println("FATAL_HK_MAIN_THREAD: terminating JVM after uncaught failure on "
					+ thread.getName());
			failure.printStackTrace(System.err);
			System.err.flush();
			System.exit(1);
		});
	}

	static boolean usesNetworkTaxiProxy(
			boolean allPersonNetworkTaxiInnovation,
			boolean fixedPlansNetworkTaxiProxy,
			boolean physicalTaxi) {
		return fixedPlansNetworkTaxiProxy
				|| (allPersonNetworkTaxiInnovation && !physicalTaxi);
	}

	private static void configurePhysicalPtAndWalk(Config config) {
		if (!config.transit().isUseTransit() || !config.transit().isUsingTransitInMobsim()) {
			throw new IllegalArgumentException("Physical PT requires useTransit=true and usingTransitInMobsim=true.");
		}
		var transitModes = new java.util.LinkedHashSet<>(config.transit().getTransitModes());
		transitModes.add("pt");
		config.transit().setTransitModes(transitModes);

		var walkParams = config.routing().getModeRoutingParams().get(
				org.matsim.api.core.v01.TransportMode.walk);
		if (walkParams == null || walkParams.getTeleportedModeSpeed() == null) {
			throw new IllegalArgumentException("Physical Walk requires the existing Walk speed parameters.");
		}
		if (!config.routing().getModeRoutingParams().containsKey(
				org.matsim.api.core.v01.TransportMode.non_network_walk)) {
			var accessWalk = new org.matsim.core.config.groups.RoutingConfigGroup.TeleportedModeParams(
					org.matsim.api.core.v01.TransportMode.non_network_walk);
			accessWalk.setTeleportedModeSpeed(walkParams.getTeleportedModeSpeed());
			accessWalk.setBeelineDistanceFactor(walkParams.getBeelineDistanceFactor());
			config.routing().addTeleportedModeParams(accessWalk);
		}
		config.routing().removeTeleportedModeParams(org.matsim.api.core.v01.TransportMode.walk);
		var networkModes = new java.util.LinkedHashSet<>(config.routing().getNetworkModes());
		// The custom Walk QSim engine consumes a NetworkRoute but intentionally has
		// no vehicle. Keeping Walk in MATSim's standard networkModes would make
		// PrepareForSim demand a vehicle id for every pedestrian.
		networkModes.remove(org.matsim.api.core.v01.TransportMode.walk);
		config.routing().setNetworkModes(networkModes);
	}

	private static int enableWalkOnRoadLinks(Scenario scenario) {
		int changed = 0;
		for (var link : scenario.getNetwork().getLinks().values()) {
			if (!link.getAllowedModes().contains(org.matsim.api.core.v01.TransportMode.car)
					|| link.getAllowedModes().contains(org.matsim.api.core.v01.TransportMode.walk)) {
				continue;
			}
			var modes = new java.util.LinkedHashSet<>(link.getAllowedModes());
			modes.add(org.matsim.api.core.v01.TransportMode.walk);
			link.setAllowedModes(modes);
			changed++;
		}
		return changed;
	}

	private static WalkRouteNormalizationStats clearWalkRoutes(Scenario scenario) {
		int cleared = 0;
		int transitTrips = 0;
		int normalizedTransitLegs = 0;
		for (Person person : scenario.getPopulation().getPersons().values()) {
			for (Plan plan : person.getPlans()) {
				var tripLegs = new ArrayList<Leg>();
				for (PlanElement element : plan.getPlanElements()) {
					if (element instanceof Leg leg) {
						tripLegs.add(leg);
					} else if (element instanceof Activity activity
							&& !activity.getType().endsWith(" interaction")
							&& !tripLegs.isEmpty()) {
						TripLegNormalizationResult result = normalizeTripLegs(scenario, tripLegs);
						cleared += result.clearedWalkRoutes();
						transitTrips += result.transitTrip() ? 1 : 0;
						normalizedTransitLegs += result.normalizedTransitLegs();
						tripLegs.clear();
					}
				}
				if (!tripLegs.isEmpty()) {
					TripLegNormalizationResult result = normalizeTripLegs(scenario, tripLegs);
					cleared += result.clearedWalkRoutes();
					transitTrips += result.transitTrip() ? 1 : 0;
					normalizedTransitLegs += result.normalizedTransitLegs();
				}
			}
		}
		return new WalkRouteNormalizationStats(cleared, transitTrips, normalizedTransitLegs);
	}

	private static TripLegNormalizationResult normalizeTripLegs(
			Scenario scenario, java.util.List<Leg> legs) {
		boolean schoolBusTrip = legs.stream().anyMatch(leg ->
					"school_bus".equals(leg.getMode()) || "school_bus".equals(
					org.matsim.core.router.TripStructureUtils.getRoutingMode(leg)));
		boolean ptTrip = schoolBusTrip || legs.stream().anyMatch(leg ->
				scenario.getConfig().transit().getTransitModes().contains(leg.getMode())
						|| "pt".equals(org.matsim.core.router.TripStructureUtils.getRoutingMode(leg)));
		String routingMode;
		if (schoolBusTrip) {
			routingMode = "school_bus";
		} else if (ptTrip) {
			routingMode = "pt";
		} else if (containsModeOrRoutingMode(legs, org.matsim.api.core.v01.TransportMode.car)) {
			routingMode = org.matsim.api.core.v01.TransportMode.car;
		} else if (containsModeOrRoutingMode(legs, "car_passenger")) {
			routingMode = "car_passenger";
		} else if (containsModeOrRoutingMode(legs, "taxi")) {
			routingMode = "taxi";
		} else if (containsModeOrRoutingMode(legs, org.matsim.api.core.v01.TransportMode.walk)) {
			routingMode = org.matsim.api.core.v01.TransportMode.walk;
		} else {
			routingMode = org.matsim.core.router.TripStructureUtils.getRoutingMode(legs.getFirst());
			if (routingMode == null) routingMode = legs.getFirst().getMode();
		}

		for (Leg leg : legs) {
			leg.setRoutingMode(routingMode);
		}
		if (ptTrip) {
			return new TripLegNormalizationResult(0, true, legs.size());
		}

		int clearedWalkRoutes = 0;
		if (org.matsim.api.core.v01.TransportMode.walk.equals(routingMode)) {
			for (Leg leg : legs) {
				if (!org.matsim.api.core.v01.TransportMode.walk.equals(leg.getMode())) continue;
				leg.setRoute(null);
				clearedWalkRoutes++;
			}
		}
		return new TripLegNormalizationResult(clearedWalkRoutes, false, 0);
	}

	private static boolean containsModeOrRoutingMode(java.util.List<Leg> legs, String mode) {
		return legs.stream().anyMatch(leg -> mode.equals(leg.getMode())
				|| mode.equals(org.matsim.core.router.TripStructureUtils.getRoutingMode(leg)));
	}

	private static int assignPhysicalWalkBookkeepingVehicles(Scenario scenario) {
		var typeId = Id.create("physical_walk_bookkeeping", org.matsim.vehicles.VehicleType.class);
		var vehicleType = scenario.getVehicles().getVehicleTypes().get(typeId);
		if (vehicleType == null) {
			vehicleType = VehicleUtils.createVehicleType(typeId)
					.setNetworkMode(org.matsim.api.core.v01.TransportMode.walk)
					.setPcuEquivalents(0.0)
					.setMaximumVelocity(HongKongPhysicalWalkModule.WALK_SPEED_M_S);
			scenario.getVehicles().addVehicleType(vehicleType);
		}
		int assigned = 0;
		for (Person person : scenario.getPopulation().getPersons().values()) {
			// Raptor and car routers may create physical Walk access/egress legs
			// later in PrepareForSim, so every person needs the bookkeeping id now.
			Id<Vehicle> vehicleId = VehicleUtils.createVehicleId(
					person, org.matsim.api.core.v01.TransportMode.walk);
			if (!scenario.getVehicles().getVehicles().containsKey(vehicleId)) {
				scenario.getVehicles().addVehicle(VehicleUtils.createVehicle(vehicleId, vehicleType));
			}
			var ids = new java.util.LinkedHashMap<>(VehicleUtils.getVehicleIds(person));
			ids.put(org.matsim.api.core.v01.TransportMode.walk, vehicleId);
			VehicleUtils.insertVehicleIdsIntoAttributes(person, ids);
			assigned++;
		}
		return assigned;
	}

	/**
	 * Repeats the routing-mode synchronization with MATSim's own trip partition
	 * after legacy bus/GMB/rail execution modes have been collapsed to {@code pt}.
	 * This deliberately runs last: PrepareForSim rejects a legacy PT chain when
	 * only its in-vehicle legs carry a routing mode.
	 */
	private static WalkRouteNormalizationStats normalizePhysicalTripRoutingModes(Scenario scenario) {
		int cleared = 0;
		int transitTrips = 0;
		int normalizedTransitLegs = 0;
		for (Person person : scenario.getPopulation().getPersons().values()) {
			for (Plan plan : person.getPlans()) {
				for (var trip : org.matsim.core.router.TripStructureUtils.getTrips(plan)) {
					TripLegNormalizationResult result = normalizeTripLegs(
							scenario, trip.getLegsOnly());
					cleared += result.clearedWalkRoutes();
					transitTrips += result.transitTrip() ? 1 : 0;
					normalizedTransitLegs += result.normalizedTransitLegs();
				}
			}
		}
		return new WalkRouteNormalizationStats(cleared, transitTrips, normalizedTransitLegs);
	}

	private record WalkRouteNormalizationStats(
			int clearedWalkRoutes, int transitTrips, int normalizedTransitLegs) { }

	private record TripLegNormalizationResult(
			int clearedWalkRoutes, boolean transitTrip, int normalizedTransitLegs) { }

	private static Path optionPath(String[] args, String prefix) {
		Path result = null;
		for (String argument : args) {
			if (!argument.startsWith(prefix)) {
				continue;
			}
			if (result != null) {
				throw new IllegalArgumentException("Duplicate option: " + prefix);
			}
			String value = argument.substring(prefix.length());
			if (value.isBlank()) {
				throw new IllegalArgumentException("Empty path option: " + prefix);
			}
			result = Path.of(value).toAbsolutePath().normalize();
		}
		return result;
	}

	private static Double optionDouble(String[] args, String prefix) {
		Double result = null;
		for (String argument : args) {
			if (!argument.startsWith(prefix)) continue;
			if (result != null) throw new IllegalArgumentException("Duplicate option: " + prefix);
			String value = argument.substring(prefix.length());
			if (value.isBlank()) throw new IllegalArgumentException("Empty numeric option: " + prefix);
			try {
				result = Double.parseDouble(value);
			} catch (NumberFormatException error) {
				throw new IllegalArgumentException("Invalid numeric option: " + argument, error);
			}
		}
		return result;
	}

	private static String optionString(String[] args, String prefix) {
		String result = null;
		for (String argument : args) {
			if (!argument.startsWith(prefix)) continue;
			if (result != null) throw new IllegalArgumentException("Duplicate option: " + prefix);
			result = argument.substring(prefix.length());
			if (result.isBlank()) throw new IllegalArgumentException("Empty option: " + prefix);
		}
		return result;
	}

	static Set<Integer> parseStrictIterationSchedule(String value, int lastIteration) {
		if (lastIteration < 1) throw new IllegalArgumentException("lastIteration must be positive");
		var result = new java.util.LinkedHashSet<Integer>();
		int previous = -1;
		for (String token : value.split(",", -1)) {
			if (token.isBlank() || !token.equals(token.trim())) {
				throw new IllegalArgumentException("Invalid household selection iteration list: " + value);
			}
			int iteration;
			try {
				iteration = Integer.parseInt(token);
			} catch (NumberFormatException error) {
				throw new IllegalArgumentException("Invalid household selection iteration: " + token, error);
			}
			if (iteration < 1 || iteration > lastIteration) {
				throw new IllegalArgumentException(
						"Household selection iteration outside 1.." + lastIteration + ": " + iteration);
			}
			if (iteration <= previous || !result.add(iteration)) {
				throw new IllegalArgumentException(
						"Household selection iterations must be unique and strictly increasing: " + value);
			}
			previous = iteration;
		}
		if (result.isEmpty()) throw new IllegalArgumentException("Empty household selection iteration list");
		return java.util.Collections.unmodifiableSet(result);
	}

	static void configurePhysicalTaxi(
			Config config, double pcu, double totalWaitUtilityPerHour) {
		if (!HongKongPhysicalTaxiFleetLoader.ALLOWED_PCU.contains(pcu)) {
			throw new IllegalArgumentException(
					"Taxi PCU must be one of " + HongKongPhysicalTaxiFleetLoader.ALLOWED_PCU
							+ "; actual=" + pcu);
		}
		var modeParams = config.scoring().getModes().get(HongKongTaxiScoringParameters.TAXI_MODE);
		if (modeParams == null) {
			throw new IllegalArgumentException("Physical Taxi requires scoring mode params for taxi.");
		}
		new HongKongPhysicalTaxiParameters(
				modeParams.getMarginalUtilityOfTraveling(), totalWaitUtilityPerHour);
		var networkModes = new java.util.LinkedHashSet<>(config.routing().getNetworkModes());
		networkModes.remove(HongKongTaxiScoringParameters.TAXI_MODE);
		config.routing().setNetworkModes(networkModes);
		var mainModes = new java.util.LinkedHashSet<>(config.qsim().getMainModes());
		mainModes.remove(HongKongTaxiScoringParameters.TAXI_MODE);
		config.qsim().setMainModes(mainModes);
		config.routing().removeTeleportedModeParams(HongKongTaxiScoringParameters.TAXI_MODE);

		MultiModeTaxiConfigGroup multiTaxi = new MultiModeTaxiConfigGroup();
		config.addModule(multiTaxi);
		TaxiConfigGroup taxi = new TaxiConfigGroup();
		taxi.mode = HongKongTaxiScoringParameters.TAXI_MODE;
		taxi.destinationKnown = true;
		taxi.vehicleDiversion = false;
		taxi.onlineVehicleTracker = false;
		taxi.pickupDuration = 60;
		taxi.dropoffDuration = 30;
		taxi.taxisFile = null;
		taxi.breakSimulationIfNotAllRequestsServed = false;
		taxi.numberOfThreads = Math.max(1, config.global().getNumberOfThreads());
		RuleBasedTaxiOptimizerParams optimizer = new RuleBasedTaxiOptimizerParams();
		optimizer.goal = RuleBasedRequestInserter.Goal.MIN_WAIT_TIME;
		optimizer.reoptimizationTimeStep = 30;
		optimizer.nearestRequestsLimit = 30;
		optimizer.nearestVehiclesLimit = 30;
		taxi.addParameterSet(optimizer);
		multiTaxi.addParameterSet(taxi);

		DvrpConfigGroup dvrp = new DvrpConfigGroup();
		dvrp.setNetworkModes(Set.of(org.matsim.api.core.v01.TransportMode.car));
		dvrp.setMobsimMode(org.matsim.api.core.v01.TransportMode.car);
		config.addModule(dvrp);
		config.qsim().setRemoveStuckVehicles(false);
		config.qsim().setStuckTime(3600);
		config.eventsManager().setSynchronizeOnSimSteps(true);
	}

	private static HongKongPhysicalTaxiParameters physicalTaxiParameters(
			Config config, double totalWaitUtilityPerHour) {
		return new HongKongPhysicalTaxiParameters(
				config.scoring().getModes().get(HongKongTaxiScoringParameters.TAXI_MODE)
						.getMarginalUtilityOfTraveling(),
				totalWaitUtilityPerHour);
	}

	private static void requireHouseholdSelectionOnly(Config config) {
		Map<String, Integer> keepLastSelectedBySubpopulation = new HashMap<>();
		Set<String> subpopulations = new HashSet<>();
		for (var settings : config.replanning().getStrategySettings()) {
			String subpopulation = settings.getSubpopulation();
			if (subpopulation == null || subpopulation.isBlank()) {
				throw new IllegalArgumentException(
						"All-household joint-plan validation requires explicit strategy subpopulations.");
			}
			subpopulations.add(subpopulation);
			if ("KeepLastSelected".equals(settings.getStrategyName())) {
				if (Math.abs(settings.getWeight() - 1.0) > 1e-12) {
					throw new IllegalArgumentException(
							"KeepLastSelected must have weight 1 for " + subpopulation);
				}
				keepLastSelectedBySubpopulation.merge(subpopulation, 1, Integer::sum);
			} else if (Math.abs(settings.getWeight()) > 1e-12) {
				throw new IllegalArgumentException(
						"All-household maximum-utility validation cannot run a second plan selector: "
								+ settings.getStrategyName() + " weight=" + settings.getWeight());
			}
		}
		if (subpopulations.isEmpty()) {
			throw new IllegalArgumentException("No replanning subpopulations were configured.");
		}
		for (String subpopulation : subpopulations) {
			if (keepLastSelectedBySubpopulation.getOrDefault(subpopulation, 0) != 1) {
				throw new IllegalArgumentException(
						"Expected exactly one KeepLastSelected strategy for " + subpopulation);
			}
		}
	}

	private static void requireHouseholdSelectionWithOrdinaryInnovation(Config config) {
		Map<String, Set<String>> positiveStrategies = new HashMap<>();
		Set<String> required = Set.of(
				"ChangeExpBeta", "ReRoute", "SubtourModeChoice",
				"TimeAllocationMutator_ReRoute");
		Set<String> borderRequired = Set.of(
				"ChangeExpBeta", "ReRoute", "TimeAllocationMutator_ReRoute");
		for (var settings : config.replanning().getStrategySettings()) {
			String subpopulation = settings.getSubpopulation();
			if (subpopulation == null || subpopulation.isBlank()) {
				throw new IllegalArgumentException(
						"Household-compatible ordinary innovation requires explicit strategy subpopulations.");
			}
			if (settings.getWeight() > 0.0) {
				positiveStrategies.computeIfAbsent(subpopulation, ignored -> new HashSet<>())
						.add(settings.getStrategyName());
			}
		}
		if (positiveStrategies.isEmpty()) {
			throw new IllegalArgumentException("No positive replanning strategies were configured.");
		}
		for (var entry : positiveStrategies.entrySet()) {
			if (org.matsim.project.hongkong.household.HouseholdJointPlanSelector
					.PROTECTED_SUBPOPULATION.equals(entry.getKey())) {
				if (!entry.getValue().equals(Set.of("KeepLastSelected"))) {
					throw new IllegalArgumentException(
							"Protected household/student candidates must use KeepLastSelected only: "
									+ entry.getValue());
				}
				continue;
			}
			if (UNPRICED_BORDER_SUBPOPULATION.equals(entry.getKey())) {
				if (!entry.getValue().containsAll(borderRequired)
						|| entry.getValue().contains("SubtourModeChoice")) {
					throw new IllegalArgumentException(
							"Unpriced-border people require route/time innovation without "
									+ "SubtourModeChoice: " + entry.getValue());
				}
				continue;
			}
			if (!entry.getValue().containsAll(required)) {
				Set<String> missing = new HashSet<>(required);
				missing.removeAll(entry.getValue());
				throw new IllegalArgumentException(
						"Ordinary innovation is incomplete for " + entry.getKey()
								+ "; missing positive strategies " + missing);
			}
		}
	}

	private static int protectHouseholdAndStudentCandidates(
			Scenario scenario,
			HouseholdJointPlanCandidateCatalog householdCandidates,
			StudentSchoolModeCandidateCatalog studentCandidates) {
		Set<Id<Person>> ids = new HashSet<>();
		for (Person person : scenario.getPopulation().getPersons().values()) {
			boolean hasOriginalPassengerLeg = person.getSelectedPlan().getPlanElements().stream()
					.filter(Leg.class::isInstance)
					.map(Leg.class::cast)
					.anyMatch(leg -> "car_passenger".equals(leg.getMode()));
			if (hasOriginalPassengerLeg) {
				ids.add(person.getId());
			}
		}
		for (var candidate : householdCandidates.candidates()) {
			ids.add(Id.createPersonId(candidate.passengerPersonId()));
			ids.add(Id.createPersonId(candidate.driverPersonId()));
		}
		for (var key : studentCandidates.trips().keySet()) {
			ids.add(Id.createPersonId(key.personId()));
		}
		for (Id<Person> id : ids) {
			Person person = scenario.getPopulation().getPersons().get(id);
			if (person == null) {
				throw new IllegalStateException("Special candidate person is absent: " + id);
			}
			PopulationUtils.putSubpopulation(
					person, org.matsim.project.hongkong.household.HouseholdJointPlanSelector
							.PROTECTED_SUBPOPULATION);
		}
		return ids.size();
	}

	private static int restrictUnpricedBorderCarModeInnovation(Scenario scenario) {
		int protectedPeople = 0;
		for (Person person : scenario.getPopulation().getPersons().values()) {
			if (org.matsim.project.hongkong.household.HouseholdJointPlanSelector
					.PROTECTED_SUBPOPULATION.equals(PopulationUtils.getSubpopulation(person))) {
				continue;
			}
			boolean hasBorderActivity = person.getSelectedPlan().getPlanElements().stream()
					.filter(Activity.class::isInstance)
					.map(Activity.class::cast)
					.map(Activity::getFacilityId)
					.filter(java.util.Objects::nonNull)
					.anyMatch(id -> id.toString().startsWith("border_"));
			if (hasBorderActivity) {
				boolean hasExistingCarLeg = person.getSelectedPlan().getPlanElements().stream()
						.filter(Leg.class::isInstance)
						.map(Leg.class::cast)
						.anyMatch(leg -> "car".equals(leg.getMode()));
				if (hasExistingCarLeg) {
					throw new IllegalStateException(
							"Unpriced border plan already contains Car and cannot be priced: "
									+ person.getId());
				}
				PopulationUtils.putSubpopulation(person, UNPRICED_BORDER_SUBPOPULATION);
				protectedPeople++;
			}
		}
		return protectedPeople;
	}

	private static int clearPtRoutes(Scenario scenario) {
		int cleared = 0;
		for (Person person : scenario.getPopulation().getPersons().values()) {
			for (Plan plan : person.getPlans()) {
				for (PlanElement element : plan.getPlanElements()) {
					if (element instanceof Leg leg && "pt".equals(leg.getMode()) && leg.getRoute() != null) {
						leg.setRoute(null);
						cleared++;
					}
				}
			}
		}
		return cleared;
	}
}
