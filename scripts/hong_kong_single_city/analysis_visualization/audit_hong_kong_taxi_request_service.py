#!/usr/bin/env python3
"""Audit physical-Taxi request service from the compact MATSim request CSV."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
from collections import Counter, defaultdict
from pathlib import Path


PICKED_STATUSES = {"completed", "onboard"}
TERMINAL_STATUSES = {"completed", "waiting", "onboard", "rejected"}


def percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def summarize_waits(values: list[float]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "mean_s": sum(values) / len(values) if values else None,
        "p50_s": percentile(values, 0.50),
        "p90_s": percentile(values, 0.90),
        "p95_s": percentile(values, 0.95),
    }


def audit(path: Path) -> dict[str, object]:
    opener = gzip.open if path.suffix == ".gz" else open
    statuses: Counter[str] = Counter()
    statuses_by_class: dict[str, Counter[str]] = {
        "behavioral": Counter(),
        "operational": Counter(),
    }
    completed_waits: list[float] = []
    picked_waits: list[float] = []
    completed_waits_by_class: dict[str, list[float]] = {
        "behavioral": [],
        "operational": [],
    }
    submitted_by_hour: Counter[int] = Counter()
    picked_by_hour: Counter[int] = Counter()

    with opener(path, "rt", encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            status = row["status"]
            if status not in TERMINAL_STATUSES:
                raise ValueError(f"Unexpected Taxi request status: {status}")
            request_class = (
                "operational" if row["operational_only"].lower() == "true" else "behavioral"
            )
            submitted_s = float(row["submitted_s"])
            wait_s = float(row["wait_s"])
            statuses[status] += 1
            statuses_by_class[request_class][status] += 1
            submitted_by_hour[int(submitted_s // 3600)] += 1
            if status in PICKED_STATUSES:
                picked_waits.append(wait_s)
                picked_by_hour[int(submitted_s // 3600)] += 1
            if status == "completed":
                completed_waits.append(wait_s)
                completed_waits_by_class[request_class].append(wait_s)

    submitted = sum(statuses.values())
    picked = sum(statuses[status] for status in PICKED_STATUSES)
    not_picked = statuses["waiting"] + statuses["rejected"]
    active_hours = sorted(submitted_by_hour)
    pickup_blackout_hours = [
        hour for hour in active_hours if submitted_by_hour[hour] > 0 and picked_by_hour[hour] == 0
    ]
    hourly = [
        {
            "request_hour": hour,
            "submitted": submitted_by_hour[hour],
            "picked": picked_by_hour[hour],
        }
        for hour in active_hours
    ]

    return {
        "source": str(path),
        "submitted": submitted,
        "status_counts": dict(statuses),
        "request_conservation": submitted == sum(statuses.values()),
        "picked": picked,
        "not_picked": not_picked,
        "not_picked_share": not_picked / submitted if submitted else None,
        "completed_wait": summarize_waits(completed_waits),
        "picked_wait": summarize_waits(picked_waits),
        "completed_wait_by_class": {
            key: summarize_waits(value) for key, value in completed_waits_by_class.items()
        },
        "status_counts_by_class": {
            key: dict(value) for key, value in statuses_by_class.items()
        },
        "pickup_blackout_hours": pickup_blackout_hours,
        "hourly_submission_pickup": hourly,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("request_audit", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.request_audit)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
