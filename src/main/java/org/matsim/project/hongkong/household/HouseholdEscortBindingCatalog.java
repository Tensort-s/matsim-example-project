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

/** Immutable, scenario-resolved bindings for the 139-pair physical pilot. */
public final class HouseholdEscortBindingCatalog {

	public static final int EXPECTED_PASSENGERS = 139;
	public static final int EXPECTED_BINDINGS = 278;

	public record Binding(
			Id<Person> passengerId,
			int passengerLegIndex,
			Leg passengerLeg,
			Id<Person> driverId,
			int driverLegIndex,
			Leg driverLeg,
			Id<Vehicle> vehicleId,
			Id<Link> driverDestinationLinkId,
			double driverPlannedDepartureTimeSeconds,
			double originAccessGapMeters,
			double destinationEgressGapMeters) {
	}

	private final List<Binding> bindings;
	private final Map<String, Binding> passengerLegBindings;

	private HouseholdEscortBindingCatalog(List<Binding> bindings) {
		this.bindings = List.copyOf(bindings);
		this.passengerLegBindings = new LinkedHashMap<>();
		for (Binding binding : bindings) {
			if (passengerLegBindings.put(key(binding.passengerId(), binding.passengerLegIndex()), binding) != null) {
				throw new IllegalArgumentException("Duplicate passenger leg binding: "
						+ binding.passengerId() + "/" + binding.passengerLegIndex());
			}
		}
	}

	public static HouseholdEscortBindingCatalog load(Path csv, Scenario scenario) {
		if (!Files.isRegularFile(csv)) {
			throw new IllegalArgumentException("Escort binding CSV is missing: " + csv);
		}
		List<Map<String, String>> rows = readCsv(csv);
		List<Binding> bindings = new ArrayList<>();
		Map<Id<Person>, Integer> passengerCounts = new HashMap<>();
		Map<Id<Person>, Id<Person>> passengerDrivers = new HashMap<>();
		Set<String> uniqueKeys = new HashSet<>();
		for (Map<String, String> row : rows) {
			Id<Person> passengerId = Id.createPersonId(required(row, "passenger_person_id"));
			Id<Person> driverId = Id.createPersonId(required(row, "driver_person_id"));
			int passengerLegIndex = Integer.parseInt(required(row, "passenger_leg_index"));
			int driverLegIndex = Integer.parseInt(required(row, "driver_leg_index"));
			Id<Vehicle> vehicleId = Id.createVehicleId(required(row, "vehicle_id"));
			if (passengerId.equals(driverId)) {
				throw new IllegalArgumentException("Passenger cannot drive their own bound leg: " + passengerId);
			}
			String key = passengerId + "/" + passengerLegIndex;
			if (!uniqueKeys.add(key)) {
				throw new IllegalArgumentException("Duplicate binding key: " + key);
			}

			Person passenger = requiredPerson(scenario, passengerId);
			Person driver = requiredPerson(scenario, driverId);
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
			Id<Person> previousDriver = passengerDrivers.putIfAbsent(passengerId, driverId);
			if (previousDriver != null && !previousDriver.equals(driverId)) {
				throw new IllegalArgumentException("Passenger has different outbound and return drivers: " + passengerId);
			}
			passengerCounts.merge(passengerId, 1, Integer::sum);
			bindings.add(new Binding(
					passengerId,
					passengerLegIndex,
					passengerLeg,
					driverId,
					driverLegIndex,
					driverLeg,
					vehicleId,
					route.getEndLinkId(),
					Double.parseDouble(required(row, "driver_planned_departure_time_s")),
					Double.parseDouble(required(row, "origin_access_gap_m")),
					Double.parseDouble(required(row, "destination_egress_gap_m"))));
		}
		if (bindings.size() != EXPECTED_BINDINGS
				|| passengerCounts.size() != EXPECTED_PASSENGERS
				|| passengerCounts.values().stream().anyMatch(count -> count != 2)) {
			throw new IllegalArgumentException(
					"Physical pilot requires exactly 139 passengers and two legs each; found passengers="
							+ passengerCounts.size() + ", bindings=" + bindings.size());
		}
		return new HouseholdEscortBindingCatalog(bindings);
	}

	public Binding bindingForPassengerLeg(Id<Person> passengerId, int legIndex) {
		return passengerLegBindings.get(key(passengerId, legIndex));
	}

	public List<Binding> bindings() {
		return bindings;
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

	private static String key(Id<Person> passengerId, int legIndex) {
		return passengerId + "/" + legIndex;
	}
}
