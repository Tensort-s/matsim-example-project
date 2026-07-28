#!/usr/bin/env python3
"""Estimate offline Hong Kong taxi fares for allocated taxi passenger legs."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point


ROOT = Path(__file__).resolve().parents[3]
WINDOWS_ROOT = Path(r"F:\Matsim\matsim-example-project")
PROJECT_ROOT = WINDOWS_ROOT if WINDOWS_ROOT.exists() else ROOT
DATA_ROOT = PROJECT_ROOT / "data"
ALLOCATION_DIR = DATA_ROOT / "taxi/hongkong/processed/taxi_initial_plan_allocation_v1"
AUDIT_DIR = DATA_ROOT / "taxi/hongkong/processed/taxi_initial_plan_audit_2026_jan_jun"
FARE_DIR = DATA_ROOT / "taxi/hongkong/processed/taxi_fare_model_v1"
V1_DIR = DATA_ROOT / "matsim_agents/hongkong/typical_weekday_5pct_v1"
V2_DIR = DATA_ROOT / "matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice"
HOUSEHOLD_DIR = DATA_ROOT / "matsim_agents/hongkong/synthetic_households_tcs2022"
GRID_PATH = (
    DATA_ROOT
    / "worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid"
    / "CityAndRegionSplit/hong_kong_fixed_link_grid/regions.shp"
)
NETWORK_PATH = (
    DATA_ROOT
    / "transit/hongkong/processed/"
    "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_ferry_core_v1_cap010/network.xml.gz"
)

SCENARIOS = ["low", "base", "high"]
URBAN_ZONES = set(range(1, 14))
NT_ZONES = {14, 15, 16, 17, 18, 19, 20, 21, 23, 24, 25}
LANTAU_ZONES = {22}
AMBIGUOUS_SWNT_ZONES = {26}
HK_ISLAND_ZONES = {1, 2, 3, 4}
KOWLOON_NT_ZONES = set(range(5, 26))
EXPANSION_WEIGHT = 20.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allocation-dir", type=Path, default=ALLOCATION_DIR)
    parser.add_argument("--audit-dir", type=Path, default=AUDIT_DIR)
    parser.add_argument("--fare-dir", type=Path, default=FARE_DIR)
    parser.add_argument("--v1-dir", type=Path, default=V1_DIR)
    parser.add_argument("--v2-dir", type=Path, default=V2_DIR)
    parser.add_argument("--household-dir", type=Path, default=HOUSEHOLD_DIR)
    parser.add_argument("--grid-path", type=Path, default=GRID_PATH)
    parser.add_argument("--network-path", type=Path, default=NETWORK_PATH)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_status_matsim_agents() -> str:
    result = subprocess.run(
        ["git", "status", "--short", "--", "data/matsim_agents/hongkong"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def hash_inputs(v2_dir: Path, network_path: Path) -> dict[str, str]:
    paths = {
        "plans_unrouted_5pct_v2.xml.gz": v2_dir / "plans_unrouted_5pct_v2.xml.gz",
        "plans_routed_5pct_v2.xml.gz": v2_dir / "plans_routed_5pct_v2.xml.gz",
        "facilities_5pct_v2.xml.gz": v2_dir / "facilities_5pct_v2.xml.gz",
        "network.xml.gz": network_path,
    }
    return {name: sha256(path) for name, path in paths.items()}


def parse_time_s(value: str | None) -> float:
    if value is None or value == "":
        return np.nan
    if isinstance(value, (int, float)):
        return float(value)
    parts = str(value).split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    return float(value)


def count_plan_modes(path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    with gzip.open(path, "rb") as handle:
        for _, elem in ET.iterparse(handle, events=("end",)):
            if elem.tag.rsplit("}", 1)[-1] == "leg":
                mode = elem.attrib.get("mode", "")
                counts[mode] = counts.get(mode, 0) + 1
            elem.clear()
    return counts


def route_attributes(plans_path: Path, needed: set[tuple[str, int]]) -> pd.DataFrame:
    rows = []
    current_person = ""
    leg_sequence = -1
    capture: dict[str, object] | None = None
    with gzip.open(plans_path, "rb") as handle:
        for event, elem in ET.iterparse(handle, events=("start", "end")):
            tag = elem.tag.rsplit("}", 1)[-1]
            if event == "start" and tag == "person":
                current_person = elem.attrib.get("id", "")
                leg_sequence = -1
            elif event == "start" and tag == "leg":
                leg_sequence += 1
                key = (current_person, leg_sequence)
                if key in needed:
                    capture = {
                        "person_id": current_person,
                        "leg_sequence": leg_sequence,
                        "routed_mode": elem.attrib.get("mode", ""),
                        "actual_travel_time_s": parse_time_s(elem.attrib.get("trav_time")),
                    }
            elif event == "end" and tag == "route" and capture is not None:
                attrib = elem.attrib
                text = (elem.text or "").strip()
                capture.update(
                    {
                        "route_type": attrib.get("type", ""),
                        "route_distance_m": float(attrib["distance"]) if "distance" in attrib else np.nan,
                        "route_trav_time_s": parse_time_s(attrib.get("trav_time")),
                        "route_start_link": attrib.get("start_link", ""),
                        "route_end_link": attrib.get("end_link", ""),
                        "route_link_sequence": text,
                        "has_route_link_sequence": bool(text),
                    }
                )
            elif event == "end" and tag == "leg" and capture is not None:
                if pd.isna(capture.get("actual_travel_time_s")):
                    capture["actual_travel_time_s"] = capture.get("route_trav_time_s", np.nan)
                rows.append(capture)
                capture = None
            if event == "end":
                elem.clear()
    return pd.DataFrame(rows)


def read_manifest_with_detail(v1_dir: Path, v2_dir: Path) -> pd.DataFrame:
    manifest = pd.read_parquet(v2_dir / "agent_trip_manifest_v2.parquet")
    v1 = pd.read_parquet(v1_dir / "agent_trip_manifest.parquet")
    detail = v1[["person_id", "leg_sequence", "mode_detail"]]
    merged = manifest.merge(detail, on=["person_id", "leg_sequence"], how="left")
    merged["mode_detail"] = merged["mode_detail"].fillna("")
    return merged


def explicit_taxi_legs(manifest: pd.DataFrame) -> pd.DataFrame:
    rows = manifest.loc[
        manifest["mode"].eq("ride") & manifest["mode_detail"].eq("taxi") & ~manifest["is_discretionary"]
    ].copy()
    rows["tour_id"] = rows["person_id"] + "::explicit_taxi_tour"
    rows["classification_source"] = "v1_mode_detail_explicit_taxi"
    rows["activity_purpose"] = rows["destination_type"].where(
        ~rows["destination_type"].isin(["home", "border", "accommodation"]), rows["origin_type"]
    )
    rows["distance_km"] = np.nan
    for scenario in SCENARIOS:
        rows[f"{scenario}_classification"] = "taxi"
    return rows[
        [
            "tour_id",
            "person_id",
            "leg_sequence",
            "population_group",
            "role",
            "origin_type",
            "destination_type",
            "origin_facility_id",
            "destination_facility_id",
            "departure_time_s",
            "distance_km",
            "classification_source",
            "activity_purpose",
        ]
        + [f"{scenario}_classification" for scenario in SCENARIOS]
    ]


def grid_tcs_lookup(household_dir: Path, v1_dir: Path) -> dict[int, int]:
    frames = []
    for path in [household_dir / "synthetic_households.parquet", v1_dir / "sampled_households.parquet"]:
        if path.exists():
            frame = pd.read_parquet(path, columns=["grid_id", "tcs_zone"])
            frame = frame.loc[frame["tcs_zone"].between(1, 26)]
            frames.append(frame)
    household = pd.concat(frames, ignore_index=True)
    lookup = (
        household.groupby(["grid_id", "tcs_zone"], as_index=False)
        .size()
        .sort_values(["grid_id", "size", "tcs_zone"], ascending=[True, False, True])
        .drop_duplicates("grid_id")
        .set_index("grid_id")["tcs_zone"]
        .astype(int)
        .to_dict()
    )
    return {int(k): int(v) for k, v in lookup.items()}


def parse_facilities(facilities_path: Path, needed_ids: set[str]) -> pd.DataFrame:
    rows = []
    with gzip.open(facilities_path, "rb") as handle:
        for _, elem in ET.iterparse(handle, events=("end",)):
            if elem.tag.rsplit("}", 1)[-1] == "facility":
                facility_id = elem.attrib.get("id", "")
                if facility_id in needed_ids:
                    rows.append(
                        {
                            "facility_id": facility_id,
                            "x": float(elem.attrib["x"]),
                            "y": float(elem.attrib["y"]),
                            "link_id": elem.attrib.get("linkId", ""),
                        }
                    )
                elem.clear()
    return pd.DataFrame(rows)


def facility_zones(facilities: pd.DataFrame, grid_path: Path, grid_tcs: dict[int, int]) -> dict[str, int]:
    result: dict[str, int] = {}
    for facility_id in facilities["facility_id"]:
        text = str(facility_id)
        if "_grid_" in text:
            try:
                grid_id = int(text.rsplit("_grid_", 1)[1])
                if grid_id in grid_tcs:
                    result[text] = int(grid_tcs[grid_id])
            except ValueError:
                pass
    unresolved = facilities.loc[~facilities["facility_id"].isin(result)].copy()
    if unresolved.empty:
        return result
    grid = gpd.read_file(grid_path)[["grid_id", "geometry"]].copy()
    grid["grid_id"] = grid["grid_id"].astype(int)
    grid["tcs_zone"] = grid["grid_id"].map(grid_tcs).fillna(-1).astype(int)
    points = gpd.GeoDataFrame(
        unresolved[["facility_id"]],
        geometry=[Point(xy) for xy in zip(unresolved["x"], unresolved["y"])],
        crs=grid.crs,
    )
    joined = gpd.sjoin(points, grid[["tcs_zone", "geometry"]], predicate="within", how="left")
    for _, row in joined.iterrows():
        result[str(row["facility_id"])] = int(row["tcs_zone"]) if pd.notna(row["tcs_zone"]) else -1
    return result


def merge_facility_evidence(legs: pd.DataFrame, v1_dir: Path, v2_dir: Path, household_dir: Path, grid_path: Path) -> pd.DataFrame:
    needed = set(legs["origin_facility_id"].astype(str)) | set(legs["destination_facility_id"].astype(str))
    facilities = parse_facilities(v2_dir / "facilities_5pct_v2.xml.gz", needed)
    coords = facilities.set_index("facility_id")[["x", "y"]]
    zones = facility_zones(facilities, grid_path, grid_tcs_lookup(household_dir, v1_dir))
    legs = legs.copy()
    legs["origin_x"] = legs["origin_facility_id"].map(coords["x"])
    legs["origin_y"] = legs["origin_facility_id"].map(coords["y"])
    legs["destination_x"] = legs["destination_facility_id"].map(coords["x"])
    legs["destination_y"] = legs["destination_facility_id"].map(coords["y"])
    if "origin_tcs_zone" not in legs.columns:
        legs["origin_tcs_zone"] = np.nan
    if "destination_tcs_zone" not in legs.columns:
        legs["destination_tcs_zone"] = np.nan
    legs["origin_tcs_zone"] = legs["origin_tcs_zone"].fillna(legs["origin_facility_id"].map(zones)).fillna(-1).astype(int)
    legs["destination_tcs_zone"] = (
        legs["destination_tcs_zone"].fillna(legs["destination_facility_id"].map(zones)).fillna(-1).astype(int)
    )
    euclidean = np.hypot(legs["destination_x"] - legs["origin_x"], legs["destination_y"] - legs["origin_y"])
    legs["euclidean_distance_m"] = euclidean
    return legs


def taxi_type_for_zones(zones: set[int]) -> tuple[str, str, str]:
    known = {int(zone) for zone in zones if int(zone) > 0}
    if not known or any(zone <= 0 for zone in zones):
        return "unresolved", "unresolved_zone", f"tour zones include unresolved value: {sorted(zones)}"
    if known <= LANTAU_ZONES:
        return "lantau_taxi", "td_operating_area_tcs_zone_rule", f"all zones are North Lantau-compatible: {sorted(known)}"
    if known & (LANTAU_ZONES | AMBIGUOUS_SWNT_ZONES):
        return "unresolved", "lantau_cross_area_unresolved", f"Lantau/SWNT evidence mixed with other zones: {sorted(known)}"
    if known <= NT_ZONES:
        return "new_territories_taxi", "td_operating_area_tcs_zone_rule", f"all zones are New Territories zones: {sorted(known)}"
    if known & URBAN_ZONES:
        return "urban_taxi", "td_operating_area_tcs_zone_rule", f"urban taxi assigned for urban/general HK tour zones: {sorted(known)}"
    return "unresolved", "unmatched_service_area_rule", f"zones do not match v1 service-area rule: {sorted(known)}"


def assign_taxi_type(legs: pd.DataFrame) -> pd.DataFrame:
    assignments = []
    for tour_id, group in legs.groupby("tour_id", sort=False):
        zones = set(group["origin_tcs_zone"].astype(int)) | set(group["destination_tcs_zone"].astype(int))
        taxi_type, source, evidence = taxi_type_for_zones(zones)
        assignments.append(
            {
                "tour_id": tour_id,
                "taxi_type": taxi_type,
                "taxi_type_assignment_source": source,
                "taxi_type_assignment_evidence": evidence,
                "service_area_exception": taxi_type == "unresolved" and ("Lantau" in evidence or "SWNT" in evidence),
            }
        )
    return legs.merge(pd.DataFrame(assignments), on="tour_id", how="left", validate="many_to_one")


def fare_for_distance(distance_m: float, rule: pd.Series) -> tuple[float, int]:
    if pd.isna(distance_m) or distance_m < 0:
        return np.nan, 0
    flagfall_distance = float(rule["flagfall_distance_m"])
    fare = float(rule["flagfall_hkd"])
    if distance_m <= flagfall_distance:
        return fare, 0
    first_end = float(rule["first_tier_end_distance_m"])
    first_inc_m = float(rule["first_tier_increment_distance_m"])
    second_inc_m = float(rule["second_tier_increment_distance_m"])
    first_count = int(math.ceil(max(min(distance_m, first_end) - flagfall_distance, 0.0) / first_inc_m))
    second_count = int(math.ceil(max(distance_m - first_end, 0.0) / second_inc_m))
    fare += first_count * float(rule["first_tier_increment_hkd"])
    fare += second_count * float(rule["second_tier_increment_hkd"])
    return round(fare, 1), first_count + second_count


def add_fares(legs: pd.DataFrame, fare_rules: pd.DataFrame) -> pd.DataFrame:
    rules = fare_rules.set_index("taxi_type")
    all_types = ["urban_taxi", "new_territories_taxi", "lantau_taxi"]
    rows = []
    for _, row in legs.iterrows():
        row = row.to_dict()
        route_distance = row.get("route_distance_m", np.nan)
        taxi_type = row["taxi_type"]
        type_for_calculation = taxi_type if taxi_type in rules.index else "urban_taxi"
        rule = rules.loc[type_for_calculation]
        meter_fare, increments = fare_for_distance(route_distance, rule)
        range_fares = [fare_for_distance(route_distance, rules.loc[taxi_type_name])[0] for taxi_type_name in all_types]
        tunnel_surcharge = 0.0
        booking_fee = 0.0
        other_surcharge = 0.0
        waiting = 0.0
        row.update(
            {
                "flagfall_hkd": float(rule["flagfall_hkd"]),
                "distance_increment_count": int(increments),
                "fare_meter_distance_hkd": meter_fare,
                "fare_waiting_hkd": waiting,
                "tunnel_name": "",
                "toll_link_id": "",
                "tunnel_surcharge_hkd": tunnel_surcharge,
                "booking_fee_hkd": booking_fee,
                "other_surcharge_hkd": other_surcharge,
                "total_fare_distance_only_hkd": round(meter_fare + tunnel_surcharge + booking_fee + other_surcharge, 1)
                if pd.notna(meter_fare)
                else np.nan,
                "total_fare_congestion_proxy_hkd": round(meter_fare + waiting + tunnel_surcharge + booking_fee + other_surcharge, 1)
                if pd.notna(meter_fare)
                else np.nan,
                "fare_rule_effective_date": rule["fare_effective_date"],
                "fare_rule_source": rule["source_url"],
                "unresolved_fare_min_distance_only_hkd": round(float(np.nanmin(range_fares)), 1),
                "unresolved_fare_max_distance_only_hkd": round(float(np.nanmax(range_fares)), 1),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def possible_harbour_tunnel(row: pd.Series) -> bool:
    oz = int(row["origin_tcs_zone"])
    dz = int(row["destination_tcs_zone"])
    return (oz in HK_ISLAND_ZONES and dz in KOWLOON_NT_ZONES) or (dz in HK_ISLAND_ZONES and oz in KOWLOON_NT_ZONES)


def departure_period(seconds: float) -> str:
    if pd.isna(seconds):
        return "unknown"
    hour = float(seconds) / 3600.0
    if hour < 6:
        return "00_early_0000_0559"
    if hour < 10:
        return "01_morning_0600_0959"
    if hour < 16:
        return "02_midday_1000_1559"
    if hour < 20:
        return "03_evening_peak_1600_1959"
    if hour < 24:
        return "04_night_2000_2359"
    return "05_after_midnight_2400_plus"


def distance_band(distance_m: float) -> str:
    if pd.isna(distance_m):
        return "unknown"
    distance_km = float(distance_m) / 1000.0
    if distance_km < 2:
        return "00_0_2km"
    if distance_km < 5:
        return "01_2_5km"
    if distance_km < 10:
        return "02_5_10km"
    if distance_km < 20:
        return "03_10_20km"
    return "04_20km_plus"


def prepare_all_taxi_leg_candidates(args: argparse.Namespace) -> tuple[pd.DataFrame, dict[str, int]]:
    candidate = pd.read_csv(args.allocation_dir / "taxi_candidate_leg_classification.csv")
    tours = pd.read_csv(args.allocation_dir / "taxi_candidate_tour_classification.csv")[
        ["tour_id", "classification_source", "activity_purpose", "departure_period"]
    ]
    candidate = candidate.merge(tours, on="tour_id", how="left", validate="many_to_one")
    manifest = read_manifest_with_detail(args.v1_dir, args.v2_dir)
    explicit = explicit_taxi_legs(manifest)
    all_legs = pd.concat([candidate, explicit], ignore_index=True, sort=False)
    all_legs = merge_facility_evidence(all_legs, args.v1_dir, args.v2_dir, args.household_dir, args.grid_path)
    needed = set(zip(all_legs["person_id"].astype(str), all_legs["leg_sequence"].astype(int)))
    routes = route_attributes(args.v2_dir / "plans_routed_5pct_v2.xml.gz", needed)
    all_legs = all_legs.merge(routes, on=["person_id", "leg_sequence"], how="left", validate="one_to_one")
    all_legs["route_available"] = all_legs["route_distance_m"].notna()
    all_legs["distance_source"] = np.where(all_legs["route_available"], "routed_plans_generic_route_distance", "unavailable_no_final_distance")
    all_legs["distance_ratio"] = all_legs["route_distance_m"] / all_legs["euclidean_distance_m"].replace(0, np.nan)
    all_legs["departure_period"] = all_legs["departure_period"].fillna(
        all_legs["departure_time_s"].map(departure_period)
    )
    all_legs["distance_band"] = all_legs["route_distance_m"].map(distance_band)
    all_legs["freeflow_travel_time_s"] = np.nan
    all_legs["excess_time_s"] = np.nan
    all_legs["congestion_proxy_status"] = "unavailable_generic_route_not_qsim_congested_or_no_link_freeflow"
    all_legs["tunnel_detection_source"] = np.where(
        all_legs.apply(possible_harbour_tunnel, axis=1),
        "no_link_sequence_possible_tunnel_ambiguous",
        "no_route_link_sequence",
    )
    all_legs["ambiguous_tunnel_route"] = all_legs["tunnel_detection_source"].eq("no_link_sequence_possible_tunnel_ambiguous")
    all_legs = assign_taxi_type(all_legs)
    preserved = pd.read_csv(args.audit_dir / "taxi_initial_plan_audit.csv")
    preserved_counts = preserved.groupby("ride_subtype")["legs_5pct"].sum().astype(int).to_dict()
    return all_legs, preserved_counts


def write_summaries(frame: pd.DataFrame, scenario: str, out_dir: Path) -> None:
    taxi = frame.loc[frame["scenario"].eq(scenario)].copy()
    fare_col = "total_fare_distance_only_hkd"
    def summarize(group: pd.DataFrame) -> pd.Series:
        values = group[fare_col].dropna()
        return pd.Series(
            {
                "legs_5pct": len(group),
                "expanded_legs": len(group) * EXPANSION_WEIGHT,
                "total_fare_hkd_5pct": values.sum(),
                "expanded_total_fare_hkd": values.sum() * EXPANSION_WEIGHT,
                "mean_hkd": values.mean(),
                "median_hkd": values.median(),
                "p10_hkd": values.quantile(0.10),
                "p25_hkd": values.quantile(0.25),
                "p75_hkd": values.quantile(0.75),
                "p90_hkd": values.quantile(0.90),
                "p95_hkd": values.quantile(0.95),
                "within_flagfall_share": group["distance_increment_count"].eq(0).mean(),
                "tolled_tunnel_share": group["tunnel_surcharge_hkd"].gt(0).mean(),
                "taxi_type_unresolved_share": group["taxi_type"].eq("unresolved").mean(),
                "route_distance_unavailable_share": (~group["route_available"]).mean(),
                "congestion_proxy_unavailable_share": group["congestion_proxy_status"].ne("available").mean(),
            }
        )

    summary_specs = {
        "type": ["taxi_type"],
        "time": ["departure_period"],
        "distance": ["distance_band"],
        "purpose": ["activity_purpose"],
        "tcs26_od": ["origin_tcs_zone", "destination_tcs_zone"],
        "population_group": ["population_group", "role"],
    }
    for name, columns in summary_specs.items():
        output = taxi.groupby(columns, dropna=False).apply(summarize).reset_index()
        output.insert(0, "scenario", scenario)
        path = out_dir / f"taxi_fare_summary_by_{name}.csv"
        mode = "a" if path.exists() else "w"
        header = not path.exists()
        output.to_csv(path, index=False, encoding="utf-8-sig", mode=mode, header=header)

    person = taxi.groupby("person_id", as_index=False).agg(
        taxi_legs_5pct=("leg_sequence", "count"),
        daily_total_fare_hkd_5pct=(fare_col, "sum"),
    )
    person["expanded_daily_total_fare_hkd"] = person["daily_total_fare_hkd_5pct"] * EXPANSION_WEIGHT
    person.insert(0, "scenario", scenario)
    path = out_dir / "taxi_fare_summary_by_person.csv"
    mode = "a" if path.exists() else "w"
    header = not path.exists()
    person.to_csv(path, index=False, encoding="utf-8-sig", mode=mode, header=header)


def scenario_frame(all_legs: pd.DataFrame, scenario: str, fare_rules: pd.DataFrame) -> pd.DataFrame:
    class_col = f"{scenario}_classification"
    taxi = all_legs.loc[all_legs[class_col].eq("taxi")].copy()
    taxi.insert(0, "scenario", scenario)
    taxi["unresolved_reason"] = np.where(taxi["taxi_type"].eq("unresolved"), taxi["taxi_type_assignment_evidence"], "")
    taxi = add_fares(taxi, fare_rules)
    columns = [
        "scenario",
        "person_id",
        "tour_id",
        "leg_sequence",
        "classification_source",
        "taxi_type",
        "taxi_type_assignment_source",
        "taxi_type_assignment_evidence",
        "origin_facility_id",
        "destination_facility_id",
        "origin_tcs_zone",
        "destination_tcs_zone",
        "departure_time_s",
        "departure_period",
        "activity_purpose",
        "population_group",
        "role",
        "route_distance_m",
        "euclidean_distance_m",
        "distance_source",
        "route_available",
        "distance_ratio",
        "distance_band",
        "actual_travel_time_s",
        "freeflow_travel_time_s",
        "excess_time_s",
        "congestion_proxy_status",
        "flagfall_hkd",
        "distance_increment_count",
        "fare_meter_distance_hkd",
        "fare_waiting_hkd",
        "tunnel_name",
        "toll_link_id",
        "tunnel_detection_source",
        "ambiguous_tunnel_route",
        "tunnel_surcharge_hkd",
        "booking_fee_hkd",
        "other_surcharge_hkd",
        "total_fare_distance_only_hkd",
        "total_fare_congestion_proxy_hkd",
        "unresolved_fare_min_distance_only_hkd",
        "unresolved_fare_max_distance_only_hkd",
        "fare_rule_effective_date",
        "fare_rule_source",
        "unresolved_reason",
    ]
    return taxi[columns]


def validation(
    scenario_frames: dict[str, pd.DataFrame],
    all_legs: pd.DataFrame,
    preserved_counts: dict[str, int],
    fare_rules: pd.DataFrame,
    hashes_before: dict[str, str],
    hashes_after: dict[str, str],
    git_before: str,
    git_after: str,
    plan_counts: dict[str, int],
) -> dict[str, object]:
    base = scenario_frames["base"]
    explicit_base = base["classification_source"].eq("v1_mode_detail_explicit_taxi").sum()
    new_base = base["classification_source"].ne("v1_mode_detail_explicit_taxi").sum()
    noncharged = all_legs.loc[
        (all_legs["base_classification"].ne("taxi")) & all_legs["classification_source"].ne("v1_mode_detail_explicit_taxi")
    ]

    boundary_tests = []
    for _, rule in fare_rules.iterrows():
        distances = [
            float(rule["flagfall_distance_m"]),
            float(rule["flagfall_distance_m"]) + 0.01,
            float(rule["first_tier_end_distance_m"]),
            float(rule["first_tier_end_distance_m"]) + 0.01,
        ]
        boundary_tests.append(
            {
                "taxi_type": rule["taxi_type"],
                "distances_m": distances,
                "fares_hkd": [fare_for_distance(distance, rule)[0] for distance in distances],
            }
        )

    assigned = base.loc[base["taxi_type"].ne("unresolved")]
    min_flagfall_ok = bool((assigned["total_fare_distance_only_hkd"] >= assigned["flagfall_hkd"]).all())
    validation_result = {
        "base_total_taxi_passenger_legs": int(len(base)),
        "base_total_taxi_passenger_legs_ok": int(len(base)) == 37286,
        "explicit_taxi_retained_legs": int(explicit_base),
        "explicit_taxi_retained_ok": int(explicit_base) == 4614,
        "base_added_taxi_legs": int(new_base),
        "base_added_taxi_legs_ok": int(new_base) == 32672,
        "private_car_passenger_preserved_legs": int(preserved_counts.get("private_car_passenger", 0)),
        "school_bus_preserved_legs": int(preserved_counts.get("school_bus", 0)),
        "non_taxi_candidate_legs_not_charged_base": int(len(noncharged)),
        "non_taxi_candidate_legs_not_charged_ok": int(len(noncharged)) == 5884,
        "same_tour_classification_consistent_base": bool(
            all_legs.groupby("tour_id")["base_classification"].nunique(dropna=False).le(1).all()
        ),
        "fare_not_below_flagfall_for_assigned_types": min_flagfall_ok,
        "negative_fares": int((base["total_fare_distance_only_hkd"] < 0).sum()),
        "currency": "HKD",
        "official_parameters_have_source_and_effective_date": bool(
            fare_rules[["fare_effective_date", "source_url", "source_download_date"]].notna().all().all()
        ),
        "plans_facilities_network_hashes_unchanged": hashes_before == hashes_after,
        "hash_before": hashes_before,
        "hash_after": hashes_after,
        "git_status_before_data_matsim_agents_hongkong": git_before,
        "git_status_after_data_matsim_agents_hongkong": git_after,
        "git_status_data_matsim_agents_hongkong_unchanged_and_empty": git_before == "" and git_after == "",
        "unrouted_plan_leg_mode_counts": {str(k): int(v) for k, v in sorted(plan_counts.items())},
        "route_distance_unavailable_share_base": float((~base["route_available"]).mean()),
        "congestion_proxy_unavailable_share_base": float(base["congestion_proxy_status"].ne("available").mean()),
        "taxi_type_unresolved_share_base": float(base["taxi_type"].eq("unresolved").mean()),
        "tolled_tunnel_share_base": float(base["tunnel_surcharge_hkd"].gt(0).mean()),
        "fare_boundary_tests": boundary_tests,
        "monotonicity_note": "Discrete fare function is monotone by construction; boundary tests verify ceiling jumps.",
        "non_modification_statement": (
            "No MATSim plans, config, facilities, vehicles, network, Java runner, modes, activities, OD, "
            "departure times, road capacities, or scoring parameters are modified."
        ),
    }
    return validation_result


def main() -> None:
    args = parse_args()
    args.fare_dir.mkdir(parents=True, exist_ok=True)
    hashes_before = hash_inputs(args.v2_dir, args.network_path)
    git_before = git_status_matsim_agents()

    fare_rules = pd.read_csv(args.fare_dir / "taxi_fare_rules.csv")
    all_legs, preserved_counts = prepare_all_taxi_leg_candidates(args)
    scenario_frames = {}
    for scenario in SCENARIOS:
        frame = scenario_frame(all_legs, scenario, fare_rules)
        frame.to_parquet(args.fare_dir / f"taxi_leg_fare_estimates_{scenario}.parquet", index=False)
        scenario_frames[scenario] = frame

    for path in args.fare_dir.glob("taxi_fare_summary_by_*.csv"):
        path.unlink()
    for scenario in SCENARIOS:
        write_summaries(scenario_frames[scenario], scenario, args.fare_dir)

    hashes_after = hash_inputs(args.v2_dir, args.network_path)
    git_after = git_status_matsim_agents()
    plan_counts = count_plan_modes(args.v2_dir / "plans_unrouted_5pct_v2.xml.gz")
    result = validation(
        scenario_frames,
        all_legs,
        preserved_counts,
        fare_rules,
        hashes_before,
        hashes_after,
        git_before,
        git_after,
        plan_counts,
    )
    (args.fare_dir / "taxi_fare_model_validation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "out_dir": args.fare_dir.as_posix(),
                "scenario_legs": {scenario: int(len(frame)) for scenario, frame in scenario_frames.items()},
                "hashes_unchanged": hashes_before == hashes_after,
                "matsim_agents_git_status_empty_before_after": git_before == "" and git_after == "",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
