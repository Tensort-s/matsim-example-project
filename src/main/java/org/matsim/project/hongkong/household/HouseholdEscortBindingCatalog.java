package org.matsim.project.hongkong.household;

import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.Leg;
import org.matsim.api.core.v01.population.Person;
import org.matsim.api.core.v01.population.Plan;
import org.matsim.api.core.v01.population.PlanElement;
import org.matsim.core.population.routes.NetworkRoute;
import org.matsim.vehicles.Vehicle;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Immutable, scenario-resolved candidate bindings with mutable active selections. */
public final class HouseholdEscortBindingCatalog {
	public static final String BINDING_KEY_ATTRIBUTE = "hkHouseholdEscortBindingKey";

	public record Binding(
			String candidateGroupId,
			String householdId,
			String candidateSource,
			boolean newCandidate,
			Id<Person> passengerId,
			int passengerLegIndex,
			Leg passengerLeg,
			Id<Person> driverId,
			int driverLegIndex,
			Leg driverLeg,
			NetworkRoute plannedDriverRoute,
			Id<Vehicle> vehicleId,
			Id<Link> passengerPickupLinkId,
			Id<Link> passengerDropoffLinkId,
			Id<Link> driverDestinationLinkId,
			double passengerPlannedDepartureTimeSeconds,
			double driverPlannedDepartureTimeSeconds,
			double originAccessGapMeters,
			double destinationEgressGapMeters) {
	}

	private final List<Binding> bindings;
	private final Map<String, Binding> passengerLegBindings;
	private final Map<String, List<Binding>> candidateGroups;
	private final Set<String> activeBindingKeys;

	private HouseholdEscortBindingCatalog(List<Binding> bindings) {
		this.bindings = new ArrayList<>();
		this.passengerLegBindings = new LinkedHashMap<>();
		this.candidateGroups = new LinkedHashMap<>();
		this.activeBindingKeys = new HashSet<>();
		register(bindings, true);
	}

	public static HouseholdEscortBindingCatalog empty() {
		return new HouseholdEscortBindingCatalog(List.of());
	}

	public synchronized void replaceWithActiveBindings(List<Binding> replacements) {
		bindings.clear();
		passengerLegBindings.clear();
		candidateGroups.clear();
		activeBindingKeys.clear();
		register(replacements, true);
	}

	/**
	 * Restores the selected joint driver's exact waypoint route after MATSim's
	 * stock per-iteration route preparation. The stock preparer may replace a
	 * valid detour route with a direct origin-destination route because pickup
	 * and drop-off waypoints are not activities in the driver's plan.
	 */
	public synchronized int restoreSelectedDriverWaypointRoutes() {
		int restored = 0;
		Set<String> restoredDriverLegs = new HashSet<>();
		for (Binding binding : bindings) {
			if (!isActive(binding)) continue;
			String driverLegKey = key(binding.driverId(), binding.driverLegIndex());
			if (!restoredDriverLegs.add(driverLegKey)) {
				throw new IllegalStateException("Multiple active passengers share one driver leg: "
						+ driverLegKey);
			}
			NetworkRoute planned = binding.plannedDriverRoute();
			if (!containsLink(planned, binding.passengerPickupLinkId())
					|| !containsLink(planned, binding.passengerDropoffLinkId())) {
				throw new IllegalStateException("Stored joint driver route omits passenger waypoint: "
						+ bindingKey(binding));
			}
			NetworkRoute restoredRoute = snapshotNetworkRoute(planned);
			binding.driverLeg().setRoute(restoredRoute);
			binding.driverLeg().setRoutingMode("car");
			if (restoredRoute.getTravelTime().isDefined()) {
				binding.driverLeg().setTravelTime(restoredRoute.getTravelTime().seconds());
			}
			restored++;
		}
		return restored;
	}

	private void register(List<Binding> additions, boolean active) {
		Map<String, List<Binding>> groups = new LinkedHashMap<>();
		for (var entry : candidateGroups.entrySet()) {
			groups.put(entry.getKey(), new ArrayList<>(entry.getValue()));
		}
		for (Binding binding : additions) {
			String key = key(binding.passengerId(), binding.passengerLegIndex());
			if (passengerLegBindings.put(key, binding) != null) {
				throw new IllegalArgumentException("Duplicate passenger leg binding: "
						+ binding.passengerId() + "/" + binding.passengerLegIndex());
			}
			groups.computeIfAbsent(binding.candidateGroupId(), ignored -> new ArrayList<>())
					.add(binding);
			if (active) activeBindingKeys.add(key);
			this.bindings.add(binding);
		}
		this.candidateGroups.clear();
		for (var entry : groups.entrySet()) {
			this.candidateGroups.put(entry.getKey(), List.copyOf(entry.getValue()));
		}
	}

