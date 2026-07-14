#!/usr/bin/env python
"""Fetch Fuzhou bus line/stop/headway data from AMap Web Service.

AMap does not provide a "download all bus lines in a city" endpoint through
the public Web Service. This script therefore performs keyword-based discovery,
deduplicates returned line records by AMap line id, and writes normalized CSV
and GeoJSON outputs.

The script can run in a small pilot mode, or with generated keyword profiles
for larger citywide collection. It never stores the API key; pass --key or set
AMAP_WEB_KEY.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlencode
from urllib.request import Request, urlopen

import requests
from bs4 import BeautifulSoup


AMAP_BUS_LINE_URL = "https://restapi.amap.com/v3/bus/linename"

PILOT_KEYWORDS = [
    "K1路",
    "51路",
    "101路",
    "200路",
    "夜班2号线",
    "地铁接驳1号专线",
    "地铁接驳2号专线",
    "马尾快线2号线",
    "闽侯地铁专线4路",
    "长乐地铁接驳1号线",
]

SPECIAL_KEYWORDS = [
    "K1路",
    "K2路",
    "K3路",
    "K4路",
    "K5路",
    "K6路",
    "夜班1号线",
    "夜班2号线",
    "夜班3号线",
    "地铁接驳1号专线",
    "地铁接驳2号专线",
    "地铁接驳5号专线",
    "地铁接驳6号专线",
    "马尾快线1号线",
    "马尾快线2号线",
    "马尾快线3号线",
    "马尾快线4号线",
    "闽侯地铁专线4路",
    "闽侯地铁专线5路",
    "闽侯地铁专线6路",
    "长乐地铁接驳1号线",
    "长乐地铁接驳2号线",
]

DEFAULT_WIKIPEDIA_BUS_LIST_URL = "https://zh.wikipedia.org/wiki/%E7%A6%8F%E5%B7%9E%E5%B8%82%E5%85%AC%E4%BA%A4%E7%BA%BF%E8%B7%AF%E5%88%97%E8%A1%A8"


def request_json(url: str, params: dict[str, Any], timeout: int) -> dict[str, Any]:
    full_url = f"{url}?{urlencode(params)}"
    req = Request(full_url, headers={"User-Agent": "matsim-fuzhou-amap-bus/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def as_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    return [value]


def clean_scalar(value: Any) -> str:
    if value is None:
        return ""
    if value == [] or value == {}:
        return ""
    return str(value)


def parse_lonlat(location: str | None) -> tuple[float | None, float | None]:
    if not location or "," not in location:
        return None, None
    try:
        lon, lat = location.split(",", 1)
        return float(lon), float(lat)
    except Exception:
        return None, None


def parse_polyline(polyline: str | None) -> list[tuple[float, float]]:
    if not polyline:
        return []
    coords = []
    for item in polyline.split(";"):
        lon, lat = parse_lonlat(item)
        if lon is not None and lat is not None:
            coords.append((lon, lat))
    return coords


def stable_id(*parts: Any, length: int = 16) -> str:
    text = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:length]


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
    if text in {"[]", "\"\"", "''"}:
        return None
    try:
        decoded = unquote(text)
        obj = json.loads(decoded)
        if isinstance(obj, str):
            if not obj:
                return None
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


def generate_keywords(profile: str, max_number: int) -> list[str]:
    if profile == "pilot":
        return list(PILOT_KEYWORDS)
    keywords: list[str] = []
    if profile in {"numeric", "citywide"}:
        for n in range(1, max_number + 1):
            keywords.append(f"{n}路")
    if profile == "citywide":
        keywords.extend(SPECIAL_KEYWORDS)
        for n in range(1, min(max_number, 50) + 1):
            keywords.extend(
                [
                    f"K{n}路",
                    f"夜班{n}号线",
                    f"地铁接驳{n}号专线",
                    f"马尾快线{n}号线",
                    f"闽侯地铁专线{n}路",
                    f"长乐地铁接驳{n}号线",
                ]
            )
    # Stable de-duplication while preserving order.
    seen = set()
    deduped = []
    for kw in keywords:
        if kw not in seen:
            seen.add(kw)
            deduped.append(kw)
    return deduped


def looks_like_bus_line_name(text: str) -> bool:
    text = re.sub(r"\s+", "", str(text or ""))
    if not text or len(text) > 40:
        return False
    if any(bad in text for bad in ["线路编号", "路线号码", "起讫站", "首末班", "备注", "票价"]):
        return False
    patterns = [
        r"^\d+路$",
        r"^\d+路快线$",
        r"^K\d+路$",
        r"^M\d+路$",
        r"^夜班\d+号线$",
        r"^地铁接驳\d+号专线$",
        r"^马尾快线\d+号线$",
        r"^闽侯地铁专线\d+路$",
        r"^长乐地铁接驳\d+号线$",
        r".*专线$",
        r".*快线$",
    ]
    return any(re.match(p, text) for p in patterns)


def normalize_line_name(text: str) -> str:
    text = re.sub(r"\[[^\]]+\]", "", str(text or ""))
    text = re.sub(r"（.*?）", "", text)
    text = re.sub(r"\(.*?\)", "", text)
    text = re.sub(r"\s+", "", text)
    return text.strip()


def dedupe_keywords(keywords: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for kw in keywords:
        kw = normalize_line_name(kw)
        if not kw or kw in seen:
            continue
        seen.add(kw)
        deduped.append(kw)
    return deduped


def discover_keywords_from_8684(city_slug: str, timeout: int = 30) -> tuple[list[str], dict[str, Any]]:
    """Discover bus line names from 8684 using both old and generic parsers."""
    base_url = f"https://{city_slug}.8684.cn"
    first_url = f"{base_url}/list1"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; matsim-fuzhou-bus/1.0)"}
    diagnostics: dict[str, Any] = {"source": "8684", "city_slug": city_slug, "first_url": first_url}
    keywords: list[str] = []
    try:
        r = requests.get(first_url, timeout=timeout, headers=headers)
        diagnostics.update({"status_code": r.status_code, "final_url": r.url, "content_length": len(r.text)})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # Old 8684 layout used by capsule-8584249.
        page_links: list[str] = []
        category = soup.find("div", {"class": "category"})
        if category:
            for a in category.find_all("a"):
                href = a.get("href")
                if href:
                    page_links.append(href)
        diagnostics["old_layout_category_found"] = bool(category)
        diagnostics["old_layout_page_links"] = len(page_links)

        if page_links:
            for href in page_links:
                url = href if href.startswith("http") else base_url + href
                pr = requests.get(url, timeout=timeout, headers=headers)
                if pr.status_code != 200:
                    continue
                psoup = BeautifulSoup(pr.text, "html.parser")
                list_div = psoup.find("div", {"class": "list clearfix"})
                if list_div:
                    for a in list_div.find_all("a"):
                        name = normalize_line_name(a.get_text(strip=True))
                        if looks_like_bus_line_name(name):
                            keywords.append(name)

        # Generic fallback: collect visible anchor text that looks like route names.
        if not keywords:
            for a in soup.find_all("a"):
                name = normalize_line_name(a.get_text(strip=True))
                if looks_like_bus_line_name(name):
                    keywords.append(name)
        keywords = dedupe_keywords(keywords)
        diagnostics["line_count"] = len(keywords)
        diagnostics["sample"] = keywords[:30]
        text_sample = soup.get_text(" ", strip=True)[:500]
        diagnostics["page_text_sample"] = text_sample
        return keywords, diagnostics
    except Exception as exc:
        diagnostics["error"] = repr(exc)
        return [], diagnostics


def discover_keywords_from_wikipedia(
    url: str = DEFAULT_WIKIPEDIA_BUS_LIST_URL,
    timeout: int = 30,
) -> tuple[list[str], dict[str, Any]]:
    """Discover Fuzhou bus line names from the public Wikipedia line list."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; matsim-fuzhou-bus/1.0)"}
    diagnostics: dict[str, Any] = {"source": "wikipedia", "url": url}
    keywords: list[str] = []
    try:
        r = requests.get(url, timeout=timeout, headers=headers)
        diagnostics.update({"status_code": r.status_code, "final_url": r.url, "content_length": len(r.text)})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for table in soup.find_all("table"):
            for tr in table.find_all("tr"):
                cells = tr.find_all(["td", "th"])
                if not cells:
                    continue
                first = normalize_line_name(cells[0].get_text(" ", strip=True))
                if looks_like_bus_line_name(first):
                    keywords.append(first)
        # As a fallback, inspect links too.
        if not keywords:
            for a in soup.find_all("a"):
                name = normalize_line_name(a.get_text(strip=True))
                if looks_like_bus_line_name(name):
                    keywords.append(name)
        keywords = dedupe_keywords(keywords)
        diagnostics["line_count"] = len(keywords)
        diagnostics["sample"] = keywords[:50]
        return keywords, diagnostics
    except Exception as exc:
        diagnostics["error"] = repr(exc)
        return [], diagnostics


