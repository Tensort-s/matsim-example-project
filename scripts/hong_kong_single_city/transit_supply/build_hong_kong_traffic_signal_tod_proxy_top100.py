#!/usr/bin/env python3
"""Build a demand-ranked or all-expressed Hong Kong 96-bin TOD signal proxy.

The historical default remains the bounded Top-100 Stage-2 MVP.  The explicit
``all_expressed`` scope activates every Stage-1.5 ``expressed`` registry group
that retains at least one safe non-U-turn executable movement.  Both scopes
use the same geometry-derived stage rule and change cycle and green splits at
exact 15-minute boundaries.  Published diagram membership is provenance only
and never changes selection, grouping, timing, or priority.  The output is
rebuildable candidate data; it does not enable signals in production.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Sequence

from build_hong_kong_traffic_signal_pilot_v1 import parse_network, read_csv, write_csv
from build_hong_kong_traffic_signal_tpdm_proxy_stage1 import stable_id


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_STAGE1 = REPO_ROOT / "data/transit/hongkong/processed/hong_kong_traffic_signals_2026_v3_tpdm_proxy_stage1"
DEFAULT_NETWORK = REPO_ROOT / "data/transit/hongkong/processed/matsim_road_pt_school_bus_supply_2026_v6_adoption_ready/network.xml.gz"
DEFAULT_OUTPUT = REPO_ROOT / "data/transit/hongkong/processed/hong_kong_traffic_signals_2026_v3_tod_proxy_top100"

TIME_BIN_SECONDS = 900
TIME_BIN_COUNT = 96
CYCLE_OPTIONS_SECONDS = (60, 75, 90, 100)
CONTROLLER_CLEARANCE_SECONDS = 6  # 5 s event intergreen + 3 s amber - 2 s red+amber
MIN_GREEN_SECONDS = 7
AXIS_CLUSTER_TOLERANCE_DEGREES = 25.0
WEBSTER_Y_LIMIT = 0.95
MODEL_STATUS = "top100_tod_15min_proxy_candidate_not_adopted"
ALL_EXPRESSED_MODEL_STATUS = "all_expressed_tod_15min_proxy_candidate_not_adopted"
PUBLIC_DIAGRAM_JUNCTIONS = {
    "TS_K005", "TS_K006", "TS_K008", "TS_K024",
    "TS_K025", "TS_K101", "TS_K118", "TS_K201",
}
CONFIDENCE_PRIORITY = {"high": 2, "medium": 1, "low": 0}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage1-dir", type=Path, default=DEFAULT_STAGE1)
    parser.add_argument("--network", type=Path, default=DEFAULT_NETWORK)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--junction-count", type=int, default=100)
    parser.add_argument(
        "--selection-scope",
        choices=("top_demand", "all_expressed"),
        default="top_demand",
        help="Use the historical demand-ranked count or every safely executable expressed registry group.",
    )
    return parser.parse_args()


def circular_axis_distance(left: float, right: float) -> float:
    """Return distance between unoriented bearings in [0, 90]."""
    delta = abs((left % 180.0) - (right % 180.0))
    return min(delta, 180.0 - delta)


def axis_mean(bearings: Sequence[float]) -> float:
    x = sum(math.cos(math.radians(2.0 * (value % 180.0))) for value in bearings)
    y = sum(math.sin(math.radians(2.0 * (value % 180.0))) for value in bearings)
    return (math.degrees(math.atan2(y, x)) / 2.0) % 180.0


def cluster_approach_axes(approaches: Sequence[dict], tolerance: float = AXIS_CLUSTER_TOLERANCE_DEGREES) -> list[list[dict]]:
    """Cluster opposite approaches onto a common, deterministic road axis."""
    clusters: list[list[dict]] = []
    for approach in sorted(approaches, key=lambda row: (float(row["approach_bearing_deg"]) % 180.0, row["approach_id"])):
        bearing = float(approach["approach_bearing_deg"]) % 180.0
        candidates = [
            (circular_axis_distance(bearing, axis_mean([float(item["approach_bearing_deg"]) for item in cluster])), index)
            for index, cluster in enumerate(clusters)
        ]
        distance, index = min(candidates, default=(math.inf, -1))
        if distance <= tolerance:
            clusters[index].append(approach)
        else:
            clusters.append([approach])
    clusters.sort(key=lambda cluster: (axis_mean([float(item["approach_bearing_deg"]) for item in cluster]), min(item["approach_id"] for item in cluster)))
    return clusters


def control_owner_priority(junction: dict) -> tuple:
    """Prefer observed registry identity, then confidence and modeled demand."""
    junction_id = junction["signal_junction_id"]
    return (
        not junction_id.startswith("TS_OSM_"),
        CONFIDENCE_PRIORITY.get(junction["stage1_confidence"], -1),
        float(junction["peak_tpdm_pcu_per_hour"]),
        float(junction["daily_tpdm_pcu_count"]),
        junction_id,
    )


def resolve_cross_system_control_ownership(
    movements: Sequence[dict], selected: Sequence[dict]
) -> tuple[list[dict], list[dict]]:
    """Assign each physical incoming link to exactly one signal system."""
    selected_by_id = {row["signal_junction_id"]: row for row in selected}
    junctions_by_link: dict[str, set[str]] = defaultdict(set)
    for movement in movements:
        junctions_by_link[movement["from_link_id"]].add(movement["signal_junction_id"])
    owner_by_link: dict[str, str] = {}
    audit_rows = []
    for from_link, junction_ids in sorted(junctions_by_link.items()):
        if len(junction_ids) < 2:
            continue
        owner = max(junction_ids, key=lambda value: control_owner_priority(selected_by_id[value]))
        owner_by_link[from_link] = owner
        owner_movements = [
            row for row in movements
            if row["from_link_id"] == from_link and row["signal_junction_id"] == owner
        ]
        for excluded in sorted(junction_ids - {owner}):
            excluded_movements = [
                row for row in movements
                if row["from_link_id"] == from_link and row["signal_junction_id"] == excluded
            ]
            audit_rows.append({
                "from_link_id": from_link,
                "owner_signal_junction_id": owner,
                "excluded_signal_junction_id": excluded,
                "owner_source_priority": "transport_department_registry" if not owner.startswith("TS_OSM_") else "osm_only",
                "owner_peak_tpdm_pcu_per_hour": selected_by_id[owner]["peak_tpdm_pcu_per_hour"],
                "excluded_peak_tpdm_pcu_per_hour": selected_by_id[excluded]["peak_tpdm_pcu_per_hour"],
                "owner_movement_count": len(owner_movements),
                "excluded_movement_count": len(excluded_movements),
                "resolution": "exclusive_incoming_link_control_assigned_to_owner",
            })
    filtered = [
        movement for movement in movements
        if owner_by_link.get(movement["from_link_id"], movement["signal_junction_id"])
        == movement["signal_junction_id"]
    ]
    return filtered, audit_rows


def read_stage_overrides(path: Path | None) -> dict[str, dict]:
    if path is None:
        return {}
    if not path.is_file():
        raise FileNotFoundError(f"Missing stage override audit: {path}")
    rows = read_csv(path)
    result = {}
    for row in rows:
        junction_id = row["signal_junction_id"]
        if junction_id in result:
            raise ValueError(f"Duplicate stage override: {junction_id}")
        tolerance = float(row["axis_cluster_tolerance_deg"])
        if tolerance < AXIS_CLUSTER_TOLERANCE_DEGREES or tolerance > 45.0:
            raise ValueError(f"Unsafe stage override tolerance for {junction_id}: {tolerance}")
        result[junction_id] = row
    return result


def bin_label(index: int) -> str:
    def clock(seconds: int) -> str:
        return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}"
    return f"{clock(index * TIME_BIN_SECONDS)}-{clock((index + 1) * TIME_BIN_SECONDS)}"


def bin_index(label: str) -> int:
    start = label.split("-", 1)[0]
    hour, minute = (int(value) for value in start.split(":"))
    index = (hour * 3600 + minute * 60) // TIME_BIN_SECONDS
    if index < 0:
        raise ValueError(f"Negative time bin is unsupported: {label}")
    # MATSim's plan-based controller repeats plans modulo 24 hours.  Service
    # and routed arrivals after 24:00 therefore belong to the corresponding
    # next-day TOD window, rather than being discarded.
    return index % TIME_BIN_COUNT


def smooth_profile(values: Sequence[float]) -> list[float]:
    """Use a conservative centred smoother without reducing raw design q."""
    result = []
    for index, value in enumerate(values):
        previous = values[index - 1] if index else values[index]
        following = values[index + 1] if index + 1 < len(values) else values[index]
        result.append(max(value, 0.25 * previous + 0.5 * value + 0.25 * following))
    return result


def recommended_cycle(stage_ratios: Sequence[float]) -> tuple[int, float, str]:
    stages = len(stage_ratios)
    total_ratio = sum(stage_ratios)
    lost = stages * CONTROLLER_CLEARANCE_SECONDS
    minimum_cycle = lost + stages * MIN_GREEN_SECONDS
    if total_ratio >= WEBSTER_Y_LIMIT:
        target = CYCLE_OPTIONS_SECONDS[-1]
        status = "oversaturated_proxy_cycle_capped"
    else:
        target = max(minimum_cycle, (1.5 * lost + 5.0) / max(1e-9, 1.0 - total_ratio))
        status = "webster_proxy"
    selected = next((cycle for cycle in CYCLE_OPTIONS_SECONDS if cycle >= target), CYCLE_OPTIONS_SECONDS[-1])
    if selected < minimum_cycle:
        raise ValueError(f"No supported cycle can provide minimum green: stages={stages}")
    if selected == CYCLE_OPTIONS_SECONDS[-1] and target > selected:
        status = "oversaturated_proxy_cycle_capped"
    return selected, total_ratio, status


def smooth_cycle_indices(recommended: Sequence[int]) -> list[int]:
    """Limit adjacent cycle changes to one discrete grade without undersizing."""
    grades = [CYCLE_OPTIONS_SECONDS.index(value) for value in recommended]
    changed = True
    while changed:
        changed = False
        for index in range(1, len(grades)):
            if grades[index] > grades[index - 1] + 1:
                grades[index - 1] = grades[index] - 1
                changed = True
            elif grades[index - 1] > grades[index] + 1:
                grades[index] = grades[index - 1] - 1
                changed = True
    return [CYCLE_OPTIONS_SECONDS[index] for index in grades]


def allocate_green(cycle: int, stage_ratios: Sequence[float]) -> list[int]:
    available = cycle - len(stage_ratios) * CONTROLLER_CLEARANCE_SECONDS
    minimum_total = len(stage_ratios) * MIN_GREEN_SECONDS
    if available < minimum_total:
        raise ValueError("Cycle is too short for the stage template")
    remaining = available - minimum_total
    weights = list(stage_ratios)
    if sum(weights) <= 0:
        weights = [1.0] * len(weights)
    exact = [remaining * weight / sum(weights) for weight in weights]
    additions = [math.floor(value) for value in exact]
    remainder = remaining - sum(additions)
    order = sorted(range(len(exact)), key=lambda index: (-(exact[index] - additions[index]), index))
    for index in order[:remainder]:
        additions[index] += 1
    return [MIN_GREEN_SECONDS + value for value in additions]


def executable_movement(row: dict) -> bool:
    return row["movement_type"] != "u_turn" and not row["demand_match_status"].startswith("excluded_")


def select_junctions(
    stage1_dir: Path,
    count: int,
    selection_scope: str,
) -> tuple[list[dict], dict[str, list[float]], list[dict]]:
    audits = {row["signal_junction_id"]: row for row in read_csv(stage1_dir / "junction_network_expression_audit.csv")}
    profiles: dict[str, list[float]] = defaultdict(lambda: [0.0] * TIME_BIN_COUNT)
    totals: Counter[str] = Counter()
    for row in read_csv(stage1_dir / "junction_demand_15min.csv"):
        index = bin_index(row["time_bin"])
        value = float(row["tpdm_pcu_per_hour"])
        profiles[row["signal_junction_id"]][index] += value
        totals[row["signal_junction_id"]] += float(row["tpdm_pcu_count"])
    approaches_by_junction: dict[str, list[dict]] = defaultdict(list)
    for approach in read_csv(stage1_dir / "signal_approaches.csv"):
        approaches_by_junction[approach["signal_junction_id"]].append(approach)
    active_approach_ids: dict[str, set[str]] = defaultdict(set)
    for movement in read_csv(stage1_dir / "signal_movements.csv"):
        if executable_movement(movement):
            active_approach_ids[movement["signal_junction_id"]].add(movement["approach_id"])
    eligible = []
    exclusions = []
    for junction_id, audit in sorted(audits.items()):
        if audit["network_expression_status"] != "expressed":
            continue
        active_approaches = [
            row for row in approaches_by_junction[junction_id]
            if row["approach_id"] in active_approach_ids[junction_id]
        ]
        if not active_approaches:
            exclusions.append({
                "signal_junction_id": junction_id,
                "network_expression_status": audit["network_expression_status"],
                "activation_status": "excluded_no_safe_non_uturn_executable_movement",
                "reason": "all_movements_removed_by_u_turn_or_registry_overlap_safety_filter",
                "public_diagram_validation_member": str(junction_id in PUBLIC_DIAGRAM_JUNCTIONS).lower(),
                "diagram_special_treatment": "false",
            })
            continue
        profile = profiles[junction_id]
        axis_count = len(cluster_approach_axes(active_approaches))
        eligible.append({
            "signal_junction_id": junction_id,
            "peak_tpdm_pcu_per_hour": max(profile),
            "daily_tpdm_pcu_count": totals[junction_id],
            "stage1_confidence": audit["junction_stage1_confidence"],
            "approach_count": audit["approach_count"],
            "movement_count": audit["movement_count"],
            "inferred_stage_count": axis_count,
            "selection_eligibility": "expressed_with_safe_non_uturn_executable_movement_unified_1to5_axis_rule",
            "public_diagram_validation_member": str(junction_id in PUBLIC_DIAGRAM_JUNCTIONS).lower(),
            "diagram_special_treatment": "false",
        })
    eligible.sort(key=lambda row: (-row["peak_tpdm_pcu_per_hour"], -row["daily_tpdm_pcu_count"], row["signal_junction_id"]))
    selected = eligible if selection_scope == "all_expressed" else eligible[:count]
    for rank, row in enumerate(selected, 1):
        row["demand_rank"] = rank
    return selected, profiles, exclusions


def build(args: argparse.Namespace) -> dict:
    if args.junction_count <= 0:
        raise ValueError("--junction-count must be positive")
    required = [
        args.stage1_dir / "signal_movements.csv",
        args.stage1_dir / "signal_approaches.csv",
        args.stage1_dir / "movement_demand_15min.csv",
        args.stage1_dir / "approach_saturation_flow.csv",
        args.stage1_dir / "junction_network_expression_audit.csv",
        args.network,
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing required inputs: " + ", ".join(missing))

    selected, junction_profiles, exclusions = select_junctions(
        args.stage1_dir, args.junction_count, args.selection_scope
    )
    expressed_registry_group_count = len(selected) + len(exclusions)
    if args.selection_scope == "top_demand" and len(selected) != args.junction_count:
        raise ValueError(f"Requested {args.junction_count} junctions but only {len(selected)} are eligible")
    model_status = MODEL_STATUS if args.selection_scope == "top_demand" else ALL_EXPRESSED_MODEL_STATUS
    system_id_prefix = "tod_top100" if args.selection_scope == "top_demand" else "tod_expressed"
    selected_ids = {row["signal_junction_id"] for row in selected}
    stage_overrides = read_stage_overrides(getattr(args, "stage_overrides", None))

    movements = [
        row for row in read_csv(args.stage1_dir / "signal_movements.csv")
        if row["signal_junction_id"] in selected_ids
        and executable_movement(row)
    ]
    ownership_rows: list[dict] = []
    if args.selection_scope == "all_expressed":
        movements, ownership_rows = resolve_cross_system_control_ownership(movements, selected)
    movement_by_id = {row["movement_id"]: row for row in movements}
    executable_approach_ids = {row["approach_id"] for row in movements}
    approaches = [
        row for row in read_csv(args.stage1_dir / "signal_approaches.csv")
        if row["approach_id"] in executable_approach_ids
    ]
    approach_by_id = {row["approach_id"]: row for row in approaches}
    saturation = {
        row["approach_id"]: float(row["approach_saturation_flow_pcu_h"])
        for row in read_csv(args.stage1_dir / "approach_saturation_flow.csv")
        if row["approach_id"] in executable_approach_ids
    }

    movement_q: dict[str, list[float]] = defaultdict(lambda: [0.0] * TIME_BIN_COUNT)
    class_q: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0] * TIME_BIN_COUNT)
    folded_after_midnight = 0.0
    for row in read_csv(args.stage1_dir / "movement_demand_15min.csv"):
        movement = movement_by_id.get(row["movement_id"])
        if movement is None:
            continue
        index = bin_index(row["time_bin"])
        if int(row["time_bin"].split(":", 1)[0]) >= 24:
            folded_after_midnight += float(row["tpdm_pcu_count"])
        value = float(row["tpdm_pcu_per_hour"])
        movement_q[row["movement_id"]][index] += value
        class_q[(row["movement_id"], row["vehicle_class"])][index] += value

    by_junction_approaches: dict[str, list[dict]] = defaultdict(list)
    for approach in approaches:
        by_junction_approaches[approach["signal_junction_id"]].append(approach)

    deactivation_rows: list[dict] = []
    override_audit_rows: list[dict] = []
    active_selected = []
    for row in selected:
        junction_id = row["signal_junction_id"]
        standard_clusters = cluster_approach_axes(by_junction_approaches[junction_id])
        override = stage_overrides.get(junction_id)
        tolerance = (
            float(override["axis_cluster_tolerance_deg"])
            if override is not None
            else AXIS_CLUSTER_TOLERANCE_DEGREES
        )
        adjusted_clusters = cluster_approach_axes(
            by_junction_approaches[junction_id], tolerance
        )
        if not adjusted_clusters:
            deactivation_rows.append({
                "signal_junction_id": junction_id,
                "source_demand_rank": row["demand_rank"],
                "standard_stage_count": 0,
                "adjusted_stage_count": 0,
                "deactivation_status": "deactivated_after_exclusive_control_ownership",
                "reason": "no_executable_approach_remains_after_cross_system_control_resolution",
            })
        elif len(adjusted_clusters) == 1:
            deactivation_rows.append({
                "signal_junction_id": junction_id,
                "source_demand_rank": row["demand_rank"],
                "standard_stage_count": len(standard_clusters),
                "adjusted_stage_count": 1,
                "deactivation_status": "deactivated_no_competing_vehicle_stage",
                "reason": "one_geometry_inferred_vehicle_stage_has_no_competing_modeled_vehicle_direction",
            })
        else:
            row["inferred_stage_count"] = len(adjusted_clusters)
            row["selection_eligibility"] = (
                "expressed_exclusive_control_multi_stage_with_audited_priority_override"
                if override is not None and tolerance != AXIS_CLUSTER_TOLERANCE_DEGREES
                else "expressed_exclusive_control_multi_stage_unified_axis_rule"
            )
            active_selected.append(row)
        if override is not None:
            override_audit_rows.append({
                **override,
                "standard_stage_count_after_ownership": len(standard_clusters),
                "adjusted_stage_count_after_ownership": len(adjusted_clusters),
                "implementation_status": (
                    "deactivated_no_competing_vehicle_stage"
                    if len(adjusted_clusters) == 1
                    else "stage_override_applied"
                    if tolerance != AXIS_CLUSTER_TOLERANCE_DEGREES
                    else "structure_retained_for_later_timing_calibration"
                ),
            })
    selected = active_selected
    for rank, row in enumerate(selected, 1):
        row["demand_rank"] = rank
    selected_ids = {row["signal_junction_id"] for row in selected}
    movements = [row for row in movements if row["signal_junction_id"] in selected_ids]
    movement_by_id = {row["movement_id"]: row for row in movements}
    executable_approach_ids = {row["approach_id"] for row in movements}
    approaches = [row for row in approaches if row["approach_id"] in executable_approach_ids]
    approach_by_id = {row["approach_id"]: row for row in approaches}
    saturation = {key: value for key, value in saturation.items() if key in executable_approach_ids}
    by_junction_approaches = defaultdict(list)
    for approach in approaches:
        by_junction_approaches[approach["signal_junction_id"]].append(approach)

    stage_by_approach: dict[str, str] = {}
    stage_rows: list[dict] = []
    stages_by_junction: dict[str, list[dict]] = {}
    for junction_id in sorted(selected_ids):
        override = stage_overrides.get(junction_id)
        tolerance = (
            float(override["axis_cluster_tolerance_deg"])
            if override is not None
            else AXIS_CLUSTER_TOLERANCE_DEGREES
        )
        clusters = cluster_approach_axes(by_junction_approaches[junction_id], tolerance)
        stages = []
        for index, cluster in enumerate(clusters, 1):
            stage_id = f"stage__{junction_id}__{index:02d}"
            group_id = f"group__{junction_id}__{index:02d}"
            for approach in cluster:
                stage_by_approach[approach["approach_id"]] = stage_id
            stage = {"stage_id": stage_id, "group_id": group_id, "approaches": cluster}
            stages.append(stage)
            stage_rows.append({
                "signal_junction_id": junction_id,
                "signal_system_id": f"{system_id_prefix}__{junction_id}",
                "stage_index": index,
                "stage_id": stage_id,
                "signal_group_id": group_id,
                "axis_bearing_deg": round(axis_mean([float(row["approach_bearing_deg"]) for row in cluster]), 6),
                "approach_ids": "|".join(sorted(row["approach_id"] for row in cluster)),
                "from_link_ids": "|".join(sorted(row["from_link_id"] for row in cluster)),
                "stage_method": (
                    "geometry_inferred_opposing_approach_axis_priority_override"
                    if tolerance != AXIS_CLUSTER_TOLERANCE_DEGREES
                    else "geometry_inferred_opposing_approach_axis"
                ),
                "stage_confidence": "proxy",
                "protected_turn_policy": "none_without_lane_to_movement_evidence",
            })
        stages_by_junction[junction_id] = stages

    # Collapse full physical paths to the executable MATSim boundary.  This is
    # required because signals can restrict only fromLink -> adjacent toLink.
    boundary_members: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for movement in movements:
        to_link = movement["first_internal_link_id"] or movement["exit_link_id"]
        boundary_members[(movement["signal_junction_id"], movement["from_link_id"], to_link)].append(movement)

    signal_rows: list[dict] = []
    boundary_signal: dict[tuple[str, str, str], str] = {}
    for key, members in sorted(boundary_members.items()):
        junction_id, from_link, to_link = key
        signal_id = stable_id("signal", junction_id, from_link, to_link)
        boundary_signal[key] = signal_id
        approach_id = members[0]["approach_id"]
        stage_id = stage_by_approach[approach_id]
        stage = next(item for item in stages_by_junction[junction_id] if item["stage_id"] == stage_id)
        signal_rows.append({
            "signal_junction_id": junction_id,
            "signal_system_id": f"{system_id_prefix}__{junction_id}",
            "signal_id": signal_id,
            "signal_group_id": stage["group_id"],
            "stage_id": stage_id,
            "approach_id": approach_id,
            "from_link_id": from_link,
            "to_link_id": to_link,
            "physical_movement_ids": "|".join(sorted(row["movement_id"] for row in members)),
            "movement_types": "|".join(sorted({row["movement_type"] for row in members})),
            "executable_boundary_evidence": "model_derived_adjacent_first_connector",
        })

    # Confirm every executable boundary is adjacent before emitting controller input.
    network_tree, _, network_links = parse_network(args.network)
    for row in signal_rows:
        incoming = network_links.get(row["from_link_id"])
        outgoing = network_links.get(row["to_link_id"])
        if incoming is None or outgoing is None or incoming.to_node != outgoing.from_node:
            raise ValueError(f"Non-adjacent executable boundary: {row['from_link_id']} -> {row['to_link_id']}")

    capacity_rows = []
    for approach_id in sorted({row["approach_id"] for row in signal_rows}):
        approach = approach_by_id[approach_id]
        link = network_links[approach["from_link_id"]]
        old_capacity = link.capacity_veh_h
        new_capacity = saturation[approach_id]
        link.element.set("capacity", f"{new_capacity:.6f}")
        capacity_rows.append({
            "signal_junction_id": approach["signal_junction_id"],
            "approach_id": approach_id,
            "from_link_id": approach["from_link_id"],
            "source_network_capacity_veh_h": round(old_capacity, 6),
            "tpdm_saturation_flow_pcu_h": round(new_capacity, 6),
            "candidate_network_capacity_veh_h": round(new_capacity, 6),
            "capacity_treatment": "replace_controlled_final_approach_with_tpdm_saturation_proxy",
            "reason": "avoid_double_counting_existing_practical_capacity_before_signal_green_ratio",
            "topology_or_id_changed": "false",
        })

    raw_approach_q: dict[str, list[float]] = defaultdict(lambda: [0.0] * TIME_BIN_COUNT)
    approach_class_q: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0] * TIME_BIN_COUNT)
    for movement_id, values in movement_q.items():
        movement = movement_by_id.get(movement_id)
        if movement is None:
            continue
        approach_id = movement["approach_id"]
        for index, value in enumerate(values):
            raw_approach_q[approach_id][index] += value
    for (movement_id, vehicle_class), values in class_q.items():
        movement = movement_by_id.get(movement_id)
        if movement is None:
            continue
        approach_id = movement["approach_id"]
        for index, value in enumerate(values):
            approach_class_q[(approach_id, vehicle_class)][index] += value
    design_approach_q = {
        approach_id: smooth_profile(raw_approach_q[approach_id])
        for approach_id in approach_by_id
    }

    plan_rows: list[dict] = []
    window_rows: list[dict] = []
    class_rows: list[dict] = []
    cycle_distribution: Counter[int] = Counter()
    design_status_distribution: Counter[str] = Counter()
    for junction_id in sorted(selected_ids):
        stages = stages_by_junction[junction_id]
        ratios_by_bin: list[list[float]] = []
        recommendations: list[int] = []
        statuses: list[str] = []
        totals: list[float] = []
        for time_index in range(TIME_BIN_COUNT):
            ratios = []
            for stage in stages:
                ratios.append(max(
                    (design_approach_q[row["approach_id"]][time_index] / saturation[row["approach_id"]] for row in stage["approaches"]),
                    default=0.0,
                ))
            cycle, total_ratio, status = recommended_cycle(ratios)
            ratios_by_bin.append(ratios)
            recommendations.append(cycle)
            statuses.append(status)
            totals.append(total_ratio)
        cycles = smooth_cycle_indices(recommendations)

        for time_index, (ratios, cycle) in enumerate(zip(ratios_by_bin, cycles)):
            greens = allocate_green(cycle, ratios)
            start_s = time_index * TIME_BIN_SECONDS
            end_s = 0 if time_index == TIME_BIN_COUNT - 1 else (time_index + 1) * TIME_BIN_SECONDS
            timing_status = statuses[time_index]
            if cycle > recommendations[time_index] and timing_status == "webster_proxy":
                timing_status = "webster_proxy_cycle_raised_for_adjacent_bin_smoothing"
            plan_id = f"tod_{time_index:02d}"
            plan_rows.append({
                "signal_junction_id": junction_id,
                "signal_system_id": f"{system_id_prefix}__{junction_id}",
                "plan_id": plan_id,
                "time_bin_index": time_index,
                "time_bin": bin_label(time_index),
                "start_time_s": start_s,
                "end_time_s": end_s,
                "cycle_s": cycle,
                "recommended_cycle_s": recommendations[time_index],
                "offset_s": 0,
                "stage_count": len(stages),
                "sum_critical_flow_ratio": round(totals[time_index], 6),
                "timing_status": timing_status,
                "demand_source": "stage1_freeflow_route_propagation_planned_q",
                "within_bin_policy": "fixed_for_full_15min",
            })
            cycle_distribution[cycle] += 1
            design_status_distribution[timing_status] += 1
            onset = 0
            for stage_index, (stage, green) in enumerate(zip(stages, greens), 1):
                dropping = onset + green
                if dropping > cycle - CONTROLLER_CLEARANCE_SECONDS:
                    raise AssertionError("Last green leaves no wrap-around clearance")
                window_rows.append({
                    "signal_junction_id": junction_id,
                    "signal_system_id": f"{system_id_prefix}__{junction_id}",
                    "plan_id": plan_id,
                    "time_bin_index": time_index,
                    "time_bin": bin_label(time_index),
                    "stage_index": stage_index,
                    "stage_id": stage["stage_id"],
                    "signal_group_id": stage["group_id"],
                    "cycle_s": cycle,
                    "green_onset_s": onset,
                    "green_dropping_s": dropping,
                    "green_seconds": green,
                    "critical_flow_ratio": round(ratios[stage_index - 1], 6),
                    "controller_clearance_after_s": CONTROLLER_CLEARANCE_SECONDS,
                })
                onset = dropping + CONTROLLER_CLEARANCE_SECONDS
            if onset != cycle:
                raise AssertionError(f"Stage windows do not fill cycle for {junction_id} {plan_id}: {onset} != {cycle}")

            for vehicle_class in ("private_car", "bus", "gmb", "school_bus", "taxi", "other_road_vehicle"):
                for stage_index, stage in enumerate(stages, 1):
                    q = sum(approach_class_q[(row["approach_id"], vehicle_class)][time_index] for row in stage["approaches"])
                    class_rows.append({
                        "signal_junction_id": junction_id,
                        "plan_id": plan_id,
                        "time_bin_index": time_index,
                        "time_bin": bin_label(time_index),
                        "stage_index": stage_index,
                        "stage_id": stage["stage_id"],
                        "vehicle_class": vehicle_class,
                        "raw_design_demand_tpdm_pcu_per_hour": round(q, 6),
                        "physical_network_status": "missing_from_physical_network" if vehicle_class == "taxi" else "represented_or_zero",
                    })

    conflict_rows = []
    for junction_id, local_approaches in sorted(by_junction_approaches.items()):
        for left_index, left in enumerate(sorted(local_approaches, key=lambda row: row["approach_id"])):
            for right in sorted(local_approaches, key=lambda row: row["approach_id"])[left_index + 1:]:
                same_stage = stage_by_approach[left["approach_id"]] == stage_by_approach[right["approach_id"]]
                conflict_rows.append({
                    "signal_junction_id": junction_id,
                    "left_approach_id": left["approach_id"],
                    "right_approach_id": right["approach_id"],
                    "relationship": "compatible_opposing_axis_proxy" if same_stage else "conflicting_different_axis_proxy",
                    "same_stage": str(same_stage).lower(),
                    "evidence": "geometry_inferred_approach_bearing_not_lane_level_conflict_observation",
                })

    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise FileExistsError(f"Refusing non-empty output directory: {args.output_dir}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "selected_junctions.csv", selected, (
        "demand_rank", "signal_junction_id", "peak_tpdm_pcu_per_hour", "daily_tpdm_pcu_count",
        "stage1_confidence", "approach_count", "movement_count", "selection_eligibility",
        "inferred_stage_count", "public_diagram_validation_member", "diagram_special_treatment",
    ))
    if exclusions and args.selection_scope == "all_expressed":
        write_csv(args.output_dir / "junction_activation_exclusions.csv", exclusions, tuple(exclusions[0]))
    if ownership_rows:
        write_csv(args.output_dir / "cross_system_control_ownership_audit.csv", ownership_rows, tuple(ownership_rows[0]))
    if deactivation_rows:
        write_csv(args.output_dir / "junction_deactivation_audit.csv", deactivation_rows, tuple(deactivation_rows[0]))
    if override_audit_rows:
        write_csv(args.output_dir / "priority_junction_override_audit.csv", override_audit_rows, tuple(override_audit_rows[0]))
    write_csv(args.output_dir / "stage_templates.csv", stage_rows, tuple(stage_rows[0]))
    write_csv(args.output_dir / "executable_signal_movements.csv", signal_rows, tuple(signal_rows[0]))
    write_csv(args.output_dir / "approach_conflict_proxy.csv", conflict_rows, tuple(conflict_rows[0]))
    write_csv(args.output_dir / "tod_plan_assignments.csv", plan_rows, tuple(plan_rows[0]))
    write_csv(args.output_dir / "tod_group_windows.csv", window_rows, tuple(window_rows[0]))
    write_csv(args.output_dir / "vehicle_class_stage_demand_15min.csv", class_rows, tuple(class_rows[0]))
    write_csv(args.output_dir / "capacity_deconvolution_audit.csv", capacity_rows, tuple(capacity_rows[0]))
    with gzip.open(args.output_dir / "network_signal_capacity_deconvolved.xml.gz", "wb", compresslevel=6) as stream:
        network_tree.write(
            stream,
            encoding="utf-8",
            xml_declaration=True,
            doctype='<!DOCTYPE network SYSTEM "http://www.matsim.org/files/dtd/network_v2.dtd">',
        )

    summary = {
        "status": model_status,
        "selection_scope": args.selection_scope,
        "expressed_registry_group_count": expressed_registry_group_count if args.selection_scope == "all_expressed" else None,
        "activation_exclusion_count": len(exclusions) if args.selection_scope == "all_expressed" else 0,
        "cross_system_control_overlap_count_resolved": len(ownership_rows),
        "no_competing_vehicle_stage_deactivation_count": sum(
            row["deactivation_status"] == "deactivated_no_competing_vehicle_stage"
            for row in deactivation_rows
        ),
        "post_ownership_empty_deactivation_count": sum(
            row["deactivation_status"] == "deactivated_after_exclusive_control_ownership"
            for row in deactivation_rows
        ),
        "priority_junction_review_count": len(override_audit_rows),
        "priority_junction_stage_override_count": sum(
            row["implementation_status"] == "stage_override_applied"
            for row in override_audit_rows
        ),
        "junction_count": len(selected),
        "time_bin_count_per_junction": TIME_BIN_COUNT,
        "plan_count": len(plan_rows),
        "stage_count": len(stage_rows),
        "signal_count": len(signal_rows),
        "group_window_count": len(window_rows),
        "minimum_selected_peak_tpdm_pcu_per_hour": selected[-1]["peak_tpdm_pcu_per_hour"],
        "cycle_distribution": dict(sorted(cycle_distribution.items())),
        "timing_status_distribution": dict(design_status_distribution),
        "folded_post_midnight_tpdm_pcu_count": folded_after_midnight,
        "controlled_approach_capacity_change_count": len(capacity_rows),
        "network_topology_or_id_modified": False,
        "candidate_network_capacity_modified": True,
        "production_adopted": False,
        "signal_activation": "explicit_opt_in_only_after_payload_staging",
        "cross_system_control_policy": "one_incoming_link_one_signal_system_registry_then_confidence_then_demand_priority",
        "deactivate_no_competing_vehicle_stage": True,
        "stage_template_policy": "fixed_all_day_geometry_inferred_opposing_axes",
        "diagram_policy": "eight_public_diagram_junctions_use_the_same_unified_rule_without_special_treatment",
        "timing_policy": "96_nonoverlapping_15min_fixed_plans",
        "right_turn_policy": "no_protected_right_stage_without_lane_to_movement_evidence",
        "cycle_options_seconds": list(CYCLE_OPTIONS_SECONDS),
        "minimum_green_seconds": MIN_GREEN_SECONDS,
        "event_intergreen_seconds": 5,
        "amber_seconds": 3,
        "red_amber_seconds": 2,
        "controller_clearance_seconds": CONTROLLER_CLEARANCE_SECONDS,
        "known_limitations": [
            "planned freeflow-propagated demand is not iterated equilibrium arrival flow",
            "approach-axis compatibility is a geometry proxy, not lane-level conflict evidence",
            "priority-junction stage overrides remain bounded geometry proxies, not observed lane-level phase plans",
            "pedestrian phases and coordination offsets are absent",
            "oversaturated bins use a capped 100-second proxy cycle",
            "taxi has no physical QVehicle demand",
        ],
    }
    (args.output_dir / "tod_qa_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (args.output_dir / "pilot_build_summary.json").write_text(json.dumps({
        "status": model_status,
        "pilot_version": "territory_wide_v3_tod_top100_proxy" if args.selection_scope == "top_demand" else "territory_wide_v3_tod_all_expressed_proxy",
        "scope": "100_high_demand_expressible_junctions_x_96_15min_plans" if args.selection_scope == "top_demand" else "all_safely_executable_expressed_registry_groups_x_96_15min_plans",
        "active_junction_count": len(selected),
        "controlled_approach_link_count": len(capacity_rows),
        "signal_movement_count": len(signal_rows),
        "signal_group_count": len(stage_rows),
        "signal_plan_count": len(plan_rows),
        "amber_s": 3,
        "red_amber_s": 2,
        "minimum_intergreen_s": 5,
        "controller_onset_gap_s": CONTROLLER_CLEARANCE_SECONDS,
        "stage_mapping_status": "geometry_inferred_opposing_axes_proxy",
        "cross_system_control_overlap_count_resolved": len(ownership_rows),
        "no_competing_vehicle_stage_deactivation_count": sum(
            row["deactivation_status"] == "deactivated_no_competing_vehicle_stage"
            for row in deactivation_rows
        ),
        "priority_junction_stage_override_count": sum(
            row["implementation_status"] == "stage_override_applied"
            for row in override_audit_rows
        ),
        "diagram_special_treatment": False,
        "public_diagram_junction_count": len(PUBLIC_DIAGRAM_JUNCTIONS & selected_ids),
        "activation_windows": "96_contiguous_15min_time_of_day_plans",
        "offsets": "zero_uncoordinated_proxy",
        "capacity_treatment": "controlled_final_approaches_use_tpdm_saturation_proxy",
        "production_adopted": False,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (args.output_dir / "tod_metadata.json").write_text(json.dumps({
        "model_status": model_status,
        "selection_scope": args.selection_scope,
        "system_id_prefix": system_id_prefix,
        "stage1_dir": str(args.stage1_dir.resolve()),
        "network": str(args.network.resolve()),
        "output_dir": str(args.output_dir.resolve()),
        "junction_selection": "all expressed groups with a safe executable movement; demand rank retained for audit" if args.selection_scope == "all_expressed" else "descending peak 15-minute TPDM PCU/h, then daily PCU, then stable junction ID",
        "diagram_policy": "validation provenance only; no special selection, grouping, timing, or priority",
        "cross_system_control_policy": "exclusive incoming-link ownership; registry identity, confidence, demand, then stable ID priority",
        "single_stage_policy": "deactivated when no competing modeled vehicle stage remains",
        "priority_stage_override_file": str(getattr(args, "stage_overrides", "")),
        "time_bins": [bin_label(index) for index in range(TIME_BIN_COUNT)],
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    args = parse_args()
    summary = build(args)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
