#!/usr/bin/env python3
"""Prepare compact non-geospatial inputs for Hong Kong LSUG calibration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / "data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid"
DEFAULT_LSUG = (
    ROOT
    / "data/gee/hongkong/worldpop_age_sex"
    / "2021_Population_Census_Statistics_ LargeSubunitGroups/LSUG_21C_converted.shp"
)
DEFAULT_DISTRICTS = (
    ROOT / "data/boundary/hongkong/2021_Population_Census_Statistics_and_Boundar_SHP/DC_21C_converted.shp"
)
DEFAULT_DIAGNOSTIC_DIR = BASE / "census_2021_commute_constraints/lsug_grid_resolution_diagnostics"
DEFAULT_GRID_ASSIGNMENT = BASE / "census_2021_commute_constraints/grid_2021_census_4area_assignment.csv"
DEFAULT_CITY_DIR = BASE / "GeneratingCodeData/data/global_cities/hong_kong_fixed_link_grid"
DEFAULT_OUT_DIR = BASE / "census_2021_commute_constraints/lsug_calibration_inputs"
FLOW_FIELDS = ["plw_hk", "plw_kln", "plw_nt"]
ORIGIN_AREA_ORDER = ["hong_kong_island", "kowloon", "new_towns", "other_nt_marine"]
DESTINATION_AREA_ORDER = ["hong_kong_island", "kowloon", "new_territories"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lsug", type=Path, default=DEFAULT_LSUG)
    parser.add_argument("--districts", type=Path, default=DEFAULT_DISTRICTS)
    parser.add_argument("--diagnostic-dir", type=Path, default=DEFAULT_DIAGNOSTIC_DIR)
    parser.add_argument("--grid-assignment", type=Path, default=DEFAULT_GRID_ASSIGNMENT)
    parser.add_argument("--city-dir", type=Path, default=DEFAULT_CITY_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args()


def assign_districts(lsug: gpd.GeoDataFrame, districts: gpd.GeoDataFrame) -> pd.DataFrame:
    points = lsug.to_crs(districts.crs).copy()
    points.geometry = points.geometry.representative_point()
    joined = gpd.sjoin(
        points[["lsbg", "geometry"]], districts[["dc_eng", "dc_chi", "geometry"]], how="left", predicate="within"
    ).drop(columns=["index_right"])
    if joined["dc_eng"].isna().any():
        missing = joined.loc[joined["dc_eng"].isna(), "lsbg"].tolist()
        raise ValueError(f"LSUG district assignment failed: {missing[:10]}")
    if joined["lsbg"].duplicated().any():
        raise ValueError("LSUG district assignment produced duplicate rows.")
    return joined.drop(columns="geometry")


def destination_code(area_code: str) -> str:
    if area_code == "hong_kong_island":
        return "hong_kong_island"
    if area_code == "kowloon":
        return "kowloon"
    return "new_territories"


def main() -> None:
    args = parse_args()
    required = [
        args.lsug,
        args.districts,
        args.diagnostic_dir / "lsug_roundtrip_reconstruction.csv",
        args.diagnostic_dir / "lsug_by_grid_population_overlap.npz",
        args.grid_assignment,
        args.city_dir / "nfeat/worldpop.npy",
        args.city_dir / "nfeat/demos.npy",
        args.city_dir / "nfeat/demos_bands.json",
    ]
    for path in required:
        if not path.exists():
            raise FileNotFoundError(path)

    lsug = gpd.read_file(args.lsug).sort_values("lsbg").reset_index(drop=True)
    districts = gpd.read_file(args.districts)
    district_assignment = assign_districts(lsug, districts)
    reconstruction = pd.read_csv(args.diagnostic_dir / "lsug_roundtrip_reconstruction.csv", dtype={"lsbg": str})
    reconstruction["lsbg"] = reconstruction["lsbg"].astype(str)

    targets = lsug[["lsbg", "lsbg_eng", "lsbg_chi"]].copy()
    targets["lsbg"] = targets["lsbg"].astype(str)
    targets = targets.merge(district_assignment, on="lsbg", validate="one_to_one")
    target_columns = [
        "lsbg",
        "census_population",
        "population_in_model_boundary",
        "modeled_population_fraction",
        "represented_in_grid",
        "primary_full_coverage_qa",
        "true_plw_hk",
        "true_plw_kln",
        "true_plw_nt",
    ]
    targets = targets.merge(reconstruction[target_columns], on="lsbg", validate="one_to_one")
    targets = targets.sort_values("lsbg").reset_index(drop=True)
    targets["lsug_index"] = np.arange(len(targets), dtype="int64")
    targets["target_fixed_workplace_workers"] = targets[[f"true_{field}" for field in FLOW_FIELDS]].sum(axis=1)
    if targets["dc_eng"].nunique() != 18:
        raise ValueError(f"Expected 18 districts, got {targets['dc_eng'].nunique()}")

    grid = pd.read_csv(args.grid_assignment).sort_values("grid_id").reset_index(drop=True)
    if len(grid) != 1585 or not np.array_equal(grid["grid_id"].to_numpy(), np.arange(1585)):
        raise ValueError("Grid assignment must contain contiguous grid_id 0..1584.")
    worldpop = np.load(args.city_dir / "nfeat/worldpop.npy").astype("float64")
    demos = np.load(args.city_dir / "nfeat/demos.npy").astype("float64")
    bands = json.loads((args.city_dir / "nfeat/demos_bands.json").read_text(encoding="utf-8"))
    working_age_indices = [
        idx
        for idx, name in enumerate(bands)
        if name.split("_", maxsplit=1)[0] in {"M", "F"} and 15 <= int(name.split("_")[1]) <= 60
    ]
    working_age = demos[:, working_age_indices].sum(axis=1)
    demo_total = demos.sum(axis=1)
    working_age_share = np.divide(working_age, demo_total, out=np.zeros_like(working_age), where=demo_total > 0)

    grid_features = grid[["grid_id", "locations", "dc_eng", "area_code"]].copy()
    grid_features["origin_area_code"] = grid_features["area_code"]
    grid_features["origin_area_index"] = grid_features["origin_area_code"].map(
        {name: idx for idx, name in enumerate(ORIGIN_AREA_ORDER)}
    )
    grid_features["destination_area_code"] = grid_features["area_code"].map(destination_code)
    grid_features["destination_area_index"] = grid_features["destination_area_code"].map(
        {name: idx for idx, name in enumerate(DESTINATION_AREA_ORDER)}
    )
    grid_features["population_count"] = worldpop[:, 0]
    grid_features["log1p_population_count"] = np.log1p(worldpop[:, 0])
    grid_features["working_age_share"] = working_age_share
    if grid_features[["origin_area_index", "destination_area_index"]].isna().any().any():
        raise ValueError("Grid area mapping produced null indices.")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    target_path = args.out_dir / "lsug_calibration_targets.csv"
    grid_path = args.out_dir / "grid_calibration_features.csv"
    targets.to_csv(target_path, index=False, encoding="utf-8-sig")
    grid_features.to_csv(grid_path, index=False, encoding="utf-8-sig")

    summary = {
        "lsug_count": int(len(targets)),
        "district_count": int(targets["dc_eng"].nunique()),
        "represented_lsug_count": int(targets["represented_in_grid"].astype(bool).sum()),
        "primary_lsug_count": int(targets["primary_full_coverage_qa"].astype(bool).sum()),
        "primary_target_workers": float(
            targets.loc[targets["primary_full_coverage_qa"].astype(bool), "target_fixed_workplace_workers"].sum()
        ),
        "grid_count": int(len(grid_features)),
        "origin_area_order": ORIGIN_AREA_ORDER,
        "destination_area_order": DESTINATION_AREA_ORDER,
        "working_age_bands": [bands[idx] for idx in working_age_indices],
        "targets_output": str(target_path),
        "grid_features_output": str(grid_path),
        "crosswalk": str(args.diagnostic_dir / "lsug_by_grid_population_overlap.npz"),
    }
    summary_path = args.out_dir / "lsug_calibration_input_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote: {target_path}")
    print(f"Wrote: {grid_path}")
    print(f"Wrote: {summary_path}")


if __name__ == "__main__":
    main()
