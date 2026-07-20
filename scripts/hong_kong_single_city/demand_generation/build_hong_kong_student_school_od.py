#!/usr/bin/env python3
"""Build Hong Kong DCCA-constrained student-to-school OD products for 2022."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from scipy.sparse import csr_matrix, save_npz


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_ROOT = ROOT / "data"
WORK_CRS = "EPSG:32650"
FLOW_COLUMNS = ["pls_same", "pls_diff_hk", "pls_diff_kln", "pls_diff_nt", "s_diff_oth"]
FLOW_TO_CATEGORY = {
    "pls_same": "same",
    "pls_diff_hk": "diff_hk",
    "pls_diff_kln": "diff_kln",
    "pls_diff_nt": "diff_nt",
    "s_diff_oth": "diff_oth",
}
CATEGORIES = list(FLOW_TO_CATEGORY.values())
STAGES = ["kindergarten", "primary", "secondary", "special"]
BASE_DISTANCE_KM = {"kindergarten": 2.0, "primary": 3.0, "secondary": 5.0, "special": 8.0}
SCENARIOS = {"short": 0.75, "base": 1.0, "long": 1.5}
EXPECTED_DCCA_TOTALS = {
    "pls_same": 545_891.0,
    "pls_diff_hk": 113_562.0,
    "pls_diff_kln": 205_463.0,
    "pls_diff_nt": 180_337.0,
    "s_diff_oth": 18_192.0,
}
TCS_TRIPS = 1_162_000.0
TCS_STUDENTS = 1_105_500.0
TCS_BOARDINGS = 1_292_000.0

TCS_DISTRICT_NAMES = {
    1: "Central & Western",
    2: "Wan Chai",
    3: "Eastern",
    4: "Southern",
    5: "Yau Ma Tei",
    6: "Mong Kok",
    7: "Sham Shui Po",
    8: "Kowloon City",
    9: "Kwun Tong",
    10: "Wong Tai Sin",
    11: "Tsuen Wan",
    12: "Kwai Chung",
    13: "Tsing Yi",
    14: "Tuen Mun",
    15: "Yuen Long",
    16: "Tin Shui Wai",
    17: "Tai Po",
    18: "Fanling/Sheung Shui",
    19: "Sha Tin",
    20: "Ma On Shan",
    21: "Tseung Kwan O",
    22: "North Lantau",
    23: "NWNT Other",
    24: "NENT Other",
    25: "SENT Other",
    26: "SWNT Other",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--max-iterations", type=int, default=250)
    parser.add_argument("--tolerance", type=float, default=1e-7)
    parser.add_argument("--parquet-min-flow", type=float, default=1e-6)
    parser.add_argument("--skip-long-parquet", action="store_true")
    return parser.parse_args()


def data_paths(data_root: Path) -> dict[str, Path]:
    boundary_dir = data_root / "boundary/hongkong/2021_Population_Census_Statistics_and_Boundar_SHP"
    city_dir = data_root / "worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid"
    nfeat = city_dir / "GeneratingCodeData/data/global_cities/hong_kong_fixed_link_grid/nfeat"
    return {
        "dcca_shp": boundary_dir / "DCCA_21C_converted.shp",
        "dcca_xlsx": boundary_dir / "DCCA_21C.xlsx",
        "dc_shp": boundary_dir / "DC_21C_converted.shp",
        "newtown": data_root / "boundary/hongkong/Boundaries_of_New_Towns_for_2021_Population_C_SHP/NewTown_2021.shp",
        "boundary": data_root / "boundary/hongkong/processed/hong_kong_fixed_link_boundary_wgs84.geojson",
        "grid": city_dir / "CityAndRegionSplit/hong_kong_fixed_link_grid/regions.shp",
        "demos": nfeat / "demos.npy",
        "demos_bands": nfeat / "demos_bands.json",
        "distance": city_dir / "GeneratingCodeData/data/global_cities/hong_kong_fixed_link_grid/adj/dis.npy",
        "schools": data_root / "school/hongkong/SCH_LOC_EDB.csv",
        "annual": data_root / "school/hongkong/tab0103.xlsx",
        "tcs_district": data_root / "school/hongkong/tcs2022_school_od_csv_revised_bundle/tcs2022_school_od_district_inputs.csv",
        "tcs_mode": data_root / "school/hongkong/tcs2022_school_od_csv_revised_bundle/tcs2022_hbs_mode_boardings_appendix.csv",
        "raw_worldpop": data_root / "gee/hongkong/worldpop_age_sex/raw_worldpop",
    }


def require_paths(paths: dict[str, Path]) -> None:
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))


def clean_number(value: object, field: str) -> float:
    if pd.isna(value):
        return 0.0
    text = str(value).strip()
    if text == "**":
        raise ValueError(f"Suppressed Census value '**' found in {field}; refusing to impute.")
    if text in {"", "-", "--"}:
        return 0.0
    return float(text.replace(",", ""))


def slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return text or "unknown"


def normalize_code(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="raise").astype(int)


def read_dcca(paths: dict[str, Path]) -> gpd.GeoDataFrame:
    shape = gpd.read_file(paths["dcca_shp"])
    shape["dcca"] = normalize_code(shape["dcca"])
    if len(shape) != 452 or shape["dcca"].duplicated().any():
        raise ValueError(f"Expected 452 unique DCCA geometries, got {len(shape)}")

    excel = pd.read_excel(paths["dcca_xlsx"], sheet_name="DCCA", header=4)
    excel = excel[pd.to_numeric(excel["dcca"], errors="coerce").notna()].copy()
    excel["dcca"] = normalize_code(excel["dcca"])
    excel = excel[excel["dcca"].isin(set(shape["dcca"]))].copy()
    if len(excel) != 452 or excel["dcca"].duplicated().any():
        raise ValueError(f"Expected 452 unique DCCA rows in Excel, got {len(excel)}")
    for column in FLOW_COLUMNS:
        excel[column] = excel[column].map(lambda value, c=column: clean_number(value, c))

    rename = {"pls_diff_h": "pls_diff_hk", "pls_diff_k": "pls_diff_kln", "pls_diff_n": "pls_diff_nt"}
    shape = shape.rename(columns=rename)
    for column in FLOW_COLUMNS:
        shape[column] = shape[column].map(lambda value, c=column: clean_number(value, c))

    compare = shape[["dcca", *FLOW_COLUMNS]].merge(
        excel[["dcca", *FLOW_COLUMNS]], on="dcca", suffixes=("_shp", "_xlsx"), validate="one_to_one"
    )
    for column in FLOW_COLUMNS:
        delta = np.abs(compare[f"{column}_shp"] - compare[f"{column}_xlsx"])
        if float(delta.max()) > 0:
            raise ValueError(f"DCCA Excel/shapefile mismatch for {column}: max delta={delta.max()}")

    totals = excel[FLOW_COLUMNS].sum()
    for column, expected in EXPECTED_DCCA_TOTALS.items():
        if not math.isclose(float(totals[column]), expected, abs_tol=0.1):
            raise ValueError(f"Unexpected DCCA total for {column}: {totals[column]} != {expected}")

    keep = ["dcca", "dcca_eng", "ca_eng", "dc", "dc_eng", "age_1", "age_2", "t_pop", "geometry"]
    result = shape[keep].merge(excel[["dcca", *FLOW_COLUMNS]], on="dcca", validate="one_to_one")
    result["dc"] = normalize_code(result["dc"])
    result["flow_total_raw"] = result[FLOW_COLUMNS].sum(axis=1)
    return gpd.GeoDataFrame(result, geometry="geometry", crs=shape.crs)


def check_dcca_dc_aggregation(dcca: gpd.GeoDataFrame, dc_path: Path) -> None:
    dc = gpd.read_file(dc_path).rename(
        columns={"pls_diff_h": "pls_diff_hk", "pls_diff_k": "pls_diff_kln", "pls_diff_n": "pls_diff_nt"}
    )
    dc["dc"] = normalize_code(dc["dc"])
    for column in FLOW_COLUMNS:
        dc[column] = dc[column].map(lambda value, c=column: clean_number(value, c))
    grouped = dcca.groupby("dc")[FLOW_COLUMNS].sum().sort_index()
    official = dc.set_index("dc")[FLOW_COLUMNS].sort_index()
    delta = (grouped - official).abs()
    if float(delta.to_numpy().max()) > 0:
        raise ValueError(f"DCCA does not aggregate to DC totals; max delta={delta.to_numpy().max()}")


def build_study_areas(
    dc_path: Path, newtown_path: Path, boundary_path: Path
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    dc = gpd.read_file(dc_path).to_crs(WORK_CRS)
    dc["dc"] = normalize_code(dc["dc"])
    newtown = gpd.read_file(newtown_path).to_crs(WORK_CRS)
    boundary = gpd.read_file(boundary_path).to_crs(WORK_CRS)
    fixed = boundary.geometry.union_all()
    newtown_union = newtown.geometry.union_all()
    records: list[dict[str, object]] = []

    for row in dc.itertuples():
        geom = row.geometry.intersection(fixed)
        if geom.is_empty:
            continue
        if int(row.dc) in {11, 12, 13, 14}:
            macro = "hk_island"
        elif int(row.dc) in {23, 24, 25, 26, 27}:
            macro = "kowloon"
        else:
            continue
        records.append(
            {
                "study_area_id": f"dc_{int(row.dc)}",
                "study_area_name": str(row.dc_eng),
                "study_area_type": "dc_district",
                "macro_region": macro,
                "dc": int(row.dc),
                "dc_eng": str(row.dc_eng),
                "geometry": geom,
            }
        )

    dc_lookup = dc[["dc", "dc_eng", "geometry"]]
    newtown_join = gpd.sjoin(
        newtown[["NewTown_en", "geometry"]].copy(), dc_lookup, predicate="intersects", how="left"
    )
    for nt_name, group in newtown_join.groupby("NewTown_en", sort=False):
        geom = newtown.loc[newtown["NewTown_en"] == nt_name, "geometry"].union_all().intersection(fixed)
        if geom.is_empty:
            continue
        overlaps = []
        for dc_row in dc_lookup.itertuples():
            area = geom.intersection(dc_row.geometry).area
            if area > 0:
                overlaps.append((area, int(dc_row.dc), str(dc_row.dc_eng)))
        _, dc_code, dc_name = max(overlaps) if overlaps else (0.0, -1, "Unknown")
        records.append(
            {
                "study_area_id": f"nt_{slug(str(nt_name))}",
                "study_area_name": str(nt_name),
                "study_area_type": "new_town",
                "macro_region": "new_town",
                "dc": dc_code,
                "dc_eng": dc_name,
                "geometry": geom,
            }
        )

    nt_dc_codes = {31, 32, 33, 34, 35, 36, 37, 38, 39}
    for row in dc.itertuples():
        if int(row.dc) not in nt_dc_codes:
            continue
        geom = row.geometry.difference(newtown_union).intersection(fixed)
        if geom.is_empty or geom.area < 1.0:
            continue
        records.append(
            {
                "study_area_id": f"nt_other_dc_{int(row.dc)}",
                "study_area_name": f"{row.dc_eng} - other NT area",
                "study_area_type": "nt_other",
                "macro_region": "nt_other",
                "dc": int(row.dc),
                "dc_eng": str(row.dc_eng),
                "geometry": geom,
            }
        )

    areas = gpd.GeoDataFrame(records, geometry="geometry", crs=WORK_CRS)
    areas = areas[~areas.geometry.is_empty & areas.geometry.notna()].reset_index(drop=True)
    if areas["study_area_id"].duplicated().any():
        raise ValueError("Duplicate Census study_area_id values")
    return areas, boundary


def worldpop_retention_by_dcca(
    dcca: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame, raw_dir: Path
) -> pd.Series:
    weighted = None
    profile = None
    weights = {"1": 0.5, "5": 1.0, "10": 1.0, "15": 0.6}
    for sex in ["m", "f"]:
        for age, weight in weights.items():
            path = raw_dir / f"hkg_{sex}_{age}_2020.tif"
            with rasterio.open(path) as src:
                array = src.read(1).astype("float64")
                nodata = src.nodata
                if nodata is not None:
                    array[array == nodata] = 0.0
                array[~np.isfinite(array)] = 0.0
                array[array < 0] = 0.0
                if weighted is None:
                    weighted = np.zeros_like(array)
                    profile = (src.crs, src.transform, src.shape)
                weighted += array * weight
    assert weighted is not None and profile is not None
    raster_crs, transform, shape = profile
    dcca_raster = dcca.to_crs(raster_crs)
    labels = rasterize(
        [(geom, idx + 1) for idx, geom in enumerate(dcca_raster.geometry)],
        out_shape=shape,
        transform=transform,
        fill=0,
        dtype="int32",
    )
    fixed = boundary.to_crs(raster_crs).geometry.union_all()
    fixed_mask = rasterize([(fixed, 1)], out_shape=shape, transform=transform, fill=0, dtype="uint8")
    total = np.bincount(labels.ravel(), weights=weighted.ravel(), minlength=len(dcca) + 1)[1:]
    retained = np.bincount(
        labels.ravel(), weights=(weighted * fixed_mask).ravel(), minlength=len(dcca) + 1
    )[1:]
    ratio = np.divide(retained, total, out=np.zeros_like(retained), where=total > 0)
    ratio = np.clip(ratio, 0.0, 1.0)
    return pd.Series(ratio, index=dcca.index, name="fixed_link_population_ratio")


def read_grid_stage_mass(paths: dict[str, Path]) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    grid = gpd.read_file(paths["grid"]).to_crs(WORK_CRS).reset_index(drop=True)
    if "grid_id" not in grid:
        grid["grid_id"] = np.arange(len(grid), dtype=int)
    demos = np.load(paths["demos"]).astype("float64")
    bands = json.loads(paths["demos_bands"].read_text(encoding="utf-8"))
    if demos.shape != (len(grid), len(bands)):
        raise ValueError(f"Grid/demos mismatch: {len(grid)} vs {demos.shape}")
    band_index = {name: idx for idx, name in enumerate(bands)}

    def age_total(age: int) -> np.ndarray:
        return demos[:, band_index[f"M_{age}"]] + demos[:, band_index[f"F_{age}"]]

    age1, age5, age10, age15 = age_total(1), age_total(5), age_total(10), age_total(15)
    masses = pd.DataFrame(
        {
            "kindergarten": 0.5 * age1 + 0.2 * age5,
            "primary": 0.8 * age5 + 0.4 * age10,
            "secondary": 0.6 * age10 + 0.6 * age15,
        }
    )
    masses["special"] = masses[["kindergarten", "primary", "secondary"]].sum(axis=1)
    masses[masses < 0] = 0.0
    return grid, masses


def build_origin_crosswalk(
    dcca: gpd.GeoDataFrame,
    study_areas: gpd.GeoDataFrame,
    grid: gpd.GeoDataFrame,
    grid_stage_mass: pd.DataFrame,
) -> gpd.GeoDataFrame:
    left = dcca.to_crs(WORK_CRS)[["dcca", "dcca_eng", "ca_eng", "dc", "dc_eng", *FLOW_COLUMNS, "geometry"]].rename(
        columns={"dc": "residence_dc", "dc_eng": "residence_dc_eng"}
    )
    atoms = gpd.overlay(left, study_areas, how="intersection", keep_geom_type=True)
    atoms = atoms[atoms.geometry.area >= 1.0].copy().reset_index(drop=True)
    atoms["atom_id"] = np.arange(len(atoms), dtype=int)
    atoms["atom_area_m2"] = atoms.geometry.area

    pieces = gpd.overlay(
        grid[["grid_id", "geometry"]],
        atoms[["atom_id", "dcca", "dcca_eng", "ca_eng", "study_area_id", "study_area_name", "study_area_type", "macro_region", "dc", "dc_eng", "geometry"]],
        how="intersection",
        keep_geom_type=True,
    )
    pieces = pieces[pieces.geometry.area >= 1.0].copy().reset_index(drop=True)
    pieces["piece_area_m2"] = pieces.geometry.area
    pieces["grid_piece_share"] = pieces["piece_area_m2"] / pieces.groupby("grid_id")["piece_area_m2"].transform("sum")
    mass_lookup = grid[["grid_id"]].copy()
    for stage in STAGES:
        mass_lookup[f"raw_{stage}"] = grid_stage_mass[stage].to_numpy()
    pieces = pieces.merge(mass_lookup, on="grid_id", validate="many_to_one")
    for stage in STAGES:
        pieces[f"raw_{stage}"] *= pieces["grid_piece_share"]
    pieces["raw_school_age"] = pieces[[f"raw_{stage}" for stage in STAGES[:3]]].sum(axis=1)
    pieces["origin_unit_id"] = np.arange(len(pieces), dtype=int)
    if len(pieces) == 0:
        raise ValueError("No grid/DCCA/study-area origin pieces were created")
    return gpd.GeoDataFrame(pieces, geometry="geometry", crs=WORK_CRS)


def parse_annual_targets(path: Path) -> dict[tuple[str, str], float]:
    raw = pd.read_excel(path, sheet_name="TAB0103", header=None)
    year_columns = {int(raw.iat[4, idx]): idx for idx in range(raw.shape[1]) if pd.notna(raw.iat[4, idx]) and str(raw.iat[4, idx]).endswith(".0")}
    year_col = year_columns.get(2022)
    if year_col is None:
        raise ValueError("Could not find 2022 in tab0103.xlsx")
    targets = {
        ("kindergarten", "all"): float(raw.iat[11, year_col]),
        ("primary", "government"): float(raw.iat[14, year_col]),
        ("primary", "aided"): float(raw.iat[15, year_col]),
        ("primary", "dss"): float(raw.iat[16, year_col]),
        ("primary", "international"): float(raw.iat[17, year_col]),
        ("primary", "other_private"): float(raw.iat[18, year_col]),
        ("secondary", "government"): float(raw.iat[24, year_col]),
        ("secondary", "aided"): float(raw.iat[25, year_col]),
        ("secondary", "caput"): float(raw.iat[26, year_col]),
        ("secondary", "dss"): float(raw.iat[27, year_col]),
        ("secondary", "international"): float(raw.iat[28, year_col]),
        ("secondary", "other_private"): float(raw.iat[29, year_col]),
        ("special", "local_aided"): float(raw.iat[35, year_col]),
        ("special", "international"): float(raw.iat[36, year_col]),
        ("special", "other_private"): float(raw.iat[37, year_col]),
    }
    if not math.isclose(sum(targets.values()), 806_928.0, abs_tol=0.1):
        raise ValueError(f"Unexpected 2022 EDB total: {sum(targets.values())}")
    return targets


def school_sector(row: pd.Series) -> str:
    finance = str(row["FINANCE TYPE"]).upper()
    category = str(row["ENGLISH CATEGORY"]).upper()
    if "GOVERNMENT" in finance or "GOVERNMENT" in category:
        return "government"
    if "DIRECT SUBSIDY" in finance or "DIRECT SUBSIDY" in category:
        return "dss"
    if "CAPUT" in finance or "CAPUT" in category:
        return "caput"
    if "ENGLISH SCHOOLS FOUNDATION" in finance or "INTERNATIONAL" in category or "ENGLISH SCHOOLS FOUNDATION" in category:
        return "international"
    if "AIDED" in finance or "AIDED" in category:
        return "aided"
    return "other_private"


def base_school_stage(row: pd.Series) -> str:
    category = str(row["ENGLISH CATEGORY"]).upper()
    level = str(row["SCHOOL LEVEL"]).upper()
    if "SPECIAL" in category:
        return "special"
    if "KINDERGARTEN" in level:
        return "kindergarten"
    if level == "PRIMARY":
        return "primary"
    if level == "SECONDARY":
        return "secondary"
    raise ValueError(f"Unknown school level/category: {level!r} / {category!r}")


def classify_tcs_zone(dc: int, study_area_name: str, study_area_type: str, dcca_name: str) -> int:
    direct = {11: 1, 12: 2, 13: 3, 14: 4, 23: 7, 24: 8, 26: 9, 25: 10}
    if dc in direct:
        return direct[dc]
    if dc == 27:
        mong_kok_tokens = ["Mong Kok", "Fu Pak", "Olympic", "Cherry", "Tai Kok Tsui", "Tai Nan"]
        return 6 if any(token in dcca_name for token in mong_kok_tokens) else 5
    if study_area_type == "new_town":
        name = study_area_name.lower()
        mapping = {
            "tsuen wan -  tsuen wan area": 11,
            "tsuen wan -  kwai chung area": 12,
            "tsuen wan -  tsing yi area": 13,
            "tuen mun": 14,
            "yuen long": 15,
            "tin shui wai": 16,
            "tai po": 17,
            "fanling/sheung shui/kwu tung": 18,
            "sha tin  - sha tin area": 19,
            "sha tin -  ma on shan area": 20,
            "tseung kwan o": 21,
            "tung chung": 22,
            "hung shui kiu/ha tsuen": 23,
        }
        if name in mapping:
            return mapping[name]
    residual = {33: 23, 34: 23, 35: 24, 36: 24, 37: 25, 38: 25, 31: 26, 32: 26, 39: 26}
    if dc in residual:
        return residual[dc]
    raise ValueError(f"Cannot map TCS zone: dc={dc}, area={study_area_name}, type={study_area_type}")


def assign_point_areas(
    points: gpd.GeoDataFrame, study_areas: gpd.GeoDataFrame, dcca: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    joined = gpd.sjoin(points, study_areas, predicate="within", how="left")
    if joined["study_area_id"].isna().any():
        missing = joined[joined["study_area_id"].isna()].drop(columns=["index_right"], errors="ignore").copy()
        missing = missing.drop(columns=[c for c in study_areas.columns if c != "geometry" and c in missing.columns])
        nearest = gpd.sjoin_nearest(
            missing,
            study_areas,
            how="left",
            max_distance=1000,
        )
        for column in ["study_area_id", "study_area_name", "study_area_type", "macro_region", "dc", "dc_eng"]:
            joined.loc[missing.index, column] = nearest[column].to_numpy()
    dcca_points = gpd.sjoin(
        joined.drop(columns=["index_right"], errors="ignore"),
        dcca.to_crs(WORK_CRS)[["dcca", "dcca_eng", "geometry"]],
        predicate="within",
        how="left",
        rsuffix="dcca",
    )
    dcca_points["dcca_eng"] = dcca_points["dcca_eng"].fillna("")
    return dcca_points.drop(columns=["index_right"], errors="ignore")


def read_schools_and_programs(
    paths: dict[str, Path],
    boundary: gpd.GeoDataFrame,
    study_areas: gpd.GeoDataFrame,
    dcca: gpd.GeoDataFrame,
    grid: gpd.GeoDataFrame,
    annual_targets: dict[tuple[str, str], float],
) -> tuple[gpd.GeoDataFrame, pd.DataFrame, pd.DataFrame]:
    schools = pd.read_csv(paths["schools"], encoding="utf-16", dtype={"SCHOOL NO.": str})
    if len(schools) != 3489 or schools["SCHOOL NO."].duplicated().any():
        raise ValueError(f"Expected 3,489 unique EDB school program records, got {len(schools)}")
    geo = gpd.GeoDataFrame(
        schools,
        geometry=gpd.points_from_xy(schools["LONGITUDE"], schools["LATITUDE"]),
        crs="EPSG:4326",
    ).to_crs(WORK_CRS)
    fixed = boundary.geometry.union_all()
    geo["inside_fixed_link"] = geo.geometry.within(fixed) | geo.geometry.touches(fixed)
    geo["base_stage"] = geo.apply(base_school_stage, axis=1)
    geo["base_sector"] = geo.apply(school_sector, axis=1)
    geo.loc[geo["base_stage"] == "kindergarten", "base_sector"] = "all"
    geo.loc[geo["base_stage"] == "special", "base_sector"] = "local_aided"
    geo["campus_id"] = geo["SCHOOL NO."].str.slice(0, 9)
    geo["school_index"] = np.arange(len(geo), dtype=int)
    geo = assign_point_areas(geo, study_areas, dcca)
    missing_area = geo["dc"].isna()
    if missing_area.any():
        recovered_dc = (pd.to_numeric(geo.loc[missing_area, "dcca"], errors="coerce") // 100).astype("Int64")
        geo.loc[missing_area, "dc"] = recovered_dc.to_numpy()
        geo.loc[missing_area, "dc_eng"] = geo.loc[missing_area, "dcca_eng"].str.split(" - ").str[0].to_numpy()
        geo.loc[missing_area, "study_area_id"] = [
            f"nt_other_dc_{int(code)}" if pd.notna(code) else "nt_other_unknown" for code in recovered_dc
        ]
        geo.loc[missing_area, "study_area_name"] = geo.loc[missing_area, "dc_eng"].astype(str) + " - other NT area"
        geo.loc[missing_area, "study_area_type"] = "nt_other"
        geo.loc[missing_area, "macro_region"] = "nt_other"
    if geo["dc"].isna().any():
        raise ValueError("Some EDB school points could not be assigned to a Census study area or DCCA")
    geo["tcs_zone"] = [
        classify_tcs_zone(int(dc), str(area), str(area_type), str(dcca_name))
        for dc, area, area_type, dcca_name in zip(
            geo["dc"], geo["study_area_name"], geo["study_area_type"], geo["dcca_eng"]
        )
    ]
    grid_join = gpd.sjoin(
        geo.drop(columns=["index_right"], errors="ignore"), grid[["grid_id", "geometry"]], predicate="within", how="left"
    )
    if grid_join["grid_id"].isna().any():
        missing = grid_join[grid_join["grid_id"].isna()].drop(columns=["index_right"], errors="ignore").copy()
        nearest = gpd.sjoin_nearest(
            missing.drop(columns=["grid_id"], errors="ignore"), grid[["grid_id", "geometry"]], how="left", max_distance=1500
        )
        grid_join.loc[missing.index, "grid_id"] = nearest["grid_id"].to_numpy()
    geo = grid_join.drop(columns=["index_right"], errors="ignore")
    geo["grid_id"] = pd.to_numeric(geo["grid_id"], errors="coerce").astype("Int64")

    programs: list[dict[str, object]] = []
    for row in geo.itertuples():
        base_stage = str(row.base_stage)
        base_sector = str(row.base_sector)
        programs.append(
            {
                "school_index": int(row.school_index),
                "student_stage": base_stage,
                "sector": base_sector,
                "inside_fixed_link": bool(row.inside_fixed_link),
            }
        )
        if base_stage != "special" and base_sector == "international":
            programs.append(
                {
                    "school_index": int(row.school_index),
                    "student_stage": "special",
                    "sector": "international",
                    "inside_fixed_link": bool(row.inside_fixed_link),
                }
            )
        elif base_stage != "special" and base_sector == "other_private" and base_stage in {"primary", "secondary"}:
            programs.append(
                {
                    "school_index": int(row.school_index),
                    "student_stage": "special",
                    "sector": "other_private",
                    "inside_fixed_link": bool(row.inside_fixed_link),
                }
            )
    program_df = pd.DataFrame(programs)
    group_counts = program_df.groupby(["student_stage", "sector"])["inside_fixed_link"].agg(["sum", "count"])
    retained_targets: dict[tuple[str, str], float] = {}
    for key, full_target in annual_targets.items():
        if key not in group_counts.index:
            raise ValueError(f"No school programs for EDB stratum {key}")
        counts = group_counts.loc[key]
        retained_targets[key] = float(full_target) * float(counts["sum"]) / float(counts["count"])
    program_df["annual_target_full"] = [annual_targets[(s, k)] for s, k in zip(program_df.student_stage, program_df.sector)]
    count_lookup = group_counts["count"].to_dict()
    program_df["capacity_prior"] = [
        annual_targets[(s, k)] / count_lookup[(s, k)] for s, k in zip(program_df.student_stage, program_df.sector)
    ]
    retained_programs = program_df[program_df["inside_fixed_link"]].copy().reset_index(drop=True)
    retained_programs["program_index"] = np.arange(len(retained_programs), dtype=int)
    retained_programs = retained_programs.merge(
        geo[
            [
                "school_index",
                "SCHOOL NO.",
                "campus_id",
                "ENGLISH NAME",
                "中文名稱",
                "SESSION",
                "DISTRICT",
                "study_area_id",
                "study_area_name",
                "study_area_type",
                "macro_region",
                "dc",
                "dcca",
                "dcca_eng",
                "tcs_zone",
                "grid_id",
                "geometry",
            ]
        ],
        on="school_index",
        validate="many_to_one",
    )
    retained_programs = gpd.GeoDataFrame(retained_programs, geometry="geometry", crs=WORK_CRS)
    target_table = pd.DataFrame(
        [
            {
                "student_stage": stage,
                "sector": sector,
                "annual_target_full": annual_targets[(stage, sector)],
                "retained_target": target,
                "full_program_count": int(group_counts.loc[(stage, sector), "count"]),
                "retained_program_count": int(group_counts.loc[(stage, sector), "sum"]),
            }
            for (stage, sector), target in retained_targets.items()
        ]
    )
    return geo, retained_programs, target_table


def add_tcs_zones_to_origins(origins: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    result = origins.copy()
    result["tcs_zone"] = [
        classify_tcs_zone(int(dc), str(area), str(area_type), str(dcca_name))
        for dc, area, area_type, dcca_name in zip(
            result["dc"], result["study_area_name"], result["study_area_type"], result["dcca_eng"]
        )
    ]
    return result


def ipf_2d(prior: np.ndarray, row_targets: np.ndarray, col_targets: np.ndarray, iterations: int = 1000) -> np.ndarray:
    matrix = np.asarray(prior, dtype="float64").copy()
    matrix = np.maximum(matrix, 1e-12)
    for _ in range(iterations):
        row_sum = matrix.sum(axis=1)
        matrix *= np.divide(row_targets, row_sum, out=np.zeros_like(row_targets), where=row_sum > 0)[:, None]
        col_sum = matrix.sum(axis=0)
        matrix *= np.divide(col_targets, col_sum, out=np.zeros_like(col_targets), where=col_sum > 0)[None, :]
        if max(np.max(np.abs(matrix.sum(axis=1) - row_targets)), np.max(np.abs(matrix.sum(axis=0) - col_targets))) < 1e-7:
            break
    return matrix


def structural_ipf(
    prior: np.ndarray,
    support: np.ndarray,
    row_targets: np.ndarray,
    col_targets: np.ndarray,
    iterations: int = 10_000,
) -> np.ndarray | None:
    """Balance a small matrix while preserving structural zero cells."""
    positive_rows = row_targets > 1e-10
    positive_cols = col_targets > 1e-10
    if np.any(positive_rows & ~support[:, positive_cols].any(axis=1)):
        return None
    if np.any(positive_cols & ~support[positive_rows, :].any(axis=0)):
        return None
    scale = max(float(row_targets.sum()), 1.0)
    matrix = np.where(support, np.maximum(prior, scale * 1e-12), 0.0)
    for _ in range(iterations):
        row_sum = matrix.sum(axis=1)
        if np.any(positive_rows & (row_sum <= 0)):
            return None
        matrix *= np.divide(row_targets, row_sum, out=np.zeros_like(row_targets), where=row_sum > 0)[:, None]
        col_sum = matrix.sum(axis=0)
        if np.any(positive_cols & (col_sum <= 0)):
            return None
        matrix *= np.divide(col_targets, col_sum, out=np.zeros_like(col_targets), where=col_sum > 0)[None, :]
        error = max(
            float(np.max(np.abs(matrix.sum(axis=1) - row_targets))),
            float(np.max(np.abs(matrix.sum(axis=0) - col_targets))),
        )
        if error <= max(scale * 1e-10, 1e-7):
            return matrix
    return None


def reconcile_atom_category_targets(
    origins: gpd.GeoDataFrame,
    atom_table: pd.DataFrame,
    dcca_flows: pd.DataFrame,
    programs: gpd.GeoDataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Preserve DCCA margins when feasible and audit unavoidable school-support reallocations."""
    table = atom_table.copy()
    origin_weights = origins[[f"target_{stage}" for stage in STAGES]].sum(axis=1).to_numpy(dtype="float64")
    centroids = origins.geometry.centroid
    atom_xy: dict[int, tuple[float, float]] = {}
    for atom, indices in origins.groupby("atom_id").groups.items():
        idx = np.asarray(list(indices), dtype=int)
        weights = origin_weights[idx]
        if weights.sum() <= 0:
            weights = np.ones(len(idx), dtype="float64")
        atom_xy[int(atom)] = (
            float(np.average(centroids.x.to_numpy()[idx], weights=weights)),
            float(np.average(centroids.y.to_numpy()[idx], weights=weights)),
        )

    program_xy = np.column_stack([programs.geometry.x, programs.geometry.y])
    program_stages = programs["student_stage"].astype(str).to_numpy()
    audit_rows: list[dict[str, object]] = []
    result_parts: list[pd.DataFrame] = []
    for dcca_id, group in table.groupby("dcca", sort=True):
        group = group.copy().reset_index(drop=True)
        row_targets = group["target_students"].to_numpy(dtype="float64")
        census_values = dcca_flows.loc[int(dcca_id)].to_numpy(dtype="float64")
        shares = census_values / census_values.sum() if census_values.sum() > 0 else np.zeros(len(CATEGORIES))
        raw_matrix = row_targets[:, None] * shares[None, :]
        support = np.zeros_like(raw_matrix, dtype=bool)
        nearest = np.full_like(raw_matrix, np.inf, dtype="float64")
        for row_idx, atom_row in group.iterrows():
            origin_reference = origins.loc[origins["atom_id"] == int(atom_row["atom_id"])].iloc[0]
            program_categories = category_for_programs(origin_reference, programs)
            x, y = atom_xy[int(atom_row["atom_id"])]
            distances = np.sqrt((program_xy[:, 0] - x) ** 2 + (program_xy[:, 1] - y) ** 2)
            for category_idx, category in enumerate(CATEGORIES):
                mask = program_categories == category
                support[row_idx, category_idx] = bool(mask.any())
                if mask.any():
                    nearest[row_idx, category_idx] = float(distances[mask].min())

        balanced = structural_ipf(raw_matrix, support, row_targets, raw_matrix.sum(axis=0))
        method = "dcca_margin_preserved"
        if balanced is None:
            method = "nearest_supported_category_reallocation"
            balanced = raw_matrix.copy()
            for row_idx in range(len(group)):
                supported_categories = np.flatnonzero(support[row_idx])
                if len(supported_categories) == 0 and row_targets[row_idx] > 1e-9:
                    raise RuntimeError(
                        f"No retained EDB school support for DCCA {dcca_id}, atom {group.loc[row_idx, 'atom_id']}"
                    )
                for category_idx in range(len(CATEGORIES)):
                    mass = float(balanced[row_idx, category_idx])
                    if mass <= 0 or support[row_idx, category_idx]:
                        continue
                    replacement = int(supported_categories[np.argmin(nearest[row_idx, supported_categories])])
                    balanced[row_idx, category_idx] = 0.0
                    balanced[row_idx, replacement] += mass
                    audit_rows.append(
                        {
                            "dcca": int(dcca_id),
                            "atom_id": int(group.loc[row_idx, "atom_id"]),
                            "student_stage": "all",
                            "source_category": CATEGORIES[category_idx],
                            "destination_category": CATEGORIES[replacement],
                            "students_reallocated": mass,
                            "nearest_supported_school_distance_m": float(nearest[row_idx, replacement]),
                            "reason": "no retained compatible school in source category",
                        }
                    )

        # A category can have a school overall but no compatible program for one
        # student stage. Reconcile only the structurally impossible stage mass.
        for row_idx, atom_row in group.iterrows():
            atom_id = int(atom_row["atom_id"])
            atom_origin_rows = origins.loc[origins["atom_id"] == atom_id]
            stage_targets = atom_origin_rows[[f"target_{stage}" for stage in STAGES]].sum().to_numpy(
                dtype="float64"
            )
            category_targets = balanced[row_idx].copy()
            row_total = float(category_targets.sum())
            category_shares = category_targets / row_total if row_total > 0 else np.zeros(len(CATEGORIES))
            stage_category_prior = stage_targets[:, None] * category_shares[None, :]
            origin_reference = atom_origin_rows.iloc[0]
            program_categories = category_for_programs(origin_reference, programs)
            x, y = atom_xy[atom_id]
            distances = np.sqrt((program_xy[:, 0] - x) ** 2 + (program_xy[:, 1] - y) ** 2)
            stage_support = np.zeros((len(STAGES), len(CATEGORIES)), dtype=bool)
            stage_nearest = np.full((len(STAGES), len(CATEGORIES)), np.inf, dtype="float64")
            for stage_idx, stage in enumerate(STAGES):
                for category_idx, category in enumerate(CATEGORIES):
                    mask = (program_stages == stage) & (program_categories == category)
                    stage_support[stage_idx, category_idx] = bool(mask.any())
                    if mask.any():
                        stage_nearest[stage_idx, category_idx] = float(distances[mask].min())
            stage_balanced = structural_ipf(
                stage_category_prior,
                stage_support,
                stage_targets,
                category_targets,
            )
            if stage_balanced is None:
                stage_balanced = stage_category_prior.copy()
                for stage_idx, stage in enumerate(STAGES):
                    supported_categories = np.flatnonzero(stage_support[stage_idx])
                    if len(supported_categories) == 0 and stage_targets[stage_idx] > 1e-9:
                        raise RuntimeError(f"No retained EDB program support for atom {atom_id}, stage {stage}")
                    for category_idx in range(len(CATEGORIES)):
                        mass = float(stage_balanced[stage_idx, category_idx])
                        if mass <= 0 or stage_support[stage_idx, category_idx]:
                            continue
                        replacement = int(
                            supported_categories[np.argmin(stage_nearest[stage_idx, supported_categories])]
                        )
                        stage_balanced[stage_idx, category_idx] = 0.0
                        stage_balanced[stage_idx, replacement] += mass
                        audit_rows.append(
                            {
                                "dcca": int(dcca_id),
                                "atom_id": atom_id,
                                "student_stage": stage,
                                "source_category": CATEGORIES[category_idx],
                                "destination_category": CATEGORIES[replacement],
                                "students_reallocated": mass,
                                "nearest_supported_school_distance_m": float(
                                    stage_nearest[stage_idx, replacement]
                                ),
                                "reason": "no retained stage-compatible school in source category",
                            }
                        )
                balanced[row_idx] = stage_balanced.sum(axis=0)

        for category_idx, category in enumerate(CATEGORIES):
            group[f"raw_target_{category}"] = raw_matrix[:, category_idx]
            group[f"target_{category}"] = balanced[:, category_idx]
        group["support_reconciliation_method"] = method
        result_parts.append(group)

    audit = pd.DataFrame(
        audit_rows,
        columns=[
            "dcca",
            "atom_id",
            "student_stage",
            "source_category",
            "destination_category",
            "students_reallocated",
            "nearest_supported_school_distance_m",
            "reason",
        ],
    )
    return pd.concat(result_parts, ignore_index=True), audit


