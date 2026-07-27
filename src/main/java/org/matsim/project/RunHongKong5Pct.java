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
				"Usage: RunHongKong5Pct <config.xml> [routed-plans.xml.gz] [--simulate] [--clear-pt-routes]"
			);
		}
		boolean simulate = Arrays.asList(args).contains("--simulate");
		boolean clearPtRoutes = Arrays.asList(args).contains("--clear-pt-routes");
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
