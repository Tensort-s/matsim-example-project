#!/usr/bin/env python3
"""Plot one executed iteration-49 private-car trip as a cost anatomy map."""

from __future__ import annotations

import argparse
import gzip
import json
import math
from pathlib import Path
from xml.etree import ElementTree as ET

import geopandas as gpd
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.patches import FancyBboxPatch, Rectangle
import numpy as np
import pandas as pd
import zstandard as zstd

from progress_report_figure_style import (
    PALETTE,
    add_method_note,
    apply_progress_report_style,
    clean_map_axis,
    save_figure,
)
from plot_progress_hong_kong_monetary_cost_maps import (
    CANONICAL_ROOT,
    EVENT_RE,
    GRID,
    OUTPUT_DIR,
    SOURCE,
    activity_group,
    car_costs,
    seconds,
    zone_group,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--source-dir", type=Path, default=SOURCE)
    parser.add_argument("--ssh-host", default="by@100.103.8.34")
    return parser.parse_args()


def tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def selected_route(path: Path, person_id: str, car_ordinal: int) -> list[str]:
    with path.open("rb") as compressed:
        with zstd.ZstdDecompressor().stream_reader(compressed) as reader:
            for _, person in ET.iterparse(reader, events=("end",)):
                if tag(person) != "person":
                    continue
                if person.attrib.get("id") != person_id:
                    person.clear()
                    continue
                plans = [child for child in person if tag(child) == "plan"]
                plan = next(
                    (p for p in plans if p.attrib.get("selected", "yes") in {"yes", "true", "1"}),
                    plans[0],
                )
                car_legs = [child for child in plan if tag(child) == "leg" and child.attrib.get("mode") == "car"]
                leg = car_legs[car_ordinal]
                route = next(child for child in leg if tag(child) == "route")
                links = (route.text or "").strip().split()
                start = route.attrib.get("start_link", "")
                end = route.attrib.get("end_link", "")
                if start and (not links or links[0] != start): links.insert(0, start)
                if end and (not links or links[-1] != end): links.append(end)
                return links
    raise KeyError((person_id, car_ordinal))


def network_geometry(path: Path) -> tuple[dict[str, tuple[float, float]], dict[str, dict[str, object]]]:
    nodes: dict[str, tuple[float, float]] = {}
    links: dict[str, dict[str, object]] = {}
    with gzip.open(path, "rb") as handle:
        for _, element in ET.iterparse(handle, events=("end",)):
            name = tag(element)
            if name == "node":
                nodes[element.attrib["id"]] = (float(element.attrib["x"]), float(element.attrib["y"]))
            elif name == "link":
                links[element.attrib["id"]] = {
                    "from": element.attrib["from"], "to": element.attrib["to"],
                    "length": float(element.attrib["length"]),
                }
            element.clear()
    return nodes, links


def time_label(value: float) -> str:
    value = int(round(value))
    return f"{value // 3600:02d}:{value % 3600 // 60:02d}:{value % 60:02d}"


def facility_zone_lookup(car_root: Path) -> dict[str, int]:
    feasibility = pd.read_parquet(
        car_root / "car_leg_input_feasibility.parquet",
        columns=["destination_facility_id", "destination_tcs_zone"],
    ).dropna()
    result = (
        feasibility.assign(destination_tcs_zone=lambda x: x.destination_tcs_zone.astype(int))
        .drop_duplicates("destination_facility_id")
        .set_index("destination_facility_id")["destination_tcs_zone"].to_dict()
    )
    repairs = pd.read_csv(car_root / "facility_tcs_zone_repairs.csv")
    result.update(dict(zip(repairs.destination_facility_id, repairs.tcs_zone.astype(int))))
    return result


def rounded_panel(ax, y: float, title: str, amount: float, color: str, lines: list[str]) -> None:
    box = FancyBboxPatch(
        (.03, y), .94, .165, boxstyle="round,pad=.012,rounding_size=.018",
        transform=ax.transAxes, facecolor="#FAFBFA", edgecolor="#D3D8D6", linewidth=.9,
    )
    ax.add_patch(box)
    ax.add_patch(Rectangle((.03, y), .018, .165, transform=ax.transAxes, color=color, linewidth=0))
    ax.text(.075, y + .125, title, transform=ax.transAxes, fontsize=11.2, va="center")
    ax.text(.93, y + .125, f"HK${amount:,.1f}", transform=ax.transAxes,
            fontsize=13.5, ha="right", va="center", color=color)
    ax.text(.075, y + .072, "\n".join(lines), transform=ax.transAxes,
            fontsize=8.3, va="center", color=PALETTE["muted"], linespacing=1.25)


def main() -> None:
    args = parse_args()
    source = args.source_dir
    it49 = source / "run6_it49"
    inputs = source / "run6_inputs"
    trips = pd.read_csv(it49 / "49.trips.csv.zst", sep=";", compression="zstd")
    legs = pd.read_csv(it49 / "49.legs.csv.zst", sep=";", compression="zstd")
    all_car = legs[legs["mode"].eq("car")].copy()
    all_car["car_ordinal"] = all_car.groupby("person").cumcount()
    car, qa = car_costs(
        legs, trips, inputs / "car_cost", it49 / "toll_link_enter_events.xmlfrag",
        args.ssh_host,
    )
    car = car.merge(all_car[["person", "trip_id", "car_ordinal"]], on=["person", "trip_id"], how="left", validate="one_to_one")
    candidates = car[
        car["fully_resolved"] & (car["toll_hkd"] > 0) & (car["parking_hkd"] > 0)
        & car["distance"].between(8_000, 35_000)
    ].copy()
    if candidates.empty:
        raise ValueError("No complete Car trip has positive energy, toll and parking components")
    median = candidates["cost_hkd"].median()
    target = candidates.loc[(candidates["cost_hkd"] - median).abs().idxmin()]
    route_links = selected_route(
        it49 / "49.experienced_plans.xml.zst", str(target.person), int(target.car_ordinal)
    )
    nodes, network = network_geometry(inputs / "network.xml.gz")
    route_links = [link for link in route_links if link in network]
    segments, lengths = [], []
    for link_id in route_links:
        link = network[link_id]
        segments.append([nodes[str(link["from"])], nodes[str(link["to"])]])
        lengths.append(float(link["length"]))
    cumulative = np.cumsum(lengths) / 1000
    total_route_km = float(sum(lengths) / 1000)

    mapping = pd.read_csv(inputs / "car_cost/toll_facility_network_mapping.csv")
    mapping = mapping[mapping["mapping_status"].eq("mapped")]
    facility_by_link = dict(zip(mapping.matsim_link_id, mapping.canonical_facility_id))
    toll_points = []
    for line in (it49 / "toll_link_enter_events.xmlfrag").read_text(encoding="utf-8").splitlines():
        match = EVENT_RE.search(line)
        if not match:
            continue
        event = match.groupdict()
        if event["vehicle"] == target.vehicle_id and target.departure_s <= float(event["time"]) <= target.arrival_s + 1:
            link = network[event["link"]]
            a, b = nodes[str(link["from"])], nodes[str(link["to"])]
            toll_points.append({
                "x": (a[0] + b[0]) / 2, "y": (a[1] + b[1]) / 2,
                "facility": facility_by_link[event["link"]], "time": float(event["time"]),
                "link": event["link"],
            })
    if not toll_points:
        raise AssertionError("Selected costed trip has no matching toll LinkEnter event")

    zones = facility_zone_lookup(inputs / "car_cost")
    facility = str(target.end_facility_id).split("__hk_car_anchor__", 1)[0]
    zone = zones[facility]
    park_group = activity_group(str(target.end_activity_type))
    duration_h = (target.next_departure_s - target.arrival_s) / 3600
    energy_rate = float(
        pd.read_csv(inputs / "car_cost/car_energy_cost_parameters.csv")
        .query("scenario == 'base'")["energy_cost_hkd_per_km"].iloc[0]
    )
    total = float(target.cost_hkd)

    apply_progress_report_style()
    fig = plt.figure(figsize=(13.2, 7.9))
    ax_map = fig.add_axes([.035, .11, .64, .79])
    ax_info = fig.add_axes([.705, .115, .27, .77])
    grid = gpd.read_file(GRID).to_crs("EPSG:32650")
    grid.plot(ax=ax_map, color=PALETTE["land"], edgecolor="#D4D9D7", linewidth=.16)
    grid.dissolve().boundary.plot(ax=ax_map, color=PALETTE["boundary"], linewidth=.7)
    collection = LineCollection(segments, cmap=mpl.colors.LinearSegmentedColormap.from_list(
        "energy", [PALETTE["blue_light"], PALETTE["brick"]]
    ), norm=mpl.colors.Normalize(0, max(cumulative)), linewidths=3.0, zorder=5)
    collection.set_array(cumulative)
    ax_map.add_collection(LineCollection(segments, colors="white", linewidths=5.2, zorder=4))
    ax_map.add_collection(collection)
    origin = segments[0][0]
    destination = segments[-1][1]
    ax_map.scatter(*origin, s=95, color=PALETTE["blue"], edgecolor="white", linewidth=1.3, zorder=7)
    ax_map.scatter(*destination, s=95, marker="s", color=PALETTE["brick"], edgecolor="white", linewidth=1.3, zorder=7)
    for point in toll_points:
        ax_map.scatter(point["x"], point["y"], marker="D", s=95, color=PALETTE["gold"],
                       edgecolor="white", linewidth=1.2, zorder=8)
        label = point["facility"].replace("_", " ").title()
        ax_map.annotate(f"{label}\n{time_label(point['time'])}", (point["x"], point["y"]),
                        xytext=(10, 10), textcoords="offset points", fontsize=8.2,
                        bbox=dict(facecolor="white", edgecolor="#D0D4D2", alpha=.94, boxstyle="round,pad=.28"))
    all_xy = np.asarray([p for seg in segments for p in seg])
    xmin, ymin = all_xy.min(axis=0); xmax, ymax = all_xy.max(axis=0)
    pad = max(xmax - xmin, ymax - ymin) * .13
    ax_map.set_xlim(xmin - pad, xmax + pad); ax_map.set_ylim(ymin - pad, ymax + pad)
    clean_map_axis(ax_map)
    scale = mpl.cm.ScalarMappable(norm=mpl.colors.Normalize(0, total_route_km), cmap=collection.cmap)
    cbar = fig.colorbar(scale, ax=ax_map, orientation="horizontal", fraction=.032, pad=.012, shrink=.54)
    cbar.set_label("Cumulative route distance — continuous energy charge (km)", fontsize=8)
    cbar.ax.tick_params(labelsize=7.5)
    ax_map.legend(
        handles=[
            mpl.lines.Line2D([], [], marker="o", linestyle="none", color=PALETTE["blue"], label="Origin"),
            mpl.lines.Line2D([], [], marker="s", linestyle="none", color=PALETTE["brick"], label="Destination / parking"),
            mpl.lines.Line2D([], [], marker="D", linestyle="none", color=PALETTE["gold"], label="Toll charged on LinkEnter"),
        ], loc="upper left", fontsize=8,
    )

    ax_info.set_axis_off()
    ax_info.text(.03, .975, "Trip cost anatomy", transform=ax_info.transAxes, fontsize=16, va="top")
    ax_info.text(.03, .925, f"HK${total:,.1f}", transform=ax_info.transAxes,
                 fontsize=27, color=PALETTE["brick"], va="top")
    ax_info.text(.03, .845,
                 f"{target.person}  •  {time_label(target.departure_s)} departure\n"
                 f"{target.distance/1000:.1f} km executed Car leg  •  {time_label(target.arrival_s)} arrival",
                 transform=ax_info.transAxes, fontsize=8.2, color=PALETTE["muted"], va="top")
    rounded_panel(ax_info, .625, "ENERGY — continuous", target.energy_hkd, PALETTE["brick"], [
        f"{target.distance/1000:.2f} km × HK${energy_rate:.3f}/km",
        "Representative licensed-fleet powertrain proxy",
    ])
    facilities = ", ".join(sorted({p["facility"].replace("_", " ").title() for p in toll_points}))
    rounded_panel(ax_info, .405, "ROAD TOLL — at gate", target.toll_hkd, PALETTE["gold"], [
        facilities,
        "Official typical-weekday private-car rule at actual entry time",
    ])
    rounded_panel(ax_info, .185, "PARKING — at destination", target.parking_hkd, PALETTE["blue"], [
        f"{park_group.replace('_', ' ').title()}  •  TCS zone {zone} ({zone_group(zone).replace('_', ' ').title()})",
        f"{duration_h:.2f} h until the same vehicle's next departure",
    ])
    ax_info.text(.03, .105,
                 "Not included in this trip\nFixed vehicle ownership is retained as a vehicle-day sidecar; it is not allocated per trip.",
                 transform=ax_info.transAxes, fontsize=8.2, color=PALETTE["muted"], va="top",
                 bbox=dict(facecolor="#F7F8F7", edgecolor="#D3D8D6", boxstyle="round,pad=.4"))

    fig.suptitle("Where a private-car trip generates money costs", fontsize=18.5, y=.993)
    fig.text(.5, .944,
             "One complete iteration-49 journey: route energy accumulation, time-specific toll passage and destination parking settlement",
             ha="center", color=PALETTE["muted"], fontsize=10.3)
    add_method_note(
        fig,
        "Executed run6 iteration-49 trip selected deterministically as the median-cost case among complete 8–35 km private-car trips with all three positive components. "
        "Energy is reconstructed from rounded exported distance (run-wide difference 0.003%); toll uses exact LinkEnter time and reconciles exactly; parking follows the runtime TCS-zone/activity/duration proxy. Amounts are HKD, not score utility.",
        y=.009,
    )
    save_figure(fig, args.output_dir, "figure_04_private_car_cost_anatomy")
    plt.close(fig)

    summary = {
        "run_identity": "run3 it.0-40 checkpoint + resume40 run6 it.41-49",
        "iteration": 49,
        "selection_rule": "median total among complete 8-35 km private-car trips with positive energy, toll and parking",
        "trip": {
            "person": str(target.person), "trip_id": str(target.trip_id),
            "vehicle_id": str(target.vehicle_id), "departure_s": float(target.departure_s),
            "arrival_s": float(target.arrival_s), "distance_m_exported": float(target.distance),
            "route_link_count": len(route_links), "energy_hkd": float(target.energy_hkd),
            "toll_hkd": float(target.toll_hkd), "parking_hkd": float(target.parking_hkd),
            "total_hkd": total, "parking_duration_h": float(duration_h),
            "destination_activity_group": park_group, "destination_tcs_zone": int(zone),
            "toll_passages": toll_points,
        },
        "runwide_car_reconciliation": qa,
        "fixed_ownership_allocated_to_trip": False,
    }
    (args.output_dir / "figure_04_private_car_cost_anatomy_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
