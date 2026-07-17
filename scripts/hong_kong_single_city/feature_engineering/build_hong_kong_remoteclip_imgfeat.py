#!/usr/bin/env python3
"""Build WEDAN RemoteCLIP image features for the Hong Kong fixed-link grid."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

_RASTERIO_SPEC = importlib.util.find_spec("rasterio")
if _RASTERIO_SPEC and _RASTERIO_SPEC.origin:
    _RASTERIO_DIR = Path(_RASTERIO_SPEC.origin).resolve().parent
    os.environ["PROJ_DATA"] = str(_RASTERIO_DIR / "proj_data")
    os.environ["PROJ_LIB"] = str(_RASTERIO_DIR / "proj_data")
    os.environ["GDAL_DATA"] = str(_RASTERIO_DIR / "gdal_data")

import geopandas as gpd
import numpy as np
import open_clip
import pandas as pd
import rasterio
import torch
from huggingface_hub import hf_hub_download
from PIL import Image
from rasterio.mask import mask
from tqdm import tqdm


ROOT = Path(__file__).resolve().parents[3]
CITY_NAME = "hong_kong_fixed_link_grid"
DEFAULT_GRID = (
    ROOT
    / "data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid"
    / "CityAndRegionSplit/hong_kong_fixed_link_grid/regions.shp"
)
DEFAULT_IMAGE = (
    ROOT
    / "data/imagery/hongkong/esri_world_imagery/fixed_link_boundary"
    / "hong_kong_fixed_link_esri_world_imagery_z14_clip_epsg32650.tif"
)
DEFAULT_NFEAT_DIR = (
    ROOT
    / "data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid"
    / "GeneratingCodeData/data/global_cities/hong_kong_fixed_link_grid/nfeat"
)
DEFAULT_CACHE_DIR = ROOT / "data/models/_shared/remoteclip"
DEFAULT_PATCH_DIR = (
    ROOT
    / "data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid"
    / "image_patches_remoteclip"
)


@dataclass
class RegionPatch:
    index: int
    grid_id: int
    location: str
    image: Image.Image
    patch_path: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grid", type=Path, default=DEFAULT_GRID, help="Hong Kong fixed-link grid regions.shp.")
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE, help="EPSG:32650 clipped Esri imagery GeoTIFF.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_NFEAT_DIR, help="Output WEDAN nfeat directory.")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR, help="RemoteCLIP checkpoint cache directory.")
    parser.add_argument("--hf-repo", default="chendelong/RemoteCLIP", help="Hugging Face repo containing RemoteCLIP weights.")
    parser.add_argument("--hf-file", default="RemoteCLIP-RN50.pt", help="RemoteCLIP checkpoint file.")
    parser.add_argument("--model-name", default="RN50", help="OpenCLIP architecture. RN50 outputs 1024-D features.")
    parser.add_argument("--batch-size", type=int, default=16, help="Encoding batch size.")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"], help="Torch device.")
    parser.add_argument("--save-patches", action="store_true", help="Save per-grid RGB patches for audit/debug.")
    parser.add_argument("--patch-dir", type=Path, default=DEFAULT_PATCH_DIR, help="Patch output directory if --save-patches is used.")
    parser.add_argument("--max-regions", type=int, default=None, help="Optional debug limit.")
    return parser.parse_args()


def download_remoteclip_checkpoint(cache_dir: Path, repo: str, filename: str) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    local = cache_dir / filename
    if local.exists() and local.stat().st_size > 0:
        return local
    downloaded = Path(hf_hub_download(repo_id=repo, filename=filename, cache_dir=str(cache_dir), local_dir=str(cache_dir)))
    if downloaded != local and downloaded.exists():
        local.write_bytes(downloaded.read_bytes())
    return local


def load_remoteclip_model(model_name: str, checkpoint_path: Path, device: str):
    model, _, preprocess = open_clip.create_model_and_transforms(model_name, pretrained=None)
    checkpoint = torch.load(checkpoint_path, map_location="cpu")
    state_dict = checkpoint.get("state_dict", checkpoint) if isinstance(checkpoint, dict) else checkpoint
    cleaned = {}
    for key, value in state_dict.items():
        if key.startswith("module."):
            key = key[len("module.") :]
        if key.startswith("model."):
            key = key[len("model.") :]
        cleaned[key] = value
    missing, unexpected = model.load_state_dict(cleaned, strict=False)
    if unexpected:
        print(f"Warning: unexpected checkpoint keys: {len(unexpected)}")
    if missing:
        print(f"Warning: missing checkpoint keys: {len(missing)}")
    model.to(device)
    model.eval()
    return model, preprocess


def rgb_patch_from_geometry(src: rasterio.DatasetReader, geom, background: int = 0) -> Image.Image:
    try:
        data, _ = mask(src, [geom], crop=True, filled=True, nodata=background, indexes=[1, 2, 3])
    except ValueError:
        data = np.zeros((3, 224, 224), dtype=np.uint8)
    data = np.nan_to_num(data, nan=background)
    data = np.clip(data, 0, 255).astype(np.uint8)
    rgb = np.moveaxis(data, 0, -1)
    if rgb.size == 0 or rgb.shape[0] < 1 or rgb.shape[1] < 1:
        rgb = np.zeros((224, 224, 3), dtype=np.uint8)
    h, w = rgb.shape[:2]
    side = max(h, w, 1)
    square = np.zeros((side, side, 3), dtype=np.uint8)
    y0 = (side - h) // 2
    x0 = (side - w) // 2
    square[y0 : y0 + h, x0 : x0 + w] = rgb
    return Image.fromarray(square, mode="RGB")


def iter_region_patches(grid: gpd.GeoDataFrame, image_path: Path, save_patches: bool, patch_dir: Path | None) -> Iterable[RegionPatch]:
    with rasterio.open(image_path) as src:
        grid_img = grid.to_crs(src.crs)
        for idx, row in grid_img.iterrows():
            grid_id = int(row.get("grid_id", idx))
            location = str(row.get("locations", idx))
            image = rgb_patch_from_geometry(src, row.geometry)
            patch_path = None
            if save_patches and patch_dir is not None:
                patch_dir.mkdir(parents=True, exist_ok=True)
                patch_file = patch_dir / f"{idx:04d}_{location.replace('-', '_')}.jpg"
                image.save(patch_file, quality=92)
                patch_path = str(patch_file)
            yield RegionPatch(index=int(idx), grid_id=grid_id, location=location, image=image, patch_path=patch_path)


def batched(items: list[RegionPatch], batch_size: int) -> Iterable[list[RegionPatch]]:
    for start in range(0, len(items), batch_size):
        yield items[start : start + batch_size]


def main() -> None:
    args = parse_args()
    for path in [args.grid, args.image]:
        if not path.exists():
            raise FileNotFoundError(path)
    if args.device == "cuda" and not torch.cuda.is_available():
        print("CUDA requested but unavailable; falling back to CPU.")
        device = "cpu"
    else:
        device = args.device

    grid = gpd.read_file(args.grid).reset_index(drop=True)
    if args.max_regions is not None:
        grid = grid.iloc[: args.max_regions].copy()
    if grid.empty:
        raise ValueError(f"Grid is empty: {args.grid}")

    print(f"Grid regions: {len(grid)}")
    print(f"Image: {args.image}")
    print(f"Device: {device}")
    checkpoint = download_remoteclip_checkpoint(args.cache_dir, args.hf_repo, args.hf_file)
    print(f"Checkpoint: {checkpoint}")
    model, preprocess = load_remoteclip_model(args.model_name, checkpoint, device)

    patches = list(iter_region_patches(grid, args.image, args.save_patches, args.patch_dir if args.save_patches else None))
    features: list[np.ndarray] = []
    rows: list[dict] = []
    with torch.no_grad():
        for batch in tqdm(list(batched(patches, args.batch_size)), desc="RemoteCLIP encoding"):
            tensors = torch.stack([preprocess(item.image) for item in batch]).to(device)
            encoded = model.encode_image(tensors).detach().cpu().float().numpy()
            features.append(encoded)
            for item in batch:
                rows.append(
                    {
                        "grid_index": item.index,
                        "grid_id": item.grid_id,
                        "locations": item.location,
                        "patch_path": item.patch_path,
                    }
                )

    imgfeat = np.vstack(features).astype("float32")
    if imgfeat.shape[1] != 1024:
        raise RuntimeError(f"Expected 1024-D RN50 features, got {imgfeat.shape}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    imgfeat_path = args.out_dir / "imgfeat.npy"
    np.save(imgfeat_path, imgfeat)
    manifest_path = args.out_dir / "imgfeat_manifest.csv"
    pd.DataFrame(rows).to_csv(manifest_path, index=False, encoding="utf-8-sig")

    row_norms = np.linalg.norm(imgfeat, axis=1)
    summary = {
        "city": CITY_NAME,
        "grid": str(args.grid),
        "image": str(args.image),
        "output": str(imgfeat_path),
        "manifest": str(manifest_path),
        "shape": list(imgfeat.shape),
        "dtype": str(imgfeat.dtype),
        "model": "RemoteCLIP-RN50 via OpenCLIP",
        "model_name": args.model_name,
        "checkpoint": str(checkpoint),
        "device": device,
        "batch_size": args.batch_size,
        "save_patches": args.save_patches,
        "patch_dir": str(args.patch_dir) if args.save_patches else None,
        "feature_stats": {
            "min": float(np.min(imgfeat)),
            "max": float(np.max(imgfeat)),
            "mean": float(np.mean(imgfeat)),
            "std": float(np.std(imgfeat)),
            "row_norm_min": float(row_norms.min()),
            "row_norm_max": float(row_norms.max()),
            "row_norm_mean": float(row_norms.mean()),
        },
        "note": "Features are raw RemoteCLIP image embeddings, not L2-normalized. Row order follows regions.shp row order.",
    }
    summary_path = args.out_dir / "imgfeat_generation_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote: {imgfeat_path} shape={imgfeat.shape}")
    print(f"Wrote: {manifest_path}")
    print(f"Wrote: {summary_path}")
    print(f"Feature row-norm min/mean/max: {row_norms.min():.6f}/{row_norms.mean():.6f}/{row_norms.max():.6f}")


if __name__ == "__main__":
    main()
