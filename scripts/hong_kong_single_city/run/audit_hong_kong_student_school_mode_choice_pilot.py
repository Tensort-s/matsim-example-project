#!/usr/bin/env python3
"""Audit the Stage 11 physical school-bus maximum-utility pilot."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import contextlib
import csv
import gzip
import json
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET


STUDENT_DECISION = re.compile(
    r"HK_STUDENT_SCHOOL_MODE_SELECTION person=(\S+) trip=(\d+) direction=(\S+) "
    r"stage=(\S+) original_mode_audit=(\S+) .*? selected_mode=(\S+) "
    r"selected_source=(\S+) selected_utility=([0-9.Ee+-]+)"
)
JOINT_DECISION = re.compile(
    r"HK_HOUSEHOLD_JOINT_SELECTION candidate=(\S+) household=(\S+) "
    r"passenger=(\S+) passenger_trip=(\d+) driver=(\S+) driver_trip=(\d+) "
    r"choice=(joint|fallback)"
)
SPLITTER_COUNTS = re.compile(
    r"School-bus departure splitter: physical=([0-9,]+); teleported-pt=([0-9,]+)\."
)
SCHOOL_BUS_MODE = "school_bus"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--student-universe", type=Path, required=True)
    parser.add_argument("--school-bus-candidates", type=Path, required=True)
    parser.add_argument("--household-candidates", type=Path, required=True)
    parser.add_argument("--plans", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
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


def local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def attributes(element: ET.Element) -> dict[str, str]:
    result: dict[str, str] = {}
    for child in element:
        if local_name(child) != "attributes":
            continue
        for item in child:
            if local_name(item) == "attribute" and item.get("name"):
                result[item.get("name", "")] = (item.text or "").strip()
    return result


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def stage_activity(element: ET.Element) -> bool:
    return (element.get("type") or "").endswith(" interaction")


def trip_mode(legs: list[ET.Element]) -> str:
    modes = {
        attributes(leg).get("routingMode", leg.get("mode", ""))
        for leg in legs
    }
    for mode in ("car_passenger", "car", "taxi", "school_bus", "pt", "walk"):
        if mode in modes:
            return mode
    return sorted(modes)[0] if modes else "missing"


def audit_student_plans(
    path: Path, expected_keys: set[tuple[str, int]]
) -> tuple[dict[tuple[str, int], dict[str, object]], Counter[str]]:
    persons = {person for person, _ in expected_keys}
    result: dict[tuple[str, int], dict[str, object]] = {}
    all_selected_leg_modes: Counter[str] = Counter()
    with xml_stream(path) as handle:
        for _, person in ET.iterparse(handle, events=("end",)):
            if local_name(person) != "person":
                continue
            person_id = person.get("id", "")
            plans = [child for child in person if local_name(child) == "plan"]
            selected = [plan for plan in plans if plan.get("selected") == "yes"]
            if len(selected) != 1:
                person.clear()
                continue
            for leg in selected[0]:
                if local_name(leg) == "leg":
                    all_selected_leg_modes[
                        attributes(leg).get("routingMode", leg.get("mode", ""))
                    ] += 1
            if person_id not in persons:
                person.clear()
                continue
            trip_index = 0
            legs: list[ET.Element] = []
            for element in selected[0]:
                kind = local_name(element)
                if kind == "leg":
                    legs.append(element)
                elif kind == "activity" and not stage_activity(element) and legs:
                    key = (person_id, trip_index)
                    if key in expected_keys:
                        mode = trip_mode(legs)
                        school_bus_legs = [
                            leg for leg in legs
                            if leg.get("mode") == "pt"
                            and attributes(leg).get("routingMode") == SCHOOL_BUS_MODE
                        ]
                        candidate_ids = [
                            attributes(leg).get("hkSchoolBusCandidateId", "")
                            for leg in school_bus_legs
                        ]
                        routes = [
                            route
                            for leg in school_bus_legs
                            for route in leg
                            if local_name(route) == "route"
                        ]
                        result[key] = {
                            "mode": mode,
                            "school_bus_candidate_ids": candidate_ids,
                            "school_bus_route_types": [
                                route.get("type", "") for route in routes
                            ],
                        }
                    trip_index += 1
                    legs = []
            person.clear()
    return result, all_selected_leg_modes


def byte_attribute(line: bytes, name: bytes) -> bytes:
    marker = name + b'="'
    start = line.find(marker)
    if start < 0:
        return b""
    start += len(marker)
    return line[start:line.find(b'"', start)]


def audit_events(
    path: Path,
    selected_school_bus: dict[tuple[str, int], str],
    options: dict[str, dict[str, str]],
) -> dict[str, object]:
    people = {person.encode(): person for person, _ in selected_school_bus}
    allowed_vehicles = defaultdict(set)
    source_capacities: dict[str, int] = {}
    for (person, _), candidate_id in selected_school_bus.items():
        row = options[candidate_id]
        allowed_vehicles[person].add(row["vehicle_id"])
        source_capacities[row["vehicle_id"]] = int(row["vehicle_capacity"])
    counts: Counter[str] = Counter()
    by_person: dict[str, Counter[str]] = defaultdict(Counter)
    wrong_vehicle_boardings = []
    non_school_bus_boardings = []
    onboard: Counter[str] = Counter()
    peak: Counter[str] = Counter()
    stuck_people = set()
    active_school_bus = Counter()
    physical_link_events: Counter[str] = Counter()
    selected_vehicle_ids = set(source_capacities)
    with xml_stream(path) as handle:
        for line in handle:
            if b"<event " not in line:
                continue
            event_type = byte_attribute(line, b"type").decode()
            person_bytes = byte_attribute(line, b"person")
            vehicle = byte_attribute(line, b"vehicle").decode()
            person = people.get(person_bytes)
            mode = (
                byte_attribute(line, b"legMode")
                or byte_attribute(line, b"mode")
            ).decode()
            routing_mode = byte_attribute(line, b"computationalRoutingMode").decode()
            if vehicle in selected_vehicle_ids and event_type in {"entered link", "left link"}:
                physical_link_events[event_type] += 1
            if person is None:
                continue
            if (event_type == "departure" and mode == "pt"
                    and routing_mode == SCHOOL_BUS_MODE):
                counts["departure"] += 1
                by_person[person]["departure"] += 1
                active_school_bus[person] += 1
            elif event_type == "arrival" and mode == SCHOOL_BUS_MODE:
                counts["arrival"] += 1
                by_person[person]["arrival"] += 1
            elif event_type in {"PersonEntersVehicle", "PersonEntersPtVehicle"} \
                    and vehicle.startswith("veh_school_bus_v6_"):
                counts["board"] += 1
                by_person[person]["board"] += 1
                if vehicle not in allowed_vehicles[person]:
                    wrong_vehicle_boardings.append({"person": person, "vehicle": vehicle})
                onboard[vehicle] += 1
                peak[vehicle] = max(peak[vehicle], onboard[vehicle])
            elif event_type in {"PersonEntersVehicle", "PersonEntersPtVehicle"} \
                    and active_school_bus[person] > 0:
                non_school_bus_boardings.append({"person": person, "vehicle": vehicle})
            elif event_type in {"PersonLeavesVehicle", "PersonLeavesPtVehicle"} \
                    and vehicle.startswith("veh_school_bus_v6_"):
                counts["alight"] += 1
                by_person[person]["alight"] += 1
                onboard[vehicle] -= 1
            elif event_type == "arrival" and mode == "pt" and active_school_bus[person] > 0:
                counts["arrival"] += 1
                by_person[person]["arrival"] += 1
                active_school_bus[person] -= 1
            elif "stuck" in event_type.lower() and active_school_bus[person] > 0:
                stuck_people.add(person)
                active_school_bus[person] -= 1
    exceeded = {
        vehicle: load
        for vehicle, load in peak.items()
        if load > source_capacities.get(vehicle, 0)
    }
    expected_by_person = Counter(person for person, _ in selected_school_bus)
    deficits = {
        event: {
            person: expected - by_person[person][event]
            for person, expected in expected_by_person.items()
            if by_person[person][event] != expected
        }
        for event in ("departure", "board", "alight", "arrival")
    }
    return {
        "event_counts": dict(counts),
        "event_count_deficits_by_person": deficits,
        "wrong_vehicle_boardings": wrong_vehicle_boardings,
        "non_school_bus_boardings": non_school_bus_boardings,
        "selected_student_stuck_people": sorted(stuck_people),
        "vehicles_with_nonzero_terminal_load": {
            vehicle: load for vehicle, load in onboard.items() if load
        },
        "school_bus_vehicle_link_events": dict(physical_link_events),
        "peak_selected_student_load": max(peak.values(), default=0),
        "vehicles_exceeding_source_capacity": exceeded,
    }


def audit_config(path: Path) -> dict[str, object]:
    root = ET.parse(path).getroot()
    modules = {module.get("name"): module for module in root.findall("./module")}
    transit_modes = next(
        item.get("value") for item in modules["transit"].findall("./param")
        if item.get("name") == "transitModes"
    )
    teleported = []
    for block in modules["routing"].findall("./parameterset"):
        if block.get("type") != "teleportedModeParameters":
            continue
        teleported.extend(
            item.get("value") for item in block.findall("./param")
            if item.get("name") == "mode"
        )
    scoring = {}
    for block in modules["scoring"].findall("./parameterset"):
        params = {item.get("name"): item.get("value") for item in block.findall("./param")}
        if params.get("mode") == SCHOOL_BUS_MODE:
            scoring = params
    strategies = defaultdict(list)
    for block in modules["replanning"].findall("./parameterset"):
        params = {item.get("name"): item.get("value") for item in block.findall("./param")}
        strategies[params["strategyName"]].append(float(params["weight"]))
    return {
        "transit_modes": transit_modes.split(","),
        "teleported_modes": teleported,
        "school_bus_scoring": scoring,
        "strategy_weights": dict(strategies),
    }


def main() -> int:
    args = parse_args()
    universe = read_csv(args.student_universe)
    option_rows = read_csv(args.school_bus_candidates)
    household_rows = {
        row["candidate_id"]: row for row in read_csv(args.household_candidates)
    }
    options = {row["candidate_id"]: row for row in option_rows}
    expected_keys = {(row["person_id"], int(row["trip_index"])) for row in universe}
    log = args.log.read_text(encoding="utf-8", errors="replace")
    decisions = {}
    for match in STUDENT_DECISION.finditer(log):
        key = (match.group(1), int(match.group(2)))
        decisions[key] = {
            "direction": match.group(3),
            "stage": match.group(4),
            "original_mode": match.group(5),
            "independent_mode": match.group(6),
            "source": match.group(7),
            "utility": float(match.group(8)),
        }
    selected_joint_keys = set()
    for match in JOINT_DECISION.finditer(log):
        if match.group(7) != "joint":
            continue
        row = household_rows[match.group(1)]
        selected_joint_keys.add((
            row["passenger_person_id"], int(row["passenger_trip_index"])
        ))
    expected_final_modes = {
        key: ("car_passenger" if key in selected_joint_keys else value["independent_mode"])
        for key, value in decisions.items()
    }
    selected_school_bus = {
        key: value["source"] for key, value in decisions.items()
        if expected_final_modes.get(key) == SCHOOL_BUS_MODE
    }
    plans, all_modes = audit_student_plans(args.plans, expected_keys)
    event_audit = audit_events(args.events, selected_school_bus, options)
    config = audit_config(args.config)
    plan_mode_mismatches = {
        f"{person}/{trip}": {
            "expected": expected_final_modes.get((person, trip)),
            "observed": record["mode"],
        }
        for (person, trip), record in plans.items()
        if record["mode"] != expected_final_modes.get((person, trip))
    }
    bad_school_bus_routes = {
        f"{person}/{trip}": record
        for (person, trip), record in plans.items()
        if record["mode"] == SCHOOL_BUS_MODE and (
            record["school_bus_candidate_ids"] != [
                selected_school_bus.get((person, trip))
            ]
            or len(record["school_bus_route_types"]) != 1
            or record["school_bus_route_types"][0] in {"", "generic"}
        )
    }
    independent_counts = Counter(
        value["independent_mode"] for value in decisions.values()
    )
    final_counts = Counter(expected_final_modes.values())
    original_counts = Counter(value["original_mode"] for value in decisions.values())
    event_counts = event_audit["event_counts"]
    expected_school_bus_legs = len(selected_school_bus)
    physical_all_pt = "Enabled physical regular-PT and guarded school-bus passenger handling." in log
    splitter_counts = [
        {
            "physical": int(match.group(1).replace(",", "")),
            "teleported_pt": int(match.group(2).replace(",", "")),
        }
        for match in SPLITTER_COUNTS.finditer(log)
    ]
    checks = {
        "process_exit_zero": int(args.exit_code.read_text(encoding="ascii").strip()) == 0,
        "all_student_trips_decided_once": set(decisions) == expected_keys,
        "every_selected_school_bus_is_catalogued": all(
            source in options for source in selected_school_bus.values()
        ),
        "all_student_trips_present_in_selected_plans": set(plans) == expected_keys,
        "selected_plan_modes_match_selector": not plan_mode_mismatches,
        "all_selected_school_bus_routes_are_physical": not bad_school_bus_routes,
        "physical_school_bus_boarding_counts_complete": all(
            event_counts.get(name, 0) == expected_school_bus_legs
            for name in ("departure", "board")
        ),
        "no_wrong_school_bus_vehicle": not event_audit["wrong_vehicle_boardings"],
        "no_regular_pt_substitution": not event_audit["non_school_bus_boardings"],
        "physical_school_bus_vehicles_moved": event_audit["school_bus_vehicle_link_events"].get(
            "entered link", 0
        ) > 0,
        "school_bus_capacity_not_configured_as_constraint": (
            "school_bus" in config["transit_modes"]
            and "school_bus" not in config["teleported_modes"]
        ),
        "runtime_unlimited_school_bus_capacity_logged": (
            "school-bus seat constraints are disabled by runtime capacity override"
            in log
        ),
        "no_generic_pt_removed_by_physical_transit_handler": (
            "pt-leg has no TransitRoute" not in log
            and "pt-agent doesn't know to what transit stop to go" not in log
        ),
        "legacy_transit_modes_normalized_before_agent_creation": (
            "Pre-QSim normalized" in log
        ),
        "iteration_1_departure_splitter_counts_complete": (
            physical_all_pt
            or (
                bool(splitter_counts)
                and splitter_counts[-1]["physical"] == expected_school_bus_legs
                and splitter_counts[-1]["teleported_pt"] > 0
            )
        ),
        "school_bus_has_zero_monetary_distance_rate": float(
            config["school_bus_scoring"].get("monetaryDistanceRate", "nan")
        ) == 0.0,
        "ordinary_innovation_frozen": (
            config["strategy_weights"].get("KeepLastSelected") == [1.0] * 3
            and config["strategy_weights"].get("ReRoute") == [0.0] * 3
            and config["strategy_weights"].get("SubtourModeChoice") == [0.0] * 3
            and config["strategy_weights"].get("TimeAllocationMutator") == [0.0] * 3
        ),
    }
    completion_advisories = {
        "physical_school_bus_trip_completion_counts_complete": all(
            event_counts.get(name, 0) == expected_school_bus_legs
            for name in ("alight", "arrival")
        ),
        "no_selected_school_bus_student_stuck": not event_audit[
            "selected_student_stuck_people"
        ],
        "no_terminal_school_bus_load": not event_audit[
            "vehicles_with_nonzero_terminal_load"
        ],
    }
    accepted = all(checks.values())
    completed = all(completion_advisories.values())
    if accepted and completed:
        status = "validated"
    elif accepted:
        status = "validated_with_network_stuck_limitations"
    else:
        status = "failed"
    report = {
        "status": status,
        "student_school_trip_count": len(expected_keys),
        "physical_school_bus_option_count": len(option_rows),
        "selected_joint_student_trip_count": len(selected_joint_keys & expected_keys),
        "original_student_modes": dict(sorted(original_counts.items())),
        "independent_max_utility_modes": dict(sorted(independent_counts.items())),
        "final_student_modes_after_household_joint_override": dict(sorted(final_counts.items())),
        "selected_school_bus_legs": expected_school_bus_legs,
        "selected_school_bus_by_original_mode": dict(sorted(Counter(
            decisions[key]["original_mode"] for key in selected_school_bus
        ).items())),
        "all_selected_leg_modes": dict(sorted(all_modes.items())),
        "plan_mode_mismatch_count": len(plan_mode_mismatches),
        "plan_mode_mismatch_samples": dict(list(plan_mode_mismatches.items())[:20]),
        "bad_school_bus_route_count": len(bad_school_bus_routes),
        "bad_school_bus_route_samples": dict(list(bad_school_bus_routes.items())[:20]),
        "events": event_audit,
        "config": config,
        "departure_splitter_counts_by_iteration": splitter_counts,
        "ordinary_pt_execution": "physical" if physical_all_pt else "teleported",
        "checks": checks,
        "completion_advisories": completion_advisories,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "failed_completion_advisories": [
            name for name, passed in completion_advisories.items() if not passed
        ],
        "all_checks_passed": accepted,
        "all_physical_trips_completed": completed,
    }
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["all_checks_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
