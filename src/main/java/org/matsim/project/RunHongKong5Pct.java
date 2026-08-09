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
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.project.hongkong.scoring.HongKongMultimodalCostScoringModule;
import org.matsim.project.hongkong.household.HouseholdEscortBindingCatalog;
import org.matsim.project.hongkong.household.HouseholdEscortJointReRouteModule;
import org.matsim.project.hongkong.household.HouseholdEscortMaxUtilitySelectorModule;
import org.matsim.project.hongkong.household.HouseholdEscortPhysicalQSimModule;
import org.matsim.project.hongkong.household.HouseholdJointPlanCandidateCatalog;
import org.matsim.project.hongkong.household.HouseholdJointPlanInnovationModule;
import org.matsim.project.hongkong.pt.HongKongOrdinaryPtRaptorModule;
import org.matsim.project.hongkong.schoolbus.StudentSchoolModeCandidateCatalog;
import org.matsim.project.hongkong.schoolbus.SchoolBusPassengerPhysicalEngine;
import org.matsim.project.hongkong.schoolbus.SchoolBusPassengerPhysicalQSimModule;
import org.matsim.project.hongkong.schoolbus.SchoolBusAwareTransitDriverAgentFactory;
import org.matsim.project.hongkong.taxi.HongKongNoRideTaxiRoutingModule;
import org.matsim.project.hongkong.taxi.HongKongTaxiScoringParameters;
import org.matsim.project.hongkong.walk.HongKongPhysicalWalkModule;
import org.matsim.project.hongkong.walk.HongKongPhysicalWalkQSimModule;
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

	private RunHongKong5Pct() {
	}

	public static void main(String[] args) {
		if (args.length < 1) {
			throw new IllegalArgumentException(
				"Usage: RunHongKong5Pct <config.xml> [routed-plans.xml.gz] [--simulate] "
						+ "[--clear-pt-routes] [--multimodal-costs "
						+ "--pt-fare-root=<path> --car-cost-root=<path> [--dynamic-car-costs]] "
						+ "[--household-escort-bindings=<path>] "
						+ "[--household-escort-joint-reroute] [--household-escort-max-utility] "
						+ "[--household-joint-plan-candidates=<path>] "
						+ "[--student-school-mode-candidates=<directory>] "
						+ "[--physical-nontaxi-modes] [--unlimited-ordinary-pt-capacity]"
			);
		}
		boolean simulate = Arrays.asList(args).contains("--simulate");
		boolean clearPtRoutes = Arrays.asList(args).contains("--clear-pt-routes");
		boolean multimodalCosts = Arrays.asList(args).contains("--multimodal-costs");
		boolean dynamicCarCosts = Arrays.asList(args).contains("--dynamic-car-costs");
		boolean physicalNonTaxiModes = Arrays.asList(args).contains("--physical-nontaxi-modes");
		boolean unlimitedOrdinaryPtCapacity = Arrays.asList(args)
				.contains("--unlimited-ordinary-pt-capacity");
		boolean householdEscortJointReRoute = Arrays.asList(args)
				.contains("--household-escort-joint-reroute");
		boolean householdEscortMaxUtility = Arrays.asList(args)
				.contains("--household-escort-max-utility");
		Path ptFareRoot = optionPath(args, "--pt-fare-root=");
		Path carCostRoot = optionPath(args, "--car-cost-root=");
		Path householdEscortBindings = optionPath(args, "--household-escort-bindings=");
		Path householdJointPlanCandidates = optionPath(args, "--household-joint-plan-candidates=");
		Path studentSchoolModeCandidates = optionPath(args, "--student-school-mode-candidates=");
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
		if (householdJointPlanCandidates != null
				&& (householdEscortBindings != null || householdEscortJointReRoute
				|| householdEscortMaxUtility)) {
			throw new IllegalArgumentException(
					"All-household joint-plan innovation is mutually exclusive with historical escort pilots.");
		}
		if (studentSchoolModeCandidates != null && householdJointPlanCandidates == null) {
			throw new IllegalArgumentException(
					"--student-school-mode-candidates currently requires --household-joint-plan-candidates.");
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

		Config config = ConfigUtils.loadConfig(args[0]);
		if (physicalNonTaxiModes) {
			configurePhysicalPtAndWalk(config);
			HongKongPhysicalWalkQSimModule.activateInConfig(config);
		}
		if (householdJointPlanCandidates != null) {
			requireHouseholdSelectionOnly(config);
		}
		if (householdEscortBindings != null || householdJointPlanCandidates != null) {
			HouseholdEscortPhysicalQSimModule.activateInConfig(config);
		}
		if (studentSchoolModeCandidates != null || physicalNonTaxiModes) {
			SchoolBusPassengerPhysicalQSimModule.activateInConfig(config);
		}
		if (studentSchoolModeCandidates != null) {
			var mainModes = new java.util.LinkedHashSet<>(config.qsim().getMainModes());
			mainModes.add(SchoolBusAwareTransitDriverAgentFactory.SCHOOL_BUS_VEHICLE_MODE);
			config.qsim().setMainModes(mainModes);
		}
		boolean noRideTaxiRouting = multimodalCosts
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
		Scenario scenario = ScenarioUtils.loadScenario(config);
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
		HouseholdEscortBindingCatalog householdEscortCatalog = householdEscortBindings == null
				? (householdJointPlanCandidates == null ? null : HouseholdEscortBindingCatalog.empty())
				: HouseholdEscortBindingCatalog.load(householdEscortBindings, scenario);
		HouseholdJointPlanCandidateCatalog householdJointCatalog = householdJointPlanCandidates == null
				? null : HouseholdJointPlanCandidateCatalog.load(householdJointPlanCandidates);
		StudentSchoolModeCandidateCatalog studentSchoolCatalog = studentSchoolModeCandidates == null
				? StudentSchoolModeCandidateCatalog.empty()
				: StudentSchoolModeCandidateCatalog.load(studentSchoolModeCandidates);
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
		if (clearPtRoutes) {
			int clearedPtRoutes = clearPtRoutes(scenario);
			System.out.printf("Cleared %,d existing pt routes for SwissRailRaptor rerouting.%n", clearedPtRoutes);
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
			VehicleUtils.insertVehicleIdsIntoAttributes(person, Map.of("car", vehicleId));
			assignedVehicles++;
		}

		System.out.printf("Loaded %,d persons; assigned %,d explicit car vehicles.%n",
			scenario.getPopulation().getPersons().size(), assignedVehicles);
		Controler controler = new Controler(scenario);
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
		if (studentSchoolCatalog.enabled() || physicalNonTaxiModes) {
			controler.addQSimModule(new SchoolBusPassengerPhysicalQSimModule());
			System.out.println(physicalNonTaxiModes
					? "Enabled physical regular-PT and guarded school-bus passenger handling."
					: "Enabled school-bus-only physical passenger departure handler; generic pt remains teleported.");
		}
		if (physicalNonTaxiModes) {
			controler.addOverridingModule(new HongKongPhysicalWalkModule());
			controler.addQSimModule(new HongKongPhysicalWalkQSimModule());
			System.out.println("Enabled capacity-free network-physical Walk; Taxi remains teleported.");
		}
		if (householdJointCatalog != null) {
			HouseholdJointPlanCandidateCatalog sharedJointCatalog = householdJointCatalog;
			controler.addOverridingModule(new AbstractModule() {
				@Override
				public void install() {
					bind(HouseholdJointPlanCandidateCatalog.class).toInstance(sharedJointCatalog);
				}
			});
			controler.addOverridingModule(new HouseholdJointPlanInnovationModule(studentSchoolCatalog));
			System.out.printf("Enabled %,d all-car-household joint-plan candidates from %s; "
					+ "baseline selection is preserved in iteration 0; independent student choices="
					+ "%s.%n",
					householdJointCatalog.candidates().size(), householdJointPlanCandidates,
					studentSchoolCatalog.enabled() ? "pt|taxi|walk|school_bus(unlimited)" : "disabled");
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
		if (multimodalCosts) {
			controler.addOverridingModule(new HongKongMultimodalCostScoringModule(
					HongKongTaxiScoringParameters.centralV1(),
					ptFareRoot,
					carCostRoot,
					dynamicCarCosts));
			System.out.printf(
					"Enabled Hong Kong Taxi/PT/Car joint cost scoring; PT root=%s; Car root=%s; dynamicCarCosts=%s.%n",
					ptFareRoot,
					carCostRoot,
					dynamicCarCosts);
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
