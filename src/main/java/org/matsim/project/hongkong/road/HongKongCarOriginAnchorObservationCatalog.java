package org.matsim.project.hongkong.road;

import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.Person;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Event-derived private-Car start-link reverse transitions to audit at runtime. */
public final class HongKongCarOriginAnchorObservationCatalog {

	public record Observation(
			Id<Person> personId,
			String vehicleId,
			int privateCarTripOrdinal,
			double vehicleEntersTrafficTimeS,
			Id<Link> startLinkId,
			Id<Link> observedReverseLinkId) {
		public Observation {
			if (personId == null || vehicleId == null || vehicleId.isBlank()
					|| privateCarTripOrdinal < 0 || !Double.isFinite(vehicleEntersTrafficTimeS)
					|| vehicleEntersTrafficTimeS < 0 || startLinkId == null
					|| observedReverseLinkId == null) {
				throw new IllegalArgumentException("Invalid Car origin-anchor observation.");
			}
		}
	}

	private final List<Observation> observations;

	private HongKongCarOriginAnchorObservationCatalog(List<Observation> observations) {
		this.observations = List.copyOf(observations);
	}

	public static HongKongCarOriginAnchorObservationCatalog load(Path path) {
		List<Map<String, String>> rows = csv(path.toAbsolutePath().normalize());
		List<Observation> observations = new ArrayList<>(rows.size());
		for (Map<String, String> row : rows) {
			observations.add(new Observation(
					Id.createPersonId(required(row, "person_id")),
					required(row, "vehicle_id"),
					Integer.parseInt(required(row, "private_car_trip_ordinal")),
					Double.parseDouble(required(row, "vehicle_enters_traffic_time_s")),
					Id.createLinkId(required(row, "start_link_id")),
					Id.createLinkId(required(row, "observed_reverse_link_id"))));
		}
		if (observations.isEmpty()) {
			throw new IllegalStateException("Car origin-anchor observation catalog is empty: " + path);
		}
		return new HongKongCarOriginAnchorObservationCatalog(observations);
	}

	public List<Observation> observations() {
		return observations;
	}

	private static String required(Map<String, String> row, String column) {
		String value = row.get(column);
		if (value == null || value.isBlank()) {
			throw new IllegalStateException("Missing Car origin-anchor column/value " + column);
		}
		return value;
	}

	private static List<Map<String, String>> csv(Path path) {
		List<String> lines;
		try {
			lines = Files.readAllLines(path, StandardCharsets.UTF_8);
		} catch (IOException error) {
			throw new IllegalStateException("Failed to read Car origin-anchor observations " + path, error);
		}
		if (lines.isEmpty()) throw new IllegalStateException("Empty CSV: " + path);
		List<String> header = csvFields(lines.getFirst());
		if (!header.isEmpty() && header.getFirst().startsWith("\uFEFF")) {
			header.set(0, header.getFirst().substring(1));
		}
		List<Map<String, String>> rows = new ArrayList<>();
		for (String line : lines.subList(1, lines.size())) {
			if (line.isBlank()) continue;
			List<String> values = csvFields(line);
			if (values.size() != header.size()) {
				throw new IllegalStateException("Malformed CSV row in " + path);
			}
			Map<String, String> row = new LinkedHashMap<>();
			for (int index = 0; index < header.size(); index++) {
				row.put(header.get(index), values.get(index));
			}
			rows.add(row);
		}
		return rows;
	}

	static List<String> csvFields(String line) {
		List<String> fields = new ArrayList<>();
		StringBuilder current = new StringBuilder();
		boolean quoted = false;
		for (int index = 0; index < line.length(); index++) {
			char value = line.charAt(index);
			if (value == '"') {
				if (quoted && index + 1 < line.length() && line.charAt(index + 1) == '"') {
					current.append('"');
					index++;
				} else {
					quoted = !quoted;
				}
			} else if (value == ',' && !quoted) {
				fields.add(current.toString());
				current.setLength(0);
			} else {
				current.append(value);
			}
		}
		if (quoted) throw new IllegalStateException("Unclosed quoted CSV field");
		fields.add(current.toString());
		return fields;
	}
}
