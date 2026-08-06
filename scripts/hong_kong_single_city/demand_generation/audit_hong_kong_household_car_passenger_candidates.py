#!/usr/bin/env python3
"""Audit real household-driver candidates for Stage 11 car-passenger legs.

The audit is deliberately read-only.  A real driver is a different simulated
member of the same household who owns an assigned private-car vehicle and has
an existing routed ``mode=car`` leg using that vehicle.  Candidate coverage is
reported at progressively stronger levels; no passenger is bound and no plan
is changed.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
from lxml import etree as ET


EXPECTED_CAR_PASSENGER_LEGS = 2_734
EXPECTED_STUDENT_LEGS = 2_490
EXPECTED_ADULT_LEGS = 244
EXPECTED_STUDENT_SWAP_LEGS = 1_912
EXPECTED_STUDENT_RETAINED_LEGS = 578


class AuditError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise AuditError(message)


def local_name(element: ET._Element) -> str:
    return ET.QName(element).localname


def direct_children(element: ET._Element, name: str) -> list[ET._Element]:
    return [child for child in element if local_name(child) == name]


def selected_plan(person: ET._Element) -> ET._Element:
    plans = direct_children(person, "plan")
    selected = [plan for plan in plans if plan.get("selected") == "yes"]
    if len(selected) == 1:
        return selected[0]
    if len(plans) == 1:
        return plans[0]
    fail(f"Selected plan unresolved for {person.get('id', '')}")


def named_attributes(element: ET._Element) -> dict[str, str]:
    blocks = direct_children(element, "attributes")
    if not blocks:
        return {}
    if len(blocks) != 1:
        fail(f"Duplicate attributes blocks on {local_name(element)}")
    result: dict[str, str] = {}
    for attribute in direct_children(blocks[0], "attribute"):
        name = attribute.get("name", "")
        if not name or name in result:
            fail(f"Invalid or duplicate attribute name {name!r}")
        result[name] = (attribute.text or "").strip()
    return result


def parse_time_seconds(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    parts = value.strip().split(":")
    if len(parts) != 3:
        fail(f"Invalid MATSim time {value!r}")
    hours, minutes, seconds = map(float, parts)
    parsed = hours * 3600 + minutes * 60 + seconds
    if not math.isfinite(parsed) or parsed < 0:
        fail(f"Invalid MATSim time {value!r}")
    return parsed


def finite_float(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def distance_m(first: tuple[float, float], second: tuple[float, float]) -> float:
    return math.hypot(first[0] - second[0], first[1] - second[1])


@dataclass(frozen=True)
class TripLeg:
    person_id: str
    household_id: str
    role: str
    leg_index: int
    mode: str
    assigned_vehicle_id: str
    route_vehicle_id: str
    departure_time_s: float
    travel_time_s: float
    origin_type: str
    origin_facility_id: str
    origin_x: float
    origin_y: float
    destination_type: str
    destination_facility_id: str
    destination_x: float
    destination_y: float
    route_distance_m: float

    @property
    def arrival_time_s(self) -> float:
        return self.departure_time_s + self.travel_time_s

    @property
    def origin(self) -> tuple[float, float]:
        return self.origin_x, self.origin_y

    @property
    def destination(self) -> tuple[float, float]:
        return self.destination_x, self.destination_y


@dataclass(frozen=True)
class Thresholds:
    direct_departure_tolerance_s: float = 15 * 60
    direct_arrival_tolerance_s: float = 15 * 60
    direct_origin_radius_m: float = 500
    direct_destination_radius_m: float = 500
    detour_departure_tolerance_s: float = 30 * 60
    detour_origin_radius_m: float = 500
    detour_max_added_distance_m: float = 5_000
    detour_max_ratio: float = 1.5


@dataclass(frozen=True)
class Candidate:
    driver: TripLeg
    departure_delta_s: float
    arrival_delta_s: float
    origin_gap_m: float
    destination_gap_m: float
    detour_added_distance_m: float
    detour_ratio: float
    direct: bool
    detour_screen: bool

    @property
    def rank(self) -> tuple[float, ...]:
        return (
            0 if self.direct else 1,
            self.departure_delta_s,
            self.origin_gap_m,
            self.destination_gap_m if self.direct else self.detour_added_distance_m,
            self.driver.person_id,
            self.driver.leg_index,
        )


def clear_element(element: ET._Element) -> None:
    element.clear()
    parent = element.getparent()
    if parent is not None:
        while element.getprevious() is not None:
            del parent[0]


def leg_from_elements(
    person_id: str,
    household_id: str,
    role: str,
    assigned_vehicle_id: str,
    leg_index: int,
    origin: ET._Element,
    leg: ET._Element,
    destination: ET._Element,
) -> TripLeg | None:
    departure = parse_time_seconds(leg.get("dep_time"))
    if departure is None:
        departure = parse_time_seconds(origin.get("end_time"))
    travel_time = parse_time_seconds(leg.get("trav_time"))
    routes = direct_children(leg, "route")
    if travel_time is None and len(routes) == 1:
        travel_time = parse_time_seconds(routes[0].get("trav_time"))
    origin_x = finite_float(origin.get("x"))
    origin_y = finite_float(origin.get("y"))
    destination_x = finite_float(destination.get("x"))
    destination_y = finite_float(destination.get("y"))
    if None in {
        departure,
        travel_time,
        origin_x,
        origin_y,
        destination_x,
        destination_y,
    }:
        return None
    route_distance = 0.0
    route_vehicle_id = ""
    if len(routes) == 1:
        route_distance = finite_float(routes[0].get("distance")) or 0.0
        route_vehicle_id = routes[0].get("vehicleRefId", "")
    elif len(routes) > 1:
        fail(f"Multiple routes on {person_id}/{leg_index}")
    return TripLeg(
        person_id=person_id,
        household_id=household_id,
        role=role,
        leg_index=leg_index,
        mode=leg.get("mode", ""),
        assigned_vehicle_id=assigned_vehicle_id,
        route_vehicle_id=route_vehicle_id,
        departure_time_s=float(departure),
        travel_time_s=float(travel_time),
        origin_type=origin.get("type", ""),
        origin_facility_id=origin.get("facility", ""),
        origin_x=float(origin_x),
        origin_y=float(origin_y),
        destination_type=destination.get("type", ""),
        destination_facility_id=destination.get("facility", ""),
        destination_x=float(destination_x),
        destination_y=float(destination_y),
        route_distance_m=float(route_distance),
    )


def parse_plans(path: Path) -> tuple[list[TripLeg], list[TripLeg], dict[str, int]]:
    passengers: list[TripLeg] = []
    driver_legs: list[TripLeg] = []
    counters: Counter[str] = Counter()
    with gzip.open(path, "rb") as handle:
        context = ET.iterparse(handle, events=("end",), tag="person", huge_tree=True)
        for _, person in context:
            counters["persons"] += 1
            person_id = person.get("id", "")
            attributes = named_attributes(person)
            household_id = attributes.get("householdId", "")
            role = attributes.get("role", "")
            assigned_vehicle_id = attributes.get("assignedVehicleId", "")
            plan = selected_plan(person)
            elements = [
                element
                for element in plan
                if local_name(element) in {"activity", "leg"}
            ]
            leg_index = 0
            for index, element in enumerate(elements):
                if local_name(element) != "leg":
                    continue
                if index == 0 or index + 1 >= len(elements):
                    fail(f"Leg lacks adjacent activities: {person_id}/{leg_index}")
                origin, destination = elements[index - 1], elements[index + 1]
                if local_name(origin) != "activity" or local_name(destination) != "activity":
                    fail(f"Plan is not alternating around {person_id}/{leg_index}")
                mode = element.get("mode", "")
                if mode in {"car", "car_passenger"}:
                    parsed = leg_from_elements(
                        person_id,
                        household_id,
                        role,
                        assigned_vehicle_id,
                        leg_index,
                        origin,
                        element,
                        destination,
                    )
                    if parsed is None:
                        counters[f"unusable_{mode}_legs"] += 1
                    elif mode == "car_passenger":
                        passengers.append(parsed)
                    else:
                        driver_legs.append(parsed)
                leg_index += 1
            clear_element(person)
    counters["car_passenger_legs"] = len(passengers)
    counters["car_legs"] = len(driver_legs)
    return passengers, driver_legs, dict(sorted(counters.items()))


def parse_vehicle_catalog(path: Path) -> tuple[dict[str, str], dict[str, int]]:
    tree = ET.parse(str(path)) if path.suffix != ".gz" else None
    if tree is None:
        with gzip.open(path, "rb") as handle:
            tree = ET.parse(handle)
    root = tree.getroot()
    type_seats: dict[str, int] = {}
    vehicle_types: dict[str, str] = {}
    for element in root.iter():
        name = local_name(element)
        if name == "vehicleType":
            type_id = element.get("id", "")
            capacities = [item for item in element.iter() if local_name(item) == "capacity"]
            if len(capacities) != 1:
                fail(f"Vehicle type {type_id} has invalid capacity")
            type_seats[type_id] = int(capacities[0].get("seats", "0"))
        elif name == "vehicle":
            vehicle_types[element.get("id", "")] = element.get("type", "")
    if not vehicle_types or "private_car" not in type_seats:
        fail("Private-vehicle catalog is incomplete")
    return vehicle_types, type_seats


def valid_driver_legs(
    driver_legs: Iterable[TripLeg], vehicle_types: dict[str, str]
) -> tuple[list[TripLeg], dict[str, int]]:
    accepted: list[TripLeg] = []
    counters: Counter[str] = Counter()
    for leg in driver_legs:
        vehicle_id = leg.assigned_vehicle_id
        if not leg.household_id:
            counters["missing_household"] += 1
        elif not vehicle_id:
            counters["missing_assigned_vehicle"] += 1
        elif vehicle_types.get(vehicle_id) != "private_car":
            counters[f"excluded_vehicle_type::{vehicle_types.get(vehicle_id, 'missing')}"] += 1
        elif leg.route_vehicle_id != vehicle_id:
            counters["route_vehicle_mismatch"] += 1
        else:
            accepted.append(leg)
            counters["accepted_private_car_legs"] += 1
    return accepted, dict(sorted(counters.items()))


def assess_candidate(
    passenger: TripLeg, driver: TripLeg, thresholds: Thresholds
) -> Candidate:
    departure_delta = abs(passenger.departure_time_s - driver.departure_time_s)
    arrival_delta = abs(passenger.arrival_time_s - driver.arrival_time_s)
    origin_gap = distance_m(passenger.origin, driver.origin)
    destination_gap = distance_m(passenger.destination, driver.destination)
    driver_direct = max(distance_m(driver.origin, driver.destination), 1.0)
    via_passenger = (
        distance_m(driver.origin, passenger.destination)
        + distance_m(passenger.destination, driver.destination)
    )
    detour_added = max(0.0, via_passenger - driver_direct)
    detour_ratio = via_passenger / driver_direct
    direct = (
        departure_delta <= thresholds.direct_departure_tolerance_s
        and arrival_delta <= thresholds.direct_arrival_tolerance_s
        and origin_gap <= thresholds.direct_origin_radius_m
        and destination_gap <= thresholds.direct_destination_radius_m
    )
    detour_screen = (
        departure_delta <= thresholds.detour_departure_tolerance_s
        and origin_gap <= thresholds.detour_origin_radius_m
        and detour_added <= thresholds.detour_max_added_distance_m
        and detour_ratio <= thresholds.detour_max_ratio
    )
    return Candidate(
        driver=driver,
        departure_delta_s=departure_delta,
        arrival_delta_s=arrival_delta,
        origin_gap_m=origin_gap,
        destination_gap_m=destination_gap,
        detour_added_distance_m=detour_added,
        detour_ratio=detour_ratio,
        direct=direct,
        detour_screen=detour_screen,
    )


def classify_passengers(
    passengers: Iterable[TripLeg],
    drivers: Iterable[TripLeg],
    thresholds: Thresholds,
) -> tuple[list[dict[str, Any]], dict[tuple[str, int], set[str]], dict[tuple[str, int], set[str]]]:
    by_household: dict[str, list[TripLeg]] = defaultdict(list)
    for driver in drivers:
        by_household[driver.household_id].append(driver)
    rows: list[dict[str, Any]] = []
    direct_sets: dict[tuple[str, int], set[str]] = {}
    default_sets: dict[tuple[str, int], set[str]] = {}
    for passenger in passengers:
        household_drivers = [
            driver
            for driver in by_household.get(passenger.household_id, [])
            if driver.person_id != passenger.person_id
        ]
        assessments = [
            assess_candidate(passenger, driver, thresholds)
            for driver in household_drivers
        ]
        direct = sorted((item for item in assessments if item.direct), key=lambda x: x.rank)
        detour = sorted(
            (item for item in assessments if item.detour_screen), key=lambda x: x.rank
        )
        key = (passenger.person_id, passenger.leg_index)
        direct_sets[key] = {item.driver.person_id for item in direct}
        default_sets[key] = {item.driver.person_id for item in detour}
        best = direct[0] if direct else (detour[0] if detour else None)
        if direct:
            status = "existing_car_leg_direct"
        elif detour:
            status = "existing_car_leg_detour_screen"
        elif household_drivers:
            status = "real_driver_no_compatible_existing_leg"
        else:
            status = "no_real_driver_current_plan"
        row = asdict(passenger)
        row.update(
            {
                "arrival_time_s": passenger.arrival_time_s,
                "real_driver_person_count": len(
                    {item.person_id for item in household_drivers}
                ),
                "real_driver_leg_count": len(household_drivers),
                "direct_candidate_count": len(direct),
                "detour_candidate_count": len(detour),
                "candidate_status": status,
                "best_driver_person_id": best.driver.person_id if best else "",
                "best_driver_leg_index": best.driver.leg_index if best else "",
                "best_vehicle_id": best.driver.assigned_vehicle_id if best else "",
                "best_departure_delta_s": best.departure_delta_s if best else "",
                "best_arrival_delta_s": best.arrival_delta_s if best else "",
                "best_origin_gap_m": best.origin_gap_m if best else "",
                "best_destination_gap_m": best.destination_gap_m if best else "",
                "best_detour_added_distance_m": (
                    best.detour_added_distance_m if best else ""
                ),
                "best_detour_ratio": best.detour_ratio if best else "",
            }
        )
        rows.append(row)
    return rows, direct_sets, default_sets


def source_labels(
    rows: list[dict[str, Any]], swap_pairs: Path, selected_adults: Path
) -> None:
    swap_ids = set(pd.read_csv(swap_pairs)["donor_person_id"].astype(str))
    adult_ids = set(pd.read_csv(selected_adults)["person_id"].astype(str))
    for row in rows:
        person_id = str(row["person_id"])
        if person_id in adult_ids:
            source = "adult_retained_private_car_passenger_van"
        elif person_id in swap_ids:
            source = "student_swap_car_household_donor"
        else:
            source = "student_original_private_vehicle_retained"
        row["allocation_source"] = source


def add_resident_metadata(rows: list[dict[str, Any]], residents_path: Path) -> None:
    residents = pd.read_parquet(
        residents_path,
        columns=[
            "person_id",
            "household_private_vehicle_count",
            "student_stage",
            "age",
            "sex",
            "relationship_role",
            "is_designated_driver",
        ],
    ).set_index("person_id")
    missing = {str(row["person_id"]) for row in rows} - set(residents.index.astype(str))
    if missing:
        fail(f"Car-passenger people missing from resident metadata: {len(missing)}")
    for row in rows:
        metadata = residents.loc[str(row["person_id"])]
        row["household_private_vehicle_count"] = int(
            metadata["household_private_vehicle_count"]
        )
        row["student_stage"] = "" if pd.isna(metadata["student_stage"]) else str(metadata["student_stage"])
        row["age"] = int(metadata["age"])
        row["sex"] = str(metadata["sex"])
        row["relationship_role"] = str(metadata["relationship_role"])
        row["is_designated_driver"] = bool(metadata["is_designated_driver"])


def person_rows(
    leg_rows: list[dict[str, Any]],
    direct_sets: dict[tuple[str, int], set[str]],
    default_sets: dict[tuple[str, int], set[str]],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in leg_rows:
        grouped[str(row["person_id"])].append(row)
    result: list[dict[str, Any]] = []
    for person_id, rows in sorted(grouped.items()):
        rows.sort(key=lambda item: int(item["leg_index"]))
        direct = [direct_sets[(person_id, int(row["leg_index"]))] for row in rows]
        default = [default_sets[(person_id, int(row["leg_index"]))] for row in rows]
        common_direct = set.intersection(*direct) if direct else set()
        common_default = set.intersection(*default) if default else set()
        all_default = bool(default) and all(default)
        any_default = any(default)
        has_real_driver = any(int(row["real_driver_person_count"]) > 0 for row in rows)
        if common_direct:
            status = "complete_direct_same_driver"
        elif common_default:
            status = "complete_detour_screen_same_driver"
        elif all_default:
            status = "complete_detour_screen_different_drivers"
        elif any_default:
            status = "partial_compatible_existing_legs"
        elif has_real_driver:
            status = "real_driver_no_compatible_tour"
        else:
            status = "no_real_driver_current_plan"
        first = rows[0]
        result.append(
            {
                "person_id": person_id,
                "household_id": first["household_id"],
                "role": first["role"],
                "allocation_source": first["allocation_source"],
                "student_stage": first["student_stage"],
                "age": first["age"],
                "sex": first["sex"],
                "relationship_role": first["relationship_role"],
                "household_private_vehicle_count": first[
                    "household_private_vehicle_count"
                ],
                "car_passenger_leg_count": len(rows),
                "compatible_leg_count": sum(bool(item) for item in default),
                "direct_leg_count": sum(bool(item) for item in direct),
                "common_direct_driver_count": len(common_direct),
                "common_detour_screen_driver_count": len(common_default),
                "candidate_tour_status": status,
                "candidate_same_driver_person_id": (
                    sorted(common_direct or common_default)[0]
                    if common_direct or common_default
                    else ""
                ),
            }
        )
    return result


def crosscheck_school_escorts(
    people: list[dict[str, Any]], assignments_path: Path
) -> dict[str, Any]:
    assignments = pd.read_csv(assignments_path)
    required = {"student_person_id", "driver_person_id", "accepted"}
    if not required <= set(assignments.columns):
        fail(f"School-escort audit lacks columns: {sorted(required - set(assignments.columns))}")
    accepted = assignments.loc[assignments["accepted"].astype(bool)].copy()
    accepted_pairs = dict(
        zip(
            accepted["student_person_id"].astype(str),
            accepted["driver_person_id"].astype(str),
            strict=True,
        )
    )
    direct_pairs = {
        str(row["person_id"]): str(row["candidate_same_driver_person_id"])
        for row in people
        if row["candidate_tour_status"] == "complete_direct_same_driver"
    }
    accepted_ids = set(accepted_pairs)
    direct_ids = set(direct_pairs)
    driver_mismatches = sorted(
        person_id
        for person_id in accepted_ids & direct_ids
        if accepted_pairs[person_id] != direct_pairs[person_id]
    )
    result = {
        "accepted_legacy_school_escort_people": len(accepted_ids),
        "complete_direct_same_driver_people": len(direct_ids),
        "person_id_intersection": len(accepted_ids & direct_ids),
        "accepted_only": len(accepted_ids - direct_ids),
        "direct_only": len(direct_ids - accepted_ids),
        "driver_id_mismatches": len(driver_mismatches),
        "exact_match": (
            accepted_ids == direct_ids and not driver_mismatches
        ),
    }
    if not result["exact_match"]:
        fail(f"Legacy school-escort cross-check failed: {result}")
    return result


def count_by(rows: Iterable[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(str(row[key]) for row in rows).items()))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        fail(f"Cannot write empty audit {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def build_summary(
    plans: Path,
    vehicles: Path,
    residents: Path,
    school_escort_assignments: Path,
    leg_rows: list[dict[str, Any]],
    people: list[dict[str, Any]],
    parse_counts: dict[str, int],
    driver_counts: dict[str, int],
    type_seats: dict[str, int],
    thresholds: Thresholds,
    escort_crosscheck: dict[str, Any],
) -> dict[str, Any]:
    role_counts = count_by(leg_rows, "role")
    source_counts = count_by(leg_rows, "allocation_source")
    status_counts = count_by(leg_rows, "candidate_status")
    person_status_counts = count_by(people, "candidate_tour_status")
    checks = {
        "car_passenger_leg_count_exact": len(leg_rows) == EXPECTED_CAR_PASSENGER_LEGS,
        "student_leg_count_exact": role_counts.get("day_school_student", 0) == EXPECTED_STUDENT_LEGS,
        "adult_leg_count_exact": role_counts.get("fixed_worker", 0) == EXPECTED_ADULT_LEGS,
        "student_swap_leg_count_exact": source_counts.get("student_swap_car_household_donor", 0) == EXPECTED_STUDENT_SWAP_LEGS,
        "student_retained_leg_count_exact": source_counts.get("student_original_private_vehicle_retained", 0) == EXPECTED_STUDENT_RETAINED_LEGS,
        "all_passengers_have_household": all(bool(row["household_id"]) for row in leg_rows),
        "all_passengers_from_car_households": all(int(row["household_private_vehicle_count"]) > 0 for row in leg_rows),
        "all_passenger_legs_have_route_time_and_coordinates": parse_counts.get("unusable_car_passenger_legs", 0) == 0,
        "private_car_has_four_passenger_seats": type_seats.get("private_car") == 5,
        "complete_direct_tours_match_legacy_school_escort_assignments": escort_crosscheck[
            "exact_match"
        ],
    }
    if not all(checks.values()):
        fail(f"Household candidate audit checks failed: {checks}")
    compatible_leg_count = sum(
        row["candidate_status"]
        in {"existing_car_leg_direct", "existing_car_leg_detour_screen"}
        for row in leg_rows
    )
    direct_leg_count = status_counts.get("existing_car_leg_direct", 0)
    complete_tour_people = sum(
        status in {
            "complete_direct_same_driver",
            "complete_detour_screen_same_driver",
        }
        for status in (str(row["candidate_tour_status"]) for row in people)
    )
    real_driver_leg_count = len(leg_rows) - status_counts.get(
        "no_real_driver_current_plan", 0
    )
    return {
        "status": "validated_read_only_candidate_audit",
        "scope": "Stage 11 no-ride car_passenger legs only; no plans or bindings changed",
        "inputs": {
            "plans": str(plans),
            "private_vehicles": str(vehicles),
            "resident_agents": str(residents),
            "school_escort_assignments": str(school_escort_assignments),
        },
        "definition": {
            "real_driver": "A different member of the same household with an assigned private_car, an existing routed mode=car leg, and matching route vehicleRefId.",
            "direct": "Existing car leg within the direct departure/arrival and origin/destination thresholds.",
            "detour_screen": "Existing car leg with a compatible departure and origin whose straight-line passenger drop-off detour satisfies the configured added-distance and ratio thresholds; this is screening, not a routed joint plan.",
        },
        "thresholds": asdict(thresholds),
        "counts": {
            "car_passenger_legs": len(leg_rows),
            "car_passenger_people": len(people),
            "car_passenger_households": len({row["household_id"] for row in leg_rows}),
            "direct_existing_car_leg_candidates": direct_leg_count,
            "direct_or_detour_screen_candidates": compatible_leg_count,
            "legs_with_real_driver_but_no_compatible_existing_leg": status_counts.get("real_driver_no_compatible_existing_leg", 0),
            "legs_without_real_driver_in_current_plan": status_counts.get("no_real_driver_current_plan", 0),
            "people_with_complete_same_driver_round_trip": complete_tour_people,
        },
        "coverage_percent": {
            "legs_with_real_driver_in_current_plan": 100 * real_driver_leg_count / len(leg_rows),
            "direct_existing_car_leg_candidates": 100 * direct_leg_count / len(leg_rows),
            "direct_or_detour_screen_candidates": 100 * compatible_leg_count / len(leg_rows),
            "people_with_complete_same_driver_round_trip": 100 * complete_tour_people / len(people),
        },
        "leg_status_counts": status_counts,
        "person_tour_status_counts": person_status_counts,
        "leg_role_counts": role_counts,
        "leg_allocation_source_counts": source_counts,
        "plan_parse_counts": parse_counts,
        "driver_validation_counts": driver_counts,
        "legacy_school_escort_crosscheck": escort_crosscheck,
        "checks": checks,
        "all_checks_passed": True,
        "limitations": [
            "Candidate status does not bind a passenger, alter a plan, or prove that a driver will accept the joint trip.",
            "Detour screening uses activity coordinates and does not replace routed network detour, schedule, score, or vehicle-conflict validation.",
            "The audit counts existing driver plans only; creating a new escort tour is outside this step.",
            "Vehicle capacity is known (five seats including the driver), but simultaneous sibling allocation is deferred until joint-plan construction.",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plans", type=Path, required=True)
    parser.add_argument("--private-vehicles", type=Path, required=True)
    parser.add_argument("--resident-agents", type=Path, required=True)
    parser.add_argument("--student-swap-pairs", type=Path, required=True)
    parser.add_argument("--selected-adults", type=Path, required=True)
    parser.add_argument("--school-escort-assignments", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--direct-departure-tolerance-min", type=float, default=15)
    parser.add_argument("--direct-arrival-tolerance-min", type=float, default=15)
    parser.add_argument("--direct-origin-radius-m", type=float, default=500)
    parser.add_argument("--direct-destination-radius-m", type=float, default=500)
    parser.add_argument("--detour-departure-tolerance-min", type=float, default=30)
    parser.add_argument("--detour-origin-radius-m", type=float, default=500)
    parser.add_argument("--detour-max-added-distance-m", type=float, default=5_000)
    parser.add_argument("--detour-max-ratio", type=float, default=1.5)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    inputs = [
        args.plans,
        args.private_vehicles,
        args.resident_agents,
        args.student_swap_pairs,
        args.selected_adults,
        args.school_escort_assignments,
    ]
    for path in inputs:
        if not path.is_file():
            fail(f"Required input is missing: {path}")
    if args.output_dir.exists():
        fail(f"Output directory already exists: {args.output_dir}")
    thresholds = Thresholds(
        direct_departure_tolerance_s=args.direct_departure_tolerance_min * 60,
        direct_arrival_tolerance_s=args.direct_arrival_tolerance_min * 60,
        direct_origin_radius_m=args.direct_origin_radius_m,
        direct_destination_radius_m=args.direct_destination_radius_m,
        detour_departure_tolerance_s=args.detour_departure_tolerance_min * 60,
        detour_origin_radius_m=args.detour_origin_radius_m,
        detour_max_added_distance_m=args.detour_max_added_distance_m,
        detour_max_ratio=args.detour_max_ratio,
    )
    if any(value <= 0 for value in asdict(thresholds).values()):
        fail("All candidate thresholds must be positive")
    passengers, all_car_legs, parse_counts = parse_plans(args.plans)
    vehicle_types, type_seats = parse_vehicle_catalog(args.private_vehicles)
    drivers, driver_counts = valid_driver_legs(all_car_legs, vehicle_types)
    leg_rows, direct_sets, default_sets = classify_passengers(
        passengers, drivers, thresholds
    )
    source_labels(leg_rows, args.student_swap_pairs, args.selected_adults)
    add_resident_metadata(leg_rows, args.resident_agents)
    people = person_rows(leg_rows, direct_sets, default_sets)
    escort_crosscheck = crosscheck_school_escorts(
        people, args.school_escort_assignments
    )
    summary = build_summary(
        args.plans,
        args.private_vehicles,
        args.resident_agents,
        args.school_escort_assignments,
        leg_rows,
        people,
        parse_counts,
        driver_counts,
        type_seats,
        thresholds,
        escort_crosscheck,
    )
    args.output_dir.mkdir(parents=True)
    write_csv(args.output_dir / "car_passenger_candidate_legs.csv", leg_rows)
    write_csv(args.output_dir / "car_passenger_candidate_people.csv", people)
    with (args.output_dir / "household_candidate_validation.json").open(
        "x", encoding="utf-8", newline="\n"
    ) as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps(summary["counts"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
