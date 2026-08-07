#!/usr/bin/env python3
"""Audit joint-trip potential across every Hong Kong household with a private car.

This is a read-only geometric/time screen. It does not alter plans, select a
joint trip, route a waypoint tour, or assert final physical feasibility.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from dataclasses import dataclass
import gzip
import json
import math
from pathlib import Path

from lxml import etree as ET


PASSENGER_MODES = {"car_passenger", "pt", "taxi", "walk"}
DRIVER_MODES = {"car", "pt", "taxi", "walk"}
SCHOOL_BUS_MODE = "school_bus"
MAX_CANDIDATES_PER_PASSENGER_TRIP = 3


@dataclass(frozen=True)
class Trip:
    person_id: str
    household_id: str
    trip_index: int
    main_mode: str
    departure_time_s: float
    arrival_time_s: float
    origin_type: str
    destination_type: str
    origin_x: float
    origin_y: float
    destination_x: float
    destination_y: float
    origin_link: str
    destination_link: str

    @property
    def origin(self) -> tuple[float, float]:
        return self.origin_x, self.origin_y

    @property
    def destination(self) -> tuple[float, float]:
        return self.destination_x, self.destination_y


@dataclass(frozen=True)
class PersonRecord:
    person_id: str
    household_id: str
    assigned_vehicle_id: str
    age: int | None
    role: str
    trips: tuple[Trip, ...]
    home_based_day: bool


@dataclass(frozen=True)
class Candidate:
    passenger: Trip
    driver: Trip
    vehicle_id: str
    driver_requires_car_switch: bool
    direct: bool
    departure_delta_s: float
    origin_gap_m: float
    destination_gap_m: float
    detour_added_distance_m: float
    detour_ratio: float

    @property
    def rank(self) -> tuple[object, ...]:
        return (
            0 if self.direct else 1,
            0 if not self.driver_requires_car_switch else 1,
            self.departure_delta_s,
            self.origin_gap_m,
            self.destination_gap_m if self.direct else self.detour_added_distance_m,
            self.driver.person_id,
            self.driver.trip_index,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plans", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def local_name(element: ET._Element) -> str:
    return ET.QName(element).localname


def parse_time(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    hours, minutes, seconds = map(float, value.split(":"))
    result = hours * 3_600 + minutes * 60 + seconds
    return result if math.isfinite(result) and result >= 0 else None


def finite(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def attributes(element: ET._Element) -> dict[str, str]:
    return {
        item.get("name", ""): (item.text or "").strip()
        for block in element
        if local_name(block) == "attributes"
        for item in block
        if local_name(item) == "attribute"
    }


def is_stage(activity: ET._Element) -> bool:
    return (activity.get("type", "").endswith(" interaction"))


def main_mode(legs: list[ET._Element]) -> str:
    routing_modes = []
    for leg in legs:
        attrs = attributes(leg)
        routing_modes.append(attrs.get("routingMode") or leg.get("mode", ""))
    for mode in ("car", "car_passenger", "pt", "taxi", "school_bus", "walk"):
        if mode in routing_modes:
            return mode
    return routing_modes[0] if routing_modes else ""


def trip_from_elements(
    person_id: str,
    household_id: str,
    trip_index: int,
    origin: ET._Element,
    destination: ET._Element,
    between: list[ET._Element],
) -> Trip | None:
    legs = [item for item in between if local_name(item) == "leg"]
    if not legs:
        return None
    departure = parse_time(origin.get("end_time")) or parse_time(legs[0].get("dep_time"))
    travel_times = []
    for leg in legs:
        value = parse_time(leg.get("trav_time"))
        if value is None:
            routes = [item for item in leg if local_name(item) == "route"]
            value = parse_time(routes[0].get("trav_time")) if len(routes) == 1 else None
        if value is None:
            return None
        travel_times.append(value)
    coords = (
        finite(origin.get("x")), finite(origin.get("y")),
        finite(destination.get("x")), finite(destination.get("y")),
    )
    if departure is None or any(value is None for value in coords):
        return None
    return Trip(
        person_id=person_id,
        household_id=household_id,
        trip_index=trip_index,
        main_mode=main_mode(legs),
        departure_time_s=departure,
        arrival_time_s=departure + sum(travel_times),
        origin_type=origin.get("type", ""),
        destination_type=destination.get("type", ""),
        origin_x=float(coords[0]),
        origin_y=float(coords[1]),
        destination_x=float(coords[2]),
        destination_y=float(coords[3]),
        origin_link=origin.get("link", ""),
        destination_link=destination.get("link", ""),
    )


def selected_plan(person: ET._Element) -> ET._Element:
    plans = [item for item in person if local_name(item) == "plan"]
    selected = [item for item in plans if item.get("selected") == "yes"]
    if len(selected) == 1:
        return selected[0]
    if len(plans) == 1:
        return plans[0]
    raise ValueError(f"Selected plan unresolved for {person.get('id', '')}")


def parse_person(person: ET._Element) -> PersonRecord | None:
    attrs = attributes(person)
    household_id = attrs.get("householdId", "")
    if not household_id:
        return None
    plan = selected_plan(person)
    elements = [item for item in plan if local_name(item) in {"activity", "leg"}]
    main_activity_indexes = [
        index for index, item in enumerate(elements)
        if local_name(item) == "activity" and not is_stage(item)
    ]
    trips: list[Trip] = []
    for trip_index, (start, end) in enumerate(zip(
        main_activity_indexes, main_activity_indexes[1:], strict=False
    )):
        trip = trip_from_elements(
            person.get("id", ""), household_id, trip_index,
            elements[start], elements[end], elements[start + 1:end],
        )
        if trip is not None:
            trips.append(trip)
    age_text = attrs.get("age", "")
    age = int(float(age_text)) if age_text else None
    home_based = bool(main_activity_indexes) and (
        elements[main_activity_indexes[0]].get("type", "") == "home"
        and elements[main_activity_indexes[-1]].get("type", "") == "home"
    )
    return PersonRecord(
        person_id=person.get("id", ""),
        household_id=household_id,
        assigned_vehicle_id=attrs.get("assignedVehicleId", "").strip(),
        age=age,
        role=attrs.get("role", ""),
        trips=tuple(trips),
        home_based_day=home_based,
    )


def distance(first: tuple[float, float], second: tuple[float, float]) -> float:
    return math.hypot(first[0] - second[0], first[1] - second[1])


def assess(passenger: Trip, driver: Trip, vehicle_id: str) -> Candidate | None:
    departure_delta = abs(passenger.departure_time_s - driver.departure_time_s)
    origin_gap = distance(passenger.origin, driver.origin)
    destination_gap = distance(passenger.destination, driver.destination)
    driver_direct = max(distance(driver.origin, driver.destination), 1.0)
    via_passenger = (
        distance(driver.origin, passenger.origin)
        + distance(passenger.origin, passenger.destination)
        + distance(passenger.destination, driver.destination)
    )
    added = max(0.0, via_passenger - driver_direct)
    ratio = via_passenger / driver_direct
    direct = departure_delta <= 1_800 and origin_gap <= 500 and destination_gap <= 500
    detour = (
        departure_delta <= 2_700
        and added <= 8_000
        and ratio <= 1.5
    )
    if not direct and not detour:
        return None
    return Candidate(
        passenger=passenger,
        driver=driver,
        vehicle_id=vehicle_id,
        driver_requires_car_switch=driver.main_mode != "car",
        direct=direct,
        departure_delta_s=departure_delta,
        origin_gap_m=origin_gap,
        destination_gap_m=destination_gap,
        detour_added_distance_m=added,
        detour_ratio=ratio,
    )


def main() -> int:
    args = parse_args()
    if args.output_dir.exists():
        raise FileExistsError(args.output_dir)
    households: dict[str, list[PersonRecord]] = defaultdict(list)
    parse_counts: Counter[str] = Counter()
    with gzip.open(args.plans, "rb") as handle:
        context = ET.iterparse(handle, events=("end",), tag="person", huge_tree=True)
        for _, person in context:
            parse_counts["persons"] += 1
            record = parse_person(person)
            if record is not None:
                households[record.household_id].append(record)
                parse_counts["persons_with_household"] += 1
                parse_counts["main_trips"] += len(record.trips)
            person.clear()
            parent = person.getparent()
            if parent is not None:
                while person.getprevious() is not None:
                    del parent[0]

    rows: list[dict[str, object]] = []
    counts: Counter[str] = Counter()
    candidate_households: set[str] = set()
    candidate_people: set[str] = set()
    for household_id, people in households.items():
        drivers = [
            person for person in people
            if person.assigned_vehicle_id and person.home_based_day
            and person.age is not None and person.age >= 18
        ]
        if not drivers:
            continue
        counts["car_households"] += 1
        counts["eligible_driver_people"] += len(drivers)
        passenger_trips = [
            trip for person in people for trip in person.trips
            if trip.main_mode in PASSENGER_MODES
        ]
        counts["eligible_passenger_trips_before_screen"] += len(passenger_trips)
        for passenger in passenger_trips:
            if passenger.origin_link == passenger.destination_link:
                counts["excluded_same_pickup_dropoff_link"] += 1
                counts[f"excluded_same_pickup_dropoff_link::{passenger.main_mode}"] += 1
                continue
            possible: list[Candidate] = []
            for driver_person in drivers:
                if driver_person.person_id == passenger.person_id:
                    continue
                for driver_trip in driver_person.trips:
                    if driver_trip.main_mode not in DRIVER_MODES:
                        continue
                    candidate = assess(
                        passenger, driver_trip, driver_person.assigned_vehicle_id
                    )
                    if candidate is not None:
                        possible.append(candidate)
            possible.sort(key=lambda item: item.rank)
            retained = possible[:MAX_CANDIDATES_PER_PASSENGER_TRIP]
            if not retained:
                counts[f"no_candidate::{passenger.main_mode}"] += 1
                continue
            counts[f"candidate_passenger_trips::{passenger.main_mode}"] += 1
            if len(possible) > len(retained):
                counts["passenger_trips_truncated_to_top3"] += 1
            candidate_households.add(household_id)
            candidate_people.add(passenger.person_id)
            for rank, candidate in enumerate(retained, start=1):
                counts["candidate_pairs"] += 1
                counts[f"candidate_pairs_by_passenger::{passenger.main_mode}"] += 1
                counts[f"candidate_pairs_by_driver::{candidate.driver.main_mode}"] += 1
                counts[
                    "candidate_pairs_requiring_driver_car_switch"
                    if candidate.driver_requires_car_switch
                    else "candidate_pairs_reusing_driver_car"
                ] += 1
                rows.append({
                    "candidate_id": (
                        f"joint:{household_id}:{passenger.person_id}:"
                        f"{passenger.trip_index}:{rank}"
                    ),
                    "household_id": household_id,
                    "passenger_person_id": passenger.person_id,
                    "passenger_trip_index": passenger.trip_index,
                    "passenger_original_mode": passenger.main_mode,
                    "driver_person_id": candidate.driver.person_id,
                    "driver_trip_index": candidate.driver.trip_index,
                    "driver_original_mode": candidate.driver.main_mode,
                    "driver_vehicle_id": candidate.vehicle_id,
                    "driver_requires_car_switch": str(
                        candidate.driver_requires_car_switch
                    ).lower(),
                    "screen_type": "direct" if candidate.direct else "detour",
                    "departure_delta_s": candidate.departure_delta_s,
                    "origin_gap_m": candidate.origin_gap_m,
                    "destination_gap_m": candidate.destination_gap_m,
                    "detour_added_distance_m": candidate.detour_added_distance_m,
                    "detour_ratio": candidate.detour_ratio,
                    "passenger_departure_time_s": passenger.departure_time_s,
                    "driver_departure_time_s": candidate.driver.departure_time_s,
                    "passenger_pickup_link": passenger.origin_link,
                    "passenger_dropoff_link": passenger.destination_link,
                    "driver_origin_link": candidate.driver.origin_link,
                    "driver_destination_link": candidate.driver.destination_link,
                })

    args.output_dir.mkdir(parents=True)
    candidate_path = args.output_dir / "household_joint_plan_potential_candidates.csv"
    if rows:
        with candidate_path.open("x", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    summary = {
        "status": "audited_read_only_household_joint_plan_potential",
        "scope": (
            "All households with an adult assigned vehicle holder and a home-based "
            "day; passenger modes car_passenger/PT/Taxi/walk; school_bus excluded"
        ),
        "thresholds": {
            "direct_departure_tolerance_s": 1_800,
            "direct_origin_radius_m": 500,
            "direct_destination_radius_m": 500,
            "detour_departure_tolerance_s": 2_700,
            "detour_max_added_distance_m": 8_000,
            "detour_max_ratio": 1.5,
            "max_candidates_per_passenger_trip": MAX_CANDIDATES_PER_PASSENGER_TRIP,
        },
        "parse_counts": dict(sorted(parse_counts.items())),
        "counts": dict(sorted(counts.items())),
        "candidate_households": len(candidate_households),
        "candidate_passenger_people": len(candidate_people),
        "candidate_rows": len(rows),
		"limitations": [
			"This is a geometric/time screen, not routed waypoint feasibility.",
            "Passenger trips whose pickup and drop-off resolve to the same network link are excluded because QSim cannot represent distinct boarding and alighting waypoints for them.",
            "A non-Car driver candidate requires switching the complete home-based day tour to Car during plan construction.",
            "School-bus trips are counted outside the open passenger modes and are not candidates in this phase.",
            "No plan is added or selected by this audit.",
        ],
        "inputs": {"plans": str(args.plans)},
        "output": str(candidate_path),
    }
    (args.output_dir / "household_joint_plan_potential_audit.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
