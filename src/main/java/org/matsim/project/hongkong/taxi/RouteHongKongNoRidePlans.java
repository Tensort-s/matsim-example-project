package org.matsim.project.hongkong.taxi;

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
import org.matsim.core.router.TripStructureUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.vehicles.Vehicle;
import org.matsim.vehicles.VehicleUtils;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Route-only preparation for the Hong Kong population with explicit Taxi,
 * car-passenger and school-bus modes and no aggregate ride mode.
 *
 * <p>The input is expected to contain routes on every unchanged trip and null
 * routes only on the student-to-student mode exchanges. Standard MATSim
 * prepare-for-sim therefore rebuilds just the affected plans. Taxi uses the
 * native passenger routing module and PT uses SwissRailRaptor. No QSim or
 * behavioral replanning is run.</p>
 */
public final class RouteHongKongNoRidePlans {

	private static final Map<String, Long> EXPECTED_RAW_INPUT_MODES = Map.of(
			"car", 67_718L,
			"car_passenger", 2_734L,
			"pt", 557_104L,
			"school_bus", 9_626L,
			"taxi", 44_000L,
			"walk", 197_868L
	);
	private static final Map<String, Long> EXPECTED_MAIN_MODES = Map.of(
			"car", 67_718L,
			"car_passenger", 2_734L,
			"pt", 557_104L,
			"school_bus", 9_626L,
			"taxi", 44_000L,
			"walk", 62_432L
	);

	private RouteHongKongNoRidePlans() {
	}

	public static void main(String[] args) {
		if (args.length != 4) {
			throw new IllegalArgumentException(
					"Usage: RouteHongKongNoRidePlans "
							+ "<route-config.xml> <input-preroute-plans.xml.gz> "
							+ "<output-routed-plans.xml.gz> <controller-output-directory>"
			);
		}
		Path configPath = Path.of(args[0]).toAbsolutePath().normalize();
		Path inputPlans = Path.of(args[1]).toAbsolutePath().normalize();
		Path outputPlans = Path.of(args[2]).toAbsolutePath().normalize();
		Path controllerOutput = Path.of(args[3]).toAbsolutePath().normalize();
		if (!Files.isRegularFile(configPath) || !Files.isRegularFile(inputPlans)) {
			throw new IllegalArgumentException("Config and input plans must be regular files");
		}
		if (Files.exists(outputPlans)) {
			throw new IllegalArgumentException("Routed output already exists: " + outputPlans);
		}
		if (Files.exists(controllerOutput)) {
			throw new IllegalArgumentException(
					"Controller output already exists: " + controllerOutput);
		}

		Config config = ConfigUtils.loadConfig(configPath.toString());
		config.plans().setInputFile(inputPlans.toString());
		config.controller().setFirstIteration(0);
		config.controller().setLastIteration(0);
		config.controller().setOutputDirectory(controllerOutput.toString());
		config.replanning().clearStrategySettings();
		HongKongNoRideTaxiRoutingModule.configure(config);

		Scenario scenario = ScenarioUtils.loadScenario(config);
		assignExplicitCarVehicles(scenario);
		RouteAudit before = auditModesAndRoutes(scenario, true);
		requireExactMainModes("input", before);
		if (!EXPECTED_RAW_INPUT_MODES.equals(before.rawLegModeCounts())) {
			throw new IllegalStateException(
					"input raw-leg mode counts differ: "
							+ before.rawLegModeCounts() + " != " + EXPECTED_RAW_INPUT_MODES);
		}

		Controler controler = new Controler(scenario);
		controler.addOverridingModule(new SwissRailRaptorModule());
		controler.addOverridingModule(new HongKongNoRideTaxiRoutingModule());
		controler.addOverridingModule(new AbstractModule() {
			@Override
			public void install() {
				bind(Mobsim.class).toInstance(() -> { });
			}
		});
		controler.run();

		RouteAudit after = auditModesAndRoutes(scenario, false);
		requireExactMainModes("routed", after);
		Path parent = outputPlans.getParent();
		if (parent != null) {
			try {
				Files.createDirectories(parent);
			} catch (Exception error) {
				throw new IllegalStateException("Cannot create routed output parent", error);
			}
		}
		new PopulationWriter(scenario.getPopulation(), scenario.getNetwork())
				.write(outputPlans.toString());
		System.out.println("Input audit: " + before);
		System.out.println("Routed audit: " + after);
		System.out.println("Wrote routed no-ride plans to " + outputPlans);
	}

