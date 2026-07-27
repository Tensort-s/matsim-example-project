"""Build a detailed multimodal particle animation from Hong Kong MATSim events.

The visualization distinguishes people, private cars, buses/GMB, rail, and
ferries. People are visible only while moving between activities and vehicles;
the matching vehicle particle represents them while they are onboard. Access,
egress, walk, and teleported ride segments are reconstructed on the street
graph, and unroutable segments are audited instead of drawn as straight lines.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import gzip
import hashlib
import heapq
import io
import json
import math
import pathlib
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import BinaryIO, Iterator


ATTR_RE = re.compile(r'(\w+)="([^"]*)"')
CATEGORIES = ("person", "car", "bus", "rail", "ferry")
VEHICLE_CATEGORIES = ("car", "bus", "rail", "ferry")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a detailed Hong Kong multimodal particle-flow viewer."
    )
    parser.add_argument("--events", type=pathlib.Path, required=True)
    parser.add_argument("--network", type=pathlib.Path, required=True)
    parser.add_argument("--transit-vehicles", type=pathlib.Path, required=True)
    parser.add_argument("--output-dir", type=pathlib.Path, required=True)
    parser.add_argument("--start-hour", type=float, default=5.0)
    parser.add_argument("--end-hour", type=float, default=24.0)
    parser.add_argument("--people", type=int, default=6500)
    parser.add_argument("--cars", type=int, default=2200)
    parser.add_argument("--buses", type=int, default=1400)
    parser.add_argument("--rail", type=int, default=550)
    parser.add_argument("--ferries", type=int, default=180)
    parser.add_argument("--max-person-points", type=int, default=90)
    parser.add_argument("--max-vehicle-points", type=int, default=180)
    parser.add_argument("--max-walk-route-expansions", type=int, default=30000)
    parser.add_argument("--max-walk-snap-distance", type=float, default=600.0)
    return parser.parse_args()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


@contextlib.contextmanager
def open_binary(path: pathlib.Path) -> Iterator[BinaryIO]:
    if path.suffix == ".zst":
        process = subprocess.Popen(
            ["zstd", "-dc", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if process.stdout is None or process.stderr is None:
            raise RuntimeError(f"Could not open zstd stream: {path}")
        try:
            yield process.stdout
        finally:
            process.stdout.close()
            stderr = process.stderr.read().decode("utf-8", errors="replace")
            process.stderr.close()
            return_code = process.wait()
            if return_code != 0:
                raise RuntimeError(
                    f"zstd failed for {path} with exit code {return_code}: {stderr}"
                )
    elif path.suffix == ".gz":
        with gzip.open(path, "rb") as stream:
            yield stream
    else:
        with path.open("rb") as stream:
            yield stream


def iter_event_attributes(events_path: pathlib.Path) -> Iterator[dict[str, str]]:
    with open_binary(events_path) as stream:
        text = io.TextIOWrapper(stream, encoding="utf-8")
        for line in text:
            if "<event " in line:
                yield dict(ATTR_RE.findall(line))


def stable_u64(text: str) -> int:
    return int.from_bytes(
        hashlib.blake2b(text.encode("utf-8"), digest_size=8).digest(), "big"
    )


def is_transit_driver(person_id: str) -> bool:
    return person_id.startswith("pt_veh_")


@dataclass(frozen=True)
class Link:
    from_node: str
    to_node: str
    length: float
    modes: frozenset[str]


@dataclass
class Network:
    nodes_xy: dict[str, tuple[float, float]]
    nodes_lonlat: dict[str, tuple[float, float]]
    links: dict[str, Link]
    walk_adjacency: dict[str, list[tuple[str, float]]]
    walk_components: dict[str, int]
    walk_component_sizes: dict[int, int]
    walk_spatial_index: dict[tuple[int, int], list[str]]


@dataclass
class Track:
    track_id: str
    category: str
    detail: str
    points: list[tuple[float, float, float]] = field(default_factory=list)


@dataclass
class RawStreetSegment:
    person_id: str
    detail: str
    start_link: str
    end_link: str
    start_s: float
    end_s: float


@dataclass
class PendingLeg:
    mode: str
    link_id: str
    start_s: float


def inverse_utm50(x: float, y: float) -> tuple[float, float]:
    """Convert EPSG:32650 coordinates to WGS84 without an external dependency."""
    a = 6378137.0
    ecc_sq = 0.0066943799901413165
    k0 = 0.9996
    x -= 500000.0
    m = y / k0
    mu = m / (
        a
        * (
            1
            - ecc_sq / 4
            - 3 * ecc_sq * ecc_sq / 64
            - 5 * ecc_sq**3 / 256
        )
    )
    e1 = (1 - math.sqrt(1 - ecc_sq)) / (1 + math.sqrt(1 - ecc_sq))
    j1 = 3 * e1 / 2 - 27 * e1**3 / 32
    j2 = 21 * e1 * e1 / 16 - 55 * e1**4 / 32
    j3 = 151 * e1**3 / 96
    j4 = 1097 * e1**4 / 512
    fp = mu + j1 * math.sin(2 * mu) + j2 * math.sin(4 * mu)
    fp += j3 * math.sin(6 * mu) + j4 * math.sin(8 * mu)
    ecc_prime_sq = ecc_sq / (1 - ecc_sq)
    c1 = ecc_prime_sq * math.cos(fp) ** 2
    t1 = math.tan(fp) ** 2
    n1 = a / math.sqrt(1 - ecc_sq * math.sin(fp) ** 2)
    r1 = a * (1 - ecc_sq) / (1 - ecc_sq * math.sin(fp) ** 2) ** 1.5
    d = x / (n1 * k0)
    lat = fp - (n1 * math.tan(fp) / r1) * (
        d * d / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * ecc_prime_sq)
        * d**4
        / 24
        + (
            61
            + 90 * t1
            + 298 * c1
            + 45 * t1 * t1
            - 252 * ecc_prime_sq
            - 3 * c1 * c1
        )
        * d**6
        / 720
    )
    lon = (
        d
        - (1 + 2 * t1 + c1) * d**3 / 6
        + (
            5
            - 2 * c1
            + 28 * t1
            - 3 * c1 * c1
            + 8 * ecc_prime_sq
            + 24 * t1 * t1
        )
        * d**5
        / 120
    ) / math.cos(fp)
    lon += math.radians(117.0)
    return math.degrees(lon), math.degrees(lat)


def read_network(path: pathlib.Path) -> Network:
    nodes_xy: dict[str, tuple[float, float]] = {}
    links: dict[str, Link] = {}
    with open_binary(path) as stream:
        for _, elem in ET.iterparse(stream, events=("end",)):
            name = local_name(elem.tag)
            if name == "node":
                nodes_xy[elem.attrib["id"]] = (
                    float(elem.attrib["x"]),
                    float(elem.attrib["y"]),
                )
            elif name == "link":
                modes = frozenset(
                    value.strip()
                    for value in elem.attrib.get("modes", "").split(",")
                    if value.strip()
                )
                links[elem.attrib["id"]] = Link(
                    elem.attrib["from"],
                    elem.attrib["to"],
                    float(elem.attrib.get("length", "1")),
                    modes,
                )
            elem.clear()

    nodes_lonlat = {
        node_id: inverse_utm50(*xy) for node_id, xy in nodes_xy.items()
    }
    adjacency: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for link_id, link in links.items():
        road_like = link_id.startswith(("road_", "connector_", "topology_"))
        walk_allowed = not link.modes or "walk" in link.modes or road_like
        if walk_allowed and not link_id.startswith(("rail_", "ferry_")):
            adjacency[link.from_node].append((link.to_node, max(0.1, link.length)))
            adjacency[link.to_node].append((link.from_node, max(0.1, link.length)))
    walk_components: dict[str, int] = {}
    component_id = 0
    for seed in adjacency:
        if seed in walk_components:
            continue
        stack = [seed]
        walk_components[seed] = component_id
        while stack:
            node_id = stack.pop()
            for next_id, _ in adjacency.get(node_id, ()):
                if next_id not in walk_components:
                    walk_components[next_id] = component_id
                    stack.append(next_id)
        component_id += 1
    component_sizes = Counter(walk_components.values())
    spatial_index: dict[tuple[int, int], list[str]] = defaultdict(list)
    cell_size = 500.0
    for node_id in adjacency:
        x, y = nodes_xy[node_id]
        spatial_index[(math.floor(x / cell_size), math.floor(y / cell_size))].append(
            node_id
        )
    return Network(
        nodes_xy,
        nodes_lonlat,
        links,
        dict(adjacency),
        walk_components,
        dict(component_sizes),
        dict(spatial_index),
    )


def read_transit_vehicle_categories(path: pathlib.Path) -> dict[str, str]:
    categories: dict[str, str] = {}
    with open_binary(path) as stream:
        for _, elem in ET.iterparse(stream, events=("end",)):
            if local_name(elem.tag) != "vehicle":
                elem.clear()
                continue
            vehicle_id = elem.attrib.get("id", "")
            type_id = elem.attrib.get("type", "").lower()
            combined = f"{vehicle_id.lower()} {type_id}"
            if "ferry" in combined:
                category = "ferry"
            elif any(token in combined for token in ("mtr_", "lrt_", "rail", "train")):
                category = "rail"
            else:
                category = "bus"
            if vehicle_id:
                categories[vehicle_id] = category
            elem.clear()
    return categories


def classify_vehicle(vehicle_id: str, transit: dict[str, str]) -> str:
    return transit.get(vehicle_id, "car")


class LowestHashes:
    def __init__(self, quota: int) -> None:
        self.quota = quota
        self.heap: list[tuple[int, str]] = []
        self.items: set[str] = set()

    def add(self, item: str) -> None:
        if item in self.items or self.quota <= 0:
            return
        value = stable_u64(item)
        entry = (-value, item)
        if len(self.heap) < self.quota:
            heapq.heappush(self.heap, entry)
            self.items.add(item)
            return
        if entry > self.heap[0]:
            _, removed = heapq.heapreplace(self.heap, entry)
            self.items.remove(removed)
            self.items.add(item)

    def selected(self) -> set[str]:
        return set(self.items)


def vehicle_trip_key(vehicle_id: str, time_s: float) -> str:
    return f"{vehicle_id}|{time_s:.3f}"


def select_samples(
    events_path: pathlib.Path,
    transit: dict[str, str],
    start_s: float,
    end_s: float,
    quotas: dict[str, int],
) -> tuple[set[str], dict[str, set[str]], Counter[str]]:
    people = LowestHashes(quotas["person"])
    vehicles = {
        category: LowestHashes(quotas[category])
        for category in VEHICLE_CATEGORIES
    }
    counts: Counter[str] = Counter()
    seen_people: set[str] = set()
    for attrs in iter_event_attributes(events_path):
        event_type = attrs.get("type", "")
        time_s = float(attrs.get("time", "-1"))
        if event_type == "departure" and start_s <= time_s < end_s:
            person_id = attrs.get("person", "")
            if person_id and not is_transit_driver(person_id):
                if person_id not in seen_people:
                    seen_people.add(person_id)
                    people.add(person_id)
                    counts["candidate_people"] += 1
        elif event_type == "vehicle enters traffic" and start_s <= time_s < end_s:
            vehicle_id = attrs.get("vehicle", "")
            if vehicle_id:
                category = classify_vehicle(vehicle_id, transit)
                key = vehicle_trip_key(vehicle_id, time_s)
                vehicles[category].add(key)
                counts[f"candidate_{category}_trips"] += 1
    return (
        people.selected(),
        {category: sampler.selected() for category, sampler in vehicles.items()},
        counts,
    )


def append_point(
    points: list[tuple[float, float, float]],
    lonlat: tuple[float, float] | None,
    time_s: float,
) -> None:
    if lonlat is None:
        return
    lon, lat = lonlat
    if points:
        last_lon, last_lat, last_time = points[-1]
        if time_s <= last_time:
            time_s = last_time + 0.001
        if abs(last_lon - lon) < 1e-8 and abs(last_lat - lat) < 1e-8:
            if time_s - last_time < 2:
                points[-1] = (lon, lat, time_s)
                return
    points.append((lon, lat, time_s))


def link_point(
    network: Network, link_id: str, at_to_node: bool = False
) -> tuple[float, float] | None:
    link = network.links.get(link_id)
    if link is None:
        return None
    node_id = link.to_node if at_to_node else link.from_node
    return network.nodes_lonlat.get(node_id)


def reconstruct_tracks(
    events_path: pathlib.Path,
    network: Network,
    transit: dict[str, str],
    selected_people: set[str],
    selected_vehicle_trips: dict[str, set[str]],
    start_s: float,
    end_s: float,
) -> tuple[dict[str, list[Track]], list[RawStreetSegment], Counter[str]]:
    tracks: dict[str, list[Track]] = {category: [] for category in CATEGORIES}
    active_display: dict[str, Track] = {}
    display_keys: dict[str, str] = {}
    vehicle_positions: dict[str, tuple[float, float, float, str]] = {}
    onboard: dict[str, set[str]] = defaultdict(set)
    pending_legs: dict[str, PendingLeg] = {}
    last_alight: dict[str, tuple[str, float]] = {}
    person_vehicle: dict[str, str] = {}
    street_segments: list[RawStreetSegment] = []
    counts: Counter[str] = Counter()

    def finish_display(vehicle_id: str) -> None:
        track = active_display.pop(vehicle_id, None)
        display_keys.pop(vehicle_id, None)
        if track is not None and len(track.points) >= 2:
            tracks[track.category].append(track)

    for attrs in iter_event_attributes(events_path):
        event_type = attrs.get("type", "")
        time_s = float(attrs.get("time", "-1"))
        if time_s > end_s + 7200:
            continue

        if event_type == "vehicle enters traffic":
            vehicle_id = attrs.get("vehicle", "")
            link_id = attrs.get("link", "")
            if not vehicle_id:
                continue
            category = classify_vehicle(vehicle_id, transit)
            point = link_point(network, link_id)
            if point is not None:
                vehicle_positions[vehicle_id] = (*point, time_s, link_id)
            key = vehicle_trip_key(vehicle_id, time_s)
            if key in selected_vehicle_trips.get(category, set()):
                finish_display(vehicle_id)
                track = Track(key, category, category)
                append_point(track.points, point, time_s)
                active_display[vehicle_id] = track
                display_keys[vehicle_id] = key
            continue

        if event_type in {"entered link", "left link", "vehicle leaves traffic"}:
            vehicle_id = attrs.get("vehicle", "")
            link_id = attrs.get("link", "")
            at_to = event_type != "entered link"
            point = link_point(network, link_id, at_to_node=at_to)
            if vehicle_id and point is not None:
                vehicle_positions[vehicle_id] = (*point, time_s, link_id)
                track = active_display.get(vehicle_id)
                if track is not None:
                    append_point(track.points, point, time_s)
            if event_type == "vehicle leaves traffic" and vehicle_id:
                for person_id in list(onboard.get(vehicle_id, ())):
                    position = vehicle_positions.get(vehicle_id)
                    if position is not None:
                        last_alight[person_id] = (position[3], time_s)
                    person_vehicle.pop(person_id, None)
                    counts["person_vehicle_left_before_alight"] += 1
                onboard.pop(vehicle_id, None)
                finish_display(vehicle_id)
            continue

        person_id = attrs.get("person", "")
        if not person_id or person_id not in selected_people:
            continue

        if event_type == "departure":
            pending_legs[person_id] = PendingLeg(
                attrs.get("legMode", "walk"),
                attrs.get("link", ""),
                time_s,
            )
            counts[f"person_departure_{attrs.get('legMode', 'unknown')}"] += 1
        elif event_type in {"PersonEntersVehicle", "PersonEntersPtVehicle"}:
            vehicle_id = attrs.get("vehicle", "")
            if not vehicle_id:
                continue
            if person_vehicle.get(person_id) == vehicle_id:
                counts["duplicate_board_event"] += 1
                continue
            position = vehicle_positions.get(vehicle_id)
            pending = pending_legs.pop(person_id, None)
            if pending is not None and position is not None:
                street_segments.append(
                    RawStreetSegment(
                        person_id,
                        "access_walk",
                        pending.link_id,
                        position[3],
                        pending.start_s,
                        time_s,
                    )
                )
            category = classify_vehicle(vehicle_id, transit)
            onboard[vehicle_id].add(person_id)
            person_vehicle[person_id] = vehicle_id
            counts[f"person_board_{category}"] += 1
            counts["person_onboard_hidden"] += 1
        elif event_type in {"PersonLeavesVehicle", "PersonLeavesPtVehicle"}:
            vehicle_id = attrs.get("vehicle", "")
            if person_vehicle.get(person_id) != vehicle_id:
                counts["duplicate_or_unmatched_alight_event"] += 1
                continue
            position = vehicle_positions.get(vehicle_id)
            if position is not None:
                last_alight[person_id] = (position[3], time_s)
            onboard.get(vehicle_id, set()).discard(person_id)
            person_vehicle.pop(person_id, None)
            counts[f"person_alight_{classify_vehicle(vehicle_id, transit)}"] += 1
        elif event_type == "arrival":
            end_link = attrs.get("link", "")
            pending = pending_legs.pop(person_id, None)
            alight = last_alight.pop(person_id, None)
            if pending is not None:
                street_segments.append(
                    RawStreetSegment(
                        person_id,
                        pending.mode or "walk",
                        pending.link_id,
                        end_link,
                        pending.start_s,
                        time_s,
                    )
                )
            elif alight is not None:
                street_segments.append(
                    RawStreetSegment(
                        person_id,
                        "egress_walk",
                        alight[0],
                        end_link,
                        alight[1],
                        time_s,
                    )
                )

    for vehicle_id in list(active_display):
        finish_display(vehicle_id)
    return tracks, street_segments, counts


def astar_nodes(
    network: Network,
    start: str,
    target: str,
    max_expansions: int,
) -> list[str] | None:
    if start == target:
        return [start]
    target_xy = network.nodes_xy.get(target)
    if target_xy is None:
        return None

    def heuristic(node_id: str) -> float:
        xy = network.nodes_xy.get(node_id)
        if xy is None:
            return 0.0
        return math.hypot(xy[0] - target_xy[0], xy[1] - target_xy[1])

    queue: list[tuple[float, float, str]] = [(heuristic(start), 0.0, start)]
    came_from: dict[str, str] = {}
    best = {start: 0.0}
    expansions = 0
    while queue and expansions < max_expansions:
        _, cost, node_id = heapq.heappop(queue)
        if cost != best.get(node_id):
            continue
        if node_id == target:
            path = [target]
            while path[-1] != start:
                path.append(came_from[path[-1]])
            path.reverse()
            return path
        expansions += 1
        for next_id, length in network.walk_adjacency.get(node_id, ()):
            new_cost = cost + length
            if new_cost < best.get(next_id, math.inf):
                best[next_id] = new_cost
                came_from[next_id] = node_id
                heapq.heappush(
                    queue, (new_cost + heuristic(next_id), new_cost, next_id)
                )
    return None


def path_with_times(
    network: Network,
    node_ids: list[str],
    start_s: float,
    end_s: float,
) -> list[tuple[float, float, float]]:
    coords = [
        (network.nodes_xy[node_id], network.nodes_lonlat[node_id])
        for node_id in node_ids
        if node_id in network.nodes_xy and node_id in network.nodes_lonlat
    ]
    if len(coords) < 2:
        return []
    cumulative = [0.0]
    for previous, current in zip(coords, coords[1:]):
        cumulative.append(
            cumulative[-1]
            + math.hypot(
                current[0][0] - previous[0][0],
                current[0][1] - previous[0][1],
            )
        )
    total = cumulative[-1]
    if total <= 0:
        return []
    duration = max(1.0, end_s - start_s)
    return [
        (lonlat[0], lonlat[1], start_s + duration * distance / total)
        for (_, lonlat), distance in zip(coords, cumulative)
    ]


def snap_to_walk_network(
    network: Network,
    node_id: str,
    max_distance_m: float,
    minimum_component_size: int = 100,
) -> tuple[str | None, float]:
    component = network.walk_components.get(node_id)
    if (
        component is not None
        and network.walk_component_sizes.get(component, 0) >= minimum_component_size
    ):
        return node_id, 0.0
    xy = network.nodes_xy.get(node_id)
    if xy is None:
        return None, math.inf
    cell_size = 500.0
    radius = max(1, math.ceil(max_distance_m / cell_size))
    cell_x = math.floor(xy[0] / cell_size)
    cell_y = math.floor(xy[1] / cell_size)
    best_node = None
    best_distance = max_distance_m
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            for candidate in network.walk_spatial_index.get(
                (cell_x + dx, cell_y + dy), ()
            ):
                candidate_component = network.walk_components[candidate]
                if (
                    network.walk_component_sizes.get(candidate_component, 0)
                    < minimum_component_size
                ):
                    continue
                candidate_xy = network.nodes_xy[candidate]
                distance = math.hypot(
                    candidate_xy[0] - xy[0], candidate_xy[1] - xy[1]
                )
                if distance < best_distance:
                    best_node = candidate
                    best_distance = distance
    return best_node, best_distance


def build_street_tracks(
    segments: list[RawStreetSegment],
    network: Network,
    max_expansions: int,
    max_snap_distance_m: float,
) -> tuple[list[Track], Counter[str]]:
    tracks: list[Track] = []
    counts: Counter[str] = Counter()
    route_cache: dict[tuple[str, str], list[str] | None] = {}
    for index, segment in enumerate(segments):
        if segment.end_s <= segment.start_s:
            counts["invalid_time"] += 1
            continue
        start_link = network.links.get(segment.start_link)
        end_link = network.links.get(segment.end_link)
        if start_link is None or end_link is None:
            counts["missing_link"] += 1
            continue
        start_node, start_snap_distance = snap_to_walk_network(
            network, start_link.to_node, max_snap_distance_m
        )
        end_node, end_snap_distance = snap_to_walk_network(
            network, end_link.from_node, max_snap_distance_m
        )
        if start_node is None or end_node is None:
            counts["unroutable_no_nearby_road"] += 1
            continue
        if start_snap_distance > 0:
            counts["snapped_start"] += 1
        if end_snap_distance > 0:
            counts["snapped_end"] += 1
        start_component = network.walk_components.get(start_node)
        end_component = network.walk_components.get(end_node)
        if (
            start_component is None
            or end_component is None
            or start_component != end_component
        ):
            counts["unroutable_disconnected"] += 1
            continue
        key = (start_node, end_node)
        if key not in route_cache:
            route_cache[key] = astar_nodes(
                network, key[0], key[1], max_expansions
            )
        node_ids = route_cache[key]
        if not node_ids:
            counts["unroutable_search_limit"] += 1
            continue
        node_ids = [start_link.from_node, *node_ids, end_link.to_node]
        counts["street_routed"] += 1
        points = path_with_times(
            network, node_ids, segment.start_s, segment.end_s
        )
        if len(points) >= 2:
            tracks.append(
                Track(
                    f"{segment.person_id}|street|{index}",
                    "person",
                    segment.detail,
                    points,
                )
            )
    return tracks, counts


def perpendicular_distance(
    point: tuple[float, float, float],
    start: tuple[float, float, float],
    end: tuple[float, float, float],
) -> float:
    lat_scale = 111320.0
    lon_scale = lat_scale * math.cos(math.radians(point[1]))
    px, py = point[0] * lon_scale, point[1] * lat_scale
    x1, y1 = start[0] * lon_scale, start[1] * lat_scale
    x2, y2 = end[0] * lon_scale, end[1] * lat_scale
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    ratio = max(
        0.0,
        min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)),
    )
    return math.hypot(px - (x1 + ratio * dx), py - (y1 + ratio * dy))


def simplify_points(
    points: list[tuple[float, float, float]],
    tolerance_m: float,
) -> list[tuple[float, float, float]]:
    if len(points) <= 2:
        return points
    keep = {0, len(points) - 1}
    stack = [(0, len(points) - 1)]
    while stack:
        start, end = stack.pop()
        distance, candidate = -1.0, -1
        for index in range(start + 1, end):
            value = perpendicular_distance(points[index], points[start], points[end])
            if value > distance:
                distance, candidate = value, index
        if candidate >= 0 and distance > tolerance_m:
            keep.add(candidate)
            stack.extend(((start, candidate), (candidate, end)))
    return [points[index] for index in sorted(keep)]


def cap_points(
    points: list[tuple[float, float, float]], max_points: int
) -> list[tuple[float, float, float]]:
    if len(points) <= max_points:
        return points
    indices = {
        round(index * (len(points) - 1) / (max_points - 1))
        for index in range(max_points)
    }
    return [points[index] for index in sorted(indices)]


def compact_track(track: Track, max_points: int) -> dict | None:
    tolerance = {
        "person": 4.0,
        "car": 10.0,
        "bus": 7.0,
        "rail": 3.0,
        "ferry": 3.0,
    }[track.category]
    points = cap_points(simplify_points(track.points, tolerance), max_points)
    if len(points) < 2 or points[-1][2] - points[0][2] < 1:
        return None
    return {
        "i": track.track_id,
        "d": track.detail,
        "p": [
            [round(lon, 6), round(lat, 6), round(time_s, 1)]
            for lon, lat, time_s in points
        ],
    }


def write_data(
    output_dir: pathlib.Path,
    tracks: dict[str, list[Track]],
    args: argparse.Namespace,
    metadata: dict,
) -> dict[str, int]:
    compact: dict[str, list[dict]] = {}
    counts: dict[str, int] = {}
    for category in CATEGORIES:
        max_points = (
            args.max_person_points
            if category == "person"
            else args.max_vehicle_points
        )
        values = [
            result
            for track in tracks[category]
            if (result := compact_track(track, max_points)) is not None
        ]
        compact[category] = values
        counts[category] = len(values)
    payload = {
        "meta": metadata,
        "tracks": compact,
    }
    destination = output_dir / "particle_data.js"
    destination.write_text(
        "window.HK_PARTICLE_DATA="
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )
    with destination.open("rb") as source, gzip.open(
        output_dir / "particle_data.js.gz", "wb", compresslevel=9
    ) as target:
        shutil.copyfileobj(source, target)
    return counts


def write_html(output_dir: pathlib.Path) -> None:
    html = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Hong Kong MATSim Multimodal Particle Flow</title>
  <link rel="stylesheet" href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css">
  <style>
    *{box-sizing:border-box}html,body,#map{width:100%;height:100%;margin:0}
    body{overflow:hidden;background:#090b0e;color:#f4f5f6;font:14px/1.35 system-ui,-apple-system,"Segoe UI",sans-serif}
    #map{position:absolute;inset:0}.panel{position:absolute;z-index:5;background:rgba(16,18,21,.9);border:1px solid rgba(255,255,255,.15);border-radius:6px;backdrop-filter:blur(10px)}
    #controls{top:12px;left:12px;right:12px;display:flex;align-items:center;gap:10px;padding:9px 10px;min-height:48px}
    button,select{height:30px;border:1px solid rgba(255,255,255,.2);border-radius:4px;background:#25282d;color:#fff;padding:0 9px}
    button{width:34px;padding:0;font-size:16px;cursor:pointer}button:hover,select:hover{background:#34383e}
    #time{font-variant-numeric:tabular-nums;min-width:58px;font-weight:500}
    #timeline{flex:1;min-width:120px;accent-color:#f5f5f5}
    .mode{display:flex;align-items:center;gap:5px;white-space:nowrap}.mode input{accent-color:currentColor}
    .swatch{width:12px;height:12px;display:inline-grid;place-items:center;color:var(--c);font-size:12px}
    #legend{left:12px;bottom:28px;padding:9px 11px;display:grid;gap:7px}
    #legend .row{display:grid;grid-template-columns:17px 65px auto;align-items:center;gap:5px}
    #legend .count{color:#c5c8cc;font-variant-numeric:tabular-nums;text-align:right}
    #status{right:12px;bottom:28px;padding:8px 10px;color:#d5d8db;font-variant-numeric:tabular-nums}
    #tip{position:absolute;z-index:8;display:none;pointer-events:none;padding:7px 9px;background:rgba(12,14,17,.94);border:1px solid rgba(255,255,255,.18);border-radius:4px;font-size:12px}
    @media(max-width:820px){#controls{align-items:flex-start;flex-wrap:wrap}.mode{font-size:12px}#timeline{order:10;flex-basis:100%}#legend{bottom:18px}#status{display:none}}
  </style>
</head>
<body>
<div id="map"></div>
<div id="controls" class="panel">
  <button id="play" type="button" title="Play or pause" aria-label="Play or pause">▶</button>
  <span id="time">05:00</span>
  <input id="timeline" type="range" aria-label="Simulation time">
  <select id="speed" aria-label="Playback speed">
    <option value="30">30×</option><option value="120" selected>120×</option>
    <option value="300">300×</option><option value="600">600×</option>
  </select>
  <label class="mode" style="color:#f7f2df"><input type="checkbox" data-mode="person" checked>People on foot</label>
  <label class="mode" style="color:#41c7ff"><input type="checkbox" data-mode="car" checked>Cars</label>
  <label class="mode" style="color:#ff9f43"><input type="checkbox" data-mode="bus" checked>Bus/GMB</label>
  <label class="mode" style="color:#5ee18a"><input type="checkbox" data-mode="rail" checked>Rail</label>
  <label class="mode" style="color:#e777ff"><input type="checkbox" data-mode="ferry" checked>Ferry</label>
  <button id="reset" type="button" title="Reset map" aria-label="Reset map">⌂</button>
</div>
<div id="legend" class="panel">
  <div class="row"><span class="swatch" style="--c:#f7f2df">●</span><span>On foot</span><span class="count" id="n-person">0</span></div>
  <div class="row"><span class="swatch" style="--c:#41c7ff">◆</span><span>Cars</span><span class="count" id="n-car">0</span></div>
  <div class="row"><span class="swatch" style="--c:#ff9f43">■</span><span>Bus/GMB</span><span class="count" id="n-bus">0</span></div>
  <div class="row"><span class="swatch" style="--c:#5ee18a">▬</span><span>Rail</span><span class="count" id="n-rail">0</span></div>
  <div class="row"><span class="swatch" style="--c:#e777ff">▲</span><span>Ferry</span><span class="count" id="n-ferry">0</span></div>
</div>
<div id="status" class="panel"></div><div id="tip"></div>
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<script src="https://unpkg.com/deck.gl@9.1.14/dist.min.js"></script>
<script src="particle_data.js"></script>
<script>
(() => {
  const DATA=window.HK_PARTICLE_DATA, meta=DATA.meta, colors={
    person:[247,242,223],car:[65,199,255],bus:[255,159,67],rail:[94,225,138],ferry:[231,119,255]
  }, widths={person:.7,car:1.7,bus:3.6,rail:5.2,ferry:6.4},
  trails={person:75,car:120,bus:210,rail:270,ferry:360},
  sizes={person:7,car:13,bus:18,rail:23,ferry:25};
  const start=meta.start_s,end=meta.end_s, slider=document.getElementById('timeline');
  slider.min=start;slider.max=end;slider.step=10;slider.value=Math.max(start,7.5*3600);
  let current=+slider.value,playing=false,last=performance.now(),speed=120;
  const visible={person:true,car:true,bus:true,rail:true,ferry:true};
  const map=new maplibregl.Map({container:'map',style:'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
    center:[114.17,22.32],zoom:10.25,pitch:42,bearing:-8,attributionControl:true});
  map.addControl(new maplibregl.NavigationControl({showCompass:true}),'top-right');
  const overlay=new deck.MapboxOverlay({interleaved:true,layers:[]});
  map.on('load',()=>{map.addControl(overlay);render();});

  function makeAtlas(){
    const c=document.createElement('canvas');c.width=320;c.height=64;const x=c.getContext('2d');
    x.lineWidth=3;x.strokeStyle='rgba(8,10,12,.9)';
    function at(i,draw){x.save();x.translate(i*64+32,32);draw(x);x.fill();x.stroke();x.restore()}
    x.fillStyle='#f7f2df';at(0,q=>q.arc(0,0,8,0,Math.PI*2));
    x.fillStyle='#41c7ff';at(1,q=>{q.beginPath();q.moveTo(18,0);q.lineTo(-11,-9);q.lineTo(-17,0);q.lineTo(-11,9);q.closePath()});
    x.fillStyle='#ff9f43';at(2,q=>{q.beginPath();q.roundRect(-21,-11,42,22,5)});
    x.fillStyle='#5ee18a';at(3,q=>{q.beginPath();q.roundRect(-25,-8,50,16,8)});
    x.fillStyle='#e777ff';at(4,q=>{q.beginPath();q.moveTo(24,0);q.lineTo(-16,-14);q.lineTo(-8,0);q.lineTo(-16,14);q.closePath()});
    return c
  }
  const atlas=makeAtlas(),mapping={person:{x:0,y:0,width:64,height:64,anchorX:32,anchorY:32},
    car:{x:64,y:0,width:64,height:64,anchorX:32,anchorY:32},bus:{x:128,y:0,width:64,height:64,anchorX:32,anchorY:32},
    rail:{x:192,y:0,width:64,height:64,anchorX:32,anchorY:32},ferry:{x:256,y:0,width:64,height:64,anchorX:32,anchorY:32}};
  function locate(track,t){
    const p=track.p;if(t<p[0][2]||t>p[p.length-1][2])return null;
    let lo=0,hi=p.length-1;while(lo+1<hi){const m=(lo+hi)>>1;if(p[m][2]<=t)lo=m;else hi=m}
    const a=p[lo],b=p[hi],dt=Math.max(.001,b[2]-a[2]),r=Math.max(0,Math.min(1,(t-a[2])/dt));
    const lon=a[0]+(b[0]-a[0])*r,lat=a[1]+(b[1]-a[1])*r;
    const angle=90-Math.atan2(b[1]-a[1],b[0]-a[0])*180/Math.PI;
    return {position:[lon,lat],angle,mode:null,id:track.i,detail:track.d}
  }
  function layers(){
    const out=[],icons=[],counts={person:0,car:0,bus:0,rail:0,ferry:0};
    for(const mode of Object.keys(DATA.tracks)){
      if(!visible[mode])continue;const data=DATA.tracks[mode];
      out.push(new deck.TripsLayer({id:'trail-'+mode,data,getPath:d=>d.p.map(q=>[q[0],q[1]]),
        getTimestamps:d=>d.p.map(q=>q[2]),getColor:colors[mode],opacity:mode==='person'?.42:.72,
        widthMinPixels:widths[mode],jointRounded:true,capRounded:true,trailLength:trails[mode],currentTime:current}));
      for(const track of data){const p=locate(track,current);if(p){p.mode=mode;icons.push(p);counts[mode]++}}
    }
    out.push(new deck.IconLayer({id:'moving-particles',data:icons,iconAtlas:atlas,iconMapping:mapping,
      getIcon:d=>d.mode,getPosition:d=>d.position,getAngle:d=>d.angle,getSize:d=>sizes[d.mode],
      sizeUnits:'pixels',pickable:true,onHover:info=>showTip(info)}));
    for(const mode of Object.keys(counts))document.getElementById('n-'+mode).textContent=counts[mode].toLocaleString();
    document.getElementById('status').textContent=icons.length.toLocaleString()+' active particles';
    return out
  }
  function showTip(info){
    const tip=document.getElementById('tip');if(!info.object){tip.style.display='none';return}
    tip.style.display='block';tip.style.left=(info.x+12)+'px';tip.style.top=(info.y+12)+'px';
    tip.textContent=info.object.mode.toUpperCase()+' · '+info.object.detail;
  }
  function clock(t){const h=Math.floor(t/3600),m=Math.floor((t%3600)/60);return String(h).padStart(2,'0')+':'+String(m).padStart(2,'0')}
  function render(){document.getElementById('time').textContent=clock(current);slider.value=current;overlay.setProps({layers:layers()})}
  function frame(now){if(playing){current+=(now-last)/1000*speed;if(current>end)current=start;render()}last=now;requestAnimationFrame(frame)}
  document.getElementById('play').onclick=()=>{playing=!playing;document.getElementById('play').textContent=playing?'⏸':'▶'};
  document.getElementById('speed').onchange=e=>speed=+e.target.value;
  slider.oninput=e=>{current=+e.target.value;render()};
  document.querySelectorAll('[data-mode]').forEach(e=>e.onchange=()=>{visible[e.dataset.mode]=e.checked;render()});
  document.getElementById('reset').onclick=()=>map.flyTo({center:[114.17,22.32],zoom:10.25,pitch:42,bearing:-8});
  requestAnimationFrame(frame);
})();
</script>
</body>
</html>
"""
    (output_dir / "index.html").write_text(html, encoding="utf-8")


