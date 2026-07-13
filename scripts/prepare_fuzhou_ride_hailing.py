"""Prepare Fuzhou ride-hailing demand candidates and MATSim taxi fleet.

This script is intentionally self-contained: it reads the current 2% MATSim
population, adds a ``ride_hailing`` candidate plan to every person, removes
illegal car plans for car-unavailable persons, and creates a DVRP/taxi fleet
whose size is derived from the population sample rate.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import io
import json
import math
import random
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import TextIO

import zstandard as zstd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POPULATION = ROOT / "output-fuzhou-transit-mode-choice-2pct-waitpenalty-metroprefer-cont20" / "output_plans.xml.zst"
DEFAULT_NETWORK = (
    ROOT
    / "data"
    / "transit"
    / "fuzhou_transit_matsim_integrated_20260709_bus_priority_transferwait_metro40"
    / "network_with_car_busprio_metro.xml.gz"
)
DEFAULT_AGENTS_SUMMARY = (
    ROOT
    / "data"
    / "matsim_agents"
    / "fuzhou_city_23_greenspace_grid_multi_activity_2pct_same_day_night"
    / "multi_activity_agents_summary.json"
)
DEFAULT_DEMAND_OUT = (
    ROOT
    / "data"
    / "matsim_routes"
    / "fuzhou_city_23_greenspace_grid_multi_activity_2pct_ride_hailing"
)
DEFAULT_FLEET_OUT = ROOT / "data" / "ride_hailing" / "fuzhou_ride_hailing_2pct_20260712"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--population", type=Path, default=DEFAULT_POPULATION)
    parser.add_argument("--network", type=Path, default=DEFAULT_NETWORK)
    parser.add_argument("--agents-summary", type=Path, default=DEFAULT_AGENTS_SUMMARY)
    parser.add_argument("--demand-out-dir", type=Path, default=DEFAULT_DEMAND_OUT)
    parser.add_argument("--fleet-out-dir", type=Path, default=DEFAULT_FLEET_OUT)
    parser.add_argument("--population-sample-rate", type=float, default=None)
    parser.add_argument("--daily-fleet-total", type=int, default=34_709)
    parser.add_argument("--vehicle-capacity", type=int, default=4)
    parser.add_argument("--service-hours", type=float, default=8.0)
    parser.add_argument("--seed", type=int, default=20260712)
    return parser.parse_args()


def open_text(path: Path, mode: str) -> TextIO:
    if "r" in mode and path.suffix == ".zst":
        raw = path.open("rb")
        reader = zstd.ZstdDecompressor().stream_reader(raw)
        return io.TextIOWrapper(reader, encoding="utf-8", newline="\n")
    if path.suffix == ".gz":
        return gzip.open(path, mode, encoding="utf-8", newline="\n")
    return path.open(mode, encoding="utf-8", newline="\n")


def parse_time_seconds(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        if ":" not in value:
            return float(value)
        parts = [float(p) for p in value.split(":")]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        if len(parts) == 2:
            return parts[0] * 3600 + parts[1] * 60
    except ValueError:
        return None
    return None


def get_attribute(person: ET.Element, name: str, default: str = "") -> str:
    attrs = person.find("attributes")
    if attrs is None:
        return default
    for attr in attrs.findall("attribute"):
        if attr.get("name") == name:
            return (attr.text or default).strip()
    return default


def set_attribute(person: ET.Element, name: str, klass: str, value: str) -> None:
    attrs = person.find("attributes")
    if attrs is None:
        attrs = ET.Element("attributes")
        person.insert(0, attrs)
    for attr in attrs.findall("attribute"):
        if attr.get("name") == name:
            attr.set("class", klass)
            attr.text = value
            return
    attr = ET.SubElement(attrs, "attribute", {"name": name, "class": klass})
    attr.text = value


def plan_modes(plan: ET.Element) -> set[str]:
    return {leg.get("mode", "") for leg in plan.findall("leg") if leg.get("mode")}


def first_leg_mode(plan: ET.Element) -> str:
    leg = plan.find("leg")
    return leg.get("mode", "") if leg is not None else ""


def selected_plan(person: ET.Element) -> ET.Element | None:
    for plan in person.findall("plan"):
        if plan.get("selected") == "yes":
            return plan
    plans = person.findall("plan")
    return plans[0] if plans else None


def select_plan(person: ET.Element, chosen: ET.Element) -> None:
    for plan in person.findall("plan"):
        plan.set("selected", "yes" if plan is chosen else "no")


def clone_mode_plan(plan: ET.Element, mode: str) -> ET.Element:
    cloned = copy.deepcopy(plan)
    cloned.set("selected", "no")
    cloned.attrib.pop("score", None)
    for leg in cloned.findall("leg"):
        leg.set("mode", mode)
        leg.attrib.pop("trav_time", None)
        leg.attrib.pop("dep_time", None)
        for route in list(leg.findall("route")):
            leg.remove(route)
    return cloned


def choose_fallback_plan(person: ET.Element) -> ET.Element | None:
    for mode in ("pt", "walk", "ride_hailing"):
        for plan in person.findall("plan"):
            modes = plan_modes(plan)
            if modes and modes == {mode}:
                return plan
    plans = person.findall("plan")
    return plans[0] if plans else None


def extract_plan_departures(plan: ET.Element) -> list[float]:
    departures: list[float] = []
    current_time: float | None = None
    for elem in list(plan):
        if elem.tag == "activity":
            end = parse_time_seconds(elem.get("end_time"))
            if end is not None:
                current_time = end
        elif elem.tag == "leg":
            dep = parse_time_seconds(elem.get("dep_time"))
            if dep is None:
                dep = current_time
            if dep is not None and 0 <= dep < 24 * 3600:
                departures.append(dep)
    return departures


def parse_network(path: Path) -> tuple[dict[str, tuple[float, float]], list[dict]]:
    nodes: dict[str, tuple[float, float]] = {}
    links: list[dict] = []
    with open_text(path, "rt") as handle:
        for _event, elem in ET.iterparse(handle, events=("end",)):
            if elem.tag == "node":
                node_id = elem.get("id")
                if node_id:
                    nodes[node_id] = (float(elem.get("x", "nan")), float(elem.get("y", "nan")))
                elem.clear()
            elif elem.tag == "link":
                link_id = elem.get("id", "")
                from_id = elem.get("from", "")
                to_id = elem.get("to", "")
                modes = set((elem.get("modes", "") or "").split(","))
                if "car" in modes and not link_id.startswith("busprio_") and from_id in nodes and to_id in nodes:
                    fx, fy = nodes[from_id]
                    tx, ty = nodes[to_id]
                    length = float(elem.get("length", "0") or 0)
                    freespeed = float(elem.get("freespeed", "0") or 0)
                    capacity = float(elem.get("capacity", "0") or 0)
                    permlanes = float(elem.get("permlanes", "1") or 1)
                    links.append(
                        {
                            "id": link_id,
                            "from": from_id,
                            "to": to_id,
                            "x": (fx + tx) / 2,
                            "y": (fy + ty) / 2,
                            "length": length,
                            "freespeed": freespeed,
                            "capacity": capacity,
                            "permlanes": permlanes,
                            "road_class": infer_road_class(link_id, freespeed, capacity, permlanes),
                        }
                    )
                elem.clear()
    return nodes, links


def infer_road_class(link_id: str, freespeed: float, capacity: float, permlanes: float) -> str:
    if link_id.startswith("syn_bus"):
        return "synthetic"
    kmh = freespeed * 3.6
    if kmh >= 85 or permlanes >= 3.0:
        return "trunk_primary"
    if kmh >= 55 or permlanes >= 2.0:
        return "secondary"
    if kmh >= 35 or capacity >= 250:
        return "tertiary"
    return "local"


def road_weight(road_class: str) -> float:
    return {
        "trunk_primary": 1.70,
        "secondary": 1.45,
        "tertiary": 1.00,
        "synthetic": 0.90,
        "local": 0.55,
    }.get(road_class, 0.75)


def load_population_sample_rate(args: argparse.Namespace, first_person_sample_weight: float | None) -> float:
    if args.population_sample_rate is not None:
        return float(args.population_sample_rate)
    if args.agents_summary.exists():
        data = json.loads(args.agents_summary.read_text(encoding="utf-8"))
        value = data.get("population_sampling", {}).get("population_sample_rate", data.get("population_sample_rate"))
        if value is not None:
            return float(value)
    if first_person_sample_weight and first_person_sample_weight > 0:
        return 1.0 / first_person_sample_weight
    raise RuntimeError("Could not determine population sample rate; pass --population-sample-rate")


def write_person(handle: TextIO, person: ET.Element) -> None:
    handle.write(f"  {ET.tostring(person, encoding='unicode', short_empty_elements=True)}\n")


def weighted_choice_index(weights: list[float], rng: random.Random) -> int:
    total = sum(weights)
    if total <= 0:
        return rng.randrange(len(weights))
    target = rng.random() * total
    acc = 0.0
    for i, weight in enumerate(weights):
        acc += weight
        if acc >= target:
            return i
    return len(weights) - 1


def build_shift_starts(departures: list[float], fleet_size: int, service_seconds: float, rng: random.Random) -> list[float]:
    if not departures:
        departures = [7.5 * 3600, 8.0 * 3600, 17.5 * 3600, 18.0 * 3600, 12.0 * 3600, 21.0 * 3600]
    starts: list[float] = []
    latest_start = max(0.0, 24 * 3600 - service_seconds)
    for _ in range(fleet_size):
        demand_time = rng.choice(departures)
        jitter = rng.uniform(-30 * 60, 30 * 60)
        start = demand_time - service_seconds / 2 + jitter
        starts.append(max(0.0, min(latest_start, start)))
    starts.sort()
    return starts


def sample_start_links(
    links: list[dict],
    fleet_size: int,
    all_home_counts: Counter[str],
    private_home_counts: Counter[str],
    rng: random.Random,
) -> tuple[list[dict], Counter[str], Counter[tuple[int, int]], int]:
    by_id = {link["id"]: link for link in links}
    scored_links = []
    for link in links:
        link_id = link["id"]
        population_term = math.sqrt(all_home_counts.get(link_id, 0))
        private_term = math.sqrt(private_home_counts.get(link_id, 0))
        score = (1.0 + 0.50 * population_term + 1.00 * private_term) * road_weight(link["road_class"])
        scored_links.append((link, max(score, 1e-6)))

    max_per_link = max(2, math.ceil(fleet_size / 250))
    max_per_cell = max(4, math.ceil(fleet_size / 100))
    selected: list[dict] = []
    link_counts: Counter[str] = Counter()
    cell_counts: Counter[tuple[int, int]] = Counter()
    relaxed_cell_assignments = 0

    for _ in range(fleet_size):
        candidates = []
        weights = []
        for link, score in scored_links:
            link_id = link["id"]
            if link_counts[link_id] >= max_per_link:
                continue
            cell = (int(link["x"] // 300), int(link["y"] // 300))
            if cell_counts[cell] >= max_per_cell:
                continue
            candidates.append(link)
            weights.append(score)

        if not candidates:
            relaxed_cell_assignments += 1
            candidates = [link for link, _ in scored_links if link_counts[link["id"]] < max_per_link]
            weights = [score for link, score in scored_links if link_counts[link["id"]] < max_per_link]
        if not candidates:
            raise RuntimeError("Could not sample enough ride-hailing start links; link cap too strict")

        chosen = candidates[weighted_choice_index(weights, rng)]
        selected.append(chosen)
        link_counts[chosen["id"]] += 1
        cell_counts[(int(chosen["x"] // 300), int(chosen["y"] // 300))] += 1

    missing = sum(1 for link_id in list(all_home_counts)[:10] if link_id not in by_id)
    return selected, link_counts, cell_counts, missing + relaxed_cell_assignments


def write_fleet(path: Path, selected_links: list[dict], starts: list[float], vehicle_capacity: int, service_seconds: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open_text(path, "wt") as handle:
        handle.write('<?xml version="1.0" encoding="utf-8"?>\n')
        handle.write('<!DOCTYPE vehicles SYSTEM "http://matsim.org/files/dtd/dvrp_vehicles_v1.dtd">\n')
        handle.write("<vehicles>\n")
        for idx, (link, start) in enumerate(zip(selected_links, starts), start=1):
            end = min(24 * 3600, start + service_seconds)
            handle.write(
                f'  <vehicle id="ride_hailing_{idx:05d}" start_link="{link["id"]}" '
                f't_0="{start:.0f}" t_1="{end:.0f}" capacity="{vehicle_capacity}" />\n'
            )
        handle.write("</vehicles>\n")


def main() -> None:
    args = parse_args()
    started = time.time()
    rng = random.Random(args.seed)
    args.demand_out_dir.mkdir(parents=True, exist_ok=True)
    args.fleet_out_dir.mkdir(parents=True, exist_ok=True)

    output_population = args.demand_out_dir / "mode_choice_plans_car_pt_walk_ride_hailing_2pct.xml.gz"
    output_fleet = args.fleet_out_dir / "ride_hailing_fleet.xml.gz"
    summary_path = args.fleet_out_dir / "ride_hailing_preparation_summary.json"
    link_qa_path = args.fleet_out_dir / "ride_hailing_start_links.csv"

    _nodes, car_links = parse_network(args.network)
    if not car_links:
        raise RuntimeError("No car-allowed candidate links found in network")

    counters: Counter[str] = Counter()
    selected_modes: Counter[str] = Counter()
    plan_mode_counts: Counter[str] = Counter()
    car_avail_counts: Counter[str] = Counter()
    all_home_counts: Counter[str] = Counter()
    private_home_counts: Counter[str] = Counter()
    departure_times: list[float] = []
    first_sample_weight: float | None = None

    with open_text(output_population, "wt") as out:
        out.write('<?xml version="1.0" encoding="utf-8"?>\n')
        out.write('<!DOCTYPE population SYSTEM "http://www.matsim.org/files/dtd/population_v6.dtd">\n')
        out.write("<population>\n")

        with open_text(args.population, "rt") as inp:
            for _event, elem in ET.iterparse(inp, events=("end",)):
                if elem.tag != "person":
                    continue
                person = copy.deepcopy(elem)
                elem.clear()
                counters["persons"] += 1

                sample_weight_text = get_attribute(person, "sample_weight", "")
                if first_sample_weight is None and sample_weight_text:
                    try:
                        first_sample_weight = float(sample_weight_text)
                    except ValueError:
                        pass

                avail = get_attribute(person, "carAvail", "unknown")
                car_avail_counts[avail] += 1
                source = selected_plan(person)
                if source is None:
                    counters["persons_without_plans"] += 1
                    continue

                first_act = source.find("activity")
                home_link = first_act.get("link") if first_act is not None else None
                if home_link:
                    all_home_counts[home_link] += 1
                    if avail == "always":
                        private_home_counts[home_link] += 1

                departure_times.extend(extract_plan_departures(source))

                for old in list(person.findall("plan")):
                    modes = plan_modes(old)
                    if modes == {"ride_hailing"}:
                        person.remove(old)
                        counters["old_ride_hailing_plans_removed"] += 1
                    elif avail == "never" and modes == {"car"}:
                        person.remove(old)
                        counters["car_plans_removed_for_caravail_never"] += 1

                if not any(plan_modes(plan) == {"ride_hailing"} for plan in person.findall("plan")):
                    person.append(clone_mode_plan(source, "ride_hailing"))
                    counters["ride_hailing_candidate_added"] += 1
                    set_attribute(person, "ride_hailing_available", "java.lang.String", "yes")

                plans = person.findall("plan")
                if not plans:
                    counters["persons_without_plans_after_fix"] += 1
                    continue

                selected_after = selected_plan(person)
                if selected_after is None or selected_after not in plans:
                    fallback = choose_fallback_plan(person)
                    if fallback is not None:
                        select_plan(person, fallback)
                        counters["selected_plan_reassigned"] += 1
                else:
                    select_plan(person, selected_after)

                final_selected = selected_plan(person)
                if final_selected is not None:
                    selected_modes[first_leg_mode(final_selected) or "unknown"] += 1

                for plan in person.findall("plan"):
                    mode = first_leg_mode(plan) or "unknown"
                    plan_mode_counts[mode] += 1
                    counters["plans"] += 1

                write_person(out, person)

        out.write("</population>\n")

    sample_rate = load_population_sample_rate(args, first_sample_weight)
    fleet_size = int(round(args.daily_fleet_total * sample_rate))
    if fleet_size <= 0:
        raise RuntimeError(f"Computed non-positive fleet size: {fleet_size}")
    service_seconds = args.service_hours * 3600
    selected_links, link_counts, cell_counts, sampling_warnings = sample_start_links(
        car_links, fleet_size, all_home_counts, private_home_counts, rng
    )
    starts = build_shift_starts(departure_times, fleet_size, service_seconds, rng)
    write_fleet(output_fleet, selected_links, starts, args.vehicle_capacity, service_seconds)

    with link_qa_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("vehicle_id,link_id,x,y,road_class,freespeed_kmh,capacity,permlanes,service_begin_s,service_end_s,link_vehicle_count\n")
        for idx, (link, start) in enumerate(zip(selected_links, starts), start=1):
            handle.write(
                f"ride_hailing_{idx:05d},{link['id']},{link['x']:.3f},{link['y']:.3f},{link['road_class']},"
                f"{link['freespeed'] * 3.6:.3f},{link['capacity']:.3f},{link['permlanes']:.3f},"
                f"{start:.0f},{min(24 * 3600, start + service_seconds):.0f},{link_counts[link['id']]}\n"
            )

    summary = {
        "created_by": "scripts/prepare_fuzhou_ride_hailing.py",
        "created_at_epoch": time.time(),
        "runtime_seconds": round(time.time() - started, 3),
        "inputs": {
            "population": str(args.population),
            "network": str(args.network),
            "agents_summary": str(args.agents_summary),
        },
        "outputs": {
            "population": str(output_population),
            "fleet": str(output_fleet),
            "start_link_qa": str(link_qa_path),
        },
        "population_sample_rate": sample_rate,
        "daily_fleet_total": args.daily_fleet_total,
        "fleet_size": fleet_size,
        "vehicle_capacity": args.vehicle_capacity,
        "service_hours": args.service_hours,
        "max_vehicles_on_one_link": max(link_counts.values()) if link_counts else 0,
        "max_vehicles_in_one_300m_cell": max(cell_counts.values()) if cell_counts else 0,
        "candidate_car_links": len(car_links),
        "counters": dict(counters),
        "car_availability": dict(car_avail_counts),
        "selected_modes_after_fix": dict(selected_modes),
        "plan_modes_after_fix": dict(plan_mode_counts),
        "sampling_warnings": sampling_warnings,
        "departure_time_samples": len(departure_times),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