	private static int assignExplicitCarVehicles(Scenario scenario) {
		int assigned = 0;
		for (Person person : scenario.getPopulation().getPersons().values()) {
			Object value = person.getAttributes().getAttribute("assignedVehicleId");
			if (value == null || value.toString().isBlank()
					|| "nan".equalsIgnoreCase(value.toString())) {
				continue;
			}
			Id<Vehicle> vehicleId = Id.create(value.toString(), Vehicle.class);
			if (!scenario.getVehicles().getVehicles().containsKey(vehicleId)) {
				throw new IllegalStateException(
						"Person " + person.getId() + " references missing vehicle " + vehicleId);
			}
			VehicleUtils.insertVehicleIdsIntoAttributes(person, Map.of("car", vehicleId));
			assigned++;
		}
		System.out.printf("Assigned %,d explicit car vehicles.%n", assigned);
		return assigned;
	}

	private static RouteAudit auditModesAndRoutes(
			Scenario scenario,
			boolean allowStudentExchangeNullRoutes) {
		Map<String, Long> rawModes = new LinkedHashMap<>();
		Map<String, Long> mainModes = new LinkedHashMap<>();
		long nullRoutes = 0;
		long taxiWithoutType = 0;
		for (Person person : scenario.getPopulation().getPersons().values()) {
			Plan plan = person.getSelectedPlan();
			if (plan == null) {
				throw new IllegalStateException("Person has no selected plan: " + person.getId());
			}
			for (PlanElement element : plan.getPlanElements()) {
				if (!(element instanceof Leg leg)) {
					continue;
				}
				rawModes.merge(leg.getMode(), 1L, Long::sum);
				if (leg.getRoute() == null) {
					nullRoutes++;
				}
				if ("ride".equals(leg.getMode())) {
					throw new IllegalStateException(
							"Aggregate ride remains on person " + person.getId());
				}
				if ("taxi".equals(leg.getMode())
						&& leg.getAttributes().getAttribute("hkTaxiType") == null) {
					taxiWithoutType++;
				}
			}
			for (TripStructureUtils.Trip trip : TripStructureUtils.getTrips(plan)) {
				String mode = TripStructureUtils.getRoutingModeIdentifier()
						.identifyMainMode(trip.getTripElements());
				mainModes.merge(mode, 1L, Long::sum);
			}
		}
		if (!allowStudentExchangeNullRoutes && nullRoutes != 0) {
			throw new IllegalStateException(
					"Route-only preparation left " + nullRoutes + " null routes");
		}
		if (allowStudentExchangeNullRoutes && nullRoutes != 3_824) {
			throw new IllegalStateException(
					"Pre-route population must contain exactly 3,824 null routes; found "
							+ nullRoutes);
		}
		if (taxiWithoutType != 0) {
			throw new IllegalStateException(
					"Taxi legs without hkTaxiType: " + taxiWithoutType);
		}
		return new RouteAudit(rawModes, mainModes, nullRoutes, taxiWithoutType);
	}

	private static void requireExactMainModes(String label, RouteAudit audit) {
		if (!EXPECTED_MAIN_MODES.equals(audit.mainModeCounts())) {
			throw new IllegalStateException(
					label + " main-trip mode counts differ: "
							+ audit.mainModeCounts() + " != " + EXPECTED_MAIN_MODES);
		}
	}

	private record RouteAudit(
			Map<String, Long> rawLegModeCounts,
			Map<String, Long> mainModeCounts,
			long nullRoutes,
			long taxiWithoutType) {
	}
}
