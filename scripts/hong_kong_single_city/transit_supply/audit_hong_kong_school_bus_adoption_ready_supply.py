#!/usr/bin/env python3
"""Audit the Hong Kong school-bus v6 MATSim network/schedule/vehicle bundle."""

from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd
from lxml import etree as ET


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SUPPLY = (
    REPO_ROOT
    / "data/transit/hongkong/processed"
    / "matsim_road_pt_school_bus_supply_2026_v6_adoption_ready"
)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_clock(value: str) -> int:
    hour, minute, second = (int(part) for part in value.split(":"))
    return hour * 3600 + minute * 60 + second


def read_xml(path: Path) -> ET._ElementTree:
    with gzip.open(path, "rb") as handle:
        return ET.parse(handle)


def audit_network(path: Path) -> tuple[dict[str, dict[str, str]], dict[str, Any]]:
    tree = read_xml(path)
    root = tree.getroot()
    links_element = next(child for child in root if local_name(child.tag) == "links")
    links: dict[str, dict[str, str]] = {}
    duplicates = 0
    for element in links_element:
        if local_name(element.tag) != "link":
            continue
        link_id = element.attrib["id"]
        duplicates += link_id in links
        links[link_id] = dict(element.attrib)
    school_bus_links = {
        link_id
        for link_id, attributes in links.items()
        if "school_bus" in {
            part.strip() for part in attributes.get("modes", "").split(",")
        }
    }
    summary = {
        "link_count": len(links),
        "duplicate_link_ids": duplicates,
        "school_bus_allowed_link_count": len(school_bus_links),
        "school_bus_reverse_proxy_link_count": sum(
            link_id.startswith("school_bus_v6_reverse_direction_proxy_")
            for link_id in links
        ),
        "school_bus_topology_connector_link_count": sum(
            link_id.startswith("school_bus_v6_topology_connector_")
            for link_id in links
        ),
    }
    return links, summary


def audit_vehicles(path: Path) -> tuple[dict[str, str], dict[str, int], dict[str, Any]]:
    tree = read_xml(path)
    root = tree.getroot()
    type_seats: dict[str, int] = {}
    vehicles: dict[str, str] = {}
    type_after_vehicle = False
    seen_vehicle = False
    for element in root:
        tag = local_name(element.tag)
        if tag == "vehicleType":
            type_after_vehicle |= seen_vehicle
            capacity = next(
                child for child in element if local_name(child.tag) == "capacity"
            )
            type_seats[element.attrib["id"]] = int(capacity.attrib["seats"])
        elif tag == "vehicle":
            seen_vehicle = True
            vehicles[element.attrib["id"]] = element.attrib["type"]
    school_vehicles = {
        vehicle_id: type_id
        for vehicle_id, type_id in vehicles.items()
        if vehicle_id.startswith("veh_school_bus_v6_")
    }
    missing_types = sorted({type_id for type_id in vehicles.values() if type_id not in type_seats})
    return school_vehicles, type_seats, {
        "all_vehicle_count": len(vehicles),
        "school_bus_vehicle_count": len(school_vehicles),
        "school_bus_vehicle_type_counts": dict(Counter(school_vehicles.values())),
        "missing_vehicle_types": missing_types,
        "vehicle_type_after_vehicle": type_after_vehicle,
    }


def ordered_stop_link_positions(
    route_links: list[str],
    stop_links: list[str],
) -> list[int] | None:
    positions: list[int] = []
    cursor = 0
    for stop_link in stop_links:
        found = None
        for index in range(cursor, len(route_links)):
            if route_links[index] == stop_link:
                found = index
                break
        if found is None:
            return None
        positions.append(found)
        cursor = found
    return positions


