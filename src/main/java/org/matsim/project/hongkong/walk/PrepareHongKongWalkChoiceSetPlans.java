package org.matsim.project.hongkong.walk;

import ch.sbb.matsim.routing.pt.raptor.SwissRailRaptorModule;
import com.google.inject.Inject;
import com.google.inject.Provider;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.TransportMode;
import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.controler.AbstractModule;
import org.matsim.core.controler.Controler;
import org.matsim.core.controler.events.StartupEvent;
import org.matsim.core.controler.listener.StartupListener;
import org.matsim.core.mobsim.framework.Mobsim;
import org.matsim.core.population.io.PopulationWriter;
import org.matsim.core.router.TripRouter;
import org.matsim.core.router.DefaultRoutingRequest;
import org.matsim.core.router.TripStructureUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.contrib.signals.SignalSystemsConfigGroup;
import org.matsim.facilities.FacilitiesUtils;
import org.matsim.project.hongkong.household.HouseholdJointPlanCandidateCatalog;
import org.matsim.project.hongkong.schoolbus.StudentSchoolModeCandidateCatalog;
import org.matsim.project.hongkong.taxi.HongKongNoRideTaxiRoutingModule;
import org.matsim.utils.objectattributes.attributable.AttributesImpl;
import org.matsim.vehicles.Vehicle;
import org.matsim.vehicles.VehicleType;
import org.matsim.vehicles.VehicleUtils;

import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashSet;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Locale;
import java.util.Set;

/** Immutable route-and-repair stage for the Hong Kong Walk calibration choice set. */
public final class PrepareHongKongWalkChoiceSetPlans {
	private static final Id<VehicleType> WALK_ROUTING_VEHICLE_TYPE_ID =
			Id.create("hk_walk_choice_set_routing_type", VehicleType.class);
	private static final Id<Vehicle> WALK_ROUTING_VEHICLE_ID =
			Id.createVehicleId("hk_walk_choice_set_routing_vehicle");

	private record Settings(
			Path outputPlans,
			Path auditCsv,
			Path unresolvedCsv,
			int maxAlternatives) {
	}

	private PrepareHongKongWalkChoiceSetPlans() {
	}

	public static void main(String[] args) {
		if (args.length != 9) {
			throw new IllegalArgumentException(
					"Usage: PrepareHongKongWalkChoiceSetPlans <config.xml> <input-plans.xml.gz> "
							+ "<household-candidates.csv> <student-school-candidates-dir> "
							+ "<output-plans.xml.gz> <audit.csv> "
							+ "<unresolved.csv> <controller-output-dir> <max-short-alternatives-per-person>");
		}
		Path configPath = regularFile(args[0], "config");
		Path inputPlans = regularFile(args[1], "input plans");
		Path householdCandidates = regularFile(args[2], "household candidates");
		Path studentSchoolCandidates = directory(args[3], "student school-mode candidates");
		Path outputPlans = absent(args[4], "output plans");
		Path auditCsv = absent(args[5], "audit CSV");
		Path unresolvedCsv = absent(args[6], "unresolved CSV");
		Path controllerOutput = absent(args[7], "controller output");
		int maxAlternatives = Integer.parseInt(args[8]);
		if (maxAlternatives < 0 || maxAlternatives > 4) {
			throw new IllegalArgumentException("Short-Walk alternatives per person must be 0..4");
		}

		Config config = ConfigUtils.loadConfig(
				configPath.toString(), new SignalSystemsConfigGroup());
		config.plans().setInputFile(inputPlans.toString());
		config.controller().setFirstIteration(0);
		config.controller().setLastIteration(0);
		config.controller().setOutputDirectory(controllerOutput.toString());
		config.replanning().clearStrategySettings();
		Scenario scenario = ScenarioUtils.loadScenario(config);
		int enabledWalkLinks = HongKongPhysicalWalkModule.enableOnCarLinks(
				scenario.getNetwork());
		installWalkRoutingVehicle(scenario);
		System.out.printf(
				"Enabled the production physical-Walk graph on %,d additional Car road links for preparation.%n",
				enabledWalkLinks);
		Set<String> protectedIds = protectedPeople(
				scenario, householdCandidates, studentSchoolCandidates);
		Settings settings = new Settings(outputPlans, auditCsv, unresolvedCsv, maxAlternatives);

		Controler controler = new Controler(scenario);
		controler.addOverridingModule(new SwissRailRaptorModule());
		controler.addOverridingModule(new HongKongNoRideTaxiRoutingModule());
		controler.addOverridingModule(new HongKongPhysicalWalkModule());
		controler.addOverridingModule(new AbstractModule() {
			@Override
			public void install() {
				bind(Settings.class).toInstance(settings);
				bind(new com.google.inject.TypeLiteral<Set<String>>() { })
						.annotatedWith(com.google.inject.name.Names.named("walkRepairProtectedIds"))
						.toInstance(protectedIds);
				addControlerListenerBinding().to(PreparationListener.class);
				bind(Mobsim.class).toInstance(() -> { });
			}
		});
		controler.run();
	}

