#!/usr/bin/env python3
"""Validate the routed Hong Kong 5% v2 multi-activity population."""

from __future__ import annotations

import argparse
import gzip
import json
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import pandas as pd


WINDOWS_DATA_ROOT = Path(r"F:\Matsim\matsim-example-project\data")
DEFAULT_DATA_ROOT = WINDOWS_DATA_ROOT if WINDOWS_DATA_ROOT.exists() else Path("data")
DEFAULT_SCENARIO = (
    DEFAULT_DATA_ROOT / "matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice"
)
DISCRETIONARY_TYPES = {
    "shopping", "dining", "leisure", "social", "medical", "personal_business",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario-dir", type=Path, default=DEFAULT_SCENARIO)
    parser.add_argument("--plans", type=Path)
    return parser.parse_args()


def parse_attributes(person: ET.Element) -> dict[str, str]:
    container = next(
        child for child in person
        if child.tag.rsplit("}", 1)[-1] == "attributes"
    )
    return {
        child.attrib.get("name", ""): child.text or ""
        for child in container
        if child.tag.rsplit("}", 1)[-1] == "attribute"
    }


def main() -> None:
    args = parse_args()
    scenario = args.scenario_dir.resolve()
    plans = args.plans or scenario / "plans_routed_5pct_v2.xml.gz"
    if not plans.exists():
        raise FileNotFoundError(plans)
    validation = scenario / "validation"
    validation.mkdir(exist_ok=True)

    mode_counts: Counter[str] = Counter()
    activity_counts: Counter[str] = Counter()
    population_counts: Counter[str] = Counter()
    people = legs = route_elements = bad_sequences = 0
    car_legs = car_without_availability = car_without_vehicle = 0
    with gzip.open(plans, "rb") as handle:
        for _, person in ET.iterparse(handle, events=("end",)):
            if person.tag.rsplit("}", 1)[-1] != "person":
                continue
            people += 1
            attributes = parse_attributes(person)
            population_counts[attributes.get("subpopulation", "")] += 1
            plan = next(
                child for child in person
                if child.tag.rsplit("}", 1)[-1] == "plan"
                and child.attrib.get("selected", "yes") == "yes"
            )
            sequence = [child.tag.rsplit("}", 1)[-1] for child in plan]
            if (
                not sequence or sequence[0] != "activity" or sequence[-1] != "activity"
                or any(sequence[index] == sequence[index + 1] for index in range(len(sequence) - 1))
            ):
                bad_sequences += 1
            for child in plan:
                tag = child.tag.rsplit("}", 1)[-1]
                if tag == "activity":
                    activity_counts[child.attrib.get("type", "")] += 1
                elif tag == "leg":
                    legs += 1
                    mode = child.attrib.get("mode", "")
                    mode_counts[mode] += 1
                    routes = [
                        route for route in child
                        if route.tag.rsplit("}", 1)[-1] == "route"
                    ]
                    route_elements += len(routes)
                    if mode == "car":
                        car_legs += 1
                        if attributes.get("carAvail") != "always":
                            car_without_availability += 1
                        vehicle = attributes.get("assignedVehicleId", "")
                        if not vehicle or vehicle.lower() == "nan":
                            car_without_vehicle += 1
            person.clear()

    summary = {
        "plans": str(plans),
        "people": people,
        "legs": legs,
        "route_elements": route_elements,
        "all_legs_have_route": route_elements == legs,
        "bad_activity_leg_sequences": bad_sequences,
        "car_legs": car_legs,
        "car_legs_without_car_availability": car_without_availability,
        "car_legs_without_assigned_vehicle": car_without_vehicle,
        "discretionary_activity_stops": int(sum(activity_counts[key] for key in DISCRETIONARY_TYPES)),
        "population_counts": dict(population_counts),
        "mode_counts": dict(mode_counts),
        "discretionary_activity_counts": {
            key: int(activity_counts[key]) for key in sorted(DISCRETIONARY_TYPES)
        },
    }
    if (
        bad_sequences or route_elements != legs
        or car_without_availability or car_without_vehicle
    ):
        raise RuntimeError(json.dumps(summary, indent=2))
    (validation / "routed_plans_validation.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    pd.DataFrame(
        sorted(mode_counts.items()), columns=["mode", "routed_leg_count"]
    ).to_csv(validation / "routed_mode_counts.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(
        sorted(activity_counts.items()), columns=["activity_type", "activity_count"]
    ).to_csv(validation / "routed_activity_counts.csv", index=False, encoding="utf-8-sig")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
