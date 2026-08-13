#!/usr/bin/env python3
"""Audit Hong Kong road congestion, vehicle paths, and network anomalies.

The audit deliberately excludes ordinary PT-passenger stuck events, including
passengers who remain at stops after missing service. Road PT vehicles remain
in scope because their movement and stuck events diagnose the road supply.
"""

from __future__ import annotations

import argparse
from array import array
from collections import Counter, defaultdict
import contextlib
import csv
from dataclasses import dataclass, field
import gzip
import heapq
import io
import json
import math
from pathlib import Path
import re
import subprocess
from typing import BinaryIO, Iterable, Iterator
import xml.etree.ElementTree as ET


EVENT_ATTRIBUTE = re.compile(rb'([A-Za-z][A-Za-z0-9_]*)="([^"]*)"')
NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
HOURS = 31


@dataclass(frozen=True)
class Link:
    link_id: str
    from_node: str
    to_node: str
    length_m: float
    freespeed_m_s: float
    capacity_veh_h: float
    lanes: float
    modes: frozenset[str]
    from_xy: tuple[float, float] | None
    to_xy: tuple[float, float] | None

    @property
    def freeflow_s(self) -> float:
        if self.freespeed_m_s <= 0:
            return math.inf
        # QSim has one-second event resolution. Ratios on sub-second links are
        # otherwise dominated by discretisation rather than congestion.
        return max(1.0, self.length_m / self.freespeed_m_s)


@dataclass
class LinkRuntime:
    traversals: int = 0
    travel_time_s: float = 0.0
    delay_s: float = 0.0
    max_ratio: float = 0.0
    ratio_gt_1_5: int = 0
    ratio_gt_2: int = 0
    ratio_gt_5: int = 0
    hourly_entries: array = field(default_factory=lambda: array("I", [0]) * HOURS)
    hourly_travel_time_s: array = field(default_factory=lambda: array("d", [0.0]) * HOURS)
    hourly_delay_s: array = field(default_factory=lambda: array("d", [0.0]) * HOURS)
    vehicle_classes: Counter[str] = field(default_factory=Counter)


@dataclass
class TripState:
    vehicle: str
    person: str
    vehicle_class: str
    start_time_s: float
    first_link: str
    current_link: str | None
    current_enter_s: float | None
    last_link: str | None = None
    route_length_m: float = 0.0
    freeflow_s: float = 0.0
    travel_time_s: float = 0.0
    repeated_links: int = 0
    immediate_uturns: int = 0
    initial_uturns: int = 0
    internal_uturns: int = 0
    adjacency_mismatches: int = 0
    nonroad_gap_links: int = 0
    road_link_count: int = 0
    sequence_broken_by_nonroad: bool = False
    seen_links: set[str] = field(default_factory=set)
    private_car_trip_ordinal: int | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--links", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--top-n", type=int, default=100)
    parser.add_argument(
        "--traffic-signal-status",
        default="disabled_baseline",
        help="Descriptive run-scope label written to the audit summary.",
    )
    return parser.parse_args()


@contextlib.contextmanager
def binary_stream(path: Path) -> Iterator[BinaryIO]:
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
    with binary_stream(path) as stream:
        for line in stream:
            if b"<event " not in line:
                continue
            yield {
                key.decode("ascii"): value.decode("utf-8")
                for key, value in EVENT_ATTRIBUTE.findall(line)
            }


def node_coord(node_id: str) -> tuple[float, float] | None:
    parts = node_id.rsplit("_", 2)
    if len(parts) != 3:
        return None
    try:
        return float(parts[-2]), float(parts[-1])
    except ValueError:
        return None


def geometry_endpoints(text: str) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
    numbers = [float(value) for value in NUMBER.findall(text)]
    if len(numbers) < 4:
        return None, None
    return (numbers[0], numbers[1]), (numbers[-2], numbers[-1])


