#!/usr/bin/env python3
"""Run the formal 3-scaler x 3-seed Hong Kong WEDAN experiment serially."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
INFERENCE_SCRIPT = Path(__file__).with_name("run_hong_kong_wedan_inference.py")
DEFAULT_OUT_ROOT = (
    ROOT
    / "data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid"
    / "CommutingODFlows/hong_kong_fixed_link_grid/hk_scaler_calibration_v1/scaler_runs"
)
SCALERS = ["local_minmax", "feature_robust", "group_robust"]
SEEDS = [666, 667, 668]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--gpu-memory-limit-gib", type=float, default=10.0)
    parser.add_argument("--physical-gpu-id", type=int, default=None)
    return parser.parse_args()


def query_gpus() -> list[dict[str, Any]]:
    command = [
        "nvidia-smi",
        "--query-gpu=index,name,memory.total,memory.free,memory.used",
        "--format=csv,noheader,nounits",
    ]
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("nvidia-smi is unavailable; CPU fallback is forbidden.") from exc
    rows = []
    for row in csv.reader(completed.stdout.splitlines()):
        if len(row) != 5:
            continue
        rows.append(
            {
                "index": int(row[0].strip()),
                "name": row[1].strip(),
                "total_mib": int(row[2].strip()),
                "free_mib": int(row[3].strip()),
                "used_mib": int(row[4].strip()),
            }
        )
    if not rows:
        raise RuntimeError("No NVIDIA GPU was reported; CPU fallback is forbidden.")
    return rows


def select_gpu(requested: int | None, required_free_mib: int) -> dict[str, Any]:
    gpus = query_gpus()
    candidates = [gpu for gpu in gpus if gpu["free_mib"] >= required_free_mib]
    if requested is not None:
        candidates = [gpu for gpu in candidates if gpu["index"] == requested]
    if not candidates:
        raise RuntimeError(
            f"No permitted GPU has at least {required_free_mib} MiB free; CPU fallback is forbidden. GPUs={gpus}"
        )
    return max(candidates, key=lambda gpu: gpu["free_mib"])


def output_complete(path: Path, scaler: str, seed: int) -> bool:
    summary_path = path / "run_summary.json"
    raw_path = path / "raw_normalized.npy"
    score_path = path / "positive_base_score.npy"
    if not all(item.exists() for item in [summary_path, raw_path, score_path]):
        return False
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        summary.get("feature_scaling") == scaler
        and summary.get("seed") == seed
        and summary.get("quantile_mapping_used") is False
        and summary.get("gpu", {}).get("peak_memory_reserved_gib", 99) <= 10.05
    )


def main() -> None:
    args = parse_args()
    if args.gpu_memory_limit_gib <= 0 or args.gpu_memory_limit_gib > 10:
        raise ValueError("--gpu-memory-limit-gib must be in (0, 10].")
    required_free_mib = int(args.gpu_memory_limit_gib * 1024)
    selected = select_gpu(args.physical_gpu_id, required_free_mib)
    args.out_root.mkdir(parents=True, exist_ok=True)

    manifest = {
        "selected_gpu": selected,
        "gpu_memory_limit_gib": args.gpu_memory_limit_gib,
        "scalers": SCALERS,
        "seeds": SEEDS,
        "sample_times": 10,
        "ddim_steps": 25,
        "execution": "strictly_serial",
        "cpu_fallback": False,
        "runs": [],
    }
    manifest_path = args.out_root.parent / "experiment_manifest.json"

    for scaler in SCALERS:
        for seed in SEEDS:
            out_dir = args.out_root / scaler / f"seed_{seed}"
            if output_complete(out_dir, scaler, seed):
                manifest["runs"].append({"scaler": scaler, "seed": seed, "status": "already_complete"})
                manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
                continue

            current = select_gpu(selected["index"], required_free_mib)
            env = os.environ.copy()
            env["CUDA_VISIBLE_DEVICES"] = str(selected["index"])
            command = [
                sys.executable,
                str(INFERENCE_SCRIPT),
                "--feature-scaling",
                scaler,
                "--seed",
                str(seed),
                "--sample-times",
                "10",
                "--ddim-steps",
                "25",
                "--gpu-memory-limit-gib",
                str(args.gpu_memory_limit_gib),
                "--out-dir",
                str(out_dir),
            ]
            print(f"Running scaler={scaler} seed={seed} on physical GPU {selected['index']} ...", flush=True)
            completed = subprocess.run(command, env=env, check=False)
            status = "complete" if completed.returncode == 0 and output_complete(out_dir, scaler, seed) else "failed"
            manifest["runs"].append(
                {
                    "scaler": scaler,
                    "seed": seed,
                    "status": status,
                    "returncode": completed.returncode,
                    "gpu_free_mib_before_run": current["free_mib"],
                }
            )
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            if status != "complete":
                raise RuntimeError(
                    f"Experiment failed for scaler={scaler}, seed={seed}; stopped without CPU fallback."
                )

    manifest["status"] = "complete"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"All experiments complete: {manifest_path}")


if __name__ == "__main__":
    main()
