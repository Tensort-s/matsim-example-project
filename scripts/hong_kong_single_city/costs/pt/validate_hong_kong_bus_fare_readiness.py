#!/usr/bin/env python3
"""Independently validate Hong Kong bus scope and fare-readiness audit outputs."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterator
from xml.etree import ElementTree as ET

import pandas as pd
import pyarrow.parquet as pq


UNSPECIFIED = "unspecified_in_source"
REVISION_STATUS = "not_encoded_in_source_revision_cutoff_only"
GTFS_REL = Path("data/transit/hongkong/PublicTransportGTFS/gtfs.zip")
JSON_REL = Path(
    "data/transit/hongkong/API_Supplements/static/"
    "routes_fares_route_stop_points/bus_route_stop_points.json"
)
REVISION_REL = JSON_REL.parent / "routes_fares_last_updated.csv"
GEOMETRY_REL = Path(
    "data/transit/hongkong/API_Supplements/geometry/franchised_bus_routes.geojson"
)
SCHEDULE_REL = Path(
    "data/transit/hongkong/processed/"
    "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_"
    "ferry_core_v1_cap010/transitSchedule_5pct.xml.gz"
)
BASE_REL = Path("data/transport_costs/hongkong/pt_fare_v1")
OUTPUT_REL = BASE_REL / "bus_scope_direction_audit_v1"
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


def stop_id_from_facility(facility_id: str) -> str:
    match = re.match(r"^pt_bus_(\d+)_", facility_id)
    return match.group(1) if match else ""


def route_parts(route_id: str) -> tuple[str, str]:
    match = re.match(r"^bus_(\d+)_([^_]+)", route_id)
    return (match.group(1), match.group(2)) if match else ("", "")


def forward_pairs(stops: list[str]) -> set[tuple[str, str]]:
    return {
        (stops[i], stops[j])
        for i in range(len(stops))
        for j in range(i + 1, len(stops))
        if stops[i] and stops[j] and stops[i] != stops[j]
    }


def read_zip_csv(archive: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    with archive.open(name) as raw:
        reader = csv.DictReader(
            io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        )
        rows: list[dict[str, str]] = []
        for line_number, row in enumerate(reader, 2):
            item = dict(row)
            item["_line_number"] = str(line_number)
            rows.append(item)
        return rows


def read_schedule(path: Path) -> tuple[list[dict[str, Any]], set[str]]:
    with gzip.open(path, "rb") as handle:
        root = ET.parse(handle).getroot()
    all_facilities = {
        element.attrib["id"]
        for element in root.iter()
        if local_name(element.tag) == "stopFacility"
    }
    rows: list[dict[str, Any]] = []
    for line in root:
        if local_name(line.tag) != "transitLine":
            continue
        for route in line:
            if local_name(route.tag) != "transitRoute":
                continue
            mode = ""
            refs: list[str] = []
            departures = 0
            for child in route:
                tag = local_name(child.tag)
                if tag == "transportMode":
                    mode = (child.text or "").strip()
                elif tag == "routeProfile":
                    refs = [
                        stop.attrib["refId"]
                        for stop in child
                        if local_name(stop.tag) == "stop"
                    ]
                elif tag == "departures":
                    departures = sum(
                        local_name(item.tag) == "departure" for item in child
                    )
            if mode == "bus":
                official, suffix = route_parts(route.attrib["id"])
                rows.append(
                    {
                        "matsim_line_id": line.attrib["id"],
                        "matsim_route_id": route.attrib["id"],
                        "official_route_id": official,
                        "suffix": suffix,
                        "refs": refs,
                        "stops": [stop_id_from_facility(ref) for ref in refs],
                        "departures": departures,
                    }
                )
    return (
        sorted(rows, key=lambda row: (row["matsim_line_id"], row["matsim_route_id"])),
        all_facilities,
    )


def source_record(
    rule: dict[str, str], attr: dict[str, str], gtfs_sha: str
) -> dict[str, Any]:
    return {
        "fare_id": rule["fare_id"],
        "fare_rule_line": int(rule["_line_number"]),
        "fare_attribute_line": int(attr["_line_number"]),
        "price": float(attr["price"]),
        "currency": attr["currency_type"],
        "route_id": rule["route_id"],
        "origin_id": rule["origin_id"],
        "destination_id": rule["destination_id"],
        "fare_rules_source_file": f"{GTFS_REL.as_posix()}::fare_rules.txt",
        "fare_attributes_source_file": f"{GTFS_REL.as_posix()}::fare_attributes.txt",
        "source_sha256": gtfs_sha,
    }


def expected_rows(
    schedule: list[dict[str, Any]],
    route_meta: dict[str, dict[str, Any]],
    lookup: dict[tuple[str, str, str], list[dict[str, Any]]],
) -> Iterator[tuple[dict[str, Any], str, str, list[dict[str, Any]], str]]:
    for route in schedule:
        meta = route_meta[route["matsim_route_id"]]
        for origin, destination in sorted(forward_pairs(route["stops"])):
            records = lookup.get(
                (route["official_route_id"], origin, destination), []
            )
            amounts = {record["price"] for record in records}
            status = (
                "missing"
                if not records
                else "unique_candidate"
                if len(records) == 1
                else "duplicate_identical"
                if len(amounts) == 1
                else "conflicting_amounts"
            )
            yield route, origin, destination, records, status


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


def rebuild_matches_current(
    repo_root: Path, source_root: Path, output_dir: Path
) -> tuple[bool, str, str]:
    audit = (
        repo_root
        / "scripts/hong_kong_single_city/costs/pt/"
        "audit_hong_kong_bus_fare_readiness.py"
    )
    current = {
        path.name: sha256(path)
        for path in sorted(output_dir.iterdir(), key=lambda item: item.name)
        if path.is_file()
    }
    with tempfile.TemporaryDirectory(prefix="hk_bus_audit_rebuild_") as temp:
        rebuilt = Path(temp) / "bus_scope_direction_audit_v1"
        subprocess.run(
            [
                sys.executable,
                str(audit),
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
        second = {
            path.name: sha256(path)
            for path in sorted(rebuilt.iterdir(), key=lambda item: item.name)
            if path.is_file()
        }
    first_digest = hashlib.sha256(compact_json(current).encode()).hexdigest()
    second_digest = hashlib.sha256(compact_json(second).encode()).hexdigest()
    return current == second, first_digest, second_digest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-project-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[4]
    source_root = args.source_project_root.resolve()
    output_dir = (args.output_dir or repo_root / OUTPUT_REL).resolve()

    expected_files = {
        "README.md",
        "bus_source_schema_audit.csv",
        "bus_fare_semantics_summary.json",
        "bus_operator_scope_audit.csv",
        "bus_route_scope_audit.csv",
        "bus_stop_crosswalk.csv",
        "bus_direction_evidence_audit.csv",
        "bus_route_direction_readiness.csv",
        "bus_od_fare_candidate_audit.parquet",
        "bus_od_fare_candidate_audit_sample.csv",
        "bus_od_conflicts.parquet",
        "bus_od_conflicts_sample.csv",
        "bus_od_duplicate_records.parquet",
        "bus_od_duplicate_records_sample.csv",
        "bus_missing_required_pairs.csv",
        "bus_route_full_fare_reference.csv",
        "bus_scope_direction_summary.json",
        "bus_scope_direction_validation.json",
        "prior_mode_protected_hashes.csv",
        "SHA256SUMS.txt",
    }
    present_files = {path.name for path in output_dir.iterdir() if path.is_file()}
    missing_files = sorted(expected_files - present_files)

    gtfs_path = source_root / GTFS_REL
    gtfs_sha = sha256(gtfs_path)
    with zipfile.ZipFile(gtfs_path) as archive:
        gtfs = {
            name: read_zip_csv(archive, name)
            for name in (
                "agency.txt",
                "routes.txt",
                "stops.txt",
                "fare_attributes.txt",
                "fare_rules.txt",
            )
        }
    raw_json = json.loads((source_root / JSON_REL).read_text(encoding="utf-8-sig"))
    json_props = [feature.get("properties") or {} for feature in raw_json["features"]]
    geometry = json.loads((source_root / GEOMETRY_REL).read_text(encoding="utf-8"))
    geometry_props = [
        feature.get("properties") or {} for feature in geometry["features"]
    ]
    franchised_codes = {
        str(item["COMPANY_CODE"]) for item in geometry_props if item.get("COMPANY_CODE")
    }
    json_codes = {str(item["companyCode"]) for item in json_props}
    gtfs_stops = {row["stop_id"] for row in gtfs["stops.txt"]}
    json_stop_ids = {str(item["stopId"]) for item in json_props}
    agency_by_id = {row["agency_id"]: row for row in gtfs["agency.txt"]}

    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in json_props:
        groups[
            (str(item["routeId"]), str(item["routeSeq"]), str(item["companyCode"]))
        ].append(item)
    patterns = {
        key: [
            str(item["stopId"])
            for item in sorted(values, key=lambda value: int(value["stopSeq"]))
        ]
        for key, values in groups.items()
    }
    schedule, _ = read_schedule(source_root / SCHEDULE_REL)
    route_meta: dict[str, dict[str, Any]] = {}
    required_keys: set[tuple[str, str, str]] = set()
    for route in schedule:
        matches = [
            key
            for key, pattern in patterns.items()
            if key[0] == route["official_route_id"] and pattern == route["stops"]
        ]
        operator = matches[0][2] if len(matches) == 1 else ""
        scope = (
            "confirmed_franchised_bus"
            if operator in franchised_codes
            else "other_bus_service"
            if operator in json_codes
            else "operator_scope_unresolved"
        )
        route_meta[route["matsim_route_id"]] = {
            "matches": matches,
            "operator": operator,
            "scope": scope,
        }
        required_keys.update(
            (route["official_route_id"], origin, destination)
            for origin, destination in forward_pairs(route["stops"])
        )

    attrs = [
        row
        for row in gtfs["fare_attributes.txt"]
        if row["agency_id"] in json_codes
    ]
    attr_by_id = {row["fare_id"]: row for row in attrs}
    raw_rules = [
        row for row in gtfs["fare_rules.txt"] if row["fare_id"] in attr_by_id
    ]
    lookup: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for rule in raw_rules:
        key = (rule["route_id"], rule["origin_id"], rule["destination_id"])
        if key in required_keys:
            lookup[key].append(
                source_record(rule, attr_by_id[rule["fare_id"]], gtfs_sha)
            )
    for values in lookup.values():
        values.sort(key=lambda row: (row["fare_rule_line"], row["fare_id"]))

    operator = pd.read_csv(
        output_dir / "bus_operator_scope_audit.csv", dtype=str, keep_default_na=False
    )
    route_scope = pd.read_csv(
        output_dir / "bus_route_scope_audit.csv", dtype=str, keep_default_na=False
    )
    crosswalk = pd.read_csv(
        output_dir / "bus_stop_crosswalk.csv", dtype=str, keep_default_na=False
    )
    direction = pd.read_csv(
        output_dir / "bus_direction_evidence_audit.csv",
        dtype=str,
        keep_default_na=False,
    )
    readiness = pd.read_csv(
        output_dir / "bus_route_direction_readiness.csv",
        dtype=str,
        keep_default_na=False,
    )
    full_refs = pd.read_csv(
        output_dir / "bus_route_full_fare_reference.csv",
        dtype=str,
        keep_default_na=False,
    )
    schema = pd.read_csv(
        output_dir / "bus_source_schema_audit.csv",
        dtype=str,
        keep_default_na=False,
    )
    summary = json.loads(
        (output_dir / "bus_scope_direction_summary.json").read_text(encoding="utf-8")
    )
    semantics = json.loads(
        (output_dir / "bus_fare_semantics_summary.json").read_text(encoding="utf-8")
    )

    # 1-5: complete schedule and operator-scope classification.
    independent_schedule = {
        "line_count": len({row["matsim_line_id"] for row in schedule}),
        "route_count": len(schedule),
        "departure_count": sum(row["departures"] for row in schedule),
        "stop_occurrence_count": sum(len(row["refs"]) for row in schedule),
        "distinct_facility_count": len({ref for row in schedule for ref in row["refs"]}),
        "distinct_official_stop_id_count": len(
            {stop for row in schedule for stop in row["stops"] if stop}
        ),
    }
    check_1 = summary["schedule"] == independent_schedule
    route_ids = {row["matsim_route_id"] for row in schedule}
    check_2 = (
        len(route_scope) == len(schedule)
        and len(readiness) == len(schedule)
        and set(route_scope["matsim_route_id"]) == route_ids
        and set(readiness["matsim_route_id"]) == route_ids
    )
    expected_scope_counts = Counter(meta["scope"] for meta in route_meta.values())
    check_3 = (
        Counter(route_scope["operator_scope_status"]) == expected_scope_counts
        and summary["operator_scope_status_counts"] == dict(expected_scope_counts)
        and all(
            row["operator_scope_status"]
            == (
                "confirmed_franchised_bus"
                if row["official_operator_code"] in franchised_codes
                else "other_bus_service"
                if row["official_operator_code"]
                else "operator_scope_unresolved"
            )
            for row in operator.to_dict("records")
        )
        and all(
            agency_by_id[code]["agency_name"]
            for code in json_codes
            if code in agency_by_id
        )
    )
    check_4 = all(
        json.loads(row["official_operator_components_json"])
        == row["official_operator"].split("+")
        for row in route_scope.to_dict("records")
        if "+" in row["official_operator"]
    ) and all(
        json.loads(row["official_operator_components_json"])
        == row["official_operator_code"].split("+")
        for row in operator.to_dict("records")
        if "+" in row["official_operator_code"]
    )
    unresolved_scope = route_scope[
        route_scope["operator_scope_status"] == "operator_scope_unresolved"
    ]
    check_5 = (
        set(unresolved_scope["matsim_route_id"]) == KNOWN_UNMATCHED
        and (unresolved_scope["known_unmatched_route"] == "True").all()
    )

    # 6-9: stop and direction evidence.
    usage_refs = {ref for route in schedule for ref in route["refs"]}
    crosswalk_lookup = crosswalk.set_index("matsim_stop_facility_id").to_dict("index")
    check_6 = set(crosswalk_lookup) == usage_refs
    for ref in usage_refs:
        stop = stop_id_from_facility(ref)
        exact = bool(stop and stop in gtfs_stops and stop in json_stop_ids)
        row = crosswalk_lookup[ref]
        check_6 &= (
            row["official_stop_id"] == stop
            and row["mapping_status"] == ("exact" if exact else "unresolved")
            and row["candidate_count"] == ("1" if exact else "0")
        )
    check_7 = all(
        token not in ";".join(crosswalk["matching_method"]).lower()
        for token in ("fuzzy", "nearest", "coordinate", "terminal_name")
    )
    direction_lookup = direction.set_index("matsim_route_id").to_dict("index")
    check_8 = len(direction) == len(schedule)
    check_9 = True
    for route in schedule:
        meta = route_meta[route["matsim_route_id"]]
        row = direction_lookup[route["matsim_route_id"]]
        exact = len(meta["matches"]) == 1
        check_8 &= (
            int(row["candidate_count"]) == len(meta["matches"])
            and row["current_direction_status"] == ("exact" if exact else "unresolved")
            and (
                row["official_json_stop_ids_json"]
                == compact_json(patterns[meta["matches"][0]])
                if exact
                else row["official_json_stop_ids_json"] == ""
            )
        )
        check_9 &= (
            row["matsim_route_suffix"] == route["suffix"]
            and row["matsim_route_suffix_used_as_direction_evidence"] == "False"
            and "suffix" not in row["direction_evidence"].lower()
        )

    # 10-15: independently reproduce every ordered-OD candidate record.
    parquet = pq.ParquetFile(output_dir / "bus_od_fare_candidate_audit.parquet")
    output_columns = set(parquet.schema_arrow.names)
    expected = expected_rows(schedule, route_meta, lookup)
    candidate_total = 0
    status_counts: Counter[str] = Counter()
    zero_records = 0
    check_10 = True
    check_11 = True
    check_12 = True
    check_13 = True
    check_14 = True
    check_15 = True
    for batch in parquet.iter_batches(batch_size=20_000):
        for row in batch.to_pylist():
            try:
                route, origin, destination, records, status = next(expected)
            except StopIteration:
                check_10 = False
                break
            candidate_total += 1
            status_counts[status] += 1
            expected_zero = sum(record["price"] == 0 for record in records)
            zero_records += expected_zero
            check_10 &= (
                row["matsim_line_id"] == route["matsim_line_id"]
                and row["matsim_route_id"] == route["matsim_route_id"]
                and row["boarding_stop_id"] == origin
                and row["alighting_stop_id"] == destination
            )
            check_11 &= (
                int(row["candidate_count"]) == len(records)
                and row["candidate_records_json"] == compact_json(records)
                and row["source_sha256"] == gtfs_sha
            )
            check_12 &= (
                row["record_status"] == status
                and int(row["distinct_amount_count"])
                == len({record["price"] for record in records})
            )
            check_13 &= (
                int(row["explicit_raw_zero_candidate_record_count"]) == expected_zero
                and (row["contains_explicit_raw_zero_candidate"] is True)
                == (expected_zero > 0)
                and not (status == "missing" and expected_zero)
            )
            check_14 &= (
                row["matching_method"]
                == "exact_route_id_and_ordered_stop_od_candidate_audit"
                and row["boarding_stop_id"] == origin
                and row["alighting_stop_id"] == destination
            )
            method = row["matching_method"].lower()
            check_15 &= all(
                token not in method
                for token in (
                    "distance",
                    "nearest",
                    "interpolation",
                    "path_sum",
                    "adjacent_sum",
                    "minimum",
                    "median",
                    "first_candidate",
                )
            )
    try:
        next(expected)
        check_10 = False
    except StopIteration:
        pass
    independently_required = sum(len(forward_pairs(route["stops"])) for route in schedule)
    check_10 &= candidate_total == independently_required
    check_12 &= summary["candidate_status_counts"] == dict(status_counts)
    check_13 &= (
        summary["explicit_raw_zero_candidate_record_count"] == zero_records
    )
    check_14 &= summary["prohibited_methods_used"]["reverse_od_substitution"] is False
    check_15 &= all(
        value is False for value in summary["prohibited_methods_used"].values()
    )

    # 16-19: fullFare, source semantics, time, and no query/pricing layer.
    check_16 = (
        len(full_refs) == len(patterns)
        and (full_refs["eligible_for_default_quote"] == "False").all()
        and summary["full_fare_reference_in_candidate_selection"] is False
        and "full_fare_hkd" not in output_columns
    )
    forbidden_schema = {"adult_octopus_fare_hkd", "adult_base_fare_hkd", "cost_hkd"}
    check_17 = (
        not forbidden_schema.intersection(output_columns)
        and semantics["answers"]["gtfs_price_passenger_payment_ticket_scope"]
        == UNSPECIFIED
        and all(
            semantics["answers"][key] == UNSPECIFIED
            for key in (
                "fare_rules_direction_route_sequence_day_time",
                "bus_json_per_stop_or_sectional_fare",
                "fullFare_unconditional_flat_fare",
                "route_specific_fare_effective_date",
            )
        )
        and not forbidden_schema.intersection(set(schema["field_name"]))
    )
    revision_rows = list(
        csv.reader((source_root / REVISION_REL).open(encoding="utf-8-sig", newline=""))
    )
    revision = revision_rows[1][0].strip()
    check_18 = (
        revision == summary["source_revision_cutoff_date"]
        and summary["cost_effective_date"] == ""
        and summary["cost_effective_date_status"] == REVISION_STATUS
        and semantics["cost_effective_date"] == ""
        and semantics["travel_date_eligibility"] == "not_performed"
    )
    check_19 = (
        not (repo_root / "scripts/hong_kong_single_city/costs/pt/quote_hong_kong_bus_fares.py").exists()
        and summary["query_interface_created"] is False
        and summary["production_pricing_performed"] is False
        and summary["matsim_scoring_integration"] == "not_performed"
        and "cost_hkd" not in output_columns
        and not has_absolute_path(output_dir)
        and not missing_files
    )

    # 20-22: production audit and protected hashes.
    production = pd.read_parquet(
        repo_root / BASE_REL / "pt_passenger_trip_fare_audit.parquet",
        columns=["cost_hkd", "mapping_status", "cost_quality"],
    )
    check_20 = (
        len(production) == 557_104
        and production["cost_hkd"].isna().all()
        and (production["mapping_status"] == "unresolved").all()
        and (production["cost_quality"] == "U").all()
    )
    prior = pd.read_csv(
        output_dir / "prior_mode_protected_hashes.csv",
        dtype=str,
        keep_default_na=False,
    )
    protected_results: list[dict[str, Any]] = []
    for row in prior.to_dict("records"):
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
    check_21 = all(
        len(protected[protected["protected_scope"] == scope]) > 0
        and protected[protected["protected_scope"] == scope]["unchanged"].all()
        for scope in (
            "mtr_station_od_v1",
            "light_rail_station_od_v1",
            "ferry_fare_v1",
            "gmb_fare_v1",
        )
    )
    matsim = protected[protected["protected_scope"] == "matsim_protected_input"]
    check_22 = len(matsim) == 8 and matsim["unchanged"].all()

    # 23: a fresh complete audit must be byte-identical.
    rebuild_ok, rebuild_digest_1, rebuild_digest_2 = rebuild_matches_current(
        repo_root, source_root, output_dir
    )
    check_23 = rebuild_ok
    checks = [
        ("01_schedule_inventory_directly_recomputed", check_1),
        ("02_one_scope_and_readiness_row_per_bus_route", check_2),
        ("03_operator_scope_has_official_evidence", check_3),
        ("04_joint_operator_relationship_retained", check_4),
        ("05_five_known_unmatched_routes_explicit", check_5),
        ("06_facility_stop_id_mapping_directly_verified", check_6),
        ("07_no_fuzzy_or_nearest_stop_matching", check_7),
        ("08_direction_requires_unique_complete_official_pattern", check_8),
        ("09_matsim_route_suffix_not_direction_evidence", check_9),
        ("10_required_forward_pairs_independently_recomputed", check_10),
        ("11_every_candidate_traces_to_raw_gtfs", check_11),
        ("12_unique_duplicate_conflict_missing_classification_true", check_12),
        ("13_explicit_raw_zero_separate_from_missing", check_13),
        ("14_no_reverse_od_substitution", check_14),
        ("15_no_interpolation_path_sum_or_candidate_selection", check_15),
        ("16_fullfare_reference_never_enters_candidate_selection", check_16),
        ("17_passenger_payment_semantics_not_invented", check_17),
        ("18_revision_cutoff_not_fare_effective_date", check_18),
        ("19_no_bus_query_or_production_pricing", check_19),
        ("20_production_557104_remain_null_unresolved", check_20),
        ("21_prior_mode_directories_unchanged", bool(check_21)),
        ("22_eight_matsim_inputs_unchanged", bool(check_22)),
        ("23_independent_complete_audit_byte_identical", check_23),
    ]
    validation = {
        "schema_version": "hong_kong_bus_scope_direction_validation_v1",
        "status": "passed" if all(value for _, value in checks) else "failed",
        "checks": [{"name": name, "passed": bool(value)} for name, value in checks],
        "independent_counts": {
            "schedule": independent_schedule,
            "operator_scope_status_counts": dict(expected_scope_counts),
            "required_forward_pairs": independently_required,
            "candidate_status_counts": dict(status_counts),
            "explicit_raw_zero_candidate_records": zero_records,
            "direction_status_counts": dict(
                Counter(
                    "exact" if len(meta["matches"]) == 1 else "unresolved"
                    for meta in route_meta.values()
                )
            ),
            "stop_crosswalk_status_counts": dict(Counter(crosswalk["mapping_status"])),
            "full_fare_references": len(full_refs),
            "production_pt_rows": len(production),
        },
        "source_sha256": {
            "gtfs": gtfs_sha,
            "bus_json": sha256(source_root / JSON_REL),
            "revision": sha256(source_root / REVISION_REL),
            "schedule": sha256(source_root / SCHEDULE_REL),
            "franchised_bus_geometry": sha256(source_root / GEOMETRY_REL),
        },
        "protected_hash_results": protected_results,
        "rebuild_determinism": {
            "passed": rebuild_ok,
            "current_overall_sha256": rebuild_digest_1,
            "rebuilt_overall_sha256": rebuild_digest_2,
        },
        "missing_required_files": missing_files,
    }
    validation_path = output_dir / "bus_scope_direction_validation.json"
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
    print(f"Bus fare-readiness validation {validation['status']}: {passed}/{len(checks)}")
    failed = [name for name, value in checks if not value]
    if failed:
        print("Failed checks: " + ", ".join(failed))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
