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
from scipy.sparse import csr_matrix, load_npz

matplotlib.use("Agg")
import matplotlib.pyplot as plt


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHOOL_OD_DIR = PROJECT_ROOT / "data/school/hongkong/processed/student_school_od_2022"
GRID_BASE = PROJECT_ROOT / "data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid"
DEFAULT_PRODUCTS = {
    "student_assignment": {
        "path": SCHOOL_OD_DIR / "student_school_assignment_grid_od.npy",
        "title": "Student-school assignment",
        "unit": "expected students",
    },
    "mechanized_home_to_school": {
        "path": SCHOOL_OD_DIR / "direction_time_od/home_to_school.npy",
        "title": "Weekday mechanized home-to-school trips",
        "unit": "daily trips",
    },
}
DEFAULT_GRID = GRID_BASE / "CityAndRegionSplit/hong_kong_fixed_link_grid/regions.shp"
DEFAULT_GRID_ASSIGNMENT = (
    SCHOOL_OD_DIR / "dcca_study_area_crosswalk.parquet"
)
DEFAULT_FIXED_LINK_BOUNDARY = (
    PROJECT_ROOT / "data/boundary/hongkong/processed/hong_kong_fixed_link_boundary_wgs84.geojson"
)
DEFAULT_DISTRICTS = (
    PROJECT_ROOT
    / "data/boundary/hongkong/2021_Population_Census_Statistics_and_Boundar_SHP/DC_21C_converted.shp"
)
DEFAULT_GRID_SCHOOL = SCHOOL_OD_DIR / "student_school_assignment_grid_school.npz"
DEFAULT_SCHOOLS = SCHOOL_OD_DIR / "schools_2022_capacity_estimates.geojson"
MODEL_CRS = "EPSG:32650"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create static grid and 18-district maps for Hong Kong student-school OD flows."
    )
    parser.add_argument("--student-assignment", type=Path, default=DEFAULT_PRODUCTS["student_assignment"]["path"])
    parser.add_argument(
        "--mechanized-home-to-school",
        type=Path,
        default=DEFAULT_PRODUCTS["mechanized_home_to_school"]["path"],
    )
    parser.add_argument("--grid", type=Path, default=DEFAULT_GRID)
    parser.add_argument("--grid-assignment", type=Path, default=DEFAULT_GRID_ASSIGNMENT)
    parser.add_argument("--fixed-link-boundary", type=Path, default=DEFAULT_FIXED_LINK_BOUNDARY)
    parser.add_argument("--district-boundary", type=Path, default=DEFAULT_DISTRICTS)
    parser.add_argument("--grid-school", type=Path, default=DEFAULT_GRID_SCHOOL)
    parser.add_argument("--schools", type=Path, default=DEFAULT_SCHOOLS)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=SCHOOL_OD_DIR / "flow_maps/exact_school_points_top3000",
    )
    parser.add_argument("--top-grid-flows", type=int, default=3000)
    parser.add_argument("--top-district-flows", type=int, default=60)
    return parser.parse_args()


def top_pairs(matrix: np.ndarray, count: int) -> pd.DataFrame:
    n = matrix.shape[0]
    values = matrix.ravel().astype("float64", copy=True)
    values[np.arange(n) * n + np.arange(n)] = -np.inf
    positive = np.flatnonzero(np.isfinite(values) & (values > 0))
    if len(positive) == 0:
        raise ValueError("OD matrix has no positive off-diagonal flows")
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
    roots = np.sqrt(np.asarray(values, dtype="float64"))
    span = max(float(roots.max() - roots.min()), 1e-9)
    return low + (high - low) * (roots - roots.min()) / span


def formatted_flow(value: float, unit: str) -> str:
    suffix = "students" if unit == "expected students" else "trips"
    if value >= 1000:
        return f"{value / 1000:.1f}k {suffix}"
    return f"{value:.0f} {suffix}"


