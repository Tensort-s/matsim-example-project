#!/usr/bin/env python3
"""Build the Hong Kong mixed-traffic supply with 5%-scaled road-PT PCUs.

Bus and GMB services retain their original road-network routes and full
timetable. Only their MATSim passenger-car-equivalent values are multiplied by
the requested factor. Passenger capacities, vehicle dimensions, rail vehicle
types, routes, stops, and departures are unchanged.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import shutil
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

from build_hong_kong_dedicated_road_pt_layer import (
    sha256_file,
    write_config,
    write_json,
)


DEFAULT_DATA_ROOT = Path(r"F:\Matsim\matsim-example-project\data")
ROAD_PT_MODES = frozenset({"bus", "gmb"})
MATSIM_NAMESPACE = "http://www.matsim.org/files/dtd"
XSI_NAMESPACE = "http://www.w3.org/2001/XMLSchema-instance"


def qname(local_name: str) -> str:
    return f"{{{MATSIM_NAMESPACE}}}{local_name}"


def load_vehicle_definitions(path: Path) -> ET.Element:
    with gzip.open(path, "rb") as handle:
        return ET.parse(handle).getroot()


def write_vehicle_definitions(root: ET.Element, path: Path) -> None:
    ET.register_namespace("", MATSIM_NAMESPACE)
    ET.register_namespace("xsi", XSI_NAMESPACE)
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as handle:
        handle.write('<?xml version="1.0" encoding="utf-8"?>\n')
        handle.write(ET.tostring(root, encoding="unicode"))
        handle.write("\n")


def load_route_vehicle_modes(schedule_path: Path) -> dict[str, str]:
    with gzip.open(schedule_path, "rb") as handle:
        root = ET.parse(handle).getroot()
    result: dict[str, str] = {}
    for line in root.findall("./transitLine"):
        for route in line.findall("./transitRoute"):
            mode = (route.findtext("./transportMode") or "").strip()
            departures = route.find("./departures")
            if departures is None:
                continue
            for departure in departures.findall("./departure"):
                vehicle_id = departure.attrib["vehicleRefId"]
                previous = result.setdefault(vehicle_id, mode)
                if previous != mode:
                    raise ValueError(
                        f"Vehicle {vehicle_id} is shared by modes {previous} and {mode}"
                    )
    return result


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
    if not 0 < args.pcu_factor <= 1:
        raise ValueError("--pcu-factor must be in (0, 1]")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.config_dir.mkdir(parents=True, exist_ok=True)
    output_network = args.output_dir / "network.xml.gz"
    output_schedule = args.output_dir / "transitSchedule_5pct.xml.gz"
    output_vehicles = args.output_dir / "transitVehicles_5pct.xml.gz"
    shutil.copy2(args.input_network, output_network)
    shutil.copy2(args.input_schedule, output_schedule)

    vehicle_root = load_vehicle_definitions(args.input_transit_vehicles)
    vehicle_types = {
        element.attrib["id"]: element
        for element in vehicle_root.findall(qname("vehicleType"))
    }
    vehicles = {
        element.attrib["id"]: element.attrib["type"]
        for element in vehicle_root.findall(qname("vehicle"))
    }
    route_vehicle_modes = load_route_vehicle_modes(args.input_schedule)
    type_vehicle_counts = Counter(vehicles.values())
    type_route_vehicle_counts: Counter[str] = Counter()
    for vehicle_id in route_vehicle_modes:
        if vehicle_id not in vehicles:
            raise ValueError(f"Departure references missing vehicle {vehicle_id}")
        type_route_vehicle_counts[vehicles[vehicle_id]] += 1

    audit_rows: list[dict[str, Any]] = []
    road_type_ids: set[str] = set()
    unchanged_values: dict[str, float] = {}
    for type_id, vehicle_type in vehicle_types.items():
        network_mode_element = vehicle_type.find(qname("networkMode"))
        pce_element = vehicle_type.find(qname("passengerCarEquivalents"))
        if network_mode_element is None or pce_element is None:
            raise ValueError(f"Vehicle type {type_id} lacks networkMode or PCE")
        mode = network_mode_element.attrib["networkMode"]
        old_pce = float(pce_element.attrib["pce"])
        new_pce = old_pce
        if mode in ROAD_PT_MODES:
            new_pce = old_pce * args.pcu_factor
            pce_element.set("pce", f"{new_pce:.6f}")
            road_type_ids.add(type_id)
        else:
            unchanged_values[type_id] = old_pce
        audit_rows.append(
            {
                "vehicle_type_id": type_id,
                "network_mode": mode,
                "vehicle_count": int(type_vehicle_counts[type_id]),
                "departure_vehicle_count": int(type_route_vehicle_counts[type_id]),
                "original_pce": old_pce,
                "pcu_scale_factor": args.pcu_factor if mode in ROAD_PT_MODES else 1.0,
                "scaled_pce": new_pce,
                "passenger_capacity_changed": False,
                "vehicle_dimensions_changed": False,
            }
        )

    if not road_type_ids:
        raise RuntimeError("No bus/GMB vehicle types were found")
    write_vehicle_definitions(vehicle_root, output_vehicles)

    # Reload the output and verify the semantic changes, not just XML writing.
    check_root = load_vehicle_definitions(output_vehicles)
    check_types = {
        element.attrib["id"]: element
        for element in check_root.findall(qname("vehicleType"))
    }
    scale_errors: list[str] = []
    nonroad_change_errors: list[str] = []
    for row in audit_rows:
        type_id = row["vehicle_type_id"]
        pce_element = check_types[type_id].find(qname("passengerCarEquivalents"))
        assert pce_element is not None
        actual = float(pce_element.attrib["pce"])
        expected = float(row["scaled_pce"])
        if abs(actual - expected) > 1e-9:
            scale_errors.append(type_id)
        if type_id in unchanged_values and abs(actual - unchanged_values[type_id]) > 1e-9:
            nonroad_change_errors.append(type_id)

    road_route_wrong_type: list[str] = []
    rail_route_wrong_type: list[str] = []
    for vehicle_id, route_mode in route_vehicle_modes.items():
        type_id = vehicles[vehicle_id]
        if route_mode in ROAD_PT_MODES and type_id not in road_type_ids:
            road_route_wrong_type.append(vehicle_id)
        if route_mode not in ROAD_PT_MODES and type_id in road_type_ids:
            rail_route_wrong_type.append(vehicle_id)

    qa = {
        "vehicle_type_scale_errors": len(scale_errors),
        "nonroad_vehicle_type_changes": len(nonroad_change_errors),
        "road_route_vehicles_with_unscaled_type": len(road_route_wrong_type),
        "nonroad_route_vehicles_with_scaled_type": len(rail_route_wrong_type),
        "missing_departure_vehicles": 0,
    }
    if any(qa.values()):
        raise RuntimeError(f"Mixed road-PT PCU scaling QA failed: {qa}")

    with (args.output_dir / "road_pt_vehicle_pcu_scaling_audit.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(audit_rows[0]))
        writer.writeheader()
        writer.writerows(audit_rows)

    dedicated_baseline = (
        args.config_dir / "config_hong_kong_5pct_010_dedicated_bus_baseline.xml"
    )
    if not dedicated_baseline.exists():
        shutil.copy2(args.template_config, dedicated_baseline)

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
        output_directory=args.config_dir / "matsim_010_mixed_bus_pcu005_smoke_output",
        last_iteration=0,
    )
    write_config(
        main_config,
        formal_config,
        network_path=output_network,
        plans_path=args.plans,
        facilities_path=args.facilities,
        private_vehicles_path=args.private_vehicles,
        schedule_path=output_schedule,
        transit_vehicles_path=output_vehicles,
        output_directory=args.config_dir / "matsim_010_mixed_bus_pcu005_50it_output",
        last_iteration=50,
    )

    summary = {
        "description": "Hong Kong mixed-traffic road PT with scaled bus/GMB PCUs",
        "input_network": str(args.input_network),
        "input_schedule": str(args.input_schedule),
        "input_transit_vehicles": str(args.input_transit_vehicles),
        "output_network": str(output_network),
        "output_schedule": str(output_schedule),
        "output_transit_vehicles": str(output_vehicles),
        "flow_capacity_factor": 0.1,
        "storage_capacity_factor": 0.1,
        "road_pt_pcu_factor": args.pcu_factor,
        "road_pt_vehicle_types_scaled": len(road_type_ids),
        "road_pt_departure_vehicles_scaled": sum(
            1
            for vehicle_id, mode in route_vehicle_modes.items()
            if mode in ROAD_PT_MODES
        ),
        "all_departure_vehicles": len(route_vehicle_modes),
        "vehicle_types_by_network_mode": dict(
            Counter(row["network_mode"] for row in audit_rows)
        ),
        "qa": qa,
        "configs": {
            "active_smoke": str(main_config),
            "formal_50_iterations": str(formal_config),
            "dedicated_bus_baseline": str(dedicated_baseline),
            "mixed_005_baseline": str(
                args.config_dir / "config_hong_kong_5pct_005_mixed_baseline.xml"
            ),
        },
        "sha256": {
            output_network.name: sha256_file(output_network),
            output_schedule.name: sha256_file(output_schedule),
            output_vehicles.name: sha256_file(output_vehicles),
        },
    }
    write_json(args.output_dir / "mixed_road_pt_pcu_scaled_supply_summary.json", summary)
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
    parser.add_argument("--pcu-factor", type=float, default=0.05)
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
        / "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_v1"
    )
    args.config_dir = args.config_dir or scenario
    return args


def main() -> None:
    args = parse_args()
    summary = build(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
