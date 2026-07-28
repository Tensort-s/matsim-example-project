#!/usr/bin/env python3
"""Create the Hong Kong base taxi behavioural-pilot routed plans.

The source routed plans are streamed into a new gzip XML file. Exactly the
validated base taxi target legs are changed from ``ride`` to ``taxi`` and
receive distance-only fare metadata. Existing plans are never overwritten and
MATSim is not run.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import re
import subprocess
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from lxml import etree as ET

from audit_hong_kong_taxi_routed_main_leg_mapping import (
    activity_signature_text,
    choose_selected_plan,
    direct_children,
    local_name,
    parse_time_s,
    route_details,
)


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT_DIR = (
    ROOT / "data/taxi/hongkong/processed/taxi_plans_conversion_v1"
)

EXPECTED_BRANCH = "feature/hk-taxi-behavioral-pilot-v1"
EXPECTED_HEAD = "cc1a71dd8d27fd524293e43dde6e58046fadb322"
EXPECTED_BASELINE = "a3d6445cfd79a74b6fd6bd01e547d7df8055a64d"

EXPECTED_HASHES = {
    "plans_routed_5pct_v2.xml.gz": (
        "c73ee48e792e7aebd55b7a2691664ae7f3f4f27d307aef2a6bf58263b3aaafea"
    ),
    "plans_unrouted_5pct_v2.xml.gz": (
        "5b463376f89bf607c0980d2e84e096f6424c76b6dc5697669aa1f9880de6a0f7"
    ),
    "taxi_unrouted_to_routed_main_leg_mapping.parquet": (
        "760c2e613f35f03da132f3168770a6b2cac6c2edbc285775b1ce9c2ef7237ac5"
    ),
    "taxi_leg_fare_estimates_base.parquet": (
        "8a90cc100a911efbc893552447fc1089bf3098bc7ce45df9fe3e4e95a6452b86"
    ),
}

EXPECTED_TARGET = 37_286
EXPECTED_EXPLICIT = 4_614
EXPECTED_ALLOCATED = 32_672
EXPECTED_NON_TAXI_RIDE = {
    "private_car_passenger": 3_564,
    "school_bus": 9_626,
    "base_other_ride": 5_884,
}
EXPECTED_COUNTS = {
    "persons": 385_820,
    "plans": 385_820,
    "activities": 1_264_870,
    "legs": 879_050,
    "routes": 879_050,
}
EXPECTED_MODES_BEFORE = {
    "car": 67_718,
    "pt": 557_104,
    "ride": 56_360,
    "taxi": 0,
    "walk": 197_868,
}
EXPECTED_MODES_AFTER = {
    "car": 67_718,
    "pt": 557_104,
    "ride": 19_074,
    "taxi": 37_286,
    "walk": 197_868,
}

TAXI_ATTRIBUTES = {
    "hkTaxiFareBaselineHkd": "java.lang.Double",
    "hkTaxiType": "java.lang.String",
    "hkTaxiFareScope": "java.lang.String",
    "hkTaxiFareModelVersion": "java.lang.String",
    "hkTaxiClassificationSource": "java.lang.String",
    "hkTaxiMainTripIndex": "java.lang.Integer",
}
STATIC_TAXI_VALUES = {
    "hkTaxiFareScope": "distance_only_v1",
    "hkTaxiFareModelVersion": "hong_kong_taxi_fare_model_v1",
}

ALLOWED_REPOSITORY_PATHS = {
    (
        "scripts/hong_kong_single_city/demand_generation/"
        "convert_hong_kong_taxi_behavioral_plans.py"
    ),
    (
        "data/taxi/hongkong/processed/taxi_plans_conversion_v1/"
        "taxi_plans_conversion_leg_audit.csv"
    ),
    (
        "data/taxi/hongkong/processed/taxi_plans_conversion_v1/"
        "taxi_plans_conversion_mode_summary.csv"
    ),
    (
        "data/taxi/hongkong/processed/taxi_plans_conversion_v1/"
        "taxi_plans_conversion_validation.json"
    ),
    "docs/HONG_KONG_TAXI_PLANS_CONVERSION.md",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--matsim-root",
        type=Path,
        required=True,
        help="Explicit read-only MATSim project root.",
    )
    parser.add_argument(
        "--output-plans",
        type=Path,
        required=True,
        help="Explicit new output plans.xml.gz path; it must not exist.",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args()


def fail(message: str) -> None:
    raise RuntimeError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def git_text(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


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


def changed_paths() -> list[str]:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(ROOT),
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


def repository_root(path: Path) -> Path:
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return Path(result.stdout.strip()).resolve()


def source_paths(matsim_root: Path) -> dict[str, Path]:
    plans_dir = (
        matsim_root
        / "data/matsim_agents/hongkong/"
        "typical_weekday_5pct_v2_activity_modechoice"
    )
    mapping_dir = (
        ROOT
        / "data/taxi/hongkong/processed/"
        "taxi_routed_main_leg_mapping_audit_v1"
    )
    fare_dir = (
        ROOT / "data/taxi/hongkong/processed/taxi_fare_model_v1"
    )
    allocation_dir = (
        ROOT
        / "data/taxi/hongkong/processed/"
        "taxi_initial_plan_allocation_v1"
    )
    bridge_dir = (
        ROOT / "data/taxi/hongkong/processed/taxi_utility_bridge_v1"
    )
    return {
        "plans_routed_5pct_v2.xml.gz": (
            plans_dir / "plans_routed_5pct_v2.xml.gz"
        ),
        "plans_unrouted_5pct_v2.xml.gz": (
            plans_dir / "plans_unrouted_5pct_v2.xml.gz"
        ),
        "taxi_unrouted_to_routed_main_leg_mapping.parquet": (
            mapping_dir
            / "taxi_unrouted_to_routed_main_leg_mapping.parquet"
        ),
        "taxi_routed_main_leg_mapping_validation.json": (
            mapping_dir / "taxi_routed_main_leg_mapping_validation.json"
        ),
        "taxi_leg_fare_estimates_base.parquet": (
            fare_dir / "taxi_leg_fare_estimates_base.parquet"
        ),
        "taxi_fare_model_validation.json": (
            fare_dir / "taxi_fare_model_validation.json"
        ),
        "taxi_candidate_leg_classification.csv": (
            allocation_dir / "taxi_candidate_leg_classification.csv"
        ),
        "taxi_allocation_summary.json": (
            allocation_dir / "taxi_allocation_summary.json"
        ),
        "old_ride_vs_new_taxi_leg_audit.parquet": (
            bridge_dir / "old_ride_vs_new_taxi_leg_audit.parquet"
        ),
        "taxi_utility_bridge_validation.json": (
            bridge_dir / "taxi_utility_bridge_validation.json"
        ),
    }


def output_paths(out_dir: Path) -> dict[str, Path]:
    return {
        "taxi_plans_conversion_leg_audit.csv": (
            out_dir / "taxi_plans_conversion_leg_audit.csv"
        ),
        "taxi_plans_conversion_mode_summary.csv": (
            out_dir / "taxi_plans_conversion_mode_summary.csv"
        ),
        "taxi_plans_conversion_validation.json": (
            out_dir / "taxi_plans_conversion_validation.json"
        ),
    }


def feed(
    hasher: Any,
    label: str,
    payload: Any,
) -> None:
    encoded = json.dumps(
        [label, payload],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    hasher.update(encoded)
    hasher.update(b"\n")


def attribute_rows(
    element: ET._Element,
    excluded_names: set[str] | None = None,
) -> list[list[dict[str, str]]]:
    excluded = excluded_names or set()
    blocks: list[list[dict[str, str]]] = []
    for block in direct_children(element, "attributes"):
        rows: list[dict[str, str]] = []
        for attribute in direct_children(block, "attribute"):
            name = attribute.get("name", "")
            if name in excluded:
                continue
            rows.append(
                {
                    "name": name,
                    "class": attribute.get("class", ""),
                    "value": attribute.text or "",
                }
            )
        blocks.append(rows)
    return blocks


def named_attributes(element: ET._Element) -> dict[str, list[dict[str, str]]]:
    values: dict[str, list[dict[str, str]]] = defaultdict(list)
    for block in direct_children(element, "attributes"):
        for attribute in direct_children(block, "attribute"):
            values[attribute.get("name", "")].append(
                {
                    "class": attribute.get("class", ""),
                    "value": attribute.text or "",
                }
            )
    return dict(values)


def blank_scan_state() -> dict[str, Any]:
    return {
        "counts": Counter(),
        "mode_counts": Counter(),
        "person_order_hasher": hashlib.sha256(),
        "activity_hasher": hashlib.sha256(),
        "route_attributes_hasher": hashlib.sha256(),
        "route_text_hasher": hashlib.sha256(),
        "normalized_structure_hasher": hashlib.sha256(),
        "selected_plan_unresolved_persons": 0,
        "target_legs": {},
        "root_tag": "",
        "root_attributes": {},
    }


def scan_root_child(
    element: ET._Element,
    state: dict[str, Any],
) -> None:
    payload = {
        "tag": local_name(element),
        "attributes": dict(sorted(element.attrib.items())),
        "attribute_blocks": attribute_rows(element),
    }
    feed(state["normalized_structure_hasher"], "root_child", payload)


def scan_person(
    person: ET._Element,
    state: dict[str, Any],
    target_lookup: dict[tuple[str, int], dict[str, Any]],
    output_scan: bool,
) -> None:
    person_id = person.get("id", "")
    state["counts"]["persons"] += 1
    state["person_order_hasher"].update(
        person_id.encode("utf-8") + b"\n"
    )
    feed(
        state["normalized_structure_hasher"],
        "person",
        {
            "attributes": dict(sorted(person.attrib.items())),
            "attribute_blocks": attribute_rows(person),
        },
    )

    selected_plan, _, determinate = choose_selected_plan(person)
    if not determinate or selected_plan is None:
        state["selected_plan_unresolved_persons"] += 1

    for plan_index, plan in enumerate(direct_children(person, "plan")):
        state["counts"]["plans"] += 1
        feed(
            state["normalized_structure_hasher"],
            "plan",
            {
                "index": plan_index,
                "attributes": dict(sorted(plan.attrib.items())),
                "attribute_blocks": attribute_rows(plan),
            },
        )
        raw_leg_sequence = -1
        for element in plan:
            tag = local_name(element)
            if tag == "activity":
                state["counts"]["activities"] += 1
                payload = {
                    "attributes": dict(sorted(element.attrib.items())),
                    "attribute_blocks": attribute_rows(element),
                }
                feed(state["activity_hasher"], "activity", payload)
                feed(
                    state["normalized_structure_hasher"],
                    "activity",
                    payload,
                )
                continue
            if tag != "leg":
                continue

            raw_leg_sequence += 1
            state["counts"]["legs"] += 1
            actual_mode = element.get("mode", "")
            state["mode_counts"][actual_mode] += 1
            target_key = (person_id, raw_leg_sequence)
            is_target = (
                plan is selected_plan and target_key in target_lookup
            )

            leg_attributes = dict(sorted(element.attrib.items()))
            excluded: set[str] = set()
            if is_target and output_scan:
                leg_attributes["mode"] = "ride"
                excluded = set(TAXI_ATTRIBUTES)
            leg_payload = {
                "attributes": leg_attributes,
                "attribute_blocks": attribute_rows(element, excluded),
            }
            feed(
                state["normalized_structure_hasher"],
                "leg",
                leg_payload,
            )

            routes = direct_children(element, "route")
            for route in routes:
                state["counts"]["routes"] += 1
                route_attributes = dict(sorted(route.attrib.items()))
                route_text = route.text or ""
                feed(
                    state["route_attributes_hasher"],
                    "route_attributes",
                    route_attributes,
                )
                feed(
                    state["route_text_hasher"],
                    "route_text",
                    route_text,
                )
                feed(
                    state["normalized_structure_hasher"],
                    "route",
                    {
                        "attributes": route_attributes,
                        "text": route_text,
                    },
                )

            if is_target:
                details = route_details(element)
                state["target_legs"][target_key] = {
                    "mode": actual_mode,
                    "route_count": details["route_count"],
                    "route_distance_m": details["route_distance_m"],
                    "actual_travel_time_s": details[
                        "actual_travel_time_s"
                    ],
                    "route_attributes_hash": details[
                        "route_attributes_hash"
                    ],
                    "route_text_hash": details["route_text_hash"],
                    "named_attributes": named_attributes(element),
                }


def finalize_scan(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "counts": dict(sorted(state["counts"].items())),
        "mode_counts": dict(sorted(state["mode_counts"].items())),
        "person_order_sha256": state["person_order_hasher"].hexdigest(),
        "activity_signatures_sha256": (
            state["activity_hasher"].hexdigest()
        ),
        "route_attributes_sha256": (
            state["route_attributes_hasher"].hexdigest()
        ),
        "route_text_sha256": state["route_text_hasher"].hexdigest(),
        "normalized_structure_sha256": (
            state["normalized_structure_hasher"].hexdigest()
        ),
        "selected_plan_unresolved_persons": (
            state["selected_plan_unresolved_persons"]
        ),
        "root_tag": state["root_tag"],
        "root_attributes": state["root_attributes"],
        "target_legs": state["target_legs"],
    }


def clear_top_level(element: ET._Element) -> None:
    element.clear()
    parent = element.getparent()
    if parent is not None:
        while element.getprevious() is not None:
            del parent[0]


def scan_plans(
    path: Path,
    target_lookup: dict[tuple[str, int], dict[str, Any]],
    output_scan: bool,
) -> dict[str, Any]:
    state = blank_scan_state()
    with gzip.open(path, "rb") as handle:
        context = ET.iterparse(
            handle,
            events=("start", "end"),
            huge_tree=True,
        )
        event, root = next(context)
        if event != "start":
            fail("Plans XML did not begin with a root start event.")
        state["root_tag"] = local_name(root)
        state["root_attributes"] = dict(sorted(root.attrib.items()))
        feed(
            state["normalized_structure_hasher"],
            "root",
            {
                "tag": state["root_tag"],
                "attributes": state["root_attributes"],
            },
        )
        for event, element in context:
            if event != "end" or element.getparent() is not root:
                continue
            if local_name(element) == "person":
                scan_person(
                    element,
                    state,
                    target_lookup,
                    output_scan,
                )
            else:
                scan_root_child(element, state)
            clear_top_level(element)
    return finalize_scan(state)


def validate_unrouted_targets(
    path: Path,
    targets_by_person: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    seen: set[tuple[str, int]] = set()
    errors: Counter[str] = Counter()
    parsed_persons = 0
    with gzip.open(path, "rb") as handle:
        context = ET.iterparse(
            handle,
            events=("end",),
            tag="person",
            huge_tree=True,
        )
        for _, person in context:
            parsed_persons += 1
            person_id = person.get("id", "")
            records = targets_by_person.get(person_id)
            if records:
                plan, _, determinate = choose_selected_plan(person)
                if not determinate or plan is None:
                    errors["selected_plan_unresolved"] += len(records)
                else:
                    direct = [
                        element
                        for element in plan
                        if local_name(element) in {"activity", "leg"}
                    ]
                    activities = [
                        element
                        for element in direct
                        if local_name(element) == "activity"
                    ]
                    legs = [
                        element
                        for element in direct
                        if local_name(element) == "leg"
                    ]
                    alternating = (
                        len(direct) % 2 == 1
                        and all(
                            local_name(element)
                            == (
                                "activity"
                                if index % 2 == 0
                                else "leg"
                            )
                            for index, element in enumerate(direct)
                        )
                    )
                    for record in records:
                        index = int(record["main_trip_index"])
                        key = (
                            person_id,
                            int(record["unrouted_leg_sequence"]),
                        )
                        if not alternating:
                            errors["not_strictly_alternating"] += 1
                            continue
                        if (
                            index < 0
                            or index >= len(legs)
                            or index + 1 >= len(activities)
                        ):
                            errors["main_trip_index_out_of_range"] += 1
                            continue
                        if (
                            int(record["unrouted_leg_sequence"])
                            != index
                        ):
                            errors["unrouted_sequence_index_mismatch"] += 1
                        if legs[index].get("mode", "") != "ride":
                            errors["unrouted_target_not_ride"] += 1
                        if (
                            activity_signature_text(activities[index])
                            != record["origin_activity_signature"]
                        ):
                            errors["origin_signature_mismatch"] += 1
                        if (
                            activity_signature_text(activities[index + 1])
                            != record[
                                "destination_activity_signature"
                            ]
                        ):
                            errors["destination_signature_mismatch"] += 1
                        seen.add(key)
            clear_top_level(person)
    return {
        "parsed_persons": parsed_persons,
        "validated_target_keys": len(seen),
        "errors": dict(sorted(errors.items())),
        "error_count": int(sum(errors.values())),
    }


def routed_trip_groups(plan: ET._Element) -> list[dict[str, Any]]:
    direct = [
        element
        for element in plan
        if local_name(element) in {"activity", "leg"}
    ]
    groups: list[dict[str, Any]] = []
    current_origin: ET._Element | None = None
    current_legs: list[tuple[int, ET._Element]] = []
    raw_leg_sequence = -1
    for element in direct:
        if local_name(element) == "leg":
            raw_leg_sequence += 1
            current_legs.append((raw_leg_sequence, element))
            continue
        if element.get("type", "").endswith(" interaction"):
            continue
        if current_origin is None:
            current_origin = element
            continue
        groups.append(
            {
                "origin_signature": (
                    activity_signature_text(current_origin)
                ),
                "destination_signature": (
                    activity_signature_text(element)
                ),
                "origin_type": current_origin.get("type", ""),
                "destination_type": element.get("type", ""),
                "legs": current_legs,
            }
        )
        current_origin = element
        current_legs = []
    return groups


def fare_text(value: float) -> str:
    return repr(float(value))


def append_taxi_attributes(
    leg: ET._Element,
    record: dict[str, Any],
) -> None:
    existing = named_attributes(leg)
    conflicts = set(existing) & set(TAXI_ATTRIBUTES)
    if conflicts:
        fail(
            "Taxi attribute conflict on "
            f"{record['person_id']} main trip "
            f"{record['main_trip_index']}: {sorted(conflicts)}"
        )
    blocks = direct_children(leg, "attributes")
    if len(blocks) > 1:
        fail(
            "Target leg has multiple direct attributes blocks: "
            f"{record['person_id']} / {record['main_trip_index']}"
        )
    if blocks:
        block = blocks[0]
    else:
        block = ET.Element("attributes")
        leg.insert(0, block)

    values = {
        "hkTaxiFareBaselineHkd": fare_text(
            record["total_fare_distance_only_hkd"]
        ),
        "hkTaxiType": str(record["taxi_type"]),
        "hkTaxiFareScope": STATIC_TAXI_VALUES["hkTaxiFareScope"],
        "hkTaxiFareModelVersion": STATIC_TAXI_VALUES[
            "hkTaxiFareModelVersion"
        ],
        "hkTaxiClassificationSource": str(
            record["classification_source"]
        ),
        "hkTaxiMainTripIndex": str(int(record["main_trip_index"])),
    }
    for name in TAXI_ATTRIBUTES:
        attribute = ET.SubElement(
            block,
            "attribute",
            name=name,
            **{"class": TAXI_ATTRIBUTES[name]},
        )
        attribute.text = values[name]


def convert_person(
    person: ET._Element,
    records: list[dict[str, Any]],
    converted_keys: set[tuple[str, int]],
) -> None:
    person_id = person.get("id", "")
    plan, _, determinate = choose_selected_plan(person)
    if not determinate or plan is None:
        fail(f"Selected routed plan unresolved for target person {person_id}")
    groups = routed_trip_groups(plan)
    for record in records:
        main_index = int(record["main_trip_index"])
        raw_sequence = int(record["mapped_routed_raw_leg_sequence"])
        target_key = (person_id, raw_sequence)
        if main_index < 0 or main_index >= len(groups):
            fail(
                f"Mapped main trip missing for {person_id} / {main_index}"
            )
        group = groups[main_index]
        if (
            group["origin_signature"]
            != record["origin_activity_signature"]
        ):
            fail(
                f"Routed origin signature mismatch for "
                f"{person_id} / {main_index}"
            )
        if (
            group["destination_signature"]
            != record["destination_activity_signature"]
        ):
            fail(
                f"Routed destination signature mismatch for "
                f"{person_id} / {main_index}"
            )
        ride_legs = [
            (sequence, leg)
            for sequence, leg in group["legs"]
            if leg.get("mode", "") == "ride"
        ]
        if len(ride_legs) != 1:
            fail(
                f"Mapped routed trip does not contain exactly one ride leg: "
                f"{person_id} / {main_index} / {len(ride_legs)}"
            )
        actual_sequence, leg = ride_legs[0]
        if actual_sequence != raw_sequence:
            fail(
                f"Mapped raw sequence mismatch for {person_id} / "
                f"{main_index}: {actual_sequence} != {raw_sequence}"
            )
        if target_key in converted_keys:
            fail(f"Duplicate conversion target: {target_key}")
        append_taxi_attributes(leg, record)
        leg.set("mode", "taxi")
        converted_keys.add(target_key)


def source_doctype(path: Path) -> str:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        prefix = handle.read(2048)
    match = re.search(r"<!DOCTYPE\s+[^>]+>", prefix)
    if not match:
        fail("Source plans DOCTYPE was not found.")
    return match.group(0)


def transform_plans(
    source: Path,
    temporary_output: Path,
    targets_by_person: dict[str, list[dict[str, Any]]],
    target_lookup: dict[tuple[str, int], dict[str, Any]],
) -> tuple[dict[str, Any], set[tuple[str, int]]]:
    state = blank_scan_state()
    converted_keys: set[tuple[str, int]] = set()
    doctype = source_doctype(source)
    with source.open("rb") as source_raw:
        with gzip.GzipFile(fileobj=source_raw, mode="rb") as source_gzip:
            context = ET.iterparse(
                source_gzip,
                events=("start", "end"),
                huge_tree=True,
            )
            event, root = next(context)
            if event != "start":
                fail("Source plans XML root start event was not found.")
            state["root_tag"] = local_name(root)
            state["root_attributes"] = dict(sorted(root.attrib.items()))
            feed(
                state["normalized_structure_hasher"],
                "root",
                {
                    "tag": state["root_tag"],
                    "attributes": state["root_attributes"],
                },
            )
            with temporary_output.open("wb") as output_raw:
                with gzip.GzipFile(
                    fileobj=output_raw,
                    mode="wb",
                    compresslevel=6,
                    mtime=0,
                ) as output_gzip:
                    with ET.xmlfile(
                        output_gzip,
                        encoding="utf-8",
                    ) as writer:
                        writer.write_declaration()
                        writer.write_doctype(doctype)
                        with writer.element(root.tag, root.attrib):
                            for event, element in context:
                                if (
                                    event != "end"
                                    or element.getparent() is not root
                                ):
                                    continue
                                if local_name(element) == "person":
                                    person_id = element.get("id", "")
                                    scan_person(
                                        element,
                                        state,
                                        target_lookup,
                                        output_scan=False,
                                    )
                                    records = targets_by_person.get(person_id)
                                    if records:
                                        convert_person(
                                            element,
                                            records,
                                            converted_keys,
                                        )
                                else:
                                    scan_root_child(element, state)
                                writer.write(element)
                                clear_top_level(element)
    return finalize_scan(state), converted_keys


def exact_attribute_match(
    record: dict[str, Any],
    output_target: dict[str, Any],
) -> tuple[bool, float]:
    expected_values = {
        "hkTaxiFareBaselineHkd": fare_text(
            record["total_fare_distance_only_hkd"]
        ),
        "hkTaxiType": str(record["taxi_type"]),
        "hkTaxiFareScope": STATIC_TAXI_VALUES["hkTaxiFareScope"],
        "hkTaxiFareModelVersion": STATIC_TAXI_VALUES[
            "hkTaxiFareModelVersion"
        ],
        "hkTaxiClassificationSource": str(
            record["classification_source"]
        ),
        "hkTaxiMainTripIndex": str(int(record["main_trip_index"])),
    }
    named = output_target["named_attributes"]
    matches = True
    for name, class_name in TAXI_ATTRIBUTES.items():
        values = named.get(name, [])
        matches = bool(
            matches
            and len(values) == 1
            and values[0]["class"] == class_name
            and values[0]["value"] == expected_values[name]
        )
    written = float(
        named.get("hkTaxiFareBaselineHkd", [{"value": "nan"}])[0][
            "value"
        ]
    )
    return matches, written


def mode_counts_with_zeroes(values: dict[str, int]) -> dict[str, int]:
    modes = set(values) | {"car", "pt", "ride", "taxi", "walk"}
    return {mode: int(values.get(mode, 0)) for mode in sorted(modes)}


def distribution(values: pd.Series) -> dict[str, float]:
    return {
        "mean": float(values.mean()),
        "median": float(values.median()),
        "p10": float(values.quantile(0.10)),
        "p90": float(values.quantile(0.90)),
        "min": float(values.min()),
        "max": float(values.max()),
    }


def main() -> None:
    args = parse_args()
    matsim_root = args.matsim_root.resolve()
    output_plans = args.output_plans.resolve()
    out_dir = args.out_dir.resolve()
    inputs = source_paths(matsim_root)
    outputs = output_paths(out_dir)

    if git_text("branch", "--show-current") != EXPECTED_BRANCH:
        fail("Current branch does not match the required branch.")
    if git_text("rev-parse", "HEAD") != EXPECTED_HEAD:
        fail("Current HEAD does not match the required starting HEAD.")
    behind, ahead = [
        int(value)
        for value in git_text(
            "rev-list",
            "--left-right",
            "--count",
            f"{EXPECTED_BASELINE}...HEAD",
        ).split()
    ]
    if (ahead, behind) != (3, 0):
        fail(
            f"Baseline relation is ahead={ahead}, behind={behind}; "
            "expected ahead=3, behind=0."
        )
    if not matsim_root.is_dir():
        fail(f"Explicit MATSim root does not exist: {matsim_root}")
    missing = [
        str(path) for path in inputs.values() if not path.is_file()
    ]
    if missing:
        fail("Missing required inputs:\n" + "\n".join(missing))
    input_resolved = {path.resolve() for path in inputs.values()}
    if output_plans in input_resolved:
        fail("Output plans path equals an input path.")
    if output_plans.exists():
        fail(f"Output plans already exist: {output_plans}")
    existing_audits = [
        str(path) for path in outputs.values() if path.exists()
    ]
    if existing_audits:
        fail(
            "Conversion audit outputs already exist:\n"
            + "\n".join(existing_audits)
        )

    repository_changes_at_invocation = changed_paths()
    unexpected_at_invocation = sorted(
        set(repository_changes_at_invocation)
        - ALLOWED_REPOSITORY_PATHS
    )
    if unexpected_at_invocation:
        fail(
            "Unexpected repository changes before conversion:\n"
            + "\n".join(unexpected_at_invocation)
        )

    external_repository = repository_root(matsim_root)
    external_protected_before = git_status(
        external_repository,
        ["data/matsim_agents/hongkong"],
    )
    if external_protected_before:
        fail(
            "Explicit MATSim root has protected Hong Kong plans changes:\n"
            + external_protected_before
        )

    input_hashes_before = {
        name: sha256(path) for name, path in inputs.items()
    }
    expected_hash_checks = {
        name: input_hashes_before[name] == expected_hash
        for name, expected_hash in EXPECTED_HASHES.items()
    }
    if not all(expected_hash_checks.values()):
        fail(
            "One or more required input SHA256 values do not match: "
            + json.dumps(expected_hash_checks, sort_keys=True)
        )

    mapping_validation = read_json(
        inputs["taxi_routed_main_leg_mapping_validation.json"]
    )
    allocation_summary = read_json(
        inputs["taxi_allocation_summary.json"]
    )
    mapping_prerequisite = {
        "status_audit_completed": (
            mapping_validation.get("status") == "audit_completed"
        ),
        "audit_execution_succeeded": bool(
            mapping_validation.get("audit_execution_succeeded")
        ),
        "mapping_rule_valid": bool(
            mapping_validation["mapping_result"]["mapping_rule_valid"]
        ),
        "uniquely_mapped_ride_legs_37286": (
            mapping_validation["mapping_result"][
                "uniquely_mapped_ride_legs"
            ]
            == EXPECTED_TARGET
        ),
        "ambiguous_mappings_zero": (
            mapping_validation["mapping_result"]["ambiguous_mappings"]
            == 0
        ),
        "missing_mappings_zero": (
            mapping_validation["mapping_result"]["missing_mappings"]
            == 0
        ),
        "existing_fare_route_extraction_valid": bool(
            mapping_validation["existing_route_extraction_result"][
                "existing_fare_route_extraction_valid"
            ]
        ),
        "existing_bridge_inputs_valid": bool(
            mapping_validation["existing_route_extraction_result"][
                "existing_bridge_inputs_valid"
            ]
        ),
        "downstream_action_not_required": not bool(
            mapping_validation["existing_route_extraction_result"][
                "downstream_action_required"
            ]
        ),
    }
    if not all(mapping_prerequisite.values()):
        fail(
            "Mapping validation prerequisite failed: "
            + json.dumps(mapping_prerequisite, sort_keys=True)
        )

    mapping = pd.read_parquet(
        inputs["taxi_unrouted_to_routed_main_leg_mapping.parquet"]
    )
    fare = pd.read_parquet(
        inputs["taxi_leg_fare_estimates_base.parquet"]
    )
    allocation = pd.read_csv(
        inputs["taxi_candidate_leg_classification.csv"],
        encoding="utf-8",
    )
    required_mapping_columns = {
        "person_id",
        "unrouted_leg_sequence",
        "main_trip_index",
        "tour_id",
        "classification_source",
        "taxi_type",
        "origin_activity_type",
        "destination_activity_type",
        "origin_activity_signature",
        "destination_activity_signature",
        "mapped_routed_raw_leg_sequence",
        "mapping_status",
    }
    missing_columns = sorted(required_mapping_columns - set(mapping.columns))
    if missing_columns:
        fail(f"Mapping columns missing: {missing_columns}")

    mapping_key_columns = [
        "person_id",
        "main_trip_index",
        "mapped_routed_raw_leg_sequence",
    ]
    mapping_unique = not mapping.duplicated(mapping_key_columns).any()
    mapping_status_valid = mapping["mapping_status"].eq(
        "mapped_unique_ride_leg"
    ).all()
    if (
        len(mapping) != EXPECTED_TARGET
        or not mapping_unique
        or not mapping_status_valid
    ):
        fail(
            "Mapping target count, uniqueness, or status is invalid: "
            f"rows={len(mapping)}, unique={mapping_unique}, "
            f"status={mapping_status_valid}"
        )

    fare_columns = [
        "person_id",
        "leg_sequence",
        "taxi_type",
        "classification_source",
        "total_fare_distance_only_hkd",
    ]
    joined = mapping.merge(
        fare[fare_columns],
        left_on=["person_id", "unrouted_leg_sequence"],
        right_on=["person_id", "leg_sequence"],
        how="left",
        validate="one_to_one",
        suffixes=("", "_fare"),
        indicator=True,
    )
    fare_values = joined["total_fare_distance_only_hkd"]
    fare_join_valid = bool(
        len(joined) == EXPECTED_TARGET
        and joined["_merge"].eq("both").all()
        and np.isfinite(fare_values).all()
        and fare_values.ge(0).all()
        and joined["taxi_type"].eq(joined["taxi_type_fare"]).all()
        and joined["classification_source"].eq(
            joined["classification_source_fare"]
        ).all()
    )
    if not fare_join_valid:
        fail("Fare join, metadata, finiteness, or non-negativity failed.")

    target_simple_keys = set(
        zip(
            joined["person_id"].astype(str),
            joined["unrouted_leg_sequence"].astype(int),
        )
    )
    allocated_rows = allocation[
        allocation["base_classification"].eq("taxi")
    ]
    allocated_keys = set(
        zip(
            allocated_rows["person_id"].astype(str),
            allocated_rows["leg_sequence"].astype(int),
        )
    )
    explicit_rows = joined[
        joined["classification_source"].eq(
            "v1_mode_detail_explicit_taxi"
        )
    ]
    explicit_keys = set(
        zip(
            explicit_rows["person_id"].astype(str),
            explicit_rows["unrouted_leg_sequence"].astype(int),
        )
    )
    allocation_target_valid = bool(
        len(explicit_keys) == EXPECTED_EXPLICIT
        and len(allocated_keys) == EXPECTED_ALLOCATED
        and not (explicit_keys & allocated_keys)
        and target_simple_keys == explicit_keys | allocated_keys
        and allocation_summary[
            "preserved_current_ride_subtypes_5pct_legs"
        ]["private_car_passenger"]
        == EXPECTED_NON_TAXI_RIDE["private_car_passenger"]
        and allocation_summary[
            "preserved_current_ride_subtypes_5pct_legs"
        ]["school_bus"]
        == EXPECTED_NON_TAXI_RIDE["school_bus"]
        and (
            allocation_summary[
                "preserved_current_ride_subtypes_5pct_legs"
            ]["unspecified_ride"]
            - EXPECTED_ALLOCATED
        )
        == EXPECTED_NON_TAXI_RIDE["base_other_ride"]
    )
    if not allocation_target_valid:
        fail("Base explicit/allocated target union is invalid.")

    records = joined.to_dict(orient="records")
    targets_by_person: dict[str, list[dict[str, Any]]] = defaultdict(list)
    target_lookup: dict[tuple[str, int], dict[str, Any]] = {}
    for record in records:
        person_id = str(record["person_id"])
        raw_sequence = int(record["mapped_routed_raw_leg_sequence"])
        record["person_id"] = person_id
        targets_by_person[person_id].append(record)
        target_key = (person_id, raw_sequence)
        if target_key in target_lookup:
            fail(f"Duplicate person/raw target key: {target_key}")
        target_lookup[target_key] = record

    unrouted_crosscheck = validate_unrouted_targets(
        inputs["plans_unrouted_5pct_v2.xml.gz"],
        targets_by_person,
    )
    if (
        unrouted_crosscheck["parsed_persons"] != EXPECTED_COUNTS["persons"]
        or unrouted_crosscheck["validated_target_keys"] != EXPECTED_TARGET
        or unrouted_crosscheck["error_count"] != 0
    ):
        fail(
            "Unrouted main-trip/signature cross-check failed: "
            + json.dumps(unrouted_crosscheck, sort_keys=True)
        )

    output_plans.parent.mkdir(parents=True, exist_ok=True)
    temp_handle = tempfile.NamedTemporaryFile(
        mode="wb",
        prefix=output_plans.name + ".",
        suffix=".tmp",
        dir=output_plans.parent,
        delete=False,
    )
    temporary_output = Path(temp_handle.name)
    temp_handle.close()
    moved = False
    try:
        before_scan, converted_keys = transform_plans(
            inputs["plans_routed_5pct_v2.xml.gz"],
            temporary_output,
            targets_by_person,
            target_lookup,
        )
        after_scan = scan_plans(
            temporary_output,
            target_lookup,
            output_scan=True,
        )

        before_targets = before_scan["target_legs"]
        after_targets = after_scan["target_legs"]
        expected_target_keys = set(target_lookup)
        before_key_diff = expected_target_keys ^ set(before_targets)
        after_key_diff = expected_target_keys ^ set(after_targets)
        converted_key_diff = expected_target_keys ^ converted_keys

        audit_rows: list[dict[str, Any]] = []
        attribute_matches = 0
        attribute_conflicts = 0
        target_route_mismatches = 0
        fare_attribute_mismatches = 0
        for target_key in sorted(
            expected_target_keys,
            key=lambda item: (item[0], item[1]),
        ):
            record = target_lookup[target_key]
            before = before_targets.get(target_key, {})
            after = after_targets.get(target_key, {})
            before_names = before.get("named_attributes", {})
            if set(before_names) & set(TAXI_ATTRIBUTES):
                attribute_conflicts += 1
            attribute_match, written_fare = exact_attribute_match(
                record,
                after,
            )
            attribute_matches += int(attribute_match)
            fare_matches = bool(
                math.isfinite(written_fare)
                and written_fare
                == float(record["total_fare_distance_only_hkd"])
            )
            fare_attribute_mismatches += int(not fare_matches)
            route_matches = bool(
                before.get("route_attributes_hash")
                == after.get("route_attributes_hash")
                and before.get("route_text_hash")
                == after.get("route_text_hash")
            )
            target_route_mismatches += int(not route_matches)
            conversion_valid = bool(
                before.get("mode") == "ride"
                and after.get("mode") == "taxi"
                and attribute_match
                and fare_matches
                and route_matches
            )
            audit_rows.append(
                {
                    "person_id": record["person_id"],
                    "unrouted_leg_sequence": int(
                        record["unrouted_leg_sequence"]
                    ),
                    "main_trip_index": int(
                        record["main_trip_index"]
                    ),
                    "mapped_routed_raw_leg_sequence": int(
                        record["mapped_routed_raw_leg_sequence"]
                    ),
                    "origin_activity_type": record[
                        "origin_activity_type"
                    ],
                    "destination_activity_type": record[
                        "destination_activity_type"
                    ],
                    "mode_before": before.get("mode", ""),
                    "mode_after": after.get("mode", ""),
                    "route_distance_m": before.get(
                        "route_distance_m", np.nan
                    ),
                    "actual_travel_time_s": before.get(
                        "actual_travel_time_s", np.nan
                    ),
                    "route_attributes_hash_before": before.get(
                        "route_attributes_hash", ""
                    ),
                    "route_attributes_hash_after": after.get(
                        "route_attributes_hash", ""
                    ),
                    "route_text_hash_before": before.get(
                        "route_text_hash", ""
                    ),
                    "route_text_hash_after": after.get(
                        "route_text_hash", ""
                    ),
                    "taxi_type": record["taxi_type"],
                    "classification_source": record[
                        "classification_source"
                    ],
                    "fare_baseline_hkd": float(
                        record["total_fare_distance_only_hkd"]
                    ),
                    "fare_attribute_written_hkd": written_fare,
                    "attribute_match": attribute_match,
                    "conversion_status": (
                        "converted_validated"
                        if conversion_valid
                        else "conversion_validation_failed"
                    ),
                }
            )

        input_hashes_after_temp_validation = {
            name: sha256(path) for name, path in inputs.items()
        }
        before_modes = mode_counts_with_zeroes(
            before_scan["mode_counts"]
        )
        after_modes = mode_counts_with_zeroes(after_scan["mode_counts"])
        temp_hash = sha256(temporary_output)
        temp_size = temporary_output.stat().st_size
        output_in_repository = (
            ROOT == output_plans
            or ROOT in output_plans.parents
        )
        expected_counts = dict(EXPECTED_COUNTS)
        routed_structure_preserved = bool(
            before_scan["normalized_structure_sha256"]
            == after_scan["normalized_structure_sha256"]
            and before_scan["person_order_sha256"]
            == after_scan["person_order_sha256"]
            and before_scan["root_tag"] == after_scan["root_tag"]
            and before_scan["root_attributes"]
            == after_scan["root_attributes"]
        )
        route_attributes_preserved = bool(
            before_scan["counts"]["routes"] == EXPECTED_COUNTS["routes"]
            and after_scan["counts"]["routes"] == EXPECTED_COUNTS["routes"]
            and before_scan["route_attributes_sha256"]
            == after_scan["route_attributes_sha256"]
        )
        route_text_preserved = bool(
            before_scan["counts"]["routes"] == EXPECTED_COUNTS["routes"]
            and after_scan["counts"]["routes"] == EXPECTED_COUNTS["routes"]
            and before_scan["route_text_sha256"]
            == after_scan["route_text_sha256"]
        )
        activities_preserved = bool(
            before_scan["counts"]["activities"]
            == EXPECTED_COUNTS["activities"]
            and after_scan["counts"]["activities"]
            == EXPECTED_COUNTS["activities"]
            and before_scan["activity_signatures_sha256"]
            == after_scan["activity_signatures_sha256"]
        )
        all_target_modes_valid = bool(
            all(
                before_targets[key]["mode"] == "ride"
                and after_targets[key]["mode"] == "taxi"
                for key in expected_target_keys
            )
        )
        pre_move_checks = {
            "required_inputs_exist": True,
            "branch_head_baseline_match": True,
            "explicit_matsim_root_used": True,
            "output_path_is_new_and_not_an_input": True,
            "expected_input_hashes_match": all(
                expected_hash_checks.values()
            ),
            "mapping_validation_prerequisite_passed": all(
                mapping_prerequisite.values()
            ),
            "target_mapping_has_37286_unique_valid_rows": bool(
                len(target_lookup) == EXPECTED_TARGET
                and mapping_unique
                and mapping_status_valid
            ),
            "base_explicit_plus_allocated_target_union_exact": (
                allocation_target_valid
            ),
            "unrouted_main_trip_and_activity_signatures_match": bool(
                unrouted_crosscheck["validated_target_keys"]
                == EXPECTED_TARGET
                and unrouted_crosscheck["error_count"] == 0
            ),
            "temporary_output_xml_fully_parsed": True,
            "before_structure_counts_match_expected": (
                before_scan["counts"] == expected_counts
            ),
            "after_structure_counts_match_expected": (
                after_scan["counts"] == expected_counts
            ),
            "before_mode_counts_match_expected": (
                before_modes == EXPECTED_MODES_BEFORE
            ),
            "after_mode_counts_match_expected": (
                after_modes == EXPECTED_MODES_AFTER
            ),
            "exactly_37286_ride_to_taxi_conversions": bool(
                len(converted_keys) == EXPECTED_TARGET
                and not converted_key_diff
                and all_target_modes_valid
            ),
            "target_key_symmetric_difference_zero": bool(
                not before_key_diff and not after_key_diff
            ),
            "all_non_target_ride_legs_remain_ride": bool(
                after_modes.get("ride") == EXPECTED_MODES_AFTER["ride"]
                and routed_structure_preserved
            ),
            "no_other_mode_or_structure_changes": (
                routed_structure_preserved
            ),
            "no_preexisting_taxi_attribute_conflicts": (
                attribute_conflicts == 0
            ),
            "all_target_taxi_attributes_exactly_match": (
                attribute_matches == EXPECTED_TARGET
            ),
            "all_fares_finite_nonnegative_and_exact": bool(
                fare_join_valid and fare_attribute_mismatches == 0
            ),
            "all_target_route_hashes_match": (
                target_route_mismatches == 0
            ),
            "all_879050_route_attributes_preserved": (
                route_attributes_preserved
            ),
            "all_879050_route_text_values_preserved": (
                route_text_preserved
            ),
            "all_1264870_activity_signatures_preserved": (
                activities_preserved
            ),
            "source_and_audit_inputs_unchanged_during_validation": (
                input_hashes_before
                == input_hashes_after_temp_validation
            ),
            "selected_plans_remain_determinate": bool(
                before_scan["selected_plan_unresolved_persons"] == 0
                and after_scan["selected_plan_unresolved_persons"] == 0
            ),
            "temporary_output_nonempty": temp_size > 0,
        }
        failed_pre_move = [
            name
            for name, passed in pre_move_checks.items()
            if not passed
        ]
        if failed_pre_move:
            fail(
                "Pre-move conversion validation failed: "
                + ", ".join(failed_pre_move)
            )

        temporary_output.replace(output_plans)
        moved = True
        output_hash = sha256(output_plans)
        output_size = output_plans.stat().st_size
        if output_hash != temp_hash or output_size != temp_size:
            fail("Atomic output move changed the output hash or size.")

        out_dir.mkdir(parents=True, exist_ok=False)
        audit = pd.DataFrame(audit_rows)
        audit.to_csv(
            outputs["taxi_plans_conversion_leg_audit.csv"],
            index=False,
            encoding="utf-8",
            lineterminator="\n",
        )
        all_modes = sorted(set(before_modes) | set(after_modes))
        mode_summary = pd.DataFrame(
            [
                {
                    "mode": mode,
                    "before_count": before_modes.get(mode, 0),
                    "after_count": after_modes.get(mode, 0),
                    "difference": (
                        after_modes.get(mode, 0)
                        - before_modes.get(mode, 0)
                    ),
                    "expected_before_count": (
                        EXPECTED_MODES_BEFORE.get(mode, 0)
                    ),
                    "expected_after_count": (
                        EXPECTED_MODES_AFTER.get(mode, 0)
                    ),
                }
                for mode in all_modes
            ]
        )
        mode_summary.to_csv(
            outputs["taxi_plans_conversion_mode_summary.csv"],
            index=False,
            encoding="utf-8",
            lineterminator="\n",
        )

        input_hashes_after = {
            name: sha256(path) for name, path in inputs.items()
        }
        external_protected_after = git_status(
            external_repository,
            ["data/matsim_agents/hongkong"],
        )
        planned_validation_path = (
            outputs["taxi_plans_conversion_validation.json"]
            .relative_to(ROOT)
            .as_posix()
        )
        repository_changes = sorted(
            set(changed_paths()) | {planned_validation_path}
        )
        unexpected_repository_changes = sorted(
            set(repository_changes) - ALLOWED_REPOSITORY_PATHS
        )
        forbidden_repository_changes = [
            path
            for path in repository_changes
            if (
                path.endswith(".java")
                or path.endswith("pom.xml")
                or path.endswith(".xml")
                or "/network" in path.lower()
                or "/facilities" in path.lower()
                or "/vehicles" in path.lower()
                or "/fleet" in path.lower()
                or "/scoring" in path.lower()
            )
        ]

        required_checks = {
            **pre_move_checks,
            "output_atomic_move_hash_and_size_match": bool(
                output_hash == temp_hash and output_size == temp_size
            ),
            "output_plans_exists_and_nonempty": bool(
                output_plans.is_file() and output_size > 0
            ),
            "leg_audit_has_37286_valid_rows": bool(
                len(audit) == EXPECTED_TARGET
                and audit["conversion_status"]
                .eq("converted_validated")
                .all()
            ),
            "mode_summary_written": bool(
                outputs[
                    "taxi_plans_conversion_mode_summary.csv"
                ].is_file()
            ),
            "all_inputs_unchanged_after_output": (
                input_hashes_before == input_hashes_after
            ),
            "external_source_plans_git_status_unchanged_clean": bool(
                external_protected_before == ""
                and external_protected_after == ""
            ),
            "only_allowed_repository_paths_changed": (
                len(unexpected_repository_changes) == 0
            ),
            "no_config_java_scoring_fleet_or_xml_changed": (
                len(forbidden_repository_changes) == 0
            ),
        }
        failed_checks = [
            name
            for name, passed in required_checks.items()
            if not passed
        ]
        all_checks_passed = all(required_checks.values())
        status = "validated" if all_checks_passed else "failed"

        classification_counts = {
            str(key): int(value)
            for key, value in joined[
                "classification_source"
            ].value_counts().sort_index().items()
        }
        taxi_type_counts = {
            str(key): int(value)
            for key, value in joined[
                "taxi_type"
            ].value_counts().sort_index().items()
        }
        validation = {
            "scenario_family": (
                "hong_kong_taxi_base_plans_conversion_v1"
            ),
            "status": status,
            "all_checks_passed": all_checks_passed,
            "required_checks": required_checks,
            "failed_checks": failed_checks,
            "starting_repository_gate": {
                "required_branch": EXPECTED_BRANCH,
                "required_starting_head": EXPECTED_HEAD,
                "baseline": EXPECTED_BASELINE,
                "ahead": ahead,
                "behind": behind,
                "task_start_git_status_short": "",
                "task_start_clean_verified_before_edits": True,
                "repository_changes_at_script_invocation": (
                    repository_changes_at_invocation
                ),
            },
            "roots": {
                "worktree_root": ROOT.as_posix(),
                "explicit_matsim_root": matsim_root.as_posix(),
                "matsim_root_was_explicit": True,
                "external_matsim_git_root": (
                    external_repository.as_posix()
                ),
            },
            "input_paths": {
                name: path.resolve().as_posix()
                for name, path in inputs.items()
            },
            "input_sha256_before": input_hashes_before,
            "input_sha256_after": input_hashes_after,
            "expected_sha256_checks": expected_hash_checks,
            "mapping_prerequisite": mapping_prerequisite,
            "output_plans": {
                "path": output_plans.as_posix(),
                "size_bytes": output_size,
                "sha256": output_hash,
                "created_via_temporary_file_and_atomic_move": True,
                "inside_git_repository": output_in_repository,
                "pushed_to_remote": False,
                "repository_policy_note": (
                    "The derived plans are stored outside both Git "
                    "worktrees because /data/matsim_agents/ is excluded "
                    "by the existing repository policy. Git LFS, "
                    ".gitattributes, and .gitignore were not changed."
                ),
            },
            "before": {
                key: value
                for key, value in before_scan.items()
                if key != "target_legs"
            },
            "after": {
                key: value
                for key, value in after_scan.items()
                if key != "target_legs"
            },
            "conversion_counts": {
                "target": EXPECTED_TARGET,
                "converted": len(converted_keys),
                "missing": len(expected_target_keys - converted_keys),
                "duplicate": 0,
                "unexpected": len(converted_keys - expected_target_keys),
                "target_key_symmetric_difference": len(
                    converted_key_diff
                ),
                "explicit": len(explicit_keys),
                "allocated_base": len(allocated_keys),
                "private_car_passenger_not_converted": (
                    EXPECTED_NON_TAXI_RIDE["private_car_passenger"]
                ),
                "school_bus_not_converted": (
                    EXPECTED_NON_TAXI_RIDE["school_bus"]
                ),
                "base_other_ride_not_converted": (
                    EXPECTED_NON_TAXI_RIDE["base_other_ride"]
                ),
            },
            "taxi_population": {
                "unique_persons": int(joined["person_id"].nunique()),
                "unique_tours": int(joined["tour_id"].nunique()),
                "taxi_type_counts": taxi_type_counts,
                "classification_source_counts": classification_counts,
                "unresolved_taxi_count": int(
                    joined["taxi_type"].eq("unresolved").sum()
                ),
            },
            "fare_baseline_hkd": distribution(fare_values),
            "attribute_validation": {
                "required_attribute_names_and_classes": (
                    TAXI_ATTRIBUTES
                ),
                "preexisting_name_conflicts": attribute_conflicts,
                "exact_attribute_match_count": attribute_matches,
                "fare_attribute_mismatch_count": (
                    fare_attribute_mismatches
                ),
                "utility_or_asc_attributes_written": False,
            },
            "preservation": {
                "route_attributes_compared": EXPECTED_COUNTS["routes"],
                "route_attributes_mismatches": (
                    0 if route_attributes_preserved else None
                ),
                "route_text_values_compared": EXPECTED_COUNTS["routes"],
                "route_text_mismatches": (
                    0 if route_text_preserved else None
                ),
                "target_route_hash_mismatches": (
                    target_route_mismatches
                ),
                "activity_signatures_compared": (
                    EXPECTED_COUNTS["activities"]
                ),
                "activity_signature_mismatches": (
                    0 if activities_preserved else None
                ),
                "normalized_structure_preserved": (
                    routed_structure_preserved
                ),
                "source_files_unchanged": (
                    input_hashes_before == input_hashes_after
                ),
            },
            "git_protection": {
                "repository_changed_paths": repository_changes,
                "allowed_repository_paths": sorted(
                    ALLOWED_REPOSITORY_PATHS
                ),
                "unexpected_repository_changes": (
                    unexpected_repository_changes
                ),
                "forbidden_repository_changes": (
                    forbidden_repository_changes
                ),
                "external_protected_status_before": (
                    external_protected_before
                ),
                "external_protected_status_after": (
                    external_protected_after
                ),
            },
            "execution_declarations": {
                "matsim_run": False,
                "qsim_run": False,
                "routing_run": False,
                "smoke_or_load_test_run": False,
                "java_custom_scoring_run": False,
                "asc_test_run": False,
                "fleet_simulation_run": False,
                "config_modified": False,
                "java_modified": False,
                "scoring_modified": False,
                "fleet_modified": False,
                "source_plans_modified": False,
            },
            "output_files": [
                path.as_posix() for path in outputs.values()
            ],
        }
        write_json(
            outputs["taxi_plans_conversion_validation.json"],
            validation,
        )
        print(
            json.dumps(
                {
                    "status": status,
                    "all_checks_passed": all_checks_passed,
                    "failed_checks": failed_checks,
                    "output_plans": validation["output_plans"],
                    "conversion_counts": validation[
                        "conversion_counts"
                    ],
                    "before_mode_counts": before_modes,
                    "after_mode_counts": after_modes,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        if not all_checks_passed:
            raise SystemExit(1)
    finally:
        if not moved and temporary_output.exists():
            temporary_output.unlink()


if __name__ == "__main__":
    main()
