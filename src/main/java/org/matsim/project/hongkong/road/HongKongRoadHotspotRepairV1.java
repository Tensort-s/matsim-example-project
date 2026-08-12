package org.matsim.project.hongkong.road;

import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.network.Network;
import org.matsim.api.core.v01.network.Node;
import org.matsim.api.core.v01.population.Activity;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.core.population.routes.NetworkRoute;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.PriorityQueue;
import java.util.Set;

/**
	 * Bounded repair for two Hong Kong service-road shortcuts found by the
 * no-signal run57 hotspot audit.
 *
 * <p>The source audit established that these links are OSM service roads with
 * through-motor restrictions, while the MATSim network admitted normal Car and
 * road-PT traffic. This repair removes motor modes and substitutes a shortest
 * free-flow-time Car path between the same endpoint nodes in existing
 * population and transit {@link NetworkRoute}s. It is deliberately not a
 * general replanning strategy.</p>
 */
public final class HongKongRoadHotspotRepairV1 {

	public static final Set<Id<Link>> RESTRICTED_LINK_IDS = Set.of(
			Id.createLinkId("road_261323_0_f"),
			Id.createLinkId("road_261308_0_f")
	);
	private static final Set<String> THROUGH_MOTOR_MODES = Set.of(
			"car", "ride", "pt", "bus", "gmb", "school_bus", "school_bus_vehicle"
	);

	private HongKongRoadHotspotRepairV1() { }

	public record RepairStats(
			Map<Id<Link>, List<Id<Link>>> replacementPaths,
			int repairedPopulationRoutes,
			int repairedTransitRoutes,
			int remappedTransitStops,
			int restrictedLinks,
			int activityReferences) { }

	public static RepairStats apply(Scenario scenario) {
		Network network = scenario.getNetwork();
		for (Id<Link> linkId : RESTRICTED_LINK_IDS) {
			if (!network.getLinks().containsKey(linkId)) {
				throw new IllegalArgumentException("Missing audited restricted link " + linkId);
			}
		}

		Map<Id<Link>, List<Id<Link>>> replacements = new LinkedHashMap<>();
		for (Id<Link> linkId : RESTRICTED_LINK_IDS.stream()
				.sorted(Comparator.comparing(Id::toString)).toList()) {
			Link link = network.getLinks().get(linkId);
			List<Id<Link>> path = shortestPath(
					network, link.getFromNode(), link.getToNode(), RESTRICTED_LINK_IDS, "car");
			if (path.isEmpty()) {
				throw new IllegalStateException("No legal Car replacement path for " + linkId);
			}
			replacements.put(linkId, List.copyOf(path));
		}

		Id<Link> tunnelService = Id.createLinkId("road_261323_0_f");
		Id<Link> tunnelParallel = Id.createLinkId("road_105124_0_f");
		if (!replacements.get(tunnelService).equals(List.of(tunnelParallel))) {
			throw new IllegalStateException(
					"Expected the audited exact Cross-Harbour-Tunnel parallel replacement; found "
							+ replacements.get(tunnelService));
		}
		int activityReferences = 0;
		int ambiguousActivityReferences = 0;
		for (var person : scenario.getPopulation().getPersons().values()) {
			for (Plan plan : person.getPlans()) {
				for (PlanElement element : plan.getPlanElements()) {
					if (element instanceof Activity activity
							&& RESTRICTED_LINK_IDS.contains(activity.getLinkId())) {
						activityReferences++;
						if (tunnelService.equals(activity.getLinkId())) {
							activity.setLinkId(tunnelParallel);
						} else {
							ambiguousActivityReferences++;
						}
					}
				}
			}
		}
		if (ambiguousActivityReferences > 0) {
			throw new IllegalStateException(
					"Refusing ambiguous Tate's-Cairn service-road activity remapping; references="
							+ ambiguousActivityReferences);
		}
		int remappedTransitStops = 0;
		for (var facility : scenario.getTransitSchedule().getFacilities().values()) {
			List<Id<Link>> path = replacements.get(facility.getLinkId());
			if (path == null) continue;
			facility.setLinkId(nearestLink(path, facility.getCoord(), network));
			remappedTransitStops++;
		}

		int populationRoutes = 0;
		for (var person : scenario.getPopulation().getPersons().values()) {
			for (Plan plan : person.getPlans()) {
				for (PlanElement element : plan.getPlanElements()) {
					if (element instanceof Leg leg && leg.getRoute() instanceof NetworkRoute route
							&& repairRoute(route, replacements, network)) {
						populationRoutes++;
					}
				}
			}
		}

		int transitRoutes = 0;
		Map<String, Map<Id<Link>, List<Id<Link>>>> transitReplacements = new HashMap<>();
		for (var line : scenario.getTransitSchedule().getTransitLines().values()) {
			for (var transitRoute : line.getRoutes().values()) {
				NetworkRoute route = transitRoute.getRoute();
				if (!containsAny(route, RESTRICTED_LINK_IDS)) continue;
				String mode = transitRoute.getTransportMode();
				Map<Id<Link>, List<Id<Link>>> modePaths = transitReplacements.computeIfAbsent(
						mode, ignored -> replacementPaths(network, mode));
				if (repairRoute(route, modePaths, network)) {
					validateTransitStopOrder(transitRoute, route);
					transitRoutes++;
				}
			}
		}

		for (Id<Link> linkId : RESTRICTED_LINK_IDS) {
			Link link = network.getLinks().get(linkId);
			Set<String> modes = new LinkedHashSet<>(link.getAllowedModes());
			modes.removeAll(THROUGH_MOTOR_MODES);
			if (modes.isEmpty()) modes.add("restricted_access");
			link.setAllowedModes(modes);
		}
		return new RepairStats(
				Map.copyOf(replacements), populationRoutes, transitRoutes, remappedTransitStops,
				RESTRICTED_LINK_IDS.size(), activityReferences);
	}

