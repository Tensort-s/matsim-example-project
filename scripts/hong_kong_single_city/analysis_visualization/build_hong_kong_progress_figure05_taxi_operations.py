"""Build progress-report Figure 5: finite-fleet Hong Kong Taxi operations.

The map uses realised iteration-49 trips and the audit inset uses the matching
request/vehicle ledgers.  It is intentionally an operational audit figure, not
a calibrated representation of observed Hong Kong Taxi trajectories.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch

from progress_report_figure_style import (
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


DISTRICT_LABELS = {
    "Central and Western": "C&W",
    "Wan Chai": "WC",
    "Eastern": "E",
    "Southern": "S",
    "Yau Tsim Mong": "YTM",
    "Sham Shui Po": "SSP",
    "Kowloon City": "KC",
    "Wong Tai Sin": "WTS",
    "Kwun Tong": "KT",
    "Kwai Tsing": "K&T",
    "Tsuen Wan": "TW",
    "Tuen Mun": "TM",
    "Yuen Long": "YL",
    "North": "N",
    "Tai Po": "TP",
    "Sha Tin": "ST",
    "Sai Kung": "SK",
    "Islands": "I",
}


def _boundary_path() -> Path:
    for path in BOUNDARY_CANDIDATES:
        if path.exists():
            return path
    raise FileNotFoundError("Hong Kong 18-district boundary shapefile was not found")


def _districts() -> gpd.GeoDataFrame:
    districts = gpd.read_file(_boundary_path())[["dc", "dc_eng", "geometry"]]
    districts["dc"] = districts["dc"].astype(int)
    return districts.to_crs("EPSG:32650")


def _taxi_od(trips_path: Path, districts: gpd.GeoDataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    columns = ["main_mode", "start_x", "start_y", "end_x", "end_y"]
    trips = pd.read_csv(trips_path, sep=";", usecols=columns)
    taxi = trips.loc[trips["main_mode"].eq("taxi")].copy()
    start = gpd.GeoDataFrame(
        taxi,
        geometry=gpd.points_from_xy(taxi["start_x"], taxi["start_y"]),
        crs="EPSG:32650",
    )
    start = gpd.sjoin(start, districts[["dc", "geometry"]], how="left", predicate="within")
    start = start.rename(columns={"dc": "origin"}).drop(columns=["index_right"])
    end = gpd.GeoDataFrame(
        start.drop(columns="geometry"),
        geometry=gpd.points_from_xy(start["end_x"], start["end_y"]),
        crs="EPSG:32650",
    )
    joined = gpd.sjoin(end, districts[["dc", "geometry"]], how="left", predicate="within")
    joined = joined.rename(columns={"dc": "destination"})
    joined = joined.dropna(subset=["origin", "destination"])
    joined[["origin", "destination"]] = joined[["origin", "destination"]].astype(int)
    flows = (
        joined.groupby(["origin", "destination"], as_index=False)
        .size()
        .rename(columns={"size": "trips"})
    )
    origins = joined.groupby("origin").size().rename("origins").reset_index()
    return flows, origins


def _scaled(values: pd.Series | np.ndarray, low: float, high: float) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    root = np.sqrt(np.maximum(values, 0.0))
    if np.ptp(root) == 0:
        return np.full_like(root, (low + high) / 2)
    return low + (root - root.min()) / np.ptp(root) * (high - low)


def _draw_flow_map(
    ax,
    districts: gpd.GeoDataFrame,
    flows: pd.DataFrame,
    origins: pd.DataFrame,
    top_n: int,
) -> None:
    districts.plot(ax=ax, color=PALETTE["land"], edgecolor=PALETTE["boundary"], linewidth=0.55, zorder=0)
    centers = districts.set_index("dc").geometry.representative_point()
    inter = flows.loc[flows["origin"].ne(flows["destination"])].nlargest(top_n, "trips").copy()
    inter["width"] = _scaled(inter["trips"], 0.7, 4.2)
    for row in inter.sort_values("trips").itertuples():
        p0, p1 = centers.loc[row.origin], centers.loc[row.destination]
        direction = 1 if (row.origin * 37 + row.destination * 17) % 2 else -1
        rad = direction * (0.055 + 0.018 * ((row.origin + row.destination) % 3))
        arrow = FancyArrowPatch(
            (p0.x, p0.y),
            (p1.x, p1.y),
            connectionstyle=f"arc3,rad={rad}",
            arrowstyle="-|>",
            mutation_scale=6.5 + row.width,
            linewidth=row.width,
            color=PALETTE["brick"],
            alpha=0.52,
            zorder=2,
            shrinkA=6,
            shrinkB=6,
        )
        ax.add_patch(arrow)

    node = districts[["dc", "dc_eng", "geometry"]].copy()
    node = node.merge(origins, left_on="dc", right_on="origin", how="left").fillna({"origins": 0})
    points = node.geometry.representative_point()
    node_sizes = _scaled(node["origins"], 54, 260)
    ax.scatter(points.x, points.y, s=node_sizes, color=PALETTE["blue"], edgecolor="white", linewidth=0.8, zorder=4)
    for name, point, size in zip(node["dc_eng"], points, node_sizes):
        ax.text(
            point.x,
            point.y,
            DISTRICT_LABELS.get(name, name[:3]),
            ha="center",
            va="center",
            fontsize=5.8 if size < 100 else 6.5,
            color="white",
            zorder=5,
        )

    width_refs = np.quantile(inter["trips"], [0.15, 0.5, 0.95]).round(-2).astype(int)
    line_handles = [
        Line2D([0], [0], color=PALETTE["brick"], linewidth=float(_scaled(inter["trips"], 0.7, 4.2)[np.abs(inter["trips"].to_numpy() - value).argmin()]), alpha=0.7, label=f"{value:,} trips")
        for value in width_refs
    ]
    line_handles.append(
        Line2D([0], [0], marker="o", linestyle="", markersize=8, markerfacecolor=PALETTE["blue"], markeredgecolor="white", label="Node size: Taxi origins")
    )
    ax.legend(handles=line_handles, title="Realised inter-district flow", loc="upper right", bbox_to_anchor=(1.0, 1.0), title_fontsize=9)
    clean_map_axis(ax)


def _draw_hourly_inset(ax, requests: pd.DataFrame, vehicles: pd.DataFrame) -> None:
    completed = requests.loc[requests["status"].eq("completed")].copy()
    hours = np.arange(24)
    request_hour = np.floor(completed["submitted_s"].to_numpy() / 3600).astype(int)
    request_counts = pd.Series(request_hour).value_counts().reindex(hours, fill_value=0).to_numpy()
    mids = (hours + 0.5) * 3600
    active = np.array(
        [((vehicles["service_begin_s"] <= t) & (vehicles["service_end_s"] > t)).sum() for t in mids]
    )
    theta = (hours + 0.5) / 24 * 2 * math.pi
    width = 2 * math.pi / 24 * 0.82
    request_scaled = request_counts / max(request_counts.max(), 1)
    active_scaled = active / max(active.max(), 1)
    ax.bar(theta, request_scaled, width=width, bottom=0, color=PALETTE["brick"], alpha=0.68, linewidth=0)
    theta_closed = np.r_[theta, theta[0] + 2 * math.pi]
    ax.plot(theta_closed, np.r_[active_scaled, active_scaled[0]], color=PALETTE["blue"], linewidth=2.0)
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.set_xticks(np.arange(0, 24, 4) / 24 * 2 * math.pi, [f"{h:02d}:00" for h in range(0, 24, 4)])
    ax.set_yticks([])
    ax.grid(color=PALETTE["grid"], linewidth=0.6)
    ax.spines["polar"].set_color(PALETTE["grid"])
    ax.set_title("Demand and active fleet through the day", fontsize=10.5, pad=12)
    ax.legend(
        handles=[
            Line2D([0], [0], color=PALETTE["brick"], linewidth=6, alpha=0.68, label="Completed requests (normalised)"),
            Line2D([0], [0], color=PALETTE["blue"], linewidth=2, label="Active fleet (normalised)"),
        ],
        loc="lower center",
        bbox_to_anchor=(0.5, -0.30),
        frameon=False,
        fontsize=7.6,
    )


def build(source_dir: Path, output_dir: Path, top_n: int = 40) -> tuple[Path, Path]:
    apply_progress_report_style()
    districts = _districts()
    flows, origins = _taxi_od(source_dir / "49.trips.csv.zst", districts)
    requests = pd.read_csv(source_dir / "49.taxi_request_audit.csv.gz")
    vehicles = pd.read_csv(source_dir / "49.taxi_vehicle_audit.csv.gz")

    fig = plt.figure(figsize=(13.6, 10.2))
    map_ax = fig.add_axes([0.045, 0.085, 0.735, 0.82])
    polar_ax = fig.add_axes([0.765, 0.49, 0.215, 0.285], projection="polar")
    _draw_flow_map(map_ax, districts, flows, origins, top_n)
    _draw_hourly_inset(polar_ax, requests, vehicles)

    completed = int(requests["status"].eq("completed").sum())
    waiting = int(requests["status"].eq("waiting").sum())
    fleet = len(vehicles)
    empty_share = vehicles["empty_vkt_km"].sum() / (vehicles["empty_vkt_km"].sum() + vehicles["occupied_vkt_km"].sum())
    fig.text(0.79, 0.40, "FINITE SUPPLY AUDIT", color=PALETTE["muted"], fontsize=8.4)
    metrics = [
        (f"{fleet:,}", "physical Taxi vehicles"),
        (f"{completed:,}", "completed requests"),
        (f"{waiting:,}", "waiting at horizon"),
        (f"{empty_share:.1%}", "fleet empty-VKT share"),
    ]
    y = 0.355
    for value, label in metrics:
        fig.text(0.79, y, value, color=PALETTE["blue"], fontsize=16, ha="left")
        fig.text(0.79, y - 0.027, label, color=PALETTE["muted"], fontsize=8.5, ha="left")
        y -= 0.078

    fig.suptitle("Hong Kong physical Taxi operations: finite fleet, realised flows", y=0.975, fontsize=18)
    fig.text(
        0.5,
        0.937,
        f"Iteration 49 • top {top_n} directed district links • request and vehicle ledgers share one execution horizon",
        ha="center",
        fontsize=11.5,
    )
    add_method_note(
        fig,
        "Arrows aggregate realised Taxi trips by origin and destination district; node area encodes Taxi trip origins.\n"
        "The radial inset independently normalises hourly completed requests and vehicles in service. Candidate 50-QSim sensitivity, not the adopted production run.",
    )
    return save_figure(fig, output_dir, "05_hong_kong_finite_taxi_operations")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--top-n", type=int, default=40)
    args = parser.parse_args()
    png, pdf = build(args.source_dir, args.output_dir, args.top_n)
    print(png)
    print(pdf)


if __name__ == "__main__":
    main()
