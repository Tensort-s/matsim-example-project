#!/usr/bin/env python3
"""Build the diagram-audited Hong Kong traffic-signal pilot v2.

Unlike pilot v1, this builder never derives stage membership by colouring a
geometry conflict graph.  A junction is activated only when both the published
stage diagram and the current MATSim node/link topology support the same
movement boundary.  Diagram-readable but not yet representable junctions stay
in the audit tables and are not compiled into signals.
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Sequence

from build_hong_kong_traffic_signal_pilot_v1 import (
    AMBER_SECONDS,
    CONTROLLER_ONSET_GAP_SECONDS,
    DEFAULT_REGISTRY,
    EVIDENCE,
    LANE_WIDTH_M,
    MINIMUM_INTERGREEN_SECONDS,
    RED_AMBER_SECONDS,
    bearing_degrees,
    internal_nodes_for_junction,
    parse_network,
    read_csv,
    reachable_exits,
    saturation_flow,
    write_csv,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "data/transit/hongkong/processed/"
    "hong_kong_traffic_signals_2026_pilot_v2_diagram_inferred"
)
CURRENT_PHYSICAL_NETWORK = (
    REPO_ROOT
    / "data/transit/hongkong/processed/"
    "matsim_road_pt_school_bus_supply_2026_v6_adoption_ready/network.xml.gz"
)
DEFAULT_NETWORK = CURRENT_PHYSICAL_NETWORK
SOURCE_DIAGRAM = (
    "data/transit/hongkong/raw/traffic_signals_2026/"
    "source_documents/Signal timing and sequence F 02.pdf"
)


# This is deliberately an explicit, reviewable registry.  The descriptions do
# not drive MATSim compilation; only ACTIVE_MOVEMENTS below can do that.
DIAGRAM_INFERENCE = (
    {
        "signal_junction_id": "TS_K006",
        "junction_name": "Nathan Road / Jordan Road",
        "diagram_inference_confidence": "high",
        "network_expression_confidence": "high",
        "activation_status": "active_high_confidence",
        "stage_inference": (
            "A=Jordan Road both directions, all shown non-U-turn vehicle movements; "
            "B=Nathan Road northbound approach, all shown non-U-turn vehicle movements; "
            "C=Nathan Road southbound approach, all shown non-U-turn vehicle movements"
        ),
        "network_expression_note": (
            "Each published phase equals one complete approach bundle in the current "
            "micro-node topology; first internal connectors therefore reproduce the diagram."
        ),
    },
    {
        "signal_junction_id": "TS_K008",
        "junction_name": "Nathan Road / Gascoigne Road / Kansu Street",
        "diagram_inference_confidence": "medium_partial",
        "network_expression_confidence": "low",
        "activation_status": "deferred",
        "stage_inference": "Protected curved movements are visible, but not every arrow can be assigned unambiguously.",
        "network_expression_note": "Current first internal connectors fan out to movements belonging to different drawn phases.",
    },
    {
        "signal_junction_id": "TS_K005",
        "junction_name": "Nathan Road / Austin Road",
        "diagram_inference_confidence": "high",
        "network_expression_confidence": "low",
        "activation_status": "deferred",
        "stage_inference": "The diagram shows an eastbound straight/right movement continuing across adjacent stages B and C.",
        "network_expression_note": "The same first connector also admits the excluded left turn, so the protected overlap is not faithfully gateable.",
    },
    {
        "signal_junction_id": "TS_K118",
        "junction_name": "Austin Road / Cox's Road / Pine Tree Hill Road",
        "diagram_inference_confidence": "medium_high",
        "network_expression_confidence": "low",
        "activation_status": "deferred",
        "stage_inference": "Stage D appears to contain no vehicle arrow and may be pedestrian-only/all-red.",
        "network_expression_note": "Only three approach bundles are recovered from the current network while the diagram implies additional or ambiguous approach structure.",
    },
    {
        "signal_junction_id": "TS_K024",
        "junction_name": "Austin Road / Chatham Road South / Cheong Wan Road",
        "diagram_inference_confidence": "medium",
        "network_expression_confidence": "low",
        "activation_status": "deferred",
        "stage_inference": "Dense multi-arm arrow pattern; several protected movements require lane-level interpretation.",
        "network_expression_note": "Current topology cannot separate all diagram movements at the first controlled connector.",
    },
    {
        "signal_junction_id": "TS_K101",
        "junction_name": "Jordan Road / Gascoigne Road / Queen Elizabeth Hospital Road",
        "diagram_inference_confidence": "low_medium",
        "network_expression_confidence": "low",
        "activation_status": "deferred",
        "stage_inference": "Complex multi-arm diagram remains insufficient for a unique movement-to-stage transcription.",
        "network_expression_note": "Do not convert ambiguous arrows into approach-wide greens.",
    },
    {
        "signal_junction_id": "TS_K201",
        "junction_name": "Jordan Road / Cox's Road",
        "diagram_inference_confidence": "high",
        "network_expression_confidence": "low",
        "activation_status": "deferred",
        "stage_inference": "Stage D has vehicle movements; protected Cox/Jordan turns and adjacent-stage overlaps are visible.",
        "network_expression_note": "Protected turns share internal connectors with movements assigned to other stages.",
    },
    {
        "signal_junction_id": "TS_K025",
        "junction_name": "Gascoigne Road / Wylie Road",
        "diagram_inference_confidence": "low_medium",
        "network_expression_confidence": "low",
        "activation_status": "deferred",
        "stage_inference": "The available raster is not clear enough for an exact arrow-by-arrow stage mapping.",
        "network_expression_note": "Await a clearer first-party diagram or a lane/connector reconstruction.",
    },
)


# One row controls one MATSim first connector.  The reachable-exit list is an
# invariant: if upstream network construction changes its fan-out, v2 stops
# instead of silently changing what the signal permits.
ACTIVE_MOVEMENTS = (
    {
        "from_link_id": "road_104550_0_f",
        "to_link_id": "road_104660_0_r",
        "reachable_exit_link_ids": "road_104562_0_f|road_104564_0_f|road_104676_0_f",
        "signal_group_id": "phase_A_jordan_both_directions",
        "green_stage_labels": "A",
        "approach_description": "Jordan Road west-to-east approach",
    },
    {
        "from_link_id": "road_104673_0_f",
        "to_link_id": "road_104674_0_f",
        "reachable_exit_link_ids": "road_104562_0_f|road_104648_0_f|road_104676_0_f",
        "signal_group_id": "phase_A_jordan_both_directions",
        "green_stage_labels": "A",
        "approach_description": "Jordan Road east-to-west approach",
    },
    {
        "from_link_id": "road_104664_0_f",
        "to_link_id": "road_104563_0_f",
        "reachable_exit_link_ids": "road_104564_0_f|road_104648_0_f|road_104676_0_f",
        "signal_group_id": "phase_B_nathan_northbound",
        "green_stage_labels": "B",
        "approach_description": "Nathan Road south-to-north approach",
    },
    {
        "from_link_id": "road_104537_0_f",
        "to_link_id": "road_104675_0_r",
        "reachable_exit_link_ids": "road_104562_0_f|road_104564_0_f|road_104648_0_f",
        "signal_group_id": "phase_C_nathan_southbound",
        "green_stage_labels": "C",
        "approach_description": "Nathan Road north-to-south approach",
    },
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry-dir", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--network", type=Path, default=DEFAULT_NETWORK)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def split_stage_labels(value: str) -> tuple[str, ...]:
    labels = tuple(item.strip() for item in value.split("|") if item.strip())
    if not labels or len(labels) != len(set(labels)):
        raise ValueError(f"Invalid green stage labels: {value!r}")
    return labels


def derive_group_window(
    timing_rows: Sequence[dict[str, object]], green_stage_labels: str
) -> tuple[int, int, int]:
    """Return cycle, onset and dropping for one contiguous stage run."""
    by_label = {str(row["stage_label"]): row for row in timing_rows}
    labels = split_stage_labels(green_stage_labels)
    missing = set(labels).difference(by_label)
    if missing:
        raise ValueError(f"Unknown green stage labels: {sorted(missing)}")
    ordered = sorted(labels, key=lambda label: int(by_label[label]["stage_start_s"]))
    if tuple(ordered) != labels:
        raise ValueError(f"Green stages must be listed in chronological order: {labels}")
    for left, right in zip(ordered, ordered[1:]):
        left_end = int(by_label[left]["stage_start_s"]) + int(
            by_label[left]["stage_duration_s"]
        )
        if left_end != int(by_label[right]["stage_start_s"]):
            raise ValueError(f"Non-contiguous green stage window: {green_stage_labels}")
    cycle_values = {int(by_label[label]["cycle_s"]) for label in ordered}
    if len(cycle_values) != 1:
        raise ValueError(f"Stage window spans inconsistent cycles: {green_stage_labels}")
    onset = int(by_label[ordered[0]]["stage_start_s"]) + CONTROLLER_ONSET_GAP_SECONDS
    dropping = int(by_label[ordered[-1]]["stage_start_s"]) + int(
        by_label[ordered[-1]]["stage_duration_s"]
    )
    cycle = cycle_values.pop()
    if not 0 <= onset < dropping <= cycle:
        raise ValueError(
            f"Invalid controller window {onset}..{dropping} for cycle {cycle}"
        )
    return cycle, onset, dropping


def rows_by_period_for_junction(
    junction_id: str, name: str, cycle: int, am: Sequence[int], pm: Sequence[int]
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for period, durations in (("am", am), ("pm", pm)):
        if sum(durations) != cycle:
            raise ValueError(f"Stage durations do not sum to cycle for {junction_id} {period}")
        start = 0
        for index, duration in enumerate(durations):
            rows.append(
                {
                    "signal_junction_id": junction_id,
                    "junction_name": name,
                    "period": period,
                    "evidence_class": "observed_partial",
                    "cycle_s": cycle,
                    "stage_label": chr(ord("A") + index),
                    "stage_duration_s": duration,
                    "stage_start_s": start,
                    "amber_s": AMBER_SECONDS,
                    "red_amber_s": RED_AMBER_SECONDS,
                    "activation_window_status": "missing_not_inferred",
                    "offset_status": "missing_not_inferred_zero_for_pilot",
                }
            )
            start += duration
    return rows


def write_table(path: Path, rows: Iterable[dict[str, object]], fields: Sequence[str]) -> None:
    write_csv(path, rows, fields)


def main() -> int:
    args = parse_args()
    required = (
        args.registry_dir / "hong_kong_signal_junctions.csv",
        args.network,
        REPO_ROOT / SOURCE_DIAGRAM,
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing required inputs: {missing}")

    tree, nodes, links = parse_network(args.network)
    outgoing = defaultdict(list)
    incoming = defaultdict(list)
    for link in links.values():
        if "car" in link.modes:
            outgoing[link.from_node].append(link)
            incoming[link.to_node].append(link)

    registry = {
        row["signal_junction_id"]: row
        for row in read_csv(args.registry_dir / "hong_kong_signal_junctions.csv")
    }
    diagram_ids = {row["signal_junction_id"] for row in DIAGRAM_INFERENCE}
    if diagram_ids.difference(registry):
        raise ValueError(f"Diagram junctions missing from registry: {sorted(diagram_ids.difference(registry))}")

    active = next(row for row in DIAGRAM_INFERENCE if row["activation_status"] == "active_high_confidence")
    junction_id = str(active["signal_junction_id"])
    evidence = next(row for row in EVIDENCE if row[0] == junction_id)
    _, name, cycle, am_durations, pm_durations = evidence
    timing_rows = rows_by_period_for_junction(
        junction_id, name, cycle, am_durations, pm_durations
    )

    registry_row = registry[junction_id]
    centroid = (
        float(registry_row["x_epsg32650"]),
        float(registry_row["y_epsg32650"]),
    )
    seed_ids = set(filter(None, registry_row["mapped_network_node_ids"].split("|")))
    internal_nodes, internal_radius = internal_nodes_for_junction(
        centroid, seed_ids, nodes, links
    )

    movement_rows: list[dict[str, object]] = []
    capacity_rows: list[dict[str, object]] = []
    controlled_approaches: set[str] = set()
    for index, spec in enumerate(ACTIVE_MOVEMENTS, start=1):
        from_link = links.get(spec["from_link_id"])
        to_link = links.get(spec["to_link_id"])
        if from_link is None or to_link is None:
            raise ValueError(f"Audited movement links missing: {spec}")
        if from_link.to_node != to_link.from_node:
            raise ValueError(f"Audited movement is not adjacent: {spec}")
        if from_link.to_node not in internal_nodes:
            raise ValueError(f"Audited movement does not enter active junction: {spec}")
        if to_link.to_node not in internal_nodes:
            raise ValueError(f"Audited first connector exits internal junction immediately: {spec}")
        exits = reachable_exits(to_link, internal_nodes, outgoing)
        actual_exits = "|".join(link.link_id for link in exits)
        if actual_exits != spec["reachable_exit_link_ids"]:
            raise ValueError(
                f"Reachable exit set changed for {spec['from_link_id']} -> {spec['to_link_id']}: "
                f"expected {spec['reachable_exit_link_ids']}, got {actual_exits}"
            )
        reverse_link_ids = {
            link.link_id
            for link in outgoing.get(from_link.to_node, [])
            if link.to_node == from_link.from_node
        }
        if to_link.link_id in reverse_link_ids:
            raise ValueError(f"U-turn connector cannot be activated: {spec}")

        movement_rows.append(
            {
                "signal_junction_id": junction_id,
                "signal_system_id": junction_id,
                "signal_id": f"sig_{index:02d}",
                "signal_group_id": spec["signal_group_id"],
                "green_stage_labels": spec["green_stage_labels"],
                "node_id": from_link.to_node,
                "from_link_id": from_link.link_id,
                "to_link_id": to_link.link_id,
                "reachable_exit_link_ids": actual_exits,
                "approach_description": spec["approach_description"],
                "approach_bearing_deg": round(
                    bearing_degrees(nodes[from_link.from_node], nodes[from_link.to_node]), 3
                ),
                "movement_representation": "approach_bundle_all_non_uturn_movements",
                "represented_turn_classes": "ahead|left|right",
                "movement_evidence": "published_stage_diagram_plus_network_topology_audit",
                "stage_mapping_evidence": "diagram_inferred_high_confidence",
            }
        )

        if from_link.link_id not in controlled_approaches:
            controlled_approaches.add(from_link.link_id)
            current_capacity = from_link.capacity_veh_h
            selected_saturation = saturation_flow(from_link.lanes)
            from_link.element.set("capacity", f"{selected_saturation:.6f}")
            capacity_rows.append(
                {
                    "signal_junction_id": junction_id,
                    "approach_link_id": from_link.link_id,
                    "current_capacity_veh_h": round(current_capacity, 6),
                    "lanes": from_link.lanes,
                    "assumed_lane_width_m": LANE_WIDTH_M,
                    "gradient_adjustment": "not_available_zero_adjustment",
                    "tpdm_saturation_flow_pcu_h": round(selected_saturation, 6),
                    "pilot_network_capacity_veh_h": round(selected_saturation, 6),
                    "capacity_treatment": "replace_final_approach_with_saturation_proxy",
                    "double_count_guard": "signal_plan_supplies_green_ratio",
                    "evidence_class": "tpdm_calculated_proxy",
                }
            )

    group_windows: list[dict[str, object]] = []
    groups = {
        (str(row["signal_group_id"]), str(row["green_stage_labels"]))
        for row in movement_rows
    }
    for period in ("am", "pm"):
        period_timing = [row for row in timing_rows if row["period"] == period]
        for group_id, stage_labels in sorted(groups):
            group_cycle, onset, dropping = derive_group_window(period_timing, stage_labels)
            group_windows.append(
                {
                    "signal_junction_id": junction_id,
                    "signal_system_id": junction_id,
                    "signal_group_id": group_id,
                    "period": period,
                    "green_stage_labels": stage_labels,
                    "cycle_s": group_cycle,
                    "green_onset_s": onset,
                    "green_dropping_s": dropping,
                    "window_evidence": "derived_from_observed_stage_duration_and_diagram_membership",
                }
            )

    stage_rows: list[dict[str, object]] = []
    for label in ("A", "B", "C"):
        stage_groups = sorted(
            group_id for group_id, labels in groups if label in split_stage_labels(labels)
        )
        stage_signals = sorted(
            str(row["signal_id"])
            for row in movement_rows
            if label in split_stage_labels(str(row["green_stage_labels"]))
        )
        stage_rows.append(
            {
                "signal_junction_id": junction_id,
                "stage_label": label,
                "signal_group_ids": "|".join(stage_groups),
                "signal_ids": "|".join(stage_signals),
                "mapping_evidence": "diagram_inferred_high_confidence",
                "represented_in_road_pilot": bool(stage_groups),
                "empty_vehicle_stage_allowed": not bool(stage_groups),
            }
        )

    conflict_rows: list[dict[str, object]] = []
    for left_index, left in enumerate(movement_rows):
        for right in movement_rows[left_index + 1 :]:
            left_stages = set(split_stage_labels(str(left["green_stage_labels"])))
            right_stages = set(split_stage_labels(str(right["green_stage_labels"])))
            shared = sorted(left_stages.intersection(right_stages))
            same_group = left["signal_group_id"] == right["signal_group_id"]
            conflict_rows.append(
                {
                    "signal_junction_id": junction_id,
                    "signal_id_a": left["signal_id"],
                    "signal_id_b": right["signal_id"],
                    "shared_green_stage_labels": "|".join(shared),
                    "blocks_shared_green": not bool(shared),
                    "reason": (
                        "diagram_observed_simultaneous_same_phase"
                        if same_group
                        else "diagram_separates_movements_into_exclusive_phases"
                    ),
                }
            )

    deferred_rows = [
        {
            "signal_junction_id": row["signal_junction_id"],
            "junction_name": row["junction_name"],
            "diagram_inference_confidence": row["diagram_inference_confidence"],
            "network_expression_confidence": row["network_expression_confidence"],
            "deferral_reason": row["network_expression_note"],
            "required_next_evidence_or_change": (
                "lane-level connector reconstruction and diagram-to-link review"
            ),
        }
        for row in DIAGRAM_INFERENCE
        if row["activation_status"] == "deferred"
    ]
    pedestrian_rows = [
        {
            "signal_junction_id": junction_id,
            "junction_name": name,
            "crossing_geometry_status": "missing_not_inferred",
            "pedestrian_phase_status": "not_activated_in_vehicle_pilot",
            "ordinary_clearance_speed_m_s": 1.2,
            "accessible_clearance_speed_m_s": 0.9,
            "pushbutton_or_demand_logic_status": "missing_not_inferred",
            "production_adoption_blocker": True,
        }
    ]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_table(args.output_dir / "diagram_stage_inference.csv", DIAGRAM_INFERENCE, list(DIAGRAM_INFERENCE[0]))
    write_table(args.output_dir / "deferred_junctions.csv", deferred_rows, list(deferred_rows[0]))
    write_table(args.output_dir / "observed_timing_evidence.csv", timing_rows, list(timing_rows[0]))
    write_table(args.output_dir / "signal_movements.csv", movement_rows, list(movement_rows[0]))
    write_table(args.output_dir / "signal_group_stage_windows.csv", group_windows, list(group_windows[0]))
    write_table(args.output_dir / "junction_stage_mapping.csv", stage_rows, list(stage_rows[0]))
    write_table(args.output_dir / "movement_conflicts.csv", conflict_rows, list(conflict_rows[0]))
    write_table(args.output_dir / "capacity_deconvolution_audit.csv", capacity_rows, list(capacity_rows[0]))
    write_table(args.output_dir / "pedestrian_phase_audit.csv", pedestrian_rows, list(pedestrian_rows[0]))

    network_output = args.output_dir / "network_signal_capacity_deconvolved.xml.gz"
    with gzip.open(network_output, "wb", compresslevel=6) as stream:
        tree.write(
            stream,
            encoding="utf-8",
            xml_declaration=True,
            doctype='<!DOCTYPE network SYSTEM "http://www.matsim.org/files/dtd/network_v2.dtd">',
        )

    summary = {
        "status": "pilot_v2_static_build_passed",
        "pilot_version": "pilot_v2_diagram_inferred",
        "scope": "one_high_confidence_executable_junction_plus_seven_deferred_audits",
        "source_network": str(args.network),
        "source_stage_diagram": SOURCE_DIAGRAM,
        "source_stage_diagram_pages": "1-2",
        "diagram_junction_count": len(DIAGRAM_INFERENCE),
        "active_junction_count": 1,
        "deferred_junction_count": len(deferred_rows),
        "controlled_approach_link_count": len(controlled_approaches),
        "signal_movement_count": len(movement_rows),
        "signal_group_count": len(groups),
        "amber_s": AMBER_SECONDS,
        "red_amber_s": RED_AMBER_SECONDS,
        "minimum_intergreen_s": MINIMUM_INTERGREEN_SECONDS,
        "controller_onset_gap_s": CONTROLLER_ONSET_GAP_SECONDS,
        "stage_mapping_status": "diagram_inferred_high_confidence_only",
        "u_turn_policy": "excluded_unless_explicitly_drawn_none_active",
        "activation_windows": "missing_not_inferred_static_am_pm_pilot_only",
        "offsets": "missing_not_inferred_zero_for_pilot",
        "pedestrian_phase_status": "not_activated_missing_crossing_geometry",
        "active_junction": {
            "signal_junction_id": junction_id,
            "junction_name": name,
            "cycle_s": cycle,
            "stage_count": 3,
            "internal_node_count": len(internal_nodes),
            "internal_radius_m": round(internal_radius, 3),
        },
    }
    (args.output_dir / "pilot_build_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
