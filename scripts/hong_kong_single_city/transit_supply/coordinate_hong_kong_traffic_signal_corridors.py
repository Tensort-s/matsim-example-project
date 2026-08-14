#!/usr/bin/env python3
"""Build a fail-closed, auditable short-block corridor-offset candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
from collections import defaultdict, deque
from pathlib import Path

from build_hong_kong_traffic_signal_pilot_v1 import parse_network, read_csv, write_csv
from build_hong_kong_traffic_signal_tod_proxy_top100 import (
    REPO_ROOT,
    TIME_BIN_COUNT,
    circular_axis_distance,
)


DEFAULT_SOURCE = REPO_ROOT / (
    "data/transit/hongkong/processed/"
    "hong_kong_traffic_signals_2026_v3_tod_proxy_all_expressed_road_hotspot_v1_candidate9"
)
DEFAULT_STAGE1 = REPO_ROOT / (
    "data/transit/hongkong/processed/"
    "hong_kong_traffic_signals_2026_v3_tpdm_proxy_stage1_road_hotspot_v1_candidate8"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/transit/hongkong/processed/"
    "hong_kong_traffic_signals_2026_v3_tod_proxy_all_expressed_road_hotspot_v1_candidate10_corridor"
)

MIN_BLOCK_M = 25.0
MIN_SHORT_STORAGE_BLOCK_M = 5.0
MAX_BLOCK_M = 250.0
MAX_DIRECTION_CHANGE_DEG = 25.0
DOMINANCE_RATIO = 1.25
MIN_DIRECTIONAL_MEAN_Q = 400.0
MIN_SEGMENT_Q = 100.0
MIN_CONSECUTIVE_BINS = 2
MIN_COORDINATED_BINS = 4
OFFSET_SEARCH_RADIUS_S = 3
MAX_MEAN_ALIGNMENT_ERROR_S = 10.0
MAX_ALIGNMENT_ERROR_S = 18.0
STANDARD_START_LOSS_S = 2.0
STANDARD_DOWNSTREAM_LEAD_S = 2.0
SHORT_BLOCK_DOWNSTREAM_LEAD_S = 3.0
CONTROLLER_CLEARANCE_S = 6
COORDINATED_VEHICLE_CLASSES = {"private_car", "bus", "gmb", "school_bus", "other_road_vehicle"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-candidate", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--stage1-dir", type=Path, default=DEFAULT_STAGE1)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def link_bearing(link, nodes) -> float:
    left = nodes[link.from_node]
    right = nodes[link.to_node]
    return math.degrees(math.atan2(right.y - left.y, right.x - left.x)) % 360.0


def turn_distance(left: float, right: float) -> float:
    delta = abs((right - left + 180.0) % 360.0 - 180.0)
    return delta


def bin_index(label: str) -> int:
    hour, minute = (int(value) for value in label.split("-", 1)[0].split(":"))
    return ((hour * 60 + minute) // 15) % TIME_BIN_COUNT


def retain_consecutive_runs(active: list[bool], minimum: int = MIN_CONSECUTIVE_BINS) -> list[bool]:
    """Remove isolated TOD bins, including runs that wrap midnight."""
    if all(active) or not any(active):
        return list(active)
    doubled = active + active
    keep = [False] * len(active)
    index = 0
    while index < len(doubled):
        if not doubled[index]:
            index += 1
            continue
        end = index
        while end < len(doubled) and doubled[end]:
            end += 1
        if end - index >= minimum:
            for position in range(index, end):
                keep[position % len(active)] = True
        index = end
    return keep


def transition_compatible(old_windows: list[dict], old_cycle: int, old_offset: int,
                          new_windows: list[dict], new_cycle: int, new_offset: int) -> bool:
    """Check a plan boundary with the same event ordering used by MATSim."""
    horizon = 3 * max(old_cycle, new_cycle)
    state: set[str] = set()
    last_drop: int | None = None
    for second in range(-horizon, horizon + 1):
        windows = old_windows if second < 0 else new_windows
        cycle = old_cycle if second < 0 else new_cycle
        offset = old_offset if second < 0 else new_offset
        phase = second % cycle
        drops = [row["signal_group_id"] for row in windows if (offset + int(row["green_dropping_s"])) % cycle == phase]
        onsets = [row["signal_group_id"] for row in windows if (offset + int(row["green_onset_s"])) % cycle == phase]
        for group in drops:
            state.discard(group)
            last_drop = second
        for group in onsets:
            if second >= -max(old_cycle, new_cycle):
                if state or (last_drop is not None and second - last_drop < CONTROLLER_CLEARANCE_S):
                    return False
            state.add(group)
        if second >= -max(old_cycle, new_cycle) and len(state) > 1:
            return False
    return True


def choose_safe_offsets(desired: list[int], cycles: list[int], windows: list[list[dict]]) -> list[int] | None:
    """Find offsets near corridor targets while preserving every TOD boundary."""
    candidates = []
    for target, cycle in zip(desired, cycles):
        if target == 0:
            candidates.append([0])
        else:
            candidates.append(sorted({(target + delta) % cycle for delta in range(-OFFSET_SEARCH_RADIUS_S, OFFSET_SEARCH_RADIUS_S + 1)}))
    best_result = None
    best_cost = math.inf
    for first in candidates[0]:
        costs = {first: min((first - desired[0]) % cycles[0], (desired[0] - first) % cycles[0])}
        parents: list[dict[int, int]] = []
        for index in range(1, TIME_BIN_COUNT):
            next_costs: dict[int, float] = {}
            parent: dict[int, int] = {}
            for current in candidates[index]:
                deviation = min((current - desired[index]) % cycles[index], (desired[index] - current) % cycles[index])
                for previous, previous_cost in costs.items():
                    if not transition_compatible(
                        windows[index - 1], cycles[index - 1], previous,
                        windows[index], cycles[index], current,
                    ):
                        continue
                    cost = previous_cost + deviation
                    if cost < next_costs.get(current, math.inf):
                        next_costs[current] = cost
                        parent[current] = previous
            if not next_costs:
                costs = {}
                break
            costs = next_costs
            parents.append(parent)
        if not costs:
            continue
        for last, cost in costs.items():
            if cost >= best_cost or not transition_compatible(
                windows[-1], cycles[-1], last, windows[0], cycles[0], first
            ):
                continue
            result = [last]
            for parent in reversed(parents):
                result.append(parent[result[-1]])
            result.reverse()
            best_result = result
            best_cost = cost
    return best_result


def choose_safe_constant_offset(
    desired: list[int], active: list[bool], cycles: list[int], windows: list[list[dict]],
    force_zero: bool = False,
) -> tuple[int, float, float] | None:
    """Choose one daily offset so 15-minute plan boundaries never phase-jump."""
    if not any(active):
        return None
    candidates = [0] if force_zero else range(min(cycles))
    best = None
    for offset in candidates:
        if any(offset >= cycle for cycle in cycles):
            continue
        if any(
            not transition_compatible(
                windows[index - 1], cycles[index - 1], offset,
                windows[index], cycles[index], offset,
            )
            for index in range(TIME_BIN_COUNT)
        ):
            continue
        errors = [
            min((offset - desired[index]) % cycles[index], (desired[index] - offset) % cycles[index])
            for index in range(TIME_BIN_COUNT) if active[index]
        ]
        mean_error = sum(errors) / len(errors)
        maximum_error = max(errors)
        score = (mean_error, maximum_error, offset)
        if best is None or score < best[0]:
            best = (score, offset, mean_error, maximum_error)
    return None if best is None else (best[1], best[2], best[3])


def build(args: argparse.Namespace) -> dict:
    source = args.source_candidate.resolve()
    stage1 = args.stage1_dir.resolve()
    output = args.output_dir.resolve()
    required = [
        source / "executable_signal_movements.csv",
        source / "tod_plan_assignments.csv",
        source / "tod_group_windows.csv",
        source / "network_signal_capacity_deconvolved.xml.gz",
        stage1 / "signal_movements.csv",
        stage1 / "movement_demand_15min.csv",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing corridor inputs: " + ", ".join(missing))
    if output.exists():
        raise FileExistsError(f"Refusing existing corridor output: {output}")

    _, nodes, links = parse_network(source / "network_signal_capacity_deconvolved.xml.gz")
    outgoing: dict[str, list] = defaultdict(list)
    for link in links.values():
        if {"car", "bus", "gmb"} & set(link.modes):
            outgoing[link.from_node].append(link)

    signal_rows = read_csv(source / "executable_signal_movements.csv")
    controlled_by_link: dict[str, list[dict]] = defaultdict(list)
    for row in signal_rows:
        controlled_by_link[row["from_link_id"]].append(row)
    if any(len({row["signal_system_id"] for row in rows}) != 1 for rows in controlled_by_link.values()):
        raise AssertionError("Source candidate has cross-system controlled links")

    stage1_movements = {row["movement_id"]: row for row in read_csv(stage1 / "signal_movements.csv")}
    q_by_movement: dict[str, list[float]] = defaultdict(lambda: [0.0] * TIME_BIN_COUNT)
    for row in read_csv(stage1 / "movement_demand_15min.csv"):
        q_by_movement[row["movement_id"]][bin_index(row["time_bin"])] += float(row["tpdm_pcu_per_hour"])

    exclusions: list[dict] = []
    connection_candidates: dict[tuple[str, str, str, str], dict] = {}
    for signal in signal_rows:
        upstream_system = signal["signal_system_id"]
        for movement_id in signal["physical_movement_ids"].split("|"):
            movement = stage1_movements.get(movement_id)
            if movement is None or movement["movement_type"] != "ahead":
                continue
            seed_ids = [value for value in movement["internal_link_sequence"].split("|") if value]
            if movement["exit_link_id"] and (not seed_ids or seed_ids[-1] != movement["exit_link_id"]):
                seed_ids.append(movement["exit_link_id"])
            path_ids: list[str] = []
            distance = 0.0
            travel_time = 0.0
            previous_bearing = link_bearing(links[signal["from_link_id"]], nodes)
            current = None
            target = None
            failure = "no_downstream_signal_within_250m"
            for seed_id in seed_ids:
                candidate = links.get(seed_id)
                if candidate is None:
                    failure = "missing_stage1_path_link"
                    break
                if current is not None and current.to_node != candidate.from_node:
                    failure = "noncontiguous_stage1_ahead_path"
                    break
                current = candidate
                path_ids.append(current.link_id)
                distance += current.length_m
                travel_time += current.length_m / max(current.freespeed_m_s, 0.1)
                previous_bearing = link_bearing(current, nodes)
                local = controlled_by_link.get(current.link_id, [])
                if local and local[0]["signal_system_id"] != upstream_system:
                    target = local[0]
                    break
                if distance > MAX_BLOCK_M:
                    failure = "downstream_signal_beyond_250m"
                    break
            visited = set(path_ids)
            while target is None and current is not None and distance <= MAX_BLOCK_M:
                choices = []
                for candidate in outgoing[current.to_node]:
                    if candidate.link_id in visited or candidate.to_node == current.from_node:
                        continue
                    angle = turn_distance(previous_bearing, link_bearing(candidate, nodes))
                    if angle <= MAX_DIRECTION_CHANGE_DEG:
                        choices.append((angle, candidate.link_id, candidate))
                if len(choices) != 1:
                    failure = "ambiguous_continuation" if choices else "no_straight_continuation"
                    break
                _, _, current = choices[0]
                visited.add(current.link_id)
                path_ids.append(current.link_id)
                distance += current.length_m
                travel_time += current.length_m / max(current.freespeed_m_s, 0.1)
                previous_bearing = link_bearing(current, nodes)
                local = controlled_by_link.get(current.link_id, [])
                if local and local[0]["signal_system_id"] != upstream_system:
                    target = local[0]
                    break
            if target is None:
                exclusions.append({
                    "scope": "directed_ahead_path", "upstream_signal_system_id": upstream_system,
                    "downstream_signal_system_id": "", "reason": failure,
                    "distance_m": round(distance, 3), "detail": movement_id,
                })
                continue
            downstream_system = target["signal_system_id"]
            if distance < MIN_SHORT_STORAGE_BLOCK_M:
                exclusions.append({
                    "scope": "directed_ahead_path", "upstream_signal_system_id": upstream_system,
                    "downstream_signal_system_id": downstream_system,
                    "reason": "block_shorter_than_5m_geometry_review", "distance_m": round(distance, 3),
                    "detail": movement_id,
                })
                continue
            if distance > MAX_BLOCK_M:
                continue
            upstream_node = links[signal["from_link_id"]].to_node
            downstream_node = links[target["from_link_id"]].to_node
            dx = nodes[downstream_node].x - nodes[upstream_node].x
            dy = nodes[downstream_node].y - nodes[upstream_node].y
            axis = math.degrees(math.atan2(dy, dx)) % 180.0
            key = (upstream_system, downstream_system, signal["signal_group_id"], target["signal_group_id"])
            row = connection_candidates.setdefault(key, {
                "upstream_signal_system_id": upstream_system,
                "downstream_signal_system_id": downstream_system,
                "upstream_signal_group_id": signal["signal_group_id"],
                "downstream_signal_group_id": target["signal_group_id"],
                "from_link_id": signal["from_link_id"], "to_controlled_link_id": target["from_link_id"],
                "path_link_ids": "|".join(path_ids), "block_length_m": distance,
                "freeflow_travel_time_s": travel_time, "axis_bearing_deg": axis,
                "block_policy": "short_storage_near_synchronous" if distance < MIN_BLOCK_M else "standard_travel_time_progression",
                "movement_ids": set(), "q": [0.0] * TIME_BIN_COUNT,
            })
            row["movement_ids"].add(movement_id)
            for index, value in enumerate(q_by_movement[movement_id]):
                row["q"][index] += value

    # A direction between the same systems must have one unambiguous group/path.
    by_direction: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in connection_candidates.values():
        by_direction[(row["upstream_signal_system_id"], row["downstream_signal_system_id"])].append(row)
    connections: dict[tuple[str, str], dict] = {}
    for direction, rows in sorted(by_direction.items()):
        if len(rows) != 1:
            exclusions.append({
                "scope": "directed_system_connection", "upstream_signal_system_id": direction[0],
                "downstream_signal_system_id": direction[1], "reason": "multiple_group_or_path_candidates",
                "distance_m": "", "detail": str(len(rows)),
            })
            continue
        connections[direction] = rows[0]

    pair_rows: dict[frozenset[str], dict] = {}
    for (left, right), row in connections.items():
        key = frozenset((left, right))
        pair = pair_rows.setdefault(key, {"systems": tuple(sorted(key)), "directions": {}, "axis": row["axis_bearing_deg"]})
        pair["directions"][(left, right)] = row
    pair_list = list(pair_rows.values())

    # Join aligned block pairs into maximal unbranched corridor candidates.
    pair_adjacency: dict[int, set[int]] = defaultdict(set)
    for left_index, left in enumerate(pair_list):
        for right_index in range(left_index + 1, len(pair_list)):
            right = pair_list[right_index]
            if not (set(left["systems"]) & set(right["systems"])):
                continue
            if circular_axis_distance(float(left["axis"]), float(right["axis"])) <= MAX_DIRECTION_CHANGE_DEG:
                pair_adjacency[left_index].add(right_index)
                pair_adjacency[right_index].add(left_index)
    pair_components = []
    unseen = set(range(len(pair_list)))
    while unseen:
        start = unseen.pop()
        component = {start}
        queue = deque([start])
        while queue:
            item = queue.popleft()
            for neighbour in pair_adjacency[item]:
                if neighbour in unseen:
                    unseen.remove(neighbour)
                    component.add(neighbour)
                    queue.append(neighbour)
        pair_components.append(component)

    plans = read_csv(source / "tod_plan_assignments.csv")
    plan_by_system_bin = {(row["signal_system_id"], int(row["time_bin_index"])): row for row in plans}
    windows_rows = read_csv(source / "tod_group_windows.csv")
    windows_by_system_bin: dict[tuple[str, int], list[dict]] = defaultdict(list)
    onset_by_system_bin_group = {}
    for row in windows_rows:
        key = (row["signal_system_id"], int(row["time_bin_index"]))
        windows_by_system_bin[key].append(row)
        onset_by_system_bin_group[(key[0], key[1], row["signal_group_id"])] = int(row["green_onset_s"])

    candidates = []
    for component_index, component in enumerate(pair_components, 1):
        pairs = [pair_list[index] for index in component]
        systems = sorted({system for pair in pairs for system in pair["systems"]})
        if len(systems) < 3:
            continue
        adjacency: dict[str, set[str]] = defaultdict(set)
        pair_by_nodes = {}
        for pair in pairs:
            left, right = pair["systems"]
            adjacency[left].add(right)
            adjacency[right].add(left)
            pair_by_nodes[frozenset((left, right))] = pair
        if any(len(values) > 2 for values in adjacency.values()):
            exclusions.append({
                "scope": "corridor_component", "upstream_signal_system_id": "",
                "downstream_signal_system_id": "", "reason": "branched_aligned_component",
                "distance_m": "", "detail": "|".join(systems),
            })
            continue
        endpoints = sorted(system for system in systems if len(adjacency[system]) == 1)
        if len(endpoints) != 2:
            exclusions.append({
                "scope": "corridor_component", "upstream_signal_system_id": "",
                "downstream_signal_system_id": "", "reason": "cyclic_or_non_linear_component",
                "distance_m": "", "detail": "|".join(systems),
            })
            continue
        order = [endpoints[0]]
        previous = None
        while len(order) < len(systems):
            choices = adjacency[order[-1]] - ({previous} if previous else set())
            if len(choices) != 1:
                break
            previous, current = order[-1], next(iter(choices))
            order.append(current)
        if len(order) != len(systems):
            continue

        def oriented_edges(sequence):
            result = []
            for upstream, downstream in zip(sequence, sequence[1:]):
                edge = connections.get((upstream, downstream))
                if edge is None:
                    return None
                result.append(edge)
            for earlier, later in zip(result, result[1:]):
                if earlier["downstream_signal_group_id"] != later["upstream_signal_group_id"]:
                    return None
            return result

        forward_edges = oriented_edges(order)
        reverse_edges = oriented_edges(list(reversed(order)))
        if forward_edges is None and reverse_edges is None:
            exclusions.append({
                "scope": "corridor_component", "upstream_signal_system_id": order[0],
                "downstream_signal_system_id": order[-1], "reason": "no_end_to_end_ahead_group_continuity",
                "distance_m": "", "detail": "|".join(order),
            })
            continue
        active = [False] * TIME_BIN_COUNT
        direction = [""] * TIME_BIN_COUNT
        forward_q = [0.0] * TIME_BIN_COUNT
        reverse_q = [0.0] * TIME_BIN_COUNT
        bin_reason = [""] * TIME_BIN_COUNT
        for index in range(TIME_BIN_COUNT):
            fq_values = [edge["q"][index] for edge in forward_edges] if forward_edges else []
            rq_values = [edge["q"][index] for edge in reverse_edges] if reverse_edges else []
            forward_q[index] = sum(fq_values) / len(fq_values) if fq_values else 0.0
            reverse_q[index] = sum(rq_values) / len(rq_values) if rq_values else 0.0
            selected_direction = ""
            selected_edges = None
            if forward_edges and forward_q[index] >= MIN_DIRECTIONAL_MEAN_Q and min(fq_values) >= MIN_SEGMENT_Q and forward_q[index] >= DOMINANCE_RATIO * reverse_q[index]:
                selected_direction, selected_edges = "forward", forward_edges
            elif reverse_edges and reverse_q[index] >= MIN_DIRECTIONAL_MEAN_Q and min(rq_values) >= MIN_SEGMENT_Q and reverse_q[index] >= DOMINANCE_RATIO * forward_q[index]:
                selected_direction, selected_edges = "reverse", reverse_edges
            if selected_edges is None:
                bin_reason[index] = "no_dominant_minimum_demand_direction"
                continue
            cycles = [int(plan_by_system_bin[(system, index)]["cycle_s"]) for system in order]
            if len(set(cycles)) != 1:
                bin_reason[index] = "incompatible_cycle"
                continue
            internal_systems = order[1:-1]
            if any(
                int(plan_by_system_bin[(system, index)]["cycle_s"]) >= 100
                or plan_by_system_bin[(system, index)]["timing_status"] == "oversaturated_proxy_cycle_capped"
                for system in internal_systems
            ):
                bin_reason[index] = "oversaturated_or_100s_internal_system"
                continue
            active[index] = True
            direction[index] = selected_direction
        retained = retain_consecutive_runs(active)
        for index, value in enumerate(active):
            if value and not retained[index]:
                bin_reason[index] = "isolated_dominant_bin"
        active = retained
        if sum(active) < MIN_COORDINATED_BINS:
            exclusions.append({
                "scope": "corridor_value", "upstream_signal_system_id": order[0],
                "downstream_signal_system_id": order[-1], "reason": "fewer_than_four_valuable_tod_bins",
                "distance_m": "", "detail": str(sum(active)),
            })
            continue
        forward_value = sum(forward_q[index] for index in range(TIME_BIN_COUNT) if active[index] and direction[index] == "forward")
        reverse_value = sum(reverse_q[index] for index in range(TIME_BIN_COUNT) if active[index] and direction[index] == "reverse")
        primary_direction = "forward" if forward_value >= reverse_value else "reverse"
        primary_active = [
            active[index] and direction[index] == primary_direction
            for index in range(TIME_BIN_COUNT)
        ]
        primary_active = retain_consecutive_runs(primary_active)
        if sum(primary_active) < MIN_COORDINATED_BINS:
            exclusions.append({
                "scope": "corridor_value", "upstream_signal_system_id": order[0],
                "downstream_signal_system_id": order[-1], "reason": "no_primary_direction_with_four_valuable_bins",
                "distance_m": "", "detail": primary_direction,
            })
            continue
        for index in range(TIME_BIN_COUNT):
            if active[index] and not primary_active[index]:
                bin_reason[index] = "opposite_to_daily_primary_direction"
        active = primary_active
        direction = [primary_direction if active[index] else "" for index in range(TIME_BIN_COUNT)]
        score = sum(max(forward_q[index], reverse_q[index]) for index in range(TIME_BIN_COUNT) if active[index])
        candidates.append({
            "component_index": component_index, "systems": order, "pairs": pairs,
            "forward_edges": forward_edges, "reverse_edges": reverse_edges,
            "active": active, "direction": direction, "forward_q": forward_q,
            "reverse_q": reverse_q, "bin_reason": bin_reason, "score": score,
            "primary_direction": primary_direction,
        })

    # A system can belong to only one implemented corridor.
    selected_candidates = []
    occupied = set()
    for candidate in sorted(candidates, key=lambda row: (-row["score"], row["systems"])):
        conflict = occupied & set(candidate["systems"])
        if conflict:
            candidate["status"] = "excluded_system_conflict_with_higher_value_corridor"
            candidate["conflict_systems"] = "|".join(sorted(conflict))
            continue
        candidate["status"] = "provisionally_selected"
        selected_candidates.append(candidate)
        occupied.update(candidate["systems"])

    # Compute desired offsets and retain only corridors with safe plan transitions.
    final_candidates = []
    for candidate in selected_candidates:
        systems = candidate["systems"]
        desired_by_system = {system: [0] * TIME_BIN_COUNT for system in systems}
        offset_detail = {}
        for index in range(TIME_BIN_COUNT):
            if not candidate["active"][index]:
                continue
            sequence = systems if candidate["direction"][index] == "forward" else list(reversed(systems))
            edges = candidate["forward_edges"] if candidate["direction"][index] == "forward" else candidate["reverse_edges"]
            cycle = int(plan_by_system_bin[(sequence[0], index)]["cycle_s"])
            desired_by_system[sequence[0]][index] = 0
            global_onset = onset_by_system_bin_group[(sequence[0], index, edges[0]["upstream_signal_group_id"])]
            offset_detail[(sequence[0], index)] = (edges[0]["upstream_signal_group_id"], 0.0, 0)
            for edge, downstream in zip(edges, sequence[1:]):
                if edge["block_policy"] == "short_storage_near_synchronous":
                    target_global = global_onset - SHORT_BLOCK_DOWNSTREAM_LEAD_S
                    progression = -SHORT_BLOCK_DOWNSTREAM_LEAD_S
                else:
                    progression = edge["freeflow_travel_time_s"] + STANDARD_START_LOSS_S - STANDARD_DOWNSTREAM_LEAD_S
                    target_global = global_onset + progression
                group = edge["downstream_signal_group_id"]
                local_onset = onset_by_system_bin_group[(downstream, index, group)]
                desired = round(target_global - local_onset) % cycle
                desired_by_system[downstream][index] = desired
                global_onset = (desired + local_onset) % cycle
                offset_detail[(downstream, index)] = (group, progression, desired)
        safe_by_system = {}
        alignment_by_system = {}
        failed_system = None
        sequence = systems if candidate["primary_direction"] == "forward" else list(reversed(systems))
        for system in systems:
            cycles = [int(plan_by_system_bin[(system, index)]["cycle_s"]) for index in range(TIME_BIN_COUNT)]
            windows = [windows_by_system_bin[(system, index)] for index in range(TIME_BIN_COUNT)]
            safe = choose_safe_constant_offset(
                desired_by_system[system], candidate["active"], cycles, windows,
                force_zero=system == sequence[0],
            )
            if safe is None:
                failed_system = system
                break
            offset, mean_error, maximum_error = safe
            if mean_error > MAX_MEAN_ALIGNMENT_ERROR_S or maximum_error > MAX_ALIGNMENT_ERROR_S:
                failed_system = system
                break
            safe_by_system[system] = [offset] * TIME_BIN_COUNT
            alignment_by_system[system] = (mean_error, maximum_error)
        if failed_system:
            candidate["status"] = "excluded_no_safe_tod_offset_transition"
            candidate["conflict_systems"] = failed_system
            occupied.difference_update(systems)
            continue
        candidate["status"] = "implemented"
        candidate["safe_offsets"] = safe_by_system
        candidate["alignment_by_system"] = alignment_by_system
        candidate["desired_offsets"] = desired_by_system
        candidate["offset_detail"] = offset_detail
        final_candidates.append(candidate)

    implemented_by_system = {
        system: candidate for candidate in final_candidates for system in candidate["systems"]
    }
    modified_plans = []
    for row in plans:
        system = row["signal_system_id"]
        index = int(row["time_bin_index"])
        candidate = implemented_by_system.get(system)
        row = dict(row)
        row["offset_s"] = candidate["safe_offsets"][system][index] if candidate else 0
        modified_plans.append(row)

    registry_rows = []
    link_rows = []
    direction_rows = []
    offset_rows = []
    all_candidates = sorted(candidates, key=lambda row: (-row["score"], row["systems"]))
    corridor_id_by_object = {id(row): f"corridor_{index:03d}" for index, row in enumerate(all_candidates, 1)}
    for candidate in all_candidates:
        corridor_id = corridor_id_by_object[id(candidate)]
        registry_rows.append({
            "corridor_id": corridor_id, "status": candidate["status"],
            "signal_system_count": len(candidate["systems"]),
            "signal_system_ids": "|".join(candidate["systems"]),
            "block_count": len(candidate["systems"]) - 1,
            "valuable_time_bin_count": sum(candidate["active"]),
            "primary_direction": candidate["primary_direction"],
            "value_score_sum_mean_directional_pcu_h": round(candidate["score"], 3),
            "conflict_systems": candidate.get("conflict_systems", ""),
        })
        for direction_name, edges in (("forward", candidate["forward_edges"]), ("reverse", candidate["reverse_edges"])):
            for sequence, edge in enumerate(edges or [], 1):
                link_rows.append({
                    "corridor_id": corridor_id, "direction": direction_name, "sequence": sequence,
                    "upstream_signal_system_id": edge["upstream_signal_system_id"],
                    "downstream_signal_system_id": edge["downstream_signal_system_id"],
                    "upstream_signal_group_id": edge["upstream_signal_group_id"],
                    "downstream_signal_group_id": edge["downstream_signal_group_id"],
                    "from_link_id": edge["from_link_id"], "to_controlled_link_id": edge["to_controlled_link_id"],
                    "path_link_ids": edge["path_link_ids"], "block_length_m": round(edge["block_length_m"], 3),
                    "freeflow_travel_time_s": round(edge["freeflow_travel_time_s"], 3),
                    "block_policy": edge["block_policy"], "movement_ids": "|".join(sorted(edge["movement_ids"])),
                })
        for index in range(TIME_BIN_COUNT):
            direction_rows.append({
                "corridor_id": corridor_id, "time_bin_index": index,
                "time_bin": plan_by_system_bin[(candidate["systems"][0], index)]["time_bin"],
                "forward_mean_q_pcu_h": round(candidate["forward_q"][index], 3),
                "reverse_mean_q_pcu_h": round(candidate["reverse_q"][index], 3),
                "selected_direction": candidate["direction"][index] if candidate["active"][index] else "",
                "coordination_status": "implemented" if candidate["status"] == "implemented" and candidate["active"][index] else "not_coordinated",
                "reason": "dominant_direction_cycle_compatible" if candidate["active"][index] else candidate["bin_reason"][index],
            })
            if candidate["status"] != "implemented":
                continue
            for system in candidate["systems"]:
                detail = candidate["offset_detail"].get((system, index), ("", 0.0, 0))
                offset_rows.append({
                    "corridor_id": corridor_id, "signal_system_id": system,
                    "time_bin_index": index,
                    "time_bin": plan_by_system_bin[(system, index)]["time_bin"],
                    "cycle_s": plan_by_system_bin[(system, index)]["cycle_s"],
                    "selected_direction": candidate["direction"][index] if candidate["active"][index] else "",
                    "coordinated_signal_group_id": detail[0] if candidate["active"][index] else "",
                    "progression_from_previous_s": round(detail[1], 3) if candidate["active"][index] else "",
                    "desired_offset_s": candidate["desired_offsets"][system][index],
                    "implemented_offset_s": candidate["safe_offsets"][system][index],
                    "transition_adjustment_s": candidate["safe_offsets"][system][index] - candidate["desired_offsets"][system][index],
                    "mean_active_bin_alignment_error_s": round(candidate["alignment_by_system"][system][0], 3),
                    "max_active_bin_alignment_error_s": round(candidate["alignment_by_system"][system][1], 3),
                })

    shutil.copytree(source, output, ignore=shutil.ignore_patterns("matsim"))
    write_csv(output / "tod_plan_assignments.csv", modified_plans, tuple(modified_plans[0]))
    write_csv(output / "signal_corridor_registry.csv", registry_rows, tuple(registry_rows[0]))
    write_csv(output / "signal_corridor_links.csv", link_rows, tuple(link_rows[0]))
    write_csv(output / "tod_corridor_direction_15min.csv", direction_rows, tuple(direction_rows[0]))
    write_csv(output / "tod_corridor_offsets.csv", offset_rows, (
        "corridor_id", "signal_system_id", "time_bin_index", "time_bin", "cycle_s",
        "selected_direction", "coordinated_signal_group_id", "progression_from_previous_s",
        "desired_offset_s", "implemented_offset_s", "transition_adjustment_s",
        "mean_active_bin_alignment_error_s", "max_active_bin_alignment_error_s",
    ))
    write_csv(output / "corridor_exclusions.csv", exclusions, (
        "scope", "upstream_signal_system_id", "downstream_signal_system_id",
        "reason", "distance_m", "detail",
    ))

    qa_path = output / "tod_qa_summary.json"
    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    qa.update({
        "status": "all_expressed_tod_15min_corridor_offset_candidate_not_runtime_validated",
        "corridor_candidate_count": len(candidates),
        "implemented_corridor_count": len(final_candidates),
        "implemented_corridor_system_count": len(implemented_by_system),
        "implemented_corridor_time_bin_count": sum(sum(row["active"]) for row in final_candidates),
        "nonzero_offset_plan_count": sum(int(row["offset_s"]) != 0 for row in modified_plans),
        "corridor_runtime_validated": False,
        "production_adopted": False,
    })
    limitations = list(qa.get("known_limitations", []))
    limitations = [
        item
        for item in limitations
        if item != "pedestrian phases and coordination offsets are absent"
    ]
    limitations.append(
        "pedestrian phases are absent; coordination offsets are limited to audited "
        "fixed-daily corridor candidates"
    )
    qa["known_limitations"] = limitations
    qa_path.write_text(json.dumps(qa, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    pilot_summary_path = output / "pilot_build_summary.json"
    pilot_summary = json.loads(pilot_summary_path.read_text(encoding="utf-8"))
    pilot_summary.update({
        "status": "all_expressed_tod_15min_corridor_offset_candidate_not_adopted",
        "offsets": "audited_fixed_daily_corridor_offsets",
        "corridor_candidate_count": len(candidates),
        "implemented_corridor_count": len(final_candidates),
        "implemented_corridor_system_count": len(implemented_by_system),
        "nonzero_offset_plan_count": sum(int(row["offset_s"]) != 0 for row in modified_plans),
        "corridor_runtime_validated": False,
        "production_adopted": False,
    })
    pilot_summary_path.write_text(
        json.dumps(pilot_summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    metadata_path = output / "tod_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata.update({
        "model_status": qa["status"], "source_candidate": str(source), "output_dir": str(output),
        "corridor_policy": {
            "block_length_m": [MIN_SHORT_STORAGE_BLOCK_M, MAX_BLOCK_M],
            "standard_block_min_m": MIN_BLOCK_M,
            "maximum_direction_change_deg": MAX_DIRECTION_CHANGE_DEG,
            "minimum_systems": 3, "dominance_ratio": DOMINANCE_RATIO,
            "minimum_directional_mean_q_pcu_h": MIN_DIRECTIONAL_MEAN_Q,
            "minimum_segment_q_pcu_h": MIN_SEGMENT_Q,
            "minimum_consecutive_bins": MIN_CONSECUTIVE_BINS,
            "minimum_coordinated_bins": MIN_COORDINATED_BINS,
            "same_cycle_required": True,
            "internal_oversaturated_or_100s_system_excluded": True,
            "short_block_downstream_lead_s": SHORT_BLOCK_DOWNSTREAM_LEAD_S,
            "offset_transition_search_radius_s": OFFSET_SEARCH_RADIUS_S,
            "offset_transition_policy": "one_fixed_daily_offset_per_system_selected_against_valuable_tod_bins",
            "maximum_mean_alignment_error_s": MAX_MEAN_ALIGNMENT_ERROR_S,
            "maximum_alignment_error_s": MAX_ALIGNMENT_ERROR_S,
        },
        "source_invariant_sha256": {
            name: sha256(source / name) for name in (
                "executable_signal_movements.csv", "stage_templates.csv", "tod_group_windows.csv",
                "network_signal_capacity_deconvolved.xml.gz",
            )
        },
        "runtime_gate": "not_run",
    })
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = {
        "status": qa["status"], "source_candidate": str(source), "output_dir": str(output),
        "directed_connections": len(connections), "corridor_candidates": len(candidates),
        "implemented_corridors": len(final_candidates),
        "implemented_systems": len(implemented_by_system),
        "implemented_corridor_bins": qa["implemented_corridor_time_bin_count"],
        "nonzero_offset_plans": qa["nonzero_offset_plan_count"],
        "exclusion_rows": len(exclusions), "production_adopted": False,
    }
    (output / "corridor_build_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return summary


def main() -> None:
    print(json.dumps(build(parse_args()), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
