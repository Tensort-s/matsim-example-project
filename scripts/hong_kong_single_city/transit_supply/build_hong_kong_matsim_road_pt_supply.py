#!/usr/bin/env python3
"""Assemble Hong Kong road and public-transport inputs for MATSim.

The output deliberately excludes population plans. Bus and GMB departures are
expanded from the local Transport Department GTFS for a representative weekday;
routes absent from that snapshot receive an explicit approximate service. MTR
and Light Rail use the previously inferred departures and station offsets.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import re
import shutil
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from xml.sax.saxutils import escape
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_ROOT = Path(r"F:\Matsim\matsim-example-project\data")
REPRESENTATIVE_DATE = "20260722"
NETWORK_CRS = "EPSG:32650"

MODE_TO_MATSIM = {
    "bus": "bus",
    "gmb": "gmb",
    "minibus": "gmb",
    "mtr": "train",
    "lrt": "light_rail",
    "hsr": "train",
    "tram": "tram",
}
ROAD_SPEED_MPS = {"bus": 7.0, "gmb": 8.0}
ROAD_DWELL_SECONDS = {"bus": 20, "gmb": 15}
FALLBACK_HEADWAY_SECONDS = {"bus": 900, "gmb": 720}
FALLBACK_START_SECONDS = 6 * 3600
FALLBACK_END_SECONDS = 23 * 3600 + 30 * 60


@dataclass(frozen=True)
class NetworkLink:
    link_id: str
    from_node: str
    to_node: str
    length_m: float
    freespeed_mps: float
    modes: frozenset[str]
    geometry: LineString


def safe_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def truthy(value: Any) -> bool:
    return safe_text(value).lower() in {"1", "true", "yes"}


def normalize_id(value: Any) -> str:
    text = safe_text(value)
    return text[:-2] if text.endswith(".0") else text


def parse_time(value: Any) -> int | None:
    text = safe_text(value)
    if not text:
        return None
    parts = text.split(":")
    if len(parts) != 3:
        return None
    try:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except ValueError:
        return None


def format_time(seconds: int | float) -> str:
    total = max(0, int(round(float(seconds))))
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def percentile_summary(series: pd.Series) -> dict[str, float | int | None]:
    values = pd.to_numeric(series, errors="coerce").dropna().to_numpy(float)
    if not len(values):
        return {"count": 0, "mean": None, "p50": None, "p95": None, "max": None}
    return {
        "count": int(len(values)),
        "mean": float(np.mean(values)),
        "p50": float(np.percentile(values, 50)),
        "p95": float(np.percentile(values, 95)),
        "max": float(np.max(values)),
    }


def load_network(path: Path) -> tuple[dict[str, tuple[float, float]], dict[str, NetworkLink]]:
    with gzip.open(path, "rb") as handle:
        root = ET.parse(handle).getroot()
    nodes_element = root.find("nodes")
    links_element = root.find("links")
    if nodes_element is None or links_element is None:
        raise ValueError("Invalid MATSim network XML")
    nodes = {
        item.attrib["id"]: (float(item.attrib["x"]), float(item.attrib["y"]))
        for item in nodes_element
    }
    links: dict[str, NetworkLink] = {}
    for item in links_element:
        from_node = item.attrib["from"]
        to_node = item.attrib["to"]
        links[item.attrib["id"]] = NetworkLink(
            link_id=item.attrib["id"],
            from_node=from_node,
            to_node=to_node,
            length_m=float(item.attrib["length"]),
            freespeed_mps=float(item.attrib["freespeed"]),
            modes=frozenset(item.attrib.get("modes", "").split(",")),
            geometry=LineString([nodes[from_node], nodes[to_node]]),
        )
    return nodes, links


def reverse_link_id(link: NetworkLink, links: dict[str, NetworkLink]) -> str:
    if link.link_id.endswith("_f"):
        direct = link.link_id[:-2] + "_r"
    elif link.link_id.endswith("_r"):
        direct = link.link_id[:-2] + "_f"
    else:
        direct = ""
    if direct in links:
        candidate = links[direct]
        if candidate.from_node == link.to_node and candidate.to_node == link.from_node:
            return direct
    candidates = [
        candidate.link_id
        for candidate in links.values()
        if candidate.from_node == link.to_node
        and candidate.to_node == link.from_node
        and abs(candidate.length_m - link.length_m) <= max(2.0, 0.02 * link.length_m)
        and ("train" in candidate.modes or "light_rail" in candidate.modes)
    ]
    if not candidates:
        synthetic_id = f"{link.link_id}_schedule_reverse"
        if synthetic_id not in links:
            links[synthetic_id] = NetworkLink(
                link_id=synthetic_id,
                from_node=link.to_node,
                to_node=link.from_node,
                length_m=link.length_m,
                freespeed_mps=link.freespeed_mps,
                modes=link.modes,
                geometry=LineString(list(link.geometry.coords)[::-1]),
            )
        return synthetic_id
    return sorted(candidates)[0]


def reverse_sequence(sequence: list[str], links: dict[str, NetworkLink]) -> list[str]:
    return [reverse_link_id(links[link_id], links) for link_id in reversed(sequence)]


def check_continuity(sequence: Iterable[str], links: dict[str, NetworkLink]) -> int:
    ids = list(sequence)
    return sum(
        links[left].to_node != links[right].from_node
        for left, right in zip(ids[:-1], ids[1:])
    )


def load_gtfs_table(archive: zipfile.ZipFile, name: str) -> pd.DataFrame:
    return pd.read_csv(archive.open(name), dtype=str, keep_default_na=False)


def active_services(calendar: pd.DataFrame, exceptions: pd.DataFrame, date: str) -> set[str]:
    instant = datetime.strptime(date, "%Y%m%d")
    weekday = instant.strftime("%A").lower()
    valid = calendar[
        (calendar[weekday].eq("1"))
        & (calendar["start_date"].le(date))
        & (calendar["end_date"].ge(date))
    ]
    result = set(valid["service_id"])
    day_exceptions = exceptions[exceptions["date"].eq(date)]
    result.update(day_exceptions.loc[day_exceptions["exception_type"].eq("1"), "service_id"])
    result.difference_update(day_exceptions.loc[day_exceptions["exception_type"].eq("2"), "service_id"])
    return result


def gtfs_direction(trip_id: str) -> str:
    parts = safe_text(trip_id).split("-")
    return parts[1] if len(parts) >= 2 else ""


def expand_road_departures(
    gtfs_path: Path,
    approved_road: pd.DataFrame,
    representative_date: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    with zipfile.ZipFile(gtfs_path) as archive:
        calendar = load_gtfs_table(archive, "calendar.txt")
        exceptions = load_gtfs_table(archive, "calendar_dates.txt")
        trips = load_gtfs_table(archive, "trips.txt")
        stop_times = load_gtfs_table(archive, "stop_times.txt")
        frequencies = load_gtfs_table(archive, "frequencies.txt")

    services = active_services(calendar, exceptions, representative_date)
    trips = trips[trips["service_id"].isin(services)].copy()
    trips["route_seq"] = trips["trip_id"].map(gtfs_direction)
    active_trip_ids = set(trips["trip_id"])

    stop_times = stop_times[stop_times["trip_id"].isin(active_trip_ids)].copy()
    stop_times["stop_sequence_number"] = pd.to_numeric(stop_times["stop_sequence"], errors="coerce")
    origins = (
        stop_times.sort_values(["trip_id", "stop_sequence_number"])
        .drop_duplicates("trip_id", keep="first")
        [["trip_id", "arrival_time", "departure_time"]]
    )
    origins["origin_seconds"] = origins.apply(
        lambda row: parse_time(row["departure_time"]) or parse_time(row["arrival_time"]),
        axis=1,
    )
    trips = trips.merge(origins[["trip_id", "origin_seconds"]], on="trip_id", how="left")

    frequencies = frequencies[frequencies["trip_id"].isin(active_trip_ids)].copy()
    frequency_trip_ids = set(frequencies["trip_id"])
    trip_lookup = trips.set_index("trip_id")[["route_id", "route_seq"]].to_dict("index")
    rows: list[dict[str, Any]] = []
    for record in frequencies.itertuples(index=False):
        start = parse_time(record.start_time)
        end = parse_time(record.end_time)
        headway = safe_int(record.headway_secs)
        metadata = trip_lookup.get(record.trip_id)
        if metadata is None or start is None or end is None or headway <= 0:
            continue
        for second in range(start, end, headway):
            rows.append(
                {
                    "route_id": normalize_id(metadata["route_id"]),
                    "route_seq": normalize_id(metadata["route_seq"]),
                    "departure_seconds": second,
                    "service_source": "gtfs_frequency",
                    "source_trip_id": record.trip_id,
                }
            )
    fixed = trips[~trips["trip_id"].isin(frequency_trip_ids) & trips["origin_seconds"].notna()]
    for record in fixed.itertuples(index=False):
        rows.append(
            {
                "route_id": normalize_id(record.route_id),
                "route_seq": normalize_id(record.route_seq),
                "departure_seconds": int(record.origin_seconds),
                "service_source": "gtfs_fixed_trip",
                "source_trip_id": record.trip_id,
            }
        )
    expanded = pd.DataFrame(rows)
    if expanded.empty:
        raise ValueError("No active GTFS road departures were expanded")
    expanded = expanded.sort_values(
        ["route_id", "route_seq", "departure_seconds", "service_source", "source_trip_id"]
    ).drop_duplicates(["route_id", "route_seq", "departure_seconds"], keep="first")
    expanded_groups = {
        (normalize_id(route_id), normalize_id(route_seq)): group.copy()
        for (route_id, route_seq), group in expanded.groupby(["route_id", "route_seq"], sort=False)
    }

    mapped_rows: list[pd.DataFrame] = []
    audit_rows: list[dict[str, Any]] = []
    for route in approved_road.itertuples(index=False):
        subset = expanded_groups.get(
            (normalize_id(route.route_id), normalize_id(route.route_seq)), pd.DataFrame()
        ).copy()
        if subset.empty:
            headway = FALLBACK_HEADWAY_SECONDS[str(route.mode)]
            subset = pd.DataFrame(
                {
                    "route_id": normalize_id(route.route_id),
                    "route_seq": normalize_id(route.route_seq),
                    "departure_seconds": range(
                        FALLBACK_START_SECONDS, FALLBACK_END_SECONDS + 1, headway
                    ),
                    "service_source": "approximate_mode_default",
                    "source_trip_id": "",
                }
            )
        subset["route_key"] = route.route_key
        subset = subset.sort_values("departure_seconds").reset_index(drop=True)
        subset["departure_sequence"] = np.arange(1, len(subset) + 1)
        subset["departure_id"] = subset.apply(
            lambda row: f"dep_{route.route_key}_{int(row['departure_sequence']):05d}", axis=1
        )
        subset["vehicle_id"] = "veh_" + subset["departure_id"]
        subset["vehicle_type_id"] = route.vehicle_type_id
        mapped_rows.append(subset)
        audit_rows.append(
            {
                "route_key": route.route_key,
                "mode": route.mode,
                "route_id": route.route_id,
                "route_seq": route.route_seq,
                "route_name": route.route_name,
                "departure_count": len(subset),
                "first_departure": format_time(subset["departure_seconds"].min()),
                "last_departure": format_time(subset["departure_seconds"].max()),
                "service_source": (
                    "approximate_mode_default"
                    if subset["service_source"].eq("approximate_mode_default").all()
                    else "gtfs"
                ),
                "vehicle_type_id": route.vehicle_type_id,
            }
        )
    departures = pd.concat(mapped_rows, ignore_index=True)
    audit = pd.DataFrame(audit_rows)
    summary = {
        "representative_date": representative_date,
        "active_service_ids": len(services),
        "active_gtfs_trips": len(trips),
        "expanded_unique_departures": len(expanded),
        "mapped_route_directions": int(audit["service_source"].eq("gtfs").sum()),
        "fallback_route_directions": int(audit["service_source"].eq("approximate_mode_default").sum()),
        "output_departures": len(departures),
    }
    return departures, audit, summary


def road_stop_offsets(
    assignments: pd.DataFrame,
    route_links: pd.DataFrame,
    facilities: pd.DataFrame,
    links: dict[str, NetworkLink],
) -> pd.DataFrame:
    facility_lookup = facilities.set_index("facility_id")
    route_link_groups = {
        route_key: group.sort_values("sequence")
        for route_key, group in route_links.groupby("route_key", sort=False)
    }
    rows: list[dict[str, Any]] = []
    for route_key, stops in assignments.groupby("route_key", sort=False):
        stops = stops.sort_values("stop_seq", key=lambda values: pd.to_numeric(values, errors="coerce"))
        sequence = route_link_groups.get(route_key)
        if sequence is None:
            raise ValueError(f"No route links for {route_key}")
        ids = sequence["link_id"].tolist()
        if not ids:
            raise ValueError(f"No route links for {route_key}")
        lengths = np.array([links[link_id].length_m for link_id in ids], dtype=float)
        starts = np.concatenate(([0.0], np.cumsum(lengths)))
        cycle_length = float(starts[-1])
        positions: list[float] = []
        for stop in stops.itertuples(index=False):
            unwrapped = max(0, safe_int(stop.route_link_index_unwrapped))
            cycle, index = divmod(unwrapped, len(ids))
            facility = facility_lookup.loc[stop.facility_id]
            point = Point(float(facility.x), float(facility.y))
            link = links[ids[index]]
            fraction = link.geometry.project(point) / max(link.geometry.length, 1e-9)
            positions.append(cycle * cycle_length + starts[index] + fraction * lengths[index])
        positions = list(np.maximum.accumulate(np.asarray(positions, dtype=float)))
        mode = safe_text(stops.iloc[0]["mode"])
        dwell = ROAD_DWELL_SECONDS[mode]
        arrival = 0
        departure = 0
        prior_position = positions[0]
        for index, (stop, position) in enumerate(zip(stops.itertuples(index=False), positions)):
            if index == 0:
                arrival = 0
                departure = 0
            else:
                distance = max(0.0, position - prior_position)
                running = max(30, int(round(distance / ROAD_SPEED_MPS[mode])))
                arrival = departure + running
                departure = arrival if index == len(stops) - 1 else arrival + dwell
            rows.append(
                {
                    "route_key": route_key,
                    "mode": mode,
                    "stop_sequence": index + 1,
                    "facility_id": stop.facility_id,
                    "link_ref_id": stop.link_ref_id,
                    "arrival_offset_seconds": arrival,
                    "departure_offset_seconds": departure,
                    "await_departure": index == 0,
                    "offset_source": "mapmatched_distance_mode_speed_dwell",
                    "distance_along_route_m": position,
                }
            )
            prior_position = position
    return pd.DataFrame(rows)


def nearest_link_candidates(
    points: list[Point], sequence: list[str], links: dict[str, NetworkLink], loop: bool
) -> tuple[list[int], list[float]] | None:
    count = len(sequence)
    candidate_sets: list[list[tuple[int, float]]] = []
    for point in points:
        distances = np.array([point.distance(links[link_id].geometry) for link_id in sequence])
        order = np.argsort(distances)[: min(24, count)]
        minimum = float(distances[order[0]])
        base = [(int(index), float(distances[index])) for index in order if distances[index] <= minimum + 180.0]
        if loop:
            base += [(index + count, distance) for index, distance in base]
        candidate_sets.append(sorted(base))

    states: dict[int, tuple[float, list[int], list[float]]] = {
        index: (distance, [index], [distance]) for index, distance in candidate_sets[0] if index < count
    }
    for candidates in candidate_sets[1:]:
        new_states: dict[int, tuple[float, list[int], list[float]]] = {}
        for index, distance in candidates:
            options = [value for prior, value in states.items() if prior <= index and index - value[1][0] <= count]
            if not options:
                continue
            best = min(options, key=lambda value: value[0])
            value = (best[0] + distance, best[1] + [index], best[2] + [distance])
            if index not in new_states or value[0] < new_states[index][0]:
                new_states[index] = value
        states = new_states
        if not states:
            return None
    best = min(states.values(), key=lambda value: value[0])
    return best[1], best[2]


def build_endpoint_proxy_stops(
    approved: pd.DataFrame,
    assignments: pd.DataFrame,
    route_links: pd.DataFrame,
    links: dict[str, NetworkLink],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    assigned_keys = set(assignments["route_key"])
    missing = approved[
        approved["mode"].isin(["bus", "gmb"])
        & ~approved["route_key"].isin(assigned_keys)
    ]
    assignment_rows: list[dict[str, Any]] = []
    facility_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    link_groups = {
        route_key: group.sort_values("sequence")
        for route_key, group in route_links.groupby("route_key", sort=False)
    }
    for route in missing.itertuples(index=False):
        sequence = link_groups[safe_text(route.route_key)]
        ids = sequence["link_id"].tolist()
        if len(ids) < 2:
            raise ValueError(f"Cannot create endpoint proxy stops for {route.route_key}")
        endpoints = [
            (1, 0, ids[0], links[ids[0]].geometry.interpolate(0.05, normalized=True), "origin"),
            (2, len(ids) - 1, ids[-1], links[ids[-1]].geometry.interpolate(0.95, normalized=True), "destination"),
        ]
        for stop_sequence, link_index, link_id, point, role in endpoints:
            stop_id = f"proxy_{route.route_key}_{role}"
            facility_id = f"pt_{stop_id}"
            facility_rows.append(
                {
                    "facility_id": facility_id,
                    "mode": route.mode,
                    "stop_id": stop_id,
                    "stop_name_en": f"{route.route_key} inferred {role}",
                    "stop_name_zh": "",
                    "facility_role": "endpoint_proxy_no_published_stops",
                    "link_ref_id": link_id,
                    "block_lane": False,
                    "x": float(point.x),
                    "y": float(point.y),
                    "source_x": float(point.x),
                    "source_y": float(point.y),
                    "facility_snap_distance_m": 0.0,
                }
            )
            assignment_rows.append(
                {
                    "route_key": route.route_key,
                    "mode": route.mode,
                    "route_id": route.route_id,
                    "route_seq": route.route_seq,
                    "company_code": route.company_code,
                    "route_name": route.route_name,
                    "stop_seq": stop_sequence,
                    "stop_id": stop_id,
                    "stop_name_en": f"{route.route_key} inferred {role}",
                    "stop_name_zh": "",
                    "facility_id": facility_id,
                    "link_ref_id": link_id,
                    "route_link_index": link_index,
                    "route_link_index_unwrapped": link_index,
                    "pickup_dropoff_source": "endpoint_proxy_no_published_stops",
                    "await_departure": stop_sequence == 1,
                    "coverage_distance_m": 0.0,
                    "assignment_distance_m": 0.0,
                    "external_or_uncovered": False,
                }
            )
        audit_rows.append(
            {
                "route_key": route.route_key,
                "mode": route.mode,
                "route_id": route.route_id,
                "route_seq": route.route_seq,
                "route_name": route.route_name,
                "proxy_stop_count": 2,
                "reason": "no_route_stop_json_and_no_gtfs_route",
                "service_source": "approximate_mode_default",
            }
        )
    return pd.DataFrame(assignment_rows), pd.DataFrame(facility_rows), pd.DataFrame(audit_rows)


def build_rail_variants(
    patterns: pd.DataFrame,
    offsets: pd.DataFrame,
    coordinates: pd.DataFrame,
    approved: pd.DataFrame,
    route_links: pd.DataFrame,
    links: dict[str, NetworkLink],
) -> tuple[dict[str, dict[str, Any]], pd.DataFrame, pd.DataFrame]:
    coordinate_lookup = {
        (safe_text(row.mode), safe_text(row.stop_code)): (float(row.x), float(row.y))
        for row in coordinates.itertuples(index=False)
        if not safe_text(row.stop_code).startswith("__route__")
        and truthy(row.coordinate_available)
        and safe_text(row.x)
        and safe_text(row.y)
    }
    approved_rail = approved[approved["mode"].isin(["mtr", "lrt"])]
    source_sequences = {
        key: group.sort_values("sequence")["link_id"].tolist()
        for key, group in route_links[route_links["mode"].isin(["mtr", "lrt"])]
        .groupby("route_key", sort=False)
    }
    variants: dict[str, dict[str, Any]] = {}
    audit_rows: list[dict[str, Any]] = []
    facility_rows: list[dict[str, Any]] = []

    for pattern in patterns.itertuples(index=False):
        route_id = safe_text(pattern.route_variant_id)
        stop_rows = offsets[offsets["route_variant_id"].eq(route_id)].sort_values(
            "stop_sequence", key=lambda values: pd.to_numeric(values, errors="coerce")
        )
        points = [
            Point(coordinate_lookup[(safe_text(row.mode), safe_text(row.stop_code))])
            for row in stop_rows.itertuples(index=False)
        ]
        loop = len(points) >= 2 and points[0].distance(points[-1]) <= 100.0
        candidates = approved_rail[
            approved_rail["mode"].eq(pattern.mode)
            & approved_rail["route_id"].map(normalize_id).eq(normalize_id(pattern.line_code))
        ]
        scored: list[tuple[float, str, str, list[str], list[int], list[float]]] = []
        seen: set[tuple[str, ...]] = set()
        for candidate in candidates.itertuples(index=False):
            base = source_sequences[safe_text(candidate.route_key)]
            for orientation, sequence in (("source", base), ("reversed", reverse_sequence(base, links))):
                token = tuple(sequence)
                if token in seen:
                    continue
                seen.add(token)
                matched = nearest_link_candidates(points, sequence, links, loop)
                if matched is None:
                    continue
                indices, distances = matched
                score = float(np.mean(distances) + 0.25 * np.percentile(distances, 95))
                scored.append((score, safe_text(candidate.route_key), orientation, sequence, indices, distances))
        if not scored:
            raise ValueError(f"No rail route sequence matches {route_id}")
        score, source_key, orientation, sequence, indices, distances = min(scored, key=lambda value: value[0])
        count = len(sequence)
        if loop:
            rotation = indices[0] % count
            selected_links = sequence[rotation:] + sequence[:rotation]
            adjusted_indices = [((index - rotation) % count) for index in indices]
            for index in range(1, len(adjusted_indices)):
                while adjusted_indices[index] < adjusted_indices[index - 1]:
                    adjusted_indices[index] += count
        else:
            start = indices[0]
            end = indices[-1]
            if end < start:
                raise ValueError(f"Non-monotonic rail sequence for {route_id}")
            selected_links = sequence[start : end + 1]
            adjusted_indices = [index - start for index in indices]
        if check_continuity(selected_links, links):
            raise ValueError(f"Rail route continuity failed for {route_id}")

        variant_stops: list[dict[str, Any]] = []
        for stop, point, raw_index, distance in zip(
            stop_rows.itertuples(index=False), points, adjusted_indices, distances
        ):
            link_index = raw_index % len(selected_links)
            link_id = selected_links[link_index]
            link = links[link_id]
            projection = link.geometry.interpolate(link.geometry.project(point))
            facility_id = f"pt_{route_id}_{safe_text(stop.stop_code)}"
            facility = {
                "facility_id": facility_id,
                "mode": safe_text(pattern.mode),
                "stop_id": safe_text(stop.stop_code),
                "stop_name_en": safe_text(stop.stop_name_en),
                "stop_name_zh": safe_text(stop.stop_name_zh),
                "x": float(projection.x),
                "y": float(projection.y),
                "link_ref_id": link_id,
                "block_lane": False,
                "facility_role": "rail_variant_platform",
                "source_x": float(point.x),
                "source_y": float(point.y),
                "snap_distance_m": float(distance),
            }
            facility_rows.append(facility)
            variant_stops.append(
                {
                    "route_key": route_id,
                    "mode": safe_text(pattern.mode),
                    "stop_sequence": safe_int(stop.stop_sequence),
                    "facility_id": facility_id,
                    "link_ref_id": link_id,
                    "arrival_offset_seconds": safe_int(stop.arrival_offset_seconds),
                    "departure_offset_seconds": safe_int(stop.departure_offset_seconds),
                    "await_departure": truthy(stop.await_departure),
                    "offset_source": "three_snapshot_rail_estimate",
                    "distance_along_route_m": math.nan,
                }
            )
        variants[route_id] = {
            "route_key": route_id,
            "mode": safe_text(pattern.mode),
            "line_code": safe_text(pattern.line_code),
            "route_name": safe_text(pattern.line_name),
            "link_ids": selected_links,
            "stops": pd.DataFrame(variant_stops),
            "source_route_key": source_key,
            "orientation": orientation,
        }
        audit_rows.append(
            {
                "route_variant_id": route_id,
                "mode": pattern.mode,
                "line_code": pattern.line_code,
                "source_route_key": source_key,
                "orientation": orientation,
                "is_loop": loop,
                "route_link_count": len(selected_links),
                "stop_count": len(stop_rows),
                "mean_station_snap_m": float(np.mean(distances)),
                "p95_station_snap_m": float(np.percentile(distances, 95)),
                "max_station_snap_m": float(np.max(distances)),
                "selection_score": score,
                "continuity_errors": check_continuity(selected_links, links),
            }
        )
    return variants, pd.DataFrame(audit_rows), pd.DataFrame(facility_rows).drop_duplicates("facility_id")


def write_schedule(
    path: Path,
    facilities: pd.DataFrame,
    routes: dict[str, dict[str, Any]],
) -> None:
    lines: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for route in routes.values():
        lines[route["line_id"]].append(route)
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as handle:
        handle.write('<?xml version="1.0" encoding="utf-8"?>\n')
        handle.write('<!DOCTYPE transitSchedule SYSTEM "http://www.matsim.org/files/dtd/transitSchedule_v2.dtd">\n')
        handle.write("<transitSchedule>\n  <transitStops>\n")
        for facility in facilities.sort_values("facility_id").itertuples(index=False):
            name = safe_text(facility.stop_name_en) or safe_text(facility.stop_name_zh) or safe_text(facility.stop_id)
            handle.write(
                f'    <stopFacility id="{escape(safe_text(facility.facility_id))}" '
                f'x="{float(facility.x):.3f}" y="{float(facility.y):.3f}" '
                f'linkRefId="{escape(safe_text(facility.link_ref_id))}" '
                f'name="{escape(name)}" isBlocking="false"/>\n'
            )
        handle.write("  </transitStops>\n")
        for line_id in sorted(lines):
            line_routes = sorted(lines[line_id], key=lambda value: value["route_key"])
            line_name = line_routes[0]["route_name"]
            handle.write(f'  <transitLine id="{escape(line_id)}" name="{escape(line_name)}">\n')
            for route in line_routes:
                handle.write(f'    <transitRoute id="{escape(route["route_key"])}">\n')
                handle.write(f'      <transportMode>{escape(MODE_TO_MATSIM[route["mode"]])}</transportMode>\n')
                handle.write("      <routeProfile>\n")
                stops = route["stops"].sort_values("stop_sequence")
                for stop in stops.itertuples(index=False):
                    await_value = "true" if bool(stop.await_departure) else "false"
                    handle.write(
                        f'        <stop refId="{escape(safe_text(stop.facility_id))}" '
                        f'arrivalOffset="{format_time(stop.arrival_offset_seconds)}" '
                        f'departureOffset="{format_time(stop.departure_offset_seconds)}" '
                        f'awaitDeparture="{await_value}"/>\n'
                    )
                handle.write("      </routeProfile>\n      <route>\n")
                for link_id in route["link_ids"]:
                    handle.write(f'        <link refId="{escape(link_id)}"/>\n')
                handle.write("      </route>\n      <departures>\n")
                for departure in route["departures"].sort_values("departure_seconds").itertuples(index=False):
                    handle.write(
                        f'        <departure id="{escape(safe_text(departure.departure_id))}" '
                        f'departureTime="{format_time(departure.departure_seconds)}" '
                        f'vehicleRefId="{escape(safe_text(departure.vehicle_id))}"/>\n'
                    )
                handle.write("      </departures>\n    </transitRoute>\n")
            handle.write("  </transitLine>\n")
        handle.write("</transitSchedule>\n")


def write_vehicles(path: Path, vehicle_types: pd.DataFrame, vehicles: pd.DataFrame) -> None:
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as handle:
        handle.write('<?xml version="1.0" encoding="utf-8"?>\n')
        handle.write(
            '<vehicleDefinitions xmlns="http://www.matsim.org/files/dtd" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xsi:schemaLocation="http://www.matsim.org/files/dtd '
            'http://www.matsim.org/files/dtd/vehicleDefinitions_v2.0.xsd">\n'
        )
        for row in vehicle_types.sort_values("vehicle_type_id").itertuples(index=False):
            handle.write(f'  <vehicleType id="{escape(safe_text(row.vehicle_type_id))}">\n')
            handle.write(
                f'    <capacity seats="{safe_int(row.model_seats)}" '
                f'standingRoomInPersons="{safe_int(row.model_standing)}"/>\n'
            )
            handle.write(f'    <length meter="{safe_float(row.length_m):.3f}"/>\n')
            handle.write(f'    <width meter="{safe_float(row.width_m):.3f}"/>\n')
            handle.write(f'    <passengerCarEquivalents pce="{safe_float(row.pce):.3f}"/>\n')
            handle.write(
                f'    <networkMode networkMode="{escape(MODE_TO_MATSIM[safe_text(row.mode)])}"/>\n'
            )
            handle.write("  </vehicleType>\n")
        for row in vehicles.sort_values("vehicle_id").itertuples(index=False):
            handle.write(
                f'  <vehicle id="{escape(safe_text(row.vehicle_id))}" '
                f'type="{escape(safe_text(row.vehicle_type_id))}"/>\n'
            )
        handle.write("</vehicleDefinitions>\n")


def write_config_template(path: Path) -> None:
    content = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE config SYSTEM "http://www.matsim.org/files/dtd/config_v2.dtd">
<config>
  <module name="global">
    <param name="coordinateSystem" value="{NETWORK_CRS}"/>
    <param name="numberOfThreads" value="8"/>
  </module>
  <module name="network">
    <param name="inputNetworkFile" value="network.xml.gz"/>
  </module>
  <module name="plans">
    <param name="inputPlansFile" value="REPLACE_WITH_HONG_KONG_PLANS.xml.gz"/>
  </module>
  <module name="transit">
    <param name="useTransit" value="true"/>
    <param name="transitScheduleFile" value="transitSchedule.xml.gz"/>
    <param name="vehiclesFile" value="transitVehicles.xml.gz"/>
    <param name="transitModes" value="bus,gmb,train,light_rail"/>
  </module>
  <module name="qsim">
    <param name="startTime" value="00:00:00"/>
    <param name="endTime" value="30:00:00"/>
    <param name="mainMode" value="car"/>
  </module>
  <module name="controller">
    <param name="firstIteration" value="0"/>
    <param name="lastIteration" value="0"/>
    <param name="outputDirectory" value="output-hong-kong-road-pt"/>
    <param name="overwriteFiles" value="deleteDirectoryIfExists"/>
  </module>
</config>
'''
    path.write_text(content, encoding="utf-8")


def write_augmented_network(
    source: Path,
    destination: Path,
    links: dict[str, NetworkLink],
    original_link_ids: set[str],
) -> int:
    additions = [links[link_id] for link_id in sorted(set(links) - original_link_ids)]
    with gzip.open(source, "rt", encoding="utf-8") as handle:
        content = handle.read()
    marker = "  </links>"
    if marker not in content:
        raise ValueError("Cannot locate MATSim network links closing tag")
    added_xml = "".join(
        f'    <link id="{escape(link.link_id)}" from="{escape(link.from_node)}" '
        f'to="{escape(link.to_node)}" length="{link.length_m:.3f}" '
        f'freespeed="{link.freespeed_mps:.3f}" capacity="1800" permlanes="1" '
        f'oneway="1" modes="{escape(",".join(sorted(link.modes)))}"/>\n'
        for link in additions
    )
    content = content.replace(marker, added_xml + marker, 1)
    with gzip.open(destination, "wt", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    return len(additions)


def apply_road_calibration(path: Path, attributes_path: Path) -> int:
    """Apply calibrated TNM road attributes without changing network structure."""
    attributes = pd.read_csv(attributes_path)
    required = {
        "route_id",
        "direction",
        "freespeed_mps",
        "capacity_vph",
        "permlanes",
    }
    missing = required - set(attributes.columns)
    if missing:
        raise ValueError(f"Road calibration table is missing columns: {sorted(missing)}")
    lookup = attributes.set_index(["route_id", "direction"]).to_dict("index")
    road_pattern = re.compile(r"^road_(\d+)_(\d+)_([fr])$")
    temporary = path.with_name(path.name + ".calibrating")
    changed = 0
    with gzip.open(path, "rt", encoding="utf-8") as reader, gzip.open(
        temporary, "wt", encoding="utf-8", newline="\n"
    ) as writer:
        for line in reader:
            if "<link " not in line:
                writer.write(line)
                continue
            id_match = re.search(r'\bid="([^"]+)"', line)
            road_match = road_pattern.match(id_match.group(1)) if id_match else None
            if not road_match:
                writer.write(line)
                continue
            route_id, _, direction = road_match.groups()
            item = lookup.get((int(route_id), direction))
            if item is None:
                writer.write(line)
                continue
            for name, value in (
                ("freespeed", float(item["freespeed_mps"])),
                ("capacity", float(item["capacity_vph"])),
                ("permlanes", float(item["permlanes"])),
            ):
                line = re.sub(
                    rf'({name}=")[^"]*(")',
                    rf"\g<1>{value:.6f}\g<2>",
                    line,
                    count=1,
                )
            changed += 1
            writer.write(line)
    temporary.replace(path)
    return changed


def xml_qa(
    schedule_path: Path,
    vehicles_path: Path,
    links: dict[str, NetworkLink],
) -> tuple[pd.DataFrame, dict[str, int]]:
    with gzip.open(schedule_path, "rb") as handle:
        schedule = ET.parse(handle).getroot()
    with gzip.open(vehicles_path, "rb") as handle:
        vehicles_root = ET.parse(handle).getroot()
    facilities = {item.attrib["id"]: item for item in schedule.find("transitStops") or []}
    local_name = lambda tag: tag.rsplit("}", 1)[-1]
    vehicle_types = {
        item.attrib["id"] for item in vehicles_root if local_name(item.tag) == "vehicleType"
    }
    vehicles = {
        item.attrib["id"]: item.attrib["type"]
        for item in vehicles_root
        if local_name(item.tag) == "vehicle"
    }
    route_count = departure_count = stop_ref_errors = link_ref_errors = 0
    vehicle_ref_errors = facility_link_errors = continuity_errors = mode_link_errors = 0
    departure_ids: set[str] = set()
    for line in schedule.findall("transitLine"):
        for route in line.findall("transitRoute"):
            route_count += 1
            mode = safe_text(route.findtext("transportMode"))
            route_link_ids = [item.attrib["refId"] for item in route.find("route") or []]
            link_ref_errors += sum(link_id not in links for link_id in route_link_ids)
            if all(link_id in links for link_id in route_link_ids):
                continuity_errors += check_continuity(route_link_ids, links)
                mode_link_errors += sum(mode not in links[link_id].modes for link_id in route_link_ids)
            route_links_set = set(route_link_ids)
            for stop in route.find("routeProfile") or []:
                facility = facilities.get(stop.attrib["refId"])
                if facility is None:
                    stop_ref_errors += 1
                elif facility.attrib.get("linkRefId") not in route_links_set:
                    facility_link_errors += 1
            for departure in route.find("departures") or []:
                departure_count += 1
                departure_ids.add(departure.attrib["id"])
                if departure.attrib.get("vehicleRefId") not in vehicles:
                    vehicle_ref_errors += 1
    invalid_vehicle_types = sum(value not in vehicle_types for value in vehicles.values())
    checks = [
        ("schedule_root", schedule.tag, "transitSchedule", schedule.tag == "transitSchedule"),
        ("route_count", route_count, 3574, route_count == 3574),
        ("duplicate_departure_ids", departure_count - len(departure_ids), 0, departure_count == len(departure_ids)),
        ("stop_reference_errors", stop_ref_errors, 0, stop_ref_errors == 0),
        ("facility_route_link_errors", facility_link_errors, 0, facility_link_errors == 0),
        ("network_link_reference_errors", link_ref_errors, 0, link_ref_errors == 0),
        ("route_continuity_errors", continuity_errors, 0, continuity_errors == 0),
        ("route_mode_link_errors", mode_link_errors, 0, mode_link_errors == 0),
        ("vehicle_reference_errors", vehicle_ref_errors, 0, vehicle_ref_errors == 0),
        ("invalid_vehicle_type_references", invalid_vehicle_types, 0, invalid_vehicle_types == 0),
        ("one_vehicle_per_departure", len(vehicles), departure_count, len(vehicles) == departure_count),
    ]
    counts = {
        "facilities": len(facilities),
        "routes": route_count,
        "departures": departure_count,
        "vehicle_types": len(vehicle_types),
        "vehicles": len(vehicles),
    }
    return pd.DataFrame(checks, columns=["check", "actual", "expected", "passed"]), counts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--representative-date", default=REPRESENTATIVE_DATE)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--road-calibration-attributes",
        type=Path,
        help="Optional road_route_direction_attributes.csv override.",
    )
    parser.add_argument(
        "--without-road-calibration",
        action="store_true",
        help="Keep the legacy uniform road attributes even if calibrated attributes exist.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data_root = args.data_root.resolve()
    processed = data_root / "transit" / "hongkong" / "processed"
    assembly = processed / "transit_schedule_assembly_inputs_2026"
    mapmatch = processed / "transit_route_link_mapmatching_2026_v2"
    timetable = processed / "mtr_lrt_approximate_timetable_2026_weekday"
    station_times = processed / "mtr_lrt_approximate_station_times_2026_weekday"
    capacities = processed / "public_transport_vehicle_capacities_inferred_2026"
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else processed / "matsim_road_pt_supply_2026_typical_weekday"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    network_source = mapmatch / "network" / "hong_kong_transit_base_network.xml.gz"
    network_output = output_dir / "network.xml.gz"
    schedule_output = output_dir / "transitSchedule.xml.gz"
    vehicles_output = output_dir / "transitVehicles.xml.gz"
    config_output = output_dir / "config-road-pt-template.xml"

    _, links = load_network(network_source)
    original_link_ids = set(links)
    approved = pd.read_csv(assembly / "approved_route_directions.csv", dtype=str, keep_default_na=False)
    route_links = pd.read_csv(assembly / "approved_route_link_sequences.csv", dtype=str, keep_default_na=False)
    route_links["sequence"] = pd.to_numeric(route_links["sequence"], errors="raise").astype(int)
    assignments = pd.read_csv(assembly / "route_stop_facility_assignments.csv", dtype=str, keep_default_na=False)
    facilities = pd.read_csv(assembly / "transit_stop_facilities.csv", dtype=str, keep_default_na=False)
    approved_road = approved[approved["mode"].isin(["bus", "gmb"])].copy()

    proxy_assignments, proxy_facilities, proxy_audit = build_endpoint_proxy_stops(
        approved, assignments, route_links, links
    )
    if not proxy_assignments.empty:
        assignments = pd.concat([assignments, proxy_assignments], ignore_index=True, sort=False)
        facilities = pd.concat([facilities, proxy_facilities], ignore_index=True, sort=False)

    road_departures, service_audit, gtfs_summary = expand_road_departures(
        data_root / "transit" / "hongkong" / "PublicTransportGTFS" / "gtfs.zip",
        approved_road,
        args.representative_date,
    )
    road_assignments = assignments[assignments["mode"].isin(["bus", "gmb"])]
    road_offsets = road_stop_offsets(road_assignments, route_links, facilities, links)

    patterns = pd.read_csv(timetable / "approximate_route_patterns.csv", dtype=str, keep_default_na=False)
    rail_departures = pd.read_csv(
        capacities / "mtr_lrt_departure_vehicle_assignments.csv", dtype=str, keep_default_na=False
    )
    rail_departures["departure_seconds"] = pd.to_numeric(
        rail_departures["departure_seconds"], errors="raise"
    ).astype(int)
    rail_offsets_source = pd.read_csv(
        station_times / "matsim_route_stop_offsets.csv", dtype=str, keep_default_na=False
    )
    coordinates = pd.read_csv(
        station_times / "station_coordinate_coverage_qa.csv", dtype=str, keep_default_na=False
    )
    rail_variants, rail_audit, rail_facilities = build_rail_variants(
        patterns, rail_offsets_source, coordinates, approved, route_links, links
    )

    routes: dict[str, dict[str, Any]] = {}
    link_ids_by_route = {
        route_key: group.sort_values("sequence")["link_id"].tolist()
        for route_key, group in route_links.groupby("route_key", sort=False)
    }
    road_offsets_by_route = {
        route_key: group.copy()
        for route_key, group in road_offsets.groupby("route_key", sort=False)
    }
    road_departures_by_route = {
        route_key: group.copy()
        for route_key, group in road_departures.groupby("route_key", sort=False)
    }
    for route in approved_road.itertuples(index=False):
        key = safe_text(route.route_key)
        routes[key] = {
            "route_key": key,
            "mode": safe_text(route.mode),
            "line_id": f"line_{route.mode}_{normalize_id(route.route_id)}",
            "route_name": safe_text(route.route_name) or key,
            "link_ids": link_ids_by_route[key],
            "stops": road_offsets_by_route[key],
            "departures": road_departures_by_route[key],
        }
    for key, variant in rail_variants.items():
        departures = rail_departures[rail_departures["route_variant_id"].eq(key)].copy()
        if departures.empty:
            raise ValueError(f"No rail departures for {key}")
        variant.update(
            {
                "line_id": f"line_{variant['mode']}_{variant['line_code']}",
                "departures": departures,
            }
        )
        routes[key] = variant

    used_road_facility_ids = set(road_offsets["facility_id"])
    output_facilities = pd.concat(
        [facilities[facilities["facility_id"].isin(used_road_facility_ids)], rail_facilities],
        ignore_index=True,
        sort=False,
    ).drop_duplicates("facility_id")

    road_vehicles = road_departures[
        ["vehicle_id", "vehicle_type_id", "departure_id", "route_key", "departure_seconds"]
    ].copy()
    rail_vehicles = rail_departures[
        ["vehicle_id", "vehicle_type_id", "departure_id", "route_variant_id", "departure_seconds"]
    ].rename(columns={"route_variant_id": "route_key"})
    all_vehicles = pd.concat([road_vehicles, rail_vehicles], ignore_index=True, sort=False)
    if all_vehicles["vehicle_id"].duplicated().any():
        raise ValueError("Duplicate vehicle IDs")
    vehicle_types = pd.read_csv(capacities / "matsim_vehicle_types.csv", dtype=str, keep_default_na=False)

    synthetic_reverse_links = write_augmented_network(
        network_source, network_output, links, original_link_ids
    )
    default_calibration = (
        processed
        / "road_speed_capacity_2026_v1"
        / "road_route_direction_attributes.csv"
    )
    calibration_path = (
        args.road_calibration_attributes.resolve()
        if args.road_calibration_attributes
        else default_calibration
    )
    calibrated_road_links = 0
    if not args.without_road_calibration and calibration_path.exists():
        calibrated_road_links = apply_road_calibration(network_output, calibration_path)
    write_schedule(schedule_output, output_facilities, routes)
    write_vehicles(vehicles_output, vehicle_types, all_vehicles)
    write_config_template(config_output)

    road_departures.to_csv(output_dir / "road_departure_manifest.csv", index=False, encoding="utf-8-sig")
    road_offsets.to_csv(output_dir / "road_route_stop_offsets.csv", index=False, encoding="utf-8-sig")
    rail_audit.to_csv(output_dir / "rail_variant_route_audit.csv", index=False, encoding="utf-8-sig")
    rail_facilities.to_csv(output_dir / "rail_variant_stop_facilities.csv", index=False, encoding="utf-8-sig")
    service_audit.to_csv(output_dir / "road_service_generation_audit.csv", index=False, encoding="utf-8-sig")
    proxy_audit.to_csv(output_dir / "endpoint_proxy_stop_audit.csv", index=False, encoding="utf-8-sig")
    all_vehicles.to_csv(output_dir / "departure_vehicle_assignments.csv", index=False, encoding="utf-8-sig")

    qa, counts = xml_qa(schedule_output, vehicles_output, links)
    qa.to_csv(output_dir / "matsim_supply_qa.csv", index=False, encoding="utf-8-sig")
    if not qa["passed"].all():
        raise RuntimeError(f"MATSim supply QA failed:\n{qa.loc[~qa['passed']].to_string(index=False)}")

    mode_route_counts = pd.Series([route["mode"] for route in routes.values()]).value_counts().to_dict()
    mode_departure_counts = pd.concat(
        [
            road_departures[["route_key", "departure_id"]].assign(
                mode=road_departures["route_key"].map(approved_road.set_index("route_key")["mode"])
            ),
            rail_departures[["route_variant_id", "departure_id", "mode"]].rename(
                columns={"route_variant_id": "route_key"}
            ),
        ],
        ignore_index=True,
    )["mode"].value_counts().to_dict()
    summary = {
        "scope": "Hong Kong road and public-transport supply; population plans intentionally excluded",
        "representative_service_date": args.representative_date,
        "crs": NETWORK_CRS,
        "network": {
            "source": str(network_source),
            "links": len(links),
            "road_links": sum(link_id.startswith("road_") for link_id in links),
            "rail_links": sum(link_id.startswith("rail_") for link_id in links),
            "synthetic_reverse_rail_connector_links": synthetic_reverse_links,
            "road_calibration_attributes": str(calibration_path)
            if calibrated_road_links
            else None,
            "calibrated_road_links": calibrated_road_links,
        },
        "schedule": {
            **counts,
            "routes_by_mode": mode_route_counts,
            "departures_by_mode": mode_departure_counts,
            "gtfs_road_service": gtfs_summary,
            "endpoint_proxy_route_directions": len(proxy_audit),
            "rail_station_snap_distance_m": percentile_summary(rail_audit["max_station_snap_m"]),
        },
        "assumptions": {
            "road_running_time": "map-matched distance at 7.0 m/s bus or 8.0 m/s GMB",
            "road_dwell_seconds": ROAD_DWELL_SECONDS,
            "road_fallback_service": "06:00-23:30; 15 min bus or 12 min GMB",
            "rail_timing": "published frequencies plus three next-train snapshots and inferred offsets",
            "vehicle_instances": "one vehicle per departure; blocks and interlining unavailable",
            "plans": "not generated in this step",
        },
        "outputs": {
            "network": str(network_output),
            "transit_schedule": str(schedule_output),
            "transit_vehicles": str(vehicles_output),
            "config_template": str(config_output),
        },
    }
    write_json(output_dir / "matsim_road_pt_supply_summary.json", summary)

    manifest_files = sorted(
        path for path in output_dir.iterdir() if path.is_file() and path.name != "SHA256SUMS.txt"
    )
    (output_dir / "SHA256SUMS.txt").write_text(
        "".join(f"{sha256_file(path)}  {path.name}\n" for path in manifest_files), encoding="ascii"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
