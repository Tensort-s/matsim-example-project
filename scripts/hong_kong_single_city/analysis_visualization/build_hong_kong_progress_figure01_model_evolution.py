"""Build progress-report Figure 1: evolution to cost-aware physical execution."""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch

from progress_report_figure_style import (
    MODE_COLORS,
    PALETTE,
    add_method_note,
    apply_progress_report_style,
    clean_map_axis,
    save_figure,
)


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DEFAULT_SOURCE = REPO / "runs/hongkong/outputs/progress_report_figures_20260824/source_data"
DEFAULT_OUTPUT = REPO / "runs/hongkong/outputs/progress_report_figures_20260824"
BOUNDARY_CANDIDATES = (
    REPO / "data/boundary/hongkong/2021_Population_Census_Statistics_and_Boundar_SHP/DC_21C_converted.shp",
    Path("F:/Matsim/matsim-example-project/data/boundary/hongkong/2021_Population_Census_Statistics_and_Boundar_SHP/DC_21C_converted.shp"),
)


def _boundary_path() -> Path:
    for path in BOUNDARY_CANDIDATES:
        if path.exists():
            return path
    raise FileNotFoundError("Hong Kong district boundary shapefile was not found")


def _districts() -> gpd.GeoDataFrame:
    frame = gpd.read_file(_boundary_path())[["dc", "dc_eng", "geometry"]]
    frame["dc"] = frame["dc"].astype(int)
    return frame.to_crs("EPSG:32650")


