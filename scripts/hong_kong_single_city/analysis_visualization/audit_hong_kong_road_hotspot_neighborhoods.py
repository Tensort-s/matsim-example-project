#!/usr/bin/env python3
"""Audit the road links that cumulatively account for a target delay share.

The audit joins runtime delay to the physical network, calibrated link
attributes, exact parallel links, local storage proxies, and observed
vehicle transitions. It is read-only and requires a new output directory.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from dataclasses import dataclass
import gzip
import json
import math
from pathlib import Path
from typing import Iterable
import xml.etree.ElementTree as ET

from audit_hong_kong_road_network_runtime import classify_vehicle, iter_events


@dataclass(frozen=True)
class NetworkLink:
    link_id: str
    from_node: str
    to_node: str
    length_m: float
    freespeed_m_s: float
    capacity_veh_h: float
    lanes: float
    modes: frozenset[str]

    def storage_proxy(self, storage_factor: float, cell_size_m: float) -> float:
        return self.length_m * self.lanes * storage_factor / cell_size_m


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--hybrid-capacity", type=Path, required=True)
    parser.add_argument("--route-directions", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--delay-share", type=float, default=0.5)
    parser.add_argument("--storage-factor", type=float, default=0.1)
    parser.add_argument("--effective-cell-size-m", type=float, default=7.5)
    return parser.parse_args()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def read_network(path: Path) -> dict[str, NetworkLink]:
    links: dict[str, NetworkLink] = {}
    opener = gzip.open if path.suffix == ".gz" else Path.open
    with opener(path, "rb") as stream:
        for _event, element in ET.iterparse(stream, events=("end",)):
            if local_name(element.tag) != "link":
                continue
            attributes = element.attrib
            modes = frozenset(filter(None, attributes.get("modes", "").split(",")))
            links[attributes["id"]] = NetworkLink(
                link_id=attributes["id"],
                from_node=attributes["from"],
                to_node=attributes["to"],
                length_m=float(attributes["length"]),
                freespeed_m_s=float(attributes["freespeed"]),
                capacity_veh_h=float(attributes["capacity"]),
                lanes=float(attributes.get("permlanes", "1")),
                modes=modes,
            )
            element.clear()
    return links


def read_csv_by_key(path: Path, key: str) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return {row[key]: row for row in csv.DictReader(stream)}


def select_hotspots(
    rows: Iterable[dict[str, str]], delay_share: float
) -> tuple[list[dict[str, str]], float]:
    if not 0 < delay_share <= 1:
        raise ValueError("delay_share must be in (0, 1]")
    ordered = sorted(rows, key=lambda row: float(row["total_delay_s"]), reverse=True)
    total = sum(float(row["total_delay_s"]) for row in ordered)
    selected: list[dict[str, str]] = []
    cumulative = 0.0
    for row in ordered:
        selected.append(row)
        cumulative += float(row["total_delay_s"])
        if cumulative >= total * delay_share:
            break
    return selected, cumulative / total if total else 0.0


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

    with args.runtime.open("r", encoding="utf-8-sig", newline="") as stream:
        runtime_rows = list(csv.DictReader(stream))
    runtime = {row["link_id"]: row for row in runtime_rows}
    hotspots, actual_share = select_hotspots(runtime_rows, args.delay_share)
    hotspot_ids = {row["link_id"] for row in hotspots}

    links = read_network(args.network)
    road_links = {key: value for key, value in links.items() if "car" in value.modes}
    incoming: dict[str, list[NetworkLink]] = defaultdict(list)
    outgoing: dict[str, list[NetworkLink]] = defaultdict(list)
    parallel: dict[tuple[str, str], list[NetworkLink]] = defaultdict(list)
    for link in road_links.values():
        incoming[link.to_node].append(link)
        outgoing[link.from_node].append(link)
        parallel[(link.from_node, link.to_node)].append(link)

    hybrid = read_csv_by_key(args.hybrid_capacity, "link_id")
    route_rows: dict[str, dict[str, str]] = {}
    with args.route_directions.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            route_rows[f"road_{row['route_id']}_0_{row['direction']}"] = row

    transition_counts: Counter[tuple[str, str, str]] = Counter()
    previous_road: dict[str, str | None] = {}
    vehicle_classes: dict[str, str] = {}
    for event in iter_events(args.events):
        event_type = event.get("type", "")
        vehicle = event.get("vehicle", "")
        if event_type == "vehicle enters traffic":
            vehicle_classes[vehicle] = classify_vehicle(vehicle, event.get("person", ""))
            previous_road[vehicle] = None
        elif event_type == "left link":
            link_id = event.get("link", "")
            if vehicle not in previous_road:
                continue
            if link_id not in road_links:
                previous_road[vehicle] = None
                continue
            previous = previous_road[vehicle]
            if previous is not None and (previous in hotspot_ids or link_id in hotspot_ids):
                transition_counts[(previous, link_id, vehicle_classes.get(vehicle, "unknown"))] += 1
            previous_road[vehicle] = link_id
        elif event_type == "vehicle leaves traffic":
            previous_road.pop(vehicle, None)
            vehicle_classes.pop(vehicle, None)

    transition_rows = [
        {
            "from_link": first,
            "to_link": second,
            "vehicle_class": vehicle_class,
            "count": count,
            "from_is_hotspot": first in hotspot_ids,
            "to_is_hotspot": second in hotspot_ids,
        }
        for (first, second, vehicle_class), count in transition_counts.most_common()
    ]
    write_csv(args.output_dir / "hotspot_observed_transitions.csv", transition_rows)

    outgoing_transitions: Counter[tuple[str, str]] = Counter()
    incoming_transitions: Counter[tuple[str, str]] = Counter()
    for (first, second, _vehicle_class), count in transition_counts.items():
        if first in hotspot_ids:
            outgoing_transitions[(first, second)] += count
        if second in hotspot_ids:
            incoming_transitions[(second, first)] += count

    hotspot_output: list[dict[str, object]] = []
    neighbor_output: list[dict[str, object]] = []
    parallel_output: list[dict[str, object]] = []
    short_output: list[dict[str, object]] = []
    issue_counts: Counter[str] = Counter()

    for rank, runtime_row in enumerate(hotspots, start=1):
        link_id = runtime_row["link_id"]
        link = road_links[link_id]
        direct_parallel = sorted(parallel[(link.from_node, link.to_node)], key=lambda x: x.link_id)
        downstream = sorted(outgoing.get(link.to_node, []), key=lambda x: x.link_id)
        upstream = sorted(incoming.get(link.from_node, []), key=lambda x: x.link_id)
        out_counts = Counter(
            {second: count for (first, second), count in outgoing_transitions.items() if first == link_id}
        )
        in_counts = Counter(
            {first: count for (second, first), count in incoming_transitions.items() if second == link_id}
        )
        out_total = sum(out_counts.values())
        in_total = sum(in_counts.values())
        dominant_out, dominant_out_count = out_counts.most_common(1)[0] if out_counts else ("", 0)
        dominant_in, dominant_in_count = in_counts.most_common(1)[0] if in_counts else ("", 0)
        hybrid_row = hybrid.get(link_id, {})
        route_row = route_rows.get(link_id, {})

        issues: list[str] = []
        if len(direct_parallel) > 1:
            issues.append("exact_parallel_links")
        if link.length_m < 10:
            issues.append("hotspot_length_lt_10m")
        if any(item.length_m < 10 for item in downstream):
            issues.append("downstream_length_lt_10m")
        if any(
            item.storage_proxy(args.storage_factor, args.effective_cell_size_m) < 1
            for item in downstream
        ):
            issues.append("downstream_storage_proxy_lt_1_vehicle")
        if out_total and dominant_out_count / out_total >= 0.9:
            issues.append("dominant_downstream_share_ge_0_9")
        if route_row.get("lane_changed_from_formal") == "True" or hybrid_row.get(
            "lane_changed_from_formal"
        ) == "True":
            issues.append("hybrid_lane_changed")
        issue_counts.update(issues)

        hotspot_output.append(
            {
                "rank": rank,
                "link_id": link_id,
                "street_ename": route_row.get("street_ename", ""),
                "from_node": link.from_node,
                "to_node": link.to_node,
                "length_m": link.length_m,
                "freespeed_km_h": link.freespeed_m_s * 3.6,
                "capacity_veh_h": link.capacity_veh_h,
                "lanes": link.lanes,
                "storage_proxy_vehicles": round(
                    link.storage_proxy(args.storage_factor, args.effective_cell_size_m), 6
                ),
                "traversals": runtime_row["traversals"],
                "mean_travel_time_ratio": runtime_row["mean_travel_time_ratio"],
                "delay_vehicle_hours": round(float(runtime_row["total_delay_s"]) / 3600, 6),
                "stuck_events": runtime_row["road_vehicle_stuck_events"],
                "parallel_link_count": len(direct_parallel),
                "parallel_link_ids": "|".join(item.link_id for item in direct_parallel),
                "upstream_link_count": len(upstream),
                "downstream_link_count": len(downstream),
                "observed_in_transitions": in_total,
                "dominant_upstream_link": dominant_in,
                "dominant_upstream_share": round(dominant_in_count / in_total, 6) if in_total else "",
                "observed_out_transitions": out_total,
                "dominant_downstream_link": dominant_out,
                "dominant_downstream_share": round(dominant_out_count / out_total, 6) if out_total else "",
                "dominant_downstream_length_m": (
                    road_links[dominant_out].length_m if dominant_out in road_links else ""
                ),
                "dominant_downstream_storage_proxy": (
                    round(
                        road_links[dominant_out].storage_proxy(
                            args.storage_factor, args.effective_cell_size_m
                        ),
                        6,
                    )
                    if dominant_out in road_links
                    else ""
                ),
                "final_road_type": hybrid_row.get("final_road_type", ""),
                "hybrid_capacity_source": hybrid_row.get(
                    "hybrid_capacity_controlling_source", ""
                ),
                "final_lane_source": route_row.get("final_lane_source", ""),
                "final_lane_confidence": route_row.get("final_lane_confidence", ""),
                "issues": "|".join(issues),
            }
        )

        for relation, candidates in (("upstream", upstream), ("downstream", downstream)):
            for item in candidates:
                neighbor_runtime = runtime.get(item.link_id, {})
                count = (
                    in_counts[item.link_id] if relation == "upstream" else out_counts[item.link_id]
                )
                neighbor_output.append(
                    {
                        "hotspot_rank": rank,
                        "hotspot_link": link_id,
                        "relation": relation,
                        "link_id": item.link_id,
                        "street_ename": route_rows.get(item.link_id, {}).get(
                            "street_ename", ""
                        ),
                        "from_node": item.from_node,
                        "to_node": item.to_node,
                        "from_node_in_degree": len(incoming.get(item.from_node, [])),
                        "from_node_out_degree": len(outgoing.get(item.from_node, [])),
                        "to_node_in_degree": len(incoming.get(item.to_node, [])),
                        "to_node_out_degree": len(outgoing.get(item.to_node, [])),
                        "length_m": item.length_m,
                        "capacity_veh_h": item.capacity_veh_h,
                        "lanes": item.lanes,
                        "storage_proxy_vehicles": round(
                            item.storage_proxy(args.storage_factor, args.effective_cell_size_m), 6
                        ),
                        "observed_transitions": count,
                        "runtime_traversals": neighbor_runtime.get("traversals", "0"),
                        "runtime_mean_ratio": neighbor_runtime.get("mean_travel_time_ratio", ""),
                        "runtime_delay_s": neighbor_runtime.get("total_delay_s", ""),
                    }
                )
                if item.length_m < 10:
                    short_output.append(neighbor_output[-1].copy())

        if len(direct_parallel) > 1:
            group_capacity = sum(item.capacity_veh_h for item in direct_parallel)
            group_lanes = sum(item.lanes for item in direct_parallel)
            group_traversals = sum(int(runtime.get(item.link_id, {}).get("traversals", "0")) for item in direct_parallel)
            for item in direct_parallel:
                item_runtime = runtime.get(item.link_id, {})
                item_traversals = int(item_runtime.get("traversals", "0"))
                parallel_output.append(
                    {
                        "hotspot_rank": rank,
                        "hotspot_link": link_id,
                        "parallel_link": item.link_id,
                        "length_m": item.length_m,
                        "freespeed_km_h": item.freespeed_m_s * 3.6,
                        "capacity_veh_h": item.capacity_veh_h,
                        "lanes": item.lanes,
                        "group_capacity_veh_h": group_capacity,
                        "group_lanes": group_lanes,
                        "runtime_traversals": item_traversals,
                        "runtime_share": (
                            round(item_traversals / group_traversals, 6)
                            if group_traversals
                            else ""
                        ),
                        "runtime_mean_ratio": item_runtime.get("mean_travel_time_ratio", ""),
                        "street_ename": route_rows.get(item.link_id, {}).get("street_ename", ""),
                        "final_lane_source": route_rows.get(item.link_id, {}).get(
                            "final_lane_source", ""
                        ),
                    }
                )

    write_csv(args.output_dir / "hotspot_links.csv", hotspot_output)
    write_csv(args.output_dir / "hotspot_neighbors.csv", neighbor_output)
    write_csv(args.output_dir / "hotspot_parallel_links.csv", parallel_output)
    write_csv(args.output_dir / "hotspot_short_connectors.csv", short_output)
    summary = {
        "status": "audited",
        "delay_share_target": args.delay_share,
        "delay_share_actual": actual_share,
        "hotspot_link_count": len(hotspots),
        "issue_counts": dict(issue_counts),
        "storage_proxy": {
            "formula": "length_m * lanes * storageCapacityFactor / effectiveCellSize_m",
            "storage_capacity_factor": args.storage_factor,
            "effective_cell_size_m": args.effective_cell_size_m,
            "warning": "diagnostic proxy; confirm MATSim queue implementation before adoption",
        },
        "outputs": {
            "hotspot_links": "hotspot_links.csv",
            "hotspot_neighbors": "hotspot_neighbors.csv",
            "hotspot_observed_transitions": "hotspot_observed_transitions.csv",
            "hotspot_parallel_links": "hotspot_parallel_links.csv",
            "hotspot_short_connectors": "hotspot_short_connectors.csv",
        },
    }
    (args.output_dir / "hotspot_neighborhood_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
