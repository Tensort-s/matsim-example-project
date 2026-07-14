"""Generate MATSim population plans from a WEDAN OD matrix.

This v1 generator converts the Greenspace Fuzhou WEDAN output into a
car-only commuter population:

    home -> car -> work -> car -> home

The script intentionally writes coordinate-based MATSim plans without link IDs.
Once a Fuzhou MATSim network is available, these points can be snapped to links
or re-routed in a later Valhalla/MATSim integration step.
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
from rasterio.transform import xy as raster_xy
from shapely.geometry import Point, mapping
from shapely.ops import transform as shapely_transform
from pyproj import Transformer


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
CITY_KEY = "fuzhou_city_23_greenspace_grid"
TARGET_CRS = "EPSG:32650"
WGS84 = "EPSG:4326"

DEFAULT_GENERATION = (
    PROJECT_ROOT
    / "data"
    / "worldcommuting_od"
    / "custom_features"
    / CITY_KEY
    / "CommutingODFlows"
    / CITY_KEY
    / "generation.npy"
)
DEFAULT_REGIONS = (
    PROJECT_ROOT
    / "data"
    / "worldcommuting_od"
    / "custom_features"
    / CITY_KEY
    / "CityAndRegionSplit"
    / CITY_KEY
    / "regions.shp"
)
DEFAULT_POPULATION_RASTER = (
    PROJECT_ROOT
    / "data"
    / "gee"
    / "fuzhou_city_23"
    / "worldpop_age_sex"
    / "worldpop_CHN_2020_pop_age_sex_fuzhou_city_23_greenspace_boundary.tif"
)
DEFAULT_WORK_POIS = (
    PROJECT_ROOT
    / "data"
    / "osm"
    / "fuzhou_city_23"
    / "fuzhou_city_23_osm_work_pois.geojson"
)
DEFAULT_OUT_DIR = PROJECT_ROOT / "data" / "matsim_agents" / CITY_KEY


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate MATSim agents from WEDAN OD output.")
    parser.add_argument("--generation", default=str(DEFAULT_GENERATION), help="WEDAN generation.npy OD matrix.")
    parser.add_argument("--regions", default=str(DEFAULT_REGIONS), help="Grid regions.shp.")
    parser.add_argument("--population-raster", default=str(DEFAULT_POPULATION_RASTER), help="WorldPop raster for home sampling.")
    parser.add_argument("--work-pois", default=str(DEFAULT_WORK_POIS), help="Work-attractor POI GeoJSON.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output directory.")
    parser.add_argument("--target-agents", type=int, default=30_000, help="Target number of sampled agents.")
    parser.add_argument("--seed", type=int, default=20260703, help="Random seed.")
    parser.add_argument("--mode", default="car", help="MATSim leg mode.")
    parser.add_argument("--crs", default=TARGET_CRS, help="Projected CRS for MATSim x/y coordinates.")
    return parser.parse_args()


def ensure_exists(path: pathlib.Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")


def safe_zone_id(regions: gpd.GeoDataFrame) -> pd.Series:
    for column in ("locations", "region_id", "id", "ID"):
        if column in regions.columns:
            return regions[column].astype(str)
    return pd.Series(np.arange(len(regions), dtype=int).astype(str), index=regions.index)


def load_inputs(args: argparse.Namespace) -> tuple[np.ndarray, gpd.GeoDataFrame]:
    generation_path = pathlib.Path(args.generation)
    regions_path = pathlib.Path(args.regions)
    ensure_exists(generation_path, "generation.npy")
    ensure_exists(regions_path, "regions.shp")

    od = np.load(generation_path).astype("float64")
    regions = gpd.read_file(regions_path).to_crs(args.crs).reset_index(drop=True)
    regions["zone_index"] = np.arange(len(regions), dtype=int)
    regions["zone_id"] = safe_zone_id(regions).to_numpy()

    if od.ndim != 2 or od.shape[0] != od.shape[1]:
        raise ValueError(f"OD matrix must be square, got shape={od.shape}")
    if od.shape[0] != len(regions):
        raise ValueError(f"OD shape {od.shape} does not match regions length {len(regions)}")
    if not np.isfinite(od).all():
        raise ValueError("OD matrix contains non-finite values.")
    if (od < 0).any():
        raise ValueError("OD matrix contains negative values.")

    od = od.copy()
    np.fill_diagonal(od, 0.0)
    return od, regions


def integerize_od(od: np.ndarray, target_agents: int, rng: np.random.Generator) -> tuple[np.ndarray, dict]:
    if target_agents <= 0:
        raise ValueError("--target-agents must be positive.")

    raw_sum = float(od.sum())
    if raw_sum <= 0:
        raise ValueError("OD matrix has no positive off-diagonal flow.")

    scale = target_agents / raw_sum
    expected = od * scale
    base = np.floor(expected).astype("int64")
    sampled = base.copy()
    current = int(sampled.sum())
    target = int(round(expected.sum()))
    target = max(0, target)

    remaining = target - current
    if remaining > 0:
        residual = (expected - base).ravel()
        positive = np.flatnonzero(residual > 0)
        if len(positive) == 0:
            raise ValueError("No residual probability available for random rounding.")
        weights = residual[positive]
        weights = weights / weights.sum()
        replace = remaining > len(positive)
        chosen = rng.choice(positive, size=remaining, replace=replace, p=weights)
        sampled.ravel()[chosen] += 1
    elif remaining < 0:
        removable = np.flatnonzero(sampled.ravel() > 0)
        weights = sampled.ravel()[removable].astype("float64")
        weights = weights / weights.sum()
        chosen = rng.choice(removable, size=abs(remaining), replace=True, p=weights)
        flat = sampled.ravel()
        for idx in chosen:
            if flat[idx] > 0:
                flat[idx] -= 1

    np.fill_diagonal(sampled, 0)
    metadata = {
        "raw_flow_sum": raw_sum,
        "target_agents": target_agents,
        "rounded_target_agents": target,
        "actual_agents": int(sampled.sum()),
        "scale": scale,
        "raw_nonzero_od": int(np.count_nonzero(od)),
        "sampled_nonzero_od": int(np.count_nonzero(sampled)),
        "raw_max_od": float(od.max()),
        "sampled_max_od": int(sampled.max()),
    }
    return sampled, metadata


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


def build_population_candidates(
    raster_path: pathlib.Path,
    regions: gpd.GeoDataFrame,
    target_crs: str,
) -> dict[int, ZonePopulationCandidates]:
    if not raster_path.exists():
        return {}

    candidates: dict[int, ZonePopulationCandidates] = {}
    with rasterio.open(raster_path) as src:
        raster_crs = src.crs
        if raster_crs is None:
            raise ValueError(f"Population raster has no CRS: {raster_path}")

        to_raster = Transformer.from_crs(target_crs, raster_crs, always_xy=True).transform
        to_target = Transformer.from_crs(raster_crs, target_crs, always_xy=True).transform

        for idx, geom in enumerate(regions.geometry):
            if geom is None or geom.is_empty:
                continue
            raster_geom = shapely_transform(to_raster, geom)
            try:
                data, out_transform = rasterio.mask.mask(
                    src,
                    [mapping(raster_geom)],
                    crop=True,
                    indexes=1,
                    filled=False,
                )
            except ValueError:
                continue

            arr = np.ma.asarray(data)
            valid = (~np.ma.getmaskarray(arr)) & np.isfinite(arr.filled(0)) & (arr.filled(0) > 0)
            rows, cols = np.where(valid)
            if len(rows) == 0:
                continue

            xs_raster, ys_raster = raster_xy(out_transform, rows, cols, offset="center")
            xs_raster = np.asarray(xs_raster, dtype="float64")
            ys_raster = np.asarray(ys_raster, dtype="float64")
            xs_target, ys_target = to_target(xs_raster, ys_raster)
            weights = np.asarray(arr.filled(0)[rows, cols], dtype="float64")

            if weights.sum() <= 0:
                continue
            candidates[idx] = ZonePopulationCandidates(
                xs=np.asarray(xs_target, dtype="float64"),
                ys=np.asarray(ys_target, dtype="float64"),
                weights=weights / weights.sum(),
            )
    return candidates


def sample_home_point(
    zone_idx: int,
    regions: gpd.GeoDataFrame,
    pop_candidates: dict[int, ZonePopulationCandidates],
    rng: np.random.Generator,
) -> PointSample:
    candidates = pop_candidates.get(zone_idx)
    if candidates is not None and len(candidates.xs) > 0:
        picked = int(rng.choice(len(candidates.xs), p=candidates.weights))
        return PointSample(float(candidates.xs[picked]), float(candidates.ys[picked]), "worldpop_weighted_pixel")
    return uniform_point_in_polygon(regions.geometry.iloc[zone_idx], rng)


def build_work_poi_candidates(
    pois_path: pathlib.Path,
    regions: gpd.GeoDataFrame,
    target_crs: str,
) -> dict[int, np.ndarray]:
    if not pois_path.exists():
        return {}

    pois = gpd.read_file(pois_path)
    if pois.empty:
        return {}
    if pois.crs is None:
        pois = pois.set_crs(WGS84)
    pois = pois.to_crs(target_crs)
    pois = pois[pois.geometry.notna() & ~pois.geometry.is_empty].copy()
    pois = pois[pois.geometry.geom_type == "Point"].copy()
    if pois.empty:
        return {}

    candidates: dict[int, list[tuple[float, float]]] = {idx: [] for idx in range(len(regions))}
    sindex = regions.sindex
    for point in pois.geometry:
        possible = list(sindex.query(point, predicate="contains"))
        if not possible:
            possible = list(sindex.query(point, predicate="intersects"))
        for zone_idx in possible[:1]:
            candidates[int(zone_idx)].append((float(point.x), float(point.y)))

    return {
        zone_idx: np.asarray(points, dtype="float64")
        for zone_idx, points in candidates.items()
        if len(points) > 0
    }


def sample_work_point(
    zone_idx: int,
    regions: gpd.GeoDataFrame,
    work_candidates: dict[int, np.ndarray],
    rng: np.random.Generator,
) -> PointSample:
    candidates = work_candidates.get(zone_idx)
    if candidates is not None and len(candidates) > 0:
        picked = int(rng.integers(0, len(candidates)))
        return PointSample(float(candidates[picked, 0]), float(candidates[picked, 1]), "osm_work_poi")
    return uniform_point_in_polygon(regions.geometry.iloc[zone_idx], rng)


def seconds_to_hms(seconds: float) -> str:
    seconds = int(round(seconds))
    seconds = max(0, min(seconds, 47 * 3600 + 59 * 60 + 59))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def xml_attr(value: object) -> str:
    return escape(str(value), {'"': "&quot;"})


def xml_text(value: object) -> str:
    return escape(str(value))


def write_plans_xml(
    path: pathlib.Path,
    rows: Iterable[dict],
    mode: str,
) -> None:
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as handle:
        handle.write('<?xml version="1.0" encoding="utf-8"?>\n')
        handle.write('<!DOCTYPE population SYSTEM "http://www.matsim.org/files/dtd/population_v6.dtd">\n')
        handle.write("<population>\n")
        for row in rows:
            person_id = xml_attr(row["person_id"])
            handle.write(f'  <person id="{person_id}">\n')
            handle.write("    <attributes>\n")
            for name, klass, value in (
                ("home_zone", "java.lang.String", row["home_zone"]),
                ("work_zone", "java.lang.String", row["work_zone"]),
                ("sample_weight", "java.lang.Double", f'{row["sample_weight"]:.10f}'),
                ("od_flow_raw", "java.lang.Double", f'{row["od_flow_raw"]:.10f}'),
            ):
                handle.write(
                    f'      <attribute name="{xml_attr(name)}" class="{xml_attr(klass)}">'
                    f"{xml_text(value)}</attribute>\n"
                )
            handle.write("    </attributes>\n")
            handle.write('    <plan selected="yes">\n')
            handle.write(
                f'      <activity type="h" x="{row["home_x"]:.3f}" y="{row["home_y"]:.3f}" '
                f'end_time="{xml_attr(row["home_end_time"])}" />\n'
            )
            handle.write(f'      <leg mode="{xml_attr(mode)}" />\n')
            handle.write(
                f'      <activity type="w" x="{row["work_x"]:.3f}" y="{row["work_y"]:.3f}" '
                f'end_time="{xml_attr(row["work_end_time"])}" />\n'
            )
            handle.write(f'      <leg mode="{xml_attr(mode)}" />\n')
            handle.write(f'      <activity type="h" x="{row["home_x"]:.3f}" y="{row["home_y"]:.3f}" />\n')
            handle.write("    </plan>\n")
            handle.write("  </person>\n")
        handle.write("</population>\n")


def validate_points(points: np.ndarray, zones: np.ndarray, regions: gpd.GeoDataFrame) -> int:
    invalid = 0
    for (x, y), zone_idx in zip(points, zones):
        geom = regions.geometry.iloc[int(zone_idx)]
        point = Point(float(x), float(y))
        if not (geom.contains(point) or geom.touches(point)):
            invalid += 1
    return invalid


def compute_correlation(raw: np.ndarray, sampled: np.ndarray) -> dict:
    mask = np.ones(raw.shape, dtype=bool)
    np.fill_diagonal(mask, False)
    raw_flat = raw[mask].astype("float64")
    sampled_flat = sampled[mask].astype("float64")
    positive = raw_flat > 0

    def corr(a: np.ndarray, b: np.ndarray) -> float | None:
        if len(a) < 2 or float(np.std(a)) == 0.0 or float(np.std(b)) == 0.0:
            return None
        return float(np.corrcoef(a, b)[0, 1])

    return {
        "pearson_all_offdiag_raw_vs_sampled": corr(raw_flat, sampled_flat),
        "pearson_positive_raw_vs_sampled": corr(raw_flat[positive], sampled_flat[positive]),
    }


def main() -> None:
    args = parse_args()
    started = time.time()
    rng = np.random.default_rng(args.seed)

    generation_path = pathlib.Path(args.generation)
    regions_path = pathlib.Path(args.regions)
    raster_path = pathlib.Path(args.population_raster)
    pois_path = pathlib.Path(args.work_pois)
    out_dir = pathlib.Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    od, regions = load_inputs(args)
    sampled_od, od_metadata = integerize_od(od, args.target_agents, rng)

    print(f"Loaded OD {od.shape}, raw sum={od_metadata['raw_flow_sum']:.3f}")
    print(f"Sampled agents={od_metadata['actual_agents']} across {od_metadata['sampled_nonzero_od']} OD pairs")
    print("Preparing population and work-attractor sampling candidates...")
    pop_candidates = build_population_candidates(raster_path, regions, args.crs)
    work_candidates = build_work_poi_candidates(pois_path, regions, args.crs)
    print(f"Population-weighted zones={len(pop_candidates)}, work-POI zones={len(work_candidates)}")

    origin_zones, dest_zones = np.where(sampled_od > 0)
    counts = sampled_od[origin_zones, dest_zones].astype("int64")
    agent_origins = np.repeat(origin_zones, counts)
    agent_dests = np.repeat(dest_zones, counts)
    n_agents = int(len(agent_origins))

    transformer_to_wgs84 = Transformer.from_crs(args.crs, WGS84, always_xy=True)
    sample_weight = 1.0 / od_metadata["scale"]

    debug_rows: list[dict] = []
    home_points = np.empty((n_agents, 2), dtype="float64")
    work_points = np.empty((n_agents, 2), dtype="float64")

    for i, (origin, dest) in enumerate(zip(agent_origins, agent_dests)):
        home = sample_home_point(int(origin), regions, pop_candidates, rng)
        work = sample_work_point(int(dest), regions, work_candidates, rng)

        am_departure = float(rng.triangular(7 * 3600, 8 * 3600, int(9.5 * 3600)))
        work_duration = float(np.clip(rng.normal(8.5 * 3600, 0.45 * 3600), 7.5 * 3600, 9.5 * 3600))
        work_end = am_departure + work_duration

        home_lon, home_lat = transformer_to_wgs84.transform(home.x, home.y)
        work_lon, work_lat = transformer_to_wgs84.transform(work.x, work.y)
        raw_flow = float(od[int(origin), int(dest)])

        person_id = f"fuzhou_commuter_{i:06d}"
        row = {
            "person_id": person_id,
            "home_zone": str(regions["zone_id"].iloc[int(origin)]),
            "work_zone": str(regions["zone_id"].iloc[int(dest)]),
            "home_zone_index": int(origin),
            "work_zone_index": int(dest),
            "mode": args.mode,
            "home_end_time": seconds_to_hms(am_departure),
            "work_end_time": seconds_to_hms(work_end),
            "home_x": home.x,
            "home_y": home.y,
            "work_x": work.x,
            "work_y": work.y,
            "home_lon": float(home_lon),
            "home_lat": float(home_lat),
            "work_lon": float(work_lon),
            "work_lat": float(work_lat),
            "home_sampling_method": home.method,
            "work_sampling_method": work.method,
            "od_flow_raw": raw_flow,
            "sample_weight": sample_weight,
        }
        debug_rows.append(row)
        home_points[i] = (home.x, home.y)
        work_points[i] = (work.x, work.y)

    plans_path = out_dir / "plans.xml.gz"
    write_plans_xml(plans_path, debug_rows, args.mode)

    debug_csv_path = out_dir / "agent_od_debug.csv"
    debug_df = pd.DataFrame(debug_rows)
    debug_df.to_csv(debug_csv_path, index=False, encoding="utf-8")

    sampled_matrix_path = out_dir / "od_sampled_matrix.npy"
    np.save(sampled_matrix_path, sampled_od.astype("int32"))

    edges_rows = []
    for origin, dest, count in zip(origin_zones, dest_zones, counts):
        raw_flow = float(od[int(origin), int(dest)])
        scaled_expected = raw_flow * od_metadata["scale"]
        edges_rows.append(
            {
                "home_zone_index": int(origin),
                "work_zone_index": int(dest),
                "home_zone": str(regions["zone_id"].iloc[int(origin)]),
                "work_zone": str(regions["zone_id"].iloc[int(dest)]),
                "raw_flow": raw_flow,
                "scaled_expected_agents": scaled_expected,
                "sampled_agents": int(count),
                "sampling_error": int(count) - scaled_expected,
            }
        )
    edges_path = out_dir / "od_sampled_edges.csv"
    pd.DataFrame(edges_rows).to_csv(edges_path, index=False, encoding="utf-8")

    points_records = []
    point_geometries = []
    for row in debug_rows:
        common = {
            "person_id": row["person_id"],
            "home_zone_index": row["home_zone_index"],
            "work_zone_index": row["work_zone_index"],
            "home_zone": row["home_zone"],
            "work_zone": row["work_zone"],
            "mode": row["mode"],
        }
        points_records.append({**common, "role": "home", "sampling_method": row["home_sampling_method"]})
        point_geometries.append(Point(row["home_x"], row["home_y"]))
        points_records.append({**common, "role": "work", "sampling_method": row["work_sampling_method"]})
        point_geometries.append(Point(row["work_x"], row["work_y"]))

    points_geojson_path = out_dir / "agents_home_work_points.geojson"
    points_gdf = gpd.GeoDataFrame(points_records, geometry=point_geometries, crs=args.crs)
    points_gdf.to_crs(WGS84).to_file(points_geojson_path, driver="GeoJSON")

    home_invalid = validate_points(home_points, agent_origins, regions)
    work_invalid = validate_points(work_points, agent_dests, regions)
    correlations = compute_correlation(od, sampled_od)

    summary = {
        "city_key": CITY_KEY,
        "created_at_epoch": time.time(),
        "runtime_seconds": round(time.time() - started, 3),
        "inputs": {
            "generation": str(generation_path),
            "regions": str(regions_path),
            "population_raster": str(raster_path),
            "work_pois": str(pois_path),
        },
        "outputs": {
            "plans_xml_gz": str(plans_path),
            "agent_od_debug_csv": str(debug_csv_path),
            "od_sampled_matrix_npy": str(sampled_matrix_path),
            "od_sampled_edges_csv": str(edges_path),
            "agents_home_work_points_geojson": str(points_geojson_path),
        },
        "crs": {
            "matsim_xy": args.crs,
            "debug_lonlat": WGS84,
        },
        "od": od_metadata,
        "sampling": {
            "seed": args.seed,
            "mode": args.mode,
            "population_weighted_zones": len(pop_candidates),
            "work_poi_zones": len(work_candidates),
            "home_sampling_methods": debug_df["home_sampling_method"].value_counts().to_dict(),
            "work_sampling_methods": debug_df["work_sampling_method"].value_counts().to_dict(),
        },
        "validation": {
            "generation_shape": list(od.shape),
            "regions_count": int(len(regions)),
            "diagonal_sum_after_zeroing": float(np.trace(od)),
            "invalid_home_points": int(home_invalid),
            "invalid_work_points": int(work_invalid),
            **correlations,
        },
    }

    summary_path = out_dir / "generation_to_agents_summary.json"
    summary["outputs"]["summary_json"] = str(summary_path)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
