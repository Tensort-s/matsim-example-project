#!/usr/bin/env python3
"""Build an experienced-arrival PT timetable and 24:00-30:00 service wrap."""

from __future__ import annotations

import argparse
from collections import defaultdict
import contextlib
import copy
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
from typing import BinaryIO, Iterator
import xml.etree.ElementTree as ET


DAY_S = 86_400.0
VERSION = "hk_experienced_pt_timetable_v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-schedule", type=Path, required=True)
    parser.add_argument("--input-vehicles", type=Path, required=True)
    parser.add_argument("--experienced-events", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--bin-minutes", type=int, default=15)
    parser.add_argument("--minimum-delay-s", type=float, default=-300.0)
    parser.add_argument("--maximum-delay-s", type=float, default=3600.0)
    parser.add_argument("--minimum-running-time-ratio", type=float, default=0.25)
    parser.add_argument("--wrap-source-end-hour", type=float, default=6.0)
    parser.add_argument("--wrap-target-start-hour", type=float, default=24.0)
    parser.add_argument("--wrap-target-end-hour", type=float, default=30.0)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@contextlib.contextmanager
def open_binary(path: Path) -> Iterator[BinaryIO]:
    if path.suffix.lower() == ".gz":
        with gzip.open(path, "rb") as handle:
            yield handle
        return
    if path.suffix.lower() == ".zst":
        process = subprocess.Popen(
            ["zstd", "-q", "-dc", str(path)], stdout=subprocess.PIPE
        )
        assert process.stdout is not None
        try:
            yield process.stdout
        finally:
            process.stdout.close()
            if process.wait() != 0:
                raise RuntimeError(f"zstd failed for {path}")
        return
    with path.open("rb") as handle:
        yield handle


def byte_attribute(line: bytes, name: bytes) -> bytes:
    marker = name + b'="'
    start = line.find(marker)
    if start < 0:
        return b""
    start += len(marker)
    return line[start:line.find(b'"', start)]


def seconds(value: str | None) -> float:
    if value is None or value == "undefined":
        return math.nan
    parts = value.split(":")
    if len(parts) != 3:
        return float(value)
    return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])


