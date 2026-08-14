#!/usr/bin/env python3
"""Validate corridor-only differences and fixed-offset transition safety."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from lxml import etree as ET

from build_hong_kong_traffic_signal_pilot_v1 import read_csv
from coordinate_hong_kong_traffic_signal_corridors import (
    DEFAULT_OUTPUT,
    DEFAULT_SOURCE,
    TIME_BIN_COUNT,
    sha256,
    transition_compatible,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--source-candidate", type=Path, default=DEFAULT_SOURCE)
    return parser.parse_args()


def local_name(element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def validate(args: argparse.Namespace) -> dict:
    candidate = args.candidate_dir.resolve()
    source = args.source_candidate.resolve()
    required = [
        candidate / "signal_corridor_registry.csv",
        candidate / "signal_corridor_links.csv",
        candidate / "tod_corridor_direction_15min.csv",
        candidate / "tod_corridor_offsets.csv",
        candidate / "corridor_exclusions.csv",
        candidate / "corridor_build_summary.json",
        candidate / "matsim/signal_control.xml",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing corridor outputs: " + ", ".join(missing))

    unchanged = (
        "executable_signal_movements.csv", "stage_templates.csv", "tod_group_windows.csv",
        "vehicle_class_stage_demand_15min.csv", "capacity_deconvolution_audit.csv",
        "network_signal_capacity_deconvolved.xml.gz",
    )
    changed_invariants = [name for name in unchanged if sha256(source / name) != sha256(candidate / name)]
    if changed_invariants:
        raise AssertionError("Corridor candidate changed non-offset inputs: " + ", ".join(changed_invariants))

    source_plans = read_csv(source / "tod_plan_assignments.csv")
    candidate_plans = read_csv(candidate / "tod_plan_assignments.csv")
    if len(source_plans) != len(candidate_plans):
        raise AssertionError("Plan cardinality changed")
    source_by_key = {(row["signal_system_id"], row["plan_id"]): row for row in source_plans}
    candidate_by_key = {(row["signal_system_id"], row["plan_id"]): row for row in candidate_plans}
    if set(source_by_key) != set(candidate_by_key):
        raise AssertionError("Plan IDs changed")
    non_offset_changes = []
    for key, source_row in source_by_key.items():
        target = candidate_by_key[key]
        for field, value in source_row.items():
            if field != "offset_s" and target[field] != value:
                non_offset_changes.append((key, field))
    if non_offset_changes:
        raise AssertionError("Corridor candidate changed non-offset plan fields")

    registry = read_csv(candidate / "signal_corridor_registry.csv")
    implemented = [row for row in registry if row["status"] == "implemented"]
    implemented_ids = {row["corridor_id"] for row in implemented}
    system_corridors = defaultdict(set)
    for row in implemented:
        for system in row["signal_system_ids"].split("|"):
            system_corridors[system].add(row["corridor_id"])
    if any(len(values) != 1 for values in system_corridors.values()):
        raise AssertionError("A signal system belongs to multiple implemented corridors")

    offset_rows = read_csv(candidate / "tod_corridor_offsets.csv")
    if {row["corridor_id"] for row in offset_rows} != implemented_ids:
        raise AssertionError("Offset audit does not cover exactly the implemented corridors")
    offsets_by_system = defaultdict(set)
    for row in offset_rows:
        system = row["signal_system_id"]
        offset = int(row["implemented_offset_s"])
        cycle = int(row["cycle_s"])
        if not 0 <= offset < cycle:
            raise AssertionError("Offset lies outside cycle")
        offsets_by_system[system].add(offset)
        plan = candidate_by_key[(system, f"tod_{int(row['time_bin_index']):02d}")]
        if int(plan["offset_s"]) != offset:
            raise AssertionError("Offset audit and plan assignment differ")
    if any(len(values) != 1 for values in offsets_by_system.values()):
        raise AssertionError("Implemented corridor system does not use one fixed daily offset")

    windows = read_csv(candidate / "tod_group_windows.csv")
    windows_by_system_bin = defaultdict(list)
    for row in windows:
        windows_by_system_bin[(row["signal_system_id"], int(row["time_bin_index"]))].append(row)
    transition_failures = []
    for system in system_corridors:
        for index in range(TIME_BIN_COUNT):
            earlier = (index - 1) % TIME_BIN_COUNT
            old_plan = candidate_by_key[(system, f"tod_{earlier:02d}")]
            new_plan = candidate_by_key[(system, f"tod_{index:02d}")]
            if not transition_compatible(
                windows_by_system_bin[(system, earlier)], int(old_plan["cycle_s"]), int(old_plan["offset_s"]),
                windows_by_system_bin[(system, index)], int(new_plan["cycle_s"]), int(new_plan["offset_s"]),
            ):
                transition_failures.append((system, index))
    if transition_failures:
        raise AssertionError("Unsafe plan-boundary offset transitions")

    root = ET.parse(candidate / "matsim/signal_control.xml").getroot()
    xml_offsets = {}
    current_system = None
    for element in root.iter():
        name = local_name(element)
        if name == "signalSystem":
            current_system = element.get("refId")
        elif name == "signalPlan":
            current_plan = element.get("id")
        elif name == "offset":
            xml_offsets[(current_system, current_plan)] = int(element.get("sec"))
    if len(xml_offsets) != len(candidate_plans):
        raise AssertionError("Compiled XML plan cardinality differs")
    if any(xml_offsets[key] != int(row["offset_s"]) for key, row in candidate_by_key.items()):
        raise AssertionError("Compiled XML offsets differ from design CSV")

    summary = json.loads((candidate / "corridor_build_summary.json").read_text(encoding="utf-8"))
    result = {
        "status": "pass",
        "implemented_corridor_count": len(implemented),
        "implemented_corridor_system_count": len(system_corridors),
        "valuable_coordinated_time_bin_count": summary["implemented_corridor_bins"],
        "nonzero_offset_plan_count": sum(int(row["offset_s"]) != 0 for row in candidate_plans),
        "fixed_daily_offset_system_count": sum(next(iter(values)) != 0 for values in offsets_by_system.values()),
        "changed_non_offset_input_count": 0,
        "changed_non_offset_plan_field_count": 0,
        "systems_in_multiple_corridors": 0,
        "offset_outside_cycle_count": 0,
        "unsafe_tod_plan_transition_count": 0,
        "compiled_xml_offset_mismatch_count": 0,
        "runtime_validated": False,
        "production_adopted": False,
    }
    qa_path = candidate / "tod_qa_summary.json"
    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    qa.update({
        "status": "all_expressed_tod_15min_corridor_offset_candidate_static_validation_passed_not_runtime_validated",
        "corridor_candidate_count": summary["corridor_candidates"],
        "implemented_corridor_count": result["implemented_corridor_count"],
        "implemented_corridor_system_count": result["implemented_corridor_system_count"],
        "implemented_corridor_time_bin_count": result["valuable_coordinated_time_bin_count"],
        "nonzero_offset_plan_count": result["nonzero_offset_plan_count"],
        "unsafe_tod_plan_transition_count": 0,
        "corridor_runtime_validated": False,
        "production_adopted": False,
    })
    qa_path.write_text(json.dumps(qa, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (candidate / "corridor_validation_summary.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    print(json.dumps(validate(parse_args()), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
