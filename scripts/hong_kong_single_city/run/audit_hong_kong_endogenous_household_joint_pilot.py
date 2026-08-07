#!/usr/bin/env python3
"""Audit the bounded endogenous household joint-candidate iteration-0 pilot."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import importlib.util
import json
from pathlib import Path
import re
import sys


HERE = Path(__file__).parent


def load_helper(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


maximum = load_helper(
    "endogenous_maximum_audit", "audit_hong_kong_household_max_utility_pilot.py"
)
real = load_helper(
    "endogenous_real_mode_audit", "audit_hong_kong_household_real_mode_pilot.py"
)
base = maximum.base

EXPECTED_BINDINGS = 384
EXPECTED_BUNDLES = 384
EXPECTED_HOUSEHOLDS = 240
EXPECTED_NEW_BINDINGS = 106
EXPECTED_NEW_BUNDLES = 106

SUMMARY = re.compile(
    r"Household escort maximum-utility selector: (?:households|candidate_bundles)=(\d+), "
    r"(?:candidates_per_household|alternatives_per_candidate)=(\d+), "
    r"selected_bound=(\d+), selected_unbound=(\d+), "
    r"active_bindings=(\d+), generated_waypoint_legs=(\d+), "
    r"infeasible_bound_households=(\d+), selected_unbound_pt_legs=(\d+), "
    r"selected_unbound_taxi_legs=(\d+), selected_unbound_car_passenger_legs=(\d+), "
    r"unavailable_physical_pt_candidates=(\d+), candidate_households=(\d+), "
    r"candidate_legs=(\d+), new_candidate_bundles=(\d+), "
    r"selected_new_bound_bundles=(\d+), selected_new_unbound_bundles=(\d+), "
    r"selected_bound_legs=(\d+), selected_unbound_legs=(\d+), "
    r"resource_conflict_unbound_bundles=(\d+), .*probability_choice=false, "
    r"driver_constraint=false, new_joint_pairs=(\d+)"
)
SELECTION = re.compile(
    r"HK_HOUSEHOLD_ESCORT_SELECTION candidate_group=(\S+) household=(\S+) "
    r"passenger=(\S+) new_candidate=(true|false) candidate_legs=(\d+) "
    r"choice=(bound|unbound) bound_minus_unbound_utility=([0-9.Ee+-]+) "
    r"schedule_feasible=(true|false)"
)
REAL_CANDIDATE = re.compile(
    r"HK_HOUSEHOLD_ESCORT_REAL_MODE_CANDIDATE candidate_group=(\S+) "
    r"household=(\S+) new_candidate=(true|false) passenger=(\S+) "
    r"passenger_leg=(\d+) pt_available=(true|false).*selected_mode=(pt|taxi)"
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


def audit_bound_events(
    path: Path,
    bindings: list[dict[str, str]],
    selection_by_group: dict[str, str],
) -> dict[str, object]:
    active_rows = [
        row for row in bindings
        if selection_by_group.get(row["candidate_group_id"]) == "bound"
    ]
    by_passenger: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in active_rows:
        by_passenger[row["passenger_person_id"]].append(row)
    for rows in by_passenger.values():
        rows.sort(key=lambda row: float(row["passenger_planned_departure_time_s"]))
    unmatched = {person: list(rows) for person, rows in by_passenger.items()}
    passenger_ids = set(by_passenger)
    vehicle_ids = {row["vehicle_id"] for row in active_rows}
    active_key: dict[str, str] = {}
    sequences: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
    vehicle_waypoint_events: set[tuple[str, str, float]] = set()

    with base.xml_stream(path) as handle:
        for line in handle:
            if b"<event " not in line:
                continue
            event_type = maximum.attribute(line, b"type").decode()
            time = float(maximum.attribute(line, b"time"))
            vehicle = maximum.attribute(line, b"vehicle").decode()
            link = maximum.attribute(line, b"link").decode()
            if vehicle in vehicle_ids and event_type in {
                "entered link", "vehicle enters traffic"
            }:
                vehicle_waypoint_events.add((vehicle, link, time))
            person = maximum.attribute(line, b"person").decode()
            if person not in passenger_ids:
                continue
            mode = (
                maximum.attribute(line, b"legMode")
                or maximum.attribute(line, b"mode")
            ).decode()
            if event_type == "departure" and mode == "car_passenger":
                candidates = unmatched[person]
                if not candidates:
                    continue
                row = min(
                    candidates,
                    key=lambda item: abs(
                        time - float(item["passenger_planned_departure_time_s"])
                    ),
                )
                if abs(time - float(row["passenger_planned_departure_time_s"])) > 3600:
                    continue
                candidates.remove(row)
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
            elif event_type == "arrival" and mode == "car_passenger" \
                    and person in active_key:
                sequences[active_key[person]].append(("arrival", time, ""))
                active_key.pop(person, None)
            elif "stuck" in event_type.lower() and person in active_key:
                sequences[active_key[person]].append(("stuck", time, ""))
                active_key.pop(person, None)

    exact_bound = 0
    failures: list[str] = []
    teleports = 0
    for row in active_rows:
        key = f"{row['passenger_person_id']}/{row['passenger_leg_index']}"
        sequence = sequences.get(key, [])
        names = [item[0] for item in sequence]
        teleports += names.count("teleport")
        if names == ["departure", "board", "alight", "arrival"]:
            board, alight = sequence[1], sequence[2]
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
                failures.append(key)
    return {
        "active_bound_candidate_legs": len(active_rows),
        "bound_legs_completed_at_exact_waypoints": exact_bound,
        "bound_waypoint_failure_count": len(failures),
        "bound_waypoint_failure_examples": failures[:20],
        "bound_teleportation_arrivals": teleports,
        "observed_passenger_legs": len(sequences),
        "unmatched_bound_departures": sum(len(rows) for rows in unmatched.values()),
    }


def main() -> int:
    args = parse_args()
    with args.bindings.open("r", encoding="utf-8", newline="") as handle:
        bindings = list(csv.DictReader(handle))
    log_text = args.log.read_text(encoding="utf-8", errors="replace")

    selection_records = [
        {
            "candidate_group": match.group(1),
            "household": match.group(2),
            "passenger": match.group(3),
            "new_candidate": match.group(4) == "true",
            "candidate_legs": int(match.group(5)),
            "choice": match.group(6),
            "delta": float(match.group(7)),
            "schedule_feasible": match.group(8) == "true",
        }
        for match in SELECTION.finditer(log_text)
    ]
    selection_by_group = {
        item["candidate_group"]: item["choice"] for item in selection_records
    }
    mode_records = [
        {
            "candidate_group": match.group(1),
            "household": match.group(2),
            "new_candidate": match.group(3) == "true",
            "passenger": match.group(4),
            "passenger_leg": int(match.group(5)),
            "pt_available": match.group(6) == "true",
            "mode": match.group(7),
        }
        for match in REAL_CANDIDATE.finditer(log_text)
    ]
    expected_modes_all = {
        (item["passenger"], item["passenger_leg"]): (
            item["candidate_group"], item["mode"]
        )
        for item in mode_records
    }
    expected_released = {
        key: mode for key, (group, mode) in expected_modes_all.items()
        if selection_by_group.get(group) == "unbound"
    }

    summary_matches = list(SUMMARY.finditer(log_text))
    summary = None
    if len(summary_matches) == 1:
        names = (
            "candidate_bundles", "alternatives_per_candidate", "selected_bound",
            "selected_unbound", "active_bindings", "generated_waypoint_legs",
            "infeasible_bound_bundles", "selected_unbound_pt_legs",
            "selected_unbound_taxi_legs", "selected_unbound_car_legs",
            "unavailable_physical_pt_candidates", "candidate_households",
            "candidate_legs", "new_candidate_bundles",
            "selected_new_bound_bundles", "selected_new_unbound_bundles",
            "selected_bound_legs", "selected_unbound_legs",
            "resource_conflict_unbound_bundles", "new_joint_pairs",
        )
        summary = dict(zip(
            names, (int(value) for value in summary_matches[0].groups()), strict=True
        ))

    groups = {row["candidate_group_id"] for row in bindings}
    households = {row["household_id"] for row in bindings}
    new_rows = [row for row in bindings if row["new_candidate"].lower() == "true"]
    new_groups = {row["candidate_group_id"] for row in new_rows}
    group_sizes = Counter(row["candidate_group_id"] for row in bindings)
    bound_resources = [
        f"{row['vehicle_id']}/{row['driver_person_id']}/{row['driver_leg_index']}"
        for row in bindings
        if selection_by_group.get(row["candidate_group_id"]) == "bound"
    ]
    resource_counts = Counter(bound_resources)
    resource_conflicts = sorted(
        key for key, count in resource_counts.items() if count > 1
    )

    choices_by_passenger: dict[str, set[str]] = defaultdict(set)
    for row in bindings:
        choice = selection_by_group.get(row["candidate_group_id"])
        if choice is not None:
            choices_by_passenger[row["passenger_person_id"]].add(choice)
    mixed_passengers = sorted(
        passenger for passenger, choices in choices_by_passenger.items()
        if choices == {"bound", "unbound"}
    )

    events = audit_bound_events(args.events, bindings, selection_by_group)
    plans = base.audit_plans(args.plans)
    released = real.audit_released_plans(args.plans, expected_released)
    config = base.audit_config(args.config)
    dynamic = [match.groups() for match in maximum.DYNAMIC.finditer(log_text)]
    physical_matches = list(maximum.PHYSICAL.finditer(log_text))
    physical = None
    if len(physical_matches) == 1:
        physical = [int(value) for value in physical_matches[0].groups()]

    checks = {
        "process_exit_zero": int(args.exit_code.read_text(encoding="ascii").strip()) == 0,
        "registry_shape_exact": len(bindings) == EXPECTED_BINDINGS
        and len(groups) == EXPECTED_BUNDLES
        and len(households) == EXPECTED_HOUSEHOLDS
        and len(new_rows) == EXPECTED_NEW_BINDINGS
        and len(new_groups) == EXPECTED_NEW_BUNDLES,
        "each_candidate_is_one_leg": set(group_sizes.values()) == {1},
        "selector_summary_exact": summary is not None
        and summary["candidate_bundles"] == EXPECTED_BUNDLES
        and summary["candidate_households"] == EXPECTED_HOUSEHOLDS
        and summary["candidate_legs"] == EXPECTED_BINDINGS
        and summary["new_candidate_bundles"] == EXPECTED_NEW_BUNDLES,
        "every_bundle_selected_once": len(selection_records) == EXPECTED_BUNDLES
        and len(selection_by_group) == EXPECTED_BUNDLES,
        "every_candidate_leg_has_real_release_choice": len(expected_modes_all) == EXPECTED_BINDINGS,
        "new_candidates_were_endogenously_selected": summary is not None
        and summary["selected_new_bound_bundles"] > 0
        and summary["selected_new_bound_bundles"]
        + summary["selected_new_unbound_bundles"] == EXPECTED_NEW_BUNDLES
        and summary["new_joint_pairs"] == summary["selected_new_bound_bundles"],
        "vehicle_resources_not_reused": not resource_conflicts,
        "selected_leg_counts_conserved": summary is not None
        and summary["selected_bound_legs"] + summary["selected_unbound_legs"]
        == EXPECTED_BINDINGS
        and summary["active_bindings"] == summary["selected_bound_legs"],
        "released_trip_count_conserved": summary is not None
        and len(expected_released) == summary["selected_unbound_legs"]
        and summary["selected_unbound_pt_legs"]
        + summary["selected_unbound_taxi_legs"] == len(expected_released)
        and summary["selected_unbound_car_legs"] == 0,
        "released_plans_are_real_pt_or_taxi": released["failure_count"] == 0
        and released["released_car_legs"] == 0,
        "completed_bound_legs_use_exact_waypoints": events[
            "bound_waypoint_failure_count"
        ] == 0 and physical is not None
        and events["bound_legs_completed_at_exact_waypoints"] == physical[3],
        "no_bound_teleportation": events["bound_teleportation_arrivals"] == 0,
        "all_bound_departures_observed": physical is not None
        and events["observed_passenger_legs"] == physical[0]
        and events["unmatched_bound_departures"] == 0,
        "all_active_bindings_classified": summary is not None and physical is not None
        and physical[-1] == summary["active_bindings"]
        and physical[-3] == 0 and physical[-2] == 0,
        "remaining_car_passenger_count_correct": summary is not None
        and plans["selected_plan_mode_counts"].get("car_passenger")
        == base.EXPECTED_MODE_COUNTS["car_passenger"] - summary["selected_unbound_legs"],
        "taxi_count_correct": summary is not None
        and plans["selected_plan_mode_counts"].get("taxi")
        == base.EXPECTED_MODE_COUNTS["taxi"] + summary["selected_unbound_taxi_legs"],
        "car_count_unchanged": plans["selected_plan_mode_counts"].get("car")
        == base.EXPECTED_MODE_COUNTS["car"],
        "ordinary_innovation_frozen": config["strategy_weights"].get("ReRoute") == [0.0]
        and config["strategy_weights"].get("SubtourModeChoice") == [0.0]
        and config["strategy_weights"].get("TimeAllocationMutator") == [0.0],
        "one_qsim_iteration": config["first_iteration"] == 0
        and config["last_iteration"] == 0,
        "dynamic_costs_live": len(dynamic) == 1
        and all(float(value) > 0 for value in dynamic[0][1:4])
        and all(float(value) > 0 for value in dynamic[0][6:9]),
        "all_scores_finite": plans["selected_scores_finite"],
    }
    report = {
        "status": "validated" if all(checks.values()) else "failed",
        "selector_summary": summary,
        "registry": {
            "bindings": len(bindings),
            "candidate_bundles": len(groups),
            "candidate_households": len(households),
            "new_candidate_bindings": len(new_rows),
            "new_candidate_bundles": len(new_groups),
            "candidate_group_size_counts": dict(sorted(Counter(
                group_sizes.values()
            ).items())),
        },
        "selection_counts": dict(sorted(Counter(
            ("new_" if item["new_candidate"] else "legacy_") + item["choice"]
            for item in selection_records
        ).items())),
        "mixed_bound_unbound_passengers": {
            "count": len(mixed_passengers),
            "examples": mixed_passengers[:20],
        },
        "vehicle_resource_conflicts": resource_conflicts,
        "released_plans": released,
        "events": events,
        "plans": plans,
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "all_checks_passed": all(checks.values()),
    }
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["all_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