def load_keywords(args: argparse.Namespace) -> list[str]:
    if args.keywords:
        return [k.strip() for k in args.keywords.split(",") if k.strip()]
    if args.keywords_file:
        lines = Path(args.keywords_file).read_text(encoding="utf-8-sig").splitlines()
        return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]
    return generate_keywords(args.keyword_profile, args.max_number)


def fetch_buslines(
    key: str,
    city: str,
    keywords: list[str],
    *,
    pages: int,
    offset: int,
    timeout: int,
    sleep_seconds: float,
    max_retries: int,
    fail_on_api_error: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    first_request = True
    stopped_early = False
    for idx, keyword in enumerate(keywords, start=1):
        for page in range(1, pages + 1):
            if not first_request and sleep_seconds:
                time.sleep(sleep_seconds)
            first_request = False
            params = {
                "key": key,
                "city": city,
                "keywords": keyword,
                "extensions": "all",
                "output": "json",
                "offset": offset,
                "page": page,
            }
            response = None
            for attempt in range(max_retries + 1):
                response = request_json(AMAP_BUS_LINE_URL, params, timeout)
                status = str(response.get("status"))
                infocode = str(response.get("infocode") or "")
                if status == "1":
                    break
                if infocode == "10021" and attempt < max_retries:
                    backoff = max(sleep_seconds, 1.0) * (attempt + 2)
                    print(
                        f"AMap QPS limit for keyword={keyword!r}, page={page}; retrying in {backoff:.1f}s...",
                        file=sys.stderr,
                    )
                    time.sleep(backoff)
                    continue
                break
            assert response is not None
            if str(response.get("status")) != "1":
                err = {
                    "keyword_index": idx,
                    "keyword": keyword,
                    "page": page,
                    "status": response.get("status"),
                    "infocode": response.get("infocode"),
                    "info": response.get("info"),
                }
                errors.append(err)
                print(f"AMap request failed: {err}", file=sys.stderr)
                if str(response.get("infocode")) == "10044":
                    stopped_early = True
                    return results, errors, stopped_early
                if fail_on_api_error:
                    raise RuntimeError(
                        f"AMap request failed for keyword={keyword!r}, page={page}: "
                        f"status={response.get('status')} infocode={response.get('infocode')} info={response.get('info')}"
                    )
                break
            count = int(response.get("count") or 0)
            print(f"[{idx}/{len(keywords)}] keyword={keyword!r} page={page} count={count}", flush=True)
            results.append({"keyword": keyword, "page": page, "response": response})
            if count <= page * offset:
                break
    return results, errors, stopped_early


def keep_line(line: dict[str, Any], *, include_metro: bool, line_type_regex: str, exclude_name_regex: str) -> bool:
    name = str(line.get("name") or "")
    line_type = str(line.get("type") or "")
    if not include_metro and "地铁" in line_type:
        return False
    if line_type_regex and not re.search(line_type_regex, line_type):
        return False
    if exclude_name_regex and re.search(exclude_name_regex, name):
        return False
    return True


def collect_lines(
    fetch_results: list[dict[str, Any]],
    *,
    include_metro: bool,
    line_type_regex: str,
    exclude_name_regex: str,
) -> list[dict[str, Any]]:
    seen = set()
    lines = []
    for result in fetch_results:
        for line in as_list(result["response"].get("buslines")):
            if not isinstance(line, dict):
                continue
            if not keep_line(
                line,
                include_metro=include_metro,
                line_type_regex=line_type_regex,
                exclude_name_regex=exclude_name_regex,
            ):
                continue
            line_id = str(line.get("id") or "")
            signature = line_id or stable_id(line.get("name"), line.get("polyline"), result["keyword"])
            if signature in seen:
                continue
            seen.add(signature)
            line = dict(line)
            line["_source_keyword"] = result["keyword"]
            line["_source_page"] = result["page"]
            lines.append(line)
    return lines


def extract_tables(lines: list[dict[str, Any]], include_polyline: bool) -> dict[str, list[dict[str, Any]]]:
    line_rows: list[dict[str, Any]] = []
    stop_occurrences: list[dict[str, Any]] = []
    station_by_key: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    trajectories: list[dict[str, Any]] = []
    service_rows: list[dict[str, Any]] = []

    for line_index, line in enumerate(lines):
        line_id = str(line.get("id") or stable_id(line.get("name"), line_index))
        line_name = clean_scalar(line.get("name"))
        stops = [s for s in as_list(line.get("busstops")) if isinstance(s, dict)]
        start_stop = clean_scalar(line.get("start_stop") or (stops[0].get("name") if stops else ""))
        end_stop = clean_scalar(line.get("end_stop") or (stops[-1].get("name") if stops else ""))
        polyline = line.get("polyline") if include_polyline else ""
        polyline_coords = parse_polyline(polyline)

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
                "source_keyword": clean_scalar(line.get("_source_keyword")),
                "has_polyline": bool(polyline_coords),
                "timedesc_parseable": decode_timedesc(line.get("timedesc")) is not None,
                "polyline": polyline if include_polyline else "",
            }
        )
        service_rows.extend(
            service_rows_from_timedesc(line_id, line_name, f"{start_stop}->{end_stop}", line.get("timedesc"))
        )

        previous = None
        for idx, stop in enumerate(stops, start=1):
            stop_id_raw = clean_scalar(stop.get("id"))
            stop_name = clean_scalar(stop.get("name"))
            lon, lat = parse_lonlat(stop.get("location"))
            station_key = stop_id_raw or stable_id(stop_name, round(lon or 0, 6), round(lat or 0, 6))
            station_id = stop_id_raw or f"amap_bus_stop_{station_key}"
            occurrence_id = f"{line_id}_{idx:03d}_{stable_id(stop_name, lon, lat, length=8)}"
            row = {
                "occurrence_id": occurrence_id,
                "line_id": line_id,
                "line_name": line_name,
                "line_type": clean_scalar(line.get("type")),
                "direction_start": start_stop,
                "direction_end": end_stop,
                "sequence": int(stop.get("sequence") or idx),
                "station_id": station_id,
                "amap_stop_id": stop_id_raw,
                "station_name": stop_name,
                "lon": lon,
                "lat": lat,
            }
            stop_occurrences.append(row)
            station = station_by_key.setdefault(
                station_key,
                {
                    "station_id": station_id,
                    "amap_stop_id": stop_id_raw,
                    "station_name": stop_name,
                    "lon": lon,
                    "lat": lat,
                    "line_ids": set(),
                    "line_names": set(),
                    "line_types": set(),
                    "occurrence_count": 0,
                },
            )
            station["line_ids"].add(line_id)
            station["line_names"].add(line_name)
            station["line_types"].add(clean_scalar(line.get("type")))
            station["occurrence_count"] += 1
            if previous:
                edges.append(
                    {
                        "edge_id": f"{previous['occurrence_id']}__{occurrence_id}",
                        "line_id": line_id,
                        "line_name": line_name,
                        "line_type": clean_scalar(line.get("type")),
                        "direction_start": start_stop,
                        "direction_end": end_stop,
                        "from_sequence": previous["sequence"],
                        "to_sequence": row["sequence"],
                        "from_station_id": previous["station_id"],
                        "from_station_name": previous["station_name"],
                        "from_lon": previous["lon"],
                        "from_lat": previous["lat"],
                        "to_station_id": row["station_id"],
                        "to_station_name": row["station_name"],
                        "to_lon": row["lon"],
                        "to_lat": row["lat"],
                    }
                )
            previous = row

        if include_polyline and len(polyline_coords) >= 2:
            trajectories.append(
                {
                    "line_id": line_id,
                    "line_name": line_name,
                    "line_type": clean_scalar(line.get("type")),
                    "direction_start": start_stop,
                    "direction_end": end_stop,
                    "polyline_coords": polyline_coords,
                }
            )

    station_rows = []
    for station in station_by_key.values():
        station_rows.append(
            {
                "station_id": station["station_id"],
                "amap_stop_id": station["amap_stop_id"],
                "station_name": station["station_name"],
                "lon": station["lon"],
                "lat": station["lat"],
                "line_ids": ";".join(sorted(station["line_ids"])),
                "line_names": ";".join(sorted(station["line_names"])),
                "line_types": ";".join(sorted(station["line_types"])),
                "occurrence_count": station["occurrence_count"],
            }
        )
    station_rows.sort(key=lambda r: (r["station_name"], r["station_id"]))
    return {
        "lines": line_rows,
        "stop_occurrences": stop_occurrences,
        "stations": station_rows,
        "edges": edges,
        "trajectories": trajectories,
        "service_frequency": service_rows,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_geojson(path: Path, features: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def point_features(rows: list[dict[str, Any]], lon_key: str = "lon", lat_key: str = "lat") -> list[dict[str, Any]]:
    features = []
    for row in rows:
        if row.get(lon_key) is None or row.get(lat_key) is None:
            continue
        props = dict(row)
        lon = props.pop(lon_key)
        lat = props.pop(lat_key)
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": props})
    return features


def edge_features(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    features = []
    for row in rows:
        if None in (row["from_lon"], row["from_lat"], row["to_lon"], row["to_lat"]):
            continue
        props = dict(row)
        coords = [[props.pop("from_lon"), props.pop("from_lat")], [props.pop("to_lon"), props.pop("to_lat")]]
        features.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords}, "properties": props})
    return features