	public static HouseholdEscortBindingCatalog load(Path csv, Scenario scenario) {
		if (!Files.isRegularFile(csv)) {
			throw new IllegalArgumentException("Escort binding CSV is missing: " + csv);
		}
		List<Map<String, String>> rows = readCsv(csv);
		List<Binding> bindings = new ArrayList<>();
		Map<Id<Person>, Integer> passengerCounts = new HashMap<>();
		Set<String> uniqueKeys = new HashSet<>();
		for (Map<String, String> row : rows) {
			Id<Person> passengerId = Id.createPersonId(required(row, "passenger_person_id"));
			Id<Person> driverId = Id.createPersonId(required(row, "driver_person_id"));
			int passengerLegIndex = Integer.parseInt(required(row, "passenger_leg_index"));
			int driverLegIndex = Integer.parseInt(required(row, "driver_leg_index"));
			Id<Vehicle> vehicleId = Id.createVehicleId(required(row, "vehicle_id"));
			Id<Link> pickupLinkId = Id.createLinkId(required(row, "passenger_pickup_link"));
			Id<Link> dropoffLinkId = Id.createLinkId(required(row, "passenger_dropoff_link"));
			if (passengerId.equals(driverId)) {
				throw new IllegalArgumentException("Passenger cannot drive their own bound leg: " + passengerId);
			}
			String key = passengerId + "/" + passengerLegIndex;
			if (!uniqueKeys.add(key)) {
				throw new IllegalArgumentException("Duplicate binding key: " + key);
			}

			Person passenger = requiredPerson(scenario, passengerId);
			Person driver = requiredPerson(scenario, driverId);
			String householdId = optional(row, "household_id",
					String.valueOf(passenger.getAttributes().getAttribute("householdId")));
			if (householdId.isBlank() || "null".equals(householdId)) {
				throw new IllegalArgumentException("Passenger lacks householdId: " + passengerId);
			}
			String candidateGroupId = optional(row, "candidate_group_id", passengerId.toString());
			String candidateSource = optional(row, "candidate_source", "legacy_complete_direct_pair");
			boolean newCandidate = Boolean.parseBoolean(optional(row, "new_candidate", "false"));
			Leg passengerLeg = selectedLeg(passenger, passengerLegIndex);
			Leg driverLeg = selectedLeg(driver, driverLegIndex);
			if (!"car_passenger".equals(passengerLeg.getMode())) {
				throw new IllegalArgumentException("Bound passenger leg is not car_passenger: " + key);
			}
			if (!"car".equals(driverLeg.getMode())) {
				throw new IllegalArgumentException("Bound driver leg is not car: "
						+ driverId + "/" + driverLegIndex);
			}
			if (!(driverLeg.getRoute() instanceof NetworkRoute route)
					|| !vehicleId.equals(route.getVehicleId())) {
				throw new IllegalArgumentException("Bound driver route vehicle mismatch: "
						+ driverId + "/" + driverLegIndex);
			}
			Vehicle vehicle = scenario.getVehicles().getVehicles().get(vehicleId);
			if (vehicle == null || !"private_car".equals(vehicle.getType().getId().toString())) {
				throw new IllegalArgumentException("Bound vehicle is not a private_car: " + vehicleId);
			}
			Object assigned = driver.getAttributes().getAttribute("assignedVehicleId");
			if (assigned == null || !vehicleId.toString().equals(assigned.toString())) {
				throw new IllegalArgumentException("Driver assignedVehicleId mismatch: " + driverId);
			}
			if (route.getEndLinkId() == null) {
				throw new IllegalArgumentException("Bound driver route lacks an end link: " + driverId);
			}
			if (!scenario.getNetwork().getLinks().containsKey(pickupLinkId)
					|| !scenario.getNetwork().getLinks().containsKey(dropoffLinkId)) {
				throw new IllegalArgumentException("Passenger waypoint is missing from the network: " + key);
			}
			passengerCounts.merge(passengerId, 1, Integer::sum);
			bindings.add(new Binding(
					candidateGroupId,
					householdId,
					candidateSource,
					newCandidate,
					passengerId,
					passengerLegIndex,
					passengerLeg,
					driverId,
					driverLegIndex,
					driverLeg,
					snapshotNetworkRoute(route),
					vehicleId,
					pickupLinkId,
					dropoffLinkId,
					route.getEndLinkId(),
					Double.parseDouble(required(row, "passenger_planned_departure_time_s")),
					Double.parseDouble(required(row, "driver_planned_departure_time_s")),
					Double.parseDouble(required(row, "origin_access_gap_m")),
					Double.parseDouble(required(row, "destination_egress_gap_m"))));
		}
		if (bindings.isEmpty() || passengerCounts.values().stream().anyMatch(count -> count < 1 || count > 2)) {
			throw new IllegalArgumentException("Household joint-candidate registry requires one or two "
					+ "candidate legs per passenger; found passengers=" + passengerCounts.size()
					+ ", bindings=" + bindings.size());
		}
		for (var entry : bindings.stream().collect(java.util.stream.Collectors.groupingBy(
				Binding::candidateGroupId)).entrySet()) {
			Set<Id<Person>> passengers = entry.getValue().stream()
					.map(Binding::passengerId).collect(java.util.stream.Collectors.toSet());
			Set<String> households = entry.getValue().stream()
					.map(Binding::householdId).collect(java.util.stream.Collectors.toSet());
			if (passengers.size() != 1 || households.size() != 1) {
				throw new IllegalArgumentException("Candidate group must contain one passenger and household: "
						+ entry.getKey());
			}
		}
		return new HouseholdEscortBindingCatalog(bindings);
	}

