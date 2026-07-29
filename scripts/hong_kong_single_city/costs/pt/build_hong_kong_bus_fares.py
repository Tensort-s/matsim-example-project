#!/usr/bin/env python3
"""Build Hong Kong franchised-bus Core v1 offline published-fare rules."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd


UNSPECIFIED = "unspecified_in_source"
DOWNLOAD_DATE = "2026-07-20"
REVISION_STATUS = "not_encoded_in_source_revision_cutoff_only"
FARE_ROLE = (
    "published_fare_passenger_and_payment_basis_unspecified_"
    "before_unmodelled_concessions"
)
APPLICABILITY = (
    "published_amount_only_passenger_payment_service_class_"
    "and_effective_period_unspecified"
)
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
EXPECTED_TOTAL = 771_666

RULE_COLUMNS = [
    "fare_scope",
    "operator",
    "operator_components_json",
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
    "route_franchise_scope_status",
    "mapping_status",
    "mapping_quality",
    "cost_quality",
    "cost_applicability_status",
    "matching_method",
    "unresolved_reason",
]
UNRESOLVED_COLUMNS = RULE_COLUMNS + ["cost_hkd", "exclusion_reason"]
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
    "service_class",
    "day_type",
    "time_period",
    "travel_date",
    "temporal_basis",
    "transfer_concession_requested",
    "expected_result",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_zip_csv(archive: zipfile.ZipFile, name: str) -> list[dict[str, str]]:
    with archive.open(name) as raw:
        reader = csv.DictReader(
            io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        )
        rows = []
        for line_number, row in enumerate(reader, 2):
            item = dict(row)
            item["_line_number"] = str(line_number)
            rows.append(item)
        return rows


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    frame.to_parquet(path, index=False, engine="pyarrow", compression="zstd")


def active_rule_from_audit(row: dict[str, Any]) -> dict[str, Any]:
    records = json.loads(row["candidate_records_json"])
    record = records[0]
    return {
        "fare_scope": "confirmed_franchised_route_exact_direction_ordered_stop_od",
        "operator": row["official_operator"],
        "operator_components_json": row["official_operator_components_json"],
        "matsim_line_id": row["matsim_line_id"],
        "matsim_route_id": row["matsim_route_id"],
        "official_route_id": row["official_route_id"],
        "official_route_sequence": row["official_route_sequence"],
        "official_direction": row["official_direction"],
        "boarding_stop_id": row["boarding_stop_id"],
        "alighting_stop_id": row["alighting_stop_id"],
        "passenger_type": UNSPECIFIED,
        "payment_medium": UNSPECIFIED,
        "service_class": UNSPECIFIED,
        "day_type": UNSPECIFIED,
        "time_period": UNSPECIFIED,
        "published_fare_hkd": float(record["price"]),
        "currency": record["currency"],
        "fare_amount_role": FARE_ROLE,
        "cost_component": "pt_fare",
        "cost_source": "td_gtfs_20260720",
        "cost_effective_date": "",
        "cost_effective_date_status": REVISION_STATUS,
        "source_revision_cutoff_date": row["source_revision_cutoff_date"],
        "source_download_date": row["source_download_date"],
        "source_record_id": (
            f"gtfs:fare_rules:{record['fare_rule_line']};"
            f"fare_attributes:{record['fare_attribute_line']};"
            f"fare_id:{record['fare_id']}"
        ),
        "source_record_ids_json": compact_json(
            [
                {
                    "fare_id": record["fare_id"],
                    "fare_rule_line": record["fare_rule_line"],
                    "fare_attribute_line": record["fare_attribute_line"],
                }
            ]
        ),
        "source_file": row["source_file"],
        "source_sha256": row["source_sha256"],
        "candidate_count": 1,
        "distinct_amount_count": 1,
        "record_status": "available",
        "candidate_records_json": row["candidate_records_json"],
        "route_franchise_scope_status": "confirmed_franchised_route",
        "mapping_status": "exact",
        "mapping_quality": "A",
        "cost_quality": "B",
        "cost_applicability_status": APPLICABILITY,
        "matching_method": (
            "confirmed_CSDI_route_key_plus_unique_complete_JSON_direction_"
            "plus_unique_GTFS_ordered_stop_OD"
        ),
        "unresolved_reason": "",
    }


def unresolved_rule_from_audit(row: dict[str, Any]) -> dict[str, Any]:
    scope = row["route_franchise_scope_status"]
    status = row["record_status"]
    reason = (
        "confirmed_route_duplicate_identical"
        if scope == "confirmed_franchised_route" and status == "duplicate_identical"
        else "confirmed_route_conflicting_amounts"
        if scope == "confirmed_franchised_route" and status == "conflicting_amounts"
        else "franchise_route_scope_unresolved"
        if scope == "franchise_route_scope_unresolved"
        else "other_bus_service_excluded"
        if scope == "other_bus_service"
        else "operator_scope_unresolved"
    )
    records = json.loads(row["candidate_records_json"])
    amount = float(records[0]["price"]) if len(records) == 1 else None
    return {
        "fare_scope": "bus_ordered_stop_od_excluded_from_core_v1",
        "operator": row["official_operator"],
        "operator_components_json": row["official_operator_components_json"],
        "matsim_line_id": row["matsim_line_id"],
        "matsim_route_id": row["matsim_route_id"],
        "official_route_id": row["official_route_id"],
        "official_route_sequence": row["official_route_sequence"],
        "official_direction": row["official_direction"],
        "boarding_stop_id": row["boarding_stop_id"],
        "alighting_stop_id": row["alighting_stop_id"],
        "passenger_type": UNSPECIFIED,
        "payment_medium": UNSPECIFIED,
        "service_class": UNSPECIFIED,
        "day_type": UNSPECIFIED,
        "time_period": UNSPECIFIED,
        "published_fare_hkd": amount,
        "currency": records[0]["currency"] if records else "",
        "fare_amount_role": (
            "excluded_published_fare_candidate_not_an_active_rule"
        ),
        "cost_component": "pt_fare",
        "cost_source": "",
        "cost_effective_date": "",
        "cost_effective_date_status": REVISION_STATUS,
        "source_revision_cutoff_date": row["source_revision_cutoff_date"],
        "source_download_date": row["source_download_date"],
        "source_record_id": "",
        "source_record_ids_json": row["candidate_record_ids_json"],
        "source_file": row["source_file"],
        "source_sha256": row["source_sha256"],
        "candidate_count": int(row["candidate_count"]),
        "distinct_amount_count": int(row["distinct_amount_count"]),
        "record_status": status,
        "candidate_records_json": row["candidate_records_json"],
        "route_franchise_scope_status": scope,
        "mapping_status": "unresolved",
        "mapping_quality": "U",
        "cost_quality": "U",
        "cost_applicability_status": "not_applicable_excluded_or_unresolved",
        "matching_method": row["matching_method"],
        "unresolved_reason": reason,
        "cost_hkd": None,
        "exclusion_reason": reason,
    }


def fixture_rows(
    active: pd.DataFrame,
    unresolved: pd.DataFrame,
    unresolved_routes: pd.DataFrame,
) -> list[dict[str, Any]]:
    def request(
        quote_id: str,
        row: dict[str, Any],
        expected: str,
        **overrides: Any,
    ) -> dict[str, Any]:
        values = {
            "quote_id": quote_id,
            "actual_transport_mode": "bus",
            "matsim_line_id": row.get("matsim_line_id", ""),
            "matsim_route_id": row.get("matsim_route_id", ""),
            "official_route_id": row.get("official_route_id", ""),
            "official_direction": row.get("official_direction", ""),
            "boarding_stop_id": row.get("boarding_stop_id", ""),
            "alighting_stop_id": row.get("alighting_stop_id", ""),
            "passenger_type": "unspecified",
            "payment_medium": "unspecified",
            "service_class": "unspecified",
            "day_type": "unspecified",
            "time_period": "unspecified",
            "travel_date": "",
            "temporal_basis": "source_snapshot_only",
            "transfer_concession_requested": "false",
            "expected_result": expected,
        }
        values.update(overrides)
        return values

    available = active[active["published_fare_hkd"] > 0]
    first = available.iloc[0].to_dict()
    second = available[available["operator"] != first["operator"]].iloc[0].to_dict()
    joint = available[available["operator"].str.contains(r"\+", regex=True)].iloc[0].to_dict()
    zero_rows = active[active["published_fare_hkd"] == 0]
    zero = zero_rows.iloc[0].to_dict() if len(zero_rows) else first
    duplicate = unresolved[
        unresolved["exclusion_reason"] == "confirmed_route_duplicate_identical"
    ].iloc[0].to_dict()
    conflict = unresolved[
        unresolved["exclusion_reason"] == "confirmed_route_conflicting_amounts"
    ].iloc[0].to_dict()
    scope_unresolved = unresolved[
        (unresolved["exclusion_reason"] == "franchise_route_scope_unresolved")
        & (unresolved["record_status"] == "unique_candidate")
    ].iloc[0].to_dict()
    other = unresolved[
        unresolved["exclusion_reason"] == "other_bus_service_excluded"
    ].iloc[0].to_dict()
    known = unresolved_routes[
        unresolved_routes["route_franchise_scope_status"]
        == "operator_scope_unresolved"
    ].iloc[0].to_dict()
    same_route = active[
        active["matsim_route_id"] == first["matsim_route_id"]
    ]
    reverse_missing = next(
        row
        for row in same_route.to_dict("records")
        if not (
            (same_route["boarding_stop_id"] == row["alighting_stop_id"])
            & (same_route["alighting_stop_id"] == row["boarding_stop_id"])
        ).any()
    )
    reverse_routes = active[
        (active["official_route_id"] == first["official_route_id"])
        & (active["official_direction"] != first["official_direction"])
    ]
    reverse_legal = (
        reverse_routes.iloc[0].to_dict() if len(reverse_routes) else second
    )
    rows = [
        request("available_nonzero_operator_1", first, "available"),
        request("available_nonzero_operator_2", second, "available"),
        request("available_joint_operator", joint, "available"),
        request(
            "available_unique_zero"
            if len(zero_rows)
            else "not_applicable_no_active_unique_zero_rule",
            zero,
            "available" if len(zero_rows) else "not_applicable",
        ),
        request("confirmed_duplicate", duplicate, "unresolved"),
        request("confirmed_conflict", conflict, "unresolved"),
        request("franchise_scope_unresolved_unique", scope_unresolved, "unresolved"),
        request("other_bus_service", other, "unresolved"),
        request("known_unmatched_route", known, "unresolved"),
        request(
            "same_direction_reverse_not_substituted",
            reverse_missing,
            "unresolved",
            boarding_stop_id=reverse_missing["alighting_stop_id"],
            alighting_stop_id=reverse_missing["boarding_stop_id"],
        ),
        request("independent_reverse_route_available", reverse_legal, "available"),
        request("official_route_mismatch", first, "unresolved", official_route_id="999999999"),
        request("line_route_mismatch", first, "unresolved", matsim_line_id=second["matsim_line_id"]),
        request("direction_unspecified", first, "unresolved", official_direction="unspecified"),
        request("direction_wrong", first, "unresolved", official_direction="999"),
        request("boarding_unknown", first, "unresolved", boarding_stop_id="999999999"),
        request("alighting_unknown", first, "unresolved", alighting_stop_id="999999999"),
        request("travel_date_nonempty", first, "unresolved", travel_date="2026-07-20"),
        request("temporal_basis_wrong", first, "unresolved", temporal_basis="travel_date"),
        request("passenger_adult", first, "unresolved", passenger_type="adult"),
        request("payment_octopus", first, "unresolved", payment_medium="Octopus"),
        request("service_class_specific", first, "unresolved", service_class="air_conditioned"),
        request("transfer_requested", first, "unresolved", transfer_concession_requested="true"),
        request(
            "fullfare_fallback_rejected",
            first,
            "unresolved",
            alighting_stop_id=first["boarding_stop_id"],
        ),
        request("missing_required_line", first, "unresolved", matsim_line_id=""),
        request("non_bus_mode", first, "unresolved", actual_transport_mode="pt"),
    ]
    return rows


def protected_hashes(repo_root: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for scope in (
        "bus_scope_direction_audit_v1",
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
    audit_dir = repo_root / AUDIT_REL

    gtfs_path = source_root / GTFS_REL
    gtfs_sha = sha256(gtfs_path)
    audit_summary = json.loads(
        (audit_dir / "bus_scope_direction_summary.json").read_text(encoding="utf-8")
    )
    if audit_summary["source_sha256"]["gtfs"] != gtfs_sha:
        raise RuntimeError("GTFS SHA256 differs from the protected bus audit")
    revision_rows = list(
        csv.reader((source_root / REVISION_REL).open(encoding="utf-8-sig", newline=""))
    )
    revision_cutoff = revision_rows[1][0].strip()
    if revision_cutoff != "2026-07-14":
        raise RuntimeError(f"Unexpected revision cut-off: {revision_cutoff}")

    candidates = pd.read_parquet(
        audit_dir / "bus_od_fare_candidate_audit.parquet"
    ).fillna("")
    active_mask = (
        (candidates["route_franchise_scope_status"] == "confirmed_franchised_route")
        & (candidates["operator_scope_status"] == "confirmed_franchised_operator")
        & (candidates["mapping_status"] == "exact")
        & (candidates["mapping_quality"] == "A")
        & (candidates["record_status"] == "unique_candidate")
        & (candidates["candidate_count"] == 1)
        & (candidates["distinct_amount_count"] == 1)
    )
    active_source = candidates[active_mask].copy()
    excluded_source = candidates[~active_mask].copy()
    if len(active_source) != EXPECTED_ACTIVE:
        difference = {
            "expected_active_rule_count": EXPECTED_ACTIVE,
            "actual_active_rule_count": len(active_source),
            "candidate_status_counts": dict(Counter(candidates["record_status"])),
            "scope_counts": dict(Counter(candidates["route_franchise_scope_status"])),
        }
        (output_dir / "bus_active_rule_count_difference.json").write_text(
            json.dumps(difference, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        raise RuntimeError(
            f"Active rule count {len(active_source):,} != {EXPECTED_ACTIVE:,}"
        )
    if len(candidates) != EXPECTED_TOTAL:
        raise RuntimeError("Required forward-pair universe changed")

    with zipfile.ZipFile(gtfs_path) as archive:
        attrs = read_zip_csv(archive, "fare_attributes.txt")
        raw_rules = read_zip_csv(archive, "fare_rules.txt")
    attr_by_line = {int(row["_line_number"]): row for row in attrs}
    rule_by_line = {int(row["_line_number"]): row for row in raw_rules}
    active_rows: list[dict[str, Any]] = []
    for row in active_source.to_dict("records"):
        records = json.loads(row["candidate_records_json"])
        if len(records) != 1:
            raise RuntimeError("Active source row does not have one raw record")
        record = records[0]
        raw_rule = rule_by_line[record["fare_rule_line"]]
        raw_attr = attr_by_line[record["fare_attribute_line"]]
        if not (
            raw_rule["fare_id"] == record["fare_id"]
            and raw_rule["route_id"] == row["official_route_id"]
            and raw_rule["origin_id"] == row["boarding_stop_id"]
            and raw_rule["destination_id"] == row["alighting_stop_id"]
            and raw_attr["fare_id"] == record["fare_id"]
            and float(raw_attr["price"]) == float(record["price"])
            and raw_attr["currency_type"] == "HKD"
            and row["source_sha256"] == gtfs_sha
        ):
            raise RuntimeError("Active candidate failed direct raw GTFS trace")
        active_rows.append(active_rule_from_audit(row))
    active = pd.DataFrame(active_rows, columns=RULE_COLUMNS)
    write_parquet(active, output_dir / "bus_fare_rules.parquet")
    write_csv(active.head(100), output_dir / "bus_fare_rules_sample.csv")

    unresolved_rows = [
        unresolved_rule_from_audit(row)
        for row in excluded_source.to_dict("records")
    ]
    unresolved = pd.DataFrame(unresolved_rows, columns=UNRESOLVED_COLUMNS)
    write_parquet(unresolved, output_dir / "bus_unresolved_fare_rules.parquet")
    write_csv(
        unresolved.head(100), output_dir / "bus_unresolved_fare_rules_sample.csv"
    )
    conflicts = unresolved[
        unresolved["exclusion_reason"] == "confirmed_route_conflicting_amounts"
    ]
    duplicates = unresolved[
        unresolved["exclusion_reason"] == "confirmed_route_duplicate_identical"
    ]
    excluded_scope = unresolved[
        unresolved["exclusion_reason"].isin(
            ["franchise_route_scope_unresolved", "other_bus_service_excluded"]
        )
    ]
    write_parquet(conflicts, output_dir / "bus_fare_conflicts.parquet")
    write_csv(conflicts.head(100), output_dir / "bus_fare_conflicts_sample.csv")
    write_parquet(duplicates, output_dir / "bus_fare_duplicate_records.parquet")
    write_csv(
        duplicates.head(100), output_dir / "bus_fare_duplicate_records_sample.csv"
    )
    write_parquet(
        excluded_scope, output_dir / "bus_excluded_scope_pairs.parquet"
    )
    write_csv(
        excluded_scope.head(100),
        output_dir / "bus_excluded_scope_pairs_sample.csv",
    )

    route_evidence = pd.read_csv(
        audit_dir / "bus_route_franchise_scope_evidence.csv",
        dtype=str,
        keep_default_na=False,
    )
    unresolved_routes = route_evidence[
        route_evidence["route_franchise_scope_status"].isin(
            ["franchise_route_scope_unresolved", "operator_scope_unresolved"]
        )
    ].copy()
    write_csv(unresolved_routes, output_dir / "bus_unresolved_routes.csv")
    readiness = pd.read_csv(
        audit_dir / "bus_route_direction_readiness.csv",
        dtype=str,
        keep_default_na=False,
    )
    write_csv(readiness, output_dir / "bus_route_direction_fare_readiness.csv")
    full_refs = pd.read_csv(
        audit_dir / "bus_route_full_fare_reference.csv",
        dtype=str,
        keep_default_na=False,
    )
    if not (full_refs["eligible_for_default_quote"] == "False").all():
        raise RuntimeError("Unexpected eligible fullFare reference")
    write_csv(full_refs, output_dir / "bus_route_full_fare_reference.csv")

    zero_active = int((active["published_fare_hkd"] == 0).sum())
    zero_by_exclusion = {
        reason: int(
            unresolved.loc[
                unresolved["exclusion_reason"] == reason,
                "candidate_records_json",
            ].map(
                lambda value: sum(
                    float(record["price"]) == 0
                    for record in json.loads(value)
                )
            ).sum()
        )
        for reason in sorted(set(unresolved["exclusion_reason"]))
    }
    exclusion_counts = dict(Counter(unresolved["exclusion_reason"]))
    fixture = pd.DataFrame(
        fixture_rows(active, unresolved, unresolved_routes),
        columns=FIXTURE_INPUT_COLUMNS,
    )
    write_csv(fixture, output_dir / "bus_fare_query_fixture_input.csv")
    write_csv(
        pd.DataFrame(),
        output_dir / "bus_fare_query_fixture_output.csv",
    )

    source_hashes = {
        "gtfs": gtfs_sha,
        "bus_json": sha256(source_root / JSON_REL),
        "franchised_bus_geometry": sha256(source_root / GEOMETRY_REL),
        "revision": sha256(source_root / REVISION_REL),
        "schedule": sha256(source_root / SCHEDULE_REL),
        "protected_bus_scope_audit_SHA256SUMS": sha256(
            audit_dir / "SHA256SUMS.txt"
        ),
    }
    semantics = {
        "schema_version": "hong_kong_bus_fare_core_v1_semantics",
        "fare_scope": "confirmed_franchised_route_exact_direction_ordered_stop_od",
        "fare_amount_role": FARE_ROLE,
        "passenger_type": UNSPECIFIED,
        "payment_medium": UNSPECIFIED,
        "service_class": UNSPECIFIED,
        "day_type": UNSPECIFIED,
        "time_period": UNSPECIFIED,
        "cost_applicability_status": APPLICABILITY,
        "source_revision_cutoff_date": revision_cutoff,
        "source_download_date": DOWNLOAD_DATE,
        "cost_effective_date": "",
        "cost_effective_date_status": REVISION_STATUS,
        "transfer_concession_status": "not_modelled",
        "production_integration": "not_performed",
        "source_sha256": source_hashes,
    }
    (output_dir / "bus_fare_semantics_summary.json").write_text(
        json.dumps(semantics, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = {
        "schema_version": "hong_kong_bus_fare_core_v1",
        "required_forward_pair_count": len(candidates),
        "active_rule_count": len(active),
        "unresolved_excluded_pair_count": len(unresolved),
        "active_plus_unresolved_count": len(active) + len(unresolved),
        "active_unique_zero_rule_count": zero_active,
        "raw_zero_candidate_record_count_total": (
            zero_active + sum(zero_by_exclusion.values())
        ),
        "zero_candidate_record_counts_by_exclusion": zero_by_exclusion,
        "exclusion_reason_counts": exclusion_counts,
        "confirmed_route_forward_pair_count": 758_563,
        "confirmed_route_active_coverage": len(active) / 758_563,
        "all_bus_pair_active_coverage": len(active) / len(candidates),
        "route_scope_counts": dict(
            Counter(route_evidence["route_franchise_scope_status"])
        ),
        "full_fare_reference_count": len(full_refs),
        "full_fare_reference_in_active_rules": False,
        "fixture_case_count": len(fixture),
        "source_sha256": source_hashes,
        "source_revision_cutoff_date": revision_cutoff,
        "source_download_date": DOWNLOAD_DATE,
        "cost_effective_date": "",
        "cost_effective_date_status": REVISION_STATUS,
        "transfer_concession_status": "not_modelled",
        "production_pt_pricing": "not_performed",
        "matsim_scoring_integration": "not_performed",
    }
    (output_dir / "bus_fare_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_csv(protected_hashes(repo_root), output_dir / "protected_hashes.csv")
    readme = f"""# Hong Kong franchised-bus fare Core v1

Offline source-snapshot rules only:

- {len(active):,} active rules are route-level confirmed, exact-direction,
  unique raw GTFS ordered-OD published amounts.
- {len(unresolved):,} required pairs remain excluded or unresolved.
- {zero_active:,} active rules are explicit raw unique zero-price records.
- Passenger, payment, service-class, and effective-period applicability remain
  unspecified; available cost quality is B, never A.
- Transfer concessions are not modelled.
- No production PT leg, MATSim input, Java, scoring, or ASC is modified.
"""
    (output_dir / "README.md").write_text(readme, encoding="utf-8")
    (output_dir / "bus_fare_validation.json").write_text(
        json.dumps(
            {
                "schema_version": "hong_kong_bus_fare_validation_v1",
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
        f"Built {len(active):,} active bus rules and "
        f"{len(unresolved):,} excluded/unresolved pairs"
    )


if __name__ == "__main__":
    main()
