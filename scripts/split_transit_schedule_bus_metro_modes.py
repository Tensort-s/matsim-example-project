#!/usr/bin/env python
"""Split integrated MATSim transit route modes into bus and metro.

The previous integrated schedule used ``pt`` for both bus and metro routes.
This helper keeps all ids, stops, route links, departures, network and
vehicles unchanged, but rewrites each transitRoute transportMode according to
its transitLine id:

* ``bus_line_*``   -> ``bus``
* ``metro_*``      -> ``metro``

It writes a new output directory so existing integrated transit inputs remain
untouched.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import pathlib
import re
import shutil
import time
import xml.etree.ElementTree as ET
from collections import Counter


LINE_RE = re.compile(r'<transitLine\s+id="([^"]+)"')
MODE_RE = re.compile(r"<transportMode>([^<]*)</transportMode>")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dir",
        type=pathlib.Path,
        default=pathlib.Path(
            "data/transit/fuzhou_transit_matsim_integrated_20260709_capacity_lanes_v2"
        ),
        help="Directory containing network_with_car_bus_metro.xml.gz, transitSchedule.xml.gz and transitVehicles.xml.gz.",
    )
    parser.add_argument(
        "--output-dir",
        type=pathlib.Path,
        default=pathlib.Path(
            "data/transit/fuzhou_transit_matsim_integrated_20260709_capacity_lanes_v2_split_modes"
        ),
        help="New directory for the copied network/vehicles and rewritten transitSchedule.",
    )
    return parser.parse_args()


def expected_mode_for_line(line_id: str) -> str:
    if line_id.startswith("bus_line_"):
        return "bus"
    if line_id.startswith("metro_"):
        return "metro"
    raise ValueError(f"Cannot infer bus/metro mode from transitLine id: {line_id!r}")


def rewrite_schedule(input_schedule: pathlib.Path, output_schedule: pathlib.Path) -> dict:
    output_schedule.parent.mkdir(parents=True, exist_ok=True)

    current_line_id: str | None = None
    current_expected_mode: str | None = None
    line_counts: Counter[str] = Counter()
    route_counts_before: Counter[str] = Counter()
    route_counts_after: Counter[str] = Counter()
    replaced = 0
    unchanged = 0
    unknown_lines: list[str] = []

    with gzip.open(input_schedule, "rt", encoding="utf-8") as src, gzip.open(
        output_schedule, "wt", encoding="utf-8", newline=""
    ) as dst:
        for line in src:
            match_line = LINE_RE.search(line)
            if match_line:
                current_line_id = match_line.group(1)
                try:
                    current_expected_mode = expected_mode_for_line(current_line_id)
                    line_counts[current_expected_mode] += 1
                except ValueError:
                    unknown_lines.append(current_line_id)
                    current_expected_mode = None

            match_mode = MODE_RE.search(line)
            if match_mode:
                old_mode = match_mode.group(1).strip()
                route_counts_before[old_mode] += 1
                if current_expected_mode is None:
                    raise ValueError(
                        f"Cannot rewrite transportMode {old_mode!r}; current transitLine is {current_line_id!r}"
                    )
                new_line = MODE_RE.sub(
                    f"<transportMode>{current_expected_mode}</transportMode>", line
                )
                route_counts_after[current_expected_mode] += 1
                if old_mode != current_expected_mode:
                    replaced += 1
                else:
                    unchanged += 1
                dst.write(new_line)
            else:
                dst.write(line)

    if unknown_lines:
        raise ValueError(f"Unknown transitLine ids: {unknown_lines[:10]}")

    return {
        "line_counts_by_new_mode": dict(line_counts),
        "route_counts_before": dict(route_counts_before),
        "route_counts_after": dict(route_counts_after),
        "transport_modes_replaced": replaced,
        "transport_modes_already_matching": unchanged,
    }


def validate_schedule(schedule_path: pathlib.Path) -> dict:
    with gzip.open(schedule_path, "rb") as f:
        root = ET.parse(f).getroot()

    stop_facilities = root.find("transitStops")
    stop_count = len(stop_facilities.findall("stopFacility")) if stop_facilities is not None else 0

    line_count = 0
    route_count = 0
    route_modes: Counter[str] = Counter()
    line_modes: dict[str, Counter[str]] = {}
    bad_routes: list[dict[str, str]] = []

    for transit_line in root.findall("transitLine"):
        line_count += 1
        line_id = transit_line.attrib.get("id", "")
        expected = expected_mode_for_line(line_id)
        line_modes[line_id] = Counter()
        for transit_route in transit_line.findall("transitRoute"):
            route_count += 1
            route_id = transit_route.attrib.get("id", "")
            mode = (transit_route.findtext("transportMode") or "").strip()
            route_modes[mode] += 1
            line_modes[line_id][mode] += 1
            if mode != expected:
                bad_routes.append(
                    {
                        "transit_line_id": line_id,
                        "transit_route_id": route_id,
                        "expected_mode": expected,
                        "actual_mode": mode,
                    }
                )

    if bad_routes:
        raise ValueError(f"Found {len(bad_routes)} routes with unexpected modes")

    return {
        "stop_facilities": stop_count,
        "transit_lines": line_count,
        "transit_routes": route_count,
        "route_modes": dict(route_modes),
        "bad_route_count": len(bad_routes),
    }


def copy_if_exists(src: pathlib.Path, dst: pathlib.Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def write_qa_csv(path: pathlib.Path, summary: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        ("bus_lines", summary["rewrite"]["line_counts_by_new_mode"].get("bus", 0)),
        ("metro_lines", summary["rewrite"]["line_counts_by_new_mode"].get("metro", 0)),
        ("bus_routes", summary["validation"]["route_modes"].get("bus", 0)),
        ("metro_routes", summary["validation"]["route_modes"].get("metro", 0)),
        ("routes_before_pt", summary["rewrite"]["route_counts_before"].get("pt", 0)),
        ("transport_modes_replaced", summary["rewrite"]["transport_modes_replaced"]),
        ("bad_route_count", summary["validation"]["bad_route_count"]),
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "value"])
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    input_dir = args.input_dir
    output_dir = args.output_dir

    input_schedule = input_dir / "transitSchedule.xml.gz"
    if not input_schedule.exists():
        raise FileNotFoundError(input_schedule)

    output_dir.mkdir(parents=True, exist_ok=True)

    copied = {}
    for filename in [
        "network_with_car_bus_metro.xml.gz",
        "transitVehicles.xml.gz",
        "transit_integration_summary.json",
        "transit_integration_qa.csv",
        "capacity_reestimate_summary.json",
        "capacity_reestimate_by_highway.csv",
        "capacity_distribution_before_after.csv",
        "capacity_reestimate_link_qa.csv",
    ]:
        copied[filename] = copy_if_exists(input_dir / filename, output_dir / filename)

    rewrite = rewrite_schedule(input_schedule, output_dir / "transitSchedule.xml.gz")
    validation = validate_schedule(output_dir / "transitSchedule.xml.gz")

    summary = {
        "created_by": "scripts/split_transit_schedule_bus_metro_modes.py",
        "created_at_epoch": time.time(),
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "mode_split_rule": {
            "bus_line_*": "bus",
            "metro_*": "metro",
        },
        "files_copied": copied,
        "rewrite": rewrite,
        "validation": validation,
        "note": "Only transitRoute transportMode values were changed; ids, stops, links, departures, network and vehicles are unchanged.",
    }

    with (output_dir / "transit_mode_split_summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    write_qa_csv(output_dir / "transit_mode_split_qa.csv", summary)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
