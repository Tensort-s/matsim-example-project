#!/usr/bin/env python3
"""Augment the Fuzhou MATSim road network with synthetic bus trajectory links.

The generated links represent bus trajectory segments inside a city-boundary
buffer where the existing road network is farther than a configurable
threshold. They are synthetic and tagged with `car,pt` modes as requested.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import numpy as np
from pyproj import Transformer
from scipy.spatial import cKDTree
from shapely.geometry import LineString, Point, shape
from shapely.ops import transform as shapely_transform, unary_union


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NETWORK = ROOT / "data" / "matsim_routes" / "fuzhou_city_23_greenspace_grid_multi_activity" / "network.xml.gz"
DEFAULT_BOUNDARY = ROOT / "data" / "osm" / "fuzhou_city_23" / "fuzhou_city_23_boundary.geojson"
DEFAULT_TRAJECTORIES = ROOT / "data" / "transit" / "fuzhou_transit_coordinates_unified_20260709" / "bus" / "bus_line_trajectories_epsg32650.geojson"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "transit" / "fuzhou_bus_osm_augmented_network_20260709_2km_carpt"


def xml_attr(value: Any) -> str:
    return escape(str(value), {'"': "&quot;"})


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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


def load_boundary_buffer(boundary_path: Path, buffer_m: float):
    data = json.loads(boundary_path.read_text(encoding="utf-8"))
    geoms = [shape(feature["geometry"]) for feature in data.get("features", []) if feature.get("geometry")]
    if not geoms and data.get("type") in {"Polygon", "MultiPolygon"}:
        geoms = [shape(data)]
    geom_wgs84 = unary_union(geoms)
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32650", always_xy=True)
    return shapely_transform(transformer.transform, geom_wgs84).buffer(buffer_m)


class NetworkXml:
    def __init__(self, path: Path, snap_k: int):
        self.path = path
        with gzip.open(path, "rt", encoding="utf-8") as f:
            self.root = ET.parse(f).getroot()
        self.nodes: dict[str, tuple[float, float]] = {}
        self.links: dict[str, dict[str, Any]] = {}
        self._load()
        self.snap_k = min(snap_k, len(self.links))
        self.node_ids = list(self.nodes)
        self.node_tree = cKDTree(np.array([self.nodes[nid] for nid in self.node_ids]))
        self.link_ids = list(self.links)
        midpoints = []
        for lid in self.link_ids:
            link = self.links[lid]
            ax, ay = self.nodes[link["from"]]
            bx, by = self.nodes[link["to"]]
            midpoints.append(((ax + bx) / 2.0, (ay + by) / 2.0))
        self.link_tree = cKDTree(np.array(midpoints))

    def _load(self) -> None:
        for node in self.root.find("nodes").findall("node"):  # type: ignore[union-attr]
            self.nodes[node.attrib["id"]] = (safe_float(node.attrib["x"]), safe_float(node.attrib["y"]))
        for link in self.root.find("links").findall("link"):  # type: ignore[union-attr]
            attrib = dict(link.attrib)
            self.links[attrib["id"]] = {
                "id": attrib["id"],
                "from": attrib["from"],
                "to": attrib["to"],
                "length": max(safe_float(attrib.get("length")), 1.0),
                "freespeed": max(safe_float(attrib.get("freespeed")), 1.0),
                "attrib": attrib,
            }

    def nearest_link_distance(self, x: float, y: float) -> float:
        _, idxs = self.link_tree.query([x, y], k=self.snap_k)
        if self.snap_k == 1:
            idxs = [int(idxs)]
        best = float("inf")
        for idx in idxs:
            lid = self.link_ids[int(idx)]
            link = self.links[lid]
            ax, ay = self.nodes[link["from"]]
            bx, by = self.nodes[link["to"]]
            best = min(best, point_segment_distance(x, y, ax, ay, bx, by))
        return best

    def nearest_node(self, x: float, y: float) -> tuple[str, float]:
        dist, idx = self.node_tree.query([x, y], k=1)
        return self.node_ids[int(idx)], float(dist)


def load_trajectories(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    features = []
    for feature in data.get("features", []):
        props = feature.get("properties") or {}
        coords = feature.get("geometry", {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        features.append(
            {
                "line_id": str(props.get("line_id") or ""),
                "line_name": props.get("line_name") or "",
                "coords": [(safe_float(x), safe_float(y)) for x, y in coords],
            }
        )
    return features


def segmentize(coords: list[tuple[float, float]], max_len_m: float) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    segments = []
    for a, b in zip(coords, coords[1:]):
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        if length <= 1:
            continue
        steps = max(1, int(math.ceil(length / max_len_m)))
        prev = a
        for i in range(1, steps + 1):
            t = i / steps
            nxt = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            segments.append((prev, nxt))
            prev = nxt
    return segments


def grid_key(point: tuple[float, float], tolerance_m: float) -> tuple[int, int]:
    return (int(round(point[0] / tolerance_m)), int(round(point[1] / tolerance_m)))


def build_synthetic_segments(
    network: NetworkXml,
    trajectories: list[dict[str, Any]],
    buffer_geom,
    missing_threshold_m: float,
    max_segment_len_m: float,
    node_merge_tolerance_m: float,
) -> tuple[dict[tuple[int, int], dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    nodes: dict[tuple[int, int], dict[str, Any]] = {}
    link_keys: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    links: list[dict[str, Any]] = []
    stats = {
        "trajectory_segments_total": 0,
        "segments_inside_buffer": 0,
        "segments_missing_road": 0,
        "segments_too_short": 0,
        "duplicate_directional_segments_skipped": 0,
    }
    for traj in trajectories:
        for a, b in segmentize(traj["coords"], max_segment_len_m):
            stats["trajectory_segments_total"] += 1
            mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
            if not buffer_geom.covers(Point(mid)):
                continue
            stats["segments_inside_buffer"] += 1
            if network.nearest_link_distance(mid[0], mid[1]) <= missing_threshold_m:
                continue
            stats["segments_missing_road"] += 1
            ak = grid_key(a, node_merge_tolerance_m)
            bk = grid_key(b, node_merge_tolerance_m)
            if ak == bk:
                stats["segments_too_short"] += 1
                continue
            if (ak, bk) in link_keys:
                stats["duplicate_directional_segments_skipped"] += 1
                continue
            link_keys.add((ak, bk))
            nodes.setdefault(ak, {"key": ak, "x": a[0], "y": a[1], "source_line_ids": set(), "source_line_names": set()})
            nodes.setdefault(bk, {"key": bk, "x": b[0], "y": b[1], "source_line_ids": set(), "source_line_names": set()})
            nodes[ak]["source_line_ids"].add(traj["line_id"])
            nodes[bk]["source_line_ids"].add(traj["line_id"])
            nodes[ak]["source_line_names"].add(traj["line_name"])
            nodes[bk]["source_line_names"].add(traj["line_name"])
            length = math.hypot(nodes[bk]["x"] - nodes[ak]["x"], nodes[bk]["y"] - nodes[ak]["y"])
            links.append(
                {
                    "from_key": ak,
                    "to_key": bk,
                    "length": max(length, 1.0),
                    "source_line_id": traj["line_id"],
                    "source_line_name": traj["line_name"],
                    "mid_nearest_road_distance_m": network.nearest_link_distance(mid[0], mid[1]),
                }
            )
    return nodes, links, stats


def assign_ids_and_connectors(
    network: NetworkXml,
    nodes: dict[tuple[int, int], dict[str, Any]],
    links: list[dict[str, Any]],
    connector_threshold_m: float,
    freespeed_mps: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    for idx, node in enumerate(nodes.values(), start=1):
        node["node_id"] = f"syn_bus_node_{idx:06d}"
    for idx, link in enumerate(links, start=1):
        link["link_id"] = f"syn_bus_link_{idx:06d}"
        link["from_node"] = nodes[link["from_key"]]["node_id"]
        link["to_node"] = nodes[link["to_key"]]["node_id"]
        link["freespeed"] = freespeed_mps
    connectors: list[dict[str, Any]] = []
    connector_seen: set[tuple[str, str]] = set()
    for node in nodes.values():
        nearest_node_id, distance = network.nearest_node(node["x"], node["y"])
        if distance > connector_threshold_m:
            continue
        for direction, from_node, to_node in [
            ("from_road", nearest_node_id, node["node_id"]),
            ("to_road", node["node_id"], nearest_node_id),
        ]:
            key = (from_node, to_node)
            if key in connector_seen:
                continue
            connector_seen.add(key)
            connectors.append(
                {
                    "link_id": f"syn_bus_connector_{len(connectors)+1:06d}",
                    "from_node": from_node,
                    "to_node": to_node,
                    "length": max(distance, 1.0),
                    "freespeed": freespeed_mps,
                    "connector_type": direction,
                    "synthetic_node_id": node["node_id"],
                    "road_node_id": nearest_node_id,
                    "connector_distance_m": distance,
                }
            )
    return links, connectors


def prune_isolated_synthetic_components(
    nodes: dict[tuple[int, int], dict[str, Any]],
    links: list[dict[str, Any]],
    connectors: list[dict[str, Any]],
    min_connector_links: int,
) -> tuple[dict[tuple[int, int], dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    if min_connector_links <= 0:
        return nodes, links, connectors, {
            "synthetic_components_total": 0,
            "synthetic_components_kept": 0,
            "synthetic_components_pruned": 0,
            "synthetic_links_pruned_as_isolated": 0,
            "synthetic_nodes_pruned_as_isolated": 0,
            "connector_links_pruned_as_isolated": 0,
        }
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra = find(a)
        rb = find(b)
        if ra != rb:
            parent[rb] = ra

    for node in nodes.values():
        find(node["node_id"])
    for link in links:
        union(link["from_node"], link["to_node"])

    connector_count_by_component: dict[str, int] = {}
    for connector in connectors:
        synthetic_node_id = connector["synthetic_node_id"]
        comp = find(synthetic_node_id)
        connector_count_by_component[comp] = connector_count_by_component.get(comp, 0) + 1

    components = {find(node["node_id"]) for node in nodes.values()}
    keep_components = {
        comp for comp in components if connector_count_by_component.get(comp, 0) >= min_connector_links
    }
    kept_links = [
        link
        for link in links
        if find(link["from_node"]) in keep_components and find(link["to_node"]) in keep_components
    ]
    kept_connectors = [
        connector
        for connector in connectors
        if find(connector["synthetic_node_id"]) in keep_components
    ]
    used_node_ids = {link["from_node"] for link in kept_links} | {link["to_node"] for link in kept_links}
    used_node_ids |= {connector["synthetic_node_id"] for connector in kept_connectors}
    kept_nodes = {
        key: node
        for key, node in nodes.items()
        if node["node_id"] in used_node_ids
    }
    stats = {
        "synthetic_components_total": len(components),
        "synthetic_components_kept": len(keep_components),
        "synthetic_components_pruned": len(components) - len(keep_components),
        "synthetic_links_pruned_as_isolated": len(links) - len(kept_links),
        "synthetic_nodes_pruned_as_isolated": len(nodes) - len(kept_nodes),
        "connector_links_pruned_as_isolated": len(connectors) - len(kept_connectors),
    }
    return kept_nodes, kept_links, kept_connectors, stats


def write_augmented_network(
    network: NetworkXml,
    nodes: dict[tuple[int, int], dict[str, Any]],
    links: list[dict[str, Any]],
    connectors: list[dict[str, Any]],
    out_path: Path,
) -> None:
    root = network.root
    nodes_el = root.find("nodes")
    links_el = root.find("links")
    for node in nodes.values():
        ET.SubElement(
            nodes_el,
            "node",
            {
                "id": node["node_id"],
                "x": f'{node["x"]:.3f}',
                "y": f'{node["y"]:.3f}',
            },
        )
    for item in [*links, *connectors]:
        ET.SubElement(
            links_el,
            "link",
            {
                "id": item["link_id"],
                "from": item["from_node"],
                "to": item["to_node"],
                "length": f'{item["length"]:.3f}',
                "freespeed": f'{item["freespeed"]:.4f}',
                "capacity": "900.000",
                "permlanes": "1.00",
                "modes": "car,pt",
            },
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out_path, "wt", encoding="utf-8", newline="\n") as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n')
        f.write('<!DOCTYPE network SYSTEM "http://www.matsim.org/files/dtd/network_v1.dtd">\n\n')
        f.write(ET.tostring(root, encoding="unicode"))
        f.write("\n")


def write_links_geojson(path: Path, links: list[dict[str, Any]], nodes_by_id: dict[str, dict[str, Any]], extra_type: str) -> None:
    features = []
    for link in links:
        from_node = nodes_by_id.get(link["from_node"])
        to_node = nodes_by_id.get(link["to_node"])
        if not from_node or not to_node:
            continue
        props = {k: v for k, v in link.items() if k not in {"from_key", "to_key"}}
        props["synthetic_type"] = extra_type
        features.append(
            {
                "type": "Feature",
                "properties": props,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[from_node["x"], from_node["y"]], [to_node["x"], to_node["y"]]],
                },
            }
        )
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", type=Path, default=DEFAULT_NETWORK)
    parser.add_argument("--boundary", type=Path, default=DEFAULT_BOUNDARY)
    parser.add_argument("--trajectories", type=Path, default=DEFAULT_TRAJECTORIES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--buffer-m", type=float, default=2000.0)
    parser.add_argument("--missing-threshold-m", type=float, default=80.0)
    parser.add_argument("--max-segment-len-m", type=float, default=80.0)
    parser.add_argument("--node-merge-tolerance-m", type=float, default=8.0)
    parser.add_argument("--connector-threshold-m", type=float, default=120.0)
    parser.add_argument("--min-component-connector-links", type=int, default=1)
    parser.add_argument("--synthetic-freespeed-mps", type=float, default=13.89)
    parser.add_argument("--snap-k", type=int, default=20)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    network = NetworkXml(args.network, args.snap_k)
    buffer_geom = load_boundary_buffer(args.boundary, args.buffer_m)
    trajectories = load_trajectories(args.trajectories)
    nodes, links, stats = build_synthetic_segments(
        network,
        trajectories,
        buffer_geom,
        args.missing_threshold_m,
        args.max_segment_len_m,
        args.node_merge_tolerance_m,
    )
    links, connectors = assign_ids_and_connectors(network, nodes, links, args.connector_threshold_m, args.synthetic_freespeed_mps)
    nodes, links, connectors, prune_stats = prune_isolated_synthetic_components(
        nodes,
        links,
        connectors,
        args.min_component_connector_links,
    )
    augmented_network = output_dir / "network_augmented_with_bus_trajectory_links.xml.gz"
    write_augmented_network(network, nodes, links, connectors, augmented_network)

    synthetic_nodes_by_id = {node["node_id"]: node for node in nodes.values()}
    road_nodes_by_id = {node_id: {"x": xy[0], "y": xy[1]} for node_id, xy in network.nodes.items()}
    all_nodes_by_id = {**road_nodes_by_id, **synthetic_nodes_by_id}
    synthetic_geojson = output_dir / "synthetic_bus_trajectory_links_epsg32650.geojson"
    connector_geojson = output_dir / "synthetic_bus_connector_links_epsg32650.geojson"
    write_links_geojson(synthetic_geojson, links, all_nodes_by_id, "bus_trajectory_missing_road")
    write_links_geojson(connector_geojson, connectors, all_nodes_by_id, "connector_to_existing_road_node")

    qa_rows = []
    for link in links:
        qa_rows.append(
            {
                "link_id": link["link_id"],
                "type": "synthetic_bus_trajectory",
                "length_m": round(link["length"], 3),
                "freespeed_mps": round(link["freespeed"], 4),
                "modes": "car,pt",
                "source_line_id": link["source_line_id"],
                "source_line_name": link["source_line_name"],
                "mid_nearest_road_distance_m": round(link["mid_nearest_road_distance_m"], 3),
            }
        )
    for link in connectors:
        qa_rows.append(
            {
                "link_id": link["link_id"],
                "type": "synthetic_connector",
                "length_m": round(link["length"], 3),
                "freespeed_mps": round(link["freespeed"], 4),
                "modes": "car,pt",
                "source_line_id": "",
                "source_line_name": "",
                "mid_nearest_road_distance_m": round(link["connector_distance_m"], 3),
            }
        )
    qa_path = output_dir / "synthetic_bus_road_links_qa.csv"
    with qa_path.open("w", encoding="utf-8-sig", newline="") as f:
        import csv

        writer = csv.DictWriter(
            f,
            fieldnames=["link_id", "type", "length_m", "freespeed_mps", "modes", "source_line_id", "source_line_name", "mid_nearest_road_distance_m"],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(qa_rows)

    summary = {
        "created_by": "scripts/augment_fuzhou_road_network_from_bus_trajectories.py",
        "inputs": {
            "network": str(args.network),
            "boundary": str(args.boundary),
            "trajectories": str(args.trajectories),
        },
        "outputs": {
            "augmented_network": str(augmented_network),
            "synthetic_links_geojson": str(synthetic_geojson),
            "connector_links_geojson": str(connector_geojson),
            "qa_csv": str(qa_path),
            "summary_json": str(output_dir / "bus_osm_augmentation_summary.json"),
        },
        "parameters": {
            "buffer_m": args.buffer_m,
            "missing_threshold_m": args.missing_threshold_m,
            "max_segment_len_m": args.max_segment_len_m,
            "node_merge_tolerance_m": args.node_merge_tolerance_m,
            "connector_threshold_m": args.connector_threshold_m,
            "min_component_connector_links": args.min_component_connector_links,
            "synthetic_freespeed_mps": args.synthetic_freespeed_mps,
            "synthetic_modes": "car,pt",
        },
        "counts": {
            "original_nodes": len(network.nodes),
            "original_links": len(network.links),
            "synthetic_nodes": len(nodes),
            "synthetic_bus_trajectory_links": len(links),
            "synthetic_connector_links": len(connectors),
            "augmented_nodes": len(network.nodes) + len(nodes),
            "augmented_links": len(network.links) + len(links) + len(connectors),
            **stats,
            **prune_stats,
        },
    }
    summary_path = output_dir / "bus_osm_augmentation_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary["counts"], ensure_ascii=False, indent=2))
    print(f"Wrote {augmented_network}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
