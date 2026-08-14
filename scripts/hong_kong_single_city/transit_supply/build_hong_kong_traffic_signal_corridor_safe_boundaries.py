#!/usr/bin/env python3
"""Shift corridor TOD plan boundaries to fixed-offset cycle barriers."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from build_hong_kong_traffic_signal_pilot_v1 import read_csv, write_csv
from build_hong_kong_traffic_signal_tod_proxy_top100 import REPO_ROOT


DAY_SECONDS = 24 * 3600
BIN_SECONDS = 15 * 60
TIME_BIN_COUNT = 96
CLEARANCE_SECONDS = 6
DEFAULT_SOURCE = REPO_ROOT / (
    "data/transit/hongkong/processed/"
    "hong_kong_traffic_signals_2026_v3_tod_proxy_all_expressed_road_hotspot_v1_"
    "candidate10_corridor"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/transit/hongkong/processed/"
    "hong_kong_traffic_signals_2026_v3_tod_proxy_all_expressed_road_hotspot_v1_"
    "candidate11_safe_boundaries"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-candidate", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def shifted_bounds(bin_index: int, shift_s: int) -> tuple[int, int]:
    if not 0 <= bin_index < TIME_BIN_COUNT:
        raise ValueError("time-bin index outside 0..95")
    if not 0 <= shift_s < BIN_SECONDS:
        raise ValueError("boundary shift outside one 15-minute bin")
    return (
        (bin_index * BIN_SECONDS + shift_s) % DAY_SECONDS,
        ((bin_index + 1) * BIN_SECONDS + shift_s) % DAY_SECONDS,
    )


def barrier_is_safe(
    actual_boundary_s: int,
    old_cycle_s: int,
    new_cycle_s: int,
    offset_s: int,
    old_windows: list[dict],
    new_windows: list[dict],
) -> bool:
    """Return true when switching occurs at the shared stage-1 onset barrier."""
    if actual_boundary_s % old_cycle_s != offset_s % old_cycle_s:
        return False
    if actual_boundary_s % new_cycle_s != offset_s % new_cycle_s:
        return False
    old_ordered = sorted(old_windows, key=lambda row: int(row["stage_index"]))
    new_ordered = sorted(new_windows, key=lambda row: int(row["stage_index"]))
    if not old_ordered or not new_ordered:
        return False
    if int(new_ordered[0]["green_onset_s"]) != 0:
        return False
    if int(old_ordered[-1]["green_dropping_s"]) != old_cycle_s - CLEARANCE_SECONDS:
        return False
    return True


def build(args: argparse.Namespace) -> dict:
    source = args.source_candidate.resolve()
    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"Output directory must be new: {output}")
    required = [
        source / "tod_plan_assignments.csv",
        source / "tod_group_windows.csv",
        source / "signal_corridor_registry.csv",
        source / "corridor_validation_summary.json",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing Candidate10 inputs: " + ", ".join(missing))

    plans = read_csv(source / "tod_plan_assignments.csv")
    windows = read_csv(source / "tod_group_windows.csv")
    registry = read_csv(source / "signal_corridor_registry.csv")
    corridor_systems = {
        system
        for row in registry
        if row["status"] == "implemented"
        for system in row["signal_system_ids"].split("|")
    }
    if len(corridor_systems) != 47:
        raise AssertionError(f"Expected 47 implemented corridor systems; found {len(corridor_systems)}")

    windows_by_plan: dict[tuple[str, str], list[dict]] = {}
    for row in windows:
        windows_by_plan.setdefault((row["signal_system_id"], row["plan_id"]), []).append(row)
    plans_by_system: dict[str, list[dict]] = {}
    for row in plans:
        plans_by_system.setdefault(row["signal_system_id"], []).append(row)

    audit_rows = []
    modified_plans = []
    shifted_systems = set()
    for system, local_plans in plans_by_system.items():
        ordered = sorted(local_plans, key=lambda row: int(row["time_bin_index"]))
        offsets = {int(row["offset_s"]) for row in ordered}
        if len(offsets) != 1:
            raise AssertionError(f"Candidate10 offset is not fixed daily for {system}")
        offset = next(iter(offsets))
        shift = offset if system in corridor_systems else 0
        if shift:
            shifted_systems.add(system)
        for row in ordered:
            updated = dict(row)
            index = int(row["time_bin_index"])
            start, end = shifted_bounds(index, shift)
            updated["start_time_s"] = start
            updated["end_time_s"] = end
            modified_plans.append(updated)
        if system not in corridor_systems:
            continue
        for index in range(TIME_BIN_COUNT):
            old_row = ordered[(index - 1) % TIME_BIN_COUNT]
            new_row = ordered[index]
            nominal = index * BIN_SECONDS
            actual = (nominal + shift) % DAY_SECONDS
            safe = barrier_is_safe(
                actual,
                int(old_row["cycle_s"]),
                int(new_row["cycle_s"]),
                offset,
                windows_by_plan[(system, old_row["plan_id"])],
                windows_by_plan[(system, new_row["plan_id"])],
            )
            audit_rows.append({
                "signal_system_id": system,
                "time_bin_index": index,
                "old_plan_id": old_row["plan_id"],
                "new_plan_id": new_row["plan_id"],
                "nominal_boundary_s": nominal,
                "actual_boundary_s": actual,
                "delay_s": shift,
                "old_cycle_s": old_row["cycle_s"],
                "new_cycle_s": new_row["cycle_s"],
                "offset_s": offset,
                "old_clearance_before_boundary_s": CLEARANCE_SECONDS,
                "new_first_stage_onset_at_boundary": str(safe).lower(),
                "boundary_status": "safe_shared_stage1_barrier" if safe else "unsafe",
            })
    unsafe = [row for row in audit_rows if row["boundary_status"] != "safe_shared_stage1_barrier"]
    if unsafe:
        raise AssertionError(f"Unsafe shifted TOD barriers: {len(unsafe)}")

    shutil.copytree(source, output, ignore=shutil.ignore_patterns("matsim"))
    write_csv(output / "tod_plan_assignments.csv", modified_plans, tuple(modified_plans[0]))
    write_csv(output / "tod_safe_boundary_transitions.csv", audit_rows, tuple(audit_rows[0]))

    qa_path = output / "tod_qa_summary.json"
    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    for key in tuple(qa):
        if key.startswith("runtime_") or key.startswith("iteration_"):
            qa.pop(key)
    qa.update({
        "status": "candidate11_safe_shifted_tod_boundaries_not_runtime_validated",
        "source_candidate": str(source),
        "safe_boundary_policy": "per_system_fixed_offset_delayed_shared_stage1_barrier",
        "safe_boundary_corridor_system_count": len(corridor_systems),
        "safe_boundary_nonzero_shift_system_count": len(shifted_systems),
        "safe_boundary_transition_count": len(audit_rows),
        "maximum_boundary_delay_s": max(int(row["delay_s"]) for row in audit_rows),
        "runtime_gate": "not_run",
        "corridor_runtime_validated": False,
        "production_adopted": False,
    })
    qa_path.write_text(json.dumps(qa, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    pilot_path = output / "pilot_build_summary.json"
    pilot = json.loads(pilot_path.read_text(encoding="utf-8"))
    for key in tuple(pilot):
        if key.startswith("runtime_") or key.startswith("iteration_"):
            pilot.pop(key)
    pilot.update({
        "status": "candidate11_safe_shifted_tod_boundaries_not_adopted",
        "tod_plan_boundaries": "per_system_fixed_offset_delayed_shared_stage1_barrier",
        "safe_boundary_corridor_system_count": len(corridor_systems),
        "safe_boundary_nonzero_shift_system_count": len(shifted_systems),
        "runtime_gate": "not_run",
        "corridor_runtime_validated": False,
        "production_adopted": False,
    })
    pilot_path.write_text(json.dumps(pilot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    metadata_path = output / "tod_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    for key in tuple(metadata):
        if key.startswith("runtime_") or key.startswith("iteration_"):
            metadata.pop(key)
    metadata.update({
        "model_status": qa["status"],
        "source_candidate": str(source),
        "output_dir": str(output),
        "safe_boundary_policy": qa["safe_boundary_policy"],
        "runtime_gate": "not_run",
    })
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = {
        "status": qa["status"],
        "source_candidate": str(source),
        "output_dir": str(output),
        "corridor_systems": len(corridor_systems),
        "nonzero_shift_systems": len(shifted_systems),
        "safe_boundary_transitions": len(audit_rows),
        "unsafe_boundary_transitions": 0,
        "maximum_boundary_delay_s": qa["maximum_boundary_delay_s"],
        "production_adopted": False,
    }
    (output / "safe_boundary_build_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return summary


def main() -> None:
    print(json.dumps(build(parse_args()), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