def clock(value: float) -> str:
    # Round the complete value first so a value such as 14:47:59.9996 carries
    # into 14:48:00.000 instead of producing the invalid second field 60.000.
    milliseconds = max(0, int(round(max(0.0, value) * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    if millis == 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def median(values: list[float]) -> float:
    return float(statistics.median(values))


def clip(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, value))


def smooth_bins(raw: dict[int, float], bins_per_day: int) -> list[float]:
    if not raw:
        return [0.0] * bins_per_day
    available = sorted(raw)
    filled: list[float] = []
    for target in range(bins_per_day):
        nearest = min(
            available,
            key=lambda item: (min(abs(item - target), bins_per_day - abs(item - target)), item),
        )
        filled.append(raw[nearest])
    weights = (1.0, 2.0, 3.0, 2.0, 1.0)
    result = []
    for target in range(bins_per_day):
        values = [filled[(target + offset) % bins_per_day] for offset in range(-2, 3)]
        result.append(sum(value * weight for value, weight in zip(values, weights)) / sum(weights))
    return result


def interpolate_shapes(stops: list[str], known: dict[str, float]) -> list[float]:
    positions = [(index, known[stop]) for index, stop in enumerate(stops) if stop in known]
    if not positions:
        return [0.0] * len(stops)
    result = []
    for index in range(len(stops)):
        exact = next((value for position, value in positions if position == index), None)
        if exact is not None:
            result.append(exact)
            continue
        before = [(position, value) for position, value in positions if position < index]
        after = [(position, value) for position, value in positions if position > index]
        if not before:
            result.append(after[0][1])
        elif not after:
            result.append(before[-1][1])
        else:
            left_i, left = before[-1]
            right_i, right = after[0]
            fraction = (index - left_i) / (right_i - left_i)
            result.append(left + fraction * (right - left))
    return result


def write_xml_gz(tree: ET.ElementTree, path: Path, doctype: str) -> None:
    with path.open("xb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as handle:
            handle.write(b"<?xml version='1.0' encoding='UTF-8'?>\n")
            if doctype:
                handle.write(doctype.encode("utf-8") + b"\n")
            tree.write(handle, encoding="utf-8", xml_declaration=False, short_empty_elements=True)
            handle.write(b"\n")


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_event_delays(
    path: Path,
    departure_index: dict[str, tuple[str, str, float]],
    bin_seconds: float,
    minimum_delay: float,
    maximum_delay: float,
) -> tuple[dict[tuple[str, str, str, int], list[float]], dict[str, int]]:
    vehicle_to_departure: dict[bytes, str] = {}
    arrivals: dict[tuple[str, str, str, int], list[float]] = defaultdict(list)
    departures: dict[tuple[str, str, str, int], list[float]] = defaultdict(list)
    stats: dict[str, int] = defaultdict(int)
    with open_binary(path) as handle:
        for line in handle:
            if b"<event " not in line:
                continue
            event_type = byte_attribute(line, b"type")
            if event_type == b"TransitDriverStarts":
                vehicle = byte_attribute(line, b"vehicleId")
                departure = byte_attribute(line, b"departureId").decode()
                if vehicle and departure in departure_index:
                    vehicle_to_departure[vehicle] = departure
                    stats["mapped_driver_starts"] += 1
                else:
                    stats["unmapped_driver_starts"] += 1
                continue
            if event_type not in {b"VehicleArrivesAtFacility", b"VehicleDepartsAtFacility"}:
                continue
            vehicle = byte_attribute(line, b"vehicle")
            departure_id = vehicle_to_departure.get(vehicle)
            if departure_id is None:
                stats["facility_events_without_departure"] += 1
                continue
            line_id, route_id, departure_time = departure_index[departure_id]
            facility = byte_attribute(line, b"facility").decode()
            delay_raw = byte_attribute(line, b"delay")
            if not facility or not delay_raw:
                stats["facility_events_missing_value"] += 1
                continue
            raw = float(delay_raw)
            value = clip(raw, minimum_delay, maximum_delay)
            if not math.isclose(raw, value, abs_tol=1e-9):
                stats["clipped_delay_events"] += 1
            bin_index = int((departure_time % DAY_S) // bin_seconds)
            key = (line_id, route_id, facility, bin_index)
            target = departures if event_type == b"VehicleDepartsAtFacility" else arrivals
            target[key].append(value)
            stats[
                "departure_delay_events"
                if event_type == b"VehicleDepartsAtFacility"
                else "arrival_delay_events"
            ] += 1
    combined: dict[tuple[str, str, str, int], list[float]] = {}
    for key in set(arrivals) | set(departures):
        combined[key] = departures.get(key) or arrivals[key]
        if key not in departures:
            stats["arrival_fallback_groups"] += 1
    stats["delay_groups"] = len(combined)
    stats["mapped_vehicles"] = len(vehicle_to_departure)
    return combined, dict(stats)


def main() -> int:
    args = parse_args()
    for path in (args.input_schedule, args.input_vehicles, args.experienced_events):
        if not path.is_file():
            raise FileNotFoundError(path)
    if args.output_dir.exists():
        raise FileExistsError(args.output_dir)
    if 60 % args.bin_minutes:
        raise ValueError("--bin-minutes must divide one hour")
    if not (0 < args.minimum_running_time_ratio <= 1):
        raise ValueError("--minimum-running-time-ratio must be in (0,1]")
    bin_seconds = args.bin_minutes * 60.0
    bins_per_day = int(DAY_S / bin_seconds)

    with open_binary(args.input_schedule) as handle:
        schedule_tree = ET.parse(handle)
    schedule_root = schedule_tree.getroot()
    routes: dict[tuple[str, str], dict[str, object]] = {}
    departure_index: dict[str, tuple[str, str, float]] = {}
    original_departure_ids: set[str] = set()
    for line in schedule_root.findall("transitLine"):
        line_id = line.get("id", "")
        for route in line.findall("transitRoute"):
            route_id = route.get("id", "")
            profile = route.find("routeProfile")
            departures_element = route.find("departures")
            if profile is None or departures_element is None:
                raise ValueError(f"Route lacks profile/departures: {line_id}/{route_id}")
            stops = profile.findall("stop")
            departures = departures_element.findall("departure")
            key = (line_id, route_id)
            routes[key] = {
                "element": route,
                "stops": stops,
                "departures_element": departures_element,
                "departures": departures,
            }
            for departure in departures:
                departure_id = departure.get("id", "")
                if not departure_id or departure_id in departure_index:
                    raise ValueError(f"Missing/duplicate departure ID: {departure_id}")
                departure_time = seconds(departure.get("departureTime"))
                departure_index[departure_id] = (line_id, route_id, departure_time)
                original_departure_ids.add(departure_id)

    observations, event_stats = read_event_delays(
        args.experienced_events, departure_index, bin_seconds,
        args.minimum_delay_s, args.maximum_delay_s,
    )

    route_observations: dict[tuple[str, str], list[tuple[str, int, float, int]]] = defaultdict(list)
    for (line_id, route_id, facility, bin_index), values in observations.items():
        route_observations[(line_id, route_id)].append(
            (facility, bin_index, median(values), len(values))
        )

    stop_rows: list[dict[str, object]] = []
    bin_rows: list[dict[str, object]] = []
    departure_rows: list[dict[str, object]] = []
    day2_rows: list[dict[str, object]] = []
    route_models: dict[tuple[str, str], tuple[list[float], list[float], float]] = {}
    routes_with_observations = 0
    monotonic_stop_corrections = 0

    for key in sorted(routes):
        line_id, route_id = key
        item = routes[key]
        stops: list[ET.Element] = item["stops"]  # type: ignore[assignment]
        facilities = [stop.get("refId", "") for stop in stops]
        obs = route_observations.get(key, [])
        if obs:
            routes_with_observations += 1
        shape_by_stop: dict[str, float] = {}
        for facility in facilities:
            values = [value for stop, _, value, _ in obs if stop == facility]
            if values:
                shape_by_stop[facility] = median(values)
        bin_shift = [0.0] * bins_per_day
        for _ in range(2):
            raw_bins: dict[int, float] = {}
            for bin_index in range(bins_per_day):
                residuals = [
                    value - shape_by_stop.get(facility, 0.0)
                    for facility, observed_bin, value, _ in obs
                    if observed_bin == bin_index
                ]
                if residuals:
                    raw_bins[bin_index] = median(residuals)
            bin_shift = smooth_bins(raw_bins, bins_per_day)
            updated: dict[str, float] = {}
            for facility in facilities:
                residuals = [
                    value - bin_shift[bin_index]
                    for observed_facility, bin_index, value, _ in obs
                    if observed_facility == facility
                ]
                if residuals:
                    updated[facility] = median(residuals)
            if updated:
                shape_by_stop = updated
        shapes = interpolate_shapes(facilities, shape_by_stop)
        anchor = shapes[0] if shapes else 0.0
        shapes = [clip(value - anchor, args.minimum_delay_s, args.maximum_delay_s) for value in shapes]
        bin_shift = [clip(value + anchor, args.minimum_delay_s, args.maximum_delay_s) for value in bin_shift]

        original_arrivals: list[float] = []
        original_departures: list[float] = []
        for index, stop in enumerate(stops):
            arrival = seconds(stop.get("arrivalOffset"))
            departure = seconds(stop.get("departureOffset"))
            if math.isnan(arrival):
                arrival = departure if not math.isnan(departure) else (original_departures[-1] if index else 0.0)
            if math.isnan(departure):
                departure = arrival
            original_arrivals.append(arrival)
            original_departures.append(departure)
        offset_anchor = original_departures[0] + (shapes[0] if shapes else 0.0)
        adjusted_arrivals: list[float] = []
        adjusted_departures: list[float] = []
        for index, stop in enumerate(stops):
            target_arrival = original_arrivals[index] + shapes[index] - offset_anchor
            target_departure = original_departures[index] + shapes[index] - offset_anchor
            if index == 0:
                arrival = max(0.0, target_arrival)
            else:
                original_run = max(0.0, original_arrivals[index] - original_departures[index - 1])
                minimum_run = max(1.0, args.minimum_running_time_ratio * original_run)
                arrival = max(target_arrival, adjusted_departures[-1] + minimum_run)
                if arrival > target_arrival + 1e-9:
                    monotonic_stop_corrections += 1
            dwell = max(0.0, original_departures[index] - original_arrivals[index])
            minimum_dwell = 0.0 if index == len(stops) - 1 else min(5.0, dwell)
            departure = max(target_departure, arrival + minimum_dwell)
            adjusted_arrivals.append(arrival)
            adjusted_departures.append(departure)
            stop.set("arrivalOffset", clock(arrival))
            stop.set("departureOffset", clock(departure))
            samples = sum(count for facility, _, _, count in obs if facility == facilities[index])
            stop_rows.append({
                "line_id": line_id,
                "route_id": route_id,
                "stop_index": index,
                "facility_id": facilities[index],
                "observation_count": samples,
                "delay_shape_s": f"{shapes[index]:.6f}",
                "original_arrival_offset_s": f"{original_arrivals[index]:.6f}",
                "adjusted_arrival_offset_s": f"{arrival:.6f}",
                "original_departure_offset_s": f"{original_departures[index]:.6f}",
                "adjusted_departure_offset_s": f"{departure:.6f}",
            })
        route_models[key] = (shapes, bin_shift, offset_anchor)
        counts_by_bin = defaultdict(int)
        for _, bin_index, _, count in obs:
            counts_by_bin[bin_index] += count
        for bin_index, shift in enumerate(bin_shift):
            bin_rows.append({
                "line_id": line_id,
                "route_id": route_id,
                "bin_index": bin_index,
                "bin_start_s": int(bin_index * bin_seconds),
                "observation_count": counts_by_bin[bin_index],
                "departure_time_shift_s": f"{shift + offset_anchor:.6f}",
            })

    adjusted_by_departure: dict[str, float] = {}
    monotonic_departure_corrections = 0
    for key in sorted(routes):
        line_id, route_id = key
        item = routes[key]
        departures: list[ET.Element] = item["departures"]  # type: ignore[assignment]
        _, shifts, offset_anchor = route_models[key]
        previous = -math.inf
        for departure in sorted(departures, key=lambda element: departure_index[element.get("id", "")][2]):
            departure_id = departure.get("id", "")
            original = departure_index[departure_id][2]
            bin_index = int((original % DAY_S) // bin_seconds)
            raw_target = max(0.0, original + shifts[bin_index] + offset_anchor)
            adjusted = max(raw_target, previous + 1.0)
            if adjusted > raw_target + 1e-9:
                monotonic_departure_corrections += 1
            previous = adjusted
            adjusted_by_departure[departure_id] = adjusted
            departure.set("departureTime", clock(adjusted))
            departure_rows.append({
                "line_id": line_id,
                "route_id": route_id,
                "departure_id": departure_id,
                "vehicle_id": departure.get("vehicleRefId", ""),
                "source_bin": bin_index,
                "original_departure_time_s": f"{original:.6f}",
                "adjusted_departure_time_s": f"{adjusted:.6f}",
                "applied_shift_s": f"{adjusted - original:.6f}",
            })

    ET.register_namespace("", "http://www.matsim.org/files/dtd")
    ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")
    with open_binary(args.input_vehicles) as handle:
        vehicles_tree = ET.parse(handle)
    vehicles_root = vehicles_tree.getroot()
    vehicle_elements = {
        element.get("id", ""): element
        for element in vehicles_root.iter()
        if local_name(element.tag) == "vehicle" and element.get("id")
    }
    existing_vehicle_ids = set(vehicle_elements)
    existing_departure_ids = set(original_departure_ids)
    wrap_source_end = args.wrap_source_end_hour * 3600
    wrap_target_start = args.wrap_target_start_hour * 3600
    wrap_target_end = args.wrap_target_end_hour * 3600
    if not math.isclose(wrap_target_start, DAY_S, abs_tol=1e-9):
        raise ValueError("This v1 builder requires wrap target to start at 24:00")
    existing_times_by_route = {
        key: [adjusted_by_departure[element.get("id", "")] for element in item["departures"]]
        for key, item in routes.items()
    }
    for key in sorted(routes):
        line_id, route_id = key
        item = routes[key]
        departures_element: ET.Element = item["departures_element"]  # type: ignore[assignment]
        originals: list[ET.Element] = list(item["departures"])  # type: ignore[arg-type]
        for departure in originals:
            departure_id = departure.get("id", "")
            original_time = departure_index[departure_id][2]
            if not (0.0 <= original_time < wrap_source_end):
                continue
            target_time = adjusted_by_departure[departure_id] + DAY_S
            if not (wrap_target_start <= target_time < wrap_target_end):
                continue
            if any(abs(existing - target_time) <= 30.0 for existing in existing_times_by_route[key]
                   if existing >= wrap_target_start):
                continue
            source_vehicle = departure.get("vehicleRefId", "")
            if source_vehicle not in vehicle_elements:
                raise ValueError(f"Departure references missing vehicle: {departure_id}/{source_vehicle}")
            new_departure_id = f"{departure_id}__day2"
            new_vehicle_id = f"{source_vehicle}__day2"
            if new_departure_id in existing_departure_ids or new_vehicle_id in existing_vehicle_ids:
                raise ValueError(f"Day-2 ID collision: {new_departure_id}/{new_vehicle_id}")
            clone_departure = copy.deepcopy(departure)
            clone_departure.set("id", new_departure_id)
            clone_departure.set("departureTime", clock(target_time))
            clone_departure.set("vehicleRefId", new_vehicle_id)
            departures_element.append(clone_departure)
            clone_vehicle = copy.deepcopy(vehicle_elements[source_vehicle])
            clone_vehicle.set("id", new_vehicle_id)
            vehicles_root.append(clone_vehicle)
            existing_departure_ids.add(new_departure_id)
            existing_vehicle_ids.add(new_vehicle_id)
            existing_times_by_route[key].append(target_time)
            day2_rows.append({
                "line_id": line_id,
                "route_id": route_id,
                "source_departure_id": departure_id,
                "source_vehicle_id": source_vehicle,
                "day2_departure_id": new_departure_id,
                "day2_vehicle_id": new_vehicle_id,
                "day2_departure_time_s": f"{target_time:.6f}",
            })

    all_departures = [
        departure
        for line in schedule_root.findall("transitLine")
        for route in line.findall("transitRoute")
        for departure in route.findall("departures/departure")
    ]
    all_departure_ids = [departure.get("id", "") for departure in all_departures]
    all_vehicle_refs = {departure.get("vehicleRefId", "") for departure in all_departures}
    if len(all_departure_ids) != len(set(all_departure_ids)):
        raise RuntimeError("Output schedule has duplicate departure IDs")
    missing_vehicles = sorted(all_vehicle_refs - existing_vehicle_ids)
    if missing_vehicles:
        raise RuntimeError(f"Output schedule references missing vehicles: {missing_vehicles[:10]}")

    args.output_dir.mkdir(parents=True)
    schedule_output = args.output_dir / "transitSchedule_experienced_day2_v1.xml.gz"
    vehicles_output = args.output_dir / "transitVehicles_experienced_day2_v1.xml.gz"
    write_xml_gz(
        schedule_tree, schedule_output,
        '<!DOCTYPE transitSchedule SYSTEM "http://www.matsim.org/files/dtd/transitSchedule_v2.dtd">',
    )
    write_xml_gz(vehicles_tree, vehicles_output, "")
    write_csv(
        args.output_dir / "pt_experienced_delay_by_route_stop.csv", stop_rows,
        ["line_id", "route_id", "stop_index", "facility_id", "observation_count",
         "delay_shape_s", "original_arrival_offset_s", "adjusted_arrival_offset_s",
         "original_departure_offset_s", "adjusted_departure_offset_s"],
    )
    write_csv(
        args.output_dir / "pt_experienced_15min_shift.csv", bin_rows,
        ["line_id", "route_id", "bin_index", "bin_start_s", "observation_count",
         "departure_time_shift_s"],
    )
    write_csv(
        args.output_dir / "pt_departure_time_changes.csv", departure_rows,
        ["line_id", "route_id", "departure_id", "vehicle_id", "source_bin",
         "original_departure_time_s", "adjusted_departure_time_s", "applied_shift_s"],
    )
    write_csv(
        args.output_dir / "pt_day2_departures.csv", day2_rows,
        ["line_id", "route_id", "source_departure_id", "source_vehicle_id",
         "day2_departure_id", "day2_vehicle_id", "day2_departure_time_s"],
    )
    summary = {
        "status": "candidate_generated_not_adopted",
        "parameter_version": VERSION,
        "method": {
            "delay_model": "route_stop_shape_plus_route_15min_shift",
            "route_line_stop_ids_preserved": True,
            "delay_clip_s": [args.minimum_delay_s, args.maximum_delay_s],
            "minimum_running_time_ratio": args.minimum_running_time_ratio,
            "wrap_source_hours": [0.0, args.wrap_source_end_hour],
            "wrap_target_hours": [args.wrap_target_start_hour, args.wrap_target_end_hour],
        },
        "counts": {
            "lines": len(schedule_root.findall("transitLine")),
            "routes": len(routes),
            "routes_with_experienced_observations": routes_with_observations,
            "original_departures": len(original_departure_ids),
            "output_departures": len(all_departures),
            "day2_departures_added": len(day2_rows),
            "input_vehicles": len(vehicle_elements),
            "output_vehicles": len(existing_vehicle_ids),
            "monotonic_stop_corrections": monotonic_stop_corrections,
            "monotonic_departure_corrections": monotonic_departure_corrections,
            **event_stats,
        },
        "qa": {
            "duplicate_departure_ids": 0,
            "missing_vehicle_references": 0,
            "all_adjusted_stop_offsets_monotonic": True,
            "day2_departure_times_within_target": all(
                wrap_target_start <= float(row["day2_departure_time_s"]) < wrap_target_end
                for row in day2_rows
            ),
        },
        "inputs": {
            "schedule": str(args.input_schedule),
            "schedule_sha256": sha256(args.input_schedule),
            "vehicles": str(args.input_vehicles),
            "vehicles_sha256": sha256(args.input_vehicles),
            "experienced_events": str(args.experienced_events),
            "experienced_events_sha256": sha256(args.experienced_events),
        },
        "outputs": {
            "schedule": str(schedule_output),
            "schedule_sha256": sha256(schedule_output),
            "vehicles": str(vehicles_output),
            "vehicles_sha256": sha256(vehicles_output),
        },
    }
    summary_path = args.output_dir / "experienced_pt_timetable_candidate_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
