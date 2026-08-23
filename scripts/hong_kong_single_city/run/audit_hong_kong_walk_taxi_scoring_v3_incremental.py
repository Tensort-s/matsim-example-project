#!/usr/bin/env python3
"""Audit the B0/B1/B2 incremental screen before permitting combined B3."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
from pathlib import Path

from audit_hong_kong_walk_taxi_scoring_factorial import (
    TOTAL_TRIPS,
    completed_trips,
    iteration_metrics,
    parse_iterations,
    planned_modes,
    scalar_metrics,
    score_by_iteration,
    taxi_metrics,
)


ARMS = ("b0", "b1", "b2")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initial-plans", type=Path, required=True)
    parser.add_argument(
        "--arm", action="append", required=True, metavar="B0=RUN",
        help="Repeat for b0 (the completed A3 baseline), b1, and b2.",
    )
    parser.add_argument("--iterations", default="0-9")
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


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


def relative_range(values: list[float]) -> float:
    average = sum(values) / len(values)
    return (max(values) - min(values)) / average if average else 0.0


def last_three_gates(rows: list[dict[str, object]], arm: str, mode: str) -> dict[str, object]:
    selected = [row for row in rows if row["arm"] == arm][-3:]
    shares = [float(row[f"{mode}_share"]) for row in selected]
    means = [float(row[f"{mode}_mean_completed_minutes"]) for row in selected]
    return {
        "share_range_pp": 100.0 * (max(shares) - min(shares)),
        "mean_range_fraction": relative_range(means),
        "share_stable": max(shares) - min(shares) <= 0.005,
        "mean_stable": relative_range(means) <= 0.05,
    }


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
    metric_rows: list[dict[str, object]] = []
    transition_rows: list[dict[str, object]] = []
    final: dict[str, dict[str, object]] = {}

    for arm in ARMS:
        run = arms[arm]
        if (run / "exit_code.txt").read_text(encoding="utf-8").strip() != "0":
            raise ValueError(f"{arm} did not exit successfully")
        scores = score_by_iteration(run / "output/scorestats.csv")
        final_planned: dict[str, str] | None = None
        for iteration in iterations:
            iteration_dir = run / f"output/ITERS/it.{iteration}"
            planned = planned_modes(iteration_dir / f"{iteration}.plans.xml.zst")
            completed = completed_trips(iteration_dir / f"{iteration}.trips.csv.zst")
            taxi = taxi_metrics(
                iteration_dir / f"{iteration}.taxi_request_audit.csv.gz", "a3"
            )
            taxi["constant_per_submitted_taxi_leg"] = -9.6 if arm == "b1" else -9.0
            metrics = iteration_metrics(planned, completed, taxi, scores[iteration])
            row: dict[str, object] = {"arm": arm, "iteration": iteration}
            row.update(scalar_metrics(metrics))
            metric_rows.append(row)
            if iteration == iterations[-1]:
                final[arm] = metrics
                final_planned = planned
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

    b0, b1, b2 = final["b0"], final["b1"], final["b2"]
    b1_taxi = b1["by_planned_mode"]["taxi"]
    b1_requests = b1["taxi_requests"]
    b2_walk = b2["by_planned_mode"]["walk"]
    b2_bands = b2["walk_duration_bands"]
    b1_stability = last_three_gates(metric_rows, "b1", "taxi")
    b2_stability = last_three_gates(metric_rows, "b2", "walk")
    relative_floor = b0["overall_completion_rate"] - 0.002

    gates = {
        "b1_taxi_share": 0.05 <= b1_taxi["share"] <= 0.07,
        "b1_taxi_request_completion": b1_requests["completion_rate"] >= 0.99,
        "b1_taxi_unpicked": b1_requests["unpicked_share"] <= 0.005,
        "b1_taxi_request_conservation": b1_requests["request_conservation"],
        "b1_overall_relative": b1["overall_completion_rate"] >= relative_floor,
        "b1_taxi_share_stable": b1_stability["share_stable"],
        "b1_taxi_mean_stable": b1_stability["mean_stable"],
        "b2_walk_share": 0.105 <= b2_walk["share"] <= 0.12,
        "b2_walk_mean_minutes": 12.0 <= b2_walk["mean_completed_minutes"] <= 15.0,
        "b2_walk_at_most_10_share": (
            0.60 <= b2_bands["at_most_10_minutes"]["share"] <= 0.68
        ),
        "b2_walk_over_15_share": (
            0.12 <= b2_bands["over_15_minutes"]["share"] <= 0.18
        ),
        "b2_walk_completion": b2_walk["completion_rate"] >= 0.995,
        "b2_overall_relative": b2["overall_completion_rate"] >= relative_floor,
        "b2_walk_share_stable": b2_stability["share_stable"],
        "b2_walk_mean_stable": b2_stability["mean_stable"],
    }
    failed = [name for name, passed in gates.items() if not passed]
    summary = {
        "status": "PASS" if not failed else "SCREENING_FAIL",
        "b3_allowed": not failed,
        "baseline": {"arm": "b0", "run": str(arms["b0"])},
        "iterations": iterations,
        "final": final,
        "last3": {"b1_taxi": b1_stability, "b2_walk": b2_stability},
        "gates": gates,
        "failed_gates": failed,
        "note": (
            "Taxi p50/mean wait are diagnostic, not B1 score-formula gates; "
            "fleet availability and dispatch calibrate that separate supply outcome."
        ),
    }
    (args.output_dir / "incremental_summary.json").write_text(
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
        "status": summary["status"],
        "b3_allowed": summary["b3_allowed"],
        "failed_gates": failed,
        "output_dir": str(args.output_dir),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