def read_links(path: Path) -> dict[str, Link]:
    result: dict[str, Link] = {}
    with binary_stream(path) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        for row in csv.DictReader(text, delimiter=";"):
            modes = frozenset(filter(None, row["modes"].split(",")))
            start, end = geometry_endpoints(row.get("geometry", ""))
            start = start or node_coord(row["from_node"])
            end = end or node_coord(row["to_node"])
            result[row["link"]] = Link(
                link_id=row["link"],
                from_node=row["from_node"],
                to_node=row["to_node"],
                length_m=float(row["length"]),
                freespeed_m_s=float(row["freespeed"]),
                capacity_veh_h=float(row["capacity"]),
                lanes=float(row["lanes"]),
                modes=modes,
                from_xy=start,
                to_xy=end,
            )
    return result


def flow_capacity_factor(path: Path) -> float:
    root = ET.parse(path).getroot()
    for module in root.findall("./module"):
        if module.get("name") != "qsim":
            continue
        for parameter in module.findall("./param"):
            if parameter.get("name") == "flowCapacityFactor":
                return float(parameter.get("value", "1"))
    raise ValueError("qsim.flowCapacityFactor is missing")


def classify_vehicle(vehicle: str, person: str = "") -> str:
    token = f"{vehicle} {person}".lower()
    if "school_bus" in token:
        return "school_bus"
    if "veh_dep_gmb" in token or "_gmb_" in token:
        return "gmb"
    if "veh_dep_bus" in token or "_bus_" in token:
        return "bus"
    if "lrt" in token or "train" in token or "mtr" in token:
        return "rail"
    if "ferry" in token:
        return "ferry"
    if vehicle.startswith("hk_vehicle_") or person.startswith("hk_person_"):
        return "private_car"
    return "other_road_vehicle"


