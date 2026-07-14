"""Create the simplified Fuzhou car/pt/walk choice set.

The script starts from the routed 2% snap-spread population, samples private
car owners from eligible adults, keeps routed car plans only for owners, adds
one generic PT plan to every person, and preserves an existing all-walk plan
when present. Separate bus and metro passenger plans are deliberately removed;
SwissRailRaptor selects bus, metro, or their combination inside generic PT.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import json
import math
import random
import re
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = (
    ROOT
    / "data"
    / "matsim_routes"
    / "fuzhou_city_23_greenspace_grid_multi_activity_2pct_busprio_floor_snapspread"
    / "mode_choice_plans_bus_metro_2pct_snapspread.xml.gz"
)
DEFAULT_OUT_DIR = (
    ROOT
    / "data"
    / "matsim_routes"
    / "fuzhou_city_23_greenspace_grid_multi_activity_2pct_carown197_pt"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--car-ownership-share", type=float, default=0.197)
    parser.add_argument("--seed", type=int, default=20260709)
    return parser.parse_args()


def open_text(path: Path, mode: str):
    if path.suffix == ".gz":
        return gzip.open(path, mode, encoding="utf-8", newline="\n")
    return path.open(mode, encoding="utf-8", newline="\n")


def get_attribute(person: ET.Element, name: str, default: str = "") -> str:
    attrs = person.find("attributes")
    if attrs is None:
        return default
    for attr in attrs.findall("attribute"):
        if attr.get("name") == name:
            return (attr.text or default).strip()
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


def remove_attribute(person: ET.Element, name: str) -> None:
    attrs = person.find("attributes")
    if attrs is None:
        return
    for attr in list(attrs.findall("attribute")):
        if attr.get("name") == name:
            attrs.remove(attr)


def plan_modes(plan: ET.Element) -> set[str]:
    return {leg.get("mode", "") for leg in plan.findall("leg") if leg.get("mode")}


def plan_is_mode(plan: ET.Element, mode: str) -> bool:
    modes = plan_modes(plan)
    return bool(modes) and modes == {mode}


def clone_plan(plan: ET.Element, mode: str, keep_routes: bool) -> ET.Element:
    cloned = copy.deepcopy(plan)
    cloned.set("selected", "no")
    cloned.attrib.pop("score", None)
    for leg in cloned.findall("leg"):
        leg.set("mode", mode)
        if not keep_routes:
            for route in list(leg.findall("route")):
                leg.remove(route)
    return cloned


def age_lower_bound(age_group: str) -> int:
    match = re.search(r"\d+", str(age_group))
    return int(match.group()) if match else 30


def car_owner_weight(agent_type: str, age_group: str) -> float:
    age = age_lower_bound(age_group)
    if agent_type == "student" or age < 20:
        return 0.0
    if agent_type in {"worker", "family_worker", "night_shift_worker"}:
        return 1.0
    if agent_type in {"non_worker_adult", "night_leisure_agent"}:
        return 0.70
    if agent_type == "retired":
        return 0.35
    return 0.50


def weighted_sample_without_replacement(
    items: list[tuple[str, float]], target: int, rng: random.Random
) -> set[str]:
    if target < 0:
        raise ValueError("target must be non-negative")
    positive = [(person_id, weight) for person_id, weight in items if weight > 0]
    if target > len(positive):
        raise ValueError(f"requested {target} car owners but only {len(positive)} agents are eligible")
    scored = [
        (math.log(max(rng.random(), 1e-12)) / weight, person_id)
        for person_id, weight in positive
    ]
    scored.sort(reverse=True)
    return {person_id for _, person_id in scored[:target]}


def write_person(handle, person: ET.Element) -> None:
    handle.write(f"  {ET.tostring(person, encoding='unicode', short_empty_elements=True)}\n")


def write_private_vehicles(path: Path, vehicle_ids: list[str]) -> None:
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
    if not 0 <= args.car_ownership_share <= 1:
        raise ValueError("--car-ownership-share must be between 0 and 1")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    output_population = args.out_dir / "mode_choice_plans_car_pt_walk_2pct_carown197.xml.gz"
    output_vehicles = args.out_dir / "private_car_vehicles_2pct_carown197.xml.gz"

    persons: list[ET.Element] = []
    metadata: dict[str, dict[str, Any]] = {}
    eligible_items: list[tuple[str, float]] = []
    agent_types: Counter[str] = Counter()
    input_plan_modes: Counter[str] = Counter()

    with open_text(args.input, "rt") as handle:
        for _event, elem in ET.iterparse(handle, events=("end",)):
            if elem.tag != "person":
                continue
            person = copy.deepcopy(elem)
            elem.clear()
            person_id = person.get("id", f"person_{len(persons):06d}")
            agent_type = get_attribute(person, "agent_type", "unknown")
            age_group = get_attribute(person, "age_group", "")
            agent_types[agent_type] += 1
            weight = car_owner_weight(agent_type, age_group)
            if weight > 0:
                eligible_items.append((person_id, weight))

            car_plan = next((plan for plan in person.findall("plan") if plan_is_mode(plan, "car")), None)
            if car_plan is None:
                raise RuntimeError(f"person {person_id} has no routed car plan")
            walk_plan = next((plan for plan in person.findall("plan") if plan_is_mode(plan, "walk")), None)
            for plan in person.findall("plan"):
                modes = plan_modes(plan)
                input_plan_modes[next(iter(modes)) if len(modes) == 1 else "mixed"] += 1
            metadata[person_id] = {
                "car_plan": copy.deepcopy(car_plan),
                "walk_plan": copy.deepcopy(walk_plan) if walk_plan is not None else None,
                "agent_type": agent_type,
                "age_group": age_group,
                "weight": weight,
            }
            persons.append(person)

    target_car_owners = int(round(len(persons) * args.car_ownership_share))
    rng = random.Random(args.seed)
    car_owner_ids = weighted_sample_without_replacement(eligible_items, target_car_owners, rng)

    counters: Counter[str] = Counter()
    selected_modes: Counter[str] = Counter()
    output_plan_modes: Counter[str] = Counter()
    car_availability: Counter[str] = Counter()
    violations: Counter[str] = Counter()

    with open_text(output_population, "wt") as out:
        out.write('<?xml version="1.0" encoding="utf-8"?>\n')
        out.write('<!DOCTYPE population SYSTEM "http://www.matsim.org/files/dtd/population_v6.dtd">\n')
        out.write("<population>\n")
        for person in persons:
            person_id = person.get("id", "")
            meta = metadata[person_id]
            is_owner = person_id in car_owner_ids
            for plan in list(person.findall("plan")):
                person.remove(plan)

            car_plan = clone_plan(meta["car_plan"], "car", keep_routes=True)
            pt_plan = clone_plan(meta["car_plan"], "pt", keep_routes=False)
            walk_plan = (
                clone_plan(meta["walk_plan"], "walk", keep_routes=False)
                if meta["walk_plan"] is not None
                else None
            )

            if is_owner:
                car_plan.set("selected", "yes")
                person.append(car_plan)
                pt_plan.set("selected", "no")
                person.append(pt_plan)
                selected_modes["car"] += 1
                output_plan_modes["car"] += 1
                output_plan_modes["pt"] += 1
                set_attribute(person, "carAvail", "java.lang.String", "always")
                set_attribute(person, "hasLicense", "java.lang.String", "yes")
                set_attribute(person, "private_car_vehicle_id", "java.lang.String", person_id)
                car_availability["always"] += 1
            else:
                pt_plan.set("selected", "yes")
                person.append(pt_plan)
                selected_modes["pt"] += 1
                output_plan_modes["pt"] += 1
                set_attribute(person, "carAvail", "java.lang.String", "never")
                set_attribute(person, "hasLicense", "java.lang.String", "no")
                remove_attribute(person, "private_car_vehicle_id")
                car_availability["never"] += 1

            if walk_plan is not None:
                walk_plan.set("selected", "no")
                person.append(walk_plan)
                output_plan_modes["walk"] += 1
                counters["walk_plans_preserved"] += 1

            set_attribute(
                person,
                "private_car_ownership_share",
                "java.lang.Double",
                f"{args.car_ownership_share:.6f}",
            )
            set_attribute(
                person,
                "private_car_owner",
                "java.lang.Boolean",
                str(is_owner).lower(),
            )

            plans = person.findall("plan")
            selected = [plan for plan in plans if plan.get("selected") == "yes"]
            if len(selected) != 1:
                violations["selected_plan_count_not_one"] += 1
            pt_count = sum(plan_is_mode(plan, "pt") for plan in plans)
            if pt_count != 1:
                violations["generic_pt_plan_count_not_one"] += 1
            car_count = sum(plan_is_mode(plan, "car") for plan in plans)
            if car_count != (1 if is_owner else 0):
                violations["car_plan_ownership_mismatch"] += 1
            if any(plan_is_mode(plan, mode) for plan in plans for mode in ("bus", "metro")):
                violations["separate_bus_or_metro_plan_present"] += 1
            counters["persons"] += 1
            counters["plans"] += len(plans)
            write_person(out, person)
        out.write("</population>\n")

    vehicle_ids = sorted(car_owner_ids)
    write_private_vehicles(output_vehicles, vehicle_ids)
    actual_share = len(car_owner_ids) / len(persons) if persons else 0.0
    summary = {
        "created_by": "scripts/prepare_fuzhou_car_pt_walk_population.py",
        "created_at_epoch": time.time(),
        "runtime_seconds": round(time.time() - started, 3),
        "input": str(args.input),
        "outputs": {
            "population": str(output_population),
            "private_vehicles": str(output_vehicles),
        },
        "parameters": {
            "car_ownership_share": args.car_ownership_share,
            "seed": args.seed,
            "owner_sampling": "weighted_without_replacement_among_adult_eligible_agents",
        },
        "counts": {
            **dict(counters),
            "eligible_car_agents": len(eligible_items),
            "target_car_owners": target_car_owners,
            "actual_car_owners": len(car_owner_ids),
            "private_vehicles": len(vehicle_ids),
        },
        "actual_car_ownership_share": actual_share,
        "actual_car_ownership_share_pct": round(actual_share * 100, 6),
        "car_availability": dict(car_availability),
        "selected_modes": dict(selected_modes),
        "input_plan_modes": dict(input_plan_modes),
        "output_plan_modes": dict(output_plan_modes),
        "agent_types": dict(agent_types),
        "violations": dict(violations),
        "validation": {
            "person_count_is_51326": len(persons) == 51326,
            "owner_and_vehicle_count_is_10111": len(car_owner_ids) == len(vehicle_ids) == 10111,
            "ownership_error_percentage_points": round(abs(actual_share - args.car_ownership_share) * 100, 8),
            "all_choice_set_invariants_pass": not violations,
        },
    }
    (args.out_dir / "car_pt_walk_population_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
