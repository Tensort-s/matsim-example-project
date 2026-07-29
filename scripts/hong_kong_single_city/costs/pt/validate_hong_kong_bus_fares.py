#!/usr/bin/env python3
"""Independently validate Hong Kong franchised-bus fare Core v1 outputs."""

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
from typing import Any
from xml.etree import ElementTree as ET

import pandas as pd
import pyarrow.parquet as pq


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
AUDIT_REL = BASE_REL / "bus_scope_direction_audit_v1"
OUTPUT_REL = BASE_REL / "bus_fare_v1"
EXPECTED_ACTIVE = 754_133
EXPECTED_CONFIRMED_PAIRS = 758_563
EXPECTED_TOTAL = 771_666
EXPECTED_EXCLUDED = 17_533
KNOWN_UNMATCHED = {
    "bus_1000004_1",
    "bus_1000004_2",
    "bus_1000611_1",
    "bus_8780_1",
    "bus_8780_2",
}
UNSPECIFIED_SOURCE = "unspecified_in_source"
UNSPECIFIED_REQUEST = "unspecified"
REVISION_STATUS = "not_encoded_in_source_revision_cutoff_only"


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


def normalize_identifier(value: Any) -> str:
    text = str(value).strip()
    try:
        number = float(text)
    except ValueError:
        return text
    return str(int(number)) if number.is_integer() else text


def forward_pairs(stops: list[str]) -> list[tuple[str, str]]:
    return sorted(
        {
            (stops[i], stops[j])
            for i in range(len(stops))
            for j in range(i + 1, len(stops))
            if stops[i] and stops[j] and stops[i] != stops[j]
        }
    )


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
            refs: list[str] = []
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
            if mode == "bus":
                official_route_id, suffix = route_parts(route.attrib["id"])
                routes.append(
                    {
                        "matsim_line_id": line.attrib["id"],
                        "matsim_route_id": route.attrib["id"],
                        "official_route_id": official_route_id,
                        "matsim_route_suffix": suffix,
                        "stops": [stop_id_from_facility(ref) for ref in refs],
                    }
                )
    return sorted(
        routes, key=lambda row: (row["matsim_line_id"], row["matsim_route_id"])
    )


def source_record(
    rule: dict[str, str], attr: dict[str, str], source_sha: str
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
        "fare_attributes_source_file": (
            f"{GTFS_REL.as_posix()}::fare_attributes.txt"
        ),
        "source_sha256": source_sha,
    }


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


def expected_quote(
    request: dict[str, str],
    readiness: dict[str, dict[str, str]],
    active_lookup: dict[tuple[str, ...], dict[str, Any]],
    unresolved_lookup: dict[tuple[str, ...], dict[str, Any]],
    route_stops: dict[str, set[str]],
    full_routes: set[str],
) -> tuple[str, str, float | None]:
    route_id = request.get("matsim_route_id", "")
    route = readiness.get(route_id)
    if request.get("actual_transport_mode") != "bus":
        return "unresolved", "actual_transport_mode_must_be_bus", None
    if not request.get("matsim_line_id"):
        return "unresolved", "missing_required_matsim_line_id", None
    if not route_id:
        return "unresolved", "missing_required_matsim_route_id", None
    if route is None:
        return "unresolved", "unknown_matsim_route_id", None
    if request["matsim_line_id"] != route["matsim_line_id"]:
        return "unresolved", "matsim_line_route_combination_mismatch", None
    scope = route["route_franchise_scope_status"]
    if scope != "confirmed_franchised_route":
        reason = (
            "route_scope_unresolved_no_official_direction_or_stop_pair"
            if scope == "operator_scope_unresolved"
            else scope
        )
        return "unresolved", reason, None
    if not request.get("official_route_id"):
        return "unresolved", "missing_required_official_route_id", None
    if request["official_route_id"] != route["official_route_id"]:
        return "unresolved", "official_route_id_mismatch", None
    direction = request.get("official_direction", "")
    if not direction:
        return "unresolved", "missing_required_official_direction", None
    if direction in {"unspecified", "unspecified_in_source"}:
        return "unresolved", "official_direction_must_be_exact", None
    if direction != route["official_route_sequence"]:
        return "unresolved", "official_direction_mismatch", None
    if not request.get("boarding_stop_id"):
        return "unresolved", "missing_required_boarding_stop_id", None
    if not request.get("alighting_stop_id"):
        return "unresolved", "missing_required_alighting_stop_id", None
    if request.get("travel_date"):
        return (
            "unresolved",
            "fare_effective_period_not_encoded_for_travel_date",
            None,
        )
    if request.get("temporal_basis") != "source_snapshot_only":
        return "unresolved", "temporal_basis_must_be_source_snapshot_only", None
    source_dimensions = {
        "passenger_type": "passenger_type_not_proven_by_source",
        "payment_medium": "payment_medium_not_proven_by_source",
        "service_class": "service_class_not_proven_by_source",
        "day_type": "day_type_not_proven_by_source",
        "time_period": "time_period_not_proven_by_source",
    }
    for field, reason in source_dimensions.items():
        if request.get(field) != UNSPECIFIED_REQUEST:
            return "unresolved", reason, None
    if request.get("transfer_concession_requested", "").lower() != "false":
        return (
            "unresolved",
            "transfer_concession_not_modelled_request_rejected",
            None,
        )
    key = (
        request["matsim_line_id"],
        route_id,
        request["official_route_id"],
        direction,
        request["boarding_stop_id"],
        request["alighting_stop_id"],
    )
    if key in active_lookup:
        return "available", "", float(active_lookup[key]["published_fare_hkd"])
    if key in unresolved_lookup:
        return "unresolved", unresolved_lookup[key]["exclusion_reason"], None
    if (
        request["boarding_stop_id"] == request["alighting_stop_id"]
        and request["official_route_id"] in full_routes
    ):
        return "unresolved", "fullfare_fallback_prohibited", None
    stops = route_stops.get(route_id, set())
    if request["boarding_stop_id"] not in stops:
        return "unresolved", "boarding_stop_not_in_route", None
    if request["alighting_stop_id"] not in stops:
        return "unresolved", "alighting_stop_not_in_route", None
    return "unresolved", "ordered_stop_pair_not_available_no_reverse_fallback", None


