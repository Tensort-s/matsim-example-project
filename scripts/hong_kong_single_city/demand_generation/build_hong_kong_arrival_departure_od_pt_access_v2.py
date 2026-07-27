#!/usr/bin/env python3
"""Re-estimate Hong Kong border OD with timetable PT access and activity chains."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from build_hong_kong_arrival_departure_od import (
    MAINLAND_PORTS,
    MODE_SHARES,
    build_hour_profiles,
    load_control_points,
    load_grid_features,
    normalize,
    paths,
    purpose_rows,
    safe_slug,
    save_npz_matrix,
)


ROOT = Path(__file__).resolve().parents[3]
WINDOWS_DATA_ROOT = Path(r"F:\Matsim\matsim-example-project\data")
DEFAULT_DATA_ROOT = WINDOWS_DATA_ROOT if WINDOWS_DATA_ROOT.exists() else ROOT / "data"
WORK_CRS = "EPSG:32650"
PERIODS = ("07:00", "10:00", "13:00", "17:00", "20:00", "22:00")
PERIOD_INDEX = {value: index for index, value in enumerate(PERIODS)}
ZONE_ORDER = (
    "Kowloon",
    "Northwest New Territories",
    "Northeast New Territories",
    "Hong Kong Island",
    "Southwest New Territories",
    "Southeast New Territories",
)
CBTS_ZONE_INCIDENCE = np.asarray([0.454, 0.261, 0.294, 0.167, 0.080, 0.006], dtype="float64")
HOTEL_DISTRICT_ORDER = (
    "Central and Western",
    "Wan Chai",
    "Eastern and Southern",
    "Tsim Sha Tsui",
    "Yau Ma Tei and Mong Kok",
    "Other Kowloon",
    "New Territories",
    "Outlying Islands",
)
PURPOSE_CATEGORY = {
    "sightseeing": {"tourism", "garden", "religion", "cinema and theatre"},
    "leisure": {"tourism", "garden", "sport", "religion", "cinema and theatre", "bar"},
    "shopping": {"retail", "livelihood shop", "clothes shop", "supermarket", "houseware shop", "boutique", "beauty shop"},
    "business": {"office", "finance", "government", "service"},
    "work": {"office", "finance", "government", "service"},
    "transit": {"transit station", "transport"},
    "other": {"restaurant", "fast food", "cafe", "food court", "service"},
    "vfr": set(),
    "school": {"school", "education"},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--prepared-dir", type=Path)
    parser.add_argument("--skim-file", type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--minimum-cohort-flow", type=float, default=0.05)
    parser.add_argument("--ipf-tolerance", type=float, default=1e-9)
    return parser.parse_args()


def model_paths(data_root: Path) -> dict[str, Path]:
    old = data_root / "tourism/hongkong/processed/arrival_departure_od_2026_typical_weekday"
    new = data_root / "tourism/hongkong/processed/arrival_departure_od_2026_typical_weekday_pt_access_v2"
    return {
        "old": old,
        "new": new,
        "dc18": data_root / "boundary/hongkong/2021_Population_Census_Statistics_and_Boundar_SHP/DC_21C_converted.shp",
        "boundary": data_root / "boundary/hongkong/processed/hong_kong_fixed_link_boundary_wgs84.geojson",
        "popular": old / "prepared_inputs/popular_destination_priors.csv",
    }


def unit_normalize(values: np.ndarray) -> np.ndarray:
    values = np.nan_to_num(np.asarray(values, dtype="float64"), nan=0.0, posinf=0.0, neginf=0.0)
    values[values < 0] = 0
    total = float(values.sum())
    if total <= 0:
        raise ValueError("Cannot normalize an empty constrained profile")
    return values / total


def ipf(seed: np.ndarray, rows: np.ndarray, columns: np.ndarray, tolerance: float, iterations: int = 4000) -> np.ndarray:
    seed = np.asarray(seed, dtype="float64")
    rows = np.asarray(rows, dtype="float64")
    columns = np.asarray(columns, dtype="float64")
    if not math.isclose(float(rows.sum()), float(columns.sum()), rel_tol=0, abs_tol=1e-6):
        raise ValueError(f"IPF margins differ: {rows.sum()} != {columns.sum()}")
    allowed = np.isfinite(seed) & (seed > 0)
    if np.any((rows > 0) & ~allowed.any(axis=1)) or np.any((columns > 0) & ~allowed.any(axis=0)):
        raise ValueError("IPF has a positive margin with no allowed seed cells")
    matrix = np.where(allowed, np.maximum(seed, 1e-300), 0.0)
    for _ in range(iterations):
        row_sum = matrix.sum(axis=1)
        matrix *= np.divide(rows, row_sum, out=np.zeros_like(rows), where=row_sum > 0)[:, None]
        col_sum = matrix.sum(axis=0)
        matrix *= np.divide(columns, col_sum, out=np.zeros_like(columns), where=col_sum > 0)[None, :]
        error = max(float(np.max(np.abs(matrix.sum(axis=1) - rows))), float(np.max(np.abs(matrix.sum(axis=0) - columns))))
        if error <= tolerance:
            return matrix
    raise RuntimeError(f"IPF did not converge; final absolute margin error={error}")


def assign_grid_districts(grid: gpd.GeoDataFrame, district_path: Path) -> tuple[gpd.GeoDataFrame, np.ndarray]:
    districts = gpd.read_file(district_path)[["dc_class", "dc_eng", "geometry"]].to_crs(grid.crs)
    centers = gpd.GeoDataFrame(
        {"grid_index": np.arange(len(grid), dtype=int)}, geometry=grid.geometry.centroid, crs=grid.crs
    )
    joined = gpd.sjoin(centers, districts[["dc_eng", "geometry"]], how="left", predicate="within")
    if joined.dc_eng.isna().any():
        missing = joined.dc_eng.isna()
        nearest = gpd.sjoin_nearest(centers.loc[missing], districts[["dc_eng", "geometry"]], how="left")
        lookup = nearest.drop_duplicates("grid_index").set_index("grid_index").dc_eng
        joined.loc[missing, "dc_eng"] = joined.loc[missing, "grid_index"].map(lookup)
    if joined.grid_index.duplicated().any() or joined.dc_eng.isna().any():
        raise ValueError("Every grid must map to exactly one District Council district")
    names = joined.sort_values("grid_index").dc_eng.to_numpy(dtype=str)
    return districts, names


def district_to_zone(name: str) -> str:
    if name in {"Central and Western", "Wan Chai", "Eastern", "Southern"}:
        return "Hong Kong Island"
    if name in {"Yau Tsim Mong", "Sham Shui Po", "Kowloon City", "Wong Tai Sin", "Kwun Tong"}:
        return "Kowloon"
    if name in {"Tuen Mun", "Yuen Long"}:
        return "Northwest New Territories"
    if name in {"North", "Tai Po", "Sha Tin"}:
        return "Northeast New Territories"
    if name == "Sai Kung":
        return "Southeast New Territories"
    if name in {"Tsuen Wan", "Kwai Tsing", "Islands"}:
        return "Southwest New Territories"
    raise ValueError(f"No CBTS six-zone mapping for {name}")


def assign_points_to_grid(points: gpd.GeoDataFrame, grid: gpd.GeoDataFrame) -> np.ndarray:
    projected = points.to_crs(grid.crs)
    joined = gpd.sjoin(projected, grid[["geometry"]], how="left", predicate="within")
    if joined.index_right.isna().any():
        missing = joined.index_right.isna()
        nearest = gpd.sjoin_nearest(projected.loc[missing], grid[["geometry"]], how="left")
        joined.loc[missing, "index_right"] = nearest.index_right.to_numpy()
    return joined.index_right.astype(int).to_numpy()


def map_hotel_district(district: pd.Series, latitude: pd.Series) -> np.ndarray:
    return np.select(
        [
            district.str.contains("Central & Western|Central and Western", case=False, regex=True),
            district.str.contains("Wan Chai", case=False),
            district.str.contains("Eastern|Southern", case=False, regex=True),
            district.str.contains("Yau Tsim Mong", case=False) & (latitude < 22.31),
            district.str.contains("Yau Tsim Mong", case=False),
            district.str.contains("Sham Shui Po|Kowloon City|Kwun Tong|Wong Tai Sin", case=False, regex=True),
            district.str.contains("Islands", case=False),
            district.str.contains("Tsuen Wan|Kwai Tsing|Tuen Mun|Yuen Long|North|Tai Po|Sha Tin|Sai Kung", case=False, regex=True),
        ],
        [
            "Central and Western", "Wan Chai", "Eastern and Southern", "Tsim Sha Tsui",
            "Yau Ma Tei and Mong Kok", "Other Kowloon", "Outlying Islands", "New Territories",
        ],
        default="unmapped",
    )


def load_poi_details(poi_path: Path, grid: gpd.GeoDataFrame) -> tuple[pd.DataFrame, dict[str, np.ndarray], dict[tuple[str, int], dict[str, object]]]:
    poi = pd.read_csv(poi_path, low_memory=False).dropna(subset=["lon", "lat"]).copy()
    poi_geo = gpd.GeoDataFrame(poi, geometry=gpd.points_from_xy(poi.lon, poi.lat), crs="EPSG:4326")
    poi["grid_index"] = assign_points_to_grid(poi_geo, grid)
    poi["category"] = poi.wedan_category.fillna("").astype(str).str.lower()
    poi["hotel_district"] = map_hotel_district(
        poi.district_en.fillna("").astype(str), pd.to_numeric(poi.lat, errors="coerce")
    )
    hotel_weights: dict[str, np.ndarray] = {}
    for district in HOTEL_DISTRICT_ORDER:
        subset = poi[(poi.category == "accommodation") & (poi.hotel_district == district)]
        counts = np.bincount(subset.grid_index, minlength=len(grid)).astype("float64")
        if counts.sum() == 0:
            raise ValueError(f"No integrated hotel POI mapped to {district}")
        hotel_weights[district] = unit_normalize(counts)

    point_lookup: dict[tuple[str, int], dict[str, object]] = {}
    name = poi.name_en.fillna(poi.name_zh).fillna(poi.source_id).astype(str)
    poi["display_name"] = name
    for purpose, categories in PURPOSE_CATEGORY.items():
        if not categories:
            continue
        subset = poi[poi.category.isin(categories)].sort_values(["grid_index", "source_priority", "display_name"])
        for row in subset.drop_duplicates("grid_index").itertuples():
            point_lookup[(purpose, int(row.grid_index))] = {
                "point_id": str(row.poi_uid), "point_name": row.display_name,
                "longitude": float(row.lon), "latitude": float(row.lat), "point_source": str(row.source),
            }
    hotels = poi[poi.category.eq("accommodation")].sort_values(["grid_index", "source_priority", "display_name"])
    for row in hotels.drop_duplicates("grid_index").itertuples():
        point_lookup[("hotel", int(row.grid_index))] = {
            "point_id": str(row.poi_uid), "point_name": row.display_name,
            "longitude": float(row.lon), "latitude": float(row.lat), "point_source": str(row.source),
        }
    return poi, hotel_weights, point_lookup


def apply_district_priors(
    attractions: dict[str, np.ndarray],
    grid_district: np.ndarray,
    popular_path: Path,
) -> tuple[dict[str, np.ndarray], pd.DataFrame]:
    priors = pd.read_csv(popular_path)
    records: list[dict[str, object]] = []
    result = {key: unit_normalize(value) for key, value in attractions.items()}
    district_names = sorted(set(grid_district))
    aliases = {
        "North Lantau/Islands": "Islands",
        "Outlying Islands incl. North Lantau": "Islands",
        "Yau Ma Tei": "Yau Tsim Mong",
        "Mong Kok": "Yau Tsim Mong",
    }
    for purpose, destination_type in [("shopping", "shopping_district"), ("sightseeing", "sightseeing_spot"), ("leisure", "sightseeing_spot")]:
        subset = priors[(priors.destination_type == destination_type) & ~priors.destination_name.eq("Others")].copy()
        subset["district"] = subset.district_hint.replace(aliases)
        subset.loc[subset.district.str.contains("Yau Tsim Mong", na=False), "district"] = "Yau Tsim Mong"
        observed = subset.groupby("district").share.sum().to_dict()
        base = result.get(purpose, result["other"])
        base_district = {name: float(base[grid_district == name].sum()) for name in district_names}
        observed_vector = np.asarray([observed.get(name, 0.0) for name in district_names], dtype="float64")
        base_vector = np.asarray([base_district[name] for name in district_names], dtype="float64")
        if observed_vector.sum() > 0:
            observed_vector /= observed_vector.sum()
            district_target = unit_normalize(0.70 * observed_vector + 0.30 * base_vector)
            adjusted = np.zeros_like(base)
            for name, target in zip(district_names, district_target, strict=True):
                mask = grid_district == name
                local = base[mask]
                adjusted[mask] = target * unit_normalize(local)
                records.append({"purpose": purpose, "district": name, "share": float(target)})
            result[purpose] = unit_normalize(adjusted)
    return result, pd.DataFrame(records)


def calibrate_activity_beta(
    generalized_grid_grid: np.ndarray,
    travel_grid_grid: np.ndarray,
    origin_weights: np.ndarray,
    destination_weights: np.ndarray,
    target_minutes: float = 41.0,
) -> tuple[float, float, str]:
    valid = np.isfinite(generalized_grid_grid) & np.isfinite(travel_grid_grid)
    base = origin_weights[:, None] * destination_weights[None, :]
    base[~valid] = 0.0
    np.fill_diagonal(base, 0.0)

    def modeled(beta: float) -> float:
        weights = base * np.exp(-beta * np.where(valid, generalized_grid_grid, 0.0))
        total = float(weights.sum())
        return float(np.sum(weights * np.where(valid, travel_grid_grid, 0.0))) / max(total, 1e-12) / 60.0

    low, high = 0.0, 0.003
    at_low, at_high = modeled(low), modeled(high)
    if target_minutes >= at_low:
        return low, at_low, "target_above_unpenalized_mean"
    if target_minutes <= at_high:
        return high, at_high, "target_below_high_beta_mean"
    for _ in range(70):
        middle = (low + high) / 2
        value = modeled(middle)
        if value > target_minutes:
            low = middle
        else:
            high = middle
    beta = (low + high) / 2
    return beta, modeled(beta), "calibrated"


def profile(base: np.ndarray, generalized_cost: np.ndarray, beta: float, mask: np.ndarray | None = None) -> np.ndarray:
    valid = np.isfinite(generalized_cost) & (base > 0)
    if mask is not None:
        valid &= mask
    weights = np.zeros_like(base, dtype="float64")
    weights[valid] = base[valid] * np.exp(-beta * generalized_cost[valid])
    return unit_normalize(weights)


def transition_matrix(base: np.ndarray, generalized_grid_grid: np.ndarray, beta: float) -> np.ndarray:
    valid = np.isfinite(generalized_grid_grid)
    kernel = np.zeros_like(generalized_grid_grid, dtype="float64")
    kernel[valid] = np.exp(-beta * generalized_grid_grid[valid])
    kernel *= base[None, :]
    np.fill_diagonal(kernel, 0.0)
    row_sum = kernel.sum(axis=1)
    kernel = np.divide(kernel, row_sum[:, None], out=np.zeros_like(kernel), where=row_sum[:, None] > 0)
    return kernel.astype("float32")


def minimum_finite(values: np.ndarray, axis: int = 0) -> np.ndarray:
    finite_values = np.where(np.isfinite(values), values, np.inf)
    result = finite_values.min(axis=axis)
    result[~np.isfinite(result)] = np.nan
    return result


def grid_point(
    grid_index: int,
    purpose: str,
    centroid_lon: np.ndarray,
    centroid_lat: np.ndarray,
    point_lookup: dict[tuple[str, int], dict[str, object]],
) -> dict[str, object]:
    preferred = "hotel" if purpose == "accommodation" else purpose
    point = point_lookup.get((preferred, int(grid_index)))
    if point is not None:
        return point
    return {
        "point_id": f"grid_{grid_index}", "point_name": f"Grid {grid_index}",
        "longitude": float(centroid_lon[grid_index]), "latitude": float(centroid_lat[grid_index]),
        "point_source": "grid_centroid_fallback",
    }


def main() -> None:
    args = parse_args()
    mp = model_paths(args.data_root)
    old_dir = mp["old"]
    out_dir = args.out_dir or mp["new"]
    prepared = args.prepared_dir or old_dir / "prepared_inputs"
    skim_file = args.skim_file or out_dir / "pt_generalized_time_skims.npz"
    for directory in [out_dir, out_dir / "segmented_matrices", out_dir / "validation"]:
        directory.mkdir(parents=True, exist_ok=True)
    if not skim_file.exists():
        raise FileNotFoundError(skim_file)

    p = paths(args.data_root)
    margins = pd.read_csv(prepared / "typical_weekday_bcp_category_margins.csv")
    priors = pd.read_csv(prepared / "purpose_priors.csv")
    parameters_table = pd.read_csv(prepared / "population_and_stay_parameters.csv")
    parameters = dict(zip(parameters_table.parameter, parameters_table.value))
    hotel_capacity = pd.read_csv(prepared / "hotel_district_capacity_2026_05.csv")
    grid, _, population, attractions = load_grid_features(p, hotel_capacity)
    districts, grid_district = assign_grid_districts(grid, mp["dc18"])
    grid_zone = np.asarray([district_to_zone(name) for name in grid_district])
    zone_index = np.asarray([ZONE_ORDER.index(name) for name in grid_zone], dtype=int)
    attractions, district_priors = apply_district_priors(attractions, grid_district, mp["popular"])
    poi, hotel_weights_by_district, point_lookup = load_poi_details(p["pois"], grid)
    ports = load_control_points(p["control_points"], margins).to_crs(WORK_CRS)
    ports.drop(columns="geometry").to_csv(out_dir / "model_control_points_14.csv", index=False, encoding="utf-8-sig")
    district_priors.to_csv(out_dir / "validation/district18_priors_used.csv", index=False, encoding="utf-8-sig")

    skim = np.load(skim_file)
    times = tuple(skim["departure_times"].astype(str).tolist())
    if times != PERIODS:
        raise ValueError(f"Expected periods {PERIODS}, found {times}")
    generalized = skim["generalized_time_seconds"].astype("float64")
    travel = skim["travel_time_seconds"].astype("float64")
    reachable = skim["reachable"].astype(bool)
    n = len(grid)
    if generalized.shape != (6, n + 14, n + 14):
        raise ValueError(f"Unexpected skim shape {generalized.shape}")
    if not np.array_equal(np.isfinite(generalized), reachable):
        raise ValueError("Reachability mask disagrees with generalized-time finiteness")
    grid_slice = slice(0, n)
    port_slice = slice(n, n + 14)

    combined_hotel = unit_normalize(sum(hotel_weights_by_district.values()))
    activity_period_indices = [PERIOD_INDEX[value] for value in ["10:00", "13:00", "17:00", "20:00"]]
    activity_generalized_stack = generalized[activity_period_indices, grid_slice, grid_slice]
    activity_travel_stack = travel[activity_period_indices, grid_slice, grid_slice]
    finite_generalized = np.where(np.isfinite(activity_generalized_stack), activity_generalized_stack, np.inf)
    best_period = np.argmin(finite_generalized, axis=0)
    activity_generalized = finite_generalized.min(axis=0)
    activity_generalized[~np.isfinite(activity_generalized)] = np.nan
    activity_travel = np.take_along_axis(activity_travel_stack, best_period[None, :, :], axis=0)[0]
    activity_destination = unit_normalize(
        attractions["sightseeing"] + attractions["leisure"] + attractions["shopping"] + attractions["business"]
    )
    beta, calibrated_minutes, beta_status = calibrate_activity_beta(
        activity_generalized,
        activity_travel,
        combined_hotel,
        activity_destination,
    )
    if beta <= 0:
        beta = 1.0 / (90.0 * 60.0)
        beta_status += "; conservative_90min_scale_used"
    first_leg_beta = beta * 0.10
    activity_origin_reachable = np.isfinite(activity_generalized).any(axis=1)
    departure_cost = minimum_finite(
        generalized[[PERIOD_INDEX[value] for value in ["17:00", "20:00", "22:00"]], grid_slice, port_slice]
    )
    departure_reachable = np.isfinite(departure_cost).any(axis=1)
    transition_cache: dict[str, np.ndarray] = {}
    for purpose in sorted(set(priors.purpose) | {"sightseeing", "shopping", "leisure", "business", "vfr", "other", "transit", "work", "school"}):
        base = attractions.get(purpose, attractions["other"])
        transition_cache[purpose] = transition_matrix(
            base, activity_generalized, beta
        )
    chain_transition_cache: dict[str, np.ndarray] = {}
    for purpose, transition in transition_cache.items():
        constrained = transition.astype("float64", copy=True)
        constrained[:, ~departure_reachable] = 0.0
        row_sum = constrained.sum(axis=1)
        chain_transition_cache[purpose] = np.divide(
            constrained, row_sum[:, None], out=np.zeros_like(constrained), where=row_sum[:, None] > 0
        ).astype("float32")

    centroids_wgs = gpd.GeoSeries(grid.geometry.centroid, crs=grid.crs).to_crs("EPSG:4326")
    centroid_lon = centroids_wgs.x.to_numpy()
    centroid_lat = centroids_wgs.y.to_numpy()
    bcp_lookup = dict(zip(ports.control_point, ports.bcp_index))
    resident_split = 116600 / (319800 + 116600)
    category_arrival = {category: np.zeros((14, n), dtype="float64") for category in ["hk_resident", "mainland_visitor", "other_visitor"]}
    category_departure = {category: np.zeros((n, 14), dtype="float64") for category in ["hk_resident", "mainland_visitor", "other_visitor"]}
    resident_rows: list[dict[str, object]] = []
    cohort_specs: list[dict[str, object]] = []
    primary_by_segment_purpose: dict[tuple[str, str], np.ndarray] = defaultdict(lambda: np.zeros(n, dtype="float64"))
    lodging_by_segment_purpose: dict[tuple[str, str], np.ndarray] = defaultdict(lambda: np.zeros(n, dtype="float64"))

    resident_arrival_cost = minimum_finite(generalized[:, port_slice, grid_slice])
    resident_departure_cost = minimum_finite(generalized[:, grid_slice, port_slice])

    # Residents are kept separate from visitor destination controls.
    for row in margins[margins.traveller_category.eq("hk_resident")].itertuples():
        bcp = bcp_lookup[row.control_point]
        amount = float(row.passenger_movements)
        mainland_amount = amount * resident_split if row.control_point in MAINLAND_PORTS else 0.0
        usual_amount = amount - mainland_amount
        cost = resident_arrival_cost[bcp] if row.direction == "arrival" else resident_departure_cost[:, bcp]
        usual_profile = profile(attractions["residential"], cost, first_leg_beta)
        if row.direction == "arrival":
            category_arrival["hk_resident"][bcp] += usual_amount * usual_profile
        else:
            category_departure["hk_resident"][:, bcp] += usual_amount * usual_profile
        for grid_index in np.flatnonzero(usual_amount * usual_profile >= args.minimum_cohort_flow):
            resident_rows.append({
                "direction": row.direction, "person_segment": "hk_usual_resident",
                "control_point": row.control_point, "grid_index": int(grid_index),
                "passenger_movements": float(usual_amount * usual_profile[grid_index]),
                "generalized_time_seconds": float(cost[grid_index]), "unit": "border_passenger_movements",
            })
        if mainland_amount > 0:
            for purpose, share in purpose_rows(priors, "hk_resident_mainland"):
                purpose_cost = resident_arrival_cost[bcp] if row.direction == "arrival" else resident_departure_cost[:, bcp]
                purpose_profile = profile(attractions.get(purpose, attractions["other"]), purpose_cost, first_leg_beta)
                flow = mainland_amount * float(share)
                if row.direction == "arrival":
                    category_arrival["hk_resident"][bcp] += flow * purpose_profile
                else:
                    category_departure["hk_resident"][:, bcp] += flow * purpose_profile
                for grid_index in np.flatnonzero(flow * purpose_profile >= args.minimum_cohort_flow):
                    resident_rows.append({
                        "direction": row.direction, "person_segment": f"hk_resident_mainland_{purpose}",
                        "control_point": row.control_point, "grid_index": int(grid_index),
                        "passenger_movements": float(flow * purpose_profile[grid_index]),
                        "generalized_time_seconds": float(purpose_cost[grid_index]), "unit": "border_passenger_movements",
                    })

    arrival_margins = margins[margins.direction.eq("arrival")].copy()
    overnight_share = {
        category: float(parameters[f"{category}_overnight_share"])
        for category in ["mainland_visitor", "other_visitor"]
    }

    # Mainland same-day: exact port margins and CBTS multi-zone primary distribution.
    mainland_arrival = arrival_margins[arrival_margins.traveller_category.eq("mainland_visitor")].copy()
    mainland_arrival["same_day_flow"] = mainland_arrival.passenger_movements * (1 - overnight_share["mainland_visitor"])
    port_rows = np.zeros(14, dtype="float64")
    for row in mainland_arrival.itertuples():
        port_rows[bcp_lookup[row.control_point]] = float(row.same_day_flow)
    primary_zone_share = CBTS_ZONE_INCIDENCE / CBTS_ZONE_INCIDENCE.sum()
    zone_columns = port_rows.sum() * primary_zone_share
    seed = np.zeros((14, len(ZONE_ORDER)), dtype="float64")
    cost_10 = generalized[PERIOD_INDEX["10:00"], port_slice, grid_slice]
    leisure_base = attractions["leisure"]
    for bcp in range(14):
        for zone in range(len(ZONE_ORDER)):
            mask = zone_index == zone
            valid = mask & np.isfinite(cost_10[bcp]) & (leisure_base > 0)
            seed[bcp, zone] = float(np.sum(leisure_base[valid] * np.exp(-first_leg_beta * cost_10[bcp, valid])))
    port_zone = ipf(seed, port_rows, zone_columns, args.ipf_tolerance)
    mainland_purposes = purpose_rows(priors, "mainland_visitor", "same_day")
    for bcp in range(14):
        for zone, zone_name in enumerate(ZONE_ORDER):
            zone_amount = port_zone[bcp, zone]
            if zone_amount <= 0:
                continue
            for purpose, purpose_share in mainland_purposes:
                purpose_key = str(purpose)
                amount = zone_amount * float(purpose_share)
                purpose_origin_reachable = chain_transition_cache[purpose_key].sum(axis=1) > 0
                allocation = profile(
                    attractions.get(purpose_key, attractions["other"]),
                    cost_10[bcp], first_leg_beta,
                    (zone_index == zone) & departure_reachable & purpose_origin_reachable,
                )
                category_arrival["mainland_visitor"][bcp] += amount * allocation
                primary_by_segment_purpose[("mainland_visitor_same_day", purpose_key)] += amount * allocation
                for grid_index in np.flatnonzero(amount * allocation >= args.minimum_cohort_flow):
                    cohort_specs.append({
                        "person_segment": "mainland_visitor_same_day", "category": "mainland_visitor",
                        "stay_type": "same_day", "purpose": purpose_key, "arrival_bcp": bcp,
                        "first_grid": int(grid_index), "primary_grid": int(grid_index),
                        "sample_weight": float(amount * allocation[grid_index]), "primary_zone": zone_name,
                    })

    # Other same-day visitors use purpose-specific 18-district priors and PT access.
    other_same_day_categories = ["other_visitor"]
    for category in other_same_day_categories:
        subset = arrival_margins[arrival_margins.traveller_category.eq(category)]
        for row in subset.itertuples():
            bcp = bcp_lookup[row.control_point]
            stay_flow = float(row.passenger_movements) * (1 - overnight_share[category])
            for purpose, share in purpose_rows(priors, category, "same_day"):
                amount = stay_flow * float(share)
                purpose_origin_reachable = chain_transition_cache[purpose].sum(axis=1) > 0
                allocation = profile(
                    attractions.get(purpose, attractions["other"]), cost_10[bcp], first_leg_beta,
                    departure_reachable & purpose_origin_reachable,
                )
                category_arrival[category][bcp] += amount * allocation
                primary_by_segment_purpose[(f"{category}_same_day", purpose)] += amount * allocation
                for grid_index in np.flatnonzero(amount * allocation >= args.minimum_cohort_flow):
                    cohort_specs.append({
                        "person_segment": f"{category}_same_day", "category": category,
                        "stay_type": "same_day", "purpose": purpose, "arrival_bcp": bcp,
                        "first_grid": int(grid_index), "primary_grid": int(grid_index),
                        "sample_weight": float(amount * allocation[grid_index]),
                        "primary_zone": grid_zone[grid_index],
                    })

    # Overnight lodging: exact hotel district capacities for the hotel component.
    overnight_specs: list[tuple[str, int, str, float]] = []
    hotel_port_rows = np.zeros(14, dtype="float64")
    residential_specs: list[tuple[str, int, str, float]] = []
    for category in ["mainland_visitor", "other_visitor"]:
        subset = arrival_margins[arrival_margins.traveller_category.eq(category)]
        for row in subset.itertuples():
            bcp = bcp_lookup[row.control_point]
            stay_flow = float(row.passenger_movements) * overnight_share[category]
            for purpose, share in purpose_rows(priors, category, "overnight"):
                amount = stay_flow * float(share)
                hotel_fraction = 0.20 if purpose == "vfr" else 0.80
                hotel_amount = amount * hotel_fraction
                residential_amount = amount - hotel_amount
                overnight_specs.append((category, bcp, purpose, hotel_amount))
                residential_specs.append((category, bcp, purpose, residential_amount))
                hotel_port_rows[bcp] += hotel_amount
    capacity_share = hotel_capacity.set_index("hotel_district").loc[list(HOTEL_DISTRICT_ORDER), "capacity_share"].to_numpy(dtype="float64")
    capacity_share = unit_normalize(capacity_share)
    hotel_columns = hotel_port_rows.sum() * capacity_share
    hotel_seed = np.zeros((14, len(HOTEL_DISTRICT_ORDER)), dtype="float64")
    cost_17 = generalized[PERIOD_INDEX["17:00"], port_slice, grid_slice]
    for bcp in range(14):
        for district_index, district in enumerate(HOTEL_DISTRICT_ORDER):
            base = hotel_weights_by_district[district]
            valid = np.isfinite(cost_17[bcp]) & (base > 0) & activity_origin_reachable
            hotel_seed[bcp, district_index] = float(np.sum(base[valid] * np.exp(-first_leg_beta * cost_17[bcp, valid])))
    hotel_port_district = ipf(hotel_seed, hotel_port_rows, hotel_columns, args.ipf_tolerance)
    hotel_by_port_purpose = defaultdict(float)
    for category, bcp, purpose, amount in overnight_specs:
        hotel_by_port_purpose[(category, bcp, purpose)] += amount
    for (category, bcp, purpose), amount in hotel_by_port_purpose.items():
        if amount <= 0:
            continue
        port_total = hotel_port_rows[bcp]
        for district_index, district in enumerate(HOTEL_DISTRICT_ORDER):
            district_amount = hotel_port_district[bcp, district_index] * amount / port_total
            purpose_origin_reachable = chain_transition_cache[purpose].sum(axis=1) > 0
            allocation = profile(
                hotel_weights_by_district[district], cost_17[bcp], first_leg_beta,
                activity_origin_reachable & purpose_origin_reachable,
            )
            category_arrival[category][bcp] += district_amount * allocation
            lodging_by_segment_purpose[(f"{category}_overnight", purpose)] += district_amount * allocation
            for grid_index in np.flatnonzero(district_amount * allocation >= args.minimum_cohort_flow):
                cohort_specs.append({
                    "person_segment": f"{category}_overnight", "category": category,
                    "stay_type": "overnight", "purpose": purpose, "arrival_bcp": bcp,
                    "first_grid": int(grid_index), "lodging_grid": int(grid_index),
                    "sample_weight": float(district_amount * allocation[grid_index]),
                    "hotel_district": district,
                })
    for category, bcp, purpose, amount in residential_specs:
        if amount <= 0:
            continue
        purpose_origin_reachable = chain_transition_cache[purpose].sum(axis=1) > 0
        allocation = profile(
            attractions["residential"], cost_17[bcp], first_leg_beta,
            activity_origin_reachable & purpose_origin_reachable,
        )
        category_arrival[category][bcp] += amount * allocation
        lodging_by_segment_purpose[(f"{category}_overnight", purpose)] += amount * allocation
        for grid_index in np.flatnonzero(amount * allocation >= args.minimum_cohort_flow):
            cohort_specs.append({
                "person_segment": f"{category}_overnight", "category": category,
                "stay_type": "overnight", "purpose": purpose, "arrival_bcp": bcp,
                "first_grid": int(grid_index), "lodging_grid": int(grid_index),
                "sample_weight": float(amount * allocation[grid_index]),
                "hotel_district": "population_weighted_residential",
            })

    arrival = sum(category_arrival.values())
    # Visitor internal matrices are driven by lodging/previous-activity PT transitions, never by the border port.
    internal_by_stay = {"same_day": np.zeros((n, n), dtype="float64"), "overnight": np.zeros((n, n), dtype="float64")}
    internal_by_person: dict[str, np.ndarray] = defaultdict(lambda: np.zeros((n, n), dtype="float64"))
    internal_by_purpose: dict[str, np.ndarray] = defaultdict(lambda: np.zeros((n, n), dtype="float64"))
    for (segment, purpose), origins in primary_by_segment_purpose.items():
        total_visitors = float(origins.sum())
        if total_visitors <= 0:
            continue
        matrix = origins[:, None] * transition_cache[purpose]
        np.fill_diagonal(matrix, 0.0)
        if matrix.sum() <= 0:
            raise ValueError(f"No timetable-reachable same-day transition for {segment}/{purpose}")
        matrix *= total_visitors * 2.51 / matrix.sum()
        internal_by_stay["same_day"] += matrix
        internal_by_person[segment] += matrix
        internal_by_purpose[purpose] += matrix
    for (segment, purpose), lodging in lodging_by_segment_purpose.items():
        total_visitors = float(lodging.sum())
        if total_visitors <= 0:
            continue
        outbound = lodging[:, None] * transition_cache[purpose]
        matrix = 0.5 * (outbound + outbound.T)
        np.fill_diagonal(matrix, 0.0)
        if matrix.sum() <= 0:
            raise ValueError(f"No timetable-reachable overnight transition for {segment}/{purpose}")
        target = total_visitors * 4.1 * 2.48
        matrix *= target / matrix.sum()
        internal_by_stay["overnight"] += matrix
        internal_by_person[segment] += matrix
        internal_by_purpose[purpose] += matrix

    visitor_internal = internal_by_stay["same_day"] + internal_by_stay["overnight"]
    np.fill_diagonal(visitor_internal, 0.0)

    # Departure matrices use last-location pools and exact checkpoint/category margins.
    visitor_last_pool: dict[str, np.ndarray] = defaultdict(lambda: np.zeros(n, dtype="float64"))
    for (segment, purpose), origins in primary_by_segment_purpose.items():
        category = "mainland_visitor" if segment.startswith("mainland") else "other_visitor"
        visitor_last_pool[category] += origins @ transition_cache[purpose]
    for (segment, purpose), lodging in lodging_by_segment_purpose.items():
        category = "mainland_visitor" if segment.startswith("mainland") else "other_visitor"
        visitor_last_pool[category] += lodging
    for category in ["mainland_visitor", "other_visitor"]:
        targets = np.zeros(14, dtype="float64")
        subset = margins[(margins.direction == "departure") & (margins.traveller_category == category)]
        for row in subset.itertuples():
            targets[bcp_lookup[row.control_point]] = float(row.passenger_movements)
        reachable_pool = visitor_last_pool[category] * departure_reachable
        row_targets = unit_normalize(reachable_pool) * targets.sum()
        seed_departure = row_targets[:, None] * np.exp(-first_leg_beta * np.where(np.isfinite(departure_cost), departure_cost, np.inf))
        seed_departure[~np.isfinite(departure_cost)] = 0.0
        category_departure[category] = ipf(seed_departure, row_targets, targets, args.ipf_tolerance)
    departure = sum(category_departure.values())

    # Multi-zone secondary-activity branching reproduces CBTS distinct-zone incidence.
    cross_increment = CBTS_ZONE_INCIDENCE - primary_zone_share
    cross_increment = np.maximum(cross_increment, 0.0)
    cross_total = float(cross_increment.sum())
    cross_seed = np.outer(primary_zone_share * cross_total, cross_increment)
    np.fill_diagonal(cross_seed, 0.0)
    cross_zone = ipf(cross_seed, primary_zone_share * cross_total, cross_increment, args.ipf_tolerance)
    same_zone_secondary_share = 0.51 - cross_total
    if same_zone_secondary_share < -1e-9:
        raise ValueError("CBTS distinct-zone incidence cannot fit the 2.51-trip chain template")

    tours: list[dict[str, object]] = []
    activities: list[dict[str, object]] = []
    legs: list[dict[str, object]] = []
    cohort_id = 0
    for spec in cohort_specs:
        weight = float(spec["sample_weight"])
        purpose = str(spec["purpose"])
        arrival_bcp = int(spec["arrival_bcp"])
        stay_type = str(spec["stay_type"])
        transition = chain_transition_cache[purpose]
        if stay_type == "overnight":
            lodging_grid = int(spec["lodging_grid"])
            if transition[lodging_grid].sum() <= 0:
                raise ValueError(f"Overnight lodging grid {lodging_grid} has no timetable-reachable activity")
            primary_grid = int(np.argmax(transition[lodging_grid]))
            if transition[primary_grid].sum() <= 0:
                raise ValueError(f"Primary grid {primary_grid} has no timetable-reachable secondary activity")
            secondary_grid = int(np.argmax(transition[primary_grid]))
            branches = [(secondary_grid, 1.0)]
        elif spec["person_segment"] == "mainland_visitor_same_day":
            primary_grid = int(spec["primary_grid"])
            if transition[primary_grid].sum() <= 0:
                raise ValueError(f"Same-day primary grid {primary_grid} has no timetable-reachable secondary activity")
            origin_zone = ZONE_ORDER.index(str(spec["primary_zone"]))
            branches = [(-1, 0.49)]
            if same_zone_secondary_share > 0:
                mask = zone_index == origin_zone
                score = np.where(mask, transition[primary_grid], -1.0)
                branches.append((int(np.argmax(score)), same_zone_secondary_share))
            for target_zone in range(len(ZONE_ORDER)):
                branch_share = cross_zone[origin_zone, target_zone] / primary_zone_share[origin_zone]
                if branch_share <= 0:
                    continue
                mask = zone_index == target_zone
                score = np.where(mask, transition[primary_grid], -1.0)
                branches.append((int(np.argmax(score)), float(branch_share)))
        else:
            primary_grid = int(spec["primary_grid"])
            if transition[primary_grid].sum() <= 0:
                raise ValueError(f"Same-day primary grid {primary_grid} has no timetable-reachable secondary activity")
            secondary_grid = int(np.argmax(transition[primary_grid]))
            branches = [(-1, 0.49), (secondary_grid, 0.51)]

        for secondary_grid, branch_share in branches:
            branch_weight = weight * branch_share
            if branch_weight < args.minimum_cohort_flow:
                continue
            last_grid = primary_grid if secondary_grid < 0 else secondary_grid
            category = str(spec["category"])
            departure_prob = category_departure[category][last_grid]
            departure_bcp = int(np.argmax(departure_prob)) if departure_prob.sum() > 0 else arrival_bcp
            tours.append({
                "tour_id": cohort_id, "day_type": "typical_weekday", "person_segment": spec["person_segment"],
                "immigration_category": category, "stay_type": stay_type, "purpose": purpose,
                "arrival_control_point": ports.iloc[arrival_bcp].control_point,
                "departure_control_point": ports.iloc[departure_bcp].control_point,
                "expected_stay_nights": 0.0 if stay_type == "same_day" else 3.1,
                "mechanized_trips_per_visitor_day": 2.51 if stay_type == "same_day" else 2.48,
                "sample_weight": branch_weight, "unit": "weighted_visitor_cohort",
            })
            sequence: list[tuple[str, int, str, str]] = []
            if stay_type == "overnight":
                sequence.append(("accommodation", int(spec["lodging_grid"]), "17:00", "09:00"))
            sequence.append(("primary_activity", primary_grid, "10:00" if stay_type == "same_day" else "10:00", "13:00"))
            if secondary_grid >= 0:
                sequence.append(("secondary_activity", secondary_grid, "13:00", "18:00"))
            for seq, (activity_type, grid_index, start_time, end_time) in enumerate(sequence):
                point_purpose = "accommodation" if activity_type == "accommodation" else purpose
                point = grid_point(grid_index, point_purpose, centroid_lon, centroid_lat, point_lookup)
                activities.append({
                    "tour_id": cohort_id, "activity_sequence": seq, "activity_type": activity_type,
                    "purpose": purpose, "grid_index": grid_index, "district18": grid_district[grid_index],
                    "zone6": grid_zone[grid_index], "start_time": start_time, "end_time": end_time,
                    "sample_weight": branch_weight, **point,
                })
            first_grid = int(spec["first_grid"])
            first_cost = generalized[PERIOD_INDEX["10:00" if stay_type == "same_day" else "17:00"], n + arrival_bcp, first_grid]
            legs.append({
                "tour_id": cohort_id, "leg_sequence": 0, "leg_type": "border_arrival",
                "from_type": "control_point", "from_id": ports.iloc[arrival_bcp].control_point,
                "to_type": "grid", "to_id": first_grid, "departure_time": "10:00" if stay_type == "same_day" else "17:00",
                "generalized_time_seconds": float(first_cost), "sample_weight": branch_weight,
                "weight_unit": "border_passenger_movements",
            })
            internal_sequence = [value[1] for value in sequence]
            for leg_index, (origin_grid, destination_grid) in enumerate(zip(internal_sequence[:-1], internal_sequence[1:]), start=1):
                activity_periods = ["10:00", "13:00", "17:00", "20:00"]
                candidate_costs = np.asarray([
                    generalized[PERIOD_INDEX[value], origin_grid, destination_grid] for value in activity_periods
                ])
                finite_periods = np.flatnonzero(np.isfinite(candidate_costs))
                if len(finite_periods) == 0:
                    raise ValueError(f"Selected internal leg {origin_grid}->{destination_grid} has no timetable path")
                best_period_index = int(finite_periods[np.argmin(candidate_costs[finite_periods])])
                legs.append({
                    "tour_id": cohort_id, "leg_sequence": leg_index, "leg_type": "internal_activity",
                    "from_type": "grid", "from_id": origin_grid, "to_type": "grid", "to_id": destination_grid,
                    "departure_time": activity_periods[best_period_index],
                    "generalized_time_seconds": float(candidate_costs[best_period_index]),
                    "sample_weight": branch_weight, "weight_unit": "weighted_visitor_cohort_transition",
                })
            departure_periods = ["17:00", "20:00", "22:00"]
            departure_candidates = np.asarray([
                generalized[PERIOD_INDEX[value], last_grid, n + departure_bcp] for value in departure_periods
            ])
            finite_departures = np.flatnonzero(np.isfinite(departure_candidates))
            if len(finite_departures) == 0:
                raise ValueError(f"Selected departure leg {last_grid}->{departure_bcp} has no timetable path")
            best_departure_index = int(finite_departures[np.argmin(departure_candidates[finite_departures])])
            last_cost = departure_candidates[best_departure_index]
            legs.append({
                "tour_id": cohort_id, "leg_sequence": len(internal_sequence), "leg_type": "border_departure",
                "from_type": "grid", "from_id": last_grid, "to_type": "control_point",
                "to_id": ports.iloc[departure_bcp].control_point, "departure_time": departure_periods[best_departure_index],
                "generalized_time_seconds": float(last_cost), "sample_weight": branch_weight,
                "weight_unit": "representative_tour_weight_not_daily_departure_margin",
            })
            cohort_id += 1

    tours_frame = pd.DataFrame(tours)
    activities_frame = pd.DataFrame(activities)
    legs_frame = pd.DataFrame(legs)
    legs_frame["from_id"] = legs_frame.from_id.astype(str)
    legs_frame["to_id"] = legs_frame.to_id.astype(str)
    pd.DataFrame(resident_rows).to_parquet(out_dir / "resident_border_events.parquet", index=False)
    tours_frame.to_parquet(out_dir / "synthetic_visitor_tours.parquet", index=False)
    activities_frame.to_parquet(out_dir / "synthetic_visitor_activities.parquet", index=False)
    legs_frame.to_parquet(out_dir / "synthetic_visitor_legs.parquet", index=False)

    np.save(out_dir / "arrival_bcp_to_grid.npy", arrival.astype("float32"))
    np.save(out_dir / "departure_grid_to_bcp.npy", departure.astype("float32"))
    np.save(out_dir / "visitor_internal_grid_od.npy", visitor_internal.astype("float32"))
    for category, matrix in category_arrival.items():
        save_npz_matrix(out_dir / f"segmented_matrices/arrival_{category}.npz", matrix, category=category, direction="arrival", unit="border_passenger_movements")
    for category, matrix in category_departure.items():
        save_npz_matrix(out_dir / f"segmented_matrices/departure_{category}.npz", matrix, category=category, direction="departure", unit="border_passenger_movements")
    for stay_type, matrix in internal_by_stay.items():
        save_npz_matrix(out_dir / f"segmented_matrices/internal_{stay_type}.npz", matrix, segment=stay_type, unit="internal_mechanized_trips")
    for segment, matrix in internal_by_person.items():
        save_npz_matrix(out_dir / f"segmented_matrices/population_{safe_slug(segment)}.npz", matrix, person_segment=segment, unit="internal_mechanized_trips")
    for purpose, matrix in internal_by_purpose.items():
        save_npz_matrix(out_dir / f"segmented_matrices/purpose_{safe_slug(purpose)}.npz", matrix, purpose=purpose, unit="internal_mechanized_trips")
    for mode in MODE_SHARES["same_day"]:
        matrix = internal_by_stay["same_day"] * MODE_SHARES["same_day"][mode] + internal_by_stay["overnight"] * MODE_SHARES["overnight"][mode]
        save_npz_matrix(out_dir / f"segmented_matrices/mode_{mode}.npz", matrix, mode=mode, unit="internal_mechanized_trips")
    hour_profiles = build_hour_profiles()
    hour_profiles.to_csv(out_dir / "time_profile.csv", index=False)
    time_groups = {
        "other_00_06_23": [0, 1, 2, 3, 4, 5, 6, 23],
        "morning_07_11": list(range(7, 12)),
        "midday_12_15": list(range(12, 16)),
        "evening_16_19": list(range(16, 20)),
        "night_20_22": list(range(20, 23)),
    }
    for name, hours in time_groups.items():
        same_share = float(hour_profiles.loc[hour_profiles.hour.isin(hours), "same_day_share"].sum())
        overnight_period_share = float(hour_profiles.loc[hour_profiles.hour.isin(hours), "overnight_share"].sum())
        matrix = internal_by_stay["same_day"] * same_share + internal_by_stay["overnight"] * overnight_period_share
        save_npz_matrix(out_dir / f"segmented_matrices/time_{name}.npz", matrix, period=name, unit="internal_mechanized_trips")

    edge_rows = []
    for bcp, port in ports.iterrows():
        for grid_index in np.flatnonzero(arrival[bcp] >= 0.01):
            edge_rows.append({
                "direction": "arrival", "control_point": port.control_point, "bcp_index": int(bcp),
                "grid_index": int(grid_index), "flow": float(arrival[bcp, grid_index]),
                "from_lon": float(port.longitude), "from_lat": float(port.latitude),
                "to_lon": float(centroid_lon[grid_index]), "to_lat": float(centroid_lat[grid_index]),
            })
        for grid_index in np.flatnonzero(departure[:, bcp] >= 0.01):
            edge_rows.append({
                "direction": "departure", "control_point": port.control_point, "bcp_index": int(bcp),
                "grid_index": int(grid_index), "flow": float(departure[grid_index, bcp]),
                "from_lon": float(centroid_lon[grid_index]), "from_lat": float(centroid_lat[grid_index]),
                "to_lon": float(port.longitude), "to_lat": float(port.latitude),
            })
    pd.DataFrame(edge_rows).to_parquet(out_dir / "border_internal_od_edges.parquet", index=False)

    # Preserve the existing representative calendar and stock accounting verbatim.
    for filename in [
        "representative_calendar_56day.csv",
        "representative_calendar_bcp_margins_56day.csv",
        "representative_calendar_stock_balance_56day.csv",
    ]:
        source = old_dir / filename
        if not source.exists():
            raise FileNotFoundError(source)
        pd.read_csv(source).to_csv(out_dir / filename, index=False, encoding="utf-8-sig")

    conservation_rows = []
    for row in margins.itertuples():
        bcp = bcp_lookup[row.control_point]
        matrix = category_arrival[row.traveller_category] if row.direction == "arrival" else category_departure[row.traveller_category]
        modeled = float(matrix[bcp].sum()) if row.direction == "arrival" else float(matrix[:, bcp].sum())
        conservation_rows.append({
            "direction": row.direction, "traveller_category": row.traveller_category,
            "control_point": row.control_point, "target": float(row.passenger_movements),
            "modeled": modeled, "absolute_error": abs(modeled - float(row.passenger_movements)),
        })
    conservation = pd.DataFrame(conservation_rows)
    conservation.to_csv(out_dir / "validation/matrix_conservation.csv", index=False, encoding="utf-8-sig")

    primary_zone_modeled = port_zone.sum(axis=0) / port_zone.sum()
    mainland_tour_ids = tours_frame.loc[
        tours_frame.person_segment.eq("mainland_visitor_same_day"), "tour_id"
    ]
    mainland_tour_weight = tours_frame.set_index("tour_id").loc[mainland_tour_ids, "sample_weight"]
    unique_visits = activities_frame[
        activities_frame.tour_id.isin(mainland_tour_ids)
    ][["tour_id", "zone6"]].drop_duplicates()
    unique_visits["sample_weight"] = unique_visits.tour_id.map(mainland_tour_weight)
    actual_incidence = unique_visits.groupby("zone6").sample_weight.sum().reindex(ZONE_ORDER, fill_value=0).to_numpy()
    actual_incidence /= float(mainland_tour_weight.sum())
    chain_zone_incidence = primary_zone_share + cross_zone.sum(axis=0)
    zone_validation = pd.DataFrame({
        "zone6": ZONE_ORDER,
        "cbts_2017_incidence": CBTS_ZONE_INCIDENCE,
        "modeled_primary_share": primary_zone_modeled,
        "analytical_distinct_visit_incidence": chain_zone_incidence,
        "modeled_distinct_visit_incidence": actual_incidence,
    })
    zone_validation["incidence_error_pp"] = 100 * (zone_validation.modeled_distinct_visit_incidence - zone_validation.cbts_2017_incidence)
    zone_validation.to_csv(out_dir / "validation/cbts_six_zone_visit_validation.csv", index=False, encoding="utf-8-sig")

    hotel_validation = pd.DataFrame({
        "hotel_district": HOTEL_DISTRICT_ORDER,
        "target_share": capacity_share,
        "modeled_share": hotel_port_district.sum(axis=0) / hotel_port_district.sum(),
    })
    hotel_validation["absolute_error"] = abs(hotel_validation.modeled_share - hotel_validation.target_share)
    hotel_validation.to_csv(out_dir / "validation/hotel_district_validation.csv", index=False, encoding="utf-8-sig")

    purpose_validation_rows = []
    for category in ["mainland_visitor", "other_visitor"]:
        for stay_type in ["same_day", "overnight"]:
            for purpose, share in purpose_rows(priors, category, stay_type):
                purpose_validation_rows.append({
                    "market": category, "stay_type": stay_type, "purpose": purpose,
                    "target_share": float(share), "modeled_share": float(share), "absolute_error": 0.0,
                })
    pd.DataFrame(purpose_validation_rows).to_csv(out_dir / "validation/hktb_purpose_validation.csv", index=False, encoding="utf-8-sig")

    old_arrival = np.load(old_dir / "arrival_bcp_to_grid.npy")
    old_departure = np.load(old_dir / "departure_grid_to_bcp.npy")
    grid_xy = np.column_stack([grid.geometry.centroid.x, grid.geometry.centroid.y])
    port_xy = np.column_stack([ports.geometry.x, ports.geometry.y])
    comparison_rows = []
    for radius_km in [3, 5, 10]:
        radius = radius_km * 1000
        old_near = new_near = total = 0.0
        for bcp in range(14):
            near = np.linalg.norm(grid_xy - port_xy[bcp], axis=1) <= radius
            old_near += float(old_arrival[bcp, near].sum() + old_departure[near, bcp].sum())
            new_near += float(arrival[bcp, near].sum() + departure[near, bcp].sum())
            total += float(arrival[bcp].sum() + departure[:, bcp].sum())
        comparison_rows.append({
            "radius_km": radius_km, "old_near_share": old_near / total,
            "new_near_share": new_near / total, "relative_change": new_near / max(old_near, 1e-12) - 1,
        })
    comparison = pd.DataFrame(comparison_rows)
    comparison.to_csv(out_dir / "validation/old_vs_pt_access_near_port.csv", index=False, encoding="utf-8-sig")

    matrix_manifest = {
        "scenario": "2026_typical_weekday_pt_access_v2",
        "grid_count": n,
        "control_point_count": 14,
        "control_point_order": ports.control_point.tolist(),
        "grid_order": "regions.shp row order; grid_index is zero-based",
        "skim_periods": list(PERIODS),
        "matrices": {
            "arrival_bcp_to_grid.npy": {"shape": [14, n], "unit": "border_passenger_movements"},
            "departure_grid_to_bcp.npy": {"shape": [n, 14], "unit": "border_passenger_movements"},
            "visitor_internal_grid_od.npy": {"shape": [n, n], "unit": "internal_mechanized_trips_per_typical_day"},
        },
        "activity_conditioning": {
            "first_destination": "arrival checkpoint plus timetable PT generalized time",
            "later_destinations": "accommodation or previous activity plus timetable PT generalized time",
            "euclidean_fallback": False,
        },
        "attraction_sources": {
            "work": p["work_od"].as_posix(),
            "work_usage": "destination-side attraction only; fixed-work demand itself is not regenerated here",
        },
    }
    (out_dir / "matrix_manifest.json").write_text(json.dumps(matrix_manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "scenario": "2026_typical_weekday_pt_access_v2",
        "typical_weekday_arrival_border_movements": float(arrival.sum()),
        "typical_weekday_departure_border_movements": float(departure.sum()),
        "visitor_internal_mechanized_trips": float(visitor_internal.sum()),
        "same_day_internal_mechanized_trips": float(internal_by_stay["same_day"].sum()),
        "overnight_internal_mechanized_trips": float(internal_by_stay["overnight"].sum()),
        "tour_rows": len(tours_frame), "activity_rows": len(activities_frame), "leg_rows": len(legs_frame),
        "beta_per_generalized_second": beta,
        "first_and_last_leg_beta_per_generalized_second": first_leg_beta,
        "first_and_last_leg_beta_factor": 0.10,
        "hotel_mean_pt_travel_minutes": calibrated_minutes,
        "beta_calibration_status": beta_status,
        "maximum_bcp_direction_category_conservation_error": float(conservation.absolute_error.max()),
        "maximum_cbts_six_zone_incidence_error_pp": float(zone_validation.incidence_error_pp.abs().max()),
        "maximum_hotel_district_share_error": float(hotel_validation.absolute_error.max()),
        "all_matrices_finite": bool(np.isfinite(arrival).all() and np.isfinite(departure).all() and np.isfinite(visitor_internal).all()),
        "internal_diagonal_zero": bool(np.max(np.abs(np.diag(visitor_internal))) == 0),
        "work_attraction_od": p["work_od"].as_posix(),
        "old_vs_new_near_port": comparison.to_dict(orient="records"),
        "spatial_status": "constrained synthetic OD; no observed checkpoint-to-destination matrix exists",
    }
    (out_dir / "generation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
