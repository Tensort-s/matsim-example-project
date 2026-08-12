#!/usr/bin/env python3
"""Build a 100-junction, 96-bin Hong Kong time-of-day signal proxy.

This is a deliberately bounded Stage-2 MVP.  It ranks only safely expressible
Stage-1.5 junctions, keeps one geometry-derived stage template for the day,
and changes cycle and green splits at exact 15-minute boundaries.  The output
is rebuildable candidate data; it does not edit the road network or enable
signals in the production configuration.
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage1-dir", type=Path, default=DEFAULT_STAGE1)
    parser.add_argument("--network", type=Path, default=DEFAULT_NETWORK)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--junction-count", type=int, default=100)
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


def select_junctions(stage1_dir: Path, count: int) -> tuple[list[dict], dict[str, list[float]]]:
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
    eligible = []
    for junction_id, profile in profiles.items():
        audit = audits.get(junction_id)
        if audit is None or audit["network_expression_status"] != "expressed":
            continue
        axis_count = len(cluster_approach_axes(approaches_by_junction[junction_id]))
        # A one-axis site cannot express competing vehicular directions; more
        # than four axes is too ambiguous for this bounded MVP.
        if not 2 <= axis_count <= 4:
            continue
        eligible.append({
            "signal_junction_id": junction_id,
            "peak_tpdm_pcu_per_hour": max(profile),
            "daily_tpdm_pcu_count": totals[junction_id],
            "stage1_confidence": audit["junction_stage1_confidence"],
            "approach_count": audit["approach_count"],
            "movement_count": audit["movement_count"],
            "inferred_stage_count": axis_count,
            "selection_eligibility": "expressed_with_planned_demand_no_unresolved_registry_overlap_and_2to4_axes",
        })
    eligible.sort(key=lambda row: (-row["peak_tpdm_pcu_per_hour"], -row["daily_tpdm_pcu_count"], row["signal_junction_id"]))
    selected = eligible[:count]
    for rank, row in enumerate(selected, 1):
        row["demand_rank"] = rank
    return selected, profiles


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

    selected, junction_profiles = select_junctions(args.stage1_dir, args.junction_count)
    if len(selected) != args.junction_count:
        raise ValueError(f"Requested {args.junction_count} junctions but only {len(selected)} are eligible")
    selected_ids = {row["signal_junction_id"] for row in selected}

    approaches = [row for row in read_csv(args.stage1_dir / "signal_approaches.csv") if row["signal_junction_id"] in selected_ids]
    approach_by_id = {row["approach_id"]: row for row in approaches}
    saturation = {row["approach_id"]: float(row["approach_saturation_flow_pcu_h"]) for row in read_csv(args.stage1_dir / "approach_saturation_flow.csv") if row["signal_junction_id"] in selected_ids}
    movements = [
        row for row in read_csv(args.stage1_dir / "signal_movements.csv")
        if row["signal_junction_id"] in selected_ids
        and row["movement_type"] != "u_turn"
        and not row["demand_match_status"].startswith("excluded_")
    ]
    movement_by_id = {row["movement_id"]: row for row in movements}

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

    stage_by_approach: dict[str, str] = {}
    stage_rows: list[dict] = []
    stages_by_junction: dict[str, list[dict]] = {}
    for junction_id in sorted(selected_ids):
        clusters = cluster_approach_axes(by_junction_approaches[junction_id])
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
                "signal_system_id": f"tod_top100__{junction_id}",
                "stage_index": index,
                "stage_id": stage_id,
                "signal_group_id": group_id,
                "axis_bearing_deg": round(axis_mean([float(row["approach_bearing_deg"]) for row in cluster]), 6),
                "approach_ids": "|".join(sorted(row["approach_id"] for row in cluster)),
                "from_link_ids": "|".join(sorted(row["from_link_id"] for row in cluster)),
                "stage_method": "geometry_inferred_opposing_approach_axis",
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
            "signal_system_id": f"tod_top100__{junction_id}",
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
        approach_id = movement_by_id[movement_id]["approach_id"]
        for index, value in enumerate(values):
            raw_approach_q[approach_id][index] += value
    for (movement_id, vehicle_class), values in class_q.items():
        approach_id = movement_by_id[movement_id]["approach_id"]
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
                "signal_system_id": f"tod_top100__{junction_id}",
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
                    "signal_system_id": f"tod_top100__{junction_id}",
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

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.output_dir / "selected_junctions.csv", selected, (
        "demand_rank", "signal_junction_id", "peak_tpdm_pcu_per_hour", "daily_tpdm_pcu_count",
        "stage1_confidence", "approach_count", "movement_count", "selection_eligibility",
        "inferred_stage_count",
    ))
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
        "status": MODEL_STATUS,
        "junction_count": len(selected),
        "time_bin_count_per_junction": TIME_BIN_COUNT,
        "plan_count": len(plan_rows),
        "stage_count": len(stage_rows),
        "signal_count": len(signal_rows),
        "group_window_count": len(window_rows),
        "top100_cutoff_peak_tpdm_pcu_per_hour": selected[-1]["peak_tpdm_pcu_per_hour"],
        "cycle_distribution": dict(sorted(cycle_distribution.items())),
        "timing_status_distribution": dict(design_status_distribution),
        "folded_post_midnight_tpdm_pcu_count": folded_after_midnight,
        "controlled_approach_capacity_change_count": len(capacity_rows),
        "network_topology_or_id_modified": False,
        "candidate_network_capacity_modified": True,
        "production_adopted": False,
        "signal_activation": "explicit_opt_in_only_after_payload_staging",
        "stage_template_policy": "fixed_all_day_geometry_inferred_opposing_axes",
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
            "pedestrian phases and coordination offsets are absent",
            "oversaturated bins use a capped 100-second proxy cycle",
            "taxi has no physical QVehicle demand",
        ],
    }
    (args.output_dir / "tod_qa_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (args.output_dir / "pilot_build_summary.json").write_text(json.dumps({
        "status": MODEL_STATUS,
        "pilot_version": "territory_wide_v3_tod_top100_proxy",
        "scope": "100_high_demand_expressible_junctions_x_96_15min_plans",
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
        "activation_windows": "96_contiguous_15min_time_of_day_plans",
        "offsets": "zero_uncoordinated_proxy",
        "capacity_treatment": "controlled_final_approaches_use_tpdm_saturation_proxy",
        "production_adopted": False,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (args.output_dir / "tod_metadata.json").write_text(json.dumps({
        "model_status": MODEL_STATUS,
        "stage1_dir": str(args.stage1_dir.resolve()),
        "network": str(args.network.resolve()),
        "output_dir": str(args.output_dir.resolve()),
        "junction_selection": "descending peak 15-minute TPDM PCU/h, then daily PCU, then stable junction ID",
        "time_bins": [bin_label(index) for index in range(TIME_BIN_COUNT)],
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    args = parse_args()
    summary = build(args)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
