"""Plot the observed run56/run57 school-bus walk-clock repair case.

The highlighted person, route, links, and event times are transcribed from the
immutable Stage 11 run56/run57 server outputs.  The script reads only the local
MATSim road network to recover link geometry; it does not require the large
event files in order to reproduce the presentation figure.
"""

from __future__ import annotations

import argparse
import gzip
from pathlib import Path
import xml.etree.ElementTree as ET

import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter, MultipleLocator
import numpy as np

from progress_report_figure_style import (
    PALETTE,
    add_method_note,
    apply_progress_report_style,
    save_figure,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = PROJECT_ROOT / "runs/hongkong/outputs/progress_report_figures_20260824"
NETWORK_RELATIVE = Path(
    "data/transit/hongkong/processed/"
    "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_ferry_core_v1_cap010/"
    "network.xml.gz"
)

PERSON_ID = "hk_person_00632810"
VEHICLE_ID = "veh_school_bus_v6_SBP_540234000_003_R009"
ROUTE_ID = "school_bus_v6_SBP_540234000_003_R009_AM"

# Exact selected-plan route in run56/run57.  The physical event stream begins
# on the second link because MATSim does not emit a LinkEnter for the start link.
WALK_LINKS = """
road_18_0_f road_788_0_f road_2641_0_f road_1734_0_f road_3710_0_f
road_263_0_f road_772_0_f road_4230_0_f road_2701_0_f road_1535_0_f
road_46_0_f road_529_0_f road_4117_0_f road_686_0_r road_2357_0_r
road_2558_0_r road_3171_0_r road_3247_0_r road_115838_0_r
road_5073_0_r road_5073_0_f
""".split()

# Observed run57 AM vehicle LinkEnter sequence, from the selected pickup to the
# school alighting link.  Start/end links are included explicitly.
BUS_LINKS = """
road_5073_0_f road_115838_0_f road_3247_0_f road_588_0_f road_1994_0_f
road_2009_0_f road_686_0_f road_4412_0_f road_4408_0_r road_3934_0_f
road_777_0_f road_1948_0_f road_2456_0_f road_3506_0_f road_3263_0_f
road_5660_0_f road_5535_0_f road_1711_0_f road_2164_0_f road_272566_0_f
road_3398_0_f road_186_0_f road_2679_0_f road_273170_0_f road_3840_0_f
road_2711_0_f road_272003_0_f road_273051_0_f road_4593_0_f road_5037_0_f
road_1519_0_f road_119291_0_f road_119292_0_f road_3851_0_f road_476_0_f
road_1468_0_f road_3598_0_f road_2677_0_f road_2791_0_f road_3742_0_f
road_44_0_f road_5468_0_f road_704_0_f road_284066_0_f road_4914_0_f
road_3626_0_f road_3396_0_r road_284068_0_f road_2788_0_f road_1123_0_f
road_852_0_r road_2961_0_f road_2399_0_f road_1124_0_f road_3638_0_r
road_5791_0_f road_3025_0_f road_2769_0_f road_3194_0_f road_802_0_f
road_3409_0_r road_851_0_r road_395_0_f road_3676_0_f road_1895_0_f
road_3389_0_r road_3659_0_f road_4432_0_f road_4431_0_f road_63649_0_r
road_63650_0_r road_5036_0_f road_63652_0_r road_850_0_r road_1066_0_f
road_280603_0_f road_1710_0_r road_63653_0_r road_1053_0_f road_1721_0_r
road_3399_0_r road_2201_0_f road_63647_0_r road_63648_0_r road_3869_0_f
road_542_0_f road_4170_0_f road_5770_0_f road_2638_0_f road_3103_0_f
road_2834_0_f road_2703_0_f road_1276_0_f road_3780_0_f road_3777_0_f
""".split()

RUN56_WALK_EXIT_S = np.array(
    [
        26367, 26403, 26431, 26564, 26578, 26680, 26786, 26829, 26875,
        26886, 26993, 27033, 27092, 27138, 27161, 27184, 27208, 27227,
        27362, 27497,
    ],
    dtype=float,
)
RUN57_WALK_EXIT_S = np.array(
    [
        26367, 26403, 26430, 26563, 26577, 26678, 26783, 26825, 26870,
        26880, 26987, 27026, 27084, 27130, 27152, 27175, 27198, 27217,
        27352, 27487,
    ],
    dtype=float,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--network",
        type=Path,
        help="MATSim network.xml(.gz); defaults to the project or canonical F-drive copy.",
    )
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    return parser.parse_args()


def resolve_network(explicit: Path | None) -> Path:
    candidates = [] if explicit is None else [explicit]
    candidates.extend(
        [
            PROJECT_ROOT / NETWORK_RELATIVE,
            Path(r"F:\Matsim\matsim-example-project") / NETWORK_RELATIVE,
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "Hong Kong MATSim network not found; pass --network with network.xml.gz."
    )


def read_network(path: Path) -> tuple[dict[str, tuple[float, float]], dict[str, tuple[str, str]]]:
    nodes: dict[str, tuple[float, float]] = {}
    links: dict[str, tuple[str, str]] = {}
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as stream:
        for _, element in ET.iterparse(stream, events=("end",)):
            tag = element.tag.rsplit("}", 1)[-1]
            if tag == "node":
                nodes[element.attrib["id"]] = (
                    float(element.attrib["x"]),
                    float(element.attrib["y"]),
                )
            elif tag == "link":
                links[element.attrib["id"]] = (
                    element.attrib["from"],
                    element.attrib["to"],
                )
            element.clear()
    return nodes, links


def segment(link_id: str, nodes, links) -> tuple[tuple[float, float], tuple[float, float]]:
    from_id, to_id = links[link_id]
    return nodes[from_id], nodes[to_id]


def hhmmss(seconds: float) -> str:
    value = int(round(seconds))
    hours, remainder = divmod(value, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def plot_map(ax, nodes, links) -> None:
    walk_segments = [segment(link, nodes, links) for link in WALK_LINKS]
    bus_segments = [segment(link, nodes, links) for link in BUS_LINKS]
    focus = np.array([point for line in walk_segments + bus_segments for point in line])
    xmin, ymin = focus.min(axis=0)
    xmax, ymax = focus.max(axis=0)
    pad = max(xmax - xmin, ymax - ymin) * 0.075
    bounds = (xmin - pad, xmax + pad, ymin - pad, ymax + pad)

    background = []
    for link_id in links:
        line = segment(link_id, nodes, links)
        mx = (line[0][0] + line[1][0]) / 2
        my = (line[0][1] + line[1][1]) / 2
        if bounds[0] <= mx <= bounds[1] and bounds[2] <= my <= bounds[3]:
            background.append(line)
    ax.add_collection(
        LineCollection(background, colors=PALETTE["grid"], linewidths=0.34, alpha=0.65, zorder=1)
    )
    ax.add_collection(
        LineCollection(walk_segments, colors=PALETTE["blue"], linewidths=2.5, zorder=4)
    )
    ax.add_collection(
        LineCollection(bus_segments, colors=PALETTE["brick"], linewidths=2.2, alpha=0.88, zorder=3)
    )

    home = (211237.944, 2467883.564)
    stop = (211427.89, 2467506.44)
    school = (215522.902, 2464831.691)
    for xy, label, color, marker, offset in [
        (home, "HOME", PALETTE["blue"], "o", (7, 7)),
        (stop, "PICKUP", PALETTE["gold"], "s", (7, -14)),
        (school, "SCHOOL", PALETTE["brick"], "D", (7, 7)),
    ]:
        ax.scatter(*xy, s=66, marker=marker, color=color, edgecolor="white", linewidth=1.0, zorder=6)
        ax.annotate(
            label,
            xy,
            xytext=offset,
            textcoords="offset points",
            fontsize=8.2,
            color=PALETTE["text"],
            weight="bold",
            zorder=7,
        )

    ax.set_xlim(bounds[0], bounds[1])
    ax.set_ylim(bounds[2], bounds[3])
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title("Observed access walk and school-bus path", loc="left", fontsize=12.5, pad=8)
    ax.text(
        0.01,
        0.01,
        "EPSG:32650  |  blue: 1.66 km access walk  |  brick: AM vehicle path",
        transform=ax.transAxes,
        fontsize=7.8,
        color=PALETTE["muted"],
        va="bottom",
    )


def plot_event_story(ax) -> None:
    start = 26247.0
    vehicle_board = 27494.0
    run56_arrival = 27497.0
    run57_arrival = 27487.0
    alight = 28114.0
    school_arrival = 28353.0

    ax.axvline(vehicle_board, color=PALETTE["gold"], lw=1.25, ls="--", zorder=1)
    ax.text(
        vehicle_board,
        3.20,
        f"vehicle boarding event\n{hhmmss(vehicle_board)}",
        ha="center",
        va="bottom",
        fontsize=8.3,
        color=PALETTE["muted"],
    )

    y56, y57 = 2.38, 1.10
    ax.hlines(y56, start, run56_arrival, color=PALETTE["blue"], lw=5.0)
    ax.scatter([start], [y56], s=46, color=PALETTE["blue"], edgecolor="white", zorder=4)
    ax.scatter([run56_arrival], [y56], s=72, marker="x", color=PALETTE["red"], linewidth=2.2, zorder=5)
    ax.annotate(
        "arrives 3 s after bus\nno boarding; stuck at 30:00",
        (run56_arrival, y56),
        xytext=(-10, 22),
        textcoords="offset points",
        ha="right",
        color=PALETTE["red"],
        fontsize=8.6,
        arrowprops=dict(arrowstyle="-", color=PALETTE["red"], lw=0.9),
    )

    ax.hlines(y57, start, run57_arrival, color=PALETTE["blue"], lw=5.0)
    ax.hlines(y57, run57_arrival, vehicle_board, color=PALETTE["gold"], lw=5.0)
    ax.hlines(y57, vehicle_board, alight, color=PALETTE["brick"], lw=5.0)
    ax.hlines(y57, alight, school_arrival, color=PALETTE["green"], lw=5.0)
    ax.scatter([start, run57_arrival, vehicle_board, alight, school_arrival], [y57] * 5,
               s=[46, 46, 58, 46, 46], color=[PALETTE["blue"], PALETTE["blue"],
               PALETTE["gold"], PALETTE["brick"], PALETTE["green"]],
               edgecolor="white", linewidth=0.9, zorder=5)
    labels = [
        (start, "walk starts\n07:17:27", "left", (0, -20)),
        (run57_arrival, "pickup arrival\n07:38:07", "right", (-10, -20)),
        (alight, "alights\n07:48:34", "right", (-6, -20)),
        (school_arrival, "school\n07:52:33", "right", (0, -36)),
    ]
    for x, label, align, offset in labels:
        ax.annotate(
            label,
            (x, y57),
            xytext=offset,
            textcoords="offset points",
            ha=align,
            va="top",
            fontsize=7.9,
            color=PALETTE["text"],
        )

    ax.text(start - 75, y56, "run56\ninteger callback", ha="right", va="center", fontsize=9.5)
    ax.text(start - 75, y57, "run57\ncontinuous due time", ha="right", va="center", fontsize=9.5)
    ax.set_ylim(0.35, 3.55)
    ax.set_xlim(start - 120, school_arrival + 120)
    ax.xaxis.set_major_locator(MultipleLocator(300))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: hhmmss(value)[:-3]))
    ax.grid(axis="x", color=PALETTE["grid"], lw=0.6, zorder=0)
    ax.set_yticks([])
    ax.set_xlabel("Simulation time (HH:MM)")
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.set_title("Same student, same selected trip: event outcome changes", loc="left", fontsize=12.5, pad=8)

    legend = [
        Line2D([0], [0], color=PALETTE["blue"], lw=4, label="physical walk"),
        Line2D([0], [0], color=PALETTE["gold"], lw=4, label="wait / board"),
        Line2D([0], [0], color=PALETTE["brick"], lw=4, label="school bus"),
        Line2D([0], [0], color=PALETTE["green"], lw=4, label="final walk"),
    ]
    ax.legend(handles=legend, loc="upper left", ncol=2, bbox_to_anchor=(0.0, 0.98))


def plot_drift(ax) -> None:
    crossed_links = np.arange(1, len(RUN56_WALK_EXIT_S) + 1)
    drift = RUN56_WALK_EXIT_S - RUN57_WALK_EXIT_S
    ax.plot(crossed_links, drift, color=PALETTE["brick"], lw=2.0)
    ax.scatter(crossed_links, drift, s=22, color=PALETTE["brick"], edgecolor="white", linewidth=0.6, zorder=3)
    ax.fill_between(crossed_links, 0, drift, color=PALETTE["brick_light"], alpha=0.22)
    ax.annotate(
        "+10 s at pickup",
        (20, 10),
        xytext=(-10, 16),
        textcoords="offset points",
        ha="right",
        fontsize=8.8,
        color=PALETTE["brick"],
        arrowprops=dict(arrowstyle="->", color=PALETTE["brick"], lw=0.9),
    )
    ax.axhline(0, color=PALETTE["boundary"], lw=0.7)
    ax.set_xlim(1, 20)
    ax.set_ylim(-0.6, 11.8)
    ax.set_xticks([1, 5, 10, 15, 20])
    ax.set_yticks([0, 2, 4, 6, 8, 10])
    ax.grid(color=PALETTE["grid"], lw=0.6)
    ax.set_xlabel("Road links completed on the access walk")
    ax.set_ylabel("run56 − run57 arrival time (s)")
    ax.set_title("Per-link rounding accumulates into a missed boarding", loc="left", fontsize=12.5, pad=8)
    ax.spines[["top", "right"]].set_visible(False)


def main() -> None:
    args = parse_args()
    apply_progress_report_style()
    network_path = resolve_network(args.network)
    nodes, links = read_network(network_path)
    missing = sorted((set(WALK_LINKS) | set(BUS_LINKS)) - set(links))
    if missing:
        raise KeyError(f"{len(missing)} observed route links are absent from {network_path}: {missing[:8]}")

    fig = plt.figure(figsize=(13.8, 8.25))
    grid = fig.add_gridspec(
        2,
        2,
        width_ratios=(0.44, 0.56),
        height_ratios=(0.62, 0.38),
        left=0.055,
        right=0.975,
        bottom=0.105,
        top=0.865,
        wspace=0.16,
        hspace=0.33,
    )
    map_ax = fig.add_subplot(grid[:, 0])
    story_ax = fig.add_subplot(grid[0, 1])
    drift_ax = fig.add_subplot(grid[1, 1])
    plot_map(map_ax, nodes, links)
    plot_event_story(story_ax)
    plot_drift(drift_ax)

    fig.suptitle(
        "A 10-second walk-clock repair restores a missed school-bus boarding",
        fontsize=18,
        y=0.962,
    )
    fig.text(
        0.5,
        0.918,
        f"Observed Stage 11 event chain for {PERSON_ID}  |  vehicle {VEHICLE_ID}",
        ha="center",
        fontsize=10.5,
        color=PALETTE["muted"],
    )
    add_method_note(
        fig,
        "Evidence: immutable run56 and run57 iteration-1 events and selected plans; route geometry from the active EPSG:32650 MATSim network.\n"
        "run56: 76 students missed their first selected bus; run57: 1,002/1,002 selected legs departed and boarded correctly. "
        "Unlimited ordinary-PT seats and frozen innovation make this a mechanical validation gate, not production equilibrium or capacity validation.",
        y=0.013,
    )
    png, pdf = save_figure(fig, args.output_dir, "figure02_school_bus_walk_timing_repair")
    plt.close(fig)
    print(png)
    print(pdf)


if __name__ == "__main__":
    main()
