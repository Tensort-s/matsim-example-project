#!/usr/bin/env python
"""Fetch Fuzhou bus-stop POIs from AMap with tiled polygon search.

This script only discovers bus-stop POIs and their AMap POI IDs. It does not
call AMap bus stop-id or bus line-id APIs. Pass the API key with --key or the
AMAP_WEB_KEY environment variable. The key is never written to outputs.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import requests
from pyproj import Transformer
from shapely.geometry import Point, box, mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BOUNDARY = PROJECT_ROOT / "data" / "osm" / "fuzhou_city_23" / "fuzhou_city_23_boundary.geojson"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "transit" / "fuzhou_bus_stop_pois_amap"

AMAP_PLACE_POLYGON_URL = "https://restapi.amap.com/v3/place/polygon"
AMAP_PLACE_TEXT_URL = "https://restapi.amap.com/v3/place/text"

BUS_STOP_TYPECODE = "150700"
BUS_STOP_KEYWORD = "公交站"
CITY = "福州"

EE = 0.00669342162296594323
A = 6378245.0
PI = math.pi


@dataclass
class Tile:
    tile_id: str
    geom_32650: Any
    level: int
    size_m: float
    parent_id: str = ""
    is_terminal: bool = False
    was_subdivided: bool = False
    saturation_warning: bool = False
    status: str = ""
    info: str = ""
    reported_count: int = 0
    pages_requested: int = 0
    poi_records: int = 0
    kept_records: int = 0
    child_ids: list[str] = field(default_factory=list)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", default=os.environ.get("AMAP_WEB_KEY"), help="AMap Web Service key.")
    parser.add_argument("--boundary", type=Path, default=DEFAULT_BOUNDARY)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--tile-size-m", type=float, default=3000.0)
    parser.add_argument("--tile-overlap-m", type=float, default=250.0)
    parser.add_argument("--boundary-buffer-m", type=float, default=500.0)
    parser.add_argument("--min-tile-size-m", type=float, default=375.0)
    parser.add_argument("--saturation-count", type=int, default=180)
    parser.add_argument("--offset", type=int, default=25)
    parser.add_argument("--max-pages", type=int, default=8)
    parser.add_argument("--sleep", type=float, default=0.35)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--max-requests", type=int, default=0, help="Safety cap; 0 means no cap.")
    parser.add_argument(
        "--skip-citywide-probe",
        action="store_true",
        help="Skip the diagnostic whole-city text-search paging probe.",
    )
    return parser.parse_args()


def transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * PI) + 20.0 * math.sin(2.0 * x * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * PI) + 40.0 * math.sin(y / 3.0 * PI)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * PI) + 320 * math.sin(y * PI / 30.0)) * 2.0 / 3.0
    return ret


def transform_lon(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * PI) + 20.0 * math.sin(2.0 * x * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * PI) + 40.0 * math.sin(x / 3.0 * PI)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * PI) + 300.0 * math.sin(x / 30.0 * PI)) * 2.0 / 3.0
    return ret


def out_of_china(lon: float, lat: float) -> bool:
    return lon < 72.004 or lon > 137.8347 or lat < 0.8293 or lat > 55.8271


def wgs84_to_gcj02(lon: float, lat: float) -> tuple[float, float]:
    if out_of_china(lon, lat):
        return lon, lat
    dlat = transform_lat(lon - 105.0, lat - 35.0)
    dlon = transform_lon(lon - 105.0, lat - 35.0)
    radlat = lat / 180.0 * PI
    magic = math.sin(radlat)
    magic = 1 - EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((A * (1 - EE)) / (magic * sqrtmagic) * PI)
    dlon = (dlon * 180.0) / (A / sqrtmagic * math.cos(radlat) * PI)
    return lon + dlon, lat + dlat


def gcj02_to_wgs84(lon: float, lat: float) -> tuple[float, float]:
    glon, glat = wgs84_to_gcj02(lon, lat)
    return lon * 2 - glon, lat * 2 - glat


def normalize_name(name: str) -> str:
    text = str(name or "").strip()
    text = re.sub(r"[（(]\s*公交站\s*[）)]", "", text)
    text = re.sub(r"\s+", "", text)
    text = text.replace("·", "")
    return text


def parse_location(location: str | None) -> tuple[float | None, float | None]:
    if not location or "," not in location:
        return None, None
    try:
        lon, lat = location.split(",", 1)
        return float(lon), float(lat)
    except Exception:
        return None, None


def request_json(url: str, params: dict[str, Any], timeout: int, max_retries: int) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = requests.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
            info = payload.get("info", "")
            if payload.get("status") == "1" or info not in {"CUQPS_HAS_EXCEEDED_THE_LIMIT", "SERVICE_NOT_AVAILABLE"}:
                return payload
            time.sleep(1.5 * (attempt + 1))
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    if last_error is not None:
        return {"status": "0", "info": f"REQUEST_EXCEPTION:{type(last_error).__name__}:{last_error}"}
    return {"status": "0", "info": "REQUEST_FAILED"}


def load_boundary(path: Path) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    boundary_4326 = gpd.read_file(path).to_crs("EPSG:4326")
    if len(boundary_4326) != 1:
        raise RuntimeError(f"Expected one Fuzhou boundary feature, got {len(boundary_4326)}: {path}")
    return boundary_4326, boundary_4326.to_crs("EPSG:32650")


def build_initial_tiles(boundary_32650: gpd.GeoDataFrame, tile_size: float, overlap: float, buffer_m: float) -> list[Tile]:
    boundary_buffer = boundary_32650.geometry.iloc[0].buffer(buffer_m)
    minx, miny, maxx, maxy = boundary_buffer.bounds
    step = tile_size - overlap
    if step <= 0:
        raise ValueError("--tile-overlap-m must be smaller than --tile-size-m")

    tiles: list[Tile] = []
    x = minx
    row = 0
    while x < maxx:
        y = miny
        col = 0
        while y < maxy:
            geom = box(x, y, x + tile_size, y + tile_size)
            if geom.intersects(boundary_buffer):
                tiles.append(Tile(tile_id=f"L0_{row:03d}_{col:03d}", geom_32650=geom, level=0, size_m=tile_size))
            y += step
            col += 1
        x += step
        row += 1
    return tiles


def subdivide_tile(tile: Tile) -> list[Tile]:
    minx, miny, maxx, maxy = tile.geom_32650.bounds
    midx = (minx + maxx) / 2.0
    midy = (miny + maxy) / 2.0
    child_size = tile.size_m / 2.0
    boxes = [
        (minx, miny, midx, midy),
        (midx, miny, maxx, midy),
        (minx, midy, midx, maxy),
        (midx, midy, maxx, maxy),
    ]
    return [
        Tile(
            tile_id=f"{tile.tile_id}_{idx}",
            geom_32650=box(*bounds),
            level=tile.level + 1,
            size_m=child_size,
            parent_id=tile.tile_id,
        )
        for idx, bounds in enumerate(boxes)
    ]


def tile_polygon_param(tile: Tile, transformer_32650_to_4326: Transformer) -> str:
    minx, miny, maxx, maxy = tile.geom_32650.bounds
    lon1, lat1 = transformer_32650_to_4326.transform(minx, miny)
    lon2, lat2 = transformer_32650_to_4326.transform(maxx, maxy)
    gcj_sw = wgs84_to_gcj02(min(lon1, lon2), min(lat1, lat2))
    gcj_ne = wgs84_to_gcj02(max(lon1, lon2), max(lat1, lat2))
    return f"{gcj_sw[0]:.6f},{gcj_sw[1]:.6f}|{gcj_ne[0]:.6f},{gcj_ne[1]:.6f}"


def fetch_tile(
    tile: Tile,
    key: str,
    args: argparse.Namespace,
    raw_fh: Any,
    transformer_32650_to_4326: Transformer,
) -> tuple[list[tuple[dict[str, Any], int]], int]:
    all_pois: list[tuple[dict[str, Any], int]] = []
    full_pages = 0
    polygon = tile_polygon_param(tile, transformer_32650_to_4326)

    for page in range(1, args.max_pages + 1):
        params = {
            "key": key,
            "polygon": polygon,
            "keywords": BUS_STOP_KEYWORD,
            "types": BUS_STOP_TYPECODE,
            "extensions": "base",
            "offset": args.offset,
            "page": page,
        }
        payload = request_json(AMAP_PLACE_POLYGON_URL, params, args.timeout, args.max_retries)
        tile.pages_requested += 1
        try:
            reported_count = int(payload.get("count") or 0)
        except Exception:
            reported_count = 0
        tile.reported_count = max(tile.reported_count, reported_count)
        tile.status = str(payload.get("status", ""))
        tile.info = str(payload.get("info", ""))

        pois = payload.get("pois") or []
        if not isinstance(pois, list):
            pois = []
        tile.poi_records += len(pois)
        all_pois.extend((poi, page) for poi in pois if isinstance(poi, dict))

        raw_record = {
            "tile_id": tile.tile_id,
            "parent_id": tile.parent_id,
            "level": tile.level,
            "size_m": tile.size_m,
            "page": page,
            "status": payload.get("status"),
            "info": payload.get("info"),
            "infocode": payload.get("infocode"),
            "count": payload.get("count"),
            "pois_returned": len(pois),
            "pois": pois,
        }
        raw_fh.write(json.dumps(raw_record, ensure_ascii=False) + "\n")
        raw_fh.flush()

        if len(pois) >= args.offset:
            full_pages += 1
        if payload.get("status") != "1":
            break
        if len(pois) < args.offset:
            break
        time.sleep(args.sleep)

    return all_pois, full_pages


def is_bus_stop_poi(poi: dict[str, Any]) -> bool:
    if not poi.get("id"):
        return False
    ptype = str(poi.get("type") or "")
    name = str(poi.get("name") or "")
    typecode = str(poi.get("typecode") or "")
    if BUS_STOP_TYPECODE and typecode and not typecode.startswith(BUS_STOP_TYPECODE[:4]):
        return False
    return ("交通设施服务" in ptype and "公交车站" in ptype) or "公交站" in name


def flatten_address(value: Any) -> str:
    if value in (None, [], {}):
        return ""
    return str(value)


def poi_to_row(
    poi: dict[str, Any],
    tile: Tile,
    page: int,
    boundary_geom_32650: Any,
    boundary_buffer_geom_32650: Any,
    transformer_4326_to_32650: Transformer,
) -> dict[str, Any] | None:
    lon_gcj, lat_gcj = parse_location(poi.get("location"))
    if lon_gcj is None or lat_gcj is None:
        return None
    lon_wgs84, lat_wgs84 = gcj02_to_wgs84(lon_gcj, lat_gcj)
    x_32650, y_32650 = transformer_4326_to_32650.transform(lon_wgs84, lat_wgs84)
    point_32650 = Point(x_32650, y_32650)
    return {
        "poi_id": poi.get("id", ""),
        "name": poi.get("name", ""),
        "normalized_name": normalize_name(str(poi.get("name") or "")),
        "type": poi.get("type", ""),
        "typecode": poi.get("typecode", ""),
        "address": flatten_address(poi.get("address")),
        "pname": poi.get("pname", ""),
        "cityname": poi.get("cityname", ""),
        "adname": poi.get("adname", ""),
        "lon_gcj02": lon_gcj,
        "lat_gcj02": lat_gcj,
        "lon_wgs84": lon_wgs84,
        "lat_wgs84": lat_wgs84,
        "x_epsg32650": x_32650,
        "y_epsg32650": y_32650,
        "inside_boundary": bool(point_32650.within(boundary_geom_32650) or point_32650.touches(boundary_geom_32650)),
        "inside_boundary_500m_buffer": bool(
            point_32650.within(boundary_buffer_geom_32650) or point_32650.touches(boundary_buffer_geom_32650)
        ),
        "source_tile_ids": tile.tile_id,
        "source_pages": str(page),
        "duplicate_count": 1,
        "stop_cluster_id": "",
        "saturation_warning": bool(tile.saturation_warning),
    }


def assign_clusters(rows: list[dict[str, Any]], distance_m: float = 80.0) -> None:
    by_name: dict[str, list[int]] = defaultdict(list)
    for idx, row in enumerate(rows):
        by_name[row["normalized_name"]].append(idx)

    cluster_seq = 0
    for name, indices in by_name.items():
        remaining = set(indices)
        while remaining:
            seed = remaining.pop()
            cluster = [seed]
            stack = [seed]
            while stack:
                current = stack.pop()
                cx = float(rows[current]["x_epsg32650"])
                cy = float(rows[current]["y_epsg32650"])
                near = [
                    idx
                    for idx in remaining
                    if math.hypot(float(rows[idx]["x_epsg32650"]) - cx, float(rows[idx]["y_epsg32650"]) - cy)
                    <= distance_m
                ]
                for idx in near:
                    remaining.remove(idx)
                    stack.append(idx)
                    cluster.append(idx)
            cluster_seq += 1
            cluster_id = f"{name or 'unnamed'}_{cluster_seq:05d}"
            for idx in cluster:
                rows[idx]["stop_cluster_id"] = cluster_id


def deduplicate_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["poi_id"])].append(row)

    unique: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    for poi_id, items in sorted(grouped.items()):
        base = dict(items[0])
        source_tiles = sorted({str(item["source_tile_ids"]) for item in items})
        source_pages = sorted({str(item["source_pages"]) for item in items if str(item.get("source_pages", ""))})
        base["source_tile_ids"] = ";".join(source_tiles)
        base["source_pages"] = ";".join(source_pages)
        base["duplicate_count"] = len(items)
        base["saturation_warning"] = any(bool(item["saturation_warning"]) for item in items)
        base["inside_boundary"] = any(bool(item["inside_boundary"]) for item in items)
        base["inside_boundary_500m_buffer"] = any(bool(item["inside_boundary_500m_buffer"]) for item in items)
        unique.append(base)
        if len(items) > 1:
            duplicates.append(
                {
                    "poi_id": poi_id,
                    "name": base["name"],
                    "duplicate_count": len(items),
                    "source_tile_ids": ";".join(source_tiles),
                }
            )
    assign_clusters(unique)
    return unique, duplicates


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_points_geojson(path: Path, rows: list[dict[str, Any]]) -> None:
    if rows:
        gdf = gpd.GeoDataFrame(
            rows,
            geometry=[Point(float(row["lon_wgs84"]), float(row["lat_wgs84"])) for row in rows],
            crs="EPSG:4326",
        )
    else:
        gdf = gpd.GeoDataFrame(rows, geometry=[], crs="EPSG:4326")
    gdf.to_file(path, driver="GeoJSON")


def write_tiles_geojson(path: Path, tiles: list[Tile]) -> None:
    rows = []
    for tile in tiles:
        rows.append(
            {
                "tile_id": tile.tile_id,
                "parent_id": tile.parent_id,
                "level": tile.level,
                "size_m": tile.size_m,
                "is_terminal": tile.is_terminal,
                "was_subdivided": tile.was_subdivided,
                "saturation_warning": tile.saturation_warning,
                "status": tile.status,
                "info": tile.info,
                "reported_count": tile.reported_count,
                "pages_requested": tile.pages_requested,
                "poi_records": tile.poi_records,
                "kept_records": tile.kept_records,
                "child_ids": ";".join(tile.child_ids),
                "geometry": tile.geom_32650,
            }
        )
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:32650").to_crs("EPSG:4326")
    gdf.to_file(path, driver="GeoJSON")


def citywide_probe(key: str, args: argparse.Namespace) -> dict[str, Any]:
    pages = []
    total_seen = 0
    for page in range(1, 11):
        payload = request_json(
            AMAP_PLACE_TEXT_URL,
            {
                "key": key,
                "keywords": BUS_STOP_KEYWORD,
                "types": BUS_STOP_TYPECODE,
                "city": CITY,
                "citylimit": "true",
                "extensions": "base",
                "offset": args.offset,
                "page": page,
            },
            args.timeout,
            args.max_retries,
        )
        pois = payload.get("pois") or []
        total_seen += len(pois) if isinstance(pois, list) else 0
        pages.append(
            {
                "page": page,
                "status": payload.get("status"),
                "info": payload.get("info"),
                "count": payload.get("count"),
                "pois_returned": len(pois) if isinstance(pois, list) else 0,
            }
        )
        if payload.get("status") != "1" or len(pois) < args.offset:
            break
        time.sleep(args.sleep)
    return {"pages": pages, "total_seen": total_seen}


def main() -> int:
    args = parse_args()
    if not args.key:
        print("Missing AMap key. Pass --key or set AMAP_WEB_KEY.", file=sys.stderr)
        return 2

    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw_pages_path = args.output_dir / "amap_bus_stop_pois_raw_pages.jsonl"

    boundary_4326, boundary_32650 = load_boundary(args.boundary)
    boundary_geom_32650 = boundary_32650.geometry.iloc[0]
    boundary_buffer_geom_32650 = boundary_geom_32650.buffer(args.boundary_buffer_m)
    transformer_32650_to_4326 = Transformer.from_crs("EPSG:32650", "EPSG:4326", always_xy=True)
    transformer_4326_to_32650 = Transformer.from_crs("EPSG:4326", "EPSG:32650", always_xy=True)

    initial_tiles = build_initial_tiles(
        boundary_32650,
        tile_size=args.tile_size_m,
        overlap=args.tile_overlap_m,
        buffer_m=args.boundary_buffer_m,
    )
    queue = deque(initial_tiles)
    all_tiles: list[Tile] = []
    terminal_rows: list[dict[str, Any]] = []
    request_count = 0
    stopped_by_request_cap = False

    with raw_pages_path.open("w", encoding="utf-8") as raw_fh:
        while queue:
            tile = queue.popleft()
            if args.max_requests and request_count >= args.max_requests:
                stopped_by_request_cap = True
                break
            if not tile.geom_32650.intersects(boundary_buffer_geom_32650):
                continue

            pois, full_pages = fetch_tile(tile, args.key, args, raw_fh, transformer_32650_to_4326)
            request_count += tile.pages_requested
            saturated = tile.reported_count >= args.saturation_count or full_pages >= args.max_pages
            can_subdivide = tile.size_m > args.min_tile_size_m + 1e-9

            if saturated and can_subdivide:
                children = [child for child in subdivide_tile(tile) if child.geom_32650.intersects(boundary_buffer_geom_32650)]
                tile.was_subdivided = True
                tile.child_ids = [child.tile_id for child in children]
                queue.extend(children)
            else:
                tile.is_terminal = True
                tile.saturation_warning = saturated and not can_subdivide
                kept = 0
                for poi, page in pois:
                    if not is_bus_stop_poi(poi):
                        continue
                    row = poi_to_row(
                        poi,
                        tile,
                        page,
                        boundary_geom_32650,
                        boundary_buffer_geom_32650,
                        transformer_4326_to_32650,
                    )
                    if row is None:
                        continue
                    terminal_rows.append(row)
                    kept += 1
                tile.kept_records = kept
            all_tiles.append(tile)
            time.sleep(args.sleep)

    unique_rows, duplicate_rows = deduplicate_rows(terminal_rows)
    fieldnames = [
        "poi_id",
        "name",
        "normalized_name",
        "type",
        "typecode",
        "address",
        "pname",
        "cityname",
        "adname",
        "lon_gcj02",
        "lat_gcj02",
        "lon_wgs84",
        "lat_wgs84",
        "x_epsg32650",
        "y_epsg32650",
        "inside_boundary",
        "inside_boundary_500m_buffer",
        "source_tile_ids",
        "source_pages",
        "duplicate_count",
        "stop_cluster_id",
        "saturation_warning",
    ]
    write_csv(args.output_dir / "amap_bus_stop_pois_unique.csv", unique_rows, fieldnames)
    write_points_geojson(args.output_dir / "amap_bus_stop_pois_unique.geojson", unique_rows)
    write_csv(args.output_dir / "amap_bus_stop_pois_duplicates.csv", duplicate_rows, ["poi_id", "name", "duplicate_count", "source_tile_ids"])
    write_tiles_geojson(args.output_dir / "amap_bus_stop_pois_tiles.geojson", all_tiles)

    saturation_rows = [
        {
            "tile_id": tile.tile_id,
            "parent_id": tile.parent_id,
            "level": tile.level,
            "size_m": tile.size_m,
            "was_subdivided": tile.was_subdivided,
            "saturation_warning": tile.saturation_warning,
            "reported_count": tile.reported_count,
            "pages_requested": tile.pages_requested,
            "poi_records": tile.poi_records,
            "kept_records": tile.kept_records,
        }
        for tile in all_tiles
        if tile.was_subdivided or tile.saturation_warning
    ]
    write_csv(
        args.output_dir / "amap_bus_stop_pois_saturation_tiles.csv",
        saturation_rows,
        [
            "tile_id",
            "parent_id",
            "level",
            "size_m",
            "was_subdivided",
            "saturation_warning",
            "reported_count",
            "pages_requested",
            "poi_records",
            "kept_records",
        ],
    )

    known_ids = {
        "BV10208391": "东街口(公交站)",
        "BV10553038": "火车站南广场(公交站)",
        "BV10665298": "宝龙城市广场(公交站)",
    }
    unique_ids = {str(row["poi_id"]) for row in unique_rows}
    summary = {
        "endpoint": AMAP_PLACE_POLYGON_URL,
        "boundary": str(args.boundary),
        "output_dir": str(args.output_dir),
        "tile_size_m": args.tile_size_m,
        "tile_overlap_m": args.tile_overlap_m,
        "boundary_buffer_m": args.boundary_buffer_m,
        "min_tile_size_m": args.min_tile_size_m,
        "saturation_count": args.saturation_count,
        "offset": args.offset,
        "max_pages": args.max_pages,
        "initial_tile_count": len(initial_tiles),
        "processed_tile_count": len(all_tiles),
        "terminal_tile_count": sum(1 for tile in all_tiles if tile.is_terminal),
        "subdivided_tile_count": sum(1 for tile in all_tiles if tile.was_subdivided),
        "saturation_warning_tile_count": sum(1 for tile in all_tiles if tile.saturation_warning),
        "request_count": request_count,
        "stopped_by_request_cap": stopped_by_request_cap,
        "terminal_raw_bus_stop_records": len(terminal_rows),
        "unique_poi_count": len(unique_rows),
        "duplicate_group_count": len(duplicate_rows),
        "dedup_removed_records": len(terminal_rows) - len(unique_rows),
        "inside_boundary_count": sum(1 for row in unique_rows if row["inside_boundary"]),
        "inside_boundary_500m_buffer_count": sum(1 for row in unique_rows if row["inside_boundary_500m_buffer"]),
        "known_sample_presence": {poi_id: poi_id in unique_ids for poi_id in known_ids},
        "citywide_probe": None if args.skip_citywide_probe else citywide_probe(args.key, args),
        "outputs": [
            "amap_bus_stop_pois_raw_pages.jsonl",
            "amap_bus_stop_pois_tiles.geojson",
            "amap_bus_stop_pois_unique.csv",
            "amap_bus_stop_pois_unique.geojson",
            "amap_bus_stop_pois_duplicates.csv",
            "amap_bus_stop_pois_saturation_tiles.csv",
            "amap_bus_stop_poi_fetch_summary.json",
        ],
    }
    (args.output_dir / "amap_bus_stop_poi_fetch_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
