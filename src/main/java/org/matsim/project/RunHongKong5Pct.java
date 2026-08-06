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
import org.matsim.project.hongkong.taxi.HongKongNoRideTaxiRoutingModule;
import org.matsim.project.hongkong.taxi.HongKongTaxiScoringParameters;
import org.matsim.vehicles.Vehicle;
import org.matsim.vehicles.VehicleUtils;

import java.nio.file.Path;
import java.util.Arrays;
import java.util.Map;

/** Loads and runs the Hong Kong 5% road/PT scenario with explicit car vehicles. */
public final class RunHongKong5Pct {

	private RunHongKong5Pct() {
	}

	public static void main(String[] args) {
		if (args.length < 1) {
			throw new IllegalArgumentException(
				"Usage: RunHongKong5Pct <config.xml> [routed-plans.xml.gz] [--simulate] "
						+ "[--clear-pt-routes] [--multimodal-costs "
						+ "--pt-fare-root=<path> --car-cost-root=<path>]"
			);
		}
		boolean simulate = Arrays.asList(args).contains("--simulate");
		boolean clearPtRoutes = Arrays.asList(args).contains("--clear-pt-routes");
		boolean multimodalCosts = Arrays.asList(args).contains("--multimodal-costs");
		Path ptFareRoot = optionPath(args, "--pt-fare-root=");
		Path carCostRoot = optionPath(args, "--car-cost-root=");
		if (multimodalCosts && (ptFareRoot == null || carCostRoot == null)) {
			throw new IllegalArgumentException(
					"--multimodal-costs requires both --pt-fare-root and --car-cost-root.");
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
		if (noRideTaxiRouting) {
			controler.addOverridingModule(new HongKongNoRideTaxiRoutingModule());
		}
		if (multimodalCosts) {
			controler.addOverridingModule(new HongKongMultimodalCostScoringModule(
					HongKongTaxiScoringParameters.centralV1(),
					ptFareRoot,
					carCostRoot));
			System.out.printf(
					"Enabled Hong Kong Taxi/PT/Car joint cost scoring; PT root=%s; Car root=%s.%n",
					ptFareRoot,
					carCostRoot);
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
