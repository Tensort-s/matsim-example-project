#!/usr/bin/env python3
"""Add a defensible core ferry layer to the Hong Kong 5% MATSim supply.

The script preserves the existing road/PT XML and appends route-specific water
links, ferry stop facilities, representative weekday departures, and scaled
vehicle types. Official GTFS controls service and timing; OSM ferry geometry is
used where it can be matched reliably.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import re
import shutil
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from statistics import median
from typing import Any, Iterable

import geopandas as gpd
import numpy as np
import osmium
import pandas as pd
from pyproj import Transformer
from scipy.spatial import cKDTree
from shapely.geometry import LineString, MultiLineString, Point, mapping
from shapely.ops import linemerge, substring, unary_union


CRS = "EPSG:32650"
REPRESENTATIVE_DATE = "20260722"
CORE_ACCESS_LIMIT_M = 1200.0
OSM_MATCH_LIMIT_M = 500.0
MIN_SEGMENT_SECONDS = 60
FERRY_DWELL_SECONDS = 20
GEOMETRY_STEP_M = 250.0
WATER_LINK_CAPACITY = 9999.0
WATER_LINK_LANES = 1.0
PASSENGER_CAPACITY_FACTOR = 0.10
SUBPOPULATIONS = ("resident", "visitor", "mainland_hk_resident")


@dataclass
class NetworkNode:
    node_id: str
    x: float
    y: float


@dataclass
class FerryPattern:
    route_id: str
    route_name: str
    pattern_id: str
    stop_ids: list[str]
    stop_names: list[str]
    stop_xy: list[tuple[float, float]]
    arrival_offsets: list[int]
    departure_offsets: list[int]
    departures: list[int]
    source_trip_ids: list[str]


@dataclass
class GeometrySource:
    source_id: str
    name: str
    geometry: LineString
    source_type: str


class FerryRelationCollector(osmium.SimpleHandler):
    def __init__(self) -> None:
        super().__init__()
        self.relations: dict[int, dict[str, Any]] = {}

    def relation(self, relation: Any) -> None:
        tags = dict(relation.tags)
        if tags.get("route") != "ferry" and tags.get("route_master") != "ferry":
            return
        way_ids = [int(member.ref) for member in relation.members if member.type == "w"]
        self.relations[int(relation.id)] = {
            "name": tags.get("name", ""),
            "from": tags.get("from", ""),
            "to": tags.get("to", ""),
            "way_ids": way_ids,
        }


class FerryWayCollector(osmium.SimpleHandler):
    def __init__(self, target_way_ids: set[int]) -> None:
        super().__init__()
        self.target_way_ids = target_way_ids
        self.ways: dict[int, LineString] = {}
        self.named_ferry_ways: dict[int, tuple[str, LineString]] = {}

    def way(self, way: Any) -> None:
        tags = dict(way.tags)
        is_ferry = tags.get("route") == "ferry"
        if int(way.id) not in self.target_way_ids and not is_ferry:
            return
        coords: list[tuple[float, float]] = []
        for node in way.nodes:
            if not node.location.valid():
                return
            coords.append((node.location.lon, node.location.lat))
        if len(coords) < 2:
            return
        line = LineString(coords)
        self.ways[int(way.id)] = line
        if is_ferry:
            self.named_ferry_ways[int(way.id)] = (tags.get("name", ""), line)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(r"F:\Matsim\matsim-example-project"),
    )
    parser.add_argument("--representative-date", default=REPRESENTATIVE_DATE)
    parser.add_argument("--core-access-limit-m", type=float, default=CORE_ACCESS_LIMIT_M)
    parser.add_argument("--osm-match-limit-m", type=float, default=OSM_MATCH_LIMIT_M)
    parser.add_argument(
        "--passenger-capacity-factor",
        type=float,
        default=PASSENGER_CAPACITY_FACTOR,
    )
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def safe_id(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("_")


def parse_time(value: str) -> int | None:
    value = str(value or "").strip()
    if not value:
        return None
    hour, minute, second = (int(item) for item in value.split(":"))
    return hour * 3600 + minute * 60 + second


def format_time(seconds: int) -> str:
    seconds = int(seconds)
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def normalize_name(value: str) -> str:
    value = value.lower()
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"[^a-z0-9\u3400-\u9fff]+", " ", value)
    return " ".join(value.split())


def name_similarity(left: str, right: str) -> float:
    left_n = normalize_name(left)
    right_n = normalize_name(right)
    if not left_n or not right_n:
        return 0.0
    ratio = SequenceMatcher(None, left_n, right_n).ratio()
    left_tokens = set(left_n.split())
    right_tokens = set(right_n.split())
    overlap = len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
    return max(ratio, overlap)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_network(path: Path) -> tuple[dict[str, NetworkNode], set[str], set[str]]:
    nodes: dict[str, NetworkNode] = {}
    road_nodes: set[str] = set()
    link_ids: set[str] = set()
    with gzip.open(path, "rb") as handle:
        for _, elem in ET.iterparse(handle, events=("end",)):
            tag = local_name(elem.tag)
            if tag == "node":
                node_id = elem.attrib["id"]
                nodes[node_id] = NetworkNode(
                    node_id=node_id,
                    x=float(elem.attrib["x"]),
                    y=float(elem.attrib["y"]),
                )
            elif tag == "link":
                link_ids.add(elem.attrib["id"])
                modes = set(elem.attrib.get("modes", "").split(","))
                if modes & {"car", "bus", "gmb", "ride"}:
                    road_nodes.add(elem.attrib["from"])
                    road_nodes.add(elem.attrib["to"])
            elem.clear()
    return nodes, road_nodes, link_ids


def active_services(
    calendar: pd.DataFrame,
    exceptions: pd.DataFrame,
    date: str,
) -> set[str]:
    instant = datetime.strptime(date, "%Y%m%d")
    weekday = instant.strftime("%A").lower()
    valid = calendar[
        calendar[weekday].eq("1")
        & calendar["start_date"].le(date)
        & calendar["end_date"].ge(date)
    ]
    services = set(valid["service_id"])
    day = exceptions[exceptions["date"].eq(date)]
    services.update(day.loc[day["exception_type"].eq("1"), "service_id"])
    services.difference_update(day.loc[day["exception_type"].eq("2"), "service_id"])
    return services


def load_gtfs(
    gtfs_dir: Path,
    date: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    kwargs = {"dtype": str, "keep_default_na": False}
    routes = pd.read_csv(gtfs_dir / "routes.txt", **kwargs)
    trips = pd.read_csv(gtfs_dir / "trips.txt", **kwargs)
    stops = pd.read_csv(gtfs_dir / "stops.txt", **kwargs)
    stop_times = pd.read_csv(gtfs_dir / "stop_times.txt", **kwargs)
    frequencies = pd.read_csv(gtfs_dir / "frequencies.txt", **kwargs)
    calendar = pd.read_csv(gtfs_dir / "calendar.txt", **kwargs)
    exceptions = pd.read_csv(gtfs_dir / "calendar_dates.txt", **kwargs)
    services = active_services(calendar, exceptions, date)
    ferry_route_ids = set(routes.loc[routes["route_type"].eq("4"), "route_id"])
    trips = trips[
        trips["route_id"].isin(ferry_route_ids) & trips["service_id"].isin(services)
    ].copy()
    active_trip_ids = set(trips["trip_id"])
    stop_times = stop_times[stop_times["trip_id"].isin(active_trip_ids)].copy()
    stop_times["stop_sequence_number"] = pd.to_numeric(
        stop_times["stop_sequence"], errors="raise"
    )
    stop_times = stop_times.sort_values(["trip_id", "stop_sequence_number"])
    frequencies = frequencies[frequencies["trip_id"].isin(active_trip_ids)].copy()
    return routes, trips, stops, stop_times, frequencies


def classify_core_routes(
    routes: pd.DataFrame,
    trips: pd.DataFrame,
    stops: pd.DataFrame,
    stop_times: pd.DataFrame,
    nodes: dict[str, NetworkNode],
    road_nodes: set[str],
    access_limit_m: float,
) -> tuple[
    set[str],
    pd.DataFrame,
    dict[str, tuple[float, float]],
    pd.DataFrame,
]:
    transformer = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)
    stop_xy: dict[str, tuple[float, float]] = {
        row.stop_id: transformer.transform(float(row.stop_lon), float(row.stop_lat))
        for row in stops.itertuples(index=False)
    }
    road_node_ids = sorted(road_nodes)
    tree = cKDTree(np.array([(nodes[item].x, nodes[item].y) for item in road_node_ids]))
    active_stop_ids = sorted(set(stop_times["stop_id"]))
    query = np.array([stop_xy[item] for item in active_stop_ids])
    distances, indices = tree.query(query)
    stop_access = {
        stop_id: (float(distance), road_node_ids[int(index)])
        for stop_id, distance, index in zip(active_stop_ids, distances, indices)
    }
    trip_route = trips.set_index("trip_id")["route_id"].to_dict()
    rows: list[dict[str, Any]] = []
    for route_id, group in stop_times.assign(
        route_id=stop_times["trip_id"].map(trip_route)
    ).groupby("route_id"):
        ids = sorted(set(group["stop_id"]))
        values = [stop_access[item][0] for item in ids]
        rows.append(
            {
                "route_id": route_id,
                "route_name": routes.set_index("route_id").at[route_id, "route_long_name"],
                "active_stop_count": len(ids),
                "max_road_access_m": max(values),
                "stops_over_limit": sum(value > access_limit_m for value in values),
                "is_core": max(values) <= access_limit_m,
            }
        )
    audit = pd.DataFrame(rows).sort_values("route_id")
    core = set(audit.loc[audit["is_core"], "route_id"])
    for stop_id in active_stop_ids:
        distance, road_node_id = stop_access[stop_id]
        x, y = stop_xy[stop_id]
        stop_xy[stop_id] = (x, y)
    stop_access_frame = pd.DataFrame(
        [
            {
                "stop_id": stop_id,
                "x": stop_xy[stop_id][0],
                "y": stop_xy[stop_id][1],
                "nearest_road_node_id": stop_access[stop_id][1],
                "nearest_road_node_m": stop_access[stop_id][0],
            }
            for stop_id in active_stop_ids
        ]
    )
    return core, audit, stop_xy, stop_access_frame


def interpolate_offsets(
    arrivals: list[int | None],
    departures: list[int | None],
    stop_xy: list[tuple[float, float]],
) -> tuple[list[int], list[int]]:
    first = departures[0] if departures[0] is not None else arrivals[0]
    if first is None:
        first = 0
    raw: list[float | None] = []
    for arrival, departure in zip(arrivals, departures):
        value = arrival if arrival is not None else departure
        raw.append(None if value is None else float(value - first))
    known = [index for index, value in enumerate(raw) if value is not None]
    if not known:
        distances = [0.0]
        for left, right in zip(stop_xy[:-1], stop_xy[1:]):
            distances.append(distances[-1] + math.dist(left, right))
        raw = [value / 7.0 for value in distances]
    else:
        for index in range(len(raw)):
            if raw[index] is not None:
                continue
            before = max((item for item in known if item < index), default=None)
            after = min((item for item in known if item > index), default=None)
            if before is not None and after is not None:
                span = after - before
                ratio = (index - before) / span
                raw[index] = float(raw[before]) + ratio * (
                    float(raw[after]) - float(raw[before])
                )
            elif before is not None:
                raw[index] = float(raw[before]) + MIN_SEGMENT_SECONDS * (index - before)
            elif after is not None:
                raw[index] = max(0.0, float(raw[after]) - MIN_SEGMENT_SECONDS * (after - index))
    arrival_offsets: list[int] = []
    departure_offsets: list[int] = []
    previous = 0
    for index, value in enumerate(raw):
        candidate = max(previous + (MIN_SEGMENT_SECONDS if index else 0), int(round(float(value))))
        arrival_offsets.append(candidate)
        if index in {0, len(raw) - 1}:
            departure_offsets.append(candidate)
        else:
            observed_departure = departures[index]
            observed_arrival = arrivals[index]
            dwell = (
                max(0, observed_departure - observed_arrival)
                if observed_departure is not None and observed_arrival is not None
                else FERRY_DWELL_SECONDS
            )
            departure_offsets.append(candidate + min(120, max(0, dwell)))
        previous = departure_offsets[-1]
    return arrival_offsets, departure_offsets


def build_patterns(
    routes: pd.DataFrame,
    trips: pd.DataFrame,
    stops: pd.DataFrame,
    stop_times: pd.DataFrame,
    frequencies: pd.DataFrame,
    core_route_ids: set[str],
    stop_xy: dict[str, tuple[float, float]],
) -> list[FerryPattern]:
    routes_lookup = routes.set_index("route_id").to_dict("index")
    stops_lookup = stops.set_index("stop_id").to_dict("index")
    trips = trips[trips["route_id"].isin(core_route_ids)].copy()
    active_trip_ids = set(trips["trip_id"])
    stop_times = stop_times[stop_times["trip_id"].isin(active_trip_ids)].copy()
    trip_route = trips.set_index("trip_id")["route_id"].to_dict()
    trip_pattern: dict[str, str] = {}
    pattern_stops: dict[str, list[str]] = {}
    pattern_trips: defaultdict[str, list[str]] = defaultdict(list)
    for trip_id, group in stop_times.groupby("trip_id", sort=False):
        ids = list(group.sort_values("stop_sequence_number")["stop_id"])
        key = f"{trip_route[trip_id]}|{'>'.join(ids)}"
        trip_pattern[trip_id] = key
        pattern_stops[key] = ids
        pattern_trips[key].append(trip_id)

    frequency_by_trip: defaultdict[str, list[Any]] = defaultdict(list)
    for row in frequencies.itertuples(index=False):
        frequency_by_trip[row.trip_id].append(row)

    patterns: list[FerryPattern] = []
    for key in sorted(pattern_stops):
        route_id, _ = key.split("|", 1)
        stop_ids = pattern_stops[key]
        xy = [stop_xy[item] for item in stop_ids]
        arrivals_by_position: list[list[int]] = [[] for _ in stop_ids]
        departures_by_position: list[list[int]] = [[] for _ in stop_ids]
        departure_seconds: list[int] = []
        source_trip_ids = pattern_trips[key]
        for trip_id in source_trip_ids:
            group = stop_times[stop_times["trip_id"].eq(trip_id)].sort_values(
                "stop_sequence_number"
            )
            arrivals = [parse_time(item) for item in group["arrival_time"]]
            departures = [parse_time(item) for item in group["departure_time"]]
            origin = departures[0] if departures[0] is not None else arrivals[0]
            if origin is None:
                continue
            arrival_offsets, departure_offsets = interpolate_offsets(arrivals, departures, xy)
            for index, value in enumerate(arrival_offsets):
                arrivals_by_position[index].append(value)
            for index, value in enumerate(departure_offsets):
                departures_by_position[index].append(value)
            frequency_rows = frequency_by_trip.get(trip_id, [])
            if frequency_rows:
                for frequency in frequency_rows:
                    start = parse_time(frequency.start_time)
                    end = parse_time(frequency.end_time)
                    headway = int(frequency.headway_secs or 0)
                    if start is None or end is None or headway <= 0:
                        continue
                    departure_seconds.extend(range(start, end, headway))
            else:
                departure_seconds.append(origin)
        if not departure_seconds:
            continue
        arrival_offsets = [
            int(round(median(values))) if values else index * MIN_SEGMENT_SECONDS
            for index, values in enumerate(arrivals_by_position)
        ]
        departure_offsets = [
            int(round(median(values))) if values else arrival_offsets[index]
            for index, values in enumerate(departures_by_position)
        ]
        previous = 0
        for index in range(len(stop_ids)):
            arrival_offsets[index] = max(
                arrival_offsets[index], previous + (MIN_SEGMENT_SECONDS if index else 0)
            )
            departure_offsets[index] = max(arrival_offsets[index], departure_offsets[index])
            previous = departure_offsets[index]
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
        patterns.append(
            FerryPattern(
                route_id=route_id,
                route_name=routes_lookup[route_id]["route_long_name"],
                pattern_id=f"ferry_{safe_id(route_id)}_{digest}",
                stop_ids=stop_ids,
                stop_names=[stops_lookup[item]["stop_name"] for item in stop_ids],
                stop_xy=xy,
                arrival_offsets=arrival_offsets,
                departure_offsets=departure_offsets,
                departures=sorted(set(departure_seconds)),
                source_trip_ids=sorted(source_trip_ids),
            )
        )
    return patterns


def project_line(
    line: LineString,
    transformer: Transformer,
) -> LineString:
    return LineString([transformer.transform(x, y) for x, y in line.coords])


def extract_osm_ferry_geometry(
    pbf: Path,
) -> list[GeometrySource]:
    relation_collector = FerryRelationCollector()
    relation_collector.apply_file(str(pbf), locations=False)
    target_way_ids = {
        way_id
        for metadata in relation_collector.relations.values()
        for way_id in metadata["way_ids"]
    }
    way_collector = FerryWayCollector(target_way_ids)
    way_collector.apply_file(str(pbf), locations=True)
    transformer = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)
    sources: list[GeometrySource] = []
    for relation_id, metadata in relation_collector.relations.items():
        lines = [
            way_collector.ways[way_id]
            for way_id in metadata["way_ids"]
            if way_id in way_collector.ways
        ]
        if not lines:
            continue
        unioned = unary_union(lines)
        merged = unioned if isinstance(unioned, LineString) else linemerge(unioned)
        components = [merged] if isinstance(merged, LineString) else list(merged.geoms)
        for index, component in enumerate(components):
            if component.length <= 0:
                continue
            sources.append(
                GeometrySource(
                    source_id=f"osm_relation_{relation_id}_{index}",
                    name=" ".join(
                        item
                        for item in [metadata["name"], metadata["from"], metadata["to"]]
                        if item
                    ),
                    geometry=project_line(component, transformer),
                    source_type="osm_relation",
                )
            )
    relation_way_ids = target_way_ids
    for way_id, (name, line) in way_collector.named_ferry_ways.items():
        if way_id in relation_way_ids:
            continue
        sources.append(
            GeometrySource(
                source_id=f"osm_way_{way_id}",
                name=name,
                geometry=project_line(line, transformer),
                source_type="osm_way",
            )
        )
    return sources


def orient_and_clip_line(
    line: LineString,
    origin: Point,
    destination: Point,
) -> LineString | None:
    start = line.project(origin)
    end = line.project(destination)
    if abs(end - start) < 1.0:
        return None
    clipped = substring(line, min(start, end), max(start, end))
    if not isinstance(clipped, LineString) or len(clipped.coords) < 2:
        return None
    coords = list(clipped.coords)
    if start > end:
        coords.reverse()
    coords[0] = (origin.x, origin.y)
    coords[-1] = (destination.x, destination.y)
    return LineString(coords)


def select_segment_geometry(
    origin_xy: tuple[float, float],
    destination_xy: tuple[float, float],
    route_name: str,
    sources: list[GeometrySource],
    match_limit_m: float,
    land_geometry: Any,
) -> tuple[LineString, dict[str, Any]]:
    origin = Point(origin_xy)
    destination = Point(destination_xy)
    direct = LineString([origin_xy, destination_xy])
    best: tuple[float, GeometrySource, float, float] | None = None
    for source in sources:
        origin_distance = source.geometry.distance(origin)
        destination_distance = source.geometry.distance(destination)
        maximum = max(origin_distance, destination_distance)
        if maximum > match_limit_m:
            continue
        similarity = name_similarity(route_name, source.name)
        score = origin_distance + destination_distance + (1.0 - similarity) * 350.0
        if best is None or score < best[0]:
            best = (score, source, maximum, similarity)
    if best is not None:
        _, source, maximum, similarity = best
        clipped = orient_and_clip_line(source.geometry, origin, destination)
        if clipped is not None and clipped.length >= direct.length * 0.75:
            return clipped, {
                "geometry_source": source.source_type,
                "geometry_source_id": source.source_id,
                "geometry_source_name": source.name,
                "max_stop_to_geometry_m": maximum,
                "name_similarity": similarity,
                "fallback_land_intersection_m": 0.0,
            }
    land_intersection = direct.intersection(land_geometry.buffer(-30.0))
    land_length = float(land_intersection.length) if not land_intersection.is_empty else 0.0
    return direct, {
        "geometry_source": "direct_fallback",
        "geometry_source_id": "",
        "geometry_source_name": "",
        "max_stop_to_geometry_m": 0.0,
        "name_similarity": 0.0,
        "fallback_land_intersection_m": land_length,
    }


def resample_line(line: LineString, step_m: float) -> list[tuple[float, float]]:
    if line.length <= step_m:
        return [tuple(line.coords[0]), tuple(line.coords[-1])]
    distances = list(np.arange(0.0, line.length, step_m)) + [line.length]
    points = [line.interpolate(value) for value in distances]
    coords: list[tuple[float, float]] = []
    for point in points:
        candidate = (float(point.x), float(point.y))
        if not coords or math.dist(coords[-1], candidate) > 0.5:
            coords.append(candidate)
    return coords


def build_water_network(
    patterns: list[FerryPattern],
    geometry_sources: list[GeometrySource],
    land_geometry: Any,
    existing_node_ids: set[str],
    existing_link_ids: set[str],
    match_limit_m: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]], pd.DataFrame]:
    nodes: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    route_data: dict[str, dict[str, Any]] = {}
    audits: list[dict[str, Any]] = []
    node_ids = set(existing_node_ids)
    link_ids = set(existing_link_ids)
    for pattern in patterns:
        route_links: list[str] = []
        facility_links: list[str] = []
        stop_node_ids: list[str] = []
        platform_end_ids: list[str] = []
        for index, (x, y) in enumerate(pattern.stop_xy):
            node_id = f"ferry_node_{pattern.pattern_id}_stop_{index:02d}"
            if node_id in node_ids:
                raise ValueError(f"Duplicate ferry node ID: {node_id}")
            node_ids.add(node_id)
            nodes.append({"node_id": node_id, "x": x, "y": y})
            stop_node_ids.append(node_id)
            platform_end = f"{node_id}_platform_end"
            node_ids.add(platform_end)
            angle = index * 0.17
            nodes.append(
                {
                    "node_id": platform_end,
                    "x": x + math.cos(angle),
                    "y": y + math.sin(angle),
                }
            )
            platform_end_ids.append(platform_end)
            platform_link = f"ferry_platform_{pattern.pattern_id}_{index:02d}"
            if platform_link in link_ids:
                raise ValueError(f"Duplicate ferry link ID: {platform_link}")
            link_ids.add(platform_link)
            links.append(
                {
                    "link_id": platform_link,
                    "from_node": node_id,
                    "to_node": platform_end,
                    "length": 1.0,
                    "freespeed": 10.0,
                    "capacity": WATER_LINK_CAPACITY,
                    "permlanes": WATER_LINK_LANES,
                    "modes": "ferry",
                    "source": "ferry_platform",
                }
            )
            facility_links.append(platform_link)

        for index, (x, y) in enumerate(pattern.stop_xy):
            route_links.append(facility_links[index])
            if index == len(pattern.stop_xy) - 1:
                break
            next_x, next_y = pattern.stop_xy[index + 1]
            line, metadata = select_segment_geometry(
                (x, y),
                (next_x, next_y),
                pattern.route_name,
                geometry_sources,
                match_limit_m,
                land_geometry,
            )
            coords = resample_line(line, GEOMETRY_STEP_M)
            segment_seconds = max(
                MIN_SEGMENT_SECONDS,
                pattern.arrival_offsets[index + 1] - pattern.departure_offsets[index],
            )
            speed = max(2.0, line.length / max(1, segment_seconds) * 1.10)
            previous_node = platform_end_ids[index]
            previous_coord = next(
                (item["x"], item["y"])
                for item in nodes
                if item["node_id"] == previous_node
            )
            segment_link_ids: list[str] = []
            for vertex_index, coord in enumerate(coords[1:-1], start=1):
                vertex_node = (
                    f"ferry_node_{pattern.pattern_id}_seg_{index:02d}_{vertex_index:03d}"
                )
                if vertex_node in node_ids:
                    raise ValueError(f"Duplicate ferry node ID: {vertex_node}")
                node_ids.add(vertex_node)
                nodes.append({"node_id": vertex_node, "x": coord[0], "y": coord[1]})
                link_id = (
                    f"ferry_link_{pattern.pattern_id}_{index:02d}_{vertex_index - 1:03d}"
                )
                if link_id in link_ids:
                    raise ValueError(f"Duplicate ferry link ID: {link_id}")
                link_ids.add(link_id)
                length = max(1.0, math.dist(previous_coord, coord))
                links.append(
                    {
                        "link_id": link_id,
                        "from_node": previous_node,
                        "to_node": vertex_node,
                        "length": length,
                        "freespeed": speed,
                        "capacity": WATER_LINK_CAPACITY,
                        "permlanes": WATER_LINK_LANES,
                        "modes": "ferry",
                        "source": metadata["geometry_source"],
                    }
                )
                segment_link_ids.append(link_id)
                previous_node = vertex_node
                previous_coord = coord
            final_link = f"ferry_link_{pattern.pattern_id}_{index:02d}_final"
            if final_link in link_ids:
                raise ValueError(f"Duplicate ferry link ID: {final_link}")
            link_ids.add(final_link)
            end_node = stop_node_ids[index + 1]
            links.append(
                {
                    "link_id": final_link,
                    "from_node": previous_node,
                    "to_node": end_node,
                    "length": max(1.0, math.dist(previous_coord, (next_x, next_y))),
                    "freespeed": speed,
                    "capacity": WATER_LINK_CAPACITY,
                    "permlanes": WATER_LINK_LANES,
                    "modes": "ferry",
                    "source": metadata["geometry_source"],
                }
            )
            segment_link_ids.append(final_link)
            route_links.extend(segment_link_ids)
            audits.append(
                {
                    "pattern_id": pattern.pattern_id,
                    "route_id": pattern.route_id,
                    "route_name": pattern.route_name,
                    "segment_index": index,
                    "origin_stop_id": pattern.stop_ids[index],
                    "destination_stop_id": pattern.stop_ids[index + 1],
                    "direct_distance_m": math.dist((x, y), (next_x, next_y)),
                    "matched_length_m": line.length,
                    "scheduled_run_time_s": segment_seconds,
                    "network_freespeed_mps": speed,
                    "water_link_count": len(segment_link_ids),
                    **metadata,
                }
            )
        route_data[pattern.pattern_id] = {
            "link_ids": route_links,
            "facility_link_ids": facility_links,
        }
    return nodes, links, route_data, pd.DataFrame(audits)


def scaled_capacity(full_capacity: float, factor: float) -> int:
    return max(1, int(math.floor(full_capacity * factor + 0.5)))


def ferry_vehicle_type(route_id: str, capacity_factor: float) -> tuple[str, int, int, str]:
    if route_id in {"7030", "7031"}:
        full = int(round(3873 / 8))
        return (
            "ferry_star_average_cap010",
            full,
            scaled_capacity(full, capacity_factor),
            "Star Ferry fleet total / 8 vessels",
        )
    if route_id in {"7007", "7008", "7009"}:
        full = 400
        return (
            "ferry_hkkf_catamaran_cap010",
            full,
            scaled_capacity(full, capacity_factor),
            "HKKF 394-408 passenger classes",
        )
    if route_id in {"7005", "7006", "7019", "7020", "7056", "7059"}:
        full = 300
        return (
            "ferry_sun_proxy_cap010",
            full,
            scaled_capacity(full, capacity_factor),
            "Sun Ferry 300 passenger midpoint proxy",
        )
    full = 200
    return (
        "ferry_generic_core_cap010",
        full,
        scaled_capacity(full, capacity_factor),
        "generic 200 passenger core-service proxy",
    )


def append_network(
    source: Path,
    destination: Path,
    nodes: list[dict[str, Any]],
    links: list[dict[str, Any]],
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(source, "rt", encoding="utf-8") as reader, gzip.open(
        destination, "wt", encoding="utf-8", newline="\n"
    ) as writer:
        for line in reader:
            if "</nodes>" in line:
                additions = "".join(
                    (
                        f'    <node id="{node["node_id"]}" x="{node["x"]:.3f}" '
                        f'y="{node["y"]:.3f}"/>\n'
                    )
                    for node in nodes
                )
                line = line.replace("</nodes>", additions + "  </nodes>", 1)
            if "</links>" in line:
                additions = "".join(
                    (
                        f'    <link id="{link["link_id"]}" from="{link["from_node"]}" '
                        f'to="{link["to_node"]}" length="{link["length"]:.3f}" '
                        f'freespeed="{link["freespeed"]:.6f}" '
                        f'capacity="{link["capacity"]:.3f}" '
                        f'permlanes="{link["permlanes"]:.1f}" modes="{link["modes"]}"/>\n'
                    )
                    for link in links
                )
                line = line.replace("</links>", additions + "  </links>", 1)
            writer.write(line)


def append_schedule(
    source: Path,
    destination: Path,
    patterns: list[FerryPattern],
    route_data: dict[str, dict[str, Any]],
    stop_access: pd.DataFrame,
    capacity_factor: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    stop_access_lookup = stop_access.set_index("stop_id").to_dict("index")
    facilities: list[dict[str, Any]] = []
    departures: list[dict[str, Any]] = []
    route_xml_by_line: defaultdict[str, list[str]] = defaultdict(list)
    line_names: dict[str, str] = {}
    for pattern in patterns:
        data = route_data[pattern.pattern_id]
        facility_ids: list[str] = []
        for index, stop_id in enumerate(pattern.stop_ids):
            facility_id = f"ferry_stop_{pattern.pattern_id}_{index:02d}"
            facility_ids.append(facility_id)
            access = stop_access_lookup[stop_id]
            facilities.append(
                {
                    "facility_id": facility_id,
                    "stop_id": stop_id,
                    "stop_name": pattern.stop_names[index],
                    "x": pattern.stop_xy[index][0],
                    "y": pattern.stop_xy[index][1],
                    "link_ref_id": data["facility_link_ids"][index],
                    "nearest_road_node_id": access["nearest_road_node_id"],
                    "nearest_road_node_m": access["nearest_road_node_m"],
                }
            )
        line_id = f"ferry_line_{safe_id(pattern.route_id)}"
        line_names[line_id] = pattern.route_name
        lines = route_xml_by_line[line_id]
        lines.append(f'    <transitRoute id="{pattern.pattern_id}">\n')
        lines.append("      <transportMode>ferry</transportMode>\n")
        lines.append("      <routeProfile>\n")
        for index, facility_id in enumerate(facility_ids):
            lines.append(
                f'        <stop refId="{facility_id}" '
                f'arrivalOffset="{format_time(pattern.arrival_offsets[index])}" '
                f'departureOffset="{format_time(pattern.departure_offsets[index])}" '
                f'awaitDeparture="true"/>\n'
            )
        lines.append("      </routeProfile>\n")
        lines.append("      <route>\n")
        for link_id in data["link_ids"]:
            lines.append(f'        <link refId="{link_id}"/>\n')
        lines.append("      </route>\n")
        lines.append("      <departures>\n")
        vehicle_type_id, full_capacity, capacity, evidence = ferry_vehicle_type(
            pattern.route_id, capacity_factor
        )
        for index, departure_second in enumerate(pattern.departures):
            departure_id = f"ferry_dep_{pattern.pattern_id}_{index:04d}"
            vehicle_id = f"ferry_vehicle_{pattern.pattern_id}_{index:04d}"
            lines.append(
                f'        <departure id="{departure_id}" '
                f'departureTime="{format_time(departure_second)}" '
                f'vehicleRefId="{vehicle_id}"/>\n'
            )
            departures.append(
                {
                    "departure_id": departure_id,
                    "vehicle_id": vehicle_id,
                    "vehicle_type_id": vehicle_type_id,
                    "route_id": pattern.route_id,
                    "pattern_id": pattern.pattern_id,
                    "departure_seconds": departure_second,
                    "full_capacity_proxy": full_capacity,
                    "capacity_factor": capacity_factor,
                    "scaled_capacity": capacity,
                    "capacity_evidence": evidence,
                }
            )
        lines.append("      </departures>\n")
        lines.append("    </transitRoute>\n")

    with gzip.open(source, "rt", encoding="utf-8") as reader, gzip.open(
        destination, "wt", encoding="utf-8", newline="\n"
    ) as writer:
        for line in reader:
            if "</transitStops>" in line:
                additions = "".join(
                    (
                        f'    <stopFacility id="{facility["facility_id"]}" '
                        f'x="{facility["x"]:.3f}" y="{facility["y"]:.3f}" '
                        f'linkRefId="{facility["link_ref_id"]}" '
                        f'name="{xml_escape(facility["stop_name"])}" isBlocking="false"/>\n'
                    )
                    for facility in facilities
                )
                line = line.replace(
                    "</transitStops>", additions + "  </transitStops>", 1
                )
            if "</transitSchedule>" in line:
                additions = []
                for line_id in sorted(route_xml_by_line):
                    additions.append(
                        f'  <transitLine id="{line_id}" '
                        f'name="{xml_escape(line_names[line_id])}">\n'
                    )
                    additions.extend(route_xml_by_line[line_id])
                    additions.append("  </transitLine>\n")
                line = line.replace(
                    "</transitSchedule>", "".join(additions) + "</transitSchedule>", 1
                )
            writer.write(line)
    return facilities, departures


def xml_escape(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def append_vehicles(
    source: Path,
    full_capacity_reference: Path,
    destination: Path,
    departures: list[dict[str, Any]],
    capacity_factor: float,
) -> pd.DataFrame:
    namespace = "http://www.matsim.org/files/dtd"
    ET.register_namespace("", namespace)
    ET.register_namespace(
        "xsi", "http://www.w3.org/2001/XMLSchema-instance"
    )

    with gzip.open(full_capacity_reference, "rb") as handle:
        reference_root = ET.parse(handle).getroot()
    reference_capacities: dict[str, tuple[int, int]] = {}
    for vehicle_type in reference_root:
        if local_name(vehicle_type.tag) != "vehicleType":
            continue
        capacity = next(
            (
                child
                for child in vehicle_type
                if local_name(child.tag) == "capacity"
            ),
            None,
        )
        if capacity is not None:
            reference_capacities[vehicle_type.attrib["id"]] = (
                int(capacity.attrib["seats"]),
                int(capacity.attrib["standingRoomInPersons"]),
            )

    with gzip.open(source, "rb") as handle:
        root = ET.parse(handle).getroot()
    capacity_audit: list[dict[str, Any]] = []
    for vehicle_type in root:
        if local_name(vehicle_type.tag) != "vehicleType":
            continue
        type_id = vehicle_type.attrib["id"]
        if type_id not in reference_capacities:
            raise KeyError(f"Missing full-capacity reference for vehicle type {type_id}")
        full_seats, full_standing = reference_capacities[type_id]
        capacity = next(
            child
            for child in vehicle_type
            if local_name(child.tag) == "capacity"
        )
        old_seats = int(capacity.attrib["seats"])
        old_standing = int(capacity.attrib["standingRoomInPersons"])
        new_seats = scaled_capacity(full_seats, capacity_factor) if full_seats else 0
        new_standing = (
            scaled_capacity(full_standing, capacity_factor) if full_standing else 0
        )
        capacity.set("seats", str(new_seats))
        capacity.set("standingRoomInPersons", str(new_standing))
        pce = next(
            (
                child.attrib.get("pce", "")
                for child in vehicle_type
                if local_name(child.tag) == "passengerCarEquivalents"
            ),
            "",
        )
        capacity_audit.append(
            {
                "vehicle_type_id": type_id,
                "mode": "existing",
                "full_seats": full_seats,
                "full_standing": full_standing,
                "source_scaled_seats": old_seats,
                "source_scaled_standing": old_standing,
                "capacity_factor": capacity_factor,
                "output_seats": new_seats,
                "output_standing": new_standing,
                "pce_unchanged": pce,
            }
        )

    type_rows: dict[str, dict[str, Any]] = {}
    for row in departures:
        type_rows[row["vehicle_type_id"]] = row
    insertion_index = next(
        index
        for index, child in enumerate(root)
        if local_name(child.tag) == "vehicle"
    )
    for type_id in sorted(type_rows):
        row = type_rows[type_id]
        vehicle_type = ET.Element(f"{{{namespace}}}vehicleType", {"id": type_id})
        ET.SubElement(
            vehicle_type,
            f"{{{namespace}}}capacity",
            {
                "seats": str(row["scaled_capacity"]),
                "standingRoomInPersons": "0",
            },
        )
        ET.SubElement(
            vehicle_type, f"{{{namespace}}}length", {"meter": "25.000"}
        )
        ET.SubElement(
            vehicle_type, f"{{{namespace}}}width", {"meter": "8.000"}
        )
        ET.SubElement(
            vehicle_type,
            f"{{{namespace}}}passengerCarEquivalents",
            {"pce": "1.000000"},
        )
        ET.SubElement(
            vehicle_type,
            f"{{{namespace}}}networkMode",
            {"networkMode": "ferry"},
        )
        root.insert(insertion_index, vehicle_type)
        insertion_index += 1
        capacity_audit.append(
            {
                "vehicle_type_id": type_id,
                "mode": "ferry",
                "full_seats": row["full_capacity_proxy"],
                "full_standing": 0,
                "source_scaled_seats": "",
                "source_scaled_standing": "",
                "capacity_factor": capacity_factor,
                "output_seats": row["scaled_capacity"],
                "output_standing": 0,
                "pce_unchanged": 1.0,
            }
        )
    for row in departures:
        ET.SubElement(
            root,
            f"{{{namespace}}}vehicle",
            {
                "id": row["vehicle_id"],
                "type": row["vehicle_type_id"],
            },
        )
    ET.indent(root, space="  ")
    with gzip.open(destination, "wb") as handle:
        handle.write(b'<?xml version="1.0" encoding="utf-8"?>\n')
        handle.write(ET.tostring(root, encoding="utf-8"))
        handle.write(b"\n")
    return pd.DataFrame(capacity_audit)


def config_module(root: ET.Element, name: str) -> ET.Element:
    for module in root.findall("module"):
        if module.attrib.get("name") == name:
            return module
    raise KeyError(f"Missing config module: {name}")


def set_config_param(module: ET.Element, name: str, value: str) -> None:
    for param in module.findall("param"):
        if param.attrib.get("name") == name:
            param.set("value", value)
            return
    ET.SubElement(module, "param", {"name": name, "value": value})


def write_ferry_config(
    source: Path,
    destination: Path,
    network: Path,
    schedule: Path,
    vehicles: Path,
    output_directory: Path,
) -> None:
    root = ET.parse(source).getroot()
    set_config_param(config_module(root, "network"), "inputNetworkFile", network.as_posix())
    transit = config_module(root, "transit")
    set_config_param(transit, "transitScheduleFile", schedule.as_posix())
    set_config_param(transit, "vehiclesFile", vehicles.as_posix())
    set_config_param(
        transit,
        "transitModes",
        "bus,gmb,train,light_rail,ferry",
    )
    controller = config_module(root, "controller")
    set_config_param(controller, "outputDirectory", output_directory.as_posix())
    set_config_param(controller, "overwriteFiles", "failIfDirectoryExists")
    replanning = config_module(root, "replanning")
    for parameter_set in list(replanning.findall("parameterset")):
        replanning.remove(parameter_set)
    for subpopulation in SUBPOPULATIONS:
        for strategy_name, weight, disable_after in [
            ("ChangeExpBeta", "0.85", None),
            ("ReRoute", "0.15", "40"),
        ]:
            parameter_set = ET.SubElement(
                replanning, "parameterset", {"type": "strategysettings"}
            )
            ET.SubElement(
                parameter_set,
                "param",
                {"name": "strategyName", "value": strategy_name},
            )
            ET.SubElement(
                parameter_set,
                "param",
                {"name": "weight", "value": weight},
            )
            ET.SubElement(
                parameter_set,
                "param",
                {"name": "subpopulation", "value": subpopulation},
            )
            if disable_after is not None:
                ET.SubElement(
                    parameter_set,
                    "param",
                    {"name": "disableAfterIteration", "value": disable_after},
                )
    ET.indent(root, space="  ")
    xml = ET.tostring(root, encoding="unicode")
    destination.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE config SYSTEM "http://www.matsim.org/files/dtd/config_v2.dtd">\n'
        + xml
        + "\n",
        encoding="utf-8",
    )


def xml_counts(
    network: Path,
    schedule: Path,
    vehicles: Path,
) -> dict[str, Any]:
    node_ids: set[str] = set()
    links: dict[str, tuple[str, str, set[str]]] = {}
    with gzip.open(network, "rb") as handle:
        for _, elem in ET.iterparse(handle, events=("end",)):
            tag = local_name(elem.tag)
            if tag == "node":
                node_ids.add(elem.attrib["id"])
            elif tag == "link":
                links[elem.attrib["id"]] = (
                    elem.attrib["from"],
                    elem.attrib["to"],
                    set(elem.attrib.get("modes", "").split(",")),
                )
            elem.clear()
    facility_links: dict[str, str] = {}
    route_count = departure_count = continuity_errors = mode_errors = 0
    departure_vehicle_refs: list[str] = []
    current_mode = ""
    current_links: list[str] = []
    in_route = False
    with gzip.open(schedule, "rb") as handle:
        for event, elem in ET.iterparse(handle, events=("start", "end")):
            tag = local_name(elem.tag)
            if event == "start" and tag == "transitRoute":
                in_route = True
                current_mode = ""
                current_links = []
            elif event == "end" and tag == "stopFacility":
                facility_links[elem.attrib["id"]] = elem.attrib["linkRefId"]
                elem.clear()
            elif event == "end" and tag == "transportMode" and in_route:
                current_mode = elem.text or ""
            elif event == "end" and tag == "link" and in_route:
                current_links.append(elem.attrib["refId"])
            elif event == "end" and tag == "departure" and in_route:
                departure_count += 1
                departure_vehicle_refs.append(elem.attrib["vehicleRefId"])
            elif event == "end" and tag == "transitRoute":
                route_count += 1
                for left, right in zip(current_links[:-1], current_links[1:]):
                    if links[left][1] != links[right][0]:
                        continuity_errors += 1
                if any(current_mode not in links[item][2] for item in current_links):
                    mode_errors += 1
                in_route = False
                elem.clear()
            elif event == "end" and not in_route:
                elem.clear()
    vehicle_ids: set[str] = set()
    vehicle_types: set[str] = set()
    invalid_vehicle_types = 0
    pending_vehicles: list[str] = []
    with gzip.open(vehicles, "rb") as handle:
        for _, elem in ET.iterparse(handle, events=("end",)):
            tag = local_name(elem.tag)
            if tag == "vehicleType":
                vehicle_types.add(elem.attrib["id"])
            elif tag == "vehicle":
                vehicle_ids.add(elem.attrib["id"])
                pending_vehicles.append(elem.attrib["type"])
            elem.clear()
    invalid_vehicle_types = sum(item not in vehicle_types for item in pending_vehicles)
    return {
        "nodes": len(node_ids),
        "links": len(links),
        "facilities": len(facility_links),
        "routes": route_count,
        "departures": departure_count,
        "vehicle_types": len(vehicle_types),
        "vehicles": len(vehicle_ids),
        "facility_missing_link_errors": sum(
            link_id not in links for link_id in facility_links.values()
        ),
        "route_link_continuity_errors": continuity_errors,
        "route_mode_link_errors": mode_errors,
        "missing_vehicle_reference_errors": sum(
            item not in vehicle_ids for item in departure_vehicle_refs
        ),
        "invalid_vehicle_type_references": invalid_vehicle_types,
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    args = parse_args()
    if not 0.0 < args.passenger_capacity_factor <= 1.0:
        raise ValueError("--passenger-capacity-factor must be in (0, 1]")
    project_root = args.project_root.resolve()
    data_root = project_root / "data"
    transit_root = data_root / "transit/hongkong"
    source_dir = (
        transit_root
        / "processed/matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_v1"
    )
    output_dir = args.output_dir or (
        transit_root
        / "processed/matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_ferry_core_v1_cap010"
    )
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise FileExistsError(f"Output directory already exists: {output_dir}")
    output_dir.mkdir(parents=True)

    source_network = source_dir / "network.xml.gz"
    source_schedule = source_dir / "transitSchedule_5pct.xml.gz"
    source_vehicles = source_dir / "transitVehicles_5pct.xml.gz"
    full_capacity_reference = (
        transit_root
        / "processed/matsim_road_pt_supply_2026_typical_weekday/transitVehicles.xml.gz"
    )
    source_config = (
        data_root
        / "matsim_agents/hongkong/typical_weekday_5pct_v1/config_hong_kong_5pct_50it.xml"
    )
    gtfs_dir = transit_root / "PublicTransportGTFS"
    osm_pbf = (
        data_root
        / "osm/hongkong/fixed_link_boundary/hong-kong-latest.osm.pbf"
    )
    boundary_path = (
        data_root
        / "boundary/hongkong/processed/hong_kong_fixed_link_boundary_wgs84.geojson"
    )
    for path in [
        source_network,
        source_schedule,
        source_vehicles,
        full_capacity_reference,
        source_config,
        osm_pbf,
        boundary_path,
    ]:
        if not path.exists():
            raise FileNotFoundError(path)

    nodes, road_nodes, existing_link_ids = read_network(source_network)
    routes, trips, stops, stop_times, frequencies = load_gtfs(
        gtfs_dir, args.representative_date
    )
    core_route_ids, route_audit, stop_xy, stop_access = classify_core_routes(
        routes,
        trips,
        stops,
        stop_times,
        nodes,
        road_nodes,
        args.core_access_limit_m,
    )
    patterns = build_patterns(
        routes,
        trips,
        stops,
        stop_times,
        frequencies,
        core_route_ids,
        stop_xy,
    )
    geometry_sources = extract_osm_ferry_geometry(osm_pbf)
    land = gpd.read_file(boundary_path).to_crs(CRS).geometry.union_all()
    new_nodes, new_links, route_data, geometry_audit = build_water_network(
        patterns,
        geometry_sources,
        land,
        set(nodes),
        existing_link_ids,
        args.osm_match_limit_m,
    )

    network_output = output_dir / "network.xml.gz"
    schedule_output = output_dir / "transitSchedule_5pct.xml.gz"
    vehicles_output = output_dir / "transitVehicles_10pct.xml.gz"
    append_network(source_network, network_output, new_nodes, new_links)
    facilities, departures = append_schedule(
        source_schedule,
        schedule_output,
        patterns,
        route_data,
        stop_access,
        args.passenger_capacity_factor,
    )
    capacity_audit = append_vehicles(
        source_vehicles,
        full_capacity_reference,
        vehicles_output,
        departures,
        args.passenger_capacity_factor,
    )
    config_output = output_dir / "config_hong_kong_5pct_ferry_core_v1_cap010_50it.xml"
    write_ferry_config(
        source_config,
        config_output,
        network_output,
        schedule_output,
        vehicles_output,
        data_root
        / "matsim_agents/hongkong/typical_weekday_5pct_ferry_core_v1_cap010"
        / "matsim_50it_output",
    )

    route_audit.to_csv(
        output_dir / "ferry_active_route_core_classification.csv",
        index=False,
        encoding="utf-8-sig",
    )
    stop_access.to_csv(
        output_dir / "ferry_stop_road_access_audit.csv",
        index=False,
        encoding="utf-8-sig",
    )
    geometry_audit.to_csv(
        output_dir / "ferry_geometry_matching_audit.csv",
        index=False,
        encoding="utf-8-sig",
    )
    pd.DataFrame(facilities).to_csv(
        output_dir / "ferry_stop_facilities.csv",
        index=False,
        encoding="utf-8-sig",
    )
    pd.DataFrame(departures).to_csv(
        output_dir / "ferry_departures_5pct.csv",
        index=False,
        encoding="utf-8-sig",
    )
    pd.DataFrame(new_links).to_csv(
        output_dir / "ferry_water_links.csv",
        index=False,
        encoding="utf-8-sig",
    )
    capacity_audit.to_csv(
        output_dir / "transit_vehicle_capacity_10pct_audit.csv",
        index=False,
        encoding="utf-8-sig",
    )
    route_features: list[dict[str, Any]] = []
    for pattern in patterns:
        coords = pattern.stop_xy
        route_features.append(
            {
                "type": "Feature",
                "properties": {
                    "route_id": pattern.route_id,
                    "pattern_id": pattern.pattern_id,
                    "route_name": pattern.route_name,
                    "stop_count": len(pattern.stop_ids),
                    "departure_count": len(pattern.departures),
                },
                "geometry": mapping(LineString(coords)) if len(coords) >= 2 else None,
            }
        )
    write_json(
        output_dir / "ferry_core_routes_epsg32650.geojson",
        {
            "type": "FeatureCollection",
            "name": "hong_kong_ferry_core_v1",
            "crs": {"type": "name", "properties": {"name": CRS}},
            "features": route_features,
        },
    )

    qa = xml_counts(network_output, schedule_output, vehicles_output)
    failed = {
        key: value
        for key, value in qa.items()
        if key.endswith("_errors") and value != 0
    }
    direct_fallbacks = int(
        geometry_audit["geometry_source"].eq("direct_fallback").sum()
    )
    land_crossing_fallbacks = int(
        (
            geometry_audit["geometry_source"].eq("direct_fallback")
            & geometry_audit["fallback_land_intersection_m"].gt(200.0)
        ).sum()
    )
    summary = {
        "version": "ferry_core_v1_cap010",
        "representative_date": args.representative_date,
        "crs": CRS,
        "source_supply": str(source_dir),
        "core_definition": (
            f"All active route stops are within {args.core_access_limit_m:.0f} m "
            "of a road-network node."
        ),
        "active_ferry_routes": int(len(route_audit)),
        "core_ferry_routes": len(core_route_ids),
        "excluded_ferry_routes": int(len(route_audit) - len(core_route_ids)),
        "core_route_patterns": len(patterns),
        "ferry_departures": len(departures),
        "ferry_stop_facilities": len(facilities),
        "new_water_nodes": len(new_nodes),
        "new_water_links": len(new_links),
        "osm_geometry_sources": len(geometry_sources),
        "direct_geometry_fallback_segments": direct_fallbacks,
        "direct_fallback_land_crossing_over_200m": land_crossing_fallbacks,
        "passenger_capacity_factor": args.passenger_capacity_factor,
        "vehicle_capacity_scope": (
            "All public-transport seats and standing capacity use the full-scale "
            f"reference times {args.passenger_capacity_factor:.2f}; bus/GMB PCU "
            "remains at the separately configured 0.05 factor."
        ),
        "existing_vehicle_types_rescaled": int(
            capacity_audit["mode"].eq("existing").sum()
        ),
        "ferry_vehicle_types_added": int(capacity_audit["mode"].eq("ferry").sum()),
        "qa": qa,
        "qa_passed": not failed and land_crossing_fallbacks == 0,
        "outputs": {
            "network": str(network_output),
            "schedule": str(schedule_output),
            "vehicles": str(vehicles_output),
            "config_50it": str(config_output),
        },
    }
    write_json(output_dir / "ferry_core_supply_summary.json", summary)
    checksum_paths = [
        network_output,
        schedule_output,
        vehicles_output,
        config_output,
        output_dir / "ferry_core_supply_summary.json",
    ]
    with (output_dir / "SHA256SUMS.txt").open("w", encoding="ascii", newline="\n") as handle:
        for path in checksum_paths:
            handle.write(f"{sha256_file(path)}  {path.name}\n")
    if failed:
        raise RuntimeError(f"Ferry Core XML QA failed: {failed}")
    if land_crossing_fallbacks:
        raise RuntimeError(
            f"{land_crossing_fallbacks} fallback ferry segments cross more than 200 m of land"
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
