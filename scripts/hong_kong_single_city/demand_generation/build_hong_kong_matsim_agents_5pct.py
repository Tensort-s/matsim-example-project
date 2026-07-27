#!/usr/bin/env python3
"""Build a reproducible 5% Hong Kong typical-weekday MATSim population.

The formal population is deliberately anchor based: observed/calibrated work,
school, and border demand is represented, while unsupported discretionary
resident tours are not invented. The script writes unrouted MATSim plans plus
facilities, private vehicles, manifests, configuration, and validation tables.
"""

from __future__ import annotations

import argparse
import hashlib
import gzip
import itertools
import json
import math
import shutil
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from xml.sax.saxutils import escape, quoteattr

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import rasterio
from pyproj import Transformer
from scipy import sparse
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree
from shapely.geometry import Point


ROOT = Path(__file__).resolve().parents[3]
WINDOWS_DATA_ROOT = Path(r"F:\Matsim\matsim-example-project\data")
DEFAULT_DATA_ROOT = WINDOWS_DATA_ROOT if WINDOWS_DATA_ROOT.exists() else ROOT / "data"
DEFAULT_OUTPUT = DEFAULT_DATA_ROOT / "matsim_agents/hongkong/typical_weekday_5pct_v1"
SAMPLE_RATE = 0.05
SEED = 20260722
TARGET_FIXED_LINK_POPULATION = 7_352_309
TARGET_RESIDENT_AGENTS = 367_615
TARGET_HOUSEHOLD_AGENTS = 363_275
TARGET_COLLECTIVE_AGENTS = TARGET_RESIDENT_AGENTS - TARGET_HOUSEHOLD_AGENTS

WORK_CATEGORIES = {
    "office", "finance", "government", "service", "health", "education",
    "retail", "shop", "industrial", "accommodation",
}
EDUCATION_CATEGORIES = {"education", "kindergarten", "dormitory"}
PT_WORK_MODES = {
    "mtr_local", "bus", "public_light_bus", "company_bus_van",
    "residential_coach", "mtr_lrt", "ferry_vessel", "tram",
}


@dataclass(frozen=True)
class Facility:
    facility_id: str
    activity_type: str
    x: float
    y: float
    link_id: str = ""
    source: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--work-od", type=Path)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--resident-target", type=int, default=TARGET_RESIDENT_AGENTS)
    parser.add_argument("--household-person-target", type=int, default=TARGET_HOUSEHOLD_AGENTS)
    parser.add_argument("--skip-raster-home-points", action="store_true")
    parser.add_argument("--sample-only", action="store_true", help="Build a 0.1% smoke sample instead of formal 5% output")
    return parser.parse_args()


def paths(data_root: Path, work_od: Path | None) -> dict[str, Path]:
    city = data_root / "worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid"
    school = data_root / "school/hongkong/processed/student_school_od_2022"
    household = data_root / "matsim_agents/hongkong/synthetic_households_tcs2022"
    tourism = data_root / "tourism/hongkong/processed/arrival_departure_od_2026_typical_weekday_pt_access_v2"
    transit = data_root / "transit/hongkong/processed/matsim_road_pt_supply_2026_typical_weekday"
    census = data_root / "boundary/hongkong/2021_Population_Census_Statistics_and_Boundar_SHP"
    default_work = (
        ROOT / "data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid"
        / "CommutingODFlows/hong_kong_fixed_link_grid/hk_scaler_calibration_v1/final"
        / "generation_hk_census_projected.npy"
    )
    if not default_work.exists():
        default_work = city / "census_2021_commute_constraints/generation_2021_census_global_unit_scaled.npy"
    return {
        "households": household / "synthetic_households.parquet",
        "persons": household / "synthetic_persons.parquet",
        "household_vehicles": household / "synthetic_household_vehicles.parquet",
        "grid_households": household / "grid_household_population_summary.csv",
        "grid": city / "CityAndRegionSplit/hong_kong_fixed_link_grid/regions.shp",
        "worldpop": city / "GeneratingCodeData/data/global_cities/hong_kong_fixed_link_grid/nfeat/worldpop.npy",
        "demos": city / "GeneratingCodeData/data/global_cities/hong_kong_fixed_link_grid/nfeat/demos.npy",
        "distance": city / "GeneratingCodeData/data/global_cities/hong_kong_fixed_link_grid/adj/dis.npy",
        "work_od": work_od or default_work,
        "commute_modes": city / "census_2021_commute_constraints/table_7_9_commute_mode_by_residence.csv",
        "student_origins": school / "student_origin_grid_stage.csv",
        "student_grid_school": school / "student_school_assignment_grid_school.npz",
        "schools": school / "schools_2022_capacity_estimates.geojson",
        "study_flows": school / "dcca_study_flow_constraints.csv",
        "retention": school / "dcca_fixed_link_retention.csv",
        "school_mode_dir": school / "mode_od/main_mode_equivalent",
        "dcca_xlsx": census / "DCCA_21C.xlsx",
        "dc_boundaries": census / "DC_21C_converted.shp",
        "population_raster": data_root / (
            "gee/hongkong/worldpop_age_sex/census_calibrated/"
            "worldpop_HKG_2021_census_lsug_calibrated_fixed_link_boundary.tif"
        ),
        "pois": data_root / "osm/hongkong/fixed_link_boundary/integrated_pois/hong_kong_fixed_link_integrated_pois.csv",
        "tourism": tourism,
        "network": transit / "network.xml.gz",
        "schedule": transit / "transitSchedule.xml.gz",
        "transit_vehicles": transit / "transitVehicles.xml.gz",
    }


def require_inputs(inputs: dict[str, Path]) -> None:
    missing = [f"{name}: {path}" for name, path in inputs.items() if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))


def largest_remainder(values: np.ndarray, total: int) -> np.ndarray:
    values = np.nan_to_num(np.asarray(values, dtype="float64"), nan=0.0, posinf=0.0, neginf=0.0)
    values = np.maximum(values, 0.0)
    if total <= 0:
        return np.zeros(len(values), dtype="int64")
    if values.sum() <= 0:
        values = np.ones(len(values), dtype="float64")
    quota = values / values.sum() * int(total)
    result = np.floor(quota).astype("int64")
    remainder = int(total - result.sum())
    if remainder:
        order = np.lexsort((np.arange(len(values)), -(quota - result)))
        result[order[:remainder]] += 1
    return result


def weighted_choices(rng: np.random.Generator, values: np.ndarray, weights: np.ndarray, size: int) -> np.ndarray:
    if size <= 0:
        return np.empty(0, dtype=values.dtype)
    weights = np.nan_to_num(np.asarray(weights, dtype="float64"), nan=0.0, posinf=0.0, neginf=0.0)
    weights = np.maximum(weights, 0.0)
    probability = None if weights.sum() <= 0 else weights / weights.sum()
    return rng.choice(values, size=size, replace=True, p=probability)


def read_census_dcca(path: Path) -> pd.DataFrame:
    frame = pd.read_excel(path, sheet_name="DCCA", header=4)
    frame.columns = [str(value).strip().lower() for value in frame.columns]
    if "dcca" not in frame.columns:
        raise ValueError("DCCA workbook does not contain dcca")
    frame = frame.loc[pd.to_numeric(frame["dcca"], errors="coerce").notna()].copy()
    needed = [
        "dcca", "dc", "dc_eng", "t_pop", "pop_non", "nwp_st", "nwp_re", "nwp_hm",
        "nwp_care", "nwp_oth", "plw_hm", "plw_nofix", "plw_out", "plw_same",
        "plw_diff_h", "plw_diff_k", "plw_diff_n", "plw_diff_o",
    ]
    for column in needed:
        if column not in frame.columns:
            frame[column] = 0
        text = frame[column].astype(str).str.strip()
        if text.str.contains(r"\*\*", regex=True).any():
            raise ValueError(f"Suppressed high-error Census values found in {column}")
        if column not in {"dc_eng"}:
            frame[column] = pd.to_numeric(frame[column].where(text.ne("-"), 0), errors="coerce").fillna(0)
    return frame[needed].copy()


def sample_households(
    frame: pd.DataFrame,
    target_people: int,
    sample_rate: float,
    rng: np.random.Generator,
) -> pd.DataFrame:
    frame = frame.copy()
    stratum = ["dcca", "household_size", "private_vehicle_count_category", "income_band_tcs", "housing_type"]
    priority = rng.random(len(frame))
    frame["_priority"] = priority
    frame["_selected"] = False
    codes, unique_strata = pd.factorize(pd.MultiIndex.from_frame(frame[stratum]), sort=False)
    group_sizes = np.bincount(codes, minlength=len(unique_strata))
    desired_households = largest_remainder(
        group_sizes * sample_rate,
        round(len(frame) * sample_rate),
    )
    order = np.lexsort((priority, codes))
    sorted_codes = codes[order]
    group_starts = np.zeros(len(unique_strata), dtype="int64")
    group_starts[1:] = np.cumsum(group_sizes[:-1])
    rank_in_group = np.arange(len(frame), dtype="int64") - group_starts[sorted_codes]
    selected_positions = order[rank_in_group < desired_households[sorted_codes]]
    frame.loc[frame.index[selected_positions], "_selected"] = True

    selected = frame._selected.to_numpy(dtype=bool)
    sizes = frame.household_size.to_numpy(dtype="int64")
    current = int(sizes[selected].sum())
    difference = target_people - current
    add_pools = {
        size: list(indices[np.argsort(priority[indices])])
        for size in np.unique(sizes)
        if len(indices := np.flatnonzero((sizes == size) & ~selected))
    }
    remove_pools = {
        size: list(indices[np.argsort(-priority[indices])])
        for size in np.unique(sizes)
        if len(indices := np.flatnonzero((sizes == size) & selected))
    }
    for _ in range(max(100, abs(difference) + 10)):
        if difference == 0:
            break
        if difference > 0:
            possible = [size for size, pool in add_pools.items() if pool and size <= difference]
            if not possible:
                possible = [size for size, pool in add_pools.items() if pool]
            if not possible:
                break
            size = min(possible, key=lambda value: (abs(value - difference), value))
            position = add_pools[size].pop(0)
            selected[position] = True
            difference -= int(size)
        else:
            excess = -difference
            possible = [size for size, pool in remove_pools.items() if pool and size <= excess]
            if not possible:
                possible = [size for size, pool in remove_pools.items() if pool]
            if not possible:
                break
            size = min(possible, key=lambda value: (abs(value - excess), value))
            position = remove_pools[size].pop(0)
            selected[position] = False
            difference += int(size)
    frame["_selected"] = selected
    selected_frame = frame.loc[frame._selected].drop(columns=["_priority", "_selected"]).copy()
    actual = int(selected_frame.household_size.sum())
    if actual != target_people:
        raise RuntimeError(f"Whole-household sampler produced {actual:,}, expected {target_people:,}")
    return selected_frame.sort_values("household_index").reset_index(drop=True)


def read_selected_persons(path: Path, selected_households: np.ndarray) -> pd.DataFrame:
    metadata = pq.ParquetFile(path)
    maximum = int(max(selected_households.max(), metadata.metadata.num_rows))
    selected_mask = np.zeros(maximum + 1, dtype=bool)
    selected_mask[selected_households.astype("int64")] = True
    columns = [
        "person_id", "person_index", "household_id", "household_index", "member_sequence",
        "relationship_role", "age", "age_band_census", "sex", "dcca", "grid_id", "tcs_zone",
        "household_private_vehicle_count", "potential_household_vehicle_access",
        "is_designated_driver", "assigned_vehicle_count",
    ]
    chunks: list[pd.DataFrame] = []
    for batch in metadata.iter_batches(batch_size=250_000, columns=columns):
        batch_frame = batch.to_pandas()
        indices = batch_frame.household_index.to_numpy(dtype="int64")
        keep = selected_mask[indices]
        if keep.any():
            chunks.append(batch_frame.loc[keep])
    return pd.concat(chunks, ignore_index=True).sort_values("person_index").reset_index(drop=True)