	private static Id<Link> nearestLink(
			List<Id<Link>> linkIds, org.matsim.api.core.v01.Coord point, Network network) {
		return linkIds.stream().min(Comparator.comparingDouble(linkId -> {
			Link link = network.getLinks().get(linkId);
			var from = link.getFromNode().getCoord();
			var to = link.getToNode().getCoord();
			double dx = to.getX() - from.getX();
			double dy = to.getY() - from.getY();
			double lengthSquared = dx * dx + dy * dy;
			double fraction = lengthSquared == 0 ? 0 : (
					(point.getX() - from.getX()) * dx + (point.getY() - from.getY()) * dy
			) / lengthSquared;
			fraction = Math.max(0, Math.min(1, fraction));
			double x = from.getX() + fraction * dx;
			double y = from.getY() + fraction * dy;
			double pointDx = point.getX() - x;
			double pointDy = point.getY() - y;
			return pointDx * pointDx + pointDy * pointDy;
		})).orElseThrow();
	}

	private static void validateTransitStopOrder(
			org.matsim.pt.transitSchedule.api.TransitRoute transitRoute, NetworkRoute route) {
		List<Id<Link>> links = new ArrayList<>();
		links.add(route.getStartLinkId());
		links.addAll(route.getLinkIds());
		if (!route.getEndLinkId().equals(links.getLast())) links.add(route.getEndLinkId());
		int cursor = 0;
		for (var stop : transitRoute.getStops()) {
			Id<Link> stopLink = stop.getStopFacility().getLinkId();
			while (cursor < links.size() && !links.get(cursor).equals(stopLink)) cursor++;
			if (cursor == links.size()) {
				throw new IllegalStateException(
						"Repaired transit route " + transitRoute.getId()
								+ " omits or passes stop out of order: " + stop.getStopFacility().getId()
								+ " on " + stopLink);
			}
		}
	}

	private static Map<Id<Link>, List<Id<Link>>> replacementPaths(Network network, String mode) {
		Map<Id<Link>, List<Id<Link>>> paths = new LinkedHashMap<>();
		for (Id<Link> linkId : RESTRICTED_LINK_IDS.stream()
				.sorted(Comparator.comparing(Id::toString)).toList()) {
			Link link = network.getLinks().get(linkId);
			List<Id<Link>> path = shortestPath(
					network, link.getFromNode(), link.getToNode(), RESTRICTED_LINK_IDS, mode);
			if (path.isEmpty()) {
				throw new IllegalStateException(
						"No legal " + mode + " transit replacement path for " + linkId);
			}
			paths.put(linkId, List.copyOf(path));
		}
		return Map.copyOf(paths);
	}

