#!/usr/bin/env python3
"""Audit runtime signal states and controlled-approach traffic events."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import contextlib
import csv
import gzip
import json
from pathlib import Path
import re
import subprocess
from typing import Iterable


EVENT_ATTRIBUTE = re.compile(rb'([A-Za-z][A-Za-z0-9_]*)="([^"]*)"')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--pilot-dir", type=Path, required=True)
    parser.add_argument("--iteration", type=int, default=1)
    parser.add_argument("--baseline-run-root", type=Path)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def event_file(run_root: Path, iteration: int) -> Path:
    directory = run_root / "output" / "ITERS" / f"it.{iteration}"
    for suffix in (".zst", ".gz", ""):
        candidate = directory / f"{iteration}.events.xml{suffix}"
        if candidate.is_file():
            return candidate
    return directory / f"{iteration}.events.xml.zst"


@contextlib.contextmanager
def xml_stream(path: Path):
    if path.suffix == ".gz":
        with gzip.open(path, "rb") as stream:
            yield stream
        return
    if path.suffix == ".zst":
        process = subprocess.Popen(
            ["zstd", "-q", "-dc", str(path)], stdout=subprocess.PIPE
        )
        assert process.stdout is not None
        try:
            yield process.stdout
        finally:
            process.stdout.close()
            if process.wait() != 0:
                raise RuntimeError(f"zstd failed for {path}")
        return
    with path.open("rb") as stream:
        yield stream


def iter_events(path: Path) -> Iterable[dict[str, str]]:
    with xml_stream(path) as stream:
        for line in stream:
            if b"<event " not in line:
                continue
            yield {
                key.decode("ascii"): value.decode("utf-8")
                for key, value in EVENT_ATTRIBUTE.findall(line)
            }


def basic_event_counts(
    path: Path,
    controlled_links: set[str],
) -> tuple[Counter[str], Counter[str]]:
    event_types: Counter[str] = Counter()
    approach_entries: Counter[str] = Counter()
    for event in iter_events(path):
        event_type = event.get("type", "")
        event_types[event_type] += 1
        if event_type == "entered link" and event.get("link") in controlled_links:
            approach_entries[event["link"]] += 1
    return event_types, approach_entries


def main() -> int:
    args = parse_args()
    events_path = event_file(args.run_root, args.iteration)
    if not events_path.is_file():
        raise FileNotFoundError(events_path)
    movements = read_csv(args.pilot_dir / "signal_movements.csv")
    conflicts = read_csv(args.pilot_dir / "movement_conflicts.csv")
    capacities = read_csv(args.pilot_dir / "capacity_deconvolution_audit.csv")
    timing = read_csv(args.pilot_dir / "observed_timing_evidence.csv")
    period = json.loads((args.run_root / "run_metadata.json").read_text(encoding="utf-8"))[
        "evidence_period"
    ]
    controlled_links = {row["approach_link_id"] for row in capacities}
    group_stage = {
        (row["signal_system_id"], row["signal_group_id"]): row["stage_label"]
        for row in movements
    }
    cycle_by_system = {
        row["signal_junction_id"]: int(row["cycle_s"])
        for row in timing
        if row["period"] == period
    }
    blocking_stage_pairs: set[tuple[str, str, str]] = set()
    movement_by_signal = {
        (row["signal_junction_id"], row["signal_id"]): row for row in movements
    }
    for row in conflicts:
        if row["blocks_shared_green"].lower() != "true":
            continue
        system = row["signal_junction_id"]
        left = movement_by_signal[(system, row["signal_id_a"])]["signal_group_id"]
        right = movement_by_signal[(system, row["signal_id_b"])]["signal_group_id"]
        blocking_stage_pairs.add((system, left, right))
        blocking_stage_pairs.add((system, right, left))

    transitions: dict[tuple[str, str], list[tuple[float, str]]] = defaultdict(list)
    event_types: Counter[str] = Counter()
    approach_entries: Counter[str] = Counter()
    active_green: dict[str, set[str]] = defaultdict(set)
    latest_red: dict[str, dict[str, float]] = defaultdict(dict)
    overlapping_green_violations: list[dict[str, object]] = []
    intergreen_violations: list[dict[str, object]] = []
    maximum_event_time = 0.0
    for event in iter_events(events_path):
        event_type = event.get("type", "")
        event_types[event_type] += 1
        maximum_event_time = max(maximum_event_time, float(event.get("time", 0.0)))
        if event_type == "entered link" and event.get("link") in controlled_links:
            approach_entries[event["link"]] += 1
        if event_type != "signalGroupStateChangedEvent":
            continue
        time = float(event["time"])
        system = event["signalSystemId"]
        group = event["signalGroupId"]
        state = event["signalGroupState"]
        transitions[(system, group)].append((time, state))
        if state == "GREEN":
            for ending_group, red_time in latest_red[system].items():
                if ending_group != group and time - red_time < 5.0:
                    intergreen_violations.append(
                        {
                            "time": time,
                            "system": system,
                            "beginning_group": group,
                            "ending_group": ending_group,
                            "previous_red": red_time,
                            "actual_intergreen_s": time - red_time,
                        }
                    )
            for other in active_green[system]:
                if (system, group, other) in blocking_stage_pairs:
                    overlapping_green_violations.append(
                        {"time": time, "system": system, "group": group, "other": other}
                    )
            active_green[system].add(group)
        elif state in {"YELLOW", "RED"}:
            active_green[system].discard(group)
            if state == "RED":
                latest_red[system][group] = time

    expected_groups = set(group_stage)
    missing_groups = sorted(expected_groups.difference(transitions))
    amber_violations: list[dict[str, object]] = []
    red_amber_violations: list[dict[str, object]] = []
    terminal_transition_truncations: list[dict[str, object]] = []
    cycle_violations: list[dict[str, object]] = []
    for (system, group), states in transitions.items():
        yellow_times = [time for time, state in states if state == "YELLOW"]
        red_times = [time for time, state in states if state == "RED"]
        red_yellow_times = [time for time, state in states if state == "REDYELLOW"]
        green_times = [time for time, state in states if state == "GREEN"]
        for yellow in yellow_times:
            following = [red for red in red_times if red >= yellow]
            if not following and yellow + 3.0 > maximum_event_time:
                terminal_transition_truncations.append(
                    {"system": system, "group": group, "state": "YELLOW", "time": yellow}
                )
            elif not following or abs(following[0] - yellow - 3.0) > 1e-9:
                amber_violations.append(
                    {"system": system, "group": group, "yellow": yellow, "next_red": following[:1]}
                )
        for red_yellow in red_yellow_times:
            following = [green for green in green_times if green >= red_yellow]
            if not following and red_yellow + 2.0 > maximum_event_time:
                terminal_transition_truncations.append(
                    {
                        "system": system,
                        "group": group,
                        "state": "REDYELLOW",
                        "time": red_yellow,
                    }
                )
            elif not following or abs(following[0] - red_yellow - 2.0) > 1e-9:
                red_amber_violations.append(
                    {
                        "system": system,
                        "group": group,
                        "red_yellow": red_yellow,
                        "next_green": following[:1],
                    }
                )
        cycle = cycle_by_system[system]
        for earlier, later in zip(green_times, green_times[1:]):
            if abs(later - earlier - cycle) > 1e-9:
                cycle_violations.append(
                    {
                        "system": system,
                        "group": group,
                        "earlier": earlier,
                        "later": later,
                        "expected_cycle": cycle,
                    }
                )

    baseline = None
    if args.baseline_run_root is not None:
        baseline_path = event_file(args.baseline_run_root, args.iteration)
        if baseline_path.is_file():
            baseline_types, baseline_entries = basic_event_counts(
                baseline_path, controlled_links
            )
            baseline = {
                "event_file": str(baseline_path),
                "controlled_approach_link_entries": sum(baseline_entries.values()),
                "person_stuck_events": baseline_types.get("stuckAndAbort", 0),
                "signal_delta_controlled_entries": (
                    sum(approach_entries.values()) - sum(baseline_entries.values())
                ),
            }

    violations = (
        len(missing_groups)
        + len(overlapping_green_violations)
        + len(intergreen_violations)
        + len(amber_violations)
        + len(red_amber_violations)
        + len(cycle_violations)
    )
    summary = {
        "status": "validated" if violations == 0 else "failed",
        "run_root": str(args.run_root),
        "iteration": args.iteration,
        "period": period,
        "signal_systems_seen": len({system for system, _ in transitions}),
        "signal_groups_seen": len(transitions),
        "signal_state_events": event_types.get("signalGroupStateChangedEvent", 0),
        "controlled_approach_links_with_entries": len(approach_entries),
        "controlled_approach_link_entries": sum(approach_entries.values()),
        "person_stuck_events": event_types.get("stuckAndAbort", 0),
        "missing_signal_groups": missing_groups,
        "blocking_overlapping_green_violations": overlapping_green_violations,
        "intergreen_duration_violations": intergreen_violations,
        "amber_duration_violations": amber_violations,
        "red_amber_duration_violations": red_amber_violations,
        "terminal_transition_truncations": terminal_transition_truncations,
        "cycle_duration_violations": cycle_violations,
        "baseline": baseline,
    }
    output = args.run_root / f"traffic_signal_event_audit_it{args.iteration}.json"
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if violations == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
