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

matplotlib.use("Agg")
import matplotlib.pyplot as plt


PROJECT_ROOT = Path(__file__).resolve().parents[3]
BASE = PROJECT_ROOT / "data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid"
DEFAULT_FINAL_DIR = (
    BASE / "CommutingODFlows/hong_kong_fixed_link_grid/hk_scaler_calibration_v1/final"
)
DEFAULT_OD = DEFAULT_FINAL_DIR / "generation_hk_census_projected.npy"
DEFAULT_GRID = BASE / "CityAndRegionSplit/hong_kong_fixed_link_grid/regions.shp"
DEFAULT_GRID_ASSIGNMENT = (
    BASE / "census_2021_commute_constraints/lsug_calibration_inputs/grid_calibration_features.csv"
)
DEFAULT_FIXED_LINK_BOUNDARY = (
    PROJECT_ROOT / "data/boundary/hongkong/processed/hong_kong_fixed_link_boundary_wgs84.geojson"
)
DEFAULT_DISTRICT_BOUNDARY = (
    PROJECT_ROOT
    / "data/boundary/hongkong/2021_Population_Census_Statistics_and_Boundar_SHP/DC_21C_converted.shp"
)
MODEL_CRS = "EPSG:32650"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create static grid and 18-district flow maps from the Census-projected Hong Kong OD matrix."
    )
    parser.add_argument("--od", type=Path, default=DEFAULT_OD)
    parser.add_argument("--grid", type=Path, default=DEFAULT_GRID)
    parser.add_argument("--grid-assignment", type=Path, default=DEFAULT_GRID_ASSIGNMENT)
    parser.add_argument("--fixed-link-boundary", type=Path, default=DEFAULT_FIXED_LINK_BOUNDARY)
    parser.add_argument("--district-boundary", type=Path, default=DEFAULT_DISTRICT_BOUNDARY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_FINAL_DIR / "flow_maps")
    parser.add_argument("--top-grid-flows", type=int, default=1000)
    parser.add_argument("--top-district-flows", type=int, default=60)
    return parser.parse_args()


def top_pairs(matrix: np.ndarray, count: int) -> pd.DataFrame:
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
        raise ValueError(f"Expected a square OD matrix, got {matrix.shape}")
    n = matrix.shape[0]
    values = matrix.ravel().astype("float64", copy=True)
    values[np.arange(n) * n + np.arange(n)] = -np.inf
    positive = np.flatnonzero(np.isfinite(values) & (values > 0))
    if len(positive) == 0:
        raise ValueError("OD matrix has no positive off-diagonal flows.")
    count = min(count, len(positive))
    selected = positive[np.argpartition(values[positive], -count)[-count:]]
    selected = selected[np.argsort(values[selected])[::-1]]
    return pd.DataFrame(
        {
            "rank": np.arange(1, count + 1),
            "origin_index": selected // n,
            "destination_index": selected % n,
            "flow": values[selected],
        }
    )


def scaled_widths(values: np.ndarray, low: float, high: float) -> np.ndarray:
    root = np.sqrt(np.asarray(values, dtype="float64"))
    span = max(float(root.max() - root.min()), 1e-9)
    return low + (high - low) * (root - root.min()) / span


def flow_legend(values: list[float], widths: list[float], color: str) -> list[Line2D]:
    def format_workers(value: float) -> str:
        return f"{value / 1000:.0f}k workers" if value >= 1000 else f"{value:.0f} workers"

    return [
        Line2D([0], [0], color=color, linewidth=width, label=format_workers(value))
        for value, width in zip(values, widths, strict=True)
    ]


