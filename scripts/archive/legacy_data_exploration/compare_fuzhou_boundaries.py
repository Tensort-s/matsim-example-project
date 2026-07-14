from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from shapely import make_valid
from shapely.ops import unary_union


PROJECT_ROOT = Path(__file__).resolve().parents[1]

CUSTOM_BOUNDARY_PATH = (
    PROJECT_ROOT / "data" / "osm" / "fuzhou_city_23" / "fuzhou_city_23_boundary.geojson"
)
WORLDOD_REGIONS_PATH = (
    PROJECT_ROOT
    / "data"
    / "worldcommuting_od"
    / "330_CN_Fuzhou"
    / "CityAndRegionSplit"
    / "330_CN_Fuzhou"
    / "regions.shp"
)
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "boundary_comparison" / "fuzhou"
TARGET_CRS = "EPSG:32650"


def load_custom_boundary() -> gpd.GeoDataFrame:
    gdf = gpd.read_file(CUSTOM_BOUNDARY_PATH).to_crs(TARGET_CRS)
    gdf["source"] = "custom_ORIG_FID_23"
    return gdf[["source", "geometry"]]


def load_worldod_boundary() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    regions = gpd.read_file(WORLDOD_REGIONS_PATH).to_crs(TARGET_CRS)
    regions["geometry"] = regions.geometry.map(make_valid)
    boundary_geom = make_valid(unary_union(regions.geometry))
    boundary = gpd.GeoDataFrame(
        [{"source": "worldcommuting_od_330_CN_Fuzhou", "geometry": boundary_geom}],
        crs=TARGET_CRS,
    )
    return regions, boundary


def area_km2(geom) -> float:
    return float(geom.area / 1_000_000)


def metric_dict(custom_geom, world_geom) -> dict[str, float | str | list[float]]:
    intersection = custom_geom.intersection(world_geom)
    union = custom_geom.union(world_geom)
    custom_minus_world = custom_geom.difference(world_geom)
    world_minus_custom = world_geom.difference(custom_geom)

    custom_area = area_km2(custom_geom)
    world_area = area_km2(world_geom)
    inter_area = area_km2(intersection)
    union_area = area_km2(union)

    return {
        "target_crs": TARGET_CRS,
        "custom_boundary_source": str(CUSTOM_BOUNDARY_PATH),
        "worldod_regions_source": str(WORLDOD_REGIONS_PATH),
        "custom_area_km2": custom_area,
        "worldod_union_area_km2": world_area,
        "intersection_area_km2": inter_area,
        "union_area_km2": union_area,
        "custom_only_area_km2": area_km2(custom_minus_world),
        "worldod_only_area_km2": area_km2(world_minus_custom),
        "iou_intersection_over_union": inter_area / union_area if union_area else 0.0,
        "custom_covered_by_worldod_pct": inter_area / custom_area * 100 if custom_area else 0.0,
        "worldod_covered_by_custom_pct": inter_area / world_area * 100 if world_area else 0.0,
        "custom_bounds_m": [float(x) for x in custom_geom.bounds],
        "worldod_bounds_m": [float(x) for x in world_geom.bounds],
        "custom_centroid_m": [float(custom_geom.centroid.x), float(custom_geom.centroid.y)],
        "worldod_centroid_m": [float(world_geom.centroid.x), float(world_geom.centroid.y)],
        "centroid_distance_m": float(custom_geom.centroid.distance(world_geom.centroid)),
    }


def same_extent(custom_gdf: gpd.GeoDataFrame, world_gdf: gpd.GeoDataFrame) -> tuple[float, float, float, float]:
    combined = gpd.GeoSeries(
        list(custom_gdf.geometry) + list(world_gdf.geometry),
        crs=TARGET_CRS,
    )
    minx, miny, maxx, maxy = combined.total_bounds
    width = maxx - minx
    height = maxy - miny
    pad = max(width, height) * 0.08
    return minx - pad, maxx + pad, miny - pad, maxy + pad


