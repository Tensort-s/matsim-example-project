#!/usr/bin/env python3
"""Compare Candidate5B signal-on against the matched signal-off iteration 0."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess

from audit_hong_kong_aggressive_road_supply_smoke import unfinished_road_states
from audit_hong_kong_connector_chain_smoke import read_trips, runtime_supply, trip_metrics
from audit_hong_kong_experienced_pt_timetable_smoke import (
    common_metrics_with_mode_changes,
    taxi_summary,
)
from audit_hong_kong_physical_nontaxi_pilot import byte_attribute


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signal-run", type=Path, required=True)
    parser.add_argument("--no-signal-run", type=Path, required=True)
    parser.add_argument("--road-registry", type=Path, required=True)
    parser.add_argument("--compatibility-summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def signal_event_summary(events: Path) -> dict[str, object]:
    decompressor = subprocess.Popen(["zstdcat", str(events)], stdout=subprocess.PIPE)
    assert decompressor.stdout is not None
    grep = subprocess.Popen(
        ["grep", "--text", "signalGroupStateChangedEvent"],
        stdin=decompressor.stdout,
        stdout=subprocess.PIPE,
    )
    decompressor.stdout.close()
    assert grep.stdout is not None
    systems: set[bytes] = set()
    groups: set[tuple[bytes, bytes]] = set()
    states: Counter[str] = Counter()
    events_count = 0
    maximum_time = 0.0
    for line in grep.stdout:
        events_count += 1
        system = byte_attribute(line, b"signalSystemId")
        group = byte_attribute(line, b"signalGroupId")
        state = byte_attribute(line, b"signalGroupState").decode("ascii")
        systems.add(system)
        groups.add((system, group))
        states[state] += 1
        maximum_time = max(maximum_time, float(byte_attribute(line, b"time") or 0))
    grep.stdout.close()
    grep_code = grep.wait()
    decompressor_code = decompressor.wait()
    if grep_code not in (0, 1) or decompressor_code != 0:
        raise RuntimeError(
            f"signal event filter failed: grep={grep_code}, zstdcat={decompressor_code}"
        )
    return {
        "signal_state_events": events_count,
        "signal_systems_seen": len(systems),
        "signal_groups_seen": len(groups),
        "state_counts": dict(sorted(states.items())),
        "maximum_signal_event_time_s": maximum_time,
    }


def relative_change(candidate: float, base: float) -> float | None:
    return candidate / base - 1 if base else None


def main() -> int:
    args = parse_args()
    for directory in (args.signal_run, args.no_signal_run):
        if not directory.is_dir():
            raise FileNotFoundError(directory)
    for path in (args.road_registry, args.compatibility_summary):
        if not path.is_file():
            raise FileNotFoundError(path)
    if args.output_dir.exists():
        raise FileExistsError(args.output_dir)
    exit_code = (args.signal_run / "exit_code.txt").read_text(encoding="ascii").strip()
    if exit_code != "0":
        raise RuntimeError(f"Signal run exit code is {exit_code}")

    signal_trips = read_trips(args.signal_run)
    base_trips = read_trips(args.no_signal_run)
    signal_metrics = trip_metrics(signal_trips)
    base_metrics = trip_metrics(base_trips)
    common = common_metrics_with_mode_changes(base_trips, signal_trips)
    signal_states = unfinished_road_states(args.signal_run)
    base_states = unfinished_road_states(args.no_signal_run)
    road = runtime_supply(args.signal_run, args.no_signal_run, args.road_registry)
    signal_taxi = taxi_summary(args.signal_run)
    base_taxi = taxi_summary(args.no_signal_run)
    compatibility = json.loads(args.compatibility_summary.read_text(encoding="utf-8"))
    signal_events = signal_event_summary(
        args.signal_run / "output/ITERS/it.0/0.events.xml.zst"
    )

    by_mode_change = {}
    modes = set(signal_metrics["by_mode"]) | set(base_metrics["by_mode"])
    for mode in sorted(modes):
        signal_mode = signal_metrics["by_mode"].get(mode, {})
        base_mode = base_metrics["by_mode"].get(mode, {})
        signal_completed = int(signal_mode.get("completed", 0))
        base_completed = int(base_mode.get("completed", 0))
        signal_time = signal_mode.get("mean_completed_minutes")
        base_time = base_mode.get("mean_completed_minutes")
        by_mode_change[mode] = {
            "completed_change": signal_completed - base_completed,
            "completed_relative_change": relative_change(signal_completed, base_completed),
            "raw_mean_minutes_change": (
                float(signal_time) - float(base_time)
                if signal_time is not None and base_time is not None else None
            ),
            "same_mode_common_mean_minutes_change": common[
                "candidate_minus_base_mean_minutes_same_mode"
            ].get(mode),
        }

    technical = {
        "exit_code_zero": True,
        "static_signal_network_compatibility": compatibility["status"] == "pass",
        "all_signal_systems_executed": (
            signal_events["signal_systems_seen"] == compatibility["signal_systems"]
        ),
        "all_signal_groups_executed": (
            signal_events["signal_groups_seen"] == compatibility["signal_groups"]
        ),
        "taxi_request_conserved": bool(signal_taxi["request_conserved"]),
        "runtime_storage_exact": road["max_abs_storage_difference_pcu"] <= 1e-10,
        "runtime_flow_exact": road["max_abs_flow_difference_pcu_per_step"] <= 1e-10,
    }
    summary = {
        "status": (
            "comparison_complete_technical_pass_not_adopted"
            if all(technical.values()) else "comparison_complete_technical_fail_not_adopted"
        ),
        "signal_on": signal_metrics,
        "signal_off_candidate5b": base_metrics,
        "changes": {
            "completed_trips": (
                signal_metrics["completed_trips"] - base_metrics["completed_trips"]
            ),
            "completion_rate_percentage_points": 100 * (
                signal_metrics["completion_rate"] - base_metrics["completion_rate"]
            ),
            "raw_mean_completed_minutes": (
                signal_metrics["mean_completed_minutes"]
                - base_metrics["mean_completed_minutes"]
            ),
            "common_completed_mean_minutes": common[
                "candidate_minus_base_mean_minutes_common"
            ],
            "by_mode": by_mode_change,
        },
        "common_completed": common,
        "signal_on_unfinished_states": signal_states,
        "signal_off_unfinished_states": base_states,
        "unfinished_state_changes": {
            "pt_waiting_before_boarding": (
                signal_states["pt_waiting_before_boarding"]
                - base_states["pt_waiting_before_boarding"]
            ),
            "pt_unfinished_onboard_or_transfer": (
                signal_states["pt_unfinished_onboard_or_transfer"]
                - base_states["pt_unfinished_onboard_or_transfer"]
            ),
            "private_car_stuck": (
                signal_states["car_stuck_classes"]["private_car"]
                - base_states["car_stuck_classes"]["private_car"]
            ),
            "regular_pt_vehicle_stuck": (
                signal_states["car_stuck_classes"]["regular_pt_vehicle"]
                - base_states["car_stuck_classes"]["regular_pt_vehicle"]
            ),
            "taxi_vehicle_stuck": (
                signal_states["car_stuck_classes"]["taxi_vehicle"]
                - base_states["car_stuck_classes"]["taxi_vehicle"]
            ),
        },
        "road_runtime": road,
        "signal_runtime": signal_events,
        "taxi_signal_on": signal_taxi,
        "taxi_signal_off": base_taxi,
        "technical_gates": technical,
        "inputs": {
            "signal_run": str(args.signal_run),
            "no_signal_run": str(args.no_signal_run),
            "road_registry": str(args.road_registry),
            "compatibility_summary": str(args.compatibility_summary),
        },
    }
    args.output_dir.mkdir(parents=True)
    output = args.output_dir / "candidate5b_signal_ab_summary.json"
    output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if all(technical.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
