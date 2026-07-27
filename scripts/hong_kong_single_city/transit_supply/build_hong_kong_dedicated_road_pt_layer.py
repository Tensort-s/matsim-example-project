#!/usr/bin/env python3
"""Separate Hong Kong road public transport from private-car traffic.

Bus and GMB routes currently share many TNM road links with cars. This script
creates parallel links for every shared road link referenced by a road-PT route
or stop, rewrites the schedule to use those links, and removes road-PT modes
from the original car links. Rail and Light Rail links are left unchanged.
"""

from __future__ import annotations

import argparse
import copy
import csv
import gzip
import hashlib
import json
import shutil
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_ROOT = Path(r"F:\Matsim\matsim-example-project\data")
ROAD_PT_MODES = frozenset({"bus", "gmb"})
RAIL_MODES = frozenset({"train", "light_rail"})
CLONE_PREFIX = "ptroad__"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_modes(value: str | None) -> set[str]:
    return {item.strip() for item in (value or "").split(",") if item.strip()}


def write_xml_gz(root: ET.Element, path: Path, doctype: str) -> None:
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as handle:
        handle.write('<?xml version="1.0" encoding="utf-8"?>\n')
        handle.write(f'<!DOCTYPE {doctype} SYSTEM "http://www.matsim.org/files/dtd/{doctype}_v2.dtd">\n')
        handle.write(ET.tostring(root, encoding="unicode"))
        handle.write("\n")


def load_xml_gz(path: Path) -> ET.Element:
    with gzip.open(path, "rb") as handle:
        return ET.parse(handle).getroot()


def route_records(schedule_root: ET.Element) -> list[tuple[str, str, ET.Element]]:
    records: list[tuple[str, str, ET.Element]] = []
    for line in schedule_root.findall("./transitLine"):
        line_id = line.attrib["id"]
        for route in line.findall("./transitRoute"):
            mode = (route.findtext("./transportMode") or "").strip()
            records.append((line_id, mode, route))
    return records


