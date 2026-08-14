#!/usr/bin/env python3
"""Validate a Hong Kong demand-ranked or all-expressed 96-bin TOD candidate."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from lxml import etree as ET

from build_hong_kong_traffic_signal_pilot_v1 import parse_network, read_csv


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CANDIDATE = REPO_ROOT / "data/transit/hongkong/processed/hong_kong_traffic_signals_2026_v3_tod_proxy_top100"
DEFAULT_NETWORK = REPO_ROOT / "data/transit/hongkong/processed/matsim_road_pt_school_bus_supply_2026_v6_adoption_ready/network.xml.gz"
EXPECTED_BINS = 96
BIN_SECONDS = 900
DAY_SECONDS = 86400
CLEARANCE_SECONDS = 6


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-dir", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--network", type=Path, default=DEFAULT_NETWORK)
    parser.add_argument("--expected-systems", type=int, default=None)
    return parser.parse_args()


def local_name(element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def descendants(root, name: str):
    return [element for element in root.iter() if local_name(element) == name]


def validate(args: argparse.Namespace) -> dict:
    csv_names = [
        "selected_junctions.csv", "stage_templates.csv", "executable_signal_movements.csv",
        "approach_conflict_proxy.csv", "tod_plan_assignments.csv", "tod_group_windows.csv",
        "vehicle_class_stage_demand_15min.csv", "capacity_deconvolution_audit.csv",
    ]
    xml_names = ["signal_systems.xml", "signal_groups.xml", "signal_control.xml", "amber_times.xml", "intergreen_times.xml"]
    required = [args.candidate_dir / name for name in csv_names]
    required += [args.candidate_dir / "matsim" / name for name in xml_names]
    required.append(args.candidate_dir / "network_signal_capacity_deconvolved.xml.gz")
    required.append(args.candidate_dir / "tod_qa_summary.json")
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing candidate outputs: " + ", ".join(missing))

    selected = read_csv(args.candidate_dir / "selected_junctions.csv")
    stages = read_csv(args.candidate_dir / "stage_templates.csv")
    signals = read_csv(args.candidate_dir / "executable_signal_movements.csv")
    plans = read_csv(args.candidate_dir / "tod_plan_assignments.csv")
    windows = read_csv(args.candidate_dir / "tod_group_windows.csv")
    class_rows = read_csv(args.candidate_dir / "vehicle_class_stage_demand_15min.csv")
    capacity_rows = read_csv(args.candidate_dir / "capacity_deconvolution_audit.csv")
    qa = json.loads((args.candidate_dir / "tod_qa_summary.json").read_text(encoding="utf-8"))
    expected_systems = args.expected_systems if args.expected_systems is not None else int(qa["junction_count"])
    if len(selected) != expected_systems or len(plans) != expected_systems * EXPECTED_BINS:
        raise AssertionError("System/96-bin cardinality failed")
    selected_ids = {row["signal_junction_id"] for row in selected}
    if len(selected_ids) != expected_systems:
        raise AssertionError("Selected junction IDs are not unique")
    expected_ranks = list(range(1, expected_systems + 1))
    if sorted(int(row["demand_rank"]) for row in selected) != expected_ranks:
        raise AssertionError("Demand ranks are not contiguous")
    if any(row.get("diagram_special_treatment") != "false" for row in selected):
        raise AssertionError("A public diagram junction received special treatment")
    diagram_rows = [row for row in selected if row.get("public_diagram_validation_member") == "true"]
    if qa.get("selection_scope") == "all_expressed" and len(diagram_rows) != 8:
        raise AssertionError("All eight public diagram junctions must use the unified expressed rule")

    stage_ids = {row["stage_id"] for row in stages}
    group_ids = {row["signal_group_id"] for row in stages}
    if len(stage_ids) != len(stages) or len(group_ids) != len(stages):
        raise AssertionError("Stage/group IDs are not unique")
    signal_ids = {(row["signal_system_id"], row["signal_id"]) for row in signals}
    if len(signal_ids) != len(signals):
        raise AssertionError("Signal IDs are not unique within system")
    for row in signals:
        if row["signal_junction_id"] not in selected_ids or row["stage_id"] not in stage_ids or row["signal_group_id"] not in group_ids:
            raise AssertionError("Signal references unknown junction/stage/group")
        if "u_turn" in row["movement_types"].split("|"):
            raise AssertionError("Executable TOD signal contains a U-turn")
    controlled_links_by_system: dict[str, set[str]] = defaultdict(set)
    for row in signals:
        controlled_links_by_system[row["from_link_id"]].add(row["signal_system_id"])
    cross_system_control_links = {
        link_id: systems for link_id, systems in controlled_links_by_system.items()
        if len(systems) > 1
    }
    if cross_system_control_links:
        raise AssertionError("A physical incoming link is controlled by multiple signal systems")

    _, network_nodes, network_links = parse_network(args.network)
    for row in signals:
        incoming = network_links.get(row["from_link_id"])
        outgoing = network_links.get(row["to_link_id"])
        if incoming is None or outgoing is None or incoming.to_node != outgoing.from_node:
            raise AssertionError("Controlled link pair is missing or non-adjacent")
        if incoming.from_node == outgoing.to_node:
            raise AssertionError("Controlled link pair is a U-turn")
    _, candidate_nodes, candidate_links = parse_network(args.candidate_dir / "network_signal_capacity_deconvolved.xml.gz")
    if len(capacity_rows) != len({row["approach_id"] for row in signals}):
        raise AssertionError("Capacity audit does not cover every controlled approach exactly once")
    changed_ids = set()
    for row in capacity_rows:
        link_id = row["from_link_id"]
        changed_ids.add(link_id)
        if link_id not in candidate_links or float(candidate_links[link_id].capacity_veh_h) != float(row["candidate_network_capacity_veh_h"]):
            raise AssertionError("Candidate network capacity does not match audit")
    if set(network_links) != set(candidate_links):
        raise AssertionError("Candidate network changed link IDs")
    if set(network_nodes) != set(candidate_nodes):
        raise AssertionError("Candidate network changed node IDs")
    changed_topology_or_attributes = [
        link_id for link_id, source in network_links.items()
        if (
            source.from_node,
            source.to_node,
            source.length_m,
            source.freespeed_m_s,
            source.lanes,
            source.modes,
        ) != (
            candidate_links[link_id].from_node,
            candidate_links[link_id].to_node,
            candidate_links[link_id].length_m,
            candidate_links[link_id].freespeed_m_s,
            candidate_links[link_id].lanes,
            candidate_links[link_id].modes,
        )
    ]
    if changed_topology_or_attributes:
        raise AssertionError("Candidate network changed topology or non-capacity link attributes")
    unexpected_changes = [
        link_id for link_id in network_links
        if link_id not in changed_ids and network_links[link_id].capacity_veh_h != candidate_links[link_id].capacity_veh_h
    ]
    if unexpected_changes:
        raise AssertionError("Candidate network changed uncontrolled capacities")

    groups_by_system: dict[str, set[str]] = defaultdict(set)
    for row in stages:
        groups_by_system[row["signal_system_id"]].add(row["signal_group_id"])
    if qa.get("selection_scope") == "all_expressed" and any(
        len(groups) < 2 for groups in groups_by_system.values()
    ):
        raise AssertionError("Active candidate contains a signal system without a competing vehicle stage")
    plans_by_system: dict[str, list[dict]] = defaultdict(list)
    for row in plans:
        plans_by_system[row["signal_system_id"]].append(row)
    windows_by_plan: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in windows:
        windows_by_plan[(row["signal_system_id"], row["plan_id"])].append(row)

    for system_id, local_plans in plans_by_system.items():
        ordered = sorted(local_plans, key=lambda row: int(row["time_bin_index"]))
        boundary_shift = int(ordered[0]["start_time_s"])
        if not 0 <= boundary_shift < BIN_SECONDS:
            raise AssertionError(f"Invalid TOD boundary shift in {system_id}")
        if [int(row["time_bin_index"]) for row in ordered] != list(range(EXPECTED_BINS)):
            raise AssertionError(f"Missing/duplicate TOD bin in {system_id}")
        for index, row in enumerate(ordered):
            cycle = int(row["cycle_s"])
            expected_start = (index * BIN_SECONDS + boundary_shift) % DAY_SECONDS
            if int(row["start_time_s"]) != expected_start:
                raise AssertionError(f"Wrong plan start in {system_id} bin {index}")
            expected_end = ((index + 1) * BIN_SECONDS + boundary_shift) % DAY_SECONDS
            if int(row["end_time_s"]) != expected_end or BIN_SECONDS % cycle or DAY_SECONDS % cycle:
                raise AssertionError(f"Invalid plan boundary/cycle in {system_id} bin {index}")
            local_windows = sorted(windows_by_plan[(system_id, row["plan_id"])], key=lambda item: int(item["stage_index"]))
            if {item["signal_group_id"] for item in local_windows} != groups_by_system[system_id]:
                raise AssertionError(f"Plan does not reference every group in {system_id} bin {index}")
            cursor = 0
            for window in local_windows:
                onset = int(window["green_onset_s"])
                dropping = int(window["green_dropping_s"])
                if onset != cursor or dropping - onset < 7:
                    raise AssertionError(f"Invalid ordered stage windows in {system_id} bin {index}")
                cursor = dropping + CLEARANCE_SECONDS
            if cursor != cycle:
                raise AssertionError(f"Clearance windows do not fill cycle in {system_id} bin {index}")
        cycle_grades = [{60: 0, 75: 1, 90: 2, 100: 3}[int(row["cycle_s"])] for row in ordered]
        if any(abs(left - right) > 1 for left, right in zip(cycle_grades, cycle_grades[1:])):
            raise AssertionError(f"Adjacent cycle grade jump in {system_id}")

    expected_class_rows = len(windows) * 6
    if len(class_rows) != expected_class_rows:
        raise AssertionError(f"Vehicle-class audit has {len(class_rows)} rows, expected {expected_class_rows}")
    taxi_rows = [row for row in class_rows if row["vehicle_class"] == "taxi"]
    if any(row["physical_network_status"] != "missing_from_physical_network" for row in taxi_rows):
        raise AssertionError("Taxi missing-physical-demand status was lost")

    systems_root = ET.parse(args.candidate_dir / "matsim/signal_systems.xml").getroot()
    groups_root = ET.parse(args.candidate_dir / "matsim/signal_groups.xml").getroot()
    control_root = ET.parse(args.candidate_dir / "matsim/signal_control.xml").getroot()
    xml_systems = descendants(systems_root, "signalSystem")
    xml_signals = descendants(systems_root, "signal")
    xml_groups = descendants(groups_root, "signalGroup")
    xml_plans = descendants(control_root, "signalPlan")
    if (len(xml_systems), len(xml_signals), len(xml_groups), len(xml_plans)) != (expected_systems, len(signals), len(stages), len(plans)):
        raise AssertionError("Compiled MATSim XML cardinality differs from design CSV")

    summary = {
        "status": "pass",
        "junction_count": len(selected),
        "selection_scope": qa.get("selection_scope", "top_demand"),
        "public_diagram_junction_count": len(diagram_rows),
        "diagram_special_treatment_count": 0,
        "plans_per_junction": EXPECTED_BINS,
        "plan_count": len(plans),
        "stage_count": len(stages),
        "signal_count": len(signals),
        "group_window_count": len(windows),
        "cycle_distribution": dict(sorted(Counter(int(row["cycle_s"]) for row in plans).items())),
        "timing_status_distribution": dict(Counter(row["timing_status"] for row in plans)),
        "stage_count_distribution": dict(sorted(Counter(len(value) for value in groups_by_system.values()).items())),
        "missing_or_nonadjacent_controlled_turns": 0,
        "active_u_turns": 0,
        "cross_system_control_links": 0,
        "active_single_stage_systems": sum(len(groups) == 1 for groups in groups_by_system.values()),
        "missing_plan_group_references": 0,
        "adjacent_cycle_grade_violations": 0,
        "controlled_approach_capacity_change_count": len(capacity_rows),
        "network_topology_or_id_modified": False,
        "candidate_network_capacity_modified": True,
        "production_adopted": False,
    }
    ownership_path = args.candidate_dir / "cross_system_control_ownership_audit.csv"
    deactivation_path = args.candidate_dir / "junction_deactivation_audit.csv"
    priority_path = args.candidate_dir / "priority_junction_override_audit.csv"
    if qa.get("selection_scope") == "all_expressed":
        if not ownership_path.is_file() or not deactivation_path.is_file() or not priority_path.is_file():
            raise AssertionError("All-expressed corrective audit tables are missing")
        summary["cross_system_control_overlap_count_resolved"] = len(read_csv(ownership_path))
        deactivations = read_csv(deactivation_path)
        summary["no_competing_vehicle_stage_deactivation_count"] = sum(
            row["deactivation_status"] == "deactivated_no_competing_vehicle_stage"
            for row in deactivations
        )
        priority_rows = read_csv(priority_path)
        summary["priority_junction_review_count"] = len(priority_rows)
        summary["priority_junction_stage_override_count"] = sum(
            row["implementation_status"] == "stage_override_applied"
            for row in priority_rows
        )
    (args.candidate_dir / "tod_validation_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return summary


def main() -> None:
    summary = validate(parse_args())
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
