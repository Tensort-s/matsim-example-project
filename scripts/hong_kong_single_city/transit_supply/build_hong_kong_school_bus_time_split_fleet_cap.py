#!/usr/bin/env python3
"""Build a fleet-capped, time-audited split of Hong Kong school-bus proxies.

The Transport Department-derived scenario ceiling is the floor of 4,200 times
the estimated non-tertiary SPB share. Locked first-party route identities count
against that ceiling. The remaining route slots are assigned to a second route
for the most severe, splittable v4 time outliers. After road routing, inferred
routes still exceeding their stage time limit are removed. Demand coverage is
therefore deliberately partial: the time limit and fleet ceiling are hard
constraints, while territory-wide student coverage is not.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from shapely.geometry import LineString

from map_match_hong_kong_school_bus_proxy_routes import (
    DEFAULT_CAMPUSES,
    DEFAULT_NETWORK,
    DEFAULT_PROXY_DIR,
    REPO_ROOT,
    assemble_routes,
    load_inputs,
    parse_network,
    percentile,
    safe_float,
    sha256,
    snap_waypoints,
    write_csv,
    write_static_map,
)


DEFAULT_V4_DIR = (
    REPO_ROOT
    / "data"
    / "school"
    / "hongkong"
    / "processed"
    / "school_bus_proxy_routes_2026_v4_road_matched"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "data"
    / "school"
    / "hongkong"
    / "processed"
    / "school_bus_proxy_routes_2026_v5_time_split_fleet_cap3439"
)
NON_TERTIARY_SHARE = 0.819006959927839
TD_REFERENCE_FLEET = 4200
FLEET_CAP = math.floor(TD_REFERENCE_FLEET * NON_TERTIARY_SHARE)
AVERAGE_SPEED_KMH = 25.2
DWELL_SECONDS_PER_PICKUP = 45.0
TIME_LIMIT_BY_STAGE = {
    "kindergarten": 60.0,
    "primary": 60.0,
    "secondary": 75.0,
    "special": 75.0,
}


def parse_waypoint(value: str) -> tuple[str, str]:
    kind, identifier = value.split(":", 1)
    return kind, identifier


def ordered_grids(segment_table: pd.DataFrame) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for route_id, group in segment_table.groupby("route_id", sort=False):
        group = group.sort_values("segment_order", key=lambda column: column.astype(int))
        labels = [group.iloc[0]["from_waypoint"], *group["to_waypoint"].tolist()]
        grids: list[str] = []
        for label in labels:
            kind, identifier = parse_waypoint(str(label))
            if kind != "origin_grid" or identifier in grids:
                continue
            grids.append(identifier)
        result[str(route_id)] = grids
    return result


def stage_limit(stage: str) -> float:
    return TIME_LIMIT_BY_STAGE.get(str(stage), 75.0)


def capacity_for(load: int) -> int:
    for capacity in (19, 28, 50):
        if load <= capacity:
            return capacity
    raise ValueError(f"Split route load {load} exceeds 50")


def aggregate_stops(stops: pd.DataFrame) -> dict[str, pd.DataFrame]:
    grouped: dict[str, pd.DataFrame] = {}
    for route_id, frame in stops.groupby("route_id", sort=False):
        rows = []
        for grid_id, grid in frame.groupby("origin_grid_id", sort=False):
            first = grid.iloc[0].to_dict()
            first["origin_grid_id"] = str(grid_id)
            first["proxy_students"] = int(pd.to_numeric(grid["proxy_students"]).sum())
            rows.append(first)
        grouped[str(route_id)] = pd.DataFrame(rows)
    return grouped


def split_at_balanced_chain(
    grids: list[str],
    stop_frame: pd.DataFrame,
    school_xy: tuple[float, float],
) -> tuple[list[str], list[str]]:
    lookup = {
        str(row.origin_grid_id): (float(row.x_epsg32650), float(row.y_epsg32650))
        for row in stop_frame.itertuples()
    }
    valid = [grid for grid in grids if grid in lookup]
    for grid in lookup:
        if grid not in valid:
            valid.append(grid)
    if len(valid) < 2:
        raise ValueError("Route has fewer than two unique pickup grids")
    coordinates = [lookup[grid] for grid in valid] + [school_xy]
    cumulative = [0.0]
    for start, end in zip(coordinates, coordinates[1:]):
        cumulative.append(cumulative[-1] + math.dist(start, end))
    target = cumulative[-1] / 2.0
    candidates = range(1, len(valid))
    cut = min(candidates, key=lambda index: (abs(cumulative[index] - target), index))
    return valid[:cut], valid[cut:]


def prepare_split_inputs(
    routes: pd.DataFrame,
    stops: pd.DataFrame,
    campuses: Any,
    v4_routes: pd.DataFrame,
    v4_segments: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    locked_count = int((routes["route_kind"] == "first_party_locked").sum())
    inferred_count = int((routes["route_kind"] == "inferred_proxy").sum())
    extra_slots = FLEET_CAP - locked_count - inferred_count
    if extra_slots <= 0:
        raise ValueError("Fleet ceiling leaves no split-route slots")

    audit = v4_routes[v4_routes["route_kind"] == "inferred_proxy"].copy()
    audit["road_path_km"] = pd.to_numeric(audit["road_path_km"])
    audit["pickup_stop_count"] = pd.to_numeric(audit["pickup_stop_count"])
    audit["modelled_road_runtime_minutes"] = (
        audit["road_path_km"] / AVERAGE_SPEED_KMH * 60.0
        + audit["pickup_stop_count"] * DWELL_SECONDS_PER_PICKUP / 60.0
    )
    audit["time_limit_minutes"] = audit["dominant_stage"].map(TIME_LIMIT_BY_STAGE).fillna(75.0)
    audit["time_excess_minutes"] = audit["modelled_road_runtime_minutes"] - audit["time_limit_minutes"]
    route_order = ordered_grids(v4_segments)
    aggregated = aggregate_stops(stops)
    splittable = audit[
        audit["route_id"].map(lambda route_id: len(route_order.get(str(route_id), [])) >= 2)
    ].sort_values(["time_excess_minutes", "modelled_road_runtime_minutes", "route_id"], ascending=[False, False, True])
    if len(splittable) < extra_slots:
        raise ValueError(f"Only {len(splittable)} routes can be split for {extra_slots} available slots")
    selected = set(splittable.head(extra_slots)["route_id"].astype(str))

    campus_lookup = {
        str(row.campus_id): (float(row.geometry.x), float(row.geometry.y))
        for row in campuses.itertuples()
    }
    route_rows: list[dict[str, Any]] = []
    stop_rows: list[dict[str, Any]] = []
    split_parents: list[str] = []
    for route in routes.to_dict("records"):
        route_id = str(route["route_id"])
        if route.get("route_kind") == "first_party_locked":
            output = dict(route)
            output.update(
                {
                    "parent_route_id": route_id,
                    "split_sequence": 0,
                    "fleet_cap_split_status": "first_party_locked_unsplit",
                }
            )
            route_rows.append(output)
            continue
        frame = aggregated[route_id].copy()
        all_grids = frame["origin_grid_id"].astype(str).tolist()
        order = list(route_order.get(route_id, all_grids))
        order.extend(grid for grid in all_grids if grid not in order)
        if route_id in selected:
            groups = split_at_balanced_chain(order, frame, campus_lookup[str(route["campus_id"])])
            split_parents.append(route_id)
        else:
            groups = ([*order],)
        stop_lookup = {str(row.origin_grid_id): row._asdict() for row in frame.itertuples(index=False)}
        for sequence, grid_group in enumerate(groups, start=1):
            new_route_id = f"{route_id}_S{sequence:02d}" if len(groups) > 1 else route_id
            selected_stops = [stop_lookup[grid] for grid in grid_group]
            load = sum(int(row["proxy_students"]) for row in selected_stops)
            school_xy = campus_lookup[str(route["campus_id"])]
            coordinates = [
                (float(row["x_epsg32650"]), float(row["y_epsg32650"]))
                for row in selected_stops
            ] + [school_xy]
            straight_km = sum(math.dist(a, b) for a, b in zip(coordinates, coordinates[1:])) / 1000.0
            output = dict(route)
            output.update(
                {
                    "route_id": new_route_id,
                    "parent_route_id": route_id,
                    "split_sequence": sequence,
                    "fleet_cap_split_status": "selected_time_outlier_split_in_two"
                    if len(groups) > 1
                    else "unsplit_under_fleet_budget",
                    "proxy_students": load,
                    "vehicle_capacity": capacity_for(load),
                    "pickup_stop_count": len(selected_stops),
                    "straight_line_chain_km": round(straight_km, 4),
                    "circuity_adjusted_km": "",
                    "inferred_run_minutes": "",
                    "first_pickup_time": "",
                    "geometry_quality": "fleet_capped_time_split_then_road_routed_proxy",
                    "adoption_status": "proxy_not_adopted_fleet_capped_time_audit",
                }
            )
            route_rows.append(output)
            for stop_order, stop in enumerate(selected_stops, start=1):
                stop_output = dict(stop)
                stop_output.update(
                    {
                        "route_id": new_route_id,
                        "stop_id": f"{new_route_id}_P{stop_order:03d}",
                        "stop_order": stop_order,
                    }
                )
                stop_rows.append(stop_output)

    metadata = {
        "locked_route_count": locked_count,
        "original_inferred_route_count": inferred_count,
        "available_extra_route_slots": extra_slots,
        "split_parent_count": len(split_parents),
        "selected_parent_route_ids_sha256": hashlib.sha256(
            "\n".join(sorted(split_parents)).encode("utf-8")
        ).hexdigest(),
        "v4_stage_specific_over_limit_route_count": int((audit["time_excess_minutes"] > 0).sum()),
        "minimum_routes_if_every_v4_outlier_split_once_including_locked": inferred_count
        + int((audit["time_excess_minutes"] > 0).sum())
        + locked_count,
    }
    return pd.DataFrame(route_rows).fillna(""), pd.DataFrame(stop_rows).fillna(""), metadata


def update_runtime_fields(
    route_rows: list[dict[str, Any]],
    features: list[dict[str, Any]],
) -> None:
    by_route: dict[str, dict[str, Any]] = {}
    for row in route_rows:
        if row["route_kind"] != "inferred_proxy":
            row.update(
                {
                    "modelled_road_runtime_minutes": "",
                    "time_limit_minutes": "",
                    "time_limit_exceeded": "",
                    "schedule_status": "first_party_locked_not_digitized",
                }
            )
        else:
            runtime = (
                safe_float(row["road_path_km"]) / AVERAGE_SPEED_KMH * 60.0
                + int(safe_float(row["pickup_stop_count"])) * DWELL_SECONDS_PER_PICKUP / 60.0
            )
            limit = stage_limit(str(row["dominant_stage"]))
            row.update(
                {
                    "modelled_road_runtime_minutes": round(runtime, 2),
                    "time_limit_minutes": limit,
                    "time_limit_exceeded": runtime > limit,
                    "schedule_status": "not_generated_pending_time_limit_review",
                }
            )
        by_route[str(row["route_id"])] = row
    for feature in features:
        feature["properties"] = dict(by_route[str(feature["properties"]["route_id"])] )


def build_single_stop_recovery_candidates(
    graph: Any,
    dropped_rows: list[dict[str, Any]],
    all_split_stops: pd.DataFrame,
    campuses: Any,
    available_slots: int,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    pd.DataFrame,
    dict[str, Any],
]:
    """Recover feasible demand as direct one-pickup routes within free slots."""
    if available_slots <= 0 or not dropped_rows:
        return [], [], [], [], pd.DataFrame(columns=all_split_stops.columns), {
            "candidate_count": 0,
            "routed_candidate_count": 0,
            "retained_count": 0,
            "retained_students": 0,
        }
    dropped_lookup = {str(row["route_id"]): row for row in dropped_rows}
    campus_lookup = {
        str(row.campus_id): (float(row.geometry.x), float(row.geometry.y))
        for row in campuses.itertuples()
    }
    candidates: list[tuple[int, float, str, dict[str, Any], dict[str, Any]]] = []
    candidate_stops = all_split_stops[
        all_split_stops["route_id"].astype(str).isin(dropped_lookup)
    ].copy()
    sequence_by_parent: Counter[str] = Counter()
    for stop in candidate_stops.to_dict("records"):
        parent_id = str(stop["route_id"])
        parent = dropped_lookup[parent_id]
        campus_id = str(parent["campus_id"])
        school_xy = campus_lookup[campus_id]
        stop_xy = (float(stop["x_epsg32650"]), float(stop["y_epsg32650"]))
        straight_km = math.dist(stop_xy, school_xy) / 1000.0
        theoretical_minutes = straight_km / AVERAGE_SPEED_KMH * 60.0 + DWELL_SECONDS_PER_PICKUP / 60.0
        if theoretical_minutes > stage_limit(str(parent["dominant_stage"])):
            continue
        sequence_by_parent[parent_id] += 1
        new_route_id = f"{parent_id}_R{sequence_by_parent[parent_id]:03d}"
        load = int(safe_float(stop["proxy_students"]))
        route = dict(parent)
        route.update(
            {
                "route_id": new_route_id,
                "parent_route_id": parent_id,
                "split_sequence": sequence_by_parent[parent_id],
                "fleet_cap_split_status": "single_pickup_recovery_from_hard_time_failure",
                "proxy_students": load,
                "vehicle_capacity": capacity_for(load),
                "pickup_stop_count": 1,
                "straight_line_chain_km": round(straight_km, 4),
                "circuity_adjusted_km": "",
                "inferred_run_minutes": "",
                "first_pickup_time": "",
                "geometry_quality": "single_pickup_recovery_then_road_routed_proxy",
                "adoption_status": "proxy_not_adopted_fleet_capped_hard_time",
            }
        )
        recovery_stop = dict(stop)
        recovery_stop.update(
            {
                "route_id": new_route_id,
                "stop_id": f"{new_route_id}_P001",
                "stop_order": 1,
            }
        )
        candidates.append((-load, theoretical_minutes, new_route_id, route, recovery_stop))
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    pool_limit = min(len(candidates), max(available_slots * 2, available_slots))
    routed_pool = candidates[:pool_limit]
    if not routed_pool:
        return [], [], [], [], pd.DataFrame(columns=all_split_stops.columns), {
            "candidate_count": len(candidates),
            "routed_candidate_count": 0,
            "retained_count": 0,
            "retained_students": 0,
        }
    recovery_routes = pd.DataFrame([item[3] for item in routed_pool]).fillna("")
    recovery_stops = pd.DataFrame([item[4] for item in routed_pool]).fillna("")
    stop_map, campus_map, recovery_snaps = snap_waypoints(
        graph,
        recovery_stops,
        campuses,
        recovery_routes,
    )
    recovery_features, recovery_segments, recovery_routing = assemble_routes(
        graph,
        recovery_routes,
        recovery_stops,
        stop_map,
        campus_map,
    )
    recovery_rows = recovery_routing.pop("route_rows")
    update_runtime_fields(recovery_rows, recovery_features)
    valid_rows = [row for row in recovery_rows if row["time_limit_exceeded"] is False]
    valid_rows.sort(
        key=lambda row: (
            -int(safe_float(row["proxy_students"])),
            safe_float(row["modelled_road_runtime_minutes"]),
            str(row["route_id"]),
        )
    )
    valid_rows = valid_rows[:available_slots]
    retained_ids = {str(row["route_id"]) for row in valid_rows}
    retained_features = [
        item for item in recovery_features if str(item["properties"]["route_id"]) in retained_ids
    ]
    retained_segments = [row for row in recovery_segments if str(row["route_id"]) in retained_ids]
    retained_stops = recovery_stops[recovery_stops["route_id"].astype(str).isin(retained_ids)].copy()
    retained_grids = set(retained_stops["origin_grid_id"].astype(str))
    retained_campuses = {
        str(row["campus_id"]) for row in valid_rows
    }
    retained_snaps = [
        row
        for row in recovery_snaps
        if (
            row["waypoint_kind"] == "origin_grid"
            and str(row["waypoint_id"]) in retained_grids
        )
        or (
            row["waypoint_kind"] == "campus"
            and str(row["waypoint_id"]) in retained_campuses
        )
    ]
    metadata = {
        "candidate_count": len(candidates),
        "routed_candidate_count": len(routed_pool),
        "road_time_feasible_candidate_count": len(
            [row for row in recovery_rows if row["time_limit_exceeded"] is False]
        ),
        "retained_count": len(valid_rows),
        "retained_students": sum(int(safe_float(row["proxy_students"])) for row in valid_rows),
        "method": "direct one-pickup recovery, ranked by load then runtime, within remaining fleet slots",
    }
    return (
        valid_rows,
        retained_features,
        retained_segments,
        retained_snaps,
        retained_stops,
        metadata,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proxy-dir", type=Path, default=DEFAULT_PROXY_DIR)
    parser.add_argument("--v4-dir", type=Path, default=DEFAULT_V4_DIR)
    parser.add_argument("--network", type=Path, default=DEFAULT_NETWORK)
    parser.add_argument("--campuses", type=Path, default=DEFAULT_CAMPUSES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    routes, stops, campuses = load_inputs(args.proxy_dir, args.campuses)
    v4_routes = pd.read_csv(args.v4_dir / "school_bus_road_matched_routes.csv", dtype=str).fillna("")
    v4_segments = pd.read_csv(args.v4_dir / "school_bus_road_match_segments.csv", dtype=str).fillna("")
    split_routes, split_stops, preparation = prepare_split_inputs(
        routes,
        stops,
        campuses,
        v4_routes,
        v4_segments,
    )
    print(
        f"fleet cap {FLEET_CAP:,}: splitting {preparation['split_parent_count']:,} parent routes",
        flush=True,
    )
    graph = parse_network(args.network)
    inferred = split_routes[split_routes["route_kind"] == "inferred_proxy"]
    stop_map, campus_map, snap_rows = snap_waypoints(graph, split_stops, campuses, inferred)
    features, segment_rows, routing = assemble_routes(
        graph,
        split_routes,
        split_stops,
        stop_map,
        campus_map,
    )
    route_rows = routing.pop("route_rows")
    update_runtime_fields(route_rows, features)

    pre_filter_inferred = [row for row in route_rows if row["route_kind"] == "inferred_proxy"]
    dropped_rows = [row for row in pre_filter_inferred if row["time_limit_exceeded"] is True]
    dropped_ids = {str(row["route_id"]) for row in dropped_rows}
    kept_ids = {str(row["route_id"]) for row in route_rows if str(row["route_id"]) not in dropped_ids}
    initial_route_rows = [row for row in route_rows if str(row["route_id"]) in kept_ids]
    initial_features = [item for item in features if str(item["properties"]["route_id"]) in kept_ids]
    initial_segment_rows = [row for row in segment_rows if str(row["route_id"]) in kept_ids]
    all_split_stops = split_stops.copy()
    initial_stops = split_stops[split_stops["route_id"].astype(str).isin(kept_ids)].copy()
    kept_proxy_routes = split_routes[split_routes["route_id"].astype(str).isin(kept_ids)].copy()
    kept_grids = set(initial_stops["origin_grid_id"].astype(str))
    kept_campuses = set(kept_proxy_routes["campus_id"].astype(str))
    initial_snap_rows = [
        row
        for row in snap_rows
        if (
            row["waypoint_kind"] == "origin_grid"
            and str(row["waypoint_id"]) in kept_grids
        )
        or (
            row["waypoint_kind"] == "campus"
            and str(row["waypoint_id"]) in kept_campuses
        )
    ]

    available_recovery_slots = FLEET_CAP - len(initial_route_rows)
    (
        recovery_rows,
        recovery_features,
        recovery_segments,
        recovery_snaps,
        recovery_stops,
        recovery_metadata,
    ) = build_single_stop_recovery_candidates(
        graph,
        dropped_rows,
        all_split_stops,
        campuses,
        available_recovery_slots,
    )
    route_rows = initial_route_rows + recovery_rows
    features = initial_features + recovery_features
    segment_rows = initial_segment_rows + recovery_segments
    split_stops = pd.concat([initial_stops, recovery_stops], ignore_index=True)
    snap_lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for row in initial_snap_rows + recovery_snaps:
        snap_lookup[(str(row["waypoint_kind"]), str(row["waypoint_id"]))] = row
    snap_rows = list(snap_lookup.values())

    route_csv = output / "school_bus_fleet_capped_routes.csv"
    stop_csv = output / "school_bus_fleet_capped_stops.csv"
    segment_csv = output / "school_bus_fleet_capped_segments.csv"
    snap_csv = output / "school_bus_fleet_capped_waypoint_snaps.csv"
    geojson_path = output / "school_bus_fleet_capped_routes.geojson"
    static_path = output / "hong_kong_school_bus_fleet_capped_overview.png"
    write_csv(route_csv, route_rows, list(route_rows[0]))
    write_csv(stop_csv, split_stops.to_dict("records"), list(split_stops.columns))
    write_csv(segment_csv, segment_rows, list(segment_rows[0]))
    write_csv(snap_csv, snap_rows, list(snap_rows[0]))
    geojson_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "name": "school_bus_time_split_fleet_cap3439",
                "features": features,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    write_static_map(
        static_path,
        graph,
        features,
        args.proxy_dir / "school_bus_proxy_route_geometries.geojson",
    )

    inferred_rows = [row for row in route_rows if row["route_kind"] == "inferred_proxy"]
    runtimes = [safe_float(row["modelled_road_runtime_minutes"]) for row in inferred_rows]
    lengths = [safe_float(row["road_path_km"]) for row in inferred_rows]
    exceeded = [row for row in inferred_rows if row["time_limit_exceeded"] is True]
    total_routes = len(route_rows)
    original_students = int(sum(int(safe_float(value)) for value in routes["proxy_students"]))
    output_students = int(sum(int(safe_float(row["proxy_students"])) for row in route_rows))
    dropped_students = original_students - output_students
    retained_proxy_students = int(sum(int(safe_float(row["proxy_students"])) for row in inferred_rows))
    retained_locked_students = output_students - retained_proxy_students
    summary = {
        "output_status": "candidate_not_adopted_fleet_capped_time_audit",
        "fleet_ceiling": {
            "transport_department_reference_vehicle_count": TD_REFERENCE_FLEET,
            "non_tertiary_share": NON_TERTIARY_SHARE,
            "exact_product": TD_REFERENCE_FLEET * NON_TERTIARY_SHARE,
            "integer_ceiling_floor": FLEET_CAP,
            "counting_rule": "one_route_equals_one_peak_vehicle; locked first-party identities count against ceiling",
        },
        **preparation,
        "output_inferred_route_count": len(inferred_rows),
        "output_locked_route_count": total_routes - len(inferred_rows),
        "output_total_route_peak_vehicle_count": total_routes,
        "pre_hard_time_filter_route_count": len(pre_filter_inferred) + preparation["locked_route_count"],
        "hard_time_filter": {
            "initial_over_limit_route_count": len(dropped_rows),
            "single_pickup_recovery": recovery_metadata,
            "dropped_proxy_students": dropped_students,
            "retained_inferred_route_count": len(inferred_rows),
            "retained_proxy_students": retained_proxy_students,
            "retained_locked_proxy_students_unvalidated_time": retained_locked_students,
            "retained_total_proxy_students": output_students,
            "retained_share_of_v3_proxy_students": output_students / original_students,
            "rule": "drop every inferred route whose road runtime exceeds its stage limit; do not force demand coverage",
        },
        "time_limit_by_stage_minutes": TIME_LIMIT_BY_STAGE,
        "average_speed_kmh": AVERAGE_SPEED_KMH,
        "dwell_seconds_per_pickup": DWELL_SECONDS_PER_PICKUP,
        "road_path_km": {
            "median": percentile(lengths, 50),
            "p95": percentile(lengths, 95),
            "maximum": round(max(lengths), 3),
            "over_100km": sum(value > 100 for value in lengths),
        },
        "modelled_road_runtime_minutes": {
            "median": percentile(runtimes, 50),
            "p95": percentile(runtimes, 95),
            "maximum": round(max(runtimes), 2),
            "over_stage_limit": len(exceeded),
            "within_stage_limit": len(inferred_rows) - len(exceeded),
            "over_120": sum(value > 120 for value in runtimes),
            "over_180": sum(value > 180 for value in runtimes),
        },
        "over_stage_limit_by_stage": dict(Counter(str(row["dominant_stage"]) for row in exceeded)),
        "initial_over_stage_limit_by_stage": dict(Counter(str(row["dominant_stage"]) for row in dropped_rows)),
        "routing_quality_counts": dict(Counter(str(row["route_path_quality"]) for row in route_rows)),
        "qa": {
            "fleet_ceiling_respected": total_routes <= FLEET_CAP,
            "pre_filter_fleet_ceiling_filled_exactly": len(pre_filter_inferred) + preparation["locked_route_count"] == FLEET_CAP,
            "retained_and_dropped_students_reconcile": output_students + dropped_students == original_students,
            "all_retained_inferred_routes_within_stage_time_limit": not exceeded,
            "route_ids_unique": len({row["route_id"] for row in route_rows}) == total_routes,
            "locked_route_count_preserved": total_routes - len(inferred_rows) == 76,
            "all_inferred_routes_within_capacity": all(
                int(safe_float(row["proxy_students"])) <= int(safe_float(row["vehicle_capacity"]))
                for row in inferred_rows
            ),
            "no_straight_disconnected_fallback": all(
                int(safe_float(row["straight_disconnected_segment_count"])) == 0
                for row in inferred_rows
            ),
        },
        "limitation": (
            "The 3,439-vehicle ceiling permits only 1,055 additional routes, while 2,030 v4 routes exceed "
            "their stage target. Splits are prioritised by v4 time excess. Any inferred split or unsplit route "
            "still over its hard stage limit is removed; unused fleet slots then recover the highest-load feasible "
            "pickup grids as direct one-pickup routes. Retained student demand remains intentionally incomplete. "
            "Locked first-party identities remain in the inventory but cannot be time-validated without geometry."
        ),
    }
    summary_path = output / "school_bus_fleet_capped_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest_rows = []
    for role, path in (
        ("input_v3_routes", args.proxy_dir / "school_bus_proxy_routes.csv"),
        ("input_v3_stops", args.proxy_dir / "school_bus_proxy_stops.csv"),
        ("input_v4_routes", args.v4_dir / "school_bus_road_matched_routes.csv"),
        ("input_v4_segments", args.v4_dir / "school_bus_road_match_segments.csv"),
        ("input_active_matsim_network", args.network),
        ("input_school_campuses", args.campuses),
        ("output_routes", route_csv),
        ("output_stops", stop_csv),
        ("output_segments", segment_csv),
        ("output_snaps", snap_csv),
        ("output_geometry", geojson_path),
        ("output_summary", summary_path),
        ("output_static_visualization", static_path),
    ):
        manifest_rows.append({"role": role, "path": str(path.resolve()), "sha256": sha256(path)})
    write_csv(output / "SOURCE_MANIFEST.csv", manifest_rows, ["role", "path", "sha256"])
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
