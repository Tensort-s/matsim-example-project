package org.matsim.project.hongkong.household;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.HashSet;
import java.util.Set;

/** Immutable all-car-household joint-plan candidate screen. */
public final class HouseholdJointPlanCandidateCatalog {

	public record Candidate(
			String candidateId,
			String householdId,
			String passengerPersonId,
			int passengerTripIndex,
			String passengerOriginalMode,
			String driverPersonId,
			int driverTripIndex,
			String driverOriginalMode,
			String vehicleId,
			boolean driverRequiresCarSwitch,
			double passengerDepartureTimeS,
			double driverDepartureTimeS,
			String passengerPickupLinkId,
			String passengerDropoffLinkId,
			String driverDestinationLinkId,
			double originAccessGapM,
			double destinationEgressGapM) {
	}

	private final List<Candidate> candidates;

	private HouseholdJointPlanCandidateCatalog(List<Candidate> candidates) {
		Set<String> ids = new HashSet<>();
		for (Candidate candidate : candidates) {
			if (!ids.add(candidate.candidateId())) {
				throw new IllegalArgumentException("Duplicate household joint candidate "
						+ candidate.candidateId());
			}
			if (candidate.passengerPersonId().equals(candidate.driverPersonId())) {
				throw new IllegalArgumentException("Joint candidate passenger cannot be the driver: "
						+ candidate.candidateId());
			}
			if ("school_bus".equals(candidate.passengerOriginalMode())
					|| "school_bus".equals(candidate.driverOriginalMode())) {
				throw new IllegalArgumentException("School bus is disabled for household joint innovation: "
						+ candidate.candidateId());
			}
		}
		this.candidates = List.copyOf(candidates);
	}

	static HouseholdJointPlanCandidateCatalog of(List<Candidate> candidates) {
		if (candidates.isEmpty()) throw new IllegalArgumentException("Candidate list is empty.");
		return new HouseholdJointPlanCandidateCatalog(candidates);
	}

	public static HouseholdJointPlanCandidateCatalog load(Path csv) {
		if (!Files.isRegularFile(csv)) {
			throw new IllegalArgumentException("Household joint-plan candidate CSV is missing: " + csv);
		}
		List<Map<String, String>> rows = readCsv(csv);
		List<Candidate> candidates = new ArrayList<>();
		for (Map<String, String> row : rows) {
			candidates.add(new Candidate(
					required(row, "candidate_id"),
					required(row, "household_id"),
					required(row, "passenger_person_id"),
					Integer.parseInt(required(row, "passenger_trip_index")),
					required(row, "passenger_original_mode"),
					required(row, "driver_person_id"),
					Integer.parseInt(required(row, "driver_trip_index")),
					required(row, "driver_original_mode"),
					required(row, "driver_vehicle_id"),
					Boolean.parseBoolean(required(row, "driver_requires_car_switch")),
					Double.parseDouble(required(row, "passenger_departure_time_s")),
					Double.parseDouble(required(row, "driver_departure_time_s")),
					required(row, "passenger_pickup_link"),
					required(row, "passenger_dropoff_link"),
					required(row, "driver_destination_link"),
					Double.parseDouble(required(row, "origin_gap_m")),
					Double.parseDouble(required(row, "destination_gap_m"))));
		}
		if (candidates.isEmpty()) {
			throw new IllegalArgumentException("Household joint-plan candidate CSV is empty: " + csv);
		}
		return new HouseholdJointPlanCandidateCatalog(candidates);
	}

	public List<Candidate> candidates() {
		return candidates;
	}

	private static List<Map<String, String>> readCsv(Path path) {
		try {
			List<String> lines = Files.readAllLines(path);
			if (lines.isEmpty()) throw new IllegalArgumentException("Empty CSV: " + path);
			String[] header = lines.getFirst().split(",", -1);
			List<Map<String, String>> rows = new ArrayList<>();
			for (int lineNumber = 2; lineNumber <= lines.size(); lineNumber++) {
				String line = lines.get(lineNumber - 1);
				if (line.isBlank()) continue;
				String[] values = line.split(",", -1);
				if (values.length != header.length) {
					throw new IllegalArgumentException("Malformed CSV line " + lineNumber + " in " + path);
				}
				Map<String, String> row = new LinkedHashMap<>();
				for (int index = 0; index < header.length; index++) row.put(header[index], values[index]);
				rows.add(row);
			}
			return rows;
		} catch (IOException error) {
			throw new IllegalArgumentException("Cannot read candidate CSV: " + path, error);
		}
	}

	private static String required(Map<String, String> row, String field) {
		String value = row.get(field);
		if (value == null || value.isBlank()) {
			throw new IllegalArgumentException("Missing candidate field " + field);
		}
		return value.trim();
	}
}
