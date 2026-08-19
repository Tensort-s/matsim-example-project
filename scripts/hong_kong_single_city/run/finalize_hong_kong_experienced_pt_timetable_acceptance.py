#!/usr/bin/env python3
"""Re-evaluate immutable PT timing smoke metrics with corrected gate semantics."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-summary", type=Path, required=True)
    parser.add_argument("--timetable-summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def corrected_summary(
    source: dict[str, object], timetable: dict[str, object]
) -> dict[str, object]:
    candidate_states = source["candidate_unfinished_states"]
    base_states = source["candidate5b_unfinished_states"]
    assert isinstance(candidate_states, dict) and isinstance(base_states, dict)
    candidate_unresolved = (
        int(candidate_states["pt_waiting_before_boarding"])
        + int(candidate_states["pt_unfinished_onboard_or_transfer"])
    )
    base_unresolved = (
        int(base_states["pt_waiting_before_boarding"])
        + int(base_states["pt_unfinished_onboard_or_transfer"])
    )
    unresolved_ratio = (
        candidate_unresolved / base_unresolved
        if base_unresolved else (0.0 if candidate_unresolved == 0 else None)
    )

    qa = timetable["qa"]
    assert isinstance(qa, dict)
    technical = dict(source["technical_gates"])
    technical["timetable_reference_qa_passed"] = (
        qa["duplicate_departure_ids"] == 0
        and qa["missing_vehicle_references"] == 0
        and bool(qa["all_adjusted_stop_offsets_monotonic"])
        and bool(qa["day2_departure_times_within_target"])
    )
    performance = dict(source["performance_gates"])
    performance.pop("pt_unfinished_onboard_or_transfer_not_worse", None)
    performance["combined_unresolved_pt_states_reduced_at_least_25_percent"] = (
        unresolved_ratio is not None and unresolved_ratio <= 0.75
    )
    ratios = {
        key: (
            None
            if isinstance(value, float) and not math.isfinite(value)
            else value
        )
        for key, value in dict(source["ratios"]).items()
    }
    ratios["combined_unresolved_pt_states"] = unresolved_ratio

    result = dict(source)
    result["status"] = (
        "pt_timing_gate_passed_not_adopted"
        if all(technical.values()) and all(performance.values())
        else "pt_timing_gate_not_passed_not_adopted"
    )
    result["ratios"] = ratios
    result["technical_gates"] = technical
    result["performance_gates"] = performance
    result["acceptance_interpretation"] = {
        "candidate_unresolved_pt_states": candidate_unresolved,
        "candidate5b_unresolved_pt_states": base_unresolved,
        "unresolved_pt_states_change": candidate_unresolved - base_unresolved,
        "onboard_or_transfer_increase_is_reported_not_hidden": True,
        "reason_for_combined_gate": (
            "new day-2 service can validly move a passenger from waiting-before-boarding "
            "to onboard-at-horizon; acceptance therefore requires the combined unresolved "
            "state to fall, while preserving each component count"
        ),
    }
    return result


def main() -> int:
    args = parse_args()
    for path in (args.source_summary, args.timetable_summary):
        if not path.is_file():
            raise FileNotFoundError(path)
    if args.output_dir.exists():
        raise FileExistsError(args.output_dir)
    source = json.loads(args.source_summary.read_text(encoding="utf-8"))
    timetable = json.loads(args.timetable_summary.read_text(encoding="utf-8"))
    result = corrected_summary(source, timetable)
    result["acceptance_revision"] = {
        "version": "v3",
        "source_summary": str(args.source_summary),
        "source_summary_sha256": sha256(args.source_summary),
        "timetable_summary": str(args.timetable_summary),
        "timetable_summary_sha256": sha256(args.timetable_summary),
        "simulation_reused_without_rerun": True,
        "zero_baseline_nonzero_candidate_ratio": "null",
    }
    args.output_dir.mkdir(parents=True)
    output = args.output_dir / "experienced_pt_timetable_smoke_summary.json"
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
