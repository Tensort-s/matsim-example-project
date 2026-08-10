package org.matsim.project.hongkong.signals;

import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.network.Network;
import org.matsim.contrib.signals.SignalSystemsConfigGroup;
import org.matsim.contrib.signals.controller.fixedTime.DefaultPlanbasedSignalSystemController;
import org.matsim.contrib.signals.data.SignalsData;
import org.matsim.contrib.signals.data.ambertimes.v10.AmberTimesWriter10;
import org.matsim.contrib.signals.data.intergreens.v10.IntergreenTimesWriter10;
import org.matsim.contrib.signals.data.intergreens.v10.IntergreensForSignalSystemData;
import org.matsim.contrib.signals.data.signalcontrol.v20.SignalControlWriter20;
import org.matsim.contrib.signals.data.signalcontrol.v20.SignalGroupSettingsData;
import org.matsim.contrib.signals.data.signalcontrol.v20.SignalPlanData;
import org.matsim.contrib.signals.data.signalgroups.v20.SignalGroupData;
import org.matsim.contrib.signals.data.signalgroups.v20.SignalGroupsWriter20;
import org.matsim.contrib.signals.data.signalsystems.v20.SignalData;
import org.matsim.contrib.signals.data.signalsystems.v20.SignalSystemControllerData;
import org.matsim.contrib.signals.data.signalsystems.v20.SignalSystemData;
import org.matsim.contrib.signals.data.signalsystems.v20.SignalSystemsWriter20;
import org.matsim.contrib.signals.model.Signal;
import org.matsim.contrib.signals.model.SignalGroup;
import org.matsim.contrib.signals.model.SignalPlan;
import org.matsim.contrib.signals.model.SignalSystem;
import org.matsim.contrib.signals.utils.SignalUtils;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.network.NetworkUtils;

import java.io.BufferedReader;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/** Compiles the audited Hong Kong eight-junction pilot tables to MATSim signal XML. */
public final class BuildHongKongTrafficSignalPilot {

	private static final int AMBER_SECONDS = 3;
	private static final int RED_AMBER_SECONDS = 2;
	private static final int INTERGREEN_SECONDS = 5;

	private BuildHongKongTrafficSignalPilot() { }

