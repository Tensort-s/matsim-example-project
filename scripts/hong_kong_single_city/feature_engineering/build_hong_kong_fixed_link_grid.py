#!/usr/bin/env python3
"""Build a WEDAN-compatible regular grid for the Hong Kong fixed-link boundary."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
from typing import Any

# Keep Windows GIS environments from picking up an incompatible global PROJ DB.
_RASTERIO_SPEC = importlib.util.find_spec("rasterio")
if _RASTERIO_SPEC and _RASTERIO_SPEC.origin:
    _RASTERIO_DIR = Path(_RASTERIO_SPEC.origin).resolve().parent
    _PROJ_DATA = str(_RASTERIO_DIR / "proj_data")
    _GDAL_DATA = str(_RASTERIO_DIR / "gdal_data")
    os.environ["PROJ_DATA"] = _PROJ_DATA
    os.environ["PROJ_LIB"] = _PROJ_DATA
    os.environ["GDAL_DATA"] = _GDAL_DATA

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
from shapely.geometry import box


ROOT = Path(__file__).resolve().parents[3]
CITY_KEY = "hong_kong_fixed_link_grid"
TARGET_CRS = "EPSG:32650"
DEFAULT_CELL_SIZE_M = 920.658900389797
DEFAULT_MIN_AREA_M2 = 1.0
DEFAULT_BOUNDARY = ROOT / "data/boundary/hongkong/processed/hong_kong_fixed_link_boundary_wgs84.geojson"
DEFAULT_OUT_DIR = ROOT / "data/worldcommuting_od/hongkong/custom_features" / CITY_KEY


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--boundary", type=Path, default=DEFAULT_BOUNDARY, help="Hong Kong fixed-link boundary.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="WEDAN custom feature output root.")
    parser.add_argument("--cell-size-m", type=float, default=DEFAULT_CELL_SIZE_M, help="Square grid cell size in metres.")
    parser.add_argument("--min-area-m2", type=float, default=DEFAULT_MIN_AREA_M2, help="Drop clipped fragments smaller than this area.")
    parser.add_argument("--target-crs", default=TARGET_CRS, help="Projected CRS for grid generation.")
    return parser.parse_args()


def load_boundary(path: Path, target_crs: str) -> gpd.GeoDataFrame:
    boundary = gpd.read_file(path)
    if boundary.empty:
        raise ValueError(f"Boundary contains no features: {path}")
    boundary = boundary.to_crs(target_crs)
    boundary["geometry"] = boundary.geometry.make_valid()
    boundary = boundary[~boundary.geometry.is_empty].copy()
    if boundary.empty:
        raise ValueError(f"Boundary contains no valid geometries after reprojection: {path}")
    return boundary


def build_grid(boundary: gpd.GeoDataFrame, cell_size_m: float, min_area_m2: float) -> gpd.GeoDataFrame:
    if cell_size_m <= 0:
        raise ValueError("--cell-size-m must be positive")
    if min_area_m2 < 0:
        raise ValueError("--min-area-m2 must be non-negative")

    boundary_union = boundary.geometry.union_all()
    minx, miny, maxx, maxy = boundary_union.bounds
    col_count = math.ceil((maxx - minx) / cell_size_m)
    row_count = math.ceil((maxy - miny) / cell_size_m)

    records: list[dict[str, Any]] = []
    geometries = []
    for col in range(col_count):
        x0 = minx + col * cell_size_m
        x1 = x0 + cell_size_m
        for row in range(row_count):
            y0 = miny + row * cell_size_m
            y1 = y0 + cell_size_m
            clipped = box(x0, y0, x1, y1).intersection(boundary_union)
            if clipped.is_empty or clipped.area < min_area_m2:
                continue
            records.append(
                {
                    "locations": f"{col}-{row}",
                    "col": col,
                    "row": row,
                    "area_m2": float(clipped.area),
                    "area_km2": float(clipped.area / 1_000_000.0),
                }
            )
            geometries.append(clipped)

    grid = gpd.GeoDataFrame(records, geometry=geometries, crs=boundary.crs)
    if grid.empty:
        raise RuntimeError("Generated grid is empty.")
    grid = grid.sort_values(["col", "row"]).reset_index(drop=True)
    grid["grid_id"] = np.arange(len(grid), dtype=int)
    return grid[["grid_id", "locations", "col", "row", "area_m2", "area_km2", "geometry"]]


def write_grid_outputs(grid: gpd.GeoDataFrame, split_dir: Path) -> dict[str, str]:
    split_dir.mkdir(parents=True, exist_ok=True)
    shp_path = split_dir / "regions.shp"
    geojson_path = split_dir / "regions.geojson"
    png_path = split_dir / "regions.png"

    grid.to_file(shp_path, encoding="utf-8")
    grid.to_crs("EPSG:4326").to_file(geojson_path, driver="GeoJSON")

    fig, ax = plt.subplots(figsize=(9, 7), dpi=200)
    grid.boundary.plot(ax=ax, linewidth=0.22, color="#333333")
    grid.plot(ax=ax, column="area_km2", cmap="viridis", alpha=0.68, legend=True)
    ax.set_aspect("equal")
    ax.set_title("Hong Kong fixed-link regular grid")
    ax.set_axis_off()
    fig.tight_layout()
    fig.savefig(png_path, bbox_inches="tight")
    plt.close(fig)

    return {
        "shapefile": str(shp_path),
        "geojson": str(geojson_path),
        "png": str(png_path),
    }


def validate_grid(grid: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame) -> dict[str, Any]:
    boundary_area_km2 = float(boundary.geometry.union_all().area / 1_000_000.0)
    grid_area_km2 = float(grid.geometry.area.sum() / 1_000_000.0)
    grid_ids = grid["grid_id"].to_numpy()
    expected_ids = np.arange(len(grid), dtype=int)
    return {
        "boundary_area_km2": boundary_area_km2,
        "grid_area_km2_sum": grid_area_km2,
        "grid_minus_boundary_area_km2": grid_area_km2 - boundary_area_km2,
        "grid_id_contiguous": bool(np.array_equal(grid_ids, expected_ids)),
        "locations_unique": bool(grid["locations"].is_unique),
        "empty_geometries": int(grid.geometry.is_empty.sum()),
        "invalid_geometries": int((~grid.geometry.is_valid).sum()),
        "min_grid_area_km2": float(grid["area_km2"].min()),
        "median_grid_area_km2": float(grid["area_km2"].median()),
        "max_grid_area_km2": float(grid["area_km2"].max()),
    }


def main() -> None:
    args = parse_args()
    if not args.boundary.exists():
        raise FileNotFoundError(args.boundary)

    boundary = load_boundary(args.boundary, args.target_crs)
    grid = build_grid(boundary, args.cell_size_m, args.min_area_m2)

    split_dir = args.out_dir / "CityAndRegionSplit" / CITY_KEY
    outputs = write_grid_outputs(grid, split_dir)
    qa = validate_grid(grid, boundary)

    summary = {
        "city_key": CITY_KEY,
        "boundary": str(args.boundary),
        "output_dir": str(args.out_dir),
        "target_crs": args.target_crs,
        "cell_size_m": float(args.cell_size_m),
        "min_area_m2": float(args.min_area_m2),
        "grid_origin": "fixed-link boundary lower-left",
        "grid_count": int(len(grid)),
        "columns": ["grid_id", "locations", "col", "row", "area_m2", "area_km2", "geometry"],
        "outputs": outputs,
        **qa,
        "note": (
            "Regular square cells are generated in EPSG:32650 from the fixed-link boundary lower-left, clipped to "
            "the boundary, sorted by col,row, and assigned contiguous grid_id values. This step only creates "
            "regions; it does not aggregate WorldPop, POI, imagery, distance, or OD features."
        ),
    }
    summary_path = split_dir / "grid_generation_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Grid cells: {len(grid)}")
    print(f"Cell size: {args.cell_size_m:.12f} m")
    print(f"Boundary area: {qa['boundary_area_km2']:.6f} km2")
    print(f"Grid area: {qa['grid_area_km2_sum']:.6f} km2")
    print(f"Area difference: {qa['grid_minus_boundary_area_km2']:.12f} km2")
    print(f"Wrote: {outputs['shapefile']}")
    print(f"Wrote: {outputs['geojson']}")
    print(f"Wrote: {outputs['png']}")
    print(f"Wrote: {summary_path}")


if __name__ == "__main__":
    main()