def flow_legend(values: list[float], widths: list[float], color: str, unit: str) -> list[Line2D]:
    return [
        Line2D([0], [0], color=color, linewidth=width, label=formatted_flow(value, unit))
        for value, width in zip(values, widths, strict=True)
    ]


def exact_school_flows(
    grid_school: csr_matrix,
    schools: gpd.GeoDataFrame,
    count: int,
    unit: str,
    grid_grid_matrix: np.ndarray | None = None,
    student_grid_matrix: np.ndarray | None = None,
) -> pd.DataFrame:
    coo = grid_school.tocoo()
    values = coo.data.astype("float64")
    if grid_grid_matrix is not None:
        if student_grid_matrix is None:
            raise ValueError("student_grid_matrix is required for mechanized exact-school flows")
        school_grid = np.full(grid_school.shape[1], -1, dtype=int)
        school_grid[schools["school_index"].to_numpy(dtype=int)] = schools["grid_id"].to_numpy(dtype=int)
        destination_grid = school_grid[coo.col]
        valid = destination_grid >= 0
        scale = np.zeros(len(values), dtype="float64")
        denominators = student_grid_matrix[coo.row[valid], destination_grid[valid]].astype("float64")
        scale[valid] = np.divide(
            grid_grid_matrix[coo.row[valid], destination_grid[valid]],
            denominators,
            out=np.zeros(valid.sum(), dtype="float64"),
            where=denominators > 0,
        )
        values *= scale
    positive = np.flatnonzero(np.isfinite(values) & (values > 0))
    count = min(count, len(positive))
    selected = positive[np.argpartition(values[positive], -count)[-count:]]
    selected = selected[np.argsort(values[selected])[::-1]]
    result = pd.DataFrame(
        {
            "rank": np.arange(1, count + 1),
            "origin_index": coo.row[selected],
            "school_index": coo.col[selected],
            "flow": values[selected],
        }
    )
    result.attrs["all_exact_flow_sum"] = float(values.sum())
    result.attrs["unit"] = unit
    return result


