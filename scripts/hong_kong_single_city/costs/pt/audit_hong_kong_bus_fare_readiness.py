#!/usr/bin/env python3
"""Audit Hong Kong bus operator scope, direction evidence, and OD fare readiness."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import re
import zipfile
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


UNSPECIFIED = "unspecified_in_source"
DOWNLOAD_DATE = "2026-07-20"
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

CANDIDATE_COLUMNS = [
    "matsim_line_id",
    "matsim_route_id",
    "service_scope",
    "operator_scope_status",
    "official_operator",
    "official_operator_components_json",
    "official_route_id",
    "official_route_sequence",
    "official_direction",
    "boarding_stop_id",
    "alighting_stop_id",
    "candidate_count",
    "distinct_amount_count",
    "candidate_fare_ids_json",
    "candidate_amounts_hkd_json",
    "candidate_record_ids_json",
    "candidate_records_json",
    "explicit_raw_zero_candidate_record_count",
    "contains_explicit_raw_zero_candidate",
    "record_status",
    "fare_amount_role",
    "passenger_type",
    "payment_medium",
    "day_type",
    "time_period",
    "cost_effective_date",
    "cost_effective_date_status",
    "source_revision_cutoff_date",
    "source_download_date",
    "source_file",
    "source_sha256",
    "matching_method",
    "mapping_status",
    "mapping_quality",
    "selection_performed",
    "production_cost_created",
    "unresolved_reason",
]


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


def read_schedule(path: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    with gzip.open(path, "rb") as handle:
        root = ET.parse(handle).getroot()
    facilities: dict[str, dict[str, str]] = {}
    for element in root.iter():
        if local_name(element.tag) == "stopFacility":
            facilities[element.attrib["id"]] = {
                "name": element.attrib.get("name", ""),
                "x": element.attrib.get("x", ""),
                "y": element.attrib.get("y", ""),
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
            if mode != "bus":
                continue
            official, suffix = route_parts(route.attrib["id"])
            rows.append(
                {
                    "matsim_line_id": line.attrib["id"],
                    "matsim_route_id": route.attrib["id"],
                    "official_route_id": official,
                    "matsim_route_suffix": suffix,
                    "stop_refs": refs,
                    "stop_ids": [stop_id_from_facility(ref) for ref in refs],
                    "departure_count": departures,
                }
            )
    return sorted(rows, key=lambda row: (row["matsim_line_id"], row["matsim_route_id"])), facilities


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    frame.to_parquet(path, index=False, engine="pyarrow", compression="zstd")


class BatchedParquetWriter:
    def __init__(self, path: Path, columns: list[str], batch_size: int = 20_000):
        self.path = path
        self.columns = columns
        self.batch_size = batch_size
        self.rows: list[dict[str, Any]] = []
        self.writer: pq.ParquetWriter | None = None

    def add(self, row: dict[str, Any]) -> None:
        self.rows.append(row)
        if len(self.rows) >= self.batch_size:
            self.flush()

    def flush(self) -> None:
        if not self.rows:
            return
        frame = pd.DataFrame(self.rows, columns=self.columns)
        table = pa.Table.from_pandas(frame, preserve_index=False)
        if self.writer is None:
            self.writer = pq.ParquetWriter(
                self.path,
                table.schema,
                compression="zstd",
                version="2.6",
                write_statistics=True,
            )
        else:
            table = table.cast(self.writer.schema)
        self.writer.write_table(table)
        self.rows.clear()

    def close(self) -> None:
        self.flush()
        if self.writer is None:
            empty = pa.Table.from_pandas(
                pd.DataFrame(columns=self.columns), preserve_index=False
            )
            pq.write_table(empty, self.path, compression="zstd", version="2.6")
        else:
            self.writer.close()


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


def schema_audit(
    gtfs: dict[str, list[dict[str, str]]],
    json_props: list[dict[str, Any]],
    geometry_props: list[dict[str, Any]],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    semantic: dict[tuple[str, str], tuple[str, str, str]] = {
        ("fare_attributes.txt", "price"): (
            "published_numeric_amount_only",
            UNSPECIFIED,
            "adult/child, cash/Octopus, ticket type, full/sectional scope not encoded",
        ),
        ("fare_attributes.txt", "payment_method"): (
            "GTFS_payment_timing_code_not_payment_medium",
            UNSPECIFIED,
            "does not identify cash or Octopus",
        ),
        ("fare_rules.txt", "route_id"): (
            "official_route_identifier_without_direction",
            "encoded",
            "",
        ),
        ("fare_rules.txt", "origin_id"): ("ordered_boarding_stop_id", "encoded", ""),
        ("fare_rules.txt", "destination_id"): (
            "ordered_alighting_stop_id",
            "encoded",
            "",
        ),
        ("bus_route_stop_points.json", "companyCode"): (
            "official_operator_code",
            "encoded",
            "joint operation is retained in the complete plus-delimited code",
        ),
        ("bus_route_stop_points.json", "routeSeq"): (
            "official_route_sequence",
            "encoded",
            "direction is exact only after a unique complete stop-pattern match",
        ),
        ("bus_route_stop_points.json", "stopSeq"): (
            "ordered_stop_position",
            "encoded",
            "",
        ),
        ("bus_route_stop_points.json", "stopId"): ("official_stop_id", "encoded", ""),
        ("bus_route_stop_points.json", "fullFare"): (
            "route_sequence_full_fare_reference_only",
            "reference_only",
            "flat-fare, passenger, payment, and effective-period conditions not proven",
        ),
        ("bus_route_stop_points.json", "lastUpdateDate"): (
            "record_update_timestamp_not_fare_effective_date",
            "provenance_only",
            "",
        ),
        ("franchised_bus_routes.geojson", "COMPANY_CODE"): (
            "operator_code_in_official_franchised_bus_geometry_layer",
            "encoded",
            "",
        ),
        ("franchised_bus_routes.geojson", "ROUTE_SEQ"): (
            "official_geometry_route_sequence",
            "encoded",
            "not used in place of complete route-stop pattern evidence",
        ),
    }
    tables: list[tuple[str, list[dict[str, Any]]]] = [
        (name, list(values))
        for name, values in gtfs.items()
    ] + [
        ("bus_route_stop_points.json", json_props),
        ("franchised_bus_routes.geojson", geometry_props),
    ]
    for table, values in tables:
        fields = sorted(
            {key for value in values[:1000] for key in value if key != "_line_number"}
        )
        for field in fields:
            meaning, status, limitation = semantic.get(
                (table, field),
                ("source_identification_description_or_provenance", "reference_only", ""),
            )
            rows.append(
                {
                    "source_table": table,
                    "field_name": field,
                    "field_present": True,
                    "distinct_nonblank_sample_count": len(
                        {
                            str(value.get(field, ""))
                            for value in values[:1000]
                            if value.get(field, "") not in ("", None)
                        }
                    ),
                    "audited_meaning": meaning,
                    "semantic_status": status,
                    "limitation": limitation,
                }
            )
    for question in (
        "price_adult_child",
        "price_cash_octopus",
        "price_ticket_type_or_sectional_scope",
        "fare_rules_direction",
        "fare_rules_route_sequence",
        "fare_rules_day_or_time",
        "json_per_stop_or_section_fare",
        "json_unconditional_flat_fare",
        "route_specific_fare_effective_date",
    ):
        rows.append(
            {
                "source_table": "cross_source_question",
                "field_name": question,
                "field_present": False,
                "distinct_nonblank_sample_count": 0,
                "audited_meaning": UNSPECIFIED,
                "semantic_status": UNSPECIFIED,
                "limitation": "not encoded in the retained official source fields",
            }
        )
    return pd.DataFrame(rows)


def protected_hashes(repo_root: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for scope in (
        "mtr_station_od_v1",
        "light_rail_station_od_v1",
        "ferry_fare_v1",
        "gmb_fare_v1",
    ):
        relative = BASE_REL / scope
        for path in sorted((repo_root / relative).iterdir(), key=lambda item: item.name):
            if path.is_file():
                rows.append(
                    {
                        "protected_scope": scope,
                        "repository_relative_path": (relative / path.name).as_posix(),
                        "size_bytes": path.stat().st_size,
                        "sha256_before": sha256(path),
                    }
                )
    baseline = pd.read_csv(
        repo_root / BASE_REL / "protected_input_hashes_baseline.csv",
        dtype=str,
        keep_default_na=False,
    )
    for row in baseline.to_dict("records"):
        rows.append(
            {
                "protected_scope": "matsim_protected_input",
                "repository_relative_path": row["repository_relative_path"],
                "size_bytes": row["size_bytes"],
                "sha256_before": row["sha256_before"],
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-project-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[4]
    source_root = args.source_project_root.resolve()
    output_dir = (args.output_dir or repo_root / OUTPUT_REL).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    source_paths = {
        "gtfs": source_root / GTFS_REL,
        "bus_json": source_root / JSON_REL,
        "revision": source_root / REVISION_REL,
        "schedule": source_root / SCHEDULE_REL,
        "franchised_bus_geometry": source_root / GEOMETRY_REL,
    }
    source_hashes = {key: sha256(path) for key, path in source_paths.items()}
    revision_rows = list(
        csv.reader(source_paths["revision"].open(encoding="utf-8-sig", newline=""))
    )
    revision_cutoff = revision_rows[1][0].strip()
    date.fromisoformat(revision_cutoff)

    with zipfile.ZipFile(source_paths["gtfs"]) as archive:
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
    raw_json = json.loads(source_paths["bus_json"].read_text(encoding="utf-8-sig"))
    json_props = [feature.get("properties") or {} for feature in raw_json["features"]]
    raw_geometry = json.loads(
        source_paths["franchised_bus_geometry"].read_text(encoding="utf-8")
    )
    geometry_props = [
        feature.get("properties") or {} for feature in raw_geometry["features"]
    ]
    franchised_codes = {
        str(item["COMPANY_CODE"]) for item in geometry_props if item.get("COMPANY_CODE")
    }
    json_codes = {str(item["companyCode"]) for item in json_props}
    bus_agencies = json_codes
    agency_by_id = {row["agency_id"]: row for row in gtfs["agency.txt"]}
    gtfs_stops = {row["stop_id"] for row in gtfs["stops.txt"]}
    gtfs_routes = {row["route_id"]: row for row in gtfs["routes.txt"]}

    json_groups: dict[
        tuple[str, str, str], list[tuple[int, int, dict[str, Any]]]
    ] = defaultdict(list)
    for index, item in enumerate(json_props):
        key = (str(item["routeId"]), str(item["routeSeq"]), str(item["companyCode"]))
        json_groups[key].append((int(item["stopSeq"]), index, item))
    patterns = {
        key: [
            str(item["stopId"])
            for _, _, item in sorted(group, key=lambda value: value[0])
        ]
        for key, group in json_groups.items()
    }
    json_stop_ids = {str(item["stopId"]) for item in json_props}

    schedule, facilities = read_schedule(source_paths["schedule"])
    route_matches: dict[str, list[tuple[str, str, str]]] = {}
    route_meta: dict[str, dict[str, Any]] = {}
    required_keys: set[tuple[str, str, str]] = set()
    for route in schedule:
        candidates = [
            key
            for key, pattern in patterns.items()
            if key[0] == route["official_route_id"] and pattern == route["stop_ids"]
        ]
        route_matches[route["matsim_route_id"]] = candidates
        operator = candidates[0][2] if len(candidates) == 1 else ""
        scope = (
            "confirmed_franchised_bus"
            if operator in franchised_codes
            else "other_bus_service"
            if operator in json_codes
            else "operator_scope_unresolved"
        )
        pairs = forward_pairs(route["stop_ids"])
        route_meta[route["matsim_route_id"]] = {
            "operator": operator,
            "scope": scope,
            "pairs": pairs,
            "candidate_keys": candidates,
        }
        required_keys.update(
            (route["official_route_id"], origin, destination)
            for origin, destination in pairs
        )

    attrs = [
        row
        for row in gtfs["fare_attributes.txt"]
        if row["agency_id"] in bus_agencies
    ]
    attr_by_id = {row["fare_id"]: row for row in attrs}
    raw_rules = [
        row for row in gtfs["fare_rules.txt"] if row["fare_id"] in attr_by_id
    ]
    candidate_lookup: dict[
        tuple[str, str, str], list[dict[str, Any]]
    ] = defaultdict(list)
    for rule in raw_rules:
        key = (rule["route_id"], rule["origin_id"], rule["destination_id"])
        if key in required_keys:
            candidate_lookup[key].append(
                source_record(rule, attr_by_id[rule["fare_id"]], source_hashes["gtfs"])
            )
    for values in candidate_lookup.values():
        values.sort(key=lambda row: (row["fare_rule_line"], row["fare_id"]))

    operator_rows: list[dict[str, Any]] = []
    schedule_operator_counts = Counter(
        meta["operator"] for meta in route_meta.values()
    )
    json_pattern_counts = Counter(key[2] for key in patterns)
    geometry_pattern_counts = Counter(
        str(item.get("COMPANY_CODE", "")) for item in geometry_props
    )
    gtfs_route_counts = Counter(
        row["agency_id"]
        for row in gtfs["routes.txt"]
        if row["agency_id"] in bus_agencies
    )
    for operator in sorted(json_codes | {""}):
        components = operator.split("+") if operator else []
        scope = (
            "confirmed_franchised_bus"
            if operator in franchised_codes
            else "other_bus_service"
            if operator
            else "operator_scope_unresolved"
        )
        agency = agency_by_id.get(operator, {})
        operator_rows.append(
            {
                "official_operator_code": operator,
                "official_operator_components_json": compact_json(components),
                "joint_operation": len(components) > 1,
                "official_agency_name": agency.get("agency_name", ""),
                "official_agency_url": agency.get("agency_url", ""),
                "gtfs_route_count": gtfs_route_counts[operator],
                "json_route_pattern_count": json_pattern_counts[operator],
                "franchised_geometry_pattern_count": geometry_pattern_counts[operator],
                "schedule_route_count": schedule_operator_counts[operator],
                "operator_scope_status": scope,
                "service_scope": scope,
                "scope_evidence": (
                    "operator_code_present_in_official_CSDI_franchised_bus_geometry_layer"
                    if scope == "confirmed_franchised_bus"
                    else "official_GTFS_agency_name_and_bus_JSON_companyCode_identify_non_core_service"
                    if scope == "other_bus_service"
                    else "no_exact_official_bus_JSON_route_pattern_or_operator"
                ),
                "scope_evidence_source_file": (
                    GEOMETRY_REL.as_posix()
                    if scope == "confirmed_franchised_bus"
                    else f"{GTFS_REL.as_posix()}::agency.txt;{JSON_REL.as_posix()}"
                ),
                "scope_evidence_sha256": (
                    source_hashes["franchised_bus_geometry"]
                    if scope == "confirmed_franchised_bus"
                    else source_hashes["gtfs"] + ";" + source_hashes["bus_json"]
                ),
            }
        )
    operator_audit = pd.DataFrame(operator_rows)
    write_csv(operator_audit, output_dir / "bus_operator_scope_audit.csv")

    route_scope_rows: list[dict[str, Any]] = []
    direction_rows: list[dict[str, Any]] = []
    readiness_rows: list[dict[str, Any]] = []
    route_pair_counts: dict[str, Counter[str]] = defaultdict(Counter)

    candidate_writer = BatchedParquetWriter(
        output_dir / "bus_od_fare_candidate_audit.parquet", CANDIDATE_COLUMNS
    )
    sample_rows: list[dict[str, Any]] = []
    conflict_rows: list[dict[str, Any]] = []
    duplicate_rows: list[dict[str, Any]] = []
    missing_rows: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    explicit_zero_candidate_records = 0

    for route in schedule:
        route_id = route["matsim_route_id"]
        meta = route_meta[route_id]
        matches = meta["candidate_keys"]
        operator = meta["operator"]
        scope = meta["scope"]
        official_sequence = matches[0][1] if len(matches) == 1 else ""
        direction_status = "exact" if len(matches) == 1 else "unresolved"
        mapping_status = "exact" if len(matches) == 1 else "unresolved"
        mapping_quality = "A" if len(matches) == 1 else "U"
        components = operator.split("+") if operator else []
        route_scope_rows.append(
            {
                "matsim_line_id": route["matsim_line_id"],
                "matsim_route_id": route_id,
                "official_route_id": route["official_route_id"],
                "official_route_sequence": official_sequence,
                "official_operator": operator,
                "official_operator_components_json": compact_json(components),
                "joint_operation": len(components) > 1,
                "service_scope": scope,
                "operator_scope_status": scope,
                "route_identifier_status": (
                    "exact_official_route_id" if len(matches) == 1 else "route_unresolved"
                ),
                "json_pattern_candidate_count": len(matches),
                "known_unmatched_route": route_id in KNOWN_UNMATCHED,
                "scope_evidence": (
                    "exact_bus_JSON_route_pattern_plus_official_operator_scope"
                    if len(matches) == 1
                    else "no_exact_official_bus_JSON_route_pattern"
                ),
                "unresolved_reason": (
                    "" if len(matches) == 1 else "official_route_operator_and_stop_pattern_not_found"
                ),
            }
        )
        direction_rows.append(
            {
                "matsim_line_id": route["matsim_line_id"],
                "matsim_route_id": route_id,
                "official_route_id": route["official_route_id"],
                "official_operator": operator,
                "official_operator_components_json": compact_json(components),
                "json_route_id": matches[0][0] if len(matches) == 1 else "",
                "json_route_sequence": official_sequence,
                "matsim_route_suffix": route["matsim_route_suffix"],
                "matsim_route_suffix_used_as_direction_evidence": False,
                "matsim_stop_ids_json": compact_json(route["stop_ids"]),
                "official_json_stop_ids_json": (
                    compact_json(patterns[matches[0]]) if len(matches) == 1 else ""
                ),
                "candidate_count": len(matches),
                "operator_relationship_consistent": len(matches) == 1,
                "prior_direction_status": "direction_not_encoded",
                "current_direction_status": direction_status,
                "direction_evidence": (
                    "unique_complete_official_routeId_routeSeq_stopSeq_pattern"
                    if len(matches) == 1
                    else UNSPECIFIED
                ),
                "upgrade_reason": (
                    "complete_schedule_stop_sequence_uniquely_matches_official_JSON_pattern"
                    if len(matches) == 1
                    else ""
                ),
                "matching_method": (
                    "route_id_plus_unique_complete_official_ordered_stop_pattern"
                    if len(matches) == 1
                    else "no_official_pattern_match"
                ),
                "mapping_status": mapping_status,
                "mapping_quality": mapping_quality,
                "unresolved_reason": (
                    "" if len(matches) == 1 else "official_direction_pattern_not_found"
                ),
            }
        )
        for origin, destination in sorted(meta["pairs"]):
            records = candidate_lookup.get(
                (route["official_route_id"], origin, destination), []
            )
            amounts = sorted({record["price"] for record in records})
            status = (
                "missing"
                if not records
                else "unique_candidate"
                if len(records) == 1
                else "duplicate_identical"
                if len(amounts) == 1
                else "conflicting_amounts"
            )
            zero_count = sum(record["price"] == 0 for record in records)
            explicit_zero_candidate_records += zero_count
            status_counts[status] += 1
            route_pair_counts[route_id][status] += 1
            row = {
                "matsim_line_id": route["matsim_line_id"],
                "matsim_route_id": route_id,
                "service_scope": scope,
                "operator_scope_status": scope,
                "official_operator": operator,
                "official_operator_components_json": compact_json(components),
                "official_route_id": route["official_route_id"],
                "official_route_sequence": official_sequence,
                "official_direction": official_sequence,
                "boarding_stop_id": origin,
                "alighting_stop_id": destination,
                "candidate_count": len(records),
                "distinct_amount_count": len(amounts),
                "candidate_fare_ids_json": compact_json(
                    [record["fare_id"] for record in records]
                ),
                "candidate_amounts_hkd_json": compact_json(
                    [record["price"] for record in records]
                ),
                "candidate_record_ids_json": compact_json(
                    [
                        f"gtfs:fare_rules:{record['fare_rule_line']};"
                        f"fare_attributes:{record['fare_attribute_line']}"
                        for record in records
                    ]
                ),
                "candidate_records_json": compact_json(records),
                "explicit_raw_zero_candidate_record_count": zero_count,
                "contains_explicit_raw_zero_candidate": zero_count > 0,
                "record_status": status,
                "fare_amount_role": "published_fare_candidate_passenger_and_payment_basis_unspecified",
                "passenger_type": UNSPECIFIED,
                "payment_medium": UNSPECIFIED,
                "day_type": UNSPECIFIED,
                "time_period": UNSPECIFIED,
                "cost_effective_date": "",
                "cost_effective_date_status": REVISION_STATUS,
                "source_revision_cutoff_date": revision_cutoff,
                "source_download_date": DOWNLOAD_DATE,
                "source_file": (
                    f"{GTFS_REL.as_posix()}::fare_rules.txt;"
                    f"{GTFS_REL.as_posix()}::fare_attributes.txt"
                ),
                "source_sha256": source_hashes["gtfs"],
                "matching_method": "exact_route_id_and_ordered_stop_od_candidate_audit",
                "mapping_status": mapping_status,
                "mapping_quality": mapping_quality,
                "selection_performed": False,
                "production_cost_created": False,
                "unresolved_reason": (
                    ""
                    if status == "unique_candidate"
                    else "no_exact_raw_candidate"
                    if status == "missing"
                    else "multiple_identical_raw_records_not_collapsed"
                    if status == "duplicate_identical"
                    else "multiple_raw_candidates_with_different_amounts"
                ),
            }
            candidate_writer.add(row)
            if len(sample_rows) < 100:
                sample_rows.append(row)
            if status == "conflicting_amounts":
                conflict_rows.append(row)
            elif status == "duplicate_identical":
                duplicate_rows.append(row)
            elif status == "missing":
                missing_rows.append(row)
    candidate_writer.close()

    def frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
        return pd.DataFrame(rows, columns=CANDIDATE_COLUMNS)

    write_csv(frame(sample_rows), output_dir / "bus_od_fare_candidate_audit_sample.csv")
    write_parquet(frame(conflict_rows), output_dir / "bus_od_conflicts.parquet")
    write_csv(
        frame(conflict_rows[:100]), output_dir / "bus_od_conflicts_sample.csv"
    )
    write_parquet(
        frame(duplicate_rows), output_dir / "bus_od_duplicate_records.parquet"
    )
    write_csv(
        frame(duplicate_rows[:100]),
        output_dir / "bus_od_duplicate_records_sample.csv",
    )
    write_csv(frame(missing_rows), output_dir / "bus_missing_required_pairs.csv")

    for route in schedule:
        route_id = route["matsim_route_id"]
        meta = route_meta[route_id]
        counts = route_pair_counts[route_id]
        required = len(meta["pairs"])
        unique = counts["unique_candidate"]
        duplicate = counts["duplicate_identical"]
        conflict = counts["conflicting_amounts"]
        missing = counts["missing"]
        if meta["scope"] == "operator_scope_unresolved":
            readiness = "operator_scope_unresolved"
        elif meta["scope"] == "other_bus_service":
            readiness = "other_bus_service_not_in_franchised_core"
        elif missing:
            readiness = "partial_missing_pairs"
        elif conflict:
            readiness = "partial_conflicting_amounts"
        elif duplicate:
            readiness = "partial_duplicate_records"
        else:
            readiness = "ready_all_pairs_unique"
        matches = meta["candidate_keys"]
        readiness_rows.append(
            {
                "matsim_line_id": route["matsim_line_id"],
                "matsim_route_id": route_id,
                "service_scope": meta["scope"],
                "operator_scope_status": meta["scope"],
                "official_operator": meta["operator"],
                "official_operator_components_json": compact_json(
                    meta["operator"].split("+") if meta["operator"] else []
                ),
                "official_route_id": route["official_route_id"],
                "official_route_sequence": matches[0][1] if len(matches) == 1 else "",
                "route_identifier_status": (
                    "exact_official_route_id" if len(matches) == 1 else "route_unresolved"
                ),
                "direction_status": "exact" if len(matches) == 1 else "unresolved",
                "stop_mapping_status": (
                    "exact" if all(route["stop_ids"]) else "unresolved"
                ),
                "required_forward_pair_count": required,
                "unique_candidate_pair_count": unique,
                "duplicate_pair_count": duplicate,
                "conflict_pair_count": conflict,
                "missing_pair_count": missing,
                "forward_candidate_coverage": (
                    (required - missing) / required if required else 0.0
                ),
                "fare_readiness": readiness,
                "mapping_status": "exact" if len(matches) == 1 else "unresolved",
                "mapping_quality": "A" if len(matches) == 1 else "U",
                "unresolved_reason": (
                    "known_schedule_proxy_route_without_official_operator_stop_or_fare_evidence"
                    if route_id in KNOWN_UNMATCHED
                    else ""
                    if readiness == "ready_all_pairs_unique"
                    else readiness
                ),
            }
        )

    route_scope = pd.DataFrame(route_scope_rows)
    direction = pd.DataFrame(direction_rows)
    readiness = pd.DataFrame(readiness_rows)
    write_csv(route_scope, output_dir / "bus_route_scope_audit.csv")
    write_csv(direction, output_dir / "bus_direction_evidence_audit.csv")
    write_csv(readiness, output_dir / "bus_route_direction_readiness.csv")

    facility_usage: dict[str, list[dict[str, str]]] = defaultdict(list)
    for route in schedule:
        operator = route_meta[route["matsim_route_id"]]["operator"]
        for ref in route["stop_refs"]:
            facility_usage[ref].append(
                {
                    "matsim_route_id": route["matsim_route_id"],
                    "official_operator": operator,
                }
            )
    crosswalk_rows: list[dict[str, Any]] = []
    for ref in sorted(facility_usage):
        official_stop = stop_id_from_facility(ref)
        in_gtfs = official_stop in gtfs_stops if official_stop else False
        in_json = official_stop in json_stop_ids if official_stop else False
        exact = bool(official_stop and in_gtfs and in_json)
        usages = facility_usage[ref]
        crosswalk_rows.append(
            {
                "matsim_stop_facility_id": ref,
                "official_stop_id": official_stop,
                "gtfs_stop_exists": in_gtfs,
                "bus_json_stop_exists": in_json,
                "route_usage_count": len({item["matsim_route_id"] for item in usages}),
                "matsim_route_ids_json": compact_json(
                    sorted({item["matsim_route_id"] for item in usages})
                ),
                "official_operators_json": compact_json(
                    sorted({item["official_operator"] for item in usages if item["official_operator"]})
                ),
                "candidate_count": 1 if exact else 0,
                "mapping_status": "exact" if exact else "unresolved",
                "mapping_quality": "A" if exact else "U",
                "matching_method": (
                    "official_stop_id_explicitly_encoded_in_facility_id"
                    if exact
                    else "no_official_stop_id_encoded_in_proxy_facility_id"
                ),
                "evidence": (
                    "facility_token_equals_GTFS_stop_id_and_bus_JSON_stopId"
                    if exact
                    else "proxy_facility_without_official_stop_token"
                ),
                "unresolved_reason": (
                    "" if exact else "official_stop_id_not_encoded_or_not_found"
                ),
            }
        )
    crosswalk = pd.DataFrame(crosswalk_rows)
    write_csv(crosswalk, output_dir / "bus_stop_crosswalk.csv")

    full_rows: list[dict[str, Any]] = []
    for key in sorted(patterns, key=lambda value: (int(value[0]), int(value[1]), value[2])):
        group = sorted(json_groups[key], key=lambda value: value[0])
        full_values = {float(item["fullFare"]) for _, _, item in group}
        full_fare = next(iter(full_values)) if len(full_values) == 1 else None
        comparable = [
            record["price"]
            for origin, destination in sorted(forward_pairs(patterns[key]))
            for record in candidate_lookup.get((key[0], origin, destination), [])
        ]
        equal = sum(value == full_fare for value in comparable)
        full_rows.append(
            {
                "official_operator": key[2],
                "official_operator_components_json": compact_json(key[2].split("+")),
                "official_route_id": key[0],
                "official_route_sequence": key[1],
                "official_direction": key[1],
                "full_fare_hkd": full_fare,
                "currency": "HKD",
                "official_stop_pattern_json": compact_json(patterns[key]),
                "gtfs_candidate_record_count": len(comparable),
                "gtfs_price_equal_full_fare_count": equal,
                "gtfs_price_different_full_fare_count": len(comparable) - equal,
                "eligible_for_default_quote": False,
                "eligibility_status": "reference_only_unconditional_flat_fare_not_proven",
                "source_record_id": "json:feature_indices:"
                + ";".join(str(index) for _, index, _ in group),
                "source_feature_json": compact_json(group[0][2]),
                "source_file": JSON_REL.as_posix(),
                "source_sha256": source_hashes["bus_json"],
                "source_revision_cutoff_date": revision_cutoff,
                "source_download_date": DOWNLOAD_DATE,
                "cost_effective_date": "",
                "cost_effective_date_status": REVISION_STATUS,
            }
        )
    full_refs = pd.DataFrame(full_rows)
    write_csv(full_refs, output_dir / "bus_route_full_fare_reference.csv")

    schema = schema_audit(gtfs, json_props, geometry_props)
    write_csv(schema, output_dir / "bus_source_schema_audit.csv")
    semantics = {
        "schema_version": "hong_kong_bus_fare_readiness_semantics_v1",
        "answers": {
            "gtfs_price_passenger_payment_ticket_scope": UNSPECIFIED,
            "fare_rules_route_and_ordered_od": "encoded",
            "fare_rules_direction_route_sequence_day_time": UNSPECIFIED,
            "bus_json_operator_routeId_routeSeq_stopSeq_stopId_fullFare": "encoded",
            "bus_json_per_stop_or_sectional_fare": UNSPECIFIED,
            "fullFare_unconditional_flat_fare": UNSPECIFIED,
            "route_specific_fare_effective_date": UNSPECIFIED,
            "official_operator_code_dictionary": "GTFS_agency_plus_bus_JSON_companyCode",
            "franchised_scope_evidence": "official_CSDI_franchised_bus_geometry_COMPANY_CODE_set",
            "joint_operation_expression": "plus_delimited_complete_operator_code_retained",
        },
        "source_urls": {
            "gtfs": "https://static.data.gov.hk/td/pt-headway-en/gtfs.zip",
            "bus_json": "https://static.data.gov.hk/td/routes-fares-geojson/JSON_BUS.json",
            "revision": "https://static.data.gov.hk/td/routes-fares-geojson/DATA_LAST_UPDATED_DATE.csv",
            "franchised_bus_geometry": (
                "https://portal.csdi.gov.hk/server/rest/services/common/"
                "td_rcd_1638844988873_41214/FeatureServer/0/query"
            ),
        },
        "source_sha256": source_hashes,
        "source_revision_cutoff_date": revision_cutoff,
        "source_download_date": DOWNLOAD_DATE,
        "cost_effective_date": "",
        "cost_effective_date_status": REVISION_STATUS,
        "travel_date_eligibility": "not_performed",
        "production_cost_created": False,
    }
    (output_dir / "bus_fare_semantics_summary.json").write_text(
        json.dumps(semantics, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    full_comparisons = {
        "comparable_gtfs_candidate_record_count": int(
            full_refs["gtfs_candidate_record_count"].sum()
        ),
        "equal_full_fare_count": int(
            full_refs["gtfs_price_equal_full_fare_count"].sum()
        ),
        "different_full_fare_count": int(
            full_refs["gtfs_price_different_full_fare_count"].sum()
        ),
    }
    summary = {
        "schema_version": "hong_kong_bus_scope_direction_audit_v1",
        "schedule": {
            "line_count": len({row["matsim_line_id"] for row in schedule}),
            "route_count": len(schedule),
            "departure_count": sum(row["departure_count"] for row in schedule),
            "stop_occurrence_count": sum(len(row["stop_refs"]) for row in schedule),
            "distinct_facility_count": len(
                {ref for row in schedule for ref in row["stop_refs"]}
            ),
            "distinct_official_stop_id_count": len(
                {stop for row in schedule for stop in row["stop_ids"] if stop}
            ),
        },
        "operator_route_counts": dict(Counter(meta["operator"] for meta in route_meta.values())),
        "operator_scope_status_counts": dict(Counter(meta["scope"] for meta in route_meta.values())),
        "stop_crosswalk_status_counts": dict(Counter(crosswalk["mapping_status"])),
        "direction_status_counts": dict(Counter(readiness["direction_status"])),
        "route_mapping_status_counts": dict(Counter(readiness["mapping_status"])),
        "route_mapping_quality_counts": dict(Counter(readiness["mapping_quality"])),
        "fare_readiness_counts": dict(Counter(readiness["fare_readiness"])),
        "required_forward_pair_count": int(readiness["required_forward_pair_count"].sum()),
        "candidate_status_counts": dict(status_counts),
        "explicit_raw_zero_candidate_record_count": explicit_zero_candidate_records,
        "known_unmatched_routes": sorted(KNOWN_UNMATCHED),
        "full_fare_reference_count": len(full_refs),
        "full_fare_reference_in_candidate_selection": False,
        "full_fare_comparison_counts": full_comparisons,
        "source_sha256": source_hashes,
        "source_revision_cutoff_date": revision_cutoff,
        "source_download_date": DOWNLOAD_DATE,
        "cost_effective_date": "",
        "cost_effective_date_status": REVISION_STATUS,
        "query_interface_created": False,
        "production_pricing_performed": False,
        "matsim_scoring_integration": "not_performed",
        "prohibited_methods_used": {
            "reverse_od_substitution": False,
            "distance_or_nearest": False,
            "adjacent_or_path_sum": False,
            "candidate_aggregation_or_first": False,
            "cross_operator_or_route": False,
            "full_fare_fallback": False,
            "fare_id_text_recovery": False,
            "missing_zero_fill": False,
        },
    }
    (output_dir / "bus_scope_direction_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    write_csv(
        protected_hashes(repo_root),
        output_dir / "prior_mode_protected_hashes.csv",
    )
    readme = f"""# Hong Kong franchised-bus scope and fare-readiness audit v1