def main() -> None:
    args = parse_args()
    for path in (args.events, args.network, args.transit_vehicles):
        if not path.is_file():
            raise FileNotFoundError(path)
    output_dir = args.output_dir.resolve()
    if output_dir.exists():
        raise FileExistsError(output_dir)
    output_dir.mkdir(parents=True)
    start_s = args.start_hour * 3600.0
    end_s = args.end_hour * 3600.0
    quotas = {
        "person": args.people,
        "car": args.cars,
        "bus": args.buses,
        "rail": args.rail,
        "ferry": args.ferries,
    }

    print("Reading network and transit vehicle categories...", flush=True)
    network = read_network(args.network)
    transit = read_transit_vehicle_categories(args.transit_vehicles)
    print(
        f"nodes={len(network.nodes_xy)} links={len(network.links)} "
        f"transit_vehicles={len(transit)}",
        flush=True,
    )

    print("Pass 1/2: deterministic stratified sampling...", flush=True)
    people, vehicle_trips, candidate_counts = select_samples(
        args.events, transit, start_s, end_s, quotas
    )
    print(
        "selected_people="
        f"{len(people)} selected_vehicle_trips="
        + json.dumps(
            {category: len(values) for category, values in vehicle_trips.items()},
            sort_keys=True,
        ),
        flush=True,
    )

    print("Pass 2/2: reconstructing person and vehicle trajectories...", flush=True)
    tracks, street_segments, event_counts = reconstruct_tracks(
        args.events,
        network,
        transit,
        people,
        vehicle_trips,
        start_s,
        end_s,
    )
    street_tracks, street_counts = build_street_tracks(
        street_segments,
        network,
        args.max_walk_route_expansions,
        args.max_walk_snap_distance,
    )
    tracks["person"].extend(street_tracks)

    metadata = {
        "start_s": start_s,
        "end_s": end_s,
        "source_events": str(args.events),
        "source_network": str(args.network),
        "sample_quotas": quotas,
        "candidate_counts": dict(candidate_counts),
        "event_counts": dict(event_counts),
        "street_routing": dict(street_counts),
    }
    track_counts = write_data(output_dir, tracks, args, metadata)
    write_html(output_dir)
    summary = {
        **metadata,
        "network": {
            "nodes": len(network.nodes_xy),
            "links": len(network.links),
            "walk_nodes": len(network.walk_adjacency),
            "walk_components": len(network.walk_component_sizes),
            "transit_vehicles": len(transit),
        },
        "output_track_counts": track_counts,
        "raw_track_counts": {
            category: len(values) for category, values in tracks.items()
        },
        "files": {
            path.name: path.stat().st_size
            for path in output_dir.iterdir()
            if path.is_file()
        },
        "notes": [
            "Vehicle motion follows MATSim link enter/leave events.",
            "People are hidden while onboard; the matching vehicle particle represents their movement.",
            "Access, egress, walk, and ride segments are shown only when routed on the road graph.",
            "Unroutable person segments are audited and never drawn as straight lines.",
            "This is a deterministic visualization sample, not a demand rescaling.",
        ],
    }
    (output_dir / "particle_flow_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("track_counts=" + json.dumps(track_counts, sort_keys=True), flush=True)
    print(f"output={output_dir}", flush=True)


if __name__ == "__main__":
    main()
