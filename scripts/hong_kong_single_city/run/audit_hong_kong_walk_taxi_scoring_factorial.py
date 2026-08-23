#!/usr/bin/env python3
"""Audit the four-arm Hong Kong Walk/Taxi scoring factorial experiment."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
import csv
import gzip
import json
import math
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET


ARMS = ("a0", "a1", "a2", "a3")
MODES = ("car", "car_passenger", "pt", "taxi", "walk")
TOTAL_TRIPS = 743_614


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initial-plans", type=Path, required=True)
    parser.add_argument(
        "--arm", action="append", required=True, metavar="A0=RUN",
        help="Repeat once for each of a0, a1, a2, and a3.",
    )
    parser.add_argument("--iterations", default="0-9")
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def parse_iterations(value: str) -> list[int]:
    if "-" in value and "," not in value:
        start, end = (int(item) for item in value.split("-", 1))
        result = list(range(start, end + 1))
    else:
        result = [int(item) for item in value.split(",")]
    if not result or result != sorted(set(result)) or result[0] < 0:
        raise ValueError(f"Invalid iteration schedule: {value}")
    return result


def parse_arms(values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        name, separator, raw_path = value.partition("=")
        if not separator or name not in ARMS or name in result:
            raise ValueError(f"Invalid or duplicate arm: {value}")
        result[name] = Path(raw_path)
    if set(result) != set(ARMS):
        raise ValueError(f"Expected arms {ARMS}; found {sorted(result)}")
    return result


@contextmanager
def open_binary(path: Path):
    if path.suffix == ".gz":
        with gzip.open(path, "rb") as source:
            yield source
        return
    if path.suffix == ".zst":
        process = subprocess.Popen(["zstdcat", str(path)], stdout=subprocess.PIPE)
        assert process.stdout is not None
        try:
            yield process.stdout
        finally:
            process.stdout.close()
            if process.wait() != 0:
                raise RuntimeError(f"zstdcat failed for {path}")
        return
    with path.open("rb") as source:
        yield source


@contextmanager
def open_text(path: Path):
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", newline="") as source:
            yield source
        return
    if path.suffix == ".zst":
        process = subprocess.Popen(
            ["zstdcat", str(path)], stdout=subprocess.PIPE,
            text=True, encoding="utf-8",
        )
        assert process.stdout is not None
        try:
            yield process.stdout
        finally:
            process.stdout.close()
            if process.wait() != 0:
                raise RuntimeError(f"zstdcat failed for {path}")
        return
    with path.open("r", encoding="utf-8", newline="") as source:
        yield source


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def leg_routing_mode(leg: ET.Element) -> str | None:
    for attribute in leg.findall("./attributes/attribute"):
        if attribute.get("name") == "routingMode" and attribute.text:
            return attribute.text.strip()
    return None


def main_mode(legs: list[ET.Element]) -> str:
    modes = [leg.get("mode", "") for leg in legs]
    effective = set(modes) | {
        value for leg in legs if (value := leg_routing_mode(leg))
    }
    for mode in ("taxi", "pt", "car", "car_passenger", "walk"):
        if mode in effective:
            return mode
    return next((mode for mode in modes if mode), "unknown")


def selected_trip_modes(person: ET.Element) -> list[str]:
    plans = [item for item in person if local_name(item.tag) == "plan"]
    selected = [item for item in plans if item.get("selected") == "yes"]
    if len(selected) != 1:
        raise ValueError(f"Person {person.get('id')} has {len(selected)} selected plans")
    result: list[str] = []
    legs: list[ET.Element] = []
    seen_origin = False
    for item in selected[0]:
        name = local_name(item.tag)
        if name == "leg":
            legs.append(item)
        elif name == "activity" and not item.get("type", "").endswith("interaction"):
            if not seen_origin:
                seen_origin = True
            else:
                if not legs:
                    raise ValueError(f"Person {person.get('id')} has an empty trip")
                result.append(main_mode(legs))
                legs = []
    if legs:
        raise ValueError(f"Person {person.get('id')} plan ends with unclosed legs")
    return result


def planned_modes(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise FileNotFoundError(path)
    result: dict[str, str] = {}
    with open_binary(path) as source:
        for _, element in ET.iterparse(source, events=("end",)):
            if local_name(element.tag) != "person":
                continue
            person_id = element.get("id", "")
            for trip_number, mode in enumerate(selected_trip_modes(element), start=1):
                result[f"{person_id}_{trip_number}"] = mode
            element.clear()
    return result


def seconds(value: str) -> float:
    hours, minutes, secs = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(secs)


def completed_trips(path: Path) -> dict[str, tuple[str, float]]:
    result: dict[str, tuple[str, float]] = {}
    with open_text(path) as source:
        for row in csv.DictReader(source, delimiter=";"):
            trip_id = row["trip_id"]
            if trip_id in result:
                raise ValueError(f"Duplicate completed trip: {trip_id}")
            result[trip_id] = (row["main_mode"], seconds(row["trav_time"]))
    return result


def percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def taxi_metrics(path: Path, arm: str) -> dict[str, object]:
    statuses: Counter[str] = Counter()
    waits: list[float] = []
    rides: list[float] = []
    with gzip.open(path, "rt", encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            status = row["status"]
            statuses[status] += 1
            if status in {"completed", "onboard"}:
                waits.append(float(row["wait_s"]))
            if status == "completed":
                rides.append(float(row["dropped_off_s"]) - float(row["picked_up_s"]))
    submitted = sum(statuses.values())
    unpicked = statuses["waiting"] + statuses["rejected"]
    wait_coefficient = -18.0 if arm in {"a1", "a3"} else -12.0
    return {
        "submitted": submitted,
        "statuses": dict(statuses),
        "request_conservation": submitted == sum(statuses.values()),
        "completion_rate": statuses["completed"] / submitted if submitted else None,
        "unpicked_share": unpicked / submitted if submitted else None,
        "wait_mean_s": sum(waits) / len(waits) if waits else None,
        "wait_p50_s": percentile(waits, 0.50),
        "wait_p90_s": percentile(waits, 0.90),
        "wait_p95_s": percentile(waits, 0.95),
        "ride_mean_s": sum(rides) / len(rides) if rides else None,
        "mean_completed_wait_score": (
            wait_coefficient * sum(waits) / len(waits) / 3600 if waits else None
        ),
        "mean_completed_in_vehicle_score": (
            -6.0 * sum(rides) / len(rides) / 3600 if rides else None
        ),
        "constant_per_submitted_taxi_leg": -9.0,
    }


def score_by_iteration(path: Path) -> dict[int, float]:
    with path.open("r", encoding="utf-8", newline="") as source:
        return {
            int(row["iteration"]): float(row["avg_executed"])
            for row in csv.DictReader(source, delimiter=";")
        }


def iteration_metrics(
    planned: dict[str, str], completed: dict[str, tuple[str, float]],
    taxi: dict[str, object], average_score: float,
) -> dict[str, object]:
    unknown = set(completed) - set(planned)
    if unknown:
        raise ValueError(f"Completed trips absent from plans: {sorted(unknown)[:5]}")
    planned_counts = Counter(planned.values())
    completed_counts: Counter[str] = Counter()
    duration_sums: defaultdict[str, float] = defaultdict(float)
    mismatches: Counter[str] = Counter()
    walk_durations: list[float] = []
    for trip_id, (actual_mode, duration) in completed.items():
        planned_mode = planned[trip_id]
        completed_counts[planned_mode] += 1
        duration_sums[planned_mode] += duration
        if planned_mode != actual_mode:
            mismatches[f"{planned_mode}->{actual_mode}"] += 1
        if planned_mode == "walk":
            walk_durations.append(duration)
    total = len(planned)
    by_mode = {
        mode: {
            "planned": planned_counts[mode],
            "share": planned_counts[mode] / total,
            "completed": completed_counts[mode],
            "completion_rate": completed_counts[mode] / planned_counts[mode],
            "mean_completed_minutes": (
                duration_sums[mode] / completed_counts[mode] / 60
                if completed_counts[mode] else None
            ),
        }
        for mode in sorted(planned_counts)
    }
    walk_count = len(walk_durations)
    walk_bands = {
        "at_most_10_minutes": sum(value <= 600 for value in walk_durations),
        "over_10_to_15_minutes": sum(600 < value <= 900 for value in walk_durations),
        "over_15_minutes": sum(value > 900 for value in walk_durations),
    }
    return {
        "planned_trips": total,
        "completed_trips": len(completed),
        "overall_completion_rate": len(completed) / total,
        "average_executed_score": average_score,
        "by_planned_mode": by_mode,
        "completed_mode_mismatches": dict(sorted(mismatches.items())),
        "walk_duration_bands": {
            key: {"count": value, "share": value / walk_count if walk_count else None}
            for key, value in walk_bands.items()
        },
        "taxi_requests": taxi,
    }


def scalar_metrics(metrics: dict[str, object]) -> dict[str, float]:
    by_mode = metrics["by_planned_mode"]
    taxi = metrics["taxi_requests"]
    return {
        "overall_completion_rate": metrics["overall_completion_rate"],
        "average_executed_score": metrics["average_executed_score"],
        "taxi_share": by_mode["taxi"]["share"],
        "taxi_completion_rate": by_mode["taxi"]["completion_rate"],
        "taxi_mean_completed_minutes": by_mode["taxi"]["mean_completed_minutes"],
        "taxi_wait_mean_s": taxi["wait_mean_s"],
        "walk_share": by_mode["walk"]["share"],
        "walk_completion_rate": by_mode["walk"]["completion_rate"],
        "walk_mean_completed_minutes": by_mode["walk"]["mean_completed_minutes"],
    }


def factorial_effects(final: dict[str, dict[str, object]]) -> dict[str, object]:
    scalars = {arm: scalar_metrics(metrics) for arm, metrics in final.items()}
    result: dict[str, object] = {}
    for metric in scalars["a0"]:
        values = {arm: scalars[arm][metric] for arm in ARMS}
        result[metric] = {
            "values": values,
            "taxi_formula_main_effect": (
                (values["a1"] + values["a3"] - values["a0"] - values["a2"]) / 2
            ),
            "walk_formula_main_effect": (
                (values["a2"] + values["a3"] - values["a0"] - values["a1"]) / 2
            ),
            "interaction": values["a3"] - values["a2"] - values["a1"] + values["a0"],
        }
    return result


def main() -> int:
    args = parse_args()
    arms = parse_arms(args.arm)
    iterations = parse_iterations(args.iterations)
    if args.output_dir.exists():
        raise FileExistsError(args.output_dir)
    args.output_dir.mkdir(parents=True)
    initial = planned_modes(args.initial_plans)
    if len(initial) != TOTAL_TRIPS:
        raise ValueError(f"Expected {TOTAL_TRIPS} initial trips; found {len(initial)}")
    initial_counts = Counter(initial.values())

    summary: dict[str, object] = {
        "initial_plans": str(args.initial_plans),
        "iterations": iterations,
        "arms": {},
    }
    metric_rows: list[dict[str, object]] = []
    transition_rows: list[dict[str, object]] = []
    final_metrics: dict[str, dict[str, object]] = {}
    for arm in ARMS:
        run = arms[arm]
        exit_code = (run / "exit_code.txt").read_text(encoding="utf-8").strip()
        if exit_code != "0":
            raise ValueError(f"{arm} did not exit successfully: {exit_code}")
        scores = score_by_iteration(run / "output/scorestats.csv")
        arm_iterations: dict[str, object] = {}
        final_planned: dict[str, str] | None = None
        for iteration in iterations:
            iteration_dir = run / f"output/ITERS/it.{iteration}"
            planned = planned_modes(iteration_dir / f"{iteration}.plans.xml.zst")
            completed = completed_trips(iteration_dir / f"{iteration}.trips.csv.zst")
            taxi = taxi_metrics(
                iteration_dir / f"{iteration}.taxi_request_audit.csv.gz", arm
            )
            metrics = iteration_metrics(planned, completed, taxi, scores[iteration])
            arm_iterations[str(iteration)] = metrics
            row: dict[str, object] = {"arm": arm, "iteration": iteration}
            row.update(scalar_metrics(metrics))
            metric_rows.append(row)
            if iteration == iterations[-1]:
                final_planned = planned
                final_metrics[arm] = metrics
        assert final_planned is not None
        transitions = Counter(
            (initial[trip_id], final_mode)
            for trip_id, final_mode in final_planned.items()
        )
        for (initial_mode, final_mode), count in sorted(transitions.items()):
            transition_rows.append({
                "arm": arm,
                "initial_mode": initial_mode,
                "final_mode": final_mode,
                "count": count,
                "share_of_initial_mode": count / initial_counts[initial_mode],
            })
        summary["arms"][arm] = {
            "run": str(run),
            "iterations": arm_iterations,
        }
    summary["factorial_effects_at_final_iteration"] = factorial_effects(final_metrics)

    (args.output_dir / "factorial_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for name, rows in (
        ("iteration_metrics.csv", metric_rows),
        ("mode_transition_matrix.csv", transition_rows),
    ):
        with (args.output_dir / name).open("w", encoding="utf-8", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    print(json.dumps({
        "status": "PASS",
        "output_dir": str(args.output_dir),
        "arms": list(ARMS),
        "iterations": iterations,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