def _realised_flows(trips_path: Path, districts: gpd.GeoDataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    usecols = ["main_mode", "start_x", "start_y", "end_x", "end_y"]
    trips = pd.read_csv(trips_path, sep=";", usecols=usecols)
    start = gpd.GeoDataFrame(
        trips,
        geometry=gpd.points_from_xy(trips["start_x"], trips["start_y"]),
        crs="EPSG:32650",
    )
    start = gpd.sjoin(start, districts[["dc", "geometry"]], how="left", predicate="within")
    start = start.rename(columns={"dc": "origin"}).drop(columns=["index_right", "geometry"])
    end = gpd.GeoDataFrame(
        start,
        geometry=gpd.points_from_xy(start["end_x"], start["end_y"]),
        crs="EPSG:32650",
    )
    joined = gpd.sjoin(end, districts[["dc", "geometry"]], how="left", predicate="within")
    joined = joined.rename(columns={"dc": "destination"}).dropna(subset=["origin", "destination"])
    joined[["origin", "destination"]] = joined[["origin", "destination"]].astype(int)
    grouped = joined.groupby(["origin", "destination", "main_mode"]).size().rename("trips").reset_index()
    flows = grouped.groupby(["origin", "destination"], as_index=False)["trips"].sum()
    dominant = grouped.loc[grouped.groupby(["origin", "destination"])["trips"].idxmax()]
    flows = flows.merge(dominant[["origin", "destination", "main_mode"]], on=["origin", "destination"])
    origins = joined.groupby("origin").size().rename("trips").reset_index()
    modes = trips["main_mode"].value_counts()
    return flows, origins, modes


def _scale(values, low: float, high: float) -> np.ndarray:
    values = np.sqrt(np.asarray(values, dtype=float))
    if np.ptp(values) == 0:
        return np.full(values.shape, (low + high) / 2)
    return low + (values - values.min()) / np.ptp(values) * (high - low)


def _draw_execution_map(ax, districts, flows, origins, top_n: int) -> None:
    districts.plot(ax=ax, color=PALETTE["land"], edgecolor=PALETTE["boundary"], linewidth=0.48, zorder=0)
    points = districts.set_index("dc").geometry.representative_point()
    inter = flows.loc[flows["origin"].ne(flows["destination"])].nlargest(top_n, "trips").copy()
    inter["width"] = _scale(inter["trips"], 0.55, 3.7)
    for row in inter.sort_values("trips").itertuples():
        p0, p1 = points.loc[row.origin], points.loc[row.destination]
        rad = (1 if (row.origin + row.destination) % 2 else -1) * (0.045 + 0.016 * ((row.origin * row.destination) % 3))
        color = MODE_COLORS.get(row.main_mode, PALETTE["brick"])
        ax.add_patch(
            FancyArrowPatch(
                (p0.x, p0.y),
                (p1.x, p1.y),
                connectionstyle=f"arc3,rad={rad}",
                arrowstyle="-|>",
                mutation_scale=5.8 + row.width,
                linewidth=row.width,
                color=color,
                alpha=0.45,
                shrinkA=4,
                shrinkB=4,
                zorder=2,
            )
        )
    node = districts[["dc", "geometry"]].merge(origins, left_on="dc", right_on="origin", how="left")
    node_points = node.geometry.representative_point()
    sizes = _scale(node["trips"].fillna(0), 28, 165)
    ax.scatter(node_points.x, node_points.y, s=sizes, color=PALETTE["blue"], edgecolor="white", linewidth=0.65, zorder=3)
    clean_map_axis(ax)
    ax.text(0.5, 1.025, "REALISED ITERATION-49 MOVEMENT", transform=ax.transAxes, ha="center", color=PALETTE["muted"], fontsize=8.5)


def _node(ax, x: float, y: float, title: str, detail: str, color: str, radius: float = 0.085) -> None:
    ax.add_patch(Circle((x, y), radius, facecolor=color, edgecolor="white", linewidth=1.1, alpha=0.96, zorder=3))
    ax.text(x, y + 0.006, title, ha="center", va="center", color="white", fontsize=9.5, zorder=4)
    ax.text(x, y - radius - 0.038, detail, ha="center", va="top", color=PALETTE["muted"], fontsize=8, linespacing=1.1)


def _module(ax, y: float, title: str, detail: str, color: str) -> None:
    box = FancyBboxPatch(
        (0.07, y - 0.065),
        0.86,
        0.13,
        boxstyle="round,pad=0.012,rounding_size=0.018",
        facecolor="white",
        edgecolor=color,
        linewidth=1.1,
    )
    ax.add_patch(box)
    ax.add_patch(Circle((0.12, y), 0.018, facecolor=color, edgecolor="none"))
    ax.text(0.16, y + 0.021, title, ha="left", va="center", fontsize=10.5, color=PALETTE["text"])
    ax.text(0.16, y - 0.025, detail, ha="left", va="center", fontsize=7.9, color=PALETTE["muted"], linespacing=1.1)


def build(source_dir: Path, output_dir: Path, top_n: int = 44) -> tuple[Path, Path]:
    apply_progress_report_style()
    districts = _districts()
    flows, origins, modes = _realised_flows(source_dir / "49.trips.csv.zst", districts)

    fig = plt.figure(figsize=(14.8, 9.2))
    left = fig.add_axes([0.035, 0.19, 0.225, 0.68])
    map_ax = fig.add_axes([0.245, 0.125, 0.50, 0.77])
    right = fig.add_axes([0.76, 0.16, 0.22, 0.71])
    left.set_xlim(0, 1)
    left.set_ylim(0, 1)
    left.axis("off")
    right.set_xlim(0, 1)
    right.set_ylim(0, 1)
    right.axis("off")

    left.text(0.5, 0.97, "ORIGINAL BASELINE", ha="center", color=PALETTE["muted"], fontsize=8.8)
    _node(left, 0.34, 0.75, "PLANS", "synthetic persons\nand activity chains", PALETTE["blue"])
    _node(left, 0.66, 0.50, "SUPPLY", "road + PT network\nand travel times", PALETTE["blue"])
    _node(left, 0.34, 0.25, "CHOICE", "mode choice expressed\nmainly in utility score", PALETTE["blue"])
    for a, b in [((0.40, 0.69), (0.59, 0.56)), ((0.59, 0.44), (0.40, 0.31))]:
        left.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=10, color=PALETTE["grid"], linewidth=1.5))

    _draw_execution_map(map_ax, districts, flows, origins, top_n)
    map_ax.legend(
        handles=[
            Line2D([0], [0], color=MODE_COLORS["pt"], linewidth=2, alpha=0.65, label="PT-dominant OD"),
            Line2D([0], [0], color=MODE_COLORS["taxi"], linewidth=2, alpha=0.65, label="Taxi-dominant OD"),
            Line2D([0], [0], marker="o", linestyle="", markerfacecolor=PALETTE["blue"], markeredgecolor="white", label="Node size: all trip origins"),
        ],
        loc="upper right",
        title="Top realised district links",
        title_fontsize=8.5,
        fontsize=7.8,
    )

    right.text(0.5, 0.97, "NEWLY IMPLEMENTED LAYERS", ha="center", color=PALETTE["muted"], fontsize=8.8)
    _module(right, 0.80, "REAL-MONEY COST", "PT fares • car energy/toll/parking\nTaxi metered distance fare", PALETTE["brick"])
    _module(right, 0.60, "PHYSICAL RESOURCES", "15,500-Taxi fleet • school-bus vehicles\nhousehold car / passenger coordination", PALETTE["blue"])
    _module(right, 0.40, "NETWORK CONTROL", "1,445 signal systems • 14 green-wave\ncorridors in Candidate11", PALETTE["green"])
    _module(right, 0.20, "AUDITABLE OUTCOMES", "completed / waiting / onboard states\ntrip, request, vehicle and event ledgers", PALETTE["purple"])

    fig.add_artist(
        FancyArrowPatch((0.225, 0.51), (0.275, 0.51), transform=fig.transFigure, arrowstyle="-|>", mutation_scale=14, color=PALETTE["brick"], linewidth=1.8)
    )
    fig.add_artist(
        FancyArrowPatch((0.72, 0.51), (0.77, 0.51), transform=fig.transFigure, arrowstyle="-|>", mutation_scale=14, color=PALETTE["brick"], linewidth=1.8)
    )

    total = int(modes.sum())
    fig.suptitle("Hong Kong mobility model evolution: from abstract demand to auditable physical execution", y=0.972, fontsize=18)
    fig.text(
        0.5,
        0.934,
        f"A single workflow now connects person plans, monetary rules, scarce vehicles, signal control and {total:,} realised trips",
        ha="center",
        fontsize=11.2,
    )
    add_method_note(
        fig,
        "The central map aggregates iteration-49 realised trips to 18 districts; arrow colour is the dominant mode on each displayed OD pair and node area is all-mode origins.\n"
        "Side modules summarise implemented model capabilities. Counts refer to the current candidate workflow and do not imply empirical calibration or production adoption.",
    )
    return save_figure(fig, output_dir, "01_hong_kong_model_evolution")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--top-n", type=int, default=44)
    args = parser.parse_args()
    png, pdf = build(args.source_dir, args.output_dir, args.top_n)
    print(png)
    print(pdf)


if __name__ == "__main__":
    main()
