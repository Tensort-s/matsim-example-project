package org.matsim.project;

import ch.sbb.matsim.routing.pt.raptor.SwissRailRaptorModule;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
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
import org.matsim.project.hongkong.taxi.HongKongNoRideTaxiRoutingModule;
import org.matsim.project.hongkong.taxi.HongKongTaxiScoringParameters;
import org.matsim.vehicles.Vehicle;
import org.matsim.vehicles.VehicleUtils;

import java.nio.file.Path;
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
						+ "[--household-joint-plan-candidates=<path>]"
			);
		}
		boolean simulate = Arrays.asList(args).contains("--simulate");
		boolean clearPtRoutes = Arrays.asList(args).contains("--clear-pt-routes");
		boolean multimodalCosts = Arrays.asList(args).contains("--multimodal-costs");
		boolean dynamicCarCosts = Arrays.asList(args).contains("--dynamic-car-costs");
		boolean householdEscortJointReRoute = Arrays.asList(args)
				.contains("--household-escort-joint-reroute");
		boolean householdEscortMaxUtility = Arrays.asList(args)
				.contains("--household-escort-max-utility");
		Path ptFareRoot = optionPath(args, "--pt-fare-root=");
		Path carCostRoot = optionPath(args, "--car-cost-root=");
		Path householdEscortBindings = optionPath(args, "--household-escort-bindings=");
		Path householdJointPlanCandidates = optionPath(args, "--household-joint-plan-candidates=");
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
		if (householdJointPlanCandidates != null) {
			requireHouseholdSelectionOnly(config);
		}
		if (householdEscortBindings != null || householdJointPlanCandidates != null) {
			HouseholdEscortPhysicalQSimModule.activateInConfig(config);
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
		HouseholdEscortBindingCatalog householdEscortCatalog = householdEscortBindings == null
				? (householdJointPlanCandidates == null ? null : HouseholdEscortBindingCatalog.empty())
				: HouseholdEscortBindingCatalog.load(householdEscortBindings, scenario);
		HouseholdJointPlanCandidateCatalog householdJointCatalog = householdJointPlanCandidates == null
				? null : HouseholdJointPlanCandidateCatalog.load(householdJointPlanCandidates);
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
		if (householdJointCatalog != null) {
			HouseholdJointPlanCandidateCatalog sharedJointCatalog = householdJointCatalog;
			controler.addOverridingModule(new AbstractModule() {
				@Override
				public void install() {
					bind(HouseholdJointPlanCandidateCatalog.class).toInstance(sharedJointCatalog);
				}
			});
			controler.addOverridingModule(new HouseholdJointPlanInnovationModule());
			System.out.printf("Enabled %,d all-car-household joint-plan candidates from %s; "
					+ "baseline selection is preserved in iteration 0; car_passenger releases="
					+ "pt|taxi|walk; school_bus disabled.%n",
					householdJointCatalog.candidates().size(), householdJointPlanCandidates);
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
