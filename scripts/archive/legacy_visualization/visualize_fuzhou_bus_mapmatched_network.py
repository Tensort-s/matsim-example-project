#!/usr/bin/env python3
"""Visualize the map-matched Fuzhou bus road network.

Outputs:
- PNG preview of base road links + bus-used PT links + bus stops.
- GeoJSON of PT road links with route-use counts.
- GeoJSON of unique mapped bus stops.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.colors import LogNorm


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUS_DIR = ROOT / "data" / "transit" / "fuzhou_bus_matsim_network_20260709"
DEFAULT_NETWORK = DEFAULT_BUS_DIR / "bus_network_with_pt.xml.gz"
DEFAULT_ROUTE_LINKS = DEFAULT_BUS_DIR / "bus_route_link_sequences.csv"
DEFAULT_STOP_SNAP = DEFAULT_BUS_DIR / "bus_stop_link_snap.csv"
DEFAULT_OUT_DIR = DEFAULT_BUS_DIR / "visualization"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_network(path: Path) -> tuple[dict[str, tuple[float, float]], dict[str, dict[str, Any]]]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        root = ET.parse(f).getroot()
    nodes: dict[str, tuple[float, float]] = {}
    for node in root.find("nodes").findall("node"):  # type: ignore[union-attr]
        nodes[node.attrib["id"]] = (safe_float(node.attrib["x"]), safe_float(node.attrib["y"]))
    links: dict[str, dict[str, Any]] = {}
    for link in root.find("links").findall("link"):  # type: ignore[union-attr]
        link_id = link.attrib["id"]
        from_node = link.attrib["from"]
        to_node = link.attrib["to"]
        links[link_id] = {
            "id": link_id,
            "from": from_node,
            "to": to_node,
            "modes": link.attrib.get("modes", ""),
            "length": safe_float(link.attrib.get("length")),
            "coords": [nodes[from_node], nodes[to_node]],
        }
    return nodes, links


def route_link_counts(path: Path) -> Counter[str]:
    rows = read_csv(path)
    counts: Counter[str] = Counter()
    # Count unique route/link occurrences, not every repeated link row across
    # duplicated CSV accidents. Existing CSV is route sequence, so this is the
    # desired bus route usage count.
    for row in rows:
        counts[row["link_id"]] += 1
    return counts


def write_pt_links_geojson(path: Path, links: dict[str, dict[str, Any]], counts: Counter[str]) -> None:
    features = []
    for link_id, count in counts.items():
        link = links.get(link_id)
        if not link:
            continue
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "link_id": link_id,
                    "route_use_count": count,
                    "length_m": round(link["length"], 3),
                    "modes": link["modes"],
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[link["coords"][0][0], link["coords"][0][1]], [link["coords"][1][0], link["coords"][1][1]]],
                },
            }
        )
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False), encoding="utf-8")


def write_unique_stops_geojson(path: Path, stop_snap_csv: Path) -> int:
    rows = read_csv(stop_snap_csv)
    by_station: dict[str, dict[str, str]] = {}
    for row in rows:
        station_id = row.get("station_id") or f'{row.get("station_name")}_{row.get("x_epsg32650")}_{row.get("y_epsg32650")}'
        by_station.setdefault(station_id, row)
    features = []
    for station_id, row in by_station.items():
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "station_id": station_id,
                    "station_name": row.get("station_name", ""),
                    "link_id": row.get("link_id", ""),
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [safe_float(row.get("x_epsg32650")), safe_float(row.get("y_epsg32650"))],
                },
            }
        )
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False), encoding="utf-8")
    return len(features)


def visualize(
    network_path: Path,
    route_links_path: Path,
    stop_snap_path: Path,
    out_dir: Path,
    dpi: int,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    _, links = load_network(network_path)
    counts = route_link_counts(route_links_path)

    base_lines = []
    pt_lines = []
    pt_values = []
    for link in links.values():
        coords = link["coords"]
        base_lines.append(coords)
        count = counts.get(link["id"], 0)
        if count > 0:
            pt_lines.append(coords)
            pt_values.append(count)

    stops_rows = read_csv(stop_snap_path)
    unique_stops: dict[str, tuple[float, float]] = {}
    for row in stops_rows:
        sid = row.get("station_id") or row.get("station_name") or str(len(unique_stops))
        unique_stops.setdefault(sid, (safe_float(row.get("x_epsg32650")), safe_float(row.get("y_epsg32650"))))

    fig, ax = plt.subplots(figsize=(13, 11), dpi=dpi)
    ax.set_facecolor("#fbfbfb")

    base_collection = LineCollection(base_lines, colors="#d2d2d2", linewidths=0.25, alpha=0.35, zorder=1)
    ax.add_collection(base_collection)

    if pt_lines:
        norm = LogNorm(vmin=max(1, min(pt_values)), vmax=max(pt_values))
        pt_collection = LineCollection(pt_lines, cmap="viridis", norm=norm, linewidths=0.75, alpha=0.95, zorder=2)
        pt_collection.set_array(pt_values)
        ax.add_collection(pt_collection)
        cbar = fig.colorbar(pt_collection, ax=ax, shrink=0.72, pad=0.01)
        cbar.set_label("Bus route-use count per road link", fontsize=9)

    if unique_stops:
        xs = [xy[0] for xy in unique_stops.values()]
        ys = [xy[1] for xy in unique_stops.values()]
        ax.scatter(xs, ys, s=4, color="#e74c3c", alpha=0.45, linewidths=0, label="Bus stops", zorder=3)

    ax.autoscale()
    ax.set_aspect("equal", adjustable="box")
    ax.set_title("Fuzhou map-matched bus routes on MATSim/OSM road links", fontsize=13)
    ax.set_xlabel("EPSG:32650 x (m)")
    ax.set_ylabel("EPSG:32650 y (m)")
    ax.legend(loc="lower left", frameon=True)
    ax.grid(color="#eeeeee", linewidth=0.35)

    png_path = out_dir / "bus_mapmatched_pt_network_epsg32650.png"
    fig.tight_layout()
    fig.savefig(png_path)
    plt.close(fig)

    pt_geojson = out_dir / "bus_mapmatched_pt_links_epsg32650.geojson"
    stops_geojson = out_dir / "bus_mapmatched_unique_stops_epsg32650.geojson"
    write_pt_links_geojson(pt_geojson, links, counts)
    unique_stop_count = write_unique_stops_geojson(stops_geojson, stop_snap_path)

    summary = {
        "network": str(network_path),
        "route_link_sequences": str(route_links_path),
        "stop_snap": str(stop_snap_path),
        "outputs": {
            "png": str(png_path),
            "pt_links_geojson": str(pt_geojson),
            "unique_stops_geojson": str(stops_geojson),
        },
        "counts": {
            "network_links_total": len(links),
            "pt_used_links": len(counts),
            "route_link_sequence_rows": sum(counts.values()),
            "unique_stop_count": unique_stop_count,
            "max_route_use_count": max(counts.values()) if counts else 0,
            "median_route_use_count": sorted(counts.values())[len(counts) // 2] if counts else 0,
        },
        "coordinate_system": "EPSG:32650",
    }
    summary_path = out_dir / "bus_mapmatched_network_visualization_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", type=Path, default=DEFAULT_NETWORK)
    parser.add_argument("--route-links", type=Path, default=DEFAULT_ROUTE_LINKS)
    parser.add_argument("--stop-snap", type=Path, default=DEFAULT_STOP_SNAP)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--dpi", type=int, default=220)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = visualize(args.network, args.route_links, args.stop_snap, args.out_dir, args.dpi)
    print(json.dumps(summary["counts"], ensure_ascii=False, indent=2))
    print(f"Wrote {summary['outputs']['png']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
