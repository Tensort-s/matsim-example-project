#!/usr/bin/env python3
"""Build the auditable eight-junction Hong Kong traffic-signal pilot.

This builder deliberately separates location evidence, observed-partial timing,
geometry-inferred stage mapping, movement control, and approach-capacity
deconvolution.  It never promotes the eight public examples to a full-day or
Hong Kong-wide observed controller programme.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import os
import re
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from lxml import etree as ET


REPO_ROOT = Path(__file__).resolve().parents[3]
FORMAL_PROJECT_ROOT = Path(
    os.environ.get("MATSIM_PROJECT_ROOT", r"F:\Matsim\matsim-example-project")
)
UPSTREAM_ROOT = FORMAL_PROJECT_ROOT if FORMAL_PROJECT_ROOT.exists() else REPO_ROOT

DEFAULT_REGISTRY = (
    REPO_ROOT
    / "data/transit/hongkong/processed/hong_kong_traffic_signal_registry_2026_v1"
)
DEFAULT_NETWORK = (
    UPSTREAM_ROOT
    / "data/transit/hongkong/processed"
    / "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_"
    "ferry_core_v1_cap010/network.xml.gz"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "data/transit/hongkong/processed/hong_kong_traffic_signals_2026_pilot_v1"
)

AMBER_SECONDS = 3
RED_AMBER_SECONDS = 2
MINIMUM_INTERGREEN_SECONDS = 5
# MATSim adds amber after a configured dropping time and red+amber before a
# configured onset.  The controller gap therefore needs this conversion to
# produce the required red-to-green intergreen in runtime events.
CONTROLLER_ONSET_GAP_SECONDS = (
    MINIMUM_INTERGREEN_SECONDS + AMBER_SECONDS - RED_AMBER_SECONDS
)
LANE_WIDTH_M = 3.25
INTERNAL_LINK_MAX_M = 45.0
MAX_INTERNAL_RADIUS_M = 75.0
APPROACH_CLUSTER_TOLERANCE_DEG = 24.0


EVIDENCE = (
    ("TS_K006", "Nathan Road / Jordan Road", 130, (64, 34, 32), (64, 34, 32)),
    (
        "TS_K008",
        "Nathan Road / Gascoigne Road / Kansu Street",
        120,
        (39, 41, 40),
        (35, 44, 41),
    ),
    ("TS_K005", "Nathan Road / Austin Road", 130, (37, 47, 46), (33, 51, 46)),
    (
        "TS_K118",
        "Austin Road / Cox's Road / Pine Tree Hill Road",
        130,
        (52, 26, 21, 31),
        (54, 23, 22, 31),
    ),
    (
        "TS_K024",
        "Austin Road / Chatham Road South / Cheong Wan Road",
        130,
        (34, 39, 44, 13),
        (32, 44, 39, 15),
    ),
    (
        "TS_K101",
        "Jordan Road / Gascoigne Road / Queen Elizabeth Hospital Road",
        130,
        (27, 18, 64, 21),
        (27, 18, 64, 21),
    ),
    ("TS_K201", "Jordan Road / Cox's Road", 130, (33, 46, 20, 31), (33, 46, 20, 31)),
    ("TS_K025", "Gascoigne Road / Wylie Road", 130, (37, 55, 38), (29, 68, 33)),
)


@dataclass(frozen=True)
class Node:
    node_id: str
    x: float
    y: float


@dataclass
class Link:
    link_id: str
    from_node: str
    to_node: str
    length_m: float
    freespeed_m_s: float
    capacity_veh_h: float
    lanes: float
    modes: frozenset[str]
    element: ET._Element


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry-dir", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--network", type=Path, default=DEFAULT_NETWORK)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def write_csv(path: Path, rows: Iterable[dict[str, object]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def open_binary(path: Path):
    return gzip.open(path, "rb") if path.suffix == ".gz" else path.open("rb")


def parse_network(path: Path) -> tuple[ET._ElementTree, dict[str, Node], dict[str, Link]]:
    with open_binary(path) as stream:
        tree = ET.parse(stream)
    root = tree.getroot()
    nodes = {
        element.get("id"): Node(
            element.get("id"), float(element.get("x")), float(element.get("y"))
        )
        for element in root.find("nodes")
    }
    links: dict[str, Link] = {}
    for element in root.find("links"):
        modes = frozenset(filter(None, (element.get("modes") or "").split(",")))
        link = Link(
            link_id=element.get("id"),
            from_node=element.get("from"),
            to_node=element.get("to"),
            length_m=float(element.get("length")),
            freespeed_m_s=float(element.get("freespeed")),
            capacity_veh_h=float(element.get("capacity")),
            lanes=float(element.get("permlanes")),
            modes=modes,
            element=element,
        )
        links[link.link_id] = link
    return tree, nodes, links


def bearing_degrees(a: Node, b: Node) -> float:
    return math.degrees(math.atan2(b.y - a.y, b.x - a.x)) % 360.0


def angular_distance(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def signed_turn_degrees(in_bearing: float, out_bearing: float) -> float:
    return (out_bearing - in_bearing + 180.0) % 360.0 - 180.0


def turn_class(angle: float) -> str:
    if abs(angle) >= 150.0:
        return "u_turn"
    if angle > 35.0:
        return "left"
    if angle < -35.0:
        return "right"
    return "ahead"


def mean_bearing(values: Sequence[float]) -> float:
    x = sum(math.cos(math.radians(value)) for value in values)
    y = sum(math.sin(math.radians(value)) for value in values)
    return math.degrees(math.atan2(y, x)) % 360.0


def cluster_bearings(link_ids: Sequence[str], links: dict[str, Link], nodes: dict[str, Node]) -> list[list[str]]:
    entries = sorted(
        (
            bearing_degrees(nodes[links[link_id].from_node], nodes[links[link_id].to_node]),
            link_id,
        )
        for link_id in link_ids
    )
    clusters: list[list[tuple[float, str]]] = []
    for bearing, link_id in entries:
        best_index = None
        best_distance = math.inf
        for index, cluster in enumerate(clusters):
            distance = angular_distance(bearing, mean_bearing([item[0] for item in cluster]))
            if distance <= APPROACH_CLUSTER_TOLERANCE_DEG and distance < best_distance:
                best_index = index
                best_distance = distance
        if best_index is None:
            clusters.append([(bearing, link_id)])
        else:
            clusters[best_index].append((bearing, link_id))

    # Join a wrap-around pair near 0/360 if the greedy ordering split it.
    if len(clusters) > 1:
        first = mean_bearing([item[0] for item in clusters[0]])
        last = mean_bearing([item[0] for item in clusters[-1]])
        if angular_distance(first, last) <= APPROACH_CLUSTER_TOLERANCE_DEG:
            clusters[0] = clusters[-1] + clusters[0]
            clusters.pop()
    clusters.sort(key=lambda cluster: mean_bearing([item[0] for item in cluster]))
    return [[item[1] for item in cluster] for cluster in clusters]


def internal_nodes_for_junction(
    centroid: tuple[float, float],
    seed_ids: set[str],
    nodes: dict[str, Node],
    links: dict[str, Link],
) -> tuple[set[str], float]:
    missing = seed_ids.difference(nodes)
    if missing:
        raise ValueError(f"Registry nodes missing from network: {sorted(missing)}")
    cx, cy = centroid
    seed_radius = max(math.hypot(nodes[node_id].x - cx, nodes[node_id].y - cy) for node_id in seed_ids)
    radius = min(MAX_INTERNAL_RADIUS_M, max(30.0, seed_radius + 12.0))
    nearby = {
        node_id
        for node_id, node in nodes.items()
        if node_id.startswith("road_") and math.hypot(node.x - cx, node.y - cy) <= radius
    }
    adjacency: dict[str, set[str]] = defaultdict(set)
    for link in links.values():
        if (
            "car" in link.modes
            and link.length_m <= INTERNAL_LINK_MAX_M
            and link.from_node in nearby
            and link.to_node in nearby
        ):
            adjacency[link.from_node].add(link.to_node)
            adjacency[link.to_node].add(link.from_node)
    accepted: set[str] = set()
    queue = deque(seed_ids)
    while queue:
        node_id = queue.popleft()
        if node_id in accepted or node_id not in nearby:
            continue
        accepted.add(node_id)
        queue.extend(adjacency[node_id].difference(accepted))
    return accepted, radius


def reachable_exits(
    first_link: Link,
    internal_nodes: set[str],
    outgoing: dict[str, list[Link]],
) -> list[Link]:
    if first_link.to_node not in internal_nodes:
        return [first_link]
    exits: dict[str, Link] = {}
    queue = deque([(first_link.to_node, frozenset({first_link.from_node}))])
    seen: set[tuple[str, frozenset[str]]] = set()
    while queue:
        node_id, visited = queue.popleft()
        state = (node_id, visited)
        if state in seen:
            continue
        seen.add(state)
        if len(visited) > 12:
            continue
        for link in outgoing.get(node_id, []):
            if "car" not in link.modes or link.to_node in visited:
                continue
            if link.to_node not in internal_nodes:
                exits[link.link_id] = link
            else:
                queue.append((link.to_node, visited | {node_id}))
    return sorted(exits.values(), key=lambda link: link.link_id)


def saturation_flow(lanes: float) -> float:
    whole_lanes = max(1, int(round(lanes)))
    nearside = 1940.0 + 100.0 * (LANE_WIDTH_M - 3.25)
    other = 2080.0 + 100.0 * (LANE_WIDTH_M - 3.25)
    return nearside + max(0, whole_lanes - 1) * other


def merge_compatible_clusters(
    clusters: list[list[str]],
    stage_count: int,
    links: dict[str, Link],
    nodes: dict[str, Node],
) -> list[list[str]]:
    result = [list(cluster) for cluster in clusters]
    while len(result) > stage_count:
        candidates: list[tuple[float, int, int]] = []
        for left in range(len(result)):
            left_bearing = mean_bearing(
                [bearing_degrees(nodes[links[item].from_node], nodes[links[item].to_node]) for item in result[left]]
            )
            for right in range(left + 1, len(result)):
                right_bearing = mean_bearing(
                    [bearing_degrees(nodes[links[item].from_node], nodes[links[item].to_node]) for item in result[right]]
                )
                opposition_error = abs(180.0 - angular_distance(left_bearing, right_bearing))
                if opposition_error <= 25.0:
                    candidates.append((opposition_error, left, right))
        if not candidates:
            raise ValueError(
                f"{len(result)} approach clusters cannot be conservatively represented by {stage_count} stages"
            )
        _, left, right = min(candidates)
        result[left].extend(result[right])
        result.pop(right)
    return result


def color_conflict_graph(
    movements: Sequence[dict[str, object]],
    conflicting_pairs: Sequence[tuple[str, str]],
    stage_count: int,
) -> dict[str, int]:
    """Assign every movement to a conflict-free inferred stage.

    The public sheet supplies the number and duration of stages, but not a
    machine-readable movement mapping.  A bounded graph-colouring step is safer
    than silently grouping whole approaches.  Preferred colours preserve the
    initial bearing ordering where it is compatible with the conflict graph.
    """

    movement_by_id = {str(row["signal_id"]): row for row in movements}
    adjacency: dict[str, set[str]] = {signal_id: set() for signal_id in movement_by_id}
    for left, right in conflicting_pairs:
        adjacency[left].add(right)
        adjacency[right].add(left)
    assigned: dict[str, int] = {}

    def choose_next() -> str:
        unassigned = [signal_id for signal_id in movement_by_id if signal_id not in assigned]
        return max(
            unassigned,
            key=lambda signal_id: (
                len({assigned[other] for other in adjacency[signal_id] if other in assigned}),
                len(adjacency[signal_id]),
                signal_id,
            ),
        )

    def search() -> bool:
        if len(assigned) == len(movement_by_id):
            return True
        signal_id = choose_next()
        blocked = {assigned[other] for other in adjacency[signal_id] if other in assigned}
        preferred = int(movement_by_id[signal_id]["preferred_stage_index"])
        choices = [preferred] + [index for index in range(stage_count) if index != preferred]
        for stage_index in choices:
            if stage_index in blocked:
                continue
            assigned[signal_id] = stage_index
            if search():
                return True
            assigned.pop(signal_id)
        return False

    if not search():
        raise ValueError(
            f"Movement conflict graph requires more than {stage_count} stages; "
            "the observed-partial timing cannot be compiled safely"
        )
    return assigned


def main() -> int:
    args = parse_args()
    required = (
        args.registry_dir / "hong_kong_signal_junctions.csv",
        args.registry_dir / "signal_controlled_link_candidates.csv",
        args.network,
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing required inputs: {missing}")

    tree, nodes, links = parse_network(args.network)
    outgoing: dict[str, list[Link]] = defaultdict(list)
    incoming: dict[str, list[Link]] = defaultdict(list)
    for link in links.values():
        if "car" not in link.modes:
            continue
        outgoing[link.from_node].append(link)
        incoming[link.to_node].append(link)

    junction_rows = {
        row["signal_junction_id"]: row
        for row in read_csv(args.registry_dir / "hong_kong_signal_junctions.csv")
    }
    evidence_ids = {row[0] for row in EVIDENCE}
    if evidence_ids.difference(junction_rows):
        raise ValueError(f"Pilot registry IDs missing: {sorted(evidence_ids.difference(junction_rows))}")

    timing_rows: list[dict[str, object]] = []
    movement_rows: list[dict[str, object]] = []
    stage_rows: list[dict[str, object]] = []
    capacity_rows: list[dict[str, object]] = []
    conflict_rows: list[dict[str, object]] = []
    pedestrian_rows: list[dict[str, object]] = []
    controlled_links: set[str] = set()
    per_junction_summary: dict[str, dict[str, object]] = {}

    for junction_id, name, cycle, am_durations, pm_durations in EVIDENCE:
        if sum(am_durations) != cycle or sum(pm_durations) != cycle:
            raise ValueError(f"Observed stage durations do not sum to cycle for {junction_id}")
        for period, durations in (("am", am_durations), ("pm", pm_durations)):
            start = 0
            for index, duration in enumerate(durations):
                label = chr(ord("A") + index)
                timing_rows.append(
                    {
                        "signal_junction_id": junction_id,
                        "junction_name": name,
                        "period": period,
                        "evidence_class": "observed_partial",
                        "cycle_s": cycle,
                        "stage_label": label,
                        "stage_duration_s": duration,
                        "stage_start_s": start,
                        "green_onset_s": start + CONTROLLER_ONSET_GAP_SECONDS,
                        "green_dropping_s": start + duration,
                        "amber_s": AMBER_SECONDS,
                        "red_amber_s": RED_AMBER_SECONDS,
                        "activation_window_status": "missing_not_inferred",
                        "offset_status": "missing_not_inferred",
                    }
                )
                start += duration

        registry = junction_rows[junction_id]
        pedestrian_rows.append(
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
        )
        centroid = (float(registry["x_epsg32650"]), float(registry["y_epsg32650"]))
        seed_ids = set(filter(None, registry["mapped_network_node_ids"].split("|")))
        internal_nodes, radius = internal_nodes_for_junction(
            centroid, seed_ids, nodes, links
        )
        approach_links = sorted(
            {
                link.link_id
                for node_id in internal_nodes
                for link in incoming.get(node_id, [])
                if link.from_node not in internal_nodes
            }
        )
        if not approach_links:
            raise ValueError(f"No boundary approach links found for {junction_id}")
        stage_count = len(am_durations)
        clusters = cluster_bearings(approach_links, links, nodes)
        preferred_stage: dict[str, int] = {}
        for index, cluster in enumerate(clusters):
            for link_id in cluster:
                preferred_stage[link_id] = index % stage_count

        junction_movements: list[dict[str, object]] = []
        for approach_index, approach_id in enumerate(approach_links, start=1):
            approach = links[approach_id]
            next_links = [
                link
                for link in outgoing.get(approach.to_node, [])
                if "car" in link.modes and link.to_node != approach.from_node
            ]
            if not next_links:
                raise ValueError(f"Controlled approach {approach_id} has no legal next Car link")
            controlled_links.add(approach_id)
            current_capacity = approach.capacity_veh_h
            selected_saturation = saturation_flow(approach.lanes)
            approach.element.set("capacity", f"{selected_saturation:.6f}")
            capacity_rows.append(
                {
                    "signal_junction_id": junction_id,
                    "approach_link_id": approach_id,
                    "current_capacity_veh_h": round(current_capacity, 6),
                    "lanes": approach.lanes,
                    "assumed_lane_width_m": LANE_WIDTH_M,
                    "gradient_adjustment": "not_available_zero_adjustment",
                    "tpdm_saturation_flow_pcu_h": round(selected_saturation, 6),
                    "pilot_network_capacity_veh_h": round(selected_saturation, 6),
                    "capacity_treatment": "replace_final_approach_with_saturation_proxy",
                    "double_count_guard": "signal_plan_supplies_green_ratio",
                    "evidence_class": "tpdm_calculated_proxy",
                }
            )
            in_bearing = bearing_degrees(nodes[approach.from_node], nodes[approach.to_node])
            for movement_index, next_link in enumerate(sorted(next_links, key=lambda item: item.link_id), start=1):
                exits = reachable_exits(next_link, internal_nodes, outgoing)
                exit_bearings = [
                    bearing_degrees(nodes[exit_link.from_node], nodes[exit_link.to_node])
                    for exit_link in exits
                ]
                if exit_bearings:
                    classes = sorted({turn_class(signed_turn_degrees(in_bearing, bearing)) for bearing in exit_bearings})
                    movement_class = classes[0] if len(classes) == 1 else "compound:" + "|".join(classes)
                    out_bearing = mean_bearing(exit_bearings)
                    angle = signed_turn_degrees(in_bearing, out_bearing)
                else:
                    movement_class = "unresolved_internal_exit"
                    out_bearing = bearing_degrees(nodes[next_link.from_node], nodes[next_link.to_node])
                    angle = signed_turn_degrees(in_bearing, out_bearing)
                signal_id = f"sig_{approach_index:02d}_{movement_index:02d}"
                row = {
                    "signal_junction_id": junction_id,
                    "signal_system_id": junction_id,
                    "signal_id": signal_id,
                    "signal_group_id": "pending_graph_coloring",
                    "stage_label": "pending_graph_coloring",
                    "preferred_stage_index": preferred_stage[approach_id],
                    "node_id": approach.to_node,
                    "from_link_id": approach_id,
                    "to_link_id": next_link.link_id,
                    "reachable_exit_link_ids": "|".join(link.link_id for link in exits),
                    "approach_bearing_deg": round(in_bearing, 3),
                    "exit_bearing_deg": round(out_bearing, 3),
                    "turn_angle_deg": round(angle, 3),
                    "turn_class": movement_class,
                    "movement_evidence": "network_topology_and_geometry_inferred",
                    "stage_mapping_evidence": "geometry_inferred_requires_diagram_review",
                }
                movement_rows.append(row)
                junction_movements.append(row)

        junction_conflicts: list[
            tuple[dict[str, object], dict[str, object], bool, bool, str]
        ] = []
        conflicting_pairs: list[tuple[str, str]] = []
        for left_index, left in enumerate(junction_movements):
            for right in junction_movements[left_index + 1 :]:
                if left["from_link_id"] == right["from_link_id"]:
                    conflict = False
                    blocks_shared_green = False
                    reason = "same_approach_diverging"
                else:
                    difference = angular_distance(
                        float(left["approach_bearing_deg"]),
                        float(right["approach_bearing_deg"]),
                    )
                    left_turn = str(left["turn_class"])
                    right_turn = str(right["turn_class"])
                    if difference < 35.0:
                        conflict = False
                        blocks_shared_green = False
                        reason = "parallel_approaches"
                    elif difference > 145.0 and "right" not in left_turn and "right" not in right_turn:
                        conflict = False
                        blocks_shared_green = False
                        reason = "opposing_non_right_movements"
                    elif difference > 145.0:
                        conflict = True
                        blocks_shared_green = False
                        reason = "opposing_permitted_yield_proxy_requires_runtime_review"
                    else:
                        conflict = True
                        blocks_shared_green = True
                        reason = "conservative_geometric_conflict"
                junction_conflicts.append(
                    (left, right, conflict, blocks_shared_green, reason)
                )
                if blocks_shared_green:
                    conflicting_pairs.append((str(left["signal_id"]), str(right["signal_id"])))

        colors = color_conflict_graph(junction_movements, conflicting_pairs, stage_count)
        for movement in junction_movements:
            label = chr(ord("A") + colors[str(movement["signal_id"])])
            movement["stage_label"] = label
            movement["signal_group_id"] = f"stage_{label}"
            movement.pop("preferred_stage_index")

        for index in range(stage_count):
            label = chr(ord("A") + index)
            stage_movements = [row for row in junction_movements if row["stage_label"] == label]
            stage_rows.append(
                {
                    "signal_junction_id": junction_id,
                    "stage_label": label,
                    "approach_link_ids": "|".join(sorted({str(row["from_link_id"]) for row in stage_movements})),
                    "signal_ids": "|".join(sorted(str(row["signal_id"]) for row in stage_movements)),
                    "mapping_evidence": (
                        "geometry_inferred_conflict_graph_requires_diagram_review"
                        if stage_movements
                        else "observed_stage_unrepresented_in_road_pilot"
                    ),
                    "represented_in_road_pilot": bool(stage_movements),
                }
            )

        for left, right, conflict, blocks_shared_green, reason in junction_conflicts:
            same_stage = left["stage_label"] == right["stage_label"]
            conflict_rows.append(
                {
                    "signal_junction_id": junction_id,
                    "signal_id_a": left["signal_id"],
                    "signal_id_b": right["signal_id"],
                    "conflict": conflict,
                    "blocks_shared_green": blocks_shared_green,
                    "same_stage": same_stage,
                    "reason": reason,
                }
            )
            if blocks_shared_green and same_stage:
                raise ValueError(
                    f"Unsafe inferred stage mapping at {junction_id}: "
                    f"{left['signal_id']} and {right['signal_id']} conflict in stage {left['stage_label']}"
                )

        per_junction_summary[junction_id] = {
            "junction_name": name,
            "cycle_s": cycle,
            "stage_count": stage_count,
            "internal_node_count": len(internal_nodes),
            "internal_radius_m": round(radius, 3),
            "approach_link_count": len(approach_links),
            "approach_cluster_count": len(clusters),
            "signal_movement_count": len(junction_movements),
        }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(
        args.output_dir / "observed_timing_evidence.csv",
        timing_rows,
        list(timing_rows[0]),
    )
    write_csv(
        args.output_dir / "junction_stage_mapping.csv",
        stage_rows,
        list(stage_rows[0]),
    )
    write_csv(
        args.output_dir / "signal_movements.csv",
        movement_rows,
        list(movement_rows[0]),
    )
    write_csv(
        args.output_dir / "movement_conflicts.csv",
        conflict_rows,
        list(conflict_rows[0]),
    )
    write_csv(
        args.output_dir / "capacity_deconvolution_audit.csv",
        capacity_rows,
        list(capacity_rows[0]),
    )
    write_csv(
        args.output_dir / "pedestrian_phase_audit.csv",
        pedestrian_rows,
        list(pedestrian_rows[0]),
    )

    network_output = args.output_dir / "network_signal_capacity_deconvolved.xml.gz"
    with gzip.open(network_output, "wb", compresslevel=6) as stream:
        tree.write(stream, encoding="utf-8", xml_declaration=True, doctype='<!DOCTYPE network SYSTEM "http://www.matsim.org/files/dtd/network_v2.dtd">')

    summary = {
        "status": "pilot_static_build_passed",
        "scope": "eight_observed_partial_junctions_only",
        "source_network": str(args.network),
        "junction_count": len(EVIDENCE),
        "controlled_approach_link_count": len(controlled_links),
        "signal_movement_count": len(movement_rows),
        "conflicting_movement_pair_count": sum(bool(row["conflict"]) for row in conflict_rows),
        "same_stage_blocking_conflict_count": sum(
            bool(row["blocks_shared_green"]) and bool(row["same_stage"])
            for row in conflict_rows
        ),
        "amber_s": AMBER_SECONDS,
        "red_amber_s": RED_AMBER_SECONDS,
        "minimum_intergreen_s": MINIMUM_INTERGREEN_SECONDS,
        "controller_onset_gap_s": CONTROLLER_ONSET_GAP_SECONDS,
        "stage_mapping_status": "geometry_inferred_requires_diagram_review",
        "activation_windows": "missing_not_inferred",
        "offsets": "missing_not_inferred",
        "runtime_conflict_file": "not_emitted_multi_node_junction_topology",
        "pedestrian_phase_status": "not_activated_missing_crossing_geometry",
        "per_junction": per_junction_summary,
    }
    (args.output_dir / "pilot_build_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