def plot_grid_straight_lines(
    od: np.ndarray,
    grid: gpd.GeoDataFrame,
    fixed_link_boundary: gpd.GeoDataFrame,
    districts: gpd.GeoDataFrame,
    count: int,
    out_path: Path,
) -> tuple[pd.DataFrame, dict[str, float]]:
    pairs = top_pairs(od, count)
    centroids = grid.geometry.centroid
    segments = [
        [
            (centroids.iloc[int(row.origin_index)].x, centroids.iloc[int(row.origin_index)].y),
            (centroids.iloc[int(row.destination_index)].x, centroids.iloc[int(row.destination_index)].y),
        ]
        for row in pairs.itertuples(index=False)
    ]
    flow = pairs["flow"].to_numpy(dtype="float64")
    widths = scaled_widths(flow, 0.12, 2.7)
    alphas = 0.05 + 0.48 * (widths - widths.min()) / max(float(widths.max() - widths.min()), 1e-9)

    fig, ax = plt.subplots(figsize=(12, 9), dpi=220)
    fixed_link_boundary.plot(ax=ax, facecolor="#f1f2ef", edgecolor="#2f2f2f", linewidth=0.55, zorder=1)
    districts.boundary.plot(ax=ax, color="#9a9a9a", linewidth=0.35, zorder=2)
    order = np.argsort(flow)
    collection = LineCollection(
        [segments[index] for index in order],
        linewidths=widths[order],
        colors="#C7472D",
        zorder=3,
    )
    collection.set_alpha(alphas[order])
    ax.add_collection(collection)

    legend_values = [float(np.quantile(flow, 0.10)), float(np.median(flow)), float(flow.max())]
    legend_widths = scaled_widths(np.asarray(legend_values), 0.5, 3.0).tolist()
    ax.legend(
        handles=flow_legend(legend_values, legend_widths, "#C7472D"),
        title="OD pair flow",
        loc="upper right",
        frameon=True,
        framealpha=0.92,
        fontsize=8,
        title_fontsize=8,
    )
    captured = float(flow.sum() / od.sum())
    ax.set_title(
        f"Hong Kong Census-projected grid OD straight-line flows\n"
        f"Top {len(pairs):,} off-diagonal pairs, {captured:.1%} of total modeled flow",
        fontsize=14,
        pad=10,
    )
    ax.text(
        0.01,
        0.015,
        "Line width and opacity increase with OD flow. District boundaries are shown for orientation.",
        transform=ax.transAxes,
        fontsize=8,
        color="#303030",
    )
    ax.set_axis_off()
    ax.set_aspect("equal")
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    pairs["origin_grid_id"] = grid.iloc[pairs["origin_index"]]["grid_id"].to_numpy()
    pairs["destination_grid_id"] = grid.iloc[pairs["destination_index"]]["grid_id"].to_numpy()
    return pairs, {
        "top_grid_flow_sum": float(flow.sum()),
        "top_grid_flow_share": captured,
        "top_grid_flow_min": float(flow.min()),
        "top_grid_flow_max": float(flow.max()),
    }


def district_matrix(od: np.ndarray, assignment: pd.DataFrame) -> tuple[list[str], np.ndarray]:
    names = sorted(assignment["dc_eng"].unique().tolist())
    if len(names) != 18:
        raise ValueError(f"Expected 18 grid districts, got {len(names)}")
    index = assignment["dc_eng"].map({name: idx for idx, name in enumerate(names)}).to_numpy(dtype="int64")
    membership = np.eye(len(names), dtype="float64")[index]
    return names, membership.T @ od.astype("float64") @ membership


def district_nodes(
    districts: gpd.GeoDataFrame,
    names: list[str],
) -> tuple[dict[str, tuple[float, float]], dict[str, str]]:
    by_name = districts.set_index("dc_eng")
    points = by_name.geometry.representative_point()
    positions = {name: (float(points.loc[name].x), float(points.loc[name].y)) for name in names}
    codes = {name: str(by_name.loc[name, "dc_class"]) for name in names}
    return positions, codes


