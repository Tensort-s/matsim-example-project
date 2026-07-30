#!/usr/bin/env python3
"""Independently validate Hong Kong bus simulation fares v1."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import re
import statistics
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import pandas as pd
import pyarrow.parquet as pq


BASE_REL = Path("data/transport_costs/hongkong/pt_fare_v1")
AUDIT_REL = BASE_REL / "bus_scope_direction_audit_v1"
CORE_REL = BASE_REL / "bus_fare_v1"
OUTPUT_REL = BASE_REL / "bus_fare_simulation_v1"
SCHEDULE_REL = Path(
    "data/transit/hongkong/processed/"
    "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_"
    "ferry_core_v1_cap010/transitSchedule_5pct.xml.gz"
)
NETWORK_REL = SCHEDULE_REL.parent / "network.xml.gz"
KNOWN_UNMATCHED = {
    "bus_1000004_1",
    "bus_1000004_2",
    "bus_1000611_1",
    "bus_8780_1",
    "bus_8780_2",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def nearest_existing_median(values: list[float]) -> tuple[float, float]:
    distinct = sorted(set(float(value) for value in values))
    position = float(statistics.median(distinct))
    selected = min(distinct, key=lambda value: (abs(value - position), -value))
    return selected, position


def independent_conflict_selection(
    row: dict[str, Any],
    records: list[dict[str, Any]],
    full_lookup: dict[tuple[str, str, str], dict[str, Any]],
) -> tuple[float, str]:
    values = [float(record["price"]) for record in records]
    distinct = sorted(set(values))
    full = full_lookup.get(
        (
            row["official_operator"],
            str(row["official_route_id"]),
            str(row["official_route_sequence"]),
        )
    )
    if full:
        pattern = json.loads(full["official_stop_pattern_json"])
        full_value = float(full["full_fare_hkd"])
        if (
            pattern
            and row["boarding_stop_id"] == pattern[0]
            and row["alighting_stop_id"] == pattern[-1]
            and sum(value == full_value for value in distinct) == 1
        ):
            return full_value, "terminal_OD_candidate_matching_JSON_fullFare"
    counts = Counter(values)
    maximum = max(counts.values())
    modes = sorted(value for value, count in counts.items() if count == maximum)
    if len(modes) == 1:
        return modes[0], "modal_raw_official_candidate_amount"
    selected, _ = nearest_existing_median(distinct)
    return selected, "median_nearest_existing_candidate_tie_higher"


def read_schedule(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rb") as handle:
        root = ET.parse(handle).getroot()
    routes: list[dict[str, Any]] = []
    for line in root:
        if local_name(line.tag) != "transitLine":
            continue
        for route in line:
            if local_name(route.tag) != "transitRoute":
                continue
            mode = ""
            stop_count = 0
            link_ids: list[str] = []
            for child in route:
                tag = local_name(child.tag)
                if tag == "transportMode":
                    mode = (child.text or "").strip()
                elif tag == "routeProfile":
                    stop_count = sum(
                        local_name(item.tag) == "stop" for item in child
                    )
                elif tag == "route":
                    link_ids = [
                        item.attrib["refId"]
                        for item in child
                        if local_name(item.tag) == "link"
                    ]
            if mode == "bus":
                routes.append(
                    {
                        "matsim_line_id": line.attrib["id"],
                        "matsim_route_id": route.attrib["id"],
                        "stop_count": stop_count,
                        "link_ids": link_ids,
                    }
                )
    return sorted(routes, key=lambda row: row["matsim_route_id"])


def read_link_lengths(path: Path, required: set[str]) -> dict[str, float]:
    lengths: dict[str, float] = {}
    with gzip.open(path, "rb") as handle:
        for _, element in ET.iterparse(handle, events=("end",)):
            if local_name(element.tag) == "link":
                link_id = element.attrib.get("id", "")
                if link_id in required:
                    lengths[link_id] = float(element.attrib["length"])
            element.clear()
    return lengths


def has_absolute_path(directory: Path) -> bool:
    patterns = (
        re.compile(rb"(?<![A-Za-z])[A-Za-z]:\\"),
        re.compile(rb"(?<![A-Za-z])[A-Za-z]:/"),
    )
    for path in directory.iterdir():
        if not path.is_file() or path.suffix == ".parquet":
            continue
        data = path.read_bytes()
        if any(pattern.search(data) for pattern in patterns):
            return True
    return False


def artifact_hashes(directory: Path) -> dict[str, str]:
    excluded = {"bus_simulation_fare_validation.json", "SHA256SUMS.txt"}
    return {
        path.name: sha256(path)
        for path in sorted(directory.iterdir(), key=lambda item: item.name)
        if path.is_file() and path.name not in excluded
    }


def rebuild_matches_current(
    repo_root: Path, source_root: Path, output_dir: Path
) -> tuple[bool, str, str, list[str]]:
    builder = (
        repo_root
        / "scripts/hong_kong_single_city/costs/pt/"
        "build_hong_kong_bus_simulation_fares.py"
    )
    query = (
        repo_root
        / "scripts/hong_kong_single_city/costs/pt/"
        "quote_hong_kong_bus_simulation_fares.py"
    )
    current = artifact_hashes(output_dir)
    with tempfile.TemporaryDirectory(prefix="hk_bus_sim_rebuild_") as temp:
        rebuilt = Path(temp) / "bus_fare_simulation_v1"
        subprocess.run(
            [
                sys.executable,
                str(builder),
                "--source-project-root",
                str(source_root),
                "--output-dir",
                str(rebuilt),
            ],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                sys.executable,
                str(query),
                "--input",
                str(rebuilt / "bus_simulation_query_fixture_input.csv"),
                "--output",
                str(rebuilt / "bus_simulation_query_fixture_output.csv"),
                "--rules",
                str(rebuilt / "bus_simulation_fare_rules.parquet"),
                "--route-fallbacks",
                str(rebuilt / "bus_route_fallback_fares.csv"),
            ],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        rebuilt_hashes = artifact_hashes(rebuilt)
    digest_1 = hashlib.sha256(compact_json(current).encode()).hexdigest()
    digest_2 = hashlib.sha256(compact_json(rebuilt_hashes).encode()).hexdigest()
    differences = sorted(
        name
        for name in set(current) | set(rebuilt_hashes)
        if current.get(name) != rebuilt_hashes.get(name)
    )
    return current == rebuilt_hashes, digest_1, digest_2, differences


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-project-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[4]
    source_root = args.source_project_root.resolve()
    output_dir = (args.output_dir or repo_root / OUTPUT_REL).resolve()
    audit_dir = repo_root / AUDIT_REL
    core_dir = repo_root / CORE_REL

    expected_files = {
        "README.md",
        "SHA256SUMS.txt",
        "bus_simulation_fare_rules.parquet",
        "bus_simulation_fare_rules_sample.csv",
        "bus_simulation_fare_anomalies.parquet",
        "bus_simulation_fare_anomalies_sample.csv",
        "bus_route_fallback_fares.csv",
        "bus_fare_resolution_method_summary.csv",
        "bus_fare_resolution_quality_summary.csv",
        "bus_simulation_query_fixture_input.csv",
        "bus_simulation_query_fixture_output.csv",
        "bus_simulation_fare_summary.json",
        "bus_simulation_fare_validation.json",
        "protected_hashes.csv",
    }
    missing_files = sorted(
        expected_files
        - {path.name for path in output_dir.iterdir() if path.is_file()}
    )
    audit = pd.read_parquet(
        audit_dir / "bus_od_fare_candidate_audit.parquet"
    ).fillna("")
    core = pd.read_parquet(core_dir / "bus_fare_rules.parquet").fillna("")
    rules = pd.read_parquet(
        output_dir / "bus_simulation_fare_rules.parquet"
    ).fillna("")
    anomalies = pd.read_parquet(
        output_dir / "bus_simulation_fare_anomalies.parquet"
    ).fillna("")
    fallbacks = pd.read_csv(
        output_dir / "bus_route_fallback_fares.csv",
        dtype=str,
        keep_default_na=False,
    )
    full_fares = pd.read_csv(
        audit_dir / "bus_route_full_fare_reference.csv",
        dtype=str,
        keep_default_na=False,
    )
    readiness = pd.read_csv(
        audit_dir / "bus_route_direction_readiness.csv",
        dtype=str,
        keep_default_na=False,
    )
    fixture_input = pd.read_csv(
        output_dir / "bus_simulation_query_fixture_input.csv",
        dtype=str,
        keep_default_na=False,
    )
    fixture_output = pd.read_csv(
        output_dir / "bus_simulation_query_fixture_output.csv",
        dtype=str,
        keep_default_na=False,
    )
    summary = json.loads(
        (output_dir / "bus_simulation_fare_summary.json").read_text(
            encoding="utf-8"
        )
    )

    key_columns = [
        "matsim_line_id",
        "matsim_route_id",
        "official_route_id",
        "official_direction",
        "boarding_stop_id",
        "alighting_stop_id",
    ]
    rule_lookup = {
        tuple(str(row[column]) for column in key_columns): row
        for row in rules.to_dict("records")
    }
    core_lookup = {
        tuple(str(row[column]) for column in key_columns): row
        for row in core.to_dict("records")
    }
    full_lookup = {
        (
            row["official_operator"],
            row["official_route_id"],
            row["official_route_sequence"],
        ): row
        for row in full_fares.to_dict("records")
    }

    check_2 = len(rules) == 771_666 and len(rule_lookup) == 771_666
    check_3 = (
        (rules["model_fare_hkd"] != "").all()
        and (rules["cost_hkd"] != "").all()
    )
    check_4 = (
        rules["model_fare_hkd"].astype(float)
        == rules["cost_hkd"].astype(float)
    ).all()
    active_match = True
    duplicate_counts: Counter[str] = Counter()
    unique_counts: Counter[str] = Counter()
    conflict_counts: Counter[str] = Counter()
    conflict_method_counts: Counter[str] = Counter()
    duplicate_ok = True
    unique_ok = True
    conflict_ok = True
    selected_in_candidates = True
    conflict_provenance_ok = True
    zero_rules = 0
    active_zero = 0
    duplicate_zero = 0
    no_unsupported_zero = True
    for source in audit.to_dict("records"):
        key = tuple(str(source[column]) for column in key_columns)
        result = rule_lookup.get(key)
        if result is None:
            active_match = False
            duplicate_ok = False
            unique_ok = False
            conflict_ok = False
            continue
        records = json.loads(source["candidate_records_json"])
        values = [float(record["price"]) for record in records]
        selected = float(result["model_fare_hkd"])
        selected_in_candidates &= selected in values
        scope = source["route_franchise_scope_status"]
        status = source["record_status"]
        if scope == "confirmed_franchised_route" and status == "unique_candidate":
            core_row = core_lookup.get(key)
            active_match &= bool(
                core_row
                and selected == float(core_row["published_fare_hkd"])
                and float(result["official_published_fare_hkd"]) == selected
                and result["fare_resolution_method"]
                == "direct_unique_gtfs_ordered_od"
                and result["cost_quality"] == "B"
            )
        elif status == "duplicate_identical":
            duplicate_counts[scope] += 1
            duplicate_ok &= (
                len(records) >= 2
                and len(set(values)) == 1
                and selected == values[0]
                and result["official_published_fare_hkd"] == ""
                and result["fare_resolution_method"]
                == "identical_raw_candidate_consensus"
                and result["cost_quality"] == "C"
                and bool(result["anomaly_flag"])
            )
        elif status == "unique_candidate":
            unique_counts[scope] += 1
            expected_method = (
                "direct_unique_gtfs_ordered_od_other_bus_scope"
                if scope == "other_bus_service"
                else "direct_unique_gtfs_ordered_od_route_scope_unresolved"
            )
            expected_quality = "B" if scope == "other_bus_service" else "C"
            unique_ok &= (
                len(records) == 1
                and selected == values[0]
                and float(result["official_published_fare_hkd"]) == selected
                and result["fare_resolution_method"] == expected_method
                and result["cost_quality"] == expected_quality
                and bool(result["anomaly_flag"])
            )
        elif status == "conflicting_amounts":
            conflict_counts[scope] += 1
            expected, method = independent_conflict_selection(
                source, records, full_lookup
            )
            conflict_method_counts[method] += 1
            conflict_ok &= (
                selected == expected
                and result["official_published_fare_hkd"] == ""
                and result["fare_resolution_method"] == method
                and result["cost_quality"] == "D"
                and bool(result["anomaly_flag"])
            )
            distinct = sorted(set(values))
            conflict_provenance_ok &= (
                json.loads(result["candidate_values_hkd_json"]) == distinct
                and int(result["candidate_record_count"]) == len(records)
                and float(result["candidate_min_hkd"]) == min(values)
                and float(result["candidate_max_hkd"]) == max(values)
                and float(result["candidate_spread_hkd"])
                == max(values) - min(values)
                and float(result["selected_candidate_hkd"]) == selected
                and json.loads(result["source_record_ids_json"])
                == json.loads(source["candidate_record_ids_json"])
            )
        if selected == 0:
            zero_rules += 1
            no_unsupported_zero &= (
                bool(result["zero_is_explicit_raw_record"])
                and values
                and all(value == 0 for value in values)
                and "explicit_raw_zero_fare" in result["anomaly_reason"]
                and int(result["audit_priority"]) == 3
            )
            if (
                scope == "confirmed_franchised_route"
                and status == "unique_candidate"
            ):
                active_zero += 1
            if status == "duplicate_identical":
                duplicate_zero += 1

    check_5 = active_match and sum(
        1
        for row in audit.to_dict("records")
        if row["route_franchise_scope_status"] == "confirmed_franchised_route"
        and row["record_status"] == "unique_candidate"
    ) == 754_133
    check_6 = (
        duplicate_ok
        and duplicate_counts["confirmed_franchised_route"] == 1_827
    )
    check_7 = (
        conflict_ok
        and conflict_counts["confirmed_franchised_route"] == 2_603
    )
    check_8 = (
        unique_ok
        and unique_counts["franchise_route_scope_unresolved"] == 2_074
    )
    check_9 = (
        duplicate_counts["franchise_route_scope_unresolved"] == 34
    )
    check_10 = unique_counts["other_bus_service"] == 10_836
    check_11 = duplicate_counts["other_bus_service"] == 139
    check_12 = conflict_counts["other_bus_service"] == 20
    check_13 = selected_in_candidates
    check_14 = conflict_provenance_ok and sum(conflict_counts.values()) == 2_623
    check_15 = active_zero == 637
    check_16 = (
        no_unsupported_zero
        and zero_rules == 642
        and duplicate_zero == 5
        and (fallbacks["route_fallback_fare_hkd"].astype(float) > 0).all()
    )

    fallback_lookup = fallbacks.set_index("matsim_route_id").to_dict("index")
    unmatched = fallbacks[
        fallbacks["route_franchise_scope_status"] == "operator_scope_unresolved"
    ]
    check_17 = (
        len(unmatched) == 5
        and set(unmatched["matsim_route_id"]) == KNOWN_UNMATCHED
        and (unmatched["route_fallback_fare_hkd"].astype(float) > 0).all()
        and (unmatched["cost_quality"] == "D").all()
    )
    check_18 = (
        len(fallbacks) == 2_363
        and fallbacks["matsim_route_id"].nunique() == 2_363
        and (fallbacks["route_fallback_fare_hkd"].astype(float) > 0).all()
    )

    schedule = read_schedule(source_root / SCHEDULE_REL)
    required_links = {
        link_id for route in schedule for link_id in route["link_ids"]
    }
    lengths = read_link_lengths(source_root / NETWORK_REL, required_links)
    schedule_lookup = {row["matsim_route_id"]: row for row in schedule}
    readiness_lookup = readiness.set_index("matsim_route_id").to_dict("index")
    route_representative: dict[str, float] = {}
    for route_id, group in rules[rules["model_fare_hkd"].astype(float) > 0].groupby(
        "matsim_route_id", sort=True
    ):
        route_representative[str(route_id)] = nearest_existing_median(
            group["model_fare_hkd"].astype(float).tolist()
        )[0]
    route_properties: dict[str, dict[str, Any]] = {}
    for route_id, scheduled in schedule_lookup.items():
        meta = readiness_lookup[route_id]
        route_properties[route_id] = {
            "distance": sum(lengths[link] for link in scheduled["link_ids"]),
            "stop_count": scheduled["stop_count"],
            "operator": meta["official_operator"],
            "official_route_id": meta["official_route_id"],
            "sequence": meta["official_route_sequence"],
        }
    priority_ok = True
    for route_id, fallback in fallback_lookup.items():
        props = route_properties[route_id]
        full = full_lookup.get(
            (props["operator"], props["official_route_id"], props["sequence"])
        )
        priority_ok &= (
            abs(float(fallback["route_distance_m"]) - props["distance"]) < 1e-6
            and int(fallback["stop_count"]) == props["stop_count"]
        )
        if full is not None and float(full["full_fare_hkd"]) > 0:
            priority_ok &= (
                int(fallback["fallback_level"]) == 1
                and float(fallback["route_fallback_fare_hkd"])
                == float(full["full_fare_hkd"])
                and fallback["fare_resolution_method"]
                == "exact_json_route_direction_fullFare"
            )
            continue
        same_direction = rules[
            (rules["official_route_id"] == props["official_route_id"])
            & (rules["official_route_sequence"] == props["sequence"])
            & (rules["model_fare_hkd"].astype(float) > 0)
        ]
        same_route = rules[
            (rules["official_route_id"] == props["official_route_id"])
            & (rules["model_fare_hkd"].astype(float) > 0)
        ]
        if len(same_direction):
            expected_level = 2
        elif len(same_route):
            expected_level = 3
        elif props["operator"]:
            expected_level = 4
        else:
            expected_level = 5
        priority_ok &= int(fallback["fallback_level"]) == expected_level
        references = json.loads(fallback["fallback_reference_values_hkd_json"])
        reference_routes = json.loads(
            fallback["fallback_reference_route_ids_json"]
        )
        selected, _ = nearest_existing_median(references)
        priority_ok &= (
            float(fallback["route_fallback_fare_hkd"]) == selected
            and len(references) == int(fallback["fallback_reference_count"])
            and len(reference_routes) == len(references)
            and all(value > 0 for value in references)
        )
        if expected_level in {4, 5}:
            candidate_ids = [
                candidate_id
                for candidate_id, candidate_props in route_properties.items()
                if candidate_id != route_id
                and candidate_id in route_representative
                and (
                    expected_level == 5
                    or candidate_props["operator"] == props["operator"]
                )
            ]
            scored = sorted(
                (
                    abs(
                        math.log(
                            max(route_properties[candidate_id]["distance"], 1.0)
                            / max(props["distance"], 1.0)
                        )
                    )
                    + (
                        abs(
                            route_properties[candidate_id]["stop_count"]
                            - props["stop_count"]
                        )
                        / max(props["stop_count"], 1)
                    ),
                    candidate_id,
                )
                for candidate_id in candidate_ids
            )[:25]
            priority_ok &= reference_routes == [route for _, route in scored]
            priority_ok &= references == [
                route_representative[route] for _, route in scored
            ]
    check_19 = priority_ok

    output_lookup = fixture_output.set_index("quote_id").to_dict("index")
    fixture_ok = len(fixture_input) == len(fixture_output) == 20
    fixture_passed = 0
    fixture_details: list[dict[str, Any]] = []
    for request in fixture_input.to_dict("records"):
        output = output_lookup.get(request["quote_id"])
        expected_available = request["expected_result"] == "available"
        expected_fallback = request["expected_fallback_used"] == "true"
        passed = bool(
            output
            and (
                (
                    expected_available
                    and output["model_fare_hkd"] != ""
                    and output["cost_hkd"] == output["model_fare_hkd"]
                    and output["fare_resolution_method"]
                    == request["expected_resolution_method"]
                    and output["fallback_used"].lower()
                    == str(expected_fallback).lower()
                    and output["transfer_concession_status"]
                    == "not_modelled_ignored_for_v1"
                    and output["eligibility_status"]
                    == "not_modelled_generic_passenger_assumed"
                    and output["temporal_status"]
                    == (
                        "source_snapshot_applied_without_route_specific_"
                        "effective_date"
                    )
                )
                or (
                    not expected_available
                    and output["model_fare_hkd"] == ""
                    and output["cost_hkd"] == ""
                    and output["fare_resolution_status"] == "unresolved"
                    and output["unresolved_reason"] == "unknown_matsim_bus_route"
                )
            )
        )
        fixture_ok &= passed
        fixture_passed += passed
        fixture_details.append(
            {"quote_id": request["quote_id"], "passed": passed}
        )
    exact_fixture_ids = {
        "confirmed_official_unique",
        "confirmed_official_zero",
        "confirmed_duplicate_consensus",
        "confirmed_conflict_unique_mode",
        "confirmed_conflict_median_tie_higher",
        "terminal_OD_matching_JSON_fullFare",
        "route_scope_unresolved_unique",
        "route_scope_unresolved_duplicate",
        "LRTFeeder_unique",
        "DB_unique",
        "PI_unique",
        "XB_unique",
        "other_service_conflict",
        "known_operator_unresolved_route_fallback",
        "known_route_unknown_OD_fallback",
        "transfer_requested_returns_base",
        "specified_passenger_payment_returns_generic",
        "travel_date_returns_snapshot",
        "reverse_OD_uses_route_fallback",
        "unknown_route_unresolved",
    }
    fixture_ok &= set(fixture_input["quote_id"]) == exact_fixture_ids
    check_20 = fixture_ok and all(
        output_lookup[quote_id]["fallback_used"] == "False"
        for quote_id in (
            "confirmed_official_unique",
            "confirmed_duplicate_consensus",
            "confirmed_conflict_unique_mode",
        )
    )
    check_21 = (
        output_lookup["known_route_unknown_OD_fallback"]["fallback_used"] == "True"
        and output_lookup["reverse_OD_uses_route_fallback"]["fallback_used"] == "True"
        and output_lookup["known_route_unknown_OD_fallback"]["cost_hkd"] != ""
    )
    check_22 = (
        output_lookup["unknown_route_unresolved"]["cost_hkd"] == ""
        and output_lookup["unknown_route_unresolved"]["fare_resolution_status"]
        == "unresolved"
    )
    check_23 = (
        rules.loc[rules["model_assumption_used"], "anomaly_flag"].all()
        and (fallbacks["anomaly_flag"] == "True").all()
        and len(anomalies) == 20_533
    )
    check_24 = "A" not in set(rules["cost_quality"]) and "A" not in set(
        fallbacks["cost_quality"]
    )
    quality_methods = {
        "direct_unique_gtfs_ordered_od": "B",
        "direct_unique_gtfs_ordered_od_other_bus_scope": "B",
        "direct_unique_gtfs_ordered_od_route_scope_unresolved": "C",
        "identical_raw_candidate_consensus": "C",
        "terminal_OD_candidate_matching_JSON_fullFare": "D",
        "modal_raw_official_candidate_amount": "D",
        "median_nearest_existing_candidate_tie_higher": "D",
    }
    check_25 = all(
        row["cost_quality"] == quality_methods[row["fare_resolution_method"]]
        for row in rules.to_dict("records")
    ) and (fallbacks["cost_quality"] == "D").all()
    check_26 = fixture_ok

    protected_baseline = pd.read_csv(
        output_dir / "protected_hashes.csv",
        dtype=str,
        keep_default_na=False,
    )
    protected_results: list[dict[str, Any]] = []
    for row in protected_baseline.to_dict("records"):
        path = (
            source_root / row["repository_relative_path"]
            if row["protected_scope"] == "matsim_protected_input"
            else repo_root / row["repository_relative_path"]
        )
        after = sha256(path)
        protected_results.append(
            {
                "protected_scope": row["protected_scope"],
                "repository_relative_path": row["repository_relative_path"],
                "sha256_before": row["sha256_before"],
                "sha256_after": after,
                "unchanged": after == row["sha256_before"],
            }
        )
    protected = pd.DataFrame(protected_results)
    bus_protected = protected[
        protected["protected_scope"].isin(
            ["bus_scope_direction_audit_v1", "bus_fare_v1"]
        )
    ]
    check_1 = (
        len(
            protected[
                protected["protected_scope"] == "bus_scope_direction_audit_v1"
            ]
        )
        == 23
        and len(
            protected[protected["protected_scope"] == "bus_fare_v1"]
        )
        == 21
        and bus_protected["unchanged"].all()
    )
    prior_scopes = (
        "mtr_station_od_v1",
        "light_rail_station_od_v1",
        "ferry_fare_v1",
        "gmb_fare_v1",
    )
    check_27 = all(
        len(protected[protected["protected_scope"] == scope]) > 0
        and protected[protected["protected_scope"] == scope]["unchanged"].all()
        for scope in prior_scopes
    )
    matsim = protected[
        protected["protected_scope"] == "matsim_protected_input"
    ]
    check_28 = len(matsim) == 8 and matsim["unchanged"].all()
    production = pd.read_parquet(
        repo_root / BASE_REL / "pt_passenger_trip_fare_audit.parquet",
        columns=["cost_hkd", "mapping_status", "cost_quality"],
    )
    check_29 = (
        len(production) == 557_104
        and production["cost_hkd"].isna().all()
        and (production["mapping_status"] == "unresolved").all()
        and (production["cost_quality"] == "U").all()
    )
    status_lines = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    allowed_prefixes = (
        "data/transport_costs/hongkong/pt_fare_v1/bus_fare_simulation_v1/",
        "scripts/hong_kong_single_city/costs/pt/"
        "build_hong_kong_bus_simulation_fares.py",
        "scripts/hong_kong_single_city/costs/pt/"
        "quote_hong_kong_bus_simulation_fares.py",
        "scripts/hong_kong_single_city/costs/pt/"
        "validate_hong_kong_bus_simulation_fares.py",
        "docs/HONG_KONG_PT_FARE_MODEL.md",
    )
    changed_paths = [line[3:].replace("\\", "/") for line in status_lines]
    check_30 = all(
        any(path.startswith(prefix) for prefix in allowed_prefixes)
        for path in changed_paths
    ) and bool(check_28)
    check_31 = not has_absolute_path(output_dir)
    rebuild_ok, digest_1, digest_2, differences = rebuild_matches_current(
        repo_root, source_root, output_dir
    )
    check_32 = rebuild_ok

    scripts = [
        repo_root
        / "scripts/hong_kong_single_city/costs/pt/"
        "build_hong_kong_bus_simulation_fares.py",
        repo_root
        / "scripts/hong_kong_single_city/costs/pt/"
        "quote_hong_kong_bus_simulation_fares.py",
        Path(__file__).resolve(),
    ]
    syntax_ok = all(
        subprocess.run(
            [sys.executable, "-m", "py_compile", str(script)],
            cwd=repo_root,
            capture_output=True,
            text=True,
        ).returncode
        == 0
        for script in scripts
    )
    parquet_ok = all(
        len(pq.ParquetFile(output_dir / name).schema_arrow.names) > 0
        for name in (
            "bus_simulation_fare_rules.parquet",
            "bus_simulation_fare_anomalies.parquet",
        )
    )
    json_ok = all(
        isinstance(
            json.loads((output_dir / name).read_text(encoding="utf-8")), dict
        )
        for name in (
            "bus_simulation_fare_summary.json",
            "bus_simulation_fare_validation.json",
        )
    )
    csv_ok = all(
        len(pd.read_csv(output_dir / name)) > 0
        for name in (
            "bus_route_fallback_fares.csv",
            "bus_fare_resolution_method_summary.csv",
            "bus_fare_resolution_quality_summary.csv",
            "bus_simulation_query_fixture_input.csv",
            "bus_simulation_query_fixture_output.csv",
            "protected_hashes.csv",
        )
    )
    diff_ok = (
        subprocess.run(
            ["git", "diff", "--check"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        ).returncode
        == 0
    )
    check_33 = syntax_ok and parquet_ok and json_ok and csv_ok and diff_ok and not missing_files

    checks = [
        ("01_bus_audit_and_bus_core_v1_unchanged", bool(check_1)),
        ("02_each_of_771666_required_ODs_has_exactly_one_rule", check_2),
        ("03_model_and_cost_fares_all_non_null", check_3),
        ("04_cost_hkd_equals_model_fare_hkd", check_4),
        ("05_754133_active_rules_exactly_match_bus_core", check_5),
        ("06_1827_confirmed_duplicates_use_common_amount", check_6),
        ("07_2603_confirmed_conflicts_follow_selection_algorithm", check_7),
        ("08_2074_scope_unresolved_unique_use_direct_gtfs", check_8),
        ("09_34_scope_unresolved_duplicates_use_consensus", check_9),
        ("10_10836_other_service_unique_use_direct_gtfs", check_10),
        ("11_139_other_service_duplicates_use_consensus", check_11),
        ("12_20_other_service_conflicts_follow_algorithm", check_12),
        ("13_conflict_selection_never_leaves_candidate_set", check_13),
        ("14_conflicts_retain_min_max_spread_and_all_record_ids", check_14),
        ("15_637_active_unique_zeros_preserved", check_15),
        ("16_no_fallback_or_resolution_invents_zero", check_16),
        ("17_five_operator_unresolved_routes_have_fallbacks", check_17),
        ("18_all_2363_routes_have_fallbacks", check_18),
        ("19_route_fallback_priority_strictly_executed", check_19),
        ("20_exact_OD_query_precedes_route_fallback", check_20),
        ("21_known_route_unknown_OD_returns_fallback", check_21),
        ("22_only_unknown_route_returns_unresolved", check_22),
        ("23_all_simulation_assumptions_are_anomalies", check_23),
        ("24_no_cost_quality_A", check_24),
        ("25_B_C_D_match_resolution_methods", check_25),
        ("26_all_fixture_cases_pass", check_26),
        ("27_mtr_light_rail_ferry_gmb_unchanged", bool(check_27)),
        ("28_eight_protected_matsim_inputs_unchanged", bool(check_28)),
        ("29_production_pt_audit_unchanged", check_29),
        ("30_no_plans_config_java_scoring_network_schedule_vehicle_change", check_30),
        ("31_outputs_contain_no_absolute_paths", check_31),
        ("32_complete_build_and_fixture_query_byte_identical", check_32),
        ("33_python_csv_json_parquet_and_git_diff_checks_pass", check_33),
    ]
    validation = {
        "schema_version": "hong_kong_bus_simulation_fare_validation_v1",
        "status": "passed" if all(value for _, value in checks) else "failed",
        "checks": [{"name": name, "passed": bool(value)} for name, value in checks],
        "independent_counts": {
            "required_OD_rules": len(rules),
            "non_null_model_fares": int((rules["model_fare_hkd"] != "").sum()),
            "route_fallbacks": len(fallbacks),
            "quality_counts": dict(Counter(rules["cost_quality"])),
            "resolution_method_counts": dict(
                Counter(rules["fare_resolution_method"])
            ),
            "conflict_method_counts": dict(conflict_method_counts),
            "active_unique_zero_rules": active_zero,
            "duplicate_consensus_zero_rules": duplicate_zero,
            "explicit_zero_rules": zero_rules,
            "ordered_OD_anomalies": int(rules["anomaly_flag"].sum()),
            "anomaly_table_rows": len(anomalies),
            "anomaly_priority_counts": {
                str(key): int(value)
                for key, value in sorted(Counter(anomalies["audit_priority"]).items())
            },
            "fixture_cases": len(fixture_input),
            "fixture_passed": fixture_passed,
            "production_pt_rows": len(production),
        },
        "unmatched_route_fallbacks": unmatched[
            [
                "matsim_route_id",
                "route_fallback_fare_hkd",
                "fallback_level",
                "fare_resolution_method",
            ]
        ].to_dict("records"),
        "fixture_results": fixture_details,
        "protected_hash_results": protected_results,
        "rebuild_determinism": {
            "passed": rebuild_ok,
            "current_build_query_overall_sha256": digest_1,
            "rebuilt_build_query_overall_sha256": digest_2,
            "different_files": differences,
        },
        "summary_consistency": {
            "model_fare_coverage": summary["model_fare_coverage"],
            "route_fallback_coverage": summary["route_fallback_coverage"],
        },
        "missing_required_files": missing_files,
    }
    validation_path = output_dir / "bus_simulation_fare_validation.json"
    validation_path.write_text(
        json.dumps(validation, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    checksum_paths = sorted(
        path
        for path in output_dir.iterdir()
        if path.is_file() and path.name != "SHA256SUMS.txt"
    )
    (output_dir / "SHA256SUMS.txt").write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in checksum_paths),
        encoding="utf-8",
    )
    passed = sum(bool(value) for _, value in checks)
    print(
        f"Bus simulation fare validation {validation['status']}: "
        f"{passed}/{len(checks)}"
    )
    print(f"Build/query overall SHA256: {digest_1}")
    failed = [name for name, value in checks if not value]
    if failed:
        print("Failed checks: " + ", ".join(failed))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