	private static boolean containsAny(NetworkRoute route, Set<Id<Link>> candidates) {
		return route != null && (candidates.contains(route.getStartLinkId())
				|| route.getLinkIds().stream().anyMatch(candidates::contains)
				|| candidates.contains(route.getEndLinkId()));
	}

	static boolean repairRoute(
			NetworkRoute route,
			Map<Id<Link>, List<Id<Link>>> replacements,
			Network network) {
		if (route == null || route.getStartLinkId() == null || route.getEndLinkId() == null) {
			return false;
		}
		List<Id<Link>> original = new ArrayList<>();
		original.add(route.getStartLinkId());
		original.addAll(route.getLinkIds());
		if (!route.getEndLinkId().equals(original.getLast())) original.add(route.getEndLinkId());
		if (original.stream().noneMatch(replacements::containsKey)) return false;

		List<Id<Link>> repaired = new ArrayList<>();
		for (Id<Link> linkId : original) {
			List<Id<Link>> replacement = replacements.get(linkId);
			if (replacement == null) {
				appendWithoutDuplicate(repaired, linkId);
			} else {
				for (Id<Link> replacementId : replacement) {
					appendWithoutDuplicate(repaired, replacementId);
				}
			}
		}
		validateContiguous(repaired, network);
		route.setLinkIds(
				repaired.getFirst(),
				repaired.size() <= 2
						? List.of()
						: new ArrayList<>(repaired.subList(1, repaired.size() - 1)),
				repaired.getLast());
		double distance = repaired.stream()
				.map(network.getLinks()::get)
				.mapToDouble(Link::getLength)
				.sum();
		route.setDistance(distance);
		return true;
	}

	private static void appendWithoutDuplicate(List<Id<Link>> links, Id<Link> linkId) {
		if (links.isEmpty() || !links.getLast().equals(linkId)) links.add(linkId);
	}

	private static void validateContiguous(List<Id<Link>> linkIds, Network network) {
		if (linkIds.isEmpty()) throw new IllegalStateException("Repaired route is empty");
		for (int index = 1; index < linkIds.size(); index++) {
			Link previous = network.getLinks().get(linkIds.get(index - 1));
			Link current = network.getLinks().get(linkIds.get(index));
			if (previous == null || current == null
					|| !previous.getToNode().getId().equals(current.getFromNode().getId())) {
				throw new IllegalStateException(
						"Non-contiguous repaired route at " + linkIds.get(index - 1)
								+ " -> " + linkIds.get(index));
			}
		}
	}

	private record NodeCost(Node node, double cost) { }

	private static List<Id<Link>> shortestPath(
			Network network, Node start, Node destination, Set<Id<Link>> excluded, String mode) {
		Map<Id<Node>, Double> distance = new HashMap<>();
		Map<Id<Node>, Link> previous = new HashMap<>();
		PriorityQueue<NodeCost> queue = new PriorityQueue<>(Comparator.comparingDouble(NodeCost::cost));
		distance.put(start.getId(), 0.0);
		queue.add(new NodeCost(start, 0.0));
		while (!queue.isEmpty()) {
			NodeCost current = queue.poll();
			if (current.cost() != distance.getOrDefault(current.node().getId(), Double.POSITIVE_INFINITY)) {
				continue;
			}
			if (current.node().getId().equals(destination.getId())) break;
			for (Link link : current.node().getOutLinks().values()) {
				if (excluded.contains(link.getId()) || !link.getAllowedModes().contains(mode)) continue;
				double nextCost = current.cost() + link.getLength() / link.getFreespeed();
				Id<Node> nextId = link.getToNode().getId();
				if (nextCost >= distance.getOrDefault(nextId, Double.POSITIVE_INFINITY)) continue;
				distance.put(nextId, nextCost);
				previous.put(nextId, link);
				queue.add(new NodeCost(link.getToNode(), nextCost));
			}
		}
		if (!distance.containsKey(destination.getId())) return List.of();
		List<Id<Link>> reverse = new ArrayList<>();
		Node cursor = destination;
		while (!cursor.getId().equals(start.getId())) {
			Link link = previous.get(cursor.getId());
			if (link == null) return List.of();
			reverse.add(link.getId());
			cursor = link.getFromNode();
		}
		java.util.Collections.reverse(reverse);
		return reverse;
	}
}