	private static final class PreparationListener implements StartupListener {
		private final Provider<TripRouter> tripRouterProvider;
		private final Scenario scenario;
		private final Settings settings;
		private final Set<String> protectedIds;
		private final Map<String, HongKongWalkChoiceSetRepair.WalkAssessment> walkCache =
				new HashMap<>();

		@Inject
		PreparationListener(
				Provider<TripRouter> tripRouterProvider,
				Scenario scenario,
				Settings settings,
				@com.google.inject.name.Named("walkRepairProtectedIds") Set<String> protectedIds) {
			this.tripRouterProvider = tripRouterProvider;
			this.scenario = scenario;
			this.settings = settings;
			this.protectedIds = protectedIds;
		}

		@Override
		public void notifyStartup(StartupEvent event) {
			TripRouter router = tripRouterProvider.get();
			HongKongWalkChoiceSetRepair.Result result = HongKongWalkChoiceSetRepair.repair(
					scenario.getPopulation().getPersons().values(), protectedIds,
					(person, origin, destination, departure, selectedMode) -> assessWalk(
							router, person, origin, destination, departure, selectedMode),
					(mode, person, origin, destination, departure) -> router.calcRoute(
							mode,
							FacilitiesUtils.toFacility(origin, scenario.getActivityFacilities()),
							FacilitiesUtils.toFacility(destination, scenario.getActivityFacilities()),
							departure, person, routeRequestAttributes(mode)),
					settings.maxAlternatives());
			writeOutputs(result);
		}

		private HongKongWalkChoiceSetRepair.WalkAssessment assessWalk(
				TripRouter router, Person person, Activity origin, Activity destination,
				double departure, String selectedMode) {
			Coord originCoord = activityCoord(origin);
			Coord destinationCoord = activityCoord(destination);
			double lowerBoundS = Math.hypot(
					originCoord.getX() - destinationCoord.getX(),
					originCoord.getY() - destinationCoord.getY())
					/ HongKongPhysicalWalkModule.WALK_SPEED_M_S;
			if (!TransportMode.walk.equals(selectedMode)
					&& lowerBoundS > HongKongWalkChoiceSetRepair.SHORT_WALK_S) {
				return HongKongWalkChoiceSetRepair.WalkAssessment.notEvaluated(
						"not_short_by_straight_line_lower_bound");
			}
			String key = endpointKey(origin) + "->" + endpointKey(destination);
			return walkCache.computeIfAbsent(key, ignored -> {
				List<? extends PlanElement> routed = router.calcRoute(
						TransportMode.walk,
						FacilitiesUtils.toFacility(origin, scenario.getActivityFacilities()),
						FacilitiesUtils.toFacility(destination, scenario.getActivityFacilities()),
						departure, person, routeRequestAttributes(TransportMode.walk));
				return assessRoutedWalk(routed);
			});
		}

		private Coord activityCoord(Activity activity) {
			if (activity.getCoord() != null) return activity.getCoord();
			if (activity.getLinkId() != null
					&& scenario.getNetwork().getLinks().containsKey(activity.getLinkId())) {
				return scenario.getNetwork().getLinks().get(activity.getLinkId()).getCoord();
			}
			throw new IllegalStateException("Activity lacks both coordinate and network link");
		}

		private static String endpointKey(Activity activity) {
			if (activity.getLinkId() != null) return "link:" + activity.getLinkId();
			Coord coord = activity.getCoord();
			if (coord == null) return "missing";
			return String.format(Locale.ROOT, "coord:%.3f:%.3f", coord.getX(), coord.getY());
		}

		private void writeOutputs(HongKongWalkChoiceSetRepair.Result result) {
			createParent(settings.outputPlans());
			createParent(settings.auditCsv());
			createParent(settings.unresolvedCsv());
			new PopulationWriter(scenario.getPopulation(), scenario.getNetwork())
					.write(settings.outputPlans().toString());
			writeCsv(settings.auditCsv(), result, false);
			writeCsv(settings.unresolvedCsv(), result, true);
			System.out.printf(Locale.ROOT,
					"Walk choice-set repair completed: protected_tours=%d, ordinary_trips=%d, "
							+ "short_alternatives=%d, unresolved_long_walks=%d, actions=%s%n",
					result.protectedToursRepaired(), result.ordinaryTripsRepaired(),
					result.shortWalkAlternativesAdded(), result.unresolvedLongWalkTrips(),
					result.actionCounts());
		}
	}

	static void installWalkRoutingVehicle(Scenario scenario) {
		if (scenario.getVehicles().getVehicles().containsKey(WALK_ROUTING_VEHICLE_ID)) return;
		VehicleType type = scenario.getVehicles().getVehicleTypes().get(WALK_ROUTING_VEHICLE_TYPE_ID);
		if (type == null) {
			type = VehicleUtils.createVehicleType(
					WALK_ROUTING_VEHICLE_TYPE_ID, TransportMode.walk);
			type.setMaximumVelocity(HongKongPhysicalWalkModule.WALK_SPEED_M_S);
			scenario.getVehicles().addVehicleType(type);
		}
		scenario.getVehicles().addVehicle(
				VehicleUtils.createVehicle(WALK_ROUTING_VEHICLE_ID, type));
	}

