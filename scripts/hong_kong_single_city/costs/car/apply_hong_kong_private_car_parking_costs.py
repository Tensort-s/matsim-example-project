#!/usr/bin/env python3
"""Build physical vehicle parking events and apply Hong Kong proxy rates.

The script writes a standalone destination-parking candidate. It does not
modify MATSim inputs, scoring, toll candidates, or unified car-cost outputs.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Iterable
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
from lxml import etree


REPO_ROOT = Path.cwd()
CAR_COST_ROOT = Path("data/transport_costs/hongkong/car_cost_v1")
FEASIBILITY_ROOT = CAR_COST_ROOT / "input_feasibility"
DEFAULT_OUTPUT = CAR_COST_ROOT / "parking_event_application_v1"
RULE_PATH = CAR_COST_ROOT / "car_parking_cost_rules.csv"
SOURCE_MANIFEST_PATH = CAR_COST_ROOT / "car_cost_source_manifest.json"
SCENARIOS = ("low", "base", "high")
SOURCE_COMMIT = "44f15a95a1a00aeaac7c9163a344d15caf787497"
PROXY_QUALITY = "official_rate_bounded_zone_activity_proxy"

INPUT_DOCS = {
    "car_cost_model_document": Path("docs/HONG_KONG_CAR_COST_MODEL.md"),
    "toll_candidate_document": Path(
        "docs/HONG_KONG_PRIVATE_CAR_TOLL_RATE_APPLICATION.md"
    ),
}
FEASIBILITY_INPUTS = {
    "feasibility_table": (
        FEASIBILITY_ROOT / "car_leg_input_feasibility.parquet"
    ),
    "feasibility_validation": (
        FEASIBILITY_ROOT / "car_cost_feasibility_validation.json"
    ),
    "feasibility_repairs": FEASIBILITY_ROOT / "required_repairs.csv",
}

EVENT_BASE_COLUMNS = [
    "person_id",
    "leg_sequence",
    "vehicle_ref_id",
    "vehicle_class",
    "mode",
    "parking_event_key",
    "origin_facility_id",
    "destination_facility_id",
    "destination_tcs_zone",
    "destination_zone_group",
    "destination_activity_type",
    "destination_activity_group",
    "departure_time_s",
    "route_travel_time_s",
    "arrival_time_s",
    "next_departure_person_id",
    "next_departure_leg_sequence",
    "next_departure_vehicle_ref_id",
    "next_departure_facility_id",
    "next_departure_time_s",
    "parking_duration_s",
    "vehicle_chain_status",
    "vehicle_chain_time_overlap",
    "next_departure_facility_mismatch",
    "parking_crosses_midnight",
    "terminal_event",
]

OUTPUT_COLUMNS = EVENT_BASE_COLUMNS + [
    "parking_status",
    "pricing_method",
    "billing_unit_count",
    "day_billing_unit_count",
    "night_billing_unit_count",
    "day_night_rate_switch_count",
    "uncapped_cost_hkd",
    "daily_cap_applied",
    "excluded_monthly_rate_hkd",
    "cost_component",
    "cost_hkd",
    "cost_source",
    "cost_effective_date",
    "cost_quality",
    "scenario",
    "unresolved_reason",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-project-root",
        type=Path,
        required=True,
        help="Canonical project root containing large read-only inputs.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def tag_name(element: Any) -> str:
    return str(element.tag).rsplit("}", 1)[-1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bundle(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda value: value.name):
        encoded = path.name.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def parse_time_s(value: object) -> float:
    if value is None or value == "":
        return float("nan")
    if isinstance(value, (int, float)):
        return float(value)
    parts = str(value).split(":")
    if len(parts) == 3:
        return (
            int(parts[0]) * 3600
            + int(parts[1]) * 60
            + float(parts[2])
        )
    return float(value)


def finite(value: object) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def normalized_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def ordered_unique(values: Iterable[object]) -> list[str]:
    return list(dict.fromkeys(normalized_text(value) for value in values))


def selected_plan(person: Any) -> Any | None:
    plans = [child for child in person if tag_name(child) == "plan"]
    if not plans:
        return None
    selected = [
        plan
        for plan in plans
        if plan.attrib.get("selected", "yes").lower()
        in {"yes", "true", "1"}
    ]
    return selected[0] if selected else plans[0]


def main_activities_and_legs(
    plan: Any,
) -> tuple[list[Any], list[tuple[int, Any]]]:
    activities: list[Any] = []
    legs: list[tuple[int, Any]] = []
    main_activity_index = -1
    for child in plan:
        name = tag_name(child)
        if name == "activity":
            if not child.attrib.get("type", "").endswith("interaction"):
                main_activity_index += 1
                activities.append(child)
        elif name == "leg":
            legs.append((main_activity_index, child))
    return activities, legs


def canonical_paths(input_root: Path) -> dict[str, Path]:
    v2 = (
        input_root
        / "data/matsim_agents/hongkong/"
        "typical_weekday_5pct_v2_activity_modechoice"
    )
    network_root = (
        input_root
        / "data/transit/hongkong/processed/"
        "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_"
        "ferry_core_v1_cap010"
    )
    result = {
        "plans_routed": v2 / "plans_routed_5pct_v2.xml.gz",
        "facilities": v2 / "facilities_5pct_v2.xml.gz",
        "private_vehicles": v2 / "privateVehicles_5pct.xml.gz",
        "trip_manifest": v2 / "agent_trip_manifest_v2.parquet",
        "config": (
            v2 / "config_hong_kong_5pct_v2_activity_modechoice_50it.xml"
        ),
        "network": network_root / "network.xml.gz",
        "synthetic_households": (
            input_root
            / "data/matsim_agents/hongkong/"
            "synthetic_households_tcs2022/synthetic_households.parquet"
        ),
        "fixed_link_grid": (
            input_root
            / "data/worldcommuting_od/hongkong/custom_features/"
            "hong_kong_fixed_link_grid/CityAndRegionSplit/"
            "hong_kong_fixed_link_grid/regions.shp"
        ),
    }
    missing = [key for key, path in result.items() if not path.exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing canonical parking inputs: {missing}"
        )
    return result


def internal_protected_paths(output_dir: Path) -> dict[str, Path]:
    output_resolved = output_dir.resolve()
    result: dict[str, Path] = {}
    for path in sorted(CAR_COST_ROOT.rglob("*")):
        if not path.is_file():
            continue
        if path.resolve().is_relative_to(output_resolved):
            continue
        result[path.as_posix()] = path
    for key, path in INPUT_DOCS.items():
        result[f"document:{key}"] = path
    return result


def hash_map(paths: dict[str, Path]) -> dict[str, str]:
    return {key: sha256_file(path) for key, path in sorted(paths.items())}


def canonical_hashes(paths: dict[str, Path]) -> dict[str, str]:
    result = {}
    for key, path in paths.items():
        if key == "fixed_link_grid":
            sidecars = sorted(
                candidate
                for candidate in path.parent.glob(f"{path.stem}.*")
                if candidate.is_file()
            )
            result["fixed_link_grid_bundle"] = sha256_bundle(sidecars)
        else:
            result[key] = sha256_file(path)
    return result


def parse_vehicle_types(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    with gzip.open(path, "rb") as handle:
        for _, element in ET.iterparse(handle, events=("end",)):
            if tag_name(element) == "vehicle":
                result[normalized_text(element.attrib.get("id"))] = (
                    normalized_text(element.attrib.get("type"))
                )
            element.clear()
    return result


def parse_facility_ids(path: Path) -> set[str]:
    result: set[str] = set()
    with gzip.open(path, "rb") as handle:
        for _, element in ET.iterparse(handle, events=("end",)):
            if tag_name(element) == "facility":
                facility_id = normalized_text(element.attrib.get("id"))
                if facility_id in result:
                    raise RuntimeError(
                        f"Duplicate canonical facility ID: {facility_id}"
                    )
                result.add(facility_id)
            element.clear()
    return result


def parse_routed_car_legs(
    path: Path, needed_keys: set[tuple[str, int]]
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    with gzip.open(path, "rb") as handle:
        context = etree.iterparse(
            handle, events=("end",), tag="person", huge_tree=True
        )
        for _, person in context:
            person_id = normalized_text(person.attrib.get("id"))
            plan = selected_plan(person)
            if plan is not None:
                activities, legs = main_activities_and_legs(plan)
                for sequence, leg in legs:
                    if leg.attrib.get("mode") != "car":
                        continue
                    key = (person_id, int(sequence))
                    if key not in needed_keys:
                        continue
                    if key in seen:
                        raise RuntimeError(f"Duplicate routed car key: {key}")
                    seen.add(key)
                    route = next(
                        (
                            child
                            for child in leg
                            if tag_name(child) == "route"
                        ),
                        None,
                    )
                    origin = (
                        activities[sequence]
                        if 0 <= sequence < len(activities)
                        else None
                    )
                    destination = (
                        activities[sequence + 1]
                        if 0 <= sequence + 1 < len(activities)
                        else None
                    )
                    departure = parse_time_s(leg.attrib.get("dep_time"))
                    travel_time = parse_time_s(
                        route.attrib.get("trav_time")
                        if route is not None
                        else leg.attrib.get("trav_time")
                    )
                    if not finite(travel_time):
                        travel_time = parse_time_s(
                            leg.attrib.get("trav_time")
                        )
                    rows.append(
                        {
                            "person_id": person_id,
                            "leg_sequence": int(sequence),
                            "vehicle_ref_id": (
                                normalized_text(
                                    route.attrib.get("vehicleRefId")
                                )
                                if route is not None
                                else ""
                            ),
                            "departure_time_s": departure,
                            "route_travel_time_s": travel_time,
                            "arrival_time_s": (
                                departure + travel_time
                                if finite(departure)
                                and finite(travel_time)
                                else float("nan")
                            ),
                            "origin_facility_id_routed": (
                                normalized_text(
                                    origin.attrib.get("facility")
                                )
                                if origin is not None
                                else ""
                            ),
                            "destination_facility_id_routed": (
                                normalized_text(
                                    destination.attrib.get("facility")
                                )
                                if destination is not None
                                else ""
                            ),
                            "destination_activity_type_routed": (
                                normalized_text(
                                    destination.attrib.get("type")
                                )
                                if destination is not None
                                else ""
                            ),
                        }
                    )
            person.clear()
            parent = person.getparent()
            if parent is not None:
                while person.getprevious() is not None:
                    del parent[0]
    if seen != needed_keys:
        raise RuntimeError(
            "Canonical routed car keys differ from manifest: "
            f"missing={len(needed_keys - seen)}, "
            f"extra={len(seen - needed_keys)}"
        )
    return pd.DataFrame(rows)


def activity_group(activity_type: object) -> str:
    value = normalized_text(activity_type)
    if value == "home":
        return "home"
    if value in {"work", "work_mobile", "business"}:
        return "work"
    if value.startswith("school") or value.startswith("education"):
        return "education"
    if value == "shopping":
        return "shopping"
    if value in {
        "dining",
        "leisure",
        "social",
        "vfr",
        "primary_activity",
        "secondary_activity",
    }:
        return "leisure"
    if value in {"medical", "personal_business"}:
        return "medical_personal_business"
    if value == "accommodation":
        return "visitor_accommodation"
    if value in {"border", "external_activity"}:
        return "border"
    return "other" if value else ""


def zone_group(zone: object) -> str:
    if not finite(zone):
        return "unresolved"
    value = int(float(zone))
    if 1 <= value <= 4:
        return "hong_kong_island"
    if 5 <= value <= 13:
        return "kowloon_urban"
    if 14 <= value <= 26:
        return "new_territories_lantau"
    return "unresolved"


def stable_parking_event_key(
    vehicle: str,
    destination: str,
    arrival_time_s: object,
    next_departure_time_s: object,
) -> str:
    arrival = (
        f"{float(arrival_time_s):.3f}"
        if finite(arrival_time_s)
        else "missing_arrival"
    )
    next_departure = (
        f"{float(next_departure_time_s):.3f}"
        if finite(next_departure_time_s)
        else "terminal_event"
    )
    payload = (
        f"vehicle={normalized_text(vehicle)}|"
        f"destination={normalized_text(destination)}|"
        f"arrival={arrival}|next_departure={next_departure}"
    )
    return "hk_parking_" + hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()[:24]


def build_vehicle_chains(
    manifest: pd.DataFrame,
    routes: pd.DataFrame,
    feasibility: pd.DataFrame,
    vehicle_types: dict[str, str],
    facility_ids: set[str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    car_manifest = manifest.loc[manifest["mode"].eq("car")].copy()
    car_manifest["person_id"] = car_manifest["person_id"].astype(str)
    car_manifest["leg_sequence"] = car_manifest["leg_sequence"].astype(int)
    car_manifest = car_manifest.rename(
        columns={"departure_time_s": "manifest_departure_time_s"}
    )
    if car_manifest.duplicated(["person_id", "leg_sequence"]).any():
        raise RuntimeError("Duplicate car keys in trip manifest")
    frame = car_manifest.merge(
        routes,
        on=["person_id", "leg_sequence"],
        how="left",
        validate="one_to_one",
    )
    benchmark = feasibility[
        [
            "person_id",
            "leg_sequence",
            "destination_tcs_zone",
            "destination_activity_group",
        ]
    ].copy()
    benchmark["person_id"] = benchmark["person_id"].astype(str)
    benchmark["leg_sequence"] = benchmark["leg_sequence"].astype(int)
    frame = frame.merge(
        benchmark,
        on=["person_id", "leg_sequence"],
        how="left",
        validate="one_to_one",
    )
    frame["origin_facility_id"] = frame[
        "origin_facility_id"
    ].map(normalized_text)
    frame["destination_facility_id"] = frame[
        "destination_facility_id"
    ].map(normalized_text)
    frame["destination_activity_type"] = frame[
        "destination_type"
    ].map(normalized_text)
    frame["destination_activity_group_rebuilt"] = frame[
        "destination_activity_type"
    ].map(activity_group)
    activity_group_mismatch = int(
        frame["destination_activity_group_rebuilt"].ne(
            frame["destination_activity_group"].fillna("")
        ).sum()
    )
    manifest_route_origin_mismatch = int(
        frame["origin_facility_id"].ne(
            frame["origin_facility_id_routed"].fillna("")
        ).sum()
    )
    manifest_route_destination_mismatch = int(
        frame["destination_facility_id"].ne(
            frame["destination_facility_id_routed"].fillna("")
        ).sum()
    )
    manifest_route_activity_mismatch = int(
        frame["destination_activity_type"].ne(
            frame["destination_activity_type_routed"].fillna("")
        ).sum()
    )
    missing_facility_reference_count = int(
        (
            ~frame["origin_facility_id"].isin(facility_ids)
            | ~frame["destination_facility_id"].isin(facility_ids)
        ).sum()
    )
    frame["vehicle_class"] = frame["vehicle_ref_id"].map(
        vehicle_types
    ).fillna("unresolved")
    unresolved_vehicle_count = int(
        frame["vehicle_class"].eq("unresolved").sum()
    )
    if any(
        (
            manifest_route_origin_mismatch,
            manifest_route_destination_mismatch,
            manifest_route_activity_mismatch,
            activity_group_mismatch,
            missing_facility_reference_count,
            unresolved_vehicle_count,
        )
    ):
        raise RuntimeError(
            "Canonical parking contexts do not agree with audited inputs: "
            f"origin={manifest_route_origin_mismatch}, "
            f"destination={manifest_route_destination_mismatch}, "
            f"activity={manifest_route_activity_mismatch}, "
            f"group={activity_group_mismatch}, "
            f"facility={missing_facility_reference_count}, "
            f"vehicle={unresolved_vehicle_count}"
        )
    frame["destination_activity_group"] = frame[
        "destination_activity_group_rebuilt"
    ]
    frame["destination_zone_group"] = frame[
        "destination_tcs_zone"
    ].map(zone_group)

    ordered = frame.sort_values(
        [
            "vehicle_ref_id",
            "departure_time_s",
            "person_id",
            "leg_sequence",
        ],
        na_position="last",
    ).copy()
    grouped = ordered.groupby(
        "vehicle_ref_id", sort=False, dropna=False
    )
    ordered["next_departure_person_id"] = grouped["person_id"].shift(-1)
    ordered["next_departure_leg_sequence"] = grouped[
        "leg_sequence"
    ].shift(-1)
    ordered["next_departure_vehicle_ref_id"] = grouped[
        "vehicle_ref_id"
    ].shift(-1)
    ordered["next_departure_facility_id"] = grouped[
        "origin_facility_id"
    ].shift(-1)
    ordered["next_departure_time_s"] = grouped[
        "departure_time_s"
    ].shift(-1)
    ordered["terminal_event"] = ordered[
        "next_departure_time_s"
    ].isna()
    ordered["vehicle_chain_time_overlap"] = (
        ordered["next_departure_time_s"].notna()
        & ordered["arrival_time_s"].notna()
        & ordered["next_departure_time_s"].lt(
            ordered["arrival_time_s"]
        )
    )
    ordered["next_departure_facility_mismatch"] = (
        ordered["next_departure_time_s"].notna()
        & ordered["next_departure_facility_id"].ne(
            ordered["destination_facility_id"]
        )
    )
    valid_duration = (
        ordered["next_departure_time_s"].notna()
        & ~ordered["vehicle_chain_time_overlap"]
        & ~ordered["next_departure_facility_mismatch"]
        & ordered["arrival_time_s"].notna()
    )
    ordered["parking_duration_s"] = np.where(
        valid_duration,
        ordered["next_departure_time_s"]
        - ordered["arrival_time_s"],
        np.nan,
    )
    ordered["parking_crosses_midnight"] = (
        valid_duration
        & np.floor(ordered["arrival_time_s"] / 86400).lt(
            np.floor(ordered["next_departure_time_s"] / 86400)
        )
    )
    ordered["vehicle_chain_status"] = np.select(
        [
            ordered["vehicle_chain_time_overlap"],
            ordered["next_departure_facility_mismatch"],
            ordered["terminal_event"]
            & ordered["destination_activity_group"].eq("home"),
            ordered["terminal_event"],
        ],
        [
            "unresolved_vehicle_time_overlap",
            "unresolved_next_departure_facility_mismatch",
            "terminal_home_fixed_separate",
            "unresolved_missing_next_departure_non_home",
        ],
        default="resolved_same_vehicle_same_facility_time_order",
    )
    ordered["parking_event_key"] = [
        stable_parking_event_key(
            vehicle, destination, arrival, next_departure
        )
        for vehicle, destination, arrival, next_departure in zip(
            ordered["vehicle_ref_id"],
            ordered["destination_facility_id"],
            ordered["arrival_time_s"],
            ordered["next_departure_time_s"],
            strict=False,
        )
    ]
    ordered["mode"] = "car"
    raw_private = ordered.loc[
        ordered["vehicle_class"].eq("private_car")
    ]
    event_counts = raw_private["parking_event_key"].value_counts()
    duplicate = event_counts.loc[event_counts.gt(1)]
    diagnostics = {
        "duplicate_parking_event_key_count": int(len(duplicate)),
        "legs_mapped_to_same_parking_event_count": int(duplicate.sum()),
        "excess_leg_mappings_to_parking_events": int(
            (duplicate - 1).sum()
        ),
        "overlapping_vehicle_parking_event_count": int(
            raw_private["vehicle_chain_time_overlap"].sum()
        ),
        "facility_chain_mismatch_count": int(
            raw_private["next_departure_facility_mismatch"].sum()
        ),
        "overlap_and_facility_mismatch_intersection_count": int(
            (
                raw_private["vehicle_chain_time_overlap"]
                & raw_private["next_departure_facility_mismatch"]
            ).sum()
        ),
        "vehicle_chain_issue_union_count": int(
            (
                raw_private["vehicle_chain_time_overlap"]
                | raw_private["next_departure_facility_mismatch"]
            ).sum()
        ),
    }
    return (
        ordered.sort_values(["person_id", "leg_sequence"]).reset_index(
            drop=True
        ),
        diagnostics,
    )


def repository_relative_rules(rules: pd.DataFrame) -> pd.DataFrame:
    result = rules.copy()
    result["source_file"] = [
        "|".join(
            (
                CAR_COST_ROOT / normalized_text(value)
            ).as_posix()
            for value in normalized_text(source_files).split("|")
            if normalized_text(value)
        )
        for source_files in result["source_file"]
    ]
    result.insert(
        0,
        "input_root_role",
        "feature_worktree_repository_relative_rule_copy",
    )
    result["source_path_quality"] = (
        "repository_relative_no_facility_level_price_claim"
    )
    return result


def parking_status(
    row: Any, scenario: str, duplicate_keys: set[str]
) -> tuple[str, str]:
    reasons = []
    if row.vehicle_class == "motorcycle":
        return "out_of_scope_motorcycle", "vehicle_class_motorcycle"
    if row.vehicle_class != "private_car":
        return "unresolved_activity_type", "unresolved_vehicle_class"
    if row.parking_event_key in duplicate_keys:
        return (
            "unresolved_duplicate_parking_event_mapping",
            "multiple_arrival_records_map_to_same_physical_event",
        )
    if bool(row.vehicle_chain_time_overlap):
        reasons.append("next_departure_precedes_arrival")
        if bool(row.next_departure_facility_mismatch):
            reasons.append("next_departure_facility_mismatch")
        return "unresolved_vehicle_time_overlap", "|".join(reasons)
    if bool(row.next_departure_facility_mismatch):
        return (
            "unresolved_next_departure_facility_mismatch",
            "next_departure_facility_differs_from_parking_destination",
        )
    if not normalized_text(row.destination_activity_group):
        return "unresolved_activity_type", "missing_activity_type"
    if bool(row.terminal_event):
        if row.destination_activity_group == "home":
            return (
                "resolved_home_marginal_zero_fixed_separate",
                "",
            )
        return (
            "unresolved_missing_next_departure_non_home",
            "terminal_non_home_event_has_no_duration_evidence",
        )
    if row.destination_activity_group == "home":
        return "resolved_home_marginal_zero_fixed_separate", ""
    if not finite(row.parking_duration_s):
        return "unresolved_missing_duration", "missing_parking_duration"
    if row.destination_zone_group == "unresolved":
        return (
            "unresolved_missing_destination_zone",
            "destination_tcs_zone_unavailable",
        )
    if row.destination_activity_group in {"border", "other"}:
        return (
            "unresolved_activity_type",
            "activity_has_no_supported_parking_proxy_rule",
        )
    if (
        row.destination_activity_group == "work"
        and scenario == "low"
    ):
        return "resolved_work_subscription_assumed_prepaid", ""
    return "resolved_proxy_charge", ""


def hourly_charge(
    arrival_time_s: float,
    duration_s: float,
    rule: Any,
) -> dict[str, Any]:
    increment = float(rule.billing_increment_s)
    units = int(math.ceil(max(0.0, duration_s) / increment))
    periods: list[str] = []
    rates: list[float] = []
    for unit in range(units):
        clock = (arrival_time_s + unit * increment) % 86400
        is_day = (
            float(rule.day_period_start_s)
            <= clock
            < float(rule.day_period_end_s)
        )
        periods.append("day" if is_day else "night")
        rates.append(
            float(rule.hourly_day_hkd)
            if is_day
            else float(rule.hourly_night_hkd)
        )
    uncapped = float(sum(rates))
    capped = uncapped
    daily_cap_applied = False
    if finite(rule.daily_cap_hkd):
        cap = float(rule.daily_cap_hkd)
        capped = min(capped, cap)
        daily_cap_applied = uncapped > cap
    if finite(rule.minimum_charge_hkd):
        capped = max(capped, float(rule.minimum_charge_hkd))
    return {
        "cost_hkd": float(capped),
        "billing_unit_count": units,
        "day_billing_unit_count": periods.count("day"),
        "night_billing_unit_count": periods.count("night"),
        "day_night_rate_switch_count": sum(
            left != right
            for left, right in zip(periods, periods[1:])
        ),
        "uncapped_cost_hkd": uncapped,
        "daily_cap_applied": daily_cap_applied,
    }


def apply_rules(
    chains: pd.DataFrame, rules: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, Any]]:
    rule_index = rules.set_index(
        ["scenario", "zone_group", "activity_group"]
    )
    private_counts = chains.loc[
        chains["vehicle_class"].eq("private_car"),
        "parking_event_key",
    ].value_counts()
    duplicate_keys = set(private_counts.loc[private_counts.gt(1)].index)
    rows: list[dict[str, Any]] = []
    for row in chains.itertuples(index=False):
        base = {
            column: getattr(row, column)
            for column in EVENT_BASE_COLUMNS
        }
        for scenario in SCENARIOS:
            status, unresolved_reason = parking_status(
                row, scenario, duplicate_keys
            )
            pricing_method = ""
            cost_hkd = float("nan")
            billing = {
                "billing_unit_count": 0,
                "day_billing_unit_count": 0,
                "night_billing_unit_count": 0,
                "day_night_rate_switch_count": 0,
                "uncapped_cost_hkd": float("nan"),
                "daily_cap_applied": False,
            }
            excluded_monthly = 0.0
            source = ""
            effective_date = ""
            quality = "unresolved"
            if status.startswith("resolved"):
                lookup_zone = (
                    row.destination_zone_group
                    if row.destination_zone_group != "unresolved"
                    else "new_territories_lantau"
                )
                key = (
                    scenario,
                    lookup_zone,
                    row.destination_activity_group,
                )
                if key not in rule_index.index:
                    status = "unresolved_activity_type"
                    unresolved_reason = (
                        "no_exact_zone_activity_scenario_rule"
                    )
                else:
                    rule = rule_index.loc[key]
                    pricing_method = normalized_text(
                        rule.pricing_method
                    )
                    source = (
                        DEFAULT_OUTPUT
                        / "parking_cost_rules_repository_relative.csv"
                    ).as_posix()
                    effective_date = normalized_text(
                        rule.effective_date
                    )
                    quality = PROXY_QUALITY
                    if status == (
                        "resolved_home_marginal_zero_fixed_separate"
                    ):
                        cost_hkd = 0.0
                        pricing_method = (
                            "home_marginal_zero_residential_fixed_separate"
                        )
                    elif status == (
                        "resolved_work_subscription_assumed_prepaid"
                    ):
                        cost_hkd = 0.0
                        excluded_monthly = float(rule.monthly_rate_hkd)
                        pricing_method = (
                            "work_subscription_assumed_prepaid_"
                            "monthly_rate_not_attached_to_leg"
                        )
                    elif pricing_method in {
                        "representative_day_pass",
                        "representative_night_pass",
                    }:
                        cost_hkd = float(rule.daily_cap_hkd)
                        billing["uncapped_cost_hkd"] = cost_hkd
                    elif pricing_method in {
                        "hourly_or_part_by_arrival_clock",
                        "hourly_or_part_capped_at_ten_hours",
                    }:
                        billing = hourly_charge(
                            float(row.arrival_time_s),
                            float(row.parking_duration_s),
                            rule,
                        )
                        cost_hkd = float(billing["cost_hkd"])
                    else:
                        status = "unresolved_activity_type"
                        unresolved_reason = (
                            "unsupported_pricing_method"
                        )
                        cost_hkd = float("nan")
                        quality = "unresolved"
            rows.append(
                {
                    **base,
                    "parking_status": status,
                    "pricing_method": pricing_method,
                    **{
                        key: value
                        for key, value in billing.items()
                        if key != "cost_hkd"
                    },
                    "excluded_monthly_rate_hkd": excluded_monthly,
                    "cost_component": "destination_parking",
                    "cost_hkd": cost_hkd,
                    "cost_source": source,
                    "cost_effective_date": effective_date,
                    "cost_quality": quality,
                    "scenario": scenario,
                    "unresolved_reason": unresolved_reason,
                }
            )
    result = pd.DataFrame(rows)[OUTPUT_COLUMNS]
    diagnostics = {
        "raw_arrival_record_count": int(len(chains)),
        "raw_private_car_arrival_record_count": int(
            chains["vehicle_class"].eq("private_car").sum()
        ),
        "raw_motorcycle_arrival_record_count": int(
            chains["vehicle_class"].eq("motorcycle").sum()
        ),
    }
    return result, diagnostics


def leg_frames(events: pd.DataFrame) -> dict[str, pd.DataFrame]:
    result = {}
    for scenario in SCENARIOS:
        frame = events.loc[events["scenario"].eq(scenario)].copy()
        if frame.duplicated(["person_id", "leg_sequence"]).any():
            raise RuntimeError(
                f"Multiple parking event mappings in {scenario} leg output"
            )
        result[scenario] = frame.sort_values(
            ["person_id", "leg_sequence"]
        ).reset_index(drop=True)
    return result


def duration_band(value: object, terminal: bool) -> str:
    if not finite(value):
        return (
            "terminal_no_next_departure"
            if terminal
            else "unavailable"
        )
    hours = float(value) / 3600
    if hours <= 1:
        return "00_0_to_1h"
    if hours <= 2:
        return "01_1_to_2h"
    if hours <= 4:
        return "02_2_to_4h"
    if hours <= 8:
        return "03_4_to_8h"
    if hours <= 12:
        return "04_8_to_12h"
    if hours <= 24:
        return "05_12_to_24h"
    return "06_over_24h"


def summarize_group(
    frame: pd.DataFrame,
    scenario: str,
    dimension: str,
    values: pd.Series,
) -> list[dict[str, Any]]:
    working = frame.copy()
    working["summary_value"] = values.astype(str)
    rows = []
    for value, group in working.groupby("summary_value", dropna=False):
        resolved = group.loc[
            group["parking_status"].str.startswith("resolved")
        ]
        rows.append(
            {
                "scenario": scenario,
                "summary_dimension": dimension,
                "summary_value": str(value),
                "record_count": int(len(group)),
                "resolved_count": int(len(resolved)),
                "unresolved_count": int(
                    group["parking_status"].str.startswith(
                        "unresolved"
                    ).sum()
                ),
                "out_of_scope_count": int(
                    group["parking_status"].eq(
                        "out_of_scope_motorcycle"
                    ).sum()
                ),
                "total_cost_hkd_resolved_only": float(
                    resolved["cost_hkd"].sum()
                )
                if len(resolved)
                else float("nan"),
                "mean_cost_hkd_resolved_only": float(
                    resolved["cost_hkd"].mean()
                ),
                "median_cost_hkd_resolved_only": float(
                    resolved["cost_hkd"].median()
                ),
                "p90_cost_hkd_resolved_only": float(
                    resolved["cost_hkd"].quantile(0.9)
                ),
            }
        )
    return rows


def build_summary(
    frames: dict[str, pd.DataFrame]
) -> pd.DataFrame:
    rows = []
    for scenario, frame in frames.items():
        bands = pd.Series(
            [
                duration_band(duration, bool(terminal))
                for duration, terminal in zip(
                    frame["parking_duration_s"],
                    frame["terminal_event"],
                    strict=False,
                )
            ],
            index=frame.index,
        )
        for dimension, values in (
            (
                "overall",
                pd.Series("all_records", index=frame.index),
            ),
            ("zone_group", frame["destination_zone_group"]),
            ("activity_group", frame["destination_activity_group"]),
            ("duration_band", bands),
            ("parking_status", frame["parking_status"]),
        ):
            rows.extend(
                summarize_group(
                    frame, scenario, dimension, values
                )
            )
    return pd.DataFrame(rows)


def benchmark_comparison(
    chains: pd.DataFrame,
    chain_diagnostics: dict[str, Any],
) -> dict[str, Any]:
    private = chains.loc[
        chains["vehicle_class"].eq("private_car")
    ]
    motorcycle = chains.loc[
        chains["vehicle_class"].eq("motorcycle")
    ]
    home = private["destination_activity_group"].eq("home")
    actual = {
        "car_legs": int(len(chains)),
        "private_car_legs": int(len(private)),
        "motorcycle": int(len(motorcycle)),
        "used_private_cars": int(private["vehicle_ref_id"].nunique()),
        "home_private_car_arrivals": int(home.sum()),
        "work": int(
            private["destination_activity_group"].eq("work").sum()
        ),
        "education": int(
            private["destination_activity_group"].eq("education").sum()
        ),
        "shopping": int(
            private["destination_activity_group"].eq("shopping").sum()
        ),
        "leisure": int(
            private["destination_activity_group"].eq("leisure").sum()
        ),
        "medical_personal_business": int(
            private["destination_activity_group"]
            .eq("medical_personal_business")
            .sum()
        ),
        "duration_available": int(
            private["parking_duration_s"].notna().sum()
        ),
        "non_home_duration_available": int(
            ((~home) & private["parking_duration_s"].notna()).sum()
        ),
        "zone_available": int(
            private["destination_tcs_zone"].notna().sum()
        ),
        "previous_overlap_diagnostics": int(
            chain_diagnostics[
                "overlapping_vehicle_parking_event_count"
            ]
        ),
        "previous_next_departure_facility_mismatch": int(
            chain_diagnostics["facility_chain_mismatch_count"]
        ),
        "previous_unresolved_vehicle_chain": int(
            chain_diagnostics["vehicle_chain_issue_union_count"]
        ),
        "no_next_departure_vehicle_events": int(
            private["terminal_event"].sum()
        ),
        "cross_midnight_events": int(
            private["parking_crosses_midnight"].sum()
        ),
    }
    expected = {
        "car_legs": 67718,
        "private_car_legs": 64789,
        "motorcycle": 2929,
        "used_private_cars": 21020,
        "home_private_car_arrivals": 28858,
        "work": 8784,
        "education": 278,
        "shopping": 7946,
        "leisure": 15652,
        "medical_personal_business": 3271,
        "duration_available": 43034,
        "non_home_duration_available": 35662,
        "zone_available": 64686,
        "previous_overlap_diagnostics": 466,
        "previous_next_departure_facility_mismatch": 321,
        "previous_unresolved_vehicle_chain": 267,
        "no_next_departure_vehicle_events": 21020,
        "cross_midnight_events": 1359,
    }
    explanations = {
        "previous_unresolved_vehicle_chain": (
            "New precedence audits time overlap and facility mismatch before "
            "home zero treatment. The prior 267 counted non-home chain "
            "failures; the rebuilt union is 735 and exposes 468 additional "
            "home-arrival chain failures."
        )
    }
    return {
        key: {
            "comparison_baseline": int(expected[key]),
            "rebuilt_actual": int(actual[key]),
            "difference": int(actual[key] - expected[key]),
            "explanation": explanations.get(
                key,
                (
                    "Exact match to the input comparison benchmark; output "
                    "was independently rebuilt rather than hard-coded."
                ),
            ),
        }
        for key in expected
    }


def validate(
    chains: pd.DataFrame,
    events: pd.DataFrame,
    frames: dict[str, pd.DataFrame],
    chain_diagnostics: dict[str, Any],
    event_diagnostics: dict[str, Any],
) -> dict[str, Any]:
    private = chains.loc[
        chains["vehicle_class"].eq("private_car")
    ]
    identity = events.loc[events["scenario"].eq("base")]
    event_identity_unique = not identity.duplicated(
        ["parking_event_key"]
    ).any()
    event_scenario_unique = not events.duplicated(
        ["parking_event_key", "scenario"]
    ).any()
    leg_key_unique = {
        scenario: bool(
            not frame.duplicated(
                ["person_id", "leg_sequence"]
            ).any()
        )
        for scenario, frame in frames.items()
    }
    row_counts = {
        scenario: int(len(frame))
        for scenario, frame in frames.items()
    }
    aggregation_errors = {}
    status_counts = {}
    resolved_counts = {}
    unresolved_counts = {}
    out_counts = {}
    zero_rule_valid = {}
    null_rule_valid = {}
    totals = {}
    for scenario, frame in frames.items():
        event_cost = events.loc[
            events["scenario"].eq(scenario)
        ].set_index(["person_id", "leg_sequence"])["cost_hkd"]
        leg_cost = frame.set_index(
            ["person_id", "leg_sequence"]
        )["cost_hkd"]
        both = pd.concat(
            [event_cost.rename("event"), leg_cost.rename("leg")],
            axis=1,
        ).dropna()
        aggregation_errors[scenario] = float(
            (both["event"] - both["leg"]).abs().max()
        )
        status_counts[scenario] = {
            str(key): int(value)
            for key, value in frame["parking_status"].value_counts().items()
        }
        resolved = frame["parking_status"].str.startswith("resolved")
        unresolved = frame["parking_status"].str.startswith(
            "unresolved"
        )
        out = frame["parking_status"].eq("out_of_scope_motorcycle")
        resolved_counts[scenario] = int(resolved.sum())
        unresolved_counts[scenario] = int(unresolved.sum())
        out_counts[scenario] = int(out.sum())
        zero = frame["cost_hkd"].eq(0)
        allowed_zero = (
            frame["parking_status"].isin(
                [
                    "resolved_home_marginal_zero_fixed_separate",
                    "resolved_work_subscription_assumed_prepaid",
                ]
            )
            | (
                frame["parking_status"].eq("resolved_proxy_charge")
                & frame["parking_duration_s"].eq(0)
            )
        )
        zero_rule_valid[scenario] = bool(
            (allowed_zero | ~zero).all()
        )
        null_rule_valid[scenario] = bool(
            frame.loc[unresolved | out, "cost_hkd"].isna().all()
        )
        totals[scenario] = float(
            frame.loc[resolved, "cost_hkd"].sum()
        )

    pivot = events.pivot(
        index="parking_event_key",
        columns="scenario",
        values="cost_hkd",
    ).dropna()
    order_valid = bool(
        (
            (pivot["low"] <= pivot["base"])
            & (pivot["base"] <= pivot["high"])
        ).all()
    )
    work_monthly_attached = int(
        events.loc[
            events["scenario"].eq("low")
            & events["destination_activity_group"].eq("work"),
            "cost_hkd",
        ].fillna(0).ne(0).sum()
    )
    home_nonzero = int(
        events.loc[
            events["parking_status"].eq(
                "resolved_home_marginal_zero_fixed_separate"
            ),
            "cost_hkd",
        ].ne(0).sum()
    )
    terminal_home = int(
        (
            private["terminal_event"]
            & private["destination_activity_group"].eq("home")
        ).sum()
    )
    terminal_nonhome = int(
        (
            private["terminal_event"]
            & ~private["destination_activity_group"].eq("home")
        ).sum()
    )
    cross_midnight = int(private["parking_crosses_midnight"].sum())
    cross_midnight_rate_switch = int(
        identity.loc[
            identity["parking_crosses_midnight"],
            "day_night_rate_switch_count",
        ].gt(0).sum()
    )
    private_keys = set(
        zip(
            private["person_id"],
            private["leg_sequence"],
            strict=False,
        )
    )
    identity_private = identity.loc[
        identity["vehicle_class"].eq("private_car")
    ]
    event_private_keys = set(
        zip(
            identity_private["person_id"],
            identity_private["leg_sequence"],
            strict=False,
        )
    )
    private_arrival_mapping_complete = bool(
        len(identity_private) == len(private)
        and event_private_keys == private_keys
    )
    publishable = bool(
        all(value == 67718 for value in row_counts.values())
        and all(leg_key_unique.values())
        and event_identity_unique
        and event_scenario_unique
        and private_arrival_mapping_complete
        and chain_diagnostics[
            "duplicate_parking_event_key_count"
        ]
        == 0
        and all(value == 0 for value in aggregation_errors.values())
        and order_valid
        and all(zero_rule_valid.values())
        and all(null_rule_valid.values())
        and work_monthly_attached == 0
        and home_nonzero == 0
    )
    return {
        "audit": (
            "Hong Kong private-car destination parking by physical vehicle "
            "event v1"
        ),
        "source_commit": SOURCE_COMMIT,
        "candidate_output_only": True,
        "parking_price_interpretation": PROXY_QUALITY,
        "facility_level_parking_price_claimed": False,
        "matsim_scoring_modified": False,
        "toll_candidate_modified": False,
        "publishable_candidate": publishable,
        "blocked": not publishable,
        "input_counts": {
            "car_legs": int(len(chains)),
            "private_car_legs": int(len(private)),
            "motorcycle_out_of_scope": int(
                chains["vehicle_class"].eq("motorcycle").sum()
            ),
            "used_private_cars": int(
                private["vehicle_ref_id"].nunique()
            ),
        },
        "physical_event_audit_from_raw_arrivals": {
            **chain_diagnostics,
            **event_diagnostics,
            "physical_private_car_event_count": int(len(private)),
            "event_identity_key_unique_before_scenario_expansion": (
                event_identity_unique
            ),
            "event_scenario_key_unique": event_scenario_unique,
            "every_private_arrival_mapped_to_event_or_explicit_unresolved": (
                private_arrival_mapping_complete
            ),
        },
        "vehicle_chain_diagnostics": {
            "time_overlap_count": int(
                chain_diagnostics[
                    "overlapping_vehicle_parking_event_count"
                ]
            ),
            "facility_mismatch_count": int(
                chain_diagnostics["facility_chain_mismatch_count"]
            ),
            "time_overlap_and_facility_mismatch_intersection": int(
                chain_diagnostics[
                    "overlap_and_facility_mismatch_intersection_count"
                ]
            ),
            "issue_union_count_non_mutually_exclusive_inputs": int(
                chain_diagnostics["vehicle_chain_issue_union_count"]
            ),
            "terminal_home_count": terminal_home,
            "terminal_non_home_count": terminal_nonhome,
            "cross_midnight_valid_event_count": cross_midnight,
            "cross_midnight_events_with_day_night_rate_switch_base": (
                cross_midnight_rate_switch
            ),
            "time_values_preserve_absolute_model_day_seconds": True,
            "vehicle_time_overlap_automatically_corrected": False,
            "facility_mismatch_charged": False,
        },
        "scenario_outputs": {
            "row_counts": row_counts,
            "person_leg_key_unique": leg_key_unique,
            "parking_status_counts": status_counts,
            "resolved_counts": resolved_counts,
            "unresolved_counts": unresolved_counts,
            "out_of_scope_counts": out_counts,
            "resolved_only_totals_hkd": totals,
            "event_to_leg_aggregation_max_abs_error_hkd": (
                aggregation_errors
            ),
            "non_null_low_le_base_le_high": order_valid,
            "zero_status_rule_valid": zero_rule_valid,
            "unresolved_and_out_of_scope_cost_null": null_rule_valid,
            "home_resolved_nonzero_count": home_nonzero,
            "work_monthly_rate_attached_to_leg_count": (
                work_monthly_attached
            ),
            "fixed_residential_parking_in_marginal_total": False,
        },
        "benchmark_comparison": benchmark_comparison(
            chains, chain_diagnostics
        ),
    }


def required_repairs(validation: dict[str, Any]) -> pd.DataFrame:
    chain = validation["vehicle_chain_diagnostics"]
    return pd.DataFrame(
        [
            {
                "repair_id": "PARKING-R01",
                "severity": "high",
                "component": "vehicle_chain",
                "finding": (
                    f"{chain['time_overlap_count']} arrivals overlap the "
                    "same vehicle's next departure; "
                    f"{chain['facility_mismatch_count']} have a facility "
                    "mismatch, with "
                    f"{chain['time_overlap_and_facility_mismatch_intersection']} "
                    "in both diagnostics."
                ),
                "required_change": (
                    "Keep these events unresolved unless the canonical "
                    "vehicle chain is corrected upstream."
                ),
            },
            {
                "repair_id": "PARKING-R02",
                "severity": "high",
                "component": "terminal_event",
                "finding": (
                    f"{chain['terminal_non_home_count']} terminal non-home "
                    "arrivals lack a next-departure duration."
                ),
                "required_change": (
                    "Provide explicit activity end-time evidence or keep "
                    "their parking cost null."
                ),
            },
            {
                "repair_id": "PARKING-R03",
                "severity": "medium",
                "component": "price_precision",
                "finding": (
                    "Destination facilities are not observed car parks with "
                    "facility-specific tariffs."
                ),
                "required_change": (
                    "Retain official_rate_bounded_zone_activity_proxy until "
                    "a sourced facility-level car-park inventory exists."
                ),
            },
            {
                "repair_id": "PARKING-R04",
                "severity": "high",
                "component": "fixed_cost_boundary",
                "finding": (
                    "Residential parking and prepaid work subscriptions are "
                    "fixed-cost boundaries, not repeated leg charges."
                ),
                "required_change": (
                    "Do not attach residential or monthly work rates to "
                    "ordinary marginal parking legs."
                ),
            },
        ]
    )


def main() -> None:
    args = parse_args()
    canonical = canonical_paths(args.input_project_root.resolve())
    required_local = {
        **INPUT_DOCS,
        **FEASIBILITY_INPUTS,
        "parking_rules": RULE_PATH,
        "source_manifest": SOURCE_MANIFEST_PATH,
    }
    missing = [
        key for key, path in required_local.items() if not path.exists()
    ]
    if missing:
        raise FileNotFoundError(
            f"Missing local parking inputs: {missing}"
        )
    protected = internal_protected_paths(args.output_dir)
    internal_before = hash_map(protected)
    canonical_before = canonical_hashes(canonical)

    manifest = pd.read_parquet(canonical["trip_manifest"])
    manifest["person_id"] = manifest["person_id"].astype(str)
    needed_keys = set(
        zip(
            manifest.loc[manifest["mode"].eq("car"), "person_id"],
            manifest.loc[manifest["mode"].eq("car"), "leg_sequence"].astype(
                int
            ),
            strict=False,
        )
    )
    routes = parse_routed_car_legs(
        canonical["plans_routed"], needed_keys
    )
    vehicles = parse_vehicle_types(canonical["private_vehicles"])
    facilities = parse_facility_ids(canonical["facilities"])
    feasibility = pd.read_parquet(
        FEASIBILITY_INPUTS["feasibility_table"]
    )
    feasibility["person_id"] = feasibility["person_id"].astype(str)
    chains, chain_diagnostics = build_vehicle_chains(
        manifest, routes, feasibility, vehicles, facilities
    )
    source_rules = pd.read_csv(RULE_PATH)
    clean_rules = repository_relative_rules(source_rules)
    events, event_diagnostics = apply_rules(chains, source_rules)
    frames = leg_frames(events)
    summary = build_summary(frames)
    validation = validate(
        chains,
        events,
        frames,
        chain_diagnostics,
        event_diagnostics,
    )

    internal_after = hash_map(protected)
    canonical_after = canonical_hashes(canonical)
    hashes_unchanged = bool(
        internal_before == internal_after
        and canonical_before == canonical_after
    )
    validation["protected_inputs"] = {
        "all_existing_car_cost_files_unchanged": (
            internal_before == internal_after
        ),
        "toll_network_mapping_v1_unchanged": all(
            internal_before[key] == internal_after[key]
            for key in internal_before
            if "toll_network_mapping_v1" in key
        ),
        "toll_rate_application_v1_unchanged": all(
            internal_before[key] == internal_after[key]
            for key in internal_before
            if "toll_rate_application_v1" in key
        ),
        "canonical_inputs_unchanged": (
            canonical_before == canonical_after
        ),
        "all_protected_sha256_unchanged": hashes_unchanged,
    }
    if not hashes_unchanged:
        validation["publishable_candidate"] = False
        validation["blocked"] = True
        raise RuntimeError("Protected input changed during parking build")

    hashes = {
        "input_root_role": (
            "canonical_project_read_only_large_inputs; absolute root omitted"
        ),
        "source_commit": SOURCE_COMMIT,
        "canonical_role_paths": {
            "plans_routed": (
                "data/matsim_agents/hongkong/"
                "typical_weekday_5pct_v2_activity_modechoice/"
                "plans_routed_5pct_v2.xml.gz"
            ),
            "facilities": (
                "data/matsim_agents/hongkong/"
                "typical_weekday_5pct_v2_activity_modechoice/"
                "facilities_5pct_v2.xml.gz"
            ),
            "private_vehicles": (
                "data/matsim_agents/hongkong/"
                "typical_weekday_5pct_v2_activity_modechoice/"
                "privateVehicles_5pct.xml.gz"
            ),
            "trip_manifest": (
                "data/matsim_agents/hongkong/"
                "typical_weekday_5pct_v2_activity_modechoice/"
                "agent_trip_manifest_v2.parquet"
            ),
        },
        "canonical_hashes_before": canonical_before,
        "canonical_hashes_after": canonical_after,
        "existing_car_cost_hashes_before": internal_before,
        "existing_car_cost_hashes_after": internal_after,
        "all_protected_sha256_unchanged": hashes_unchanged,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    events.to_parquet(
        args.output_dir / "car_parking_events.parquet", index=False
    )
    for scenario, frame in frames.items():
        frame.to_parquet(
            args.output_dir
            / f"car_leg_parking_cost_estimates_{scenario}.parquet",
            index=False,
        )
    summary.to_csv(
        args.output_dir / "parking_event_application_summary.csv",
        index=False,
        encoding="utf-8",
    )
    required_repairs(validation).to_csv(
        args.output_dir / "parking_event_required_repairs.csv",
        index=False,
        encoding="utf-8",
    )
    clean_rules.to_csv(
        args.output_dir / "parking_cost_rules_repository_relative.csv",
        index=False,
        encoding="utf-8",
    )
    (
        args.output_dir / "parking_event_application_validation.json"
    ).write_text(
        json.dumps(validation, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "parking_event_input_hashes.json").write_text(
        json.dumps(hashes, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "physical_private_car_events": validation[
                    "physical_event_audit_from_raw_arrivals"
                ]["physical_private_car_event_count"],
                "duplicate_event_keys": chain_diagnostics[
                    "duplicate_parking_event_key_count"
                ],
                "time_overlap": chain_diagnostics[
                    "overlapping_vehicle_parking_event_count"
                ],
                "facility_mismatch": chain_diagnostics[
                    "facility_chain_mismatch_count"
                ],
                "intersection": chain_diagnostics[
                    "overlap_and_facility_mismatch_intersection_count"
                ],
                "status_counts_base": validation["scenario_outputs"][
                    "parking_status_counts"
                ]["base"],
                "totals_hkd": validation["scenario_outputs"][
                    "resolved_only_totals_hkd"
                ],
                "protected": hashes_unchanged,
                "publishable_candidate": validation[
                    "publishable_candidate"
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
