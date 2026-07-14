"""Download Fuzhou WorldPop age/sex population raster from Google Earth Engine.

This downloads `WorldPop/GP/100m/pop_age_sex` clipped by the Greenspace-derived
Fuzhou city boundary (`city_id=23`), not by the WorldOD 225-region boundary.

The output is a multi-band GeoTIFF with:
  - population
  - M_0 ... M_80
  - F_0 ... F_80

Example:
    .\.venv_geo311\Scripts\python.exe scripts\download_fuzhou_age_sex_population_from_gee.py --authenticate --project YOUR_GEE_PROJECT
    .\.venv_geo311\Scripts\python.exe scripts\download_fuzhou_age_sex_population_from_gee.py --project YOUR_GEE_PROJECT
"""

from __future__ import annotations

import argparse
import json
import pathlib
import zipfile

import ee
import geopandas as gpd
import requests
from shapely.geometry import mapping


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_BOUNDARY = PROJECT_ROOT / "data" / "osm" / "fuzhou_city_23" / "fuzhou_city_23_boundary.geojson"
DEFAULT_OUT_DIR = PROJECT_ROOT / "data" / "gee" / "fuzhou_city_23" / "worldpop_age_sex"

AGE_SEX_BANDS = [
    "population",
    "M_0",
    "M_1",
    "M_5",
    "M_10",
    "M_15",
    "M_20",
    "M_25",
    "M_30",
    "M_35",
    "M_40",
    "M_45",
    "M_50",
    "M_55",
    "M_60",
    "M_65",
    "M_70",
    "M_75",
    "M_80",
    "F_0",
    "F_1",
    "F_5",
    "F_10",
    "F_15",
    "F_20",
    "F_25",
    "F_30",
    "F_35",
    "F_40",
    "F_45",
    "F_50",
    "F_55",
    "F_60",
    "F_65",
    "F_70",
    "F_75",
    "F_80",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download WorldPop age/sex population bands for Fuzhou using the Greenspace city boundary."
    )
    parser.add_argument("--boundary", default=str(DEFAULT_BOUNDARY), help="Greenspace-derived Fuzhou boundary file.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output directory.")
    parser.add_argument("--dataset", default="WorldPop/GP/100m/pop_age_sex", help="Earth Engine ImageCollection ID.")
    parser.add_argument("--country", default="CHN", help="WorldPop country property.")
    parser.add_argument("--year", type=int, default=2020, help="WorldPop year property. This dataset currently provides 2020.")
    parser.add_argument("--scale", type=float, default=100.0, help="Download scale in metres.")
    parser.add_argument("--project", default=None, help="Google Cloud project registered for Earth Engine.")
    parser.add_argument(
        "--authenticate",
        action="store_true",
        help="Run ee.Authenticate() before initializing. Use this for the first local run.",
    )
    parser.add_argument(
        "--bands",
        nargs="*",
        default=AGE_SEX_BANDS,
        help="Bands to download. Defaults to population plus all age-sex bands.",
    )
    return parser.parse_args()


def initialize_earth_engine(project: str | None, authenticate: bool) -> None:
    if authenticate:
        ee.Authenticate()
    if project:
        ee.Initialize(project=project)
    else:
        ee.Initialize()


def load_boundary(path: pathlib.Path) -> tuple[gpd.GeoDataFrame, ee.Geometry]:
    gdf = gpd.read_file(path)
    if gdf.empty:
        raise ValueError(f"Boundary file contains no features: {path}")
    gdf_4326 = gdf.to_crs("EPSG:4326")
    geom = gdf_4326.union_all()
    return gdf_4326, ee.Geometry(mapping(geom))


def get_image(dataset: str, country: str, year: int, bands: list[str], region: ee.Geometry) -> ee.Image:
    collection = (
        ee.ImageCollection(dataset)
        .filter(ee.Filter.eq("country", country))
        .filter(ee.Filter.eq("year", year))
        .filterBounds(region)
    )
    count = collection.size().getInfo()
    if count < 1:
        raise RuntimeError(f"No image found for dataset={dataset}, country={country}, year={year}")
    image = ee.Image(collection.first())
    available = image.bandNames().getInfo()
    missing = [band for band in bands if band not in available]
    if missing:
        raise RuntimeError(f"Requested bands are missing from GEE image: {missing}. Available bands: {available}")
    # Earth Engine's GeoTIFF download can encode masked pixels as -99999 while
    # not setting a nodata tag. Fill masked pixels with 0 before export so that
    # downstream population sums are not contaminated by the clip mask.
    return image.select(bands).clip(region).unmask(0)


def download_image(image: ee.Image, region: ee.Geometry, out_dir: pathlib.Path, filename_stem: str, scale: float) -> pathlib.Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    url = image.getDownloadURL(
        {
            "name": filename_stem,
            "scale": scale,
            "region": region,
            "format": "GEO_TIFF",
            "filePerBand": False,
        }
    )
    response = requests.get(url, timeout=600)
    response.raise_for_status()

    if response.content[:2] == b"PK":
        zip_path = out_dir / f"{filename_stem}.zip"
        zip_path.write_bytes(response.content)
        with zipfile.ZipFile(zip_path) as zf:
            tif_members = [name for name in zf.namelist() if name.lower().endswith((".tif", ".tiff"))]
            if not tif_members:
                raise RuntimeError(f"No GeoTIFF found inside downloaded archive: {zip_path}")
            zf.extract(tif_members[0], out_dir)
        extracted = out_dir / tif_members[0]
        tif_path = out_dir / f"{filename_stem}.tif"
        if extracted != tif_path:
            if tif_path.exists():
                tif_path.unlink()
            extracted.replace(tif_path)
        return tif_path

    tif_path = out_dir / f"{filename_stem}.tif"
    tif_path.write_bytes(response.content)
    return tif_path


def main() -> None:
    args = parse_args()
    boundary = pathlib.Path(args.boundary)
    out_dir = pathlib.Path(args.out_dir)
    if not boundary.exists():
        raise FileNotFoundError(f"Boundary not found: {boundary}")

    initialize_earth_engine(args.project, args.authenticate)
    boundary_gdf, region = load_boundary(boundary)
    image = get_image(args.dataset, args.country, args.year, args.bands, region)

    filename_stem = f"worldpop_{args.country}_{args.year}_pop_age_sex_fuzhou_city_23_greenspace_boundary"
    tif_path = download_image(image, region, out_dir, filename_stem, args.scale)

    bounds = boundary_gdf.total_bounds.tolist()
    metadata = {
        "dataset": args.dataset,
        "country": args.country,
        "year": args.year,
        "scale_m": args.scale,
        "boundary_source": "Greenspace city_id=23 boundary exported to data/osm/fuzhou/city_23/fuzhou_city_23_boundary.geojson",
        "boundary_path": str(boundary),
        "boundary_crs_for_download": "EPSG:4326",
        "boundary_bounds_lonlat": bounds,
        "bands": args.bands,
        "output_tif": str(tif_path),
        "note": "Each band is an estimated count of residents per grid cell. The raster is clipped by the Greenspace Fuzhou boundary, not by WorldOD regions. Masked pixels outside the boundary are exported as 0.",
    }
    metadata_path = out_dir / f"{filename_stem}.metadata.json"
    bands_path = out_dir / "worldpop_age_sex_bands.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    bands_path.write_text(json.dumps(args.bands, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Downloaded: {tif_path}")
    print(f"Metadata:   {metadata_path}")
    print(f"Bands:      {bands_path}")


if __name__ == "__main__":
    main()
