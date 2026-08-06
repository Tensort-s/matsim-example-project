#!/usr/bin/env python3
"""Merge only the student-exchange routes into Hong Kong no-ride plans.

MATSim's default prepare-for-sim reroutes an entire plan when any trip has a
null route.  The no-ride reallocation intentionally clears 3,824 student legs,
but a whole-plan route-only pass can also change unrelated Car routes that are
covered by static Stage 11 cost tables.  This tool reads that successful
whole-plan routing result and copies only the two exchange trips of each of
1,912 students back into the pre-routing population.  Every non-target trip is
retained from the pre-routing input without reconstruction.
"""

from __future__ import annotations

import argparse
import copy
import csv
import gzip
import json
import re
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterator

from lxml import etree as ET


TAXI_ATTRIBUTES = {
    "hkTaxiFareBaselineHkd",
    "hkTaxiType",
    "hkTaxiFareScope",
    "hkTaxiFareModelVersion",
    "hkTaxiClassificationSource",
    "hkTaxiMainTripIndex",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preroute-plans", type=Path, required=True)
    parser.add_argument("--whole-plan-routed", type=Path, required=True)
    parser.add_argument("--student-pairs-csv", type=Path, required=True)
    parser.add_argument("--output-plans", type=Path, required=True)
    parser.add_argument("--validation-json", type=Path, required=True)
    return parser.parse_args()


def fail(message: str) -> None:
    raise RuntimeError(message)


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


def is_stage_activity(element: ET._Element) -> bool:
    return (
        local_name(element) == "activity"
        and element.get("type", "").endswith(" interaction")
    )


def plan_parts(
    plan: ET._Element,
) -> tuple[
    list[ET._Element],
    list[ET._Element],
    list[list[ET._Element]],
    list[ET._Element],
]:
    children = list(plan)
    main_positions = [
        index
        for index, element in enumerate(children)
        if local_name(element) == "activity" and not is_stage_activity(element)
    ]
    if not main_positions:
        fail("Plan contains no main activity")
    prefix = children[: main_positions[0]]
    activities = [children[index] for index in main_positions]
    segments = [
        children[main_positions[index] + 1 : main_positions[index + 1]]
        for index in range(len(main_positions) - 1)
    ]
    suffix = children[main_positions[-1] + 1 :]
    if len(segments) != len(activities) - 1:
        fail("Main-trip segmentation failed")
    for index, segment in enumerate(segments):
        if not any(local_name(element) == "leg" for element in segment):
            fail(f"Main trip {index} contains no leg")
    return prefix, activities, segments, suffix


def activity_signature(element: ET._Element) -> tuple[str, ...]:
    return tuple(
        element.get(name, "")
        for name in ("type", "x", "y", "link", "facility")
    )


def target_lookup(path: Path) -> dict[str, set[int]]:
    result: dict[str, set[int]] = defaultdict(set)
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            for field in ("displaced_person_id", "donor_person_id"):
                person_id = row[field]
                if not person_id:
                    fail(f"Empty {field} in student exchange pair table")
                result[person_id].update({0, 1})
    if len(result) != 1_912:
        fail(f"Expected 1,912 student exchange persons; found {len(result)}")
    if any(indices != {0, 1} for indices in result.values()):
        fail("Every exchange student must target exactly main trips 0 and 1")
    if sum(len(indices) for indices in result.values()) != 3_824:
        fail("Student exchange leg target is not exactly 3,824")
    return dict(result)


def source_doctype(path: Path) -> str:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        prefix = handle.read(2048)
    match = re.search(r"<!DOCTYPE\s+[^>]+>", prefix)
    if not match:
        fail("Source plans DOCTYPE not found")
    return match.group(0)


def top_level_persons(
    context: Any, root: ET._Element
) -> Iterator[ET._Element]:
    for event, element in context:
        if (
            event == "end"
            and element.getparent() is root
            and local_name(element) == "person"
        ):
            yield element


def clear_top_level(element: ET._Element) -> None:
    element.clear()
    parent = element.getparent()
    if parent is not None:
        while element.getprevious() is not None:
            del parent[0]


def merge_person(
    source_person: ET._Element,
    routed_person: ET._Element,
    target_indices: set[int],
    counters: Counter[str],
) -> None:
    person_id = source_person.get("id", "")
    if routed_person.get("id", "") != person_id:
        fail(
            f"Population person order mismatch: {person_id} != "
            f"{routed_person.get('id', '')}"
        )
    source_plan = selected_plan(source_person)
    routed_plan = selected_plan(routed_person)
    source_prefix, source_activities, source_segments, source_suffix = plan_parts(
        source_plan
    )
    _, routed_activities, routed_segments, _ = plan_parts(routed_plan)
    if len(source_activities) != len(routed_activities):
        fail(f"Main activity count changed for {person_id}")
    for source_activity, routed_activity in zip(
        source_activities, routed_activities
    ):
        if activity_signature(source_activity) != activity_signature(routed_activity):
            fail(f"Main activity signature changed for {person_id}")
    if max(target_indices) >= len(source_segments):
        fail(f"Target trip index missing for {person_id}")

    rebuilt: list[ET._Element] = list(source_prefix)
    for index, activity in enumerate(source_activities[:-1]):
        rebuilt.append(activity)
        if index in target_indices:
            segment = [copy.deepcopy(element) for element in routed_segments[index]]
            if any(
                local_name(element) == "leg"
                and not direct_children(element, "route")
                for element in segment
            ):
                fail(f"Routed target trip still has null route: {person_id}/{index}")
            rebuilt.extend(segment)
            counters["target_main_trips_merged"] += 1
            counters["target_raw_legs_merged"] += sum(
                local_name(element) == "leg" for element in segment
            )
            counters["target_stage_activities_merged"] += sum(
                is_stage_activity(element) for element in segment
            )
        else:
            rebuilt.extend(source_segments[index])
    rebuilt.append(source_activities[-1])
    rebuilt.extend(source_suffix)
    for element in list(source_plan):
        source_plan.remove(element)
    for element in rebuilt:
        source_plan.append(element)


def merge_plans(
    source: Path,
    routed: Path,
    destination: Path,
    targets: dict[str, set[int]],
) -> dict[str, int]:
    counters: Counter[str] = Counter()
    seen_targets: set[str] = set()
    doctype = source_doctype(source)
    with gzip.open(source, "rb") as source_handle, gzip.open(
        routed, "rb"
    ) as routed_handle:
        source_context = ET.iterparse(
            source_handle, events=("start", "end"), huge_tree=True
        )
        routed_context = ET.iterparse(
            routed_handle, events=("start", "end"), huge_tree=True
        )
        source_event, source_root = next(source_context)
        routed_event, routed_root = next(routed_context)
        if source_event != "start" or routed_event != "start":
            fail("Population root start event missing")
        routed_people = top_level_persons(routed_context, routed_root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as raw_output:
            with gzip.GzipFile(
                fileobj=raw_output,
                mode="wb",
                compresslevel=6,
                mtime=0,
            ) as gzip_output:
                with ET.xmlfile(gzip_output, encoding="utf-8") as writer:
                    writer.write_declaration()
                    writer.write_doctype(doctype)
                    with writer.element(source_root.tag, source_root.attrib):
                        for event, source_element in source_context:
                            if (
                                event != "end"
                                or source_element.getparent() is not source_root
                            ):
                                continue
                            if local_name(source_element) != "person":
                                writer.write(source_element)
                                clear_top_level(source_element)
                                continue
                            routed_person = next(routed_people, None)
                            if routed_person is None:
                                fail("Whole-plan routed population ended early")
                            person_id = source_element.get("id", "")
                            if routed_person.get("id", "") != person_id:
                                fail("Source and routed population orders differ")
                            target_indices = targets.get(person_id)
                            if target_indices:
                                merge_person(
                                    source_element,
                                    routed_person,
                                    target_indices,
                                    counters,
                                )
                                seen_targets.add(person_id)
                            writer.write(source_element)
                            counters["persons"] += 1
                            clear_top_level(source_element)
                            clear_top_level(routed_person)
        if next(routed_people, None) is not None:
            fail("Whole-plan routed population contains extra persons")
    missing = set(targets) - seen_targets
    if missing:
        fail(f"Selective merge missed {len(missing)} target persons")
    if counters["persons"] != 385_820:
        fail(f"Unexpected population count {counters['persons']}")
    if counters["target_main_trips_merged"] != 3_824:
        fail("Selective merge did not replace exactly 3,824 main trips")
    return dict(sorted(counters.items()))


def named_attributes(element: ET._Element) -> set[str]:
    return {
        attribute.get("name", "")
        for block in direct_children(element, "attributes")
        for attribute in direct_children(block, "attribute")
    }


def audit_plans(path: Path) -> dict[str, Any]:
    modes: Counter[str] = Counter()
    null_routes = 0
    taxi_without_type = 0
    persons = 0
    legs = 0
    with gzip.open(path, "rb") as handle:
        context = ET.iterparse(handle, events=("end",), tag="person", huge_tree=True)
        for _, person in context:
            persons += 1
            for plan in direct_children(person, "plan"):
                if plan.get("selected") != "yes" and len(direct_children(person, "plan")) > 1:
                    continue
                for leg in direct_children(plan, "leg"):
                    legs += 1
                    mode = leg.get("mode", "")
                    modes[mode] += 1
                    if not direct_children(leg, "route"):
                        null_routes += 1
                    if mode == "taxi" and "hkTaxiType" not in named_attributes(leg):
                        taxi_without_type += 1
            clear_top_level(person)
    return {
        "persons": persons,
        "raw_legs": legs,
        "raw_leg_mode_counts": dict(sorted(modes.items())),
        "null_routes": null_routes,
        "taxi_without_hkTaxiType": taxi_without_type,
        "ride_raw_legs": int(modes.get("ride", 0)),
    }


def main() -> None:
    args = parse_args()
    inputs = [
        args.preroute_plans.resolve(),
        args.whole_plan_routed.resolve(),
        args.student_pairs_csv.resolve(),
    ]
    output = args.output_plans.resolve()
    validation = args.validation_json.resolve()
    missing = [str(path) for path in inputs if not path.is_file()]
    if missing:
        fail("Missing inputs:\n" + "\n".join(missing))
    if output.exists() or validation.exists():
        fail("Selective-route output or validation already exists")
    targets = target_lookup(inputs[2])
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as directory:
        temporary = Path(directory) / output.name
        counters = merge_plans(inputs[0], inputs[1], temporary, targets)
        audit = audit_plans(temporary)
        checks = {
            "persons_exact": audit["persons"] == 385_820,
            "target_main_trips_merged_exact": (
                counters["target_main_trips_merged"] == 3_824
            ),
            "all_routes_non_null": audit["null_routes"] == 0,
            "ride_absent": audit["ride_raw_legs"] == 0,
            "taxi_count_exact": (
                audit["raw_leg_mode_counts"].get("taxi") == 44_000
            ),
            "taxi_types_complete": audit["taxi_without_hkTaxiType"] == 0,
            "car_raw_leg_count_unchanged": (
                audit["raw_leg_mode_counts"].get("car") == 67_718
            ),
            "car_passenger_raw_leg_count_exact": (
                audit["raw_leg_mode_counts"].get("car_passenger") == 2_734
            ),
            "school_bus_raw_leg_count_exact": (
                audit["raw_leg_mode_counts"].get("school_bus") == 9_626
            ),
        }
        if not all(checks.values()):
            fail(f"Selective route validation failed: {checks}; {audit}")
        temporary.replace(output)
    validation.parent.mkdir(parents=True, exist_ok=True)
    with validation.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(
            {
                "status": "validated",
                "all_checks_passed": True,
                "checks": checks,
                "merge_counts": counters,
                "output_audit": audit,
                "scope": (
                    "Only the 3,824 student exchange main trips are copied "
                    "from the whole-plan route-only result; every non-target "
                    "trip remains from the pre-routing population."
                ),
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )
        handle.write("\n")
    print(json.dumps({"checks": checks, "audit": audit}, indent=2))


if __name__ == "__main__":
    main()
