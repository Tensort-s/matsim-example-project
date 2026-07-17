#!/usr/bin/env python3
"""Download and extract OSM POIs for the Hong Kong fixed-link boundary.

This mirrors the later Fuzhou Geofabrik/PBF workflow: download a regional OSM
PBF, read points/lines/multipolygons, keep OSM features with POI-like tags that
intersect the model boundary, convert non-point features to representative
points, and write boundary-specific GeoJSON products for downstream WEDAN POI
feature aggregation.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
from pathlib import Path
from typing import Any

import pandas as pd
import requests

_RASTERIO_SPEC = importlib.util.find_spec("rasterio")
if _RASTERIO_SPEC and _RASTERIO_SPEC.origin:
    _RASTERIO_DIR = Path(_RASTERIO_SPEC.origin).resolve().parent
    _PROJ_DATA = str(_RASTERIO_DIR / "proj_data")
    _GDAL_DATA = str(_RASTERIO_DIR / "gdal_data")
    os.environ["PROJ_DATA"] = _PROJ_DATA
    os.environ["PROJ_LIB"] = _PROJ_DATA
    os.environ["GDAL_DATA"] = _GDAL_DATA

import geopandas as gpd


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT_DIR = ROOT / "data/osm/hongkong/fixed_link_boundary"
DEFAULT_BOUNDARY = ROOT / "data/boundary/hongkong/processed/hong_kong_fixed_link_boundary_wgs84.geojson"
DEFAULT_PBF_URL = "https://download.geofabrik.de/asia/china/hong-kong-latest.osm.pbf"
DEFAULT_PBF = DEFAULT_OUT_DIR / "hong-kong-latest.osm.pbf"

TAG_KEYS = [
    "amenity",
    "shop",
    "office",
    "tourism",
    "leisure",
    "healthcare",
    "craft",
    "industrial",
    "public_transport",
    "railway",
    "landuse",
    "building",
    "highway",
]

POI_KEYS = [
    "amenity",
    "shop",
    "office",
    "tourism",
    "leisure",
    "healthcare",
    "craft",
    "industrial",
    "public_transport",
    "railway",
]

WORK_RELATED_AMENITIES = {
    "school",
    "university",
    "college",
    "hospital",
    "clinic",
    "doctors",
    "bank",
    "restaurant",
    "cafe",
    "fast_food",
    "marketplace",
    "police",
    "fire_station",
    "post_office",
    "courthouse",
    "townhall",
    "library",
    "theatre",
    "cinema",
    "kindergarten",
    "pharmacy",
}

WORK_RELATED_RAILWAY = {"station", "halt", "tram_stop", "subway_entrance"}
WORK_RELATED_LANDUSE = {"commercial", "retail", "industrial", "education", "institutional"}
WORK_RELATED_BUILDINGS = {
    "commercial",
    "retail",
    "industrial",
    "office",
    "school",
    "university",
    "college",
    "hospital",
    "kindergarten",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--boundary", type=Path, default=DEFAULT_BOUNDARY, help="Hong Kong fixed-link boundary.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Output directory.")
    parser.add_argument("--pbf-url", default=DEFAULT_PBF_URL, help="Geofabrik Hong Kong PBF URL.")
    parser.add_argument("--pbf", type=Path, default=DEFAULT_PBF, help="Local PBF path.")
    parser.add_argument("--timeout", type=int, default=180, help="Download timeout in seconds.")
    parser.add_argument("--force-download", action="store_true", help="Redownload PBF even if it already exists.")
    return parser.parse_args()


def download_pbf(url: str, path: Path, timeout: int, force: bool) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0 and not force:
        return {"downloaded": False, "pbf_path": str(path), "bytes": path.stat().st_size}

    tmp = path.with_suffix(path.suffix + ".part")
    headers = {"User-Agent": "matsim-hong-kong-research/1.0"}
    with requests.get(url, headers=headers, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        with tmp.open("wb") as fh:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    fh.write(chunk)
    tmp.replace(path)
    return {"downloaded": True, "pbf_path": str(path), "bytes": path.stat().st_size}


def parse_other_tags(value: Any) -> dict[str, str]:
    if value is None or pd.isna(value):
        return {}
    return dict(re.findall(r'"([^"]+)"=>"([^"]*)"', str(value)))


def enrich_tags(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    gdf = gdf.copy()
    if "other_tags" not in gdf.columns:
        for key in TAG_KEYS:
            if key not in gdf.columns:
                gdf[key] = None
        return gdf

    parsed = gdf["other_tags"].map(parse_other_tags)
    for key in TAG_KEYS:
        values = parsed.map(lambda tags, tag=key: tags.get(tag))
        if key not in gdf.columns:
            gdf[key] = values
        else:
            gdf[key] = gdf[key].where(gdf[key].notna(), values)
    return gdf


def read_layer_bbox(pbf_path: Path, layer: str, boundary: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    bounds = tuple(boundary.total_bounds)
    try:
        gdf = gpd.read_file(pbf_path, layer=layer, bbox=bounds).to_crs("EPSG:4326")
    except Exception as exc:
        raise RuntimeError(f"Failed reading OSM layer '{layer}' from {pbf_path}: {exc}") from exc
    if gdf.empty:
        return gdf
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    return enrich_tags(gdf)


def non_empty_mask(gdf: gpd.GeoDataFrame, columns: list[str]) -> pd.Series:
    mask = pd.Series(False, index=gdf.index)
    for column in columns:
        if column in gdf.columns:
            mask = mask | gdf[column].notna()
    return mask


def representative_points_within_boundary(gdf: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if gdf.empty:
        return gdf.copy()
    out = gdf.copy()
    out["geometry"] = out.geometry.representative_point()
    out = gpd.sjoin(out, boundary[["geometry"]], predicate="within", how="inner")
    return out.drop(columns=["index_right"], errors="ignore").copy()


def build_work_pois(pois: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    work_mask = pd.Series(False, index=pois.index)
    for column in ["office", "shop", "industrial", "craft", "healthcare"]:
        if column in pois.columns:
            work_mask = work_mask | pois[column].notna()
    if "amenity" in pois.columns:
        work_mask = work_mask | pois["amenity"].isin(WORK_RELATED_AMENITIES)
    if "railway" in pois.columns:
        work_mask = work_mask | pois["railway"].isin(WORK_RELATED_RAILWAY)
    return pois.loc[work_mask].copy()


def write_geojson(gdf: gpd.GeoDataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(path, driver="GeoJSON")


def main() -> None:
    args = parse_args()
    if not args.boundary.exists():
        raise FileNotFoundError(args.boundary)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    pbf_info = download_pbf(args.pbf_url, args.pbf, args.timeout, args.force_download)
    boundary = gpd.read_file(args.boundary).to_crs("EPSG:4326")
    boundary["geometry"] = boundary.geometry.make_valid()
    boundary = boundary[~boundary.geometry.is_empty].copy()
    if boundary.empty:
        raise ValueError(f"Boundary contains no valid geometry: {args.boundary}")

    points = read_layer_bbox(args.pbf, "points", boundary)
    lines = read_layer_bbox(args.pbf, "lines", boundary)
    multipolygons = read_layer_bbox(args.pbf, "multipolygons", boundary)

    point_pois_bbox = points.loc[non_empty_mask(points, POI_KEYS)].copy()
    line_pois_bbox = lines.loc[non_empty_mask(lines, POI_KEYS)].copy()
    polygon_pois_bbox = multipolygons.loc[non_empty_mask(multipolygons, POI_KEYS)].copy()

    point_pois = representative_points_within_boundary(point_pois_bbox, boundary)
    line_pois = representative_points_within_boundary(line_pois_bbox, boundary)
    polygon_pois = representative_points_within_boundary(polygon_pois_bbox, boundary)

    pois = gpd.GeoDataFrame(
        pd.concat(
            [
                point_pois,
                line_pois,
                polygon_pois,
            ],
            ignore_index=True,
        ),
        geometry="geometry",
        crs="EPSG:4326",
    )
    work_pois = build_work_pois(pois)

    poi_path = args.out_dir / "hong_kong_fixed_link_osm_pois.geojson"
    work_poi_path = args.out_dir / "hong_kong_fixed_link_osm_work_pois.geojson"
    write_geojson(pois, poi_path)
    write_geojson(work_pois, work_poi_path)

    summary = {
        "source": "Geofabrik Hong Kong OSM PBF",
        "source_url": args.pbf_url,
        "pbf": pbf_info,
        "boundary": str(args.boundary),
        "boundary_bounds_lonlat": [float(x) for x in boundary.total_bounds],
        "bbox_layer_rows": {
            "points": int(len(points)),
            "lines": int(len(lines)),
            "multipolygons": int(len(multipolygons)),
        },
        "poi_candidates": {
            "point_pois_bbox": int(len(point_pois_bbox)),
            "line_pois_bbox": int(len(line_pois_bbox)),
            "polygon_pois_bbox": int(len(polygon_pois_bbox)),
            "point_pois_inside_boundary": int(len(point_pois)),
            "line_pois_inside_boundary": int(len(line_pois)),
            "polygon_pois_inside_boundary": int(len(polygon_pois)),
        },
        "outputs": {
            "pois": str(poi_path),
            "poi_count": int(len(pois)),
            "work_pois": str(work_poi_path),
            "work_poi_count": int(len(work_pois)),
        },
        "note": "POI lines and polygons are represented by representative points inside the fixed-link boundary. Raw OSM contributor metadata is not included in Geofabrik public extracts.",
    }
    summary_path = args.out_dir / "osm_poi_extract_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
