"""Download Fuzhou population raster from Google Earth Engine.

This script downloads the WorldPop population image for China/Fuzhou and clips it
to the local Fuzhou city boundary. It is intentionally small and project-local:
authenticate once with Earth Engine, then run the script whenever the population
input needs to be refreshed.

Example:
    .\.venv_geo311\Scripts\python.exe scripts\download_fuzhou_population_from_gee.py --authenticate --project YOUR_GEE_PROJECT
    .\.venv_geo311\Scripts\python.exe scripts\download_fuzhou_population_from_gee.py --project YOUR_GEE_PROJECT
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import zipfile

import ee
import geopandas as gpd
import requests
from shapely.geometry import mapping


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_BOUNDARY = PROJECT_ROOT / "data" / "osm" / "fuzhou_city_23" / "fuzhou_city_23_boundary.geojson"
DEFAULT_OUT_DIR = PROJECT_ROOT / "data" / "gee" / "fuzhou_city_23"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download a clipped WorldPop population GeoTIFF from Google Earth Engine."
    )
    parser.add_argument("--boundary", default=str(DEFAULT_BOUNDARY), help="Boundary file readable by GeoPandas.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output directory.")
    parser.add_argument("--dataset", default="WorldPop/GP/100m/pop", help="Earth Engine ImageCollection ID.")
    parser.add_argument("--country", default="CHN", help="WorldPop country code property.")
    parser.add_argument("--year", type=int, default=2020, help="WorldPop year property.")
    parser.add_argument("--band", default="population", help="Band to download.")
    parser.add_argument("--scale", type=float, default=100.0, help="Download scale in metres.")
    parser.add_argument("--project", default=None, help="Google Cloud project registered for Earth Engine.")
    parser.add_argument(
        "--authenticate",
        action="store_true",
        help="Run ee.Authenticate() before initializing. Use this for the first local run.",
    )
    return parser.parse_args()


def initialize_earth_engine(project: str | None, authenticate: bool) -> None:
    if authenticate:
        ee.Authenticate()
    if project:
        ee.Initialize(project=project)
    else:
        ee.Initialize()


def load_boundary_as_ee_geometry(path: pathlib.Path) -> ee.Geometry:
    gdf = gpd.read_file(path)
    if gdf.empty:
        raise ValueError(f"Boundary file contains no features: {path}")
    geom = gdf.to_crs("EPSG:4326").union_all()
    return ee.Geometry(mapping(geom))


def get_population_image(dataset: str, country: str, year: int, band: str, region: ee.Geometry) -> ee.Image:
    collection = (
        ee.ImageCollection(dataset)
        .filter(ee.Filter.eq("country", country))
        .filter(ee.Filter.eq("year", year))
        .filterBounds(region)
    )
    count = collection.size().getInfo()
    if count < 1:
        raise RuntimeError(f"No image found for dataset={dataset}, country={country}, year={year}")
    return ee.Image(collection.first()).select(band).clip(region)


def download_image(image: ee.Image, region: ee.Geometry, out_dir: pathlib.Path, filename_stem: str, scale: float) -> pathlib.Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    url = image.getDownloadURL(
        {
            "name": filename_stem,
            "scale": scale,
            "region": region,
            "format": "GEO_TIFF",
        }
    )
    response = requests.get(url, timeout=300)
    response.raise_for_status()

    content_type = response.headers.get("content-type", "").lower()
    if "zip" in content_type or response.content[:2] == b"PK":
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
    region = load_boundary_as_ee_geometry(boundary)
    image = get_population_image(args.dataset, args.country, args.year, args.band, region)

    filename_stem = f"worldpop_{args.country}_{args.year}_{args.band}_fuzhou_city_23"
    tif_path = download_image(image, region, out_dir, filename_stem, args.scale)

    metadata = {
        "dataset": args.dataset,
        "country": args.country,
        "year": args.year,
        "band": args.band,
        "scale_m": args.scale,
        "boundary": str(boundary),
        "output_tif": str(tif_path),
        "note": "WorldPop/GP/100m/pop population band is treated as population count per grid cell for downstream aggregation.",
    }
    metadata_path = out_dir / f"{filename_stem}.metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Downloaded: {tif_path}")
    print(f"Metadata:   {metadata_path}")


if __name__ == "__main__":
    main()
