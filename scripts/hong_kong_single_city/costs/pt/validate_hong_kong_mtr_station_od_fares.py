"""Independently validate Hong Kong MTR station-OD fare rules v1.

The validator rereads the original official MTR and TD CSV files.  It does not
import the MTR rule builder or trust builder-computed validation booleans.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd

from quote_hong_kong_mtr_station_od_fares import (
    OUTPUT_COLUMNS,
    quote_dataframe,
)


CANONICAL_SOURCE_ROOT = Path(r"F:\Matsim\matsim-example-project")
DOMESTIC_SCOPE = "domestic_mtr_station_od"
AIRPORT_SCOPE = "airport_express_station_od"
SOURCE_BY_SCOPE = {
    DOMESTIC_SCOPE: "mtr_domestic_fares",
    AIRPORT_SCOPE: "mtr_airport_express_fares",
}
NORMALIZED_SOURCE_BY_SCOPE = {
    DOMESTIC_SCOPE: "mtr_domestic_fares_20260720",
    AIRPORT_SCOPE: "mtr_airport_express_fares_20260720",
}
LOCAL_ABSOLUTE_PATH = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|\\\\[^\\])")


def repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Independently validate Hong Kong MTR domestic and Airport Express "
            "adult Octopus station-OD rules."
        )
    )
    parser.add_argument("--source-project-root", type=Path, default=None)
    parser.add_argument("--fare-model-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser.parse_args()


def choose_source_root(value: Path | None) -> Path:
    if value is not None:
        return value.resolve()
    local = repository_root()
    marker = local / "data/transit/hongkong/MTR/mtr_lines_fares.csv"
    return local if marker.exists() else CANONICAL_SOURCE_ROOT


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def require_columns(frame: pd.DataFrame, columns: list[str], label: str) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise AssertionError(f"{label} missing columns: {missing}")


def read_manifest(
    model_dir: Path, source_root: Path
) -> tuple[pd.DataFrame, dict[str, dict[str, str]]]:
    manifest = pd.read_csv(
        model_dir / "fare_source_manifest.csv",
        dtype=str,
        keep_default_na=False,
    )
    require_columns(
        manifest,
        [
            "source_id",
            "effective_date",
            "effective_date_status",
            "repository_relative_path",
            "size_bytes",
            "sha256",
        ],
        "fare_source_manifest",
    )
    rows: dict[str, dict[str, str]] = {}
    for record in manifest.to_dict("records"):
        source_id = str(record["source_id"])
        path = source_root / Path(record["repository_relative_path"])
        if not path.exists():
            raise AssertionError(f"Missing source: {record['repository_relative_path']}")
        if path.stat().st_size != int(record["size_bytes"]):
            raise AssertionError(f"Source size mismatch: {source_id}")
        if sha256(path) != record["sha256"]:
            raise AssertionError(f"Source SHA256 mismatch: {source_id}")
        rows[source_id] = {str(key): str(value) for key, value in record.items()}
    return manifest, rows


def read_raw_records(
    source_root: Path, source_rows: dict[str, dict[str, str]]
) -> tuple[
    dict[str, dict[tuple[str, str], list[dict[str, Any]]]],
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    mtr_dir = source_root / "data/transit/hongkong/MTR"
    domestic = pd.read_csv(
        mtr_dir / "mtr_lines_fares.csv", dtype=str, keep_default_na=False
    )
    airport = pd.read_csv(
        mtr_dir / "airport_express_fares.csv", dtype=str, keep_default_na=False
    )
    stations = pd.read_csv(
        mtr_dir / "mtr_lines_and_stations.csv",
        dtype=str,
        keep_default_na=False,
    )
    specifications = [
        (
            DOMESTIC_SCOPE,
            domestic,
            "SRC_STATION_ID",
            "DEST_STATION_ID",
            "OCT_ADT_FARE",
        ),
        (
            AIRPORT_SCOPE,
            airport,
            "ST_FROM_ID",
            "ST_TO_ID",
            "OCT_ADT_FARE",
        ),
    ]
    records: dict[str, dict[tuple[str, str], list[dict[str, Any]]]] = {}
    for scope, frame, origin_column, destination_column, fare_column in specifications:
        source_id = SOURCE_BY_SCOPE[scope]
        scope_records: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for offset, row in enumerate(frame.to_dict("records"), start=2):
            key = (str(row[origin_column]), str(row[destination_column]))
            fare_text = str(row[fare_column]).strip()
            item = {
                "source_record_id": f"{source_id}:csv_line_{offset:06d}",
                "fare_hkd": float(fare_text) if fare_text else None,
                "source_file": source_rows[source_id]["repository_relative_path"],
                "source_sha256": source_rows[source_id]["sha256"],
            }
            scope_records.setdefault(key, []).append(item)
        records[scope] = scope_records
    return records, domestic, airport, stations


def parse_td_revision_date(
    source_root: Path,
    manifest: pd.DataFrame,
    source_rows: dict[str, dict[str, str]],
) -> dict[str, Any]:
    evidence = source_rows.get("td_route_fare_revision_date")
    if evidence is None:
        raise AssertionError("TD revision-date source missing from manifest")
    path = source_root / Path(evidence["repository_relative_path"])
    table = pd.read_csv(path, dtype=str, keep_default_na=False)
    parsed = {
        pd.Timestamp(value).date().isoformat()
        for value in table.to_numpy().ravel()
        if str(value).strip()
    }
    if len(parsed) != 1:
        raise AssertionError(f"TD date file did not parse to one date: {parsed}")
    parsed_date = next(iter(parsed))
    td_ids = {
        "td_gtfs",
        "td_bus_route_fares",
        "td_gmb_route_fares",
        "td_ferry_route_fares",
        "td_route_fare_revision_date",
    }
    td = manifest[manifest["source_id"].isin(td_ids)]
    if set(td["source_id"]) != td_ids:
        raise AssertionError("Not all TD sources are present for date validation")
    if not td["effective_date"].eq(parsed_date).all():
        raise AssertionError("TD manifest date differs from parsed local file")
    if not td["effective_date_status"].eq("local_source_proven").all():
        raise AssertionError("TD date evidence status is not local_source_proven")
    return {
        "parsed_date": parsed_date,
        "manifest_rows_matched": int(len(td)),
        "parsed_from_local_file": True,
    }


def read_train_schedule(
    schedule_path: Path,
) -> dict[tuple[str, str], list[str]]:
    with gzip.open(schedule_path, "rb") as handle:
        root = ET.parse(handle).getroot()
    result: dict[tuple[str, str], list[str]] = {}
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
            if mode == "train":
                result[(line.attrib["id"], route.attrib["id"])] = refs
    if len(result) != 30:
        raise AssertionError(f"Expected 30 train routes, found {len(result)}")
    return result


def exact_code_tokens(facility_id: str, known_codes: set[str]) -> list[str]:
    return sorted(
        code
        for code in known_codes
        if re.search(rf"(?:^|_){re.escape(code)}(?:_|$)", facility_id)
    )


def independently_map_schedule_facilities(
    source_root: Path,
    stations: pd.DataFrame,
    inventory: pd.DataFrame,
) -> dict[str, set[str]]:
    stations = stations.rename(
        columns={
            "Line Code": "line_code",
            "Station Code": "station_code",
            "Station ID": "station_id",
        }
    )
    stations = stations[
        stations["line_code"].ne("")
        & stations["station_code"].ne("")
        & stations["station_id"].ne("")
    ]
    key_to_ids = (
        stations.groupby(["line_code", "station_code"])["station_id"]
        .agg(lambda values: set(values))
        .to_dict()
    )
    known_codes = set(stations["station_code"])
    schedule_path = (
        source_root
        / "data/transit/hongkong/processed/"
        "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_"
        "ferry_core_v1_cap010/transitSchedule_5pct.xml.gz"
    )
    schedule = read_train_schedule(schedule_path)
    train_inventory = inventory[inventory["transport_mode"].eq("train")]
    facility_to_ids: dict[str, set[str]] = {}
    for row in train_inventory.itertuples(index=False):
        key = (str(row.matsim_line_id), str(row.matsim_route_id))
        refs = schedule[key]
        expected = [str(value) for value in json.loads(row.official_stop_ids_json)]
        independently_mapped: list[str] = []
        for facility_id in refs:
            codes = exact_code_tokens(facility_id, known_codes)
            candidate_ids = (
                key_to_ids.get((str(row.official_route_id), codes[0]), set())
                if len(codes) == 1
                else set()
            )
            facility_to_ids.setdefault(facility_id, set()).update(candidate_ids)
            independently_mapped.append(
                next(iter(candidate_ids)) if len(candidate_ids) == 1 else ""
            )
        if independently_mapped != expected:
            raise AssertionError(
                f"Independent station mapping mismatch for {row.matsim_route_id}"
            )
    return facility_to_ids


def validate_station_crosswalk(
    crosswalk: pd.DataFrame,
    records: dict[str, dict[tuple[str, str], list[dict[str, Any]]]],
    stations: pd.DataFrame,
    facility_to_ids: dict[str, set[str]],
) -> dict[str, Any]:
    required = [
        "station_id",
        "station_code",
        "station_name_en",
        "line_codes",
        "in_domestic_fare_matrix",
        "in_airport_express_fare_matrix",
        "in_schedule",
        "schedule_facility_count",
        "schedule_facility_ids_json",
        "mapping_status",
        "mapping_quality",
        "matching_method",
        "source_id",
        "unresolved_reason",
    ]
    require_columns(crosswalk, required, "mtr_station_crosswalk")
    if crosswalk["station_id"].duplicated().any():
        raise AssertionError("Station crosswalk has duplicate station_id")

    raw_ids: set[str] = set()
    for scope_records in records.values():
        for boarding, alighting in scope_records:
            raw_ids.update([boarding, alighting])
    official_station_ids = set(
        stations.loc[stations["Station ID"].ne(""), "Station ID"]
    )
    expected_ids = raw_ids | official_station_ids
    if set(crosswalk["station_id"]) != expected_ids:
        raise AssertionError("Station crosswalk does not cover official ID union")

    claimed_facility_to_ids: dict[str, set[str]] = {}
    for row in crosswalk.itertuples(index=False):
        facilities = json.loads(row.schedule_facility_ids_json)
        if len(facilities) != int(row.schedule_facility_count):
            raise AssertionError(
                f"Facility count mismatch for station {row.station_id}"
            )
        for facility_id in facilities:
            claimed_facility_to_ids.setdefault(facility_id, set()).add(
                str(row.station_id)
            )
        if row.mapping_status == "exact":
            if not facilities or row.mapping_quality != "A":
                raise AssertionError("Exact station mapping lacks facilities/A quality")
        elif row.mapping_status in {"ambiguous", "unresolved"}:
            if not row.unresolved_reason:
                raise AssertionError("Non-exact station mapping lacks reason")
        else:
            raise AssertionError(f"Invalid station mapping status {row.mapping_status}")
    if any(len(ids) > 1 for ids in claimed_facility_to_ids.values()):
        raise AssertionError("Schedule facility assigned to multiple station IDs")

    independently_exact = {
        facility_id: next(iter(ids))
        for facility_id, ids in facility_to_ids.items()
        if len(ids) == 1
    }
    claimed_exact = {
        facility_id: next(iter(ids))
        for facility_id, ids in claimed_facility_to_ids.items()
        if len(ids) == 1
    }
    if claimed_exact != independently_exact:
        raise AssertionError("Station facility crosswalk differs from independent map")
    return {
        "rows": int(len(crosswalk)),
        "mapping_status": {
            str(key): int(value)
            for key, value in crosswalk["mapping_status"].value_counts().items()
        },
        "ambiguous_schedule_facilities": int(
            sum(len(ids) > 1 for ids in facility_to_ids.values())
        ),
    }


def raw_conflict_keys(
    records: dict[tuple[str, str], list[dict[str, Any]]]
) -> set[tuple[str, str]]:
    result = set()
    for key, candidates in records.items():
        fares = {
            item["fare_hkd"]
            for item in candidates
            if item["fare_hkd"] is not None
        }
        if len(fares) > 1:
            result.add(key)
    return result


def validate_rules(
    rules: pd.DataFrame,
    records: dict[str, dict[tuple[str, str], list[dict[str, Any]]]],
    source_rows: dict[str, dict[str, str]],
    normalized_path: Path,
) -> dict[str, Any]:
    required = [
        "fare_network_scope",
        "boarding_station_id",
        "alighting_station_id",
        "adult_octopus_fare_hkd",
        "currency",
        "cost_component",
        "cost_source",
        "cost_effective_date",
        "cost_effective_date_status",
        "source_record_id",
        "source_file",
        "source_sha256",
        "record_status",
        "candidate_records_json",
        "matching_method",
        "unresolved_reason",
    ]
    require_columns(rules, required, "mtr_station_od_fare_rules")
    if set(rules["fare_network_scope"]) != {DOMESTIC_SCOPE, AIRPORT_SCOPE}:
        raise AssertionError("Domestic and Airport Express scopes are not separate")
    key_columns = [
        "fare_network_scope",
        "boarding_station_id",
        "alighting_station_id",
    ]
    if rules.duplicated(key_columns).any():
        raise AssertionError("Duplicate scope + ordered station-OD rule key")

    source_record_lookup: dict[str, tuple[str, tuple[str, str], dict[str, Any]]] = {}
    for scope, scope_records in records.items():
        for key, candidates in scope_records.items():
            for candidate in candidates:
                source_record_lookup[candidate["source_record_id"]] = (
                    scope,
                    key,
                    candidate,
                )

    available = rules["record_status"].eq("available")
    non_available = ~available
    if rules.loc[non_available, "adult_octopus_fare_hkd"].notna().any():
        raise AssertionError("Non-available rule has a fare, including zero")
    if rules.loc[non_available, "source_record_id"].fillna("").ne("").any():
        raise AssertionError("Non-available rule selected a source record")
    if rules.loc[non_available, "unresolved_reason"].fillna("").eq("").any():
        raise AssertionError("Non-available rule lacks unresolved reason")

    for row in rules.loc[available].itertuples(index=False):
        trace = source_record_lookup.get(str(row.source_record_id))
        if trace is None:
            raise AssertionError(f"Unknown source_record_id: {row.source_record_id}")
        raw_scope, raw_key, candidate = trace
        output_key = (str(row.boarding_station_id), str(row.alighting_station_id))
        if raw_scope != row.fare_network_scope or raw_key != output_key:
            raise AssertionError("Available fare does not match exact ordered raw OD")
        if not np.isclose(
            float(row.adult_octopus_fare_hkd),
            float(candidate["fare_hkd"]),
            rtol=0,
            atol=1e-9,
        ):
            raise AssertionError("Available fare amount differs from raw CSV")
        source = source_rows[SOURCE_BY_SCOPE[raw_scope]]
        if row.source_file != source["repository_relative_path"]:
            raise AssertionError("Available fare source_file mismatch")
        if row.source_sha256 != source["sha256"]:
            raise AssertionError("Available fare source SHA256 mismatch")
        if row.cost_effective_date != source["effective_date"]:
            raise AssertionError("Available fare effective date mismatch")
        if row.cost_effective_date_status != source["effective_date_status"]:
            raise AssertionError("Available fare effective-date status mismatch")

    if not set(rules["matching_method"]).issubset(
        {
            "exact_ordered_station_id_raw_csv_record",
            "explicit_absence_from_hashed_official_csv",
        }
    ):
        raise AssertionError("Unexpected fare inference method")

    normalized = pd.read_parquet(normalized_path)
    scope_result: dict[str, dict[str, int]] = {}
    for scope in [DOMESTIC_SCOPE, AIRPORT_SCOPE]:
        group = rules[rules["fare_network_scope"].eq(scope)]
        raw_keys = set(records[scope])
        group_available = group[group["record_status"].eq("available")]
        output_available_keys = set(
            group_available[
                ["boarding_station_id", "alighting_station_id"]
            ].itertuples(index=False, name=None)
        )
        expected_available = {
            key
            for key, candidates in records[scope].items()
            if len(
                {
                    item["fare_hkd"]
                    for item in candidates
                    if item["fare_hkd"] is not None
                }
            )
            == 1
        }
        if output_available_keys != expected_available:
            raise AssertionError(f"Available ordered OD keys differ for {scope}")
        output_conflicts = set(
            group.loc[
                group["record_status"].eq("ambiguous"),
                ["boarding_station_id", "alighting_station_id"],
            ].itertuples(index=False, name=None)
        )
        if output_conflicts != raw_conflict_keys(records[scope]):
            raise AssertionError(f"Conflicting duplicates mishandled for {scope}")

        existing = normalized[
            normalized["source_id"].eq(NORMALIZED_SOURCE_BY_SCOPE[scope])
        ][["origin_stop_id", "destination_stop_id", "adult_octopus_fare_hkd"]]
        normalized_map = {
            (str(row.origin_stop_id), str(row.destination_stop_id)): float(
                row.adult_octopus_fare_hkd
            )
            for row in existing.itertuples(index=False)
        }
        for row in group_available.itertuples(index=False):
            key = (str(row.boarding_station_id), str(row.alighting_station_id))
            if key not in normalized_map or not np.isclose(
                float(row.adult_octopus_fare_hkd),
                normalized_map[key],
                rtol=0,
                atol=1e-9,
            ):
                raise AssertionError(f"Raw/normalized crosscheck failed for {scope}")
        scope_result[scope] = {
            "total_records": int(len(group)),
            "available_records": int(group["record_status"].eq("available").sum()),
            "conflicting_records": int(group["record_status"].eq("ambiguous").sum()),
            "missing_records": int(group["record_status"].eq("unresolved").sum()),
            "official_zero_fare_records": int(
                group["adult_octopus_fare_hkd"].eq(0).sum()
            ),
            "raw_official_ordered_od_records": int(len(raw_keys)),
            "available_costs_with_raw_source_record": int(
                group_available["source_record_id"].ne("").sum()
            ),
        }
    return {
        "fare_network_scopes": scope_result,
        "all_available_costs_trace_to_raw_ordered_od": True,
        "reverse_direction_substitution_present": False,
        "distance_interpolation_present": False,
        "path_summation_present": False,
        "cross_scope_fallback_present": False,
        "missing_fare_zero_fill_present": False,
    }


def ordered_pairs(stops: list[str]) -> set[tuple[str, str]]:
    return {
        (stops[index], stops[later])
        for index in range(len(stops))
        for later in range(index + 1, len(stops))
    }


def validate_unresolved_airport_pairs(
    unresolved: pd.DataFrame,
    inventory: pd.DataFrame,
    records: dict[str, dict[tuple[str, str], list[dict[str, Any]]]],
    rules: pd.DataFrame,
) -> list[dict[str, str]]:
    require_columns(
        unresolved,
        [
            "fare_network_scope",
            "boarding_station_id",
            "alighting_station_id",
            "matsim_route_id",
            "official_direction",
            "record_status",
            "unresolved_reason",
        ],
        "mtr_unresolved_od_pairs",
    )
    required: set[tuple[str, str]] = set()
    for row in inventory[
        inventory["transport_mode"].eq("train")
        & inventory["official_route_id"].eq("AEL")
    ].itertuples(index=False):
        required |= ordered_pairs(
            [str(value) for value in json.loads(row.official_stop_ids_json)]
        )
    raw_available = set(records[AIRPORT_SCOPE])
    expected_missing = required - raw_available
    written = set(
        unresolved[
            ["boarding_station_id", "alighting_station_id"]
        ].itertuples(index=False, name=None)
    )
    if written != expected_missing or len(written) != 6:
        raise AssertionError("Airport Express missing-pair set is not exact")
    rule_missing = set(
        rules.loc[
            rules["fare_network_scope"].eq(AIRPORT_SCOPE)
            & rules["record_status"].eq("unresolved"),
            ["boarding_station_id", "alighting_station_id"],
        ].itertuples(index=False, name=None)
    )
    if rule_missing != expected_missing:
        raise AssertionError("Unresolved AEL rules differ from unresolved-pair table")
    return [
        {"boarding_station_id": boarding, "alighting_station_id": alighting}
        for boarding, alighting in sorted(expected_missing)
    ]


def validate_route_readiness(
    readiness: pd.DataFrame,
    inventory: pd.DataFrame,
    route_crosswalk: pd.DataFrame,
    rules: pd.DataFrame,
) -> dict[str, Any]:
    required = [
        "matsim_line_id",
        "matsim_route_id",
        "official_line_id",
        "official_direction",
        "scheduled_stop_count",
        "mapped_station_count",
        "station_id_coverage",
        "direction_status",
        "required_forward_pair_count",
        "matched_forward_pair_count",
        "forward_pair_coverage",
        "fare_network_scope",
        "mapping_status",
        "mapping_quality",
        "fare_readiness",
        "unresolved_reason",
    ]
    require_columns(readiness, required, "mtr_schedule_route_fare_readiness")
    if len(readiness) != 30 or readiness["matsim_route_id"].duplicated().any():
        raise AssertionError("Train route readiness must contain 30 unique routes")

    available_by_scope = {
        scope: set(
            group.loc[
                group["record_status"].eq("available"),
                ["boarding_station_id", "alighting_station_id"],
            ].itertuples(index=False, name=None)
        )
        for scope, group in rules.groupby("fare_network_scope")
    }
    train_inventory = inventory[inventory["transport_mode"].eq("train")]
    train_crosswalk = route_crosswalk[
        route_crosswalk["transport_mode"].eq("train")
    ]
    expected_base = train_inventory.merge(
        train_crosswalk,
        on=["matsim_line_id", "matsim_route_id", "transport_mode"],
        validate="one_to_one",
        suffixes=("_inventory", ""),
    )
    expected_by_route = {
        str(row.matsim_route_id): row
        for row in expected_base.itertuples(index=False)
    }
    for row in readiness.itertuples(index=False):
        source = expected_by_route[str(row.matsim_route_id)]
        stops = [
            str(value) for value in json.loads(source.official_stop_ids_json)
        ]
        pairs = ordered_pairs(stops)
        matched = len(pairs & available_by_scope[str(row.fare_network_scope)])
        if int(row.required_forward_pair_count) != len(pairs):
            raise AssertionError("Route required pair count mismatch")
        if int(row.matched_forward_pair_count) != matched:
            raise AssertionError("Route matched pair count mismatch")
        if not np.isclose(
            float(row.forward_pair_coverage),
            matched / len(pairs) if pairs else 0.0,
        ):
            raise AssertionError("Route forward-pair coverage mismatch")
        if row.mapping_status != source.mapping_status:
            raise AssertionError("Route mapping status was not preserved")
        if row.mapping_quality != source.mapping_quality:
            raise AssertionError("Route mapping quality was not preserved")
    tkl_compositions = readiness[
        readiness["matsim_route_id"].isin(["mtr_TKL_LHP-DT", "mtr_TKL_LHP-UT"])
    ]
    if len(tkl_compositions) != 2 or not tkl_compositions[
        "mapping_status"
    ].eq("one_to_many_explicit").all():
        raise AssertionError("TKL branch compositions were collapsed")
    return {
        "mapping_status": {
            str(key): int(value)
            for key, value in readiness["mapping_status"].value_counts().items()
        },
        "mapping_quality": {
            str(key): int(value)
            for key, value in readiness["mapping_quality"].value_counts().items()
        },
        "fare_readiness": {
            str(key): int(value)
            for key, value in readiness["fare_readiness"].value_counts().items()
        },
    }


def normalize_for_csv_compare(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column in result.columns:
        if column in {"cost_hkd", "transfer_concession_hkd"}:
            result[column] = pd.to_numeric(
                result[column], errors="coerce"
            ).astype(float)
        else:
            result[column] = result[column].fillna("").astype(str)
    return result


def validate_fixture(
    fixture_input: pd.DataFrame,
    fixture_output: pd.DataFrame,
    rules: pd.DataFrame,
) -> dict[str, Any]:
    require_columns(fixture_output, OUTPUT_COLUMNS, "fixture output")
    actual = quote_dataframe(fixture_input, rules)
    expected = normalize_for_csv_compare(fixture_output[OUTPUT_COLUMNS])
    actual = normalize_for_csv_compare(actual[OUTPUT_COLUMNS])
    pd.testing.assert_frame_equal(
        actual,
        expected,
        check_dtype=False,
        check_exact=False,
        rtol=0,
        atol=1e-9,
    )
    if fixture_output["transfer_concession_hkd"].notna().any():
        raise AssertionError("Fixture contains a transfer concession amount")
    if not fixture_output["transfer_concession_status"].eq("not_modelled").all():
        raise AssertionError("Fixture transfer concessions are not explicit")
    required_ids = {
        "domestic_available",
        "airport_express_available",
        "domestic_reverse_ordered",
        "unknown_boarding",
        "unknown_alighting",
        "missing_scope",
        "domestic_ids_in_airport_scope",
        "airport_express_known_missing_pair",
        "unsupported_child",
        "unsupported_payment",
        "generic_pt_mode",
        "missing_actual_mode",
        "airport_same_station_without_record",
        "missing_boarding",
        "missing_alighting",
        "transfer_concession_requested",
    }
    if set(fixture_input["quote_id"]) != required_ids:
        raise AssertionError("Fixture case coverage is incomplete")
    by_id = actual.set_index("quote_id")
    priced_ids = {
        "domestic_available",
        "airport_express_available",
        "domestic_reverse_ordered",
        "transfer_concession_requested",
    }
    if not by_id.loc[sorted(priced_ids), "cost_hkd"].notna().all():
        raise AssertionError("Fixture available cases were not priced")
    if not by_id.loc[sorted(priced_ids), "mapping_status"].eq("exact").all():
        raise AssertionError("Fixture available cases are not exact")
    if not by_id.loc[sorted(priced_ids), "cost_quality"].eq("B").all():
        raise AssertionError("MTR fixture quote exceeded evidence quality B")
    unresolved_ids = required_ids - priced_ids
    if by_id.loc[sorted(unresolved_ids), "cost_hkd"].notna().any():
        raise AssertionError("Fixture unresolved case received a fare")
    if not by_id.loc[sorted(unresolved_ids), "cost_quality"].eq("U").all():
        raise AssertionError("Fixture unresolved case is not quality U")
    if (
        by_id.loc["domestic_available", "source_record_id"]
        == by_id.loc["domestic_reverse_ordered", "source_record_id"]
    ):
        raise AssertionError("Reverse ordered OD reused the forward source record")
    if (
        by_id.loc[
            "airport_express_known_missing_pair", "unresolved_reason"
        ]
        != "official_airport_express_ordered_od_record_missing"
    ):
        raise AssertionError("Known Airport Express gap was not preserved")
    if (
        by_id.loc["domestic_ids_in_airport_scope", "mapping_status"]
        != "unresolved"
    ):
        raise AssertionError("Cross-scope fixture request was not unresolved")
    return {
        "cases": int(len(actual)),
        "passed": int(len(actual)),
        "priced": int(actual["cost_hkd"].notna().sum()),
        "unresolved": int(actual["cost_hkd"].isna().sum()),
    }


def validate_mtr_dates(
    rules: pd.DataFrame, source_rows: dict[str, dict[str, str]]
) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for scope, source_id in SOURCE_BY_SCOPE.items():
        source = source_rows[source_id]
        if (
            source["effective_date_status"]
            != "external_official_reference_not_locally_archived"
        ):
            raise AssertionError(f"MTR date evidence was improperly upgraded: {scope}")
        available = rules[
            rules["fare_network_scope"].eq(scope)
            & rules["record_status"].eq("available")
        ]
        if not available["cost_effective_date"].eq(source["effective_date"]).all():
            raise AssertionError(f"Rule effective date mismatch: {scope}")
        if not available["cost_effective_date_status"].eq(
            source["effective_date_status"]
        ).all():
            raise AssertionError(f"Rule effective-date status mismatch: {scope}")
        result[scope] = {
            "effective_date": source["effective_date"],
            "effective_date_status": source["effective_date_status"],
        }
    return result


def validate_production_trip_audit(model_dir: Path) -> dict[str, Any]:
    trips = pd.read_parquet(model_dir / "pt_passenger_trip_fare_audit.parquet")
    if len(trips) != 557_104:
        raise AssertionError("Production PT audit row count changed")
    if trips["cost_hkd"].notna().any():
        raise AssertionError("Production generic PT trips gained a fare")
    if not trips["mapping_status"].eq("unresolved").all():
        raise AssertionError("Production generic PT trips are not all unresolved")
    return {
        "rows": int(len(trips)),
        "priced_rows": 0,
        "unresolved_rows": int(len(trips)),
    }


def validate_protected_inputs(
    model_dir: Path, source_root: Path
) -> dict[str, Any]:
    baseline = pd.read_csv(model_dir / "protected_input_hashes_baseline.csv")
    require_columns(
        baseline,
        ["repository_relative_path", "size_bytes", "sha256_before"],
        "protected input baseline",
    )
    checked = 0
    for row in baseline.itertuples(index=False):
        path = source_root / Path(row.repository_relative_path)
        if (
            path.stat().st_size != int(row.size_bytes)
            or sha256(path) != row.sha256_before
        ):
            raise AssertionError(f"Protected input changed: {row.repository_relative_path}")
        checked += 1
    return {"files_checked": checked, "all_unchanged": True}


def validate_summary(
    summary: dict[str, Any],
    station_result: dict[str, Any],
    rules_result: dict[str, Any],
    readiness_result: dict[str, Any],
    fixture_result: dict[str, Any],
) -> None:
    if summary["station_crosswalk"] != station_result["mapping_status"]:
        raise AssertionError("Station summary differs from crosswalk")
    for scope, summary_values in summary["fare_network_scopes"].items():
        validated_values = rules_result["fare_network_scopes"][scope]
        for key, value in summary_values.items():
            if int(validated_values[key]) != int(value):
                raise AssertionError(
                    f"Fare scope summary differs from rules: {scope} {key}"
                )
    if (
        summary["train_route_mapping_status"]
        != readiness_result["mapping_status"]
    ):
        raise AssertionError("Route mapping summary differs from readiness table")
    if (
        summary["train_route_fare_readiness"]
        != readiness_result["fare_readiness"]
    ):
        raise AssertionError("Route readiness summary differs from detail")
    if int(summary["fixture_quotes"]["total"]) != fixture_result["cases"]:
        raise AssertionError("Fixture total differs from summary")


def validate_portability(output_dir: Path) -> list[str]:
    checked = []
    for path in sorted(output_dir.iterdir()):
        if path.suffix.lower() not in {".csv", ".json", ".md", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8")
        if LOCAL_ABSOLUTE_PATH.search(text):
            raise AssertionError(f"Absolute local path found in {path.name}")
        checked.append(path.name)
    return checked


def write_sha256s(output_dir: Path) -> None:
    files = sorted(
        path
        for path in output_dir.iterdir()
        if path.is_file() and path.name != "SHA256SUMS.txt"
    )
    (output_dir / "SHA256SUMS.txt").write_text(
        "\n".join(f"{sha256(path)}  {path.name}" for path in files) + "\n",
        encoding="utf-8",
    )


def verify_sha256s(output_dir: Path) -> int:
    lines = (output_dir / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    entries = {
        line.split("  ", 1)[1]: line.split("  ", 1)[0]
        for line in lines
        if line.strip()
    }
    expected_files = {
        path.name
        for path in output_dir.iterdir()
        if path.is_file() and path.name != "SHA256SUMS.txt"
    }
    if set(entries) != expected_files:
        raise AssertionError("SHA256SUMS file list mismatch")
    for filename, digest in entries.items():
        if sha256(output_dir / filename) != digest:
            raise AssertionError(f"Output SHA256 mismatch: {filename}")
    return len(entries)


def main() -> None:
    args = parse_args()
    source_root = choose_source_root(args.source_project_root)
    model_dir = (
        args.fare_model_dir.resolve()
        if args.fare_model_dir
        else repository_root() / "data/transport_costs/hongkong/pt_fare_v1"
    )
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else model_dir / "mtr_station_od_v1"
    )

    manifest, source_rows = read_manifest(model_dir, source_root)
    records, _, _, stations = read_raw_records(source_root, source_rows)
    td_date_result = parse_td_revision_date(source_root, manifest, source_rows)
    inventory = pd.read_csv(
        model_dir / "transit_schedule_inventory.csv",
        dtype=str,
        keep_default_na=False,
    )
    route_crosswalk = pd.read_csv(
        model_dir / "route_to_official_fare_match.csv",
        dtype=str,
        keep_default_na=False,
    )
    station_crosswalk = pd.read_csv(
        output_dir / "mtr_station_crosswalk.csv",
        dtype=str,
        keep_default_na=False,
    )
    station_crosswalk["schedule_facility_count"] = pd.to_numeric(
        station_crosswalk["schedule_facility_count"], errors="raise"
    )
    rules = pd.read_parquet(output_dir / "mtr_station_od_fare_rules.parquet")
    unresolved = pd.read_csv(
        output_dir / "mtr_unresolved_od_pairs.csv",
        dtype=str,
        keep_default_na=False,
    )
    readiness = pd.read_csv(
        output_dir / "mtr_schedule_route_fare_readiness.csv",
        dtype=str,
        keep_default_na=False,
    )
    fixture_input = pd.read_csv(
        output_dir / "mtr_fare_query_fixture_input.csv",
        dtype=str,
        keep_default_na=False,
    )
    fixture_output = pd.read_csv(
        output_dir / "mtr_fare_query_fixture_output.csv",
        dtype=str,
        keep_default_na=False,
    )
    fixture_output["cost_hkd"] = pd.to_numeric(
        fixture_output["cost_hkd"], errors="coerce"
    )
    fixture_output["transfer_concession_hkd"] = pd.to_numeric(
        fixture_output["transfer_concession_hkd"], errors="coerce"
    )
    summary = json.loads(
        (output_dir / "mtr_station_od_summary.json").read_text(encoding="utf-8")
    )

    facility_map = independently_map_schedule_facilities(
        source_root, stations, inventory
    )
    station_result = validate_station_crosswalk(
        station_crosswalk, records, stations, facility_map
    )
    rules_result = validate_rules(
        rules,
        records,
        source_rows,
        model_dir / "official_fares_normalized.parquet",
    )
    missing_pairs = validate_unresolved_airport_pairs(
        unresolved, inventory, records, rules
    )
    readiness_result = validate_route_readiness(
        readiness, inventory, route_crosswalk, rules
    )
    fixture_result = validate_fixture(fixture_input, fixture_output, rules)
    mtr_date_result = validate_mtr_dates(rules, source_rows)
    production_result = validate_production_trip_audit(model_dir)
    protected_result = validate_protected_inputs(model_dir, source_root)
    validate_summary(
        summary,
        station_result,
        rules_result,
        readiness_result,
        fixture_result,
    )
    portability_files = validate_portability(output_dir)

    validation = {
        "validator": "independent Hong Kong MTR station-OD fare validator v1",
        "station_crosswalk": station_result,
        "fare_rules": rules_result,
        "airport_express_missing_ordered_od_pairs": missing_pairs,
        "train_route_readiness": readiness_result,
        "fixture": fixture_result,
        "mtr_effective_date_evidence": mtr_date_result,
        "td_revision_date_validation": td_date_result,
        "transfer_concessions": {
            "amounts_present": 0,
            "status": "not_modelled",
        },
        "production_pt_audit": production_result,
        "protected_inputs": protected_result,
        "portability": {
            "text_files_checked": portability_files,
            "absolute_local_paths_found": 0,
        },
        "validation_passed": True,
    }
    (output_dir / "mtr_station_od_validation.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for path in output_dir.glob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))
    write_sha256s(output_dir)
    validation["output_sha256_entries_verified"] = verify_sha256s(output_dir)
    print(json.dumps(validation, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
