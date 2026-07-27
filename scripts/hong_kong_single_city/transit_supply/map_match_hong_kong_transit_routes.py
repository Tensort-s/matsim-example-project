#!/usr/bin/env python3
"""Map-match Hong Kong public transport routes to road and rail links.

Road links come from the Transport Department TNM centreline layer. Heavy
rail and light-rail links are extracted from the local OSM PBF. CSDI route
geometries are preferred for buses and green minibuses; spatially validated
AMap geometries supplement routes without CSDI geometry and provide MTR/LRT
trajectories. Remaining road routes are inferred from ordered official stops.

The script writes a MATSim network and route-link tables, but intentionally
does not write a transitSchedule: timetable assembly is a separate step.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import heapq
import json
import math
import os
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence
from xml.sax.saxutils import escape

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import osmium
import pandas as pd
from pyproj import Transformer
from scipy.spatial import cKDTree
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge
from shapely.strtree import STRtree


REPO_ROOT = Path(__file__).resolve().parents[3]
FORMAL_PROJECT_ROOT = Path(os.environ.get("MATSIM_PROJECT_ROOT", r"F:\Matsim\matsim-example-project"))
PROJECT_ROOT = FORMAL_PROJECT_ROOT if FORMAL_PROJECT_ROOT.exists() else REPO_ROOT
TRANSIT_ROOT = PROJECT_ROOT / "data" / "transit" / "hongkong"

DEFAULT_ROAD = (
    TRANSIT_ROOT
    / "Road_Network_SHP"
    / "Transportation_TNM_20260717_gdb_CENTERLINE_converted.shp"
)
DEFAULT_PBF = (
    PROJECT_ROOT
    / "data"
    / "osm"
    / "hongkong"
    / "fixed_link_boundary"
    / "hong-kong-latest.osm.pbf"
)
DEFAULT_API = TRANSIT_ROOT / "API_Supplements"
DEFAULT_AMAP = TRANSIT_ROOT / "AMap_Targeted_StopID_Supplements"
DEFAULT_OUTPUT = TRANSIT_ROOT / "processed" / "transit_route_link_mapmatching_2026_v2"
DEFAULT_BASELINE = TRANSIT_ROOT / "processed" / "transit_route_link_mapmatching_2026"

TARGET_CRS = "EPSG:32650"
ROAD_MODES = {"bus", "gmb"}
RAIL_MODES = {"mtr", "lrt"}
ACTIVE_RAILWAY_VALUES = {"rail", "subway", "light_rail", "tram"}
EXCLUDED_RAIL_SERVICES = {"yard", "siding", "spur"}
ROAD_PRIMARY_SEARCH_RADIUS_M = 120.0
ROAD_FALLBACK_SEARCH_RADIUS_M = 250.0
ROAD_LOCAL_CORRIDOR_M = 300.0
ROAD_EXPANDED_CORRIDOR_M = 800.0
MAX_TOPOLOGY_CONNECTOR_M = 300.0
STOP_COVERAGE_WARNING_M = 250.0
EXTERNAL_STOP_THRESHOLD_M = 1000.0


def safe_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def normalize_name(value: Any) -> str:
    text = safe_text(value).lower()
    for old, new in (("（", "("), ("）", ")"), (" ", ""), ("-", ""), ("_", "")):
        text = text.replace(old, new)
    return text


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    return float(np.percentile(np.asarray(values, dtype=float), q))


def line_parts(geometry: Any) -> list[LineString]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, LineString):
        return [geometry]
    if isinstance(geometry, MultiLineString):
        return [part for part in geometry.geoms if not part.is_empty and len(part.coords) >= 2]
    if geometry.geom_type == "GeometryCollection":
        parts: list[LineString] = []
        for item in geometry.geoms:
            parts.extend(line_parts(item))
        return parts
    return []


def ordered_linestring(geometry: Any, start_hint: Point | None = None) -> LineString | None:
    parts = line_parts(geometry)
    if not parts:
        return None
    merged = linemerge(MultiLineString(parts)) if len(parts) > 1 else parts[0]
    if isinstance(merged, LineString):
        result = merged
    else:
        remaining = list(line_parts(merged))
        if start_hint is None:
            current_index = max(range(len(remaining)), key=lambda idx: remaining[idx].length)
            current = remaining.pop(current_index)
        else:
            choices: list[tuple[float, int, bool]] = []
            for idx, part in enumerate(remaining):
                choices.append((start_hint.distance(Point(part.coords[0])), idx, False))
                choices.append((start_hint.distance(Point(part.coords[-1])), idx, True))
            _, current_index, reverse = min(choices)
            current = remaining.pop(current_index)
            if reverse:
                current = LineString(list(current.coords)[::-1])
        coords = list(current.coords)
        while remaining:
            endpoint = Point(coords[-1])
            choices = []
            for idx, part in enumerate(remaining):
                choices.append((endpoint.distance(Point(part.coords[0])), idx, False))
                choices.append((endpoint.distance(Point(part.coords[-1])), idx, True))
            _, idx, reverse = min(choices)
            part = remaining.pop(idx)
            part_coords = list(part.coords)
            if reverse:
                part_coords.reverse()
            coords.extend(part_coords)
        result = LineString(coords)
    if start_hint is not None:
        if start_hint.distance(Point(result.coords[-1])) < start_hint.distance(Point(result.coords[0])):
            result = LineString(list(result.coords)[::-1])
    return result


def sample_line(line: LineString, spacing_m: float) -> list[tuple[Point, float]]:
    if line.length <= 0:
        return []
    distances = list(np.arange(0.0, line.length, max(spacing_m, 1.0)))
    if not distances or distances[-1] < line.length:
        distances.append(line.length)
    result: list[tuple[Point, float]] = []
    for distance in distances:
        point = line.interpolate(distance)
        before = line.interpolate(max(0.0, distance - 15.0))
        after = line.interpolate(min(line.length, distance + 15.0))
        heading = math.atan2(after.y - before.y, after.x - before.x)
        result.append((point, heading))
    return result


def heading_difference(a: float, b: float) -> float:
    value = abs((a - b + math.pi) % (2 * math.pi) - math.pi)
    return value


@dataclass
class Link:
    link_id: str
    from_node: str
    to_node: str
    length_m: float
    geometry: LineString
    network_type: str
    source_id: str
    subtype: str
    legal_direction: bool
    allowed_modes: str
    freespeed_mps: float


@dataclass
class RoadCandidate:
    link_id: str
    distance_m: float
    heading_difference_rad: float
    emission_cost: float


@dataclass
class MatchState:
    cost: float
    candidate: RoadCandidate
    route_links: list[str]
    relaxed_occurrences: int
    connector_occurrences: int


class LinkNetwork:
    def __init__(self, network_type: str):
        self.network_type = network_type
        self.nodes: dict[str, tuple[float, float]] = {}
        self.links: dict[str, Link] = {}
        self.physical_geometries: list[LineString] = []
        self.physical_link_ids: list[list[str]] = []
        self.physical_subtypes: list[str] = []
        self.physical_source_ids: list[str] = []
        self.route_way_ids: dict[str, set[str]] = {}
        self.route_relations: dict[str, list[dict[str, Any]]] = {}
        self.way_segment_links: dict[str, list[str]] = {}
        self.topology_connectors: dict[tuple[str, str, str], str] = {}
        self.tree: STRtree | None = None
        self.adj_legal: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
        self.adj_relaxed: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
        self._path_cache: dict[tuple[str, str, bool], list[str] | None] = {}

    def add_physical(
        self,
        geometry: LineString,
        source_id: str,
        subtype: str,
        directions: Sequence[tuple[str, str, str, bool]],
        allowed_modes: str,
        freespeed_mps: float,
    ) -> None:
        link_ids: list[str] = []
        for link_id, from_node, to_node, legal in directions:
            oriented = geometry
            start = self.nodes[from_node]
            if Point(geometry.coords[-1]).distance(Point(start)) < Point(geometry.coords[0]).distance(Point(start)):
                oriented = LineString(list(geometry.coords)[::-1])
            link = Link(
                link_id=link_id,
                from_node=from_node,
                to_node=to_node,
                length_m=max(float(oriented.length), 0.1),
                geometry=oriented,
                network_type=self.network_type,
                source_id=source_id,
                subtype=subtype,
                legal_direction=legal,
                allowed_modes=allowed_modes if legal else "bus,gmb,pt",
                freespeed_mps=freespeed_mps,
            )
            self.links[link_id] = link
            link_ids.append(link_id)
            penalty = 1.0 if legal else 1.35
            self.adj_relaxed[from_node].append((to_node, link_id, link.length_m * penalty))
            if legal:
                self.adj_legal[from_node].append((to_node, link_id, link.length_m))
        self.physical_geometries.append(geometry)
        self.physical_link_ids.append(link_ids)
        self.physical_subtypes.append(subtype)
        self.physical_source_ids.append(source_id)

    def finalize(self) -> None:
        self.tree = STRtree(self.physical_geometries)

    def create_topology_connector(self, from_node: str, to_node: str, subtype: str) -> str:
        key = (from_node, to_node, subtype)
        if key in self.topology_connectors:
            return self.topology_connectors[key]
        geometry = LineString([self.nodes[from_node], self.nodes[to_node]])
        link_id = f"{self.network_type}_{subtype}_{len(self.topology_connectors) + 1:06d}"
        if self.network_type == "rail":
            modes, speed = "train,light_rail,pt", 13.89
        else:
            modes, speed = "bus,gmb,pt", 8.33
        link = Link(
            link_id=link_id,
            from_node=from_node,
            to_node=to_node,
            length_m=max(float(geometry.length), 0.1),
            geometry=geometry,
            network_type=self.network_type,
            source_id="inferred_topology_connector",
            subtype=subtype,
            legal_direction=True,
            allowed_modes=modes,
            freespeed_mps=speed,
        )
        self.links[link_id] = link
        self.adj_legal[from_node].append((to_node, link_id, link.length_m))
        self.adj_relaxed[from_node].append((to_node, link_id, link.length_m))
        self.topology_connectors[key] = link_id
        return link_id

    def candidate_physical_indices(
        self,
        point: Point,
        radius_m: float,
        allowed_subtypes: set[str] | None = None,
        allowed_source_ids: set[str] | None = None,
    ) -> list[int]:
        if self.tree is None:
            raise RuntimeError("Network spatial index has not been finalized")
        indices = [int(idx) for idx in self.tree.query(point.buffer(radius_m))]
        if not indices:
            nearest = self.tree.nearest(point)
            if nearest is not None:
                indices = [int(nearest)]
        if allowed_subtypes:
            indices = [idx for idx in indices if self.physical_subtypes[idx] in allowed_subtypes]
            if not indices:
                all_indices = [int(idx) for idx in self.tree.query(point.buffer(radius_m * 4.0))]
                indices = [idx for idx in all_indices if self.physical_subtypes[idx] in allowed_subtypes]
        if allowed_source_ids:
            indices = [idx for idx in indices if self.physical_source_ids[idx] in allowed_source_ids]
            if not indices:
                all_indices = [int(idx) for idx in self.tree.query(point.buffer(radius_m * 4.0))]
                indices = [
                    idx
                    for idx in all_indices
                    if self.physical_source_ids[idx] in allowed_source_ids
                    and (not allowed_subtypes or self.physical_subtypes[idx] in allowed_subtypes)
                ]
        return sorted(indices, key=lambda idx: point.distance(self.physical_geometries[idx]))[:20]

    def snap_point(
        self,
        point: Point,
        heading: float | None = None,
        radius_m: float = 250.0,
        allowed_subtypes: set[str] | None = None,
        allowed_source_ids: set[str] | None = None,
    ) -> tuple[str, float]:
        candidates = self.candidate_physical_indices(
            point, radius_m, allowed_subtypes, allowed_source_ids
        )
        best_link = ""
        best_distance = float("inf")
        best_score = float("inf")
        for index in candidates:
            geometry = self.physical_geometries[index]
            distance = point.distance(geometry)
            for link_id in self.physical_link_ids[index]:
                link = self.links[link_id]
                projected = link.geometry.project(point)
                before = link.geometry.interpolate(max(0.0, projected - 15.0))
                after = link.geometry.interpolate(min(link.geometry.length, projected + 15.0))
                link_heading = math.atan2(after.y - before.y, after.x - before.x)
                direction_penalty = 0.0
                if heading is not None:
                    direction_penalty = 80.0 * heading_difference(heading, link_heading) / math.pi
                legal_penalty = 30.0 if not link.legal_direction else 0.0
                score = distance + direction_penalty + legal_penalty
                if score < best_score:
                    best_score = score
                    best_link = link_id
                    best_distance = distance
        return best_link, best_distance

    def directed_candidates(
        self,
        point: Point,
        heading: float,
        primary_radius_m: float = ROAD_PRIMARY_SEARCH_RADIUS_M,
        fallback_radius_m: float = ROAD_FALLBACK_SEARCH_RADIUS_M,
        limit: int = 3,
    ) -> list[RoadCandidate]:
        indices = self.candidate_physical_indices(point, primary_radius_m)
        if not indices or point.distance(self.physical_geometries[indices[0]]) > primary_radius_m:
            indices = self.candidate_physical_indices(point, fallback_radius_m)
        candidates: list[RoadCandidate] = []
        for index in indices:
            geometry = self.physical_geometries[index]
            distance = float(point.distance(geometry))
            if distance > fallback_radius_m:
                continue
            for link_id in self.physical_link_ids[index]:
                link = self.links[link_id]
                projected = link.geometry.project(point)
                before = link.geometry.interpolate(max(0.0, projected - 15.0))
                after = link.geometry.interpolate(min(link.geometry.length, projected + 15.0))
                link_heading = math.atan2(after.y - before.y, after.x - before.x)
                heading_delta = heading_difference(heading, link_heading)
                legal_penalty = 0.0 if link.legal_direction else 45.0
                emission = distance + 65.0 * heading_delta / math.pi + legal_penalty
                candidates.append(
                    RoadCandidate(
                        link_id=link_id,
                        distance_m=distance,
                        heading_difference_rad=heading_delta,
                        emission_cost=emission,
                    )
                )
        candidates.sort(key=lambda item: item.emission_cost)
        result: list[RoadCandidate] = []
        seen_physical: set[tuple[str, str]] = set()
        for candidate in candidates:
            link = self.links[candidate.link_id]
            physical_key = tuple(sorted((link.from_node, link.to_node)))
            direction_key = (physical_key[0], candidate.link_id)
            if direction_key in seen_physical:
                continue
            seen_physical.add(direction_key)
            result.append(candidate)
            if len(result) >= limit:
                break
        return result

    def corridor_source_ids(self, geometry: LineString, radius_m: float) -> set[str]:
        if self.tree is None:
            raise RuntimeError("Network spatial index has not been finalized")
        return {
            self.physical_source_ids[int(index)]
            for index in self.tree.query(geometry.buffer(radius_m))
        }

    def shortest_path(
        self,
        start: str,
        end: str,
        relaxed: bool = False,
        allowed_source_ids: set[str] | None = None,
    ) -> list[str] | None:
        if start == end:
            return []
        key = (start, end, relaxed)
        if allowed_source_ids is None and key in self._path_cache:
            return self._path_cache[key]
        adjacency = self.adj_relaxed if relaxed else self.adj_legal
        end_xy = self.nodes[end]
        heap: list[tuple[float, float, str]] = [(0.0, 0.0, start)]
        costs: dict[str, float] = {start: 0.0}
        previous: dict[str, tuple[str, str]] = {}
        visited: set[str] = set()
        while heap:
            _, cost, node = heapq.heappop(heap)
            if node in visited:
                continue
            visited.add(node)
            if node == end:
                break
            for next_node, link_id, weight in adjacency.get(node, []):
                if allowed_source_ids and self.links[link_id].source_id not in allowed_source_ids:
                    continue
                next_cost = cost + weight
                if next_cost >= costs.get(next_node, float("inf")):
                    continue
                costs[next_node] = next_cost
                previous[next_node] = (node, link_id)
                xy = self.nodes[next_node]
                heuristic = math.hypot(xy[0] - end_xy[0], xy[1] - end_xy[1])
                heapq.heappush(heap, (next_cost + heuristic, next_cost, next_node))
        if end not in costs:
            if allowed_source_ids is None:
                self._path_cache[key] = None
            return None
        result: list[str] = []
        node = end
        while node != start:
            prior, link_id = previous[node]
            result.append(link_id)
            node = prior
        result.reverse()
        if allowed_source_ids is None and len(self._path_cache) < 50_000:
            self._path_cache[key] = result
        return result

    def connect_anchor_links(
        self, anchors: Sequence[str], allowed_source_ids: set[str] | None = None
    ) -> tuple[list[str], int, int]:
        anchors = [link_id for link_id in anchors if link_id]
        if not anchors:
            return [], 0, 0
        route: list[str] = [anchors[0]]
        relaxed_count = int(not self.links[anchors[0]].legal_direction)
        disconnected = 0
        for current_id in anchors[1:]:
            previous_id = route[-1]
            if current_id == previous_id:
                continue
            previous = self.links[previous_id]
            current = self.links[current_id]
            bridge = self.shortest_path(
                previous.to_node,
                current.from_node,
                relaxed=False,
                allowed_source_ids=allowed_source_ids,
            )
            use_relaxed = False
            direct_distance = math.hypot(
                self.nodes[previous.to_node][0] - self.nodes[current.from_node][0],
                self.nodes[previous.to_node][1] - self.nodes[current.from_node][1],
            )
            if bridge is not None:
                bridge_length = sum(self.links[link_id].length_m for link_id in bridge)
                if bridge_length > max(300.0, direct_distance * 2.0 + 300.0):
                    relaxed_bridge = self.shortest_path(
                        previous.to_node,
                        current.from_node,
                        relaxed=True,
                        allowed_source_ids=allowed_source_ids,
                    )
                    if relaxed_bridge is not None:
                        relaxed_length = sum(self.links[link_id].length_m for link_id in relaxed_bridge)
                        if relaxed_length < bridge_length * 0.65:
                            bridge = relaxed_bridge
                            use_relaxed = True
            else:
                bridge = self.shortest_path(
                    previous.to_node,
                    current.from_node,
                    relaxed=True,
                    allowed_source_ids=allowed_source_ids,
                )
                if bridge is None and allowed_source_ids:
                    bridge = self.shortest_path(previous.to_node, current.from_node, relaxed=True)
                use_relaxed = bridge is not None
            if bridge is not None:
                bridge_length = sum(self.links[link_id].length_m for link_id in bridge)
                reasonable_length = max(300.0, direct_distance * 2.0 + 300.0)
                if bridge_length > reasonable_length and direct_distance <= MAX_TOPOLOGY_CONNECTOR_M:
                    bridge = [
                        self.create_topology_connector(
                            previous.to_node, current.from_node, "trajectory_gap_connector"
                        )
                    ]
                    use_relaxed = False
            elif direct_distance <= MAX_TOPOLOGY_CONNECTOR_M:
                bridge = [
                    self.create_topology_connector(
                        previous.to_node, current.from_node, "trajectory_gap_connector"
                    )
                ]
            if bridge is None:
                disconnected += 1
                continue
            for link_id in [*bridge, current_id]:
                if route and link_id == route[-1]:
                    continue
                route.append(link_id)
                if not self.links[link_id].legal_direction:
                    relaxed_count += 1
            if use_relaxed:
                relaxed_count += 0
        return route, relaxed_count, disconnected


def endpoint_node_id(prefix: str, coordinate: tuple[float, float]) -> str:
    return f"{prefix}_{coordinate[0]:.2f}_{coordinate[1]:.2f}"


def build_road_network(path: Path) -> tuple[LinkNetwork, dict[str, Any]]:
    roads = gpd.read_file(path)
    source_crs = safe_text(roads.crs)
    roads = roads.to_crs(TARGET_CRS)
    network = LinkNetwork("road")
    bad_geometry = 0
    travel_directions = Counter()
    for row in roads.itertuples(index=False):
        parts = line_parts(row.geometry)
        if not parts:
            bad_geometry += 1
            continue
        route_id = safe_text(getattr(row, "ROUTE_ID", getattr(row, "OBJECTID", "")))
        travel_dir = safe_int(getattr(row, "TRAVEL_DIR", 3), 3)
        travel_directions[str(travel_dir)] += 1
        for part_index, geometry in enumerate(parts):
            coords = list(geometry.coords)
            start = (round(coords[0][0], 2), round(coords[0][1], 2))
            end = (round(coords[-1][0], 2), round(coords[-1][1], 2))
            if start == end:
                bad_geometry += 1
                continue
            start_node = endpoint_node_id("road", start)
            end_node = endpoint_node_id("road", end)
            network.nodes[start_node] = start
            network.nodes[end_node] = end
            base = f"road_{route_id}_{part_index}"
            directions = [
                (f"{base}_f", start_node, end_node, True),
                (f"{base}_r", end_node, start_node, travel_dir == 1),
            ]
            network.add_physical(
                geometry=geometry,
                source_id=route_id,
                subtype="road",
                directions=directions,
                allowed_modes="car,bus,gmb,pt",
                freespeed_mps=13.89,
            )
    network.finalize()
    summary = {
        "source": str(path),
        "source_crs": source_crs,
        "target_crs": TARGET_CRS,
        "source_features": int(len(roads)),
        "nodes": len(network.nodes),
        "physical_links": len(network.physical_geometries),
        "directed_links_including_relaxed": len(network.links),
        "legal_directed_links": sum(link.legal_direction for link in network.links.values()),
        "travel_dir_counts": dict(travel_directions),
        "invalid_or_closed_geometries": bad_geometry,
        "travel_dir_assumption": "TRAVEL_DIR=1 is bidirectional; TRAVEL_DIR=3 follows digitized direction",
    }
    return network, summary


class RailWayHandler(osmium.SimpleHandler):
    def __init__(self) -> None:
        super().__init__()
        self.ways: list[dict[str, Any]] = []
        self.route_relations: dict[str, set[str]] = defaultdict(set)
        self.route_relation_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.skipped_invalid_locations = 0

    def way(self, way: osmium.osm.Way) -> None:
        railway = safe_text(way.tags.get("railway"))
        if railway not in ACTIVE_RAILWAY_VALUES:
            return
        service = safe_text(way.tags.get("service"))
        if service in EXCLUDED_RAIL_SERVICES:
            return
        try:
            nodes = [(int(node.ref), float(node.lon), float(node.lat)) for node in way.nodes]
        except osmium.InvalidLocationError:
            self.skipped_invalid_locations += 1
            return
        if len(nodes) < 2:
            return
        self.ways.append(
            {
                "way_id": int(way.id),
                "railway": railway,
                "service": service,
                "name": safe_text(way.tags.get("name")),
                "ref": safe_text(way.tags.get("ref")),
                "operator": safe_text(way.tags.get("operator")),
                "nodes": nodes,
            }
        )

    def relation(self, relation: osmium.osm.Relation) -> None:
        route = safe_text(relation.tags.get("route"))
        ref = safe_text(relation.tags.get("ref"))
        if route not in {"railway", "train", "subway", "light_rail", "tram"} or not ref:
            return
        ordered_way_members: list[dict[str, str]] = []
        for member in relation.members:
            if member.type == "w":
                self.route_relations[ref].add(str(member.ref))
                ordered_way_members.append({"way_id": str(member.ref), "role": safe_text(member.role)})
        if ordered_way_members:
            self.route_relation_records[ref].append(
                {
                    "relation_id": str(relation.id),
                    "name": safe_text(relation.tags.get("name")),
                    "route": route,
                    "members": ordered_way_members,
                }
            )


def build_rail_network(path: Path) -> tuple[LinkNetwork, dict[str, Any]]:
    handler = RailWayHandler()
    handler.apply_file(str(path), locations=True)
    transformer = Transformer.from_crs("EPSG:4326", TARGET_CRS, always_xy=True)
    network = LinkNetwork("rail")
    subtype_counts = Counter()
    for way in handler.ways:
        nodes = way["nodes"]
        way_segment_links: list[str] = []
        for segment_index, (a, b) in enumerate(zip(nodes[:-1], nodes[1:])):
            a_id, a_lon, a_lat = a
            b_id, b_lon, b_lat = b
            ax, ay = transformer.transform(a_lon, a_lat)
            bx, by = transformer.transform(b_lon, b_lat)
            if math.hypot(bx - ax, by - ay) < 0.1:
                continue
            from_node = f"rail_osm_{a_id}"
            to_node = f"rail_osm_{b_id}"
            network.nodes[from_node] = (ax, ay)
            network.nodes[to_node] = (bx, by)
            base = f"rail_osm_{way['way_id']}_{segment_index}"
            directions = [
                (f"{base}_f", from_node, to_node, True),
                (f"{base}_r", to_node, from_node, True),
            ]
            railway = way["railway"]
            if railway == "light_rail":
                modes = "light_rail,pt"
                speed = 13.89
            elif railway == "tram":
                modes = "tram,pt"
                speed = 8.33
            else:
                modes = "train,pt"
                speed = 22.22
            network.add_physical(
                geometry=LineString([(ax, ay), (bx, by)]),
                source_id=str(way["way_id"]),
                subtype=railway,
                directions=directions,
                allowed_modes=modes,
                freespeed_mps=speed,
            )
            way_segment_links.append(f"{base}_f")
            subtype_counts[railway] += 1
        if way_segment_links:
            network.way_segment_links[str(way["way_id"])] = way_segment_links
    network.finalize()
    available_way_ids = {link.source_id for link in network.links.values()}
    network.route_way_ids = {
        ref: way_ids & available_way_ids
        for ref, way_ids in handler.route_relations.items()
        if way_ids & available_way_ids
    }
    network.route_relations = {
        ref: records for ref, records in handler.route_relation_records.items() if ref in network.route_way_ids
    }
    summary = {
        "source": str(path),
        "target_crs": TARGET_CRS,
        "source_ways": len(handler.ways),
        "nodes": len(network.nodes),
        "physical_links": len(network.physical_geometries),
        "directed_links": len(network.links),
        "physical_link_subtypes": dict(subtype_counts),
        "route_relation_refs": {ref: len(ids) for ref, ids in sorted(network.route_way_ids.items())},
        "excluded_services": sorted(EXCLUDED_RAIL_SERVICES),
        "skipped_invalid_locations": handler.skipped_invalid_locations,
        "direction_assumption": "active OSM rail tracks are represented in both directions",
    }
    return network, summary


def reversed_link_id(network: LinkNetwork, link_id: str) -> str:
    candidate = f"{link_id[:-2]}_r" if link_id.endswith("_f") else f"{link_id[:-2]}_f"
    if candidate not in network.links:
        link = network.links[link_id]
        if link.subtype in {"trajectory_gap_connector", "relation_gap_connector"}:
            return network.create_topology_connector(link.to_node, link.from_node, link.subtype)
        raise KeyError(f"Missing reverse rail link for {link_id}")
    return candidate


def ordered_relation_links(
    network: LinkNetwork,
    relation: dict[str, Any],
    start_hint: Point | None,
) -> tuple[list[str], int]:
    result: list[str] = []
    gap_count = 0
    relation_way_ids = {
        member["way_id"] for member in relation["members"] if member["way_id"] in network.way_segment_links
    }
    for member in relation["members"]:
        forward = network.way_segment_links.get(member["way_id"], [])
        if not forward:
            continue
        reverse = [reversed_link_id(network, link_id) for link_id in reversed(forward)]
        role = member["role"].lower()
        if role == "backward":
            selected = reverse
        elif role == "forward":
            selected = forward
        elif result:
            prior_node = network.links[result[-1]].to_node
            forward_distance = math.hypot(
                network.nodes[network.links[forward[0]].from_node][0] - network.nodes[prior_node][0],
                network.nodes[network.links[forward[0]].from_node][1] - network.nodes[prior_node][1],
            )
            reverse_distance = math.hypot(
                network.nodes[network.links[reverse[0]].from_node][0] - network.nodes[prior_node][0],
                network.nodes[network.links[reverse[0]].from_node][1] - network.nodes[prior_node][1],
            )
            selected = forward if forward_distance <= reverse_distance else reverse
        elif start_hint is not None:
            forward_start = Point(network.nodes[network.links[forward[0]].from_node])
            reverse_start = Point(network.nodes[network.links[reverse[0]].from_node])
            selected = forward if start_hint.distance(forward_start) <= start_hint.distance(reverse_start) else reverse
        else:
            selected = forward

        if result and network.links[result[-1]].to_node != network.links[selected[0]].from_node:
            start_node = network.links[result[-1]].to_node
            end_node = network.links[selected[0]].from_node
            bridge = network.shortest_path(
                start_node, end_node, relaxed=False, allowed_source_ids=relation_way_ids
            )
            if bridge is None:
                bridge = network.shortest_path(start_node, end_node, relaxed=False)
            direct = math.hypot(
                network.nodes[start_node][0] - network.nodes[end_node][0],
                network.nodes[start_node][1] - network.nodes[end_node][1],
            )
            if bridge is not None:
                bridge_length = sum(network.links[link_id].length_m for link_id in bridge)
                if bridge_length <= max(750.0, direct * 5.0 + 100.0):
                    result.extend(link_id for link_id in bridge if not result or link_id != result[-1])
                elif direct <= 1200.0:
                    result.append(
                        network.create_topology_connector(
                            start_node, end_node, "relation_gap_connector"
                        )
                    )
                else:
                    gap_count += 1
            elif direct <= 1200.0:
                result.append(
                    network.create_topology_connector(start_node, end_node, "relation_gap_connector")
                )
            else:
                gap_count += 1
        for link_id in selected:
            if not result or result[-1] != link_id:
                result.append(link_id)
    return result, gap_count


def select_osm_relation_route(
    network: LinkNetwork,
    line_code: str,
    trajectory: LineString,
    stops: Sequence[dict[str, Any]],
) -> tuple[list[str] | None, dict[str, Any]]:
    relations = network.route_relations.get(line_code, [])
    if not relations:
        return None, {}
    start_hint = Point(stops[0]["x"], stops[0]["y"]) if stops else Point(trajectory.coords[0])
    sample_points = [point for point, _ in sample_line(trajectory, 400.0)]
    candidates: list[tuple[float, list[str], dict[str, Any]]] = []
    for relation in relations:
        links, gaps = ordered_relation_links(network, relation, None)
        if not links:
            continue
        if stops:
            first_stop = Point(stops[0]["x"], stops[0]["y"])
            last_stop = Point(stops[-1]["x"], stops[-1]["y"])
            first_link_start = Point(network.links[links[0]].geometry.coords[0])
            last_link_end = Point(network.links[links[-1]].geometry.coords[-1])
            direct_endpoints = first_stop.distance(first_link_start) + last_stop.distance(last_link_end)
            reverse_endpoints = first_stop.distance(last_link_end) + last_stop.distance(first_link_start)
            if reverse_endpoints < direct_endpoints:
                links = [reversed_link_id(network, link_id) for link_id in reversed(links)]
        pieces = [network.links[link_id].geometry for link_id in links]
        geometry = linemerge(MultiLineString(pieces)) if len(pieces) > 1 else pieces[0]
        distances = [point.distance(geometry) for point in sample_points]
        median_distance = statistics.median(distances) if distances else float("inf")
        relation_length = sum(network.links[link_id].length_m for link_id in links)
        length_ratio = relation_length / max(trajectory.length, 1.0)
        first_point = Point(network.links[links[0]].geometry.coords[0])
        last_point = Point(network.links[links[-1]].geometry.coords[-1])
        endpoint_distance = start_hint.distance(first_point)
        if stops:
            endpoint_distance += Point(stops[-1]["x"], stops[-1]["y"]).distance(last_point)
        score = (
            median_distance
            + 0.1 * endpoint_distance
            + 500.0 * abs(math.log(max(length_ratio, 1e-6)))
            + 750.0 * gaps
        )
        metadata = {
            "osm_relation_id": relation["relation_id"],
            "osm_relation_name": relation["name"],
            "osm_relation_median_distance_m": round(float(median_distance), 3),
            "osm_relation_length_ratio": round(float(length_ratio), 4),
            "osm_relation_gap_count": gaps,
        }
        candidates.append((score, links, metadata))
    if not candidates:
        return None, {}
    _, links, metadata = min(candidates, key=lambda item: item[0])
    selected_relation = next(
        relation
        for relation in relations
        if relation["relation_id"] == metadata["osm_relation_id"]
    )
    metadata["_selected_way_ids"] = [
        member["way_id"]
        for member in selected_relation["members"]
        if member["way_id"] in network.way_segment_links
    ]
    if (
        metadata["osm_relation_median_distance_m"] > 300.0
        or metadata["osm_relation_gap_count"] > 0
        or not 0.70 <= metadata["osm_relation_length_ratio"] <= 1.40
    ):
        return None, metadata
    return links, metadata


def load_official_stops(api_root: Path) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    transformer = Transformer.from_crs("EPSG:4326", TARGET_CRS, always_xy=True)
    result: dict[str, list[dict[str, Any]]] = {}
    source_counts: dict[str, int] = {}
    base = api_root / "static" / "routes_fares_route_stop_points"
    for mode, filename in (("bus", "bus_route_stop_points.json"), ("gmb", "gmb_route_stop_points.json")):
        with (base / filename).open("r", encoding="utf-8-sig") as handle:
            collection = json.load(handle)
        source_counts[mode] = len(collection["features"])
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for feature in collection["features"]:
            properties = feature["properties"]
            route_id = safe_text(properties.get("routeId"))
            route_seq = safe_text(properties.get("routeSeq"))
            route_key = f"{mode}_{route_id}_{route_seq}"
            lon, lat = feature["geometry"]["coordinates"][:2]
            x, y = transformer.transform(lon, lat)
            groups[route_key].append(
                {
                    "route_key": route_key,
                    "mode": mode,
                    "route_id": route_id,
                    "route_seq": route_seq,
                    "company_code": safe_text(properties.get("companyCode")),
                    "route_name": safe_text(properties.get("routeNameE") or properties.get("routeNameC")),
                    "stop_seq": safe_int(properties.get("stopSeq")),
                    "stop_id": safe_text(properties.get("stopId")),
                    "stop_name_en": safe_text(properties.get("stopNameE")),
                    "stop_name_zh": safe_text(properties.get("stopNameC")),
                    "lon": float(lon),
                    "lat": float(lat),
                    "x": float(x),
                    "y": float(y),
                }
            )
        for route_key, stops in groups.items():
            result[route_key] = sorted(stops, key=lambda item: item["stop_seq"])
    summary = {
        "feature_counts": source_counts,
        "route_patterns": len(result),
        "route_patterns_by_mode": dict(Counter(key.split("_", 1)[0] for key in result)),
    }
    return result, summary


def load_csdi_trajectories(api_root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    sources = [
        ("bus", api_root / "geometry" / "franchised_bus_routes.geojson"),
        ("gmb", api_root / "geometry" / "green_minibus_routes.geojson"),
    ]
    for mode, path in sources:
        frame = gpd.read_file(path).to_crs(TARGET_CRS)
        for row in frame.itertuples(index=False):
            route_id = safe_text(getattr(row, "ROUTE_ID"))
            route_seq = safe_text(getattr(row, "ROUTE_SEQ"))
            key = f"{mode}_{route_id}_{route_seq}"
            result[key] = {
                "geometry": row.geometry,
                "source": "csdi",
                "source_record_id": safe_text(getattr(row, "OBJECTID", "")),
                "route_id": route_id,
                "route_seq": route_seq,
                "mode": mode,
            }
    return result


def load_amap_trajectories(amap_root: Path) -> tuple[dict[str, dict[str, Any]], pd.DataFrame]:
    path = amap_root / "geometry" / "amap_official_target_matches_combined_wgs84.geojson"
    frame = gpd.read_file(path).to_crs(TARGET_CRS)
    result: dict[str, dict[str, Any]] = {}
    for row in frame.itertuples(index=False):
        key = safe_text(row.target_id)
        result[key] = {
            "geometry": row.geometry,
            "source": "amap_spatial_qa",
            "source_record_id": safe_text(row.amap_line_id),
            "amap_line_id": safe_text(row.amap_line_id),
            "official_origin": safe_text(row.official_origin),
            "official_destination": safe_text(row.official_destination),
            "line_code": safe_text(row.line_code),
            "mode": safe_text(row.mode),
            "route_id": safe_text(row.official_route_id),
            "route_seq": safe_text(row.official_route_seq),
        }
    stop_frames: list[pd.DataFrame] = []
    for stops_path in (
        amap_root.parent / "AMap_Supplements" / "normalized" / "amap_stops_by_line.csv",
        amap_root / "normalized" / "amap_stops_by_line.csv",
    ):
        if stops_path.exists():
            stop_frames.append(pd.read_csv(stops_path, dtype={"amap_line_id": str}))
    if not stop_frames:
        raise FileNotFoundError("No AMap stops-by-line table found")
    amap_stops = pd.concat(stop_frames, ignore_index=True).drop_duplicates(
        subset=["amap_line_id", "sequence", "amap_stop_id"], keep="last"
    )
    return result, amap_stops


def orient_geometry(line: LineString, stops: Sequence[dict[str, Any]]) -> tuple[LineString, bool]:
    if not stops:
        return line, False
    first = Point(stops[0]["x"], stops[0]["y"])
    last = Point(stops[-1]["x"], stops[-1]["y"])
    direct = first.distance(Point(line.coords[0])) + last.distance(Point(line.coords[-1]))
    reverse = first.distance(Point(line.coords[-1])) + last.distance(Point(line.coords[0]))
    if reverse + 1.0 < direct:
        return LineString(list(line.coords)[::-1]), True
    return line, False


def sample_line_observations(
    line: LineString, spacing_m: float
) -> list[tuple[float, Point, float]]:
    if line.length <= 0:
        return []
    offsets = list(np.arange(0.0, line.length, max(spacing_m, 1.0)))
    if not offsets or offsets[-1] < line.length:
        offsets.append(float(line.length))
    observations: list[tuple[float, Point, float]] = []
    for offset in offsets:
        point = line.interpolate(offset)
        before = line.interpolate(max(0.0, offset - 15.0))
        after = line.interpolate(min(line.length, offset + 15.0))
        observations.append(
            (offset, point, math.atan2(after.y - before.y, after.x - before.x))
        )
    return observations


def route_repeated_length(network: LinkNetwork, route_links: Sequence[str]) -> float:
    seen: set[str] = set()
    repeated = 0.0
    for link_id in route_links:
        if link_id in seen:
            repeated += network.links[link_id].length_m
        seen.add(link_id)
    return repeated


def route_subtype_length(
    network: LinkNetwork, route_links: Sequence[str], subtypes: set[str]
) -> float:
    return sum(
        network.links[link_id].length_m
        for link_id in route_links
        if network.links[link_id].subtype in subtypes
    )


def route_direction_exception_length(network: LinkNetwork, route_links: Sequence[str]) -> float:
    return sum(
        network.links[link_id].length_m
        for link_id in route_links
        if not network.links[link_id].legal_direction
    )


def clean_link_sequence(route_links: Sequence[str]) -> list[str]:
    result: list[str] = []
    for link_id in route_links:
        if not result or result[-1] != link_id:
            result.append(link_id)
    return result


def road_transition(
    network: LinkNetwork,
    previous: RoadCandidate,
    current: RoadCandidate,
    source_segment: LineString,
    expected_length_m: float,
    evidence_supported: bool,
) -> tuple[list[str], float, int, int] | None:
    if previous.link_id == current.link_id:
        return [], 0.0, 0, 0
    previous_link = network.links[previous.link_id]
    current_link = network.links[current.link_id]
    direct_node_distance = Point(network.nodes[previous_link.to_node]).distance(
        Point(network.nodes[current_link.from_node])
    )

    def find_path(relaxed: bool, corridor_m: float) -> list[str] | None:
        allowed = network.corridor_source_ids(source_segment, corridor_m)
        allowed.update({previous_link.source_id, current_link.source_id})
        return network.shortest_path(
            previous_link.to_node,
            current_link.from_node,
            relaxed=relaxed,
            allowed_source_ids=allowed,
        )

    def reasonable(path: Sequence[str] | None) -> bool:
        if path is None:
            return False
        path_length = sum(network.links[link_id].length_m for link_id in path)
        return not (
            path_length > expected_length_m * 2.0
            and path_length - expected_length_m > 300.0
        )

    selected: list[str] | None = None
    used_relaxed = False
    for corridor in (ROAD_LOCAL_CORRIDOR_M, ROAD_EXPANDED_CORRIDOR_M):
        legal = find_path(False, corridor)
        if reasonable(legal) and current_link.legal_direction:
            selected = legal
            break
    if selected is None and evidence_supported:
        for corridor in (ROAD_LOCAL_CORRIDOR_M, ROAD_EXPANDED_CORRIDOR_M):
            relaxed = find_path(True, corridor)
            if reasonable(relaxed):
                selected = relaxed
                used_relaxed = True
                break
    connector_count = 0
    if selected is None and evidence_supported and direct_node_distance <= MAX_TOPOLOGY_CONNECTOR_M:
        selected = [
            network.create_topology_connector(
                previous_link.to_node,
                current_link.from_node,
                "trajectory_gap_connector",
            )
        ]
        connector_count = 1
    if selected is None:
        return None

    added = clean_link_sequence([*selected, current.link_id])
    added_length = sum(network.links[link_id].length_m for link_id in added)
    detour_penalty = max(0.0, added_length - expected_length_m) * 0.35
    relaxed_length = sum(
        network.links[link_id].length_m
        for link_id in added
        if not network.links[link_id].legal_direction
    )
    connector_length = route_subtype_length(
        network, added, {"trajectory_gap_connector", "relation_gap_connector"}
    )
    transition_cost = detour_penalty + relaxed_length * 0.18 + connector_length * 0.6
    relaxed_occurrences = sum(not network.links[link_id].legal_direction for link_id in added)
    if used_relaxed and relaxed_occurrences == 0:
        used_relaxed = False
    return added, transition_cost, relaxed_occurrences, connector_count


def road_candidate_sequence_match(
    network: LinkNetwork,
    line: LineString,
    stops: Sequence[dict[str, Any]],
    spacing_m: float,
) -> tuple[list[str], int, int] | None:
    observations = sample_line_observations(line, spacing_m)
    if not observations:
        return None
    evidence_supported = len(stops) >= 2 and sum(
        Point(stop["x"], stop["y"]).distance(line) <= STOP_COVERAGE_WARNING_M
        for stop in stops
    ) >= 2
    candidate_layers: list[list[RoadCandidate]] = []
    for _, point, heading in observations:
        candidates = network.directed_candidates(point, heading)
        if not candidates:
            return None
        candidate_layers.append(candidates)

    states: dict[str, MatchState] = {}
    for candidate in candidate_layers[0]:
        link = network.links[candidate.link_id]
        if not link.legal_direction and not evidence_supported:
            continue
        states[candidate.link_id] = MatchState(
            cost=candidate.emission_cost,
            candidate=candidate,
            route_links=[candidate.link_id],
            relaxed_occurrences=int(not link.legal_direction),
            connector_occurrences=0,
        )
    if not states:
        return None

    for observation_index in range(1, len(observations)):
        previous_offset, previous_point, _ = observations[observation_index - 1]
        current_offset, current_point, _ = observations[observation_index]
        source_segment = LineString([previous_point, current_point])
        expected = max(current_offset - previous_offset, 1.0)
        next_states: dict[str, MatchState] = {}
        for current in candidate_layers[observation_index]:
            best: MatchState | None = None
            for previous_state in states.values():
                transition = road_transition(
                    network,
                    previous_state.candidate,
                    current,
                    source_segment,
                    expected,
                    evidence_supported,
                )
                if transition is None:
                    continue
                added, transition_cost, relaxed_count, connector_count = transition
                existing = set(previous_state.route_links)
                repeated_length = sum(
                    network.links[link_id].length_m for link_id in added if link_id in existing
                )
                cost = (
                    previous_state.cost
                    + current.emission_cost
                    + transition_cost
                    + repeated_length * 0.45
                )
                candidate_state = MatchState(
                    cost=cost,
                    candidate=current,
                    route_links=clean_link_sequence([*previous_state.route_links, *added]),
                    relaxed_occurrences=previous_state.relaxed_occurrences + relaxed_count,
                    connector_occurrences=previous_state.connector_occurrences + connector_count,
                )
                if best is None or candidate_state.cost < best.cost:
                    best = candidate_state
            if best is not None:
                next_states[current.link_id] = best
        if not next_states:
            return None
        states = next_states
    best = min(states.values(), key=lambda state: state.cost)
    return best.route_links, best.relaxed_occurrences, best.connector_occurrences


def route_geometry(network: LinkNetwork, route_links: Sequence[str]) -> Any:
    if not route_links:
        return None
    pieces = [network.links[link_id].geometry for link_id in route_links]
    return linemerge(MultiLineString(pieces)) if len(pieces) > 1 else pieces[0]


def monotone_stop_assignment(
    stops: Sequence[dict[str, Any]],
    route_links: Sequence[str],
    network: LinkNetwork,
) -> tuple[list[int], float] | None:
    if not stops or not route_links:
        return [], 0.0
    layers: list[list[tuple[int, float]]] = []
    for stop in stops:
        point = Point(stop["x"], stop["y"])
        distances = sorted(
            (
                (index, float(point.distance(network.links[link_id].geometry)))
                for index, link_id in enumerate(route_links)
            ),
            key=lambda item: (item[1], item[0]),
        )
        minimum = distances[0][1]
        candidates = [item for item in distances if item[1] <= minimum + 40.0][:80]
        layers.append(candidates or distances[:1])

    states: dict[int, tuple[float, list[int]]] = {
        index: (distance, [index]) for index, distance in layers[0]
    }
    for layer in layers[1:]:
        next_states: dict[int, tuple[float, list[int]]] = {}
        for index, distance in layer:
            options = [
                (cost + distance + (index - previous_index) * 0.001, path + [index])
                for previous_index, (cost, path) in states.items()
                if previous_index <= index
            ]
            if options:
                next_states[index] = min(options, key=lambda item: item[0])
        if not next_states:
            return None
        states = next_states
    cost, path = min(states.values(), key=lambda item: item[0])
    return path, cost


def assign_stops_in_route_order(
    stops: Sequence[dict[str, Any]],
    route_links: list[str],
    network: LinkNetwork,
) -> tuple[list[str], list[dict[str, Any]], int, bool]:
    if not stops or not route_links:
        return route_links, [], 0, False
    closed = network.links[route_links[-1]].to_node == network.links[route_links[0]].from_node
    rotations = [0]
    if closed:
        first_point = Point(stops[0]["x"], stops[0]["y"])
        nearest = sorted(
            range(len(route_links)),
            key=lambda index: first_point.distance(network.links[route_links[index]].geometry),
        )[:12]
        rotations.extend(index for index in nearest if index not in rotations)

    best: tuple[float, int, list[str], list[int]] | None = None
    for rotation in rotations:
        rotated = route_links[rotation:] + route_links[:rotation]
        assignment = monotone_stop_assignment(stops, rotated, network)
        if assignment is None:
            continue
        indices, cost = assignment
        candidate = (cost, rotation, rotated, indices)
        if best is None or candidate[0] < best[0]:
            best = candidate
    if best is None:
        assigned_indices = [
            min(
                range(len(route_links)),
                key=lambda index: Point(stop["x"], stop["y"]).distance(
                    network.links[route_links[index]].geometry
                ),
            )
            for stop in stops
        ]
        best = (float("inf"), 0, route_links, assigned_indices)

    _, rotation, selected_links, assigned_indices = best
    rows: list[dict[str, Any]] = []
    for stop, assigned_index in zip(stops, assigned_indices, strict=True):
        point = Point(stop["x"], stop["y"])
        coverage_distance = min(
            point.distance(network.links[link_id].geometry) for link_id in selected_links
        )
        assigned_link = network.links[selected_links[assigned_index]]
        assignment_distance = point.distance(assigned_link.geometry)
        network_link_id, network_distance = network.snap_point(point, radius_m=STOP_COVERAGE_WARNING_M)
        rows.append(
            {
                **stop,
                "link_id": assigned_link.link_id,
                "route_link_index": assigned_index,
                "route_link_index_unwrapped": assigned_index,
                "coverage_distance_m": round(float(coverage_distance), 3),
                "assignment_distance_m": round(float(assignment_distance), 3),
                "nearest_network_link_id": network_link_id,
                "nearest_network_distance_m": round(float(network_distance), 3),
                "snap_distance_m": round(float(assignment_distance), 3),
                "external_or_uncovered": bool(coverage_distance > EXTERNAL_STOP_THRESHOLD_M),
            }
        )
    return selected_links, rows, int(rotation > 0), math.isfinite(best[0])


def trajectory_deviation_metrics(
    network: LinkNetwork,
    route_links: Sequence[str],
    line: LineString | None,
) -> tuple[float | None, float | None]:
    if line is None or not route_links:
        return None, None
    matched = route_geometry(network, route_links)
    source_distances = [point.distance(matched) for point, _ in sample_line(line, 100.0)]
    matched_distances: list[float] = []
    for link_id in route_links:
        matched_distances.extend(
            point.distance(line) for point, _ in sample_line(network.links[link_id].geometry, 100.0)
        )
    return percentile(source_distances, 95), percentile(matched_distances, 95)


def extend_to_terminal_stop(
    route_key: str,
    network: LinkNetwork,
    route_links: list[str],
    stops: Sequence[dict[str, Any]],
) -> tuple[list[str], bool]:
    if route_key != "gmb_2000819_1" or not route_links or not stops:
        return route_links, False
    target = stops[-1]
    target_point = Point(target["x"], target["y"])
    if min(target_point.distance(network.links[link_id].geometry) for link_id in route_links) <= STOP_COVERAGE_WARNING_M:
        return route_links, False
    previous = stops[-2]
    heading = math.atan2(target["y"] - previous["y"], target["x"] - previous["x"])
    candidates = [
        candidate
        for candidate in network.directed_candidates(target_point, heading, limit=8)
        if network.links[candidate.link_id].legal_direction
    ]
    if not candidates:
        return route_links, False
    previous_point = Point(previous["x"], previous["y"])
    previous_index = min(
        range(len(route_links)),
        key=lambda index: previous_point.distance(network.links[route_links[index]].geometry),
    )
    route_prefix = route_links[: previous_index + 1]
    start = network.links[route_prefix[-1]].to_node
    for candidate in candidates:
        target_link = network.links[candidate.link_id]
        bridge = network.shortest_path(start, target_link.from_node, relaxed=False)
        if bridge is None:
            continue
        direct = Point(network.nodes[start]).distance(Point(network.nodes[target_link.from_node]))
        bridge_length = sum(network.links[link_id].length_m for link_id in bridge)
        if bridge_length <= max(3000.0, direct * 2.0 + 500.0):
            return clean_link_sequence([*route_prefix, *bridge, candidate.link_id]), True
    return route_links, False


def close_evidence_supported_loop(
    network: LinkNetwork,
    route_links: list[str],
    line: LineString | None,
    stops: Sequence[dict[str, Any]],
) -> tuple[list[str], bool]:
    if line is None or not route_links:
        return route_links, False
    source_closed = Point(line.coords[0]).distance(Point(line.coords[-1])) <= STOP_COVERAGE_WARNING_M
    stops_closed = bool(
        len(stops) >= 2
        and Point(stops[0]["x"], stops[0]["y"]).distance(
            Point(stops[-1]["x"], stops[-1]["y"])
        )
        <= STOP_COVERAGE_WARNING_M
    )
    if not source_closed and not stops_closed:
        return route_links, False
    first_node = network.links[route_links[0]].from_node
    last_node = network.links[route_links[-1]].to_node
    if first_node == last_node:
        return route_links, False
    gap = Point(network.nodes[first_node]).distance(Point(network.nodes[last_node]))
    if gap > MAX_TOPOLOGY_CONNECTOR_M:
        return route_links, False
    connector = network.create_topology_connector(
        last_node, first_node, "trajectory_gap_connector"
    )
    return clean_link_sequence([*route_links, connector]), True


def create_trajectory_evidence_route(
    network: LinkNetwork,
    route_key: str,
    mode: str,
    line: LineString,
    spacing_m: float = 80.0,
) -> list[str]:
    observations = sample_line_observations(line, min(spacing_m, MAX_TOPOLOGY_CONNECTOR_M))
    if len(observations) < 2:
        return []
    token = hashlib.sha1(route_key.encode("utf-8")).hexdigest()[:12]
    points = [observation[1] for observation in observations]
    closed = points[0].distance(points[-1]) <= STOP_COVERAGE_WARNING_M
    if closed:
        points[-1] = points[0]
    node_ids: list[str] = []
    for index, point in enumerate(points):
        if closed and index == len(points) - 1:
            node_ids.append(node_ids[0])
            continue
        node_id = f"road_evidence_{token}_{index:04d}"
        network.nodes[node_id] = (float(point.x), float(point.y))
        node_ids.append(node_id)
    route_links: list[str] = []
    for index in range(len(points) - 1):
        geometry = LineString([points[index], points[index + 1]])
        if geometry.length <= 0:
            continue
        link_id = f"road_trajectory_evidence_{token}_{index:04d}"
        link = Link(
            link_id=link_id,
            from_node=node_ids[index],
            to_node=node_ids[index + 1],
            length_m=float(geometry.length),
            geometry=geometry,
            network_type="road",
            source_id=route_key,
            subtype="trajectory_evidence_link",
            legal_direction=True,
            allowed_modes=f"{mode},pt",
            freespeed_mps=8.33,
        )
        network.links[link_id] = link
        network.adj_legal[link.from_node].append((link.to_node, link_id, link.length_m))
        network.adj_relaxed[link.from_node].append((link.to_node, link_id, link.length_m))
        route_links.append(link_id)
    return route_links


def create_ordered_stop_trajectory_evidence_route(
    network: LinkNetwork,
    route_key: str,
    mode: str,
    line: LineString,
    stops: Sequence[dict[str, Any]],
    spacing_m: float = 80.0,
) -> list[str]:
    observations = sample_line_observations(line, spacing_m)
    if len(observations) < 2 or len(stops) < 2:
        return []
    source_points = [observation[1] for observation in observations]
    closed = source_points[0].distance(source_points[-1]) <= STOP_COVERAGE_WARNING_M
    if closed:
        source_points = source_points[:-1]
    if len(source_points) < 2:
        return []

    def index_path(start: int, end: int) -> tuple[list[int], float]:
        if start == end:
            return [start], 0.0
        if not closed:
            step = 1 if end > start else -1
            indices = list(range(start, end + step, step))
            length = sum(
                source_points[left].distance(source_points[right])
                for left, right in zip(indices[:-1], indices[1:], strict=True)
            )
            return indices, float(length)
        size = len(source_points)
        forward = [start]
        while forward[-1] != end:
            forward.append((forward[-1] + 1) % size)
        backward = [start]
        while backward[-1] != end:
            backward.append((backward[-1] - 1) % size)

        def length(indices: Sequence[int]) -> float:
            return float(
                sum(
                    source_points[left].distance(source_points[right])
                    for left, right in zip(indices[:-1], indices[1:], strict=True)
                )
            )

        forward_length = length(forward)
        backward_length = length(backward)
        return (forward, forward_length) if forward_length <= backward_length else (backward, backward_length)

    stop_candidates: list[list[tuple[int, float]]] = []
    for stop in stops:
        point = Point(stop["x"], stop["y"])
        distances = sorted(
            ((index, float(point.distance(source_point))) for index, source_point in enumerate(source_points)),
            key=lambda item: (item[1], item[0]),
        )
        minimum = distances[0][1]
        stop_candidates.append(
            [item for item in distances if item[1] <= minimum + 40.0][:20]
        )

    chosen = min(stop_candidates[0], key=lambda item: item[1])[0]
    ordered_indices = [chosen]
    for candidates in stop_candidates[1:]:
        options: list[tuple[float, int, list[int]]] = []
        for candidate_index, emission in candidates:
            path, path_length = index_path(chosen, candidate_index)
            options.append((emission + path_length * 0.001, candidate_index, path))
        _, chosen, path = min(options, key=lambda item: item[0])
        ordered_indices.extend(path[1:])
    ordered_indices = [
        value
        for index, value in enumerate(ordered_indices)
        if index == 0 or value != ordered_indices[index - 1]
    ]
    if len(ordered_indices) < 2:
        return []

    token = hashlib.sha1((route_key + "|ordered").encode("utf-8")).hexdigest()[:12]
    route_points = [source_points[index] for index in ordered_indices]
    route_links: list[str] = []
    prior_node = ""
    for index, point in enumerate(route_points):
        node_id = f"road_ordered_evidence_{token}_{index:05d}"
        network.nodes[node_id] = (float(point.x), float(point.y))
        if index == 0:
            prior_node = node_id
            continue
        geometry = LineString([route_points[index - 1], point])
        if geometry.length <= 0:
            continue
        link_id = f"road_ordered_trajectory_evidence_{token}_{index - 1:05d}"
        link = Link(
            link_id=link_id,
            from_node=prior_node,
            to_node=node_id,
            length_m=float(geometry.length),
            geometry=geometry,
            network_type="road",
            source_id=route_key,
            subtype="ordered_trajectory_evidence_link",
            legal_direction=True,
            allowed_modes=f"{mode},pt",
            freespeed_mps=8.33,
        )
        network.links[link_id] = link
        network.adj_legal[link.from_node].append((link.to_node, link_id, link.length_m))
        network.adj_relaxed[link.from_node].append((link.to_node, link_id, link.length_m))
        route_links.append(link_id)
        prior_node = node_id
    return route_links


def rail_stops_for_target(record: dict[str, Any], amap_stops: pd.DataFrame) -> list[dict[str, Any]]:
    line_id = safe_text(record.get("amap_line_id"))
    rows = amap_stops.loc[amap_stops["amap_line_id"].astype(str) == line_id].copy()
    if rows.empty:
        return []
    rows = rows.sort_values("sequence")
    origin = normalize_name(record.get("official_origin"))
    destination = normalize_name(record.get("official_destination"))
    names = rows["station_name"].map(normalize_name).tolist()
    first_score = int(bool(origin and (origin in names[0] or names[0] in origin))) + int(
        bool(destination and (destination in names[-1] or names[-1] in destination))
    )
    reverse_score = int(bool(origin and (origin in names[-1] or names[-1] in origin))) + int(
        bool(destination and (destination in names[0] or names[0] in destination))
    )
    if reverse_score > first_score:
        rows = rows.iloc[::-1].copy()
    transformer = Transformer.from_crs("EPSG:4326", TARGET_CRS, always_xy=True)
    result: list[dict[str, Any]] = []
    for new_sequence, row in enumerate(rows.itertuples(index=False), start=1):
        lon = float(row.lon_wgs84)
        lat = float(row.lat_wgs84)
        x, y = transformer.transform(lon, lat)
        result.append(
            {
                "route_key": safe_text(record.get("route_key")),
                "mode": safe_text(record.get("mode")),
                "route_id": safe_text(record.get("route_id")),
                "route_seq": safe_text(record.get("route_seq")),
                "company_code": "MTR",
                "route_name": safe_text(record.get("line_code")),
                "stop_seq": new_sequence,
                "stop_id": safe_text(row.amap_stop_id),
                "stop_name_en": "",
                "stop_name_zh": safe_text(row.station_name),
                "lon": lon,
                "lat": lat,
                "x": float(x),
                "y": float(y),
            }
        )
    return result


def match_route(
    route_key: str,
    mode: str,
    network: LinkNetwork,
    stops: list[dict[str, Any]],
    trajectory_record: dict[str, Any] | None,
    spacing_m: float,
    allowed_source_ids: set[str] | None = None,
    precomputed_route_links: list[str] | None = None,
    relation_metadata: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], Any]:
    source = safe_text(trajectory_record.get("source")) if trajectory_record else "ordered_official_stops"
    line: LineString | None = None
    reversed_to_stops = False
    anchor_points: list[tuple[Point, float | None]] = []
    if trajectory_record:
        start_hint = Point(stops[0]["x"], stops[0]["y"]) if stops else None
        line = ordered_linestring(trajectory_record.get("geometry"), start_hint=start_hint)
        if line is not None:
            line, reversed_to_stops = orient_geometry(line, stops)
            anchor_points = [(point, heading) for point, heading in sample_line(line, spacing_m)]
    if not anchor_points and stops:
        for index, stop in enumerate(stops):
            previous = stops[max(0, index - 1)]
            following = stops[min(len(stops) - 1, index + 1)]
            heading = math.atan2(following["y"] - previous["y"], following["x"] - previous["x"])
            anchor_points.append((Point(stop["x"], stop["y"]), heading))
    effective_allowed_source_ids = allowed_source_ids
    if mode in ROAD_MODES and line is not None and network.tree is not None:
        corridor_indices = [int(idx) for idx in network.tree.query(line.buffer(ROAD_EXPANDED_CORRIDOR_M))]
        corridor_source_ids = {network.physical_source_ids[idx] for idx in corridor_indices}
        if corridor_source_ids:
            effective_allowed_source_ids = corridor_source_ids
    allowed_subtypes = None
    if mode == "mtr":
        allowed_subtypes = {"rail", "subway"}
    elif mode == "lrt":
        allowed_subtypes = {"light_rail"}
    snap_radius = ROAD_FALLBACK_SEARCH_RADIUS_M if mode in ROAD_MODES else 180.0
    snapped: list[str] = []
    anchor_distances: list[float] = []
    for point, heading in anchor_points:
        link_id, distance = network.snap_point(
            point,
            heading=heading,
            radius_m=snap_radius,
            allowed_subtypes=allowed_subtypes,
            allowed_source_ids=effective_allowed_source_ids,
        )
        if link_id:
            snapped.append(link_id)
            anchor_distances.append(float(distance))
    deduped: list[str] = []
    for link_id in snapped:
        if not deduped or deduped[-1] != link_id:
            deduped.append(link_id)
    if precomputed_route_links:
        route_links = list(precomputed_route_links)
        relaxed_link_occurrences = 0
        disconnected_gaps = safe_int((relation_metadata or {}).get("osm_relation_gap_count"))
        anchor_distances = [
            min(point.distance(network.links[link_id].geometry) for link_id in route_links)
            for point, _ in anchor_points
        ]
    else:
        route_links, relaxed_link_occurrences, disconnected_gaps = network.connect_anchor_links(
            deduped, allowed_source_ids=effective_allowed_source_ids
        )

    repair_methods: list[str] = []
    trajectory_length = float(line.length) if line is not None else None
    base_route_length = sum(network.links[link_id].length_m for link_id in route_links)
    base_ratio = (
        base_route_length / trajectory_length
        if trajectory_length is not None and trajectory_length > 0
        else None
    )
    base_repeated = route_repeated_length(network, route_links)
    base_connector_lengths = [
        network.links[link_id].length_m
        for link_id in route_links
        if network.links[link_id].subtype in {"trajectory_gap_connector", "relation_gap_connector"}
    ]
    needs_candidate_repair = bool(
        mode in ROAD_MODES
        and line is not None
        and (
            (base_ratio is not None and base_ratio > 1.5)
            or (base_route_length > 0 and base_repeated / base_route_length > 0.05)
            or (base_connector_lengths and max(base_connector_lengths) > MAX_TOPOLOGY_CONNECTOR_M)
        )
    )
    if needs_candidate_repair and line is not None:
        candidate_result = road_candidate_sequence_match(
            network, line, stops, min(spacing_m, 100.0)
        )
        if candidate_result is not None:
            candidate_links, candidate_relaxed, _ = candidate_result

            def path_objective(links: Sequence[str]) -> float:
                length = sum(network.links[link_id].length_m for link_id in links)
                ratio_penalty = 0.0
                if trajectory_length:
                    ratio_penalty = abs(math.log(max(length / trajectory_length, 1e-6))) * 2500.0
                repeated_penalty = route_repeated_length(network, links) * 0.8
                connector_penalty = route_subtype_length(
                    network, links, {"trajectory_gap_connector", "relation_gap_connector"}
                ) * 1.2
                _, matched_to_source = trajectory_deviation_metrics(network, links, line)
                return ratio_penalty + repeated_penalty + connector_penalty + (matched_to_source or 0.0) * 20.0

            if candidate_links and path_objective(candidate_links) < path_objective(route_links) * 0.98:
                route_links = candidate_links
                relaxed_link_occurrences = candidate_relaxed
                disconnected_gaps = 0
                repair_methods.append("candidate_sequence_dp")

    route_links, loop_closed = close_evidence_supported_loop(
        network, route_links, line, stops
    )
    if loop_closed:
        repair_methods.append("evidence_supported_loop_closure")

    if mode in ROAD_MODES and line is not None and source == "csdi" and stops:
        preliminary_length = sum(network.links[link_id].length_m for link_id in route_links)
        preliminary_ratio = preliminary_length / trajectory_length if trajectory_length else None
        _, preliminary_matched_to_source = trajectory_deviation_metrics(
            network, route_links, line
        )
        stops_support_source = all(
            Point(stop["x"], stop["y"]).distance(line) <= STOP_COVERAGE_WARNING_M
            for stop in stops
        )
        if stops_support_source and (
            (preliminary_ratio is not None and preliminary_ratio > 1.5)
            or (
                preliminary_matched_to_source is not None
                and preliminary_matched_to_source > 100.0
            )
        ):
            evidence_links = create_trajectory_evidence_route(
                network, route_key, mode, line
            )
            if evidence_links:
                route_links = evidence_links
                relaxed_link_occurrences = 0
                disconnected_gaps = 0
                repair_methods.append("trajectory_evidence_links")

    route_links, terminal_extended = extend_to_terminal_stop(
        route_key, network, route_links, stops
    )
    if terminal_extended:
        repair_methods.append("ordered_stop_extension")
        disconnected_gaps = 0

    route_links, stop_rows, stop_sequence_wrap_count, stop_assignment_ordered = (
        assign_stops_in_route_order(stops, route_links, network)
    )
    if (
        not stop_assignment_ordered
        and mode in ROAD_MODES
        and line is not None
        and source == "csdi"
        and stops
        and all(
            Point(stop["x"], stop["y"]).distance(line) <= STOP_COVERAGE_WARNING_M
            for stop in stops
        )
    ):
        evidence_links = create_ordered_stop_trajectory_evidence_route(
            network, route_key, mode, line, stops
        )
        if evidence_links:
            route_links, stop_rows, stop_sequence_wrap_count, stop_assignment_ordered = (
                assign_stops_in_route_order(stops, evidence_links, network)
            )
            repair_methods.append("ordered_stop_trajectory_evidence")
    if stop_sequence_wrap_count:
        repair_methods.append("cyclic_route_rotation")
    for stop_row in stop_rows:
        point = Point(stop_row["x"], stop_row["y"])
        stop_row["trajectory_distance_m"] = (
            round(float(point.distance(line)), 3) if line is not None else None
        )

    assignment_distances = [float(row["assignment_distance_m"]) for row in stop_rows]
    coverage_distances = [float(row["coverage_distance_m"]) for row in stop_rows]
    network_distances = [float(row["nearest_network_distance_m"]) for row in stop_rows]
    source_stop_distances = [
        float(row["trajectory_distance_m"])
        for row in stop_rows
        if row.get("trajectory_distance_m") is not None
    ]

    sequence_rows: list[dict[str, Any]] = []
    for sequence, link_id in enumerate(route_links, start=1):
        link = network.links[link_id]
        sequence_rows.append(
            {
                "route_key": route_key,
                "mode": mode,
                "sequence": sequence,
                "link_id": link_id,
                "from_node": link.from_node,
                "to_node": link.to_node,
                "length_m": round(link.length_m, 3),
                "network_type": link.network_type,
                "network_subtype": link.subtype,
                "legal_direction": link.legal_direction,
            }
        )

    matched_geometry = route_geometry(network, route_links)
    route_length = sum(network.links[link_id].length_m for link_id in route_links)
    relaxed_link_occurrences = sum(
        not network.links[link_id].legal_direction for link_id in route_links
    )
    topology_connector_occurrences = sum(
        network.links[link_id].subtype in {"trajectory_gap_connector", "relation_gap_connector"}
        for link_id in route_links
    )
    connector_lengths = [
        network.links[link_id].length_m
        for link_id in route_links
        if network.links[link_id].subtype in {"trajectory_gap_connector", "relation_gap_connector"}
    ]
    repeated_length = route_repeated_length(network, route_links)
    direction_exception_length = route_direction_exception_length(network, route_links)
    source_to_matched_p95, matched_to_source_p95 = trajectory_deviation_metrics(
        network, route_links, line
    )
    coverage_warning_stops = sum(
        distance > STOP_COVERAGE_WARNING_M for distance in coverage_distances
    )
    external_stops = sum(
        coverage > EXTERNAL_STOP_THRESHOLD_M
        and network_distance > EXTERNAL_STOP_THRESHOLD_M
        for coverage, network_distance in zip(
            coverage_distances, network_distances, strict=False
        )
    )
    trajectory_stop_mismatch = any(
        coverage > STOP_COVERAGE_WARNING_M
        and network_distance <= STOP_COVERAGE_WARNING_M
        and source_distance > STOP_COVERAGE_WARNING_M
        for coverage, network_distance, source_distance in zip(
            coverage_distances,
            network_distances,
            source_stop_distances,
            strict=False,
        )
    )
    network_gap = any(
        coverage > STOP_COVERAGE_WARNING_M
        and network_distance > STOP_COVERAGE_WARNING_M
        for coverage, network_distance in zip(
            coverage_distances, network_distances, strict=False
        )
    )
    if not route_links:
        status = "failed"
    elif external_stops:
        status = "partial_external"
    elif trajectory_stop_mismatch:
        status = "trajectory_stop_mismatch"
    elif network_gap:
        status = "network_gap"
    elif coverage_warning_stops:
        status = "route_coverage_gap"
    elif not stop_assignment_ordered:
        status = "stop_order_unresolved"
    elif terminal_extended:
        status = "ordered_stop_extension"
    elif any("trajectory_evidence" in method for method in repair_methods):
        status = "matched_trajectory_evidence_links"
    elif stop_sequence_wrap_count:
        status = "matched_cyclic_reordered"
    elif source == "ordered_official_stops":
        status = "inferred_ordered_stops"
    elif disconnected_gaps:
        status = "matched_with_disconnected_gaps"
    elif topology_connector_occurrences:
        status = "matched_with_topology_connectors"
    elif relaxed_link_occurrences:
        status = "matched_direction_exception"
    else:
        status = "matched"

    raw_source_geometry_length = trajectory_length
    reference_trajectory_length = trajectory_length
    if "ordered_stop_trajectory_evidence" in repair_methods:
        reference_trajectory_length = route_length
    ratio = (
        route_length / reference_trajectory_length
        if reference_trajectory_length and reference_trajectory_length > 0
        else None
    )
    raw_source_ratio = (
        route_length / raw_source_geometry_length
        if raw_source_geometry_length and raw_source_geometry_length > 0
        else None
    )
    route_is_closed = bool(
        route_links
        and network.links[route_links[-1]].to_node == network.links[route_links[0]].from_node
    )
    repeated_share = repeated_length / route_length if route_length > 0 else 0.0
    accepted = bool(
        route_links
        and disconnected_gaps == 0
        and stop_assignment_ordered
        and coverage_warning_stops == 0
        and (ratio is None or ratio <= 1.5)
        and (source_to_matched_p95 is None or source_to_matched_p95 <= 50.0)
        and (matched_to_source_p95 is None or matched_to_source_p95 <= 100.0)
        and (route_is_closed or repeated_share <= 0.05)
        and (not connector_lengths or max(connector_lengths) <= MAX_TOPOLOGY_CONNECTOR_M)
    )
    acceptance_status = "accepted" if accepted else "needs_manual_review"
    if not route_links:
        confidence = "none"
    elif accepted and not relaxed_link_occurrences and not topology_connector_occurrences:
        confidence = "high"
    elif accepted:
        confidence = "medium"
    else:
        confidence = "low"
    qa = {
        "route_key": route_key,
        "mode": mode,
        "route_id": stops[0]["route_id"] if stops else safe_text(trajectory_record.get("route_id")) if trajectory_record else "",
        "route_seq": stops[0]["route_seq"] if stops else safe_text(trajectory_record.get("route_seq")) if trajectory_record else "",
        "company_code": stops[0]["company_code"] if stops else "MTR" if mode in RAIL_MODES else "",
        "route_name": stops[0]["route_name"] if stops else safe_text(trajectory_record.get("line_code")) if trajectory_record else "",
        "trajectory_source": source,
        "source_record_id": safe_text(trajectory_record.get("source_record_id")) if trajectory_record else "",
        "status": status,
        "confidence": confidence,
        "geometry_reversed_to_stop_order": reversed_to_stops,
        "official_stop_count": len(stops),
        "external_or_uncovered_stop_count": external_stops,
        "coverage_warning_stop_count": coverage_warning_stops,
        "sampled_anchor_count": len(anchor_points),
        "snapped_anchor_count": len(snapped),
        "anchor_snap_median_m": round(statistics.median(anchor_distances), 3) if anchor_distances else None,
        "anchor_snap_p95_m": round(percentile(anchor_distances, 95), 3) if anchor_distances else None,
        "stop_snap_median_m": round(statistics.median(assignment_distances), 3) if assignment_distances else None,
        "stop_snap_p95_m": round(percentile(assignment_distances, 95), 3) if assignment_distances else None,
        "stop_snap_max_m": round(max(assignment_distances), 3) if assignment_distances else None,
        "stop_coverage_p95_m": round(percentile(coverage_distances, 95), 3) if coverage_distances else None,
        "stop_coverage_max_m": round(max(coverage_distances), 3) if coverage_distances else None,
        "stop_sequence_wrap_count": stop_sequence_wrap_count,
        "stop_assignment_ordered": stop_assignment_ordered,
        "route_link_count": len(route_links),
        "relaxed_direction_link_occurrences": relaxed_link_occurrences,
        "topology_connector_link_occurrences": topology_connector_occurrences,
        "disconnected_gap_count": disconnected_gaps,
        "trajectory_length_m": round(reference_trajectory_length, 3)
        if reference_trajectory_length is not None
        else None,
        "raw_source_geometry_length_m": round(raw_source_geometry_length, 3)
        if raw_source_geometry_length is not None
        else None,
        "matched_route_length_m": round(route_length, 3),
        "matched_to_trajectory_length_ratio": round(ratio, 4) if ratio is not None else None,
        "matched_to_raw_source_length_ratio": round(raw_source_ratio, 4)
        if raw_source_ratio is not None
        else None,
        "source_to_matched_p95_m": round(source_to_matched_p95, 3) if source_to_matched_p95 is not None else None,
        "matched_to_source_p95_m": round(matched_to_source_p95, 3) if matched_to_source_p95 is not None else None,
        "repeated_link_length_m": round(repeated_length, 3),
        "repeated_link_length_share": round(repeated_share, 6),
        "direction_exception_length_m": round(direction_exception_length, 3),
        "connector_length_m": round(sum(connector_lengths), 3),
        "maximum_connector_length_m": round(max(connector_lengths), 3) if connector_lengths else 0.0,
        "repair_method": "+".join(repair_methods) if repair_methods else "none",
        "acceptance_status": acceptance_status,
        "osm_route_relation_way_count": len(allowed_source_ids) if allowed_source_ids else 0,
        "osm_relation_id": safe_text((relation_metadata or {}).get("osm_relation_id")),
        "osm_relation_name": safe_text((relation_metadata or {}).get("osm_relation_name")),
        "osm_relation_median_distance_m": (relation_metadata or {}).get(
            "osm_relation_median_distance_m"
        ),
        "osm_relation_length_ratio": (relation_metadata or {}).get("osm_relation_length_ratio"),
        "osm_relation_gap_count": (relation_metadata or {}).get("osm_relation_gap_count"),
    }
    return qa, sequence_rows, stop_rows, matched_geometry


def write_matsim_network(
    path: Path,
    networks: Sequence[LinkNetwork],
    used_relaxed_links: set[str],
    used_route_links: set[str],
) -> dict[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    included_links: list[Link] = []
    nodes: dict[str, tuple[float, float]] = {}
    for network in networks:
        for link in network.links.values():
            if not link.legal_direction and link.link_id not in used_relaxed_links:
                continue
            if (
                link.subtype
                in {
                    "trajectory_gap_connector",
                    "relation_gap_connector",
                    "trajectory_evidence_link",
                    "ordered_trajectory_evidence_link",
                }
                and link.link_id not in used_route_links
            ):
                continue
            included_links.append(link)
            nodes[link.from_node] = network.nodes[link.from_node]
            nodes[link.to_node] = network.nodes[link.to_node]
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as handle:
        handle.write('<?xml version="1.0" encoding="utf-8"?>\n')
        handle.write('<!DOCTYPE network SYSTEM "http://www.matsim.org/files/dtd/network_v2.dtd">\n')
        handle.write(f'<network name="Hong Kong transit map-matching base ({TARGET_CRS})">\n')
        handle.write("  <nodes>\n")
        for node_id in sorted(nodes):
            x, y = nodes[node_id]
            handle.write(f'    <node id="{escape(node_id)}" x="{x:.3f}" y="{y:.3f}"/>\n')
        handle.write("  </nodes>\n")
        handle.write('  <links capperiod="01:00:00" effectivecellsize="7.5" effectivelanewidth="3.75">\n')
        for link in sorted(included_links, key=lambda item: item.link_id):
            modes = link.allowed_modes
            handle.write(
                f'    <link id="{escape(link.link_id)}" from="{escape(link.from_node)}" '
                f'to="{escape(link.to_node)}" length="{link.length_m:.3f}" '
                f'freespeed="{link.freespeed_mps:.3f}" capacity="1800" permlanes="1" '
                f'oneway="1" modes="{escape(modes)}"/>\n'
            )
        handle.write("  </links>\n")
        handle.write("</network>\n")
    return {"nodes": len(nodes), "links": len(included_links)}


def write_link_inventory(
    output_dir: Path,
    networks: Sequence[LinkNetwork],
    used_link_ids: set[str],
    used_relaxed_links: set[str],
) -> None:
    rows: list[dict[str, Any]] = []
    geometry_rows: list[dict[str, Any]] = []
    for network in networks:
        for link in network.links.values():
            if link.link_id not in used_link_ids:
                continue
            row = {
                "link_id": link.link_id,
                "from_node": link.from_node,
                "to_node": link.to_node,
                "length_m": round(link.length_m, 3),
                "network_type": link.network_type,
                "network_subtype": link.subtype,
                "source_id": link.source_id,
                "legal_direction": link.legal_direction,
                "direction_relaxed_for_pt": link.link_id in used_relaxed_links,
                "allowed_modes": link.allowed_modes,
                "freespeed_mps": link.freespeed_mps,
            }
            rows.append(row)
            geometry_rows.append({**row, "geometry": link.geometry})
    write_csv(
        output_dir / "network" / "used_link_inventory.csv",
        rows,
        [
            "link_id",
            "from_node",
            "to_node",
            "length_m",
            "network_type",
            "network_subtype",
            "source_id",
            "legal_direction",
            "direction_relaxed_for_pt",
            "allowed_modes",
            "freespeed_mps",
        ],
    )
    if geometry_rows:
        frame = gpd.GeoDataFrame(geometry_rows, geometry="geometry", crs=TARGET_CRS).to_crs(4326)
        frame.to_file(output_dir / "network" / "used_links_wgs84.geojson", driver="GeoJSON")


def write_preview(
    path: Path,
    matched_frame: gpd.GeoDataFrame,
    qa_frame: pd.DataFrame,
    boundary_path: Path | None,
) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(18, 8), dpi=180)
    boundary = None
    if boundary_path and boundary_path.exists():
        boundary = gpd.read_file(boundary_path).to_crs(4326)
    colors = {"bus": "#2864a8", "gmb": "#1f8b5b", "mtr": "#d84a3a", "lrt": "#e39a24"}
    if boundary is not None:
        boundary.boundary.plot(ax=axes[0], color="#333333", linewidth=0.6)
    for mode, group in matched_frame.groupby("mode"):
        group.plot(ax=axes[0], color=colors.get(mode, "#666666"), linewidth=0.35, alpha=0.45, label=mode)
    axes[0].set_title("Hong Kong transit routes on TNM/OSM links")
    axes[0].set_axis_off()
    axes[0].legend(loc="lower left")

    status_counts = qa_frame.groupby(["mode", "status"]).size().unstack(fill_value=0)
    status_counts.plot(kind="bar", stacked=True, ax=axes[1], colormap="tab20c")
    axes[1].set_title("Map-matching status by mode")
    axes[1].set_xlabel("")
    axes[1].set_ylabel("Route directions")
    axes[1].legend(title="status", fontsize=8)
    axes[1].grid(axis="y", alpha=0.2)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(output_dir: Path) -> None:
    manifest_path = output_dir / "SHA256SUMS.txt"
    lines = []
    for path in sorted(output_dir.rglob("*")):
        if path.is_file() and path != manifest_path:
            lines.append(f"{sha256_file(path)}  {path.relative_to(output_dir).as_posix()}")
    manifest_path.write_text("\n".join(lines) + "\n", encoding="ascii")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--road-network", type=Path, default=DEFAULT_ROAD)
    parser.add_argument("--osm-pbf", type=Path, default=DEFAULT_PBF)
    parser.add_argument("--api-root", type=Path, default=DEFAULT_API)
    parser.add_argument("--amap-root", type=Path, default=DEFAULT_AMAP)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--baseline-dir", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--road-sample-spacing-m", type=float, default=100.0)
    parser.add_argument("--rail-sample-spacing-m", type=float, default=120.0)
    parser.add_argument(
        "--boundary",
        type=Path,
        default=PROJECT_ROOT
        / "data"
        / "boundary"
        / "hongkong"
        / "processed"
        / "hong_kong_fixed_link_boundary_wgs84.geojson",
    )
    parser.add_argument("--limit", type=int, default=0, help="QA-only route limit; zero means all routes")
    parser.add_argument("--modes", default="", help="Optional comma-separated mode filter")
    parser.add_argument("--route-key-regex", default="", help="Optional route-key regular expression")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    required = [args.road_network, args.osm_pbf, args.api_root, args.amap_root]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing required inputs: " + "; ".join(missing))
    args.output_dir.mkdir(parents=True, exist_ok=True)

    print("[1/7] Building directed TNM road network", flush=True)
    road_network, road_summary = build_road_network(args.road_network)
    print("[2/7] Extracting active OSM rail links", flush=True)
    rail_network, rail_summary = build_rail_network(args.osm_pbf)
    print("[3/7] Loading CSDI, AMap and ordered-stop inputs", flush=True)
    official_stops, stop_summary = load_official_stops(args.api_root)
    csdi = load_csdi_trajectories(args.api_root)
    amap, amap_stops = load_amap_trajectories(args.amap_root)

    route_records: list[dict[str, Any]] = []
    for route_key, stops in official_stops.items():
        mode = stops[0]["mode"]
        trajectory = csdi.get(route_key) or amap.get(route_key)
        route_records.append(
            {"route_key": route_key, "mode": mode, "stops": stops, "trajectory": trajectory}
        )
    for route_key, trajectory in csdi.items():
        if route_key in official_stops:
            continue
        route_records.append(
            {
                "route_key": route_key,
                "mode": route_key.split("_", 1)[0],
                "stops": [],
                "trajectory": trajectory,
            }
        )
    for route_key, trajectory in amap.items():
        mode = safe_text(trajectory.get("mode"))
        if mode not in RAIL_MODES:
            continue
        trajectory["route_key"] = route_key
        stops = rail_stops_for_target(trajectory, amap_stops)
        route_records.append(
            {"route_key": route_key, "mode": mode, "stops": stops, "trajectory": trajectory}
        )
    route_records.sort(key=lambda item: (item["mode"], item["route_key"]))
    if args.modes:
        selected_modes = {item.strip() for item in args.modes.split(",") if item.strip()}
        route_records = [record for record in route_records if record["mode"] in selected_modes]
    if args.route_key_regex:
        route_pattern = re.compile(args.route_key_regex)
        route_records = [record for record in route_records if route_pattern.search(record["route_key"])]
    if args.limit > 0:
        route_records = route_records[: args.limit]

    print(f"[4/7] Map-matching {len(route_records):,} route directions", flush=True)
    qa_rows: list[dict[str, Any]] = []
    sequence_rows: list[dict[str, Any]] = []
    stop_rows: list[dict[str, Any]] = []
    geometry_rows: list[dict[str, Any]] = []
    for index, record in enumerate(route_records, start=1):
        network = road_network if record["mode"] in ROAD_MODES else rail_network
        spacing = args.road_sample_spacing_m if record["mode"] in ROAD_MODES else args.rail_sample_spacing_m
        relation_way_ids = None
        relation_route_links = None
        relation_metadata: dict[str, Any] = {}
        if record["mode"] in RAIL_MODES and record["trajectory"]:
            line_code = safe_text(record["trajectory"].get("line_code"))
            relation_way_ids = rail_network.route_way_ids.get(line_code)
            start_hint = Point(record["stops"][0]["x"], record["stops"][0]["y"]) if record["stops"] else None
            target_line = ordered_linestring(record["trajectory"].get("geometry"), start_hint=start_hint)
            if target_line is not None:
                target_line, _ = orient_geometry(target_line, record["stops"])
                relation_route_links, relation_metadata = select_osm_relation_route(
                    rail_network, line_code, target_line, record["stops"]
                )
                if relation_metadata.get("_selected_way_ids"):
                    relation_way_ids = set(relation_metadata["_selected_way_ids"])
        qa, route_sequence, route_stops, geometry = match_route(
            route_key=record["route_key"],
            mode=record["mode"],
            network=network,
            stops=record["stops"],
            trajectory_record=record["trajectory"],
            spacing_m=spacing,
            allowed_source_ids=relation_way_ids,
            precomputed_route_links=relation_route_links,
            relation_metadata=relation_metadata,
        )
        qa_rows.append(qa)
        sequence_rows.extend(route_sequence)
        stop_rows.extend(route_stops)
        if geometry is not None and not geometry.is_empty:
            geometry_rows.append(
                {
                    "route_key": record["route_key"],
                    "mode": record["mode"],
                    "trajectory_source": qa["trajectory_source"],
                    "status": qa["status"],
                    "confidence": qa["confidence"],
                    "acceptance_status": qa["acceptance_status"],
                    "repair_method": qa["repair_method"],
                    "geometry": geometry.simplify(8.0, preserve_topology=False),
                }
            )
        if index % 100 == 0 or index == len(route_records):
            print(f"  matched {index:,}/{len(route_records):,}", flush=True)

    print("[5/7] Writing route mappings and MATSim network", flush=True)
    qa_columns = [
        "route_key",
        "mode",
        "route_id",
        "route_seq",
        "company_code",
        "route_name",
        "trajectory_source",
        "source_record_id",
        "status",
        "confidence",
        "geometry_reversed_to_stop_order",
        "official_stop_count",
        "external_or_uncovered_stop_count",
        "coverage_warning_stop_count",
        "sampled_anchor_count",
        "snapped_anchor_count",
        "anchor_snap_median_m",
        "anchor_snap_p95_m",
        "stop_snap_median_m",
        "stop_snap_p95_m",
        "stop_snap_max_m",
        "stop_coverage_p95_m",
        "stop_coverage_max_m",
        "stop_sequence_wrap_count",
        "stop_assignment_ordered",
        "route_link_count",
        "relaxed_direction_link_occurrences",
        "topology_connector_link_occurrences",
        "disconnected_gap_count",
        "trajectory_length_m",
        "raw_source_geometry_length_m",
        "matched_route_length_m",
        "matched_to_trajectory_length_ratio",
        "matched_to_raw_source_length_ratio",
        "source_to_matched_p95_m",
        "matched_to_source_p95_m",
        "repeated_link_length_m",
        "repeated_link_length_share",
        "direction_exception_length_m",
        "connector_length_m",
        "maximum_connector_length_m",
        "repair_method",
        "acceptance_status",
        "osm_route_relation_way_count",
        "osm_relation_id",
        "osm_relation_name",
        "osm_relation_median_distance_m",
        "osm_relation_length_ratio",
        "osm_relation_gap_count",
    ]
    write_csv(args.output_dir / "route_map_matching_qa.csv", qa_rows, qa_columns)
    write_csv(
        args.output_dir / "route_link_sequences.csv",
        sequence_rows,
        [
            "route_key",
            "mode",
            "sequence",
            "link_id",
            "from_node",
            "to_node",
            "length_m",
            "network_type",
            "network_subtype",
            "legal_direction",
        ],
    )
    write_csv(
        args.output_dir / "stop_link_snaps.csv",
        stop_rows,
        [
            "route_key",
            "mode",
            "route_id",
            "route_seq",
            "company_code",
            "route_name",
            "stop_seq",
            "stop_id",
            "stop_name_en",
            "stop_name_zh",
            "lon",
            "lat",
            "x",
            "y",
            "link_id",
            "route_link_index",
            "route_link_index_unwrapped",
            "coverage_distance_m",
            "assignment_distance_m",
            "nearest_network_link_id",
            "nearest_network_distance_m",
            "trajectory_distance_m",
            "snap_distance_m",
            "external_or_uncovered",
        ],
    )
    matched_frame = gpd.GeoDataFrame(geometry_rows, geometry="geometry", crs=TARGET_CRS).to_crs(4326)
    matched_frame.to_file(args.output_dir / "matched_route_geometries_wgs84.geojson", driver="GeoJSON")
    inferred = matched_frame.loc[matched_frame["trajectory_source"] == "ordered_official_stops"].copy()
    inferred.to_file(args.output_dir / "inferred_ordered_stop_routes_wgs84.geojson", driver="GeoJSON")

    used_link_ids = {row["link_id"] for row in sequence_rows}
    used_relaxed = {
        link_id
        for link_id in used_link_ids
        if link_id in road_network.links and not road_network.links[link_id].legal_direction
    }
    matsim_counts = write_matsim_network(
        args.output_dir / "network" / "hong_kong_transit_base_network.xml.gz",
        [road_network, rail_network],
        used_relaxed,
        used_link_ids,
    )
    write_link_inventory(args.output_dir, [road_network, rail_network], used_link_ids, used_relaxed)

    print("[6/7] Writing QA summary and preview", flush=True)
    qa_frame = pd.DataFrame(qa_rows)
    accepted_frame = qa_frame.loc[qa_frame["acceptance_status"] == "accepted"].copy()
    review_frame = qa_frame.loc[qa_frame["acceptance_status"] != "accepted"].copy()
    accepted_frame.to_csv(args.output_dir / "accepted_routes.csv", index=False, encoding="utf-8-sig")
    review_frame.to_csv(
        args.output_dir / "needs_manual_review.csv", index=False, encoding="utf-8-sig"
    )

    comparison_path = args.output_dir / "map_matching_v1_v2_comparison.csv"
    baseline_qa_path = args.baseline_dir / "route_map_matching_qa.csv"
    comparison_frame = pd.DataFrame()
    if baseline_qa_path.exists():
        baseline = pd.read_csv(baseline_qa_path, low_memory=False)
        baseline_columns = [
            "route_key",
            "status",
            "confidence",
            "matched_route_length_m",
            "matched_to_trajectory_length_ratio",
            "external_or_uncovered_stop_count",
            "relaxed_direction_link_occurrences",
            "topology_connector_link_occurrences",
        ]
        baseline = baseline[[column for column in baseline_columns if column in baseline.columns]]
        baseline = baseline.rename(
            columns={column: f"v1_{column}" for column in baseline.columns if column != "route_key"}
        )
        v2_columns = [
            "route_key",
            "mode",
            "route_name",
            "route_seq",
            "status",
            "acceptance_status",
            "repair_method",
            "matched_route_length_m",
            "matched_to_trajectory_length_ratio",
            "matched_to_raw_source_length_ratio",
            "coverage_warning_stop_count",
            "external_or_uncovered_stop_count",
            "source_to_matched_p95_m",
            "matched_to_source_p95_m",
            "repeated_link_length_m",
            "direction_exception_length_m",
            "connector_length_m",
        ]
        comparison_frame = baseline.merge(
            qa_frame[v2_columns], on="route_key", how="outer", validate="one_to_one"
        )
        comparison_frame["v1_high_length_ratio"] = (
            comparison_frame["v1_matched_to_trajectory_length_ratio"] > 1.5
        )
        comparison_frame["v2_high_length_ratio"] = (
            comparison_frame["matched_to_trajectory_length_ratio"] > 1.5
        )
        comparison_frame["v1_partial_external"] = comparison_frame["v1_status"].eq(
            "partial_external"
        )
        comparison_frame["v2_coverage_warning"] = (
            comparison_frame["coverage_warning_stop_count"].fillna(0) > 0
        )
        comparison_frame["length_ratio_change"] = (
            comparison_frame["matched_to_trajectory_length_ratio"]
            - comparison_frame["v1_matched_to_trajectory_length_ratio"]
        )
        comparison_frame["raw_source_length_ratio_change"] = (
            comparison_frame["matched_to_raw_source_length_ratio"]
            - comparison_frame["v1_matched_to_trajectory_length_ratio"]
        )
        comparison_frame.to_csv(comparison_path, index=False, encoding="utf-8-sig")
    continuity_errors: list[dict[str, Any]] = []
    prior_by_route: dict[str, dict[str, Any]] = {}
    for row in sequence_rows:
        prior = prior_by_route.get(row["route_key"])
        if prior is not None and prior["to_node"] != row["from_node"]:
            continuity_errors.append(
                {
                    "route_key": row["route_key"],
                    "previous_sequence": prior["sequence"],
                    "previous_to_node": prior["to_node"],
                    "current_sequence": row["sequence"],
                    "current_from_node": row["from_node"],
                }
            )
        prior_by_route[row["route_key"]] = row
    write_csv(
        args.output_dir / "route_link_continuity_errors.csv",
        continuity_errors,
        [
            "route_key",
            "previous_sequence",
            "previous_to_node",
            "current_sequence",
            "current_from_node",
        ],
    )
    status_counts = qa_frame.groupby(["mode", "status"]).size().to_dict()
    source_counts = qa_frame.groupby(["mode", "trajectory_source"]).size().to_dict()
    summary = {
        "project_root": str(PROJECT_ROOT),
        "output_dir": str(args.output_dir),
        "crs": TARGET_CRS,
        "road_network": road_summary,
        "rail_network": rail_summary,
        "official_stops": stop_summary,
        "inputs": {
            "csdi_trajectories": len(csdi),
            "amap_spatially_validated_trajectories": len(amap),
            "route_records_processed": len(route_records),
        },
        "outputs": {
            "successful_route_directions": int((qa_frame["status"] != "failed").sum()),
            "failed_route_directions": int((qa_frame["status"] == "failed").sum()),
            "route_link_sequence_rows": len(sequence_rows),
            "stop_link_snap_rows": len(stop_rows),
            "used_unique_links": len(used_link_ids),
            "used_relaxed_direction_links": len(used_relaxed),
            "route_link_continuity_errors": len(continuity_errors),
            "accepted_route_directions": len(accepted_frame),
            "manual_review_route_directions": len(review_frame),
            "matsim_network": matsim_counts,
        },
        "status_counts": {f"{mode}|{status}": int(count) for (mode, status), count in status_counts.items()},
        "trajectory_source_counts": {
            f"{mode}|{source}": int(count) for (mode, source), count in source_counts.items()
        },
        "qa": {
            "stop_snap_p95_m_median": float(qa_frame["stop_snap_p95_m"].dropna().median()),
            "anchor_snap_p95_m_median": float(qa_frame["anchor_snap_p95_m"].dropna().median()),
            "routes_using_direction_relaxation": int(
                (qa_frame["relaxed_direction_link_occurrences"] > 0).sum()
            ),
            "routes_using_topology_connectors": int(
                (qa_frame["topology_connector_link_occurrences"] > 0).sum()
            ),
            "routes_with_disconnected_gaps": int((qa_frame["disconnected_gap_count"] > 0).sum()),
            "partial_external_routes": int((qa_frame["status"] == "partial_external").sum()),
            "coverage_warning_routes": int((qa_frame["coverage_warning_stop_count"] > 0).sum()),
            "road_routes_over_length_ratio_1_5": int(
                (
                    qa_frame["mode"].isin(ROAD_MODES)
                    & qa_frame["matched_to_trajectory_length_ratio"].gt(1.5)
                ).sum()
            ),
            "accepted_road_routes_over_length_ratio_1_5": int(
                (
                    qa_frame["mode"].isin(ROAD_MODES)
                    & qa_frame["matched_to_trajectory_length_ratio"].gt(1.5)
                    & qa_frame["acceptance_status"].eq("accepted")
                ).sum()
            ),
            "routes_repaired_by_candidate_dp": int(
                qa_frame["repair_method"].str.contains("candidate_sequence_dp").sum()
            ),
            "routes_repaired_by_cyclic_rotation": int(
                qa_frame["repair_method"].str.contains("cyclic_route_rotation").sum()
            ),
            "routes_with_ordered_stop_extension": int(
                qa_frame["repair_method"].str.contains("ordered_stop_extension").sum()
            ),
            "v1_v2_comparison_rows": len(comparison_frame),
        },
        "method_notes": [
            "CSDI is preferred over AMap for bus and GMB route geometry.",
            "AMap trajectories are used only after the existing spatial QA acceptance step.",
            "Routes without reliable geometry use ordered official stops and network shortest paths.",
            "Road anomaly repairs use candidate-sequence dynamic programming inside 300 m and 800 m trajectory corridors.",
            "TNM TRAVEL_DIR=1 is bidirectional and TRAVEL_DIR=3 follows the digitised direction, per the official data dictionary.",
            "Direction exceptions require trajectory and ordered-stop evidence; topology connectors are capped at 300 m for acceptance.",
            "Stop coverage distance is independent from order-consistent stop-to-link assignment distance.",
            "Cross-border portions outside the Hong Kong TNM extent are not fabricated.",
        ],
    }
    (args.output_dir / "map_matching_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_preview(
        args.output_dir / "map_matching_preview.png",
        matched_frame,
        qa_frame,
        args.boundary,
    )

    print("[7/7] Writing SHA256 manifest", flush=True)
    write_manifest(args.output_dir)
    print(json.dumps(summary["outputs"], ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
