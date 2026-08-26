"""Plot an observed household joint-car day from Stage 11 run57.

The figure combines the actual person/vehicle event chain with the screened
candidate record and the retained Walk baseline.  IDs, times, coordinates,
scores, and link sequences come from immutable release57/run57 artifacts.
"""

from __future__ import annotations

import argparse
import gzip
from pathlib import Path
import xml.etree.ElementTree as ET

import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch
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

HOUSEHOLD_ID = "hk_hh_1251667"
DRIVER_ID = "hk_person_03051340"
PASSENGER_ID = "hk_person_03051341"
VEHICLE_ID = "hk_vehicle_0210204"

# Retained baseline route for the passenger's AM Walk alternative.
BASELINE_WALK_LINKS = """
road_272574_0_r road_101074_0_r road_101071_0_f road_266865_0_f
road_101076_0_r road_101070_0_f road_101078_0_f road_101079_0_f
road_164507_0_f road_100755_0_f road_100756_0_f road_101057_0_r
road_101056_0_f road_103243_0_f road_104029_0_f road_103683_0_f
road_103677_0_f road_111003_0_f road_111002_0_f road_103678_0_f
road_103644_0_f road_103546_0_f road_103157_0_f road_103193_0_f
road_103545_0_f road_103973_0_f road_104030_0_f road_103675_0_f
""".split()

# Actual run57 LinkEnter sequence for the household vehicle's first tour.  The
# start link is inserted explicitly because MATSim emits no LinkEnter for it.
# The route passes the passenger's school drop-off link, then continues to the
# driver's workplace.
MORNING_VEHICLE_LINKS = """
road_272574_0_r road_101074_0_r road_101071_0_f road_266865_0_f
road_101076_0_r road_101070_0_f road_101078_0_f road_101079_0_f
road_164507_0_f road_100755_0_f road_100756_0_f road_101057_0_r
road_101056_0_f road_103243_0_f road_104029_0_f road_103683_0_f
road_103677_0_f road_111003_0_f road_111002_0_f road_103678_0_f
road_103644_0_f road_103546_0_f road_103157_0_f road_103193_0_f
road_103545_0_f road_103973_0_f road_104030_0_f road_103675_0_f
road_104032_0_f road_164660_0_f road_164661_0_f road_164659_0_f
road_164658_0_f road_164657_0_f road_103860_0_f road_103034_0_f
road_103867_0_f road_103850_0_f road_296651_0_f road_102847_0_f
road_103467_0_f road_103468_0_f road_103820_0_f road_102812_0_f
road_103815_0_f road_102630_0_f road_102633_0_f road_103798_0_f
road_102673_0_f road_102356_0_f road_102353_0_f road_102372_0_r
road_102374_0_r road_102365_0_f road_102366_0_f road_102375_0_r
road_102350_0_r road_102330_0_f road_111007_0_f road_102314_0_f
road_102336_0_f road_102337_0_f road_102335_0_f road_102308_0_f
road_102334_0_f road_102347_0_r road_102346_0_r road_103753_0_f
road_103754_0_f road_273303_0_f road_104613_0_f road_104620_0_r
road_104622_0_r road_104619_0_f road_104604_0_f road_104617_0_f
road_104482_0_f road_104609_0_f road_111896_0_f road_104479_0_f
road_260733_0_f road_104614_0_f road_104990_0_f road_104616_0_f
road_105208_0_f road_105129_0_f road_104324_0_f road_261323_0_f
road_261324_0_f road_105057_0_f road_5341_0_f road_5687_0_f
road_3293_0_f road_1601_0_f road_3203_0_f road_65373_0_f
road_3088_0_f road_4739_0_f road_4348_0_f road_4735_0_f
road_2879_0_f road_4301_0_f road_4950_0_f road_5319_0_f
road_5135_0_f road_2758_0_f road_2374_0_f road_1966_0_f
road_115564_0_f road_798_0_f road_115562_0_f road_4123_0_f
road_3165_0_f road_3913_0_f road_2311_0_f road_4056_0_f
road_4058_0_f road_5008_0_f road_5360_0_f road_2448_0_f
road_5773_0_f road_1435_0_f road_5003_0_f road_5264_0_f
road_2454_0_f road_3070_0_f road_4383_0_f road_4381_0_f
road_2312_0_f road_968_0_f road_177_0_f road_1736_0_f
road_5362_0_f road_5355_0_f road_790_0_f road_2079_0_f
road_3228_0_f road_3992_0_f road_2000_0_r road_755_0_f
road_316_0_f road_3046_0_f road_1871_0_f road_4715_0_f
road_1870_0_r road_1577_0_r road_271789_0_r road_3790_0_r
road_271788_0_r road_4321_0_r road_5236_0_f road_5150_0_f
road_5208_0_f road_1075_0_f road_2175_0_r road_4835_0_r road_4835_0_f
""".split()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", type=Path)
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
    raise FileNotFoundError("Pass --network with the Hong Kong MATSim network.xml.gz")


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


