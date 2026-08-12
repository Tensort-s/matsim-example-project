package org.matsim.project.hongkong.road;

import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.population.routes.NetworkRoute;
import org.matsim.core.scenario.ScenarioUtils;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.ArrayList;
import java.util.List;

/** Full-scenario validator for the order-preserving run62 repair V1 materializer. */
public final class MaterializeHongKongRoadHotspotRepairV1 {

	private MaterializeHongKongRoadHotspotRepairV1() { }

	public static void main(String[] args) throws Exception {
		if ((args.length != 6 && args.length != 7) || !"--validate".equals(args[0])) {
			throw new IllegalArgumentException("Usage: MaterializeHongKongRoadHotspotRepairV1 "
					+ "--validate <network> <plans> <schedule> <vehicles> <facilities> "
					+ "[materialization_validation.json]");
		}
		Scenario candidate = load(requireFile(args[1]), requireFile(args[2]),
				requireFile(args[3]), requireFile(args[4]), requireFile(args[5]));
		Validation validation = validate(candidate);
		if (args.length == 7) recordValidation(Path.of(args[6]), validation);
		System.out.println("Validated materialized road-hotspot candidate: "
				+ validation.toJson());
	}

	private static Scenario load(Path network, Path plans, Path schedule, Path vehicles,
			Path facilities) {
		Config config = ConfigUtils.createConfig();
		config.global().setCoordinateSystem("EPSG:32650");
		config.network().setInputFile(network.toString());
		config.plans().setInputFile(plans.toString());
		config.plans().setInputCRS("EPSG:32650");
		config.facilities().setInputFile(facilities.toString());
		config.transit().setUseTransit(true);
		config.transit().setTransitScheduleFile(schedule.toString());
		config.transit().setVehiclesFile(vehicles.toString());
		return ScenarioUtils.loadScenario(config);
	}

	private static Path requireFile(String value) {
		Path path = Path.of(value).toAbsolutePath().normalize();
		if (!Files.isRegularFile(path)) throw new IllegalArgumentException("Missing input " + path);
		return path;
	}

	private static Validation validate(Scenario scenario) {
		long forbiddenPopulationRoutes = 0;
		long missingPopulationLinks = 0;
		long nonContiguousPopulationRoutes = 0;
		long forbiddenActivityReferences = 0;
		for (var person : scenario.getPopulation().getPersons().values()) {
			for (var plan : person.getPlans()) {
				for (PlanElement element : plan.getPlanElements()) {
					if (element instanceof Activity activity
							&& HongKongRoadHotspotRepairV1.RESTRICTED_LINK_IDS.contains(activity.getLinkId())) {
						forbiddenActivityReferences++;
					}
					if (!(element instanceof Leg leg) || !(leg.getRoute() instanceof NetworkRoute route)) continue;
					List<org.matsim.api.core.v01.Id<Link>> links = fullRoute(route);
					if (links.stream().anyMatch(HongKongRoadHotspotRepairV1.RESTRICTED_LINK_IDS::contains)) {
						forbiddenPopulationRoutes++;
					}
					if (links.stream().anyMatch(id -> !scenario.getNetwork().getLinks().containsKey(id))) {
						missingPopulationLinks++;
					} else if (!contiguous(links, scenario)) {
						nonContiguousPopulationRoutes++;
					}
				}
			}
		}
		long forbiddenTransitRoutes = 0;
		long missingTransitLinks = 0;
		long nonContiguousTransitRoutes = 0;
		long missingStopLinks = 0;
		long outOfOrderStops = 0;
		for (var facility : scenario.getTransitSchedule().getFacilities().values()) {
			if (!scenario.getNetwork().getLinks().containsKey(facility.getLinkId())) missingStopLinks++;
		}
		for (var line : scenario.getTransitSchedule().getTransitLines().values()) {
			for (var transitRoute : line.getRoutes().values()) {
				List<org.matsim.api.core.v01.Id<Link>> links = fullRoute(transitRoute.getRoute());
				if (links.stream().anyMatch(HongKongRoadHotspotRepairV1.RESTRICTED_LINK_IDS::contains)) {
					forbiddenTransitRoutes++;
				}
				if (links.stream().anyMatch(id -> !scenario.getNetwork().getLinks().containsKey(id))) {
					missingTransitLinks++;
				} else if (!contiguous(links, scenario)) {
					nonContiguousTransitRoutes++;
				}
				int cursor = 0;
				for (var stop : transitRoute.getStops()) {
					while (cursor < links.size()
							&& !links.get(cursor).equals(stop.getStopFacility().getLinkId())) cursor++;
					if (cursor == links.size()) { outOfOrderStops++; break; }
				}
			}
		}
		long restrictedLinksAllowingMotor = HongKongRoadHotspotRepairV1.RESTRICTED_LINK_IDS.stream()
				.map(scenario.getNetwork().getLinks()::get)
				.filter(link -> link.getAllowedModes().stream().anyMatch(
						SetHolder.THROUGH_MOTOR_MODES::contains)).count();
		long restrictedLinksNotWalkOnly = HongKongRoadHotspotRepairV1.RESTRICTED_LINK_IDS.stream()
				.map(scenario.getNetwork().getLinks()::get)
				.filter(link -> !link.getAllowedModes().equals(java.util.Set.of("walk"))).count();
		Validation result = new Validation(forbiddenPopulationRoutes, missingPopulationLinks,
				nonContiguousPopulationRoutes, forbiddenActivityReferences, forbiddenTransitRoutes,
				missingTransitLinks, nonContiguousTransitRoutes, missingStopLinks, outOfOrderStops,
				restrictedLinksAllowingMotor, restrictedLinksNotWalkOnly);
		if (!result.valid()) throw new IllegalStateException("Candidate validation failed: " + result);
		return result;
	}

