"""Download Esri World Imagery for the Greenspace Fuzhou boundary.

The WorldCommuting-OD paper uses Esri World Imagery and then extracts
RemoteCLIP features from clipped region images. This script performs the local
image acquisition step for the Greenspace Fuzhou `city_id=23` boundary:

1. Convert boundary bbox to Web Mercator tile coordinates.
2. Download Esri World Imagery XYZ tiles.
3. Stitch tiles into an RGB Web Mercator GeoTIFF.
4. Mask/crop the GeoTIFF by the Greenspace Fuzhou boundary.
5. Optionally reproject the clipped image to EPSG:32650 for local GIS work.

Example:
    .\.venv_geo311\Scripts\python.exe scripts\download_fuzhou_esri_world_imagery.py
"""

from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import json
import math
import os
import pathlib
from dataclasses import dataclass
from io import BytesIO

# Some Windows GIS installations set PROJ_LIB globally to an incompatible
# proj.db (for example GeoDa). Force this script to use the PROJ database that
# belongs to rasterio/GDAL before importing geopandas/rasterio.
_RASTERIO_SPEC = importlib.util.find_spec("rasterio")
if _RASTERIO_SPEC and _RASTERIO_SPEC.origin:
    _RASTERIO_DIR = pathlib.Path(_RASTERIO_SPEC.origin).resolve().parent
    _PROJ_DATA = str(_RASTERIO_DIR / "proj_data")
    _GDAL_DATA = str(_RASTERIO_DIR / "gdal_data")
    os.environ["PROJ_DATA"] = _PROJ_DATA
    os.environ["PROJ_LIB"] = _PROJ_DATA
    os.environ["GDAL_DATA"] = _GDAL_DATA

import geopandas as gpd
import numpy as np

import rasterio
import requests
from PIL import Image
from rasterio import mask as rio_mask
from rasterio.enums import Resampling
from rasterio.transform import from_bounds
from rasterio.warp import calculate_default_transform, reproject


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_BOUNDARY = PROJECT_ROOT / "data" / "osm" / "fuzhou_city_23" / "fuzhou_city_23_boundary.geojson"
DEFAULT_OUT_DIR = PROJECT_ROOT / "data" / "imagery" / "esri_world_imagery" / "fuzhou_city_23_greenspace_boundary"
DEFAULT_TILE_URL = "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
WEB_MERCATOR_HALF_WORLD = 20037508.342789244
TILE_SIZE = 256


@dataclass(frozen=True)
class Tile:
    z: int
    x: int
    y: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download and mosaic Esri World Imagery for Greenspace Fuzhou.")
    parser.add_argument("--boundary", default=str(DEFAULT_BOUNDARY), help="Greenspace Fuzhou boundary GeoJSON/shapefile.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output directory.")
    parser.add_argument("--zoom", type=int, default=14, help="XYZ tile zoom. z14 is roughly 10 m/pixel at low latitudes.")
    parser.add_argument("--tile-url", default=DEFAULT_TILE_URL, help="XYZ tile URL template with {z}/{y}/{x}.")
    parser.add_argument("--workers", type=int, default=12, help="Parallel tile download workers.")
    parser.add_argument("--timeout", type=int, default=60, help="Per-tile HTTP timeout in seconds.")
    parser.add_argument("--reproject-utm", action="store_true", default=True, help="Also write EPSG:32650 clipped GeoTIFF.")
    parser.add_argument("--no-reproject-utm", action="store_false", dest="reproject_utm", help="Skip EPSG:32650 output.")
    return parser.parse_args()


