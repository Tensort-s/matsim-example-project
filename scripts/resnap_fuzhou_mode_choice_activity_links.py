#!/usr/bin/env python3
"""Spread activity link snapping and reroute car legs for Fuzhou mode-choice plans.

The input population already contains car/bus/metro/walk candidate plans. This
script keeps the plan set and mode choices, but resamples every activity's car
network link from nearby links instead of always using the nearest link. Car
legs are then rerouted between the updated activity links. PT and walk legs keep
their route-free form, but their adjacent activities receive the same updated
links for consistency.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import pathlib
import random
import time
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from typing import Any

import networkx as nx
import numpy as np
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

from generate_matsim_routes_from_agents import batch_route_links, hms


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_INPUT = (
    ROOT
    / "data"
    / "matsim_routes"
    / "fuzhou_city_23_greenspace_grid_multi_activity_2pct_same_day_night"
    / "mode_choice_plans_bus_metro_2pct.xml.gz"
)
DEFAULT_NETWORK = (
    ROOT
    / "data"
    / "transit"
    / "fuzhou_transit_matsim_integrated_20260709_bus_priority_carcap5_floor_lanes_raw"
    / "network_with_car_busprio_metro.xml.gz"
)
DEFAULT_LINK_QA = (
    ROOT
    / "data"
    / "transit"
    / "fuzhou_transit_matsim_integrated_20260709_bus_priority_carcap5_floor_lanes_raw"
    / "bus_priority_network_qa.csv"
)
DEFAULT_OUT_DIR = (
    ROOT
    / "data"
    / "matsim_routes"
    / "fuzhou_city_23_greenspace_grid_multi_activity_2pct_busprio_floor_snapspread"
)

MAJOR_HIGHWAYS = {"motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link", "secondary", "secondary_link"}
MID_HIGHWAYS = {"tertiary", "tertiary_link", "unclassified", "residential"}
LOW_HIGHWAYS = {"service", "living_street"}


@dataclass
class Link:
    id: str
    from_node: str
    to_node: str
    length: float
    freespeed: float
    capacity: float
    permlanes: float
    geometry: LineString
    highway: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=pathlib.Path, default=DEFAULT_INPUT)
    parser.add_argument("--network", type=pathlib.Path, default=DEFAULT_NETWORK)
    parser.add_argument("--link-qa", type=pathlib.Path, default=DEFAULT_LINK_QA)
    parser.add_argument("--out-dir", type=pathlib.Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--output-name", default="mode_choice_plans_bus_metro_2pct_snapspread.xml.gz")
    parser.add_argument("--candidate-radius-m", type=float, default=300.0)
    parser.add_argument("--max-candidates", type=int, default=10)
    parser.add_argument("--distance-offset-m", type=float, default=20.0)
    parser.add_argument("--seed", type=int, default=20260710)
    parser.add_argument("--route-batch-size", type=int, default=256)
    return parser.parse_args()


def open_text(path: pathlib.Path, mode: str):
    if path.suffix == ".gz":
        return gzip.open(path, mode, encoding="utf-8", newline="\n")
    return path.open(mode, encoding="utf-8", newline="\n")


def split_modes(value: str | None) -> set[str]:
    return {x.strip() for x in (value or "").replace(";", ",").split(",") if x.strip()}


def as_float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except ValueError:
        return default


def load_link_qa(path: pathlib.Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {row["link_id"]: row for row in csv.DictReader(handle) if row.get("link_id")}


def parse_network(path: pathlib.Path, link_qa: dict[str, dict[str, str]]) -> tuple[list[Link], dict[str, Link]]:
    nodes: dict[str, tuple[float, float]] = {}
    raw_links: list[dict[str, str]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for _event, elem in ET.iterparse(handle, events=("end",)):
            if elem.tag == "node":
                nodes[elem.get("id", "")] = (as_float(elem.get("x")), as_float(elem.get("y")))
            elif elem.tag == "link":
                if "car" in split_modes(elem.get("modes")):
                    raw_links.append(dict(elem.attrib))
            elem.clear()

    links: list[Link] = []
    for row in raw_links:
        from_node = row.get("from", "")
        to_node = row.get("to", "")
        if from_node not in nodes or to_node not in nodes:
            continue
        a = nodes[from_node]
        b = nodes[to_node]
        if a == b:
            continue
        link_id = row.get("id", "")
        length = as_float(row.get("length"), math.dist(a, b))
        freespeed = as_float(row.get("freespeed"), 1.0)
        if length <= 0 or freespeed <= 0:
            continue
        qa = link_qa.get(link_id, {})
        links.append(
            Link(
                id=link_id,
                from_node=from_node,
                to_node=to_node,
                length=length,
                freespeed=freespeed,
                capacity=as_float(row.get("capacity")),
                permlanes=as_float(row.get("permlanes"), 1.0),
                geometry=LineString([a, b]),
                highway=(qa.get("highway") or "").lower(),
            )
        )
    return links, {link.id: link for link in links}


def build_graph(links: list[Link]) -> nx.DiGraph:
    graph = nx.DiGraph()
    for link in links:
        weight = link.length / link.freespeed
        existing = graph.get_edge_data(link.from_node, link.to_node)
        if existing is None or weight < existing["weight"]:
            graph.add_edge(link.from_node, link.to_node, weight=weight, length=link.length, link_id=link.id)
    return graph


def largest_strong_links(graph: nx.DiGraph, links: list[Link]) -> tuple[list[Link], dict[str, Any]]:
    components = list(nx.strongly_connected_components(graph))
    if not components:
        raise RuntimeError("car graph has no strongly connected component")
    largest = max(components, key=len)
    selected = [link for link in links if link.from_node in largest and link.to_node in largest]
    return selected, {
        "strong_component_count": len(components),
        "largest_strong_node_count": len(largest),
        "largest_strong_link_count": len(selected),
        "all_car_link_count": len(links),
    }


def road_weight(highway: str) -> float:
    if highway in MAJOR_HIGHWAYS:
        return 1.5
    if highway in LOW_HIGHWAYS:
        return 0.5
    if highway in MID_HIGHWAYS:
        return 1.0
    return 1.0


def choose_link(
    point: Point,
    tree: STRtree,
    links: list[Link],
    rng: random.Random,
    radius_m: float,
    max_candidates: int,
    distance_offset_m: float,
) -> tuple[Link, dict[str, Any]]:
    indices = list(tree.query(point.buffer(radius_m)))
    candidates: list[tuple[float, Link]] = []
    for idx_raw in indices:
        idx = int(idx_raw)
        link = links[idx]
        dist = float(point.distance(link.geometry))
        if dist <= radius_m:
            candidates.append((dist, link))
    candidates.sort(key=lambda item: item[0])
    fallback = False
    if not candidates:
        idx = int(tree.nearest(point))
        link = links[idx]
        candidates = [(float(point.distance(link.geometry)), link)]
        fallback = True
    candidates = candidates[:max_candidates]

    weights = []
    for dist, link in candidates:
        weights.append(max(link.capacity, 1.0) * road_weight(link.highway) / (dist + distance_offset_m))
    total = sum(weights)
    pick = rng.random() * total if total > 0 else 0
    acc = 0.0
    chosen = candidates[-1][1]
    chosen_dist = candidates[-1][0]
    for (dist, link), weight in zip(candidates, weights):
        acc += weight
        if pick <= acc:
            chosen = link
            chosen_dist = dist
            break
    return chosen, {
        "chosen_link": chosen.id,
        "chosen_distance_m": chosen_dist,
        "candidate_count": len(candidates),
        "fallback_nearest": fallback,
        "chosen_highway": chosen.highway,
        "chosen_capacity": chosen.capacity,
        "chosen_permlanes": chosen.permlanes,
    }


def activity_xy(activity: ET.Element) -> tuple[float, float] | None:
    try:
        return (float(activity.get("x", "")), float(activity.get("y", "")))
    except ValueError:
        return None


def xy_key(xy: tuple[float, float]) -> tuple[float, float]:
    return (round(xy[0], 3), round(xy[1], 3))


def persons_from_population(path: pathlib.Path) -> list[ET.Element]:
    persons: list[ET.Element] = []
    with open_text(path, "rt") as handle:
        for event, elem in ET.iterparse(handle, events=("end",)):
            if elem.tag == "person":
                persons.append(ET.fromstring(ET.tostring(elem, encoding="unicode")))
                elem.clear()
    return persons


def plan_sequence(plan: ET.Element) -> list[ET.Element]:
    return [child for child in list(plan) if child.tag in {"activity", "leg"}]


def route_text(link_ids: list[str]) -> str:
    return " ".join(link_ids)


def write_population(path: pathlib.Path, persons: list[ET.Element]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open_text(path, "wt") as handle:
        handle.write('<?xml version="1.0" encoding="utf-8"?>\n')
        handle.write('<!DOCTYPE population SYSTEM "http://www.matsim.org/files/dtd/population_v6.dtd">\n')
        handle.write("<population>\n")
        for person in persons:
            handle.write(f"  {ET.tostring(person, encoding='unicode', short_empty_elements=True)}\n")
        handle.write("</population>\n")


def write_csv(path: pathlib.Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    started = time.time()
    rng = random.Random(args.seed)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    link_qa = load_link_qa(args.link_qa)
    all_links, _all_by_id = parse_network(args.network, link_qa)
    graph_all = build_graph(all_links)
    routing_links, component_summary = largest_strong_links(graph_all, all_links)
    graph = build_graph(routing_links)
    link_by_id = {link.id: link for link in routing_links}
    tree = STRtree([link.geometry for link in routing_links])

    persons = persons_from_population(args.input)
    snap_rows: list[dict[str, Any]] = []
    link_use_counter: Counter[str] = Counter()
    route_requests: list[tuple[Link, Link]] = []
    route_targets: list[tuple[ET.Element, str, str]] = []
    counters: Counter[str] = Counter()

    for person in persons:
        person_id = person.get("id", "")
        person_coord_links: dict[tuple[float, float], str] = {}
        for plan_idx, plan in enumerate(person.findall("plan")):
            for act_idx, activity in enumerate(plan.findall("activity")):
                xy = activity_xy(activity)
                if xy is None:
                    counters["activities_missing_xy"] += 1
                    continue
                key = xy_key(xy)
                if key not in person_coord_links:
                    chosen, meta = choose_link(
                        Point(*xy),
                        tree,
                        routing_links,
                        rng,
                        args.candidate_radius_m,
                        args.max_candidates,
                        args.distance_offset_m,
                    )
                    person_coord_links[key] = chosen.id
                    link_use_counter[chosen.id] += 1
                    snap_rows.append(
                        {
                            "person_id": person_id,
                            "activity_xy_key": f"{key[0]:.3f},{key[1]:.3f}",
                            "x": f"{xy[0]:.3f}",
                            "y": f"{xy[1]:.3f}",
                            "chosen_link": chosen.id,
                            "chosen_distance_m": f'{meta["chosen_distance_m"]:.3f}',
                            "candidate_count": meta["candidate_count"],
                            "fallback_nearest": str(meta["fallback_nearest"]).lower(),
                            "chosen_highway": meta["chosen_highway"],
                            "chosen_capacity": f'{meta["chosen_capacity"]:.3f}',
                            "chosen_permlanes": f'{meta["chosen_permlanes"]:.3f}',
                        }
                    )
                    if meta["fallback_nearest"]:
                        counters["snap_fallback_nearest"] += 1
                activity.set("link", person_coord_links[key])
                counters["activities_updated"] += 1

        for plan in person.findall("plan"):
            seq = plan_sequence(plan)
            for idx, elem in enumerate(seq):
                if elem.tag != "leg":
                    continue
                if elem.get("mode") != "car":
                    continue
                prev_act = seq[idx - 1] if idx > 0 and seq[idx - 1].tag == "activity" else None
                next_act = seq[idx + 1] if idx + 1 < len(seq) and seq[idx + 1].tag == "activity" else None
                if prev_act is None or next_act is None:
                    counters["car_legs_missing_adjacent_activity"] += 1
                    continue
                start_id = prev_act.get("link", "")
                end_id = next_act.get("link", "")
                start_link = link_by_id.get(start_id)
                end_link = link_by_id.get(end_id)
                if start_link is None or end_link is None:
                    counters["car_legs_link_not_in_graph"] += 1
                    continue
                route_requests.append((start_link, end_link))
                route_targets.append((elem, start_id, end_id))
                counters["car_legs_to_route"] += 1

    routes = batch_route_links(graph, link_by_id, route_requests, batch_size=args.route_batch_size)
    unrouted_rows: list[dict[str, Any]] = []
    for route_result, (leg, start_id, end_id) in zip(routes, route_targets):
        for old_route in list(leg.findall("route")):
            leg.remove(old_route)
        if route_result is None:
            counters["car_legs_unrouted"] += 1
            unrouted_rows.append({"start_link": start_id, "end_link": end_id, "reason": "no_path"})
            continue
        link_ids, distance, travel_time = route_result
        route_el = ET.Element(
            "route",
            {
                "type": "links",
                "start_link": start_id,
                "end_link": end_id,
                "trav_time": hms(travel_time),
                "distance": f"{distance:.3f}",
            },
        )
        route_el.text = route_text(link_ids)
        leg.append(route_el)
        counters["car_legs_routed"] += 1

    output_population = args.out_dir / args.output_name
    write_population(output_population, persons)
    write_csv(
        args.out_dir / "activity_link_snapspread_debug.csv",
        snap_rows,
        [
            "person_id",
            "activity_xy_key",
            "x",
            "y",
            "chosen_link",
            "chosen_distance_m",
            "candidate_count",
            "fallback_nearest",
            "chosen_highway",
            "chosen_capacity",
            "chosen_permlanes",
        ],
    )
    top_rows = [
        {"link_id": link_id, "unique_activity_points": count, "capacity": link_by_id.get(link_id).capacity if link_id in link_by_id else ""}
        for link_id, count in link_use_counter.most_common(100)
    ]
    write_csv(args.out_dir / "activity_link_concentration_top100.csv", top_rows, ["link_id", "unique_activity_points", "capacity"])
    if unrouted_rows:
        write_csv(args.out_dir / "snapspread_unrouted_car_legs.csv", unrouted_rows, ["start_link", "end_link", "reason"])

    snap_distances = np.asarray([float(row["chosen_distance_m"]) for row in snap_rows], dtype="float64") if snap_rows else np.asarray([])
    summary = {
        "created_by": "scripts/resnap_fuzhou_mode_choice_activity_links.py",
        "created_at_epoch": time.time(),
        "runtime_seconds": round(time.time() - started, 3),
        "inputs": {"population": str(args.input), "network": str(args.network), "link_qa": str(args.link_qa)},
        "outputs": {
            "population": str(output_population),
            "snap_debug": str(args.out_dir / "activity_link_snapspread_debug.csv"),
            "concentration_top100": str(args.out_dir / "activity_link_concentration_top100.csv"),
        },
        "parameters": {
            "candidate_radius_m": args.candidate_radius_m,
            "max_candidates": args.max_candidates,
            "distance_offset_m": args.distance_offset_m,
            "seed": args.seed,
        },
        "network": component_summary,
        "counts": dict(counters),
        "snap_distance_m": {
            "mean": float(snap_distances.mean()) if len(snap_distances) else None,
            "p50": float(np.percentile(snap_distances, 50)) if len(snap_distances) else None,
            "p95": float(np.percentile(snap_distances, 95)) if len(snap_distances) else None,
            "max": float(snap_distances.max()) if len(snap_distances) else None,
        },
        "top_link_unique_activity_points_max": int(max(link_use_counter.values())) if link_use_counter else 0,
        "unrouted_share": counters["car_legs_unrouted"] / counters["car_legs_to_route"] if counters["car_legs_to_route"] else 0.0,
    }
    (args.out_dir / "activity_link_snapspread_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
