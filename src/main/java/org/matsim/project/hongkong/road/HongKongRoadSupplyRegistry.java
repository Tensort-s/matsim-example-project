package org.matsim.project.hongkong.road;

import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.network.Link;
import org.matsim.core.config.groups.QSimConfigGroup;

import java.io.BufferedReader;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Immutable full-network registry with explicit storage and optional QSim-only flow overrides. */
public final class HongKongRoadSupplyRegistry {
	private static final double EPSILON = 1e-8;

	public record StorageOverride(
			Id<Link> linkId,
			double physicalLengthMeters,
			double physicalLanes,
			double freespeedMetersPerSecond,
			double physicalFlowCapacityVehiclesPerHour,
			double qsimFlowCapacityVehiclesPerHour,
			boolean flowCapacityOverride,
			double storageCapacityQsimPcu,
			double storageLaneFloorXPcu,
			String relationshipIds) {
	}

	private final Path source;
	private final String sourceNetworkSha256;
	private final int roadLinkCount;
	private final Map<Id<Link>, StorageOverride> overrides;

	private HongKongRoadSupplyRegistry(
			Path source,
			String sourceNetworkSha256,
			int roadLinkCount,
			Map<Id<Link>, StorageOverride> overrides) {
		this.source = source;
		this.sourceNetworkSha256 = sourceNetworkSha256;
		this.roadLinkCount = roadLinkCount;
		this.overrides = Collections.unmodifiableMap(new LinkedHashMap<>(overrides));
	}

