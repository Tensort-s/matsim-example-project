#!/usr/bin/env python3
"""Validate Candidate11 delayed TOD boundaries against Candidate10."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from build_hong_kong_traffic_signal_corridor_safe_boundaries import (
    BIN_SECONDS,
    DAY_SECONDS,
    DEFAULT_OUTPUT,
    DEFAULT_SOURCE,
    TIME_BIN_COUNT,
    barrier_is_safe,
)
from build_hong_kong_traffic_signal_pilot_v1 import read_csv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-candidate", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--candidate-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def xml_root(path: Path) -> ET.Element:
    if path.suffix == ".gz":
        with gzip.open(path, "rb") as stream:
            return ET.parse(stream).getroot()
    return ET.parse(path).getroot()


def validate(args: argparse.Namespace) -> dict:
    source = args.source_candidate.resolve()
    candidate = args.candidate_dir.resolve()
    required = [
        "tod_plan_assignments.csv",
        "tod_group_windows.csv",
        "signal_corridor_registry.csv",
        "tod_safe_boundary_transitions.csv",
        "matsim/signal_control.xml",
    ]
    missing = [name for name in required if not (candidate / name).is_file()]
    if missing:
        raise FileNotFoundError("Missing Candidate11 artifacts: " + ", ".join(missing))

    source_plans = read_csv(source / "tod_plan_assignments.csv")
    plans = read_csv(candidate / "tod_plan_assignments.csv")
    windows = read_csv(candidate / "tod_group_windows.csv")
    registry = read_csv(candidate / "signal_corridor_registry.csv")
    boundary_rows = read_csv(candidate / "tod_safe_boundary_transitions.csv")
    if len(source_plans) != len(plans):
        raise AssertionError("Plan row count changed relative to Candidate10")

    corridor_systems = {
        system
        for row in registry
        if row["status"] == "implemented"
        for system in row["signal_system_ids"].split("|")
    }
    if len(corridor_systems) != 47:
        raise AssertionError(f"Expected 47 corridor systems; found {len(corridor_systems)}")

    source_by_key = {
        (row["signal_system_id"], row["plan_id"]): row for row in source_plans
    }
    plans_by_system: dict[str, list[dict[str, str]]] = {}
    plan_by_key: dict[tuple[str, str], dict[str, str]] = {}
    for row in plans:
        plans_by_system.setdefault(row["signal_system_id"], []).append(row)
        plan_by_key[(row["signal_system_id"], row["plan_id"])] = row
    windows_by_plan: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in windows:
        windows_by_plan.setdefault((row["signal_system_id"], row["plan_id"]), []).append(row)

    changed_fields: set[str] = set()
    shifted_systems: set[str] = set()
    for key, row in plan_by_key.items():
        source_row = source_by_key[key]
        local_changes = {field for field in row if row[field] != source_row[field]}
        if local_changes.difference({"start_time_s", "end_time_s"}):
            raise AssertionError(f"Non-boundary plan change for {key}: {sorted(local_changes)}")
        changed_fields.update(local_changes)
    for system, local_plans in plans_by_system.items():
        ordered = sorted(local_plans, key=lambda row: int(row["time_bin_index"]))
        if len(ordered) != TIME_BIN_COUNT:
            raise AssertionError(f"Expected 96 plans for {system}")
        offset_values = {int(row["offset_s"]) for row in ordered}
        if len(offset_values) != 1:
            raise AssertionError(f"Offset changes within day for {system}")
        shift = next(iter(offset_values)) if system in corridor_systems else 0
        if shift:
            shifted_systems.add(system)
        for index, row in enumerate(ordered):
            expected_start = (index * BIN_SECONDS + shift) % DAY_SECONDS
            expected_end = ((index + 1) * BIN_SECONDS + shift) % DAY_SECONDS
            if int(row["start_time_s"]) != expected_start or int(row["end_time_s"]) != expected_end:
                raise AssertionError(f"Incorrect shifted bounds for {system} bin {index}")

    if len(boundary_rows) != len(corridor_systems) * TIME_BIN_COUNT:
        raise AssertionError("Incomplete corridor boundary audit")
    unsafe = []
    for audit in boundary_rows:
        system = audit["signal_system_id"]
        index = int(audit["time_bin_index"])
        old_plan = plan_by_key[(system, audit["old_plan_id"])]
        new_plan = plan_by_key[(system, audit["new_plan_id"])]
        safe = barrier_is_safe(
            int(audit["actual_boundary_s"]),
            int(old_plan["cycle_s"]),
            int(new_plan["cycle_s"]),
            int(new_plan["offset_s"]),
            windows_by_plan[(system, old_plan["plan_id"])],
            windows_by_plan[(system, new_plan["plan_id"])],
        )
        expected_index = (int(old_plan["time_bin_index"]) + 1) % TIME_BIN_COUNT
        if index != expected_index or not safe or audit["boundary_status"] != "safe_shared_stage1_barrier":
            unsafe.append(audit)
    if unsafe:
        raise AssertionError(f"Unsafe or inconsistent boundary rows: {len(unsafe)}")

    control = xml_root(candidate / "matsim" / "signal_control.xml")
    xml_plans: dict[tuple[str, str], tuple[int, int, int, int]] = {}
    for system_element in control.iter():
        if system_element.tag.rsplit("}", 1)[-1] == "signalSystem":
            system = system_element.attrib["refId"]
            for plan in system_element.iter():
                if plan.tag.rsplit("}", 1)[-1] != "signalPlan":
                    continue
                values = {}
                for child in plan:
                    name = child.tag.rsplit("}", 1)[-1]
                    if name in {"start", "stop"}:
                        hours, minutes, seconds = map(int, child.attrib["daytime"].split(":"))
                        values[name] = hours * 3600 + minutes * 60 + seconds
                    elif name in {"cycleTime", "offset"}:
                        values[name] = int(float(child.attrib["sec"]))
                xml_plans[(system, plan.attrib["id"])] = (
                    values["start"], values["stop"], values["cycleTime"], values["offset"]
                )
    if len(xml_plans) != len(plans):
        raise AssertionError("Compiled XML plan count does not match CSV")
    for key, row in plan_by_key.items():
        expected = tuple(int(row[field]) for field in ("start_time_s", "end_time_s", "cycle_s", "offset_s"))
        if xml_plans.get(key) != expected:
            raise AssertionError(f"Compiled XML mismatch for {key}")

    immutable_files = [
        "network_signal_capacity_deconvolved.xml.gz",
        "capacity_deconvolution_audit.csv",
        "executable_signal_movements.csv",
        "junction_deactivation_audit.csv",
        "signal_corridor_registry.csv",
        "signal_corridor_links.csv",
        "tod_corridor_offsets.csv",
        "tod_group_windows.csv",
        "vehicle_class_stage_demand_15min.csv",
        "matsim/signal_systems.xml",
        "matsim/signal_groups.xml",
    ]
    changed_immutable = [name for name in immutable_files if sha256(source / name) != sha256(candidate / name)]
    if changed_immutable:
        raise AssertionError("Unexpected Candidate10 artifact changes: " + ", ".join(changed_immutable))

    summary = {
        "status": "pass",
        "candidate": "candidate11_safe_boundaries",
        "source_candidate": str(source),
        "candidate_dir": str(candidate),
        "signal_system_count": len(plans_by_system),
        "corridor_system_count": len(corridor_systems),
        "nonzero_shift_system_count": len(shifted_systems),
        "plan_count": len(plans),
        "safe_boundary_transition_count": len(boundary_rows),
        "unsafe_boundary_transition_count": 0,
        "maximum_boundary_delay_s": max(int(row["delay_s"]) for row in boundary_rows),
        "changed_plan_fields": sorted(changed_fields),
        "changed_immutable_files": [],
        "compiled_xml_plan_mismatches": 0,
        "runtime_gate": "not_run",
        "production_adopted": False,
    }
    output = candidate / "safe_boundary_validation_summary.json"
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> None:
    validate(parse_args())


if __name__ == "__main__":
    main()