	static AttributesImpl routeRequestAttributes(String mode) {
		AttributesImpl attributes = new AttributesImpl();
		if (TransportMode.walk.equals(mode)) {
			attributes.putAttribute(
					DefaultRoutingRequest.ATTRIBUTE_VEHICLE_ID, WALK_ROUTING_VEHICLE_ID);
		}
		return attributes;
	}

	static HongKongWalkChoiceSetRepair.WalkAssessment assessRoutedWalk(
			List<? extends PlanElement> routed) {
		double timeS = 0.0;
		double distanceM = 0.0;
		int physicalWalkLegs = 0;
		for (PlanElement element : routed) {
			if (!(element instanceof Leg leg)) continue;
			if (leg.getRoute() == null || !leg.getTravelTime().isDefined()) {
				throw new IllegalStateException(
						"Physical Walk assessment returned an unrouted leg mode=" + leg.getMode());
			}
			timeS += leg.getTravelTime().seconds();
			if (TransportMode.walk.equals(leg.getMode())) {
				distanceM += leg.getRoute().getDistance();
				physicalWalkLegs++;
			}
		}
		if (physicalWalkLegs != 1) {
			throw new IllegalStateException("Walk assessment requires exactly one Walk leg");
		}
		return HongKongWalkChoiceSetRepair.WalkAssessment.routed(timeS, distanceM);
	}

	static Set<String> protectedPeople(
			Scenario scenario, Path candidateCsv, Path studentCandidateDirectory) {
		Set<String> ids = new LinkedHashSet<>();
		for (var candidate : HouseholdJointPlanCandidateCatalog.load(candidateCsv).candidates()) {
			ids.add(candidate.passengerPersonId());
			ids.add(candidate.driverPersonId());
		}
		StudentSchoolModeCandidateCatalog.load(studentCandidateDirectory).trips().keySet()
				.forEach(key -> ids.add(key.personId()));
		for (Person person : scenario.getPopulation().getPersons().values()) {
			if (person.getSelectedPlan() == null) continue;
			boolean carPassenger = TripStructureUtils.getTrips(person.getSelectedPlan()).stream()
					.anyMatch(trip -> "car_passenger".equals(
							TripStructureUtils.getRoutingModeIdentifier()
									.identifyMainMode(trip.getTripElements())));
			if (carPassenger) ids.add(person.getId().toString());
		}
		System.out.printf("Protected %,d household/student people for atomic Walk repair.%n", ids.size());
		return Set.copyOf(ids);
	}

	private static void writeCsv(
			Path path, HongKongWalkChoiceSetRepair.Result result, boolean unresolvedOnly) {
		try (BufferedWriter writer = Files.newBufferedWriter(
				path, StandardCharsets.UTF_8, java.nio.file.StandardOpenOption.CREATE_NEW)) {
			writer.write("person_id,trip_index,tour_index,protected_person,selected_mode_before,"
					+ "network_walk_time_s,network_walk_distance_m,walk_class,action,detail\n");
			for (var row : result.rows()) {
				if (unresolvedOnly && !row.action().startsWith("unresolved")) continue;
				writer.write(csv(row.personId()) + "," + row.tripIndex() + "," + row.tourIndex()
						+ "," + row.protectedPerson() + "," + csv(row.selectedModeBefore())
						+ "," + number(row.networkWalkTimeS()) + "," + number(row.networkWalkDistanceM())
						+ "," + csv(row.walkClass()) + "," + csv(row.action()) + ","
						+ csv(row.detail()) + "\n");
			}
		} catch (IOException error) {
			throw new IllegalStateException("Cannot write Walk choice-set audit " + path, error);
		}
	}

	private static String number(double value) {
		return Double.isFinite(value) ? String.format(Locale.ROOT, "%.3f", value) : "";
	}

	private static String csv(String value) {
		String text = value == null ? "" : value;
		return "\"" + text.replace("\"", "\"\"") + "\"";
	}

	private static Path regularFile(String value, String label) {
		Path path = Path.of(value).toAbsolutePath().normalize();
		if (!Files.isRegularFile(path)) {
			throw new IllegalArgumentException(label + " must be a regular file: " + path);
		}
		return path;
	}

	private static Path directory(String value, String label) {
		Path path = Path.of(value).toAbsolutePath().normalize();
		if (!Files.isDirectory(path)) {
			throw new IllegalArgumentException(label + " must be a directory: " + path);
		}
		return path;
	}

	private static Path absent(String value, String label) {
		Path path = Path.of(value).toAbsolutePath().normalize();
		if (Files.exists(path)) {
			throw new IllegalArgumentException(label + " must not already exist: " + path);
		}
		return path;
	}

	private static void createParent(Path path) {
		Path parent = path.getParent();
		if (parent == null || Files.isDirectory(parent)) return;
		try {
			Files.createDirectories(parent);
		} catch (IOException error) {
			throw new IllegalStateException("Cannot create output parent " + parent, error);
		}
	}
}
