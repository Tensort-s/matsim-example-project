#!/usr/bin/env python3
"""Compare realized MATSim trips before and after ordinary innovation."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, TextIO


@contextmanager
def open_text(path: Path) -> Iterator[TextIO]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
            yield stream
        return
    if path.suffix == ".zst":
        executable = shutil.which("zstd")
        if executable is None:
            raise RuntimeError("Reading .zst requires the zstd executable.")
        process = subprocess.Popen(
            [executable, "-q", "-dc", str(path)],
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        if process.stdout is None:
            raise RuntimeError(f"Could not open zstd stream for {path}")
        try:
            yield process.stdout
        finally:
            process.stdout.close()
            return_code = process.wait()
            if return_code != 0:
                raise RuntimeError(f"zstd failed for {path} with exit code {return_code}")
        return
    with path.open("r", encoding="utf-8", newline="") as stream:
        yield stream


def seconds(value: str) -> int | None:
    if not value or value.lower() in {"undefined", "nan"}:
        return None
    parts = value.split(":")
    if len(parts) != 3:
        raise ValueError(f"Unexpected MATSim time {value!r}")
    return int(parts[0]) * 3_600 + int(parts[1]) * 60 + int(float(parts[2]))


def read_trips(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    with open_text(path) as stream:
        return {
            (row["person"], row["trip_number"]): row
            for row in csv.DictReader(stream, delimiter=";")
        }


def read_pt_legs(path: Path) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = defaultdict(list)
    with open_text(path) as stream:
        for row in csv.DictReader(stream, delimiter=";"):
            if row["mode"] == "pt":
                result[row["trip_id"]].append(row)
    return result


def service_signature(legs: list[dict[str, str]]) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (leg["transit_line"], leg["transit_route"], leg["vehicle_id"])
        for leg in legs
    )


def route_signature(route: ET.Element | None) -> str:
    """Return a stable digest of one network route without retaining link lists."""
    if route is None:
        return "missing"
    payload = "\0".join(
        (
            route.get("type", ""),
            route.get("start_link", ""),
            route.get("end_link", ""),
            " ".join((route.text or "").split()),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def attribute_value(plan: ET.Element, name: str) -> str | None:
    for attribute in plan.findall("./attributes/attribute"):
        if attribute.get("name") == name:
            return (attribute.text or "").strip()
    return None


def read_selected_plan_audit(path: Path) -> dict[str, object]:
    car_routes: dict[tuple[str, int], str] = {}
    role_counts: Counter[str] = Counter()
    total_people = 0
    total_plans = 0
    template_plans = 0
    selected_template_plans = 0
    selected_car_passenger_legs = 0
    selected_unbound_car_passenger_legs = 0

    with open_text(path) as stream:
        for _, person in ET.iterparse(stream, events=("end",)):
            if person.tag != "person":
                continue
            total_people += 1
            person_id = person.get("id", "")
            selected: ET.Element | None = None
            for plan in person.findall("plan"):
                total_plans += 1
                is_template = (attribute_value(plan, "hkHouseholdJointTemplate") or "").lower() == "true"
                if is_template:
                    template_plans += 1
                if plan.get("selected") == "yes":
                    selected = plan
                    if is_template:
                        selected_template_plans += 1
            if selected is not None:
                role_counts[attribute_value(selected, "hkHouseholdJointPlanRole") or "untagged"] += 1
                for leg_index, leg in enumerate(selected.findall("leg")):
                    mode = leg.get("mode", "")
                    if mode == "car":
                        car_routes[(person_id, leg_index)] = route_signature(leg.find("route"))
                    elif mode == "car_passenger":
                        selected_car_passenger_legs += 1
                        if not attribute_value(leg, "hkHouseholdEscortBindingKey"):
                            selected_unbound_car_passenger_legs += 1
            person.clear()

    return {
        "people": total_people,
        "plans": total_plans,
        "temporary_template_plans": template_plans,
        "selected_temporary_template_plans": selected_template_plans,
        "selected_plan_role_counts": dict(sorted(role_counts.items())),
        "selected_car_passenger_legs": selected_car_passenger_legs,
        "selected_unbound_car_passenger_legs": selected_unbound_car_passenger_legs,
        "car_routes": car_routes,
    }


def compare_selected_plans(baseline_path: Path, final_path: Path) -> dict[str, object]:
    baseline = read_selected_plan_audit(baseline_path)
    final = read_selected_plan_audit(final_path)
    baseline_routes = baseline.pop("car_routes")
    final_routes = final.pop("car_routes")
    assert isinstance(baseline_routes, dict)
    assert isinstance(final_routes, dict)
    common = set(baseline_routes) & set(final_routes)
    changed = sum(baseline_routes[key] != final_routes[key] for key in common)
    return {
        "baseline_plans": str(baseline_path),
        "final_plans": str(final_path),
        "baseline_selected_plan_integrity": baseline,
        "final_selected_plan_integrity": final,
        "private_car_route_innovation": {
            "baseline_selected_car_legs": len(baseline_routes),
            "final_selected_car_legs": len(final_routes),
            "common_person_leg_keys": len(common),
            "changed_network_route_sequences": changed,
            "unchanged_network_route_sequences": len(common) - changed,
        },
    }


def summarize(args: argparse.Namespace) -> dict[str, object]:
    baseline = read_trips(args.baseline_trips)
    final = read_trips(args.final_trips)
    baseline_pt_legs = read_pt_legs(args.baseline_legs)
    final_pt_legs = read_pt_legs(args.final_legs)
    common = sorted(set(baseline) & set(final))

    transitions: Counter[str] = Counter()
    final_modes: Counter[str] = Counter()
    departure_changes_by_final_mode: Counter[str] = Counter()
    departure_offsets: list[int] = []
    retained_pt = 0
    retained_pt_departure_changed = 0
    retained_pt_first_boarding_changed = 0
    retained_pt_service_changed = 0
    retained_pt_vehicle_changed = 0

    for key in common:
        before = baseline[key]
        after = final[key]
        before_mode = before["main_mode"]
        after_mode = after["main_mode"]
        transitions[f"{before_mode}->{after_mode}"] += 1
        final_modes[after_mode] += 1
        before_departure = seconds(before["dep_time"])
        after_departure = seconds(after["dep_time"])
        if before_departure is not None and after_departure is not None:
            offset = after_departure - before_departure
            departure_offsets.append(offset)
            if offset != 0:
                departure_changes_by_final_mode[after_mode] += 1

        if before_mode != "pt" or after_mode != "pt":
            continue
        retained_pt += 1
        if before_departure != after_departure:
            retained_pt_departure_changed += 1
        before_legs = baseline_pt_legs.get(before["trip_id"], [])
        after_legs = final_pt_legs.get(after["trip_id"], [])
        before_boarding = seconds(before_legs[0]["dep_time"]) if before_legs else None
        after_boarding = seconds(after_legs[0]["dep_time"]) if after_legs else None
        if before_boarding != after_boarding:
            retained_pt_first_boarding_changed += 1
        before_signature = service_signature(before_legs)
        after_signature = service_signature(after_legs)
        if before_signature != after_signature:
            retained_pt_service_changed += 1
        if tuple(value[2] for value in before_signature) != tuple(
            value[2] for value in after_signature
        ):
            retained_pt_vehicle_changed += 1

    offsets_sorted = sorted(departure_offsets)

    def percentile(fraction: float) -> int | None:
        if not offsets_sorted:
            return None
        index = round((len(offsets_sorted) - 1) * fraction)
        return offsets_sorted[index]

    summary: dict[str, object] = {
        "inputs": {
            "baseline_trips": str(args.baseline_trips),
            "baseline_legs": str(args.baseline_legs),
            "final_trips": str(args.final_trips),
            "final_legs": str(args.final_legs),
        },
        "trip_reference_integrity": {
            "baseline_trips": len(baseline),
            "final_trips": len(final),
            "common_person_trip_keys": len(common),
            "baseline_only_keys": len(set(baseline) - set(final)),
            "final_only_keys": len(set(final) - set(baseline)),
        },
        "mode_innovation": {
            "final_mode_counts": dict(sorted(final_modes.items())),
            "mode_transition_counts": dict(sorted(transitions.items())),
        },
        "time_innovation": {
            "changed_departures_by_final_mode": dict(
                sorted(departure_changes_by_final_mode.items())
            ),
            "departure_offset_seconds_p05": percentile(0.05),
            "departure_offset_seconds_p50": percentile(0.50),
            "departure_offset_seconds_p95": percentile(0.95),
        },
        "retained_pt_schedule_adaptation": {
            "retained_pt_trips": retained_pt,
            "main_trip_departure_changed": retained_pt_departure_changed,
            "first_pt_boarding_time_changed": retained_pt_first_boarding_changed,
            "transit_service_sequence_changed": retained_pt_service_changed,
            "transit_vehicle_sequence_changed": retained_pt_vehicle_changed,
        },
    }
    if args.baseline_plans is not None and args.final_plans is not None:
        summary["selected_plan_innovation"] = compare_selected_plans(
            args.baseline_plans, args.final_plans
        )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-trips", type=Path, required=True)
    parser.add_argument("--baseline-legs", type=Path, required=True)
    parser.add_argument("--final-trips", type=Path, required=True)
    parser.add_argument("--final-legs", type=Path, required=True)
    parser.add_argument("--baseline-plans", type=Path)
    parser.add_argument("--final-plans", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (args.baseline_plans is None) != (args.final_plans is None):
        parser.error("--baseline-plans and --final-plans must be supplied together")
    return args


def main() -> None:
    args = parse_args()
    summary = summarize(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