def build_collective_people(
    count: int,
    worldpop: np.ndarray,
    demos: np.ndarray,
    grid_households: pd.DataFrame,
    grid_dcca: dict[int, int],
    grid_tcs: dict[int, int],
    rng: np.random.Generator,
) -> pd.DataFrame:
    household_population = np.zeros(len(worldpop), dtype="float64")
    for row in grid_households.itertuples(index=False):
        household_population[int(row.grid_id)] += float(row.household_members)
    residual = np.maximum(worldpop[:, 0].astype("float64") - household_population, 0.0)
    grid_counts = largest_remainder(residual, count)
    rows: list[dict[str, object]] = []
    bands = np.array([0, 1, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80] * 2)
    sexes = np.array(["M"] * 18 + ["F"] * 18)
    cursor = 0
    for grid_id, n in enumerate(grid_counts):
        if n <= 0:
            continue
        probabilities = np.maximum(demos[grid_id].astype("float64"), 0.0)
        sampled = weighted_choices(rng, np.arange(36), probabilities, int(n)).astype(int)
        for band_idx in sampled:
            lower = int(bands[band_idx])
            upper = 90 if lower == 80 else (4 if lower == 1 else lower + 4)
            if lower == 0:
                upper = 0
            age = int(rng.integers(lower, upper + 1))
            rows.append({
                "person_id": f"hk_collective_{cursor:06d}", "person_index": -1 - cursor,
                "household_id": "", "household_index": -1, "member_sequence": 0,
                "relationship_role": "collective_resident", "age": age,
                "age_band_census": 1 if age < 15 else (2 if age < 25 else (3 if age < 45 else (4 if age < 65 else 5))),
                "sex": str(sexes[band_idx]), "dcca": int(grid_dcca.get(grid_id, -1)),
                "grid_id": grid_id, "tcs_zone": int(grid_tcs.get(grid_id, -1)),
                "household_private_vehicle_count": 0, "potential_household_vehicle_access": False,
                "is_designated_driver": False, "assigned_vehicle_count": 0,
            })
            cursor += 1
    return pd.DataFrame(rows)


def sample_population_weighted_points(
    grid: gpd.GeoDataFrame,
    counts: pd.Series,
    raster_path: Path,
    rng: np.random.Generator,
    skip_raster: bool,
) -> dict[int, np.ndarray]:
    result: dict[int, np.ndarray] = {}
    if skip_raster:
        for grid_id, n in counts.items():
            point = grid.geometry.iloc[int(grid_id)].representative_point()
            result[int(grid_id)] = np.repeat([[point.x, point.y]], int(n), axis=0)
        return result
    with rasterio.open(raster_path) as source:
        data = source.read(masked=True).filled(0).sum(axis=0).astype("float64")
        rows, cols = np.nonzero(data > 0)
        weights = data[rows, cols]
        xs, ys = rasterio.transform.xy(source.transform, rows, cols, offset="center")
        transformer = Transformer.from_crs(source.crs, grid.crs, always_xy=True)
        x, y = transformer.transform(np.asarray(xs), np.asarray(ys))
    pixels = gpd.GeoDataFrame(
        {"x": x, "y": y, "weight": weights},
        geometry=gpd.points_from_xy(x, y), crs=grid.crs,
    )
    joined = gpd.sjoin(pixels, grid[["grid_id", "geometry"]], predicate="within", how="inner")
    pixel_groups = {int(key): value for key, value in joined.groupby("grid_id", sort=False)}
    for grid_id, n_value in counts.items():
        n = int(n_value)
        if n <= 0:
            continue
        candidates = pixel_groups.get(int(grid_id))
        if candidates is None or candidates.empty:
            point = grid.geometry.iloc[int(grid_id)].representative_point()
            result[int(grid_id)] = np.repeat([[point.x, point.y]], n, axis=0)
            continue
        picked = weighted_choices(
            rng, np.arange(len(candidates)), candidates.weight.to_numpy(dtype="float64"), n
        ).astype(int)
        result[int(grid_id)] = candidates[["x", "y"]].to_numpy(dtype="float64")[picked]
    return result


def assign_home_coordinates(
    households: pd.DataFrame,
    residents: pd.DataFrame,
    grid: gpd.GeoDataFrame,
    raster_path: Path,
    rng: np.random.Generator,
    skip_raster: bool,
) -> tuple[pd.DataFrame, dict[str, Facility]]:
    household_counts = households.groupby("grid_id").size()
    collective = residents.household_id.eq("")
    collective_counts = residents.loc[collective].groupby("grid_id").size()
    total_counts = household_counts.add(collective_counts, fill_value=0).astype(int)
    point_pools = sample_population_weighted_points(grid, total_counts, raster_path, rng, skip_raster)
    coordinates: dict[str, tuple[float, float]] = {}
    facilities: dict[str, Facility] = {}
    for grid_id, group in households.groupby("grid_id", sort=True):
        points = point_pools[int(grid_id)]
        for row, point in zip(group.itertuples(index=False), points):
            facility_id = f"home_{row.household_id}"
            coordinates[str(row.household_id)] = (float(point[0]), float(point[1]))
            facilities[facility_id] = Facility(facility_id, "home", float(point[0]), float(point[1]), source="worldpop_pixel")
    collective_pools: dict[int, np.ndarray] = {}
    for grid_id, n_value in collective_counts.items():
        household_n = int(household_counts.get(grid_id, 0))
        collective_pools[int(grid_id)] = point_pools[int(grid_id)][household_n:household_n + int(n_value)]
        point_pools[int(grid_id)] = point_pools[int(grid_id)][:household_n]
    collective_cursor = defaultdict(int)
    home_x = np.empty(len(residents), dtype="float64")
    home_y = np.empty(len(residents), dtype="float64")
    home_facility = np.empty(len(residents), dtype=object)
    for idx, row in residents.iterrows():
        if row.household_id:
            x, y = coordinates[str(row.household_id)]
            facility_id = f"home_{row.household_id}"
        else:
            grid_id = int(row.grid_id)
            offset = collective_cursor[grid_id]
            collective_cursor[grid_id] += 1
            x, y = collective_pools[grid_id][offset]
            facility_id = f"home_{row.person_id}"
            facilities[facility_id] = Facility(facility_id, "home", float(x), float(y), source="collective_worldpop_pixel")
        home_x[idx], home_y[idx], home_facility[idx] = x, y, facility_id
    residents["home_x"] = home_x
    residents["home_y"] = home_y
    residents["home_facility_id"] = home_facility
    return residents, facilities


def allocate_without_replacement(
    residents: pd.DataFrame,
    candidates: np.ndarray,
    count: int,
    rng: np.random.Generator,
) -> np.ndarray:
    available = candidates[residents.loc[candidates, "role"].eq("home_only").to_numpy()]
    if count > len(available):
        count = len(available)
    if count <= 0:
        return np.empty(0, dtype="int64")
    return rng.choice(available, size=count, replace=False)


def assign_student_roles(residents: pd.DataFrame, origins: pd.DataFrame, rate: float, rng: np.random.Generator) -> pd.DataFrame:
    origins = origins.groupby(["grid_id", "student_stage"], as_index=False).students.sum()
    formal_total = round(origins.students.sum() * rate)
    origins["target"] = largest_remainder(origins.students.to_numpy(), formal_total)
    age_ranges = {"kindergarten": (3, 5), "primary": (6, 11), "secondary": (12, 17), "special": (3, 21)}
    grid_groups = {int(key): np.asarray(value, dtype="int64") for key, value in residents.groupby("grid_id").groups.items()}
    for stage in ["special", "kindergarten", "primary", "secondary"]:
        low, high = age_ranges[stage]
        stage_rows = origins.loc[origins.student_stage.eq(stage) & origins.target.gt(0)]
        for row in stage_rows.itertuples(index=False):
            group = grid_groups.get(int(row.grid_id), np.empty(0, dtype="int64"))
            local = residents.loc[group]
            candidates = group[(local.age.between(low, high) & local.role.eq("home_only")).to_numpy()]
            selected = allocate_without_replacement(residents, candidates, int(row.target), rng)
            residents.loc[selected, "role"] = "day_school_student"
            residents.loc[selected, "student_stage"] = stage
    return residents


def assign_fixed_workers(residents: pd.DataFrame, work_od: np.ndarray, rate: float, rng: np.random.Generator) -> pd.DataFrame:
    target_total = round(float(work_od.sum()) * rate)
    row_targets = largest_remainder(work_od.sum(axis=1), target_total)
    grid_groups = {int(key): np.asarray(value, dtype="int64") for key, value in residents.groupby("grid_id").groups.items()}
    for grid_id, target in enumerate(row_targets):
        if target <= 0:
            continue
        group = grid_groups.get(grid_id, np.empty(0, dtype="int64"))
        local = residents.loc[group]
        candidates = group[(local.age.between(18, 69) & local.role.eq("home_only")).to_numpy()]
        selected = allocate_without_replacement(residents, candidates, int(target), rng)
        if len(selected) < int(target):
            local = residents.loc[group]
            fallback = group[(local.age.between(15, 84) & local.role.eq("home_only")).to_numpy()]
            extra = allocate_without_replacement(residents, fallback, int(target) - len(selected), rng)
            selected = np.concatenate([selected, extra])
        residents.loc[selected, "role"] = "fixed_worker"
    return residents


def assign_census_residual_roles(
    residents: pd.DataFrame,
    census: pd.DataFrame,
    retention: pd.DataFrame,
    rate: float,
    rng: np.random.Generator,
) -> pd.DataFrame:
    controls = census.merge(retention[["dcca", "fixed_link_population_ratio"]], on="dcca", how="left")
    controls["fixed_link_population_ratio"] = controls.fixed_link_population_ratio.fillna(0)
    roles = [("work_home", "plw_hm"), ("work_mobile", "plw_nofix"), ("work_outside_hk", "plw_out")]
    dcca_groups = {int(key): np.asarray(value, dtype="int64") for key, value in residents.groupby("dcca").groups.items()}
    for role, column in roles:
        for row in controls.itertuples(index=False):
            target = round(float(getattr(row, column)) * float(row.fixed_link_population_ratio) * rate)
            group = dcca_groups.get(int(row.dcca), np.empty(0, dtype="int64"))
            local = residents.loc[group]
            candidates = group[(local.age.between(18, 74) & local.role.eq("home_only")).to_numpy()]
            selected = allocate_without_replacement(residents, candidates, target, rng)
            residents.loc[selected, "role"] = role
    return residents


def assign_tertiary_students(
    residents: pd.DataFrame,
    study_flows: pd.DataFrame,
    rate: float,
    rng: np.random.Generator,
) -> pd.DataFrame:
    by_dcca = study_flows.groupby("dcca", as_index=False).agg(
        full_time_students=("fixed_link_adjusted_students", "sum"),
        day_school_students=("modeled_students", "sum"),
    )
    by_dcca["residual"] = np.maximum(by_dcca.full_time_students - by_dcca.day_school_students, 0)
    dcca_groups = {int(key): np.asarray(value, dtype="int64") for key, value in residents.groupby("dcca").groups.items()}
    for row in by_dcca.itertuples(index=False):
        target = round(float(row.residual) * rate)
        group = dcca_groups.get(int(row.dcca), np.empty(0, dtype="int64"))
        local = residents.loc[group]
        candidates = group[(local.age.between(18, 29) & local.role.eq("home_only")).to_numpy()]
        selected = allocate_without_replacement(residents, candidates, target, rng)
        residents.loc[selected, "role"] = "tertiary_student"
        residents.loc[selected, "student_stage"] = "tertiary"
    return residents


