#!/usr/bin/env python3
"""Run one Hong Kong WEDAN scaler/seed experiment on one capped GPU."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
CITY_NAME = "hong_kong_fixed_link_grid"
WEDAN_ROOT = ROOT / "data/worldcommuting_od/_shared/GeneratingCodeData"
WEDAN_CODE = WEDAN_ROOT / "code"
DEFAULT_CITY_DIR = (
    ROOT
    / "data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid"
    / "GeneratingCodeData/data/global_cities/hong_kong_fixed_link_grid"
)
DEFAULT_EXPERIMENT_ROOT = (
    ROOT
    / "data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid"
    / "CommutingODFlows/hong_kong_fixed_link_grid/hk_scaler_calibration_v1/scaler_runs"
)
DEFAULT_CONFIG = WEDAN_ROOT / "exp/config/us.json"
DEFAULT_CHECKPOINT = WEDAN_ROOT / "exp/model/US2world/model_666_best.pkl"
SCALER_NAMES = ["local_minmax", "feature_robust", "group_robust"]
FEATURE_GROUPS = {
    "population_count": (0, 1),
    "population_density": (1, 2),
    "demographics": (2, 38),
    "pois": (38, 72),
    "remoteclip": (72, 1096),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city-dir", type=Path, default=DEFAULT_CITY_DIR)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--feature-scaling", choices=SCALER_NAMES, required=True)
    parser.add_argument("--sample-times", type=int, default=10)
    parser.add_argument("--ddim-steps", type=int, default=25)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--gpu-memory-limit-gib", type=float, default=10.0)
    return parser.parse_args()


def setup_wedan_imports() -> None:
    dgl_dir = ROOT / ".cache/dgl"
    dgl_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("DGLDEFAULTDIR", str(dgl_dir))
    os.environ.setdefault("DGLBACKEND", "pytorch")
    sys.path.insert(0, str(WEDAN_CODE))


def require_single_capped_gpu(torch, dgl, limit_gib: float):
    visible = os.environ.get("CUDA_VISIBLE_DEVICES", "").strip()
    visible_ids = [part.strip() for part in visible.split(",") if part.strip()]
    if len(visible_ids) != 1:
        raise RuntimeError("CUDA_VISIBLE_DEVICES must expose exactly one physical GPU; CPU fallback is forbidden.")
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise RuntimeError("Exactly one CUDA GPU must be available; CPU fallback is forbidden.")
    if limit_gib <= 0 or limit_gib > 10.0:
        raise ValueError("GPU memory limit must be in (0, 10] GiB.")

    device = torch.device("cuda:0")
    props = torch.cuda.get_device_properties(device)
    total_gib = props.total_memory / 1024**3
    if total_gib < limit_gib:
        raise RuntimeError(f"GPU total memory {total_gib:.3f} GiB is below the requested {limit_gib:.3f} GiB limit.")
    torch.cuda.set_per_process_memory_fraction(min(limit_gib / total_gib, 1.0), device=0)
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats(device)

    try:
        test_graph = dgl.graph(([0], [1]), num_nodes=2).to(device)
        del test_graph
    except Exception as exc:
        raise RuntimeError("DGL is not CUDA-capable; CPU fallback is forbidden.") from exc

    return device, {
        "physical_gpu_id": visible_ids[0],
        "logical_gpu_id": 0,
        "gpu_name": props.name,
        "gpu_total_memory_gib": total_gib,
        "memory_limit_gib": limit_gib,
        "cuda_visible_devices": visible,
        "torch_version": torch.__version__,
        "torch_cuda_version": torch.version.cuda,
        "dgl_version": dgl.__version__,
    }


def load_city_arrays(city_dir: Path) -> dict[str, np.ndarray]:
    arrays = {
        "pop": np.load(city_dir / "nfeat/worldpop.npy").astype("float32"),
        "demo": np.load(city_dir / "nfeat/demos.npy").astype("float32"),
        "pois": np.load(city_dir / "nfeat/pois.npy").astype("float32"),
        "imgfeat": np.load(city_dir / "nfeat/imgfeat.npy").astype("float32"),
        "dis": np.load(city_dir / "adj/dis.npy").astype("float32"),
    }
    expected = {
        "pop": (1585, 2),
        "demo": (1585, 36),
        "pois": (1585, 34),
        "imgfeat": (1585, 1024),
        "dis": (1585, 1585),
    }
    actual = {key: value.shape for key, value in arrays.items()}
    if actual != expected:
        raise ValueError(f"Unexpected Hong Kong input shapes: {actual}")
    for key, value in arrays.items():
        if not np.all(np.isfinite(value)) or np.any(value < 0) and key != "imgfeat":
            raise ValueError(f"Invalid values in {key}: {value.shape}")
    arrays["nfeat"] = np.concatenate(
        [np.log1p(arrays["pop"]), arrays["demo"], arrays["pois"], arrays["imgfeat"]], axis=1
    ).astype("float32")
    return arrays


def scale_with_bounds(data: np.ndarray, low: np.ndarray, high: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    low = np.asarray(low, dtype="float64")
    high = np.asarray(high, dtype="float64")
    span = high - low
    constant = span <= 0
    safe_span = np.where(constant, 1.0, span)
    below = data < low
    above = data > high
    scaled = np.clip((data - low) / safe_span * 2.0 - 1.0, -1.0, 1.0)
    if np.ndim(constant) == 0:
        if bool(constant):
            scaled[...] = 0.0
    elif np.any(constant):
        scaled[..., constant] = 0.0
    metadata = {
        "low": low.tolist() if low.ndim else float(low),
        "high": high.tolist() if high.ndim else float(high),
        "constant_dimensions": int(np.count_nonzero(constant)),
        "below_fraction": float(np.mean(below)),
        "above_fraction": float(np.mean(above)),
        "scaled_min": float(np.min(scaled)),
        "scaled_max": float(np.max(scaled)),
    }
    return scaled.astype("float32"), metadata


def scale_features(arrays: dict[str, np.ndarray], method: str) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    nfeat = arrays["nfeat"].astype("float64")
    dis = arrays["dis"].astype("float64")
    offdiag = dis[~np.eye(dis.shape[0], dtype=bool)]

    if method == "local_minmax":
        nfeat_scaled, feat_meta = scale_with_bounds(nfeat, np.min(nfeat, axis=0), np.max(nfeat, axis=0))
        dis_scaled, dis_meta = scale_with_bounds(dis, np.array(0.0), np.array(np.max(offdiag)))
        groups = {"per_feature": feat_meta}
    elif method == "feature_robust":
        nfeat_scaled, feat_meta = scale_with_bounds(
            nfeat, np.quantile(nfeat, 0.01, axis=0), np.quantile(nfeat, 0.99, axis=0)
        )
        dis_scaled, dis_meta = scale_with_bounds(dis, np.array(0.0), np.array(np.quantile(offdiag, 0.99)))
        groups = {"per_feature_q01_q99": feat_meta}
    elif method == "group_robust":
        nfeat_scaled = np.zeros_like(nfeat, dtype="float32")
        groups = {}
        for name, (start, stop) in FEATURE_GROUPS.items():
            values = nfeat[:, start:stop]
            scaled, metadata = scale_with_bounds(
                values, np.array(np.quantile(values, 0.01)), np.array(np.quantile(values, 0.99))
            )
            nfeat_scaled[:, start:stop] = scaled
            metadata["columns"] = [start, stop]
            groups[name] = metadata
        dis_scaled, dis_meta = scale_with_bounds(dis, np.array(0.0), np.array(np.quantile(offdiag, 0.99)))
    else:
        raise ValueError(f"Unknown scaling method: {method}")

    np.fill_diagonal(dis_scaled, -1.0)
    metadata = {
        "method": method,
        "feature_groups": groups,
        "distance": dis_meta,
        "nfeat_shape": list(nfeat_scaled.shape),
        "distance_shape": list(dis_scaled.shape),
        "fuzhou_reference_used": False,
    }
    return nfeat_scaled, dis_scaled, metadata


def positive_base_score(raw: np.ndarray) -> tuple[np.ndarray, dict[str, float]]:
    mask = ~np.eye(raw.shape[0], dtype=bool)
    values = raw[mask].astype("float64")
    median = float(np.median(values))
    q25, q75 = np.quantile(values, [0.25, 0.75])
    iqr = float(q75 - q25)
    if not np.isfinite(iqr) or iqr <= 0:
        iqr = max(float(np.std(values)), 1.0)
    z = np.clip((raw.astype("float64") - median) / iqr, -8.0, 8.0)
    score = np.logaddexp(0.0, z).astype("float32")
    np.fill_diagonal(score, 0.0)
    return score, {
        "method": "softplus(clip((raw-offdiag_median)/offdiag_iqr,-8,8))",
        "offdiag_median": median,
        "offdiag_q25": float(q25),
        "offdiag_q75": float(q75),
        "offdiag_iqr": iqr,
        "score_min": float(score.min()),
        "score_max": float(score.max()),
        "score_mean": float(score.mean()),
    }


def load_config(path: Path, n_indim: int, img_dim: int, args: argparse.Namespace, device):
    config = json.loads(path.read_text(encoding="utf-8"))
    config["device"] = device
    config["check_device"] = 0
    config["sample_times"] = args.sample_times
    config["DDIM_T_sample"] = args.ddim_steps
    config["n_indim"] = n_indim
    config["e_indim"] = 1
    config["n_outdim"] = n_indim
    config["e_outdim"] = 1
    config["img_dim"] = img_dim
    return config


def save_plot(score: np.ndarray, out_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 6), dpi=160)
    im = ax.imshow(np.log1p(score), cmap="magma")
    ax.set_title("Hong Kong WEDAN positive base score")
    ax.set_xlabel("Destination grid")
    ax.set_ylabel("Origin grid")
    fig.colorbar(im, ax=ax, shrink=0.82, label="log1p(score)")
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def main() -> None:
    args = parse_args()
    setup_wedan_imports()

    import dgl
    import torch
    from model import Diffusion

    for path in [args.city_dir, args.checkpoint, args.config]:
        if not path.exists():
            raise FileNotFoundError(path)
    if args.sample_times != 10 or args.ddim_steps != 25:
        raise ValueError("Formal scaler experiments require sample_times=10 and ddim_steps=25.")

    device, gpu_info = require_single_capped_gpu(torch, dgl, args.gpu_memory_limit_gib)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)

    arrays = load_city_arrays(args.city_dir)
    nfeat_scaled, dis_scaled, scaling_info = scale_features(arrays, args.feature_scaling)
    config = load_config(args.config, nfeat_scaled.shape[1], arrays["imgfeat"].shape[1], args, device)
    out_dir = args.out_dir or DEFAULT_EXPERIMENT_ROOT / args.feature_scaling / f"seed_{args.seed}"
    out_dir.mkdir(parents=True, exist_ok=True)

    n = torch.as_tensor(nfeat_scaled, dtype=torch.float32, device=device)
    dim = arrays["dis"].shape[0]
    e = torch.zeros((dim, dim), dtype=torch.float32, device=device)
    dis = torch.as_tensor(dis_scaled, dtype=torch.float32, device=device)
    batchlization = torch.ones((dim, dim), dtype=torch.float32, device=device)
    model = Diffusion(config).to(device)
    state_dict = torch.load(args.checkpoint, map_location=device)
    model.load_state_dict(state_dict)
    model.eval()

    outputs = []
    try:
        with torch.no_grad():
            condition = ((n, e), dis, batchlization)
            for idx in range(args.sample_times):
                print(f"Sampling {idx + 1}/{args.sample_times} ...", flush=True)
                sample = model.DDIM_sample_loop(n.shape, e.shape, condition)[-1]
                outputs.append(sample.detach().cpu().numpy())
                del sample
    except torch.cuda.OutOfMemoryError as exc:
        raise RuntimeError("CUDA OOM under the 10 GiB cap; CPU fallback is forbidden.") from exc

    raw = np.mean(np.stack(outputs), axis=0).astype("float32")
    raw = np.where(np.isfinite(raw), raw, 0.0).astype("float32")
    np.fill_diagonal(raw, 0.0)
    score, score_info = positive_base_score(raw)

    peak_allocated = torch.cuda.max_memory_allocated(device) / 1024**3
    peak_reserved = torch.cuda.max_memory_reserved(device) / 1024**3
    gpu_info["peak_memory_allocated_gib"] = peak_allocated
    gpu_info["peak_memory_reserved_gib"] = peak_reserved
    if peak_reserved > args.gpu_memory_limit_gib + 0.05:
        raise RuntimeError(
            f"Peak reserved GPU memory {peak_reserved:.3f} GiB exceeded the {args.gpu_memory_limit_gib:.3f} GiB cap."
        )

    raw_path = out_dir / "raw_normalized.npy"
    score_path = out_dir / "positive_base_score.npy"
    np.save(raw_path, raw)
    np.save(score_path, score)
    (out_dir / "scaler_metadata.json").write_text(
        json.dumps(scaling_info, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    save_plot(score, out_dir / "positive_base_score.png")

    summary = {
        "city": CITY_NAME,
        "feature_scaling": args.feature_scaling,
        "seed": args.seed,
        "sample_times": args.sample_times,
        "ddim_steps": args.ddim_steps,
        "checkpoint": str(args.checkpoint),
        "fuzhou_reference_used": False,
        "quantile_mapping_used": False,
        "raw_output": str(raw_path),
        "positive_base_score_output": str(score_path),
        "raw_stats": {
            "shape": list(raw.shape),
            "dtype": str(raw.dtype),
            "min": float(raw.min()),
            "max": float(raw.max()),
            "mean": float(raw.mean()),
            "diagonal_sum": float(np.diag(raw).sum()),
        },
        "positive_score": score_info,
        "gpu": gpu_info,
    }
    summary_path = out_dir / "run_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote: {raw_path}")
    print(f"Wrote: {score_path}")
    print(f"Peak reserved GPU memory: {peak_reserved:.3f} GiB")


if __name__ == "__main__":
    main()
