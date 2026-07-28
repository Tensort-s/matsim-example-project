#!/usr/bin/env python3
"""Quote audited Hong Kong Ferry fares for explicit route-direction-stop-OD requests."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import pandas as pd


INPUT_COLUMNS = [
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
    "transfer_concession_requested",
]
OUTPUT_COLUMNS = [
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
    "cost_component",
    "fare_amount_role",
    "cost_hkd",
    "cost_source",
    "cost_effective_date",
    "cost_effective_date_status",
    "cost_quality",
    "mapping_status",
    "source_record_id",
    "unresolved_reason",
    "transfer_concession_hkd",
    "transfer_concession_status",
]
UNSPECIFIED_INPUT_FIELDS = [
    "passenger_type",
    "payment_medium",
    "service_class",
    "vessel_service_type",
    "day_type",
]


def blank_result(request: dict[str, str]) -> dict[str, object]:
    return {
        **{column: request.get(column, "") for column in INPUT_COLUMNS if column in OUTPUT_COLUMNS},
        "cost_component": "pt_fare",
        "fare_amount_role": "",
        "cost_hkd": None,
        "cost_source": "",
        "cost_effective_date": "",
        "cost_effective_date_status": "",
        "cost_quality": "U",
        "mapping_status": "unresolved",
        "source_record_id": "",
        "unresolved_reason": "",
        "transfer_concession_hkd": None,
        "transfer_concession_status": "not_modelled",
    }


def quote_one(
    request: dict[str, str], rules: pd.DataFrame, full_route_ids: set[str]
) -> dict[str, object]:
    result = blank_result(request)
    if request["actual_transport_mode"].strip() != "ferry":
        result["unresolved_reason"] = "actual_transport_mode_must_be_ferry"
        return result
    for field in UNSPECIFIED_INPUT_FIELDS:
        if request[field].strip() != "unspecified":
            result["unresolved_reason"] = f"{field}_not_explicitly_supported_by_source"
            return result
    try:
        travel_date = date.fromisoformat(request["travel_date"].strip())
    except ValueError:
        result["unresolved_reason"] = "invalid_travel_date"
        return result

    available = rules[rules["record_status"] == "available"]
    route_id = request["official_route_id"].strip()
    matsim_route_id = request["matsim_route_id"].strip()
    route_candidates = available[
        (available["official_route_id"] == route_id)
        & (available["matsim_route_id"] == matsim_route_id)
    ]
    if not route_id or not matsim_route_id:
        result["unresolved_reason"] = "route_identifier_missing"
        return result
    if route_candidates.empty:
        if route_id not in set(available["official_route_id"]):
            result["unresolved_reason"] = "unknown_official_route_id"
        elif matsim_route_id not in set(
            available[available["official_route_id"] == route_id]["matsim_route_id"]
        ):
            result["unresolved_reason"] = "matsim_route_and_official_route_mismatch"
        else:
            result["unresolved_reason"] = "route_not_available"
        return result

    direction = request["official_direction"].strip()
    if not direction:
        result["unresolved_reason"] = "official_direction_missing"
        return result
    exact_scope = route_candidates[
        route_candidates["fare_scope"] == "exact_route_direction_stop_od"
    ]
    partial_scope = route_candidates[
        route_candidates["fare_scope"] == "route_stop_od_direction_not_encoded"
    ]
    if len(exact_scope):
        direction_candidates = exact_scope[
            exact_scope["official_direction"] == direction
        ]
        if direction_candidates.empty:
            result["unresolved_reason"] = "official_direction_mismatch"
            return result
    else:
        if direction != "unspecified":
            result["unresolved_reason"] = "official_direction_not_encoded_input_must_be_unspecified"
            return result
        direction_candidates = partial_scope

    boarding = request["boarding_stop_id"].strip()
    alighting = request["alighting_stop_id"].strip()
    if not boarding:
        result["unresolved_reason"] = "boarding_stop_id_missing"
        return result
    if not alighting:
        result["unresolved_reason"] = "alighting_stop_id_missing"
        return result
    od_candidates = direction_candidates[
        (direction_candidates["boarding_stop_id"] == boarding)
        & (direction_candidates["alighting_stop_id"] == alighting)
    ]
    if od_candidates.empty:
        known_boarding = boarding in set(route_candidates["boarding_stop_id"]) | set(
            route_candidates["alighting_stop_id"]
        )
        known_alighting = alighting in set(route_candidates["boarding_stop_id"]) | set(
            route_candidates["alighting_stop_id"]
        )
        if not known_boarding:
            result["unresolved_reason"] = "unknown_boarding_stop_for_route"
        elif not known_alighting:
            result["unresolved_reason"] = "unknown_alighting_stop_for_route"
        elif route_id in full_route_ids:
            result["unresolved_reason"] = (
                "ordered_stop_od_rule_missing_full_fare_reference_not_used"
            )
        else:
            result["unresolved_reason"] = "ordered_stop_od_rule_missing"
        return result
    if len(od_candidates) > 1:
        result["mapping_status"] = "ambiguous"
        result["unresolved_reason"] = "multiple_matching_fare_rules"
        return result

    rule = od_candidates.iloc[0]
    effective = date.fromisoformat(str(rule["cost_effective_date"]))
    if travel_date < effective:
        result["unresolved_reason"] = "travel_date_before_cost_effective_date"
        return result
    result.update(
        {
            "fare_amount_role": rule["fare_amount_role"],
            "cost_hkd": float(rule["adult_base_fare_hkd"]),
            "cost_source": rule["cost_source"],
            "cost_effective_date": rule["cost_effective_date"],
            "cost_effective_date_status": rule["cost_effective_date_status"],
            "cost_quality": rule["mapping_quality"],
            "mapping_status": rule["mapping_status"],
            "source_record_id": rule["source_record_id"],
            "unresolved_reason": "",
        }
    )
    return result


def run(input_path: Path, output_path: Path, rules_path: Path, full_path: Path) -> None:
    requests = pd.read_csv(input_path, dtype=str, keep_default_na=False)
    missing = [column for column in INPUT_COLUMNS if column not in requests.columns]
    if missing:
        raise ValueError(f"Input is missing required columns: {missing}")
    rules = pd.read_parquet(rules_path).fillna("")
    for column in rules.columns:
        if column != "adult_base_fare_hkd":
            rules[column] = rules[column].astype(str)
    full_refs = pd.read_csv(full_path, dtype=str, keep_default_na=False)
    full_route_ids = set(full_refs["official_route_id"])
    results = [
        quote_one({key: str(value) for key, value in row.items()}, rules, full_route_ids)
        for row in requests.to_dict("records")
    ]
    pd.DataFrame(results, columns=OUTPUT_COLUMNS).to_csv(
        output_path, index=False, encoding="utf-8", lineterminator="\n"
    )
    print(f"Wrote {len(results)} Ferry fare quotes to {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    repo_root = Path(__file__).resolve().parents[4]
    default_dir = (
        repo_root / "data/transport_costs/hongkong/pt_fare_v1/ferry_fare_v1"
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--rules",
        type=Path,
        default=default_dir / "ferry_fare_rules.parquet",
    )
    parser.add_argument(
        "--full-fare-reference",
        type=Path,
        default=default_dir / "ferry_route_full_fare_reference.csv",
    )
    args = parser.parse_args()
    run(args.input, args.output, args.rules, args.full_fare_reference)


if __name__ == "__main__":
    main()