def plot_exact_school_flows(
    pairs: pd.DataFrame,
    grid: gpd.GeoDataFrame,
    schools: gpd.GeoDataFrame,
    boundary: gpd.GeoDataFrame,
    districts: gpd.GeoDataFrame,
    title: str,
    unit: str,
    out_path: Path,
) -> tuple[pd.DataFrame, dict[str, float]]:
    school_lookup = schools.set_index("school_index")
    origins = grid.geometry.centroid
    school_points = school_lookup.loc[pairs["school_index"], "geometry"].reset_index(drop=True)
    segments = [
        [
            (origins.iloc[int(row.origin_index)].x, origins.iloc[int(row.origin_index)].y),
            (school_points.iloc[index].x, school_points.iloc[index].y),
        ]
        for index, row in enumerate(pairs.itertuples(index=False))
    ]
    flows = pairs["flow"].to_numpy(dtype="float64")
    widths = scaled_widths(flows, 0.10, 2.7)
    alphas = 0.045 + 0.50 * (widths - widths.min()) / max(float(widths.max() - widths.min()), 1e-9)

    fig, ax = plt.subplots(figsize=(12, 9), dpi=220)
    boundary.plot(ax=ax, facecolor="#f0f2ef", edgecolor="#303030", linewidth=0.55, zorder=1)
    districts.boundary.plot(ax=ax, color="#929292", linewidth=0.35, zorder=2)
    order = np.argsort(flows)
    collection = LineCollection(
        [segments[index] for index in order],
        linewidths=widths[order],
        colors="#C7472D",
        zorder=3,
    )
    collection.set_alpha(alphas[order])
    ax.add_collection(collection)

    destination_flow = pairs.groupby("school_index")["flow"].sum()
    destination_points = school_lookup.loc[destination_flow.index]
    point_sizes = scaled_widths(destination_flow.to_numpy(dtype="float64"), 5.0, 42.0)
    ax.scatter(
        destination_points.geometry.x,
        destination_points.geometry.y,
        s=point_sizes,
        color="#246B8E",
        edgecolor="white",
        linewidth=0.35,
        alpha=0.88,
        zorder=5,
        label="Exact EDB school location",
    )

    legend_values = [float(np.quantile(flows, 0.10)), float(np.median(flows)), float(flows.max())]
    legend_widths = scaled_widths(np.asarray(legend_values), 0.5, 3.0).tolist()
    handles = flow_legend(legend_values, legend_widths, "#C7472D", unit)
    handles.append(
        Line2D(
            [0],
            [0],
            marker="o",
            linestyle="none",
            markerfacecolor="#246B8E",
            markeredgecolor="white",
            markersize=6,
            label="Exact EDB school location",
        )
    )
    ax.legend(
        handles=handles,
        title="Flow encoding",
        loc="upper right",
        frameon=True,
        framealpha=0.93,
        fontsize=8,
        title_fontsize=8,
    )
    total = float(pairs.attrs["all_exact_flow_sum"])
    captured = float(flows.sum() / total) if total > 0 else 0.0
    ax.set_title(
        f"Hong Kong {title}: home grid to exact school locations\n"
        f"Top {len(pairs):,} pairs, {captured:.1%} of mapped {unit}",
        fontsize=14,
        pad=10,
    )
    ax.text(
        0.01,
        0.015,
        "Origins are residential grid centroids; blue endpoints are exact Education Bureau school coordinates.",
        transform=ax.transAxes,
        fontsize=8,
        color="#303030",
    )
    ax.set_axis_off()
    ax.set_aspect("equal")
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    school_rows = school_lookup.loc[pairs["school_index"]]
    pairs = pairs.copy()
    pairs["origin_grid_id"] = grid.iloc[pairs["origin_index"]]["grid_id"].to_numpy()
    pairs["school_no"] = school_rows["SCHOOL NO."].astype(str).to_numpy()
    pairs["campus_id"] = school_rows["campus_id"].astype(str).to_numpy()
    pairs["school_name_en"] = school_rows["ENGLISH NAME"].astype(str).to_numpy()
    pairs["destination_grid_id"] = school_rows["grid_id"].to_numpy(dtype=int)
    pairs["school_x_epsg32650"] = school_rows.geometry.x.to_numpy()
    pairs["school_y_epsg32650"] = school_rows.geometry.y.to_numpy()
    return pairs, {
        "exact_school_flow_total": total,
        "top_exact_school_flow_sum": float(flows.sum()),
        "top_exact_school_flow_share": captured,
        "top_exact_school_unique_schools": int(pairs["school_index"].nunique()),
    }


