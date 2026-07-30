"""Build auditable Hong Kong Light Rail adult Octopus stop-OD rules v1.

The builder rereads the original official Light Rail CSV files, cross-checks
the normalized catalog, maps exact stop codes to schedule facilities, and
writes a pure offline ordered-OD rule layer. It never reads production plans.
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
    quote_dataframe,
)


CANONICAL_SOURCE_ROOT = Path(r"F:\Matsim\matsim-example-project")
FARE_SCOPE = "light_rail_station_od"
FARE_SOURCE_ID = "mtr_light_rail_fares"
PATTERN_SOURCE_ID = "mtr_light_rail_stop_patterns"


def repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build auditable Hong Kong Light Rail adult Octopus ordered "
            "stop-OD fare rules v1."
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


def compact_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def sort_stop_id(value: str) -> tuple[int, str]:
    text = str(value)
    return (int(text), text) if text.isdigit() else (10**9, text)


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
    required_ids = {FARE_SOURCE_ID, PATTERN_SOURCE_ID}
    if not required_ids.issubset(set(manifest["source_id"])):
        raise AssertionError("Light Rail sources missing from manifest")
    source_rows: dict[str, dict[str, str]] = {}
    for source_id in required_ids:
        rows = manifest[manifest["source_id"].eq(source_id)]
        if len(rows) != 1:
            raise AssertionError(f"Expected one manifest row for {source_id}")
        record = {str(key): str(value) for key, value in rows.iloc[0].items()}
        path = source_root / Path(record["repository_relative_path"])
        if (
            not path.exists()
            or path.stat().st_size != int(record["size_bytes"])
            or sha256(path) != record["sha256"]
        ):
            raise AssertionError(f"Light Rail source integrity failure: {source_id}")
        source_rows[source_id] = record
    fare_source = source_rows[FARE_SOURCE_ID]
    if (
        fare_source["effective_date_status"]
        != "external_official_reference_not_locally_archived"
    ):
        raise AssertionError("Light Rail date evidence was improperly upgraded")
    return manifest, fare_source, source_rows[PATTERN_SOURCE_ID]


def read_lrt_schedule_routes(
    schedule_path: Path,
) -> dict[tuple[str, str], list[str]]:
    with gzip.open(schedule_path, "rb") as handle:
        root = ET.parse(handle).getroot()
    routes: dict[tuple[str, str], list[str]] = {}
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
                routes[(line.attrib["id"], route.attrib["id"])] = refs
    if len(routes) != 20:
        raise AssertionError(f"Expected 20 Light Rail routes, found {len(routes)}")
    return routes


def exact_stop_code_candidates(
    facility_id: str, known_codes: set[str]
) -> list[str]:
    return sorted(
        code
        for code in known_codes
        if re.search(rf"(?:^|_){re.escape(code)}(?:_|$)", facility_id)
    )


def build_stop_crosswalk(
    fares: pd.DataFrame,
    patterns: pd.DataFrame,
    inventory: pd.DataFrame,
    schedule_routes: dict[tuple[str, str], list[str]],
) -> tuple[pd.DataFrame, dict[tuple[str, str], list[str]]]:
    patterns = patterns.rename(
        columns={
            "Line Code": "line_code",
            "Direction": "direction",
            "Stop Code": "stop_code",
            "Stop ID": "stop_id",
            "English Name": "stop_name_en",
            "Sequence": "sequence",
        }
    )
    fare_ids = set(fares["from_station_id"]) | set(fares["to_station_id"])
    pattern_ids = set(patterns["stop_id"])
    all_ids = fare_ids | pattern_ids
    stop_code_by_id = (
        patterns.groupby("stop_id")["stop_code"]
        .agg(lambda values: sorted(set(values)))
        .to_dict()
    )
    stop_name_by_id = (
        patterns.groupby("stop_id")["stop_name_en"]
        .agg(lambda values: sorted(set(values))[0])
        .to_dict()
    )
    route_codes_by_id = (
        patterns.groupby("stop_id")["line_code"]
        .agg(lambda values: sorted(set(values)))
        .to_dict()
    )
    ids_by_line_code = (
        patterns.groupby(["line_code", "stop_code"])["stop_id"]
        .agg(lambda values: sorted(set(values)))
        .to_dict()
    )
    known_codes = set(patterns["stop_code"])

    lrt_inventory = inventory[inventory["transport_mode"].eq("light_rail")]
    if len(lrt_inventory) != 20:
        raise AssertionError("Inventory does not contain 20 Light Rail routes")
    facility_candidates: dict[str, set[str]] = {}
    mapped_routes: dict[tuple[str, str], list[str]] = {}
    for row in lrt_inventory.itertuples(index=False):
        key = (str(row.matsim_line_id), str(row.matsim_route_id))
        refs = schedule_routes.get(key)
        if refs is None:
            raise AssertionError(f"Light Rail route missing from schedule: {key}")
        mapped: list[str] = []
        for facility_id in refs:
            codes = exact_stop_code_candidates(facility_id, known_codes)
            candidate_ids = (
                set(
                    ids_by_line_code.get(
                        (str(row.official_route_id), codes[0]), []
                    )
                )
                if len(codes) == 1
                else set()
            )
            facility_candidates.setdefault(facility_id, set()).update(candidate_ids)
            mapped.append(
                next(iter(candidate_ids)) if len(candidate_ids) == 1 else ""
            )
        expected = [str(value) for value in json.loads(row.official_stop_ids_json)]
        if mapped != expected:
            raise AssertionError(
                f"Raw stop-code mapping differs from inventory for {key}"
            )
        mapped_routes[key] = mapped

    exact_facilities_by_id: dict[str, set[str]] = {}
    ambiguous_ids: set[str] = set()
    for facility_id, candidates in facility_candidates.items():
        if len(candidates) == 1:
            stop_id = next(iter(candidates))
            exact_facilities_by_id.setdefault(stop_id, set()).add(facility_id)
        elif len(candidates) > 1:
            ambiguous_ids.update(candidates)

    rows: list[dict[str, Any]] = []
    for stop_id in sorted(all_ids, key=sort_stop_id):
        codes = stop_code_by_id.get(stop_id, [])
        facilities = sorted(exact_facilities_by_id.get(stop_id, set()))
        if stop_id in ambiguous_ids:
            candidate_count = 2
            status = "ambiguous"
            quality = "D"
            reason = "schedule_facility_maps_to_multiple_official_stop_ids"
        elif facilities:
            candidate_count = 1
            status = "exact"
            quality = "A"
            reason = ""
        else:
            candidate_count = 0
            status = "unresolved"
            quality = "U"
            reason = (
                "official_stop_id_missing_stop_code"
                if not codes
                else "official_stop_id_not_present_in_schedule"
            )
        rows.append(
            {
                "stop_id": stop_id,
                "stop_code": codes[0] if len(codes) == 1 else "",
                "stop_name_en": stop_name_by_id.get(stop_id, ""),
                "official_route_codes": ";".join(
                    route_codes_by_id.get(stop_id, [])
                ),
                "in_fare_matrix": stop_id in fare_ids,
                "in_official_route_pattern": stop_id in pattern_ids,
                "in_schedule": bool(facilities),
                "schedule_facility_count": len(facilities),
                "schedule_facility_ids_json": compact_json(facilities),
                "candidate_count": candidate_count,
                "candidate_cardinality": (
                    "none"
                    if candidate_count == 0
                    else "one"
                    if candidate_count == 1
                    else "multiple"
                ),
                "candidate_official_stop_ids_json": compact_json(
                    [stop_id] if candidate_count == 1 else []
                ),
                "mapping_status": status,
                "mapping_quality": quality,
                "matching_method": (
                    "exact_official_line_code_and_stop_code_tokens"
                    if facilities
                    else "no_fuzzy_name_or_coordinate_fallback"
                ),
                "source_id": PATTERN_SOURCE_ID if codes else FARE_SOURCE_ID,
                "unresolved_reason": reason,
            }
        )
    return pd.DataFrame(rows), mapped_routes


def build_rule_tables(
    fares: pd.DataFrame,
    stop_names: dict[str, str],
    source: dict[str, str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    fares = fares.copy()
    fares["_csv_line"] = np.arange(2, len(fares) + 2)
    rows: list[dict[str, Any]] = []
    conflict_rows: list[dict[str, Any]] = []
    unresolved_rows: list[dict[str, Any]] = []
    for (boarding, alighting), group in fares.groupby(
        ["from_station_id", "to_station_id"], sort=False
    ):
        candidates = []
        amounts: list[float] = []
        for record in group.to_dict("records"):
            amount_text = str(record["fare_octo_adult"]).strip()
            amount = float(amount_text) if amount_text else np.nan
            source_record_id = (
                f"{FARE_SOURCE_ID}:csv_line_{int(record['_csv_line']):06d}"
            )
            candidates.append(
                {
                    "source_record_id": source_record_id,
                    "csv_line": int(record["_csv_line"]),
                    "fare_hkd": None if pd.isna(amount) else amount,
                }
            )
            if not pd.isna(amount):
                amounts.append(amount)
        distinct = sorted(set(amounts))
        if len(distinct) > 1:
            status = "ambiguous"
            amount: float | None = None
            source_record_id = ""
            reason = "conflicting_official_fares_for_ordered_od_key"
        elif len(distinct) == 1:
            status = "available"
            amount = distinct[0]
            source_record_id = (
                candidates[0]["source_record_id"] if len(candidates) == 1 else ""
            )
            reason = ""
        else:
            status = "unresolved"
            amount = None
            source_record_id = ""
            reason = "official_ordered_od_record_has_no_adult_octopus_fare"
        base = {
            "fare_network_scope": FARE_SCOPE,
            "boarding_stop_id": str(boarding),
            "alighting_stop_id": str(alighting),
            "boarding_stop_name_en": stop_names.get(str(boarding), ""),
            "alighting_stop_name_en": stop_names.get(str(alighting), ""),
            "adult_octopus_fare_hkd": amount,
            "currency": "HKD",
            "cost_component": "public_transport_fare",
            "fare_amount_role": FARE_AMOUNT_ROLE,
            "cost_source": FARE_SOURCE_ID,
            "cost_effective_date": (
                source["effective_date"] if status == "available" else ""
            ),
            "cost_effective_date_status": (
                source["effective_date_status"] if status == "available" else ""
            ),
            "source_record_id": source_record_id,
            "source_file": source["repository_relative_path"],
            "source_sha256": source["sha256"],
            "record_status": status,
            "candidate_records_json": compact_json(candidates),
            "matching_method": "exact_ordered_stop_id_raw_csv_record",
            "unresolved_reason": reason,
        }
        rows.append(base)
        if status == "ambiguous":
            conflict_rows.append(dict(base))
        elif status == "unresolved":
            unresolved_rows.append(dict(base))

    columns = list(rows[0])
    rules = pd.DataFrame(rows, columns=columns)
    conflicts = pd.DataFrame(conflict_rows, columns=columns)
    unresolved = pd.DataFrame(unresolved_rows, columns=columns)
    for frame in (rules, conflicts, unresolved):
        frame["adult_octopus_fare_hkd"] = pd.array(
            frame["adult_octopus_fare_hkd"], dtype="Float64"
        )
    return rules, conflicts, unresolved


def crosscheck_normalized(rules: pd.DataFrame, normalized_path: Path) -> int:
    normalized = pd.read_parquet(normalized_path)
    existing = normalized[
        normalized["source_id"].eq("mtr_light_rail_fares_20260720")
    ][["origin_stop_id", "destination_stop_id", "adult_octopus_fare_hkd"]]
    available = rules[rules["record_status"].eq("available")][
        ["boarding_stop_id", "alighting_stop_id", "adult_octopus_fare_hkd"]
    ]
    merged = available.merge(
        existing,
        left_on=["boarding_stop_id", "alighting_stop_id"],
        right_on=["origin_stop_id", "destination_stop_id"],
        how="outer",
        suffixes=("_raw", "_normalized"),
        indicator=True,
    )
    if not merged["_merge"].eq("both").all():
        raise AssertionError("Raw and normalized Light Rail OD keys differ")
    if not np.allclose(
        merged["adult_octopus_fare_hkd_raw"],
        merged["adult_octopus_fare_hkd_normalized"],
        rtol=0,
        atol=1e-9,
    ):
        raise AssertionError("Raw and normalized Light Rail amounts differ")
    return len(available)


def distinct_ordered_forward_pairs(stops: list[str]) -> set[tuple[str, str]]:
    return {
        (stops[index], stops[later])
        for index in range(len(stops))
        for later in range(index + 1, len(stops))
        if stops[index] and stops[later] and stops[index] != stops[later]
    }


def is_contiguous_subsequence(sequence: list[str], reference: list[str]) -> bool:
    if len(sequence) > len(reference):
        return False
    return any(
        reference[start : start + len(sequence)] == sequence
        for start in range(len(reference) - len(sequence) + 1)
    )


def build_route_readiness(
    inventory: pd.DataFrame,
    top_crosswalk: pd.DataFrame,
    direction_patterns: pd.DataFrame,
    rules: pd.DataFrame,
) -> pd.DataFrame:
    lrt_inventory = inventory[inventory["transport_mode"].eq("light_rail")]
    lrt_crosswalk = top_crosswalk[
        top_crosswalk["transport_mode"].eq("light_rail")
    ]
    routes = lrt_inventory.merge(
        lrt_crosswalk,
        on=["matsim_line_id", "matsim_route_id", "transport_mode"],
        how="inner",
        validate="one_to_one",
        suffixes=("_inventory", ""),
    )
    if len(routes) != 20:
        raise AssertionError("Light Rail readiness merge must contain 20 routes")
    pattern_map = {
        (str(row.official_line_id), str(row.official_direction)): [
            str(value) for value in json.loads(row.official_stop_ids_json)
        ]
        for row in direction_patterns[
            direction_patterns["transport_mode"].eq("light_rail")
        ].itertuples(index=False)
    }
    available = set(
        rules.loc[
            rules["record_status"].eq("available"),
            ["boarding_stop_id", "alighting_stop_id"],
        ].itertuples(index=False, name=None)
    )
    output_rows = []
    for row in routes.itertuples(index=False):
        stops = [
            str(value) for value in json.loads(row.official_stop_ids_json)
        ]
        pairs = distinct_ordered_forward_pairs(stops)
        matched = len(pairs & available)
        if row.mapping_status == "one_to_many_explicit":
            pattern_type = "loop_multi_direction_composite"
            if stops[0] != stops[-1]:
                raise AssertionError(f"Loop does not close: {row.matsim_route_id}")
        elif row.direction_status == "explicit_direction_short_turn":
            pattern_type = "short_turn"
            reference = pattern_map.get(
                (str(row.official_line_id), str(row.official_direction))
            )
            if reference is None or not is_contiguous_subsequence(stops, reference):
                raise AssertionError(
                    f"Short turn is not an official subsequence: {row.matsim_route_id}"
                )
        else:
            pattern_type = "exact_direction"
            reference = pattern_map.get(
                (str(row.official_line_id), str(row.official_direction))
            )
            if reference != stops:
                raise AssertionError(
                    f"Exact direction differs from raw pattern: {row.matsim_route_id}"
                )
        readiness = (
            "ready"
            if matched == len(pairs)
            and float(row.stop_id_coverage) == 1.0
            else "partial_missing_official_od"
        )
        output_rows.append(
            {
                "matsim_line_id": row.matsim_line_id,
                "matsim_route_id": row.matsim_route_id,
                "official_line_id": row.official_line_id,
                "official_direction": row.official_direction,
                "scheduled_stop_count": len(stops),
                "mapped_stop_count": sum(bool(value) for value in stops),
                "stop_id_coverage": float(row.stop_id_coverage),
                "direction_status": row.direction_status,
                "candidate_count": int(row.candidate_count),
                "required_forward_pair_count": len(pairs),
                "matched_forward_pair_count": matched,
                "forward_pair_coverage": matched / len(pairs) if pairs else 0.0,
                "fare_network_scope": FARE_SCOPE,
                "mapping_status": row.mapping_status,
                "mapping_quality": row.mapping_quality,
                "fare_readiness": readiness,
                "route_pattern_type": pattern_type,
                "matching_method": row.matching_method,
                "evidence": row.evidence,
                "unresolved_reason": row.unresolved_reason,
            }
        )
    return pd.DataFrame(output_rows).sort_values(
        ["matsim_line_id", "matsim_route_id"]
    )


def build_fixture() -> pd.DataFrame:
    common = {
        "actual_transport_mode": "light_rail",
        "fare_network_scope": FARE_SCOPE,
        "boarding_stop_id": "1",
        "alighting_stop_id": "10",
        "passenger_type": "adult",
        "payment_medium": "Octopus",
        "travel_date": "2026-07-28",
        "transfer_concession_requested": "false",
    }
    rows: list[dict[str, str]] = []

    def add(quote_id: str, **updates: str) -> None:
        row = dict(common)
        row.update(updates)
        row["quote_id"] = quote_id
        rows.append(row)

    add("available_ordered_od")
    add("reverse_ordered_od", boarding_stop_id="10", alighting_stop_id="1")
    add("official_zero_same_stop", boarding_stop_id="1", alighting_stop_id="1")
    add("unknown_boarding_stop", boarding_stop_id="9999")
    add("unknown_alighting_stop", alighting_stop_id="9999")
    add("missing_scope", fare_network_scope="")
    add("wrong_domestic_mtr_scope", fare_network_scope="domestic_mtr_station_od")
    add("generic_pt_mode", actual_transport_mode="pt")
    add("missing_actual_mode", actual_transport_mode="")
    add("unsupported_child", passenger_type="child")
    add("unsupported_payment", payment_medium="SingleJourneyTicket")
    add("missing_boarding_stop", boarding_stop_id="")
    add("missing_alighting_stop", alighting_stop_id="")
    add(
        "same_stop_missing_not_applicable_complete_matrix",
        boarding_stop_id="10",
        alighting_stop_id="10",
    )
    add(
        "unresolved_official_od_not_present_complete_matrix",
        boarding_stop_id="15",
        alighting_stop_id="20",
    )
    add(
        "ambiguous_od_not_present_unique_matrix",
        boarding_stop_id="20",
        alighting_stop_id="15",
    )
    add("transfer_concession_requested", transfer_concession_requested="true")
    add("travel_date_before_effective", travel_date="2024-06-29")
    add("invalid_travel_date", travel_date="2024/06/30")
    columns = [
        "quote_id",
        "actual_transport_mode",
        "fare_network_scope",
        "boarding_stop_id",
        "alighting_stop_id",
        "passenger_type",
        "payment_medium",
        "travel_date",
        "transfer_concession_requested",
    ]
    return pd.DataFrame(rows, columns=columns)


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
    output_dir.mkdir(parents=True, exist_ok=True)

    _, fare_source, pattern_source = read_manifest(model_dir, source_root)
    fares_path = source_root / Path(fare_source["repository_relative_path"])
    patterns_path = source_root / Path(pattern_source["repository_relative_path"])
    fares = pd.read_csv(fares_path, dtype=str, keep_default_na=False)
    patterns = pd.read_csv(patterns_path, dtype=str, keep_default_na=False)
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
    for column in [
        "stop_id_coverage",
        "candidate_count",
        "required_forward_pair_count",
        "matched_forward_pair_count",
        "forward_pair_coverage",
    ]:
        top_crosswalk[column] = pd.to_numeric(
            top_crosswalk[column], errors="raise"
        )
    direction_patterns = pd.read_csv(
        model_dir / "official_direction_stop_patterns.csv",
        dtype=str,
        keep_default_na=False,
    )
    schedule_path = (
        source_root
        / "data/transit/hongkong/processed/"
        "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_"
        "ferry_core_v1_cap010/transitSchedule_5pct.xml.gz"
    )
    schedule_routes = read_lrt_schedule_routes(schedule_path)
    stop_crosswalk, _ = build_stop_crosswalk(
        fares, patterns, inventory, schedule_routes
    )
    stop_names = stop_crosswalk.set_index("stop_id")["stop_name_en"].to_dict()
    rules, conflicts, unresolved = build_rule_tables(
        fares, stop_names, fare_source
    )
    rules["_boarding_sort"] = rules["boarding_stop_id"].map(
        lambda value: sort_stop_id(str(value))[0]
    )
    rules["_alighting_sort"] = rules["alighting_stop_id"].map(
        lambda value: sort_stop_id(str(value))[0]
    )
    rules = rules.sort_values(
        [
            "_boarding_sort",
            "_alighting_sort",
            "boarding_stop_id",
            "alighting_stop_id",
        ]
    ).drop(columns=["_boarding_sort", "_alighting_sort"])
    if rules.duplicated(
        ["fare_network_scope", "boarding_stop_id", "alighting_stop_id"]
    ).any():
        raise AssertionError("Duplicate Light Rail ordered OD rule key")
    normalized_count = crosscheck_normalized(
        rules, model_dir / "official_fares_normalized.parquet"
    )
    readiness = build_route_readiness(
        inventory, top_crosswalk, direction_patterns, rules
    )
    fixture_input = build_fixture()
    fixture_output = quote_dataframe(fixture_input, rules)

    stop_crosswalk.to_csv(
        output_dir / "light_rail_stop_crosswalk.csv",
        index=False,
        encoding="utf-8",
    )
    rules.to_parquet(
        output_dir / "light_rail_station_od_fare_rules.parquet", index=False
    )
    rules.head(100).to_csv(
        output_dir / "light_rail_station_od_fare_rules_sample.csv",
        index=False,
        encoding="utf-8",
    )
    conflicts.to_csv(
        output_dir / "light_rail_fare_conflicts.csv",
        index=False,
        encoding="utf-8",
    )
    unresolved.to_csv(
        output_dir / "light_rail_unresolved_od_pairs.csv",
        index=False,
        encoding="utf-8",
    )
    readiness.to_csv(
        output_dir / "light_rail_schedule_route_fare_readiness.csv",
        index=False,
        encoding="utf-8",
    )
    fixture_input.to_csv(
        output_dir / "light_rail_fare_query_fixture_input.csv",
        index=False,
        encoding="utf-8",
    )
    fixture_output.to_csv(
        output_dir / "light_rail_fare_query_fixture_output.csv",
        index=False,
        encoding="utf-8",
    )

    summary = {
        "model": "Hong Kong Light Rail adult Octopus station-OD fare rules v1",
        "model_role": "offline_explicit_light_rail_stop_od_quote_rules",
        "official_stops": int(len(stop_crosswalk)),
        "stop_crosswalk": {
            str(key): int(value)
            for key, value in stop_crosswalk["mapping_status"]
            .value_counts()
            .items()
        },
        "fare_rules": {
            "raw_ordered_od_records": int(len(fares)),
            "total_rule_records": int(len(rules)),
            "available_records": int(rules["record_status"].eq("available").sum()),
            "ambiguous_records": int(rules["record_status"].eq("ambiguous").sum()),
            "unresolved_records": int(rules["record_status"].eq("unresolved").sum()),
            "official_zero_fare_records": int(
                rules["adult_octopus_fare_hkd"].eq(0).sum()
            ),
            "raw_to_normalized_records_crosschecked": int(normalized_count),
        },
        "route_mapping_status": {
            str(key): int(value)
            for key, value in readiness["mapping_status"].value_counts().items()
        },
        "route_mapping_quality": {
            str(key): int(value)
            for key, value in readiness["mapping_quality"].value_counts().items()
        },
        "route_fare_readiness": {
            str(key): int(value)
            for key, value in readiness["fare_readiness"].value_counts().items()
        },
        "route_pattern_type": {
            str(key): int(value)
            for key, value in readiness["route_pattern_type"].value_counts().items()
        },
        "forward_pairs": {
            "required": int(readiness["required_forward_pair_count"].sum()),
            "matched": int(readiness["matched_forward_pair_count"].sum()),
            "coverage": (
                float(readiness["matched_forward_pair_count"].sum())
                / float(readiness["required_forward_pair_count"].sum())
            ),
        },
        "fixture": {
            "total": int(len(fixture_output)),
            "priced": int(fixture_output["cost_hkd"].notna().sum()),
            "unresolved": int(fixture_output["cost_hkd"].isna().sum()),
            "not_applicable_source_cases": [
                "same_stop_without_official_record",
                "unresolved_official_od",
                "ambiguous_official_od",
            ],
            "not_applicable_reason": (
                "official Light Rail CSV is a complete unique 68x68 matrix"
            ),
        },
        "effective_date": fare_source["effective_date"],
        "effective_date_status": fare_source["effective_date_status"],
        "fare_amount_role": FARE_AMOUNT_ROLE,
        "transfer_concessions": "not_modelled",
        "production_passenger_trip_pricing": "not_performed",
        "prohibited_inference_methods_present": False,
    }
    (output_dir / "light_rail_station_od_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    readme = """# Hong Kong Light Rail station-OD fare rules v1

This directory contains adult Octopus base fares for explicit ordered Light
Rail stop IDs. It is separate from domestic MTR and Airport Express scopes.
The official source is a complete unique 68 by 68 matrix: all 4,624 OD
records are available, including 68 explicit same-stop zero fares.

No reverse substitution, distance interpolation, nearest match, path sum,
cross-scope fallback, full-route replacement, or missing-value zero fill is
used. Transfer concessions are not modelled. The query interface does not
read or price the 557,104 generic production PT legs.
"""
    (output_dir / "README.md").write_text(readme, encoding="utf-8")
    write_sha256s(output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
