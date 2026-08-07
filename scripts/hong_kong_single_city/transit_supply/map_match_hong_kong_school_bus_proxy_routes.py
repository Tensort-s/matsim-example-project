#!/usr/bin/env python3
"""Convert inferred Hong Kong school-bus chains to road-aligned paths.

Inferred route membership and demand are preserved. Pickup order is improved
with a deterministic farthest-start nearest-neighbour and 2-opt proxy. Each
pickup representative point and school campus is snapped to the nearest MATSim
physical-road node, then consecutive waypoints are connected by shortest paths
on links allowing ``car``. Bus-only links are excluded because they are
duplicated public-transport route layers, not the base street graph. A
reverse-direction road-topology fallback is permitted only when the
directed graph has no path and is explicitly recorded. First-party locked
routes remain geometry-null: their published names are evidence, not a licence
to invent stop coordinates or alignments.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import heapq
import json
import math
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import geopandas as gpd
import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection
from pyproj import Transformer
from scipy.spatial import cKDTree
from shapely.geometry import LineString, mapping


REPO_ROOT = Path(__file__).resolve().parents[3]
FORMAL_ROOT = Path(r"F:\Matsim\matsim-example-project")
PROJECT_ROOT = FORMAL_ROOT if FORMAL_ROOT.exists() else REPO_ROOT
DEFAULT_PROXY_DIR = (
    REPO_ROOT
    / "data"
    / "school"
    / "hongkong"
    / "processed"
    / "school_bus_proxy_routes_2026_v3_school_probability_locked76"
)
DEFAULT_NETWORK = (
    PROJECT_ROOT
    / "data"
    / "transit"
    / "hongkong"
    / "processed"
    / "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_ferry_core_v1_cap010"
    / "network.xml.gz"
)
DEFAULT_CAMPUSES = (
    PROJECT_ROOT
    / "data"
    / "school"
    / "hongkong"
    / "processed"
    / "student_school_od_2022"
    / "school_campus_capacity_estimates.geojson"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "data"
    / "school"
    / "hongkong"
    / "processed"
    / "school_bus_proxy_routes_2026_v4_road_matched"
)
TARGET_CRS = "EPSG:32650"
ROAD_MODES = {"car"}
NO_PATH = "no_path"


@dataclass(frozen=True)
class RoadEdge:
    to_node: int
    length_m: float
    link_id: str


@dataclass
class RoadGraph:
    node_ids: list[str]
    coordinates: np.ndarray
    directed: list[list[RoadEdge]]
    undirected: list[list[RoadEdge]]
    edge_count: int
    selected_link_modes: Counter[str]
    visual_segments: list[tuple[tuple[float, float], tuple[float, float], float]]
    topology_connector_count: int
    routable_node_indices: np.ndarray


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    return round(float(np.percentile(np.asarray(values, dtype=float), q)), 3)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def parse_network(path: Path) -> RoadGraph:
    """Read the active MATSim network and retain the physical car-road layer."""
    opener = gzip.open if path.suffix == ".gz" else open
    nodes: dict[str, tuple[float, float]] = {}
    selected: dict[tuple[str, str], tuple[float, str, str, float]] = {}
    mode_counts: Counter[str] = Counter()
    with opener(path, "rb") as handle:
        for _event, element in ET.iterparse(handle, events=("end",)):
            tag = element.tag.rsplit("}", 1)[-1]
            if tag == "node":
                nodes[element.attrib["id"]] = (
                    float(element.attrib["x"]),
                    float(element.attrib["y"]),
                )
            elif tag == "link":
                modes_text = element.attrib.get("modes", "")
                modes = {part.strip() for part in modes_text.split(",") if part.strip()}
                if not modes.intersection(ROAD_MODES):
                    element.clear()
                    continue
                from_id = element.attrib["from"]
                to_id = element.attrib["to"]
                length = max(float(element.attrib.get("length", "0")), 0.01)
                capacity = safe_float(element.attrib.get("capacity"), 0.0)
                key = (from_id, to_id)
                old = selected.get(key)
                if old is None or length < old[0]:
                    selected[key] = (length, element.attrib["id"], modes_text, capacity)
                mode_counts[modes_text] += 1
            element.clear()

    used_ids = sorted({node_id for edge in selected for node_id in edge})
    missing = [node_id for node_id in used_ids if node_id not in nodes]
    if missing:
        raise ValueError(f"Network has {len(missing)} selected-link nodes without coordinates")
    node_index = {node_id: idx for idx, node_id in enumerate(used_ids)}
    coordinates = np.asarray([nodes[node_id] for node_id in used_ids], dtype=float)
    directed: list[list[RoadEdge]] = [[] for _ in used_ids]
    undirected: list[list[RoadEdge]] = [[] for _ in used_ids]
    visual_segments: list[tuple[tuple[float, float], tuple[float, float], float]] = []
    for (from_id, to_id), (length, link_id, _modes, capacity) in selected.items():
        from_idx = node_index[from_id]
        to_idx = node_index[to_id]
        edge = RoadEdge(to_idx, length, link_id)
        directed[from_idx].append(edge)
        undirected[from_idx].append(edge)
        undirected[to_idx].append(RoadEdge(from_idx, length, link_id))
        visual_segments.append((nodes[from_id], nodes[to_id], capacity))

    # TNM carriageways and intersection arms can terminate a few metres apart
    # while representing the same physical road system. Add the minimum set of
    # <=10 m bidirectional topology connectors needed to join such components.
    parent = list(range(len(used_ids)))
    size = [1] * len(used_ids)

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(a: int, b: int) -> bool:
        a_root = find(a)
        b_root = find(b)
        if a_root == b_root:
            return False
        if size[a_root] < size[b_root]:
            a_root, b_root = b_root, a_root
        parent[b_root] = a_root
        size[a_root] += size[b_root]
        return True

    for from_idx, adjacency in enumerate(undirected):
        for edge in adjacency:
            union(from_idx, edge.to_node)
    nearby_pairs = cKDTree(coordinates).query_pairs(10.0, output_type="ndarray")
    if len(nearby_pairs):
        pair_delta = coordinates[nearby_pairs[:, 0]] - coordinates[nearby_pairs[:, 1]]
        pair_distance = np.hypot(pair_delta[:, 0], pair_delta[:, 1])
        order = np.argsort(pair_distance)
    else:
        pair_distance = np.asarray([], dtype=float)
        order = np.asarray([], dtype=int)
    topology_connector_count = 0
    for pair_index in order:
        a, b = (int(value) for value in nearby_pairs[pair_index])
        if not union(a, b):
            continue
        topology_connector_count += 1
        length = max(float(pair_distance[pair_index]), 0.01)
        link_id = f"school_bus_topology_connector_{topology_connector_count:04d}"
        directed[a].append(RoadEdge(b, length, link_id))
        directed[b].append(RoadEdge(a, length, link_id))
        undirected[a].append(RoadEdge(b, length, link_id))
        undirected[b].append(RoadEdge(a, length, link_id))
        visual_segments.append((tuple(coordinates[a]), tuple(coordinates[b]), 0.0))
    component_sizes = Counter(find(index) for index in range(len(used_ids)))
    largest_component = component_sizes.most_common(1)[0][0]
    routable_node_indices = np.asarray(
        [index for index in range(len(used_ids)) if find(index) == largest_component],
        dtype=int,
    )
    return RoadGraph(
        node_ids=used_ids,
        coordinates=coordinates,
        directed=directed,
        undirected=undirected,
        edge_count=len(selected),
        selected_link_modes=mode_counts,
        visual_segments=visual_segments,
        topology_connector_count=topology_connector_count,
        routable_node_indices=routable_node_indices,
    )


def astar_path(
    graph: RoadGraph,
    source: int,
    target: int,
    directed: bool,
) -> tuple[list[int], list[str], float] | None:
    if source == target:
        return [source], [], 0.0
    adjacency = graph.directed if directed else graph.undirected
    target_xy = graph.coordinates[target]
    queue: list[tuple[float, float, int]] = [(0.0, 0.0, source)]
    distance: dict[int, float] = {source: 0.0}
    predecessor: dict[int, tuple[int, str]] = {}
    visited: set[int] = set()
    while queue:
        _score, current_distance, node = heapq.heappop(queue)
        if node in visited:
            continue
        visited.add(node)
        if node == target:
            node_path = [target]
            link_path: list[str] = []
            while node_path[-1] != source:
                previous, link_id = predecessor[node_path[-1]]
                link_path.append(link_id)
                node_path.append(previous)
            node_path.reverse()
            link_path.reverse()
            return node_path, link_path, current_distance
        for edge in adjacency[node]:
            candidate = current_distance + edge.length_m
            if candidate >= distance.get(edge.to_node, math.inf):
                continue
            distance[edge.to_node] = candidate
            predecessor[edge.to_node] = (node, edge.link_id)
            delta = graph.coordinates[edge.to_node] - target_xy
            heuristic = float(math.hypot(delta[0], delta[1]))
            heapq.heappush(queue, (candidate + heuristic, candidate, edge.to_node))
    return None


def optimise_pickup_order(
    graph: RoadGraph,
    pickup_nodes: list[int],
    pickup_labels: list[str],
    school_node: int,
) -> tuple[list[int], list[str], float]:
    """Create a compact inbound order with a fixed school endpoint.

    Repeated pickups snapped to the same node are collapsed for geometry. The
    start is the pickup farthest from school, followed by nearest-neighbour
    ordering and a deterministic 2-opt refinement. This changes only inferred
    proxy ordering; it never edits the locked first-party records.
    """
    unique: dict[int, str] = {}
    for node, label in zip(pickup_nodes, pickup_labels):
        unique.setdefault(node, label)
    nodes = list(unique)
    labels = unique
    if not nodes:
        return [school_node], [f"campus_node:{graph.node_ids[school_node]}"], 0.0
    school_xy = graph.coordinates[school_node]
    start = max(nodes, key=lambda node: float(np.linalg.norm(graph.coordinates[node] - school_xy)))
    order = [start]
    remaining = set(nodes)
    remaining.remove(start)
    while remaining:
        current_xy = graph.coordinates[order[-1]]
        next_node = min(
            remaining,
            key=lambda node: (
                float(np.linalg.norm(graph.coordinates[node] - current_xy)),
                graph.node_ids[node],
            ),
        )
        order.append(next_node)
        remaining.remove(next_node)

    def chain_length(candidate: list[int]) -> float:
        chain = candidate + [school_node]
        return float(
            sum(
                np.linalg.norm(graph.coordinates[b] - graph.coordinates[a])
                for a, b in zip(chain, chain[1:])
            )
        )

    best_length = chain_length(order)
    for _pass in range(4):
        improved = False
        for left in range(1, max(1, len(order) - 1)):
            for right in range(left + 1, len(order)):
                candidate = order[:left] + list(reversed(order[left : right + 1])) + order[right + 1 :]
                candidate_length = chain_length(candidate)
                if candidate_length + 0.01 < best_length:
                    order = candidate
                    best_length = candidate_length
                    improved = True
        if not improved:
            break
    ordered_labels = [labels[node] for node in order] + [f"campus_node:{graph.node_ids[school_node]}"]
    return order + [school_node], ordered_labels, best_length


def load_inputs(proxy_dir: Path, campus_path: Path) -> tuple[pd.DataFrame, pd.DataFrame, gpd.GeoDataFrame]:
    routes = pd.read_csv(proxy_dir / "school_bus_proxy_routes.csv", dtype=str).fillna("")
    stops = pd.read_csv(proxy_dir / "school_bus_proxy_stops.csv", dtype=str).fillna("")
    campuses = gpd.read_file(campus_path)[["campus_id", "geometry"]].copy()
    campuses["campus_id"] = campuses["campus_id"].astype(str)
    campuses = campuses.to_crs(TARGET_CRS)
    if routes["route_id"].duplicated().any():
        raise ValueError("Route IDs are not unique")
    return routes, stops, campuses


def snap_waypoints(
    graph: RoadGraph,
    stops: pd.DataFrame,
    campuses: gpd.GeoDataFrame,
    inferred_routes: pd.DataFrame,
) -> tuple[dict[str, int], dict[str, int], list[dict[str, Any]]]:
    routable_coordinates = graph.coordinates[graph.routable_node_indices]
    tree = cKDTree(routable_coordinates)
    stop_points = (
        stops[["origin_grid_id", "x_epsg32650", "y_epsg32650"]]
        .drop_duplicates("origin_grid_id")
        .copy()
    )
    campus_ids = set(inferred_routes["campus_id"])
    campus_points = campuses[campuses["campus_id"].isin(campus_ids)].copy()
    missing_campuses = campus_ids.difference(set(campus_points["campus_id"]))
    if missing_campuses:
        raise ValueError(f"Missing {len(missing_campuses)} campus coordinates")

    stop_map: dict[str, int] = {}
    campus_map: dict[str, int] = {}
    rows: list[dict[str, Any]] = []
    for kind, frame in (("origin_grid", stop_points), ("campus", campus_points)):
        if kind == "origin_grid":
            keys = frame["origin_grid_id"].astype(str).tolist()
            coords = frame[["x_epsg32650", "y_epsg32650"]].astype(float).to_numpy()
        else:
            keys = frame["campus_id"].astype(str).tolist()
            coords = np.asarray([(geom.x, geom.y) for geom in frame.geometry], dtype=float)
        distances, local_indices = tree.query(coords, k=1)
        indices = graph.routable_node_indices[np.asarray(local_indices, dtype=int)]
        for key, source_xy, distance, node_idx in zip(keys, coords, distances, indices):
            node_idx = int(node_idx)
            if kind == "origin_grid":
                stop_map[key] = node_idx
            else:
                campus_map[key] = node_idx
            node_xy = graph.coordinates[node_idx]
            rows.append(
                {
                    "waypoint_kind": kind,
                    "waypoint_id": key,
                    "source_x_epsg32650": round(float(source_xy[0]), 3),
                    "source_y_epsg32650": round(float(source_xy[1]), 3),
                    "matched_node_id": graph.node_ids[node_idx],
                    "matched_x_epsg32650": round(float(node_xy[0]), 3),
                    "matched_y_epsg32650": round(float(node_xy[1]), 3),
                    "snap_distance_m": round(float(distance), 3),
                }
            )
    return stop_map, campus_map, rows


def assemble_routes(
    graph: RoadGraph,
    routes: pd.DataFrame,
    stops: pd.DataFrame,
    stop_map: dict[str, int],
    campus_map: dict[str, int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    to_wgs84 = Transformer.from_crs(TARGET_CRS, "EPSG:4326", always_xy=True)
    stop_groups = {
        route_id: group.sort_values("stop_order", key=lambda column: column.astype(int))
        for route_id, group in stops.groupby("route_id", sort=False)
    }
    snap_lookup = {
        ("origin_grid", key): graph.coordinates[index] for key, index in stop_map.items()
    }
    snap_lookup.update({("campus", key): graph.coordinates[index] for key, index in campus_map.items()})
    cache: dict[tuple[int, int], tuple[list[int], list[str], float, str] | None] = {}
    features: list[dict[str, Any]] = []
    route_rows: list[dict[str, Any]] = []
    segment_rows: list[dict[str, Any]] = []
    route_quality_counts: Counter[str] = Counter()
    total_directed = 0
    total_undirected = 0
    total_straight = 0
    total_topology_connectors = 0

    inferred = routes[routes["route_kind"] == "inferred_proxy"].copy()
    for route_number, route in enumerate(inferred.to_dict("records"), start=1):
        route_id = route["route_id"]
        group = stop_groups.get(route_id)
        if group is None or group.empty:
            raise ValueError(f"Inferred route {route_id} has no pickup stops")
        pickup_nodes = [stop_map[str(grid_id)] for grid_id in group["origin_grid_id"]]
        pickup_labels = [f"origin_grid:{value}" for value in group["origin_grid_id"]]
        school_node = campus_map[str(route["campus_id"])]
        collapsed_nodes, collapsed_labels, optimised_straight_m = optimise_pickup_order(
            graph,
            pickup_nodes,
            pickup_labels,
            school_node,
        )
        collapsed_labels[-1] = f"campus:{route['campus_id']}"

        full_nodes: list[int] = []
        road_length_m = 0.0
        directed_count = 0
        undirected_count = 0
        straight_count = 0
        route_topology_count = 0
        for sequence, (source, target) in enumerate(zip(collapsed_nodes, collapsed_nodes[1:]), start=1):
            key = (source, target)
            result = cache.get(key)
            if key not in cache:
                path = astar_path(graph, source, target, directed=True)
                quality = "directed_road"
                if path is None:
                    path = astar_path(graph, source, target, directed=False)
                    quality = "undirected_road_fallback"
                if path is not None and any(link_id.startswith("school_bus_topology_connector_") for link_id in path[1]):
                    quality += "_with_topology_connector"
                result = (*path, quality) if path is not None else None
                cache[key] = result
            if result is None:
                node_path = [source, target]
                link_path: list[str] = []
                delta = graph.coordinates[target] - graph.coordinates[source]
                segment_length = float(math.hypot(delta[0], delta[1]))
                quality = "straight_disconnected_fallback"
            else:
                node_path, link_path, segment_length, quality = result
            topology_count = sum(link_id.startswith("school_bus_topology_connector_") for link_id in link_path)
            if quality.startswith("directed_road"):
                directed_count += 1
            elif quality.startswith("undirected_road_fallback"):
                undirected_count += 1
            else:
                straight_count += 1
            total_topology_connectors += topology_count
            route_topology_count += topology_count
            road_length_m += segment_length
            full_nodes.extend(node_path if not full_nodes else node_path[1:])
            segment_rows.append(
                {
                    "route_id": route_id,
                    "segment_order": sequence,
                    "from_waypoint": collapsed_labels[sequence - 1],
                    "to_waypoint": collapsed_labels[sequence],
                    "from_node_id": graph.node_ids[source],
                    "to_node_id": graph.node_ids[target],
                    "path_quality": quality,
                    "path_length_m": round(segment_length, 3),
                    "network_link_count": len(link_path),
                    "topology_connector_count": topology_count,
                    "network_link_ids": "|".join(link_path),
                }
            )

        coords_projected = [tuple(graph.coordinates[index]) for index in full_nodes]
        if len(coords_projected) == 1:
            coords_projected.append(coords_projected[0])
        projected_line = LineString(coords_projected).simplify(3.0, preserve_topology=False)
        coords_wgs84 = [to_wgs84.transform(x, y) for x, y in projected_line.coords]
        line_wgs84 = LineString(coords_wgs84)
        if straight_count:
            route_quality = "road_with_straight_disconnected_fallback"
        elif undirected_count:
            route_quality = "road_with_undirected_fallback"
        elif route_topology_count:
            route_quality = "road_with_topology_connectors"
        else:
            route_quality = "road_directed"
        route_quality_counts[route_quality] += 1
        total_directed += directed_count
        total_undirected += undirected_count
        total_straight += straight_count
        original_km = safe_float(route.get("straight_line_chain_km"))
        optimised_straight_km = optimised_straight_m / 1000.0
        output = dict(route)
        output.update(
            {
                "road_path_km": round(road_length_m / 1000.0, 3),
                "original_to_optimised_straight_ratio": round(original_km / optimised_straight_km, 3)
                if optimised_straight_km > 0
                else "",
                "optimised_straight_chain_km": round(optimised_straight_km, 3),
                "road_to_optimised_straight_ratio": round(road_length_m / 1000.0 / optimised_straight_km, 3)
                if optimised_straight_km > 0
                else "",
                "pickup_order_method": "farthest_start_nearest_neighbour_2opt_proxy",
                "timing_status": "legacy_v3_times_not_recalculated_after_reordering",
                "road_node_count": len(full_nodes),
                "road_segment_count": len(collapsed_nodes) - 1,
                "directed_segment_count": directed_count,
                "undirected_fallback_segment_count": undirected_count,
                "straight_disconnected_segment_count": straight_count,
                "topology_connector_occurrence_count": route_topology_count,
                "route_path_quality": route_quality,
            }
        )
        route_rows.append(output)
        properties = dict(output)
        features.append({"type": "Feature", "properties": properties, "geometry": mapping(line_wgs84)})
        if route_number % 250 == 0:
            print(f"routed {route_number:,}/{len(inferred):,} inferred routes", flush=True)

    for route in routes[routes["route_kind"] == "first_party_locked"].to_dict("records"):
        output = dict(route)
        output.update(
            {
                "road_path_km": "",
                "original_to_optimised_straight_ratio": "",
                "optimised_straight_chain_km": "",
                "road_to_optimised_straight_ratio": "",
                "pickup_order_method": "first_party_locked_not_reordered",
                "timing_status": "first_party_locked_times_not_digitized",
                "road_node_count": 0,
                "road_segment_count": 0,
                "directed_segment_count": 0,
                "undirected_fallback_segment_count": 0,
                "straight_disconnected_segment_count": 0,
                "topology_connector_occurrence_count": 0,
                "route_path_quality": "first_party_locked_geometry_not_digitized",
            }
        )
        route_rows.append(output)
        features.append({"type": "Feature", "properties": output, "geometry": None})
        route_quality_counts[output["route_path_quality"]] += 1

    summary = {
        "inferred_route_count": len(inferred),
        "locked_route_count": int((routes["route_kind"] == "first_party_locked").sum()),
        "route_quality_counts": dict(route_quality_counts),
        "directed_segment_count": total_directed,
        "undirected_fallback_segment_count": total_undirected,
        "straight_disconnected_segment_count": total_straight,
        "topology_connector_occurrence_count": total_topology_connectors,
        "unique_segment_od_count": len(cache),
    }
    return features, segment_rows, {"route_rows": route_rows, **summary}


def write_static_map(
    path: Path,
    graph: RoadGraph,
    features: list[dict[str, Any]],
    original_geojson_path: Path,
) -> None:
    mpl.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
    mpl.rcParams["axes.unicode_minus"] = False
    inferred_features = [item for item in features if item["geometry"] is not None]
    projected_lines: list[np.ndarray] = []
    from_wgs84 = Transformer.from_crs("EPSG:4326", TARGET_CRS, always_xy=True)
    for item in inferred_features:
        coords = np.asarray(item["geometry"]["coordinates"], dtype=float)
        x, y = from_wgs84.transform(coords[:, 0], coords[:, 1])
        projected_lines.append(np.column_stack([x, y]))
    original = gpd.read_file(original_geojson_path).to_crs(TARGET_CRS)
    original = original[original.geometry.notna() & ~original.geometry.is_empty]

    road_segments = [np.asarray([start, end], dtype=float) for start, end, _capacity in graph.visual_segments]
    fig, axes = plt.subplots(1, 2, figsize=(15, 8), dpi=180, constrained_layout=True)
    titles = ["原始直线型候选路线", "道路网络匹配后的候选路径"]
    for axis, title in zip(axes, titles):
        axis.add_collection(LineCollection(road_segments, colors="#b7c0c8", linewidths=0.12, alpha=0.32))
        axis.set_title(title, fontsize=13, weight="bold")
        axis.set_aspect("equal")
        axis.axis("off")
    original_segments = []
    for geometry in original.geometry:
        if geometry.geom_type == "LineString":
            original_segments.append(np.asarray(geometry.coords))
    axes[0].add_collection(LineCollection(original_segments, colors="#d35f5f", linewidths=0.32, alpha=0.32))
    axes[1].add_collection(LineCollection(projected_lines, colors="#147d8f", linewidths=0.34, alpha=0.31))
    all_xy = graph.coordinates
    for axis in axes:
        axis.set_xlim(float(all_xy[:, 0].min()) - 1500, float(all_xy[:, 0].max()) + 1500)
        axis.set_ylim(float(all_xy[:, 1].min()) - 1500, float(all_xy[:, 1].max()) + 1500)
    fig.suptitle("香港非大专院校校巴 proxy：直线链与道路路径对比", fontsize=16, weight="bold")
    fig.text(
        0.5,
        0.015,
        "道路匹配保留推断接载顺序；76 条一手来源路线未虚构几何。底图为当前 MATSim car 道路层。",
        ha="center",
        fontsize=9,
        color="#46515a",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proxy-dir", type=Path, default=DEFAULT_PROXY_DIR)
    parser.add_argument("--network", type=Path, default=DEFAULT_NETWORK)
    parser.add_argument("--campuses", type=Path, default=DEFAULT_CAMPUSES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    routes, stops, campuses = load_inputs(args.proxy_dir, args.campuses)
    inferred = routes[routes["route_kind"] == "inferred_proxy"]
    print(f"reading road network: {args.network}", flush=True)
    graph = parse_network(args.network)
    print(f"road graph: {len(graph.node_ids):,} nodes, {graph.edge_count:,} directed links", flush=True)
    stop_map, campus_map, snap_rows = snap_waypoints(graph, stops, campuses, inferred)
    features, segment_rows, result = assemble_routes(graph, routes, stops, stop_map, campus_map)
    route_rows = result.pop("route_rows")

    route_csv = output_dir / "school_bus_road_matched_routes.csv"
    segment_csv = output_dir / "school_bus_road_match_segments.csv"
    snap_csv = output_dir / "school_bus_route_waypoint_snaps.csv"
    geojson_path = output_dir / "school_bus_road_matched_routes.geojson"
    static_path = output_dir / "hong_kong_school_bus_road_matched_overview.png"
    fields = list(route_rows[0])
    write_csv(route_csv, route_rows, fields)
    write_csv(segment_csv, segment_rows, list(segment_rows[0]))
    write_csv(snap_csv, snap_rows, list(snap_rows[0]))
    geojson_path.write_text(
        json.dumps({"type": "FeatureCollection", "name": "school_bus_road_matched_routes_v4", "features": features}, ensure_ascii=False),
        encoding="utf-8",
    )
    write_static_map(
        static_path,
        graph,
        features,
        args.proxy_dir / "school_bus_proxy_route_geometries.geojson",
    )

    snap_values = [safe_float(row["snap_distance_m"]) for row in snap_rows]
    inferred_lengths = [safe_float(row["road_path_km"]) for row in route_rows if row["route_kind"] == "inferred_proxy"]
    optimised_straight_lengths = [
        safe_float(row["optimised_straight_chain_km"])
        for row in route_rows
        if row["route_kind"] == "inferred_proxy"
    ]
    road_ratios = [
        safe_float(row["road_to_optimised_straight_ratio"])
        for row in route_rows
        if row["route_kind"] == "inferred_proxy"
    ]
    inferred_route_rows = [row for row in route_rows if row["route_kind"] == "inferred_proxy"]
    summary = {
        "output_status": "candidate_not_adopted_for_production",
        "crs": {"routing": TARGET_CRS, "geojson": "EPSG:4326"},
        "routing_network": str(args.network.resolve()),
        "road_mode_filter": sorted(ROAD_MODES),
        "network_road_node_count": len(graph.node_ids),
        "network_directed_road_link_count": graph.edge_count,
        "network_topology_connector_count": graph.topology_connector_count,
        "network_largest_routable_component_node_count": len(graph.routable_node_indices),
        **result,
        "waypoint_count": len(snap_rows),
        "waypoint_snap_distance_m": {
            "median": percentile(snap_values, 50),
            "p95": percentile(snap_values, 95),
            "maximum": round(max(snap_values), 3),
            "over_500m": sum(value > 500 for value in snap_values),
            "over_1000m": sum(value > 1000 for value in snap_values),
        },
        "inferred_route_road_path_km": {
            "median": percentile(inferred_lengths, 50),
            "p95": percentile(inferred_lengths, 95),
            "maximum": round(max(inferred_lengths), 3),
            "total": round(sum(inferred_lengths), 3),
        },
        "optimised_straight_chain_km": {
            "median": percentile(optimised_straight_lengths, 50),
            "p95": percentile(optimised_straight_lengths, 95),
            "maximum": round(max(optimised_straight_lengths), 3),
            "total": round(sum(optimised_straight_lengths), 3),
        },
        "road_to_optimised_straight_ratio": {
            "median": percentile(road_ratios, 50),
            "p95": percentile(road_ratios, 95),
            "maximum": round(max(road_ratios), 3),
        },
        "manual_review_flags": {
            "road_path_over_100km": sum(value > 100 for value in inferred_lengths),
            "road_to_optimised_straight_ratio_over_3": sum(value > 3 for value in road_ratios),
            "road_to_optimised_straight_ratio_over_5": sum(value > 5 for value in road_ratios),
            "routes_with_undirected_fallback": result["route_quality_counts"].get("road_with_undirected_fallback", 0),
            "waypoints_over_1000m_from_car_road": sum(value > 1000 for value in snap_values),
        },
        "qa": {
            "route_count_preserved": len(route_rows) == len(routes),
            "route_ids_preserved": {row["route_id"] for row in route_rows} == set(routes["route_id"]),
            "inferred_geometry_count_matches": sum(item["geometry"] is not None for item in features) == len(inferred_route_rows),
            "locked_geometry_is_null": all(
                item["geometry"] is None
                for item in features
                if item["properties"]["route_kind"] == "first_party_locked"
            ),
            "no_straight_disconnected_fallback": result["straight_disconnected_segment_count"] == 0,
            "all_inferred_routes_have_positive_road_length": all(safe_float(row["road_path_km"]) > 0 for row in inferred_route_rows),
            "proxy_student_total_preserved": sum(int(safe_float(row["proxy_students"])) for row in route_rows)
            == sum(int(safe_float(value)) for value in routes["proxy_students"]),
        },
        "method_notes": [
            "Route membership and pickup demand are inherited from the v3 inferred proxy routes.",
            "Within each inferred route, pickup order is improved by farthest-start nearest-neighbour plus deterministic 2-opt before road routing.",
            "Legacy v3 inferred pickup/arrival times are retained only as provenance and are not recalculated after waypoint reordering.",
            "Waypoints are snapped to the nearest node incident to a MATSim car link.",
            "Bus-only links are excluded because they duplicate public-transport route layers rather than the base street graph.",
            "Directed shortest paths are preferred; undirected topology fallback is explicitly flagged.",
            "A straight connector is used only when both road searches fail and is explicitly flagged.",
            "The 76 first-party locked route names retain null geometry rather than fabricated alignments.",
        ],
    }
    summary_path = output_dir / "school_bus_road_match_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest_rows = []
    for role, path in (
        ("input_proxy_routes", args.proxy_dir / "school_bus_proxy_routes.csv"),
        ("input_proxy_stops", args.proxy_dir / "school_bus_proxy_stops.csv"),
        ("input_active_matsim_network", args.network),
        ("input_school_campuses", args.campuses),
        ("output_route_table", route_csv),
        ("output_segment_table", segment_csv),
        ("output_waypoint_snaps", snap_csv),
        ("output_route_geometry", geojson_path),
        ("output_summary", summary_path),
        ("output_static_visualization", static_path),
    ):
        manifest_rows.append({"role": role, "path": str(path.resolve()), "sha256": sha256(path)})
    write_csv(output_dir / "SOURCE_MANIFEST.csv", manifest_rows, ["role", "path", "sha256"])
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
