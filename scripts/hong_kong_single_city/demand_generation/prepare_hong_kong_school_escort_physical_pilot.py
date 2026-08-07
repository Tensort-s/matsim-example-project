#!/usr/bin/env python3
"""Build the fixed 139-household school-escort physical-pilot bindings."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
from collections import Counter
from pathlib import Path
import xml.etree.ElementTree as ET


EXPECTED_PEOPLE = 139
EXPECTED_LEGS = 278


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plans", type=Path, required=True)
    parser.add_argument("--candidate-people", type=Path, required=True)
    parser.add_argument("--candidate-legs", type=Path, required=True)
    parser.add_argument("--legacy-assignments", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def fail(message: str) -> None:
    raise ValueError(message)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def selected_plan(person: ET.Element) -> ET.Element:
    plans = [item for item in person if local_name(item) == "plan"]
    selected = [item for item in plans if item.get("selected") == "yes"]
    if len(selected) != 1:
        fail(f"Person {person.get('id')} has {len(selected)} selected plans")
    return selected[0]


def parse_time(value: str | None) -> float:
    if value is None or not value.strip():
        fail("Missing time")
    text = value.strip()
    if ":" not in text:
        return float(text)
    parts = [float(item) for item in text.split(":")]
    if len(parts) != 3:
        fail(f"Invalid time: {value}")
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def inspect_target_legs(
    plans: Path, target_people: set[str]
) -> dict[tuple[str, int], dict[str, object]]:
    result: dict[tuple[str, int], dict[str, object]] = {}
    opener = gzip.open if plans.suffix == ".gz" else open
    with opener(plans, "rb") as handle:
        for _, person in ET.iterparse(handle, events=("end",)):
            if local_name(person) != "person":
                continue
            person_id = person.get("id", "")
            if person_id in target_people:
                plan = selected_plan(person)
                leg_index = 0
                for element in plan:
                    if local_name(element) != "leg":
                        continue
                    routes = [item for item in element if local_name(item) == "route"]
                    route = routes[0] if len(routes) == 1 else None
                    result[(person_id, leg_index)] = {
                        "mode": element.get("mode", ""),
                        "departure_time_s": parse_time(element.get("dep_time")),
                        "travel_time_s": parse_time(element.get("trav_time")),
                        "route_vehicle_id": route.get("vehicleRefId", "") if route is not None else "",
                        "route_start_link": route.get("start_link", "") if route is not None else "",
                        "route_end_link": route.get("end_link", "") if route is not None else "",
                    }
                    leg_index += 1
            person.clear()
    return result


def build_bindings(
    people_rows: list[dict[str, str]],
    leg_rows: list[dict[str, str]],
    legacy_rows: list[dict[str, str]],
    inspected: dict[tuple[str, int], dict[str, object]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    pilot_people = {
        row["person_id"]: row
        for row in people_rows
        if row["candidate_tour_status"] == "complete_direct_same_driver"
    }
    if len(pilot_people) != EXPECTED_PEOPLE:
        fail(f"Expected {EXPECTED_PEOPLE} complete direct people, found {len(pilot_people)}")

    accepted_legacy = {
        row["student_person_id"]: row["driver_person_id"]
        for row in legacy_rows
        if row["accepted"].strip().lower() in {"true", "1", "yes"}
    }
    if accepted_legacy != {
        person_id: row["candidate_same_driver_person_id"]
        for person_id, row in pilot_people.items()
    }:
        fail("Complete-direct candidates do not exactly match accepted legacy escorts")

    bindings: list[dict[str, object]] = []
    for row in leg_rows:
        passenger_id = row["person_id"]
        if passenger_id not in pilot_people:
            continue
        passenger_leg_index = int(row["leg_index"])
        driver_id = row["best_driver_person_id"]
        driver_leg_index = int(row["best_driver_leg_index"])
        vehicle_id = row["best_vehicle_id"]
        passenger = inspected.get((passenger_id, passenger_leg_index))
        driver = inspected.get((driver_id, driver_leg_index))
        if passenger is None or driver is None:
            fail(f"Missing inspected plan leg for {passenger_id}/{passenger_leg_index}")
        if passenger["mode"] != "car_passenger" or driver["mode"] != "car":
            fail(f"Mode mismatch for {passenger_id}/{passenger_leg_index}")
        if driver["route_vehicle_id"] != vehicle_id:
            fail(f"Vehicle mismatch for {driver_id}/{driver_leg_index}")
        passenger_departure = float(passenger["departure_time_s"])
        driver_departure = float(driver["departure_time_s"])
        bindings.append(
            {
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
            }
        )

    bindings.sort(key=lambda item: (str(item["passenger_person_id"]), int(item["passenger_leg_index"])))
    if len(bindings) != EXPECTED_LEGS:
        fail(f"Expected {EXPECTED_LEGS} bindings, found {len(bindings)}")
    per_person = Counter(str(item["passenger_person_id"]) for item in bindings)
    if set(per_person.values()) != {2}:
        fail("Every pilot passenger must have exactly two bound legs")
    if any(float(item["passenger_ready_before_driver_s"]) < 0 for item in bindings):
        fail("At least one passenger is not ready before the bound driver departs")
    if any(
        not str(item["passenger_pickup_link"])
        or not str(item["passenger_dropoff_link"])
        for item in bindings
    ):
        fail("At least one passenger binding lacks a real network waypoint")

    summary = {
        "status": "validated_fixed_binding_catalog",
        "scope": "Existing complete direct school_escort pairs only; no new driver tours and no plan innovation",
        "counts": {
            "passenger_people": len(per_person),
            "bound_car_passenger_legs": len(bindings),
            "driver_people": len({str(item["driver_person_id"]) for item in bindings}),
            "private_vehicles": len({str(item["vehicle_id"]) for item in bindings}),
        },
        "timing": {
            "minimum_passenger_ready_before_driver_s": min(
                float(item["passenger_ready_before_driver_s"]) for item in bindings
            ),
            "maximum_passenger_ready_before_driver_s": max(
                float(item["passenger_ready_before_driver_s"]) for item in bindings
            ),
        },
        "implicit_connectors": {
            "maximum_origin_access_gap_m": max(
                float(item["origin_access_gap_m"]) for item in bindings
            ),
            "maximum_destination_egress_gap_m": max(
                float(item["destination_egress_gap_m"]) for item in bindings
            ),
            "modeled_as_separate_walk_legs": False,
        },
        "checks": {
            "exact_139_people": len(per_person) == EXPECTED_PEOPLE,
            "exact_278_legs": len(bindings) == EXPECTED_LEGS,
            "exact_legacy_pair_match": True,
            "two_legs_per_passenger": set(per_person.values()) == {2},
            "all_passengers_ready_before_driver": all(
                float(item["passenger_ready_before_driver_s"]) >= 0 for item in bindings
            ),
            "all_driver_routes_use_bound_vehicle": True,
            "all_bindings_have_pickup_dropoff_links": all(
                bool(item["passenger_pickup_link"])
                and bool(item["passenger_dropoff_link"])
                for item in bindings
            ),
        },
    }
    summary["all_checks_passed"] = all(summary["checks"].values())
    return bindings, summary


def main() -> int:
    args = parse_args()
    people = read_rows(args.candidate_people)
    legs = read_rows(args.candidate_legs)
    legacy = read_rows(args.legacy_assignments)
    pilot_people = {
        row["person_id"]
        for row in people
        if row["candidate_tour_status"] == "complete_direct_same_driver"
    }
    driver_people = {
        row["best_driver_person_id"]
        for row in legs
        if row["person_id"] in pilot_people
    }
    inspected = inspect_target_legs(args.plans, pilot_people | driver_people)
    bindings, summary = build_bindings(people, legs, legacy, inspected)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    bindings_path = args.output_dir / "school_escort_physical_bindings.csv"
    with bindings_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(bindings[0]))
        writer.writeheader()
        writer.writerows(bindings)
    filter_ids = sorted({
        str(item[field])
        for item in bindings
        for field in ("passenger_person_id", "driver_person_id", "vehicle_id")
    })
    (args.output_dir / "school_escort_physical_event_filter_ids.txt").write_text(
        "\n".join(filter_ids) + "\n", encoding="utf-8"
    )
    summary["inputs"] = {
        "plans": str(args.plans),
        "candidate_people": str(args.candidate_people),
        "candidate_legs": str(args.candidate_legs),
        "legacy_assignments": str(args.legacy_assignments),
    }
    summary["output"] = str(bindings_path)
    summary["event_filter_id_count"] = len(filter_ids)
    (args.output_dir / "school_escort_physical_binding_validation.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
