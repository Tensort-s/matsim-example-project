#!/usr/bin/env python
"""Visualize Fuzhou AMap bus-stop POI tiled-search outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
from shapely.geometry import Point


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = PROJECT_ROOT / "data" / "transit" / "fuzhou_bus_stop_pois_amap"
DEFAULT_BOUNDARY = PROJECT_ROOT / "data" / "osm" / "fuzhou_city_23" / "fuzhou_city_23_boundary.geojson"
DEFAULT_OSM_STOPS = PROJECT_ROOT / "data" / "transit" / "fuzhou_bus_osm" / "fuzhou_bus_osm_stops.geojson"


def read_summary(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_pois(input_dir: Path) -> gpd.GeoDataFrame:
    csv_path = input_dir / "amap_bus_stop_pois_unique.csv"
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    gdf = gpd.GeoDataFrame(
        df,
        geometry=[Point(xy) for xy in zip(df["lon_wgs84"], df["lat_wgs84"])],
        crs="EPSG:4326",
    )
    return gdf.to_crs("EPSG:32650")


def setup_axis(ax, title: str, boundary_32650: gpd.GeoDataFrame) -> None:
    minx, miny, maxx, maxy = boundary_32650.total_bounds
    pad_x = (maxx - minx) * 0.05
    pad_y = (maxy - miny) * 0.05
    ax.set_xlim(minx - pad_x, maxx + pad_x)
    ax.set_ylim(miny - pad_y, maxy + pad_y)
    ax.set_aspect("equal", adjustable="box")
    ax.set_title(title)
    ax.set_xlabel("Easting (EPSG:32650, m)")
    ax.set_ylabel("Northing (EPSG:32650, m)")
    ax.grid(alpha=0.18, linewidth=0.35)


def plot_overview(pois: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame, tiles: gpd.GeoDataFrame, out_png: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 8))
    if not tiles.empty:
        tiles.boundary.plot(ax=ax, color="#cccccc", linewidth=0.25, alpha=0.6)
    boundary.boundary.plot(ax=ax, color="#111111", linewidth=1.4)

    inside = pois[pois["inside_boundary"].astype(bool)]
    buffer_only = pois[(~pois["inside_boundary"].astype(bool)) & (pois["inside_boundary_500m_buffer"].astype(bool))]
    outside = pois[~pois["inside_boundary_500m_buffer"].astype(bool)]

    if not inside.empty:
        inside.plot(ax=ax, color="#1f78b4", markersize=6, alpha=0.78, label=f"inside boundary ({len(inside)})")
    if not buffer_only.empty:
        buffer_only.plot(ax=ax, color="#ff7f00", markersize=10, alpha=0.85, label=f"within 500m buffer ({len(buffer_only)})")
    if not outside.empty:
        outside.plot(ax=ax, color="#e31a1c", markersize=12, alpha=0.9, label=f"outside buffer ({len(outside)})")

    setup_axis(ax, f"AMap Fuzhou bus-stop POIs: {len(pois)} unique IDs", boundary)
    ax.legend(loc="lower left", frameon=True)
    fig.tight_layout()
    fig.savefig(out_png, dpi=220)
    plt.close(fig)


def plot_density(pois: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame, out_png: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 8))
    boundary.boundary.plot(ax=ax, color="#111111", linewidth=1.2)
    xs = pois.geometry.x
    ys = pois.geometry.y
    hb = ax.hexbin(xs, ys, gridsize=55, mincnt=1, cmap="magma")
    cb = fig.colorbar(hb, ax=ax)
    cb.set_label("Bus-stop POI count")
    setup_axis(ax, "AMap bus-stop POI density", boundary)
    fig.tight_layout()
    fig.savefig(out_png, dpi=220)
    plt.close(fig)


def plot_tile_coverage(tiles: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame, out_png: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 8))
    if not tiles.empty and "kept_records" in tiles.columns:
        tiles.plot(
            ax=ax,
            column="kept_records",
            cmap="viridis",
            linewidth=0.25,
            edgecolor="#777777",
            alpha=0.72,
            legend=True,
            legend_kwds={"label": "Kept bus-stop POIs per tile"},
        )
    boundary.boundary.plot(ax=ax, color="#111111", linewidth=1.3)
    setup_axis(ax, "AMap tiled polygon search coverage", boundary)
    fig.tight_layout()
    fig.savefig(out_png, dpi=220)
    plt.close(fig)


def plot_quality_panel(
    pois: gpd.GeoDataFrame,
    boundary: gpd.GeoDataFrame,
    osm_stops: gpd.GeoDataFrame | None,
    out_png: Path,
) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(16, 5.4))

    duplicate_counts = pois["duplicate_count"].fillna(1).astype(int)
    axes[0].hist(duplicate_counts, bins=range(1, int(duplicate_counts.max()) + 3), color="#377eb8", alpha=0.85)
    axes[0].set_title("Duplicate observations per POI ID")
    axes[0].set_xlabel("duplicate_count")
    axes[0].set_ylabel("POI IDs")
    axes[0].grid(alpha=0.18)

    boundary_counts = {
        "inside": int(pois["inside_boundary"].astype(bool).sum()),
        "buffer only": int((~pois["inside_boundary"].astype(bool) & pois["inside_boundary_500m_buffer"].astype(bool)).sum()),
        "outside buffer": int((~pois["inside_boundary_500m_buffer"].astype(bool)).sum()),
    }
    axes[1].bar(boundary_counts.keys(), boundary_counts.values(), color=["#1f78b4", "#ff7f00", "#e31a1c"])
    axes[1].set_title("Boundary status")
    axes[1].set_ylabel("POI IDs")
    for idx, value in enumerate(boundary_counts.values()):
        axes[1].text(idx, value, str(value), ha="center", va="bottom")

    boundary.boundary.plot(ax=axes[2], color="#111111", linewidth=1.1)
    pois.plot(ax=axes[2], color="#1f78b4", markersize=4, alpha=0.5, label=f"AMap POIs ({len(pois)})")
    if osm_stops is not None and not osm_stops.empty:
        osm_stops.plot(ax=axes[2], color="#e41a1c", markersize=3, alpha=0.45, label=f"OSM stops ({len(osm_stops)})")
    setup_axis(axes[2], "AMap POIs vs OSM bus stops", boundary)
    axes[2].legend(loc="lower left")

    fig.suptitle("AMap bus-stop POI quality checks")
    fig.tight_layout()
    fig.savefig(out_png, dpi=220)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--boundary", type=Path, default=DEFAULT_BOUNDARY)
    parser.add_argument("--osm-stops", type=Path, default=DEFAULT_OSM_STOPS)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()

    input_dir = args.input_dir
    output_dir = args.output_dir or (input_dir / "visualization")
    output_dir.mkdir(parents=True, exist_ok=True)

    pois = load_pois(input_dir)
    boundary = gpd.read_file(args.boundary).to_crs("EPSG:32650")
    tiles_path = input_dir / "amap_bus_stop_pois_tiles.geojson"
    tiles = gpd.read_file(tiles_path).to_crs("EPSG:32650") if tiles_path.exists() else gpd.GeoDataFrame(geometry=[], crs="EPSG:32650")
    osm_stops = None
    if args.osm_stops.exists():
        osm_stops = gpd.read_file(args.osm_stops).to_crs("EPSG:32650")

    overview_png = output_dir / "amap_bus_stop_pois_overview.png"
    density_png = output_dir / "amap_bus_stop_pois_density.png"
    tiles_png = output_dir / "amap_bus_stop_pois_tile_coverage.png"
    quality_png = output_dir / "amap_bus_stop_pois_quality_panel.png"

    plot_overview(pois, boundary, tiles, overview_png)
    plot_density(pois, boundary, density_png)
    plot_tile_coverage(tiles, boundary, tiles_png)
    plot_quality_panel(pois, boundary, osm_stops, quality_png)

    summary = read_summary(input_dir / "amap_bus_stop_poi_fetch_summary.json")
    vis_summary = {
        "input_dir": str(input_dir),
        "poi_count": int(len(pois)),
        "inside_boundary_count": int(pois["inside_boundary"].astype(bool).sum()),
        "inside_boundary_500m_buffer_count": int(pois["inside_boundary_500m_buffer"].astype(bool).sum()),
        "tile_count": int(len(tiles)),
        "osm_stop_count": int(len(osm_stops)) if osm_stops is not None else None,
        "fetch_summary": {
            "request_count": summary.get("request_count"),
            "unique_poi_count": summary.get("unique_poi_count"),
            "saturation_warning_tile_count": summary.get("saturation_warning_tile_count"),
        },
        "outputs": [
            overview_png.name,
            density_png.name,
            tiles_png.name,
            quality_png.name,
        ],
    }
    (output_dir / "amap_bus_stop_pois_visualization_summary.json").write_text(
        json.dumps(vis_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(vis_summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
