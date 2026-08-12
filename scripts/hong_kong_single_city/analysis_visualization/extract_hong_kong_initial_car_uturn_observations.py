#!/usr/bin/env python3
"""Extract every event-derived initial private-Car reverse transition.

This is the lightweight precursor to the full road runtime audit.  It preserves
the same MATSim start-link semantics while emitting the person and per-person
Car-trip ordinal needed by the bounded activity-anchor repair.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from dataclasses import dataclass
import json
from pathlib import Path

from audit_hong_kong_road_network_runtime import (
    Link,
    classify_vehicle,
    iter_events,
    read_links,
)


@dataclass
class State:
    person_id: str
    vehicle_id: str
    trip_ordinal: int
    start_time_s: float
    last_road_link_id: str | None = None
    road_link_count: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--links", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def exact_reverse(first: Link, second: Link) -> bool:
    return first.from_node == second.to_node and first.to_node == second.from_node


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fields = list(rows[0]) if rows else [
        "person_id",
        "vehicle_id",
        "private_car_trip_ordinal",
        "vehicle_enters_traffic_time_s",
        "uturn_transition_time_s",
        "start_link_id",
        "observed_reverse_link_id",
    ]
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    if args.output_dir.exists():
        raise FileExistsError(args.output_dir)
    args.output_dir.mkdir(parents=True)
    links = read_links(args.links)
    active: dict[str, State] = {}
    trip_ordinals: Counter[str] = Counter()
    rows: list[dict[str, object]] = []
    event_counts: Counter[str] = Counter()

    for event in iter_events(args.events):
        event_type = event.get("type", "")
        event_counts[event_type] += 1
        if event_type == "vehicle enters traffic":
            vehicle_id = event.get("vehicle", "")
            person_id = event.get("person", "")
            if classify_vehicle(vehicle_id, person_id) != "private_car":
                continue
            ordinal = trip_ordinals[person_id]
            trip_ordinals[person_id] += 1
            active[vehicle_id] = State(
                person_id=person_id,
                vehicle_id=vehicle_id,
                trip_ordinal=ordinal,
                start_time_s=float(event.get("time", 0.0)),
            )
        elif event_type == "left link":
            vehicle_id = event.get("vehicle", "")
            state = active.get(vehicle_id)
            if state is None:
                continue
            link_id = event.get("link", "")
            link = links.get(link_id)
            if link is None:
                state.last_road_link_id = None
                continue
            if state.road_link_count == 1 and state.last_road_link_id is not None:
                previous = links[state.last_road_link_id]
                if exact_reverse(previous, link):
                    rows.append(
                        {
                            "person_id": state.person_id,
                            "vehicle_id": state.vehicle_id,
                            "private_car_trip_ordinal": state.trip_ordinal,
                            "vehicle_enters_traffic_time_s": state.start_time_s,
                            "uturn_transition_time_s": float(event.get("time", 0.0)),
                            "start_link_id": previous.link_id,
                            "observed_reverse_link_id": link.link_id,
                        }
                    )
            state.last_road_link_id = link_id
            state.road_link_count += 1
        elif event_type == "vehicle leaves traffic":
            active.pop(event.get("vehicle", ""), None)

    write_csv(args.output_dir / "initial_private_car_uturn_events.csv", rows)
    summary = {
        "status": "extracted",
        "links": str(args.links),
        "events": str(args.events),
        "private_car_trip_count": sum(trip_ordinals.values()),
        "persons_with_private_car_traffic": len(trip_ordinals),
        "initial_private_car_uturn_event_rows": len(rows),
        "unique_person_trip_keys": len(
            {(row["person_id"], row["private_car_trip_ordinal"]) for row in rows}
        ),
        "selected_event_counts": {
            name: event_counts[name]
            for name in ("vehicle enters traffic", "left link", "vehicle leaves traffic")
        },
        "output": "initial_private_car_uturn_events.csv",
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