	public static void main(String[] args) throws IOException {
		if (args.length != 4) {
			throw new IllegalArgumentException(
					"Usage: BuildHongKongTrafficSignalPilot <audit-dir> <network.xml.gz> "
							+ "<output-dir> <am|pm>");
		}
		Path auditDirectory = Path.of(args[0]).toAbsolutePath().normalize();
		Path networkFile = Path.of(args[1]).toAbsolutePath().normalize();
		Path outputDirectory = Path.of(args[2]).toAbsolutePath().normalize();
		String period = args[3].toLowerCase(Locale.ROOT);
		if (!Set.of("am", "pm").contains(period)) {
			throw new IllegalArgumentException("Period must be am or pm, not " + period);
		}
		Path movementsFile = auditDirectory.resolve("signal_movements.csv");
		Path timingFile = auditDirectory.resolve("observed_timing_evidence.csv");
		for (Path required : List.of(movementsFile, timingFile, networkFile)) {
			if (!Files.isRegularFile(required)) {
				throw new IllegalArgumentException("Missing required pilot input: " + required);
			}
		}

		Network network = NetworkUtils.readNetwork(networkFile.toString());
		List<Map<String, String>> movements = readCsv(movementsFile);
		List<Map<String, String>> timings = readCsv(timingFile).stream()
				.filter(row -> period.equals(row.get("period")))
				.toList();
		if (movements.isEmpty() || timings.isEmpty()) {
			throw new IllegalArgumentException("Pilot movement or timing table is empty.");
		}

		Config config = ConfigUtils.createConfig(new SignalSystemsConfigGroup());
		SignalSystemsConfigGroup signalConfig = ConfigUtils.addOrGetModule(
				config, SignalSystemsConfigGroup.class);
		signalConfig.setUseSignalSystems(true);
		signalConfig.setUseAmbertimes(true);
		signalConfig.setUseIntergreenTimes(true);
		signalConfig.setActionOnIntergreenViolation(
				SignalSystemsConfigGroup.ActionOnSignalSpecsViolation.EXCEPTION);
		SignalsData data = SignalUtils.createSignalsData(signalConfig);
		data.getAmberTimesData().setDefaultAmber(AMBER_SECONDS);
		data.getAmberTimesData().setDefaultRedAmber(RED_AMBER_SECONDS);

		Map<String, SignalSystemData> systems = new LinkedHashMap<>();
		Map<String, SignalGroupData> groups = new LinkedHashMap<>();
		Set<String> uniqueSignals = new LinkedHashSet<>();
		for (Map<String, String> row : movements) {
			String systemText = required(row, "signal_system_id");
			String signalText = required(row, "signal_id");
			String groupText = required(row, "signal_group_id");
			String uniqueSignal = systemText + "::" + signalText;
			if (!uniqueSignals.add(uniqueSignal)) {
				throw new IllegalArgumentException("Duplicate signal ID in system: " + uniqueSignal);
			}
			Id<SignalSystem> systemId = Id.create(systemText, SignalSystem.class);
			SignalSystemData system = systems.computeIfAbsent(systemText, ignored -> {
				SignalSystemData created = data.getSignalSystemsData().getFactory()
						.createSignalSystemData(systemId);
				data.getSignalSystemsData().addSignalSystemData(created);
				return created;
			});
			Id<Link> fromLinkId = Id.createLinkId(required(row, "from_link_id"));
			Id<Link> toLinkId = Id.createLinkId(required(row, "to_link_id"));
			Link fromLink = network.getLinks().get(fromLinkId);
			Link toLink = network.getLinks().get(toLinkId);
			if (fromLink == null || toLink == null) {
				throw new IllegalArgumentException(
						"Signal movement references missing link: " + fromLinkId + " -> " + toLinkId);
			}
			if (!fromLink.getToNode().getId().equals(toLink.getFromNode().getId())) {
				throw new IllegalArgumentException(
						"Signal movement is not topologically adjacent: " + fromLinkId + " -> " + toLinkId);
			}
			Id<Signal> signalId = Id.create(signalText, Signal.class);
			SignalData signal = data.getSignalSystemsData().getFactory().createSignalData(signalId);
			signal.setLinkId(fromLinkId);
			signal.addTurningMoveRestriction(toLinkId);
			system.addSignalData(signal);

			String uniqueGroup = systemText + "::" + groupText;
			SignalGroupData group = groups.computeIfAbsent(uniqueGroup, ignored -> {
				Id<SignalGroup> groupId = Id.create(groupText, SignalGroup.class);
				SignalGroupData created = data.getSignalGroupsData().getFactory()
						.createSignalGroupData(systemId, groupId);
				data.getSignalGroupsData().addSignalGroupData(created);
				return created;
			});
			group.addSignalId(signalId);
		}

		Map<String, List<Map<String, String>>> timingBySystem = new LinkedHashMap<>();
		for (Map<String, String> row : timings) {
			timingBySystem.computeIfAbsent(required(row, "signal_junction_id"), ignored -> new ArrayList<>())
					.add(row);
		}
		for (Map.Entry<String, SignalSystemData> entry : systems.entrySet()) {
			String systemText = entry.getKey();
			Id<SignalSystem> systemId = entry.getValue().getId();
			List<Map<String, String>> systemTiming = timingBySystem.get(systemText);
			if (systemTiming == null) {
				throw new IllegalArgumentException("Missing " + period + " timing for " + systemText);
			}
			int cycle = Integer.parseInt(required(systemTiming.getFirst(), "cycle_s"));
			SignalSystemControllerData controller = data.getSignalControlData().getFactory()
					.createSignalSystemControllerData(systemId);
			controller.setControllerIdentifier(DefaultPlanbasedSignalSystemController.IDENTIFIER);
			data.getSignalControlData().addSignalSystemControllerData(controller);
			SignalPlanData plan = data.getSignalControlData().getFactory()
					.createSignalPlanData(Id.create("observed_partial_" + period, SignalPlan.class));
			plan.setStartTime(0.0);
			plan.setEndTime(0.0);
			plan.setCycleTime(cycle);
			plan.setOffset(0);
			controller.addSignalPlanData(plan);

			Map<Id<SignalGroup>, SignalGroupData> systemGroups = data.getSignalGroupsData()
					.getSignalGroupDataBySystemId(systemId);
			for (Map<String, String> timing : systemTiming) {
				Id<SignalGroup> groupId = Id.create(
						"stage_" + required(timing, "stage_label"), SignalGroup.class);
				if (!systemGroups.containsKey(groupId)) {
					continue;
				}
				int onset = Integer.parseInt(required(timing, "green_onset_s"));
				int dropping = Integer.parseInt(required(timing, "green_dropping_s"));
				if (onset < 0 || dropping <= onset || dropping > cycle) {
					throw new IllegalArgumentException(
							"Invalid green interval for " + systemText + " " + groupId
									+ ": " + onset + ".." + dropping + " cycle=" + cycle);
				}
				SignalGroupSettingsData settings = data.getSignalControlData().getFactory()
						.createSignalGroupSettingsData(groupId);
				settings.setOnset(onset);
				settings.setDropping(dropping);
				plan.addSignalGroupSettings(settings);
			}
			if (plan.getSignalGroupSettingsDataByGroupId().size() != systemGroups.size()) {
				throw new IllegalArgumentException(
						"Not every signal group has timing in " + systemText + " " + period);
			}

			IntergreensForSignalSystemData intergreens = data.getIntergreenTimesData().getFactory()
					.createIntergreensForSignalSystem(systemId);
			List<Id<SignalGroup>> groupIds = new ArrayList<>(systemGroups.keySet());
			for (Id<SignalGroup> ending : groupIds) {
				for (Id<SignalGroup> beginning : groupIds) {
					if (!ending.equals(beginning)) {
						intergreens.setIntergreenTime(INTERGREEN_SECONDS, ending, beginning);
					}
				}
			}
			data.getIntergreenTimesData().addIntergreensForSignalSystem(intergreens);
		}

		Files.createDirectories(outputDirectory);
		new SignalSystemsWriter20(data.getSignalSystemsData()).write(
				outputDirectory.resolve("signal_systems.xml").toString());
		new SignalGroupsWriter20(data.getSignalGroupsData()).write(
				outputDirectory.resolve("signal_groups.xml").toString());
		new SignalControlWriter20(data.getSignalControlData()).write(
				outputDirectory.resolve("signal_control.xml").toString());
		new AmberTimesWriter10(data.getAmberTimesData()).write(
				outputDirectory.resolve("amber_times.xml").toString());
		new IntergreenTimesWriter10(data.getIntergreenTimesData()).write(
				outputDirectory.resolve("intergreen_times.xml").toString());
		System.out.printf(
				"Compiled Hong Kong signal pilot: period=%s systems=%,d signals=%,d groups=%,d output=%s%n",
				period, systems.size(), movements.size(), groups.size(), outputDirectory);
	}