def build_origin_targets(
    origins: gpd.GeoDataFrame,
    dcca: gpd.GeoDataFrame,
    retained_target_table: pd.DataFrame,
    tcs_path: Path,
    programs: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    origins = origins.copy()
    stage_targets = retained_target_table.groupby("student_stage")["retained_target"].sum().reindex(STAGES)
    retained_total = float(stage_targets.sum())
    dcca_flow = dcca.set_index("dcca")["flow_total_raw"]
    origins["dcca_intensity"] = origins["dcca"].map(dcca_flow).fillna(0.0)
    raw_dcca_mass = origins.groupby("dcca")["raw_school_age"].transform("sum")
    origins["dcca_intensity"] = np.divide(
        origins["dcca_intensity"], raw_dcca_mass, out=np.zeros(len(origins)), where=raw_dcca_mass.to_numpy() > 0
    )
    for stage in STAGES:
        origins[f"prior_{stage}"] = origins[f"raw_{stage}"] * origins["dcca_intensity"]

    tcs = pd.read_csv(tcs_path)
    tcs["district_id"] = pd.to_numeric(tcs["district_id"]).astype(int)
    if set(tcs["district_id"]) != set(range(1, 27)):
        raise ValueError("TCS district table does not contain IDs 1..26")
    zone_retained = origins.groupby("tcs_zone")["raw_school_age"].sum().reindex(range(1, 27), fill_value=0.0)
    zone_prior = origins.groupby("tcs_zone")[[f"prior_{stage}" for stage in STAGES]].sum().reindex(range(1, 27), fill_value=0.0)
    resident = tcs.set_index("district_id")["resident_students"].astype(float).reindex(range(1, 27))
    retention_factor = np.ones(26, dtype="float64")
    # Only zones affected by removed islands should be downweighted. The origin coverage itself supplies the signal.
    if zone_retained.loc[26] > 0:
        dcca_swnt = dcca[dcca["dc"].isin([31, 32, 39])]
        full_swnt = float(dcca_swnt["flow_total_raw"].sum())
        retained_swnt = float(origins[origins["tcs_zone"] == 26]["raw_school_age"].sum())
        raw_swnt = float(origins[origins["tcs_zone"] == 26]["raw_school_age"].sum() / max(dcca_swnt["fixed_link_population_ratio"].mean(), 1e-6))
        if full_swnt > 0 and raw_swnt > 0:
            retention_factor[25] = min(1.0, retained_swnt / raw_swnt)
    zone_targets = resident.to_numpy() * retention_factor
    zone_targets *= retained_total / zone_targets.sum()
    zone_stage = ipf_2d(zone_prior.to_numpy(), zone_targets, stage_targets.to_numpy())

    for s_idx, stage in enumerate(STAGES):
        targets = np.zeros(len(origins), dtype="float64")
        for zone in range(1, 27):
            mask = origins["tcs_zone"].to_numpy() == zone
            weights = origins.loc[mask, f"prior_{stage}"].to_numpy(dtype="float64")
            if weights.sum() <= 0:
                weights = origins.loc[mask, f"raw_{stage}"].to_numpy(dtype="float64")
            if weights.sum() > 0:
                targets[mask] = zone_stage[zone - 1, s_idx] * weights / weights.sum()
        origins[f"target_{stage}"] = targets

    dcca_flows = dcca.set_index("dcca")[FLOW_COLUMNS]
    atom_totals = origins.groupby("atom_id")[[f"target_{stage}" for stage in STAGES]].sum().sum(axis=1)
    atom_table = origins.drop_duplicates("atom_id")[["atom_id", "dcca", "study_area_id", "tcs_zone"]].set_index("atom_id")
    atom_table["target_students"] = atom_totals
    atom_table, support_audit = reconcile_atom_category_targets(
        origins, atom_table.reset_index(), dcca_flows, programs
    )
    return origins, atom_table, tcs, support_audit


def category_for_programs(origin_row: pd.Series, programs: pd.DataFrame) -> np.ndarray:
    same = programs["study_area_id"].astype(str).to_numpy() == str(origin_row["study_area_id"])
    macro = programs["macro_region"].astype(str).to_numpy()
    area_type = programs["study_area_type"].astype(str).to_numpy()
    categories = np.full(len(programs), "diff_oth", dtype=object)
    categories[macro == "hk_island"] = "diff_hk"
    categories[macro == "kowloon"] = "diff_kln"
    categories[area_type == "new_town"] = "diff_nt"
    categories[same] = "same"
    return categories


def weighted_quantile(values: np.ndarray, weights: np.ndarray, quantile: float) -> float:
    order = np.argsort(values)
    sorted_values = values[order]
    cumulative = np.cumsum(weights[order])
    if cumulative[-1] <= 0:
        return 0.0
    return float(sorted_values[np.searchsorted(cumulative, quantile * cumulative[-1], side="left")])


def fit_assignment(
    origins: gpd.GeoDataFrame,
    atom_targets: pd.DataFrame,
    programs: pd.DataFrame,
    target_table: pd.DataFrame,
    scenario: str,
    max_iterations: int,
    tolerance: float,
) -> tuple[dict[str, np.ndarray], dict[str, object]]:
    scenario_scale = SCENARIOS[scenario]
    origin_xy = np.column_stack([origins.geometry.centroid.x, origins.geometry.centroid.y])
    matrices: dict[str, np.ndarray] = {}
    distances: dict[str, np.ndarray] = {}
    stage_programs: dict[str, pd.DataFrame] = {}
    category_codes: dict[str, np.ndarray] = {}
    atom_ids = atom_targets["atom_id"].to_numpy(dtype=int)
    atom_to_position = {int(atom): idx for idx, atom in enumerate(atom_ids)}
    origin_atom_position = origins["atom_id"].map(atom_to_position).to_numpy(dtype=int)
    atom_aggregator = csr_matrix(
        (
            np.ones(len(origins), dtype="float64"),
            (origin_atom_position, np.arange(len(origins), dtype=int)),
        ),
        shape=(len(atom_ids), len(origins)),
    )
    atom_category_targets = atom_targets[[f"target_{category}" for category in CATEGORIES]].to_numpy(
        dtype="float64"
    )
    atom_representatives = (
        origins.drop_duplicates("atom_id").set_index("atom_id").loc[atom_ids].reset_index()
    )

    for stage in STAGES:
        stage_p = programs[programs["student_stage"] == stage].copy().reset_index(drop=True)
        if stage_p.empty:
            raise ValueError(f"No retained programs for stage {stage}")
        stage_programs[stage] = stage_p
        school_xy = np.column_stack([stage_p.geometry.x, stage_p.geometry.y])
        distance = np.sqrt(((origin_xy[:, None, :] - school_xy[None, :, :]) ** 2).sum(axis=2))
        distances[stage] = distance
        kernel = np.exp(-distance / (BASE_DISTANCE_KM[stage] * scenario_scale * 1000.0))
        kernel *= stage_p["capacity_prior"].to_numpy(dtype="float64")[None, :]
        row_target = origins[f"target_{stage}"].to_numpy(dtype="float64")
        row_sum = kernel.sum(axis=1)
        matrix = kernel * np.divide(row_target, row_sum, out=np.zeros_like(row_target), where=row_sum > 0)[:, None]
        matrices[stage] = matrix
        codes = np.empty((len(atom_ids), len(stage_p)), dtype=np.int8)
        for atom_position, origin_row in atom_representatives.iterrows():
            categories = category_for_programs(origin_row, stage_p)
            codes[atom_position] = np.asarray([CATEGORIES.index(category) for category in categories], dtype=np.int8)
        category_codes[stage] = codes

    group_targets = target_table.set_index(["student_stage", "sector"])["retained_target"].to_dict()
    converged = False
    max_error = float("inf")
    error_components: dict[str, float] = {}
    for iteration in range(1, max_iterations + 1):
        for stage in STAGES:
            matrix = matrices[stage]
            target = origins[f"target_{stage}"].to_numpy(dtype="float64")
            current = matrix.sum(axis=1)
            matrix *= np.divide(target, current, out=np.zeros_like(target), where=current > 0)[:, None]

        for stage in STAGES:
            matrix = matrices[stage]
            stage_p = stage_programs[stage]
            for sector, cols_series in stage_p.groupby("sector").groups.items():
                cols = np.asarray(list(cols_series), dtype=int)
                target = float(group_targets[(stage, str(sector))])
                current = float(matrix[:, cols].sum())
                if current <= 0 and target > 0:
                    raise RuntimeError(f"Zero assignment support for {stage}/{sector}")
                if current > 0:
                    matrix[:, cols] *= target / current

        atom_category_current = np.zeros_like(atom_category_targets)
        atom_program_flows: dict[str, np.ndarray] = {}
        for stage in STAGES:
            atom_program = np.asarray(atom_aggregator @ matrices[stage])
            atom_program_flows[stage] = atom_program
            codes = category_codes[stage]
            for category_idx in range(len(CATEGORIES)):
                atom_category_current[:, category_idx] += np.where(
                    codes == category_idx, atom_program, 0.0
                ).sum(axis=1)
        missing_support = (atom_category_targets > 1e-9) & (atom_category_current <= 0)
        if missing_support.any():
            atom_position, category_idx = np.argwhere(missing_support)[0]
            raise RuntimeError(
                f"No school support for atom={atom_ids[atom_position]}, "
                f"category={CATEGORIES[category_idx]}, target={atom_category_targets[atom_position, category_idx]}"
            )
        atom_category_factor = np.divide(
            atom_category_targets,
            atom_category_current,
            out=np.zeros_like(atom_category_targets),
            where=atom_category_current > 0,
        )
        for stage in STAGES:
            atom_program_factor = np.take_along_axis(
                atom_category_factor, category_codes[stage], axis=1
            )
            matrices[stage] *= atom_program_factor[origin_atom_position]

        if iteration == 1 or iteration % 5 == 0 or iteration == max_iterations:
            row_error = 0.0
            row_absolute_error = 0.0
            row_absolute_error_sum = 0.0
            row_target_sum = 0.0
            for stage in STAGES:
                target = origins[f"target_{stage}"].to_numpy(dtype="float64")
                current = matrices[stage].sum(axis=1)
                absolute = np.abs(current - target)
                row_error = max(
                    row_error, float(np.max(absolute / np.maximum(target, 1.0)))
                )
                row_absolute_error = max(row_absolute_error, float(absolute.max()))
                row_absolute_error_sum += float(absolute.sum())
                row_target_sum += float(target.sum())
            sector_error = 0.0
            for stage in STAGES:
                stage_p = stage_programs[stage]
                for sector, cols_series in stage_p.groupby("sector").groups.items():
                    cols = np.asarray(list(cols_series), dtype=int)
                    target = float(group_targets[(stage, str(sector))])
                    current = float(matrices[stage][:, cols].sum())
                    sector_error = max(sector_error, abs(current - target) / max(target, 1.0))
            atom_category_current = np.zeros_like(atom_category_targets)
            for stage in STAGES:
                atom_program = np.asarray(atom_aggregator @ matrices[stage])
                codes = category_codes[stage]
                for category_idx in range(len(CATEGORIES)):
                    atom_category_current[:, category_idx] += np.where(
                        codes == category_idx, atom_program, 0.0
                    ).sum(axis=1)
            category_error = float(
                np.max(
                    np.abs(atom_category_current - atom_category_targets)
                    / np.maximum(atom_category_targets, 1.0)
                )
            )
            error_components = {
                "origin_stage": row_error,
                "origin_stage_wape": row_absolute_error_sum / row_target_sum,
                "origin_stage_max_abs_students": row_absolute_error,
                "stage_sector": sector_error,
                "atom_category": category_error,
            }
            max_error = max(row_error, sector_error, category_error)
            print(
                f"    iter={iteration} row_wape={error_components['origin_stage_wape']:.3e} "
                f"row_max_abs={row_absolute_error:.3e} sector={sector_error:.3e} "
                f"atom_category={category_error:.3e}"
            )
            if (
                error_components["origin_stage_wape"] <= tolerance
                and row_absolute_error <= max(0.01, tolerance)
                and sector_error <= tolerance
                and category_error <= tolerance
            ):
                converged = True
                break
    if not converged:
        raise RuntimeError(
            f"Assignment IPF did not converge for {scenario}: max relative error={max_error:.3e}, "
            f"components={error_components}"
        )

    distance_values: list[np.ndarray] = []
    flow_values: list[np.ndarray] = []
    school_caps = np.zeros(len(programs), dtype="float64")
    for stage in STAGES:
        matrix = matrices[stage]
        distance_values.append(distances[stage].ravel())
        flow_values.append(matrix.ravel())
        stage_p = stage_programs[stage]
        school_caps[stage_p["program_index"].to_numpy(dtype=int)] = matrix.sum(axis=0)
    all_distance = np.concatenate(distance_values)
    all_flow = np.concatenate(flow_values)
    positive = all_flow > 1e-12
    total = float(all_flow.sum())
    sorted_caps = np.sort(school_caps)
    gini = 0.0
    if sorted_caps.sum() > 0:
        n = len(sorted_caps)
        gini = float((2 * np.dot(np.arange(1, n + 1), sorted_caps) / (n * sorted_caps.sum())) - (n + 1) / n)
    metrics = {
        "scenario": scenario,
        "iterations": iteration,
        "max_relative_constraint_error": max_error,
        "constraint_error_components": error_components,
        "total_students": total,
        "mean_distance_m": float(np.average(all_distance[positive], weights=all_flow[positive])),
        "median_distance_m": weighted_quantile(all_distance[positive], all_flow[positive], 0.5),
        "p90_distance_m": weighted_quantile(all_distance[positive], all_flow[positive], 0.9),
        "school_program_capacity_gini": gini,
    }
    return matrices, metrics


def aggregate_assignment(
    matrices: dict[str, np.ndarray], origins: gpd.GeoDataFrame, programs: pd.DataFrame, grid: gpd.GeoDataFrame
) -> tuple[np.ndarray, np.ndarray, pd.DataFrame]:
    grid_id_to_idx = {int(grid_id): idx for idx, grid_id in enumerate(grid["grid_id"])}
    n_grid = len(grid)
    n_school = int(programs["school_index"].max()) + 1
    grid_school = np.zeros((n_grid, n_school), dtype="float64")
    program_caps: list[pd.DataFrame] = []
    for stage in STAGES:
        stage_p = programs[programs["student_stage"] == stage].copy().reset_index(drop=True)
        matrix = matrices[stage]
        row_grid = origins["grid_id"].map(grid_id_to_idx).to_numpy(dtype=int)
        school_idx = stage_p["school_index"].to_numpy(dtype=int)
        for row_idx, grid_idx in enumerate(row_grid):
            np.add.at(grid_school[grid_idx], school_idx, matrix[row_idx])
        caps = stage_p[["program_index", "school_index", "student_stage", "sector", "capacity_prior"]].copy()
        caps["estimated_students"] = matrix.sum(axis=0)
        program_caps.append(caps)
    grid_grid = np.zeros((n_grid, n_grid), dtype="float64")
    school_grid = programs.drop_duplicates("school_index").set_index("school_index")["grid_id"]
    for school_idx in range(n_school):
        grid_id = school_grid.get(school_idx)
        if pd.isna(grid_id):
            continue
        grid_grid[:, grid_id_to_idx[int(grid_id)]] += grid_school[:, school_idx]
    return grid_school, grid_grid, pd.concat(program_caps, ignore_index=True)


def modeled_atom_category(
    matrices: dict[str, np.ndarray], origins: gpd.GeoDataFrame, programs: pd.DataFrame
) -> pd.DataFrame:
    rows_out: list[dict[str, object]] = []
    for atom, row_indices in origins.groupby("atom_id").groups.items():
        idx = np.asarray(list(row_indices), dtype=int)
        origin_row = origins.iloc[int(idx[0])]
        record: dict[str, object] = {"atom_id": int(atom), "dcca": int(origin_row["dcca"])}
        for category in CATEGORIES:
            value = 0.0
            for stage in STAGES:
                stage_p = programs[programs["student_stage"] == stage].copy().reset_index(drop=True)
                cats = category_for_programs(origin_row, stage_p)
                cols = np.flatnonzero(cats == category)
                value += float(matrices[stage][np.ix_(idx, cols)].sum())
            record[f"modeled_{category}"] = value
        rows_out.append(record)
    return pd.DataFrame(rows_out)


def build_dcca_validation(
    dcca: gpd.GeoDataFrame,
    atom_targets: pd.DataFrame,
    modeled_atoms: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, float]]:
    raw_target_by_dcca = atom_targets.groupby("dcca")[[f"raw_target_{c}" for c in CATEGORIES]].sum()
    target_by_dcca = atom_targets.groupby("dcca")[[f"target_{c}" for c in CATEGORIES]].sum()
    modeled_by_dcca = modeled_atoms.groupby("dcca")[[f"modeled_{c}" for c in CATEGORIES]].sum()
    records: list[dict[str, object]] = []
    for row in dcca.itertuples():
        raw_total = float(row.flow_total_raw)
        retention = float(row.fixed_link_population_ratio)
        raw_target_total = (
            float(raw_target_by_dcca.loc[int(row.dcca)].sum()) if int(row.dcca) in raw_target_by_dcca.index else 0.0
        )
        target_total = float(target_by_dcca.loc[int(row.dcca)].sum()) if int(row.dcca) in target_by_dcca.index else 0.0
        for flow_column, category in FLOW_TO_CATEGORY.items():
            raw = float(getattr(row, flow_column))
            raw_share = raw / raw_total if raw_total > 0 else 0.0
            raw_target = (
                float(raw_target_by_dcca.loc[int(row.dcca), f"raw_target_{category}"])
                if int(row.dcca) in raw_target_by_dcca.index
                else 0.0
            )
            target = float(target_by_dcca.loc[int(row.dcca), f"target_{category}"]) if int(row.dcca) in target_by_dcca.index else 0.0
            modeled = float(modeled_by_dcca.loc[int(row.dcca), f"modeled_{category}"]) if int(row.dcca) in modeled_by_dcca.index else 0.0
            records.append(
                {
                    "dcca": int(row.dcca),
                    "dcca_eng": row.dcca_eng,
                    "dc": int(row.dc),
                    "dc_eng": row.dc_eng,
                    "category": category,
                    "raw_census_students": raw,
                    "fixed_link_adjusted_students": raw * retention,
                    "day_school_scaled_target": raw_target,
                    "reconciled_supported_target": target,
                    "support_reallocation_delta": target - raw_target,
                    "modeled_students": modeled,
                    "raw_share": raw_share,
                    "target_share": raw_target / raw_target_total if raw_target_total > 0 else 0.0,
                    "reconciled_target_share": target / target_total if target_total > 0 else 0.0,
                    "modeled_share": modeled / target_total if target_total > 0 else 0.0,
                    "fixed_link_population_ratio": retention,
                }
            )
    validation = pd.DataFrame(records)
    validation["absolute_error"] = (validation["modeled_students"] - validation["reconciled_supported_target"]).abs()
    validation["raw_target_absolute_difference"] = (
        validation["modeled_students"] - validation["day_school_scaled_target"]
    ).abs()
    validation["share_absolute_error"] = (
        validation["modeled_share"] - validation["reconciled_target_share"]
    ).abs()
    validation["raw_share_absolute_difference"] = (validation["modeled_share"] - validation["target_share"]).abs()
    denom = float(validation["reconciled_supported_target"].sum())
    raw_denom = float(validation["day_school_scaled_target"].sum())
    metrics = {
        "dcca_category_share_mae": float(validation["share_absolute_error"].mean()),
        "dcca_category_wape": float(validation["absolute_error"].sum() / denom) if denom > 0 else 0.0,
        "dcca_category_max_abs_error": float(validation["absolute_error"].max()),
        "dcca_raw_category_share_difference_mae": float(validation["raw_share_absolute_difference"].mean()),
        "dcca_raw_category_wape": (
            float(validation["raw_target_absolute_difference"].sum() / raw_denom) if raw_denom > 0 else 0.0
        ),
        "support_reallocated_students": float(validation["support_reallocation_delta"].clip(lower=0).sum()),
    }
    return validation, metrics


