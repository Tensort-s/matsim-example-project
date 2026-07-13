#!/usr/bin/env python3
"""Build a Fuzhou MATSim network where buses use pt-only priority links.

The script starts from the integrated bus/metro split-mode network and schedule.
It duplicates every bus route/stop link as a pt-only ``busprio_*`` link, rewires
bus transit routes and bus stop facilities to those duplicated links, and scales
only car links by a configurable capacity factor. This keeps qsim's global
flow/storage factors at 1.0 while retaining a sampled-capacity road network for
private cars.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import shutil
import time
import xml.etree.ElementTree as ET
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INTEGRATED_DIR = ROOT / "data" / "transit" / "fuzhou_transit_matsim_integrated_20260709_capacity_lanes_v2_split_modes"
DEFAULT_POPULATION = (
    ROOT
    / "data"
    / "matsim_routes"
    / "fuzhou_city_23_greenspace_grid_multi_activity_2pct_same_day_night"
    / "mode_choice_plans_bus_metro_2pct.xml.gz"
)
DEFAULT_OUT_DIR = ROOT / "data" / "transit" / "fuzhou_transit_matsim_integrated_20260709_bus_priority_carcap5"
DEFAULT_CAPACITY_QA = DEFAULT_INTEGRATED_DIR / "capacity_reestimate_link_qa.csv"


CAPACITY_FLOOR_BY_HIGHWAY = {
    "service": 100.0,
    "living_street": 100.0,
    "residential": 200.0,
    "unclassified": 200.0,
    "tertiary": 300.0,
    "tertiary_link": 300.0,
    "secondary": 300.0,
    "secondary_link": 300.0,
    "primary": 300.0,
    "primary_link": 300.0,
    "trunk": 300.0,
    "trunk_link": 300.0,
    "motorway": 300.0,
    "motorway_link": 300.0,
}
SYNTHETIC_CAR_CAPACITY_FLOOR = 300.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", type=Path, default=DEFAULT_INTEGRATED_DIR / "network_with_car_bus_metro.xml.gz")
    parser.add_argument("--schedule", type=Path, default=DEFAULT_INTEGRATED_DIR / "transitSchedule.xml.gz")
    parser.add_argument("--vehicles", type=Path, default=DEFAULT_INTEGRATED_DIR / "transitVehicles.xml.gz")
    parser.add_argument("--population", type=Path, default=DEFAULT_POPULATION)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--capacity-qa", type=Path, default=DEFAULT_CAPACITY_QA)
    parser.add_argument("--car-capacity-factor", type=float, default=0.05)
    parser.add_argument(
        "--use-car-capacity-floors",
        action="store_true",
        help="Apply highway-specific minimum capacity after car capacity scaling.",
    )
    parser.add_argument(
        "--preserve-car-permlanes",
        action="store_true",
        help="Keep original car permlanes instead of scaling them by car-capacity-factor.",
    )
    parser.add_argument("--bus-priority-min-capacity", type=float, default=3600.0)
    parser.add_argument("--bus-priority-min-permlanes", type=float, default=1.0)
    parser.add_argument("--verify-population-links", action="store_true")
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
        handle.write(ET.tostring(root, encoding="unicode"))
        handle.write("\n")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def split_modes(modes: str | None) -> list[str]:
    return [m.strip() for m in (modes or "").replace(";", ",").split(",") if m.strip()]


def set_modes(link: ET.Element, modes: list[str]) -> None:
    link.set("modes", ",".join(dict.fromkeys(modes)))


def as_float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except ValueError:
        return default


def load_capacity_metadata(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {row["link_id"]: row for row in csv.DictReader(handle) if row.get("link_id")}


def capacity_floor(link_id: str, link_meta: dict[str, str]) -> float:
    if link_id.startswith("syn_bus_link_") or link_id.startswith("syn_bus_connector_"):
        return SYNTHETIC_CAR_CAPACITY_FLOOR
    highway = (link_meta.get("highway") or "").strip().lower()
    return CAPACITY_FLOOR_BY_HIGHWAY.get(highway, 300.0 if highway else 0.0)


def collect_bus_usage(schedule_root: ET.Element) -> tuple[set[str], set[str], dict[str, list[str]], dict[str, str]]:
    """Return bus route links, bus stop facility ids, route link lists and stop ids by mode."""
    bus_links: set[str] = set()
    bus_stops: set[str] = set()
    bus_route_links: dict[str, list[str]] = {}
    stop_modes: dict[str, str] = {}

    for line in schedule_root.findall("transitLine"):
        line_id = line.get("id", "")
        for route in line.findall("transitRoute"):
            route_id = route.get("id", "")
            mode = (route.findtext("transportMode") or "").strip()
            key = f"{line_id}/{route_id}"
            if mode != "bus":
                route_profile = route.find("routeProfile")
                if route_profile is not None:
                    for stop in route_profile.findall("stop"):
                        ref = stop.get("refId")
                        if ref:
                            stop_modes.setdefault(ref, mode)
                continue

            route_profile = route.find("routeProfile")
            if route_profile is not None:
                for stop in route_profile.findall("stop"):
                    ref = stop.get("refId")
                    if ref:
                        bus_stops.add(ref)
                        stop_modes[ref] = "bus"

            links_el = route.find("route")
            links: list[str] = []
            if links_el is not None:
                for link in links_el.findall("link"):
                    ref = link.get("refId")
                    if ref:
                        bus_links.add(ref)
                        links.append(ref)
            bus_route_links[key] = links
    return bus_links, bus_stops, bus_route_links, stop_modes


def collect_population_route_links(population_path: Path) -> set[str]:
    route_links: set[str] = set()
    if not population_path.exists():
        return route_links
    with gzip.open(population_path, "rt", encoding="utf-8") as handle:
        for _event, elem in ET.iterparse(handle, events=("end",)):
            if elem.tag != "route":
                elem.clear()
                continue
            start = elem.get("start_link")
            end = elem.get("end_link")
            if start:
                route_links.add(start)
            if end:
                route_links.add(end)
            text = (elem.text or "").strip()
            if text:
                route_links.update(text.split())
            elem.clear()
    return route_links


def build_bus_priority(args: argparse.Namespace) -> dict[str, Any]:
    started = time.time()
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    network_root = read_xml_gz(args.network).getroot()
    schedule_root = read_xml_gz(args.schedule).getroot()
    links_el = network_root.find("links")
    if links_el is None:
        raise ValueError("network has no <links>")
    stops_el = schedule_root.find("transitStops")
    if stops_el is None:
        raise ValueError("schedule has no <transitStops>")

    bus_links, bus_stops, bus_route_links, stop_modes = collect_bus_usage(schedule_root)
    capacity_meta = load_capacity_metadata(args.capacity_qa)
    bus_stop_link_refs: set[str] = set()
    for stop in stops_el.findall("stopFacility"):
        stop_id = stop.get("id", "")
        if stop_id in bus_stops or stop_id.startswith("bus_stop_"):
            link_ref = stop.get("linkRefId")
            if link_ref:
                bus_stop_link_refs.add(link_ref)
    bus_links.update(bus_stop_link_refs)
    link_by_id = {link.get("id", ""): link for link in links_el.findall("link")}
    missing_bus_route_links = sorted(link_id for link_id in bus_links if link_id not in link_by_id)
    if missing_bus_route_links:
        raise RuntimeError(f"{len(missing_bus_route_links)} bus route links are missing from network")

    mapping_rows: list[dict[str, Any]] = []
    busprio_map: dict[str, str] = {}
    existing_link_ids = set(link_by_id)

    for original_id in sorted(bus_links):
        original = link_by_id[original_id]
        busprio_id = f"busprio_{original_id}"
        if busprio_id in existing_link_ids:
            raise RuntimeError(f"bus-priority link id already exists: {busprio_id}")
        busprio = deepcopy(original)
        busprio.set("id", busprio_id)
        set_modes(busprio, ["pt"])
        original_capacity = as_float(original.get("capacity"), 0.0)
        original_permlanes = as_float(original.get("permlanes"), 1.0)
        busprio.set("capacity", f"{max(original_capacity, args.bus_priority_min_capacity):.6g}")
        busprio.set("permlanes", f"{max(original_permlanes, args.bus_priority_min_permlanes):.6g}")
        links_el.append(busprio)
        busprio_map[original_id] = busprio_id
        existing_link_ids.add(busprio_id)
        mapping_rows.append(
            {
                "original_link_id": original_id,
                "bus_priority_link_id": busprio_id,
                "original_modes": original.get("modes", ""),
                "bus_priority_modes": "pt",
                "original_capacity": original_capacity,
                "bus_priority_capacity": as_float(busprio.get("capacity")),
                "original_permlanes": original_permlanes,
                "bus_priority_permlanes": as_float(busprio.get("permlanes")),
            }
        )

    mode_counts_before = Counter()
    mode_counts_after = Counter()
    scaled_car_links = 0
    car_links_capacity_floor_applied = 0
    car_links_permlanes_preserved = 0
    car_capacity_before = 0.0
    car_capacity_after = 0.0
    car_permlanes_before = 0.0
    car_permlanes_after = 0.0
    removed_pt_from_car_links = 0

    for link in links_el.findall("link"):
        modes_before = split_modes(link.get("modes"))
        mode_counts_before[",".join(modes_before)] += 1
        if link.get("id", "").startswith("busprio_"):
            mode_counts_after[link.get("modes", "")] += 1
            continue
        if "car" in modes_before:
            cap_before = as_float(link.get("capacity"), 0.0)
            lanes_before = as_float(link.get("permlanes"), 1.0)
            scaled_capacity = cap_before * args.car_capacity_factor
            floor_capacity = capacity_floor(link.get("id", ""), capacity_meta.get(link.get("id", ""), {})) if args.use_car_capacity_floors else 0.0
            new_capacity = max(scaled_capacity, floor_capacity)
            if new_capacity > scaled_capacity + 1e-9:
                car_links_capacity_floor_applied += 1
            link.set("capacity", f"{new_capacity:.6g}")
            if args.preserve_car_permlanes:
                new_lanes = lanes_before if lanes_before > 0 else 1.0
                car_links_permlanes_preserved += 1
            else:
                new_lanes = max(lanes_before * args.car_capacity_factor, 1e-6)
            link.set("permlanes", f"{new_lanes:.6g}")
            scaled_car_links += 1
            car_capacity_before += cap_before
            car_capacity_after += as_float(link.get("capacity"), 0.0)
            car_permlanes_before += lanes_before
            car_permlanes_after += as_float(link.get("permlanes"), 0.0)
            if "pt" in modes_before:
                removed_pt_from_car_links += 1
            set_modes(link, ["car"])
        mode_counts_after[link.get("modes", "")] += 1

    bus_stop_rewired = 0
    bus_stop_missing_mapping: list[dict[str, str]] = []
    for stop in stops_el.findall("stopFacility"):
        stop_id = stop.get("id", "")
        if stop_id not in bus_stops and not stop_id.startswith("bus_stop_"):
            continue
        old_link = stop.get("linkRefId", "")
        new_link = busprio_map.get(old_link)
        if new_link:
            stop.set("linkRefId", new_link)
            bus_stop_rewired += 1
        else:
            bus_stop_missing_mapping.append({"stopFacility": stop_id, "old_linkRefId": old_link})

    bus_route_links_rewired = 0
    bus_routes_rewired = 0
    bus_route_missing_mapping: list[dict[str, str]] = []
    for line in schedule_root.findall("transitLine"):
        for route in line.findall("transitRoute"):
            mode = (route.findtext("transportMode") or "").strip()
            if mode != "bus":
                continue
            links_el_route = route.find("route")
            if links_el_route is None:
                continue
            bus_routes_rewired += 1
            for link in links_el_route.findall("link"):
                old_ref = link.get("refId", "")
                new_ref = busprio_map.get(old_ref)
                if new_ref:
                    link.set("refId", new_ref)
                    bus_route_links_rewired += 1
                else:
                    bus_route_missing_mapping.append(
                        {
                            "line_id": line.get("id", ""),
                            "route_id": route.get("id", ""),
                            "old_link_ref": old_ref,
                        }
                    )

    if bus_stop_missing_mapping:
        write_csv(out_dir / "bus_priority_stop_missing_mapping.csv", bus_stop_missing_mapping, ["stopFacility", "old_linkRefId"])
        raise RuntimeError(f"{len(bus_stop_missing_mapping)} bus stops could not be mapped to bus-priority links")
    if bus_route_missing_mapping:
        write_csv(out_dir / "bus_priority_route_missing_mapping.csv", bus_route_missing_mapping, ["line_id", "route_id", "old_link_ref"])
        raise RuntimeError(f"{len(bus_route_missing_mapping)} bus route links could not be mapped to bus-priority links")

    output_network = out_dir / "network_with_car_busprio_metro.xml.gz"
    output_schedule = out_dir / "transitSchedule.xml.gz"
    output_vehicles = out_dir / "transitVehicles.xml.gz"
    write_xml_gz(output_network, network_root, '<!DOCTYPE network SYSTEM "http://www.matsim.org/files/dtd/network_v1.dtd">')
    write_xml_gz(output_schedule, schedule_root, '<!DOCTYPE transitSchedule SYSTEM "http://www.matsim.org/files/dtd/transitSchedule_v2.dtd">')
    shutil.copy2(args.vehicles, output_vehicles)
    write_csv(
        out_dir / "bus_priority_link_mapping.csv",
        mapping_rows,
        [
            "original_link_id",
            "bus_priority_link_id",
            "original_modes",
            "bus_priority_modes",
            "original_capacity",
            "bus_priority_capacity",
            "original_permlanes",
            "bus_priority_permlanes",
        ],
    )

    final_link_ids = {link.get("id", "") for link in links_el.findall("link")}
    population_missing_links: list[str] = []
    if args.verify_population_links:
        pop_links = collect_population_route_links(args.population)
        population_missing_links = sorted(link_id for link_id in pop_links if link_id not in final_link_ids)
        if population_missing_links:
            write_csv(out_dir / "population_missing_route_links.csv", [{"link_id": x} for x in population_missing_links], ["link_id"])

    qa_rows: list[dict[str, Any]] = []
    for link in links_el.findall("link"):
        link_id = link.get("id", "")
        modes = split_modes(link.get("modes"))
        if link_id.startswith("busprio_") or "car" in modes or "pt" in modes:
            qa_rows.append(
                {
                    "link_id": link_id,
                    "modes": ",".join(modes),
                    "capacity": link.get("capacity", ""),
                    "permlanes": link.get("permlanes", ""),
                    "highway": capacity_meta.get(link_id, {}).get("highway", ""),
                    "link_class": capacity_meta.get(link_id, {}).get("link_class", ""),
                    "is_bus_priority": str(link_id.startswith("busprio_")).lower(),
                    "is_car_link": str("car" in modes).lower(),
                    "is_pt_link": str("pt" in modes).lower(),
                }
            )
    write_csv(
        out_dir / "bus_priority_network_qa.csv",
        qa_rows,
        ["link_id", "modes", "capacity", "permlanes", "highway", "link_class", "is_bus_priority", "is_car_link", "is_pt_link"],
    )

    summary = {
        "created_by": "scripts/build_fuzhou_bus_priority_network.py",
        "created_at_epoch": time.time(),
        "runtime_seconds": round(time.time() - started, 3),
        "inputs": {
            "network": str(args.network),
            "schedule": str(args.schedule),
            "vehicles": str(args.vehicles),
            "population": str(args.population) if args.verify_population_links else None,
            "capacity_qa": str(args.capacity_qa),
        },
        "outputs": {
            "network": str(output_network),
            "transitSchedule": str(output_schedule),
            "transitVehicles": str(output_vehicles),
            "link_mapping": str(out_dir / "bus_priority_link_mapping.csv"),
            "qa": str(out_dir / "bus_priority_network_qa.csv"),
            "summary": str(out_dir / "bus_priority_network_summary.json"),
        },
        "parameters": {
            "car_capacity_factor": args.car_capacity_factor,
            "use_car_capacity_floors": bool(args.use_car_capacity_floors),
            "preserve_car_permlanes": bool(args.preserve_car_permlanes),
            "capacity_floor_by_highway": CAPACITY_FLOOR_BY_HIGHWAY,
            "synthetic_car_capacity_floor": SYNTHETIC_CAR_CAPACITY_FLOOR,
            "bus_priority_min_capacity": args.bus_priority_min_capacity,
            "bus_priority_min_permlanes": args.bus_priority_min_permlanes,
            "qsim_flow_storage_factor_expected": 1.0,
        },
        "counts": {
            "bus_routes": len(bus_route_links),
            "bus_route_original_links_unique": len(bus_links),
            "bus_priority_links_created": len(busprio_map),
            "bus_stop_facilities_rewired": bus_stop_rewired,
            "bus_route_link_refs_rewired": bus_route_links_rewired,
            "bus_routes_rewired": bus_routes_rewired,
            "car_links_scaled": scaled_car_links,
            "car_links_capacity_floor_applied": car_links_capacity_floor_applied,
            "car_links_permlanes_preserved": car_links_permlanes_preserved,
            "car_links_removed_pt_mode": removed_pt_from_car_links,
            "final_links": len(final_link_ids),
            "population_missing_route_links": len(population_missing_links),
        },
        "capacity": {
            "car_capacity_before_sum": car_capacity_before,
            "car_capacity_after_sum": car_capacity_after,
            "car_capacity_after_over_before": car_capacity_after / car_capacity_before if car_capacity_before else None,
            "car_permlanes_before_sum": car_permlanes_before,
            "car_permlanes_after_sum": car_permlanes_after,
            "car_permlanes_after_over_before": car_permlanes_after / car_permlanes_before if car_permlanes_before else None,
        },
        "modes": {
            "before": dict(mode_counts_before),
            "after": dict(mode_counts_after),
        },
        "validation": {
            "all_bus_stops_rewired": len(bus_stop_missing_mapping) == 0,
            "all_bus_route_links_rewired": len(bus_route_missing_mapping) == 0,
            "population_route_links_all_exist": len(population_missing_links) == 0 if args.verify_population_links else None,
        },
    }
    (out_dir / "bus_priority_network_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    args = parse_args()
    summary = build_bus_priority(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
