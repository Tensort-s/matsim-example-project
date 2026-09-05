#!/usr/bin/env python3
"""Create a static Hong Kong parking-supply map."""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle


matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import patheffects


REPO_ROOT = Path(__file__).resolve().parents[3]
CANONICAL_ROOT = Path(r"F:\Matsim\matsim-example-project")
DEFAULT_SUPPLY = (
    REPO_ROOT
    / "data/transport_costs/hongkong/parking_supply_2026_v1/"
    "hong_kong_parking_supply.csv"
)
DEFAULT_DISTRICTS = (
    CANONICAL_ROOT
    / "data/boundary/hongkong/"
    "2021_Population_Census_Statistics_and_Boundar_SHP/DC_21C_converted.shp"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "data/transport_costs/hongkong/parking_supply_2026_v1/visualization/"
    "hong_kong_parking_supply_static.png"
)
WORK_CRS = "EPSG:32650"
METER_COLOR = "#D87862"
OFFSTREET_COLOR = "#287592"
BOUNDARY_FILL = "#EEF1EF"
BOUNDARY_EDGE = "#777D7B"
LABEL_COLOR = "#626A68"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--supply", type=Path, default=DEFAULT_SUPPLY)
    parser.add_argument("--districts", type=Path, default=DEFAULT_DISTRICTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dpi", type=int, default=220)
    return parser.parse_args()


def load_data(supply_path: Path, district_path: Path) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    supply = pd.read_csv(supply_path, low_memory=False)
    required = {
        "parking_supply_id",
        "facility_type",
        "private_car_capacity",
        "x_epsg32650",
        "y_epsg32650",
    }
    missing = sorted(required - set(supply.columns))
    if missing:
        raise ValueError(f"Parking supply is missing columns: {missing}")
    if supply["parking_supply_id"].duplicated().any():
        raise ValueError("Parking supply IDs are not unique")
    parking = gpd.GeoDataFrame(
        supply,
        geometry=gpd.points_from_xy(supply["x_epsg32650"], supply["y_epsg32650"]),
        crs=WORK_CRS,
    )
    districts = gpd.read_file(district_path)[["dc_class", "dc_eng", "geometry"]].to_crs(WORK_CRS)
    if len(districts) != 18:
        raise ValueError(f"Expected 18 districts, got {len(districts)}")
    return parking, districts


def draw_districts(ax: plt.Axes, districts: gpd.GeoDataFrame, label: bool = True) -> None:
    districts.plot(
        ax=ax,
        facecolor=BOUNDARY_FILL,
        edgecolor=BOUNDARY_EDGE,
        linewidth=0.6,
        zorder=1,
    )
    if not label:
        return
    points = districts.geometry.representative_point()
    for row, point in zip(districts.itertuples(index=False), points):
        text = ax.text(
            point.x,
            point.y,
            row.dc_class,
            ha="center",
            va="center",
            fontsize=7.2,
            color="#FFFFFF",
            weight="normal",
            zorder=6,
            bbox={
                "boxstyle": "circle,pad=0.28",
                "facecolor": "#4D788B",
                "edgecolor": "#FFFFFF",
                "linewidth": 0.6,
                "alpha": 0.93,
            },
        )
        text.set_path_effects([patheffects.withStroke(linewidth=0.3, foreground="#4D788B")])


def plot_supply(ax: plt.Axes, parking: gpd.GeoDataFrame) -> None:
    meters = parking.loc[parking["facility_type"].eq("metered_on_street_pole")].copy()
    offstreet = parking.loc[~parking["facility_type"].eq("metered_on_street_pole")].copy()
    known = offstreet.loc[offstreet["private_car_capacity"].notna()].copy()
    unknown = offstreet.loc[offstreet["private_car_capacity"].isna()].copy()

    meter_capacity = pd.to_numeric(meters["private_car_capacity"], errors="raise").clip(1, 8)
    meter_sizes = 2.6 + 1.65 * meter_capacity
    ax.scatter(
        meters.geometry.x,
        meters.geometry.y,
        s=meter_sizes,
        c=METER_COLOR,
        alpha=0.48,
        edgecolors="none",
        zorder=3,
        rasterized=True,
    )
    ax.scatter(
        unknown.geometry.x,
        unknown.geometry.y,
        s=16,
        facecolors="none",
        edgecolors=OFFSTREET_COLOR,
        linewidths=0.75,
        alpha=0.72,
        zorder=4,
        rasterized=True,
    )
    known_capacity = pd.to_numeric(known["private_car_capacity"], errors="raise").clip(lower=1)
    known_sizes = 16 + 3.5 * np.sqrt(known_capacity)
    ax.scatter(
        known.geometry.x,
        known.geometry.y,
        s=known_sizes,
        c=OFFSTREET_COLOR,
        edgecolors="#FFFFFF",
        linewidths=0.55,
        alpha=0.9,
        zorder=5,
        rasterized=True,
    )


def set_extent(ax: plt.Axes, bounds: np.ndarray, padding: float) -> None:
    min_x, min_y, max_x, max_y = bounds
    ax.set_xlim(min_x - padding, max_x + padding)
    ax.set_ylim(min_y - padding, max_y + padding)
    ax.set_aspect("equal")
    ax.set_axis_off()


def add_scale_bar(ax: plt.Axes, length_m: float = 10000) -> None:
    min_x, max_x = ax.get_xlim()
    min_y, max_y = ax.get_ylim()
    x0 = min_x + 0.035 * (max_x - min_x)
    y0 = min_y + 0.035 * (max_y - min_y)
    ax.plot([x0, x0 + length_m], [y0, y0], color="#4F5554", linewidth=2.0, zorder=8)
    ax.plot([x0, x0], [y0 - 180, y0 + 180], color="#4F5554", linewidth=1.1, zorder=8)
    ax.plot([x0 + length_m, x0 + length_m], [y0 - 180, y0 + 180], color="#4F5554", linewidth=1.1, zorder=8)
    ax.text(x0 + length_m / 2, y0 + 420, "10 km", ha="center", va="bottom", fontsize=7.5, color=LABEL_COLOR)


def add_legend(ax: plt.Axes) -> None:
    handles = [
        Line2D([], [], marker="o", linestyle="none", markersize=5.5, markerfacecolor=METER_COLOR,
               markeredgecolor="none", alpha=0.65, label="Metered on-street pole"),
        Line2D([], [], marker="o", linestyle="none", markersize=7.5, markerfacecolor=OFFSTREET_COLOR,
               markeredgecolor="#FFFFFF", label="Off-street: known capacity"),
        Line2D([], [], marker="o", linestyle="none", markersize=7.0, markerfacecolor="none",
               markeredgecolor=OFFSTREET_COLOR, label="Off-street: capacity unknown"),
        Line2D([], [], marker="o", linestyle="none", markersize=4.5, markerfacecolor=OFFSTREET_COLOR,
               markeredgecolor="#FFFFFF", label="20 spaces"),
        Line2D([], [], marker="o", linestyle="none", markersize=8.2, markerfacecolor=OFFSTREET_COLOR,
               markeredgecolor="#FFFFFF", label="200 spaces"),
        Line2D([], [], marker="o", linestyle="none", markersize=12.2, markerfacecolor=OFFSTREET_COLOR,
               markeredgecolor="#FFFFFF", label="800 spaces"),
    ]
    legend = ax.legend(
        handles=handles,
        title="Parking encoding",
        loc="upper right",
        bbox_to_anchor=(0.995, 0.985),
        frameon=True,
        framealpha=0.92,
        facecolor="#FFFFFF",
        edgecolor="#C7CCCA",
        fontsize=8,
        title_fontsize=8.5,
        labelspacing=0.55,
        borderpad=0.7,
        handletextpad=0.7,
    )
    legend.get_frame().set_linewidth(0.7)


def create_map(parking: gpd.GeoDataFrame, districts: gpd.GeoDataFrame, output: Path, dpi: int) -> None:
    fig, ax = plt.subplots(figsize=(13.2, 10.4), facecolor="#FFFFFF")
    ax.set_facecolor("#FFFFFF")
    draw_districts(ax, districts, label=True)
    plot_supply(ax, parking)
    all_bounds = np.array(
        [
            min(districts.total_bounds[0], parking.total_bounds[0]),
            min(districts.total_bounds[1], parking.total_bounds[1]),
            max(districts.total_bounds[2], parking.total_bounds[2]),
            max(districts.total_bounds[3], parking.total_bounds[3]),
        ]
    )
    set_extent(ax, all_bounds, padding=1200)
    add_scale_bar(ax)
    add_legend(ax)

    fig.suptitle(
        "Hong Kong parking supply candidate",
        x=0.5,
        y=0.975,
        fontsize=17,
        fontweight="normal",
    )
    fig.text(
        0.5,
        0.942,
        "10,025 facilities: 569 off-street car parks and 9,456 metered poles (17,558 eligible spaces)",
        ha="center",
        va="center",
        fontsize=11.5,
        color="#2D3231",
    )
    district_key = [f"{row.dc_class} {row.dc_eng}" for row in districts.itertuples(index=False)]
    key_lines = ["   ".join(district_key[i : i + 6]) for i in range(0, len(district_key), 6)]
    fig.text(
        0.5,
        0.040,
        "Marker area: observed capacity where available; meter area: spaces per pole. Hollow circles have unknown capacity.\n"
        "Nearest Car links are not shown and remain entrance/direction-unverified. Candidate is not runtime-adopted.\n"
        + "\n".join(key_lines),
        ha="center",
        va="bottom",
        fontsize=7.3,
        color="#3F4544",
        linespacing=1.3,
    )
    fig.subplots_adjust(left=0.025, right=0.985, top=0.925, bottom=0.115)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=dpi, bbox_inches="tight", facecolor="#FFFFFF")
    plt.close(fig)


def main() -> None:
    args = parse_args()
    parking, districts = load_data(args.supply, args.districts)
    create_map(parking, districts, args.output, args.dpi)
    print(args.output)


if __name__ == "__main__":
    main()
