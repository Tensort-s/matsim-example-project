#!/usr/bin/env python3
"""Audit bound waypoints plus released PT/Taxi household passenger trips."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET


HERE = Path(__file__).parent


def load_helper(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


maximum = load_helper(
    "household_maximum_audit", "audit_hong_kong_household_max_utility_pilot.py"
)
base = maximum.base

SUMMARY = re.compile(
    r"Household escort maximum-utility selector: (?:households|candidate_bundles)=(\d+), "
    r"(?:candidates_per_household|alternatives_per_candidate)=(\d+), "
    r"selected_bound=(\d+), selected_unbound=(\d+), "
    r"active_bindings=(\d+), generated_waypoint_legs=(\d+), "
    r"infeasible_bound_households=(\d+), selected_unbound_pt_legs=(\d+), "
    r"selected_unbound_taxi_legs=(\d+), selected_unbound_car_passenger_legs=(\d+), "
    r"unavailable_physical_pt_candidates=(\d+), .*probability_choice=false, "
    r"driver_constraint=false, new_joint_pairs=\d+"
)
REAL_CANDIDATE = re.compile(
    r"HK_HOUSEHOLD_ESCORT_REAL_MODE_CANDIDATE "
    r"(?:candidate_group=\S+ household=\S+ new_candidate=(?:true|false) )?"
    r"passenger=(\S+) passenger_leg=(\d+) "
    r"pt_available=(true|false).*selected_mode=(pt|taxi)"
)
RELEASED_MODE = "hkHouseholdEscortReleasedPassengerMode"
RELEASED_INDEX = "hkHouseholdEscortOriginalPassengerLegIndex"
TAXI_NAMES = {
    "hkTaxiFareBaselineHkd", "hkTaxiType", "hkTaxiFareScope",
    "hkTaxiFareModelVersion", "hkTaxiClassificationSource", "hkTaxiMainTripIndex",
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


def local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def element_attributes(element: ET.Element) -> dict[str, str]:
    values: dict[str, str] = {}
    for child in element:
        if local_name(child) != "attributes":
            continue
        for attribute in child:
            if local_name(attribute) == "attribute" and attribute.get("name"):
                values[attribute.get("name", "")] = (attribute.text or "").strip()
    return values


def audit_released_plans(
    path: Path,
    expected: dict[tuple[str, int], str],
) -> dict[str, object]:
    observed: dict[tuple[str, int], list[dict[str, object]]] = {}
    released_car_legs = 0
    with base.xml_stream(path) as handle:
        for _, person in ET.iterparse(handle, events=("end",)):
            if local_name(person) != "person":
                continue
            person_id = person.get("id", "")
            if not any(key[0] == person_id for key in expected):
                person.clear()
                continue
            selected = [
                item for item in person
                if local_name(item) == "plan" and item.get("selected") == "yes"
            ]
            if len(selected) != 1:
                person.clear()
                continue
            for leg in selected[0]:
                if local_name(leg) != "leg":
                    continue
                attributes = element_attributes(leg)
                if RELEASED_MODE not in attributes:
                    continue
                mode = leg.get("mode", "")
                released_car_legs += mode == "car"
                key = (person_id, int(attributes[RELEASED_INDEX]))
                route = next(
                    (item for item in leg if local_name(item) == "route"), None
                )
                observed.setdefault(key, []).append({
                    "mode": mode,
                    "released_mode": attributes[RELEASED_MODE],
                    "routing_mode": leg.get("routingMode", attributes.get("routingMode", "")),
                    "route_type": "" if route is None else route.get("type", ""),
                    "route_present": route is not None,
                    "taxi_attributes": sorted(TAXI_NAMES & set(attributes)),
                })
            person.clear()

    failures: list[str] = []
    pt_trips = 0
    taxi_trips = 0
    for key, expected_mode in expected.items():
        legs = observed.get(key, [])
        if not legs:
            failures.append(f"{key}: released trip tag absent")
            continue
        if any(item["released_mode"] != expected_mode for item in legs):
            failures.append(f"{key}: released-mode tag mismatch")
        if any(item["mode"] == "car" for item in legs):
            failures.append(f"{key}: illegal passenger Car leg")
        if expected_mode == "taxi":
            taxi_trips += 1
            taxi_legs = [item for item in legs if item["mode"] == "taxi"]
            if len(taxi_legs) != 1 or not taxi_legs[0]["route_present"]:
                failures.append(f"{key}: Taxi trip is not one routed Taxi leg")
            elif len(taxi_legs[0]["taxi_attributes"]) != len(TAXI_NAMES):
                failures.append(f"{key}: Taxi fare attributes incomplete")
        else:
            pt_trips += 1
            physical = [
                item for item in legs
                if item["mode"] == "pt"
                and (
                    item["route_type"].lower() == "default_pt"
                    or item["route_type"].lower().startswith("experimentalpt")
                )
            ]
            if not physical:
                failures.append(f"{key}: no TransitPassengerRoute PT leg")
            if any(item["routing_mode"] not in {"", "pt"} for item in legs):
                failures.append(f"{key}: inconsistent PT routingMode")
    extras = sorted(set(observed) - set(expected))
    if extras:
        failures.append(f"unexpected released trip tags: {extras[:10]}")
    return {
        "expected_released_trips": len(expected),
        "observed_released_trips": len(observed),
        "physical_pt_trips": pt_trips,
        "routed_taxi_trips": taxi_trips,
        "released_car_legs": released_car_legs,
        "failure_count": len(failures),
        "failure_examples": failures[:20],
    }


def main() -> int:
    args = parse_args()
    with args.bindings.open("r", encoding="utf-8", newline="") as handle:
        bindings = list(csv.DictReader(handle))
    log_text = args.log.read_text(encoding="utf-8", errors="replace")
    selections = {
        match.group(1): match.group(2)
        for match in maximum.SELECTION.finditer(log_text)
    }
    expected_modes_all = {
        (match.group(1), int(match.group(2))): match.group(4)
        for match in REAL_CANDIDATE.finditer(log_text)
    }
    expected_released = {
        key: mode for key, mode in expected_modes_all.items()
        if selections.get(key[0]) == "unbound"
    }
    summary_matches = list(SUMMARY.finditer(log_text))
    summary = None
    if len(summary_matches) == 1:
        names = (
            "households", "candidates_per_household", "selected_bound",
            "selected_unbound", "active_bindings", "generated_waypoint_legs",
            "infeasible_bound_households", "selected_unbound_pt_legs",
            "selected_unbound_taxi_legs", "selected_unbound_car_passenger_legs",
            "unavailable_physical_pt_candidates",
        )
        summary = dict(zip(names, (int(value) for value in summary_matches[0].groups())))

    events = maximum.audit_events(args.events, bindings, selections)
    plans = base.audit_plans(args.plans)
    released = audit_released_plans(args.plans, expected_released)
    config = base.audit_config(args.config)
    dynamic = [match.groups() for match in maximum.DYNAMIC.finditer(log_text)]
    physical_matches = list(maximum.PHYSICAL.finditer(log_text))
    physical = None
    if len(physical_matches) == 1:
        physical = [int(value) for value in physical_matches[0].groups()]

    checks = {
        "process_exit_zero": int(args.exit_code.read_text(encoding="ascii").strip()) == 0,
        "selector_summary_present": summary is not None,
        "all_candidate_legs_have_pt_taxi_choice": len(expected_modes_all) == 278,
        "released_trip_count_conserved": summary is not None
        and len(expected_released) == summary["selected_unbound"] * 2
        and summary["selected_unbound_pt_legs"]
        + summary["selected_unbound_taxi_legs"] == len(expected_released)
        and summary["selected_unbound_car_passenger_legs"] == 0,
        "released_plans_are_real_pt_or_taxi": released["failure_count"] == 0
        and released["released_car_legs"] == 0,
        "completed_bound_legs_use_exact_waypoints": events[
            "bound_waypoint_failure_count"
        ] == 0,
        "no_bound_teleportation": events["bound_teleportation_arrivals"] == 0,
        "all_active_bindings_classified": summary is not None and physical is not None
        and physical[-1] == summary["active_bindings"]
        and physical[-3] == 0 and physical[-2] == 0,
        "remaining_car_passenger_count_correct": summary is not None
        and plans["selected_plan_mode_counts"].get("car_passenger")
        == base.EXPECTED_MODE_COUNTS["car_passenger"]
        - summary["selected_unbound"] * 2,
        "taxi_count_correct": summary is not None
        and plans["selected_plan_mode_counts"].get("taxi")
        == base.EXPECTED_MODE_COUNTS["taxi"]
        + summary["selected_unbound_taxi_legs"],
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
        "selection_counts": {
            "bound": sum(value == "bound" for value in selections.values()),
            "unbound": sum(value == "unbound" for value in selections.values()),
        },
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
    return 0 if report["all_checks_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