def audit_schedule(
    path: Path,
    links: dict[str, dict[str, str]],
    school_vehicles: dict[str, str],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    tree = read_xml(path)
    root = tree.getroot()
    stops_element = next(child for child in root if local_name(child.tag) == "transitStops")
    stops: dict[str, str] = {}
    duplicate_stops = 0
    for element in stops_element:
        if local_name(element.tag) != "stopFacility":
            continue
        facility_id = element.attrib["id"]
        duplicate_stops += facility_id in stops
        stops[facility_id] = element.attrib["linkRefId"]

    route_records: dict[str, dict[str, Any]] = {}
    errors: Counter[str] = Counter()
    vehicle_intervals: defaultdict[str, list[tuple[int, int, str]]] = defaultdict(list)
    line_count = 0
    for line in root:
        if local_name(line.tag) != "transitLine" or not line.attrib["id"].startswith("line_school_bus_v6_"):
            continue
        line_count += 1
        transit_routes = [child for child in line if local_name(child.tag) == "transitRoute"]
        if len(transit_routes) != 2:
            errors["line_direction_count"] += 1
        for route in transit_routes:
            route_id = route.attrib["id"]
            mode = next(child for child in route if local_name(child.tag) == "transportMode").text
            profile = next(child for child in route if local_name(child.tag) == "routeProfile")
            network_route = next(child for child in route if local_name(child.tag) == "route")
            departures = next(child for child in route if local_name(child.tag) == "departures")
            route_links = [child.attrib["refId"] for child in network_route]
            profile_stops = [child for child in profile if local_name(child.tag) == "stop"]
            stop_ids = [child.attrib["refId"] for child in profile_stops]
            stop_links = [stops.get(stop_id, "") for stop_id in stop_ids]
            arrival_offsets = [parse_clock(child.attrib["arrivalOffset"]) for child in profile_stops]
            departure_offsets = [parse_clock(child.attrib["departureOffset"]) for child in profile_stops]
            departure_rows = [child for child in departures if local_name(child.tag) == "departure"]

            if mode != "school_bus":
                errors["transport_mode"] += 1
            if not route_links:
                errors["empty_network_route"] += 1
            if any(link_id not in links for link_id in route_links):
                errors["missing_network_link"] += 1
            if any(
                "school_bus" not in {
                    part.strip()
                    for part in links[link_id].get("modes", "").split(",")
                }
                for link_id in route_links
                if link_id in links
            ):
                errors["school_bus_mode_not_allowed"] += 1
            continuity_errors = sum(
                links[left]["to"] != links[right]["from"]
                for left, right in zip(route_links, route_links[1:])
                if left in links and right in links
            )
            if continuity_errors:
                errors["network_route_discontinuity"] += continuity_errors
            if any(stop_id not in stops for stop_id in stop_ids):
                errors["missing_stop_facility"] += 1
            if ordered_stop_link_positions(route_links, stop_links) is None:
                errors["stop_link_order"] += 1
            if any(b < a for a, b in zip(arrival_offsets, arrival_offsets[1:])):
                errors["arrival_offset_order"] += 1
            if any(departure < arrival for arrival, departure in zip(arrival_offsets, departure_offsets)):
                errors["departure_before_arrival"] += 1
            if len(departure_rows) != 1:
                errors["departure_count"] += 1
                continue
            departure = departure_rows[0]
            vehicle_id = departure.attrib["vehicleRefId"]
            if vehicle_id not in school_vehicles:
                errors["missing_school_bus_vehicle"] += 1
            start = parse_clock(departure.attrib["departureTime"])
            end = start + arrival_offsets[-1]
            vehicle_intervals[vehicle_id].append((start, end, route_id))
            route_records[route_id] = {
                "line_id": line.attrib["id"],
                "vehicle_id": vehicle_id,
                "network_link_count": len(route_links),
                "stop_count": len(stop_ids),
                "departure_time": start,
                "runtime_seconds": arrival_offsets[-1],
            }

    overlaps = []
    for vehicle_id, intervals in vehicle_intervals.items():
        intervals.sort()
        for left, right in zip(intervals, intervals[1:]):
            if left[1] > right[0]:
                overlaps.append((vehicle_id, left[2], right[2]))
    return route_records, {
        "school_bus_line_count": line_count,
        "school_bus_transit_route_count": len(route_records),
        "school_bus_departure_count": len(route_records),
        "school_bus_stop_facility_count": sum(
            facility_id.startswith("sbv6_") for facility_id in stops
        ),
        "duplicate_stop_ids": duplicate_stops,
        "vehicle_schedule_overlap_count": len(overlaps),
        "error_counts": dict(errors),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--supply-dir", type=Path, default=DEFAULT_SUPPLY)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    supply = args.supply_dir.resolve()
    network_path = supply / "network.xml.gz"
    schedule_path = supply / "transitSchedule_5pct_school_bus_v6.xml.gz"
    vehicles_path = supply / "transitVehicles_10pct_regular_school_bus_unscaled.xml.gz"
    route_audit_path = supply / "school_bus_routes_v6.csv"
    first_party_path = supply / "school_bus_first_party_reconstruction_v6.csv"
    for path in (network_path, schedule_path, vehicles_path, route_audit_path, first_party_path):
        if not path.exists():
            raise FileNotFoundError(path)

    links, network = audit_network(network_path)
    vehicles, type_seats, vehicle = audit_vehicles(vehicles_path)
    schedule_records, schedule = audit_schedule(schedule_path, links, vehicles)
    route_audit = pd.read_csv(route_audit_path)
    first_party = pd.read_csv(first_party_path)
    inbound = route_audit[route_audit["direction"].eq("inbound_am")]
    time_limit_violations = int(
        route_audit["time_limit_exceeded"].astype(str).str.lower().eq("true").sum()
    )
    capacity_errors = 0
    for row in inbound.itertuples():
        vehicle_id = f"veh_school_bus_v6_{row.route_id}"
        type_id = vehicles.get(vehicle_id)
        seats = type_seats.get(type_id or "", -1)
        if seats != int(row.vehicle_capacity) or int(row.proxy_students) > seats:
            capacity_errors += 1

    checks = {
        "network_link_ids_unique": network["duplicate_link_ids"] == 0,
        "vehicle_types_precede_vehicles": not vehicle["vehicle_type_after_vehicle"],
        "all_vehicle_type_references_resolve": not vehicle["missing_vehicle_types"],
        "school_bus_line_count_exact": schedule["school_bus_line_count"] == 3439,
        "school_bus_transit_route_count_exact": schedule["school_bus_transit_route_count"] == 6878,
        "school_bus_vehicle_count_exact": vehicle["school_bus_vehicle_count"] == 3439,
        "schedule_has_no_structural_errors": not schedule["error_counts"],
        "vehicles_have_no_schedule_overlap": schedule["vehicle_schedule_overlap_count"] == 0,
        "route_capacity_unscaled_and_sufficient": capacity_errors == 0,
        "all_directions_within_stage_time_limit": time_limit_violations == 0,
        "all_76_first_party_routes_reconstructed": len(first_party) == 76
        and bool(first_party["reconstructed_pickup_count"].gt(0).all()),
        "route_audit_has_both_directions": len(route_audit) == 6878,
    }
    result = {
        "status": "pass" if all(checks.values()) else "fail",
        "network": network,
        "vehicles": vehicle,
        "schedule": schedule,
        "route_capacity_error_count": capacity_errors,
        "time_limit_violation_count": time_limit_violations,
        "first_party_route_count": len(first_party),
        "checks": checks,
    }
    output = supply / "school_bus_supply_v6_validation.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
