"""Calibrate Fuzhou bus-priority speeds and add targeted bus-metro transfers.

The input is the existing integrated car/bus-priority/metro MATSim supply.
Only ``busprio_*`` link freespeeds and bus routeProfile offsets are changed.
Car and metro links, capacities, lanes, departures, and vehicles are preserved.
Targeted bidirectional minimalTransferTimes are added between bus and metro
stop facilities within a configurable radius.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import shutil
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_DIR = (
    ROOT
    / "data"
    / "transit"
    / "fuzhou_transit_matsim_integrated_20260709_bus_priority_carcap5_floor_lanes_raw"
)
DEFAULT_OUTPUT_DIR = (
    ROOT
    / "data"
    / "transit"
    / "fuzhou_transit_matsim_integrated_20260709_bus_priority_speedcal_transfer300_carcap5"
)
DEFAULT_CAPACITY_QA = (
    ROOT
    / "data"
    / "transit"
    / "fuzhou_transit_matsim_integrated_20260709_capacity_lanes_v2_split_modes"
    / "capacity_reestimate_link_qa.csv"
)

SPEED_CAP_KMH = {
    "service": 15.0,
    "living_street": 15.0,
    "residential": 20.0,
    "unclassified": 20.0,
    "tertiary": 22.0,
    "tertiary_link": 22.0,
    "secondary": 25.0,
    "secondary_link": 25.0,
    "primary": 28.0,
    "primary_link": 28.0,
    "trunk": 30.0,
    "trunk_link": 30.0,
    "motorway": 30.0,
    "motorway_link": 30.0,
    "synthetic": 22.0,
    "unknown": 22.0,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", type=Path, default=DEFAULT_INPUT_DIR / "network_with_car_busprio_metro.xml.gz")
    parser.add_argument("--schedule", type=Path, default=DEFAULT_INPUT_DIR / "transitSchedule.xml.gz")
    parser.add_argument("--vehicles", type=Path, default=DEFAULT_INPUT_DIR / "transitVehicles.xml.gz")
    parser.add_argument("--capacity-qa", type=Path, default=DEFAULT_CAPACITY_QA)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--bus-stop-dwell-s", type=float, default=20.0)
    parser.add_argument("--transfer-radius-m", type=float, default=300.0)
    parser.add_argument("--transfer-walk-speed-mps", type=float, default=1.2)
    parser.add_argument("--transfer-fixed-time-s", type=float, default=60.0)
    parser.add_argument("--transfer-min-time-s", type=float, default=90.0)
    return parser.parse_args()


def read_xml_gz(path: Path) -> ET.ElementTree:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return ET.parse(handle)


def write_xml_gz(path: Path, root: ET.Element, doctype: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as handle:
        handle.write('<?xml version="1.0" encoding="utf-8"?>\n')
        handle.write(doctype)
        handle.write("\n\n")
        handle.write(ET.tostring(root, encoding="unicode", short_empty_elements=True))
        handle.write("\n")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def safe_float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def parse_time_s(value: str | None) -> float:
    if not value:
        return 0.0
    parts = value.split(":")
    if len(parts) != 3:
        return 0.0
    try:
        return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    except ValueError:
        return 0.0


def format_time_s(value: float) -> str:
    seconds = max(0, int(round(value)))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def load_highways(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {
            str(row.get("link_id", "")): str(row.get("highway", "")).strip().lower()
            for row in csv.DictReader(handle)
            if row.get("link_id")
        }


def busprio_road_class(link_id: str, highways: dict[str, str]) -> str:
    original_id = link_id.removeprefix("busprio_")
    if original_id.startswith("syn_bus_link_") or original_id.startswith("syn_bus_connector_"):
        return "synthetic"
    highway = highways.get(original_id, "")
    return highway if highway in SPEED_CAP_KMH else "unknown"


def route_and_stop_modes(schedule_root: ET.Element) -> tuple[Counter[str], dict[str, set[str]]]:
    route_modes: Counter[str] = Counter()
    stop_modes: dict[str, set[str]] = defaultdict(set)
    for line in schedule_root.findall("transitLine"):
        for route in line.findall("transitRoute"):
            mode = (route.findtext("transportMode") or "").strip()
            route_modes[mode] += 1
            profile = route.find("routeProfile")
            if profile is None:
                continue
            for stop in profile.findall("stop"):
                ref_id = stop.get("refId")
                if ref_id:
                    stop_modes[ref_id].add(mode)
    return route_modes, stop_modes


def find_monotonic_route_indices(
    route_refs: list[str], stop_refs: list[str], facility_link_refs: dict[str, str]
) -> tuple[list[int], list[str]]:
    indices: list[int] = []
    warnings: list[str] = []
    cursor = 0
    for stop_id in stop_refs:
        target = facility_link_refs.get(stop_id, "")
        found = next((idx for idx in range(cursor, len(route_refs)) if route_refs[idx] == target), None)
        if found is None:
            all_matches = [idx for idx, ref in enumerate(route_refs) if ref == target]
            if all_matches:
                found = min(all_matches, key=lambda idx: abs(idx - cursor))
                warnings.append(f"non_monotonic_fallback:{stop_id}:{target}")
            else:
                found = min(cursor, max(len(route_refs) - 1, 0))
                warnings.append(f"missing_stop_link:{stop_id}:{target}")
        found = max(found, indices[-1] if indices else 0)
        indices.append(found)
        cursor = found
    return indices, warnings


def recalibrate_bus_route_profiles(
    schedule_root: ET.Element,
    links: dict[str, ET.Element],
    facility_link_refs: dict[str, str],
    dwell_s: float,
) -> tuple[list[dict[str, Any]], list[str]]:
    qa_rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    for line in schedule_root.findall("transitLine"):
        line_id = line.get("id", "")
        for route in line.findall("transitRoute"):
            if (route.findtext("transportMode") or "").strip() != "bus":
                continue
            route_id = route.get("id", "")
            route_el = route.find("route")
            profile = route.find("routeProfile")
            if route_el is None or profile is None:
                warnings.append(f"missing_route_or_profile:{line_id}/{route_id}")
                continue
            route_refs = [link.get("refId", "") for link in route_el.findall("link")]
            stops = profile.findall("stop")
            stop_refs = [stop.get("refId", "") for stop in stops]
            if not route_refs or not stops:
                warnings.append(f"empty_route_or_profile:{line_id}/{route_id}")
                continue
            missing_links = [ref for ref in route_refs if ref not in links]
            if missing_links:
                warnings.append(f"missing_network_links:{line_id}/{route_id}:{len(missing_links)}")
                continue

            travel_times = [
                safe_float(links[ref].get("length")) / max(safe_float(links[ref].get("freespeed")), 1e-9)
                for ref in route_refs
            ]
            cumulative_after: list[float] = []
            cumulative = 0.0
            for travel_time in travel_times:
                cumulative += travel_time
                cumulative_after.append(cumulative)

            indices, index_warnings = find_monotonic_route_indices(route_refs, stop_refs, facility_link_refs)
            warnings.extend(f"{line_id}/{route_id}:{warning}" for warning in index_warnings)
            first_before = cumulative_after[indices[0]] - travel_times[indices[0]]
            old_terminal_s = parse_time_s(stops[-1].get("arrivalOffset"))
            last_departure_s = 0.0
            arrivals: list[float] = []
            for stop_idx, (stop, route_idx) in enumerate(zip(stops, indices)):
                if stop_idx == 0:
                    arrival_s = 0.0
                else:
                    road_elapsed_s = cumulative_after[route_idx] - first_before
                    arrival_s = road_elapsed_s + dwell_s * stop_idx
                    arrival_s = max(arrival_s, last_departure_s + 1.0)
                departure_s = arrival_s if stop_idx == len(stops) - 1 else arrival_s + dwell_s
                stop.set("arrivalOffset", format_time_s(arrival_s))
                stop.set("departureOffset", format_time_s(departure_s))
                arrivals.append(arrival_s)
                last_departure_s = departure_s

            route_length_m = sum(safe_float(links[ref].get("length")) for ref in route_refs)
            service_length_m = sum(
                safe_float(links[route_refs[idx]].get("length"))
                for idx in range(indices[0], indices[-1] + 1)
            )
            new_terminal_s = arrivals[-1]
            qa_rows.append(
                {
                    "line_id": line_id,
                    "route_id": route_id,
                    "stop_count": len(stops),
                    "route_link_count": len(route_refs),
                    "route_length_m": round(route_length_m, 3),
                    "service_length_m": round(service_length_m, 3),
                    "old_terminal_offset_s": round(old_terminal_s, 3),
                    "new_terminal_offset_s": round(new_terminal_s, 3),
                    "old_commercial_speed_kmh": round(service_length_m / old_terminal_s * 3.6, 3)
                    if old_terminal_s > 0
                    else "",
                    "new_commercial_speed_kmh": round(service_length_m / new_terminal_s * 3.6, 3)
                    if new_terminal_s > 0
                    else "",
                    "offsets_strictly_increasing": str(
                        all(arrivals[idx] > arrivals[idx - 1] for idx in range(1, len(arrivals)))
                    ).lower(),
                    "index_warning_count": len(index_warnings),
                }
            )
    return qa_rows, warnings


def add_targeted_transfers(
    schedule_root: ET.Element,
    stop_modes: dict[str, set[str]],
    radius_m: float,
    walk_speed_mps: float,
    fixed_time_s: float,
    minimum_time_s: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    transit_stops = schedule_root.find("transitStops")
    if transit_stops is None:
        raise ValueError("schedule has no transitStops")
    facilities = {stop.get("id", ""): stop for stop in transit_stops.findall("stopFacility")}
    bus_stops: list[tuple[str, float, float]] = []
    metro_stops: list[tuple[str, float, float]] = []
    for stop_id, modes in stop_modes.items():
        facility = facilities.get(stop_id)
        if facility is None:
            continue
        x = safe_float(facility.get("x"), math.nan)
        y = safe_float(facility.get("y"), math.nan)
        if not math.isfinite(x) or not math.isfinite(y):
            continue
        if "bus" in modes:
            bus_stops.append((stop_id, x, y))
        if "metro" in modes:
            metro_stops.append((stop_id, x, y))

    transfer_el = schedule_root.find("minimalTransferTimes")
    if transfer_el is None:
        transfer_el = ET.Element("minimalTransferTimes")
        children = list(schedule_root)
        insert_at = children.index(transit_stops) + 1
        schedule_root.insert(insert_at, transfer_el)

    relations: dict[tuple[str, str], float] = {}
    for relation in transfer_el.findall("relation"):
        key = (relation.get("fromStop", ""), relation.get("toStop", ""))
        transfer_time = safe_float(relation.get("transferTime"), math.inf)
        if key[0] and key[1] and math.isfinite(transfer_time):
            relations[key] = min(relations.get(key, math.inf), transfer_time)
    existing_relation_count = len(relations)

    cell_size = max(radius_m, 1.0)
    grid: dict[tuple[int, int], list[tuple[str, float, float]]] = defaultdict(list)
    for stop in bus_stops:
        grid[(math.floor(stop[1] / cell_size), math.floor(stop[2] / cell_size))].append(stop)

    qa_rows: list[dict[str, Any]] = []
    covered_metro_ids: set[str] = set()
    for metro_id, mx, my in metro_stops:
        cx, cy = math.floor(mx / cell_size), math.floor(my / cell_size)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for bus_id, bx, by in grid.get((cx + dx, cy + dy), []):
                    distance_m = math.hypot(mx - bx, my - by)
                    if distance_m > radius_m:
                        continue
                    transfer_time_s = max(minimum_time_s, fixed_time_s + distance_m / walk_speed_mps)
                    relations[(bus_id, metro_id)] = min(
                        relations.get((bus_id, metro_id), math.inf), transfer_time_s
                    )
                    relations[(metro_id, bus_id)] = min(
                        relations.get((metro_id, bus_id), math.inf), transfer_time_s
                    )
                    covered_metro_ids.add(metro_id)
                    qa_rows.append(
                        {
                            "bus_stop_facility": bus_id,
                            "metro_stop_facility": metro_id,
                            "distance_m": round(distance_m, 3),
                            "transfer_time_s": round(transfer_time_s, 3),
                        }
                    )

    for relation in list(transfer_el.findall("relation")):
        transfer_el.remove(relation)
    for (from_stop, to_stop), transfer_time_s in sorted(relations.items()):
        ET.SubElement(
            transfer_el,
            "relation",
            {
                "fromStop": from_stop,
                "toStop": to_stop,
                "transferTime": f"{transfer_time_s:.3f}",
            },
        )

    uncovered_rows = [
        {
            "metro_stop_facility": metro_id,
            "x": x,
            "y": y,
            "reason": f"no_bus_stop_within_{radius_m:g}m",
        }
        for metro_id, x, y in metro_stops
        if metro_id not in covered_metro_ids
    ]
    return qa_rows, uncovered_rows, existing_relation_count


def main() -> None:
    args = parse_args()
    started = time.time()
    for path in (args.network, args.schedule, args.vehicles):
        if not path.exists():
            raise FileNotFoundError(path)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    network_root = read_xml_gz(args.network).getroot()
    schedule_root = read_xml_gz(args.schedule).getroot()
    links_el = network_root.find("links")
    transit_stops = schedule_root.find("transitStops")
    if links_el is None or transit_stops is None:
        raise ValueError("network links or transit stops missing")
    links = {link.get("id", ""): link for link in links_el.findall("link")}
    highways = load_highways(args.capacity_qa)

    non_busprio_snapshot = {
        link_id: (
            link.get("freespeed", ""),
            link.get("capacity", ""),
            link.get("permlanes", ""),
            link.get("modes", ""),
        )
        for link_id, link in links.items()
        if not link_id.startswith("busprio_")
    }

    speed_rows: list[dict[str, Any]] = []
    for link_id, link in links.items():
        if not link_id.startswith("busprio_"):
            continue
        road_class = busprio_road_class(link_id, highways)
        cap_kmh = SPEED_CAP_KMH[road_class]
        old_speed_mps = safe_float(link.get("freespeed"))
        new_speed_mps = min(old_speed_mps, cap_kmh / 3.6)
        link.set("freespeed", f"{new_speed_mps:.6f}")
        speed_rows.append(
            {
                "link_id": link_id,
                "original_link_id": link_id.removeprefix("busprio_"),
                "road_class": road_class,
                "length_m": round(safe_float(link.get("length")), 3),
                "old_freespeed_kmh": round(old_speed_mps * 3.6, 3),
                "speed_cap_kmh": cap_kmh,
                "new_freespeed_kmh": round(new_speed_mps * 3.6, 3),
                "capacity": link.get("capacity", ""),
                "permlanes": link.get("permlanes", ""),
                "speed_was_capped": str(new_speed_mps < old_speed_mps - 1e-9).lower(),
            }
        )

    route_modes, stop_modes = route_and_stop_modes(schedule_root)
    facility_link_refs = {
        stop.get("id", ""): stop.get("linkRefId", "") for stop in transit_stops.findall("stopFacility")
    }
    timing_rows, timing_warnings = recalibrate_bus_route_profiles(
        schedule_root, links, facility_link_refs, args.bus_stop_dwell_s
    )
    transfer_rows, uncovered_rows, existing_relation_count = add_targeted_transfers(
        schedule_root,
        stop_modes,
        args.transfer_radius_m,
        args.transfer_walk_speed_mps,
        args.transfer_fixed_time_s,
        args.transfer_min_time_s,
    )

    non_busprio_after = {
        link_id: (
            link.get("freespeed", ""),
            link.get("capacity", ""),
            link.get("permlanes", ""),
            link.get("modes", ""),
        )
        for link_id, link in links.items()
        if not link_id.startswith("busprio_")
    }
    non_busprio_changed = [
        link_id for link_id, values in non_busprio_snapshot.items() if non_busprio_after.get(link_id) != values
    ]
    if non_busprio_changed:
        raise RuntimeError(f"{len(non_busprio_changed)} non-bus-priority links changed unexpectedly")

    network_ids = set(links)
    missing_route_links: list[str] = []
    missing_stop_links: list[str] = []
    departure_count = 0
    for line in schedule_root.findall("transitLine"):
        for route in line.findall("transitRoute"):
            route_el = route.find("route")
            if route_el is not None:
                missing_route_links.extend(
                    ref
                    for ref in (link.get("refId", "") for link in route_el.findall("link"))
                    if ref not in network_ids
                )
            departures = route.find("departures")
            if departures is not None:
                departure_count += len(departures.findall("departure"))
    for stop in transit_stops.findall("stopFacility"):
        ref = stop.get("linkRefId", "")
        if ref and ref not in network_ids:
            missing_stop_links.append(ref)
    if missing_route_links or missing_stop_links:
        raise RuntimeError(
            f"missing schedule references: route={len(missing_route_links)} stop={len(missing_stop_links)}"
        )

    output_network = args.out_dir / "network_with_car_busprio_metro.xml.gz"
    output_schedule = args.out_dir / "transitSchedule.xml.gz"
    output_vehicles = args.out_dir / "transitVehicles.xml.gz"
    write_xml_gz(output_network, network_root, '<!DOCTYPE network SYSTEM "http://www.matsim.org/files/dtd/network_v1.dtd">')
    write_xml_gz(
        output_schedule,
        schedule_root,
        '<!DOCTYPE transitSchedule SYSTEM "http://www.matsim.org/files/dtd/transitSchedule_v2.dtd">',
    )
    shutil.copy2(args.vehicles, output_vehicles)

    write_csv(
        args.out_dir / "bus_speed_link_qa.csv",
        speed_rows,
        [
            "link_id",
            "original_link_id",
            "road_class",
            "length_m",
            "old_freespeed_kmh",
            "speed_cap_kmh",
            "new_freespeed_kmh",
            "capacity",
            "permlanes",
            "speed_was_capped",
        ],
    )
    write_csv(
        args.out_dir / "bus_route_timing_qa.csv",
        timing_rows,
        [
            "line_id",
            "route_id",
            "stop_count",
            "route_link_count",
            "route_length_m",
            "service_length_m",
            "old_terminal_offset_s",
            "new_terminal_offset_s",
            "old_commercial_speed_kmh",
            "new_commercial_speed_kmh",
            "offsets_strictly_increasing",
            "index_warning_count",
        ],
    )
    write_csv(
        args.out_dir / "bus_metro_transfer_qa.csv",
        transfer_rows,
        ["bus_stop_facility", "metro_stop_facility", "distance_m", "transfer_time_s"],
    )
    write_csv(
        args.out_dir / "uncovered_metro_stop_facilities.csv",
        uncovered_rows,
        ["metro_stop_facility", "x", "y", "reason"],
    )
    write_csv(
        args.out_dir / "bus_route_timing_warnings.csv",
        [{"warning": warning} for warning in timing_warnings],
        ["warning"],
    )

    total_length = sum(row["length_m"] for row in speed_rows)
    old_time = sum(
        row["length_m"] / max(row["old_freespeed_kmh"] / 3.6, 1e-9) for row in speed_rows
    )
    new_time = sum(
        row["length_m"] / max(row["new_freespeed_kmh"] / 3.6, 1e-9) for row in speed_rows
    )
    summary = {
        "created_by": "scripts/calibrate_fuzhou_bus_priority_speed_and_transfers.py",
        "created_at_epoch": time.time(),
        "runtime_seconds": round(time.time() - started, 3),
        "inputs": {
            "network": str(args.network),
            "schedule": str(args.schedule),
            "vehicles": str(args.vehicles),
            "capacity_qa": str(args.capacity_qa),
        },
        "outputs": {
            "network": str(output_network),
            "schedule": str(output_schedule),
            "vehicles": str(output_vehicles),
        },
        "parameters": {
            "speed_caps_kmh": SPEED_CAP_KMH,
            "bus_stop_dwell_s": args.bus_stop_dwell_s,
            "transfer_radius_m": args.transfer_radius_m,
            "transfer_walk_speed_mps": args.transfer_walk_speed_mps,
            "transfer_fixed_time_s": args.transfer_fixed_time_s,
            "transfer_min_time_s": args.transfer_min_time_s,
        },
        "counts": {
            "network_links": len(links),
            "bus_priority_links": len(speed_rows),
            "bus_priority_links_capped": sum(row["speed_was_capped"] == "true" for row in speed_rows),
            "bus_routes_retimed": len(timing_rows),
            "route_modes": dict(route_modes),
            "departures": departure_count,
            "targeted_bus_metro_pairs": len(transfer_rows),
            "targeted_directional_relations": len(transfer_rows) * 2,
            "existing_transfer_relations": existing_relation_count,
            "covered_metro_stop_facilities": len({row["metro_stop_facility"] for row in transfer_rows}),
            "uncovered_metro_stop_facilities": len(uncovered_rows),
            "timing_warnings": len(timing_warnings),
        },
        "speed": {
            "old_length_harmonic_kmh": round(total_length / old_time * 3.6, 3) if old_time > 0 else None,
            "new_length_harmonic_kmh": round(total_length / new_time * 3.6, 3) if new_time > 0 else None,
        },
        "validation": {
            "non_bus_priority_links_unchanged": not non_busprio_changed,
            "missing_route_links": len(missing_route_links),
            "missing_stop_links": len(missing_stop_links),
            "all_bus_offsets_strictly_increasing": all(
                row["offsets_strictly_increasing"] == "true" for row in timing_rows
            ),
            "all_targeted_transfer_distances_within_radius": all(
                row["distance_m"] <= args.transfer_radius_m + 1e-6 for row in transfer_rows
            ),
        },
    }
    (args.out_dir / "bus_speed_transfer_calibration_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