def residence_area(dc_name: str) -> str:
    hk = {"Central and Western", "Wan Chai", "Eastern", "Southern"}
    kln = {"Yau Tsim Mong", "Sham Shui Po", "Kowloon City", "Wong Tai Sin", "Kwun Tong"}
    return "hong_kong_island" if dc_name in hk else ("kowloon" if dc_name in kln else "new_territories")


def load_pois(path: Path, grid: gpd.GeoDataFrame) -> pd.DataFrame:
    pois = pd.read_csv(path, low_memory=False)
    lon_col = "longitude" if "longitude" in pois else "lon"
    lat_col = "latitude" if "latitude" in pois else "lat"
    pois[lon_col] = pd.to_numeric(pois[lon_col], errors="coerce")
    pois[lat_col] = pd.to_numeric(pois[lat_col], errors="coerce")
    pois = pois.loc[pois[lon_col].notna() & pois[lat_col].notna()].copy()
    transformer = Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True)
    pois["x"], pois["y"] = transformer.transform(pois[lon_col].to_numpy(), pois[lat_col].to_numpy())
    if "grid_id" not in pois:
        points = gpd.GeoDataFrame(pois[["poi_uid"]].copy(), geometry=gpd.points_from_xy(pois.x, pois.y), crs=grid.crs)
        joined = gpd.sjoin(points, grid[["grid_id", "geometry"]], predicate="within", how="left")
        pois["grid_id"] = joined.grid_id.to_numpy()
    pois["grid_id"] = pd.to_numeric(pois.grid_id, errors="coerce").fillna(-1).astype(int)
    pois["wedan_category"] = pois.get("wedan_category", "").fillna("").astype(str).str.lower()
    pois["poi_uid"] = pois.get("poi_uid", pd.Series(np.arange(len(pois)))).astype(str)
    return pois


def choose_work_destinations(
    residents: pd.DataFrame,
    work_od: np.ndarray,
    commute_modes: pd.DataFrame,
    pois: pd.DataFrame,
    grid: gpd.GeoDataFrame,
    rng: np.random.Generator,
    facilities: dict[str, Facility],
) -> pd.DataFrame:
    workers = residents.index[residents.role.eq("fixed_worker")].to_numpy(dtype="int64")
    dc_names = residents.groupby("dcca").dc_eng.first().to_dict()
    mode_rows = commute_modes.loc[
        ~commute_modes.residence_area_3_code.eq("total") & ~commute_modes.mode_code.eq("total")
    ].copy()
    grouped_modes: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for area, group in mode_rows.groupby("residence_area_3_code"):
        totals = group.groupby("mode_code", as_index=False).workers.sum()
        grouped_modes[str(area)] = (totals.mode_code.to_numpy(dtype=str), totals.workers.to_numpy(dtype=float))
    work_pois = pois.loc[pois.wedan_category.isin(WORK_CATEGORIES) & pois.grid_id.ge(0)].copy()
    poi_by_grid = {int(key): value for key, value in work_pois.groupby("grid_id")}
    representatives = grid.geometry.representative_point()
    grid_area = {
        int(row.grid_id): residence_area(str(row.dc_eng)) if str(row.dc_eng) else "unknown"
        for row in grid[["grid_id", "dc_eng"]].itertuples(index=False)
    }
    grid_district = grid.set_index("grid_id").dc_eng.fillna("").astype(str).to_dict()
    district_names = sorted({value for value in grid_district.values() if value})
    district_masks = {
        district: np.asarray([grid_district.get(index, "") == district for index in range(len(grid))])
        for district in district_names
    }
    assigned_mode_detail: dict[int, str] = {}
    for area in ["hong_kong_island", "kowloon", "new_territories"]:
        area_workers = np.asarray([
            index for index in workers
            if residence_area(str(dc_names.get(int(residents.at[index, "dcca"]), ""))) == area
        ], dtype="int64")
        if not len(area_workers):
            continue
        mode_values, mode_weights = grouped_modes.get(area, grouped_modes["new_territories"])
        mode_counts = largest_remainder(mode_weights, len(area_workers))
        available = area_workers.copy()
        rng.shuffle(available)
        car_position = np.flatnonzero(mode_values == "private_car_passenger_van")
        if len(car_position):
            car_target = int(mode_counts[car_position[0]])
            eligible = available[residents.loc[available, "is_designated_driver"].fillna(False).to_numpy(dtype=bool)]
            selected_car = eligible[:car_target]
            if len(selected_car) < car_target:
                fill = available[~np.isin(available, selected_car)][:car_target - len(selected_car)]
                selected_car = np.concatenate([selected_car, fill])
            for index in selected_car:
                assigned_mode_detail[int(index)] = "private_car_passenger_van"
            available = available[~np.isin(available, selected_car)]
        cursor = 0
        for mode_value, count in zip(mode_values, mode_counts):
            if mode_value == "private_car_passenger_van":
                continue
            selected = available[cursor:cursor + int(count)]
            cursor += len(selected)
            for index in selected:
                assigned_mode_detail[int(index)] = str(mode_value)
        for index in available[cursor:]:
            assigned_mode_detail[int(index)] = "total"
    for origin, person_indices in residents.loc[workers].groupby("grid_id").groups.items():
        indices = np.asarray(list(person_indices), dtype="int64")
        row = np.maximum(work_od[int(origin)].astype("float64"), 0.0)
        district_weights = np.asarray([row[mask].sum() for mask in district_masks.values()], dtype="float64")
        district_counts = largest_remainder(district_weights, len(indices))
        destination_counts = np.zeros(len(row), dtype="int64")
        for district, district_count in zip(district_names, district_counts):
            mask = district_masks[district]
            destination_counts[mask] = largest_remainder(row[mask], int(district_count))
        walk_indices = indices[np.asarray([assigned_mode_detail[int(index)] == "on_foot" for index in indices])]
        other_indices = indices[~np.isin(indices, walk_indices)]
        origin_district = grid_district.get(int(origin), "")
        local_destinations = district_masks.get(origin_district, np.zeros(len(row), dtype=bool))
        if len(walk_indices) and int(destination_counts[local_destinations].sum()) >= len(walk_indices):
            destination_counts[local_destinations] = largest_remainder(
                destination_counts[local_destinations], int(destination_counts[local_destinations].sum()) - len(walk_indices)
            )
        else:
            walk_indices = np.empty(0, dtype="int64")
            other_indices = indices
        destinations = np.empty(len(indices), dtype="int64")
        positions = {int(index): position for position, index in enumerate(indices)}
        for index in walk_indices:
            destinations[positions[int(index)]] = int(origin)
        other_destinations = np.repeat(np.arange(len(row)), destination_counts).astype(int)
        rng.shuffle(other_destinations)
        if len(other_destinations) != len(other_indices):
            other_destinations = weighted_choices(rng, np.arange(len(row)), destination_counts, len(other_indices)).astype(int)
        for index, destination in zip(other_indices, other_destinations):
            destinations[positions[int(index)]] = destination
        for person_idx, destination in zip(indices, destinations):
            detail = assigned_mode_detail[int(person_idx)]
            if detail == "on_foot":
                matsim_mode = "walk"
            elif detail == "private_car_passenger_van":
                matsim_mode = "car" if bool(residents.at[person_idx, "is_designated_driver"]) else "ride"
            elif detail in PT_WORK_MODES:
                matsim_mode = "pt"
            elif detail == "taxi":
                matsim_mode = "ride"
            else:
                matsim_mode = "pt"
            if destination in poi_by_grid:
                choice = poi_by_grid[destination].iloc[int(rng.integers(0, len(poi_by_grid[destination])))]
                facility_id = f"work_poi_{choice.poi_uid}"
                x, y, source = float(choice.x), float(choice.y), "integrated_work_poi"
            else:
                point = representatives.iloc[destination]
                facility_id = f"work_grid_{destination}"
                x, y, source = float(point.x), float(point.y), "grid_representative_fallback"
            facilities.setdefault(facility_id, Facility(facility_id, "work", x, y, source=source))
            residents.at[person_idx, "destination_grid_id"] = destination
            residents.at[person_idx, "destination_facility_id"] = facility_id
            residents.at[person_idx, "mode_detail"] = detail
            residents.at[person_idx, "matsim_mode"] = matsim_mode
    return residents


