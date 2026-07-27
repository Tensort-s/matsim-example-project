#!/usr/bin/env python3
"""Measure LSUG/grid population mixing and the grid-resolution error floor."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path

_RASTERIO_SPEC = importlib.util.find_spec("rasterio")
if _RASTERIO_SPEC and _RASTERIO_SPEC.origin:
    _RASTERIO_DIR = Path(_RASTERIO_SPEC.origin).resolve().parent
    os.environ["PROJ_DATA"] = str(_RASTERIO_DIR / "proj_data")
    os.environ["PROJ_LIB"] = str(_RASTERIO_DIR / "proj_data")
    os.environ["GDAL_DATA"] = str(_RASTERIO_DIR / "gdal_data")

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from scipy.optimize import lsq_linear
from scipy.sparse import coo_matrix, csr_matrix, diags, save_npz
from shapely.geometry import box
from shapely.prepared import prep


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BASE = ROOT / "data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid"
DEFAULT_GRID = DEFAULT_BASE / "CityAndRegionSplit/hong_kong_fixed_link_grid/regions.shp"
DEFAULT_LSUG = (
    ROOT
    / "data/gee/hongkong/worldpop_age_sex"
    / "2021_Population_Census_Statistics_ LargeSubunitGroups/LSUG_21C_converted.shp"
)
DEFAULT_RASTER = (
    ROOT
    / "data/gee/hongkong/worldpop_age_sex/census_calibrated"
    / "worldpop_HKG_2021_census_lsug_calibrated_fixed_link_boundary.tif"
)
DEFAULT_OUT_DIR = DEFAULT_BASE / "census_2021_commute_constraints/lsug_grid_resolution_diagnostics"

FLOW_FIELDS = ["plw_hk", "plw_kln", "plw_nt"]
FLOW_LABELS = {
    "plw_hk": "Hong Kong Island",
    "plw_kln": "Kowloon",
    "plw_nt": "New Territories",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grid", type=Path, default=DEFAULT_GRID)
    parser.add_argument("--lsug", type=Path, default=DEFAULT_LSUG)
    parser.add_argument("--population-raster", type=Path, default=DEFAULT_RASTER)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--significant-share",
        type=float,
        default=0.01,
        help="Minimum population share used when counting significant overlaps.",
    )
    parser.add_argument(
        "--full-coverage-threshold",
        type=float,
        default=0.90,
        help="Minimum modeled Census population fraction for the primary error metrics.",
    )
    parser.add_argument(
        "--compute-lower-bound",
        action="store_true",
        help="Also run the expensive non-negative grid-fit lower-bound diagnostic.",
    )
    parser.add_argument(
        "--candidate-cell-sizes",
        type=float,
        nargs="*",
        default=[750.0, 700.0],
        help="Optional candidate square-grid cell sizes in metres for round-trip comparison.",
    )
    return parser.parse_args()


def numeric_series(series: pd.Series) -> np.ndarray:
    return (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.strip()
        .replace({"-": "0", "": "0", "nan": "0", "None": "0"})
        .astype(float)
        .to_numpy()
    )


def make_valid(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = gdf.copy()
    invalid = ~out.geometry.is_valid
    if invalid.any():
        out.loc[invalid, "geometry"] = out.loc[invalid, "geometry"].make_valid()
    return out.loc[out.geometry.notna() & ~out.geometry.is_empty].copy()


def population_overlap_matrix(
    lsug: gpd.GeoDataFrame,
    grid: gpd.GeoDataFrame,
    raster_path: Path,
) -> tuple[csr_matrix, dict]:
    with rasterio.open(raster_path) as src:
        population = src.read(1, masked=True).filled(0).astype("float64")
        population = np.where(np.isfinite(population) & (population > 0), population, 0.0)
        shape = (src.height, src.width)
        transform = src.transform
        raster_crs = src.crs

    if raster_crs is None:
        raise ValueError(f"Population raster has no CRS: {raster_path}")

    lsug_raster = make_valid(lsug.to_crs(raster_crs))
    grid_raster = make_valid(grid.to_crs(raster_crs))
    if len(lsug_raster) != len(lsug) or len(grid_raster) != len(grid):
        raise ValueError("Geometry cleanup unexpectedly removed LSUG or grid rows.")

    lsug_ids = rasterize(
        ((geom, idx + 1) for idx, geom in enumerate(lsug_raster.geometry)),
        out_shape=shape,
        transform=transform,
        fill=0,
        dtype="int32",
        all_touched=False,
    )
    grid_ids = rasterize(
        ((geom, idx + 1) for idx, geom in enumerate(grid_raster.geometry)),
        out_shape=shape,
        transform=transform,
        fill=0,
        dtype="int32",
        all_touched=False,
    )

    positive = population > 0
    assigned = positive & (lsug_ids > 0) & (grid_ids > 0)
    rows = lsug_ids[assigned].astype("int64") - 1
    cols = grid_ids[assigned].astype("int64") - 1
    weights = population[assigned]
    overlap = coo_matrix((weights, (rows, cols)), shape=(len(lsug), len(grid))).tocsr()
    overlap.sum_duplicates()

    raster_total = float(population[positive].sum())
    assigned_total = float(weights.sum())
    qa = {
        "raster_shape": list(shape),
        "raster_crs": str(raster_crs),
        "positive_population_pixels": int(positive.sum()),
        "assigned_population_pixels": int(assigned.sum()),
        "raster_population_total": raster_total,
        "assigned_population_total": assigned_total,
        "assigned_population_share": assigned_total / raster_total if raster_total else 0.0,
    }
    return overlap, qa


def weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    mask = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    if not mask.any():
        return float("nan")
    values = values[mask]
    weights = weights[mask]
    order = np.argsort(values)
    values = values[order]
    cumulative = np.cumsum(weights[order])
    return float(values[np.searchsorted(cumulative, q * cumulative[-1], side="left")])


def mixing_table(
    matrix: csr_matrix,
    row_ids: pd.Series,
    significant_share: float,
    axis_name: str,
) -> pd.DataFrame:
    totals = np.asarray(matrix.sum(axis=1)).ravel()
    rows: list[dict] = []
    for idx in range(matrix.shape[0]):
        start, end = matrix.indptr[idx], matrix.indptr[idx + 1]
        values = matrix.data[start:end]
        total = totals[idx]
        shares = values / total if total > 0 else np.zeros_like(values)
        positive = shares > 0
        entropy = float(-(shares[positive] * np.log(shares[positive])).sum()) if positive.any() else 0.0
        rows.append(
            {
                axis_name: row_ids.iloc[idx],
                "population": float(total),
                "overlap_count": int(len(values)),
                "significant_overlap_count": int(np.count_nonzero(shares >= significant_share)),
                "dominant_population_share": float(shares.max()) if len(shares) else 0.0,
                "effective_overlap_count": float(np.exp(entropy)) if len(shares) else 0.0,
            }
        )
    return pd.DataFrame(rows)


def build_crosswalk_tables(
    overlap: csr_matrix,
    lsug: gpd.GeoDataFrame,
    grid: gpd.GeoDataFrame,
    significant_share: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    grid_mixing = mixing_table(overlap.transpose().tocsr(), grid["grid_id"], significant_share, "grid_id")
    lsug_fragmentation = mixing_table(overlap, lsug["lsbg"].astype(str), significant_share, "lsbg")

    lsug_totals = np.asarray(overlap.sum(axis=1)).ravel()
    grid_totals = np.asarray(overlap.sum(axis=0)).ravel()
    coo = overlap.tocoo()
    entries = pd.DataFrame(
        {
            "lsug_index": coo.row,
            "grid_index": coo.col,
            "population": coo.data,
        }
    )
    entries["lsbg"] = lsug.iloc[coo.row]["lsbg"].astype(str).to_numpy()
    entries["grid_id"] = grid.iloc[coo.col]["grid_id"].to_numpy()
    entries["share_of_lsug_population"] = np.divide(
        coo.data,
        lsug_totals[coo.row],
        out=np.zeros_like(coo.data),
        where=lsug_totals[coo.row] > 0,
    )
    entries["share_of_grid_population"] = np.divide(
        coo.data,
        grid_totals[coo.col],
        out=np.zeros_like(coo.data),
        where=grid_totals[coo.col] > 0,
    )
    entries = entries[
        [
            "lsbg",
            "grid_id",
            "population",
            "share_of_lsug_population",
            "share_of_grid_population",
            "lsug_index",
            "grid_index",
        ]
    ].sort_values(["grid_id", "population"], ascending=[True, False])
    return grid_mixing, lsug_fragmentation, entries


def roundtrip_reconstruction(overlap: csr_matrix, target: np.ndarray) -> tuple[np.ndarray, csr_matrix, csr_matrix]:
    lsug_population = np.asarray(overlap.sum(axis=1)).ravel()
    grid_population = np.asarray(overlap.sum(axis=0)).ravel()

    lsug_to_grid = overlap.transpose().tocsr() @ diags(
        np.divide(1.0, lsug_population, out=np.zeros_like(lsug_population), where=lsug_population > 0)
    )
    grid_to_lsug = overlap @ diags(
        np.divide(1.0, grid_population, out=np.zeros_like(grid_population), where=grid_population > 0)
    )
    grid_flows = lsug_to_grid @ target
    reconstructed = grid_to_lsug @ grid_flows
    return np.asarray(reconstructed), grid_to_lsug.tocsr(), lsug_to_grid.tocsr()


def reconstruction_metrics(target: np.ndarray, predicted: np.ndarray, mask: np.ndarray) -> dict:
    target = target[mask].astype("float64")
    predicted = predicted[mask].astype("float64")
    error = predicted - target
    absolute = np.abs(error)
    target_total = float(target.sum())
    row_target = target.sum(axis=1)
    row_predicted = predicted.sum(axis=1)
    valid_share = (row_target > 0) & (row_predicted > 0)
    target_share = np.divide(target, row_target[:, None], out=np.zeros_like(target), where=row_target[:, None] > 0)
    predicted_share = np.divide(
        predicted,
        row_predicted[:, None],
        out=np.zeros_like(predicted),
        where=row_predicted[:, None] > 0,
    )
    share_abs = np.abs(predicted_share - target_share)
    weights = row_target[valid_share]
    weighted_share_mae = (
        float(np.average(share_abs[valid_share].mean(axis=1), weights=weights)) if weights.sum() > 0 else float("nan")
    )
    weighted_tvd = (
        float(np.average(0.5 * share_abs[valid_share].sum(axis=1), weights=weights))
        if weights.sum() > 0
        else float("nan")
    )
    centered = target - target.mean(axis=0, keepdims=True)
    ss_total = float(np.square(centered).sum())
    return {
        "lsug_count": int(mask.sum()),
        "target_workers": target_total,
        "predicted_workers": float(predicted.sum()),
        "cell_mae_workers": float(absolute.mean()),
        "cell_rmse_workers": float(np.sqrt(np.square(error).mean())),
        "cell_wape": float(absolute.sum() / target_total) if target_total > 0 else float("nan"),
        "r_squared": float(1.0 - np.square(error).sum() / ss_total) if ss_total > 0 else float("nan"),
        "origin_total_mae_workers": float(np.abs(row_predicted - row_target).mean()),
        "origin_total_wape": (
            float(np.abs(row_predicted - row_target).sum() / row_target.sum()) if row_target.sum() > 0 else float("nan")
        ),
        "destination_share_mae_pp_unweighted": float(share_abs[valid_share].mean() * 100.0),
        "destination_share_mae_pp_worker_weighted": weighted_share_mae * 100.0,
        "destination_share_tvd_pp_worker_weighted": weighted_tvd * 100.0,
    }


def lower_bound_reconstruction(
    grid_to_lsug: csr_matrix,
    target: np.ndarray,
    mask: np.ndarray,
) -> tuple[np.ndarray, list[dict]]:
    design = grid_to_lsug[mask]
    predicted = np.zeros_like(target, dtype="float64")
    solver_rows: list[dict] = []
    for col, field in enumerate(FLOW_FIELDS):
        values = target[mask, col]
        scale = max(float(values.max()), 1.0)
        result = lsq_linear(
            design,
            values / scale,
            bounds=(0.0, np.inf),
            tol=1e-7,
            lsmr_tol=1e-7,
            max_iter=500,
            verbose=0,
        )
        predicted[:, col] = grid_to_lsug @ (result.x * scale)
        solver_rows.append(
            {
                "field": field,
                "destination": FLOW_LABELS[field],
                "success": bool(result.success),
                "status": int(result.status),
                "cost": float(result.cost),
                "optimality": float(result.optimality),
                "iterations": int(result.nit),
            }
        )
    return predicted, solver_rows


def build_candidate_grid(grid: gpd.GeoDataFrame, cell_size_m: float) -> gpd.GeoDataFrame:
    if cell_size_m <= 0:
        raise ValueError("Candidate cell sizes must be positive.")
    metric = grid.to_crs("EPSG:32650")
    if hasattr(metric.geometry, "union_all"):
        boundary = metric.geometry.union_all()
    else:
        boundary = metric.geometry.unary_union
    prepared_boundary = prep(boundary)
    minx, miny, maxx, maxy = boundary.bounds
    records: list[dict] = []
    col = 0
    x = minx
    while x < maxx:
        row = 0
        y = miny
        while y < maxy:
            square = box(x, y, x + cell_size_m, y + cell_size_m)
            if prepared_boundary.intersects(square):
                records.append({"col": col, "row": row, "geometry": square})
            row += 1
            y = miny + row * cell_size_m
        col += 1
        x = minx + col * cell_size_m
    candidate = gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:32650")
    candidate = candidate.sort_values(["col", "row"]).reset_index(drop=True)
    candidate["grid_id"] = np.arange(len(candidate), dtype="int64")
    return candidate[["grid_id", "col", "row", "geometry"]]


def summarize_grid_mixing(grid_mixing: pd.DataFrame) -> dict:
    grid_population = grid_mixing["population"].to_numpy(dtype="float64")
    populated = grid_population > 0
    population_total = float(grid_population.sum())
    dominant = grid_mixing["dominant_population_share"].to_numpy(dtype="float64")
    return {
        "grid_count": int(len(grid_mixing)),
        "populated_grid_count": int(populated.sum()),
        "median_significant_lsug_count_per_populated_grid": float(
            grid_mixing.loc[populated, "significant_overlap_count"].median()
        ),
        "p90_significant_lsug_count_per_populated_grid": float(
            grid_mixing.loc[populated, "significant_overlap_count"].quantile(0.90)
        ),
        "max_significant_lsug_count_per_grid": int(grid_mixing["significant_overlap_count"].max()),
        "population_weighted_median_dominant_lsug_share": weighted_quantile(dominant, grid_population, 0.50),
        "population_weighted_p10_dominant_lsug_share": weighted_quantile(dominant, grid_population, 0.10),
        "population_share_in_grids_dominant_lsug_below_0_8": (
            float(grid_population[dominant < 0.8].sum() / population_total) if population_total else 0.0
        ),
        "population_share_in_grids_dominant_lsug_below_0_5": (
            float(grid_population[dominant < 0.5].sum() / population_total) if population_total else 0.0
        ),
    }


def choose_resolution(metrics: dict, mixing: dict) -> dict:
    share_mae = metrics["destination_share_mae_pp_worker_weighted"]
    wape = metrics["cell_wape"]
    mixed_population = mixing["population_share_in_grids_dominant_lsug_below_0_8"]
    if share_mae <= 2.0 and wape <= 0.08:
        code = "retain_current_grid"
        text = "Retain the current grid; population-weighted crosswalking loses little LSUG commute information."
    elif share_mae <= 5.0 and wape <= 0.15:
        code = "retain_and_test_finer_grid"
        text = "Retain the current grid for the first calibrator, but compare a 700-750 m candidate grid."
    else:
        code = "replace_with_finer_grid"
        text = "The current grid imposes a material LSUG reconstruction error; use a finer grid before calibration."
    return {
        "decision_code": code,
        "decision": text,
        "roundtrip_worker_weighted_share_mae_pp": share_mae,
        "roundtrip_cell_wape": wape,
        "mixed_grid_population_share_dominant_lsug_below_0_8": mixed_population,
        "thresholds": {
            "retain": "weighted share MAE <= 2 pp and cell WAPE <= 8%",
            "borderline": "weighted share MAE <= 5 pp and cell WAPE <= 15%",
            "replace": "above the borderline thresholds",
        },
        "caveat": "This decision isolates origin-side LSUG/grid resolution loss; it does not validate WEDAN scalers or destination-grid allocation within the three workplace regions.",
    }


def save_plot(
    grid_mixing: pd.DataFrame,
    lsug_results: pd.DataFrame,
    primary_mask: np.ndarray,
    out_path: Path,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(12, 9), dpi=180)
    populated_grid = grid_mixing[grid_mixing["population"] > 0]
    axes[0, 0].hist(populated_grid["dominant_population_share"], bins=np.linspace(0, 1, 21), color="#287271")
    axes[0, 0].set_title("Dominant LSUG population share per grid")
    axes[0, 0].set_xlabel("Dominant share")
    axes[0, 0].set_ylabel("Grid count")

    max_count = int(max(10, populated_grid["significant_overlap_count"].quantile(0.99)))
    axes[0, 1].hist(
        populated_grid["significant_overlap_count"].clip(upper=max_count),
        bins=np.arange(0.5, max_count + 1.5),
        color="#E76F51",
    )
    axes[0, 1].set_title("Significant LSUGs per populated grid")
    axes[0, 1].set_xlabel("Count (>=1% of grid population)")
    axes[0, 1].set_ylabel("Grid count")

    selected = lsug_results.loc[primary_mask]
    colors = ["#264653", "#E9C46A", "#D1495B"]
    for field, color in zip(FLOW_FIELDS, colors, strict=True):
        axes[1, 0].scatter(
            selected[f"true_{field}"],
            selected[f"roundtrip_{field}"],
            s=7,
            alpha=0.35,
            color=color,
            label=FLOW_LABELS[field],
        )
    limit = max(selected[[f"true_{field}" for field in FLOW_FIELDS]].to_numpy().max(), 1.0)
    axes[1, 0].plot([0, limit], [0, limit], color="black", linewidth=1)
    axes[1, 0].set_xlim(0, limit)
    axes[1, 0].set_ylim(0, limit)
    axes[1, 0].set_title("LSUG flows after grid round trip")
    axes[1, 0].set_xlabel("Census workers")
    axes[1, 0].set_ylabel("Reconstructed workers")
    axes[1, 0].legend(frameon=False, fontsize=8)

    axes[1, 1].scatter(
        selected["fixed_workplace_workers_model_boundary"],
        selected["destination_share_mae_pp_roundtrip"],
        s=8,
        alpha=0.4,
        color="#6A4C93",
    )
    axes[1, 1].set_xscale("log")
    axes[1, 1].set_title("Share error by LSUG commuter count")
    axes[1, 1].set_xlabel("Fixed-workplace workers (log scale)")
    axes[1, 1].set_ylabel("Destination-share MAE (percentage points)")

    fig.suptitle("Hong Kong LSUG / fixed-link grid resolution diagnostics", fontsize=14)
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    args = parse_args()
    for path in [args.grid, args.lsug, args.population_raster]:
        if not path.exists():
            raise FileNotFoundError(path)
    if not 0 < args.significant_share < 1:
        raise ValueError("--significant-share must be between 0 and 1.")

    grid = gpd.read_file(args.grid).sort_values("grid_id").reset_index(drop=True)
    lsug = gpd.read_file(args.lsug).sort_values("lsbg").reset_index(drop=True)
    required_grid = {"grid_id", "geometry"}
    required_lsug = {"lsbg", "t_pop", *FLOW_FIELDS, "geometry"}
    if missing := required_grid - set(grid.columns):
        raise ValueError(f"Grid is missing fields: {sorted(missing)}")
    if missing := required_lsug - set(lsug.columns):
        raise ValueError(f"LSUG is missing fields: {sorted(missing)}")

    for field in ["t_pop", *FLOW_FIELDS]:
        lsug[field] = numeric_series(lsug[field])
    overlap, raster_qa = population_overlap_matrix(lsug, grid, args.population_raster)
    grid_mixing, lsug_fragmentation, overlap_entries = build_crosswalk_tables(
        overlap, lsug, grid, args.significant_share
    )

    lsug_population = np.asarray(overlap.sum(axis=1)).ravel()
    census_population = lsug["t_pop"].to_numpy(dtype="float64")
    modeled_fraction = np.divide(
        lsug_population,
        census_population,
        out=np.zeros_like(lsug_population),
        where=census_population > 0,
    )
    modeled_fraction = np.clip(modeled_fraction, 0.0, 1.0)
    census_target = lsug[FLOW_FIELDS].to_numpy(dtype="float64")
    target = census_target * modeled_fraction[:, None]

    reconstructed, grid_to_lsug, lsug_to_grid = roundtrip_reconstruction(overlap, target)
    represented = (lsug_population > 0) & (target.sum(axis=1) > 0)
    primary = represented & (modeled_fraction >= args.full_coverage_threshold)
    if not primary.any():
        raise ValueError("No LSUG rows satisfy the primary coverage threshold.")

    city_shares = target[primary].sum(axis=0) / target[primary].sum()
    baseline = target.sum(axis=1, keepdims=True) * city_shares[None, :]
    lower_bound = None
    solver_rows: list[dict] = []
    if args.compute_lower_bound:
        lower_bound, solver_rows = lower_bound_reconstruction(grid_to_lsug, target, primary)

    lsug_results = lsug[["lsbg"]].copy()
    for optional in ["lsbg_eng", "lsbg_chi"]:
        if optional in lsug.columns:
            lsug_results[optional] = lsug[optional]
    lsug_results["census_population"] = census_population
    lsug_results["population_in_model_boundary"] = lsug_population
    lsug_results["modeled_population_fraction"] = modeled_fraction
    lsug_results["fixed_workplace_workers_model_boundary"] = target.sum(axis=1)
    lsug_results["represented_in_grid"] = represented
    lsug_results["primary_full_coverage_qa"] = primary
    for idx, field in enumerate(FLOW_FIELDS):
        lsug_results[f"true_{field}"] = target[:, idx]
        lsug_results[f"roundtrip_{field}"] = reconstructed[:, idx]
        lsug_results[f"baseline_{field}"] = baseline[:, idx]
        if lower_bound is not None:
            lsug_results[f"lower_bound_{field}"] = lower_bound[:, idx]
    target_rows = target.sum(axis=1)
    reconstructed_rows = reconstructed.sum(axis=1)
    target_shares = np.divide(target, target_rows[:, None], out=np.zeros_like(target), where=target_rows[:, None] > 0)
    reconstructed_shares = np.divide(
        reconstructed,
        reconstructed_rows[:, None],
        out=np.zeros_like(reconstructed),
        where=reconstructed_rows[:, None] > 0,
    )
    lsug_results["destination_share_mae_pp_roundtrip"] = (
        np.abs(reconstructed_shares - target_shares).mean(axis=1) * 100.0
    )

    grid_population = grid_mixing["population"].to_numpy(dtype="float64")
    populated = grid_population > 0
    grid_mix_summary = summarize_grid_mixing(grid_mixing)

    primary_metrics = reconstruction_metrics(target, reconstructed, primary)
    represented_metrics = reconstruction_metrics(target, reconstructed, represented)
    baseline_metrics = reconstruction_metrics(target, baseline, primary)
    lower_bound_metrics = reconstruction_metrics(target, lower_bound, primary) if lower_bound is not None else None
    decision = choose_resolution(primary_metrics, grid_mix_summary)

    metric_grid = grid.to_crs("EPSG:32650")
    current_cell_size = float(np.sqrt(metric_grid.geometry.area.max()))
    comparison_rows = [
        {
            "cell_size_m": current_cell_size,
            "grid_count": len(grid),
            "populated_grid_count": int(populated.sum()),
            "weighted_destination_share_mae_pp": primary_metrics["destination_share_mae_pp_worker_weighted"],
            "cell_wape": primary_metrics["cell_wape"],
            "origin_total_wape": primary_metrics["origin_total_wape"],
            "population_weighted_median_dominant_lsug_share": grid_mix_summary[
                "population_weighted_median_dominant_lsug_share"
            ],
            "population_share_dominant_lsug_below_0_5": grid_mix_summary[
                "population_share_in_grids_dominant_lsug_below_0_5"
            ],
            "is_current_grid": True,
        }
    ]
    candidate_summaries: list[dict] = []
    for cell_size in args.candidate_cell_sizes:
        if np.isclose(cell_size, current_cell_size):
            continue
        candidate = build_candidate_grid(grid, cell_size)
        candidate_overlap, candidate_raster_qa = population_overlap_matrix(lsug, candidate, args.population_raster)
        candidate_mixing = mixing_table(
            candidate_overlap.transpose().tocsr(),
            candidate["grid_id"],
            args.significant_share,
            "grid_id",
        )
        candidate_reconstructed, _, _ = roundtrip_reconstruction(candidate_overlap, target)
        candidate_metrics = reconstruction_metrics(target, candidate_reconstructed, primary)
        candidate_mix_summary = summarize_grid_mixing(candidate_mixing)
        row = {
            "cell_size_m": float(cell_size),
            "grid_count": len(candidate),
            "populated_grid_count": candidate_mix_summary["populated_grid_count"],
            "weighted_destination_share_mae_pp": candidate_metrics[
                "destination_share_mae_pp_worker_weighted"
            ],
            "cell_wape": candidate_metrics["cell_wape"],
            "origin_total_wape": candidate_metrics["origin_total_wape"],
            "population_weighted_median_dominant_lsug_share": candidate_mix_summary[
                "population_weighted_median_dominant_lsug_share"
            ],
            "population_share_dominant_lsug_below_0_5": candidate_mix_summary[
                "population_share_in_grids_dominant_lsug_below_0_5"
            ],
            "is_current_grid": False,
        }
        comparison_rows.append(row)
        candidate_summaries.append(
            {
                **row,
                "raster_assignment_qa": candidate_raster_qa,
                "grid_mixing": candidate_mix_summary,
                "roundtrip_reconstruction_primary": candidate_metrics,
            }
        )

    resolution_comparison = pd.DataFrame(comparison_rows).sort_values("cell_size_m", ascending=False)
    if candidate_summaries:
        best = min(candidate_summaries, key=lambda item: item["weighted_destination_share_mae_pp"])
        share_reduction = primary_metrics["destination_share_mae_pp_worker_weighted"] - best[
            "weighted_destination_share_mae_pp"
        ]
        relative_share_reduction = share_reduction / primary_metrics["destination_share_mae_pp_worker_weighted"]
        wape_reduction = primary_metrics["cell_wape"] - best["cell_wape"]
        feasible_node_count = best["grid_count"] <= 3000
        materially_better = feasible_node_count and (relative_share_reduction >= 0.20 or wape_reduction >= 0.03)
        decision["candidate_test"] = {
            "best_cell_size_m": best["cell_size_m"],
            "best_grid_count": best["grid_count"],
            "weighted_share_mae_reduction_pp": share_reduction,
            "weighted_share_mae_relative_reduction": relative_share_reduction,
            "cell_wape_reduction": wape_reduction,
            "within_wedan_3000_node_limit": feasible_node_count,
            "material_improvement_rule": "at least 20% share-MAE reduction or 3 percentage-point WAPE reduction",
        }
        if materially_better:
            decision["decision_code"] = "replace_with_finer_grid"
            decision["decision"] = (
                f"Replace the current grid with the tested {best['cell_size_m']:.0f} m grid before final calibration; "
                "it materially reduces LSUG reconstruction loss and remains within 3,000 nodes."
            )
        else:
            decision["decision_code"] = "retain_current_grid"
            decision["decision"] = (
                "Retain the current grid; the tested finer grids do not reduce LSUG reconstruction loss enough to "
                "justify rebuilding every WEDAN feature and distance matrix."
            )

    destination_rows = []
    for idx, field in enumerate(FLOW_FIELDS):
        destination_rows.append(
            {
                "field": field,
                "destination": FLOW_LABELS[field],
                "primary_true_workers": float(target[primary, idx].sum()),
                "primary_roundtrip_workers": float(reconstructed[primary, idx].sum()),
                "primary_mae_workers": float(np.abs(reconstructed[primary, idx] - target[primary, idx]).mean()),
                "primary_wape": float(
                    np.abs(reconstructed[primary, idx] - target[primary, idx]).sum() / target[primary, idx].sum()
                ),
            }
        )
    destination_summary = pd.DataFrame(destination_rows)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    overlap_entries.to_csv(args.out_dir / "lsug_grid_population_overlap.csv", index=False, encoding="utf-8-sig")
    grid_mixing.to_csv(args.out_dir / "grid_population_mixing_metrics.csv", index=False, encoding="utf-8-sig")
    lsug_fragmentation.to_csv(args.out_dir / "lsug_population_fragmentation_metrics.csv", index=False, encoding="utf-8-sig")
    lsug_results.to_csv(args.out_dir / "lsug_roundtrip_reconstruction.csv", index=False, encoding="utf-8-sig")
    destination_summary.to_csv(args.out_dir / "destination_reconstruction_summary.csv", index=False, encoding="utf-8-sig")
    resolution_comparison.to_csv(args.out_dir / "candidate_grid_resolution_comparison.csv", index=False, encoding="utf-8-sig")
    if solver_rows:
        pd.DataFrame(solver_rows).to_csv(args.out_dir / "lower_bound_solver_qa.csv", index=False, encoding="utf-8-sig")
    elif (args.out_dir / "lower_bound_solver_qa.csv").exists():
        (args.out_dir / "lower_bound_solver_qa.csv").unlink()
    save_npz(args.out_dir / "lsug_by_grid_population_overlap.npz", overlap)
    save_npz(args.out_dir / "grid_to_lsug_population_crosswalk.npz", grid_to_lsug)
    save_npz(args.out_dir / "lsug_to_grid_population_crosswalk.npz", lsug_to_grid)
    save_plot(grid_mixing, lsug_results, primary, args.out_dir / "lsug_grid_resolution_diagnostics.png")

    summary = {
        "inputs": {
            "grid": str(args.grid),
            "lsug": str(args.lsug),
            "population_raster": str(args.population_raster),
        },
        "parameters": {
            "significant_overlap_share": args.significant_share,
            "full_coverage_threshold": args.full_coverage_threshold,
            "lower_bound_computed": args.compute_lower_bound,
            "candidate_cell_sizes_m": args.candidate_cell_sizes,
        },
        "raster_assignment_qa": raster_qa,
        "grid_mixing": grid_mix_summary,
        "lsug_coverage": {
            "lsug_count": int(len(lsug)),
            "represented_lsug_count": int(represented.sum()),
            "primary_full_coverage_lsug_count": int(primary.sum()),
            "modeled_population_total": float(lsug_population.sum()),
            "census_population_total": float(census_population.sum()),
        },
        "roundtrip_reconstruction_primary": primary_metrics,
        "roundtrip_reconstruction_all_represented": represented_metrics,
        "citywide_share_baseline_primary": baseline_metrics,
        "nonnegative_grid_fit_lower_bound_primary": lower_bound_metrics,
        "candidate_grid_comparison": candidate_summaries,
        "decision": decision,
        "method_note": (
            "The round trip allocates each LSUG's observed three-region flows to grids by calibrated WorldPop overlap, "
            "then reassigns each homogeneous grid's flows back to LSUGs by the same population overlap. The residual is "
            "the practical information loss caused by the origin zoning mismatch. The NNLS result is a grid-specific "
            "best-fit lower bound, not a deployable low-parameter calibrator."
        ),
        "excluded_target_note": (
            "plw_oth is excluded because it combines no fixed workplace, marine, work at home, and workplaces outside "
            "Hong Kong and therefore has no destination grid in the fixed-workplace OD matrix."
        ),
    }
    summary_path = args.out_dir / "lsug_grid_resolution_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"LSUG rows: {len(lsug)}; represented: {represented.sum()}; primary: {primary.sum()}")
    print(f"Grid rows: {len(grid)}; populated: {populated.sum()}")
    print(
        "Round-trip primary weighted destination-share MAE: "
        f"{primary_metrics['destination_share_mae_pp_worker_weighted']:.3f} percentage points"
    )
    print(f"Round-trip primary cell WAPE: {primary_metrics['cell_wape']:.3%}")
    print(f"Decision: {decision['decision_code']}")
    print(f"Wrote: {summary_path}")


if __name__ == "__main__":
    main()
