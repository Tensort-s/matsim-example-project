#!/usr/bin/env python3
"""Visualize final AMap Fuzhou bus stop/line source data.

This visualizes the cleaned final AMap stop/line dataset before MATSim
boundary clipping or map matching.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.colors import LogNorm


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FINAL_DIR = ROOT / "data" / "transit" / "fuzhou_bus_amap_stop_line_final_20260709"
DEFAULT_LINES = DEFAULT_FINAL_DIR / "bus_lines" / "amap_bus_line_trajectories_full.geojson"
DEFAULT_STOPS = DEFAULT_FINAL_DIR / "bus_lines" / "amap_bus_stops_complete.csv"
DEFAULT_STOPS_BY_LINE = DEFAULT_FINAL_DIR / "bus_lines" / "amap_bus_stops_by_line_full.csv"
DEFAULT_OUT_DIR = DEFAULT_FINAL_DIR / "visualization"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_lines(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    features = []
    for feature in data.get("features", []):
        props = feature.get("properties") or {}
        coords = feature.get("geometry", {}).get("coordinates") or []
        if feature.get("geometry", {}).get("type") == "LineString" and len(coords) >= 2:
            features.append({"properties": props, "coordinates": coords})
    return features


def load_stops(path: Path) -> list[dict[str, Any]]:
    rows = read_csv(path)
    stops = []
    for row in rows:
        lon = safe_float(row.get("lon_wgs84"))
        lat = safe_float(row.get("lat_wgs84"))
        if lon and lat:
            stops.append(row)
    return stops


def write_preview_geojson(lines: list[dict[str, Any]], stops: list[dict[str, Any]], out_dir: Path) -> tuple[Path, Path]:
    line_features = [
        {
            "type": "Feature",
            "properties": feature["properties"],
            "geometry": {"type": "LineString", "coordinates": feature["coordinates"]},
        }
        for feature in lines
    ]
    stop_features = [
        {
            "type": "Feature",
            "properties": {
                "station_id": row.get("station_id", row.get("stop_id", row.get("poi_id", ""))),
                "name": row.get("name", row.get("station_name", "")),
                "source": "amap_bus_stops_complete",
            },
            "geometry": {"type": "Point", "coordinates": [safe_float(row.get("lon_wgs84")), safe_float(row.get("lat_wgs84"))]},
        }
        for row in stops
    ]
    lines_path = out_dir / "amap_bus_lines_full_wgs84_preview.geojson"
    stops_path = out_dir / "amap_bus_stops_complete_wgs84_preview.geojson"
    lines_path.write_text(json.dumps({"type": "FeatureCollection", "features": line_features}, ensure_ascii=False), encoding="utf-8")
    stops_path.write_text(json.dumps({"type": "FeatureCollection", "features": stop_features}, ensure_ascii=False), encoding="utf-8")
    return lines_path, stops_path


def visualize(lines: list[dict[str, Any]], stops: list[dict[str, Any]], stops_by_line_path: Path, out_dir: Path, dpi: int) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)

    line_segments = [feature["coordinates"] for feature in lines]
    route_counts_by_base: Counter[str] = Counter()
    for feature in lines:
        name = feature["properties"].get("line_name", "")
        base = name.split("(", 1)[0]
        route_counts_by_base[base] += 1

    stop_use_counts: Counter[str] = Counter()
    if stops_by_line_path.exists():
        for row in read_csv(stops_by_line_path):
            station_id = row.get("station_id") or row.get("amap_stop_id") or row.get("station_name")
            stop_use_counts[station_id] += 1

    stop_x = [safe_float(row.get("lon_wgs84")) for row in stops]
    stop_y = [safe_float(row.get("lat_wgs84")) for row in stops]
    stop_sizes = []
    for row in stops:
        station_id = row.get("station_id") or row.get("amap_stop_id") or row.get("name")
        stop_sizes.append(max(2.0, min(16.0, 1.5 + stop_use_counts.get(station_id, 1) ** 0.5)))

    fig, ax = plt.subplots(figsize=(12.5, 10.5), dpi=dpi)
    ax.set_facecolor("#fbfbfb")
    if line_segments:
        line_collection = LineCollection(line_segments, colors="#2563eb", linewidths=0.35, alpha=0.33, zorder=1)
        ax.add_collection(line_collection)
    if stops:
        ax.scatter(stop_x, stop_y, s=stop_sizes, color="#e11d48", alpha=0.55, linewidths=0, zorder=2, label="AMap bus stops")
    ax.autoscale()
    ax.set_aspect("equal", adjustable="box")
    ax.set_title("Fuzhou AMap final bus lines and stops (full source dataset)", fontsize=13)
    ax.set_xlabel("Longitude WGS84")
    ax.set_ylabel("Latitude WGS84")
    ax.grid(color="#eeeeee", linewidth=0.35)
    ax.legend(loc="lower left", frameon=True)
    fig.tight_layout()
    png_path = out_dir / "amap_bus_lines_and_stops_full_wgs84.png"
    fig.savefig(png_path)
    plt.close(fig)

    lines_geojson, stops_geojson = write_preview_geojson(lines, stops, out_dir)
    summary = {
        "outputs": {
            "png": str(png_path),
            "lines_preview_geojson": str(lines_geojson),
            "stops_preview_geojson": str(stops_geojson),
        },
        "counts": {
            "line_trajectory_features": len(lines),
            "unique_route_base_names": len(route_counts_by_base),
            "complete_stop_points": len(stops),
            "stops_with_line_usage": len(stop_use_counts),
            "max_stop_line_usage": max(stop_use_counts.values()) if stop_use_counts else 0,
        },
        "coordinate_system": "WGS84 lon/lat",
        "note": "This is the final AMap source stop/line dataset before MATSim boundary clipping or map matching.",
    }
    summary_path = out_dir / "amap_bus_lines_and_stops_full_visualization_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lines", type=Path, default=DEFAULT_LINES)
    parser.add_argument("--stops", type=Path, default=DEFAULT_STOPS)
    parser.add_argument("--stops-by-line", type=Path, default=DEFAULT_STOPS_BY_LINE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--dpi", type=int, default=220)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    lines = load_lines(args.lines)
    stops = load_stops(args.stops)
    summary = visualize(lines, stops, args.stops_by_line, args.out_dir, args.dpi)
    print(json.dumps(summary["counts"], ensure_ascii=False, indent=2))
    print(f"Wrote {summary['outputs']['png']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
