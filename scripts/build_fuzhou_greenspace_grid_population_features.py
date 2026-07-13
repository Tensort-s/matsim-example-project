"""Create a WorldOD-style Fuzhou grid and aggregate age/sex population features.

Inputs:
  - Greenspace Fuzhou city boundary (`city_id=23`)
  - GEE-downloaded `WorldPop/GP/100m/pop_age_sex` multi-band raster
  - WorldOD Fuzhou regions only as a reference for grid cell size

Outputs:
  - A clipped regular grid over the Greenspace Fuzhou boundary
  - `worldpop.npy` with shape (N, 2):
      column 0: total population count
      column 1: total population density, people / km^2
  - `demos.npy` with shape (N, 36):
      M_0 ... M_80, F_0 ... F_80 aggregated counts
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.mask import mask
from shapely.geometry import box


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_BOUNDARY = PROJECT_ROOT / "data" / "osm" / "fuzhou_city_23" / "fuzhou_city_23_boundary.geojson"
DEFAULT_WORLDOD_REGIONS = (
    PROJECT_ROOT
    / "data"
    / "worldcommuting_od"
    / "330_CN_Fuzhou"
    / "CityAndRegionSplit"
    / "330_CN_Fuzhou"
    / "regions.shp"
)
DEFAULT_AGE_SEX_RASTER = (
    PROJECT_ROOT
    / "data"
    / "gee"
    / "fuzhou_city_23"
    / "worldpop_age_sex"
    / "worldpop_CHN_2020_pop_age_sex_fuzhou_city_23_greenspace_boundary.tif"
)
DEFAULT_BANDS_JSON = (
    PROJECT_ROOT
    / "data"
    / "gee"
    / "fuzhou_city_23"
    / "worldpop_age_sex"
    / "worldpop_age_sex_bands.json"
)
DEFAULT_OUT_DIR = (
    PROJECT_ROOT
    / "data"
    / "worldcommuting_od"
    / "custom_features"
    / "fuzhou_city_23_greenspace_grid"
)
TARGET_CRS = "EPSG:32650"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a WorldOD-style grid for the Greenspace Fuzhou boundary and aggregate WorldPop age/sex features."
    )
    parser.add_argument("--boundary", default=str(DEFAULT_BOUNDARY), help="Greenspace Fuzhou boundary.")
    parser.add_argument("--age-sex-raster", default=str(DEFAULT_AGE_SEX_RASTER), help="GEE pop_age_sex multi-band GeoTIFF.")
    parser.add_argument("--bands-json", default=str(DEFAULT_BANDS_JSON), help="JSON list of raster band names.")
    parser.add_argument(
        "--worldod-regions",
        default=str(DEFAULT_WORLDOD_REGIONS),
        help="WorldOD regions shapefile used only to infer the reference grid cell size.",
    )
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output directory.")
    parser.add_argument("--cell-size", type=float, default=None, help="Grid cell size in metres. Defaults to WorldOD median full cell size.")
    parser.add_argument(
        "--min-area-m2",
        type=float,
        default=1.0,
        help="Drop clipped grid fragments smaller than this area.",
    )
    parser.add_argument(
        "--origin",
        choices=["boundary", "worldod"],
        default="boundary",
        help="Use the Greenspace boundary lower-left or WorldOD lower-left as the grid origin.",
    )
    return parser.parse_args()


def infer_worldod_cell_size(worldod_regions: pathlib.Path) -> float:
    regions = gpd.read_file(worldod_regions).to_crs(TARGET_CRS)
    sizes: list[float] = []
    for geom in regions.geometry:
        minx, miny, maxx, maxy = geom.bounds
        width = maxx - minx
        height = maxy - miny
        area = geom.area
        if width > 0 and height > 0:
            squareness = min(width, height) / max(width, height)
            fill_ratio = area / (width * height)
            if squareness > 0.98 and fill_ratio > 0.98:
                sizes.append((width + height) / 2.0)
    if not sizes:
        raise RuntimeError(f"Could not infer full square cell size from {worldod_regions}")
    return float(np.median(sizes))


def load_boundary(path: pathlib.Path) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)
    if gdf.empty:
        raise ValueError(f"Boundary contains no features: {path}")
    return gdf.to_crs(TARGET_CRS)


def make_grid(boundary: gpd.GeoDataFrame, cell_size: float, origin_mode: str, worldod_regions: pathlib.Path, min_area_m2: float) -> gpd.GeoDataFrame:
    boundary_union = boundary.union_all()
    minx, miny, maxx, maxy = boundary_union.bounds
    if origin_mode == "worldod":
        ref = gpd.read_file(worldod_regions).to_crs(TARGET_CRS)
        origin_x, origin_y = ref.total_bounds[0], ref.total_bounds[1]
        start_i = math.floor((minx - origin_x) / cell_size)
        start_j = math.floor((miny - origin_y) / cell_size)
        end_i = math.ceil((maxx - origin_x) / cell_size)
        end_j = math.ceil((maxy - origin_y) / cell_size)
    else:
        origin_x, origin_y = minx, miny
        start_i, start_j = 0, 0
        end_i = math.ceil((maxx - origin_x) / cell_size)
        end_j = math.ceil((maxy - origin_y) / cell_size)

    records: list[dict] = []
    geometries = []
    for i in range(start_i, end_i):
        x0 = origin_x + i * cell_size
        x1 = x0 + cell_size
        for j in range(start_j, end_j):
            y0 = origin_y + j * cell_size
            y1 = y0 + cell_size
            cell = box(x0, y0, x1, y1)
            clipped = cell.intersection(boundary_union)
            if clipped.is_empty or clipped.area < min_area_m2:
                continue
            records.append(
                {
                    "locations": f"{i}-{j}",
                    "col": i,
                    "row": j,
                    "area_m2": float(clipped.area),
                    "area_km2": float(clipped.area / 1_000_000.0),
                }
            )
            geometries.append(clipped)

    grid = gpd.GeoDataFrame(records, geometry=geometries, crs=TARGET_CRS)
    grid = grid.sort_values(["col", "row"]).reset_index(drop=True)
    grid["grid_id"] = np.arange(len(grid), dtype=int)
    return grid[["grid_id", "locations", "col", "row", "area_m2", "area_km2", "geometry"]]


def read_bands(path: pathlib.Path) -> list[str]:
    bands = json.loads(path.read_text(encoding="utf-8"))
    if len(bands) != 37 or bands[0] != "population":
        raise ValueError(f"Expected 37 bands with first band 'population', got {len(bands)} bands from {path}")
    return bands


def aggregate_raster(grid: gpd.GeoDataFrame, raster_path: pathlib.Path) -> np.ndarray:
    rows: list[np.ndarray] = []
    with rasterio.open(raster_path) as src:
        grid_raster = grid.to_crs(src.crs)
        for geom in grid_raster.geometry:
            try:
                clipped, _ = mask(src, [geom], crop=True, filled=False, all_touched=False)
            except ValueError:
                rows.append(np.zeros(src.count, dtype="float64"))
                continue
            # Sum inside each clipped polygon. Masked pixels are ignored; valid
            # zero-valued pixels outside the city boundary remain zero.
            sums = np.ma.sum(clipped, axis=(1, 2)).filled(0).astype("float64")
            sums = np.where(np.isfinite(sums), sums, 0.0)
            sums[sums < 0] = 0.0
            rows.append(sums)
    return np.vstack(rows)


def save_grid(grid: gpd.GeoDataFrame, out_dir: pathlib.Path) -> dict:
    split_dir = out_dir / "CityAndRegionSplit" / "fuzhou_city_23_greenspace_grid"
    split_dir.mkdir(parents=True, exist_ok=True)
    shp_path = split_dir / "regions.shp"
    geojson_path = split_dir / "regions.geojson"
    grid.to_file(shp_path, encoding="utf-8")
    grid.to_crs("EPSG:4326").to_file(geojson_path, driver="GeoJSON")

    png_path = split_dir / "regions.png"
    try:
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(8, 6), dpi=200)
        grid.boundary.plot(ax=ax, linewidth=0.25, color="#333333")
        grid.plot(ax=ax, column="area_km2", cmap="viridis", alpha=0.65, legend=True)
        ax.set_aspect("equal")
        ax.set_title("Fuzhou Greenspace Boundary Grid")
        ax.set_axis_off()
        fig.tight_layout()
        fig.savefig(png_path)
        plt.close(fig)
    except Exception:
        png_path = None

    return {
        "shapefile": str(shp_path),
        "geojson": str(geojson_path),
        "png": str(png_path) if png_path else None,
    }


def main() -> None:
    args = parse_args()
    boundary_path = pathlib.Path(args.boundary)
    raster_path = pathlib.Path(args.age_sex_raster)
    bands_path = pathlib.Path(args.bands_json)
    worldod_regions = pathlib.Path(args.worldod_regions)
    out_dir = pathlib.Path(args.out_dir)

    for path in [boundary_path, raster_path, bands_path, worldod_regions]:
        if not path.exists():
            raise FileNotFoundError(path)

    bands = read_bands(bands_path)
    cell_size = args.cell_size if args.cell_size else infer_worldod_cell_size(worldod_regions)
    boundary = load_boundary(boundary_path)
    grid = make_grid(boundary, cell_size, args.origin, worldod_regions, args.min_area_m2)
    if grid.empty:
        raise RuntimeError("Generated grid is empty.")

    band_sums = aggregate_raster(grid, raster_path)
    population = band_sums[:, 0]
    density = np.divide(population, grid["area_km2"].to_numpy(), out=np.zeros_like(population), where=grid["area_km2"].to_numpy() > 0)
    worldpop = np.column_stack([population, density]).astype("float32")
    demos = band_sums[:, 1:].astype("float32")

    nfeat_dir = out_dir / "GeneratingCodeData" / "data" / "global_cities" / "fuzhou_city_23_greenspace_grid" / "nfeat"
    nfeat_dir.mkdir(parents=True, exist_ok=True)
    worldpop_path = nfeat_dir / "worldpop.npy"
    demos_path = nfeat_dir / "demos.npy"
    np.save(worldpop_path, worldpop)
    np.save(demos_path, demos)

    table = grid.drop(columns="geometry").copy()
    table["population"] = population
    table["population_density_per_km2"] = density
    for idx, band in enumerate(bands[1:]):
        table[band] = demos[:, idx]
    csv_path = nfeat_dir / "population_age_sex_grid_features.csv"
    table.to_csv(csv_path, index=False, encoding="utf-8-sig")

    grid_outputs = save_grid(grid, out_dir)
    band_def_path = nfeat_dir / "demos_bands.json"
    band_def_path.write_text(json.dumps(bands[1:], indent=2, ensure_ascii=False), encoding="utf-8")

    summary = {
        "boundary": str(boundary_path),
        "age_sex_raster": str(raster_path),
        "worldod_cell_size_reference": str(worldod_regions),
        "cell_size_m": cell_size,
        "grid_origin": args.origin,
        "target_crs": TARGET_CRS,
        "grid_count": int(len(grid)),
        "grid_area_km2_sum": float(grid["area_km2"].sum()),
        "worldpop_output": str(worldpop_path),
        "worldpop_shape": list(worldpop.shape),
        "worldpop_columns": ["population_count", "population_density_per_km2"],
        "demos_output": str(demos_path),
        "demos_shape": list(demos.shape),
        "demos_bands": bands[1:],
        "csv_output": str(csv_path),
        "grid_outputs": grid_outputs,
        "population_sum": float(population.sum()),
        "age_sex_sum": float(demos.sum()),
        "population_minus_age_sex_sum": float(population.sum() - demos.sum()),
        "max_grid_population": float(population.max()),
        "nonzero_population_grids": int(np.count_nonzero(population > 0)),
        "aggregation_note": "Raster pixels are assigned by pixel center (rasterio all_touched=False) to avoid double-counting across adjacent grid cells.",
    }
    summary_path = nfeat_dir / "feature_generation_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Grid cells: {len(grid)}")
    print(f"Cell size: {cell_size:.6f} m")
    print(f"Grid area: {summary['grid_area_km2_sum']:.6f} km2")
    print(f"Population sum: {summary['population_sum']:.3f}")
    print(f"Age-sex sum: {summary['age_sex_sum']:.3f}")
    print(f"Wrote: {worldpop_path} shape={worldpop.shape}")
    print(f"Wrote: {demos_path} shape={demos.shape}")
    print(f"Wrote: {grid_outputs['shapefile']}")
    print(f"Wrote: {summary_path}")


if __name__ == "__main__":
    main()
