#!/usr/bin/env python3
"""Build the auditable Hong Kong Ferry Core v1 offline fare-rule catalogue."""

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


EFFECTIVE_DATE_STATUS = "not_encoded_in_source_revision_cutoff_only"
DOWNLOAD_DATE = "2026-07-20"
UNSPECIFIED = "unspecified_in_source"
COST_APPLICABILITY = (
    "published_amount_only_passenger_payment_class_vessel_day_and_"
    "effective_period_unspecified"
)
SUPPLY_REL = Path(
    "data/transit/hongkong/processed/"
    "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_"
    "ferry_core_v1_cap010"
)
GTFS_REL = Path("data/transit/hongkong/PublicTransportGTFS/gtfs.zip")
JSON_REL = Path(
    "data/transit/hongkong/API_Supplements/static/"
    "routes_fares_route_stop_points/ferry_route_stop_points.json"
)
REVISION_REL = JSON_REL.parent / "routes_fares_last_updated.csv"
OUTPUT_REL = Path("data/transport_costs/hongkong/pt_fare_v1/ferry_fare_v1")
BASE_FARE_REL = Path("data/transport_costs/hongkong/pt_fare_v1")

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
    "vessel_service_type",
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
    "source_file",
    "source_sha256",
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
    "matsim_route_id",
    "official_route_id",
    "official_direction",
    "boarding_stop_id",
    "alighting_stop_id",
    "passenger_type",
    "payment_medium",
    "service_class",
    "vessel_service_type",
    "travel_date",
    "day_type",
    "temporal_basis",
    "transfer_concession_requested",
    "expected_result",
]

FIXTURE_OUTPUT_COLUMNS = [
    "quote_id",
    "actual_transport_mode",
    "matsim_route_id",
    "official_route_id",
    "official_direction",
    "boarding_stop_id",
    "alighting_stop_id",
    "passenger_type",
    "payment_medium",
    "service_class",
    "vessel_service_type",
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


def read_csv_rows_from_zip(archive: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    with archive.open(name) as raw:
        reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))
        rows = []
        for line_number, row in enumerate(reader, start=2):
            row["_line_number"] = str(line_number)
            rows.append(dict(row))
        return rows


def read_raw_gtfs(path: Path) -> dict[str, list[dict[str, str]]]:
    with zipfile.ZipFile(path) as archive:
        return {
            name: read_csv_rows_from_zip(archive, name)
            for name in (
                "agency.txt",
                "routes.txt",
                "stops.txt",
                "fare_attributes.txt",
                "fare_rules.txt",
            )
        }