	public static HongKongRoadSupplyRegistry load(
			Path registryPath,
			Path networkPath,
			Scenario scenario,
			double expectedTaxiPcu) {
		Path registry = registryPath.toAbsolutePath().normalize();
		Path network = networkPath.toAbsolutePath().normalize();
		if (!Files.isRegularFile(registry) || !Files.isRegularFile(network)) {
			throw new IllegalArgumentException("Road-supply registry/network is not a regular file: "
					+ registry + ", " + network);
		}
		List<String> lines;
		try {
			lines = Files.readAllLines(registry, StandardCharsets.UTF_8);
		} catch (IOException error) {
			throw new IllegalArgumentException("Cannot read road-supply registry: " + registry, error);
		}
		if (lines.size() < 2) {
			throw new IllegalArgumentException("Road-supply registry is empty: " + registry);
		}
		List<String> header = parseCsvLine(lines.getFirst());
		Map<String, Integer> columns = new LinkedHashMap<>();
		for (int index = 0; index < header.size(); index++) columns.put(header.get(index), index);
		for (String required : List.of(
				"link_id", "physical_length_m", "physical_lanes", "freespeed_m_s",
				"flow_capacity_vph", "flow_capacity_override",
				"storage_capacity_qsim_pcu", "storage_capacity_override",
				"continuity_relationship_ids",
				"source_network_sha256")) {
			if (!columns.containsKey(required)) {
				throw new IllegalArgumentException("Road-supply registry lacks column: " + required);
			}
		}
		String storageFloorColumn = columns.containsKey("storage_floor_pcu")
				? "storage_floor_pcu"
				: (columns.containsKey("storage_lane_floor_x_pcu")
						? "storage_lane_floor_x_pcu" : "continuity_lane_floor_x_pcu");
		if (!columns.containsKey(storageFloorColumn)) {
			throw new IllegalArgumentException(
					"Road-supply registry lacks storage_floor_pcu, storage_lane_floor_x_pcu, "
							+ "and legacy continuity_lane_floor_x_pcu");
		}

		String registryNetworkSha = null;
		Map<Id<Link>, StorageOverride> overrides = new LinkedHashMap<>();
		int roadLinks = 0;
		for (int lineNumber = 2; lineNumber <= lines.size(); lineNumber++) {
			String line = lines.get(lineNumber - 1);
			if (line.isBlank()) continue;
			List<String> values = parseCsvLine(line);
			if (values.size() != header.size()) {
				throw new IllegalArgumentException("Malformed road-supply CSV row " + lineNumber);
			}
			String rowSha = value(values, columns, "source_network_sha256");
			if (registryNetworkSha == null) registryNetworkSha = rowSha;
			if (!registryNetworkSha.equals(rowSha)) {
				throw new IllegalArgumentException("Mixed source-network SHA values at row " + lineNumber);
			}
			Id<Link> linkId = Id.createLinkId(value(values, columns, "link_id"));
			Link link = scenario.getNetwork().getLinks().get(linkId);
			if (link == null) throw new IllegalArgumentException("Registry link absent from network: " + linkId);
			double length = number(values, columns, "physical_length_m", lineNumber);
			double lanes = number(values, columns, "physical_lanes", lineNumber);
			double freespeed = number(values, columns, "freespeed_m_s", lineNumber);
			double capacity = number(values, columns, "flow_capacity_vph", lineNumber);
			double physicalCapacity = columns.containsKey("physical_flow_capacity_vph")
					? number(values, columns, "physical_flow_capacity_vph", lineNumber)
					: capacity;
			boolean flowOverride = Boolean.parseBoolean(
					value(values, columns, "flow_capacity_override"));
			requireClose(linkId, "length", length, link.getLength());
			requireClose(linkId, "lanes", lanes, link.getNumberOfLanes());
			requireClose(linkId, "freespeed", freespeed, link.getFreespeed());
			requireClose(linkId, "physical flow capacity", physicalCapacity, link.getCapacity());
			if (!flowOverride) {
				requireClose(linkId, "non-overridden flow capacity", physicalCapacity, capacity);
			} else if (!Double.isFinite(capacity) || capacity <= 0.0
					|| capacity + EPSILON < physicalCapacity) {
				throw new IllegalArgumentException(
						"Invalid or reducing QSim flow-capacity override for " + linkId);
			}
			roadLinks++;
			boolean storageOverride = Boolean.parseBoolean(
					value(values, columns, "storage_capacity_override"));
			if (flowOverride && !storageOverride) {
				throw new IllegalArgumentException(
						"QSim flow override requires an explicit storage row for " + linkId);
			}
			if (!storageOverride) continue;
			double storage = number(values, columns, "storage_capacity_qsim_pcu", lineNumber);
			double x = number(values, columns, storageFloorColumn, lineNumber);
			if (storage + EPSILON < x) {
				throw new IllegalArgumentException("Explicit storage is below x for " + linkId);
			}
			StorageOverride previous = overrides.put(linkId, new StorageOverride(
					linkId, length, lanes, freespeed, physicalCapacity, capacity,
					flowOverride, storage, x,
					value(values, columns, "continuity_relationship_ids")));
			if (previous != null) throw new IllegalArgumentException("Duplicate registry link: " + linkId);
		}
		if (registryNetworkSha == null) throw new IllegalArgumentException("Missing source-network SHA");
		String actualNetworkSha = sha256(network);
		if (!registryNetworkSha.equals(actualNetworkSha)) {
			throw new IllegalArgumentException("Road-supply source-network SHA mismatch: registry="
					+ registryNetworkSha + ", actual=" + actualNetworkSha);
		}
		if (overrides.isEmpty() || overrides.size() > roadLinks) {
			throw new IllegalArgumentException("Explicit-storage registry has invalid override count: "
					+ overrides.size() + " for " + roadLinks + " road links");
		}
		QSimConfigGroup qsim = scenario.getConfig().qsim();
		if (qsim.getTrafficDynamics() != QSimConfigGroup.TrafficDynamics.queue) {
			throw new IllegalArgumentException("Explicit storage supports trafficDynamics=queue only");
		}
		if (qsim.isUseLanes()) {
			throw new IllegalArgumentException("Explicit storage does not support QSim lane definitions");
		}
		if (Math.abs(qsim.getStorageCapFactor() - 0.1) > EPSILON
				|| Math.abs(qsim.getFlowCapFactor() - 0.1) > EPSILON
				|| Math.abs(qsim.getTimeStepSize() - 1.0) > EPSILON
				|| Math.abs(scenario.getNetwork().getEffectiveCellSize() - 7.5) > EPSILON
				|| Math.abs(expectedTaxiPcu - 0.05) > EPSILON) {
			throw new IllegalArgumentException(
					"Explicit-storage registry requires storage/flow factors=0.1, time step=1 s, "
							+ "effective cell size=7.5 m, Taxi PCU=0.05");
		}
		for (StorageOverride override : overrides.values()) {
			double flowPerSecond = override.qsimFlowCapacityVehiclesPerHour() / 3600.0;
			double defaultStorage = override.physicalLengthMeters() * override.physicalLanes()
					* qsim.getStorageCapFactor() / scenario.getNetwork().getEffectiveCellSize();
			double bufferSafety = flowPerSecond * qsim.getTimeStepSize() * qsim.getFlowCapFactor();
			double freeflowSafety = override.physicalLengthMeters() / override.freespeedMetersPerSecond()
					* flowPerSecond * qsim.getFlowCapFactor();
			double required = Math.max(override.storageLaneFloorXPcu(),
					Math.max(defaultStorage, Math.max(bufferSafety, freeflowSafety)));
			requireClose(override.linkId(), "explicit storage formula", required,
					override.storageCapacityQsimPcu());
		}
		return new HongKongRoadSupplyRegistry(registry, registryNetworkSha, roadLinks, overrides);
	}

