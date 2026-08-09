#!/usr/bin/env python3
"""Audit the Stage 11 no-innovation physical non-Taxi integration gate."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import contextlib
import gzip
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET


MAIN_MODES = {"car", "car_passenger", "pt", "school_bus", "taxi", "walk"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--exit-code", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


@contextlib.contextmanager
def xml_stream(path: Path):
    if path.suffix == ".gz":
        with gzip.open(path, "rb") as handle:
            yield handle
        return
    if path.suffix == ".zst":
        process = subprocess.Popen(["zstd", "-q", "-dc", str(path)], stdout=subprocess.PIPE)
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


def audit_events(path: Path) -> dict[str, object]:
    counts: Counter[str] = Counter()
    departures: Counter[str] = Counter()
    arrivals: Counter[str] = Counter()
    teleported: Counter[str] = Counter()
    teleported_main: Counter[str] = Counter()
    teleported_main_samples: dict[str, list[str]] = defaultdict(list)
    stuck: Counter[str] = Counter()
    stuck_by_entity_class: Counter[str] = Counter()
    stuck_person_samples: dict[str, list[str]] = defaultdict(list)
    pt_active: Counter[bytes] = Counter()
    pt_boardings_on_active_leg: Counter[bytes] = Counter()
    pt_onboard: set[bytes] = set()
    pt_person_stuck_state: Counter[str] = Counter()
    person_stuck_time_hour: Counter[str] = Counter()
    walk_active: Counter[bytes] = Counter()
    active_effective_mode: dict[bytes, str] = {}
    pt_vehicle_entries = 0
    pt_vehicle_leaves = 0
    pt_people_boarded: set[bytes] = set()
    pt_people_alighted: set[bytes] = set()

    with xml_stream(path) as handle:
        for line in handle:
            if b"<event " not in line:
                continue
            event_type = byte_attribute(line, b"type").decode()
            person = byte_attribute(line, b"person")
            mode = (
                byte_attribute(line, b"legMode")
                or byte_attribute(line, b"networkMode")
                or byte_attribute(line, b"mode")
            ).decode()
            routing_mode = byte_attribute(line, b"computationalRoutingMode").decode()
            vehicle = byte_attribute(line, b"vehicle")

            if event_type == "departure" and mode in MAIN_MODES:
                effective = routing_mode or mode
                departures[effective] += 1
                active_effective_mode[person] = effective
                if mode == "pt":
                    pt_active[person] += 1
                    pt_boardings_on_active_leg[person] = 0
                    pt_onboard.discard(person)
                elif mode == "walk":
                    walk_active[person] += 1
            elif event_type == "arrival" and mode in MAIN_MODES:
                arrivals[mode] += 1
                active_effective_mode.pop(person, None)
                if mode == "pt" and pt_active[person]:
                    pt_active[person] -= 1
                    pt_boardings_on_active_leg.pop(person, None)
                    pt_onboard.discard(person)
                elif mode == "walk" and walk_active[person]:
                    walk_active[person] -= 1
            elif event_type == "travelled" and mode:
                teleported[mode] += 1
                effective = active_effective_mode.get(person, routing_mode or mode)
                if effective == mode and mode in MAIN_MODES:
                    teleported_main[mode] += 1
                    if len(teleported_main_samples[mode]) < 20:
                        teleported_main_samples[mode].append(person.decode())
            elif "stuck" in event_type.lower() and mode:
                stuck[mode] += 1
                entity = person or vehicle
                if entity.startswith(b"pt_veh_"):
                    entity_class = "regular_pt_vehicle"
                elif entity.startswith(b"veh_school_bus_v6_"):
                    entity_class = "school_bus_vehicle"
                else:
                    entity_class = "person"
                    event_time = float(byte_attribute(line, b"time") or b"0")
                    person_stuck_time_hour[str(int(event_time // 3_600))] += 1
                    if len(stuck_person_samples[mode]) < 20:
                        stuck_person_samples[mode].append(entity.decode())
                stuck_by_entity_class[entity_class] += 1
                if mode == "pt" and pt_active[person]:
                    if person in pt_onboard:
                        pt_person_stuck_state["onboard"] += 1
                    elif pt_boardings_on_active_leg[person] > 0:
                        pt_person_stuck_state["waiting_after_boarding_on_leg"] += 1
                    else:
                        pt_person_stuck_state["waiting_before_boarding"] += 1
                    pt_active[person] -= 1
                    pt_boardings_on_active_leg.pop(person, None)
                    pt_onboard.discard(person)
                elif mode == "walk" and walk_active[person]:
                    walk_active[person] -= 1

            if event_type == "physical walk entered link":
                counts["walk_link_enter"] += 1
            elif event_type == "physical walk left link":
                counts["walk_link_leave"] += 1
            elif event_type in {"PersonEntersVehicle", "PersonEntersPtVehicle"}:
                if pt_active[person]:
                    pt_vehicle_entries += 1
                    pt_people_boarded.add(person)
                    pt_boardings_on_active_leg[person] += 1
                    pt_onboard.add(person)
                if vehicle.startswith(b"veh_school_bus_v6_"):
                    counts["school_bus_board"] += 1
            elif event_type in {"PersonLeavesVehicle", "PersonLeavesPtVehicle"}:
                if pt_active[person]:
                    pt_vehicle_leaves += 1
                    pt_people_alighted.add(person)
                    pt_onboard.discard(person)
                if vehicle.startswith(b"veh_school_bus_v6_"):
                    counts["school_bus_alight"] += 1
            elif event_type == "vehicle enters traffic":
                if mode == "car" and not person.startswith(b"pt_veh_"):
                    counts["car_vehicle_enters_traffic"] += 1
            elif event_type == "entered link":
                counts["physical_vehicle_link_enter"] += 1

    return {
        "departures_by_effective_mode": dict(departures),
        "arrivals_by_execution_mode": dict(arrivals),
        "teleportation_arrivals_by_mode": dict(teleported),
        "direct_main_mode_teleportation_arrivals": dict(teleported_main),
        "direct_main_mode_teleportation_samples": dict(teleported_main_samples),
        "stuck_by_mode": dict(stuck),
        "stuck_by_entity_class": dict(stuck_by_entity_class),
        "stuck_person_samples_by_mode": dict(stuck_person_samples),
        "pt_person_stuck_state": dict(pt_person_stuck_state),
        "person_stuck_time_hour": dict(sorted(person_stuck_time_hour.items(), key=lambda item: int(item[0]))),
        "walk_link_enter_events": counts["walk_link_enter"],
        "walk_link_leave_events": counts["walk_link_leave"],
        "regular_and_school_pt_board_events": pt_vehicle_entries,
        "regular_and_school_pt_alight_events": pt_vehicle_leaves,
        "pt_people_with_boarding": len(pt_people_boarded),
        "pt_people_with_alighting": len(pt_people_alighted),
        "school_bus_board_events": counts["school_bus_board"],
        "school_bus_alight_events": counts["school_bus_alight"],
        "car_vehicle_enters_traffic": counts["car_vehicle_enters_traffic"],
        "physical_vehicle_link_enter_events": counts["physical_vehicle_link_enter"],
        "unfinished_pt_legs": sum(pt_active.values()),
        "unfinished_walk_legs": sum(walk_active.values()),
    }


def audit_config(path: Path) -> dict[str, object]:
    root = ET.parse(path).getroot()
    strategy = next(
        module
        for module in root.findall("module")
        if module.get("name") in {"replanning", "strategy"}
    )
    weights: dict[str, float] = defaultdict(float)
    for block in strategy.findall("parameterset"):
        if block.get("type") != "strategysettings":
            continue
        values = {item.get("name"): item.get("value") for item in block.findall("param")}
        weights[values.get("strategyName", "missing")] += float(values.get("weight", "0"))
    return {
        "strategy_weights": dict(weights),
        "ordinary_innovation_frozen": all(
            weights.get(name, 0.0) == 0.0
            for name in ("ReRoute", "SubtourModeChoice", "TimeAllocationMutator")
        ) and weights.get("KeepLastSelected", 0.0) > 0.0,
    }


def main() -> int:
    args = parse_args()
    exit_code = int(args.exit_code.read_text(encoding="ascii").strip())
    events = audit_events(args.events)
    config = audit_config(args.config)
    dep = events["departures_by_effective_mode"]
    teleported = events["direct_main_mode_teleportation_arrivals"]
    checks = {
        "process_exit_zero": exit_code == 0,
        "ordinary_innovation_frozen": config["ordinary_innovation_frozen"],
        "car_is_physical": dep.get("car", 0) > 0 and events["car_vehicle_enters_traffic"] > 0,
        "pt_is_physical": dep.get("pt", 0) > 0 and events["pt_people_with_boarding"] > 0,
        "school_bus_is_physical": dep.get("school_bus", 0) > 0 and events["school_bus_board_events"] > 0,
        "walk_is_network_physical": dep.get("walk", 0) > 0 and events["walk_link_enter_events"] > 0,
        "pt_not_teleported": teleported.get("pt", 0) == 0 and teleported.get("school_bus", 0) == 0,
        "walk_not_teleported": teleported.get("walk", 0) == 0,
        "taxi_is_sole_teleported_main_mode": teleported.get("taxi", 0) > 0
        and all(teleported.get(mode, 0) == 0 for mode in MAIN_MODES - {"taxi"}),
    }
    passed = all(checks.values())
    result = {
        "status": "validated" if passed else "failed",
        "exit_code": exit_code,
        "checks": checks,
        "config": config,
        "events": events,
        "interpretation": (
            "All non-Taxi main modes passed the no-innovation physical execution gate; "
            "Taxi is the sole teleported main mode."
            if passed else
            "At least one physical execution or innovation-freeze gate failed."
        ),
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
