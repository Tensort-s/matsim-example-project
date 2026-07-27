"""Download Hong Kong WorldPop population and age/sex rasters.

This mirrors the Fuzhou WorldPop age/sex workflow, but uses the public
WorldPop static file repository instead of Google Earth Engine so it can run
without local Earth Engine authentication.

Outputs:
  - a multi-band clipped GeoTIFF with:
      population, M_0 ... M_80, F_0 ... F_80
  - band-name JSON
  - metadata JSON
  - basic per-band summary JSON
"""

from __future__ import annotations

import argparse
import json
import pathlib
from collections.abc import Iterable

import geopandas as gpd
import numpy as np
import rasterio
import requests
from rasterio.mask import mask


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]
DEFAULT_BOUNDARY = (
    PROJECT_ROOT
    / "data"
    / "boundary"
    / "hongkong"
    / "processed"
    / "hong_kong_fixed_link_boundary_wgs84.geojson"
)
DEFAULT_OUT_DIR = PROJECT_ROOT / "data" / "gee" / "hongkong" / "worldpop_age_sex"

POP_COLLECTION_URL = "https://data.worldpop.org/GIS/Population/Global_2000_2020"
AGE_SEX_COLLECTION_URL = "https://data.worldpop.org/GIS/AgeSex_structures/Global_2000_2020"

AGE_GROUPS = ["0", "1", "5", "10", "15", "20", "25", "30", "35", "40", "45", "50", "55", "60", "65", "70", "75", "80"]
AGE_SEX_BANDS = ["population"] + [f"M_{age}" for age in AGE_GROUPS] + [f"F_{age}" for age in AGE_GROUPS]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download and clip WorldPop HKG 2020 population plus age/sex bands."
    )
    parser.add_argument("--boundary", default=str(DEFAULT_BOUNDARY), help="Hong Kong boundary readable by GeoPandas.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output directory.")
    parser.add_argument("--raw-dir", default=None, help="Raw download directory. Defaults to OUT_DIR/raw_worldpop.")
    parser.add_argument("--country", default="HKG", help="WorldPop country code.")
    parser.add_argument("--year", type=int, default=2020, help="WorldPop year.")
    parser.add_argument("--overwrite", action="store_true", help="Download raw files again even when present.")
    return parser.parse_args()


def iter_band_sources(country: str, year: int) -> Iterable[tuple[str, str]]:
    country_uc = country.upper()
    country_lc = country.lower()
    population_base_url = f"{POP_COLLECTION_URL}/{year}/{country_uc}"
    age_sex_base_url = f"{AGE_SEX_COLLECTION_URL}/{year}/{country_uc}"
    yield "population", f"{population_base_url}/{country_lc}_ppp_{year}.tif"
    for sex in ["m", "f"]:
        for age in AGE_GROUPS:
            yield f"{sex.upper()}_{age}", f"{age_sex_base_url}/{country_lc}_{sex}_{age}_{year}.tif"


def download_file(url: str, path: pathlib.Path, overwrite: bool) -> None:
    if path.exists() and path.stat().st_size > 0 and not overwrite:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=300) as response:
        response.raise_for_status()
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("wb") as fh:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    fh.write(chunk)
        tmp.replace(path)


def load_boundary(path: pathlib.Path) -> tuple[gpd.GeoDataFrame, list[dict]]:
    gdf = gpd.read_file(path)
    if gdf.empty:
        raise ValueError(f"Boundary file contains no features: {path}")
    gdf_4326 = gdf.to_crs("EPSG:4326")
    return gdf_4326, [geom.__geo_interface__ for geom in gdf_4326.geometry]


def clipped_array(path: pathlib.Path, geometries: list[dict]) -> tuple[np.ndarray, dict]:
    with rasterio.open(path) as src:
        data, transform = mask(src, geometries, crop=True, filled=True, nodata=0)
        profile = src.profile.copy()
        profile.update(
            {
                "height": data.shape[1],
                "width": data.shape[2],
                "transform": transform,
                "count": 1,
                "nodata": 0,
                "compress": "deflate",
                "tiled": False,
            }
        )
        profile.pop("blockxsize", None)
        profile.pop("blockysize", None)
    arr = data[0].astype("float32")
    arr = np.where(np.isfinite(arr), arr, 0).astype("float32")
    return arr, profile