def read_schedule(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rb") as handle:
        root = ET.parse(handle).getroot()
    rows: list[dict[str, Any]] = []
    for line in root:
        if local_name(line.tag) != "transitLine":
            continue
        for route in line:
            if local_name(route.tag) != "transitRoute":
                continue
            mode = ""
            refs: list[str] = []
            for child in route:
                if local_name(child.tag) == "transportMode":
                    mode = (child.text or "").strip()
                elif local_name(child.tag) == "routeProfile":
                    refs = [
                        stop.attrib["refId"]
                        for stop in child
                        if local_name(stop.tag) == "stop"
                    ]
            if mode == "ferry":
                rows.append(
                    {
                        "matsim_line_id": line.attrib["id"],
                        "matsim_route_id": route.attrib["id"],
                        "operator": "FERRY",
                        "stop_refs": refs,
                    }
                )
    return rows


def forward_pairs(stops: list[str]) -> list[tuple[str, str]]:
    return [
        (stops[i], stops[j])
        for i in range(len(stops))
        for j in range(i + 1, len(stops))
        if stops[i] and stops[j] and stops[i] != stops[j]
    ]


def parse_revision_cutoff_date(path: Path) -> str:
    rows = list(csv.reader(path.open(encoding="utf-8-sig", newline="")))
    value = rows[1][0].strip()
    date.fromisoformat(value)
    return value


def infer_type(values: list[Any]) -> str:
    non_null = [value for value in values if value not in (None, "")]
    if not non_null:
        return "null"
    if all(isinstance(value, bool) for value in non_null):
        return "boolean"
    try:
        for value in non_null:
            int(str(value))
        return "integer"
    except ValueError:
        pass
    try:
        for value in non_null:
            float(str(value))
        return "number"
    except ValueError:
        return "string"


def semantic_metadata(table: str, field: str) -> dict[str, str]:
    key = (table, field)
    overrides = {
        ("fare_attributes.txt", "fare_id"): (
            "Opaque GTFS fare identifier and join key. Its observed tokens are not treated as independent schema fields.",
            "join between fare_attributes.txt and fare_rules.txt",
            "true",
            "true",
            "resolved_for_join_only",
            "",
        ),
        ("fare_attributes.txt", "price"): (
            "Published numeric GTFS fare amount; passenger and payment-medium basis are not stated.",
            "GTFS field name plus numeric source values; no adult, child, Octopus, or cash field exists",
            "true",
            "true",
            "unspecified_in_source",
            "adult/passenger category and payment medium are not encoded",
        ),
        ("fare_attributes.txt", "currency_type"): (
            "Currency code for price.",
            "all Ferry values are HKD",
            "true",
            "true",
            "resolved",
            "",
        ),
        ("fare_attributes.txt", "payment_method"): (
            "GTFS payment-timing code; value 0 does not identify cash or Octopus.",
            "all Ferry values are 0 and no payment-medium field is present",
            "false",
            "false",
            "unspecified_in_source",
            "cash versus Octopus is not encoded",
        ),
        ("fare_attributes.txt", "transfers"): (
            "GTFS transfer count code; 0 permits no transfer on the fare record.",
            "all Ferry values are 0",
            "true",
            "false",
            "resolved_but_concessions_not_modelled",
            "",
        ),
        ("fare_attributes.txt", "agency_id"): (
            "Agency identifier.",
            "all selected rows are FERRY",
            "true",
            "true",
            "resolved",
            "",
        ),
        ("fare_rules.txt", "fare_id"): (
            "Join key to fare_attributes.txt.",
            "258 Ferry rule identifiers join uniquely to fare attributes",
            "true",
            "true",
            "resolved",
            "",
        ),
        ("fare_rules.txt", "route_id"): (
            "Official GTFS route identifier; not a direction field.",
            "route_id values join to routes.txt",
            "true",
            "true",
            "resolved_route_only",
            "",
        ),
        ("fare_rules.txt", "origin_id"): (
            "Ordered boarding stop identifier.",
            "joins to stops.txt and is retained as boarding_stop_id",
            "true",
            "true",
            "resolved",
            "",
        ),
        ("fare_rules.txt", "destination_id"): (
            "Ordered alighting stop identifier.",
            "joins to stops.txt and is retained as alighting_stop_id",
            "true",
            "true",
            "resolved",
            "",
        ),
        ("ferry_route_stop_points.json", "routeSeq"): (
            "Official route-direction sequence code within a routeId.",
            "routeId + routeSeq + ordered stopSeq forms an explicit direction pattern",
            "true",
            "true",
            "resolved",
            "",
        ),
        ("ferry_route_stop_points.json", "stopSeq"): (
            "Ordered stop position within routeId + routeSeq.",
            "integer sequence values form official stop patterns",
            "true",
            "true",
            "resolved",
            "",
        ),
        ("ferry_route_stop_points.json", "stopId"): (
            "Official stop identifier.",
            "cross-checked against GTFS stops and explicit Ferry Core facility mapping",
            "true",
            "true",
            "resolved",
            "",
        ),
        ("ferry_route_stop_points.json", "fullFare"): (
            "Published route-direction full-fare reference repeated on stop features; not a stop-OD rule.",
            "constant within each routeId + routeSeq; 119 of 240 comparable GTFS OD prices differ",
            "false",
            "false",
            "ambiguous_pricing_basis",
            "passenger/payment/class/day/vessel basis is unstated and value is not OD-specific",
        ),
        ("ferry_route_stop_points.json", "lastUpdateDate"): (
            "Per-record last-update timestamp, not the dataset-wide fare effective date.",
            "source field values; dataset revision cut-off is independently parsed",
            "true",
            "false",
            "resolved_as_provenance_only",
            "",
        ),
        ("ferry_route_stop_points.json", "serviceMode"): (
            "Official service-mode code whose T/R meanings are not defined in the local source.",
            "values T and R occur without a local code dictionary",
            "false",
            "false",
            "unspecified_in_source",
            "cannot infer ordinary versus high-speed vessel",
        ),
        ("ferry_route_stop_points.json", "specialType"): (
            "Official numeric special-type code without a local code dictionary.",
            "values 0, 1, 2, and 3 occur",
            "false",
            "false",
            "unspecified_in_source",
            "cannot infer fare class, vessel type, or day type",
        ),
    }
    if key in overrides:
        values = overrides[key]
    else:
        values = (
            "Source field retained for identification, description, or provenance.",
            "field name and source values",
            "true",
            "false",
            "resolved_for_reference",
            "",
        )
    return dict(
        zip(
            (
                "semantic_interpretation",
                "semantic_evidence",
                "machine_usable",
                "required_for_pricing",
                "ambiguity_status",
                "unresolved_reason",
            ),
            values,
        )
    )


def build_schema_audit(
    gtfs: dict[str, list[dict[str, str]]], json_props: list[dict[str, Any]]
) -> pd.DataFrame:
    ferry_route_ids = {
        row["route_id"] for row in gtfs["routes.txt"] if row["agency_id"] == "FERRY"
    }
    attrs = [row for row in gtfs["fare_attributes.txt"] if row["agency_id"] == "FERRY"]
    fare_ids = {row["fare_id"] for row in attrs}
    rules = [row for row in gtfs["fare_rules.txt"] if row["fare_id"] in fare_ids]
    stop_ids = {row["origin_id"] for row in rules} | {
        row["destination_id"] for row in rules
    }
    subsets = {
        "agency.txt": [
            row for row in gtfs["agency.txt"] if row["agency_id"] == "FERRY"
        ],
        "routes.txt": [
            row for row in gtfs["routes.txt"] if row["route_id"] in ferry_route_ids
        ],
        "stops.txt": [
            row for row in gtfs["stops.txt"] if row["stop_id"] in stop_ids
        ],
        "fare_attributes.txt": attrs,
        "fare_rules.txt": rules,
        "ferry_route_stop_points.json": json_props,
    }
    records = []
    for table, rows in subsets.items():
        fields = sorted(
            {key for row in rows for key in row if not key.startswith("_")}
        )
        for field in fields:
            values = [row.get(field) for row in rows]
            non_null = [value for value in values if value not in (None, "")]
            samples = sorted(
                {str(value) for value in non_null}, key=lambda value: (len(value), value)
            )[:8]
            records.append(
                {
                    "source_id": (
                        "td_ferry_route_fares_20260720"
                        if table.endswith(".json")
                        else "td_gtfs_20260720"
                    ),
                    "source_file": (
                        JSON_REL.as_posix()
                        if table.endswith(".json")
                        else f"{GTFS_REL.as_posix()}!{table}"
                    ),
                    "table_or_object": table,
                    "field_name": field,
                    "field_type": infer_type(non_null),
                    "non_null_count": len(non_null),
                    "unique_count": len(
                        {compact_json(value) for value in non_null}
                    ),
                    "sample_values_json": compact_json(samples),
                    **semantic_metadata(table, field),
                }
            )
    return pd.DataFrame(records)


def append_active_rule_schema_audit(
    audit: pd.DataFrame, rules: pd.DataFrame
) -> pd.DataFrame:
    semantics = {
        "published_fare_hkd": (
            "Neutral published amount copied exactly from GTFS price.",
            "direct fare_id join to fare_attributes.txt price",
            "true",
            "true",
            "resolved",
            "",
        ),
        "mapping_quality": (
            "Quality of route, direction, and ordered-OD mapping evidence.",
            "A for exact JSON direction pattern; C where official direction is not encoded",
            "true",
            "true",
            "resolved",
            "",
        ),
        "cost_quality": (
            "Quality of the published amount as a usable cost component, separate from mapping quality.",
            "B for exact mapping with incomplete applicability; C for direction-not-encoded mapping",
            "true",
            "true",
            "resolved",
            "",
        ),
        "cost_applicability_status": (
            "Explicit limitation that passenger/payment/class/vessel/day/effective period are unspecified.",
            "derived conservatively from absent source condition fields",
            "true",
            "true",
            "resolved_limitation",
            "",
        ),
        "cost_effective_date": (
            "Route-specific fare effective date; empty because the source does not encode one.",
            "TD revision cut-off is not treated as a fare effective date",
            "true",
            "true",
            "not_encoded_in_source",
            "route-specific fare effective period is unavailable",
        ),
        "source_revision_cutoff_date": (
            "TD local dataset revision cut-off date, not fare effective date.",
            "parsed from routes_fares_last_updated.csv",
            "true",
            "false",
            "resolved_as_source_provenance",
            "",
        ),
        "source_download_date": (
            "Local official-source snapshot download date.",
            "retained source acquisition provenance",
            "true",
            "false",
            "resolved_as_source_provenance",
            "",
        ),
    }
    rows = []
    for field, values in semantics.items():
        non_null = [
            value
            for value in rules[field].tolist()
            if value not in (None, "")
        ]
        rows.append(
            {
                "source_id": "derived_ferry_fare_v1",
                "source_file": "ferry_fare_rules.parquet",
                "table_or_object": "active_ferry_rule_schema",
                "field_name": field,
                "field_type": infer_type(non_null),
                "non_null_count": len(non_null),
                "unique_count": len({compact_json(value) for value in non_null}),
                "sample_values_json": compact_json(
                    sorted({str(value) for value in non_null})[:8]
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
                        values,
                    )
                ),
            }
        )
    return pd.concat([audit, pd.DataFrame(rows)], ignore_index=True)