def lonlat_to_tile(lon: float, lat: float, z: int) -> tuple[int, int]:
    lat = max(min(lat, 85.05112878), -85.05112878)
    n = 2**z
    x = int(math.floor((lon + 180.0) / 360.0 * n))
    lat_rad = math.radians(lat)
    y = int(math.floor((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n))
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def tile_bounds_mercator(x: int, y: int, z: int) -> tuple[float, float, float, float]:
    n = 2**z
    tile_span = 2 * WEB_MERCATOR_HALF_WORLD / n
    left = -WEB_MERCATOR_HALF_WORLD + x * tile_span
    right = left + tile_span
    top = WEB_MERCATOR_HALF_WORLD - y * tile_span
    bottom = top - tile_span
    return left, bottom, right, top


def boundary_and_tiles(boundary_path: pathlib.Path, zoom: int) -> tuple[gpd.GeoDataFrame, list[Tile], dict]:
    boundary = gpd.read_file(boundary_path)
    if boundary.empty:
        raise ValueError(f"Boundary contains no features: {boundary_path}")
    boundary_4326 = boundary.to_crs("EPSG:4326")
    minlon, minlat, maxlon, maxlat = boundary_4326.total_bounds
    minx, maxy = lonlat_to_tile(float(minlon), float(minlat), zoom)
    maxx, miny = lonlat_to_tile(float(maxlon), float(maxlat), zoom)
    xs = range(min(minx, maxx), max(minx, maxx) + 1)
    ys = range(min(miny, maxy), max(miny, maxy) + 1)
    tiles = [Tile(zoom, x, y) for y in ys for x in xs]
    info = {
        "boundary_bounds_lonlat": [float(minlon), float(minlat), float(maxlon), float(maxlat)],
        "tile_x_min": min(x.x for x in tiles),
        "tile_x_max": max(x.x for x in tiles),
        "tile_y_min": min(x.y for x in tiles),
        "tile_y_max": max(x.y for x in tiles),
        "tile_count": len(tiles),
    }
    return boundary_4326, tiles, info


def download_tile(tile: Tile, url_template: str, tiles_dir: pathlib.Path, timeout: int) -> pathlib.Path:
    out_path = tiles_dir / str(tile.z) / str(tile.x) / f"{tile.y}.jpg"
    if out_path.exists() and out_path.stat().st_size > 0:
        return out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    url = url_template.format(z=tile.z, x=tile.x, y=tile.y)
    headers = {"User-Agent": "matsim-fuzhou-research/1.0"}
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    # Normalize tile image to RGB JPEG/PNG readable bytes. Some missing tiles may
    # still return an image placeholder; keep it, because it preserves the mosaic.
    image = Image.open(BytesIO(response.content)).convert("RGB")
    image.save(out_path, format="JPEG", quality=95)
    return out_path


def download_tiles(tiles: list[Tile], url_template: str, out_dir: pathlib.Path, workers: int, timeout: int) -> list[pathlib.Path]:
    tiles_dir = out_dir / "tiles"
    downloaded: list[pathlib.Path] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(download_tile, tile, url_template, tiles_dir, timeout): tile
            for tile in tiles
        }
        for i, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            tile = futures[future]
            try:
                downloaded.append(future.result())
            except Exception as exc:
                raise RuntimeError(f"Failed to download tile z={tile.z} x={tile.x} y={tile.y}: {exc}") from exc
            if i % 25 == 0 or i == len(tiles):
                print(f"Downloaded/verified {i}/{len(tiles)} tiles")
    return downloaded


def build_mosaic(tiles: list[Tile], tiles_dir: pathlib.Path, mosaic_path: pathlib.Path) -> dict:
    xs = sorted({tile.x for tile in tiles})
    ys = sorted({tile.y for tile in tiles})
    x_to_col = {x: i for i, x in enumerate(xs)}
    y_to_row = {y: i for i, y in enumerate(ys)}
    width = len(xs) * TILE_SIZE
    height = len(ys) * TILE_SIZE
    mosaic = np.zeros((3, height, width), dtype=np.uint8)

    for tile in tiles:
        path = tiles_dir / str(tile.z) / str(tile.x) / f"{tile.y}.jpg"
        image = Image.open(path).convert("RGB")
        arr = np.asarray(image, dtype=np.uint8)
        row = y_to_row[tile.y] * TILE_SIZE
        col = x_to_col[tile.x] * TILE_SIZE
        mosaic[:, row : row + TILE_SIZE, col : col + TILE_SIZE] = arr.transpose(2, 0, 1)

    left, bottom, _, _ = tile_bounds_mercator(min(xs), max(ys), tiles[0].z)
    _, _, right, top = tile_bounds_mercator(max(xs), min(ys), tiles[0].z)
    transform = from_bounds(left, bottom, right, top, width, height)
    profile = {
        "driver": "GTiff",
        "width": width,
        "height": height,
        "count": 3,
        "dtype": "uint8",
        "crs": "EPSG:3857",
        "transform": transform,
        "compress": "deflate",
        "photometric": "RGB",
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
    }
    mosaic_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(mosaic_path, "w", **profile) as dst:
        dst.write(mosaic)
        dst.set_band_description(1, "red")
        dst.set_band_description(2, "green")
        dst.set_band_description(3, "blue")

    return {
        "mosaic_path": str(mosaic_path),
        "mosaic_width": width,
        "mosaic_height": height,
        "mosaic_bounds_epsg3857": [left, bottom, right, top],
    }


def clip_to_boundary(mosaic_path: pathlib.Path, boundary_4326: gpd.GeoDataFrame, clipped_path: pathlib.Path) -> dict:
    with rasterio.open(mosaic_path) as src:
        boundary_3857 = boundary_4326.to_crs(src.crs)
        geoms = [geom for geom in boundary_3857.geometry if geom is not None and not geom.is_empty]
        clipped, transform = rio_mask.mask(src, geoms, crop=True, nodata=0, filled=True)
        profile = src.profile.copy()
        profile.update(
            {
                "height": clipped.shape[1],
                "width": clipped.shape[2],
                "transform": transform,
                "nodata": 0,
                "compress": "deflate",
                "photometric": "RGB",
            }
        )
    clipped_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(clipped_path, "w", **profile) as dst:
        dst.write(clipped)
        dst.set_band_description(1, "red")
        dst.set_band_description(2, "green")
        dst.set_band_description(3, "blue")
    with rasterio.open(clipped_path) as dst:
        return {
            "clipped_path": str(clipped_path),
            "clipped_crs": str(dst.crs),
            "clipped_width": dst.width,
            "clipped_height": dst.height,
            "clipped_bounds": list(dst.bounds),
            "clipped_resolution": list(dst.res),
        }


