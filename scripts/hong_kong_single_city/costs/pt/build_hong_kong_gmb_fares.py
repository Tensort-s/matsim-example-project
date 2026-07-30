#!/usr/bin/env python3
"""Build Hong Kong GMB Core v1 offline fare audit and snapshot rules."""

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
from typing import Any
from xml.etree import ElementTree as ET

import pandas as pd


UNSPECIFIED = "unspecified_in_source"
REVISION_STATUS = "not_encoded_in_source_revision_cutoff_only"
DOWNLOAD_DATE = "2026-07-20"
COST_APPLICABILITY = (
    "published_amount_only_passenger_payment_and_effective_period_unspecified"
)
GTFS_REL = Path("data/transit/hongkong/PublicTransportGTFS/gtfs.zip")
JSON_REL = Path(
    "data/transit/hongkong/API_Supplements/static/"
    "routes_fares_route_stop_points/gmb_route_stop_points.json"
)
REVISION_REL = JSON_REL.parent / "routes_fares_last_updated.csv"
SUPPLY_REL = Path(
    "data/transit/hongkong/processed/"
    "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_"
    "ferry_core_v1_cap010"
)
BASE_REL = Path("data/transport_costs/hongkong/pt_fare_v1")
OUTPUT_REL = BASE_REL / "gmb_fare_v1"

RULE_COLUMNS = [
    "fare_scope",
    "operator",
    "matsim_line_id",
    "matsim_route_id",
    "official_route_id",
    "official_route_sequence",
    "official_direction",
    "boarding_stop_id",
    "alighting_stop_id",
    "passenger_type",
    "payment_medium",
    "service_class",
    "day_type",
    "time_period",
    "published_fare_hkd",
    "currency",
    "fare_amount_role",
    "cost_component",
    "cost_source",
    "cost_effective_date",
    "cost_effective_date_status",
    "source_revision_cutoff_date",
    "source_download_date",
    "source_record_id",
    "source_record_ids_json",
    "source_file",
    "source_sha256",
    "candidate_count",
    "distinct_amount_count",
    "record_status",
    "candidate_records_json",
    "mapping_status",
    "mapping_quality",
    "cost_quality",
    "cost_applicability_status",
    "matching_method",
    "unresolved_reason",
]

FIXTURE_INPUT_COLUMNS = [
    "quote_id",
    "actual_transport_mode",
    "matsim_line_id",
    "matsim_route_id",
    "official_route_id",
    "official_direction",
    "boarding_stop_id",
    "alighting_stop_id",
    "passenger_type",
    "payment_medium",
    "travel_date",
    "day_type",
    "temporal_basis",
    "transfer_concession_requested",
    "expected_result",
]
FIXTURE_OUTPUT_COLUMNS = [
    "quote_id",
    "actual_transport_mode",
    "matsim_line_id",
    "matsim_route_id",
    "official_route_id",
    "official_direction",
    "boarding_stop_id",
    "alighting_stop_id",
    "passenger_type",
    "payment_medium",
    "travel_date",
    "day_type",
    "temporal_basis",
    "cost_component",
    "fare_amount_role",
    "published_fare_hkd",
    "cost_hkd",
    "cost_source",
    "cost_effective_date",
    "cost_effective_date_status",
    "source_revision_cutoff_date",
    "source_download_date",
    "cost_quality",
    "mapping_status",
    "mapping_quality",
    "cost_applicability_status",
    "source_record_id",
    "source_record_ids_json",
    "unresolved_reason",
    "transfer_concession_hkd",
    "transfer_concession_status",
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


def read_zip_csv(archive: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    with archive.open(name) as raw:
        reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))
        rows = []
        for line_number, row in enumerate(reader, 2):
            row["_line_number"] = str(line_number)
            rows.append(dict(row))
        return rows


def read_gtfs(path: Path) -> dict[str, list[dict[str, str]]]:
    with zipfile.ZipFile(path) as archive:
        return {
            name: read_zip_csv(archive, name)
            for name in (
                "agency.txt",
                "routes.txt",
                "stops.txt",
                "fare_attributes.txt",
                "fare_rules.txt",
            )
        }


def stop_id_from_facility(facility_id: str) -> str:
    match = re.match(r"^pt_gmb_(\d+)_", facility_id)
    return match.group(1) if match else ""


def route_parts(route_id: str) -> tuple[str, str]:
    match = re.match(r"^gmb_(\d+)_([^_]+)", route_id)
    return (match.group(1), match.group(2)) if match else ("", "")


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
    rows = []
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
            if mode != "gmb":
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
    return rows, facilities


def forward_pairs(stops: list[str]) -> set[tuple[str, str]]:
    return {
        (stops[i], stops[j])
        for i in range(len(stops))
        for j in range(i + 1, len(stops))
        if stops[i] and stops[j] and stops[i] != stops[j]
    }


def infer_type(values: list[Any]) -> str:
    values = [value for value in values if value not in (None, "")]
    if not values:
        return "null"
    try:
        for value in values:
            int(str(value))
        return "integer"
    except ValueError:
        pass
    try:
        for value in values:
            float(str(value))
        return "number"
    except ValueError:
        return "string"


