#!/usr/bin/env python3
"""Audit one staged Candidate5 smoke against Candidate3, Candidate4, and TPDM3."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

from audit_hong_kong_connector_chain_smoke import (
    common_metrics,
    read_one_csv,
    read_trips,
    runtime_supply,
    trip_metrics,
)
from audit_hong_kong_physical_nontaxi_pilot import (
    audit_events,
    byte_attribute,
    xml_stream,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("A", "B", "C"), required=True)
    parser.add_argument("--candidate-run", type=Path, required=True)
    parser.add_argument("--stage-a-run", type=Path)
    parser.add_argument("--candidate3-run", type=Path, required=True)
    parser.add_argument("--candidate4-run", type=Path, required=True)
    parser.add_argument("--tpdm3-run", type=Path, required=True)
    parser.add_argument("--road-registry", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--minimum-completion-rate", type=float)
    parser.add_argument("--maximum-blocked-change-percent", type=float)
    parser.add_argument("--maximum-common-time-delta-minutes", type=float, default=0.5)
    parser.add_argument("--maximum-pt-unfinished-ratio", type=float, default=0.5)
    parser.add_argument("--maximum-private-car-stuck-ratio", type=float, default=0.5)
    return parser.parse_args()


def horizon_stuck_classes(events: Path) -> dict[str, int]:
    counts = {
        "private_car": 0,
        "regular_pt_vehicle": 0,
        "school_bus_vehicle": 0,
        "taxi_vehicle": 0,
        "other": 0,
    }
    with xml_stream(events) as handle:
        for line in handle:
            if b"<event " not in line or b"stuck" not in byte_attribute(line, b"type").lower():
                continue
            mode = (
                byte_attribute(line, b"legMode")
                or byte_attribute(line, b"networkMode")
                or byte_attribute(line, b"mode")
            )
            if mode != b"car":
                continue
            entity = byte_attribute(line, b"person") or byte_attribute(line, b"vehicle")
            if entity.startswith(b"pt_veh_"):
                counts["regular_pt_vehicle"] += 1
            elif entity.startswith(b"veh_school_bus_v6_"):
                counts["school_bus_vehicle"] += 1
            elif entity.startswith((b"hk_taxi_", b"taxi_")):
                counts["taxi_vehicle"] += 1
            elif entity:
                counts["private_car"] += 1
            else:
                counts["other"] += 1
    return counts


def unfinished_road_states(run: Path) -> dict[str, object]:
    events = run / "output/ITERS/it.0/0.events.xml.zst"
    audit = audit_events(events)
    return {
        "pt_waiting_before_boarding": int(
            audit["pt_person_stuck_state"].get("waiting_before_boarding", 0)
        ),
        "pt_unfinished_onboard_or_transfer": int(audit["unfinished_pt_legs"]),
        "car_stuck_classes": horizon_stuck_classes(events),
    }


def main() -> int:
    args = parse_args()
    if args.stage != "A" and args.stage_a_run is None:
        raise ValueError("--stage-a-run is required for Candidate5B/C acceptance")
    runs = (
        args.candidate_run, args.candidate3_run, args.candidate4_run, args.tpdm3_run,
        *(() if args.stage_a_run is None else (args.stage_a_run,)),
    )
    for path in runs:
        if not path.is_dir():
            raise FileNotFoundError(path)
    if not args.road_registry.is_file():
        raise FileNotFoundError(args.road_registry)
    if args.output_dir.exists():
        raise FileExistsError(args.output_dir)
    exit_code = (args.candidate_run / "exit_code.txt").read_text(encoding="ascii").strip()
    if exit_code != "0":
        raise RuntimeError(f"Candidate5{args.stage} exit code is {exit_code}")

    candidate = read_trips(args.candidate_run)
    candidate3 = read_trips(args.candidate3_run)
    candidate4 = read_trips(args.candidate4_run)
    tpdm3 = read_trips(args.tpdm3_run)
    stage_base_run = args.candidate3_run if args.stage_a_run is None else args.stage_a_run
    stage_base = candidate3 if args.stage_a_run is None else read_trips(args.stage_a_run)
    candidate_metrics = trip_metrics(candidate)
    vs_candidate3 = common_metrics(candidate3, candidate)
    supply_vs_candidate3 = runtime_supply(
        args.candidate_run, args.candidate3_run, args.road_registry
    )
    supply_vs_stage_base = runtime_supply(
        args.candidate_run, stage_base_run, args.road_registry
    )
    states = unfinished_road_states(args.candidate_run)
    base_states = unfinished_road_states(stage_base_run)
    taxi = read_one_csv(
        args.candidate_run / "output/ITERS/it.0/0.taxi_operating_summary.csv"
    )
    taxi_counts = {
        key: int(taxi[key])
        for key in ("submitted", "completed", "waiting", "onboard", "rejected")
    }
    request_conserved = taxi_counts["submitted"] == sum(
        taxi_counts[key]
        for key in ("completed", "waiting", "onboard", "rejected")
    )
    technical = {
        "exit_code_zero": True,
        "iteration_zero_output_present": (
            args.candidate_run / "output/ITERS/it.0/0.events.xml.zst"
        ).is_file(),
        "request_conserved": request_conserved,
        "runtime_storage_exact": math.isclose(
            supply_vs_candidate3["max_abs_storage_difference_pcu"], 0.0, abs_tol=1e-10
        ),
        "runtime_flow_exact": math.isclose(
            supply_vs_candidate3["max_abs_flow_difference_pcu_per_step"], 0.0, abs_tol=1e-10
        ),
    }
    minimum_completion_rate = args.minimum_completion_rate
    if minimum_completion_rate is None:
        minimum_completion_rate = 0.80 if args.stage == "A" else 0.92
    maximum_blocked_change_percent = args.maximum_blocked_change_percent
    if maximum_blocked_change_percent is None:
        maximum_blocked_change_percent = -50.0 if args.stage == "A" else -40.0
    candidate_vs_stage_base = common_metrics(stage_base, candidate)
    pt_waiting_ratio = (
        states["pt_waiting_before_boarding"] / base_states["pt_waiting_before_boarding"]
    )
    pt_unfinished_ratio = (
        states["pt_unfinished_onboard_or_transfer"]
        / base_states["pt_unfinished_onboard_or_transfer"]
    )
    private_car_stuck_ratio = (
        states["car_stuck_classes"]["private_car"]
        / base_states["car_stuck_classes"]["private_car"]
    )
    performance = {
        "completion_at_least_target": (
            candidate_metrics["completion_rate"] >= minimum_completion_rate
        ),
        "blocked_seconds_change_at_most_target": (
            supply_vs_stage_base["all_link_blocked_seconds_change_percent"]
            <= maximum_blocked_change_percent
        ),
        "common_completed_time_delta_at_most_target": (
            candidate_vs_stage_base["candidate_minus_base_mean_minutes_common"]
            <= args.maximum_common_time_delta_minutes
        ),
        "pt_waiting_before_boarding_ratio_at_most_target": (
            pt_waiting_ratio <= args.maximum_pt_unfinished_ratio
        ),
        "pt_unfinished_onboard_or_transfer_ratio_at_most_target": (
            pt_unfinished_ratio <= args.maximum_pt_unfinished_ratio
        ),
        "private_car_stuck_ratio_at_most_target": (
            private_car_stuck_ratio <= args.maximum_private_car_stuck_ratio
        ),
    }
    summary = {
        "status": (
            "stage_gate_passed_not_adopted"
            if all(technical.values()) and all(performance.values())
            else "stage_gate_not_passed_not_adopted"
        ),
        "stage": args.stage,
        "candidate": candidate_metrics,
        "candidate3": trip_metrics(candidate3),
        "candidate4": trip_metrics(candidate4),
        "tpdm3": trip_metrics(tpdm3),
        "candidate_vs_candidate3": vs_candidate3,
        "candidate_vs_stage_base": candidate_vs_stage_base,
        "candidate_vs_candidate4": common_metrics(candidate4, candidate),
        "candidate_vs_tpdm3": common_metrics(tpdm3, candidate),
        "runtime_supply_vs_candidate3": supply_vs_candidate3,
        "runtime_supply_vs_stage_base": supply_vs_stage_base,
        "unfinished_road_states": states,
        "stage_base_unfinished_road_states": base_states,
        "unfinished_state_ratios": {
            "pt_waiting_before_boarding": pt_waiting_ratio,
            "pt_unfinished_onboard_or_transfer": pt_unfinished_ratio,
            "private_car_stuck": private_car_stuck_ratio,
        },
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
        "gate": {
            "thresholds": {
                "minimum_completion_rate": minimum_completion_rate,
                "maximum_blocked_change_percent": maximum_blocked_change_percent,
                "maximum_common_time_delta_minutes": args.maximum_common_time_delta_minutes,
                "maximum_pt_unfinished_ratio": args.maximum_pt_unfinished_ratio,
                "maximum_private_car_stuck_ratio": args.maximum_private_car_stuck_ratio,
            },
            "technical": technical,
            "performance": performance,
            "passed": all(technical.values()) and all(performance.values()),
        },
        "inputs": {
            "candidate_run": str(args.candidate_run),
            "stage_base_run": str(stage_base_run),
            "candidate3_run": str(args.candidate3_run),
            "candidate4_run": str(args.candidate4_run),
            "tpdm3_run": str(args.tpdm3_run),
            "road_registry": str(args.road_registry),
        },
    }
    if not all(technical.values()):
        raise RuntimeError(f"Candidate5 technical QA failed: {technical}")
    args.output_dir.mkdir()
    output = args.output_dir / f"candidate5{args.stage.lower()}_smoke_acceptance_summary.json"
    output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
