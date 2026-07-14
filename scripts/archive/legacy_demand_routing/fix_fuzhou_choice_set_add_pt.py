"""Fix Fuzhou mode-choice population choice set and add generic PT plans.

This post-processes an existing MATSim population that already contains
car/bus/metro/walk candidate plans.

Changes:
- add one generic ``pt`` candidate plan to each person, if missing;
- remove all ``car`` plans for persons whose ``carAvail`` attribute is
  ``never``;
- if the selected plan is removed, select the best available fallback in the
  order metro -> pt -> bus -> walk -> first remaining plan;
- write a compact QA summary for checking the resulting choice set.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import json
import pathlib
import time
import xml.etree.ElementTree as ET
from collections import Counter


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_INPUT = (
    ROOT
    / "data"
    / "matsim_routes"
    / "fuzhou_city_23_greenspace_grid_multi_activity_2pct_busprio_floor_snapspread"
    / "mode_choice_plans_bus_metro_2pct_snapspread.xml.gz"
)
DEFAULT_OUTPUT = (
    ROOT
    / "data"
    / "matsim_routes"
    / "fuzhou_city_23_greenspace_grid_multi_activity_2pct_busprio_floor_snapspread_choicefix_pt"
    / "mode_choice_plans_bus_metro_pt_2pct_choicefix.xml.gz"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=pathlib.Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=pathlib.Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--summary",
        type=pathlib.Path,
        default=None,
        help="Optional summary JSON path. Defaults to output sibling.",
    )
    return parser.parse_args()


def open_text(path: pathlib.Path, mode: str):
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


def first_leg_mode(plan: ET.Element) -> str:
    leg = plan.find("leg")
    if leg is None:
        return ""
    return leg.get("mode", "")


def plan_modes(plan: ET.Element) -> set[str]:
    return {leg.get("mode", "") for leg in plan.findall("leg") if leg.get("mode")}


def is_car_plan(plan: ET.Element) -> bool:
    modes = plan_modes(plan)
    return bool(modes) and modes == {"car"}


def has_plan_mode(person: ET.Element, mode: str) -> bool:
    for plan in person.findall("plan"):
        modes = plan_modes(plan)
        if modes and modes == {mode}:
            return True
    return False


def clone_mode_plan(plan: ET.Element, mode: str) -> ET.Element:
    cloned = copy.deepcopy(plan)
    cloned.set("selected", "no")
    for leg in cloned.findall("leg"):
        leg.set("mode", mode)
        for route in list(leg.findall("route")):
            leg.remove(route)
    return cloned


def select_plan(person: ET.Element, plan: ET.Element) -> None:
    for candidate in person.findall("plan"):
        candidate.set("selected", "yes" if candidate is plan else "no")


def selected_plan(person: ET.Element) -> ET.Element | None:
    for plan in person.findall("plan"):
        if plan.get("selected") == "yes":
            return plan
    plans = person.findall("plan")
    return plans[0] if plans else None


def choose_fallback_plan(person: ET.Element) -> ET.Element | None:
    plans = person.findall("plan")
    for mode in ("metro", "pt", "bus", "walk"):
        for plan in plans:
            modes = plan_modes(plan)
            if modes and modes == {mode}:
                return plan
    return plans[0] if plans else None


def write_person(handle, person: ET.Element) -> None:
    xml = ET.tostring(person, encoding="unicode", short_empty_elements=True)
    handle.write(f"  {xml}\n")


def main() -> None:
    args = parse_args()
    started = time.time()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    summary_path = args.summary or args.output.with_name("choice_set_fix_summary.json")

    counters: Counter[str] = Counter()
    selected_modes: Counter[str] = Counter()
    plan_mode_counts: Counter[str] = Counter()
    car_avail_counts: Counter[str] = Counter()

    with open_text(args.output, "wt") as out:
        out.write('<?xml version="1.0" encoding="utf-8"?>\n')
        out.write('<!DOCTYPE population SYSTEM "http://www.matsim.org/files/dtd/population_v6.dtd">\n')
        out.write("<population>\n")

        context = ET.iterparse(open_text(args.input, "rt"), events=("end",))
        for _, elem in context:
            if elem.tag != "person":
                continue

            person = copy.deepcopy(elem)
            elem.clear()
            counters["persons"] += 1

            avail = get_attribute(person, "carAvail", "unknown")
            car_avail_counts[avail] += 1

            source = selected_plan(person) or (person.findall("plan")[0] if person.findall("plan") else None)
            if source is not None and not has_plan_mode(person, "pt"):
                person.append(clone_mode_plan(source, "pt"))
                counters["pt_candidate_added"] += 1

            selected_before = selected_plan(person)
            selected_removed = False
            if avail == "never":
                for plan in list(person.findall("plan")):
                    if is_car_plan(plan):
                        if plan is selected_before:
                            selected_removed = True
                        person.remove(plan)
                        counters["car_plans_removed_for_caravail_never"] += 1

            plans = person.findall("plan")
            if not plans:
                counters["persons_without_plans_after_fix"] += 1
                continue

            selected_after = selected_plan(person)
            if selected_after is None or selected_after not in plans or selected_removed:
                fallback = choose_fallback_plan(person)
                if fallback is not None:
                    select_plan(person, fallback)
                    counters["selected_plan_reassigned"] += 1
            else:
                select_plan(person, selected_after)

            selected_final = selected_plan(person)
            if selected_final is not None:
                selected_modes[first_leg_mode(selected_final)] += 1

            for plan in person.findall("plan"):
                mode = first_leg_mode(plan) or "unknown"
                plan_mode_counts[mode] += 1
                counters["plans"] += 1

            write_person(out, person)

        out.write("</population>\n")

    summary = {
        "created_by": "scripts/fix_fuzhou_choice_set_add_pt.py",
        "created_at_epoch": time.time(),
        "runtime_seconds": round(time.time() - started, 3),
        "input": str(args.input),
        "output": str(args.output),
        "counts": dict(counters),
        "car_availability": dict(car_avail_counts),
        "selected_modes_after_fix": dict(selected_modes),
        "plan_modes_after_fix": dict(plan_mode_counts),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