def choose_school_destinations(
    residents: pd.DataFrame,
    matrix_path: Path,
    schools_path: Path,
    school_mode_dir: Path,
    grid: gpd.GeoDataFrame,
    rng: np.random.Generator,
    facilities: dict[str, Facility],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    matrix = sparse.load_npz(matrix_path).tocsr()
    schools = gpd.read_file(schools_path).to_crs(grid.crs).sort_values("school_index").reset_index(drop=True)
    schools["school_index"] = pd.to_numeric(schools.school_index).astype(int)
    school_by_index = schools.set_index("school_index", drop=False)
    stage_by_index = np.full(matrix.shape[1], "", dtype=object)
    valid_school_indices = school_by_index.index.to_numpy(dtype=int)
    stage_by_index[valid_school_indices] = school_by_index.base_stage.astype(str).str.lower().to_numpy()
    school_modes = {}
    for path in sorted(school_mode_dir.glob("*.npy")):
        school_modes[path.stem] = float(np.load(path, mmap_mode="r").sum())
    mode_names = np.asarray(list(school_modes), dtype=str)
    mode_weights = np.asarray(list(school_modes.values()), dtype=float)
    mechanized_probability = 841_686.4956507729 / (2 * 800_761.1195713682)
    audit_rows: list[dict[str, object]] = []
    for (origin, stage), person_indices in residents.loc[residents.role.eq("day_school_student")].groupby(["grid_id", "student_stage"]).groups.items():
        indices = np.asarray(list(person_indices), dtype="int64")
        start, end = matrix.indptr[int(origin)], matrix.indptr[int(origin) + 1]
        candidate_school = matrix.indices[start:end]
        weights = matrix.data[start:end].astype("float64")
        compatible = stage_by_index[candidate_school] == str(stage).lower()
        if compatible.any():
            candidate_school, weights = candidate_school[compatible], weights[compatible]
        else:
            retained = np.isin(candidate_school, valid_school_indices)
            candidate_school, weights = candidate_school[retained], weights[retained]
        chosen = weighted_choices(rng, candidate_school, weights, len(indices)).astype(int)
        for person_idx, school_idx in zip(indices, chosen):
            school = school_by_index.loc[school_idx]
            facility_id = f"school_{int(school.school_index)}"
            facilities.setdefault(facility_id, Facility(
                facility_id, f"school_{stage}", float(school.geometry.x), float(school.geometry.y), source="edb_school_coordinate"
            ))
            mechanized = bool(rng.random() < mechanized_probability)
            detail = str(weighted_choices(rng, mode_names, mode_weights, 1)[0]) if mechanized else "walk"
            if detail in {"private_vehicle", "taxi", "spb"}:
                matsim_mode = "ride"
            elif detail == "walk":
                matsim_mode = "walk"
            else:
                matsim_mode = "pt"
            residents.at[person_idx, "destination_grid_id"] = int(school.grid_id)
            residents.at[person_idx, "destination_facility_id"] = facility_id
            residents.at[person_idx, "mode_detail"] = detail
            residents.at[person_idx, "matsim_mode"] = matsim_mode
            audit_rows.append({
                "person_id": residents.at[person_idx, "person_id"], "origin_grid_id": int(origin),
                "student_stage": stage, "school_index": int(school.school_index),
                "school_no": str(school.get("SCHOOL NO.", "")), "destination_grid_id": int(school.grid_id),
                "mode_detail": detail, "matsim_mode": matsim_mode,
            })
    return residents, pd.DataFrame(audit_rows)


def choose_proxy_destinations(
    residents: pd.DataFrame,
    distance: np.ndarray,
    work_od: np.ndarray,
    pois: pd.DataFrame,
    grid: gpd.GeoDataFrame,
    rng: np.random.Generator,
    facilities: dict[str, Facility],
) -> pd.DataFrame:
    representatives = grid.geometry.representative_point()
    work_attraction = np.maximum(work_od.sum(axis=0), 0)
    education = pois.loc[pois.wedan_category.isin(EDUCATION_CATEGORIES) & pois.grid_id.ge(0)]
    work_pois = pois.loc[pois.wedan_category.isin(WORK_CATEGORIES) & pois.grid_id.ge(0)]
    for role, subset, scale, activity_type in [
        ("work_mobile", work_pois, 5_000.0, "work_mobile"),
        ("tertiary_student", education, 8_000.0, "education_tertiary"),
    ]:
        by_grid = {int(key): value for key, value in subset.groupby("grid_id")}
        for origin, indices_value in residents.loc[residents.role.eq(role)].groupby("grid_id").groups.items():
            indices = np.asarray(list(indices_value), dtype="int64")
            attraction = work_attraction.copy() if role == "work_mobile" else np.asarray([len(by_grid.get(i, [])) for i in range(len(grid))], dtype=float)
            weights = attraction * np.exp(-distance[int(origin)].astype("float64") / scale)
            destinations = weighted_choices(rng, np.arange(len(grid)), weights, len(indices)).astype(int)
            for person_idx, destination in zip(indices, destinations):
                if destination in by_grid:
                    poi = by_grid[destination].iloc[int(rng.integers(0, len(by_grid[destination])))]
                    facility_id = f"{activity_type}_poi_{poi.poi_uid}"
                    x, y, source = float(poi.x), float(poi.y), f"integrated_{activity_type}_poi"
                else:
                    point = representatives.iloc[destination]
                    facility_id = f"{activity_type}_grid_{destination}"
                    x, y, source = float(point.x), float(point.y), "grid_representative_fallback"
                facilities.setdefault(facility_id, Facility(facility_id, activity_type, x, y, source=source))
                residents.at[person_idx, "destination_grid_id"] = destination
                residents.at[person_idx, "destination_facility_id"] = facility_id
                residents.at[person_idx, "mode_detail"] = "modeled_proxy"
                residents.at[person_idx, "matsim_mode"] = "pt"
    return residents


def build_network_link_index(network_path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    with gzip.open(network_path, "rb") as handle:
        root = ET.parse(handle).getroot()
    nodes: dict[str, tuple[float, float]] = {}
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "node":
            nodes[element.attrib["id"]] = (float(element.attrib["x"]), float(element.attrib["y"]))
    node_ids = list(nodes)
    node_index = {node_id: index for index, node_id in enumerate(node_ids)}
    records: list[tuple[str, str, str, tuple[float, float]]] = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "link":
            continue
        modes = set(element.attrib.get("modes", "car").split(","))
        if "car" not in modes:
            continue
        origin, destination = nodes[element.attrib["from"]], nodes[element.attrib["to"]]
        records.append((
            element.attrib["id"], element.attrib["from"], element.attrib["to"],
            ((origin[0] + destination[0]) / 2, (origin[1] + destination[1]) / 2),
        ))
    rows = np.asarray([node_index[value[1]] for value in records], dtype="int64")
    cols = np.asarray([node_index[value[2]] for value in records], dtype="int64")
    graph = sparse.csr_matrix((np.ones(len(records), dtype=np.int8), (rows, cols)), shape=(len(nodes), len(nodes)))
    component_count, labels = connected_components(graph, directed=True, connection="strong")
    component_sizes = np.bincount(labels, minlength=component_count)
    largest = int(np.argmax(component_sizes))
    retained = [value for value in records if labels[node_index[value[1]]] == largest and labels[node_index[value[2]]] == largest]
    ids = [value[0] for value in retained]
    coordinates = [value[3] for value in retained]
    return np.asarray(ids, dtype=object), np.asarray(coordinates, dtype="float64"), np.asarray(list(nodes.values()), dtype="float64")


def snap_facilities(facilities: dict[str, Facility], network_path: Path) -> dict[str, Facility]:
    link_ids, coordinates, _ = build_network_link_index(network_path)
    tree = cKDTree(coordinates)
    keys = list(facilities)
    query = np.asarray([[facilities[key].x, facilities[key].y] for key in keys], dtype="float64")
    distances, positions = tree.query(query, k=1)
    result = {}
    for key, distance, position in zip(keys, distances, positions):
        item = facilities[key]
        result[key] = Facility(item.facility_id, item.activity_type, item.x, item.y, str(link_ids[int(position)]), item.source)
    return result


def assign_times(residents: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    residents["outbound_time_s"] = np.nan
    residents["return_time_s"] = np.nan
    workers = residents.role.isin(["fixed_worker", "work_mobile"])
    worker_count = int(workers.sum())
    starts = np.clip(rng.normal(8.75 * 3600, 45 * 60, worker_count), 5.5 * 3600, 12 * 3600)
    durations = np.clip(rng.normal(8.5 * 3600, 75 * 60, worker_count), 4 * 3600, 12 * 3600)
    residents.loc[workers, "outbound_time_s"] = starts - np.clip(rng.normal(45 * 60, 20 * 60, worker_count), 10 * 60, 120 * 60)
    residents.loc[workers, "return_time_s"] = starts + durations
    school = residents.role.eq("day_school_student")
    n_school = int(school.sum())
    residents.loc[school, "outbound_time_s"] = np.clip(rng.normal(7.45 * 3600, 25 * 60, n_school), 6.5 * 3600, 8.75 * 3600)
    stages = residents.loc[school, "student_stage"].astype(str).to_numpy()
    school_end = np.where(stages == "kindergarten", 12.5 * 3600, np.where(stages == "primary", 15.5 * 3600, 16.0 * 3600))
    residents.loc[school, "return_time_s"] = school_end + rng.normal(0, 20 * 60, n_school)
    tertiary = residents.role.eq("tertiary_student")
    n_tertiary = int(tertiary.sum())
    residents.loc[tertiary, "outbound_time_s"] = np.clip(rng.normal(8.7 * 3600, 60 * 60, n_tertiary), 7 * 3600, 12 * 3600)
    residents.loc[tertiary, "return_time_s"] = np.clip(rng.normal(16.5 * 3600, 90 * 60, n_tertiary), 12 * 3600, 22 * 3600)
    return residents


def assign_school_escorts(residents: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Give one compatible private-vehicle student to each available household driver."""
    students = residents.loc[
        residents.role.eq("day_school_student") & residents.mode_detail.eq("private_vehicle")
        & residents.household_id.ne("")
    ].sort_values(["household_id", "outbound_time_s", "person_id"])
    drivers = residents.loc[
        residents.is_designated_driver.fillna(False) & residents.role.isin(["home_only", "work_home"])
        & residents.household_id.ne("")
    ]
    driver_by_household = {str(key): list(value) for key, value in drivers.groupby("household_id").groups.items()}
    used: set[int] = set()
    audit: list[dict[str, object]] = []
    for student in students.itertuples():
        candidates = [int(index) for index in driver_by_household.get(str(student.household_id), []) if int(index) not in used]
        if not candidates:
            continue
        driver_index = candidates[0]
        used.add(driver_index)
        residents.at[driver_index, "role"] = "school_escort"
        residents.at[driver_index, "destination_grid_id"] = int(student.destination_grid_id)
        residents.at[driver_index, "destination_facility_id"] = str(student.destination_facility_id)
        residents.at[driver_index, "matsim_mode"] = "car"
        residents.at[driver_index, "mode_detail"] = "school_escort_private_vehicle"
        residents.at[driver_index, "outbound_time_s"] = float(student.outbound_time_s)
        residents.at[driver_index, "return_time_s"] = float(student.return_time_s)
        audit.append({
            "student_person_id": student.person_id, "driver_person_id": residents.at[driver_index, "person_id"],
            "household_id": student.household_id, "school_facility_id": student.destination_facility_id,
            "morning_departure_time_s": float(student.outbound_time_s),
            "afternoon_pickup_time_s": float(student.return_time_s),
        })
    return residents, pd.DataFrame(audit)


def assign_vehicle_ids(residents: pd.DataFrame, vehicles_path: Path, selected_households: set[int]) -> tuple[pd.DataFrame, pd.DataFrame]:
    vehicles = pd.read_parquet(vehicles_path)
    vehicles = vehicles.loc[vehicles.household_index.isin(selected_households)].copy()
    driver_lookup = vehicles.loc[vehicles.vehicle_type.eq("private_car")].groupby("driver_person_id").vehicle_id.first().to_dict()
    residents["assigned_vehicle_id"] = residents.person_id.map(driver_lookup).fillna("").astype(str)
    residents.loc[~residents.matsim_mode.eq("car"), "assigned_vehicle_id"] = ""
    invalid_car = residents.matsim_mode.eq("car") & residents.assigned_vehicle_id.eq("")
    residents.loc[invalid_car, "matsim_mode"] = "ride"
    return residents, vehicles


def select_typical_resident_border_travelers(
    residents: pd.DataFrame,
    events: pd.DataFrame,
    ports: pd.DataFrame,
    grid: gpd.GeoDataFrame,
    rng: np.random.Generator,
    facilities: dict[str, Facility],
    rate: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    usual = events.loc[events.person_segment.eq("hk_usual_resident")].copy()
    departure = usual.loc[usual.direction.eq("departure")]
    target = round(float(departure.passenger_movements.sum()) * rate)
    grid_targets = largest_remainder(departure.groupby("grid_index").passenger_movements.sum().reindex(range(len(grid)), fill_value=0).to_numpy(), target)
    chosen_rows: list[dict[str, object]] = []
    grid_groups = {int(key): np.asarray(value, dtype="int64") for key, value in residents.groupby("grid_id").groups.items()}
    for grid_id, count in enumerate(grid_targets):
        if count <= 0:
            continue
        group = grid_groups.get(grid_id, np.empty(0, dtype="int64"))
        local = residents.loc[group]
        candidates = group[(local.role.isin(["work_outside_hk", "home_only", "work_home"]) & local.age.ge(16)).to_numpy()]
        selected = rng.choice(candidates, size=min(int(count), len(candidates)), replace=False) if len(candidates) else np.empty(0, dtype=int)
        port_rows = departure.loc[departure.grid_index.eq(grid_id)]
        port_names = port_rows.control_point.to_numpy(dtype=str)
        port_weights = port_rows.passenger_movements.to_numpy(dtype=float)
        selected_ports = weighted_choices(rng, port_names, port_weights, len(selected))
        for person_idx, port_name in zip(selected, selected_ports):
            residents.at[person_idx, "role"] = "usual_resident_border"
            residents.at[person_idx, "border_control_point"] = str(port_name)
            residents.at[person_idx, "matsim_mode"] = "pt"
            residents.at[person_idx, "mode_detail"] = "border_pt_proxy"
            chosen_rows.append({
                "person_id": residents.at[person_idx, "person_id"], "person_index_in_frame": int(person_idx),
                "grid_id": grid_id, "control_point": str(port_name),
            })
    transformer = Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True)
    for row in ports.itertuples(index=False):
        x, y = transformer.transform(float(row.longitude), float(row.latitude))
        facility_id = f"border_{int(row.bcp_index)}"
        facilities[facility_id] = Facility(facility_id, "border", x, y, source="official_control_point")
    port_index = ports.set_index("control_point").bcp_index.to_dict()
    for row in chosen_rows:
        idx = int(row["person_index_in_frame"])
        residents.at[idx, "destination_facility_id"] = f"border_{int(port_index[row['control_point']])}"
        residents.at[idx, "outbound_time_s"] = float(rng.normal(7.5 * 3600, 75 * 60))
        residents.at[idx, "return_time_s"] = float(rng.normal(19 * 3600, 90 * 60))
    return residents, pd.DataFrame(chosen_rows)


def integerize_weighted_rows(frame: pd.DataFrame, weight: pd.Series, target: int, rng: np.random.Generator) -> pd.DataFrame:
    expected = np.maximum(weight.to_numpy(dtype="float64"), 0.0)
    counts = largest_remainder(expected, target)
    repeated = np.repeat(np.arange(len(frame)), counts)
    if len(repeated):
        rng.shuffle(repeated)
    result = frame.iloc[repeated].copy().reset_index(drop=True)
    result["source_expected_weight"] = expected[repeated]
    return result


def build_external_agents(
    tourism: Path,
    ports: pd.DataFrame,
    grid: gpd.GeoDataFrame,
    facilities: dict[str, Facility],
    rng: np.random.Generator,
    rate: float,
) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    tours = pd.read_parquet(tourism / "synthetic_visitor_tours.parquet")
    activities = pd.read_parquet(tourism / "synthetic_visitor_activities.parquet")
    events = pd.read_parquet(tourism / "resident_border_events.parquet")
    transformer = Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True)
    grid_points = grid.geometry.representative_point()
    activity_lookup = {int(key): value.sort_values("activity_sequence") for key, value in activities.groupby("tour_id")}
    visitor_days = tours.sample_weight * (tours.expected_stay_nights + 1.0) * rate
    visitor_target = round(float(visitor_days.sum()))
    sampled_tours = integerize_weighted_rows(tours, visitor_days, visitor_target, rng)
    port_index = ports.set_index("control_point").bcp_index.to_dict()
    external_rows: list[dict[str, object]] = []
    external_plans: list[dict[str, object]] = []
    for cursor, row in enumerate(sampled_tours.itertuples(index=False)):
        source_activities = activity_lookup[int(row.tour_id)]
        overnight = str(row.stay_type) == "overnight"
        day_draw = rng.random()
        if not overnight:
            day_kind = "same_day"
        elif day_draw < 1 / 4.1:
            day_kind = "arrival_day"
        elif day_draw < 2 / 4.1:
            day_kind = "departure_day"
        else:
            day_kind = "stay_day"
        activity_specs: list[dict[str, object]] = []
        if day_kind in {"same_day", "arrival_day"}:
            bcp = int(port_index[str(row.arrival_control_point)])
            activity_specs.append({"facility_id": f"border_{bcp}", "type": "border", "end": 9.5 * 3600 if day_kind == "same_day" else 17 * 3600})
        for activity in source_activities.itertuples(index=False):
            point_id = str(activity.point_id) if str(activity.point_id) not in {"", "nan"} else f"grid_{int(activity.grid_index)}"
            facility_id = f"visitor_{point_id.replace(':', '_').replace(' ', '_')}"
            x, y = transformer.transform(float(activity.longitude), float(activity.latitude))
            facilities.setdefault(facility_id, Facility(facility_id, str(activity.activity_type), x, y, source=str(activity.point_source)))
            if day_kind == "arrival_day" and str(activity.activity_type) != "accommodation":
                continue
            if day_kind == "departure_day" and str(activity.activity_type) == "secondary_activity":
                continue
            activity_specs.append({"facility_id": facility_id, "type": str(activity.activity_type), "end": None})
        if day_kind in {"same_day", "departure_day"}:
            bcp = int(port_index[str(row.departure_control_point)])
            activity_specs.append({"facility_id": f"border_{bcp}", "type": "border", "end": None})
        elif overnight and activity_specs:
            accommodation = next((value for value in activity_specs if value["type"] == "accommodation"), None)
            if accommodation is not None and activity_specs[-1]["facility_id"] != accommodation["facility_id"]:
                activity_specs.append({"facility_id": accommodation["facility_id"], "type": "accommodation", "end": None})
        for index in range(len(activity_specs) - 1):
            if activity_specs[index]["end"] is None:
                activity_specs[index]["end"] = [9 * 3600, 13 * 3600, 18 * 3600, 20 * 3600][min(index, 3)]
        mode = "pt" if rng.random() < (0.77 if not overnight else 0.61) else "ride"
        person_id = f"hk_visitor_{cursor:06d}"
        external_rows.append({
            "person_id": person_id, "population_group": "visitor", "role": str(row.person_segment),
            "household_id": "", "age": -1, "sex": "", "dcca": -1, "grid_id": -1,
            "tcs_zone": -1, "expansion_weight": 20.0, "matsim_mode": mode,
            "mode_detail": "visitor_tcs_proxy", "visitor_day_kind": day_kind,
        })
        external_plans.append({"person_id": person_id, "activities": activity_specs, "mode": mode})

    mainland = events.loc[~events.person_segment.eq("hk_usual_resident")].copy()
    arrivals = mainland.loc[mainland.direction.eq("arrival")]
    mainland_target = round(float(arrivals.passenger_movements.sum()) * rate)
    sampled_mainland = integerize_weighted_rows(arrivals, arrivals.passenger_movements * rate, mainland_target, rng)
    departure = mainland.loc[mainland.direction.eq("departure")]
    for cursor, row in enumerate(sampled_mainland.itertuples(index=False)):
        matching = departure.loc[departure.person_segment.eq(row.person_segment)]
        departure_row = matching.iloc[int(rng.integers(0, len(matching)))] if len(matching) else None
        arrival_bcp = int(port_index[str(row.control_point)])
        departure_bcp = int(port_index[str(departure_row.control_point)]) if departure_row is not None else arrival_bcp
        destination_grid = int(row.grid_index)
        point = grid_points.iloc[destination_grid]
        activity_id = f"mainland_activity_{destination_grid}_{str(row.person_segment).replace(' ', '_')}"
        facilities.setdefault(activity_id, Facility(activity_id, "external_activity", float(point.x), float(point.y), source="pt_access_v2_grid"))
        purpose = str(row.person_segment).rsplit("_", 1)[-1]
        person_id = f"hk_mainland_resident_{cursor:06d}"
        external_rows.append({
            "person_id": person_id, "population_group": "mainland_hk_resident", "role": str(row.person_segment),
            "household_id": "", "age": -1, "sex": "", "dcca": -1, "grid_id": destination_grid,
            "tcs_zone": -1, "expansion_weight": 20.0, "matsim_mode": "pt", "mode_detail": "border_pt_proxy",
            "visitor_day_kind": "",
        })
        external_plans.append({
            "person_id": person_id, "mode": "pt", "activities": [
                {"facility_id": f"border_{arrival_bcp}", "type": "border", "end": 8 * 3600},
                {"facility_id": activity_id, "type": purpose, "end": 18 * 3600},
                {"facility_id": f"border_{departure_bcp}", "type": "border", "end": None},
            ],
        })
    return pd.DataFrame(external_rows), external_plans


def format_time(seconds: float | int | None) -> str | None:
    if seconds is None or not np.isfinite(seconds):
        return None
    seconds = max(0, int(round(float(seconds))))
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def resident_plan(row: pd.Series) -> dict[str, object]:
    home = str(row.home_facility_id)
    role = str(row.role)
    mode = str(row.matsim_mode or "walk")
    if role in {"home_only", "work_home"} or not str(row.destination_facility_id):
        activities = [{"facility_id": home, "type": "home", "end": None}]
    elif role == "school_escort":
        school = str(row.destination_facility_id)
        outbound = float(row.outbound_time_s)
        pickup = float(row.return_time_s)
        activities = [
            {"facility_id": home, "type": "home", "end": outbound},
            {"facility_id": school, "type": "school_escort", "end": outbound + 10 * 60},
            {"facility_id": home, "type": "home", "end": max(outbound + 20 * 60, pickup - 30 * 60)},
            {"facility_id": school, "type": "school_escort", "end": pickup},
            {"facility_id": home, "type": "home", "end": None},
        ]
    elif role == "usual_resident_border":
        activities = [
            {"facility_id": home, "type": "home", "end": float(row.outbound_time_s)},
            {"facility_id": str(row.destination_facility_id), "type": "border", "end": float(row.return_time_s)},
            {"facility_id": home, "type": "home", "end": None},
        ]
    else:
        activity_type = {
            "fixed_worker": "work", "work_mobile": "work_mobile", "day_school_student": f"school_{row.student_stage}",
            "tertiary_student": "education_tertiary", "work_outside_hk": "border",
        }.get(role, role)
        activities = [
            {"facility_id": home, "type": "home", "end": float(row.outbound_time_s)},
            {"facility_id": str(row.destination_facility_id), "type": activity_type, "end": float(row.return_time_s)},
            {"facility_id": home, "type": "home", "end": None},
        ]
    return {"person_id": str(row.person_id), "activities": activities, "mode": mode}


def write_facilities(path: Path, facilities: dict[str, Facility]) -> None:
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as handle:
        handle.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        handle.write('<!DOCTYPE facilities SYSTEM "http://www.matsim.org/files/dtd/facilities_v1.dtd">\n')
        handle.write('<facilities name="hong_kong_5pct_facilities">\n')
        for item in sorted(facilities.values(), key=lambda value: value.facility_id):
            handle.write(f'  <facility id={quoteattr(item.facility_id)} x="{item.x:.3f}" y="{item.y:.3f}" linkId={quoteattr(item.link_id)}>\n')
            handle.write(f'    <activity type={quoteattr(item.activity_type)}/>\n')
            if item.source == "edb_school_coordinate":
                handle.write('    <activity type="school_escort"/>\n')
            handle.write('  </facility>\n')
        handle.write('</facilities>\n')


def write_population(
    path: Path,
    resident_agents: pd.DataFrame,
    resident_plans: Iterable[dict[str, object]],
    external_agents: pd.DataFrame,
    external_plans: Iterable[dict[str, object]],
    facilities: dict[str, Facility],
    trip_writer: pq.ParquetWriter,
) -> tuple[int, int]:
    attributes = pd.concat([
        resident_agents.assign(population_group="resident", expansion_weight=20.0),
        external_agents,
    ], ignore_index=True, sort=False).set_index("person_id")
    plan_iter = itertools.chain(resident_plans, external_plans)
    trip_rows: list[dict[str, object]] = []
    person_count = leg_count = 0
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as handle:
        handle.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        handle.write('<!DOCTYPE population SYSTEM "http://www.matsim.org/files/dtd/population_v6.dtd">\n')
        handle.write('<population>\n')
        for plan in plan_iter:
            person_id = str(plan["person_id"])
            row = attributes.loc[person_id]
            assigned_vehicle_id = row.get("assigned_vehicle_id", "")
            if pd.isna(assigned_vehicle_id):
                assigned_vehicle_id = ""
            assigned_vehicle_id = str(assigned_vehicle_id)
            handle.write(f'  <person id={quoteattr(person_id)}>\n    <attributes>\n')
            values = {
                "subpopulation": str(row.get("population_group", "resident")),
                "expansionWeight": float(row.get("expansion_weight", 20.0)),
                "role": str(row.get("role", "")), "householdId": str(row.get("household_id", "")),
                "age": int(row.get("age", -1)), "sex": str(row.get("sex", "")),
                "dcca": int(row.get("dcca", -1)), "gridId": int(row.get("grid_id", -1)),
                "tcsZone": int(row.get("tcs_zone", -1)), "modeDetail": str(row.get("mode_detail", "")),
                "carAvail": "always" if assigned_vehicle_id else "never",
                "assignedVehicleId": assigned_vehicle_id,
            }
            for name, value in values.items():
                klass = "java.lang.Double" if isinstance(value, float) else ("java.lang.Integer" if isinstance(value, int) else "java.lang.String")
                handle.write(f'      <attribute name={quoteattr(name)} class={quoteattr(klass)}>{escape(str(value))}</attribute>\n')
            handle.write('    </attributes>\n    <plan selected="yes">\n')
            activities = plan["activities"]
            for sequence, activity in enumerate(activities):
                facility = facilities[str(activity["facility_id"])]
                end = format_time(activity.get("end"))
                end_attr = f' end_time={quoteattr(end)}' if end else ""
                handle.write(
                    f'      <activity type={quoteattr(str(activity["type"]))} facility={quoteattr(facility.facility_id)} '
                    f'link={quoteattr(facility.link_id)} x="{facility.x:.3f}" y="{facility.y:.3f}"{end_attr}/>\n'
                )
                if sequence < len(activities) - 1:
                    mode = str(plan["mode"])
                    handle.write(f'      <leg mode={quoteattr(mode)}/>\n')
                    destination = facilities[str(activities[sequence + 1]["facility_id"])]
                    trip_rows.append({
                        "person_id": person_id, "leg_sequence": sequence, "population_group": values["subpopulation"],
                        "role": values["role"], "mode": mode, "mode_detail": values["modeDetail"],
                        "origin_facility_id": facility.facility_id, "destination_facility_id": destination.facility_id,
                        "departure_time_s": activity.get("end"), "expansion_weight": values["expansionWeight"],
                    })
                    leg_count += 1
                    if len(trip_rows) >= 100_000:
                        trip_writer.write_table(pa.Table.from_pylist(trip_rows))
                        trip_rows.clear()
            handle.write('    </plan>\n  </person>\n')
            person_count += 1
        handle.write('</population>\n')
    if trip_rows:
        trip_writer.write_table(pa.Table.from_pylist(trip_rows))
    return person_count, leg_count


def write_private_vehicles(path: Path, vehicles: pd.DataFrame) -> None:
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as handle:
        handle.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        handle.write('<vehicleDefinitions xmlns="http://www.matsim.org/files/dtd" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.matsim.org/files/dtd http://www.matsim.org/files/dtd/vehicleDefinitions_v2.0.xsd">\n')
        for type_id, seats, pcu in [("private_car", 5, 1.0), ("motorcycle", 2, 0.25)]:
            handle.write(f'  <vehicleType id="{type_id}"><capacity seats="{seats}" standingRoomInPersons="0"/><length meter="4.5"/><width meter="1.8"/><passengerCarEquivalents pce="{pcu}"/><networkMode networkMode="car"/></vehicleType>\n')
        for row in vehicles.itertuples(index=False):
            type_id = "motorcycle" if str(row.vehicle_type) == "motorcycle" else "private_car"
            handle.write(f'  <vehicle id={quoteattr(str(row.vehicle_id))} type={quoteattr(type_id)}/>\n')
        handle.write('</vehicleDefinitions>\n')


def scale_transit_vehicles(source: Path, destination: Path, factor: float = SAMPLE_RATE) -> None:
    with gzip.open(source, "rb") as handle:
        tree = ET.parse(handle)
    root = tree.getroot()
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "capacity":
            seats = int(float(element.attrib.get("seats", 0)))
            standing = int(float(element.attrib.get("standingRoomInPersons", 0)))
            scaled_seats = max(1, round(seats * factor)) if seats > 0 else 0
            scaled_standing = max(0, round(standing * factor))
            if scaled_seats + scaled_standing < 1:
                scaled_seats = 1
            element.set("seats", str(scaled_seats))
            element.set("standingRoomInPersons", str(scaled_standing))
    with gzip.open(destination, "wb") as handle:
        tree.write(handle, encoding="utf-8", xml_declaration=True)


def _ordered_stop_link_indices(stop_xy: np.ndarray, segment_xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Assign stops to non-decreasing route-link occurrences by segment distance."""
    stop_count = len(stop_xy)
    link_count = len(segment_xy)
    if stop_count == 0 or link_count == 0:
        return np.empty(0, dtype="int64"), np.empty(0, dtype="float64")
    costs = np.empty((stop_count, link_count), dtype="float64")
    starts = segment_xy[:, :2]
    vectors = segment_xy[:, 2:] - starts
    length_sq = np.sum(vectors * vectors, axis=1)
    for stop_index, point in enumerate(stop_xy):
        relative = point - starts
        fraction = np.divide(
            np.sum(relative * vectors, axis=1), length_sq,
            out=np.zeros(link_count, dtype="float64"), where=length_sq > 0,
        )
        fraction = np.clip(fraction, 0.0, 1.0)
        projected = starts + fraction[:, None] * vectors
        costs[stop_index] = np.sum((projected - point) ** 2, axis=1)
    previous = np.full(link_count, np.inf, dtype="float64")
    previous[0] = costs[0, 0]
    predecessors: list[np.ndarray] = []
    for stop_index in range(1, stop_count):
        prefix_arg = np.empty(link_count, dtype="int64")
        best_index = 0
        best_value = previous[0]
        for link_index in range(link_count):
            if previous[link_index] < best_value:
                best_value = previous[link_index]
                best_index = link_index
            prefix_arg[link_index] = best_index
        current = costs[stop_index] + previous[prefix_arg]
        if stop_index == stop_count - 1:
            current[:-1] = np.inf
        predecessors.append(prefix_arg)
        previous = current
    assigned = np.empty(stop_count, dtype="int64")
    assigned[-1] = int(np.argmin(previous))
    for stop_index in range(stop_count - 1, 0, -1):
        assigned[stop_index - 1] = predecessors[stop_index - 1][assigned[stop_index]]
    return assigned, np.sqrt(costs[np.arange(stop_count), assigned])


def repair_closed_transit_routes(source: Path, network_path: Path, destination: Path, audit_path: Path) -> pd.DataFrame:
    """Close loops and bind every route stop to an ordered link occurrence."""
    with gzip.open(network_path, "rb") as handle:
        network_root = ET.parse(handle).getroot()
    local_name = lambda element: element.tag.rsplit("}", 1)[-1]
    node_xy = {
        element.get("id"): (float(element.get("x")), float(element.get("y")))
        for element in network_root.iter() if local_name(element) == "node"
    }
    link_nodes: dict[str, tuple[str, str]] = {}
    link_segments: dict[str, tuple[float, float, float, float]] = {}
    for element in network_root.iter():
        if local_name(element) != "link":
            continue
        link_id = element.get("id")
        from_node, to_node = element.get("from"), element.get("to")
        link_nodes[link_id] = (from_node, to_node)
        link_segments[link_id] = (*node_xy[from_node], *node_xy[to_node])
    with gzip.open(source, "rb") as handle:
        tree = ET.parse(handle)
    root = tree.getroot()
    transit_stops = next(element for element in root if local_name(element) == "transitStops")
    stop_elements = {
        element.get("id"): element for element in transit_stops if local_name(element) == "stopFacility"
    }
    audit: list[dict[str, object]] = []
    for route in [element for element in root.iter() if local_name(element) == "transitRoute"]:
        profile = next((element for element in route if local_name(element) == "routeProfile"), None)
        network_route = next((element for element in route if local_name(element) == "route"), None)
        if profile is None or network_route is None:
            continue
        stops = [element for element in profile if local_name(element) == "stop"]
        links = [element for element in network_route if local_name(element) == "link"]
        if not stops or not links:
            continue
        first_stop_id = stops[0].get("refId")
        terminal_link = stop_elements[stops[-1].get("refId")].get("linkRefId")
        final_link = links[-1].get("refId")
        closed_route_repair = False
        if stops[0].get("refId") == stops[-1].get("refId") and terminal_link != final_link:
            final_nodes = link_nodes.get(final_link)
            terminal_nodes = link_nodes.get(terminal_link)
            if final_nodes is None or terminal_nodes is None or final_nodes[1] != terminal_nodes[0]:
                raise ValueError(
                    f"Closed route {route.get('id')} cannot be safely joined: {final_link} -> {terminal_link}"
                )
            ET.SubElement(network_route, links[-1].tag, {"refId": terminal_link})
            links = [element for element in network_route if local_name(element) == "link"]
            closed_route_repair = True
        route_link_ids = [element.get("refId") for element in links]
        segments = np.asarray([link_segments[link_id] for link_id in route_link_ids], dtype="float64")
        stop_xy = np.asarray([
            (float(stop_elements[stop.get("refId")].get("x")), float(stop_elements[stop.get("refId")].get("y")))
            for stop in stops
        ], dtype="float64")
        assigned_indices, distances = _ordered_stop_link_indices(stop_xy, segments)
        route_token = hashlib.sha1(str(route.get("id")).encode("utf-8")).hexdigest()[:10]
        for sequence, (stop, link_index, distance) in enumerate(zip(stops, assigned_indices, distances)):
            source_stop_id = stop.get("refId")
            source_stop = stop_elements[source_stop_id]
            clone_id = f"{source_stop_id}__{route_token}_{sequence:03d}"
            clone_attributes = dict(source_stop.attrib)
            clone_attributes["id"] = clone_id
            clone_attributes["linkRefId"] = route_link_ids[int(link_index)]
            transit_stops.append(ET.Element(source_stop.tag, clone_attributes))
            stop.set("refId", clone_id)
            audit.append({
                "transit_route_id": route.get("id"), "stop_sequence": sequence,
                "source_stop_facility_id": source_stop_id, "scenario_stop_facility_id": clone_id,
                "source_link_id": source_stop.get("linkRefId"),
                "assigned_link_id": route_link_ids[int(link_index)], "assigned_link_index": int(link_index),
                "assignment_distance_m": float(distance), "closed_route_repaired": closed_route_repair,
                "repair_method": "ordered_route_specific_stop_link_assignment",
            })
    with gzip.open(destination, "wt", encoding="utf-8", newline="\n") as handle:
        handle.write('<?xml version="1.0" encoding="utf-8"?>\n')
        handle.write('<!DOCTYPE transitSchedule SYSTEM "http://www.matsim.org/files/dtd/transitSchedule_v2.dtd">\n')
        handle.write(ET.tostring(root, encoding="unicode"))
    result = pd.DataFrame(audit)
    result.to_csv(audit_path, index=False, encoding="utf-8-sig")
    return result


def write_config(path: Path, inputs: dict[str, Path], output: Path) -> None:
    output = output.resolve()
    network = inputs["network"].resolve().as_posix()
    schedule = (output / "transitSchedule_5pct.xml.gz").resolve().as_posix()
    config = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE config SYSTEM "http://www.matsim.org/files/dtd/config_v2.dtd">
<config>
  <module name="global"><param name="coordinateSystem" value="EPSG:32650"/><param name="numberOfThreads" value="8"/></module>
  <module name="network"><param name="inputNetworkFile" value="{network}"/></module>
  <module name="plans"><param name="inputPlansFile" value="{(output / 'plans_unrouted_5pct.xml.gz').as_posix()}"/></module>
  <module name="facilities"><param name="inputFacilitiesFile" value="{(output / 'facilities_5pct.xml.gz').as_posix()}"/></module>
  <module name="vehicles"><param name="vehiclesFile" value="{(output / 'privateVehicles_5pct.xml.gz').as_posix()}"/></module>
  <module name="transit"><param name="useTransit" value="true"/><param name="transitScheduleFile" value="{schedule}"/><param name="vehiclesFile" value="{(output / 'transitVehicles_5pct.xml.gz').as_posix()}"/><param name="transitModes" value="bus,gmb,train,light_rail"/></module>
  <module name="qsim"><param name="startTime" value="00:00:00"/><param name="endTime" value="30:00:00"/><param name="flowCapacityFactor" value="0.05"/><param name="storageCapacityFactor" value="0.05"/><param name="mainMode" value="car"/><param name="vehiclesSource" value="fromVehiclesData"/></module>
  <module name="routing"><param name="networkModes" value="car"/><param name="accessEgressType" value="accessEgressModeToLink"/><param name="networkRouteConsistencyCheck" value="disable"/></module>
  <module name="controller"><param name="firstIteration" value="0"/><param name="lastIteration" value="0"/><param name="outputDirectory" value="{(output / 'matsim_load_test_output').as_posix()}"/><param name="overwriteFiles" value="deleteDirectoryIfExists"/></module>
  <module name="replanning"><parameterset type="strategysettings"><param name="strategyName" value="ChangeExpBeta"/><param name="weight" value="0.85"/></parameterset><parameterset type="strategysettings"><param name="strategyName" value="ReRoute"/><param name="weight" value="0.15"/><param name="disableAfterIteration" value="80"/></parameterset></module>
  <module name="scoring">
    <parameterset type="modeParams"><param name="mode" value="car"/><param name="constant" value="0"/><param name="marginalUtilityOfTraveling_util_hr" value="-6"/><param name="monetaryDistanceRate" value="-0.0005"/></parameterset>
    <parameterset type="modeParams"><param name="mode" value="pt"/><param name="constant" value="0"/><param name="marginalUtilityOfTraveling_util_hr" value="-6"/></parameterset>
    <parameterset type="modeParams"><param name="mode" value="walk"/><param name="constant" value="0"/><param name="marginalUtilityOfTraveling_util_hr" value="-6"/></parameterset>
    <parameterset type="modeParams"><param name="mode" value="ride"/><param name="constant" value="0"/><param name="marginalUtilityOfTraveling_util_hr" value="-6"/></parameterset>
    <parameterset type="activityParams"><param name="activityType" value="home"/><param name="typicalDuration" value="12:00:00"/></parameterset>
    <parameterset type="activityParams"><param name="activityType" value="work"/><param name="typicalDuration" value="08:30:00"/></parameterset>
    <parameterset type="activityParams"><param name="activityType" value="work_mobile"/><param name="typicalDuration" value="08:00:00"/></parameterset>
    <parameterset type="activityParams"><param name="activityType" value="education_tertiary"/><param name="typicalDuration" value="07:00:00"/></parameterset>
    <parameterset type="activityParams"><param name="activityType" value="school_kindergarten"/><param name="typicalDuration" value="04:00:00"/></parameterset>
    <parameterset type="activityParams"><param name="activityType" value="school_primary"/><param name="typicalDuration" value="07:00:00"/></parameterset>
    <parameterset type="activityParams"><param name="activityType" value="school_secondary"/><param name="typicalDuration" value="07:30:00"/></parameterset>
    <parameterset type="activityParams"><param name="activityType" value="school_special"/><param name="typicalDuration" value="06:00:00"/></parameterset>
    <parameterset type="activityParams"><param name="activityType" value="border"/><param name="typicalDuration" value="00:20:00"/></parameterset>
    <parameterset type="activityParams"><param name="activityType" value="accommodation"/><param name="typicalDuration" value="12:00:00"/></parameterset>
    <parameterset type="activityParams"><param name="activityType" value="primary_activity"/><param name="typicalDuration" value="03:00:00"/></parameterset>
    <parameterset type="activityParams"><param name="activityType" value="secondary_activity"/><param name="typicalDuration" value="04:00:00"/></parameterset>
    <parameterset type="activityParams"><param name="activityType" value="external_activity"/><param name="typicalDuration" value="08:00:00"/></parameterset>
    <parameterset type="activityParams"><param name="activityType" value="school"/><param name="typicalDuration" value="07:00:00"/></parameterset>
    <parameterset type="activityParams"><param name="activityType" value="school_escort"/><param name="typicalDuration" value="00:10:00"/></parameterset>
    <parameterset type="activityParams"><param name="activityType" value="business"/><param name="typicalDuration" value="08:00:00"/></parameterset>
    <parameterset type="activityParams"><param name="activityType" value="leisure"/><param name="typicalDuration" value="03:00:00"/></parameterset>
    <parameterset type="activityParams"><param name="activityType" value="vfr"/><param name="typicalDuration" value="04:00:00"/></parameterset>
    <parameterset type="activityParams"><param name="activityType" value="other"/><param name="typicalDuration" value="03:00:00"/></parameterset>
    <parameterset type="activityParams"><param name="activityType" value="transit"/><param name="typicalDuration" value="02:00:00"/></parameterset>
  </module>
</config>
'''
    path.write_text(config, encoding="utf-8")


def validate_plans_xml(path: Path, facilities: dict[str, Facility]) -> dict[str, int]:
    people = legs = activities = bad_sequences = bad_facilities = 0
    with gzip.open(path, "rb") as handle:
        for event, element in ET.iterparse(handle, events=("end",)):
            tag = element.tag.rsplit("}", 1)[-1]
            if tag == "person":
                people += 1
                plan = next((child for child in element if child.tag.rsplit("}", 1)[-1] == "plan"), None)
                if plan is not None:
                    sequence = [child.tag.rsplit("}", 1)[-1] for child in plan]
                    activities += sequence.count("activity")
                    legs += sequence.count("leg")
                    if not sequence or sequence[0] != "activity" or sequence[-1] != "activity" or any(sequence[i] == sequence[i + 1] for i in range(len(sequence) - 1)):
                        bad_sequences += 1
                    for child in plan:
                        if child.tag.rsplit("}", 1)[-1] == "activity" and child.attrib.get("facility") not in facilities:
                            bad_facilities += 1
                element.clear()
    return {"persons": people, "legs": legs, "activities": activities, "bad_sequences": bad_sequences, "bad_facilities": bad_facilities}


def write_control_validations(
    output: Path,
    residents: pd.DataFrame,
    external_agents: pd.DataFrame,
    work_od: np.ndarray,
    census: pd.DataFrame,
    retention: pd.DataFrame,
    commute_modes: pd.DataFrame,
    school_audit: pd.DataFrame,
    resident_border_audit: pd.DataFrame,
    grid: gpd.GeoDataFrame,
    rate: float,
) -> dict[str, float]:
    validation_dir = output / "validation"
    expansion = 1.0 / rate
    controls = census.merge(retention[["dcca", "fixed_link_population_ratio"]], on="dcca", how="left")
    controls["target_population"] = controls.t_pop * controls.fixed_link_population_ratio.fillna(0)
    modeled = residents.groupby("dcca").size().mul(expansion).rename("modeled_population")
    dcca = controls[["dcca", "dc_eng", "target_population"]].merge(modeled, on="dcca", how="left").fillna({"modeled_population": 0})
    dcca["absolute_error"] = (dcca.modeled_population - dcca.target_population).abs()
    dcca.to_csv(validation_dir / "dcca_population_balance.csv", index=False, encoding="utf-8-sig")

    tcs = residents.groupby("tcs_zone").size().mul(expansion).rename("expanded_population").reset_index()
    tcs.to_csv(validation_dir / "tcs26_population_distribution.csv", index=False, encoding="utf-8-sig")

    work = residents.loc[residents.role.eq("fixed_worker")].copy()
    grid_area = {
        int(row.grid_id): residence_area(str(row.dc_eng)) if str(row.dc_eng) else "unknown"
        for row in grid[["grid_id", "dc_eng"]].itertuples(index=False)
    }
    work["origin_area"] = work.grid_id.map(grid_area).fillna("unknown")
    work["destination_area"] = work.destination_grid_id.map(grid_area).fillna("unknown")
    modeled_area = work.groupby(["origin_area", "destination_area"]).size().mul(expansion).rename("modeled_workers").reset_index()
    modeled_area.to_csv(validation_dir / "work_od_3area_modeled.csv", index=False, encoding="utf-8-sig")
    grid_areas = np.asarray([grid_area.get(index, "unknown") for index in range(work_od.shape[0])], dtype=object)
    target_rows = []
    for origin_area in ["hong_kong_island", "kowloon", "new_territories"]:
        origin_mask = grid_areas == origin_area
        for destination_area in ["hong_kong_island", "kowloon", "new_territories"]:
            destination_mask = grid_areas == destination_area
            target_rows.append({
                "origin_area": origin_area, "destination_area": destination_area,
                "target_workers": float(work_od[origin_mask][:, destination_mask].sum()),
            })
    target_area = pd.DataFrame(target_rows).merge(modeled_area, on=["origin_area", "destination_area"], how="left").fillna({"modeled_workers": 0})
    target_area["absolute_error"] = (target_area.modeled_workers - target_area.target_workers).abs()
    target_area.to_csv(validation_dir / "work_od_3area_target_vs_modeled.csv", index=False, encoding="utf-8-sig")

    target_modes = commute_modes.loc[
        commute_modes.residence_area_3_code.eq("total") & ~commute_modes.mode_code.eq("total")
    ].groupby("mode_code").workers.sum().rename("target_workers")
    modeled_modes = work.groupby("mode_detail").size().mul(expansion).rename("modeled_workers")
    mode_balance = pd.concat([target_modes, modeled_modes], axis=1).fillna(0).rename_axis("mode_code").reset_index()
    mode_balance["absolute_error"] = (mode_balance.modeled_workers - mode_balance.target_workers).abs()
    mode_balance.to_csv(validation_dir / "work_mode_balance.csv", index=False, encoding="utf-8-sig")

    school_balance = school_audit.groupby("student_stage").size().mul(expansion).rename("expanded_students").reset_index()
    school_balance.to_csv(validation_dir / "school_stage_balance.csv", index=False, encoding="utf-8-sig")
    border_balance = resident_border_audit.groupby("control_point").size().mul(expansion).rename("expanded_departures").reset_index()
    border_balance.to_csv(validation_dir / "usual_resident_border_balance.csv", index=False, encoding="utf-8-sig")

    population_wape = float(dcca.absolute_error.sum() / max(dcca.target_population.sum(), 1.0))
    work_area_wape = float(target_area.absolute_error.sum() / max(target_area.target_workers.sum(), 1.0))
    work_mode_wape = float(mode_balance.absolute_error.sum() / max(mode_balance.target_workers.sum(), 1.0))
    metrics = {
        "dcca_population_wape": population_wape,
        "work_3area_wape": work_area_wape,
        "work_mode_wape": work_mode_wape,
        "resident_border_agents": int(len(resident_border_audit)),
        "visitor_day_agents": int(external_agents.population_group.eq("visitor").sum()),
        "mainland_hk_resident_agents": int(external_agents.population_group.eq("mainland_hk_resident").sum()),
    }
    (validation_dir / "control_metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    figure, axes = plt.subplots(1, 3, figsize=(16, 5))
    residents.role.value_counts().head(10).sort_values().plot.barh(ax=axes[0], color="#2878B5")
    axes[0].set_title("Resident agents by role")
    residents.matsim_mode.value_counts().sort_values().plot.bar(ax=axes[1], color="#D9534F")
    axes[1].set_title("Resident agents by MATSim mode")
    axes[1].tick_params(axis="x", rotation=0)
    district_counts = residents.loc[residents.dc_eng.ne("")].groupby("dc_eng").size().sort_values()
    district_counts.plot.barh(ax=axes[2], color="#3A923A")
    axes[2].set_title("Sampled household residents by district")
    for axis in axes:
        axis.grid(axis="x" if axis is not axes[1] else "y", alpha=0.2)
    figure.tight_layout()
    figure.savefig(validation_dir / "agents_validation_summary.png", dpi=180, bbox_inches="tight")
    plt.close(figure)
    return metrics


def main() -> None:
    args = parse_args()
    rng = np.random.default_rng(args.seed)
    inputs = paths(args.data_root, args.work_od)
    require_inputs(inputs)
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    (output / "validation").mkdir(exist_ok=True)
    rate = 0.001 if args.sample_only else SAMPLE_RATE
    resident_target = round(TARGET_FIXED_LINK_POPULATION * rate) if args.sample_only else args.resident_target
    household_target = round(7_265_494 * rate) if args.sample_only else args.household_person_target
    collective_target = resident_target - household_target

    households_full = pd.read_parquet(inputs["households"])
    sampled_households = sample_households(households_full, household_target, rate, rng)
    residents = read_selected_persons(inputs["persons"], sampled_households.household_index.to_numpy())
    grid = gpd.read_file(inputs["grid"]).to_crs("EPSG:32650").sort_values("grid_id").reset_index(drop=True)
    grid_households = pd.read_csv(inputs["grid_households"])
    worldpop = np.load(inputs["worldpop"])
    demos = np.load(inputs["demos"])
    grid_dcca = households_full.groupby("grid_id").dcca.agg(lambda value: int(value.mode().iloc[0])).to_dict()
    grid_tcs = households_full.groupby("grid_id").tcs_zone.agg(lambda value: int(value.mode().iloc[0])).to_dict()
    dc_boundaries = gpd.read_file(inputs["dc_boundaries"])[["dc_eng", "geometry"]].to_crs(grid.crs)
    grid_centers = gpd.GeoDataFrame(
        grid[["grid_id"]].copy(), geometry=grid.geometry.representative_point(), crs=grid.crs
    )
    grid_district_join = gpd.sjoin(grid_centers, dc_boundaries, predicate="within", how="left")
    grid_dc_eng = grid_district_join.set_index("grid_id").dc_eng.fillna("").astype(str).to_dict()
    grid["dc_eng"] = grid.grid_id.map(grid_dc_eng).fillna("")
    collective = build_collective_people(collective_target, worldpop, demos, grid_households, grid_dcca, grid_tcs, rng)
    residents = pd.concat([residents, collective], ignore_index=True, sort=False)
    residents["expansion_weight"] = TARGET_FIXED_LINK_POPULATION / resident_target
    household_names = sampled_households.set_index("household_id")[["dc_eng", "income_band_tcs", "housing_type"]]
    residents = residents.merge(household_names, left_on="household_id", right_index=True, how="left")
    residents["dc_eng"] = residents.dc_eng.fillna("")
    residents.loc[residents.dc_eng.eq(""), "dc_eng"] = residents.loc[residents.dc_eng.eq(""), "grid_id"].map(grid_dc_eng).fillna("")
    residents["role"] = "home_only"
    residents["student_stage"] = ""
    residents["destination_grid_id"] = -1
    residents["destination_facility_id"] = ""
    residents["mode_detail"] = ""
    residents["matsim_mode"] = "walk"
    residents["border_control_point"] = ""

    residents, facilities = assign_home_coordinates(
        sampled_households, residents, grid, inputs["population_raster"], rng, args.skip_raster_home_points
    )
    work_od = np.load(inputs["work_od"]).astype("float64")
    distance = np.load(inputs["distance"], mmap_mode="r")
    residents = assign_student_roles(residents, pd.read_csv(inputs["student_origins"]), rate, rng)
    residents = assign_fixed_workers(residents, work_od, rate, rng)
    census = read_census_dcca(inputs["dcca_xlsx"])
    retention = pd.read_csv(inputs["retention"])
    residents = assign_census_residual_roles(residents, census, retention, rate, rng)
    residents = assign_tertiary_students(residents, pd.read_csv(inputs["study_flows"]), rate, rng)
    pois = load_pois(inputs["pois"], grid)
    residents = choose_work_destinations(
        residents, work_od, pd.read_csv(inputs["commute_modes"]), pois, grid, rng, facilities
    )
    residents, school_audit = choose_school_destinations(
        residents, inputs["student_grid_school"], inputs["schools"], inputs["school_mode_dir"], grid, rng, facilities
    )
    residents = choose_proxy_destinations(residents, distance, work_od, pois, grid, rng, facilities)
    residents = assign_times(residents, rng)
    residents, school_escort_audit = assign_school_escorts(residents)
    ports = pd.read_csv(inputs["tourism"] / "model_control_points_14.csv")
    events = pd.read_parquet(inputs["tourism"] / "resident_border_events.parquet")
    residents, resident_border_audit = select_typical_resident_border_travelers(
        residents, events, ports, grid, rng, facilities, rate
    )
    external_agents, external_plans = build_external_agents(inputs["tourism"], ports, grid, facilities, rng, rate)
    residents, private_vehicles = assign_vehicle_ids(
        residents, inputs["household_vehicles"], set(sampled_households.household_index.astype(int))
    )
    invalid_escort = residents.role.eq("school_escort") & residents.assigned_vehicle_id.eq("")
    invalid_escort_ids = set(residents.loc[invalid_escort, "person_id"].astype(str))
    residents.loc[invalid_escort, ["role", "destination_facility_id", "mode_detail", "matsim_mode"]] = [
        "home_only", "", "", "walk"
    ]
    if not school_escort_audit.empty:
        school_escort_audit["accepted"] = ~school_escort_audit.driver_person_id.astype(str).isin(invalid_escort_ids)
    facilities = snap_facilities(facilities, inputs["network"])

    sampled_households.to_parquet(output / "sampled_households.parquet", index=False)
    residents.to_parquet(output / "sampled_resident_agents.parquet", index=False)
    external_agents.to_parquet(output / "sampled_external_agents.parquet", index=False)
    pd.concat([residents.assign(population_group="resident"), external_agents], ignore_index=True, sort=False).to_parquet(
        output / "sampled_agents.parquet", index=False
    )
    school_audit.to_csv(output / "validation/sampled_student_school_assignments.csv", index=False, encoding="utf-8-sig")
    school_escort_audit.to_csv(output / "validation/school_escort_assignments.csv", index=False, encoding="utf-8-sig")
    resident_border_audit.to_csv(output / "validation/usual_resident_border_assignments.csv", index=False, encoding="utf-8-sig")
    private_vehicles.to_csv(output / "household_vehicle_assignment.csv", index=False, encoding="utf-8-sig")

    write_facilities(output / "facilities_5pct.xml.gz", facilities)
    write_private_vehicles(output / "privateVehicles_5pct.xml.gz", private_vehicles)
    scale_transit_vehicles(inputs["transit_vehicles"], output / "transitVehicles_5pct.xml.gz", rate)
    schedule_repairs = repair_closed_transit_routes(
        inputs["schedule"], inputs["network"], output / "transitSchedule_5pct.xml.gz",
        output / "validation/transit_schedule_closed_route_repairs.csv",
    )
    trip_path = output / "agent_trip_manifest.parquet"
    trip_schema = pa.schema([
        ("person_id", pa.string()), ("leg_sequence", pa.int64()), ("population_group", pa.string()),
        ("role", pa.string()), ("mode", pa.string()), ("mode_detail", pa.string()),
        ("origin_facility_id", pa.string()), ("destination_facility_id", pa.string()),
        ("departure_time_s", pa.float64()), ("expansion_weight", pa.float64()),
    ])
    with pq.ParquetWriter(trip_path, trip_schema, compression="zstd") as trip_writer:
        resident_plans = (resident_plan(row) for _, row in residents.iterrows())
        person_count, leg_count = write_population(
            output / "plans_unrouted_5pct.xml.gz", residents, resident_plans,
            external_agents, external_plans, facilities, trip_writer,
        )
    write_config(output / "config_hong_kong_5pct.xml", inputs, output)
    validation = validate_plans_xml(output / "plans_unrouted_5pct.xml.gz", facilities)
    role_counts = residents.role.value_counts().rename_axis("role").reset_index(name="agents")
    role_counts["expanded_people"] = role_counts.agents * residents.expansion_weight.iloc[0]
    role_counts.to_csv(output / "validation/resident_role_counts.csv", index=False, encoding="utf-8-sig")
    mode_counts = pd.concat([
        residents[["matsim_mode", "mode_detail"]], external_agents[["matsim_mode", "mode_detail"]]
    ]).value_counts().rename("agents").reset_index()
    mode_counts.to_csv(output / "validation/mode_counts.csv", index=False, encoding="utf-8-sig")
    facility_audit = pd.DataFrame([vars(value) for value in facilities.values()])
    facility_audit.to_parquet(output / "validation/facility_link_audit.parquet", index=False)
    control_metrics = write_control_validations(
        output, residents, external_agents, work_od, census, retention,
        pd.read_csv(inputs["commute_modes"]), school_audit, resident_border_audit, grid, rate,
    )
    summary = {
        "scenario": "hong_kong_typical_weekday_5pct_v1",
        "seed": args.seed, "sample_rate": rate,
        "fixed_link_population_control": TARGET_FIXED_LINK_POPULATION,
        "resident_agents": int(len(residents)), "household_resident_agents": int(len(residents) - len(collective)),
        "collective_resident_agents": int(len(collective)), "visitor_day_agents": int(external_agents.population_group.eq("visitor").sum()),
        "mainland_hk_resident_agents": int(external_agents.population_group.eq("mainland_hk_resident").sum()),
        "total_agents": int(person_count), "total_legs": int(leg_count), "facilities": len(facilities),
        "private_vehicle_records": int(len(private_vehicles)), "work_od_source": str(inputs["work_od"]),
        "school_escort_drivers": int(school_escort_audit.accepted.sum()) if "accepted" in school_escort_audit else 0,
        "school_escort_rejected_no_vehicle": int((~school_escort_audit.accepted).sum()) if "accepted" in school_escort_audit else 0,
        "closed_transit_routes_repaired": int(schedule_repairs.closed_route_repaired.groupby(schedule_repairs.transit_route_id).max().sum()),
        "route_stop_occurrences_rebound": int(len(schedule_repairs)),
        "route_stop_assignment_p95_m": float(schedule_repairs.assignment_distance_m.quantile(0.95)),
        "route_stop_assignment_max_m": float(schedule_repairs.assignment_distance_m.max()),
        "work_od_total": float(work_od.sum()), "student_assignment_source": str(inputs["student_grid_school"]),
        "plans_validation": validation,
        "control_metrics": control_metrics,
        "role_counts": {str(key): int(value) for key, value in residents.role.value_counts().items()},
        "limitations": [
            "Resident discretionary tours are not generated without resident TCS trip-rate controls.",
            "Mobile-work and tertiary destination points are model proxies and are audited separately.",
            "Ride represents taxi/private passenger/school-bus demand without explicit operating vehicles.",
            "Ferry and tram observed mode labels are routed on the available bus/MTR/LRT transit supply.",
            "The unrouted population must pass the MATSim load/routing check before plans_routed_5pct.xml.gz is promoted.",
        ],
        "outputs": {
            "plans_unrouted": str(output / "plans_unrouted_5pct.xml.gz"),
            "facilities": str(output / "facilities_5pct.xml.gz"),
            "private_vehicles": str(output / "privateVehicles_5pct.xml.gz"),
            "transit_vehicles": str(output / "transitVehicles_5pct.xml.gz"),
            "transit_schedule": str(output / "transitSchedule_5pct.xml.gz"),
            "config": str(output / "config_hong_kong_5pct.xml"),
        },
    }
    (output / "generation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: summary[key] for key in ["resident_agents", "visitor_day_agents", "mainland_hk_resident_agents", "total_agents", "total_legs"]}, indent=2))


if __name__ == "__main__":
    main()
