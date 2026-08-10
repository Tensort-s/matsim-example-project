#!/usr/bin/env python3
"""Validate the Hong Kong eight-junction MATSim signal pilot without hashes."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
from pathlib import Path

from lxml import etree as ET


REPO_ROOT = Path(__file__).resolve().parents[3]
FORMAL_PROJECT_ROOT = Path(
    os.environ.get("MATSIM_PROJECT_ROOT", r"F:\Matsim\matsim-example-project")
)
UPSTREAM_ROOT = FORMAL_PROJECT_ROOT if FORMAL_PROJECT_ROOT.exists() else REPO_ROOT
DEFAULT_PILOT = (
    REPO_ROOT
    / "data/transit/hongkong/processed/hong_kong_traffic_signals_2026_pilot_v1"
)
DEFAULT_SOURCE_NETWORK = (
    UPSTREAM_ROOT
    / "data/transit/hongkong/processed"
    / "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_"
    "ferry_core_v1_cap010/network.xml.gz"
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


def event_level_intergreen_seconds(
    ending: dict[str, str], beginning: dict[str, str], cycle_s: int
) -> int:
    """Return MATSim's red-to-green interval for consecutive plan stages."""
    beginning_onset = int(beginning["green_onset_s"])
    if int(beginning["stage_start_s"]) <= int(ending["stage_start_s"]):
        beginning_onset += cycle_s
    return (
        beginning_onset
        + int(beginning["red_amber_s"])
        - int(ending["green_dropping_s"])
        - int(ending["amber_s"])
    )


def main() -> int:
    args = parse_args()
    required_files = [
        args.pilot_dir / "signal_movements.csv",
        args.pilot_dir / "movement_conflicts.csv",
        args.pilot_dir / "capacity_deconvolution_audit.csv",
        args.pilot_dir / "observed_timing_evidence.csv",
        args.pilot_dir / "network_signal_capacity_deconvolved.xml.gz",
    ]
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

    movements = read_csv(args.pilot_dir / "signal_movements.csv")
    conflicts = read_csv(args.pilot_dir / "movement_conflicts.csv")
    capacities = read_csv(args.pilot_dir / "capacity_deconvolution_audit.csv")
    timings = read_csv(args.pilot_dir / "observed_timing_evidence.csv")
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
                f"Pilot saturation capacity mismatch for {link_id}",
            )
    require(
        changed_capacity_links == controlled_links,
        "Capacity deconvolution changed a different link set than the audited approaches",
    )

    require(
        all(
            row["blocks_shared_green"].lower() != "true"
            or row["same_stage"].lower() != "true"
            for row in conflicts
        ),
        "A blocking movement conflict shares a stage",
    )
    timing_lookup = {
        (row["signal_junction_id"], row["period"], row["stage_label"]): row
        for row in timings
    }
    timing_groups: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in timings:
        timing_groups.setdefault(
            (row["signal_junction_id"], row["period"]), []
        ).append(row)
    event_intergreens: list[int] = []
    for (junction_id, period), rows in timing_groups.items():
        ordered = sorted(rows, key=lambda row: int(row["stage_start_s"]))
        cycle_s = int(ordered[0]["cycle_s"])
        for index, ending in enumerate(ordered):
            beginning = ordered[(index + 1) % len(ordered)]
            actual = event_level_intergreen_seconds(ending, beginning, cycle_s)
            require(
                actual >= 5,
                f"Event-level intergreen below 5 seconds for {junction_id} "
                f"{period} {ending['stage_label']}->{beginning['stage_label']}: {actual}",
            )
            event_intergreens.append(actual)

    period_summaries: dict[str, dict[str, int]] = {}
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
        require(len(systems) == 8, f"{period}: expected 8 systems")
        require(len(signals) == len(movements), f"{period}: signal count mismatch")
        require(len(plans) == 8, f"{period}: expected one plan per system")

        signal_rows = {(row["signal_system_id"], row["signal_id"]): row for row in movements}
        for system in systems:
            system_id = system.get("id")
            for signal in [item for item in system.iter() if local_name(item) == "signal"]:
                row = signal_rows[(system_id, signal.get("id"))]
                require(signal.get("linkIdRef") == row["from_link_id"], "Signal link mismatch")
                turning_refs = [
                    item.get("refId")
                    for item in signal.iter()
                    if local_name(item) == "toLink"
                ]
                require(turning_refs == [row["to_link_id"]], "Turning restriction mismatch")
                require(
                    source_links[row["from_link_id"]]["to"]
                    == source_links[row["to_link_id"]]["from"],
                    "Non-adjacent compiled movement",
                )

        for control_system in children(control_root, "signalSystem"):
            system_id = control_system.get("refId")
            controller = next(
                item for item in control_system.iter()
                if local_name(item) == "signalSystemController"
            )
            plan = next(item for item in controller.iter() if local_name(item) == "signalPlan")
            cycle_element = next(item for item in plan.iter() if local_name(item) == "cycleTime")
            cycle = int(cycle_element.get("sec"))
            for setting in [item for item in plan.iter() if local_name(item) == "signalGroupSettings"]:
                group_id = setting.get("refId")
                stage = group_id.removeprefix("stage_")
                evidence = timing_lookup[(system_id, period, stage)]
                onset = next(item for item in setting.iter() if local_name(item) == "onset")
                dropping = next(item for item in setting.iter() if local_name(item) == "dropping")
                require(int(onset.get("sec")) == int(evidence["green_onset_s"]), "Onset mismatch")
                require(int(dropping.get("sec")) == int(evidence["green_dropping_s"]), "Dropping mismatch")
                require(int(evidence["cycle_s"]) == cycle, "Cycle mismatch")

        defaults = next(item for item in amber_root.iter() if local_name(item) == "globalDefaults")
        amber_values = [item for item in defaults.iter() if local_name(item) == "amber"]
        red_amber_values = [item for item in defaults.iter() if local_name(item) == "redAmber"]
        require(amber_values and int(amber_values[0].get("seconds")) == 3, "Amber must be 3 seconds")
        require(red_amber_values and int(red_amber_values[0].get("seconds")) == 2, "Red-amber must be 2 seconds")
        intergreens = children(intergreen_root, "beginningSignalGroup")
        require(all(int(item.get("timeSeconds")) >= 5 for item in intergreens), "Intergreen below 5 seconds")

        period_summaries[period] = {
            "systems": len(systems),
            "signals": len(signals),
            "groups": len(groups),
            "plans": len(plans),
            "settings": len(settings),
            "intergreen_pairs": len(intergreens),
        }

    summary = {
        "status": "validated",
        "junctions": 8,
        "controlled_approach_links": len(controlled_links),
        "signal_movements": len(movements),
        "capacity_only_network_changes": len(changed_capacity_links),
        "blocking_same_stage_conflicts": 0,
        "minimum_event_level_intergreen_s": min(event_intergreens),
        "hash_gate_used": False,
        "periods": period_summaries,
        "known_runtime_boundary": (
            "The active road network represents physical junctions as micro-node clusters; "
            "cross-node conflicts are enforced by fixed stage separation and static audit, "
            "not by a fabricated single-node MATSim conflictingDirections file."
        ),
    }
    (args.pilot_dir / "pilot_validation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
