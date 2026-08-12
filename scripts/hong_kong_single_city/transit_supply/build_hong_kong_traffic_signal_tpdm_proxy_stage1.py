#!/usr/bin/env python3
"""Build the Hong Kong territory-wide traffic-signal TPDM proxy Stage 1.

Stage 1 is deliberately limited to physical movement topology, planned demand
q, observed approach-flow comparisons, and approach-level TPDM saturation flow
S.  It does not create stages, cycles, green splits, offsets, controllers, or
MATSim signal XML.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Iterable, Sequence

from build_hong_kong_traffic_signal_pilot_v1 import (
    Link,
    Node,
    bearing_degrees,
    internal_nodes_for_junction,
    parse_network,
    read_csv,
    signed_turn_degrees,
    write_csv,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY = REPO_ROOT / "data/transit/hongkong/processed/hong_kong_traffic_signal_registry_2026_v1"
DEFAULT_SUPPLY = REPO_ROOT / "data/transit/hongkong/processed/matsim_road_pt_school_bus_supply_2026_v6_adoption_ready"
DEFAULT_NETWORK = DEFAULT_SUPPLY / "network.xml.gz"
DEFAULT_PLANS = REPO_ROOT / "data/matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice/plans_routed_5pct_v2.xml.gz"
DEFAULT_SCHEDULE = DEFAULT_SUPPLY / "transitSchedule_5pct_school_bus_v6.xml.gz"
DEFAULT_ROAD_AUDIT = REPO_ROOT / "data/transit/hongkong/processed/road_speed_capacity_2026_v1"
DEFAULT_OUTPUT = REPO_ROOT / "data/transit/hongkong/processed/hong_kong_traffic_signals_2026_v3_tpdm_proxy_stage1"

MODEL_STATUS = "territory_wide_tpdm_proxy_stage1_candidate_not_adopted"
TIME_BIN_SECONDS = 15 * 60
PRIVATE_CAR_EXPANSION = 20.0
LANE_WIDTH_M = 3.25
TPDM_NEARSIDE_BASE = 1940.0
TPDM_OTHER_BASE = 2080.0
TPDM_WIDTH_COEFFICIENT = 100.0
TPDM_UPHILL_COEFFICIENT = 42.0
MAX_INTERNAL_PATH_LINKS = 12
MAX_PATHS_PER_APPROACH = 2048

# Parameterised geometry classifier.  The two uncertainty bands deliberately
# produce ``ambiguous`` instead of forcing marginal angles into a turn class.
TURN_THRESHOLDS = {
    "ahead_max_abs_deg": 30.0,
    "turn_min_abs_deg": 45.0,
    "u_turn_ambiguous_min_abs_deg": 135.0,
    "u_turn_min_abs_deg": 150.0,
}

PCU_FACTORS = {
    "private_car": 1.0,
    "motorcycle": 0.4,
    "bus": 2.0,
    "gmb": 1.5,
    "school_bus": 2.0,
    "taxi": 1.0,
    "other_road_vehicle": 1.0,
}

TS_K006_V2_BOUNDARIES = {
    ("road_104550_0_f", "road_104660_0_r"): {
        "road_104562_0_f", "road_104564_0_f", "road_104676_0_f"
    },
    ("road_104673_0_f", "road_104674_0_f"): {
        "road_104562_0_f", "road_104648_0_f", "road_104676_0_f"
    },
    ("road_104664_0_f", "road_104563_0_f"): {
        "road_104564_0_f", "road_104648_0_f", "road_104676_0_f"
    },
    ("road_104537_0_f", "road_104675_0_r"): {
        "road_104562_0_f", "road_104564_0_f", "road_104648_0_f"
    },
}
VALIDATION_JUNCTIONS = {
    "TS_K006", "TS_K008", "TS_K005", "TS_K118",
    "TS_K024", "TS_K101", "TS_K201", "TS_K025",
}
VALIDATION_NETWORK_EXPRESSION = {
    "TS_K006": ("high", "pass_exact_v2_movement_boundary"),
    "TS_K008": ("low", "deferred_connector_fanout_crosses_drawn_phases"),
    "TS_K005": ("low", "deferred_connector_admits_diagram_excluded_turn"),
    "TS_K118": ("low", "deferred_network_recovers_fewer_approach_bundles_than_diagram_implies"),
    "TS_K024": ("low", "deferred_lane_level_protected_movements_not_separable"),
    "TS_K101": ("low", "deferred_diagram_not_uniquely_transcribable"),
    "TS_K201": ("low", "deferred_protected_turns_share_internal_connectors"),
    "TS_K025": ("low", "deferred_raster_insufficient_for_arrow_level_validation"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry-dir", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--network", type=Path, default=DEFAULT_NETWORK)
    parser.add_argument("--plans", type=Path, default=DEFAULT_PLANS)
    parser.add_argument("--transit-schedule", type=Path, default=DEFAULT_SCHEDULE)
    parser.add_argument("--road-audit-dir", type=Path, default=DEFAULT_ROAD_AUDIT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-internal-path-links", type=int, default=MAX_INTERNAL_PATH_LINKS)
    parser.add_argument("--max-paths-per-approach", type=int, default=MAX_PATHS_PER_APPROACH)
    return parser.parse_args()


def open_binary(path: Path):
    return gzip.open(path, "rb") if path.suffix == ".gz" else path.open("rb")


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_clock(value: str) -> float:
    parts = value.split(":")
    if len(parts) != 3:
        raise ValueError(f"Expected HH:MM:SS, got {value!r}")
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])


def time_bin(seconds: float) -> str:
    start = int(math.floor(seconds / TIME_BIN_SECONDS) * TIME_BIN_SECONDS)
    end = start + TIME_BIN_SECONDS
    def fmt(value: int) -> str:
        return f"{value // 3600:02d}:{value % 3600 // 60:02d}"
    return f"{fmt(start)}-{fmt(end)}"


def classify_turn(angle: float, thresholds: dict[str, float] = TURN_THRESHOLDS) -> str:
    absolute = abs(angle)
    if absolute >= thresholds["u_turn_min_abs_deg"]:
        return "u_turn"
    if absolute >= thresholds["u_turn_ambiguous_min_abs_deg"]:
        return "ambiguous"
    if absolute <= thresholds["ahead_max_abs_deg"]:
        return "ahead"
    if absolute < thresholds["turn_min_abs_deg"]:
        return "ambiguous"
    return "left" if angle > 0 else "right"


def stable_id(prefix: str, *parts: str) -> str:
    readable = "__".join(re.sub(r"[^A-Za-z0-9_.-]+", "_", item) for item in parts[:3])
    digest = hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:10]
    return f"{prefix}__{readable}__{digest}"


def enumerate_paths(
    approach: Link,
    internal_nodes: set[str],
    outgoing: dict[str, list[Link]],
    max_internal_links: int,
    max_paths: int,
) -> tuple[list[tuple[tuple[str, ...], Link]], bool]:
    """Enumerate simple physical paths after an approach up to the first exit."""
    paths: list[tuple[tuple[str, ...], Link]] = []
    truncated = False
    stack: list[tuple[str, tuple[str, ...], frozenset[str]]] = [
        (approach.to_node, (), frozenset({approach.from_node, approach.to_node}))
    ]
    while stack:
        node_id, internal_sequence, visited = stack.pop()
        for link in reversed(outgoing.get(node_id, [])):
            if "car" not in link.modes or link.to_node in visited:
                continue
            if link.to_node not in internal_nodes:
                paths.append((internal_sequence, link))
                if len(paths) >= max_paths:
                    return paths, True
                continue
            if len(internal_sequence) >= max_internal_links:
                truncated = True
                continue
            stack.append(
                (link.to_node, internal_sequence + (link.link_id,), visited | {link.to_node})
            )
    paths.sort(key=lambda item: (item[1].link_id, len(item[0]), item[0]))
    return paths, truncated


def build_topology(
    registry_rows: list[dict[str, str]],
    candidate_rows: list[dict[str, str]],
    nodes: dict[str, Node],
    links: dict[str, Link],
    max_internal_links: int,
    max_paths: int,
) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict], dict]:
    candidate_pairs = {
        (row["signal_junction_id"], row["controlled_link_candidate_id"])
        for row in candidate_rows
    }
    outgoing: dict[str, list[Link]] = defaultdict(list)
    incoming: dict[str, list[Link]] = defaultdict(list)
    for link in links.values():
        if "car" in link.modes:
            outgoing[link.from_node].append(link)
            incoming[link.to_node].append(link)
    for values in outgoing.values():
        values.sort(key=lambda item: item.link_id)
    for values in incoming.values():
        values.sort(key=lambda item: item.link_id)

    movements: list[dict] = []
    approaches: list[dict] = []
    exceptions: list[dict] = []
    uturns: list[dict] = []
    junction_audit: list[dict] = []
    path_multiplicity: Counter[tuple[str, str, str]] = Counter()

    for registry in registry_rows:
        junction_id = registry["signal_junction_id"]
        seed_ids = set(filter(None, registry["mapped_network_node_ids"].split("|")))
        missing_seeds = sorted(seed_ids.difference(nodes))
        internal_nodes: set[str] = set()
        radius = 0.0
        if not seed_ids:
            exceptions.append({
                "signal_junction_id": junction_id, "approach_id": "", "movement_id": "",
                "exception_type": "no_mapped_network_seed", "severity": "error",
                "detail": "Registry has no mapped MATSim road node.",
            })
        elif missing_seeds:
            exceptions.append({
                "signal_junction_id": junction_id, "approach_id": "", "movement_id": "",
                "exception_type": "mapped_seed_missing_from_network", "severity": "error",
                "detail": "|".join(missing_seeds),
            })
        else:
            internal_nodes, radius = internal_nodes_for_junction(
                (float(registry["x_epsg32650"]), float(registry["y_epsg32650"])),
                seed_ids, nodes, links,
            )

        junction_approaches = sorted(
            {
                link.link_id: link
                for node_id in internal_nodes
                for link in incoming.get(node_id, ())
                if link.from_node not in internal_nodes
            }.values(),
            key=lambda item: item.link_id,
        ) if internal_nodes else []
        junction_movement_start = len(movements)
        topology_ambiguous = False
        exit_ids: set[str] = set()

        for approach in junction_approaches:
            approach_id = stable_id("approach", junction_id, approach.link_id)
            bearing = bearing_degrees(nodes[approach.from_node], nodes[approach.to_node])
            paths, truncated = enumerate_paths(
                approach, internal_nodes, outgoing, max_internal_links, max_paths
            )
            if truncated:
                topology_ambiguous = True
                exceptions.append({
                    "signal_junction_id": junction_id, "approach_id": approach_id,
                    "movement_id": "", "exception_type": "path_enumeration_truncated",
                    "severity": "error",
                    "detail": f"limit_internal_links={max_internal_links};limit_paths={max_paths}",
                })
            if not paths:
                exceptions.append({
                    "signal_junction_id": junction_id, "approach_id": approach_id,
                    "movement_id": "", "exception_type": "approach_has_no_reachable_exit",
                    "severity": "error", "detail": approach.link_id,
                })
            approaches.append({
                "signal_junction_id": junction_id,
                "approach_id": approach_id,
                "from_link_id": approach.link_id,
                "from_node_id": approach.from_node,
                "stopline_node_id": approach.to_node,
                "approach_bearing_deg": round(bearing, 6),
                "lanes": approach.lanes,
                "network_capacity_veh_h": approach.capacity_veh_h,
                "registry_candidate_status": (
                    "candidate_incoming_link" if (junction_id, approach.link_id) in candidate_pairs
                    else "recovered_from_micro_node_cluster"
                ),
                "movement_count": len(paths),
                "approach_topology_confidence": (
                    "review" if truncated or not paths else
                    "high" if registry["confidence"] == "high" and (junction_id, approach.link_id) in candidate_pairs
                    else "medium"
                ),
                "evidence": "model_derived_network_topology",
                "review_flag": str(truncated or not paths).lower(),
            })

            for internal_sequence, exit_link in paths:
                exit_ids.add(exit_link.link_id)
                exit_bearing = bearing_degrees(nodes[exit_link.from_node], nodes[exit_link.to_node])
                angle = signed_turn_degrees(bearing, exit_bearing)
                movement_type = classify_turn(angle)
                first_internal = internal_sequence[0] if internal_sequence else ""
                identity_parts = (
                    junction_id, approach.link_id, first_internal, exit_link.link_id,
                    "|".join(internal_sequence),
                )
                movement_id = stable_id("movement", *identity_parts)
                path_multiplicity[(junction_id, approach.link_id, exit_link.link_id)] += 1
                diagram_supported = (
                    junction_id == "TS_K006"
                    and (approach.link_id, first_internal) in TS_K006_V2_BOUNDARIES
                    and exit_link.link_id in TS_K006_V2_BOUNDARIES[(approach.link_id, first_internal)]
                    and movement_type != "u_turn"
                )
                if movement_type == "u_turn":
                    legal_status = "excluded_no_positive_evidence"
                    evidence = "model_derived_topology_no_positive_legal_evidence"
                elif diagram_supported:
                    legal_status = "supported_by_published_diagram"
                    evidence = "observed_diagram_plus_model_derived_topology"
                else:
                    legal_status = "unresolved"
                    evidence = "model_derived_topology_legal_permission_unresolved"
                review = movement_type == "ambiguous" or legal_status != "supported_by_published_diagram"
                confidence = (
                    "high" if diagram_supported else
                    "review" if movement_type in {"u_turn", "ambiguous"} or truncated
                    else "medium"
                )
                row = {
                    "signal_junction_id": junction_id,
                    "approach_id": approach_id,
                    "movement_id": movement_id,
                    "from_link_id": approach.link_id,
                    "first_internal_link_id": first_internal,
                    "exit_link_id": exit_link.link_id,
                    "internal_link_sequence": "|".join(internal_sequence),
                    "from_node_id": approach.from_node,
                    "exit_node_id": exit_link.to_node,
                    "approach_bearing_deg": round(bearing, 6),
                    "exit_bearing_deg": round(exit_bearing, 6),
                    "turn_angle_deg": round(angle, 6),
                    "movement_type": movement_type,
                    "movement_topology_confidence": confidence,
                    "movement_evidence": evidence,
                    "legal_status": legal_status,
                    "review_flag": str(review).lower(),
                }
                movements.append(row)
                if movement_type == "u_turn":
                    uturns.append({
                        **row,
                        "candidate_status": "u_turn_candidate",
                        "activation_status": "not_activated",
                        "required_positive_evidence": "OSM restriction/access/lane tag or official layout",
                    })

        junction_movements = movements[junction_movement_start:]
        for movement in junction_movements:
            multiplicity = path_multiplicity[
                (junction_id, movement["from_link_id"], movement["exit_link_id"])
            ]
            if multiplicity > 1:
                topology_ambiguous = True
                movement["movement_topology_confidence"] = "review"
                movement["review_flag"] = "true"
                exceptions.append({
                    "signal_junction_id": junction_id,
                    "approach_id": movement["approach_id"],
                    "movement_id": movement["movement_id"],
                    "exception_type": "multiple_internal_paths_same_boundary",
                    "severity": "review",
                    "detail": f"path_count={multiplicity}",
                })
            if movement["legal_status"] == "unresolved":
                exceptions.append({
                    "signal_junction_id": junction_id,
                    "approach_id": movement["approach_id"],
                    "movement_id": movement["movement_id"],
                    "exception_type": "movement_legal_permission_unresolved",
                    "severity": "review",
                    "detail": "Topology/one-way/access permits routing; lane-level turn legality unavailable.",
                })
        first_exit = defaultdict(set)
        for movement in junction_movements:
            first_exit[(movement["from_link_id"], movement["first_internal_link_id"])].add(movement["exit_link_id"])
        fanout_count = sum(1 for exits in first_exit.values() if len(exits) > 1)
        if fanout_count:
            topology_ambiguous = True
        expression_status = (
            "unexpressed" if not junction_approaches or not junction_movements
            else "review" if topology_ambiguous
            else "expressed"
        )
        stage1_confidence = (
            "review" if expression_status != "expressed"
            else "high" if registry["confidence"] == "high"
            else "medium"
        )
        junction_audit.append({
            "signal_junction_id": junction_id,
            "registry_confidence": registry["confidence"],
            "source_coverage": registry["source_coverage"],
            "validation_set_status": "published_diagram_validation_set" if junction_id in VALIDATION_JUNCTIONS else "not_in_validation_set",
            "diagram_network_expression_confidence": VALIDATION_NETWORK_EXPRESSION.get(junction_id, ("", ""))[0],
            "diagram_movement_validation_result": VALIDATION_NETWORK_EXPRESSION.get(junction_id, ("", ""))[1],
            "mapped_seed_count": len(seed_ids),
            "internal_node_count": len(internal_nodes),
            "internal_radius_m": round(radius, 3),
            "approach_count": len(junction_approaches),
            "exit_count": len(exit_ids),
            "movement_count": len(junction_movements),
            "first_connector_multiple_exit_count": fanout_count,
            "topology_ambiguous": str(topology_ambiguous).lower(),
            "network_expression_status": expression_status,
            "junction_stage1_confidence": stage1_confidence,
        })

    signature_groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for movement in movements:
        if movement["legal_status"] != "excluded_no_positive_evidence":
            signature_groups[(
                movement["from_link_id"], movement["internal_link_sequence"], movement["exit_link_id"]
            )].append(movement)
    shared_signatures = {key: values for key, values in signature_groups.items() if len(values) > 1}
    affected_junctions: Counter[str] = Counter()
    for signature, shared_movements in shared_signatures.items():
        junction_ids = sorted({movement["signal_junction_id"] for movement in shared_movements})
        for movement in shared_movements:
            movement["movement_topology_confidence"] = "review"
            movement["review_flag"] = "true"
            movement["demand_match_status"] = "excluded_shared_physical_path_between_registry_groups"
            affected_junctions[movement["signal_junction_id"]] += 1
            exceptions.append({
                "signal_junction_id": movement["signal_junction_id"],
                "approach_id": movement["approach_id"],
                "movement_id": movement["movement_id"],
                "exception_type": "physical_path_shared_by_multiple_registry_junctions",
                "severity": "error",
                "detail": "registry_junctions=" + "|".join(junction_ids),
            })
    for movement in movements:
        movement.setdefault("demand_match_status", "eligible_unique_physical_path")
    for row in junction_audit:
        count = affected_junctions[row["signal_junction_id"]]
        row["shared_physical_movement_count"] = count
        if count:
            row["topology_ambiguous"] = "true"
            row["network_expression_status"] = "review"
            row["junction_stage1_confidence"] = "review"

    actual_k006: dict[tuple[str, str], set[str]] = defaultdict(set)
    for movement in movements:
        if movement["signal_junction_id"] == "TS_K006" and movement["movement_type"] != "u_turn":
            key = (movement["from_link_id"], movement["first_internal_link_id"])
            if key in TS_K006_V2_BOUNDARIES:
                actual_k006[key].add(movement["exit_link_id"])
    regression = {
        "status": "pass" if dict(actual_k006) == TS_K006_V2_BOUNDARIES else "fail",
        "expected": {" -> ".join(key): sorted(value) for key, value in TS_K006_V2_BOUNDARIES.items()},
        "actual": {" -> ".join(key): sorted(value) for key, value in actual_k006.items()},
    }
    if regression["status"] != "pass":
        raise RuntimeError("TS_K006 automatic movement boundary differs from audited v2 truth: " + json.dumps(regression))
    return movements, approaches, exceptions, uturns, junction_audit, regression


def normalise_route_links(route_element) -> list[str]:
    values = []
    start = route_element.get("start_link", "")
    end = route_element.get("end_link", "")
    if start:
        values.append(start)
    values.extend((route_element.text or "").split())
    if end:
        values.append(end)
    result: list[str] = []
    for value in values:
        if not result or result[-1] != value:
            result.append(value)
    return result


def movement_matcher(movements: list[dict]) -> dict[str, list[tuple[tuple[str, ...], dict]]]:
    result: dict[str, list[tuple[tuple[str, ...], dict]]] = defaultdict(list)
    for movement in movements:
        # Excluded U-turns are registered but do not enter design demand.
        if (
            movement["legal_status"] == "excluded_no_positive_evidence"
            or movement.get("demand_match_status") == "excluded_shared_physical_path_between_registry_groups"
        ):
            continue
        suffix = tuple(filter(None, movement["internal_link_sequence"].split("|"))) + (movement["exit_link_id"],)
        result[movement["from_link_id"]].append((suffix, movement))
    for values in result.values():
        values.sort(key=lambda item: (-len(item[0]), item[1]["movement_id"]))
    return result


def route_crossings(
    route_links: Sequence[str],
    links: dict[str, Link],
    matcher: dict[str, list[tuple[tuple[str, ...], dict]]],
) -> list[tuple[dict, float]]:
    result: list[tuple[dict, float]] = []
    elapsed = 0.0
    for index, link_id in enumerate(route_links):
        link = links.get(link_id)
        if link is None:
            continue
        elapsed += link.length_m / max(link.freespeed_m_s, 0.01)
        candidates = matcher.get(link_id, ())
        for suffix, movement in candidates:
            if tuple(route_links[index + 1:index + 1 + len(suffix)]) == suffix:
                result.append((movement, elapsed))
                break
    return result


def add_demand(
    store: dict[tuple[str, str], list[float]],
    movement: dict,
    arrival: float,
    vehicle_class: str,
    expansion: float,
) -> None:
    key = (movement["movement_id"], time_bin(arrival))
    values = store.setdefault(key + (vehicle_class,), [0.0, 0.0])
    values[0] += 1.0
    values[1] += expansion


def extract_demand(
    plans: Path,
    schedule: Path,
    links: dict[str, Link],
    movements: list[dict],
) -> tuple[list[dict], list[dict], list[dict], list[dict], dict]:
    from lxml import etree as ET

    matcher = movement_matcher(movements)
    movement_by_id = {row["movement_id"]: row for row in movements}
    demand: dict[tuple[str, str, str], list[float]] = {}
    source_counts = Counter()
    nonphysical_counts = Counter()
    matched_crossings = Counter()

    with open_binary(plans) as stream:
        for _, person in ET.iterparse(stream, events=("end",), tag="person"):
            person_attributes = {
                item.get("name"): (item.text or "")
                for item in person.findall("./attributes/attribute")
            }
            selected = next((plan for plan in person.findall("plan") if plan.get("selected") == "yes"), None)
            if selected is not None:
                for leg in selected.findall("leg"):
                    if leg.get("mode") == "ride":
                        nonphysical_counts["ride_generic_passenger_legs"] += 1
                        if person_attributes.get("modeDetail") == "taxi":
                            nonphysical_counts["taxi_passenger_legs"] += 1
                    if leg.get("mode") != "car":
                        continue
                    route = leg.find("route")
                    if route is None or route.get("type") != "links":
                        continue
                    source_counts["private_car"] += 1
                    departure = parse_clock(leg.get("dep_time", "00:00:00"))
                    for movement, offset in route_crossings(normalise_route_links(route), links, matcher):
                        add_demand(demand, movement, departure + offset, "private_car", PRIVATE_CAR_EXPANSION)
                        matched_crossings["private_car"] += 1
            person.clear()

    road_transit_modes = {"bus": "bus", "gmb": "gmb", "school_bus": "school_bus"}
    with open_binary(schedule) as stream:
        for _, transit_route in ET.iterparse(stream, events=("end",), tag="transitRoute"):
            mode_element = transit_route.find("transportMode")
            mode = (mode_element.text or "").strip() if mode_element is not None else ""
            vehicle_class = road_transit_modes.get(mode)
            if vehicle_class:
                route_element = transit_route.find("route")
                route_links = [element.get("refId") for element in route_element.findall("link")] if route_element is not None else []
                crossings = route_crossings(route_links, links, matcher)
                departures = transit_route.find("departures")
                for departure in departures.findall("departure") if departures is not None else ():
                    source_counts[vehicle_class] += 1
                    departure_time = parse_clock(departure.get("departureTime"))
                    for movement, offset in crossings:
                        add_demand(demand, movement, departure_time + offset, vehicle_class, 1.0)
                        matched_crossings[vehicle_class] += 1
            transit_route.clear()

    scaling_spec = {
        "private_car": ("sampled_5pct_resident_vehicle_demand", PRIVATE_CAR_EXPANSION, "routed_selected_car_legs", "high", "Project documentation confirms the population is a 5% whole-person sample."),
        "motorcycle": ("not_present_as_routed_vehicle_class", 1.0, "no_physical_route_in_selected_plans", "high", "No motorcycle leg mode occurs in the selected routed plans."),
        "bus": ("full_operational_timetable", 1.0, "transit_schedule_departures", "high", "Complete timetable; QSim 5% PCU is not a TPDM demand factor."),
        "gmb": ("full_operational_timetable", 1.0, "transit_schedule_departures", "high", "Complete timetable; QSim 5% PCU is not a TPDM demand factor."),
        "school_bus": ("full_supply_proxy", 1.0, "v6_proxy_departures", "medium", "6,878 AM/PM physical proxy routes; not expanded with residents."),
        "taxi": ("missing_from_physical_network", 1.0, "teleported_passenger_mode_no_QVehicle", "high", f"Taxi passenger demand has no routed physical road vehicle; {nonphysical_counts['taxi_passenger_legs']} sampled taxi-labelled passenger legs ({nonphysical_counts['taxi_passenger_legs'] * PRIVATE_CAR_EXPANSION:g} fullscale passenger-leg equivalents) are not fabricated as Taxi QVehicles."),
        "other_road_vehicle": ("not_present", 1.0, "no_supported_physical_route_source", "medium", "No separately classified routed road vehicle source found."),
    }
    scaling_rows = []
    for vehicle_class, (status, factor, method, confidence, notes) in scaling_spec.items():
        scaling_rows.append({
            "vehicle_class": vehicle_class,
            "raw_model_count": source_counts[vehicle_class],
            "sampling_status": status,
            "expansion_factor": factor,
            "tpdm_pcu_factor": PCU_FACTORS[vehicle_class],
            "fullscale_equivalent_method": method,
            "evidence": "observed_project_input" if source_counts[vehicle_class] else "unresolved_or_absent_input",
            "confidence": confidence,
            "notes": notes,
        })

    movement_rows = []
    for (movement_id, bin_label, vehicle_class), (raw, fullscale) in sorted(demand.items()):
        movement = movement_by_id[movement_id]
        pcu = fullscale * PCU_FACTORS[vehicle_class]
        movement_rows.append({
            "signal_junction_id": movement["signal_junction_id"],
            "approach_id": movement["approach_id"],
            "movement_id": movement_id,
            "time_bin": bin_label,
            "vehicle_class": vehicle_class,
            "raw_vehicle_count": round(raw, 6),
            "expansion_factor": PRIVATE_CAR_EXPANSION if vehicle_class == "private_car" else 1.0,
            "fullscale_vehicle_count": round(fullscale, 6),
            "tpdm_pcu_factor": PCU_FACTORS[vehicle_class],
            "tpdm_pcu_count": round(pcu, 6),
            "tpdm_pcu_per_hour": round(pcu * 4.0, 6),
            "arrival_time_method": "freeflow_route_propagation",
            "demand_source": "routed_plans" if vehicle_class == "private_car" else "transit_schedule",
            "demand_confidence": "high" if vehicle_class in {"private_car", "bus", "gmb"} else "medium",
        })

    def aggregate(keys: Sequence[str], id_fields: Sequence[str]) -> list[dict]:
        totals: dict[tuple, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
        for row in movement_rows:
            key = tuple(row[field] for field in keys)
            totals[key][0] += float(row["raw_vehicle_count"])
            totals[key][1] += float(row["fullscale_vehicle_count"])
            totals[key][2] += float(row["tpdm_pcu_count"])
        result = []
        for key, values in sorted(totals.items()):
            row = dict(zip(keys, key))
            row.update({
                "raw_vehicle_count": round(values[0], 6),
                "fullscale_vehicle_count": round(values[1], 6),
                "tpdm_pcu_count": round(values[2], 6),
                "tpdm_pcu_per_hour": round(values[2] * 4.0, 6),
                "arrival_time_method": "freeflow_route_propagation",
            })
            result.append(row)
        return result

    approach_rows = aggregate(
        ("signal_junction_id", "approach_id", "time_bin", "vehicle_class"),
        ("signal_junction_id", "approach_id"),
    )
    junction_rows = aggregate(
        ("signal_junction_id", "time_bin", "vehicle_class"),
        ("signal_junction_id",),
    )
    demand_summary = {
        "raw_source_vehicle_count_by_class": dict(source_counts),
        "matched_signal_movement_crossings_by_class": dict(matched_crossings),
        "fullscale_movement_vehicle_count_by_class": dict(Counter({
            vehicle_class: sum(values[1] for key, values in demand.items() if key[2] == vehicle_class)
            for vehicle_class in scaling_spec
        })),
        "tpdm_movement_pcu_count_by_class": {
            vehicle_class: sum(values[1] for key, values in demand.items() if key[2] == vehicle_class) * PCU_FACTORS[vehicle_class]
            for vehicle_class in scaling_spec
        },
        "taxi_road_demand_status": "missing_from_physical_network",
        "generic_ride_passenger_legs_without_physical_qvehicle": nonphysical_counts["ride_generic_passenger_legs"],
        "taxi_labelled_sampled_passenger_legs_without_physical_qvehicle": nonphysical_counts["taxi_passenger_legs"],
        "taxi_labelled_fullscale_passenger_leg_equivalent_not_vehicle_demand": nonphysical_counts["taxi_passenger_legs"] * PRIVATE_CAR_EXPANSION,
        "movement_rows_excluded_from_q_due_to_shared_registry_path": sum(
            row.get("demand_match_status") == "excluded_shared_physical_path_between_registry_groups"
            for row in movements
        ),
    }
    return scaling_rows, movement_rows, approach_rows, junction_rows, demand_summary


def route_direction(link_id: str, link_attribute_rows: dict[str, dict]) -> tuple[str, str]:
    row = link_attribute_rows.get(link_id)
    if row:
        return row["route_id"], row["direction"]
    match = re.fullmatch(r"road_(.+)_\d+_([fr])", link_id)
    return (match.group(1), match.group(2)) if match else ("", "")


def build_anchors(
    road_audit_dir: Path,
    approaches: list[dict],
    approach_demand: list[dict],
) -> tuple[list[dict], dict]:
    link_attributes = {
        row["link_id"]: row for row in read_csv(road_audit_dir / "matsim_link_attributes.csv")
    }
    approaches_by_route: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for approach in approaches:
        route, direction = route_direction(approach["from_link_id"], link_attributes)
        if route:
            approaches_by_route[(route, direction)].append(approach)

    raw_by_bin: dict[tuple[str, str], float] = defaultdict(float)
    for row in approach_demand:
        raw_by_bin[(row["approach_id"], row["time_bin"])] += float(row["fullscale_vehicle_count"]) * 4.0

    anchor_rows: list[dict] = []
    detector_xwalk = {
        row["AID_ID_Number"]: row
        for row in read_csv(road_audit_dir / "traffic_detector_route_crosswalk.csv")
        if row["match_status"] == "matched"
    }
    detector_groups: dict[tuple[str, str, str], list[tuple[float, float, str]]] = defaultdict(list)
    for row in read_csv(road_audit_dir / "traffic_detector_15min_windows.csv"):
        xwalk = detector_xwalk.get(row["detector_id"])
        if not xwalk:
            continue
        label = time_bin(datetime.fromisoformat(row["window_start"]).hour * 3600 + datetime.fromisoformat(row["window_start"]).minute * 60)
        detector_groups[(xwalk["route_id"], xwalk["matched_direction"], label)].append(
            (float(row["flow_rate_vphpl"]), float(row["observed_seconds"]), row["detector_id"])
        )
    for (route, direction, label), observations in detector_groups.items():
        for approach in approaches_by_route.get((route, direction), ()):
            observed_seconds = median(value[1] for value in observations)
            observed_q = median(value[0] for value in observations) * float(approach["lanes"])
            confidence = "medium" if observed_seconds >= 450 else "low"
            raw_q = raw_by_bin[(approach["approach_id"], label)]
            anchored = observed_q if confidence == "medium" else raw_q
            anchor_rows.append({
                "signal_junction_id": approach["signal_junction_id"],
                "approach_id": approach["approach_id"],
                "time_period": label,
                "model_raw_approach_q_veh_h": round(raw_q, 6),
                "observed_approach_q_veh_h": round(observed_q, 6),
                "observed_source": "traffic_detector_observed_volume_vphpl_times_network_lanes",
                "observed_source_ids": "|".join(sorted({value[2] for value in observations})),
                "observed_coverage": f"median_observed_seconds={observed_seconds:g}",
                "turning_share_source": "model_derived_15min" if raw_q > 0 else "unavailable_zero_model_demand",
                "anchored_approach_q_veh_h": round(anchored, 6),
                "difference_ratio": round((observed_q - raw_q) / raw_q, 6) if raw_q else "",
                "confidence": confidence,
                "anchor_action": "observed_anchor" if confidence == "medium" else "retain_model_low_quality_observation",
            })

    atc_xwalk: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in read_csv(road_audit_dir / "atc_direction_route_crosswalk.csv"):
        if row["match_status"] == "matched":
            atc_xwalk[(row["station_no"], row["direction"])].append(row)
    for flow in read_csv(road_audit_dir / "atc_directional_details_2024.csv"):
        for xwalk in atc_xwalk.get((flow["station_no"], flow["direction"]), ()):
            route_key = (xwalk["route_id"], xwalk["matched_direction"])
            for approach in approaches_by_route.get(route_key, ()):
                for period, field, start_hour, end_hour in (
                    ("weekday_am_peak", "weekday_am_peak_flow", 7, 10),
                    ("weekday_pm_peak", "weekday_pm_peak_flow", 16, 19),
                ):
                    if not flow[field]:
                        continue
                    bins = [
                        value for (approach_id, label), value in raw_by_bin.items()
                        if approach_id == approach["approach_id"]
                        and start_hour <= int(label[:2]) < end_hour
                    ]
                    raw_q = max(bins, default=0.0)
                    observed_q = float(flow[field])
                    confidence = (
                        "high" if float(xwalk["match_score"]) >= 0.9 and float(xwalk["match_distance_m"]) <= 30
                        else "medium"
                    )
                    anchor_rows.append({
                        "signal_junction_id": approach["signal_junction_id"],
                        "approach_id": approach["approach_id"],
                        "time_period": period,
                        "model_raw_approach_q_veh_h": round(raw_q, 6),
                        "observed_approach_q_veh_h": round(observed_q, 6),
                        "observed_source": "transport_department_atc_directional_peak_flow",
                        "observed_source_ids": f"ATC_{flow['station_no']}_{flow['direction']}",
                        "observed_coverage": "weekday_directional_peak_hour",
                        "turning_share_source": "model_derived_peak_15min" if raw_q > 0 else "unavailable_zero_model_demand",
                        "anchored_approach_q_veh_h": round(observed_q, 6),
                        "difference_ratio": round((observed_q - raw_q) / raw_q, 6) if raw_q else "",
                        "confidence": confidence,
                        "anchor_action": "observed_anchor",
                    })
    anchor_rows.sort(key=lambda row: (row["signal_junction_id"], row["approach_id"], row["time_period"], row["observed_source"]))
    ratios = [float(row["difference_ratio"]) for row in anchor_rows if row["difference_ratio"] != ""]
    summary = {
        "anchored_approach_count": len({row["approach_id"] for row in anchor_rows if row["anchor_action"] == "observed_anchor"}),
        "detector_anchor_approach_count": len({row["approach_id"] for row in anchor_rows if row["observed_source"].startswith("traffic_detector")}),
        "atc_anchor_approach_count": len({row["approach_id"] for row in anchor_rows if row["observed_source"].startswith("transport_department")}),
        "model_observed_difference_ratio_distribution": {
            "count": len(ratios),
            "min": min(ratios) if ratios else None,
            "median": median(ratios) if ratios else None,
            "max": max(ratios) if ratios else None,
        },
    }
    return anchor_rows, summary


def build_saturation(approaches: list[dict], road_audit_dir: Path) -> tuple[list[dict], list[dict], dict]:
    link_attributes = {
        row["link_id"]: row for row in read_csv(road_audit_dir / "matsim_link_attributes.csv")
    }
    rows = []
    audit = []
    for approach in approaches:
        lane_value = float(approach["lanes"])
        lane_count = max(1, int(round(lane_value)))
        nearside = TPDM_NEARSIDE_BASE + TPDM_WIDTH_COEFFICIENT * (LANE_WIDTH_M - 3.25)
        other = TPDM_OTHER_BASE + TPDM_WIDTH_COEFFICIENT * (LANE_WIDTH_M - 3.25)
        gradient_adjustment = 0.0
        saturation = nearside + max(0, lane_count - 1) * other + gradient_adjustment
        lane_evidence = (
            "road_capacity_workflow_model_derived"
            if approach["from_link_id"] in link_attributes
            else "network_permlanes_model_derived"
        )
        capacity = float(approach["network_capacity_veh_h"])
        row = {
            "signal_junction_id": approach["signal_junction_id"],
            "approach_id": approach["approach_id"],
            "from_link_id": approach["from_link_id"],
            "lane_count_input": lane_value,
            "lane_count_used": lane_count,
            "lane_count_evidence": lane_evidence,
            "lane_width_m": LANE_WIDTH_M,
            "lane_width_evidence": "default_tpdm_reference",
            "gradient_percent": 0.0,
            "gradient_adjustment_pcu_h": gradient_adjustment,
            "gradient_evidence": "unavailable_no_adjustment",
            "nearside_lane_saturation_pcu_h": nearside,
            "other_lane_saturation_pcu_h_lane": other,
            "approach_saturation_flow_pcu_h": saturation,
            "saturation_status": "approach_saturation_proxy",
            "current_network_capacity_veh_h": capacity,
            "network_capacity_to_tpdm_s_ratio": round(capacity / saturation, 6),
            "capacity_separation": "comparison_only_network_not_modified",
        }
        rows.append(row)
        audit.append({
            "signal_junction_id": approach["signal_junction_id"],
            "approach_id": approach["approach_id"],
            "assumption": "TPDM_Vol4_nearside_plus_other_lanes",
            "formula": "1940+100*(W-3.25)+(N-1)*(2080+100*(W-3.25))-42*uphill_percent_per_lane",
            "lane_count_evidence": lane_evidence,
            "lane_width_evidence": "default_tpdm_reference",
            "gradient_evidence": "unavailable_no_adjustment",
            "movement_specific_allocation": "not_performed_no_lane_to_movement_mapping",
            "review_flag": str(abs(lane_value - lane_count) > 1e-9).lower(),
        })
    values = [float(row["approach_saturation_flow_pcu_h"]) for row in rows]
    ratios = [float(row["network_capacity_to_tpdm_s_ratio"]) for row in rows]
    summary = {
        "approach_count": len(rows),
        "lane_count_evidence_distribution": dict(Counter(row["lane_count_evidence"] for row in rows)),
        "lane_width_evidence_distribution": dict(Counter(row["lane_width_evidence"] for row in rows)),
        "gradient_evidence_distribution": dict(Counter(row["gradient_evidence"] for row in rows)),
        "approach_saturation_flow_pcu_h_distribution": {
            "min": min(values) if values else None, "median": median(values) if values else None,
            "max": max(values) if values else None,
        },
        "network_capacity_to_tpdm_s_ratio_distribution": {
            "min": min(ratios) if ratios else None, "median": median(ratios) if ratios else None,
            "max": max(ratios) if ratios else None,
        },
        "network_modified": False,
    }
    return rows, audit, summary


def write_table(path: Path, rows: list[dict], fallback_fields: Sequence[str]) -> None:
    write_csv(path, rows, list(rows[0]) if rows else fallback_fields)


def main() -> None:
    args = parse_args()
    required = [
        args.registry_dir / "hong_kong_signal_junctions.csv",
        args.registry_dir / "signal_controlled_link_candidates.csv",
        args.network, args.plans, args.transit_schedule,
        args.road_audit_dir / "matsim_link_attributes.csv",
        args.road_audit_dir / "traffic_detector_route_crosswalk.csv",
        args.road_audit_dir / "traffic_detector_15min_windows.csv",
        args.road_audit_dir / "atc_direction_route_crosswalk.csv",
        args.road_audit_dir / "atc_directional_details_2024.csv",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing Stage-1 inputs:\n" + "\n".join(missing))

    registry_rows = read_csv(required[0])
    if len(registry_rows) != 2054:
        raise ValueError(f"Canonical registry must contain 2,054 junctions, got {len(registry_rows)}")
    candidate_rows = read_csv(required[1])
    _, nodes, links = parse_network(args.network)
    movements, approaches, exceptions, uturns, junction_audit, regression = build_topology(
        registry_rows, candidate_rows, nodes, links,
        args.max_internal_path_links, args.max_paths_per_approach,
    )
    scaling, movement_demand, approach_demand, junction_demand, demand_summary = extract_demand(
        args.plans, args.transit_schedule, links, movements
    )
    anchors, anchor_summary = build_anchors(args.road_audit_dir, approaches, approach_demand)
    saturation, saturation_audit, saturation_summary = build_saturation(approaches, args.road_audit_dir)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_table(args.output_dir / "signal_movements.csv", movements, ("signal_junction_id", "movement_id"))
    write_table(args.output_dir / "signal_approaches.csv", approaches, ("signal_junction_id", "approach_id"))
    write_table(args.output_dir / "movement_topology_exceptions.csv", exceptions, ("signal_junction_id", "exception_type"))
    write_table(args.output_dir / "u_turn_candidates.csv", uturns, ("signal_junction_id", "movement_id"))
    write_table(args.output_dir / "junction_network_expression_audit.csv", junction_audit, ("signal_junction_id",))
    write_table(args.output_dir / "vehicle_class_demand_scaling.csv", scaling, ("vehicle_class",))
    write_table(args.output_dir / "movement_demand_15min.csv", movement_demand, ("movement_id", "time_bin"))
    write_table(args.output_dir / "approach_demand_15min.csv", approach_demand, ("approach_id", "time_bin"))
    write_table(args.output_dir / "junction_demand_15min.csv", junction_demand, ("signal_junction_id", "time_bin"))
    write_table(args.output_dir / "approach_flow_anchor_audit.csv", anchors, ("signal_junction_id", "approach_id"))
    write_table(args.output_dir / "approach_saturation_flow.csv", saturation, ("approach_id",))
    write_table(args.output_dir / "saturation_flow_assumption_audit.csv", saturation_audit, ("approach_id",))

    expression_counts = Counter(row["network_expression_status"] for row in junction_audit)
    junction_confidence_counts = Counter(row["junction_stage1_confidence"] for row in junction_audit)
    confidence_rows = []
    for entity, rows, field in (
        ("junction_network_expression", junction_audit, "network_expression_status"),
        ("junction_stage1_confidence", junction_audit, "junction_stage1_confidence"),
        ("movement_topology", movements, "movement_topology_confidence"),
        ("approach_topology", approaches, "approach_topology_confidence"),
        ("observed_flow_anchor", anchors, "confidence"),
    ):
        counts = Counter(row[field] for row in rows)
        for confidence, count in sorted(counts.items()):
            confidence_rows.append({
                "entity_type": entity, "confidence_or_status": confidence,
                "count": count, "percent": round(100.0 * count / len(rows), 6) if rows else 0.0,
            })
    write_table(args.output_dir / "stage1_coverage_by_confidence.csv", confidence_rows, ("entity_type", "confidence_or_status"))

    movement_types = Counter(row["movement_type"] for row in movements)
    qa = {
        "status": MODEL_STATUS,
        "stage_boundary": {
            "included": ["movement_registry", "planned_demand_q", "approach_tpdm_saturation_flow_S"],
            "forbidden_outputs_created": False,
            "stage_cycle_green_split_offset_controller_or_signal_xml": "not_generated",
        },
        "junction_coverage": {
            "canonical_registry_junction_count": len(registry_rows),
            "junctions_with_approaches": sum(int(row["approach_count"]) > 0 for row in junction_audit),
            "junctions_with_movements": sum(int(row["movement_count"]) > 0 for row in junction_audit),
            "completely_unexpressed": expression_counts["unexpressed"],
            "expression_status_distribution": dict(expression_counts),
            "high_medium_review_distribution": dict(junction_confidence_counts),
        },
        "movement_topology": {
            "movement_count": len(movements),
            "movement_type_distribution": dict(movement_types),
            "excluded_u_turn_count": sum(row["legal_status"] == "excluded_no_positive_evidence" for row in movements),
            "unresolved_legal_movement_count": sum(row["legal_status"] == "unresolved" for row in movements),
            "first_connector_multiple_exit_count": sum(int(row["first_connector_multiple_exit_count"]) for row in junction_audit),
            "topology_ambiguous_junction_count": sum(row["topology_ambiguous"] == "true" for row in junction_audit),
            "path_enumeration_truncation_count": sum(row["exception_type"] == "path_enumeration_truncated" for row in exceptions),
            "physical_path_signature_shared_between_registry_groups_count": len({
                (row["from_link_id"], row["internal_link_sequence"], row["exit_link_id"])
                for row in movements
                if row.get("demand_match_status") == "excluded_shared_physical_path_between_registry_groups"
            }),
            "movement_rows_excluded_from_q_due_to_shared_registry_path": sum(
                row.get("demand_match_status") == "excluded_shared_physical_path_between_registry_groups"
                for row in movements
            ),
        },
        "demand_q": demand_summary,
        "observed_flow_anchors": anchor_summary,
        "saturation_flow_S": saturation_summary,
        "ts_k006_v2_regression": regression,
        "assumptions": {
            "turn_thresholds_deg": TURN_THRESHOLDS,
            "internal_path_limits": {"max_links": args.max_internal_path_links, "max_paths_per_approach": args.max_paths_per_approach},
            "arrival_time_method": "freeflow_route_propagation",
            "private_car_expansion": PRIVATE_CAR_EXPANSION,
            "tpdm_pcu_factors": PCU_FACTORS,
            "lane_width_m": LANE_WIDTH_M,
            "gradient": "unavailable_no_adjustment",
        },
    }
    metadata = {
        "status": MODEL_STATUS,
        "inputs": {
            "registry_dir": str(args.registry_dir.resolve()),
            "network": str(args.network.resolve()),
            "plans": str(args.plans.resolve()),
            "transit_schedule": str(args.transit_schedule.resolve()),
            "road_audit_dir": str(args.road_audit_dir.resolve()),
        },
        "model_version": "hong_kong_traffic_signals_2026_v3_tpdm_proxy_stage1",
        "builder": str(Path(__file__).resolve()),
        "provenance_note": "Paths identify actual inputs; hashes are provenance only and are not acceptance gates or model inputs.",
    }
    (args.output_dir / "stage1_qa_summary.json").write_text(json.dumps(qa, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (args.output_dir / "stage1_metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(qa, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
