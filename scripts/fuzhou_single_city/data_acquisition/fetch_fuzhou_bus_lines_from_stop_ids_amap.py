#!/usr/bin/env python
"""Fetch Fuzhou AMap bus lines through bus-stop POI IDs.

Pipeline:
1. Select bus-stop POIs within a 2 km Fuzhou-boundary buffer.
2. Query /v3/bus/stopid to discover line IDs serving each stop.
3. Query /v3/bus/lineid?extensions=all for full line detail.
4. Build full line, trajectory, stop-sequence, edge, service-frequency tables.
5. Merge original POI stops and line-detail stops into a complete stop set.

The script never writes the AMap API key. Pass --key or set AMAP_WEB_KEY.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import sys
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import geopandas as gpd
import pandas as pd
import requests
from pyproj import Transformer
from shapely.geometry import LineString, Point, mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POIS = PROJECT_ROOT / "data" / "transit" / "fuzhou_bus_stop_pois_amap" / "amap_bus_stop_pois_unique.csv"
DEFAULT_BOUNDARY = PROJECT_ROOT / "data" / "osm" / "fuzhou_city_23" / "fuzhou_city_23_boundary.geojson"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "transit" / "fuzhou_bus_amap_stopid_lineid"

AMAP_STOPID_URL = "https://restapi.amap.com/v3/bus/stopid"
AMAP_LINEID_URL = "https://restapi.amap.com/v3/bus/lineid"
CITY = "福州"

EE = 0.00669342162296594323
A = 6378245.0
PI = math.pi


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", default=os.environ.get("AMAP_WEB_KEY"), help="AMap Web Service key.")
    parser.add_argument("--stop-pois", type=Path, default=DEFAULT_POIS)
    parser.add_argument("--boundary", type=Path, default=DEFAULT_BOUNDARY)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--buffer-m", type=float, default=2000.0)
    parser.add_argument("--sleep", type=float, default=0.08)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--max-stops", type=int, default=0, help="Debug cap; 0 means all selected stops.")
    parser.add_argument("--max-lines", type=int, default=0, help="Debug cap; 0 means all discovered lines.")
    parser.add_argument("--cluster-distance-m", type=float, default=80.0)
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


def stable_id(*parts: Any, length: int = 16) -> str:
    text = "|".join("" if part is None else str(part) for part in parts)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:length]


def clean_scalar(value: Any) -> str:
    if value is None or value == [] or value == {}:
        return ""
    return str(value)


def as_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    return [value]


def parse_lonlat(location: str | None) -> tuple[float | None, float | None]:
    if not location or "," not in str(location):
        return None, None
    try:
        lon, lat = str(location).split(",", 1)
        return float(lon), float(lat)
    except Exception:
        return None, None


def parse_polyline(polyline: str | None) -> list[tuple[float, float]]:
    coords = []
    if not polyline:
        return coords
    for item in str(polyline).split(";"):
        lon, lat = parse_lonlat(item)
        if lon is not None and lat is not None:
            coords.append((lon, lat))
    return coords


def normalize_name(name: str) -> str:
    text = str(name or "").strip()
    text = re.sub(r"[（(]\s*公交站\s*[）)]", "", text)
    text = re.sub(r"\s+", "", text)
    return text.replace("·", "")


def parse_time_to_minutes(value: str | None) -> float | None:
    if not value:
        return None
    parts = str(value).split(":")
    try:
        if len(parts) == 3:
            h, m, s = [float(x) for x in parts]
            return h * 60 + m + s / 60
        if len(parts) == 2:
            h, m = [float(x) for x in parts]
            return h * 60 + m
    except Exception:
        return None
    return None


def decode_timedesc(value: Any) -> dict[str, Any] | None:
    if not value or value == [] or value == {}:
        return None
    text = str(value)
    if text in {"[]", '""', "''"}:
        return None
    try:
        obj = json.loads(unquote(text))
        if isinstance(obj, str):
            obj = json.loads(obj)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def service_rows_from_timedesc(line_id: str, line_name: str, direction: str, timedesc: Any) -> list[dict[str, Any]]:
    obj = decode_timedesc(timedesc)
    if not obj:
        return [
            {
                "line_id": line_id,
                "line_name": line_name,
                "direction": direction,
                "day_type": "",
                "day_week": "",
                "period_start": "",
                "period_end": "",
                "interval_time": "",
                "headway_minutes": "",
                "remark": "",
                "all_remark": "",
                "source": "not_returned_or_not_parseable_from_amap_timedesc",
                "notes": "Need operator source or manual observation for service frequency.",
            }
        ]
    rows: list[dict[str, Any]] = []
    all_remark = str(obj.get("allRemark") or "")
    for group in obj.get("rule_group") or []:
        date = group.get("date") or {}
        day_type = ",".join(str(x) for x in date.get("day_type") or [])
        day_week = ",".join(str(x) for x in date.get("day_week") or [])
        remark = str(group.get("remark") or "")
        for period in group.get("time_group") or []:
            interval_time = str(period.get("interval_time") or "")
            headway = parse_time_to_minutes(interval_time)
            rows.append(
                {
                    "line_id": line_id,
                    "line_name": line_name,
                    "direction": direction,
                    "day_type": day_type,
                    "day_week": day_week,
                    "period_start": str(period.get("start_time") or ""),
                    "period_end": str(period.get("end_time") or ""),
                    "interval_time": interval_time,
                    "headway_minutes": headway if headway is not None else "",
                    "remark": remark,
                    "all_remark": all_remark,
                    "source": "amap_timedesc",
                    "notes": "",
                }
            )
    if rows:
        return rows
    return [
        {
            "line_id": line_id,
            "line_name": line_name,
            "direction": direction,
            "day_type": "",
            "day_week": "",
            "period_start": "",
            "period_end": "",
            "interval_time": "",
            "headway_minutes": "",
            "remark": "",
            "all_remark": all_remark,
            "source": "amap_timedesc_without_rule_group",
            "notes": "Timedesc parsed, but no usable rule_group found.",
        }
    ]


def request_json(url: str, params: dict[str, Any], timeout: int, max_retries: int) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = requests.get(url, params=params, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
            info = payload.get("info", "")
            if payload.get("status") == "1":
                return payload
            if info == "USER_DAILY_QUERY_OVER_LIMIT":
                return payload
            if info in {"CUQPS_HAS_EXCEEDED_THE_LIMIT", "SERVICE_NOT_AVAILABLE"}:
                time.sleep(1.5 * (attempt + 1))
                continue
            return payload
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    return {"status": "0", "info": f"REQUEST_EXCEPTION:{type(last_error).__name__}:{last_error}"}


def load_jsonl_by_key(path: Path, key: str) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    out = {}
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except Exception:
                continue
            value = str(record.get(key) or "")
            if value:
                out[value] = record
    return out


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        fh.flush()


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_geojson(path: Path, features: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, indent=2), encoding="utf-8")


def select_stop_pois(args: argparse.Namespace) -> pd.DataFrame:
    df = pd.read_csv(args.stop_pois, encoding="utf-8-sig")
    boundary = gpd.read_file(args.boundary).to_crs("EPSG:32650")
    buffer_geom = boundary.geometry.iloc[0].buffer(args.buffer_m)
    points = gpd.GeoDataFrame(
        df,
        geometry=[Point(x, y) for x, y in zip(df["x_epsg32650"], df["y_epsg32650"])],
        crs="EPSG:32650",
    )
    selected = points[points.geometry.within(buffer_geom) | points.geometry.touches(buffer_geom)].copy()
    selected["inside_boundary_2km_buffer"] = True
    selected["distance_to_boundary_m"] = selected.geometry.distance(boundary.geometry.iloc[0].boundary)
    selected = selected.drop(columns=["geometry"])
    if args.max_stops:
        selected = selected.head(args.max_stops).copy()
    return selected


def fetch_stopid_responses(args: argparse.Namespace, selected_stops: pd.DataFrame, raw_path: Path) -> tuple[list[dict[str, Any]], bool, int]:
    cached = load_jsonl_by_key(raw_path, "stop_id")
    records: list[dict[str, Any]] = []
    stopped_by_limit = False
    new_requests = 0
    for idx, row in selected_stops.iterrows():
        stop_id = str(row["poi_id"])
        if stop_id in cached:
            records.append(cached[stop_id])
            continue
        payload = request_json(
            AMAP_STOPID_URL,
            {"key": args.key, "city": CITY, "id": stop_id},
            args.timeout,
            args.max_retries,
        )
        record = {
            "stop_id": stop_id,
            "stop_name": row.get("name", ""),
            "status": payload.get("status"),
            "info": payload.get("info"),
            "infocode": payload.get("infocode"),
            "payload": payload,
        }
        append_jsonl(raw_path, record)
        records.append(record)
        new_requests += 1
        if payload.get("info") == "USER_DAILY_QUERY_OVER_LIMIT":
            stopped_by_limit = True
            break
        if new_requests % 100 == 0:
            print(f"stopid requests: {new_requests} new, {len(records)}/{len(selected_stops)} total")
        time.sleep(args.sleep)
    return records, stopped_by_limit, new_requests


def build_stop_to_lines(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
    rows: list[dict[str, Any]] = []
    line_to_stops: dict[str, set[str]] = defaultdict(set)
    for record in records:
        stop_id = str(record.get("stop_id") or "")
        payload = record.get("payload") or {}
        for stop in as_list(payload.get("busstops")):
            if not isinstance(stop, dict):
                continue
            stop_name = clean_scalar(stop.get("name"))
            for line in as_list(stop.get("buslines")):
                if not isinstance(line, dict):
                    continue
                line_id = clean_scalar(line.get("id"))
                if not line_id:
                    continue
                line_to_stops[line_id].add(stop_id)
                rows.append(
                    {
                        "stop_id": stop_id,
                        "queried_stop_name": clean_scalar(record.get("stop_name")),
                        "returned_stop_id": clean_scalar(stop.get("id")),
                        "returned_stop_name": stop_name,
                        "line_id": line_id,
                        "line_name": clean_scalar(line.get("name")),
                        "line_type": clean_scalar(line.get("type")),
                        "start_stop": clean_scalar(line.get("start_stop")),
                        "end_stop": clean_scalar(line.get("end_stop")),
                    }
                )
    # avoid repeated stop-line pairs caused by odd API payload shapes
    unique = {}
    for row in rows:
        unique[(row["stop_id"], row["line_id"])] = row
    return list(unique.values()), line_to_stops


def fetch_lineid_responses(args: argparse.Namespace, line_ids: list[str], raw_path: Path) -> tuple[list[dict[str, Any]], bool, int]:
    cached = load_jsonl_by_key(raw_path, "line_id")
    records: list[dict[str, Any]] = []
    stopped_by_limit = False
    new_requests = 0
    if args.max_lines:
        line_ids = line_ids[: args.max_lines]
    for line_id in line_ids:
        if line_id in cached:
            records.append(cached[line_id])
            continue
        payload = request_json(
            AMAP_LINEID_URL,
            {"key": args.key, "city": CITY, "id": line_id, "extensions": "all"},
            args.timeout,
            args.max_retries,
        )
        record = {
            "line_id": line_id,
            "status": payload.get("status"),
            "info": payload.get("info"),
            "infocode": payload.get("infocode"),
            "payload": payload,
        }
        append_jsonl(raw_path, record)
        records.append(record)
        new_requests += 1
        if payload.get("info") == "USER_DAILY_QUERY_OVER_LIMIT":
            stopped_by_limit = True
            break
        if new_requests % 100 == 0:
            print(f"lineid requests: {new_requests} new, {len(records)}/{len(line_ids)} total")
        time.sleep(args.sleep)
    return records, stopped_by_limit, new_requests


def point_from_gcj(lon_gcj: float | None, lat_gcj: float | None, transformer: Transformer) -> dict[str, Any]:
    if lon_gcj is None or lat_gcj is None:
        return {"lon_gcj02": "", "lat_gcj02": "", "lon_wgs84": "", "lat_wgs84": "", "x_epsg32650": "", "y_epsg32650": ""}
    lon_wgs, lat_wgs = gcj02_to_wgs84(lon_gcj, lat_gcj)
    x, y = transformer.transform(lon_wgs, lat_wgs)
    return {"lon_gcj02": lon_gcj, "lat_gcj02": lat_gcj, "lon_wgs84": lon_wgs, "lat_wgs84": lat_wgs, "x_epsg32650": x, "y_epsg32650": y}


def normalize_line_records(
    line_records: list[dict[str, Any]],
    line_to_source_stops: dict[str, set[str]],
    transformer: Transformer,
) -> dict[str, list[dict[str, Any]]]:
    line_rows: list[dict[str, Any]] = []
    trajectory_features: list[dict[str, Any]] = []
    stop_by_line_rows: list[dict[str, Any]] = []
    edge_rows: list[dict[str, Any]] = []
    service_rows: list[dict[str, Any]] = []
    line_stop_rows_for_union: list[dict[str, Any]] = []

    for record in line_records:
        payload = record.get("payload") or {}
        for idx, line in enumerate(as_list(payload.get("buslines"))):
            if not isinstance(line, dict):
                continue
            line_id = clean_scalar(line.get("id")) or str(record.get("line_id") or stable_id(line.get("name"), idx))
            line_name = clean_scalar(line.get("name"))
            start_stop = clean_scalar(line.get("start_stop"))
            end_stop = clean_scalar(line.get("end_stop"))
            direction = f"{start_stop}->{end_stop}"
            stops = [stop for stop in as_list(line.get("busstops")) if isinstance(stop, dict)]
            coords_gcj = parse_polyline(line.get("polyline"))
            coords_wgs = [gcj02_to_wgs84(lon, lat) for lon, lat in coords_gcj]

            line_rows.append(
                {
                    "line_id": line_id,
                    "line_name": line_name,
                    "line_type": clean_scalar(line.get("type")),
                    "company": clean_scalar(line.get("company")),
                    "start_stop": start_stop,
                    "end_stop": end_stop,
                    "start_time": clean_scalar(line.get("start_time")),
                    "end_time": clean_scalar(line.get("end_time")),
                    "status": clean_scalar(line.get("status")),
                    "direction_pair_line_id": clean_scalar(line.get("direc")),
                    "distance": clean_scalar(line.get("distance")),
                    "basic_price": clean_scalar(line.get("basic_price")),
                    "total_price": clean_scalar(line.get("total_price")),
                    "bounds": clean_scalar(line.get("bounds")),
                    "stop_count": len(stops),
                    "has_polyline": bool(coords_wgs),
                    "timedesc": clean_scalar(line.get("timedesc")),
                    "timedesc_parseable": decode_timedesc(line.get("timedesc")) is not None,
                    "source_stop_ids": ";".join(sorted(line_to_source_stops.get(line_id, set()))),
                }
            )
            service_rows.extend(service_rows_from_timedesc(line_id, line_name, direction, line.get("timedesc")))

            if len(coords_wgs) >= 2:
                trajectory_features.append(
                    {
                        "type": "Feature",
                        "geometry": mapping(LineString(coords_wgs)),
                        "properties": {
                            "line_id": line_id,
                            "line_name": line_name,
                            "start_stop": start_stop,
                            "end_stop": end_stop,
                            "coord_source": "AMap GCJ-02 converted to WGS84",
                        },
                    }
                )

            previous = None
            for stop_index, stop in enumerate(stops, start=1):
                stop_id = clean_scalar(stop.get("id")) or stable_id(line_id, stop_index, stop.get("name"), stop.get("location"))
                stop_name = clean_scalar(stop.get("name"))
                lon_gcj, lat_gcj = parse_lonlat(stop.get("location"))
                coords = point_from_gcj(lon_gcj, lat_gcj, transformer)
                occurrence_id = f"{line_id}_{stop_index:03d}_{stop_id}"
                row = {
                    "occurrence_id": occurrence_id,
                    "line_id": line_id,
                    "line_name": line_name,
                    "stop_sequence": stop_index,
                    "station_id": stop_id,
                    "station_name": stop_name,
                    **coords,
                }
                stop_by_line_rows.append(row)
                line_stop_rows_for_union.append(
                    {
                        "source_id": stop_id,
                        "name": stop_name,
                        "normalized_name": normalize_name(stop_name),
                        "source_types": "lineid_busstop",
                        "line_ids": line_id,
                        **coords,
                    }
                )
                if previous is not None:
                    edge_rows.append(
                        {
                            "edge_id": f"{line_id}_{previous['stop_sequence']:03d}_{stop_index:03d}",
                            "line_id": line_id,
                            "line_name": line_name,
                            "from_sequence": previous["stop_sequence"],
                            "to_sequence": stop_index,
                            "from_station_id": previous["station_id"],
                            "from_station_name": previous["station_name"],
                            "to_station_id": stop_id,
                            "to_station_name": stop_name,
                            "from_lon_wgs84": previous["lon_wgs84"],
                            "from_lat_wgs84": previous["lat_wgs84"],
                            "to_lon_wgs84": coords["lon_wgs84"],
                            "to_lat_wgs84": coords["lat_wgs84"],
                        }
                    )
                previous = row

    return {
        "lines": line_rows,
        "trajectories": trajectory_features,
        "stops_by_line": stop_by_line_rows,
        "edges": edge_rows,
        "service": service_rows,
        "line_stop_rows_for_union": line_stop_rows_for_union,
    }


def make_original_stop_rows(selected_stops: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    for _, row in selected_stops.iterrows():
        rows.append(
            {
                "source_id": str(row["poi_id"]),
                "name": clean_scalar(row.get("name")),
                "normalized_name": normalize_name(clean_scalar(row.get("name"))),
                "source_types": "poi",
                "line_ids": "",
                "lon_gcj02": row.get("lon_gcj02", ""),
                "lat_gcj02": row.get("lat_gcj02", ""),
                "lon_wgs84": row.get("lon_wgs84", ""),
                "lat_wgs84": row.get("lat_wgs84", ""),
                "x_epsg32650": row.get("x_epsg32650", ""),
                "y_epsg32650": row.get("y_epsg32650", ""),
            }
        )
    return rows


def merge_by_source_id(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("source_id") or stable_id(row.get("name"), row.get("lon_wgs84"), row.get("lat_wgs84")))].append(row)
    out = []
    for source_id, items in grouped.items():
        poi_items = [item for item in items if "poi" in str(item.get("source_types"))]
        base = dict(poi_items[0] if poi_items else items[0])
        base["source_id"] = source_id
        base["source_ids"] = source_id
        base["source_types"] = ";".join(sorted({t for item in items for t in str(item.get("source_types", "")).split(";") if t}))
        base["line_ids"] = ";".join(sorted({line for item in items for line in str(item.get("line_ids", "")).split(";") if line}))
        base["raw_record_count"] = len(items)
        out.append(base)
    return out


def cluster_complete_stops(rows: list[dict[str, Any]], distance_m: float) -> list[dict[str, Any]]:
    by_name: dict[str, list[int]] = defaultdict(list)
    for idx, row in enumerate(rows):
        by_name[str(row.get("normalized_name") or "")].append(idx)

    clusters: list[list[int]] = []
    for _, indices in by_name.items():
        remaining = set(indices)
        while remaining:
            seed = remaining.pop()
            cluster = [seed]
            stack = [seed]
            while stack:
                cur = stack.pop()
                try:
                    cx = float(rows[cur]["x_epsg32650"])
                    cy = float(rows[cur]["y_epsg32650"])
                except Exception:
                    continue
                near = []
                for idx in list(remaining):
                    try:
                        dist = math.hypot(float(rows[idx]["x_epsg32650"]) - cx, float(rows[idx]["y_epsg32650"]) - cy)
                    except Exception:
                        continue
                    if dist <= distance_m:
                        near.append(idx)
                for idx in near:
                    remaining.remove(idx)
                    stack.append(idx)
                    cluster.append(idx)
            clusters.append(cluster)

    merged = []
    for seq, cluster in enumerate(clusters, start=1):
        items = [rows[idx] for idx in cluster]
        poi_items = [item for item in items if "poi" in str(item.get("source_types"))]
        base = dict(poi_items[0] if poi_items else items[0])
        source_ids = sorted({sid for item in items for sid in str(item.get("source_ids") or item.get("source_id") or "").split(";") if sid})
        source_types = sorted({t for item in items for t in str(item.get("source_types", "")).split(";") if t})
        line_ids = sorted({line for item in items for line in str(item.get("line_ids", "")).split(";") if line})
        base["merged_stop_id"] = f"amap_stop_{seq:05d}"
        base["source_ids"] = ";".join(source_ids)
        base["source_types"] = ";".join(source_types)
        base["line_ids"] = ";".join(line_ids)
        base["source_id_count"] = len(source_ids)
        base["merge_member_count"] = len(items)
        base["merge_method"] = "same_id" if len(items) == 1 and len(source_ids) == 1 else "same_name_80m_cluster"
        merged.append(base)
    return merged


def add_boundary_flags(rows: list[dict[str, Any]], boundary_path: Path, buffer_m: float) -> None:
    boundary = gpd.read_file(boundary_path).to_crs("EPSG:32650").geometry.iloc[0]
    buffer_geom = boundary.buffer(buffer_m)
    for row in rows:
        try:
            pt = Point(float(row["x_epsg32650"]), float(row["y_epsg32650"]))
            row["inside_boundary"] = bool(pt.within(boundary) or pt.touches(boundary))
            row["inside_boundary_2km_buffer"] = bool(pt.within(buffer_geom) or pt.touches(buffer_geom))
        except Exception:
            row["inside_boundary"] = False
            row["inside_boundary_2km_buffer"] = False


def write_complete_stops(rows: list[dict[str, Any]], output_dir: Path) -> None:
    fieldnames = [
        "merged_stop_id",
        "source_ids",
        "source_id_count",
        "name",
        "normalized_name",
        "source_types",
        "line_ids",
        "merge_member_count",
        "merge_method",
        "lon_gcj02",
        "lat_gcj02",
        "lon_wgs84",
        "lat_wgs84",
        "x_epsg32650",
        "y_epsg32650",
        "inside_boundary",
        "inside_boundary_2km_buffer",
        "raw_record_count",
    ]
    write_csv(output_dir / "amap_bus_stops_complete.csv", rows, fieldnames)
    features = []
    for row in rows:
        try:
            geom = Point(float(row["lon_wgs84"]), float(row["lat_wgs84"]))
        except Exception:
            continue
        props = {key: value for key, value in row.items() if key not in {"geometry"}}
        features.append({"type": "Feature", "geometry": mapping(geom), "properties": props})
    write_geojson(output_dir / "amap_bus_stops_complete.geojson", features)

    diagnostics = [
        {
            "merged_stop_id": row["merged_stop_id"],
            "name": row["name"],
            "source_ids": row["source_ids"],
            "source_id_count": row["source_id_count"],
            "source_types": row["source_types"],
            "merge_method": row["merge_method"],
            "line_id_count": len([x for x in str(row.get("line_ids", "")).split(";") if x]),
        }
        for row in rows
        if int(row.get("source_id_count") or 0) > 1 or "lineid_busstop" not in str(row.get("source_types", ""))
    ]
    write_csv(output_dir / "amap_bus_stops_merge_diagnostics.csv", diagnostics)


def main() -> int:
    args = parse_args()
    if not args.key:
        print("Missing AMap key. Pass --key or set AMAP_WEB_KEY.", file=sys.stderr)
        return 2
    args.output_dir.mkdir(parents=True, exist_ok=True)
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:32650", always_xy=True)

    selected_stops = select_stop_pois(args)
    selected_stops.to_csv(args.output_dir / "amap_bus_stop_ids_selected_2km_buffer.csv", index=False, encoding="utf-8-sig")

    stop_raw = args.output_dir / "amap_stopid_raw_responses.jsonl"
    line_raw = args.output_dir / "amap_lineid_raw_responses.jsonl"
    stop_records, stop_limit, stop_new = fetch_stopid_responses(args, selected_stops, stop_raw)
    stop_to_lines, line_to_source_stops = build_stop_to_lines(stop_records)
    write_csv(args.output_dir / "amap_stop_to_lines.csv", stop_to_lines)

    line_ids = sorted(line_to_source_stops)
    line_records, line_limit, line_new = fetch_lineid_responses(args, line_ids, line_raw)
    normalized = normalize_line_records(line_records, line_to_source_stops, transformer)

    line_fields = [
        "line_id",
        "line_name",
        "line_type",
        "company",
        "start_stop",
        "end_stop",
        "start_time",
        "end_time",
        "status",
        "direction_pair_line_id",
        "distance",
        "basic_price",
        "total_price",
        "bounds",
        "stop_count",
        "has_polyline",
        "timedesc",
        "timedesc_parseable",
        "source_stop_ids",
    ]
    write_csv(args.output_dir / "amap_bus_lines_full.csv", normalized["lines"], line_fields)
    write_geojson(args.output_dir / "amap_bus_line_trajectories_full.geojson", normalized["trajectories"])
    write_csv(args.output_dir / "amap_bus_stops_by_line_full.csv", normalized["stops_by_line"])
    write_csv(args.output_dir / "amap_bus_adjacent_stop_edges_full.csv", normalized["edges"])
    write_csv(args.output_dir / "amap_bus_service_frequency_full.csv", normalized["service"])

    original_stop_rows = make_original_stop_rows(selected_stops)
    id_merged = merge_by_source_id(original_stop_rows + normalized["line_stop_rows_for_union"])
    complete_stops = cluster_complete_stops(id_merged, args.cluster_distance_m)
    add_boundary_flags(complete_stops, args.boundary, args.buffer_m)
    write_complete_stops(complete_stops, args.output_dir)

    nonempty_headway = [
        row
        for row in normalized["service"]
        if str(row.get("headway_minutes", "")) not in {"", "nan", "None"}
    ]
    selected_ids = set(selected_stops["poi_id"].astype(str))
    complete_source_ids = {sid for row in complete_stops for sid in str(row.get("source_ids", "")).split(";") if sid}
    summary = {
        "stop_pois_input": str(args.stop_pois),
        "boundary": str(args.boundary),
        "buffer_m": args.buffer_m,
        "selected_stop_ids": int(len(selected_stops)),
        "stopid_raw_records": int(len(stop_records)),
        "stopid_new_requests": int(stop_new),
        "stopid_stopped_by_daily_limit": stop_limit,
        "stop_to_line_pairs": int(len(stop_to_lines)),
        "unique_line_ids_discovered": int(len(line_ids)),
        "lineid_raw_records": int(len(line_records)),
        "lineid_new_requests": int(line_new),
        "lineid_stopped_by_daily_limit": line_limit,
        "line_records_full": int(len(normalized["lines"])),
        "line_trajectories": int(len(normalized["trajectories"])),
        "stops_by_line_records": int(len(normalized["stops_by_line"])),
        "adjacent_stop_edges": int(len(normalized["edges"])),
        "service_frequency_rows": int(len(normalized["service"])),
        "nonempty_headway_rows": int(len(nonempty_headway)),
        "lines_with_headway": int(len({row["line_id"] for row in nonempty_headway})),
        "original_selected_stop_ids_retained": int(len(selected_ids & complete_source_ids)),
        "complete_stop_count": int(len(complete_stops)),
        "complete_stops_inside_boundary": int(sum(1 for row in complete_stops if row.get("inside_boundary"))),
        "complete_stops_inside_2km_buffer": int(sum(1 for row in complete_stops if row.get("inside_boundary_2km_buffer"))),
        "outputs": [
            "amap_bus_stop_ids_selected_2km_buffer.csv",
            "amap_stopid_raw_responses.jsonl",
            "amap_lineid_raw_responses.jsonl",
            "amap_stop_to_lines.csv",
            "amap_bus_lines_full.csv",
            "amap_bus_line_trajectories_full.geojson",
            "amap_bus_stops_by_line_full.csv",
            "amap_bus_adjacent_stop_edges_full.csv",
            "amap_bus_service_frequency_full.csv",
            "amap_bus_stops_complete.csv",
            "amap_bus_stops_complete.geojson",
            "amap_bus_stops_merge_diagnostics.csv",
            "amap_bus_line_fetch_summary.json",
        ],
    }
    (args.output_dir / "amap_bus_line_fetch_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
