#!/usr/bin/env python3
"""Independently validate Hong Kong Ferry Core v1 fare audit outputs."""

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
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import pandas as pd


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
BASE_REL = Path("data/transport_costs/hongkong/pt_fare_v1")
UNSPECIFIED = "unspecified_in_source"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def read_zip_csv(path: Path, name: str) -> list[dict[str, str]]:
    with zipfile.ZipFile(path) as archive, archive.open(name) as raw:
        reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))
        rows = []
        for line_number, row in enumerate(reader, start=2):
            row["_line_number"] = str(line_number)
            rows.append(dict(row))
        return rows


def read_schedule(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rb") as handle:
        root = ET.parse(handle).getroot()
    rows = []
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
                match = re.match(r"^ferry_(\d+)_", route.attrib["id"])
                rows.append(
                    {
                        "matsim_line_id": line.attrib["id"],
                        "matsim_route_id": route.attrib["id"],
                        "official_route_id": match.group(1) if match else "",
                        "stop_refs": refs,
                    }
                )
    return rows


def forward_pairs(stops: list[str]) -> set[tuple[str, str]]:
    return {
        (stops[i], stops[j])
        for i in range(len(stops))
        for j in range(i + 1, len(stops))
        if stops[i] and stops[j] and stops[i] != stops[j]
    }


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def text_values_have_absolute_path(output_dir: Path) -> bool:
    pattern = re.compile(r"(?<![A-Za-z])\b[A-Za-z]:[\\/]")
    for path in output_dir.iterdir():
        if path.suffix.lower() in {".csv", ".json", ".md", ".txt"}:
            if pattern.search(path.read_text(encoding="utf-8")):
                return True
        elif path.suffix.lower() == ".parquet":
            frame = pd.read_parquet(path)
            for column in frame.select_dtypes(include=["object", "string"]).columns:
                if frame[column].fillna("").astype(str).str.contains(pattern).any():
                    return True
    return False


def reproduce_fixture_status(
    request: dict[str, str], rules: pd.DataFrame, full_route_ids: set[str]
) -> tuple[str, float | None]:
    if request["actual_transport_mode"] != "ferry":
        return "unresolved", None
    for field in (
        "passenger_type",
        "payment_medium",
        "service_class",
        "vessel_service_type",
        "day_type",
    ):
        if request[field] != "unspecified":
            return "unresolved", None
    try:
        travel_date = pd.Timestamp(request["travel_date"]).date()
    except Exception:
        return "unresolved", None
    candidates = rules[
        (rules["record_status"] == "available")
        & (rules["matsim_route_id"] == request["matsim_route_id"])
        & (rules["official_route_id"] == request["official_route_id"])
    ]
    if candidates.empty or not request["official_direction"]:
        return "unresolved", None
    if (candidates["fare_scope"] == "exact_route_direction_stop_od").any():
        candidates = candidates[
            (candidates["fare_scope"] == "exact_route_direction_stop_od")
            & (candidates["official_direction"] == request["official_direction"])
        ]
    elif request["official_direction"] == "unspecified":
        candidates = candidates[
            candidates["fare_scope"] == "route_stop_od_direction_not_encoded"
        ]
    else:
        return "unresolved", None
    candidates = candidates[
        (candidates["boarding_stop_id"] == request["boarding_stop_id"])
        & (candidates["alighting_stop_id"] == request["alighting_stop_id"])
    ]
    if len(candidates) != 1:
        return ("ambiguous", None) if len(candidates) > 1 else ("unresolved", None)
    rule = candidates.iloc[0]
    if travel_date < pd.Timestamp(rule["cost_effective_date"]).date():
        return "unresolved", None
    return str(rule["mapping_status"]), float(rule["adult_base_fare_hkd"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-project-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[4]
    source_root = args.source_project_root.resolve()
    output_dir = (args.output_dir or repo_root / OUTPUT_REL).resolve()

    required_files = [
        "README.md",
        "ferry_source_schema_audit.csv",
        "ferry_fare_semantics_summary.json",
        "ferry_stop_crosswalk.csv",
        "ferry_route_direction_fare_readiness.csv",
        "ferry_fare_rules.parquet",
        "ferry_fare_rules_sample.csv",
        "ferry_fare_conflicts.csv",
        "ferry_unresolved_fare_rules.csv",
        "ferry_route_full_fare_reference.csv",
        "ferry_fare_query_fixture_input.csv",
        "ferry_fare_query_fixture_output.csv",
        "ferry_fare_summary.json",
        "ferry_fare_validation.json",
        "prior_mode_protected_hashes.csv",
        "SHA256SUMS.txt",
    ]
    missing_files = [name for name in required_files if not (output_dir / name).is_file()]

    gtfs_path = source_root / GTFS_REL
    attrs_all = read_zip_csv(gtfs_path, "fare_attributes.txt")
    rules_all = read_zip_csv(gtfs_path, "fare_rules.txt")
    stops_all = read_zip_csv(gtfs_path, "stops.txt")
    ferry_attrs = [row for row in attrs_all if row["agency_id"] == "FERRY"]
    attr_by_id = {row["fare_id"]: row for row in ferry_attrs}
    fare_ids = set(attr_by_id)
    ferry_rules = [row for row in rules_all if row["fare_id"] in fare_ids]
    rule_lookup: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in ferry_rules:
        rule_lookup[(row["route_id"], row["origin_id"], row["destination_id"])].append(
            row
        )
    ruled_fare_ids = {row["fare_id"] for row in ferry_rules}
    orphan_ids = fare_ids - ruled_fare_ids

    raw_json = json.loads((source_root / JSON_REL).read_text(encoding="utf-8-sig"))
    json_props = [feature["properties"] for feature in raw_json["features"]]
    json_patterns: dict[tuple[str, str], list[str]] = {}
    json_groups: dict[tuple[str, str], list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for index, props in enumerate(json_props):
        json_groups[(str(props["routeId"]), str(props["routeSeq"]))].append(
            (index, props)
        )
    for key, group in json_groups.items():
        json_patterns[key] = [
            str(props["stopId"])
            for _, props in sorted(group, key=lambda item: int(item[1]["stopSeq"]))
        ]

    facilities_path = source_root / SUPPLY_REL / "ferry_stop_facilities.csv"
    facilities = list(
        csv.DictReader(facilities_path.open(encoding="utf-8-sig", newline=""))
    )
    facility_by_id = {row["facility_id"]: row for row in facilities}
    schedule = read_schedule(source_root / SUPPLY_REL / "transitSchedule_5pct.xml.gz")
    independently_expected = {}
    total_pairs = 0
    total_matched = 0
    exact_count = 0
    partial_count = 0
    for route in schedule:
        stops = [facility_by_id.get(ref, {}).get("stop_id", "") for ref in route["stop_refs"]]
        candidates = [
            key
            for key, pattern in json_patterns.items()
            if key[0] == route["official_route_id"] and pattern == stops
        ]
        pairs = forward_pairs(stops)
        matched = {
            pair
            for pair in pairs
            if (route["official_route_id"], pair[0], pair[1]) in rule_lookup
        }
        exact = len(candidates) == 1 and len(matched) == len(pairs) and all(stops)
        exact_count += int(exact)
        partial_count += int(not exact and len(matched) == len(pairs))
        total_pairs += len(pairs)
        total_matched += len(matched)
        independently_expected[route["matsim_route_id"]] = {
            "route_id": route["official_route_id"],
            "stops": stops,
            "direction": candidates[0][1] if exact else "",
            "pairs": pairs,
            "matched": matched,
            "mapping_status": "exact" if exact else "partial",
            "quality": "A" if exact else "C",
        }

    crosswalk = pd.read_csv(
        output_dir / "ferry_stop_crosswalk.csv", dtype=str, keep_default_na=False
    )
    readiness = pd.read_csv(
        output_dir / "ferry_route_direction_fare_readiness.csv",
        dtype=str,
        keep_default_na=False,
    )
    rules = pd.read_parquet(output_dir / "ferry_fare_rules.parquet")
    rules = rules.where(pd.notna(rules), "")
    for column in rules.columns:
        if column != "adult_base_fare_hkd":
            rules[column] = rules[column].astype(str)
    unresolved = pd.read_csv(
        output_dir / "ferry_unresolved_fare_rules.csv",
        dtype=str,
        keep_default_na=False,
    )
    conflicts = pd.read_csv(
        output_dir / "ferry_fare_conflicts.csv", dtype=str, keep_default_na=False
    )
    full_refs = pd.read_csv(
        output_dir / "ferry_route_full_fare_reference.csv",
        dtype=str,
        keep_default_na=False,
    )
    schema = pd.read_csv(
        output_dir / "ferry_source_schema_audit.csv",
        dtype=str,
        keep_default_na=False,
    )
    summary = json.loads(
        (output_dir / "ferry_fare_summary.json").read_text(encoding="utf-8")
    )
    semantics = json.loads(
        (output_dir / "ferry_fare_semantics_summary.json").read_text(encoding="utf-8")
    )

    # 1: exact current schedule route universe.
    check_1 = (
        len(schedule) == 39
        and len(readiness) == 39
        and readiness["matsim_route_id"].nunique() == 39
        and set(readiness["matsim_route_id"]) == set(independently_expected)
    )

    # 2: crosswalk is the direct facility table mapping and never fuzzy/nearest.
    gtfs_stop_ids = {row["stop_id"] for row in stops_all}
    json_stop_ids = {str(row["stopId"]) for row in json_props}
    crosswalk_lookup = crosswalk.set_index("matsim_stop_facility_id").to_dict("index")
    check_2 = len(crosswalk) == len(facilities) == 87
    for raw in facilities:
        out = crosswalk_lookup.get(raw["facility_id"], {})
        check_2 &= (
            out.get("official_stop_id") == raw["stop_id"]
            and out.get("candidate_count") == "1"
            and out.get("matching_method") == "explicit_ferry_stop_facilities_stop_id"
            and (out.get("in_gtfs") == "True") == (raw["stop_id"] in gtfs_stop_ids)
            and (out.get("in_ferry_json") == "True") == (raw["stop_id"] in json_stop_ids)
        )

    # 3-5: direction pattern, 34/5 evidence, and 60 direct forward pairs.
    readiness_lookup = readiness.set_index("matsim_route_id").to_dict("index")
    check_3 = True
    for route_id, expected in independently_expected.items():
        out = readiness_lookup[route_id]
        check_3 &= (
            out["official_route_id"] == expected["route_id"]
            and out["official_direction"] == expected["direction"]
            and int(out["scheduled_stop_count"]) == len(expected["stops"])
            and int(out["required_forward_pair_count"]) == len(expected["pairs"])
            and int(out["matched_fare_pair_count"]) == len(expected["matched"])
        )
    check_4 = (
        exact_count == 34
        and partial_count == 5
        and Counter(readiness["mapping_status"]) == {"exact": 34, "partial": 5}
        and Counter(readiness["mapping_quality"]) == {"A": 34, "C": 5}
        and all(
            readiness_lookup[key]["mapping_status"] == value["mapping_status"]
            and readiness_lookup[key]["mapping_quality"] == value["quality"]
            for key, value in independently_expected.items()
        )
    )
    check_5 = total_pairs == total_matched == 60 and int(
        readiness["required_forward_pair_count"].astype(int).sum()
    ) == int(readiness["matched_fare_pair_count"].astype(int).sum()) == 60

    # 6-10: raw-record trace, exact OD orientation, prohibited fallbacks/zero/conflict.
    trace_ok = True
    orientation_ok = True
    for row in rules.to_dict("records"):
        candidates = rule_lookup[
            (
                str(row["official_route_id"]),
                str(row["boarding_stop_id"]),
                str(row["alighting_stop_id"]),
            )
        ]
        orientation_ok &= len(candidates) == 1
        match = re.fullmatch(
            r"gtfs:fare_rules\.txt:(\d+)\|fare_attributes\.txt:(\d+)\|fare_id:(.+)",
            str(row["source_record_id"]),
        )
        if not match or len(candidates) != 1:
            trace_ok = False
            continue
        raw_rule = candidates[0]
        raw_attr = attr_by_id[raw_rule["fare_id"]]
        trace_ok &= (
            match.group(1) == raw_rule["_line_number"]
            and match.group(2) == raw_attr["_line_number"]
            and match.group(3) == raw_rule["fare_id"]
            and float(row["adult_base_fare_hkd"]) == float(raw_attr["price"])
            and row["source_sha256"] == sha256(gtfs_path)
            and row["source_file"] == GTFS_REL.as_posix()
        )
    full_trace_ok = True
    for row in full_refs.to_dict("records"):
        match = re.fullmatch(r"json:feature_indices:([0-9;]+)", row["source_record_id"])
        if not match:
            full_trace_ok = False
            continue
        indices = [int(value) for value in match.group(1).split(";")]
        values = {float(json_props[index]["fullFare"]) for index in indices}
        full_trace_ok &= (
            len(values) == 1
            and float(row["full_fare_hkd"]) == next(iter(values))
            and row["source_sha256"] == sha256(source_root / JSON_REL)
        )
    unresolved_trace_ok = (
        len(unresolved) == len(orphan_ids) == 27
        and set(
            re.search(r"fare_id:(.+)$", value).group(1)
            for value in unresolved["source_record_id"]
        )
        == orphan_ids
    )
    check_6 = trace_ok and full_trace_ok and unresolved_trace_ok
    check_7 = orientation_ok
    methods = ";".join(rules["matching_method"].astype(str)).lower()
    check_8 = all(
        token not in methods
        for token in ("reverse_substitution", "distance", "path_sum", "full_fare_fallback")
    ) and not (rules["fare_scope"] == "route_level_full_fare_reference_only").any()
    raw_zero_count = sum(
        float(attr_by_id[row["fare_id"]]["price"]) == 0 for row in ferry_rules
    )
    check_9 = raw_zero_count == 0 and not (
        (pd.to_numeric(rules["adult_base_fare_hkd"], errors="coerce") == 0)
    ).any()
    raw_conflicts = sum(
        len({attr_by_id[row["fare_id"]]["price"] for row in candidates}) > 1
        for candidates in rule_lookup.values()
    )
    check_10 = raw_conflicts == 0 and conflicts.empty

    # 11-12: source-unspecified dimensions and fullFare boundary.
    condition_columns = [
        "passenger_type",
        "payment_medium",
        "service_class",
        "vessel_service_type",
        "day_type",
        "time_period",
    ]
    check_11 = all((rules[column] == UNSPECIFIED).all() for column in condition_columns)
    answers = semantics["answers"]
    check_11 &= all(
        answers[key]["answer"] == UNSPECIFIED
        for key in (
            "price_is_explicit_adult_fare",
            "payment_medium",
            "ordinary_or_high_speed_vessel",
            "deck_seat_or_cabin_class",
            "weekday_weekend_public_holiday",
        )
    )
    check_12 = (
        len(full_refs) == 102
        and (full_refs["eligible_for_default_quote"] == "False").all()
        and summary["full_fare_reference_in_available_rules"] is False
    )

    # 13: independently reproduce availability and amount of every fixture row.
    fixture_in = pd.read_csv(
        output_dir / "ferry_fare_query_fixture_input.csv",
        dtype=str,
        keep_default_na=False,
    )
    fixture_out = pd.read_csv(
        output_dir / "ferry_fare_query_fixture_output.csv",
        dtype=str,
        keep_default_na=False,
    )
    fixture_out_lookup = fixture_out.set_index("quote_id").to_dict("index")
    fixture_ok = len(fixture_in) == len(fixture_out) == 19
    fixture_available = 0
    for request in fixture_in.to_dict("records"):
        status, amount = reproduce_fixture_status(
            request, rules, set(full_refs["official_route_id"])
        )
        out = fixture_out_lookup.get(request["quote_id"], {})
        expected_available = request["expected_result"] == "available"
        actual_available = out.get("cost_hkd", "") != ""
        fixture_ok &= expected_available == actual_available
        fixture_ok &= (status in {"exact", "partial"}) == actual_available
        if actual_available:
            fixture_available += 1
            fixture_ok &= float(out["cost_hkd"]) == amount
        else:
            fixture_ok &= out.get("cost_hkd", "") == "" and bool(
                out.get("unresolved_reason", "")
            )
    check_13 = fixture_ok

    # 14-16: effective date, provenance, and transfers.
    revision_rows = list(
        csv.reader(
            (source_root / REVISION_REL).open(encoding="utf-8-sig", newline="")
        )
    )
    raw_effective = revision_rows[1][0].strip()
    check_14 = (
        raw_effective == "2026-07-14"
        and summary["effective_date"] == raw_effective
        and (rules["cost_effective_date"] == raw_effective).all()
    )
    check_15 = (
        (rules["source_sha256"].str.fullmatch(r"[0-9a-f]{64}")).all()
        and (full_refs["source_sha256"].str.fullmatch(r"[0-9a-f]{64}")).all()
        and trace_ok
        and full_trace_ok
    )
    check_16 = (
        (fixture_out["transfer_concession_hkd"] == "").all()
        and (fixture_out["transfer_concession_status"] == "not_modelled").all()
        and summary["transfer_concession_status"] == "not_modelled"
    )

    # 17-18 and 20: hash protected prior-mode directories and eight MATSim inputs.
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
    protected_frame = pd.DataFrame(protected_results)
    check_17 = protected_frame[
        protected_frame["protected_scope"] == "mtr_station_od_v1"
    ]["unchanged"].all()
    check_18 = protected_frame[
        protected_frame["protected_scope"] == "light_rail_station_od_v1"
    ]["unchanged"].all()
    protected_matsim = protected_frame[
        protected_frame["protected_scope"] == "matsim_protected_input"
    ]
    check_20 = len(protected_matsim) == 8 and protected_matsim["unchanged"].all()

    # 19: production passenger audit is still entirely unresolved/null.
    production = pd.read_parquet(
        repo_root / BASE_REL / "pt_passenger_trip_fare_audit.parquet",
        columns=["cost_hkd", "mapping_status", "cost_quality"],
    )
    check_19 = (
        len(production) == 557_104
        and production["cost_hkd"].isna().all()
        and (production["mapping_status"] == "unresolved").all()
        and (production["cost_quality"] == "U").all()
    )

    # 21-23: portable formats, complete schemas/hashes, deterministic order.
    check_21 = not text_values_have_absolute_path(output_dir)
    expected_schema_fields = {
        "source_id",
        "source_file",
        "table_or_object",
        "field_name",
        "semantic_interpretation",
        "semantic_evidence",
        "machine_usable",
        "required_for_pricing",
        "ambiguity_status",
        "unresolved_reason",
    }
    check_22 = (
        not missing_files
        and expected_schema_fields.issubset(schema.columns)
        and len(rules) == 60
        and len(readiness) == 39
        and len(full_refs) == 102
        and all(
            re.fullmatch(r"[0-9a-f]{64}", value)
            for value in list(rules["source_sha256"]) + list(full_refs["source_sha256"])
        )
    )
    sorted_rule_keys = list(
        rules[
            ["matsim_route_id", "boarding_stop_id", "alighting_stop_id"]
        ].itertuples(index=False, name=None)
    )
    sorted_route_ids = list(readiness["matsim_route_id"])
    check_23 = (
        sorted_rule_keys == sorted(sorted_rule_keys)
        and sorted_route_ids == sorted(sorted_route_ids)
        and compact_json(summary) == compact_json(json.loads(compact_json(summary)))
        and compact_json(semantics) == compact_json(json.loads(compact_json(semantics)))
    )

    checks = [
        ("01_schedule_39_routes_complete_unique", check_1),
        ("02_stop_crosswalk_cardinality_and_explicit_evidence", check_2),
        ("03_route_routeSeq_stopSeq_direction_patterns", check_3),
        ("04_exact_34_partial_5_evidence", check_4),
        ("05_raw_forward_pairs_60", check_5),
        ("06_non_null_amounts_trace_to_raw_records", check_6),
        ("07_no_reverse_od_substitution", check_7),
        ("08_no_interpolation_path_sum_or_fullfare_fallback", check_8),
        ("09_no_missing_fare_zero_fill", check_9),
        ("10_conflicts_not_silently_selected", check_10),
        ("11_source_unspecified_conditions_not_invented", check_11),
        ("12_fullfare_reference_not_default_rule", check_12),
        ("13_fixture_independently_reproduced", check_13),
        ("14_td_effective_date_locally_parsed", check_14),
        ("15_source_file_sha_and_record_trace_valid", check_15),
        ("16_transfer_concessions_not_modelled", check_16),
        ("17_mtr_station_od_directory_unchanged", bool(check_17)),
        ("18_light_rail_station_od_directory_unchanged", bool(check_18)),
        ("19_production_557104_all_unresolved", check_19),
        ("20_eight_protected_matsim_inputs_unchanged", bool(check_20)),
        ("21_no_absolute_local_paths_in_outputs", check_21),
        ("22_json_csv_parquet_sha_schemas_valid", check_22),
        ("23_deterministic_order_and_serialization_contract", check_23),
    ]
    status = "passed" if all(value for _, value in checks) else "failed"
    validation = {
        "schema_version": "hong_kong_ferry_fare_validation_v1",
        "status": status,
        "checks": [
            {"check_number": index, "name": name, "passed": bool(value)}
            for index, (name, value) in enumerate(checks, start=1)
        ],
        "independent_raw_counts": {
            "gtfs_ferry_fare_attributes": len(ferry_attrs),
            "gtfs_ferry_fare_rules": len(ferry_rules),
            "gtfs_orphan_fare_attributes": len(orphan_ids),
            "json_features": len(json_props),
            "json_route_directions": len(json_patterns),
            "schedule_ferry_routes": len(schedule),
            "exact_routes": exact_count,
            "partial_routes": partial_count,
            "required_forward_pairs": total_pairs,
            "matched_forward_pairs": total_matched,
            "raw_conflicts": raw_conflicts,
            "raw_zero_fares": raw_zero_count,
            "fixture_rows": len(fixture_in),
            "fixture_available_rows": fixture_available,
        },
        "protected_hash_results": protected_results,
        "missing_required_files": missing_files,
    }
    validation_path = output_dir / "ferry_fare_validation.json"
    validation_path.write_text(
        json.dumps(validation, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    checksum_paths = sorted(
        path
        for path in output_dir.iterdir()
        if path.is_file() and path.name != "SHA256SUMS.txt"
    )
    checksum_text = "".join(
        f"{sha256(path)}  {path.name}\n" for path in checksum_paths
    )
    checksum_path = output_dir / "SHA256SUMS.txt"
    checksum_path.write_text(checksum_text, encoding="utf-8")
    manifest_valid = all(
        sha256(output_dir / name) == expected
        for expected, name in (
            line.split("  ", 1) for line in checksum_text.splitlines()
        )
    )
    print(f"Ferry fare validation {status}: {sum(value for _, value in checks)}/23")
    if status != "passed" or not manifest_valid:
        failed = [name for name, value in checks if not value]
        if not manifest_valid:
            failed.append("post_write_sha256_manifest")
        raise SystemExit("Failed checks: " + ", ".join(failed))


if __name__ == "__main__":
    main()
