#!/usr/bin/env python3
"""Audit Hong Kong taxi main-trip mapping across unrouted and routed plans.

The audit is read-only with respect to all existing plans, fare products, and
utility-bridge products. Corrected route, fare, and utility values are written
only to a new audit directory. MATSim is not run.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from lxml import etree as ET


ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = (
    ROOT
    / "data/taxi/hongkong/processed/"
    "taxi_routed_main_leg_mapping_audit_v1"
)

EXPECTED_PLAN_HASHES = {
    "plans_unrouted_5pct_v2.xml.gz": (
        "5b463376f89bf607c0980d2e84e096f6424c76b6dc5697669aa1f9880de6a0f7"
    ),
    "plans_routed_5pct_v2.xml.gz": (
        "c73ee48e792e7aebd55b7a2691664ae7f3f4f27d307aef2a6bf58263b3aaafea"
    ),
}
EXPECTED_TAXI_LEGS = 37_286
EXPECTED_EXPLICIT_TAXI = 4_614
EXPECTED_ALLOCATED_TAXI = 32_672
LEG_KEY = ["person_id", "leg_sequence"]
TOLERANCE = 1e-9

WORKTREE_PROTECTED_PATHS = [
    "data/taxi/hongkong/processed/taxi_initial_plan_allocation_v1",
    "data/taxi/hongkong/processed/taxi_fare_model_v1",
    "data/taxi/hongkong/processed/taxi_utility_bridge_v1",
    "data/matsim_agents/hongkong",
    "src",
    "scenarios",
]
EXTERNAL_PROTECTED_PATHS = [
    "data/matsim_agents/hongkong",
    "src",
    "scenarios",
]
ALLOWED_REPOSITORY_PATHS = {
    "scripts/hong_kong_single_city/demand_generation/"
    "audit_hong_kong_taxi_routed_main_leg_mapping.py",
    "data/taxi/hongkong/processed/"
    "taxi_routed_main_leg_mapping_audit_v1/"
    "routed_activity_type_inventory.csv",
    "data/taxi/hongkong/processed/"
    "taxi_routed_main_leg_mapping_audit_v1/"
    "routed_plan_structure_summary.csv",
    "data/taxi/hongkong/processed/"
    "taxi_routed_main_leg_mapping_audit_v1/"
    "taxi_unrouted_to_routed_main_leg_mapping.parquet",
    "data/taxi/hongkong/processed/"
    "taxi_routed_main_leg_mapping_audit_v1/"
    "taxi_existing_route_extraction_impact.csv",
    "data/taxi/hongkong/processed/"
    "taxi_routed_main_leg_mapping_audit_v1/"
    "taxi_routed_main_leg_mapping_validation.json",
    "docs/HONG_KONG_TAXI_ROUTED_MAIN_LEG_MAPPING_AUDIT.md",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--matsim-root",
        type=Path,
        required=True,
        help="Explicit read-only MATSim project root.",
    )
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    return parser.parse_args()


def local_name(element: ET._Element) -> str:
    return ET.QName(element).localname


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_paths(paths: dict[str, Path]) -> dict[str, str]:
    return {name: sha256(path) for name, path in paths.items()}


def require_files(paths: dict[str, Path]) -> None:
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Missing required audit inputs:\n" + "\n".join(missing)
        )


def git_root(path: Path) -> Path:
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return Path(result.stdout.strip()).resolve()


def git_status(repository: Path, pathspecs: list[str]) -> str:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "status",
            "--short",
            "--",
            *pathspecs,
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def changed_paths(repository: Path) -> list[str]:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "-z",
        ],
        check=True,
        capture_output=True,
    )
    paths: list[str] = []
    for entry in result.stdout.decode("utf-8").split("\0"):
        if entry:
            paths.append(entry[3:].replace("\\", "/"))
    return sorted(set(paths))


def source_paths(matsim_root: Path) -> dict[str, Path]:
    v2 = (
        matsim_root
        / "data/matsim_agents/hongkong/"
        "typical_weekday_5pct_v2_activity_modechoice"
    )
    v1 = (
        matsim_root
        / "data/matsim_agents/hongkong/typical_weekday_5pct_v1"
    )
    allocation = (
        ROOT
        / "data/taxi/hongkong/processed/"
        "taxi_initial_plan_allocation_v1"
    )
    fare = (
        ROOT
        / "data/taxi/hongkong/processed/taxi_fare_model_v1"
    )
    bridge = (
        ROOT
        / "data/taxi/hongkong/processed/taxi_utility_bridge_v1"
    )
    return {
        "plans_unrouted_5pct_v2.xml.gz": (
            v2 / "plans_unrouted_5pct_v2.xml.gz"
        ),
        "plans_routed_5pct_v2.xml.gz": (
            v2 / "plans_routed_5pct_v2.xml.gz"
        ),
        "agent_trip_manifest_v2.parquet": (
            v2 / "agent_trip_manifest_v2.parquet"
        ),
        "agent_trip_manifest_v1.parquet": (
            v1 / "agent_trip_manifest.parquet"
        ),
        "taxi_candidate_leg_classification.csv": (
            allocation / "taxi_candidate_leg_classification.csv"
        ),
        "taxi_allocation_summary.json": (
            allocation / "taxi_allocation_summary.json"
        ),
        "taxi_leg_fare_estimates_base.parquet": (
            fare / "taxi_leg_fare_estimates_base.parquet"
        ),
        "taxi_fare_model_validation.json": (
            fare / "taxi_fare_model_validation.json"
        ),
        "taxi_fare_rules.csv": fare / "taxi_fare_rules.csv",
        "old_ride_vs_new_taxi_leg_audit.parquet": (
            bridge / "old_ride_vs_new_taxi_leg_audit.parquet"
        ),
        "taxi_utility_bridge_validation.json": (
            bridge / "taxi_utility_bridge_validation.json"
        ),
    }


def output_paths(out_dir: Path) -> dict[str, Path]:
    return {
        "routed_activity_type_inventory.csv": (
            out_dir / "routed_activity_type_inventory.csv"
        ),
        "routed_plan_structure_summary.csv": (
            out_dir / "routed_plan_structure_summary.csv"
        ),
        "taxi_unrouted_to_routed_main_leg_mapping.parquet": (
            out_dir
            / "taxi_unrouted_to_routed_main_leg_mapping.parquet"
        ),
        "taxi_existing_route_extraction_impact.csv": (
            out_dir / "taxi_existing_route_extraction_impact.csv"
        ),
        "taxi_routed_main_leg_mapping_validation.json": (
            out_dir / "taxi_routed_main_leg_mapping_validation.json"
        ),
    }


def direct_children(
    element: ET._Element, tag_name: str
) -> list[ET._Element]:
    return [
        child for child in element if local_name(child) == tag_name
    ]


def choose_selected_plan(
    person: ET._Element,
) -> tuple[ET._Element | None, int, bool]:
    plans = direct_children(person, "plan")
    if len(plans) == 1:
        return plans[0], 1, True
    selected = [
        plan
        for plan in plans
        if str(plan.get("selected", "")).lower() in {"yes", "true"}
    ]
    if len(selected) == 1:
        return selected[0], len(plans), True
    return None, len(plans), False


def parse_time_s(value: str | None) -> float:
    if value is None or value == "":
        return float("nan")
    parts = str(value).split(":")
    if len(parts) == 3:
        return (
            int(parts[0]) * 3600
            + int(parts[1]) * 60
            + float(parts[2])
        )
    return float(value)


def activity_signature_dict(
    activity: ET._Element,
) -> dict[str, str]:
    def canonical_coordinate(value: str | None) -> str:
        if value in (None, ""):
            return ""
        return format(float(value), ".15g")

    return {
        "type": activity.get("type", ""),
        "facility": activity.get("facility", ""),
        "link": activity.get("link", ""),
        "x": canonical_coordinate(activity.get("x")),
        "y": canonical_coordinate(activity.get("y")),
    }


def activity_signature_text(activity: ET._Element) -> str:
    return json.dumps(
        activity_signature_dict(activity),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def signature_sequence_hash(signatures: list[str]) -> str:
    digest = hashlib.sha256()
    for signature in signatures:
        digest.update(signature.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def route_details(leg: ET._Element) -> dict[str, Any]:
    routes = direct_children(leg, "route")
    route = routes[0] if len(routes) == 1 else None
    if route is None:
        route_type = ""
        route_distance = float("nan")
        route_travel_time = float("nan")
        start_link = ""
        end_link = ""
        route_text = ""
        attributes_hash = ""
        text_hash = hashlib.sha256(b"").hexdigest()
    else:
        route_type = route.get("type", "")
        route_distance = (
            float(route.get("distance"))
            if route.get("distance") not in (None, "")
            else float("nan")
        )
        route_travel_time = parse_time_s(route.get("trav_time"))
        start_link = route.get("start_link", "")
        end_link = route.get("end_link", "")
        route_text = route.text or ""
        attributes_hash = hashlib.sha256(
            json.dumps(
                dict(sorted(route.attrib.items())),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        text_hash = hashlib.sha256(
            route_text.encode("utf-8")
        ).hexdigest()
    leg_travel_time = parse_time_s(leg.get("trav_time"))
    actual_travel_time = (
        leg_travel_time
        if np.isfinite(leg_travel_time)
        else route_travel_time
    )
    return {
        "mode": leg.get("mode", ""),
        "leg_travel_time_s": leg_travel_time,
        "actual_travel_time_s": actual_travel_time,
        "route_count": len(routes),
        "route_type": route_type,
        "route_distance_m": route_distance,
        "route_travel_time_s": route_travel_time,
        "start_link": start_link,
        "end_link": end_link,
        "route_text_present": bool(route_text.strip()),
        "route_text_hash": text_hash,
        "route_attributes_hash": attributes_hash,
    }


def blank_structure() -> dict[str, Any]:
    return {
        "counts": Counter(),
        "mode_counts": Counter(),
        "activity_type_counts": Counter(),
        "route_type_counts": Counter(),
        "plan_count_distribution": Counter(),
        "multi_plan_persons": 0,
        "selected_plan_unresolved_persons": 0,
        "invalid_unrouted_alternation_persons": 0,
        "person_order_hasher": hashlib.sha256(),
    }


def count_person_structure(
    person: ET._Element,
    structure: dict[str, Any],
) -> tuple[ET._Element | None, bool]:
    structure["counts"]["persons"] += 1
    person_id = person.get("id", "")
    structure["person_order_hasher"].update(
        person_id.encode("utf-8") + b"\n"
    )
    selected_plan, plan_count, determinate = choose_selected_plan(person)
    structure["plan_count_distribution"][plan_count] += 1
    structure["counts"]["plans"] += plan_count
    if plan_count > 1:
        structure["multi_plan_persons"] += 1
    if not determinate:
        structure["selected_plan_unresolved_persons"] += 1

    for plan in direct_children(person, "plan"):
        for element in plan.iter():
            tag = local_name(element)
            if tag == "activity":
                structure["counts"]["activities"] += 1
                structure["activity_type_counts"][
                    element.get("type", "")
                ] += 1
            elif tag == "leg":
                structure["counts"]["legs"] += 1
                structure["mode_counts"][
                    element.get("mode", "")
                ] += 1
            elif tag == "route":
                structure["counts"]["routes"] += 1
                structure["route_type_counts"][
                    element.get("type", "")
                ] += 1
    return selected_plan, determinate


def iter_persons(path: Path):
    with gzip.open(path, "rb") as handle:
        context = ET.iterparse(
            handle,
            events=("end",),
            tag="person",
            huge_tree=True,
        )
        for _, person in context:
            yield person
            person.clear()
            parent = person.getparent()
            if parent is not None:
                while person.getprevious() is not None:
                    del parent[0]


def scan_unrouted(
    path: Path,
    target_indices_by_person: dict[str, set[int]],
) -> tuple[
    dict[str, Any],
    dict[str, tuple[int, str]],
    dict[tuple[str, int], dict[str, Any]],
]:
    structure = blank_structure()
    person_signatures: dict[str, tuple[int, str]] = {}
    target_trip_info: dict[tuple[str, int], dict[str, Any]] = {}

    for person in iter_persons(path):
        person_id = person.get("id", "")
        selected_plan, determinate = count_person_structure(
            person, structure
        )
        if not determinate or selected_plan is None:
            continue
        direct = [
            element
            for element in selected_plan
            if local_name(element) in {"activity", "leg"}
        ]
        expected = [
            "activity" if index % 2 == 0 else "leg"
            for index in range(len(direct))
        ]
        tags = [local_name(element) for element in direct]
        alternating = (
            len(direct) >= 1
            and len(direct) % 2 == 1
            and tags == expected
        )
        if not alternating:
            structure["invalid_unrouted_alternation_persons"] += 1

        activities = [
            element for element in direct if local_name(element) == "activity"
        ]
        legs = [
            element for element in direct if local_name(element) == "leg"
        ]
        signatures = [
            activity_signature_text(activity)
            for activity in activities
        ]
        person_signatures[person_id] = (
            len(signatures),
            signature_sequence_hash(signatures),
        )

        for trip_index in target_indices_by_person.get(person_id, set()):
            key = (person_id, trip_index)
            if (
                not alternating
                or trip_index < 0
                or trip_index >= len(legs)
                or trip_index + 1 >= len(activities)
            ):
                target_trip_info[key] = {
                    "unrouted_mapping_status": "unrouted_trip_not_found"
                }
                continue
            origin = activities[trip_index]
            destination = activities[trip_index + 1]
            target_trip_info[key] = {
                "unrouted_mapping_status": "validated_main_trip",
                "unrouted_mode": legs[trip_index].get("mode", ""),
                "origin_activity_type": origin.get("type", ""),
                "destination_activity_type": destination.get("type", ""),
                "origin_activity_signature": (
                    activity_signature_text(origin)
                ),
                "destination_activity_signature": (
                    activity_signature_text(destination)
                ),
            }

    structure["person_order_sha256"] = (
        structure["person_order_hasher"].hexdigest()
    )
    del structure["person_order_hasher"]
    return structure, person_signatures, target_trip_info


def build_routed_trip_groups(
    selected_plan: ET._Element,
    unrouted_activity_types: set[str],
    capture_leg_details: bool,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[str],
    set[str],
    set[str],
    bool,
]:
    direct = [
        element
        for element in selected_plan
        if local_name(element) in {"activity", "leg"}
    ]
    routed_only_types = {
        element.get("type", "")
        for element in direct
        if local_name(element) == "activity"
        and element.get("type", "") not in unrouted_activity_types
    }
    accepted_stage_types = {
        activity_type
        for activity_type in routed_only_types
        if activity_type.endswith(" interaction")
    }
    unknown_routed_only_types = (
        routed_only_types - accepted_stage_types
    )

    raw_legs: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    main_signatures: list[str] = []
    current_origin: ET._Element | None = None
    current_legs: list[dict[str, Any]] = []
    current_stages: list[str] = []
    cumulative_stage_count = 0
    cumulative_extra_leg_count = 0
    valid = True

    for element in direct:
        tag = local_name(element)
        if tag == "leg":
            details = (
                route_details(element)
                if capture_leg_details
                else {
                    "mode": element.get("mode", ""),
                    "route_type": "",
                }
            )
            details["raw_leg_sequence"] = len(raw_legs)
            raw_legs.append(details)
            current_legs.append(details)
            continue

        activity_type = element.get("type", "")
        if activity_type in accepted_stage_types:
            if current_origin is None:
                valid = False
            current_stages.append(activity_type)
            continue
        if activity_type in unknown_routed_only_types:
            valid = False

        signature = activity_signature_text(element)
        main_signatures.append(signature)
        if current_origin is None:
            current_origin = element
            continue

        group = {
            "origin_activity": current_origin,
            "destination_activity": element,
            "origin_activity_signature": (
                activity_signature_text(current_origin)
            ),
            "destination_activity_signature": signature,
            "legs": current_legs,
            "stage_activity_types": current_stages,
            "preceding_stage_activity_count": cumulative_stage_count,
            "preceding_extra_routed_leg_count": (
                cumulative_extra_leg_count
            ),
        }
        if not current_legs:
            valid = False
        groups.append(group)
        cumulative_stage_count += len(current_stages)
        cumulative_extra_leg_count += max(len(current_legs) - 1, 0)
        current_origin = element
        current_legs = []
        current_stages = []

    if (
        current_origin is None
        or current_legs
        or current_stages
        or len(groups) != max(len(main_signatures) - 1, 0)
    ):
        valid = False
    return (
        groups,
        raw_legs,
        main_signatures,
        accepted_stage_types,
        unknown_routed_only_types,
        valid,
    )


def empty_leg_details(prefix: str) -> dict[str, Any]:
    return {
        f"{prefix}_routed_mode": "",
        f"{prefix}_route_type": "",
        f"{prefix}_route_distance_m": float("nan"),
        f"{prefix}_leg_travel_time_s": float("nan"),
        f"{prefix}_route_travel_time_s": float("nan"),
        f"{prefix}_actual_travel_time_s": float("nan"),
        f"{prefix}_start_link": "",
        f"{prefix}_end_link": "",
        f"{prefix}_route_text_present": False,
        f"{prefix}_route_text_hash": "",
        f"{prefix}_route_attributes_hash": "",
    }


def prefixed_leg_details(
    prefix: str, details: dict[str, Any] | None
) -> dict[str, Any]:
    if details is None:
        return empty_leg_details(prefix)
    return {
        f"{prefix}_routed_mode": details["mode"],
        f"{prefix}_route_type": details["route_type"],
        f"{prefix}_route_distance_m": details["route_distance_m"],
        f"{prefix}_leg_travel_time_s": (
            details["leg_travel_time_s"]
        ),
        f"{prefix}_route_travel_time_s": (
            details["route_travel_time_s"]
        ),
        f"{prefix}_actual_travel_time_s": (
            details["actual_travel_time_s"]
        ),
        f"{prefix}_start_link": details["start_link"],
        f"{prefix}_end_link": details["end_link"],
        f"{prefix}_route_text_present": (
            details["route_text_present"]
        ),
        f"{prefix}_route_text_hash": (
            details["route_text_hash"]
        ),
        f"{prefix}_route_attributes_hash": (
            details["route_attributes_hash"]
        ),
    }


def scan_routed(
    path: Path,
    target_indices_by_person: dict[str, set[int]],
    unrouted_person_signatures: dict[str, tuple[int, str]],
    unrouted_target_info: dict[tuple[str, int], dict[str, Any]],
    unrouted_activity_types: set[str],
) -> tuple[dict[str, Any], dict[tuple[str, int], dict[str, Any]]]:
    structure = blank_structure()
    remaining_person_ids = set(unrouted_person_signatures)
    unexpected_person_ids: list[str] = []
    mapping: dict[tuple[str, int], dict[str, Any]] = {}
    accepted_stage_types: set[str] = set()
    unknown_routed_only_types: set[str] = set()
    main_sequence_mismatch_persons = 0
    ambiguous_stage_persons = 0

    for person in iter_persons(path):
        person_id = person.get("id", "")
        selected_plan, determinate = count_person_structure(
            person, structure
        )
        if person_id in remaining_person_ids:
            remaining_person_ids.remove(person_id)
        else:
            unexpected_person_ids.append(person_id)
        if not determinate or selected_plan is None:
            continue

        (
            groups,
            raw_legs,
            main_signatures,
            person_stage_types,
            person_unknown_types,
            stage_structure_valid,
        ) = build_routed_trip_groups(
            selected_plan,
            unrouted_activity_types,
            person_id in target_indices_by_person,
        )
        accepted_stage_types.update(person_stage_types)
        unknown_routed_only_types.update(person_unknown_types)
        if not stage_structure_valid:
            ambiguous_stage_persons += 1

        routed_signature = (
            len(main_signatures),
            signature_sequence_hash(main_signatures),
        )
        main_sequence_matches = (
            unrouted_person_signatures.get(person_id)
            == routed_signature
        )
        if not main_sequence_matches:
            main_sequence_mismatch_persons += 1

        for trip_index in target_indices_by_person.get(person_id, set()):
            key = (person_id, trip_index)
            base = unrouted_target_info.get(key, {})
            row: dict[str, Any] = {
                "old_assumed_routed_raw_leg_sequence": trip_index,
                "main_trip_index": trip_index,
                "main_activity_sequence_matches": (
                    main_sequence_matches
                ),
                "stage_structure_valid": stage_structure_valid,
            }
            old_leg = (
                raw_legs[trip_index]
                if 0 <= trip_index < len(raw_legs)
                else None
            )
            row.update(prefixed_leg_details("old_extracted", old_leg))

            if not stage_structure_valid:
                status = "ambiguous_stage_structure"
                group = None
            elif trip_index < 0 or trip_index >= len(groups):
                status = "no_corresponding_main_trip"
                group = None
            else:
                group = groups[trip_index]
                signatures_match = bool(
                    group["origin_activity_signature"]
                    == base.get("origin_activity_signature")
                    and group["destination_activity_signature"]
                    == base.get("destination_activity_signature")
                )
                if not signatures_match:
                    status = "main_activity_signature_mismatch"
                else:
                    ride_legs = [
                        leg
                        for leg in group["legs"]
                        if leg["mode"] == "ride"
                    ]
                    if len(ride_legs) == 0:
                        status = "no_ride_leg_in_mapped_trip"
                    elif len(ride_legs) > 1:
                        status = "multiple_ride_legs_in_mapped_trip"
                    else:
                        status = "mapped_unique_ride_leg"

            if group is None:
                row.update(
                    {
                        "routed_trip_leg_count": 0,
                        "routed_trip_mode_sequence": "",
                        "routed_stage_activity_sequence": "",
                        "routed_trip_route_type_sequence": "",
                        "preceding_stage_activity_count": 0,
                        "preceding_extra_routed_leg_count": 0,
                        "mapped_routed_raw_leg_sequence": np.nan,
                        "mapped_routed_leg_position_within_trip": np.nan,
                    }
                )
                row.update(prefixed_leg_details("mapped", None))
            else:
                row.update(
                    {
                        "routed_trip_leg_count": len(group["legs"]),
                        "routed_trip_mode_sequence": ">".join(
                            leg["mode"] for leg in group["legs"]
                        ),
                        "routed_stage_activity_sequence": ">".join(
                            group["stage_activity_types"]
                        ),
                        "routed_trip_route_type_sequence": ">".join(
                            leg["route_type"] for leg in group["legs"]
                        ),
                        "preceding_stage_activity_count": (
                            group["preceding_stage_activity_count"]
                        ),
                        "preceding_extra_routed_leg_count": (
                            group["preceding_extra_routed_leg_count"]
                        ),
                    }
                )
                ride_legs = [
                    leg
                    for leg in group["legs"]
                    if leg["mode"] == "ride"
                ]
                mapped_leg = (
                    ride_legs[0] if len(ride_legs) == 1 else None
                )
                if mapped_leg is None:
                    row[
                        "mapped_routed_raw_leg_sequence"
                    ] = np.nan
                    row[
                        "mapped_routed_leg_position_within_trip"
                    ] = np.nan
                else:
                    row[
                        "mapped_routed_raw_leg_sequence"
                    ] = mapped_leg["raw_leg_sequence"]
                    row[
                        "mapped_routed_leg_position_within_trip"
                    ] = group["legs"].index(mapped_leg)
                row.update(
                    prefixed_leg_details("mapped", mapped_leg)
                )
            row["mapping_status"] = status
            mapped_raw = row["mapped_routed_raw_leg_sequence"]
            row["raw_sequence_matches"] = bool(
                pd.notna(mapped_raw)
                and int(mapped_raw) == trip_index
            )
            mapping[key] = row

    structure["person_order_sha256"] = (
        structure["person_order_hasher"].hexdigest()
    )
    del structure["person_order_hasher"]
    structure["missing_person_ids_count"] = len(remaining_person_ids)
    structure["unexpected_person_ids_count"] = len(
        unexpected_person_ids
    )
    structure["main_sequence_mismatch_persons"] = (
        main_sequence_mismatch_persons
    )
    structure["ambiguous_stage_persons"] = ambiguous_stage_persons
    structure["accepted_stage_types"] = sorted(accepted_stage_types)
    structure["unknown_routed_only_activity_types"] = sorted(
        unknown_routed_only_types
    )
    return structure, mapping


def fare_for_distance(distance_m: float, rule: pd.Series) -> float:
    if pd.isna(distance_m) or distance_m < 0:
        return float("nan")
    fare = float(rule["flagfall_hkd"])
    flagfall_distance = float(rule["flagfall_distance_m"])
    if distance_m <= flagfall_distance:
        return fare
    first_end = float(rule["first_tier_end_distance_m"])
    first_count = int(
        math.ceil(
            max(
                min(distance_m, first_end) - flagfall_distance,
                0.0,
            )
            / float(rule["first_tier_increment_distance_m"])
        )
    )
    second_count = int(
        math.ceil(
            max(distance_m - first_end, 0.0)
            / float(rule["second_tier_increment_distance_m"])
        )
    )
    fare += first_count * float(rule["first_tier_increment_hkd"])
    fare += second_count * float(rule["second_tier_increment_hkd"])
    return round(fare, 1)


def corrected_fares(
    taxi_types: pd.Series,
    distances: pd.Series,
    fare_rules: pd.DataFrame,
) -> pd.Series:
    rules = fare_rules.set_index("taxi_type")
    values = []
    for taxi_type, distance in zip(taxi_types, distances):
        calculation_type = (
            taxi_type
            if taxi_type in rules.index
            else "urban_taxi"
        )
        values.append(
            fare_for_distance(distance, rules.loc[calculation_type])
        )
    return pd.Series(values, index=taxi_types.index, dtype=float)


def distance_band(distance_m: float) -> str:
    if pd.isna(distance_m):
        return "unavailable"
    if distance_m < 2_000:
        return "00_0_2km"
    if distance_m < 5_000:
        return "01_2_5km"
    if distance_m < 10_000:
        return "02_5_10km"
    if distance_m < 20_000:
        return "03_10_20km"
    return "04_20km_plus"


def numeric_distribution(series: pd.Series) -> dict[str, float | int]:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return {"count": 0}
    return {
        "count": int(len(clean)),
        "mean": float(clean.mean()),
        "median": float(clean.median()),
        "p10": float(clean.quantile(0.10)),
        "p25": float(clean.quantile(0.25)),
        "p75": float(clean.quantile(0.75)),
        "p90": float(clean.quantile(0.90)),
        "min": float(clean.min()),
        "max": float(clean.max()),
    }


def grouped_impact(
    impact: pd.DataFrame, column: str
) -> list[dict[str, Any]]:
    rows = []
    for value, group in impact.groupby(
        column, dropna=False, sort=True
    ):
        rows.append(
            {
                "group": "<missing>" if pd.isna(value) else str(value),
                "legs": int(len(group)),
                "raw_sequence_match_share": float(
                    group["raw_sequence_matches"].mean()
                ),
                "route_distance_match_share": float(
                    group["route_distance_matches"].mean()
                ),
                "fare_match_share": float(
                    group["fare_matches"].mean()
                ),
                "fare_difference_mean_hkd": float(
                    group["fare_difference_hkd"].mean()
                ),
            }
        )
    return rows


def activity_inventory(
    unrouted: dict[str, Any],
    routed: dict[str, Any],
) -> pd.DataFrame:
    unrouted_counts = unrouted["activity_type_counts"]
    routed_counts = routed["activity_type_counts"]
    stage_types = set(routed["accepted_stage_types"])
    rows = []
    for activity_type in sorted(
        set(unrouted_counts) | set(routed_counts)
    ):
        unrouted_count = int(unrouted_counts[activity_type])
        routed_count = int(routed_counts[activity_type])
        is_stage = activity_type in stage_types
        reason = (
            "Routed-only MATSim interaction activity; removing every "
            "occurrence restores the exact unrouted main-activity "
            "signature sequence."
            if is_stage
            else "Present in the unrouted main-activity inventory and "
            "retained as a main activity."
        )
        for source, count in [
            ("unrouted", unrouted_count),
            ("routed", routed_count),
        ]:
            rows.append(
                {
                    "plan_source": source,
                    "activity_type": activity_type,
                    "activity_count": count,
                    "present_in_unrouted": unrouted_count > 0,
                    "present_in_routed": routed_count > 0,
                    "count_difference": routed_count - unrouted_count,
                    "proposed_stage_activity": is_stage,
                    "stage_classification_reason": reason,
                }
            )
    return pd.DataFrame(rows)


def structure_summary(
    unrouted: dict[str, Any],
    routed: dict[str, Any],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for source, structure in [
        ("unrouted", unrouted),
        ("routed", routed),
    ]:
        for metric in [
            "persons",
            "plans",
            "activities",
            "legs",
            "routes",
        ]:
            rows.append(
                {
                    "plan_source": source,
                    "section": "structure_count",
                    "metric": metric,
                    "category": "all",
                    "value": structure["counts"][metric],
                }
            )
        for mode, count in sorted(structure["mode_counts"].items()):
            rows.append(
                {
                    "plan_source": source,
                    "section": "mode_count",
                    "metric": "legs",
                    "category": mode,
                    "value": count,
                }
            )
        for route_type, count in sorted(
            structure["route_type_counts"].items()
        ):
            rows.append(
                {
                    "plan_source": source,
                    "section": "route_type_count",
                    "metric": "routes",
                    "category": route_type,
                    "value": count,
                }
            )
        for plan_count, people in sorted(
            structure["plan_count_distribution"].items()
        ):
            rows.append(
                {
                    "plan_source": source,
                    "section": "plans_per_person",
                    "metric": "persons",
                    "category": str(plan_count),
                    "value": people,
                }
            )
        rows.extend(
            [
                {
                    "plan_source": source,
                    "section": "person_plan_audit",
                    "metric": "multi_plan_persons",
                    "category": "all",
                    "value": structure["multi_plan_persons"],
                },
                {
                    "plan_source": source,
                    "section": "person_plan_audit",
                    "metric": "selected_plan_unresolved_persons",
                    "category": "all",
                    "value": structure[
                        "selected_plan_unresolved_persons"
                    ],
                },
                {
                    "plan_source": source,
                    "section": "person_order",
                    "metric": "person_order_sha256",
                    "category": "all",
                    "value": structure["person_order_sha256"],
                },
            ]
        )
    rows.extend(
        [
            {
                "plan_source": "comparison",
                "section": "cross_source",
                "metric": "person_id_order_matches",
                "category": "all",
                "value": (
                    unrouted["person_order_sha256"]
                    == routed["person_order_sha256"]
                ),
            },
            {
                "plan_source": "comparison",
                "section": "cross_source",
                "metric": "person_sets_match",
                "category": "all",
                "value": (
                    routed["missing_person_ids_count"] == 0
                    and routed["unexpected_person_ids_count"] == 0
                ),
            },
            {
                "plan_source": "comparison",
                "section": "cross_source",
                "metric": "main_sequence_mismatch_persons",
                "category": "all",
                "value": routed["main_sequence_mismatch_persons"],
            },
            {
                "plan_source": "comparison",
                "section": "stage_audit",
                "metric": "accepted_stage_types",
                "category": "all",
                "value": "|".join(routed["accepted_stage_types"]),
            },
            {
                "plan_source": "comparison",
                "section": "stage_audit",
                "metric": "ambiguous_stage_persons",
                "category": "all",
                "value": routed["ambiguous_stage_persons"],
            },
        ]
    )
    return pd.DataFrame(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    matsim_root = args.matsim_root.resolve()
    inputs = source_paths(matsim_root)
    outputs = output_paths(args.out_dir)
    require_files(inputs)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    worktree_repository = git_root(ROOT)
    external_repository = git_root(matsim_root)
    worktree_status_before = git_status(
        worktree_repository, WORKTREE_PROTECTED_PATHS
    )
    external_status_before = git_status(
        external_repository, EXTERNAL_PROTECTED_PATHS
    )
    if worktree_status_before or external_status_before:
        raise RuntimeError(
            "Protected paths must be clean before the audit.\n"
            f"worktree={worktree_status_before!r}\n"
            f"external={external_status_before!r}"
        )

    input_hashes_before = hash_paths(inputs)
    allocation_summary = json.loads(
        inputs["taxi_allocation_summary.json"].read_text(
            encoding="utf-8"
        )
    )
    fare_validation = json.loads(
        inputs["taxi_fare_model_validation.json"].read_text(
            encoding="utf-8"
        )
    )
    bridge_validation = json.loads(
        inputs["taxi_utility_bridge_validation.json"].read_text(
            encoding="utf-8"
        )
    )
    fare = pd.read_parquet(
        inputs["taxi_leg_fare_estimates_base.parquet"]
    )
    bridge = pd.read_parquet(
        inputs["old_ride_vs_new_taxi_leg_audit.parquet"]
    )
    allocation = pd.read_csv(
        inputs["taxi_candidate_leg_classification.csv"],
        encoding="utf-8-sig",
    )
    v2_manifest = pd.read_parquet(
        inputs["agent_trip_manifest_v2.parquet"]
    )
    v1_manifest = pd.read_parquet(
        inputs["agent_trip_manifest_v1.parquet"]
    )
    fare_rules = pd.read_csv(
        inputs["taxi_fare_rules.csv"], encoding="utf-8-sig"
    )

    def key_set(frame: pd.DataFrame) -> set[tuple[str, int]]:
        return set(
            zip(
                frame["person_id"].astype(str),
                frame["leg_sequence"].astype(int),
            )
        )

    fare_keys = key_set(fare)
    bridge_keys = key_set(bridge)
    allocated = allocation.loc[
        allocation["base_classification"].eq("taxi")
    ].copy()
    allocated_keys = key_set(allocated)
    explicit = v1_manifest.loc[
        v1_manifest["mode_detail"].eq("taxi")
    ].copy()
    explicit_keys = key_set(explicit)
    combined_classification_keys = allocated_keys | explicit_keys
    target_indices_by_person: dict[str, set[int]] = defaultdict(set)
    for person_id, leg_sequence in fare_keys:
        target_indices_by_person[person_id].add(leg_sequence)

    manifest_target = fare[LEG_KEY].merge(
        v2_manifest[
            LEG_KEY
            + [
                "mode",
                "origin_type",
                "destination_type",
                "origin_facility_id",
                "destination_facility_id",
            ]
        ],
        on=LEG_KEY,
        how="left",
        validate="one_to_one",
    )

    unrouted, person_signatures, target_trip_info = scan_unrouted(
        inputs["plans_unrouted_5pct_v2.xml.gz"],
        target_indices_by_person,
    )
    routed, routed_mapping = scan_routed(
        inputs["plans_routed_5pct_v2.xml.gz"],
        target_indices_by_person,
        person_signatures,
        target_trip_info,
        set(unrouted["activity_type_counts"]),
    )

    mapping_rows = []
    for fare_row in fare.itertuples(index=False):
        key = (str(fare_row.person_id), int(fare_row.leg_sequence))
        unrouted_info = target_trip_info.get(
            key,
            {"unrouted_mapping_status": "unrouted_trip_not_found"},
        )
        routed_info = routed_mapping.get(
            key,
            {
                "mapping_status": "no_corresponding_main_trip",
                **empty_leg_details("old_extracted"),
                **empty_leg_details("mapped"),
            },
        )
        mapping_rows.append(
            {
                "person_id": key[0],
                "unrouted_leg_sequence": key[1],
                "main_trip_index": key[1],
                "tour_id": fare_row.tour_id,
                "classification_source": (
                    fare_row.classification_source
                ),
                "taxi_type": fare_row.taxi_type,
                "population_group": fare_row.population_group,
                "role": fare_row.role,
                "activity_purpose": fare_row.activity_purpose,
                **unrouted_info,
                **routed_info,
            }
        )
    mapping = pd.DataFrame(mapping_rows)
    mapping["raw_sequence_matches"] = mapping[
        "raw_sequence_matches"
    ].fillna(False).astype(bool)

    impact = mapping.copy()
    impact = impact.merge(
        fare[
            LEG_KEY
            + [
                "route_distance_m",
                "actual_travel_time_s",
                "total_fare_distance_only_hkd",
                "distance_band",
            ]
        ].rename(
            columns={
                "leg_sequence": "unrouted_leg_sequence",
                "route_distance_m": "existing_route_distance_m",
                "actual_travel_time_s": (
                    "existing_actual_travel_time_s"
                ),
                "total_fare_distance_only_hkd": (
                    "existing_distance_only_fare_hkd"
                ),
                "distance_band": "existing_distance_band",
            }
        ),
        on=["person_id", "unrouted_leg_sequence"],
        how="left",
        validate="one_to_one",
    )
    impact = impact.merge(
        bridge[
            LEG_KEY
            + [
                "asc_equivalent",
                "old_ride_score",
                "new_taxi_score_before_asc",
            ]
        ].rename(
            columns={
                "leg_sequence": "unrouted_leg_sequence",
                "asc_equivalent": "existing_asc_equivalent",
                "old_ride_score": "existing_old_ride_score",
                "new_taxi_score_before_asc": (
                    "existing_new_taxi_score_before_asc"
                ),
            }
        ),
        on=["person_id", "unrouted_leg_sequence"],
        how="left",
        validate="one_to_one",
    )

    impact["route_distance_difference_m"] = (
        impact["mapped_route_distance_m"]
        - impact["old_extracted_route_distance_m"]
    )
    impact["travel_time_difference_s"] = (
        impact["mapped_actual_travel_time_s"]
        - impact["old_extracted_actual_travel_time_s"]
    )
    impact["route_attributes_match"] = (
        impact["old_extracted_route_attributes_hash"]
        == impact["mapped_route_attributes_hash"]
    )
    impact["route_text_hash_match"] = (
        impact["old_extracted_route_text_hash"]
        == impact["mapped_route_text_hash"]
    )
    impact["route_distance_matches"] = np.isclose(
        impact["old_extracted_route_distance_m"],
        impact["mapped_route_distance_m"],
        rtol=0.0,
        atol=TOLERANCE,
        equal_nan=False,
    )
    impact["travel_time_matches"] = np.isclose(
        impact["old_extracted_actual_travel_time_s"],
        impact["mapped_actual_travel_time_s"],
        rtol=0.0,
        atol=TOLERANCE,
        equal_nan=False,
    )
    impact["old_extraction_reproduces_existing_distance"] = np.isclose(
        impact["old_extracted_route_distance_m"],
        impact["existing_route_distance_m"],
        rtol=0.0,
        atol=TOLERANCE,
        equal_nan=False,
    )
    impact["old_extraction_reproduces_existing_travel_time"] = np.isclose(
        impact["old_extracted_actual_travel_time_s"],
        impact["existing_actual_travel_time_s"],
        rtol=0.0,
        atol=TOLERANCE,
        equal_nan=False,
    )

    impact["corrected_distance_only_fare_hkd"] = corrected_fares(
        impact["taxi_type"],
        impact["mapped_route_distance_m"],
        fare_rules,
    )
    impact["fare_difference_hkd"] = (
        impact["corrected_distance_only_fare_hkd"]
        - impact["existing_distance_only_fare_hkd"]
    )
    impact["absolute_fare_difference_hkd"] = impact[
        "fare_difference_hkd"
    ].abs()
    impact["fare_matches"] = np.isclose(
        impact["corrected_distance_only_fare_hkd"],
        impact["existing_distance_only_fare_hkd"],
        rtol=0.0,
        atol=TOLERANCE,
        equal_nan=False,
    )
    impact["corrected_distance_band"] = impact[
        "mapped_route_distance_m"
    ].map(distance_band)
    corrected_hours = (
        impact["mapped_actual_travel_time_s"] / 3600.0
    )
    impact["corrected_old_ride_score"] = (
        -1.5
        - 6.0 * corrected_hours
        - 0.0015 * impact["mapped_route_distance_m"]
    )
    impact["corrected_new_taxi_score_before_asc"] = (
        -6.0 * corrected_hours
        - 0.05 * impact["corrected_distance_only_fare_hkd"]
    )
    impact["corrected_asc_equivalent"] = (
        impact["corrected_old_ride_score"]
        - impact["corrected_new_taxi_score_before_asc"]
    )
    impact["asc_equivalent_difference"] = (
        impact["corrected_asc_equivalent"]
        - impact["existing_asc_equivalent"]
    )
    impact["comparison_status"] = np.where(
        impact["mapping_status"].eq("mapped_unique_ride_leg"),
        np.where(
            impact["route_distance_matches"]
            & impact["travel_time_matches"]
            & impact["fare_matches"],
            "existing_extraction_matches_correct_mapping",
            "existing_extraction_differs_from_correct_mapping",
        ),
        "corrected_values_unavailable_due_to_mapping_status",
    )

    inventory = activity_inventory(unrouted, routed)
    structure = structure_summary(unrouted, routed)
    inventory.to_csv(
        outputs["routed_activity_type_inventory.csv"],
        index=False,
        encoding="utf-8-sig",
    )
    structure.to_csv(
        outputs["routed_plan_structure_summary.csv"],
        index=False,
        encoding="utf-8-sig",
    )
    mapping.to_parquet(
        outputs[
            "taxi_unrouted_to_routed_main_leg_mapping.parquet"
        ],
        index=False,
    )
    impact.to_csv(
        outputs["taxi_existing_route_extraction_impact.csv"],
        index=False,
        encoding="utf-8-sig",
    )
    write_json(
        outputs["taxi_routed_main_leg_mapping_validation.json"],
        {"status": "pending_audit_completion"},
    )

    input_hashes_after = hash_paths(inputs)
    worktree_status_after = git_status(
        worktree_repository, WORKTREE_PROTECTED_PATHS
    )
    external_status_after = git_status(
        external_repository, EXTERNAL_PROTECTED_PATHS
    )
    repository_changes = changed_paths(worktree_repository)
    unexpected_changes = sorted(
        set(repository_changes) - ALLOWED_REPOSITORY_PATHS
    )

    current_plan_hashes = {
        name: input_hashes_before[name]
        for name in EXPECTED_PLAN_HASHES
    }
    plan_hash_references = {
        "expected": EXPECTED_PLAN_HASHES,
        "allocation_validation": {
            name: allocation_summary["plans_integrity"]["hash_before"][
                name
            ]
            for name in EXPECTED_PLAN_HASHES
        },
        "fare_validation": {
            name: fare_validation["hash_before"][name]
            for name in EXPECTED_PLAN_HASHES
        },
        "bridge_validation": {
            name: bridge_validation["protected_matsim_hashes_before"][
                name
            ]
            for name in EXPECTED_PLAN_HASHES
        },
    }
    plan_hashes_match_all_references = all(
        referenced == current_plan_hashes
        for referenced in plan_hash_references.values()
    )
    fare_hash_matches_bridge_validation = bool(
        input_hashes_before[
            "taxi_leg_fare_estimates_base.parquet"
        ]
        == bridge_validation["input_hashes_before"][
            "taxi_leg_fare_estimates_base.parquet"
        ]
    )
    bridge_audit_hash_matches_validation = bool(
        input_hashes_before[
            "old_ride_vs_new_taxi_leg_audit.parquet"
        ]
        == bridge_validation["output_hashes"][
            "old_ride_vs_new_taxi_leg_audit.parquet"
        ]
    )
    hashes_match = bool(
        plan_hashes_match_all_references
        and fare_hash_matches_bridge_validation
        and bridge_audit_hash_matches_validation
    )

    mapping_counts = mapping["mapping_status"].value_counts().to_dict()
    unique_main_trips = int(
        mapping["main_activity_sequence_matches"].fillna(False).sum()
    )
    unique_ride_legs = int(
        mapping["mapping_status"].eq("mapped_unique_ride_leg").sum()
    )
    ambiguous_mappings = int(
        mapping["mapping_status"]
        .isin(
            [
                "multiple_ride_legs_in_mapped_trip",
                "ambiguous_stage_structure",
                "main_activity_signature_mismatch",
            ]
        )
        .sum()
    )
    missing_mappings = int(
        mapping["mapping_status"]
        .isin(
            [
                "no_corresponding_main_trip",
                "no_ride_leg_in_mapped_trip",
            ]
        )
        .sum()
    )
    mapping_rule_valid = bool(
        unique_ride_legs == EXPECTED_TAXI_LEGS
        and ambiguous_mappings == 0
        and missing_mappings == 0
    )

    old_raw_match_count = int(
        impact["raw_sequence_matches"].sum()
    )
    old_raw_mismatch_count = int(
        len(impact) - old_raw_match_count
    )
    distance_match_count = int(
        impact["route_distance_matches"].sum()
    )
    travel_time_match_count = int(
        impact["travel_time_matches"].sum()
    )
    fare_match_count = int(impact["fare_matches"].sum())
    existing_fare_route_extraction_valid = bool(
        mapping_rule_valid
        and old_raw_mismatch_count == 0
        and distance_match_count == EXPECTED_TAXI_LEGS
        and travel_time_match_count == EXPECTED_TAXI_LEGS
        and fare_match_count == EXPECTED_TAXI_LEGS
    )
    bridge_difference = impact["asc_equivalent_difference"]
    existing_bridge_inputs_valid = bool(
        mapping_rule_valid
        and fare_match_count == EXPECTED_TAXI_LEGS
        and np.isclose(
            bridge_difference,
            0.0,
            rtol=0.0,
            atol=TOLERANCE,
            equal_nan=False,
        ).all()
    )
    downstream_action_required = bool(
        not existing_fare_route_extraction_valid
        or not existing_bridge_inputs_valid
    )

    outputs_exist = all(
        path.is_file() and path.stat().st_size > 0
        for path in outputs.values()
    )
    taxi_key_sets_match = bool(
        len(fare_keys) == EXPECTED_TAXI_LEGS
        and fare_keys == bridge_keys
        and fare_keys == combined_classification_keys
        and len(allocated_keys) == EXPECTED_ALLOCATED_TAXI
        and len(explicit_keys) == EXPECTED_EXPLICIT_TAXI
        and not (allocated_keys & explicit_keys)
    )
    person_sets_match = bool(
        routed["missing_person_ids_count"] == 0
        and routed["unexpected_person_ids_count"] == 0
    )
    main_activity_sequences_match = bool(
        routed["main_sequence_mismatch_persons"] == 0
        and routed["ambiguous_stage_persons"] == 0
        and not routed["unknown_routed_only_activity_types"]
    )
    plans_parsed = bool(
        unrouted["counts"]["persons"] > 0
        and routed["counts"]["persons"] > 0
        and unrouted["counts"]["legs"] > 0
        and routed["counts"]["legs"] > 0
    )
    audit_execution_checks = {
        "inputs_exist": True,
        "hashes_match": hashes_match,
        "source_files_unchanged": (
            input_hashes_before == input_hashes_after
        ),
        "plans_parsed": plans_parsed,
        "person_sets_match": person_sets_match,
        "main_activity_sequences_match_after_stage_removal": (
            main_activity_sequences_match
        ),
        "taxi_key_sets_match": taxi_key_sets_match,
        "selected_plans_determinate": bool(
            unrouted["selected_plan_unresolved_persons"] == 0
            and routed["selected_plan_unresolved_persons"] == 0
        ),
        "unrouted_main_trip_index_equals_leg_sequence": bool(
            unrouted["invalid_unrouted_alternation_persons"] == 0
        ),
        "outputs_exist": outputs_exist,
        "protected_git_status_empty_before_after": bool(
            worktree_status_before == ""
            and worktree_status_after == ""
            and external_status_before == ""
            and external_status_after == ""
        ),
        "only_allowed_paths_changed": len(unexpected_changes) == 0,
    }
    audit_execution_succeeded = all(
        audit_execution_checks.values()
    )
    failed_execution_checks = [
        key
        for key, passed in audit_execution_checks.items()
        if not passed
    ]

    if not audit_execution_succeeded:
        status = "mapping_unresolved"
    elif not mapping_rule_valid:
        status = "mapping_unresolved"
    elif downstream_action_required:
        status = "audit_completed_with_fare_rebuild_blocker"
    else:
        status = "audit_completed"

    fare_change_count = int((~impact["fare_matches"]).sum())
    corrected_available_count = int(
        impact["corrected_distance_only_fare_hkd"].notna().sum()
    )
    old_mode_counts = (
        impact["old_extracted_routed_mode"]
        .value_counts(dropna=False)
        .to_dict()
    )
    mapped_mode_counts = (
        impact["mapped_routed_mode"]
        .value_counts(dropna=False)
        .to_dict()
    )
    impact_summary = {
        "raw_sequence_matches": old_raw_match_count,
        "raw_sequence_differs": old_raw_mismatch_count,
        "old_extracted_routed_mode_counts": old_mode_counts,
        "correct_mapped_mode_counts": mapped_mode_counts,
        "old_routed_mode_ride_count": int(
            impact["old_extracted_routed_mode"].eq("ride").sum()
        ),
        "route_distance_match_count": distance_match_count,
        "route_distance_match_share": (
            distance_match_count / EXPECTED_TAXI_LEGS
        ),
        "route_distance_absolute_difference_m": numeric_distribution(
            impact["route_distance_difference_m"].abs()
        ),
        "travel_time_match_count": travel_time_match_count,
        "travel_time_match_share": (
            travel_time_match_count / EXPECTED_TAXI_LEGS
        ),
        "travel_time_absolute_difference_s": numeric_distribution(
            impact["travel_time_difference_s"].abs()
        ),
        "route_attributes_match_count": int(
            impact["route_attributes_match"].sum()
        ),
        "route_text_hash_match_count": int(
            impact["route_text_hash_match"].sum()
        ),
        "old_extraction_reproduces_existing_distance_count": int(
            impact[
                "old_extraction_reproduces_existing_distance"
            ].sum()
        ),
        "old_extraction_reproduces_existing_travel_time_count": int(
            impact[
                "old_extraction_reproduces_existing_travel_time"
            ].sum()
        ),
        "by_classification_source": grouped_impact(
            impact, "classification_source"
        ),
        "by_taxi_type": grouped_impact(impact, "taxi_type"),
        "by_main_trip_index": grouped_impact(
            impact, "main_trip_index"
        ),
        "by_preceding_stage_activity_count": grouped_impact(
            impact, "preceding_stage_activity_count"
        ),
    }
    fare_impact = {
        "corrected_fare_available_count": corrected_available_count,
        "fare_match_count": fare_match_count,
        "fare_change_count": fare_change_count,
        "fare_difference_hkd": numeric_distribution(
            impact["fare_difference_hkd"]
        ),
        "absolute_fare_difference_hkd": numeric_distribution(
            impact["absolute_fare_difference_hkd"]
        ),
        "by_taxi_type": grouped_impact(impact, "taxi_type"),
        "by_corrected_distance_band": grouped_impact(
            impact, "corrected_distance_band"
        ),
        "by_classification_source": grouped_impact(
            impact, "classification_source"
        ),
        "unresolved_taxi_rule": (
            "Existing v1 rule reproduced exactly: unresolved taxi types "
            "use the urban_taxi meter-distance rule while retaining their "
            "unresolved classification."
        ),
    }
    corrected_asc_distribution = numeric_distribution(
        impact["corrected_asc_equivalent"]
    )
    existing_asc_distribution = numeric_distribution(
        impact["existing_asc_equivalent"]
    )
    bridge_impact = {
        "existing_asc_equivalent": existing_asc_distribution,
        "corrected_asc_equivalent": corrected_asc_distribution,
        "corrected_minus_existing_asc_equivalent": (
            numeric_distribution(impact["asc_equivalent_difference"])
        ),
        "impact_diagnostic_only": True,
        "existing_candidates_unchanged": [-12, -9, -6],
    }

    validation = {
        "scenario_family": (
            "hong_kong_taxi_routed_main_leg_mapping_audit_v1"
        ),
        "status": status,
        "audit_execution_succeeded": audit_execution_succeeded,
        "failed_audit_execution_checks": failed_execution_checks,
        "audit_execution_checks": audit_execution_checks,
        "roots": {
            "worktree_root": ROOT.as_posix(),
            "worktree_git_repository_root": (
                worktree_repository.as_posix()
            ),
            "explicit_matsim_root": matsim_root.as_posix(),
            "matsim_root_was_explicit": True,
            "external_git_repository_root": (
                external_repository.as_posix()
            ),
        },
        "input_paths": {
            name: path.as_posix() for name, path in inputs.items()
        },
        "input_hashes_before": input_hashes_before,
        "input_hashes_after": input_hashes_after,
        "input_hashes_unchanged": (
            input_hashes_before == input_hashes_after
        ),
        "plan_hash_references": plan_hash_references,
        "hash_consistency": {
            "plan_hashes_match_all_references": (
                plan_hashes_match_all_references
            ),
            "fare_hash_matches_bridge_validation": (
                fare_hash_matches_bridge_validation
            ),
            "bridge_audit_hash_matches_validation": (
                bridge_audit_hash_matches_validation
            ),
        },
        "plan_structure": {
            "unrouted": {
                "counts": dict(unrouted["counts"]),
                "mode_counts": dict(unrouted["mode_counts"]),
                "activity_type_counts": dict(
                    unrouted["activity_type_counts"]
                ),
                "route_type_counts": dict(
                    unrouted["route_type_counts"]
                ),
                "plan_count_distribution": {
                    str(key): value
                    for key, value in unrouted[
                        "plan_count_distribution"
                    ].items()
                },
                "multi_plan_persons": unrouted[
                    "multi_plan_persons"
                ],
                "person_order_sha256": unrouted[
                    "person_order_sha256"
                ],
            },
            "routed": {
                "counts": dict(routed["counts"]),
                "mode_counts": dict(routed["mode_counts"]),
                "activity_type_counts": dict(
                    routed["activity_type_counts"]
                ),
                "route_type_counts": dict(
                    routed["route_type_counts"]
                ),
                "plan_count_distribution": {
                    str(key): value
                    for key, value in routed[
                        "plan_count_distribution"
                    ].items()
                },
                "multi_plan_persons": routed[
                    "multi_plan_persons"
                ],
                "person_order_sha256": routed[
                    "person_order_sha256"
                ],
            },
            "person_id_order_matches": bool(
                unrouted["person_order_sha256"]
                == routed["person_order_sha256"]
            ),
            "person_sets_match": person_sets_match,
            "stage_activity_types": routed["accepted_stage_types"],
            "unknown_routed_only_activity_types": routed[
                "unknown_routed_only_activity_types"
            ],
            "stage_activity_count": int(
                sum(
                    routed["activity_type_counts"][activity_type]
                    for activity_type in routed[
                        "accepted_stage_types"
                    ]
                )
            ),
            "main_sequence_mismatch_persons": routed[
                "main_sequence_mismatch_persons"
            ],
            "ambiguous_stage_persons": routed[
                "ambiguous_stage_persons"
            ],
        },
        "taxi_key_set_crosscheck": {
            "fare_keys": len(fare_keys),
            "bridge_keys": len(bridge_keys),
            "allocated_base_taxi_keys": len(allocated_keys),
            "explicit_v1_taxi_keys": len(explicit_keys),
            "allocation_explicit_overlap": len(
                allocated_keys & explicit_keys
            ),
            "fare_bridge_symmetric_difference": len(
                fare_keys ^ bridge_keys
            ),
            "fare_vs_allocation_plus_explicit_symmetric_difference": (
                len(fare_keys ^ combined_classification_keys)
            ),
            "v2_manifest_target_rows": len(manifest_target),
            "v2_manifest_target_mode_counts": (
                manifest_target["mode"].value_counts().to_dict()
            ),
        },
        "mapping_result": {
            "selected_taxi_keys": len(fare_keys),
            "uniquely_mapped_main_trips": unique_main_trips,
            "uniquely_mapped_ride_legs": unique_ride_legs,
            "ambiguous_mappings": ambiguous_mappings,
            "missing_mappings": missing_mappings,
            "mapping_status_counts": mapping_counts,
            "mapping_rule_valid": mapping_rule_valid,
        },
        "existing_route_extraction_result": {
            "old_raw_sequence_correct_count": old_raw_match_count,
            "old_raw_sequence_incorrect_count": (
                old_raw_mismatch_count
            ),
            "old_routed_mode_ride_count": int(
                impact["old_extracted_routed_mode"].eq("ride").sum()
            ),
            "old_routed_mode_counts": old_mode_counts,
            "correct_mapped_mode_counts": mapped_mode_counts,
            "route_distance_match_count": distance_match_count,
            "travel_time_match_count": travel_time_match_count,
            "fare_match_count": fare_match_count,
            "existing_fare_route_extraction_valid": (
                existing_fare_route_extraction_valid
            ),
            "existing_bridge_inputs_valid": (
                existing_bridge_inputs_valid
            ),
            "downstream_action_required": (
                downstream_action_required
            ),
            "recommended_downstream_action": (
                "Rebuild fare and utility-bridge audits from the validated "
                "main-trip mapping before plans conversion."
                if downstream_action_required
                else "Main-trip mapping audit does not block plans conversion."
            ),
        },
        "route_extraction_impact": impact_summary,
        "fare_impact": fare_impact,
        "bridge_impact": bridge_impact,
        "git_protection": {
            "worktree_protected_status_before": (
                worktree_status_before
            ),
            "worktree_protected_status_after": (
                worktree_status_after
            ),
            "external_protected_status_before": (
                external_status_before
            ),
            "external_protected_status_after": (
                external_status_after
            ),
            "repository_changed_paths": repository_changes,
            "allowed_repository_paths": sorted(
                ALLOWED_REPOSITORY_PATHS
            ),
            "unexpected_repository_changes": unexpected_changes,
        },
        "output_hashes": {
            name: sha256(path)
            for name, path in outputs.items()
            if name
            != "taxi_routed_main_leg_mapping_validation.json"
        },
        "non_modification_statement": (
            "No existing plans, fare, bridge, config, network, Java, or "
            "simulation output was modified. No MATSim routing, QSim, "
            "Controler, smoke test, taxi mode creation, plan conversion, "
            "fare rebuild, or bridge rebuild was run."
        ),
        "outputs": list(outputs),
    }
    write_json(
        outputs["taxi_routed_main_leg_mapping_validation.json"],
        validation,
    )

    print(
        json.dumps(
            {
                "status": status,
                "audit_execution_succeeded": (
                    audit_execution_succeeded
                ),
                "failed_audit_execution_checks": (
                    failed_execution_checks
                ),
                "stage_activity_types": routed[
                    "accepted_stage_types"
                ],
                "stage_activity_count": validation[
                    "plan_structure"
                ]["stage_activity_count"],
                "mapping_result": validation["mapping_result"],
                "existing_route_extraction_result": validation[
                    "existing_route_extraction_result"
                ],
                "unexpected_repository_changes": (
                    unexpected_changes
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if not audit_execution_succeeded:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
