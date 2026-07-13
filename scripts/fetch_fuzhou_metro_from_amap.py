#!/usr/bin/env python
"""Fetch Fuzhou Metro line/stop metadata from AMap Web Service.

This script uses AMap's public Web Service bus line endpoint. In AMap's data
model, metro lines are returned through the bus line API as a public transit
line type. The script keeps station locations, service times, line membership,
stop order, adjacent-stop relationships, and optionally line trajectory
polylines.

It does not write the API key anywhere. Pass it with --key or set AMAP_WEB_KEY.
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
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote
from urllib.parse import urlencode
from urllib.request import Request, urlopen


AMAP_BUS_LINE_URL = "https://restapi.amap.com/v3/bus/linename"

DEFAULT_KEYWORDS = [
    "福州地铁1号线",
    "福州地铁2号线",
    "福州地铁4号线",
    "福州地铁5号线",
    "福州地铁6号线",
    "福州地铁滨海快线",
    "滨海快线",
    "福州地铁F1线",
]

METRO_HINTS = ("地铁", "轨道交通", "滨海快线", "F1", "metro", "subway")
DEFAULT_EXCLUDE_NAME_REGEX = "东延|东调|接驳|专线"


def request_json(url: str, params: dict[str, Any], timeout: int) -> dict[str, Any]:
    full_url = f"{url}?{urlencode(params)}"
    req = Request(full_url, headers={"User-Agent": "matsim-fuzhou-amap-transit/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    return json.loads(data.decode("utf-8"))


def as_list(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    return [value]


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


def clean_scalar(value: Any) -> str:
    if value is None:
        return ""
    if value == [] or value == {}:
        return ""
    return str(value)


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
    """Decode AMap timedesc, which is often URL-encoded JSON."""
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
        if isinstance(obj, dict):
            return obj
    except Exception:
        return None
    return None


def service_rows_from_timedesc(
    line_id: str,
    line_name: str,
    direction: str,
    timedesc: Any,
) -> list[dict[str, Any]]:
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
                "notes": "Need official/operator source for service period and frequency.",
            }
        ]

    rows: list[dict[str, Any]] = []
    all_remark = str(obj.get("allRemark") or "")
    for group in obj.get("rule_group") or []:
        date = group.get("date") or {}
        day_type = ",".join(str(x) for x in date.get("day_type") or [])
        day_week = ",".join(str(x) for x in date.get("day_week") or [])
        remark = str(group.get("remark") or "")
        time_group = group.get("time_group") or []
        if not time_group:
            rows.append(
                {
                    "line_id": line_id,
                    "line_name": line_name,
                    "direction": direction,
                    "day_type": day_type,
                    "day_week": day_week,
                    "period_start": "",
                    "period_end": "",
                    "interval_time": "",
                    "headway_minutes": "",
                    "remark": remark,
                    "all_remark": all_remark,
                    "source": "amap_timedesc_rule_group",
                    "notes": "No time_group in this rule.",
                }
            )
            continue
        for period in time_group:
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


def stable_id(*parts: Any, length: int = 16) -> str:
    text = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:length]


def looks_like_metro_line(line: dict[str, Any], include_related_bus: bool = False) -> bool:
    line_type = str(line.get("type", "") or "")
    name = str(line.get("name", "") or "")
    if "地铁" in line_type:
        return True
    if name.startswith("滨海快线"):
        return True
    if name.startswith("地铁") and "接驳" not in name and "专线" not in name:
        return True
    if not include_related_bus:
        return False
    text = " ".join(
        str(line.get(k, "") or "")
        for k in ("name", "type", "company", "terminal_name", "front_name")
    ).lower()
    return any(hint.lower() in text for hint in METRO_HINTS)


def clean_line_name(name: str | None) -> str:
    if not name:
        return ""
    # AMap often appends parenthesized direction/time hints. Keep the display
    # name as-is in outputs, but use this for rough duplicate grouping.
    return name.replace("（", "(").replace("）", ")").strip()


def strip_polyline_from_line(line: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(line)
    cleaned.pop("polyline", None)
    return cleaned


@dataclass
class FetchResult:
    keyword: str
    page: int
    response: dict[str, Any]


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
) -> list[FetchResult]:
    results: list[FetchResult] = []
    first_request = True
    for keyword in keywords:
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
                        f"AMap QPS limit for keyword={keyword!r}, page={page}; "
                        f"retrying in {backoff:.1f}s...",
                        file=sys.stderr,
                    )
                    time.sleep(backoff)
                    continue
                break
            assert response is not None
            results.append(FetchResult(keyword=keyword, page=page, response=response))
            status = str(response.get("status"))
            if status != "1":
                raise RuntimeError(
                    f"AMap request failed for keyword={keyword!r}, page={page}: "
                    f"status={response.get('status')} infocode={response.get('infocode')} "
                    f"info={response.get('info')}"
                )
            count = int(response.get("count") or 0)
            if count <= page * offset:
                break
    return results


def collect_lines(
    fetch_results: list[FetchResult],
    include_related_bus: bool = False,
    active_only: bool = False,
    exclude_name_regex: str = "",
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    lines = []
    for result in fetch_results:
        for line in as_list(result.response.get("buslines")):
            if not isinstance(line, dict):
                continue
            if not looks_like_metro_line(line, include_related_bus=include_related_bus):
                continue
            if active_only and str(line.get("status", "") or "") != "1":
                continue
            if exclude_name_regex and re.search(exclude_name_regex, str(line.get("name", "") or "")):
                continue
            line_id = str(line.get("id") or "")
            signature = line_id or stable_id(line.get("name"), line.get("polyline"), result.keyword)
            if signature in seen:
                continue
            seen.add(signature)
            line = dict(line)
            line["_source_keyword"] = result.keyword
            line["_source_page"] = result.page
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
        line_name = clean_line_name(line.get("name"))
        stops = [s for s in as_list(line.get("busstops")) if isinstance(s, dict)]
        start_stop = line.get("start_stop") or (stops[0].get("name") if stops else "")
        end_stop = line.get("end_stop") or (stops[-1].get("name") if stops else "")
        polyline = line.get("polyline") if include_polyline else ""
        polyline_coords = parse_polyline(polyline)

        line_rows.append(
            {
                "line_id": line_id,
                "line_name": line_name,
                "line_type": line.get("type", ""),
                "company": line.get("company", ""),
                "start_stop": start_stop,
                "end_stop": end_stop,
                "start_time": clean_scalar(line.get("start_time", "")),
                "end_time": clean_scalar(line.get("end_time", "")),
                "status": clean_scalar(line.get("status", "")),
                "direction_pair_line_id": clean_scalar(line.get("direc", "")),
                "distance": line.get("distance", ""),
                "basic_price": line.get("basic_price", ""),
                "total_price": line.get("total_price", ""),
                "bounds": line.get("bounds", ""),
                "stop_count": len(stops),
                "source_keyword": line.get("_source_keyword", ""),
                "has_polyline": bool(polyline_coords),
                "timedesc_parseable": decode_timedesc(line.get("timedesc")) is not None,
                "polyline": polyline if include_polyline else "",
            }
        )

        service_rows.extend(
            service_rows_from_timedesc(
                line_id,
                line_name,
                f"{start_stop}->{end_stop}",
                line.get("timedesc"),
            )
        )

        previous_occurrence: dict[str, Any] | None = None
        for idx, stop in enumerate(stops, start=1):
            stop_id_raw = str(stop.get("id") or "")
            stop_name = str(stop.get("name") or "")
            lon, lat = parse_lonlat(stop.get("location"))
            station_key = stop_id_raw or stable_id(stop_name, round(lon or 0, 6), round(lat or 0, 6))
            station_id = stop_id_raw or f"amap_station_{station_key}"
            occurrence_id = f"{line_id}_{idx:03d}_{stable_id(stop_name, lon, lat, length=8)}"
            stop_row = {
                "occurrence_id": occurrence_id,
                "line_id": line_id,
                "line_name": line_name,
                "direction_start": start_stop,
                "direction_end": end_stop,
                "sequence": int(stop.get("sequence") or idx),
                "station_id": station_id,
                "amap_stop_id": stop_id_raw,
                "station_name": stop_name,
                "lon": lon,
                "lat": lat,
            }
            stop_occurrences.append(stop_row)

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
                    "occurrence_count": 0,
                },
            )
            station["line_ids"].add(line_id)
            station["line_names"].add(line_name)
            station["occurrence_count"] += 1

            if previous_occurrence:
                edges.append(
                    {
                        "edge_id": f"{previous_occurrence['occurrence_id']}__{occurrence_id}",
                        "line_id": line_id,
                        "line_name": line_name,
                        "direction_start": start_stop,
                        "direction_end": end_stop,
                        "from_sequence": previous_occurrence["sequence"],
                        "to_sequence": stop_row["sequence"],
                        "from_station_id": previous_occurrence["station_id"],
                        "from_station_name": previous_occurrence["station_name"],
                        "from_lon": previous_occurrence["lon"],
                        "from_lat": previous_occurrence["lat"],
                        "to_station_id": stop_row["station_id"],
                        "to_station_name": stop_row["station_name"],
                        "to_lon": stop_row["lon"],
                        "to_lat": stop_row["lat"],
                    }
                )
            previous_occurrence = stop_row

        if include_polyline and len(polyline_coords) >= 2:
            trajectories.append(
                {
                    "line_id": line_id,
                    "line_name": line_name,
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
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def feature_collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": features}


def write_geojson(path: Path, features: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(feature_collection(features), ensure_ascii=False, indent=2), encoding="utf-8")


def station_features(stations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    features = []
    for row in stations:
        if row["lon"] is None or row["lat"] is None:
            continue
        props = dict(row)
        lon = props.pop("lon")
        lat = props.pop("lat")
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": props,
            }
        )
    return features


def stop_occurrence_features(stops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    features = []
    for row in stops:
        if row["lon"] is None or row["lat"] is None:
            continue
        props = dict(row)
        lon = props.pop("lon")
        lat = props.pop("lat")
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": props,
            }
        )
    return features


def edge_features(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    features = []
    for row in edges:
        if None in (row["from_lon"], row["from_lat"], row["to_lon"], row["to_lat"]):
            continue
        props = dict(row)
        from_lon = props.pop("from_lon")
        from_lat = props.pop("from_lat")
        to_lon = props.pop("to_lon")
        to_lat = props.pop("to_lat")
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[from_lon, from_lat], [to_lon, to_lat]]},
                "properties": props,
            }
        )
    return features


def trajectory_features(trajectories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    features = []
    for row in trajectories:
        coords = row["polyline_coords"]
        if len(coords) < 2:
            continue
        props = {k: v for k, v in row.items() if k != "polyline_coords"}
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[lon, lat] for lon, lat in coords]},
                "properties": props,
            }
        )
    return features


def sanitize_raw_results(results: list[FetchResult], include_polyline: bool) -> list[dict[str, Any]]:
    output = []
    for result in results:
        response = dict(result.response)
        if not include_polyline:
            response["buslines"] = [
                strip_polyline_from_line(line) if isinstance(line, dict) else line
                for line in as_list(response.get("buslines"))
            ]
        output.append({"keyword": result.keyword, "page": result.page, "response": response})
    return output


def load_keywords(args: argparse.Namespace) -> list[str]:
    keywords = list(DEFAULT_KEYWORDS)
    if args.keywords:
        keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    if args.keywords_file:
        lines = Path(args.keywords_file).read_text(encoding="utf-8").splitlines()
        keywords = [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]
    return keywords


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", default=os.environ.get("AMAP_WEB_KEY") or os.environ.get("AMAP_KEY"))
    parser.add_argument("--city", default="福州")
    parser.add_argument("--keywords", help="Comma-separated line keywords. Overrides defaults.")
    parser.add_argument("--keywords-file", help="UTF-8 text file, one keyword per line. Overrides defaults.")
    parser.add_argument("--output-dir", default="data/transit/fuzhou_metro_amap")
    parser.add_argument("--pages", type=int, default=2)
    parser.add_argument("--offset", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--max-retries", type=int, default=4)
    parser.add_argument(
        "--include-polyline",
        action="store_true",
        help="Keep AMap line trajectory polylines and write trajectory GeoJSON.",
    )
    parser.add_argument(
        "--include-related-bus",
        action="store_true",
        help="Also keep bus lines whose names mention metro, such as feeder or connector services.",
    )
    parser.add_argument(
        "--active-only",
        action="store_true",
        help="Keep only currently active lines where AMap status=1.",
    )
    parser.add_argument(
        "--exclude-name-regex",
        default="",
        help=(
            "Regex for line names to exclude after fetch. "
            f"For current-operation metro data, a useful value is {DEFAULT_EXCLUDE_NAME_REGEX!r}."
        ),
    )
    parser.add_argument(
        "--no-raw",
        action="store_true",
        help="Do not write raw API response JSON. Useful if you only want normalized tables.",
    )
    args = parser.parse_args()

    if not args.key:
        print(
            "Missing AMap Web Service key. Set AMAP_WEB_KEY or pass --key.",
            file=sys.stderr,
        )
        sys.exit(2)

    keywords = load_keywords(args)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Fetching AMap metro lines for city={args.city}, keywords={keywords}")
    fetch_results = fetch_buslines(
        args.key,
        args.city,
        keywords,
        pages=args.pages,
        offset=args.offset,
        timeout=args.timeout,
        sleep_seconds=args.sleep,
        max_retries=args.max_retries,
    )
    lines = collect_lines(
        fetch_results,
        include_related_bus=args.include_related_bus,
        active_only=args.active_only,
        exclude_name_regex=args.exclude_name_regex,
    )
    tables = extract_tables(lines, include_polyline=args.include_polyline)

    write_csv(output_dir / "amap_metro_lines.csv", tables["lines"])
    write_csv(output_dir / "amap_metro_stops_by_line.csv", tables["stop_occurrences"])
    write_csv(output_dir / "amap_metro_stations.csv", tables["stations"])
    write_csv(output_dir / "amap_metro_adjacent_stop_edges.csv", tables["edges"])
    write_csv(output_dir / "amap_metro_service_frequency.csv", tables["service_frequency"])

    write_geojson(output_dir / "amap_metro_stations.geojson", station_features(tables["stations"]))
    write_geojson(output_dir / "amap_metro_stops_by_line.geojson", stop_occurrence_features(tables["stop_occurrences"]))
    write_geojson(output_dir / "amap_metro_adjacent_stop_edges.geojson", edge_features(tables["edges"]))
    if args.include_polyline:
        write_geojson(output_dir / "amap_metro_line_trajectories.geojson", trajectory_features(tables["trajectories"]))

    if not args.no_raw:
        raw_path = output_dir / (
            "amap_raw_busline_responses_with_polyline.json"
            if args.include_polyline
            else "amap_raw_busline_responses_no_polyline.json"
        )
        raw_path.write_text(
            json.dumps(sanitize_raw_results(fetch_results, args.include_polyline), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    summary = {
        "city": args.city,
        "keywords": keywords,
        "endpoint": AMAP_BUS_LINE_URL,
        "include_polyline": args.include_polyline,
        "include_related_bus": args.include_related_bus,
        "active_only": args.active_only,
        "exclude_name_regex": args.exclude_name_regex,
        "raw_response_count": len(fetch_results),
        "metro_line_records": len(tables["lines"]),
        "station_records_unique": len(tables["stations"]),
        "stop_occurrences": len(tables["stop_occurrences"]),
        "adjacent_stop_edges": len(tables["edges"]),
        "trajectory_records": len(tables["trajectories"]),
        "headway_note": "AMap bus line endpoint usually does not return train frequency/headway; see amap_metro_service_frequency.csv.",
        "outputs": sorted(p.name for p in output_dir.glob("*")),
    }
    (output_dir / "amap_metro_fetch_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
