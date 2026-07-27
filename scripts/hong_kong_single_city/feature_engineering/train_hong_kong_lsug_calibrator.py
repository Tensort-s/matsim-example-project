#!/usr/bin/env python3
"""Select a Hong Kong scaler and train the 18-parameter LSUG calibrator."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix, load_npz


ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid"
DEFAULT_EXPERIMENT_ROOT = (
    BASE / "CommutingODFlows/hong_kong_fixed_link_grid/hk_scaler_calibration_v1"
)
DEFAULT_INPUT_DIR = BASE / "census_2021_commute_constraints/lsug_calibration_inputs"
DEFAULT_CROSSWALK = (
    BASE
    / "census_2021_commute_constraints/lsug_grid_resolution_diagnostics"
    / "lsug_by_grid_population_overlap.npz"
)
DEFAULT_LEGACY_OD = BASE / "CommutingODFlows/hong_kong_fixed_link_grid/generation.npy"
SCALERS = ["local_minmax", "feature_robust", "group_robust"]
SEEDS = [666, 667, 668]
TARGET_COLUMNS = ["true_plw_hk", "true_plw_kln", "true_plw_nt"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-root", type=Path, default=DEFAULT_EXPERIMENT_ROOT)
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--crosswalk", type=Path, default=DEFAULT_CROSSWALK)
    parser.add_argument("--legacy-od", type=Path, default=DEFAULT_LEGACY_OD)
    parser.add_argument("--gpu-memory-limit-gib", type=float, default=10.0)
    parser.add_argument("--buffer-grid-share", type=float, default=0.10)
    return parser.parse_args()


def require_gpu(torch, limit_gib: float) -> tuple[Any, dict[str, Any]]:
    visible = [part.strip() for part in os.environ.get("CUDA_VISIBLE_DEVICES", "").split(",") if part.strip()]
    if len(visible) != 1 or not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise RuntimeError("Calibration requires exactly one CUDA GPU; CPU fallback is forbidden.")
    if limit_gib <= 0 or limit_gib > 10:
        raise ValueError("GPU memory limit must be in (0, 10] GiB.")
    device = torch.device("cuda:0")
    props = torch.cuda.get_device_properties(device)
    total_gib = props.total_memory / 1024**3
    torch.cuda.set_per_process_memory_fraction(min(limit_gib / total_gib, 1.0), device=0)
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats(device)
    return device, {
        "physical_gpu_id": visible[0],
        "gpu_name": props.name,
        "gpu_total_memory_gib": total_gib,
        "memory_limit_gib": limit_gib,
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
    }


def normalized_grid_to_lsug(overlap: csr_matrix) -> csr_matrix:
    grid_population = np.asarray(overlap.sum(axis=0)).ravel()
    inverse = np.divide(1.0, grid_population, out=np.zeros_like(grid_population), where=grid_population > 0)
    return overlap.multiply(inverse).tocsr()


def torch_sparse(matrix: csr_matrix, torch, device):
    coo = matrix.tocoo()
    indices = torch.as_tensor(np.vstack([coo.row, coo.col]), dtype=torch.long, device=device)
    values = torch.as_tensor(coo.data, dtype=torch.float32, device=device)
    return torch.sparse_coo_tensor(indices, values, coo.shape, device=device).coalesce()


def aggregate_destination_regions(score: np.ndarray, destination_index: np.ndarray) -> np.ndarray:
    result = np.zeros((score.shape[0], 3), dtype="float64")
    for region in range(3):
        result[:, region] = score[:, destination_index == region].sum(axis=1, dtype="float64")
    return result


def metrics(target: np.ndarray, predicted: np.ndarray, mask: np.ndarray) -> dict[str, float]:
    target = target[mask].astype("float64")
    predicted = predicted[mask].astype("float64")
    error = predicted - target
    absolute = np.abs(error)
    target_total = float(target.sum())
    target_rows = target.sum(axis=1)
    predicted_rows = predicted.sum(axis=1)
    true_share = np.divide(target, target_rows[:, None], out=np.zeros_like(target), where=target_rows[:, None] > 0)
    pred_share = np.divide(
        predicted, predicted_rows[:, None], out=np.zeros_like(predicted), where=predicted_rows[:, None] > 0
    )
    share_abs = np.abs(pred_share - true_share)
    valid = (target_rows > 0) & (predicted_rows > 0)
    weights = target_rows[valid]
    weighted_share_mae = float(np.average(share_abs[valid].mean(axis=1), weights=weights))
    weighted_tvd = float(np.average(0.5 * share_abs[valid].sum(axis=1), weights=weights))
    return {
        "lsug_count": int(mask.sum()),
        "target_workers": target_total,
        "predicted_workers": float(predicted.sum()),
        "cell_mae_workers": float(absolute.mean()),
        "cell_rmse_workers": float(np.sqrt(np.square(error).mean())),
        "cell_wape": float(absolute.sum() / target_total),
        "origin_total_wape": float(np.abs(predicted_rows - target_rows).sum() / target_rows.sum()),
        "weighted_share_mae_pp": weighted_share_mae * 100.0,
        "weighted_tvd_pp": weighted_tvd * 100.0,
    }


def area_od_share_metrics(
    target: np.ndarray,
    predicted: np.ndarray,
    mask: np.ndarray,
    lsug_origin_area_weights: np.ndarray,
) -> dict[str, float]:
    weights = lsug_origin_area_weights[mask].astype("float64")
    target_blocks = weights.T @ target[mask].astype("float64")
    predicted_blocks = weights.T @ predicted[mask].astype("float64")
    target_share = target_blocks / target_blocks.sum()
    predicted_share = predicted_blocks / predicted_blocks.sum()
    error = predicted_share - target_share
    return {
        "area_od_share_mae_pp": float(np.abs(error).mean() * 100.0),
        "area_od_share_rmse_pp": float(np.sqrt(np.square(error).mean()) * 100.0),
        "area_od_tvd_pp": float(0.5 * np.abs(error).sum() * 100.0),
    }


def compute_buffer_masks(
    overlap: csr_matrix,
    grid_to_lsug: csr_matrix,
    primary: np.ndarray,
    districts: np.ndarray,
    heldout_district: str,
    threshold: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    validation = primary & (districts == heldout_district)
    heldout_grid_share = np.asarray(grid_to_lsug[validation].max(axis=0).toarray()).ravel()
    buffered_grids = heldout_grid_share >= threshold
    if buffered_grids.any():
        buffered_lsug = np.asarray(overlap[:, buffered_grids].sum(axis=1)).ravel() > 0
    else:
        buffered_lsug = np.zeros(len(primary), dtype=bool)
    training = primary & ~validation & ~buffered_lsug
    return training, validation, buffered_lsug


def model_loss(pred, target, mask, beta, gamma, torch):
    selected_pred = pred[mask]
    selected_target = target[mask]
    log_loss = torch.nn.functional.smooth_l1_loss(
        torch.log1p(selected_pred), torch.log1p(selected_target), reduction="mean"
    )
    pred_share = selected_pred / selected_pred.sum(dim=1, keepdim=True).clamp_min(1e-8)
    target_share = selected_target / selected_target.sum(dim=1, keepdim=True).clamp_min(1e-8)
    share_kl = (target_share * (torch.log(target_share.clamp_min(1e-8)) - torch.log(pred_share.clamp_min(1e-8)))).sum(
        dim=1
    ).mean()
    regularization = beta.square().mean() + gamma.square().mean()
    return log_loss + 0.5 * share_kl + 1e-3 * regularization


def train_calibrator(
    base_region: np.ndarray,
    target: np.ndarray,
    train_mask: np.ndarray,
    grid_to_lsug_t,
    origin_area: np.ndarray,
    covariates: np.ndarray,
    torch,
    device,
) -> tuple[np.ndarray, np.ndarray, tuple[np.ndarray, np.ndarray], dict[str, Any]]:
    base_t = torch.as_tensor(base_region, dtype=torch.float32, device=device)
    target_t = torch.as_tensor(target, dtype=torch.float32, device=device)
    area_t = torch.as_tensor(origin_area, dtype=torch.long, device=device)
    covariates_t = torch.as_tensor(covariates, dtype=torch.float32, device=device)
    mask_t = torch.as_tensor(train_mask, dtype=torch.bool, device=device)
    beta = torch.nn.Parameter(torch.zeros((4, 3), dtype=torch.float32, device=device))
    gamma = torch.nn.Parameter(torch.zeros((2, 3), dtype=torch.float32, device=device))

    def predict():
        raw_effect = beta[area_t] + covariates_t @ gamma
        log_multiplier = 5.0 * torch.tanh(raw_effect / 5.0)
        grid_region = base_t * torch.exp(log_multiplier)
        return torch.sparse.mm(grid_to_lsug_t, grid_region), grid_region

    optimizer = torch.optim.Adam([beta, gamma], lr=0.03)
    best_loss = float("inf")
    stale = 0
    adam_steps = 0
    try:
        for step in range(1200):
            optimizer.zero_grad(set_to_none=True)
            pred, _ = predict()
            loss = model_loss(pred, target_t, mask_t, beta, gamma, torch)
            loss.backward()
            optimizer.step()
            adam_steps = step + 1
            value = float(loss.detach().cpu())
            if best_loss - value > 1e-7:
                best_loss = value
                stale = 0
            else:
                stale += 1
            if stale >= 120:
                break

        lbfgs = torch.optim.LBFGS(
            [beta, gamma], lr=0.5, max_iter=100, tolerance_grad=1e-7, tolerance_change=1e-9, line_search_fn="strong_wolfe"
        )

        def closure():
            lbfgs.zero_grad(set_to_none=True)
            pred, _ = predict()
            loss = model_loss(pred, target_t, mask_t, beta, gamma, torch)
            loss.backward()
            return loss

        final_loss = float(lbfgs.step(closure).detach().cpu())
        with torch.no_grad():
            prediction, grid_region = predict()
    except torch.cuda.OutOfMemoryError as exc:
        raise RuntimeError("Calibrator CUDA OOM under the 10 GiB cap; CPU fallback is forbidden.") from exc

    return (
        prediction.detach().cpu().numpy().astype("float64"),
        grid_region.detach().cpu().numpy().astype("float64"),
        (beta.detach().cpu().numpy(), gamma.detach().cpu().numpy()),
        {
            "adam_steps": adam_steps,
            "best_adam_loss": best_loss,
            "lbfgs_returned_loss": final_loss,
            "beta": beta.detach().cpu().numpy().tolist(),
            "gamma": gamma.detach().cpu().numpy().tolist(),
        },
    )


def global_baseline(base_prediction: np.ndarray, target: np.ndarray, train_mask: np.ndarray) -> tuple[np.ndarray, float]:
    denominator = float(base_prediction[train_mask].sum())
    scale = float(target[train_mask].sum() / denominator) if denominator > 0 else 0.0
    return base_prediction * scale, scale


def legacy_metrics(
    legacy_od: np.ndarray,
    destination_index: np.ndarray,
    grid_to_lsug: csr_matrix,
    target: np.ndarray,
    primary: np.ndarray,
    lsug_origin_area_weights: np.ndarray,
) -> dict[str, float]:
    legacy_region = aggregate_destination_regions(legacy_od.astype("float64"), destination_index)
    prediction = grid_to_lsug @ legacy_region
    prediction, scale = global_baseline(prediction, target, primary)
    result = metrics(target, prediction, primary)
    result.update(area_od_share_metrics(target, prediction, primary, lsug_origin_area_weights))
    result["global_scale"] = scale
    return result


def census_projection(
    generalized: np.ndarray,
    overlap: csr_matrix,
    target: np.ndarray,
    represented: np.ndarray,
    destination_index: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    grid_region = aggregate_destination_regions(generalized, destination_index)
    projected_region = np.zeros_like(grid_region)
    for lsug_idx in np.flatnonzero(represented):
        row = overlap.getrow(lsug_idx)
        grid_indices = row.indices
        population = row.data.astype("float64")
        if not len(grid_indices):
            continue
        for region in range(3):
            weights = population * grid_region[grid_indices, region]
            if weights.sum() <= 0:
                weights = population.copy()
            weights /= weights.sum()
            projected_region[grid_indices, region] += target[lsug_idx, region] * weights

    projected = np.zeros_like(generalized, dtype="float64")
    for region in range(3):
        destination_mask = destination_index == region
        denominator = grid_region[:, region]
        shares = np.divide(
            generalized[:, destination_mask],
            denominator[:, None],
            out=np.zeros((len(generalized), int(destination_mask.sum())), dtype="float64"),
            where=denominator[:, None] > 0,
        )
        projected[:, destination_mask] = shares * projected_region[:, region, None]
    np.fill_diagonal(projected, 0.0)
    return projected, projected_region


def save_diagnostic_plot(comparison: pd.DataFrame, oof: pd.DataFrame, out_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), dpi=170)
    grouped = comparison.groupby("scaler", sort=False)["calibrated_share_mae_pp"].agg(["mean", "std"])
    axes[0].bar(grouped.index, grouped["mean"], yerr=grouped["std"], color=["#277DA1", "#43AA8B", "#F8961E"])
    axes[0].set_ylabel("Held-out weighted share MAE (pp)")
    axes[0].set_title("Scaler comparison across seeds and districts")
    axes[0].tick_params(axis="x", rotation=18)

    for idx, field in enumerate(TARGET_COLUMNS):
        short = field.removeprefix("true_")
        axes[1].scatter(
            oof[f"true_{short}"], oof[f"pred_{short}"], s=7, alpha=0.35, label=short.replace("plw_", "")
        )
    limit = max(oof[[field for field in TARGET_COLUMNS]].to_numpy().max(), 1.0)
    axes[1].plot([0, limit], [0, limit], color="black", linewidth=1)
    axes[1].set_xlim(0, limit)
    axes[1].set_ylim(0, limit)
    axes[1].set_xlabel("Census workers")
    axes[1].set_ylabel("Spatially held-out prediction")
    axes[1].set_title("Selected scaler out-of-fold predictions")
    axes[1].legend(frameon=False)
    fig.tight_layout()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    args = parse_args()
    import torch

    device, gpu_info = require_gpu(torch, args.gpu_memory_limit_gib)
    target_path = args.input_dir / "lsug_calibration_targets.csv"
    grid_path = args.input_dir / "grid_calibration_features.csv"
    for path in [target_path, grid_path, args.crosswalk, args.legacy_od]:
        if not path.exists():
            raise FileNotFoundError(path)

    targets_df = pd.read_csv(target_path, dtype={"lsbg": str})
    grid_df = pd.read_csv(grid_path).sort_values("grid_id").reset_index(drop=True)
    overlap = load_npz(args.crosswalk).tocsr().astype("float64")
    if overlap.shape != (len(targets_df), len(grid_df)) or overlap.shape != (1746, 1585):
        raise ValueError(f"Unexpected crosswalk shape: {overlap.shape}")
    grid_to_lsug = normalized_grid_to_lsug(overlap)
    grid_to_lsug_t = torch_sparse(grid_to_lsug, torch, device)

    target = targets_df[TARGET_COLUMNS].to_numpy(dtype="float64")
    primary = targets_df["primary_full_coverage_qa"].astype(bool).to_numpy()
    represented = targets_df["represented_in_grid"].astype(bool).to_numpy()
    districts = targets_df["dc_eng"].astype(str).to_numpy()
    district_order = sorted(np.unique(districts[primary]).tolist())
    if len(district_order) != 18:
        raise ValueError(f"Expected 18 held-out districts, got {district_order}")
    origin_area = grid_df["origin_area_index"].to_numpy(dtype="int64")
    destination_index = grid_df["destination_area_index"].to_numpy(dtype="int64")
    grid_origin_one_hot = np.eye(4, dtype="float64")[origin_area]
    lsug_origin_area_weights = np.asarray(overlap @ grid_origin_one_hot)
    lsug_origin_totals = lsug_origin_area_weights.sum(axis=1, keepdims=True)
    lsug_origin_area_weights = np.divide(
        lsug_origin_area_weights,
        lsug_origin_totals,
        out=np.zeros_like(lsug_origin_area_weights),
        where=lsug_origin_totals > 0,
    )
    covariates = grid_df[["log1p_population_count", "working_age_share"]].to_numpy(dtype="float64")
    covariate_mean = covariates.mean(axis=0)
    covariate_std = covariates.std(axis=0)
    covariate_std = np.where(covariate_std > 0, covariate_std, 1.0)
    covariates = (covariates - covariate_mean) / covariate_std

    fold_rows: list[dict[str, Any]] = []
    oof_by_run: dict[tuple[str, int], np.ndarray] = {}
    base_scores: dict[tuple[str, int], np.ndarray] = {}
    for scaler in SCALERS:
        for seed in SEEDS:
            score_path = args.experiment_root / "scaler_runs" / scaler / f"seed_{seed}" / "positive_base_score.npy"
            summary_path = score_path.with_name("run_summary.json")
            if not score_path.exists() or not summary_path.exists():
                raise FileNotFoundError(f"Incomplete scaler run: {score_path}")
            run_summary = json.loads(summary_path.read_text(encoding="utf-8"))
            if run_summary.get("quantile_mapping_used") is not False:
                raise ValueError(f"Forbidden quantile mapping in {summary_path}")
            score = np.load(score_path).astype("float64")
            if score.shape != (1585, 1585) or not np.all(np.isfinite(score)) or np.any(score < 0):
                raise ValueError(f"Invalid positive score: {score_path}")
            base_scores[(scaler, seed)] = score
            base_region = aggregate_destination_regions(score, destination_index)
            base_prediction = grid_to_lsug @ base_region
            oof_prediction = np.full_like(target, np.nan, dtype="float64")

            for district in district_order:
                train_mask, validation_mask, buffered = compute_buffer_masks(
                    overlap, grid_to_lsug, primary, districts, district, args.buffer_grid_share
                )
                if train_mask.sum() < 500 or validation_mask.sum() == 0:
                    raise ValueError(f"Invalid fold {district}: train={train_mask.sum()} val={validation_mask.sum()}")
                calibrated_pred, _, _, fit = train_calibrator(
                    base_region,
                    target,
                    train_mask,
                    grid_to_lsug_t,
                    origin_area,
                    covariates,
                    torch,
                    device,
                )
                baseline_pred, baseline_scale = global_baseline(base_prediction, target, train_mask)
                calibrated_metrics = metrics(target, calibrated_pred, validation_mask)
                baseline_metrics = metrics(target, baseline_pred, validation_mask)
                oof_prediction[validation_mask] = calibrated_pred[validation_mask]
                fold_rows.append(
                    {
                        "scaler": scaler,
                        "seed": seed,
                        "heldout_district": district,
                        "train_lsug_count": int(train_mask.sum()),
                        "validation_lsug_count": int(validation_mask.sum()),
                        "buffered_lsug_count": int((buffered & primary & ~validation_mask).sum()),
                        "baseline_global_scale": baseline_scale,
                        "baseline_share_mae_pp": baseline_metrics["weighted_share_mae_pp"],
                        "calibrated_share_mae_pp": calibrated_metrics["weighted_share_mae_pp"],
                        "baseline_cell_wape": baseline_metrics["cell_wape"],
                        "calibrated_cell_wape": calibrated_metrics["cell_wape"],
                        "calibrated_cell_mae": calibrated_metrics["cell_mae_workers"],
                        "calibrated_cell_rmse": calibrated_metrics["cell_rmse_workers"],
                        "calibrated_origin_total_wape": calibrated_metrics["origin_total_wape"],
                        "calibrated_tvd_pp": calibrated_metrics["weighted_tvd_pp"],
                        "share_mae_improved": calibrated_metrics["weighted_share_mae_pp"]
                        < baseline_metrics["weighted_share_mae_pp"],
                        "adam_steps": fit["adam_steps"],
                    }
                )
            if np.isnan(oof_prediction[primary]).any():
                raise RuntimeError(f"OOF prediction is incomplete for {scaler}/{seed}")
            oof_by_run[(scaler, seed)] = oof_prediction

    fold_df = pd.DataFrame(fold_rows)
    scaler_rows = []
    for scaler in SCALERS:
        subset = fold_df[fold_df["scaler"].eq(scaler)]
        district_improvement = (
            subset.groupby("heldout_district")[["baseline_share_mae_pp", "calibrated_share_mae_pp"]].mean()
        )
        improved_districts = int(
            (district_improvement["calibrated_share_mae_pp"] < district_improvement["baseline_share_mae_pp"]).sum()
        )
        baseline_mean = float(subset["baseline_share_mae_pp"].mean())
        calibrated_mean = float(subset["calibrated_share_mae_pp"].mean())
        scaler_oof = np.mean(np.stack([oof_by_run[(scaler, seed)] for seed in SEEDS]), axis=0)
        scaler_area_metrics = area_od_share_metrics(target, scaler_oof, primary, lsug_origin_area_weights)
        scaler_rows.append(
            {
                "scaler": scaler,
                "baseline_share_mae_pp": baseline_mean,
                "calibrated_share_mae_pp": calibrated_mean,
                "relative_share_mae_improvement": (baseline_mean - calibrated_mean) / baseline_mean,
                "improved_districts_of_18": improved_districts,
                "calibrated_share_mae_seed_std": float(
                    subset.groupby("seed")["calibrated_share_mae_pp"].mean().std(ddof=0)
                ),
                "calibrated_cell_wape": float(subset["calibrated_cell_wape"].mean()),
                "calibrated_origin_total_wape": float(subset["calibrated_origin_total_wape"].mean()),
                **scaler_area_metrics,
            }
        )
    comparison = pd.DataFrame(scaler_rows).sort_values(
        ["calibrated_share_mae_pp", "calibrated_cell_wape", "calibrated_share_mae_seed_std"]
    ).reset_index(drop=True)
    selected_scaler = str(comparison.iloc[0]["scaler"])

    ensemble_score = np.exp(
        np.mean(
            np.stack([np.log(base_scores[(selected_scaler, seed)] + 1e-8) for seed in SEEDS]), axis=0
        )
    )
    np.fill_diagonal(ensemble_score, 0.0)
    ensemble_region = aggregate_destination_regions(ensemble_score, destination_index)
    final_prediction, final_grid_region, _, final_fit = train_calibrator(
        ensemble_region, target, primary, grid_to_lsug_t, origin_area, covariates, torch, device
    )
    beta = np.asarray(final_fit["beta"], dtype="float64")
    gamma = np.asarray(final_fit["gamma"], dtype="float64")
    raw_effect = beta[origin_area] + covariates @ gamma
    multiplier = np.exp(5.0 * np.tanh(raw_effect / 5.0))
    generalized = ensemble_score * multiplier[:, destination_index]
    np.fill_diagonal(generalized, 0.0)
    projected, projected_region = census_projection(generalized, overlap, target, represented, destination_index)
    projected_reaggregated = grid_to_lsug @ projected_region

    selected_oof = np.mean(np.stack([oof_by_run[(selected_scaler, seed)] for seed in SEEDS]), axis=0)
    selected_oof_result = metrics(target, selected_oof, primary)
    selected_oof_result.update(area_od_share_metrics(target, selected_oof, primary, lsug_origin_area_weights))
    oof_rows = targets_df.loc[primary, ["lsug_index", "lsbg", "dc_eng"]].copy()
    for idx, field in enumerate(TARGET_COLUMNS):
        short = field.removeprefix("true_")
        oof_rows[f"true_{short}"] = target[primary, idx]
        oof_rows[f"pred_{short}"] = selected_oof[primary, idx]

    legacy = np.load(args.legacy_od)
    legacy_result = legacy_metrics(
        legacy, destination_index, grid_to_lsug, target, primary, lsug_origin_area_weights
    )
    generalized_result = metrics(target, final_prediction, primary)
    generalized_result.update(
        area_od_share_metrics(target, final_prediction, primary, lsug_origin_area_weights)
    )
    projected_result = metrics(target, projected_reaggregated, represented)
    selected_row = comparison.iloc[0]
    accepted = bool(
        selected_row["relative_share_mae_improvement"] >= 0.10
        and selected_row["improved_districts_of_18"] >= 12
        and selected_row["calibrated_share_mae_pp"] < legacy_result["weighted_share_mae_pp"]
        and selected_oof_result["area_od_share_mae_pp"] < legacy_result["area_od_share_mae_pp"]
    )

    final_dir = args.experiment_root / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    np.save(final_dir / "generation_hk_generalized.npy", generalized.astype("float32"))
    np.save(final_dir / "generation_hk_census_projected.npy", projected.astype("float32"))
    fold_df.to_csv(final_dir / "district_cv_metrics.csv", index=False, encoding="utf-8-sig")
    comparison.to_csv(final_dir / "scaler_comparison.csv", index=False, encoding="utf-8-sig")
    oof_rows.to_csv(final_dir / "lsug_validation_predictions.csv", index=False, encoding="utf-8-sig")
    save_diagnostic_plot(fold_df, oof_rows, final_dir / "calibration_diagnostics.png")

    peak_allocated = torch.cuda.max_memory_allocated(device) / 1024**3
    peak_reserved = torch.cuda.max_memory_reserved(device) / 1024**3
    gpu_info["peak_memory_allocated_gib"] = peak_allocated
    gpu_info["peak_memory_reserved_gib"] = peak_reserved
    if peak_reserved > args.gpu_memory_limit_gib + 0.05:
        raise RuntimeError("Calibration exceeded the 10 GiB GPU cap.")

    parameter_payload = {
        "selected_scaler": selected_scaler,
        "seeds": SEEDS,
        "origin_area_order": ["hong_kong_island", "kowloon", "new_towns", "other_nt_marine"],
        "destination_area_order": ["hong_kong_island", "kowloon", "new_territories"],
        "covariates": ["log1p_population_count", "working_age_share"],
        "covariate_mean": covariate_mean.tolist(),
        "covariate_std": covariate_std.tolist(),
        "beta": final_fit["beta"],
        "gamma": final_fit["gamma"],
    }
    (final_dir / "calibrator_parameters.json").write_text(
        json.dumps(parameter_payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    summary = {
        "selected_scaler": selected_scaler,
        "accepted_as_replacement": accepted,
        "acceptance_rules": {
            "minimum_relative_share_mae_improvement": 0.10,
            "minimum_improved_districts": 12,
            "must_beat_legacy_fuzhou_quantile_share_mae": True,
            "must_beat_legacy_fuzhou_quantile_4area_od_share_mae": True,
        },
        "selected_cv": selected_row.to_dict(),
        "selected_oof_primary": selected_oof_result,
        "legacy_fuzhou_quantile_primary": legacy_result,
        "generalized_primary": generalized_result,
        "census_projected_represented_roundtrip": projected_result,
        "census_projected_latent_target_workers": float(target[represented].sum()),
        "census_projected_grid_workers": float(projected.sum()),
        "gpu": gpu_info,
        "cpu_fallback": False,
        "fuzhou_quantile_used_in_new_outputs": False,
    }
    (final_dir / "calibration_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Selected scaler: {selected_scaler}")
    print(f"Accepted as replacement: {accepted}")
    print(f"Wrote final outputs: {final_dir}")


if __name__ == "__main__":
    main()
