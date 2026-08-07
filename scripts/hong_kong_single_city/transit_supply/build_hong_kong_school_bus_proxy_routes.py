#!/usr/bin/env python3
"""Build a territory-wide, explicitly inferred Hong Kong school-bus proxy.

The output is modelling preparation, not observed or licensed route supply.
TCS 2022 SPB is filtered by a documented non-tertiary school-bus share.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml
from shapely.geometry import LineString


def hhmmss(value: datetime) -> str:
    return value.strftime("%H:%M:%S")


def largest_remainder(values: np.ndarray, target: int) -> np.ndarray:
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("Demand weights contain non-finite or negative values")
    if values.sum() <= 0:
        raise ValueError("Demand weights sum to zero")
    scaled = values * (target / values.sum())
    result = np.floor(scaled).astype(np.int64)
    remaining = target - int(result.sum())
    if remaining:
        order = np.argsort(-(scaled - result), kind="stable")
        result[order[:remaining]] += 1
    if int(result.sum()) != target:
        raise AssertionError("Integer allocation did not conserve the target")
    return result


def largest_remainder_with_minimum(values: np.ndarray, target: int, minimum: int = 1) -> np.ndarray:
    if target < minimum * len(values):
        raise ValueError("Target is too small for the requested per-row minimum")
    remaining = target - minimum * len(values)
    if remaining == 0:
        return np.full(len(values), minimum, dtype=np.int64)
    return largest_remainder(values, remaining) + minimum


def stable_unit_draw(seed: str, campus_id: object) -> float:
    payload = f"{seed}:{campus_id}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") / 2**64


def distance_bonus(distance_m: float, bonuses: dict) -> float:
    if distance_m <= 500:
        return float(bonuses["at_most_500m"])
    if distance_m <= 1000:
        return float(bonuses["500_to_1000m"])
    if distance_m <= 2000:
        return float(bonuses["1000_to_2000m"])
    return float(bonuses["over_2000m"])


def choose_capacity(load: int, allowed: list[int], maximum: int) -> int:
    for capacity in sorted(set(allowed + [maximum])):
        if load <= capacity:
            return capacity
    return maximum


def split_route_pickups(group: pd.DataFrame, maximum: int) -> list[list[dict]]:
    """Angular sweep, splitting high-volume grid pickups without losing riders."""
    pieces: list[dict] = []
    for row in group.sort_values(["angle", "origin_grid_id"], kind="stable").itertuples():
        remaining = int(row.proxy_students)
        while remaining:
            count = min(remaining, maximum)
            pieces.append({"origin_grid_id": int(row.origin_grid_id), "x": float(row.x), "y": float(row.y), "students": count, "stage": row.dominant_stage, "angle": float(row.angle), "radius_m": float(row.radius_m)})
            remaining -= count
    routes: list[list[dict]] = []
    current: list[dict] = []
    load = 0
    for piece in pieces:
        remaining = piece["students"]
        while remaining:
            room = maximum - load
            take = min(room, remaining)
            current.append({**piece, "students": take})
            load += take
            remaining -= take
            if load == maximum:
                routes.append(current)
                current, load = [], 0
    if current:
        routes.append(current)
    return routes


def route_length_m(stops: list[dict], school_xy: tuple[float, float]) -> float:
    coordinates = [(s["x"], s["y"]) for s in stops] + [school_xy]
    if len(coordinates) < 2:
        return 0.0
    return float(sum(math.dist(a, b) for a, b in zip(coordinates[:-1], coordinates[1:])))


def write_hash_manifest(output_dir: Path, names: list[str]) -> None:
    with (output_dir / "SOURCE_MANIFEST.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["path", "sha256", "bytes", "provenance"])
        writer.writeheader()
        for name in names:
            path = output_dir / name
            payload = path.read_bytes()
            writer.writerow({"path": name, "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload), "provenance": "derived_proxy_not_observed"})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True, help="Project data root containing school/ and worldcommuting_od/")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--assumptions", type=Path, required=True)
    parser.add_argument("--locked-routes", type=Path, required=True)
    args = parser.parse_args()

    assumptions = yaml.safe_load(args.assumptions.read_text(encoding="utf-8"))
    demand_cfg = assumptions["demand"]
    routing = assumptions["routing"]
    selection_cfg = assumptions["school_selection"]
    locked_cfg = assumptions["locked_routes"]
    share = float(demand_cfg["non_tertiary_school_bus_share_of_spb_boardings"])
    if not 0 <= share <= 1:
        raise ValueError("Non-tertiary school-bus share must be between zero and one")
    daily_two_way = float(demand_cfg["daily_two_way_main_mode_equivalent"])
    derived_target = round(0.5 * daily_two_way * share)
    target = int(demand_cfg["target_round_trip_students"])
    if target != derived_target:
        raise ValueError(
            "Configured target_round_trip_students does not match the rounded "
            f"TCS SPB split: configured={target}, derived={derived_target}"
        )
    school_dir = args.input_root / "school" / "hongkong" / "processed" / "student_school_od_2022"
    assignment_path = school_dir / "student_school_assignment_od.parquet"
    campus_path = school_dir / "school_campus_capacity_estimates.geojson"
    program_path = school_dir / "schools_2022_capacity_estimates.csv"
    grid_path = args.input_root / "worldcommuting_od" / "hongkong" / "custom_features" / "hong_kong_fixed_link_grid" / "CityAndRegionSplit" / "hong_kong_fixed_link_grid" / "regions.shp"
    transit_stop_path = args.input_root / "transit" / "hongkong" / "processed" / "transit_schedule_assembly_inputs_2026" / "transit_stop_facilities.csv"
    for path in (assignment_path, campus_path, program_path, grid_path, transit_stop_path, args.locked_routes):
        if not path.exists():
            raise FileNotFoundError(path)

    assignments = pd.read_parquet(assignment_path, columns=["campus_id", "origin_grid_id", "student_stage", "students_expected"])
    grouped = assignments.groupby(["campus_id", "origin_grid_id", "student_stage"], as_index=False, sort=True)["students_expected"].sum()
    total_expected = float(assignments["students_expected"].sum())
    del assignments

    campuses = gpd.read_file(campus_path).to_crs(assumptions["crs"])
    campuses["school_x"] = campuses.geometry.x
    campuses["school_y"] = campuses.geometry.y
    campus_cols = ["campus_id", "school_x", "school_y", "estimated_students", "school_project_count", "grid_id", "study_area_id", "tcs_zone"]
    campus_table = pd.DataFrame(campuses[campus_cols]).drop_duplicates("campus_id")

    programs = pd.read_csv(program_path, encoding="utf-8")
    programs["campus_id"] = programs["campus_id"].astype(str)
    stage_totals = programs.groupby(["campus_id", "base_stage"], as_index=False)["estimated_students"].sum()
    dominant_stage = stage_totals.sort_values(["campus_id", "estimated_students", "base_stage"], ascending=[True, False, True], kind="stable").drop_duplicates("campus_id").rename(columns={"base_stage": "dominant_stage"})[["campus_id", "dominant_stage"]]
    sector_totals = programs.groupby(["campus_id", "base_sector"], as_index=False)["estimated_students"].sum()
    dominant_sector = sector_totals.sort_values(["campus_id", "estimated_students", "base_sector"], ascending=[True, False, True], kind="stable").drop_duplicates("campus_id").rename(columns={"base_sector": "dominant_sector"})[["campus_id", "dominant_sector"]]
    school_names = programs.groupby("campus_id", as_index=False).agg(
        school_name_en=("ENGLISH NAME", lambda x: " | ".join(sorted(set(map(str, x))))),
        school_name_zh=("中文名稱", lambda x: " | ".join(sorted(set(map(str, x))))),
    )
    campus_table["campus_id"] = campus_table["campus_id"].astype(str)
    campus_table = campus_table.merge(dominant_stage, on="campus_id", how="left", validate="one_to_one")
    campus_table = campus_table.merge(dominant_sector, on="campus_id", how="left", validate="one_to_one")
    campus_table = campus_table.merge(school_names, on="campus_id", how="left", validate="one_to_one")

    transit_stops = pd.read_csv(transit_stop_path, usecols=["mode", "x", "y"])
    mtr_xy = transit_stops.loc[transit_stops["mode"].eq("mtr"), ["x", "y"]].drop_duplicates().to_numpy(dtype=float)
    if len(mtr_xy) == 0:
        raise ValueError("No MTR facilities found for school accessibility scoring")
    campus_xy = campus_table[["school_x", "school_y"]].to_numpy(dtype=float)
    campus_table["nearest_mtr_distance_m"] = np.sqrt(((campus_xy[:, None, :] - mtr_xy[None, :, :]) ** 2).sum(axis=2)).min(axis=1)

    locked_routes = pd.read_csv(args.locked_routes, dtype={"campus_id": str, "route_code": str})
    if len(locked_routes) != int(locked_cfg["expected_route_count"]):
        raise ValueError(f"Locked route inventory has {len(locked_routes)} rows, expected {locked_cfg['expected_route_count']}")
    if locked_routes[["source_id", "route_code"]].duplicated().any():
        raise ValueError("Locked route source_id/route_code pairs must be unique")
    unknown_locked = sorted(set(locked_routes["campus_id"]) - set(campus_table["campus_id"]))
    if unknown_locked:
        raise ValueError(f"Locked routes reference unknown campuses: {unknown_locked}")
    locked_counts = locked_routes.groupby("campus_id").size().rename("locked_route_count")
    campus_table = campus_table.merge(locked_counts, on="campus_id", how="left")
    campus_table["locked_route_count"] = campus_table["locked_route_count"].fillna(0).astype(int)

    base_probs = selection_cfg["base_probability_by_stage"]
    funding_bonus = selection_cfg["funding_bonus"]
    mtr_bonus_cfg = selection_cfg["mtr_distance_bonus"]
    low = float(selection_cfg["probability_floor"])
    high = float(selection_cfg["probability_ceiling"])
    rows = []
    for row in campus_table.itertuples(index=False):
        stage = row.dominant_stage if row.dominant_stage in base_probs else "other"
        base = float(base_probs[stage])
        fund = float(funding_bonus.get(row.dominant_sector, 0.0))
        mtr = distance_bonus(float(row.nearest_mtr_distance_m), mtr_bonus_cfg)
        enrol = float(selection_cfg["enrolment_bonus"]["at_least_700"]) if float(row.estimated_students) >= 700 else 0.0
        if float(row.estimated_students) < 150 and stage != "special":
            enrol += float(selection_cfg["enrolment_bonus"]["below_150"])
        probability = min(high, max(low, base + fund + mtr + enrol))
        draw = stable_unit_draw(str(selection_cfg["deterministic_seed"]), row.campus_id)
        forced = int(row.locked_route_count) > 0 and bool(selection_cfg["force_first_party_schools"])
        rows.append({"campus_id": row.campus_id, "base_probability": base, "funding_bonus": fund, "mtr_distance_bonus": mtr, "enrolment_bonus": enrol, "school_bus_probability": probability, "deterministic_draw": draw, "has_school_bus": forced or draw < probability, "selection_reason": "first_party_locked" if forced else "probability_draw"})
    school_probability = campus_table.merge(pd.DataFrame(rows), on="campus_id", how="left", validate="one_to_one")

    grouped["campus_id"] = grouped["campus_id"].astype(str)
    grouped = grouped.merge(school_probability[["campus_id", "has_school_bus"]], on="campus_id", how="left", validate="many_to_one")
    grouped = grouped[grouped["has_school_bus"]].copy()
    stage_weights = selection_cfg["stage_demand_weight"]
    grouped["demand_weight"] = grouped["students_expected"] * grouped["student_stage"].map(stage_weights).fillna(float(stage_weights["other"]))
    campus_weights = grouped.groupby("campus_id", as_index=False)["demand_weight"].sum()
    campus_weights["campus_target"] = largest_remainder_with_minimum(campus_weights["demand_weight"].to_numpy(dtype=float), target)
    grouped = grouped.merge(campus_weights[["campus_id", "campus_target"]], on="campus_id", how="left", validate="many_to_one")
    grouped["proxy_students"] = 0
    for _, campus_group in grouped.groupby("campus_id", sort=True):
        allocation = largest_remainder(campus_group["demand_weight"].to_numpy(dtype=float), int(campus_group["campus_target"].iloc[0]))
        grouped.loc[campus_group.index, "proxy_students"] = allocation
    grouped = grouped[grouped["proxy_students"] > 0].copy()

    stage_rows = grouped.sort_values("proxy_students", ascending=False, kind="stable").drop_duplicates(["campus_id", "origin_grid_id"])
    grid_demand = grouped.groupby(["campus_id", "origin_grid_id"], as_index=False)["proxy_students"].sum()
    grid_demand = grid_demand.merge(stage_rows[["campus_id", "origin_grid_id", "student_stage"]], on=["campus_id", "origin_grid_id"], how="left").rename(columns={"student_stage": "dominant_stage"})

    grids = gpd.read_file(grid_path).to_crs(assumptions["crs"])
    grid_points = grids[["grid_id", "geometry"]].copy()
    grid_points["geometry"] = grid_points.geometry.representative_point()
    grid_points["x"] = grid_points.geometry.x
    grid_points["y"] = grid_points.geometry.y
    grid_xy = pd.DataFrame(grid_points.drop(columns="geometry")).rename(columns={"grid_id": "origin_grid_id"})
    grid_demand = grid_demand.merge(grid_xy, on="origin_grid_id", how="left", validate="many_to_one")
    if grid_demand[["x", "y"]].isna().any().any():
        raise ValueError("Some demand rows do not match the fixed-link grid")

    grid_demand = grid_demand.merge(campus_table[campus_cols], on="campus_id", how="left", validate="many_to_one")
    if grid_demand[["school_x", "school_y"]].isna().any().any():
        raise ValueError("Some assigned campuses have no school coordinate")
    grid_demand["dx"] = grid_demand["x"] - grid_demand["school_x"]
    grid_demand["dy"] = grid_demand["y"] - grid_demand["school_y"]
    grid_demand["radius_m"] = np.hypot(grid_demand["dx"], grid_demand["dy"])
    grid_demand["angle"] = np.arctan2(grid_demand["dy"], grid_demand["dx"])

    arrival = datetime.strptime(routing["school_arrival_time"], "%H:%M:%S")
    maximum = int(routing["maximum_vehicle_capacity"])
    small_caps = [int(x) for x in routing["small_vehicle_capacities"]]
    route_rows, stop_rows, time_rows, route_geometries = [], [], [], []
    probability_lookup = school_probability.set_index("campus_id")
    locked_load_total = 0
    for campus_id, locked_group in locked_routes.groupby("campus_id", sort=True):
        demand_index = grid_demand.index[grid_demand["campus_id"].eq(campus_id)]
        campus_total = int(grid_demand.loc[demand_index, "proxy_students"].sum())
        capacities = locked_group["model_capacity"].fillna(int(locked_cfg["default_model_capacity"])).astype(int).to_numpy()
        locked_target = min(campus_total, int(capacities.sum()))
        if locked_target >= len(capacities):
            loads = largest_remainder_with_minimum(np.maximum(capacities - 1, 0), locked_target)
        else:
            loads = np.zeros(len(capacities), dtype=int)
            loads[:locked_target] = 1
        if (loads > capacities).any():
            raise AssertionError(f"Locked loads exceed capacity for campus {campus_id}")
        remaining = campus_total - int(loads.sum())
        if campus_total > 0:
            if remaining:
                residual = largest_remainder(grid_demand.loc[demand_index, "proxy_students"].to_numpy(dtype=float), remaining)
            else:
                residual = np.zeros(len(demand_index), dtype=int)
            grid_demand.loc[demand_index, "proxy_students"] = residual
        locked_load_total += int(loads.sum())
        school = probability_lookup.loc[campus_id]
        for locked_row, load in zip(locked_group.itertuples(index=False), loads):
            route_id = f"SBL_{locked_row.source_id}_{locked_row.route_code}".replace("/", "_")
            capacity = int(locked_row.model_capacity) if pd.notna(locked_row.model_capacity) else int(locked_cfg["default_model_capacity"])
            route_rows.append({"route_id": route_id, "campus_id": campus_id, "direction": "inbound_am", "proxy_students": int(load), "vehicle_capacity": capacity, "pickup_stop_count": 0, "first_pickup_time": "", "school_arrival_time": routing["school_arrival_time"], "inferred_run_minutes": np.nan, "straight_line_chain_km": np.nan, "circuity_adjusted_km": np.nan, "maximum_school_radius_km": np.nan, "radius_flag": "not_digitized_locked", "dominant_stage": school.dominant_stage, "return_departure_time": routing["return_departure_by_stage"].get(school.dominant_stage, routing["return_departure_by_stage"]["other"]), "evidence_class": locked_row.evidence_class, "geometry_quality": "first_party_route_geometry_not_redistributed_or_not_digitized", "adoption_status": "first_party_route_locked_proxy_load_not_adopted", "route_kind": "first_party_locked", "source_id": locked_row.source_id, "source_route_code": locked_row.route_code})
            route_geometries.append(None)

    grid_demand = grid_demand[grid_demand["proxy_students"] > 0].copy()
    for campus_id, campus_group in grid_demand.groupby("campus_id", sort=True):
        campus_group = campus_group.copy()
        school_xy = (float(campus_group["school_x"].iloc[0]), float(campus_group["school_y"].iloc[0]))
        route_groups = split_route_pickups(campus_group, maximum)
        for sequence, raw_stops in enumerate(route_groups, start=1):
            # A far-to-near inbound order is deterministic and avoids claiming road optimisation.
            stops = sorted(raw_stops, key=lambda item: (-item["radius_m"], item["origin_grid_id"]))
            route_id = f"SBP_{str(campus_id)}_{sequence:03d}"
            load = sum(s["students"] for s in stops)
            capacity = choose_capacity(load, small_caps, maximum)
            line_m = route_length_m(stops, school_xy)
            modelled_m = line_m * float(routing["road_circuity_factor"])
            raw_minutes = modelled_m / (float(routing["average_in_vehicle_speed_kmh"]) * 1000 / 60) + len(stops) * float(routing["dwell_seconds_per_pickup"]) / 60
            run_minutes = min(float(routing["maximum_run_minutes"]), max(float(routing["minimum_run_minutes"]), raw_minutes))
            start = arrival - timedelta(minutes=run_minutes)
            dominant_stage = max(stops, key=lambda s: s["students"])["stage"]
            max_radius_km = max(s["radius_m"] for s in stops) / 1000
            route_rows.append({"route_id": route_id, "campus_id": campus_id, "direction": "inbound_am", "proxy_students": load, "vehicle_capacity": capacity, "pickup_stop_count": len(stops), "first_pickup_time": hhmmss(start), "school_arrival_time": routing["school_arrival_time"], "inferred_run_minutes": round(run_minutes, 2), "straight_line_chain_km": round(line_m / 1000, 4), "circuity_adjusted_km": round(modelled_m / 1000, 4), "maximum_school_radius_km": round(max_radius_km, 4), "radius_flag": "over_20km_review" if max_radius_km > float(assumptions["qa"]["flag_radius_over_km"]) else "within_proxy_threshold", "dominant_stage": dominant_stage, "return_departure_time": routing["return_departure_by_stage"].get(dominant_stage, routing["return_departure_by_stage"]["other"]), "evidence_class": "inferred_proxy", "geometry_quality": routing["route_geometry"], "adoption_status": assumptions["status"], "route_kind": "inferred_proxy", "source_id": "", "source_route_code": ""})
            coordinates = [(s["x"], s["y"]) for s in stops] + [school_xy]
            if len(coordinates) == 1:
                coordinates = [coordinates[0], coordinates[0]]
            route_geometries.append(LineString(coordinates))
            elapsed = 0.0
            segment_budget = run_minutes / max(len(stops), 1)
            for order, stop in enumerate(stops, start=1):
                pickup = start + timedelta(minutes=elapsed)
                stop_id = f"{route_id}_P{order:03d}"
                stop_rows.append({"route_id": route_id, "stop_id": stop_id, "stop_order": order, "origin_grid_id": stop["origin_grid_id"], "proxy_students": stop["students"], "dominant_stage": stop["stage"], "x_epsg32650": round(stop["x"], 3), "y_epsg32650": round(stop["y"], 3), "stop_quality": "inferred_origin_grid_representative_point", "evidence_class": "inferred_proxy"})
                time_rows.append({"route_id": route_id, "stop_id": stop_id, "stop_order": order, "inferred_pickup_time": hhmmss(pickup), "time_quality": "inferred_uniform_route_progression", "school_arrival_time": routing["school_arrival_time"]})
                elapsed += segment_budget

    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    routes_df = pd.DataFrame(route_rows)
    stops_df = pd.DataFrame(stop_rows)
    times_df = pd.DataFrame(time_rows)
    routes_df.to_csv(output / "school_bus_proxy_routes.csv", index=False, encoding="utf-8")
    stops_df.to_csv(output / "school_bus_proxy_stops.csv", index=False, encoding="utf-8")
    times_df.to_csv(output / "school_bus_proxy_route_stop_times.csv", index=False, encoding="utf-8")
    route_gdf = gpd.GeoDataFrame(routes_df.copy(), geometry=route_geometries, crs=assumptions["crs"]).to_crs("EPSG:4326")
    route_gdf.to_file(output / "school_bus_proxy_route_geometries.geojson", driver="GeoJSON")
    school_probability.to_csv(output / "school_bus_school_probabilities.csv", index=False, encoding="utf-8")
    routes_df[routes_df["route_kind"].eq("first_party_locked")].to_csv(output / "school_bus_locked_first_party_routes.csv", index=False, encoding="utf-8")

    campus_demand = routes_df.groupby("campus_id", as_index=False).agg(proxy_students=("proxy_students", "sum"), route_count_total=("route_id", "count"), maximum_school_radius_km=("maximum_school_radius_km", "max"))
    kind_counts = routes_df.groupby(["campus_id", "route_kind"]).size().unstack(fill_value=0).reset_index().rename(columns={"first_party_locked": "locked_route_count_output", "inferred_proxy": "proxy_route_count"})
    campus_demand = school_probability.merge(campus_demand, on="campus_id", how="left")
    campus_demand = campus_demand.merge(kind_counts, on="campus_id", how="left")
    fill_columns = ["proxy_students", "route_count_total", "maximum_school_radius_km", "locked_route_count_output", "proxy_route_count"]
    for column in fill_columns:
        if column not in campus_demand:
            campus_demand[column] = 0
    campus_demand[fill_columns] = campus_demand[fill_columns].fillna(0)
    campus_demand.to_csv(output / "school_bus_proxy_demand_by_campus.csv", index=False, encoding="utf-8")

    observed_total = int(routes_df["proxy_students"].sum())
    locked_mask = routes_df["route_kind"].eq("first_party_locked")
    proxy_mask = routes_df["route_kind"].eq("inferred_proxy")
    selected_by_stage = school_probability.groupby("dominant_stage")["has_school_bus"].agg(["sum", "count"])
    selection_counts = {str(stage): {"selected": int(row["sum"]), "total": int(row["count"]), "zero": int(row["count"] - row["sum"])} for stage, row in selected_by_stage.iterrows()}
    summary = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "version": assumptions["version"],
        "status": assumptions["status"],
        "target_round_trip_students": target,
        "output_round_trip_students": observed_total,
        "source_assignment_expected_students": total_expected,
        "tcs_spb_daily_two_way_main_mode_equivalent": daily_two_way,
        "non_tertiary_school_bus_share_of_spb_boardings": share,
        "target_derivation": "round(0.5 * tcs_spb_daily_two_way_main_mode_equivalent * non_tertiary_school_bus_share_of_spb_boardings)",
        "campuses_selected_for_school_bus": int(school_probability["has_school_bus"].sum()),
        "campuses_zero_school_bus": int((~school_probability["has_school_bus"]).sum()),
        "selection_counts_by_dominant_stage": selection_counts,
        "campuses_with_proxy_service": int((campus_demand["proxy_students"] > 0).sum()),
        "campuses_total": int(len(campus_demand)),
        "locked_first_party_routes": int(locked_mask.sum()),
        "locked_first_party_routes_with_positive_model_load": int((locked_mask & routes_df["proxy_students"].gt(0)).sum()),
        "locked_first_party_proxy_students": int(routes_df.loc[locked_mask, "proxy_students"].sum()),
        "inferred_proxy_routes": int(proxy_mask.sum()),
        "inferred_proxy_students": int(routes_df.loc[proxy_mask, "proxy_students"].sum()),
        "routes_total": int(len(routes_df)),
        "proxy_pickup_records": int(len(stops_df)),
        "routes_over_20km_radius": int((routes_df["radius_flag"] == "over_20km_review").sum()),
        "crs": assumptions["crs"],
        "warnings": [demand_cfg["caveat"], selection_cfg["caveat"], locked_cfg["caveat"], "First-party locking preserves route identity and school priority, but model loads are inferred and locked route geometry/stops are not redistributed or digitised here.", "All remaining route, stop, pickup time and geometry fields are inferred/proxy, not observed, licensed or road-routed.", "The campus estimated_students field is a modelled constraint, not official school-level enrolment."],
        "qa": {"integer_demand_conserved": observed_total == target, "nonnegative_routes": bool((routes_df["proxy_students"] >= 0).all()), "route_capacity_respected": bool((routes_df["proxy_students"] <= routes_df["vehicle_capacity"]).all()), "all_stop_routes_resolve": bool(stops_df["route_id"].isin(routes_df["route_id"]).all()), "locked_route_count_exact": int(locked_mask.sum()) == int(locked_cfg["expected_route_count"]), "locked_campuses_forced_selected": bool(school_probability.loc[school_probability["locked_route_count"].gt(0), "has_school_bus"].all()), "allows_zero_service_campuses": bool((~school_probability["has_school_bus"]).any())},
    }
    if not all(summary["qa"].values()):
        raise AssertionError(summary["qa"])
    (output / "school_bus_proxy_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    names = ["school_bus_proxy_routes.csv", "school_bus_proxy_stops.csv", "school_bus_proxy_route_stop_times.csv", "school_bus_proxy_route_geometries.geojson", "school_bus_school_probabilities.csv", "school_bus_locked_first_party_routes.csv", "school_bus_proxy_demand_by_campus.csv", "school_bus_proxy_summary.json"]
    write_hash_manifest(output, names)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
