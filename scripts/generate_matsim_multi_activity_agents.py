"""Generate age/sex-informed multi-activity MATSim population plans.

This v2 generator keeps the WEDAN OD matrix as the work-commute backbone,
but no longer treats every person as a commuter. Home zones and person types
are sampled from WorldPop age/sex features per grid cell; daily chains then
add school, shopping, leisure, restaurant, and medical activities using POI
attractiveness and distance decay.

The output is coordinate-based MATSim population_v6 XML without link IDs.
Routing can be applied in a later step using the existing MATSim network.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import pathlib
import time
from dataclasses import dataclass
from typing import Iterable
from xml.sax.saxutils import escape

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rasterio.mask
from pyproj import Transformer
from rasterio.transform import xy as raster_xy
from shapely.geometry import Point, mapping
from shapely.ops import transform as shapely_transform


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
CITY_KEY = "fuzhou_city_23_greenspace_grid"
TARGET_CRS = "EPSG:32650"
WGS84 = "EPSG:4326"

FEATURE_ROOT = PROJECT_ROOT / "data" / "worldcommuting_od" / "custom_features" / CITY_KEY
GLOBAL_CITY_ROOT = FEATURE_ROOT / "GeneratingCodeData" / "data" / "global_cities" / CITY_KEY

DEFAULT_GENERATION = FEATURE_ROOT / "CommutingODFlows" / CITY_KEY / "generation.npy"
DEFAULT_REGIONS = FEATURE_ROOT / "CityAndRegionSplit" / CITY_KEY / "regions.shp"
DEFAULT_WORLDPOP = GLOBAL_CITY_ROOT / "nfeat" / "worldpop.npy"
DEFAULT_DEMOS = GLOBAL_CITY_ROOT / "nfeat" / "demos.npy"
DEFAULT_DEMOS_BANDS = GLOBAL_CITY_ROOT / "nfeat" / "demos_bands.json"
DEFAULT_DIS = GLOBAL_CITY_ROOT / "adj" / "dis.npy"
DEFAULT_POPULATION_RASTER = (
    PROJECT_ROOT
    / "data"
    / "gee"
    / "fuzhou_city_23"
    / "worldpop_age_sex"
    / "worldpop_CHN_2020_pop_age_sex_fuzhou_city_23_greenspace_boundary.tif"
)
DEFAULT_POIS = PROJECT_ROOT / "data" / "osm" / "fuzhou_city_23" / "fuzhou_city_23_osm_pois.geojson"
DEFAULT_OUT_DIR = PROJECT_ROOT / "data" / "matsim_agents" / f"{CITY_KEY}_multi_activity"

AGE_BANDS = [0, 1, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80]
DEFAULT_DEMO_BANDS = [f"M_{age}" for age in AGE_BANDS] + [f"F_{age}" for age in AGE_BANDS]

ACTIVITY_TYPES = ["work", "school", "shop", "leisure", "restaurant", "medical"]
ACTIVITY_ALIAS = {
    "w": "work",
    "w_night": "work",
    "leisure_night": "leisure",
}
POI_CATEGORY_VALUES: dict[str, dict[str, set[str]]] = {
    "work": {
        "office": {"company", "government", "administrative", "association", "it", "lawyer", "accountant"},
        "industrial": {"industrial", "factory", "warehouse"},
        "landuse": {"commercial", "industrial", "retail"},
        "amenity": {"bank", "post_office", "courthouse", "townhall", "school", "university", "hospital", "clinic"},
        "shop": {"mall", "department_store", "supermarket", "convenience", "retail"},
    },
    "school": {
        "amenity": {"kindergarten", "school", "college", "university", "language_school", "music_school"},
    },
    "shop": {
        "shop": {
            "supermarket",
            "mall",
            "department_store",
            "convenience",
            "marketplace",
            "clothes",
            "bakery",
            "greengrocer",
            "retail",
        },
        "amenity": {"marketplace"},
        "landuse": {"retail", "commercial"},
    },
    "leisure": {
        "leisure": {"park", "sports_centre", "fitness_centre", "stadium", "playground", "garden", "pitch"},
        "tourism": {"attraction", "museum", "hotel", "viewpoint", "theme_park", "zoo"},
        "amenity": {"cinema", "theatre", "community_centre", "library", "restaurant", "cafe", "bar"},
        "sport": {"basketball", "soccer", "tennis", "swimming", "badminton"},
    },
    "restaurant": {
        "amenity": {"restaurant", "fast_food", "cafe", "food_court", "bar", "pub"},
    },
    "medical": {
        "amenity": {"hospital", "clinic", "doctors", "dentist", "pharmacy"},
        "healthcare": {"hospital", "clinic", "doctor", "dentist", "pharmacy", "yes"},
    },
}

CHAIN_TEMPLATES: dict[str, list[tuple[str, list[str], float]]] = {
    "worker": [
        ("worker_basic", ["h", "w", "h"], 0.50),
        ("worker_shop", ["h", "w", "shop", "h"], 0.20),
        ("worker_leisure", ["h", "w", "leisure", "h"], 0.10),
        ("worker_dinner", ["h", "w", "restaurant", "h"], 0.10),
        ("worker_lunch", ["h", "w", "restaurant", "w", "h"], 0.10),
    ],
    "student": [
        ("student_basic", ["h", "school", "h"], 0.75),
        ("student_leisure", ["h", "school", "leisure", "h"], 0.15),
        ("student_shop", ["h", "school", "shop", "h"], 0.10),
    ],
    "retired": [
        ("home_shop", ["h", "shop", "h"], 0.35),
        ("home_medical", ["h", "medical", "h"], 0.15),
        ("home_leisure", ["h", "leisure", "h"], 0.30),
        ("home_multi", ["h", "shop", "leisure", "h"], 0.20),
    ],
    "non_worker_adult": [
        ("home_shop", ["h", "shop", "h"], 0.35),
        ("home_medical", ["h", "medical", "h"], 0.10),
        ("home_leisure", ["h", "leisure", "h"], 0.35),
        ("home_multi", ["h", "shop", "leisure", "h"], 0.20),
    ],
    "family_worker": [
        ("dropoff_work_pickup", ["h", "school", "w", "school", "h"], 0.60),
        ("dropoff_work_shop_pickup", ["h", "school", "w", "shop", "school", "h"], 0.25),
        ("work_pickup_leisure", ["h", "w", "school", "leisure", "h"], 0.15),
    ],
    "night_shift_worker": [
        ("night_shift_basic", ["h", "w_night", "h"], 0.70),
        ("night_shift_restaurant", ["h", "restaurant", "w_night", "h"], 0.30),
    ],
    "night_leisure_agent": [
        ("night_leisure_basic", ["h", "leisure_night", "h"], 0.60),
        ("night_restaurant_leisure", ["h", "restaurant", "leisure_night", "h"], 0.40),
    ],
}

HALF_LIFE_KM = {
    "work": 15.0,
    "school": 3.0,
    "shop": 4.0,
    "leisure": 7.0,
    "restaurant": 3.0,
    "medical": 10.0,
    "w_night": 15.0,
    "leisure_night": 7.0,
}


@dataclass
class ZonePopulationCandidates:
    xs: np.ndarray
    ys: np.ndarray
    weights: np.ndarray


@dataclass
class PointSample:
    x: float
    y: float
    method: str


@dataclass
class ActivitySpec:
    act_type: str
    zone_idx: int
    zone_id: str
    point: PointSample
    end_time: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate multi-activity MATSim plans from WEDAN + WorldPop.")
    parser.add_argument("--generation", default=str(DEFAULT_GENERATION), help="WEDAN generation.npy OD matrix.")
    parser.add_argument("--regions", default=str(DEFAULT_REGIONS), help="Grid regions.shp.")
    parser.add_argument("--worldpop", default=str(DEFAULT_WORLDPOP), help="WorldPop zone population features.")
    parser.add_argument("--demos", default=str(DEFAULT_DEMOS), help="WorldPop age/sex zone features.")
    parser.add_argument("--demos-bands", default=str(DEFAULT_DEMOS_BANDS), help="demos.npy band names JSON.")
    parser.add_argument("--distance", default=str(DEFAULT_DIS), help="Zone distance matrix dis.npy.")
    parser.add_argument("--population-raster", default=str(DEFAULT_POPULATION_RASTER), help="WorldPop raster for home sampling.")
    parser.add_argument("--pois", default=str(DEFAULT_POIS), help="OSM POI GeoJSON.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output directory.")
    parser.add_argument("--target-agents", type=int, default=30_000, help="Target number of sampled agents.")
    parser.add_argument(
        "--target-population-share",
        type=float,
        default=None,
        help="If set, derive target agents from WorldPop total population times this share. Overrides --target-agents.",
    )
    parser.add_argument("--night-agent-share", type=float, default=0.0, help="Share of agents reassigned to night templates.")
    parser.add_argument("--night-shift-share", type=float, default=0.0, help="Share of all agents assigned to night-shift work.")
    parser.add_argument("--night-leisure-share", type=float, default=0.0, help="Share of all agents assigned to late-night leisure.")
    parser.add_argument(
        "--same-day-night",
        action="store_true",
        help="Keep night templates within the same service day; no activity end_time reaches 24:00:00.",
    )
    parser.add_argument("--seed", type=int, default=20260704, help="Random seed.")
    parser.add_argument("--mode", default="car", help="MATSim leg mode.")
    parser.add_argument("--crs", default=TARGET_CRS, help="Projected CRS for MATSim coordinates.")
    parser.add_argument("--intra-work-rate", type=float, default=0.15, help="Synthetic intra-zone work flow as share of outbound work flow.")
    return parser.parse_args()


def ensure_exists(path: pathlib.Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")


def safe_zone_id(regions: gpd.GeoDataFrame) -> pd.Series:
    for column in ("locations", "region_id", "id", "ID", "grid_id"):
        if column in regions.columns:
            return regions[column].astype(str)
    return pd.Series(np.arange(len(regions), dtype=int).astype(str), index=regions.index)


def seconds_to_hms(seconds: float) -> str:
    seconds = int(round(seconds))
    seconds = max(0, min(seconds, 47 * 3600 + 59 * 60 + 59))
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def xml_attr(value: object) -> str:
    return escape(str(value), {'"': "&quot;"})


def xml_text(value: object) -> str:
    return escape(str(value))


def normalize_weights(weights: np.ndarray) -> np.ndarray | None:
    weights = np.asarray(weights, dtype="float64")
    weights = np.where(np.isfinite(weights) & (weights > 0), weights, 0.0)
    total = float(weights.sum())
    if total <= 0:
        return None
    return weights / total


def integerize_vector(expected: np.ndarray, target_total: int, rng: np.random.Generator) -> np.ndarray:
    expected = np.asarray(expected, dtype="float64")
    expected = np.where(np.isfinite(expected) & (expected > 0), expected, 0.0)
    if target_total <= 0:
        raise ValueError("target total must be positive")
    if float(expected.sum()) <= 0:
        raise ValueError("cannot integerize an all-zero vector")
    scaled = expected * (target_total / float(expected.sum()))
    base = np.floor(scaled).astype("int64")
    remaining = int(target_total - base.sum())
    if remaining > 0:
        residual = scaled - base
        probs = normalize_weights(residual)
        if probs is None:
            probs = normalize_weights(scaled)
        chosen = rng.choice(len(base), size=remaining, replace=remaining > len(base), p=probs)
        for idx in chosen:
            base[int(idx)] += 1
    elif remaining < 0:
        probs = normalize_weights(base)
        chosen = rng.choice(len(base), size=abs(remaining), replace=True, p=probs)
        for idx in chosen:
            if base[int(idx)] > 0:
                base[int(idx)] -= 1
    return base


def load_core_inputs(args: argparse.Namespace) -> tuple[np.ndarray, gpd.GeoDataFrame, np.ndarray, np.ndarray, list[str], np.ndarray]:
    paths = {
        "generation.npy": pathlib.Path(args.generation),
        "regions.shp": pathlib.Path(args.regions),
        "worldpop.npy": pathlib.Path(args.worldpop),
        "demos.npy": pathlib.Path(args.demos),
        "dis.npy": pathlib.Path(args.distance),
    }
    for label, path in paths.items():
        ensure_exists(path, label)

    od = np.load(paths["generation.npy"]).astype("float64")
    worldpop = np.load(paths["worldpop.npy"]).astype("float64")
    demos = np.load(paths["demos.npy"]).astype("float64")
    dis = np.load(paths["dis.npy"]).astype("float64")

    bands_path = pathlib.Path(args.demos_bands)
    if bands_path.exists():
        bands = json.loads(bands_path.read_text(encoding="utf-8"))
    else:
        bands = DEFAULT_DEMO_BANDS

    regions = gpd.read_file(paths["regions.shp"]).to_crs(args.crs).reset_index(drop=True)
    regions["zone_index"] = np.arange(len(regions), dtype=int)
    regions["zone_id"] = safe_zone_id(regions).to_numpy()

    n = len(regions)
    if od.shape != (n, n):
        raise ValueError(f"generation shape {od.shape} does not match regions count {n}")
    if dis.shape != (n, n):
        raise ValueError(f"distance shape {dis.shape} does not match regions count {n}")
    if worldpop.shape[0] != n or worldpop.shape[1] < 1:
        raise ValueError(f"worldpop shape {worldpop.shape} does not match regions count {n}")
    if demos.shape != (n, len(bands)):
        raise ValueError(f"demos shape {demos.shape} does not match bands count {len(bands)} and regions count {n}")
    if len(bands) != 36:
        raise ValueError(f"Expected 36 age/sex bands, got {len(bands)}")

    od = np.where(np.isfinite(od) & (od > 0), od, 0.0)
    np.fill_diagonal(od, 0.0)
    dis = np.where(np.isfinite(dis) & (dis >= 0), dis, 0.0)
    worldpop = np.where(np.isfinite(worldpop), worldpop, 0.0)
    demos = np.where(np.isfinite(demos) & (demos > 0), demos, 0.0)
    return od, regions, worldpop, demos, bands, dis


def aggregate_age_sex(demos: np.ndarray, bands: list[str], worldpop: np.ndarray, regions: gpd.GeoDataFrame) -> pd.DataFrame:
    band_index = {band: idx for idx, band in enumerate(bands)}

    def band_sum(prefix: str, ages: Iterable[int]) -> np.ndarray:
        cols = [band_index[f"{prefix}_{age}"] for age in ages if f"{prefix}_{age}" in band_index]
        if not cols:
            return np.zeros(demos.shape[0], dtype="float64")
        return demos[:, cols].sum(axis=1)

    male = band_sum("M", AGE_BANDS)
    female = band_sum("F", AGE_BANDS)
    child = band_sum("M", [0, 1, 5, 10, 15]) + band_sum("F", [0, 1, 5, 10, 15])
    adult = band_sum("M", [20, 25, 30, 35, 40, 45, 50, 55, 60]) + band_sum("F", [20, 25, 30, 35, 40, 45, 50, 55, 60])
    senior = band_sum("M", [65, 70, 75, 80]) + band_sum("F", [65, 70, 75, 80])
    demo_total = male + female
    population = np.where(worldpop[:, 0] > 0, worldpop[:, 0], demo_total)
    safe_total = np.where(demo_total > 0, demo_total, np.nan)
    df = pd.DataFrame(
        {
            "zone_index": np.arange(len(regions), dtype=int),
            "zone_id": regions["zone_id"].astype(str).to_numpy(),
            "population_total": population,
            "age_sex_total": demo_total,
            "male_population": male,
            "female_population": female,
            "child_0_19_population": child,
            "adult_20_64_population": adult,
            "senior_65_plus_population": senior,
            "child_0_19_share": np.nan_to_num(child / safe_total),
            "adult_20_64_share": np.nan_to_num(adult / safe_total),
            "senior_65_plus_share": np.nan_to_num(senior / safe_total),
        }
    )
    return df


def age_from_band(band: str) -> tuple[str, int]:
    sex, age = band.split("_", 1)
    return sex, int(age)


def labor_participation_probability(sex: str, age: int) -> float:
    if age < 20 or age >= 65:
        return 0.0
    if age == 20:
        return 0.58 if sex == "M" else 0.52
    if 25 <= age <= 50:
        return 0.84 if sex == "M" else 0.72
    if age == 55:
        return 0.68 if sex == "M" else 0.48
    if age == 60:
        return 0.38 if sex == "M" else 0.24
    return 0.75 if sex == "M" else 0.62


def family_worker_probability(child_share: float) -> float:
    if not np.isfinite(child_share):
        child_share = 0.0
    return float(np.clip(0.04 + 0.75 * child_share, 0.04, 0.28))


def uniform_point_in_polygon(geom, rng: np.random.Generator, max_attempts: int = 1_000) -> PointSample:
    minx, miny, maxx, maxy = geom.bounds
    for _ in range(max_attempts):
        x = float(rng.uniform(minx, maxx))
        y = float(rng.uniform(miny, maxy))
        point = Point(x, y)
        if geom.contains(point) or geom.touches(point):
            return PointSample(x, y, "polygon_uniform")
    point = geom.representative_point()
    return PointSample(float(point.x), float(point.y), "polygon_representative")


def build_population_candidates(raster_path: pathlib.Path, regions: gpd.GeoDataFrame, target_crs: str) -> dict[int, ZonePopulationCandidates]:
    if not raster_path.exists():
        return {}
    candidates: dict[int, ZonePopulationCandidates] = {}
    with rasterio.open(raster_path) as src:
        if src.crs is None:
            return {}
        to_raster = Transformer.from_crs(target_crs, src.crs, always_xy=True).transform
        to_target = Transformer.from_crs(src.crs, target_crs, always_xy=True).transform
        for idx, geom in enumerate(regions.geometry):
            if geom is None or geom.is_empty:
                continue
            raster_geom = shapely_transform(to_raster, geom)
            try:
                data, out_transform = rasterio.mask.mask(src, [mapping(raster_geom)], crop=True, indexes=1, filled=False)
            except ValueError:
                continue
            arr = np.ma.asarray(data)
            valid = (~np.ma.getmaskarray(arr)) & np.isfinite(arr.filled(0)) & (arr.filled(0) > 0)
            rows, cols = np.where(valid)
            if len(rows) == 0:
                continue
            xs_raster, ys_raster = raster_xy(out_transform, rows, cols, offset="center")
            xs_target, ys_target = to_target(np.asarray(xs_raster, dtype="float64"), np.asarray(ys_raster, dtype="float64"))
            weights = np.asarray(arr.filled(0)[rows, cols], dtype="float64")
            probs = normalize_weights(weights)
            if probs is not None:
                candidates[idx] = ZonePopulationCandidates(np.asarray(xs_target), np.asarray(ys_target), probs)
    return candidates


def sample_home_point(zone_idx: int, regions: gpd.GeoDataFrame, pop_candidates: dict[int, ZonePopulationCandidates], rng: np.random.Generator) -> PointSample:
    candidates = pop_candidates.get(zone_idx)
    if candidates is not None and len(candidates.xs) > 0:
        picked = int(rng.choice(len(candidates.xs), p=candidates.weights))
        return PointSample(float(candidates.xs[picked]), float(candidates.ys[picked]), "worldpop_weighted_pixel")
    return uniform_point_in_polygon(regions.geometry.iloc[zone_idx], rng)


def load_pois(path: pathlib.Path, regions: gpd.GeoDataFrame, target_crs: str) -> tuple[dict[str, dict[int, np.ndarray]], pd.DataFrame]:
    ensure_exists(path, "OSM POI GeoJSON")
    pois = gpd.read_file(path)
    if pois.crs is None:
        pois = pois.set_crs(WGS84)
    pois = pois.to_crs(target_crs)
    pois = pois[pois.geometry.notna() & ~pois.geometry.is_empty & (pois.geometry.geom_type == "Point")].copy()

    candidates: dict[str, dict[int, list[tuple[float, float]]]] = {act: {} for act in ACTIVITY_TYPES}
    sindex = regions.sindex
    for _, row in pois.iterrows():
        point = row.geometry
        possible = list(sindex.query(point, predicate="contains"))
        if not possible:
            possible = list(sindex.query(point, predicate="intersects"))
        if not possible:
            continue
        zone_idx = int(possible[0])
        categories = classify_poi(row)
        for act in categories:
            candidates[act].setdefault(zone_idx, []).append((float(point.x), float(point.y)))

    arrays: dict[str, dict[int, np.ndarray]] = {}
    rows = []
    for act, by_zone in candidates.items():
        arrays[act] = {zone: np.asarray(points, dtype="float64") for zone, points in by_zone.items() if points}
        for zone, points in arrays[act].items():
            rows.append({"activity_type": act, "zone_index": zone, "poi_count": int(len(points))})
    return arrays, pd.DataFrame(rows)


def classify_poi(row: pd.Series) -> set[str]:
    matched: set[str] = set()
    for activity, column_values in POI_CATEGORY_VALUES.items():
        for column, values in column_values.items():
            if column not in row.index:
                continue
            value = row.get(column)
            if value is None or (isinstance(value, float) and math.isnan(value)):
                continue
            value_text = str(value).strip().lower()
            if value_text in values:
                matched.add(activity)
    return matched


def build_attraction_matrix(poi_counts: pd.DataFrame, n_zones: int, population: np.ndarray) -> dict[str, np.ndarray]:
    attractions: dict[str, np.ndarray] = {}
    pop_weight = normalize_weights(population)
    if pop_weight is None:
        pop_weight = np.ones(n_zones, dtype="float64") / n_zones
    for act in ACTIVITY_TYPES:
        arr = np.zeros(n_zones, dtype="float64")
        if not poi_counts.empty:
            sub = poi_counts[poi_counts["activity_type"] == act]
            if not sub.empty:
                arr[sub["zone_index"].to_numpy(dtype=int)] = sub["poi_count"].to_numpy(dtype="float64")
        if float(arr.sum()) <= 0:
            arr = pop_weight.copy()
        attractions[act] = arr
    return attractions


def distance_decay(dis: np.ndarray, origin: int, half_life_km: float) -> np.ndarray:
    km = np.asarray(dis[origin], dtype="float64") / 1000.0
    half_life_km = max(0.1, float(half_life_km))
    return np.exp(-math.log(2.0) * km / half_life_km)


def sample_zone_from_scores(scores: np.ndarray, rng: np.random.Generator, fallback: np.ndarray | None = None) -> int:
    probs = normalize_weights(scores)
    if probs is None and fallback is not None:
        probs = normalize_weights(fallback)
    if probs is None:
        probs = np.ones(len(scores), dtype="float64") / len(scores)
    return int(rng.choice(len(scores), p=probs))


def sample_work_zone(
    home_zone: int,
    od: np.ndarray,
    work_attraction: np.ndarray,
    dis: np.ndarray,
    rng: np.random.Generator,
    intra_work_rate: float,
) -> tuple[int, str]:
    row = od[home_zone].copy()
    outflow = float(row.sum())
    if outflow > 0:
        row[home_zone] = max(0.0, intra_work_rate) * outflow
        return sample_zone_from_scores(row, rng), "wedan_od_with_synthetic_intra"
    scores = work_attraction * distance_decay(dis, home_zone, HALF_LIFE_KM["work"])
    scores[home_zone] += max(0.0, intra_work_rate) * max(float(scores.sum()), 1.0)
    return sample_zone_from_scores(scores, rng, fallback=work_attraction), "work_attraction_distance_fallback"


def sample_activity_zone(
    activity: str,
    origin_zone: int,
    attractions: dict[str, np.ndarray],
    dis: np.ndarray,
    population: np.ndarray,
    rng: np.random.Generator,
) -> tuple[int, str]:
    activity = ACTIVITY_ALIAS.get(activity, activity)
    base = attractions.get(activity)
    if base is None:
        base = population
    scores = base * distance_decay(dis, origin_zone, HALF_LIFE_KM.get(activity, 6.0))
    return sample_zone_from_scores(scores, rng, fallback=population), f"{activity}_attraction_distance"


def sample_activity_point(
    activity: str,
    zone_idx: int,
    regions: gpd.GeoDataFrame,
    candidates: dict[str, dict[int, np.ndarray]],
    rng: np.random.Generator,
    dis: np.ndarray | None = None,
) -> PointSample:
    activity = ACTIVITY_ALIAS.get(activity, activity)
    points = candidates.get(activity, {}).get(zone_idx)
    if points is not None and len(points) > 0:
        picked = int(rng.integers(0, len(points)))
        return PointSample(float(points[picked, 0]), float(points[picked, 1]), f"osm_{activity}_poi")

    if dis is not None:
        by_zone = candidates.get(activity, {})
        available = np.asarray(list(by_zone.keys()), dtype=int)
        if len(available) > 0:
            nearest_zone = int(available[np.argmin(dis[zone_idx, available])])
            if float(dis[zone_idx, nearest_zone]) <= 5000:
                points = by_zone[nearest_zone]
                picked = int(rng.integers(0, len(points)))
                return PointSample(float(points[picked, 0]), float(points[picked, 1]), f"nearest_zone_osm_{activity}_poi")

    return uniform_point_in_polygon(regions.geometry.iloc[zone_idx], rng)


def choose_template(agent_type: str, rng: np.random.Generator) -> tuple[str, list[str]]:
    options = CHAIN_TEMPLATES[agent_type]
    probs = np.asarray([x[2] for x in options], dtype="float64")
    probs = probs / probs.sum()
    idx = int(rng.choice(len(options), p=probs))
    return options[idx][0], list(options[idx][1])


def build_night_agent_assignments(
    candidates: list[tuple[int, int, int]],
    total_agents: int,
    night_shift_share: float,
    night_leisure_share: float,
    rng: np.random.Generator,
) -> dict[tuple[int, int], str]:
    """Choose adult agents to be reassigned to night-shift or late-night leisure templates.

    The key is (home zone index, ordinal within that zone's selected age/sex sample).
    This keeps the night selection deterministic without changing the zone-level home
    agent counts or age/sex sampling.
    """
    if not candidates:
        return {}
    candidate_keys = [(zone_idx, local_idx) for zone_idx, local_idx, _age in candidates]
    rng.shuffle(candidate_keys)
    shift_count = min(len(candidate_keys), int(round(max(0.0, night_shift_share) * total_agents)))
    leisure_count = min(len(candidate_keys) - shift_count, int(round(max(0.0, night_leisure_share) * total_agents)))
    assignments: dict[tuple[int, int], str] = {}
    for key in candidate_keys[:shift_count]:
        assignments[key] = "night_shift_worker"
    for key in candidate_keys[shift_count : shift_count + leisure_count]:
        assignments[key] = "night_leisure_agent"
    return assignments


def triangular(rng: np.random.Generator, left_h: float, mode_h: float, right_h: float) -> float:
    return float(rng.triangular(left_h * 3600, mode_h * 3600, right_h * 3600))


def clipped_normal(rng: np.random.Generator, mean_h: float, sd_h: float, low_h: float, high_h: float) -> float:
    return float(np.clip(rng.normal(mean_h * 3600, sd_h * 3600), low_h * 3600, high_h * 3600))


def generate_end_times(
    template_name: str,
    agent_type: str,
    chain: list[str],
    rng: np.random.Generator,
    same_day_night: bool = False,
) -> list[str | None]:
    end: list[float | None] = [None] * len(chain)

    if agent_type == "night_shift_worker":
        if same_day_night:
            end[0] = triangular(rng, 18.5, 19.6, 20.7)
            if template_name == "night_shift_restaurant":
                end[1] = min(float(end[0]) + float(rng.uniform(35 * 60, 75 * 60)), 21.15 * 3600)
                work_idx = 2
            else:
                work_idx = 1
            end[work_idx] = min(
                max(float(end[work_idx - 1] or end[0]) + 2.2 * 3600, triangular(rng, 22.4, 23.1, 23.75)),
                23.75 * 3600,
            )
            current = float(end[work_idx])
        else:
            end[0] = triangular(rng, 20.5, 22.0, 23.5)
            if template_name == "night_shift_restaurant":
                end[1] = float(end[0]) + float(rng.uniform(35 * 60, 90 * 60))
                work_idx = 2
            else:
                work_idx = 1
            end[work_idx] = max(float(end[work_idx - 1] or end[0]) + 7.0 * 3600, triangular(rng, 29.0, 30.0, 32.5))
            current = float(end[work_idx])
    elif agent_type == "night_leisure_agent":
        end[0] = triangular(rng, 19.3, 20.6, 22.0) if same_day_night else triangular(rng, 20.0, 21.5, 23.5)
        if template_name == "night_restaurant_leisure":
            end[1] = float(end[0]) + float(rng.uniform(45 * 60, 95 * 60))
            if same_day_night:
                end[1] = min(float(end[1]), 22.35 * 3600)
            current = float(end[1])
        else:
            current = float(end[0])
    elif agent_type == "student":
        end[0] = triangular(rng, 6.83, 7.42, 8.0)
        school_idx = chain.index("school")
        end[school_idx] = triangular(rng, 15.5, 16.2, 17.5)
        current = float(end[school_idx])
    elif agent_type == "family_worker":
        end[0] = triangular(rng, 6.9, 7.35, 8.0)
        if template_name == "dropoff_work_pickup":
            end[1] = max(float(end[0]) + 20 * 60, triangular(rng, 7.45, 7.75, 8.25))
            end[2] = triangular(rng, 16.2, 17.0, 18.1)
            end[3] = max(float(end[2]) + 20 * 60, triangular(rng, 16.6, 17.25, 18.3))
            current = float(end[3])
        elif template_name == "dropoff_work_shop_pickup":
            end[1] = max(float(end[0]) + 20 * 60, triangular(rng, 7.45, 7.75, 8.25))
            end[2] = triangular(rng, 16.0, 16.7, 17.6)
            end[3] = float(end[2]) + float(rng.uniform(25 * 60, 75 * 60))
            end[4] = max(float(end[3]) + 15 * 60, triangular(rng, 17.0, 17.6, 18.6))
            current = float(end[4])
        else:
            work_idx = chain.index("w")
            end[work_idx] = triangular(rng, 16.2, 17.0, 18.1)
            school_idx = chain.index("school")
            end[school_idx] = max(float(end[work_idx]) + 20 * 60, triangular(rng, 16.7, 17.35, 18.4))
            current = float(end[school_idx])
    elif agent_type == "worker":
        end[0] = triangular(rng, 7.0, 8.0, 9.5)
        if template_name == "worker_lunch":
            first_w = 1
            rest_idx = 2
            second_w = 3
            end[first_w] = triangular(rng, 11.5, 12.0, 13.0)
            end[rest_idx] = float(end[first_w]) + clipped_normal(rng, 0.9, 0.2, 0.5, 1.25)
            end[second_w] = max(float(end[rest_idx]) + 3.0 * 3600, float(end[0]) + clipped_normal(rng, 8.5, 0.45, 7.5, 9.5))
            current = float(end[second_w])
        else:
            work_idx = chain.index("w")
            end[work_idx] = float(end[0]) + clipped_normal(rng, 8.5, 0.45, 7.5, 9.5)
            current = float(end[work_idx])
    else:
        if "medical" in chain:
            end[0] = triangular(rng, 8.5, 9.5, 15.5)
        elif "shop" in chain and rng.random() < 0.45:
            end[0] = triangular(rng, 9.8, 10.8, 12.0)
        else:
            end[0] = triangular(rng, 14.0, 17.5, 19.5)
        current = float(end[0])

    for idx in range(1, len(chain) - 1):
        if end[idx] is not None:
            continue
        act = chain[idx]
        if act == "shop":
            duration = float(rng.uniform(20 * 60, 90 * 60))
        elif act == "restaurant":
            duration = float(rng.uniform(30 * 60, 75 * 60)) if template_name == "worker_lunch" else float(rng.uniform(45 * 60, 120 * 60))
        elif act == "leisure":
            if current < 17.5 * 3600:
                current = max(current, triangular(rng, 17.5, 18.5, 20.0))
            duration = float(rng.uniform(1 * 3600, 3 * 3600))
        elif act == "leisure_night":
            if current < 21.0 * 3600:
                night_right = 22.4 if same_day_night else 23.5
                current = max(current, triangular(rng, 21.0, 22.0, night_right))
            duration = float(rng.uniform(1.0 * 3600, 2.2 * 3600)) if same_day_night else float(rng.uniform(1.5 * 3600, 4.0 * 3600))
        elif act == "medical":
            duration = float(rng.uniform(30 * 60, 120 * 60))
        elif act == "school":
            duration = float(rng.uniform(10 * 60, 35 * 60))
        elif act == "w":
            duration = clipped_normal(rng, 8.0, 0.5, 7.0, 9.5)
        elif act == "w_night":
            duration = clipped_normal(rng, 3.3, 0.5, 2.2, 4.6) if same_day_night else clipped_normal(rng, 8.0, 0.6, 7.0, 9.5)
        else:
            duration = float(rng.uniform(30 * 60, 120 * 60))
        current = max(current + duration, (end[idx - 1] or 0) + 10 * 60)
        if same_day_night and agent_type in {"night_shift_worker", "night_leisure_agent"}:
            current = min(current, 23.75 * 3600)
        end[idx] = current

    return [seconds_to_hms(x) if x is not None else None for x in end]


def write_plans_xml(path: pathlib.Path, person_rows: Iterable[dict], mode: str) -> None:
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as handle:
        handle.write('<?xml version="1.0" encoding="utf-8"?>\n')
        handle.write('<!DOCTYPE population SYSTEM "http://www.matsim.org/files/dtd/population_v6.dtd">\n')
        handle.write("<population>\n")
        for row in person_rows:
            handle.write(f'  <person id="{xml_attr(row["person_id"])}">\n')
            handle.write("    <attributes>\n")
            for name, klass, value in row["attributes"]:
                handle.write(
                    f'      <attribute name="{xml_attr(name)}" class="{xml_attr(klass)}">'
                    f"{xml_text(value)}</attribute>\n"
                )
            handle.write("    </attributes>\n")
            handle.write('    <plan selected="yes">\n')
            activities: list[ActivitySpec] = row["activities"]
            for idx, act in enumerate(activities):
                end_attr = f' end_time="{xml_attr(act.end_time)}"' if act.end_time is not None else ""
                handle.write(
                    f'      <activity type="{xml_attr(act.act_type)}" x="{act.point.x:.3f}" '
                    f'y="{act.point.y:.3f}"{end_attr} />\n'
                )
                if idx < len(activities) - 1:
                    handle.write(f'      <leg mode="{xml_attr(mode)}" />\n')
            handle.write("    </plan>\n")
            handle.write("  </person>\n")
        handle.write("</population>\n")


def validate_activity_points(person_rows: list[dict], regions: gpd.GeoDataFrame) -> int:
    invalid = 0
    for row in person_rows:
        for act in row["activities"]:
            geom = regions.geometry.iloc[int(act.zone_idx)]
            p = Point(act.point.x, act.point.y)
            if act.point.method.startswith("nearest_zone_osm_"):
                continue
            if not (geom.contains(p) or geom.touches(p)):
                invalid += 1
    return invalid


def main() -> None:
    args = parse_args()
    started = time.time()
    rng = np.random.default_rng(args.seed)
    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    od, regions, worldpop, demos, bands, dis = load_core_inputs(args)
    n_zones = len(regions)
    zone_profile = aggregate_age_sex(demos, bands, worldpop, regions)
    zone_profile_path = out_dir / "zone_population_profile.csv"
    zone_profile.to_csv(zone_profile_path, index=False, encoding="utf-8")

    worldpop_population_sum = float(zone_profile["population_total"].sum())
    target_population_share = args.target_population_share
    if target_population_share is not None:
        if not (0 < target_population_share <= 1):
            raise ValueError("--target-population-share must be in (0, 1].")
        args.target_agents = int(round(worldpop_population_sum * target_population_share))
    population_sample_rate = float(args.target_agents / worldpop_population_sum) if worldpop_population_sum > 0 else math.nan
    sample_weight = float(worldpop_population_sum / args.target_agents)

    if args.night_agent_share and (args.night_shift_share or args.night_leisure_share):
        requested = args.night_shift_share + args.night_leisure_share
        if abs(requested - args.night_agent_share) > 1e-9:
            print(
                "Warning: --night-agent-share differs from --night-shift-share + --night-leisure-share; "
                "using the explicit night-shift/night-leisure split."
            )
    elif args.night_agent_share and not (args.night_shift_share or args.night_leisure_share):
        args.night_shift_share = args.night_agent_share * 0.4
        args.night_leisure_share = args.night_agent_share * 0.6

    print(
        f"Loaded {n_zones} zones; assigning {args.target_agents} agents "
        f"by WorldPop zone population (sample_rate={population_sample_rate:.6f})..."
    )
    zone_agent_counts = integerize_vector(zone_profile["population_total"].to_numpy(), args.target_agents, rng)
    zone_profile["sampled_home_agents"] = zone_agent_counts

    print("Preparing spatial sampling candidates...")
    pop_candidates = build_population_candidates(pathlib.Path(args.population_raster), regions, args.crs)
    poi_candidates, poi_counts = load_pois(pathlib.Path(args.pois), regions, args.crs)
    attractions = build_attraction_matrix(poi_counts, n_zones, zone_profile["population_total"].to_numpy())

    transformer_to_wgs84 = Transformer.from_crs(args.crs, WGS84, always_xy=True)
    global_age_probs = normalize_weights(demos.sum(axis=0))
    if global_age_probs is None:
        global_age_probs = np.ones(len(bands), dtype="float64") / len(bands)

    person_rows: list[dict] = []
    debug_rows: list[dict] = []
    point_rows: list[dict] = []
    point_geoms: list[Point] = []
    age_sex_records: list[dict] = []

    selected_bands_by_zone: dict[int, np.ndarray] = {}
    adult_night_candidates: list[tuple[int, int, int]] = []
    age_sex_method_by_zone: dict[int, str] = {}
    local_probs_by_zone: dict[int, np.ndarray] = {}
    for zone_idx, n_agents in enumerate(zone_agent_counts):
        if n_agents <= 0:
            continue
        local_probs = normalize_weights(demos[zone_idx])
        if local_probs is None:
            local_probs = global_age_probs
            age_sex_method = "citywide_age_sex_fallback"
        else:
            age_sex_method = "zone_age_sex"
        selected = rng.choice(len(bands), size=int(n_agents), replace=True, p=local_probs)
        selected_bands_by_zone[int(zone_idx)] = selected
        age_sex_method_by_zone[int(zone_idx)] = age_sex_method
        local_probs_by_zone[int(zone_idx)] = local_probs
        for local_idx, band_idx in enumerate(selected):
            _sex, age = age_from_band(bands[int(band_idx)])
            if 20 <= age < 65:
                adult_night_candidates.append((int(zone_idx), int(local_idx), int(age)))

    night_assignments = build_night_agent_assignments(
        adult_night_candidates,
        args.target_agents,
        args.night_shift_share,
        args.night_leisure_share,
        rng,
    )

    person_idx = 0
    for zone_idx, n_agents in enumerate(zone_agent_counts):
        if n_agents <= 0:
            continue
        age_sex_method = age_sex_method_by_zone[int(zone_idx)]

        selected_bands = selected_bands_by_zone[int(zone_idx)]
        for local_agent_idx, band_idx in enumerate(selected_bands):
            sex, age = age_from_band(bands[int(band_idx)])
            home_zone = int(zone_idx)
            home_zone_id = str(regions["zone_id"].iloc[home_zone])

            night_agent_role = night_assignments.get((int(zone_idx), int(local_agent_idx)), "")
            if night_agent_role:
                agent_type = night_agent_role
            elif age < 20:
                agent_type = "student"
            elif age >= 65:
                agent_type = "retired"
            else:
                p_worker = labor_participation_probability(sex, age)
                if rng.random() < p_worker:
                    p_family = family_worker_probability(float(zone_profile.loc[zone_idx, "child_0_19_share"]))
                    agent_type = "family_worker" if rng.random() < p_family else "worker"
                else:
                    agent_type = "non_worker_adult"

            template_name, chain = choose_template(agent_type, rng)
            end_times = generate_end_times(template_name, agent_type, chain, rng, same_day_night=args.same_day_night)

            home_point = sample_home_point(home_zone, regions, pop_candidates, rng)
            zone_for_role: dict[str, int] = {"h": home_zone}
            od_methods: dict[str, str] = {}

            if "w" in chain or "w_night" in chain:
                work_zone, method = sample_work_zone(
                    home_zone,
                    od,
                    attractions["work"],
                    dis,
                    rng,
                    args.intra_work_rate,
                )
                zone_for_role["w"] = work_zone
                zone_for_role["w_night"] = work_zone
                od_methods["work"] = method

            activity_specs: list[ActivitySpec] = []
            previous_zone = home_zone
            for idx, act in enumerate(chain):
                if act == "h":
                    zone = home_zone
                    point = home_point
                elif act in ("w", "w_night"):
                    zone = zone_for_role[act]
                    point = sample_activity_point("work", zone, regions, poi_candidates, rng, dis)
                else:
                    if act == "school" and act in zone_for_role:
                        zone = zone_for_role[act]
                    elif act != "school" and idx > 0 and act == chain[idx - 1] and act in zone_for_role:
                        zone = zone_for_role[act]
                    else:
                        zone, method = sample_activity_zone(
                            act,
                            previous_zone,
                            attractions,
                            dis,
                            zone_profile["population_total"].to_numpy(),
                            rng,
                        )
                        if act == "school":
                            zone_for_role[act] = zone
                        od_methods[act] = method
                    point = sample_activity_point(act, zone, regions, poi_candidates, rng, dis)

                spec = ActivitySpec(
                    act_type=act,
                    zone_idx=int(zone),
                    zone_id=str(regions["zone_id"].iloc[int(zone)]),
                    point=point,
                    end_time=end_times[idx],
                )
                activity_specs.append(spec)
                previous_zone = int(zone)

            person_id = f"fuzhou_multi_{person_idx:06d}"
            person_idx += 1

            work_zone_attr = ""
            if "w" in zone_for_role:
                work_zone_attr = str(regions["zone_id"].iloc[int(zone_for_role["w"])])

            attributes = [
                ("home_zone", "java.lang.String", home_zone_id),
                ("home_zone_index", "java.lang.Integer", home_zone),
                ("agent_type", "java.lang.String", agent_type),
                ("activity_chain_template", "java.lang.String", template_name),
                ("age_group", "java.lang.String", f"{age}+"),
                ("sex", "java.lang.String", sex),
                ("sample_weight", "java.lang.Double", f"{sample_weight:.10f}"),
                ("population_sample_rate", "java.lang.Double", f"{population_sample_rate:.10f}"),
                ("is_night_agent", "java.lang.Boolean", "true" if night_agent_role else "false"),
                ("age_sex_assignment_method", "java.lang.String", age_sex_method),
            ]
            if work_zone_attr:
                attributes.append(("work_zone", "java.lang.String", work_zone_attr))
                attributes.append(("work_zone_index", "java.lang.Integer", int(zone_for_role["w"])))

            row = {
                "person_id": person_id,
                "attributes": attributes,
                "activities": activity_specs,
                "agent_type": agent_type,
                "template": template_name,
                "home_zone_index": home_zone,
                "home_zone": home_zone_id,
                "age_group": f"{age}+",
                "sex": sex,
                "age_sex_method": age_sex_method,
            }
            person_rows.append(row)

            debug_base = {
                "person_id": person_id,
                "agent_type": agent_type,
                "activity_chain_template": template_name,
                "is_night_agent": bool(night_agent_role),
                "night_agent_role": night_agent_role,
                "age_group": f"{age}+",
                "sex": sex,
                "home_zone_index": home_zone,
                "home_zone": home_zone_id,
                "age_sex_assignment_method": age_sex_method,
                "chain": "->".join(chain),
            }
            for key, value in od_methods.items():
                debug_base[f"{key}_od_method"] = value

            debug_rows.append(
                {
                    **debug_base,
                    "activity_count": len(activity_specs),
                    "first_departure": activity_specs[0].end_time,
                    "last_timed_activity_end": next((a.end_time for a in reversed(activity_specs) if a.end_time is not None), ""),
                    "work_zone_index": zone_for_role.get("w", ""),
                    "work_zone": work_zone_attr,
                }
            )

            age_sex_records.append(
                {
                    "zone_index": home_zone,
                    "zone_id": home_zone_id,
                    "age_group": f"{age}+",
                    "sex": sex,
                    "agent_type": agent_type,
                    "count": 1,
                }
            )

            for seq, act in enumerate(activity_specs):
                lon, lat = transformer_to_wgs84.transform(act.point.x, act.point.y)
                point_rows.append(
                    {
                        "person_id": person_id,
                        "sequence": seq,
                        "activity_type": act.act_type,
                        "agent_type": agent_type,
                        "activity_chain_template": template_name,
                        "zone_index": act.zone_idx,
                        "zone_id": act.zone_id,
                        "end_time": act.end_time or "",
                        "sampling_method": act.point.method,
                        "lon": float(lon),
                        "lat": float(lat),
                    }
                )
                point_geoms.append(Point(act.point.x, act.point.y))

    plans_path = out_dir / "plans_multi_activity.xml.gz"
    write_plans_xml(plans_path, person_rows, args.mode)

    debug_path = out_dir / "agent_activity_debug.csv"
    pd.DataFrame(debug_rows).to_csv(debug_path, index=False, encoding="utf-8")

    point_path = out_dir / "activity_points.geojson"
    gpd.GeoDataFrame(point_rows, geometry=point_geoms, crs=args.crs).to_crs(WGS84).to_file(point_path, driver="GeoJSON")

    chain_summary_path = out_dir / "activity_chain_summary.csv"
    pd.DataFrame(debug_rows).groupby(["agent_type", "activity_chain_template", "chain"], dropna=False).size().reset_index(name="agents").to_csv(
        chain_summary_path, index=False, encoding="utf-8"
    )

    type_zone_path = out_dir / "agent_type_by_zone.csv"
    pd.DataFrame(debug_rows).groupby(["home_zone_index", "home_zone", "agent_type"], dropna=False).size().reset_index(name="agents").to_csv(
        type_zone_path, index=False, encoding="utf-8"
    )

    age_summary_path = out_dir / "agent_age_sex_assignment_summary.csv"
    pd.DataFrame(age_sex_records).groupby(["zone_index", "zone_id", "age_group", "sex", "agent_type"], dropna=False)["count"].sum().reset_index().to_csv(
        age_summary_path, index=False, encoding="utf-8"
    )

    activity_od_path = out_dir / "activity_od_summary.csv"
    od_rows = []
    for row in person_rows:
        acts = row["activities"]
        for a, b in zip(acts[:-1], acts[1:]):
            od_rows.append(
                {
                    "from_activity": a.act_type,
                    "to_activity": b.act_type,
                    "from_zone_index": a.zone_idx,
                    "to_zone_index": b.zone_idx,
                    "from_zone": a.zone_id,
                    "to_zone": b.zone_id,
                }
            )
    if od_rows:
        pd.DataFrame(od_rows).groupby(
            ["from_activity", "to_activity", "from_zone_index", "to_zone_index", "from_zone", "to_zone"], dropna=False
        ).size().reset_index(name="trips").to_csv(activity_od_path, index=False, encoding="utf-8")
    else:
        pd.DataFrame().to_csv(activity_od_path, index=False, encoding="utf-8")

    invalid_points = validate_activity_points(person_rows, regions)
    debug_df = pd.DataFrame(debug_rows)
    point_df = pd.DataFrame(point_rows)

    summary = {
        "city_key": CITY_KEY,
        "created_at_epoch": time.time(),
        "runtime_seconds": round(time.time() - started, 3),
        "inputs": {
            "generation": str(pathlib.Path(args.generation)),
            "regions": str(pathlib.Path(args.regions)),
            "worldpop": str(pathlib.Path(args.worldpop)),
            "demos": str(pathlib.Path(args.demos)),
            "demos_bands": str(pathlib.Path(args.demos_bands)),
            "distance": str(pathlib.Path(args.distance)),
            "population_raster": str(pathlib.Path(args.population_raster)),
            "pois": str(pathlib.Path(args.pois)),
        },
        "outputs": {
            "plans_multi_activity_xml_gz": str(plans_path),
            "zone_population_profile_csv": str(zone_profile_path),
            "agent_type_by_zone_csv": str(type_zone_path),
            "agent_age_sex_assignment_summary_csv": str(age_summary_path),
            "activity_chain_summary_csv": str(chain_summary_path),
            "activity_points_geojson": str(point_path),
            "agent_activity_debug_csv": str(debug_path),
            "activity_od_summary_csv": str(activity_od_path),
        },
        "parameters": {
            "target_agents": args.target_agents,
            "actual_agents": int(len(person_rows)),
            "target_population_share": target_population_share,
            "population_sample_rate": population_sample_rate,
            "sample_weight": sample_weight,
            "night_agent_share_requested": args.night_agent_share,
            "night_shift_share_requested": args.night_shift_share,
            "night_leisure_share_requested": args.night_leisure_share,
            "same_day_night": bool(args.same_day_night),
            "night_agents_assigned": int(len(night_assignments)),
            "adult_night_candidate_count": int(len(adult_night_candidates)),
            "seed": args.seed,
            "mode": args.mode,
            "crs": args.crs,
            "intra_work_rate": args.intra_work_rate,
            "age_groups": {
                "student": "0-19",
                "worker_non_worker_family_worker": "20-64 with age/sex labor participation curve",
                "retired": "65+",
            },
        },
        "population": {
            "worldpop_population_sum": worldpop_population_sum,
            "age_sex_population_sum": float(zone_profile["age_sex_total"].sum()),
            "sample_weight_mean": sample_weight,
            "home_zones_with_agents": int(np.count_nonzero(zone_agent_counts)),
            "population_weighted_home_sampling_zones": int(len(pop_candidates)),
        },
        "poi_candidates": {
            activity: int(sum(len(points) for points in by_zone.values())) for activity, by_zone in poi_candidates.items()
        },
        "agent_types": debug_df["agent_type"].value_counts().to_dict(),
        "night_agent_types": debug_df.loc[debug_df["is_night_agent"], "agent_type"].value_counts().to_dict(),
        "activity_chains": debug_df["activity_chain_template"].value_counts().to_dict(),
        "activity_types": point_df["activity_type"].value_counts().to_dict(),
        "sampling_methods": point_df["sampling_method"].value_counts().to_dict(),
        "validation": {
            "generation_shape": list(od.shape),
            "regions_count": int(n_zones),
            "demos_shape": list(demos.shape),
            "worldpop_shape": list(worldpop.shape),
            "invalid_activity_points_excluding_nearest_zone_poi": int(invalid_points),
            "all_person_ids_unique": bool(debug_df["person_id"].is_unique),
            "uses_fixed_citywide_agent_type_ratio": False,
        },
    }
    summary_path = out_dir / "multi_activity_agents_summary.json"
    summary["outputs"]["summary_json"] = str(summary_path)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
