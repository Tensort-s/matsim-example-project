#!/usr/bin/env python3
"""Estimate MATSim-ready MTR/LRT running, dwell, and stop offset times.

The estimator combines three synchronized next-train snapshots with ordered
route stops and map-matched rail-link distances. Snapshot times constrain
adjacent-station elapsed times; a line-speed model fills and stabilizes sparse
or rounded observations. Dwell times remain explicit assumptions because the
public APIs do not uniquely separate motion and platform dwell.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_TRANSIT_ROOT = PROJECT_ROOT / "data/transit/hongkong"
DEFAULT_SNAPSHOTS = [
    DEFAULT_TRANSIT_ROOT / "API_Supplements/realtime_snapshots/20260720T102416Z",
    DEFAULT_TRANSIT_ROOT / "API_Supplements/realtime_snapshots/20260722T034716Z",
    DEFAULT_TRANSIT_ROOT / "API_Supplements/realtime_snapshots/20260722T055352Z",
]

INITIAL_SPEED_KMH = {
    "AEL": 65.0,
    "DRL": 30.0,
    "EAL": 45.0,
    "ISL": 34.0,
    "KTL": 34.0,
    "SIL": 35.0,
    "TCL": 47.0,
    "TKL": 36.0,
    "TML": 43.0,
    "TWL": 35.0,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transit-root", type=Path, default=DEFAULT_TRANSIT_ROOT)
    parser.add_argument("--snapshot-dir", action="append", type=Path, dest="snapshot_dirs")
    parser.add_argument("--timetable-dir", type=Path)
    parser.add_argument("--mapmatching-dir", type=Path)
    parser.add_argument("--mtr-stops", type=Path)
    parser.add_argument("--lrt-stops", type=Path)
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def normalize_id(value: Any) -> str:
    return re.sub(r"\.0$", "", str(value).strip())


def normalize_name(value: Any) -> str:
    text = str(value).strip().lower()
    text = re.sub(r"\([^)]*\)", "", text)
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", text)


def format_seconds(seconds: int | float) -> str:
    value = int(round(float(seconds)))
    hour, remainder = divmod(value, 3600)
    minute, second = divmod(remainder, 60)
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_manifest(output_dir: Path) -> None:
    manifest = output_dir / "SHA256SUMS.txt"
    rows = []
    for path in sorted(output_dir.rglob("*")):
        if path.is_file() and path != manifest:
            rows.append(f"{file_sha256(path)}  {path.relative_to(output_dir).as_posix()}")
    manifest.write_text("\n".join(rows) + "\n", encoding="ascii")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    order = np.argsort(values)
    sorted_values = values[order]
    sorted_weights = weights[order]
    cutoff = sorted_weights.sum() / 2.0
    return float(sorted_values[np.searchsorted(np.cumsum(sorted_weights), cutoff)])


def route_link_position(index: int, lengths: np.ndarray) -> float:
    if not len(lengths):
        return math.nan
    cycle, remainder = divmod(max(0, int(index)), len(lengths))
    starts = np.concatenate(([0.0], np.cumsum(lengths)))
    return float(cycle * starts[-1] + starts[remainder])


def build_distance_lookup(
    route_links: pd.DataFrame,
    stop_snaps: pd.DataFrame,
    mtr_stops: pd.DataFrame,
    lrt_stops: pd.DataFrame,
) -> tuple[dict[tuple[str, str, str, str], float], pd.DataFrame]:
    source_groups: dict[str, pd.DataFrame] = {}
    for (line, direction), group in mtr_stops.groupby(["Line Code", "Direction"], sort=False):
        source_groups[f"mtr_{line}_{direction}"] = group.sort_values("Sequence")
    for (line, direction), group in lrt_stops.groupby(["Line Code", "Direction"], sort=False):
        source_groups[f"lrt_{normalize_id(line)}_{normalize_id(direction)}"] = group.sort_values("Sequence")

    candidates: dict[tuple[str, str, str, str], list[float]] = defaultdict(list)
    audit_rows: list[dict[str, Any]] = []
    rail_snaps = stop_snaps[stop_snaps["mode"].isin(["mtr", "lrt"])]
    for route_key, snap_group in rail_snaps.groupby("route_key", sort=False):
        official = source_groups.get(str(route_key))
        links = route_links[route_links["route_key"].eq(route_key)].sort_values("sequence")
        snaps = snap_group.sort_values("stop_seq")
        if official is None or len(official) != len(snaps) or len(links) == 0:
            audit_rows.append(
                {
                    "route_key": route_key,
                    "status": "source_or_count_mismatch",
                    "official_stop_count": 0 if official is None else len(official),
                    "mapmatched_stop_count": len(snaps),
                    "segment_count": 0,
                }
            )
            continue
        mode = str(snaps.iloc[0]["mode"])
        line_code = normalize_id(official.iloc[0]["Line Code"])
        code_column = "Station Code" if mode == "mtr" else "Stop Code"
        codes = official[code_column].map(normalize_id).tolist()
        lengths = pd.to_numeric(links["length_m"], errors="coerce").fillna(0).to_numpy(float)
        positions = [
            route_link_position(index, lengths)
            for index in pd.to_numeric(snaps["route_link_index_unwrapped"], errors="coerce").fillna(0)
        ]
        segment_count = 0
        for from_code, to_code, start, end in zip(codes[:-1], codes[1:], positions[:-1], positions[1:]):
            distance = end - start
            if math.isfinite(distance) and 30 <= distance <= 30000:
                candidates[(mode, line_code, from_code, to_code)].append(distance)
                segment_count += 1
        audit_rows.append(
            {
                "route_key": route_key,
                "status": "aligned",
                "official_stop_count": len(official),
                "mapmatched_stop_count": len(snaps),
                "segment_count": segment_count,
            }
        )
    lookup = {key: float(np.median(values)) for key, values in candidates.items()}
    return lookup, pd.DataFrame(audit_rows)


def build_station_coordinate_lookup(
    stop_snaps: pd.DataFrame,
    mtr_stops: pd.DataFrame,
    lrt_stops: pd.DataFrame,
    target_stops: pd.DataFrame,
) -> tuple[dict[tuple[str, str], tuple[float, float]], pd.DataFrame]:
    candidates: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
    audit_rows: list[dict[str, Any]] = []
    rail_snaps = stop_snaps[stop_snaps["mode"].isin(["mtr", "lrt"])]
    for route_key, snap_group in rail_snaps.groupby("route_key", sort=False):
        snaps = snap_group.sort_values("stop_seq")
        mode = str(snaps.iloc[0]["mode"])
        line_code = normalize_id(snaps.iloc[0]["route_id"])
        possible = target_stops[
            target_stops["mode"].eq(mode)
            & target_stops["line_code"].map(normalize_id).eq(line_code)
        ]
        scored: list[tuple[float, str, pd.DataFrame]] = []
        map_names = [normalize_name(value) for value in snaps["stop_name_zh"]]
        for target_route, target_group in possible.groupby("route_variant_id", sort=False):
            targets = target_group.sort_values("stop_sequence")
            if len(targets) != len(snaps):
                continue
            target_names = [normalize_name(value) for value in targets["stop_name_zh"]]
            similarities = [
                SequenceMatcher(None, source_name, target_name).ratio()
                for source_name, target_name in zip(map_names, target_names)
            ]
            scored.append((float(np.mean(similarities)), str(target_route), targets))
        if not scored:
            continue
        score, target_route, targets = max(scored, key=lambda value: value[0])
        if score < 0.35:
            continue
        for target_row, snap_row in zip(targets.itertuples(index=False), snaps.itertuples(index=False)):
            candidates[(mode, normalize_id(target_row.stop_code))].append(
                (float(snap_row.x), float(snap_row.y))
            )
        audit_rows.append(
            {
                "mode": mode,
                "stop_code": f"__route__{route_key}",
                "coordinate_available": True,
                "coordinate_observation_count": len(snaps),
                "x": math.nan,
                "y": math.nan,
                "matched_target_route": target_route,
                "route_sequence_name_similarity": score,
            }
        )

    lookup = {
        key: (
            float(np.median([value[0] for value in values])),
            float(np.median([value[1] for value in values])),
        )
        for key, values in candidates.items()
    }
    required = target_stops[["mode", "stop_code"]].drop_duplicates()
    for row in required.itertuples(index=False):
        key = (str(row.mode), normalize_id(row.stop_code))
        audit_rows.append(
            {
                "mode": key[0],
                "stop_code": key[1],
                "coordinate_available": key in lookup,
                "coordinate_observation_count": len(candidates.get(key, [])),
                "x": lookup.get(key, (math.nan, math.nan))[0],
                "y": lookup.get(key, (math.nan, math.nan))[1],
                "matched_target_route": "",
                "route_sequence_name_similarity": math.nan,
            }
        )
    return lookup, pd.DataFrame(audit_rows)


def build_reliable_segment_distances(
    patterns: pd.DataFrame,
    route_stops: pd.DataFrame,
    link_distances: dict[tuple[str, str, str, str], float],
    coordinates: dict[tuple[str, str], tuple[float, float]],
) -> tuple[
    dict[tuple[str, str, str, str], float],
    dict[tuple[str, str, str, str], str],
    pd.DataFrame,
]:
    pairs: dict[tuple[str, str, str, str], float] = {}
    for pattern in patterns.itertuples(index=False):
        stops = route_stops[route_stops["route_variant_id"].eq(pattern.route_variant_id)].sort_values(
            "stop_sequence"
        )
        for from_stop, to_stop in zip(stops.iloc[:-1].itertuples(), stops.iloc[1:].itertuples()):
            from_code = normalize_id(from_stop.stop_code)
            to_code = normalize_id(to_stop.stop_code)
            key = (pattern.mode, normalize_id(pattern.line_code), from_code, to_code)
            first = coordinates.get((pattern.mode, from_code))
            second = coordinates.get((pattern.mode, to_code))
            if first and second:
                pairs[key] = float(math.hypot(second[0] - first[0], second[1] - first[1]))

    ratios: dict[tuple[str, str], list[float]] = defaultdict(list)
    for key, straight in pairs.items():
        link_distance = link_distances.get(key)
        if straight >= 50 and link_distance is not None:
            ratio = link_distance / straight
            if 1.0 <= ratio <= (1.45 if key[0] == "mtr" else 1.65):
                ratios[(key[0], key[1])].append(ratio)

    parameter_rows = []
    circuity: dict[tuple[str, str], float] = {}
    line_keys = patterns[["mode", "line_code"]].drop_duplicates()
    for row in line_keys.itertuples(index=False):
        key = (str(row.mode), normalize_id(row.line_code))
        values = ratios.get(key, [])
        default = 1.08 if key[0] == "mtr" else 1.12
        lower, upper = ((1.02, 1.25) if key[0] == "mtr" else (1.03, 1.35))
        factor = float(np.clip(np.median(values), lower, upper)) if values else default
        circuity[key] = factor
        parameter_rows.append(
            {
                "mode": key[0],
                "line_code": key[1],
                "circuity_factor": factor,
                "reliable_link_segment_samples": len(values),
                "circuity_source": "reliable_link_ratio_median" if values else "mode_prior",
            }
        )

    final: dict[tuple[str, str, str, str], float] = {}
    sources: dict[tuple[str, str, str, str], str] = {}
    for key, straight in pairs.items():
        link_distance = link_distances.get(key)
        maximum_ratio = 1.45 if key[0] == "mtr" else 1.65
        if link_distance is not None and straight >= 50 and 1.0 <= link_distance / straight <= maximum_ratio:
            final[key] = link_distance
            sources[key] = "mapmatched_route_links_qa_passed"
        else:
            final[key] = straight * circuity[(key[0], key[1])]
            sources[key] = "station_coordinates_line_circuity"
    return final, sources, pd.DataFrame(parameter_rows)


def prepare_snapshot(snapshot_dir: Path) -> dict[str, Any]:
    mtr_rows = read_jsonl(snapshot_dir / "mtr_next_train.jsonl")
    lrt_rows = read_jsonl(snapshot_dir / "light_rail_next_train.jsonl")
    first = mtr_rows[0]["response"]
    local_text = first.get("sys_time") or first.get("curr_time")
    local_dt = datetime.strptime(local_text, "%Y-%m-%d %H:%M:%S")
    return {
        "snapshot_id": snapshot_dir.name,
        "captured_local": local_text,
        "mtr": {
            (str(row["request_parameters"]["line"]), str(row["request_parameters"]["sta"])): row
            for row in mtr_rows
        },
        "lrt": {normalize_id(row["request_parameters"]["station_id"]): row for row in lrt_rows},
        "local_date": local_dt.date(),
    }


def mtr_prediction_times(
    snapshot: dict[str, Any], line_code: str, station_code: str, destination_code: str
) -> list[int]:
    record = snapshot["mtr"].get((line_code, station_code))
    if not record:
        return []
    values: list[int] = []
    for data in (record["response"].get("data") or {}).values():
        for direction in ("UP", "DOWN"):
            for train in data.get(direction) or []:
                if str(train.get("dest")) != destination_code or str(train.get("valid")) != "Y":
                    continue
                try:
                    predicted = datetime.strptime(str(train["time"]), "%Y-%m-%d %H:%M:%S")
                except (KeyError, TypeError, ValueError):
                    continue
                midnight = datetime.combine(snapshot["local_date"], datetime.min.time())
                values.append(int((predicted - midnight).total_seconds()))
    return sorted(set(values))


def lrt_prediction_times(
    snapshot: dict[str, Any], station_id: str, route_no: str, destination_name: str
) -> list[int]:
    record = snapshot["lrt"].get(normalize_id(station_id))
    if not record:
        return []
    response = record["response"]
    system_text = response.get("system_time") or snapshot["captured_local"]
    system_dt = datetime.strptime(system_text, "%Y-%m-%d %H:%M:%S")
    base = system_dt.hour * 3600 + system_dt.minute * 60 + system_dt.second
    expected = normalize_name(destination_name)
    values: list[int] = []
    for platform in response.get("platform_list") or []:
        for train in platform.get("route_list") or []:
            if str(train.get("route_no")) != route_no:
                continue
            if normalize_name(train.get("dest_en", "")) != expected:
                continue
            text = str(train.get("time_en", ""))
            match = re.search(r"(\d+)\s*mins?", text, flags=re.I)
            if match:
                values.append(base + int(match.group(1)) * 60)
            elif text.strip() == "-" or any(word in text.lower() for word in ("arriv", "depart")):
                values.append(base)
    return sorted(set(values))


def match_adjacent_predictions(
    from_times: list[int], to_times: list[int], prior_seconds: float, mode: str
) -> tuple[float, int, float, int] | None:
    if not from_times or not to_times or not math.isfinite(prior_seconds):
        return None
    minimum = max(15.0 if mode == "lrt" else 25.0, prior_seconds * 0.35)
    maximum = min(1500.0, max(180.0, prior_seconds * (3.0 if mode == "lrt" else 2.6)))
    best: tuple[float, float, list[float], int] | None = None
    for shift in range(-4, 5):
        deltas = []
        for index, from_time in enumerate(from_times):
            target_index = index + shift
            if 0 <= target_index < len(to_times):
                delta = float(to_times[target_index] - from_time)
                if minimum <= delta <= maximum:
                    deltas.append(delta)
        if not deltas:
            continue
        median = float(np.median(deltas))
        mad = float(np.median(np.abs(np.asarray(deltas) - median)))
        coverage_penalty = 1.0 - len(deltas) / max(len(from_times), len(to_times))
        score = abs(math.log(max(median, 1) / max(prior_seconds, 1))) + mad / 180 + coverage_penalty * 0.2
        candidate = (score, abs(median - prior_seconds), deltas, shift)
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    if best is None:
        return None
    deltas = np.asarray(best[2], dtype=float)
    median = float(np.median(deltas))
    mad = float(np.median(np.abs(deltas - median)))
    return median, len(deltas), mad, best[3]


def dwell_seconds(
    mode: str,
    stop_code: str,
    sequence: int,
    stop_count: int,
    mtr_line_counts: dict[str, int],
    lrt_route_counts: dict[str, int],
) -> tuple[int, str]:
    if sequence == 1:
        return 0, "origin_departure_anchor"
    if sequence == stop_count:
        return 0, "destination_no_turnaround"
    if mode == "mtr":
        if mtr_line_counts.get(stop_code, 0) > 1:
            return 45, "mtr_interchange_prior"
        return 30, "mtr_ordinary_prior"
    if lrt_route_counts.get(stop_code, 0) >= 4:
        return 30, "lrt_major_interchange_prior"
    return 20, "lrt_ordinary_prior"


def collect_raw_observations(
    patterns: pd.DataFrame,
    route_stops: pd.DataFrame,
    snapshots: list[dict[str, Any]],
    distances: dict[tuple[str, str, str, str], float],
    speed_by_line: dict[tuple[str, str], float],
    mtr_line_counts: dict[str, int],
    lrt_route_counts: dict[str, int],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for pattern in patterns.itertuples(index=False):
        stops = route_stops[route_stops["route_variant_id"].eq(pattern.route_variant_id)].sort_values(
            "stop_sequence"
        )
        destination_name = "TSW Circular" if pattern.direction == "LOOP" else pattern.destination_name_en
        for from_stop, to_stop in zip(stops.iloc[:-1].itertuples(), stops.iloc[1:].itertuples()):
            from_code = normalize_id(from_stop.stop_code)
            to_code = normalize_id(to_stop.stop_code)
            key = (pattern.mode, normalize_id(pattern.line_code), from_code, to_code)
            distance = distances.get(key, math.nan)
            dwell, _ = dwell_seconds(
                pattern.mode,
                from_code,
                int(from_stop.stop_sequence),
                len(stops),
                mtr_line_counts,
                lrt_route_counts,
            )
            speed = speed_by_line[(pattern.mode, normalize_id(pattern.line_code))]
            prior = distance / (speed / 3.6) + dwell if math.isfinite(distance) else math.nan
            for snapshot in snapshots:
                if pattern.mode == "mtr":
                    from_times = mtr_prediction_times(
                        snapshot, normalize_id(pattern.line_code), from_code, normalize_id(pattern.destination_code)
                    )
                    to_times = mtr_prediction_times(
                        snapshot, normalize_id(pattern.line_code), to_code, normalize_id(pattern.destination_code)
                    )
                else:
                    from_times = lrt_prediction_times(
                        snapshot, normalize_id(from_stop.stop_id), normalize_id(pattern.line_code), destination_name
                    )
                    to_times = lrt_prediction_times(
                        snapshot, normalize_id(to_stop.stop_id), normalize_id(pattern.line_code), destination_name
                    )
                matched = match_adjacent_predictions(from_times, to_times, prior, pattern.mode)
                if matched is None:
                    continue
                elapsed, pair_count, mad, rank_shift = matched
                rows.append(
                    {
                        "snapshot_id": snapshot["snapshot_id"],
                        "captured_local": snapshot["captured_local"],
                        "route_variant_id": pattern.route_variant_id,
                        "mode": pattern.mode,
                        "line_code": normalize_id(pattern.line_code),
                        "from_stop_code": from_code,
                        "to_stop_code": to_code,
                        "from_stop_name_en": from_stop.stop_name_en,
                        "to_stop_name_en": to_stop.stop_name_en,
                        "distance_m": distance,
                        "prior_elapsed_seconds": prior,
                        "observed_elapsed_seconds": elapsed,
                        "matched_prediction_pairs": pair_count,
                        "within_snapshot_mad_seconds": mad,
                        "rank_shift": rank_shift,
                        "from_prediction_count": len(from_times),
                        "to_prediction_count": len(to_times),
                    }
                )
    return pd.DataFrame(rows)


def fit_line_speeds(
    observations: pd.DataFrame,
    initial_speeds: dict[tuple[str, str], float],
    mtr_line_counts: dict[str, int],
    lrt_route_counts: dict[str, int],
) -> pd.DataFrame:
    candidates: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
    if len(observations):
        grouped = observations.groupby(
            ["mode", "line_code", "from_stop_code", "to_stop_code", "snapshot_id"], as_index=False
        ).agg(
            distance_m=("distance_m", "median"),
            observed_elapsed_seconds=("observed_elapsed_seconds", "median"),
            pair_count=("matched_prediction_pairs", "sum"),
        )
        for row in grouped.itertuples(index=False):
            dwell = 45 if row.mode == "mtr" and mtr_line_counts.get(row.from_stop_code, 0) > 1 else 30
            if row.mode == "lrt":
                dwell = 30 if lrt_route_counts.get(row.from_stop_code, 0) >= 4 else 20
            moving = row.observed_elapsed_seconds - dwell
            if moving <= 15 or not math.isfinite(row.distance_m):
                continue
            speed = row.distance_m / moving * 3.6
            bounds = (15, 110) if row.mode == "mtr" else (6, 45)
            if bounds[0] <= speed <= bounds[1]:
                candidates[(row.mode, row.line_code)].append((speed, max(1, row.pair_count)))
    rows = []
    for key, initial in sorted(initial_speeds.items()):
        values = candidates.get(key, [])
        if values:
            speeds = np.asarray([value for value, _ in values], dtype=float)
            weights = np.asarray([weight for _, weight in values], dtype=float)
            fitted = weighted_median(speeds, weights)
            lower, upper = ((25, 90) if key[0] == "mtr" else (12, 35))
            fitted = float(np.clip(fitted, lower, upper))
            source = "snapshot_weighted_median"
        else:
            fitted = initial
            source = "initial_mode_line_prior"
        rows.append(
            {
                "mode": key[0],
                "line_code": key[1],
                "initial_speed_kmh": initial,
                "fitted_speed_kmh": fitted,
                "valid_snapshot_segment_samples": len(values),
                "speed_source": source,
            }
        )
    return pd.DataFrame(rows)


def aggregate_segment_estimates(
    patterns: pd.DataFrame,
    route_stops: pd.DataFrame,
    observations: pd.DataFrame,
    distances: dict[tuple[str, str, str, str], float],
    distance_sources: dict[tuple[str, str, str, str], str],
    speed_parameters: pd.DataFrame,
    mtr_line_counts: dict[str, int],
    lrt_route_counts: dict[str, int],
) -> pd.DataFrame:
    speeds = {
        (row.mode, normalize_id(row.line_code)): float(row.fitted_speed_kmh)
        for row in speed_parameters.itertuples(index=False)
    }
    pooled: dict[tuple[str, str, str, str], pd.DataFrame] = {}
    if len(observations):
        for key, group in observations.groupby(["mode", "line_code", "from_stop_code", "to_stop_code"]):
            per_snapshot = group.groupby("snapshot_id", as_index=False).agg(
                observed=("observed_elapsed_seconds", "median"),
                pair_count=("matched_prediction_pairs", "sum"),
                within_mad=("within_snapshot_mad_seconds", "median"),
            )
            pooled[key] = per_snapshot

    fallback_distance = {
        mode: float(np.median([value for key, value in distances.items() if key[0] == mode]))
        for mode in ("mtr", "lrt")
    }
    rows: list[dict[str, Any]] = []
    for pattern in patterns.itertuples(index=False):
        stops = route_stops[route_stops["route_variant_id"].eq(pattern.route_variant_id)].sort_values(
            "stop_sequence"
        )
        for from_stop, to_stop in zip(stops.iloc[:-1].itertuples(), stops.iloc[1:].itertuples()):
            from_code = normalize_id(from_stop.stop_code)
            to_code = normalize_id(to_stop.stop_code)
            key = (pattern.mode, normalize_id(pattern.line_code), from_code, to_code)
            distance = distances.get(key, fallback_distance[pattern.mode])
            distance_source = distance_sources.get(key, "mode_median_fallback")
            dwell, dwell_source = dwell_seconds(
                pattern.mode,
                from_code,
                int(from_stop.stop_sequence),
                len(stops),
                mtr_line_counts,
                lrt_route_counts,
            )
            speed = speeds[(pattern.mode, normalize_id(pattern.line_code))]
            model_running = distance / (speed / 3.6)
            model_elapsed = model_running + dwell
            snapshot_frame = pooled.get(key)
            if snapshot_frame is None or len(snapshot_frame) == 0:
                snapshot_count = 0
                observed = math.nan
                between_mad = math.nan
                weight = 0.0
                source = "line_speed_model"
            else:
                snapshot_count = int(len(snapshot_frame))
                observed_values = snapshot_frame["observed"].to_numpy(float)
                observed = float(np.median(observed_values))
                between_mad = float(np.median(np.abs(observed_values - observed)))
                base_weights = (
                    {1: 0.45, 2: 0.65, 3: 0.78}
                    if pattern.mode == "mtr"
                    else {1: 0.30, 2: 0.45, 3: 0.60}
                )
                weight = base_weights[min(snapshot_count, 3)] * math.exp(-between_mad / 180)
                source = f"snapshot_{snapshot_count}_shrinkage"
            elapsed = model_elapsed if not math.isfinite(observed) else weight * observed + (1 - weight) * model_elapsed
            elapsed = float(np.clip(elapsed, max(dwell + 15, model_elapsed * 0.60), model_elapsed * 1.65))
            running = max(15.0, elapsed - dwell)
            running = int(round(running / 5) * 5)
            elapsed = running + dwell
            confidence = (
                "high" if pattern.mode == "mtr" and snapshot_count >= 2 and distance_source != "mode_median_fallback"
                else "medium" if snapshot_count >= 1 and distance_source != "mode_median_fallback"
                else "low"
            )
            rows.append(
                {
                    "route_variant_id": pattern.route_variant_id,
                    "mode": pattern.mode,
                    "line_code": normalize_id(pattern.line_code),
                    "direction": pattern.direction,
                    "from_stop_sequence": int(from_stop.stop_sequence),
                    "to_stop_sequence": int(to_stop.stop_sequence),
                    "from_stop_code": from_code,
                    "to_stop_code": to_code,
                    "from_stop_name_en": from_stop.stop_name_en,
                    "to_stop_name_en": to_stop.stop_name_en,
                    "distance_m": round(distance, 3),
                    "distance_source": distance_source,
                    "fitted_line_speed_kmh": round(speed, 3),
                    "snapshot_count": snapshot_count,
                    "observed_elapsed_median_seconds": observed,
                    "between_snapshot_mad_seconds": between_mad,
                    "snapshot_weight": round(weight, 4),
                    "model_elapsed_seconds": round(model_elapsed, 3),
                    "origin_dwell_seconds": dwell,
                    "origin_dwell_source": dwell_source,
                    "estimated_running_seconds": running,
                    "estimated_elapsed_arrival_to_arrival_seconds": elapsed,
                    "estimate_source": source,
                    "confidence": confidence,
                }
            )
    return pd.DataFrame(rows)


def build_stop_offsets(
    patterns: pd.DataFrame, route_stops: pd.DataFrame, segments: pd.DataFrame,
    mtr_line_counts: dict[str, int], lrt_route_counts: dict[str, int]
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for pattern in patterns.itertuples(index=False):
        stops = route_stops[route_stops["route_variant_id"].eq(pattern.route_variant_id)].sort_values(
            "stop_sequence"
        )
        route_segments = segments[segments["route_variant_id"].eq(pattern.route_variant_id)].sort_values(
            "from_stop_sequence"
        )
        arrival = 0
        departure = 0
        for index, stop in enumerate(stops.itertuples(index=False)):
            sequence = int(stop.stop_sequence)
            dwell, dwell_source = dwell_seconds(
                pattern.mode,
                normalize_id(stop.stop_code),
                sequence,
                len(stops),
                mtr_line_counts,
                lrt_route_counts,
            )
            previous_running = 0
            previous_source = "origin"
            confidence = "high"
            if index > 0:
                segment = route_segments.iloc[index - 1]
                previous_running = int(segment["estimated_running_seconds"])
                arrival = departure + previous_running
                departure = arrival + dwell
                previous_source = str(segment["estimate_source"])
                confidence = str(segment["confidence"])
            facility_id = (
                f"mtr_{normalize_id(stop.stop_code)}"
                if pattern.mode == "mtr"
                else f"lrt_{normalize_id(stop.stop_id)}"
            )
            rows.append(
                {
                    "route_variant_id": pattern.route_variant_id,
                    "mode": pattern.mode,
                    "line_code": normalize_id(pattern.line_code),
                    "direction": pattern.direction,
                    "stop_sequence": sequence,
                    "transit_stop_facility_id": facility_id,
                    "stop_code": normalize_id(stop.stop_code),
                    "source_stop_id": normalize_id(stop.stop_id),
                    "stop_name_en": stop.stop_name_en,
                    "stop_name_zh": stop.stop_name_zh,
                    "arrival_offset_seconds": arrival,
                    "departure_offset_seconds": departure,
                    "arrival_offset": format_seconds(arrival),
                    "departure_offset": format_seconds(departure),
                    "dwell_seconds": dwell,
                    "dwell_source": dwell_source,
                    "previous_segment_running_seconds": previous_running,
                    "previous_segment_source": previous_source,
                    "confidence": confidence,
                    "await_departure": sequence == 1,
                }
            )
    return pd.DataFrame(rows)


def plot_qa(segments: pd.DataFrame, route_summary: pd.DataFrame, output: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(15, 6), dpi=180)
    colors = {"mtr": "#176b87", "lrt": "#d07a20"}
    for mode, group in segments.groupby("mode"):
        observed = group[group["observed_elapsed_median_seconds"].notna()]
        axes[0].scatter(
            observed["model_elapsed_seconds"] / 60,
            observed["estimated_elapsed_arrival_to_arrival_seconds"] / 60,
            s=13,
            alpha=0.65,
            color=colors[mode],
            label=mode.upper(),
        )
    upper = max(
        float(segments["model_elapsed_seconds"].max()),
        float(segments["estimated_elapsed_arrival_to_arrival_seconds"].max()),
    ) / 60
    axes[0].plot([0, upper], [0, upper], color="#7f878d", linewidth=1, linestyle="--")
    axes[0].set_xlabel("Line-speed model elapsed time (minutes)")
    axes[0].set_ylabel("Final estimated elapsed time (minutes)")
    axes[0].set_title("Adjacent-station estimates")
    axes[0].legend(frameon=False)
    axes[0].grid(color="#dfe3e6", linewidth=0.5)

    display = route_summary.sort_values("route_runtime_minutes", ascending=False)
    axes[1].barh(
        display["route_variant_id"],
        display["route_runtime_minutes"],
        color=[colors[mode] for mode in display["mode"]],
    )
    axes[1].invert_yaxis()
    axes[1].set_xlabel("Origin-to-destination runtime (minutes)")
    axes[1].set_title("Inferred route runtimes")
    axes[1].tick_params(axis="y", labelsize=6)
    axes[1].grid(axis="x", color="#dfe3e6", linewidth=0.5)
    for axis in axes:
        axis.spines[["top", "right", "left"]].set_visible(False)
    fig.suptitle("Hong Kong MATSim-ready MTR and Light Rail station timing QA", fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(output, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> int:
    args = parse_args()
    transit_root = args.transit_root.resolve()
    snapshot_dirs = args.snapshot_dirs or DEFAULT_SNAPSHOTS
    timetable_dir = args.timetable_dir or transit_root / "processed/mtr_lrt_approximate_timetable_2026_weekday"
    mapmatching_dir = args.mapmatching_dir or transit_root / "processed/transit_route_link_mapmatching_2026_v2"
    mtr_stops_path = args.mtr_stops or transit_root / "MTR/mtr_lines_and_stations.csv"
    lrt_stops_path = args.lrt_stops or transit_root / "MTR/light_rail_routes_and_stops.csv"
    output_dir = args.output_dir or transit_root / "processed/mtr_lrt_approximate_station_times_2026_weekday"
    required = [
        timetable_dir / "approximate_route_patterns.csv",
        timetable_dir / "approximate_route_stops.csv",
        mapmatching_dir / "route_link_sequences.csv",
        mapmatching_dir / "stop_link_snaps.csv",
        mtr_stops_path,
        lrt_stops_path,
    ]
    for snapshot_dir in snapshot_dirs:
        required.extend([snapshot_dir / "mtr_next_train.jsonl", snapshot_dir / "light_rail_next_train.jsonl"])
    for path in required:
        if not path.exists():
            raise FileNotFoundError(path)
    if len(snapshot_dirs) != 3:
        raise ValueError("Exactly three independent snapshot directories are required")
    output_dir.mkdir(parents=True, exist_ok=True)

    patterns = pd.read_csv(timetable_dir / "approximate_route_patterns.csv", dtype=str, keep_default_na=False)
    route_stops = pd.read_csv(timetable_dir / "approximate_route_stops.csv", dtype=str, keep_default_na=False)
    route_stops["stop_sequence"] = pd.to_numeric(route_stops["stop_sequence"])
    route_links = pd.read_csv(mapmatching_dir / "route_link_sequences.csv", low_memory=False)
    stop_snaps = pd.read_csv(mapmatching_dir / "stop_link_snaps.csv", low_memory=False)
    mtr_stops = pd.read_csv(mtr_stops_path, dtype=str, keep_default_na=False)
    lrt_stops = pd.read_csv(lrt_stops_path, dtype=str, keep_default_na=False)
    mtr_stops["Sequence"] = pd.to_numeric(mtr_stops["Sequence"])
    lrt_stops["Sequence"] = pd.to_numeric(lrt_stops["Sequence"])
    snapshots = [prepare_snapshot(path) for path in snapshot_dirs]

    link_distances, distance_audit = build_distance_lookup(route_links, stop_snaps, mtr_stops, lrt_stops)
    coordinates, coordinate_audit = build_station_coordinate_lookup(
        stop_snaps, mtr_stops, lrt_stops, route_stops
    )
    distances, distance_sources, distance_parameters = build_reliable_segment_distances(
        patterns, route_stops, link_distances, coordinates
    )
    mtr_line_counts = (
        mtr_stops.groupby("Station Code")["Line Code"].nunique().astype(int).to_dict()
    )
    lrt_route_counts = (
        lrt_stops.groupby("Stop Code")["Line Code"].nunique().astype(int).to_dict()
    )
    initial_speeds = {
        (str(row.mode), normalize_id(row.line_code)): (
            INITIAL_SPEED_KMH.get(normalize_id(row.line_code), 38.0)
            if row.mode == "mtr"
            else 22.0
        )
        for row in patterns[["mode", "line_code"]].drop_duplicates().itertuples(index=False)
    }

    first_observations = collect_raw_observations(
        patterns,
        route_stops,
        snapshots,
        distances,
        initial_speeds,
        mtr_line_counts,
        lrt_route_counts,
    )
    first_speed_parameters = fit_line_speeds(
        first_observations, initial_speeds, mtr_line_counts, lrt_route_counts
    )
    fitted_speeds = {
        (row.mode, normalize_id(row.line_code)): float(row.fitted_speed_kmh)
        for row in first_speed_parameters.itertuples(index=False)
    }
    observations = collect_raw_observations(
        patterns,
        route_stops,
        snapshots,
        distances,
        fitted_speeds,
        mtr_line_counts,
        lrt_route_counts,
    )
    speed_parameters = fit_line_speeds(
        observations, initial_speeds, mtr_line_counts, lrt_route_counts
    )
    segments = aggregate_segment_estimates(
        patterns,
        route_stops,
        observations,
        distances,
        distance_sources,
        speed_parameters,
        mtr_line_counts,
        lrt_route_counts,
    )
    offsets = build_stop_offsets(
        patterns, route_stops, segments, mtr_line_counts, lrt_route_counts
    )
    route_summary = (
        offsets.groupby(["route_variant_id", "mode", "line_code", "direction"], as_index=False)
        .agg(
            stop_count=("stop_sequence", "size"),
            route_runtime_seconds=("arrival_offset_seconds", "max"),
            total_dwell_seconds=("dwell_seconds", "sum"),
            low_confidence_stops=("confidence", lambda values: int((values == "low").sum())),
        )
    )
    route_summary["route_runtime_minutes"] = route_summary["route_runtime_seconds"] / 60

    observations.to_csv(output_dir / "snapshot_adjacent_station_observations.csv", index=False, encoding="utf-8-sig")
    speed_parameters.to_csv(output_dir / "line_speed_parameters.csv", index=False, encoding="utf-8-sig")
    segments.to_csv(output_dir / "adjacent_station_time_estimates.csv", index=False, encoding="utf-8-sig")
    offsets.to_csv(output_dir / "matsim_route_stop_offsets.csv", index=False, encoding="utf-8-sig")
    route_summary.to_csv(output_dir / "route_runtime_summary.csv", index=False, encoding="utf-8-sig")
    distance_audit.to_csv(output_dir / "mapmatched_distance_alignment_qa.csv", index=False, encoding="utf-8-sig")
    coordinate_audit.to_csv(output_dir / "station_coordinate_coverage_qa.csv", index=False, encoding="utf-8-sig")
    distance_parameters.to_csv(output_dir / "line_distance_parameters.csv", index=False, encoding="utf-8-sig")
    preview = output_dir / "station_timing_qa.png"
    plot_qa(segments, route_summary, preview)

    if len(patterns) != offsets["route_variant_id"].nunique():
        raise ValueError("Not every route pattern received stop offsets")
    if not offsets.groupby("route_variant_id")["arrival_offset_seconds"].apply(
        lambda values: values.is_monotonic_increasing
    ).all():
        raise ValueError("Arrival offsets are not monotonic")
    if (segments["estimated_running_seconds"] <= 0).any() or segments["distance_m"].isna().any():
        raise ValueError("Invalid segment time or distance")

    summary = {
        "scope": "inferred MATSim-ready MTR/LRT station running, dwell, and cumulative offset times",
        "snapshot_dirs": [str(path) for path in snapshot_dirs],
        "snapshot_local_times": [snapshot["captured_local"] for snapshot in snapshots],
        "snapshot_sha256": {
            path.name: {
                "mtr": file_sha256(path / "mtr_next_train.jsonl"),
                "lrt": file_sha256(path / "light_rail_next_train.jsonl"),
            }
            for path in snapshot_dirs
        },
        "route_patterns": int(len(patterns)),
        "route_patterns_by_mode": patterns.groupby("mode").size().astype(int).to_dict(),
        "route_stop_offsets": int(len(offsets)),
        "adjacent_route_segments": int(len(segments)),
        "unique_physical_directed_segments": int(
            segments[["mode", "line_code", "from_stop_code", "to_stop_code"]].drop_duplicates().shape[0]
        ),
        "snapshot_observation_rows": int(len(observations)),
        "segments_with_any_snapshot": int((segments["snapshot_count"] > 0).sum()),
        "segments_with_all_three_snapshots": int((segments["snapshot_count"] >= 3).sum()),
        "segments_by_confidence": segments.groupby("confidence").size().astype(int).to_dict(),
        "distance_sources": segments.groupby("distance_source").size().astype(int).to_dict(),
        "runtime_minutes_by_mode": route_summary.groupby("mode")["route_runtime_minutes"].agg(
            ["min", "median", "max"]
        ).to_dict(orient="index"),
        "dwell_assumptions_seconds": {
            "mtr_ordinary": 30,
            "mtr_interchange": 45,
            "lrt_ordinary": 20,
            "lrt_major_interchange": 30,
            "route_origin": 0,
            "route_destination": 0,
        },
        "qa": {
            "routes_missing_offsets": 0,
            "non_monotonic_route_offsets": 0,
            "nonpositive_running_times": 0,
            "missing_segment_distances": 0,
        },
        "limitations": [
            "The APIs do not expose train IDs; adjacent predictions are matched by ordered rank and a distance prior.",
            "MTR predictions are minute-granularity and Light Rail predictions are relative integer minutes.",
            "Dwell times are station-type priors, not directly observed platform dwell measurements.",
            "Terminal turnaround and vehicle block layover are excluded from passenger route offsets.",
            "These offsets are intended for synthetic MATSim supply, not publication as an official timetable.",
        ],
    }
    (output_dir / "station_timing_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_manifest(output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
