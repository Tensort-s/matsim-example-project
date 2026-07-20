#!/usr/bin/env python3
"""Aggregate integrated Hong Kong POIs to WEDAN 34-category grid features."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from collections import Counter
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


ROOT = Path(__file__).resolve().parents[3]
CITY_NAME = "hong_kong_fixed_link_grid"
MODEL_CRS = "EPSG:32650"
DEFAULT_GRID = (
    ROOT
    / "data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid"
    / "CityAndRegionSplit/hong_kong_fixed_link_grid/regions.shp"
)
DEFAULT_POIS = (
    ROOT
    / "data/osm/hongkong/fixed_link_boundary/integrated_pois"
    / "hong_kong_fixed_link_integrated_pois.geojson"
)
DEFAULT_NFEAT_DIR = (
    ROOT
    / "data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid"
    / "GeneratingCodeData/data/global_cities/hong_kong_fixed_link_grid/nfeat"
)

POI_CATEGORIES = [
    "finance",
    "toilets",
    "transport",
    "cinema and theatre",
    "health",
    "service",
    "education",
    "government",
    "religion",
    "accommodation",
    "bar",
    "cafe",
    "fast food",
    "ice cream",
    "food court",
    "restaurant",
    "beauty shop",
    "clothes shop",
    "boutique",
    "bicycle shop",
    "retail",
    "supermarket",
    "houseware shop",
    "sport",
    "transit station",
    "kindergarten",
    "office",
    "recycling",
    "travel agency",
    "tourism",
    "livelihood shop",
    "residential",
    "dormitory",
    "garden",
]
CATEGORY_TO_INDEX = {category: idx for idx, category in enumerate(POI_CATEGORIES)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grid", type=Path, default=DEFAULT_GRID, help="Hong Kong fixed-link grid regions.shp.")
    parser.add_argument("--pois", type=Path, default=DEFAULT_POIS, help="Integrated iGeoCom+OSM POI GeoJSON.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_NFEAT_DIR, help="Output WEDAN nfeat directory.")
    parser.add_argument("--boundary-nearest-m", type=float, default=1.0, help="Nearest assignment tolerance for boundary points.")
    return parser.parse_args()


def normalize_category(value: object) -> str | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    category = str(value).strip().lower()
    if not category or category in {"none", "nan", "null", "unmapped"}:
        return None
    return category


def assign_pois_to_grid(pois: gpd.GeoDataFrame, grid: gpd.GeoDataFrame, tolerance_m: float) -> gpd.GeoDataFrame:
    poi_cols = [col for col in ["poi_uid", "source", "source_id", "name_en", "name_zh", "wedan_category", "is_work_related"] if col in pois.columns]
    pois_proj = pois[poi_cols + ["geometry"]].to_crs(MODEL_CRS).reset_index(drop=False).rename(columns={"index": "poi_index"})
    grid_proj = grid[["grid_id", "locations", "geometry"]].to_crs(MODEL_CRS).reset_index(drop=True)

    joined = gpd.sjoin(pois_proj, grid_proj, how="left", predicate="within").drop(columns=["index_right"])
    unmatched = joined["grid_id"].isna()
    if unmatched.any():
        nearest = gpd.sjoin_nearest(
            pois_proj.loc[unmatched, poi_cols + ["poi_index", "geometry"]],
            grid_proj,
            how="left",
            max_distance=tolerance_m,
            distance_col="nearest_distance_m",
        ).drop(columns=["index_right"])
        nearest = nearest.drop_duplicates(subset=["poi_index"], keep="first")
        nearest = nearest.set_index("poi_index")
        joined = joined.set_index("poi_index")
        for col in ["grid_id", "locations"]:
            joined.loc[nearest.index, col] = nearest[col]
        joined["assignment_method"] = "within"
        joined.loc[nearest.index, "assignment_method"] = "nearest"
        joined["nearest_distance_m"] = np.nan
        joined.loc[nearest.index, "nearest_distance_m"] = nearest["nearest_distance_m"]
        joined = joined.reset_index()
    else:
        joined["assignment_method"] = "within"
        joined["nearest_distance_m"] = np.nan

    return pd.DataFrame(joined.drop(columns="geometry"))


def main() -> None:
    args = parse_args()
    for path in [args.grid, args.pois]:
        if not path.exists():
            raise FileNotFoundError(path)

    grid = gpd.read_file(args.grid).reset_index(drop=True)
    pois = gpd.read_file(args.pois)
    if grid.empty:
        raise ValueError(f"Grid is empty: {args.grid}")
    if pois.empty:
        raise ValueError(f"POI layer is empty: {args.pois}")
    if "wedan_category" not in pois.columns:
        raise ValueError("Integrated POI layer must contain a wedan_category column.")

    assignments = assign_pois_to_grid(pois, grid, args.boundary_nearest_m)
    assignments["normalized_category"] = assignments["wedan_category"].map(normalize_category)
    assignments["is_counted"] = assignments["normalized_category"].isin(POI_CATEGORIES) & assignments["grid_id"].notna()

    pois_array = np.zeros((len(grid), len(POI_CATEGORIES)), dtype="int64")
    for row in assignments.loc[assignments["is_counted"]].itertuples(index=False):
        pois_array[int(row.grid_id), CATEGORY_TO_INDEX[row.normalized_category]] += 1

    args.out_dir.mkdir(parents=True, exist_ok=True)
    pois_path = args.out_dir / "pois.npy"
    np.save(pois_path, pois_array)

    assignments_path = args.out_dir / "poi_grid_assignments.csv"
    assignments.to_csv(assignments_path, index=False, encoding="utf-8-sig")

    category_counts = pd.DataFrame(
        {
            "category": POI_CATEGORIES,
            "category_index": list(range(len(POI_CATEGORIES))),
            "poi_count": pois_array.sum(axis=0).astype(int),
        }
    )
    category_counts_path = args.out_dir / "poi_category_counts.csv"
    category_counts.to_csv(category_counts_path, index=False, encoding="utf-8-sig")

    categories_path = args.out_dir / "poi_categories.json"
    categories_path.write_text(json.dumps(POI_CATEGORIES, indent=2, ensure_ascii=False), encoding="utf-8")

    raw_category_counter = Counter(assignments["normalized_category"].fillna("unmapped"))
    source_counter = Counter(assignments["source"].fillna("unknown")) if "source" in assignments.columns else {}
    summary = {
        "city": CITY_NAME,
        "grid": str(args.grid),
        "pois": str(args.pois),
        "output_dir": str(args.out_dir),
        "pois_output": str(pois_path),
        "shape": list(pois_array.shape),
        "dtype": str(pois_array.dtype),
        "grid_count": int(len(grid)),
        "input_pois": int(len(pois)),
        "assigned_pois": int(assignments["grid_id"].notna().sum()),
        "unassigned_pois": int(assignments["grid_id"].isna().sum()),
        "counted_pois": int(assignments["is_counted"].sum()),
        "unmapped_or_uncounted_pois": int((~assignments["is_counted"]).sum()),
        "nonzero_grids": int(np.count_nonzero(pois_array.sum(axis=1) > 0)),
        "total_category_counts": {row.category: int(row.poi_count) for row in category_counts.itertuples(index=False)},
        "raw_wedan_category_counts": dict(sorted(raw_category_counter.items())),
        "source_counts": dict(sorted(source_counter.items())) if source_counter else {},
        "assignment_tolerance_m": args.boundary_nearest_m,
        "assignments_csv": str(assignments_path),
        "category_counts_csv": str(category_counts_path),
        "categories_json": str(categories_path),
        "note": "Only POIs with a recognized WEDAN 34-category value are counted in pois.npy; unmapped POIs remain in the assignment audit.",
    }
    summary_path = args.out_dir / "pois_generation_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Grid cells: {len(grid)}")
    print(f"Input POIs: {len(pois)}")
    print(f"Counted POIs: {summary['counted_pois']}")
    print(f"Wrote: {pois_path} shape={pois_array.shape}")
    print(f"Wrote: {summary_path}")


if __name__ == "__main__":
    main()