def strongly_connected_components(
    links: dict[str, Link],
) -> tuple[list[set[str]], dict[str, int], dict[str, int]]:
    adjacency: dict[str, list[str]] = defaultdict(list)
    reverse: dict[str, list[str]] = defaultdict(list)
    in_degree: Counter[str] = Counter()
    out_degree: Counter[str] = Counter()
    nodes: set[str] = set()
    for link in links.values():
        adjacency[link.from_node].append(link.to_node)
        reverse[link.to_node].append(link.from_node)
        out_degree[link.from_node] += 1
        in_degree[link.to_node] += 1
        nodes.add(link.from_node)
        nodes.add(link.to_node)

    visited: set[str] = set()
    order: list[str] = []
    for root in nodes:
        if root in visited:
            continue
        visited.add(root)
        stack: list[tuple[str, int]] = [(root, 0)]
        while stack:
            node, index = stack[-1]
            neighbours = adjacency.get(node, [])
            if index < len(neighbours):
                neighbour = neighbours[index]
                stack[-1] = (node, index + 1)
                if neighbour not in visited:
                    visited.add(neighbour)
                    stack.append((neighbour, 0))
            else:
                stack.pop()
                order.append(node)

    assigned: set[str] = set()
    components: list[set[str]] = []
    for root in reversed(order):
        if root in assigned:
            continue
        assigned.add(root)
        component: set[str] = set()
        stack = [root]
        while stack:
            node = stack.pop()
            component.add(node)
            for neighbour in reverse.get(node, []):
                if neighbour not in assigned:
                    assigned.add(neighbour)
                    stack.append(neighbour)
        components.append(component)
    components.sort(key=len, reverse=True)
    return components, dict(in_degree), dict(out_degree)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        path.write_text("\n", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    if args.output_dir.exists():
        raise FileExistsError(f"Output directory must be new: {args.output_dir}")
    args.output_dir.mkdir(parents=True)

    all_links = read_links(args.links)
    road_links = {
        link_id: link for link_id, link in all_links.items() if "car" in link.modes
    }
    capacity_factor = flow_capacity_factor(args.config)
    scc_components, in_degree, out_degree = strongly_connected_components(road_links)
    scc_sizes = [len(component) for component in scc_components]
    largest_scc = scc_components[0] if scc_components else set()
    road_nodes = set(in_degree) | set(out_degree)

    static_rows: list[dict[str, object]] = []
    for link in road_links.values():
        reasons: list[str] = []
        if link.from_node == link.to_node:
            reasons.append("self_loop")
        if link.length_m < 1:
            reasons.append("length_lt_1m")
        elif link.length_m < 5:
            reasons.append("length_lt_5m")
        elif link.length_m < 10:
            reasons.append("length_lt_10m")
        if link.freespeed_m_s <= 0:
            reasons.append("nonpositive_freespeed")
        elif link.freespeed_m_s < 2:
            reasons.append("freespeed_lt_2m_s")
        elif link.freespeed_m_s > 36.1112:
            reasons.append("freespeed_gt_130km_h")
        if link.capacity_veh_h <= 0:
            reasons.append("nonpositive_capacity")
        if link.lanes <= 0:
            reasons.append("nonpositive_lanes")
        if link.to_node not in out_degree:
            reasons.append("directed_sink_to_node")
        if link.from_node not in in_degree:
            reasons.append("directed_source_from_node")
        if link.from_node not in largest_scc or link.to_node not in largest_scc:
            reasons.append("outside_largest_strong_component")
        if reasons:
            static_rows.append(
                {
                    "link_id": link.link_id,
                    "from_node": link.from_node,
                    "to_node": link.to_node,
                    "length_m": link.length_m,
                    "freespeed_km_h": link.freespeed_m_s * 3.6,
                    "capacity_veh_h": link.capacity_veh_h,
                    "lanes": link.lanes,
                    "reasons": "|".join(reasons),
                }
            )

    runtime: dict[str, LinkRuntime] = {}
    active: dict[str, TripState] = {}
    person_vehicle: dict[str, str] = {}
    trip_counts: dict[str, Counter[str]] = defaultdict(Counter)
    stuck_by_class: Counter[str] = Counter()
    stuck_by_link_class: Counter[tuple[str, str]] = Counter()
    stuck_by_hour_link_class: Counter[tuple[int, str, str]] = Counter()
    trip_starts_by_link: Counter[str] = Counter()
    excluded_pt_passenger_stuck = 0
    excluded_other_nonroad_stuck = 0
    all_stuck_leg_modes: Counter[str] = Counter()
    uturn_pairs: Counter[tuple[str, str, str, str]] = Counter()
    initial_private_car_uturn_rows: list[dict[str, object]] = []
    private_car_trip_ordinals: Counter[str] = Counter()
    repeated_links: Counter[str] = Counter()
    traversal_mismatches = 0
    road_traversals = 0
    event_counts: Counter[str] = Counter()
    maximum_event_time = 0.0
    anomaly_heaps: dict[str, list[tuple[float, int, dict[str, object]]]] = defaultdict(list)
    heap_serial = 0

    def push_anomaly(score: float, row: dict[str, object]) -> None:
        nonlocal heap_serial
        heap_serial += 1
        item = (score, heap_serial, row)
        heap = anomaly_heaps[str(row["vehicle_class"])]
        if len(heap) < args.top_n:
            heapq.heappush(heap, item)
        elif score > heap[0][0]:
            heapq.heapreplace(heap, item)

    def finalize_trip(state: TripState, end_time_s: float, status: str) -> None:
        counts = trip_counts[state.vehicle_class]
        counts["trips"] += 1
        counts[status] += 1
        counts["repeated_links"] += state.repeated_links
        counts["immediate_uturns"] += state.immediate_uturns
        counts["initial_uturns"] += state.initial_uturns
        counts["internal_uturns"] += state.internal_uturns
        counts["adjacency_mismatches"] += state.adjacency_mismatches
        counts["nonroad_gap_links"] += state.nonroad_gap_links
        if state.repeated_links:
            counts["trips_with_repeated_links"] += 1
        if state.immediate_uturns:
            counts["trips_with_immediate_uturns"] += 1
        if state.adjacency_mismatches:
            counts["trips_with_adjacency_mismatches"] += 1

        first = road_links.get(state.first_link)
        last = road_links.get(state.last_link or "")
        detour = math.nan
        euclidean = math.nan
        if first and last and first.to_xy and last.to_xy:
            # A MATSim vehicle is inserted at the downstream end of its start
            # link. The start link produces a left-link event but is not a
            # full traversed segment, so the straight-line origin is its to-node.
            euclidean = math.dist(first.to_xy, last.to_xy)
            if euclidean >= 100:
                detour = state.route_length_m / euclidean
        travel_ratio = (
            state.travel_time_s / state.freeflow_s if state.freeflow_s > 0 else math.nan
        )
        if math.isfinite(detour):
            for threshold in (2, 3, 5, 10):
                if detour > threshold:
                    counts[f"detour_gt_{threshold}"] += 1
        score = max(
            detour if math.isfinite(detour) else 0,
            travel_ratio if math.isfinite(travel_ratio) else 0,
            state.immediate_uturns * 5,
            state.repeated_links * 3,
            state.adjacency_mismatches * 20,
        )
        if score >= 2:
            push_anomaly(
                score,
                {
                    "vehicle": state.vehicle,
                    "person": state.person,
                    "vehicle_class": state.vehicle_class,
                    "status": status,
                    "start_time_s": state.start_time_s,
                    "end_time_s": end_time_s,
                    "route_length_m": round(state.route_length_m, 3),
                    "euclidean_m": round(euclidean, 3) if math.isfinite(euclidean) else "",
                    "detour_ratio": round(detour, 6) if math.isfinite(detour) else "",
                    "travel_time_ratio": (
                        round(travel_ratio, 6) if math.isfinite(travel_ratio) else ""
                    ),
                    "repeated_links": state.repeated_links,
                    "immediate_uturns": state.immediate_uturns,
                    "initial_uturns": state.initial_uturns,
                    "internal_uturns": state.internal_uturns,
                    "adjacency_mismatches": state.adjacency_mismatches,
                    "nonroad_gap_links": state.nonroad_gap_links,
                    "first_link": state.first_link,
                    "last_link": state.last_link or "",
                },
            )

    for event in iter_events(args.events):
        event_type = event.get("type", "")
        event_counts[event_type] += 1
        time_s = float(event.get("time", 0))
        maximum_event_time = max(maximum_event_time, time_s)
        if event_type == "vehicle enters traffic":
            vehicle = event.get("vehicle", "")
            person = event.get("person", "")
            link_id = event.get("link", "")
            if vehicle in active:
                finalize_trip(active.pop(vehicle), time_s, "interrupted")
            vehicle_class = classify_vehicle(vehicle, person)
            private_car_trip_ordinal = None
            if vehicle_class == "private_car" and person:
                private_car_trip_ordinal = private_car_trip_ordinals[person]
                private_car_trip_ordinals[person] += 1
            active[vehicle] = TripState(
                vehicle=vehicle,
                person=person,
                vehicle_class=vehicle_class,
                start_time_s=time_s,
                first_link=link_id,
                current_link=link_id,
                current_enter_s=time_s,
                private_car_trip_ordinal=private_car_trip_ordinal,
            )
            if link_id in road_links:
                trip_starts_by_link[link_id] += 1
            if person:
                person_vehicle[person] = vehicle
        elif event_type == "entered link":
            vehicle = event.get("vehicle", "")
            state = active.get(vehicle)
            if state is not None:
                state.current_link = event.get("link", "")
                state.current_enter_s = time_s
        elif event_type == "left link":
            vehicle = event.get("vehicle", "")
            link_id = event.get("link", "")
            state = active.get(vehicle)
            if state is None:
                traversal_mismatches += 1
                continue
            if state.current_link != link_id or state.current_enter_s is None:
                state.adjacency_mismatches += 1
                traversal_mismatches += 1
                state.current_link = None
                state.current_enter_s = None
                continue
            link = road_links.get(link_id)
            if link is not None:
                travel_time = max(0.0, time_s - state.current_enter_s)
                ratio = travel_time / link.freeflow_s
                delay = max(0.0, travel_time - link.freeflow_s)
                aggregate = runtime.setdefault(link_id, LinkRuntime())
                aggregate.traversals += 1
                aggregate.travel_time_s += travel_time
                aggregate.delay_s += delay
                aggregate.max_ratio = max(aggregate.max_ratio, ratio)
                aggregate.ratio_gt_1_5 += ratio > 1.5
                aggregate.ratio_gt_2 += ratio > 2
                aggregate.ratio_gt_5 += ratio > 5
                hour = min(HOURS - 1, max(0, int(state.current_enter_s // 3600)))
                aggregate.hourly_entries[hour] += 1
                aggregate.hourly_travel_time_s[hour] += travel_time
                aggregate.hourly_delay_s[hour] += delay
                aggregate.vehicle_classes[state.vehicle_class] += 1
                road_traversals += 1

                if state.last_link is not None and not state.sequence_broken_by_nonroad:
                    previous = road_links.get(state.last_link)
                    if previous is not None:
                        if previous.to_node != link.from_node:
                            state.adjacency_mismatches += 1
                        if (
                            previous.from_node == link.to_node
                            and previous.to_node == link.from_node
                        ):
                            state.immediate_uturns += 1
                            position = "initial" if state.road_link_count == 1 else "internal"
                            if position == "initial":
                                state.initial_uturns += 1
                                if (state.vehicle_class == "private_car"
                                        and state.private_car_trip_ordinal is not None):
                                    initial_private_car_uturn_rows.append(
                                        {
                                            "person_id": state.person,
                                            "vehicle_id": state.vehicle,
                                            "private_car_trip_ordinal": state.private_car_trip_ordinal,
                                            "vehicle_enters_traffic_time_s": state.start_time_s,
                                            "uturn_transition_time_s": time_s,
                                            "start_link_id": previous.link_id,
                                            "observed_reverse_link_id": link.link_id,
                                        }
                                    )
                            else:
                                state.internal_uturns += 1
                            uturn_pairs[
                                (state.vehicle_class, position, previous.link_id, link.link_id)
                            ] += 1
                if link_id in state.seen_links:
                    state.repeated_links += 1
                    repeated_links[link_id] += 1
                state.seen_links.add(link_id)
                state.last_link = link_id
                # The first left-link event closes MATSim's start link; the
                # vehicle was inserted at its downstream end rather than
                # traversing the full segment. Keep its queueing time in the
                # link congestion statistics, but exclude its geometry from
                # trip distance/free-flow path diagnostics.
                if not (state.road_link_count == 0 and link_id == state.first_link):
                    state.route_length_m += link.length_m
                    state.freeflow_s += link.freeflow_s
                state.travel_time_s += travel_time
                state.road_link_count += 1
                state.sequence_broken_by_nonroad = False
            else:
                state.nonroad_gap_links += 1
                state.sequence_broken_by_nonroad = True
            state.current_link = None
            state.current_enter_s = None
        elif event_type == "vehicle leaves traffic":
            vehicle = event.get("vehicle", "")
            state = active.pop(vehicle, None)
            if state is not None:
                finalize_trip(state, time_s, "completed")
                person_vehicle.pop(state.person, None)
        elif "stuck" in event_type.lower():
            person = event.get("person", "")
            link_id = event.get("link", "")
            leg_mode = event.get("legMode", "")
            all_stuck_leg_modes[leg_mode] += 1
            is_pt_vehicle = person.startswith("pt_veh_")
            if not is_pt_vehicle and leg_mode == "pt":
                excluded_pt_passenger_stuck += 1
                continue
            if link_id not in road_links or (
                not is_pt_vehicle and leg_mode not in {"car", "school_bus_vehicle"}
            ):
                excluded_other_nonroad_stuck += 1
                continue
            vehicle = person_vehicle.get(person, "")
            vehicle_class = classify_vehicle(vehicle, person)
            stuck_by_class[vehicle_class] += 1
            stuck_by_link_class[(link_id, vehicle_class)] += 1
            hour = min(HOURS - 1, max(0, int(time_s // 3600)))
            stuck_by_hour_link_class[(hour, link_id, vehicle_class)] += 1
            state = active.pop(vehicle, None)
            if state is not None:
                finalize_trip(state, time_s, "stuck")
                person_vehicle.pop(state.person, None)

    for state in list(active.values()):
        finalize_trip(state, maximum_event_time, "terminal_active")

    link_rows: list[dict[str, object]] = []
    for link_id, aggregate in runtime.items():
        link = road_links[link_id]
        mean_time = aggregate.travel_time_s / aggregate.traversals
        mean_ratio = mean_time / link.freeflow_s
        peak_hour = max(range(HOURS), key=aggregate.hourly_entries.__getitem__)
        peak_count = int(aggregate.hourly_entries[peak_hour])
        effective_capacity = link.capacity_veh_h * capacity_factor
        link_rows.append(
            {
                "link_id": link_id,
                "from_node": link.from_node,
                "to_node": link.to_node,
                "length_m": round(link.length_m, 3),
                "freespeed_km_h": round(link.freespeed_m_s * 3.6, 3),
                "capacity_veh_h": link.capacity_veh_h,
                "effective_capacity_factor": capacity_factor,
                "lanes": link.lanes,
                "inside_largest_strong_component": (
                    link.from_node in largest_scc and link.to_node in largest_scc
                ),
                "traversals": aggregate.traversals,
                "trip_starts_on_link": trip_starts_by_link[link_id],
                "trip_start_share_of_traversals": round(
                    trip_starts_by_link[link_id] / aggregate.traversals, 6
                ),
                "mean_travel_time_s": round(mean_time, 6),
                "freeflow_time_s": round(link.freeflow_s, 6),
                "mean_travel_time_ratio": round(mean_ratio, 6),
                "max_travel_time_ratio": round(aggregate.max_ratio, 6),
                "total_delay_s": round(aggregate.delay_s, 6),
                "share_ratio_gt_1_5": round(aggregate.ratio_gt_1_5 / aggregate.traversals, 6),
                "share_ratio_gt_2": round(aggregate.ratio_gt_2 / aggregate.traversals, 6),
                "share_ratio_gt_5": round(aggregate.ratio_gt_5 / aggregate.traversals, 6),
                "peak_entry_hour": peak_hour,
                "peak_vehicle_entries": peak_count,
                "peak_vehicle_count_capacity_proxy": (
                    round(peak_count / effective_capacity, 6)
                    if effective_capacity > 0
                    else ""
                ),
                "vehicle_classes": "|".join(
                    f"{key}:{value}" for key, value in sorted(aggregate.vehicle_classes.items())
                ),
                "road_vehicle_stuck_events": sum(
                    stuck_by_link_class[(link_id, vehicle_class)]
                    for vehicle_class in stuck_by_class
                ),
            }
        )
    link_rows.sort(key=lambda row: float(row["total_delay_s"]), reverse=True)
    write_csv(args.output_dir / "link_runtime_audit.csv", link_rows)
    write_csv(args.output_dir / "static_network_anomalies.csv", static_rows)

    stuck_rows = [
        {
            "link_id": link_id,
            "vehicle_class": vehicle_class,
            "stuck_events": count,
            "from_node": road_links[link_id].from_node,
            "to_node": road_links[link_id].to_node,
            "length_m": road_links[link_id].length_m,
            "freespeed_km_h": road_links[link_id].freespeed_m_s * 3.6,
            "capacity_veh_h": road_links[link_id].capacity_veh_h,
        }
        for (link_id, vehicle_class), count in stuck_by_link_class.most_common()
    ]
    write_csv(args.output_dir / "road_vehicle_stuck_hotspots.csv", stuck_rows)
    write_csv(
        args.output_dir / "road_vehicle_stuck_by_hour.csv",
        [
            {
                "hour": hour,
                "link_id": link_id,
                "vehicle_class": vehicle_class,
                "stuck_events": count,
            }
            for (hour, link_id, vehicle_class), count in sorted(
                stuck_by_hour_link_class.items(), key=lambda item: (-item[1], item[0])
            )
        ],
    )
    anomaly_rows = [
        item[2]
        for vehicle_class in sorted(anomaly_heaps)
        for item in sorted(anomaly_heaps[vehicle_class], reverse=True)
    ]
    write_csv(
        args.output_dir / "trip_path_anomalies_top.csv",
        anomaly_rows,
    )
    write_csv(
        args.output_dir / "immediate_uturn_pairs.csv",
        [
            {
                "vehicle_class": pair[0],
                "position": pair[1],
                "from_link": pair[2],
                "to_link": pair[3],
                "count": count,
            }
            for pair, count in uturn_pairs.most_common()
        ],
    )
    write_csv(
        args.output_dir / "initial_private_car_uturn_events.csv",
        initial_private_car_uturn_rows,
    )

    congested_100 = [row for row in link_rows if int(row["traversals"]) >= 100]
    top_mean_ratio = sorted(
        congested_100, key=lambda row: float(row["mean_travel_time_ratio"]), reverse=True
    )[: args.top_n]
    top_delay = link_rows[: args.top_n]
    top_volume_proxy = sorted(
        link_rows,
        key=lambda row: float(row["peak_vehicle_count_capacity_proxy"] or 0),
        reverse=True,
    )[: args.top_n]
    write_csv(args.output_dir / "top_links_by_mean_ratio.csv", top_mean_ratio)
    write_csv(args.output_dir / "top_links_by_total_delay.csv", top_delay)
    write_csv(args.output_dir / "top_links_by_vehicle_count_capacity_proxy.csv", top_volume_proxy)
    hourly_rows: list[dict[str, object]] = []
    for link_row in link_rows[: max(args.top_n, 200)]:
        link_id = str(link_row["link_id"])
        aggregate = runtime[link_id]
        for hour in range(HOURS):
            count = int(aggregate.hourly_entries[hour])
            if count == 0:
                continue
            hourly_rows.append(
                {
                    "link_id": link_id,
                    "hour": hour,
                    "entries": count,
                    "mean_travel_time_s": round(
                        aggregate.hourly_travel_time_s[hour] / count, 6
                    ),
                    "mean_travel_time_ratio": round(
                        aggregate.hourly_travel_time_s[hour] / count
                        / road_links[link_id].freeflow_s,
                        6,
                    ),
                    "total_delay_s": round(aggregate.hourly_delay_s[hour], 6),
                }
            )
    write_csv(args.output_dir / "top_delay_links_hourly_profile.csv", hourly_rows)

    static_reason_counts: Counter[str] = Counter()
    for row in static_rows:
        static_reason_counts.update(str(row["reasons"]).split("|"))
    summary = {
        "status": "audited",
        "scope": {
            "traffic_signals": args.traffic_signal_status,
            "road_links": len(road_links),
            "road_nodes": len(road_nodes),
            "road_links_outside_largest_scc": sum(
                link.from_node not in largest_scc or link.to_node not in largest_scc
                for link in road_links.values()
            ),
            "events": str(args.events),
            "excluded_from_road_findings": "ordinary PT-passenger stuck/waiting events",
            "included_as_road_findings": "private Car, Bus, GMB, school-bus and other road-vehicle events",
        },
        "network": {
            "strongly_connected_component_count": len(scc_sizes),
            "largest_scc_nodes": scc_sizes[0] if scc_sizes else 0,
            "largest_scc_node_share": scc_sizes[0] / len(road_nodes) if road_nodes else 0,
            "scc_size_top20": scc_sizes[:20],
            "directed_sink_nodes": sum(node not in out_degree for node in road_nodes),
            "directed_source_nodes": sum(node not in in_degree for node in road_nodes),
            "static_anomaly_reason_counts": dict(static_reason_counts),
        },
        "runtime": {
            "road_link_traversals": road_traversals,
            "road_links_with_traversals": len(runtime),
            "road_links_without_traversals": len(road_links) - len(runtime),
            "event_counts_selected": {
                key: event_counts[key]
                for key in (
                    "vehicle enters traffic",
                    "entered link",
                    "left link",
                    "vehicle leaves traffic",
                    "stuckAndAbort",
                )
            },
            "traversal_state_mismatches": traversal_mismatches,
            "road_vehicle_stuck_by_class": dict(stuck_by_class),
            "road_vehicle_stuck_total": sum(stuck_by_class.values()),
            "excluded_pt_passenger_stuck_events": excluded_pt_passenger_stuck,
            "excluded_other_nonroad_stuck_events": excluded_other_nonroad_stuck,
            "all_stuck_events_by_leg_mode": dict(all_stuck_leg_modes),
            "trip_path_by_vehicle_class": {
                key: dict(value) for key, value in sorted(trip_counts.items())
            },
            "immediate_uturn_pair_count": len(uturn_pairs),
            "immediate_uturn_event_count": sum(uturn_pairs.values()),
            "initial_private_car_uturn_event_rows": len(initial_private_car_uturn_rows),
            "immediate_uturn_events_by_vehicle_class": dict(
                Counter(
                    {
                        vehicle_class: sum(
                            count
                            for (candidate_class, _position, _from, _to), count
                            in uturn_pairs.items()
                            if candidate_class == vehicle_class
                        )
                        for vehicle_class in {pair[0] for pair in uturn_pairs}
                    }
                )
            ),
            "repeated_link_id_count": len(repeated_links),
            "repeated_link_event_count": sum(repeated_links.values()),
        },
        "congestion": {
            "links_ge_100_traversals": len(congested_100),
            "links_ge_100_mean_ratio_gt_1_5": sum(
                float(row["mean_travel_time_ratio"]) > 1.5 for row in congested_100
            ),
            "links_ge_100_mean_ratio_gt_2": sum(
                float(row["mean_travel_time_ratio"]) > 2 for row in congested_100
            ),
            "total_road_delay_vehicle_hours": sum(
                float(row["total_delay_s"]) for row in link_rows
            )
            / 3600,
            "capacity_proxy_warning": (
                "peak vehicle-count/capacity is diagnostic only; MATSim vehicle PCU factors "
                "are not reconstructed in this audit"
            ),
        },
        "outputs": {
            "link_runtime_audit": "link_runtime_audit.csv",
            "road_vehicle_stuck_hotspots": "road_vehicle_stuck_hotspots.csv",
            "road_vehicle_stuck_by_hour": "road_vehicle_stuck_by_hour.csv",
            "trip_path_anomalies_top": "trip_path_anomalies_top.csv",
            "immediate_uturn_pairs": "immediate_uturn_pairs.csv",
            "initial_private_car_uturn_events": "initial_private_car_uturn_events.csv",
            "static_network_anomalies": "static_network_anomalies.csv",
            "top_delay_links_hourly_profile": "top_delay_links_hourly_profile.csv",
        },
    }
    (args.output_dir / "road_network_runtime_audit_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
