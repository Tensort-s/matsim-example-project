"""Build a deterministic Hong Kong MATSim Taxi/DVRP fleet.

The optional *derived link-level* origin proxy is a UTF-8 CSV containing a link identifier column
(`link_id`, `start_link_id`, or `origin_link_id`) and, optionally, one of
`weight`, `origin_weight`, `origin_count`, `count`, or `trips`. Repeated link
rows are aggregated. Raw TCS26 zone OD tables are not accepted directly: they
must first be mapped to network links. Alternatively, ``--taxi-origin-plans``
streams a frozen MATSim selected/experienced plans file and aggregates the
activity link immediately preceding every Taxi leg.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import hashlib
import io
import json
import math
import random
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence
from xml.sax.saxutils import quoteattr

try:
    import zstandard
except ImportError:  # pragma: no cover - exercised only in minimal runtimes
    zstandard = None


FULL_FLEET_SIZE = 15_500
TAXI_TYPE_TARGETS = (
    ("urban", 13_083),
    ("nt", 2_353),
    ("lantau", 64),
)
SHIFT_TARGETS = (
    ("midnight", 3_100, 0.0, 0.0),
    ("00_02", 1_550, 0.0, 2 * 3600.0),
    ("02_04", 2_325, 2 * 3600.0, 4 * 3600.0),
    ("04_06", 3_875, 4 * 3600.0, 6 * 3600.0),
    ("06_08", 3_100, 6 * 3600.0, 8 * 3600.0),
    ("08_10", 1_550, 8 * 3600.0, 10 * 3600.0),
)
SERVICE_SECONDS = 18 * 3600.0
PROXY_SHARE = 0.70
VEHICLE_CAPACITY = 4
ASSUMED_PCU = 1.0

LINK_ID_COLUMNS = ("link_id", "start_link_id", "origin_link_id")
WEIGHT_COLUMNS = ("weight", "origin_weight", "origin_count", "count", "trips")


@dataclass(frozen=True)
class RoadLink:
    link_id: str
    from_node: str
    to_node: str
    length_m: float
    lanes: float
    x: float
    y: float
    modes: frozenset[str]
    attributes: Mapping[str, str] = field(compare=False)

    @property
    def lane_km(self) -> float:
        return self.length_m * self.lanes / 1000.0


@dataclass(frozen=True)
class FleetVehicle:
    vehicle_id: str
    taxi_type: str
    start_link: RoadLink
    service_begin_s: float
    service_end_s: float
    sampling_source: str
    proxy_weight: float


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


@contextmanager
def open_binary(path: Path):
    if path.suffix.lower() == ".gz":
        with gzip.open(path, "rb") as handle:
            yield handle
    elif path.suffix.lower() == ".zst":
        if zstandard is not None:
            with path.open("rb") as raw:
                with zstandard.ZstdDecompressor().stream_reader(raw) as handle:
                    yield handle
        else:
            executable = shutil.which("zstdcat")
            if executable is None:
                raise RuntimeError(
                    "Reading .zst plans requires the Python zstandard package or zstdcat"
                )
            process = subprocess.Popen(
                [executable, str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            assert process.stdout is not None
            try:
                yield process.stdout
            finally:
                process.stdout.close()
                stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
                return_code = process.wait()
                if process.stderr:
                    process.stderr.close()
                if return_code != 0:
                    raise RuntimeError(
                        f"zstdcat failed for {path} with exit {return_code}: {stderr.strip()}"
                    )
    else:
        with path.open("rb") as handle:
            yield handle


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def split_modes(raw: str) -> frozenset[str]:
    return frozenset(value for value in re.split(r"[,;\s]+", raw.strip()) if value)


def is_signal_internal(link_id: str, attributes: Mapping[str, str]) -> bool:
    evidence = " ".join(
        [link_id, *[f"{key}={value}" for key, value in attributes.items()]]
    ).lower()
    signal_token = "signal" in evidence or "traffic_light" in evidence or "trafficlight" in evidence
    internal_token = "internal" in evidence or "connector" in evidence
    return signal_token and internal_token


def parse_car_network(path: Path) -> tuple[dict[str, tuple[float, float]], list[RoadLink], dict[str, int]]:
    nodes: dict[str, tuple[float, float]] = {}
    car_links: list[RoadLink] = []
    counters: Counter[str] = Counter()
    current_link: dict | None = None

    with open_binary(path) as handle:
        for event, elem in ET.iterparse(handle, events=("start", "end")):
            tag = local_name(elem.tag)
            if event == "start" and tag == "node":
                node_id = elem.get("id")
                if node_id is not None:
                    try:
                        nodes[node_id] = (float(elem.get("x", "nan")), float(elem.get("y", "nan")))
                    except ValueError:
                        counters["invalid_nodes"] += 1
            elif event == "start" and tag == "link":
                current_link = {"xml": dict(elem.attrib), "attributes": {}}
            elif event == "end" and tag == "attribute" and current_link is not None:
                name = elem.get("name")
                if name:
                    current_link["attributes"][name] = (elem.text or "").strip()
                elem.clear()
            elif event == "end" and tag == "link" and current_link is not None:
                counters["network_links"] += 1
                xml = current_link["xml"]
                attrs = current_link["attributes"]
                link_id = xml.get("id", "")
                modes = split_modes(xml.get("modes", attrs.get("modes", "")))
                if "car" not in modes:
                    counters["non_car_links_excluded"] += 1
                elif is_signal_internal(link_id, {**xml, **attrs}):
                    counters["signal_internal_links_excluded"] += 1
                else:
                    try:
                        from_node = xml["from"]
                        to_node = xml["to"]
                        length = float(xml.get("length", "nan"))
                        lanes = float(xml.get("permlanes", xml.get("lanes", "1")))
                        from_xy = nodes[from_node]
                        to_xy = nodes[to_node]
                    except (KeyError, ValueError):
                        counters["invalid_car_links_excluded"] += 1
                    else:
                        if not (math.isfinite(length) and length > 0 and math.isfinite(lanes) and lanes > 0):
                            counters["invalid_car_links_excluded"] += 1
                        else:
                            car_links.append(
                                RoadLink(
                                    link_id=link_id,
                                    from_node=from_node,
                                    to_node=to_node,
                                    length_m=length,
                                    lanes=lanes,
                                    x=(from_xy[0] + to_xy[0]) / 2,
                                    y=(from_xy[1] + to_xy[1]) / 2,
                                    modes=modes,
                                    attributes=attrs,
                                )
                            )
                current_link = None
                elem.clear()
            elif event == "end" and tag == "node":
                elem.clear()

    counters["network_nodes"] = len(nodes)
    counters["candidate_car_links"] = len(car_links)
    if not nodes:
        raise ValueError(f"No nodes found in network: {path}")
    if not car_links:
        raise ValueError(f"No eligible car links found in network: {path}")
    return nodes, car_links, dict(counters)


def largest_strong_component(links: Sequence[RoadLink]) -> tuple[set[str], list[RoadLink], dict[str, int]]:
    outgoing: dict[str, list[str]] = defaultdict(list)
    incoming: dict[str, list[str]] = defaultdict(list)
    graph_nodes: set[str] = set()
    for link in links:
        outgoing[link.from_node].append(link.to_node)
        incoming[link.to_node].append(link.from_node)
        graph_nodes.update((link.from_node, link.to_node))
    for values in outgoing.values():
        values.sort()
    for values in incoming.values():
        values.sort()

    visited: set[str] = set()
    order: list[str] = []
    for seed in sorted(graph_nodes):
        if seed in visited:
            continue
        visited.add(seed)
        stack: list[tuple[str, bool]] = [(seed, False)]
        while stack:
            node, expanded = stack.pop()
            if expanded:
                order.append(node)
                continue
            stack.append((node, True))
            for neighbour in reversed(outgoing.get(node, ())):
                if neighbour not in visited:
                    visited.add(neighbour)
                    stack.append((neighbour, False))

    components: list[set[str]] = []
    assigned: set[str] = set()
    for seed in reversed(order):
        if seed in assigned:
            continue
        component: set[str] = set()
        assigned.add(seed)
        stack = [seed]
        while stack:
            node = stack.pop()
            component.add(node)
            for neighbour in incoming.get(node, ()):
                if neighbour not in assigned:
                    assigned.add(neighbour)
                    stack.append(neighbour)
        components.append(component)

    if not components:
        raise ValueError("Car network contains no strongly connected component")
    components.sort(key=lambda component: (-len(component), min(component)))
    main = components[0]
    retained = sorted(
        (link for link in links if link.from_node in main and link.to_node in main),
        key=lambda link: link.link_id,
    )
    if not retained:
        raise ValueError("Largest car strongly connected component contains no links")
    audit = {
        "strong_component_count": len(components),
        "main_component_node_count": len(main),
        "main_component_link_count": len(retained),
        "outside_main_component_link_count": len(links) - len(retained),
    }
    return main, retained, audit


def remove_undirected_dead_ends(links: Sequence[RoadLink]) -> tuple[list[RoadLink], dict[str, int]]:
    """Retain the undirected 2-core so bidirectional cul-de-sacs are excluded."""
    neighbours: dict[str, set[str]] = defaultdict(set)
    for link in links:
        if link.from_node != link.to_node:
            neighbours[link.from_node].add(link.to_node)
            neighbours[link.to_node].add(link.from_node)
    degree = {node: len(values) for node, values in neighbours.items()}
    queue = sorted(node for node, value in degree.items() if value <= 1)
    removed_nodes: set[str] = set()
    cursor = 0
    while cursor < len(queue):
        node = queue[cursor]
        cursor += 1
        if node in removed_nodes or degree.get(node, 0) > 1:
            continue
        removed_nodes.add(node)
        for neighbour in sorted(neighbours.get(node, ())):
            if neighbour in removed_nodes:
                continue
            degree[neighbour] -= 1
            if degree[neighbour] == 1:
                queue.append(neighbour)
    retained = [
        link for link in links
        if link.from_node not in removed_nodes and link.to_node not in removed_nodes
    ]
    if not retained:
        raise ValueError("Dead-end removal eliminated every car link")
    return retained, {
        "undirected_dead_end_node_count": len(removed_nodes),
        "dead_end_links_excluded": len(links) - len(retained),
        "links_after_dead_end_filter": len(retained),
    }


def _find_column(fieldnames: Sequence[str], candidates: Sequence[str]) -> str | None:
    lookup = {name.strip().lower(): name for name in fieldnames}
    return next((lookup[name] for name in candidates if name in lookup), None)


def load_origin_proxy(path: Path | None, eligible_ids: set[str]) -> tuple[dict[str, float], dict]:
    if path is None:
        return {}, {"status": "not_provided_lane_km_fallback", "rows": 0, "usable_rows": 0}

    weights: Counter[str] = Counter()
    rows = usable = unknown = nonpositive = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"Origin proxy CSV has no header: {path}")
        link_column = _find_column(reader.fieldnames, LINK_ID_COLUMNS)
        weight_column = _find_column(reader.fieldnames, WEIGHT_COLUMNS)
        if link_column is None:
            raise ValueError(
                f"Origin proxy must contain one of {LINK_ID_COLUMNS}; got {reader.fieldnames}"
            )
        for row in reader:
            rows += 1
            link_id = (row.get(link_column) or "").strip()
            try:
                weight = float(row.get(weight_column, "1") or "1") if weight_column else 1.0
            except ValueError:
                nonpositive += 1
                continue
            if not math.isfinite(weight) or weight <= 0:
                nonpositive += 1
            elif link_id not in eligible_ids:
                unknown += 1
            else:
                weights[link_id] += weight
                usable += 1

    status = "used" if weights else "provided_no_eligible_rows_lane_km_fallback"
    return dict(weights), {
        "status": status,
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "rows": rows,
        "usable_rows": usable,
        "unknown_or_ineligible_link_rows": unknown,
        "nonpositive_or_invalid_weight_rows": nonpositive,
        "eligible_proxy_link_count": len(weights),
        "eligible_proxy_weight_sum": sum(weights.values()),
    }


def load_taxi_origin_plans(path: Path | None, eligible_ids: set[str]) -> tuple[dict[str, float], dict]:
    if path is None:
        return {}, {"status": "not_provided", "persons": 0, "selected_taxi_legs": 0}

    weights: Counter[str] = Counter()
    persons = selected_plans = taxi_legs = missing_link = ineligible_link = 0
    with open_binary(path) as handle:
        context = ET.iterparse(handle, events=("start", "end"))
        root = None
        for event, elem in context:
            tag = local_name(elem.tag)
            if root is None and event == "start":
                root = elem
            if event != "end" or tag != "person":
                continue
            persons += 1
            plans = [child for child in elem if local_name(child.tag) == "plan"]
            selected = next(
                (plan for plan in plans if (plan.get("selected") or "").strip().lower() in {"yes", "true", "1"}),
                plans[0] if len(plans) == 1 else None,
            )
            if selected is not None:
                selected_plans += 1
                previous_activity_link: str | None = None
                for element in selected:
                    element_tag = local_name(element.tag)
                    if element_tag in {"activity", "act"}:
                        previous_activity_link = element.get("link") or element.get("linkId")
                    elif element_tag == "leg" and (element.get("mode") or "").strip() == "taxi":
                        taxi_legs += 1
                        if not previous_activity_link:
                            missing_link += 1
                        elif previous_activity_link not in eligible_ids:
                            ineligible_link += 1
                        else:
                            weights[previous_activity_link] += 1.0
            elem.clear()
            if root is not None:
                root.clear()

    status = "used" if weights else "provided_no_eligible_taxi_origins"
    return dict(weights), {
        "status": status,
        "path": str(path.resolve()),
        "sha256": sha256(path),
        "persons": persons,
        "selected_plans": selected_plans,
        "selected_taxi_legs": taxi_legs,
        "eligible_taxi_origin_legs": int(sum(weights.values())),
        "missing_origin_link_legs": missing_link,
        "ineligible_origin_link_legs": ineligible_link,
        "eligible_proxy_link_count": len(weights),
    }


def apportion(total: int, targets: Sequence[tuple[str, int]]) -> dict[str, int]:
    denominator = sum(value for _name, value in targets)
    exact = [(name, total * value / denominator) for name, value in targets]
    result = {name: math.floor(value) for name, value in exact}
    remainder = total - sum(result.values())
    ranking = sorted(exact, key=lambda item: (-(item[1] - math.floor(item[1])), item[0]))
    for name, _value in ranking[:remainder]:
        result[name] += 1
    return result


def build_shift_starts(fleet_size: int) -> tuple[list[float], dict[str, int]]:
    counts = apportion(fleet_size, [(name, target) for name, target, _start, _end in SHIFT_TARGETS])
    starts: list[float] = []
    for name, _target, interval_start, interval_end in SHIFT_TARGETS:
        count = counts[name]
        if interval_start == interval_end:
            starts.extend([interval_start] * count)
        elif count:
            width = interval_end - interval_start
            starts.extend(interval_start + width * (index + 0.5) / count for index in range(count))
    if len(starts) != fleet_size:
        raise AssertionError(f"Shift apportionment produced {len(starts)} starts for {fleet_size} vehicles")
    return starts, counts


def cumulative_weights(weights: Iterable[float]) -> list[float]:
    cumulative: list[float] = []
    total = 0.0
    for weight in weights:
        total += weight
        cumulative.append(total)
    if total <= 0:
        raise ValueError("Weighted sampling requires a positive total weight")
    return cumulative


def weighted_choice(items: Sequence[RoadLink], cumulative: Sequence[float], rng: random.Random) -> RoadLink:
    target = rng.random() * cumulative[-1]
    return items[min(bisect.bisect_right(cumulative, target), len(items) - 1)]


def build_fleet(
    eligible_links: Sequence[RoadLink],
    proxy_weights: Mapping[str, float],
    fleet_size: int,
    seed: int,
) -> tuple[list[FleetVehicle], dict]:
    links = sorted(eligible_links, key=lambda link: link.link_id)
    by_id = {link.link_id: link for link in links}
    lane_cumulative = cumulative_weights(link.lane_km for link in links)
    proxy_links = [by_id[link_id] for link_id in sorted(proxy_weights) if link_id in by_id]
    proxy_cumulative = cumulative_weights(proxy_weights[link.link_id] for link in proxy_links) if proxy_links else []

    proxy_assignments = round(fleet_size * PROXY_SHARE) if proxy_links else 0
    sources = ["origin_proxy"] * proxy_assignments + ["lane_km"] * (fleet_size - proxy_assignments)
    rng = random.Random(seed)
    rng.shuffle(sources)

    starts, shift_counts = build_shift_starts(fleet_size)
    random.Random(seed + 1).shuffle(starts)
    type_counts = apportion(fleet_size, TAXI_TYPE_TARGETS)
    identities: list[tuple[str, str]] = []
    for taxi_type, _target in TAXI_TYPE_TARGETS:
        identities.extend(
            (f"hk_taxi_{taxi_type}_{index:05d}", taxi_type)
            for index in range(1, type_counts[taxi_type] + 1)
        )

    vehicles: list[FleetVehicle] = []
    start_link_counts: Counter[str] = Counter()
    for (vehicle_id, taxi_type), start, source in zip(identities, starts, sources):
        if source == "origin_proxy":
            link = weighted_choice(proxy_links, proxy_cumulative, rng)
        else:
            link = weighted_choice(links, lane_cumulative, rng)
        start_link_counts[link.link_id] += 1
        vehicles.append(
            FleetVehicle(
                vehicle_id=vehicle_id,
                taxi_type=taxi_type,
                start_link=link,
                service_begin_s=start,
                service_end_s=start + SERVICE_SECONDS,
                sampling_source=source,
                proxy_weight=float(proxy_weights.get(link.link_id, 0.0)),
            )
        )

    audit = {
        "taxi_type_counts": dict(Counter(vehicle.taxi_type for vehicle in vehicles)),
        "shift_batch_counts": shift_counts,
        "sampling_source_counts": dict(Counter(vehicle.sampling_source for vehicle in vehicles)),
        "unique_start_link_count": len(start_link_counts),
        "maximum_vehicles_on_one_start_link": max(start_link_counts.values()),
    }
    return vehicles, audit


@contextmanager
def deterministic_gzip_text(path: Path):
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8", newline="\n") as text:
                yield text


def write_fleet_xml(path: Path, vehicles: Sequence[FleetVehicle]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with deterministic_gzip_text(path) as handle:
        handle.write('<?xml version="1.0" encoding="utf-8"?>\n')
        handle.write('<!DOCTYPE vehicles SYSTEM "http://matsim.org/files/dtd/dvrp_vehicles_v1.dtd">\n')
        handle.write("<vehicles>\n")
        for vehicle in vehicles:
            handle.write(
                "  <vehicle"
                f" id={quoteattr(vehicle.vehicle_id)}"
                f" start_link={quoteattr(vehicle.start_link.link_id)}"
                f' t_0="{vehicle.service_begin_s:.3f}"'
                f' t_1="{vehicle.service_end_s:.3f}"'
                f' capacity="{VEHICLE_CAPACITY}" />\n'
            )
        handle.write("</vehicles>\n")


def write_start_links(path: Path, vehicles: Sequence[FleetVehicle]) -> None:
    fields = (
        "vehicle_id", "taxi_type", "start_link_id", "x", "y", "length_m", "lanes",
        "lane_km", "service_begin_s", "service_end_s", "capacity", "pcu",
        "sampling_source", "proxy_weight",
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for vehicle in vehicles:
            link = vehicle.start_link
            writer.writerow({
                "vehicle_id": vehicle.vehicle_id,
                "taxi_type": vehicle.taxi_type,
                "start_link_id": link.link_id,
                "x": f"{link.x:.3f}",
                "y": f"{link.y:.3f}",
                "length_m": f"{link.length_m:.3f}",
                "lanes": f"{link.lanes:.3f}",
                "lane_km": f"{link.lane_km:.6f}",
                "service_begin_s": f"{vehicle.service_begin_s:.3f}",
                "service_end_s": f"{vehicle.service_end_s:.3f}",
                "capacity": VEHICLE_CAPACITY,
                "pcu": f"{ASSUMED_PCU:.1f}",
                "sampling_source": vehicle.sampling_source,
                "proxy_weight": f"{vehicle.proxy_weight:.6f}",
            })


def nactive_rows(vehicles: Sequence[FleetVehicle]) -> list[dict]:
    rows = []
    for index in range(96):
        start = index * 15 * 60.0
        end = start + 15 * 60.0
        active = sum(vehicle.service_begin_s <= start < vehicle.service_end_s for vehicle in vehicles)
        rows.append({
            "period_index": index,
            "start_s": int(start),
            "end_s": int(end),
            "active_at_start": active,
            "active_share": active / len(vehicles),
        })
    return rows


def write_nactive(path: Path, rows: Sequence[dict]) -> None:
    fields = ("period_index", "start_s", "end_s", "active_at_start", "active_share")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "active_share": f"{row['active_share']:.9f}"})


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", type=Path, required=True, help="Candidate11 MATSim network XML or XML.gz")
    parser.add_argument(
        "--link-origin-proxy", "--tcs26-origin-proxy", dest="link_origin_proxy", type=Path,
        help=("Optional UTF-8 derived link-level Taxi-origin proxy CSV; this does not read raw "
              "TCS26 zone OD. Absent/empty coverage falls back to lane-km"),
    )
    parser.add_argument(
        "--taxi-origin-plans", type=Path,
        help=("Optional frozen MATSim selected/experienced plans XML(.gz/.zst); Taxi origins "
              "derived from it take precedence over --link-origin-proxy"),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--fleet-size", type=int, default=FULL_FLEET_SIZE, help="Use 1550 for the 0.5%% smoke fleet")
    parser.add_argument("--seed", type=int, default=20260815)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict:
    if args.fleet_size <= 0:
        raise ValueError("--fleet-size must be positive")
    if not args.network.is_file():
        raise FileNotFoundError(args.network)
    if args.link_origin_proxy is not None and not args.link_origin_proxy.is_file():
        raise FileNotFoundError(args.link_origin_proxy)
    if args.taxi_origin_plans is not None and not args.taxi_origin_plans.is_file():
        raise FileNotFoundError(args.taxi_origin_plans)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    _nodes, car_links, network_audit = parse_car_network(args.network)
    core_links, dead_end_audit = remove_undirected_dead_ends(car_links)
    _component_nodes, eligible_links, component_audit = largest_strong_component(core_links)
    eligible_ids = {link.link_id for link in eligible_links}
    plan_weights, plans_audit = load_taxi_origin_plans(args.taxi_origin_plans, eligible_ids)
    csv_weights, csv_audit = load_origin_proxy(args.link_origin_proxy, eligible_ids)
    if plan_weights:
        proxy_weights = plan_weights
        origin_source = "frozen_taxi_origin_plans"
    elif csv_weights:
        proxy_weights = csv_weights
        origin_source = "derived_link_origin_proxy_csv"
    else:
        proxy_weights = {}
        origin_source = "lane_km_fallback"
    vehicles, fleet_audit = build_fleet(eligible_links, proxy_weights, args.fleet_size, args.seed)
    active_rows = nactive_rows(vehicles)

    fleet_path = args.output_dir / "hong_kong_taxi_fleet.xml.gz"
    starts_path = args.output_dir / "hong_kong_taxi_start_links.csv"
    active_path = args.output_dir / "hong_kong_taxi_nactive_15min.csv"
    qa_path = args.output_dir / "hong_kong_taxi_fleet_qa.json"
    write_fleet_xml(fleet_path, vehicles)
    write_start_links(starts_path, vehicles)
    write_nactive(active_path, active_rows)

    with gzip.open(fleet_path, "rb") as handle:
        xml_vehicle_count = len(ET.parse(handle).getroot().findall("vehicle"))
    eligible_link_ids = {link.link_id for link in eligible_links}
    checks = {
        "fleet_count_matches_request": len(vehicles) == args.fleet_size == xml_vehicle_count,
        "all_start_links_eligible": all(vehicle.start_link.link_id in eligible_link_ids for vehicle in vehicles),
        "all_capacities_equal_four": VEHICLE_CAPACITY == 4,
        "all_service_windows_exactly_18h": all(
            math.isclose(
                vehicle.service_end_s - vehicle.service_begin_s,
                SERVICE_SECONDS,
                rel_tol=0.0,
                abs_tol=1e-9,
            )
            for vehicle in vehicles
        ),
        "latest_service_end_no_later_than_28h": max(vehicle.service_end_s for vehicle in vehicles) <= 28 * 3600,
        "nactive_has_96_periods": len(active_rows) == 96,
        "stable_unique_vehicle_ids": len({vehicle.vehicle_id for vehicle in vehicles}) == len(vehicles),
    }
    if args.fleet_size == FULL_FLEET_SIZE:
        checks["full_fleet_type_targets_exact"] = fleet_audit["taxi_type_counts"] == dict(TAXI_TYPE_TARGETS)
        checks["full_fleet_shift_targets_exact"] = fleet_audit["shift_batch_counts"] == {
            name: target for name, target, _start, _end in SHIFT_TARGETS
        }

    qa = {
        "status": "validated" if all(checks.values()) else "failed",
        "created_by": "scripts/hong_kong_single_city/demand_generation/build_hong_kong_taxi_dvrp_fleet.py",
        "inputs": {
            "network": str(args.network.resolve()),
            "network_sha256": sha256(args.network),
            "origin_prior_source": origin_source,
            "taxi_origin_plans": plans_audit,
            "link_origin_proxy": csv_audit,
        },
        "parameters": {
            "fleet_size": args.fleet_size,
            "seed": args.seed,
            "vehicle_capacity": VEHICLE_CAPACITY,
            "assumed_pcu": ASSUMED_PCU,
            "service_hours": SERVICE_SECONDS / 3600,
            "origin_proxy_share": PROXY_SHARE if proxy_weights else 0.0,
            "lane_km_share": 1.0 - PROXY_SHARE if proxy_weights else 1.0,
        },
        "network_filter": {**network_audit, **dead_end_audit, **component_audit},
        "fleet": {
            **fleet_audit,
            "service_begin_min_s": min(vehicle.service_begin_s for vehicle in vehicles),
            "service_begin_max_s": max(vehicle.service_begin_s for vehicle in vehicles),
            "service_end_min_s": min(vehicle.service_end_s for vehicle in vehicles),
            "service_end_max_s": max(vehicle.service_end_s for vehicle in vehicles),
        },
        "nactive": {
            "period_count": len(active_rows),
            "minimum_active": min(row["active_at_start"] for row in active_rows),
            "maximum_active": max(row["active_at_start"] for row in active_rows),
            "at_00_00": active_rows[0]["active_at_start"],
            "at_08_00": active_rows[32]["active_at_start"],
            "at_18_00": active_rows[72]["active_at_start"],
            "at_23_45": active_rows[95]["active_at_start"],
        },
        "outputs": {
            "fleet_xml_gz": str(fleet_path.resolve()),
            "start_links_csv": str(starts_path.resolve()),
            "nactive_csv": str(active_path.resolve()),
        },
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
    }
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if qa["status"] != "validated":
        raise RuntimeError(f"Fleet QA failed: {qa['failed_checks']}")
    return qa


def main() -> None:
    qa = run(parse_args())
    print(json.dumps({
        "status": qa["status"],
        "fleet_size": qa["parameters"]["fleet_size"],
        "eligible_links": qa["network_filter"]["main_component_link_count"],
        "taxi_type_counts": qa["fleet"]["taxi_type_counts"],
        "sampling_source_counts": qa["fleet"]["sampling_source_counts"],
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