def tcs_block_matrix(
    matrices: dict[str, np.ndarray], origins: gpd.GeoDataFrame, programs: pd.DataFrame
) -> np.ndarray:
    block = np.zeros((26, 26), dtype="float64")
    oz = origins["tcs_zone"].to_numpy(dtype=int) - 1
    for stage in STAGES:
        stage_p = programs[programs["student_stage"] == stage].copy().reset_index(drop=True)
        dz = stage_p["tcs_zone"].to_numpy(dtype=int) - 1
        matrix = matrices[stage]
        for origin_zone in range(26):
            rows = np.flatnonzero(oz == origin_zone)
            if len(rows) == 0:
                continue
            for destination_zone in range(26):
                cols = np.flatnonzero(dz == destination_zone)
                if len(cols):
                    block[origin_zone, destination_zone] += float(matrix[np.ix_(rows, cols)].sum())
    return block


def build_mechanized_matrices(
    matrices: dict[str, np.ndarray],
    origins: gpd.GeoDataFrame,
    programs: pd.DataFrame,
    tcs: pd.DataFrame,
    grid: gpd.GeoDataFrame,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, float]]:
    assignment_total = sum(float(matrix.sum()) for matrix in matrices.values())
    mechanized_total = assignment_total * TCS_TRIPS / TCS_STUDENTS
    production = tcs.sort_values("district_id")["hbs_production_trips_balanced_to_official_total"].to_numpy(dtype="float64")
    attraction = tcs.sort_values("district_id")["hbs_attraction_trips_balanced_to_official_total"].to_numpy(dtype="float64")
    production *= mechanized_total / production.sum()
    attraction *= mechanized_total / attraction.sum()
    prior_block = tcs_block_matrix(matrices, origins, programs)
    block = ipf_2d(prior_block + 1e-12, production, attraction)
    factor = np.divide(block, prior_block, out=np.zeros_like(block), where=prior_block > 0)

    grid_id_to_idx = {int(grid_id): idx for idx, grid_id in enumerate(grid["grid_id"])}
    grid_grid = np.zeros((len(grid), len(grid)), dtype="float64")
    stage_grid: dict[str, np.ndarray] = {stage: np.zeros_like(grid_grid) for stage in STAGES}
    oz = origins["tcs_zone"].to_numpy(dtype=int) - 1
    row_grid = origins["grid_id"].map(grid_id_to_idx).to_numpy(dtype=int)
    for stage in STAGES:
        stage_p = programs[programs["student_stage"] == stage].copy().reset_index(drop=True)
        dz = stage_p["tcs_zone"].to_numpy(dtype=int) - 1
        school_grid = stage_p["grid_id"].map(grid_id_to_idx).to_numpy(dtype=int)
        mechanized = matrices[stage] * factor[oz[:, None], dz[None, :]]
        for row_idx, origin_grid in enumerate(row_grid):
            np.add.at(stage_grid[stage][origin_grid], school_grid, mechanized[row_idx])
        grid_grid += stage_grid[stage]
    qa = {
        "assignment_students": assignment_total,
        "mechanized_trip_rate_per_student": TCS_TRIPS / TCS_STUDENTS,
        "mechanized_trip_total": float(grid_grid.sum()),
        "production_max_abs_error": float(np.max(np.abs(block.sum(axis=1) - production))),
        "attraction_max_abs_error": float(np.max(np.abs(block.sum(axis=0) - attraction))),
    }
    return grid_grid, block, factor, qa