	public static NetworkRoute snapshotNetworkRoute(NetworkRoute source) {
		NetworkRoute copy = org.matsim.core.population.routes.RouteUtils.createLinkNetworkRouteImpl(
				source.getStartLinkId(), new ArrayList<>(source.getLinkIds()), source.getEndLinkId());
		copy.setVehicleId(source.getVehicleId());
		copy.setDistance(source.getDistance());
		if (source.getTravelTime().isDefined()) {
			copy.setTravelTime(source.getTravelTime().seconds());
		}
		return copy;
	}

	private static boolean containsLink(NetworkRoute route, Id<Link> linkId) {
		return linkId.equals(route.getStartLinkId())
				|| route.getLinkIds().contains(linkId)
				|| linkId.equals(route.getEndLinkId());
	}

	public Binding bindingForPassengerLeg(Id<Person> passengerId, int legIndex) {
		return passengerLegBindings.get(key(passengerId, legIndex));
	}

	public synchronized Binding activeBindingForPassengerLeg(Id<Person> passengerId, int legIndex) {
		String key = key(passengerId, legIndex);
		return activeBindingKeys.contains(key) ? passengerLegBindings.get(key) : null;
	}

	public synchronized Binding activeBindingForKey(String bindingKey) {
		return activeBindingKeys.contains(bindingKey) ? passengerLegBindings.get(bindingKey) : null;
	}

	public synchronized void setCandidateGroupBound(String candidateGroupId, boolean bound) {
		List<Binding> group = candidateGroups.get(candidateGroupId);
		if (group == null || group.isEmpty()) {
			throw new IllegalArgumentException("Unknown household candidate group " + candidateGroupId);
		}
		List<String> keys = group.stream()
				.map(binding -> key(binding.passengerId(), binding.passengerLegIndex()))
				.toList();
		if (bound) {
			activeBindingKeys.addAll(keys);
		} else {
			activeBindingKeys.removeAll(keys);
		}
	}

	public synchronized boolean isActive(Binding binding) {
		return activeBindingKeys.contains(key(binding.passengerId(), binding.passengerLegIndex()));
	}

	public synchronized int activeBindingCount() {
		return activeBindingKeys.size();
	}

	public List<Binding> bindings() {
		return List.copyOf(bindings);
	}

	public Map<String, List<Binding>> candidateGroups() {
		return java.util.Collections.unmodifiableMap(candidateGroups);
	}

	public static String bindingKey(Binding binding) {
		return key(binding.passengerId(), binding.passengerLegIndex());
	}

	private static Person requiredPerson(Scenario scenario, Id<Person> id) {
		Person person = scenario.getPopulation().getPersons().get(id);
		if (person == null) {
			throw new IllegalArgumentException("Binding references missing person: " + id);
		}
		return person;
	}

	private static Leg selectedLeg(Person person, int requestedIndex) {
		Plan selected = person.getSelectedPlan();
		if (selected == null) {
			throw new IllegalArgumentException("Person lacks a selected plan: " + person.getId());
		}
		int legIndex = 0;
		for (PlanElement element : selected.getPlanElements()) {
			if (element instanceof Leg leg) {
				if (legIndex == requestedIndex) {
					return leg;
				}
				legIndex++;
			}
		}
		throw new IllegalArgumentException("Missing selected-plan leg " + requestedIndex
				+ " for person " + person.getId());
	}

	private static List<Map<String, String>> readCsv(Path path) {
		try {
			List<String> lines = Files.readAllLines(path);
			if (lines.isEmpty()) {
				throw new IllegalArgumentException("Empty escort binding CSV: " + path);
			}
			String[] header = lines.getFirst().split(",", -1);
			List<Map<String, String>> rows = new ArrayList<>();
			for (int lineNumber = 2; lineNumber <= lines.size(); lineNumber++) {
				String line = lines.get(lineNumber - 1);
				if (line.isBlank()) {
					continue;
				}
				String[] values = line.split(",", -1);
				if (values.length != header.length) {
					throw new IllegalArgumentException("Unsupported quoted or malformed CSV at line " + lineNumber);
				}
				Map<String, String> row = new LinkedHashMap<>();
				for (int index = 0; index < header.length; index++) {
					row.put(header[index], values[index]);
				}
				rows.add(row);
			}
			return rows;
		} catch (IOException error) {
			throw new IllegalArgumentException("Cannot read escort binding CSV: " + path, error);
		}
	}

	private static String required(Map<String, String> row, String name) {
		String value = row.get(name);
		if (value == null || value.isBlank()) {
			throw new IllegalArgumentException("Missing escort binding field: " + name);
		}
		return value;
	}

	private static String optional(Map<String, String> row, String name, String fallback) {
		String value = row.get(name);
		return value == null || value.isBlank() ? fallback : value.trim();
	}

	private static String key(Id<Person> passengerId, int legIndex) {
		return passengerId + "/" + legIndex;
	}
}
