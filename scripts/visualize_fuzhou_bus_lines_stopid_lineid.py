#!/usr/bin/env python
"""Visualize Fuzhou AMap bus data fetched via stopid -> lineid."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = PROJECT_ROOT / "data" / "transit" / "fuzhou_bus_amap_stopid_lineid"
DEFAULT_BOUNDARY = PROJECT_ROOT / "data" / "osm" / "fuzhou_city_23" / "fuzhou_city_23_boundary.geojson"
DEFAULT_OUTPUT_DIR = DEFAULT_INPUT_DIR / "visualization"


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path, encoding="utf-8-sig")


def setup_map(ax, boundary: gpd.GeoDataFrame, title: str) -> None:
    minx, miny, maxx, maxy = boundary.total_bounds
    pad_x = (maxx - minx) * 0.07
    pad_y = (maxy - miny) * 0.07
    ax.set_xlim(minx - pad_x, maxx + pad_x)
    ax.set_ylim(miny - pad_y, maxy + pad_y)
    ax.set_aspect("equal", adjustable="box")
    ax.set_title(title)
    ax.set_xlabel("Easting (EPSG:32650, m)")
    ax.set_ylabel("Northing (EPSG:32650, m)")
    ax.grid(alpha=0.16, linewidth=0.35)


def plot_network_overview(lines: gpd.GeoDataFrame, stops: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame, out_png: Path) -> None:
    fig, ax = plt.subplots(figsize=(13, 10))
    if not lines.empty:
        lines.plot(ax=ax, color="#2166ac", linewidth=0.45, alpha=0.22, label=f"line trajectories ({len(lines)})")
    boundary.boundary.plot(ax=ax, color="#111111", linewidth=1.4)

    inside = stops[stops["inside_boundary"].astype(bool)]
    buffer_only = stops[(~stops["inside_boundary"].astype(bool)) & stops["inside_boundary_2km_buffer"].astype(bool)]
    outside = stops[~stops["inside_boundary_2km_buffer"].astype(bool)]
    if not inside.empty:
        inside.plot(ax=ax, color="#111111", markersize=3, alpha=0.55, label=f"stops inside ({len(inside)})")
    if not buffer_only.empty:
        buffer_only.plot(ax=ax, color="#ff7f00", markersize=8, alpha=0.75, label=f"stops in 2km buffer ({len(buffer_only)})")
    if not outside.empty:
        outside.plot(ax=ax, color="#e31a1c", markersize=8, alpha=0.75, label=f"stops outside 2km ({len(outside)})")

    setup_map(ax, boundary, f"Fuzhou bus network from AMap stopid/lineid\n{len(lines)} trajectories, {len(stops)} complete stops")
    ax.legend(loc="lower left", frameon=True)
    fig.tight_layout()
    fig.savefig(out_png, dpi=220)
    plt.close(fig)


def plot_line_density(lines: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame, out_png: Path) -> None:
    fig, ax = plt.subplots(figsize=(13, 10))
    boundary.boundary.plot(ax=ax, color="#111111", linewidth=1.3)
    if not lines.empty:
        vertices_x = []
        vertices_y = []
        for geom in lines.geometry:
            if geom is None or geom.is_empty:
                continue
            geoms = list(geom.geoms) if geom.geom_type == "MultiLineString" else [geom]
            for line in geoms:
                xs, ys = line.xy
                vertices_x.extend(xs)
                vertices_y.extend(ys)
        hb = ax.hexbin(vertices_x, vertices_y, gridsize=75, mincnt=1, cmap="viridis")
        cb = fig.colorbar(hb, ax=ax)
        cb.set_label("Trajectory vertex count")
    setup_map(ax, boundary, "Bus line trajectory density")
    fig.tight_layout()
    fig.savefig(out_png, dpi=220)
    plt.close(fig)


def plot_stop_density(stops: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame, out_png: Path) -> None:
    fig, ax = plt.subplots(figsize=(12, 9))
    boundary.boundary.plot(ax=ax, color="#111111", linewidth=1.2)
    hb = ax.hexbin(stops.geometry.x, stops.geometry.y, gridsize=60, mincnt=1, cmap="magma")
    cb = fig.colorbar(hb, ax=ax)
    cb.set_label("Complete stop count")
    setup_map(ax, boundary, "Complete bus-stop density")
    fig.tight_layout()
    fig.savefig(out_png, dpi=220)
    plt.close(fig)


def plot_stop_sources(stops: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame, out_png: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(15, 6))

    source_counts = stops["source_types"].fillna("(missing)").value_counts()
    axes[0].barh(source_counts.index[::-1], source_counts.values[::-1], color="#4daf4a")
    axes[0].set_title("Complete stop source types")
    axes[0].set_xlabel("Stop count")
    for idx, value in enumerate(source_counts.values[::-1]):
        axes[0].text(value, idx, str(int(value)), va="center", ha="left")

    color_map = {
        "lineid_busstop;poi": "#1f78b4",
        "lineid_busstop": "#984ea3",
        "poi": "#ff7f00",
    }
    for label, color in color_map.items():
        sub = stops[stops["source_types"].fillna("") == label]
        if not sub.empty:
            sub.plot(ax=axes[1], color=color, markersize=5, alpha=0.65, label=f"{label} ({len(sub)})")
    boundary.boundary.plot(ax=axes[1], color="#111111", linewidth=1.2)
    setup_map(axes[1], boundary, "Stop source map")
    axes[1].legend(loc="lower left", frameon=True)

    fig.tight_layout()
    fig.savefig(out_png, dpi=220)
    plt.close(fig)


def plot_line_coverage(lines_df: pd.DataFrame, service_df: pd.DataFrame, out_png: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(15, 10))

    line_type_counts = lines_df["line_type"].fillna("(missing)").replace("", "(missing)").value_counts().head(12)
    axes[0, 0].barh(line_type_counts.index[::-1], line_type_counts.values[::-1], color="#377eb8")
    axes[0, 0].set_title("Line type distribution")
    axes[0, 0].set_xlabel("Line/direction records")

    axes[0, 1].hist(pd.to_numeric(lines_df["stop_count"], errors="coerce").dropna(), bins=35, color="#984ea3", alpha=0.85)
    axes[0, 1].set_title("Stops per line/direction")
    axes[0, 1].set_xlabel("Stop count")
    axes[0, 1].set_ylabel("Records")
    axes[0, 1].grid(alpha=0.15)

    has_headway_lines = set()
    if not service_df.empty and "headway_minutes" in service_df.columns:
        headway = pd.to_numeric(service_df["headway_minutes"], errors="coerce")
        nonempty = service_df[headway.notna()].copy()
        nonempty["headway_minutes_num"] = headway[headway.notna()]
        has_headway_lines = set(nonempty["line_id"].astype(str))
    else:
        nonempty = pd.DataFrame()
    counts = pd.Series(
        {
            "with headway": int(lines_df["line_id"].astype(str).isin(has_headway_lines).sum()),
            "missing headway": int((~lines_df["line_id"].astype(str).isin(has_headway_lines)).sum()),
        }
    )
    axes[1, 0].bar(counts.index, counts.values, color=["#4daf4a", "#e41a1c"])
    axes[1, 0].set_title("Headway coverage")
    axes[1, 0].set_ylabel("Line/direction records")
    for idx, value in enumerate(counts.values):
        axes[1, 0].text(idx, value, str(int(value)), ha="center", va="bottom")

    if not nonempty.empty:
        axes[1, 1].hist(nonempty["headway_minutes_num"], bins=25, color="#ff7f00", alpha=0.85)
    axes[1, 1].set_title("Parsed headway distribution")
    axes[1, 1].set_xlabel("Headway (minutes)")
    axes[1, 1].set_ylabel("Records")
    axes[1, 1].grid(alpha=0.15)

    fig.suptitle(f"AMap stopid/lineid bus data coverage: {len(lines_df)} line/direction records")
    fig.tight_layout()
    fig.savefig(out_png, dpi=220)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--boundary", type=Path, default=DEFAULT_BOUNDARY)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    boundary = gpd.read_file(args.boundary).to_crs("EPSG:32650")
    lines = gpd.read_file(args.input_dir / "amap_bus_line_trajectories_full.geojson").to_crs("EPSG:32650")
    stops = gpd.read_file(args.input_dir / "amap_bus_stops_complete.geojson").to_crs("EPSG:32650")
    lines_df = read_csv(args.input_dir / "amap_bus_lines_full.csv")
    service_df = read_csv(args.input_dir / "amap_bus_service_frequency_full.csv")

    network_png = args.output_dir / "amap_bus_full_network_overview.png"
    line_density_png = args.output_dir / "amap_bus_full_line_density.png"
    stop_density_png = args.output_dir / "amap_bus_full_stop_density.png"
    stop_sources_png = args.output_dir / "amap_bus_full_stop_sources.png"
    coverage_png = args.output_dir / "amap_bus_full_line_coverage.png"

    plot_network_overview(lines, stops, boundary, network_png)
    plot_line_density(lines, boundary, line_density_png)
    plot_stop_density(stops, boundary, stop_density_png)
    plot_stop_sources(stops, boundary, stop_sources_png)
    plot_line_coverage(lines_df, service_df, coverage_png)

    summary = {
        "input_dir": str(args.input_dir),
        "line_trajectories": int(len(lines)),
        "complete_stops": int(len(stops)),
        "line_records": int(len(lines_df)),
        "service_frequency_rows": int(len(service_df)),
        "outputs": [
            network_png.name,
            line_density_png.name,
            stop_density_png.name,
            stop_sources_png.name,
            coverage_png.name,
        ],
    }
    (args.output_dir / "amap_bus_full_visualization_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