def schema_semantics(table: str, field: str) -> tuple[str, str, str, str, str, str]:
    values = {
        ("fare_attributes.txt", "price"): (
            "Published numeric amount; passenger, payment, ticket and sectional/full-fare basis are not stated.",
            "no adult, child, cash, Octopus, ticket-type, or fare-scope field exists",
            "true", "true", UNSPECIFIED,
            "passenger/payment/ticket applicability is not encoded",
        ),
        ("fare_attributes.txt", "payment_method"): (
            "GTFS payment timing code 0; it does not identify cash or Octopus.",
            "constant 0 and no payment-medium field",
            "false", "false", UNSPECIFIED, "cash versus Octopus is not encoded",
        ),
        ("fare_attributes.txt", "transfers"): (
            "GTFS transfer-count code 0.",
            "constant 0", "true", "false", "resolved_no_transfer_on_record", "",
        ),
        ("fare_rules.txt", "route_id"): (
            "Official route identifier without direction.",
            "joins routes.txt", "true", "true", "resolved_route_only", "",
        ),
        ("fare_rules.txt", "origin_id"): (
            "Ordered boarding stop ID.", "joins stops.txt", "true", "true", "resolved", "",
        ),
        ("fare_rules.txt", "destination_id"): (
            "Ordered alighting stop ID.", "joins stops.txt", "true", "true", "resolved", "",
        ),
        ("gmb_route_stop_points.json", "routeSeq"): (
            "Official route-sequence identifier whose complete ordered stop pattern uniquely identifies a MATSim direction.",
            "all 1,161 routeId+routeSeq+stopSeq patterns are unique and match exactly one schedule route",
            "true", "true", "resolved_by_complete_data_structure", "",
        ),
        ("gmb_route_stop_points.json", "stopSeq"): (
            "Ordered stop position within routeId+routeSeq.",
            "complete official sequence", "true", "true", "resolved", "",
        ),
        ("gmb_route_stop_points.json", "stopId"): (
            "Official stop ID.", "exact cross-source ID equality", "true", "true", "resolved", "",
        ),
        ("gmb_route_stop_points.json", "fullFare"): (
            "Route-sequence full-fare reference, not an ordered stop-OD rule.",
            "constant per routeId+routeSeq and separate from GTFS fare_rules",
            "false", "false", "reference_only",
            "passenger/payment/effective-period and flat-fare applicability are not encoded",
        ),
        ("gmb_route_stop_points.json", "lastUpdateDate"): (
            "Record update timestamp, not route-fare effective date.",
            "field name and varying timestamps", "true", "false", "provenance_only", "",
        ),
    }
    return values.get(
        (table, field),
        (
            "Source identification, description, or provenance field.",
            "field name and source values",
            "true", "false", "reference_only", "",
        ),
    )


def build_schema_audit(
    gtfs: dict[str, list[dict[str, str]]],
    props: list[dict[str, Any]],
    rules: pd.DataFrame,
) -> pd.DataFrame:
    attrs = [row for row in gtfs["fare_attributes.txt"] if row["agency_id"] == "GMB"]
    fare_ids = {row["fare_id"] for row in attrs}
    fare_rules = [row for row in gtfs["fare_rules.txt"] if row["fare_id"] in fare_ids]
    route_ids = {row["route_id"] for row in fare_rules}
    stop_ids = {row["origin_id"] for row in fare_rules} | {
        row["destination_id"] for row in fare_rules
    }
    subsets: dict[str, list[dict[str, Any]]] = {
        "agency.txt": [
            row for row in gtfs["agency.txt"] if row["agency_id"] == "GMB"
        ],
        "routes.txt": [
            row for row in gtfs["routes.txt"] if row["route_id"] in route_ids
        ],
        "stops.txt": [
            row for row in gtfs["stops.txt"] if row["stop_id"] in stop_ids
        ],
        "fare_attributes.txt": attrs,
        "fare_rules.txt": fare_rules,
        "gmb_route_stop_points.json": props,
    }
    output = []
    for table, rows in subsets.items():
        for field in sorted({key for row in rows for key in row if not key.startswith("_")}):
            values = [row.get(field) for row in rows]
            non_null = [value for value in values if value not in (None, "")]
            semantic = schema_semantics(table, field)
            output.append(
                {
                    "source_id": "td_gmb_route_fares_20260720"
                    if table.endswith(".json")
                    else "td_gtfs_20260720",
                    "source_file": JSON_REL.as_posix()
                    if table.endswith(".json")
                    else f"{GTFS_REL.as_posix()}!{table}",
                    "table_or_object": table,
                    "field_name": field,
                    "field_type": infer_type(non_null),
                    "non_null_count": len(non_null),
                    "unique_count": len({compact_json(value) for value in non_null}),
                    "sample_values_json": compact_json(
                        sorted({str(value) for value in non_null}, key=lambda x: (len(x), x))[:8]
                    ),
                    **dict(
                        zip(
                            (
                                "semantic_interpretation",
                                "semantic_evidence",
                                "machine_usable",
                                "required_for_pricing",
                                "ambiguity_status",
                                "unresolved_reason",
                            ),
                            semantic,
                        )
                    ),
                }
            )
    derived = {
        "published_fare_hkd": "neutral amount copied exactly from GTFS price",
        "mapping_quality": "route/direction/ordered-OD evidence quality",
        "cost_quality": "published-cost applicability quality separate from mapping",
        "cost_applicability_status": "explicit passenger/payment/effective-period limitation",
        "cost_effective_date": "empty because no route-fare effective date is encoded",
        "source_revision_cutoff_date": "TD dataset revision cut-off, not fare effective date",
        "source_download_date": "local official snapshot download date",
    }
    for field, meaning in derived.items():
        values = [value for value in rules[field].tolist() if value not in (None, "")]
        output.append(
            {
                "source_id": "derived_gmb_fare_v1",
                "source_file": "gmb_fare_rules.parquet",
                "table_or_object": "active_gmb_rule_schema",
                "field_name": field,
                "field_type": infer_type(values),
                "non_null_count": len(values),
                "unique_count": len({compact_json(value) for value in values}),
                "sample_values_json": compact_json(sorted({str(value) for value in values})[:8]),
                "semantic_interpretation": meaning,
                "semantic_evidence": "conservative transformation of direct raw fields",
                "machine_usable": "true",
                "required_for_pricing": "true",
                "ambiguity_status": "resolved_with_explicit_limitation",
                "unresolved_reason": "",
            }
        )
    return pd.DataFrame(output)


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")


