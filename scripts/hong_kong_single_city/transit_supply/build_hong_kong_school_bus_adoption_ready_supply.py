#!/usr/bin/env python3
"""Build the Hong Kong school-bus v6 road-running MATSim supply candidate.

The builder keeps all v5 passenger capacities unscaled, reconstructs pickup
geometry for the 76 first-party route identities from the same campus-specific
student OD evidence used by v3, creates road-running inbound and outbound
services, and merges them into the active Ferry Core road/PT supply.

First-party identity is observed evidence. Its reconstructed pickup membership,
ordering, timing, and road geometry remain explicit model proxies; restricted
or unavailable published stop tables are not reproduced.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml
from lxml import etree as ET
from scipy.spatial import cKDTree

from map_match_hong_kong_school_bus_proxy_routes import (
    REPO_ROOT,
    TARGET_CRS,
    astar_path,
    optimise_pickup_order,
    parse_network,
    safe_float,
)


FORMAL_ROOT = Path(r"F:\Matsim\matsim-example-project")
PROJECT_ROOT = FORMAL_ROOT if FORMAL_ROOT.exists() else REPO_ROOT
ACTIVE_SUPPLY = (
    PROJECT_ROOT
    / "data/transit/hongkong/processed"
    / "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_ferry_core_v1_cap010"
)
V5_DIR = (
    REPO_ROOT
    / "data/school/hongkong/processed"
    / "school_bus_proxy_routes_2026_v5_time_split_fleet_cap3439"
)
V3_DIR = (
    REPO_ROOT
    / "data/school/hongkong/processed"
    / "school_bus_proxy_routes_2026_v3_school_probability_locked76"
)
STUDENT_OD = (
    PROJECT_ROOT
    / "data/school/hongkong/processed/student_school_od_2022"
    / "student_school_assignment_od.parquet"
)
CAMPUSES = (
    PROJECT_ROOT
    / "data/school/hongkong/processed/student_school_od_2022"
    / "school_campus_capacity_estimates.geojson"
)
GRIDS = (
    PROJECT_ROOT
    / "data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid"
    / "CityAndRegionSplit/hong_kong_fixed_link_grid/regions.shp"
)
ASSUMPTIONS = REPO_ROOT / "cities/hongkong/school_bus_proxy_assumptions.yaml"
OUTPUT_DIR = (
    REPO_ROOT
    / "data/transit/hongkong/processed"
    / "matsim_road_pt_school_bus_supply_2026_v6_adoption_ready"
)

AVERAGE_SPEED_M_S = 25.2 / 3.6
DWELL_SECONDS = 45.0
SCHOOL_BUS_MODE = "school_bus"
NETWORK_FILE = "network.xml.gz"
SCHEDULE_FILE = "transitSchedule_5pct_school_bus_v6.xml.gz"
VEHICLES_FILE = "transitVehicles_10pct_regular_school_bus_unscaled.xml.gz"
TIME_LIMIT_BY_STAGE = {
    "kindergarten": 60.0,
    "primary": 60.0,
    "secondary": 75.0,
    "special": 75.0,
}


@dataclass(frozen=True)
class RoutedSegment:
    source: int
    target: int
    node_indices: tuple[int, ...]
    link_ids: tuple[str, ...]
    length_m: float
    quality: str


@dataclass
class RouteDirection:
    direction: str
    stop_ids: list[str]
    stop_link_ids: list[str]
    route_link_ids: list[str]
    segment_lengths_m: list[float]
    path_quality: str
    directed_segment_count: int
    repaired_segment_count: int
    topology_connector_count: int
    reverse_link_count: int


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def read_xml_gz(path: Path) -> ET._ElementTree:
    with gzip.open(path, "rb") as handle:
        return ET.parse(handle)


def write_xml_gz(
    tree: ET._ElementTree,
    path: Path,
    fallback_doctype: str | None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doctype = tree.docinfo.doctype or fallback_doctype
    options: dict[str, Any] = {}
    if doctype:
        options["doctype"] = doctype
    with gzip.open(path, "wb", compresslevel=6) as handle:
        tree.write(
            handle,
            encoding="utf-8",
            xml_declaration=True,
            pretty_print=True,
            **options,
        )


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: Sequence[str]) -> None:
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def parse_clock(value: str) -> int:
    hour, minute, second = (int(part) for part in value.split(":"))
    return hour * 3600 + minute * 60 + second


def format_clock(seconds: float) -> str:
    rounded = max(0, int(round(seconds)))
    hour, remainder = divmod(rounded, 3600)
    minute, second = divmod(remainder, 60)
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def largest_remainder(weights: np.ndarray, target: int) -> np.ndarray:
    weights = np.asarray(weights, dtype=float)
    if target < 0 or not np.isfinite(weights).all() or (weights < 0).any():
        raise ValueError("Invalid largest-remainder inputs")
    if target == 0:
        return np.zeros(len(weights), dtype=np.int64)
    if weights.sum() <= 0:
        raise ValueError("Positive target requires positive weights")
    scaled = weights * (target / weights.sum())
    result = np.floor(scaled).astype(np.int64)
    remaining = target - int(result.sum())
    if remaining:
        order = np.argsort(-(scaled - result), kind="stable")
        result[order[:remaining]] += 1
    if int(result.sum()) != target:
        raise AssertionError("Largest remainder did not conserve target")
    return result


def ordered_v5_grids(segments: pd.DataFrame) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for route_id, group in segments.groupby("route_id", sort=False):
        group = group.sort_values("segment_order", key=lambda column: column.astype(int))
        labels = [str(group.iloc[0]["from_waypoint"]), *group["to_waypoint"].astype(str).tolist()]
        grids: list[str] = []
        for label in labels:
            if not label.startswith("origin_grid:"):
                continue
            grid_id = label.split(":", 1)[1]
            if grid_id not in grids:
                grids.append(grid_id)
        result[str(route_id)] = grids
    return result


def reconstruct_locked_stops(
    locked_routes: pd.DataFrame,
    student_od_path: Path,
    grid_path: Path,
    campus_path: Path,
    assumptions_path: Path,
) -> pd.DataFrame:
    """Give each locked identity one nearby, campus-OD-supported proxy pickup."""
    assumptions = yaml.safe_load(assumptions_path.read_text(encoding="utf-8"))
    stage_weights = assumptions["school_selection"]["stage_demand_weight"]
    campus_ids = set(locked_routes["campus_id"].astype(str))
    od = pd.read_parquet(
        student_od_path,
        columns=["campus_id", "origin_grid_id", "student_stage", "students_expected"],
    )
    od["campus_id"] = od["campus_id"].astype(str)
    od["origin_grid_id"] = od["origin_grid_id"].astype(str)
    od = od[od["campus_id"].isin(campus_ids)].copy()
    od["weight"] = pd.to_numeric(od["students_expected"]) * od["student_stage"].map(
        stage_weights
    ).fillna(float(stage_weights["other"]))
    od = od.groupby(["campus_id", "origin_grid_id"], as_index=False)["weight"].sum()

    grids = gpd.read_file(grid_path).to_crs(TARGET_CRS)[["grid_id", "geometry"]]
    grids["origin_grid_id"] = grids["grid_id"].astype(str)
    grids["geometry"] = grids.geometry.representative_point()
    grids["x"] = grids.geometry.x
    grids["y"] = grids.geometry.y
    grid_xy = pd.DataFrame(grids[["origin_grid_id", "x", "y"]])
    od = od.merge(grid_xy, on="origin_grid_id", how="left", validate="many_to_one")
    if od[["x", "y"]].isna().any().any():
        raise ValueError("Locked-route OD references grids without representative points")

    campuses = gpd.read_file(campus_path)[["campus_id", "geometry"]].to_crs(TARGET_CRS)
    campuses["campus_id"] = campuses["campus_id"].astype(str)
    campus_xy = {
        row.campus_id: (float(row.geometry.x), float(row.geometry.y))
        for row in campuses.itertuples()
    }

    stop_rows: list[dict[str, Any]] = []
    for campus_id, route_group in locked_routes.groupby("campus_id", sort=True):
        demand = od[od["campus_id"].eq(str(campus_id))].copy()
        school_x, school_y = campus_xy[str(campus_id)]
        demand["radius_m"] = np.hypot(demand["x"] - school_x, demand["y"] - school_y)
        stage = str(route_group.iloc[0]["dominant_stage"])
        radius_limit_m = 12_000.0 if stage in {"kindergarten", "primary"} else 18_000.0
        eligible = demand[demand["radius_m"] <= radius_limit_m].copy()
        if len(eligible) < len(route_group):
            eligible = demand.copy()
        eligible["selection_score"] = eligible["weight"] / (1.0 + eligible["radius_m"] / 1000.0)
        eligible = eligible.sort_values(
            ["selection_score", "radius_m", "origin_grid_id"],
            ascending=[False, True, True],
            kind="stable",
        ).head(len(route_group))
        if len(eligible) != len(route_group):
            raise ValueError(f"Insufficient OD-supported pickups for campus {campus_id}")
        for route, pickup in zip(route_group.to_dict("records"), eligible.to_dict("records")):
            stop_rows.append(
                {
                    "route_id": str(route["route_id"]),
                    "stop_id": f"{route['route_id']}_FP001",
                    "stop_order": 1,
                    "origin_grid_id": str(pickup["origin_grid_id"]),
                    "proxy_students": int(safe_float(route["proxy_students"])),
                    "dominant_stage": str(route["dominant_stage"]),
                    "x_epsg32650": round(float(pickup["x"]), 3),
                    "y_epsg32650": round(float(pickup["y"]), 3),
                    "stop_quality": "nearby_campus_od_supported_proxy_for_first_party_identity",
                    "evidence_class": "inferred_proxy",
                }
            )
    result = pd.DataFrame(stop_rows)
    if int(pd.to_numeric(result["proxy_students"]).sum()) != int(
        pd.to_numeric(locked_routes["proxy_students"]).sum()
    ):
        raise AssertionError("Locked stop reconstruction changed passenger demand")
    return result


class NetworkMaterializer:
    def __init__(self, path: Path) -> None:
        self.tree = read_xml_gz(path)
        root = self.tree.getroot()
        self.nodes_element = next(child for child in root if local_name(child.tag) == "nodes")
        self.links_element = next(child for child in root if local_name(child.tag) == "links")
        self.node_xy = {
            element.attrib["id"]: (float(element.attrib["x"]), float(element.attrib["y"]))
            for element in self.nodes_element
            if local_name(element.tag) == "node"
        }
        self.links = {
            element.attrib["id"]: element
            for element in self.links_element
            if local_name(element.tag) == "link"
        }
        self.synthetic_by_key: dict[tuple[str, str, str], str] = {}
        self.used_original_links: set[str] = set()
        self.repair_rows: list[dict[str, Any]] = []

    def _allow_school_bus(self, element: ET._Element) -> None:
        modes = [part.strip() for part in element.attrib.get("modes", "").split(",") if part.strip()]
        if SCHOOL_BUS_MODE not in modes:
            modes.append(SCHOOL_BUS_MODE)
            element.attrib["modes"] = ",".join(modes)

    def resolve(self, original_id: str, from_node: str, to_node: str) -> str:
        original = self.links.get(original_id)
        if original is not None and original.attrib["from"] == from_node and original.attrib["to"] == to_node:
            self._allow_school_bus(original)
            self.used_original_links.add(original_id)
            return original_id

        kind = "topology_connector" if original_id.startswith("school_bus_topology_connector_") else "reverse_direction_proxy"
        key = (kind, from_node, to_node)
        if key in self.synthetic_by_key:
            return self.synthetic_by_key[key]
        link_id = f"school_bus_v6_{kind}_{len(self.synthetic_by_key) + 1:05d}"
        if original is not None:
            attributes = dict(original.attrib)
            attributes.update(
                {
                    "id": link_id,
                    "from": from_node,
                    "to": to_node,
                    "modes": SCHOOL_BUS_MODE,
                }
            )
            length = float(attributes.get("length", "0"))
        else:
            x1, y1 = self.node_xy[from_node]
            x2, y2 = self.node_xy[to_node]
            length = max(math.hypot(x2 - x1, y2 - y1), 0.01)
            attributes = {
                "id": link_id,
                "from": from_node,
                "to": to_node,
                "length": f"{length:.3f}",
                "freespeed": f"{AVERAGE_SPEED_M_S:.6f}",
                "capacity": "999.0",
                "permlanes": "1.0",
                "oneway": "1",
                "modes": SCHOOL_BUS_MODE,
            }
        self.links_element.append(ET.Element("link", attributes))
        self.links[link_id] = self.links_element[-1]
        self.synthetic_by_key[key] = link_id
        self.repair_rows.append(
            {
                "link_id": link_id,
                "repair_kind": kind,
                "source_link_id": original_id if original is not None else "",
                "from_node": from_node,
                "to_node": to_node,
                "length_m": round(length, 3),
                "adoption_note": "road-aligned proxy repair; legal direction not independently observed",
            }
        )
        return link_id


class SchoolBusRouter:
    def __init__(self, graph: Any, network: NetworkMaterializer) -> None:
        self.graph = graph
        self.network = network
        self.cache: dict[tuple[int, int, bool], RoutedSegment] = {}

    def route(self, source: int, target: int, shortest_repair: bool = False) -> RoutedSegment:
        key = (source, target, shortest_repair)
        if key in self.cache:
            return self.cache[key]
        directed_path = astar_path(self.graph, source, target, directed=True)
        repaired_path = astar_path(self.graph, source, target, directed=False) if shortest_repair else None
        path = directed_path
        quality = "directed_road"
        if path is None or (
            repaired_path is not None and repaired_path[2] + 0.01 < path[2]
        ):
            path = repaired_path or astar_path(self.graph, source, target, directed=False)
            quality = "road_topology_repaired"
        if path is None:
            raise ValueError(
                f"No road-topology path between {self.graph.node_ids[source]} and "
                f"{self.graph.node_ids[target]}"
            )
        nodes, source_links, length_m = path
        materialized = []
        has_connector = False
        has_reverse = False
        for from_index, to_index, source_link in zip(nodes, nodes[1:], source_links):
            from_node = self.graph.node_ids[from_index]
            to_node = self.graph.node_ids[to_index]
            resolved = self.network.resolve(source_link, from_node, to_node)
            repair = self.network.links[resolved]
            has_connector |= "topology_connector" in resolved
            has_reverse |= "reverse_direction_proxy" in resolved
            materialized.append(resolved)
        if has_connector:
            quality += "_with_connector"
        if has_reverse:
            quality += "_with_reverse_proxy"
        result = RoutedSegment(
            source=source,
            target=target,
            node_indices=tuple(nodes),
            link_ids=tuple(materialized),
            length_m=float(length_m),
            quality=quality,
        )
        self.cache[key] = result
        return result


def nearest_nodes(graph: Any, coordinates: pd.DataFrame) -> tuple[dict[str, int], list[dict[str, Any]]]:
    routable = graph.routable_node_indices
    tree = cKDTree(graph.coordinates[routable])
    keys = coordinates["key"].astype(str).tolist()
    source = coordinates[["x", "y"]].astype(float).to_numpy()
    distances, local_indices = tree.query(source, k=1)
    indices = routable[np.asarray(local_indices, dtype=int)]
    mapping: dict[str, int] = {}
    rows: list[dict[str, Any]] = []
    for key, xy, distance, node_index in zip(keys, source, distances, indices):
        node_index = int(node_index)
        mapping[key] = node_index
        matched = graph.coordinates[node_index]
        kind, identifier = key.split(":", 1)
        rows.append(
            {
                "waypoint_kind": kind,
                "waypoint_id": identifier,
                "source_x_epsg32650": round(float(xy[0]), 3),
                "source_y_epsg32650": round(float(xy[1]), 3),
                "matched_node_id": graph.node_ids[node_index],
                "matched_x_epsg32650": round(float(matched[0]), 3),
                "matched_y_epsg32650": round(float(matched[1]), 3),
                "snap_distance_m": round(float(distance), 3),
            }
        )
    return mapping, rows


def collapse_pickups(
    route: dict[str, Any],
    ordered_grid_ids: list[str],
    stops: pd.DataFrame,
    node_map: dict[str, int],
    graph: Any,
    campus_node: int,
) -> list[dict[str, Any]]:
    frame = stops[stops["route_id"].astype(str).eq(str(route["route_id"]))].copy()
    grouped = {
        str(grid_id): group
        for grid_id, group in frame.groupby("origin_grid_id", sort=False)
    }
    ordered = [grid_id for grid_id in ordered_grid_ids if grid_id in grouped]
    ordered.extend(grid_id for grid_id in grouped if grid_id not in ordered)
    pickups: list[dict[str, Any]] = []
    by_node: dict[int, dict[str, Any]] = {}
    for grid_id in ordered:
        group = grouped[grid_id]
        node = node_map[f"origin_grid:{grid_id}"]
        if node not in by_node:
            item = {
                "node": node,
                "grid_ids": [],
                "proxy_students": 0,
            }
            by_node[node] = item
            pickups.append(item)
        item = by_node[node]
        item["grid_ids"].append(grid_id)
        item["proxy_students"] += int(pd.to_numeric(group["proxy_students"]).sum())
    if not pickups:
        raise ValueError(f"Route {route['route_id']} has no reconstructed pickup")
    occupied = {int(item["node"]) for item in pickups if int(item["node"]) != campus_node}
    for pickup in pickups:
        if int(pickup["node"]) != campus_node:
            continue
        source_rows = frame[
            frame["origin_grid_id"].astype(str).isin(pickup["grid_ids"])
        ]
        source_x = float(pd.to_numeric(source_rows["x_epsg32650"]).mean())
        source_y = float(pd.to_numeric(source_rows["y_epsg32650"]).mean())
        candidates = graph.routable_node_indices
        distances = np.hypot(
            graph.coordinates[candidates, 0] - source_x,
            graph.coordinates[candidates, 1] - source_y,
        )
        for local in np.argsort(distances):
            candidate = int(candidates[int(local)])
            if candidate != campus_node and candidate not in occupied:
                pickup["node"] = candidate
                occupied.add(candidate)
                break
        if int(pickup["node"]) == campus_node:
            raise ValueError(f"Could not separate pickup and campus nodes for {route['route_id']}")
    return pickups


def route_chain(
    nodes: list[int],
    router: SchoolBusRouter,
    shortest_repair: bool = False,
) -> tuple[list[RoutedSegment], list[str], list[float], dict[str, int]]:
    segments: list[RoutedSegment] = []
    links: list[str] = []
    lengths: list[float] = []
    quality_counts: Counter[str] = Counter()
    for source, target in zip(nodes, nodes[1:]):
        segment = router.route(source, target, shortest_repair=shortest_repair)
        if not segment.link_ids:
            raise ValueError("Collapsed school-bus waypoints produced an empty road segment")
        segments.append(segment)
        links.extend(segment.link_ids)
        lengths.append(segment.length_m)
        quality_counts[segment.quality] += 1
    return segments, links, lengths, dict(quality_counts)


def stop_link_ids(segments: list[RoutedSegment]) -> list[str]:
    result = [segments[0].link_ids[0]]
    for segment in segments[1:]:
        result.append(segment.link_ids[0])
    result.append(segments[-1].link_ids[-1])
    return result


def direction_quality(segments: list[RoutedSegment]) -> tuple[str, int, int, int, int]:
    directed = sum(segment.quality.startswith("directed_road") for segment in segments)
    repaired = len(segments) - directed
    connectors = sum("connector" in link_id for segment in segments for link_id in segment.link_ids)
    reverses = sum("reverse_direction_proxy" in link_id for segment in segments for link_id in segment.link_ids)
    if reverses:
        quality = "continuous_with_reverse_direction_proxy"
    elif connectors:
        quality = "continuous_with_topology_connector"
    else:
        quality = "continuous_directed_road"
    return quality, directed, repaired, connectors, reverses


def add_stop_facility(
    transit_stops: ET._Element,
    facility_id: str,
    node_index: int,
    link_id: str,
    graph: Any,
    name: str,
) -> None:
    x, y = graph.coordinates[node_index]
    ET.SubElement(
        transit_stops,
        "stopFacility",
        {
            "id": facility_id,
            "x": f"{float(x):.3f}",
            "y": f"{float(y):.3f}",
            "linkRefId": link_id,
            "name": name,
            "isBlocking": "false",
        },
    )


def append_transit_route(
    line: ET._Element,
    route_id: str,
    stop_ids: list[str],
    stop_links: list[str],
    route_links: list[str],
    segment_lengths_m: list[float],
    departure_time_seconds: float,
    vehicle_id: str,
) -> float:
    route = ET.SubElement(line, "transitRoute", {"id": route_id})
    ET.SubElement(route, "transportMode").text = SCHOOL_BUS_MODE
    profile = ET.SubElement(route, "routeProfile")
    arrivals = [0.0]
    departures = [0.0]
    elapsed = 0.0
    for index, length_m in enumerate(segment_lengths_m, start=1):
        elapsed += length_m / AVERAGE_SPEED_M_S
        arrivals.append(elapsed)
        if index < len(segment_lengths_m):
            elapsed += DWELL_SECONDS
        departures.append(elapsed)
    for index, stop_id in enumerate(stop_ids):
        ET.SubElement(
            profile,
            "stop",
            {
                "refId": stop_id,
                "arrivalOffset": format_clock(arrivals[index]),
                "departureOffset": format_clock(departures[index]),
                "awaitDeparture": "true",
            },
        )
    network_route = ET.SubElement(route, "route")
    for link_id in route_links:
        ET.SubElement(network_route, "link", {"refId": link_id})
    departures_element = ET.SubElement(route, "departures")
    ET.SubElement(
        departures_element,
        "departure",
        {
            "id": f"dep_{route_id}",
            "departureTime": format_clock(departure_time_seconds),
            "vehicleRefId": vehicle_id,
        },
    )
    if len(stop_links) != len(stop_ids):
        raise AssertionError("Stop link mapping length mismatch")
    return arrivals[-1]


def vehicle_namespace(root: ET._Element) -> str:
    if root.tag.startswith("{"):
        return root.tag.split("}", 1)[0][1:]
    return ""


def qname(namespace: str, tag: str) -> str:
    return f"{{{namespace}}}{tag}" if namespace else tag


def append_vehicle_types_and_vehicles(
    vehicle_tree: ET._ElementTree,
    route_rows: list[dict[str, Any]],
) -> dict[int, str]:
    root = vehicle_tree.getroot()
    namespace = vehicle_namespace(root)
    capacities = sorted({int(safe_float(row["vehicle_capacity"])) for row in route_rows})
    type_specs = {}
    for capacity in capacities:
        if capacity <= 19:
            type_specs[capacity] = (7.0, 2.2, 0.05)
        elif capacity <= 28:
            type_specs[capacity] = (9.0, 2.4, 0.075)
        elif capacity <= 50:
            type_specs[capacity] = (12.0, 2.55, 0.125)
        else:
            raise ValueError(f"Unsupported school-bus capacity {capacity}")
    type_ids: dict[int, str] = {}
    existing_types = {
        element.attrib["id"]
        for element in root
        if local_name(element.tag) == "vehicleType"
    }
    for capacity, (length, width, pce) in type_specs.items():
        type_id = f"school_bus_v6_{capacity}_seat_unscaled"
        type_ids[capacity] = type_id
        if type_id in existing_types:
            raise ValueError(f"Vehicle type already exists: {type_id}")
        vehicle_type = ET.Element(qname(namespace, "vehicleType"), {"id": type_id})
        ET.SubElement(
            vehicle_type,
            qname(namespace, "capacity"),
            {"seats": str(capacity), "standingRoomInPersons": "0"},
        )
        ET.SubElement(vehicle_type, qname(namespace, "length"), {"meter": f"{length:.3f}"})
        ET.SubElement(vehicle_type, qname(namespace, "width"), {"meter": f"{width:.3f}"})
        ET.SubElement(vehicle_type, qname(namespace, "passengerCarEquivalents"), {"pce": f"{pce:.6f}"})
        ET.SubElement(vehicle_type, qname(namespace, "networkMode"), {"networkMode": SCHOOL_BUS_MODE})
        first_vehicle_index = next(
            (
                index
                for index, element in enumerate(root)
                if local_name(element.tag) == "vehicle"
            ),
            len(root),
        )
        root.insert(first_vehicle_index, vehicle_type)
    for route in route_rows:
        capacity = int(safe_float(route["vehicle_capacity"]))
        if capacity not in type_ids:
            raise ValueError(f"Unsupported school-bus capacity {capacity}")
        ET.SubElement(
            root,
            qname(namespace, "vehicle"),
            {
                "id": f"veh_school_bus_v6_{route['route_id']}",
                "type": type_ids[capacity],
            },
        )
    return type_ids


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--active-supply", type=Path, default=ACTIVE_SUPPLY)
    parser.add_argument("--v5-dir", type=Path, default=V5_DIR)
    parser.add_argument("--v3-dir", type=Path, default=V3_DIR)
    parser.add_argument("--student-od", type=Path, default=STUDENT_OD)
    parser.add_argument("--campuses", type=Path, default=CAMPUSES)
    parser.add_argument("--grids", type=Path, default=GRIDS)
    parser.add_argument("--assumptions", type=Path, default=ASSUMPTIONS)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    required = [
        args.active_supply / "network.xml.gz",
        args.active_supply / "transitSchedule_5pct.xml.gz",
        args.active_supply / "transitVehicles_10pct.xml.gz",
        args.v5_dir / "school_bus_fleet_capped_routes.csv",
        args.v5_dir / "school_bus_fleet_capped_stops.csv",
        args.v5_dir / "school_bus_fleet_capped_segments.csv",
        args.v3_dir / "school_bus_locked_first_party_routes.csv",
        args.student_od,
        args.campuses,
        args.grids,
        args.assumptions,
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing v6 inputs:\n" + "\n".join(missing))
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    routes = pd.read_csv(args.v5_dir / "school_bus_fleet_capped_routes.csv", dtype=str).fillna("")
    v5_stops = pd.read_csv(args.v5_dir / "school_bus_fleet_capped_stops.csv", dtype=str).fillna("")
    v5_segments = pd.read_csv(args.v5_dir / "school_bus_fleet_capped_segments.csv", dtype=str).fillna("")
    locked_routes = routes[routes["route_kind"].eq("first_party_locked")].copy()
    inferred_routes = routes[routes["route_kind"].eq("inferred_proxy")].copy()
    if len(routes) != 3439 or len(locked_routes) != 76 or len(inferred_routes) != 3363:
        raise ValueError("Unexpected v5 route inventory")
    locked_stops = reconstruct_locked_stops(
        locked_routes,
        args.student_od,
        args.grids,
        args.campuses,
        args.assumptions,
    )
    all_stops = pd.concat([v5_stops, locked_stops], ignore_index=True).fillna("")

    campuses = gpd.read_file(args.campuses)[["campus_id", "geometry"]].to_crs(TARGET_CRS)
    campuses["campus_id"] = campuses["campus_id"].astype(str)
    campus_xy = {
        row.campus_id: (float(row.geometry.x), float(row.geometry.y))
        for row in campuses.itertuples()
    }
    needed_campuses = set(routes["campus_id"].astype(str))
    if needed_campuses.difference(campus_xy):
        raise ValueError("V5 routes reference missing campus coordinates")

    waypoint_rows = (
        all_stops[["origin_grid_id", "x_epsg32650", "y_epsg32650"]]
        .drop_duplicates("origin_grid_id")
        .rename(
            columns={
                "origin_grid_id": "identifier",
                "x_epsg32650": "x",
                "y_epsg32650": "y",
            }
        )
    )
    waypoint_rows["key"] = "origin_grid:" + waypoint_rows["identifier"].astype(str)
    campus_rows = pd.DataFrame(
        [
            {"key": f"campus:{campus_id}", "x": xy[0], "y": xy[1]}
            for campus_id, xy in campus_xy.items()
            if campus_id in needed_campuses
        ]
    )
    waypoints = pd.concat([waypoint_rows[["key", "x", "y"]], campus_rows], ignore_index=True)

    graph = parse_network(args.active_supply / "network.xml.gz")
    node_map, snap_rows = nearest_nodes(graph, waypoints)
    network = NetworkMaterializer(args.active_supply / "network.xml.gz")
    router = SchoolBusRouter(graph, network)
    schedule_tree = read_xml_gz(args.active_supply / "transitSchedule_5pct.xml.gz")
    schedule_root = schedule_tree.getroot()
    transit_stops = next(child for child in schedule_root if local_name(child.tag) == "transitStops")
    vehicle_tree = read_xml_gz(args.active_supply / "transitVehicles_10pct.xml.gz")
    append_vehicle_types_and_vehicles(vehicle_tree, routes.to_dict("records"))

    v5_order = ordered_v5_grids(v5_segments)
    locked_order: dict[str, list[str]] = {}
    for route in locked_routes.to_dict("records"):
        frame = locked_stops[locked_stops["route_id"].eq(route["route_id"])]
        pickup_nodes = [node_map[f"origin_grid:{grid_id}"] for grid_id in frame["origin_grid_id"].astype(str)]
        labels = frame["origin_grid_id"].astype(str).tolist()
        school_node = node_map[f"campus:{route['campus_id']}"]
        _, ordered_labels, _ = optimise_pickup_order(graph, pickup_nodes, labels, school_node)
        locked_order[str(route["route_id"])] = [
            label for label in ordered_labels[:-1] if label in set(labels)
        ]

    route_audit: list[dict[str, Any]] = []
    stop_audit: list[dict[str, Any]] = []
    first_party_audit: list[dict[str, Any]] = []
    quality_counts: Counter[str] = Counter()
    total_proxy_students = 0
    for route_number, route in enumerate(routes.to_dict("records"), start=1):
        route_id = str(route["route_id"])
        campus_id = str(route["campus_id"])
        school_node = node_map[f"campus:{campus_id}"]
        order = locked_order.get(route_id, v5_order.get(route_id, []))
        pickups = collapse_pickups(route, order, all_stops, node_map, graph, school_node)
        pickup_nodes = [int(item["node"]) for item in pickups]
        inbound_nodes = pickup_nodes + [school_node]
        outbound_nodes = list(reversed(inbound_nodes))
        inbound_segments, inbound_links, inbound_lengths, _ = route_chain(inbound_nodes, router)
        outbound_segments, outbound_links, outbound_lengths, _ = route_chain(outbound_nodes, router)
        time_limit_minutes = TIME_LIMIT_BY_STAGE.get(str(route["dominant_stage"]), 75.0)
        dwell_total = DWELL_SECONDS * max(0, len(pickups) - 1)
        if sum(inbound_lengths) / AVERAGE_SPEED_M_S + dwell_total > time_limit_minutes * 60.0:
            inbound_segments, inbound_links, inbound_lengths, _ = route_chain(
                inbound_nodes,
                router,
                shortest_repair=True,
            )
        if sum(outbound_lengths) / AVERAGE_SPEED_M_S + dwell_total > time_limit_minutes * 60.0:
            outbound_segments, outbound_links, outbound_lengths, _ = route_chain(
                outbound_nodes,
                router,
                shortest_repair=True,
            )
        inbound_stop_links = stop_link_ids(inbound_segments)
        outbound_stop_links = stop_link_ids(outbound_segments)
        inbound_quality = direction_quality(inbound_segments)
        outbound_quality = direction_quality(outbound_segments)

        vehicle_id = f"veh_school_bus_v6_{route_id}"
        line = ET.Element(
            "transitLine",
            {
                "id": f"line_school_bus_v6_{route_id}",
                "name": f"School bus {route_id}",
            },
        )
        inbound_stop_ids: list[str] = []
        for index, pickup in enumerate(pickups, start=1):
            facility_id = f"sbv6_{route_id}_AM_P{index:03d}"
            inbound_stop_ids.append(facility_id)
            add_stop_facility(
                transit_stops,
                facility_id,
                int(pickup["node"]),
                inbound_stop_links[index - 1],
                graph,
                f"School bus pickup {';'.join(pickup['grid_ids'])}",
            )
            stop_audit.append(
                {
                    "route_id": route_id,
                    "direction": "inbound_am",
                    "stop_order": index,
                    "facility_id": facility_id,
                    "origin_grid_ids": ";".join(pickup["grid_ids"]),
                    "campus_id": campus_id,
                    "proxy_students": pickup["proxy_students"],
                    "node_id": graph.node_ids[int(pickup["node"])],
                    "link_ref_id": inbound_stop_links[index - 1],
                    "stop_provenance": "first_party_identity_od_reconstruction"
                    if route["route_kind"] == "first_party_locked"
                    else "v5_inferred_pickup",
                }
            )
        inbound_school = f"sbv6_{route_id}_AM_SCHOOL"
        inbound_stop_ids.append(inbound_school)
        add_stop_facility(
            transit_stops,
            inbound_school,
            school_node,
            inbound_stop_links[-1],
            graph,
            f"School campus {campus_id}",
        )

        inbound_duration = sum(inbound_lengths) / AVERAGE_SPEED_M_S + DWELL_SECONDS * max(0, len(pickups) - 1)
        inbound_departure = parse_clock(str(route["school_arrival_time"])) - inbound_duration
        actual_inbound_duration = append_transit_route(
            line,
            f"school_bus_v6_{route_id}_AM",
            inbound_stop_ids,
            inbound_stop_links,
            inbound_links,
            inbound_lengths,
            inbound_departure,
            vehicle_id,
        )

        outbound_stop_ids: list[str] = []
        outbound_school = f"sbv6_{route_id}_PM_SCHOOL"
        outbound_stop_ids.append(outbound_school)
        add_stop_facility(
            transit_stops,
            outbound_school,
            school_node,
            outbound_stop_links[0],
            graph,
            f"School campus {campus_id}",
        )
        for index, pickup in enumerate(reversed(pickups), start=1):
            facility_id = f"sbv6_{route_id}_PM_P{index:03d}"
            outbound_stop_ids.append(facility_id)
            add_stop_facility(
                transit_stops,
                facility_id,
                int(pickup["node"]),
                outbound_stop_links[index],
                graph,
                f"School bus drop-off {';'.join(pickup['grid_ids'])}",
            )
            stop_audit.append(
                {
                    "route_id": route_id,
                    "direction": "outbound_pm",
                    "stop_order": index,
                    "facility_id": facility_id,
                    "origin_grid_ids": ";".join(pickup["grid_ids"]),
                    "campus_id": campus_id,
                    "proxy_students": pickup["proxy_students"],
                    "node_id": graph.node_ids[int(pickup["node"])],
                    "link_ref_id": outbound_stop_links[index],
                    "stop_provenance": "first_party_identity_od_reconstruction"
                    if route["route_kind"] == "first_party_locked"
                    else "v5_inferred_pickup",
                }
            )
        actual_outbound_duration = append_transit_route(
            line,
            f"school_bus_v6_{route_id}_PM",
            outbound_stop_ids,
            outbound_stop_links,
            outbound_links,
            outbound_lengths,
            parse_clock(str(route["return_departure_time"])),
            vehicle_id,
        )
        schedule_root.append(line)

        for direction, links, duration, quality in (
            ("inbound_am", inbound_links, actual_inbound_duration, inbound_quality),
            ("outbound_pm", outbound_links, actual_outbound_duration, outbound_quality),
        ):
            quality_counts[quality[0]] += 1
            route_audit.append(
                {
                    "route_id": route_id,
                    "direction": direction,
                    "campus_id": campus_id,
                    "route_kind": route["route_kind"],
                    "dominant_stage": route["dominant_stage"],
                    "school_arrival_time": route["school_arrival_time"],
                    "return_departure_time": route["return_departure_time"],
                    "source_id": route.get("source_id", ""),
                    "source_route_code": route.get("source_route_code", ""),
                    "proxy_students": int(safe_float(route["proxy_students"])),
                    "vehicle_capacity": int(safe_float(route["vehicle_capacity"])),
                    "capacity_scaled": False,
                    "pickup_stop_count": len(pickups),
                    "network_link_count": len(links),
                    "road_path_km": round(sum(
                        float(network.links[link_id].attrib.get("length", "0")) for link_id in links
                    ) / 1000.0, 3),
                    "scheduled_runtime_minutes": round(duration / 60.0, 2),
                    "time_limit_minutes": time_limit_minutes,
                    "time_limit_exceeded": duration > time_limit_minutes * 60.0 + 0.5,
                    "path_quality": quality[0],
                    "directed_segment_count": quality[1],
                    "repaired_segment_count": quality[2],
                    "topology_connector_occurrence_count": quality[3],
                    "reverse_direction_proxy_occurrence_count": quality[4],
                    "geometry_provenance": "first_party_route_identity_with_od_reconstructed_road_geometry"
                    if route["route_kind"] == "first_party_locked"
                    else "v5_proxy_membership_rerouted_on_v6_network",
                }
            )
        if route["route_kind"] == "first_party_locked":
            first_party_audit.append(
                {
                    "route_id": route_id,
                    "source_id": route.get("source_id", ""),
                    "source_route_code": route.get("source_route_code", ""),
                    "campus_id": campus_id,
                    "proxy_students": int(safe_float(route["proxy_students"])),
                    "vehicle_capacity": int(safe_float(route["vehicle_capacity"])),
                    "reconstructed_pickup_count": len(pickups),
                    "identity_evidence_class": route.get("evidence_class", ""),
                    "geometry_evidence_class": "inferred_proxy_from_campus_specific_student_od",
                    "published_stop_geometry_claimed": False,
                }
            )
        total_proxy_students += int(safe_float(route["proxy_students"]))
        if route_number % 250 == 0:
            print(f"built {route_number:,}/{len(routes):,} school-bus lines", flush=True)

    network_output = output / NETWORK_FILE
    schedule_output = output / SCHEDULE_FILE
    vehicles_output = output / VEHICLES_FILE
    write_xml_gz(
        network.tree,
        network_output,
        '<!DOCTYPE network SYSTEM "http://www.matsim.org/files/dtd/network_v2.dtd">',
    )
    write_xml_gz(
        schedule_tree,
        schedule_output,
        '<!DOCTYPE transitSchedule SYSTEM "http://www.matsim.org/files/dtd/transitSchedule_v2.dtd">',
    )
    write_xml_gz(
        vehicle_tree,
        vehicles_output,
        None,
    )

    route_fields = list(route_audit[0])
    stop_fields = list(stop_audit[0])
    repair_fields = list(network.repair_rows[0]) if network.repair_rows else [
        "link_id", "repair_kind", "source_link_id", "from_node", "to_node", "length_m", "adoption_note"
    ]
    write_csv(output / "school_bus_routes_v6.csv", route_audit, route_fields)
    write_csv(output / "school_bus_stops_v6.csv", stop_audit, stop_fields)
    write_csv(output / "school_bus_network_repairs_v6.csv", network.repair_rows, repair_fields)
    write_csv(output / "school_bus_waypoint_snaps_v6.csv", snap_rows, list(snap_rows[0]))
    write_csv(output / "school_bus_first_party_reconstruction_v6.csv", first_party_audit, list(first_party_audit[0]))

    summary = {
        "status": "adoption_ready_candidate_not_current_production",
        "base_supply": str(args.active_supply.resolve()),
        "route_inventory": {
            "total_lines": len(routes),
            "inferred_v5_lines": len(inferred_routes),
            "first_party_identity_lines": len(locked_routes),
            "physical_transit_routes": len(route_audit),
            "departures": len(route_audit),
            "vehicles": len(routes),
        },
        "demand_and_capacity": {
            "retained_v5_proxy_students": total_proxy_students,
            "first_party_proxy_students": int(pd.to_numeric(locked_routes["proxy_students"]).sum()),
            "passenger_capacity_scaled": False,
            "vehicle_capacity_classes": sorted(
                {int(safe_float(value)) for value in routes["vehicle_capacity"]}
            ),
            "all_route_loads_within_unscaled_capacity": all(
                int(safe_float(row["proxy_students"])) <= int(safe_float(row["vehicle_capacity"]))
                for row in routes.to_dict("records")
            ),
        },
        "road_routing": {
            "direction_quality_counts": dict(quality_counts),
            "original_links_enabled_for_school_bus": len(network.used_original_links),
            "synthetic_network_repair_links": len(network.repair_rows),
            "repair_kind_counts": dict(Counter(row["repair_kind"] for row in network.repair_rows)),
        },
        "first_party_geometry": {
            "identity_count": len(first_party_audit),
            "all_have_reconstructed_pickups": all(row["reconstructed_pickup_count"] > 0 for row in first_party_audit),
            "method": "one nearby campus-specific student-OD-supported proxy pickup per first-party identity, road-network routing",
            "provenance_limit": "route identity is first-party evidence; pickup membership, stop geometry, order and road path are inferred proxies",
        },
        "outputs": {
            "network": NETWORK_FILE,
            "schedule": SCHEDULE_FILE,
            "vehicles": VEHICLES_FILE,
        },
        "qa": {
            "all_3439_lines_built": len(routes) == 3439,
            "all_76_first_party_lines_physical": len(first_party_audit) == 76
            and all(row["reconstructed_pickup_count"] > 0 for row in first_party_audit),
            "both_directions_present": len(route_audit) == 2 * len(routes),
            "all_students_fit_unscaled_capacity": all(
                int(safe_float(row["proxy_students"])) <= int(safe_float(row["vehicle_capacity"]))
                for row in routes.to_dict("records")
            ),
            "no_empty_network_routes": all(int(row["network_link_count"]) > 0 for row in route_audit),
            "all_directions_within_stage_time_limit": not any(
                bool(row["time_limit_exceeded"]) for row in route_audit
            ),
        },
    }
    (output / "school_bus_supply_v6_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