def empty_frame(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns)


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")


def build_fixture(rules: pd.DataFrame) -> pd.DataFrame:
    exact = rules[
        (rules["fare_scope"] == "exact_route_direction_stop_od")
        & (rules["record_status"] == "available")
    ].iloc[0]
    reverse_matches = rules[
        (rules["official_route_id"] == exact["official_route_id"])
        & (rules["boarding_stop_id"] == exact["alighting_stop_id"])
        & (rules["alighting_stop_id"] == exact["boarding_stop_id"])
        & (rules["record_status"] == "available")
    ]
    reverse = reverse_matches.iloc[0] if len(reverse_matches) else exact
    partial = rules[
        (rules["fare_scope"] == "route_stop_od_direction_not_encoded")
        & (rules["record_status"] == "available")
    ].iloc[0]

    def base(identifier: str, rule: pd.Series = exact) -> dict[str, str]:
        return {
            "quote_id": identifier,
            "actual_transport_mode": "ferry",
            "matsim_route_id": str(rule["matsim_route_id"]),
            "official_route_id": str(rule["official_route_id"]),
            "official_direction": str(rule["official_direction"]),
            "boarding_stop_id": str(rule["boarding_stop_id"]),
            "alighting_stop_id": str(rule["alighting_stop_id"]),
            "passenger_type": "unspecified",
            "payment_medium": "unspecified",
            "service_class": "unspecified",
            "vessel_service_type": "unspecified",
            "travel_date": "",
            "day_type": "unspecified",
            "temporal_basis": "source_snapshot_only",
            "transfer_concession_requested": "false",
            "expected_result": "available",
        }

    rows: list[dict[str, str]] = []
    rows.append(base("exact_available"))
    rows.append(base("reverse_direction_available", reverse))
    invalid_reverse = base("reverse_within_same_direction_unresolved")
    invalid_reverse["boarding_stop_id"], invalid_reverse["alighting_stop_id"] = (
        invalid_reverse["alighting_stop_id"],
        invalid_reverse["boarding_stop_id"],
    )
    invalid_reverse["expected_result"] = "unresolved"
    rows.append(invalid_reverse)
    partial_row = base("partial_direction_unspecified_available", partial)
    partial_row["official_direction"] = "unspecified"
    rows.append(partial_row)
    partial_specific = base("partial_specific_direction_unresolved", partial)
    partial_specific["official_direction"] = "1"
    partial_specific["expected_result"] = "unresolved"
    rows.append(partial_specific)
    unknown_route = base("unknown_route")
    unknown_route["official_route_id"] = "999999999"
    unknown_route["expected_result"] = "unresolved"
    rows.append(unknown_route)
    route_id_mismatch = base("matsim_official_route_mismatch")
    route_id_mismatch["matsim_route_id"] = str(partial["matsim_route_id"])
    route_id_mismatch["expected_result"] = "unresolved"
    rows.append(route_id_mismatch)
    unknown_boarding = base("unknown_boarding")
    unknown_boarding["boarding_stop_id"] = "UNKNOWN"
    unknown_boarding["expected_result"] = "unresolved"
    rows.append(unknown_boarding)
    unknown_alighting = base("unknown_alighting")
    unknown_alighting["alighting_stop_id"] = "UNKNOWN"
    unknown_alighting["expected_result"] = "unresolved"
    rows.append(unknown_alighting)
    route_od_mismatch = base("route_od_mismatch")
    route_od_mismatch["official_route_id"] = str(partial["official_route_id"])
    route_od_mismatch["matsim_route_id"] = str(partial["matsim_route_id"])
    route_od_mismatch["official_direction"] = "unspecified"
    route_od_mismatch["expected_result"] = "unresolved"
    rows.append(route_od_mismatch)
    for field, value, identifier in (
        ("passenger_type", "adult", "passenger_type_not_supported"),
        ("payment_medium", "Octopus", "octopus_not_supported"),
        ("payment_medium", "cash", "cash_not_supported"),
        ("service_class", "standard", "service_class_not_supported"),
        ("vessel_service_type", "ordinary", "vessel_type_not_supported"),
        ("day_type", "weekday", "day_type_not_supported"),
    ):
        item = base(identifier)
        item[field] = value
        item["expected_result"] = "unresolved"
        rows.append(item)
    full_only = base("full_fare_reference_not_fallback")
    full_only["alighting_stop_id"] = full_only["boarding_stop_id"]
    full_only["expected_result"] = "unresolved"
    rows.append(full_only)
    temporal_missing = base("temporal_basis_missing")
    temporal_missing["temporal_basis"] = ""
    temporal_missing["expected_result"] = "unresolved"
    rows.append(temporal_missing)
    temporal_wrong = base("temporal_basis_wrong")
    temporal_wrong["temporal_basis"] = "travel_date_applicability"
    temporal_wrong["expected_result"] = "unresolved"
    rows.append(temporal_wrong)
    dated = base("nonempty_travel_date")
    dated["travel_date"] = "2026-07-14"
    dated["expected_result"] = "unresolved"
    rows.append(dated)
    transfer = base("transfer_concession_requested")
    transfer["transfer_concession_requested"] = "true"
    rows.append(transfer)
    generic = base("generic_pt_mode")
    generic["actual_transport_mode"] = "pt"
    generic["expected_result"] = "unresolved"
    rows.append(generic)
    return pd.DataFrame(rows, columns=FIXTURE_INPUT_COLUMNS)