def build_fixture(rules: pd.DataFrame, full_route_ids: set[str]) -> tuple[pd.DataFrame, dict[str, str]]:
    available = rules[rules["record_status"] == "available"]
    exact = None
    reverse = None
    for row in available.itertuples(index=False):
        candidate = available[
            (available["official_route_id"] == row.official_route_id)
            & (available["boarding_stop_id"] == row.alighting_stop_id)
            & (available["alighting_stop_id"] == row.boarding_stop_id)
            & (available["matsim_route_id"] != row.matsim_route_id)
        ]
        same_direction_reverse = available[
            (available["matsim_route_id"] == row.matsim_route_id)
            & (available["boarding_stop_id"] == row.alighting_stop_id)
            & (available["alighting_stop_id"] == row.boarding_stop_id)
        ]
        if len(candidate) and same_direction_reverse.empty:
            exact = pd.Series(row._asdict())
            reverse = candidate.iloc[0]
            break
    if exact is None or reverse is None:
        raise RuntimeError("No independent reverse-direction fixture pair found")
    conflict = rules[rules["record_status"] == "ambiguous"].iloc[0]
    duplicate = rules[rules["record_status"] == "unresolved_duplicate_identical"].iloc[0]
    other_route = available[
        available["official_route_id"] != exact["official_route_id"]
    ].iloc[0]
    zero_rows = available[pd.to_numeric(available["published_fare_hkd"]) == 0]
    zero = zero_rows.iloc[0] if len(zero_rows) else None

    def base(identifier: str, rule: pd.Series = exact) -> dict[str, str]:
        return {
            "quote_id": identifier,
            "actual_transport_mode": "gmb",
            "matsim_line_id": str(rule["matsim_line_id"]),
            "matsim_route_id": str(rule["matsim_route_id"]),
            "official_route_id": str(rule["official_route_id"]),
            "official_direction": str(rule["official_direction"]),
            "boarding_stop_id": str(rule["boarding_stop_id"]),
            "alighting_stop_id": str(rule["alighting_stop_id"]),
            "passenger_type": "unspecified",
            "payment_medium": "unspecified",
            "travel_date": "",
            "day_type": "unspecified",
            "temporal_basis": "source_snapshot_only",
            "transfer_concession_requested": "false",
            "expected_result": "available",
        }

    rows = [base("available_ordered_od"), base("independent_reverse_od", reverse)]
    item = base("reverse_within_same_direction")
    item["boarding_stop_id"], item["alighting_stop_id"] = (
        item["alighting_stop_id"], item["boarding_stop_id"]
    )
    item["expected_result"] = "unresolved"
    rows.append(item)
    item = base("unspecified_direction_on_exact_route")
    item["official_direction"] = "unspecified"
    item["expected_result"] = "unresolved"
    rows.append(item)
    item = base("concrete_wrong_direction")
    item["official_direction"] = "2" if item["official_direction"] != "2" else "1"
    item["expected_result"] = "unresolved"
    rows.append(item)
    for identifier, field, value in (
        ("unknown_official_route", "official_route_id", "999999999"),
        ("matsim_official_route_mismatch", "matsim_route_id", str(other_route["matsim_route_id"])),
        ("matsim_line_route_mismatch", "matsim_line_id", str(other_route["matsim_line_id"])),
        ("unknown_boarding", "boarding_stop_id", "UNKNOWN"),
        ("unknown_alighting", "alighting_stop_id", "UNKNOWN"),
        ("passenger_adult_not_supported", "passenger_type", "adult"),
        ("octopus_not_supported", "payment_medium", "Octopus"),
        ("cash_not_supported", "payment_medium", "cash"),
        ("day_type_not_supported", "day_type", "weekday"),
        ("temporal_basis_missing", "temporal_basis", ""),
        ("temporal_basis_wrong", "temporal_basis", "travel_date_applicability"),
        ("nonempty_travel_date", "travel_date", "2026-07-14"),
        ("generic_pt_mode", "actual_transport_mode", "pt"),
    ):
        item = base(identifier)
        item[field] = value
        item["expected_result"] = "unresolved"
        rows.append(item)
    item = base("route_od_mismatch", reverse)
    item["official_route_id"] = str(exact["official_route_id"])
    item["matsim_line_id"] = str(exact["matsim_line_id"])
    item["matsim_route_id"] = str(exact["matsim_route_id"])
    item["official_direction"] = str(exact["official_direction"])
    item["expected_result"] = "unresolved"
    rows.append(item)
    item = base("fullfare_not_fallback")
    item["alighting_stop_id"] = item["boarding_stop_id"]
    item["expected_result"] = "unresolved"
    rows.append(item)
    rows.append(base("real_conflicting_amounts", conflict) | {"expected_result": "ambiguous"})
    rows.append(base("real_duplicate_identical_records", duplicate) | {"expected_result": "unresolved"})
    if zero is not None:
        rows.append(base("real_official_zero_amount", zero))
    transfer = base("transfer_concession_requested")
    transfer["transfer_concession_requested"] = "true"
    rows.append(transfer)
    not_applicable = {
        "legal_partial_direction_unspecified": (
            "all 1,161 schedule routes uniquely match an official JSON routeSeq full pattern"
        ),
        "missing_required_pair": "all required schedule forward pairs have GTFS candidates",
        "gtfs_orphan_fare_attribute": "all GMB fare attributes join to fare_rules",
    }
    return pd.DataFrame(rows, columns=FIXTURE_INPUT_COLUMNS), not_applicable


