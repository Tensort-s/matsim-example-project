#!/usr/bin/env python3
"""Independently validate Hong Kong GMB Core v1 fare audit outputs."""

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
UNSPECIFIED = "unspecified_in_source"
REVISION_STATUS = "not_encoded_in_source_revision_cutoff_only"
COST_APPLICABILITY = (
    "published_amount_only_passenger_payment_and_effective_period_unspecified"
)


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


def stop_id(facility_id: str) -> str:
    match = re.match(r"^pt_gmb_(\d+)_", facility_id)
    return match.group(1) if match else ""


def route_parts(route_id: str) -> tuple[str, str]:
    match = re.match(r"^gmb_(\d+)_([^_]+)", route_id)
    return (match.group(1), match.group(2)) if match else ("", "")


def read_zip_csv(path: Path, name: str) -> list[dict[str, str]]:
    with zipfile.ZipFile(path) as archive, archive.open(name) as raw:
        reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))
        rows = []
        for line_number, row in enumerate(reader, 2):
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
            departures = 0
            for child in route:
                tag = local_name(child.tag)
                if tag == "transportMode":
                    mode = (child.text or "").strip()
                elif tag == "routeProfile":
                    refs = [
                        item.attrib["refId"]
                        for item in child
                        if local_name(item.tag) == "stop"
                    ]
                elif tag == "departures":
                    departures = sum(local_name(item.tag) == "departure" for item in child)
            if mode == "gmb":
                official, suffix = route_parts(route.attrib["id"])
                rows.append(
                    {
                        "matsim_line_id": line.attrib["id"],
                        "matsim_route_id": route.attrib["id"],
                        "official_route_id": official,
                        "suffix": suffix,
                        "refs": refs,
                        "stops": [stop_id(ref) for ref in refs],
                        "departures": departures,
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


def has_absolute_path(output_dir: Path) -> bool:
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


def independently_quote(request: dict[str, str], rules: pd.DataFrame) -> tuple[str, float | None]:
    if request["actual_transport_mode"] != "gmb":
        return "unresolved", None
    if any(request[field] != "unspecified" for field in ("passenger_type", "payment_medium", "day_type")):
        return "unresolved", None
    if request["temporal_basis"] != "source_snapshot_only" or request["travel_date"]:
        return "unresolved", None
    candidates = rules[
        (rules["matsim_line_id"] == request["matsim_line_id"])
        & (rules["matsim_route_id"] == request["matsim_route_id"])
        & (rules["official_route_id"] == request["official_route_id"])
        & (rules["official_direction"] == request["official_direction"])
        & (rules["boarding_stop_id"] == request["boarding_stop_id"])
        & (rules["alighting_stop_id"] == request["alighting_stop_id"])
    ]
    if len(candidates) != 1:
        return "unresolved", None
    rule = candidates.iloc[0]
    if rule["record_status"] == "available":
        return "available", float(rule["published_fare_hkd"])
    return str(rule["record_status"]), None


def rebuild_matches_current(
    repo_root: Path, source_root: Path, output_dir: Path
) -> tuple[bool, str, str]:
    builder = repo_root / "scripts/hong_kong_single_city/costs/pt/build_hong_kong_gmb_fares.py"
    quote = repo_root / "scripts/hong_kong_single_city/costs/pt/quote_hong_kong_gmb_fares.py"
    current = {
        path.name: sha256(path)
        for path in sorted(output_dir.iterdir(), key=lambda item: item.name)
        if path.is_file()
    }
    with tempfile.TemporaryDirectory(prefix="hk_gmb_rebuild_") as temp:
        rebuilt = Path(temp) / "gmb_fare_v1"
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
                str(quote),
                "--input",
                str(rebuilt / "gmb_fare_query_fixture_input.csv"),
                "--output",
                str(rebuilt / "gmb_fare_query_fixture_output.csv"),
                "--rules",
                str(rebuilt / "gmb_fare_rules.parquet"),
                "--full-fare-reference",
                str(rebuilt / "gmb_route_full_fare_reference.csv"),
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
        "gmb_source_schema_audit.csv",
        "gmb_fare_semantics_summary.json",
        "gmb_stop_crosswalk.csv",
        "gmb_direction_evidence_audit.csv",
        "gmb_route_direction_fare_readiness.csv",
        "gmb_fare_rules.parquet",
        "gmb_fare_rules_sample.csv",
        "gmb_fare_conflicts.csv",
        "gmb_unresolved_fare_rules.csv",
        "gmb_route_full_fare_reference.csv",
        "gmb_fare_query_fixture_input.csv",
        "gmb_fare_query_fixture_output.csv",
        "gmb_fare_summary.json",
        "gmb_fare_validation.json",
        "prior_mode_protected_hashes.csv",
        "SHA256SUMS.txt",
    }
    missing_files = sorted(expected_files - {path.name for path in output_dir.iterdir() if path.is_file()})

    gtfs_path = source_root / GTFS_REL
    attrs_all = read_zip_csv(gtfs_path, "fare_attributes.txt")
    fare_rules_all = read_zip_csv(gtfs_path, "fare_rules.txt")
    stops_all = read_zip_csv(gtfs_path, "stops.txt")
    attrs = [row for row in attrs_all if row["agency_id"] == "GMB"]
    attr_by_id = {row["fare_id"]: row for row in attrs}
    raw_rules = [row for row in fare_rules_all if row["fare_id"] in attr_by_id]
    raw_lookup: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in raw_rules:
        attr = attr_by_id[row["fare_id"]]
        raw_lookup[(row["route_id"], row["origin_id"], row["destination_id"])].append(
            {
                "fare_id": row["fare_id"],
                "price": float(attr["price"]),
                "fare_rule_line": int(row["_line_number"]),
                "fare_attribute_line": int(attr["_line_number"]),
            }
        )

    raw_json = json.loads((source_root / JSON_REL).read_text(encoding="utf-8-sig"))
    props = [feature["properties"] for feature in raw_json["features"]]
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
    gtfs_stop_ids = {row["stop_id"] for row in stops_all}
    schedule = read_schedule(source_root / SUPPLY_REL / "transitSchedule_5pct.xml.gz")

    rules = pd.read_parquet(output_dir / "gmb_fare_rules.parquet").fillna("")
    for column in rules.columns:
        if column != "published_fare_hkd":
            rules[column] = rules[column].astype(str)
    readiness = pd.read_csv(
        output_dir / "gmb_route_direction_fare_readiness.csv",
        dtype=str,
        keep_default_na=False,
    )
    direction = pd.read_csv(
        output_dir / "gmb_direction_evidence_audit.csv",
        dtype=str,
        keep_default_na=False,
    )
    crosswalk = pd.read_csv(
        output_dir / "gmb_stop_crosswalk.csv", dtype=str, keep_default_na=False
    )
    conflicts = pd.read_csv(
        output_dir / "gmb_fare_conflicts.csv", dtype=str, keep_default_na=False
    )
    unresolved = pd.read_csv(
        output_dir / "gmb_unresolved_fare_rules.csv",
        dtype=str,
        keep_default_na=False,
    )
    full_refs = pd.read_csv(
        output_dir / "gmb_route_full_fare_reference.csv",
        dtype=str,
        keep_default_na=False,
    )
    schema = pd.read_csv(
        output_dir / "gmb_source_schema_audit.csv", dtype=str, keep_default_na=False
    )
    summary = json.loads((output_dir / "gmb_fare_summary.json").read_text(encoding="utf-8"))
    semantics = json.loads(
        (output_dir / "gmb_fare_semantics_summary.json").read_text(encoding="utf-8")
    )
    expected_full_fare_comparisons = {
        "comparable_gtfs_candidate_record_count": 0,
        "gtfs_price_equal_full_fare_count": 0,
        "gtfs_price_different_full_fare_count": 0,
    }
    for key, pattern in patterns.items():
        full_fares = {float(item["fullFare"]) for _, item in json_groups[key]}
        full_fare = next(iter(full_fares)) if len(full_fares) == 1 else None
        ordered_pairs = {
            (pattern[boarding_index], pattern[alighting_index])
            for boarding_index in range(len(pattern))
            for alighting_index in range(boarding_index + 1, len(pattern))
            if pattern[boarding_index]
            and pattern[alighting_index]
            and pattern[boarding_index] != pattern[alighting_index]
        }
        for boarding_stop, alighting_stop in ordered_pairs:
            candidates = raw_lookup.get(
                (key[0], boarding_stop, alighting_stop), []
            )
            for candidate in candidates:
                expected_full_fare_comparisons[
                    "comparable_gtfs_candidate_record_count"
                ] += 1
                comparison_key = (
                    "gtfs_price_equal_full_fare_count"
                    if candidate["price"] == full_fare
                    else "gtfs_price_different_full_fare_count"
                )
                expected_full_fare_comparisons[comparison_key] += 1

    route_expected: dict[str, dict[str, Any]] = {}
    required_count = matched_count = 0
    raw_status_counts: Counter[str] = Counter()
    for route in schedule:
        candidates = [
            key
            for key, pattern in patterns.items()
            if key[0] == route["official_route_id"] and pattern == route["stops"]
        ]
        pairs = forward_pairs(route["stops"])
        required_count += len(pairs)
        matched_count += sum(
            bool(raw_lookup.get((route["official_route_id"], a, b))) for a, b in pairs
        )
        statuses = {}
        for boarding, alighting in pairs:
            candidates_raw = raw_lookup.get(
                (route["official_route_id"], boarding, alighting), []
            )
            amounts = {item["price"] for item in candidates_raw}
            status = (
                "available"
                if len(candidates_raw) == 1
                else "unresolved_duplicate_identical"
                if len(candidates_raw) > 1 and len(amounts) == 1
                else "ambiguous"
                if len(amounts) > 1
                else "unresolved"
            )
            raw_status_counts[status] += 1
            statuses[(boarding, alighting)] = status
        route_expected[route["matsim_route_id"]] = {
            "candidate": candidates,
            "pairs": pairs,
            "statuses": statuses,
        }

    # 1-5: schedule inventory, one-row readiness, explicit stop mapping, no fuzzy, pairs.
    check_1 = (
        summary["schedule"]["line_count"] == len({row["matsim_line_id"] for row in schedule})
        and summary["schedule"]["route_count"] == len(schedule)
        and summary["schedule"]["departure_count"] == sum(row["departures"] for row in schedule)
        and summary["schedule"]["stop_occurrence_count"] == sum(len(row["refs"]) for row in schedule)
    )
    check_2 = (
        len(readiness) == len(schedule)
        and readiness["matsim_route_id"].nunique() == len(schedule)
        and set(readiness["matsim_route_id"]) == set(route_expected)
    )
    crosswalk_lookup = crosswalk.set_index("matsim_stop_facility_id").to_dict("index")
    facility_ids = {ref for route in schedule for ref in route["refs"]}
    check_3 = len(crosswalk) == len(facility_ids)
    for facility_id in facility_ids:
        official = stop_id(facility_id)
        output = crosswalk_lookup.get(facility_id, {})
        check_3 &= (
            output.get("official_stop_id") == official
            and output.get("candidate_count") == "1"
            and (output.get("in_gtfs") == "True") == (official in gtfs_stop_ids)
            and (output.get("in_gmb_json") == "True") == (official in json_stop_ids)
        )
    check_4 = (
        crosswalk["matching_method"]
        == "official_stop_id_encoded_in_matsim_facility_id"
    ).all() and not crosswalk["matching_method"].str.contains(
        "fuzzy|nearest|coordinate", case=False, regex=True
    ).any()
    check_5 = (
        required_count == int(readiness["required_forward_pair_count"].astype(int).sum())
        and matched_count == int(readiness["matched_fare_pair_count"].astype(int).sum())
        and len(rules) == required_count
    )

    # 6-7: raw amount trace and true candidate/conflict handling.
    trace_ok = True
    status_ok = Counter(rules["record_status"]) == raw_status_counts
    for row in rules.to_dict("records"):
        raw = raw_lookup.get(
            (row["official_route_id"], row["boarding_stop_id"], row["alighting_stop_id"]),
            [],
        )
        amounts = {item["price"] for item in raw}
        expected_status = (
            "available"
            if len(raw) == 1
            else "unresolved_duplicate_identical"
            if len(raw) > 1 and len(amounts) == 1
            else "ambiguous"
            if len(amounts) > 1
            else "unresolved"
        )
        status_ok &= (
            row["record_status"] == expected_status
            and int(row["candidate_count"]) == len(raw)
            and int(row["distinct_amount_count"]) == len(amounts)
        )
        if expected_status == "available":
            match = re.fullmatch(
                r"gtfs:fare_rules\.txt:(\d+)\|fare_attributes\.txt:(\d+)\|fare_id:(.+)",
                row["source_record_id"],
            )
            trace_ok &= bool(match) and float(row["published_fare_hkd"]) == raw[0]["price"]
            if match:
                trace_ok &= (
                    int(match.group(1)) == raw[0]["fare_rule_line"]
                    and int(match.group(2)) == raw[0]["fare_attribute_line"]
                    and match.group(3) == raw[0]["fare_id"]
                )
        else:
            trace_ok &= row["published_fare_hkd"] in ("", None)
    check_6 = trace_ok and "adult_base_fare_hkd" not in rules.columns and "adult_octopus_fare_hkd" not in rules.columns
    check_7 = (
        status_ok
        and len(conflicts) == raw_status_counts["ambiguous"]
        and len(unresolved)
        == raw_status_counts["unresolved"]
        + raw_status_counts["unresolved_duplicate_identical"]
    )

    # 8-12: direct orientation/fallback boundaries and direction proof.
    check_8 = all(
        raw_lookup.get((row["official_route_id"], row["boarding_stop_id"], row["alighting_stop_id"]))
        for row in rules.to_dict("records")
    )
    methods = ";".join(rules["matching_method"]).lower()
    check_9 = all(
        token not in methods
        for token in ("distance", "nearest", "path_sum", "adjacent_sum", "interpolation")
    )
    check_10 = (
        len(full_refs) == len(patterns)
        and (full_refs["eligible_for_default_quote"] == "False").all()
        and not (rules["fare_scope"] == "route_level_full_fare_reference_only").any()
        and summary["full_fare_comparison_counts"]
        == expected_full_fare_comparisons
        and int(full_refs["gtfs_candidate_record_count"].astype(int).sum())
        == expected_full_fare_comparisons["comparable_gtfs_candidate_record_count"]
        and int(full_refs["gtfs_price_equal_full_fare_count"].astype(int).sum())
        == expected_full_fare_comparisons["gtfs_price_equal_full_fare_count"]
        and int(full_refs["gtfs_price_different_full_fare_count"].astype(int).sum())
        == expected_full_fare_comparisons["gtfs_price_different_full_fare_count"]
    )
    raw_zero_keys = {
        (row["route_id"], row["origin_id"], row["destination_id"])
        for row in raw_rules
        if float(attr_by_id[row["fare_id"]]["price"]) == 0
    }
    output_zero = rules[pd.to_numeric(rules["published_fare_hkd"], errors="coerce") == 0]
    check_11 = all(
        (row["official_route_id"], row["boarding_stop_id"], row["alighting_stop_id"])
        in raw_zero_keys
        for row in output_zero.to_dict("records")
    )
    direction_lookup = direction.set_index("matsim_route_id").to_dict("index")
    check_12 = len(direction) == len(schedule)
    for route in schedule:
        expected = route_expected[route["matsim_route_id"]]
        output = direction_lookup[route["matsim_route_id"]]
        check_12 &= (
            len(expected["candidate"]) == 1
            and output["official_json_route_sequence"] == expected["candidate"][0][1]
            and output["complete_stop_sequence_exact"] == "True"
            and output["route_suffix_used_as_evidence"] == "False"
            and output["current_mapping_quality"] == "A"
        )

    # 13-17: semantics, quality split, time, fixture, transfers.
    check_13 = all(
        (rules[column] == UNSPECIFIED).all()
        for column in ("passenger_type", "payment_medium", "service_class", "day_type", "time_period")
    ) and all(
        semantics["answers"][key] == UNSPECIFIED
        for key in (
            "price_passenger_type",
            "price_payment_medium",
            "price_ticket_or_sectional_scope",
        )
    )
    available = rules["record_status"] == "available"
    unavailable = ~available
    check_14 = (
        (rules.loc[available, "mapping_quality"] == "A").all()
        and (rules.loc[available, "cost_quality"] == "B").all()
        and (rules.loc[unavailable, "cost_quality"] == "U").all()
        and not (rules["cost_quality"] == "A").any()
        and (rules.loc[available, "cost_applicability_status"] == COST_APPLICABILITY).all()
    )
    revision_rows = list(
        csv.reader((source_root / REVISION_REL).open(encoding="utf-8-sig", newline=""))
    )
    revision = revision_rows[1][0].strip()
    check_15 = (
        revision == "2026-07-14"
        and (rules["cost_effective_date"] == "").all()
        and (rules["cost_effective_date_status"] == REVISION_STATUS).all()
        and (rules["source_revision_cutoff_date"] == revision).all()
        and (rules["source_download_date"] == "2026-07-20").all()
    )
    fixture_in = pd.read_csv(
        output_dir / "gmb_fare_query_fixture_input.csv", dtype=str, keep_default_na=False
    )
    fixture_out = pd.read_csv(
        output_dir / "gmb_fare_query_fixture_output.csv", dtype=str, keep_default_na=False
    )
    fixture_lookup = fixture_out.set_index("quote_id").to_dict("index")
    fixture_ok = len(fixture_in) == len(fixture_out)
    fixture_available = 0
    for request in fixture_in.to_dict("records"):
        status, amount = independently_quote(request, rules)
        output = fixture_lookup.get(request["quote_id"], {})
        expected = request["expected_result"]
        actual_available = output.get("cost_hkd", "") != ""
        fixture_ok &= actual_available == (expected == "available")
        if expected == "ambiguous":
            fixture_ok &= output.get("mapping_status") == "ambiguous"
        if actual_available:
            fixture_available += 1
            fixture_ok &= (
                status == "available"
                and float(output["cost_hkd"]) == amount
                and float(output["published_fare_hkd"]) == amount
                and output["cost_quality"] == "B"
                and output["cost_effective_date"] == ""
            )
        else:
            fixture_ok &= output.get("cost_quality") == "U" and bool(output.get("unresolved_reason"))
    check_16 = fixture_ok
    check_17 = (
        (fixture_out["transfer_concession_hkd"] == "").all()
        and (fixture_out["transfer_concession_status"] == "not_modelled").all()
        and fixture_lookup["transfer_concession_requested"]["cost_hkd"] != ""
    )

    # 18-20: production audit and protected hashes.
    production = pd.read_parquet(
        repo_root / BASE_REL / "pt_passenger_trip_fare_audit.parquet",
        columns=["cost_hkd", "mapping_status", "cost_quality"],
    )
    check_18 = (
        len(production) == 557_104
        and production["cost_hkd"].isna().all()
        and (production["mapping_status"] == "unresolved").all()
        and (production["cost_quality"] == "U").all()
    )
    prior = pd.read_csv(
        output_dir / "prior_mode_protected_hashes.csv", dtype=str, keep_default_na=False
    )
    protected_results = []
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
    check_19 = all(
        len(protected[protected["protected_scope"] == scope]) > 0
        and protected[protected["protected_scope"] == scope]["unchanged"].all()
        for scope in ("mtr_station_od_v1", "light_rail_station_od_v1", "ferry_fare_v1")
    )
    matsim = protected[protected["protected_scope"] == "matsim_protected_input"]
    check_20 = len(matsim) == 8 and matsim["unchanged"].all()

    # 21-23: portability, schemas, independent rebuild.
    check_21 = not has_absolute_path(output_dir)
    check_22 = (
        not missing_files
        and len(rules) == required_count
        and len(readiness) == len(schedule)
        and len(full_refs) == len(patterns)
        and {"published_fare_hkd", "cost_quality", "mapping_quality"}.issubset(rules.columns)
        and "adult_base_fare_hkd" not in set(schema["field_name"])
        and "adult_octopus_fare_hkd" not in set(schema["field_name"])
        and all(re.fullmatch(r"[0-9a-f]{64}", value) for value in rules["source_sha256"] if value)
    )
    rebuild_ok, rebuild_digest_1, rebuild_digest_2 = rebuild_matches_current(
        repo_root, source_root, output_dir
    )
    check_23 = rebuild_ok

    checks = [
        ("01_schedule_inventory_directly_recomputed", check_1),
        ("02_one_readiness_row_per_schedule_route", check_2),
        ("03_facility_official_stop_mapping_explicit", check_3),
        ("04_no_fuzzy_or_coordinate_nearest_mapping", check_4),
        ("05_forward_pairs_directly_recomputed", check_5),
        ("06_available_amounts_trace_to_raw_gtfs", check_6),
        ("07_candidate_cardinality_and_conflicts_preserved", check_7),
        ("08_no_reverse_od_substitution", check_8),
        ("09_no_distance_interpolation_or_path_sum", check_9),
        ("10_fullfare_reference_never_fallback", check_10),
        ("11_zero_only_when_explicit_in_raw_source", check_11),
        ("12_direction_proven_without_route_suffix", check_12),
        ("13_passenger_payment_semantics_not_invented", check_13),
        ("14_mapping_quality_separate_from_cost_quality", check_14),
        ("15_revision_cutoff_not_fare_effective_date", check_15),
        ("16_fixture_independently_reproduced", check_16),
        ("17_transfer_concession_not_modelled", check_17),
        ("18_production_557104_remain_null_unresolved", check_18),
        ("19_prior_mode_directories_unchanged", bool(check_19)),
        ("20_eight_matsim_inputs_unchanged", bool(check_20)),
        ("21_no_absolute_local_paths", check_21),
        ("22_json_csv_parquet_schema_and_sha_valid", check_22),
        ("23_independent_complete_rebuild_byte_identical", check_23),
    ]
    status = "passed" if all(value for _, value in checks) else "failed"
    validation = {
        "schema_version": "hong_kong_gmb_fare_validation_v1",
        "status": status,
        "checks": [
            {"check_number": index, "name": name, "passed": bool(value)}
            for index, (name, value) in enumerate(checks, 1)
        ],
        "independent_counts": {
            "schedule_lines": len({row["matsim_line_id"] for row in schedule}),
            "schedule_routes": len(schedule),
            "schedule_departures": sum(row["departures"] for row in schedule),
            "schedule_stop_occurrences": sum(len(row["refs"]) for row in schedule),
            "schedule_distinct_facilities": len({ref for row in schedule for ref in row["refs"]}),
            "schedule_distinct_official_stop_ids": len({stop for row in schedule for stop in row["stops"]}),
            "required_forward_pairs": required_count,
            "matched_forward_pairs": matched_count,
            "gtfs_fare_attributes": len(attrs),
            "gtfs_fare_rules": len(raw_rules),
            "gtfs_orphans": len({row["fare_id"] for row in attrs} - {row["fare_id"] for row in raw_rules}),
            "rule_status_counts": dict(raw_status_counts),
            "fixture_rows": len(fixture_in),
            "fixture_available_rows": fixture_available,
            "full_fare_references": len(full_refs),
            "full_fare_comparison_counts": expected_full_fare_comparisons,
        },
        "mapping_quality_counts": dict(Counter(rules["mapping_quality"])),
        "cost_quality_counts": dict(Counter(rules["cost_quality"])),
        "protected_hash_results": protected_results,
        "rebuild_determinism": {
            "passed": rebuild_ok,
            "current_overall_sha256": rebuild_digest_1,
            "rebuilt_overall_sha256": rebuild_digest_2,
        },
        "missing_required_files": missing_files,
    }
    validation_path = output_dir / "gmb_fare_validation.json"
    validation_path.write_text(
        json.dumps(validation, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    checksum_paths = sorted(
        path for path in output_dir.iterdir() if path.is_file() and path.name != "SHA256SUMS.txt"
    )
    checksum_text = "".join(f"{sha256(path)}  {path.name}\n" for path in checksum_paths)
    (output_dir / "SHA256SUMS.txt").write_text(checksum_text, encoding="utf-8")
    manifest_ok = all(
        sha256(output_dir / name) == expected
        for expected, name in (line.split("  ", 1) for line in checksum_text.splitlines())
    )
    print(f"GMB fare validation {status}: {sum(value for _, value in checks)}/23")
    if status != "passed" or not manifest_ok:
        failed = [name for name, value in checks if not value]
        if not manifest_ok:
            failed.append("post_write_sha256_manifest")
        raise SystemExit("Failed checks: " + ", ".join(failed))


if __name__ == "__main__":
    main()
