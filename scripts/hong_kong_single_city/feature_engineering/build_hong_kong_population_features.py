#!/usr/bin/env python3
"""Build WEDAN population and age/sex features for the Hong Kong fixed-link grid."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path

_RASTERIO_SPEC = importlib.util.find_spec("rasterio")
if _RASTERIO_SPEC and _RASTERIO_SPEC.origin:
    _RASTERIO_DIR = Path(_RASTERIO_SPEC.origin).resolve().parent
    os.environ["PROJ_DATA"] = str(_RASTERIO_DIR / "proj_data")
    os.environ["PROJ_LIB"] = str(_RASTERIO_DIR / "proj_data")
    os.environ["GDAL_DATA"] = str(_RASTERIO_DIR / "gdal_data")

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.mask import mask


ROOT = Path(__file__).resolve().parents[3]
CITY_NAME = "hong_kong_fixed_link_grid"
DEFAULT_GRID = (
    ROOT
    / "data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid"
    / "CityAndRegionSplit/hong_kong_fixed_link_grid/regions.shp"
)
DEFAULT_RASTER = (
    ROOT
    / "data/gee/hongkong/worldpop_age_sex/census_calibrated"
    / "worldpop_HKG_2021_census_lsug_calibrated_fixed_link_boundary.tif"
)
DEFAULT_BANDS = ROOT / "data/gee/hongkong/worldpop_age_sex/worldpop_age_sex_bands.json"
DEFAULT_NFEAT_DIR = (
    ROOT
    / "data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid"
    / "GeneratingCodeData/data/global_cities/hong_kong_fixed_link_grid/nfeat"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grid", type=Path, default=DEFAULT_GRID, help="Hong Kong fixed-link grid regions.shp.")
    parser.add_argument("--age-sex-raster", type=Path, default=DEFAULT_RASTER, help="Calibrated 37-band WorldPop raster.")
    parser.add_argument("--bands-json", type=Path, default=DEFAULT_BANDS, help="Band names JSON.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_NFEAT_DIR, help="Output WEDAN nfeat directory.")
    return parser.parse_args()


def read_bands(path: Path) -> list[str]:
    bands = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(bands, list) or len(bands) != 37 or bands[0] != "population":
        raise ValueError(f"Expected 37 bands with first band 'population', got {bands!r}")
    return [str(band) for band in bands]


def aggregate_raster_by_grid(grid: gpd.GeoDataFrame, raster_path: Path) -> np.ndarray:
    rows: list[np.ndarray] = []
    with rasterio.open(raster_path) as src:
        if src.count != 37:
            raise ValueError(f"Expected 37 raster bands, got {src.count}: {raster_path}")
        grid_raster = grid.to_crs(src.crs)
        for geom in grid_raster.geometry:
            try:
                clipped, _ = mask(src, [geom], crop=True, filled=False, all_touched=False)
            except ValueError:
                rows.append(np.zeros(src.count, dtype="float64"))
                continue
            sums = np.ma.sum(clipped, axis=(1, 2)).filled(0).astype("float64")
            sums = np.where(np.isfinite(sums), sums, 0.0)
            sums[sums < 0] = 0.0
            rows.append(sums)
    return np.vstack(rows)


def main() -> None:
    args = parse_args()
    for path in [args.grid, args.age_sex_raster, args.bands_json]:
        if not path.exists():
            raise FileNotFoundError(path)

    bands = read_bands(args.bands_json)
    grid = gpd.read_file(args.grid).reset_index(drop=True)
    if grid.empty:
        raise ValueError(f"Grid is empty: {args.grid}")
    if "area_km2" not in grid.columns:
        grid["area_km2"] = grid.to_crs("EPSG:32650").geometry.area / 1_000_000.0

    band_sums = aggregate_raster_by_grid(grid, args.age_sex_raster)
    population = band_sums[:, 0]
    area_km2 = grid["area_km2"].to_numpy(dtype="float64")
    density = np.divide(population, area_km2, out=np.zeros_like(population), where=area_km2 > 0)

    worldpop = np.column_stack([population, density]).astype("float32")
    demos = band_sums[:, 1:].astype("float32")
    if worldpop.shape != (len(grid), 2) or demos.shape != (len(grid), 36):
        raise RuntimeError(f"Unexpected shapes: worldpop={worldpop.shape}, demos={demos.shape}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    worldpop_path = args.out_dir / "worldpop.npy"
    demos_path = args.out_dir / "demos.npy"
    np.save(worldpop_path, worldpop)
    np.save(demos_path, demos)

    table = grid.drop(columns="geometry").copy()
    table["population"] = population
    table["population_density_per_km2"] = density
    for idx, band in enumerate(bands[1:]):
        table[band] = demos[:, idx]
    csv_path = args.out_dir / "population_age_sex_grid_features.csv"
    table.to_csv(csv_path, index=False, encoding="utf-8-sig")

    demos_bands_path = args.out_dir / "demos_bands.json"
    demos_bands_path.write_text(json.dumps(bands[1:], indent=2, ensure_ascii=False), encoding="utf-8")

    summary = {
        "city": CITY_NAME,
        "grid": str(args.grid),
        "age_sex_raster": str(args.age_sex_raster),
        "bands_json": str(args.bands_json),
        "output_dir": str(args.out_dir),
        "grid_count": int(len(grid)),
        "grid_crs": str(grid.crs),
        "worldpop_output": str(worldpop_path),
        "worldpop_shape": list(worldpop.shape),
        "worldpop_dtype": str(worldpop.dtype),
        "worldpop_columns": ["population_count", "population_density_per_km2"],
        "demos_output": str(demos_path),
        "demos_shape": list(demos.shape),
        "demos_dtype": str(demos.dtype),
        "demos_bands": bands[1:],
        "csv_output": str(csv_path),
        "population_sum": float(population.sum()),
        "age_sex_sum": float(demos.sum()),
        "population_minus_age_sex_sum": float(population.sum() - demos.sum()),
        "max_grid_population": float(population.max()) if len(population) else 0.0,
        "nonzero_population_grids": int(np.count_nonzero(population > 0)),
        "aggregation_note": "Raster pixels are assigned by pixel center with rasterio all_touched=False to avoid double-counting adjacent grid cells.",
    }
    summary_path = args.out_dir / "feature_generation_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Grid cells: {len(grid)}")
    print(f"Population sum: {summary['population_sum']:.3f}")
    print(f"Age-sex sum: {summary['age_sex_sum']:.3f}")
    print(f"Wrote: {worldpop_path} shape={worldpop.shape}")
    print(f"Wrote: {demos_path} shape={demos.shape}")
    print(f"Wrote: {summary_path}")


if __name__ == "__main__":
    main()
