#!/usr/bin/env python3
"""Calibrate Hong Kong MATSim road speeds, lanes, and capacities.

The calibrated values are static supply parameters. Observed hourly speeds are
written as validation targets and are deliberately not imposed on MATSim links.
Only original TNM road links (``road_<ROUTE_ID>_<part>_[fr]``) are edited.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import re
import shutil
import statistics
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from shapely.geometry import LineString, MultiLineString, Point

try:
    import xlrd
except ImportError as exc:  # pragma: no cover - checked by CLI
    raise SystemExit(
        "xlrd>=2.0.1 is required for the 2024 ATC .xls workbooks. "
        "Install it in .venv_geo311 before running this script."
    ) from exc


DEFAULT_PROJECT_ROOT = Path(r"F:\Matsim\matsim-example-project")
ROAD_LINK_RE = re.compile(r"^road_(\d+)_(\d+)_([fr])$")
ROAD_TYPES = ("EX", "UT", "PD", "DD", "LD", "RT", "RR")
TYPE_NAMES = {
    "EXPRESSWAY": "EX",
    "URBAN TRUNK": "UT",
    "PRIMARY DISTRIBUTOR": "PD",
    "DISTRICT DISTRIBUTOR": "DD",
    "LOCAL DISTRIBUTOR": "LD",
    "RURAL TRUNK": "RT",
    "RURAL ROAD": "RR",
}
DEFAULT_LANES = {"EX": 3, "UT": 3, "PD": 2, "DD": 2, "LD": 1, "RT": 2, "RR": 1}
DEFAULT_CAPACITY = {
    "EX": 2000.0,
    "UT": 1800.0,
    "PD": 1700.0,
    "DD": 1500.0,
    "LD": 1200.0,
    "RT": 1600.0,
    "RR": 1200.0,
}
PEAK_HOUR_FACTOR = {
    "EX": 0.0768,
    "UT": 0.0704,
    "PD": 0.0715,
    "DD": 0.0740,
    "LD": 0.0753,
    "RT": 0.0801,
    "RR": 0.0795,
}
DIRECTION_ANGLE = {
    "E": 0.0,
    "EAST": 0.0,
    "EB": 0.0,
    "NE": 45.0,
    "NORTH EAST": 45.0,
    "N": 90.0,
    "NORTH": 90.0,
    "NB": 90.0,
    "NW": 135.0,
    "NORTH WEST": 135.0,
    "W": 180.0,
    "WEST": 180.0,
    "WB": 180.0,
    "SW": 225.0,
    "SOUTH WEST": 225.0,
    "S": 270.0,
    "SOUTH": 270.0,
    "SB": 270.0,
    "SE": 315.0,
    "SOUTH EAST": 315.0,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--update-formal-network",
        action="store_true",
        help="Back up and atomically replace the formal network after all Python QA passes.",
    )
    parser.add_argument("--skip-plots", action="store_true")
    return parser.parse_args()


def safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def safe_float(value: Any, default: float = math.nan) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def child_text(element: ET.Element, name: str) -> str:
    for child in element:
        if local_tag(child.tag) == name:
            return safe_text(child.text)
    return ""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_name(value: Any) -> str:
    text = safe_text(value).upper()
    text = re.split(r"\bNEAR\b|\s+-\s+(?:EAST|WEST|NORTH|SOUTH)", text)[0]
    text = re.sub(r"\b(?:ROAD|STREET|AVENUE|HIGHWAY|EXPRESSWAY|FLYOVER|BRIDGE)\b", " ", text)
    return re.sub(r"[^A-Z0-9]+", " ", text).strip()


def name_similarity(left: Any, right: Any) -> float:
    a, b = normalize_name(left), normalize_name(right)
    if not a or not b or a == "99" or b == "99":
        return 0.0
    if a in b or b in a:
        return min(len(a), len(b)) / max(len(a), len(b))
    return SequenceMatcher(None, a, b).ratio()


def angle_difference(left: float, right: float) -> float:
    return abs((left - right + 180.0) % 360.0 - 180.0)


def line_bearing(line: LineString | MultiLineString, point: Point) -> float:
    if isinstance(line, MultiLineString):
        parts = list(line.geoms)
        line = min(parts, key=lambda geom: geom.distance(point))
    position = line.project(point)
    start = line.interpolate(max(0.0, position - 10.0))
    end = line.interpolate(min(line.length, position + 10.0))
    return math.degrees(math.atan2(end.y - start.y, end.x - start.x)) % 360.0


def parse_speed_limit(value: Any) -> float:
    match = re.search(r"(\d+(?:\.\d+)?)", safe_text(value))
    return safe_float(match.group(1), 50.0) if match else 50.0


def road_type_code(value: Any) -> str:
    text = safe_text(value).upper()
    for label, code in TYPE_NAMES.items():
        if label in text:
            return code
    short = text[:2]
    return short if short in ROAD_TYPES else ""


def direction_code(value: Any) -> str:
    text = safe_text(value).upper().replace("-", " ")
    replacements = {
        "EAST BOUND": "EB",
        "WEST BOUND": "WB",
        "NORTH BOUND": "NB",
        "SOUTH BOUND": "SB",
        "EASTBOUND": "EB",
        "WESTBOUND": "WB",
        "NORTHBOUND": "NB",
        "SOUTHBOUND": "SB",
    }
    return replacements.get(text, text)


def choose_direction(line: LineString | MultiLineString, point: Point, observed: Any) -> tuple[str, float]:
    target = DIRECTION_ANGLE.get(direction_code(observed))
    forward = line_bearing(line, point)
    if target is None:
        return "f", math.nan
    fdiff = angle_difference(forward, target)
    rdiff = angle_difference((forward + 180.0) % 360.0, target)
    return ("f", fdiff) if fdiff <= rdiff else ("r", rdiff)


def load_roads(road_gdb: Path) -> tuple[gpd.GeoDataFrame, dict[int, float]]:
    roads = gpd.read_file(road_gdb, layer="CENTERLINE").to_crs("EPSG:2326")
    roads["route_id"] = pd.to_numeric(roads["ROUTE_ID"], errors="raise").astype(int)
    roads = roads.drop_duplicates("route_id").copy()
    limits = gpd.read_file(road_gdb, layer="SPEED_LIMIT")
    limits["route_id"] = pd.to_numeric(limits["ROAD_ROUTE_ID"], errors="coerce")
    limits["limit_kmh"] = limits["SPEED_LIMIT"].map(parse_speed_limit)
    # A route can contain several speed-limit sections. The lower value is the
    # conservative legal ceiling for the aggregated MATSim link.
    limit_map = (
        limits.dropna(subset=["route_id"])
        .groupby("route_id")["limit_kmh"]
        .min()
        .astype(float)
        .to_dict()
    )
    limit_map = {int(key): float(value) for key, value in limit_map.items()}
    roads["legal_speed_kmh"] = roads["route_id"].map(limit_map).fillna(50.0)
    return roads, limit_map


def rank_point_to_roads(
    points: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
    id_col: str,
    name_col: str | None,
    direction_col: str | None,
    max_distance: float = 60.0,
) -> pd.DataFrame:
    sindex = roads.sindex
    results: list[dict[str, Any]] = []
    for _, row in points.iterrows():
        point = row.geometry
        candidates = list(sindex.query(point.buffer(max_distance), predicate="intersects"))
        if not candidates:
            candidates = list(sindex.nearest(point, return_all=True)[1])
        ranked: list[tuple[float, int, float, float, str, float]] = []
        for index in candidates:
            road = roads.iloc[int(index)]
            distance = float(point.distance(road.geometry))
            if distance > max_distance and candidates:
                continue
            similarity = (
                max(
                    name_similarity(row.get(name_col), road.get("STREET_ENAME")),
                    name_similarity(row.get(name_col), road.get("ALIAS_ENAME")),
                )
                if name_col
                else 0.0
            )
            matched_direction, angle_diff = choose_direction(
                road.geometry, point, row.get(direction_col) if direction_col else ""
            )
            distance_score = max(0.0, 1.0 - distance / max_distance)
            direction_score = 0.5 if math.isnan(angle_diff) else max(0.0, 1.0 - angle_diff / 90.0)
            if name_col and direction_col:
                score = 0.50 * similarity + 0.30 * distance_score + 0.20 * direction_score
            elif name_col:
                score = 0.65 * similarity + 0.35 * distance_score
            else:
                score = 0.75 * distance_score + 0.25 * direction_score
            ranked.append(
                (score, int(index), distance, similarity, matched_direction, angle_diff)
            )
        if not ranked:
            results.append({id_col: row[id_col], "match_status": "unmatched"})
            continue
        score, index, distance, similarity, matched_direction, angle_diff = max(ranked)
        road = roads.iloc[index]
        accepted = score >= 0.45 or distance <= 15.0
        results.append(
            {
                id_col: row[id_col],
                "route_id": int(road.route_id) if accepted else math.nan,
                "matched_direction": matched_direction if accepted else "",
                "match_distance_m": distance,
                "name_similarity": similarity,
                "direction_difference_deg": angle_diff,
                "match_score": score,
                "match_status": "matched" if accepted else "manual_review",
                "matched_street_ename": safe_text(road.get("STREET_ENAME")),
                "matched_st_code": safe_float(road.get("ST_CODE")),
            }
        )
    return pd.DataFrame(results)


def parse_segment_speeds(
    xml_dir: Path,
    legal_speed: dict[int, float],
    known_routes: set[int],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    values: dict[tuple[int, int], list[float]] = defaultdict(list)
    route_ids_seen: set[int] = set()
    total = valid_flag = accepted = 0
    files = sorted(xml_dir.glob("*.xml"))
    for path in files:
        root = ET.parse(path).getroot()
        hour = int(child_text(root, "time").split(":", 1)[0])
        for segment in root.iter():
            if local_tag(segment.tag) != "segment":
                continue
            segment_id = child_text(segment, "segment_id")
            if not segment_id:
                continue
            total += 1
            route_id = int(float(segment_id))
            route_ids_seen.add(route_id)
            if child_text(segment, "valid").upper() != "Y":
                continue
            valid_flag += 1
            speed = safe_float(child_text(segment, "speed"))
            ceiling = min(130.0, 1.35 * legal_speed.get(route_id, 50.0))
            if route_id in known_routes and 0.0 < speed <= ceiling:
                values[(route_id, hour)].append(speed)
                accepted += 1
    route_rows: list[dict[str, Any]] = []
    hourly_rows: list[dict[str, Any]] = []
    for route_id in sorted(known_routes):
        route_values: list[float] = []
        for hour in range(24):
            samples = values.get((route_id, hour), [])
            route_values.extend(samples)
            if samples:
                hourly_rows.append(
                    {
                        "route_id": route_id,
                        "hour": hour,
                        "observations": len(samples),
                        "speed_q10_kmh": float(np.quantile(samples, 0.10)),
                        "speed_median_kmh": float(np.median(samples)),
                        "speed_q90_kmh": float(np.quantile(samples, 0.90)),
                    }
                )
        limit = legal_speed.get(route_id, 50.0)
        q85 = float(np.quantile(route_values, 0.85)) if route_values else math.nan
        reliable = len(route_values) >= 50
        freespeed = min(limit, max(q85, 0.85 * limit)) if reliable else limit
        route_rows.append(
            {
                "route_id": route_id,
                "legal_speed_kmh": limit,
                "speed_observations": len(route_values),
                "observed_speed_q85_kmh": q85,
                "freespeed_kmh": freespeed,
                "freespeed_source": "observed_q85_limited" if reliable else "legal_limit",
            }
        )
    route_df = pd.DataFrame(route_rows)
    hourly_df = pd.DataFrame(hourly_rows)
    if not hourly_df.empty:
        hourly_df = hourly_df.merge(
            route_df[["route_id", "freespeed_kmh"]], on="route_id", how="left"
        )
        hourly_df["observed_to_freespeed_ratio"] = (
            hourly_df["speed_median_kmh"] / hourly_df["freespeed_kmh"]
        )
        hourly_df["median_travel_time_s_per_km"] = (
            3600.0 / hourly_df["speed_median_kmh"].clip(lower=0.1)
        )
    summary = {
        "xml_files": len(files),
        "records": total,
        "valid_y_records": valid_flag,
        "accepted_records": accepted,
        "unique_segment_ids": len(route_ids_seen),
        "matched_2026_route_ids": len(route_ids_seen & known_routes),
        "unmatched_legacy_route_ids": sorted(route_ids_seen - known_routes),
    }
    return route_df, hourly_df, summary


def parse_raw_detectors(xml_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    lane_counts: dict[str, Counter[int]] = defaultdict(Counter)
    bins: dict[tuple[str, datetime], dict[str, float]] = defaultdict(
        lambda: {"seconds": 0.0, "volume": 0.0, "occupancy_sum": 0.0, "occupancy_n": 0.0}
    )
    detectors_seen: set[str] = set()
    ever_valid: set[str] = set()
    lane_records = valid_records = 0
    files = sorted(xml_dir.glob("*.xml"))
    for path in files:
        root = ET.parse(path).getroot()
        date_text = child_text(root, "date")
        for period in root.iter():
            if local_tag(period.tag) != "period":
                continue
            time_text = child_text(period, "period_from")
            timestamp = pd.Timestamp(f"{date_text} {time_text}").to_pydatetime()
            bin_time = timestamp.replace(minute=(timestamp.minute // 15) * 15, second=0)
            for detector in period.iter():
                if local_tag(detector.tag) != "detector":
                    continue
                detector_id = child_text(detector, "detector_id")
                if not detector_id:
                    continue
                detectors_seen.add(detector_id)
                lanes = [item for item in detector.iter() if local_tag(item.tag) == "lane"]
                lane_counts[detector_id][len(lanes)] += 1
                valid_lanes = [item for item in lanes if child_text(item, "valid").upper() == "Y"]
                lane_records += len(lanes)
                valid_records += len(valid_lanes)
                if valid_lanes:
                    ever_valid.add(detector_id)
                if not lanes or len(valid_lanes) / len(lanes) < 0.80:
                    continue
                volumes = [safe_float(child_text(item, "volume"), 0.0) for item in valid_lanes]
                occupancies = [
                    safe_float(child_text(item, "occupancy"))
                    for item in valid_lanes
                    if 0.0 <= safe_float(child_text(item, "occupancy")) <= 100.0
                ]
                record = bins[(detector_id, bin_time)]
                record["seconds"] += 30.0
                record["volume"] += sum(max(0.0, value) for value in volumes)
                record["occupancy_sum"] += sum(occupancies)
                record["occupancy_n"] += len(occupancies)
    detector_rows: list[dict[str, Any]] = []
    for detector_id, counts in lane_counts.items():
        modal_lanes, modal_periods = counts.most_common(1)[0]
        periods = sum(counts.values())
        detector_rows.append(
            {
                "detector_id": detector_id,
                "periods": periods,
                "modal_lanes": modal_lanes,
                "lane_mode_share": modal_periods / periods,
                "lane_count_reliable": periods >= 100 and modal_periods / periods >= 0.80,
            }
        )
    windows: list[dict[str, Any]] = []
    modal_map = {row["detector_id"]: row["modal_lanes"] for row in detector_rows}
    for (detector_id, bin_time), record in bins.items():
        lanes = max(1, modal_map.get(detector_id, 1))
        if record["seconds"] < 450.0 or record["occupancy_n"] <= 0:
            continue
        windows.append(
            {
                "detector_id": detector_id,
                "window_start": bin_time,
                "observed_seconds": record["seconds"],
                "flow_rate_vphpl": record["volume"] * 3600.0 / record["seconds"] / lanes,
                "occupancy_pct": record["occupancy_sum"] / record["occupancy_n"],
            }
        )
    detector_df = pd.DataFrame(detector_rows)
    window_df = pd.DataFrame(windows)
    summary = {
        "xml_files": len(files),
        "unique_detectors": len(detectors_seen),
        "ever_valid_detectors": len(ever_valid),
        "lane_records": lane_records,
        "valid_lane_records": valid_records,
        "valid_lane_record_share": valid_records / lane_records if lane_records else 0.0,
        "eligible_15min_windows": len(window_df),
    }
    return detector_df, window_df, summary


def estimate_detector_capacities(windows: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for detector_id, frame in windows.groupby("detector_id"):
        eligible = frame.loc[frame["occupancy_pct"].between(5.0, 40.0)].copy()
        if eligible.empty:
            rows.append(
                {
                    "detector_id": detector_id,
                    "capacity_windows": 0,
                    "occupancy_bins": 0,
                    "raw_capacity_vphpl": math.nan,
                }
            )
            continue
        eligible["occupancy_bin"] = pd.cut(
            eligible["occupancy_pct"],
            bins=np.arange(5.0, 45.0, 5.0),
            include_lowest=True,
            right=False,
        )
        by_bin = eligible.groupby("occupancy_bin", observed=True)["flow_rate_vphpl"].quantile(0.90)
        raw = float(by_bin.max()) if len(eligible) >= 20 and len(by_bin) >= 3 else math.nan
        rows.append(
            {
                "detector_id": detector_id,
                "capacity_windows": len(eligible),
                "occupancy_bins": len(by_bin),
                "raw_capacity_vphpl": float(np.clip(raw, 900.0, 2300.0))
                if math.isfinite(raw)
                else math.nan,
            }
        )
    return pd.DataFrame(rows)


def parse_annual_atc(atc_root: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for year in (2019, 2020, 2021, 2022, 2023, 2024):
        candidates = list(atc_root.rglob(f"GISDB{str(year)[-2:]}.xml"))
        if not candidates:
            continue
        root = ET.parse(candidates[0]).getroot()
        for record in root.iter():
            fields = {local_tag(child.tag): safe_text(child.text) for child in record}
            station = fields.get("ID", "")
            if not station or not station.isdigit():
                continue
            rows.append(
                {
                    "year": year,
                    "station_no": int(station),
                    "regional": fields.get("Regional", ""),
                    "station_type": fields.get("StationType", ""),
                    "road_type": road_type_code(fields.get("RoadType", "")),
                    "road_network": fields.get("RoadNetwork", ""),
                    "road_name": fields.get("RoadName", ""),
                    "road_from": fields.get("RoadFrom", ""),
                    "road_to": fields.get("RoadTo", ""),
                    "previous_aadt": safe_float(fields.get("PreAADT")),
                    "current_aadt": safe_float(fields.get("CurAADT")),
                }
            )
    return pd.DataFrame(rows)


def parse_atc_workbook(path: Path) -> list[dict[str, Any]]:
    workbook = xlrd.open_workbook(str(path), on_demand=True)
    sheet = workbook.sheet_by_index(0)
    station_no = int(path.stem[1:])
    road_type = road_type_code(sheet.cell_value(3, 17) if sheet.nrows > 3 else "")
    link_description = safe_text(sheet.cell_value(0, 36) if sheet.ncols > 36 else "")
    headers: list[int] = []
    for row in range(sheet.nrows):
        label = direction_code(sheet.cell_value(row, 1) if sheet.ncols > 1 else "")
        if label in {"EB", "WB", "NB", "SB"}:
            headers.append(row)
    results: list[dict[str, Any]] = []
    for index, start in enumerate(headers):
        end = headers[index + 1] if index + 1 < len(headers) else sheet.nrows
        labels: dict[str, int] = {}
        for row in range(start + 1, end):
            if sheet.ncols <= 1:
                continue
            label = safe_text(sheet.cell_value(row, 1)).upper()
            # Some one-way station sheets retain a second empty template block.
            # Keep the first populated directional block rather than allowing
            # the empty duplicate labels to overwrite it.
            if label and label not in labels:
                labels[label] = row
        aadt_row = next((row for label, row in labels.items() if "A.A.D.T" in label), None)
        am_row = next(
            (row for label, row in labels.items() if "ONE-WAY FLOW AT AM" in label), None
        )
        pm_row = next(
            (row for label, row in labels.items() if "ONE-WAY FLOW AT PM" in label), None
        )
        if aadt_row is None:
            continue
        results.append(
            {
                "station_no": station_no,
                "direction": direction_code(sheet.cell_value(start, 1)),
                "road_type": road_type,
                "link_description": link_description,
                "all_day_aadt": safe_float(sheet.cell_value(aadt_row, 30)),
                "weekday_aadt": safe_float(sheet.cell_value(aadt_row, 39)),
                "weekday_am_peak_flow": safe_float(sheet.cell_value(am_row, 39))
                if am_row is not None
                else math.nan,
                "weekday_pm_peak_flow": safe_float(sheet.cell_value(pm_row, 39))
                if pm_row is not None
                else math.nan,
            }
        )
    workbook.release_resources()
    return results


def parse_detailed_atc(atc_root: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    current_dirs = [
        path
        for path in atc_root.rglob("Current")
        if path.is_dir() and path.parent.name == "2024"
    ]
    if not current_dirs:
        raise FileNotFoundError("Could not locate the ATC 2024/Current directory")
    files = sorted(current_dirs[0].glob("S[0-9][0-9][0-9][0-9].xls"))
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in files:
        try:
            rows.extend(parse_atc_workbook(path))
        except Exception as exc:  # retained in QA, then hard-failed below
            errors.append(f"{path.name}: {exc}")
    frame = pd.DataFrame(rows)
    return frame, {
        "workbooks": len(files),
        "parsed_direction_rows": len(frame),
        "unique_stations": int(frame["station_no"].nunique()) if not frame.empty else 0,
        "parse_errors": errors,
    }


def add_atc_trends(annual: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    fit_years = {2019, 2022, 2023, 2024}
    for station, frame in annual.groupby("station_no"):
        fit = frame.loc[frame["year"].isin(fit_years) & (frame["current_aadt"] > 0)].copy()
        if len(fit) >= 3:
            slope = float(np.polyfit(fit["year"], np.log(fit["current_aadt"]), 1)[0])
            slope = float(np.clip(slope, -0.05, 0.05))
        else:
            slope = 0.0
        current = frame.loc[frame["year"] == 2024, "current_aadt"]
        aadt_2024 = float(current.iloc[0]) if len(current) else math.nan
        rows.append(
            {
                "station_no": int(station),
                "aadt_2024": aadt_2024,
                "annual_log_trend_2019_2024_excluding_2020_2021": slope,
                "projected_aadt_2026_for_qa": aadt_2024 * math.exp(2.0 * slope)
                if math.isfinite(aadt_2024)
                else math.nan,
            }
        )
    return pd.DataFrame(rows)


def classify_roads(
    roads: gpd.GeoDataFrame,
    atc_2024: pd.DataFrame,
    atc_matches: pd.DataFrame,
) -> pd.DataFrame:
    anchors = (
        atc_2024[["station_no", "road_type"]]
        .merge(atc_matches[["station_no", "route_id", "match_status"]], on="station_no")
        .query("match_status == 'matched' and road_type != ''")
    )
    direct = (
        anchors.groupby("route_id")["road_type"]
        .agg(lambda values: Counter(values).most_common(1)[0][0])
        .to_dict()
    )
    road_frame = roads[["route_id", "ST_CODE", "ROUTE_NUM", "legal_speed_kmh"]].copy()
    route_to_st = road_frame.set_index("route_id")["ST_CODE"].to_dict()
    st_types: dict[Any, str] = {}
    for st_code, group in anchors.assign(
        ST_CODE=anchors["route_id"].map(route_to_st)
    ).dropna(subset=["ST_CODE"]).groupby("ST_CODE"):
        counts = Counter(group["road_type"])
        if len(counts) == 1:
            st_types[st_code] = next(iter(counts))
    rows: list[dict[str, Any]] = []
    for _, road in road_frame.iterrows():
        route_id = int(road.route_id)
        if route_id in direct:
            code, source, confidence = direct[route_id], "atc_direct", "high"
        elif road.ST_CODE in st_types:
            code, source, confidence = st_types[road.ST_CODE], "st_code_corridor", "medium"
        elif road.legal_speed_kmh >= 80:
            code, source, confidence = "EX", "speed_fallback", "low"
        elif road.legal_speed_kmh >= 70:
            code, source, confidence = "UT", "speed_fallback", "low"
        elif safe_text(road.ROUTE_NUM):
            code, source, confidence = "PD", "route_number_fallback", "low"
        else:
            code, source, confidence = "LD", "default_fallback", "low"
        rows.append(
            {
                "route_id": route_id,
                "road_type": code,
                "road_type_source": source,
                "road_type_confidence": confidence,
            }
        )
    return pd.DataFrame(rows)


def build_route_direction_attributes(
    roads: gpd.GeoDataFrame,
    speed: pd.DataFrame,
    road_classes: pd.DataFrame,
    detector_locations: gpd.GeoDataFrame,
    detector_stats: pd.DataFrame,
    detector_capacity: pd.DataFrame,
    detector_matches: pd.DataFrame,
    atc_2024: pd.DataFrame,
    atc_matches: pd.DataFrame,
    details: pd.DataFrame,
    detail_matches: pd.DataFrame,
    trends: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    detectors = (
        detector_stats.merge(detector_capacity, on="detector_id", how="left")
        .merge(
            detector_matches.rename(columns={"AID_ID_Number": "detector_id"}),
            on="detector_id",
            how="left",
        )
        .merge(road_classes, on="route_id", how="left")
    )
    class_capacity = DEFAULT_CAPACITY.copy()
    for code, frame in detectors.groupby("road_type"):
        values = frame["raw_capacity_vphpl"].dropna()
        if code in ROAD_TYPES and len(values) >= 10:
            class_capacity[code] = float(np.median(values))
    detectors["class_prior_vphpl"] = detectors["road_type"].map(class_capacity)
    detectors["capacity_weight"] = np.minimum(
        0.8, detectors["capacity_windows"].fillna(0) / (detectors["capacity_windows"].fillna(0) + 40)
    )
    detectors["shrunk_capacity_vphpl"] = (
        detectors["capacity_weight"] * detectors["raw_capacity_vphpl"]
        + (1.0 - detectors["capacity_weight"]) * detectors["class_prior_vphpl"]
    )
    detectors.loc[detectors["raw_capacity_vphpl"].isna(), "shrunk_capacity_vphpl"] = detectors[
        "class_prior_vphpl"
    ]

    direct_detector: dict[tuple[int, str], dict[str, Any]] = {}
    for key, frame in detectors.dropna(subset=["route_id"]).groupby(
        ["route_id", "matched_direction"]
    ):
        reliable = frame.loc[frame["lane_count_reliable"]]
        direct_detector[(int(key[0]), str(key[1]))] = {
            "lanes": int(round(float(reliable["modal_lanes"].median())))
            if len(reliable)
            else math.nan,
            "capacity": float(frame["shrunk_capacity_vphpl"].median()),
            "detectors": len(frame),
        }

    detailed = details.merge(
        detail_matches[["station_no", "direction", "route_id", "matched_direction"]],
        on=["station_no", "direction"],
        how="left",
    )
    detailed = detailed.merge(road_classes, on="route_id", how="left")
    detailed["class_capacity_vphpl"] = detailed["road_type_y"].map(class_capacity)
    detailed["peak_flow"] = detailed[
        ["weekday_am_peak_flow", "weekday_pm_peak_flow"]
    ].max(axis=1)
    detailed["inferred_lanes"] = np.ceil(
        detailed["peak_flow"] / (0.90 * detailed["class_capacity_vphpl"])
    ).clip(1, 6)
    detail_map: dict[tuple[int, str], dict[str, Any]] = {}
    for key, frame in detailed.dropna(
        subset=["route_id", "inferred_lanes", "peak_flow"]
    ).groupby(
        ["route_id", "matched_direction"]
    ):
        detail_map[(int(key[0]), str(key[1]))] = {
            "lanes": int(frame["inferred_lanes"].max()),
            "peak_flow": float(frame["peak_flow"].max()),
            "station_no": ",".join(map(str, sorted(frame["station_no"].unique()))),
        }

    atc_routes = (
        atc_2024.merge(atc_matches[["station_no", "route_id", "match_status"]], on="station_no")
        .merge(trends, on="station_no", how="left")
        .merge(road_classes, on="route_id", how="left")
    )
    weekday_factor = (
        details.groupby("road_type")["weekday_aadt"].sum()
        / details.groupby("road_type")["all_day_aadt"].sum()
    ).replace([np.inf, -np.inf], np.nan).fillna(1.0).to_dict()
    atc_routes["directional_peak_estimate"] = (
        atc_routes["projected_aadt_2026_for_qa"]
        * atc_routes["road_type_y"].map(weekday_factor).fillna(1.0)
        * 0.5
        * atc_routes["road_type_y"].map(PEAK_HOUR_FACTOR).fillna(0.075)
    )
    atc_routes["inferred_lanes"] = np.ceil(
        atc_routes["directional_peak_estimate"]
        / (0.90 * atc_routes["road_type_y"].map(class_capacity))
    ).clip(1, 6)
    atc_map: dict[int, dict[str, Any]] = {}
    for route_id, frame in atc_routes.dropna(
        subset=["route_id", "inferred_lanes", "directional_peak_estimate"]
    ).groupby("route_id"):
        atc_map[int(route_id)] = {
            "lanes": int(frame["inferred_lanes"].max()),
            "peak_flow": float(frame["directional_peak_estimate"].max()),
        }

    anchor_lanes: dict[Any, list[int]] = defaultdict(list)
    anchor_caps: dict[Any, list[float]] = defaultdict(list)
    road_st = roads.set_index("route_id")["ST_CODE"].to_dict()
    for (route_id, _), item in direct_detector.items():
        st_code = road_st.get(route_id)
        if st_code is not None and math.isfinite(item["lanes"]):
            anchor_lanes[st_code].append(int(item["lanes"]))
            anchor_caps[st_code].append(float(item["capacity"]))
    for (route_id, _), item in detail_map.items():
        st_code = road_st.get(route_id)
        if st_code is not None:
            anchor_lanes[st_code].append(int(item["lanes"]))
    for route_id, item in atc_map.items():
        st_code = road_st.get(route_id)
        if st_code is not None:
            anchor_lanes[st_code].append(int(item["lanes"]))

    speed_map = speed.set_index("route_id").to_dict("index")
    class_map = road_classes.set_index("route_id").to_dict("index")
    rows: list[dict[str, Any]] = []
    anomalies: list[dict[str, Any]] = []
    for _, road in roads.iterrows():
        route_id = int(road.route_id)
        code = class_map[route_id]["road_type"]
        legal_directions = ["f", "r"] if int(road.TRAVEL_DIRECTION) == 1 else ["f"]
        for direction in legal_directions:
            key = (route_id, direction)
            st_code = road.ST_CODE
            peak_flow = math.nan
            if key in direct_detector and math.isfinite(direct_detector[key]["lanes"]):
                lanes = int(direct_detector[key]["lanes"])
                lane_source, confidence = "detector_modal", "high"
            elif key in detail_map:
                lanes = int(detail_map[key]["lanes"])
                peak_flow = detail_map[key]["peak_flow"]
                lane_source, confidence = "atc_direction_peak", "high"
            elif route_id in atc_map:
                lanes = int(atc_map[route_id]["lanes"])
                peak_flow = atc_map[route_id]["peak_flow"]
                lane_source, confidence = "atc_aadt_inferred", "medium"
            elif st_code in anchor_lanes:
                lanes = int(round(statistics.median(anchor_lanes[st_code])))
                lane_source, confidence = "st_code_corridor", "medium"
            else:
                lanes = DEFAULT_LANES[code]
                lane_source, confidence = "road_type_default", "low"
            if key in direct_detector:
                lane_capacity = direct_detector[key]["capacity"]
                capacity_source = "detector_fundamental_diagram"
            elif st_code in anchor_caps:
                lane_capacity = float(statistics.median(anchor_caps[st_code]))
                capacity_source = "st_code_detector_propagation"
            else:
                lane_capacity = class_capacity[code]
                capacity_source = "road_type_prior"
            lane_capacity = float(np.clip(lane_capacity, 900.0, 2300.0))
            while math.isfinite(peak_flow) and peak_flow > 0.95 * lanes * lane_capacity and lanes < 6:
                lanes += 1
                lane_source += "+vc_adjustment"
            vc = peak_flow / (lanes * lane_capacity) if math.isfinite(peak_flow) else math.nan
            if math.isfinite(vc) and vc > 0.95:
                anomalies.append(
                    {
                        "route_id": route_id,
                        "direction": direction,
                        "issue": "peak_flow_exceeds_95pct_capacity_after_six_lanes",
                        "peak_flow_vph": peak_flow,
                        "capacity_vph": lanes * lane_capacity,
                        "vc_ratio": vc,
                    }
                )
            rows.append(
                {
                    "route_id": route_id,
                    "direction": direction,
                    "street_ename": safe_text(road.STREET_ENAME),
                    "st_code": safe_float(road.ST_CODE),
                    "travel_direction": int(road.TRAVEL_DIRECTION),
                    "road_type": code,
                    "road_type_source": class_map[route_id]["road_type_source"],
                    "legal_speed_kmh": speed_map[route_id]["legal_speed_kmh"],
                    "freespeed_kmh": speed_map[route_id]["freespeed_kmh"],
                    "freespeed_mps": speed_map[route_id]["freespeed_kmh"] / 3.6,
                    "freespeed_source": speed_map[route_id]["freespeed_source"],
                    "speed_observations": speed_map[route_id]["speed_observations"],
                    "permlanes": int(np.clip(lanes, 1, 6)),
                    "lane_source": lane_source,
                    "capacity_confidence": confidence,
                    "capacity_per_lane_vph": lane_capacity,
                    "capacity_vph": int(np.clip(lanes, 1, 6)) * lane_capacity,
                    "capacity_source": capacity_source,
                    "atc_peak_flow_vph": peak_flow,
                    "atc_peak_vc_ratio": vc,
                }
            )
    params = {
        "road_type_capacity_priors_vphpl": class_capacity,
        "default_lanes": DEFAULT_LANES,
        "peak_hour_factors": PEAK_HOUR_FACTOR,
        "weekday_aadt_factors": weekday_factor,
        "anomalies": anomalies,
    }
    return pd.DataFrame(rows), params


def replace_attribute(line: str, attribute: str, value: float) -> str:
    pattern = rf'({attribute}=")[^"]*(")'
    return re.sub(pattern, rf"\g<1>{value:.6f}\g<2>", line, count=1)


def write_candidate_network(
    source: Path,
    destination: Path,
    attributes: pd.DataFrame,
) -> pd.DataFrame:
    lookup = attributes.set_index(["route_id", "direction"]).to_dict("index")
    records: list[dict[str, Any]] = []
    destination.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(source, "rt", encoding="utf-8") as reader, gzip.open(
        destination, "wt", encoding="utf-8", newline="\n"
    ) as writer:
        for line in reader:
            if "<link " not in line:
                writer.write(line)
                continue
            id_match = re.search(r'\bid="([^"]+)"', line)
            if not id_match:
                writer.write(line)
                continue
            link_id = id_match.group(1)
            road_match = ROAD_LINK_RE.match(link_id)
            if not road_match:
                writer.write(line)
                continue
            route_id, _, direction = road_match.groups()
            key = (int(route_id), direction)
            if key not in lookup:
                writer.write(line)
                continue
            item = lookup[key]
            old = {
                name: safe_float(re.search(rf'\b{name}="([^"]+)"', line).group(1))
                for name in ("freespeed", "capacity", "permlanes")
            }
            line = replace_attribute(line, "freespeed", item["freespeed_mps"])
            line = replace_attribute(line, "capacity", item["capacity_vph"])
            line = replace_attribute(line, "permlanes", item["permlanes"])
            records.append(
                {
                    "link_id": link_id,
                    "route_id": int(route_id),
                    "direction": direction,
                    "old_freespeed_mps": old["freespeed"],
                    "new_freespeed_mps": item["freespeed_mps"],
                    "old_capacity_vph": old["capacity"],
                    "new_capacity_vph": item["capacity_vph"],
                    "old_permlanes": old["permlanes"],
                    "new_permlanes": item["permlanes"],
                }
            )
            writer.write(line)
    return pd.DataFrame(records)


def network_signature(path: Path) -> dict[str, Any]:
    nodes: set[str] = set()
    links: dict[str, tuple[str, str, str]] = {}
    with gzip.open(path, "rb") as stream:
        for _, element in ET.iterparse(stream, events=("end",)):
            tag = local_tag(element.tag)
            if tag == "node":
                nodes.add(element.attrib["id"])
            elif tag == "link":
                links[element.attrib["id"]] = (
                    element.attrib["from"],
                    element.attrib["to"],
                    element.attrib.get("modes", ""),
                )
            element.clear()
    return {"nodes": nodes, "links": links}


def schedule_missing_links(schedule: Path, link_ids: set[str]) -> list[str]:
    missing: set[str] = set()
    with gzip.open(schedule, "rb") as stream:
        for _, element in ET.iterparse(stream, events=("end",)):
            if local_tag(element.tag) == "link" and "refId" in element.attrib:
                ref = element.attrib["refId"]
                if ref not in link_ids:
                    missing.add(ref)
            element.clear()
    return sorted(missing)


def validate_candidate(
    baseline: Path,
    candidate: Path,
    schedule: Path,
    link_attributes: pd.DataFrame,
) -> dict[str, Any]:
    old = network_signature(baseline)
    new = network_signature(candidate)
    topology_equal = old["nodes"] == new["nodes"] and old["links"] == new["links"]
    missing_refs = schedule_missing_links(schedule, set(new["links"]))
    numeric_ok = bool(
        np.isfinite(
            link_attributes[
                ["new_freespeed_mps", "new_capacity_vph", "new_permlanes"]
            ].to_numpy()
        ).all()
        and (link_attributes["new_freespeed_mps"] > 0).all()
        and link_attributes["new_permlanes"].between(1, 6).all()
    )
    result = {
        "baseline_nodes": len(old["nodes"]),
        "candidate_nodes": len(new["nodes"]),
        "baseline_links": len(old["links"]),
        "candidate_links": len(new["links"]),
        "node_link_topology_modes_equal": topology_equal,
        "changed_original_road_links": len(link_attributes),
        "missing_transit_route_link_references": missing_refs,
        "numeric_ranges_valid": numeric_ok,
        "passed": topology_equal and not missing_refs and numeric_ok,
    }
    return result


def make_plots(
    roads: gpd.GeoDataFrame,
    attributes: pd.DataFrame,
    link_attributes: pd.DataFrame,
    output_dir: Path,
) -> None:
    route_values = (
        attributes.groupby("route_id")
        .agg(
            freespeed_kmh=("freespeed_kmh", "median"),
            permlanes=("permlanes", "median"),
            capacity_vph=("capacity_vph", "median"),
            confidence=("capacity_confidence", lambda values: Counter(values).most_common(1)[0][0]),
        )
        .reset_index()
    )
    mapped = roads.merge(route_values, on="route_id", how="left")
    fig, axes = plt.subplots(2, 2, figsize=(16, 13), constrained_layout=True)
    for ax, column, title, cmap in [
        (axes[0, 0], "freespeed_kmh", "Free-flow speed (km/h)", "viridis"),
        (axes[0, 1], "permlanes", "Permanent lanes per direction", "plasma"),
        (axes[1, 0], "capacity_vph", "Directional capacity (veh/h)", "magma"),
    ]:
        mapped.plot(column=column, ax=ax, linewidth=0.45, cmap=cmap, legend=True)
        ax.set_title(title)
        ax.set_axis_off()
    colors = {"high": "#26734d", "medium": "#e6a700", "low": "#b7413e"}
    for confidence, frame in mapped.groupby("confidence", dropna=False):
        frame.plot(
            ax=axes[1, 1],
            color=colors.get(confidence, "#bdbdbd"),
            linewidth=0.45,
            label=str(confidence),
        )
    axes[1, 1].set_title("Capacity evidence confidence")
    axes[1, 1].legend(loc="lower left")
    axes[1, 1].set_axis_off()
    fig.suptitle("Hong Kong MATSim road supply calibration, 2026", fontsize=16)
    fig.savefig(output_dir / "road_speed_lane_capacity_maps.png", dpi=180)
    plt.close(fig)

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5), constrained_layout=True)
    pairs = [
        ("new_freespeed_mps", 3.6, "Free-flow speed (km/h)"),
        ("new_permlanes", 1.0, "Lanes per direction"),
        ("new_capacity_vph", 1.0, "Capacity (veh/h)"),
    ]
    for ax, (column, factor, title) in zip(axes, pairs):
        ax.hist(link_attributes[column] * factor, bins=35, color="#276678", alpha=0.85)
        ax.set_title(title)
        ax.set_ylabel("MATSim road links")
        ax.grid(alpha=0.2)
    fig.savefig(output_dir / "road_attribute_distributions.png", dpi=180)
    plt.close(fig)


def write_comparison_tables(
    roads: gpd.GeoDataFrame,
    attributes: pd.DataFrame,
    link_attributes: pd.DataFrame,
    data_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    old = (
        link_attributes.groupby(["route_id", "direction"])
        .agg(
            old_freespeed_mps=("old_freespeed_mps", "median"),
            old_capacity_vph=("old_capacity_vph", "median"),
            old_permlanes=("old_permlanes", "median"),
        )
        .reset_index()
    )
    comparison = attributes.merge(old, on=["route_id", "direction"], how="left")
    lengths = roads.set_index("route_id").geometry.length.to_dict()
    comparison["length_m"] = comparison["route_id"].map(lengths)
    comparison["old_freespeed_kmh"] = comparison["old_freespeed_mps"] * 3.6

    def aggregate(frame: pd.DataFrame, group: str) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        for label, part in frame.groupby(group, dropna=False):
            weights = part["length_m"].fillna(0.0).to_numpy()
            if weights.sum() <= 0:
                weights = np.ones(len(part))
            rows.append(
                {
                    group: label,
                    "route_directions": len(part),
                    "directional_length_km": float(part["length_m"].sum() / 1000.0),
                    "old_freespeed_kmh_length_weighted": float(
                        np.average(part["old_freespeed_kmh"], weights=weights)
                    ),
                    "new_freespeed_kmh_length_weighted": float(
                        np.average(part["freespeed_kmh"], weights=weights)
                    ),
                    "old_lanes_length_weighted": float(
                        np.average(part["old_permlanes"], weights=weights)
                    ),
                    "new_lanes_length_weighted": float(
                        np.average(part["permlanes"], weights=weights)
                    ),
                    "old_capacity_vph_length_weighted": float(
                        np.average(part["old_capacity_vph"], weights=weights)
                    ),
                    "new_capacity_vph_length_weighted": float(
                        np.average(part["capacity_vph"], weights=weights)
                    ),
                    "high_confidence_share": float(
                        np.average(part["capacity_confidence"].eq("high"), weights=weights)
                    ),
                }
            )
        return pd.DataFrame(rows)

    by_type = aggregate(comparison, "road_type")
    by_type.to_csv(output_dir / "road_type_attribute_comparison.csv", index=False)

    district_path = (
        data_root
        / "boundary"
        / "hongkong"
        / "2021_Population_Census_Statistics_and_Boundar_SHP"
        / "DC_21C_converted.shp"
    )
    district_table = pd.DataFrame()
    if district_path.exists():
        districts = gpd.read_file(district_path)[["dc_eng", "geometry"]].to_crs(roads.crs)
        points = roads[["route_id", "geometry"]].copy()
        points.geometry = points.geometry.representative_point()
        joined = gpd.sjoin(points, districts, how="left", predicate="within").drop(
            columns=["index_right"]
        )
        missing = joined["dc_eng"].isna()
        if missing.any():
            nearest = gpd.sjoin_nearest(
                points.loc[missing], districts, how="left", max_distance=1000.0
            ).drop(columns=["index_right"])
            joined.loc[missing, "dc_eng"] = nearest.set_index("route_id").loc[
                joined.loc[missing, "route_id"], "dc_eng"
            ].to_numpy()
        joined["dc_eng"] = joined["dc_eng"].fillna("outside_dc_boundary")
        comparison = comparison.merge(
            joined[["route_id", "dc_eng"]].drop_duplicates("route_id"),
            on="route_id",
            how="left",
        )
        district_table = aggregate(comparison, "dc_eng")
        district_table.to_csv(
            output_dir / "district_road_attribute_comparison.csv", index=False
        )

    peak = comparison.loc[comparison["atc_peak_flow_vph"].notna()].copy()
    peak["capacity_minus_peak_vph"] = (
        peak["capacity_vph"] - peak["atc_peak_flow_vph"]
    )
    peak["over_capacity_95pct"] = (
        peak["atc_peak_flow_vph"] > 0.95 * peak["capacity_vph"]
    )
    peak.to_csv(output_dir / "atc_peak_capacity_validation.csv", index=False)
    wape = (
        float(
            np.abs(peak["capacity_vph"] - peak["atc_peak_flow_vph"]).sum()
            / peak["atc_peak_flow_vph"].sum()
        )
        if len(peak) and peak["atc_peak_flow_vph"].sum() > 0
        else math.nan
    )
    return {
        "road_type_groups": len(by_type),
        "official_district_groups": int(
            district_table["dc_eng"].ne("outside_dc_boundary").sum()
        )
        if not district_table.empty
        else 0,
        "outside_district_route_directions": int(
            comparison["dc_eng"].eq("outside_dc_boundary").sum()
        )
        if "dc_eng" in comparison
        else 0,
        "atc_supported_route_directions": len(peak),
        "atc_peak_capacity_headroom_wape": wape,
        "atc_peak_over_95pct_capacity": int(peak["over_capacity_95pct"].sum()),
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    args = parse_args()
    project_root = args.project_root.resolve()
    data_root = project_root / "data"
    transit_root = data_root / "transit" / "hongkong"
    traffic_root = transit_root / "TrafficFlow"
    day_root = traffic_root / "TrafficDataofRoads20260722"
    atc_root = traffic_root / "ATC" / "AnnualTrafficCensusTrafficData_202602"
    road_gdb = transit_root / "RdNet_IRNP.gdb"
    atc_gdb = traffic_root / "ATC_IRNP.gdb"
    supply_dir = transit_root / "processed" / "matsim_road_pt_supply_2026_typical_weekday"
    formal_network = supply_dir / "network.xml.gz"
    schedule = supply_dir / "transitSchedule.xml.gz"
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else transit_root / "processed" / "road_speed_capacity_2026_v1"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "qa").mkdir(exist_ok=True)

    roads, legal_speed = load_roads(road_gdb)
    known_routes = set(roads["route_id"])
    speed, hourly_speed, speed_summary = parse_segment_speeds(
        day_root / "TrafficSpeedsRoadNetworkSegments20260722",
        legal_speed,
        known_routes,
    )

    detector_csv = next((day_root / "LocationsTrafficDetectors").glob("*.csv"))
    detector_locations = pd.read_csv(detector_csv)
    detector_locations["Easting"] = pd.to_numeric(detector_locations["Easting"])
    detector_locations["Northing"] = pd.to_numeric(detector_locations["Northing"])
    detector_locations = gpd.GeoDataFrame(
        detector_locations,
        geometry=gpd.points_from_xy(detector_locations["Easting"], detector_locations["Northing"]),
        crs="EPSG:2326",
    )
    detector_matches = rank_point_to_roads(
        detector_locations,
        roads,
        "AID_ID_Number",
        "Road_EN",
        "Direction",
    )
    detector_stats, detector_windows, detector_summary = parse_raw_detectors(
        day_root / "TrafficSpeedVolumeRoadOccupancyRaw20260722"
    )
    detector_capacity = estimate_detector_capacities(detector_windows)

    annual = parse_annual_atc(atc_root)
    atc_2024 = annual.loc[annual["year"] == 2024].copy()
    trends = add_atc_trends(annual)
    atc_points = gpd.read_file(atc_gdb, layer="ATC_STATION_PT").to_crs("EPSG:2326")
    atc_points["station_no"] = pd.to_numeric(atc_points["ATC_STATION_NO"]).astype(int)
    atc_points = atc_points.merge(
        atc_2024[["station_no", "road_name"]], on="station_no", how="left"
    )
    atc_matches = rank_point_to_roads(
        atc_points, roads, "station_no", "road_name", None
    )
    details, detail_summary = parse_detailed_atc(atc_root)
    station_lines = gpd.read_file(atc_gdb, layer="ATC_STATION_LINE").to_crs("EPSG:2326")
    station_lines["station_no"] = pd.to_numeric(station_lines["ATC_STATION_NO"]).astype(int)
    station_lines["direction"] = station_lines["DIRECTION"].map(direction_code)
    station_line_points = station_lines.copy()
    station_line_points.geometry = station_lines.geometry.interpolate(
        0.5, normalized=True
    )
    detail_matches = rank_point_to_roads(
        station_line_points,
        roads,
        "FEATUREID",
        None,
        "DIRECTION",
    )
    detail_matches = station_lines[["FEATUREID", "station_no", "direction"]].merge(
        detail_matches, on="FEATUREID", how="left"
    )
    missing_detail = details.merge(
        detail_matches[["station_no", "direction"]],
        on=["station_no", "direction"],
        how="left",
        indicator=True,
    ).query("_merge == 'left_only'")
    if len(missing_detail):
        fallback = missing_detail[["station_no", "direction"]].merge(
            atc_matches[["station_no", "route_id", "matched_direction", "match_status"]],
            on="station_no",
            how="left",
        )
        detail_matches = pd.concat(
            [
                detail_matches,
                fallback.assign(FEATUREID=math.nan, match_status="point_fallback"),
            ],
            ignore_index=True,
        )

    road_classes = classify_roads(roads, atc_2024, atc_matches)
    attributes, capacity_params = build_route_direction_attributes(
        roads,
        speed,
        road_classes,
        detector_locations,
        detector_stats,
        detector_capacity,
        detector_matches,
        atc_2024,
        atc_matches,
        details,
        detail_matches,
        trends,
    )

    candidate = output_dir / "network_calibrated_candidate.xml.gz"
    link_attributes = write_candidate_network(formal_network, candidate, attributes)
    validation = validate_candidate(formal_network, candidate, schedule, link_attributes)

    annual.merge(trends, on="station_no", how="left").to_csv(
        output_dir / "annual_atc_station_summary_2019_2024.csv", index=False
    )
    atc_matches.to_csv(output_dir / "atc_station_route_crosswalk.csv", index=False)
    details.to_csv(output_dir / "atc_directional_details_2024.csv", index=False)
    detail_matches.to_csv(output_dir / "atc_direction_route_crosswalk.csv", index=False)
    detector_matches.to_csv(output_dir / "traffic_detector_route_crosswalk.csv", index=False)
    detector_stats.merge(detector_capacity, on="detector_id", how="left").to_csv(
        output_dir / "traffic_detector_lane_capacity_estimates.csv", index=False
    )
    detector_windows.to_csv(output_dir / "traffic_detector_15min_windows.csv", index=False)
    hourly_speed.to_csv(output_dir / "hourly_observed_speed_profiles.csv", index=False)
    attributes.to_csv(output_dir / "road_route_direction_attributes.csv", index=False)
    link_attributes.to_csv(output_dir / "matsim_link_attributes.csv", index=False)
    pd.DataFrame(capacity_params["anomalies"]).to_csv(
        output_dir / "qa" / "capacity_anomalies.csv", index=False
    )
    write_json(output_dir / "capacity_model_parameters.json", capacity_params)
    write_json(output_dir / "qa" / "network_candidate_validation.json", validation)

    detail_aadt = details.groupby("station_no")["all_day_aadt"].sum()
    xml_aadt = atc_2024.set_index("station_no")["current_aadt"]
    common = detail_aadt.index.intersection(xml_aadt.index)
    aadt_error = detail_aadt.loc[common] - xml_aadt.loc[common]
    aadt_conflicts = [
        {
            "station_no": int(station),
            "detailed_workbook_aadt": float(detail_aadt.loc[station]),
            "annual_xml_aadt": float(xml_aadt.loc[station]),
            "difference": float(aadt_error.loc[station]),
        }
        for station in aadt_error.index[aadt_error.abs() > 1e-6]
    ]
    aadt_max_error = float(aadt_error.abs().max())
    input_qa = {
        "atc_2024_records": len(atc_2024),
        "atc_2024_unique_stations": int(atc_2024["station_no"].nunique()),
        "atc_point_features": len(atc_points),
        "atc_point_unique_stations": int(atc_points["station_no"].nunique()),
        "detailed_atc": detail_summary,
        "detailed_aadt_sum_max_abs_error": aadt_max_error,
        "detailed_vs_annual_aadt_source_conflicts": aadt_conflicts,
        "segment_speeds": speed_summary,
        "raw_detectors": detector_summary,
        "detector_location_records": len(detector_locations),
        "detector_route_match_rate": float(
            detector_matches["route_id"].notna().mean()
        ),
        "atc_route_match_rate": float(atc_matches["route_id"].notna().mean()),
    }
    hard_input_pass = (
        len(atc_2024) == 1694
        and atc_2024["station_no"].nunique() == 1694
        and len(atc_points) == 1694
        and detail_summary["workbooks"] == 191
        and detail_summary["unique_stations"] == 191
        and not detail_summary["parse_errors"]
        # The official 2024 sources contain one known station-level revision
        # conflict (S2405). It is preserved in the audit and not silently
        # reconciled; all other detailed stations must balance exactly.
        and len(aadt_conflicts) <= 1
        and aadt_max_error <= 100.0
        and detector_summary["unique_detectors"] == 760
        and detector_summary["ever_valid_detectors"] == 749
        and speed_summary["matched_2026_route_ids"] == 4505
    )
    input_qa["passed"] = hard_input_pass
    write_json(output_dir / "qa" / "input_data_validation.json", input_qa)

    if not args.skip_plots:
        make_plots(roads, attributes, link_attributes, output_dir)
    comparison_summary = write_comparison_tables(
        roads, attributes, link_attributes, data_root, output_dir
    )

    summary = {
        "created_at": datetime.now().astimezone().isoformat(),
        "project_root": str(project_root),
        "formal_network": str(formal_network),
        "candidate_network": str(candidate),
        "baseline_sha256": sha256(formal_network),
        "candidate_sha256": sha256(candidate),
        "route_direction_records": len(attributes),
        "changed_original_road_links": len(link_attributes),
        "freespeed_kmh": attributes["freespeed_kmh"].describe().to_dict(),
        "permlanes": attributes["permlanes"].value_counts().sort_index().to_dict(),
        "capacity_vph": attributes["capacity_vph"].describe().to_dict(),
        "lane_source": attributes["lane_source"].value_counts().to_dict(),
        "capacity_source": attributes["capacity_source"].value_counts().to_dict(),
        "confidence": attributes["capacity_confidence"].value_counts().to_dict(),
        "input_qa_passed": hard_input_pass,
        "network_qa_passed": validation["passed"],
        "formal_network_updated": False,
        "capacity_units": "vehicles/hour/direction",
        "freespeed_units": "m/s in MATSim XML; km/h in audit tables",
        "observed_hourly_speed_usage": "validation_target_only",
        "comparison_qa": comparison_summary,
    }

    if args.update_formal_network:
        if not hard_input_pass or not validation["passed"]:
            raise RuntimeError("QA failed; the formal MATSim network was not modified.")
        backup = supply_dir / "network_uniform_capacity_baseline.xml.gz"
        if not backup.exists():
            shutil.copy2(formal_network, backup)
        backup_hash = sha256(backup)
        with tempfile.NamedTemporaryFile(
            dir=supply_dir, prefix="network_calibrated_", suffix=".xml.gz", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
        shutil.copy2(candidate, temporary_path)
        os.replace(temporary_path, formal_network)
        summary["formal_network_updated"] = True
        summary["backup_network"] = str(backup)
        summary["backup_sha256"] = backup_hash
        summary["formal_network_sha256_after_update"] = sha256(formal_network)
        (supply_dir / "network_uniform_capacity_baseline.sha256").write_text(
            f"{backup_hash}  {backup.name}\n", encoding="ascii"
        )
        (supply_dir / "network.xml.gz.sha256").write_text(
            f"{summary['formal_network_sha256_after_update']}  network.xml.gz\n",
            encoding="ascii",
        )

    write_json(output_dir / "road_speed_capacity_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
