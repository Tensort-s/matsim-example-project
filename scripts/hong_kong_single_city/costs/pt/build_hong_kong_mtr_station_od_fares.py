"""Build auditable Hong Kong MTR adult Octopus station-OD fare rules v1.

The builder rereads the original official MTR CSV files, cross-checks the
existing normalized fare catalog, maps official station IDs/codes to schedule
facilities without fuzzy names or coordinates, and writes a pure offline rule
table.  It never reads or changes production plans.
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

from quote_hong_kong_mtr_station_od_fares import quote_dataframe


CANONICAL_SOURCE_ROOT = Path(r"F:\Matsim\matsim-example-project")
DOMESTIC_SCOPE = "domestic_mtr_station_od"
AIRPORT_SCOPE = "airport_express_station_od"
DOMESTIC_SOURCE_ID = "mtr_domestic_fares"
AIRPORT_SOURCE_ID = "mtr_airport_express_fares"
STATION_SOURCE_ID = "mtr_line_station_patterns"


def repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build auditable Hong Kong MTR domestic and Airport Express "
            "adult Octopus ordered station-OD fare rules."
        )
    )
    parser.add_argument("--source-project-root", type=Path, default=None)
    parser.add_argument(
        "--fare-model-dir",
        type=Path,
        default=None,
        help="Existing pt_fare_v1 directory; defaults inside this worktree.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Defaults to pt_fare_v1/mtr_station_od_v1.",
    )
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


def compact_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def sort_station_id(value: str) -> tuple[int, str]:
    text = str(value)
    return (int(text), text) if text.isdigit() else (10**9, text)


def require_columns(frame: pd.DataFrame, columns: list[str], label: str) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise AssertionError(f"{label} missing columns: {missing}")


def read_manifest(model_dir: Path, source_root: Path) -> pd.DataFrame:
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
            "sha256",
        ],
        "fare_source_manifest",
    )
    required = {
        DOMESTIC_SOURCE_ID,
        AIRPORT_SOURCE_ID,
        STATION_SOURCE_ID,
        "td_route_fare_revision_date",
    }
    if not required.issubset(set(manifest["source_id"])):
        raise AssertionError(
            f"Fare source manifest missing: {sorted(required-set(manifest['source_id']))}"
        )
    for row in manifest.itertuples(index=False):
        path = source_root / Path(row.repository_relative_path)
        if not path.exists():
            raise AssertionError(f"Missing source file: {row.repository_relative_path}")
        if sha256(path) != row.sha256:
            raise AssertionError(f"Source SHA256 mismatch: {row.source_id}")
    return manifest


def source_meta(manifest: pd.DataFrame, source_id: str) -> dict[str, str]:
    rows = manifest[manifest["source_id"].eq(source_id)]
    if len(rows) != 1:
        raise AssertionError(f"Expected one manifest row for {source_id}")
    return {str(key): str(value) for key, value in rows.iloc[0].items()}


def read_train_schedule_routes(schedule_path: Path) -> dict[tuple[str, str], list[str]]:
    with gzip.open(schedule_path, "rb") as handle:
        root = ET.parse(handle).getroot()
    routes: dict[tuple[str, str], list[str]] = {}
    for line in root:
        if local_name(line.tag) != "transitLine":
            continue
        line_id = line.attrib["id"]
        for route in line:
            if local_name(route.tag) != "transitRoute":
                continue
            mode = ""
            stop_refs: list[str] = []
            for child in route:
                if local_name(child.tag) == "transportMode":
                    mode = (child.text or "").strip()
                elif local_name(child.tag) == "routeProfile":
                    stop_refs = [
                        stop.attrib["refId"]
                        for stop in child
                        if local_name(stop.tag) == "stop"
                    ]
            if mode == "train":
                key = (line_id, route.attrib["id"])
                if key in routes:
                    raise AssertionError(f"Duplicate train route in schedule: {key}")
                routes[key] = stop_refs
    if len(routes) != 30:
        raise AssertionError(f"Expected 30 train routes, found {len(routes)}")
    return routes


def station_code_candidates(facility_id: str, known_codes: set[str]) -> list[str]:
    return sorted(
        [
            code
            for code in known_codes
            if re.search(rf"(?:^|_){re.escape(code)}(?:_|$)", facility_id)
        ],
        key=lambda value: (-len(value), value),
    )


def read_official_station_tables(
    mtr_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    stations = pd.read_csv(
        mtr_dir / "mtr_lines_and_stations.csv",
        dtype=str,
        keep_default_na=False,
    )
    domestic = pd.read_csv(
        mtr_dir / "mtr_lines_fares.csv",
        dtype=str,
        keep_default_na=False,
    )
    airport = pd.read_csv(
        mtr_dir / "airport_express_fares.csv",
        dtype=str,
        keep_default_na=False,
    )
    stations = stations.rename(
        columns={
            "Line Code": "line_code",
            "Direction": "direction",
            "Station Code": "station_code",
            "Station ID": "station_id",
            "English Name": "station_name_en",
            "Sequence": "sequence",
        }
    )
    stations = stations[
        stations["station_id"].ne("") & stations["station_code"].ne("")
    ].copy()
    return stations, domestic, airport


def build_station_crosswalk(
    stations: pd.DataFrame,
    domestic: pd.DataFrame,
    airport: pd.DataFrame,
    inventory: pd.DataFrame,
    schedule_routes: dict[tuple[str, str], list[str]],
) -> tuple[pd.DataFrame, dict[tuple[str, str], list[str]]]:
    domestic_ids = set(domestic["SRC_STATION_ID"]) | set(
        domestic["DEST_STATION_ID"]
    )
    airport_ids = set(airport["ST_FROM_ID"]) | set(airport["ST_TO_ID"])
    all_ids = set(stations["station_id"]) | domestic_ids | airport_ids

    name_candidates: dict[str, set[str]] = {}
    for station_id, name in stations[
        ["station_id", "station_name_en"]
    ].itertuples(index=False, name=None):
        name_candidates.setdefault(station_id, set()).add(name)
    for station_id, name in pd.concat(
        [
            domestic[["SRC_STATION_ID", "SRC_STATION_NAME"]].rename(
                columns={
                    "SRC_STATION_ID": "station_id",
                    "SRC_STATION_NAME": "station_name_en",
                }
            ),
            domestic[["DEST_STATION_ID", "DEST_STATION_NAME"]].rename(
                columns={
                    "DEST_STATION_ID": "station_id",
                    "DEST_STATION_NAME": "station_name_en",
                }
            ),
            airport[["ST_FROM_ID", "ST_FROM"]].rename(
                columns={"ST_FROM_ID": "station_id", "ST_FROM": "station_name_en"}
            ),
            airport[["ST_TO_ID", "ST_TO"]].rename(
                columns={"ST_TO_ID": "station_id", "ST_TO": "station_name_en"}
            ),
        ],
        ignore_index=True,
    ).itertuples(index=False, name=None):
        if name:
            name_candidates.setdefault(station_id, set()).add(name)

    code_by_id = (
        stations.groupby("station_id")["station_code"]
        .agg(lambda values: sorted(set(values)))
        .to_dict()
    )
    lines_by_id = (
        stations.groupby("station_id")["line_code"]
        .agg(lambda values: sorted(set(values)))
        .to_dict()
    )
    ids_by_line_code = (
        stations.groupby(["line_code", "station_code"])["station_id"]
        .agg(lambda values: sorted(set(values)))
        .to_dict()
    )
    known_codes = set(stations["station_code"])

    train_inventory = inventory[inventory["transport_mode"].eq("train")].copy()
    if len(train_inventory) != 30:
        raise AssertionError("Inventory does not contain 30 train routes")

    facility_candidates: dict[str, set[str]] = {}
    mapped_route_sequences: dict[tuple[str, str], list[str]] = {}
    for row in train_inventory.itertuples(index=False):
        key = (str(row.matsim_line_id), str(row.matsim_route_id))
        refs = schedule_routes.get(key)
        if refs is None:
            raise AssertionError(f"Train route missing from schedule XML: {key}")
        line_code = str(row.official_route_id)
        mapped: list[str] = []
        for facility_id in refs:
            codes = station_code_candidates(facility_id, known_codes)
            if len(codes) != 1:
                mapped.append("")
                continue
            candidates = set(ids_by_line_code.get((line_code, codes[0]), []))
            facility_candidates.setdefault(facility_id, set()).update(candidates)
            mapped.append(next(iter(candidates)) if len(candidates) == 1 else "")
        expected = [str(value) for value in json.loads(row.official_stop_ids_json)]
        if mapped != expected:
            raise AssertionError(
                f"Raw station-code mapping differs from inventory for {key}: "
                f"{mapped} != {expected}"
            )
        mapped_route_sequences[key] = mapped

    exact_facilities_by_id: dict[str, set[str]] = {}
    ambiguous_ids: set[str] = set()
    for facility_id, candidates in facility_candidates.items():
        if len(candidates) == 1:
            station_id = next(iter(candidates))
            exact_facilities_by_id.setdefault(station_id, set()).add(facility_id)
        elif len(candidates) > 1:
            ambiguous_ids.update(candidates)

    rows: list[dict[str, Any]] = []
    for station_id in sorted(all_ids, key=sort_station_id):
        codes = code_by_id.get(station_id, [])
        line_codes = lines_by_id.get(station_id, [])
        facilities = sorted(exact_facilities_by_id.get(station_id, set()))
        if station_id in ambiguous_ids:
            mapping_status = "ambiguous"
            mapping_quality = "D"
            reason = "schedule_facility_maps_to_multiple_official_station_ids"
        elif facilities:
            mapping_status = "exact"
            mapping_quality = "A"
            reason = ""
        else:
            mapping_status = "unresolved"
            mapping_quality = "U"
            reason = (
                "official_station_id_missing_station_code"
                if not codes
                else "official_station_id_not_present_in_schedule"
            )
        names = sorted(name_candidates.get(station_id, {""}))
        preferred_name = names[0] if names else ""
        source_id = STATION_SOURCE_ID if codes else DOMESTIC_SOURCE_ID
        rows.append(
            {
                "station_id": station_id,
                "station_code": codes[0] if len(codes) == 1 else "",
                "station_name_en": preferred_name,
                "line_codes": ";".join(line_codes),
                "in_domestic_fare_matrix": station_id in domestic_ids,
                "in_airport_express_fare_matrix": station_id in airport_ids,
                "in_schedule": bool(facilities),
                "schedule_facility_count": len(facilities),
                "schedule_facility_ids_json": compact_json(facilities),
                "mapping_status": mapping_status,
                "mapping_quality": mapping_quality,
                "matching_method": (
                    "exact_official_line_code_and_station_code_tokens"
                    if facilities
                    else "no_fuzzy_name_or_coordinate_fallback"
                ),
                "source_id": source_id,
                "unresolved_reason": reason,
            }
        )
    crosswalk = pd.DataFrame(rows)
    return crosswalk, mapped_route_sequences


def raw_rule_rows(
    raw: pd.DataFrame,
    scope: str,
    source: dict[str, str],
    source_filename: str,
    origin_id_column: str,
    destination_id_column: str,
    origin_name_column: str,
    destination_name_column: str,
    fare_column: str,
) -> pd.DataFrame:
    frame = raw.copy()
    frame["_csv_line"] = np.arange(2, len(frame) + 2)
    rows: list[dict[str, Any]] = []
    for (boarding, alighting), group in frame.groupby(
        [origin_id_column, destination_id_column], sort=False
    ):
        candidates = []
        fares: list[float] = []
        for record in group.to_dict("records"):
            fare_text = str(record[fare_column]).strip()
            fare = float(fare_text) if fare_text else np.nan
            record_id = (
                f"{source['source_id']}:csv_line_{int(record['_csv_line']):06d}"
            )
            candidates.append(
                {
                    "source_record_id": record_id,
                    "csv_line": int(record["_csv_line"]),
                    "fare_hkd": None if pd.isna(fare) else fare,
                }
            )
            if not pd.isna(fare):
                fares.append(fare)
        distinct_fares = sorted(set(fares))
        if len(distinct_fares) > 1:
            status = "ambiguous"
            amount: float | None = None
            record_id = ""
            reason = "conflicting_official_fares_for_ordered_od_key"
        elif len(distinct_fares) == 1:
            status = "available"
            amount = distinct_fares[0]
            record_id = (
                candidates[0]["source_record_id"] if len(candidates) == 1 else ""
            )
            reason = ""
        else:
            status = "unresolved"
            amount = None
            record_id = ""
            reason = "official_ordered_od_record_has_no_adult_octopus_fare"
        first = group.iloc[0]
        rows.append(
            {
                "fare_network_scope": scope,
                "boarding_station_id": str(boarding),
                "alighting_station_id": str(alighting),
                "boarding_station_name_en": str(first[origin_name_column]),
                "alighting_station_name_en": str(first[destination_name_column]),
                "adult_octopus_fare_hkd": amount,
                "currency": "HKD",
                "cost_component": "public_transport_fare",
                "cost_source": source["source_id"],
                "cost_effective_date": (
                    source["effective_date"] if status == "available" else ""
                ),
                "cost_effective_date_status": (
                    source["effective_date_status"] if status == "available" else ""
                ),
                "source_record_id": record_id,
                "source_file": source["repository_relative_path"],
                "source_sha256": source["sha256"],
                "record_status": status,
                "candidate_records_json": compact_json(candidates),
                "matching_method": "exact_ordered_station_id_raw_csv_record",
                "unresolved_reason": reason,
            }
        )
    return pd.DataFrame(rows)


def ordered_forward_pairs(stops: list[str]) -> list[tuple[str, str]]:
    return [
        (stops[index], stops[later])
        for index in range(len(stops))
        for later in range(index + 1, len(stops))
    ]


def build_airport_missing_pairs(
    airport_rules: pd.DataFrame,
    train_inventory: pd.DataFrame,
    airport_source: dict[str, str],
    station_names: dict[str, str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    available = {
        (str(row.boarding_station_id), str(row.alighting_station_id))
        for row in airport_rules.itertuples(index=False)
        if row.record_status == "available"
    }
    missing_rows: list[dict[str, str]] = []
    for row in train_inventory[
        train_inventory["official_route_id"].eq("AEL")
    ].itertuples(index=False):
        stops = [str(value) for value in json.loads(row.official_stop_ids_json)]
        for boarding, alighting in ordered_forward_pairs(stops):
            if (boarding, alighting) in available:
                continue
            missing_rows.append(
                {
                    "fare_network_scope": AIRPORT_SCOPE,
                    "boarding_station_id": boarding,
                    "alighting_station_id": alighting,
                    "boarding_station_name_en": station_names.get(boarding, ""),
                    "alighting_station_name_en": station_names.get(alighting, ""),
                    "matsim_line_id": str(row.matsim_line_id),
                    "matsim_route_id": str(row.matsim_route_id),
                    "official_line_id": "AEL",
                    "official_direction": str(row.official_route_sequence),
                    "record_status": "unresolved",
                    "unresolved_reason": (
                        "official_airport_express_ordered_od_record_missing"
                    ),
                }
            )
    unresolved = pd.DataFrame(missing_rows).drop_duplicates(
        ["fare_network_scope", "boarding_station_id", "alighting_station_id"]
    )
    unresolved = unresolved.sort_values(
        ["official_direction", "boarding_station_id", "alighting_station_id"]
    ).reset_index(drop=True)
    if len(unresolved) != 6:
        raise AssertionError(
            f"Expected six Airport Express missing pairs, found {len(unresolved)}"
        )

    additional_rules = []
    for row in unresolved.to_dict("records"):
        additional_rules.append(
            {
                "fare_network_scope": AIRPORT_SCOPE,
                "boarding_station_id": row["boarding_station_id"],
                "alighting_station_id": row["alighting_station_id"],
                "boarding_station_name_en": row["boarding_station_name_en"],
                "alighting_station_name_en": row["alighting_station_name_en"],
                "adult_octopus_fare_hkd": None,
                "currency": "HKD",
                "cost_component": "public_transport_fare",
                "cost_source": airport_source["source_id"],
                "cost_effective_date": "",
                "cost_effective_date_status": "",
                "source_record_id": "",
                "source_file": airport_source["repository_relative_path"],
                "source_sha256": airport_source["sha256"],
                "record_status": "unresolved",
                "candidate_records_json": "[]",
                "matching_method": "explicit_absence_from_hashed_official_csv",
                "unresolved_reason": row["unresolved_reason"],
            }
        )
    return unresolved, pd.DataFrame(additional_rules)


def crosscheck_normalized(
    rules: pd.DataFrame, normalized_path: Path
) -> dict[str, int]:
    normalized = pd.read_parquet(normalized_path)
    specifications = [
        (DOMESTIC_SCOPE, "mtr_domestic_fares_20260720"),
        (AIRPORT_SCOPE, "mtr_airport_express_fares_20260720"),
    ]
    result: dict[str, int] = {}
    for scope, normalized_source_id in specifications:
        raw_rules = rules[
            rules["fare_network_scope"].eq(scope)
            & rules["record_status"].eq("available")
        ][
            [
                "boarding_station_id",
                "alighting_station_id",
                "adult_octopus_fare_hkd",
            ]
        ].copy()
        existing = normalized[normalized["source_id"].eq(normalized_source_id)][
            ["origin_stop_id", "destination_stop_id", "adult_octopus_fare_hkd"]
        ].rename(
            columns={
                "origin_stop_id": "boarding_station_id",
                "destination_stop_id": "alighting_station_id",
            }
        )
        merged = raw_rules.merge(
            existing,
            on=["boarding_station_id", "alighting_station_id"],
            how="outer",
            suffixes=("_raw", "_normalized"),
            indicator=True,
        )
        if not merged["_merge"].eq("both").all():
            raise AssertionError(f"Normalized OD keys differ for {scope}")
        if not np.allclose(
            merged["adult_octopus_fare_hkd_raw"],
            merged["adult_octopus_fare_hkd_normalized"],
            rtol=0,
            atol=1e-9,
        ):
            raise AssertionError(f"Normalized fares differ from raw CSV for {scope}")
        result[scope] = len(raw_rules)
    return result


def build_route_readiness(
    inventory: pd.DataFrame,
    route_crosswalk: pd.DataFrame,
    direction_patterns: pd.DataFrame,
    rules: pd.DataFrame,
) -> pd.DataFrame:
    train_inventory = inventory[inventory["transport_mode"].eq("train")].copy()
    train_crosswalk = route_crosswalk[
        route_crosswalk["transport_mode"].eq("train")
    ].copy()
    routes = train_inventory.merge(
        train_crosswalk,
        on=["matsim_line_id", "matsim_route_id", "transport_mode"],
        how="inner",
        validate="one_to_one",
        suffixes=("_inventory", ""),
    )
    if len(routes) != 30:
        raise AssertionError("Train readiness merge does not contain 30 routes")

    pattern_keys = set(
        direction_patterns.loc[
            direction_patterns["transport_mode"].eq("train"),
            ["official_line_id", "official_direction"],
        ].itertuples(index=False, name=None)
    )
    available_by_scope = {
        scope: {
            (str(row.boarding_station_id), str(row.alighting_station_id))
            for row in group.itertuples(index=False)
            if row.record_status == "available"
        }
        for scope, group in rules.groupby("fare_network_scope")
    }

    output_rows: list[dict[str, Any]] = []
    for row in routes.itertuples(index=False):
        stops = [
            str(value) for value in json.loads(row.official_stop_ids_json)
        ]
        pairs = ordered_forward_pairs(stops)
        available = available_by_scope.get(str(row.fare_scope), set())
        matched = sum(pair in available for pair in pairs)
        station_coverage = (
            sum(bool(value) for value in stops) / len(stops) if stops else 0.0
        )
        if station_coverage == 1.0 and matched == len(pairs):
            readiness = "ready"
        elif matched > 0:
            readiness = "partial_missing_official_od"
        else:
            readiness = "unresolved"
        reason = str(row.unresolved_reason)
        if readiness == "partial_missing_official_od":
            reason = "six_airport_express_ordered_od_pairs_missing"
        if (
            int(row.candidate_count) == 1
            and (str(row.official_line_id), str(row.official_direction))
            not in pattern_keys
        ):
            raise AssertionError(
                f"Route direction absent from official patterns: {row.matsim_route_id}"
            )
        output_rows.append(
            {
                "matsim_line_id": row.matsim_line_id,
                "matsim_route_id": row.matsim_route_id,
                "official_line_id": row.official_line_id,
                "official_direction": row.official_direction,
                "scheduled_stop_count": len(stops),
                "mapped_station_count": sum(bool(value) for value in stops),
                "station_id_coverage": station_coverage,
                "direction_status": row.direction_status,
                "required_forward_pair_count": len(pairs),
                "matched_forward_pair_count": matched,
                "forward_pair_coverage": matched / len(pairs) if pairs else 0.0,
                "fare_network_scope": row.fare_scope,
                "mapping_status": row.mapping_status,
                "mapping_quality": row.mapping_quality,
                "fare_readiness": readiness,
                "matching_method": row.matching_method,
                "evidence": row.evidence,
                "unresolved_reason": reason,
            }
        )
    return pd.DataFrame(output_rows).sort_values(
        ["matsim_line_id", "matsim_route_id"]
    )


def fixture_input() -> pd.DataFrame:
    common = {
        "actual_transport_mode": "train",
        "fare_network_scope": DOMESTIC_SCOPE,
        "boarding_station_id": "1",
        "alighting_station_id": "2",
        "passenger_type": "adult",
        "payment_medium": "Octopus",
        "travel_date": "2026-07-28",
        "transfer_concession_requested": "false",
    }
    cases: list[dict[str, str]] = []

    def add(quote_id: str, **updates: str) -> None:
        row = dict(common)
        row.update(updates)
        row["quote_id"] = quote_id
        cases.append(row)

    add("domestic_available")
    add(
        "airport_express_available",
        fare_network_scope=AIRPORT_SCOPE,
        boarding_station_id="44",
        alighting_station_id="47",
    )
    add(
        "domestic_reverse_ordered",
        boarding_station_id="2",
        alighting_station_id="1",
    )
    add("unknown_boarding", boarding_station_id="9999")
    add("unknown_alighting", alighting_station_id="9999")
    add("missing_scope", fare_network_scope="")
    add(
        "domestic_ids_in_airport_scope",
        fare_network_scope=AIRPORT_SCOPE,
    )
    add(
        "airport_express_known_missing_pair",
        fare_network_scope=AIRPORT_SCOPE,
        boarding_station_id="44",
        alighting_station_id="45",
    )
    add("unsupported_child", passenger_type="child")
    add("unsupported_payment", payment_medium="SingleJourneyTicket")
    add("generic_pt_mode", actual_transport_mode="pt")
    add("missing_actual_mode", actual_transport_mode="")
    add(
        "airport_same_station_without_record",
        fare_network_scope=AIRPORT_SCOPE,
        boarding_station_id="44",
        alighting_station_id="44",
    )
    add("missing_boarding", boarding_station_id="")
    add("missing_alighting", alighting_station_id="")
    add("transfer_concession_requested", transfer_concession_requested="true")
    columns = [
        "quote_id",
        "actual_transport_mode",
        "fare_network_scope",
        "boarding_station_id",
        "alighting_station_id",
        "passenger_type",
        "payment_medium",
        "travel_date",
        "transfer_concession_requested",
    ]
    return pd.DataFrame(cases, columns=columns)


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
        else model_dir / "mtr_station_od_v1"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = read_manifest(model_dir, source_root)
    domestic_source = source_meta(manifest, DOMESTIC_SOURCE_ID)
    airport_source = source_meta(manifest, AIRPORT_SOURCE_ID)
    mtr_dir = source_root / "data/transit/hongkong/MTR"
    stations, domestic_raw, airport_raw = read_official_station_tables(mtr_dir)

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
    numeric_columns = [
        "stop_count",
        "official_stop_id_coverage",
    ]
    for column in numeric_columns:
        if column in inventory:
            inventory[column] = pd.to_numeric(inventory[column], errors="raise")
    for column in [
        "scheduled_stop_count",
        "mapped_stop_count",
        "stop_id_coverage",
        "candidate_count",
        "required_forward_pair_count",
        "matched_forward_pair_count",
        "forward_pair_coverage",
    ]:
        route_crosswalk[column] = pd.to_numeric(
            route_crosswalk[column], errors="raise"
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
    schedule_routes = read_train_schedule_routes(schedule_path)
    station_crosswalk, _ = build_station_crosswalk(
        stations,
        domestic_raw,
        airport_raw,
        inventory,
        schedule_routes,
    )

    domestic_rules = raw_rule_rows(
        domestic_raw,
        DOMESTIC_SCOPE,
        domestic_source,
        "mtr_lines_fares.csv",
        "SRC_STATION_ID",
        "DEST_STATION_ID",
        "SRC_STATION_NAME",
        "DEST_STATION_NAME",
        "OCT_ADT_FARE",
    )
    airport_rules = raw_rule_rows(
        airport_raw,
        AIRPORT_SCOPE,
        airport_source,
        "airport_express_fares.csv",
        "ST_FROM_ID",
        "ST_TO_ID",
        "ST_FROM",
        "ST_TO",
        "OCT_ADT_FARE",
    )
    station_names = station_crosswalk.set_index("station_id")[
        "station_name_en"
    ].to_dict()
    train_inventory = inventory[inventory["transport_mode"].eq("train")]
    unresolved_pairs, missing_rules = build_airport_missing_pairs(
        airport_rules, train_inventory, airport_source, station_names
    )
    for frame in (domestic_rules, airport_rules, missing_rules):
        frame["adult_octopus_fare_hkd"] = pd.array(
            frame["adult_octopus_fare_hkd"], dtype="Float64"
        )
    rules = pd.concat(
        [domestic_rules, airport_rules, missing_rules], ignore_index=True
    )
    rules["_boarding_sort"] = rules["boarding_station_id"].map(
        lambda value: sort_station_id(str(value))[0]
    )
    rules["_alighting_sort"] = rules["alighting_station_id"].map(
        lambda value: sort_station_id(str(value))[0]
    )
    rules = rules.sort_values(
        [
            "fare_network_scope",
            "_boarding_sort",
            "_alighting_sort",
            "boarding_station_id",
            "alighting_station_id",
        ]
    ).drop(columns=["_boarding_sort", "_alighting_sort"])
    rules["adult_octopus_fare_hkd"] = pd.array(
        rules["adult_octopus_fare_hkd"], dtype="Float64"
    )
    if rules.duplicated(
        ["fare_network_scope", "boarding_station_id", "alighting_station_id"]
    ).any():
        raise AssertionError("Duplicate scope + ordered station-OD rule key")

    normalized_counts = crosscheck_normalized(
        rules, model_dir / "official_fares_normalized.parquet"
    )
    readiness = build_route_readiness(
        inventory, route_crosswalk, direction_patterns, rules
    )
    fixtures = fixture_input()
    fixture_output = quote_dataframe(fixtures, rules)

    station_crosswalk.to_csv(
        output_dir / "mtr_station_crosswalk.csv",
        index=False,
        encoding="utf-8",
    )
    rules.to_parquet(
        output_dir / "mtr_station_od_fare_rules.parquet", index=False
    )
    sample = pd.concat(
        [
            rules[rules["fare_network_scope"].eq(DOMESTIC_SCOPE)].head(50),
            rules[rules["fare_network_scope"].eq(AIRPORT_SCOPE)],
        ],
        ignore_index=True,
    )
    sample.to_csv(
        output_dir / "mtr_station_od_fare_rules_sample.csv",
        index=False,
        encoding="utf-8",
    )
    unresolved_pairs.to_csv(
        output_dir / "mtr_unresolved_od_pairs.csv",
        index=False,
        encoding="utf-8",
    )
    readiness.to_csv(
        output_dir / "mtr_schedule_route_fare_readiness.csv",
        index=False,
        encoding="utf-8",
    )
    fixtures.to_csv(
        output_dir / "mtr_fare_query_fixture_input.csv",
        index=False,
        encoding="utf-8",
    )
    fixture_output.to_csv(
        output_dir / "mtr_fare_query_fixture_output.csv",
        index=False,
        encoding="utf-8",
    )

    scope_summary: dict[str, dict[str, int]] = {}
    for scope, group in rules.groupby("fare_network_scope", sort=True):
        scope_summary[str(scope)] = {
            "total_records": int(len(group)),
            "available_records": int(group["record_status"].eq("available").sum()),
            "conflicting_records": int(group["record_status"].eq("ambiguous").sum()),
            "missing_records": int(group["record_status"].eq("unresolved").sum()),
            "official_zero_fare_records": int(
                group["adult_octopus_fare_hkd"].eq(0).sum()
            ),
        }
    summary = {
        "model": "Hong Kong MTR adult Octopus station-OD fare rules v1",
        "model_role": "offline_explicit_station_od_quote_rules",
        "fare_network_scopes": scope_summary,
        "raw_to_normalized_crosscheck_available_records": normalized_counts,
        "station_crosswalk": {
            str(key): int(value)
            for key, value in station_crosswalk["mapping_status"]
            .value_counts()
            .items()
        },
        "train_route_mapping_status": {
            str(key): int(value)
            for key, value in readiness["mapping_status"].value_counts().items()
        },
        "train_route_fare_readiness": {
            str(key): int(value)
            for key, value in readiness["fare_readiness"].value_counts().items()
        },
        "airport_express_missing_ordered_od_pairs": int(len(unresolved_pairs)),
        "fixture_quotes": {
            "total": int(len(fixture_output)),
            "priced": int(fixture_output["cost_hkd"].notna().sum()),
            "unresolved": int(fixture_output["cost_hkd"].isna().sum()),
        },
        "supported_passenger_type": "adult",
        "supported_payment_medium": "Octopus",
        "transfer_concessions": "not_modelled",
        "production_passenger_trip_pricing": "not_performed",
        "prohibited_inference_methods_present": False,
    }
    (output_dir / "mtr_station_od_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    readme = """# Hong Kong MTR station-OD fare rules v1

This directory contains pure offline adult Octopus rules for explicit ordered
MTR station IDs. `domestic_mtr_station_od` and
`airport_express_station_od` are separate scopes. Missing ordered pairs remain
unresolved; no reverse lookup, distance interpolation, path summation,
cross-scope fallback, or missing-value zero fill is used.

The quote interface does not read production plans. The existing 557,104
generic PT passenger-trip audit rows remain unresolved with null `cost_hkd`.
Transfer concessions are not modelled.

Every available amount is traced to an original official CSV line and source
SHA256. MTR fare effective-date evidence remains
`external_official_reference_not_locally_archived`.
"""
    (output_dir / "README.md").write_text(readme, encoding="utf-8")
    write_sha256s(output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
