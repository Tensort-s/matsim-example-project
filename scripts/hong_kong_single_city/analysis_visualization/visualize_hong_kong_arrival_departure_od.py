#!/usr/bin/env python3
"""Visualize Hong Kong border OD as district links and visitor activity chains."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd
from matplotlib import patheffects
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch
from scipy.spatial import cKDTree
from shapely.geometry import LineString

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[3]
WINDOWS_DATA_ROOT = Path(r"F:\Matsim\matsim-example-project\data")
DEFAULT_DATA_ROOT = WINDOWS_DATA_ROOT if WINDOWS_DATA_ROOT.exists() else ROOT / "data"
WORK_CRS = "EPSG:32650"
FLOW_COLOR = "#B33B24"
DISTRICT_COLOR = "#246B8E"
PORT_COLOR = "#263238"
HOTEL_COLOR = "#D39A2C"
ACTIVITY_COLOR = "#246B8E"
SECONDARY_COLOR = "#7A5C9E"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--top-district-flows", type=int, default=100)
    parser.add_argument("--top-activity-chains", type=int, default=100)
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


def scaled_widths(values: np.ndarray, low: float, high: float) -> np.ndarray:
    roots = np.sqrt(np.asarray(values, dtype="float64"))
    span = max(float(roots.max() - roots.min()), 1e-9)
    return low + (high - low) * (roots - roots.min()) / span


def formatted_flow(value: float, unit: str) -> str:
    if value >= 1000:
        return f"{value / 1000:.1f}k {unit}"
    return f"{value:.0f} {unit}"


def flow_legend(values: np.ndarray, widths: np.ndarray, unit: str) -> list[Line2D]:
    return [
        Line2D([0], [0], color=FLOW_COLOR, linewidth=width, label=formatted_flow(value, unit))
        for value, width in zip(values, widths, strict=True)
    ]


def top_rectangular_pairs(matrix: np.ndarray, count: int) -> pd.DataFrame:
    values = np.asarray(matrix, dtype="float64").ravel()
    positive = np.flatnonzero(np.isfinite(values) & (values > 0))
    if len(positive) == 0:
        raise ValueError("Flow matrix has no positive values")
    count = min(count, len(positive))
    selected = positive[np.argpartition(values[positive], -count)[-count:]]
    selected = selected[np.argsort(values[selected])[::-1]]
    row, column = np.unravel_index(selected, matrix.shape)
    return pd.DataFrame({
        "rank": np.arange(1, count + 1),
        "row": row,
        "column": column,
        "flow": values[selected],
    })


def load_layers(paths: dict[str, Path]) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame, gpd.GeoDataFrame]:
    grid = gpd.read_file(paths["grid"]).to_crs(WORK_CRS).reset_index(drop=True)
    boundary = gpd.read_file(paths["boundary"]).to_crs(WORK_CRS)
    districts = gpd.read_file(paths["dc18"])[["dc_class", "dc_eng", "geometry"]].to_crs(WORK_CRS)
    fixed = boundary.geometry.union_all()
    districts["geometry"] = districts.geometry.intersection(fixed)
    districts = districts.loc[~districts.geometry.is_empty].reset_index(drop=True)
    if len(districts) != 18:
        raise ValueError(f"Expected 18 retained districts, got {len(districts)}")
    ports_table = pd.read_csv(paths["model"] / "model_control_points_14.csv", encoding="utf-8-sig")
    ports = gpd.GeoDataFrame(
        ports_table,
        geometry=gpd.points_from_xy(ports_table.longitude, ports_table.latitude),
        crs="EPSG:4326",
    ).to_crs(WORK_CRS)
    return grid, boundary, districts, ports


def assign_grid_districts(grid: gpd.GeoDataFrame, districts: gpd.GeoDataFrame) -> np.ndarray:
    centers = gpd.GeoDataFrame(
        {"grid_index": np.arange(len(grid))}, geometry=grid.geometry.centroid, crs=grid.crs
    )
    joined = gpd.sjoin(centers, districts[["dc_eng", "geometry"]], how="left", predicate="within")
    if joined["dc_eng"].isna().any():
        missing = joined["dc_eng"].isna()
        nearest = gpd.sjoin_nearest(
            centers.loc[missing, ["grid_index", "geometry"]],
            districts[["dc_eng", "geometry"]],
            how="left",
        )
        joined.loc[missing, "dc_eng"] = nearest.set_index("grid_index").loc[
            joined.loc[missing, "grid_index"], "dc_eng"
        ].to_numpy()
    if joined["grid_index"].duplicated().any() or joined["dc_eng"].isna().any():
        raise ValueError("Could not assign every grid to exactly one district")
    lookup = {name: index for index, name in enumerate(districts["dc_eng"])}
    return joined.sort_values("grid_index")["dc_eng"].map(lookup).to_numpy(dtype=int)


def aggregate_district_port(
    model: Path,
    grid_district: np.ndarray,
    district_count: int,
) -> tuple[np.ndarray, np.ndarray]:
    arrival = np.load(model / "arrival_bcp_to_grid.npy")
    departure = np.load(model / "departure_grid_to_bcp.npy")
    arrival_18 = np.zeros((arrival.shape[0], district_count), dtype="float64")
    departure_18 = np.zeros((district_count, departure.shape[1]), dtype="float64")
    for district_index in range(district_count):
        mask = grid_district == district_index
        arrival_18[:, district_index] = np.sum(arrival[:, mask], axis=1, dtype=np.float64)
        departure_18[district_index, :] = np.sum(departure[mask, :], axis=0, dtype=np.float64)
    return arrival_18, departure_18


def draw_bipartite_panel(
    ax: plt.Axes,
    matrix: np.ndarray,
    direction: str,
    pairs: pd.DataFrame,
    districts: gpd.GeoDataFrame,
    ports: gpd.GeoDataFrame,
    boundary: gpd.GeoDataFrame,
) -> None:
    boundary.plot(ax=ax, facecolor="#edf0ed", edgecolor="#3f3f3f", linewidth=0.6, zorder=1)
    districts.boundary.plot(ax=ax, color="#929292", linewidth=0.35, zorder=2)
    district_points = districts.geometry.representative_point()
    district_xy = np.column_stack([district_points.x, district_points.y])
    port_xy = np.column_stack([ports.geometry.x, ports.geometry.y])
    flows = pairs["flow"].to_numpy(dtype="float64")
    widths = scaled_widths(flows, 0.45, 4.8)
    alphas = 0.16 + 0.58 * (widths - widths.min()) / max(float(np.ptp(widths)), 1e-9)

    for index in np.argsort(flows):
        row = pairs.iloc[int(index)]
        if direction == "arrival":
            start = port_xy[int(row.row)]
            end = district_xy[int(row.column)]
        else:
            start = district_xy[int(row.row)]
            end = port_xy[int(row.column)]
        bend = 0.08 if (int(row.row) + int(row.column)) % 2 == 0 else -0.08
        ax.add_patch(FancyArrowPatch(
            start,
            end,
            connectionstyle=f"arc3,rad={bend}",
            arrowstyle="-|>",
            mutation_scale=5.0 + widths[index] * 1.4,
            linewidth=widths[index],
            color=FLOW_COLOR,
            alpha=alphas[index],
            shrinkA=4,
            shrinkB=4,
            zorder=3,
        ))

    district_totals = matrix.sum(axis=0 if direction == "arrival" else 1)
    port_totals = matrix.sum(axis=1 if direction == "arrival" else 0)
    district_sizes = scaled_widths(district_totals, 55.0, 360.0)
    port_sizes = scaled_widths(port_totals, 45.0, 300.0)
    ax.scatter(
        district_xy[:, 0], district_xy[:, 1], s=district_sizes, color=DISTRICT_COLOR,
        edgecolor="white", linewidth=0.8, alpha=0.92, zorder=5,
    )
    ax.scatter(
        port_xy[:, 0], port_xy[:, 1], s=port_sizes, marker="s", color=PORT_COLOR,
        edgecolor="white", linewidth=0.7, alpha=0.94, zorder=5,
    )
    for index, district in districts.iterrows():
        label = ax.text(
            district_xy[index, 0], district_xy[index, 1], str(district.dc_class),
            ha="center", va="center", color="white", fontsize=6.5, zorder=6,
        )
        label.set_path_effects([patheffects.withStroke(linewidth=0.9, foreground="#17485F")])
    for index in range(len(ports)):
        ax.text(
            port_xy[index, 0], port_xy[index, 1], f"P{index + 1}", ha="center", va="center",
            color="white", fontsize=5.5, zorder=6,
        )

    legend_values = np.asarray([np.quantile(flows, 0.10), np.median(flows), flows.max()])
    handles = flow_legend(legend_values, scaled_widths(legend_values, 0.8, 4.8), "movements")
    handles.extend([
        Line2D([0], [0], marker="o", linestyle="none", markerfacecolor=DISTRICT_COLOR,
               markeredgecolor="white", markersize=7, label="District node"),
        Line2D([0], [0], marker="s", linestyle="none", markerfacecolor=PORT_COLOR,
               markeredgecolor="white", markersize=7, label="Control point"),
    ])
    ax.legend(handles=handles, title="Flow encoding", loc="upper right", frameon=True,
              framealpha=0.94, fontsize=7, title_fontsize=8)
    title = "Arrivals: control point to district" if direction == "arrival" else "Departures: district to control point"
    ax.set_title(f"{title}\nTop {len(pairs)} directed links", fontsize=12, pad=8)
    ax.set_axis_off()
    ax.set_aspect("equal")


def plot_district_port_flows(
    model: Path,
    out: Path,
    districts: gpd.GeoDataFrame,
    ports: gpd.GeoDataFrame,
    boundary: gpd.GeoDataFrame,
    arrival_18: np.ndarray,
    departure_18: np.ndarray,
    count: int,
) -> dict[str, object]:
    arrival_pairs = top_rectangular_pairs(arrival_18, count)
    departure_pairs = top_rectangular_pairs(departure_18, count)
    fig, axes = plt.subplots(1, 2, figsize=(19, 9.5), dpi=220)
    draw_bipartite_panel(axes[0], arrival_18, "arrival", arrival_pairs, districts, ports, boundary)
    draw_bipartite_panel(axes[1], departure_18, "departure", departure_pairs, districts, ports, boundary)
    fig.suptitle("Hong Kong 2026 typical-weekday 18-district and control-point OD flows", fontsize=15)
    district_key = [f"{row.dc_class} {row.dc_eng}" for row in districts.itertuples()]
    port_key = [f"P{index + 1} {row.name_en}" for index, row in ports.iterrows()]
    key_lines = ["   ".join(district_key[i:i + 6]) for i in range(0, len(district_key), 6)]
    key_lines.extend("   ".join(port_key[i:i + 4]) for i in range(0, len(port_key), 4))
    fig.text(0.5, 0.015, "\n".join(key_lines), ha="center", va="bottom", fontsize=6.5)
    fig.subplots_adjust(left=0.01, right=0.99, top=0.91, bottom=0.16, wspace=0.02)
    output = out / "hong_kong_typical_weekday_dc18_control_point_od_flows.png"
    fig.savefig(output, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    arrival_frame = arrival_pairs.copy()
    arrival_frame["direction"] = "arrival"
    arrival_frame["control_point"] = ports.iloc[arrival_frame.row]["control_point"].to_numpy()
    arrival_frame["district"] = districts.iloc[arrival_frame.column]["dc_eng"].to_numpy()
    departure_frame = departure_pairs.copy()
    departure_frame["direction"] = "departure"
    departure_frame["district"] = districts.iloc[departure_frame.row]["dc_eng"].to_numpy()
    departure_frame["control_point"] = ports.iloc[departure_frame.column]["control_point"].to_numpy()
    pd.concat([arrival_frame, departure_frame], ignore_index=True).to_csv(
        model / "validation/dc18_control_point_top_flows.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(arrival_18, index=ports.control_point, columns=districts.dc_eng).to_csv(
        model / "validation/arrival_bcp_to_dc18.csv", encoding="utf-8-sig"
    )
    pd.DataFrame(departure_18, index=districts.dc_eng, columns=ports.control_point).to_csv(
        model / "validation/departure_dc18_to_bcp.csv", encoding="utf-8-sig"
    )
    return {
        "output": str(output),
        "arrival_total": float(arrival_18.sum()),
        "departure_total": float(departure_18.sum()),
        "arrival_top_flow_sum": float(arrival_pairs.flow.sum()),
        "departure_top_flow_sum": float(departure_pairs.flow.sum()),
        "top_links_each_direction": int(count),
    }


PURPOSE_CATEGORIES = {
    "sightseeing": {"tourism", "garden", "religion", "sport"},
    "leisure": {"tourism", "garden", "sport", "religion", "restaurant"},
    "shopping": {"retail", "livelihood shop", "clothes shop", "restaurant", "fast food"},
    "business": {"office", "finance", "service"},
    "work": {"office", "finance", "service"},
    "transit": {"transit station", "transport"},
    "other": {"service", "tourism", "retail", "restaurant"},
    "vfr": set(),
}
SECONDARY_CATEGORIES = {
    "sightseeing": {"restaurant", "retail", "garden"},
    "leisure": {"restaurant", "retail", "tourism"},
    "shopping": {"restaurant", "tourism", "garden"},
    "business": {"restaurant", "retail", "transit station"},
    "work": {"restaurant", "retail", "transit station"},
    "transit": {"retail", "restaurant", "tourism"},
    "other": {"retail", "restaurant", "tourism"},
    "vfr": {"retail", "restaurant", "garden"},
}


def load_pois(path: Path, grid: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    table = pd.read_csv(path, low_memory=False).dropna(subset=["lon", "lat"]).copy()
    table = table.loc[table["name_en"].notna() | table["name_zh"].notna()].copy()
    points = gpd.GeoDataFrame(
        table,
        geometry=gpd.points_from_xy(table.lon, table.lat),
        crs="EPSG:4326",
    ).to_crs(grid.crs)
    joined = gpd.sjoin(points, grid[["geometry"]], how="inner", predicate="within")
    joined = joined.rename(columns={"index_right": "grid_index"}).reset_index(drop=True)
    joined["wedan_category"] = joined["wedan_category"].fillna("").astype(str)
    joined["display_name"] = joined["name_en"].fillna(joined["name_zh"]).fillna("Unnamed POI").astype(str)
    return joined


def choose_primary(
    candidates: gpd.GeoDataFrame,
    purpose: str,
    fallback_point,
) -> tuple[object, str, str]:
    allowed = PURPOSE_CATEGORIES.get(purpose, PURPOSE_CATEGORIES["other"])
    if purpose == "vfr":
        return fallback_point, "Residential activity grid", "population_weighted_grid"
    matching = candidates.loc[candidates["wedan_category"].isin(allowed)]
    if matching.empty:
        matching = candidates
    if matching.empty:
        return fallback_point, f"{purpose.title()} activity grid", "grid_centroid_fallback"
    row = matching.sort_values(["source_priority", "display_name"]).iloc[0]
    return row.geometry, row.display_name, "integrated_poi_in_activity_grid"


def nearest_named_poi(
    point,
    pois: gpd.GeoDataFrame,
    tree: cKDTree,
    excluded_uid: str | None = None,
    minimum_distance_m: float = 50.0,
) -> tuple[object, str, str]:
    _, indices = tree.query([point.x, point.y], k=min(50, len(pois)))
    for index in np.atleast_1d(indices):
        row = pois.iloc[int(index)]
        uid_allowed = excluded_uid is None or str(row.poi_uid) != excluded_uid
        if uid_allowed and row.geometry.distance(point) >= minimum_distance_m:
            return row.geometry, row.display_name, str(row.poi_uid)
    row = pois.iloc[int(np.atleast_1d(indices)[-1])]
    return row.geometry, row.display_name, str(row.poi_uid)


def build_activity_chains(
    model: Path,
    grid: gpd.GeoDataFrame,
    ports: gpd.GeoDataFrame,
    pois: gpd.GeoDataFrame,
    count: int,
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    tours = pd.read_parquet(model / "synthetic_visitor_tours.parquet")
    group_columns = ["person_segment", "arrival_control_point", "purpose", "stay_type", "activity_grid_index"]
    top = (
        tours.groupby(group_columns, as_index=False).sample_weight.sum()
        .nlargest(count, "sample_weight")
        .reset_index(drop=True)
    )
    top.insert(0, "rank", np.arange(1, len(top) + 1))
    grid_centers = grid.geometry.centroid
    poi_groups = {int(index): frame for index, frame in pois.groupby("grid_index")}
    port_lookup = ports.set_index("control_point")
    hotels = pois.loc[pois["wedan_category"].eq("accommodation")].reset_index(drop=True)
    if hotels.empty:
        raise ValueError("No named accommodation POIs are available for overnight chains")
    hotel_tree = cKDTree(np.column_stack([hotels.geometry.x, hotels.geometry.y]))
    secondary_sets: dict[str, tuple[gpd.GeoDataFrame, cKDTree]] = {}
    for purpose, categories in SECONDARY_CATEGORIES.items():
        subset = pois.loc[pois["wedan_category"].isin(categories)].reset_index(drop=True)
        if subset.empty:
            subset = pois.reset_index(drop=True)
        secondary_sets[purpose] = (
            subset,
            cKDTree(np.column_stack([subset.geometry.x, subset.geometry.y])),
        )

    records: list[dict[str, object]] = []
    geometries: list[LineString] = []
    for row in top.itertuples(index=False):
        grid_index = int(row.activity_grid_index)
        primary_point, primary_name, primary_method = choose_primary(
            poi_groups.get(grid_index, pois.iloc[0:0]), row.purpose, grid_centers.iloc[grid_index]
        )
        start = port_lookup.loc[row.arrival_control_point].geometry
        if primary_point.distance(start) < 50.0:
            primary_point = grid_centers.iloc[grid_index]
            primary_name = f"{row.purpose.title()} activity grid"
            primary_method = "grid_centroid_port_separation"
        path_points = [start]
        hotel_name = ""
        if row.stay_type == "overnight":
            hotel_point, hotel_name, _ = nearest_named_poi(primary_point, hotels, hotel_tree)
            path_points.append(hotel_point)
        secondary_pois, secondary_tree = secondary_sets.get(row.purpose, secondary_sets["other"])
        secondary_point, secondary_name, _ = nearest_named_poi(primary_point, secondary_pois, secondary_tree)
        path_points.extend([primary_point, secondary_point])
        geometries.append(LineString([(point.x, point.y) for point in path_points]))
        records.append({
            **row._asdict(),
            "control_point_name_en": str(port_lookup.loc[row.arrival_control_point, "name_en"]),
            "primary_activity_name": primary_name,
            "primary_selection_method": primary_method,
            "secondary_activity_name": secondary_name,
            "accommodation_name": hotel_name,
            "waypoint_count": len(path_points),
            "path_length_km": LineString([(point.x, point.y) for point in path_points]).length / 1000.0,
            "start_x": start.x,
            "start_y": start.y,
            "primary_x": primary_point.x,
            "primary_y": primary_point.y,
            "secondary_x": secondary_point.x,
            "secondary_y": secondary_point.y,
        })
    chains = gpd.GeoDataFrame(records, geometry=geometries, crs=grid.crs)
    return chains, top


def plot_activity_chains(
    model: Path,
    out: Path,
    chains: gpd.GeoDataFrame,
    ports: gpd.GeoDataFrame,
    boundary: gpd.GeoDataFrame,
    districts: gpd.GeoDataFrame,
) -> dict[str, object]:
    flows = chains["sample_weight"].to_numpy(dtype="float64")
    widths = scaled_widths(flows, 0.45, 4.5)
    alphas = 0.18 + 0.60 * (widths - widths.min()) / max(float(np.ptp(widths)), 1e-9)
    segments = []
    segment_widths = []
    segment_colors = []
    for index in np.argsort(flows):
        coordinates = list(chains.geometry.iloc[int(index)].coords)
        for start, end in zip(coordinates[:-1], coordinates[1:], strict=True):
            segments.append([start, end])
            segment_widths.append(widths[index])
            segment_colors.append((*matplotlib.colors.to_rgb(FLOW_COLOR), alphas[index]))

    fig, ax = plt.subplots(figsize=(13, 9.5), dpi=220)
    boundary.plot(ax=ax, facecolor="#edf0ed", edgecolor="#3f3f3f", linewidth=0.6, zorder=1)
    districts.boundary.plot(ax=ax, color="#929292", linewidth=0.35, zorder=2)
    ax.add_collection(LineCollection(segments, linewidths=segment_widths, colors=segment_colors, zorder=3))
    overnight = chains["stay_type"].eq("overnight")
    if overnight.any():
        hotel_xy = np.asarray([list(line.coords)[1] for line in chains.loc[overnight, "geometry"]])
        ax.scatter(hotel_xy[:, 0], hotel_xy[:, 1], s=18, marker="D", color=HOTEL_COLOR,
                   edgecolor="white", linewidth=0.35, alpha=0.90, zorder=5)
    primary_xy = np.column_stack([chains.primary_x, chains.primary_y])
    secondary_xy = np.column_stack([chains.secondary_x, chains.secondary_y])
    ax.scatter(primary_xy[:, 0], primary_xy[:, 1], s=24, color=ACTIVITY_COLOR,
               edgecolor="white", linewidth=0.4, alpha=0.90, zorder=5)
    ax.scatter(secondary_xy[:, 0], secondary_xy[:, 1], s=15, color=SECONDARY_COLOR,
               edgecolor="white", linewidth=0.35, alpha=0.88, zorder=5)
    used_ports = ports.loc[ports.control_point.isin(chains.arrival_control_point.unique())]
    ax.scatter(used_ports.geometry.x, used_ports.geometry.y, s=36, marker="s", color=PORT_COLOR,
               edgecolor="white", linewidth=0.6, alpha=0.95, zorder=6)
    for index, port in used_ports.iterrows():
        ax.text(port.geometry.x, port.geometry.y, f"P{index + 1}", ha="center", va="center",
                color="white", fontsize=5.5, zorder=7)

    legend_values = np.asarray([np.quantile(flows, 0.10), np.median(flows), flows.max()])
    handles = flow_legend(legend_values, scaled_widths(legend_values, 0.8, 4.5), "visitors")
    handles.extend([
        Line2D([0], [0], marker="s", linestyle="none", markerfacecolor=PORT_COLOR,
               markeredgecolor="white", markersize=7, label="Arrival control point"),
        Line2D([0], [0], marker="D", linestyle="none", markerfacecolor=HOTEL_COLOR,
               markeredgecolor="white", markersize=6, label="Accommodation waypoint"),
        Line2D([0], [0], marker="o", linestyle="none", markerfacecolor=ACTIVITY_COLOR,
               markeredgecolor="white", markersize=7, label="Primary activity POI"),
        Line2D([0], [0], marker="o", linestyle="none", markerfacecolor=SECONDARY_COLOR,
               markeredgecolor="white", markersize=6, label="Secondary activity POI"),
    ])
    ax.legend(handles=handles, title="Chain encoding", loc="upper right", frameon=True,
              framealpha=0.94, fontsize=7.5, title_fontsize=8)
    all_visitor_weight = float(pd.read_parquet(model / "synthetic_visitor_tours.parquet", columns=["sample_weight"])["sample_weight"].sum())
    captured = float(flows.sum() / all_visitor_weight)
    ax.set_title(
        f"Hong Kong visitor arrival activity chains\nTop {len(chains)} weighted cohorts, {captured:.1%} of arrival visitor weight",
        fontsize=14,
        pad=9,
    )
    ax.text(
        0.01, 0.012,
        "Lines connect model control points and representative integrated POIs; these are synthesized activity chains, not observed routes.",
        transform=ax.transAxes, fontsize=7.5, color="#303030",
    )
    ax.set_axis_off()
    ax.set_aspect("equal")
    fig.tight_layout()
    output = out / "hong_kong_visitor_arrival_activity_chains_top100.png"
    fig.savefig(output, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    chains.drop(columns="geometry").to_csv(
        model / "validation/visitor_arrival_activity_chains_top100.csv", index=False, encoding="utf-8-sig"
    )
    chains.to_crs("EPSG:4326").to_file(
        model / "validation/visitor_arrival_activity_chains_top100.geojson", driver="GeoJSON"
    )
    return {
        "output": str(output),
        "chain_count": int(len(chains)),
        "top_chain_weight": float(flows.sum()),
        "share_of_arrival_visitor_weight": captured,
        "overnight_chains": int(overnight.sum()),
        "same_day_chains": int((~overnight).sum()),
        "minimum_waypoints": int(chains.waypoint_count.min()),
        "maximum_waypoints": int(chains.waypoint_count.max()),
    }


def main() -> None:
    args = parse_args()
    paths = data_paths(args.data_root)
    for path in paths.values():
        if not path.exists():
            raise FileNotFoundError(path)
    model = paths["model"]
    out = args.out_dir or model / "visualizations"
    out.mkdir(parents=True, exist_ok=True)
    (model / "validation").mkdir(exist_ok=True)

    grid, boundary, districts, ports = load_layers(paths)
    grid_district = assign_grid_districts(grid, districts)
    arrival_18, departure_18 = aggregate_district_port(model, grid_district, len(districts))
    district_summary = plot_district_port_flows(
        model, out, districts, ports, boundary, arrival_18, departure_18, args.top_district_flows
    )

    pois = load_pois(paths["pois"], grid)
    chains, _ = build_activity_chains(model, grid, ports, pois, args.top_activity_chains)
    chain_summary = plot_activity_chains(model, out, chains, ports, boundary, districts)
    summary = {
        "scenario": "2026_typical_weekday_HKTB_Q1",
        "district_control_point": district_summary,
        "visitor_arrival_activity_chains": chain_summary,
        "activity_chain_note": "Representative multi-waypoint chains are synthesized from modeled arrival cohorts and integrated POIs; they are not observed trajectories.",
    }
    (model / "validation/arrival_departure_visualization_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
