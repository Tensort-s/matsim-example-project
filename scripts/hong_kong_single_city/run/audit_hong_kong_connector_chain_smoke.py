#!/usr/bin/env python3
"""Audit Candidate4 against matched TPDM3 and Candidate3 iteration-0 runs."""

from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import json
import math
from pathlib import Path
import subprocess
from typing import Any


TOTAL_TRIPS = 743_614


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate4-run", type=Path, required=True)
    parser.add_argument("--candidate3-run", type=Path, required=True)
    parser.add_argument("--tpdm3-run", type=Path, required=True)
    parser.add_argument("--road-registry", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def seconds(value: str) -> float:
    hours, minutes, secs = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(secs)


def read_trips(run: Path) -> dict[str, tuple[str, float]]:
    path = run / "output/output_trips.csv.zst"
    if not path.is_file():
        raise FileNotFoundError(path)
    process = subprocess.Popen(
        ["zstdcat", str(path)], stdout=subprocess.PIPE, text=True,
        encoding="utf-8",
    )
    assert process.stdout is not None
    result: dict[str, tuple[str, float]] = {}
    for row in csv.DictReader(process.stdout, delimiter=";"):
        trip_id = row["trip_id"]
        if trip_id in result:
            raise ValueError(f"Duplicate completed trip ID: {trip_id}")
        result[trip_id] = (row["main_mode"], seconds(row["trav_time"]))
    process.stdout.close()
    if process.wait() != 0:
        raise RuntimeError(f"zstdcat failed for {path}")
    return result


def trip_metrics(trips: dict[str, tuple[str, float]]) -> dict[str, Any]:
    counts: dict[str, int] = defaultdict(int)
    sums: dict[str, float] = defaultdict(float)
    for mode, duration in trips.values():
        counts[mode] += 1
        sums[mode] += duration
    count = len(trips)
    return {
        "completed_trips": count,
        "total_planned_trips": TOTAL_TRIPS,
        "completion_rate": count / TOTAL_TRIPS,
        "mean_completed_minutes": sum(sums.values()) / count / 60,
        "by_mode": {
            mode: {
                "completed": counts[mode],
                "share_of_completed": counts[mode] / count,
                "mean_completed_minutes": sums[mode] / counts[mode] / 60,
            }
            for mode in sorted(counts)
        },
    }


def common_metrics(
    base: dict[str, tuple[str, float]], candidate: dict[str, tuple[str, float]]
) -> dict[str, Any]:
    common = sorted(set(base) & set(candidate))
    deltas: dict[str, list[float]] = defaultdict(list)
    for trip_id in common:
        base_mode, base_seconds = base[trip_id]
        candidate_mode, candidate_seconds = candidate[trip_id]
        if base_mode != candidate_mode:
            raise ValueError(f"Mode changed for matched trip {trip_id}: {base_mode}, {candidate_mode}")
        deltas[base_mode].append((candidate_seconds - base_seconds) / 60)
        deltas["__all__"].append((candidate_seconds - base_seconds) / 60)
    candidate_only = set(candidate) - set(base)
    base_only = set(base) - set(candidate)
    return {
        "common_completed_trips": len(common),
        "candidate_minus_base_mean_minutes_common": sum(deltas["__all__"]) / len(common),
        "candidate_minus_base_mean_minutes_common_by_mode": {
            mode: sum(values) / len(values)
            for mode, values in sorted(deltas.items()) if mode != "__all__"
        },
        "candidate_only_completed": len(candidate_only),
        "candidate_only_mean_minutes": (
            sum(candidate[item][1] for item in candidate_only) / len(candidate_only) / 60
            if candidate_only else None
        ),
        "base_only_completed": len(base_only),
        "base_only_mean_minutes": (
            sum(base[item][1] for item in base_only) / len(base_only) / 60
            if base_only else None
        ),
    }


def read_one_csv(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 1:
        raise ValueError(f"Expected one row in {path}; found {len(rows)}")
    return rows[0]


def runtime_supply(
    candidate4_run: Path, candidate3_run: Path, registry_path: Path
) -> dict[str, Any]:
    audit_path = (
        candidate4_run
        / "output/ITERS/it.0/0.explicit_storage_capacity_audit.csv"
    )
    with audit_path.open(encoding="utf-8", newline="") as handle:
        audit = {row["link_id"]: row for row in csv.DictReader(handle)}
    candidate3_audit_path = (
        candidate3_run
        / "output/ITERS/it.0/0.explicit_storage_capacity_audit.csv"
    )
    with candidate3_audit_path.open(encoding="utf-8", newline="") as handle:
        candidate3_audit = {
            row["link_id"]: row for row in csv.DictReader(handle)
        }
    with registry_path.open(encoding="utf-8", newline="") as handle:
        registry = {row["link_id"]: row for row in csv.DictReader(handle)}
    flow_ids = {
        link_id for link_id, row in registry.items()
        if row["flow_capacity_override"].lower() == "true"
    }
    if set(audit) != set(registry) or set(candidate3_audit) != set(registry):
        raise ValueError("Runtime supply audit IDs do not equal registry IDs")
    storage_diffs = [
        abs(float(row["requested_storage_qsim_pcu"])
            - float(row["actual_storage_qsim_pcu"]))
        for row in audit.values()
    ]
    flow_diffs = [
        abs(float(audit[link_id]["expected_flow_capacity_qsim_pcu_per_step"])
            - float(audit[link_id]["actual_flow_capacity_qsim_pcu_per_step"]))
        for link_id in flow_ids
    ]
    blocked = {
        link_id: float(row["blocked_inflow_seconds"])
        for link_id, row in audit.items()
    }
    candidate3_blocked = {
        link_id: float(row["blocked_inflow_seconds"])
        for link_id, row in candidate3_audit.items()
    }
    examples = {}
    for link_id in ("road_104307_0_r", "road_104308_0_f"):
        examples[link_id] = {
            "physical_flow_capacity_vph": float(registry[link_id]["physical_flow_capacity_vph"]),
            "qsim_flow_capacity_vph": float(registry[link_id]["flow_capacity_vph"]),
            "requested_storage_qsim_pcu": float(audit[link_id]["requested_storage_qsim_pcu"]),
            "actual_storage_qsim_pcu": float(audit[link_id]["actual_storage_qsim_pcu"]),
            "expected_flow_qsim_pcu_per_step": float(
                audit[link_id]["expected_flow_capacity_qsim_pcu_per_step"]
            ),
            "actual_flow_qsim_pcu_per_step": float(
                audit[link_id]["actual_flow_capacity_qsim_pcu_per_step"]
            ),
            "blocked_inflow_seconds": float(audit[link_id]["blocked_inflow_seconds"]),
            "candidate3_blocked_inflow_seconds": float(
                candidate3_audit[link_id]["blocked_inflow_seconds"]
            ),
        }
    all_base = sum(candidate3_blocked.values())
    all_candidate = sum(blocked.values())
    target_base = sum(candidate3_blocked[link_id] for link_id in flow_ids)
    target_candidate = sum(blocked[link_id] for link_id in flow_ids)
    return {
        "runtime_rows": len(audit),
        "flow_override_links": len(flow_ids),
        "max_abs_storage_difference_pcu": max(storage_diffs),
        "max_abs_flow_difference_pcu_per_step": max(flow_diffs),
        "blocked_links": sum(value > 0 for value in blocked.values()),
        "candidate3_blocked_links": sum(value > 0 for value in candidate3_blocked.values()),
        "all_link_blocked_seconds": all_candidate,
        "candidate3_all_link_blocked_seconds": all_base,
        "all_link_blocked_seconds_change_percent": (all_candidate / all_base - 1) * 100,
        "flow_override_link_blocked_seconds": target_candidate,
        "candidate3_flow_override_link_blocked_seconds": target_base,
        "flow_override_link_blocked_seconds_change_percent": (
            target_candidate / target_base - 1
        ) * 100,
        "flow_override_links_improved": sum(
            blocked[item] < candidate3_blocked[item] for item in flow_ids
        ),
        "flow_override_links_worsened": sum(
            blocked[item] > candidate3_blocked[item] for item in flow_ids
        ),
        "flow_override_links_unchanged": sum(
            blocked[item] == candidate3_blocked[item] for item in flow_ids
        ),
        "example_chain": examples,
    }


def main() -> int:
    args = parse_args()
    for path in (args.candidate4_run, args.candidate3_run, args.tpdm3_run):
        if not path.is_dir():
            raise FileNotFoundError(path)
    if not args.road_registry.is_file():
        raise FileNotFoundError(args.road_registry)
    if args.output_dir.exists():
        raise FileExistsError(args.output_dir)
    exit_code = (args.candidate4_run / "exit_code.txt").read_text(encoding="ascii").strip()
    if exit_code != "0":
        raise RuntimeError(f"Candidate4 exit code is {exit_code}")
    candidate4 = read_trips(args.candidate4_run)
    candidate3 = read_trips(args.candidate3_run)
    tpdm3 = read_trips(args.tpdm3_run)
    taxi = read_one_csv(
        args.candidate4_run / "output/ITERS/it.0/0.taxi_operating_summary.csv"
    )
    taxi_counts = {key: int(taxi[key]) for key in (
        "submitted", "completed", "waiting", "onboard", "rejected"
    )}
    request_conserved = taxi_counts["submitted"] == sum(
        taxi_counts[key] for key in ("completed", "waiting", "onboard", "rejected")
    )
    summary = {
        "status": "accepted_technical_smoke_not_adopted",
        "candidate4": trip_metrics(candidate4),
        "candidate3": trip_metrics(candidate3),
        "tpdm3": trip_metrics(tpdm3),
        "candidate4_vs_candidate3": common_metrics(candidate3, candidate4),
        "candidate4_vs_tpdm3": common_metrics(tpdm3, candidate4),
        "runtime_supply": runtime_supply(
            args.candidate4_run, args.candidate3_run, args.road_registry
        ),
        "taxi": {
            **taxi_counts,
            "request_conserved": request_conserved,
            "wait_p50_s": float(taxi["wait_p50_s"]),
            "wait_p90_s": float(taxi["wait_p90_s"]),
            "wait_p95_s": float(taxi["wait_p95_s"]),
            "wait_p99_s": float(taxi["wait_p99_s"]),
            "empty_vkt_km": float(taxi["empty_vkt_km"]),
            "occupied_vkt_km": float(taxi["occupied_vkt_km"]),
            "empty_vkt_ratio": float(taxi["empty_vkt_ratio"]),
        },
        "qa": {
            "exit_code_zero": True,
            "iteration_zero_output_present": (
                args.candidate4_run / "output/ITERS/it.0/0.events.xml.zst"
            ).is_file(),
            "request_conserved": request_conserved,
        },
        "inputs": {
            "candidate4_run": str(args.candidate4_run),
            "candidate3_run": str(args.candidate3_run),
            "tpdm3_run": str(args.tpdm3_run),
            "road_registry": str(args.road_registry),
        },
    }
    if not all(summary["qa"].values()):
        raise RuntimeError(f"Candidate4 smoke QA failed: {summary['qa']}")
    if not math.isclose(
        summary["runtime_supply"]["max_abs_flow_difference_pcu_per_step"],
        0.0, abs_tol=1e-10,
    ):
        raise RuntimeError("Candidate4 runtime flow differs from registry")
    args.output_dir.mkdir()
    output = args.output_dir / "connector_chain_smoke_acceptance_summary.json"
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
