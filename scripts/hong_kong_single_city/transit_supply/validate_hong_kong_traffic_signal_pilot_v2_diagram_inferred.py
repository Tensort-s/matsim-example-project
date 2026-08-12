#!/usr/bin/env python3
"""Validate the diagram-inferred Hong Kong MATSim signal pilot v2."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from pathlib import Path

from lxml import etree as ET


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PILOT = (
    REPO_ROOT
    / "data/transit/hongkong/processed/"
    "hong_kong_traffic_signals_2026_pilot_v2_diagram_inferred"
)
DEFAULT_SOURCE_NETWORK = (
    REPO_ROOT
    / "data/transit/hongkong/processed/"
    "matsim_road_pt_school_bus_supply_2026_v6_adoption_ready/network.xml.gz"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-dir", type=Path, default=DEFAULT_PILOT)
    parser.add_argument("--source-network", type=Path, default=DEFAULT_SOURCE_NETWORK)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def parse_xml(path: Path) -> ET._ElementTree:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as stream:
        return ET.parse(stream)


def local_name(element: ET._Element) -> str:
    return ET.QName(element).localname


def children(element: ET._Element, name: str) -> list[ET._Element]:
    return [child for child in element.iter() if local_name(child) == name]


def network_tables(path: Path) -> tuple[dict[str, tuple[str, str]], dict[str, dict[str, str]]]:
    root = parse_xml(path).getroot()
    nodes = {
        element.get("id"): (element.get("x"), element.get("y"))
        for element in root.find("nodes")
    }
    links = {element.get("id"): dict(element.attrib) for element in root.find("links")}
    return nodes, links


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def split_labels(value: str) -> set[str]:
    return {item for item in value.split("|") if item}


def main() -> int:
    args = parse_args()
    table_names = (
        "diagram_stage_inference.csv",
        "deferred_junctions.csv",
        "observed_timing_evidence.csv",
        "signal_movements.csv",
        "signal_group_stage_windows.csv",
        "junction_stage_mapping.csv",
        "movement_conflicts.csv",
        "capacity_deconvolution_audit.csv",
        "pedestrian_phase_audit.csv",
    )
    required_files = [args.pilot_dir / name for name in table_names]
    required_files.extend(
        [
            args.pilot_dir / "pilot_build_summary.json",
            args.pilot_dir / "network_signal_capacity_deconvolved.xml.gz",
        ]
    )
    for period in ("am", "pm"):
        required_files.extend(
            args.pilot_dir / f"matsim_{period}" / filename
            for filename in (
                "signal_systems.xml",
                "signal_groups.xml",
                "signal_control.xml",
                "amber_times.xml",
                "intergreen_times.xml",
            )
        )
    missing = [str(path) for path in required_files if not path.is_file()]
    require(not missing, f"Missing pilot files: {missing}")

    build_summary = json.loads(
        (args.pilot_dir / "pilot_build_summary.json").read_text(encoding="utf-8")
    )
    inferences = read_csv(args.pilot_dir / "diagram_stage_inference.csv")
    deferred = read_csv(args.pilot_dir / "deferred_junctions.csv")
    movements = read_csv(args.pilot_dir / "signal_movements.csv")
    windows = read_csv(args.pilot_dir / "signal_group_stage_windows.csv")
    stages = read_csv(args.pilot_dir / "junction_stage_mapping.csv")
    conflicts = read_csv(args.pilot_dir / "movement_conflicts.csv")
    capacities = read_csv(args.pilot_dir / "capacity_deconvolution_audit.csv")

    require(build_summary["pilot_version"] == "pilot_v2_diagram_inferred", "Wrong pilot version")
    require(len(inferences) == build_summary["diagram_junction_count"] == 8, "Diagram audit count mismatch")
    require(len(deferred) == build_summary["deferred_junction_count"] == 7, "Deferred count mismatch")
    active_ids = {
        row["signal_junction_id"]
        for row in inferences
        if row["activation_status"] == "active_high_confidence"
    }
    require(active_ids == {"TS_K006"}, f"Unexpected active junction set: {active_ids}")
    require(
        {row["signal_junction_id"] for row in movements} == active_ids,
        "A deferred junction leaked into executable movements",
    )
    require(
        all(row["represented_turn_classes"] == "ahead|left|right" for row in movements),
        "An active movement contains an unaudited turn class",
    )
    require(
        all("u_turn" not in row["movement_representation"] for row in movements),
        "An active U-turn was emitted",
    )

    group_stages: dict[str, set[str]] = {}
    for row in movements:
        labels = split_labels(row["green_stage_labels"])
        previous = group_stages.setdefault(row["signal_group_id"], labels)
        require(previous == labels, f"Inconsistent stages within group {row['signal_group_id']}")
    for row in conflicts:
        shared = split_labels(row["shared_green_stage_labels"])
        blocks = row["blocks_shared_green"].lower() == "true"
        require(not (blocks and shared), "A blocking pair shares a green stage")

    stage_lookup = {row["stage_label"]: split_labels(row["signal_group_ids"]) for row in stages}
    for group, labels in group_stages.items():
        for label in labels:
            require(group in stage_lookup[label], f"Stage mapping omits group {group} from {label}")
    require(set(stage_lookup) == {"A", "B", "C"}, "TS_K006 must retain observed stages A/B/C")

    controlled_links = {row["approach_link_id"] for row in capacities}
    source_nodes, source_links = network_tables(args.source_network)
    pilot_nodes, pilot_links = network_tables(
        args.pilot_dir / "network_signal_capacity_deconvolved.xml.gz"
    )
    require(source_nodes == pilot_nodes, "Pilot network changed node IDs or coordinates")
    require(source_links.keys() == pilot_links.keys(), "Pilot network changed link membership")
    capacity_by_link = {row["approach_link_id"]: row for row in capacities}
    changed_capacity_links: set[str] = set()
    for link_id, source in source_links.items():
        pilot = pilot_links[link_id]
        for key, value in source.items():
            if key == "capacity" and link_id in controlled_links:
                continue
            require(pilot.get(key) == value, f"Unexpected network change {link_id} {key}")
        if pilot["capacity"] != source["capacity"]:
            changed_capacity_links.add(link_id)
        if link_id in controlled_links:
            audit = capacity_by_link[link_id]
            require(
                abs(float(source["capacity"]) - float(audit["current_capacity_veh_h"])) < 1e-6,
                f"Source capacity mismatch for {link_id}",
            )
            require(
                abs(float(pilot["capacity"]) - float(audit["pilot_network_capacity_veh_h"])) < 1e-6,
                f"Pilot capacity mismatch for {link_id}",
            )
    require(changed_capacity_links == controlled_links, "Unexpected capacity change set")

    window_lookup = {
        (row["signal_system_id"], row["period"], row["signal_group_id"]): row
        for row in windows
    }
    period_summaries: dict[str, dict[str, int]] = {}
    minimum_event_intergreen = 10**9
    for period in ("am", "pm"):
        directory = args.pilot_dir / f"matsim_{period}"
        systems_root = parse_xml(directory / "signal_systems.xml").getroot()
        groups_root = parse_xml(directory / "signal_groups.xml").getroot()
        control_root = parse_xml(directory / "signal_control.xml").getroot()
        amber_root = parse_xml(directory / "amber_times.xml").getroot()
        intergreen_root = parse_xml(directory / "intergreen_times.xml").getroot()
        systems = children(systems_root, "signalSystem")
        signals = children(systems_root, "signal")
        groups = children(groups_root, "signalGroup")
        plans = children(control_root, "signalPlan")
        settings = children(control_root, "signalGroupSettings")
        require(len(systems) == len(active_ids), f"{period}: signal system count mismatch")
        require(len(signals) == len(movements), f"{period}: signal count mismatch")
        require(len(groups) == len(group_stages), f"{period}: group count mismatch")
        require(len(plans) == len(active_ids), f"{period}: plan count mismatch")
        require(len(settings) == len(group_stages), f"{period}: setting count mismatch")

        movement_lookup = {(row["signal_system_id"], row["signal_id"]): row for row in movements}
        for system in systems:
            system_id = system.get("id")
            for signal in [item for item in system.iter() if local_name(item) == "signal"]:
                row = movement_lookup[(system_id, signal.get("id"))]
                require(signal.get("linkIdRef") == row["from_link_id"], "Signal link mismatch")
                turning_refs = [
                    item.get("refId") for item in signal.iter() if local_name(item) == "toLink"
                ]
                require(turning_refs == [row["to_link_id"]], "Turning restriction mismatch")
                require(
                    source_links[row["from_link_id"]]["to"] == source_links[row["to_link_id"]]["from"],
                    "Non-adjacent compiled movement",
                )
                require(
                    source_links[row["from_link_id"]]["from"] != source_links[row["to_link_id"]]["to"],
                    "Compiled movement is a direct U-turn",
                )

        for control_system in children(control_root, "signalSystem"):
            system_id = control_system.get("refId")
            plan = next(item for item in control_system.iter() if local_name(item) == "signalPlan")
            cycle = int(next(item for item in plan.iter() if local_name(item) == "cycleTime").get("sec"))
            for setting in [item for item in plan.iter() if local_name(item) == "signalGroupSettings"]:
                group_id = setting.get("refId")
                expected = window_lookup[(system_id, period, group_id)]
                onset = int(next(item for item in setting.iter() if local_name(item) == "onset").get("sec"))
                dropping = int(next(item for item in setting.iter() if local_name(item) == "dropping").get("sec"))
                require(onset == int(expected["green_onset_s"]), "Onset mismatch")
                require(dropping == int(expected["green_dropping_s"]), "Dropping mismatch")
                require(cycle == int(expected["cycle_s"]), "Cycle mismatch")

        defaults = next(item for item in amber_root.iter() if local_name(item) == "globalDefaults")
        amber = int(next(item for item in defaults.iter() if local_name(item) == "amber").get("seconds"))
        red_amber = int(next(item for item in defaults.iter() if local_name(item) == "redAmber").get("seconds"))
        require(amber == 3, "Amber must be 3 seconds")
        require(red_amber == 2, "Red-amber must be 2 seconds")
        intergreens = children(intergreen_root, "beginningSignalGroup")
        require(all(int(item.get("timeSeconds")) >= 5 for item in intergreens), "Intergreen below 5 seconds")

        system_windows = [row for row in windows if row["period"] == period]
        for ending in system_windows:
            for beginning in system_windows:
                if ending["signal_group_id"] == beginning["signal_group_id"]:
                    continue
                if not split_labels(ending["green_stage_labels"]).isdisjoint(
                    split_labels(beginning["green_stage_labels"])
                ):
                    continue
                beginning_onset = int(beginning["green_onset_s"])
                if beginning_onset <= int(ending["green_onset_s"]):
                    beginning_onset += int(ending["cycle_s"])
                event_gap = beginning_onset + red_amber - int(ending["green_dropping_s"]) - amber
                # Only the chronological next non-overlapping group is a real
                # transition; negative values here refer to a later cycle.
                if event_gap >= 0:
                    minimum_event_intergreen = min(minimum_event_intergreen, event_gap)

        period_summaries[period] = {
            "systems": len(systems),
            "signals": len(signals),
            "groups": len(groups),
            "plans": len(plans),
            "settings": len(settings),
            "intergreen_pairs": len(intergreens),
        }

    require(minimum_event_intergreen >= 5, "Event-level intergreen below 5 seconds")
    summary = {
        "status": "validated",
        "pilot_version": "pilot_v2_diagram_inferred",
        "diagram_junctions": len(inferences),
        "active_junctions": len(active_ids),
        "deferred_junctions": len(deferred),
        "controlled_approach_links": len(controlled_links),
        "signal_movements": len(movements),
        "signal_groups": len(group_stages),
        "capacity_only_network_changes": len(changed_capacity_links),
        "blocking_shared_stage_conflicts": 0,
        "minimum_event_level_intergreen_s": minimum_event_intergreen,
        "periods": period_summaries,
        "production_adoption_status": "not_adopted_static_pilot_only",
    }
    (args.pilot_dir / "pilot_validation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