def plot_grid_flows(
    matrix: np.ndarray,
    grid: gpd.GeoDataFrame,
    boundary: gpd.GeoDataFrame,
    districts: gpd.GeoDataFrame,
    count: int,
    title: str,
    unit: str,
    out_path: Path,
) -> tuple[pd.DataFrame, dict[str, float]]:
    pairs = top_pairs(matrix, count)
    centroids = grid.geometry.centroid
    segments = [
        [
            (centroids.iloc[int(row.origin_index)].x, centroids.iloc[int(row.origin_index)].y),
            (centroids.iloc[int(row.destination_index)].x, centroids.iloc[int(row.destination_index)].y),
        ]
        for row in pairs.itertuples(index=False)
    ]
    flows = pairs["flow"].to_numpy(dtype="float64")
    widths = scaled_widths(flows, 0.12, 2.8)
    alphas = 0.06 + 0.50 * (widths - widths.min()) / max(float(widths.max() - widths.min()), 1e-9)

    fig, ax = plt.subplots(figsize=(12, 9), dpi=220)
    boundary.plot(ax=ax, facecolor="#f0f2ef", edgecolor="#303030", linewidth=0.55, zorder=1)
    districts.boundary.plot(ax=ax, color="#929292", linewidth=0.35, zorder=2)
    order = np.argsort(flows)
    collection = LineCollection(
        [segments[index] for index in order],
        linewidths=widths[order],
        colors="#C7472D",
        zorder=3,
    )
    collection.set_alpha(alphas[order])
    ax.add_collection(collection)

    legend_values = [float(np.quantile(flows, 0.10)), float(np.median(flows)), float(flows.max())]
    legend_widths = scaled_widths(np.asarray(legend_values), 0.5, 3.0).tolist()
    ax.legend(
        handles=flow_legend(legend_values, legend_widths, "#C7472D", unit),
        title="OD pair flow",
        loc="upper right",
        frameon=True,
        framealpha=0.93,
        fontsize=8,
        title_fontsize=8,
    )
    diagonal = float(np.trace(matrix))
    inter_grid = float(matrix.sum() - diagonal)
    captured = float(flows.sum() / inter_grid) if inter_grid > 0 else 0.0
    ax.set_title(
        f"Hong Kong {title}: grid OD straight-line flows\n"
        f"Top {len(pairs):,} off-diagonal pairs, {captured:.1%} of inter-grid {unit}",
        fontsize=14,
        pad=10,
    )
    ax.text(
        0.01,
        0.015,
        "Line width and opacity increase with flow; same-grid flows are excluded from lines.",
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
        "total_flow": float(matrix.sum()),
        "same_grid_flow": diagonal,
        "inter_grid_flow": inter_grid,
        "top_grid_flow_sum": float(flows.sum()),
        "top_grid_flow_share_of_inter_grid": captured,
    }


def district_matrix(matrix: np.ndarray, assignment: pd.DataFrame) -> tuple[list[str], np.ndarray]:
    names = sorted(assignment["dc_eng"].unique().tolist())
    if len(names) != 18:
        raise ValueError(f"Expected 18 district assignments, got {len(names)}")
    indices = assignment["dc_eng"].map({name: idx for idx, name in enumerate(names)}).to_numpy(dtype=int)
    membership = np.eye(len(names), dtype="float64")[indices]
    return names, membership.T @ matrix.astype("float64") @ membership


def district_nodes(
    districts: gpd.GeoDataFrame, names: list[str]
) -> tuple[dict[str, tuple[float, float]], dict[str, str]]:
    indexed = districts.set_index("dc_eng")
    points = indexed.geometry.representative_point()
    positions = {name: (float(points.loc[name].x), float(points.loc[name].y)) for name in names}
    codes = {name: str(indexed.loc[name, "dc_class"]) for name in names}
    return positions, codes


def grid_district_assignment(
    grid: gpd.GeoDataFrame,
    districts: gpd.GeoDataFrame,
    optional_path: Path,
) -> pd.DataFrame:
    if optional_path.exists():
        if optional_path.suffix.lower() == ".parquet":
            crosswalk = pd.read_parquet(optional_path)
            required = {"grid_id", "dc_eng", "raw_school_age", "piece_area_m2"}
            if not required.issubset(crosswalk.columns):
                raise ValueError(f"Population crosswalk lacks required columns: {optional_path}")
            assignment = (
                crosswalk.sort_values(
                    ["grid_id", "raw_school_age", "piece_area_m2"],
                    ascending=[True, False, False],
                )
                .drop_duplicates("grid_id")
                [["grid_id", "dc_eng"]]
                .sort_values("grid_id")
                .reset_index(drop=True)
            )
        else:
            assignment = pd.read_csv(optional_path).sort_values("grid_id").reset_index(drop=True)
        if "dc_eng" not in assignment:
            raise ValueError(f"Grid assignment lacks dc_eng: {optional_path}")
        return assignment[["grid_id", "dc_eng"]]
    points = gpd.GeoDataFrame(
        {"grid_id": grid["grid_id"].to_numpy()},
        geometry=grid.geometry.centroid,
        crs=grid.crs,
    )
    assignment = gpd.sjoin(
        points,
        districts[["dc_eng", "geometry"]],
        how="left",
        predicate="within",
    ).drop(columns="index_right")
    if assignment["dc_eng"].isna().any():
        missing = assignment["dc_eng"].isna()
        nearest = gpd.sjoin_nearest(
            assignment.loc[missing, ["grid_id", "geometry"]],
            districts[["dc_eng", "geometry"]],
            how="left",
        )
        assignment.loc[missing, "dc_eng"] = nearest.set_index("grid_id").loc[
            assignment.loc[missing, "grid_id"], "dc_eng"
        ].to_numpy()
    if assignment["grid_id"].duplicated().any() or assignment["dc_eng"].isna().any():
        raise ValueError("Could not construct a unique district assignment for every grid")
    return assignment[["grid_id", "dc_eng"]].sort_values("grid_id").reset_index(drop=True)


