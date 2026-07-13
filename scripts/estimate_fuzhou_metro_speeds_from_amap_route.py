#!/usr/bin/env python3
"""Estimate MATSim metro freespeeds from AMap transit routing results.

The script queries AMap's integrated transit routing endpoint for each metro
direction using the first and last station coordinates. It keeps only direct,
single-line metro alternatives and derives a MATSim-friendly freespeed after
subtracting a fixed average wait time and fixed station dwell time.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_METRO_DIR = DEFAULT_ROOT / "data" / "transit" / "fuzhou_metro_final_20260709"
DEFAULT_LINES_CSV = DEFAULT_METRO_DIR / "amap_active" / "amap_metro_lines.csv"
DEFAULT_STOPS_CSV = DEFAULT_METRO_DIR / "amap_active" / "amap_metro_stops_by_line.csv"
DEFAULT_OUTPUT_CSV = DEFAULT_METRO_DIR / "amap_active" / "amap_metro_speed_estimates_from_route_api.csv"
DEFAULT_SUMMARY_JSON = DEFAULT_METRO_DIR / "metadata" / "amap_metro_speed_estimation_summary.json"
DEFAULT_RAW_JSONL = DEFAULT_METRO_DIR / "metadata" / "amap_metro_speed_estimation_raw_responses.jsonl"


AMAP_TRANSIT_URL = "https://restapi.amap.com/v3/direction/transit/integrated"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", "", value).replace("（", "(").replace("）", ")")


def line_base_name(line_name: str | None) -> str:
    value = normalize_text(line_name)
    if "(" in value:
        return value.split("(", 1)[0]
    return value


def safe_float(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return str(value)


def load_line_records(lines_csv: Path, stops_csv: Path) -> list[dict[str, Any]]:
    lines = {row["line_id"]: row for row in read_csv(lines_csv)}
    stops_by_line: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in read_csv(stops_csv):
        stops_by_line[row["line_id"]].append(row)

    records: list[dict[str, Any]] = []
    for line_id, stops in sorted(stops_by_line.items()):
        stops_sorted = sorted(stops, key=lambda r: safe_int(r.get("sequence")))
        if not stops_sorted:
            continue
        first = stops_sorted[0]
        last = stops_sorted[-1]
        line = lines.get(line_id, {})
        line_name = line.get("line_name") or first.get("line_name") or ""
        station_count = safe_int(line.get("stop_count"), len(stops_sorted)) or len(stops_sorted)
        api_distance_m = safe_float(line.get("distance")) * 1000.0
        records.append(
            {
                "line_id": line_id,
                "line_name": line_name,
                "origin_station": first.get("station_name", ""),
                "destination_station": last.get("station_name", ""),
                "origin": f"{first.get('lon')},{first.get('lat')}",
                "destination": f"{last.get('lon')},{last.get('lat')}",
                "station_count": station_count,
                "stops_by_line_count": len(stops_sorted),
                "line_table_distance_m": api_distance_m,
                "direction_pair_line_id": line.get("direction_pair_line_id", ""),
            }
        )
    return records


def amap_query(
    key: str,
    origin: str,
    destination: str,
    strategy: str,
    city: str,
    timeout: int,
) -> dict[str, Any]:
    params = {
        "key": key,
        "origin": origin,
        "destination": destination,
        "city": city,
        "cityd": city,
        "strategy": strategy,
        "output": "json",
    }
    url = AMAP_TRANSIT_URL + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
        return json.loads(response.read().decode("utf-8"))


def buslines_from_transit(transit: dict[str, Any]) -> tuple[list[dict[str, Any]], float]:
    buslines: list[dict[str, Any]] = []
    walking_duration_s = 0.0
    for segment in transit.get("segments") or []:
        walking = segment.get("walking") or {}
        walking_duration_s += safe_float(walking.get("duration"))
        lines = (segment.get("bus") or {}).get("buslines") or []
        if isinstance(lines, dict):
            lines = [lines]
        for line in lines:
            buslines.append(line)
    return buslines, walking_duration_s


def is_direct_target_plan(
    buslines: list[dict[str, Any]],
    target_line_name: str,
    origin_station: str,
    destination_station: str,
) -> bool:
    if len(buslines) != 1:
        return False
    line = buslines[0]
    selected_line_name = normalize_text(line.get("name"))
    target = normalize_text(target_line_name)
    if selected_line_name != target:
        return False
    dep = normalize_text((line.get("departure_stop") or {}).get("name"))
    arr = normalize_text((line.get("arrival_stop") or {}).get("name"))
    return dep == normalize_text(origin_station) and arr == normalize_text(destination_station)


def plan_summary(transit: dict[str, Any], rank: int, target: dict[str, Any]) -> dict[str, Any]:
    buslines, walking_duration_s = buslines_from_transit(transit)
    segments: list[dict[str, Any]] = []
    busline_duration_s = 0.0
    busline_distance_m = 0.0
    for line in buslines:
        duration = safe_float(line.get("duration"))
        distance = safe_float(line.get("distance"))
        busline_duration_s += duration
        busline_distance_m += distance
        segments.append(
            {
                "name": line.get("name", ""),
                "type": line.get("type", ""),
                "from": (line.get("departure_stop") or {}).get("name", ""),
                "to": (line.get("arrival_stop") or {}).get("name", ""),
                "duration_s": duration,
                "distance_m": distance,
                "via_num": line.get("via_num", ""),
            }
        )
    return {
        "rank": rank,
        "api_total_duration_s": safe_float(transit.get("duration")),
        "api_total_distance_m": safe_float(transit.get("distance")),
        "walking_distance_m": safe_float(transit.get("walking_distance")),
        "walking_duration_s": walking_duration_s,
        "busline_duration_s": busline_duration_s,
        "busline_distance_m": busline_distance_m,
        "segments_count": len(segments),
        "segments": segments,
        "is_direct_target": is_direct_target_plan(
            buslines,
            target["line_name"],
            target["origin_station"],
            target["destination_station"],
        ),
    }


def find_direct_plan(
    key: str,
    target: dict[str, Any],
    strategies: list[str],
    city: str,
    timeout: int,
    sleep_s: float,
    raw_writer: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    selected: dict[str, Any] | None = None
    for strategy in strategies:
        if sleep_s > 0 and attempts:
            time.sleep(sleep_s)
        query_summary = {
            "line_id": target["line_id"],
            "line_name": target["line_name"],
            "origin_station": target["origin_station"],
            "destination_station": target["destination_station"],
            "origin": target["origin"],
            "destination": target["destination"],
            "city": city,
            "strategy": strategy,
        }
        try:
            response = amap_query(key, target["origin"], target["destination"], strategy, city, timeout)
            error = None
        except Exception as exc:  # pragma: no cover - network failure path
            response = {}
            error = f"{type(exc).__name__}: {exc}"
        transits = (response.get("route") or {}).get("transits") or []
        if isinstance(transits, dict):
            transits = [transits]
        plans = [plan_summary(transit, rank, target) for rank, transit in enumerate(transits, start=1)]
        raw_record = {
            "query": query_summary,
            "error": error,
            "status": response.get("status"),
            "info": response.get("info"),
            "infocode": response.get("infocode"),
            "count": response.get("count"),
            "response": response,
        }
        raw_writer.write(json.dumps(raw_record, ensure_ascii=False, default=json_default) + "\n")
        attempt = {
            "strategy": strategy,
            "error": error,
            "status": response.get("status"),
            "info": response.get("info"),
            "infocode": response.get("infocode"),
            "count": response.get("count"),
            "transit_count": len(plans),
            "plans": plans,
        }
        attempts.append(attempt)
        for plan in plans:
            if plan["is_direct_target"]:
                selected = {"strategy": strategy, **plan}
                return selected, {"attempts": attempts}
    return selected, {"attempts": attempts}


def compute_speed_row(
    target: dict[str, Any],
    selected: dict[str, Any] | None,
    status: str,
    fallback_source_line_id: str = "",
    fallback_note: str = "",
    wait_time_s: float = 120.0,
    dwell_time_per_intermediate_stop_s: float = 30.0,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "line_id": target["line_id"],
        "line_name": target["line_name"],
        "origin_station": target["origin_station"],
        "destination_station": target["destination_station"],
        "station_count": target["station_count"],
        "stops_by_line_count": target["stops_by_line_count"],
        "direction_pair_line_id": target.get("direction_pair_line_id", ""),
        "estimate_status": status,
        "fallback_source_line_id": fallback_source_line_id,
        "fallback_note": fallback_note,
        "selected_strategy": "",
        "selected_plan_rank": "",
        "selected_plan_segments_count": "",
        "selected_line_name": "",
        "selected_departure_stop": "",
        "selected_arrival_stop": "",
        "api_total_duration_s": "",
        "api_total_duration_min": "",
        "api_total_distance_m": "",
        "api_line_duration_s": "",
        "api_line_distance_m": "",
        "walking_duration_s": "",
        "walking_distance_m": "",
        "average_wait_time_subtracted_s": wait_time_s,
        "vehicle_service_time_s": "",
        "dwell_time_s": "",
        "pure_running_time_s": "",
        "matsim_freespeed_mps": "",
        "speed_kmh": "",
        "with_dwell_average_speed_mps": "",
        "with_dwell_average_speed_kmh": "",
        "line_table_distance_m": round(safe_float(target.get("line_table_distance_m")), 3),
        "warning": "",
    }
    if not selected:
        return row

    segment = (selected.get("segments") or [{}])[0]
    api_total_duration_s = safe_float(selected.get("api_total_duration_s"))
    walking_duration_s = safe_float(selected.get("walking_duration_s"))
    api_line_duration_s = safe_float(segment.get("duration_s"))
    api_line_distance_m = safe_float(segment.get("distance_m")) or safe_float(selected.get("busline_distance_m"))
    vehicle_service_time_s = api_total_duration_s - walking_duration_s - wait_time_s
    dwell_time_s = max(safe_int(target["station_count"]) - 2, 0) * dwell_time_per_intermediate_stop_s
    pure_running_time_s = vehicle_service_time_s - dwell_time_s
    with_dwell_speed_mps = api_line_distance_m / vehicle_service_time_s if vehicle_service_time_s > 0 else math.nan
    freespeed_mps = api_line_distance_m / pure_running_time_s if pure_running_time_s > 0 else math.nan

    warnings: list[str] = []
    if pure_running_time_s <= 0:
        warnings.append("non_positive_pure_running_time")
    if not math.isnan(freespeed_mps):
        if line_base_name(target["line_name"]) == normalize_text("滨海快线"):
            if freespeed_mps > 30:
                warnings.append("speed_gt_30mps_for_binhai_express")
        elif not (8 <= freespeed_mps <= 18):
            warnings.append("speed_outside_8_18mps_common_metro_range")

    row.update(
        {
            "selected_strategy": selected.get("strategy", ""),
            "selected_plan_rank": selected.get("rank", ""),
            "selected_plan_segments_count": selected.get("segments_count", ""),
            "selected_line_name": segment.get("name", ""),
            "selected_departure_stop": segment.get("from", ""),
            "selected_arrival_stop": segment.get("to", ""),
            "api_total_duration_s": round(api_total_duration_s, 3),
            "api_total_duration_min": round(api_total_duration_s / 60.0, 3),
            "api_total_distance_m": round(safe_float(selected.get("api_total_distance_m")), 3),
            "api_line_duration_s": round(api_line_duration_s, 3),
            "api_line_distance_m": round(api_line_distance_m, 3),
            "walking_duration_s": round(walking_duration_s, 3),
            "walking_distance_m": round(safe_float(selected.get("walking_distance_m")), 3),
            "vehicle_service_time_s": round(vehicle_service_time_s, 3),
            "dwell_time_s": round(dwell_time_s, 3),
            "pure_running_time_s": round(pure_running_time_s, 3),
            "matsim_freespeed_mps": round(freespeed_mps, 4) if not math.isnan(freespeed_mps) else "",
            "speed_kmh": round(freespeed_mps * 3.6, 3) if not math.isnan(freespeed_mps) else "",
            "with_dwell_average_speed_mps": round(with_dwell_speed_mps, 4)
            if not math.isnan(with_dwell_speed_mps)
            else "",
            "with_dwell_average_speed_kmh": round(with_dwell_speed_mps * 3.6, 3)
            if not math.isnan(with_dwell_speed_mps)
            else "",
            "warning": ";".join(warnings),
        }
    )
    return row


def apply_reverse_direction_fallback(
    rows: list[dict[str, Any]],
    records_by_id: dict[str, dict[str, Any]],
    wait_time_s: float,
    dwell_time_per_intermediate_stop_s: float,
) -> None:
    rows_by_id = {row["line_id"]: row for row in rows}
    for row in rows:
        if row["estimate_status"] == "direct_route_api":
            continue
        pair_id = row.get("direction_pair_line_id") or ""
        pair_row = rows_by_id.get(pair_id)
        target = records_by_id[row["line_id"]]
        if not pair_row or pair_row.get("estimate_status") not in (
            "direct_route_api",
            "estimated_from_reverse_direction",
        ):
            continue
        # Reuse the reverse direction's final speed, while keeping this direction's
        # own station count and line-table distance for traceability.
        for key in (
            "matsim_freespeed_mps",
            "speed_kmh",
            "with_dwell_average_speed_mps",
            "with_dwell_average_speed_kmh",
        ):
            row[key] = pair_row.get(key, "")
        row["estimate_status"] = "estimated_from_reverse_direction"
        row["fallback_source_line_id"] = pair_id
        row["fallback_note"] = "No direct AMap transit plan found; copied speed from opposite direction."
        if row.get("matsim_freespeed_mps"):
            distance = safe_float(target.get("line_table_distance_m"))
            freespeed = safe_float(row.get("matsim_freespeed_mps"))
            dwell = max(safe_int(target["station_count"]) - 2, 0) * dwell_time_per_intermediate_stop_s
            pure = distance / freespeed if freespeed > 0 and distance > 0 else 0
            row["dwell_time_s"] = round(dwell, 3)
            row["pure_running_time_s"] = round(pure, 3) if pure > 0 else ""
            row["vehicle_service_time_s"] = round(pure + dwell, 3) if pure > 0 else ""
            row["average_wait_time_subtracted_s"] = wait_time_s


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--amap-key", default=os.environ.get("AMAP_KEY") or os.environ.get("AMAP_API_KEY"))
    parser.add_argument("--lines-csv", type=Path, default=DEFAULT_LINES_CSV)
    parser.add_argument("--stops-csv", type=Path, default=DEFAULT_STOPS_CSV)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--summary-json", type=Path, default=DEFAULT_SUMMARY_JSON)
    parser.add_argument("--raw-jsonl", type=Path, default=DEFAULT_RAW_JSONL)
    parser.add_argument("--city", default="福州")
    parser.add_argument("--strategies", default="0,1,2,3,5")
    parser.add_argument("--wait-time-s", type=float, default=120.0)
    parser.add_argument("--dwell-time-s", type=float, default=30.0)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--sleep-s", type=float, default=0.2)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.amap_key:
        print("ERROR: provide --amap-key or set AMAP_KEY/AMAP_API_KEY.", file=sys.stderr)
        return 2

    records = load_line_records(args.lines_csv, args.stops_csv)
    records_by_id = {record["line_id"]: record for record in records}
    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]

    args.raw_jsonl.parent.mkdir(parents=True, exist_ok=True)
    selected_by_line: dict[str, dict[str, Any] | None] = {}
    attempts_by_line: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    with args.raw_jsonl.open("w", encoding="utf-8", newline="\n") as raw_writer:
        for target in records:
            selected, diagnostics = find_direct_plan(
                args.amap_key,
                target,
                strategies,
                args.city,
                args.timeout,
                args.sleep_s,
                raw_writer,
            )
            selected_by_line[target["line_id"]] = selected
            attempts_by_line[target["line_id"]] = diagnostics
            status = "direct_route_api" if selected else "no_direct_plan_found"
            rows.append(
                compute_speed_row(
                    target,
                    selected,
                    status,
                    wait_time_s=args.wait_time_s,
                    dwell_time_per_intermediate_stop_s=args.dwell_time_s,
                )
            )

    apply_reverse_direction_fallback(rows, records_by_id, args.wait_time_s, args.dwell_time_s)

    fieldnames = [
        "line_id",
        "line_name",
        "origin_station",
        "destination_station",
        "station_count",
        "stops_by_line_count",
        "direction_pair_line_id",
        "estimate_status",
        "fallback_source_line_id",
        "fallback_note",
        "selected_strategy",
        "selected_plan_rank",
        "selected_plan_segments_count",
        "selected_line_name",
        "selected_departure_stop",
        "selected_arrival_stop",
        "api_total_duration_s",
        "api_total_duration_min",
        "api_total_distance_m",
        "api_line_duration_s",
        "api_line_distance_m",
        "walking_duration_s",
        "walking_distance_m",
        "average_wait_time_subtracted_s",
        "vehicle_service_time_s",
        "dwell_time_s",
        "pure_running_time_s",
        "matsim_freespeed_mps",
        "speed_kmh",
        "with_dwell_average_speed_mps",
        "with_dwell_average_speed_kmh",
        "line_table_distance_m",
        "warning",
    ]
    write_csv(args.output_csv, rows, fieldnames)

    status_counts: dict[str, int] = defaultdict(int)
    warning_counts: dict[str, int] = defaultdict(int)
    speeds = []
    for row in rows:
        status_counts[str(row["estimate_status"])] += 1
        for warning in str(row.get("warning") or "").split(";"):
            if warning:
                warning_counts[warning] += 1
        if row.get("matsim_freespeed_mps") not in ("", None):
            speeds.append(safe_float(row["matsim_freespeed_mps"]))

    summary = {
        "created_by": "scripts/estimate_fuzhou_metro_speeds_from_amap_route.py",
        "inputs": {
            "lines_csv": str(args.lines_csv),
            "stops_csv": str(args.stops_csv),
        },
        "outputs": {
            "speed_estimates_csv": str(args.output_csv),
            "raw_responses_jsonl": str(args.raw_jsonl),
            "summary_json": str(args.summary_json),
        },
        "parameters": {
            "city": args.city,
            "strategies": strategies,
            "wait_time_s": args.wait_time_s,
            "dwell_time_per_intermediate_stop_s": args.dwell_time_s,
            "direct_plan_rule": "exact target line_name and exact origin/destination stop names; one busline segment only",
        },
        "counts": {
            "line_direction_records": len(rows),
            "status_counts": dict(status_counts),
            "warning_counts": dict(warning_counts),
        },
        "speed_summary_mps": {
            "min": round(min(speeds), 4) if speeds else None,
            "max": round(max(speeds), 4) if speeds else None,
            "mean": round(sum(speeds) / len(speeds), 4) if speeds else None,
        },
        "fallback_or_failed_lines": [
            {
                "line_id": row["line_id"],
                "line_name": row["line_name"],
                "estimate_status": row["estimate_status"],
                "fallback_source_line_id": row.get("fallback_source_line_id", ""),
                "warning": row.get("warning", ""),
            }
            for row in rows
            if row["estimate_status"] != "direct_route_api" or row.get("warning")
        ],
        "diagnostics_by_line": attempts_by_line,
    }
    args.summary_json.parent.mkdir(parents=True, exist_ok=True)
    args.summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")
    print(json.dumps(summary["counts"], ensure_ascii=False, indent=2))
    print(f"Wrote {args.output_csv}")
    print(f"Wrote {args.summary_json}")
    print(f"Wrote {args.raw_jsonl}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
