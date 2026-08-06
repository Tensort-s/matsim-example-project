#!/usr/bin/env python3
"""Audit one fixed-binding school-escort JointReRoute cycle and it.1 QSim."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
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


ENGINE_PATTERN = re.compile(
    r"Household school-escort physical pilot: departures=(\d+), boardings=(\d+), "
    r"alightings=(\d+), completed=(\d+), passenger_stuck_onboard=(\d+), "
    r"driver_stuck_before_pickup=(\d+), skipped_after_prior_failure=(\d+), "
    r"waiting=(\d+), onboard=(\d+), classified=(\d+)"
)
JOINT_PATTERN = re.compile(
    r"Household school-escort JointReRoute: source_iteration=(\d+), drivers=(\d+), "
    r"unique_driver_legs=(\d+), changed_routes=(\d+), unchanged_routes=(\d+), "
    r"bindings_valid=(\d+)"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bindings", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--input-plans", type=Path, required=True)
    parser.add_argument("--output-plans", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--exit-code", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def read_bindings(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def route_record(leg: ET.Element) -> dict[str, object]:
    route = next((item for item in leg if local_name(item) == "route"), None)
    if route is None:
        return {"mode": leg.get("mode", ""), "route": None}
    return {
        "mode": leg.get("mode", ""),
        "start_link": route.get("start_link", ""),
        "end_link": route.get("end_link", ""),
        "vehicle_ref_id": route.get("vehicleRefId", ""),
        "distance": float(route.get("distance", "nan")),
        "links": tuple((route.text or "").split()),
    }


def selected_leg_records(
    path: Path,
    requested: dict[str, set[int]],
) -> dict[tuple[str, int], dict[str, object]]:
    records: dict[tuple[str, int], dict[str, object]] = {}
    with base.xml_stream(path) as handle:
        for _, element in ET.iterparse(handle, events=("end",)):
            if local_name(element) != "person":
                continue
            person_id = element.get("id", "")
            if person_id in requested:
                selected = [
                    item for item in element
                    if local_name(item) == "plan" and item.get("selected") == "yes"
                ]
                if len(selected) != 1:
                    raise ValueError(f"Expected one selected plan for {person_id}")
                legs = [item for item in selected[0] if local_name(item) == "leg"]
                for leg_index in requested[person_id]:
                    if leg_index >= len(legs):
                        raise ValueError(f"Missing selected leg {person_id}/{leg_index}")
                    records[(person_id, leg_index)] = route_record(legs[leg_index])
            element.clear()
    expected = sum(len(indices) for indices in requested.values())
    if len(records) != expected:
        raise ValueError(f"Expected {expected} requested legs; found {len(records)}")
    return records


def parsed_engine_summary(match: re.Match[str]) -> dict[str, int]:
    names = (
        "departures", "boardings", "alightings", "completed",
        "passenger_stuck_onboard", "driver_stuck_before_pickup",
        "skipped_after_prior_failure", "waiting", "onboard", "classified",
    )
    return {name: int(value) for name, value in zip(names, match.groups())}


def main() -> int:
    args = parse_args()
    bindings = read_bindings(args.bindings)
    driver_requests: dict[str, set[int]] = {}
    passenger_requests: dict[str, set[int]] = {}
    for row in bindings:
        driver_requests.setdefault(row["driver_person_id"], set()).add(
            int(row["driver_leg_index"])
        )
        passenger_requests.setdefault(row["passenger_person_id"], set()).add(
            int(row["passenger_leg_index"])
        )
    all_requests = {person: set(indices) for person, indices in driver_requests.items()}
    for person, indices in passenger_requests.items():
        all_requests.setdefault(person, set()).update(indices)

    initial = selected_leg_records(args.input_plans, all_requests)
    final = selected_leg_records(args.output_plans, all_requests)
    unique_driver_keys = {
        (row["driver_person_id"], int(row["driver_leg_index"])) for row in bindings
    }
    changed_driver_keys = sorted(
        f"{person}/{leg_index}"
        for person, leg_index in unique_driver_keys
        if initial[(person, leg_index)]["links"] != final[(person, leg_index)]["links"]
    )
    unchanged_driver_legs = len(unique_driver_keys) - len(changed_driver_keys)

    binding_identity_failures: list[str] = []
    for row in bindings:
        passenger_key = (row["passenger_person_id"], int(row["passenger_leg_index"]))
        driver_key = (row["driver_person_id"], int(row["driver_leg_index"]))
        passenger = final[passenger_key]
        driver = final[driver_key]
        if passenger["mode"] != "car_passenger":
            binding_identity_failures.append(f"passenger_mode:{passenger_key}")
        if driver["mode"] != "car":
            binding_identity_failures.append(f"driver_mode:{driver_key}")
        if driver["vehicle_ref_id"] != row["vehicle_id"]:
            binding_identity_failures.append(f"vehicle:{driver_key}")
        if driver["start_link"] != row["driver_route_start_link"]:
            binding_identity_failures.append(f"start_link:{driver_key}")
        if driver["end_link"] != row["driver_route_end_link"]:
            binding_identity_failures.append(f"end_link:{driver_key}")

    events = base.audit_events(args.events, bindings)
    plans = base.audit_plans(args.output_plans)
    config = base.audit_config(args.config)
    log_text = args.log.read_text(encoding="utf-8", errors="replace")
    engine_summaries = [parsed_engine_summary(item) for item in ENGINE_PATTERN.finditer(log_text)]
    joint_matches = list(JOINT_PATTERN.finditer(log_text))
    joint_summary = None
    if len(joint_matches) == 1:
        values = [int(value) for value in joint_matches[0].groups()]
        joint_summary = dict(zip(
            ("source_iteration", "drivers", "unique_driver_legs", "changed_routes",
             "unchanged_routes", "bindings_valid"),
            values,
        ))
    final_engine = engine_summaries[-1] if engine_summaries else None
    completed = events["bound_legs_with_exact_depart_board_alight_arrive_sequence"]
    onboard_stuck = events["bound_legs_passenger_stuck_while_onboard"]
    pickup_stuck = events["bound_legs_driver_stuck_before_pickup"]
    skipped = events["bound_legs_not_started_after_prior_failure"]
    expected_engine = {
        "departures": completed + onboard_stuck + pickup_stuck,
        "boardings": completed + onboard_stuck,
        "alightings": completed,
        "completed": completed,
        "passenger_stuck_onboard": onboard_stuck,
        "driver_stuck_before_pickup": pickup_stuck,
        "skipped_after_prior_failure": skipped,
        "waiting": 0,
        "onboard": 0,
        "classified": base.EXPECTED_BOUND_LEGS,
    }
    exit_code = int(args.exit_code.read_text(encoding="ascii").strip())
    route_counts_match = joint_summary is not None and (
        joint_summary["changed_routes"] == len(changed_driver_keys)
        and joint_summary["unchanged_routes"] == unchanged_driver_legs
        and joint_summary["unique_driver_legs"] == len(unique_driver_keys)
    )
    checks = {
        "process_exit_zero": exit_code == 0,
        "exact_binding_catalog": len(bindings) == base.EXPECTED_BOUND_LEGS
        and len(passenger_requests) == base.EXPECTED_BOUND_PEOPLE,
        "one_joint_reroute_application": joint_summary is not None
        and joint_summary["source_iteration"] == 0
        and joint_summary["bindings_valid"] == base.EXPECTED_BOUND_LEGS,
        "joint_reroute_changed_routes": bool(changed_driver_keys),
        "log_and_plan_route_counts_match": route_counts_match,
        "binding_identity_preserved": not binding_identity_failures,
        "two_qsim_iterations": len(engine_summaries) == 2
        and config["first_iteration"] == 0 and config["last_iteration"] == 1,
        "final_engine_matches_events": final_engine == expected_engine,
        "all_final_bound_outcomes_classified": (
            completed + onboard_stuck + pickup_stuck + skipped
            == base.EXPECTED_BOUND_LEGS
            and events["sequence_failure_count"] == 0
        ),
        "no_final_bound_teleportation": events["bound_teleportation_arrivals"] == 0,
        "final_bound_vehicles_moved_on_network": events[
            "bound_vehicle_link_event_counts"
        ].get("entered link", 0) > 0,
        "ordinary_innovation_frozen": config["strategy_weights"].get("ReRoute") == [0.0]
        and config["strategy_weights"].get("SubtourModeChoice") == [0.0]
        and config["strategy_weights"].get("TimeAllocationMutator") == [0.0],
        "output_mode_counts_unchanged": plans["selected_plan_mode_counts"]
        == base.EXPECTED_MODE_COUNTS,
        "all_output_scores_finite": plans["selected_scores_finite"],
        "fixed_route_multimodal_cost_module_excluded": (
            "Enabled Hong Kong Taxi/PT/Car joint cost scoring" not in log_text
        ),
    }
    report = {
        "status": "validated" if all(checks.values()) else "failed",
        "scope": (
            "Fixed 139-pair school_escort: it.0, one binding-preserving "
            "JointReRoute, then physical it.1"
        ),
        "inputs": {name: str(getattr(args, name)) for name in (
            "bindings", "events", "input_plans", "output_plans", "config", "log",
            "exit_code",
        )},
        "joint_reroute": {
            "log_summary": joint_summary,
            "unique_driver_legs": len(unique_driver_keys),
            "changed_driver_legs": len(changed_driver_keys),
            "unchanged_driver_legs": unchanged_driver_legs,
            "changed_driver_leg_examples": changed_driver_keys[:20],
            "binding_identity_failure_count": len(binding_identity_failures),
            "binding_identity_failure_examples": binding_identity_failures[:20],
        },
        "engine_summaries": engine_summaries,
        "final_iteration_events": events,
        "plans": plans,
        "config": config,
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "all_checks_passed": all(checks.values()),
        "interpretation": (
            "This isolates binding persistence under one driver-route innovation cycle. "
            "The fixed-route Taxi/PT/Car cost module is intentionally not loaded, so the "
            "run is not evidence for cost consistency after rerouting."
        ),
    }
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["all_checks_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
