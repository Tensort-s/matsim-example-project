#!/usr/bin/env python3
"""Validate Hong Kong WEDAN OD against 2021 Census commute tables 7.8 and 7.9."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
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


ROOT = Path(__file__).resolve().parents[3]
MODEL_CRS = "EPSG:32650"
CITY_NAME = "hong_kong_fixed_link_grid"
DEFAULT_BASE = ROOT / "data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid"
DEFAULT_GRID = DEFAULT_BASE / "CityAndRegionSplit/hong_kong_fixed_link_grid/regions.shp"
DEFAULT_DC = ROOT / "data/boundary/hongkong/2021_Population_Census_Statistics_and_Boundar_SHP/DC_21C_converted.shp"
DEFAULT_NEWTOWN = ROOT / "data/boundary/hongkong/Boundaries_of_New_Towns_for_2021_Population_C_SHP/NewTown_2021.shp"
DEFAULT_OD = DEFAULT_BASE / "CommutingODFlows/hong_kong_fixed_link_grid/generation.npy"
DEFAULT_CONSTRAINT_DIR = DEFAULT_BASE / "census_2021_commute_constraints"
DEFAULT_TARGET = DEFAULT_CONSTRAINT_DIR / "census_2021_area_od_target_4area.csv"
DEFAULT_TABLE_79 = DEFAULT_CONSTRAINT_DIR / "table_7_9_commute_mode_by_residence.csv"

HKI_DISTRICTS = {"Central and Western", "Wan Chai", "Eastern", "Southern"}
KOWLOON_DISTRICTS = {"Yau Tsim Mong", "Sham Shui Po", "Kowloon City", "Wong Tai Sin", "Kwun Tong"}
AREA_ORDER = ["hong_kong_island", "kowloon", "new_towns", "other_nt_marine"]
AREA_LABELS = {
    "hong_kong_island": "Hong Kong Island",
    "kowloon": "Kowloon",
    "new_towns": "New towns",
    "other_nt_marine": "Other areas in the New Territories and Marine",
}
AREA_LABELS_ZH = {
    "hong_kong_island": "香港島",
    "kowloon": "九龍",
    "new_towns": "新市鎮",
    "other_nt_marine": "新界其他地區及水上",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grid", type=Path, default=DEFAULT_GRID, help="Hong Kong fixed-link grid regions.shp.")
    parser.add_argument("--district-boundary", type=Path, default=DEFAULT_DC, help="District Council boundary shapefile.")
    parser.add_argument("--newtown-boundary", type=Path, default=DEFAULT_NEWTOWN, help="2021 New Town boundary shapefile.")
    parser.add_argument("--od", type=Path, default=DEFAULT_OD, help="Original WEDAN generation.npy.")
    parser.add_argument("--target-od", type=Path, default=DEFAULT_TARGET, help="Census 4-area target OD CSV from table 7.8.")
    parser.add_argument("--table-7-9", type=Path, default=DEFAULT_TABLE_79, help="Table 7.9 tidy CSV.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_CONSTRAINT_DIR, help="Output directory.")
    parser.add_argument(
        "--newtown-min-overlap-share",
        type=float,
        default=0.25,
        help="Classify an NT grid as New towns if this share of its polygon overlaps a New Town boundary.",
    )
    return parser.parse_args()


def district_to_base_area(dc_eng: str) -> str:
    if dc_eng in HKI_DISTRICTS:
        return "hong_kong_island"
    if dc_eng in KOWLOON_DISTRICTS:
        return "kowloon"
    return "new_territories"


def union_geometry(gdf: gpd.GeoDataFrame):
    if hasattr(gdf.geometry, "union_all"):
        return gdf.geometry.union_all()
    return gdf.geometry.unary_union


def assign_grid_areas(
    grid: gpd.GeoDataFrame,
    districts: gpd.GeoDataFrame,
    newtowns: gpd.GeoDataFrame,
    min_overlap_share: float,
) -> pd.DataFrame:
    grid_metric = grid.to_crs(MODEL_CRS).reset_index(drop=True)
    districts_metric = districts.to_crs(MODEL_CRS)
    newtowns_metric = newtowns.to_crs(MODEL_CRS)

    centroids = grid_metric.copy()
    centroids["geometry"] = grid_metric.geometry.centroid
    joined = gpd.sjoin(
        centroids[["grid_id", "locations", "geometry"]],
        districts_metric[["dc_eng", "geometry"]],
        how="left",
        predicate="within",
    ).drop(columns=["index_right"])
    missing = joined["dc_eng"].isna()
    if missing.any():
        nearest = gpd.sjoin_nearest(
            centroids.loc[missing, ["grid_id", "locations", "geometry"]],
            districts_metric[["dc_eng", "geometry"]],
            how="left",
        ).drop(columns=["index_right"])
        nearest = nearest.drop_duplicates("grid_id").set_index("grid_id")
        joined = joined.set_index("grid_id")
        joined.loc[nearest.index, "dc_eng"] = nearest["dc_eng"]
        joined = joined.reset_index()

    joined = joined.sort_values("grid_id").reset_index(drop=True)
    joined["base_area_code"] = joined["dc_eng"].map(district_to_base_area)

    newtown_union = union_geometry(newtowns_metric)
    newtown_centroid = centroids.geometry.within(newtown_union).to_numpy()
    newtown_overlap_m2 = grid_metric.geometry.intersection(newtown_union).area.to_numpy()
    grid_area_m2 = grid_metric.geometry.area.to_numpy()
    newtown_overlap_share = np.divide(
        newtown_overlap_m2,
        grid_area_m2,
        out=np.zeros_like(newtown_overlap_m2, dtype="float64"),
        where=grid_area_m2 > 0,
    )

    area_codes = []
    for idx, row in joined.iterrows():
        if row["base_area_code"] in {"hong_kong_island", "kowloon"}:
            area_codes.append(row["base_area_code"])
        elif newtown_centroid[idx] or newtown_overlap_share[idx] >= min_overlap_share:
            area_codes.append("new_towns")
        else:
            area_codes.append("other_nt_marine")

    centroid_wgs84 = centroids.to_crs("EPSG:4326")
    assignment = pd.DataFrame(
        {
            "grid_id": joined["grid_id"].astype(int),
            "locations": joined["locations"],
            "dc_eng": joined["dc_eng"],
            "base_area_code": joined["base_area_code"],
            "area_code": area_codes,
            "area_en": [AREA_LABELS[code] for code in area_codes],
            "area_zh": [AREA_LABELS_ZH[code] for code in area_codes],
            "newtown_centroid_within": newtown_centroid.astype(bool),
            "newtown_overlap_m2": newtown_overlap_m2,
            "newtown_overlap_share": newtown_overlap_share,
            "centroid_lon": centroid_wgs84.geometry.x.to_numpy(),
            "centroid_lat": centroid_wgs84.geometry.y.to_numpy(),
        }
    )
    if assignment["area_code"].isna().any():
        raise ValueError("Grid area assignment produced null area_code values.")
    return assignment


def compute_area_matrix(od: np.ndarray, assignments: pd.DataFrame) -> pd.DataFrame:
    area_idx = {area: assignments.index[assignments["area_code"].eq(area)].to_numpy() for area in AREA_ORDER}
    rows = []
    for origin in AREA_ORDER:
        oi = area_idx[origin]
        for destination in AREA_ORDER:
            di = area_idx[destination]
            rows.append(
                {
                    "residence_area_code": origin,
                    "residence_area_en": AREA_LABELS[origin],
                    "residence_area_zh": AREA_LABELS_ZH[origin],
                    "workplace_area_code": destination,
                    "workplace_area_en": AREA_LABELS[destination],
                    "workplace_area_zh": AREA_LABELS_ZH[destination],
                    "wedan_original_sum": float(od[np.ix_(oi, di)].astype("float64").sum()),
                    "origin_grids": int(len(oi)),
                    "destination_grids": int(len(di)),
                }
            )
    return pd.DataFrame(rows)


def compare_area_od(wedan_area: pd.DataFrame, target: pd.DataFrame, global_unit: float) -> pd.DataFrame:
    merged = wedan_area.merge(
        target[["residence_area_code", "workplace_area_code", "workers"]],
        on=["residence_area_code", "workplace_area_code"],
        how="left",
        validate="one_to_one",
    )
    if merged["workers"].isna().any():
        raise ValueError("Census target is missing one or more 4-area OD blocks.")

    wedan_total = float(merged["wedan_original_sum"].sum())
    census_total = float(merged["workers"].sum())
    merged["wedan_original_share"] = merged["wedan_original_sum"] / wedan_total
    merged["census_share"] = merged["workers"] / census_total
    merged["wedan_global_unit_scaled_workers"] = merged["wedan_original_sum"] * global_unit
    merged["scaled_minus_census_workers"] = merged["wedan_global_unit_scaled_workers"] - merged["workers"]
    merged["share_error"] = merged["wedan_original_share"] - merged["census_share"]
    merged["abs_share_error"] = merged["share_error"].abs()
    merged["relative_error_after_global_unit"] = np.where(
        merged["workers"] > 0,
        merged["scaled_minus_census_workers"] / merged["workers"],
        np.nan,
    )
    merged["block_workers_per_wedan_unit"] = np.where(
        merged["wedan_original_sum"] > 0,
        merged["workers"] / merged["wedan_original_sum"],
        np.nan,
    )
    merged["block_unit_factor_ratio_to_global"] = merged["block_workers_per_wedan_unit"] / global_unit
    return merged


def compare_margins(comparison: pd.DataFrame, axis: str) -> pd.DataFrame:
    if axis == "origin":
        group_cols = ["residence_area_code", "residence_area_en", "residence_area_zh"]
        out_cols = {
            "residence_area_code": "area_code",
            "residence_area_en": "area_en",
            "residence_area_zh": "area_zh",
        }
    elif axis == "destination":
        group_cols = ["workplace_area_code", "workplace_area_en", "workplace_area_zh"]
        out_cols = {
            "workplace_area_code": "area_code",
            "workplace_area_en": "area_en",
            "workplace_area_zh": "area_zh",
        }
    else:
        raise ValueError(axis)
    grouped = (
        comparison.groupby(group_cols, as_index=False)
        .agg(
            census_workers=("workers", "sum"),
            wedan_original_sum=("wedan_original_sum", "sum"),
            wedan_global_unit_scaled_workers=("wedan_global_unit_scaled_workers", "sum"),
        )
        .rename(columns=out_cols)
    )
    census_total = grouped["census_workers"].sum()
    wedan_total = grouped["wedan_original_sum"].sum()
    grouped["census_share"] = grouped["census_workers"] / census_total
    grouped["wedan_original_share"] = grouped["wedan_original_sum"] / wedan_total
    grouped["share_error"] = grouped["wedan_original_share"] - grouped["census_share"]
    grouped["abs_share_error"] = grouped["share_error"].abs()
    grouped["relative_error_after_global_unit"] = (
        grouped["wedan_global_unit_scaled_workers"] - grouped["census_workers"]
    ) / grouped["census_workers"]
    return grouped


def jensen_shannon_divergence(p: np.ndarray, q: np.ndarray) -> float:
    p = p.astype("float64")
    q = q.astype("float64")
    p = p / p.sum()
    q = q / q.sum()
    m = 0.5 * (p + q)

    def kl(a: np.ndarray, b: np.ndarray) -> float:
        mask = a > 0
        return float(np.sum(a[mask] * np.log(a[mask] / b[mask])))

    return 0.5 * kl(p, m) + 0.5 * kl(q, m)


def mode_share_by_residence(table79: pd.DataFrame) -> pd.DataFrame:
    non_total = table79[(table79["mode_code"] != "total") & (table79["residence_area_4_code"] != "total")].copy()
    totals = table79[(table79["mode_code"] == "total") & (table79["residence_area_4_code"] != "total")][
        ["residence_area_4_code", "workers"]
    ].rename(columns={"workers": "residence_total_workers"})
    out = non_total.merge(totals, on="residence_area_4_code", how="left", validate="many_to_one")
    out["mode_share_within_residence_area"] = out["workers"] / out["residence_total_workers"]
    return out


def save_global_unit_scaled_od(od: np.ndarray, global_unit: float, out_dir: Path) -> tuple[Path, Path, float]:
    scaled = od.astype("float64") * global_unit
    np.fill_diagonal(scaled, 0.0)
    npy_path = out_dir / "generation_2021_census_global_unit_scaled.npy"
    csv_path = out_dir / "generation_2021_census_global_unit_scaled.csv"
    np.save(npy_path, scaled.astype("float32"))
    np.savetxt(csv_path, scaled, delimiter=",", fmt="%.6f")
    return npy_path, csv_path, float(scaled.sum())


def main() -> None:
    args = parse_args()
    for path in [args.grid, args.district_boundary, args.newtown_boundary, args.od, args.target_od, args.table_7_9]:
        if not path.exists():
            raise FileNotFoundError(path)
    if not 0.0 <= args.newtown_min_overlap_share <= 1.0:
        raise ValueError("--newtown-min-overlap-share must be between 0 and 1")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    grid = gpd.read_file(args.grid).reset_index(drop=True)
    districts = gpd.read_file(args.district_boundary)
    newtowns = gpd.read_file(args.newtown_boundary)
    od = np.load(args.od)
    target = pd.read_csv(args.target_od)
    table79 = pd.read_csv(args.table_7_9)
    if od.shape != (len(grid), len(grid)):
        raise ValueError(f"OD/grid shape mismatch: od={od.shape}, grid={len(grid)}")

    assignments = assign_grid_areas(grid, districts, newtowns, args.newtown_min_overlap_share)
    if len(assignments) != len(grid):
        raise ValueError(f"Assignment row count mismatch: {len(assignments)} != {len(grid)}")
    area_counts = assignments["area_code"].value_counts().reindex(AREA_ORDER, fill_value=0).astype(int).to_dict()
    if any(value == 0 for value in area_counts.values()):
        raise ValueError(f"At least one Census 4-area class has zero assigned grids: {area_counts}")

    target_total = int(target["workers"].sum())
    original_total = float(od.astype("float64").sum())
    if target_total != 2_659_558:
        raise ValueError(f"Unexpected Census target total: {target_total}")
    if not np.isfinite(od).all() or (od < 0).any():
        raise ValueError("Original OD must be finite and non-negative.")

    global_workers_per_wedan_unit = target_total / original_total
    wedan_units_per_worker = original_total / target_total
    scaled_npy, scaled_csv, scaled_total = save_global_unit_scaled_od(od, global_workers_per_wedan_unit, args.out_dir)

    wedan_area = compute_area_matrix(od, assignments)
    comparison = compare_area_od(wedan_area, target, global_workers_per_wedan_unit)
    origin_margins = compare_margins(comparison, "origin")
    destination_margins = compare_margins(comparison, "destination")
    mode_shares = mode_share_by_residence(table79)

    comparison_path = args.out_dir / "wedan_original_vs_census_area_od_4area.csv"
    origin_path = args.out_dir / "wedan_original_vs_census_origin_margins_4area.csv"
    destination_path = args.out_dir / "wedan_original_vs_census_destination_margins_4area.csv"
    assignment_path = args.out_dir / "grid_2021_census_4area_assignment.csv"
    mode_share_path = args.out_dir / "census_2021_mode_share_by_residence_4area.csv"
    comparison.to_csv(comparison_path, index=False, encoding="utf-8-sig")
    origin_margins.to_csv(origin_path, index=False, encoding="utf-8-sig")
    destination_margins.to_csv(destination_path, index=False, encoding="utf-8-sig")
    assignments.to_csv(assignment_path, index=False, encoding="utf-8-sig")
    mode_shares.to_csv(mode_share_path, index=False, encoding="utf-8-sig")

    share_errors = comparison["share_error"].to_numpy(dtype="float64")
    census_share = comparison["census_share"].to_numpy(dtype="float64")
    wedan_share = comparison["wedan_original_share"].to_numpy(dtype="float64")
    summary = {
        "city": CITY_NAME,
        "method": "global_unit_inference_and_4area_share_validation",
        "input_od": str(args.od),
        "grid": str(args.grid),
        "district_boundary": str(args.district_boundary),
        "newtown_boundary": str(args.newtown_boundary),
        "target_4area_od": str(args.target_od),
        "table_7_9": str(args.table_7_9),
        "grid_assignment_csv": str(assignment_path),
        "area_comparison_csv": str(comparison_path),
        "origin_margin_comparison_csv": str(origin_path),
        "destination_margin_comparison_csv": str(destination_path),
        "mode_share_csv": str(mode_share_path),
        "global_unit_scaled_od": str(scaled_npy),
        "global_unit_scaled_csv": str(scaled_csv),
        "shape": list(od.shape),
        "original_od_sum": original_total,
        "census_fixed_workplace_total": target_total,
        "global_workers_per_wedan_unit": global_workers_per_wedan_unit,
        "global_wedan_units_per_worker": wedan_units_per_worker,
        "global_unit_scaled_sum": scaled_total,
        "global_unit_scaled_sum_close_to_census": math.isclose(scaled_total, target_total, rel_tol=1e-6, abs_tol=1e-2),
        "original_diag_sum": float(np.diag(od).sum()),
        "area_counts": area_counts,
        "share_mae_16_blocks": float(np.mean(np.abs(share_errors))),
        "share_rmse_16_blocks": float(np.sqrt(np.mean(share_errors**2))),
        "total_variation_distance_16_blocks": float(0.5 * np.sum(np.abs(share_errors))),
        "jensen_shannon_divergence_16_blocks": jensen_shannon_divergence(wedan_share, census_share),
        "max_abs_share_error_block": comparison.loc[
            comparison["abs_share_error"].idxmax(),
            ["residence_area_code", "workplace_area_code", "share_error", "abs_share_error"],
        ].to_dict(),
        "max_relative_error_after_global_unit_block": comparison.loc[
            comparison["relative_error_after_global_unit"].abs().idxmax(),
            [
                "residence_area_code",
                "workplace_area_code",
                "relative_error_after_global_unit",
                "wedan_global_unit_scaled_workers",
                "workers",
            ],
        ].to_dict(),
        "notes": [
            "Table 7.8 supplies the 4-area residence-to-workplace validation matrix for fixed workplaces in Hong Kong.",
            "Table 7.9 supplies the matching fixed-workplace total and residence-area mode split.",
            "The global-unit scaled OD preserves the original WEDAN spatial proportions; it is not area-corrected.",
            "Per-block unit factors diagnose spatial bias: if they differ strongly from the global factor, WEDAN area ratios do not match Census.",
        ],
    }
    summary_path = args.out_dir / "wedan_flow_unit_inference_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote: {assignment_path}")
    print(f"Wrote: {comparison_path}")
    print(f"Wrote: {origin_path}")
    print(f"Wrote: {destination_path}")
    print(f"Wrote: {mode_share_path}")
    print(f"Wrote: {scaled_npy}")
    print(f"Wrote: {summary_path}")
    print(
        "Global unit: "
        f"1 WEDAN unit = {global_workers_per_wedan_unit:.8f} workers; "
        f"1 worker = {wedan_units_per_worker:.3f} WEDAN units"
    )
    print(
        "Share validation: "
        f"MAE={summary['share_mae_16_blocks']:.6f}, "
        f"RMSE={summary['share_rmse_16_blocks']:.6f}, "
        f"TVD={summary['total_variation_distance_16_blocks']:.6f}"
    )


if __name__ == "__main__":
    main()
