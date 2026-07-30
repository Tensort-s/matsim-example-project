#!/usr/bin/env python3
"""Quote coverage-first Hong Kong bus simulation fares v1."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd


BASE = Path(
    "data/transport_costs/hongkong/pt_fare_v1/bus_fare_simulation_v1"
)
OUTPUT_COLUMNS = [
    "quote_id",
    "actual_transport_mode",
    "matsim_line_id",
    "matsim_route_id",
    "official_route_id",
    "official_direction",
    "boarding_stop_id",
    "alighting_stop_id",
    "official_published_fare_hkd",
    "model_fare_hkd",
    "cost_hkd",
    "currency",
    "fare_resolution_status",
    "fare_resolution_method",
    "cost_quality",
    "anomaly_flag",
    "anomaly_severity",
    "anomaly_reason",
    "audit_priority",
    "fallback_used",
    "candidate_values_hkd_json",
    "selection_rationale",
    "source_record_ids_json",
    "source_file",
    "source_sha256",
    "transfer_concession_status",
    "eligibility_status",
    "temporal_status",
    "unresolved_reason",
]


def output_base(request: dict[str, str]) -> dict[str, Any]:
    output = {column: request.get(column, "") for column in OUTPUT_COLUMNS}
    output.update(
        {
            "official_published_fare_hkd": None,
            "model_fare_hkd": None,
            "cost_hkd": None,
            "currency": "HKD",
            "fare_resolution_status": "unresolved",
            "fare_resolution_method": "",
            "cost_quality": "U",
            "anomaly_flag": True,
            "anomaly_severity": "high",
            "anomaly_reason": "",
            "audit_priority": "",
            "fallback_used": False,
            "candidate_values_hkd_json": "[]",
            "selection_rationale": "",
            "source_record_ids_json": "[]",
            "source_file": "",
            "source_sha256": "",
            "transfer_concession_status": "not_modelled_ignored_for_v1",
            "eligibility_status": "not_modelled_generic_passenger_assumed",
            "temporal_status": (
                "source_snapshot_applied_without_route_specific_effective_date"
            ),
            "unresolved_reason": "",
        }
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--rules",
        type=Path,
        default=BASE / "bus_simulation_fare_rules.parquet",
    )
    parser.add_argument(
        "--route-fallbacks",
        type=Path,
        default=BASE / "bus_route_fallback_fares.csv",
    )
    args = parser.parse_args()
    requests = pd.read_csv(args.input, dtype=str, keep_default_na=False)
    route_ids = sorted(
        {value for value in requests.get("matsim_route_id", []) if value}
    )
    filters = [("matsim_route_id", "in", route_ids)] if route_ids else None
    rules = pd.read_parquet(args.rules, filters=filters).fillna("")
    fallbacks = pd.read_csv(
        args.route_fallbacks, dtype=str, keep_default_na=False
    )
    rule_columns = [
        "matsim_line_id",
        "matsim_route_id",
        "official_route_id",
        "official_direction",
        "boarding_stop_id",
        "alighting_stop_id",
    ]
    rule_lookup = {
        tuple(str(row[column]) for column in rule_columns): row
        for row in rules.to_dict("records")
    }
    fallback_lookup = fallbacks.set_index("matsim_route_id").to_dict("index")
    outputs: list[dict[str, Any]] = []
    for request in requests.to_dict("records"):
        output = output_base(request)
        route_id = request.get("matsim_route_id", "")
        fallback = fallback_lookup.get(route_id)
        if request.get("actual_transport_mode") != "bus":
            output["unresolved_reason"] = "actual_transport_mode_not_bus"
            output["anomaly_reason"] = "unknown_or_inapplicable_route"
            outputs.append(output)
            continue
        if fallback is None:
            output["unresolved_reason"] = "unknown_matsim_bus_route"
            output["anomaly_reason"] = "unknown_route_has_no_simulation_fallback"
            outputs.append(output)
            continue
        key = (
            request.get("matsim_line_id", ""),
            route_id,
            request.get("official_route_id", ""),
            request.get("official_direction", ""),
            request.get("boarding_stop_id", ""),
            request.get("alighting_stop_id", ""),
        )
        rule = rule_lookup.get(key)
        if rule is not None:
            output.update(
                {
                    "official_published_fare_hkd": (
                        None
                        if rule["official_published_fare_hkd"] == ""
                        else float(rule["official_published_fare_hkd"])
                    ),
                    "model_fare_hkd": float(rule["model_fare_hkd"]),
                    "cost_hkd": float(rule["cost_hkd"]),
                    "currency": rule["currency"],
                    "fare_resolution_status": rule["fare_resolution_status"],
                    "fare_resolution_method": rule["fare_resolution_method"],
                    "cost_quality": rule["cost_quality"],
                    "anomaly_flag": bool(rule["anomaly_flag"]),
                    "anomaly_severity": rule["anomaly_severity"],
                    "anomaly_reason": rule["anomaly_reason"],
                    "audit_priority": int(rule["audit_priority"]),
                    "fallback_used": False,
                    "candidate_values_hkd_json": rule[
                        "candidate_values_hkd_json"
                    ],
                    "selection_rationale": rule["selection_rationale"],
                    "source_record_ids_json": rule[
                        "source_record_ids_json"
                    ],
                    "source_file": rule["source_file"],
                    "source_sha256": rule["source_sha256"],
                    "unresolved_reason": "",
                }
            )
        else:
            reasons: list[str] = []
            if request.get("matsim_line_id") != fallback["matsim_line_id"]:
                reasons.append("request_line_does_not_match_known_route")
            if request.get("official_route_id") != fallback["official_route_id"]:
                reasons.append("request_official_route_does_not_match_known_route")
            if request.get("official_direction") != fallback["official_direction"]:
                reasons.append("request_direction_not_exact_for_known_route")
            reasons.append("exact_ordered_OD_not_available_route_fallback_used")
            output.update(
                {
                    "official_published_fare_hkd": None,
                    "model_fare_hkd": float(fallback["route_fallback_fare_hkd"]),
                    "cost_hkd": float(fallback["route_fallback_fare_hkd"]),
                    "currency": "HKD",
                    "fare_resolution_status": "route_fallback",
                    "fare_resolution_method": fallback[
                        "fare_resolution_method"
                    ],
                    "cost_quality": "D",
                    "anomaly_flag": True,
                    "anomaly_severity": "high",
                    "anomaly_reason": (
                        "route_level_fallback_for_simulation_coverage;"
                        + ";".join(reasons)
                    ),
                    "audit_priority": 5,
                    "fallback_used": True,
                    "candidate_values_hkd_json": fallback[
                        "fallback_reference_values_hkd_json"
                    ],
                    "selection_rationale": fallback["selection_rationale"],
                    "source_record_ids_json": fallback[
                        "source_record_ids_json"
                    ],
                    "source_file": fallback["source_file"],
                    "source_sha256": fallback["source_sha256"],
                    "unresolved_reason": "",
                }
            )
        outputs.append(output)
    result = pd.DataFrame(outputs, columns=OUTPUT_COLUMNS)
    result.to_csv(args.output, index=False, encoding="utf-8", lineterminator="\n")
    print(f"Wrote {len(result):,} bus simulation fare quotes to {args.output}")


if __name__ == "__main__":
    main()
