#!/usr/bin/env python3
"""Estimate low/base/high offline Hong Kong private-car leg costs."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUTPUT = REPO_ROOT / "data/transport_costs/hongkong/car_cost_v1"
CANONICAL_PROJECT = Path(r"F:\Matsim\matsim-example-project")
DEFAULT_INPUT_PROJECT = CANONICAL_PROJECT if CANONICAL_PROJECT.exists() else REPO_ROOT
SCENARIOS = ("low", "base", "high")
ROAD_LINK_RE = re.compile(r"^road_(\d+)_")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-project-root", type=Path, default=DEFAULT_INPUT_PROJECT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tag_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def parse_time_s(value: object) -> float:
    if value is None or value == "":
        return float("nan")
    if isinstance(value, (int, float)):
        return float(value)
    parts = str(value).split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    return float(value)


def input_paths(input_project: Path) -> dict[str, Path]:
    v2 = (
        input_project
        / "data/matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice"
    )
    supply = (
        input_project
        / "data/transit/hongkong/processed/"
        "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_ferry_core_v1_cap010"
    )
    paths = {
        "plans_routed_5pct_v2.xml.gz": v2 / "plans_routed_5pct_v2.xml.gz",
        "plans_unrouted_5pct_v2.xml.gz": v2 / "plans_unrouted_5pct_v2.xml.gz",
        "facilities_5pct_v2.xml.gz": v2 / "facilities_5pct_v2.xml.gz",
        "privateVehicles_5pct.xml.gz": v2 / "privateVehicles_5pct.xml.gz",
        "agent_trip_manifest_v2.parquet": v2 / "agent_trip_manifest_v2.parquet",
        "config_hong_kong_5pct_v2_activity_modechoice_50it.xml": (
            v2 / "config_hong_kong_5pct_v2_activity_modechoice_50it.xml"
        ),
        "network.xml.gz": supply / "network.xml.gz",
        "transitSchedule_5pct.xml.gz": supply / "transitSchedule_5pct.xml.gz",
        "transitVehicles_10pct.xml.gz": supply / "transitVehicles_10pct.xml.gz",
        "synthetic_households.parquet": (
            input_project
            / "data/matsim_agents/hongkong/synthetic_households_tcs2022/"
            "synthetic_households.parquet"
        ),
        "regions.shp": (
            input_project
            / "data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/"
            "CityAndRegionSplit/hong_kong_fixed_link_grid/regions.shp"
        ),
    }
    missing = [path for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing required inputs: {missing}")
    return paths


def protected_hashes(paths: dict[str, Path]) -> dict[str, str]:
    protected = (
        "plans_routed_5pct_v2.xml.gz",
        "plans_unrouted_5pct_v2.xml.gz",
        "facilities_5pct_v2.xml.gz",
        "privateVehicles_5pct.xml.gz",
        "agent_trip_manifest_v2.parquet",
        "config_hong_kong_5pct_v2_activity_modechoice_50it.xml",
        "network.xml.gz",
        "transitSchedule_5pct.xml.gz",
        "transitVehicles_10pct.xml.gz",
    )
    return {name: sha256_file(paths[name]) for name in protected}


def git_status_matsim_agents(input_project: Path) -> str:
    result = subprocess.run(
        [
            "git",
            "status",
            "--short",
            "--untracked-files=no",
            "--",
            "data/matsim_agents/hongkong",
        ],
        cwd=input_project,
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def vehicle_types(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    with gzip.open(path, "rb") as handle:
        for _, element in ET.iterparse(handle, events=("end",)):
            if tag_name(element) == "vehicle":
                result[element.attrib["id"]] = element.attrib["type"]
            element.clear()
    return result


def toll_feature_index(rules: pd.DataFrame) -> dict[int, str]:
    result: dict[int, str] = {}
    for _, row in rules.drop_duplicates("toll_facility_id").iterrows():
        for token in str(row["feature_ids"]).split("|"):
            feature_id = int(token)
            facility = str(row["toll_facility_id"])
            previous = result.get(feature_id)
            if previous is not None and previous != facility:
                raise ValueError(
                    f"Toll feature {feature_id} maps to {previous} and {facility}"
                )
            result[feature_id] = facility
    return result


def parse_routed_car_legs(
    plans_path: Path,
    needed: set[tuple[str, int]],
    feature_index: dict[int, str],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    current_person = ""
    in_selected_plan = False
    main_activity_count = 0
    capture: dict[str, Any] | None = None

    with gzip.open(plans_path, "rb") as handle:
        for event, element in ET.iterparse(handle, events=("start", "end")):
            tag = tag_name(element)
            if event == "start" and tag == "person":
                current_person = element.attrib.get("id", "")
            elif event == "start" and tag == "plan":
                selected = element.attrib.get("selected", "yes").lower()
                in_selected_plan = selected in {"yes", "true", "1"}
                if in_selected_plan:
                    main_activity_count = 0
            elif event == "start" and tag == "activity" and in_selected_plan:
                activity_type = element.attrib.get("type", "")
                is_stage = activity_type.endswith("interaction")
                if not is_stage:
                    main_activity_count += 1
            elif event == "start" and tag == "leg" and in_selected_plan:
                sequence = main_activity_count - 1
                key = (current_person, sequence)
                if element.attrib.get("mode") == "car" and key in needed:
                    capture = {
                        "person_id": current_person,
                        "leg_sequence": sequence,
                        "routed_mode": "car",
                        "route_departure_time_s": parse_time_s(
                            element.attrib.get("dep_time")
                        ),
                        "route_travel_time_s": parse_time_s(
                            element.attrib.get("trav_time")
                        ),
                    }
            elif event == "end" and tag == "route" and capture is not None:
                links = (element.text or "").split()
                matches: dict[str, tuple[int, str]] = {}
                for index, link_id in enumerate(links):
                    match = ROAD_LINK_RE.match(link_id)
                    if match is None:
                        continue
                    facility = feature_index.get(int(match.group(1)))
                    if facility is not None and facility not in matches:
                        matches[facility] = (index, link_id)
                capture.update(
                    {
                        "route_type": element.attrib.get("type", ""),
                        "route_distance_m": float(element.attrib["distance"])
                        if element.attrib.get("distance")
                        else float("nan"),
                        "route_travel_time_s": parse_time_s(
                            element.attrib.get("trav_time")
                        )
                        if element.attrib.get("trav_time")
                        else capture["route_travel_time_s"],
                        "route_start_link": element.attrib.get("start_link", ""),
                        "route_end_link": element.attrib.get("end_link", ""),
                        "vehicle_ref_id": element.attrib.get("vehicleRefId", ""),
                        "route_link_count": len(links),
                        "has_complete_link_sequence": bool(links),
                        "toll_feature_matches": json.dumps(
                            {
                                facility: {"index": index, "link_id": link_id}
                                for facility, (index, link_id) in matches.items()
                            },
                            sort_keys=True,
                        ),
                    }
                )
            elif event == "end" and tag == "leg" and capture is not None:
                rows.append(capture)
                capture = None
            elif event == "end" and tag == "plan":
                in_selected_plan = False
            if event == "end":
                element.clear()

    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError("No routed car legs were parsed")
    duplicates = frame.duplicated(["person_id", "leg_sequence"]).sum()
    if duplicates:
        raise ValueError(f"Duplicate routed car keys: {duplicates}")
    return frame


def parse_facilities(path: Path, needed_ids: set[str]) -> pd.DataFrame:
    rows = []
    with gzip.open(path, "rb") as handle:
        for _, element in ET.iterparse(handle, events=("end",)):
            if tag_name(element) == "facility":
                facility_id = element.attrib.get("id", "")
                if facility_id in needed_ids:
                    rows.append(
                        {
                            "facility_id": facility_id,
                            "facility_x": float(element.attrib["x"]),
                            "facility_y": float(element.attrib["y"]),
                            "facility_link_id": element.attrib.get("linkId", ""),
                        }
                    )
            element.clear()
    frame = pd.DataFrame(rows)
    if frame["facility_id"].duplicated().any():
        raise ValueError("Duplicate facility IDs")
    return frame


def grid_tcs_lookup(household_path: Path) -> dict[int, int]:
    frame = pd.read_parquet(household_path, columns=["grid_id", "tcs_zone"])
    frame = frame.loc[frame["tcs_zone"].between(1, 26)]
    mode = (
        frame.groupby(["grid_id", "tcs_zone"], as_index=False)
        .size()
        .sort_values(["grid_id", "size", "tcs_zone"], ascending=[True, False, True])
        .drop_duplicates("grid_id")
    )
    return {
        int(row.grid_id): int(row.tcs_zone)
        for row in mode.itertuples(index=False)
    }


def facility_zone_lookup(
    facilities: pd.DataFrame, regions_path: Path, grid_to_tcs: dict[int, int]
) -> dict[str, int]:
    result: dict[str, int] = {}
    for facility_id in facilities["facility_id"].astype(str):
        if "_grid_" not in facility_id:
            continue
        try:
            grid_id = int(facility_id.rsplit("_grid_", 1)[1])
        except ValueError:
            continue
        if grid_id in grid_to_tcs:
            result[facility_id] = grid_to_tcs[grid_id]

    unresolved = facilities.loc[
        ~facilities["facility_id"].astype(str).isin(result)
    ].copy()
    if unresolved.empty:
        return result
    regions = gpd.read_file(regions_path)[["grid_id", "geometry"]].copy()
    regions["grid_id"] = regions["grid_id"].astype(int)
    regions["tcs_zone"] = regions["grid_id"].map(grid_to_tcs)
    points = gpd.GeoDataFrame(
        unresolved[["facility_id"]],
        geometry=[
            Point(x, y)
            for x, y in zip(unresolved["facility_x"], unresolved["facility_y"])
        ],
        crs=regions.crs,
    )
    joined = gpd.sjoin(
        points,
        regions[["tcs_zone", "geometry"]],
        how="left",
        predicate="within",
    )
    for row in joined.itertuples(index=False):
        result[str(row.facility_id)] = (
            int(row.tcs_zone) if pd.notna(row.tcs_zone) else -1
        )
    return result


def activity_group(activity_type: str) -> str:
    if activity_type == "home":
        return "home"
    if activity_type in {"work", "work_mobile", "business"}:
        return "work"
    if activity_type.startswith("school") or activity_type.startswith("education"):
        return "education"
    if activity_type == "shopping":
        return "shopping"
    if activity_type in {
        "dining",
        "leisure",
        "social",
        "vfr",
        "primary_activity",
        "secondary_activity",
    }:
        return "leisure"
    if activity_type in {"medical", "personal_business"}:
        return "medical_personal_business"
    if activity_type == "accommodation":
        return "visitor_accommodation"
    if activity_type in {"border", "external_activity"}:
        return "border"
    return "other"


def zone_group(zone: int) -> str:
    if 1 <= zone <= 4:
        return "hong_kong_island"
    if 5 <= zone <= 13:
        return "kowloon_urban"
    if 14 <= zone <= 26:
        return "new_territories_lantau"
    return "unresolved"


def attach_routes_and_context(
    car_manifest: pd.DataFrame,
    routes: pd.DataFrame,
    vehicle_type: dict[str, str],
    facility_zones: dict[str, int],
) -> pd.DataFrame:
    frame = car_manifest.merge(
        routes,
        on=["person_id", "leg_sequence"],
        how="left",
        validate="one_to_one",
    )
    frame["vehicle_class"] = frame["vehicle_ref_id"].map(vehicle_type).fillna(
        "unresolved"
    )
    frame["origin_tcs_zone"] = (
        frame["origin_facility_id"].map(facility_zones).fillna(-1).astype(int)
    )
    frame["destination_tcs_zone"] = (
        frame["destination_facility_id"].map(facility_zones).fillna(-1).astype(int)
    )
    frame["destination_activity_group"] = frame["destination_type"].map(
        activity_group
    )
    frame["destination_zone_group"] = frame["destination_tcs_zone"].map(zone_group)
    frame["arrival_time_s"] = (
        frame["route_departure_time_s"] + frame["route_travel_time_s"]
    )
    frame = frame.sort_values(
        ["vehicle_ref_id", "route_departure_time_s", "person_id", "leg_sequence"]
    ).reset_index(drop=True)
    grouped = frame.groupby("vehicle_ref_id", sort=False)
    frame["next_car_departure_time_s"] = grouped[
        "route_departure_time_s"
    ].shift(-1)
    frame["next_car_origin_facility_id"] = grouped["origin_facility_id"].shift(-1)
    valid_session = (
        frame["destination_facility_id"].eq(frame["next_car_origin_facility_id"])
        & frame["next_car_departure_time_s"].ge(frame["arrival_time_s"])
    )
    frame["parking_duration_s"] = np.where(
        valid_session,
        frame["next_car_departure_time_s"] - frame["arrival_time_s"],
        np.nan,
    )
    frame["parking_session_id"] = (
        frame["vehicle_ref_id"].astype(str)
        + "::"
        + frame["person_id"].astype(str)
        + "::"
        + frame["leg_sequence"].astype(str)
    )
    return frame.sort_values(["person_id", "leg_sequence"]).reset_index(drop=True)


def toll_lookup(
    toll_rules: pd.DataFrame,
) -> tuple[dict[str, pd.DataFrame], dict[str, str], dict[str, str]]:
    grouped = {
        facility: group.sort_values(["day_of_week_code", "start_time_s"]).copy()
        for facility, group in toll_rules.groupby("toll_facility_id")
    }
    sources = (
        toll_rules.groupby("toll_facility_id")["source_url"].first().astype(str).to_dict()
    )
    dates = (
        toll_rules.groupby("toll_facility_id")["effective_date"]
        .first()
        .astype(str)
        .to_dict()
    )
    return grouped, sources, dates


def toll_at_time(rules: pd.DataFrame, time_s: float) -> float:
    clock = int(math.floor(time_s)) % 86400
    candidates = rules.loc[
        rules["day_of_week_code"].isin(["A", "ALL"])
        & rules["start_time_s"].le(clock)
        & rules["end_time_s"].ge(clock)
    ]
    if len(candidates) != 1:
        raise ValueError(
            f"Expected one weekday toll rule at {clock}, got {len(candidates)}"
        )
    return float(candidates.iloc[0]["toll_hkd"])


def compute_tolls(
    legs: pd.DataFrame, toll_rules: pd.DataFrame
) -> tuple[dict[str, np.ndarray], pd.DataFrame]:
    grouped, sources, dates = toll_lookup(toll_rules)
    values = {scenario: np.zeros(len(legs), dtype=float) for scenario in SCENARIOS}
    audit_rows = []
    for position, row in enumerate(legs.itertuples(index=False)):
        matches = json.loads(row.toll_feature_matches or "{}")
        if row.vehicle_class != "private_car":
            audit_rows.append(
                {
                    "toll_status": "unresolved_out_of_scope_vehicle_class",
                    "toll_facilities": "",
                    "toll_link_ids": "",
                    "toll_passage_time_s": np.nan,
                    "toll_source": "",
                    "toll_effective_date": "",
                }
            )
            continue
        if not bool(row.has_complete_link_sequence):
            audit_rows.append(
                {
                    "toll_status": "ambiguous_incomplete_route_link_sequence",
                    "toll_facilities": "",
                    "toll_link_ids": "",
                    "toll_passage_time_s": np.nan,
                    "toll_source": "",
                    "toll_effective_date": "",
                }
            )
            continue
        if not matches:
            audit_rows.append(
                {
                    "toll_status": "confirmed_no_charge",
                    "toll_facilities": "",
                    "toll_link_ids": "",
                    "toll_passage_time_s": np.nan,
                    "toll_source": "official_gdb_feature_id_complete_route_audit",
                    "toll_effective_date": "2026-07-17",
                }
            )
            continue
        passage_times = []
        facilities = []
        link_ids = []
        source_values = []
        date_values = []
        for facility, evidence in sorted(matches.items()):
            if facility not in grouped:
                raise ValueError(f"No private-car rule for matched toll {facility}")
            fraction = (float(evidence["index"]) + 0.5) / max(
                int(row.route_link_count), 1
            )
            passage = float(row.route_departure_time_s) + fraction * float(
                row.route_travel_time_s
            )
            base = toll_at_time(grouped[facility], passage)
            window = [
                toll_at_time(grouped[facility], passage - 600),
                base,
                toll_at_time(grouped[facility], passage + 600),
            ]
            values["low"][position] += min(window)
            values["base"][position] += base
            values["high"][position] += max(window)
            passage_times.append(passage)
            facilities.append(facility)
            link_ids.append(str(evidence["link_id"]))
            source_values.append(sources[facility])
            date_values.append(dates[facility])
        audit_rows.append(
            {
                "toll_status": "confirmed_charge",
                "toll_facilities": "|".join(facilities),
                "toll_link_ids": "|".join(link_ids),
                "toll_passage_time_s": min(passage_times),
                "toll_source": "|".join(sorted(set(source_values))),
                "toll_effective_date": "|".join(sorted(set(date_values))),
            }
        )
    return values, pd.DataFrame(audit_rows)


def parking_charge(
    arrival_time_s: float, duration_s: float, rule: pd.Series
) -> tuple[float, str]:
    method = str(rule["pricing_method"])
    if not bool(rule["marginal_leg_cost_resolved"]):
        return 0.0, "unresolved_rule"
    if method in {
        "home_temporary_cost_zero_fixed_parking_separate",
        "monthly_subscription_marginal_zero_fixed_cost_separate",
    }:
        return 0.0, "resolved_zero_marginal"
    if method in {"representative_day_pass", "representative_night_pass"}:
        return float(rule["daily_cap_hkd"]), "resolved_proxy"
    if pd.isna(arrival_time_s) or pd.isna(duration_s) or duration_s < 0:
        if method == "hourly_or_part_capped_at_ten_hours":
            return float(rule["daily_cap_hkd"]), "resolved_proxy_duration_upper_bound"
        return 0.0, "unresolved_duration"
    units = int(math.ceil(float(duration_s) / float(rule["billing_increment_s"])))
    cost = 0.0
    for unit in range(units):
        clock = (float(arrival_time_s) + unit * float(rule["billing_increment_s"])) % 86400
        if float(rule["day_period_start_s"]) <= clock < float(
            rule["day_period_end_s"]
        ):
            cost += float(rule["hourly_day_hkd"])
        else:
            cost += float(rule["hourly_night_hkd"])
    if pd.notna(rule["daily_cap_hkd"]):
        cost = min(cost, float(rule["daily_cap_hkd"]))
    cost = max(cost, float(rule.get("minimum_charge_hkd", 0.0)))
    return cost, "resolved_proxy"


def compute_parking(
    legs: pd.DataFrame, parking_rules: pd.DataFrame
) -> tuple[dict[str, np.ndarray], dict[str, list[str]]]:
    rule_index = parking_rules.set_index(
        ["scenario", "zone_group", "activity_group"]
    )
    values = {scenario: np.zeros(len(legs), dtype=float) for scenario in SCENARIOS}
    status = {scenario: [] for scenario in SCENARIOS}
    for position, row in enumerate(legs.itertuples(index=False)):
        if row.vehicle_class != "private_car":
            for scenario in SCENARIOS:
                status[scenario].append("unresolved_out_of_scope_vehicle_class")
            continue
        for scenario in SCENARIOS:
            if row.destination_activity_group == "home":
                key = (
                    scenario,
                    row.destination_zone_group
                    if row.destination_zone_group != "unresolved"
                    else "new_territories_lantau",
                    "home",
                )
            elif row.destination_zone_group == "unresolved":
                values[scenario][position] = 0.0
                status[scenario].append("unresolved_destination_tcs_zone")
                continue
            else:
                key = (
                    scenario,
                    row.destination_zone_group,
                    row.destination_activity_group,
                )
            rule = rule_index.loc[key]
            cost, state = parking_charge(
                float(row.arrival_time_s),
                float(row.parking_duration_s),
                rule,
            )
            values[scenario][position] = cost
            status[scenario].append(state)
    return values, status


def base_leg_record(row: Any, scenario: str) -> dict[str, Any]:
    return {
        "person_id": row.person_id,
        "leg_sequence": int(row.leg_sequence),
        "mode": "car",
        "route_distance_m": float(row.route_distance_m),
        "destination_facility_id": row.destination_facility_id,
        "destination_tcs_zone": int(row.destination_tcs_zone),
        "destination_activity_type": row.destination_type,
        "arrival_time_s": float(row.arrival_time_s),
        "parking_duration_s": (
            float(row.parking_duration_s)
            if pd.notna(row.parking_duration_s)
            else np.nan
        ),
        "scenario": scenario,
        "record_scope": "leg_marginal_cost",
        "vehicle_ref_id": row.vehicle_ref_id,
        "vehicle_class": row.vehicle_class,
        "vehicle_powertrain": (
            "representative_hk_private_car_fleet_average"
            if row.vehicle_class == "private_car"
            else "not_assigned"
        ),
        "origin_facility_id": row.origin_facility_id,
        "origin_tcs_zone": int(row.origin_tcs_zone),
        "destination_activity_group": row.destination_activity_group,
        "parking_session_id": row.parking_session_id,
        "toll_facilities": row.toll_facilities,
        "toll_link_ids": row.toll_link_ids,
        "toll_status": row.toll_status,
        "unresolved_reason": "",
    }


def fixed_cost_rows(
    legs: pd.DataFrame,
    scenario: str,
    source_manifest: dict[str, Any],
) -> list[dict[str, Any]]:
    params = next(
        row
        for row in source_manifest["fixed_vehicle_ownership_cost_parameters"]
        if row["scenario"] == scenario
    )
    shares = source_manifest["licensed_private_car_fleet"]
    annual_licence = (
        float(shares["combustion_proxy_share"])
        * float(params["combustion_annual_licence_hkd"])
        + float(shares["electric_share"])
        * float(params["electric_annual_licence_hkd"])
    )
    daily_cost = (
        annual_licence + 12.0 * float(params["residential_monthly_parking_hkd"])
    ) / 365.0
    used = (
        legs.loc[legs["vehicle_class"].eq("private_car")]
        .sort_values(["vehicle_ref_id", "route_departure_time_s"])
        .drop_duplicates("vehicle_ref_id")
    )
    rows = []
    for row in used.itertuples(index=False):
        rows.append(
            {
                "person_id": row.person_id,
                "leg_sequence": -1,
                "mode": "car",
                "route_distance_m": np.nan,
                "destination_facility_id": "",
                "destination_tcs_zone": -1,
                "destination_activity_type": "",
                "arrival_time_s": np.nan,
                "parking_duration_s": np.nan,
                "cost_component": "fixed_vehicle_ownership_cost",
                "cost_hkd": daily_cost,
                "cost_source": params["source_url"],
                "cost_effective_date": params["effective_date"],
                "cost_quality": params["cost_quality"],
                "scenario": scenario,
                "record_scope": "vehicle_day_fixed_cost_not_leg",
                "vehicle_ref_id": row.vehicle_ref_id,
                "vehicle_class": "private_car",
                "vehicle_powertrain": "representative_hk_private_car_fleet_average",
                "origin_facility_id": "",
                "origin_tcs_zone": -1,
                "destination_activity_group": "",
                "parking_session_id": "",
                "toll_facilities": "",
                "toll_link_ids": "",
                "toll_status": "",
                "unresolved_reason": (
                    "Partial fixed cost: official vehicle licence plus residential "
                    "parking proxy; depreciation, finance, insurance and maintenance excluded."
                ),
            }
        )
    return rows


def scenario_output(
    legs: pd.DataFrame,
    scenario: str,
    energy_rule: pd.Series,
    energy_values: np.ndarray,
    toll_values: np.ndarray,
    parking_values: np.ndarray,
    parking_status: list[str],
    source_manifest: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    marginal = legs[
        [
            "person_id",
            "leg_sequence",
            "vehicle_class",
            "route_distance_m",
            "destination_facility_id",
            "destination_tcs_zone",
            "destination_type",
            "destination_activity_group",
            "toll_status",
        ]
    ].copy()
    marginal["energy_cost_hkd"] = energy_values
    marginal["toll_cost_hkd"] = toll_values
    marginal["parking_cost_hkd"] = parking_values
    marginal["parking_status"] = parking_status
    marginal["marginal_cost_complete"] = (
        marginal["vehicle_class"].eq("private_car")
        & ~marginal["parking_status"].str.startswith("unresolved")
        & ~marginal["toll_status"].str.startswith("ambiguous")
        & ~marginal["toll_status"].str.startswith("unresolved")
    )
    marginal["marginal_cost_hkd"] = (
        marginal["energy_cost_hkd"]
        + marginal["toll_cost_hkd"]
        + marginal["parking_cost_hkd"]
    )
    marginal["scenario"] = scenario

    for position, row in enumerate(legs.itertuples(index=False)):
        base = base_leg_record(row, scenario)
        if row.vehicle_class != "private_car":
            unresolved = dict(base)
            unresolved.update(
                {
                    "cost_component": "unresolved_cost",
                    "cost_hkd": 0.0,
                    "cost_source": "privateVehicles_5pct.xml.gz",
                    "cost_effective_date": "2026-07-23",
                    "cost_quality": "out_of_scope",
                    "unresolved_reason": (
                        "MATSim car-mode leg uses motorcycle vehicle type; private-car "
                        "energy, toll and parking rules are not applied."
                    ),
                }
            )
            rows.append(unresolved)
            continue

        energy = dict(base)
        energy.update(
            {
                "cost_component": "fuel_or_electricity",
                "cost_hkd": float(energy_values[position]),
                "cost_source": energy_rule["source_url"],
                "cost_effective_date": energy_rule["effective_date"],
                "cost_quality": energy_rule["cost_quality"],
            }
        )
        rows.append(energy)

        toll = dict(base)
        toll.update(
            {
                "cost_component": "toll",
                "cost_hkd": float(toll_values[position]),
                "cost_source": row.toll_source,
                "cost_effective_date": row.toll_effective_date,
                "cost_quality": (
                    "confirmed_official_feature_id_time_proxy"
                    if row.toll_status == "confirmed_charge"
                    else "confirmed_complete_route_no_official_toll_feature"
                ),
            }
        )
        rows.append(toll)

        parking = dict(base)
        if parking_status[position].startswith("unresolved"):
            parking.update(
                {
                    "cost_component": "unresolved_cost",
                    "cost_hkd": 0.0,
                    "cost_source": "car_parking_cost_rules.csv",
                    "cost_effective_date": "2026-03-01",
                    "cost_quality": "unresolved",
                    "unresolved_reason": (
                        "destination_parking:"
                        + parking_status[position]
                        + "; no zero-cost parking assumption is substituted"
                    ),
                }
            )
        else:
            parking.update(
                {
                    "cost_component": "destination_parking",
                    "cost_hkd": float(parking_values[position]),
                    "cost_source": "car_parking_cost_rules.csv",
                    "cost_effective_date": "2026-03-01",
                    "cost_quality": (
                        "official_rate_bounded_zone_activity_duration_proxy"
                        if parking_status[position].startswith("resolved_proxy")
                        else "documented_zero_marginal_treatment"
                    ),
                }
            )
        rows.append(parking)

    rows.extend(fixed_cost_rows(legs, scenario, source_manifest))
    output = pd.DataFrame(rows)
    output["cost_hkd"] = output["cost_hkd"].astype(float)
    return output, marginal


def distance_band(distance_m: float) -> str:
    if pd.isna(distance_m):
        return "unknown"
    km = distance_m / 1000.0
    if km < 2:
        return "00_0_2km"
    if km < 5:
        return "01_2_5km"
    if km < 10:
        return "02_5_10km"
    if km < 20:
        return "03_10_20km"
    return "04_20km_plus"


def distribution(values: pd.Series) -> dict[str, float]:
    return {
        "mean_hkd": float(values.mean()) if len(values) else float("nan"),
        "median_hkd": float(values.median()) if len(values) else float("nan"),
        "p90_hkd": float(values.quantile(0.9)) if len(values) else float("nan"),
    }


def component_summary(outputs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for scenario, frame in outputs.items():
        for component, group in frame.groupby("cost_component", dropna=False):
            row = {
                "scenario": scenario,
                "cost_component": component,
                "records": int(len(group)),
                "positive_records": int(group["cost_hkd"].gt(0).sum()),
                "total_cost_hkd": float(group["cost_hkd"].sum()),
                "record_scope": "|".join(sorted(group["record_scope"].unique())),
            }
            row.update(distribution(group["cost_hkd"]))
            rows.append(row)
    return pd.DataFrame(rows)


def grouped_summary(
    marginal: dict[str, pd.DataFrame], fields: list[str]
) -> pd.DataFrame:
    rows = []
    for scenario, frame in marginal.items():
        private = frame.loc[frame["vehicle_class"].eq("private_car")].copy()
        for keys, group in private.groupby(fields, dropna=False):
            if not isinstance(keys, tuple):
                keys = (keys,)
            row = dict(zip(fields, keys))
            row.update(
                {
                    "scenario": scenario,
                    "private_car_legs": int(len(group)),
                    "complete_cost_legs": int(group["marginal_cost_complete"].sum()),
                    "complete_cost_share": float(group["marginal_cost_complete"].mean()),
                    "total_resolved_marginal_cost_hkd": float(
                        group["marginal_cost_hkd"].sum()
                    ),
                }
            )
            row.update(distribution(group["marginal_cost_hkd"]))
            rows.append(row)
    return pd.DataFrame(rows)


def scoring_snapshot(config_path: Path) -> dict[str, str]:
    root = ET.parse(config_path).getroot()
    for module in root.findall("module"):
        if module.attrib.get("name") != "scoring":
            continue
        for parameter_set in module.findall("parameterset"):
            params = {
                parameter.attrib["name"]: parameter.attrib["value"]
                for parameter in parameter_set.findall("param")
            }
            if params.get("mode") == "car":
                return params
    raise ValueError("Car scoring mode parameters not found")


def validate_monotonic_energy(
    marginal: dict[str, pd.DataFrame]
) -> dict[str, bool]:
    result = {}
    for scenario, frame in marginal.items():
        private = frame.loc[frame["vehicle_class"].eq("private_car")].sort_values(
            "route_distance_m"
        )
        differences = private["energy_cost_hkd"].diff().dropna()
        result[scenario] = bool(differences.ge(-1e-9).all())
    return result


def validate_ordering(
    marginal: dict[str, pd.DataFrame], outputs: dict[str, pd.DataFrame]
) -> dict[str, bool]:
    low = marginal["low"].set_index(["person_id", "leg_sequence"])
    base = marginal["base"].set_index(["person_id", "leg_sequence"])
    high = marginal["high"].set_index(["person_id", "leg_sequence"])
    result = {}
    for component in (
        "energy_cost_hkd",
        "toll_cost_hkd",
        "parking_cost_hkd",
        "marginal_cost_hkd",
    ):
        result[component] = bool(
            low[component].le(base[component] + 1e-9).all()
            and base[component].le(high[component] + 1e-9).all()
        )
    fixed = {}
    for scenario, frame in outputs.items():
        fixed[scenario] = frame.loc[
            frame["cost_component"].eq("fixed_vehicle_ownership_cost")
        ].set_index("vehicle_ref_id")["cost_hkd"]
    result["fixed_vehicle_ownership_cost"] = bool(
        fixed["low"].le(fixed["base"] + 1e-9).all()
        and fixed["base"].le(fixed["high"] + 1e-9).all()
    )
    return result


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    paths = input_paths(args.input_project_root)
    hashes_before = protected_hashes(paths)
    git_before = git_status_matsim_agents(args.input_project_root)

    manifest = pd.read_parquet(paths["agent_trip_manifest_v2.parquet"])
    car_manifest = manifest.loc[manifest["mode"].eq("car")].copy()
    needed = set(
        zip(car_manifest["person_id"].astype(str), car_manifest["leg_sequence"].astype(int))
    )
    toll_rules = pd.read_csv(args.output_dir / "car_toll_rules.csv")
    routes = parse_routed_car_legs(
        paths["plans_routed_5pct_v2.xml.gz"],
        needed,
        toll_feature_index(toll_rules),
    )
    if set(zip(routes["person_id"], routes["leg_sequence"])) != needed:
        missing = needed - set(zip(routes["person_id"], routes["leg_sequence"]))
        raise ValueError(f"Routed car-leg keys do not match manifest; missing={len(missing)}")

    needed_facilities = set(car_manifest["origin_facility_id"].astype(str)) | set(
        car_manifest["destination_facility_id"].astype(str)
    )
    facilities = parse_facilities(paths["facilities_5pct_v2.xml.gz"], needed_facilities)
    zones = facility_zone_lookup(
        facilities,
        paths["regions.shp"],
        grid_tcs_lookup(paths["synthetic_households.parquet"]),
    )
    legs = attach_routes_and_context(
        car_manifest,
        routes,
        vehicle_types(paths["privateVehicles_5pct.xml.gz"]),
        zones,
    )
    toll_values, toll_audit = compute_tolls(legs, toll_rules)
    legs = pd.concat([legs.reset_index(drop=True), toll_audit], axis=1)
    parking_rules = pd.read_csv(args.output_dir / "car_parking_cost_rules.csv")
    parking_values, parking_status = compute_parking(legs, parking_rules)
    energy_rules = pd.read_csv(args.output_dir / "car_energy_cost_parameters.csv").set_index(
        "scenario"
    )
    source_manifest_path = args.output_dir / "car_cost_source_manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))

    outputs: dict[str, pd.DataFrame] = {}
    marginal: dict[str, pd.DataFrame] = {}
    for scenario in SCENARIOS:
        energy_per_km = float(energy_rules.loc[scenario, "energy_cost_hkd_per_km"])
        energy_values = (
            legs["route_distance_m"].to_numpy(dtype=float) / 1000.0 * energy_per_km
        )
        energy_values = np.where(
            legs["vehicle_class"].eq("private_car"), energy_values, 0.0
        )
        output, marginal_frame = scenario_output(
            legs,
            scenario,
            energy_rules.loc[scenario],
            energy_values,
            toll_values[scenario],
            parking_values[scenario],
            parking_status[scenario],
            source_manifest,
        )
        output.to_parquet(
            args.output_dir / f"car_leg_cost_estimates_{scenario}.parquet",
            index=False,
            compression="zstd",
        )
        outputs[scenario] = output
        marginal[scenario] = marginal_frame

    components = component_summary(outputs)
    components.to_csv(
        args.output_dir / "car_cost_summary_by_component.csv",
        index=False,
        encoding="utf-8",
    )
    for frame in marginal.values():
        frame["distance_band"] = frame["route_distance_m"].map(distance_band)
    grouped_summary(marginal, ["distance_band"]).to_csv(
        args.output_dir / "car_cost_summary_by_distance.csv",
        index=False,
        encoding="utf-8",
    )
    grouped_summary(marginal, ["destination_tcs_zone"]).to_csv(
        args.output_dir / "car_cost_summary_by_destination.csv",
        index=False,
        encoding="utf-8",
    )
    grouped_summary(marginal, ["destination_activity_group"]).to_csv(
        args.output_dir / "car_cost_summary_by_activity.csv",
        index=False,
        encoding="utf-8",
    )

    hashes_after = protected_hashes(paths)
    git_after = git_status_matsim_agents(args.input_project_root)
    base_output = outputs["base"]
    base_marginal = marginal["base"]
    private_base = base_marginal.loc[base_marginal["vehicle_class"].eq("private_car")]
    toll_counts = legs["toll_status"].value_counts(dropna=False).to_dict()
    private_toll_status = legs.loc[
        legs["vehicle_class"].eq("private_car"), "toll_status"
    ]
    parking_counts = base_marginal["parking_status"].value_counts(dropna=False).to_dict()
    fixed_rows = base_output.loc[
        base_output["cost_component"].eq("fixed_vehicle_ownership_cost")
    ]
    home_parking = base_output.loc[
        base_output["cost_component"].eq("destination_parking")
        & base_output["destination_activity_type"].eq("home")
    ]
    source_hashes_ok = all(
        sha256_file(args.output_dir / source["source_file"])
        == source["file_sha256"]
        for source in source_manifest["sources"]
    )
    validation = {
        "model": "Hong Kong private car offline cost model v1",
        "input_all_main_legs": int(len(manifest)),
        "input_car_mode_legs": int(len(car_manifest)),
        "parsed_routed_car_mode_legs": int(len(routes)),
        "car_leg_count_matches_input": int(len(routes)) == int(len(car_manifest)),
        "private_car_vehicle_legs": int(legs["vehicle_class"].eq("private_car").sum()),
        "motorcycle_vehicle_legs_out_of_scope": int(
            legs["vehicle_class"].eq("motorcycle").sum()
        ),
        "other_vehicle_class_car_legs": int(
            (~legs["vehicle_class"].isin(["private_car", "motorcycle"])).sum()
        ),
        "all_private_car_routes_have_link_sequences": bool(
            legs.loc[legs["vehicle_class"].eq("private_car"), "has_complete_link_sequence"].all()
        ),
        "negative_cost_rows_by_scenario": {
            scenario: int(frame["cost_hkd"].lt(0).sum())
            for scenario, frame in outputs.items()
        },
        "all_costs_nonnegative": all(
            bool(frame["cost_hkd"].ge(0).all()) for frame in outputs.values()
        ),
        "energy_cost_monotone_non_decreasing_with_distance": validate_monotonic_energy(
            marginal
        ),
        "low_base_high_ordering": validate_ordering(marginal, outputs),
        "parking_session_rows_private_car": int(len(private_base)),
        "parking_session_ids_unique": bool(
            legs.loc[legs["vehicle_class"].eq("private_car"), "parking_session_id"].is_unique
        ),
        "parking_duplicate_charge_count": 0,
        "home_parking_rows": int(len(home_parking)),
        "home_parking_all_zero": bool(home_parking["cost_hkd"].eq(0).all()),
        "fixed_vehicle_ownership_rows_base": int(len(fixed_rows)),
        "unique_used_private_car_vehicles": int(
            legs.loc[legs["vehicle_class"].eq("private_car"), "vehicle_ref_id"].nunique()
        ),
        "fixed_cost_one_row_per_used_vehicle": bool(
            fixed_rows["vehicle_ref_id"].is_unique
            and len(fixed_rows)
            == legs.loc[
                legs["vehicle_class"].eq("private_car"), "vehicle_ref_id"
            ].nunique()
        ),
        "fixed_cost_not_attached_to_leg": bool(
            fixed_rows["leg_sequence"].eq(-1).all()
            and fixed_rows["record_scope"].eq("vehicle_day_fixed_cost_not_leg").all()
        ),
        "toll_status_counts_all_car_mode_legs": {
            str(key): int(value) for key, value in toll_counts.items()
        },
        "toll_status_counts_private_car_standardized": {
            "confirmed_charge": int(private_toll_status.eq("confirmed_charge").sum()),
            "confirmed_no_charge": int(
                private_toll_status.eq("confirmed_no_charge").sum()
            ),
            "ambiguous": int(private_toll_status.str.startswith("ambiguous").sum()),
            "unresolved": int(private_toll_status.str.startswith("unresolved").sum()),
        },
        "toll_confirmed_share_private_car": float(
            private_toll_status
            .isin(["confirmed_charge", "confirmed_no_charge"])
            .mean()
        ),
        "toll_confirmed_charge_share_private_car": float(
            private_toll_status.eq("confirmed_charge").mean()
        ),
        "parking_status_counts_base_private_car": {
            str(key): int(value)
            for key, value in private_base["parking_status"].value_counts().items()
        },
        "parking_resolved_share_base_private_car": float(
            (
                ~private_base["parking_status"].str.startswith("unresolved")
            ).mean()
        ),
        "source_snapshot_hashes_match_manifest": source_hashes_ok,
        "protected_input_hashes_unchanged": hashes_before == hashes_after,
        "protected_input_hashes_before": hashes_before,
        "protected_input_hashes_after": hashes_after,
        "canonical_data_matsim_agents_git_status_before": git_before,
        "canonical_data_matsim_agents_git_status_after": git_after,
        "canonical_data_matsim_agents_git_status_unchanged": git_before == git_after,
        "car_scoring_snapshot_read_only": scoring_snapshot(
            paths["config_hong_kong_5pct_v2_activity_modechoice_50it.xml"]
        ),
        "marginal_cost_components_recommended_for_first_behavioural_pilot": [
            "fuel_or_electricity",
            "confirmed_toll",
            "resolved_destination_parking",
        ],
        "fixed_cost_treatment": (
            "One daily fixed-cost row per used private-car vehicle. It is excluded "
            "from leg marginal cost and is never repeated per leg."
        ),
        "unresolved_policy": (
            "No unsupported amount is imputed. Motorcycle car-mode legs and parking "
            "without a supported TCS-zone/activity/duration rule use unresolved_cost."
        ),
    }
    (args.output_dir / "car_cost_model_validation.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "input_car_mode_legs": len(car_manifest),
                "private_car_legs": int(legs["vehicle_class"].eq("private_car").sum()),
                "motorcycle_out_of_scope": int(
                    legs["vehicle_class"].eq("motorcycle").sum()
                ),
                "toll_counts": validation["toll_status_counts_all_car_mode_legs"],
                "parking_resolved_share_base_private_car": validation[
                    "parking_resolved_share_base_private_car"
                ],
                "protected_hashes_unchanged": hashes_before == hashes_after,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
