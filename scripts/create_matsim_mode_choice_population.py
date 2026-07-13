"""Create a MATSim population with car/bus/metro/walk candidate plans.

The input is a routed, car-only MATSim population. The output keeps the routed
car plan, adds optional public-transport and walk candidate plans, calibrates
car availability against a sampled private-car stock, and can write a matching
private-car vehicles file. PT/walk legs are intentionally left without link
routes so MATSim can route them against the configured transit/walk router.
"""

from __future__ import annotations

import argparse
import copy
import csv
import gzip
import json
import math
import pathlib
import random
import time
import xml.etree.ElementTree as ET
from collections import Counter


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_INPUT = (
    ROOT
    / "data"
    / "matsim_routes"
    / "fuzhou_city_23_greenspace_grid_multi_activity_5pct"
    / "routed_multi_activity_plans.xml.gz"
)
DEFAULT_OUTPUT = (
    ROOT
    / "data"
    / "matsim_routes"
    / "fuzhou_city_23_greenspace_grid_multi_activity_5pct"
    / "mode_choice_plans.xml.gz"
)
DEFAULT_METRO_STATIONS = (
    ROOT
    / "data"
    / "transit"
    / "fuzhou_transit_coordinates_unified_20260709"
    / "metro"
    / "metro_stations_unified.csv"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=pathlib.Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=pathlib.Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--pt-candidate-share", type=float, default=0.30)
    parser.add_argument(
        "--split-pt-modes",
        action="store_true",
        help="Generate separate bus and metro candidate plans instead of one generic pt plan.",
    )
    parser.add_argument("--bus-candidate-share", type=float, default=0.30)
    parser.add_argument("--metro-candidate-share", type=float, default=0.30)
    parser.add_argument("--initial-bus-share", type=float, default=0.0, help="Initial bus selection probability for car-available, non-near-metro agents.")
    parser.add_argument("--initial-metro-share", type=float, default=0.0, help="Initial metro selection probability for car-available, non-near-metro agents.")
    parser.add_argument("--near-metro-radius-m", type=float, default=800.0)
    parser.add_argument("--near-metro-initial-metro-share", type=float, default=0.70)
    parser.add_argument("--metro-stations", type=pathlib.Path, default=DEFAULT_METRO_STATIONS)
    parser.add_argument("--max-walk-leg-distance", type=float, default=1200.0)
    parser.add_argument("--civil-cars-total", type=float, default=None, help="Full-population civil car stock used to calibrate car availability.")
    parser.add_argument("--population-sample-rate", type=float, default=None, help="Population sample rate used to scale civil car stock.")
    parser.add_argument("--private-vehicles-output", type=pathlib.Path, default=None)
    parser.add_argument("--seed", type=int, default=20260709)
    return parser.parse_args()


def open_text(path: pathlib.Path, mode: str):
    if path.suffix == ".gz":
        return gzip.open(path, mode, encoding="utf-8", newline="\n")
    return path.open(mode, encoding="utf-8", newline="\n")


def get_attribute(person: ET.Element, name: str, default: str = "") -> str:
    for attr in person.findall("./attributes/attribute"):
        if attr.get("name") == name:
            return attr.text or default
    return default


def set_attribute(person: ET.Element, name: str, klass: str, value: str) -> None:
    attrs = person.find("attributes")
    if attrs is None:
        attrs = ET.Element("attributes")
        person.insert(0, attrs)
    for attr in attrs.findall("attribute"):
        if attr.get("name") == name:
            attr.set("class", klass)
            attr.text = value
            return
    attr = ET.SubElement(attrs, "attribute", {"name": name, "class": klass})
    attr.text = value


def selected_plan(person: ET.Element) -> ET.Element:
    plans = person.findall("plan")
    for plan in plans:
        if plan.get("selected") == "yes":
            return plan
    if not plans:
        raise ValueError(f"person {person.get('id')} has no plan")
    plans[0].set("selected", "yes")
    return plans[0]


def plan_leg_distances(plan: ET.Element) -> list[float]:
    distances: list[float] = []
    for leg in plan.findall("leg"):
        route = leg.find("route")
        if route is None:
            distances.append(math.inf)
            continue
        try:
            distances.append(float(route.get("distance", "inf")))
        except ValueError:
            distances.append(math.inf)
    return distances


def clone_mode_plan(plan: ET.Element, mode: str) -> ET.Element:
    cloned = copy.deepcopy(plan)
    cloned.set("selected", "no")
    for leg in cloned.findall("leg"):
        leg.set("mode", mode)
        for route in list(leg.findall("route")):
            leg.remove(route)
    return cloned


def mark_selected(person: ET.Element, selected_plan: ET.Element) -> None:
    for plan in person.findall("plan"):
        plan.set("selected", "yes" if plan is selected_plan else "no")


def write_person(handle, person: ET.Element) -> None:
    xml = ET.tostring(person, encoding="unicode", short_empty_elements=True)
    handle.write(f"  {xml}\n")


def parse_age(age_group: str) -> int:
    try:
        return int(str(age_group).replace("+", ""))
    except ValueError:
        return 30


def car_owner_weight(agent_type: str, age_group: str) -> float:
    age = parse_age(age_group)
    if agent_type == "student" or age < 20:
        return 0.0
    if agent_type in {"worker", "family_worker", "night_shift_worker"}:
        return 1.0
    if agent_type in {"non_worker_adult", "night_leisure_agent"}:
        return 0.70
    if agent_type == "retired":
        return 0.35
    return 0.50


def load_metro_station_points(path: pathlib.Path) -> list[tuple[float, float]]:
    if not path.exists():
        return []
    points: list[tuple[float, float]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                points.append((float(row["x_epsg32650"]), float(row["y_epsg32650"])))
            except (KeyError, TypeError, ValueError):
                continue
    return points


def first_activity_xy(plan: ET.Element) -> tuple[float, float] | None:
    act = plan.find("activity")
    if act is None:
        return None
    try:
        return float(act.get("x", "")), float(act.get("y", ""))
    except ValueError:
        return None


def nearest_metro_distance_m(xy: tuple[float, float] | None, stations: list[tuple[float, float]]) -> float:
    if xy is None or not stations:
        return math.inf
    x, y = xy
    return min(math.hypot(x - sx, y - sy) for sx, sy in stations)


def weighted_sample_without_replacement(items: list[tuple[str, float]], k: int, rng: random.Random) -> set[str]:
    if k <= 0:
        return set()
    scored: list[tuple[float, str]] = []
    for person_id, weight in items:
        if weight <= 0:
            continue
        scored.append((math.log(max(rng.random(), 1e-12)) / weight, person_id))
    scored.sort(reverse=True)
    return {person_id for _, person_id in scored[: min(k, len(scored))]}


def write_private_vehicles(path: pathlib.Path, vehicle_ids: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open_text(path, "wt") as handle:
        handle.write('<?xml version="1.0" encoding="utf-8"?>\n')
        handle.write(
            '<vehicleDefinitions xmlns="http://www.matsim.org/files/dtd" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xsi:schemaLocation="http://www.matsim.org/files/dtd '
            'http://www.matsim.org/files/dtd/vehicleDefinitions_v2.0.xsd">\n'
        )
        handle.write('  <vehicleType id="private_car">\n')
        handle.write('    <capacity seats="4" standingRoomInPersons="0" />\n')
        handle.write('    <length meter="5.0" />\n')
        handle.write('    <width meter="1.8" />\n')
        handle.write('    <passengerCarEquivalents pce="1.0" />\n')
        handle.write('    <networkMode networkMode="car" />\n')
        handle.write("  </vehicleType>\n")
        for vehicle_id in vehicle_ids:
            handle.write(f'  <vehicle id="{vehicle_id}" type="private_car" />\n')
        handle.write("</vehicleDefinitions>\n")


def main() -> None:
    args = parse_args()
    started = time.time()
    if not args.input.exists():
        raise FileNotFoundError(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    metro_stations = load_metro_station_points(args.metro_stations)

    persons: list[ET.Element] = []
    person_meta: dict[str, dict] = {}
    eligible_car_items: list[tuple[str, float]] = []
    agent_type_counter: Counter[str] = Counter()

    with open_text(args.input, "rt") as src:
        for event, elem in ET.iterparse(src, events=("end",)):
            if elem.tag != "person":
                continue
            person = copy.deepcopy(elem)
            plan = selected_plan(person)
            for other in person.findall("plan"):
                other.set("selected", "yes" if other is plan else "no")
            person_id = person.get("id") or f"person_{len(persons):06d}"
            agent_type = get_attribute(person, "agent_type", "unknown")
            age_group = get_attribute(person, "age_group", "")
            agent_type_counter[agent_type] += 1
            weight = car_owner_weight(agent_type, age_group)
            if weight > 0:
                eligible_car_items.append((person_id, weight))
            nearest_metro = nearest_metro_distance_m(first_activity_xy(plan), metro_stations)
            person_meta[person_id] = {
                "base_plan": plan,
                "nearest_metro_distance_m": nearest_metro,
                "near_metro": nearest_metro <= args.near_metro_radius_m,
                "agent_type": agent_type,
                "age_group": age_group,
            }
            persons.append(person)
            elem.clear()

    if args.civil_cars_total is not None or args.population_sample_rate is not None:
        if args.civil_cars_total is None or args.population_sample_rate is None:
            raise ValueError("--civil-cars-total and --population-sample-rate must be supplied together.")
        target_private_cars = int(round(args.civil_cars_total * args.population_sample_rate))
        car_owner_ids = weighted_sample_without_replacement(eligible_car_items, target_private_cars, rng)
    else:
        car_owner_ids = set()
        for person_id, meta in person_meta.items():
            agent_type = meta["agent_type"]
            age = parse_age(meta["age_group"])
            if agent_type == "student" or age < 20:
                continue
            if agent_type == "retired" and rng.random() < 0.40:
                continue
            if agent_type in {"night_leisure_agent", "non_worker_adult"} and rng.random() < 0.15:
                continue
            car_owner_ids.add(person_id)
        target_private_cars = len(car_owner_ids)

    counters: Counter[str] = Counter()
    car_avail_counter: Counter[str] = Counter()
    near_metro_counter: Counter[str] = Counter()

    with open_text(args.output, "wt") as out:
        out.write('<?xml version="1.0" encoding="utf-8"?>\n')
        out.write('<!DOCTYPE population SYSTEM "http://www.matsim.org/files/dtd/population_v6.dtd">\n')
        out.write("<population>\n")
        for person in persons:
            person_id = person.get("id") or ""
            counters["persons"] += 1
            meta = person_meta[person_id]
            plan = selected_plan(person)

            avail = "always" if person_id in car_owner_ids else "never"
            car_avail_counter[avail] += 1
            set_attribute(person, "carAvail", "java.lang.String", avail)
            set_attribute(person, "hasLicense", "java.lang.String", "yes" if avail == "always" else "no")
            set_attribute(person, "nearest_metro_distance_m", "java.lang.Double", f"{meta['nearest_metro_distance_m']:.3f}")
            set_attribute(person, "near_metro_station_800m", "java.lang.Boolean", str(bool(meta["near_metro"])).lower())
            if avail == "always":
                set_attribute(person, "private_car_vehicle_id", "java.lang.String", person_id)
            if meta["near_metro"]:
                near_metro_counter["near_metro_agents"] += 1
            else:
                near_metro_counter["non_near_metro_agents"] += 1

            distances = plan_leg_distances(plan)
            all_walkable = bool(distances) and all(distance <= args.max_walk_leg_distance for distance in distances)

            pt_plan: ET.Element | None = None
            bus_plan: ET.Element | None = None
            metro_plan: ET.Element | None = None
            walk_plan: ET.Element | None = None
            if args.split_pt_modes:
                if avail == "never" or rng.random() < args.bus_candidate_share:
                    bus_plan = clone_mode_plan(plan, "bus")
                    person.append(bus_plan)
                    counters["bus_candidate_plans"] += 1
                if avail == "never" or meta["near_metro"] or rng.random() < args.metro_candidate_share:
                    metro_plan = clone_mode_plan(plan, "metro")
                    person.append(metro_plan)
                    counters["metro_candidate_plans"] += 1
                    if meta["near_metro"]:
                        counters["near_metro_forced_metro_candidate_plans"] += 1
            else:
                if avail == "never" or rng.random() < args.pt_candidate_share:
                    pt_plan = clone_mode_plan(plan, "pt")
                    person.append(pt_plan)
                    counters["pt_candidate_plans"] += 1

            if all_walkable:
                walk_plan = clone_mode_plan(plan, "walk")
                person.append(walk_plan)
                counters["walk_candidate_plans"] += 1

            selected = plan
            if args.split_pt_modes:
                if meta["near_metro"] and metro_plan is not None and rng.random() < args.near_metro_initial_metro_share:
                    selected = metro_plan
                    counters["initial_selected_metro_near_station_plans"] += 1
                elif avail == "never":
                    if metro_plan is not None:
                        selected = metro_plan
                        counters["initial_selected_metro_no_car_plans"] += 1
                    elif bus_plan is not None:
                        selected = bus_plan
                        counters["initial_selected_bus_no_car_plans"] += 1
                    elif walk_plan is not None:
                        selected = walk_plan
                        counters["initial_selected_walk_no_car_plans"] += 1
                elif metro_plan is not None and rng.random() < args.initial_metro_share:
                    selected = metro_plan
                    counters["initial_selected_metro_base_plans"] += 1
                elif bus_plan is not None and rng.random() < args.initial_bus_share:
                    selected = bus_plan
                    counters["initial_selected_bus_base_plans"] += 1
            elif avail == "never":
                if pt_plan is not None:
                    selected = pt_plan
                    counters["initial_selected_pt_no_car_plans"] += 1
                elif walk_plan is not None:
                    selected = walk_plan
                    counters["initial_selected_walk_no_car_plans"] += 1

            mark_selected(person, selected)
            selected_mode = "car"
            first_leg = selected.find("leg")
            if first_leg is not None:
                selected_mode = first_leg.get("mode", selected_mode)
            counters[f"initial_selected_{selected_mode}_plans"] += 1
            counters["plans"] += len(person.findall("plan"))
            write_person(out, person)
        out.write("</population>\n")

    vehicle_ids = sorted(car_owner_ids)
    if args.private_vehicles_output is not None:
        write_private_vehicles(args.private_vehicles_output, vehicle_ids)

    summary = {
        "created_by": "scripts/create_matsim_mode_choice_population.py",
        "created_at_epoch": time.time(),
        "runtime_seconds": round(time.time() - started, 3),
        "input": str(args.input),
        "output": str(args.output),
        "private_vehicles_output": str(args.private_vehicles_output) if args.private_vehicles_output else None,
        "parameters": {
            "pt_candidate_share": args.pt_candidate_share,
            "split_pt_modes": args.split_pt_modes,
            "bus_candidate_share": args.bus_candidate_share,
            "metro_candidate_share": args.metro_candidate_share,
            "initial_bus_share": args.initial_bus_share,
            "initial_metro_share": args.initial_metro_share,
            "near_metro_radius_m": args.near_metro_radius_m,
            "near_metro_initial_metro_share": args.near_metro_initial_metro_share,
            "max_walk_leg_distance": args.max_walk_leg_distance,
            "civil_cars_total": args.civil_cars_total,
            "population_sample_rate": args.population_sample_rate,
            "target_private_cars": target_private_cars,
            "seed": args.seed,
        },
        "counts": dict(counters),
        "near_metro": dict(near_metro_counter),
        "agent_types": dict(agent_type_counter),
        "car_availability": dict(car_avail_counter),
        "private_vehicle_count": len(vehicle_ids),
        "eligible_car_agent_count": len(eligible_car_items),
    }
    summary_path = args.output.with_name("mode_choice_population_summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
