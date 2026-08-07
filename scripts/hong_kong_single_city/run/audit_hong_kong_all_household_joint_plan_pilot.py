#!/usr/bin/env python3
"""Audit the all-car-household delayed joint-plan iterations 0-1 pilot."""

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


INITIAL_MODE_COUNTS = {
    "car": 67_718,
    "car_passenger": 2_734,
    "pt": 557_375,
    "school_bus": 9_626,
    "taxi": 44_000,
    "walk": 199_863,
}
EXPECTED_CANDIDATES = 9_289
EXPECTED_HOUSEHOLDS = 5_789
EXPECTED_CAR_PASSENGER = 2_734

GENERATOR = re.compile(
    r"Household joint-plan alternatives: candidates=(\d+), passenger_templates=(\d+), "
    r"driver_templates=(\d+), driver_switch_templates=(\d+), selected_templates=0, "
    r"original_car_passenger_trips=(\d+), car_passenger_unbind_templates=(\d+), "
    r"car_passenger_release_modes=pt\|taxi\|walk, "
    r"baseline_selected_plans_preserved=true, school_bus_candidates=0"
)
SUMMARY = re.compile(
    r"Household joint-plan selector: source_iteration=0, candidate_pairs=(\d+), "
    r"candidate_households=(\d+), driver_switch_candidates=(\d+), "
    r"infeasible_candidates=(\d+), selected_joint_pairs=(\d+), "
    r"selected_existing_car_pairs=(\d+), selected_driver_switch_pairs=(\d+), "
    r"active_physical_bindings=(\d+), original_car_passenger_trips=(\d+), "
    r"fallback_best_pt=(\d+), fallback_best_taxi=(\d+), fallback_best_walk=(\d+), "
    r"selected_plans_added=(\d+), repaired_selected_taxi_trips=(\d+), "
    r"initial_selected_plans_preserved_through_iteration_0=true, "
    r"school_bus_candidates=0, probability_choice=false, driver_constraint=false"
)
SELECTION = re.compile(
    r"HK_HOUSEHOLD_JOINT_SELECTION candidate=(\S+) household=(\S+) "
    r"passenger=(\S+) passenger_trip=(\d+) driver=(\S+) driver_trip=(\d+) "
    r"choice=(joint|fallback) utility_delta=([0-9.Ee+-]+) schedule_feasible=(true|false)"
)
RELEASE_DECISION = re.compile(
    r"HK_CAR_PASSENGER_RELEASE_CANDIDATE passenger=(\S+) trip=(\d+) .*? "
    r"selected_mode=(pt|taxi|walk)"
)
PHYSICAL = re.compile(
    r"Household school-escort physical pilot: departures=(\d+), boardings=(\d+), "
    r"alightings=(\d+), completed=(\d+), passenger_stuck_onboard=(\d+), "
    r"driver_stuck_before_pickup=(\d+), skipped_after_prior_failure=(\d+), "
    r"waiting=(\d+), onboard=(\d+), classified=(\d+), "
    r"simulation_end_before_pickup=(\d+), simulation_end_while_onboard=(\d+), "
    r"simulation_end_before_bound_departure=(\d+)"
)
RELEASED_MODE = "hkHouseholdEscortReleasedPassengerMode"
RELEASED_INDEX = "hkHouseholdEscortOriginalPassengerLegIndex"
JOINT_ID = "hkHouseholdJointCandidateId"
PLAN_ROLE = "hkHouseholdJointPlanRole"
TEMPLATE = "hkHouseholdJointTemplate"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--plans", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--exit-code", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


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


@contextlib.contextmanager
def open_xml(path: Path):
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
            return_code = process.wait()
            if return_code != 0:
                raise RuntimeError(f"zstd failed for {path}: {return_code}")
        return
    with path.open("rb") as handle:
        yield handle