def stop_mode_usage(
    routes: list[tuple[str, str, ET.Element]],
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for _, mode, route in routes:
        profile = route.find("./routeProfile")
        if profile is None:
            continue
        for stop in profile.findall("./stop"):
            result[stop.attrib["refId"]].add(mode)
    return result


def set_param(module: ET.Element, name: str, value: str) -> None:
    for param in module.findall("./param"):
        if param.attrib.get("name") == name:
            param.set("value", value)
            return
    ET.SubElement(module, "param", {"name": name, "value": value})


def get_module(root: ET.Element, name: str) -> ET.Element:
    for module in root.findall("./module"):
        if module.attrib.get("name") == name:
            return module
    return ET.SubElement(root, "module", {"name": name})


def write_config(
    template_path: Path,
    output_path: Path,
    *,
    network_path: Path,
    plans_path: Path,
    facilities_path: Path,
    private_vehicles_path: Path,
    schedule_path: Path,
    transit_vehicles_path: Path,
    output_directory: Path,
    last_iteration: int,
) -> None:
    root = ET.parse(template_path).getroot()
    set_param(get_module(root, "network"), "inputNetworkFile", network_path.as_posix())
    set_param(get_module(root, "plans"), "inputPlansFile", plans_path.as_posix())
    set_param(get_module(root, "facilities"), "inputFacilitiesFile", facilities_path.as_posix())
    set_param(get_module(root, "vehicles"), "vehiclesFile", private_vehicles_path.as_posix())

    transit = get_module(root, "transit")
    set_param(transit, "useTransit", "true")
    set_param(transit, "transitScheduleFile", schedule_path.as_posix())
    set_param(transit, "vehiclesFile", transit_vehicles_path.as_posix())
    set_param(transit, "transitModes", "bus,gmb,train,light_rail")

    qsim = get_module(root, "qsim")
    set_param(qsim, "flowCapacityFactor", "0.1")
    set_param(qsim, "storageCapacityFactor", "0.1")
    set_param(qsim, "numberOfThreads", "8")
    set_param(qsim, "stuckTime", "600")
    set_param(qsim, "removeStuckVehicles", "true")
    set_param(qsim, "vehiclesSource", "fromVehiclesData")

    controller = get_module(root, "controller")
    set_param(controller, "firstIteration", "0")
    set_param(controller, "lastIteration", str(last_iteration))
    set_param(controller, "outputDirectory", output_directory.as_posix())
    set_param(
        controller,
        "overwriteFiles",
        "deleteDirectoryIfExists" if last_iteration == 0 else "failIfDirectoryExists",
    )
    set_param(controller, "writeEventsInterval", "1" if last_iteration == 0 else "10")
    set_param(controller, "writePlansInterval", "1" if last_iteration == 0 else "10")
    set_param(controller, "writeSnapshotsInterval", "0")

    replanning = get_module(root, "replanning")
    for settings in replanning.findall("./parameterset"):
        names = {
            param.attrib.get("name"): param
            for param in settings.findall("./param")
        }
        if names.get("strategyName", ET.Element("x")).attrib.get("value") == "ReRoute":
            if "disableAfterIteration" in names:
                names["disableAfterIteration"].set(
                    "value",
                    "0" if last_iteration == 0 else str(max(1, last_iteration - 10)),
                )

    with output_path.open("wt", encoding="utf-8", newline="\n") as handle:
        handle.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        handle.write('<!DOCTYPE config SYSTEM "http://www.matsim.org/files/dtd/config_v2.dtd">\n')
        handle.write(ET.tostring(root, encoding="unicode"))
        handle.write("\n")


def build(args: argparse.Namespace) -> dict[str, Any]:
    for path in (
        args.input_network,
        args.input_schedule,
        args.input_transit_vehicles,
        args.template_config,
        args.plans,
        args.facilities,
        args.private_vehicles,
    ):
        if not path.exists():
            raise FileNotFoundError(path)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    network_root = load_xml_gz(args.input_network)
    schedule_root = load_xml_gz(args.input_schedule)
    links_element = network_root.find("./links")
    stops_element = schedule_root.find("./transitStops")
    if links_element is None or stops_element is None:
        raise ValueError("Invalid MATSim network or transit schedule")

    links = {link.attrib["id"]: link for link in links_element.findall("./link")}
    original_link_ids = set(links)
    routes = route_records(schedule_root)
    stop_usage = stop_mode_usage(routes)
    facilities = {
        facility.attrib["id"]: facility
        for facility in stops_element.findall("./stopFacility")
    }

    shared_links = {
        link_id
        for link_id, link in links.items()
        if "car" in parse_modes(link.attrib.get("modes"))
        and ROAD_PT_MODES & parse_modes(link.attrib.get("modes"))
    }
    route_shared_links: set[str] = set()
    route_link_counts: Counter[str] = Counter()
    for _, mode, route in routes:
        if mode not in ROAD_PT_MODES:
            continue
        network_route = route.find("./route")
        if network_route is None:
            continue
        for ref in network_route.findall("./link"):
            link_id = ref.attrib["refId"]
            route_link_counts[link_id] += 1
            if link_id in shared_links:
                route_shared_links.add(link_id)

    stop_shared_links: set[str] = set()
    for facility_id, modes in stop_usage.items():
        if not ROAD_PT_MODES & modes:
            continue
        facility = facilities.get(facility_id)
        if facility is None:
            raise ValueError(f"Missing stop facility {facility_id}")
        link_id = facility.attrib.get("linkRefId", "")
        if link_id in shared_links:
            stop_shared_links.add(link_id)

    clone_source_ids = route_shared_links | stop_shared_links
    clone_map = {
        link_id: f"{CLONE_PREFIX}{link_id}"
        for link_id in sorted(clone_source_ids)
    }
    duplicate_ids = set(clone_map.values()) & original_link_ids
    if duplicate_ids:
        raise ValueError(f"Dedicated link IDs already exist: {sorted(duplicate_ids)[:5]}")

    crosswalk_rows: list[dict[str, Any]] = []
    for source_id in sorted(clone_source_ids):
        source = links[source_id]
        clone = copy.deepcopy(source)
        clone_id = clone_map[source_id]
        clone.set("id", clone_id)
        clone.set("modes", "bus,gmb,pt")
        original_capacity = float(source.attrib.get("capacity", "0"))
        clone.set("capacity", f"{max(original_capacity, args.pt_link_capacity):.6g}")
        links_element.append(clone)
        links[clone_id] = clone
        crosswalk_rows.append(
            {
                "source_link_id": source_id,
                "dedicated_link_id": clone_id,
                "from_node": source.attrib["from"],
                "to_node": source.attrib["to"],
                "length_m": float(source.attrib["length"]),
                "freespeed_mps": float(source.attrib["freespeed"]),
                "source_capacity_veh_h": original_capacity,
                "dedicated_capacity_veh_h": float(clone.attrib["capacity"]),
                "permlanes": float(source.attrib.get("permlanes", "1")),
                "route_reference_count": int(route_link_counts[source_id]),
                "used_as_stop_link": source_id in stop_shared_links,
            }
        )

    changed_original_links = 0
    for source_id in shared_links:
        link = links[source_id]
        modes = parse_modes(link.attrib.get("modes"))
        car_modes = modes - {"bus", "gmb", "pt"}
        car_modes.add("car")
        link.set("modes", ",".join(sorted(car_modes)))
        changed_original_links += 1

    changed_route_refs = 0
    route_audit_rows: list[dict[str, Any]] = []
    for line_id, mode, route in routes:
        network_route = route.find("./route")
        if network_route is None:
            continue
        refs = network_route.findall("./link")
        before = [ref.attrib["refId"] for ref in refs]
        if mode in ROAD_PT_MODES:
            for ref in refs:
                if ref.attrib["refId"] in clone_map:
                    ref.set("refId", clone_map[ref.attrib["refId"]])
                    changed_route_refs += 1
        after = [ref.attrib["refId"] for ref in refs]
        route_audit_rows.append(
            {
                "transit_line_id": line_id,
                "transit_route_id": route.attrib["id"],
                "mode": mode,
                "link_count": len(after),
                "dedicated_link_occurrences": sum(
                    link_id.startswith(CLONE_PREFIX) for link_id in after
                ),
                "changed_link_occurrences": sum(
                    left != right for left, right in zip(before, after)
                ),
            }
        )

    changed_stop_refs = 0
    stop_audit_rows: list[dict[str, Any]] = []
    for facility_id, facility in facilities.items():
        modes = stop_usage.get(facility_id, set())
        original_ref = facility.attrib.get("linkRefId", "")
        new_ref = original_ref
        if ROAD_PT_MODES & modes and original_ref in clone_map:
            if RAIL_MODES & modes:
                raise ValueError(
                    f"Road and rail modes unexpectedly share facility {facility_id}"
                )
            new_ref = clone_map[original_ref]
            facility.set("linkRefId", new_ref)
            changed_stop_refs += 1
        if ROAD_PT_MODES & modes:
            stop_audit_rows.append(
                {
                    "facility_id": facility_id,
                    "modes": ",".join(sorted(modes)),
                    "original_link_ref_id": original_ref,
                    "new_link_ref_id": new_ref,
                    "changed": original_ref != new_ref,
                }
            )

    output_network = args.output_dir / "network.xml.gz"
    output_schedule = args.output_dir / "transitSchedule_5pct.xml.gz"
    output_vehicles = args.output_dir / "transitVehicles_5pct.xml.gz"
    write_xml_gz(network_root, output_network, "network")
    write_xml_gz(schedule_root, output_schedule, "transitSchedule")
    shutil.copy2(args.input_transit_vehicles, output_vehicles)

    with (args.output_dir / "dedicated_bus_link_crosswalk.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(crosswalk_rows[0]))
        writer.writeheader()
        writer.writerows(crosswalk_rows)
    with (args.output_dir / "dedicated_bus_stop_crosswalk.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(stop_audit_rows[0]))
        writer.writeheader()
        writer.writerows(stop_audit_rows)
    with (args.output_dir / "dedicated_bus_route_audit.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(route_audit_rows[0]))
        writer.writeheader()
        writer.writerows(route_audit_rows)

    final_links = {
        link.attrib["id"]: link
        for link in links_element.findall("./link")
    }
    missing_route_refs: list[str] = []
    road_pt_refs_on_car_links: list[str] = []
    continuity_errors = 0
    for _, mode, route in routes:
        network_route = route.find("./route")
        if network_route is None:
            continue
        ids = [ref.attrib["refId"] for ref in network_route.findall("./link")]
        for link_id in ids:
            if link_id not in final_links:
                missing_route_refs.append(link_id)
            elif mode in ROAD_PT_MODES and "car" in parse_modes(
                final_links[link_id].attrib.get("modes")
            ):
                road_pt_refs_on_car_links.append(link_id)
        continuity_errors += sum(
            final_links[left].attrib["to"] != final_links[right].attrib["from"]
            for left, right in zip(ids[:-1], ids[1:])
            if left in final_links and right in final_links
        )

    missing_stop_refs: list[str] = []
    road_pt_stops_on_car_links: list[str] = []
    for facility_id, modes in stop_usage.items():
        facility = facilities[facility_id]
        link_id = facility.attrib.get("linkRefId", "")
        if link_id not in final_links:
            missing_stop_refs.append(link_id)
        elif ROAD_PT_MODES & modes and "car" in parse_modes(
            final_links[link_id].attrib.get("modes")
        ):
            road_pt_stops_on_car_links.append(facility_id)

    remaining_mixed_links = sum(
        "car" in parse_modes(link.attrib.get("modes"))
        and bool(ROAD_PT_MODES & parse_modes(link.attrib.get("modes")))
        for link in final_links.values()
    )
    qa = {
        "missing_route_link_references": len(missing_route_refs),
        "missing_stop_link_references": len(missing_stop_refs),
        "road_pt_route_references_on_car_links": len(road_pt_refs_on_car_links),
        "road_pt_stops_on_car_links": len(road_pt_stops_on_car_links),
        "route_link_continuity_errors": continuity_errors,
        "remaining_car_bus_gmb_mixed_links": remaining_mixed_links,
    }
    if any(qa.values()):
        raise RuntimeError(f"Dedicated road-PT layer QA failed: {qa}")

    baseline_config = args.config_dir / "config_hong_kong_5pct_005_mixed_baseline.xml"
    if not baseline_config.exists():
        shutil.copy2(args.template_config, baseline_config)
    main_config = args.config_dir / "config_hong_kong_5pct.xml"
    formal_config = args.config_dir / "config_hong_kong_5pct_50it.xml"
    write_config(
        args.template_config,
        main_config,
        network_path=output_network,
        plans_path=args.plans,
        facilities_path=args.facilities,
        private_vehicles_path=args.private_vehicles,
        schedule_path=output_schedule,
        transit_vehicles_path=output_vehicles,
        output_directory=args.config_dir / "matsim_010_dedicated_bus_smoke_output",
        last_iteration=0,
    )
    write_config(
        args.template_config,
        formal_config,
        network_path=output_network,
        plans_path=args.plans,
        facilities_path=args.facilities,
        private_vehicles_path=args.private_vehicles,
        schedule_path=output_schedule,
        transit_vehicles_path=output_vehicles,
        output_directory=args.config_dir / "matsim_010_dedicated_bus_50it_output",
        last_iteration=50,
    )

    summary = {
        "description": "Hong Kong 5% MATSim supply with road PT separated from private cars",
        "input_network": str(args.input_network),
        "input_schedule": str(args.input_schedule),
        "output_network": str(output_network),
        "output_schedule": str(output_schedule),
        "flow_capacity_factor": 0.1,
        "storage_capacity_factor": 0.1,
        "dedicated_pt_link_capacity_floor_veh_h_full_scale": args.pt_link_capacity,
        "network_links_before": len(original_link_ids),
        "network_links_after": len(final_links),
        "mixed_links_converted_to_car_only": changed_original_links,
        "dedicated_links_created": len(clone_map),
        "route_link_references_changed": changed_route_refs,
        "stop_link_references_changed": changed_stop_refs,
        "route_modes": dict(Counter(mode for _, mode, _ in routes)),
        "qa": qa,
        "configs": {
            "smoke": str(main_config),
            "formal_50_iterations": str(formal_config),
            "mixed_005_baseline": str(baseline_config),
        },
        "sha256": {
            output_network.name: sha256_file(output_network),
            output_schedule.name: sha256_file(output_schedule),
            output_vehicles.name: sha256_file(output_vehicles),
        },
    }
    write_json(args.output_dir / "dedicated_road_pt_supply_summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--input-network", type=Path)
    parser.add_argument("--input-schedule", type=Path)
    parser.add_argument("--input-transit-vehicles", type=Path)
    parser.add_argument("--template-config", type=Path)
    parser.add_argument("--plans", type=Path)
    parser.add_argument("--facilities", type=Path)
    parser.add_argument("--private-vehicles", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--config-dir", type=Path)
    parser.add_argument("--pt-link-capacity", type=float, default=10000.0)
    args = parser.parse_args()

    scenario = (
        args.data_root
        / "matsim_agents"
        / "hongkong"
        / "typical_weekday_5pct_v1"
    )
    args.input_network = args.input_network or (
        args.data_root
        / "transit"
        / "hongkong"
        / "processed"
        / "road_capacity_hybrid_tpdm_flow_2026_v1"
        / "network_hybrid_capacity.xml.gz"
    )
    args.input_schedule = args.input_schedule or scenario / "transitSchedule_5pct.xml.gz"
    args.input_transit_vehicles = (
        args.input_transit_vehicles or scenario / "transitVehicles_5pct.xml.gz"
    )
    args.template_config = args.template_config or scenario / "config_hong_kong_5pct.xml"
    args.plans = args.plans or scenario / "plans_routed_5pct.xml.gz"
    args.facilities = args.facilities or scenario / "facilities_5pct.xml.gz"
    args.private_vehicles = (
        args.private_vehicles or scenario / "privateVehicles_5pct.xml.gz"
    )
    args.output_dir = args.output_dir or (
        args.data_root
        / "transit"
        / "hongkong"
        / "processed"
        / "matsim_road_pt_supply_2026_hybrid_capacity_dedicated_bus_v1"
    )
    args.config_dir = args.config_dir or scenario
    return args


def main() -> None:
    args = parse_args()
    summary = build(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
