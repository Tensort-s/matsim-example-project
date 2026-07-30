"""Independently validate Hong Kong Light Rail station-OD fare rules v1.

The validator rereads the original fare and route-pattern CSVs, production
transitSchedule, top-level route crosswalk, source manifest, and every new
Light Rail artifact. It does not import the Light Rail rule builder.
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

from quote_hong_kong_light_rail_station_od_fares import (
    FARE_AMOUNT_ROLE,
    OUTPUT_COLUMNS,
    quote_dataframe,
)


CANONICAL_SOURCE_ROOT = Path(r"F:\Matsim\matsim-example-project")
FARE_SCOPE = "light_rail_station_od"
FARE_SOURCE_ID = "mtr_light_rail_fares"
PATTERN_SOURCE_ID = "mtr_light_rail_stop_patterns"
LOCAL_ABSOLUTE_PATH = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|\\\\[^\\])")


def repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Independently validate Hong Kong Light Rail adult Octopus "
            "ordered stop-OD fare rules v1."
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
    marker = local / "data/transit/hongkong/MTR/light_rail_fares.csv"
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
) -> tuple[pd.DataFrame, dict[str, str], dict[str, str]]:
    manifest = pd.read_csv(
        model_dir / "fare_source_manifest.csv",
        dtype=str,
        keep_default_na=False,
    )
    result: dict[str, dict[str, str]] = {}
    for source_id in [FARE_SOURCE_ID, PATTERN_SOURCE_ID]:
        rows = manifest[manifest["source_id"].eq(source_id)]
        if len(rows) != 1:
            raise AssertionError(f"Expected one manifest row for {source_id}")
        row = {str(key): str(value) for key, value in rows.iloc[0].items()}
        path = source_root / Path(row["repository_relative_path"])
        if (
            not path.exists()
            or path.stat().st_size != int(row["size_bytes"])
            or sha256(path) != row["sha256"]
        ):
            raise AssertionError(f"Source integrity failure: {source_id}")
        result[source_id] = row
    fare_source = result[FARE_SOURCE_ID]
    if fare_source["effective_date"] != "2024-06-30":
        raise AssertionError("Unexpected Light Rail effective date")
    if (
        fare_source["effective_date_status"]
        != "external_official_reference_not_locally_archived"
    ):
        raise AssertionError("Light Rail date evidence was improperly upgraded")
    return manifest, fare_source, result[PATTERN_SOURCE_ID]


def read_raw_sources(
    source_root: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, dict[str, Any]]]:
    mtr_dir = source_root / "data/transit/hongkong/MTR"
    fares = pd.read_csv(
        mtr_dir / "light_rail_fares.csv",
        dtype=str,
        keep_default_na=False,
    )
    patterns = pd.read_csv(
        mtr_dir / "light_rail_routes_and_stops.csv",
        dtype=str,
        keep_default_na=False,
    )
    records: dict[str, dict[str, Any]] = {}
    for csv_line, row in enumerate(fares.to_dict("records"), start=2):
        source_record_id = f"{FARE_SOURCE_ID}:csv_line_{csv_line:06d}"
        records[source_record_id] = {
            "key": (str(row["from_station_id"]), str(row["to_station_id"])),
            "fare_hkd": (
                float(row["fare_octo_adult"])
                if str(row["fare_octo_adult"]).strip()
                else None
            ),
            "csv_line": csv_line,
        }
    return fares, patterns, records


def read_schedule(
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
            if mode == "light_rail":
                result[(line.attrib["id"], route.attrib["id"])] = refs
    if len(result) != 20:
        raise AssertionError(f"Expected 20 Light Rail routes, found {len(result)}")
    return result


def exact_code_tokens(facility_id: str, known_codes: set[str]) -> list[str]:
    return sorted(
        code
        for code in known_codes
        if re.search(rf"(?:^|_){re.escape(code)}(?:_|$)", facility_id)
    )


def independently_map_facilities(
    source_root: Path,
    patterns: pd.DataFrame,
    inventory: pd.DataFrame,
) -> tuple[dict[str, set[str]], dict[tuple[str, str], list[str]]]:
    pattern = patterns.rename(
        columns={
            "Line Code": "line_code",
            "Stop Code": "stop_code",
            "Stop ID": "stop_id",
        }
    )
    ids_by_line_code = (
        pattern.groupby(["line_code", "stop_code"])["stop_id"]
        .agg(lambda values: set(values))
        .to_dict()
    )
    known_codes = set(pattern["stop_code"])
    schedule_path = (
        source_root
        / "data/transit/hongkong/processed/"
        "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_"
        "ferry_core_v1_cap010/transitSchedule_5pct.xml.gz"
    )
    schedule = read_schedule(schedule_path)
    facility_to_ids: dict[str, set[str]] = {}
    route_stop_ids: dict[tuple[str, str], list[str]] = {}
    for row in inventory[
        inventory["transport_mode"].eq("light_rail")
    ].itertuples(index=False):
        key = (str(row.matsim_line_id), str(row.matsim_route_id))
        mapped = []
        for facility_id in schedule[key]:
            codes = exact_code_tokens(facility_id, known_codes)
            ids = (
                ids_by_line_code.get(
                    (str(row.official_route_id), codes[0]), set()
                )
                if len(codes) == 1
                else set()
            )
            facility_to_ids.setdefault(facility_id, set()).update(ids)
            mapped.append(next(iter(ids)) if len(ids) == 1 else "")
        expected = [str(value) for value in json.loads(row.official_stop_ids_json)]
        if mapped != expected:
            raise AssertionError(
                f"Independent schedule stop mapping mismatch: {row.matsim_route_id}"
            )
        route_stop_ids[key] = mapped
    return facility_to_ids, route_stop_ids


def validate_stop_crosswalk(
    crosswalk: pd.DataFrame,
    fares: pd.DataFrame,
    patterns: pd.DataFrame,
    facility_to_ids: dict[str, set[str]],
) -> dict[str, Any]:
    required = [
        "stop_id",
        "stop_code",
        "stop_name_en",
        "official_route_codes",
        "in_fare_matrix",
        "in_official_route_pattern",
        "in_schedule",
        "schedule_facility_count",
        "schedule_facility_ids_json",
        "candidate_count",
        "candidate_cardinality",
        "mapping_status",
        "mapping_quality",
        "matching_method",
        "source_id",
        "unresolved_reason",
    ]
    require_columns(crosswalk, required, "light_rail_stop_crosswalk")
    if crosswalk["stop_id"].duplicated().any():
        raise AssertionError("Duplicate stop_id in crosswalk")
    fare_ids = set(fares["from_station_id"]) | set(fares["to_station_id"])
    pattern_ids = set(patterns["Stop ID"])
    if set(crosswalk["stop_id"]) != fare_ids | pattern_ids:
        raise AssertionError("Stop crosswalk does not cover official stop union")

    claimed: dict[str, set[str]] = {}
    for row in crosswalk.itertuples(index=False):
        facilities = json.loads(row.schedule_facility_ids_json)
        if len(facilities) != int(row.schedule_facility_count):
            raise AssertionError(f"Facility count mismatch for stop {row.stop_id}")
        for facility_id in facilities:
            claimed.setdefault(facility_id, set()).add(str(row.stop_id))
        count = int(row.candidate_count)
        expected_cardinality = (
            "none" if count == 0 else "one" if count == 1 else "multiple"
        )
        if row.candidate_cardinality != expected_cardinality:
            raise AssertionError("Candidate count/cardinality mismatch")
        if row.mapping_status == "exact":
            if count != 1 or not facilities or row.mapping_quality != "A":
                raise AssertionError("Exact stop mapping lacks unique evidence")
        elif row.mapping_status == "ambiguous":
            if count <= 1 or not row.unresolved_reason:
                raise AssertionError("Ambiguous stop mapping inconsistency")
        elif row.mapping_status == "unresolved":
            if count != 0 or not row.unresolved_reason:
                raise AssertionError("Unresolved stop mapping inconsistency")
        else:
            raise AssertionError(f"Invalid stop mapping status {row.mapping_status}")
    if any(len(ids) > 1 for ids in claimed.values()):
        raise AssertionError("One facility assigned to multiple official stop IDs")
    independent_exact = {
        facility: next(iter(ids))
        for facility, ids in facility_to_ids.items()
        if len(ids) == 1
    }
    claimed_exact = {
        facility: next(iter(ids)) for facility, ids in claimed.items()
    }
    if claimed_exact != independent_exact:
        raise AssertionError("Stop crosswalk differs from independent exact mapping")
    return {
        "official_stops": int(len(fare_ids | pattern_ids)),
        "rows": int(len(crosswalk)),
        "mapping_status": {
            str(key): int(value)
            for key, value in crosswalk["mapping_status"].value_counts().items()
        },
        "ambiguous_schedule_facilities": int(
            sum(len(ids) > 1 for ids in facility_to_ids.values())
        ),
    }


def raw_key_groups(
    fares: pd.DataFrame,
) -> dict[tuple[str, str], list[tuple[str, float | None]]]:
    groups: dict[tuple[str, str], list[tuple[str, float | None]]] = {}
    for csv_line, row in enumerate(fares.to_dict("records"), start=2):
        key = (str(row["from_station_id"]), str(row["to_station_id"]))
        text = str(row["fare_octo_adult"]).strip()
        groups.setdefault(key, []).append(
            (
                f"{FARE_SOURCE_ID}:csv_line_{csv_line:06d}",
                float(text) if text else None,
            )
        )
    return groups


def validate_rules(
    rules: pd.DataFrame,
    conflicts: pd.DataFrame,
    unresolved: pd.DataFrame,
    fares: pd.DataFrame,
    raw_records: dict[str, dict[str, Any]],
    fare_source: dict[str, str],
    normalized_path: Path,
) -> dict[str, Any]:
    required = [
        "fare_network_scope",
        "boarding_stop_id",
        "alighting_stop_id",
        "boarding_stop_name_en",
        "alighting_stop_name_en",
        "adult_octopus_fare_hkd",
        "currency",
        "cost_component",
        "fare_amount_role",
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
    for frame, label in [
        (rules, "Light Rail fare rules"),
        (conflicts, "Light Rail fare conflicts"),
        (unresolved, "Light Rail unresolved OD pairs"),
    ]:
        require_columns(frame, required, label)
    if not rules["fare_network_scope"].eq(FARE_SCOPE).all():
        raise AssertionError("Light Rail rule contains another fare scope")
    if rules.duplicated(
        ["fare_network_scope", "boarding_stop_id", "alighting_stop_id"]
    ).any():
        raise AssertionError("Duplicate Light Rail rule key")

    raw_groups = raw_key_groups(fares)
    expected_conflicts = {
        key
        for key, candidates in raw_groups.items()
        if len({amount for _, amount in candidates if amount is not None}) > 1
    }
    expected_unresolved = {
        key
        for key, candidates in raw_groups.items()
        if not {amount for _, amount in candidates if amount is not None}
    }
    output_conflicts = set(
        conflicts[["boarding_stop_id", "alighting_stop_id"]].itertuples(
            index=False, name=None
        )
    )
    output_unresolved = set(
        unresolved[["boarding_stop_id", "alighting_stop_id"]].itertuples(
            index=False, name=None
        )
    )
    if output_conflicts != expected_conflicts:
        raise AssertionError("Conflict table differs from raw conflicting keys")
    if output_unresolved != expected_unresolved:
        raise AssertionError("Unresolved table differs from raw missing amounts")

    non_available = ~rules["record_status"].eq("available")
    if rules.loc[non_available, "adult_octopus_fare_hkd"].notna().any():
        raise AssertionError("Non-available rule contains an amount, including zero")
    if rules.loc[non_available, "source_record_id"].fillna("").ne("").any():
        raise AssertionError("Non-available rule selected a source record")
    if rules.loc[non_available, "unresolved_reason"].fillna("").eq("").any():
        raise AssertionError("Non-available rule lacks unresolved reason")

    available = rules[rules["record_status"].eq("available")]
    for row in available.itertuples(index=False):
        raw = raw_records.get(str(row.source_record_id))
        if raw is None:
            raise AssertionError(f"Unknown source record: {row.source_record_id}")
        key = (str(row.boarding_stop_id), str(row.alighting_stop_id))
        if raw["key"] != key:
            raise AssertionError("Available rule used reverse or another OD record")
        if not np.isclose(
            float(row.adult_octopus_fare_hkd),
            float(raw["fare_hkd"]),
            rtol=0,
            atol=1e-9,
        ):
            raise AssertionError("Rule amount differs from original CSV line")
        if (
            row.source_file != fare_source["repository_relative_path"]
            or row.source_sha256 != fare_source["sha256"]
        ):
            raise AssertionError("Rule source path/SHA256 mismatch")
        if (
            row.cost_effective_date != fare_source["effective_date"]
            or row.cost_effective_date_status
            != fare_source["effective_date_status"]
        ):
            raise AssertionError("Rule effective date/status mismatch")
        if row.fare_amount_role != FARE_AMOUNT_ROLE:
            raise AssertionError("Fare amount role is not explicit base fare")
    if not rules["matching_method"].eq(
        "exact_ordered_stop_id_raw_csv_record"
    ).all():
        raise AssertionError("Unexpected Light Rail fare inference method")

    raw_zero_ids = {
        source_record_id
        for source_record_id, record in raw_records.items()
        if record["fare_hkd"] == 0
    }
    output_zero_ids = set(
        available.loc[
            available["adult_octopus_fare_hkd"].eq(0), "source_record_id"
        ]
    )
    if output_zero_ids != raw_zero_ids:
        raise AssertionError("Official zero fares were lost or fabricated")

    normalized = pd.read_parquet(normalized_path)
    normalized = normalized[
        normalized["source_id"].eq("mtr_light_rail_fares_20260720")
    ]
    normalized_map = {
        (str(row.origin_stop_id), str(row.destination_stop_id)): float(
            row.adult_octopus_fare_hkd
        )
        for row in normalized.itertuples(index=False)
    }
    for row in available.itertuples(index=False):
        key = (str(row.boarding_stop_id), str(row.alighting_stop_id))
        if key not in normalized_map or not np.isclose(
            float(row.adult_octopus_fare_hkd),
            normalized_map[key],
            rtol=0,
            atol=1e-9,
        ):
            raise AssertionError("Raw-to-normalized Light Rail crosscheck failed")
    return {
        "raw_ordered_od_records": int(len(fares)),
        "raw_unique_ordered_od_keys": int(len(raw_groups)),
        "available_records": int(len(available)),
        "ambiguous_records": int(len(output_conflicts)),
        "unresolved_records": int(len(output_unresolved)),
        "official_zero_fare_records": int(len(raw_zero_ids)),
        "available_costs_with_unique_raw_source_record": int(
            available["source_record_id"].nunique()
        ),
        "available_cost_trace_rate": (
            float(available["source_record_id"].nunique()) / float(len(available))
            if len(available)
            else 0.0
        ),
        "reverse_direction_substitution_present": False,
        "distance_interpolation_present": False,
        "path_summation_present": False,
        "cross_scope_fallback_present": False,
        "missing_fare_zero_fill_present": False,
    }


def ordered_forward_pairs(stops: list[str]) -> set[tuple[str, str]]:
    return {
        (stops[index], stops[later])
        for index in range(len(stops))
        for later in range(index + 1, len(stops))
        if stops[index] and stops[later] and stops[index] != stops[later]
    }


def is_contiguous_subsequence(sequence: list[str], reference: list[str]) -> bool:
    return any(
        reference[start : start + len(sequence)] == sequence
        for start in range(max(0, len(reference) - len(sequence) + 1))
    )


def validate_route_readiness(
    readiness: pd.DataFrame,
    inventory: pd.DataFrame,
    top_crosswalk: pd.DataFrame,
    patterns: pd.DataFrame,
    route_stop_ids: dict[tuple[str, str], list[str]],
    fares: pd.DataFrame,
) -> dict[str, Any]:
    required = [
        "matsim_line_id",
        "matsim_route_id",
        "official_line_id",
        "official_direction",
        "scheduled_stop_count",
        "mapped_stop_count",
        "stop_id_coverage",
        "direction_status",
        "candidate_count",
        "required_forward_pair_count",
        "matched_forward_pair_count",
        "forward_pair_coverage",
        "fare_network_scope",
        "mapping_status",
        "mapping_quality",
        "fare_readiness",
        "route_pattern_type",
        "matching_method",
        "evidence",
        "unresolved_reason",
    ]
    require_columns(
        readiness, required, "light_rail_schedule_route_fare_readiness"
    )
    if len(readiness) != 20 or readiness["matsim_route_id"].duplicated().any():
        raise AssertionError("Readiness must cover 20 unique Light Rail routes")
    pattern = patterns.rename(
        columns={
            "Line Code": "line_code",
            "Direction": "direction",
            "Stop ID": "stop_id",
            "Sequence": "sequence",
        }
    )
    pattern_map = {
        (str(line), str(direction)): group.sort_values(
            "sequence", key=lambda values: pd.to_numeric(values)
        )["stop_id"].astype(str).tolist()
        for (line, direction), group in pattern.groupby(
            ["line_code", "direction"]
        )
    }
    raw_available = {
        (str(row.from_station_id), str(row.to_station_id))
        for row in fares.itertuples(index=False)
        if str(row.fare_octo_adult).strip()
    }
    source = inventory[
        inventory["transport_mode"].eq("light_rail")
    ].merge(
        top_crosswalk[top_crosswalk["transport_mode"].eq("light_rail")],
        on=["matsim_line_id", "matsim_route_id", "transport_mode"],
        validate="one_to_one",
        suffixes=("_inventory", ""),
    )
    source_by_route = {
        str(row.matsim_route_id): row for row in source.itertuples(index=False)
    }
    for row in readiness.itertuples(index=False):
        original = source_by_route[str(row.matsim_route_id)]
        key = (str(row.matsim_line_id), str(row.matsim_route_id))
        stops = route_stop_ids[key]
        pairs = ordered_forward_pairs(stops)
        matched = len(pairs & raw_available)
        if int(row.required_forward_pair_count) != len(pairs):
            raise AssertionError("Required forward-pair count mismatch")
        if int(row.matched_forward_pair_count) != matched:
            raise AssertionError("Matched forward-pair count mismatch")
        if not np.isclose(float(row.forward_pair_coverage), matched / len(pairs)):
            raise AssertionError("Forward-pair coverage mismatch")
        if (
            row.mapping_status != original.mapping_status
            or row.mapping_quality != original.mapping_quality
            or row.direction_status != original.direction_status
        ):
            raise AssertionError("Top-level route mapping state was not preserved")
        if row.route_pattern_type == "loop_multi_direction_composite":
            if (
                row.mapping_status != "one_to_many_explicit"
                or int(row.candidate_count) != 2
                or stops[0] != stops[-1]
            ):
                raise AssertionError("Loop route was collapsed or not closed")
        elif row.route_pattern_type == "short_turn":
            reference = pattern_map.get(
                (str(row.official_line_id), str(row.official_direction))
            )
            if (
                row.mapping_status != "partial"
                or reference is None
                or not is_contiguous_subsequence(stops, reference)
            ):
                raise AssertionError("Short turn classification is invalid")
        elif row.route_pattern_type == "exact_direction":
            reference = pattern_map.get(
                (str(row.official_line_id), str(row.official_direction))
            )
            if row.mapping_status != "exact" or reference != stops:
                raise AssertionError("Exact direction classification is invalid")
        else:
            raise AssertionError("Unknown Light Rail route pattern type")
        if row.fare_readiness != "ready":
            raise AssertionError("Complete official OD matrix should make route ready")
    return {
        "routes": int(len(readiness)),
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
        "route_pattern_type": {
            str(key): int(value)
            for key, value in readiness["route_pattern_type"].value_counts().items()
        },
        "forward_pairs_required": int(
            pd.to_numeric(readiness["required_forward_pair_count"]).sum()
        ),
        "forward_pairs_matched": int(
            pd.to_numeric(readiness["matched_forward_pair_count"]).sum()
        ),
        "forward_pair_coverage": (
            float(pd.to_numeric(readiness["matched_forward_pair_count"]).sum())
            / float(pd.to_numeric(readiness["required_forward_pair_count"]).sum())
        ),
    }


def normalize_fixture(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    for column in output:
        if column in {"cost_hkd", "transfer_concession_hkd"}:
            output[column] = pd.to_numeric(output[column], errors="coerce").astype(
                float
            )
        else:
            output[column] = output[column].fillna("").astype(str)
    return output


def validate_fixture(
    fixture_input: pd.DataFrame,
    fixture_output: pd.DataFrame,
    rules: pd.DataFrame,
) -> dict[str, Any]:
    require_columns(fixture_output, OUTPUT_COLUMNS, "Light Rail fixture output")
    actual = normalize_fixture(quote_dataframe(fixture_input, rules)[OUTPUT_COLUMNS])
    expected = normalize_fixture(fixture_output[OUTPUT_COLUMNS])
    pd.testing.assert_frame_equal(
        actual,
        expected,
        check_dtype=False,
        check_exact=False,
        rtol=0,
        atol=1e-9,
    )
    by_id = actual.set_index("quote_id")
    required_ids = {
        "available_ordered_od",
        "reverse_ordered_od",
        "official_zero_same_stop",
        "unknown_boarding_stop",
        "unknown_alighting_stop",
        "missing_scope",
        "wrong_domestic_mtr_scope",
        "generic_pt_mode",
        "missing_actual_mode",
        "unsupported_child",
        "unsupported_payment",
        "missing_boarding_stop",
        "missing_alighting_stop",
        "same_stop_missing_not_applicable_complete_matrix",
        "unresolved_official_od_not_present_complete_matrix",
        "ambiguous_od_not_present_unique_matrix",
        "transfer_concession_requested",
        "travel_date_before_effective",
        "invalid_travel_date",
    }
    if set(fixture_input["quote_id"]) != required_ids:
        raise AssertionError("Fixture case set is incomplete")
    priced_ids = {
        "available_ordered_od",
        "reverse_ordered_od",
        "official_zero_same_stop",
        "same_stop_missing_not_applicable_complete_matrix",
        "unresolved_official_od_not_present_complete_matrix",
        "ambiguous_od_not_present_unique_matrix",
        "transfer_concession_requested",
    }
    unresolved_ids = required_ids - priced_ids
    if not by_id.loc[sorted(priced_ids), "cost_hkd"].notna().all():
        raise AssertionError("Expected available fixture case was not priced")
    if not by_id.loc[sorted(priced_ids), "cost_quality"].eq("B").all():
        raise AssertionError("Available Light Rail quote exceeded quality B")
    if by_id.loc[sorted(unresolved_ids), "cost_hkd"].notna().any():
        raise AssertionError("Unresolved fixture request received a fare")
    if not by_id.loc[sorted(unresolved_ids), "cost_quality"].eq("U").all():
        raise AssertionError("Unresolved fixture request is not quality U")
    if float(by_id.loc["official_zero_same_stop", "cost_hkd"]) != 0:
        raise AssertionError("Official zero fare was treated as missing")
    if (
        by_id.loc["available_ordered_od", "source_record_id"]
        == by_id.loc["reverse_ordered_od", "source_record_id"]
    ):
        raise AssertionError("Reverse OD reused the forward raw source record")
    if (
        by_id.loc["travel_date_before_effective", "unresolved_reason"]
        != "travel_date_precedes_fare_effective_date"
    ):
        raise AssertionError("Pre-effective-date fixture behavior is wrong")
    if (
        by_id.loc["invalid_travel_date", "unresolved_reason"]
        != "invalid_travel_date"
    ):
        raise AssertionError("Invalid-date fixture behavior is wrong")
    if fixture_output["transfer_concession_hkd"].notna().any():
        raise AssertionError("Fixture contains a transfer concession amount")
    if not fixture_output["transfer_concession_status"].eq("not_modelled").all():
        raise AssertionError("Transfer concession status is not_modelled")
    if not fixture_output["fare_amount_role"].eq(FARE_AMOUNT_ROLE).all():
        raise AssertionError("Fixture does not label the amount as base fare")
    return {
        "cases": int(len(actual)),
        "passed": int(len(actual)),
        "priced": int(actual["cost_hkd"].notna().sum()),
        "unresolved": int(actual["cost_hkd"].isna().sum()),
        "source_unresolved_od_cases_available": 0,
        "source_ambiguous_od_cases_available": 0,
        "source_same_stop_missing_cases_available": 0,
    }


def validate_mtr_directory(
    output_dir: Path, model_dir: Path
) -> dict[str, Any]:
    baseline = pd.read_csv(
        output_dir / "mtr_station_od_v1_protected_hashes.csv",
        dtype=str,
        keep_default_na=False,
    )
    require_columns(
        baseline,
        ["filename", "size_bytes", "sha256_before"],
        "MTR protected hash baseline",
    )
    mtr_dir = model_dir / "mtr_station_od_v1"
    actual_files = {path.name for path in mtr_dir.iterdir() if path.is_file()}
    if actual_files != set(baseline["filename"]):
        raise AssertionError("MTR station-OD directory file set changed")
    for row in baseline.itertuples(index=False):
        path = mtr_dir / row.filename
        if (
            path.stat().st_size != int(row.size_bytes)
            or sha256(path) != row.sha256_before
        ):
            raise AssertionError(f"MTR station-OD file changed: {row.filename}")
    sha_entries = {}
    for line in (mtr_dir / "SHA256SUMS.txt").read_text(
        encoding="utf-8"
    ).splitlines():
        if line.strip():
            digest, filename = line.split("  ", 1)
            sha_entries[filename] = digest
    for filename, digest in sha_entries.items():
        if sha256(mtr_dir / filename) != digest:
            raise AssertionError(f"MTR internal SHA mismatch: {filename}")
    return {"files_checked": int(len(baseline)), "all_unchanged": True}


def validate_production_audit(model_dir: Path) -> dict[str, Any]:
    trips = pd.read_parquet(model_dir / "pt_passenger_trip_fare_audit.parquet")
    if len(trips) != 557_104:
        raise AssertionError("Production PT audit row count changed")
    if trips["cost_hkd"].notna().any():
        raise AssertionError("Production generic PT trips gained a fare")
    if not trips["mapping_status"].eq("unresolved").all():
        raise AssertionError("Production PT audit is not all unresolved")
    return {
        "rows": int(len(trips)),
        "priced_rows": 0,
        "unresolved_rows": int(len(trips)),
    }


def validate_protected_inputs(
    model_dir: Path, source_root: Path
) -> dict[str, Any]:
    baseline = pd.read_csv(model_dir / "protected_input_hashes_baseline.csv")
    for row in baseline.itertuples(index=False):
        path = source_root / Path(row.repository_relative_path)
        if (
            path.stat().st_size != int(row.size_bytes)
            or sha256(path) != row.sha256_before
        ):
            raise AssertionError(f"Protected MATSim input changed: {row.repository_relative_path}")
    return {"files_checked": int(len(baseline)), "all_unchanged": True}


def validate_summary(
    summary: dict[str, Any],
    stops: dict[str, Any],
    fare_result: dict[str, Any],
    routes: dict[str, Any],
    fixture: dict[str, Any],
) -> None:
    if int(summary["official_stops"]) != stops["official_stops"]:
        raise AssertionError("Official stop summary mismatch")
    if summary["stop_crosswalk"] != stops["mapping_status"]:
        raise AssertionError("Stop crosswalk summary mismatch")
    fields = [
        "raw_ordered_od_records",
        "available_records",
        "ambiguous_records",
        "unresolved_records",
        "official_zero_fare_records",
    ]
    for field in fields:
        if int(summary["fare_rules"][field]) != int(fare_result[field]):
            raise AssertionError(f"Fare summary mismatch: {field}")
    if summary["route_mapping_status"] != routes["mapping_status"]:
        raise AssertionError("Route status summary mismatch")
    if summary["route_mapping_quality"] != routes["mapping_quality"]:
        raise AssertionError("Route quality summary mismatch")
    if summary["route_fare_readiness"] != routes["fare_readiness"]:
        raise AssertionError("Route readiness summary mismatch")
    if summary["route_pattern_type"] != routes["route_pattern_type"]:
        raise AssertionError("Route pattern summary mismatch")
    if int(summary["forward_pairs"]["required"]) != routes[
        "forward_pairs_required"
    ]:
        raise AssertionError("Forward-pair required summary mismatch")
    if int(summary["forward_pairs"]["matched"]) != routes[
        "forward_pairs_matched"
    ]:
        raise AssertionError("Forward-pair matched summary mismatch")
    if int(summary["fixture"]["total"]) != fixture["cases"]:
        raise AssertionError("Fixture summary mismatch")


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
    entries = {}
    for line in (output_dir / "SHA256SUMS.txt").read_text(
        encoding="utf-8"
    ).splitlines():
        if line.strip():
            digest, filename = line.split("  ", 1)
            entries[filename] = digest
    expected = {
        path.name
        for path in output_dir.iterdir()
        if path.is_file() and path.name != "SHA256SUMS.txt"
    }
    if set(entries) != expected:
        raise AssertionError("Light Rail SHA256SUMS file set mismatch")
    for filename, digest in entries.items():
        if sha256(output_dir / filename) != digest:
            raise AssertionError(f"Light Rail output SHA mismatch: {filename}")
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
        else model_dir / "light_rail_station_od_v1"
    )

    _, fare_source, _ = read_manifest(model_dir, source_root)
    fares, patterns, raw_records = read_raw_sources(source_root)
    inventory = pd.read_csv(
        model_dir / "transit_schedule_inventory.csv",
        dtype=str,
        keep_default_na=False,
    )
    top_crosswalk = pd.read_csv(
        model_dir / "route_to_official_fare_match.csv",
        dtype=str,
        keep_default_na=False,
    )
    stop_crosswalk = pd.read_csv(
        output_dir / "light_rail_stop_crosswalk.csv",
        dtype=str,
        keep_default_na=False,
    )
    rules = pd.read_parquet(
        output_dir / "light_rail_station_od_fare_rules.parquet"
    )
    conflicts = pd.read_csv(
        output_dir / "light_rail_fare_conflicts.csv",
        dtype=str,
        keep_default_na=False,
    )
    unresolved = pd.read_csv(
        output_dir / "light_rail_unresolved_od_pairs.csv",
        dtype=str,
        keep_default_na=False,
    )
    readiness = pd.read_csv(
        output_dir / "light_rail_schedule_route_fare_readiness.csv",
        dtype=str,
        keep_default_na=False,
    )
    fixture_input = pd.read_csv(
        output_dir / "light_rail_fare_query_fixture_input.csv",
        dtype=str,
        keep_default_na=False,
    )
    fixture_output = pd.read_csv(
        output_dir / "light_rail_fare_query_fixture_output.csv",
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
        (output_dir / "light_rail_station_od_summary.json").read_text(
            encoding="utf-8"
        )
    )

    facility_map, route_stop_ids = independently_map_facilities(
        source_root, patterns, inventory
    )
    stop_result = validate_stop_crosswalk(
        stop_crosswalk, fares, patterns, facility_map
    )
    fare_result = validate_rules(
        rules,
        conflicts,
        unresolved,
        fares,
        raw_records,
        fare_source,
        model_dir / "official_fares_normalized.parquet",
    )
    route_result = validate_route_readiness(
        readiness,
        inventory,
        top_crosswalk,
        patterns,
        route_stop_ids,
        fares,
    )
    fixture_result = validate_fixture(fixture_input, fixture_output, rules)
    mtr_result = validate_mtr_directory(output_dir, model_dir)
    production_result = validate_production_audit(model_dir)
    protected_result = validate_protected_inputs(model_dir, source_root)
    validate_summary(
        summary, stop_result, fare_result, route_result, fixture_result
    )
    portability = validate_portability(output_dir)

    validation = {
        "validator": "independent Hong Kong Light Rail station-OD validator v1",
        "stop_crosswalk": stop_result,
        "fare_rules": fare_result,
        "route_readiness": route_result,
        "fixture": fixture_result,
        "effective_date_evidence": {
            "effective_date": fare_source["effective_date"],
            "effective_date_status": fare_source["effective_date_status"],
        },
        "transfer_concessions": {
            "amounts_present": 0,
            "status": "not_modelled",
            "fare_amount_role": FARE_AMOUNT_ROLE,
        },
        "mtr_station_od_v1": mtr_result,
        "production_pt_audit": production_result,
        "protected_inputs": protected_result,
        "portability": {
            "text_files_checked": portability,
            "absolute_local_paths_found": 0,
        },
        "validation_passed": True,
    }
    (output_dir / "light_rail_station_od_validation.json").write_text(
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
