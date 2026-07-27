from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import matplotlib
import numpy as np
import pandas as pd
from matplotlib import patheffects
from matplotlib.colors import Normalize
from scipy.sparse import load_npz

matplotlib.use("Agg")
import matplotlib.pyplot as plt


PROJECT_ROOT = Path(__file__).resolve().parents[3]
BASE = PROJECT_ROOT / "data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid"
DEFAULT_INPUT_DIR = BASE / "census_2021_commute_constraints/lsug_calibration_inputs"
DEFAULT_CROSSWALK = (
    BASE
    / "census_2021_commute_constraints/lsug_grid_resolution_diagnostics"
    / "lsug_by_grid_population_overlap.npz"
)
DEFAULT_FINAL_DIR = (
    BASE
    / "CommutingODFlows/hong_kong_fixed_link_grid/hk_scaler_calibration_v1/final"
)
DEFAULT_BOUNDARY = (
    PROJECT_ROOT
    / "data/boundary/hongkong/2021_Population_Census_Statistics_and_Boundar_SHP/DC_21C_converted.shp"
)
TARGET_COLUMNS = ["true_plw_hk", "true_plw_kln", "true_plw_nt"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Map and chart 18-district LSUGx3 errors for generalized and Census-projected Hong Kong OD."
    )
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--crosswalk", type=Path, default=DEFAULT_CROSSWALK)
    parser.add_argument("--final-dir", type=Path, default=DEFAULT_FINAL_DIR)
    parser.add_argument("--district-boundary", type=Path, default=DEFAULT_BOUNDARY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_FINAL_DIR / "district_lsug3_metrics")
    return parser.parse_args()


def aggregate_destination_regions(od: np.ndarray, destination_index: np.ndarray) -> np.ndarray:
    result = np.zeros((od.shape[0], 3), dtype="float64")
    for region in range(3):
        result[:, region] = od[:, destination_index == region].sum(axis=1, dtype="float64")
    return result


def predict_lsug_flows(
    od_path: Path, destination_index: np.ndarray, grid_to_lsug
) -> np.ndarray:
    od = np.load(od_path, mmap_mode="r")
    if od.shape != (1585, 1585) or not np.isfinite(od).all() or np.any(od < 0):
        raise ValueError(f"Invalid OD matrix: {od_path}")
    grid_region = aggregate_destination_regions(od, destination_index)
    return np.asarray(grid_to_lsug @ grid_region)


def district_metrics(
    targets: pd.DataFrame,
    truth: np.ndarray,
    predictions: dict[str, np.ndarray],
) -> pd.DataFrame:
    primary = targets["primary_full_coverage_qa"].astype(bool).to_numpy()
    rows: list[dict[str, float | int | str]] = []
    for district in sorted(targets.loc[primary, "dc_eng"].unique()):
        mask = primary & targets["dc_eng"].eq(district).to_numpy()
        district_truth = truth[mask]
        true_totals = district_truth.sum(axis=1)
        true_shares = np.divide(
            district_truth,
            true_totals[:, None],
            out=np.zeros_like(district_truth),
            where=true_totals[:, None] > 0,
        )
        row: dict[str, float | int | str] = {
            "dc_eng": district,
            "primary_lsug_count": int(mask.sum()),
            "target_workers": float(district_truth.sum()),
        }
        for method, prediction in predictions.items():
            district_prediction = prediction[mask]
            predicted_totals = district_prediction.sum(axis=1)
            predicted_shares = np.divide(
                district_prediction,
                predicted_totals[:, None],
                out=np.zeros_like(district_prediction),
                where=predicted_totals[:, None] > 0,
            )
            valid = (true_totals > 0) & (predicted_totals > 0)
            share_error = np.abs(predicted_shares[valid] - true_shares[valid]).mean(axis=1)
            row[f"{method}_share_mae_pp"] = float(
                np.average(share_error, weights=true_totals[valid]) * 100.0
            )
            row[f"{method}_cell_wape_pct"] = float(
                np.abs(district_prediction - district_truth).sum() / district_truth.sum() * 100.0
            )
        rows.append(row)
    result = pd.DataFrame(rows)
    if len(result) != 18 or result["primary_lsug_count"].min() <= 0:
        raise ValueError("Expected metrics for 18 districts with at least one primary LSUG each.")
    return result


