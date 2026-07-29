#!/usr/bin/env python3
"""Quote strict snapshot-only Hong Kong franchised-bus published amounts."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pandas as pd


BASE = Path("data/transport_costs/hongkong/pt_fare_v1/bus_fare_v1")
OUTPUT_COLUMNS = [
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
    "route_franchise_scope_status",
    "unresolved_reason",
    "transfer_concession_hkd",
    "transfer_concession_status",
]


def blank_output(request: dict[str, str]) -> dict[str, Any]:
    output = {column: request.get(column, "") for column in OUTPUT_COLUMNS}
    output.update(
        {
            "cost_component": "pt_fare",
            "fare_amount_role": "",
            "published_fare_hkd": None,
            "cost_hkd": None,
            "cost_source": "",
            "cost_effective_date": "",
            "cost_effective_date_status": "not_encoded_in_source_revision_cutoff_only",
            "source_revision_cutoff_date": "2026-07-14",
            "source_download_date": "2026-07-20",
            "cost_quality": "U",
            "mapping_status": "unresolved",
            "mapping_quality": "U",
            "cost_applicability_status": "not_applicable_unresolved_request",
            "source_record_id": "",
            "source_record_ids_json": "[]",
            "route_franchise_scope_status": "",
            "unresolved_reason": "",
            "transfer_concession_hkd": None,
            "transfer_concession_status": "not_modelled",
        }
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rules", type=Path, default=BASE / "bus_fare_rules.parquet")
    parser.add_argument(
        "--unresolved",
        type=Path,
        default=BASE / "bus_unresolved_fare_rules.parquet",
    )
    parser.add_argument(
        "--readiness",
        type=Path,
        default=BASE / "bus_route_direction_fare_readiness.csv",
    )
    parser.add_argument(
        "--full-fare-reference",
        type=Path,
        default=BASE / "bus_route_full_fare_reference.csv",
    )
    args = parser.parse_args()
    requests = pd.read_csv(args.input, dtype=str, keep_default_na=False)
    route_ids = sorted(
        {value for value in requests.get("matsim_route_id", []) if value}
    )
    filters = [("matsim_route_id", "in", route_ids)] if route_ids else None
    rules = pd.read_parquet(args.rules, filters=filters).fillna("")
    unresolved = pd.read_parquet(args.unresolved, filters=filters).fillna("")
    readiness = pd.read_csv(args.readiness, dtype=str, keep_default_na=False)
    full_refs = pd.read_csv(
        args.full_fare_reference, dtype=str, keep_default_na=False
    )
    readiness_lookup = readiness.set_index("matsim_route_id").to_dict("index")
    rule_lookup = {
        (
            row["matsim_line_id"],
            row["matsim_route_id"],
            row["official_route_id"],
            row["official_direction"],
            row["boarding_stop_id"],
            row["alighting_stop_id"],
        ): row
        for row in rules.to_dict("records")
    }
    unresolved_lookup = {
        (
            row["matsim_line_id"],
            row["matsim_route_id"],
            row["official_route_id"],
            row["official_direction"],
            row["boarding_stop_id"],
            row["alighting_stop_id"],
        ): row
        for row in unresolved.to_dict("records")
    }
    full_routes = set(full_refs["official_route_id"])
    outputs: list[dict[str, Any]] = []
    for request in requests.to_dict("records"):
        output = blank_output(request)
        mode = request.get("actual_transport_mode", "")
        route_id = request.get("matsim_route_id", "")
        route_meta = readiness_lookup.get(route_id)
        if mode != "bus":
            reason = "actual_transport_mode_must_be_bus"
        elif not request.get("matsim_line_id"):
            reason = "missing_required_matsim_line_id"
        elif not route_id:
            reason = "missing_required_matsim_route_id"
        elif route_meta is None:
            reason = "unknown_matsim_route_id"
        elif request["matsim_line_id"] != route_meta["matsim_line_id"]:
            reason = "matsim_line_route_combination_mismatch"
        elif route_meta["route_franchise_scope_status"] != "confirmed_franchised_route":
            reason = (
                "route_scope_unresolved_no_official_direction_or_stop_pair"
                if route_meta["route_franchise_scope_status"]
                == "operator_scope_unresolved"
                else route_meta["route_franchise_scope_status"]
            )
        elif not request.get("official_route_id"):
            reason = "missing_required_official_route_id"
        elif request["official_route_id"] != route_meta["official_route_id"]:
            reason = "official_route_id_mismatch"
        elif not request.get("official_direction"):
            reason = "missing_required_official_direction"
        elif request["official_direction"] in ("unspecified", "unspecified_in_source"):
            reason = "official_direction_must_be_exact"
        elif request["official_direction"] != route_meta["official_route_sequence"]:
            reason = "official_direction_mismatch"
        elif not request.get("boarding_stop_id"):
            reason = "missing_required_boarding_stop_id"
        elif not request.get("alighting_stop_id"):
            reason = "missing_required_alighting_stop_id"
        elif request.get("travel_date"):
            reason = "fare_effective_period_not_encoded_for_travel_date"
        elif request.get("temporal_basis") != "source_snapshot_only":
            reason = "temporal_basis_must_be_source_snapshot_only"
        elif request.get("passenger_type") != "unspecified":
            reason = "passenger_type_not_proven_by_source"
        elif request.get("payment_medium") != "unspecified":
            reason = "payment_medium_not_proven_by_source"
        elif request.get("service_class") != "unspecified":
            reason = "service_class_not_proven_by_source"
        elif request.get("day_type") != "unspecified":
            reason = "day_type_not_proven_by_source"
        elif request.get("time_period") != "unspecified":
            reason = "time_period_not_proven_by_source"
        elif request.get("transfer_concession_requested", "").lower() != "false":
            reason = "transfer_concession_not_modelled_request_rejected"
        else:
            key = (
                request["matsim_line_id"],
                route_id,
                request["official_route_id"],
                request["official_direction"],
                request["boarding_stop_id"],
                request["alighting_stop_id"],
            )
            rule = rule_lookup.get(key)
            excluded = unresolved_lookup.get(key)
            if rule is not None:
                output.update(
                    {
                        "fare_amount_role": rule["fare_amount_role"],
                        "published_fare_hkd": float(rule["published_fare_hkd"]),
                        "cost_hkd": float(rule["published_fare_hkd"]),
                        "cost_source": rule["cost_source"],
                        "cost_effective_date": "",
                        "cost_effective_date_status": rule[
                            "cost_effective_date_status"
                        ],
                        "source_revision_cutoff_date": rule[
                            "source_revision_cutoff_date"
                        ],
                        "source_download_date": rule["source_download_date"],
                        "cost_quality": "B",
                        "mapping_status": "exact",
                        "mapping_quality": "A",
                        "cost_applicability_status": rule[
                            "cost_applicability_status"
                        ],
                        "source_record_id": rule["source_record_id"],
                        "source_record_ids_json": rule["source_record_ids_json"],
                        "route_franchise_scope_status": (
                            "confirmed_franchised_route"
                        ),
                        "unresolved_reason": "",
                    }
                )
                outputs.append(output)
                continue
            if excluded is not None:
                reason = excluded["exclusion_reason"]
                output["route_franchise_scope_status"] = excluded[
                    "route_franchise_scope_status"
                ]
            elif (
                request["boarding_stop_id"] == request["alighting_stop_id"]
                and request["official_route_id"] in full_routes
            ):
                reason = "fullfare_fallback_prohibited"
            else:
                route_rules = pd.concat(
                    [
                        rules[rules["matsim_route_id"] == route_id],
                        unresolved[unresolved["matsim_route_id"] == route_id],
                    ],
                    ignore_index=True,
                )
                known_stops = set(route_rules["boarding_stop_id"]) | set(
                    route_rules["alighting_stop_id"]
                )
                if request["boarding_stop_id"] not in known_stops:
                    reason = "boarding_stop_not_in_route"
                elif request["alighting_stop_id"] not in known_stops:
                    reason = "alighting_stop_not_in_route"
                else:
                    reason = "ordered_stop_pair_not_available_no_reverse_fallback"
        output["unresolved_reason"] = reason
        if route_meta is not None:
            output["route_franchise_scope_status"] = route_meta[
                "route_franchise_scope_status"
            ]
        outputs.append(output)
    result = pd.DataFrame(outputs, columns=OUTPUT_COLUMNS)
    result.to_csv(args.output, index=False, encoding="utf-8", lineterminator="\n")
    print(f"Wrote {len(result):,} bus fare quote results to {args.output}")


if __name__ == "__main__":
    main()
