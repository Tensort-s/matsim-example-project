#!/usr/bin/env python3
"""Fail-fast preflight for the strict single-GPU Hong Kong WEDAN run."""

from __future__ import annotations

import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def main() -> None:
    visible = [part.strip() for part in os.environ.get("CUDA_VISIBLE_DEVICES", "").split(",") if part.strip()]
    if len(visible) != 1:
        raise RuntimeError("CUDA_VISIBLE_DEVICES must expose exactly one GPU.")
    os.environ.setdefault("DGLDEFAULTDIR", str(ROOT / ".cache/dgl"))
    os.environ.setdefault("DGLBACKEND", "pytorch")

    import dgl
    import torch

    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise RuntimeError("Exactly one CUDA GPU is required; CPU fallback is forbidden.")
    device = torch.device("cuda:0")
    props = torch.cuda.get_device_properties(device)
    total_gib = props.total_memory / 1024**3
    torch.cuda.set_per_process_memory_fraction(min(10.0 / total_gib, 1.0), device=0)
    graph = dgl.graph(([0], [1]), num_nodes=2).to(device)
    tensor = torch.ones((1024, 1024), dtype=torch.float32, device=device)
    result = tensor @ tensor
    torch.cuda.synchronize(device)
    peak_reserved = torch.cuda.max_memory_reserved(device) / 1024**3
    if peak_reserved > 10.05:
        raise RuntimeError(f"Preflight exceeded the 10 GiB cap: {peak_reserved:.3f} GiB")
    payload = {
        "status": "ok",
        "physical_gpu_id": visible[0],
        "gpu_name": props.name,
        "gpu_total_memory_gib": total_gib,
        "torch_version": torch.__version__,
        "torch_cuda_version": torch.version.cuda,
        "dgl_version": dgl.__version__,
        "dgl_graph_device": str(graph.device),
        "tensor_device": str(result.device),
        "memory_limit_gib": 10.0,
        "peak_reserved_gib": peak_reserved,
        "cpu_fallback": False,
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