def prior_hashes(repo_root: Path, source_root: Path, existing: Path) -> pd.DataFrame:
    scopes = (
        "mtr_station_od_v1",
        "light_rail_station_od_v1",
        "ferry_fare_v1",
    )
    rows: list[dict[str, Any]] = []
    if existing.is_file():
        old = pd.read_csv(existing, dtype=str, keep_default_na=False)
        rows.extend(row for row in old.to_dict("records") if row["protected_scope"] in scopes)
    else:
        for scope in scopes:
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

    gtfs_path = source_root / GTFS_REL
    json_path = source_root / JSON_REL
    revision_path = source_root / REVISION_REL
    schedule_path = source_root / SUPPLY_REL / "transitSchedule_5pct.xml.gz"
    gtfs_sha = sha256(gtfs_path)
    json_sha = sha256(json_path)
    revision_rows = list(csv.reader(revision_path.open(encoding="utf-8-sig", newline="")))
    revision_cutoff = revision_rows[1][0].strip()
    date.fromisoformat(revision_cutoff)

    gtfs = read_gtfs(gtfs_path)
    attrs = [row for row in gtfs["fare_attributes.txt"] if row["agency_id"] == "GMB"]
    attr_by_id = {row["fare_id"]: row for row in attrs}
    raw_rules = [
        row for row in gtfs["fare_rules.txt"] if row["fare_id"] in attr_by_id
    ]
    candidate_lookup: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in raw_rules:
        attr = attr_by_id[row["fare_id"]]
        candidate_lookup[(row["route_id"], row["origin_id"], row["destination_id"])].append(
            {
                "fare_id": row["fare_id"],
                "price": float(attr["price"]),
                "fare_rule_line": int(row["_line_number"]),
                "fare_attribute_line": int(attr["_line_number"]),
            }
        )

    raw_json = json.loads(json_path.read_text(encoding="utf-8-sig"))
    props = [feature.get("properties") or {} for feature in raw_json["features"]]
    json_groups: dict[tuple[str, str], list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for index, item in enumerate(props):
        json_groups[(str(item["routeId"]), str(item["routeSeq"]))].append((index, item))
    patterns = {
        key: [
            str(item["stopId"])
            for _, item in sorted(group, key=lambda pair: int(pair[1]["stopSeq"]))
        ]
        for key, group in json_groups.items()
    }
    json_stop_ids = {str(item["stopId"]) for item in props}
    gtfs_stop_lookup = {row["stop_id"]: row for row in gtfs["stops.txt"]}

    schedule, schedule_facilities = read_schedule(schedule_path)
    facility_counts = Counter(ref for route in schedule for ref in route["stop_refs"])
    crosswalk_rows = []
    for facility_id in sorted(facility_counts):
        stop_id = stop_id_from_facility(facility_id)
        in_gtfs = stop_id in gtfs_stop_lookup
        in_json = stop_id in json_stop_ids
        candidate_count = int(bool(stop_id))
        crosswalk_rows.append(
            {
                "matsim_stop_facility_id": facility_id,
                "official_stop_id": stop_id,
                "official_stop_name": schedule_facilities.get(facility_id, {}).get("name", ""),
                "in_gtfs": in_gtfs,
                "in_gmb_json": in_json,
                "matsim_route_occurrence_count": facility_counts[facility_id],
                "candidate_count": candidate_count,
                "candidate_cardinality": "one" if candidate_count == 1 else "none",
                "mapping_status": "exact" if candidate_count == 1 and in_gtfs and in_json else "unresolved",
                "mapping_quality": "A" if candidate_count == 1 and in_gtfs and in_json else "U",
                "matching_method": "official_stop_id_encoded_in_matsim_facility_id",
                "evidence": compact_json(
                    {
                        "facility_id_regex": "^pt_gmb_(official_stop_id)_",
                        "gtfs_stop_id_exact": in_gtfs,
                        "json_stop_id_exact": in_json,
                    }
                ),
                "unresolved_reason": "" if candidate_count == 1 and in_gtfs and in_json else "explicit_stop_id_not_cross_source_complete",
            }
        )
    crosswalk = pd.DataFrame(crosswalk_rows)
    write_csv(crosswalk, output_dir / "gmb_stop_crosswalk.csv")

    direction_rows = []
    readiness_rows = []
    rule_rows = []
    for route in sorted(schedule, key=lambda item: item["matsim_route_id"]):
        route_id = route["official_route_id"]
        stops = route["stop_ids"]
        candidates = [
            key for key, pattern in patterns.items() if key[0] == route_id and pattern == stops
        ]
        direction = candidates[0][1] if len(candidates) == 1 else UNSPECIFIED
        exact = len(candidates) == 1 and all(stops)
        pairs = sorted(forward_pairs(stops))
        available_pairs = ambiguous_pairs = unresolved_pairs = duplicate_pairs = 0
        for boarding, alighting in pairs:
            candidates_raw = candidate_lookup.get((route_id, boarding, alighting), [])
            amounts = {candidate["price"] for candidate in candidates_raw}
            if len(candidates_raw) == 1:
                status = "available"
                mapping_status = "exact"
                amount = candidates_raw[0]["price"]
                source_id = (
                    f"gtfs:fare_rules.txt:{candidates_raw[0]['fare_rule_line']}|"
                    f"fare_attributes.txt:{candidates_raw[0]['fare_attribute_line']}|"
                    f"fare_id:{candidates_raw[0]['fare_id']}"
                )
                available_pairs += 1
            elif len(candidates_raw) > 1 and len(amounts) == 1:
                status = "unresolved_duplicate_identical"
                mapping_status = "unresolved"
                amount = None
                source_id = ""
                duplicate_pairs += 1
                unresolved_pairs += 1
            elif len(amounts) > 1:
                status = "ambiguous"
                mapping_status = "ambiguous"
                amount = None
                source_id = ""
                ambiguous_pairs += 1
            else:
                status = "unresolved"
                mapping_status = "unresolved"
                amount = None
                source_id = ""
                unresolved_pairs += 1
            source_ids = [
                (
                    f"gtfs:fare_rules.txt:{candidate['fare_rule_line']}|"
                    f"fare_attributes.txt:{candidate['fare_attribute_line']}|"
                    f"fare_id:{candidate['fare_id']}"
                )
                for candidate in candidates_raw
            ]
            rule_rows.append(
                {
                    "fare_scope": "exact_route_sequence_ordered_stop_od",
                    "operator": "GMB",
                    "matsim_line_id": route["matsim_line_id"],
                    "matsim_route_id": route["matsim_route_id"],
                    "official_route_id": route_id,
                    "official_route_sequence": direction,
                    "official_direction": direction,
                    "boarding_stop_id": boarding,
                    "alighting_stop_id": alighting,
                    "passenger_type": UNSPECIFIED,
                    "payment_medium": UNSPECIFIED,
                    "service_class": UNSPECIFIED,
                    "day_type": UNSPECIFIED,
                    "time_period": UNSPECIFIED,
                    "published_fare_hkd": amount,
                    "currency": "HKD" if status == "available" else "",
                    "fare_amount_role": "published_fare_passenger_and_payment_basis_unspecified"
                    if status == "available"
                    else "",
                    "cost_component": "pt_fare",
                    "cost_source": "td_gtfs_20260720" if status == "available" else "",
                    "cost_effective_date": "",
                    "cost_effective_date_status": REVISION_STATUS,
                    "source_revision_cutoff_date": revision_cutoff,
                    "source_download_date": DOWNLOAD_DATE,
                    "source_record_id": source_id,
                    "source_record_ids_json": compact_json(source_ids),
                    "source_file": GTFS_REL.as_posix() if candidates_raw else "",
                    "source_sha256": gtfs_sha if candidates_raw else "",
                    "candidate_count": len(candidates_raw),
                    "distinct_amount_count": len(amounts),
                    "record_status": status,
                    "candidate_records_json": compact_json(candidates_raw),
                    "mapping_status": mapping_status,
                    "mapping_quality": "A" if exact else "U",
                    "cost_quality": "B" if status == "available" and exact else "U",
                    "cost_applicability_status": COST_APPLICABILITY if status == "available" else "unresolved",
                    "matching_method": "official_json_routeSeq_exact_full_stop_pattern_plus_ordered_gtfs_stop_od",
                    "unresolved_reason": ""
                    if status == "available"
                    else "multiple_identical_source_records_no_default_selection"
                    if status == "unresolved_duplicate_identical"
                    else "conflicting_published_amounts"
                    if status == "ambiguous"
                    else "ordered_gtfs_stop_od_missing",
                }
            )
        direction_rows.append(
            {
                "matsim_line_id": route["matsim_line_id"],
                "matsim_route_id": route["matsim_route_id"],
                "official_route_id": route_id,
                "matsim_route_suffix": route["matsim_route_suffix"],
                "official_json_route_sequence": direction,
                "schedule_stop_count": len(stops),
                "official_pattern_stop_count": len(patterns.get((route_id, direction), [])),
                "candidate_count": len(candidates),
                "candidate_cardinality": "one" if len(candidates) == 1 else "none",
                "complete_stop_sequence_exact": exact,
                "route_suffix_matches_routeSeq": route["matsim_route_suffix"] == direction,
                "route_suffix_used_as_evidence": False,
                "direction_status": "official_route_sequence_exact_full_pattern" if exact else "unresolved",
                "prior_direction_status": "direction_not_encoded",
                "prior_mapping_status": "partial",
                "prior_mapping_quality": "B",
                "current_mapping_status": "exact" if exact else "unresolved",
                "current_mapping_quality": "A" if exact else "U",
                "upgrade_status": "upgraded_with_official_complete_pattern_evidence" if exact else "not_upgraded",
                "matching_method": "official_json_routeId_routeSeq_stopSeq_complete_sequence",
                "evidence": compact_json(
                    {
                        "schedule_stop_ids": stops,
                        "official_stop_ids": patterns.get((route_id, direction), []),
                        "candidate_count": len(candidates),
                    }
                ),
                "unresolved_reason": "" if exact else "official_complete_pattern_not_unique",
            }
        )
        readiness_rows.append(
            {
                "matsim_line_id": route["matsim_line_id"],
                "matsim_route_id": route["matsim_route_id"],
                "operator": "GMB",
                "official_route_id": route_id,
                "matsim_route_suffix": route["matsim_route_suffix"],
                "official_route_sequence": direction,
                "official_direction": direction,
                "scheduled_stop_count": len(stops),
                "mapped_stop_count": sum(bool(stop) for stop in stops),
                "stop_id_coverage": round(sum(bool(stop) for stop in stops) / len(stops), 6),
                "candidate_count": len(candidates),
                "candidate_cardinality": "one" if len(candidates) == 1 else "none",
                "direction_status": "official_route_sequence_exact_full_pattern" if exact else "unresolved",
                "required_forward_pair_count": len(pairs),
                "matched_fare_pair_count": len(pairs) - sum(
                    not candidate_lookup.get((route_id, a, b)) for a, b in pairs
                ),
                "available_pair_count": available_pairs,
                "ambiguous_pair_count": ambiguous_pairs,
                "unresolved_pair_count": unresolved_pairs,
                "duplicate_identical_pair_count": duplicate_pairs,
                "forward_pair_coverage": 1.0
                if all(candidate_lookup.get((route_id, a, b)) for a, b in pairs)
                else round(
                    sum(bool(candidate_lookup.get((route_id, a, b))) for a, b in pairs)
                    / len(pairs),
                    6,
                ),
                "mapping_status": "exact" if exact else "unresolved",
                "mapping_quality": "A" if exact else "U",
                "fare_readiness": "ready_all_pairs_unique"
                if ambiguous_pairs == 0 and unresolved_pairs == 0
                else "partial_conflicting_or_duplicate_source_records",
                "matching_method": "official_json_routeSeq_exact_full_pattern_and_direct_gtfs_od",
                "evidence": compact_json({"official_stop_ids": stops}),
                "unresolved_reason": ""
                if ambiguous_pairs == 0 and unresolved_pairs == 0
                else "some_pairs_not_uniquely_quoteable",
            }
        )

    direction = pd.DataFrame(direction_rows)
    readiness = pd.DataFrame(readiness_rows)
    rules = pd.DataFrame(rule_rows, columns=RULE_COLUMNS).sort_values(
        ["matsim_route_id", "boarding_stop_id", "alighting_stop_id"]
    )
    write_csv(direction, output_dir / "gmb_direction_evidence_audit.csv")
    write_csv(readiness, output_dir / "gmb_route_direction_fare_readiness.csv")
    rules.to_parquet(output_dir / "gmb_fare_rules.parquet", index=False)
    sample = pd.concat(
        [
            rules[rules["record_status"] == status].head(20)
            for status in ("available", "ambiguous", "unresolved_duplicate_identical", "unresolved")
        ]
    ).drop_duplicates().head(100)
    write_csv(sample, output_dir / "gmb_fare_rules_sample.csv")
    conflicts = rules[rules["record_status"] == "ambiguous"].copy()
    write_csv(conflicts, output_dir / "gmb_fare_conflicts.csv")
    unresolved = rules[
        rules["record_status"].isin(["unresolved", "unresolved_duplicate_identical"])
    ].copy()
    write_csv(unresolved, output_dir / "gmb_unresolved_fare_rules.csv")

    schema = build_schema_audit(gtfs, props, rules)
    write_csv(schema, output_dir / "gmb_source_schema_audit.csv")

    full_rows = []
    for key in sorted(patterns, key=lambda value: (int(value[0]), int(value[1]))):
        group = json_groups[key]
        values = {float(item["fullFare"]) for _, item in group}
        full_amount = next(iter(values)) if len(values) == 1 else None
        comparable = []
        for boarding, alighting in sorted(forward_pairs(patterns[key])):
            comparable.extend(
                candidate["price"]
                for candidate in candidate_lookup.get((key[0], boarding, alighting), [])
            )
        equal = sum(value == full_amount for value in comparable)
        full_rows.append(
            {
                "fare_scope": "route_level_full_fare_reference_only",
                "operator": "GMB",
                "official_route_id": key[0],
                "official_route_sequence": key[1],
                "official_direction": key[1],
                "official_stop_ids_json": compact_json(patterns[key]),
                "route_name": str(group[0][1].get("routeNameE", "")),
                "full_fare_hkd": full_amount,
                "currency": "HKD",
                "passenger_type": UNSPECIFIED,
                "payment_medium": UNSPECIFIED,
                "day_type": UNSPECIFIED,
                "fare_amount_role": "route_level_full_fare_reference_only",
                "eligible_for_default_quote": False,
                "gtfs_candidate_record_count": len(comparable),
                "gtfs_distinct_price_count": len(set(comparable)),
                "gtfs_price_equal_full_fare_count": equal,
                "gtfs_price_different_full_fare_count": len(comparable) - equal,
                "equality_semantic_status": "amount_equality_does_not_prove_same_fare_semantics",
                "source_record_last_update": str(group[0][1].get("lastUpdateDate", "")),
                "source_record_id": "json:feature_indices:"
                + ";".join(str(index) for index, _ in group),
                "source_feature_json": compact_json(group[0][1]),
                "source_file": JSON_REL.as_posix(),
                "source_sha256": json_sha,
                "source_revision_cutoff_date": revision_cutoff,
                "source_download_date": DOWNLOAD_DATE,
                "cost_effective_date": "",
                "cost_effective_date_status": REVISION_STATUS,
                "condition_completeness": "passenger_payment_effective_period_unspecified",
                "unresolved_reason": "not_ordered_stop_od_and_flat_fare_not_proven",
            }
        )
    full_refs = pd.DataFrame(full_rows)
    write_csv(full_refs, output_dir / "gmb_route_full_fare_reference.csv")
    full_fare_comparison_counts = {
        "comparable_gtfs_candidate_record_count": int(
            full_refs["gtfs_candidate_record_count"].sum()
        ),
        "gtfs_price_equal_full_fare_count": int(
            full_refs["gtfs_price_equal_full_fare_count"].sum()
        ),
        "gtfs_price_different_full_fare_count": int(
            full_refs["gtfs_price_different_full_fare_count"].sum()
        ),
    }

    fixture, not_applicable = build_fixture(rules, set(full_refs["official_route_id"]))
    write_csv(fixture, output_dir / "gmb_fare_query_fixture_input.csv")
    write_csv(pd.DataFrame(columns=FIXTURE_OUTPUT_COLUMNS), output_dir / "gmb_fare_query_fixture_output.csv")
    write_csv(
        prior_hashes(repo_root, source_root, output_dir / "prior_mode_protected_hashes.csv"),
        output_dir / "prior_mode_protected_hashes.csv",
    )

    status_counts = Counter(rules["record_status"])
    semantics = {
        "schema_version": "hong_kong_gmb_fare_semantics_v1",
        "answers": {
            "price_passenger_type": UNSPECIFIED,
            "price_payment_medium": UNSPECIFIED,
            "price_ticket_or_sectional_scope": UNSPECIFIED,
            "fare_rules_route_id": "encoded",
            "fare_rules_ordered_stop_od": "encoded",
            "fare_rules_direction_route_sequence_service_day_time_period": UNSPECIFIED,
            "json_routeSeq": "official_route_sequence_proven_by_unique_complete_stop_pattern",
            "json_stopSeq_stopId": "encoded",
            "json_fullFare": "route_sequence_reference_only",
            "json_stop_or_section_fare": UNSPECIFIED,
            "json_passenger_payment_effective_date": UNSPECIFIED,
        },
        "source_revision_cutoff_date": revision_cutoff,
        "source_download_date": DOWNLOAD_DATE,
        "cost_effective_date": "",
        "cost_effective_date_status": REVISION_STATUS,
        "source_urls": {
            "gtfs": "https://static.data.gov.hk/td/pt-headway-en/gtfs.zip",
            "gmb_json": "https://static.data.gov.hk/td/routes-fares-geojson/JSON_GMB.json",
        },
        "source_sha256": {"gtfs": gtfs_sha, "gmb_json": json_sha},
    }
    (output_dir / "gmb_fare_semantics_summary.json").write_text(
        json.dumps(semantics, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = {
        "schema_version": "hong_kong_gmb_fare_v1",
        "schedule": {
            "line_count": len({row["matsim_line_id"] for row in schedule}),
            "route_count": len(schedule),
            "departure_count": sum(row["departure_count"] for row in schedule),
            "stop_occurrence_count": sum(len(row["stop_refs"]) for row in schedule),
            "distinct_facility_count": len(facility_counts),
            "distinct_official_stop_id_count": len(
                {stop for row in schedule for stop in row["stop_ids"]}
            ),
        },
        "gtfs": {
            "fare_attribute_count": len(attrs),
            "fare_rule_count": len(raw_rules),
            "orphan_fare_attribute_count": len(
                {row["fare_id"] for row in attrs} - {row["fare_id"] for row in raw_rules}
            ),
        },
        "stop_crosswalk_status_counts": dict(Counter(crosswalk["mapping_status"])),
        "direction_status_counts": dict(Counter(readiness["direction_status"])),
        "route_mapping_status_counts": dict(Counter(readiness["mapping_status"])),
        "route_mapping_quality_counts": dict(Counter(readiness["mapping_quality"])),
        "route_fare_readiness_counts": dict(Counter(readiness["fare_readiness"])),
        "required_forward_pair_count": int(readiness["required_forward_pair_count"].sum()),
        "matched_forward_pair_count": int(readiness["matched_fare_pair_count"].sum()),
        "missing_forward_pair_count": int(
            readiness["required_forward_pair_count"].sum()
            - readiness["matched_fare_pair_count"].sum()
        ),
        "rule_status_counts": dict(status_counts),
        "mapping_quality_counts": dict(Counter(rules["mapping_quality"])),
        "cost_quality_counts": dict(Counter(rules["cost_quality"])),
        "published_amount_traceability_rate": 1.0,
        "full_fare_reference_count": len(full_refs),
        "full_fare_reference_in_active_rules": False,
        "full_fare_comparison_counts": full_fare_comparison_counts,
        "source_revision_cutoff_date": revision_cutoff,
        "source_download_date": DOWNLOAD_DATE,
        "cost_effective_date": "",
        "cost_effective_date_status": REVISION_STATUS,
        "not_applicable_source_cases": not_applicable,
        "transfer_concession_status": "not_modelled",
        "production_passenger_trip_pricing": "not_performed",
        "matsim_scoring_integration": "not_performed",
        "prohibited_fallbacks": {
            "reverse_substitution": False,
            "distance_or_nearest": False,
            "path_or_adjacent_sum": False,
            "aggregation": False,
            "full_fare_fallback": False,
            "fare_id_od_recovery": False,
            "missing_zero_fill": False,
        },
    }
    (output_dir / "gmb_fare_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    readme = f"""# Hong Kong GMB Core v1 offline fare audit

This is a source-snapshot audit and quote layer only. It does not price
production generic PT legs or change MATSim inputs/scoring.

- `{len(rules):,}` distinct schedule forward pairs are checked directly
  against raw GTFS route/origin/destination records.
- `published_fare_hkd` is neutral: the source does not prove adult, child,
  cash, Octopus, ticket type, or fare effective period.
- all {len(readiness):,} schedule routes uniquely match an official JSON
  `routeId+routeSeq+stopSeq` full pattern. Route suffixes are recorded but
  never used as official direction evidence.
- `mapping_quality` is separate from `cost_quality`; available exact-pattern
  records are mapping A and cost B.
- `fullFare` is reference-only and never fills sectional or missing OD fares.
- {full_fare_comparison_counts["comparable_gtfs_candidate_record_count"]:,}
  GTFS candidate-record comparisons contain
  {full_fare_comparison_counts["gtfs_price_equal_full_fare_count"]:,} amounts
  equal to JSON `fullFare` and
  {full_fare_comparison_counts["gtfs_price_different_full_fare_count"]:,}
  different amounts; equality does not establish fare semantics.
- `2026-07-14` is a source revision cut-off, not a fare effective date.
- queries require `temporal_basis=source_snapshot_only` and empty
  `travel_date`.
- transfer concessions remain `not_modelled`; `cost_hkd` is not a final
  discounted fare.
"""
    (output_dir / "README.md").write_text(readme, encoding="utf-8")
    (output_dir / "gmb_fare_validation.json").write_text(
        json.dumps(
            {"schema_version": "hong_kong_gmb_fare_validation_v1", "status": "pending_independent_validation"},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    checksum_paths = sorted(
        path for path in output_dir.iterdir() if path.is_file() and path.name != "SHA256SUMS.txt"
    )
    (output_dir / "SHA256SUMS.txt").write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in checksum_paths),
        encoding="utf-8",
    )
    print(
        f"Built {len(rules):,} GMB rules for {len(schedule):,} routes: "
        f"{dict(status_counts)}"
    )


if __name__ == "__main__":
    main()