def audit_plans(path: Path) -> dict[str, object]:
    selected_modes: Counter[str] = Counter()
    selected_roles: Counter[str] = Counter()
    selected_templates = 0
    template_roles: Counter[str] = Counter()
    released_trip_keys: set[tuple[str, str, str]] = set()
    selected_joint_ids: set[str] = set()
    selected_car_passenger = 0
    selected_car_passenger_resolved = 0
    person_count = 0
    with open_xml(path) as handle:
        for _, person in ET.iterparse(handle, events=("end",)):
            if local_name(person) != "person":
                continue
            person_count += 1
            plans = [item for item in person if local_name(item) == "plan"]
            selected = [item for item in plans if item.get("selected") == "yes"]
            if len(selected) != 1:
                person.clear()
                continue
            for plan in plans:
                plan_attributes = attributes(plan)
                role = plan_attributes.get(PLAN_ROLE, "untagged")
                is_template = plan_attributes.get(TEMPLATE, "false").lower() == "true"
                if is_template:
                    template_roles[role] += 1
                if plan is selected[0]:
                    selected_roles[role] += 1
                    selected_templates += is_template
                    for leg in plan:
                        if local_name(leg) != "leg":
                            continue
                        mode = leg.get("mode", "")
                        selected_modes[mode] += 1
                        leg_attributes = attributes(leg)
                        if RELEASED_MODE in leg_attributes:
                            released_trip_keys.add((
                                person.get("id", ""),
                                leg_attributes.get(RELEASED_INDEX, ""),
                                leg_attributes[RELEASED_MODE],
                            ))
                        if mode == "car_passenger":
                            selected_car_passenger += 1
                            candidate_id = leg_attributes.get(JOINT_ID)
                            binding_key = leg_attributes.get("hkHouseholdEscortBindingKey")
                            if candidate_id and binding_key:
                                selected_joint_ids.add(candidate_id)
                                selected_car_passenger_resolved += 1
            person.clear()
    return {
        "persons": person_count,
        "selected_mode_counts": dict(sorted(selected_modes.items())),
        "selected_plan_roles": dict(sorted(selected_roles.items())),
        "template_plan_roles": dict(sorted(template_roles.items())),
        "selected_template_plans": selected_templates,
        "released_modes": dict(sorted(Counter(
            mode for _, _, mode in released_trip_keys
        ).items())),
        "selected_joint_candidate_ids": len(selected_joint_ids),
        "selected_car_passenger_legs": selected_car_passenger,
        "resolved_car_passenger_legs": selected_car_passenger_resolved,
    }


def audit_config(path: Path) -> dict[str, object]:
    root = ET.parse(path).getroot()
    modules = {item.get("name"): item for item in root.findall("./module")}
    controller = modules["controller"]
    values = {item.get("name"): item.get("value") for item in controller.findall("./param")}
    weights: dict[str, list[float]] = defaultdict(list)
    for settings in modules["replanning"].findall("./parameterset"):
        params = {item.get("name"): item.get("value") for item in settings.findall("./param")}
        weights[params["strategyName"]].append(float(params["weight"]))
    return {
        "first_iteration": int(values["firstIteration"]),
        "last_iteration": int(values["lastIteration"]),
        "strategy_weights": dict(weights),
    }