	private static String required(Map<String, String> row, String key) {
		String value = row.get(key);
		if (value == null || value.isBlank()) {
			throw new IllegalArgumentException("Missing CSV value for " + key + " in " + row);
		}
		return value;
	}

	private static List<Map<String, String>> readCsv(Path path) throws IOException {
		try (BufferedReader reader = Files.newBufferedReader(path, StandardCharsets.UTF_8)) {
			String headerLine = reader.readLine();
			if (headerLine == null) return List.of();
			if (headerLine.startsWith("\uFEFF")) headerLine = headerLine.substring(1);
			List<String> headers = parseCsvLine(headerLine);
			List<Map<String, String>> rows = new ArrayList<>();
			String line;
			while ((line = reader.readLine()) != null) {
				if (line.isBlank()) continue;
				List<String> values = parseCsvLine(line);
				if (values.size() != headers.size()) {
					throw new IllegalArgumentException(
							"CSV width mismatch in " + path + ": " + values.size() + " != " + headers.size());
				}
				Map<String, String> row = new LinkedHashMap<>();
				for (int index = 0; index < headers.size(); index++) {
					row.put(headers.get(index), values.get(index));
				}
				rows.add(row);
			}
			return rows;
		}
	}

	private static List<String> parseCsvLine(String line) {
		List<String> values = new ArrayList<>();
		StringBuilder value = new StringBuilder();
		boolean quoted = false;
		for (int index = 0; index < line.length(); index++) {
			char character = line.charAt(index);
			if (character == '"') {
				if (quoted && index + 1 < line.length() && line.charAt(index + 1) == '"') {
					value.append('"');
					index++;
				} else {
					quoted = !quoted;
				}
			} else if (character == ',' && !quoted) {
				values.add(value.toString());
				value.setLength(0);
			} else {
				value.append(character);
			}
		}
		if (quoted) throw new IllegalArgumentException("Unclosed CSV quote: " + line);
		values.add(value.toString());
		return values;
	}
}