def set_equal_scale(ax, extent: tuple[float, float, float, float], title: str) -> None:
    minx, maxx, miny, maxy = extent
    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)
    ax.set_aspect("equal", adjustable="box")
    ax.set_title(title, fontsize=12)
    ax.set_xlabel("Easting, EPSG:32650 (m)")
    ax.set_ylabel("Northing, EPSG:32650 (m)")
    ax.grid(True, linewidth=0.3, alpha=0.35)


def plot_comparison(
    custom: gpd.GeoDataFrame,
    world_boundary: gpd.GeoDataFrame,
    world_regions: gpd.GeoDataFrame,
) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    extent = same_extent(custom, world_boundary)

    custom_geom = custom.iloc[0].geometry
    world_geom = world_boundary.iloc[0].geometry
    intersection = gpd.GeoDataFrame([{"geometry": custom_geom.intersection(world_geom)}], crs=TARGET_CRS)
    custom_only = gpd.GeoDataFrame([{"geometry": custom_geom.difference(world_geom)}], crs=TARGET_CRS)
    world_only = gpd.GeoDataFrame([{"geometry": world_geom.difference(custom_geom)}], crs=TARGET_CRS)

    fig, axes = plt.subplots(1, 3, figsize=(18, 6), dpi=220)

    # Panel 1: custom boundary
    custom.plot(ax=axes[0], facecolor="#e66101", edgecolor="#8c2d04", alpha=0.35, linewidth=1.4)
    set_equal_scale(axes[0], extent, "A. Custom Fuzhou boundary\nGreenspace ORIG_FID=23")

    # Panel 2: WorldOD regions and dissolved boundary
    world_regions.plot(ax=axes[1], facecolor="#5ab4ac", edgecolor="#01665e", alpha=0.32, linewidth=0.25)
    world_boundary.boundary.plot(ax=axes[1], color="#003c30", linewidth=1.4)
    set_equal_scale(axes[1], extent, "B. WorldCommuting-OD Fuzhou\n330_CN_Fuzhou, 225 regions")

    # Panel 3: overlay and differences
    intersection.plot(ax=axes[2], facecolor="#4daf4a", edgecolor="none", alpha=0.50)
    custom_only.plot(ax=axes[2], facecolor="#e66101", edgecolor="#8c2d04", alpha=0.55, linewidth=0.5)
    world_only.plot(ax=axes[2], facecolor="#5ab4ac", edgecolor="#01665e", alpha=0.55, linewidth=0.5)
    custom.boundary.plot(ax=axes[2], color="#8c2d04", linewidth=1.2)
    world_boundary.boundary.plot(ax=axes[2], color="#003c30", linewidth=1.2)
    set_equal_scale(axes[2], extent, "C. Overlay / spatial difference")
    axes[2].legend(
        handles=[
            Patch(facecolor="#4daf4a", label="Overlap"),
            Patch(facecolor="#e66101", label="Custom only"),
            Patch(facecolor="#5ab4ac", label="WorldOD only"),
        ],
        loc="lower right",
        fontsize=9,
    )

    fig.suptitle("Fuzhou boundary comparison in the same CRS and scale (EPSG:32650)", fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.93))

    out = OUTPUT_DIR / "fuzhou_boundary_comparison_same_crs_scale.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    custom = load_custom_boundary()
    world_regions, world_boundary = load_worldod_boundary()

    custom_geom = custom.iloc[0].geometry
    world_geom = world_boundary.iloc[0].geometry
    metrics = metric_dict(custom_geom, world_geom)
    metrics["worldod_region_count"] = int(len(world_regions))

    metrics_path = OUTPUT_DIR / "fuzhou_boundary_comparison_metrics.json"
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    custom.to_file(OUTPUT_DIR / "custom_fuzhou_orig_fid_23_epsg32650.geojson", driver="GeoJSON")
    world_boundary.to_file(OUTPUT_DIR / "worldod_330_CN_Fuzhou_union_epsg32650.geojson", driver="GeoJSON")

    png_path = plot_comparison(custom, world_boundary, world_regions)

    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"figure={png_path}")
    print(f"metrics={metrics_path}")


if __name__ == "__main__":
    main()