This is an operator-scope, direction-evidence, and ordered-OD candidate audit.
It creates no bus fare query, passenger cost, transfer rule, or MATSim scoring
integration.

- Schedule: {summary["schedule"]["line_count"]:,} lines,
  {len(schedule):,} routes, {sum(row["departure_count"] for row in schedule):,}
  departures.
- Operator scope: {summary["operator_scope_status_counts"]}.
- Direction is exact only for a unique complete official
  `routeId+routeSeq+stopSeq` match. MATSim suffixes are never evidence.
- Ordered-OD candidate states: {dict(status_counts)}.
- Every candidate retains raw GTFS line identifiers, source path, and SHA256.
- No `cost_hkd` or selected production fare exists.
- All {len(full_refs):,} JSON `fullFare` records are reference-only with
  `eligible_for_default_quote=false`.
- `2026-07-14` is a source revision cut-off, not a fare effective date.
"""
    (output_dir / "README.md").write_text(readme, encoding="utf-8")
    (output_dir / "bus_scope_direction_validation.json").write_text(
        json.dumps(
            {
                "schema_version": "hong_kong_bus_scope_direction_validation_v1",
                "status": "pending_independent_validation",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
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
    print(
        f"Audited {len(schedule):,} bus routes and "
        f"{sum(status_counts.values()):,} ordered OD pairs: {dict(status_counts)}"
    )


if __name__ == "__main__":
    main()
