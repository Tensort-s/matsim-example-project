#!/usr/bin/env python3
"""Audit experienced PT timing plus 24:00-30:00 wrap against Candidate5B."""

from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import json
import math
from pathlib import Path
import subprocess

from audit_hong_kong_connector_chain_smoke import (
    read_one_csv,
    read_trips,
    runtime_supply,
    trip_metrics,
)
from audit_hong_kong_aggressive_road_supply_smoke import unfinished_road_states
from audit_hong_kong_physical_nontaxi_pilot import byte_attribute, xml_stream


DAY_S = 86_400.0
END_S = 108_000.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-run", type=Path, required=True)
    parser.add_argument("--candidate5b-run", type=Path, required=True)
    parser.add_argument("--road-registry", type=Path, required=True)
    parser.add_argument("--timetable-summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def day2_runtime(events: Path) -> dict[str, int]:
    day2_vehicles: set[bytes] = set()
    driver_starts = 0
    facility_departures = 0
    late_facility_departures = 0
    if events.suffix.lower() == ".zst":
        decompressor = subprocess.Popen(["zstdcat", str(events)], stdout=subprocess.PIPE)
        assert decompressor.stdout is not None
        grep = subprocess.Popen(
            ["grep", "--text", "__day2"],
            stdin=decompressor.stdout,
            stdout=subprocess.PIPE,
        )
        decompressor.stdout.close()
        assert grep.stdout is not None
        handle_context = grep.stdout
    else:
        decompressor = None
        grep = None
        handle_context = None
    with (xml_stream(events) if handle_context is None else handle_context) as handle:
        for line in handle:
            if b"<event " not in line:
                continue
            event_type = byte_attribute(line, b"type")
            if event_type == b"TransitDriverStarts":
                departure = byte_attribute(line, b"departureId")
                if departure.endswith(b"__day2"):
                    driver_starts += 1
                    vehicle = byte_attribute(line, b"vehicleId")
                    if vehicle:
                        day2_vehicles.add(vehicle)
                continue
            if event_type != b"VehicleDepartsAtFacility":
                continue
            vehicle = byte_attribute(line, b"vehicle")
            if vehicle not in day2_vehicles:
                continue
            facility_departures += 1
            time_raw = byte_attribute(line, b"time")
            if time_raw and DAY_S <= float(time_raw) <= END_S:
                late_facility_departures += 1
    if grep is not None:
        grep_code = grep.wait()
        decompressor_code = decompressor.wait() if decompressor is not None else 0
        if grep_code not in (0, 1) or decompressor_code != 0:
            raise RuntimeError(
                f"day-2 event filter failed: grep={grep_code}, zstdcat={decompressor_code}"
            )
    return {
        "day2_driver_starts": driver_starts,
        "day2_distinct_vehicles_started": len(day2_vehicles),
        "day2_facility_departures": facility_departures,
        "day2_facility_departures_within_24_30": late_facility_departures,
    }


def taxi_summary(run: Path) -> dict[str, object]:
    row = read_one_csv(run / "output/ITERS/it.0/0.taxi_operating_summary.csv")
    counts = {
        key: int(row[key])
        for key in ("submitted", "completed", "waiting", "onboard", "rejected")
    }
    return {
        **counts,
        "request_conserved": counts["submitted"] == sum(
            counts[key] for key in ("completed", "waiting", "onboard", "rejected")
        ),
        "wait_p50_s": float(row["wait_p50_s"]),
        "wait_p90_s": float(row["wait_p90_s"]),
        "wait_p95_s": float(row["wait_p95_s"]),
        "wait_p99_s": float(row["wait_p99_s"]),
        "empty_vkt_share": (
            float(row["empty_vkt_km"])
            / (float(row["empty_vkt_km"]) + float(row["occupied_vkt_km"]))
        ),
    }


def common_metrics_with_mode_changes(
    base: dict[str, tuple[str, float]],
    candidate: dict[str, tuple[str, float]],
) -> dict[str, object]:
    common = set(base) & set(candidate)
    all_deltas: list[float] = []
    same_mode_deltas: dict[str, list[float]] = defaultdict(list)
    transitions: dict[str, int] = defaultdict(int)
    for trip_id in common:
        base_mode, base_seconds = base[trip_id]
        candidate_mode, candidate_seconds = candidate[trip_id]
        delta = (candidate_seconds - base_seconds) / 60
        all_deltas.append(delta)
        transitions[f"{base_mode}->{candidate_mode}"] += 1
        if base_mode == candidate_mode:
            same_mode_deltas[base_mode].append(delta)
    candidate_only = set(candidate) - set(base)
    base_only = set(base) - set(candidate)
    return {
        "common_completed_trips": len(common),
        "candidate_minus_base_mean_minutes_common": sum(all_deltas) / len(all_deltas),
        "same_mode_common_trips": sum(map(len, same_mode_deltas.values())),
        "candidate_minus_base_mean_minutes_same_mode": {
            mode: sum(values) / len(values)
            for mode, values in sorted(same_mode_deltas.items())
        },
        "mode_transitions": dict(sorted(transitions.items())),
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


def safe_ratio(candidate: int | float, base: int | float) -> float | None:
    """Return an auditable ratio when a matched baseline count is zero."""
    if base:
        return candidate / base
    return 0.0 if candidate == 0 else None


def main() -> int:
    args = parse_args()
    for directory in (args.candidate_run, args.candidate5b_run):
        if not directory.is_dir():
            raise FileNotFoundError(directory)
    for path in (args.road_registry, args.timetable_summary):
        if not path.is_file():
            raise FileNotFoundError(path)
    if args.output_dir.exists():
        raise FileExistsError(args.output_dir)
    exit_code = (args.candidate_run / "exit_code.txt").read_text(encoding="ascii").strip()
    if exit_code != "0":
        raise RuntimeError(f"PT candidate exit code is {exit_code}")

    candidate = read_trips(args.candidate_run)
    base = read_trips(args.candidate5b_run)
    candidate_metrics = trip_metrics(candidate)
    base_metrics = trip_metrics(base)
    common = common_metrics_with_mode_changes(base, candidate)
    candidate_states = unfinished_road_states(args.candidate_run)
    base_states = unfinished_road_states(args.candidate5b_run)
    supply = runtime_supply(args.candidate_run, args.candidate5b_run, args.road_registry)
    timetable = json.loads(args.timetable_summary.read_text(encoding="utf-8"))
    events = args.candidate_run / "output/ITERS/it.0/0.events.xml.zst"
    day2 = day2_runtime(events)
    taxi = taxi_summary(args.candidate_run)

    waiting_ratio = safe_ratio(
        candidate_states["pt_waiting_before_boarding"],
        base_states["pt_waiting_before_boarding"],
    )
    unfinished_ratio = safe_ratio(
        candidate_states["pt_unfinished_onboard_or_transfer"],
        base_states["pt_unfinished_onboard_or_transfer"],
    )
    unresolved_candidate = (
        candidate_states["pt_waiting_before_boarding"]
        + candidate_states["pt_unfinished_onboard_or_transfer"]
    )
    unresolved_base = (
        base_states["pt_waiting_before_boarding"]
        + base_states["pt_unfinished_onboard_or_transfer"]
    )
    unresolved_ratio = safe_ratio(unresolved_candidate, unresolved_base)
    blocked_ratio = safe_ratio(
        supply["all_link_blocked_seconds"],
        supply["candidate3_all_link_blocked_seconds"],
    )
    technical = {
        "exit_code_zero": True,
        "timetable_reference_qa_passed": (
            timetable["qa"]["duplicate_departure_ids"] == 0
            and timetable["qa"]["missing_vehicle_references"] == 0
            and timetable["qa"]["all_adjusted_stop_offsets_monotonic"]
            and timetable["qa"]["day2_departure_times_within_target"]
        ),
        "all_routes_had_experienced_observations": (
            timetable["counts"]["routes_with_experienced_observations"]
            == timetable["counts"]["routes"]
        ),
        "day2_departures_executed": day2["day2_driver_starts"] > 0,
        "taxi_request_conserved": taxi["request_conserved"],
        "runtime_storage_exact": math.isclose(
            supply["max_abs_storage_difference_pcu"], 0.0, abs_tol=1e-10
        ),
        "runtime_flow_exact": math.isclose(
            supply["max_abs_flow_difference_pcu_per_step"], 0.0, abs_tol=1e-10
        ),
    }
    performance = {
        "completion_not_lower_than_candidate5b": (
            candidate_metrics["completion_rate"] >= base_metrics["completion_rate"]
        ),
        "pt_waiting_before_boarding_reduced_at_least_25_percent": waiting_ratio <= 0.75,
        "combined_unresolved_pt_states_reduced_at_least_25_percent": (
            unresolved_ratio <= 0.75
        ),
        "common_completed_mean_not_worse_over_0_5_min": (
            common["candidate_minus_base_mean_minutes_common"] <= 0.5
        ),
        "road_blocked_seconds_not_worse_over_10_percent": blocked_ratio <= 1.10,
    }
    summary = {
        "status": (
            "pt_timing_gate_passed_not_adopted"
            if all(technical.values()) and all(performance.values())
            else "pt_timing_gate_not_passed_not_adopted"
        ),
        "candidate": candidate_metrics,
        "candidate5b": base_metrics,
        "candidate_vs_candidate5b": common,
        "candidate_unfinished_states": candidate_states,
        "candidate5b_unfinished_states": base_states,
        "ratios": {
            "pt_waiting_before_boarding": waiting_ratio,
            "pt_unfinished_onboard_or_transfer": unfinished_ratio,
            "combined_unresolved_pt_states": unresolved_ratio,
            "road_blocked_seconds": blocked_ratio,
        },
        "road_runtime": supply,
        "day2_runtime": day2,
        "taxi": taxi,
        "timetable_counts": timetable["counts"],
        "technical_gates": technical,
        "performance_gates": performance,
        "inputs": {
            "candidate_run": str(args.candidate_run),
            "candidate5b_run": str(args.candidate5b_run),
            "road_registry": str(args.road_registry),
            "timetable_summary": str(args.timetable_summary),
        },
    }
    args.output_dir.mkdir(parents=True)
    output = args.output_dir / "experienced_pt_timetable_smoke_summary.json"
    output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
