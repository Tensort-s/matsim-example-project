#!/usr/bin/env python3
"""Build coverage-first Hong Kong bus simulation fares v1."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import statistics
from collections import Counter
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import pandas as pd


BASE_REL = Path("data/transport_costs/hongkong/pt_fare_v1")
AUDIT_REL = BASE_REL / "bus_scope_direction_audit_v1"
CORE_REL = BASE_REL / "bus_fare_v1"
OUTPUT_REL = BASE_REL / "bus_fare_simulation_v1"
SCHEDULE_REL = Path(
    "data/transit/hongkong/processed/"
    "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_"
    "ferry_core_v1_cap010/transitSchedule_5pct.xml.gz"
)
NETWORK_REL = SCHEDULE_REL.parent / "network.xml.gz"
EXPECTED_PAIRS = 771_666
EXPECTED_ROUTES = 2_363

RULE_COLUMNS = [
    "fare_scope",
    "matsim_line_id",
    "matsim_route_id",
    "official_operator",
    "operator_scope_status",
    "route_franchise_scope_status",
    "official_route_id",
    "official_route_sequence",
    "official_direction",
    "boarding_stop_id",
    "alighting_stop_id",
    "official_published_fare_hkd",
    "model_fare_hkd",
    "cost_hkd",
    "currency",
    "fare_resolution_status",
    "fare_resolution_method",
    "official_value_available",
    "model_assumption_used",
    "cost_quality",
    "anomaly_flag",
    "anomaly_severity",
    "anomaly_reason",
    "audit_priority",
    "zero_is_explicit_raw_record",
    "candidate_values_hkd_json",
    "candidate_record_count",
    "candidate_min_hkd",
    "candidate_max_hkd",
    "candidate_spread_hkd",
    "selected_candidate_hkd",
    "selection_rationale",
    "source_record_ids_json",
    "source_file",
    "source_sha256",
    "candidate_records_json",
    "source_revision_cutoff_date",
    "source_download_date",
    "cost_effective_date",
    "cost_effective_date_status",
    "passenger_type",
    "payment_medium",
    "service_class",
    "day_type",
    "time_period",
    "transfer_concession_status",
    "eligibility_status",
    "temporal_status",
]


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


def nearest_existing_median(values: list[float]) -> tuple[float, float]:
    distinct = sorted(set(float(value) for value in values))
    position = float(statistics.median(distinct))
    selected = min(distinct, key=lambda value: (abs(value - position), -value))
    return selected, position


def read_schedule_routes(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rb") as handle:
        root = ET.parse(handle).getroot()
    routes: list[dict[str, Any]] = []
    for line in root:
        if local_name(line.tag) != "transitLine":
            continue
        for route in line:
            if local_name(route.tag) != "transitRoute":
                continue
            mode = ""
            stop_count = 0
            link_ids: list[str] = []
            for child in route:
                tag = local_name(child.tag)
                if tag == "transportMode":
                    mode = (child.text or "").strip()
                elif tag == "routeProfile":
                    stop_count = sum(
                        local_name(item.tag) == "stop" for item in child
                    )
                elif tag == "route":
                    link_ids = [
                        item.attrib["refId"]
                        for item in child
                        if local_name(item.tag) == "link"
                    ]
            if mode == "bus":
                routes.append(
                    {
                        "matsim_line_id": line.attrib["id"],
                        "matsim_route_id": route.attrib["id"],
                        "stop_count": stop_count,
                        "link_ids": link_ids,
                    }
                )
    return sorted(routes, key=lambda row: row["matsim_route_id"])


def read_link_lengths(path: Path, required: set[str]) -> dict[str, float]:
    lengths: dict[str, float] = {}
    with gzip.open(path, "rb") as handle:
        for _, element in ET.iterparse(handle, events=("end",)):
            if local_name(element.tag) == "link":
                link_id = element.attrib.get("id", "")
                if link_id in required:
                    lengths[link_id] = float(element.attrib["length"])
            element.clear()
    missing = required - set(lengths)
    if missing:
        raise RuntimeError(f"Network lacks {len(missing)} scheduled bus links")
    return lengths


def conflict_selection(
    row: dict[str, Any],
    records: list[dict[str, Any]],
    full_fare_lookup: dict[tuple[str, str, str], dict[str, Any]],
) -> tuple[float, str, str]:
    values = [float(record["price"]) for record in records]
    distinct = sorted(set(values))
    full = full_fare_lookup.get(
        (
            row["official_operator"],
            str(row["official_route_id"]),
            str(row["official_route_sequence"]),
        )
    )
    if full:
        pattern = json.loads(full["official_stop_pattern_json"])
        full_value = float(full["full_fare_hkd"])
        if (
            pattern
            and row["boarding_stop_id"] == pattern[0]
            and row["alighting_stop_id"] == pattern[-1]
            and sum(value == full_value for value in distinct) == 1
        ):
            return (
                full_value,
                "terminal_OD_candidate_matching_JSON_fullFare",
                (
                    "terminal ordered OD; exactly one distinct raw candidate "
                    f"equals JSON fullFare {full_value:g}"
                ),
            )
    frequencies = Counter(values)
    maximum = max(frequencies.values())
    modes = sorted(value for value, count in frequencies.items() if count == maximum)
    if len(modes) == 1:
        selected = modes[0]
        return (
            selected,
            "modal_raw_official_candidate_amount",
            (
                f"unique raw-candidate mode {selected:g} occurs {maximum} times; "
                f"frequencies={compact_json(dict(sorted(frequencies.items())))}"
            ),
        )
    selected, position = nearest_existing_median(distinct)
    return (
        selected,
        "median_nearest_existing_candidate_tie_higher",
        (
            f"modal frequency tied at {maximum}; distinct-value median position "
            f"{position:g}; selected nearest existing candidate {selected:g}, "
            "with higher amount used for an equal-distance tie"
        ),
    )


def simulation_rule(
    row: dict[str, Any],
    core_lookup: dict[tuple[str, ...], dict[str, Any]],
    full_fare_lookup: dict[tuple[str, str, str], dict[str, Any]],
) -> dict[str, Any]:
    records = json.loads(row["candidate_records_json"])
    values = [float(record["price"]) for record in records]
    distinct = sorted(set(values))
    scope = row["route_franchise_scope_status"]
    status = row["record_status"]
    key = (
        row["matsim_line_id"],
        row["matsim_route_id"],
        row["official_route_id"],
        row["official_direction"],
        row["boarding_stop_id"],
        row["alighting_stop_id"],
    )
    official: float | None = None
    assumption = True
    anomaly = True
    severity = ""
    reason = ""
    priority = 0
    if (
        scope == "confirmed_franchised_route"
        and status == "unique_candidate"
        and key in core_lookup
    ):
        selected = float(core_lookup[key]["published_fare_hkd"])
        if selected != values[0]:
            raise RuntimeError("Bus Core active amount differs from raw audit candidate")
        official = selected
        resolution_status = "official_unique"
        method = "direct_unique_gtfs_ordered_od"
        assumption = False
        quality = "B"
        anomaly = False
        rationale = "exact Bus Core v1 active rule and unique raw GTFS ordered OD"
    elif status == "duplicate_identical":
        if len(distinct) != 1 or len(records) < 2:
            raise RuntimeError("Duplicate-consensus row is not an identical duplicate")
        selected = distinct[0]
        resolution_status = "official_duplicate_consensus"
        method = "identical_raw_candidate_consensus"
        quality = "C"
        severity = "low"
        reason = "duplicate_identical_records_collapsed_for_simulation"
        priority = 1
        rationale = (
            f"all {len(records)} raw official candidate records equal "
            f"{selected:g}; no record-order selection"
        )
    elif scope == "other_bus_service" and status == "unique_candidate":
        selected = values[0]
        official = selected
        resolution_status = "official_unique_scope_relaxed"
        method = "direct_unique_gtfs_ordered_od_other_bus_scope"
        quality = "B"
        severity = "medium"
        reason = (
            "other_bus_service_included_for_coverage_without_eligibility_modelling"
        )
        priority = 2
        rationale = (
            "unique raw GTFS ordered OD used for another officially identified "
            "bus service without passenger eligibility modelling"
        )
    elif (
        scope == "franchise_route_scope_unresolved"
        and status == "unique_candidate"
    ):
        selected = values[0]
        official = selected
        resolution_status = "official_unique_scope_relaxed"
        method = (
            "direct_unique_gtfs_ordered_od_route_scope_unresolved"
        )
        quality = "C"
        severity = "medium"
        reason = "exact_GTFS_OD_used_despite_missing_CSDI_route_scope_key"
        priority = 2
        rationale = (
            "unique raw GTFS ordered OD and exact JSON direction used despite "
            "the missing exact CSDI route-scope key"
        )
    elif status == "conflicting_amounts":
        selected, method, rationale = conflict_selection(
            row, records, full_fare_lookup
        )
        official = None
        resolution_status = "official_conflict_candidate_selected"
        quality = "D"
        severity = "high"
        reason = "conflicting_official_amounts_resolved_for_simulation"
        priority = 4
    else:
        raise RuntimeError(
            f"Unimplemented simulation resolution: scope={scope}, status={status}"
        )
    explicit_zero = selected == 0
    if explicit_zero:
        if not values or any(value != 0 for value in values):
            raise RuntimeError("A zero simulation fare was not supported by all records")
        anomaly = True
        severity = "medium" if severity in {"", "low"} else severity
        reason = (
            f"{reason};explicit_raw_zero_fare" if reason else "explicit_raw_zero_fare"
        )
        priority = 3
    if selected not in values:
        raise RuntimeError("Selected fare is outside the raw candidate set")
    return {
        "fare_scope": "bus_simulation_coverage_ordered_stop_od",
        "matsim_line_id": row["matsim_line_id"],
        "matsim_route_id": row["matsim_route_id"],
        "official_operator": row["official_operator"],
        "operator_scope_status": row["operator_scope_status"],
        "route_franchise_scope_status": scope,
        "official_route_id": row["official_route_id"],
        "official_route_sequence": row["official_route_sequence"],
        "official_direction": row["official_direction"],
        "boarding_stop_id": row["boarding_stop_id"],
        "alighting_stop_id": row["alighting_stop_id"],
        "official_published_fare_hkd": official,
        "model_fare_hkd": selected,
        "cost_hkd": selected,
        "currency": "HKD",
        "fare_resolution_status": resolution_status,
        "fare_resolution_method": method,
        "official_value_available": official is not None,
        "model_assumption_used": assumption,
        "cost_quality": quality,
        "anomaly_flag": anomaly,
        "anomaly_severity": severity,
        "anomaly_reason": reason,
        "audit_priority": priority,
        "zero_is_explicit_raw_record": explicit_zero,
        "candidate_values_hkd_json": compact_json(distinct),
        "candidate_record_count": len(records),
        "candidate_min_hkd": min(values),
        "candidate_max_hkd": max(values),
        "candidate_spread_hkd": max(values) - min(values),
        "selected_candidate_hkd": selected,
        "selection_rationale": rationale,
        "source_record_ids_json": row["candidate_record_ids_json"],
        "source_file": row["source_file"],
        "source_sha256": row["source_sha256"],
        "candidate_records_json": row["candidate_records_json"],
        "source_revision_cutoff_date": row["source_revision_cutoff_date"],
        "source_download_date": row["source_download_date"],
        "cost_effective_date": "",
        "cost_effective_date_status": row["cost_effective_date_status"],
        "passenger_type": "generic_passenger_assumed_for_simulation",
        "payment_medium": "unspecified_ignored_for_simulation",
        "service_class": "unspecified_ignored_for_simulation",
        "day_type": "unspecified_ignored_for_simulation",
        "time_period": "unspecified_ignored_for_simulation",
        "transfer_concession_status": "not_modelled_ignored_for_v1",
        "eligibility_status": "not_modelled_generic_passenger_assumed",
        "temporal_status": (
            "source_snapshot_applied_without_route_specific_effective_date"
        ),
    }


def route_representative_values(rules: pd.DataFrame) -> dict[str, float]:
    result: dict[str, float] = {}
    for route_id, group in rules[rules["model_fare_hkd"] > 0].groupby(
        "matsim_route_id", sort=True
    ):
        selected, _ = nearest_existing_median(group["model_fare_hkd"].tolist())
        result[str(route_id)] = selected
    return result


def cohort(
    target: dict[str, Any],
    candidates: list[dict[str, Any]],
    representative: dict[str, float],
    limit: int = 25,
) -> list[dict[str, Any]]:
    scored: list[tuple[float, str, dict[str, Any]]] = []
    target_distance = max(float(target["route_distance_m"]), 1.0)
    target_stops = max(int(target["stop_count"]), 1)
    for candidate in candidates:
        route_id = candidate["matsim_route_id"]
        if route_id == target["matsim_route_id"] or route_id not in representative:
            continue
        candidate_distance = max(float(candidate["route_distance_m"]), 1.0)
        score = abs(math.log(candidate_distance / target_distance)) + (
            abs(int(candidate["stop_count"]) - target_stops) / target_stops
        )
        scored.append((score, route_id, candidate))
    return [item[2] for item in sorted(scored)[:limit]]


def build_fallbacks(
    route_rows: list[dict[str, Any]],
    rules: pd.DataFrame,
    full_fares: pd.DataFrame,
    source_hashes: dict[str, str],
) -> pd.DataFrame:
    full_lookup = {
        (
            row["official_operator"],
            row["official_route_id"],
            row["official_route_sequence"],
        ): row
        for row in full_fares.to_dict("records")
    }
    representative = route_representative_values(rules)
    nonzero_by_route = {
        route_id: sorted(set(group["model_fare_hkd"].astype(float)))
        for route_id, group in rules[rules["model_fare_hkd"] > 0].groupby(
            "matsim_route_id", sort=True
        )
    }
    rows_by_official_direction: dict[tuple[str, str], list[float]] = {}
    rows_by_official: dict[str, list[float]] = {}
    for (official, sequence), group in rules[rules["model_fare_hkd"] > 0].groupby(
        ["official_route_id", "official_route_sequence"], sort=True
    ):
        rows_by_official_direction[(str(official), str(sequence))] = sorted(
            set(group["model_fare_hkd"].astype(float))
        )
    for official, group in rules[rules["model_fare_hkd"] > 0].groupby(
        "official_route_id", sort=True
    ):
        rows_by_official[str(official)] = sorted(
            set(group["model_fare_hkd"].astype(float))
        )
    route_lookup = {row["matsim_route_id"]: row for row in route_rows}
    output: list[dict[str, Any]] = []
    for route in route_rows:
        key = (
            route["official_operator"],
            route["official_route_id"],
            route["official_route_sequence"],
        )
        full = full_lookup.get(key)
        references: list[float]
        reference_routes: list[str]
        if full is not None and float(full["full_fare_hkd"]) > 0:
            references = [float(full["full_fare_hkd"])]
            reference_routes = [route["matsim_route_id"]]
            selected = references[0]
            level = 1
            method = "exact_json_route_direction_fullFare"
            rationale = (
                "exact official operator + routeId + routeSeq JSON fullFare "
                "used only as a route-level simulation fallback"
            )
            source_file = full["source_file"]
            source_sha = full["source_sha256"]
            source_ids = compact_json([full["source_record_id"]])
        elif (
            route["official_route_id"],
            route["official_route_sequence"],
        ) in rows_by_official_direction:
            references = rows_by_official_direction[
                (route["official_route_id"], route["official_route_sequence"])
            ]
            reference_routes = sorted(
                set(
                    rules.loc[
                        (rules["official_route_id"] == route["official_route_id"])
                        & (
                            rules["official_route_sequence"]
                            == route["official_route_sequence"]
                        ),
                        "matsim_route_id",
                    ]
                )
            )
            selected, position = nearest_existing_median(references)
            level = 2
            method = "same_route_direction_nonzero_od_median_nearest_existing"
            rationale = (
                f"nonzero same-route-direction OD median position {position:g}; "
                f"nearest actual value {selected:g}, tie higher"
            )
            source_file = (
                "data/transport_costs/hongkong/pt_fare_v1/"
                "bus_fare_simulation_v1/bus_simulation_fare_rules.parquet"
            )
            source_sha = source_hashes["gtfs"]
            source_ids = "[]"
        elif route["official_route_id"] in rows_by_official:
            references = rows_by_official[route["official_route_id"]]
            reference_routes = sorted(
                set(
                    rules.loc[
                        rules["official_route_id"] == route["official_route_id"],
                        "matsim_route_id",
                    ]
                )
            )
            selected, position = nearest_existing_median(references)
            level = 3
            method = "same_official_route_nonzero_od_median_nearest_existing"
            rationale = (
                f"nonzero all-direction official-route median position {position:g}; "
                f"nearest actual value {selected:g}, tie higher"
            )
            source_file = (
                "data/transport_costs/hongkong/pt_fare_v1/"
                "bus_fare_simulation_v1/bus_simulation_fare_rules.parquet"
            )
            source_sha = source_hashes["gtfs"]
            source_ids = "[]"
        else:
            same_operator = [
                candidate
                for candidate in route_rows
                if route["official_operator"]
                and candidate["official_operator"] == route["official_operator"]
            ]
            references_rows = cohort(
                route, same_operator, representative
            )
            if references_rows:
                level = 4
                method = (
                    "same_operator_distance_stop_cohort_median_nearest_existing"
                )
            else:
                references_rows = cohort(route, route_rows, representative)
                level = 5
                method = (
                    "all_bus_distance_stop_cohort_median_nearest_existing"
                )
            if not references_rows:
                raise RuntimeError(f"No route fallback cohort for {route['matsim_route_id']}")
            reference_routes = [
                candidate["matsim_route_id"] for candidate in references_rows
            ]
            references = [
                representative[candidate["matsim_route_id"]]
                for candidate in references_rows
            ]
            selected, position = nearest_existing_median(references)
            rationale = (
                f"level {level} similarity cohort of {len(references)} routes; "
                f"nonzero route-representative median position {position:g}; "
                f"nearest actual reference value {selected:g}, tie higher"
            )
            source_file = (
                "data/transport_costs/hongkong/pt_fare_v1/"
                "bus_fare_simulation_v1/bus_simulation_fare_rules.parquet;"
                f"{SCHEDULE_REL.as_posix()};{NETWORK_REL.as_posix()}"
            )
            source_sha = compact_json(
                {
                    "gtfs": source_hashes["gtfs"],
                    "network": source_hashes["network"],
                    "schedule": source_hashes["schedule"],
                }
            )
            source_ids = "[]"
        if selected <= 0:
            direct = nonzero_by_route.get(route["matsim_route_id"], [])
            if direct or not route.get("all_direct_candidates_explicit_zero", False):
                raise RuntimeError("Route fallback produced a prohibited zero")
        output.append(
            {
                "matsim_line_id": route["matsim_line_id"],
                "matsim_route_id": route["matsim_route_id"],
                "official_operator": route["official_operator"],
                "official_route_id": route["official_route_id"],
                "official_route_sequence": route["official_route_sequence"],
                "official_direction": route["official_direction"],
                "route_franchise_scope_status": route[
                    "route_franchise_scope_status"
                ],
                "route_distance_m": route["route_distance_m"],
                "stop_count": route["stop_count"],
                "route_fallback_fare_hkd": selected,
                "fallback_level": level,
                "fare_resolution_status": "route_fallback",
                "fare_resolution_method": method,
                "fallback_reference_route_ids_json": compact_json(reference_routes),
                "fallback_reference_values_hkd_json": compact_json(references),
                "fallback_reference_count": len(references),
                "official_published_fare_hkd": None,
                "model_fare_hkd": selected,
                "cost_hkd": selected,
                "currency": "HKD",
                "cost_quality": "D",
                "model_assumption_used": True,
                "anomaly_flag": True,
                "anomaly_severity": "high",
                "anomaly_reason": "route_level_fallback_for_simulation_coverage",
                "audit_priority": 5,
                "selection_rationale": rationale,
                "source_record_ids_json": source_ids,
                "source_file": source_file,
                "source_sha256": source_sha,
            }
        )
    return pd.DataFrame(output)


def fixture_rows(rules: pd.DataFrame, fallbacks: pd.DataFrame) -> pd.DataFrame:
    def request(
        quote_id: str,
        row: dict[str, Any],
        expected: str = "available",
        expected_fallback: bool = False,
        **overrides: Any,
    ) -> dict[str, Any]:
        result = {
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
            "travel_date": "",
            "transfer_concession_requested": "false",
            "expected_result": expected,
            "expected_fallback_used": str(expected_fallback).lower(),
            "expected_resolution_method": row.get("fare_resolution_method", ""),
        }
        result.update(overrides)
        return result

    def first(**conditions: str) -> dict[str, Any]:
        selected = rules
        for column, value in conditions.items():
            selected = selected[selected[column] == value]
        return selected.iloc[0].to_dict()

    official = rules[
        (rules["fare_resolution_status"] == "official_unique")
        & (rules["model_fare_hkd"] > 0)
    ].iloc[0].to_dict()
    zero = rules[rules["model_fare_hkd"] == 0].iloc[0].to_dict()
    duplicate = first(
        route_franchise_scope_status="confirmed_franchised_route",
        fare_resolution_method="identical_raw_candidate_consensus",
    )
    modal = first(
        fare_resolution_method="modal_raw_official_candidate_amount"
    )
    median = first(
        fare_resolution_method="median_nearest_existing_candidate_tie_higher"
    )
    terminal = first(
        fare_resolution_method="terminal_OD_candidate_matching_JSON_fullFare"
    )
    scope_unique = first(
        fare_resolution_method=(
            "direct_unique_gtfs_ordered_od_route_scope_unresolved"
        )
    )
    scope_duplicate = rules[
        (rules["route_franchise_scope_status"] == "franchise_route_scope_unresolved")
        & (rules["fare_resolution_method"] == "identical_raw_candidate_consensus")
    ].iloc[0].to_dict()
    operator_rows = {
        operator: rules[
            (rules["official_operator"] == operator)
            & (
                rules["fare_resolution_method"]
                == "direct_unique_gtfs_ordered_od_other_bus_scope"
            )
        ].iloc[0].to_dict()
        for operator in ("LRTFeeder", "DB", "PI", "XB")
    }
    other_conflict = rules[
        (rules["route_franchise_scope_status"] == "other_bus_service")
        & (rules["fare_resolution_status"] == "official_conflict_candidate_selected")
    ].iloc[0].to_dict()
    unresolved_route = fallbacks[
        fallbacks["route_franchise_scope_status"] == "operator_scope_unresolved"
    ].iloc[0].to_dict()
    rows = [
        request("confirmed_official_unique", official),
        request("confirmed_official_zero", zero),
        request("confirmed_duplicate_consensus", duplicate),
        request("confirmed_conflict_unique_mode", modal),
        request("confirmed_conflict_median_tie_higher", median),
        request("terminal_OD_matching_JSON_fullFare", terminal),
        request("route_scope_unresolved_unique", scope_unique),
        request("route_scope_unresolved_duplicate", scope_duplicate),
        request("LRTFeeder_unique", operator_rows["LRTFeeder"]),
        request("DB_unique", operator_rows["DB"]),
        request("PI_unique", operator_rows["PI"]),
        request("XB_unique", operator_rows["XB"]),
        request("other_service_conflict", other_conflict),
        request(
            "known_operator_unresolved_route_fallback",
            unresolved_route,
            expected_fallback=True,
            boarding_stop_id="unknown_boarding",
            alighting_stop_id="unknown_alighting",
            expected_resolution_method=unresolved_route["fare_resolution_method"],
        ),
        request(
            "known_route_unknown_OD_fallback",
            official,
            expected_fallback=True,
            boarding_stop_id="unknown_boarding",
            alighting_stop_id="unknown_alighting",
            expected_resolution_method=fallbacks.set_index("matsim_route_id").loc[
                official["matsim_route_id"], "fare_resolution_method"
            ],
        ),
        request(
            "transfer_requested_returns_base",
            official,
            transfer_concession_requested="true",
        ),
        request(
            "specified_passenger_payment_returns_generic",
            official,
            passenger_type="adult",
            payment_medium="Octopus",
        ),
        request(
            "travel_date_returns_snapshot",
            official,
            travel_date="2026-07-20",
        ),
        request(
            "reverse_OD_uses_route_fallback",
            official,
            expected_fallback=True,
            boarding_stop_id=official["alighting_stop_id"],
            alighting_stop_id=official["boarding_stop_id"],
            expected_resolution_method=fallbacks.set_index("matsim_route_id").loc[
                official["matsim_route_id"], "fare_resolution_method"
            ],
        ),
        request(
            "unknown_route_unresolved",
            {},
            expected="unresolved",
            matsim_line_id="line_bus_unknown",
            matsim_route_id="bus_unknown_1",
            official_route_id="unknown",
            official_direction="1",
            boarding_stop_id="a",
            alighting_stop_id="b",
        ),
    ]
    return pd.DataFrame(rows)


def protected_hashes(repo_root: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for scope in (
        "bus_scope_direction_audit_v1",
        "bus_fare_v1",
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


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, encoding="utf-8", lineterminator="\n")


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
    core_dir = repo_root / CORE_REL

    candidates = pd.read_parquet(
        audit_dir / "bus_od_fare_candidate_audit.parquet"
    ).fillna("")
    if len(candidates) != EXPECTED_PAIRS:
        raise RuntimeError("Bus required forward-pair universe changed")
    core = pd.read_parquet(core_dir / "bus_fare_rules.parquet").fillna("")
    core_key_columns = [
        "matsim_line_id",
        "matsim_route_id",
        "official_route_id",
        "official_direction",
        "boarding_stop_id",
        "alighting_stop_id",
    ]
    core_lookup = {
        tuple(str(row[column]) for column in core_key_columns): row
        for row in core.to_dict("records")
    }
    if len(core_lookup) != 754_133:
        raise RuntimeError("Protected Bus Core active universe changed")
    full_fares = pd.read_csv(
        audit_dir / "bus_route_full_fare_reference.csv",
        dtype=str,
        keep_default_na=False,
    )
    full_fare_lookup = {
        (
            row["official_operator"],
            row["official_route_id"],
            row["official_route_sequence"],
        ): row
        for row in full_fares.to_dict("records")
    }
    rules = pd.DataFrame(
        [
            simulation_rule(row, core_lookup, full_fare_lookup)
            for row in candidates.to_dict("records")
        ],
        columns=RULE_COLUMNS,
    )
    if (
        len(rules) != EXPECTED_PAIRS
        or rules["model_fare_hkd"].isna().any()
        or rules["cost_hkd"].isna().any()
        or not (rules["model_fare_hkd"] == rules["cost_hkd"]).all()
    ):
        raise RuntimeError("Simulation fare coverage is incomplete")
    key_columns = [
        "matsim_line_id",
        "matsim_route_id",
        "official_route_id",
        "official_direction",
        "boarding_stop_id",
        "alighting_stop_id",
    ]
    if rules.duplicated(key_columns).any():
        raise RuntimeError("Simulation fare primary key is not unique")

    schedule_rows = read_schedule_routes(source_root / SCHEDULE_REL)
    if len(schedule_rows) != EXPECTED_ROUTES:
        raise RuntimeError("Production schedule bus route count changed")
    required_links = {
        link_id for route in schedule_rows for link_id in route["link_ids"]
    }
    link_lengths = read_link_lengths(source_root / NETWORK_REL, required_links)
    readiness = pd.read_csv(
        audit_dir / "bus_route_direction_readiness.csv",
        dtype=str,
        keep_default_na=False,
    )
    readiness_lookup = readiness.set_index("matsim_route_id").to_dict("index")
    route_rows: list[dict[str, Any]] = []
    direct_zero_status = (
        rules.groupby("matsim_route_id")["model_fare_hkd"]
        .apply(lambda values: len(values) > 0 and (values == 0).all())
        .to_dict()
    )
    for scheduled in schedule_rows:
        meta = readiness_lookup[scheduled["matsim_route_id"]]
        route_rows.append(
            {
                **scheduled,
                "official_operator": meta["official_operator"],
                "official_route_id": meta["official_route_id"],
                "official_route_sequence": meta["official_route_sequence"],
                "official_direction": meta["official_route_sequence"],
                "route_franchise_scope_status": meta[
                    "route_franchise_scope_status"
                ],
                "route_distance_m": sum(
                    link_lengths[link_id] for link_id in scheduled["link_ids"]
                ),
                "all_direct_candidates_explicit_zero": direct_zero_status.get(
                    scheduled["matsim_route_id"], False
                ),
            }
        )
    source_hashes = {
        "gtfs": json.loads(
            (audit_dir / "bus_scope_direction_summary.json").read_text(
                encoding="utf-8"
            )
        )["source_sha256"]["gtfs"],
        "schedule": sha256(source_root / SCHEDULE_REL),
        "network": sha256(source_root / NETWORK_REL),
    }
    fallbacks = build_fallbacks(route_rows, rules, full_fares, source_hashes)
    if (
        len(fallbacks) != EXPECTED_ROUTES
        or fallbacks["route_fallback_fare_hkd"].isna().any()
        or (fallbacks["route_fallback_fare_hkd"] <= 0).any()
    ):
        raise RuntimeError("Route fallback coverage is incomplete")

    rules.to_parquet(
        output_dir / "bus_simulation_fare_rules.parquet",
        index=False,
        engine="pyarrow",
        compression="zstd",
    )
    write_csv(rules.head(100), output_dir / "bus_simulation_fare_rules_sample.csv")
    write_csv(fallbacks, output_dir / "bus_route_fallback_fares.csv")

    rule_anomalies = rules[rules["anomaly_flag"]].copy().astype(object)
    rule_anomalies.insert(0, "record_scope", "ordered_stop_od")
    fallback_anomalies = fallbacks.copy().astype(object)
    fallback_anomalies.insert(0, "record_scope", "route_fallback")
    anomalies = pd.concat(
        [rule_anomalies, fallback_anomalies], ignore_index=True, sort=False
    )
    anomalies.to_parquet(
        output_dir / "bus_simulation_fare_anomalies.parquet",
        index=False,
        engine="pyarrow",
        compression="zstd",
    )
    sample = (
        anomalies.sort_values(["record_scope", "audit_priority", "matsim_route_id"])
        .groupby(["record_scope", "audit_priority"], sort=True)
        .head(20)
    )
    write_csv(
        sample, output_dir / "bus_simulation_fare_anomalies_sample.csv"
    )

    method_summary = (
        rules.groupby(
            ["fare_resolution_status", "fare_resolution_method", "cost_quality"],
            dropna=False,
        )
        .size()
        .reset_index(name="rule_count")
    )
    quality_summary = (
        rules.groupby("cost_quality").size().reset_index(name="rule_count")
    )
    write_csv(
        method_summary, output_dir / "bus_fare_resolution_method_summary.csv"
    )
    write_csv(
        quality_summary, output_dir / "bus_fare_resolution_quality_summary.csv"
    )

    fixture = fixture_rows(rules, fallbacks)
    write_csv(fixture, output_dir / "bus_simulation_query_fixture_input.csv")
    write_csv(pd.DataFrame(), output_dir / "bus_simulation_query_fixture_output.csv")
    method_counts = dict(Counter(rules["fare_resolution_method"]))
    quality_counts = dict(Counter(rules["cost_quality"]))
    priority_counts = {
        str(key): int(value)
        for key, value in sorted(Counter(rules["audit_priority"]).items())
    }
    anomaly_priority_counts = {
        str(key): int(value)
        for key, value in sorted(Counter(anomalies["audit_priority"]).items())
    }
    summary = {
        "schema_version": "hong_kong_bus_simulation_fare_v1",
        "required_forward_pair_count": len(rules),
        "non_null_model_fare_count": int(rules["model_fare_hkd"].notna().sum()),
        "model_fare_coverage": float(rules["model_fare_hkd"].notna().mean()),
        "route_fallback_count": len(fallbacks),
        "route_fallback_coverage": len(fallbacks) / EXPECTED_ROUTES,
        "quality_counts": quality_counts,
        "resolution_method_counts": method_counts,
        "resolution_status_counts": dict(Counter(rules["fare_resolution_status"])),
        "audit_priority_counts": priority_counts,
        "ordered_od_anomaly_count": len(rule_anomalies),
        "anomaly_table_count_including_route_fallbacks": len(anomalies),
        "anomaly_priority_counts": anomaly_priority_counts,
        "explicit_zero_rule_count": int((rules["model_fare_hkd"] == 0).sum()),
        "active_unique_zero_rule_count": int(
            (
                (rules["fare_resolution_status"] == "official_unique")
                & (rules["model_fare_hkd"] == 0)
            ).sum()
        ),
        "duplicate_consensus_zero_rule_count": int(
            (
                (
                    rules["fare_resolution_status"]
                    == "official_duplicate_consensus"
                )
                & (rules["model_fare_hkd"] == 0)
            ).sum()
        ),
        "fixture_case_count": len(fixture),
        "source_sha256": source_hashes,
        "source_revision_cutoff_date": "2026-07-14",
        "source_download_date": "2026-07-20",
        "cost_effective_date": "",
        "transfer_concession_status": "not_modelled_ignored_for_v1",
        "eligibility_status": "not_modelled_generic_passenger_assumed",
        "temporal_status": (
            "source_snapshot_applied_without_route_specific_effective_date"
        ),
        "matsim_scoring_integration": "not_performed",
    }
    (output_dir / "bus_simulation_fare_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_csv(protected_hashes(repo_root), output_dir / "protected_hashes.csv")
    readme = f"""# Hong Kong bus simulation fare layer v1

Coverage-first offline model layer, separate from the official audit and Bus
Core v1:

- {len(rules):,}/{EXPECTED_PAIRS:,} required ordered ODs have a non-null model fare.
- {len(fallbacks):,}/{EXPECTED_ROUTES:,} bus routes have a non-null route fallback.
- Official unique values remain separate from duplicate consensus, relaxed
  scope, conflict selection, and route fallback assumptions.
- Eligibility, payment medium, transfer concessions, and route-specific
  effective dates are not modelled.
- No fare has entered production PT legs or MATSim scoring.
"""
    (output_dir / "README.md").write_text(readme, encoding="utf-8")
    (output_dir / "bus_simulation_fare_validation.json").write_text(
        json.dumps(
            {
                "schema_version": "hong_kong_bus_simulation_fare_validation_v1",
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
        f"Built {len(rules):,} simulation OD fares and "
        f"{len(fallbacks):,} route fallbacks"
    )


if __name__ == "__main__":
    main()