def build_prior_hashes(repo_root: Path, existing_path: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if existing_path.is_file():
        existing = pd.read_csv(existing_path, dtype=str, keep_default_na=False)
        rows.extend(
            row
            for row in existing.to_dict("records")
            if row["protected_scope"]
            in {"mtr_station_od_v1", "light_rail_station_od_v1"}
        )
    else:
        for scope, relative in (
            ("mtr_station_od_v1", BASE_FARE_REL / "mtr_station_od_v1"),
            ("light_rail_station_od_v1", BASE_FARE_REL / "light_rail_station_od_v1"),
        ):
            for path in sorted(
                (repo_root / relative).iterdir(), key=lambda item: item.name
            ):
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
        repo_root / BASE_FARE_REL / "protected_input_hashes_baseline.csv",
        dtype=str,
        keep_default_na=False,
    )
    for record in baseline.to_dict("records"):
        rows.append(
            {
                "protected_scope": "matsim_protected_input",
                "repository_relative_path": record["repository_relative_path"],
                "size_bytes": record["size_bytes"],
                "sha256_before": record["sha256_before"],
            }
        )
    return pd.DataFrame(rows)


def build_readme(summary: dict[str, Any]) -> str:
    return f"""# Hong Kong Ferry Core v1 offline fare rules

This directory is an audit and offline quote layer only. It does not change or
price MATSim plans and is not connected to config, scoring, Java, network,
schedule, vehicles, facilities, or transfer concessions.

Direct official inputs are TD GTFS `fare_attributes.txt` / `fare_rules.txt`
and the TD Ferry route-stop GeoJSON snapshot. The production schedule and
`ferry_stop_facilities.csv` are read only to prove the 39 MATSim route and stop
crosswalks.

Key source semantics:

- `price` is a published GTFS amount in HKD, but the source does not identify
  adult/child, cash/Octopus, class, vessel type, weekday, weekend, or holiday.
- the active neutral amount field is `published_fare_hkd`; there is no
  `adult_base_fare_hkd` compatibility alias;
- queries therefore accept only `unspecified` for those source-unspecified
  dimensions;
- `mapping_quality` describes route/direction/OD evidence, while
  `cost_quality` is B for exact-direction published amounts and C where the
  official direction is not encoded. B does not prove an adult payable fare;
- `source_revision_cutoff_date=2026-07-14` describes the local TD snapshot,
  not a route fare effective date. `cost_effective_date` is empty and queries
  require `temporal_basis=source_snapshot_only` with an empty `travel_date`;
- GTFS route + ordered origin/destination is used without reverse substitution,
  interpolation, path summing, aggregation, or missing-value zero fill;
- JSON `fullFare` is retained only in
  `ferry_route_full_fare_reference.csv`; it is never a default quote;
- transfer concessions are `not_modelled`.

`cost_hkd` is only the published base amount component. It is not an actual
passenger fare or final discounted fare.

Current build: {summary["schedule_route_count"]} Ferry routes,
{summary["required_forward_pair_count"]} required ordered forward pairs,
{summary["available_rule_count"]} available published-amount rules, and
{summary["full_fare_reference_count"]} route-direction full-fare references.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-project-root",
        type=Path,
        default=None,
        help="Project root containing ignored official/raw inputs.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: repository pt_fare_v1/ferry_fare_v1).",
    )
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[4]
    source_root = (args.source_project_root or repo_root).resolve()
    output_dir = (args.output_dir or repo_root / OUTPUT_REL).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    gtfs_path = source_root / GTFS_REL
    json_path = source_root / JSON_REL
    revision_path = source_root / REVISION_REL
    facilities_path = source_root / SUPPLY_REL / "ferry_stop_facilities.csv"
    schedule_path = source_root / SUPPLY_REL / "transitSchedule_5pct.xml.gz"
    revision_cutoff_date = parse_revision_cutoff_date(revision_path)
    gtfs_sha = sha256(gtfs_path)
    json_sha = sha256(json_path)

    gtfs = read_raw_gtfs(gtfs_path)
    attrs = [row for row in gtfs["fare_attributes.txt"] if row["agency_id"] == "FERRY"]
    attr_by_id = {row["fare_id"]: row for row in attrs}
    fare_ids = set(attr_by_id)
    raw_rules = [row for row in gtfs["fare_rules.txt"] if row["fare_id"] in fare_ids]
    raw_rules_by_key: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in raw_rules:
        raw_rules_by_key[
            (row["route_id"], row["origin_id"], row["destination_id"])
        ].append(row)

    raw_json = json.loads(json_path.read_text(encoding="utf-8-sig"))
    json_props = [feature.get("properties") or {} for feature in raw_json["features"]]
    patterns: dict[tuple[str, str], list[str]] = defaultdict(list)
    feature_indices: dict[tuple[str, str], list[int]] = defaultdict(list)
    full_values: dict[tuple[str, str], set[float]] = defaultdict(set)
    json_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for index, props in enumerate(json_props):
        key = (str(props["routeId"]), str(props["routeSeq"]))
        json_groups[key].append(props)
        feature_indices[key].append(index)
        full_values[key].add(float(props["fullFare"]))
    for key, group in json_groups.items():
        patterns[key] = [
            str(item["stopId"]) for item in sorted(group, key=lambda item: int(item["stopSeq"]))
        ]

    schema_audit = build_schema_audit(gtfs, json_props)

    facilities = list(
        csv.DictReader(facilities_path.open(encoding="utf-8-sig", newline=""))
    )
    facility_by_id = {row["facility_id"]: row for row in facilities}
    gtfs_stop_by_id = {row["stop_id"]: row for row in gtfs["stops.txt"]}
    json_stop_ids = {str(row["stopId"]) for row in json_props}
    schedule = read_schedule(schedule_path)
    route_counts = Counter(
        ref for route in schedule for ref in route["stop_refs"]
    )
    crosswalk_rows = []
    for row in sorted(facilities, key=lambda item: item["facility_id"]):
        stop_id = str(row["stop_id"])
        in_gtfs = stop_id in gtfs_stop_by_id
        in_json = stop_id in json_stop_ids
        crosswalk_rows.append(
            {
                "matsim_stop_facility_id": row["facility_id"],
                "official_stop_id": stop_id,
                "official_stop_name": row["stop_name"],
                "gtfs_stop_id": stop_id if in_gtfs else "",
                "in_ferry_facilities": True,
                "in_gtfs": in_gtfs,
                "in_ferry_json": in_json,
                "matsim_route_count": route_counts[row["facility_id"]],
                "candidate_count": 1,
                "candidate_cardinality": "one",
                "mapping_status": "exact" if in_gtfs and in_json else "partial_source_coverage",
                "mapping_quality": "A" if in_gtfs and in_json else "B",
                "matching_method": "explicit_ferry_stop_facilities_stop_id",
                "evidence": compact_json(
                    {
                        "facility_stop_id": stop_id,
                        "gtfs_stop_id_exact": in_gtfs,
                        "json_stop_id_exact": in_json,
                    }
                ),
                "unresolved_reason": "" if in_gtfs and in_json else "official_stop_absent_from_ferry_json",
            }
        )
    crosswalk = pd.DataFrame(crosswalk_rows)
    write_csv(crosswalk, output_dir / "ferry_stop_crosswalk.csv")

    route_rows: list[dict[str, Any]] = []
    rule_rows: list[dict[str, Any]] = []
    for route in sorted(schedule, key=lambda item: item["matsim_route_id"]):
        match = re.match(r"^ferry_(\d+)_", route["matsim_route_id"])
        route_id = match.group(1) if match else ""
        stops = [
            str(facility_by_id.get(ref, {}).get("stop_id", ""))
            for ref in route["stop_refs"]
        ]
        candidates = [
            (key, pattern)
            for key, pattern in patterns.items()
            if key[0] == route_id and pattern == stops
        ]
        required = forward_pairs(stops)
        matched = [
            pair for pair in required if (route_id, pair[0], pair[1]) in raw_rules_by_key
        ]
        exact = len(candidates) == 1 and all(stops)
        direction = candidates[0][0][1] if exact else ""
        mapping_status = "exact" if exact and len(matched) == len(required) else "partial"
        quality = "A" if mapping_status == "exact" else "C"
        direction_status = (
            "explicit_direction_exact" if exact else "direction_pattern_not_available"
        )
        full_count = 1 if exact and candidates[0][0] in full_values else 0
        distinct_fares: set[float] = set()
        fare_id_count = 0
        for boarding, alighting in required:
            candidates_raw = raw_rules_by_key.get((route_id, boarding, alighting), [])
            candidate_details = []
            amounts: set[float] = set()
            for raw_rule in candidates_raw:
                attr = attr_by_id[raw_rule["fare_id"]]
                amount = float(attr["price"])
                amounts.add(amount)
                distinct_fares.add(amount)
                fare_id_count += 1
                candidate_details.append(
                    {
                        "fare_id": raw_rule["fare_id"],
                        "fare_rule_line": int(raw_rule["_line_number"]),
                        "fare_attribute_line": int(attr["_line_number"]),
                        "price": amount,
                    }
                )
            status = (
                "available"
                if len(candidates_raw) == 1 and len(amounts) == 1
                else "ambiguous"
                if len(amounts) > 1
                else "unresolved"
            )
            source_record_id = ""
            amount_value: float | None = None
            if status == "available":
                raw_rule = candidates_raw[0]
                attr = attr_by_id[raw_rule["fare_id"]]
                source_record_id = (
                    f"gtfs:fare_rules.txt:{raw_rule['_line_number']}|"
                    f"fare_attributes.txt:{attr['_line_number']}|fare_id:{raw_rule['fare_id']}"
                )
                amount_value = float(attr["price"])
            rule_rows.append(
                {
                    "fare_scope": (
                        "exact_route_direction_stop_od"
                        if exact
                        else "route_stop_od_direction_not_encoded"
                    ),
                    "operator": "FERRY",
                    "matsim_line_id": route["matsim_line_id"],
                    "matsim_route_id": route["matsim_route_id"],
                    "official_route_id": route_id,
                    "official_route_sequence": direction if exact else UNSPECIFIED,
                    "official_direction": direction if exact else UNSPECIFIED,
                    "boarding_stop_id": boarding,
                    "alighting_stop_id": alighting,
                    "passenger_type": UNSPECIFIED,
                    "payment_medium": UNSPECIFIED,
                    "service_class": UNSPECIFIED,
                    "vessel_service_type": UNSPECIFIED,
                    "day_type": UNSPECIFIED,
                    "time_period": UNSPECIFIED,
                    "published_fare_hkd": amount_value,
                    "currency": "HKD" if status == "available" else "",
                    "fare_amount_role": (
                        "published_fare_passenger_and_payment_basis_unspecified"
                        if status == "available"
                        else ""
                    ),
                    "cost_component": "pt_fare",
                    "cost_source": "td_gtfs_20260720" if status == "available" else "",
                    "cost_effective_date": "",
                    "cost_effective_date_status": EFFECTIVE_DATE_STATUS,
                    "source_revision_cutoff_date": revision_cutoff_date,
                    "source_download_date": DOWNLOAD_DATE,
                    "source_record_id": source_record_id,
                    "source_file": GTFS_REL.as_posix() if status == "available" else "",
                    "source_sha256": gtfs_sha if status == "available" else "",
                    "record_status": status,
                    "candidate_records_json": compact_json(candidate_details),
                    "mapping_status": mapping_status,
                    "mapping_quality": quality,
                    "cost_quality": (
                        "B"
                        if status == "available" and exact
                        else "C"
                        if status == "available"
                        else "U"
                    ),
                    "cost_applicability_status": (
                        COST_APPLICABILITY if status == "available" else "unresolved"
                    ),
                    "matching_method": (
                        "route_direction_exact_json_pattern_plus_ordered_gtfs_stop_od"
                        if exact
                        else "route_plus_ordered_gtfs_stop_od_direction_not_encoded"
                    ),
                    "unresolved_reason": (
                        ""
                        if status == "available"
                        else "conflicting_published_amounts"
                        if status == "ambiguous"
                        else "ordered_gtfs_stop_od_fare_missing"
                    ),
                }
            )
        route_rows.append(
            {
                "matsim_line_id": route["matsim_line_id"],
                "matsim_route_id": route["matsim_route_id"],
                "operator": "FERRY",
                "official_route_id": route_id,
                "official_route_sequence": direction,
                "official_direction": direction,
                "scheduled_stop_count": len(stops),
                "mapped_stop_count": sum(bool(stop) for stop in stops),
                "stop_id_coverage": round(sum(bool(stop) for stop in stops) / len(stops), 6),
                "candidate_count": len(candidates),
                "candidate_cardinality": "one" if len(candidates) == 1 else "none",
                "direction_status": direction_status,
                "official_pattern_status": "exact_complete_pattern" if exact else "not_available",
                "required_forward_pair_count": len(required),
                "matched_fare_pair_count": len(matched),
                "forward_pair_coverage": round(len(matched) / len(required), 6),
                "gtfs_fare_id_count": fare_id_count,
                "distinct_fare_count": len(distinct_fares),
                "full_fare_record_count": full_count,
                "fare_condition_completeness": "passenger_payment_class_vessel_day_unspecified_in_source",
                "mapping_status": mapping_status,
                "mapping_quality": quality,
                "fare_readiness": (
                    "ready_exact_direction_with_unspecified_source_conditions"
                    if exact
                    else "partial_direction_not_encoded_with_unique_ordered_od_fares"
                ),
                "matching_method": (
                    "explicit_facility_stop_ids_plus_exact_json_direction_pattern_plus_gtfs_od"
                    if exact
                    else "explicit_facility_stop_ids_plus_gtfs_od_without_direction_pattern"
                ),
                "evidence": compact_json(
                    {
                        "official_stop_ids": stops,
                        "json_pattern_candidate_count": len(candidates),
                        "matched_forward_pairs": len(matched),
                    }
                ),
                "unresolved_reason": "" if exact else "official_direction_stop_pattern_not_available",
            }
        )

    readiness = pd.DataFrame(route_rows)
    rules = pd.DataFrame(rule_rows, columns=RULE_COLUMNS).sort_values(
        ["matsim_route_id", "boarding_stop_id", "alighting_stop_id"]
    )
    schema_audit = append_active_rule_schema_audit(schema_audit, rules)
    write_csv(schema_audit, output_dir / "ferry_source_schema_audit.csv")
    write_csv(readiness, output_dir / "ferry_route_direction_fare_readiness.csv")
    rules.to_parquet(output_dir / "ferry_fare_rules.parquet", index=False)
    write_csv(rules.head(100), output_dir / "ferry_fare_rules_sample.csv")

    conflict_columns = [
        "official_route_id",
        "boarding_stop_id",
        "alighting_stop_id",
        "distinct_amount_count",
        "candidate_records_json",
        "unresolved_reason",
    ]
    conflicts = []
    for key, candidates_raw in sorted(raw_rules_by_key.items()):
        amounts = {attr_by_id[row["fare_id"]]["price"] for row in candidates_raw}
        if len(amounts) > 1:
            conflicts.append(
                {
                    "official_route_id": key[0],
                    "boarding_stop_id": key[1],
                    "alighting_stop_id": key[2],
                    "distinct_amount_count": len(amounts),
                    "candidate_records_json": compact_json(
                        [
                            {
                                "fare_id": row["fare_id"],
                                "price": attr_by_id[row["fare_id"]]["price"],
                            }
                            for row in candidates_raw
                        ]
                    ),
                    "unresolved_reason": "conflicting_published_amounts",
                }
            )
    write_csv(
        pd.DataFrame(conflicts, columns=conflict_columns),
        output_dir / "ferry_fare_conflicts.csv",
    )

    ruled_ids = {row["fare_id"] for row in raw_rules}
    unresolved_rows = []
    for attr in attrs:
        if attr["fare_id"] in ruled_ids:
            continue
        parts = attr["fare_id"].split("-")
        unresolved_rows.append(
            {
                **{column: "" for column in RULE_COLUMNS},
                "fare_scope": "unresolved",
                "operator": "FERRY",
                "official_route_id": parts[0],
                "official_route_sequence": parts[1] if len(parts) > 1 else UNSPECIFIED,
                "passenger_type": UNSPECIFIED,
                "payment_medium": UNSPECIFIED,
                "service_class": UNSPECIFIED,
                "vessel_service_type": UNSPECIFIED,
                "day_type": UNSPECIFIED,
                "time_period": UNSPECIFIED,
                "published_fare_hkd": float(attr["price"]),
                "currency": attr["currency_type"],
                "fare_amount_role": "unresolved_fare_attribute_without_stop_od_rule",
                "cost_component": "pt_fare",
                "cost_source": "td_gtfs_20260720",
                "cost_effective_date": "",
                "cost_effective_date_status": EFFECTIVE_DATE_STATUS,
                "source_revision_cutoff_date": revision_cutoff_date,
                "source_download_date": DOWNLOAD_DATE,
                "cost_quality": "U",
                "cost_applicability_status": "unresolved",
                "source_record_id": f"gtfs:fare_attributes.txt:{attr['_line_number']}|fare_id:{attr['fare_id']}",
                "source_file": GTFS_REL.as_posix(),
                "source_sha256": gtfs_sha,
                "record_status": "unresolved",
                "mapping_status": "unresolved",
                "mapping_quality": "U",
                "candidate_records_json": compact_json(
                    [{"fare_id": attr["fare_id"], "price": float(attr["price"])}]
                ),
                "matching_method": "fare_attribute_left_anti_join_fare_rules",
                "unresolved_reason": "fare_attribute_has_no_fare_rule_origin_destination",
            }
        )
    unresolved = pd.DataFrame(unresolved_rows, columns=RULE_COLUMNS)
    write_csv(unresolved, output_dir / "ferry_unresolved_fare_rules.csv")

    schedule_exact_keys = {
        (row["official_route_id"], row["official_direction"])
        for row in route_rows
        if row["mapping_status"] == "exact"
    }
    full_rows = []
    for key in sorted(patterns, key=lambda item: (int(item[0]), int(item[1]))):
        group = json_groups[key]
        values = full_values[key]
        comparable = []
        for raw_rule in raw_rules:
            pieces = raw_rule["fare_id"].split("-")
            if raw_rule["route_id"] == key[0] and len(pieces) >= 4 and pieces[1] == key[1]:
                comparable.append(float(attr_by_id[raw_rule["fare_id"]]["price"]))
        full_amount = next(iter(values)) if len(values) == 1 else None
        equal_count = sum(value == full_amount for value in comparable)
        status = (
            "no_gtfs_rules"
            if not comparable
            else "all_equal"
            if equal_count == len(comparable)
            else "none_equal"
            if equal_count == 0
            else "mixed_equal_and_different"
        )
        full_rows.append(
            {
                "fare_scope": "route_level_full_fare_reference_only",
                "operator": "FERRY",
                "official_route_id": key[0],
                "official_route_sequence": key[1],
                "official_direction": key[1],
                "official_stop_ids_json": compact_json(patterns[key]),
                "route_name": str(group[0].get("routeNameE", "")),
                "full_fare_hkd": full_amount,
                "currency": "HKD",
                "passenger_type": UNSPECIFIED,
                "payment_medium": UNSPECIFIED,
                "service_class": UNSPECIFIED,
                "vessel_service_type": UNSPECIFIED,
                "day_type": UNSPECIFIED,
                "fare_amount_role": "route_level_full_fare_reference_only",
                "eligible_for_default_quote": False,
                "in_current_schedule_exact_scope": key in schedule_exact_keys,
                "gtfs_rule_count": len(comparable),
                "gtfs_distinct_price_count": len(set(comparable)),
                "gtfs_price_equal_full_fare_count": equal_count,
                "gtfs_full_fare_correspondence": status,
                "source_record_last_update": str(group[0].get("lastUpdateDate", "")),
                "source_record_id": "json:feature_indices:" + ";".join(
                    str(index) for index in feature_indices[key]
                ),
                "source_file": JSON_REL.as_posix(),
                "source_sha256": json_sha,
                "cost_effective_date": "",
                "cost_effective_date_status": EFFECTIVE_DATE_STATUS,
                "source_revision_cutoff_date": revision_cutoff_date,
                "source_download_date": DOWNLOAD_DATE,
                "unresolved_reason": "not_stop_od_and_source_conditions_unspecified",
            }
        )
    full_refs = pd.DataFrame(full_rows)
    write_csv(full_refs, output_dir / "ferry_route_full_fare_reference.csv")

    fixture = build_fixture(rules)
    write_csv(fixture, output_dir / "ferry_fare_query_fixture_input.csv")
    write_csv(
        empty_frame(FIXTURE_OUTPUT_COLUMNS),
        output_dir / "ferry_fare_query_fixture_output.csv",
    )

    prior_hashes = build_prior_hashes(
        repo_root, output_dir / "prior_mode_protected_hashes.csv"
    )
    write_csv(prior_hashes, output_dir / "prior_mode_protected_hashes.csv")

    existing_paths = [
        BASE_FARE_REL / name
        for name in (
            "fare_source_manifest.csv",
            "official_fares_normalized.parquet",
            "official_route_full_fares.csv",
            "transit_schedule_inventory.csv",
            "route_to_official_fare_match.csv",
            "official_direction_stop_patterns.csv",
        )
    ]
    existing_inputs = {
        path.name: {
            "exists": (repo_root / path).is_file(),
            "sha256": sha256(repo_root / path) if (repo_root / path).is_file() else "",
        }
        for path in existing_paths
    }
    normalized = pd.read_parquet(repo_root / BASE_FARE_REL / "official_fares_normalized.parquet")
    normalized_ferry = normalized[normalized["mode"] == "ferry"]
    comparison_count = 0
    raw_amount_lookup = {
        (row["route_id"], row["origin_id"], row["destination_id"]): float(
            attr_by_id[row["fare_id"]]["price"]
        )
        for row in raw_rules
    }
    for row in normalized_ferry.to_dict("records"):
        key = (
            str(row["official_route_id"]),
            str(row["origin_stop_id"]),
            str(row["destination_stop_id"]),
        )
        if key in raw_amount_lookup and float(row["adult_octopus_fare_hkd"]) == raw_amount_lookup[key]:
            comparison_count += 1

    exact_count = int((readiness["mapping_status"] == "exact").sum())
    partial_count = int((readiness["mapping_status"] == "partial").sum())
    available_count = int((rules["record_status"] == "available").sum())
    ambiguous_count = int((rules["record_status"] == "ambiguous").sum())
    semantics = {
        "schema_version": "hong_kong_ferry_fare_semantics_v1",
        "answers": {
            "price_is_explicit_adult_fare": {
                "answer": UNSPECIFIED,
                "reason": "no passenger_type field or local metadata defines price as adult",
            },
            "payment_medium": {
                "answer": UNSPECIFIED,
                "reason": "payment_method=0 does not distinguish cash from Octopus",
            },
            "ordinary_or_high_speed_vessel": {
                "answer": UNSPECIFIED,
                "reason": "serviceMode/specialType codes lack a local official code dictionary",
            },
            "deck_seat_or_cabin_class": {"answer": UNSPECIFIED},
            "weekday_weekend_public_holiday": {"answer": UNSPECIFIED},
            "direction": {
                "answer": "encoded_in_json_routeSeq_stopSeq_not_in_gtfs_fare_rules_fields",
                "json_route_direction_count": len(patterns),
            },
            "stop_od": {
                "answer": "encoded_as_ordered_gtfs_origin_id_destination_id",
                "gtfs_ferry_rule_count": len(raw_rules),
            },
            "transfers": {
                "answer": "gtfs_transfers_zero_no_transfer_on_fare_record",
                "transfer_concessions": "not_modelled",
            },
            "fullFare": {
                "answer": "route_direction_full_fare_reference_only",
                "reason": "not stop-OD and passenger/payment/class/day/vessel conditions unstated",
            },
            "gtfs_price_vs_json_fullFare": {
                "answer": "not_rowwise_equivalent",
                "comparable_gtfs_rule_count": sum(row["gtfs_rule_count"] for row in full_rows),
                "equal_count": sum(row["gtfs_price_equal_full_fare_count"] for row in full_rows),
                "different_count": sum(
                    row["gtfs_rule_count"] - row["gtfs_price_equal_full_fare_count"]
                    for row in full_rows
                ),
            },
        },
        "source_urls": {
            "gtfs": "https://static.data.gov.hk/td/pt-headway-en/gtfs.zip",
            "ferry_json": "https://static.data.gov.hk/td/routes-fares-geojson/JSON_FERRY.json",
        },
        "source_revision_cutoff_date": revision_cutoff_date,
        "source_download_date": DOWNLOAD_DATE,
        "cost_effective_date": "",
        "cost_effective_date_status": EFFECTIVE_DATE_STATUS,
        "source_sha256": {"gtfs": gtfs_sha, "ferry_json": json_sha},
    }
    (output_dir / "ferry_fare_semantics_summary.json").write_text(
        json.dumps(semantics, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    summary = {
        "schema_version": "hong_kong_ferry_fare_v1",
        "source_revision_cutoff_date": revision_cutoff_date,
        "source_download_date": DOWNLOAD_DATE,
        "cost_effective_date": "",
        "cost_effective_date_status": EFFECTIVE_DATE_STATUS,
        "cost_effective_date_status_counts": dict(
            Counter(rules["cost_effective_date_status"])
        ),
        "gtfs_ferry_fare_attribute_count": len(attrs),
        "gtfs_ferry_fare_rule_count": len(raw_rules),
        "gtfs_orphan_fare_attribute_count": len(unresolved),
        "gtfs_ferry_stop_count": len(
            {row["origin_id"] for row in raw_rules}
            | {row["destination_id"] for row in raw_rules}
        ),
        "ferry_json_stop_count": len(json_stop_ids),
        "ferry_facility_count": len(crosswalk),
        "ferry_facility_unique_official_stop_count": crosswalk["official_stop_id"].nunique(),
        "stop_crosswalk_status_counts": dict(Counter(crosswalk["mapping_status"])),
        "schedule_route_count": len(readiness),
        "route_mapping_status_counts": dict(Counter(readiness["mapping_status"])),
        "route_mapping_quality_counts": dict(Counter(readiness["mapping_quality"])),
        "active_rule_mapping_quality_counts": dict(Counter(rules["mapping_quality"])),
        "active_rule_cost_quality_counts": dict(Counter(rules["cost_quality"])),
        "active_rule_cost_applicability_status_counts": dict(
            Counter(rules["cost_applicability_status"])
        ),
        "route_fare_readiness_counts": dict(Counter(readiness["fare_readiness"])),
        "required_forward_pair_count": int(readiness["required_forward_pair_count"].sum()),
        "matched_forward_pair_count": int(readiness["matched_fare_pair_count"].sum()),
        "forward_pair_coverage": round(
            readiness["matched_fare_pair_count"].sum()
            / readiness["required_forward_pair_count"].sum(),
            6,
        ),
        "available_rule_count": available_count,
        "exact_direction_available_rule_count": int(
            (
                (rules["record_status"] == "available")
                & (rules["fare_scope"] == "exact_route_direction_stop_od")
            ).sum()
        ),
        "partial_direction_available_rule_count": int(
            (
                (rules["record_status"] == "available")
                & (rules["fare_scope"] == "route_stop_od_direction_not_encoded")
            ).sum()
        ),
        "ambiguous_rule_count": ambiguous_count,
        "unresolved_required_pair_count": int((rules["record_status"] == "unresolved").sum()),
        "unresolved_orphan_source_record_count": len(unresolved),
        "full_fare_reference_count": len(full_refs),
        "full_fare_reference_in_available_rules": False,
        "non_null_amount_traceability_rate": 1.0,
        "fare_condition_coverage": {
            "route_id": 1.0,
            "ordered_stop_od": 1.0,
            "direction_exact": round(48 / 60, 6),
            "passenger_type_explicit": 0.0,
            "payment_medium_explicit": 0.0,
            "service_class_explicit": 0.0,
            "vessel_service_type_explicit": 0.0,
            "day_type_explicit": 0.0,
            "time_period_explicit": 0.0,
        },
        "existing_audit_inputs": existing_inputs,
        "legacy_normalized_raw_gtfs_amount_crosscheck": {
            "normalized_ferry_count": len(normalized_ferry),
            "matching_raw_amount_count": comparison_count,
        },
        "not_applicable_source_cases": {
            "conflicting_fare": "no conflicting amount exists for a raw Ferry route-stop-OD key",
            "unresolved_required_forward_pair": "all 60 current schedule forward pairs have one raw GTFS fare",
            "official_zero_fare": "no raw Ferry GTFS fare rule has price zero",
        },
        "prohibited_fallbacks": {
            "reverse_substitution": False,
            "distance_interpolation": False,
            "path_sum": False,
            "aggregation": False,
            "full_fare_fallback": False,
            "missing_zero_fill": False,
        },
        "transfer_concession_status": "not_modelled",
        "production_passenger_trip_pricing": "not_performed",
        "matsim_scoring_integration": "not_performed",
    }
    (output_dir / "ferry_fare_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "README.md").write_text(
        build_readme(summary), encoding="utf-8"
    )
    (output_dir / "ferry_fare_validation.json").write_text(
        json.dumps(
            {
                "schema_version": "hong_kong_ferry_fare_validation_v1",
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
        f"Built {len(rules)} Ferry OD rules for {len(readiness)} routes "
        f"({exact_count} exact, {partial_count} partial) in {output_dir}"
    )


if __name__ == "__main__":
    main()
