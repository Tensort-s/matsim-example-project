#!/usr/bin/env python3
"""Create static QA maps and charts for the Hong Kong border OD model."""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D


ROOT = Path(__file__).resolve().parents[3]
WINDOWS_DATA_ROOT = Path(r"F:\Matsim\matsim-example-project\data")
DEFAULT_DATA_ROOT = WINDOWS_DATA_ROOT if WINDOWS_DATA_ROOT.exists() else ROOT / "data"
WORK_CRS = "EPSG:32650"
COLORS = {"arrival": "#1b9e77", "departure": "#d95f02", "internal": "#7570b3", "boundary": "#4f5964"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--top-k", type=int, default=3000)
    return parser.parse_args()


def data_paths(root: Path) -> dict[str, Path]:
    city = root / "worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid"
    model = root / "tourism/hongkong/processed/arrival_departure_od_2026_typical_weekday"
    return {
        "model": model,
        "grid": city / "CityAndRegionSplit/hong_kong_fixed_link_grid/regions.shp",
        "boundary": root / "boundary/hongkong/processed/hong_kong_fixed_link_boundary_wgs84.geojson",
        "dc18": root / "boundary/hongkong/2021_Population_Census_Statistics_and_Boundar_SHP/DC_21C_converted.shp",
        "pois": root / "osm/hongkong/fixed_link_boundary/integrated_pois/hong_kong_fixed_link_integrated_pois.csv",
    }


def plot_base(ax: plt.Axes, boundary: gpd.GeoDataFrame, dc18: gpd.GeoDataFrame | None = None) -> None:
    boundary.plot(ax=ax, facecolor="#f3f5f4", edgecolor=COLORS["boundary"], linewidth=0.8, zorder=0)
    if dc18 is not None:
        dc18.boundary.plot(ax=ax, color="#aeb6bc", linewidth=0.45, zorder=1)
    ax.set_aspect("equal")
    ax.set_axis_off()


def line_widths(values: np.ndarray, low: float = 0.15, high: float = 3.4) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    scaled = (np.log1p(values) - np.log1p(values).min()) / max(np.ptp(np.log1p(values)), 1e-9)
    return low + scaled * (high - low)


def draw_flow_lines(ax: plt.Axes, starts: np.ndarray, ends: np.ndarray, flows: np.ndarray, color: str) -> None:
    segments = np.stack([starts, ends], axis=1)
    order = np.argsort(flows)
    collection = LineCollection(segments[order], colors=color, linewidths=line_widths(flows[order]), alpha=0.28, zorder=2)
    ax.add_collection(collection)


def top_indices(matrix: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    flat = matrix.ravel()
    k = min(k, int(np.count_nonzero(flat > 0)))
    selected = np.argpartition(flat, -k)[-k:]
    selected = selected[np.argsort(flat[selected])[::-1]]
    row, col = np.unravel_index(selected, matrix.shape)
    return row, col, flat[selected]


def border_flow_map(model: Path, out: Path, grid: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame, ports: gpd.GeoDataFrame, top_k: int) -> None:
    arrival = np.load(model / "arrival_bcp_to_grid.npy")
    departure = np.load(model / "departure_grid_to_bcp.npy")
    centroids = grid.geometry.centroid
    grid_xy = np.column_stack([centroids.x, centroids.y])
    port_xy = np.column_stack([ports.geometry.x, ports.geometry.y])
    fig, axes = plt.subplots(1, 2, figsize=(18, 8), constrained_layout=True)
    for ax, matrix, direction in [(axes[0], arrival, "arrival"), (axes[1], departure, "departure")]:
        plot_base(ax, boundary)
        r, c, flow = top_indices(matrix, top_k)
        if direction == "arrival":
            starts, ends = port_xy[r], grid_xy[c]
            title = f"Arrivals: control point to internal grid (Top {len(flow):,})"
        else:
            starts, ends = grid_xy[r], port_xy[c]
            title = f"Departures: internal grid to control point (Top {len(flow):,})"
        draw_flow_lines(ax, starts, ends, flow, COLORS[direction])
        ports.plot(ax=ax, color="#263238", markersize=20, zorder=4)
        ax.set_title(title, fontsize=13, fontweight="normal")
    fig.suptitle("Hong Kong 2026 typical-weekday border flows", fontsize=16, fontweight="normal")
    fig.savefig(out / "typical_weekday_border_flows_top3000.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


def dc18_flow_map(model: Path, out: Path, grid: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame, dc18: gpd.GeoDataFrame, ports: gpd.GeoDataFrame) -> None:
    centers = gpd.GeoDataFrame({"grid_index": np.arange(len(grid))}, geometry=grid.geometry.centroid, crs=grid.crs)
    joined = gpd.sjoin(centers, dc18[["dc_eng", "geometry"]], how="left", predicate="within")
    if joined.dc_eng.isna().any():
        nearest = gpd.sjoin_nearest(centers.loc[joined.dc_eng.isna()], dc18[["dc_eng", "geometry"]], how="left")
        joined.loc[joined.dc_eng.isna(), "dc_eng"] = nearest.dc_eng.to_numpy()
    district_names = dc18.dc_eng.tolist()
    district_index = {name: i for i, name in enumerate(district_names)}
    grid_dc = joined.dc_eng.map(district_index).to_numpy()
    dc_points = dc18.geometry.representative_point()
    dc_xy = np.column_stack([dc_points.x, dc_points.y])
    port_xy = np.column_stack([ports.geometry.x, ports.geometry.y])
    arrival = np.load(model / "arrival_bcp_to_grid.npy")
    departure = np.load(model / "departure_grid_to_bcp.npy")
    a18 = np.zeros((len(ports), len(dc18)))
    d18 = np.zeros((len(dc18), len(ports)))
    for d in range(len(dc18)):
        mask = grid_dc == d
        a18[:, d] = arrival[:, mask].sum(axis=1)
        d18[d, :] = departure[mask, :].sum(axis=0)
    fig, axes = plt.subplots(1, 2, figsize=(18, 8), constrained_layout=True)
    for ax, matrix, direction in [(axes[0], a18, "arrival"), (axes[1], d18, "departure")]:
        plot_base(ax, boundary, dc18)
        r, c, flow = top_indices(matrix, min(120, matrix.size))
        if direction == "arrival":
            starts, ends = port_xy[r], dc_xy[c]
            title = "Arrival movements aggregated to 18 districts"
        else:
            starts, ends = dc_xy[r], port_xy[c]
            title = "Departure movements aggregated from 18 districts"
        draw_flow_lines(ax, starts, ends, flow, COLORS[direction])
        ports.plot(ax=ax, color="#263238", markersize=22, zorder=4)
        ax.set_title(title, fontsize=13, fontweight="normal")
    fig.suptitle("Control point and 18-district flow structure", fontsize=16, fontweight="normal")
    fig.savefig(out / "typical_weekday_dc18_border_flow.png", dpi=220, bbox_inches="tight")
    plt.close(fig)
    pd.DataFrame(a18, index=ports.control_point, columns=district_names).to_csv(model / "validation/arrival_bcp_to_dc18.csv", encoding="utf-8-sig")
    pd.DataFrame(d18, index=district_names, columns=ports.control_point).to_csv(model / "validation/departure_dc18_to_bcp.csv", encoding="utf-8-sig")


def internal_flow_map(model: Path, out: Path, grid: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame, dc18: gpd.GeoDataFrame, top_k: int) -> None:
    matrix = np.load(model / "visitor_internal_grid_od.npy", mmap_mode="r")
    r, c, flow = top_indices(matrix, top_k)
    centroids = grid.geometry.centroid
    xy = np.column_stack([centroids.x, centroids.y])
    fig, ax = plt.subplots(figsize=(12, 10), constrained_layout=True)
    plot_base(ax, boundary, dc18)
    draw_flow_lines(ax, xy[r], xy[c], flow, COLORS["internal"])
    ax.set_title(f"Visitor internal mechanized OD (Top {len(flow):,})", fontsize=15, fontweight="normal")
    fig.savefig(out / "typical_weekday_visitor_internal_od_top3000.png", dpi=230, bbox_inches="tight")
    plt.close(fig)


def representative_poi_map(paths: dict[str, Path], out: Path, grid: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame, ports: gpd.GeoDataFrame) -> None:
    tours = pd.read_parquet(paths["model"] / "synthetic_visitor_tours.parquet")
    top = tours.groupby(["arrival_control_point", "activity_grid_index"], as_index=False).sample_weight.sum().nlargest(120, "sample_weight")
    poi = pd.read_csv(paths["pois"], low_memory=False).dropna(subset=["lon", "lat"])
    poi = poi[poi.name_en.notna() | poi.name_zh.notna()].copy()
    poi_gdf = gpd.GeoDataFrame(poi, geometry=gpd.points_from_xy(poi.lon, poi.lat), crs="EPSG:4326").to_crs(grid.crs)
    joined = gpd.sjoin(poi_gdf, grid[["geometry"]], how="inner", predicate="within")
    priority = joined.wedan_category.fillna("").isin(["tourism", "retail", "office", "accommodation", "transit station"])
    joined["priority"] = priority.astype(int)
    representatives = joined.sort_values(["index_right", "priority", "source_priority"], ascending=[True, False, True]).drop_duplicates("index_right").set_index("index_right")
    top = top[top.activity_grid_index.isin(representatives.index)].copy()
    reps = representatives.loc[top.activity_grid_index]
    port_lookup = ports.set_index("control_point")
    starts = np.column_stack([port_lookup.loc[top.arrival_control_point].geometry.x, port_lookup.loc[top.arrival_control_point].geometry.y])
    ends = np.column_stack([reps.geometry.x, reps.geometry.y])
    fig, ax = plt.subplots(figsize=(12, 10), constrained_layout=True)
    plot_base(ax, boundary)
    draw_flow_lines(ax, starts, ends, top.sample_weight.to_numpy(), "#c44e52")
    gpd.GeoSeries(reps.geometry, crs=grid.crs).plot(ax=ax, color="#c44e52", markersize=12, zorder=4)
    ports.plot(ax=ax, color="#263238", markersize=24, zorder=5)
    ax.set_title("Visitor arrivals to representative named POIs", fontsize=15, fontweight="normal")
    fig.savefig(out / "typical_weekday_major_poi_arrival_flows.png", dpi=230, bbox_inches="tight")
    plt.close(fig)
    audit = top.copy()
    audit["poi_uid"] = reps.poi_uid.to_numpy()
    audit["poi_name_en"] = reps.name_en.to_numpy()
    audit["poi_name_zh"] = reps.name_zh.to_numpy()
    audit.to_csv(paths["model"] / "validation/major_poi_flow_audit.csv", index=False, encoding="utf-8-sig")


def validation_charts(model: Path, out: Path) -> None:
    validation = pd.read_csv(model / "prepared_inputs/july_weekday_holdout_validation.csv")
    names = pd.read_csv(model / "model_control_points_14.csv", encoding="utf-8-sig").set_index("control_point")["name_en"]
    validation["control_point"] = validation["control_point"].map(names).fillna(validation["control_point"])
    grouped = validation.groupby(["control_point", "direction"], as_index=False)[["passenger_movements", "actual_july_weekday_median"]].sum()
    order = grouped.groupby("control_point").passenger_movements.sum().sort_values().index
    fig, axes = plt.subplots(1, 2, figsize=(17, 8), constrained_layout=True, sharey=True)
    for ax, direction, color in zip(axes, ["arrival", "departure"], [COLORS["arrival"], COLORS["departure"]]):
        part = grouped[grouped.direction == direction].set_index("control_point").reindex(order)
        y = np.arange(len(part))
        ax.barh(y - 0.18, part.passenger_movements, height=0.34, color=color, label="Typical weekday model")
        ax.barh(y + 0.18, part.actual_july_weekday_median, height=0.34, color="#8f969b", label="July weekday median")
        ax.set_yticks(y, part.index)
        ax.set_xlabel("Border passenger movements/day")
        ax.set_title(direction.capitalize())
        ax.grid(axis="x", color="#d9dde0", linewidth=0.6)
        ax.legend(frameon=False)
    fig.suptitle("Typical weekday margins versus July 2026 holdout", fontsize=16, fontweight="normal")
    fig.savefig(out / "validation/typical_weekday_marginal_validation.png", dpi=220, bbox_inches="tight")
    plt.close(fig)

    tours = pd.read_parquet(model / "synthetic_visitor_tours.parquet")
    purpose = tours.groupby("purpose").sample_weight.sum().sort_values(ascending=False)
    stay = tours.groupby("stay_type").sample_weight.sum().sort_values(ascending=False)
    mode = pd.Series({
        name.replace("mode_", "").replace(".npz", ""): float(np.load(path)["data"].sum())
        for path in (model / "segmented_matrices").glob("mode_*.npz") for name in [path.name]
    }).sort_values(ascending=False)
    fig, axes = plt.subplots(1, 3, figsize=(18, 6), constrained_layout=True)
    for ax, series, title, color in [
        (axes[0], purpose, "Arrival visitor cohorts by purpose", "#4c78a8"),
        (axes[1], stay, "Arrival visitor cohorts by stay type", "#59a14f"),
        (axes[2], mode, "Internal mechanized trips by mode", "#e15759"),
    ]:
        ax.barh(np.arange(len(series)), series.values, color=color)
        ax.set_yticks(np.arange(len(series)), series.index)
        ax.invert_yaxis()
        ax.grid(axis="x", color="#d9dde0", linewidth=0.6)
        ax.set_title(title)
    fig.savefig(out / "validation/segment_purpose_mode_summary.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    args = parse_args()
    p = data_paths(args.data_root)
    model = p["model"]
    out = args.out_dir or model / "visualizations"
    (out / "validation").mkdir(parents=True, exist_ok=True)
    grid = gpd.read_file(p["grid"]).to_crs(WORK_CRS).reset_index(drop=True)
    boundary = gpd.read_file(p["boundary"]).to_crs(WORK_CRS)
    dc18 = gpd.read_file(p["dc18"]).to_crs(WORK_CRS)
    ports_df = pd.read_csv(model / "model_control_points_14.csv", encoding="utf-8-sig")
    ports = gpd.GeoDataFrame(ports_df, geometry=gpd.points_from_xy(ports_df.longitude, ports_df.latitude), crs="EPSG:4326").to_crs(WORK_CRS)
    border_flow_map(model, out, grid, boundary, ports, args.top_k)
    dc18_flow_map(model, out, grid, boundary, dc18, ports)
    internal_flow_map(model, out, grid, boundary, dc18, args.top_k)
    representative_poi_map(p, out, grid, boundary, ports)
    validation_charts(model, out)
    print(f"Wrote static visualizations to {out}")


if __name__ == "__main__":
    main()
