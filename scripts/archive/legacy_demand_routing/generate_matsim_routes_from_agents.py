"""Generate a MATSim car network and routed population from Fuzhou agents.

This script builds a lightweight MATSim-compatible road network from the
previously extracted OSM road GeoJSON, snaps generated home/work coordinates to
the routing component, and writes population_v6 plans with link routes.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import pathlib
import time
from collections import Counter
from dataclasses import dataclass
from typing import Iterable
from xml.sax.saxutils import escape

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
CITY_KEY = "fuzhou_city_23_greenspace_grid"
TARGET_CRS = "EPSG:32650"

DEFAULT_AGENTS_DIR = PROJECT_ROOT / "data" / "matsim_agents" / CITY_KEY
DEFAULT_AGENT_DEBUG = DEFAULT_AGENTS_DIR / "agent_od_debug.csv"
DEFAULT_ROADS = PROJECT_ROOT / "data" / "osm" / "fuzhou_city_23" / "fuzhou_city_23_osm_roads.geojson"
DEFAULT_OUT_DIR = PROJECT_ROOT / "data" / "matsim_routes" / CITY_KEY

CAR_HIGHWAYS = {
    "motorway",
    "motorway_link",
    "trunk",
    "trunk_link",
    "primary",
    "primary_link",
    "secondary",
    "secondary_link",
    "tertiary",
    "tertiary_link",
    "unclassified",
    "residential",
    "living_street",
    "service",
}

HIGHWAY_DEFAULTS = {
    "motorway": (33.33, 2_000.0, 2.0),
    "motorway_link": (22.22, 1_500.0, 1.0),
    "trunk": (27.78, 1_800.0, 2.0),
    "trunk_link": (16.67, 1_200.0, 1.0),
    "primary": (22.22, 1_500.0, 2.0),
    "primary_link": (13.89, 1_000.0, 1.0),
    "secondary": (16.67, 1_200.0, 1.5),
    "secondary_link": (11.11, 900.0, 1.0),
    "tertiary": (13.89, 1_000.0, 1.2),
    "tertiary_link": (8.33, 700.0, 1.0),
    "unclassified": (11.11, 800.0, 1.0),
    "residential": (8.33, 600.0, 1.0),
    "living_street": (4.17, 300.0, 1.0),
    "service": (5.56, 300.0, 1.0),
}


@dataclass
class Link:
    id: str
    from_node: str
    to_node: str
    length: float
    freespeed: float
    capacity: float
    permlanes: float
    geometry: LineString
    highway: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate MATSim routes for Fuzhou OD agents.")
    parser.add_argument("--agent-debug", default=str(DEFAULT_AGENT_DEBUG), help="agent_od_debug.csv from OD agent generation.")
    parser.add_argument("--roads", default=str(DEFAULT_ROADS), help="OSM roads GeoJSON.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output route directory.")
    parser.add_argument("--crs", default=TARGET_CRS, help="Projected CRS used by MATSim network/plans.")
    parser.add_argument("--snap-component", choices=["largest_strong", "all"], default="largest_strong")
    parser.add_argument("--max-unrouted-share", type=float, default=0.05)
    parser.add_argument("--sample-route-checks", type=int, default=100)
    return parser.parse_args()


def ensure_exists(path: pathlib.Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")


def as_bool_oneway(value: object, other_tags: object) -> int:
    """Return 1 forward-only, -1 reverse-only, 0 bidirectional."""
    text = f"{'' if pd.isna(value) else value} {'' if pd.isna(other_tags) else other_tags}".lower()
    if "oneway\"=>\"-1" in text or "oneway=-1" in text:
        return -1
    if (
        "oneway\"=>\"yes" in text
        or "oneway\"=>\"true" in text
        or "oneway\"=>\"1" in text
        or "oneway=yes" in text
        or "oneway=true" in text
    ):
        return 1
    return 0


def node_key(x: float, y: float) -> tuple[float, float]:
    return (round(float(x), 3), round(float(y), 3))


def hms(seconds: float) -> str:
    total = int(round(max(0.0, seconds)))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def xml_attr(value: object) -> str:
    return escape(str(value), {'"': "&quot;"})


def xml_text(value: object) -> str:
    return escape(str(value))


def build_network(roads_path: pathlib.Path, target_crs: str) -> tuple[dict[str, tuple[float, float]], list[Link], dict]:
    roads = gpd.read_file(roads_path)
    if roads.crs is None:
        roads = roads.set_crs("EPSG:4326")
    roads = roads.to_crs(target_crs)
    roads = roads[roads.geometry.notna() & ~roads.geometry.is_empty].copy()
    roads = roads[roads.geometry.geom_type == "LineString"].copy()
    roads["highway"] = roads["highway"].astype(str).str.lower()
    roads = roads[roads["highway"].isin(CAR_HIGHWAYS)].copy()

    coord_frequency: Counter[tuple[float, float]] = Counter()
    for geom in roads.geometry:
        for x, y in geom.coords:
            coord_frequency[node_key(x, y)] += 1

    node_ids: dict[tuple[float, float], str] = {}
    nodes: dict[str, tuple[float, float]] = {}
    links: list[Link] = []
    highway_counter: Counter[str] = Counter()

    def get_node_id(coord: tuple[float, float]) -> str:
        key = node_key(coord[0], coord[1])
        existing = node_ids.get(key)
        if existing is not None:
            return existing
        node_id = f"n_{len(node_ids)}"
        node_ids[key] = node_id
        nodes[node_id] = key
        return node_id

    def add_link(link_id: str, coords: list[tuple[float, float]], highway: str) -> None:
        a = coords[0]
        b = coords[-1]
        if node_key(a[0], a[1]) == node_key(b[0], b[1]):
            return
        line = LineString(coords)
        length = float(line.length)
        if length <= 1.0:
            return
        freespeed, capacity, permlanes = HIGHWAY_DEFAULTS[highway]
        links.append(
            Link(
                id=link_id,
                from_node=get_node_id(a),
                to_node=get_node_id(b),
                length=length,
                freespeed=freespeed,
                capacity=capacity,
                permlanes=permlanes,
                geometry=line,
                highway=highway,
            )
        )

    for road_idx, row in roads.reset_index(drop=True).iterrows():
        geom: LineString = row.geometry
        coords = [(float(x), float(y)) for x, y in geom.coords]
        if len(coords) < 2:
            continue
        highway = str(row["highway"])
        direction = as_bool_oneway(row.get("oneway"), row.get("other_tags"))
        highway_counter[highway] += 1
        split_indices = [0]
        for coord_idx, coord in enumerate(coords[1:-1], start=1):
            if coord_frequency[node_key(coord[0], coord[1])] > 1:
                split_indices.append(coord_idx)
        split_indices.append(len(coords) - 1)

        for part_idx, (start_idx, end_idx) in enumerate(zip(split_indices[:-1], split_indices[1:])):
            part_coords = coords[start_idx : end_idx + 1]
            if len(part_coords) < 2:
                continue
            if direction == -1:
                add_link(f"l_{road_idx}_{part_idx}_r", list(reversed(part_coords)), highway)
            else:
                add_link(f"l_{road_idx}_{part_idx}_f", part_coords, highway)
                if direction == 0:
                    add_link(f"l_{road_idx}_{part_idx}_r", list(reversed(part_coords)), highway)

    summary = {
        "roads_input_rows": int(len(roads)),
        "highway_rows": dict(highway_counter),
        "node_count": int(len(nodes)),
        "link_count": int(len(links)),
    }
    return nodes, links, summary


def build_graph(links: list[Link]) -> tuple[nx.DiGraph, dict[str, Link]]:
    graph = nx.DiGraph()
    link_by_id = {link.id: link for link in links}
    for link in links:
        weight = link.length / link.freespeed
        existing = graph.get_edge_data(link.from_node, link.to_node)
        if existing is None or weight < existing["weight"]:
            graph.add_edge(
                link.from_node,
                link.to_node,
                weight=weight,
                length=link.length,
                link_id=link.id,
            )
    return graph, link_by_id


def select_routing_links(graph: nx.DiGraph, links: list[Link], mode: str) -> tuple[list[Link], dict]:
    if mode == "all":
        return links, {"snap_component": "all", "routing_node_count": graph.number_of_nodes()}

    components = list(nx.strongly_connected_components(graph))
    if not components:
        raise ValueError("Network graph has no strongly connected component.")
    largest = max(components, key=len)
    routing_links = [link for link in links if link.from_node in largest and link.to_node in largest]
    return routing_links, {
        "snap_component": "largest_strong",
        "strong_component_count": len(components),
        "routing_node_count": len(largest),
        "routing_link_count": len(routing_links),
    }


def write_network_xml(path: pathlib.Path, nodes: dict[str, tuple[float, float]], links: list[Link]) -> None:
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as handle:
        handle.write('<?xml version="1.0" encoding="utf-8"?>\n')
        handle.write('<!DOCTYPE network SYSTEM "http://www.matsim.org/files/dtd/network_v2.dtd">\n')
        handle.write("<network>\n")
        handle.write("  <nodes>\n")
        for node_id, (x, y) in nodes.items():
            handle.write(f'    <node id="{xml_attr(node_id)}" x="{x:.3f}" y="{y:.3f}" />\n')
        handle.write("  </nodes>\n")
        handle.write("  <links capperiod=\"01:00:00\">\n")
        for link in links:
            handle.write(
                f'    <link id="{xml_attr(link.id)}" from="{xml_attr(link.from_node)}" to="{xml_attr(link.to_node)}" '
                f'length="{link.length:.3f}" freespeed="{link.freespeed:.6f}" '
                f'capacity="{link.capacity:.3f}" permlanes="{link.permlanes:.2f}" modes="car" />\n'
            )
        handle.write("  </links>\n")
        handle.write("</network>\n")


def prepare_snapper(links: list[Link]) -> tuple[STRtree, list[LineString], list[Link]]:
    geometries = [link.geometry for link in links]
    return STRtree(geometries), geometries, links


def nearest_link(point: Point, tree: STRtree, snap_links: list[Link]) -> tuple[Link, float]:
    idx = int(tree.nearest(point))
    link = snap_links[idx]
    return link, float(point.distance(link.geometry))


def route_between_links(
    graph: nx.DiGraph,
    link_by_id: dict[str, Link],
    start_link: Link,
    end_link: Link,
) -> tuple[list[str], float, float] | None:
    if start_link.id == end_link.id:
        travel_time = start_link.length / start_link.freespeed
        return [start_link.id], start_link.length, travel_time

    try:
        _cost, node_path = nx.bidirectional_dijkstra(graph, start_link.to_node, end_link.from_node, weight="weight")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None

    link_ids = [start_link.id]
    for from_node, to_node in zip(node_path[:-1], node_path[1:]):
        edge = graph.get_edge_data(from_node, to_node)
        if edge is None:
            return None
        link_ids.append(str(edge["link_id"]))
    link_ids.append(end_link.id)

    distance = 0.0
    travel_time = 0.0
    for link_id in link_ids:
        link = link_by_id[link_id]
        distance += link.length
        travel_time += link.length / link.freespeed
    return link_ids, distance, travel_time


def build_sparse_graph(graph: nx.DiGraph) -> tuple[csr_matrix, dict[str, int], list[str], dict[tuple[int, int], str]]:
    node_ids = list(graph.nodes())
    node_to_idx = {node_id: idx for idx, node_id in enumerate(node_ids)}
    rows: list[int] = []
    cols: list[int] = []
    weights: list[float] = []
    edge_link_by_idx: dict[tuple[int, int], str] = {}
    for from_node, to_node, data in graph.edges(data=True):
        from_idx = node_to_idx[from_node]
        to_idx = node_to_idx[to_node]
        rows.append(from_idx)
        cols.append(to_idx)
        weights.append(float(data["weight"]))
        edge_link_by_idx[(from_idx, to_idx)] = str(data["link_id"])
    matrix = csr_matrix((weights, (rows, cols)), shape=(len(node_ids), len(node_ids)))
    return matrix, node_to_idx, node_ids, edge_link_by_idx


def reconstruct_node_path(predecessors: np.ndarray, source_idx: int, target_idx: int) -> list[int] | None:
    if source_idx == target_idx:
        return [source_idx]
    current = target_idx
    reversed_path = [target_idx]
    guard = 0
    while current != source_idx:
        current = int(predecessors[current])
        if current < 0:
            return None
        reversed_path.append(current)
        guard += 1
        if guard > len(predecessors):
            return None
    return list(reversed(reversed_path))


def batch_route_links(
    graph: nx.DiGraph,
    link_by_id: dict[str, Link],
    requests: list[tuple[Link, Link]],
    batch_size: int = 256,
) -> list[tuple[list[str], float, float] | None]:
    matrix, node_to_idx, _node_ids, edge_link_by_idx = build_sparse_graph(graph)
    outputs: list[tuple[list[str], float, float] | None] = [None] * len(requests)
    source_to_requests: dict[str, list[int]] = {}

    for req_idx, (start_link, end_link) in enumerate(requests):
        if start_link.id == end_link.id:
            travel_time = start_link.length / start_link.freespeed
            outputs[req_idx] = ([start_link.id], start_link.length, travel_time)
            continue
        source_to_requests.setdefault(start_link.to_node, []).append(req_idx)

    sources = list(source_to_requests)
    for offset in range(0, len(sources), batch_size):
        batch_sources = sources[offset : offset + batch_size]
        source_indices = np.asarray([node_to_idx[source] for source in batch_sources], dtype=np.int32)
        distances, predecessors = dijkstra(
            matrix,
            directed=True,
            indices=source_indices,
            return_predecessors=True,
        )
        distances = np.atleast_2d(distances)
        predecessors = np.atleast_2d(predecessors)

        for local_idx, source_node in enumerate(batch_sources):
            source_idx = int(source_indices[local_idx])
            pred_row = predecessors[local_idx]
            for req_idx in source_to_requests[source_node]:
                start_link, end_link = requests[req_idx]
                target_idx = node_to_idx.get(end_link.from_node)
                if target_idx is None or not np.isfinite(distances[local_idx, target_idx]):
                    outputs[req_idx] = None
                    continue
                node_path = reconstruct_node_path(pred_row, source_idx, int(target_idx))
                if node_path is None:
                    outputs[req_idx] = None
                    continue

                link_ids = [start_link.id]
                missing_edge = False
                for from_idx, to_idx in zip(node_path[:-1], node_path[1:]):
                    edge_link_id = edge_link_by_idx.get((int(from_idx), int(to_idx)))
                    if edge_link_id is None:
                        missing_edge = True
                        break
                    link_ids.append(edge_link_id)
                if missing_edge:
                    outputs[req_idx] = None
                    continue
                link_ids.append(end_link.id)

                distance = 0.0
                travel_time = 0.0
                for link_id in link_ids:
                    link = link_by_id[link_id]
                    distance += link.length
                    travel_time += link.length / link.freespeed
                outputs[req_idx] = (link_ids, distance, travel_time)

        print(f"  batch-routed source nodes {min(offset + batch_size, len(sources))}/{len(sources)}")

    return outputs


def intermediate_route_text(link_ids: list[str]) -> str:
    return " ".join(link_ids)


def write_routed_plans(path: pathlib.Path, rows: Iterable[dict]) -> None:
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as handle:
        handle.write('<?xml version="1.0" encoding="utf-8"?>\n')
        handle.write('<!DOCTYPE population SYSTEM "http://www.matsim.org/files/dtd/population_v6.dtd">\n')
        handle.write("<population>\n")
        for row in rows:
            handle.write(f'  <person id="{xml_attr(row["person_id"])}">\n')
            handle.write("    <attributes>\n")
            for name, klass, value in (
                ("home_zone", "java.lang.String", row["home_zone"]),
                ("work_zone", "java.lang.String", row["work_zone"]),
                ("sample_weight", "java.lang.Double", f'{row["sample_weight"]:.10f}'),
                ("od_flow_raw", "java.lang.Double", f'{row["od_flow_raw"]:.10f}'),
            ):
                handle.write(
                    f'      <attribute name="{xml_attr(name)}" class="{xml_attr(klass)}">'
                    f"{xml_text(value)}</attribute>\n"
                )
            handle.write("    </attributes>\n")
            handle.write('    <plan selected="yes">\n')
            handle.write(
                f'      <activity type="h" x="{row["home_x"]:.3f}" y="{row["home_y"]:.3f}" '
                f'link="{xml_attr(row["home_link"])}" end_time="{xml_attr(row["home_end_time"])}" />\n'
            )
            handle.write('      <leg mode="car">\n')
            if row["routed"]:
                handle.write(
                    f'        <route type="links" start_link="{xml_attr(row["home_link"])}" '
                    f'end_link="{xml_attr(row["work_link"])}" trav_time="{xml_attr(row["out_trav_time"])}" '
                    f'distance="{row["out_distance"]:.3f}">{xml_text(row["out_route_text"])}</route>\n'
                )
            handle.write("      </leg>\n")
            handle.write(
                f'      <activity type="w" x="{row["work_x"]:.3f}" y="{row["work_y"]:.3f}" '
                f'link="{xml_attr(row["work_link"])}" end_time="{xml_attr(row["work_end_time"])}" />\n'
            )
            handle.write('      <leg mode="car">\n')
            if row["routed"]:
                handle.write(
                    f'        <route type="links" start_link="{xml_attr(row["work_link"])}" '
                    f'end_link="{xml_attr(row["home_link"])}" trav_time="{xml_attr(row["return_trav_time"])}" '
                    f'distance="{row["return_distance"]:.3f}">{xml_text(row["return_route_text"])}</route>\n'
                )
            handle.write("      </leg>\n")
            handle.write(
                f'      <activity type="h" x="{row["home_x"]:.3f}" y="{row["home_y"]:.3f}" '
                f'link="{xml_attr(row["home_link"])}" />\n'
            )
            handle.write("    </plan>\n")
            handle.write("  </person>\n")
        handle.write("</population>\n")


def main() -> None:
    args = parse_args()
    started = time.time()
    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    agent_debug_path = pathlib.Path(args.agent_debug)
    roads_path = pathlib.Path(args.roads)
    ensure_exists(agent_debug_path, "agent_od_debug.csv")
    ensure_exists(roads_path, "roads GeoJSON")

    print("Building MATSim network from OSM road GeoJSON...")
    nodes, links, network_summary = build_network(roads_path, args.crs)
    graph, link_by_id = build_graph(links)
    snap_links, component_summary = select_routing_links(graph, links, args.snap_component)
    tree, _snap_geoms, snap_links = prepare_snapper(snap_links)

    network_path = out_dir / "network.xml.gz"
    output_node_ids = {link.from_node for link in snap_links} | {link.to_node for link in snap_links}
    output_nodes = {node_id: coord for node_id, coord in nodes.items() if node_id in output_node_ids}
    write_network_xml(network_path, output_nodes, snap_links)

    agents = pd.read_csv(agent_debug_path)
    required = {
        "person_id",
        "home_x",
        "home_y",
        "work_x",
        "work_y",
        "home_end_time",
        "work_end_time",
        "home_zone",
        "work_zone",
        "sample_weight",
        "od_flow_raw",
    }
    missing = sorted(required - set(agents.columns))
    if missing:
        raise ValueError(f"agent debug CSV missing columns: {missing}")

    print(f"Snapping {len(agents)} agents to routing links...")
    snapped_agents: list[dict] = []
    out_requests: list[tuple[Link, Link]] = []
    return_requests: list[tuple[Link, Link]] = []

    for idx, agent in agents.iterrows():
        home_point = Point(float(agent["home_x"]), float(agent["home_y"]))
        work_point = Point(float(agent["work_x"]), float(agent["work_y"]))
        home_link, home_snap_distance = nearest_link(home_point, tree, snap_links)
        work_link, work_snap_distance = nearest_link(work_point, tree, snap_links)

        snapped_agents.append(
            {
                "agent": agent,
                "home_link": home_link,
                "work_link": work_link,
                "home_snap_distance": home_snap_distance,
                "work_snap_distance": work_snap_distance,
            }
        )
        out_requests.append((home_link, work_link))
        return_requests.append((work_link, home_link))

        if (idx + 1) % 5_000 == 0:
            print(f"  snapped {idx + 1}/{len(agents)} agents")

    print("Batch routing outbound legs...")
    out_routes = batch_route_links(graph, link_by_id, out_requests)
    print("Batch routing return legs...")
    return_routes = batch_route_links(graph, link_by_id, return_requests)

    rows: list[dict] = []
    unrouted_rows: list[dict] = []
    for snapped, out_route, return_route in zip(snapped_agents, out_routes, return_routes):
        agent = snapped["agent"]
        home_link = snapped["home_link"]
        work_link = snapped["work_link"]
        home_snap_distance = snapped["home_snap_distance"]
        work_snap_distance = snapped["work_snap_distance"]
        routed = out_route is not None and return_route is not None

        if routed:
            out_ids, out_distance, out_time = out_route
            return_ids, return_distance, return_time = return_route
        else:
            out_ids, out_distance, out_time = [], math.nan, math.nan
            return_ids, return_distance, return_time = [], math.nan, math.nan
            unrouted_rows.append(
                {
                    "person_id": agent["person_id"],
                    "home_link": home_link.id,
                    "work_link": work_link.id,
                    "home_snap_distance": home_snap_distance,
                    "work_snap_distance": work_snap_distance,
                    "reason": "no_directed_path",
                }
            )

        rows.append(
            {
                "person_id": agent["person_id"],
                "home_zone": agent["home_zone"],
                "work_zone": agent["work_zone"],
                "sample_weight": float(agent["sample_weight"]),
                "od_flow_raw": float(agent["od_flow_raw"]),
                "home_x": float(agent["home_x"]),
                "home_y": float(agent["home_y"]),
                "work_x": float(agent["work_x"]),
                "work_y": float(agent["work_y"]),
                "home_end_time": agent["home_end_time"],
                "work_end_time": agent["work_end_time"],
                "home_link": home_link.id,
                "work_link": work_link.id,
                "home_snap_distance": home_snap_distance,
                "work_snap_distance": work_snap_distance,
                "routed": routed,
                "out_distance": out_distance,
                "out_travel_time_seconds": out_time,
                "out_trav_time": "" if not routed else hms(out_time),
                "out_route_links": len(out_ids),
                "out_route_text": "" if not routed else intermediate_route_text(out_ids),
                "return_distance": return_distance,
                "return_travel_time_seconds": return_time,
                "return_trav_time": "" if not routed else hms(return_time),
                "return_route_links": len(return_ids),
                "return_route_text": "" if not routed else intermediate_route_text(return_ids),
            }
        )

    routed_plans_path = out_dir / "routed_plans.xml.gz"
    write_routed_plans(routed_plans_path, rows)

    route_debug_path = out_dir / "agent_route_debug.csv"
    route_debug_fields = [
        "person_id",
        "home_zone",
        "work_zone",
        "home_link",
        "work_link",
        "home_snap_distance",
        "work_snap_distance",
        "routed",
        "out_distance",
        "out_travel_time_seconds",
        "out_route_links",
        "return_distance",
        "return_travel_time_seconds",
        "return_route_links",
    ]
    with route_debug_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=route_debug_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    unrouted_path = out_dir / "unrouted_agents.csv"
    with unrouted_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["person_id", "home_link", "work_link", "home_snap_distance", "work_snap_distance", "reason"],
        )
        writer.writeheader()
        writer.writerows(unrouted_rows)

    routed_count = sum(1 for row in rows if row["routed"])
    unrouted_count = len(rows) - routed_count
    unrouted_share = unrouted_count / len(rows) if rows else 1.0
    routed_distances = np.asarray([row["out_distance"] for row in rows if row["routed"]], dtype="float64")
    home_snap = np.asarray([row["home_snap_distance"] for row in rows], dtype="float64")
    work_snap = np.asarray([row["work_snap_distance"] for row in rows], dtype="float64")

    sampled_rows = [row for row in rows if row["routed"]][: args.sample_route_checks]
    route_sequence_checks = 0
    for row in sampled_rows:
        out_ids = str(row["out_route_text"]).split()
        if out_ids and out_ids[0] == row["home_link"] and out_ids[-1] == row["work_link"]:
            route_sequence_checks += 1

    summary = {
        "city_key": CITY_KEY,
        "created_at_epoch": time.time(),
        "runtime_seconds": round(time.time() - started, 3),
        "inputs": {
            "agent_debug_csv": str(agent_debug_path),
            "roads_geojson": str(roads_path),
        },
        "outputs": {
            "network_xml_gz": str(network_path),
            "routed_plans_xml_gz": str(routed_plans_path),
            "agent_route_debug_csv": str(route_debug_path),
            "unrouted_agents_csv": str(unrouted_path),
        },
        "crs": args.crs,
        "network": {**network_summary, **component_summary},
        "output_network": {
            "node_count": int(len(output_nodes)),
            "link_count": int(len(snap_links)),
        },
        "routing": {
            "agent_count": int(len(rows)),
            "routed_count": int(routed_count),
            "unrouted_count": int(unrouted_count),
            "snap_success_rate": 1.0,
            "routed_success_rate": float(1.0 - unrouted_share),
            "unique_link_od_requests": int(
                len({(start.id, end.id) for start, end in out_requests})
                + len({(start.id, end.id) for start, end in return_requests})
            ),
            "home_snap_distance_m": {
                "mean": float(home_snap.mean()) if len(home_snap) else None,
                "p95": float(np.percentile(home_snap, 95)) if len(home_snap) else None,
                "max": float(home_snap.max()) if len(home_snap) else None,
            },
            "work_snap_distance_m": {
                "mean": float(work_snap.mean()) if len(work_snap) else None,
                "p95": float(np.percentile(work_snap, 95)) if len(work_snap) else None,
                "max": float(work_snap.max()) if len(work_snap) else None,
            },
            "out_distance_m": {
                "mean": float(routed_distances.mean()) if len(routed_distances) else None,
                "p95": float(np.percentile(routed_distances, 95)) if len(routed_distances) else None,
                "max": float(routed_distances.max()) if len(routed_distances) else None,
            },
            "sample_route_sequence_checks": {
                "checked": int(len(sampled_rows)),
                "passed": int(route_sequence_checks),
            },
        },
        "validation": {
            "all_link_lengths_positive": all(link.length > 0 for link in links),
            "all_link_freespeeds_positive": all(link.freespeed > 0 for link in links),
            "all_link_capacities_positive": all(link.capacity > 0 for link in links),
            "unrouted_share_threshold": args.max_unrouted_share,
            "passed_unrouted_threshold": unrouted_share <= args.max_unrouted_share,
        },
    }
    summary_path = out_dir / "route_generation_summary.json"
    summary["outputs"]["route_generation_summary_json"] = str(summary_path)

    network_summary_path = out_dir / "network_summary.json"
    network_summary_path.write_text(
        json.dumps(
            {
                "network": {**network_summary, **component_summary},
                "output_network": {"node_count": int(len(output_nodes)), "link_count": int(len(snap_links))},
                "crs": args.crs,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    summary["outputs"]["network_summary_json"] = str(network_summary_path)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if unrouted_share > args.max_unrouted_share:
        raise SystemExit(
            f"Unrouted share {unrouted_share:.2%} exceeds threshold {args.max_unrouted_share:.2%}. "
            f"See {unrouted_path}"
        )


if __name__ == "__main__":
    main()