def plot_district_flows(
    names: list[str],
    matrix: np.ndarray,
    districts: gpd.GeoDataFrame,
    count: int,
    out_path: Path,
) -> tuple[pd.DataFrame, dict[str, float]]:
    pairs = top_pairs(matrix, count)
    positions, codes = district_nodes(districts, names)
    flows = pairs["flow"].to_numpy(dtype="float64")
    widths = scaled_widths(flows, 0.65, 5.2)
    alphas = 0.28 + 0.48 * (widths - widths.min()) / max(float(widths.max() - widths.min()), 1e-9)
    intra = np.diag(matrix).astype("float64")
    node_sizes = scaled_widths(intra, 90.0, 650.0)

    fig, ax = plt.subplots(figsize=(13, 9.5), dpi=220)
    districts.plot(ax=ax, facecolor="#edf0ed", edgecolor="#3f3f3f", linewidth=0.6, zorder=1)

    draw_order = np.argsort(flows)
    for index in draw_order:
        row = pairs.iloc[int(index)]
        origin = names[int(row.origin_index)]
        destination = names[int(row.destination_index)]
        arrow = FancyArrowPatch(
            positions[origin],
            positions[destination],
            connectionstyle="arc3,rad=0.12",
            arrowstyle="-|>",
            mutation_scale=5.5 + widths[index] * 1.5,
            linewidth=widths[index],
            color="#B33B24",
            alpha=alphas[index],
            shrinkA=5,
            shrinkB=5,
            zorder=3,
        )
        ax.add_patch(arrow)

    for idx, name in enumerate(names):
        x, y = positions[name]
        ax.scatter(
            x,
            y,
            s=node_sizes[idx],
            color="#246B8E",
            edgecolor="white",
            linewidth=1.0,
            alpha=0.92,
            zorder=5,
        )
        label = ax.text(
            x,
            y,
            codes[name],
            ha="center",
            va="center",
            color="white",
            fontsize=7,
            zorder=6,
        )
        label.set_path_effects([patheffects.withStroke(linewidth=1.0, foreground="#17485F")])

    legend_values = [float(np.quantile(flows, 0.10)), float(np.median(flows)), float(flows.max())]
    legend_widths = scaled_widths(np.asarray(legend_values), 0.8, 5.0).tolist()
    flow_handles = flow_legend(legend_values, legend_widths, "#B33B24")
    node_handles = [
        Line2D(
            [0],
            [0],
            marker="o",
            linestyle="none",
            markerfacecolor="#246B8E",
            markeredgecolor="white",
            markersize=8,
            label="Node size: within-district flow",
        )
    ]
    ax.legend(
        handles=flow_handles + node_handles,
        title="Flow encoding",
        loc="upper right",
        frameon=True,
        framealpha=0.94,
        fontsize=8,
        title_fontsize=8,
    )
    inter_total = float(matrix.sum() - np.trace(matrix))
    captured = float(flows.sum() / inter_total)
    code_items = [f"{codes[name]} {name}" for name in sorted(names, key=lambda item: codes[item])]
    code_key = "\n".join(
        "   ".join(code_items[start : start + 6]) for start in range(0, len(code_items), 6)
    )
    ax.set_title(
        f"Hong Kong Census-projected 18-district OD flows\n"
        f"Top {len(pairs)} directed inter-district links, {captured:.1%} of inter-district flow",
        fontsize=14,
        pad=10,
    )
    ax.text(
        0.5,
        -0.035,
        "Arrow direction indicates origin to destination; width indicates flow.\n" + code_key,
        transform=ax.transAxes,
        ha="center",
        va="top",
        fontsize=7,
    )
    ax.set_axis_off()
    ax.set_aspect("equal")
    fig.subplots_adjust(left=0.01, right=0.99, top=0.92, bottom=0.10)
    fig.savefig(out_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    pairs["origin_district"] = [names[int(index)] for index in pairs["origin_index"]]
    pairs["destination_district"] = [names[int(index)] for index in pairs["destination_index"]]
    return pairs, {
        "district_total_flow": float(matrix.sum()),
        "district_intra_flow": float(np.trace(matrix)),
        "district_inter_flow": inter_total,
        "top_district_flow_sum": float(flows.sum()),
        "top_district_flow_share_of_inter": captured,
    }


def main() -> None:
    args = parse_args()
    required = [
        args.od,
        args.grid,
        args.grid_assignment,
        args.fixed_link_boundary,
        args.district_boundary,
    ]
    for path in required:
        if not path.exists():
            raise FileNotFoundError(path)

    od = np.load(args.od, mmap_mode="r")
    if od.shape != (1585, 1585) or not np.isfinite(od).all() or np.any(od < 0):
        raise ValueError(f"Invalid OD matrix: {args.od}")
    grid = gpd.read_file(args.grid).sort_values("grid_id").reset_index(drop=True).to_crs(MODEL_CRS)
    if len(grid) != len(od) or not np.array_equal(grid["grid_id"].to_numpy(), np.arange(len(grid))):
        raise ValueError("Grid must contain contiguous grid_id values aligned with the OD matrix.")
    assignment = pd.read_csv(args.grid_assignment).sort_values("grid_id").reset_index(drop=True)
    if not np.array_equal(assignment["grid_id"].to_numpy(), grid["grid_id"].to_numpy()):
        raise ValueError("Grid assignment is not aligned with regions.shp.")
    fixed_link_boundary = gpd.read_file(args.fixed_link_boundary).to_crs(MODEL_CRS)
    districts = gpd.read_file(args.district_boundary)[["dc_class", "dc_eng", "geometry"]].to_crs(MODEL_CRS)
    if len(districts) != 18:
        raise ValueError(f"Expected 18 district polygons, got {len(districts)}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    grid_pairs, grid_summary = plot_grid_straight_lines(
        od,
        grid,
        fixed_link_boundary,
        districts,
        args.top_grid_flows,
        args.out_dir / "hong_kong_census_projected_grid_od_straight_lines.png",
    )
    names, matrix = district_matrix(od, assignment)
    district_pairs, district_summary = plot_district_flows(
        names,
        matrix,
        districts,
        args.top_district_flows,
        args.out_dir / "hong_kong_census_projected_18_district_od_flows.png",
    )

    grid_pairs.to_csv(args.out_dir / "hong_kong_top_grid_od_flows.csv", index=False, encoding="utf-8-sig")
    district_pairs.to_csv(
        args.out_dir / "hong_kong_top_18_district_od_flows.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(matrix, index=names, columns=names).to_csv(
        args.out_dir / "hong_kong_18_district_od_matrix.csv", encoding="utf-8-sig"
    )
    summary = {
        "od": str(args.od),
        "od_shape": list(od.shape),
        "od_total_flow": float(od.sum()),
        "top_grid_flows": int(args.top_grid_flows),
        "top_district_flows": int(args.top_district_flows),
        **grid_summary,
        **district_summary,
    }
    (args.out_dir / "hong_kong_census_projected_flow_maps_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"Wrote outputs to: {args.out_dir}")


if __name__ == "__main__":
    main()