def add_map_labels(ax, frame: gpd.GeoDataFrame, value_column: str) -> None:
    points = frame.geometry.representative_point()
    for point, code, value in zip(points, frame["dc_class"], frame[value_column], strict=True):
        label = ax.text(
            point.x,
            point.y,
            f"{code}\n{value:.1f}",
            ha="center",
            va="center",
            fontsize=6.5,
            color="#161616",
            linespacing=0.9,
        )
        label.set_path_effects([patheffects.withStroke(linewidth=2.0, foreground="white")])


def plot_metric_maps(
    districts: gpd.GeoDataFrame,
    columns: tuple[str, str],
    metric_title: str,
    unit: str,
    out_path: Path,
) -> None:
    maximum = float(districts[list(columns)].to_numpy().max())
    norm = Normalize(vmin=0.0, vmax=maximum)
    cmap = plt.get_cmap("cividis")
    fig, axes = plt.subplots(1, 2, figsize=(15, 7.5), dpi=180)
    for ax, column, title in zip(
        axes, columns, ["Generalized full-data calibration", "Census projected"], strict=True
    ):
        districts.plot(
            column=column,
            cmap=cmap,
            norm=norm,
            linewidth=0.65,
            edgecolor="white",
            ax=ax,
        )
        districts.boundary.plot(ax=ax, color="#333333", linewidth=0.35)
        add_map_labels(ax, districts, column)
        ax.set_title(title, fontsize=12, pad=8)
        ax.set_axis_off()
    colorbar = fig.colorbar(
        plt.cm.ScalarMappable(norm=norm, cmap=cmap),
        ax=axes,
        orientation="horizontal",
        fraction=0.04,
        pad=0.055,
        aspect=42,
    )
    colorbar.ax.tick_params(labelsize=8)
    key_items = [f"{row.dc_class} {row.dc_eng}" for row in districts.itertuples()]
    key = "\n".join("   ".join(key_items[start : start + 6]) for start in range(0, len(key_items), 6))
    fig.suptitle(f"Hong Kong district LSUGx3 {metric_title} ({unit})", fontsize=15, y=0.98)
    fig.text(
        0.5,
        0.015,
        "Labels show district code and value. Same 1,657 primary LSUGs are used for both methods.\n" + key,
        ha="center",
        va="bottom",
        fontsize=7,
        wrap=True,
    )
    fig.subplots_adjust(left=0.02, right=0.98, top=0.92, bottom=0.20, wspace=0.03)
    fig.savefig(out_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def add_bar_labels(ax, bars, values: np.ndarray) -> None:
    offset = max(float(values.max()) * 0.012, 0.08)
    for bar, value in zip(bars, values, strict=True):
        ax.text(
            bar.get_width() + offset,
            bar.get_y() + bar.get_height() / 2,
            f"{value:.1f}",
            va="center",
            ha="left",
            fontsize=6.5,
        )


def plot_bars(metrics: pd.DataFrame, out_path: Path) -> None:
    ordered = metrics.sort_values("generalized_share_mae_pp", ascending=True).reset_index(drop=True)
    y = np.arange(len(ordered))
    height = 0.36
    generalized_color = "#247BA0"
    projected_color = "#D95F45"
    fig, axes = plt.subplots(1, 2, figsize=(15, 10), dpi=180, sharey=True)
    specifications = [
        ("share_mae_pp", "LSUGx3 share MAE", "percentage points"),
        ("cell_wape_pct", "LSUGx3 Cell WAPE", "%"),
    ]
    for ax, (suffix, title, unit) in zip(axes, specifications, strict=True):
        generalized = ordered[f"generalized_{suffix}"].to_numpy()
        projected = ordered[f"census_projected_{suffix}"].to_numpy()
        bars_generalized = ax.barh(
            y - height / 2,
            generalized,
            height,
            color=generalized_color,
            label="Generalized",
        )
        bars_projected = ax.barh(
            y + height / 2,
            projected,
            height,
            color=projected_color,
            label="Census projected",
        )
        add_bar_labels(ax, bars_generalized, generalized)
        add_bar_labels(ax, bars_projected, projected)
        ax.set_title(title, fontsize=12)
        ax.set_xlabel(unit)
        ax.set_yticks(y, ordered["dc_eng"])
        ax.grid(axis="x", color="#d8d8d8", linewidth=0.6)
        ax.set_axisbelow(True)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.set_xlim(0, max(generalized.max(), projected.max()) * 1.18)
    axes[0].legend(loc="lower right", frameon=False)
    fig.suptitle(
        "Hong Kong 18-district LSUGx3 OD error comparison",
        fontsize=15,
        y=0.98,
    )
    fig.text(
        0.5,
        0.015,
        "District share MAE is weighted by LSUG fixed-workplace population; both methods use the same 1,657 primary LSUGs.",
        ha="center",
        fontsize=8,
    )
    fig.subplots_adjust(left=0.17, right=0.98, top=0.92, bottom=0.07, wspace=0.12)
    fig.savefig(out_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> None:
    args = parse_args()
    required = [
        args.input_dir / "lsug_calibration_targets.csv",
        args.input_dir / "grid_calibration_features.csv",
        args.crosswalk,
        args.final_dir / "generation_hk_generalized.npy",
        args.final_dir / "generation_hk_census_projected.npy",
        args.district_boundary,
    ]
    for path in required:
        if not path.exists():
            raise FileNotFoundError(path)

    targets = pd.read_csv(args.input_dir / "lsug_calibration_targets.csv", dtype={"lsbg": str})
    grid = pd.read_csv(args.input_dir / "grid_calibration_features.csv").sort_values("grid_id")
    overlap = load_npz(args.crosswalk).tocsr().astype("float64")
    grid_population = np.asarray(overlap.sum(axis=0)).ravel()
    inverse_population = np.divide(
        1.0,
        grid_population,
        out=np.zeros_like(grid_population),
        where=grid_population > 0,
    )
    grid_to_lsug = overlap.multiply(inverse_population).tocsr()
    destination_index = grid["destination_area_index"].to_numpy(dtype="int64")
    truth = targets[TARGET_COLUMNS].to_numpy(dtype="float64")
    predictions = {
        "generalized": predict_lsug_flows(
            args.final_dir / "generation_hk_generalized.npy", destination_index, grid_to_lsug
        ),
        "census_projected": predict_lsug_flows(
            args.final_dir / "generation_hk_census_projected.npy", destination_index, grid_to_lsug
        ),
    }
    metrics = district_metrics(targets, truth, predictions)

    districts = gpd.read_file(args.district_boundary)[["dc_class", "dc_eng", "geometry"]]
    if len(districts) != 18 or districts["dc_eng"].nunique() != 18:
        raise ValueError("District boundary must contain 18 unique District Council areas.")
    districts = districts.merge(metrics, on="dc_eng", validate="one_to_one").sort_values("dc_class")
    if districts.isna().any().any():
        raise ValueError("District boundary and metric join produced missing values.")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(args.out_dir / "hong_kong_district_lsug3_metrics.csv", index=False, encoding="utf-8-sig")
    plot_metric_maps(
        districts,
        ("generalized_share_mae_pp", "census_projected_share_mae_pp"),
        "share MAE",
        "percentage points",
        args.out_dir / "hong_kong_district_lsug3_share_mae_maps.png",
    )
    plot_metric_maps(
        districts,
        ("generalized_cell_wape_pct", "census_projected_cell_wape_pct"),
        "Cell WAPE",
        "%",
        args.out_dir / "hong_kong_district_lsug3_cell_wape_maps.png",
    )
    plot_bars(metrics, args.out_dir / "hong_kong_district_lsug3_metrics_bars.png")
    print(metrics.to_string(index=False))
    print(f"Wrote outputs to: {args.out_dir}")


if __name__ == "__main__":
    main()
