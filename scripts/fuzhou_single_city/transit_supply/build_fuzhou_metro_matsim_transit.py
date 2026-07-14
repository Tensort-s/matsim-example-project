#!/usr/bin/env python3
"""Build a MATSim-ready Fuzhou metro transit network, schedule, and vehicles.

Inputs are the previously cleaned AMap metro station/order/frequency data,
unified EPSG:32650 coordinates, and AMap-route-derived freespeeds.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UNIFIED_DIR = ROOT / "data" / "transit" / "fuzhou_transit_coordinates_unified_20260709"
DEFAULT_METRO_DIR = ROOT / "data" / "transit" / "fuzhou_metro_final_20260709"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "transit" / "fuzhou_metro_matsim_network_20260709"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def xml_attr(value: Any) -> str:
    return escape(str(value), {'"': "&quot;"})


def normalize(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", "", value).replace("（", "(").replace("）", ")")


def safe_float(value: Any, default: float = 0.0) -> float:
    if value in ("", None):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    if value in ("", None):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def parse_hms(value: str) -> int:
    hh, mm, ss = [int(part) for part in value.split(":")]
    return hh * 3600 + mm * 60 + ss


def format_hms(seconds: float) -> str:
    seconds_i = int(round(seconds))
    hh = seconds_i // 3600
    mm = (seconds_i % 3600) // 60
    ss = seconds_i % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}"


def line_family(line_name: str) -> str:
    name = normalize(line_name)
    if name.startswith("地铁1号线"):
        return "metro_1"
    if name.startswith("地铁2号线"):
        return "metro_2"
    if name.startswith("地铁4号线"):
        return "metro_4"
    if name.startswith("地铁5号线"):
        return "metro_5"
    if name.startswith("地铁6号线"):
        return "metro_6"
    if name.startswith("滨海快线"):
        return "metro_binhai_f1"
    return "metro_" + re.sub(r"[^A-Za-z0-9]+", "_", line_name).strip("_")


def vehicle_type_for_line(line_name: str) -> tuple[str, int, str]:
    name = normalize(line_name)
    if name.startswith("地铁6号线"):
        return "metro_b_4car_capacity_1358", 1358, "B型4节编组，按最大载客能力1358人/列"
    if name.startswith("滨海快线"):
        return "metro_f1_4car_capacity_1084", 1084, "市域A型/F1 4节编组，按最大载客能力1084人/列"
    return "metro_b_b2_6car_capacity_1460", 1460, "B型/B2型6节编组，额定6人/㎡约1460人/列"


def make_node_id(station_id: str) -> str:
    return f"metro_node_{station_id}"


def make_link_id(line_id: str, from_seq: int, to_seq: int) -> str:
    return f"metro_link_{line_id}_{from_seq:03d}_{to_seq:03d}"


def make_stop_facility_id(line_id: str, sequence: int, station_id: str) -> str:
    return f"metro_stop_{line_id}_{sequence:03d}_{station_id}"


def load_inputs(args: argparse.Namespace) -> dict[str, Any]:
    stops = read_csv(args.stops_by_line_csv)
    speeds = {row["line_id"]: row for row in read_csv(args.speed_csv)}
    frequencies = read_csv(args.frequency_csv)
    return {"stops": stops, "speeds": speeds, "frequencies": frequencies}


def build_lines(inputs: dict[str, Any]) -> list[dict[str, Any]]:
    stops_by_line: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in inputs["stops"]:
        stops_by_line[row["line_id"]].append(row)

    freq_by_line: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in inputs["frequencies"]:
        if row.get("day_type") == "weekday":
            freq_by_line[row["line_id"]].append(row)
    if not freq_by_line:
        for row in inputs["frequencies"]:
            freq_by_line[row["line_id"]].append(row)

    lines: list[dict[str, Any]] = []
    for line_id, stops in sorted(stops_by_line.items()):
        stops_sorted = sorted(stops, key=lambda row: safe_int(row.get("sequence")))
        speed_row = inputs["speeds"].get(line_id)
        if not speed_row:
            raise ValueError(f"Missing speed estimate for line_id={line_id}")
        freespeed = safe_float(speed_row.get("matsim_freespeed_mps"))
        api_distance = safe_float(speed_row.get("api_line_distance_m"))
        if freespeed <= 0 or api_distance <= 0:
            raise ValueError(f"Invalid speed/distance for line_id={line_id}")
        if not freq_by_line.get(line_id):
            raise ValueError(f"Missing weekday frequency rows for line_id={line_id}")
        lines.append(
            {
                "line_id": line_id,
                "line_name": stops_sorted[0]["line_name"],
                "stops": stops_sorted,
                "freespeed_mps": freespeed,
                "api_line_distance_m": api_distance,
                "speed_source_status": speed_row.get("estimate_status", ""),
                "frequency_rows": sorted(freq_by_line[line_id], key=lambda row: row.get("period_start", "")),
            }
        )
    return lines


def euclidean(a: dict[str, str], b: dict[str, str]) -> float:
    dx = safe_float(a.get("x_epsg32650")) - safe_float(b.get("x_epsg32650"))
    dy = safe_float(a.get("y_epsg32650")) - safe_float(b.get("y_epsg32650"))
    return math.hypot(dx, dy)


def allocate_link_lengths(line: dict[str, Any]) -> list[float]:
    stops = line["stops"]
    raw = [max(euclidean(stops[i], stops[i + 1]), 1.0) for i in range(len(stops) - 1)]
    total_raw = sum(raw)
    if total_raw <= 0:
        raise ValueError(f"Invalid station geometry for {line['line_id']}")
    return [distance / total_raw * line["api_line_distance_m"] for distance in raw]


def make_route_offsets(line: dict[str, Any], link_lengths: list[float], dwell_s: float) -> list[dict[str, Any]]:
    stops = line["stops"]
    offsets: list[dict[str, Any]] = []
    current_s = 0.0
    for idx, stop in enumerate(stops):
        sequence = safe_int(stop["sequence"])
        if idx == 0:
            arrival_s = 0.0
            departure_s = 0.0
        else:
            current_s += link_lengths[idx - 1] / line["freespeed_mps"]
            arrival_s = current_s
            departure_s = arrival_s if idx == len(stops) - 1 else arrival_s + dwell_s
            current_s = departure_s
        if idx < len(stops) - 1:
            link_ref = make_link_id(line["line_id"], sequence, safe_int(stops[idx + 1]["sequence"]))
        else:
            link_ref = make_link_id(line["line_id"], safe_int(stops[idx - 1]["sequence"]), sequence)
        offsets.append(
            {
                "sequence": sequence,
                "station_id": stop["station_id"],
                "station_name": stop["station_name"],
                "facility_id": make_stop_facility_id(line["line_id"], sequence, stop["station_id"]),
                "link_ref_id": link_ref,
                "arrival_s": arrival_s,
                "departure_s": departure_s,
            }
        )
    return offsets


def generate_departure_times(frequency_rows: list[dict[str, str]]) -> list[tuple[int, str, float]]:
    departures: list[tuple[int, str, float]] = []
    for row in frequency_rows:
        start = parse_hms(row["period_start"])
        end = parse_hms(row["period_end"])
        headway_min = safe_float(row.get("headway_minutes"))
        if headway_min <= 0:
            continue
        headway_s = int(round(headway_min * 60))
        t = start
        while t < end:
            departures.append((t, f"{row['period_start']}-{row['period_end']}", headway_min))
            t += headway_s
    departures = sorted(set(departures), key=lambda item: item[0])
    return departures


def write_network(path: Path, nodes: dict[str, dict[str, Any]], links: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n')
        f.write('<!DOCTYPE network SYSTEM "http://www.matsim.org/files/dtd/network_v1.dtd">\n\n')
        f.write('<network name="Fuzhou metro transit network EPSG:32650">\n')
        f.write("  <nodes>\n")
        for node_id in sorted(nodes):
            node = nodes[node_id]
            f.write(f'    <node id="{xml_attr(node_id)}" x="{node["x"]:.3f}" y="{node["y"]:.3f}" />\n')
        f.write("  </nodes>\n")
        f.write('  <links capperiod="01:00:00">\n')
        for link in links:
            f.write(
                f'    <link id="{xml_attr(link["id"])}" from="{xml_attr(link["from"])}" '
                f'to="{xml_attr(link["to"])}" length="{link["length"]:.3f}" '
                f'freespeed="{link["freespeed"]:.4f}" capacity="100000.0" '
                f'permlanes="1.0" modes="pt" />\n'
            )
        f.write("  </links>\n")
        f.write("</network>\n")


def write_schedule(path: Path, lines: list[dict[str, Any]], route_data: dict[str, dict[str, Any]]) -> None:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for line in lines:
        grouped[line_family(line["line_name"])].append(line)

    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n')
        f.write('<!DOCTYPE transitSchedule SYSTEM "http://www.matsim.org/files/dtd/transitSchedule_v2.dtd">\n\n')
        f.write("<transitSchedule>\n")
        f.write("  <transitStops>\n")
        for line in lines:
            data = route_data[line["line_id"]]
            for stop in data["route_offsets"]:
                original = data["stops_by_sequence"][stop["sequence"]]
                f.write(
                    f'    <stopFacility id="{xml_attr(stop["facility_id"])}" '
                    f'x="{safe_float(original["x_epsg32650"]):.3f}" '
                    f'y="{safe_float(original["y_epsg32650"]):.3f}" '
                    f'linkRefId="{xml_attr(stop["link_ref_id"])}" '
                    f'name="{xml_attr(original["station_name"])}" isBlocking="false" />\n'
                )
        f.write("  </transitStops>\n")
        for transit_line_id in sorted(grouped):
            f.write(f'  <transitLine id="{xml_attr(transit_line_id)}">\n')
            for line in sorted(grouped[transit_line_id], key=lambda item: item["line_id"]):
                data = route_data[line["line_id"]]
                route_id = f"metro_route_{line['line_id']}"
                f.write(f'    <transitRoute id="{xml_attr(route_id)}">\n')
                f.write("      <transportMode>pt</transportMode>\n")
                f.write("      <routeProfile>\n")
                for stop in data["route_offsets"]:
                    f.write(
                        f'        <stop refId="{xml_attr(stop["facility_id"])}" '
                        f'arrivalOffset="{format_hms(stop["arrival_s"])}" '
                        f'departureOffset="{format_hms(stop["departure_s"])}" />\n'
                    )
                f.write("      </routeProfile>\n")
                f.write("      <route>\n")
                for link_id in data["route_link_ids"]:
                    f.write(f'        <link refId="{xml_attr(link_id)}" />\n')
                f.write("      </route>\n")
                f.write("      <departures>\n")
                for idx, (departure_s, _, _) in enumerate(data["departures"], start=1):
                    departure_id = f"dep_{line['line_id']}_{idx:04d}"
                    vehicle_id = f"metro_vehicle_{line['line_id']}_{idx:04d}"
                    f.write(
                        f'        <departure id="{xml_attr(departure_id)}" '
                        f'departureTime="{format_hms(departure_s)}" '
                        f'vehicleRefId="{xml_attr(vehicle_id)}" />\n'
                    )
                f.write("      </departures>\n")
                f.write("    </transitRoute>\n")
            f.write("  </transitLine>\n")
        f.write("</transitSchedule>\n")


def write_vehicles(path: Path, lines: list[dict[str, Any]], route_data: dict[str, dict[str, Any]]) -> None:
    type_info: dict[str, tuple[int, str]] = {}
    for line in lines:
        type_id, capacity, note = vehicle_type_for_line(line["line_name"])
        type_info[type_id] = (capacity, note)

    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n')
        f.write('<!DOCTYPE vehicleDefinitions SYSTEM "http://www.matsim.org/files/dtd/vehicleDefinitions_v1.dtd">\n\n')
        f.write("<vehicleDefinitions>\n")
        for type_id in sorted(type_info):
            capacity, _ = type_info[type_id]
            seats = int(round(capacity * 0.25))
            standing = capacity - seats
            f.write(f'  <vehicleType id="{xml_attr(type_id)}">\n')
            f.write(f'    <capacity seats="{seats}" standingRoomInPersons="{standing}" />\n')
            f.write('    <length meter="120.0" />\n')
            f.write('    <width meter="3.0" />\n')
            f.write('    <accessTime secondsPerPerson="0.5" />\n')
            f.write('    <egressTime secondsPerPerson="0.5" />\n')
            f.write('    <doorOperation mode="parallel" />\n')
            f.write('    <passengerCarEquivalents pce="0.0" />\n')
            f.write("  </vehicleType>\n")
        for line in sorted(lines, key=lambda item: item["line_id"]):
            type_id, _, _ = vehicle_type_for_line(line["line_name"])
            for idx, _ in enumerate(route_data[line["line_id"]]["departures"], start=1):
                vehicle_id = f"metro_vehicle_{line['line_id']}_{idx:04d}"
                f.write(f'  <vehicle id="{xml_attr(vehicle_id)}" type="{xml_attr(type_id)}" />\n')
        f.write("</vehicleDefinitions>\n")


def build_outputs(args: argparse.Namespace) -> dict[str, Any]:
    inputs = load_inputs(args)
    lines = build_lines(inputs)

    nodes: dict[str, dict[str, Any]] = {}
    links: list[dict[str, Any]] = []
    route_data: dict[str, dict[str, Any]] = {}
    qa_rows: list[dict[str, Any]] = []

    for line in lines:
        stops = line["stops"]
        for stop in stops:
            node_id = make_node_id(stop["station_id"])
            nodes[node_id] = {
                "x": safe_float(stop["x_epsg32650"]),
                "y": safe_float(stop["y_epsg32650"]),
                "station_name": stop["station_name"],
            }
        lengths = allocate_link_lengths(line)
        route_link_ids: list[str] = []
        straight_total = 0.0
        for i in range(len(stops) - 1):
            from_stop = stops[i]
            to_stop = stops[i + 1]
            from_seq = safe_int(from_stop["sequence"])
            to_seq = safe_int(to_stop["sequence"])
            link_id = make_link_id(line["line_id"], from_seq, to_seq)
            straight = euclidean(from_stop, to_stop)
            straight_total += straight
            route_link_ids.append(link_id)
            links.append(
                {
                    "id": link_id,
                    "from": make_node_id(from_stop["station_id"]),
                    "to": make_node_id(to_stop["station_id"]),
                    "length": lengths[i],
                    "straight_length": straight,
                    "freespeed": line["freespeed_mps"],
                    "line_id": line["line_id"],
                }
            )
        departures = generate_departure_times(line["frequency_rows"])
        route_offsets = make_route_offsets(line, lengths, args.dwell_time_s)
        route_data[line["line_id"]] = {
            "route_link_ids": route_link_ids,
            "route_offsets": route_offsets,
            "departures": departures,
            "stops_by_sequence": {safe_int(stop["sequence"]): stop for stop in stops},
        }
        type_id, capacity, cap_note = vehicle_type_for_line(line["line_name"])
        final_arrival = route_offsets[-1]["arrival_s"] if route_offsets else 0.0
        qa_rows.append(
            {
                "line_id": line["line_id"],
                "line_name": line["line_name"],
                "transit_line_id": line_family(line["line_name"]),
                "origin_station": stops[0]["station_name"],
                "destination_station": stops[-1]["station_name"],
                "station_count": len(stops),
                "link_count": len(route_link_ids),
                "departure_count": len(departures),
                "first_departure": format_hms(departures[0][0]) if departures else "",
                "last_departure": format_hms(departures[-1][0]) if departures else "",
                "api_line_distance_m": round(line["api_line_distance_m"], 3),
                "allocated_link_length_sum_m": round(sum(lengths), 3),
                "straight_station_distance_sum_m": round(straight_total, 3),
                "freespeed_mps": round(line["freespeed_mps"], 4),
                "scheduled_terminal_arrival_offset_s": round(final_arrival, 3),
                "vehicle_type_id": type_id,
                "vehicle_capacity_persons": capacity,
                "capacity_source_note": cap_note,
                "speed_source_status": line["speed_source_status"],
            }
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    network_path = args.output_dir / "metro_network.xml.gz"
    schedule_path = args.output_dir / "metro_transitSchedule.xml.gz"
    vehicles_path = args.output_dir / "metro_transitVehicles.xml.gz"
    qa_path = args.output_dir / "metro_transit_network_qa.csv"
    summary_path = args.output_dir / "metro_transit_network_summary.json"

    write_network(network_path, nodes, links)
    write_schedule(schedule_path, lines, route_data)
    write_vehicles(vehicles_path, lines, route_data)
    write_csv(
        qa_path,
        qa_rows,
        [
            "line_id",
            "line_name",
            "transit_line_id",
            "origin_station",
            "destination_station",
            "station_count",
            "link_count",
            "departure_count",
            "first_departure",
            "last_departure",
            "api_line_distance_m",
            "allocated_link_length_sum_m",
            "straight_station_distance_sum_m",
            "freespeed_mps",
            "scheduled_terminal_arrival_offset_s",
            "vehicle_type_id",
            "vehicle_capacity_persons",
            "capacity_source_note",
            "speed_source_status",
        ],
    )

    vehicle_type_counts: dict[str, int] = defaultdict(int)
    for line in lines:
        type_id, _, _ = vehicle_type_for_line(line["line_name"])
        vehicle_type_counts[type_id] += len(route_data[line["line_id"]]["departures"])

    summary = {
        "created_by": "scripts/build_fuzhou_metro_matsim_transit.py",
        "coordinate_system": "EPSG:32650",
        "transport_mode_written": "pt",
        "dwell_time_s_per_intermediate_station": args.dwell_time_s,
        "outputs": {
            "network": str(network_path),
            "transitSchedule": str(schedule_path),
            "transitVehicles": str(vehicles_path),
            "qa_csv": str(qa_path),
            "summary_json": str(summary_path),
        },
        "counts": {
            "station_nodes": len(nodes),
            "directional_links": len(links),
            "transit_lines": len({line_family(line["line_name"]) for line in lines}),
            "transit_routes": len(lines),
            "stop_facilities": sum(len(route_data[line["line_id"]]["route_offsets"]) for line in lines),
            "departures_and_vehicles": sum(len(route_data[line["line_id"]]["departures"]) for line in lines),
            "vehicle_type_counts": dict(vehicle_type_counts),
        },
        "capacity_policy": {
            "metro_1_2_4_5": "B/B2 type 6-car train, 1460 passengers/train",
            "metro_6": "B type 4-car train, 1358 passengers/train",
            "binhai_f1": "Suburban A/F1 type 4-car train, 1084 passengers/train",
            "vehicle_capacity_split": "25% seats, remaining standing; total capacity equals supplied line capacity",
        },
        "qa_by_route": qa_rows,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stops-by-line-csv",
        type=Path,
        default=DEFAULT_UNIFIED_DIR / "metro" / "metro_stops_by_line_unified.csv",
    )
    parser.add_argument(
        "--frequency-csv",
        type=Path,
        default=DEFAULT_METRO_DIR / "amap_active" / "amap_metro_service_frequency_completed.csv",
    )
    parser.add_argument(
        "--speed-csv",
        type=Path,
        default=DEFAULT_METRO_DIR / "amap_active" / "amap_metro_speed_estimates_from_route_api.csv",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--dwell-time-s", type=float, default=30.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_outputs(args)
    print(json.dumps(summary["counts"], ensure_ascii=False, indent=2))
    print(f"Wrote {summary['outputs']['network']}")
    print(f"Wrote {summary['outputs']['transitSchedule']}")
    print(f"Wrote {summary['outputs']['transitVehicles']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
