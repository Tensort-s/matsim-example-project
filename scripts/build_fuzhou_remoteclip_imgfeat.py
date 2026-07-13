"""Build WEDAN/WorldOD-style `imgfeat.npy` from Fuzhou Esri imagery.

The WorldCommuting-OD paper describes satellite image features as 1,024-D
semantic vectors extracted by the RemoteCLIP image encoder from Esri World
Imagery. This script applies the same idea to the Greenspace Fuzhou grid:

  - Input grid: custom Greenspace boundary grid, `regions.shp`
  - Input image: clipped Esri World Imagery GeoTIFF
  - Encoder: RemoteCLIP-RN50 via OpenCLIP, output dim 1024
  - Output: `imgfeat.npy`, shape (N, 1024), aligned to grid row order

The script intentionally does not L2-normalize the output features, matching the
raw feature style seen in the downloaded WorldOD examples.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pathlib
from dataclasses import dataclass
from typing import Iterable

# Force rasterio/GDAL to use its own PROJ database on Windows before importing
# geopandas/rasterio. This avoids conflicts with other GIS apps such as GeoDa.
_RASTERIO_SPEC = importlib.util.find_spec("rasterio")
if _RASTERIO_SPEC and _RASTERIO_SPEC.origin:
    _RASTERIO_DIR = pathlib.Path(_RASTERIO_SPEC.origin).resolve().parent
    os.environ["PROJ_DATA"] = str(_RASTERIO_DIR / "proj_data")
    os.environ["PROJ_LIB"] = str(_RASTERIO_DIR / "proj_data")
    os.environ["GDAL_DATA"] = str(_RASTERIO_DIR / "gdal_data")

import geopandas as gpd
import numpy as np
import rasterio
from PIL import Image
from rasterio.mask import mask
from tqdm import tqdm

import torch
import open_clip
from huggingface_hub import hf_hub_download


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_GRID = (
    PROJECT_ROOT
    / "data"
    / "worldcommuting_od"
    / "custom_features"
    / "fuzhou_city_23_greenspace_grid"
    / "CityAndRegionSplit"
    / "fuzhou_city_23_greenspace_grid"
    / "regions.shp"
)
DEFAULT_IMAGE = (
    PROJECT_ROOT
    / "data"
    / "imagery"
    / "esri_world_imagery"
    / "fuzhou_city_23_greenspace_boundary"
    / "fuzhou_city_23_esri_world_imagery_z14_greenspace_clip_epsg32650.tif"
)
DEFAULT_NFEAT_DIR = (
    PROJECT_ROOT
    / "data"
    / "worldcommuting_od"
    / "custom_features"
    / "fuzhou_city_23_greenspace_grid"
    / "GeneratingCodeData"
    / "data"
    / "global_cities"
    / "fuzhou_city_23_greenspace_grid"
    / "nfeat"
)
DEFAULT_CACHE_DIR = PROJECT_ROOT / "data" / "models" / "remoteclip"
DEFAULT_PATCH_DIR = (
    PROJECT_ROOT
    / "data"
    / "worldcommuting_od"
    / "custom_features"
    / "fuzhou_city_23_greenspace_grid"
    / "image_patches_remoteclip"
)


@dataclass
class RegionPatch:
    index: int
    location: str
    image: Image.Image
    patch_path: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract RemoteCLIP-RN50 imgfeat.npy for the Greenspace Fuzhou grid.")
    parser.add_argument("--grid", default=str(DEFAULT_GRID), help="Grid regions shapefile.")
    parser.add_argument("--image", default=str(DEFAULT_IMAGE), help="Clipped Esri imagery GeoTIFF.")
    parser.add_argument("--out-dir", default=str(DEFAULT_NFEAT_DIR), help="Output nfeat directory.")
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR), help="Model cache directory.")
    parser.add_argument("--hf-repo", default="chendelong/RemoteCLIP", help="Hugging Face repo containing RemoteCLIP weights.")
    parser.add_argument("--hf-file", default="RemoteCLIP-RN50.pt", help="RemoteCLIP checkpoint file.")
    parser.add_argument("--model-name", default="RN50", help="OpenCLIP model architecture. RN50 outputs 1024-D features.")
    parser.add_argument("--batch-size", type=int, default=16, help="CPU batch size.")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"], help="Torch device.")
    parser.add_argument("--save-patches", action="store_true", help="Save per-grid RGB patches for audit/debug.")
    parser.add_argument("--patch-dir", default=str(DEFAULT_PATCH_DIR), help="Patch output directory if --save-patches is used.")
    parser.add_argument("--max-regions", type=int, default=None, help="Optional debug limit.")
    return parser.parse_args()


def download_remoteclip_checkpoint(cache_dir: pathlib.Path, repo: str, filename: str) -> pathlib.Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    local = cache_dir / filename
    if local.exists() and local.stat().st_size > 0:
        return local
    path = hf_hub_download(repo_id=repo, filename=filename, cache_dir=str(cache_dir), local_dir=str(cache_dir))
    downloaded = pathlib.Path(path)
    if downloaded != local and downloaded.exists():
        # Make the path predictable for later runs.
        local.write_bytes(downloaded.read_bytes())
    return local


def load_remoteclip_model(model_name: str, checkpoint_path: pathlib.Path, device: str):
    model, _, preprocess = open_clip.create_model_and_transforms(model_name, pretrained=None)
    checkpoint = torch.load(checkpoint_path, map_location="cpu")
    state_dict = checkpoint.get("state_dict", checkpoint) if isinstance(checkpoint, dict) else checkpoint
    # RemoteCLIP checkpoints are OpenCLIP-compatible; strip common prefixes if present.
    cleaned = {}
    for key, value in state_dict.items():
        if key.startswith("module."):
            key = key[len("module.") :]
        if key.startswith("model."):
            key = key[len("model.") :]
        cleaned[key] = value
    missing, unexpected = model.load_state_dict(cleaned, strict=False)
    if len(unexpected) > 0:
        print(f"Warning: unexpected checkpoint keys: {len(unexpected)}")
    if len(missing) > 0:
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
    # Pad to square before CLIP preprocessing so elongated clipped polygons are
    # resized rather than center-cropped away.
    h, w = rgb.shape[:2]
    side = max(h, w, 1)
    square = np.zeros((side, side, 3), dtype=np.uint8)
    y0 = (side - h) // 2
    x0 = (side - w) // 2
    square[y0 : y0 + h, x0 : x0 + w] = rgb
    return Image.fromarray(square, mode="RGB")


def iter_region_patches(grid: gpd.GeoDataFrame, image_path: pathlib.Path, save_patches: bool, patch_dir: pathlib.Path | None) -> Iterable[RegionPatch]:
    with rasterio.open(image_path) as src:
        grid_img = grid.to_crs(src.crs)
        for idx, row in grid_img.iterrows():
            location = str(row.get("locations", idx))
            image = rgb_patch_from_geometry(src, row.geometry)
            patch_path = None
            if save_patches and patch_dir is not None:
                patch_dir.mkdir(parents=True, exist_ok=True)
                patch_file = patch_dir / f"{idx:04d}_{location.replace('-', '_')}.jpg"
                image.save(patch_file, quality=92)
                patch_path = str(patch_file)
            yield RegionPatch(index=int(idx), location=location, image=image, patch_path=patch_path)


def batched(items: list[RegionPatch], batch_size: int) -> Iterable[list[RegionPatch]]:
    for start in range(0, len(items), batch_size):
        yield items[start : start + batch_size]


def main() -> None:
    args = parse_args()
    grid_path = pathlib.Path(args.grid)
    image_path = pathlib.Path(args.image)
    out_dir = pathlib.Path(args.out_dir)
    cache_dir = pathlib.Path(args.cache_dir)
    patch_dir = pathlib.Path(args.patch_dir) if args.save_patches else None

    for path in [grid_path, image_path]:
        if not path.exists():
            raise FileNotFoundError(path)

    if args.device == "cuda" and not torch.cuda.is_available():
        print("CUDA requested but unavailable; falling back to CPU.")
        device = "cpu"
    else:
        device = args.device

    grid = gpd.read_file(grid_path).reset_index(drop=True)
    if args.max_regions is not None:
        grid = grid.iloc[: args.max_regions].copy()

    print(f"Grid regions: {len(grid)}")
    print(f"Image: {image_path}")
    print(f"Device: {device}")
    checkpoint = download_remoteclip_checkpoint(cache_dir, args.hf_repo, args.hf_file)
    print(f"Checkpoint: {checkpoint}")
    model, preprocess = load_remoteclip_model(args.model_name, checkpoint, device)

    patches = list(iter_region_patches(grid, image_path, args.save_patches, patch_dir))
    features: list[np.ndarray] = []
    rows: list[dict] = []

    with torch.no_grad():
        for batch in tqdm(list(batched(patches, args.batch_size)), desc="RemoteCLIP encoding"):
            tensors = torch.stack([preprocess(item.image) for item in batch]).to(device)
            encoded = model.encode_image(tensors)
            encoded = encoded.detach().cpu().float().numpy()
            features.append(encoded)
            for item in batch:
                rows.append({"grid_index": item.index, "locations": item.location, "patch_path": item.patch_path})

    imgfeat = np.vstack(features).astype("float32")
    if imgfeat.shape[1] != 1024:
        raise RuntimeError(f"Expected 1024-D RN50 features, got {imgfeat.shape}")

    out_dir.mkdir(parents=True, exist_ok=True)
    imgfeat_path = out_dir / "imgfeat.npy"
    np.save(imgfeat_path, imgfeat)

    import pandas as pd

    manifest_path = out_dir / "imgfeat_manifest.csv"
    pd.DataFrame(rows).to_csv(manifest_path, index=False, encoding="utf-8-sig")

    summary = {
        "grid": str(grid_path),
        "image": str(image_path),
        "output": str(imgfeat_path),
        "shape": list(imgfeat.shape),
        "dtype": str(imgfeat.dtype),
        "model": "RemoteCLIP-RN50 via OpenCLIP",
        "model_name": args.model_name,
        "hf_repo": args.hf_repo,
        "hf_file": args.hf_file,
        "checkpoint": str(checkpoint),
        "device": device,
        "batch_size": args.batch_size,
        "save_patches": args.save_patches,
        "patch_dir": str(patch_dir) if patch_dir else None,
        "feature_stats": {
            "min": float(np.min(imgfeat)),
            "max": float(np.max(imgfeat)),
            "mean": float(np.mean(imgfeat)),
            "std": float(np.std(imgfeat)),
            "row_norm_min": float(np.linalg.norm(imgfeat, axis=1).min()),
            "row_norm_max": float(np.linalg.norm(imgfeat, axis=1).max()),
            "row_norm_mean": float(np.linalg.norm(imgfeat, axis=1).mean()),
        },
        "note": "Features are raw RemoteCLIP image embeddings, not L2-normalized. Row order follows regions.shp row order.",
    }
    summary_path = out_dir / "imgfeat_generation_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote: {imgfeat_path} shape={imgfeat.shape}")
    print(f"Wrote: {manifest_path}")
    print(f"Wrote: {summary_path}")
    print(f"Feature mean/std: {summary['feature_stats']['mean']:.6f}/{summary['feature_stats']['std']:.6f}")


if __name__ == "__main__":
    main()
