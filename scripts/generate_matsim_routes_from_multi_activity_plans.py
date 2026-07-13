"""Route coordinate-based multi-activity MATSim plans.

The input population contains arbitrary activity chains such as
home-school-work-shop-home. This script snaps every activity coordinate to the
nearest car link, routes every consecutive activity pair by free-flow travel
time, and writes a MATSim population_v6 file with link routes.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import pathlib
import time
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from typing import Iterable
from xml.sax.saxutils import escape

import numpy as np
from shapely.geometry import Point

from generate_matsim_routes_from_agents import (
    CITY_KEY,
    DEFAULT_ROADS,
    TARGET_CRS,
    Link,
    batch_route_links,
    build_graph,
    build_network,
    hms,
    intermediate_route_text,
    nearest_link,
    prepare_snapper,
    select_routing_links,
    write_network_xml,
)


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_PLANS = (
    PROJECT_ROOT
    / "data"
    / "matsim_agents"
    / f"{CITY_KEY}_multi_activity"
    / "plans_multi_activity.xml.gz"
)
DEFAULT_OUT_DIR = PROJECT_ROOT / "data" / "matsim_routes" / f"{CITY_KEY}_multi_activity"


@dataclass
class Attribute:
    name: str
    klass: str
    value: str


@dataclass
class Activity:
    act_type: str
    x: float
    y: float
    end_time: str | None
    link_id: str | None = None
    snap_distance: float | None = None


@dataclass
class Leg:
    mode: str
    routed: bool = False
    route_links: list[str] | None = None
    distance: float = math.nan
    travel_time: float = math.nan
    start_link: str | None = None
    end_link: str | None = None


@dataclass
class PersonPlan:
    person_id: str
    attributes: list[Attribute]
    activities: list[Activity]
    legs: list[Leg]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Route multi-activity MATSim plans.")
    parser.add_argument("--plans", default=str(DEFAULT_PLANS), help="Coordinate-based plans_multi_activity.xml.gz.")
    parser.add_argument("--roads", default=str(DEFAULT_ROADS), help="OSM roads GeoJSON.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output route directory.")
    parser.add_argument("--crs", default=TARGET_CRS, help="Projected CRS used by MATSim network/plans.")
    parser.add_argument("--snap-component", choices=["largest_strong", "all"], default="largest_strong")
    parser.add_argument("--max-unrouted-share", type=float, default=0.05)
    parser.add_argument("--sample-route-checks", type=int, default=100)
    return parser.parse_args()


def ensure_exists(path: pathlib.Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")


def xml_attr(value: object) -> str:
    return escape(str(value), {'"': "&quot;"})


def xml_text(value: object) -> str:
    return escape(str(value))


def open_xml_text(path: pathlib.Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("rt", encoding="utf-8")


def parse_population(path: pathlib.Path) -> list[PersonPlan]:
    persons: list[PersonPlan] = []
    with open_xml_text(path) as handle:
        for _event, elem in ET.iterparse(handle, events=("end",)):
            if elem.tag != "person":
                continue
            person_id = elem.attrib["id"]
            attributes: list[Attribute] = []
            attributes_elem = elem.find("attributes")
            if attributes_elem is not None:
                for attr in attributes_elem.findall("attribute"):
                    attributes.append(
                        Attribute(
                            name=attr.attrib.get("name", ""),
                            klass=attr.attrib.get("class", "java.lang.String"),
                            value=attr.text or "",
                        )
                    )

            plan = elem.find("plan")
            if plan is None:
                raise ValueError(f"person {person_id} has no selected plan")
            activities: list[Activity] = []
            legs: list[Leg] = []
            for child in list(plan):
                if child.tag == "activity":
                    activities.append(
                        Activity(
                            act_type=child.attrib["type"],
                            x=float(child.attrib["x"]),
                            y=float(child.attrib["y"]),
                            end_time=child.attrib.get("end_time"),
                        )
                    )
                elif child.tag == "leg":
                    legs.append(Leg(mode=child.attrib.get("mode", "car")))

            if len(activities) != len(legs) + 1:
                raise ValueError(
                    f"person {person_id} has inconsistent activity/leg sequence: "
                    f"{len(activities)} activities, {len(legs)} legs"
                )
            persons.append(PersonPlan(person_id=person_id, attributes=attributes, activities=activities, legs=legs))
            elem.clear()
    return persons


def write_routed_population(path: pathlib.Path, persons: Iterable[PersonPlan]) -> None:
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as handle:
        handle.write('<?xml version="1.0" encoding="utf-8"?>\n')
        handle.write('<!DOCTYPE population SYSTEM "http://www.matsim.org/files/dtd/population_v6.dtd">\n')
        handle.write("<population>\n")
        for person in persons:
            handle.write(f'  <person id="{xml_attr(person.person_id)}">\n')
            if person.attributes:
                handle.write("    <attributes>\n")
                for attr in person.attributes:
                    handle.write(
                        f'      <attribute name="{xml_attr(attr.name)}" class="{xml_attr(attr.klass)}">'
                        f"{xml_text(attr.value)}</attribute>\n"
                    )
                handle.write("    </attributes>\n")
            handle.write('    <plan selected="yes">\n')
            for idx, activity in enumerate(person.activities):
                end_attr = f' end_time="{xml_attr(activity.end_time)}"' if activity.end_time is not None else ""
                link_attr = f' link="{xml_attr(activity.link_id)}"' if activity.link_id else ""
                handle.write(
                    f'      <activity type="{xml_attr(activity.act_type)}" '
                    f'x="{activity.x:.3f}" y="{activity.y:.3f}"{link_attr}{end_attr} />\n'
                )
                if idx < len(person.legs):
                    leg = person.legs[idx]
                    handle.write(f'      <leg mode="{xml_attr(leg.mode)}">\n')
                    if leg.routed and leg.route_links:
                        handle.write(
                            f'        <route type="links" start_link="{xml_attr(leg.start_link)}" '
                            f'end_link="{xml_attr(leg.end_link)}" trav_time="{xml_attr(hms(leg.travel_time))}" '
                            f'distance="{leg.distance:.3f}">{xml_text(intermediate_route_text(leg.route_links))}</route>\n'
                        )
                    handle.write("      </leg>\n")
            handle.write("    </plan>\n")
            handle.write("  </person>\n")
        handle.write("</population>\n")


def parse_hms(value: str) -> int:
    h, m, s = [int(part) for part in value.split(":")]
    return h * 3600 + m * 60 + s


def validate_time_order(persons: Iterable[PersonPlan]) -> tuple[int, list[str]]:
    bad = 0
    examples: list[str] = []
    for person in persons:
        times = [parse_hms(a.end_time) for a in person.activities if a.end_time is not None]
        if any(b <= a for a, b in zip(times, times[1:])):
            bad += 1
            if len(examples) < 10:
                examples.append(person.person_id)
    return bad, examples


def main() -> None:
    args = parse_args()
    started = time.time()
    plans_path = pathlib.Path(args.plans)
    roads_path = pathlib.Path(args.roads)
    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ensure_exists(plans_path, "plans_multi_activity.xml.gz")
    ensure_exists(roads_path, "roads GeoJSON")

    print("Building MATSim car network from OSM road GeoJSON...")
    nodes, links, network_summary = build_network(roads_path, args.crs)
    graph, link_by_id = build_graph(links)
    snap_links, component_summary = select_routing_links(graph, links, args.snap_component)
    graph, link_by_id = build_graph(snap_links)

    network_path = out_dir / "network.xml.gz"
    output_node_ids = {link.from_node for link in snap_links} | {link.to_node for link in snap_links}
    output_nodes = {node_id: coord for node_id, coord in nodes.items() if node_id in output_node_ids}
    write_network_xml(network_path, output_nodes, snap_links)

    print("Parsing multi-activity plans...")
    persons = parse_population(plans_path)
    print(f"Parsed persons={len(persons)}")

    tree, _geometries, snap_links = prepare_snapper(snap_links)
    route_requests: list[tuple[Link, Link]] = []
    request_meta: list[tuple[PersonPlan, int]] = []
    activity_counter: Counter[str] = Counter()
    leg_type_counter: Counter[str] = Counter()

    print("Snapping activities to routing links...")
    activity_count = 0
    for person in persons:
        for activity in person.activities:
            link, snap_distance = nearest_link(Point(activity.x, activity.y), tree, snap_links)
            activity.link_id = link.id
            activity.snap_distance = snap_distance
            activity_counter[activity.act_type] += 1
            activity_count += 1
        for leg_idx, leg in enumerate(person.legs):
            start_activity = person.activities[leg_idx]
            end_activity = person.activities[leg_idx + 1]
            start_link = link_by_id[str(start_activity.link_id)]
            end_link = link_by_id[str(end_activity.link_id)]
            leg.start_link = start_link.id
            leg.end_link = end_link.id
            route_requests.append((start_link, end_link))
            request_meta.append((person, leg_idx))
            leg_type_counter[f"{start_activity.act_type}->{end_activity.act_type}"] += 1

    print(f"Snapped activities={activity_count}; routing legs={len(route_requests)}")
    print("Batch routing all legs...")
    routes = batch_route_links(graph, link_by_id, route_requests)

    unrouted_leg_rows: list[dict] = []
    for route, (person, leg_idx) in zip(routes, request_meta):
        leg = person.legs[leg_idx]
        start_activity = person.activities[leg_idx]
        end_activity = person.activities[leg_idx + 1]
        if route is None:
            unrouted_leg_rows.append(
                {
                    "person_id": person.person_id,
                    "leg_index": leg_idx,
                    "from_activity": start_activity.act_type,
                    "to_activity": end_activity.act_type,
                    "start_link": leg.start_link,
                    "end_link": leg.end_link,
                    "from_snap_distance": start_activity.snap_distance,
                    "to_snap_distance": end_activity.snap_distance,
                    "reason": "no_directed_path",
                }
            )
            continue
        link_ids, distance, travel_time = route
        leg.routed = True
        leg.route_links = link_ids
        leg.distance = distance
        leg.travel_time = travel_time

    routed_plans_path = out_dir / "routed_multi_activity_plans.xml.gz"
    write_routed_population(routed_plans_path, persons)

    route_debug_path = out_dir / "multi_activity_route_debug.csv"
    with route_debug_path.open("w", encoding="utf-8", newline="") as handle:
        fields = [
            "person_id",
            "leg_index",
            "from_activity",
            "to_activity",
            "from_link",
            "to_link",
            "from_snap_distance",
            "to_snap_distance",
            "routed",
            "distance",
            "travel_time_seconds",
            "route_link_count",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for person in persons:
            for leg_idx, leg in enumerate(person.legs):
                start_activity = person.activities[leg_idx]
                end_activity = person.activities[leg_idx + 1]
                writer.writerow(
                    {
                        "person_id": person.person_id,
                        "leg_index": leg_idx,
                        "from_activity": start_activity.act_type,
                        "to_activity": end_activity.act_type,
                        "from_link": leg.start_link,
                        "to_link": leg.end_link,
                        "from_snap_distance": start_activity.snap_distance,
                        "to_snap_distance": end_activity.snap_distance,
                        "routed": leg.routed,
                        "distance": "" if not leg.routed else f"{leg.distance:.3f}",
                        "travel_time_seconds": "" if not leg.routed else f"{leg.travel_time:.3f}",
                        "route_link_count": 0 if not leg.route_links else len(leg.route_links),
                    }
                )

    unrouted_legs_path = out_dir / "unrouted_legs.csv"
    with unrouted_legs_path.open("w", encoding="utf-8", newline="") as handle:
        fields = [
            "person_id",
            "leg_index",
            "from_activity",
            "to_activity",
            "start_link",
            "end_link",
            "from_snap_distance",
            "to_snap_distance",
            "reason",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(unrouted_leg_rows)

    unrouted_person_ids = sorted({row["person_id"] for row in unrouted_leg_rows})
    unrouted_persons_path = out_dir / "unrouted_persons.csv"
    with unrouted_persons_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["person_id", "unrouted_leg_count"])
        writer.writeheader()
        per_person = Counter(row["person_id"] for row in unrouted_leg_rows)
        for person_id in unrouted_person_ids:
            writer.writerow({"person_id": person_id, "unrouted_leg_count": per_person[person_id]})

    total_legs = len(route_requests)
    routed_legs = sum(1 for route in routes if route is not None)
    unrouted_legs = total_legs - routed_legs
    unrouted_share = unrouted_legs / total_legs if total_legs else 1.0
    snap_distances = np.asarray(
        [a.snap_distance for person in persons for a in person.activities if a.snap_distance is not None],
        dtype="float64",
    )
    routed_distances = np.asarray([leg.distance for person in persons for leg in person.legs if leg.routed], dtype="float64")
    routed_times = np.asarray([leg.travel_time for person in persons for leg in person.legs if leg.routed], dtype="float64")
    bad_time_order, bad_time_examples = validate_time_order(persons)

    sample_checked = 0
    sample_passed = 0
    for person in persons:
        for leg in person.legs:
            if sample_checked >= args.sample_route_checks:
                break
            if not leg.routed or not leg.route_links:
                continue
            sample_checked += 1
            if leg.route_links[0] == leg.start_link and leg.route_links[-1] == leg.end_link:
                sample_passed += 1
        if sample_checked >= args.sample_route_checks:
            break

    summary = {
        "city_key": f"{CITY_KEY}_multi_activity",
        "created_at_epoch": time.time(),
        "runtime_seconds": round(time.time() - started, 3),
        "inputs": {
            "plans_xml_gz": str(plans_path),
            "roads_geojson": str(roads_path),
        },
        "outputs": {
            "network_xml_gz": str(network_path),
            "routed_multi_activity_plans_xml_gz": str(routed_plans_path),
            "multi_activity_route_debug_csv": str(route_debug_path),
            "unrouted_legs_csv": str(unrouted_legs_path),
            "unrouted_persons_csv": str(unrouted_persons_path),
        },
        "crs": args.crs,
        "network": {**network_summary, **component_summary},
        "output_network": {
            "node_count": int(len(output_nodes)),
            "link_count": int(len(snap_links)),
        },
        "population": {
            "person_count": int(len(persons)),
            "activity_count": int(activity_count),
            "leg_count": int(total_legs),
            "activity_types": dict(activity_counter),
            "leg_types": dict(leg_type_counter),
        },
        "routing": {
            "routed_legs": int(routed_legs),
            "unrouted_legs": int(unrouted_legs),
            "unrouted_persons": int(len(unrouted_person_ids)),
            "routed_success_rate": float(1.0 - unrouted_share),
            "unrouted_share": float(unrouted_share),
            "snap_success_rate": 1.0,
            "snap_distance_m": {
                "mean": float(snap_distances.mean()) if len(snap_distances) else None,
                "p95": float(np.percentile(snap_distances, 95)) if len(snap_distances) else None,
                "max": float(snap_distances.max()) if len(snap_distances) else None,
            },
            "route_distance_m": {
                "mean": float(routed_distances.mean()) if len(routed_distances) else None,
                "p95": float(np.percentile(routed_distances, 95)) if len(routed_distances) else None,
                "max": float(routed_distances.max()) if len(routed_distances) else None,
            },
            "route_travel_time_seconds": {
                "mean": float(routed_times.mean()) if len(routed_times) else None,
                "p95": float(np.percentile(routed_times, 95)) if len(routed_times) else None,
                "max": float(routed_times.max()) if len(routed_times) else None,
            },
            "sample_route_sequence_checks": {
                "checked": int(sample_checked),
                "passed": int(sample_passed),
            },
        },
        "validation": {
            "all_link_lengths_positive": all(link.length > 0 for link in snap_links),
            "all_link_speeds_positive": all(link.freespeed > 0 for link in snap_links),
            "all_link_capacities_positive": all(link.capacity > 0 for link in snap_links),
            "bad_time_order_persons": int(bad_time_order),
            "bad_time_order_examples": bad_time_examples,
            "unrouted_share_threshold": args.max_unrouted_share,
            "passed_unrouted_threshold": bool(unrouted_share <= args.max_unrouted_share),
        },
    }

    network_summary_path = out_dir / "network_summary.json"
    network_summary_path.write_text(
        json.dumps(
            {
                "network": {**network_summary, **component_summary},
                "output_network": {"node_count": int(len(output_nodes)), "link_count": int(len(snap_links))},
                "crs": args.crs,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    summary["outputs"]["network_summary_json"] = str(network_summary_path)

    summary_path = out_dir / "multi_activity_route_generation_summary.json"
    summary["outputs"]["multi_activity_route_generation_summary_json"] = str(summary_path)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if unrouted_share > args.max_unrouted_share:
        raise SystemExit(
            f"Unrouted share {unrouted_share:.2%} exceeds threshold {args.max_unrouted_share:.2%}. "
            f"See {unrouted_legs_path}"
        )
    if bad_time_order:
        raise SystemExit(f"Found {bad_time_order} persons with non-increasing activity end times.")


if __name__ == "__main__":
    main()