def allocate_modes(
    mechanized: np.ndarray,
    distance: np.ndarray,
    grid_tcs_zone: np.ndarray,
    mode_table: pd.DataFrame,
    max_iterations: int = 100,
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray], pd.DataFrame]:
    modes = mode_table[mode_table["mode"] != "Official total"].copy()
    mode_names = modes["mode"].tolist()
    reported = modes["hbs_boardings_reported"].astype(float).to_numpy()
    shares = reported / reported.sum()
    trip_targets = shares * mechanized.sum()
    boarding_targets = shares * mechanized.sum() * TCS_BOARDINGS / TCS_TRIPS
    positive = mechanized > 0
    flow = mechanized[positive].astype("float64")
    dist = distance[positive].astype("float64")
    row_index, col_index = np.nonzero(positive)
    oz = grid_tcs_zone[row_index]
    dz = grid_tcs_zone[col_index]
    scores = np.ones((len(mode_names), len(flow)), dtype="float64")
    for idx, mode in enumerate(mode_names):
        if mode == "MTR":
            scores[idx] = 0.5 + np.minimum(dist / 5000.0, 3.0)
        elif mode == "LRT":
            nwnt = np.isin(oz, [14, 15, 16, 23]) | np.isin(dz, [14, 15, 16, 23])
            scores[idx] = 0.08 + 2.5 * nwnt
        elif mode == "Tram":
            island = (oz <= 4) & (dz <= 4)
            scores[idx] = 0.03 + 3.0 * island
        elif mode == "Ferry":
            cross = ((oz <= 4) & (dz > 4)) | ((dz <= 4) & (oz > 4)) | (oz == 26) | (dz == 26)
            scores[idx] = 0.02 + 2.0 * cross
        elif mode == "PLB":
            scores[idx] = 0.6 + np.exp(-((dist - 5000.0) / 5000.0) ** 2)
        elif mode == "Franchised Bus":
            scores[idx] = 0.8 + np.minimum(dist / 8000.0, 2.0)
        elif mode == "Private Vehicle":
            scores[idx] = 0.35 + np.minimum(dist / 10000.0, 1.5)
        elif mode == "Taxi":
            scores[idx] = 0.3 + np.exp(-dist / 6000.0)
        elif mode == "SPB":
            scores[idx] = 0.8 + np.minimum(dist / 12000.0, 1.5)
    values = scores * flow[None, :]
    values *= np.divide(trip_targets, values.sum(axis=1), out=np.ones_like(trip_targets), where=values.sum(axis=1) > 0)[:, None]
    for _ in range(max_iterations):
        cell_sum = values.sum(axis=0)
        values *= np.divide(flow, cell_sum, out=np.zeros_like(flow), where=cell_sum > 0)[None, :]
        mode_sum = values.sum(axis=1)
        values *= np.divide(trip_targets, mode_sum, out=np.zeros_like(trip_targets), where=mode_sum > 0)[:, None]
    cell_sum = values.sum(axis=0)
    values *= np.divide(flow, cell_sum, out=np.zeros_like(flow), where=cell_sum > 0)[None, :]
    # A final global adjustment is tiny; preserve exact cell totals by assigning residual to the largest mode.
    residual = flow - values.sum(axis=0)
    values[np.argmax(values, axis=0), np.arange(len(flow))] += residual

    main: dict[str, np.ndarray] = {}
    boarding: dict[str, np.ndarray] = {}
    rows = []
    for idx, mode in enumerate(mode_names):
        key = slug(mode)
        matrix = np.zeros_like(mechanized, dtype="float32")
        matrix[positive] = values[idx].astype("float32")
        main[key] = matrix
        board = matrix.astype("float64") * (boarding_targets[idx] / max(float(matrix.sum()), 1e-12))
        boarding[key] = board.astype("float32")
        rows.append(
            {
                "mode": mode,
                "mode_key": key,
                "main_mode_trip_target": trip_targets[idx],
                "main_mode_trip_actual": float(matrix.sum()),
                "boarding_equivalent_target": boarding_targets[idx],
                "boarding_equivalent_actual": float(board.sum()),
            }
        )
    return main, boarding, pd.DataFrame(rows)