def summarize_band(name: str, arr: np.ndarray) -> dict:
    positive = arr[arr > 0]
    return {
        "band": name,
        "sum": float(arr.sum(dtype="float64")),
        "positive_pixel_count": int(positive.size),
        "min_positive": float(positive.min()) if positive.size else 0.0,
        "max": float(arr.max()) if arr.size else 0.0,
    }


def main() -> None:
    args = parse_args()
    boundary = pathlib.Path(args.boundary)
    out_dir = pathlib.Path(args.out_dir)
    raw_dir = pathlib.Path(args.raw_dir) if args.raw_dir else out_dir / "raw_worldpop"

    if not boundary.exists():
        raise FileNotFoundError(f"Boundary not found: {boundary}")

    out_dir.mkdir(parents=True, exist_ok=True)
    boundary_gdf, geometries = load_boundary(boundary)

    raw_paths: dict[str, pathlib.Path] = {}
    for band_name, url in iter_band_sources(args.country, args.year):
        raw_path = raw_dir / pathlib.Path(url).name
        print(f"{band_name}: {url}")
        download_file(url, raw_path, args.overwrite)
        raw_paths[band_name] = raw_path

    arrays: list[np.ndarray] = []
    summaries: list[dict] = []
    output_profile: dict | None = None
    for band_name in AGE_SEX_BANDS:
        arr, profile = clipped_array(raw_paths[band_name], geometries)
        if output_profile is None:
            output_profile = profile
        arrays.append(arr)
        summaries.append(summarize_band(band_name, arr))

    assert output_profile is not None
    stack = np.stack(arrays).astype("float32")
    output_profile.update(count=len(AGE_SEX_BANDS), dtype="float32")

    stem = f"worldpop_{args.country}_{args.year}_pop_age_sex_hong_kong_fixed_link_boundary"
    tif_path = out_dir / f"{stem}.tif"
    if tif_path.exists():
        tif_path.unlink()
    with rasterio.open(tif_path, "w", **output_profile) as dst:
        dst.write(stack)
        for idx, band_name in enumerate(AGE_SEX_BANDS, start=1):
            dst.set_band_description(idx, band_name)

    bands_path = out_dir / "worldpop_age_sex_bands.json"
    metadata_path = out_dir / f"{stem}.metadata.json"
    summary_path = out_dir / "worldpop_age_sex_summary.json"

    metadata = {
        "dataset": "WorldPop public static GeoTIFF repository",
        "population_source": f"{POP_COLLECTION_URL}/{args.year}/{args.country.upper()}/{args.country.lower()}_ppp_{args.year}.tif",
        "age_sex_source_base": f"{AGE_SEX_COLLECTION_URL}/{args.year}/{args.country.upper()}",
        "country": args.country,
        "year": args.year,
        "boundary_path": str(boundary),
        "boundary_crs_for_clip": "EPSG:4326",
        "boundary_bounds_lonlat": boundary_gdf.total_bounds.tolist(),
        "bands": AGE_SEX_BANDS,
        "raw_dir": str(raw_dir),
        "output_tif": str(tif_path),
        "note": "Each band is an estimated resident count per grid cell. Pixels outside the Hong Kong fixed-link boundary are exported as 0.",
    }
    summary = {
        "path": str(tif_path),
        "band_count": len(AGE_SEX_BANDS),
        "shape": list(stack.shape),
        "crs": str(output_profile.get("crs")),
        "transform": list(output_profile["transform"])[:6],
        "summaries": summaries,
        "population_sum": summaries[0]["sum"],
        "male_age_sex_sum": float(sum(item["sum"] for item in summaries if item["band"].startswith("M_"))),
        "female_age_sex_sum": float(sum(item["sum"] for item in summaries if item["band"].startswith("F_"))),
    }

    bands_path.write_text(json.dumps(AGE_SEX_BANDS, indent=2, ensure_ascii=False), encoding="utf-8")
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote: {tif_path}")
    print(f"Bands: {bands_path}")
    print(f"Metadata: {metadata_path}")
    print(f"Summary: {summary_path}")


if __name__ == "__main__":
    main()
