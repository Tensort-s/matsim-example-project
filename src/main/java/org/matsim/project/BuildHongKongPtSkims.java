package org.matsim.project;

import ch.sbb.matsim.routing.pt.raptor.RaptorParameters;
import ch.sbb.matsim.routing.pt.raptor.RaptorStaticConfig;
import ch.sbb.matsim.routing.pt.raptor.RaptorUtils;
import ch.sbb.matsim.routing.pt.raptor.SwissRailRaptor;
import ch.sbb.matsim.routing.pt.raptor.SwissRailRaptorCore;
import ch.sbb.matsim.routing.pt.raptor.SwissRailRaptorData;
import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Scenario;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.network.io.MatsimNetworkReader;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.pt.transitSchedule.api.TransitScheduleReader;
import org.matsim.pt.transitSchedule.api.TransitStopFacility;
import org.matsim.vehicles.MatsimVehicleReader;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/** Builds schedule-based public-transport skims for Hong Kong model nodes. */
public final class BuildHongKongPtSkims {

	private static final double WALK_SPEED_MPS = 1.2;
	private static final double PRIMARY_ACCESS_RADIUS_M = 800.0;
	private static final double EXTENDED_ACCESS_RADIUS_M = 1200.0;
	private static final double TRANSFER_RADIUS_M = 500.0;
	private static final double TRANSFER_PENALTY_S = 300.0;
	private static final int ACCESS_STOP_COUNT = 3;

	private BuildHongKongPtSkims() {
	}

	private record SkimNode(int index, String id, String type, Coord coord) {
	}

	private record StopAccess(TransitStopFacility stop, double distanceM, boolean extended) {
	}

	private static List<SkimNode> readNodes(Path path) throws IOException {
		List<SkimNode> nodes = new ArrayList<>();
		try (BufferedReader reader = Files.newBufferedReader(path, StandardCharsets.UTF_8)) {
			String header = reader.readLine();
			if (!"node_index\tnode_id\tnode_type\tx\ty".equals(header)) {
				throw new IllegalArgumentException("Unexpected skim node header: " + header);
			}
			String line;
			while ((line = reader.readLine()) != null) {
				String[] values = line.split("\\t", -1);
				if (values.length != 5) {
					throw new IllegalArgumentException("Invalid skim node row: " + line);
				}
				int index = Integer.parseInt(values[0]);
				if (index != nodes.size()) {
					throw new IllegalArgumentException("node_index must be contiguous from zero");
				}
				nodes.add(new SkimNode(
					index,
					values[1],
					values[2],
					new Coord(Double.parseDouble(values[3]), Double.parseDouble(values[4]))
				));
			}
		}
		return nodes;
	}

	private static double parseTimeSeconds(String value) {
		LocalTime time = LocalTime.parse(value);
		return time.toSecondOfDay();
	}

	private static String timeSlug(String value) {
		return value.replace(":", "");
	}

	private static List<StopAccess> nearbyStops(
		SwissRailRaptorData data,
		Coord coord
	) {
		List<StopAccess> primary = data.findNearbyStops(
			coord.getX(), coord.getY(), PRIMARY_ACCESS_RADIUS_M
		).stream().map(stop -> new StopAccess(
			stop,
			distance(coord, stop.getCoord()),
			false
		)).sorted(Comparator.comparingDouble(StopAccess::distanceM)).limit(ACCESS_STOP_COUNT).toList();
		if (primary.size() >= ACCESS_STOP_COUNT) {
			return primary;
		}

		Map<org.matsim.api.core.v01.Id<TransitStopFacility>, StopAccess> combined = new HashMap<>();
		for (StopAccess access : primary) {
			combined.put(access.stop().getId(), access);
		}
		data.findNearbyStops(
			coord.getX(), coord.getY(), EXTENDED_ACCESS_RADIUS_M
		).forEach(stop -> {
			double distance = distance(coord, stop.getCoord());
			combined.putIfAbsent(stop.getId(), new StopAccess(
				stop,
				distance,
				distance > PRIMARY_ACCESS_RADIUS_M
			));
		});
		return combined.values().stream()
			.sorted(Comparator.comparingDouble(StopAccess::distanceM))
			.limit(ACCESS_STOP_COUNT)
			.toList();
	}

