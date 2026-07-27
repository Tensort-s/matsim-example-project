#!/usr/bin/env python3
"""Visualize the PT-accessibility Hong Kong border OD model and its QA comparison."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
from shapely.geometry import LineString

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from visualize_hong_kong_arrival_departure_od import (
    FLOW_COLOR,
    HOTEL_COLOR,
    PORT_COLOR,
    SECONDARY_COLOR,
    WORK_CRS,
    aggregate_district_port,
    assign_grid_districts,
    load_layers,
    plot_district_port_flows,
    scaled_widths,
)


ROOT = Path(__file__).resolve().parents[3]
WINDOWS_DATA_ROOT = Path(r"F:\Matsim\matsim-example-project\data")
DEFAULT_DATA_ROOT = WINDOWS_DATA_ROOT if WINDOWS_DATA_ROOT.exists() else ROOT / "data"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--top-district-flows", type=int, default=100)
    parser.add_argument("--top-activity-chains", type=int, default=100)
    return parser.parse_args()


def data_paths(root: Path, model: Path) -> dict[str, Path]:
    city = root / "worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid"
    return {
        "model": model,
        "grid": city / "CityAndRegionSplit/hong_kong_fixed_link_grid/regions.shp",
        "boundary": root / "boundary/hongkong/processed/hong_kong_fixed_link_boundary_wgs84.geojson",
        "dc18": root / "boundary/hongkong/2021_Population_Census_Statistics_and_Boundar_SHP/DC_21C_converted.shp",
    }


def make_chain_geometries(
    model: Path,
    ports: gpd.GeoDataFrame,
    top_count: int,
) -> gpd.GeoDataFrame:
    tours = pd.read_parquet(model / "synthetic_visitor_tours.parquet")
    selected = tours.nlargest(top_count, "sample_weight").copy()
    activities = pd.read_parquet(model / "synthetic_visitor_activities.parquet")
    activities = activities[activities.tour_id.isin(selected.tour_id)].sort_values(["tour_id", "activity_sequence"])
    port_lookup = ports.to_crs("EPSG:4326").set_index("control_point").geometry.to_dict()
    rows = []
    for tour in selected.itertuples():
        subset = activities[activities.tour_id.eq(tour.tour_id)]
        points = [port_lookup[tour.arrival_control_point]]
        points.extend(gpd.points_from_xy(subset.longitude, subset.latitude).tolist())
        points.append(port_lookup[tour.departure_control_point])
        rows.append({
            "tour_id": int(tour.tour_id), "person_segment": tour.person_segment,
            "stay_type": tour.stay_type, "purpose": tour.purpose,
            "arrival_control_point": tour.arrival_control_point,
            "departure_control_point": tour.departure_control_point,
            "sample_weight": float(tour.sample_weight), "waypoint_count": len(points),
            "geometry": LineString(points),
        })
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326").to_crs(WORK_CRS)


def plot_top_chains(
    model: Path,
    out: Path,
    boundary: gpd.GeoDataFrame,
    districts: gpd.GeoDataFrame,
    ports: gpd.GeoDataFrame,
    top_count: int,
) -> dict[str, object]:
    chains = make_chain_geometries(model, ports, top_count)
    flows = chains.sample_weight.to_numpy(dtype="float64")
    widths = scaled_widths(flows, 0.55, 5.0)
    colors = ["#287D8E" if stay == "same_day" else "#C47A2C" for stay in chains.stay_type]
    fig, ax = plt.subplots(figsize=(13.5, 10), dpi=220)
    boundary.plot(ax=ax, facecolor="#EEF1EE", edgecolor="#333333", linewidth=0.65, zorder=1)
    districts.boundary.plot(ax=ax, color="#9AA1A4", linewidth=0.35, zorder=2)
    segments = []
    segment_widths = []
    segment_colors = []
    for row, width, color in zip(chains.itertuples(), widths, colors, strict=True):
        coordinates = np.asarray(row.geometry.coords)
        segments.extend(np.stack([coordinates[:-1], coordinates[1:]], axis=1))
        segment_widths.extend([width] * (len(coordinates) - 1))
        segment_colors.extend([color] * (len(coordinates) - 1))
    ax.add_collection(LineCollection(segments, linewidths=segment_widths, colors=segment_colors, alpha=0.44, zorder=3))

    selected_ids = chains.tour_id.tolist()
    activities = pd.read_parquet(model / "synthetic_visitor_activities.parquet")
    activities = activities[activities.tour_id.isin(selected_ids)]
    activity_geo = gpd.GeoDataFrame(
        activities,
        geometry=gpd.points_from_xy(activities.longitude, activities.latitude),
        crs="EPSG:4326",
    ).to_crs(WORK_CRS)
    symbol = {
        "accommodation": ("D", HOTEL_COLOR, 24),
        "primary_activity": ("o", "#246B8E", 25),
        "secondary_activity": ("o", SECONDARY_COLOR, 17),
    }
    for activity_type, (marker, color, size) in symbol.items():
        subset = activity_geo[activity_geo.activity_type.eq(activity_type)]
        ax.scatter(subset.geometry.x, subset.geometry.y, marker=marker, s=size, color=color,
                   edgecolor="white", linewidth=0.35, alpha=0.9, zorder=5)
    used_names = set(chains.arrival_control_point) | set(chains.departure_control_point)
    used_ports = ports[ports.control_point.isin(used_names)]
    ax.scatter(used_ports.geometry.x, used_ports.geometry.y, marker="s", s=42, color=PORT_COLOR,
               edgecolor="white", linewidth=0.55, zorder=6)
    for row in used_ports.itertuples():
        ax.annotate(f"P{int(row.bcp_index) + 1}", (row.geometry.x, row.geometry.y), xytext=(3, 3),
                    textcoords="offset points", fontsize=6.5, color="#202020", zorder=7)
    handles = [
        Line2D([0], [0], color="#287D8E", linewidth=2.5, label="Same-day visitor chain"),
        Line2D([0], [0], color="#C47A2C", linewidth=2.5, label="Overnight visitor chain"),
        Line2D([0], [0], marker="D", linestyle="none", color=HOTEL_COLOR, label="Accommodation"),
        Line2D([0], [0], marker="o", linestyle="none", color="#246B8E", label="Primary activity"),
        Line2D([0], [0], marker="o", linestyle="none", color=SECONDARY_COLOR, label="Secondary activity"),
    ]
    ax.legend(handles=handles, loc="upper right", fontsize=8, framealpha=0.95)
    ax.set_title(f"Hong Kong PT-access visitor activity chains\nTop {len(chains)} weighted cohorts", fontsize=14)
    ax.text(0.01, 0.012, "Lines join control points and synthesized activity waypoints; widths represent cohort weight.",
            transform=ax.transAxes, fontsize=7.5, color="#333333")
    ax.set_axis_off()
    ax.set_aspect("equal")
    fig.tight_layout()
    output = out / "hong_kong_pt_access_visitor_activity_chains_top100.png"
    fig.savefig(output, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    chains.to_crs("EPSG:4326").to_file(model / "validation/visitor_activity_chains_top100.geojson", driver="GeoJSON")
    chains.drop(columns="geometry").to_csv(model / "validation/visitor_activity_chains_top100.csv", index=False, encoding="utf-8-sig")
    return {"output": str(output), "count": len(chains), "weight": float(flows.sum())}


def plot_near_port_comparison(model: Path, out: Path) -> dict[str, object]:
    frame = pd.read_csv(model / "validation/old_vs_pt_access_near_port.csv")
    x = np.arange(len(frame))
    width = 0.34
    fig, ax = plt.subplots(figsize=(8.2, 5.3), dpi=220)
    old = ax.bar(x - width / 2, frame.old_near_share * 100, width, label="Old Euclidean model", color="#8B8F93")
    new = ax.bar(x + width / 2, frame.new_near_share * 100, width, label="PT-access V2", color=FLOW_COLOR)
    ax.bar_label(old, fmt="%.1f%%", fontsize=8, padding=2)
    ax.bar_label(new, fmt="%.1f%%", fontsize=8, padding=2)
    ax.set_xticks(x, [f"Within {value:g} km" for value in frame.radius_km])
    ax.set_ylabel("Share of border-internal movements (%)")
    ax.set_title("Checkpoint-proximity concentration: old vs PT-access model")
    ax.grid(axis="y", alpha=0.22)
    ax.legend(frameon=False)
    fig.tight_layout()
    output = out / "hong_kong_old_vs_pt_access_near_port_comparison.png"
    fig.savefig(output, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return {"output": str(output), "rows": frame.to_dict(orient="records")}


def main() -> None:
    args = parse_args()
    model = args.model_dir or args.data_root / "tourism/hongkong/processed/arrival_departure_od_2026_typical_weekday_pt_access_v2"
    out = args.out_dir or model / "visualizations"
    out.mkdir(parents=True, exist_ok=True)
    paths = data_paths(args.data_root, model)
    for path in paths.values():
        if not path.exists():
            raise FileNotFoundError(path)
    grid, boundary, districts, ports = load_layers(paths)
    grid_district = assign_grid_districts(grid, districts)
    arrival_18, departure_18 = aggregate_district_port(model, grid_district, len(districts))
    district_summary = plot_district_port_flows(
        model, out, districts, ports, boundary, arrival_18, departure_18, args.top_district_flows
    )
    chain_summary = plot_top_chains(model, out, boundary, districts, ports, args.top_activity_chains)
    comparison_summary = plot_near_port_comparison(model, out)
    summary = {
        "scenario": "2026_typical_weekday_pt_access_v2",
        "district_control_point": district_summary,
        "visitor_activity_chains": chain_summary,
        "near_port_comparison": comparison_summary,
    }
    (model / "validation/pt_access_visualization_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
