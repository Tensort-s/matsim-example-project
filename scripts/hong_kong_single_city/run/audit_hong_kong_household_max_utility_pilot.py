#!/usr/bin/env python3
"""Audit the deterministic existing bound-versus-unbound household pilot."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
from collections import defaultdict
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET


BASE_PATH = Path(__file__).with_name(
    "audit_hong_kong_school_escort_physical_pilot.py"
)
SPEC = importlib.util.spec_from_file_location("school_escort_physical_audit", BASE_PATH)
base = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = base
SPEC.loader.exec_module(base)

SELECTION = re.compile(
    r"HK_HOUSEHOLD_ESCORT_SELECTION "
    r"(?:candidate_group=\S+ household=\S+ )?passenger=(\S+) "
    r"(?:new_candidate=(?:true|false) candidate_legs=\d+ )?choice=(bound|unbound) "
    r"bound_minus_unbound_utility=([0-9.Ee+-]+) schedule_feasible=(true|false)"
)
SUMMARY = re.compile(
    r"Household escort maximum-utility selector: (?:households|candidate_bundles)=(\d+), "
    r"(?:candidates_per_household|alternatives_per_candidate)=(\d+), "
    r"selected_bound=(\d+), selected_unbound=(\d+), "
    r"active_bindings=(\d+), generated_waypoint_legs=(\d+), "
    r"infeasible_bound_households=(\d+), .*probability_choice=false, "
    r"driver_constraint=false, new_joint_pairs=\d+"
)
DYNAMIC = re.compile(
    r"HK_DYNAMIC_CAR_COST_AUDIT iteration=(\d+) linkEntries=(\d+) "
    r"tollEntries=(\d+) parkingEvents=(\d+) parkingFacilityMismatches=(\d+) "
    r"terminalParkingEvents=(\d+) energyHkd=([0-9.Ee+-]+) "
    r"tollHkd=([0-9.Ee+-]+) parkingHkd=([0-9.Ee+-]+)"
)
PHYSICAL = re.compile(
    r"Household school-escort physical pilot: departures=(\d+), "
    r"boardings=(\d+), alightings=(\d+), completed=(\d+), "
    r"passenger_stuck_onboard=(\d+), driver_stuck_before_pickup=(\d+), "
    r"skipped_after_prior_failure=(\d+), waiting=(\d+), onboard=(\d+), "
    r"classified=(\d+)"
)


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


def attribute(line: bytes, name: bytes) -> bytes:
    marker = name + b'="'
    start = line.find(marker)
    if start < 0:
        return b""
    start += len(marker)
    end = line.find(b'"', start)
    return line[start:end]


def audit_events(
    path: Path,
    rows: list[dict[str, str]],
    selections: dict[str, str],
) -> dict[str, object]:
    by_passenger: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_passenger[row["passenger_person_id"]].append(row)
    for values in by_passenger.values():
        values.sort(key=lambda row: int(row["passenger_leg_index"]))
    by_original_index = {
        person: {int(row["passenger_leg_index"]): row for row in rows}
        for person, rows in by_passenger.items()
    }
    passenger_ids = set(by_passenger)
    vehicle_ids = {row["vehicle_id"] for row in rows}
    next_leg = defaultdict(int)
    active_key: dict[str, str] = {}
    sequences: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
    vehicle_waypoint_events: set[tuple[str, str, float]] = set()

    with base.xml_stream(path) as handle:
        for line in handle:
            if b"<event " not in line:
                continue
            event_type = attribute(line, b"type").decode()
            time = float(attribute(line, b"time"))
            vehicle = attribute(line, b"vehicle").decode()
            link = attribute(line, b"link").decode()
            if vehicle in vehicle_ids and event_type in {
                "entered link", "vehicle enters traffic"
            }:
                vehicle_waypoint_events.add((vehicle, link, time))
            person = attribute(line, b"person").decode()
            if person not in passenger_ids:
                continue
            mode = (
                attribute(line, b"legMode") or attribute(line, b"mode")
            ).decode()
            if event_type == "departure" and mode == "car_passenger":
                ordinal = next_leg[person]
                next_leg[person] += 1
                if selections.get(person) != "bound":
                    continue
                row = by_original_index[person].get(ordinal)
                if row is None:
                    continue
                key = f"{person}/{row['passenger_leg_index']}"
                active_key[person] = key
                sequences[key].append(("departure", time, ""))
            elif event_type == "PersonEntersVehicle" and person in active_key:
                sequences[active_key[person]].append(("board", time, vehicle))
            elif event_type == "PersonLeavesVehicle" and person in active_key:
                sequences[active_key[person]].append(("alight", time, vehicle))
            elif event_type in {"TeleportationArrival", "teleportationArrival"} \
                    and person in active_key:
                sequences[active_key[person]].append(("teleport", time, ""))
            elif event_type == "arrival" and mode == "car_passenger" and person in active_key:
                sequences[active_key[person]].append(("arrival", time, ""))
                active_key.pop(person, None)
            elif "stuck" in event_type.lower() and person in active_key:
                sequences[active_key[person]].append(("stuck", time, ""))
                active_key.pop(person, None)

    exact_bound = 0
    bound_waypoint_failures: list[str] = []
    bound_teleports = 0
    unbound_vehicle_events = 0
    unbound_teleports = 0
    for row in rows:
        person = row["passenger_person_id"]
        key = f"{person}/{row['passenger_leg_index']}"
        sequence = sequences.get(key, [])
        names = [item[0] for item in sequence]
        if selections[person] == "bound":
            bound_teleports += names.count("teleport")
            if names == ["departure", "board", "alight", "arrival"]:
                board = sequence[1]
                alight = sequence[2]
                board_ok = (
                    row["vehicle_id"], row["passenger_pickup_link"], board[1]
                ) in vehicle_waypoint_events
                alight_ok = (
                    row["vehicle_id"], row["passenger_dropoff_link"], alight[1]
                ) in vehicle_waypoint_events
                if board[2] == row["vehicle_id"] and alight[2] == row["vehicle_id"] \
                        and board_ok and alight_ok:
                    exact_bound += 1
                else:
                    bound_waypoint_failures.append(key)
        else:
            unbound_vehicle_events += names.count("board") + names.count("alight")
            unbound_teleports += names.count("teleport")

    return {
        "bound_legs_completed_at_exact_waypoints": exact_bound,
        "bound_waypoint_failure_count": len(bound_waypoint_failures),
        "bound_waypoint_failure_examples": bound_waypoint_failures[:20],
        "bound_teleportation_arrivals": bound_teleports,
        "unbound_person_vehicle_events": unbound_vehicle_events,
        "unbound_teleportation_arrivals": unbound_teleports,
        "observed_passenger_legs": len(sequences),
    }


def car_passenger_time_only(config: Path) -> bool:
    root = ET.parse(config).getroot()
    scoring = next(item for item in root.findall("module") if item.get("name") == "scoring")
    for block in scoring.iter("parameterset"):
        values = {item.get("name"): item.get("value") for item in block.findall("param")}
        if values.get("mode") == "car_passenger":
            return (
                float(values.get("constant", "nan")) == -1.5
                and float(values.get("marginalUtilityOfTraveling_util_hr", "nan")) == -6.0
                and float(values.get("marginalUtilityOfDistance_util_m", "nan")) == 0.0
                and float(values.get("monetaryDistanceRate", "nan")) == 0.0
            )
    return False


def main() -> int:
    args = parse_args()
    with args.bindings.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    log_text = args.log.read_text(encoding="utf-8", errors="replace")
    selections = {
        match.group(1): match.group(2) for match in SELECTION.finditer(log_text)
    }
    summary_matches = list(SUMMARY.finditer(log_text))
    summary = None
    if len(summary_matches) == 1:
        values = [int(item) for item in summary_matches[0].groups()]
        summary = dict(zip(
            ("households", "candidates_per_household", "selected_bound",
             "selected_unbound", "active_bindings", "generated_waypoint_legs",
             "infeasible_bound_households"), values,
        ))
    events = audit_events(args.events, rows, selections)
    plans = base.audit_plans(args.plans)
    config = base.audit_config(args.config)
    dynamic = [match.groups() for match in DYNAMIC.finditer(log_text)]
    physical_matches = list(PHYSICAL.finditer(log_text))
    physical = None
    if len(physical_matches) == 1:
        physical = dict(zip(
            ("departures", "boardings", "alightings", "completed",
             "passenger_stuck_onboard", "driver_stuck_before_pickup",
             "skipped_after_prior_failure", "waiting", "onboard", "classified"),
            (int(value) for value in physical_matches[0].groups()),
        ))
    bound_people = sum(choice == "bound" for choice in selections.values())
    unbound_people = sum(choice == "unbound" for choice in selections.values())
    checks = {
        "process_exit_zero": int(args.exit_code.read_text(encoding="ascii").strip()) == 0,
        "exact_existing_candidate_population": len(rows) == 278 and len(selections) == 139,
        "exact_two_candidates_no_probability_or_driver_constraint": summary is not None
        and summary["households"] == 139
        and summary["candidates_per_household"] == 2,
        "bound_unbound_selection_conserved": summary is not None
        and bound_people == summary["selected_bound"]
        and unbound_people == summary["selected_unbound"]
        and bound_people + unbound_people == 139
        and summary["active_bindings"] == bound_people * 2,
        "all_waypoint_candidates_generated": summary is not None
        and summary["generated_waypoint_legs"] == 278,
        "completed_bound_legs_use_exact_waypoints": events[
            "bound_waypoint_failure_count"
        ] == 0
        and physical is not None
        and events["bound_legs_completed_at_exact_waypoints"] == physical["completed"],
        "all_active_bindings_classified": physical is not None
        and summary is not None
        and physical["classified"] == summary["active_bindings"]
        and physical["waiting"] == 0
        and physical["onboard"] == 0,
        "no_bound_teleportation": events["bound_teleportation_arrivals"] == 0,
        "no_unbound_vehicle_boarding": events["unbound_person_vehicle_events"] == 0,
        "passenger_score_is_base_plus_time_only": car_passenger_time_only(args.config),
        "ordinary_innovation_frozen": config["strategy_weights"].get("ReRoute") == [0.0]
        and config["strategy_weights"].get("SubtourModeChoice") == [0.0]
        and config["strategy_weights"].get("TimeAllocationMutator") == [0.0],
        "one_qsim_iteration": config["first_iteration"] == 0
        and config["last_iteration"] == 0,
        "dynamic_costs_live": len(dynamic) == 1
        and all(float(value) > 0 for value in dynamic[0][1:4])
        and all(float(value) > 0 for value in dynamic[0][6:9]),
        "output_modes_conserved": plans["selected_plan_mode_counts"]
        == base.EXPECTED_MODE_COUNTS,
        "all_scores_finite": plans["selected_scores_finite"],
    }
    report = {
        "status": "validated" if all(checks.values()) else "failed",
        "selector_summary": summary,
        "physical_summary": physical,
        "selection_counts": {"bound": bound_people, "unbound": unbound_people},
        "events": events,
        "plans": plans,
        "config": config,
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "all_checks_passed": all(checks.values()),
        "inputs": {name: str(getattr(args, name)) for name in (
            "bindings", "events", "plans", "config", "log", "exit_code",
        )},
    }
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["all_checks_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