	public Path source() { return source; }
	public String sourceNetworkSha256() { return sourceNetworkSha256; }
	public int roadLinkCount() { return roadLinkCount; }
	public Map<Id<Link>, StorageOverride> overrides() { return overrides; }
	public StorageOverride override(Id<Link> linkId) { return overrides.get(linkId); }

	private static String value(List<String> row, Map<String, Integer> columns, String name) {
		return row.get(columns.get(name));
	}

	private static double number(List<String> row, Map<String, Integer> columns, String name, int line) {
		try {
			return Double.parseDouble(value(row, columns, name));
		} catch (RuntimeException error) {
			throw new IllegalArgumentException("Invalid " + name + " at row " + line, error);
		}
	}

	private static void requireClose(Id<Link> linkId, String field, double expected, double actual) {
		double tolerance = EPSILON * Math.max(1.0, Math.max(Math.abs(expected), Math.abs(actual)));
		if (!Double.isFinite(expected) || !Double.isFinite(actual) || Math.abs(expected - actual) > tolerance) {
			throw new IllegalArgumentException("Registry " + field + " mismatch for " + linkId
					+ ": expected=" + expected + ", actual=" + actual);
		}
	}

	private static List<String> parseCsvLine(String line) {
		List<String> result = new ArrayList<>();
		StringBuilder current = new StringBuilder();
		boolean quoted = false;
		for (int index = 0; index < line.length(); index++) {
			char value = line.charAt(index);
			if (value == '"') {
				if (quoted && index + 1 < line.length() && line.charAt(index + 1) == '"') {
					current.append('"'); index++;
				} else quoted = !quoted;
			} else if (value == ',' && !quoted) {
				result.add(current.toString()); current.setLength(0);
			} else current.append(value);
		}
		if (quoted) throw new IllegalArgumentException("Unclosed quoted CSV field");
		result.add(current.toString());
		return result;
	}

	private static String sha256(Path path) {
		try (var input = Files.newInputStream(path)) {
			MessageDigest digest = MessageDigest.getInstance("SHA-256");
			byte[] buffer = new byte[8 * 1024 * 1024];
			for (int read; (read = input.read(buffer)) >= 0;) if (read > 0) digest.update(buffer, 0, read);
			return java.util.HexFormat.of().formatHex(digest.digest());
		} catch (IOException | NoSuchAlgorithmException error) {
			throw new IllegalArgumentException("Cannot hash network: " + path, error);
		}
	}
}