	private static double distance(Coord first, Coord second) {
		return Math.hypot(first.getX() - second.getX(), first.getY() - second.getY());
	}

	private static FileChannel createBinary(Path path) throws IOException {
		return FileChannel.open(
			path,
			StandardOpenOption.CREATE,
			StandardOpenOption.TRUNCATE_EXISTING,
			StandardOpenOption.WRITE
		);
	}

	private static void writeFloatRow(FileChannel channel, float[] values) throws IOException {
		ByteBuffer buffer = ByteBuffer.allocate(values.length * Float.BYTES).order(ByteOrder.LITTLE_ENDIAN);
		for (float value : values) {
			buffer.putFloat(value);
		}
		buffer.flip();
		while (buffer.hasRemaining()) {
			channel.write(buffer);
		}
	}

	private static void writeShortRow(FileChannel channel, short[] values) throws IOException {
		ByteBuffer buffer = ByteBuffer.allocate(values.length * Short.BYTES).order(ByteOrder.LITTLE_ENDIAN);
		for (short value : values) {
			buffer.putShort(value);
		}
		buffer.flip();
		while (buffer.hasRemaining()) {
			channel.write(buffer);
		}
	}

	private static void writeByteRow(FileChannel channel, byte[] values) throws IOException {
		ByteBuffer buffer = ByteBuffer.wrap(values);
		while (buffer.hasRemaining()) {
			channel.write(buffer);
		}
	}

	private static void writeAccessAudit(
		Path path,
		List<SkimNode> nodes,
		List<List<StopAccess>> access
	) throws IOException {
		try (BufferedWriter writer = Files.newBufferedWriter(path, StandardCharsets.UTF_8)) {
			writer.write("node_index\tnode_id\tnode_type\taccess_rank\tstop_id\tstop_name\tdistance_m\textended_radius\n");
			for (SkimNode node : nodes) {
				List<StopAccess> options = access.get(node.index());
				if (options.isEmpty()) {
					writer.write(String.format(Locale.ROOT, "%d\t%s\t%s\t0\t\t\t\ttrue%n",
						node.index(), node.id(), node.type()));
					continue;
				}
				for (int rank = 0; rank < options.size(); rank++) {
					StopAccess option = options.get(rank);
					String name = option.stop().getName() == null ? "" : option.stop().getName().replace('\t', ' ');
					writer.write(String.format(Locale.ROOT, "%d\t%s\t%s\t%d\t%s\t%s\t%.3f\t%s%n",
						node.index(), node.id(), node.type(), rank + 1, option.stop().getId(), name,
						option.distanceM(), option.extended()));
				}
			}
		}
	}

