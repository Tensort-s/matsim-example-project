#!/usr/bin/env python3
"""Calculate completion rates by planned main mode from MATSim outputs."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plans", type=Path, required=True)
    parser.add_argument("--completed-trips", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def routing_mode(leg: ET.Element) -> str | None:
    for attribute in leg.findall("./attributes/attribute"):
        if attribute.get("name") == "routingMode" and attribute.text:
            return attribute.text.strip()
    return None


def main_mode(legs: list[ET.Element]) -> str:
    modes = [leg.get("mode", "") for leg in legs]
    routing_modes = [routing_mode(leg) for leg in legs]
    effective = set(modes) | {item for item in routing_modes if item}
    for mode in ("taxi", "pt", "car", "car_passenger", "walk"):
        if mode in effective:
            return mode
    return next((mode for mode in modes if mode), "unknown")


def selected_trip_modes(person: ET.Element) -> list[str]:
    plans = [item for item in person if local_name(item.tag) == "plan"]
    selected = [item for item in plans if item.get("selected") == "yes"]
    if len(selected) != 1:
        raise ValueError(
            f"Person {person.get('id')} has {len(selected)} selected plans"
        )
    modes: list[str] = []
    legs: list[ET.Element] = []
    seen_origin = False
    for item in selected[0]:
        name = local_name(item.tag)
        if name == "leg":
            legs.append(item)
            continue
        if name != "activity" or item.get("type", "").endswith("interaction"):
            continue
        if not seen_origin:
            seen_origin = True
            continue
        if not legs:
            raise ValueError(f"Person {person.get('id')} has an empty main trip")
        modes.append(main_mode(legs))
        legs = []
    if legs:
        raise ValueError(f"Person {person.get('id')} plan ends with unclosed legs")
    return modes


def open_zstd(path: Path, *, text: bool = False) -> subprocess.Popen:
    return subprocess.Popen(
        ["zstdcat", str(path)], stdout=subprocess.PIPE,
        text=text, encoding="utf-8" if text else None,
    )


def planned_modes(path: Path) -> dict[str, str]:
    process = open_zstd(path)
    assert process.stdout is not None
    result: dict[str, str] = {}
    for _, element in ET.iterparse(process.stdout, events=("end",)):
        if local_name(element.tag) != "person":
            continue
        person_id = element.get("id", "")
        for trip_number, mode in enumerate(selected_trip_modes(element), start=1):
            result[f"{person_id}_{trip_number}"] = mode
        element.clear()
    process.stdout.close()
    if process.wait() != 0:
        raise RuntimeError(f"zstdcat failed for {path}")
    return result


def completed_modes(path: Path) -> dict[str, str]:
    process = open_zstd(path, text=True)
    assert process.stdout is not None
    result = {
        row["trip_id"]: row["main_mode"]
        for row in csv.DictReader(process.stdout, delimiter=";")
    }
    process.stdout.close()
    if process.wait() != 0:
        raise RuntimeError(f"zstdcat failed for {path}")
    return result


def summarize(planned: dict[str, str], completed: dict[str, str]) -> dict[str, object]:
    unknown_completed = sorted(set(completed) - set(planned))
    if unknown_completed:
        raise ValueError(f"Completed trips absent from plans: {unknown_completed[:5]}")
    planned_counts = Counter(planned.values())
    completed_by_planned_mode = Counter(planned[trip_id] for trip_id in completed)
    mode_mismatches = Counter(
        f"{planned[trip_id]}->{mode}"
        for trip_id, mode in completed.items()
        if planned[trip_id] != mode
    )
    modes = sorted(planned_counts)
    return {
        "planned_trips": len(planned),
        "completed_trips": len(completed),
        "overall_completion_rate": len(completed) / len(planned),
        "by_planned_main_mode": {
            mode: {
                "planned": planned_counts[mode],
                "completed": completed_by_planned_mode[mode],
                "unfinished": planned_counts[mode] - completed_by_planned_mode[mode],
                "completion_rate": completed_by_planned_mode[mode] / planned_counts[mode],
            }
            for mode in modes
        },
        "completed_main_mode_mismatches": dict(sorted(mode_mismatches.items())),
    }


def main() -> int:
    args = parse_args()
    for path in (args.plans, args.completed_trips):
        if not path.is_file():
            raise FileNotFoundError(path)
    if args.output.exists():
        raise FileExistsError(args.output)
    summary = summarize(planned_modes(args.plans), completed_modes(args.completed_trips))
    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
