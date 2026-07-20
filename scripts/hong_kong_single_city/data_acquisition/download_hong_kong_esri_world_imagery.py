#!/usr/bin/env python3
"""Download Esri World Imagery for the Hong Kong fixed-link model boundary.

The WEDAN / WorldCommuting-OD image feature workflow uses Esri World Imagery
tiles as the remote-sensing image source. This script mirrors the Fuzhou
imagery workflow for Hong Kong:

1. Convert the Hong Kong fixed-link boundary bounding box to XYZ tile indices.
2. Download or reuse Esri World Imagery tiles.
3. Stitch the tiles into an RGB Web Mercator GeoTIFF.
4. Clip the mosaic to the fixed-link model boundary.
5. Reproject the clipped image to a local UTM CRS for downstream GIS and
   RemoteCLIP feature extraction.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import json
import math
import os
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

# Some Windows GIS installations set PROJ_LIB globally to an incompatible
# proj.db. Force rasterio/geopandas to use the PROJ/GDAL data bundled with
# rasterio before importing GIS libraries.
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
import rasterio
import requests
from PIL import Image
from rasterio import mask as rio_mask
from rasterio.enums import Resampling
from rasterio.transform import from_bounds
from rasterio.warp import calculate_default_transform, reproject


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BOUNDARY = ROOT / "data/boundary/hongkong/processed/hong_kong_fixed_link_boundary_wgs84.geojson"
DEFAULT_OUT_DIR = ROOT / "data/imagery/hongkong/esri_world_imagery/fixed_link_boundary"
DEFAULT_TILE_URL = "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
WEB_MERCATOR_HALF_WORLD = 20037508.342789244
TILE_SIZE = 256


@dataclass(frozen=True)
class Tile:
    z: int
    x: int
    y: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--boundary", type=Path, default=DEFAULT_BOUNDARY, help="Hong Kong fixed-link boundary file.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Output directory.")
    parser.add_argument("--zoom", type=int, default=14, help="XYZ tile zoom. z14 matches the current Fuzhou workflow.")
    parser.add_argument("--tile-url", default=DEFAULT_TILE_URL, help="XYZ tile URL template with {z}/{y}/{x}.")
    parser.add_argument("--workers", type=int, default=12, help="Parallel tile download workers.")
    parser.add_argument("--timeout", type=int, default=60, help="Per-tile HTTP timeout in seconds.")
    parser.add_argument("--reproject-crs", default="EPSG:32650", help="Local projected CRS for the clipped output.")
    parser.add_argument("--no-reproject", action="store_true", help="Skip local CRS reprojection.")
    parser.add_argument("--dry-run", action="store_true", help="Only report tile coverage; do not download imagery.")
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


def boundary_and_tiles(boundary_path: Path, zoom: int) -> tuple[gpd.GeoDataFrame, list[Tile], dict[str, Any]]:
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
        "tile_x_min": min(tile.x for tile in tiles),
        "tile_x_max": max(tile.x for tile in tiles),
        "tile_y_min": min(tile.y for tile in tiles),
        "tile_y_max": max(tile.y for tile in tiles),
        "tile_count": len(tiles),
    }
    return boundary_4326, tiles, info


def download_tile(tile: Tile, url_template: str, tiles_dir: Path, timeout: int) -> Path:
    out_path = tiles_dir / str(tile.z) / str(tile.x) / f"{tile.y}.jpg"
    if out_path.exists() and out_path.stat().st_size > 0:
        return out_path

    out_path.parent.mkdir(parents=True, exist_ok=True)
    url = url_template.format(z=tile.z, x=tile.x, y=tile.y)
    headers = {"User-Agent": "matsim-hong-kong-research/1.0"}
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    image = Image.open(BytesIO(response.content)).convert("RGB")
    image.save(out_path, format="JPEG", quality=95)
    return out_path


def download_tiles(tiles: list[Tile], url_template: str, out_dir: Path, workers: int, timeout: int) -> list[Path]:
    tiles_dir = out_dir / "tiles"
    downloaded: list[Path] = []
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
                print(f"Downloaded/verified {i}/{len(tiles)} tiles", flush=True)
    return downloaded


def build_mosaic(tiles: list[Tile], tiles_dir: Path, mosaic_path: Path) -> dict[str, Any]:
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


def clip_to_boundary(mosaic_path: Path, boundary_4326: gpd.GeoDataFrame, clipped_path: Path) -> dict[str, Any]:
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


def reproject_to_crs(src_path: Path, dst_path: Path, dst_crs: str) -> dict[str, Any]:
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
            "projected_path": str(dst_path),
            "projected_crs": str(dst.crs),
            "projected_width": dst.width,
            "projected_height": dst.height,
            "projected_bounds": list(dst.bounds),
            "projected_resolution": list(dst.res),
        }


def write_preview(src_path: Path, boundary_4326: gpd.GeoDataFrame, preview_path: Path) -> dict[str, Any]:
    with rasterio.open(src_path) as src:
        max_side = 1600
        scale = min(max_side / src.width, max_side / src.height, 1.0)
        out_width = max(1, int(src.width * scale))
        out_height = max(1, int(src.height * scale))
        data = src.read([1, 2, 3], out_shape=(3, out_height, out_width), resampling=Resampling.bilinear)
        extent = [src.bounds.left, src.bounds.right, src.bounds.bottom, src.bounds.top]
        boundary = boundary_4326.to_crs(src.crs)

    rgb = np.moveaxis(data, 0, -1)
    fig, ax = plt.subplots(figsize=(10, 8), dpi=180)
    ax.imshow(rgb, extent=extent)
    boundary.boundary.plot(ax=ax, color="#ffcc00", linewidth=0.8)
    ax.set_title("Hong Kong Esri World Imagery z14 fixed-link boundary")
    ax.set_axis_off()
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(preview_path, bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)
    return {"preview_path": str(preview_path)}


def write_tile_manifest(tiles: list[Tile], out_dir: Path, zoom: int) -> Path:
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
    manifest_path = out_dir / f"tile_manifest_z{zoom}.json"
    manifest_path.write_text(json.dumps(tile_manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest_path


def main() -> None:
    args = parse_args()
    if not args.boundary.exists():
        raise FileNotFoundError(args.boundary)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    boundary_4326, tiles, tile_info = boundary_and_tiles(args.boundary, args.zoom)
    print(f"Boundary: {args.boundary}")
    print(f"Zoom: {args.zoom}; tiles: {tile_info['tile_count']}")

    if args.dry_run:
        print(json.dumps(tile_info, indent=2, ensure_ascii=False))
        return

    downloaded = download_tiles(tiles, args.tile_url, args.out_dir, args.workers, args.timeout)

    stem = f"hong_kong_fixed_link_esri_world_imagery_z{args.zoom}"
    mosaic_path = args.out_dir / f"{stem}_mosaic_epsg3857.tif"
    clipped_path = args.out_dir / f"{stem}_clip_epsg3857.tif"
    projected_epsg = args.reproject_crs.lower().replace(":", "")
    projected_path = args.out_dir / f"{stem}_clip_{projected_epsg}.tif"
    preview_path = args.out_dir / f"{stem}_preview.png"

    mosaic_info = build_mosaic(tiles, args.out_dir / "tiles", mosaic_path)
    clip_info = clip_to_boundary(mosaic_path, boundary_4326, clipped_path)
    projected_info = {} if args.no_reproject else reproject_to_crs(clipped_path, projected_path, args.reproject_crs)
    preview_source = projected_path if projected_info else clipped_path
    preview_info = write_preview(preview_source, boundary_4326, preview_path)
    manifest_path = write_tile_manifest(tiles, args.out_dir, args.zoom)

    metadata = {
        "source": "Esri World Imagery",
        "source_url_template": args.tile_url,
        "boundary_source": "Hong Kong fixed-link model boundary from 2021 Census District Council polygons",
        "boundary_path": str(args.boundary),
        "zoom": args.zoom,
        "tile_size": TILE_SIZE,
        "downloaded_or_cached_tiles": len(downloaded),
        **tile_info,
        **mosaic_info,
        **clip_info,
        **projected_info,
        **preview_info,
        "tile_manifest": str(manifest_path),
        "note": (
            "Imagery is downloaded from Esri World Imagery XYZ tiles and clipped to the Hong Kong fixed-link "
            "model boundary. Please respect Esri/ArcGIS terms of use when redistributing derived imagery."
        ),
    }
    metadata_path = args.out_dir / f"{stem}_metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Mosaic:    {mosaic_path}")
    print(f"Clipped:   {clipped_path}")
    if projected_info:
        print(f"Projected: {projected_path}")
    print(f"Preview:   {preview_path}")
    print(f"Metadata:  {metadata_path}")


if __name__ == "__main__":
    main()
