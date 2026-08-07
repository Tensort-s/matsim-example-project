#!/usr/bin/env python3
"""Build the bounded endogenous household joint-candidate registry.

The registry contains every Stage 11 ``car_passenger`` leg that passed the
existing direct-or-detour same-household driver screen.  It preserves the 278
legacy school-escort bindings and adds the 106 newly eligible legs without
creating a driver tour or assigning a new household vehicle.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path

from prepare_hong_kong_school_escort_physical_pilot import (
    fail,
    inspect_target_legs,
    read_rows,
)


EXPECTED_CANDIDATE_LEGS = 384
EXPECTED_CANDIDATE_PEOPLE = 244
EXPECTED_CANDIDATE_HOUSEHOLDS = 240
EXPECTED_CANDIDATE_BUNDLES = 384
EXPECTED_LEGACY_LEGS = 278
EXPECTED_NEW_LEGS = 106
ELIGIBLE_STATUSES = {
    "existing_car_leg_direct",
    "existing_car_leg_detour_screen",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plans", type=Path, required=True)
    parser.add_argument("--candidate-legs", type=Path, required=True)
    parser.add_argument("--legacy-bindings", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def build_registry(
    candidate_rows: list[dict[str, str]],
    legacy_rows: list[dict[str, str]],
    inspected: dict[tuple[str, int], dict[str, object]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    eligible = [
        row for row in candidate_rows
        if row["candidate_status"] in ELIGIBLE_STATUSES
    ]
    legacy = {
        (row["passenger_person_id"], int(row["passenger_leg_index"])): row
        for row in legacy_rows
    }
    if len(legacy) != EXPECTED_LEGACY_LEGS:
        fail(f"Expected {EXPECTED_LEGACY_LEGS} legacy bindings, found {len(legacy)}")

    bindings: list[dict[str, object]] = []
    matched_legacy: set[tuple[str, int]] = set()
    for row in eligible:
        passenger_id = row["person_id"]
        passenger_leg_index = int(row["leg_index"])
        driver_id = row["best_driver_person_id"]
        driver_leg_index = int(row["best_driver_leg_index"])
        vehicle_id = row["best_vehicle_id"]
        household_id = row["household_id"]
        passenger = inspected.get((passenger_id, passenger_leg_index))
        driver = inspected.get((driver_id, driver_leg_index))
        if passenger is None or driver is None:
            fail(f"Missing inspected plan leg for {passenger_id}/{passenger_leg_index}")
        if passenger["mode"] != "car_passenger" or driver["mode"] != "car":
            fail(f"Mode mismatch for {passenger_id}/{passenger_leg_index}")
        if driver["route_vehicle_id"] != vehicle_id:
            fail(f"Vehicle mismatch for {driver_id}/{driver_leg_index}")
        if not passenger["route_start_link"] or not passenger["route_end_link"]:
            fail(f"Passenger route lacks physical waypoint links: {passenger_id}/{passenger_leg_index}")

        key = (passenger_id, passenger_leg_index)
        is_legacy = key in legacy
        if is_legacy:
            reference = legacy[key]
            expected = (
                reference["driver_person_id"],
                int(reference["driver_leg_index"]),
                reference["vehicle_id"],
                reference["passenger_pickup_link"],
                reference["passenger_dropoff_link"],
            )
            observed = (
                driver_id,
                driver_leg_index,
                vehicle_id,
                passenger["route_start_link"],
                passenger["route_end_link"],
            )
            if observed != expected:
                fail(f"Legacy binding changed for {passenger_id}/{passenger_leg_index}")
            matched_legacy.add(key)

        passenger_departure = float(passenger["departure_time_s"])
        driver_departure = float(driver["departure_time_s"])
        bindings.append({
            "candidate_group_id": (
                f"joint:{household_id}:{passenger_id}:{passenger_leg_index}"
            ),
            "household_id": household_id,
            "candidate_source": (
                "legacy_complete_direct_pair" if is_legacy else row["candidate_status"]
            ),
            "new_candidate": str(not is_legacy).lower(),
            "passenger_person_id": passenger_id,
            "passenger_leg_index": passenger_leg_index,
            "driver_person_id": driver_id,
            "driver_leg_index": driver_leg_index,
            "vehicle_id": vehicle_id,
            "passenger_planned_departure_time_s": passenger_departure,
            "driver_planned_departure_time_s": driver_departure,
            "passenger_ready_before_driver_s": driver_departure - passenger_departure,
            "origin_access_gap_m": float(row["best_origin_gap_m"]),
            "destination_egress_gap_m": float(row["best_destination_gap_m"]),
            "passenger_pickup_link": passenger["route_start_link"],
            "passenger_dropoff_link": passenger["route_end_link"],
            "driver_route_start_link": driver["route_start_link"],
            "driver_route_end_link": driver["route_end_link"],
        })

    bindings.sort(key=lambda item: (
        str(item["household_id"]),
        str(item["passenger_person_id"]),
        int(item["passenger_leg_index"]),
    ))
    if matched_legacy != set(legacy):
        fail(f"Registry lost {len(set(legacy) - matched_legacy)} legacy bindings")

    by_group: dict[str, list[dict[str, object]]] = defaultdict(list)
    by_household: dict[str, set[str]] = defaultdict(set)
    by_resource: Counter[str] = Counter()
    for binding in bindings:
        group = str(binding["candidate_group_id"])
        by_group[group].append(binding)
        by_household[str(binding["household_id"])].add(group)
        resource = (
            f"{binding['vehicle_id']}/{binding['driver_person_id']}/"
            f"{binding['driver_leg_index']}"
        )
        by_resource[resource] += 1

    new_bindings = [item for item in bindings if item["new_candidate"] == "true"]
    candidate_people = {str(item["passenger_person_id"]) for item in bindings}
    checks = {
        "candidate_leg_count_exact": len(bindings) == EXPECTED_CANDIDATE_LEGS,
        "candidate_bundle_count_exact": len(by_group) == EXPECTED_CANDIDATE_BUNDLES,
        "candidate_people_exact": len(candidate_people) == EXPECTED_CANDIDATE_PEOPLE,
        "candidate_households_exact": len(by_household) == EXPECTED_CANDIDATE_HOUSEHOLDS,
        "legacy_bindings_preserved": len(matched_legacy) == EXPECTED_LEGACY_LEGS,
        "new_candidate_leg_count_exact": len(new_bindings) == EXPECTED_NEW_LEGS,
        "one_leg_per_candidate_bundle": all(len(group) == 1 for group in by_group.values()),
        "household_selector_limit_respected": max(map(len, by_household.values())) <= 20,
        "all_routes_and_vehicles_resolved": all(
            item["vehicle_id"]
            and item["passenger_pickup_link"]
            and item["passenger_dropoff_link"]
            for item in bindings
        ),
    }
    if not all(checks.values()):
        fail(f"Household joint-candidate registry checks failed: {checks}")

    summary = {
        "status": "validated_household_joint_candidate_registry",
        "scope": (
            "Existing driver Car legs only; direct/detour-screened household "
            "passengers; no new driver tour or independent passenger Car"
        ),
        "counts": {
            "candidate_legs": len(bindings),
            "candidate_bundles": len(by_group),
            "candidate_people": len(candidate_people),
            "candidate_households": len(by_household),
            "legacy_legs": len(matched_legacy),
            "legacy_bundles": sum(
                all(item["new_candidate"] == "false" for item in group)
                for group in by_group.values()
            ),
            "new_candidate_legs": len(new_bindings),
            "new_candidate_bundles": sum(
                any(item["new_candidate"] == "true" for item in group)
                for group in by_group.values()
            ),
            "one_leg_bundles": sum(len(group) == 1 for group in by_group.values()),
            "two_leg_bundles": sum(len(group) == 2 for group in by_group.values()),
            "shared_driver_leg_resources": sum(count > 1 for count in by_resource.values()),
            "passenger_departure_after_driver_departure_legs": sum(
                float(item["passenger_ready_before_driver_s"]) < 0 for item in bindings
            ),
        },
        "candidate_source_counts": dict(sorted(Counter(
            str(item["candidate_source"]) for item in bindings
        ).items())),
        "checks": checks,
        "all_checks_passed": True,
    }
    return bindings, summary


def main() -> int:
    args = parse_args()
    candidate_rows = read_rows(args.candidate_legs)
    legacy_rows = read_rows(args.legacy_bindings)
    eligible = [
        row for row in candidate_rows
        if row["candidate_status"] in ELIGIBLE_STATUSES
    ]
    target_people = {
        value
        for row in eligible
        for value in (row["person_id"], row["best_driver_person_id"])
    }
    inspected = inspect_target_legs(args.plans, target_people)
    bindings, summary = build_registry(candidate_rows, legacy_rows, inspected)

    args.output_dir.mkdir(parents=True, exist_ok=False)
    registry = args.output_dir / "household_joint_candidate_bindings.csv"
    with registry.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(bindings[0]))
        writer.writeheader()
        writer.writerows(bindings)
    summary["inputs"] = {
        "plans": str(args.plans),
        "candidate_legs": str(args.candidate_legs),
        "legacy_bindings": str(args.legacy_bindings),
    }
    summary["output"] = str(registry)
    (args.output_dir / "household_joint_candidate_registry_validation.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
