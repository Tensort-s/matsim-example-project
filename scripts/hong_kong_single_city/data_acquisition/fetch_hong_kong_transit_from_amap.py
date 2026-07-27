#!/usr/bin/env python3
"""Collect missing Hong Kong transit data from AMap Web Service.

Official Hong Kong route-stop and CSDI data define the target inventory. AMap
is used only as a supplementary source for missing bus/GMB shapes and for MTR
and Light Rail line geometry, station coordinates, operating windows, fares,
and any parseable ``timedesc`` headways.

The API key is read from ``--key`` or AMAP_WEB_KEY/AMAP_KEY/AMAP_API_KEY and is
never written to logs, cache files, manifests, or normalized outputs.
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
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote

import requests


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_ROOT = ROOT / "data"
DEFAULT_OUTPUT = Path("transit/hongkong/AMap_Supplements")
AMAP_LINE_NAME_URL = "https://restapi.amap.com/v3/bus/linename"

EE = 0.00669342162296594323
EARTH_RADIUS = 6378137.0
A = 6378245.0
PI = math.pi

MTR_ALIASES: dict[str, list[str]] = {
    "AEL": ["香港机场快线", "机场快线", "機場快綫"],
    "DRL": ["香港迪士尼线", "迪士尼线", "迪士尼綫"],
    "EAL": ["香港东铁线", "东铁线", "東鐵綫"],
    "ISL": ["香港港岛线", "港岛线", "港島綫"],
    "KTL": ["香港观塘线", "观塘线", "觀塘綫"],
    "SIL": ["香港南港岛线", "南港岛线", "南港島綫"],
    "TCL": ["香港东涌线", "东涌线", "東涌綫"],
    "TKL": ["香港将军澳线", "将军澳线", "將軍澳綫"],
    "TML": ["香港屯马线", "屯马线", "屯馬綫"],
    "TWL": ["香港荃湾线", "荃湾线", "荃灣綫"],
}

MODE_HINTS = {
    "mtr": ("地铁", "地鐵", "轨道交通", "軌道交通", "subway", "metro"),
    "lrt": ("轻轨", "輕軌", "轻铁", "輕鐵", "有轨电车", "有軌電車", "light rail"),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_amap_key() -> str | None:
    for name in ("AMAP_WEB_KEY", "AMAP_KEY", "AMAP_API_KEY"):
        value = os.environ.get(name)
        if value:
            return value
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                for name in ("AMAP_WEB_KEY", "AMAP_KEY", "AMAP_API_KEY"):
                    try:
                        value, _ = winreg.QueryValueEx(key, name)
                    except FileNotFoundError:
                        continue
                    if value:
                        return str(value)
        except OSError:
            pass
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--key",
        default=default_amap_key(),
        help="AMap Web Service key. Prefer an environment variable.",
    )
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--city", default="香港")
    parser.add_argument("--pages", type=int, default=2)
    parser.add_argument("--offset", type=int, default=50)
    parser.add_argument("--sleep", type=float, default=0.25)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--max-retries", type=int, default=4)
    parser.add_argument("--max-keywords", type=int, default=0, help="Debug limit; 0 means all keywords.")
    parser.add_argument("--refresh", action="store_true", help="Ignore cached keyword responses.")
    parser.add_argument("--prepare-only", action="store_true", help="Write official targets and keywords without API calls.")
    parser.add_argument("--accept-score", type=float, default=55.0)
    return parser.parse_args()


def transform_lat(x: float, y: float) -> float:
    value = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y
    value += 0.2 * math.sqrt(abs(x))
    value += (20.0 * math.sin(6.0 * x * PI) + 20.0 * math.sin(2.0 * x * PI)) * 2.0 / 3.0
    value += (20.0 * math.sin(y * PI) + 40.0 * math.sin(y / 3.0 * PI)) * 2.0 / 3.0
    value += (160.0 * math.sin(y / 12.0 * PI) + 320 * math.sin(y * PI / 30.0)) * 2.0 / 3.0
    return value


def transform_lon(x: float, y: float) -> float:
    value = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y
    value += 0.1 * math.sqrt(abs(x))
    value += (20.0 * math.sin(6.0 * x * PI) + 20.0 * math.sin(2.0 * x * PI)) * 2.0 / 3.0
    value += (20.0 * math.sin(x * PI) + 40.0 * math.sin(x / 3.0 * PI)) * 2.0 / 3.0
    value += (150.0 * math.sin(x / 12.0 * PI) + 300.0 * math.sin(x / 30.0 * PI)) * 2.0 / 3.0
    return value


def wgs84_to_gcj02(lon: float, lat: float) -> tuple[float, float]:
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
    guess_lon, guess_lat = lon, lat
    for _ in range(6):
        projected_lon, projected_lat = wgs84_to_gcj02(guess_lon, guess_lat)
        guess_lon -= projected_lon - lon
        guess_lat -= projected_lat - lat
    return guess_lon, guess_lat


def parse_lonlat(value: Any) -> tuple[float | None, float | None]:
    if not value or "," not in str(value):
        return None, None
    try:
        lon, lat = str(value).split(",", 1)
        return float(lon), float(lat)
    except ValueError:
        return None, None


def parse_polyline(value: Any) -> list[tuple[float, float]]:
    coordinates: list[tuple[float, float]] = []
    if not value:
        return coordinates
    for part in str(value).split(";"):
        lon, lat = parse_lonlat(part)
        if lon is not None and lat is not None:
            coordinates.append((lon, lat))
    return coordinates


def as_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    return value if isinstance(value, list) else [value]


def normalize_name(value: Any) -> str:
    text = str(value or "").lower().strip()
    replacements = {
        "綫": "线",
        "鐵": "铁",
        "馬": "马",
        "東": "东",
        "島": "岛",
        "將": "将",
        "灣": "湾",
        "觀": "观",
        "機場": "机场",
        "廸": "迪",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"[（(].*?[）)]", "", text)
    text = re.sub(
        r"香港|港铁|港鐵|巴士|公交|小巴|地铁|地鐵|轻铁|輕鐵|轻轨|輕軌|线路|線路|路线|路線|号线|號線|線|线|路|站",
        "",
        text,
    )
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", text)


def stable_hash(value: str, length: int = 16) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1 = map(math.radians, a)
    lon2, lat2 = map(math.radians, b)
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS * math.asin(min(1.0, math.sqrt(h)))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        if not fields:
            return
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def route_keywords(mode: str, line_code: str, company: str) -> list[str]:
    code = str(line_code).strip()
    if mode == "gmb":
        return [f"香港小巴{code}", f"{code}小巴"]
    operator_prefixes = {
        "CTB": "城巴",
        "KMB": "九巴",
        "LWB": "龙运巴士",
    }
    if company in operator_prefixes:
        return [f"{operator_prefixes[company]}{code}", f"香港{code}路", code]
    if company == "LRTFeeder":
        return [f"港铁巴士{code}", f"香港{code}路"]
    if company == "DB":
        return [f"愉景湾巴士{code}", code]
    if company == "PI":
        return [f"珀丽湾巴士{code}", code]
    if company == "XB":
        return [code, f"香港跨境巴士{code}"]
    return [f"香港{code}路", code]


def grouped_point_features(path: Path) -> dict[tuple[str, str], list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for feature in payload.get("features") or []:
        props = feature.get("properties") or {}
        key = (str(props.get("routeId")), str(props.get("routeSeq")))
        groups[key].append(feature)
    for features in groups.values():
        features.sort(key=lambda feature: int((feature.get("properties") or {}).get("stopSeq") or 0))
    return groups


def point_coords(feature: dict[str, Any]) -> tuple[float | None, float | None]:
    coordinates = (feature.get("geometry") or {}).get("coordinates") or []
    if len(coordinates) < 2:
        return None, None
    return float(coordinates[0]), float(coordinates[1])


def build_official_targets(data_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    transit_root = data_root / "transit/hongkong"
    api_root = transit_root / "API_Supplements"
    coverage_path = api_root / "normalized/route_geometry_coverage.csv"
    coverage = read_csv(coverage_path)
    bus_groups = grouped_point_features(
        api_root / "static/routes_fares_route_stop_points/bus_route_stop_points.json"
    )
    gmb_groups = grouped_point_features(
        api_root / "static/routes_fares_route_stop_points/gmb_route_stop_points.json"
    )
    targets: list[dict[str, Any]] = []
    query_rows: list[dict[str, Any]] = []

    for mode, groups in (("bus", bus_groups), ("gmb", gmb_groups)):
        missing = [
            row
            for row in coverage
            if row.get("mode") == mode
            and row.get("has_route_stop_pattern", "").lower() == "true"
            and row.get("has_csdi_geometry", "").lower() == "false"
        ]
        for row in missing:
            key = (row["route_id"], row["route_seq"])
            features = groups.get(key) or []
            if not features:
                continue
            first = features[0]
            last = features[-1]
            first_props = first.get("properties") or {}
            last_props = last.get("properties") or {}
            first_lon, first_lat = point_coords(first)
            last_lon, last_lat = point_coords(last)
            target_id = f"{mode}_{row['route_id']}_{row['route_seq']}"
            keywords = route_keywords(mode, row["route_name"], row["company_code"])
            target = {
                "target_id": target_id,
                "mode": mode,
                "official_route_id": row["route_id"],
                "official_route_seq": row["route_seq"],
                "line_code": row["route_name"],
                "company_code": row["company_code"],
                "direction": row["route_seq"],
                "origin_name_zh": first_props.get("stopNameC", ""),
                "destination_name_zh": last_props.get("stopNameC", ""),
                "origin_name_en": first_props.get("stopNameE", ""),
                "destination_name_en": last_props.get("stopNameE", ""),
                "origin_lon_wgs84": first_lon,
                "origin_lat_wgs84": first_lat,
                "destination_lon_wgs84": last_lon,
                "destination_lat_wgs84": last_lat,
                "official_stop_count": len(features),
                "official_station_names_zh": "|".join(
                    str((feature.get("properties") or {}).get("stopNameC") or "")
                    for feature in features
                ),
                "query_keywords": "|".join(dict.fromkeys(keywords)),
            }
            targets.append(target)
            for rank, keyword in enumerate(dict.fromkeys(keywords), start=1):
                query_rows.append(
                    {"target_id": target_id, "mode": mode, "query_rank": rank, "keyword": keyword}
                )

    rail_specs = [
        ("mtr", transit_root / "MTR/mtr_lines_and_stations.csv", "Line Code", "Direction"),
        ("lrt", transit_root / "MTR/light_rail_routes_and_stops.csv", "Line Code", "Direction"),
    ]
    for mode, path, line_field, direction_field in rail_specs:
        rows = read_csv(path)
        groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
        for row in rows:
            if row.get(line_field) and row.get(direction_field):
                groups[(row[line_field], row[direction_field])].append(row)
        for (line_code, direction), members in sorted(groups.items()):
            members.sort(key=lambda row: float(row.get("Sequence") or 0))
            target_id = f"{mode}_{line_code}_{direction}"
            if mode == "mtr":
                keywords = MTR_ALIASES.get(line_code, [f"香港地铁{line_code}"])
            else:
                keywords = [f"香港轻铁{line_code}线", f"轻轨{line_code}线"]
            targets.append(
                {
                    "target_id": target_id,
                    "mode": mode,
                    "official_route_id": line_code,
                    "official_route_seq": direction,
                    "line_code": line_code,
                    "company_code": "MTR",
                    "direction": direction,
                    "origin_name_zh": members[0].get("Chinese Name", ""),
                    "destination_name_zh": members[-1].get("Chinese Name", ""),
                    "origin_name_en": members[0].get("English Name", ""),
                    "destination_name_en": members[-1].get("English Name", ""),
                    "origin_lon_wgs84": None,
                    "origin_lat_wgs84": None,
                    "destination_lon_wgs84": None,
                    "destination_lat_wgs84": None,
                    "official_stop_count": len(members),
                    "official_station_names_zh": "|".join(
                        str(member.get("Chinese Name") or "") for member in members
                    ),
                    "query_keywords": "|".join(dict.fromkeys(keywords)),
                }
            )
            for rank, keyword in enumerate(dict.fromkeys(keywords), start=1):
                query_rows.append(
                    {"target_id": target_id, "mode": mode, "query_rank": rank, "keyword": keyword}
                )

    targets.sort(key=lambda row: (row["mode"], row["line_code"], row["direction"]))
    query_rows.sort(key=lambda row: (row["mode"], row["target_id"], row["query_rank"]))
    return targets, query_rows


class AMapClient:
    def __init__(self, key: str, timeout: float, retries: int, sleep_seconds: float) -> None:
        self.key = key
        self.timeout = timeout
        self.retries = retries
        self.sleep_seconds = sleep_seconds
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "matsim-hong-kong-amap-transit/1.0"})

    def fetch(self, city: str, keyword: str, page: int, offset: int) -> dict[str, Any]:
        params = {
            "key": self.key,
            "city": city,
            "keywords": keyword,
            "page": page,
            "offset": offset,
            "extensions": "all",
            "output": "json",
        }
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(AMAP_LINE_NAME_URL, params=params, timeout=self.timeout)
                response.raise_for_status()
                payload = response.json()
                if str(payload.get("status")) == "1":
                    time.sleep(self.sleep_seconds)
                    return payload
                info = str(payload.get("info") or "")
                if info in {
                    "CUQPS_HAS_EXCEEDED_THE_LIMIT",
                    "USER_DAILY_QUERY_OVER_LIMIT",
                    "USER_OVER_QUOTA",
                    "SERVICE_NOT_AVAILABLE",
                }:
                    time.sleep(min(2 ** (attempt + 1), 20))
                    continue
                return payload
            except requests.RequestException as exc:
                last_error = exc
                time.sleep(min(2 ** (attempt + 1), 20))
        return {
            "status": "0",
            "info": f"REQUEST_FAILED:{type(last_error).__name__ if last_error else 'unknown'}",
            "infocode": "",
        }


def collect_responses(
    client: AMapClient,
    query_rows: list[dict[str, Any]],
    output_root: Path,
    city: str,
    pages: int,
    offset: int,
    refresh: bool,
    max_keywords: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    unique_keywords = list(dict.fromkeys(row["keyword"] for row in query_rows))
    if max_keywords > 0:
        unique_keywords = unique_keywords[:max_keywords]
    responses: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    cache_dir = output_root / "raw/by_keyword"
    cache_dir.mkdir(parents=True, exist_ok=True)
    for keyword_index, keyword in enumerate(unique_keywords, start=1):
        for page in range(1, pages + 1):
            cache_path = cache_dir / f"{stable_hash(keyword)}_page_{page}.json"
            if cache_path.exists() and not refresh:
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
                source = "cache"
            else:
                payload = client.fetch(city, keyword, page, offset)
                write_json(cache_path, payload)
                source = "api"
            responses.append(
                {"keyword": keyword, "page": page, "source": source, "response": payload}
            )
            if str(payload.get("status")) != "1":
                errors.append(
                    {
                        "keyword": keyword,
                        "page": page,
                        "info": payload.get("info"),
                        "infocode": payload.get("infocode"),
                    }
                )
                break
            count = int(payload.get("count") or 0)
            if count <= page * offset:
                break
        if keyword_index % 20 == 0 or keyword_index == len(unique_keywords):
            print(f"AMap keywords: {keyword_index}/{len(unique_keywords)}", flush=True)
    return responses, errors


def line_mode(line: dict[str, Any]) -> str:
    text = f"{line.get('type', '')} {line.get('name', '')}".lower()
    if any(hint in text for hint in MODE_HINTS["lrt"]):
        return "lrt"
    if any(hint in text for hint in MODE_HINTS["mtr"]):
        return "mtr"
    if "小巴" in text or "minibus" in text:
        return "gmb"
    return "bus"


def extract_unique_lines(
    responses: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
    by_id: dict[str, dict[str, Any]] = {}
    keyword_lines: dict[str, set[str]] = defaultdict(set)
    for record in responses:
        keyword = record["keyword"]
        for line in as_list(record["response"].get("buslines")):
            if not isinstance(line, dict):
                continue
            line_id = str(line.get("id") or stable_hash(json.dumps(line, sort_keys=True, ensure_ascii=False)))
            by_id.setdefault(line_id, line)
            keyword_lines[keyword].add(line_id)
    return list(by_id.values()), keyword_lines


def target_station_set(target: dict[str, Any]) -> set[str]:
    return {
        normalize_name(name)
        for name in str(target.get("official_station_names_zh") or "").split("|")
        if normalize_name(name)
    }


def candidate_station_set(line: dict[str, Any]) -> set[str]:
    return {
        normalize_name(stop.get("name"))
        for stop in as_list(line.get("busstops"))
        if isinstance(stop, dict) and normalize_name(stop.get("name"))
    }


def score_candidate(
    target: dict[str, Any],
    line: dict[str, Any],
    came_from_target_query: bool,
) -> dict[str, Any]:
    score = 20.0 if came_from_target_query else 0.0
    target_mode = target["mode"]
    candidate_mode = line_mode(line)
    mode_compatible = candidate_mode == target_mode or (
        target_mode in {"bus", "gmb"} and candidate_mode in {"bus", "gmb"}
    )
    if mode_compatible:
        score += 15.0
    else:
        score -= 25.0

    target_names = [normalize_name(target.get("line_code"))]
    if target_mode == "mtr":
        target_names.extend(normalize_name(alias) for alias in MTR_ALIASES.get(target["line_code"], []))
    candidate_name = normalize_name(line.get("name"))
    target_names = [name for name in target_names if name]
    name_exact = candidate_name in target_names
    name_contains = any(name in candidate_name or candidate_name in name for name in target_names)
    if name_exact:
        score += 35.0
    elif name_contains:
        score += 25.0

    official_stations = target_station_set(target)
    amap_stations = candidate_station_set(line)
    station_overlap = (
        len(official_stations & amap_stations) / len(official_stations)
        if official_stations
        else 0.0
    )
    score += station_overlap * 30.0
    official_count = int(target.get("official_stop_count") or 0)
    candidate_count = len(as_list(line.get("busstops")))
    count_similarity = (
        1.0 - min(abs(official_count - candidate_count) / max(official_count, 1), 1.0)
        if official_count and candidate_count
        else 0.0
    )
    score += count_similarity * 10.0

    endpoint_distance = None
    orientation = "unknown"
    stops = [stop for stop in as_list(line.get("busstops")) if isinstance(stop, dict)]
    origin = (target.get("origin_lon_wgs84"), target.get("origin_lat_wgs84"))
    destination = (
        target.get("destination_lon_wgs84"),
        target.get("destination_lat_wgs84"),
    )
    if stops and all(value not in (None, "") for value in (*origin, *destination)):
        start_gcj = parse_lonlat(stops[0].get("location"))
        end_gcj = parse_lonlat(stops[-1].get("location"))
        if None not in (*start_gcj, *end_gcj):
            start = gcj02_to_wgs84(float(start_gcj[0]), float(start_gcj[1]))
            end = gcj02_to_wgs84(float(end_gcj[0]), float(end_gcj[1]))
            origin_pair = (float(origin[0]), float(origin[1]))
            destination_pair = (float(destination[0]), float(destination[1]))
            direct = (haversine_m(origin_pair, start) + haversine_m(destination_pair, end)) / 2
            reverse = (haversine_m(origin_pair, end) + haversine_m(destination_pair, start)) / 2
            endpoint_distance = min(direct, reverse)
            orientation = "direct" if direct <= reverse else "reverse"
            if endpoint_distance <= 100:
                score += 25
            elif endpoint_distance <= 500:
                score += 20
            elif endpoint_distance <= 1500:
                score += 10
            if orientation == "reverse":
                score -= 5

    return {
        "score": round(score, 6),
        "candidate_mode": candidate_mode,
        "mode_compatible": mode_compatible,
        "name_exact": name_exact,
        "name_contains": name_contains,
        "station_overlap": round(station_overlap, 6),
        "stop_count_similarity": round(count_similarity, 6),
        "endpoint_mean_distance_m": (
            round(endpoint_distance, 3) if endpoint_distance is not None else None
        ),
        "orientation": orientation,
    }


def match_targets(
    targets: list[dict[str, Any]],
    query_rows: list[dict[str, Any]],
    lines: list[dict[str, Any]],
    keyword_lines: dict[str, set[str]],
    accept_score: float,
) -> list[dict[str, Any]]:
    line_by_id = {
        str(line.get("id") or stable_hash(json.dumps(line, sort_keys=True, ensure_ascii=False))): line
        for line in lines
    }
    target_keywords: dict[str, list[str]] = defaultdict(list)
    for row in query_rows:
        target_keywords[row["target_id"]].append(row["keyword"])
    matches: list[dict[str, Any]] = []
    for target in targets:
        candidate_ids: set[str] = set()
        for keyword in target_keywords[target["target_id"]]:
            candidate_ids.update(keyword_lines.get(keyword, set()))
        scored = []
        for candidate_id in candidate_ids:
            line = line_by_id[candidate_id]
            metrics = score_candidate(target, line, came_from_target_query=True)
            scored.append((metrics["score"], candidate_id, line, metrics))
        scored.sort(key=lambda item: (-item[0], item[1]))
        if scored:
            _, candidate_id, line, metrics = scored[0]
            accepted = metrics["score"] >= accept_score and metrics["mode_compatible"]
            matches.append(
                {
                    "target_id": target["target_id"],
                    "mode": target["mode"],
                    "official_route_id": target["official_route_id"],
                    "official_route_seq": target["official_route_seq"],
                    "line_code": target["line_code"],
                    "amap_line_id": candidate_id,
                    "amap_line_name": line.get("name"),
                    "amap_line_type": line.get("type"),
                    "match_score": metrics["score"],
                    "accepted": accepted,
                    "candidate_count": len(scored),
                    **{key: value for key, value in metrics.items() if key != "score"},
                }
            )
        else:
            matches.append(
                {
                    "target_id": target["target_id"],
                    "mode": target["mode"],
                    "official_route_id": target["official_route_id"],
                    "official_route_seq": target["official_route_seq"],
                    "line_code": target["line_code"],
                    "amap_line_id": "",
                    "amap_line_name": "",
                    "amap_line_type": "",
                    "match_score": 0.0,
                    "accepted": False,
                    "candidate_count": 0,
                    "candidate_mode": "",
                    "mode_compatible": False,
                    "name_exact": False,
                    "name_contains": False,
                    "station_overlap": 0.0,
                    "stop_count_similarity": 0.0,
                    "endpoint_mean_distance_m": None,
                    "orientation": "unknown",
                }
            )
    return matches


def decode_timedesc(value: Any) -> dict[str, Any] | None:
    if not value or value in ([], {}):
        return None
    try:
        parsed = json.loads(unquote(str(value)))
        if isinstance(parsed, str):
            parsed = json.loads(parsed)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


def headway_minutes(value: Any) -> float | None:
    if not value:
        return None
    parts = str(value).split(":")
    try:
        values = [float(part) for part in parts]
    except ValueError:
        return None
    if len(values) == 3:
        return values[0] * 60 + values[1] + values[2] / 60
    if len(values) == 2:
        return values[0] * 60 + values[1]
    return None


def normalize_outputs(
    lines: list[dict[str, Any]], output_root: Path
) -> dict[str, int]:
    line_rows: list[dict[str, Any]] = []
    stop_rows: list[dict[str, Any]] = []
    station_rows: dict[str, dict[str, Any]] = {}
    frequency_rows: list[dict[str, Any]] = []
    gcj_features: list[dict[str, Any]] = []
    wgs_features: list[dict[str, Any]] = []
    for line in lines:
        line_id = str(line.get("id") or stable_hash(str(line.get("name"))))
        stops = [stop for stop in as_list(line.get("busstops")) if isinstance(stop, dict)]
        coordinates_gcj = parse_polyline(line.get("polyline"))
        coordinates_wgs = [gcj02_to_wgs84(lon, lat) for lon, lat in coordinates_gcj]
        line_rows.append(
            {
                "amap_line_id": line_id,
                "mode": line_mode(line),
                "line_name": line.get("name"),
                "line_type": line.get("type"),
                "company": line.get("company"),
                "start_stop": line.get("start_stop"),
                "end_stop": line.get("end_stop"),
                "start_time": line.get("start_time"),
                "end_time": line.get("end_time"),
                "status": line.get("status"),
                "reverse_line_id": line.get("direc"),
                "distance_km": line.get("distance"),
                "basic_price_cny": line.get("basic_price"),
                "total_price_cny": line.get("total_price"),
                "loop": line.get("loop"),
                "stop_count": len(stops),
                "polyline_vertex_count": len(coordinates_gcj),
                "has_polyline": len(coordinates_gcj) >= 2,
                "timedesc_parseable": decode_timedesc(line.get("timedesc")) is not None,
            }
        )
        for index, stop in enumerate(stops, start=1):
            lon_gcj, lat_gcj = parse_lonlat(stop.get("location"))
            lon_wgs = lat_wgs = None
            if lon_gcj is not None and lat_gcj is not None:
                lon_wgs, lat_wgs = gcj02_to_wgs84(lon_gcj, lat_gcj)
            stop_id = str(stop.get("id") or stable_hash(f"{stop.get('name')}|{lon_gcj}|{lat_gcj}"))
            stop_rows.append(
                {
                    "amap_line_id": line_id,
                    "line_name": line.get("name"),
                    "mode": line_mode(line),
                    "sequence": int(stop.get("sequence") or index),
                    "amap_stop_id": stop_id,
                    "station_name": stop.get("name"),
                    "lon_gcj02": lon_gcj,
                    "lat_gcj02": lat_gcj,
                    "lon_wgs84": lon_wgs,
                    "lat_wgs84": lat_wgs,
                }
            )
            station = station_rows.setdefault(
                stop_id,
                {
                    "amap_stop_id": stop_id,
                    "station_name": stop.get("name"),
                    "lon_gcj02": lon_gcj,
                    "lat_gcj02": lat_gcj,
                    "lon_wgs84": lon_wgs,
                    "lat_wgs84": lat_wgs,
                    "line_ids": set(),
                    "modes": set(),
                },
            )
            station["line_ids"].add(line_id)
            station["modes"].add(line_mode(line))

        timedesc = decode_timedesc(line.get("timedesc"))
        if timedesc:
            for group in timedesc.get("rule_group") or []:
                date = group.get("date") or {}
                for period in group.get("time_group") or []:
                    frequency_rows.append(
                        {
                            "amap_line_id": line_id,
                            "line_name": line.get("name"),
                            "day_type": "|".join(map(str, date.get("day_type") or [])),
                            "day_week": "|".join(map(str, date.get("day_week") or [])),
                            "period_start": period.get("start_time"),
                            "period_end": period.get("end_time"),
                            "interval_time": period.get("interval_time"),
                            "headway_minutes": headway_minutes(period.get("interval_time")),
                            "remark": group.get("remark"),
                            "all_remark": timedesc.get("allRemark"),
                        }
                    )
        if len(coordinates_gcj) >= 2:
            properties = {
                "amap_line_id": line_id,
                "line_name": line.get("name"),
                "mode": line_mode(line),
                "line_type": line.get("type"),
                "company": line.get("company"),
            }
            gcj_features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": coordinates_gcj},
                    "properties": properties,
                }
            )
            wgs_features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": coordinates_wgs},
                    "properties": properties,
                }
            )

    station_output = []
    for station in station_rows.values():
        station_output.append(
            {
                **{key: value for key, value in station.items() if key not in {"line_ids", "modes"}},
                "line_ids": "|".join(sorted(station["line_ids"])),
                "modes": "|".join(sorted(station["modes"])),
            }
        )
    write_csv(output_root / "normalized/amap_lines.csv", line_rows)
    write_csv(output_root / "normalized/amap_stops_by_line.csv", stop_rows)
    write_csv(output_root / "normalized/amap_stations.csv", station_output)
    write_csv(output_root / "normalized/amap_service_frequency.csv", frequency_rows)
    write_json(
        output_root / "geometry/amap_line_trajectories_gcj02.geojson",
        {"type": "FeatureCollection", "features": gcj_features},
    )
    write_json(
        output_root / "geometry/amap_line_trajectories_wgs84.geojson",
        {"type": "FeatureCollection", "features": wgs_features},
    )
    return {
        "amap_line_records": len(line_rows),
        "amap_stop_occurrences": len(stop_rows),
        "amap_unique_stations": len(station_output),
        "amap_trajectory_records": len(wgs_features),
        "amap_headway_periods": len(frequency_rows),
    }


def write_matched_geometry(
    targets: list[dict[str, Any]],
    matches: list[dict[str, Any]],
    lines: list[dict[str, Any]],
    output_root: Path,
) -> int:
    target_by_id = {target["target_id"]: target for target in targets}
    line_by_id = {str(line.get("id")): line for line in lines}
    features = []
    for match in matches:
        if not match["accepted"] or not match["amap_line_id"]:
            continue
        line = line_by_id.get(str(match["amap_line_id"]))
        if not line:
            continue
        coordinates = [gcj02_to_wgs84(lon, lat) for lon, lat in parse_polyline(line.get("polyline"))]
        if len(coordinates) < 2:
            continue
        target = target_by_id[match["target_id"]]
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coordinates},
                "properties": {
                    "target_id": match["target_id"],
                    "mode": match["mode"],
                    "official_route_id": match["official_route_id"],
                    "official_route_seq": match["official_route_seq"],
                    "line_code": match["line_code"],
                    "amap_line_id": match["amap_line_id"],
                    "amap_line_name": match["amap_line_name"],
                    "match_score": match["match_score"],
                    "station_overlap": match["station_overlap"],
                    "endpoint_mean_distance_m": match["endpoint_mean_distance_m"],
                    "coordinate_source": "AMap GCJ-02 converted to WGS84",
                    "official_origin": target["origin_name_zh"],
                    "official_destination": target["destination_name_zh"],
                },
            }
        )
    write_json(
        output_root / "geometry/amap_official_target_matches_wgs84.geojson",
        {"type": "FeatureCollection", "features": features},
    )
    return len(features)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(output_root: Path) -> None:
    rows = []
    manifest_path = output_root / "metadata/amap_download_manifest.csv"
    for path in sorted(output_root.rglob("*")):
        if not path.is_file() or path == manifest_path:
            continue
        rows.append(
            {
                "relative_path": path.relative_to(output_root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    write_csv(manifest_path, rows, ["relative_path", "size_bytes", "sha256"])


def target_fields() -> list[str]:
    return [
        "target_id",
        "mode",
        "official_route_id",
        "official_route_seq",
        "line_code",
        "company_code",
        "direction",
        "origin_name_zh",
        "destination_name_zh",
        "origin_name_en",
        "destination_name_en",
        "origin_lon_wgs84",
        "origin_lat_wgs84",
        "destination_lon_wgs84",
        "destination_lat_wgs84",
        "official_stop_count",
        "official_station_names_zh",
        "query_keywords",
    ]


def main() -> None:
    args = parse_args()
    data_root = args.data_root.resolve()
    output_root = args.output if args.output.is_absolute() else data_root / args.output
    output_root = output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    targets, query_rows = build_official_targets(data_root)
    write_csv(output_root / "targets/official_missing_targets.csv", targets, target_fields())
    write_csv(
        output_root / "targets/amap_query_targets.csv",
        query_rows,
        ["target_id", "mode", "query_rank", "keyword"],
    )
    unique_keywords = list(dict.fromkeys(row["keyword"] for row in query_rows))
    target_counts = Counter(target["mode"] for target in targets)
    preparation_summary = {
        "generated_at_utc": utc_now(),
        "status": "prepared_only" if args.prepare_only else "collecting",
        "city": args.city,
        "target_counts": dict(sorted(target_counts.items())),
        "target_count": len(targets),
        "query_row_count": len(query_rows),
        "unique_keyword_count": len(unique_keywords),
        "api_key_written_to_outputs": False,
        "coordinate_workflow": "AMap GCJ-02 -> iterative WGS84",
    }
    write_json(output_root / "metadata/amap_preparation_summary.json", preparation_summary)

    if args.prepare_only:
        write_manifest(output_root)
        print(json.dumps(preparation_summary, ensure_ascii=False, indent=2))
        return
    if not args.key:
        print(
            "Missing AMap Web Service key. Set AMAP_WEB_KEY, AMAP_KEY, or AMAP_API_KEY, "
            "or pass --key. Targets were prepared; no API request was made.",
            file=sys.stderr,
        )
        write_manifest(output_root)
        raise SystemExit(2)

    client = AMapClient(args.key, args.timeout, args.max_retries, args.sleep)
    responses, errors = collect_responses(
        client,
        query_rows,
        output_root,
        args.city,
        args.pages,
        args.offset,
        args.refresh,
        args.max_keywords,
    )
    write_json(output_root / "raw/amap_busline_response_index.json", responses)
    write_json(output_root / "metadata/amap_api_errors.json", errors)
    lines, keyword_lines = extract_unique_lines(responses)
    normalized_counts = normalize_outputs(lines, output_root)
    matches = match_targets(targets, query_rows, lines, keyword_lines, args.accept_score)
    write_csv(output_root / "matches/official_amap_route_matches.csv", matches)
    unmatched = [match for match in matches if not match["accepted"]]
    write_csv(output_root / "matches/unmatched_or_low_confidence_targets.csv", unmatched)
    matched_geometry_count = write_matched_geometry(targets, matches, lines, output_root)

    accepted_by_mode = Counter(
        match["mode"] for match in matches if match["accepted"]
    )
    final_summary = {
        **preparation_summary,
        "generated_at_utc": utc_now(),
        "status": "complete" if not errors else "complete_with_api_errors",
        "pages": args.pages,
        "offset": args.offset,
        "response_records": len(responses),
        "api_error_count": len(errors),
        **normalized_counts,
        "accepted_match_count": sum(bool(match["accepted"]) for match in matches),
        "accepted_matches_by_mode": dict(sorted(accepted_by_mode.items())),
        "unmatched_or_low_confidence_count": len(unmatched),
        "matched_geometry_count": matched_geometry_count,
        "accept_score": args.accept_score,
        "limitations": [
            "AMap is a supplementary source and is not authoritative for Hong Kong service completeness.",
            "AMap Web Service output coordinates are GCJ-02 and are converted to WGS84 here.",
            "Only accepted scored matches enter the official-target matched geometry layer.",
            "A missing or unparseable timedesc is not a complete timetable.",
        ],
    }
    write_json(output_root / "metadata/amap_fetch_summary.json", final_summary)
    write_manifest(output_root)
    print(json.dumps(final_summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