def main() -> int:
    args = parse_args()
    with args.candidates.open("r", encoding="utf-8", newline="") as handle:
        candidates = list(csv.DictReader(handle))
    log_text = args.log.read_text(encoding="utf-8", errors="replace")
    generator_matches = list(GENERATOR.finditer(log_text))
    summary_matches = list(SUMMARY.finditer(log_text))
    selections = [
        {
            "candidate": match.group(1),
            "household": match.group(2),
            "passenger": match.group(3),
            "passenger_trip": int(match.group(4)),
            "driver": match.group(5),
            "driver_trip": int(match.group(6)),
            "choice": match.group(7),
            "delta": float(match.group(8)),
            "schedule_feasible": match.group(9) == "true",
        }
        for match in SELECTION.finditer(log_text)
    ]
    selected = {item["candidate"] for item in selections if item["choice"] == "joint"}
    release_decisions = {
        (match.group(1), int(match.group(2))): match.group(3)
        for match in RELEASE_DECISION.finditer(log_text)
    }
    generator = None if len(generator_matches) != 1 else [
        int(value) for value in generator_matches[0].groups()
    ]
    summary = None if len(summary_matches) != 1 else [
        int(value) for value in summary_matches[0].groups()
    ]
    physical = [[int(value) for value in match.groups()] for match in PHYSICAL.finditer(log_text)]
    plans = audit_plans(args.plans)
    config = audit_config(args.config)
    candidate_ids = {row["candidate_id"] for row in candidates}
    school_bus_rows = [
        row for row in candidates
        if row["passenger_original_mode"] == "school_bus"
        or row["driver_original_mode"] == "school_bus"
    ]
    selected_switch = sum(
        row["candidate_id"] in selected
        and row["driver_requires_car_switch"].lower() == "true"
        for row in candidates
    )
    rows_by_id = {row["candidate_id"]: row for row in candidates}
    selected_original_car_passenger_keys = {
        (rows_by_id[candidate_id]["passenger_person_id"],
         int(rows_by_id[candidate_id]["passenger_trip_index"]))
        for candidate_id in selected
        if rows_by_id[candidate_id]["passenger_original_mode"] == "car_passenger"
    }
    expected_release_modes = Counter(
        mode for trip_key, mode in release_decisions.items()
        if trip_key not in selected_original_car_passenger_keys
    )
    expected_mode_counts = Counter(INITIAL_MODE_COUNTS)
    for candidate_id in selected:
        original_mode = rows_by_id[candidate_id]["passenger_original_mode"]
        expected_mode_counts[original_mode] -= 1
        expected_mode_counts["car_passenger"] += 1
    for mode, count in expected_release_modes.items():
        expected_mode_counts["car_passenger"] -= count
        expected_mode_counts[mode] += count

    checks = {
        "process_exit_zero": int(args.exit_code.read_text(encoding="ascii").strip()) == 0,
        "candidate_registry_exact": len(candidates) == EXPECTED_CANDIDATES
        and len(candidate_ids) == EXPECTED_CANDIDATES
        and len({row["household_id"] for row in candidates}) == EXPECTED_HOUSEHOLDS,
        "school_bus_excluded": not school_bus_rows,
        "templates_generated_after_iteration_0": generator is not None
        and generator[0] == EXPECTED_CANDIDATES
        and generator[1] == EXPECTED_CANDIDATES
        and generator[2] == EXPECTED_CANDIDATES
        and generator[4] == EXPECTED_CAR_PASSENGER
        and generator[5] == EXPECTED_CAR_PASSENGER * 3,
        "every_candidate_decided_once": len(selections) == EXPECTED_CANDIDATES
        and {item["candidate"] for item in selections} == candidate_ids,
        "selector_summary_consistent": summary is not None
        and summary[0] == EXPECTED_CANDIDATES
        and summary[1] == EXPECTED_HOUSEHOLDS
        and summary[4] == len(selected)
        and summary[7] == len(selected)
        and summary[8] == EXPECTED_CAR_PASSENGER
        and summary[12] == plans["selected_plan_roles"].get(
            "household_joint_composite_after_iteration_0", 0
        ),
        "driver_switch_count_consistent": summary is not None
        and summary[6] == selected_switch,
        "no_template_selected": plans["selected_template_plans"] == 0,
        "all_selected_car_passenger_is_physical": plans["selected_car_passenger_legs"]
        == len(selected) and len(physical) == 2 and physical[1][9] == len(selected),
        "all_original_car_passenger_decided": len(release_decisions) == EXPECTED_CAR_PASSENGER,
        "non_stage_mode_counts_match_decisions": all(
            plans["selected_mode_counts"].get(mode, 0) == expected_mode_counts[mode]
            for mode in ("car", "car_passenger", "school_bus", "taxi")
        ),
        "all_original_car_passenger_resolved": sum(expected_release_modes.values())
        + len(selected_original_car_passenger_keys) == EXPECTED_CAR_PASSENGER,
        "school_bus_count_unchanged": plans["selected_mode_counts"].get("school_bus")
        == INITIAL_MODE_COUNTS["school_bus"],
        "ride_absent": plans["selected_mode_counts"].get("ride", 0) == 0,
        "physical_iteration_0_empty_iteration_1_classified": len(physical) == 2
        and physical[0][9] == 0
        and physical[1][9] == len(selected)
        and physical[1][7] == 0 and physical[1][8] == 0,
        "ordinary_innovation_frozen": config["strategy_weights"].get("KeepLastSelected") == [1.0] * 3
        and "ChangeExpBeta" not in config["strategy_weights"]
        and config["strategy_weights"].get("ReRoute") == [0.0] * 3
        and config["strategy_weights"].get("SubtourModeChoice") == [0.0] * 3
        and config["strategy_weights"].get("TimeAllocationMutator") == [0.0] * 3,
        "iterations_0_and_1": config["first_iteration"] == 0
        and config["last_iteration"] == 1,
        "no_fatal_log_error": not re.search(r"\b(?:FATAL|ERROR)\b", log_text),
    }
    report = {
        "status": "validated" if all(checks.values()) else "failed",
        "candidate_rows": len(candidates),
        "candidate_households": len({row["household_id"] for row in candidates}),
        "selection_counts": dict(Counter(item["choice"] for item in selections)),
        "selected_driver_switch_pairs": selected_switch,
        "selected_original_car_passenger_joint_trips": len(selected_original_car_passenger_keys),
        "release_decisions": dict(sorted(Counter(release_decisions.values()).items())),
        "expected_applied_release_modes": dict(sorted(expected_release_modes.items())),
        "expected_selected_mode_counts": dict(sorted(expected_mode_counts.items())),
        "generator": generator,
        "selector_summary": summary,
        "physical_iterations": physical,
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