def hhmm(seconds: float) -> str:
    value = int(round(seconds))
    hours, remainder = divmod(value, 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}"


def hhmmss(seconds: float) -> str:
    value = int(round(seconds))
    hours, remainder = divmod(value, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def route_collections(nodes, links):
    morning = [segment(link, nodes, links) for link in MORNING_VEHICLE_LINKS]
    baseline = [segment(link, nodes, links) for link in BASELINE_WALK_LINKS]
    school_index = MORNING_VEHICLE_LINKS.index("road_103675_0_f") + 1
    shared = morning[:school_index]
    driver_only = morning[school_index:]
    return morning, shared, driver_only, baseline


def plot_map(ax, nodes, links) -> None:
    morning, shared, driver_only, baseline = route_collections(nodes, links)
    focus = np.array([point for line in morning for point in line])
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
    ax.add_collection(LineCollection(background, colors=PALETTE["grid"], linewidths=0.31, alpha=0.62))
    ax.add_collection(
        LineCollection(baseline, colors=PALETTE["green"], linewidths=1.55, linestyles="dashed", alpha=0.8, zorder=2)
    )
    ax.add_collection(
        LineCollection(driver_only, colors=PALETTE["brick"], linewidths=2.3, alpha=0.9, zorder=3)
    )
    ax.add_collection(
        LineCollection(shared, colors=PALETTE["brick_light"], linewidths=4.1, alpha=0.98, zorder=4)
    )

    points = [
        ((213280.39, 2471447.471), "HOME\npickup", "o", PALETTE["blue"], (10, -2), "left"),
        ((212777.564, 2471775.452), "SCHOOL\ndrop-off", "D", PALETTE["gold"], (-10, 10), "right"),
        ((205105.046, 2466603.313), "WORK", "s", PALETTE["brick"], (7, 7), "left"),
    ]
    for xy, label, marker, color, offset, align in points:
        ax.scatter(*xy, s=70, marker=marker, color=color, edgecolor="white", linewidth=1.0, zorder=6)
        ax.annotate(label, xy, xytext=offset, textcoords="offset points", fontsize=8.2,
                    ha=align, weight="bold", color=PALETTE["text"], zorder=7)

    ax.set_xlim(bounds[0], bounds[1])
    ax.set_ylim(bounds[2], bounds[3])
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title("Morning vehicle path: home → school → work", loc="left", fontsize=12.5, pad=8)
    ax.text(
        0.01,
        0.01,
        "EPSG:32650  |  thick: passenger onboard  |  thin: driver alone  |  dashed: retained Walk baseline",
        transform=ax.transAxes,
        fontsize=7.6,
        color=PALETTE["muted"],
        va="bottom",
    )


def lane_segment(ax, y, start, end, color, width=6.0, label=None, zorder=3):
    ax.hlines(y, start, end, color=color, lw=width, zorder=zorder)
    if label:
        ax.text((start + end) / 2, y + 0.11, label, ha="center", va="bottom", fontsize=7.7, color=PALETTE["text"])


def plot_timeline(ax) -> None:
    # Exact run57 events.
    p_depart_am, driver_depart_am = 21407, 21408
    driver_enter_am, p_enter_am = 21472, 21473
    p_drop_am, driver_work = 21604, 22596
    p_depart_pm, driver_depart_pm = 55192, 55193
    driver_enter_pm, p_enter_pm = 55242, 56095
    p_home, driver_home = 56347, 56348

    y_driver, y_passenger, y_vehicle = 2.65, 1.65, 0.65
    muted_activity = PALETTE["land"]
    parked = PALETTE["grid"]

    # A documented broken time axis gives the two short joint episodes enough
    # room while retaining the long work/school interval as a compressed band.
    def tx(seconds: float) -> float:
        if seconds <= 23000:
            return 0.03 + (seconds - 21350) / (23000 - 21350) * 0.28
        if seconds < 55000:
            return 0.35 + (seconds - 23000) / (55000 - 23000) * 0.26
        return 0.66 + (seconds - 55000) / (56500 - 55000) * 0.31

    def lane(y, start, end, color, width=6.0, label=None, zorder=3):
        lane_segment(ax, y, tx(start), tx(end), color, width, label, zorder)

    # Driver lane.
    lane(y_driver, p_depart_am, driver_depart_am, muted_activity, 7)
    lane(y_driver, driver_depart_am, driver_enter_am, PALETTE["green"], 6)
    lane(y_driver, driver_enter_am, p_drop_am, PALETTE["brick_light"], 8)
    lane(y_driver, p_drop_am, driver_work, PALETTE["brick"], 6, "drive to work")
    lane(y_driver, driver_work, driver_depart_pm, muted_activity, 7, "work")
    lane(y_driver, driver_depart_pm, driver_enter_pm, PALETTE["green"], 6)
    lane(y_driver, driver_enter_pm, p_enter_pm, PALETTE["brick"], 6, "drive to school")
    lane(y_driver, p_enter_pm, driver_home, PALETTE["brick_light"], 8)

    # Passenger lane.
    lane(y_passenger, p_depart_am, p_enter_am, PALETTE["gold"], 6)
    lane(y_passenger, p_enter_am, p_drop_am, PALETTE["brick_light"], 8)
    lane(y_passenger, p_drop_am, p_depart_pm, muted_activity, 7, "school")
    lane(y_passenger, p_depart_pm, p_enter_pm, PALETTE["gold"], 6, "wait 15:03")
    lane(y_passenger, p_enter_pm, p_home, PALETTE["brick_light"], 8)

    # Vehicle lane.
    lane(y_vehicle, p_depart_am, driver_enter_am, parked, 7)
    lane(y_vehicle, driver_enter_am, p_drop_am, PALETTE["brick_light"], 8)
    lane(y_vehicle, p_drop_am, driver_work, PALETTE["brick"], 6)
    lane(y_vehicle, driver_work, driver_enter_pm, parked, 7, "parked at work")
    lane(y_vehicle, driver_enter_pm, p_enter_pm, PALETTE["brick"], 6)
    lane(y_vehicle, p_enter_pm, driver_home, PALETTE["brick_light"], 8)

    for start_x, end_x, label in [
        (p_enter_am, p_drop_am, "05:57:53 both onboard\n06:00:04 student alights"),
        (p_enter_pm, p_home, "15:34:55 pickup\n15:39:07 home"),
    ]:
        x = (tx(start_x) + tx(end_x)) / 2
        ax.axvspan(tx(start_x), tx(end_x), color=PALETTE["brick_light"], alpha=0.10, zorder=0)
        ax.text(x, 3.22, label, ha="center", va="bottom", fontsize=7.8, color=PALETTE["muted"])

    for break_x in (0.33, 0.635):
        ax.text(break_x, 0.04, "//", transform=ax.get_xaxis_transform(), ha="center",
                va="bottom", color=PALETTE["boundary"], fontsize=12)

    ax.set_yticks([y_driver, y_passenger, y_vehicle], ["Driver", "Student", "Vehicle"])
    ax.set_xlim(0, 1)
    ax.set_ylim(0.2, 3.65)
    tick_seconds = [21604, 22596, 55193, 56095, 56347]
    ax.set_xticks([tx(value) for value in tick_seconds], [hhmm(value) for value in tick_seconds])
    ax.grid(axis="x", color=PALETTE["grid"], lw=0.6, zorder=0)
    ax.set_xlabel("Broken event-time axis (HH:MM); // compresses the long activity interval")
    ax.spines[["top", "right"]].set_visible(False)
    ax.set_title("One household vehicle binds two people in event time", loc="left", fontsize=12.5, pad=8)


def draw_plan_strip(ax) -> None:
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.set_title("Selected physical plan versus the preserved baseline", loc="left", fontsize=12.5, pad=8)

    box_kw = dict(boxstyle="round,pad=0.012,rounding_size=0.012", ec=PALETTE["grid"], lw=0.8)
    ax.add_patch(FancyBboxPatch((0.01, 0.54), 0.98, 0.35, fc=PALETTE["land_alt"], **box_kw))
    ax.add_patch(FancyBboxPatch((0.01, 0.08), 0.98, 0.35, fc=PALETTE["land_alt"], **box_kw))

    ax.text(0.035, 0.79, "PRESERVED BASELINE", fontsize=8.1, weight="bold", color=PALETTE["green"])
    ax.text(0.035, 0.64, "Home  ── Walk 23:47 ──  School  ── Walk 41:59 ──  Home",
            fontsize=10.0, color=PALETTE["text"])
    ax.text(0.965, 0.79, "plan score 128.13", ha="right", fontsize=8.5, color=PALETTE["muted"])

    ax.text(0.035, 0.33, "SELECTED JOINT COMPOSITE", fontsize=8.1, weight="bold", color=PALETTE["brick"])
    ax.text(0.035, 0.18, "Home  ══ shared car ══  School  ··· driver continues to Work",
            fontsize=10.0, color=PALETTE["text"])
    ax.text(0.965, 0.33, "plan score 133.41", ha="right", fontsize=8.5, color=PALETTE["muted"])

    ax.text(
        0.50,
        0.005,
        "Screened candidate: original passenger mode Walk · +350.6 m driver detour · detour ratio 1.037",
        ha="center",
        va="bottom",
        fontsize=7.9,
        color=PALETTE["muted"],
    )


def main() -> None:
    args = parse_args()
    apply_progress_report_style()
    network_path = resolve_network(args.network)
    nodes, links = read_network(network_path)
    required = set(MORNING_VEHICLE_LINKS) | set(BASELINE_WALK_LINKS)
    missing = sorted(required - set(links))
    if missing:
        raise KeyError(f"{len(missing)} observed route links are absent from {network_path}: {missing[:8]}")

    fig = plt.figure(figsize=(14.2, 8.25))
    grid = fig.add_gridspec(
        2,
        2,
        width_ratios=(0.43, 0.57),
        height_ratios=(0.66, 0.34),
        left=0.055,
        right=0.975,
        bottom=0.105,
        top=0.865,
        wspace=0.15,
        hspace=0.30,
    )
    map_ax = fig.add_subplot(grid[:, 0])
    time_ax = fig.add_subplot(grid[0, 1])
    strip_ax = fig.add_subplot(grid[1, 1])
    plot_map(map_ax, nodes, links)
    plot_timeline(time_ax)
    draw_plan_strip(strip_ax)

    fig.suptitle("A household car becomes a shared physical resource", fontsize=18, y=0.962)
    fig.text(
        0.5,
        0.918,
        f"Observed Stage 11 run57 day for household {HOUSEHOLD_ID}  |  {VEHICLE_ID}  |  4,003 selected · 3,895 completed",
        ha="center",
        fontsize=10.5,
        color=PALETTE["muted"],
    )
    add_method_note(
        fig,
        "Evidence: release57 household candidate registry plus run57 iteration-1 selected plans and person/vehicle events; map uses the observed AM LinkEnter sequence.\n"
        f"Driver {DRIVER_ID}; student {PASSENGER_ID}. Scores are MATSim utilities, not money. The deterministic model choice is not an observed household preference or probability. "
        "run57 is a frozen-innovation, unlimited-ordinary-PT mechanical gate rather than production equilibrium.",
        y=0.013,
    )
    png, pdf = save_figure(fig, args.output_dir, "figure03_household_joint_car_timeline")
    plt.close(fig)
    print(png)
    print(pdf)


if __name__ == "__main__":
    main()
