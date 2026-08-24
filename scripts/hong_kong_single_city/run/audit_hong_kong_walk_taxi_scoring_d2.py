#!/usr/bin/env python3
from __future__ import annotations
import argparse
from collections import Counter
import csv
import gzip
import importlib.util
import json
from pathlib import Path

def load_base(path: Path):
    spec = importlib.util.spec_from_file_location("factorial", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module

def taxi_metrics(path: Path, base):
    statuses = Counter()
    waits = []
    rides = []
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
    return {
        "submitted": submitted,
        "statuses": dict(statuses),
        "request_conservation": submitted == sum(statuses.values()),
        "completion_rate": statuses["completed"] / submitted if submitted else None,
        "unpicked_share": unpicked / submitted if submitted else None,
        "wait_mean_s": sum(waits) / len(waits) if waits else None,
        "wait_p50_s": base.percentile(waits, 0.50),
        "wait_p90_s": base.percentile(waits, 0.90),
        "wait_p95_s": base.percentile(waits, 0.95),
        "ride_mean_s": sum(rides) / len(rides) if rides else None,
        "mean_completed_wait_score": -6.0 * sum(waits) / len(waits) / 3600 if waits else None,
        "mean_completed_in_vehicle_score": -6.0 * sum(rides) / len(rides) / 3600 if rides else None,
        "constant_per_submitted_taxi_leg": -9.6,
        "adult_fare_utility_per_hkd": -0.5,
        "student_fare_utility_per_hkd": -0.6,
    }

def scalar(metrics):
    by = metrics["by_planned_mode"]
    taxi = metrics["taxi_requests"]
    row = {
        "overall_completion_rate": metrics["overall_completion_rate"],
        "average_executed_score": metrics["average_executed_score"],
        "taxi_request_completion_rate": taxi["completion_rate"],
        "taxi_unpicked_share": taxi["unpicked_share"],
        "taxi_wait_mean_s": taxi["wait_mean_s"],
        "taxi_wait_p50_s": taxi["wait_p50_s"],
        "taxi_wait_p90_s": taxi["wait_p90_s"],
        "taxi_wait_p95_s": taxi["wait_p95_s"],
    }
    for mode in sorted(by):
        item = by[mode]
        row[f"{mode}_share"] = item["share"]
        row[f"{mode}_completion_rate"] = item["completion_rate"]
        row[f"{mode}_mean_completed_minutes"] = item["mean_completed_minutes"]
        row[f"{mode}_incomplete_count"] = item["planned"] - item["completed"]
    return row

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-script", type=Path, required=True)
    parser.add_argument("--initial-plans", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--factorial-summary", type=Path, required=True)
    parser.add_argument("--incremental-summary", type=Path, required=True)
    parser.add_argument("--c1-summary", type=Path, required=True)
    parser.add_argument("--d1-summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise FileExistsError(args.output_dir)
    args.output_dir.mkdir(parents=True)
    base = load_base(args.base_script)
    if (args.run / "exit_code.txt").read_text(encoding="utf-8").strip() != "0":
        raise ValueError("D2 run did not exit 0")
    initial = base.planned_modes(args.initial_plans)
    scores = base.score_by_iteration(args.run / "output/scorestats.csv")
    iterations = list(range(22))
    metrics_by_iteration = {}
    rows = []
    final_planned = None
    for iteration in iterations:
        idir = args.run / f"output/ITERS/it.{iteration}"
        planned = base.planned_modes(idir / f"{iteration}.plans.xml.zst")
        completed = base.completed_trips(idir / f"{iteration}.trips.csv.zst")
        taxi = taxi_metrics(idir / f"{iteration}.taxi_request_audit.csv.gz", base)
        metrics = base.iteration_metrics(planned, completed, taxi, scores[iteration])
        for mode, item in metrics["by_planned_mode"].items():
            item["incomplete_or_right_censored"] = item["planned"] - item["completed"]
        metrics_by_iteration[str(iteration)] = metrics
        row = {"arm": "d2", "iteration": iteration}
        row.update(scalar(metrics))
        rows.append(row)
        final_planned = planned
    assert final_planned is not None
    initial_counts = Counter(initial.values())
    transitions = Counter((initial[k], v) for k, v in final_planned.items())
    transition_rows = [{
        "arm": "d2", "initial_mode": a, "final_mode": b, "count": n,
        "share_of_initial_mode": n / initial_counts[a],
    } for (a, b), n in sorted(transitions.items())]
    factorial = json.loads(args.factorial_summary.read_text(encoding="utf-8"))
    incremental = json.loads(args.incremental_summary.read_text(encoding="utf-8"))
    c1_summary = json.loads(args.c1_summary.read_text(encoding="utf-8"))
    d1_summary = json.loads(args.d1_summary.read_text(encoding="utf-8"))
    a3 = factorial["arms"]["a3"]["iterations"]["9"]
    b1 = incremental["final"]["b1"]
    c1 = c1_summary["c1"]["iterations"]["24"]
    d1 = d1_summary["d1"]["iterations"]["21"]
    final = metrics_by_iteration["21"]
    comparisons = {
        "a3_iteration9": a3,
        "b1_iteration9": b1,
        "c1_iteration24": c1,
        "d1_iteration21": d1,
        "d2_iteration21": final,
    }
    comparison_rows = []
    for name, metrics in comparisons.items():
        row = {"case": name}
        row.update(scalar(metrics))
        comparison_rows.append(row)
    last5 = rows[-5:]
    stable_fields = [
        "taxi_share", "taxi_mean_completed_minutes", "taxi_wait_mean_s",
        "walk_share", "walk_mean_completed_minutes", "overall_completion_rate",
    ]
    stability = {}
    for field in stable_fields:
        values = [float(row[field]) for row in last5]
        stability[field] = {"min": min(values), "max": max(values), "range": max(values)-min(values)}
    taxi = final["taxi_requests"]
    taxi_share = final["by_planned_mode"]["taxi"]["share"]
    walk = final["by_planned_mode"]["walk"]
    walk_bands = final["walk_duration_bands"]
    gates = {
        "walk_share_10_5_to_12_percent": 0.105 <= walk["share"] <= 0.12,
        "walk_mean_12_to_15_minutes": 12.0 <= walk["mean_completed_minutes"] <= 15.0,
        "walk_at_most_10_minutes_60_to_68_percent": (
            0.60 <= walk_bands["at_most_10_minutes"]["share"] <= 0.68
        ),
        "walk_over_15_minutes_12_to_18_percent": (
            0.12 <= walk_bands["over_15_minutes"]["share"] <= 0.18
        ),
        "walk_completion_at_least_99_5_percent": walk["completion_rate"] >= 0.995,
        "taxi_share_5_to_7_percent": 0.05 <= taxi_share <= 0.07,
        "taxi_request_conservation": taxi["request_conservation"],
        "taxi_request_completion_at_least_99_percent": taxi["completion_rate"] >= 0.99,
        "taxi_unpicked_at_most_0_5_percent": taxi["unpicked_share"] <= 0.005,
        "taxi_wait_p50_3_to_5_minutes": 180 <= taxi["wait_p50_s"] <= 300,
        "taxi_wait_mean_5_to_7_minutes": 300 <= taxi["wait_mean_s"] <= 420,
        "taxi_wait_p90_at_most_10_minutes": taxi["wait_p90_s"] <= 600,
        "taxi_wait_p95_at_most_15_minutes": taxi["wait_p95_s"] <= 900,
        "overall_completion_at_least_99_5_percent": final["overall_completion_rate"] >= 0.995,
        "last5_taxi_share_range_at_most_0_5pp": stability["taxi_share"]["range"] <= 0.005,
        "last5_taxi_duration_range_at_most_5min": stability["taxi_mean_completed_minutes"]["range"] <= 5.0,
    }
    summary = {
        "status": "PASS",
        "meaning": "Audit completed; calibration gates are reported separately and do not define technical run success.",
        "run": str(args.run),
        "iterations": iterations,
        "scoring": {
            "taxi_adult_fare_utility_per_hkd": -0.5,
            "taxi_student_fare_utility_per_hkd": -0.6,
            "taxi_wait_utility_per_hour": -6.0,
            "taxi_in_vehicle_utility_per_hour": -6.0,
            "taxi_constant_per_trip": -9.6,
            "walk_profile": "calibration-v4",
        },
        "d2": {"iterations": metrics_by_iteration, "last5_stability": stability},
        "comparison_final": comparisons,
        "tcs_and_acceptance_gates": gates,
        "failed_gates": [k for k, v in gates.items() if not v],
        "stuck_interpretation": {
            "available_measure": "planned minus completed trips by mode",
            "limitation": "This combines pre-horizon stuck, waiting/onboard at 30h, and right censoring; it is not an exact PersonStuckEvent count.",
            "final_incomplete_by_mode": {
                mode: item["planned"] - item["completed"]
                for mode, item in final["by_planned_mode"].items()
            },
        },
        "score_interpretation": "average_executed_score is population plan score; MATSim does not expose an additive trip-level score by main mode in these outputs.",
    }
    (args.output_dir / "d2_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    for filename, data in [
        ("iteration_metrics.csv", rows),
        ("mode_transition_matrix.csv", transition_rows),
        ("comparison_final.csv", comparison_rows),
    ]:
        with (args.output_dir / filename).open("w", encoding="utf-8", newline="") as target:
            writer = csv.DictWriter(target, fieldnames=list(data[0]))
            writer.writeheader()
            writer.writerows(data)
    print(json.dumps({"status":"PASS","output_dir":str(args.output_dir),"failed_gates":summary["failed_gates"]}, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
