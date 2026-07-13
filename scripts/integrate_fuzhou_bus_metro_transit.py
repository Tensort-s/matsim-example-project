#!/usr/bin/env python3
"""Integrate Fuzhou bus and metro MATSim transit inputs.

The script merges:
- bus car/pt road network + metro network
- bus transitSchedule + metro transitSchedule
- bus transitVehicles + metro transitVehicles

It fails on ID collisions instead of silently renaming IDs.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
BUS_DIR = ROOT / "data" / "transit" / "fuzhou_bus_matsim_network_20260709_boundary500m_conservative_augmented"
METRO_DIR = ROOT / "data" / "transit" / "fuzhou_metro_matsim_network_20260709"
DEFAULT_OUT_DIR = ROOT / "data" / "transit" / "fuzhou_transit_matsim_integrated_20260709"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
MATSIM_DTD_NS = "http://www.matsim.org/files/dtd"


def read_xml_gz(path: Path) -> ET.ElementTree:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return ET.parse(f)


def write_xml_gz(path: Path, root: ET.Element, doctype: str | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n')
        if doctype:
            f.write(doctype)
            f.write("\n\n")
        f.write(ET.tostring(root, encoding="unicode"))
        f.write("\n")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def collect_ids(root: ET.Element, path: str) -> set[str]:
    return {el.attrib["id"] for el in root.findall(path) if "id" in el.attrib}


def findall_local(root: ET.Element, local_name: str) -> list[ET.Element]:
    return [el for el in root.iter() if el.tag.rsplit("}", 1)[-1] == local_name]


def fail_on_conflicts(conflicts: list[dict[str, str]], out_dir: Path) -> None:
    if not conflicts:
        return
    conflict_path = out_dir / "transit_integration_conflicts.csv"
    write_csv(conflict_path, conflicts, ["kind", "id", "source_a", "source_b"])
    raise RuntimeError(f"ID conflicts found; wrote {conflict_path}")


def _split_modes(modes: str) -> list[str]:
    return [m.strip() for m in modes.replace(";", ",").split(",") if m.strip()]


def _largest_strongly_connected_component(edges: list[tuple[str, str]]) -> set[str]:
    nodes: set[str] = set()
    graph: dict[str, list[str]] = {}
    reverse_graph: dict[str, list[str]] = {}
    for src, dst in edges:
        nodes.add(src)
        nodes.add(dst)
        graph.setdefault(src, []).append(dst)
        reverse_graph.setdefault(dst, []).append(src)
        graph.setdefault(dst, [])
        reverse_graph.setdefault(src, [])

    visited: set[str] = set()
    order: list[str] = []
    for node in nodes:
        if node in visited:
            continue
        stack: list[tuple[str, bool]] = [(node, False)]
        while stack:
            current, expanded = stack.pop()
            if expanded:
                order.append(current)
                continue
            if current in visited:
                continue
            visited.add(current)
            stack.append((current, True))
            for nxt in graph.get(current, []):
                if nxt not in visited:
                    stack.append((nxt, False))

    largest: set[str] = set()
    visited.clear()
    for node in reversed(order):
        if node in visited:
            continue
        component: set[str] = set()
        stack = [node]
        visited.add(node)
        while stack:
            current = stack.pop()
            component.add(current)
            for nxt in reverse_graph.get(current, []):
                if nxt not in visited:
                    visited.add(nxt)
                    stack.append(nxt)
        if len(component) > len(largest):
            largest = component
    return largest


def sanitize_car_modes_for_routing(network_root: ET.Element) -> dict[str, Any]:
    links_el = network_root.find("links")
    if links_el is None:
        return {"car_links_before_sanitize": 0, "car_links_after_sanitize": 0, "car_modes_removed": 0, "car_only_links_converted_to_pt": 0}

    links = list(links_el.findall("link"))
    car_edges: list[tuple[str, str]] = []
    for link in links:
        modes = _split_modes(link.attrib.get("modes", ""))
        if "car" in modes:
            car_edges.append((link.attrib["from"], link.attrib["to"]))

    largest_car_component = _largest_strongly_connected_component(car_edges)
    removed = 0
    converted_to_pt = 0
    for link in links:
        modes = _split_modes(link.attrib.get("modes", ""))
        if "car" not in modes:
            continue
        if link.attrib["from"] in largest_car_component and link.attrib["to"] in largest_car_component:
            continue
        modes = [m for m in modes if m != "car"]
        removed += 1
        if not modes:
            modes = ["pt"]
            converted_to_pt += 1
        link.set("modes", ",".join(modes))

    car_after = 0
    for link in links:
        if "car" in _split_modes(link.attrib.get("modes", "")):
            car_after += 1
    return {
        "car_links_before_sanitize": len(car_edges),
        "largest_car_scc_nodes": len(largest_car_component),
        "car_links_after_sanitize": car_after,
        "car_modes_removed": removed,
        "car_only_links_converted_to_pt": converted_to_pt,
    }


def sanitize_route_profiles_for_link_order(schedule_root: ET.Element) -> dict[str, Any]:
    stops_el = schedule_root.find("transitStops")
    if stops_el is None:
        return {"route_profile_stops_removed_for_order": 0, "routes_with_ordered_stop_removals": 0}
    stop_link = {sf.attrib["id"]: sf.attrib.get("linkRefId") for sf in stops_el.findall("stopFacility")}

    removed_total = 0
    affected_routes = 0
    routes_with_too_few_stops = 0
    for line in schedule_root.findall("transitLine"):
        for route in line.findall("transitRoute"):
            route_profile = route.find("routeProfile")
            route_links_el = route.find("route")
            if route_profile is None or route_links_el is None:
                continue
            route_links = [link.attrib["refId"] for link in route_links_el.findall("link")]
            cursor = -1
            keep: list[ET.Element] = []
            remove: list[ET.Element] = []
            for stop in list(route_profile.findall("stop")):
                ref_id = stop.attrib.get("refId")
                link_id = stop_link.get(ref_id or "")
                try:
                    pos = route_links.index(link_id, cursor + 1)
                except ValueError:
                    remove.append(stop)
                    continue
                cursor = pos
                keep.append(stop)
            if remove:
                affected_routes += 1
                removed_total += len(remove)
                if len(keep) < 2:
                    routes_with_too_few_stops += 1
                for stop in remove:
                    route_profile.remove(stop)

    return {
        "route_profile_stops_removed_for_order": removed_total,
        "routes_with_ordered_stop_removals": affected_routes,
        "routes_with_too_few_stops_after_order_sanitize": routes_with_too_few_stops,
    }


def merge_network(bus_network: Path, metro_network: Path, out_path: Path, out_dir: Path) -> dict[str, Any]:
    bus_tree = read_xml_gz(bus_network)
    metro_tree = read_xml_gz(metro_network)
    bus_root = bus_tree.getroot()
    metro_root = metro_tree.getroot()

    bus_nodes_el = bus_root.find("nodes")
    bus_links_el = bus_root.find("links")
    metro_nodes_el = metro_root.find("nodes")
    metro_links_el = metro_root.find("links")
    if None in (bus_nodes_el, bus_links_el, metro_nodes_el, metro_links_el):
        raise ValueError("Invalid network XML structure")

    bus_node_ids = collect_ids(bus_root, "./nodes/node")
    metro_node_ids = collect_ids(metro_root, "./nodes/node")
    bus_link_ids = collect_ids(bus_root, "./links/link")
    metro_link_ids = collect_ids(metro_root, "./links/link")
    conflicts: list[dict[str, str]] = []
    for node_id in sorted(bus_node_ids & metro_node_ids):
        conflicts.append({"kind": "network_node", "id": node_id, "source_a": str(bus_network), "source_b": str(metro_network)})
    for link_id in sorted(bus_link_ids & metro_link_ids):
        conflicts.append({"kind": "network_link", "id": link_id, "source_a": str(bus_network), "source_b": str(metro_network)})
    fail_on_conflicts(conflicts, out_dir)

    for node in list(metro_nodes_el):
        bus_nodes_el.append(node)
    for link in list(metro_links_el):
        bus_links_el.append(link)

    sanitize_stats = sanitize_car_modes_for_routing(bus_root)
    write_xml_gz(out_path, bus_root, '<!DOCTYPE network SYSTEM "http://www.matsim.org/files/dtd/network_v1.dtd">')
    return {
        "bus_nodes": len(bus_node_ids),
        "bus_links": len(bus_link_ids),
        "metro_nodes": len(metro_node_ids),
        "metro_links": len(metro_link_ids),
        "integrated_nodes": len(bus_node_ids) + len(metro_node_ids),
        "integrated_links": len(bus_link_ids) + len(metro_link_ids),
        **sanitize_stats,
    }


def merge_schedule(bus_schedule: Path, metro_schedule: Path, out_path: Path, out_dir: Path) -> dict[str, Any]:
    bus_root = read_xml_gz(bus_schedule).getroot()
    metro_root = read_xml_gz(metro_schedule).getroot()
    bus_stops_el = bus_root.find("transitStops")
    metro_stops_el = metro_root.find("transitStops")
    if bus_stops_el is None or metro_stops_el is None:
        raise ValueError("Invalid transitSchedule XML structure")

    bus_stop_ids = collect_ids(bus_root, "./transitStops/stopFacility")
    metro_stop_ids = collect_ids(metro_root, "./transitStops/stopFacility")
    bus_line_ids = collect_ids(bus_root, "./transitLine")
    metro_line_ids = collect_ids(metro_root, "./transitLine")
    bus_departure_ids = collect_ids(bus_root, ".//departure")
    metro_departure_ids = collect_ids(metro_root, ".//departure")

    conflicts: list[dict[str, str]] = []
    for stop_id in sorted(bus_stop_ids & metro_stop_ids):
        conflicts.append({"kind": "stopFacility", "id": stop_id, "source_a": str(bus_schedule), "source_b": str(metro_schedule)})
    for line_id in sorted(bus_line_ids & metro_line_ids):
        conflicts.append({"kind": "transitLine", "id": line_id, "source_a": str(bus_schedule), "source_b": str(metro_schedule)})
    for dep_id in sorted(bus_departure_ids & metro_departure_ids):
        conflicts.append({"kind": "departure", "id": dep_id, "source_a": str(bus_schedule), "source_b": str(metro_schedule)})
    fail_on_conflicts(conflicts, out_dir)

    for stop in list(metro_stops_el):
        bus_stops_el.append(stop)
    for line in metro_root.findall("transitLine"):
        bus_root.append(line)

    route_order_stats = sanitize_route_profiles_for_link_order(bus_root)
    write_xml_gz(out_path, bus_root, '<!DOCTYPE transitSchedule SYSTEM "http://www.matsim.org/files/dtd/transitSchedule_v2.dtd">')
    return {
        "bus_stops": len(bus_stop_ids),
        "bus_lines": len(bus_line_ids),
        "bus_departures": len(bus_departure_ids),
        "metro_stops": len(metro_stop_ids),
        "metro_lines": len(metro_line_ids),
        "metro_departures": len(metro_departure_ids),
        "integrated_stops": len(bus_stop_ids) + len(metro_stop_ids),
        "integrated_lines": len(bus_line_ids) + len(metro_line_ids),
        "integrated_departures": len(bus_departure_ids) + len(metro_departure_ids),
        **route_order_stats,
    }


def merge_vehicles(bus_vehicles: Path, metro_vehicles: Path, out_path: Path, out_dir: Path) -> dict[str, Any]:
    bus_root = read_xml_gz(bus_vehicles).getroot()
    metro_root = read_xml_gz(metro_vehicles).getroot()

    bus_type_ids = collect_ids(bus_root, "./vehicleType")
    metro_type_ids = collect_ids(metro_root, "./vehicleType")
    bus_vehicle_ids = collect_ids(bus_root, "./vehicle")
    metro_vehicle_ids = collect_ids(metro_root, "./vehicle")
    conflicts: list[dict[str, str]] = []
    for type_id in sorted(bus_type_ids & metro_type_ids):
        conflicts.append({"kind": "vehicleType", "id": type_id, "source_a": str(bus_vehicles), "source_b": str(metro_vehicles)})
    for vehicle_id in sorted(bus_vehicle_ids & metro_vehicle_ids):
        conflicts.append({"kind": "vehicle", "id": vehicle_id, "source_a": str(bus_vehicles), "source_b": str(metro_vehicles)})
    fail_on_conflicts(conflicts, out_dir)

    vehicle_types = list(bus_root.findall("vehicleType")) + list(metro_root.findall("vehicleType"))
    vehicles = list(bus_root.findall("vehicle")) + list(metro_root.findall("vehicle"))
    bus_root.clear()

    for vehicle_type in vehicle_types:
        for legacy_child_name in ("accessTime", "egressTime", "doorOperation"):
            legacy_child = vehicle_type.find(legacy_child_name)
            if legacy_child is not None:
                vehicle_type.remove(legacy_child)
        if vehicle_type.find("networkMode") is None:
            network_mode = ET.Element("networkMode")
            network_mode.set("networkMode", "pt")
            pce = vehicle_type.find("passengerCarEquivalents")
            if pce is None:
                vehicle_type.append(network_mode)
            else:
                vehicle_type.insert(list(vehicle_type).index(pce) + 1, network_mode)
        bus_root.append(vehicle_type)
    for vehicle in vehicles:
        bus_root.append(vehicle)

    ET.register_namespace("xsi", XSI)
    bus_root.set("xmlns", MATSIM_DTD_NS)
    bus_root.set(
        f"{{{XSI}}}schemaLocation",
        f"{MATSIM_DTD_NS} http://www.matsim.org/files/dtd/vehicleDefinitions_v2.0.xsd",
    )
    write_xml_gz(out_path, bus_root, None)
    return {
        "bus_vehicle_types": len(bus_type_ids),
        "bus_vehicles": len(bus_vehicle_ids),
        "metro_vehicle_types": len(metro_type_ids),
        "metro_vehicles": len(metro_vehicle_ids),
        "integrated_vehicle_types": len(bus_type_ids) + len(metro_type_ids),
        "integrated_vehicles": len(bus_vehicle_ids) + len(metro_vehicle_ids),
    }


def validate_integrated(network_path: Path, schedule_path: Path, vehicles_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    network_root = read_xml_gz(network_path).getroot()
    schedule_root = read_xml_gz(schedule_path).getroot()
    vehicles_root = read_xml_gz(vehicles_path).getroot()
    links = {el.attrib["id"]: el.attrib for el in network_root.find("links").findall("link")}  # type: ignore[union-attr]
    stops = {el.attrib["id"]: el.attrib.get("linkRefId") for el in schedule_root.find("transitStops").findall("stopFacility")}  # type: ignore[union-attr]
    vehicles = {el.attrib["id"] for el in findall_local(vehicles_root, "vehicle")}

    qa_rows: list[dict[str, Any]] = []
    missing_stop_links = 0
    missing_route_links = 0
    non_pt_route_links = 0
    missing_stop_refs = 0
    stop_link_not_in_route = 0
    missing_vehicle_refs = 0
    discontinuities = 0
    route_count = 0
    departure_count = 0
    for stop_id, link_id in stops.items():
        if link_id not in links:
            missing_stop_links += 1
            qa_rows.append({"check": "stop_link_missing", "id": stop_id, "detail": str(link_id)})

    for line in schedule_root.findall("transitLine"):
        line_id = line.attrib["id"]
        for route in line.findall("transitRoute"):
            route_count += 1
            route_id = route.attrib["id"]
            route_links = [el.attrib["refId"] for el in route.find("route").findall("link")]  # type: ignore[union-attr]
            route_link_set = set(route_links)
            for link_id in route_links:
                if link_id not in links:
                    missing_route_links += 1
                    qa_rows.append({"check": "route_link_missing", "id": f"{line_id}/{route_id}", "detail": link_id})
                elif "pt" not in links[link_id].get("modes", "").split(","):
                    non_pt_route_links += 1
                    qa_rows.append({"check": "route_link_without_pt_mode", "id": f"{line_id}/{route_id}", "detail": link_id})
            for a, b in zip(route_links, route_links[1:]):
                if a in links and b in links and links[a]["to"] != links[b]["from"]:
                    discontinuities += 1
                    qa_rows.append({"check": "route_discontinuity", "id": f"{line_id}/{route_id}", "detail": f"{a}->{b}"})
            for stop in route.find("routeProfile").findall("stop"):  # type: ignore[union-attr]
                stop_id = stop.attrib["refId"]
                link_id = stops.get(stop_id)
                if stop_id not in stops:
                    missing_stop_refs += 1
                    qa_rows.append({"check": "stop_ref_missing", "id": f"{line_id}/{route_id}", "detail": stop_id})
                elif link_id not in route_link_set:
                    stop_link_not_in_route += 1
                    qa_rows.append({"check": "stop_link_not_in_route", "id": f"{line_id}/{route_id}", "detail": f"{stop_id}:{link_id}"})
            for dep in route.find("departures").findall("departure"):  # type: ignore[union-attr]
                departure_count += 1
                vehicle_id = dep.attrib["vehicleRefId"]
                if vehicle_id not in vehicles:
                    missing_vehicle_refs += 1
                    qa_rows.append({"check": "departure_vehicle_missing", "id": f"{line_id}/{route_id}", "detail": vehicle_id})

    summary = {
        "network_links": len(links),
        "schedule_stops": len(stops),
        "transit_routes": route_count,
        "departures": departure_count,
        "vehicles": len(vehicles),
        "missing_stop_links": missing_stop_links,
        "missing_route_links": missing_route_links,
        "non_pt_route_links": non_pt_route_links,
        "missing_stop_refs": missing_stop_refs,
        "stop_link_not_in_route": stop_link_not_in_route,
        "missing_vehicle_refs": missing_vehicle_refs,
        "route_discontinuities": discontinuities,
        "qa_issue_count": len(qa_rows),
    }
    return summary, qa_rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bus-network", type=Path, default=BUS_DIR / "bus_network_with_pt.xml.gz")
    parser.add_argument("--bus-schedule", type=Path, default=BUS_DIR / "bus_transitSchedule.xml.gz")
    parser.add_argument("--bus-vehicles", type=Path, default=BUS_DIR / "bus_transitVehicles.xml.gz")
    parser.add_argument("--metro-network", type=Path, default=METRO_DIR / "metro_network.xml.gz")
    parser.add_argument("--metro-schedule", type=Path, default=METRO_DIR / "metro_transitSchedule.xml.gz")
    parser.add_argument("--metro-vehicles", type=Path, default=METRO_DIR / "metro_transitVehicles.xml.gz")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    network_out = out_dir / "network_with_car_bus_metro.xml.gz"
    schedule_out = out_dir / "transitSchedule.xml.gz"
    vehicles_out = out_dir / "transitVehicles.xml.gz"
    qa_out = out_dir / "transit_integration_qa.csv"
    summary_out = out_dir / "transit_integration_summary.json"

    network_counts = merge_network(args.bus_network, args.metro_network, network_out, out_dir)
    schedule_counts = merge_schedule(args.bus_schedule, args.metro_schedule, schedule_out, out_dir)
    vehicle_counts = merge_vehicles(args.bus_vehicles, args.metro_vehicles, vehicles_out, out_dir)
    validation_counts, qa_rows = validate_integrated(network_out, schedule_out, vehicles_out)
    write_csv(qa_out, qa_rows, ["check", "id", "detail"])

    summary = {
        "created_by": "scripts/integrate_fuzhou_bus_metro_transit.py",
        "coordinate_system": "EPSG:32650",
        "inputs": {
            "bus_network": str(args.bus_network),
            "bus_schedule": str(args.bus_schedule),
            "bus_vehicles": str(args.bus_vehicles),
            "metro_network": str(args.metro_network),
            "metro_schedule": str(args.metro_schedule),
            "metro_vehicles": str(args.metro_vehicles),
        },
        "outputs": {
            "network": str(network_out),
            "transitSchedule": str(schedule_out),
            "transitVehicles": str(vehicles_out),
            "qa_csv": str(qa_out),
            "summary_json": str(summary_out),
        },
        "counts": {
            **network_counts,
            **schedule_counts,
            **vehicle_counts,
            **validation_counts,
        },
    }
    summary_out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary["counts"], ensure_ascii=False, indent=2))
    print(f"Wrote {network_out}")
    print(f"Wrote {schedule_out}")
    print(f"Wrote {vehicles_out}")
    if validation_counts["qa_issue_count"]:
        raise RuntimeError(f"Integration QA failed with {validation_counts['qa_issue_count']} issues; see {qa_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
