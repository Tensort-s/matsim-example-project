#!/usr/bin/env python3
"""Discover remaining Hong Kong AMap transit lines from known stop locations.

Only official stops belonging to currently unmatched routes are queried. The
pipeline uses AMap place/around (with place/text fallback), bus/stopid, and
bus/lineid. It deliberately does not perform a citywide polygon search.

Successful responses are cached independently by endpoint. Daily quota errors
are not cached, so a later rerun resumes from the first missing request. The
AMap Web Service key is never written to outputs, caches, manifests, or logs.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import json
import math
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from shapely.geometry import LineString, mapping

import fetch_hong_kong_transit_from_amap as shared


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_ROOT = ROOT / "data"
DEFAULT_KEYWORD_OUTPUT = Path("transit/hongkong/AMap_Supplements")
DEFAULT_OUTPUT = Path("transit/hongkong/AMap_Targeted_StopID_Supplements")
DEFAULT_OFFICIAL_STOPS = Path(
    "transit/hongkong/API_Supplements/static/"
    "routes_fares_route_stop_points/bus_route_stop_points.json"
)

AMAP_PLACE_AROUND_URL = "https://restapi.amap.com/v3/place/around"
AMAP_PLACE_TEXT_URL = "https://restapi.amap.com/v3/place/text"
AMAP_STOP_ID_URL = "https://restapi.amap.com/v3/bus/stopid"
AMAP_LINE_ID_URL = "https://restapi.amap.com/v3/bus/lineid"
BUS_STOP_TYPE = "150700"

DAILY_LIMIT_INFOS = {"USER_DAILY_QUERY_OVER_LIMIT", "USER_OVER_QUOTA"}
RETRYABLE_INFOS = {
    "CGQPS_HAS_EXCEEDED_THE_LIMIT",
    "CUQPS_HAS_EXCEEDED_THE_LIMIT",
    "SERVICE_NOT_AVAILABLE",
}
CROSS_BORDER_HINTS = (
    "皇岗",
    "皇崗",
    "落马洲",
    "落馬洲",
    "跨境",
    "huanggang",
    "lokmachau",
    "crossborder",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", default=shared.default_amap_key(), help="AMap Web Service key.")
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--keyword-output", type=Path, default=DEFAULT_KEYWORD_OUTPUT)
    parser.add_argument("--official-stops", type=Path, default=DEFAULT_OFFICIAL_STOPS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--city", default="香港")
    parser.add_argument("--radius-m", type=float, default=300.0)
    parser.add_argument("--near-distance-m", type=float, default=80.0)
    parser.add_argument("--name-similarity", type=float, default=0.45)
    parser.add_argument("--max-candidates-per-stop", type=int, default=3)
    parser.add_argument("--place-pages", type=int, default=2)
    parser.add_argument("--place-offset", type=int, default=25)
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--max-retries", type=int, default=4)
    parser.add_argument("--accept-score", type=float, default=55.0)
    parser.add_argument("--max-official-stops", type=int, default=0, help="Debug cap; 0 means all.")
    parser.add_argument("--max-stop-ids", type=int, default=0, help="Debug cap; 0 means all.")
    parser.add_argument("--max-line-ids", type=int, default=0, help="Debug cap; 0 means all.")
    parser.add_argument(
        "--stage",
        choices=("all", "prepare", "place", "stopid", "lineid", "match"),
        default="all",
    )
    parser.add_argument("--refresh", action="store_true", help="Ignore successful cached API responses.")
    return parser.parse_args()


def resolve_under(data_root: Path, value: Path) -> Path:
    return value.resolve() if value.is_absolute() else (data_root / value).resolve()


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def stable_id(*parts: Any, length: int = 20) -> str:
    text = "|".join("" if value is None else str(value) for value in parts)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def bool_value(value: Any) -> bool:
    return value is True or str(value).strip().lower() == "true"


class AMapClient:
    def __init__(self, key: str, timeout: float, max_retries: int, sleep_seconds: float) -> None:
        self.key = key
        self.timeout = timeout
        self.max_retries = max_retries
        self.sleep_seconds = sleep_seconds
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "matsim-hong-kong-targeted-stopid/1.0"})

    def request(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        request_params = {**params, "key": self.key, "output": "json"}
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(url, params=request_params, timeout=self.timeout)
                response.raise_for_status()
                payload = response.json()
                info = str(payload.get("info") or "")
                if str(payload.get("status")) == "1" or info in DAILY_LIMIT_INFOS:
                    time.sleep(self.sleep_seconds)
                    return payload
                if info in RETRYABLE_INFOS:
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


def cached_request(
    client: AMapClient,
    url: str,
    params: dict[str, Any],
    cache_path: Path,
    refresh: bool,
) -> tuple[dict[str, Any], str]:
    if cache_path.exists() and not refresh:
        return read_json(cache_path), "cache"
    payload = client.request(url, params)
    if str(payload.get("status")) == "1":
        write_json(cache_path, payload)
    return payload, "api"


def load_targets(keyword_output: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    targets = read_csv(keyword_output / "targets/official_missing_targets.csv")
    matches = read_csv(keyword_output / "matches/official_amap_route_matches.csv")
    accepted_ids = {row["target_id"] for row in matches if bool_value(row.get("accepted"))}
    unmatched = [target for target in targets if target["target_id"] not in accepted_ids]
    return targets, unmatched


def build_official_stops(
    unmatched_targets: list[dict[str, str]], official_stops_path: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    target_by_route = {
        (target["official_route_id"], target["official_route_seq"]): target
        for target in unmatched_targets
        if target["mode"] == "bus"
    }
    payload = read_json(official_stops_path)
    occurrences = []
    for feature in payload.get("features") or []:
        props = feature.get("properties") or {}
        key = (str(props.get("routeId")), str(props.get("routeSeq")))
        target = target_by_route.get(key)
        coordinates = (feature.get("geometry") or {}).get("coordinates") or []
        if target is None or len(coordinates) < 2:
            continue
        name_zh = str(props.get("stopNameC") or "").strip()
        name_en = str(props.get("stopNameE") or "").strip()
        lon = round(float(coordinates[0]), 6)
        lat = round(float(coordinates[1]), 6)
        unique_stop_id = "official_stop_" + stable_id(name_zh, lon, lat, length=16)
        occurrences.append(
            {
                "target_id": target["target_id"],
                "company_code": target["company_code"],
                "line_code": target["line_code"],
                "official_route_id": target["official_route_id"],
                "official_route_seq": target["official_route_seq"],
                "stop_sequence": int(props.get("stopSeq") or 0),
                "stop_name_zh": name_zh,
                "stop_name_en": name_en,
                "lon_wgs84": lon,
                "lat_wgs84": lat,
                "unique_stop_id": unique_stop_id,
            }
        )
    occurrences.sort(
        key=lambda row: (row["company_code"], row["line_code"], row["target_id"], row["stop_sequence"])
    )

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in occurrences:
        grouped[row["unique_stop_id"]].append(row)
    unique_stops = []
    for unique_stop_id, rows in sorted(grouped.items()):
        first = rows[0]
        unique_stops.append(
            {
                "unique_stop_id": unique_stop_id,
                "stop_name_zh": first["stop_name_zh"],
                "stop_name_en": first["stop_name_en"],
                "lon_wgs84": first["lon_wgs84"],
                "lat_wgs84": first["lat_wgs84"],
                "target_ids": "|".join(sorted({row["target_id"] for row in rows})),
                "company_codes": "|".join(sorted({row["company_code"] for row in rows})),
                "line_codes": "|".join(sorted({row["line_code"] for row in rows})),
                "official_route_ids": "|".join(sorted({row["official_route_id"] for row in rows})),
                "occurrence_count": len(rows),
            }
        )

    expected = {
        "unmatched_targets": 28,
        "stop_occurrences": 169,
        "unique_stops": 55,
        "unique_names": 52,
    }
    actual = {
        "unmatched_targets": len(unmatched_targets),
        "stop_occurrences": len(occurrences),
        "unique_stops": len(unique_stops),
        "unique_names": len({row["stop_name_zh"] for row in unique_stops}),
    }
    if actual != expected:
        raise RuntimeError(f"Official targeted-stop counts changed: expected {expected}, got {actual}")
    return occurrences, unique_stops


def name_similarity(a: Any, b: Any) -> float:
    left = shared.normalize_name(a)
    right = shared.normalize_name(b)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    ratio = difflib.SequenceMatcher(None, left, right).ratio()
    if left in right or right in left:
        ratio = max(ratio, min(len(left), len(right)) / max(len(left), len(right)), 0.7)
    left_chars = set(left)
    right_chars = set(right)
    overlap = len(left_chars & right_chars) / max(len(left_chars | right_chars), 1)
    return round(max(ratio, overlap), 6)


def parse_place_candidate(
    poi: dict[str, Any], official_stop: dict[str, Any], source: str
) -> dict[str, Any] | None:
    lon_gcj, lat_gcj = shared.parse_lonlat(poi.get("location"))
    if lon_gcj is None or lat_gcj is None or not poi.get("id"):
        return None
    lon_wgs, lat_wgs = shared.gcj02_to_wgs84(lon_gcj, lat_gcj)
    official_point = (float(official_stop["lon_wgs84"]), float(official_stop["lat_wgs84"]))
    distance = shared.haversine_m(official_point, (lon_wgs, lat_wgs))
    similarity_zh = name_similarity(official_stop["stop_name_zh"], poi.get("name"))
    similarity_en = name_similarity(official_stop["stop_name_en"], poi.get("name"))
    return {
        "unique_stop_id": official_stop["unique_stop_id"],
        "official_stop_name_zh": official_stop["stop_name_zh"],
        "official_stop_name_en": official_stop["stop_name_en"],
        "official_lon_wgs84": official_stop["lon_wgs84"],
        "official_lat_wgs84": official_stop["lat_wgs84"],
        "target_ids": official_stop["target_ids"],
        "line_codes": official_stop["line_codes"],
        "amap_poi_id": str(poi.get("id")),
        "amap_poi_name": poi.get("name"),
        "amap_type": poi.get("type"),
        "amap_typecode": poi.get("typecode"),
        "amap_address": poi.get("address") if isinstance(poi.get("address"), str) else "",
        "amap_district": poi.get("adname"),
        "lon_gcj02": lon_gcj,
        "lat_gcj02": lat_gcj,
        "lon_wgs84": lon_wgs,
        "lat_wgs84": lat_wgs,
        "distance_m": round(distance, 3),
        "name_similarity_zh": similarity_zh,
        "name_similarity_en": similarity_en,
        "name_similarity_max": max(similarity_zh, similarity_en),
        "discovery_source": source,
    }


def reliable_candidate(row: dict[str, Any], args: argparse.Namespace) -> bool:
    distance = float(row["distance_m"])
    similarity = float(row["name_similarity_max"])
    return distance <= args.near_distance_m or (
        distance <= args.radius_m and similarity >= args.name_similarity
    )


def fallback_city(stop: dict[str, Any], default_city: str) -> str:
    lon = float(stop["lon_wgs84"])
    lat = float(stop["lat_wgs84"])
    return "深圳" if lon <= 114.09 and lat >= 22.49 else default_city


def request_place_pages(
    client: AMapClient,
    url: str,
    params: dict[str, Any],
    cache_prefix: Path,
    pages: int,
    offset: int,
    refresh: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool, int, int]:
    pois = []
    errors = []
    daily_limit = False
    new_requests = cache_hits = 0
    for page in range(1, pages + 1):
        payload, source = cached_request(
            client,
            url,
            {**params, "page": page, "offset": offset, "extensions": "base"},
            cache_prefix.parent / f"{cache_prefix.name}_page_{page}.json",
            refresh,
        )
        new_requests += source == "api"
        cache_hits += source == "cache"
        info = str(payload.get("info") or "")
        if info in DAILY_LIMIT_INFOS:
            daily_limit = True
            errors.append({"page": page, "info": info, "infocode": payload.get("infocode")})
            break
        if str(payload.get("status")) != "1":
            errors.append({"page": page, "info": info, "infocode": payload.get("infocode")})
            break
        page_pois = [item for item in shared.as_list(payload.get("pois")) if isinstance(item, dict)]
        pois.extend(page_pois)
        if len(page_pois) < offset:
            break
    return pois, errors, daily_limit, int(new_requests), int(cache_hits)


def run_place_stage(
    args: argparse.Namespace,
    client: AMapClient,
    unique_stops: list[dict[str, Any]],
    output_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if args.max_official_stops:
        unique_stops = unique_stops[: args.max_official_stops]
    all_candidates = []
    selected = []
    errors = []
    new_requests = cache_hits = fallback_stop_count = 0
    stopped_by_daily_limit = False

    for index, stop in enumerate(unique_stops, start=1):
        lon_gcj, lat_gcj = shared.wgs84_to_gcj02(
            float(stop["lon_wgs84"]), float(stop["lat_wgs84"])
        )
        around_pois, around_errors, daily_limit, new, cached = request_place_pages(
            client,
            AMAP_PLACE_AROUND_URL,
            {
                "location": f"{lon_gcj:.6f},{lat_gcj:.6f}",
                "radius": int(args.radius_m),
                "types": BUS_STOP_TYPE,
                "sortrule": "distance",
            },
            output_root / "raw/place_around" / stop["unique_stop_id"],
            args.place_pages,
            args.place_offset,
            args.refresh,
        )
        new_requests += new
        cache_hits += cached
        errors.extend({"stage": "place_around", "unique_stop_id": stop["unique_stop_id"], **row} for row in around_errors)
        if daily_limit:
            stopped_by_daily_limit = True
            break
        candidates = [
            row
            for poi in around_pois
            if (row := parse_place_candidate(poi, stop, "place_around")) is not None
        ]
        reliable = [row for row in candidates if reliable_candidate(row, args)]

        if not reliable:
            fallback_stop_count += 1
            for language, keyword in (("zh", stop["stop_name_zh"]), ("en", stop["stop_name_en"])):
                if not keyword:
                    continue
                text_pois, text_errors, daily_limit, new, cached = request_place_pages(
                    client,
                    AMAP_PLACE_TEXT_URL,
                    {
                        "keywords": keyword,
                        "types": BUS_STOP_TYPE,
                        "city": fallback_city(stop, args.city),
                        "citylimit": "true",
                    },
                    output_root / "raw/place_text" / f"{stop['unique_stop_id']}_{language}",
                    1,
                    args.place_offset,
                    args.refresh,
                )
                new_requests += new
                cache_hits += cached
                errors.extend(
                    {"stage": "place_text", "unique_stop_id": stop["unique_stop_id"], "language": language, **row}
                    for row in text_errors
                )
                candidates.extend(
                    row
                    for poi in text_pois
                    if (row := parse_place_candidate(poi, stop, f"place_text_{language}")) is not None
                )
                if daily_limit:
                    stopped_by_daily_limit = True
                    break
                reliable = [row for row in candidates if reliable_candidate(row, args)]
                if reliable:
                    break
        by_poi: dict[str, dict[str, Any]] = {}
        for row in candidates:
            current = by_poi.get(row["amap_poi_id"])
            rank = (-float(row["name_similarity_max"]), float(row["distance_m"]))
            if current is None or rank < (
                -float(current["name_similarity_max"]), float(current["distance_m"])
            ):
                by_poi[row["amap_poi_id"]] = row
        candidate_rows = sorted(
            by_poi.values(),
            key=lambda row: (-float(row["name_similarity_max"]), float(row["distance_m"]), row["amap_poi_id"]),
        )
        for rank, row in enumerate(candidate_rows, start=1):
            row["candidate_rank"] = rank
            row["reliable"] = reliable_candidate(row, args)
            row["selected"] = row["reliable"] and sum(bool(item.get("selected")) for item in candidate_rows) < args.max_candidates_per_stop
            all_candidates.append(row)
        selected.extend(row for row in candidate_rows if row.get("selected"))
        if stopped_by_daily_limit:
            break
        if index % 10 == 0 or index == len(unique_stops):
            print(f"targeted place search: {index}/{len(unique_stops)}", flush=True)

    write_csv(output_root / "targets/amap_stop_poi_candidates.csv", all_candidates)
    write_csv(output_root / "targets/amap_selected_stop_pois.csv", selected)
    write_json(output_root / "metadata/place_api_errors.json", errors)
    summary = {
        "official_stops_requested": len({row["unique_stop_id"] for row in all_candidates})
        + sum(1 for stop in unique_stops if stop["unique_stop_id"] not in {row["unique_stop_id"] for row in all_candidates}),
        "new_requests": new_requests,
        "cache_hits": cache_hits,
        "fallback_text_stop_count": fallback_stop_count,
        "candidate_rows": len(all_candidates),
        "selected_official_to_poi_rows": len(selected),
        "unique_selected_poi_ids": len({row["amap_poi_id"] for row in selected}),
        "official_stops_without_selected_poi": len(unique_stops) - len({row["unique_stop_id"] for row in selected}),
        "stopped_by_daily_limit": stopped_by_daily_limit,
        "error_count": len(errors),
    }
    write_json(output_root / "metadata/place_stage_summary.json", summary)
    return selected, summary


def load_selected_pois(path: Path) -> list[dict[str, str]]:
    return read_csv(path) if path.exists() else []


def selected_poi_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["amap_poi_id"])].append(row)
    result = {}
    for poi_id, members in grouped.items():
        result[poi_id] = {
            "amap_poi_id": poi_id,
            "amap_poi_name": members[0].get("amap_poi_name"),
            "unique_stop_ids": "|".join(sorted({str(row["unique_stop_id"]) for row in members})),
            "target_ids": "|".join(
                sorted({value for row in members for value in str(row.get("target_ids") or "").split("|") if value})
            ),
            "min_distance_m": min(float(row["distance_m"]) for row in members),
            "max_name_similarity": max(float(row["name_similarity_max"]) for row in members),
        }
    return result


def run_stopid_stage(
    args: argparse.Namespace,
    client: AMapClient,
    selected_pois: list[dict[str, Any]],
    output_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    poi_index = selected_poi_index(selected_pois)
    poi_rows = sorted(
        poi_index.values(),
        key=lambda row: (float(row["min_distance_m"]), -float(row["max_name_similarity"]), row["amap_poi_id"]),
    )
    if args.max_stop_ids:
        poi_rows = poi_rows[: args.max_stop_ids]
    stop_to_line_rows = []
    errors = []
    new_requests = cache_hits = 0
    stopped_by_daily_limit = False

    for index, poi in enumerate(poi_rows, start=1):
        poi_id = poi["amap_poi_id"]
        payload, source = cached_request(
            client,
            AMAP_STOP_ID_URL,
            {"city": args.city, "id": poi_id},
            output_root / "raw/stopid" / f"{stable_id(poi_id)}.json",
            args.refresh,
        )
        new_requests += source == "api"
        cache_hits += source == "cache"
        info = str(payload.get("info") or "")
        if info in DAILY_LIMIT_INFOS:
            stopped_by_daily_limit = True
            errors.append({"stage": "stopid", "amap_poi_id": poi_id, "info": info})
            break
        if str(payload.get("status")) != "1":
            errors.append(
                {"stage": "stopid", "amap_poi_id": poi_id, "info": info, "infocode": payload.get("infocode")}
            )
            continue
        for returned_stop in shared.as_list(payload.get("busstops")):
            if not isinstance(returned_stop, dict):
                continue
            for line in shared.as_list(returned_stop.get("buslines")):
                if not isinstance(line, dict) or not line.get("id"):
                    continue
                stop_to_line_rows.append(
                    {
                        **poi,
                        "returned_stop_id": returned_stop.get("id"),
                        "returned_stop_name": returned_stop.get("name"),
                        "amap_line_id": str(line.get("id")),
                        "amap_line_name": line.get("name"),
                        "amap_line_type": line.get("type"),
                        "start_stop": line.get("start_stop"),
                        "end_stop": line.get("end_stop"),
                    }
                )
        if index % 25 == 0 or index == len(poi_rows):
            print(f"stopid: {index}/{len(poi_rows)}", flush=True)

    unique_rows = list(
        {
            (row["amap_poi_id"], row["amap_line_id"]): row
            for row in stop_to_line_rows
        }.values()
    )
    write_csv(output_root / "normalized/amap_stop_to_lines.csv", unique_rows)
    write_json(output_root / "metadata/stopid_api_errors.json", errors)
    summary = {
        "unique_selected_poi_ids": len(poi_rows),
        "new_requests": int(new_requests),
        "cache_hits": int(cache_hits),
        "stop_to_line_pairs": len(unique_rows),
        "unique_line_ids_discovered": len({row["amap_line_id"] for row in unique_rows}),
        "stopped_by_daily_limit": stopped_by_daily_limit,
        "error_count": len(errors),
    }
    write_json(output_root / "metadata/stopid_stage_summary.json", summary)
    return unique_rows, summary


def endpoint_name_matches(target: dict[str, str], row: dict[str, Any]) -> bool:
    endpoint_text = shared.normalize_name(f"{row.get('start_stop', '')}{row.get('end_stop', '')}")
    names = (
        target.get("origin_name_zh"),
        target.get("destination_name_zh"),
        target.get("origin_name_en"),
        target.get("destination_name_en"),
    )
    return any(
        normalized and (normalized in endpoint_text or endpoint_text in normalized)
        for name in names
        if (normalized := shared.normalize_name(name))
    )


def filter_line_ids(
    stop_to_lines: list[dict[str, Any]], unmatched_targets: list[dict[str, str]]
) -> list[dict[str, Any]]:
    target_by_id = {row["target_id"]: row for row in unmatched_targets}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in stop_to_lines:
        grouped[row["amap_line_id"]].append(row)
    audit = []
    for line_id, rows in sorted(grouped.items()):
        first = rows[0]
        linked_targets = {
            target_id
            for row in rows
            for target_id in str(row.get("target_ids") or "").split("|")
            if target_id in target_by_id
        }
        target_stops: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            for target_id in str(row.get("target_ids") or "").split("|"):
                if target_id in target_by_id:
                    target_stops[target_id].update(
                        value for value in str(row.get("unique_stop_ids") or "").split("|") if value
                    )
        line_text = f"{first.get('amap_line_name', '')} {first.get('start_stop', '')} {first.get('end_stop', '')}"
        normalized_line_name = shared.normalize_name(first.get("amap_line_name"))
        cross_border_hint = any(hint in line_text.lower().replace(" ", "") for hint in CROSS_BORDER_HINTS)
        reasons = []
        relevant_targets = set()
        for target_id in linked_targets:
            target = target_by_id[target_id]
            code = shared.normalize_name(target["line_code"])
            if code and (code in normalized_line_name or normalized_line_name in code):
                reasons.append(f"line_name:{target_id}")
                relevant_targets.add(target_id)
            if target["company_code"] == "XB" and cross_border_hint:
                reasons.append(f"cross_border_hint:{target_id}")
                relevant_targets.add(target_id)
            if endpoint_name_matches(target, first):
                reasons.append(f"endpoint_name:{target_id}")
                relevant_targets.add(target_id)
            if len(target_stops[target_id]) >= 2:
                reasons.append(f"multiple_target_stops:{target_id}")
                relevant_targets.add(target_id)
        audit.append(
            {
                "amap_line_id": line_id,
                "amap_line_name": first.get("amap_line_name"),
                "amap_line_type": first.get("amap_line_type"),
                "start_stop": first.get("start_stop"),
                "end_stop": first.get("end_stop"),
                "source_poi_ids": "|".join(sorted({row["amap_poi_id"] for row in rows})),
                "linked_target_ids": "|".join(sorted(linked_targets)),
                "relevant_target_ids": "|".join(sorted(relevant_targets)),
                "linked_official_stop_count": len(
                    {value for row in rows for value in str(row.get("unique_stop_ids") or "").split("|") if value}
                ),
                "selection_reasons": "|".join(sorted(set(reasons))),
                "selected_for_lineid": bool(reasons),
            }
        )
    return audit


def run_lineid_stage(
    args: argparse.Namespace,
    client: AMapClient,
    line_audit: list[dict[str, Any]],
    output_root: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected = [row for row in line_audit if bool_value(row.get("selected_for_lineid"))]
    if args.max_line_ids:
        selected = selected[: args.max_line_ids]
    lines_by_id: dict[str, dict[str, Any]] = {}
    errors = []
    new_requests = cache_hits = 0
    stopped_by_daily_limit = False
    for index, row in enumerate(selected, start=1):
        line_id = row["amap_line_id"]
        payload, source = cached_request(
            client,
            AMAP_LINE_ID_URL,
            {"city": args.city, "id": line_id, "extensions": "all"},
            output_root / "raw/lineid" / f"{stable_id(line_id)}.json",
            args.refresh,
        )
        new_requests += source == "api"
        cache_hits += source == "cache"
        info = str(payload.get("info") or "")
        if info in DAILY_LIMIT_INFOS:
            stopped_by_daily_limit = True
            errors.append({"stage": "lineid", "amap_line_id": line_id, "info": info})
            break
        if str(payload.get("status")) != "1":
            errors.append(
                {"stage": "lineid", "amap_line_id": line_id, "info": info, "infocode": payload.get("infocode")}
            )
            continue
        for line in shared.as_list(payload.get("buslines")):
            if isinstance(line, dict):
                returned_id = str(line.get("id") or line_id)
                lines_by_id.setdefault(returned_id, line)
        if index % 25 == 0 or index == len(selected):
            print(f"lineid: {index}/{len(selected)}", flush=True)
    lines = list(lines_by_id.values())
    normalized = shared.normalize_outputs(lines, output_root)
    write_json(output_root / "metadata/lineid_api_errors.json", errors)
    summary = {
        "discovered_line_ids": len(line_audit),
        "selected_line_ids": len(selected),
        "new_requests": int(new_requests),
        "cache_hits": int(cache_hits),
        "unique_line_records": len(lines),
        "stopped_by_daily_limit": stopped_by_daily_limit,
        "error_count": len(errors),
        **normalized,
    }
    write_json(output_root / "metadata/lineid_stage_summary.json", summary)
    return lines, summary


def load_cached_lines(output_root: Path) -> list[dict[str, Any]]:
    lines = {}
    for path in sorted((output_root / "raw/lineid").glob("*.json")):
        payload = read_json(path)
        for line in shared.as_list(payload.get("buslines")):
            if isinstance(line, dict):
                line_id = str(line.get("id") or stable_id(json.dumps(line, ensure_ascii=False, sort_keys=True)))
                lines.setdefault(line_id, line)
    return list(lines.values())


def match_remaining(
    unmatched_targets: list[dict[str, str]], lines: list[dict[str, Any]], accept_score: float
) -> list[dict[str, Any]]:
    rows = []
    for target in unmatched_targets:
        scored = []
        for line in lines:
            metrics = shared.score_candidate(target, line, came_from_target_query=False)
            endpoint_and_stations = (
                metrics["endpoint_mean_distance_m"] is not None
                and metrics["endpoint_mean_distance_m"] <= 1000
                and metrics["station_overlap"] >= 0.1
            )
            evidence = (
                metrics["name_exact"]
                or metrics["name_contains"]
                or metrics["station_overlap"] >= 0.2
                or endpoint_and_stations
            )
            scored.append((metrics["score"], str(line.get("id") or ""), line, metrics, evidence))
        scored.sort(key=lambda item: (-item[0], item[1]))
        if not scored:
            rows.append(
                {
                    "target_id": target["target_id"],
                    "mode": target["mode"],
                    "company_code": target["company_code"],
                    "line_code": target["line_code"],
                    "official_route_id": target["official_route_id"],
                    "official_route_seq": target["official_route_seq"],
                    "amap_line_id": "",
                    "amap_line_name": "",
                    "match_score": 0.0,
                    "accepted": False,
                    "candidate_count": 0,
                    "match_evidence": False,
                }
            )
            continue
        _, line_id, line, metrics, evidence = scored[0]
        accepted = bool(metrics["mode_compatible"] and evidence and metrics["score"] >= accept_score)
        rows.append(
            {
                "target_id": target["target_id"],
                "mode": target["mode"],
                "company_code": target["company_code"],
                "line_code": target["line_code"],
                "official_route_id": target["official_route_id"],
                "official_route_seq": target["official_route_seq"],
                "amap_line_id": line_id,
                "amap_line_name": line.get("name"),
                "amap_line_type": line.get("type"),
                "match_score": metrics["score"],
                "accepted": accepted,
                "candidate_count": len(scored),
                "match_evidence": evidence,
                **{key: value for key, value in metrics.items() if key != "score"},
            }
        )
    return rows


def numeric_value(value: Any, default: float = math.inf) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def audit_existing_spatial_matches(
    existing_matches: list[dict[str, str]], targets: list[dict[str, str]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    target_by_id = {target["target_id"]: target for target in targets}
    audited = []
    audit_rows = []
    for source_row in existing_matches:
        row: dict[str, Any] = {**source_row, "acquisition_method": "linename"}
        originally_accepted = bool_value(row.get("accepted"))
        endpoint_distance = numeric_value(row.get("endpoint_mean_distance_m"))
        station_overlap = numeric_value(row.get("station_overlap"), default=0.0)
        spatial_evidence = endpoint_distance <= 5000 or station_overlap >= 0.1
        target = target_by_id.get(row["target_id"], {})
        row["accepted_before_spatial_qa"] = originally_accepted
        row["spatial_qa_passed"] = not originally_accepted or spatial_evidence
        row["spatial_qa_reason"] = (
            "not_previously_accepted"
            if not originally_accepted
            else "endpoint_within_5km_or_station_overlap"
            if spatial_evidence
            else "rejected_no_station_overlap_and_endpoint_over_5km"
        )
        if originally_accepted and not spatial_evidence:
            row["accepted"] = False
        audited.append(row)
        if originally_accepted:
            audit_rows.append(
                {
                    "target_id": row["target_id"],
                    "mode": row.get("mode"),
                    "company_code": target.get("company_code"),
                    "line_code": row.get("line_code"),
                    "official_origin": target.get("origin_name_zh"),
                    "official_destination": target.get("destination_name_zh"),
                    "amap_line_name": row.get("amap_line_name"),
                    "endpoint_mean_distance_m": row.get("endpoint_mean_distance_m"),
                    "station_overlap": row.get("station_overlap"),
                    "spatial_qa_passed": spatial_evidence,
                    "spatial_qa_reason": row["spatial_qa_reason"],
                }
            )
    return audited, audit_rows


def merge_results(
    keyword_output: Path,
    output_root: Path,
    targets: list[dict[str, str]],
    targeted_matches: list[dict[str, Any]],
    lines: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, dict[str, Any]]:
    existing_matches = read_csv(keyword_output / "matches/official_amap_route_matches.csv")
    audited_existing, historical_audit = audit_existing_spatial_matches(existing_matches, targets)
    write_csv(output_root / "matches/historical_linename_spatial_qa.csv", historical_audit)
    unfiltered_combined = {
        row["target_id"]: {**row, "acquisition_method": "linename"}
        for row in existing_matches
    }
    combined = {row["target_id"]: row for row in audited_existing}
    for row in targeted_matches:
        if bool_value(row.get("accepted")):
            promoted = {
                **row,
                "acquisition_method": "targeted_stopid_lineid",
                "accepted_before_spatial_qa": False,
                "spatial_qa_passed": True,
                "spatial_qa_reason": "strict_targeted_name_station_endpoint_evidence",
            }
            unfiltered_combined[row["target_id"]] = promoted
            combined[row["target_id"]] = promoted
    unfiltered_rows = [unfiltered_combined[key] for key in sorted(unfiltered_combined)]
    combined_rows = [combined[key] for key in sorted(combined)]
    write_csv(output_root / "matches/combined_official_target_matches_unfiltered.csv", unfiltered_rows)
    write_csv(output_root / "matches/combined_official_target_matches.csv", combined_rows)

    existing_geometry_path = keyword_output / "geometry/amap_official_target_matches_wgs84.geojson"
    existing_geometry = read_json(existing_geometry_path)
    features_by_target = {
        str((feature.get("properties") or {}).get("target_id")): feature
        for feature in existing_geometry.get("features") or []
    }
    line_by_id = {str(line.get("id")): line for line in lines}
    target_by_id = {target["target_id"]: target for target in targets}
    for match in targeted_matches:
        if not bool_value(match.get("accepted")):
            continue
        line = line_by_id.get(str(match["amap_line_id"]))
        coordinates = [
            shared.gcj02_to_wgs84(lon, lat)
            for lon, lat in shared.parse_polyline(line.get("polyline") if line else None)
        ]
        if len(coordinates) < 2:
            continue
        reversed_to_official_direction = str(match.get("orientation")) == "reverse"
        if reversed_to_official_direction:
            coordinates.reverse()
        target = target_by_id[match["target_id"]]
        features_by_target[match["target_id"]] = {
            "type": "Feature",
            "geometry": mapping(LineString(coordinates)),
            "properties": {
                "target_id": match["target_id"],
                "mode": match["mode"],
                "official_route_id": match["official_route_id"],
                "official_route_seq": match["official_route_seq"],
                "line_code": match["line_code"],
                "amap_line_id": match["amap_line_id"],
                "amap_line_name": match["amap_line_name"],
                "match_score": match["match_score"],
                "station_overlap": match.get("station_overlap"),
                "endpoint_mean_distance_m": match.get("endpoint_mean_distance_m"),
                "acquisition_method": "targeted_stopid_lineid",
                "geometry_reversed_to_official_direction": reversed_to_official_direction,
                "coordinate_source": "AMap GCJ-02 converted to WGS84",
                "official_origin": target["origin_name_zh"],
                "official_destination": target["destination_name_zh"],
            },
        }
    unfiltered_features = [features_by_target[key] for key in sorted(features_by_target) if key]
    write_json(
        output_root / "geometry/amap_official_target_matches_combined_unfiltered_wgs84.geojson",
        {"type": "FeatureCollection", "features": unfiltered_features},
    )
    accepted_target_ids = {
        row["target_id"] for row in combined_rows if bool_value(row.get("accepted"))
    }
    features = [
        feature
        for feature in unfiltered_features
        if str((feature.get("properties") or {}).get("target_id")) in accepted_target_ids
    ]
    write_json(
        output_root / "geometry/amap_official_target_matches_combined_wgs84.geojson",
        {"type": "FeatureCollection", "features": features},
    )
    rejected = [row for row in historical_audit if not bool_value(row["spatial_qa_passed"])]
    qa_summary = {
        "historical_accepted_input_count": sum(bool_value(row.get("accepted")) for row in existing_matches),
        "historical_spatial_qa_rejected_count": len(rejected),
        "historical_spatial_qa_rejected_target_ids": [row["target_id"] for row in rejected],
        "historical_retained_accepted_count": sum(
            bool_value(row.get("accepted")) for row in audited_existing
        ),
        "unfiltered_combined_geometry_count": len(unfiltered_features),
    }
    return combined_rows, len(features), qa_summary


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest(output_root: Path) -> None:
    manifest_path = output_root / "metadata/amap_targeted_stopid_manifest.csv"
    rows = []
    for path in sorted(output_root.rglob("*")):
        if path.is_file() and path != manifest_path:
            rows.append(
                {
                    "relative_path": path.relative_to(output_root).as_posix(),
                    "size_bytes": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )
    write_csv(manifest_path, rows, ["relative_path", "size_bytes", "sha256"])


def main() -> None:
    args = parse_args()
    data_root = args.data_root.resolve()
    keyword_output = resolve_under(data_root, args.keyword_output)
    official_stops_path = resolve_under(data_root, args.official_stops)
    output_root = resolve_under(data_root, args.output)
    output_root.mkdir(parents=True, exist_ok=True)

    targets, unmatched_targets = load_targets(keyword_output)
    occurrences, unique_stops = build_official_stops(unmatched_targets, official_stops_path)
    write_csv(output_root / "targets/targeted_official_stop_occurrences.csv", occurrences)
    write_csv(output_root / "targets/targeted_unique_official_stops.csv", unique_stops)
    preparation = {
        "generated_at_utc": utc_now(),
        "status": "prepared",
        "unmatched_target_count": len(unmatched_targets),
        "unmatched_by_company": dict(sorted(Counter(row["company_code"] for row in unmatched_targets).items())),
        "official_stop_occurrence_count": len(occurrences),
        "unique_official_stop_count": len(unique_stops),
        "unique_official_stop_name_count": len({row["stop_name_zh"] for row in unique_stops}),
        "uses_place_polygon": False,
        "api_key_written_to_outputs": False,
    }
    write_json(output_root / "metadata/targeted_preparation_summary.json", preparation)
    if args.stage == "prepare":
        write_manifest(output_root)
        print(json.dumps(preparation, ensure_ascii=False, indent=2))
        return
    if not args.key and args.stage != "match":
        write_manifest(output_root)
        raise SystemExit("Missing AMap Web Service key. Target files were prepared without API calls.")

    client = AMapClient(args.key or "unused-in-match-stage", args.timeout, args.max_retries, args.sleep)
    place_summary_path = output_root / "metadata/place_stage_summary.json"
    stopid_summary_path = output_root / "metadata/stopid_stage_summary.json"
    lineid_summary_path = output_root / "metadata/lineid_stage_summary.json"
    place_summary: dict[str, Any] = read_json(place_summary_path) if place_summary_path.exists() else {}
    stopid_summary: dict[str, Any] = read_json(stopid_summary_path) if stopid_summary_path.exists() else {}
    lineid_summary: dict[str, Any] = read_json(lineid_summary_path) if lineid_summary_path.exists() else {}

    if args.stage in {"all", "place"}:
        selected_pois, place_summary = run_place_stage(args, client, unique_stops, output_root)
    else:
        selected_pois = load_selected_pois(output_root / "targets/amap_selected_stop_pois.csv")

    if args.stage in {"all", "stopid"}:
        stop_to_lines, stopid_summary = run_stopid_stage(args, client, selected_pois, output_root)
    else:
        path = output_root / "normalized/amap_stop_to_lines.csv"
        stop_to_lines = read_csv(path) if path.exists() else []

    line_audit = filter_line_ids(stop_to_lines, unmatched_targets)
    write_csv(output_root / "normalized/amap_lineid_candidates.csv", line_audit)
    if args.stage in {"all", "lineid"}:
        lines, lineid_summary = run_lineid_stage(args, client, line_audit, output_root)
    else:
        lines = load_cached_lines(output_root)

    targeted_matches = match_remaining(unmatched_targets, lines, args.accept_score)
    write_csv(output_root / "matches/targeted_remaining_route_matches.csv", targeted_matches)
    write_csv(
        output_root / "matches/targeted_still_unmatched_routes.csv",
        [row for row in targeted_matches if not bool_value(row.get("accepted"))],
    )
    combined_matches, combined_geometry_count, historical_qa = merge_results(
        keyword_output, output_root, targets, targeted_matches, lines
    )
    new_accepted = [row for row in targeted_matches if bool_value(row.get("accepted"))]
    combined_accepted = [row for row in combined_matches if bool_value(row.get("accepted"))]
    partial = any(
        bool(summary.get("stopped_by_daily_limit") or summary.get("error_count"))
        for summary in (place_summary, stopid_summary, lineid_summary)
    )
    final_summary = {
        **preparation,
        "generated_at_utc": utc_now(),
        "status": "partial" if partial else "complete",
        "place_stage": place_summary,
        "stopid_stage": stopid_summary,
        "lineid_stage": lineid_summary,
        "new_accepted_match_count": len(new_accepted),
        "new_accepted_by_company": dict(sorted(Counter(row["company_code"] for row in new_accepted).items())),
        "historical_linename_spatial_qa": historical_qa,
        "combined_accepted_match_count": len(combined_accepted),
        "combined_geometry_count": combined_geometry_count,
        "remaining_unmatched_count": len(targets) - len(combined_accepted),
        "coordinate_workflow": "Official WGS84 -> AMap GCJ-02 query; AMap GCJ-02 -> iterative WGS84 output",
        "limitations": [
            "Only the 55 known official stops of the 28 currently unmatched route targets are searched.",
            "MTR and Light Rail targets accepted by the line-name method are not queried again; the nominally accepted GMB target was outside the 28-target query set but is rejected by historical spatial QA.",
            "A cross-boundary coach absent from AMap remains unmatched; no synthetic straight-line trajectory is created.",
            "Four previously accepted line-name matches fail spatial QA and are retained only in unfiltered audit outputs.",
        ],
    }
    write_json(output_root / "metadata/amap_targeted_stopid_summary.json", final_summary)
    write_manifest(output_root)
    print(json.dumps(final_summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
