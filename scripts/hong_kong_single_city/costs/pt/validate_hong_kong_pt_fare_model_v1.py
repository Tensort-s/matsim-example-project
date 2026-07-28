"""Independently validate Hong Kong offline PT fare model v1 outputs.

This validator does not import the build or trip-audit scripts. It recomputes
counts, consistency checks, protected-input hashes, source hashes, portability
checks, and summary reconciliation directly from the written artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


CANONICAL_SOURCE_ROOT = Path(r"F:\Matsim\matsim-example-project")
ALLOWED_MAPPING_STATUSES = {
    "exact",
    "one_to_many_explicit",
    "partial",
    "ambiguous",
    "unresolved",
    "not_applicable",
}
ALLOWED_MAPPING_QUALITIES = {"A", "B", "C", "D", "U"}
KNOWN_UNMATCHED_ROUTES = {
    "bus_1000004_1",
    "bus_1000004_2",
    "bus_1000611_1",
    "bus_8780_1",
    "bus_8780_2",
}
LOCAL_ABSOLUTE_PATH = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|\\\\[^\\])")


def repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Independently validate Hong Kong PT fare model v1 outputs."
    )
    parser.add_argument("--source-project-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser.parse_args()


def choose_source_root(value: Path | None) -> Path:
    if value is not None:
        return value.resolve()
    local = repository_root()
    protected = (
        local
        / "data/transit/hongkong/processed/"
        "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_"
        "ferry_core_v1_cap010/network.xml.gz"
    )
    return local if protected.exists() else CANONICAL_SOURCE_ROOT


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_columns(frame: pd.DataFrame, required: list[str], label: str) -> None:
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise AssertionError(f"{label} missing columns: {missing}")


def write_sha256s(output_dir: Path) -> None:
    paths = sorted(
        path
        for path in output_dir.iterdir()
        if path.is_file() and path.name != "SHA256SUMS.txt"
    )
    (output_dir / "SHA256SUMS.txt").write_text(
        "\n".join(f"{sha256(path)}  {path.name}" for path in paths) + "\n",
        encoding="utf-8",
    )


def validate_portability(output_dir: Path) -> list[str]:
    checked: list[str] = []
    for path in sorted(output_dir.iterdir()):
        if path.suffix.lower() not in {".csv", ".json", ".md", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8")
        if LOCAL_ABSOLUTE_PATH.search(text):
            raise AssertionError(f"Absolute local path found in {path.name}")
        checked.append(path.name)
    return checked


def validate_json_files(output_dir: Path) -> list[str]:
    parsed: list[str] = []
    for path in sorted(output_dir.glob("*.json")):
        json.loads(path.read_text(encoding="utf-8"))
        parsed.append(path.name)
    return parsed


def validate_source_manifest(
    source_root: Path, source_manifest: pd.DataFrame
) -> dict[str, int]:
    required = [
        "source_id",
        "mode_scope",
        "source_url",
        "source_dataset_url",
        "effective_date",
        "effective_date_basis",
        "effective_date_status",
        "download_date",
        "download_date_basis",
        "repository_relative_path",
        "size_bytes",
        "sha256",
    ]
    require_columns(source_manifest, required, "fare_source_manifest")
    forbidden_columns = {"local_path", "absolute_path", "source_project_root"}
    if set(source_manifest.columns) & forbidden_columns:
        raise AssertionError("Source manifest retains an absolute-path column")
    checked = 0
    for row in source_manifest.itertuples(index=False):
        relative = Path(row.repository_relative_path)
        if relative.is_absolute():
            raise AssertionError(f"Absolute source path: {relative}")
        path = source_root / relative
        if not path.exists():
            raise AssertionError(f"Missing source file: {relative.as_posix()}")
        if path.stat().st_size != int(row.size_bytes):
            raise AssertionError(f"Source size mismatch: {row.source_id}")
        if sha256(path) != row.sha256:
            raise AssertionError(f"Source SHA256 mismatch: {row.source_id}")
        checked += 1
    return {"source_rows": len(source_manifest), "source_hashes_verified": checked}


def validate_inventory(inventory: pd.DataFrame) -> dict[str, Any]:
    require_columns(
        inventory,
        [
            "matsim_line_id",
            "matsim_route_id",
            "transport_mode",
            "departure_count",
        ],
        "transit_schedule_inventory",
    )
    result = {
        "lines": int(inventory["matsim_line_id"].nunique()),
        "routes": int(len(inventory)),
        "departures": int(inventory["departure_count"].sum()),
    }
    expected = {"lines": 2434, "routes": 3613, "departures": 159967}
    if result != expected:
        raise AssertionError(f"Schedule inventory mismatch: {result} != {expected}")
    return result


def validate_crosswalk(crosswalk: pd.DataFrame) -> dict[str, Any]:
    required = [
        "matsim_line_id",
        "matsim_route_id",
        "transport_mode",
        "official_route_id",
        "official_route_sequence",
        "official_line_id",
        "official_direction",
        "scheduled_stop_count",
        "mapped_stop_count",
        "stop_id_coverage",
        "candidate_count",
        "candidate_cardinality",
        "route_identifier_status",
        "direction_status",
        "fare_scope",
        "official_od_pair_count",
        "required_forward_pair_count",
        "matched_forward_pair_count",
        "forward_pair_coverage",
        "full_fare_record_count",
        "mapping_status",
        "mapping_quality",
        "matching_method",
        "evidence",
        "unresolved_reason",
    ]
    require_columns(crosswalk, required, "route_to_official_fare_match")
    if len(crosswalk) != 3613:
        raise AssertionError(f"Crosswalk has {len(crosswalk)} rows, expected 3613")
    if crosswalk.duplicated(["matsim_line_id", "matsim_route_id"]).any():
        raise AssertionError("Duplicate line_id + route_id in crosswalk")
    if not set(crosswalk["mapping_status"]).issubset(ALLOWED_MAPPING_STATUSES):
        raise AssertionError("Invalid mapping_status value")
    if not set(crosswalk["mapping_quality"]).issubset(
        ALLOWED_MAPPING_QUALITIES
    ):
        raise AssertionError("Invalid mapping_quality value")

    cardinality = np.select(
        [
            crosswalk["candidate_count"].eq(0),
            crosswalk["candidate_count"].eq(1),
        ],
        ["none", "one"],
        default="multiple",
    )
    if not np.array_equal(cardinality, crosswalk["candidate_cardinality"].to_numpy()):
        raise AssertionError("candidate_count/cardinality inconsistency")
    exact = crosswalk["mapping_status"].eq("exact")
    if not crosswalk.loc[exact, "candidate_count"].eq(1).all():
        raise AssertionError("Exact mapping has non-unique candidate")
    if not crosswalk.loc[exact, "mapping_quality"].eq("A").all():
        raise AssertionError("Exact mapping is not quality A")
    if crosswalk.loc[exact, "direction_status"].isin(
        ["", "direction_not_encoded", "unresolved"]
    ).any():
        raise AssertionError("Exact mapping lacks explicit direction")
    if not crosswalk.loc[exact, "forward_pair_coverage"].eq(1.0).all():
        raise AssertionError("Exact mapping lacks full forward-pair coverage")
    if not crosswalk.loc[exact, "stop_id_coverage"].eq(1.0).all():
        raise AssertionError("Exact mapping lacks full station/stop coverage")

    quality_a = crosswalk["mapping_quality"].eq("A")
    if not (quality_a == exact).all():
        raise AssertionError("Quality A is not identical to exact mappings")
    needs_reason = crosswalk["mapping_status"].isin(
        ["partial", "ambiguous", "unresolved"]
    )
    if crosswalk.loc[needs_reason, "unresolved_reason"].fillna("").eq("").any():
        raise AssertionError("Non-final mapping lacks unresolved_reason")
    one_to_many = crosswalk["mapping_status"].eq("one_to_many_explicit")
    if not crosswalk.loc[one_to_many, "candidate_count"].gt(1).all():
        raise AssertionError("one_to_many_explicit lacks multiple candidates")

    known = crosswalk[crosswalk["matsim_route_id"].isin(KNOWN_UNMATCHED_ROUTES)]
    if set(known["matsim_route_id"]) != KNOWN_UNMATCHED_ROUTES:
        raise AssertionError("Known unmatched routes disappeared")
    if not known["mapping_status"].eq("unresolved").all():
        raise AssertionError("Known unmatched routes are no longer unresolved")

    status_counts = {
        str(key): int(value)
        for key, value in crosswalk["mapping_status"].value_counts().items()
    }
    quality_counts = {
        str(key): int(value)
        for key, value in crosswalk["mapping_quality"].value_counts().items()
    }
    forward = {}
    for mode, group in crosswalk.groupby("transport_mode"):
        required_total = int(group["required_forward_pair_count"].sum())
        matched_total = int(group["matched_forward_pair_count"].sum())
        forward[str(mode)] = {
            "required_forward_pairs": required_total,
            "matched_forward_pairs": matched_total,
            "weighted_forward_pair_coverage": (
                matched_total / required_total if required_total else 0.0
            ),
        }
    return {
        "rows": len(crosswalk),
        "mapping_status": status_counts,
        "mapping_quality": quality_counts,
        "forward_pair_coverage_by_mode": forward,
        "known_unmatched_routes": sorted(KNOWN_UNMATCHED_ROUTES),
    }


def validate_trip_audit(trips: pd.DataFrame) -> dict[str, Any]:
    required = [
        "person_id",
        "leg_sequence",
        "mode",
        "cost_component",
        "cost_hkd",
        "cost_source",
        "cost_effective_date",
        "cost_quality",
        "mapping_status",
        "unresolved_reason",
        "required_missing_fields",
        "serialized_route_type",
        "actual_transport_mode",
        "actual_line_id",
        "actual_route_id",
        "boarding_stop_id",
        "alighting_stop_id",
        "source_record_id",
        "transfer_concession_hkd",
        "transfer_concession_status",
        "estimation_method",
    ]
    require_columns(trips, required, "pt_passenger_trip_fare_audit")
    if trips.duplicated(["person_id", "leg_sequence"]).any():
        raise AssertionError("Duplicate person_id + leg_sequence in trip audit")
    if not trips["mode"].eq("pt").all():
        raise AssertionError("Non-PT row found in PT trip audit")

    missing_route_evidence = (
        trips["serialized_route_type"].eq("generic")
        & trips["actual_transport_mode"].isna()
        & trips["actual_line_id"].isna()
        & trips["actual_route_id"].isna()
        & trips["boarding_stop_id"].isna()
        & trips["alighting_stop_id"].isna()
    )
    if trips.loc[missing_route_evidence, "cost_hkd"].notna().any():
        raise AssertionError("Generic PT trip without itinerary has cost_hkd")
    if trips.loc[missing_route_evidence, "cost_quality"].ne("U").any():
        raise AssertionError("Unchargeable generic PT trip is not quality U")
    if trips.loc[missing_route_evidence, "mapping_status"].ne("unresolved").any():
        raise AssertionError("Unchargeable generic PT trip is not unresolved")
    if trips.loc[missing_route_evidence, "unresolved_reason"].fillna("").eq("").any():
        raise AssertionError("Unchargeable generic PT trip lacks unresolved_reason")

    missing_cost = trips["cost_hkd"].isna()
    if trips.loc[missing_cost, "cost_hkd"].eq(0).any():
        raise AssertionError("Missing fare was filled with zero")
    priced = trips["cost_hkd"].notna()
    if priced.any():
        trace_fields = [
            "cost_source",
            "cost_effective_date",
            "source_record_id",
            "actual_transport_mode",
            "actual_route_id",
            "boarding_stop_id",
            "alighting_stop_id",
        ]
        if trips.loc[priced, trace_fields].isna().any().any():
            raise AssertionError("Priced trip lacks source/itinerary trace")
    forbidden_columns = {
        "bus_fare_estimate_hkd",
        "gmb_fare_estimate_hkd",
        "train_fare_estimate_hkd",
        "light_rail_fare_estimate_hkd",
        "ferry_fare_estimate_hkd",
        "nearest_reference_distance_gap_m",
    }
    if set(trips.columns) & forbidden_columns:
        raise AssertionError("Withdrawn cross-mode/distance estimator columns remain")
    methods = trips["estimation_method"].fillna("").astype(str)
    if methods.str.contains("median|distance_bin|clip", case=False, regex=True).any():
        raise AssertionError("Cross-mode median or distance clipping remains")
    if trips["transfer_concession_hkd"].notna().any():
        raise AssertionError("Transfer concession amount was fabricated")
    if not trips["transfer_concession_status"].str.startswith("not_modelled").all():
        raise AssertionError("Transfer-concession status is not explicit")

    reason_counts = {
        str(key): int(value)
        for key, value in trips["unresolved_reason"].value_counts().items()
    }
    return {
        "total_rows": int(len(trips)),
        "priced_rows": int(priced.sum()),
        "unresolved_rows": int(trips["mapping_status"].eq("unresolved").sum()),
        "unresolved_reason_counts": reason_counts,
        "cross_mode_fare_aggregation_present": False,
        "distance_endpoint_clipping_present": False,
    }


def validate_protected_inputs(
    source_root: Path, baseline: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, Any]]:
    require_columns(
        baseline,
        ["repository_relative_path", "size_bytes", "sha256_before"],
        "protected_input_hashes_baseline",
    )
    rows = []
    for record in baseline.itertuples(index=False):
        relative = Path(record.repository_relative_path)
        path = source_root / relative
        if not path.exists():
            raise AssertionError(f"Protected input missing: {relative.as_posix()}")
        size_after = path.stat().st_size
        hash_after = sha256(path)
        rows.append(
            {
                "repository_relative_path": relative.as_posix(),
                "size_bytes_before": int(record.size_bytes),
                "size_bytes_after": int(size_after),
                "sha256_before": record.sha256_before,
                "sha256_after": hash_after,
                "unchanged": bool(
                    int(record.size_bytes) == size_after
                    and record.sha256_before == hash_after
                ),
            }
        )
    comparison = pd.DataFrame(rows)
    if not comparison["unchanged"].all():
        changed = comparison.loc[
            ~comparison["unchanged"], "repository_relative_path"
        ].tolist()
        raise AssertionError(f"Protected inputs changed: {changed}")
    return comparison, {
        "files_checked": int(len(comparison)),
        "all_unchanged": bool(comparison["unchanged"].all()),
    }


def validate_summary(
    summary: dict[str, Any],
    inventory_result: dict[str, Any],
    crosswalk_result: dict[str, Any],
    trip_result: dict[str, Any],
) -> None:
    schedule = summary["schedule"]
    if (
        int(schedule["transit_lines"]) != inventory_result["lines"]
        or int(schedule["transit_routes"]) != inventory_result["routes"]
        or int(schedule["departures"]) != inventory_result["departures"]
    ):
        raise AssertionError("Summary schedule counts do not match detail")
    route_summary = summary["route_matches"]
    if route_summary["mapping_status"] != crosswalk_result["mapping_status"]:
        raise AssertionError("Summary mapping_status counts do not match detail")
    if route_summary["mapping_quality"] != crosswalk_result["mapping_quality"]:
        raise AssertionError("Summary mapping_quality counts do not match detail")
    for mode, detail in crosswalk_result["forward_pair_coverage_by_mode"].items():
        summary_detail = route_summary["forward_pair_coverage_by_mode"][mode]
        for key in ("required_forward_pairs", "matched_forward_pairs"):
            if int(summary_detail[key]) != int(detail[key]):
                raise AssertionError(f"Summary forward-pair {key} mismatch: {mode}")
        if not np.isclose(
            float(summary_detail["weighted_forward_pair_coverage"]),
            float(detail["weighted_forward_pair_coverage"]),
        ):
            raise AssertionError(f"Summary forward-pair coverage mismatch: {mode}")
    trip_summary = summary["trip_audit"]
    if int(trip_summary["total_pt_trips"]) != trip_result["total_rows"]:
        raise AssertionError("Summary PT trip count does not match detail")
    if int(trip_summary["priced_trips"]) != trip_result["priced_rows"]:
        raise AssertionError("Summary priced trip count does not match detail")
    if int(trip_summary["unresolved_trips"]) != trip_result["unresolved_rows"]:
        raise AssertionError("Summary unresolved trip count does not match detail")


def main() -> None:
    args = parse_args()
    source_root = choose_source_root(args.source_project_root)
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else repository_root() / "data/transport_costs/hongkong/pt_fare_v1"
    )

    inventory = pd.read_csv(output_dir / "transit_schedule_inventory.csv")
    crosswalk = pd.read_csv(
        output_dir / "route_to_official_fare_match.csv",
        keep_default_na=False,
    )
    trips = pd.read_parquet(output_dir / "pt_passenger_trip_fare_audit.parquet")
    source_manifest = pd.read_csv(
        output_dir / "fare_source_manifest.csv", keep_default_na=False
    )
    baseline = pd.read_csv(output_dir / "protected_input_hashes_baseline.csv")
    summary = json.loads(
        (output_dir / "pt_fare_model_summary.json").read_text(encoding="utf-8")
    )

    inventory_result = validate_inventory(inventory)
    crosswalk_result = validate_crosswalk(crosswalk)
    trip_result = validate_trip_audit(trips)
    source_result = validate_source_manifest(source_root, source_manifest)
    comparison, protected_result = validate_protected_inputs(source_root, baseline)
    validate_summary(summary, inventory_result, crosswalk_result, trip_result)

    comparison.to_csv(
        output_dir / "protected_input_hash_comparison.csv",
        index=False,
        encoding="utf-8",
    )
    portability_checked = validate_portability(output_dir)
    json_parsed = validate_json_files(output_dir)

    legacy_files = [
        "official_fare_distance_curve.csv",
        "pt_passenger_trip_fare_estimates.parquet",
        "pt_passenger_trip_fare_estimates_sample.csv",
        "pt_trip_fare_validation.json",
    ]
    legacy_present = [
        filename for filename in legacy_files if (output_dir / filename).exists()
    ]
    if legacy_present:
        raise AssertionError(f"Withdrawn active outputs remain: {legacy_present}")

    validation = {
        "validator": "independent Hong Kong PT fare model v1 validator",
        "schedule_inventory": inventory_result,
        "route_crosswalk": crosswalk_result,
        "trip_audit": trip_result,
        "fare_sources": source_result,
        "protected_inputs": protected_result,
        "portability": {
            "text_files_checked": portability_checked,
            "absolute_local_paths_found": 0,
        },
        "json_files_parsed": json_parsed,
        "withdrawn_active_outputs_present": legacy_present,
        "validation_passed": True,
    }
    validation_path = output_dir / "pt_fare_independent_validation.json"
    validation_path.write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_sha256s(output_dir)

    sha_lines = (
        output_dir / "SHA256SUMS.txt"
    ).read_text(encoding="utf-8").strip().splitlines()
    sha_map = {
        line.split("  ", 1)[1]: line.split("  ", 1)[0] for line in sha_lines
    }
    for path in output_dir.iterdir():
        if path.is_file() and path.name != "SHA256SUMS.txt":
            if sha_map.get(path.name) != sha256(path):
                raise AssertionError(f"Output SHA256 mismatch: {path.name}")
    print(json.dumps(validation, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