def trajectory_features(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    features = []
    for row in rows:
        coords = row["polyline_coords"]
        props = {k: v for k, v in row.items() if k != "polyline_coords"}
        features.append(
            {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[x, y] for x, y in coords]}, "properties": props}
        )
    return features


def sanitize_raw_results(results: list[dict[str, Any]], include_polyline: bool) -> list[dict[str, Any]]:
    output = []
    for result in results:
        response = dict(result["response"])
        if not include_polyline:
            response["buslines"] = [
                {k: v for k, v in line.items() if k != "polyline"} if isinstance(line, dict) else line
                for line in as_list(response.get("buslines"))
            ]
        output.append({"keyword": result["keyword"], "page": result["page"], "response": response})
    return output


def write_coverage(output_dir: Path, lines: list[dict[str, Any]], service_rows: list[dict[str, Any]]) -> None:
    import pandas as pd

    line_df = pd.DataFrame(lines)
    svc_df = pd.DataFrame(service_rows)
    if line_df.empty:
        write_csv(output_dir / "amap_bus_data_coverage_and_missing_items.csv", [])
        return
    rows = []
    for _, line in line_df.iterrows():
        line_id = str(line["line_id"])
        sub = svc_df[svc_df["line_id"].astype(str) == line_id] if not svc_df.empty else pd.DataFrame()
        sub_nonempty = sub[sub["headway_minutes"].notna() & (sub["headway_minutes"].astype(str) != "")] if not sub.empty else pd.DataFrame()
        rows.append(
            {
                "line_id": line["line_id"],
                "line_name": line["line_name"],
                "line_type": line["line_type"],
                "start_stop": line["start_stop"],
                "end_stop": line["end_stop"],
                "stop_count": line["stop_count"],
                "has_polyline": line["has_polyline"],
                "timedesc_parseable": line["timedesc_parseable"],
                "service_period_rows": len(sub_nonempty),
                "min_headway_minutes": sub_nonempty["headway_minutes"].astype(float).min() if len(sub_nonempty) else "",
                "max_headway_minutes": sub_nonempty["headway_minutes"].astype(float).max() if len(sub_nonempty) else "",
                "missing_items": ";".join(
                    item
                    for item, missing in [
                        ("headway/frequency", len(sub_nonempty) == 0),
                        ("polyline", not bool(line["has_polyline"])),
                        ("start_time/end_time", not bool(str(line.get("start_time", "")).strip())),
                    ]
                    if missing
                ),
            }
        )
    write_csv(output_dir / "amap_bus_data_coverage_and_missing_items.csv", rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", default=os.environ.get("AMAP_WEB_KEY") or os.environ.get("AMAP_KEY"))
    parser.add_argument("--city", default="福州")
    parser.add_argument("--keywords", help="Comma-separated keywords. Overrides keyword profile.")
    parser.add_argument("--keywords-file", help="UTF-8 text file, one keyword per line. Overrides keyword profile.")
    parser.add_argument("--discover-from-8684", action="store_true", help="Discover route names from 8684 before querying AMap.")
    parser.add_argument("--8684-city-slug", default="fuzhou", help="8684 subdomain slug, e.g. fuzhou.")
    parser.add_argument(
        "--discover-from-wikipedia",
        action="store_true",
        help="Discover route names from the public Fuzhou bus line list on Chinese Wikipedia.",
    )
    parser.add_argument("--wikipedia-url", default=DEFAULT_WIKIPEDIA_BUS_LIST_URL)
    parser.add_argument(
        "--discovery-only",
        action="store_true",
        help="Only discover route keywords and write keyword files; do not query AMap.",
    )
    parser.add_argument("--start-keyword-index", type=int, default=1, help="1-based index to resume keyword processing.")
    parser.add_argument("--max-keywords", type=int, default=0, help="Limit number of keywords after discovery/loading. 0 means no limit.")
    parser.add_argument("--keyword-profile", choices=["pilot", "numeric", "citywide"], default="pilot")
    parser.add_argument("--max-number", type=int, default=300, help="Largest N for generated N路 keywords.")
    parser.add_argument("--pages", type=int, default=2)
    parser.add_argument("--offset", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--sleep", type=float, default=3.0)
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument(
        "--fail-on-api-error",
        action="store_true",
        help="Abort on API errors other than daily quota. By default, save partial results and continue where possible.",
    )
    parser.add_argument("--include-polyline", action="store_true")
    parser.add_argument("--include-metro", action="store_true", help="Keep metro lines too. Default excludes line_type containing 地铁.")
    parser.add_argument("--line-type-regex", default="", help="Optional regex for line type filtering, e.g. 普通公交|快速公交.")
    parser.add_argument("--exclude-name-regex", default="", help="Optional regex for line names to exclude.")
    parser.add_argument("--output-dir", default="data/transit/fuzhou_bus_amap")
    parser.add_argument("--no-raw", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    discovery_diagnostics: list[dict[str, Any]] = []

    if args.discover_from_8684:
        keywords, diag = discover_keywords_from_8684(args.__dict__["8684_city_slug"], timeout=args.timeout)
        discovery_diagnostics.append(diag)
    elif args.discover_from_wikipedia:
        keywords, diag = discover_keywords_from_wikipedia(args.wikipedia_url, timeout=args.timeout)
        discovery_diagnostics.append(diag)
    else:
        keywords = load_keywords(args)

    if not keywords and (args.discover_from_8684 or args.discover_from_wikipedia):
        print("Discovery returned no keywords; falling back to keyword profile.", file=sys.stderr)
        keywords = load_keywords(args)

    keywords = dedupe_keywords(keywords)
    if args.start_keyword_index > 1:
        keywords = keywords[args.start_keyword_index - 1 :]
    if args.max_keywords and args.max_keywords > 0:
        keywords = keywords[: args.max_keywords]

    (output_dir / "keywords_used.txt").write_text("\n".join(keywords), encoding="utf-8")
    if discovery_diagnostics:
        (output_dir / "keyword_discovery_diagnostics.json").write_text(
            json.dumps(discovery_diagnostics, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    write_csv(output_dir / "discovered_bus_keywords.csv", [{"keyword": kw} for kw in keywords])

    if args.discovery_only:
        summary = {
            "city": args.city,
            "keyword_count": len(keywords),
            "keywords_file": str(output_dir / "keywords_used.txt"),
            "discovery_diagnostics": discovery_diagnostics,
        }
        (output_dir / "amap_bus_fetch_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    if not args.key:
        print("Missing AMap Web Service key. Set AMAP_WEB_KEY or pass --key.", file=sys.stderr)
        sys.exit(2)

    print(f"Fetching AMap bus lines city={args.city}, keywords={len(keywords)}, profile={args.keyword_profile}")
    fetch_results, api_errors, stopped_early = fetch_buslines(
        args.key,
        args.city,
        keywords,
        pages=args.pages,
        offset=args.offset,
        timeout=args.timeout,
        sleep_seconds=args.sleep,
        max_retries=args.max_retries,
        fail_on_api_error=args.fail_on_api_error,
    )
    lines = collect_lines(
        fetch_results,
        include_metro=args.include_metro,
        line_type_regex=args.line_type_regex,
        exclude_name_regex=args.exclude_name_regex,
    )
    tables = extract_tables(lines, include_polyline=args.include_polyline)

    write_csv(output_dir / "amap_bus_lines.csv", tables["lines"])
    write_csv(output_dir / "amap_bus_stops_by_line.csv", tables["stop_occurrences"])
    write_csv(output_dir / "amap_bus_stations.csv", tables["stations"])
    write_csv(output_dir / "amap_bus_adjacent_stop_edges.csv", tables["edges"])
    write_csv(output_dir / "amap_bus_service_frequency.csv", tables["service_frequency"])
    write_geojson(output_dir / "amap_bus_stations.geojson", point_features(tables["stations"]))
    write_geojson(output_dir / "amap_bus_stops_by_line.geojson", point_features(tables["stop_occurrences"]))
    write_geojson(output_dir / "amap_bus_adjacent_stop_edges.geojson", edge_features(tables["edges"]))
    if args.include_polyline:
        write_geojson(output_dir / "amap_bus_line_trajectories.geojson", trajectory_features(tables["trajectories"]))

    write_coverage(output_dir, tables["lines"], tables["service_frequency"])

    if not args.no_raw:
        raw_name = "amap_raw_busline_responses_with_polyline.json" if args.include_polyline else "amap_raw_busline_responses_no_polyline.json"
        (output_dir / raw_name).write_text(
            json.dumps(sanitize_raw_results(fetch_results, args.include_polyline), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if api_errors:
        (output_dir / "amap_api_errors.json").write_text(
            json.dumps(api_errors, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    summary = {
        "city": args.city,
        "endpoint": AMAP_BUS_LINE_URL,
        "keyword_count": len(keywords),
        "keyword_profile": args.keyword_profile,
        "discovery_diagnostics": discovery_diagnostics,
        "include_polyline": args.include_polyline,
        "include_metro": args.include_metro,
        "raw_response_count": len(fetch_results),
        "api_error_count": len(api_errors),
        "stopped_early": stopped_early,
        "bus_line_records": len(tables["lines"]),
        "station_records_unique": len(tables["stations"]),
        "stop_occurrences": len(tables["stop_occurrences"]),
        "adjacent_stop_edges": len(tables["edges"]),
        "trajectory_records": len(tables["trajectories"]),
        "outputs": sorted(p.name for p in output_dir.glob("*")),
    }
    (output_dir / "amap_bus_fetch_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
