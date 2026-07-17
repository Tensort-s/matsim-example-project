#!/usr/bin/env python3
"""Build WEDAN-compatible `adj/dis.npy` for the Hong Kong fixed-link grid."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path

_RASTERIO_SPEC = importlib.util.find_spec("rasterio")
if _RASTERIO_SPEC and _RASTERIO_SPEC.origin:
    _RASTERIO_DIR = Path(_RASTERIO_SPEC.origin).resolve().parent
    _PROJ_DATA = str(_RASTERIO_DIR / "proj_data")
    _GDAL_DATA = str(_RASTERIO_DIR / "gdal_data")
    os.environ["PROJ_DATA"] = _PROJ_DATA
    os.environ["PROJ_LIB"] = _PROJ_DATA
    os.environ["GDAL_DATA"] = _GDAL_DATA

import geopandas as gpd
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
CITY_KEY = "hong_kong_fixed_link_grid"
TARGET_CRS = "EPSG:32650"
DEFAULT_GRID = (
    ROOT
    / "data/worldcommuting_od/hongkong/custom_features"
    / CITY_KEY
    / "CityAndRegionSplit"
    / CITY_KEY
    / "regions.shp"
)
DEFAULT_OUT_DIR = (
    ROOT
    / "data/worldcommuting_od/hongkong/custom_features"
    / CITY_KEY
    / "GeneratingCodeData/data/global_cities"
    / CITY_KEY
    / "adj"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grid", type=Path, default=DEFAULT_GRID, help="Hong Kong grid regions.shp.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Output adj directory.")
    parser.add_argument("--unit", choices=["m", "km"], default="m", help="Output distance unit. Default: metres.")
    return parser.parse_args()


def build_distance_matrix(coords: np.ndarray, unit: str) -> np.ndarray:
    diff = coords[:, None, :] - coords[None, :, :]
    dis_m = np.sqrt(np.sum(diff * diff, axis=2))
    dis = dis_m / 1000.0 if unit == "km" else dis_m
    dis = dis.astype("float32")
    np.fill_diagonal(dis, 0.0)
    return dis


def main() -> None:
    args = parse_args()
    if not args.grid.exists():
        raise FileNotFoundError(args.grid)

    grid = gpd.read_file(args.grid).to_crs(TARGET_CRS).reset_index(drop=True)
    if grid.empty:
        raise ValueError(f"Grid contains no features: {args.grid}")

    centroids = grid.geometry.centroid
    coords = np.column_stack([centroids.x.to_numpy(), centroids.y.to_numpy()]).astype("float64")
    dis = build_distance_matrix(coords, args.unit)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    dis_path = args.out_dir / "dis.npy"
    np.save(dis_path, dis)

    centroid_wgs84 = gpd.GeoSeries(centroids, crs=TARGET_CRS).to_crs("EPSG:4326")
    centroids_table = pd.DataFrame(
        {
            "grid_index": np.arange(len(grid), dtype=int),
            "locations": grid["locations"].astype(str) if "locations" in grid.columns else np.arange(len(grid)).astype(str),
            "centroid_x_epsg32650": coords[:, 0],
            "centroid_y_epsg32650": coords[:, 1],
            "centroid_lon": centroid_wgs84.x,
            "centroid_lat": centroid_wgs84.y,
            "area_km2": grid.geometry.area.to_numpy() / 1_000_000.0,
        }
    )
    centroids_csv = args.out_dir / "grid_centroids.csv"
    centroids_table.to_csv(centroids_csv, index=False, encoding="utf-8-sig")

    sample_size = min(20, dis.shape[0])
    sample_csv = args.out_dir / "dis_matrix_sample_20x20.csv"
    pd.DataFrame(dis[:sample_size, :sample_size]).to_csv(sample_csv, index=False, encoding="utf-8-sig")

    non_diag = dis[~np.eye(dis.shape[0], dtype=bool)]
    summary = {
        "city_key": CITY_KEY,
        "grid": str(args.grid),
        "output": str(dis_path),
        "shape": list(dis.shape),
        "dtype": str(dis.dtype),
        "unit": args.unit,
        "crs_for_distance": TARGET_CRS,
        "method": "Euclidean distance between grid polygon centroids.",
        "grid_count": int(len(grid)),
        "min_nonzero_distance": float(non_diag[non_diag > 0].min()) if np.any(non_diag > 0) else 0.0,
        "max_distance": float(dis.max()),
        "mean_non_diagonal_distance": float(non_diag.mean()),
        "is_symmetric": bool(np.allclose(dis, dis.T)),
        "diagonal_max_abs": float(np.max(np.abs(np.diag(dis)))),
        "centroids_csv": str(centroids_csv),
        "sample_csv": str(sample_csv),
        "row_order": "Rows and columns follow regions.shp row order after GeoPandas read/reset_index.",
    }
    summary_path = args.out_dir / "dis_generation_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote: {dis_path} shape={dis.shape}")
    print(f"Wrote: {centroids_csv}")
    print(f"Wrote: {sample_csv}")
    print(f"Wrote: {summary_path}")
    print(f"Unit: {args.unit}; max distance: {summary['max_distance']:.3f}; min nonzero: {summary['min_nonzero_distance']:.3f}")


if __name__ == "__main__":
    main()