def dominant_grid_tcs_zone(origins: gpd.GeoDataFrame, grid: gpd.GeoDataFrame) -> np.ndarray:
    weights = origins.groupby(["grid_id", "tcs_zone"])["raw_school_age"].sum().reset_index()
    dominant = weights.loc[weights.groupby("grid_id")["raw_school_age"].idxmax()].set_index("grid_id")["tcs_zone"]
    return grid["grid_id"].map(dominant).fillna(26).to_numpy(dtype=int)


def write_long_assignment_parquet(
    path: Path,
    matrices: dict[str, np.ndarray],
    origins: gpd.GeoDataFrame,
    programs: pd.DataFrame,
    min_flow: float,
) -> dict[str, float]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("pyarrow is required for student_school_assignment_od.parquet") from exc
    writer = None
    rows_written = 0
    flow_written = 0.0
    flow_total = 0.0
    try:
        for stage in STAGES:
            stage_p = programs[programs["student_stage"] == stage].copy().reset_index(drop=True)
            matrix = matrices[stage]
            flow_total += float(matrix.sum())
            for start in range(0, len(origins), 32):
                stop = min(start + 32, len(origins))
                chunk = matrix[start:stop]
                rr, cc = np.nonzero(chunk >= min_flow)
                if len(rr) == 0:
                    continue
                origin_idx = rr + start
                values = chunk[rr, cc]
                frame = pd.DataFrame(
                    {
                        "origin_grid_id": origins.iloc[origin_idx]["grid_id"].to_numpy(dtype=int),
                        "origin_unit_id": origins.iloc[origin_idx]["origin_unit_id"].to_numpy(dtype=int),
                        "origin_dcca": origins.iloc[origin_idx]["dcca"].to_numpy(dtype=int),
                        "origin_study_area_id": origins.iloc[origin_idx]["study_area_id"].astype(str).to_numpy(),
                        "origin_tcs_zone": origins.iloc[origin_idx]["tcs_zone"].to_numpy(dtype=int),
                        "school_no": stage_p.iloc[cc]["SCHOOL NO."].astype(str).to_numpy(),
                        "campus_id": stage_p.iloc[cc]["campus_id"].astype(str).to_numpy(),
                        "destination_grid_id": stage_p.iloc[cc]["grid_id"].to_numpy(dtype=int),
                        "destination_study_area_id": stage_p.iloc[cc]["study_area_id"].astype(str).to_numpy(),
                        "destination_tcs_zone": stage_p.iloc[cc]["tcs_zone"].to_numpy(dtype=int),
                        "student_stage": stage,
                        "students_expected": values.astype("float32"),
                    }
                )
                table = pa.Table.from_pandas(frame, preserve_index=False)
                if writer is None:
                    writer = pq.ParquetWriter(path, table.schema, compression="zstd")
                writer.write_table(table)
                rows_written += len(frame)
                flow_written += float(values.sum())
    finally:
        if writer is not None:
            writer.close()
    return {
        "parquet_rows": rows_written,
        "parquet_flow_written": flow_written,
        "parquet_flow_total": flow_total,
        "parquet_omitted_flow": flow_total - flow_written,
        "parquet_min_flow": min_flow,
    }


