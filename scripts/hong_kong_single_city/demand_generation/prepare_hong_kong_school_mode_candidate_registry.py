#!/usr/bin/env python3
"""Generate school-mode candidates for every Hong Kong day-school trip.

The selected mode in the input plan is retained only as an audit field.  It is
never used for eligibility or ranking.  PT and taxi release alternatives are
created for every school trip, walk is created for trips within a configurable
distance, and school-bus candidates are created only when the adoption-ready
v6 supply has a stage-compatible physical service for the student's campus and
home grid.  Inbound and outbound trips are screened independently.

This script creates a candidate registry.  It deliberately does not choose a
candidate, modify selected plans, or allocate shared vehicle seats; those are
selection-time responsibilities.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from dataclasses import asdict, dataclass
import gzip
import json
import math
from pathlib import Path
import re
from typing import Iterable

import pandas as pd
from lxml import etree as ET


REPO_ROOT = Path(__file__).resolve().parents[3]
FORMAL_ROOT = Path(r"F:\Matsim\matsim-example-project")
PROJECT_ROOT = FORMAL_ROOT if FORMAL_ROOT.exists() else REPO_ROOT
V6_SUPPLY = (
    REPO_ROOT
    / "data/transit/hongkong/processed"
    / "matsim_road_pt_school_bus_supply_2026_v6_adoption_ready"
)
DEFAULT_PLANS = (
    REPO_ROOT
    / "data/school/hongkong/processed/school_bus_plan_candidates_5pct_v6"
    / "plans_routed_selective_5pct_taxi_44000_no_ride.xml.gz"
)
DEFAULT_SCHOOLS = (
    PROJECT_ROOT
    / "data/school/hongkong/processed/student_school_od_2022"
    / "schools_2022_capacity_estimates.csv"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "data/school/hongkong/processed/school_bus_plan_candidates_5pct_v6"
)

SCHOOL_FACILITY_PATTERN = re.compile(r"^school_(\d+)$")
BASE_RELEASE_MODES = ("pt", "taxi")


@dataclass(frozen=True)
class SchoolTrip:
    trip_id: str
    person_id: str
    household_id: str
    trip_index: int
    direction: str
    student_stage: str
    home_grid_id: str
    school_facility_id: str
    school_index: int | None
    campus_id: str
    original_mode_audit_only: str
    original_departure_time_s: float
    original_travel_time_s: float
    school_end_time_s: float | None
    home_x: float
    home_y: float
    home_link_id: str
    school_x: float
    school_y: float
    school_link_id: str
    crowfly_distance_m: float


@dataclass(frozen=True)
class ServiceOption:
    route_id: str
    direction: str
    campus_id: str
    dominant_stage: str
    transit_line_id: str
    transit_route_id: str
    departure_id: str
    vehicle_id: str
    boarding_facility_id: str
    alighting_facility_id: str
    boarding_link_id: str
    alighting_link_id: str
    boarding_x: float
    boarding_y: float
    alighting_x: float
    alighting_y: float
    scheduled_board_time_s: float
    scheduled_alight_time_s: float
    vehicle_capacity: int
    proxy_students: int
    route_kind: str
    path_quality: str

    @property
    def in_vehicle_time_s(self) -> float:
        return self.scheduled_alight_time_s - self.scheduled_board_time_s


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plans", type=Path, default=DEFAULT_PLANS)
    parser.add_argument("--supply-dir", type=Path, default=V6_SUPPLY)
    parser.add_argument("--schools", type=Path, default=DEFAULT_SCHOOLS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-route-candidates", type=int, default=3)
    parser.add_argument("--max-home-stop-distance-m", type=float, default=1_500.0)
    parser.add_argument("--max-campus-stop-distance-m", type=float, default=750.0)
    parser.add_argument("--max-walk-distance-m", type=float, default=5_000.0)
    parser.add_argument("--walk-circuity", type=float, default=1.25)
    parser.add_argument("--walk-speed-m-s", type=float, default=1.2)
    parser.add_argument("--max-return-wait-minutes", type=float, default=90.0)
    parser.add_argument("--max-return-early-minutes", type=float, default=30.0)
    return parser.parse_args()


def local_name(element: ET._Element) -> str:
    return ET.QName(element).localname


def parse_time(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    parts = value.split(":")
    if len(parts) != 3:
        return None
    hours, minutes, seconds = map(float, parts)
    result = hours * 3_600 + minutes * 60 + seconds
    return result if math.isfinite(result) and result >= 0 else None


def format_time(seconds: float | None) -> str:
    if seconds is None or not math.isfinite(seconds):
        return ""
    rounded = max(0, int(round(seconds)))
    hours, remainder = divmod(rounded, 3_600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


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


def is_stage_activity(activity: ET._Element) -> bool:
    return activity.get("type", "").endswith(" interaction")


def selected_plan(person: ET._Element) -> ET._Element:
    plans = [child for child in person if local_name(child) == "plan"]
    selected = [plan for plan in plans if plan.get("selected") == "yes"]
    if len(selected) == 1:
        return selected[0]
    if len(plans) == 1:
        return plans[0]
    raise ValueError(f"Selected plan unresolved for {person.get('id', '')}")


def main_mode(legs: list[ET._Element]) -> str:
    modes: list[str] = []
    for leg in legs:
        leg_attributes = attributes(leg)
        modes.append(leg_attributes.get("routingMode") or leg.get("mode", ""))
    for mode in ("car", "car_passenger", "school_bus", "pt", "taxi", "walk"):
        if mode in modes:
            return mode
    return modes[0] if modes else ""


def leg_travel_time(leg: ET._Element) -> float | None:
    value = parse_time(leg.get("trav_time"))
    if value is not None:
        return value
    routes = [child for child in leg if local_name(child) == "route"]
    if len(routes) == 1:
        return parse_time(routes[0].get("trav_time"))
    return None


def activity_xy(activity: ET._Element) -> tuple[float, float] | None:
    x = finite(activity.get("x"))
    y = finite(activity.get("y"))
    return (x, y) if x is not None and y is not None else None


def school_identity(activity: ET._Element) -> tuple[str, int | None]:
    facility = activity.get("facility", "")
    match = SCHOOL_FACILITY_PATTERN.match(facility)
    return facility, int(match.group(1)) if match else None


def school_stage(activity: ET._Element) -> str:
    activity_type = activity.get("type", "")
    return activity_type.removeprefix("school_") if activity_type.startswith("school_") else ""


def extract_student_trips(
    plans_path: Path,
    campus_by_school: dict[int, str],
) -> tuple[list[SchoolTrip], dict[str, int]]:
    trips: list[SchoolTrip] = []
    audit = Counter()
    with gzip.open(plans_path, "rb") as handle:
        context = ET.iterparse(handle, events=("end",), tag="person")
        for _, person in context:
            audit["people"] += 1
            person_attributes = attributes(person)
            if person_attributes.get("role") != "day_school_student":
                person.clear()
                continue
            audit["day_school_students"] += 1
            person_id = person.get("id", "")
            plan = selected_plan(person)
            elements = [
                child for child in plan
                if local_name(child) in {"activity", "leg"}
            ]
            main_activity_indexes = [
                index for index, element in enumerate(elements)
                if local_name(element) == "activity" and not is_stage_activity(element)
            ]
            for trip_index, (start, end) in enumerate(
                zip(main_activity_indexes, main_activity_indexes[1:], strict=False)
            ):
                origin = elements[start]
                destination = elements[end]
                origin_school = origin.get("type", "").startswith("school_")
                destination_school = destination.get("type", "").startswith("school_")
                if origin_school == destination_school:
                    continue
                direction = "outbound_pm" if origin_school else "inbound_am"
                school_activity = origin if origin_school else destination
                home_activity = destination if origin_school else origin
                legs = [
                    element for element in elements[start + 1:end]
                    if local_name(element) == "leg"
                ]
                travel_times = [leg_travel_time(leg) for leg in legs]
                departure = parse_time(origin.get("end_time"))
                if departure is None and legs:
                    departure = parse_time(legs[0].get("dep_time"))
                home_xy = activity_xy(home_activity)
                school_xy = activity_xy(school_activity)
                if departure is None or not legs or any(value is None for value in travel_times):
                    audit["school_trips_missing_time"] += 1
                    continue
                if home_xy is None or school_xy is None:
                    audit["school_trips_missing_coordinates"] += 1
                    continue
                facility_id, school_index = school_identity(school_activity)
                campus_id = campus_by_school.get(school_index, "") if school_index is not None else ""
                if not campus_id:
                    audit["school_trips_missing_campus"] += 1
                home_grid = person_attributes.get("gridId", "")
                if not home_grid:
                    audit["school_trips_missing_home_grid"] += 1
                distance_m = math.hypot(home_xy[0] - school_xy[0], home_xy[1] - school_xy[1])
                trip_id = f"{person_id}:school_trip_{trip_index}:{direction}"
                trips.append(
                    SchoolTrip(
                        trip_id=trip_id,
                        person_id=person_id,
                        household_id=person_attributes.get("householdId", ""),
                        trip_index=trip_index,
                        direction=direction,
                        student_stage=school_stage(school_activity),
                        home_grid_id=home_grid,
                        school_facility_id=facility_id,
                        school_index=school_index,
                        campus_id=campus_id,
                        original_mode_audit_only=main_mode(legs),
                        original_departure_time_s=departure,
                        original_travel_time_s=float(sum(value for value in travel_times if value is not None)),
                        school_end_time_s=parse_time(school_activity.get("end_time")),
                        home_x=home_xy[0],
                        home_y=home_xy[1],
                        home_link_id=home_activity.get("link", ""),
                        school_x=school_xy[0],
                        school_y=school_xy[1],
                        school_link_id=school_activity.get("link", ""),
                        crowfly_distance_m=distance_m,
                    )
                )
                audit["school_trips"] += 1
                audit[f"direction::{direction}"] += 1
                audit[f"original_mode::{main_mode(legs)}"] += 1
            person.clear()
            while person.getprevious() is not None:
                del person.getparent()[0]
    return trips, dict(audit)


def load_campus_map(path: Path) -> dict[int, str]:
    frame = pd.read_csv(path, dtype={"campus_id": str})
    required = {"school_index", "campus_id"}
    if not required.issubset(frame.columns):
        raise ValueError(f"School table lacks {sorted(required.difference(frame.columns))}")
    frame["school_index"] = pd.to_numeric(frame["school_index"], errors="raise").astype(int)
    if frame["school_index"].duplicated().any():
        raise ValueError("school_index is not unique")
    return dict(zip(frame["school_index"], frame["campus_id"], strict=True))


def split_grid_ids(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(";") if item.strip())


def load_service_options(
    supply_dir: Path,
) -> tuple[dict[tuple[str, str, str], list[ServiceOption]], dict[str, int]]:
    routes = pd.read_csv(supply_dir / "school_bus_routes_v6.csv", dtype=str).fillna("")
    stops = pd.read_csv(supply_dir / "school_bus_stops_v6.csv", dtype=str).fillna("")
    required_route_fields = {
        "route_id", "direction", "campus_id", "dominant_stage",
        "vehicle_capacity", "proxy_students", "route_kind", "path_quality",
    }
    if not required_route_fields.issubset(routes.columns):
        raise ValueError(
            "v6 route registry must be rebuilt with candidate-adoption fields: "
            + ", ".join(sorted(required_route_fields.difference(routes.columns)))
        )
    route_metadata = {
        (row.route_id, row.direction): row
        for row in routes.itertuples(index=False)
    }
    stop_grid_ids = {
        row.facility_id: split_grid_ids(row.origin_grid_ids)
        for row in stops.itertuples(index=False)
    }
    facilities: dict[str, tuple[float, float, str]] = {}
    lookup: dict[tuple[str, str, str], list[ServiceOption]] = defaultdict(list)
    audit = Counter()
    schedule_path = supply_dir / "transitSchedule_5pct_school_bus_v6.xml.gz"
    with gzip.open(schedule_path, "rb") as handle:
        context = ET.iterparse(handle, events=("end",))
        for _, element in context:
            name = local_name(element)
            if name == "stopFacility" and element.get("id", "").startswith("sbv6_"):
                facilities[element.get("id", "")] = (
                    float(element.get("x", "nan")),
                    float(element.get("y", "nan")),
                    element.get("linkRefId", ""),
                )
            elif name == "transitLine" and element.get("id", "").startswith("line_school_bus_v6_"):
                line_id = element.get("id", "")
                for transit_route in [child for child in element if local_name(child) == "transitRoute"]:
                    transit_route_id = transit_route.get("id", "")
                    if transit_route_id.endswith("_AM"):
                        direction = "inbound_am"
                        route_id = transit_route_id.removeprefix("school_bus_v6_").removesuffix("_AM")
                    elif transit_route_id.endswith("_PM"):
                        direction = "outbound_pm"
                        route_id = transit_route_id.removeprefix("school_bus_v6_").removesuffix("_PM")
                    else:
                        continue
                    metadata = route_metadata.get((route_id, direction))
                    if metadata is None:
                        raise ValueError(f"Schedule route lacks v6 metadata: {transit_route_id}")
                    profile = next(child for child in transit_route if local_name(child) == "routeProfile")
                    profile_stops = [child for child in profile if local_name(child) == "stop"]
                    departures_block = next(child for child in transit_route if local_name(child) == "departures")
                    departures = [child for child in departures_block if local_name(child) == "departure"]
                    if len(departures) != 1:
                        raise ValueError(f"Expected one departure for {transit_route_id}")
                    departure = departures[0]
                    departure_time = parse_time(departure.get("departureTime"))
                    if departure_time is None:
                        raise ValueError(f"Invalid departure time for {transit_route_id}")
                    if direction == "inbound_am":
                        school_stop = profile_stops[-1]
                        passenger_stops = profile_stops[:-1]
                    else:
                        school_stop = profile_stops[0]
                        passenger_stops = profile_stops[1:]
                    school_facility_id = school_stop.get("refId", "")
                    school_xy = facilities[school_facility_id]
                    for passenger_stop in passenger_stops:
                        passenger_facility_id = passenger_stop.get("refId", "")
                        passenger_xy = facilities[passenger_facility_id]
                        grid_ids = stop_grid_ids.get(passenger_facility_id, ())
                        if not grid_ids:
                            raise ValueError(f"Passenger stop lacks grid membership: {passenger_facility_id}")
                        if direction == "inbound_am":
                            board_stop, alight_stop = passenger_stop, school_stop
                            board_id, alight_id = passenger_facility_id, school_facility_id
                            board_xy, alight_xy = passenger_xy, school_xy
                        else:
                            board_stop, alight_stop = school_stop, passenger_stop
                            board_id, alight_id = school_facility_id, passenger_facility_id
                            board_xy, alight_xy = school_xy, passenger_xy
                        board_offset = parse_time(board_stop.get("departureOffset"))
                        alight_offset = parse_time(alight_stop.get("arrivalOffset"))
                        if board_offset is None or alight_offset is None:
                            raise ValueError(f"Invalid stop offsets for {transit_route_id}")
                        option = ServiceOption(
                            route_id=route_id,
                            direction=direction,
                            campus_id=str(metadata.campus_id),
                            dominant_stage=str(metadata.dominant_stage),
                            transit_line_id=line_id,
                            transit_route_id=transit_route_id,
                            departure_id=departure.get("id", ""),
                            vehicle_id=departure.get("vehicleRefId", ""),
                            boarding_facility_id=board_id,
                            alighting_facility_id=alight_id,
                            boarding_link_id=board_xy[2],
                            alighting_link_id=alight_xy[2],
                            boarding_x=board_xy[0],
                            boarding_y=board_xy[1],
                            alighting_x=alight_xy[0],
                            alighting_y=alight_xy[1],
                            scheduled_board_time_s=departure_time + board_offset,
                            scheduled_alight_time_s=departure_time + alight_offset,
                            vehicle_capacity=int(float(metadata.vehicle_capacity)),
                            proxy_students=int(float(metadata.proxy_students)),
                            route_kind=str(metadata.route_kind),
                            path_quality=str(metadata.path_quality),
                        )
                        for grid_id in grid_ids:
                            lookup[(option.campus_id, direction, grid_id)].append(option)
                            audit["grid_service_memberships"] += 1
                    audit[f"routes::{direction}"] += 1
                element.clear()
    audit["school_bus_stop_facilities"] = len(facilities)
    audit["service_keys"] = len(lookup)
    return dict(lookup), dict(audit)


def distance(first: tuple[float, float], second: tuple[float, float]) -> float:
    return math.hypot(first[0] - second[0], first[1] - second[1])


def eligible_school_bus_options(
    trip: SchoolTrip,
    options: Iterable[ServiceOption],
    args: argparse.Namespace,
) -> list[tuple[ServiceOption, float, float, float | None]]:
    eligible: list[tuple[ServiceOption, float, float, float | None]] = []
    for option in options:
        if option.dominant_stage != trip.student_stage:
            continue
        if trip.direction == "inbound_am":
            home_stop = (option.boarding_x, option.boarding_y)
            campus_stop = (option.alighting_x, option.alighting_y)
        else:
            home_stop = (option.alighting_x, option.alighting_y)
            campus_stop = (option.boarding_x, option.boarding_y)
        home_access = distance((trip.home_x, trip.home_y), home_stop)
        campus_access = distance((trip.school_x, trip.school_y), campus_stop)
        if home_access > args.max_home_stop_distance_m:
            continue
        if campus_access > args.max_campus_stop_distance_m:
            continue
        return_shift = None
        if trip.direction == "outbound_pm" and trip.school_end_time_s is not None:
            return_shift = option.scheduled_board_time_s - trip.school_end_time_s
            if return_shift < -args.max_return_early_minutes * 60:
                continue
            if return_shift > args.max_return_wait_minutes * 60:
                continue
        eligible.append((option, home_access, campus_access, return_shift))
    eligible.sort(
        key=lambda item: (
            abs(item[3]) if item[3] is not None else 0.0,
            item[1] + item[2],
            item[0].in_vehicle_time_s,
            item[0].route_id,
        )
    )
    return eligible[: args.max_route_candidates]


def trip_row(trip: SchoolTrip) -> dict[str, object]:
    row = asdict(trip)
    row["school_index"] = "" if trip.school_index is None else trip.school_index
    row["original_departure_time"] = format_time(trip.original_departure_time_s)
    row["original_travel_time"] = format_time(trip.original_travel_time_s)
    row["school_end_time"] = format_time(trip.school_end_time_s)
    return row


def base_candidate_row(trip: SchoolTrip, mode: str, rank: int) -> dict[str, object]:
    return {
        "candidate_id": f"{trip.trip_id}:{mode}",
        "trip_id": trip.trip_id,
        "person_id": trip.person_id,
        "household_id": trip.household_id,
        "trip_index": trip.trip_index,
        "direction": trip.direction,
        "student_stage": trip.student_stage,
        "campus_id": trip.campus_id,
        "home_grid_id": trip.home_grid_id,
        "candidate_mode": mode,
        "candidate_rank_within_mode": rank,
        "original_mode_audit_only": trip.original_mode_audit_only,
        "requires_reroute": True,
        "selection_status": "unselected_candidate",
        "capacity_constraint": "none" if mode != "school_bus" else "selection_time_shared_vehicle_capacity",
    }


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"Refusing to write empty table: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: list[str] = []
    for row in rows:
        for field in row:
            if field not in fields:
                fields.append(field)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    required = [
        args.plans,
        args.schools,
        args.supply_dir / "school_bus_routes_v6.csv",
        args.supply_dir / "school_bus_stops_v6.csv",
        args.supply_dir / "transitSchedule_5pct_school_bus_v6.xml.gz",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing candidate-generation inputs:\n" + "\n".join(missing))
    if args.max_route_candidates < 1:
        raise ValueError("max-route-candidates must be positive")

    campus_by_school = load_campus_map(args.schools)
    trips, population_audit = extract_student_trips(args.plans, campus_by_school)
    services, service_audit = load_service_options(args.supply_dir)

    universe_rows: list[dict[str, object]] = []
    mode_rows: list[dict[str, object]] = []
    school_bus_rows: list[dict[str, object]] = []
    reason_counts = Counter()
    school_bus_trip_ids: set[str] = set()
    for trip in trips:
        matched = services.get((trip.campus_id, trip.direction, trip.home_grid_id), [])
        eligible = eligible_school_bus_options(trip, matched, args)
        if not trip.campus_id:
            reason = "missing_school_to_campus_mapping"
        elif not trip.home_grid_id:
            reason = "missing_home_grid"
        elif not matched:
            reason = "no_v6_service_for_campus_home_grid_direction"
        elif not any(option.dominant_stage == trip.student_stage for option in matched):
            reason = "no_stage_compatible_v6_service"
        elif not eligible:
            reason = "service_failed_access_or_return_time_screen"
        else:
            reason = "eligible_v6_physical_service"
            school_bus_trip_ids.add(trip.trip_id)
        reason_counts[reason] += 1
        universe = trip_row(trip)
        universe.update(
            {
                "school_bus_eligible": bool(eligible),
                "school_bus_route_candidate_count": len(eligible),
                "school_bus_screen_result": reason,
                "old_mode_used_for_eligibility_or_ranking": False,
            }
        )
        universe_rows.append(universe)

        for mode in BASE_RELEASE_MODES:
            row = base_candidate_row(trip, mode, 1)
            row["candidate_provenance"] = "all_student_release_alternative"
            mode_rows.append(row)
        if trip.crowfly_distance_m <= args.max_walk_distance_m:
            row = base_candidate_row(trip, "walk", 1)
            row.update(
                {
                    "candidate_provenance": "distance_screened_all_student_release_alternative",
                    "estimated_walk_distance_m": round(trip.crowfly_distance_m * args.walk_circuity, 3),
                    "estimated_walk_time_s": round(
                        trip.crowfly_distance_m * args.walk_circuity / args.walk_speed_m_s, 3
                    ),
                }
            )
            mode_rows.append(row)
        for rank, (option, home_access, campus_access, return_shift) in enumerate(eligible, start=1):
            mode_row = base_candidate_row(trip, "school_bus", rank)
            mode_row["candidate_id"] = f"{trip.trip_id}:school_bus:{option.route_id}"
            mode_row["candidate_provenance"] = "v6_physical_supply_exact_campus_home_grid_stage"
            mode_rows.append(mode_row)
            bus_row = dict(mode_row)
            bus_row.update(
                {
                    "route_id": option.route_id,
                    "transit_line_id": option.transit_line_id,
                    "transit_route_id": option.transit_route_id,
                    "departure_id": option.departure_id,
                    "vehicle_id": option.vehicle_id,
                    "boarding_facility_id": option.boarding_facility_id,
                    "alighting_facility_id": option.alighting_facility_id,
                    "boarding_link_id": option.boarding_link_id,
                    "alighting_link_id": option.alighting_link_id,
                    "scheduled_board_time": format_time(option.scheduled_board_time_s),
                    "scheduled_alight_time": format_time(option.scheduled_alight_time_s),
                    "scheduled_board_time_s": round(option.scheduled_board_time_s, 3),
                    "scheduled_alight_time_s": round(option.scheduled_alight_time_s, 3),
                    "in_vehicle_time_s": round(option.in_vehicle_time_s, 3),
                    "home_stop_distance_m": round(home_access, 3),
                    "campus_stop_distance_m": round(campus_access, 3),
                    "return_departure_shift_s": "" if return_shift is None else round(return_shift, 3),
                    "vehicle_capacity": option.vehicle_capacity,
                    "v6_proxy_students": option.proxy_students,
                    "route_kind": option.route_kind,
                    "path_quality": option.path_quality,
                    "contains_real_waypoint": True,
                }
            )
            school_bus_rows.append(bus_row)

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "school_trip_universe_v6.csv", universe_rows)
    write_csv(output / "school_mode_candidates_v6.csv", mode_rows)
    if school_bus_rows:
        write_csv(output / "school_bus_physical_route_candidates_v6.csv", school_bus_rows)

    direction_counts = Counter(trip.direction for trip in trips)
    original_mode_counts = Counter(trip.original_mode_audit_only for trip in trips)
    eligible_by_direction = Counter(
        trip.direction for trip in trips if trip.trip_id in school_bus_trip_ids
    )
    eligible_by_original_mode = Counter(
        trip.original_mode_audit_only for trip in trips if trip.trip_id in school_bus_trip_ids
    )
    directions_by_person: dict[str, set[str]] = defaultdict(set)
    for trip in trips:
        if trip.trip_id in school_bus_trip_ids:
            directions_by_person[trip.person_id].add(trip.direction)
    student_pattern_counts = Counter()
    for person_id in {trip.person_id for trip in trips}:
        directions = directions_by_person.get(person_id, set())
        if directions == {"inbound_am", "outbound_pm"}:
            student_pattern_counts["both_directions"] += 1
        elif directions == {"inbound_am"}:
            student_pattern_counts["inbound_only"] += 1
        elif directions == {"outbound_pm"}:
            student_pattern_counts["outbound_only"] += 1
        else:
            student_pattern_counts["neither_direction"] += 1
    candidate_mode_counts = Counter(str(row["candidate_mode"]) for row in mode_rows)
    old_school_bus_eligible = sum(
        trip.original_mode_audit_only == "school_bus" and trip.trip_id in school_bus_trip_ids
        for trip in trips
    )
    old_school_bus_ineligible = sum(
        trip.original_mode_audit_only == "school_bus" and trip.trip_id not in school_bus_trip_ids
        for trip in trips
    )
    newly_eligible_from_other_modes = sum(
        trip.original_mode_audit_only != "school_bus" and trip.trip_id in school_bus_trip_ids
        for trip in trips
    )

    coverage_by_original_mode = []
    for mode in sorted(original_mode_counts):
        total = original_mode_counts[mode]
        eligible_count = eligible_by_original_mode[mode]
        coverage_by_original_mode.append(
            {
                "original_mode_audit_only": mode,
                "school_trip_count": total,
                "school_bus_eligible_trip_count": eligible_count,
                "school_bus_ineligible_trip_count": total - eligible_count,
                "school_bus_eligible_share": eligible_count / total if total else 0.0,
            }
        )
    coverage_by_stage_direction = []
    stage_direction_totals = Counter((trip.student_stage, trip.direction) for trip in trips)
    stage_direction_eligible = Counter(
        (trip.student_stage, trip.direction)
        for trip in trips if trip.trip_id in school_bus_trip_ids
    )
    for stage, direction in sorted(stage_direction_totals):
        total = stage_direction_totals[(stage, direction)]
        eligible_count = stage_direction_eligible[(stage, direction)]
        coverage_by_stage_direction.append(
            {
                "student_stage": stage,
                "direction": direction,
                "school_trip_count": total,
                "school_bus_eligible_trip_count": eligible_count,
                "school_bus_ineligible_trip_count": total - eligible_count,
                "school_bus_eligible_share": eligible_count / total if total else 0.0,
            }
        )
    write_csv(output / "school_bus_candidate_coverage_by_original_mode_v6.csv", coverage_by_original_mode)
    write_csv(output / "school_bus_candidate_coverage_by_stage_direction_v6.csv", coverage_by_stage_direction)
    summary = {
        "status": "candidate_registry_generated_not_selected_not_applied_to_plans",
        "policy": {
            "student_scope": "every selected-plan day_school_student school trip",
            "inbound_outbound_independent": True,
            "old_mode_policy": "audit_only; never used for eligibility or ranking",
            "base_release_modes_every_trip": list(BASE_RELEASE_MODES),
            "walk_policy": f"crow-fly distance <= {args.max_walk_distance_m:g} m",
            "car_passenger_policy": "not duplicated here; supplied only by the separate real-driver household joint candidate catalog",
            "school_bus_selection": "not performed; shared vehicle capacity must be enforced by the future selector",
        },
        "inputs": {
            "plans": str(args.plans.resolve()),
            "schools": str(args.schools.resolve()),
            "v6_supply": str(args.supply_dir.resolve()),
        },
        "student_universe": {
            **population_audit,
            "direction_counts": dict(direction_counts),
            "original_mode_counts_audit_only": dict(original_mode_counts),
        },
        "school_bus_screen": {
            "eligible_unique_school_trips": len(school_bus_trip_ids),
            "eligible_share": len(school_bus_trip_ids) / len(trips) if trips else 0.0,
            "physical_route_candidate_rows": len(school_bus_rows),
            "eligible_by_direction": dict(eligible_by_direction),
            "eligible_by_original_mode_audit_only": dict(eligible_by_original_mode),
            "student_direction_pattern_counts": dict(student_pattern_counts),
            "old_school_bus_transition_audit": {
                "old_school_bus_still_physically_eligible": old_school_bus_eligible,
                "old_school_bus_now_ineligible": old_school_bus_ineligible,
                "newly_eligible_from_non_school_bus_modes": newly_eligible_from_other_modes,
            },
            "screen_result_counts": dict(reason_counts),
        },
        "candidate_catalog": {
            "rows": len(mode_rows),
            "mode_counts": dict(candidate_mode_counts),
            "max_school_bus_routes_per_trip": args.max_route_candidates,
        },
        "service_inventory": service_audit,
        "thresholds": {
            "max_home_stop_distance_m": args.max_home_stop_distance_m,
            "max_campus_stop_distance_m": args.max_campus_stop_distance_m,
            "max_walk_distance_m": args.max_walk_distance_m,
            "walk_circuity": args.walk_circuity,
            "walk_speed_m_s": args.walk_speed_m_s,
            "max_return_wait_minutes": args.max_return_wait_minutes,
            "max_return_early_minutes": args.max_return_early_minutes,
        },
        "qa": {
            "all_school_trips_have_pt_candidate": candidate_mode_counts["pt"] == len(trips),
            "all_school_trips_have_taxi_candidate": candidate_mode_counts["taxi"] == len(trips),
            "all_school_bus_candidates_have_real_waypoints": all(
                bool(row["contains_real_waypoint"]) for row in school_bus_rows
            ),
            "school_bus_candidates_reference_v6_supply": all(
                str(row["transit_line_id"]).startswith("line_school_bus_v6_")
                and str(row["transit_route_id"]).startswith("school_bus_v6_")
                for row in school_bus_rows
            ),
            "old_mode_not_used_for_eligibility_or_ranking": True,
            "no_candidate_selected_or_plan_modified": True,
        },
        "outputs": {
            "school_trip_universe": "school_trip_universe_v6.csv",
            "mode_candidates": "school_mode_candidates_v6.csv",
            "school_bus_physical_candidates": "school_bus_physical_route_candidates_v6.csv",
            "coverage_by_original_mode": "school_bus_candidate_coverage_by_original_mode_v6.csv",
            "coverage_by_stage_direction": "school_bus_candidate_coverage_by_stage_direction_v6.csv",
        },
    }
    (output / "school_mode_candidate_summary_v6.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