def artifact_hashes(directory: Path) -> dict[str, str]:
    excluded = {"bus_fare_validation.json", "SHA256SUMS.txt"}
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
        / "scripts/hong_kong_single_city/costs/pt/build_hong_kong_bus_fares.py"
    )
    query = (
        repo_root
        / "scripts/hong_kong_single_city/costs/pt/quote_hong_kong_bus_fares.py"
    )
    current = artifact_hashes(output_dir)
    with tempfile.TemporaryDirectory(prefix="hk_bus_fare_rebuild_") as temp:
        rebuilt = Path(temp) / "bus_fare_v1"
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
                str(rebuilt / "bus_fare_query_fixture_input.csv"),
                "--output",
                str(rebuilt / "bus_fare_query_fixture_output.csv"),
                "--rules",
                str(rebuilt / "bus_fare_rules.parquet"),
                "--unresolved",
                str(rebuilt / "bus_unresolved_fare_rules.parquet"),
                "--readiness",
                str(rebuilt / "bus_route_direction_fare_readiness.csv"),
                "--full-fare-reference",
                str(rebuilt / "bus_route_full_fare_reference.csv"),
            ],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        second = artifact_hashes(rebuilt)
    current_digest = hashlib.sha256(compact_json(current).encode()).hexdigest()
    rebuilt_digest = hashlib.sha256(compact_json(second).encode()).hexdigest()
    differences = sorted(
        name
        for name in set(current) | set(second)
        if current.get(name) != second.get(name)
    )
    return current == second, current_digest, rebuilt_digest, differences


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-project-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[4]
    source_root = args.source_project_root.resolve()
    output_dir = (args.output_dir or repo_root / OUTPUT_REL).resolve()
    audit_dir = repo_root / AUDIT_REL

    expected_files = {
        "README.md",
        "SHA256SUMS.txt",
        "bus_fare_rules.parquet",
        "bus_fare_rules_sample.csv",
        "bus_unresolved_fare_rules.parquet",
        "bus_unresolved_fare_rules_sample.csv",
        "bus_fare_conflicts.parquet",
        "bus_fare_conflicts_sample.csv",
        "bus_fare_duplicate_records.parquet",
        "bus_fare_duplicate_records_sample.csv",
        "bus_excluded_scope_pairs.parquet",
        "bus_excluded_scope_pairs_sample.csv",
        "bus_unresolved_routes.csv",
        "bus_route_direction_fare_readiness.csv",
        "bus_route_full_fare_reference.csv",
        "bus_fare_semantics_summary.json",
        "bus_fare_summary.json",
        "bus_fare_query_fixture_input.csv",
        "bus_fare_query_fixture_output.csv",
        "bus_fare_validation.json",
        "protected_hashes.csv",
    }
    present_files = {path.name for path in output_dir.iterdir() if path.is_file()}
    missing_files = sorted(expected_files - present_files)

    gtfs_path = source_root / GTFS_REL
    source_hashes = {
        "gtfs": sha256(gtfs_path),
        "bus_json": sha256(source_root / JSON_REL),
        "franchised_bus_geometry": sha256(source_root / GEOMETRY_REL),
        "revision": sha256(source_root / REVISION_REL),
        "schedule": sha256(source_root / SCHEDULE_REL),
    }
    with zipfile.ZipFile(gtfs_path) as archive:
        attrs = read_zip_csv(archive, "fare_attributes.txt")
        raw_rules = read_zip_csv(archive, "fare_rules.txt")
    attrs_by_id = {row["fare_id"]: row for row in attrs}
    attrs_by_line = {int(row["_line_number"]): row for row in attrs}
    rules_by_line = {int(row["_line_number"]): row for row in raw_rules}

    raw_json = json.loads(
        (source_root / JSON_REL).read_text(encoding="utf-8-sig")
    )
    json_properties = [
        feature.get("properties") or {} for feature in raw_json["features"]
    ]
    json_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in json_properties:
        json_groups[
            (
                normalize_identifier(item["routeId"]),
                normalize_identifier(item["routeSeq"]),
                str(item["companyCode"]).strip(),
            )
        ].append(item)
    json_patterns = {
        key: [
            str(item["stopId"])
            for item in sorted(rows, key=lambda value: int(value["stopSeq"]))
        ]
        for key, rows in json_groups.items()
    }
    json_operators = {key[2] for key in json_patterns}

    geometry = json.loads(
        (source_root / GEOMETRY_REL).read_text(encoding="utf-8")
    )
    csdi_keys: set[tuple[str, str, str]] = set()
    for feature in geometry["features"]:
        item = feature.get("properties") or {}
        csdi_keys.add(
            (
                str(item.get("COMPANY_CODE", "")).strip(),
                normalize_identifier(item.get("ROUTE_ID", "")),
                normalize_identifier(item.get("ROUTE_SEQ", "")),
            )
        )
    franchised_operators = {key[0] for key in csdi_keys if key[0]}
    schedule = read_schedule(source_root / SCHEDULE_REL)

    audit_summary = json.loads(
        (audit_dir / "bus_scope_direction_summary.json").read_text(
            encoding="utf-8"
        )
    )
    audit_candidates = pd.read_parquet(
        audit_dir / "bus_od_fare_candidate_audit.parquet"
    ).fillna("")
    audit_evidence = pd.read_csv(
        audit_dir / "bus_route_franchise_scope_evidence.csv",
        dtype=str,
        keep_default_na=False,
    )
    audit_direction = pd.read_csv(
        audit_dir / "bus_direction_evidence_audit.csv",
        dtype=str,
        keep_default_na=False,
    )
    evidence_by_route = audit_evidence.set_index("matsim_route_id").to_dict("index")
    direction_by_route = audit_direction.set_index("matsim_route_id").to_dict("index")

    route_meta: dict[str, dict[str, Any]] = {}
    all_required_keys: set[tuple[str, str, str]] = set()
    for route in schedule:
        matches = [
            key
            for key, pattern in json_patterns.items()
            if key[0] == route["official_route_id"] and pattern == route["stops"]
        ]
        operator = matches[0][2] if len(matches) == 1 else ""
        operator_scope = (
            "confirmed_franchised_operator"
            if operator in franchised_operators
            else "other_bus_operator"
            if operator in json_operators
            else "operator_scope_unresolved"
        )
        csdi_key = (
            (operator, matches[0][0], matches[0][1])
            if len(matches) == 1
            else ("", route["official_route_id"], "")
        )
        scope = (
            "confirmed_franchised_route"
            if operator_scope == "confirmed_franchised_operator"
            and csdi_key in csdi_keys
            else "franchise_route_scope_unresolved"
            if operator_scope == "confirmed_franchised_operator"
            else "other_bus_service"
            if operator_scope == "other_bus_operator"
            else "operator_scope_unresolved"
        )
        pairs = forward_pairs(route["stops"])
        route_meta[route["matsim_route_id"]] = {
            **route,
            "matches": matches,
            "operator": operator,
            "operator_scope": operator_scope,
            "csdi_key": csdi_key,
            "scope": scope,
            "pairs": pairs,
        }
        all_required_keys.update(
            (route["official_route_id"], origin, destination)
            for origin, destination in pairs
        )

    raw_lookup: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for rule in raw_rules:
        attr = attrs_by_id.get(rule["fare_id"])
        if attr is None:
            continue
        key = (rule["route_id"], rule["origin_id"], rule["destination_id"])
        if key in all_required_keys:
            raw_lookup[key].append(source_record(rule, attr, source_hashes["gtfs"]))
    for records in raw_lookup.values():
        records.sort(key=lambda row: (row["fare_rule_line"], row["fare_id"]))

    independent_scope_counts: Counter[str] = Counter()
    independent_status_counts: Counter[str] = Counter()
    independent_scope_status: dict[str, Counter[str]] = defaultdict(Counter)
    independent_zero_by_reason: Counter[str] = Counter()
    independent_pair_rows: dict[
        tuple[str, str, str], tuple[str, str, list[dict[str, Any]]]
    ] = {}
    for route in schedule:
        meta = route_meta[route["matsim_route_id"]]
        independent_scope_counts[meta["scope"]] += 1
        for origin, destination in meta["pairs"]:
            records = raw_lookup.get(
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
            independent_status_counts[status] += 1
            independent_scope_status[meta["scope"]][status] += 1
            independent_pair_rows[
                (route["matsim_route_id"], origin, destination)
            ] = (meta["scope"], status, records)
            reason = (
                "confirmed_route_duplicate_identical"
                if meta["scope"] == "confirmed_franchised_route"
                and status == "duplicate_identical"
                else "confirmed_route_conflicting_amounts"
                if meta["scope"] == "confirmed_franchised_route"
                and status == "conflicting_amounts"
                else "franchise_route_scope_unresolved"
                if meta["scope"] == "franchise_route_scope_unresolved"
                else "other_bus_service_excluded"
                if meta["scope"] == "other_bus_service"
                else ""
            )
            if reason:
                independent_zero_by_reason[reason] += sum(
                    record["price"] == 0 for record in records
                )

    active = pd.read_parquet(output_dir / "bus_fare_rules.parquet").fillna("")
    unresolved = pd.read_parquet(
        output_dir / "bus_unresolved_fare_rules.parquet"
    ).fillna("")
    conflicts = pd.read_parquet(output_dir / "bus_fare_conflicts.parquet").fillna("")
    duplicates = pd.read_parquet(
        output_dir / "bus_fare_duplicate_records.parquet"
    ).fillna("")
    excluded_scope = pd.read_parquet(
        output_dir / "bus_excluded_scope_pairs.parquet"
    ).fillna("")
    unresolved_routes = pd.read_csv(
        output_dir / "bus_unresolved_routes.csv",
        dtype=str,
        keep_default_na=False,
    )
    readiness = pd.read_csv(
        output_dir / "bus_route_direction_fare_readiness.csv",
        dtype=str,
        keep_default_na=False,
    )
    full_refs = pd.read_csv(
        output_dir / "bus_route_full_fare_reference.csv",
        dtype=str,
        keep_default_na=False,
    )
    fixture_input = pd.read_csv(
        output_dir / "bus_fare_query_fixture_input.csv",
        dtype=str,
        keep_default_na=False,
    )
    fixture_output = pd.read_csv(
        output_dir / "bus_fare_query_fixture_output.csv",
        dtype=str,
        keep_default_na=False,
    )
    summary = json.loads(
        (output_dir / "bus_fare_summary.json").read_text(encoding="utf-8")
    )
    semantics = json.loads(
        (output_dir / "bus_fare_semantics_summary.json").read_text(
            encoding="utf-8"
        )
    )

    confirmed_pair_count = sum(
        len(meta["pairs"])
        for meta in route_meta.values()
        if meta["scope"] == "confirmed_franchised_route"
    )
    check_1 = source_hashes == {
        key: summary["source_sha256"][key] for key in source_hashes
    } and source_hashes == {
        key: audit_summary["source_sha256"][key] for key in source_hashes
    }
    check_2 = True
    check_3 = True
    for route_id, meta in route_meta.items():
        evidence = evidence_by_route[route_id]
        direction = direction_by_route[route_id]
        check_2 &= (
            evidence["route_franchise_scope_status"] == meta["scope"]
            and (
                meta["scope"] != "confirmed_franchised_route"
                or (
                    len(meta["matches"]) == 1
                    and meta["csdi_key"] in csdi_keys
                    and evidence["csdi_exact_key_match"] == "True"
                )
            )
        )
        check_3 &= (
            int(direction["candidate_count"]) == len(meta["matches"])
            and direction["current_direction_status"]
            == ("exact" if len(meta["matches"]) == 1 else "unresolved")
            and (
                direction["official_json_stop_ids_json"]
                == compact_json(json_patterns[meta["matches"][0]])
                if len(meta["matches"]) == 1
                else direction["official_json_stop_ids_json"] == ""
            )
        )
    check_4 = confirmed_pair_count == EXPECTED_CONFIRMED_PAIRS
    check_5 = len(active) == EXPECTED_ACTIVE
    primary_key = [
        "matsim_line_id",
        "matsim_route_id",
        "official_route_id",
        "official_direction",
        "boarding_stop_id",
        "alighting_stop_id",
        "passenger_type",
        "payment_medium",
        "service_class",
        "day_type",
        "time_period",
    ]
    check_6 = not active.duplicated(primary_key).any()

    active_trace_ok = True
    active_scope_ok = True
    active_zero = 0
    for row in active.to_dict("records"):
        key = (
            row["matsim_route_id"],
            row["boarding_stop_id"],
            row["alighting_stop_id"],
        )
        independent = independent_pair_rows.get(key)
        records = json.loads(row["candidate_records_json"])
        active_scope_ok &= (
            independent is not None
            and independent[0] == "confirmed_franchised_route"
            and independent[1] == "unique_candidate"
            and route_meta[row["matsim_route_id"]]["operator_scope"]
            == "confirmed_franchised_operator"
            and len(route_meta[row["matsim_route_id"]]["matches"]) == 1
            and row["official_direction"]
            == route_meta[row["matsim_route_id"]]["matches"][0][1]
            and int(row["candidate_count"]) == 1
            and int(row["distinct_amount_count"]) == 1
        )
        if len(records) != 1:
            active_trace_ok = False
            continue
        record = records[0]
        raw_rule = rules_by_line.get(int(record["fare_rule_line"]))
        raw_attr = attrs_by_line.get(int(record["fare_attribute_line"]))
        source_ids = json.loads(row["source_record_ids_json"])
        active_trace_ok &= bool(
            raw_rule
            and raw_attr
            and raw_rule["fare_id"] == record["fare_id"]
            and raw_rule["route_id"] == row["official_route_id"]
            and raw_rule["origin_id"] == row["boarding_stop_id"]
            and raw_rule["destination_id"] == row["alighting_stop_id"]
            and raw_attr["fare_id"] == record["fare_id"]
            and float(raw_attr["price"]) == float(row["published_fare_hkd"])
            and raw_attr["currency_type"] == "HKD"
            and row["currency"] == "HKD"
            and row["source_sha256"] == source_hashes["gtfs"]
            and len(source_ids) == 1
            and int(source_ids[0]["fare_rule_line"])
            == int(record["fare_rule_line"])
            and int(source_ids[0]["fare_attribute_line"])
            == int(record["fare_attribute_line"])
            and source_ids[0]["fare_id"] == record["fare_id"]
        )
        active_zero += float(row["published_fare_hkd"]) == 0
    check_7 = bool(active_scope_ok)
    check_8 = bool(active_trace_ok)
    check_9 = (
        set(active["record_status"]) == {"available"}
        and set(active["route_franchise_scope_status"])
        == {"confirmed_franchised_route"}
        and not set(active["matsim_route_id"]).intersection(
            set(
                unresolved_routes[
                    unresolved_routes["route_franchise_scope_status"].isin(
                        [
                            "franchise_route_scope_unresolved",
                            "operator_scope_unresolved",
                        ]
                    )
                ]["matsim_route_id"]
            )
        )
    )
    reason_counts = Counter(unresolved["exclusion_reason"])
    check_10 = (
        len(unresolved) == EXPECTED_EXCLUDED
        and set(unresolved["unresolved_reason"]) == set(reason_counts)
        and unresolved["unresolved_reason"].equals(unresolved["exclusion_reason"])
    )
    check_11 = len(active) + len(unresolved) == EXPECTED_TOTAL
    check_12 = (
        reason_counts["confirmed_route_duplicate_identical"] == 1_827
        and len(duplicates) == 1_827
        and not set(duplicates["matsim_route_id"]).difference(
            set(unresolved["matsim_route_id"])
        )
    )
    check_13 = (
        reason_counts["confirmed_route_conflicting_amounts"] == 2_603
        and len(conflicts) == 2_603
    )
    scope_unresolved_routes = unresolved_routes[
        unresolved_routes["route_franchise_scope_status"]
        == "franchise_route_scope_unresolved"
    ]
    check_14 = (
        len(scope_unresolved_routes) == 9
        and reason_counts["franchise_route_scope_unresolved"] == 2_108
        and len(
            excluded_scope[
                excluded_scope["exclusion_reason"]
                == "franchise_route_scope_unresolved"
            ]
        )
        == 2_108
    )
    other_route_count = independent_scope_counts["other_bus_service"]
    check_15 = (
        other_route_count == 103
        and reason_counts["other_bus_service_excluded"] == 10_995
        and len(
            excluded_scope[
                excluded_scope["exclusion_reason"] == "other_bus_service_excluded"
            ]
        )
        == 10_995
    )
    unmatched = unresolved_routes[
        unresolved_routes["route_franchise_scope_status"]
        == "operator_scope_unresolved"
    ]
    check_16 = len(unmatched) == 5 and set(unmatched["matsim_route_id"]) == KNOWN_UNMATCHED
    check_17 = (
        active_zero == 637
        and summary["active_unique_zero_rule_count"] == active_zero
        and independent_zero_by_reason["confirmed_route_duplicate_identical"] == 10
        and independent_zero_by_reason["confirmed_route_conflicting_amounts"] == 0
        and independent_zero_by_reason["franchise_route_scope_unresolved"] == 0
        and independent_zero_by_reason["other_bus_service_excluded"] == 0
        and summary["raw_zero_candidate_record_count_total"] == 647
    )
    check_18 = (
        not active["published_fare_hkd"].isna().any()
        and not (active["published_fare_hkd"] < 0).any()
        and (unresolved["cost_hkd"] == "").all()
        and not (
            (unresolved["candidate_count"].astype(int) == 0)
            & (unresolved["published_fare_hkd"] == 0)
        ).any()
    )
    check_19 = (
        "reverse" not in ";".join(active["matching_method"]).lower()
        and summary.get("reverse_od_fallback_used", False) is False
    )
    forbidden_tokens = (
        "distance",
        "interpolation",
        "path_sum",
        "adjacent_sum",
        "minimum",
        "maximum",
        "median",
        "mean",
        "first_candidate",
    )
    methods = ";".join(active["matching_method"]).lower()
    check_20 = all(token not in methods for token in forbidden_tokens)
    check_21 = (
        (full_refs["eligible_for_default_quote"] == "False").all()
        and summary["full_fare_reference_in_active_rules"] is False
        and "full_fare_hkd" not in active.columns
        and "fullFare" not in methods
    )
    revision_rows = list(
        csv.reader((source_root / REVISION_REL).open(encoding="utf-8-sig", newline=""))
    )
    revision_cutoff = revision_rows[1][0].strip()
    check_22 = (active["cost_effective_date"] == "").all()
    check_23 = (
        revision_cutoff == "2026-07-14"
        and (active["source_revision_cutoff_date"] == revision_cutoff).all()
        and (active["cost_effective_date_status"] == REVISION_STATUS).all()
        and semantics["cost_effective_date"] == ""
        and semantics["cost_effective_date_status"] == REVISION_STATUS
    )
    check_24 = (
        set(active["cost_quality"]) == {"B"}
        and "A" not in set(active["cost_quality"])
        and set(active["mapping_quality"]) == {"A"}
    )
    check_25 = (
        (unresolved["cost_hkd"] == "").all()
        and set(unresolved["cost_quality"]) == {"U"}
        and set(unresolved["mapping_status"]) == {"unresolved"}
        and set(unresolved["mapping_quality"]) == {"U"}
    )

    readiness_lookup = readiness.set_index("matsim_route_id").to_dict("index")
    active_key_columns = [
        "matsim_line_id",
        "matsim_route_id",
        "official_route_id",
        "official_direction",
        "boarding_stop_id",
        "alighting_stop_id",
    ]
    active_lookup = {
        tuple(str(row[column]) for column in active_key_columns): row
        for row in active.to_dict("records")
    }
    unresolved_lookup = {
        tuple(str(row[column]) for column in active_key_columns): row
        for row in unresolved.to_dict("records")
    }
    route_stops = {
        route_id: set(meta["stops"]) for route_id, meta in route_meta.items()
    }
    full_routes = set(full_refs["official_route_id"])
    output_by_quote = fixture_output.set_index("quote_id").to_dict("index")
    fixture_ok = len(fixture_input) == len(fixture_output) >= 25
    fixture_passed = 0
    fixture_details: list[dict[str, Any]] = []
    for request in fixture_input.to_dict("records"):
        expected_status, expected_reason, expected_cost = expected_quote(
            request,
            readiness_lookup,
            active_lookup,
            unresolved_lookup,
            route_stops,
            full_routes,
        )
        actual = output_by_quote.get(request["quote_id"])
        passed = bool(
            actual
            and request["expected_result"] == expected_status
            and actual["unresolved_reason"] == expected_reason
            and (
                (
                    expected_status == "available"
                    and float(actual["cost_hkd"]) == expected_cost
                    and float(actual["published_fare_hkd"]) == expected_cost
                    and actual["cost_quality"] == "B"
                    and actual["mapping_status"] == "exact"
                    and actual["mapping_quality"] == "A"
                )
                or (
                    expected_status == "unresolved"
                    and actual["cost_hkd"] == ""
                    and actual["published_fare_hkd"] == ""
                    and actual["cost_quality"] == "U"
                    and actual["mapping_status"] == "unresolved"
                    and actual["mapping_quality"] == "U"
                )
            )
        )
        fixture_ok &= passed
        fixture_passed += passed
        fixture_details.append(
            {
                "quote_id": request["quote_id"],
                "expected_result": expected_status,
                "expected_unresolved_reason": expected_reason,
                "passed": passed,
            }
        )
    required_fixture_ids = {
        "available_nonzero_operator_1",
        "available_nonzero_operator_2",
        "available_joint_operator",
        "available_unique_zero",
        "confirmed_duplicate",
        "confirmed_conflict",
        "franchise_scope_unresolved_unique",
        "other_bus_service",
        "known_unmatched_route",
        "same_direction_reverse_not_substituted",
        "independent_reverse_route_available",
        "official_route_mismatch",
        "line_route_mismatch",
        "direction_unspecified",
        "direction_wrong",
        "boarding_unknown",
        "alighting_unknown",
        "travel_date_nonempty",
        "temporal_basis_wrong",
        "passenger_adult",
        "payment_octopus",
        "service_class_specific",
        "transfer_requested",
        "fullfare_fallback_rejected",
        "missing_required_line",
    }
    fixture_ok &= required_fixture_ids.issubset(set(fixture_input["quote_id"]))
    check_26 = bool(fixture_ok)
    check_27 = (
        (fixture_output["transfer_concession_hkd"] == "").all()
        and (fixture_output["transfer_concession_status"] == "not_modelled").all()
        and summary["transfer_concession_status"] == "not_modelled"
    )

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
        protected["protected_scope"] == "bus_scope_direction_audit_v1"
    ]
    check_28 = len(bus_protected) > 0 and bus_protected["unchanged"].all()
    prior_scopes = (
        "mtr_station_od_v1",
        "light_rail_station_od_v1",
        "ferry_fare_v1",
        "gmb_fare_v1",
    )
    check_29 = all(
        len(protected[protected["protected_scope"] == scope]) > 0
        and protected[protected["protected_scope"] == scope]["unchanged"].all()
        for scope in prior_scopes
    )
    matsim_protected = protected[
        protected["protected_scope"] == "matsim_protected_input"
    ]
    check_30 = (
        len(matsim_protected) == 8 and matsim_protected["unchanged"].all()
    )
    production = pd.read_parquet(
        repo_root / BASE_REL / "pt_passenger_trip_fare_audit.parquet",
        columns=["cost_hkd", "mapping_status", "cost_quality"],
    )
    check_31 = (
        len(production) == 557_104
        and production["cost_hkd"].isna().all()
        and (production["mapping_status"] == "unresolved").all()
        and (production["cost_quality"] == "U").all()
    )
    check_32 = not has_absolute_path(output_dir)
    rebuild_ok, digest_1, digest_2, rebuild_differences = rebuild_matches_current(
        repo_root, source_root, output_dir
    )
    check_33 = rebuild_ok

    scripts = [
        repo_root
        / "scripts/hong_kong_single_city/costs/pt/build_hong_kong_bus_fares.py",
        repo_root
        / "scripts/hong_kong_single_city/costs/pt/quote_hong_kong_bus_fares.py",
        Path(__file__).resolve(),
    ]
    syntax_ok = True
    for script in scripts:
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(script)],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        syntax_ok &= result.returncode == 0
    diff_check = subprocess.run(
        ["git", "diff", "--check"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    parquet_schema_ok = all(
        len(pq.ParquetFile(output_dir / name).schema_arrow.names) > 0
        for name in (
            "bus_fare_rules.parquet",
            "bus_unresolved_fare_rules.parquet",
            "bus_fare_conflicts.parquet",
            "bus_fare_duplicate_records.parquet",
            "bus_excluded_scope_pairs.parquet",
        )
    )
    checksums = {}
    for line in (output_dir / "SHA256SUMS.txt").read_text(
        encoding="utf-8"
    ).splitlines():
        digest, name = line.split("  ", 1)
        checksums[name] = digest
    checksum_names = {
        path.name
        for path in output_dir.iterdir()
        if path.is_file() and path.name != "SHA256SUMS.txt"
    }
    checksum_schema_ok = checksum_names == set(checksums)
    check_34 = (
        syntax_ok
        and parquet_schema_ok
        and checksum_schema_ok
        and not missing_files
        and diff_check.returncode == 0
    )

    checks = [
        ("01_raw_source_sha256_verified", check_1),
        ("02_route_level_csdi_exact_keys_independently_verified", check_2),
        ("03_complete_json_direction_stop_sequences_independently_verified", check_3),
        ("04_confirmed_route_forward_pairs_equal_758563", check_4),
        ("05_active_rules_equal_754133", check_5),
        ("06_active_rule_primary_key_globally_unique", check_6),
        ("07_every_active_rule_confirmed_exact_and_unique", check_7),
        ("08_every_active_amount_equals_unique_raw_gtfs_price", check_8),
        ("09_active_excludes_duplicate_conflict_other_and_unresolved", check_9),
        ("10_all_17533_nonactive_pairs_retained_with_reasons", check_10),
        ("11_active_plus_unresolved_equals_771666", check_11),
        ("12_confirmed_duplicate_1827_not_published", check_12),
        ("13_confirmed_conflict_2603_not_published", check_13),
        ("14_nine_scope_unresolved_routes_2108_pairs_excluded", check_14),
        ("15_other_service_103_routes_10995_pairs_excluded", check_15),
        ("16_five_known_unmatched_routes_remain_unresolved", check_16),
        ("17_raw_zero_missing_and_unresolved_distinguished", check_17),
        ("18_no_missing_value_filled_with_zero", check_18),
        ("19_no_reverse_od_fallback", check_19),
        ("20_no_distance_interpolation_path_sum_or_candidate_aggregation", check_20),
        ("21_fullfare_never_enters_active_rules", check_21),
        ("22_cost_effective_date_empty", check_22),
        ("23_revision_cutoff_not_used_as_fare_effective_date", check_23),
        ("24_available_cost_quality_B_and_never_A", check_24),
        ("25_unresolved_cost_null_quality_U", check_25),
        ("26_every_fixture_expected_result_matches_query", check_26),
        ("27_transfer_concession_null_and_not_modelled", check_27),
        ("28_prior_bus_scope_direction_audit_unchanged", bool(check_28)),
        ("29_mtr_light_rail_ferry_gmb_directories_unchanged", bool(check_29)),
        ("30_eight_protected_matsim_inputs_unchanged", bool(check_30)),
        ("31_production_557104_pt_audit_still_null_unresolved_U", check_31),
        ("32_outputs_contain_no_absolute_paths", check_32),
        ("33_complete_build_and_fixture_query_byte_identical", check_33),
        ("34_syntax_schema_checksum_and_git_diff_check_pass", check_34),
    ]
    validation = {
        "schema_version": "hong_kong_bus_fare_validation_v1",
        "status": "passed" if all(value for _, value in checks) else "failed",
        "checks": [{"name": name, "passed": bool(value)} for name, value in checks],
        "independent_counts": {
            "schedule_bus_route_count": len(schedule),
            "route_scope_counts": dict(independent_scope_counts),
            "candidate_status_counts": dict(independent_status_counts),
            "scope_candidate_status_counts": {
                scope: dict(counts)
                for scope, counts in independent_scope_status.items()
            },
            "confirmed_route_forward_pairs": confirmed_pair_count,
            "active_rules": len(active),
            "active_unique_zero_rules": active_zero,
            "unresolved_excluded_pairs": len(unresolved),
            "exclusion_reason_counts": dict(reason_counts),
            "fixture_cases": len(fixture_input),
            "fixture_passed": fixture_passed,
            "production_pt_rows": len(production),
        },
        "source_sha256": source_hashes,
        "fixture_results": fixture_details,
        "protected_hash_results": protected_results,
        "rebuild_determinism": {
            "passed": rebuild_ok,
            "current_build_query_overall_sha256": digest_1,
            "rebuilt_build_query_overall_sha256": digest_2,
            "different_files": rebuild_differences,
        },
        "missing_required_files": missing_files,
    }
    validation_path = output_dir / "bus_fare_validation.json"
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
    print(f"Bus fare validation {validation['status']}: {passed}/{len(checks)}")
    print(f"Build/query overall SHA256: {digest_1}")
    failed = [name for name, value in checks if not value]
    if failed:
        print("Failed checks: " + ", ".join(failed))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
