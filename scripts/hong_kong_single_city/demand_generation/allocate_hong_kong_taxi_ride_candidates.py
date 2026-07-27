#!/usr/bin/env python3
"""Allocate Hong Kong unspecified ride tours to taxi/other_ride scenarios.

This script is read-only with respect to MATSim plans. It creates auxiliary
classification tables for taxi calibration without editing plans XML, activity
chains, OD, departure times, or leg counts.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point


ROOT = Path(__file__).resolve().parents[3]
WINDOWS_ROOT = Path(r"F:\Matsim\matsim-example-project")
PROJECT_ROOT = WINDOWS_ROOT if WINDOWS_ROOT.exists() else ROOT
DATA_ROOT = PROJECT_ROOT / "data"

AUDIT_DIR = DATA_ROOT / "taxi/hongkong/processed/taxi_initial_plan_audit_2026_jan_jun"
V2_DIR = DATA_ROOT / "matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice"
V1_DIR = DATA_ROOT / "matsim_agents/hongkong/typical_weekday_5pct_v1"
HOUSEHOLD_DIR = DATA_ROOT / "matsim_agents/hongkong/synthetic_households_tcs2022"
GRID_PATH = (
    DATA_ROOT
    / "worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid"
    / "CityAndRegionSplit/hong_kong_fixed_link_grid/regions.shp"
)
OUT_DIR = DATA_ROOT / "taxi/hongkong/processed/taxi_initial_plan_allocation_v1"

SAMPLE_RATE = 0.05
EXPANSION_WEIGHT = 20.0
RANDOM_SEED = 20260727
SCENARIO_OFFSETS = {"low": 11, "base": 23, "high": 37}
STRATA_COLUMNS = [
    "population_group",
    "activity_purpose",
    "departure_period",
    "origin_tcs_zone",
    "distance_band",
    "tour_leg_count",
]


@dataclass(frozen=True)
class ScenarioTarget:
    scenario: str
    official_statistic: str
    total_taxi_legs_target: int
    additional_taxi_legs_target: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-dir", type=Path, default=AUDIT_DIR)
    parser.add_argument("--v1-dir", type=Path, default=V1_DIR)
    parser.add_argument("--v2-dir", type=Path, default=V2_DIR)
    parser.add_argument("--household-dir", type=Path, default=HOUSEHOLD_DIR)
    parser.add_argument("--grid-path", type=Path, default=GRID_PATH)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--seed", type=int, default=RANDOM_SEED)
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


def hash_plan_inputs(v2_dir: Path) -> dict[str, str]:
    names = [
        "plans_unrouted_5pct_v2.xml.gz",
        "plans_routed_5pct_v2.xml.gz",
        "facilities_5pct_v2.xml.gz",
    ]
    return {name: sha256(v2_dir / name) for name in names}


def count_plan_leg_modes(plans_path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    with gzip.open(plans_path, "rb") as handle:
        for _, elem in ET.iterparse(handle, events=("end",)):
            if elem.tag.rsplit("}", 1)[-1] == "leg":
                mode = elem.attrib.get("mode", "")
                counts[mode] = counts.get(mode, 0) + 1
            elem.clear()
    return counts


def read_manifest_with_mode_detail(v1_dir: Path, v2_dir: Path) -> pd.DataFrame:
    manifest = pd.read_parquet(v2_dir / "agent_trip_manifest_v2.parquet")
    v1_manifest = pd.read_parquet(v1_dir / "agent_trip_manifest.parquet")
    detail = v1_manifest[["person_id", "leg_sequence", "mode_detail"]].copy()
    merged = manifest.merge(detail, on=["person_id", "leg_sequence"], how="left")
    merged["mode_detail"] = merged["mode_detail"].fillna("")
    return merged


def classify_existing_ride(row: pd.Series) -> str:
    if bool(row["is_discretionary"]):
        return "unspecified_ride"
    detail = str(row.get("mode_detail", "") or "")
    if detail == "taxi":
        return "taxi"
    if detail in {"private_car_passenger_van", "private_vehicle"}:
        return "private_car_passenger"
    if detail == "spb":
        return "school_bus"
    return "unspecified_ride"


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


def distance_band(distance_km: float) -> str:
    if pd.isna(distance_km):
        return "unknown"
    if distance_km < 2:
        return "00_0_2km"
    if distance_km < 5:
        return "01_2_5km"
    if distance_km < 10:
        return "02_5_10km"
    if distance_km < 20:
        return "03_10_20km"
    return "04_20km_plus"


def compact_chain(values: list[object]) -> str:
    cleaned = []
    for value in values:
        if value is None or pd.isna(value):
            continue
        text = str(value)
        if text and text != "-1":
            cleaned.append(text)
    return ">".join(cleaned) if cleaned else "unknown"


def grid_tcs_lookup(household_dir: Path, v1_dir: Path) -> dict[int, int]:
    frames = []
    for path in [
        household_dir / "synthetic_households.parquet",
        v1_dir / "sampled_households.parquet",
    ]:
        if path.exists():
            frame = pd.read_parquet(path, columns=["grid_id", "tcs_zone"])
            frame = frame.loc[frame["tcs_zone"].between(1, 26)].copy()
            frames.append(frame)
    if not frames:
        return {}
    households = pd.concat(frames, ignore_index=True)
    lookup = (
        households.groupby(["grid_id", "tcs_zone"], as_index=False)
        .size()
        .sort_values(["grid_id", "size", "tcs_zone"], ascending=[True, False, True])
        .drop_duplicates("grid_id")
        .set_index("grid_id")["tcs_zone"]
        .astype(int)
        .to_dict()
    )
    return {int(grid_id): int(zone) for grid_id, zone in lookup.items()}


def parse_facility_coordinates(facilities_path: Path, needed_ids: set[str]) -> pd.DataFrame:
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


def facility_tcs_lookup(
    facilities: pd.DataFrame,
    grid_path: Path,
    grid_tcs: dict[int, int],
) -> dict[str, int]:
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
        unresolved[["facility_id"]].copy(),
        geometry=[Point(xy) for xy in zip(unresolved["x"], unresolved["y"])],
        crs=grid.crs,
    )
    joined = gpd.sjoin(points, grid[["tcs_zone", "geometry"]], predicate="within", how="left")
    for _, row in joined.iterrows():
        result[str(row["facility_id"])] = int(row["tcs_zone"]) if pd.notna(row["tcs_zone"]) else -1
    return result


def enrich_person_attributes(v1_dir: Path) -> pd.DataFrame:
    people = pd.read_parquet(v1_dir / "sampled_agents.parquet")
    columns = [
        "person_id",
        "household_id",
        "age",
        "sex",
        "dcca",
        "grid_id",
        "tcs_zone",
        "household_private_vehicle_count",
        "potential_household_vehicle_access",
        "is_designated_driver",
        "assigned_vehicle_count",
        "income_band_tcs",
        "housing_type",
        "visitor_day_kind",
    ]
    present = [column for column in columns if column in people.columns]
    return people[present].drop_duplicates("person_id")


def make_candidate_legs(
    manifest: pd.DataFrame,
    assignments: pd.DataFrame,
    v1_dir: Path,
    v2_dir: Path,
    household_dir: Path,
    grid_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    ride = manifest.loc[manifest["mode"].eq("ride")].copy()
    ride["current_ride_subtype"] = ride.apply(classify_existing_ride, axis=1)
    candidates = ride.loc[ride["current_ride_subtype"].eq("unspecified_ride")].copy()

    needed_facilities = set(candidates["origin_facility_id"].dropna().astype(str))
    needed_facilities.update(candidates["destination_facility_id"].dropna().astype(str))
    facilities = parse_facility_coordinates(v2_dir / "facilities_5pct_v2.xml.gz", needed_facilities)
    facility_coord = facilities.set_index("facility_id")[["x", "y"]].to_dict("index")
    grid_tcs = grid_tcs_lookup(household_dir, v1_dir)
    facility_zone = facility_tcs_lookup(facilities, grid_path, grid_tcs)

    assignments = assignments.loc[assignments["initial_discretionary_mode"].eq("ride")].copy()
    assignment_lookup = assignments.set_index("person_id").to_dict("index")
    person_attrs = enrich_person_attributes(v1_dir)

    leg_rows = []
    tour_rows = []

    for person_id, group in candidates.sort_values(["person_id", "leg_sequence"]).groupby("person_id", sort=False):
        first = group.iloc[0]
        tour_id = f"{person_id}::unspecified_ride_tour"
        population_group = str(first["population_group"])
        role = str(first["role"])
        is_resident_discretionary = population_group == "resident" and bool(first["is_discretionary"])
        assignment = assignment_lookup.get(person_id) if is_resident_discretionary else None

        leg_zones: list[tuple[int, int]] = []
        if assignment is not None:
            home_zone = int(assignment.get("tcs_zone", -1))
            first_zone = int(assignment.get("first_zone", -1))
            second_zone = int(assignment.get("second_zone", -1))
            if int(assignment.get("new_leg_count", len(group))) == 3:
                leg_zones = [(home_zone, first_zone), (first_zone, second_zone), (second_zone, home_zone)]
            else:
                leg_zones = [(home_zone, first_zone), (first_zone, home_zone)]

        leg_distances = []
        for i, (_, leg) in enumerate(group.iterrows()):
            origin = str(leg["origin_facility_id"])
            dest = str(leg["destination_facility_id"])
            ox = facility_coord.get(origin, {}).get("x", np.nan)
            oy = facility_coord.get(origin, {}).get("y", np.nan)
            dx = facility_coord.get(dest, {}).get("x", np.nan)
            dy = facility_coord.get(dest, {}).get("y", np.nan)
            distance_km = math.hypot(dx - ox, dy - oy) / 1000.0 if np.isfinite([ox, oy, dx, dy]).all() else np.nan
            leg_distances.append(distance_km)
            if i < len(leg_zones):
                oz, dz = leg_zones[i]
            else:
                oz = facility_zone.get(origin, -1)
                dz = facility_zone.get(dest, -1)
            leg_rows.append(
                {
                    "tour_id": tour_id,
                    "person_id": person_id,
                    "leg_sequence": int(leg["leg_sequence"]),
                    "population_group": population_group,
                    "role": role,
                    "origin_type": leg["origin_type"],
                    "destination_type": leg["destination_type"],
                    "origin_facility_id": origin,
                    "destination_facility_id": dest,
                    "departure_time_s": float(leg["departure_time_s"]),
                    "origin_tcs_zone": int(oz),
                    "destination_tcs_zone": int(dz),
                    "distance_km": distance_km,
                }
            )

        if assignment is not None:
            new_leg_count = int(assignment.get("new_leg_count", len(group)))
            first_purpose = str(assignment.get("first_purpose", "") or "")
            second_purpose = str(assignment.get("second_purpose", "") or "")
            activity_purpose = compact_chain([first_purpose, second_purpose])
            origin_tcs_zone = int(assignment.get("tcs_zone", -1))
            first_zone = int(assignment.get("first_zone", -1))
            second_zone = int(assignment.get("second_zone", -1))
            source = "resident_discretionary_ride_assignment"
        else:
            new_leg_count = int(len(group))
            purpose_values = [
                value
                for value in group["destination_type"].tolist()
                if str(value) not in {"home", "border", "accommodation"}
            ]
            activity_purpose = "visitor_" + compact_chain(purpose_values)
            origin_tcs_zone = int(leg_rows[-len(group)]["origin_tcs_zone"])
            zones = [row["destination_tcs_zone"] for row in leg_rows[-len(group) :]]
            first_zone = int(zones[0]) if zones else -1
            second_zone = int(zones[1]) if len(zones) > 1 else -1
            source = "visitor_tcs_proxy_unspecified_ride"

        departure = float(group["departure_time_s"].min())
        tour_distance_km = float(np.nansum(leg_distances)) if leg_distances else np.nan
        tour_rows.append(
            {
                "tour_id": tour_id,
                "person_id": person_id,
                "population_group": population_group,
                "role": role,
                "classification_source": source,
                "activity_purpose": activity_purpose,
                "tour_leg_count": new_leg_count,
                "manifest_ride_leg_count": int(len(group)),
                "leg_sequences": "|".join(group["leg_sequence"].astype(str)),
                "tour_departure_time_s": departure,
                "departure_period": departure_period(departure),
                "origin_tcs_zone": origin_tcs_zone,
                "first_destination_tcs_zone": first_zone,
                "second_destination_tcs_zone": second_zone,
                "tcs26_tour_chain": compact_chain([origin_tcs_zone, first_zone, second_zone, origin_tcs_zone]),
                "tour_distance_km": tour_distance_km,
                "distance_band": distance_band(tour_distance_km),
            }
        )

    legs = pd.DataFrame(leg_rows)
    tours = pd.DataFrame(tour_rows).merge(person_attrs, on="person_id", how="left", suffixes=("", "_person"))
    tours["candidate_leg_count"] = tours["tour_leg_count"].astype(int)
    return legs, tours


def scenario_targets(official: pd.DataFrame, audit: pd.DataFrame) -> tuple[list[ScenarioTarget], dict[str, int]]:
    explicit_taxi = int(audit.loc[audit["ride_subtype"].eq("taxi"), "legs_5pct"].sum())
    preserved = {
        "explicit_taxi": explicit_taxi,
        "private_car_passenger": int(audit.loc[audit["ride_subtype"].eq("private_car_passenger"), "legs_5pct"].sum()),
        "school_bus": int(audit.loc[audit["ride_subtype"].eq("school_bus"), "legs_5pct"].sum()),
        "unspecified_ride": int(audit.loc[audit["ride_subtype"].eq("unspecified_ride"), "legs_5pct"].sum()),
    }
    controls = {
        "low": ("available_month_min", float(official["model_5pct_daily_pax_target"].min())),
        "base": ("available_month_mean", float(official["model_5pct_daily_pax_target"].mean())),
        "high": ("available_month_max", float(official["model_5pct_daily_pax_target"].max())),
    }
    targets = []
    for scenario, (statistic, value) in controls.items():
        total = int(round(value))
        targets.append(
            ScenarioTarget(
                scenario=scenario,
                official_statistic=statistic,
                total_taxi_legs_target=total,
                additional_taxi_legs_target=total - explicit_taxi,
            )
        )
    return targets, preserved


def quota_table(tours: pd.DataFrame, additional_target: int) -> pd.DataFrame:
    strata = tours.groupby(STRATA_COLUMNS, dropna=False, as_index=False).agg(
        candidate_tours=("tour_id", "count"),
        candidate_legs=("candidate_leg_count", "sum"),
    )
    total_legs = float(strata["candidate_legs"].sum())
    strata["ideal_taxi_legs"] = strata["candidate_legs"] / total_legs * float(additional_target)
    strata["quota_floor"] = np.floor(strata["ideal_taxi_legs"]).astype(int)
    remainder = additional_target - int(strata["quota_floor"].sum())
    strata["quota_remainder"] = strata["ideal_taxi_legs"] - strata["quota_floor"]
    strata = strata.sort_values(STRATA_COLUMNS).reset_index(drop=True)
    if remainder > 0:
        order = strata.sort_values(["quota_remainder"] + STRATA_COLUMNS, ascending=[False] + [True] * len(STRATA_COLUMNS))
        strata.loc[order.index[:remainder], "quota_floor"] += 1
    strata = strata.rename(columns={"quota_floor": "allocated_taxi_leg_quota"})
    return strata.sort_values(STRATA_COLUMNS).reset_index(drop=True)


def counts_for_delta(delta: int, available: dict[int, int]) -> tuple[dict[int, int], int]:
    best: tuple[int, int, int, int] | None = None
    max_three = min(available.get(3, 0), math.ceil(delta / 3) + 2)
    for c3 in range(max_three + 1):
        max_two = min(available.get(2, 0), math.ceil(max(delta - 3 * c3, 0) / 2) + 2)
        for c2 in range(max_two + 1):
            remaining = delta - 3 * c3 - 2 * c2
            if 0 <= remaining <= available.get(1, 0):
                return {1: remaining, 2: c2, 3: c3}, 0
            if remaining > 0:
                c1 = min(remaining, available.get(1, 0))
            else:
                c1 = 0
            achieved = 3 * c3 + 2 * c2 + c1
            error = abs(delta - achieved)
            candidate = (error, -achieved, c1, c2, c3)
            if best is None or candidate < best:
                best = candidate
    assert best is not None
    _, achieved_neg, c1, c2, c3 = best
    achieved = -achieved_neg
    return {1: c1, 2: c2, 3: c3}, delta - achieved


def allocate_scenario(
    tours: pd.DataFrame,
    target: ScenarioTarget,
    seed: int,
) -> tuple[pd.Series, pd.DataFrame, dict[str, object]]:
    rng = np.random.default_rng(seed + SCENARIO_OFFSETS[target.scenario])
    working = tours.copy()
    working["random_score"] = rng.random(len(working))
    quotas = quota_table(working, target.additional_taxi_legs_target)
    working = working.merge(quotas[STRATA_COLUMNS + ["allocated_taxi_leg_quota"]], on=STRATA_COLUMNS, how="left")
    working["allocated_taxi_leg_quota"] = working["allocated_taxi_leg_quota"].fillna(0).astype(int)

    selected = pd.Series(False, index=working.index)
    for _, group in working.groupby(STRATA_COLUMNS, dropna=False, sort=False):
        leg_count = int(group["candidate_leg_count"].iloc[0])
        quota = int(group["allocated_taxi_leg_quota"].iloc[0])
        n_select = min(len(group), int(round(quota / max(leg_count, 1))))
        chosen = group.sort_values("random_score").head(n_select).index
        selected.loc[chosen] = True

    current = int(working.loc[selected, "candidate_leg_count"].sum())
    delta = target.additional_taxi_legs_target - current
    repair_error = 0
    if delta != 0:
        if delta > 0:
            pool = working.loc[~selected].copy()
            pool["repair_priority"] = pool["random_score"]
            available = pool["candidate_leg_count"].value_counts().to_dict()
            needed, repair_error = counts_for_delta(delta, {int(k): int(v) for k, v in available.items()})
            for leg_count, count in needed.items():
                if count > 0:
                    chosen = pool.loc[pool["candidate_leg_count"].eq(leg_count)].sort_values("repair_priority").head(count).index
                    selected.loc[chosen] = True
        else:
            pool = working.loc[selected].copy()
            pool["repair_priority"] = 1.0 - pool["random_score"]
            available = pool["candidate_leg_count"].value_counts().to_dict()
            needed, repair_error = counts_for_delta(abs(delta), {int(k): int(v) for k, v in available.items()})
            for leg_count, count in needed.items():
                if count > 0:
                    chosen = pool.loc[pool["candidate_leg_count"].eq(leg_count)].sort_values("repair_priority").head(count).index
                    selected.loc[chosen] = False

    selected_legs = int(working.loc[selected, "candidate_leg_count"].sum())
    working["selected"] = selected.to_numpy()
    working["selected_candidate_leg_count"] = np.where(working["selected"], working["candidate_leg_count"], 0)
    quotas = quotas.merge(
        working.groupby(STRATA_COLUMNS, dropna=False, as_index=False).agg(
            selected_tours=("selected", "sum"),
            selected_taxi_legs=("selected_candidate_leg_count", "sum"),
        ),
        on=STRATA_COLUMNS,
        how="left",
    )
    quotas["selected_tours"] = quotas["selected_tours"].fillna(0).astype(int)
    quotas["selected_taxi_legs"] = quotas["selected_taxi_legs"].fillna(0).astype(int)
    quotas.insert(0, "scenario", target.scenario)

    metadata = {
        "scenario": target.scenario,
        "official_statistic": target.official_statistic,
        "total_taxi_legs_target": target.total_taxi_legs_target,
        "additional_taxi_legs_target": target.additional_taxi_legs_target,
        "selected_additional_taxi_legs": selected_legs,
        "selected_total_taxi_legs": selected_legs + (target.total_taxi_legs_target - target.additional_taxi_legs_target),
        "integerization_error_5pct_legs": selected_legs - target.additional_taxi_legs_target,
        "repair_error_5pct_legs": repair_error,
        "random_seed": seed + SCENARIO_OFFSETS[target.scenario],
    }
    return selected, quotas, metadata


def distribution_tables(tours: pd.DataFrame, legs: pd.DataFrame, scenarios: list[str], out_dir: Path) -> None:
    tour_dims = {
        "purpose": ["activity_purpose"],
        "departure_period": ["departure_period"],
        "distance_band": ["distance_band"],
        "population_group": ["population_group", "role"],
    }
    for name, dims in tour_dims.items():
        rows = []
        for scenario in scenarios:
            selected = tours.loc[tours[f"{scenario}_classification"].eq("taxi")]
            frame = selected.groupby(dims, dropna=False, as_index=False).agg(
                selected_taxi_tours=("tour_id", "count"),
                selected_taxi_legs=("candidate_leg_count", "sum"),
            )
            frame.insert(0, "scenario", scenario)
            rows.append(frame)
        pd.concat(rows, ignore_index=True).to_csv(
            out_dir / f"taxi_allocation_distribution_by_{name}.csv",
            index=False,
            encoding="utf-8-sig",
        )

    rows = []
    for scenario in scenarios:
        leg_frame = legs.loc[legs[f"{scenario}_classification"].eq("taxi")]
        frame = leg_frame.groupby(
            ["origin_tcs_zone", "destination_tcs_zone"], dropna=False, as_index=False
        ).agg(selected_taxi_legs=("tour_id", "count"), selected_taxi_tours=("tour_id", "nunique"))
        frame.insert(0, "scenario", scenario)
        rows.append(frame)
    pd.concat(rows, ignore_index=True).to_csv(
        out_dir / "taxi_allocation_distribution_by_tcs26_od.csv",
        index=False,
        encoding="utf-8-sig",
    )


def main() -> None:
    args = parse_args()
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    plan_hash_before = hash_plan_inputs(args.v2_dir)
    git_status_before = git_status_matsim_agents()

    official = pd.read_csv(args.audit_dir / "taxi_official_daily_control.csv")
    audit = pd.read_csv(args.audit_dir / "taxi_initial_plan_audit.csv")
    summary = json.loads((args.audit_dir / "taxi_initial_plan_gap_summary.json").read_text(encoding="utf-8"))
    manifest = read_manifest_with_mode_detail(args.v1_dir, args.v2_dir)
    assignments = pd.read_parquet(args.v2_dir / "resident_discretionary_activity_assignments.parquet")

    legs, tours = make_candidate_legs(
        manifest=manifest,
        assignments=assignments,
        v1_dir=args.v1_dir,
        v2_dir=args.v2_dir,
        household_dir=args.household_dir,
        grid_path=args.grid_path,
    )
    targets, preserved = scenario_targets(official, audit)
    if int(tours["candidate_leg_count"].sum()) != preserved["unspecified_ride"]:
        raise ValueError("Candidate tour legs do not match audited unspecified_ride legs")

    all_quotas = []
    scenario_meta = []
    for target in targets:
        selected, quotas, metadata = allocate_scenario(tours, target, args.seed)
        tours[f"{target.scenario}_selected_as_taxi"] = selected.to_numpy()
        tours[f"{target.scenario}_classification"] = np.where(selected.to_numpy(), "taxi", "other_ride")
        all_quotas.append(quotas)
        scenario_meta.append(metadata)

    scenario_names = [target.scenario for target in targets]
    leg_classes = legs.merge(
        tours[["tour_id"] + [f"{scenario}_classification" for scenario in scenario_names]],
        on="tour_id",
        how="left",
        validate="many_to_one",
    )
    distribution_tables(tours, leg_classes, scenario_names, out_dir)

    pd.concat(all_quotas, ignore_index=True).to_csv(
        out_dir / "taxi_allocation_stratum_quota.csv", index=False, encoding="utf-8-sig"
    )
    tours.sort_values(["person_id", "tour_id"]).to_csv(
        out_dir / "taxi_candidate_tour_classification.csv", index=False, encoding="utf-8-sig"
    )
    leg_classes.sort_values(["person_id", "leg_sequence"]).to_csv(
        out_dir / "taxi_candidate_leg_classification.csv", index=False, encoding="utf-8-sig"
    )

    plan_counts = count_plan_leg_modes(args.v2_dir / "plans_unrouted_5pct_v2.xml.gz")
    plan_hash_after = hash_plan_inputs(args.v2_dir)
    git_status_after = git_status_matsim_agents()

    output_summary = {
        "scenario_family": "hong_kong_taxi_initial_plan_allocation_v1",
        "random_seed_base": args.seed,
        "audit_summary_source": summary,
        "preserved_current_ride_subtypes_5pct_legs": preserved,
        "candidate_unspecified_ride_tours": int(len(tours)),
        "candidate_unspecified_ride_legs": int(tours["candidate_leg_count"].sum()),
        "stratification_columns": STRATA_COLUMNS,
        "scenario_targets": scenario_meta,
        "plans_integrity": {
            "hash_before": plan_hash_before,
            "hash_after": plan_hash_after,
            "hashes_unchanged": plan_hash_before == plan_hash_after,
            "git_status_before_data_matsim_agents_hongkong": git_status_before,
            "git_status_after_data_matsim_agents_hongkong": git_status_after,
            "git_status_unchanged": git_status_before == git_status_after,
            "unrouted_plan_leg_mode_counts": {str(k): int(v) for k, v in sorted(plan_counts.items())},
        },
        "non_modification_statement": (
            "This allocation writes only data/taxi outputs and does not modify MATSim plans, "
            "facilities, activities, OD, departure times, or leg counts."
        ),
        "outputs": [
            "taxi_candidate_tour_classification.csv",
            "taxi_candidate_leg_classification.csv",
            "taxi_allocation_stratum_quota.csv",
            "taxi_allocation_distribution_by_purpose.csv",
            "taxi_allocation_distribution_by_departure_period.csv",
            "taxi_allocation_distribution_by_tcs26_od.csv",
            "taxi_allocation_distribution_by_distance_band.csv",
            "taxi_allocation_distribution_by_population_group.csv",
            "taxi_allocation_summary.json",
        ],
    }
    (out_dir / "taxi_allocation_summary.json").write_text(
        json.dumps(output_summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(
        json.dumps(
            {
                "out_dir": out_dir.as_posix(),
                "candidate_tours": int(len(tours)),
                "candidate_legs": int(tours["candidate_leg_count"].sum()),
                "scenario_targets": scenario_meta,
                "plans_hashes_unchanged": plan_hash_before == plan_hash_after,
                "matsim_agents_git_status_unchanged": git_status_before == git_status_after,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
