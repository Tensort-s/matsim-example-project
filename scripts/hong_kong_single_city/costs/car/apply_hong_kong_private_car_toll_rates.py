#!/usr/bin/env python3
"""Apply audited Hong Kong private-car toll rates by physical passage event.

This script does not modify MATSim inputs, scoring, or the existing unified
car-cost outputs. It reads the audited facility-network mapping, reconstructs
ordered route matches, forms physical passage events, and writes a standalone
toll-rate candidate dataset.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
from lxml import etree


REPO_ROOT = Path.cwd()
CAR_COST_ROOT = Path("data/transport_costs/hongkong/car_cost_v1")
MAPPING_ROOT = CAR_COST_ROOT / "toll_network_mapping_v1"
DEFAULT_OUTPUT = CAR_COST_ROOT / "toll_rate_application_v1"
AUDIT_DOC = Path("docs/HONG_KONG_CAR_TOLL_NETWORK_MAPPING.md")
DAY_TYPE_ASSUMPTION = (
    "official_day_type_A_as_typical_workday; scenario_has_no_calendar_date"
)
PASSAGE_WINDOW_S = 600.0
SCENARIOS = ("low", "base", "high")
EVENT_STATUS_RESOLVED = "confirmed_charge"
EVENT_STATUS_UNRESOLVED = "unresolved"

AUDIT_INPUTS = {
    "mapping_document": AUDIT_DOC,
    "facility_network_mapping": (
        MAPPING_ROOT / "toll_facility_network_mapping.csv"
    ),
    "official_feature_inventory": (
        MAPPING_ROOT / "official_toll_feature_inventory.csv"
    ),
    "feature_alias_resolution": (
        MAPPING_ROOT / "toll_feature_alias_resolution.csv"
    ),
    "leg_identification": (
        MAPPING_ROOT / "car_leg_toll_identification.parquet"
    ),
    "mapping_validation": (
        MAPPING_ROOT / "toll_network_mapping_validation.json"
    ),
    "mapping_required_repairs": (
        MAPPING_ROOT / "toll_mapping_required_repairs.csv"
    ),
}

EXPECTED_AUDIT_SHA256 = {
    "mapping_document": (
        "9d06efbbb4056411de2b4d2a301780bf24adb10479ecdec152fabcd5836179e4"
    ),
    "facility_network_mapping": (
        "ccd3fcd5dcd4028b5717edde4369b2e27f6c41d6675fc65e400ce394cfc74ead"
    ),
    "official_feature_inventory": (
        "4d45377dec8b96b1de8a529b6bc814f44e4bf6549f671a4f1c9ea02355686b20"
    ),
    "feature_alias_resolution": (
        "5e561a0f238fac07ed151a503f6e32b53fb48a1c5c66db1d4d4ca9dcdce4d384"
    ),
    "leg_identification": (
        "c4f1c997a2d48084bd1f51a54d584447de9cdcd22a0a2eebd2f9d21d845fb735"
    ),
    "mapping_validation": (
        "bb51eb8d97a68c27cf1d6e4c9fa7830c5d8ee63a5b4753dd34c63ffed1cb588e"
    ),
    "mapping_required_repairs": (
        "337f49c48cef79d83522dc1e6efecae68961c13383421055fd3d1799abb93072"
    ),
}

LEG_COLUMNS = [
    "person_id",
    "leg_sequence",
    "mode",
    "cost_component",
    "cost_hkd",
    "cost_source",
    "cost_effective_date",
    "cost_quality",
    "scenario",
    "toll_status",
    "toll_event_count",
    "canonical_facility_ids",
    "unresolved_reason",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-project-root",
        type=Path,
        required=True,
        help="Canonical project root containing the large read-only inputs.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def tag_name(element: Any) -> str:
    return str(element.tag).rsplit("}", 1)[-1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_time_s(value: object) -> float:
    if value is None or value == "":
        return float("nan")
    if isinstance(value, (int, float)):
        return float(value)
    parts = str(value).split(":")
    if len(parts) == 3:
        return (
            int(parts[0]) * 3600
            + int(parts[1]) * 60
            + float(parts[2])
        )
    return float(value)


def parse_clock_s(value: object) -> int:
    parts = str(value).split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid official rate clock value: {value}")
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])


def ordered_unique(values: Iterable[object]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values))


def selected_plan(person: Any) -> Any | None:
    plans = [child for child in person if tag_name(child) == "plan"]
    if not plans:
        return None
    selected = [
        plan
        for plan in plans
        if plan.attrib.get("selected", "yes").lower()
        in {"yes", "true", "1"}
    ]
    return selected[0] if selected else plans[0]


def car_legs_in_plan(plan: Any) -> list[tuple[int, Any]]:
    main_activity_index = -1
    result = []
    for child in plan:
        name = tag_name(child)
        if name == "activity":
            if not child.attrib.get("type", "").endswith("interaction"):
                main_activity_index += 1
        elif name == "leg" and child.attrib.get("mode") == "car":
            result.append((main_activity_index, child))
    return result


def reconstruct_links(route: Any | None) -> list[str]:
    if route is None:
        return []
    start = route.attrib.get("start_link", "")
    end = route.attrib.get("end_link", "")
    intermediate = (route.text or "").split()
    if intermediate and intermediate[0] == start:
        intermediate = intermediate[1:]
    if intermediate and intermediate[-1] == end:
        intermediate = intermediate[:-1]
    full = [start] if start else []
    full.extend(intermediate)
    if end and (not full or full[-1] != end):
        full.append(end)
    return full


def canonical_input_paths(input_root: Path) -> dict[str, Path]:
    v2 = (
        input_root
        / "data/matsim_agents/hongkong/"
        "typical_weekday_5pct_v2_activity_modechoice"
    )
    network_root = (
        input_root
        / "data/transit/hongkong/processed/"
        "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_"
        "ferry_core_v1_cap010"
    )
    result = {
        "plans_routed": v2 / "plans_routed_5pct_v2.xml.gz",
        "network": network_root / "network.xml.gz",
    }
    missing = [key for key, path in result.items() if not path.exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing canonical read-only inputs: {missing}"
        )
    return result


def internal_protected_paths(output_dir: Path) -> dict[str, Path]:
    protected: dict[str, Path] = {}
    output_resolved = output_dir.resolve()
    for path in sorted(CAR_COST_ROOT.rglob("*")):
        if not path.is_file():
            continue
        if path.resolve().is_relative_to(output_resolved):
            continue
        protected[path.as_posix()] = path
    protected[AUDIT_DOC.as_posix()] = AUDIT_DOC
    return protected


def hash_path_map(paths: dict[str, Path]) -> dict[str, str]:
    return {key: sha256_file(path) for key, path in sorted(paths.items())}


def load_network(path: Path) -> dict[str, dict[str, Any]]:
    links: dict[str, dict[str, Any]] = {}
    with gzip.open(path, "rb") as handle:
        for _, element in ET.iterparse(handle, events=("end",)):
            if tag_name(element) == "link":
                link_id = str(element.attrib["id"])
                links[link_id] = {
                    "from": str(element.attrib["from"]),
                    "to": str(element.attrib["to"]),
                    "length": float(element.attrib.get("length", "nan")),
                    "freespeed": float(
                        element.attrib.get("freespeed", "nan")
                    ),
                }
            element.clear()
    return links


def load_audited_mapping() -> tuple[
    pd.DataFrame,
    dict[str, list[dict[str, Any]]],
    dict[str, set[int]],
]:
    mapping = pd.read_csv(AUDIT_INPUTS["facility_network_mapping"])
    mapping = mapping.loc[mapping["mapping_status"].eq("mapped")].copy()
    if not mapping["network_link_exists"].all():
        raise RuntimeError("Audited mapping contains a missing network link")
    if set(mapping["mapping_quality"]) != {"B"}:
        raise RuntimeError("Unexpected audited mapping evidence grades")
    link_mapping: dict[str, list[dict[str, Any]]] = defaultdict(list)
    facility_features: dict[str, set[int]] = defaultdict(set)
    for row in mapping.itertuples(index=False):
        record = {
            "canonical_facility_id": str(row.canonical_facility_id),
            "official_feature_id": int(row.official_feature_id),
            "mapping_method": str(row.mapping_method),
            "mapping_quality": str(row.mapping_quality),
            "alias_status": str(row.alias_status),
        }
        link_mapping[str(row.matsim_link_id)].append(record)
        facility_features[str(row.canonical_facility_id)].add(
            int(row.official_feature_id)
        )
    return mapping, dict(link_mapping), dict(facility_features)


def build_initial_clusters(
    matches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_index: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for match in matches:
        by_index[int(match["route_index"])].append(match)
    clusters: list[dict[str, Any]] = []
    current_indices: list[int] = []
    for index in sorted(by_index):
        if current_indices and index > current_indices[-1] + 1:
            clusters.append(
                cluster_record(current_indices, by_index)
            )
            current_indices = []
        current_indices.append(index)
    if current_indices:
        clusters.append(cluster_record(current_indices, by_index))
    return clusters


def cluster_record(
    indices: list[int],
    by_index: dict[int, list[dict[str, Any]]],
) -> dict[str, Any]:
    records = [
        record
        for index in indices
        for record in by_index[index]
    ]
    return {
        "start": min(indices),
        "end": max(indices),
        "route_indices": indices,
        "records": records,
        "features": {
            int(record["official_feature_id"]) for record in records
        },
    }


def stable_event_id(
    person_id: str,
    leg_sequence: int,
    facility: str,
    start_index: int,
    end_index: int,
) -> str:
    payload = (
        f"{person_id}|{leg_sequence}|{facility}|"
        f"{start_index}|{end_index}|physical-passage-v1"
    )
    return "hk_toll_" + hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()[:20]


def event_from_facility_matches(
    person_id: str,
    leg_sequence: int,
    facility: str,
    matches: list[dict[str, Any]],
    route_links: list[str],
    links: dict[str, dict[str, Any]],
    official_features: set[int],
) -> dict[str, Any]:
    clusters = build_initial_clusters(matches)
    feature_cluster_counts: Counter[int] = Counter()
    for cluster in clusters:
        feature_cluster_counts.update(cluster["features"])
    repeated_features = sorted(
        feature
        for feature, count in feature_cluster_counts.items()
        if count > 1
    )
    all_features = ordered_unique(
        record["official_feature_id"]
        for cluster in clusters
        for record in cluster["records"]
    )
    all_features_int = {int(value) for value in all_features}
    western_alias = bool(
        facility == "western_harbour_crossing"
        and 151858 in all_features_int
        and bool(all_features_int & {2684, 2685})
    )
    route_topology_contiguous = all(
        links[left]["to"] == links[right]["from"]
        for left, right in zip(route_links, route_links[1:])
    )

    unresolved_reason = ""
    if len(clusters) == 1:
        cluster_resolution = "single_spatial_match_cluster"
    elif repeated_features:
        cluster_resolution = "repeated_facility_passage_review"
        unresolved_reason = (
            "same_official_feature_reappears_in_separated_route_clusters:"
            + "|".join(map(str, repeated_features))
        )
    elif not route_topology_contiguous:
        cluster_resolution = "repeated_facility_passage_review"
        unresolved_reason = "route_topology_not_contiguous_between_clusters"
    elif not all_features_int.issubset(official_features):
        cluster_resolution = "repeated_facility_passage_review"
        unresolved_reason = "cluster_contains_unexpected_official_feature"
    elif western_alias:
        cluster_resolution = (
            "resolved_whc_alias_and_complementary_feature_fragmentation"
        )
    elif len(all_features_int) >= 2:
        cluster_resolution = (
            "resolved_complementary_official_feature_fragmentation"
        )
    else:
        cluster_resolution = "repeated_facility_passage_review"
        unresolved_reason = (
            "separated_clusters_lack_complementary_feature_evidence"
        )

    gap_links = []
    gap_distances = []
    for left, right in zip(clusters, clusters[1:]):
        gap_links.append(int(right["start"] - left["end"] - 1))
        gap_distances.append(
            float(
                sum(
                    links[link_id]["length"]
                    for link_id in route_links[
                        left["end"] + 1 : right["start"]
                    ]
                )
            )
        )
    start = int(clusters[0]["start"])
    end = int(clusters[-1]["end"])
    matched_records = [
        record
        for cluster in clusters
        for record in cluster["records"]
    ]
    matched_links = ordered_unique(
        record["link_id"] for record in matched_records
    )
    feature_matches = {
        (
            int(record["route_index"]),
            int(record["official_feature_id"]),
        )
        for record in matched_records
    }
    return {
        "toll_event_id": stable_event_id(
            person_id, leg_sequence, facility, start, end
        ),
        "person_id": person_id,
        "leg_sequence": int(leg_sequence),
        "canonical_facility_id": facility,
        "route_match_start_index": start,
        "route_match_end_index": end,
        "matched_link_ids": "|".join(matched_links),
        "matched_feature_ids": "|".join(all_features),
        "raw_mapping_match_count": int(len(matched_records)),
        "feature_match_count": int(len(feature_matches)),
        "initial_spatial_cluster_count": int(len(clusters)),
        "separated_cluster_gap_link_counts": "|".join(
            map(str, gap_links)
        ),
        "separated_cluster_gap_distance_m": "|".join(
            f"{value:.3f}" for value in gap_distances
        ),
        "cluster_resolution": cluster_resolution,
        "alias_deduplicated": western_alias,
        "event_construction_status": (
            EVENT_STATUS_UNRESOLVED
            if unresolved_reason
            else EVENT_STATUS_RESOLVED
        ),
        "event_construction_unresolved_reason": unresolved_reason,
    }


def passage_times(
    event: dict[str, Any],
    route_links: list[str],
    links: dict[str, dict[str, Any]],
    departure_time_s: float,
    route_travel_time_s: float,
) -> dict[str, Any]:
    invalid_reason = ""
    if not math.isfinite(departure_time_s):
        invalid_reason = "invalid_departure_time"
    elif not math.isfinite(route_travel_time_s) or route_travel_time_s < 0:
        invalid_reason = "invalid_route_travel_time"

    lengths = np.asarray(
        [float(links[link_id]["length"]) for link_id in route_links],
        dtype=float,
    )
    freespeeds = np.asarray(
        [float(links[link_id]["freespeed"]) for link_id in route_links],
        dtype=float,
    )
    if (
        not len(route_links)
        or not np.isfinite(lengths).all()
        or (lengths < 0).any()
        or not np.isfinite(freespeeds).all()
        or (freespeeds <= 0).any()
    ):
        invalid_reason = invalid_reason or "invalid_route_weight_inputs"
    freeflow = lengths / freespeeds
    if (
        not invalid_reason
        and (
            float(lengths.sum()) <= 0
            or float(freeflow.sum()) <= 0
        )
    ):
        invalid_reason = "nonpositive_route_weight_sum"

    if invalid_reason:
        return {
            "departure_time_s": departure_time_s,
            "route_travel_time_s": route_travel_time_s,
            "passage_time_base_s": float("nan"),
            "passage_time_low_s": float("nan"),
            "passage_time_high_s": float("nan"),
            "passage_time_length_weight_s": float("nan"),
            "passage_time_method": (
                "unresolved_invalid_leg_or_network_time_inputs"
            ),
            "passage_time_quality": "unresolved",
            "passage_time_unresolved_reason": invalid_reason,
        }

    start = int(event["route_match_start_index"])
    end = int(event["route_match_end_index"])
    ff_position = (
        float(freeflow[:start].sum())
        + 0.5 * float(freeflow[start : end + 1].sum())
    )
    length_position = (
        float(lengths[:start].sum())
        + 0.5 * float(lengths[start : end + 1].sum())
    )
    base = departure_time_s + route_travel_time_s * (
        ff_position / float(freeflow.sum())
    )
    length_weight = departure_time_s + route_travel_time_s * (
        length_position / float(lengths.sum())
    )
    low = min(base - PASSAGE_WINDOW_S, length_weight)
    high = max(base + PASSAGE_WINDOW_S, length_weight)
    return {
        "departure_time_s": float(departure_time_s),
        "route_travel_time_s": float(route_travel_time_s),
        "passage_time_base_s": float(base),
        "passage_time_low_s": float(low),
        "passage_time_high_s": float(high),
        "passage_time_length_weight_s": float(length_weight),
        "passage_time_method": (
            "leg_travel_time_allocated_by_cumulative_network_freeflow_time;"
            "length_weight_sensitivity_check;"
            "analyst_plus_minus_600s_rate_boundary_window"
        ),
        "passage_time_quality": (
            "estimated_not_observed_analyst_sensitivity"
        ),
        "passage_time_unresolved_reason": "",
    }


def parse_routes_and_events(
    plans_path: Path,
    prior_legs: pd.DataFrame,
    links: dict[str, dict[str, Any]],
    link_mapping: dict[str, list[dict[str, Any]]],
    facility_features: dict[str, set[int]],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    prior_lookup = {
        (str(row.person_id), int(row.leg_sequence)): str(row.vehicle_class)
        for row in prior_legs.itertuples(index=False)
    }
    needed_keys = set(prior_lookup)
    route_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()

    with gzip.open(plans_path, "rb") as handle:
        context = etree.iterparse(
            handle, events=("end",), tag="person", huge_tree=True
        )
        for _, person in context:
            person_id = str(person.attrib.get("id", ""))
            plan = selected_plan(person)
            if plan is not None:
                for leg_sequence, leg in car_legs_in_plan(plan):
                    key = (person_id, int(leg_sequence))
                    if key not in needed_keys:
                        continue
                    if key in seen:
                        raise RuntimeError(f"Duplicate routed car leg: {key}")
                    seen.add(key)
                    route = next(
                        (
                            child
                            for child in leg
                            if tag_name(child) == "route"
                        ),
                        None,
                    )
                    route_links = reconstruct_links(route)
                    all_links_exist = bool(route_links) and all(
                        link_id in links for link_id in route_links
                    )
                    topology_contiguous = bool(route_links) and all(
                        links[left]["to"] == links[right]["from"]
                        for left, right in zip(
                            route_links, route_links[1:]
                        )
                    )
                    departure = parse_time_s(leg.attrib.get("dep_time"))
                    travel_time = parse_time_s(
                        route.attrib.get("trav_time")
                        if route is not None
                        else leg.attrib.get("trav_time")
                    )
                    raw_matches: list[dict[str, Any]] = []
                    if all_links_exist:
                        for index, link_id in enumerate(route_links):
                            for mapping in link_mapping.get(link_id, []):
                                raw_matches.append(
                                    {
                                        "route_index": int(index),
                                        "link_id": link_id,
                                        **mapping,
                                    }
                                )
                    facility_matches: dict[
                        str, list[dict[str, Any]]
                    ] = defaultdict(list)
                    for match in raw_matches:
                        facility_matches[
                            str(match["canonical_facility_id"])
                        ].append(match)

                    leg_events = []
                    if prior_lookup[key] == "private_car":
                        for facility, matches in sorted(
                            facility_matches.items(),
                            key=lambda item: min(
                                int(match["route_index"])
                                for match in item[1]
                            ),
                        ):
                            event = event_from_facility_matches(
                                person_id,
                                int(leg_sequence),
                                facility,
                                matches,
                                route_links,
                                links,
                                facility_features[facility],
                            )
                            event.update(
                                passage_times(
                                    event,
                                    route_links,
                                    links,
                                    departure,
                                    travel_time,
                                )
                            )
                            leg_events.append(event)
                            event_rows.append(event)
                    route_rows.append(
                        {
                            "person_id": person_id,
                            "leg_sequence": int(leg_sequence),
                            "vehicle_class": prior_lookup[key],
                            "route_link_count": int(len(route_links)),
                            "all_route_links_exist": bool(all_links_exist),
                            "route_topology_contiguous": bool(
                                topology_contiguous
                            ),
                            "raw_mapping_match_count": int(
                                len(raw_matches)
                            ),
                            "feature_match_count": int(
                                len(
                                    {
                                        (
                                            int(match["route_index"]),
                                            int(
                                                match[
                                                    "official_feature_id"
                                                ]
                                            ),
                                        )
                                        for match in raw_matches
                                    }
                                )
                            ),
                            "canonical_event_count": int(len(leg_events)),
                            "event_facilities": "|".join(
                                event["canonical_facility_id"]
                                for event in leg_events
                            ),
                        }
                    )
            person.clear()
            parent = person.getparent()
            if parent is not None:
                while person.getprevious() is not None:
                    del parent[0]
    if seen != needed_keys:
        missing = len(needed_keys - seen)
        extra = len(seen - needed_keys)
        raise RuntimeError(
            f"Routed car leg keys differ: missing={missing}, extra={extra}"
        )
    routes = pd.DataFrame(route_rows).sort_values(
        ["person_id", "leg_sequence"]
    )
    events = pd.DataFrame(event_rows).sort_values(
        [
            "person_id",
            "leg_sequence",
            "route_match_start_index",
            "canonical_facility_id",
        ]
    )
    diagnostics = {
        "raw_mapping_match_count": int(
            routes["raw_mapping_match_count"].sum()
        ),
        "feature_match_count": int(routes["feature_match_count"].sum()),
        "canonical_event_count": int(len(events)),
    }
    return routes, events, diagnostics


def rate_value(frame: pd.DataFrame) -> pd.Series:
    return frame["concession_toll"].where(
        frame["concession_toll"].notna(),
        frame["gazetted_toll"],
    )


def prepare_rate_schedules(
    inventory: pd.DataFrame,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    rates = inventory.copy()
    rates["rate_hkd"] = rate_value(rates)
    rates = rates.loc[rates["rate_hkd"].notna()].copy()
    rates = rates.loc[
        ~rates["official_facility_name_raw"].str.contains(
            "Backup Toll Point", case=False, na=False
        )
    ].copy()
    schedules: dict[str, dict[str, Any]] = {}
    interval_validation: dict[str, Any] = {}

    for facility, group in rates.groupby("canonical_facility_id"):
        rule_types = set(group["rule_type"])
        if len(rule_types) != 1:
            raise RuntimeError(f"Mixed toll rule types for {facility}")
        rule_type = str(next(iter(rule_types)))
        sources = sorted(set(group["source_layer"].astype(str)))
        source_hashes = sorted(set(group["source_sha256"].astype(str)))
        effective_dates = sorted(set(group["effective_date"].astype(str)))
        if len(sources) != 1 or len(source_hashes) != 1:
            raise RuntimeError(f"Ambiguous rate provenance for {facility}")
        if len(effective_dates) != 1:
            raise RuntimeError(f"Ambiguous effective date for {facility}")
        common = {
            "rule_type": rule_type,
            "rate_source": (
                "data/transit/hongkong/RdNet_IRNP.gdb:"
                + sources[0]
            ),
            "rate_source_sha256": source_hashes[0],
            "rate_effective_date": effective_dates[0],
        }
        if rule_type == "flat":
            unique_rates = sorted(set(group["rate_hkd"].astype(float)))
            if len(unique_rates) != 1:
                raise RuntimeError(f"Ambiguous flat rate for {facility}")
            schedules[facility] = {
                **common,
                "flat_rate_hkd": float(unique_rates[0]),
                "intervals": [],
            }
            interval_validation[facility] = {
                "rule_type": "flat",
                "gap_count": 0,
                "overlap_count": 0,
                "rate_hkd": float(unique_rates[0]),
            }
            continue

        facility_intervals: dict[str, list[dict[str, Any]]] = {}
        facility_validation: dict[str, Any] = {"rule_type": rule_type}
        for day_type in ("A", "B"):
            day = group.loc[
                group["day_of_week"].astype(str).eq(day_type)
            ].copy()
            day["start_s"] = day["start_time"].map(parse_clock_s)
            day["end_exclusive_s"] = (
                day["end_time"].map(parse_clock_s) + 1
            )
            dedup = day[
                [
                    "start_s",
                    "end_exclusive_s",
                    "start_time",
                    "end_time",
                    "rate_hkd",
                ]
            ].drop_duplicates()
            dedup = dedup.sort_values(
                ["start_s", "end_exclusive_s", "rate_hkd"]
            )
            gaps = []
            overlaps = []
            cursor = 0
            for row in dedup.itertuples(index=False):
                if int(row.start_s) > cursor:
                    gaps.append([cursor, int(row.start_s)])
                if int(row.start_s) < cursor:
                    overlaps.append([int(row.start_s), cursor])
                cursor = max(cursor, int(row.end_exclusive_s))
            if cursor < 86400:
                gaps.append([cursor, 86400])
            facility_validation[day_type] = {
                "interval_count": int(len(dedup)),
                "gap_count": int(len(gaps)),
                "overlap_count": int(len(overlaps)),
                "gaps": gaps,
                "overlaps": overlaps,
            }
            facility_intervals[day_type] = [
                {
                    "start_s": int(row.start_s),
                    "end_exclusive_s": int(row.end_exclusive_s),
                    "start_time": str(row.start_time),
                    "end_time": str(row.end_time),
                    "rate_hkd": float(row.rate_hkd),
                }
                for row in dedup.itertuples(index=False)
            ]
        schedules[facility] = {
            **common,
            "flat_rate_hkd": None,
            "intervals": facility_intervals["A"],
            "intervals_day_type_B": facility_intervals["B"],
        }
        interval_validation[facility] = facility_validation

    reported_gaps = sum(
        record.get(day, {}).get("gap_count", 0)
        for record in interval_validation.values()
        for day in ("A", "B")
    )
    reported_overlaps = sum(
        record.get(day, {}).get("overlap_count", 0)
        for record in interval_validation.values()
        for day in ("A", "B")
    )
    if reported_gaps or reported_overlaps:
        raise RuntimeError(
            "Official rate interval gaps or overlaps require blocking review"
        )
    return schedules, interval_validation


def interval_at(
    schedule: dict[str, Any], time_s: float
) -> dict[str, Any] | None:
    if schedule["rule_type"] == "flat":
        return {
            "start_time": "00:00:00",
            "end_time": "23:59:59",
            "rate_hkd": float(schedule["flat_rate_hkd"]),
        }
    clock = float(time_s % 86400.0)
    for interval in schedule["intervals"]:
        if (
            float(interval["start_s"])
            <= clock
            < float(interval["end_exclusive_s"])
        ):
            return interval
    return None


def intervals_over_window(
    schedule: dict[str, Any],
    low_s: float,
    high_s: float,
) -> list[dict[str, Any]]:
    if schedule["rule_type"] == "flat":
        return [interval_at(schedule, low_s)]
    result = []
    first_day = math.floor(low_s / 86400.0) - 1
    last_day = math.floor(high_s / 86400.0) + 1
    for day in range(first_day, last_day + 1):
        offset = day * 86400.0
        for interval in schedule["intervals"]:
            start = offset + float(interval["start_s"])
            end = offset + float(interval["end_exclusive_s"])
            if start < high_s and end > low_s:
                result.append(interval)
    return result


def interval_label(interval: dict[str, Any]) -> str:
    return (
        f"A {interval['start_time']}-{interval['end_time']}"
        f" @ HKD {float(interval['rate_hkd']):.2f}"
    )


def apply_rates_to_events(
    events: pd.DataFrame,
    schedules: dict[str, dict[str, Any]],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    scenario_rows: list[dict[str, Any]] = []
    boundary_window_count = 0
    base_length_boundary_count = 0
    unresolved_event_count = 0

    for event in events.to_dict(orient="records"):
        unresolved = str(
            event["event_construction_unresolved_reason"]
        )
        unresolved = unresolved or str(
            event["passage_time_unresolved_reason"]
        )
        facility = str(event["canonical_facility_id"])
        schedule = schedules.get(facility)
        if schedule is None:
            unresolved = unresolved or "facility_missing_official_pc_rate"

        base_interval = None
        length_interval = None
        window_intervals: list[dict[str, Any]] = []
        if not unresolved:
            base_interval = interval_at(
                schedule, float(event["passage_time_base_s"])
            )
            length_interval = interval_at(
                schedule, float(event["passage_time_length_weight_s"])
            )
            window_intervals = intervals_over_window(
                schedule,
                float(event["passage_time_low_s"]),
                float(event["passage_time_high_s"]),
            )
            if base_interval is None or length_interval is None:
                unresolved = "rate_interval_not_found_for_passage_time"
            elif not window_intervals:
                unresolved = "no_rate_interval_over_sensitivity_window"

        if unresolved:
            unresolved_event_count += 1
            choices = {
                scenario: (float("nan"), "")
                for scenario in SCENARIOS
            }
            boundary_window = False
            base_length_boundary = False
        else:
            minimum = min(
                float(interval["rate_hkd"])
                for interval in window_intervals
            )
            maximum = max(
                float(interval["rate_hkd"])
                for interval in window_intervals
            )
            base_rate = float(base_interval["rate_hkd"])
            choices = {
                "low": (
                    minimum,
                    "|".join(
                        ordered_unique(
                            interval_label(interval)
                            for interval in window_intervals
                            if float(interval["rate_hkd"]) == minimum
                        )
                    ),
                ),
                "base": (base_rate, interval_label(base_interval)),
                "high": (
                    maximum,
                    "|".join(
                        ordered_unique(
                            interval_label(interval)
                            for interval in window_intervals
                            if float(interval["rate_hkd"]) == maximum
                        )
                    ),
                ),
            }
            boundary_window = len(
                {
                    float(interval["rate_hkd"])
                    for interval in window_intervals
                }
            ) > 1
            base_length_boundary = (
                float(base_interval["rate_hkd"])
                != float(length_interval["rate_hkd"])
            )
            boundary_window_count += int(boundary_window)
            base_length_boundary_count += int(base_length_boundary)

        for scenario in SCENARIOS:
            cost_hkd, matched_interval = choices[scenario]
            scenario_rows.append(
                {
                    **event,
                    "scenario": scenario,
                    "vehicle_class": "private_car",
                    "day_type_assumption": DAY_TYPE_ASSUMPTION,
                    "rate_source": (
                        schedule["rate_source"] if schedule else ""
                    ),
                    "rate_source_sha256": (
                        schedule["rate_source_sha256"]
                        if schedule
                        else ""
                    ),
                    "rate_effective_date": (
                        schedule["rate_effective_date"]
                        if schedule
                        else ""
                    ),
                    "matched_rate_interval": matched_interval,
                    "rate_quality": (
                        "official_PC_rate_with_estimated_passage_time"
                        if not unresolved
                        else "unresolved"
                    ),
                    "sensitivity_window_assumption_s": PASSAGE_WINDOW_S,
                    "sensitivity_window_crosses_rate_boundary": bool(
                        boundary_window
                    ),
                    "base_vs_length_weight_crosses_rate_boundary": bool(
                        base_length_boundary
                    ),
                    "toll_status": (
                        EVENT_STATUS_RESOLVED
                        if not unresolved
                        else EVENT_STATUS_UNRESOLVED
                    ),
                    "cost_hkd": (
                        float(cost_hkd)
                        if math.isfinite(float(cost_hkd))
                        else float("nan")
                    ),
                    "unresolved_reason": unresolved,
                }
            )
    result = pd.DataFrame(scenario_rows)
    diagnostics = {
        "unresolved_physical_event_count": int(unresolved_event_count),
        "sensitivity_window_crosses_rate_boundary_event_count": int(
            boundary_window_count
        ),
        "base_vs_length_weight_crosses_rate_boundary_event_count": int(
            base_length_boundary_count
        ),
    }
    return result, diagnostics


def leg_outputs(
    prior_legs: pd.DataFrame,
    event_scenarios: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    output: dict[str, pd.DataFrame] = {}
    for scenario in SCENARIOS:
        scenario_events = event_scenarios.loc[
            event_scenarios["scenario"].eq(scenario)
        ].sort_values(
            [
                "person_id",
                "leg_sequence",
                "route_match_start_index",
            ]
        )
        grouped = {
            key: group
            for key, group in scenario_events.groupby(
                ["person_id", "leg_sequence"], sort=False
            )
        }
        rows = []
        for leg in prior_legs.itertuples(index=False):
            key = (str(leg.person_id), int(leg.leg_sequence))
            group = grouped.get(key)
            vehicle_class = str(leg.vehicle_class)
            identification = str(leg.toll_identification_status)
            if vehicle_class == "motorcycle":
                toll_status = "out_of_scope"
                cost_hkd = float("nan")
                cost_quality = "out_of_scope_motorcycle"
                unresolved_reason = "vehicle_class_motorcycle"
                event_count = 0
                facilities = ""
                sources = ""
                effective_dates = ""
            elif identification == (
                "confirmed_no_charge_all_facilities_covered"
            ):
                toll_status = "confirmed_no_charge"
                cost_hkd = 0.0
                cost_quality = (
                    "confirmed_full_route_no_audited_toll_facility"
                )
                unresolved_reason = ""
                event_count = 0
                facilities = ""
                sources = (
                    MAPPING_ROOT
                    / "toll_facility_network_mapping.csv"
                ).as_posix()
                effective_dates = ""
            elif group is None or group.empty:
                toll_status = "unresolved"
                cost_hkd = float("nan")
                cost_quality = "unresolved"
                unresolved_reason = (
                    "identified_charge_leg_has_no_passage_event"
                )
                event_count = 0
                facilities = ""
                sources = ""
                effective_dates = ""
            elif group["toll_status"].ne(EVENT_STATUS_RESOLVED).any():
                toll_status = "unresolved"
                cost_hkd = float("nan")
                cost_quality = "unresolved"
                unresolved_reason = "|".join(
                    ordered_unique(
                        value
                        for value in group["unresolved_reason"]
                        if str(value)
                    )
                )
                event_count = int(len(group))
                facilities = "|".join(
                    group["canonical_facility_id"].astype(str)
                )
                sources = "|".join(
                    ordered_unique(group["rate_source"])
                )
                effective_dates = "|".join(
                    ordered_unique(group["rate_effective_date"])
                )
            else:
                toll_status = "confirmed_charge"
                cost_hkd = float(group["cost_hkd"].sum())
                cost_quality = (
                    "official_PC_rates_estimated_passage_time_"
                    "analyst_sensitivity"
                )
                unresolved_reason = ""
                event_count = int(len(group))
                facilities = "|".join(
                    group["canonical_facility_id"].astype(str)
                )
                sources = "|".join(
                    ordered_unique(group["rate_source"])
                )
                effective_dates = "|".join(
                    ordered_unique(group["rate_effective_date"])
                )
            rows.append(
                {
                    "person_id": key[0],
                    "leg_sequence": key[1],
                    "mode": "car",
                    "cost_component": "toll",
                    "cost_hkd": cost_hkd,
                    "cost_source": sources,
                    "cost_effective_date": effective_dates,
                    "cost_quality": cost_quality,
                    "scenario": scenario,
                    "toll_status": toll_status,
                    "toll_event_count": int(event_count),
                    "canonical_facility_ids": facilities,
                    "unresolved_reason": unresolved_reason,
                }
            )
        frame = pd.DataFrame(rows)[LEG_COLUMNS].sort_values(
            ["person_id", "leg_sequence"]
        )
        output[scenario] = frame.reset_index(drop=True)
    return output


def quantile_90(values: pd.Series) -> float:
    return float(values.quantile(0.9)) if len(values) else float("nan")


def build_summary(
    event_scenarios: pd.DataFrame,
    leg_frames: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    rows = []
    for scenario in SCENARIOS:
        events = event_scenarios.loc[
            event_scenarios["scenario"].eq(scenario)
        ]
        legs = leg_frames[scenario]
        for facility, group in events.groupby("canonical_facility_id"):
            resolved = group.loc[
                group["toll_status"].eq(EVENT_STATUS_RESOLVED)
            ]
            rows.append(
                {
                    "summary_scope": "facility",
                    "canonical_facility_id": facility,
                    "scenario": scenario,
                    "passage_event_count": int(len(group)),
                    "resolved_event_count": int(len(resolved)),
                    "unresolved_event_count": int(
                        group["toll_status"].eq("unresolved").sum()
                    ),
                    "charge_leg_count": int(
                        resolved[
                            ["person_id", "leg_sequence"]
                        ].drop_duplicates().shape[0]
                    ),
                    "resolved_private_car_leg_count": int(
                        resolved[
                            ["person_id", "leg_sequence"]
                        ].drop_duplicates().shape[0]
                    ),
                    "incomplete_unresolved_leg_count": int(
                        group.loc[
                            group["toll_status"].eq("unresolved"),
                            ["person_id", "leg_sequence"],
                        ].drop_duplicates().shape[0]
                    ),
                    "out_of_scope_leg_count": 0,
                    "total_cost_hkd_resolved_only": float(
                        resolved["cost_hkd"].sum()
                    ),
                    "mean_cost_hkd_resolved_only": float(
                        resolved["cost_hkd"].mean()
                    ),
                    "median_cost_hkd_resolved_only": float(
                        resolved["cost_hkd"].median()
                    ),
                    "p90_cost_hkd_resolved_only": quantile_90(
                        resolved["cost_hkd"]
                    ),
                    "rate_effective_dates": "|".join(
                        ordered_unique(group["rate_effective_date"])
                    ),
                    "rate_sources": "|".join(
                        ordered_unique(group["rate_source"])
                    ),
                    "rate_boundary_event_count": int(
                        group[
                            "sensitivity_window_crosses_rate_boundary"
                        ].sum()
                    ),
                    "all_record_resolved_coverage_fraction": float(
                        len(resolved) / len(group)
                    ),
                    "private_car_resolved_coverage_fraction": float(
                        len(resolved) / len(group)
                    ),
                }
            )
        resolved_legs = legs.loc[
            legs["toll_status"].isin(
                ["confirmed_charge", "confirmed_no_charge"]
            )
        ]
        resolved_values = resolved_legs["cost_hkd"]
        rows.append(
            {
                "summary_scope": "overall",
                "canonical_facility_id": "all",
                "scenario": scenario,
                "passage_event_count": int(len(events)),
                "resolved_event_count": int(
                    events["toll_status"].eq(EVENT_STATUS_RESOLVED).sum()
                ),
                "unresolved_event_count": int(
                    events["toll_status"].eq("unresolved").sum()
                ),
                "charge_leg_count": int(
                    legs["toll_status"].eq("confirmed_charge").sum()
                ),
                "resolved_private_car_leg_count": int(len(resolved_legs)),
                "incomplete_unresolved_leg_count": int(
                    legs["toll_status"].eq("unresolved").sum()
                ),
                "out_of_scope_leg_count": int(
                    legs["toll_status"].eq("out_of_scope").sum()
                ),
                "total_cost_hkd_resolved_only": float(
                    resolved_values.sum()
                ),
                "mean_cost_hkd_resolved_only": float(
                    resolved_values.mean()
                ),
                "median_cost_hkd_resolved_only": float(
                    resolved_values.median()
                ),
                "p90_cost_hkd_resolved_only": quantile_90(
                    resolved_values
                ),
                "rate_effective_dates": "|".join(
                    ordered_unique(events["rate_effective_date"])
                ),
                "rate_sources": "|".join(
                    ordered_unique(events["rate_source"])
                ),
                "rate_boundary_event_count": int(
                    events[
                        "sensitivity_window_crosses_rate_boundary"
                    ].sum()
                ),
                "all_record_resolved_coverage_fraction": float(
                    len(resolved_legs) / len(legs)
                ),
                "private_car_resolved_coverage_fraction": float(
                    len(resolved_legs)
                    / legs["toll_status"].ne("out_of_scope").sum()
                ),
            }
        )
    return pd.DataFrame(rows)


def validate_outputs(
    prior_legs: pd.DataFrame,
    routes: pd.DataFrame,
    events: pd.DataFrame,
    event_scenarios: pd.DataFrame,
    leg_frames: dict[str, pd.DataFrame],
    mapping_validation: dict[str, Any],
    route_diagnostics: dict[str, Any],
    rate_diagnostics: dict[str, Any],
    interval_validation: dict[str, Any],
) -> dict[str, Any]:
    expected_status = {
        "confirmed_charge_facility_identified": 25858,
        "confirmed_no_charge_all_facilities_covered": 38931,
        "out_of_scope_motorcycle": 2929,
    }
    status_counts = {
        str(key): int(value)
        for key, value in prior_legs[
            "toll_identification_status"
        ].value_counts().items()
    }
    input_identification_matches = bool(
        len(prior_legs) == 67718
        and prior_legs["vehicle_class"].eq("private_car").sum() == 64789
        and prior_legs["vehicle_class"].eq("motorcycle").sum() == 2929
        and status_counts == expected_status
        and mapping_validation[
            "route_legs_with_multiple_physical_facilities"
        ]
        == 4786
        and mapping_validation[
            "legs_different_from_current_car_cost_v1"
        ]
        == 27220
    )
    if not input_identification_matches:
        raise RuntimeError("94e02c8 mapping identification invariants differ")

    identity_unique = not events.duplicated(
        ["person_id", "leg_sequence", "toll_event_id"]
    ).any()
    scenario_unique = not event_scenarios.duplicated(
        ["person_id", "leg_sequence", "toll_event_id", "scenario"]
    ).any()
    event_facility_unique = bool(
        events["canonical_facility_id"].notna().all()
        and events["canonical_facility_id"].ne("").all()
    )
    whc_alias_duplicate_event_count = int(
        events.loc[
            events["alias_deduplicated"],
            ["person_id", "leg_sequence", "canonical_facility_id"],
        ].duplicated().sum()
    )
    separated = events.loc[
        events["initial_spatial_cluster_count"].gt(1)
    ]
    repeated_review = events.loc[
        events["cluster_resolution"].eq(
            "repeated_facility_passage_review"
        )
    ]

    aggregation_max_abs_error = 0.0
    event_by_scenario = {
        scenario: event_scenarios.loc[
            event_scenarios["scenario"].eq(scenario)
            & event_scenarios["toll_status"].eq(EVENT_STATUS_RESOLVED)
        ]
        for scenario in SCENARIOS
    }
    for scenario in SCENARIOS:
        event_sum = (
            event_by_scenario[scenario]
            .groupby(["person_id", "leg_sequence"])["cost_hkd"]
            .sum()
        )
        legs = leg_frames[scenario]
        charge = legs.loc[
            legs["toll_status"].eq("confirmed_charge")
        ].set_index(["person_id", "leg_sequence"])["cost_hkd"]
        aligned = event_sum.reindex(charge.index)
        error = (aligned - charge).abs()
        if len(error):
            aggregation_max_abs_error = max(
                aggregation_max_abs_error, float(error.max())
            )

    event_pivot = event_scenarios.pivot(
        index=["person_id", "leg_sequence", "toll_event_id"],
        columns="scenario",
        values="cost_hkd",
    )
    event_nonnull = event_pivot.dropna()
    event_order_valid = bool(
        (
            (event_nonnull["low"] <= event_nonnull["base"])
            & (event_nonnull["base"] <= event_nonnull["high"])
        ).all()
    )
    leg_pivots = pd.concat(
        [
            frame.set_index(["person_id", "leg_sequence"])[
                ["cost_hkd"]
            ].rename(columns={"cost_hkd": scenario})
            for scenario, frame in leg_frames.items()
        ],
        axis=1,
    )
    leg_nonnull = leg_pivots.dropna()
    leg_order_valid = bool(
        (
            (leg_nonnull["low"] <= leg_nonnull["base"])
            & (leg_nonnull["base"] <= leg_nonnull["high"])
        ).all()
    )
    zero_rules = {}
    null_rules = {}
    leg_status_counts = {}
    totals = {}
    for scenario, frame in leg_frames.items():
        zero_rows = frame["cost_hkd"].eq(0)
        zero_rules[scenario] = bool(
            frame.loc[zero_rows, "toll_status"]
            .eq("confirmed_no_charge")
            .all()
        )
        null_required = frame["toll_status"].isin(
            ["unresolved", "out_of_scope"]
        )
        null_rules[scenario] = bool(
            frame.loc[null_required, "cost_hkd"].isna().all()
        )
        leg_status_counts[scenario] = {
            str(key): int(value)
            for key, value in frame["toll_status"].value_counts().items()
        }
        totals[scenario] = float(
            frame.loc[
                frame["toll_status"].eq("confirmed_charge"), "cost_hkd"
            ].sum()
        )

    facility_event_counts = {
        str(key): int(value)
        for key, value in events[
            "canonical_facility_id"
        ].value_counts().sort_index().items()
    }
    unresolved_events = int(
        event_scenarios.loc[
            event_scenarios["scenario"].eq("base"),
            "toll_status",
        ].eq("unresolved").sum()
    )
    rate_gap_count = sum(
        record.get(day, {}).get("gap_count", 0)
        for record in interval_validation.values()
        for day in ("A", "B")
    )
    rate_overlap_count = sum(
        record.get(day, {}).get("overlap_count", 0)
        for record in interval_validation.values()
        for day in ("A", "B")
    )
    publishable = bool(
        input_identification_matches
        and identity_unique
        and scenario_unique
        and event_facility_unique
        and whc_alias_duplicate_event_count == 0
        and len(repeated_review) == 0
        and aggregation_max_abs_error <= 1e-9
        and event_order_valid
        and leg_order_valid
        and all(zero_rules.values())
        and all(null_rules.values())
        and rate_gap_count == 0
        and rate_overlap_count == 0
        and unresolved_events == 0
    )
    return {
        "audit": (
            "Hong Kong private-car toll rate application by passage event v1"
        ),
        "candidate_output_only": True,
        "matsim_scoring_modified": False,
        "publishable_candidate": publishable,
        "blocked": not publishable,
        "input_mapping_identification": {
            "car_leg_count": int(len(prior_legs)),
            "private_car_leg_count": int(
                prior_legs["vehicle_class"].eq("private_car").sum()
            ),
            "motorcycle_out_of_scope_leg_count": int(
                prior_legs["vehicle_class"].eq("motorcycle").sum()
            ),
            "status_counts": status_counts,
            "multiple_distinct_physical_facility_legs": int(
                mapping_validation[
                    "route_legs_with_multiple_physical_facilities"
                ]
            ),
            "legs_different_from_old_car_cost_v1": int(
                mapping_validation[
                    "legs_different_from_current_car_cost_v1"
                ]
            ),
            "matches_94e02c8_audit_invariants": (
                input_identification_matches
            ),
        },
        "route_event_construction": {
            **route_diagnostics,
            "event_identity_key_unique_before_scenario_expansion": (
                identity_unique
            ),
            "event_scenario_key_unique": scenario_unique,
            "every_event_has_one_canonical_facility": (
                event_facility_unique
            ),
            "private_car_charge_leg_count": int(
                prior_legs["toll_identification_status"].eq(
                    "confirmed_charge_facility_identified"
                ).sum()
            ),
            "multiple_distinct_facility_leg_count": int(
                mapping_validation[
                    "route_legs_with_multiple_physical_facilities"
                ]
            ),
            "private_car_multiple_distinct_facility_leg_count": int(
                (
                    routes["vehicle_class"].eq("private_car")
                    & routes["canonical_event_count"].gt(1)
                ).sum()
            ),
            "same_facility_multiple_spatial_cluster_leg_facility_count": (
                int(len(separated))
            ),
            "whc_alias_merged_event_count": int(
                events["alias_deduplicated"].sum()
            ),
            "whc_duplicate_physical_events_after_merge": (
                whc_alias_duplicate_event_count
            ),
            "complementary_feature_fragmentation_merged_count": int(
                events["cluster_resolution"].eq(
                    "resolved_complementary_official_feature_fragmentation"
                ).sum()
            ),
            "repeated_facility_passage_review_count": int(
                len(repeated_review)
            ),
            "facility_event_counts": facility_event_counts,
            "all_route_links_exist": bool(
                routes["all_route_links_exist"].all()
            ),
            "all_routes_topologically_contiguous": bool(
                routes["route_topology_contiguous"].all()
            ),
        },
        "passage_time_and_rates": {
            "passage_time_observed": False,
            "base_method": (
                "cumulative network free-flow travel-time weighting"
            ),
            "length_weight_sensitivity_calculated": True,
            "analyst_sensitivity_window_seconds": PASSAGE_WINDOW_S,
            "analyst_sensitivity_window_purpose": (
                "capture possible official time-varying rate boundaries "
                "around an estimated, not observed, facility passage time"
            ),
            "day_type_assumption": DAY_TYPE_ASSUMPTION,
            **rate_diagnostics,
            "official_interval_validation": interval_validation,
            "reported_rate_gap_count": int(rate_gap_count),
            "reported_rate_overlap_count": int(rate_overlap_count),
        },
        "leg_output": {
            "row_counts": {
                scenario: int(len(frame))
                for scenario, frame in leg_frames.items()
            },
            "status_counts": leg_status_counts,
            "event_to_leg_aggregation_max_abs_error_hkd": float(
                aggregation_max_abs_error
            ),
            "event_low_le_base_le_high": event_order_valid,
            "leg_low_le_base_le_high": leg_order_valid,
            "zero_only_for_confirmed_no_charge": zero_rules,
            "unresolved_and_out_of_scope_cost_null": null_rules,
            "resolved_charge_totals_hkd": totals,
        },
    }


def required_repairs(validation: dict[str, Any]) -> pd.DataFrame:
    rows = [
        {
            "repair_id": "TOLLRATE-R01",
            "severity": "medium",
            "component": "scenario_calendar",
            "finding": (
                "The typical-weekday plans do not carry an exact calendar "
                "date; official day type A is an explicit analyst assumption."
            ),
            "required_change": (
                "Bind a real simulation calendar and legal day type before "
                "using the candidate outside the typical-workday scenario."
            ),
        },
        {
            "repair_id": "TOLLRATE-R02",
            "severity": "medium",
            "component": "passage_time",
            "finding": (
                "Facility passage times are estimated from leg travel time "
                "and network weights, not observed timestamps."
            ),
            "required_change": (
                "Replace or validate estimated passage times if observed "
                "link-entry times become available."
            ),
        },
        {
            "repair_id": "TOLLRATE-R03",
            "severity": "high",
            "component": "integration",
            "finding": (
                "These are standalone toll candidates and do not repair the "
                "unified car-cost outputs or MATSim scoring."
            ),
            "required_change": (
                "Use a separately reviewed rebuild stage; do not overwrite "
                "existing low/base/high car-cost outputs in place."
            ),
        },
    ]
    repeated = validation["route_event_construction"][
        "repeated_facility_passage_review_count"
    ]
    if repeated:
        rows.append(
            {
                "repair_id": "TOLLRATE-R04",
                "severity": "critical",
                "component": "passage_event",
                "finding": (
                    f"{repeated} same-facility separated passage records "
                    "lack sufficient physical-event evidence."
                ),
                "required_change": (
                    "Resolve each repeated-facility passage before treating "
                    "the candidate as publishable."
                ),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    args = parse_args()
    canonical = canonical_input_paths(args.input_project_root.resolve())
    missing_audit = [
        key for key, path in AUDIT_INPUTS.items() if not path.exists()
    ]
    if missing_audit:
        raise FileNotFoundError(
            f"Missing locked mapping audit inputs: {missing_audit}"
        )

    audit_hashes_before = hash_path_map(AUDIT_INPUTS)
    if audit_hashes_before != EXPECTED_AUDIT_SHA256:
        raise RuntimeError(
            "Locked 94e02c8 mapping audit SHA256 values do not match"
        )
    protected_paths = internal_protected_paths(args.output_dir)
    internal_hashes_before = hash_path_map(protected_paths)
    canonical_hashes_before = {
        key: sha256_file(path) for key, path in canonical.items()
    }

    mapping_validation = json.loads(
        AUDIT_INPUTS["mapping_validation"].read_text(encoding="utf-8")
    )
    prior_legs = pd.read_parquet(AUDIT_INPUTS["leg_identification"])
    mapping, link_mapping, facility_features = load_audited_mapping()
    aliases = pd.read_csv(AUDIT_INPUTS["feature_alias_resolution"])
    if not (
        len(aliases) == 1
        and aliases.iloc[0]["alias_status"]
        == "canonical_alias_same_physical_facility"
        and bool(aliases.iloc[0]["charge_once_per_route_passage"])
    ):
        raise RuntimeError("WHC alias audit is not charge-once complete")

    links = load_network(canonical["network"])
    mapped_links = set(mapping["matsim_link_id"].astype(str))
    if not mapped_links.issubset(links):
        raise RuntimeError("Audited mapped links differ from canonical network")

    routes, events, route_diagnostics = parse_routes_and_events(
        canonical["plans_routed"],
        prior_legs,
        links,
        link_mapping,
        facility_features,
    )
    inventory = pd.read_csv(AUDIT_INPUTS["official_feature_inventory"])
    schedules, interval_validation = prepare_rate_schedules(inventory)
    event_scenarios, rate_diagnostics = apply_rates_to_events(
        events, schedules
    )
    legs = leg_outputs(prior_legs, event_scenarios)
    summary = build_summary(event_scenarios, legs)
    validation = validate_outputs(
        prior_legs,
        routes,
        events,
        event_scenarios,
        legs,
        mapping_validation,
        route_diagnostics,
        rate_diagnostics,
        interval_validation,
    )

    audit_hashes_after = hash_path_map(AUDIT_INPUTS)
    internal_hashes_after = hash_path_map(protected_paths)
    canonical_hashes_after = {
        key: sha256_file(path) for key, path in canonical.items()
    }
    hashes_unchanged = bool(
        audit_hashes_before == audit_hashes_after
        and internal_hashes_before == internal_hashes_after
        and canonical_hashes_before == canonical_hashes_after
    )
    validation["protected_inputs"] = {
        "locked_audit_sha256_match_94e02c8": (
            audit_hashes_before == EXPECTED_AUDIT_SHA256
        ),
        "locked_audit_inputs_unchanged": (
            audit_hashes_before == audit_hashes_after
        ),
        "all_existing_car_cost_v1_inputs_and_outputs_unchanged": (
            internal_hashes_before == internal_hashes_after
        ),
        "canonical_plans_and_network_unchanged": (
            canonical_hashes_before == canonical_hashes_after
        ),
        "all_protected_hashes_unchanged": hashes_unchanged,
    }
    if not hashes_unchanged:
        validation["publishable_candidate"] = False
        validation["blocked"] = True
        raise RuntimeError("Protected input changed during rate application")

    input_hashes = {
        "input_root_role": (
            "canonical_project_read_only_large_inputs; absolute root omitted"
        ),
        "locked_mapping_audit_commit": (
            "94e02c8c34a9c9861f9c5d355b1bf6ade0f1ef64"
        ),
        "audit_inputs_before": audit_hashes_before,
        "audit_inputs_after": audit_hashes_after,
        "canonical_inputs": {
            "plans_routed": {
                "role_path": (
                    "data/matsim_agents/hongkong/"
                    "typical_weekday_5pct_v2_activity_modechoice/"
                    "plans_routed_5pct_v2.xml.gz"
                ),
                "sha256_before": canonical_hashes_before["plans_routed"],
                "sha256_after": canonical_hashes_after["plans_routed"],
            },
            "network": {
                "role_path": (
                    "data/transit/hongkong/processed/"
                    "matsim_road_pt_supply_2026_hybrid_capacity_mixed_"
                    "bus_pcu005_ferry_core_v1_cap010/network.xml.gz"
                ),
                "sha256_before": canonical_hashes_before["network"],
                "sha256_after": canonical_hashes_after["network"],
            },
        },
        "existing_car_cost_v1_file_hashes_before": (
            internal_hashes_before
        ),
        "existing_car_cost_v1_file_hashes_after": internal_hashes_after,
        "all_protected_hashes_unchanged": hashes_unchanged,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    event_scenarios.to_parquet(
        args.output_dir / "car_toll_passage_events.parquet",
        index=False,
    )
    for scenario, frame in legs.items():
        frame.to_parquet(
            args.output_dir
            / f"car_leg_toll_cost_estimates_{scenario}.parquet",
            index=False,
        )
    summary.to_csv(
        args.output_dir / "toll_rate_application_summary.csv",
        index=False,
        encoding="utf-8",
    )
    required_repairs(validation).to_csv(
        args.output_dir / "toll_rate_required_repairs.csv",
        index=False,
        encoding="utf-8",
    )
    (
        args.output_dir / "toll_rate_application_validation.json"
    ).write_text(
        json.dumps(validation, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "toll_rate_input_hashes.json").write_text(
        json.dumps(input_hashes, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "physical_passage_events": int(len(events)),
                "event_scenario_rows": int(len(event_scenarios)),
                "facility_event_counts": validation[
                    "route_event_construction"
                ]["facility_event_counts"],
                "leg_status_counts_base": validation["leg_output"][
                    "status_counts"
                ]["base"],
                "totals_hkd": validation["leg_output"][
                    "resolved_charge_totals_hkd"
                ],
                "whc_alias_merged": validation[
                    "route_event_construction"
                ]["whc_alias_merged_event_count"],
                "separated_clusters": validation[
                    "route_event_construction"
                ][
                    "same_facility_multiple_spatial_cluster_leg_facility_count"
                ],
                "repeated_review": validation[
                    "route_event_construction"
                ]["repeated_facility_passage_review_count"],
                "protected": hashes_unchanged,
                "publishable_candidate": validation[
                    "publishable_candidate"
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
