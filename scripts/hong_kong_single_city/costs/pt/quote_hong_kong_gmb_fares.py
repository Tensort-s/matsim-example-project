#!/usr/bin/env python3
"""Quote Hong Kong GMB published amounts for explicit snapshot-only requests."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


INPUT_COLUMNS = [
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
]
OUTPUT_COLUMNS = [
    *[column for column in INPUT_COLUMNS if column != "transfer_concession_requested"],
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


def blank_result(request: dict[str, str]) -> dict[str, object]:
    return {
        **{column: request.get(column, "") for column in OUTPUT_COLUMNS},
        "cost_component": "pt_fare",
        "fare_amount_role": "",
        "published_fare_hkd": None,
        "cost_hkd": None,
        "cost_source": "",
        "cost_effective_date": "",
        "cost_effective_date_status": "",
        "source_revision_cutoff_date": "",
        "source_download_date": "",
        "cost_quality": "U",
        "mapping_status": "unresolved",
        "mapping_quality": "U",
        "cost_applicability_status": "unresolved",
        "source_record_id": "",
        "source_record_ids_json": "[]",
        "unresolved_reason": "",
        "transfer_concession_hkd": None,
        "transfer_concession_status": "not_modelled",
    }


def quote_one(
    request: dict[str, str], rules: pd.DataFrame, full_route_ids: set[str]
) -> dict[str, object]:
    result = blank_result(request)
    if request["actual_transport_mode"] != "gmb":
        result["unresolved_reason"] = "actual_transport_mode_must_be_gmb"
        return result
    for field in ("passenger_type", "payment_medium", "day_type"):
        if request[field] != "unspecified":
            result["unresolved_reason"] = f"{field}_not_explicitly_supported_by_source"
            return result
    if request["temporal_basis"] != "source_snapshot_only":
        result["unresolved_reason"] = "temporal_basis_must_be_source_snapshot_only"
        return result
    if request["travel_date"]:
        result["unresolved_reason"] = "fare_effective_period_not_encoded_for_travel_date"
        return result

    line_id = request["matsim_line_id"]
    route_id = request["matsim_route_id"]
    official_id = request["official_route_id"]
    direction = request["official_direction"]
    if not line_id or not route_id or not official_id:
        result["unresolved_reason"] = "line_or_route_identifier_missing"
        return result
    route_rows = rules[
        (rules["matsim_line_id"] == line_id)
        & (rules["matsim_route_id"] == route_id)
        & (rules["official_route_id"] == official_id)
    ]
    if route_rows.empty:
        if official_id not in set(rules["official_route_id"]):
            result["unresolved_reason"] = "unknown_official_route_id"
        elif route_id not in set(
            rules[rules["official_route_id"] == official_id]["matsim_route_id"]
        ):
            result["unresolved_reason"] = "matsim_route_and_official_route_mismatch"
        else:
            result["unresolved_reason"] = "matsim_line_and_route_mismatch"
        return result
    if direction == "unspecified":
        result["unresolved_reason"] = "official_direction_is_encoded_for_this_route"
        return result
    direction_rows = route_rows[route_rows["official_direction"] == direction]
    if direction_rows.empty:
        result["unresolved_reason"] = "official_direction_mismatch"
        return result
    boarding = request["boarding_stop_id"]
    alighting = request["alighting_stop_id"]
    od_rows = direction_rows[
        (direction_rows["boarding_stop_id"] == boarding)
        & (direction_rows["alighting_stop_id"] == alighting)
    ]
    if od_rows.empty:
        known = set(route_rows["boarding_stop_id"]) | set(route_rows["alighting_stop_id"])
        if boarding not in known:
            result["unresolved_reason"] = "unknown_boarding_stop_for_route"
        elif alighting not in known:
            result["unresolved_reason"] = "unknown_alighting_stop_for_route"
        elif official_id in full_route_ids:
            result["unresolved_reason"] = (
                "ordered_stop_od_rule_missing_full_fare_reference_not_used"
            )
        else:
            result["unresolved_reason"] = "ordered_stop_od_rule_missing"
        return result
    if len(od_rows) != 1:
        result["mapping_status"] = "ambiguous"
        result["unresolved_reason"] = "multiple_derived_rule_rows"
        return result
    rule = od_rows.iloc[0]
    if rule["record_status"] != "available":
        result["mapping_status"] = rule["mapping_status"]
        result["mapping_quality"] = rule["mapping_quality"]
        result["source_record_ids_json"] = rule["source_record_ids_json"]
        result["unresolved_reason"] = rule["unresolved_reason"]
        return result
    amount = float(rule["published_fare_hkd"])
    result.update(
        {
            "fare_amount_role": rule["fare_amount_role"],
            "published_fare_hkd": amount,
            "cost_hkd": amount,
            "cost_source": rule["cost_source"],
            "cost_effective_date": rule["cost_effective_date"],
            "cost_effective_date_status": rule["cost_effective_date_status"],
            "source_revision_cutoff_date": rule["source_revision_cutoff_date"],
            "source_download_date": rule["source_download_date"],
            "cost_quality": rule["cost_quality"],
            "mapping_status": rule["mapping_status"],
            "mapping_quality": rule["mapping_quality"],
            "cost_applicability_status": rule["cost_applicability_status"],
            "source_record_id": rule["source_record_id"],
            "source_record_ids_json": rule["source_record_ids_json"],
            "unresolved_reason": "",
        }
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    repo_root = Path(__file__).resolve().parents[4]
    default_dir = repo_root / "data/transport_costs/hongkong/pt_fare_v1/gmb_fare_v1"
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rules", type=Path, default=default_dir / "gmb_fare_rules.parquet")
    parser.add_argument(
        "--full-fare-reference",
        type=Path,
        default=default_dir / "gmb_route_full_fare_reference.csv",
    )
    args = parser.parse_args()
    requests = pd.read_csv(args.input, dtype=str, keep_default_na=False)
    missing = [column for column in INPUT_COLUMNS if column not in requests.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")
    rules = pd.read_parquet(args.rules).fillna("")
    for column in rules.columns:
        if column != "published_fare_hkd":
            rules[column] = rules[column].astype(str)
    full_refs = pd.read_csv(
        args.full_fare_reference, dtype=str, keep_default_na=False
    )
    outputs = [
        quote_one(
            {key: str(value) for key, value in request.items()},
            rules,
            set(full_refs["official_route_id"]),
        )
        for request in requests.to_dict("records")
    ]
    pd.DataFrame(outputs, columns=OUTPUT_COLUMNS).to_csv(
        args.output, index=False, encoding="utf-8", lineterminator="\n"
    )
    print(f"Wrote {len(outputs)} GMB fare quotes to {args.output}")


if __name__ == "__main__":
    main()