	public static void main(String[] args) throws Exception {
		if (args.length != 6) {
			throw new IllegalArgumentException(
				"Usage: BuildHongKongPtSkims <network> <schedule> <vehicles> <nodes.tsv> <output-dir> <times-comma-separated>"
			);
		}

		Path networkPath = Path.of(args[0]);
		Path schedulePath = Path.of(args[1]);
		Path vehiclesPath = Path.of(args[2]);
		Path nodesPath = Path.of(args[3]);
		Path outputDir = Path.of(args[4]);
		String[] timeValues = args[5].split(",");
		Files.createDirectories(outputDir);

		Config config = ConfigUtils.createConfig();
		config.transit().setUseTransit(true);
		config.transitRouter().setSearchRadius(PRIMARY_ACCESS_RADIUS_M);
		config.transitRouter().setExtensionRadius(EXTENDED_ACCESS_RADIUS_M);
		config.transitRouter().setAdditionalTransferTime(60.0);
		config.scoring().getOrCreateModeParams("pt").setMarginalUtilityOfTraveling(-1.0);
		config.scoring().getOrCreateModeParams("walk").setMarginalUtilityOfTraveling(-2.0);
		config.scoring().setMarginalUtlOfWaitingPt_utils_hr(-2.0);
		config.scoring().setUtilityOfLineSwitch(-TRANSFER_PENALTY_S / 3600.0);

		Scenario scenario = ScenarioUtils.createScenario(config);
		MatsimNetworkReader networkReader = new MatsimNetworkReader(scenario.getNetwork());
		networkReader.setValidating(false);
		networkReader.readFile(networkPath.toString());
		new TransitScheduleReader(scenario).readFile(schedulePath.toString());
		new MatsimVehicleReader(scenario.getTransitVehicles()).readFile(vehiclesPath.toString());

		RaptorStaticConfig staticConfig = RaptorUtils.createStaticConfig(config);
		staticConfig.setOptimization(RaptorStaticConfig.RaptorOptimization.OneToAllRouting);
		staticConfig.setBeelineWalkConnectionDistance(TRANSFER_RADIUS_M);
		staticConfig.setBeelineWalkSpeed(WALK_SPEED_MPS);
		staticConfig.setMinimalTransferTime(60.0);
		SwissRailRaptorData data = SwissRailRaptorData.create(
			scenario.getTransitSchedule(),
			scenario.getTransitVehicles(),
			staticConfig,
			scenario.getNetwork(),
			null
		);
		SwissRailRaptor raptor = new SwissRailRaptor.Builder(data, config).build();
		RaptorParameters parameters = RaptorUtils.createParameters(config);
		parameters.setBeelineWalkSpeed(WALK_SPEED_MPS);
		parameters.setSearchRadius(PRIMARY_ACCESS_RADIUS_M);
		parameters.setExtensionRadius(EXTENDED_ACCESS_RADIUS_M);
		parameters.setTransferPenaltyFixCostPerTransfer(TRANSFER_PENALTY_S);

		List<SkimNode> nodes = readNodes(nodesPath);
		List<List<StopAccess>> nodeAccess = nodes.stream()
			.map(node -> nearbyStops(data, node.coord()))
			.toList();
		writeAccessAudit(outputDir.resolve("node_stop_access.tsv"), nodes, nodeAccess);

		int nodeCount = nodes.size();
		for (String timeValue : timeValues) {
			double departureTime = parseTimeSeconds(timeValue);
			String slug = timeSlug(timeValue);
			Path travelPath = outputDir.resolve("travel_time_" + slug + ".f32");
			Path generalizedPath = outputDir.resolve("generalized_time_" + slug + ".f32");
			Path transferPath = outputDir.resolve("transfers_" + slug + ".i16");
			Path reachablePath = outputDir.resolve("reachable_" + slug + ".u8");

			try (
				FileChannel travelChannel = createBinary(travelPath);
				FileChannel generalizedChannel = createBinary(generalizedPath);
				FileChannel transferChannel = createBinary(transferPath);
				FileChannel reachableChannel = createBinary(reachablePath)
			) {
				for (SkimNode origin : nodes) {
					float[] travelRow = new float[nodeCount];
					float[] generalizedRow = new float[nodeCount];
					short[] transferRow = new short[nodeCount];
					byte[] reachableRow = new byte[nodeCount];
					java.util.Arrays.fill(travelRow, Float.NaN);
					java.util.Arrays.fill(generalizedRow, Float.NaN);
					java.util.Arrays.fill(transferRow, (short) -1);

					List<StopAccess> originStops = nodeAccess.get(origin.index());
					List<Map<org.matsim.api.core.v01.Id<TransitStopFacility>, SwissRailRaptorCore.TravelInfo>> trees = new ArrayList<>();
					for (StopAccess originStop : originStops) {
						double accessSeconds = originStop.distanceM() / WALK_SPEED_MPS;
						trees.add(raptor.calcTree(
							originStop.stop(),
							departureTime + accessSeconds,
							parameters,
							null
						));
					}

					for (SkimNode destination : nodes) {
						if (origin.index() == destination.index()) {
							travelRow[destination.index()] = 0.0f;
							generalizedRow[destination.index()] = 0.0f;
							transferRow[destination.index()] = 0;
							reachableRow[destination.index()] = 1;
							continue;
						}
						double bestGeneralized = Double.POSITIVE_INFINITY;
						double bestTravel = Double.POSITIVE_INFINITY;
						int bestTransfers = -1;
						for (int originStopIndex = 0; originStopIndex < originStops.size(); originStopIndex++) {
							StopAccess originStop = originStops.get(originStopIndex);
							double accessSeconds = originStop.distanceM() / WALK_SPEED_MPS;
							Map<org.matsim.api.core.v01.Id<TransitStopFacility>, SwissRailRaptorCore.TravelInfo> tree = trees.get(originStopIndex);
							for (StopAccess destinationStop : nodeAccess.get(destination.index())) {
								SwissRailRaptorCore.TravelInfo info = tree.get(destinationStop.stop().getId());
								if (info == null) {
									continue;
								}
								double egressSeconds = destinationStop.distanceM() / WALK_SPEED_MPS;
								double inSystemSeconds = Math.max(0.0, info.ptArrivalTime - (departureTime + accessSeconds));
								double totalTravelSeconds = accessSeconds + inSystemSeconds + egressSeconds;
								double generalizedSeconds = 2.0 * accessSeconds
									+ inSystemSeconds
									+ Math.max(0.0, info.waitingTime)
									+ 2.0 * egressSeconds
									+ Math.max(0, info.transferCount) * TRANSFER_PENALTY_S;
								if (generalizedSeconds < bestGeneralized) {
									bestGeneralized = generalizedSeconds;
									bestTravel = totalTravelSeconds;
									bestTransfers = Math.max(0, info.transferCount);
								}
							}
						}
						if (Double.isFinite(bestGeneralized)) {
							travelRow[destination.index()] = (float) bestTravel;
							generalizedRow[destination.index()] = (float) bestGeneralized;
							transferRow[destination.index()] = (short) Math.min(bestTransfers, Short.MAX_VALUE);
							reachableRow[destination.index()] = 1;
						}
					}

					writeFloatRow(travelChannel, travelRow);
					writeFloatRow(generalizedChannel, generalizedRow);
					writeShortRow(transferChannel, transferRow);
					writeByteRow(reachableChannel, reachableRow);
					if ((origin.index() + 1) % 50 == 0 || origin.index() + 1 == nodeCount) {
						System.out.printf(Locale.ROOT, "PT_SKIM_PROGRESS time=%s origin=%d/%d%n",
							timeValue, origin.index() + 1, nodeCount);
					}
				}
			}
		}

		Map<String, Object> summary = new HashMap<>();
		summary.put("nodes", nodeCount);
		summary.put("times", String.join(",", timeValues));
		summary.put("walk_speed_mps", WALK_SPEED_MPS);
		summary.put("primary_access_radius_m", PRIMARY_ACCESS_RADIUS_M);
		summary.put("extended_access_radius_m", EXTENDED_ACCESS_RADIUS_M);
		summary.put("transfer_radius_m", TRANSFER_RADIUS_M);
		summary.put("transfer_penalty_s", TRANSFER_PENALTY_S);
		try (BufferedWriter writer = Files.newBufferedWriter(outputDir.resolve("java_skim_summary.txt"), StandardCharsets.UTF_8)) {
			for (Map.Entry<String, Object> entry : summary.entrySet()) {
				writer.write(entry.getKey() + "=" + entry.getValue());
				writer.newLine();
			}
		}
		System.out.printf("PT_SKIM_COMPLETE nodes=%d periods=%d%n", nodeCount, timeValues.length);
	}
}