def plot_district_flows(
    names: list[str],
    matrix: np.ndarray,
    districts: gpd.GeoDataFrame,
    count: int,
    title: str,
    unit: str,
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
    for index in np.argsort(flows):
        row = pairs.iloc[int(index)]
        origin = names[int(row.origin_index)]
        destination = names[int(row.destination_index)]
        ax.add_patch(
            FancyArrowPatch(
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
        )

    for index, name in enumerate(names):
        x, y = positions[name]
        ax.scatter(
            x,
            y,
            s=node_sizes[index],
            color="#246B8E",
            edgecolor="white",
            linewidth=1.0,
            alpha=0.92,
            zorder=5,
        )
        label = ax.text(x, y, codes[name], ha="center", va="center", color="white", fontsize=7, zorder=6)
        label.set_path_effects([patheffects.withStroke(linewidth=1.0, foreground="#17485F")])

    legend_values = [float(np.quantile(flows, 0.10)), float(np.median(flows)), float(flows.max())]
    legend_widths = scaled_widths(np.asarray(legend_values), 0.8, 5.0).tolist()
    handles = flow_legend(legend_values, legend_widths, "#B33B24", unit)
    handles.append(
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
    )
    ax.legend(
        handles=handles,
        title="Flow encoding",
        loc="upper right",
        frameon=True,
        framealpha=0.94,
        fontsize=8,
        title_fontsize=8,
    )
    inter = float(matrix.sum() - np.trace(matrix))
    captured = float(flows.sum() / inter) if inter > 0 else 0.0
    code_items = [f"{codes[name]} {name}" for name in sorted(names, key=lambda item: codes[item])]
    code_key = "\n".join("   ".join(code_items[start : start + 6]) for start in range(0, len(code_items), 6))
    ax.set_title(
        f"Hong Kong {title}: 18-district OD flows\n"
        f"Top {len(pairs)} directed links, {captured:.1%} of inter-district {unit}",
        fontsize=14,
        pad=10,
    )
    ax.text(
        0.5,
        -0.035,
        "Arrow direction is home to school; width indicates flow. Node size indicates within-district flow.\n"
        + code_key,
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
        "district_inter_flow": inter,
        "top_district_flow_sum": float(flows.sum()),
        "top_district_flow_share_of_inter": captured,
    }


def main() -> None:
    args = parse_args()
    required = [
        args.student_assignment,
        args.mechanized_home_to_school,
        args.grid,
        args.fixed_link_boundary,
        args.district_boundary,
        args.grid_school,
        args.schools,
    ]
    for path in required:
        if not path.exists():
            raise FileNotFoundError(path)

    grid = gpd.read_file(args.grid).sort_values("grid_id").reset_index(drop=True).to_crs(MODEL_CRS)
    if len(grid) != 1585 or not np.array_equal(grid["grid_id"].to_numpy(), np.arange(len(grid))):
        raise ValueError("Grid must contain contiguous grid_id values 0..1584")
    boundary = gpd.read_file(args.fixed_link_boundary).to_crs(MODEL_CRS)
    districts = gpd.read_file(args.district_boundary)[["dc_class", "dc_eng", "geometry"]].to_crs(MODEL_CRS)
    if len(districts) != 18:
        raise ValueError(f"Expected 18 district polygons, got {len(districts)}")
    assignment = grid_district_assignment(grid, districts, args.grid_assignment)
    if not np.array_equal(assignment["grid_id"].to_numpy(), grid["grid_id"].to_numpy()):
        raise ValueError("District assignment is not aligned with the grid")
    grid_school = load_npz(args.grid_school).tocsr()
    schools = gpd.read_file(args.schools).to_crs(MODEL_CRS)
    if grid_school.shape[0] != len(grid):
        raise ValueError(f"Grid-school matrix is not aligned with the grid: {grid_school.shape}")
    if schools["school_index"].duplicated().any() or int(schools["school_index"].max()) >= grid_school.shape[1]:
        raise ValueError("School locations are not aligned with grid-school matrix columns")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    product_paths = {
        "student_assignment": args.student_assignment,
        "mechanized_home_to_school": args.mechanized_home_to_school,
    }
    student_grid_matrix = np.load(args.student_assignment, mmap_mode="r")
    all_summary: dict[str, object] = {
        "grid_count": len(grid),
        "top_grid_flows": args.top_grid_flows,
        "top_district_flows": args.top_district_flows,
        "products": {},
    }
    for key, path in product_paths.items():
        metadata = DEFAULT_PRODUCTS[key]
        matrix = np.load(path, mmap_mode="r")
        if matrix.shape != (len(grid), len(grid)) or not np.isfinite(matrix).all() or np.any(matrix < 0):
            raise ValueError(f"Invalid OD matrix: {path}")
        exact_pairs = exact_school_flows(
            grid_school,
            schools,
            args.top_grid_flows,
            str(metadata["unit"]),
            grid_grid_matrix=matrix if key == "mechanized_home_to_school" else None,
            student_grid_matrix=student_grid_matrix if key == "mechanized_home_to_school" else None,
        )
        grid_pairs, grid_summary = plot_exact_school_flows(
            exact_pairs,
            grid,
            schools,
            boundary,
            districts,
            str(metadata["title"]),
            str(metadata["unit"]),
            args.out_dir / f"hong_kong_{key}_home_grid_to_exact_school_top{args.top_grid_flows}.png",
        )
        names, aggregated = district_matrix(matrix, assignment)
        district_pairs, district_summary = plot_district_flows(
            names,
            aggregated,
            districts,
            args.top_district_flows,
            str(metadata["title"]),
            str(metadata["unit"]),
            args.out_dir / f"hong_kong_{key}_18_district_od_flows.png",
        )
        grid_pairs.to_csv(
            args.out_dir / f"hong_kong_{key}_top{args.top_grid_flows}_exact_school_flows.csv",
            index=False,
            encoding="utf-8-sig",
        )
        district_pairs.to_csv(
            args.out_dir / f"hong_kong_{key}_top_18_district_od_flows.csv",
            index=False,
            encoding="utf-8-sig",
        )
        pd.DataFrame(aggregated, index=names, columns=names).to_csv(
            args.out_dir / f"hong_kong_{key}_18_district_od_matrix.csv",
            encoding="utf-8-sig",
        )
        all_summary["products"][key] = {
            "matrix": str(path),
            "unit": metadata["unit"],
            **grid_summary,
            **district_summary,
        }

    summary_path = args.out_dir / "hong_kong_student_school_flow_maps_summary.json"
    summary_path.write_text(json.dumps(all_summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(all_summary, indent=2, ensure_ascii=False))
    print(f"Wrote outputs to: {args.out_dir}")


if __name__ == "__main__":
    main()
