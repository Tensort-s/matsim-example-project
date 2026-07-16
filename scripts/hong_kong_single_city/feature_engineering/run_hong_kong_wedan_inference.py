#!/usr/bin/env python3
"""Run WEDAN inference for the Hong Kong fixed-link grid."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

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
DEFAULT_OUT_DIR = (
    ROOT
    / "data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid"
    / "CommutingODFlows/hong_kong_fixed_link_grid"
)
DEFAULT_CONFIG = WEDAN_ROOT / "exp/config/us.json"
DEFAULT_CHECKPOINT = WEDAN_ROOT / "exp/model/US2world/model_666_best.pkl"
DEFAULT_REFERENCE_OD = ROOT / "data/worldcommuting_od/fuzhou/330_CN_Fuzhou/CommutingODFlows/330_CN_Fuzhou/generation.npy"
DEFAULT_REFERENCE_CITY = ROOT / "data/worldcommuting_od/fuzhou/330_CN_Fuzhou/GeneratingCodeData/data/global_cities/330_CN_Fuzhou"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city-dir", type=Path, default=DEFAULT_CITY_DIR, help="City feature directory containing nfeat/ and adj/.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR, help="Output OD directory.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="WEDAN config JSON.")
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT, help="WEDAN checkpoint.")
    parser.add_argument("--reference-od", type=Path, default=DEFAULT_REFERENCE_OD, help="Reference OD for quantile calibration.")
    parser.add_argument("--reference-city-dir", type=Path, default=DEFAULT_REFERENCE_CITY, help="Reference city feature dir for approximate scaling.")
    parser.add_argument("--sample-times", type=int, default=10, help="Number of DDIM samples to average. Original config uses 100.")
    parser.add_argument("--ddim-steps", type=int, default=25, help="DDIM sampling steps.")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"], help="Torch device.")
    parser.add_argument(
        "--feature-scaling",
        choices=["reference_minmax", "local_minmax", "none"],
        default="reference_minmax",
        help="Approximate feature/dis scaling because original training scalers are unavailable.",
    )
    parser.add_argument("--seed", type=int, default=666, help="Random seed.")
    return parser.parse_args()


def setup_wedan_imports() -> None:
    dgl_dir = ROOT / ".cache/dgl"
    dgl_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("DGLDEFAULTDIR", str(dgl_dir))
    os.environ.setdefault("DGLBACKEND", "pytorch")
    sys.path.insert(0, str(WEDAN_CODE))


def load_config(path: Path, n_indim: int, img_dim: int, args: argparse.Namespace):
    import torch

    config = json.loads(path.read_text(encoding="utf-8"))
    requested = args.device
    device = "cuda" if requested == "cuda" and torch.cuda.is_available() else "cpu"
    config["device"] = torch.device(device)
    config["check_device"] = 0
    config["sample_times"] = args.sample_times
    config["DDIM_T_sample"] = args.ddim_steps
    config["n_indim"] = n_indim
    config["e_indim"] = 1
    config["n_outdim"] = n_indim
    config["e_outdim"] = 1
    config["img_dim"] = img_dim
    return config


def load_city_arrays(city_dir: Path) -> dict[str, np.ndarray]:
    arrays = {
        "pop": np.load(city_dir / "nfeat/worldpop.npy").astype("float32"),
        "demo": np.load(city_dir / "nfeat/demos.npy").astype("float32"),
        "pois": np.load(city_dir / "nfeat/pois.npy").astype("float32"),
        "imgfeat": np.load(city_dir / "nfeat/imgfeat.npy").astype("float32"),
        "dis": np.load(city_dir / "adj/dis.npy").astype("float32"),
    }
    rows = {value.shape[0] for value in arrays.values() if value.ndim >= 2}
    if len(rows) != 1:
        raise ValueError(f"Row counts do not align: { {key: value.shape for key, value in arrays.items()} }")
    for key, value in arrays.items():
        if not np.all(np.isfinite(value)):
            raise ValueError(f"Non-finite values in {key}: {value.shape}")
    arrays["nfeat"] = np.concatenate([np.log1p(arrays["pop"]), arrays["demo"], arrays["pois"], arrays["imgfeat"]], axis=1)
    return arrays


def fit_minmax(data: np.ndarray):
    mn = np.nanmin(data, axis=0)
    mx = np.nanmax(data, axis=0)
    span = np.where(mx > mn, mx - mn, 1.0)

    def transform(x: np.ndarray) -> np.ndarray:
        return ((x - mn) / span * 2.0 - 1.0).astype("float32")

    return transform


def scale_features(arrays: dict[str, np.ndarray], args: argparse.Namespace) -> tuple[np.ndarray, np.ndarray, dict]:
    if args.feature_scaling == "none":
        return arrays["nfeat"], arrays["dis"], {"method": "none"}

    if args.feature_scaling == "local_minmax":
        feat_transform = fit_minmax(arrays["nfeat"])
        dis_transform = fit_minmax(arrays["dis"].reshape(-1, 1))
        return (
            feat_transform(arrays["nfeat"]),
            dis_transform(arrays["dis"].reshape(-1, 1)).reshape(arrays["dis"].shape),
            {"method": "local_minmax", "note": "Scaler fitted on the target Hong Kong grid itself."},
        )

    ref = load_city_arrays(args.reference_city_dir)
    feat_transform = fit_minmax(ref["nfeat"])
    dis_transform = fit_minmax(ref["dis"].reshape(-1, 1))
    return (
        feat_transform(arrays["nfeat"]),
        dis_transform(arrays["dis"].reshape(-1, 1)).reshape(arrays["dis"].shape),
        {"method": "reference_minmax", "reference_city_dir": str(args.reference_city_dir)},
    )


def quantile_map_to_reference(raw: np.ndarray, reference_od: np.ndarray) -> np.ndarray:
    out = np.zeros_like(raw, dtype="float64")
    mask = ~np.eye(raw.shape[0], dtype=bool)
    raw_values = raw[mask].astype("float64")
    ref_values = reference_od[~np.eye(reference_od.shape[0], dtype=bool)].astype("float64")
    ref_values = np.where(np.isfinite(ref_values), ref_values, 0.0)
    ref_sorted = np.sort(ref_values)
    order = np.argsort(raw_values, kind="mergesort")
    ranks = np.empty_like(order)
    ranks[order] = np.arange(len(order))
    q_idx = np.floor(ranks / max(len(ranks) - 1, 1) * (len(ref_sorted) - 1)).astype(int)
    mapped = ref_sorted[q_idx]
    out[mask] = mapped
    np.fill_diagonal(out, 0.0)
    out[out < 0] = 0.0
    return np.floor(out).astype("float32")


def save_plot(od: np.ndarray, out_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 6), dpi=180)
    shown = np.log1p(od)
    im = ax.imshow(shown, cmap="magma")
    ax.set_title("Hong Kong Fixed-link Grid OD prediction (log1p)")
    ax.set_xlabel("Destination grid")
    ax.set_ylabel("Origin grid")
    fig.colorbar(im, ax=ax, shrink=0.82, label="log1p(flow)")
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)


def main() -> None:
    args = parse_args()
    setup_wedan_imports()

    import torch
    from model import Diffusion

    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    for path in [args.city_dir, args.checkpoint, args.reference_od, args.config, args.reference_city_dir]:
        if not path.exists():
            raise FileNotFoundError(path)

    arrays = load_city_arrays(args.city_dir)
    nfeat_scaled, dis_scaled, scaling_info = scale_features(arrays, args)
    config = load_config(args.config, nfeat_scaled.shape[1], arrays["imgfeat"].shape[1], args)
    device = config["device"]

    n = torch.FloatTensor(nfeat_scaled).to(device)
    dim = arrays["dis"].shape[0]
    e = torch.zeros((dim, dim), dtype=torch.float32, device=device)
    dis = torch.FloatTensor(dis_scaled).to(device)
    batchlization = torch.ones((dim, dim), dtype=torch.float32, device=device)

    model = Diffusion(config).to(device)
    state_dict = torch.load(args.checkpoint, map_location=device)
    model.load_state_dict(state_dict)
    model.eval()

    print(f"City nodes: {dim}")
    print(f"nfeat dim: {nfeat_scaled.shape[1]}")
    print(f"Device: {device}")
    print(f"Sample times: {args.sample_times}; DDIM steps: {args.ddim_steps}")
    print(f"Feature scaling: {scaling_info}")

    e_hats = []
    with torch.no_grad():
        c = ((n, e), dis, batchlization)
        for i in range(args.sample_times):
            print(f"Sampling {i + 1}/{args.sample_times} ...")
            e_hat = model.DDIM_sample_loop(n.shape, e.shape, c)[-1]
            e_hats.append(e_hat.cpu().numpy())
    raw = np.mean(np.stack(e_hats), axis=0).astype("float32")
    raw = np.where(np.isfinite(raw), raw, 0.0)
    np.fill_diagonal(raw, 0.0)

    reference_od = np.load(args.reference_od)
    calibrated = quantile_map_to_reference(raw, reference_od)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = args.out_dir / "generation_raw_normalized.npy"
    generation_path = args.out_dir / "generation.npy"
    csv_path = args.out_dir / "generation.csv"
    png_path = args.out_dir / "generation.png"
    np.save(raw_path, raw)
    np.save(generation_path, calibrated)
    np.savetxt(csv_path, calibrated, delimiter=",", fmt="%.0f")
    save_plot(calibrated, png_path)

    summary = {
        "city": CITY_NAME,
        "city_dir": str(args.city_dir),
        "output_dir": str(args.out_dir),
        "config": str(args.config),
        "checkpoint": str(args.checkpoint),
        "reference_od": str(args.reference_od),
        "raw_output": str(raw_path),
        "generation_output": str(generation_path),
        "csv_output": str(csv_path),
        "png_output": str(png_path),
        "nodes": int(dim),
        "input_shapes": {key: list(value.shape) for key, value in arrays.items() if key != "nfeat"},
        "nfeat_shape": list(nfeat_scaled.shape),
        "sample_times": args.sample_times,
        "ddim_steps": args.ddim_steps,
        "device": str(device),
        "feature_scaling": scaling_info,
        "calibration": {
            "method": "off-diagonal quantile mapping to reference WorldOD Fuzhou generation.npy",
            "note": "Original US training scalers are unavailable locally; calibrated generation.npy is reference-scaled.",
        },
        "raw_stats": {
            "min": float(raw.min()),
            "max": float(raw.max()),
            "mean": float(raw.mean()),
            "std": float(raw.std()),
            "diag_sum": float(np.diag(raw).sum()),
        },
        "generation_stats": {
            "sum": float(calibrated.sum()),
            "nonzero": int(np.count_nonzero(calibrated)),
            "min": float(calibrated.min()),
            "max": float(calibrated.max()),
            "mean": float(calibrated.mean()),
            "diag_sum": float(np.diag(calibrated).sum()),
        },
    }
    summary_path = args.out_dir / "generation_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote: {generation_path} shape={calibrated.shape}")
    print(f"Wrote: {raw_path}")
    print(f"Wrote: {csv_path}")
    print(f"Wrote: {png_path}")
    print(f"Wrote: {summary_path}")
    print(f"Generation sum: {summary['generation_stats']['sum']:.0f}; nonzero: {summary['generation_stats']['nonzero']}")


if __name__ == "__main__":
    main()
