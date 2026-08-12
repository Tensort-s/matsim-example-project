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
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Compiles the bounded Top-100, 96-bin Hong Kong TOD signal proxy. */
public final class BuildHongKongTrafficSignalTodTop100 {

	private static final int EXPECTED_SYSTEMS = 100;
	private static final int EXPECTED_PLANS_PER_SYSTEM = 96;
	private static final int DAY_SECONDS = 24 * 3600;
	private static final int BIN_SECONDS = 15 * 60;
	private static final int AMBER_SECONDS = 3;
	private static final int RED_AMBER_SECONDS = 2;
	private static final int INTERGREEN_SECONDS = 5;

	private BuildHongKongTrafficSignalTodTop100() { }

	public static void main(String[] args) throws IOException {
		if (args.length != 3) {
			throw new IllegalArgumentException(
					"Usage: BuildHongKongTrafficSignalTodTop100 <candidate-dir> <network.xml.gz> <output-dir>");
		}
		Path candidateDirectory = Path.of(args[0]).toAbsolutePath().normalize();
		Path networkFile = Path.of(args[1]).toAbsolutePath().normalize();
		Path outputDirectory = Path.of(args[2]).toAbsolutePath().normalize();
		Path signalsFile = candidateDirectory.resolve("executable_signal_movements.csv");
		Path plansFile = candidateDirectory.resolve("tod_plan_assignments.csv");
		Path windowsFile = candidateDirectory.resolve("tod_group_windows.csv");
		for (Path required : List.of(signalsFile, plansFile, windowsFile, networkFile)) {
			if (!Files.isRegularFile(required)) {
				throw new IllegalArgumentException("Missing required TOD input: " + required);
			}
		}

		Network network = NetworkUtils.readNetwork(networkFile.toString());
		List<Map<String, String>> signalRows = readCsv(signalsFile);
		List<Map<String, String>> planRows = readCsv(plansFile);
		List<Map<String, String>> windowRows = readCsv(windowsFile);

		Config config = ConfigUtils.createConfig(new SignalSystemsConfigGroup());
		SignalSystemsConfigGroup signalConfig = ConfigUtils.addOrGetModule(config, SignalSystemsConfigGroup.class);
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
		for (Map<String, String> row : signalRows) {
			String systemText = required(row, "signal_system_id");
			String signalText = required(row, "signal_id");
			String groupText = required(row, "signal_group_id");
			if (!uniqueSignals.add(systemText + "::" + signalText)) {
				throw new IllegalArgumentException("Duplicate signal ID: " + systemText + "::" + signalText);
			}
			Id<SignalSystem> systemId = Id.create(systemText, SignalSystem.class);
			SignalSystemData system = systems.computeIfAbsent(systemText, ignored -> {
				SignalSystemData created = data.getSignalSystemsData().getFactory().createSignalSystemData(systemId);
				data.getSignalSystemsData().addSignalSystemData(created);
				return created;
			});
			Id<Link> fromLinkId = Id.createLinkId(required(row, "from_link_id"));
			Id<Link> toLinkId = Id.createLinkId(required(row, "to_link_id"));
			Link fromLink = network.getLinks().get(fromLinkId);
			Link toLink = network.getLinks().get(toLinkId);
			if (fromLink == null || toLink == null) {
				throw new IllegalArgumentException("Missing controlled link: " + fromLinkId + " -> " + toLinkId);
			}
			if (!fromLink.getToNode().getId().equals(toLink.getFromNode().getId())) {
				throw new IllegalArgumentException("Non-adjacent controlled turn: " + fromLinkId + " -> " + toLinkId);
			}
			if (fromLink.getFromNode().getId().equals(toLink.getToNode().getId())) {
				throw new IllegalArgumentException("TOD proxy must not activate U-turn: " + fromLinkId + " -> " + toLinkId);
			}
			Id<Signal> signalId = Id.create(signalText, Signal.class);
			SignalData signal = data.getSignalSystemsData().getFactory().createSignalData(signalId);
			signal.setLinkId(fromLinkId);
			signal.addTurningMoveRestriction(toLinkId);
			system.addSignalData(signal);

			String uniqueGroup = systemText + "::" + groupText;
			SignalGroupData group = groups.computeIfAbsent(uniqueGroup, ignored -> {
				Id<SignalGroup> groupId = Id.create(groupText, SignalGroup.class);
				SignalGroupData created = data.getSignalGroupsData().getFactory().createSignalGroupData(systemId, groupId);
				data.getSignalGroupsData().addSignalGroupData(created);
				return created;
			});
			group.addSignalId(signalId);
		}
		if (systems.size() != EXPECTED_SYSTEMS) {
			throw new IllegalArgumentException("Expected exactly 100 signal systems, found " + systems.size());
		}

		Map<String, Map<String, Map<String, String>>> plansBySystem = indexUnique(planRows, "signal_system_id", "plan_id");
		Map<String, Map<String, List<Map<String, String>>>> windowsBySystemPlan = indexMany(windowRows, "signal_system_id", "plan_id");
		for (Map.Entry<String, SignalSystemData> entry : systems.entrySet()) {
			String systemText = entry.getKey();
			Id<SignalSystem> systemId = entry.getValue().getId();
			Map<String, Map<String, String>> systemPlans = plansBySystem.get(systemText);
			if (systemPlans == null || systemPlans.size() != EXPECTED_PLANS_PER_SYSTEM) {
				throw new IllegalArgumentException("Expected 96 plans for " + systemText);
			}
			Map<Id<SignalGroup>, SignalGroupData> systemGroups = data.getSignalGroupsData()
					.getSignalGroupDataBySystemId(systemId);

			SignalSystemControllerData controller = data.getSignalControlData().getFactory()
					.createSignalSystemControllerData(systemId);
			controller.setControllerIdentifier(DefaultPlanbasedSignalSystemController.IDENTIFIER);
			data.getSignalControlData().addSignalSystemControllerData(controller);
			for (int bin = 0; bin < EXPECTED_PLANS_PER_SYSTEM; bin++) {
				String planText = String.format("tod_%02d", bin);
				Map<String, String> row = systemPlans.get(planText);
				if (row == null) throw new IllegalArgumentException("Missing " + planText + " for " + systemText);
				int start = integer(row, "start_time_s");
				int end = integer(row, "end_time_s");
				int cycle = integer(row, "cycle_s");
				if (start != bin * BIN_SECONDS || end != (bin == 95 ? 0 : (bin + 1) * BIN_SECONDS)) {
					throw new IllegalArgumentException("Non-contiguous TOD plan bounds for " + systemText + " " + planText);
				}
				if (DAY_SECONDS % cycle != 0 || BIN_SECONDS % cycle != 0) {
					throw new IllegalArgumentException("Cycle must divide a 15-minute bin and day: " + cycle);
				}
				SignalPlanData plan = data.getSignalControlData().getFactory()
						.createSignalPlanData(Id.create(planText, SignalPlan.class));
				plan.setStartTime((double) start);
				plan.setEndTime((double) end);
				plan.setCycleTime(cycle);
				plan.setOffset(integer(row, "offset_s"));
				controller.addSignalPlanData(plan);

				List<Map<String, String>> windows = windowsBySystemPlan
						.getOrDefault(systemText, Map.of()).get(planText);
				if (windows == null || windows.size() != systemGroups.size()) {
					throw new IllegalArgumentException("Every group needs one window in " + systemText + " " + planText);
				}
				Set<Id<SignalGroup>> configured = new LinkedHashSet<>();
				for (Map<String, String> window : windows) {
					Id<SignalGroup> groupId = Id.create(required(window, "signal_group_id"), SignalGroup.class);
					if (!systemGroups.containsKey(groupId) || !configured.add(groupId)) {
						throw new IllegalArgumentException("Unknown or duplicate group in " + systemText + " " + planText + ": " + groupId);
					}
					int onset = integer(window, "green_onset_s");
					int dropping = integer(window, "green_dropping_s");
					if (onset < 0 || dropping <= onset || dropping > cycle - 6) {
						throw new IllegalArgumentException("Unsafe green interval in " + systemText + " " + planText + ": " + onset + ".." + dropping);
					}
					SignalGroupSettingsData settings = data.getSignalControlData().getFactory()
							.createSignalGroupSettingsData(groupId);
					settings.setOnset(onset);
					settings.setDropping(dropping);
					plan.addSignalGroupSettings(settings);
				}
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
		new SignalSystemsWriter20(data.getSignalSystemsData()).write(outputDirectory.resolve("signal_systems.xml").toString());
		new SignalGroupsWriter20(data.getSignalGroupsData()).write(outputDirectory.resolve("signal_groups.xml").toString());
		new SignalControlWriter20(data.getSignalControlData()).write(outputDirectory.resolve("signal_control.xml").toString());
		new AmberTimesWriter10(data.getAmberTimesData()).write(outputDirectory.resolve("amber_times.xml").toString());
		new IntergreenTimesWriter10(data.getIntergreenTimesData()).write(outputDirectory.resolve("intergreen_times.xml").toString());
		System.out.printf("Compiled Hong Kong TOD Top-100: systems=%,d signals=%,d groups=%,d plans=%,d output=%s%n",
				systems.size(), signalRows.size(), groups.size(), planRows.size(), outputDirectory);
	}

	private static int integer(Map<String, String> row, String key) {
		return Integer.parseInt(required(row, key));
	}

	private static Map<String, Map<String, Map<String, String>>> indexUnique(
			List<Map<String, String>> rows, String outerKey, String innerKey) {
		Map<String, Map<String, Map<String, String>>> result = new LinkedHashMap<>();
		for (Map<String, String> row : rows) {
			Map<String, Map<String, String>> inner = result.computeIfAbsent(required(row, outerKey), ignored -> new LinkedHashMap<>());
			if (inner.put(required(row, innerKey), row) != null) {
				throw new IllegalArgumentException("Duplicate row for " + required(row, outerKey) + " " + required(row, innerKey));
			}
		}
		return result;
	}

	private static Map<String, Map<String, List<Map<String, String>>>> indexMany(
			List<Map<String, String>> rows, String outerKey, String innerKey) {
		Map<String, Map<String, List<Map<String, String>>>> result = new HashMap<>();
		for (Map<String, String> row : rows) {
			result.computeIfAbsent(required(row, outerKey), ignored -> new HashMap<>())
					.computeIfAbsent(required(row, innerKey), ignored -> new ArrayList<>()).add(row);
		}
		return result;
	}

	private static String required(Map<String, String> row, String key) {
		String value = row.get(key);
		if (value == null || value.isBlank()) throw new IllegalArgumentException("Missing CSV value for " + key);
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
				if (values.size() != headers.size()) throw new IllegalArgumentException("CSV width mismatch in " + path);
				Map<String, String> row = new LinkedHashMap<>();
				for (int index = 0; index < headers.size(); index++) row.put(headers.get(index), values.get(index));
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
				} else quoted = !quoted;
			} else if (character == ',' && !quoted) {
				values.add(value.toString());
				value.setLength(0);
			} else value.append(character);
		}
		if (quoted) throw new IllegalArgumentException("Unclosed CSV quote");
		values.add(value.toString());
		return values;
	}
}
