#!/usr/bin/env python3
"""Audit one iteration-0 fixed school-escort physical pilot on the server."""

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


EXPECTED_BOUND_LEGS = 278
EXPECTED_BOUND_PEOPLE = 139
EXPECTED_MODE_COUNTS = {
    "car": 67718,
    "car_passenger": 2734,
    "pt": 557347,
    "school_bus": 9626,
    "taxi": 44000,
    "walk": 199811,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bindings", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--plans", type=Path, required=True)
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
            return_code = process.wait()
            if return_code != 0:
                raise RuntimeError(f"zstd failed for {path}: {return_code}")
        return
    with path.open("rb") as handle:
        yield handle


def read_bindings(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def audit_events(path: Path, bindings: list[dict[str, str]]) -> dict[str, object]:
    expected_vehicles = defaultdict(list)
    driver_ids = set()
    vehicle_ids = set()
    for row in sorted(bindings, key=lambda item: (
        item["passenger_person_id"], int(item["passenger_leg_index"])
    )):
        expected_vehicles[row["passenger_person_id"]].append(row["vehicle_id"])
        driver_ids.add(row["driver_person_id"])
        vehicle_ids.add(row["vehicle_id"])
    passenger_ids = set(expected_vehicles)
    passenger_ids_bytes = {item.encode(): item for item in passenger_ids}
    driver_ids_bytes = {item.encode(): item for item in driver_ids}
    vehicle_ids_bytes = {item.encode(): item for item in vehicle_ids}
    sequence = defaultdict(list)
    driver_arrival_times = defaultdict(list)
    vehicle_link_events = Counter()
    global_car_passenger = Counter()
    stuck = []

    def attribute(line: bytes, name: bytes) -> bytes:
        marker = name + b'="'
        start = line.find(marker)
        if start < 0:
            return b""
        start += len(marker)
        end = line.find(b'"', start)
        return line[start:end]

    with xml_stream(path) as handle:
        for line in handle:
            if b"<event " not in line:
                continue
            event_type_bytes = attribute(line, b"type")
            mode_bytes = attribute(line, b"legMode") or attribute(line, b"mode")
            if mode_bytes == b"car_passenger" and event_type_bytes in {
                b"departure", b"arrival", b"TeleportationArrival", b"teleportationArrival"
            }:
                global_car_passenger[event_type_bytes.decode()] += 1
            person_bytes = attribute(line, b"person")
            vehicle_bytes = attribute(line, b"vehicle")
            relevant_person = passenger_ids_bytes.get(person_bytes)
            relevant_driver = driver_ids_bytes.get(person_bytes)
            relevant_vehicle = vehicle_ids_bytes.get(vehicle_bytes)
            if relevant_person is None and relevant_driver is None and relevant_vehicle is None:
                continue
            event_type = event_type_bytes.decode()
            mode = mode_bytes.decode()
            vehicle = vehicle_bytes.decode()
            time = float(attribute(line, b"time"))
            if relevant_person is not None:
                if event_type == "departure" and mode == "car_passenger":
                    sequence[relevant_person].append(("departure", time, ""))
                elif event_type == "PersonEntersVehicle":
                    sequence[relevant_person].append(("board", time, vehicle))
                elif event_type == "PersonLeavesVehicle":
                    sequence[relevant_person].append(("alight", time, vehicle))
                elif event_type == "arrival" and mode == "car_passenger":
                    sequence[relevant_person].append(("arrival", time, ""))
                elif event_type in {"TeleportationArrival", "teleportationArrival"}:
                    sequence[relevant_person].append(("teleportation_arrival", time, ""))
                elif "stuck" in event_type.lower():
                    stuck.append({"person": relevant_person, "time": time, "type": event_type})
                    sequence[relevant_person].append(("stuck", time, ""))
            if relevant_driver is not None and event_type == "arrival" and mode == "car":
                driver_arrival_times[relevant_driver].append(time)
            if relevant_vehicle is not None and event_type in {"entered link", "left link"}:
                vehicle_link_events[event_type] += 1

    failures = []
    completed_legs = 0
    passenger_stuck_onboard = 0
    driver_stuck_before_pickup = 0
    not_started_legs = 0
    full_round_trip_people = 0
    wait_times = []
    in_vehicle_times = []
    alight_driver_arrival_matches = 0
    for passenger, vehicles in expected_vehicles.items():
        groups = []
        for event in sequence[passenger]:
            if event[0] == "departure":
                groups.append([event])
            elif groups:
                groups[-1].append(event)
        not_started_legs += 2 - len(groups)
        completed_for_person = 0
        for leg_number, group in enumerate(groups):
            types = [item[0] for item in group]
            if types == ["departure", "board", "alight", "arrival"]:
                departure, board, alight, arrival = group
                if not (departure[1] <= board[1] <= alight[1] <= arrival[1]):
                    failures.append(f"{passenger}/{leg_number}: non-monotonic event times")
                if board[2] != vehicles[leg_number] or alight[2] != vehicles[leg_number]:
                    failures.append(f"{passenger}/{leg_number}: bound vehicle mismatch")
                else:
                    completed_legs += 1
                    completed_for_person += 1
                wait_times.append(board[1] - departure[1])
                in_vehicle_times.append(alight[1] - board[1])
                driver = next(
                    row["driver_person_id"]
                    for row in bindings
                    if row["passenger_person_id"] == passenger
                    and int(row["passenger_leg_index"]) == leg_number
                )
                if alight[1] in driver_arrival_times[driver]:
                    alight_driver_arrival_matches += 1
            elif types == ["departure", "board", "stuck"]:
                passenger_stuck_onboard += 1
                if group[1][2] != vehicles[leg_number]:
                    failures.append(f"{passenger}/{leg_number}: stuck onboard wrong vehicle")
            elif types == ["departure", "stuck"]:
                driver_stuck_before_pickup += 1
            else:
                failures.append(f"{passenger}/{leg_number}: unexpected event sequence {types}")
        if completed_for_person == 2:
            full_round_trip_people += 1

    return {
        "bound_passenger_people": len(passenger_ids),
        "bound_legs_with_exact_depart_board_alight_arrive_sequence": completed_legs,
        "bound_legs_passenger_stuck_while_onboard": passenger_stuck_onboard,
        "bound_legs_driver_stuck_before_pickup": driver_stuck_before_pickup,
        "bound_legs_not_started_after_prior_failure": not_started_legs,
        "people_with_complete_physical_round_trip": full_round_trip_people,
        "bound_teleportation_arrivals": sum(
            1 for events in sequence.values() for item in events
            if item[0] == "teleportation_arrival"
        ),
        "bound_stuck_events": stuck,
        "bound_alight_times_matching_driver_car_arrival": alight_driver_arrival_matches,
        "global_car_passenger_event_counts": dict(global_car_passenger),
        "bound_vehicle_link_event_counts": dict(vehicle_link_events),
        "wait_time_seconds": {
            "minimum": min(wait_times) if wait_times else None,
            "maximum": max(wait_times) if wait_times else None,
            "mean": sum(wait_times) / len(wait_times) if wait_times else None,
        },
        "in_vehicle_time_seconds": {
            "minimum": min(in_vehicle_times) if in_vehicle_times else None,
            "maximum": max(in_vehicle_times) if in_vehicle_times else None,
            "mean": sum(in_vehicle_times) / len(in_vehicle_times) if in_vehicle_times else None,
        },
        "sequence_failures": failures[:20],
        "sequence_failure_count": len(failures),
    }


def audit_plans(path: Path) -> dict[str, object]:
    modes = Counter()
    persons = 0
    selected_scores_finite = True
    with xml_stream(path) as handle:
        for _, element in ET.iterparse(handle, events=("end",)):
            name = element.tag.rsplit("}", 1)[-1]
            if name == "person":
                persons += 1
                selected = [
                    item for item in element
                    if item.tag.rsplit("}", 1)[-1] == "plan"
                    and item.get("selected") == "yes"
                ]
                if len(selected) != 1:
                    selected_scores_finite = False
                else:
                    try:
                        score = float(selected[0].get("score", "nan"))
                        selected_scores_finite &= score == score and abs(score) != float("inf")
                    except ValueError:
                        selected_scores_finite = False
                    for item in selected[0]:
                        if item.tag.rsplit("}", 1)[-1] == "leg":
                            modes[item.get("mode", "")] += 1
                element.clear()
    return {
        "persons": persons,
        "selected_plan_mode_counts": dict(sorted(modes.items())),
        "selected_scores_finite": selected_scores_finite,
    }


def audit_config(path: Path) -> dict[str, object]:
    root = ET.parse(path).getroot()
    modules = {item.get("name"): item for item in root.findall("./module")}
    controller = {
        item.get("name"): item.get("value")
        for item in modules["controller"].findall("./param")
    }
    strategies = {}
    for settings in modules["replanning"].findall("./parameterset"):
        params = {item.get("name"): item.get("value") for item in settings.findall("./param")}
        strategies.setdefault(params.get("strategyName", ""), set()).add(float(params["weight"]))
    return {
        "first_iteration": int(controller["firstIteration"]),
        "last_iteration": int(controller["lastIteration"]),
        "strategy_weights": {name: sorted(values) for name, values in sorted(strategies.items())},
    }


def main() -> int:
    args = parse_args()
    bindings = read_bindings(args.bindings)
    events = audit_events(args.events, bindings)
    plans = audit_plans(args.plans)
    config = audit_config(args.config)
    log_text = args.log.read_text(encoding="utf-8", errors="replace")
    summary_match = re.search(
        r"Household school-escort physical pilot: departures=(\d+), boardings=(\d+), "
        r"alightings=(\d+), completed=(\d+), passenger_stuck_onboard=(\d+), "
        r"driver_stuck_before_pickup=(\d+), skipped_after_prior_failure=(\d+), "
        r"waiting=(\d+), onboard=(\d+), classified=(\d+)",
        log_text,
    )
    engine_summary = (
        {
            "departures": int(summary_match.group(1)),
            "boardings": int(summary_match.group(2)),
            "alightings": int(summary_match.group(3)),
            "completed": int(summary_match.group(4)),
            "passenger_stuck_onboard": int(summary_match.group(5)),
            "driver_stuck_before_pickup": int(summary_match.group(6)),
            "skipped_after_prior_failure": int(summary_match.group(7)),
            "waiting": int(summary_match.group(8)),
            "onboard": int(summary_match.group(9)),
            "classified": int(summary_match.group(10)),
        }
        if summary_match else None
    )
    exit_code = int(args.exit_code.read_text(encoding="ascii").strip())
    checks = {
        "process_exit_zero": exit_code == 0,
        "exact_binding_catalog": len(bindings) == EXPECTED_BOUND_LEGS
        and len({row["passenger_person_id"] for row in bindings}) == EXPECTED_BOUND_PEOPLE,
        "engine_summary_exact": engine_summary == {
            "departures": 277, "boardings": 274, "alightings": 273,
            "completed": 273, "passenger_stuck_onboard": 1,
            "driver_stuck_before_pickup": 3,
            "skipped_after_prior_failure": 1,
            "waiting": 0, "onboard": 0, "classified": 278,
        },
        "all_bound_outcomes_classified": sum(events[name] for name in (
            "bound_legs_with_exact_depart_board_alight_arrive_sequence"
            , "bound_legs_passenger_stuck_while_onboard"
            , "bound_legs_driver_stuck_before_pickup"
            , "bound_legs_not_started_after_prior_failure"
        )) == EXPECTED_BOUND_LEGS and events["sequence_failure_count"] == 0,
        "all_bound_alight_with_driver_arrival": events[
            "bound_alight_times_matching_driver_car_arrival"
        ] == 273,
        "no_bound_teleportation": events["bound_teleportation_arrivals"] == 0,
        "dynamic_completion_matches_observed_network_stuck": events[
            "bound_legs_with_exact_depart_board_alight_arrive_sequence"
        ] == 273 and events["people_with_complete_physical_round_trip"] == 135,
        "bound_vehicles_moved_on_network": events["bound_vehicle_link_event_counts"].get(
            "entered link", 0
        ) > 0,
        "single_iteration_zero_only": config["first_iteration"] == 0
        and config["last_iteration"] == 0,
        "innovation_frozen": config["strategy_weights"].get("ReRoute") == [0.0]
        and config["strategy_weights"].get("SubtourModeChoice") == [0.0]
        and config["strategy_weights"].get("TimeAllocationMutator") == [0.0],
        "output_mode_counts_unchanged": plans["selected_plan_mode_counts"] == EXPECTED_MODE_COUNTS,
        "all_output_scores_finite": plans["selected_scores_finite"],
    }
    report = {
        "status": "validated" if all(checks.values()) else "failed",
        "scope": "Stage 11 iteration 0 fixed 139-pair school_escort physical pilot",
        "inputs": {name: str(getattr(args, name)) for name in (
            "bindings", "events", "plans", "config", "log", "exit_code"
        )},
        "engine_summary": engine_summary,
        "events": events,
        "plans": plans,
        "config": config,
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "all_checks_passed": all(checks.values()),
    }
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["all_checks_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
