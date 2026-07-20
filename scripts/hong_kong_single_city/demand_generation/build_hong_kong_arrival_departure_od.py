#!/usr/bin/env python3
"""Build a constrained synthetic Hong Kong typical-weekday border OD model."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial.distance import cdist


ROOT = Path(__file__).resolve().parents[3]
WINDOWS_DATA_ROOT = Path(r"F:\Matsim\matsim-example-project\data")
DEFAULT_DATA_ROOT = WINDOWS_DATA_ROOT if WINDOWS_DATA_ROOT.exists() else ROOT / "data"
WORK_CRS = "EPSG:32650"
MAINLAND_PORTS = {"罗湖", "落马洲支线", "落马洲", "文锦渡", "深圳湾", "香园围", "高铁西九龙", "港珠澳大桥"}
PORT_ORDER = [
    "机场", "罗湖", "落马洲支线", "落马洲", "文锦渡", "沙头角", "中国客运码头",
    "港澳客轮码头", "深圳湾", "启德邮轮码头", "高铁西九龙", "港珠澳大桥", "香园围", "港口管制",
]
DISTANCE_SCALE_KM = {
    "school": 10.0, "work": 14.0, "leisure": 18.0, "sightseeing": 18.0,
    "shopping": 14.0, "business": 16.0, "vfr": 12.0, "transit": 5.0, "other": 12.0,
}
OVERNIGHT_SHARE = {"mainland_visitor": 0.37, "other_visitor": 0.66}
MODE_SHARES = {
    "same_day": {"mtr": 0.52, "franchised_bus": 0.25, "taxi_hired_car": 0.11, "other_mechanized": 0.12},
    "overnight": {"mtr": 0.47, "franchised_bus": 0.14, "taxi_hired_car": 0.12, "other_mechanized": 0.27},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--prepared-dir", type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--minimum-cohort-flow", type=float, default=0.05)
    return parser.parse_args()


def paths(data_root: Path) -> dict[str, Path]:
    city = data_root / "worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid"
    nfeat = city / "GeneratingCodeData/data/global_cities/hong_kong_fixed_link_grid/nfeat"
    return {
        "grid": city / "CityAndRegionSplit/hong_kong_fixed_link_grid/regions.shp",
        "distance": city / "GeneratingCodeData/data/global_cities/hong_kong_fixed_link_grid/adj/dis.npy",
        "worldpop": nfeat / "worldpop.npy",
        "work_od": city / "census_2021_commute_constraints/generation_2021_census_area_scaled.npy",
        "pois": data_root / "osm/hongkong/fixed_link_boundary/integrated_pois/hong_kong_fixed_link_integrated_pois.csv",
        "schools": data_root / "school/hongkong/processed/student_school_od_2022/schools_2022_capacity_estimates.geojson",
        "control_points": data_root / "border/hongkong/control_points/hong_kong_control_point_locations_2026-07-16.csv",
    }


def normalize(values: np.ndarray) -> np.ndarray:
    values = np.nan_to_num(np.asarray(values, dtype=float), nan=0.0, posinf=0.0, neginf=0.0)
    values[values < 0] = 0
    total = values.sum()
    return values / total if total > 0 else np.full(len(values), 1.0 / len(values))


def assign_points_to_grid(points: gpd.GeoDataFrame, grid: gpd.GeoDataFrame) -> np.ndarray:
    joined = gpd.sjoin(points.to_crs(grid.crs), grid[["geometry"]], how="left", predicate="within")
    missing = joined.index_right.isna()
    if missing.any():
        nearest = gpd.sjoin_nearest(points.loc[missing].to_crs(grid.crs), grid[["geometry"]], how="left")
        joined.loc[missing, "index_right"] = nearest["index_right"].to_numpy()
    return joined["index_right"].astype(int).to_numpy()


def load_grid_features(
    p: dict[str, Path], hotel_districts: pd.DataFrame
) -> tuple[gpd.GeoDataFrame, np.ndarray, np.ndarray, dict[str, np.ndarray]]:
    for path in p.values():
        if not path.exists():
            raise FileNotFoundError(path)
    grid = gpd.read_file(p["grid"]).to_crs(WORK_CRS).reset_index(drop=True)
    n = len(grid)
    if n != 1585:
        raise ValueError(f"Expected 1585 grid cells, found {n}")
    worldpop = np.load(p["worldpop"])
    population = worldpop[:, 0].astype(float)
    distance = np.load(p["distance"]).astype(np.float32)
    if distance.shape != (n, n):
        raise ValueError(f"Distance shape {distance.shape} does not match grid")

    poi = pd.read_csv(p["pois"], low_memory=False)
    poi = poi.dropna(subset=["lon", "lat"])
    poi_gdf = gpd.GeoDataFrame(poi, geometry=gpd.points_from_xy(poi.lon, poi.lat), crs="EPSG:4326")
    poi_gdf["grid_index"] = assign_points_to_grid(poi_gdf, grid)
    category = poi_gdf["wedan_category"].fillna("").astype(str).str.lower()

    groups = {
        "sightseeing": {"tourism", "garden", "sport", "religion", "cinema and theatre"},
        "leisure": {"tourism", "garden", "sport", "religion", "cinema and theatre", "bar"},
        "shopping": {"retail", "livelihood shop", "clothes shop", "supermarket", "houseware shop", "boutique", "beauty shop"},
        "business": {"office", "finance", "government", "service"},
        "transit": {"transit station", "transport"},
        "food": {"restaurant", "fast food", "cafe", "bar", "food court", "ice cream"},
        "hotel": {"accommodation"},
    }
    weights: dict[str, np.ndarray] = {}
    for name, cats in groups.items():
        mask = category.isin(cats)
        counts = np.bincount(poi_gdf.loc[mask, "grid_index"], minlength=n).astype(float)
        weights[name] = normalize(np.sqrt(counts) + (counts > 0) * 0.25)

    hotel_pois = poi_gdf.loc[category.eq("accommodation")].copy()
    district = hotel_pois["district_en"].fillna("").astype(str)
    hotel_pois["hotel_district"] = np.select(
        [
            district.str.contains("Central & Western", case=False),
            district.str.contains("Wan Chai", case=False),
            district.str.contains("Eastern|Southern", case=False),
            district.str.contains("Yau Tsim Mong", case=False) & (hotel_pois.geometry.y < 22.31),
            district.str.contains("Yau Tsim Mong", case=False),
            district.str.contains("Sham Shui Po|Kowloon City|Kwun Tong|Wong Tai Sin", case=False),
            district.str.contains("Islands", case=False),
            district.str.contains("Tsuen Wan|Kwai Tsing|Tuen Mun|Yuen Long|North|Tai Po|Sha Tin|Sai Kung", case=False),
        ],
        [
            "Central and Western", "Wan Chai", "Eastern and Southern", "Tsim Sha Tsui",
            "Yau Ma Tei and Mong Kok", "Other Kowloon", "Outlying Islands", "New Territories",
        ],
        default="unmapped",
    )
    district_share = hotel_districts.set_index("hotel_district")["capacity_share"].to_dict()
    district_count = hotel_pois.loc[hotel_pois.hotel_district != "unmapped", "hotel_district"].value_counts().to_dict()
    hotel_pois["capacity_weight"] = [
        district_share.get(d, 0.0) / district_count.get(d, 1) if d != "unmapped" else 0.0
        for d in hotel_pois.hotel_district
    ]
    hotel_grid = np.bincount(
        hotel_pois.grid_index, weights=hotel_pois.capacity_weight, minlength=n
    ).astype(float)
    if hotel_grid.sum() > 0:
        weights["hotel"] = normalize(hotel_grid)

    work = np.load(p["work_od"], mmap_mode="r")
    work_attraction = np.asarray(work.sum(axis=0), dtype=float)
    is_work = poi_gdf.get("is_work_related", pd.Series(False, index=poi_gdf.index)).astype(str).str.lower().isin(["true", "1"])
    work_poi = np.bincount(poi_gdf.loc[is_work, "grid_index"], minlength=n).astype(float)
    weights["work"] = normalize(np.sqrt(work_attraction + 1) * (1 + np.log1p(work_poi)))

    schools = gpd.read_file(p["schools"]).to_crs(grid.crs)
    schools["grid_index"] = assign_points_to_grid(schools, grid)
    numeric_candidates = [c for c in schools.columns if any(k in c.lower() for k in ["capacity", "student", "estimate"])]
    capacity_col = next((c for c in numeric_candidates if pd.to_numeric(schools[c], errors="coerce").notna().any()), None)
    school_capacity = pd.to_numeric(schools[capacity_col], errors="coerce").fillna(1).clip(lower=0).to_numpy() if capacity_col else np.ones(len(schools))
    weights["school"] = normalize(np.bincount(schools.grid_index, weights=school_capacity, minlength=n).astype(float))
    weights["vfr"] = normalize(population)
    weights["other"] = normalize(0.45 * normalize(population) + 0.25 * weights["shopping"] + 0.30 * weights["food"])
    weights["residential"] = normalize(population)
    weights["hotel"] = normalize(weights["hotel"] + 0.03 * weights["residential"])
    return grid, distance, population, weights


def load_control_points(path: Path, margins: pd.DataFrame) -> gpd.GeoDataFrame:
    raw = pd.read_csv(path, encoding="utf-8-sig")
    rows = []
    for name in PORT_ORDER:
        subset = raw[raw["traffic_csv_category"] == name]
        if name == "机场":
            preferred = subset[subset.name_en.str.contains("Terminal 1", na=False)]
            subset = preferred if len(preferred) else subset
        elif name == "港口管制":
            preferred = subset[subset.name_en.eq("Harbour Control")]
            subset = preferred if len(preferred) else subset
        if subset.empty:
            raise ValueError(f"No authoritative point for statistical control point {name}")
        row = subset.iloc[0]
        rows.append({"bcp_index": len(rows), "control_point": name, "name_en": row.name_en, "longitude": float(row.longitude), "latitude": float(row.latitude)})
    out = pd.DataFrame(rows)
    missing = set(margins.control_point.unique()) - set(out.control_point)
    if missing:
        raise ValueError(f"Traffic categories missing from 14-node model: {sorted(missing)}")
    return gpd.GeoDataFrame(out, geometry=gpd.points_from_xy(out.longitude, out.latitude), crs="EPSG:4326")


def port_to_grid_distances(ports: gpd.GeoDataFrame, grid: gpd.GeoDataFrame) -> np.ndarray:
    port_xy = np.column_stack([ports.to_crs(grid.crs).geometry.x, ports.to_crs(grid.crs).geometry.y])
    centroids = grid.geometry.centroid
    grid_xy = np.column_stack([centroids.x, centroids.y])
    return cdist(port_xy, grid_xy).astype(np.float32)


def destination_profile(base: np.ndarray, distances_m: np.ndarray, purpose: str) -> np.ndarray:
    scale = DISTANCE_SCALE_KM.get(purpose, 12.0) * 1000.0
    return normalize(base * np.exp(-distances_m / scale))


def purpose_rows(priors: pd.DataFrame, segment: str) -> list[tuple[str, float]]:
    subset = priors[priors.person_segment == segment]
    if subset.empty:
        return [("other", 1.0)]
    return list(subset[["purpose", "share"]].itertuples(index=False, name=None))


def internal_matrix(origin_weights: np.ndarray, destination_weights: np.ndarray, distance: np.ndarray, total: float, scale_km: float) -> np.ndarray:
    kernel = np.exp(-distance.astype(np.float64) / (scale_km * 1000.0)) * destination_weights[None, :]
    np.fill_diagonal(kernel, 0.0)
    row_sum = kernel.sum(axis=1)
    valid = row_sum > 0
    kernel[valid] /= row_sum[valid, None]
    result = origin_weights[:, None] * total * kernel
    result[~np.isfinite(result)] = 0
    np.fill_diagonal(result, 0.0)
    correction = total / result.sum() if result.sum() else 1.0
    return (result * correction).astype(np.float32)


def build_hour_profiles() -> pd.DataFrame:
    hours = np.arange(24)
    hotel = np.zeros(24, dtype=float)
    hotel[[10, 18, 20]] = [0.08, 0.08, 0.10]
    active = np.array([7, 8, 9, 11, 12, 13, 14, 15, 16, 17, 19, 21, 22])
    hotel[active] = 0.74 / len(active)
    same = np.zeros(24, dtype=float)
    window = np.arange(10, 20)
    triangle = np.array([1.0, 1.3, 1.8, 2.2, 2.2, 1.8, 1.4, 1.1, 0.8, 0.6])
    same[window] = 0.90 * triangle / triangle.sum()
    outside = np.array([7, 8, 9, 20, 21, 22])
    same[outside] = 0.10 / len(outside)
    return pd.DataFrame({"hour": hours, "same_day_share": same, "overnight_share": hotel})


def save_npz_matrix(path: Path, matrix: np.ndarray, **metadata: object) -> None:
    np.savez_compressed(path, data=matrix.astype(np.float32), metadata=json.dumps(metadata, ensure_ascii=False))


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "unclassified"


def main() -> None:
    args = parse_args()
    out = args.out_dir or args.data_root / "tourism/hongkong/processed/arrival_departure_od_2026_typical_weekday"
    prepared = args.prepared_dir or out / "prepared_inputs"
    out.mkdir(parents=True, exist_ok=True)
    (out / "segmented_matrices").mkdir(exist_ok=True)
    (out / "validation").mkdir(exist_ok=True)

    p = paths(args.data_root)
    hotel_districts = pd.read_csv(prepared / "hotel_district_capacity_2026_05.csv")
    grid, distance, population, attractions = load_grid_features(p, hotel_districts)
    n = len(grid)
    margins = pd.read_csv(prepared / "typical_weekday_bcp_category_margins.csv")
    priors = pd.read_csv(prepared / "purpose_priors.csv")
    ports = load_control_points(p["control_points"], margins)
    ports.to_crs("EPSG:4326").drop(columns="geometry").to_csv(out / "model_control_points_14.csv", index=False, encoding="utf-8-sig")
    bcp_distance = port_to_grid_distances(ports, grid)

    arrival = np.zeros((len(ports), n), dtype=np.float64)
    departure = np.zeros((n, len(ports)), dtype=np.float64)
    resident_events: list[dict[str, object]] = []
    edge_rows: list[dict[str, object]] = []
    cohort_frames: list[pd.DataFrame] = []
    segment_arrival_profiles: dict[str, np.ndarray] = {}
    segment_purpose_profiles: dict[tuple[str, str], np.ndarray] = {}
    category_arrival = {c: np.zeros((len(ports), n), dtype=np.float64) for c in ["hk_resident", "mainland_visitor", "other_visitor"]}
    category_departure = {c: np.zeros((n, len(ports)), dtype=np.float64) for c in ["hk_resident", "mainland_visitor", "other_visitor"]}

    bcp_index = dict(zip(ports.control_point, ports.bcp_index))
    resident_split = 116600 / (319800 + 116600)
    for _, margin in margins.iterrows():
        b = bcp_index[margin.control_point]
        amount = float(margin.passenger_movements)
        category = margin.traveller_category
        direction = margin.direction
        row_alloc = np.zeros(n, dtype=np.float64)
        if category == "hk_resident":
            mainland_amount = amount * resident_split if margin.control_point in MAINLAND_PORTS else 0.0
            usual_amount = amount - mainland_amount
            home_profile = destination_profile(attractions["residential"], bcp_distance[b], "vfr")
            if direction == "arrival":
                arrival[b] += usual_amount * home_profile
            else:
                departure[:, b] += usual_amount * home_profile
            row_alloc += usual_amount * home_profile
            nz = np.flatnonzero(home_profile > 0)
            resident_events.extend({
                "direction": direction, "person_segment": "hk_usual_resident", "control_point": margin.control_point,
                "grid_index": int(g), "passenger_movements": float(usual_amount * home_profile[g]), "unit": "border_passenger_movements",
            } for g in nz if usual_amount * home_profile[g] >= 0.01)

            if mainland_amount > 0:
                rows = purpose_rows(priors, "hk_resident_mainland")
                for purpose, share in rows:
                    profile = destination_profile(attractions.get(purpose, attractions["other"]), bcp_distance[b], purpose)
                    flow = mainland_amount * share
                    if direction == "arrival":
                        arrival[b] += flow * profile
                    else:
                        departure[:, b] += flow * profile
                    row_alloc += flow * profile
                    resident_events.extend({
                        "direction": direction, "person_segment": f"hk_resident_mainland_{purpose}", "control_point": margin.control_point,
                        "grid_index": int(g), "passenger_movements": float(flow * profile[g]), "unit": "border_passenger_movements",
                    } for g in np.flatnonzero(profile > 0) if flow * profile[g] >= 0.01)
            if direction == "arrival":
                category_arrival[category][b] += row_alloc
            else:
                category_departure[category][:, b] += row_alloc
            continue

        overnight_share = OVERNIGHT_SHARE[category]
        for stay_type, stay_share in [("same_day", 1 - overnight_share), ("overnight", overnight_share)]:
            person_segment = f"{category}_{stay_type}"
            source_segment = category
            for purpose, purpose_share in purpose_rows(priors, source_segment):
                purpose_key = "sightseeing" if purpose == "leisure" and stay_type == "overnight" else purpose
                profile = destination_profile(attractions.get(purpose_key, attractions["other"]), bcp_distance[b], purpose_key)
                flow = amount * stay_share * purpose_share
                if direction == "arrival":
                    arrival[b] += flow * profile
                    segment_arrival_profiles[person_segment] = segment_arrival_profiles.get(person_segment, np.zeros(n)) + flow * profile
                    segment_purpose_profiles[(person_segment, purpose_key)] = segment_purpose_profiles.get((person_segment, purpose_key), np.zeros(n)) + flow * profile
                    keep = flow * profile >= args.minimum_cohort_flow
                    if keep.any():
                        g = np.flatnonzero(keep)
                        frame = pd.DataFrame({
                            "day_type": "typical_weekday", "person_segment": person_segment,
                            "immigration_category": category, "arrival_control_point": margin.control_point,
                            "departure_control_point_distribution": "category_specific_typical_departure_margin",
                            "purpose": purpose_key, "stay_type": stay_type,
                            "expected_stay_nights": 0.0 if stay_type == "same_day" else 3.1,
                            "activity_grid_index": g, "sample_weight": flow * profile[g],
                            "mechanized_trips_per_visitor_day": 2.51 if stay_type == "same_day" else 2.48,
                            "unit": "weighted_visitor_cohort",
                        })
                        cohort_frames.append(frame)
                else:
                    departure[:, b] += flow * profile
                row_alloc += flow * profile
        if direction == "arrival":
            category_arrival[category][b] += row_alloc
        else:
            category_departure[category][:, b] += row_alloc

    np.save(out / "arrival_bcp_to_grid.npy", arrival.astype(np.float32))
    np.save(out / "departure_grid_to_bcp.npy", departure.astype(np.float32))
    for category, matrix in category_arrival.items():
        save_npz_matrix(out / f"segmented_matrices/arrival_{category}.npz", matrix, category=category, direction="arrival", unit="border_passenger_movements")
    for category, matrix in category_departure.items():
        save_npz_matrix(out / f"segmented_matrices/departure_{category}.npz", matrix, category=category, direction="departure", unit="border_passenger_movements")

    residents = pd.DataFrame(resident_events)
    residents.to_parquet(out / "resident_border_events.parquet", index=False)
    tours = pd.concat(cohort_frames, ignore_index=True)
    tours.insert(0, "cohort_id", np.arange(len(tours), dtype=np.int64))
    tours.to_parquet(out / "synthetic_visitor_tours.parquet", index=False)

    centroids_wgs = gpd.GeoSeries(grid.geometry.centroid, crs=grid.crs).to_crs("EPSG:4326")
    for b, port in ports.iterrows():
        for g in np.flatnonzero(arrival[b] >= 0.01):
            edge_rows.append({"direction": "arrival", "control_point": port.control_point, "bcp_index": int(b), "grid_index": int(g), "flow": float(arrival[b, g]), "from_lon": port.longitude, "from_lat": port.latitude, "to_lon": centroids_wgs.iloc[g].x, "to_lat": centroids_wgs.iloc[g].y})
        for g in np.flatnonzero(departure[:, b] >= 0.01):
            edge_rows.append({"direction": "departure", "control_point": port.control_point, "bcp_index": int(b), "grid_index": int(g), "flow": float(departure[g, b]), "from_lon": centroids_wgs.iloc[g].x, "from_lat": centroids_wgs.iloc[g].y, "to_lon": port.longitude, "to_lat": port.latitude})
    pd.DataFrame(edge_rows).to_parquet(out / "border_internal_od_edges.parquet", index=False)

    internal_by_stay = {"same_day": np.zeros((n, n), dtype=np.float32), "overnight": np.zeros((n, n), dtype=np.float32)}
    internal_by_person = {segment: np.zeros((n, n), dtype=np.float32) for segment in segment_arrival_profiles}
    purpose_names = sorted({purpose for _, purpose in segment_purpose_profiles})
    internal_by_purpose = {purpose: np.zeros((n, n), dtype=np.float32) for purpose in purpose_names}
    for (segment, purpose), profile in segment_purpose_profiles.items():
        stay_type = "same_day" if segment.endswith("same_day") else "overnight"
        count = float(profile.sum())
        if stay_type == "overnight":
            origin = normalize(0.80 * attractions["hotel"] + 0.20 * attractions["residential"])
            total_trips = count * 4.1 * 2.48
            scale = 16.0
        else:
            origin = normalize(profile)
            total_trips = count * 2.51
            scale = 14.0
        destination = attractions.get(purpose, attractions["other"])
        contribution = internal_matrix(origin, destination, distance, total_trips, scale)
        internal_by_stay[stay_type] += contribution
        internal_by_person[segment] += contribution
        internal_by_purpose[purpose] += contribution

    visitor_internal = internal_by_stay["same_day"] + internal_by_stay["overnight"]
    np.fill_diagonal(visitor_internal, 0)
    np.save(out / "visitor_internal_grid_od.npy", visitor_internal.astype(np.float32))
    save_npz_matrix(out / "segmented_matrices/internal_same_day.npz", internal_by_stay["same_day"], segment="same_day", unit="internal_mechanized_trips")
    save_npz_matrix(out / "segmented_matrices/internal_overnight.npz", internal_by_stay["overnight"], segment="overnight", unit="internal_mechanized_trips")
    for segment, matrix in internal_by_person.items():
        save_npz_matrix(out / f"segmented_matrices/population_{segment}.npz", matrix, person_segment=segment, unit="internal_mechanized_trips")
    for purpose, matrix in internal_by_purpose.items():
        save_npz_matrix(out / f"segmented_matrices/purpose_{safe_slug(purpose)}.npz", matrix, purpose=purpose, unit="internal_mechanized_trips")

    for mode in MODE_SHARES["same_day"]:
        matrix = internal_by_stay["same_day"] * MODE_SHARES["same_day"][mode] + internal_by_stay["overnight"] * MODE_SHARES["overnight"][mode]
        save_npz_matrix(out / f"segmented_matrices/mode_{mode}.npz", matrix, mode=mode, unit="internal_mechanized_trips")

    hours = build_hour_profiles()
    hours.to_csv(out / "time_profile.csv", index=False)
    hotel_validation = hotel_districts[["hotel_district", "capacity_share"]].copy()
    hotel_validation["modeled_hotel_component_share"] = hotel_validation["capacity_share"] * 0.97
    hotel_validation = pd.concat([
        hotel_validation,
        pd.DataFrame([{"hotel_district": "population_weighted_residential_fallback", "capacity_share": 0.0, "modeled_hotel_component_share": 0.03}]),
    ], ignore_index=True)
    hotel_validation.to_csv(out / "validation/hotel_district_weight_validation.csv", index=False)
    periods = {
        "other_00_06_23": [0, 1, 2, 3, 4, 5, 6, 23],
        "morning_07_11": range(7, 12),
        "midday_12_15": range(12, 16),
        "evening_16_19": range(16, 20),
        "night_20_22": range(20, 23),
    }
    for name, h in periods.items():
        same_share = float(hours.loc[hours.hour.isin(h), "same_day_share"].sum())
        overnight_share = float(hours.loc[hours.hour.isin(h), "overnight_share"].sum())
        matrix = internal_by_stay["same_day"] * same_share + internal_by_stay["overnight"] * overnight_share
        save_npz_matrix(out / f"segmented_matrices/time_{name}.npz", matrix, period=name, unit="internal_mechanized_trips")

    # A representative eight-week calendar makes boundary stocks explicit.
    weekend_margin_rows = pd.read_csv(prepared / "typical_weekend_bcp_category_margins.csv")
    dates = pd.date_range("2026-05-04", periods=56, freq="D")
    calendar_margin_rows = []
    for date in dates:
        source = weekend_margin_rows if date.dayofweek >= 5 else margins
        frame = source[["direction", "traveller_category", "control_point", "passenger_movements"]].copy()
        frame.insert(0, "day_type", "weekend" if date.dayofweek >= 5 else "weekday")
        frame.insert(0, "date", date.date().isoformat())
        calendar_margin_rows.append(frame)
    calendar_margins = pd.concat(calendar_margin_rows, ignore_index=True)
    calendar_margins.to_csv(out / "representative_calendar_bcp_margins_56day.csv", index=False)
    calendar_totals = calendar_margins.groupby(["date", "day_type", "direction"], as_index=False).passenger_movements.sum()
    calendar_totals.pivot(index=["date", "day_type"], columns="direction", values="passenger_movements").reset_index().to_csv(
        out / "representative_calendar_56day.csv", index=False
    )

    stock_rows = []
    carry_summary = {}
    daily_category = calendar_margins.groupby(["date", "traveller_category", "direction"], as_index=False).passenger_movements.sum()
    for category, group in daily_category.groupby("traveller_category"):
        pivot = group.pivot(index="date", columns="direction", values="passenger_movements").fillna(0).reset_index()
        pivot["net"] = pivot.get("arrival", 0) - pivot.get("departure", 0)
        raw_balance = pivot["net"].cumsum()
        carry_in_category = max(0.0, -float(min(0.0, raw_balance.min())))
        pivot["stock_after_carry"] = raw_balance + carry_in_category
        pivot["traveller_category"] = category
        stock_rows.append(pivot)
        carry_summary[category] = {
            "carry_in": carry_in_category,
            "carry_out": float(pivot.stock_after_carry.iloc[-1]),
            "note": "Boundary stock required by repeated median day-type margins; not an observed unique-person stock.",
        }
    pd.concat(stock_rows, ignore_index=True).to_csv(out / "representative_calendar_stock_balance_56day.csv", index=False)

    validation_rows = []
    for direction, matrix_total in [("arrival", arrival.sum()), ("departure", departure.sum())]:
        target = float(margins.loc[margins.direction == direction, "passenger_movements"].sum())
        validation_rows.append({"check": f"{direction}_total", "target": target, "modeled": float(matrix_total), "absolute_error": abs(target - matrix_total)})
    for _, target_row in margins.iterrows():
        b = bcp_index[target_row.control_point]
        category = target_row.traveller_category
        if target_row.direction == "arrival":
            modeled = category_arrival[category][b].sum()
        else:
            modeled = category_departure[category][:, b].sum()
        validation_rows.append({
            "check": f"{target_row.direction}:{category}:{target_row.control_point}",
            "target": float(target_row.passenger_movements), "modeled": float(modeled),
            "absolute_error": abs(float(target_row.passenger_movements) - float(modeled)),
        })
    validation = pd.DataFrame(validation_rows)
    validation.to_csv(out / "validation/matrix_conservation.csv", index=False)

    manifest = {
        "scenario": "2026_typical_weekday",
        "grid_count": n,
        "control_point_count": len(ports),
        "control_point_order": ports.control_point.tolist(),
        "grid_order": "regions.shp row order; grid_index is zero-based",
        "matrices": {
            "arrival_bcp_to_grid.npy": {"shape": [14, n], "unit": "border_passenger_movements"},
            "departure_grid_to_bcp.npy": {"shape": [n, 14], "unit": "border_passenger_movements"},
            "visitor_internal_grid_od.npy": {"shape": [n, n], "unit": "internal_mechanized_trips_per_typical_day"},
            "segmented_matrices/*.npz": {"storage": "dense_float32_compressed", "unit": "internal_mechanized_trips"},
        },
        "population_units": {
            "border_passenger_movements": "immigration clearance movements, not unique persons",
            "weighted_visitor_cohort": "synthetic cohort weight",
            "visitor_days": "overnight visitor arrivals multiplied by 4.1 days; same-day by one day",
            "internal_mechanized_trips": "visitor-days multiplied by TCS trip rates",
        },
    }
    (out / "matrix_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "typical_weekday_arrival_border_movements": float(arrival.sum()),
        "typical_weekday_departure_border_movements": float(departure.sum()),
        "weighted_arrival_visitor_cohorts": float(tours.sample_weight.sum()),
        "visitor_internal_mechanized_trips": float(visitor_internal.sum()),
        "same_day_internal_mechanized_trips": float(internal_by_stay["same_day"].sum()),
        "overnight_internal_mechanized_trips": float(internal_by_stay["overnight"].sum()),
        "representative_calendar_days": 56,
        "calendar_carry_by_immigration_category": carry_summary,
        "resident_mainland_share_baseline": resident_split,
        "spatial_status": "constrained synthetic OD; no observed control-point-to-destination matrix exists",
        "all_finite": bool(np.isfinite(arrival).all() and np.isfinite(departure).all() and np.isfinite(visitor_internal).all()),
        "diagonal_zero": bool(np.max(np.abs(np.diag(visitor_internal))) == 0),
    }
    (out / "generation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
