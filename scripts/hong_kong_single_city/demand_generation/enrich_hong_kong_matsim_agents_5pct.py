#!/usr/bin/env python3
"""Add TCS-controlled resident discretionary tours and mode choice to HK plans.

This script preserves the calibrated work, school, and border activities in the
5% v1 population. It fills the gap between those mandatory mechanized legs and
the TCS 2022 all-purpose mechanized-trip control with home-based-other (HBO) and
non-home-based/employers-business (NHB+EB) activity legs. Destinations use the
integrated Hong Kong POI layer and TCS 26-zone production/attraction controls.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import shutil
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pyproj import Transformer
from scipy import sparse
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree


ROOT = Path(__file__).resolve().parents[3]
WINDOWS_DATA_ROOT = Path(r"F:\Matsim\matsim-example-project\data")
DEFAULT_DATA_ROOT = WINDOWS_DATA_ROOT if WINDOWS_DATA_ROOT.exists() else ROOT / "data"
DEFAULT_V1 = DEFAULT_DATA_ROOT / "matsim_agents/hongkong/typical_weekday_5pct_v1"
DEFAULT_OUTPUT = DEFAULT_DATA_ROOT / "matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice"
DEFAULT_SUPPLY = DEFAULT_DATA_ROOT / (
    "transit/hongkong/processed/"
    "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_ferry_core_v1_cap010"
)

SAMPLE_RATE = 0.05
SEED = 20260723
TCS_ALL_PURPOSE_TRIPS = 12_363_000
TCS_HBO_TRIPS = 5_139_000
TCS_NHB_EB_TRIPS = 959_000

TCS_ZONE_NAMES = [
    "Central & Western", "Wan Chai", "Eastern", "Southern", "Yau Ma Tei",
    "Mong Kok", "Sham Shui Po", "Kowloon City", "Kwun Tong", "Wong Tai Sin",
    "Tsuen Wan", "Kwai Chung", "Tsing Yi", "Tuen Mun", "Yuen Long",
    "Tin Shui Wai", "Tai Po", "Fanling/Sheung Shui", "Sha Tin", "Ma On Shan",
    "Tseung Kwan O", "North Lantau", "NWNT (Other Area)", "NENT (Other Area)",
    "SENT (Other Area)", "SWNT (Other Area)",
]

# TCS 2022 Final Report Appendix Table A.2, in thousands of mechanized trips.
TCS_HBO_PRODUCTION = np.asarray([
    319, 210, 498, 227, 155, 97, 316, 337, 389, 270, 217, 173, 129,
    236, 95, 91, 145, 108, 359, 134, 264, 50, 168, 92, 48, 9,
], dtype="float64")
TCS_HBO_ATTRACTION = np.asarray([
    313, 540, 322, 175, 480, 300, 364, 306, 312, 157, 224, 147, 60,
    238, 183, 43, 182, 99, 305, 66, 157, 47, 66, 24, 20, 7,
], dtype="float64")
TCS_NHB_PRODUCTION = np.asarray([
    82, 60, 60, 21, 81, 48, 69, 77, 80, 40, 39, 35, 10, 27, 23, 13,
    17, 11, 60, 13, 40, 18, 13, 6, 17, 2,
], dtype="float64")
TCS_NHB_ATTRACTION = np.asarray([
    56, 83, 48, 21, 96, 70, 84, 66, 69, 35, 37, 39, 10, 33, 15, 16,
    15, 14, 55, 13, 53, 11, 4, 7, 7, 1,
], dtype="float64")

# TCS Appendix A.3 HBO boardings mapped to MATSim main modes.
TCS_HBO_MODE_WEIGHTS = {"pt": 3_972.0, "car": 1_055.0, "ride": 550.0}

PURPOSE_CATEGORIES = {
    "shopping": {
        "retail", "livelihood shop", "clothes shop", "supermarket",
        "houseware shop", "boutique", "bicycle shop",
    },
    "dining": {"restaurant", "fast food", "cafe", "food court", "ice cream", "bar"},
    "leisure": {"tourism", "sport", "garden", "cinema and theatre", "religion"},
    "social": {"restaurant", "cafe", "garden", "religion", "residential"},
    "medical": {"health"},
    "personal_business": {
        "service", "finance", "government", "beauty shop", "travel agency",
    },
}
ACTIVITY_TYPICAL_DURATION = {
    "shopping": "01:30:00",
    "dining": "01:15:00",
    "leisure": "02:30:00",
    "social": "02:00:00",
    "medical": "01:30:00",
    "personal_business": "01:15:00",
}
ACTIVITY_DURATION_SECONDS = {
    "shopping": 75 * 60,
    "dining": 70 * 60,
    "leisure": 150 * 60,
    "social": 120 * 60,
    "medical": 90 * 60,
    "personal_business": 75 * 60,
}


@dataclass(frozen=True)
class FacilityRecord:
    facility_id: str
    x: float
    y: float
    link_id: str
    activity_types: tuple[str, ...]
    source: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--v1-dir", type=Path, default=DEFAULT_V1)
    parser.add_argument("--supply-dir", type=Path, default=DEFAULT_SUPPLY)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--sample-rate", type=float, default=SAMPLE_RATE)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def largest_remainder(values: np.ndarray, total: int) -> np.ndarray:
    values = np.maximum(np.nan_to_num(np.asarray(values, dtype="float64")), 0.0)
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


def ipf(seed: np.ndarray, rows: np.ndarray, cols: np.ndarray, iterations: int = 500) -> np.ndarray:
    matrix = np.maximum(np.asarray(seed, dtype="float64"), 1e-12)
    rows = np.asarray(rows, dtype="float64")
    cols = np.asarray(cols, dtype="float64")
    if not math.isclose(float(rows.sum()), float(cols.sum()), abs_tol=1e-6):
        raise ValueError("IPF row and column controls have different totals")
    for _ in range(iterations):
        row_sum = matrix.sum(axis=1)
        matrix *= np.divide(rows, row_sum, out=np.zeros_like(rows), where=row_sum > 0)[:, None]
        col_sum = matrix.sum(axis=0)
        matrix *= np.divide(cols, col_sum, out=np.zeros_like(cols), where=col_sum > 0)[None, :]
        if max(np.abs(matrix.sum(axis=1) - rows).max(), np.abs(matrix.sum(axis=0) - cols).max()) < 1e-8:
            break
    return matrix


def integerize_matrix(matrix: np.ndarray, rows: np.ndarray, cols: np.ndarray) -> np.ndarray:
    rows = np.asarray(rows, dtype="int64")
    cols = np.asarray(cols, dtype="int64")
    result = np.floor(matrix).astype("int64")
    row_need = rows - result.sum(axis=1)
    col_need = cols - result.sum(axis=0)
    fractions = matrix - result
    order = np.argsort(fractions, axis=None)[::-1]
    for flat in order:
        if row_need.sum() == 0:
            break
        row, col = np.unravel_index(int(flat), matrix.shape)
        if row_need[row] > 0 and col_need[col] > 0:
            result[row, col] += 1
            row_need[row] -= 1
            col_need[col] -= 1
    while row_need.sum() > 0:
        row = int(np.flatnonzero(row_need > 0)[0])
        candidates = np.flatnonzero(col_need > 0)
        col = int(candidates[np.argmax(matrix[row, candidates])])
        amount = int(min(row_need[row], col_need[col]))
        result[row, col] += amount
        row_need[row] -= amount
        col_need[col] -= amount
    if not np.array_equal(result.sum(axis=1), rows) or not np.array_equal(result.sum(axis=0), cols):
        raise RuntimeError("Integer matrix does not preserve margins")
    return result


def zone_distance_matrix(residents: pd.DataFrame) -> np.ndarray:
    centers = (
        residents.loc[residents.tcs_zone.between(1, 26)]
        .groupby("tcs_zone")[["home_x", "home_y"]].mean()
        .reindex(range(1, 27))
    )
    if centers.isna().any().any():
        raise ValueError("Cannot calculate all 26 TCS zone centers")
    xy = centers.to_numpy(dtype="float64")
    return np.sqrt(np.sum((xy[:, None, :] - xy[None, :, :]) ** 2, axis=2))


def choose_residents_by_zone(
    residents: pd.DataFrame,
    zone_counts: np.ndarray,
    driver_person_ids: set[str],
    target_driver_tours: int,
    rng: np.random.Generator,
) -> pd.DataFrame:
    excluded_roles = {"usual_resident_border", "school_escort", "work_outside_hk"}
    eligible = residents.loc[
        residents.tcs_zone.between(1, 26)
        & ~residents.role.isin(excluded_roles)
        & residents.age.ge(5)
    ].copy()
    selected_indices: list[int] = []
    for zone, count in enumerate(zone_counts, start=1):
        if int(count) <= 0:
            continue
        candidates = eligible.index[eligible.tcs_zone.eq(zone)].to_numpy(dtype="int64")
        if len(candidates) < int(count):
            raise RuntimeError(f"TCS zone {zone} has only {len(candidates)} eligible residents for {count} tours")
        role = residents.loc[candidates, "role"].astype(str)
        age = residents.loc[candidates, "age"].to_numpy(dtype="float64")
        priority = np.ones(len(candidates), dtype="float64")
        priority += np.where(role.eq("home_only"), 2.5, 0.0)
        priority += np.where(role.eq("work_home"), 2.0, 0.0)
        priority += np.where(age >= 65, 1.2, 0.0)
        priority += np.where(role.isin(["fixed_worker", "work_mobile"]), 0.25, 0.0)
        is_driver = residents.loc[candidates, "person_id"].astype(str).isin(driver_person_ids).to_numpy()
        priority += np.where(is_driver, 1.5, 0.0)
        keys = np.log(np.maximum(rng.random(len(candidates)), 1e-12)) / priority
        chosen = candidates[np.argpartition(keys, -int(count))[-int(count):]]
        selected_indices.extend(chosen.tolist())
    selected_set = set(selected_indices)
    selected = residents.loc[selected_indices].copy()
    driver_capacity = np.asarray([
        int(
            eligible.loc[
                eligible.tcs_zone.eq(zone)
                & eligible.person_id.astype(str).isin(driver_person_ids)
            ].shape[0]
        )
        for zone in range(1, 27)
    ], dtype="int64")
    desired_driver = largest_remainder(
        np.minimum(driver_capacity, zone_counts),
        min(int(target_driver_tours), int(np.minimum(driver_capacity, zone_counts).sum())),
    )
    desired_driver = np.minimum(desired_driver, np.minimum(driver_capacity, zone_counts))
    shortfall = int(target_driver_tours - desired_driver.sum())
    while shortfall > 0:
        capacity = np.minimum(driver_capacity, zone_counts) - desired_driver
        candidates = np.flatnonzero(capacity > 0)
        if not len(candidates):
            break
        zone = int(candidates[np.argmax(capacity[candidates])])
        desired_driver[zone] += 1
        shortfall -= 1
    for zone, desired in enumerate(desired_driver, start=1):
        selected_zone = selected.index[selected.tcs_zone.eq(zone)].to_numpy(dtype="int64")
        selected_driver = selected_zone[
            residents.loc[selected_zone, "person_id"].astype(str).isin(driver_person_ids).to_numpy()
        ]
        need = int(desired - len(selected_driver))
        if need <= 0:
            continue
        available_driver = eligible.index[
            eligible.tcs_zone.eq(zone)
            & eligible.person_id.astype(str).isin(driver_person_ids)
            & ~eligible.index.isin(selected_set)
        ].to_numpy(dtype="int64")
        replaceable = selected_zone[
            ~residents.loc[selected_zone, "person_id"].astype(str).isin(driver_person_ids).to_numpy()
        ]
        count = min(need, len(available_driver), len(replaceable))
        if count <= 0:
            continue
        additions = rng.choice(available_driver, size=count, replace=False)
        removals = rng.choice(replaceable, size=count, replace=False)
        selected_set.difference_update(removals.tolist())
        selected_set.update(additions.tolist())
        selected = residents.loc[list(selected_set)].copy()
    return selected.sample(frac=1.0, random_state=int(rng.integers(0, 2**31 - 1)))


def adjust_nhb_zone_controls(
    hbo_attraction: np.ndarray,
    nhb_production: np.ndarray,
    nhb_attraction: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, list[dict[str, int]]]:
    prod = nhb_production.copy().astype("int64")
    attr = nhb_attraction.copy().astype("int64")
    audit: list[dict[str, int]] = []
    for zone in range(26):
        excess = int(max(prod[zone] + attr[zone] - hbo_attraction[zone], 0))
        if excess <= 0:
            continue
        moved_prod = min(excess, int(prod[zone]))
        prod[zone] -= moved_prod
        remaining = excess - moved_prod
        if remaining:
            attr[zone] -= remaining
        capacity = hbo_attraction - prod - attr
        capacity[zone] = 0
        for _ in range(excess):
            target = int(np.argmax(capacity))
            if capacity[target] <= 0:
                raise RuntimeError("No feasible zone for NHB control adjustment")
            if moved_prod > 0:
                prod[target] += 1
                moved_prod -= 1
            else:
                attr[target] += 1
            capacity[target] -= 1
        audit.append({"zone": zone + 1, "excess_shifted": excess})
    return prod, attr, audit


def assign_zone_sequences(
    selected: pd.DataFrame,
    hbo_attraction: np.ndarray,
    nhb_production: np.ndarray,
    nhb_attraction: np.ndarray,
    zone_distance: np.ndarray,
    rng: np.random.Generator,
) -> pd.DataFrame:
    result = selected.copy()
    first_target_float = (hbo_attraction + nhb_production - nhb_attraction) / 2.0
    first_target = largest_remainder(np.maximum(first_target_float, 0), len(result))
    first_target = np.maximum(first_target, nhb_production)
    difference = int(first_target.sum() - len(result))
    while difference > 0:
        candidates = np.flatnonzero(first_target > nhb_production)
        zone = int(candidates[np.argmax(first_target[candidates] - first_target_float[candidates])])
        first_target[zone] -= 1
        difference -= 1
    origin_counts = result.tcs_zone.value_counts().reindex(range(1, 27), fill_value=0).to_numpy(dtype="int64")
    gravity = np.exp(-zone_distance / 7_500.0)
    np.fill_diagonal(gravity, np.diag(gravity) * 1.35)
    first_matrix = integerize_matrix(ipf(gravity, origin_counts, first_target), origin_counts, first_target)
    first_zone = np.empty(len(result), dtype="int64")
    frame_positions = {index: position for position, index in enumerate(result.index)}
    for origin_zone in range(1, 27):
        people = result.index[result.tcs_zone.eq(origin_zone)].to_numpy(dtype="int64")
        rng.shuffle(people)
        destinations = np.repeat(np.arange(1, 27), first_matrix[origin_zone - 1])
        rng.shuffle(destinations)
        for person_index, destination in zip(people, destinations):
            first_zone[frame_positions[person_index]] = int(destination)
    result["first_zone"] = first_zone

    double_indices: list[int] = []
    actual_double_origin = np.zeros(26, dtype="int64")
    for zone in range(1, 27):
        candidates = result.index[result.first_zone.eq(zone)].to_numpy(dtype="int64")
        count = min(int(nhb_production[zone - 1]), len(candidates))
        if count:
            chosen = rng.choice(candidates, size=count, replace=False)
            double_indices.extend(chosen.tolist())
            actual_double_origin[zone - 1] = count
    shortfall = int(nhb_production.sum() - len(double_indices))
    if shortfall:
        remaining = result.index[~result.index.isin(double_indices)].to_numpy(dtype="int64")
        chosen = rng.choice(remaining, size=shortfall, replace=False)
        double_indices.extend(chosen.tolist())
        for zone, count in result.loc[chosen, "first_zone"].value_counts().items():
            actual_double_origin[int(zone) - 1] += int(count)

    second_target = nhb_attraction.copy()
    if second_target.sum() != len(double_indices):
        second_target = largest_remainder(second_target, len(double_indices))
    second_matrix = integerize_matrix(
        ipf(gravity, actual_double_origin, second_target),
        actual_double_origin,
        second_target,
    )
    result["second_zone"] = -1
    for first in range(1, 27):
        people = np.asarray([index for index in double_indices if int(result.at[index, "first_zone"]) == first], dtype="int64")
        rng.shuffle(people)
        destinations = np.repeat(np.arange(1, 27), second_matrix[first - 1])
        rng.shuffle(destinations)
        for person_index, destination in zip(people, destinations):
            result.at[person_index, "second_zone"] = int(destination)
    return result


def purpose_probabilities(row: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    purposes = np.asarray(list(ACTIVITY_TYPICAL_DURATION), dtype=object)
    role = str(row.role)
    age = int(row.age)
    if role in {"fixed_worker", "work_mobile"}:
        weights = np.asarray([0.28, 0.32, 0.22, 0.08, 0.02, 0.08])
    elif role in {"day_school_student", "tertiary_student"} or age < 25:
        weights = np.asarray([0.20, 0.30, 0.35, 0.12, 0.01, 0.02])
    elif age >= 65:
        weights = np.asarray([0.30, 0.12, 0.20, 0.18, 0.12, 0.08])
    else:
        weights = np.asarray([0.35, 0.20, 0.18, 0.12, 0.05, 0.10])
    return purposes, weights / weights.sum()


def assign_purposes(assignments: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    result = assignments.copy()
    first: list[str] = []
    second: list[str] = []
    for _, row in result.iterrows():
        purposes, probabilities = purpose_probabilities(row)
        first_purpose = str(rng.choice(purposes, p=probabilities))
        first.append(first_purpose)
        if int(row.second_zone) < 0:
            second.append("")
            continue
        conditional = probabilities.copy()
        conditional[purposes == first_purpose] *= 0.25
        if first_purpose != "dining":
            conditional[purposes == "dining"] *= 1.35
        conditional /= conditional.sum()
        second.append(str(rng.choice(purposes, p=conditional)))
    result["first_purpose"] = first
    result["second_purpose"] = second
    return result


def load_pois(
    path: Path,
    grid_path: Path,
    grid_zone_path: Path,
) -> tuple[pd.DataFrame, dict[int, tuple[float, float]], gpd.GeoDataFrame]:
    grid = gpd.read_file(grid_path).to_crs("EPSG:32650").sort_values("grid_id").reset_index(drop=True)
    zone_rows = pd.read_csv(grid_zone_path)
    zone_rows["household_members"] = pd.to_numeric(zone_rows.household_members, errors="coerce").fillna(0)
    grid_zone = (
        zone_rows.sort_values(["grid_id", "household_members"], ascending=[True, False])
        .drop_duplicates("grid_id").set_index("grid_id").tcs_zone.astype(int)
    )
    representatives = grid.geometry.representative_point()
    known = grid.grid_id.map(grid_zone)
    missing = known.isna()
    if missing.any():
        known_xy = np.c_[representatives.loc[~missing].x, representatives.loc[~missing].y]
        nearest = cKDTree(known_xy).query(np.c_[representatives.loc[missing].x, representatives.loc[missing].y])[1]
        known.loc[missing] = known.loc[~missing].to_numpy()[nearest]
    grid["tcs_zone"] = known.astype(int)
    zone_fallback = {
        int(zone): (float(group.geometry.x.mean()), float(group.geometry.y.mean()))
        for zone, group in gpd.GeoDataFrame(
            grid[["tcs_zone"]], geometry=representatives, crs=grid.crs
        ).groupby("tcs_zone")
    }

    pois = pd.read_csv(path, low_memory=False)
    lon_col = "longitude" if "longitude" in pois else "lon"
    lat_col = "latitude" if "latitude" in pois else "lat"
    pois[lon_col] = pd.to_numeric(pois[lon_col], errors="coerce")
    pois[lat_col] = pd.to_numeric(pois[lat_col], errors="coerce")
    pois = pois.loc[pois[lon_col].notna() & pois[lat_col].notna()].copy()
    transformer = Transformer.from_crs("EPSG:4326", grid.crs, always_xy=True)
    pois["x"], pois["y"] = transformer.transform(pois[lon_col].to_numpy(), pois[lat_col].to_numpy())
    points = gpd.GeoDataFrame(
        pois[["poi_uid"]].copy(), geometry=gpd.points_from_xy(pois.x, pois.y), crs=grid.crs
    )
    joined = gpd.sjoin(points, grid[["grid_id", "tcs_zone", "geometry"]], predicate="within", how="inner")
    pois = pois.loc[joined.index].copy()
    pois["grid_id"] = joined.grid_id.to_numpy(dtype="int64")
    pois["tcs_zone"] = joined.tcs_zone.to_numpy(dtype="int64")
    pois["wedan_category"] = pois.wedan_category.fillna("").astype(str).str.lower()
    pois["poi_uid"] = pois.poi_uid.astype(str)
    pois["source_priority"] = pd.to_numeric(pois.source_priority, errors="coerce").fillna(2)
    return pois, zone_fallback, grid


def build_poi_facilities(
    assignments: pd.DataFrame,
    pois: pd.DataFrame,
    zone_fallback: dict[int, tuple[float, float]],
    network_path: Path,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, dict[str, FacilityRecord]]:
    pools: dict[tuple[int, str], pd.DataFrame] = {}
    for purpose, categories in PURPOSE_CATEGORIES.items():
        subset = pois.loc[pois.wedan_category.isin(categories)]
        for zone, group in subset.groupby("tcs_zone"):
            pools[(int(zone), purpose)] = group
    useful = pois.loc[pois.wedan_category.ne("")]
    zone_any = {int(zone): group for zone, group in useful.groupby("tcs_zone")}
    facilities: dict[str, FacilityRecord] = {}
    result = assignments.copy()
    for prefix in ["first", "second"]:
        facility_ids: list[str] = []
        for _, row in result.iterrows():
            zone = int(row[f"{prefix}_zone"])
            purpose = str(row[f"{prefix}_purpose"])
            if zone < 1 or not purpose:
                facility_ids.append("")
                continue
            candidates = pools.get((zone, purpose), zone_any.get(zone))
            if candidates is not None and len(candidates):
                priority = np.where(candidates.source_priority.to_numpy(dtype=float) <= 1, 1.5, 1.0)
                choice = candidates.iloc[int(rng.choice(np.arange(len(candidates)), p=priority / priority.sum()))]
                token = str(choice.poi_uid).replace(":", "_").replace("/", "_").replace(" ", "_")
                facility_id = f"resident_{purpose}_{token}"
                x, y = float(choice.x), float(choice.y)
                source = "integrated_poi"
            else:
                x, y = zone_fallback[zone]
                facility_id = f"resident_{purpose}_tcs_zone_{zone:02d}"
                source = "tcs_zone_representative_fallback"
            facilities.setdefault(
                facility_id,
                FacilityRecord(facility_id, x, y, "", (purpose,), source),
            )
            facility_ids.append(facility_id)
        result[f"{prefix}_facility_id"] = facility_ids
    facilities = snap_new_facilities(facilities, network_path)
    return result, facilities


def build_car_link_index(network_path: Path) -> tuple[np.ndarray, np.ndarray]:
    with gzip.open(network_path, "rb") as handle:
        root = ET.parse(handle).getroot()
    nodes = {
        element.attrib["id"]: (float(element.attrib["x"]), float(element.attrib["y"]))
        for element in root.iter() if element.tag.rsplit("}", 1)[-1] == "node"
    }
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
    graph = sparse.csr_matrix((np.ones(len(records)), (rows, cols)), shape=(len(nodes), len(nodes)))
    count, labels = connected_components(graph, directed=True, connection="strong")
    largest = int(np.argmax(np.bincount(labels, minlength=count)))
    retained = [
        record for record in records
        if labels[node_index[record[1]]] == largest and labels[node_index[record[2]]] == largest
    ]
    return (
        np.asarray([record[0] for record in retained], dtype=object),
        np.asarray([record[3] for record in retained], dtype="float64"),
    )


def snap_new_facilities(
    facilities: dict[str, FacilityRecord],
    network_path: Path,
) -> dict[str, FacilityRecord]:
    link_ids, link_xy = build_car_link_index(network_path)
    keys = list(facilities)
    distances, positions = cKDTree(link_xy).query(
        np.asarray([[facilities[key].x, facilities[key].y] for key in keys]), k=1
    )
    result: dict[str, FacilityRecord] = {}
    for key, distance, position in zip(keys, distances, positions):
        item = facilities[key]
        source = item.source if distance <= 1_000 else f"{item.source};long_snap_{distance:.1f}m"
        result[key] = FacilityRecord(
            item.facility_id, item.x, item.y, str(link_ids[int(position)]),
            item.activity_types, source,
        )
    return result


def assign_modes(
    assignments: pd.DataFrame,
    driver_vehicle: dict[str, str],
    rng: np.random.Generator,
) -> pd.DataFrame:
    result = assignments.copy()
    result["new_leg_count"] = np.where(result.second_zone.ge(1), 3, 2)
    total_legs = int(result.new_leg_count.sum())
    weights = np.asarray(list(TCS_HBO_MODE_WEIGHTS.values()), dtype="float64")
    mode_targets = largest_remainder(weights, total_legs)
    target = dict(zip(TCS_HBO_MODE_WEIGHTS, mode_targets))
    result["initial_discretionary_mode"] = "pt"

    eligible = result.index[result.person_id.astype(str).isin(driver_vehicle)].to_numpy(dtype="int64")
    rng.shuffle(eligible)
    cumulative = 0
    car_indices: list[int] = []
    for index in eligible:
        if cumulative >= target["car"]:
            break
        car_indices.append(int(index))
        cumulative += int(result.at[index, "new_leg_count"])
    result.loc[car_indices, "initial_discretionary_mode"] = "car"

    remaining = result.index[~result.index.isin(car_indices)].to_numpy(dtype="int64")
    rng.shuffle(remaining)
    cumulative = 0
    ride_indices: list[int] = []
    for index in remaining:
        if cumulative >= target["ride"]:
            break
        ride_indices.append(int(index))
        cumulative += int(result.at[index, "new_leg_count"])
    result.loc[ride_indices, "initial_discretionary_mode"] = "ride"
    return result


def assign_times(assignments: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    result = assignments.copy()
    starts: list[float] = []
    first_ends: list[float] = []
    second_ends: list[float] = []
    for _, row in result.iterrows():
        role = str(row.role)
        age = int(row.age)
        if role in {"fixed_worker", "work_mobile"}:
            base = max(float(row.return_time_s) + 75 * 60, 18.0 * 3600)
            start = float(np.clip(rng.normal(base, 35 * 60), 17 * 3600, 22.0 * 3600))
        elif role in {"day_school_student", "tertiary_student"}:
            base = max(float(row.return_time_s) + 45 * 60, 16.0 * 3600)
            start = float(np.clip(rng.normal(base, 35 * 60), 15 * 3600, 21.5 * 3600))
        elif age >= 65:
            start = float(np.clip(rng.normal(10.5 * 3600, 75 * 60), 8.5 * 3600, 15 * 3600))
        else:
            start = float(np.clip(rng.normal(13.5 * 3600, 120 * 60), 9 * 3600, 18 * 3600))
        first_duration = ACTIVITY_DURATION_SECONDS[str(row.first_purpose)]
        first_end = start + 40 * 60 + first_duration
        second_end = math.nan
        if int(row.second_zone) >= 1:
            second_duration = ACTIVITY_DURATION_SECONDS[str(row.second_purpose)]
            second_end = min(first_end + 40 * 60 + second_duration, 25.5 * 3600)
        starts.append(start)
        first_ends.append(first_end)
        second_ends.append(second_end)
    result["tour_departure_time_s"] = starts
    result["first_activity_end_time_s"] = first_ends
    result["second_activity_end_time_s"] = second_ends
    result["activity_pattern"] = np.where(
        result.second_zone.ge(1),
        "home-primary-secondary-home",
        "home-primary-home",
    )
    return result


def read_facilities(path: Path) -> dict[str, FacilityRecord]:
    with gzip.open(path, "rb") as handle:
        root = ET.parse(handle).getroot()
    result: dict[str, FacilityRecord] = {}
    for element in root:
        if element.tag.rsplit("}", 1)[-1] != "facility":
            continue
        types = tuple(
            child.attrib["type"] for child in element
            if child.tag.rsplit("}", 1)[-1] == "activity"
        )
        result[element.attrib["id"]] = FacilityRecord(
            element.attrib["id"], float(element.attrib["x"]), float(element.attrib["y"]),
            element.attrib.get("linkId", ""), types, "v1",
        )
    return result


def write_facilities(
    path: Path,
    old: dict[str, FacilityRecord],
    new: dict[str, FacilityRecord],
) -> None:
    combined = dict(old)
    combined.update(new)
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as handle:
        handle.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        handle.write('<!DOCTYPE facilities SYSTEM "http://www.matsim.org/files/dtd/facilities_v1.dtd">\n')
        handle.write('<facilities name="hong_kong_5pct_v2_activity_modechoice">\n')
        for item in combined.values():
            handle.write(
                f'  <facility id={quoteattr(item.facility_id)} x="{item.x:.3f}" y="{item.y:.3f}" '
                f'linkId={quoteattr(item.link_id)}>\n'
            )
            for activity_type in item.activity_types:
                handle.write(f'    <activity type={quoteattr(activity_type)}/>\n')
            handle.write('  </facility>\n')
        handle.write('</facilities>\n')


def format_time(seconds: float | int | None) -> str | None:
    if seconds is None or not np.isfinite(seconds):
        return None
    seconds = max(0, int(round(float(seconds))))
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def set_person_attribute(person: ET.Element, name: str, value: str) -> None:
    attributes = next(
        child for child in person
        if child.tag.rsplit("}", 1)[-1] == "attributes"
    )
    existing = next(
        (child for child in attributes if child.attrib.get("name") == name),
        None,
    )
    if existing is None:
        existing = ET.SubElement(
            attributes, "attribute",
            {"name": name, "class": "java.lang.String"},
        )
    existing.text = value


def append_discretionary_tour(
    person: ET.Element,
    assignment: pd.Series,
    facilities: dict[str, FacilityRecord],
) -> None:
    plan = next(
        child for child in person
        if child.tag.rsplit("}", 1)[-1] == "plan" and child.attrib.get("selected", "yes") == "yes"
    )
    last = plan[-1]
    if last.tag.rsplit("}", 1)[-1] != "activity" or last.attrib.get("type") != "home":
        raise ValueError(f"Person {person.attrib['id']} does not end at home")
    final_home = ET.Element(last.tag, dict(last.attrib))
    final_home.attrib.pop("end_time", None)
    last.set("end_time", format_time(assignment.tour_departure_time_s))
    mode = str(assignment.initial_discretionary_mode)
    first = facilities[str(assignment.first_facility_id)]
    ET.SubElement(plan, "leg", {"mode": mode})
    ET.SubElement(plan, "activity", {
        "type": str(assignment.first_purpose),
        "facility": first.facility_id,
        "link": first.link_id,
        "x": f"{first.x:.3f}",
        "y": f"{first.y:.3f}",
        "end_time": format_time(assignment.first_activity_end_time_s),
    })
    if int(assignment.second_zone) >= 1:
        second = facilities[str(assignment.second_facility_id)]
        ET.SubElement(plan, "leg", {"mode": mode})
        ET.SubElement(plan, "activity", {
            "type": str(assignment.second_purpose),
            "facility": second.facility_id,
            "link": second.link_id,
            "x": f"{second.x:.3f}",
            "y": f"{second.y:.3f}",
            "end_time": format_time(assignment.second_activity_end_time_s),
        })
    ET.SubElement(plan, "leg", {"mode": mode})
    plan.append(final_home)
    set_person_attribute(person, "activityPattern", str(assignment.activity_pattern))
    set_person_attribute(person, "initialDiscretionaryMode", mode)


def write_plans(
    source: Path,
    destination: Path,
    assignments: pd.DataFrame,
    facilities: dict[str, FacilityRecord],
    driver_vehicle: dict[str, str],
    trip_manifest: Path,
) -> dict[str, int]:
    assignment_lookup = assignments.set_index("person_id")
    schema = pa.schema([
        ("person_id", pa.string()), ("leg_sequence", pa.int64()),
        ("population_group", pa.string()), ("role", pa.string()),
        ("mode", pa.string()), ("origin_type", pa.string()), ("destination_type", pa.string()),
        ("origin_facility_id", pa.string()), ("destination_facility_id", pa.string()),
        ("departure_time_s", pa.float64()), ("is_discretionary", pa.bool_()),
    ])
    people = legs = activities = bad_sequences = missing_facilities = 0
    trip_rows: list[dict[str, object]] = []
    with gzip.open(source, "rb") as input_handle, gzip.open(destination, "wt", encoding="utf-8", newline="\n") as output_handle:
        output_handle.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        output_handle.write('<!DOCTYPE population SYSTEM "http://www.matsim.org/files/dtd/population_v6.dtd">\n')
        output_handle.write("<population>\n")
        with pq.ParquetWriter(trip_manifest, schema, compression="zstd") as parquet_writer:
            for _, person in ET.iterparse(input_handle, events=("end",)):
                if person.tag.rsplit("}", 1)[-1] != "person":
                    continue
                person_id = str(person.attrib["id"])
                if person_id in driver_vehicle:
                    set_person_attribute(person, "carAvail", "always")
                    set_person_attribute(person, "assignedVehicleId", driver_vehicle[person_id])
                if person_id in assignment_lookup.index:
                    append_discretionary_tour(person, assignment_lookup.loc[person_id], facilities)
                plan = next(
                    child for child in person
                    if child.tag.rsplit("}", 1)[-1] == "plan" and child.attrib.get("selected", "yes") == "yes"
                )
                sequence = [child.tag.rsplit("}", 1)[-1] for child in plan]
                if (
                    not sequence or sequence[0] != "activity" or sequence[-1] != "activity"
                    or any(sequence[i] == sequence[i + 1] for i in range(len(sequence) - 1))
                ):
                    bad_sequences += 1
                plan_activities = [child for child in plan if child.tag.rsplit("}", 1)[-1] == "activity"]
                plan_legs = [child for child in plan if child.tag.rsplit("}", 1)[-1] == "leg"]
                attributes = next(child for child in person if child.tag.rsplit("}", 1)[-1] == "attributes")
                attribute_values = {child.attrib.get("name"): child.text or "" for child in attributes}
                for sequence_index, leg in enumerate(plan_legs):
                    origin = plan_activities[sequence_index]
                    target = plan_activities[sequence_index + 1]
                    origin_facility = origin.attrib.get("facility", "")
                    target_facility = target.attrib.get("facility", "")
                    if origin_facility not in facilities or target_facility not in facilities:
                        missing_facilities += 1
                    trip_rows.append({
                        "person_id": person_id,
                        "leg_sequence": sequence_index,
                        "population_group": attribute_values.get("subpopulation", ""),
                        "role": attribute_values.get("role", ""),
                        "mode": leg.attrib.get("mode", ""),
                        "origin_type": origin.attrib.get("type", ""),
                        "destination_type": target.attrib.get("type", ""),
                        "origin_facility_id": origin_facility,
                        "destination_facility_id": target_facility,
                        "departure_time_s": float("nan") if "end_time" not in origin.attrib else float(
                            sum(float(part) * factor for part, factor in zip(
                                origin.attrib["end_time"].split(":"), [3600, 60, 1]
                            ))
                        ),
                        "is_discretionary": (
                            origin.attrib.get("type") in ACTIVITY_TYPICAL_DURATION
                            or target.attrib.get("type") in ACTIVITY_TYPICAL_DURATION
                        ),
                    })
                    if len(trip_rows) >= 100_000:
                        parquet_writer.write_table(pa.Table.from_pylist(trip_rows, schema=schema))
                        trip_rows.clear()
                people += 1
                legs += len(plan_legs)
                activities += len(plan_activities)
                output_handle.write(ET.tostring(person, encoding="unicode"))
                output_handle.write("\n")
                person.clear()
            if trip_rows:
                parquet_writer.write_table(pa.Table.from_pylist(trip_rows, schema=schema))
        output_handle.write("</population>\n")
    return {
        "people": people,
        "legs": legs,
        "activities": activities,
        "bad_sequences": bad_sequences,
        "missing_facility_references": missing_facilities,
    }


def config_text(
    output: Path,
    supply: Path,
    v1: Path,
    last_iteration: int,
    plans_name: str,
) -> str:
    strategy_blocks: list[str] = []
    for population in ["resident", "visitor", "mainland_hk_resident"]:
        weights = (
            [("ChangeExpBeta", 0.70, None), ("ReRoute", 0.10, 40),
             ("SubtourModeChoice", 0.15, 40), ("TimeAllocationMutator", 0.05, 40)]
            if population == "resident"
            else [("ChangeExpBeta", 0.75, None), ("ReRoute", 0.10, 40),
                  ("SubtourModeChoice", 0.10, 40), ("TimeAllocationMutator", 0.05, 40)]
        )
        for name, weight, disable in weights:
            disable_param = "" if disable is None else f'<param name="disableAfterIteration" value="{disable}"/>'
            strategy_blocks.append(
                '<parameterset type="strategysettings">'
                f'<param name="strategyName" value="{name}"/>'
                f'<param name="weight" value="{weight}"/>'
                f'<param name="subpopulation" value="{population}"/>'
                f'{disable_param}</parameterset>'
            )
    activity_params = "\n".join(
        f'<parameterset type="activityParams"><param name="activityType" value="{name}"/>'
        f'<param name="typicalDuration" value="{duration}"/></parameterset>'
        for name, duration in {
            "home": "12:00:00", "work": "08:30:00", "work_mobile": "08:00:00",
            "education_tertiary": "07:00:00", "school_kindergarten": "04:00:00",
            "school_primary": "07:00:00", "school_secondary": "07:30:00",
            "school_special": "06:00:00", "border": "00:20:00",
            "accommodation": "12:00:00", "primary_activity": "03:00:00",
            "secondary_activity": "04:00:00", "external_activity": "08:00:00",
            "school": "07:00:00", "school_escort": "00:10:00",
            "business": "08:00:00", "vfr": "04:00:00", "other": "03:00:00",
            "transit": "02:00:00", **ACTIVITY_TYPICAL_DURATION,
        }.items()
    )
    run_name = "load_test" if last_iteration == 0 else "50it"
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE config SYSTEM "http://www.matsim.org/files/dtd/config_v2.dtd">
<config>
  <module name="global"><param name="coordinateSystem" value="EPSG:32650"/><param name="numberOfThreads" value="8"/></module>
  <module name="network"><param name="inputNetworkFile" value="{(supply / 'network.xml.gz').as_posix()}"/></module>
  <module name="plans"><param name="inputPlansFile" value="{(output / plans_name).as_posix()}"/></module>
  <module name="facilities"><param name="inputFacilitiesFile" value="{(output / 'facilities_5pct_v2.xml.gz').as_posix()}"/></module>
  <module name="vehicles"><param name="vehiclesFile" value="{(v1 / 'privateVehicles_5pct.xml.gz').as_posix()}"/></module>
  <module name="transit"><param name="useTransit" value="true"/><param name="transitScheduleFile" value="{(supply / 'transitSchedule_5pct.xml.gz').as_posix()}"/><param name="vehiclesFile" value="{(supply / 'transitVehicles_10pct.xml.gz').as_posix()}"/><param name="transitModes" value="bus,gmb,train,light_rail,ferry"/></module>
  <module name="qsim"><param name="startTime" value="00:00:00"/><param name="endTime" value="30:00:00"/><param name="flowCapacityFactor" value="0.1"/><param name="storageCapacityFactor" value="0.1"/><param name="mainMode" value="car"/><param name="vehiclesSource" value="fromVehiclesData"/><param name="numberOfThreads" value="8"/><param name="stuckTime" value="600"/><param name="removeStuckVehicles" value="true"/></module>
  <module name="routing"><param name="networkModes" value="car"/><param name="accessEgressType" value="accessEgressModeToLink"/><param name="networkRouteConsistencyCheck" value="disable"/></module>
  <module name="controller"><param name="firstIteration" value="0"/><param name="lastIteration" value="{last_iteration}"/><param name="outputDirectory" value="{(output / f'matsim_{run_name}_output').as_posix()}"/><param name="overwriteFiles" value="failIfDirectoryExists"/><param name="writeEventsInterval" value="10"/><param name="writePlansInterval" value="10"/><param name="writeSnapshotsInterval" value="0"/></module>
  <module name="replanning">{''.join(strategy_blocks)}</module>
  <module name="subtourModeChoice"><param name="modes" value="car,pt,walk,ride"/><param name="chainBasedModes" value="car"/><param name="considerCarAvailability" value="true"/><param name="behavior" value="fromSpecifiedModesToSpecifiedModes"/><param name="probaForRandomSingleTripMode" value="0.0"/></module>
  <module name="timeAllocationMutator"><param name="mutationRange" value="1800"/><param name="mutationAffectsDuration" value="true"/><param name="latestActivityEndTime" value="30:00:00"/><param name="mutateAroundInitialEndTimeOnly" value="true"/></module>
  <module name="scoring">
    <parameterset type="modeParams"><param name="mode" value="car"/><param name="constant" value="-0.5"/><param name="marginalUtilityOfTraveling_util_hr" value="-6"/><param name="monetaryDistanceRate" value="-0.0007"/></parameterset>
    <parameterset type="modeParams"><param name="mode" value="pt"/><param name="constant" value="0"/><param name="marginalUtilityOfTraveling_util_hr" value="-6"/></parameterset>
    <parameterset type="modeParams"><param name="mode" value="walk"/><param name="constant" value="0"/><param name="marginalUtilityOfTraveling_util_hr" value="-6"/></parameterset>
    <parameterset type="modeParams"><param name="mode" value="ride"/><param name="constant" value="-1.5"/><param name="marginalUtilityOfTraveling_util_hr" value="-6"/><param name="monetaryDistanceRate" value="-0.0015"/></parameterset>
    {activity_params}
  </module>
</config>
'''


def write_validations(
    output: Path,
    assignments: pd.DataFrame,
    hbo_prod_target: np.ndarray,
    hbo_att_target: np.ndarray,
    nhb_prod_original: np.ndarray,
    nhb_att_original: np.ndarray,
    nhb_prod_adjusted: np.ndarray,
    nhb_att_adjusted: np.ndarray,
) -> dict[str, float]:
    actual_hbo_prod = assignments.tcs_zone.value_counts().reindex(range(1, 27), fill_value=0).to_numpy() * 2
    first = assignments.first_zone.value_counts().reindex(range(1, 27), fill_value=0).to_numpy()
    singles = assignments.loc[assignments.second_zone.lt(1), "first_zone"].value_counts().reindex(range(1, 27), fill_value=0).to_numpy()
    second = assignments.loc[assignments.second_zone.ge(1), "second_zone"].value_counts().reindex(range(1, 27), fill_value=0).to_numpy()
    actual_hbo_att = first + singles + second
    actual_nhb_prod = assignments.loc[assignments.second_zone.ge(1), "first_zone"].value_counts().reindex(range(1, 27), fill_value=0).to_numpy()
    actual_nhb_att = second
    validation = pd.DataFrame({
        "tcs_zone": np.arange(1, 27),
        "district_name": TCS_ZONE_NAMES,
        "hbo_production_target": hbo_prod_target,
        "hbo_production_actual": actual_hbo_prod,
        "hbo_attraction_target": hbo_att_target,
        "hbo_attraction_actual": actual_hbo_att,
        "nhb_production_original_target": nhb_prod_original,
        "nhb_production_feasible_target": nhb_prod_adjusted,
        "nhb_production_actual": actual_nhb_prod,
        "nhb_attraction_original_target": nhb_att_original,
        "nhb_attraction_feasible_target": nhb_att_adjusted,
        "nhb_attraction_actual": actual_nhb_att,
    })
    validation.to_csv(output / "validation/tcs26_discretionary_trip_controls.csv", index=False, encoding="utf-8-sig")
    assignments.role.value_counts().rename_axis("role").reset_index(name="tour_agents").to_csv(
        output / "validation/discretionary_tours_by_role.csv", index=False, encoding="utf-8-sig"
    )
    purpose_values = pd.concat([
        assignments.first_purpose,
        assignments.loc[assignments.second_purpose.ne(""), "second_purpose"],
    ])
    purpose_values.value_counts().rename_axis("purpose").reset_index(name="activity_stops").to_csv(
        output / "validation/discretionary_activity_purpose_counts.csv", index=False, encoding="utf-8-sig"
    )
    mode_legs = assignments.groupby("initial_discretionary_mode").new_leg_count.sum()
    mode_validation = pd.DataFrame({
        "mode": list(TCS_HBO_MODE_WEIGHTS),
        "tcs_a3_boarding_share": np.asarray(list(TCS_HBO_MODE_WEIGHTS.values())) / sum(TCS_HBO_MODE_WEIGHTS.values()),
    })
    mode_validation["initial_leg_count"] = mode_validation["mode"].map(mode_legs).fillna(0).astype(int)
    mode_validation["initial_leg_share"] = mode_validation.initial_leg_count / mode_validation.initial_leg_count.sum()
    mode_validation.to_csv(output / "validation/discretionary_initial_mode_validation.csv", index=False, encoding="utf-8-sig")

    def wape(actual: np.ndarray, target: np.ndarray) -> float:
        return float(np.abs(actual - target).sum() / max(float(target.sum()), 1.0))

    return {
        "hbo_production_wape": wape(actual_hbo_prod, hbo_prod_target),
        "hbo_attraction_wape": wape(actual_hbo_att, hbo_att_target),
        "nhb_production_wape_vs_feasible": wape(actual_nhb_prod, nhb_prod_adjusted),
        "nhb_attraction_wape_vs_feasible": wape(actual_nhb_att, nhb_att_adjusted),
    }


def require(paths: dict[str, Path]) -> None:
    missing = [f"{name}: {path}" for name, path in paths.items() if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing required inputs:\n" + "\n".join(missing))


def main() -> None:
    args = parse_args()
    rng = np.random.default_rng(args.seed)
    output = args.output_dir.resolve()
    key_output = output / "plans_unrouted_5pct_v2.xml.gz"
    if key_output.exists() and not args.overwrite:
        raise FileExistsError(f"{key_output} exists; use --overwrite to replace local v2 outputs")
    output.mkdir(parents=True, exist_ok=True)
    (output / "validation").mkdir(exist_ok=True)
    paths = {
        "v1_plans": args.v1_dir / "plans_unrouted_5pct.xml.gz",
        "v1_facilities": args.v1_dir / "facilities_5pct.xml.gz",
        "v1_residents": args.v1_dir / "sampled_resident_agents.parquet",
        "v1_manifest": args.v1_dir / "agent_trip_manifest.parquet",
        "v1_private_vehicles": args.v1_dir / "privateVehicles_5pct.xml.gz",
        "vehicle_assignment": args.v1_dir / "household_vehicle_assignment.csv",
        "pois": args.data_root / (
            "osm/hongkong/fixed_link_boundary/integrated_pois/"
            "hong_kong_fixed_link_integrated_pois.csv"
        ),
        "grid": args.data_root / (
            "worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/"
            "CityAndRegionSplit/hong_kong_fixed_link_grid/regions.shp"
        ),
        "grid_zone": args.data_root / (
            "matsim_agents/hongkong/synthetic_households_tcs2022/"
            "grid_household_population_summary.csv"
        ),
        "network": args.supply_dir / "network.xml.gz",
        "schedule": args.supply_dir / "transitSchedule_5pct.xml.gz",
        "transit_vehicles": args.supply_dir / "transitVehicles_10pct.xml.gz",
    }
    require(paths)

    residents = pd.read_parquet(paths["v1_residents"])
    manifest = pd.read_parquet(paths["v1_manifest"])
    internal_mechanized = manifest.loc[
        manifest.population_group.eq("resident")
        & manifest["mode"].isin(["car", "pt", "ride"])
        & ~manifest.role.eq("usual_resident_border")
        & ~manifest.origin_facility_id.astype(str).str.startswith("border_")
        & ~manifest.destination_facility_id.astype(str).str.startswith("border_")
    ]
    tcs_target = round(TCS_ALL_PURPOSE_TRIPS * args.sample_rate)
    residual = int(tcs_target - len(internal_mechanized))
    if residual <= 0:
        raise RuntimeError(
            f"Existing internal mechanized legs ({len(internal_mechanized):,}) already exceed "
            f"TCS target ({tcs_target:,})"
        )
    nhb_target = int(round(residual * TCS_NHB_EB_TRIPS / (TCS_HBO_TRIPS + TCS_NHB_EB_TRIPS)))
    if (residual - nhb_target) % 2:
        nhb_target += 1 if nhb_target < residual else -1
    tour_target = (residual - nhb_target) // 2
    hbo_target = 2 * tour_target

    hbo_prod = largest_remainder(TCS_HBO_PRODUCTION, hbo_target)
    if np.any(hbo_prod % 2):
        odd = np.flatnonzero(hbo_prod % 2)
        for left, right in zip(odd[::2], odd[1::2]):
            hbo_prod[left] += 1
            hbo_prod[right] -= 1
    tour_origins = hbo_prod // 2
    hbo_att = largest_remainder(TCS_HBO_ATTRACTION, hbo_target)
    nhb_prod_original = largest_remainder(TCS_NHB_PRODUCTION, nhb_target)
    nhb_att_original = largest_remainder(TCS_NHB_ATTRACTION, nhb_target)
    nhb_prod, nhb_att, adjustment_audit = adjust_nhb_zone_controls(
        hbo_att, nhb_prod_original, nhb_att_original
    )

    vehicle_rows = pd.read_csv(paths["vehicle_assignment"])
    vehicle_rows["vehicle_type_priority"] = np.where(vehicle_rows.vehicle_type.eq("private_car"), 0, 1)
    vehicle_rows = vehicle_rows.sort_values(
        ["driver_person_id", "vehicle_type_priority", "vehicle_sequence"]
    )
    driver_vehicle = (
        vehicle_rows.drop_duplicates("driver_person_id")
        .set_index("driver_person_id").vehicle_id.astype(str).to_dict()
    )
    existing_vehicle = residents.loc[
        residents.assigned_vehicle_id.fillna("").astype(str).ne(""),
        ["person_id", "assigned_vehicle_id"],
    ]
    driver_vehicle.update(
        existing_vehicle.set_index("person_id").assigned_vehicle_id.astype(str).to_dict()
    )
    target_driver_tours = round(
        tour_target * TCS_HBO_MODE_WEIGHTS["car"] / sum(TCS_HBO_MODE_WEIGHTS.values())
    )
    selected = choose_residents_by_zone(
        residents, tour_origins, set(driver_vehicle), target_driver_tours, rng
    )
    assignments = assign_zone_sequences(
        selected, hbo_att, nhb_prod, nhb_att, zone_distance_matrix(residents), rng
    )
    assignments = assign_purposes(assignments, rng)
    pois, zone_fallback, _ = load_pois(paths["pois"], paths["grid"], paths["grid_zone"])
    assignments, new_facilities = build_poi_facilities(
        assignments, pois, zone_fallback, paths["network"], rng
    )

    assignments = assign_modes(assignments, driver_vehicle, rng)
    assignments = assign_times(assignments, rng)
    assignments.to_parquet(output / "resident_discretionary_activity_assignments.parquet", index=False)

    old_facilities = read_facilities(paths["v1_facilities"])
    all_facilities = dict(old_facilities)
    all_facilities.update(new_facilities)
    write_facilities(output / "facilities_5pct_v2.xml.gz", old_facilities, new_facilities)
    shutil.copy2(paths["v1_private_vehicles"], output / "privateVehicles_5pct.xml.gz")
    plan_validation = write_plans(
        paths["v1_plans"], key_output, assignments, all_facilities,
        driver_vehicle, output / "agent_trip_manifest_v2.parquet",
    )
    validation_metrics = write_validations(
        output, assignments, hbo_prod, hbo_att, nhb_prod_original, nhb_att_original,
        nhb_prod, nhb_att,
    )
    pd.DataFrame(adjustment_audit).to_csv(
        output / "validation/nhb_feasibility_adjustments.csv", index=False, encoding="utf-8-sig"
    )
    (output / "config_hong_kong_5pct_v2_activity_modechoice_0it.xml").write_text(
        config_text(output, args.supply_dir.resolve(), output, 0, key_output.name),
        encoding="utf-8",
    )
    (output / "config_hong_kong_5pct_v2_activity_modechoice_50it.xml").write_text(
        config_text(output, args.supply_dir.resolve(), output, 50, "plans_routed_5pct_v2.xml.gz"),
        encoding="utf-8",
    )
    controls = pd.DataFrame({
        "tcs_zone": np.arange(1, 27), "district_name": TCS_ZONE_NAMES,
        "tcs_a2_hbo_production_thousand": TCS_HBO_PRODUCTION,
        "tcs_a2_hbo_attraction_thousand": TCS_HBO_ATTRACTION,
        "tcs_a2_nhb_eb_production_thousand": TCS_NHB_PRODUCTION,
        "tcs_a2_nhb_eb_attraction_thousand": TCS_NHB_ATTRACTION,
    })
    controls.to_csv(output / "tcs2022_appendix_a2_controls.csv", index=False, encoding="utf-8-sig")
    summary = {
        "scenario": "hong_kong_typical_weekday_5pct_v2_activity_modechoice",
        "seed": args.seed,
        "sample_rate": args.sample_rate,
        "tcs_all_purpose_mechanized_target": tcs_target,
        "existing_internal_mechanized_legs": int(len(internal_mechanized)),
        "new_discretionary_mechanized_legs": int(assignments.new_leg_count.sum()),
        "combined_internal_mechanized_legs_before_mode_replanning": int(
            len(internal_mechanized) + assignments.new_leg_count.sum()
        ),
        "discretionary_tour_agents": int(len(assignments)),
        "single_stop_tours": int(assignments.second_zone.lt(1).sum()),
        "two_stop_tours": int(assignments.second_zone.ge(1).sum()),
        "hbo_leg_target": int(hbo_target),
        "nhb_eb_leg_target": int(nhb_target),
        "residents_with_car_available_for_mode_choice": int(
            residents.person_id.astype(str).isin(driver_vehicle).sum()
        ),
        "new_activity_facilities": int(len(new_facilities)),
        "plan_validation": plan_validation,
        "tcs26_validation": validation_metrics,
        "method_notes": [
            "Existing calibrated work, school, escort, and internal border plans are retained.",
            "The discretionary total fills the residual to the TCS 2022 all-purpose mechanized-trip target.",
            "TCS A.2 controls spatial distribution; integrated POIs provide exact activity coordinates.",
            "NHB controls are minimally shifted where a zone-level HBO/NHB endpoint combination is infeasible.",
            "Initial discretionary modes use TCS A.3 HBO boarding shares; final shares are endogenous.",
            "SubtourModeChoice considers car availability and treats car as a chain-based mode.",
            "Resident discretionary purpose shares are transparent role/age priors because TCS publishes HBO aggregate totals, not a full resident purpose split.",
        ],
        "sources": {
            "tcs_report": "https://www.td.gov.hk/filemanager/en/content_5349/tcs2022_eng.pdf",
            "tcs_appendices": "https://www.td.gov.hk/filemanager/en/content_5349/tcs2022app_eng.pdf",
            "v1_population": str(args.v1_dir),
            "integrated_pois": str(paths["pois"]),
            "supply": str(args.supply_dir),
        },
    }
    (output / "generation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        key: summary[key] for key in [
            "existing_internal_mechanized_legs", "new_discretionary_mechanized_legs",
            "combined_internal_mechanized_legs_before_mode_replanning",
            "discretionary_tour_agents", "single_stop_tours", "two_stop_tours",
            "new_activity_facilities",
        ]
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