def plot_outputs(
    out_dir: Path,
    study_areas: gpd.GeoDataFrame,
    grid: gpd.GeoDataFrame,
    origin_table: pd.DataFrame,
    schools_capacity: gpd.GeoDataFrame,
    dcca_validation: pd.DataFrame,
    block: np.ndarray,
    mode_qa: pd.DataFrame,
) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(20, 7))
    study_areas.boundary.plot(ax=axes[0], color="#555555", linewidth=0.35)
    schools_capacity.plot(
        ax=axes[0],
        markersize=np.clip(schools_capacity["estimated_students"].to_numpy() / 40.0, 1.0, 30.0),
        color="#d1495b",
        alpha=0.55,
    )
    axes[0].set_title("Estimated school capacity")
    axes[0].axis("off")

    grid_plot = grid.merge(origin_table.groupby("grid_id")["students"].sum(), on="grid_id", how="left")
    grid_plot["students"] = grid_plot["students"].fillna(0.0)
    grid_plot.plot(column="students", ax=axes[1], cmap="viridis", legend=True, linewidth=0)
    axes[1].set_title("Student origins by fixed-link grid")
    axes[1].axis("off")

    im = axes[2].imshow(np.log1p(block), cmap="magma")
    axes[2].set_title("TCS-constrained 26x26 HBS OD, log1p")
    axes[2].set_xlabel("Destination district")
    axes[2].set_ylabel("Origin district")
    fig.colorbar(im, ax=axes[2], fraction=0.046)
    fig.tight_layout()
    fig.savefig(out_dir / "student_school_od_overview.png", dpi=220, bbox_inches="tight")
    plt.close(fig)

    dcca_metrics = dcca_validation.groupby("dcca").agg(
        share_mae=("raw_share_absolute_difference", "mean"),
        cell_wape=("raw_target_absolute_difference", lambda x: float(x.sum())),
    )
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    axes[0].hist(dcca_metrics["share_mae"], bins=30, color="#2a9d8f")
    axes[0].set_title("Modeled vs unreconciled DCCA x 5 shares")
    axes[0].set_xlabel("Mean absolute share error")
    axes[0].set_ylabel("DCCA count")
    axes[1].bar(mode_qa["mode"], mode_qa["main_mode_trip_actual"], color="#457b9d")
    axes[1].tick_params(axis="x", rotation=50)
    axes[1].set_title("Mechanized HBS main-mode equivalents")
    axes[1].set_ylabel("Daily trips")
    fig.tight_layout()
    fig.savefig(out_dir / "dcca_and_mode_validation.png", dpi=220, bbox_inches="tight")
    plt.close(fig)

    dc18 = dcca_validation.groupby(["dc", "dc_eng", "category"], as_index=False)[
        ["day_school_scaled_target", "modeled_students"]
    ].sum()
    dc18["target_share"] = dc18["day_school_scaled_target"] / dc18.groupby("dc")[
        "day_school_scaled_target"
    ].transform("sum")
    dc18["modeled_share"] = dc18["modeled_students"] / dc18.groupby("dc")[
        "modeled_students"
    ].transform("sum")
    dc18["share_difference"] = dc18["modeled_share"] - dc18["target_share"]
    share_difference = dc18.pivot(index="dc_eng", columns="category", values="share_difference").reindex(
        columns=CATEGORIES
    )
    district_error = dc18.assign(
        absolute_error=(dc18["modeled_students"] - dc18["day_school_scaled_target"]).abs()
    ).groupby("dc_eng")[["absolute_error", "day_school_scaled_target"]].sum()
    district_wape = district_error["absolute_error"] / district_error["day_school_scaled_target"].clip(lower=1.0)
    fig, axes = plt.subplots(1, 2, figsize=(16, 7))
    max_abs = max(float(np.abs(share_difference.to_numpy()).max()), 1e-4)
    image = axes[0].imshow(share_difference.to_numpy(), cmap="RdBu_r", vmin=-max_abs, vmax=max_abs)
    axes[0].set_xticks(range(len(CATEGORIES)), CATEGORIES, rotation=35, ha="right")
    axes[0].set_yticks(range(len(share_difference.index)), share_difference.index)
    axes[0].set_title("18-district modeled minus unreconciled share")
    fig.colorbar(image, ax=axes[0], fraction=0.046)
    district_wape.sort_values().plot.barh(ax=axes[1], color="#457b9d")
    axes[1].set_title("18-district WAPE vs unreconciled target")
    axes[1].set_xlabel("WAPE")
    axes[1].set_ylabel("")
    fig.tight_layout()
    fig.savefig(out_dir / "dc18_study_flow_validation.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    args = parse_args()
    paths = data_paths(args.data_root.resolve())
    require_paths(paths)
    out_dir = args.out_dir or (args.data_root / "school/hongkong/processed/student_school_od_2022")
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "direction_time_od").mkdir(exist_ok=True)
    (out_dir / "mode_od/main_mode_equivalent").mkdir(parents=True, exist_ok=True)
    (out_dir / "mode_od/boarding_equivalent").mkdir(parents=True, exist_ok=True)

    print("[1/10] Reading and validating DCCA Census inputs...")
    dcca = read_dcca(paths)
    check_dcca_dc_aggregation(dcca, paths["dc_shp"])
    study_areas, boundary = build_study_areas(paths["dc_shp"], paths["newtown"], paths["boundary"])
    dcca["fixed_link_population_ratio"] = worldpop_retention_by_dcca(dcca, boundary, paths["raw_worldpop"])
    dcca["fixed_link_status"] = np.select(
        [
            dcca["fixed_link_population_ratio"] <= 1e-8,
            dcca["fixed_link_population_ratio"] < 1.0 - 1e-8,
        ],
        ["excluded", "partial"],
        default="full",
    )
    dcca[
        [
            "dcca",
            "dcca_eng",
            "dc",
            "dc_eng",
            "flow_total_raw",
            "fixed_link_population_ratio",
            "fixed_link_status",
        ]
    ].to_csv(out_dir / "dcca_fixed_link_retention.csv", index=False, encoding="utf-8-sig")
    study_areas.to_crs("EPSG:4326").to_file(out_dir / "census_study_areas.geojson", driver="GeoJSON")

    print("[2/10] Building population-weighted grid/DCCA/study-area crosswalk...")
    grid, grid_stage_mass = read_grid_stage_mass(paths)
    crosswalk_path = out_dir / "dcca_study_area_crosswalk.parquet"
    origins = None
    if crosswalk_path.exists():
        try:
            cached = gpd.read_parquet(crosswalk_path)
            if "geometry" in cached and len(cached) > 0:
                origins = cached.to_crs(WORK_CRS)
                print(f"  - Reusing cached crosswalk: {crosswalk_path}")
        except (ValueError, TypeError):
            origins = None
    if origins is None:
        origins = build_origin_crosswalk(dcca, study_areas, grid, grid_stage_mass)
        origins = add_tcs_zones_to_origins(origins)
        origins.to_parquet(crosswalk_path, index=False)

    print("[3/10] Preparing EDB schools and 2022 enrollment constraints...")
    annual_targets = parse_annual_targets(paths["annual"])
    schools_all, programs, target_table = read_schools_and_programs(
        paths, boundary, study_areas, dcca, grid, annual_targets
    )
    excluded = schools_all[~schools_all["inside_fixed_link"]].copy()
    excluded.drop(columns="geometry").to_csv(out_dir / "schools_excluded_fixed_link.csv", index=False, encoding="utf-8-sig")
    target_table.to_csv(out_dir / "edb_2022_stage_sector_targets.csv", index=False, encoding="utf-8-sig")

    print("[4/10] Raking student origins to EDB stage totals and TCS resident-student districts...")
    origins, atom_targets, tcs, support_audit = build_origin_targets(
        origins, dcca, target_table, paths["tcs_district"], programs
    )
    support_audit.to_csv(
        out_dir / "dcca_flow_support_reconciliation.csv", index=False, encoding="utf-8-sig"
    )
    origin_long = origins[["grid_id", "origin_unit_id", "atom_id", "dcca", "study_area_id", "tcs_zone"]].copy()
    origin_long = origin_long.loc[origin_long.index.repeat(len(STAGES))].reset_index(drop=True)
    origin_long["student_stage"] = STAGES * len(origins)
    origin_long["students"] = np.concatenate(
        [origins[[f"target_{stage}" for stage in STAGES]].to_numpy()[row] for row in range(len(origins))]
    )
    origin_long.to_csv(out_dir / "student_origin_grid_stage.csv", index=False, encoding="utf-8-sig")

    print("[5/10] Fitting short/base/long constrained student-school assignments...")
    scenario_metrics = []
    scenario_dcca_records: list[pd.DataFrame] = []
    scenario_school_records: list[pd.DataFrame] = []
    base_matrices: dict[str, np.ndarray] | None = None
    for scenario in ["short", "base", "long"]:
        print(f"  - {scenario}")
        matrices, metrics = fit_assignment(
            origins, atom_targets, programs, target_table, scenario, args.max_iterations, args.tolerance
        )
        scenario_metrics.append(metrics)
        scenario_atoms = modeled_atom_category(matrices, origins, programs)
        scenario_dcca = scenario_atoms.groupby("dcca")[[f"modeled_{category}" for category in CATEGORIES]].sum()
        scenario_dcca.columns = [column.removeprefix("modeled_") for column in scenario_dcca.columns]
        scenario_dcca = scenario_dcca.reset_index().melt(
            id_vars="dcca", var_name="category", value_name="modeled_students"
        )
        scenario_dcca["scenario"] = scenario
        scenario_dcca_records.append(scenario_dcca)
        scenario_caps: list[pd.DataFrame] = []
        for stage in STAGES:
            stage_programs = programs[programs["student_stage"] == stage].copy().reset_index(drop=True)
            caps = stage_programs[["program_index", "school_index", "campus_id", "student_stage", "sector"]].copy()
            caps["estimated_students"] = matrices[stage].sum(axis=0)
            scenario_caps.append(caps)
        scenario_school = pd.concat(scenario_caps, ignore_index=True)
        scenario_school["scenario"] = scenario
        scenario_school_records.append(scenario_school)
        if scenario == "base":
            base_matrices = matrices
    assert base_matrices is not None
    pd.DataFrame(scenario_metrics).to_csv(out_dir / "distance_scenario_comparison.csv", index=False, encoding="utf-8-sig")
    pd.concat(scenario_dcca_records, ignore_index=True).to_csv(
        out_dir / "distance_scenario_dcca_categories.csv", index=False, encoding="utf-8-sig"
    )
    pd.concat(scenario_school_records, ignore_index=True).to_csv(
        out_dir / "distance_scenario_school_capacity.csv", index=False, encoding="utf-8-sig"
    )

    print("[6/10] Aggregating the base assignment and writing school capacity estimates...")
    grid_school, assignment_grid, program_caps = aggregate_assignment(base_matrices, origins, programs, grid)
    np.save(out_dir / "student_school_assignment_grid_od.npy", assignment_grid.astype("float32"))
    save_npz(out_dir / "student_school_assignment_grid_school.npz", csr_matrix(grid_school.astype("float32")))
    program_caps.to_csv(out_dir / "school_program_capacity_estimates.csv", index=False, encoding="utf-8-sig")
    school_cap = program_caps.groupby("school_index")["estimated_students"].sum()
    retained_schools = schools_all[schools_all["inside_fixed_link"]].copy()
    retained_schools["estimated_students"] = retained_schools["school_index"].map(school_cap).fillna(0.0)
    school_fields = [
        "school_index",
        "SCHOOL NO.",
        "campus_id",
        "ENGLISH NAME",
        "中文名稱",
        "base_stage",
        "base_sector",
        "SESSION",
        "DISTRICT",
        "study_area_id",
        "tcs_zone",
        "grid_id",
        "estimated_students",
        "geometry",
    ]
    school_output = retained_schools[school_fields]
    school_output.drop(columns="geometry").to_csv(out_dir / "schools_2022_capacity_estimates.csv", index=False, encoding="utf-8-sig")
    school_output.to_crs("EPSG:4326").to_file(out_dir / "schools_2022_capacity_estimates.geojson", driver="GeoJSON")
    campus_output = (
        school_output.sort_values("school_index")
        .groupby("campus_id", as_index=False)
        .agg(
            estimated_students=("estimated_students", "sum"),
            school_project_count=("school_index", "count"),
            grid_id=("grid_id", "first"),
            study_area_id=("study_area_id", "first"),
            tcs_zone=("tcs_zone", "first"),
            geometry=("geometry", "first"),
        )
    )
    campus_output = gpd.GeoDataFrame(campus_output, geometry="geometry", crs=WORK_CRS)
    campus_output.drop(columns="geometry").to_csv(
        out_dir / "school_campus_capacity_estimates.csv", index=False, encoding="utf-8-sig"
    )
    campus_output.to_crs("EPSG:4326").to_file(
        out_dir / "school_campus_capacity_estimates.geojson", driver="GeoJSON"
    )

    parquet_qa: dict[str, float] = {}
    if not args.skip_long_parquet:
        parquet_qa = write_long_assignment_parquet(
            out_dir / "student_school_assignment_od.parquet",
            base_matrices,
            origins,
            programs,
            args.parquet_min_flow,
        )

    print("[7/10] Validating DCCA x 5 constraints...")
    modeled_atoms = modeled_atom_category(base_matrices, origins, programs)
    dcca_validation, dcca_metrics = build_dcca_validation(dcca, atom_targets, modeled_atoms)
    dcca_validation.to_csv(out_dir / "dcca_study_flow_constraints.csv", index=False, encoding="utf-8-sig")
    dc18_validation = (
        dcca_validation.groupby(["dc", "dc_eng", "category"], as_index=False)[
            [
                "raw_census_students",
                "fixed_link_adjusted_students",
                "day_school_scaled_target",
                "reconciled_supported_target",
                "modeled_students",
            ]
        ]
        .sum()
        .sort_values(["dc", "category"])
    )
    for prefix in ["day_school_scaled_target", "reconciled_supported_target", "modeled_students"]:
        total = dc18_validation.groupby("dc")[prefix].transform("sum")
        dc18_validation[f"{prefix}_share"] = np.divide(
            dc18_validation[prefix],
            total,
            out=np.zeros(len(dc18_validation), dtype="float64"),
            where=total.to_numpy() > 0,
        )
    dc18_validation["modeled_vs_reconciled_absolute_error"] = (
        dc18_validation["modeled_students"] - dc18_validation["reconciled_supported_target"]
    ).abs()
    dc18_validation.to_csv(out_dir / "dc18_study_flow_validation.csv", index=False, encoding="utf-8-sig")

    print("[8/10] Applying TCS 26-district mechanized HBS constraints...")
    mechanized, tcs_block, block_factor, mech_qa = build_mechanized_matrices(
        base_matrices, origins, programs, tcs, grid
    )
    np.save(out_dir / "hbs_mechanized_home_school_grid_od.npy", mechanized.astype("float32"))
    pd.DataFrame(tcs_block, index=TCS_DISTRICT_NAMES.values(), columns=TCS_DISTRICT_NAMES.values()).to_csv(
        out_dir / "tcs26_mechanized_home_school_od.csv", encoding="utf-8-sig"
    )
    pd.DataFrame(block_factor, index=TCS_DISTRICT_NAMES.values(), columns=TCS_DISTRICT_NAMES.values()).to_csv(
        out_dir / "tcs26_block_scaling_factors.csv", encoding="utf-8-sig"
    )
    tcs_sorted = tcs.sort_values("district_id").reset_index(drop=True)
    production_reference = tcs_sorted["hbs_production_trips_balanced_to_official_total"].to_numpy(
        dtype="float64"
    )
    attraction_reference = tcs_sorted["hbs_attraction_trips_balanced_to_official_total"].to_numpy(
        dtype="float64"
    )
    production_target = production_reference * tcs_block.sum() / production_reference.sum()
    attraction_target = attraction_reference * tcs_block.sum() / attraction_reference.sum()
    tcs_validation = pd.DataFrame(
        {
            "district_id": tcs_sorted["district_id"],
            "district_name": tcs_sorted["district_id"].map(TCS_DISTRICT_NAMES),
            "production_official_reference": production_reference,
            "production_target_retained_total": production_target,
            "production_modeled": tcs_block.sum(axis=1),
            "attraction_official_reference": attraction_reference,
            "attraction_target_retained_total": attraction_target,
            "attraction_modeled": tcs_block.sum(axis=0),
        }
    )
    tcs_validation["production_absolute_error"] = (
        tcs_validation["production_modeled"] - tcs_validation["production_target_retained_total"]
    ).abs()
    tcs_validation["attraction_absolute_error"] = (
        tcs_validation["attraction_modeled"] - tcs_validation["attraction_target_retained_total"]
    ).abs()
    tcs_validation.to_csv(out_dir / "tcs26_marginal_validation.csv", index=False, encoding="utf-8-sig")

    direction_dir = out_dir / "direction_time_od"
    home_school = 0.5 * mechanized
    school_home = (0.5 * mechanized).T
    direction_matrices = {
        "home_to_school.npy": home_school,
        "school_to_home.npy": school_home,
        "home_to_school_0700_0800.npy": 0.64 * home_school,
        "home_to_school_other_time.npy": 0.36 * home_school,
        "school_to_home_1300_1400.npy": 0.22 * school_home,
        "school_to_home_1600_1700.npy": 0.23 * school_home,
        "school_to_home_other_time.npy": 0.55 * school_home,
    }
    for filename, matrix in direction_matrices.items():
        np.save(direction_dir / filename, matrix.astype("float32"))

    print("[9/10] Allocating main-mode and boarding-equivalent matrices...")
    distance = np.load(paths["distance"]).astype("float64")
    grid_tcs_zone = dominant_grid_tcs_zone(origins, grid)
    mode_table = pd.read_csv(paths["tcs_mode"])
    main_modes, boarding_modes, mode_qa = allocate_modes(mechanized, distance, grid_tcs_zone, mode_table)
    for key, matrix in main_modes.items():
        np.save(out_dir / "mode_od/main_mode_equivalent" / f"{key}.npy", matrix)
    for key, matrix in boarding_modes.items():
        np.save(out_dir / "mode_od/boarding_equivalent" / f"{key}.npy", matrix)
    mode_qa.to_csv(out_dir / "mode_od/mode_generation_qa.csv", index=False, encoding="utf-8-sig")

    print("[10/10] Writing QA plots and summary...")
    plot_outputs(out_dir, study_areas, grid, origin_long, school_output, dcca_validation, tcs_block, mode_qa)
    main_sum = sum(matrix.astype("float64") for matrix in main_modes.values())
    dc18_error_summary = dc18_validation.assign(
        absolute_error=(
            dc18_validation["modeled_students"] - dc18_validation["day_school_scaled_target"]
        ).abs()
    ).groupby("dc")[["absolute_error", "day_school_scaled_target"]].sum()
    dc18_wape = (
        dc18_error_summary["absolute_error"]
        / dc18_error_summary["day_school_scaled_target"].clip(lower=1.0)
    )
    summary = {
        "model_year": 2022,
        "output_dir": str(out_dir),
        "dcca_count": int(len(dcca)),
        "dcca_census_flow_total": float(dcca[FLOW_COLUMNS].sum().sum()),
        "dcca_fixed_link_status_counts": {
            str(key): int(value) for key, value in dcca["fixed_link_status"].value_counts().items()
        },
        "census_study_area_count": int(len(study_areas)),
        "grid_count": int(len(grid)),
        "school_records_full": int(len(schools_all)),
        "school_records_retained": int(schools_all["inside_fixed_link"].sum()),
        "school_records_excluded": int((~schools_all["inside_fixed_link"]).sum()),
        "school_programs_retained": int(len(programs)),
        "retained_day_school_students": float(target_table["retained_target"].sum()),
        "support_reconciliation_event_count": int(len(support_audit)),
        "support_reconciliation_students": (
            float(support_audit["students_reallocated"].sum()) if len(support_audit) else 0.0
        ),
        "assignment_shape": list(assignment_grid.shape),
        "assignment_total_students": float(assignment_grid.sum()),
        "mechanized_shape": list(mechanized.shape),
        **mech_qa,
        **dcca_metrics,
        **parquet_qa,
        "main_mode_cell_sum_max_abs_error": float(np.max(np.abs(main_sum - mechanized))),
        "dc18_unreconciled_target_wape_mean": float(dc18_wape.mean()),
        "tcs26_production_max_abs_error": float(tcs_validation["production_absolute_error"].max()),
        "tcs26_attraction_max_abs_error": float(tcs_validation["attraction_absolute_error"].max()),
        "scenario_metrics": scenario_metrics,
        "units": {
            "student_school_assignment": "expected students",
            "mechanized_hbs": "weekday mechanized trips",
            "main_mode_equivalent": "approximate trips",
            "boarding_equivalent": "boardings, may exceed trips",
        },
        "limitations": [
            "DCCA x 5 flows include all full-time students and are used as a spatial structure proxy for EDB day-school students.",
            "Structurally unsupported DCCA atom/category targets are reallocated to the nearest category with a retained compatible school and fully audited.",
            "Individual-school enrollment is estimated, not an official school capacity count.",
            "Walk-only and cycling HBS totals are not inferred from purpose shares.",
            "TCS Yau Ma Tei/Mong Kok is mapped from DCCA geography because no machine-readable TCS polygon is published.",
        ],
    }
    (out_dir / "student_school_od_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    validation_summary = {
        key: value
        for key, value in summary.items()
        if key.startswith(("dcca_", "dc18_", "tcs26_", "support_", "main_mode_"))
    }
    (out_dir / "student_school_od_validation_summary.json").write_text(
        json.dumps(validation_summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps({k: summary[k] for k in ["assignment_total_students", "mechanized_trip_total", "dcca_category_wape"]}, indent=2))
    print(f"Wrote: {out_dir}")


if __name__ == "__main__":
    main()