	private static List<org.matsim.api.core.v01.Id<Link>> fullRoute(NetworkRoute route) {
		List<org.matsim.api.core.v01.Id<Link>> result = new ArrayList<>();
		if (route == null || route.getStartLinkId() == null || route.getEndLinkId() == null) return result;
		result.add(route.getStartLinkId());
		result.addAll(route.getLinkIds());
		if (!route.getEndLinkId().equals(result.getLast())) result.add(route.getEndLinkId());
		return result;
	}

	private static boolean contiguous(List<org.matsim.api.core.v01.Id<Link>> ids, Scenario scenario) {
		for (int i = 1; i < ids.size(); i++) {
			Link previous = scenario.getNetwork().getLinks().get(ids.get(i - 1));
			Link current = scenario.getNetwork().getLinks().get(ids.get(i));
			if (!previous.getToNode().getId().equals(current.getFromNode().getId())) return false;
		}
		return true;
	}

	private static void recordValidation(Path path, Validation validation) throws IOException {
		Path resolved = path.toAbsolutePath().normalize();
		if (!Files.isRegularFile(resolved)) {
			throw new IllegalArgumentException("Missing validation manifest " + resolved);
		}
		String json = Files.readString(resolved, StandardCharsets.UTF_8);
		if (!json.contains("\"status\": \"bounded_rewrite_complete_pending_java_validation\"")
				|| !json.contains("\"java_reference_validation\": \"pending\"")) {
			throw new IllegalArgumentException(
					"Validation manifest is not in the pending Java-validation state: " + resolved);
		}
		json = json.replace(
				"\"status\": \"bounded_rewrite_complete_pending_java_validation\"",
				"\"status\": \"validated\"");
		json = json.replace(
				"\"java_reference_validation\": \"pending\"",
				"\"java_reference_validation\": \"passed\"");
		Files.writeString(resolved, json, StandardCharsets.UTF_8,
				StandardOpenOption.TRUNCATE_EXISTING);
	}

	private record Validation(long forbiddenPopulationRoutes, long missingPopulationLinks,
			long nonContiguousPopulationRoutes, long forbiddenActivityReferences,
			long forbiddenTransitRoutes, long missingTransitLinks, long nonContiguousTransitRoutes,
			long missingStopLinks, long outOfOrderStops, long restrictedLinksAllowingMotor,
			long restrictedLinksNotWalkOnly) {
		boolean valid() {
			return forbiddenPopulationRoutes == 0 && missingPopulationLinks == 0
					&& nonContiguousPopulationRoutes == 0 && forbiddenActivityReferences == 0
					&& forbiddenTransitRoutes == 0 && missingTransitLinks == 0
					&& nonContiguousTransitRoutes == 0 && missingStopLinks == 0
					&& outOfOrderStops == 0 && restrictedLinksAllowingMotor == 0
					&& restrictedLinksNotWalkOnly == 0;
		}
		String toJson() {
			return "{\"forbidden_population_routes\": " + forbiddenPopulationRoutes
					+ ", \"missing_population_links\": " + missingPopulationLinks
					+ ", \"non_contiguous_population_routes\": " + nonContiguousPopulationRoutes
					+ ", \"forbidden_activity_references\": " + forbiddenActivityReferences
					+ ", \"forbidden_transit_routes\": " + forbiddenTransitRoutes
					+ ", \"missing_transit_links\": " + missingTransitLinks
					+ ", \"non_contiguous_transit_routes\": " + nonContiguousTransitRoutes
					+ ", \"missing_stop_links\": " + missingStopLinks
					+ ", \"out_of_order_stops\": " + outOfOrderStops
					+ ", \"restricted_links_allowing_motor\": " + restrictedLinksAllowingMotor
					+ ", \"restricted_links_not_walk_only\": " + restrictedLinksNotWalkOnly + "}";
		}
	}

	private static final class SetHolder {
		private static final java.util.Set<String> THROUGH_MOTOR_MODES = java.util.Set.of(
				"car", "ride", "pt", "bus", "gmb", "school_bus", "school_bus_vehicle");
	}
}
