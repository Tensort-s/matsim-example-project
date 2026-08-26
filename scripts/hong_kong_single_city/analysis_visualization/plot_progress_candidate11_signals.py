"""Plot Candidate11 signal coverage and an evidence-backed green-wave corridor.

The figure combines the complete Candidate11 signal-system inventory with one
automatically selected implemented corridor.  It intentionally distinguishes
evidence-backed signal locations from inferred/modelled timing plans.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle

from progress_report_figure_style import (
    PALETTE,
    add_method_note,
    apply_progress_report_style,
    clean_map_axis,
    save_figure,
)


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE = (
    ROOT
    / "runs/hongkong/outputs/progress_report_figures_20260824/source_data"
    / "signal_candidate11"
)
DEFAULT_BOUNDARY = (
    ROOT
    / "runs/hongkong/outputs/progress_report_figures_20260824/source_data"
    / "hong_kong_fixed_link_boundary.geojson"
)
DEFAULT_OUTPUT = (
    ROOT / "runs/hongkong/outputs/progress_report_figures_20260824"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--boundary", type=Path, default=DEFAULT_BOUNDARY)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--corridor-id", default="", help="Optional implemented corridor override")
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_network(path: Path) -> tuple[dict[str, tuple[float, float]], dict[str, dict[str, object]]]:
    opener = gzip.open if path.suffix == ".gz" else open
    nodes: dict[str, tuple[float, float]] = {}
    links: dict[str, dict[str, object]] = {}
    with opener(path, "rb") as handle:
        for _, elem in ET.iterparse(handle, events=("end",)):
            tag = local_name(elem.tag)
            if tag == "node":
                nodes[elem.attrib["id"]] = (float(elem.attrib["x"]), float(elem.attrib["y"]))
            elif tag == "link":
                link_id = elem.attrib["id"]
                links[link_id] = {
                    "from": elem.attrib["from"],
                    "to": elem.attrib["to"],
                    "length": float(elem.attrib.get("length", "nan")),
                }
            elem.clear()
    return nodes, links


def parse_signal_systems(path: Path) -> tuple[dict[str, list[str]], int]:
    systems: dict[str, list[str]] = {}
    movement_count = 0
    current_system = ""
    for event, elem in ET.iterparse(path, events=("start", "end")):
        tag = local_name(elem.tag)
        if event == "start" and tag == "signalSystem":
            current_system = elem.attrib["id"]
            systems[current_system] = []
        elif event == "end" and tag == "signal":
            systems[current_system].append(elem.attrib["linkIdRef"])
            movement_count += sum(1 for child in elem.iter() if local_name(child.tag) == "toLink")
            elem.clear()
        elif event == "end" and tag == "signalSystem":
            current_system = ""
            elem.clear()
    return systems, movement_count


def parse_signal_group_count(path: Path) -> int:
    count = 0
    for _, elem in ET.iterparse(path, events=("end",)):
        if local_name(elem.tag) == "signalGroup":
            count += 1
        elem.clear()
    return count


def parse_control_plan(
    path: Path, systems: set[str], plan_id: str, group_by_system: dict[str, str]
) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    tree = ET.parse(path)
    for system in tree.getroot():
        if local_name(system.tag) != "signalSystem":
            continue
        system_id = system.attrib.get("refId", "")
        if system_id not in systems:
            continue
        target_group = group_by_system[system_id]
        for plan in system.iter():
            if local_name(plan.tag) != "signalPlan" or plan.attrib.get("id") != plan_id:
                continue
            cycle = next(float(x.attrib["sec"]) for x in plan if local_name(x.tag) == "cycleTime")
            offset = next(float(x.attrib["sec"]) for x in plan if local_name(x.tag) == "offset")
            for settings in plan:
                if local_name(settings.tag) != "signalGroupSettings" or settings.attrib.get("refId") != target_group:
                    continue
                onset = next(float(x.attrib["sec"]) for x in settings if local_name(x.tag) == "onset")
                dropping = next(float(x.attrib["sec"]) for x in settings if local_name(x.tag) == "dropping")
                result[system_id] = {
                    "cycle": cycle,
                    "offset": offset,
                    "onset": onset,
                    "dropping": dropping,
                }
    missing = systems - result.keys()
    if missing:
        raise ValueError(f"Missing coordinated green windows: {sorted(missing)}")
    return result


def system_coordinates(
    systems: dict[str, list[str]], nodes: dict[str, tuple[float, float]], links: dict[str, dict[str, object]]
) -> dict[str, tuple[float, float]]:
    coordinates: dict[str, tuple[float, float]] = {}
    for system_id, link_ids in systems.items():
        points = []
        for link_id in link_ids:
            link = links.get(link_id)
            if link is not None and link["to"] in nodes:
                points.append(nodes[str(link["to"])])
        if points:
            coordinates[system_id] = tuple(np.mean(np.asarray(points), axis=0))
    return coordinates


def link_segments(
    link_ids: list[str], nodes: dict[str, tuple[float, float]], links: dict[str, dict[str, object]]
) -> list[list[tuple[float, float]]]:
    segments = []
    for link_id in link_ids:
        link = links.get(link_id)
        if link is None:
            continue
        start = nodes.get(str(link["from"]))
        end = nodes.get(str(link["to"]))
        if start is not None and end is not None:
            segments.append([start, end])
    return segments


def choose_corridor(registry: list[dict[str, str]], override: str) -> dict[str, str]:
    implemented = [row for row in registry if row["status"] == "implemented"]
    if override:
        matches = [row for row in implemented if row["corridor_id"] == override]
        if not matches:
            raise ValueError(f"Corridor is not implemented: {override}")
        return matches[0]
    eligible = [row for row in implemented if int(row["signal_system_count"]) >= 4]
    return max(eligible, key=lambda row: float(row["value_score_sum_mean_directional_pcu_h"]))


def choose_peak_bin(rows: list[dict[str, str]], corridor_id: str) -> dict[str, str]:
    active = [
        row
        for row in rows
        if row["corridor_id"] == corridor_id and row["selected_direction"]
    ]
    return max(
        active,
        key=lambda row: float(row["forward_mean_q_pcu_h"]) + float(row["reverse_mean_q_pcu_h"]),
    )


def ordered_corridor(
    corridor_links: list[dict[str, str]], corridor_id: str, direction: str
) -> tuple[list[str], list[float], list[str]]:
    rows = sorted(
        [
            row
            for row in corridor_links
            if row["corridor_id"] == corridor_id and row["direction"] == direction
        ],
        key=lambda row: int(row["sequence"]),
    )
    systems = [rows[0]["upstream_signal_system_id"]] + [row["downstream_signal_system_id"] for row in rows]
    distances = [0.0]
    path_links: list[str] = []
    for row in rows:
        distances.append(distances[-1] + float(row["block_length_m"]))
        path_links.extend([part for part in row["path_link_ids"].split("|") if part])
    return systems, distances, path_links


def green_intervals(plan: dict[str, float], horizon: float) -> list[tuple[float, float]]:
    cycle = plan["cycle"]
    start_phase = (plan["offset"] + plan["onset"]) % cycle
    end_phase = (plan["offset"] + plan["dropping"]) % cycle
    intervals: list[tuple[float, float]] = []
    for base in np.arange(-cycle, horizon + cycle, cycle):
        if end_phase > start_phase:
            candidates = [(base + start_phase, base + end_phase)]
        else:
            candidates = [(base + start_phase, base + cycle), (base, base + end_phase)]
        for start, end in candidates:
            clipped = (max(0.0, start), min(horizon, end))
            if clipped[1] > clipped[0]:
                intervals.append(clipped)
    return intervals


def main() -> int:
    args = parse_args()
    source = args.source_dir.resolve()
    boundary = gpd.read_file(args.boundary)
    if boundary.crs is None:
        boundary = boundary.set_crs("EPSG:32650")
    elif str(boundary.crs).upper() != "EPSG:32650":
        boundary = boundary.to_crs("EPSG:32650")

    registry = read_csv(source / "signal_corridor_registry.csv")
    corridor_rows = read_csv(source / "signal_corridor_links.csv")
    direction_rows = read_csv(source / "tod_corridor_direction_15min.csv")
    offset_rows = read_csv(source / "tod_corridor_offsets.csv")
    selected = choose_corridor(registry, args.corridor_id)
    peak = choose_peak_bin(direction_rows, selected["corridor_id"])
    direction = peak["selected_direction"]
    ordered_systems, cumulative_m, corridor_path_ids = ordered_corridor(
        corridor_rows, selected["corridor_id"], direction
    )

    nodes, links = parse_network(source / "network_signal_capacity_deconvolved.xml.gz")
    signal_links, movement_count = parse_signal_systems(source / "signal_systems.xml")
    group_count = parse_signal_group_count(source / "signal_groups.xml")
    coordinates = system_coordinates(signal_links, nodes, links)
    if len(coordinates) != len(signal_links):
        raise ValueError("Some Candidate11 signal systems could not be geolocated")

    peak_index = int(peak["time_bin_index"])
    plan_id = f"tod_{peak_index:02d}"
    peak_offsets = {
        row["signal_system_id"]: row
        for row in offset_rows
        if row["corridor_id"] == selected["corridor_id"]
        and int(row["time_bin_index"]) == peak_index
    }
    group_by_system = {
        system: peak_offsets[system]["coordinated_signal_group_id"] for system in ordered_systems
    }
    plans = parse_control_plan(
        source / "signal_control.xml", set(ordered_systems), plan_id, group_by_system
    )

    implemented = [row for row in registry if row["status"] == "implemented"]
    implemented_systems = {
        system
        for row in implemented
        for system in row["signal_system_ids"].split("|")
        if system
    }
    all_road_segments = link_segments(list(links), nodes, links)
    corridor_segments = link_segments(corridor_path_ids, nodes, links)

    apply_progress_report_style()
    fig = plt.figure(figsize=(15.2, 10.2))
    grid = fig.add_gridspec(
        2, 2, width_ratios=(1.52, 1.0), height_ratios=(1.0, 1.0),
        left=0.035, right=0.98, top=0.86, bottom=0.102, wspace=0.07, hspace=0.19
    )
    ax_global = fig.add_subplot(grid[:, 0])
    ax_zoom = fig.add_subplot(grid[0, 1])
    ax_wave = fig.add_subplot(grid[1, 1])

    fig.suptitle("Hong Kong Candidate11 traffic signals: coverage and coordinated progression", y=0.966)
    fig.text(
        0.5, 0.905,
        "Evidence-backed junction locations, modelled time-of-day plans, and one representative green-wave corridor",
        ha="center", va="center", color=PALETTE["muted"], fontsize=10.5,
    )

    boundary.plot(ax=ax_global, facecolor=PALETTE["land"], edgecolor=PALETTE["boundary"], linewidth=0.65, zorder=0)
    ax_global.add_collection(LineCollection(all_road_segments, colors=PALETTE["grid"], linewidths=0.16, alpha=0.50, zorder=1))
    ordinary = np.asarray([coordinates[key] for key in coordinates if key not in implemented_systems])
    coordinated = np.asarray([coordinates[key] for key in implemented_systems])
    selected_xy = np.asarray([coordinates[key] for key in ordered_systems])
    ax_global.scatter(ordinary[:, 0], ordinary[:, 1], s=4.5, color=PALETTE["blue_light"], alpha=0.72, linewidth=0, zorder=3)
    ax_global.scatter(coordinated[:, 0], coordinated[:, 1], s=11, color=PALETTE["brick_light"], alpha=0.88, linewidth=0, zorder=4)
    ax_global.scatter(selected_xy[:, 0], selected_xy[:, 1], s=36, color=PALETTE["brick"], edgecolor="white", linewidth=0.65, zorder=5)
    minx, miny, maxx, maxy = boundary.total_bounds
    ax_global.set_xlim(minx - 1500, maxx + 1500)
    ax_global.set_ylim(miny - 1500, maxy + 1500)
    clean_map_axis(ax_global)
    ax_global.set_title("A  Full Candidate11 distribution", loc="left", fontsize=12.2, pad=6)
    legend = [
        Line2D([], [], marker="o", linestyle="", color=PALETTE["blue_light"], markersize=5, label=f"Other signal systems ({len(signal_links):,} total)"),
        Line2D([], [], marker="o", linestyle="", color=PALETTE["brick_light"], markersize=6, label=f"Implemented corridor systems ({len(implemented_systems)})"),
        Line2D([], [], marker="o", linestyle="", color=PALETTE["brick"], markersize=7, label=f"Representative {selected['corridor_id'].replace('_', ' ')}"),
    ]
    ax_global.legend(handles=legend, loc="upper right", frameon=True, borderpad=0.65)
    ax_global.text(
        0.015, 0.018,
        f"{len(signal_links):,} systems  ·  {group_count:,} groups  ·  {movement_count:,} controlled turns\n"
        f"{len(implemented):,} implemented corridors; {len(implemented_systems):,} corridor systems",
        transform=ax_global.transAxes, va="bottom", ha="left", fontsize=8.8, color=PALETTE["text"],
        bbox=dict(facecolor="white", edgecolor=PALETTE["grid"], linewidth=0.6, alpha=0.93, boxstyle="square,pad=0.45"),
    )

    corridor_points = np.asarray([coordinates[key] for key in ordered_systems])
    pad = max(260.0, 0.35 * max(np.ptp(corridor_points[:, 0]), np.ptp(corridor_points[:, 1])))
    xmin, ymin = corridor_points.min(axis=0) - pad
    xmax, ymax = corridor_points.max(axis=0) + pad
    local_ids = []
    for link_id, link in links.items():
        a = nodes[str(link["from"])]
        b = nodes[str(link["to"])]
        if max(a[0], b[0]) >= xmin and min(a[0], b[0]) <= xmax and max(a[1], b[1]) >= ymin and min(a[1], b[1]) <= ymax:
            local_ids.append(link_id)
    ax_zoom.add_collection(LineCollection(link_segments(local_ids, nodes, links), colors=PALETTE["grid"], linewidths=0.7, alpha=0.85, zorder=1))
    ax_zoom.add_collection(LineCollection(corridor_segments, colors=PALETTE["brick"], linewidths=3.3, alpha=0.88, zorder=3))
    ax_zoom.plot(corridor_points[:, 0], corridor_points[:, 1], color=PALETTE["brick"], linewidth=1.4, zorder=3)
    ax_zoom.scatter(corridor_points[:, 0], corridor_points[:, 1], s=92, color=PALETTE["blue"], edgecolor="white", linewidth=1.0, zorder=4)
    for index, (system_id, (x, y)) in enumerate(zip(ordered_systems, corridor_points, strict=True), start=1):
        ax_zoom.text(x, y, str(index), ha="center", va="center", color="white", fontsize=8.4, zorder=5)
        ax_zoom.annotate(
            system_id.split("__")[-1], (x, y), xytext=(5, 7), textcoords="offset points",
            fontsize=7.4, color=PALETTE["text"], zorder=5,
        )
    if len(corridor_points) >= 2:
        ax_zoom.annotate(
            "", xy=corridor_points[1], xytext=corridor_points[0],
            arrowprops=dict(arrowstyle="-|>", color=PALETTE["brick"], lw=2.0, shrinkA=11, shrinkB=11), zorder=6,
        )
    ax_zoom.set_xlim(xmin, xmax)
    ax_zoom.set_ylim(ymin, ymax)
    clean_map_axis(ax_zoom)
    flow = max(float(peak["forward_mean_q_pcu_h"]), float(peak["reverse_mean_q_pcu_h"]))
    ax_zoom.set_title(
        f"B  Representative corridor: {selected['corridor_id'].replace('_', ' ')}",
        loc="left", fontsize=12.2, pad=6,
    )
    ax_zoom.text(
        0.02, 0.02,
        f"Peak coordinated bin {peak['time_bin']} · {direction} direction · {flow:,.0f} mean PCU/h\n"
        f"{len(ordered_systems)} systems across {cumulative_m[-1]:.0f} m; arrows follow the selected progression",
        transform=ax_zoom.transAxes, ha="left", va="bottom", fontsize=8.2, color=PALETTE["muted"],
    )

    horizon = 120.0
    for index, (system_id, distance) in enumerate(zip(ordered_systems, cumulative_m, strict=True), start=1):
        ax_wave.axvline(distance, color=PALETTE["grid"], linewidth=0.75, zorder=0)
        for start, end in green_intervals(plans[system_id], horizon):
            ax_wave.add_patch(
                Rectangle((distance - 4.3, start), 8.6, end - start, facecolor=PALETTE["blue_light"], edgecolor="none", alpha=0.82, zorder=2)
            )

    first_intervals = green_intervals(plans[ordered_systems[0]], horizon)
    start_time = first_intervals[0][0] + 0.25 * (first_intervals[0][1] - first_intervals[0][0])
    progression_times = [0.0]
    direction_link_rows = sorted(
        [row for row in corridor_rows if row["corridor_id"] == selected["corridor_id"] and row["direction"] == direction],
        key=lambda row: int(row["sequence"]),
    )
    for row in direction_link_rows:
        progression_times.append(progression_times[-1] + float(row["freeflow_travel_time_s"]))
    vehicle_t = np.asarray(progression_times) + start_time
    ax_wave.plot(cumulative_m, vehicle_t, color=PALETTE["brick"], linewidth=2.1, marker="o", markersize=4.2, zorder=4, label="Design-speed vehicle trajectory")
    ax_wave.plot(cumulative_m, vehicle_t + plans[ordered_systems[0]]["cycle"], color=PALETTE["brick"], linewidth=1.5, alpha=0.62, zorder=4)
    ax_wave.set_xlim(-12, cumulative_m[-1] + 12)
    ax_wave.set_ylim(0, horizon)
    ax_wave.set_xlabel("Distance along selected direction (m)")
    ax_wave.set_ylabel("Seconds from cycle reference")
    ax_wave.set_xticks(cumulative_m)
    ax_wave.set_xticklabels(
        [f"{index}\n{value:.0f}" for index, value in enumerate(cumulative_m, start=1)]
    )
    ax_wave.set_yticks(np.arange(0, horizon + 1, 20))
    ax_wave.grid(axis="y", color=PALETTE["grid"], linewidth=0.6, alpha=0.75)
    ax_wave.set_title("C  Time–space green-wave diagram", loc="left", fontsize=12.2, pad=6)
    ax_wave.legend(
        handles=[
            Line2D([], [], color=PALETTE["blue_light"], linewidth=7, label="Coordinated green window"),
            Line2D([], [], color=PALETTE["brick"], linewidth=2, marker="o", markersize=4, label="Design-speed trajectory"),
        ],
        loc="upper right", frameon=True,
    )
    offsets = [int(float(peak_offsets[system]["implemented_offset_s"])) for system in ordered_systems]
    ax_wave.text(
        0.015, 0.025,
        "Fixed offsets along direction: " + " → ".join(f"{value}s" for value in offsets),
        transform=ax_wave.transAxes, ha="left", va="bottom", fontsize=8.2, color=PALETTE["muted"],
    )

    add_method_note(
        fig,
        "Candidate11 safe-boundary control; EPSG:32650. Signal locations and controlled turns come from the compiled MATSim package. "
        "Cycle, green split, TOD plan and corridor offsets are modelled research candidates, not observed Hong Kong signal timings.\n"
        "Representative corridor is selected reproducibly as the highest-value implemented corridor with at least four systems; the displayed bin has its largest coordinated directional flow.",
        y=0.008,
    )
    png, pdf = save_figure(fig, args.output_dir, "figure_a_candidate11_signals_greenwave", dpi=260)
    plt.close(fig)

    provenance = {
        "schema_version": "progress_report_candidate11_signal_figure_v1",
        "candidate_status": "research_candidate_not_production_adopted",
        "source_directory": str(source),
        "signal_system_count": len(signal_links),
        "signal_group_count": group_count,
        "controlled_turn_count": movement_count,
        "implemented_corridor_count": len(implemented),
        "implemented_corridor_system_count": len(implemented_systems),
        "representative_corridor": selected["corridor_id"],
        "representative_direction": direction,
        "representative_time_bin": peak["time_bin"],
        "representative_plan_id": plan_id,
        "representative_system_ids": ordered_systems,
        "representative_cumulative_distance_m": cumulative_m,
        "representative_fixed_offsets_s": offsets,
        "outputs": [str(png), str(pdf)],
    }
    metadata_path = args.output_dir / "figure_a_candidate11_signals_greenwave_provenance.json"
    metadata_path.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(provenance, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
