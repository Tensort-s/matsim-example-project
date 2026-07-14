"""Build WEDAN-compatible `adj/dis.npy` for the Greenspace Fuzhou grid.

`dis.npy` is a straight-line centroid-to-centroid distance matrix. Distances are
computed in EPSG:32650 metres, matching the local projected CRS used for the
custom Fuzhou grid.
"""

from __future__ import annotations

import argparse
import json
import pathlib

import geopandas as gpd
import numpy as np
import pandas as pd


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_GRID = (
    PROJECT_ROOT
    / "data"
    / "worldcommuting_od"
    / "custom_features"
    / "fuzhou_city_23_greenspace_grid"
    / "CityAndRegionSplit"
    / "fuzhou_city_23_greenspace_grid"
    / "regions.shp"
)
DEFAULT_OUT_DIR = (
    PROJECT_ROOT
    / "data"
    / "worldcommuting_od"
    / "custom_features"
    / "fuzhou_city_23_greenspace_grid"
    / "GeneratingCodeData"
    / "data"
    / "global_cities"
    / "fuzhou_city_23_greenspace_grid"
    / "adj"
)
TARGET_CRS = "EPSG:32650"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate straight-line centroid distance matrix for Fuzhou grid.")
    parser.add_argument("--grid", default=str(DEFAULT_GRID), help="Grid regions.shp.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output adj directory.")
    parser.add_argument("--unit", choices=["m", "km"], default="m", help="Output distance unit. Default: metres.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    grid_path = pathlib.Path(args.grid)
    out_dir = pathlib.Path(args.out_dir)
    if not grid_path.exists():
        raise FileNotFoundError(grid_path)

    grid = gpd.read_file(grid_path).to_crs(TARGET_CRS).reset_index(drop=True)
    centroids = grid.geometry.centroid
    coords = np.column_stack([centroids.x.to_numpy(), centroids.y.to_numpy()]).astype("float64")

    diff = coords[:, None, :] - coords[None, :, :]
    dis_m = np.sqrt(np.sum(diff * diff, axis=2))
    dis = dis_m / 1000.0 if args.unit == "km" else dis_m
    dis = dis.astype("float32")
    np.fill_diagonal(dis, 0.0)

    out_dir.mkdir(parents=True, exist_ok=True)
    dis_path = out_dir / "dis.npy"
    np.save(dis_path, dis)

    centroids_table = pd.DataFrame(
        {
            "grid_index": np.arange(len(grid), dtype=int),
            "locations": grid["locations"].astype(str) if "locations" in grid.columns else np.arange(len(grid)).astype(str),
            "centroid_x_epsg32650": coords[:, 0],
            "centroid_y_epsg32650": coords[:, 1],
            "centroid_lon": gpd.GeoSeries(centroids, crs=TARGET_CRS).to_crs("EPSG:4326").x,
            "centroid_lat": gpd.GeoSeries(centroids, crs=TARGET_CRS).to_crs("EPSG:4326").y,
            "area_km2": grid.geometry.area.to_numpy() / 1_000_000.0,
        }
    )
    centroids_csv = out_dir / "grid_centroids.csv"
    centroids_table.to_csv(centroids_csv, index=False, encoding="utf-8-sig")

    # Small readable sample for quick inspection.
    sample_size = min(20, dis.shape[0])
    sample_csv = out_dir / "dis_matrix_sample_20x20.csv"
    pd.DataFrame(dis[:sample_size, :sample_size]).to_csv(sample_csv, index=False, encoding="utf-8-sig")

    non_diag = dis[~np.eye(dis.shape[0], dtype=bool)]
    summary = {
        "grid": str(grid_path),
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
    }
    summary_path = out_dir / "dis_generation_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote: {dis_path} shape={dis.shape}")
    print(f"Wrote: {centroids_csv}")
    print(f"Wrote: {sample_csv}")
    print(f"Wrote: {summary_path}")
    print(f"Unit: {args.unit}; max distance: {summary['max_distance']:.3f}; min nonzero: {summary['min_nonzero_distance']:.3f}")


if __name__ == "__main__":
    main()
