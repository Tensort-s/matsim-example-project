#!/usr/bin/env python3
"""Prepare Hong Kong fixed-link administrative boundary for MATSim.

The source is the 2021 Population Census district boundary shapefile.  District
polygons are split into physical land components, then components with fixed
road, bridge, tunnel, or dam access are retained for the traffic model boundary.
Disconnected outlying islands are documented in the component inventory but are
excluded from the dissolved model boundary.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import matplotlib.pyplot as plt
from shapely.geometry import MultiPolygon, Polygon


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE = (
    ROOT
    / "data"
    / "boundary"
    / "hongkong"
    / "2021_Population_Census_Statistics_and_Boundar_SHP"
    / "DC_21C_converted.shp"
)
DEFAULT_OUT_DIR = ROOT / "data" / "boundary" / "hongkong" / "processed"
TARGET_CRS = "EPSG:2326"
WGS84 = "EPSG:4326"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--simplify-m", type=float, default=20.0)
    return parser.parse_args()


def component_name(area_km2: float, lon: float, lat: float) -> tuple[bool, str, str]:
    """Classify dissolved land components by fixed-link access.

    The rules intentionally use broad centroid and area windows because the
    source file has no island-name attribute after district dissolve.
    """
    if area_km2 > 700:
        return True, "mainland_new_territories_kowloon", "Largest contiguous mainland/New Territories/Kowloon landmass"
    if 140 <= area_km2 <= 170 and 113.88 <= lon <= 114.02 and 22.22 <= lat <= 22.32:
        return True, "lantau", "Lantau Island has fixed road links via Tsing Ma/Kap Shui Mun and Tuen Mun-Chek Lap Kok"
    if 70 <= area_km2 <= 90 and 114.12 <= lon <= 114.27 and 22.20 <= lat <= 22.29:
        return True, "hong_kong_island", "Hong Kong Island is connected to Kowloon by road tunnels"
    if 10 <= area_km2 <= 20 and 113.88 <= lon <= 113.96 and 22.28 <= lat <= 22.34:
        return True, "chek_lap_kok_airport", "Airport island is connected to Lantau and regional road links"
    if 8 <= area_km2 <= 14 and 114.07 <= lon <= 114.12 and 22.32 <= lat <= 22.37:
        return True, "tsing_yi", "Tsing Yi is connected by fixed road bridges"
    if 1.0 <= area_km2 <= 2.0 and 114.13 <= lon <= 114.18 and 22.22 <= lat <= 22.25:
        return True, "ap_lei_chau", "Ap Lei Chau is connected to Hong Kong Island by road bridge"
    if 0.7 <= area_km2 <= 1.2 and 114.04 <= lon <= 114.08 and 22.33 <= lat <= 22.37:
        return True, "ma_wan", "Ma Wan has fixed road access through the Lantau Link"
    if 5 <= area_km2 <= 8 and 114.29 <= lon <= 114.34 and 22.34 <= lat <= 22.38:
        return True, "high_island", "High Island is connected to Sai Kung by dam roads"
    return False, "outlying_island_without_fixed_road_link", "Excluded: no fixed road/bridge/tunnel connection in this boundary product"


def explode_union(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    dissolved = gdf.geometry.union_all()
    parts = list(dissolved.geoms) if isinstance(dissolved, MultiPolygon) else [dissolved]
    components = gpd.GeoDataFrame(
        {"component_id": list(range(len(parts))), "geometry": parts},
        crs=gdf.crs,
    )
    components["area_km2"] = components.geometry.area / 1_000_000.0
    ll = components.to_crs(WGS84)
    reps = ll.geometry.representative_point()
    components["lon"] = reps.x
    components["lat"] = reps.y
    classes = [component_name(row.area_km2, row.lon, row.lat) for row in components.itertuples()]
    components["retain"] = [x[0] for x in classes]
    components["component_name"] = [x[1] for x in classes]
    components["classification_note"] = [x[2] for x in classes]
    return components


def write_outputs(components: gpd.GeoDataFrame, source: Path, out_dir: Path, simplify_m: float) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)

    retained = components[components["retain"]].copy()
    boundary_geom = retained.geometry.union_all()
    boundary = gpd.GeoDataFrame(
        {
            "city": ["hong_kong"],
            "boundary_type": ["fixed_link_administrative_boundary"],
            "source": [str(source)],
            "retained_components": [int(len(retained))],
            "excluded_components": [int((~components["retain"]).sum())],
            "area_km2": [float(boundary_geom.area / 1_000_000.0)],
            "geometry": [boundary_geom],
        },
        crs=components.crs,
    )

    boundary_path = out_dir / "hong_kong_fixed_link_boundary.geojson"
    boundary_ll_path = out_dir / "hong_kong_fixed_link_boundary_wgs84.geojson"
    components_path = out_dir / "hong_kong_boundary_components.geojson"
    gpkg_path = out_dir / "hong_kong_fixed_link_boundary.gpkg"

    boundary.to_file(boundary_path, driver="GeoJSON")
    boundary.to_crs(WGS84).to_file(boundary_ll_path, driver="GeoJSON")
    components.to_file(components_path, driver="GeoJSON")
    boundary.to_file(gpkg_path, layer="fixed_link_boundary", driver="GPKG")
    components.to_file(gpkg_path, layer="components", driver="GPKG")

    png_path = out_dir / "hong_kong_fixed_link_boundary_preview.png"
    plot_boundary(components, boundary, png_path)

    simplified = boundary.copy()
    simplified["geometry"] = simplified.geometry.simplify(simplify_m, preserve_topology=True)
    simplified_ll_path = out_dir / "hong_kong_fixed_link_boundary_wgs84_simplified.geojson"
    simplified.to_crs(WGS84).to_file(simplified_ll_path, driver="GeoJSON")

    summary = {
        "source": str(source),
        "source_crs": str(components.crs),
        "target_crs": TARGET_CRS,
        "component_count": int(len(components)),
        "retained_component_count": int(len(retained)),
        "excluded_component_count": int((~components["retain"]).sum()),
        "retained_area_km2": float(boundary.geometry.area.iloc[0] / 1_000_000.0),
        "excluded_area_km2": float(components.loc[~components["retain"], "area_km2"].sum()),
        "retained_components": retained.sort_values("area_km2", ascending=False)[
            ["component_name", "area_km2", "lon", "lat", "classification_note"]
        ].to_dict(orient="records"),
        "outputs": {
            "boundary_geojson": str(boundary_path),
            "boundary_wgs84_geojson": str(boundary_ll_path),
            "components_geojson": str(components_path),
            "boundary_gpkg": str(gpkg_path),
            "preview_png": str(png_path),
            "simplified_wgs84_geojson": str(simplified_ll_path),
        },
    }
    summary_path = out_dir / "hong_kong_boundary_preparation_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    summary["outputs"]["summary_json"] = str(summary_path)
    return summary


def plot_boundary(components: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame, png_path: Path) -> None:
    retained = components[components["retain"]]
    excluded = components[~components["retain"]]

    fig, ax = plt.subplots(figsize=(10, 8), dpi=180)
    excluded.plot(ax=ax, color="#d9d9d9", edgecolor="#9e9e9e", linewidth=0.25, alpha=0.95)
    retained.plot(ax=ax, color="#4c78a8", edgecolor="#1f4e79", linewidth=0.45, alpha=0.95)
    boundary.boundary.plot(ax=ax, color="#17324d", linewidth=0.9)

    for _, row in retained.iterrows():
        if row["area_km2"] < 0.7:
            continue
        point = row.geometry.representative_point()
        label = row["component_name"].replace("_", " ")
        ax.annotate(label, (point.x, point.y), fontsize=6.5, color="#17324d", ha="center")

    ax.set_title("Hong Kong fixed-link model boundary from 2021 Census DC boundary", fontsize=11)
    ax.set_xlabel("Hong Kong 1980 Grid easting (m)")
    ax.set_ylabel("Hong Kong 1980 Grid northing (m)")
    ax.set_aspect("equal")
    ax.grid(True, linewidth=0.25, color="#eeeeee")

    handles = [
        plt.Line2D([0], [0], marker="s", color="none", markerfacecolor="#4c78a8", markeredgecolor="#1f4e79",
                   markersize=8, label="Retained fixed-link land components"),
        plt.Line2D([0], [0], marker="s", color="none", markerfacecolor="#d9d9d9", markeredgecolor="#9e9e9e",
                   markersize=8, label="Excluded disconnected outlying islands"),
    ]
    ax.legend(handles=handles, loc="lower right", fontsize=8, frameon=True)
    fig.tight_layout()
    fig.savefig(png_path, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    args = parse_args()
    source = args.source.resolve()
    gdf = gpd.read_file(source)
    if str(gdf.crs) != TARGET_CRS:
        gdf = gdf.to_crs(TARGET_CRS)
    components = explode_union(gdf)
    summary = write_outputs(components, source, args.out_dir, args.simplify_m)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
