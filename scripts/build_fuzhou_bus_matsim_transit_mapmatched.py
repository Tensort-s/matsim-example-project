#!/usr/bin/env python3
"""Build map-matched Fuzhou bus MATSim transit files.

This script maps AMap bus line trajectories to the existing MATSim road
network, marks the used road links as `pt`, and writes a bus transit schedule
and vehicles file. It intentionally does not regenerate the OSM road network.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import heapq
import json
import math
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import numpy as np
from pyproj import Transformer
from scipy.spatial import cKDTree
from shapely.geometry import Point, shape
from shapely.ops import transform as shapely_transform, unary_union


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "data" / "transit" / "fuzhou_bus_matsim_network_20260709"
DEFAULT_NETWORK = ROOT / "data" / "matsim_routes" / "fuzhou_city_23_greenspace_grid_multi_activity" / "network.xml.gz"
DEFAULT_BUS_DIR = ROOT / "data" / "transit" / "fuzhou_bus_amap_stop_line_final_20260709" / "bus_lines"
DEFAULT_UNIFIED_BUS_DIR = ROOT / "data" / "transit" / "fuzhou_transit_coordinates_unified_20260709" / "bus"
DEFAULT_TIMETABLE_DIR = ROOT / "data" / "transit" / "fuzhou_bus_timetable_final_20260709" / "tables"
DEFAULT_BOUNDARY = ROOT / "data" / "osm" / "fuzhou_city_23" / "fuzhou_city_23_boundary.geojson"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def xml_attr(value: Any) -> str:
    return escape(str(value), {'"': "&quot;"})


def normalize(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", "", value).replace("（", "(").replace("）", ")")


def route_base_name(line_name: str) -> str:
    name = normalize(line_name)
    return name.split("(", 1)[0]


def safe_float(value: Any, default: float = 0.0) -> float:
    if value in ("", None):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    if value in ("", None):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def parse_time_to_seconds(value: str | None) -> int | None:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    if ":" in value:
        parts = [int(float(p)) for p in value.split(":")]
        if len(parts) == 2:
            return parts[0] * 3600 + parts[1] * 60
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if value.isdigit():
        if len(value) <= 2:
            return int(value) * 3600
        hh = int(value[:-2])
        mm = int(value[-2:])
        return hh * 3600 + mm * 60
    return None


def format_hms(seconds: float) -> str:
    seconds_i = int(round(seconds))
    hh = seconds_i // 3600
    mm = (seconds_i % 3600) // 60
    ss = seconds_i % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}"


def point_segment_distance(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    vx = bx - ax
    vy = by - ay
    wx = px - ax
    wy = py - ay
    c2 = vx * vx + vy * vy
    if c2 <= 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, (wx * vx + wy * vy) / c2))
    qx = ax + t * vx
    qy = ay + t * vy
    return math.hypot(px - qx, py - qy)


class RoadNetwork:
    def __init__(self, path: Path, snap_k: int = 20, allow_dynamic_gap_connectors: bool = True):
        self.path = path
        self.allow_dynamic_gap_connectors = allow_dynamic_gap_connectors
        with gzip.open(path, "rt", encoding="utf-8") as f:
            self.root = ET.parse(f).getroot()
        self.nodes: dict[str, tuple[float, float]] = {}
        self.links: dict[str, dict[str, Any]] = {}
        self.link_order: list[str] = []
        self.adj: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
        self._load()
        self.snap_k = min(snap_k, len(self.link_order))
        midpoints = []
        for link_id in self.link_order:
            link = self.links[link_id]
            ax, ay = self.nodes[link["from"]]
            bx, by = self.nodes[link["to"]]
            midpoints.append(((ax + bx) / 2.0, (ay + by) / 2.0))
        self.kdtree = cKDTree(np.array(midpoints))
        self.shortest_cache: dict[tuple[str, str], list[str] | None] = {}
        self.dynamic_gap_connectors: dict[tuple[str, str], str] = {}
        self.dynamic_gap_connector_links: list[dict[str, Any]] = []

    def _load(self) -> None:
        nodes_el = self.root.find("nodes")
        links_el = self.root.find("links")
        if nodes_el is None or links_el is None:
            raise ValueError(f"Invalid MATSim network: {self.path}")
        for node in nodes_el.findall("node"):
            self.nodes[node.attrib["id"]] = (safe_float(node.attrib["x"]), safe_float(node.attrib["y"]))
        for link in links_el.findall("link"):
            attrib = dict(link.attrib)
            link_id = attrib["id"]
            from_node = attrib["from"]
            to_node = attrib["to"]
            length = max(safe_float(attrib.get("length")), 1.0)
            freespeed = max(safe_float(attrib.get("freespeed")), 1.0)
            self.links[link_id] = {
                "id": link_id,
                "from": from_node,
                "to": to_node,
                "length": length,
                "freespeed": freespeed,
                "cost": length / freespeed,
                "attrib": attrib,
            }
            self.link_order.append(link_id)
            self.adj[from_node].append((to_node, link_id, length / freespeed))

    def snap_point(self, x: float, y: float, candidate_links: list[str] | None = None) -> tuple[str, float]:
        if candidate_links:
            best_id = ""
            best_dist = float("inf")
            for link_id in candidate_links:
                link = self.links[link_id]
                ax, ay = self.nodes[link["from"]]
                bx, by = self.nodes[link["to"]]
                dist = point_segment_distance(x, y, ax, ay, bx, by)
                if dist < best_dist:
                    best_id = link_id
                    best_dist = dist
            return best_id, best_dist
        _, idxs = self.kdtree.query([x, y], k=self.snap_k)
        if self.snap_k == 1:
            idxs = [int(idxs)]
        best_id = ""
        best_dist = float("inf")
        for idx in idxs:
            link_id = self.link_order[int(idx)]
            link = self.links[link_id]
            ax, ay = self.nodes[link["from"]]
            bx, by = self.nodes[link["to"]]
            dist = point_segment_distance(x, y, ax, ay, bx, by)
            if dist < best_dist:
                best_id = link_id
                best_dist = dist
        return best_id, best_dist

    def shortest_path_links(self, start_node: str, end_node: str) -> list[str] | None:
        if start_node == end_node:
            return []
        key = (start_node, end_node)
        if key in self.shortest_cache:
            return self.shortest_cache[key]
        heap: list[tuple[float, str]] = [(0.0, start_node)]
        dist: dict[str, float] = {start_node: 0.0}
        prev: dict[str, tuple[str, str]] = {}
        visited: set[str] = set()
        while heap:
            cost, node = heapq.heappop(heap)
            if node in visited:
                continue
            visited.add(node)
            if node == end_node:
                break
            for next_node, link_id, weight in self.adj.get(node, []):
                next_cost = cost + weight
                if next_cost < dist.get(next_node, float("inf")):
                    dist[next_node] = next_cost
                    prev[next_node] = (node, link_id)
                    heapq.heappush(heap, (next_cost, next_node))
        if end_node not in dist:
            self.shortest_cache[key] = None
            return None
        path: list[str] = []
        node = end_node
        while node != start_node:
            prior, link_id = prev[node]
            path.append(link_id)
            node = prior
        path.reverse()
        self.shortest_cache[key] = path
        return path

    def create_gap_connector_link(self, from_node: str, to_node: str) -> str:
        key = (from_node, to_node)
        existing = self.dynamic_gap_connectors.get(key)
        if existing:
            return existing
        ax, ay = self.nodes[from_node]
        bx, by = self.nodes[to_node]
        length = max(math.hypot(bx - ax, by - ay), 1.0)
        link_id = f"dynamic_bus_gap_connector_{len(self.dynamic_gap_connectors) + 1:06d}"
        link = {
            "id": link_id,
            "from": from_node,
            "to": to_node,
            "length": length,
            "freespeed": 13.89,
            "cost": length / 13.89,
            "attrib": {
                "id": link_id,
                "from": from_node,
                "to": to_node,
                "length": f"{length:.3f}",
                "freespeed": "13.8900",
                "capacity": "900.000",
                "permlanes": "1.00",
                "modes": "car,pt",
            },
            "dynamic_gap_connector": True,
        }
        self.links[link_id] = link
        self.adj[from_node].append((to_node, link_id, link["cost"]))
        self.dynamic_gap_connectors[key] = link_id
        self.dynamic_gap_connector_links.append(link)
        return link_id

    def connect_link_sequence(self, snapped_links: list[str]) -> tuple[list[str], int]:
        route: list[str] = []
        gaps = 0
        for link_id in snapped_links:
            if not link_id:
                continue
            if not route:
                route.append(link_id)
                continue
            if route[-1] == link_id:
                continue
            prev = self.links[route[-1]]
            curr = self.links[link_id]
            if prev["to"] == curr["from"]:
                route.append(link_id)
                continue
            bridge = self.shortest_path_links(prev["to"], curr["from"])
            if bridge is None:
                gaps += 1
                if self.allow_dynamic_gap_connectors:
                    connector = self.create_gap_connector_link(prev["to"], curr["from"])
                    if not route or route[-1] != connector:
                        route.append(connector)
                route.append(link_id)
            else:
                for b in bridge:
                    if not route or route[-1] != b:
                        route.append(b)
                if not route or route[-1] != link_id:
                    route.append(link_id)
        return route, gaps

    def write_with_pt_modes(self, path: Path, pt_link_ids: set[str]) -> None:
        links_el = self.root.find("links")
        existing_xml_link_ids = {link_el.attrib["id"] for link_el in links_el.findall("link")}  # type: ignore[union-attr]
        for link in self.dynamic_gap_connector_links:
            if link["id"] in existing_xml_link_ids:
                continue
            ET.SubElement(links_el, "link", link["attrib"])  # type: ignore[arg-type,union-attr]
            existing_xml_link_ids.add(link["id"])
        for link_el in self.root.find("links").findall("link"):  # type: ignore[union-attr]
            link_id = link_el.attrib["id"]
            modes = set(filter(None, (link_el.attrib.get("modes") or "car").split(",")))
            if link_id in pt_link_ids:
                modes.add("pt")
            link_el.attrib["modes"] = ",".join(sorted(modes))
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8", newline="\n") as f:
            f.write('<?xml version="1.0" encoding="utf-8"?>\n')
            f.write('<!DOCTYPE network SYSTEM "http://www.matsim.org/files/dtd/network_v1.dtd">\n\n')
            f.write(ET.tostring(self.root, encoding="unicode"))
            f.write("\n")


def load_trajectories(path: Path) -> dict[str, list[tuple[float, float]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, list[tuple[float, float]]] = {}
    for feature in data.get("features", []):
        props = feature.get("properties") or {}
        line_id = str(props.get("line_id") or "")
        coords = feature.get("geometry", {}).get("coordinates") or []
        if line_id and coords:
            result[line_id] = [(safe_float(x), safe_float(y)) for x, y in coords]
    return result


def load_boundary_buffer(boundary_path: Path | None, buffer_m: float):
    if not boundary_path:
        return None
    if not boundary_path.exists():
        raise FileNotFoundError(boundary_path)
    data = json.loads(boundary_path.read_text(encoding="utf-8"))
    geometries = [shape(feature["geometry"]) for feature in data.get("features", []) if feature.get("geometry")]
    if not geometries and data.get("type") in {"Polygon", "MultiPolygon"}:
        geometries = [shape(data)]
    if not geometries:
        raise ValueError(f"No polygon geometry found in {boundary_path}")
    geom_wgs84 = unary_union(geometries)
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32650", always_xy=True)
    geom_epsg32650 = shapely_transform(transformer.transform, geom_wgs84)
    return geom_epsg32650.buffer(buffer_m)


def sample_coords(coords: list[tuple[float, float]], min_spacing_m: float) -> list[tuple[float, float]]:
    if len(coords) <= 2:
        return coords
    sampled = [coords[0]]
    last = coords[0]
    for point in coords[1:-1]:
        if math.hypot(point[0] - last[0], point[1] - last[1]) >= min_spacing_m:
            sampled.append(point)
            last = point
    if sampled[-1] != coords[-1]:
        sampled.append(coords[-1])
    return sampled


def load_bus_lines(stops_path: Path, boundary_buffer_geom: Any | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], int]:
    by_line: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in read_csv(stops_path):
        by_line[row["line_id"]].append(row)
    lines: list[dict[str, Any]] = []
    dropped_stops: list[dict[str, Any]] = []
    dropped_lines: list[dict[str, Any]] = []
    for line_id, stops in sorted(by_line.items()):
        stops_sorted = sorted(stops, key=lambda row: safe_int(row.get("stop_sequence")))
        kept_stops: list[dict[str, str]] = []
        for stop in stops_sorted:
            x = safe_float(stop.get("x_epsg32650"))
            y = safe_float(stop.get("y_epsg32650"))
            if boundary_buffer_geom is not None and not boundary_buffer_geom.covers(Point(x, y)):
                dropped_stops.append(
                    {
                        "line_id": line_id,
                        "line_name": stop.get("line_name", ""),
                        "stop_sequence": stop.get("stop_sequence", ""),
                        "station_id": stop.get("station_id", ""),
                        "station_name": stop.get("station_name", ""),
                        "x_epsg32650": x,
                        "y_epsg32650": y,
                        "drop_reason": "outside_city_boundary_buffer",
                    }
                )
            else:
                kept_stops.append(stop)
        stops_sorted = kept_stops
        if len(stops_sorted) < 2:
            if kept_stops:
                first_name = kept_stops[0].get("line_name", "")
            elif stops:
                first_name = stops[0].get("line_name", "")
            else:
                first_name = ""
            dropped_lines.append(
                {
                    "line_id": line_id,
                    "line_name": first_name,
                    "original_stop_count": len(stops),
                    "kept_stop_count": len(stops_sorted),
                    "drop_reason": "fewer_than_two_stops_inside_city_boundary_buffer",
                }
            )
            continue
        first = stops_sorted[0]
        last = stops_sorted[-1]
        lines.append(
            {
                "line_id": line_id,
                "line_name": first["line_name"],
                "start_stop": first["station_name"],
                "end_stop": last["station_name"],
                "stops": stops_sorted,
                "original_stop_count": len(stops),
                "kept_stop_count": len(stops_sorted),
            }
        )
    return lines, dropped_stops, dropped_lines, len(by_line)


def build_timetable_index(rules_path: Path) -> tuple[dict[str, list[dict[str, str]]], dict[tuple[str, str], list[dict[str, str]]]]:
    by_name: dict[str, list[dict[str, str]]] = defaultdict(list)
    by_direction: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in read_csv(rules_path):
        target_name = row.get("target_line_name") or ""
        if target_name:
            by_name[normalize(target_name)].append(row)
        direction_key = (normalize(row.get("direction_from")), normalize(row.get("direction_to")))
        if direction_key != ("", ""):
            by_direction[direction_key].append(row)
    return by_name, by_direction


def generate_departures_from_rules(rules: list[dict[str, str]]) -> tuple[list[int], str]:
    departures: set[int] = set()
    source_parts: set[str] = set()
    for row in rules:
        source_parts.add(row.get("rule_source") or row.get("merge_source") or "timetable_rule")
        csv_value = row.get("departures_csv") or ""
        if csv_value:
            for item in csv_value.split(";"):
                t = parse_time_to_seconds(item)
                if t is not None:
                    departures.add(t)
            continue
        start = parse_time_to_seconds(row.get("period_start"))
        end = parse_time_to_seconds(row.get("period_end"))
        headway = safe_float(row.get("headway_mode_minutes")) or safe_float(row.get("headway_median_minutes")) or safe_float(row.get("headway_mean_minutes"))
        if start is None or end is None or headway <= 0:
            continue
        t = start
        step = int(round(headway * 60))
        while t < end:
            departures.add(t)
            t += step
    return sorted(departures), "+".join(sorted(source_parts))


def fallback_departures(line_name: str) -> tuple[list[int], str]:
    base = route_base_name(line_name)
    if "夜" in base or "夜间" in base:
        start, end, headway = 20 * 3600, 24 * 3600, 20 * 60
    elif any(token in base for token in ["专线", "通勤", "接驳"]):
        start, end, headway = 6 * 3600, 20 * 3600, 20 * 60
    else:
        start, end, headway = 6 * 3600, 23 * 3600, 10 * 60
    return list(range(start, end, headway)), "default_estimated_headway"


def departures_for_line(
    line: dict[str, Any],
    by_name: dict[str, list[dict[str, str]]],
    by_direction: dict[tuple[str, str], list[dict[str, str]]],
) -> tuple[list[int], str, str]:
    exact = by_name.get(normalize(line["line_name"]), [])
    if exact:
        departures, source = generate_departures_from_rules(exact)
        if departures:
            return departures, "timetable_exact_line_name", source
    direction = by_direction.get((normalize(line["start_stop"]), normalize(line["end_stop"])), [])
    if direction:
        departures, source = generate_departures_from_rules(direction)
        if departures:
            return departures, "timetable_direction_match", source
    departures, source = fallback_departures(line["line_name"])
    return departures, "fallback_default", source


def build_route_from_trajectory(
    network: RoadNetwork,
    line: dict[str, Any],
    trajectories: dict[str, list[tuple[float, float]]],
    min_spacing_m: float,
    boundary_buffer_geom: Any | None = None,
) -> tuple[list[str], str, int, int]:
    stop_links = [
        network.snap_point(safe_float(stop["x_epsg32650"]), safe_float(stop["y_epsg32650"]))[0]
        for stop in line["stops"]
    ]
    coords = trajectories.get(line["line_id"])
    if coords:
        if boundary_buffer_geom is not None:
            coords = [(x, y) for x, y in coords if boundary_buffer_geom.covers(Point(x, y))]
        first_stop = line["stops"][0]
        last_stop = line["stops"][-1]
        endpoints = [
            (safe_float(first_stop["x_epsg32650"]), safe_float(first_stop["y_epsg32650"])),
            (safe_float(last_stop["x_epsg32650"]), safe_float(last_stop["y_epsg32650"])),
        ]
        sampled = sample_coords(coords, min_spacing_m)
        anchored: list[tuple[float, float]] = []
        for point in [endpoints[0], *sampled, endpoints[1]]:
            if not anchored or math.hypot(point[0] - anchored[-1][0], point[1] - anchored[-1][1]) > 10.0:
                anchored.append(point)
        sampled = anchored
        snapped = [network.snap_point(x, y)[0] for x, y in sampled]
        deduped = [snapped[0]] if snapped else []
        for link_id in snapped[1:]:
            if link_id != deduped[-1]:
                deduped.append(link_id)
        route, gaps = network.connect_link_sequence(deduped)
        if route and gaps == 0:
            return route, "trajectory_map_matching", len(sampled), gaps
        # A geometry-nearest trajectory link can be topologically unreachable
        # when synthetic one-way bus links are present. In that case, prefer a
        # station-constrained shortest-path route if it is more continuous.
        stop_route, stop_gaps = network.connect_link_sequence(stop_links)
        if stop_route and stop_gaps <= gaps:
            return stop_route, "stop_to_stop_fallback_after_trajectory_gaps", len(stop_links), stop_gaps
        if route:
            return route, "trajectory_map_matching_with_gaps", len(sampled), gaps
    route, gaps = network.connect_link_sequence(stop_links)
    return route, "stop_to_stop_fallback", len(stop_links), gaps


def stop_facilities_for_route(
    network: RoadNetwork,
    line: dict[str, Any],
    route_links: list[str],
) -> tuple[list[dict[str, Any]], float, float, int]:
    stop_rows: list[dict[str, Any]] = []
    distances: list[float] = []
    route_index_by_link: dict[str, list[int]] = defaultdict(list)
    for idx, link_id in enumerate(route_links):
        route_index_by_link[link_id].append(idx)
    previous_index = 0
    unmatched = 0
    for stop in line["stops"]:
        x = safe_float(stop["x_epsg32650"])
        y = safe_float(stop["y_epsg32650"])
        link_id, dist = network.snap_point(x, y, candidate_links=route_links)
        candidate_indices = route_index_by_link.get(link_id, [])
        after = [idx for idx in candidate_indices if idx >= previous_index]
        if after:
            route_index = after[0]
        elif candidate_indices:
            route_index = candidate_indices[-1]
        else:
            route_index = previous_index
            unmatched += 1
        previous_index = max(previous_index, route_index)
        distances.append(dist)
        facility_id = f"bus_stop_{line['line_id']}_{safe_int(stop['stop_sequence']):03d}_{stop['station_id']}"
        stop_rows.append(
            {
                "facility_id": facility_id,
                "line_id": line["line_id"],
                "line_name": line["line_name"],
                "stop_sequence": safe_int(stop["stop_sequence"]),
                "station_id": stop["station_id"],
                "station_name": stop["station_name"],
                "x": x,
                "y": y,
                "link_id": link_id,
                "route_index": route_index,
                "snap_distance_m": dist,
            }
        )
    median = float(np.median(distances)) if distances else 0.0
    p95 = float(np.percentile(distances, 95)) if distances else 0.0
    return stop_rows, median, p95, unmatched


def route_offsets(network: RoadNetwork, route_links: list[str], stops: list[dict[str, Any]], dwell_s: float) -> list[dict[str, Any]]:
    cumulative_after: list[float] = []
    total = 0.0
    for link_id in route_links:
        link = network.links[link_id]
        total += link["length"] / link["freespeed"]
        cumulative_after.append(total)
    result: list[dict[str, Any]] = []
    last_departure = 0.0
    for idx, stop in enumerate(stops):
        route_idx = min(max(int(stop["route_index"]), 0), len(cumulative_after) - 1)
        if idx == 0:
            arrival = 0.0
        else:
            arrival = max(cumulative_after[route_idx], last_departure + 1.0)
        departure = arrival if idx == len(stops) - 1 else arrival + dwell_s
        last_departure = departure
        item = dict(stop)
        item["arrival_offset_s"] = arrival
        item["departure_offset_s"] = departure
        result.append(item)
    return result


def write_schedule(path: Path, route_results: list[dict[str, Any]], network: RoadNetwork) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n')
        f.write('<!DOCTYPE transitSchedule SYSTEM "http://www.matsim.org/files/dtd/transitSchedule_v2.dtd">\n\n')
        f.write("<transitSchedule>\n")
        f.write("  <transitStops>\n")
        for result in route_results:
            for stop in result["stop_offsets"]:
                f.write(
                    f'    <stopFacility id="{xml_attr(stop["facility_id"])}" '
                    f'x="{stop["x"]:.3f}" y="{stop["y"]:.3f}" '
                    f'linkRefId="{xml_attr(stop["link_id"])}" '
                    f'name="{xml_attr(stop["station_name"])}" isBlocking="false" />\n'
                )
        f.write("  </transitStops>\n")
        for result in route_results:
            line_id = result["line_id"]
            f.write(f'  <transitLine id="bus_line_{xml_attr(line_id)}">\n')
            f.write(f'    <transitRoute id="bus_route_{xml_attr(line_id)}">\n')
            f.write("      <transportMode>pt</transportMode>\n")
            f.write("      <routeProfile>\n")
            for stop in result["stop_offsets"]:
                f.write(
                    f'        <stop refId="{xml_attr(stop["facility_id"])}" '
                    f'arrivalOffset="{format_hms(stop["arrival_offset_s"])}" '
                    f'departureOffset="{format_hms(stop["departure_offset_s"])}" />\n'
                )
            f.write("      </routeProfile>\n")
            f.write("      <route>\n")
            for link_id in result["route_links"]:
                f.write(f'        <link refId="{xml_attr(link_id)}" />\n')
            f.write("      </route>\n")
            f.write("      <departures>\n")
            for idx, dep_s in enumerate(result["departures"], start=1):
                dep_id = f"bus_dep_{line_id}_{idx:04d}"
                veh_id = f"bus_vehicle_{line_id}_{idx:04d}"
                f.write(
                    f'        <departure id="{xml_attr(dep_id)}" '
                    f'departureTime="{format_hms(dep_s)}" vehicleRefId="{xml_attr(veh_id)}" />\n'
                )
            f.write("      </departures>\n")
            f.write("    </transitRoute>\n")
            f.write("  </transitLine>\n")
        f.write("</transitSchedule>\n")


def write_vehicles(path: Path, route_results: list[dict[str, Any]], capacity: int) -> None:
    seats = int(round(capacity * 0.35))
    standing = capacity - seats
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n')
        f.write('<!DOCTYPE vehicleDefinitions SYSTEM "http://www.matsim.org/files/dtd/vehicleDefinitions_v1.dtd">\n\n')
        f.write("<vehicleDefinitions>\n")
        f.write('  <vehicleType id="bus_standard_capacity_80">\n')
        f.write(f'    <capacity seats="{seats}" standingRoomInPersons="{standing}" />\n')
        f.write('    <length meter="12.0" />\n')
        f.write('    <width meter="2.5" />\n')
        f.write('    <accessTime secondsPerPerson="0.5" />\n')
        f.write('    <egressTime secondsPerPerson="0.5" />\n')
        f.write('    <doorOperation mode="parallel" />\n')
        f.write('    <passengerCarEquivalents pce="2.5" />\n')
        f.write("  </vehicleType>\n")
        for result in route_results:
            line_id = result["line_id"]
            for idx, _ in enumerate(result["departures"], start=1):
                f.write(f'  <vehicle id="bus_vehicle_{xml_attr(line_id)}_{idx:04d}" type="bus_standard_capacity_80" />\n')
        f.write("</vehicleDefinitions>\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", type=Path, default=DEFAULT_NETWORK)
    parser.add_argument("--stops-by-line", type=Path, default=DEFAULT_UNIFIED_BUS_DIR / "bus_stops_by_line_unified.csv")
    parser.add_argument("--trajectories", type=Path, default=DEFAULT_UNIFIED_BUS_DIR / "bus_line_trajectories_epsg32650.geojson")
    parser.add_argument("--timetable-rules", type=Path, default=DEFAULT_TIMETABLE_DIR / "amap_mobile_timetable_regularized_rules.csv")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--boundary-geojson", type=Path, default=None)
    parser.add_argument("--boundary-buffer-m", type=float, default=0.0)
    parser.add_argument("--trajectory-sample-spacing-m", type=float, default=120.0)
    parser.add_argument("--stop-dwell-s", type=float, default=20.0)
    parser.add_argument("--bus-capacity", type=int, default=80)
    parser.add_argument("--snap-k", type=int, default=20)
    parser.add_argument("--disable-dynamic-gap-connectors", action="store_true")
    parser.add_argument("--drop-routes-with-gaps", action="store_true")
    parser.add_argument("--max-bridge-gap-count", type=int, default=0)
    parser.add_argument("--drop-routes-with-stop-snap-p95-gt", type=float, default=0.0)
    parser.add_argument("--max-lines", type=int, default=0, help="Optional smoke-test limit; 0 means all lines.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    network = RoadNetwork(args.network, snap_k=args.snap_k, allow_dynamic_gap_connectors=not args.disable_dynamic_gap_connectors)
    boundary_buffer_geom = None
    if args.boundary_geojson and args.boundary_buffer_m >= 0:
        boundary_buffer_geom = load_boundary_buffer(args.boundary_geojson, args.boundary_buffer_m)
    lines, dropped_stops, dropped_lines, original_route_count = load_bus_lines(args.stops_by_line, boundary_buffer_geom)
    if args.max_lines:
        lines = lines[: args.max_lines]
    trajectories = load_trajectories(args.trajectories)
    by_name, by_direction = build_timetable_index(args.timetable_rules)

    route_results: list[dict[str, Any]] = []
    route_seq_rows: list[dict[str, Any]] = []
    stop_snap_rows: list[dict[str, Any]] = []
    qa_rows: list[dict[str, Any]] = []
    used_links: set[str] = set()

    for idx, line in enumerate(lines, start=1):
        route_links, match_method, sampled_count, gap_count = build_route_from_trajectory(
            network, line, trajectories, args.trajectory_sample_spacing_m, boundary_buffer_geom
        )
        if not route_links:
            qa_rows.append(
                {
                    "line_id": line["line_id"],
                    "line_name": line["line_name"],
                    "status": "failed_no_route",
                    "route_link_count": 0,
                }
            )
            continue
        if args.drop_routes_with_gaps and gap_count > args.max_bridge_gap_count:
            qa_rows.append(
                {
                    "line_id": line["line_id"],
                    "line_name": line["line_name"],
                    "status": "dropped_unresolved_bridge_gaps",
                    "match_method": match_method,
                    "sampled_anchor_count": sampled_count,
                    "bridge_gap_count": gap_count,
                    "stop_count": len(line["stops"]),
                    "route_link_count": len(route_links),
                    "warning": "unresolved_bridge_gaps_not_connected_conservatively",
                }
            )
            continue
        stop_rows, snap_median, snap_p95, unmatched_stops = stop_facilities_for_route(network, line, route_links)
        if args.drop_routes_with_stop_snap_p95_gt > 0 and snap_p95 > args.drop_routes_with_stop_snap_p95_gt:
            qa_rows.append(
                {
                    "line_id": line["line_id"],
                    "line_name": line["line_name"],
                    "status": "dropped_stop_snap_p95_gt_threshold",
                    "match_method": match_method,
                    "sampled_anchor_count": sampled_count,
                    "bridge_gap_count": gap_count,
                    "stop_count": len(stop_rows),
                    "route_link_count": len(route_links),
                    "stop_snap_median_m": round(snap_median, 3),
                    "stop_snap_p95_m": round(snap_p95, 3),
                    "stop_snap_max_m": round(max((row["snap_distance_m"] for row in stop_rows), default=0.0), 3),
                    "warning": "stop_snap_p95_too_large_not_connected_conservatively",
                }
            )
            continue
        stop_offsets = route_offsets(network, route_links, stop_rows, args.stop_dwell_s)
        departures, departure_match_status, departure_source = departures_for_line(line, by_name, by_direction)
        if not departures:
            departures, departure_source = fallback_departures(line["line_name"])
            departure_match_status = "fallback_default_empty_rules"
        used_links.update(route_links)
        route_results.append(
            {
                "line_id": line["line_id"],
                "line_name": line["line_name"],
                "route_links": route_links,
                "stop_offsets": stop_offsets,
                "departures": departures,
            }
        )
        for seq, link_id in enumerate(route_links, start=1):
            link = network.links[link_id]
            route_seq_rows.append(
                {
                    "line_id": line["line_id"],
                    "line_name": line["line_name"],
                    "route_link_sequence": seq,
                    "link_id": link_id,
                    "from_node": link["from"],
                    "to_node": link["to"],
                    "length_m": round(link["length"], 3),
                    "freespeed_mps": round(link["freespeed"], 4),
                }
            )
        for stop in stop_offsets:
            stop_snap_rows.append(
                {
                    "line_id": line["line_id"],
                    "line_name": line["line_name"],
                    "stop_sequence": stop["stop_sequence"],
                    "station_id": stop["station_id"],
                    "station_name": stop["station_name"],
                    "x_epsg32650": round(stop["x"], 3),
                    "y_epsg32650": round(stop["y"], 3),
                    "link_id": stop["link_id"],
                    "route_index": stop["route_index"],
                    "snap_distance_m": round(stop["snap_distance_m"], 3),
                    "arrival_offset": format_hms(stop["arrival_offset_s"]),
                    "departure_offset": format_hms(stop["departure_offset_s"]),
                }
            )
        route_length = sum(network.links[lid]["length"] for lid in route_links)
        max_snap = max((row["snap_distance_m"] for row in stop_rows), default=0.0)
        qa_rows.append(
            {
                "line_id": line["line_id"],
                "line_name": line["line_name"],
                "status": "success",
                "match_method": match_method,
                "sampled_anchor_count": sampled_count,
                "bridge_gap_count": gap_count,
                "stop_count": len(stop_rows),
                "route_link_count": len(route_links),
                "route_length_m": round(route_length, 3),
                "stop_snap_median_m": round(snap_median, 3),
                "stop_snap_p95_m": round(snap_p95, 3),
                "stop_snap_max_m": round(max_snap, 3),
                "unmatched_stops": unmatched_stops,
                "departure_count": len(departures),
                "first_departure": format_hms(departures[0]) if departures else "",
                "last_departure": format_hms(departures[-1]) if departures else "",
                "departure_match_status": departure_match_status,
                "departure_source": departure_source,
                "warning": ";".join(
                    w
                    for w in [
                        "stop_snap_p95_gt_250m" if snap_p95 > 250 else "",
                        "bridge_gap_count_gt_0" if gap_count > 0 else "",
                        "fallback_departures" if departure_match_status.startswith("fallback") else "",
                    ]
                    if w
                ),
            }
        )
        if idx % 100 == 0:
            print(f"Processed {idx}/{len(lines)} bus routes...")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    network_path = args.output_dir / "bus_network_with_pt.xml.gz"
    schedule_path = args.output_dir / "bus_transitSchedule.xml.gz"
    vehicles_path = args.output_dir / "bus_transitVehicles.xml.gz"
    route_seq_path = args.output_dir / "bus_route_link_sequences.csv"
    stop_snap_path = args.output_dir / "bus_stop_link_snap.csv"
    qa_path = args.output_dir / "bus_map_matching_qa.csv"
    dropped_stops_path = args.output_dir / "bus_dropped_stops_outside_boundary_buffer.csv"
    dropped_lines_path = args.output_dir / "bus_dropped_lines_after_boundary_filter.csv"
    summary_path = args.output_dir / "bus_map_matching_summary.json"

    network.write_with_pt_modes(network_path, used_links)
    write_schedule(schedule_path, route_results, network)
    write_vehicles(vehicles_path, route_results, args.bus_capacity)
    write_csv(
        route_seq_path,
        route_seq_rows,
        ["line_id", "line_name", "route_link_sequence", "link_id", "from_node", "to_node", "length_m", "freespeed_mps"],
    )
    write_csv(
        stop_snap_path,
        stop_snap_rows,
        [
            "line_id",
            "line_name",
            "stop_sequence",
            "station_id",
            "station_name",
            "x_epsg32650",
            "y_epsg32650",
            "link_id",
            "route_index",
            "snap_distance_m",
            "arrival_offset",
            "departure_offset",
        ],
    )
    write_csv(
        qa_path,
        qa_rows,
        [
            "line_id",
            "line_name",
            "status",
            "match_method",
            "sampled_anchor_count",
            "bridge_gap_count",
            "stop_count",
            "route_link_count",
            "route_length_m",
            "stop_snap_median_m",
            "stop_snap_p95_m",
            "stop_snap_max_m",
            "unmatched_stops",
            "departure_count",
            "first_departure",
            "last_departure",
            "departure_match_status",
            "departure_source",
            "warning",
        ],
    )
    write_csv(
        dropped_stops_path,
        dropped_stops,
        ["line_id", "line_name", "stop_sequence", "station_id", "station_name", "x_epsg32650", "y_epsg32650", "drop_reason"],
    )
    write_csv(
        dropped_lines_path,
        dropped_lines,
        ["line_id", "line_name", "original_stop_count", "kept_stop_count", "drop_reason"],
    )

    success = [row for row in qa_rows if row.get("status") == "success"]
    warnings = defaultdict(int)
    for row in success:
        for warning in str(row.get("warning") or "").split(";"):
            if warning:
                warnings[warning] += 1
    summary = {
        "created_by": "scripts/build_fuzhou_bus_matsim_transit_mapmatched.py",
        "coordinate_system": "EPSG:32650",
        "inputs": {
            "network": str(args.network),
            "stops_by_line": str(args.stops_by_line),
            "trajectories": str(args.trajectories),
            "timetable_rules": str(args.timetable_rules),
            "boundary_geojson": str(args.boundary_geojson) if args.boundary_geojson else None,
        },
        "outputs": {
            "network": str(network_path),
            "transitSchedule": str(schedule_path),
            "transitVehicles": str(vehicles_path),
            "route_link_sequences": str(route_seq_path),
            "stop_link_snap": str(stop_snap_path),
            "qa": str(qa_path),
            "dropped_stops": str(dropped_stops_path),
            "dropped_lines": str(dropped_lines_path),
            "summary": str(summary_path),
        },
        "parameters": {
            "trajectory_sample_spacing_m": args.trajectory_sample_spacing_m,
            "stop_dwell_s": args.stop_dwell_s,
            "bus_capacity": args.bus_capacity,
            "snap_k": args.snap_k,
            "boundary_buffer_m": args.boundary_buffer_m if args.boundary_geojson else None,
            "allow_dynamic_gap_connectors": not args.disable_dynamic_gap_connectors,
            "drop_routes_with_gaps": args.drop_routes_with_gaps,
            "max_bridge_gap_count": args.max_bridge_gap_count,
            "drop_routes_with_stop_snap_p95_gt": args.drop_routes_with_stop_snap_p95_gt,
        },
        "counts": {
            "input_bus_routes_before_boundary_filter": original_route_count,
            "input_bus_routes": len(lines),
            "successful_routes": len(success),
            "failed_routes": len(lines) - len(success),
            "dropped_routes_after_boundary_filter": len(dropped_lines),
            "dropped_stops_outside_boundary_buffer": len(dropped_stops),
            "success_rate": round(len(success) / len(lines), 4) if lines else 0,
            "pt_enabled_road_links": len(used_links),
            "stop_facilities": len(stop_snap_rows),
            "departures_and_vehicles": sum(len(r["departures"]) for r in route_results),
            "route_link_sequence_rows": len(route_seq_rows),
            "warnings": dict(warnings),
        },
        "qa_summary": {
            "stop_snap_median_m_median": round(float(np.median([safe_float(r.get("stop_snap_median_m")) for r in success])), 3)
            if success
            else None,
            "stop_snap_p95_m_median": round(float(np.median([safe_float(r.get("stop_snap_p95_m")) for r in success])), 3)
            if success
            else None,
            "stop_snap_p95_m_max": round(max([safe_float(r.get("stop_snap_p95_m")) for r in success]), 3) if success else None,
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary["counts"], ensure_ascii=False, indent=2))
    print(f"Wrote {network_path}")
    print(f"Wrote {schedule_path}")
    print(f"Wrote {vehicles_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
