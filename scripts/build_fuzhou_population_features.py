"""Build WEDAN-compatible Fuzhou population node features.

The WEDAN/WorldCommuting-OD Fuzhou example expects 225 region-level rows. This
script aggregates a population raster to those 225 WorldOD regions and writes a
2-column `worldpop.npy`:

    column 0: estimated population count in the region
    column 1: estimated population density, people / km^2

If a 36-column `demos.npy` reference is available from WorldCommuting-OD, the
script copies it into the output folder as a compatibility fallback. That file
is not derived from Greenspace/GEE; it is kept separate in the summary.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.mask import mask


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_REGIONS = (
    PROJECT_ROOT
    / "data"
    / "worldcommuting_od"
    / "330_CN_Fuzhou"
    / "CityAndRegionSplit"
    / "330_CN_Fuzhou"
    / "regions.shp"
)
DEFAULT_GEE_RASTER = PROJECT_ROOT / "data" / "gee" / "fuzhou_city_23" / "worldpop_CHN_2020_population_fuzhou_city_23.tif"
DEFAULT_GREENSPACE_RASTER = pathlib.Path(
    r"F:\GreenspaceExposureMeasurement\resources_by_function\raw\rasters\worldpop\worldpop_density_2020_proj\city_23.tif"
)
DEFAULT_DEMOS = (
    PROJECT_ROOT
    / "data"
    / "worldcommuting_od"
    / "330_CN_Fuzhou"
    / "GeneratingCodeData"
    / "data"
    / "global_cities"
    / "330_CN_Fuzhou"
    / "nfeat"
    / "demos.npy"
)
DEFAULT_OUT_DIR = (
    PROJECT_ROOT
    / "data"
    / "worldcommuting_od"
    / "custom_features"
    / "fuzhou_city_23_population"
    / "nfeat"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate Fuzhou population raster to WEDAN region features.")
    parser.add_argument("--regions", default=str(DEFAULT_REGIONS), help="WorldOD/WEDAN regions shapefile.")
    parser.add_argument(
        "--population-raster",
        default=str(DEFAULT_GEE_RASTER if DEFAULT_GEE_RASTER.exists() else DEFAULT_GREENSPACE_RASTER),
        help="Population raster. GEE WorldPop should be count per cell; Greenspace density raster should use --raster-mode density.",
    )
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output nfeat directory.")
    parser.add_argument(
        "--raster-mode",
        choices=["auto", "count", "density"],
        default="auto",
        help="'count' sums raster cells; 'density' multiplies by pixel area in km2 first.",
    )
    parser.add_argument("--demos-reference", default=str(DEFAULT_DEMOS), help="Optional 36-column demos.npy reference to copy.")
    parser.add_argument(
        "--copy-demos",
        action="store_true",
        help="Copy the reference demos.npy into the output directory for WEDAN compatibility.",
    )
    return parser.parse_args()


def infer_mode(path: pathlib.Path, requested: str) -> str:
    if requested != "auto":
        return requested
    lowered = str(path).lower()
    if "density" in lowered:
        return "density"
    return "count"


def clean_values(values: np.ma.MaskedArray, nodata: float | int | None) -> np.ndarray:
    arr = np.asarray(values, dtype="float64")
    mask_arr = np.ma.getmaskarray(values)
    valid = ~mask_arr & np.isfinite(arr)
    if nodata is not None and np.isfinite(nodata):
        valid &= arr != nodata
    return arr[valid]


def aggregate_population(regions: gpd.GeoDataFrame, raster_path: pathlib.Path, mode: str) -> tuple[np.ndarray, pd.DataFrame, dict]:
    rows: list[dict] = []

    with rasterio.open(raster_path) as src:
        regions_in_raster_crs = regions.to_crs(src.crs)
        regions_for_area = regions.to_crs("EPSG:32650")
        pixel_area_km2 = abs(src.transform.a * src.transform.e) / 1_000_000.0

        if mode == "density" and not src.crs.is_projected:
            raise ValueError("Density mode requires a projected raster CRS so pixel area can be computed.")

        for idx, (geom_raster, geom_area) in enumerate(zip(regions_in_raster_crs.geometry, regions_for_area.geometry)):
            area_km2 = float(geom_area.area / 1_000_000.0)
            try:
                clipped, _ = mask(src, [geom_raster], crop=True, filled=False, indexes=1)
                values = clean_values(clipped, src.nodata)
            except ValueError:
                values = np.array([], dtype="float64")

            if values.size == 0:
                raw_sum = 0.0
                raw_mean = 0.0
                population = 0.0
                valid_pixels = 0
            else:
                raw_sum = float(values.sum())
                raw_mean = float(values.mean())
                valid_pixels = int(values.size)
                if mode == "density":
                    population = raw_sum * pixel_area_km2
                else:
                    population = raw_sum

            density = population / area_km2 if area_km2 > 0 else 0.0
            region_id = regions.iloc[idx].get("ID", idx)
            rows.append(
                {
                    "region_index": idx,
                    "region_id": region_id,
                    "area_km2": area_km2,
                    "valid_pixels": valid_pixels,
                    "raw_sum": raw_sum,
                    "raw_mean": raw_mean,
                    "population_count": population,
                    "population_density_per_km2": density,
                }
            )

        table = pd.DataFrame(rows)
        features = table[["population_count", "population_density_per_km2"]].to_numpy(dtype="float32")
        raster_info = {
            "raster_crs": str(src.crs),
            "raster_bounds": list(src.bounds),
            "raster_width": src.width,
            "raster_height": src.height,
            "raster_nodata": src.nodata,
            "pixel_area_km2": pixel_area_km2,
        }

    return features, table, raster_info


def main() -> None:
    args = parse_args()
    regions_path = pathlib.Path(args.regions)
    raster_path = pathlib.Path(args.population_raster)
    out_dir = pathlib.Path(args.out_dir)
    demos_reference = pathlib.Path(args.demos_reference) if args.demos_reference else None

    if not regions_path.exists():
        raise FileNotFoundError(f"Regions shapefile not found: {regions_path}")
    if not raster_path.exists():
        raise FileNotFoundError(f"Population raster not found: {raster_path}")

    out_dir.mkdir(parents=True, exist_ok=True)
    regions = gpd.read_file(regions_path)
    mode = infer_mode(raster_path, args.raster_mode)
    features, table, raster_info = aggregate_population(regions, raster_path, mode)

    worldpop_path = out_dir / "worldpop.npy"
    csv_path = out_dir / "worldpop_region_features.csv"
    np.save(worldpop_path, features)
    table.to_csv(csv_path, index=False, encoding="utf-8-sig")

    demos_note = "No demos.npy copied."
    demos_path = None
    if args.copy_demos and demos_reference and demos_reference.exists():
        demos = np.load(demos_reference)
        if demos.shape[0] != features.shape[0]:
            raise ValueError(f"demos row count {demos.shape[0]} does not match worldpop row count {features.shape[0]}")
        demos_path = out_dir / "demos.npy"
        shutil.copy2(demos_reference, demos_path)
        demos_note = (
            "Copied from WorldCommuting-OD reference data for model compatibility; "
            "not derived from Greenspace/GEE population raster."
        )

    summary = {
        "regions": str(regions_path),
        "population_raster": str(raster_path),
        "raster_mode": mode,
        "worldpop_output": str(worldpop_path),
        "worldpop_shape": list(features.shape),
        "csv_output": str(csv_path),
        "demos_output": str(demos_path) if demos_path else None,
        "demos_note": demos_note,
        "total_population": float(features[:, 0].sum()),
        "mean_density_per_km2": float(features[:, 1].mean()),
        "max_region_population": float(features[:, 0].max()),
        "regions_count": int(features.shape[0]),
        "raster": raster_info,
        "feature_definition": {
            "worldpop[:, 0]": "population_count",
            "worldpop[:, 1]": "population_density_per_km2",
        },
    }
    summary_path = out_dir / "feature_generation_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote: {worldpop_path} shape={features.shape}")
    print(f"Wrote: {csv_path}")
    print(f"Wrote: {summary_path}")
    if demos_path:
        print(f"Copied compatible demos: {demos_path}")
    print(f"Total population: {summary['total_population']:.2f}")


if __name__ == "__main__":
    main()
