#!/usr/bin/env python3
"""Audit PT stuck-and-abort events at the Hong Kong QSim horizon."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import xml.etree.ElementTree as ET


ATTRIBUTE = re.compile(r'(\w+)="([^"]*)"')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-stuck-events", type=Path, required=True)
    parser.add_argument("--baseline-stuck-events", type=Path, required=True)
    parser.add_argument("--candidate-driver-starts", type=Path, required=True)
    parser.add_argument("--baseline-driver-starts", type=Path, required=True)
    parser.add_argument("--candidate-schedule", type=Path, required=True)
    parser.add_argument("--horizon-s", type=float, default=108_000.0)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def attributes(line: str) -> dict[str, str]:
    return dict(ATTRIBUTE.findall(line))


def seconds(value: str | None) -> float:
    if not value or value == "undefined":
        return math.nan
    parts = value.split(":")
    if len(parts) == 3:
        return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    return float(value)


def read_fragments(path: Path) -> list[dict[str, str]]:
    return [
        attributes(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if "<event " in line
    ]


def read_driver_starts(path: Path) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for row in read_fragments(path):
        driver = row.get("driverId", "")
        if not driver:
            raise ValueError("Transit driver start lacks driverId")
        # Vehicle-block and school-bus drivers can execute several departures.
        # Fragments preserve event order, so the final start is the active
        # departure relevant to a horizon abort for that driver.
        result[driver] = row
    return result


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def open_schedule(path: Path):
    return gzip.open(path, "rb") if path.suffix.lower() == ".gz" else path.open("rb")


def schedule_departures(path: Path) -> dict[str, dict[str, object]]:
    with open_schedule(path) as handle:
        tree = ET.parse(handle)
    result: dict[str, dict[str, object]] = {}
    for line in tree.getroot():
        if local_name(line.tag) != "transitLine":
            continue
        line_id = line.get("id", "")
        for route in line:
            if local_name(route.tag) != "transitRoute":
                continue
            route_id = route.get("id", "")
            route_duration = 0.0
            departures_element = None
            for child in route:
                name = local_name(child.tag)
                if name == "routeProfile":
                    for stop in child:
                        if local_name(stop.tag) != "stop":
                            continue
                        for key in ("arrivalOffset", "departureOffset"):
                            value = seconds(stop.get(key))
                            if math.isfinite(value):
                                route_duration = max(route_duration, value)
                elif name == "departures":
                    departures_element = child
            if departures_element is None:
                raise ValueError(f"Route lacks departures: {line_id}/{route_id}")
            for departure in departures_element:
                if local_name(departure.tag) != "departure":
                    continue
                departure_id = departure.get("id", "")
                departure_time = seconds(departure.get("departureTime"))
                if not departure_id or departure_id in result:
                    raise ValueError(f"Missing/duplicate departure: {departure_id}")
                result[departure_id] = {
                    "line_id": line_id,
                    "route_id": route_id,
                    "departure_time_s": departure_time,
                    "route_duration_s": route_duration,
                    "scheduled_end_s": departure_time + route_duration,
                }
    return result


def quantiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {key: None for key in ("min", "p50", "p90", "p95", "p99", "max")}
    ordered = sorted(values)

    def percentile(fraction: float) -> float:
        position = fraction * (len(ordered) - 1)
        lower = math.floor(position)
        upper = math.ceil(position)
        if lower == upper:
            return ordered[lower]
        return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)

    return {
        "min": ordered[0],
        "p50": statistics.median(ordered),
        "p90": percentile(0.90),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
        "max": ordered[-1],
    }


def submode(route_id: str) -> str:
    return route_id.split("_", 1)[0] if "_" in route_id else route_id


def top(counter: Counter[str], limit: int = 25) -> list[dict[str, object]]:
    return [
        {"id": key, "count": count}
        for key, count in counter.most_common(limit)
    ]


def classify(
    stuck: list[dict[str, str]],
    starts: dict[str, dict[str, str]],
    schedule: dict[str, dict[str, object]],
    horizon: float,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    joined: list[dict[str, object]] = []
    missing_driver = 0
    missing_departure = 0
    for event in stuck:
        driver = event.get("person", "")
        start = starts.get(driver)
        if start is None:
            missing_driver += 1
            continue
        departure_id = start.get("departureId", "")
        scheduled = schedule.get(departure_id)
        if scheduled is None:
            missing_departure += 1
            continue
        event_time = float(event.get("time", "nan"))
        route_id = str(scheduled["route_id"])
        scheduled_end = float(scheduled["scheduled_end_s"])
        joined.append({
            "driver_id": driver,
            "vehicle_id": start.get("vehicleId", ""),
            "departure_id": departure_id,
            "line_id": scheduled["line_id"],
            "route_id": route_id,
            "submode": submode(route_id),
            "event_time_s": event_time,
            "event_type": event.get("type", ""),
            "road_state": event.get("legMode") == "car" and bool(event.get("link")),
            "link_id": event.get("link", ""),
            "day2": departure_id.endswith("__day2"),
            "departure_time_s": scheduled["departure_time_s"],
            "route_duration_s": scheduled["route_duration_s"],
            "scheduled_end_s": scheduled_end,
            "scheduled_end_after_horizon": scheduled_end > horizon,
            "scheduled_seconds_past_horizon": max(0.0, scheduled_end - horizon),
            "scheduled_finish_margin_before_horizon_s": max(0.0, horizon - scheduled_end),
        })
    road = [row for row in joined if row["road_state"]]
    road_day2 = [row for row in road if row["day2"]]
    road_original = [row for row in road if not row["day2"]]
    expected_after = [row for row in road_day2 if row["scheduled_end_after_horizon"]]
    delayed_past = [row for row in road_day2 if not row["scheduled_end_after_horizon"]]
    route_counts = Counter(str(row["route_id"]) for row in road_day2)
    link_counts = Counter(str(row["link_id"]) for row in road_day2)
    summary = {
        "all_pt_stuck_and_abort_events": len(stuck),
        "joined_to_driver_and_schedule": len(joined),
        "missing_driver_mapping": missing_driver,
        "missing_schedule_departure": missing_departure,
        "all_at_exact_horizon": all(
            math.isclose(float(row["event_time_s"]), horizon, abs_tol=1e-9)
            for row in joined
        ),
        "pre_horizon_stuck_events": sum(
            float(row["event_time_s"]) < horizon for row in joined
        ),
        "event_types": dict(Counter(str(row["event_type"]) for row in joined)),
        "road_state_events": len(road),
        "nonroad_horizon_abort_events": len(joined) - len(road),
        "road_day2_events": len(road_day2),
        "road_original_events": len(road_original),
        "road_day2_by_submode": dict(Counter(str(row["submode"]) for row in road_day2)),
        "road_original_by_submode": dict(Counter(str(row["submode"]) for row in road_original)),
        "day2_scheduled_end_after_horizon": len(expected_after),
        "day2_scheduled_end_by_horizon_but_still_active": len(delayed_past),
        "day2_boundary_censoring_share": len(expected_after) / len(road_day2) if road_day2 else None,
        "day2_departure_time_s": quantiles([
            float(row["departure_time_s"]) for row in road_day2
        ]),
        "day2_scheduled_end_s": quantiles([
            float(row["scheduled_end_s"]) for row in road_day2
        ]),
        "scheduled_seconds_past_horizon": quantiles([
            float(row["scheduled_seconds_past_horizon"]) for row in expected_after
        ]),
        "finish_margin_for_delayed_past_horizon_s": quantiles([
            float(row["scheduled_finish_margin_before_horizon_s"]) for row in delayed_past
        ]),
        "top_day2_routes": top(route_counts),
        "top_day2_horizon_links": top(link_counts),
    }
    return summary, joined


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fields = list(rows[0]) if rows else ["driver_id"]
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    inputs = (
        args.candidate_stuck_events, args.baseline_stuck_events,
        args.candidate_driver_starts, args.baseline_driver_starts,
        args.candidate_schedule,
    )
    for path in inputs:
        if not path.is_file():
            raise FileNotFoundError(path)
    if args.output_dir.exists():
        raise FileExistsError(args.output_dir)
    schedule = schedule_departures(args.candidate_schedule)
    candidate, candidate_rows = classify(
        read_fragments(args.candidate_stuck_events),
        read_driver_starts(args.candidate_driver_starts),
        schedule, args.horizon_s,
    )
    baseline, baseline_rows = classify(
        read_fragments(args.baseline_stuck_events),
        read_driver_starts(args.baseline_driver_starts),
        schedule, args.horizon_s,
    )
    # The baseline uses the original timetable, but original departure IDs and
    # route offsets are preserved by the candidate. Day-2 IDs do not occur in it.
    summary = {
        "status": "pt_horizon_stuck_audit_complete_not_adopted",
        "horizon_s": args.horizon_s,
        "candidate": candidate,
        "original_pt_comparison": {
            "candidate_road_original": candidate["road_original_events"],
            "baseline_road_original": baseline["road_original_events"],
            "change": int(candidate["road_original_events"]) - int(baseline["road_original_events"]),
            "candidate_all_original_horizon_aborts": (
                int(candidate["all_pt_stuck_and_abort_events"])
                - int(candidate["road_day2_events"])
            ),
            "baseline_all_horizon_aborts": baseline["all_pt_stuck_and_abort_events"],
        },
        "baseline": baseline,
        "interpretation": {
            "stuck_time_timeout_observed_before_horizon": (
                int(candidate["pre_horizon_stuck_events"]) > 0
            ),
            "extra_road_abort_events_are_day2": (
                int(candidate["road_day2_events"])
                == int(candidate["road_state_events"]) - int(candidate["road_original_events"])
            ),
            "boundary_censoring_is_not_a_road_stuck_timeout": True,
        },
        "inputs": {
            str(path): sha256(path) for path in inputs
        },
    }
    args.output_dir.mkdir(parents=True)
    write_csv(args.output_dir / "candidate_pt_horizon_stuck_events.csv", candidate_rows)
    write_csv(args.output_dir / "baseline_pt_horizon_stuck_events.csv", baseline_rows)
    output = args.output_dir / "pt_horizon_stuck_summary.json"
    output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