def reproject_to_utm(src_path: pathlib.Path, dst_path: pathlib.Path, dst_crs: str = "EPSG:32650") -> dict:
    with rasterio.open(src_path) as src:
        transform, width, height = calculate_default_transform(src.crs, dst_crs, src.width, src.height, *src.bounds)
        profile = src.profile.copy()
        profile.update(
            {
                "crs": dst_crs,
                "transform": transform,
                "width": width,
                "height": height,
                "compress": "deflate",
                "photometric": "RGB",
                "nodata": 0,
            }
        )
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(dst_path, "w", **profile) as dst:
            for band in range(1, src.count + 1):
                reproject(
                    source=rasterio.band(src, band),
                    destination=rasterio.band(dst, band),
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=transform,
                    dst_crs=dst_crs,
                    resampling=Resampling.bilinear,
                    src_nodata=0,
                    dst_nodata=0,
                )
            dst.set_band_description(1, "red")
            dst.set_band_description(2, "green")
            dst.set_band_description(3, "blue")
    with rasterio.open(dst_path) as dst:
        return {
            "utm_path": str(dst_path),
            "utm_crs": str(dst.crs),
            "utm_width": dst.width,
            "utm_height": dst.height,
            "utm_bounds": list(dst.bounds),
            "utm_resolution": list(dst.res),
        }


def main() -> None:
    args = parse_args()
    boundary_path = pathlib.Path(args.boundary)
    out_dir = pathlib.Path(args.out_dir)
    if not boundary_path.exists():
        raise FileNotFoundError(boundary_path)

    out_dir.mkdir(parents=True, exist_ok=True)
    boundary_4326, tiles, tile_info = boundary_and_tiles(boundary_path, args.zoom)
    print(f"Boundary: {boundary_path}")
    print(f"Zoom: {args.zoom}; tiles: {tile_info['tile_count']}")
    downloaded = download_tiles(tiles, args.tile_url, out_dir, args.workers, args.timeout)

    mosaic_path = out_dir / f"fuzhou_city_23_esri_world_imagery_z{args.zoom}_mosaic_epsg3857.tif"
    clipped_path = out_dir / f"fuzhou_city_23_esri_world_imagery_z{args.zoom}_greenspace_clip_epsg3857.tif"
    utm_path = out_dir / f"fuzhou_city_23_esri_world_imagery_z{args.zoom}_greenspace_clip_epsg32650.tif"

    mosaic_info = build_mosaic(tiles, out_dir / "tiles", mosaic_path)
    clip_info = clip_to_boundary(mosaic_path, boundary_4326, clipped_path)
    utm_info = reproject_to_utm(clipped_path, utm_path) if args.reproject_utm else {}

    tile_manifest = [
        {
            "z": tile.z,
            "x": tile.x,
            "y": tile.y,
            "path": str(out_dir / "tiles" / str(tile.z) / str(tile.x) / f"{tile.y}.jpg"),
            "bounds_epsg3857": list(tile_bounds_mercator(tile.x, tile.y, tile.z)),
        }
        for tile in tiles
    ]
    manifest_path = out_dir / f"tile_manifest_z{args.zoom}.json"
    manifest_path.write_text(json.dumps(tile_manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    metadata = {
        "source": "Esri World Imagery",
        "source_url_template": args.tile_url,
        "boundary_source": "Greenspace Fuzhou city_id=23",
        "boundary_path": str(boundary_path),
        "zoom": args.zoom,
        "tile_size": TILE_SIZE,
        "downloaded_or_cached_tiles": len(downloaded),
        **tile_info,
        **mosaic_info,
        **clip_info,
        **utm_info,
        "tile_manifest": str(manifest_path),
        "note": "Imagery is downloaded from Esri World Imagery XYZ tiles and clipped to the Greenspace Fuzhou boundary. Please respect Esri/ArcGIS terms of use when redistributing derived imagery.",
    }
    metadata_path = out_dir / f"fuzhou_city_23_esri_world_imagery_z{args.zoom}_metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Mosaic:   {mosaic_path}")
    print(f"Clipped:  {clipped_path}")
    if args.reproject_utm:
        print(f"UTM clip: {utm_path}")
    print(f"Metadata: {metadata_path}")


if __name__ == "__main__":
    main()
