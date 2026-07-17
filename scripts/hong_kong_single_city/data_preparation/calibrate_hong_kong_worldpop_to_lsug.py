#!/usr/bin/env python3
"""Calibrate Hong Kong WorldPop age-sex rasters to 2021 Census LSUG totals.

The input WorldPop raster has 37 bands:

population, M_0 ... M_80, F_0 ... F_80

The 2021 Census Large Subunit Group (LSUG) layer provides total population,
male/female totals, and five broad age totals.  It does not provide the full
sex-by-age cross-tabulation, so this script uses iterative proportional fitting
within each LSUG to preserve the WorldPop age-sex pattern while matching the
available Census margins.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WORLDPOP = (
    ROOT
    / "data"
    / "gee"
    / "hongkong"
    / "worldpop_age_sex"
    / "worldpop_HKG_2020_pop_age_sex_hong_kong_fixed_link_boundary.tif"
)
DEFAULT_BANDS = ROOT / "data" / "gee" / "hongkong" / "worldpop_age_sex" / "worldpop_age_sex_bands.json"
DEFAULT_LSUG = (
    ROOT
    / "data"
    / "gee"
    / "hongkong"
    / "worldpop_age_sex"
    / "2021_Population_Census_Statistics_ LargeSubunitGroups"
    / "LSUG_21C_converted.shp"
)
DEFAULT_FIXED_LINK_BOUNDARY = ROOT / "data" / "boundary" / "hongkong" / "processed" / "hong_kong_fixed_link_boundary.geojson"
DEFAULT_OUT_DIR = ROOT / "data" / "gee" / "hongkong" / "worldpop_age_sex" / "census_calibrated"

AGE_GROUPS: dict[str, list[str]] = {
    "age_1": ["0", "1", "5", "10"],      # under 15
    "age_2": ["15", "20"],                # 15-24
    "age_3": ["25", "30", "35", "40"],   # 25-44
    "age_4": ["45", "50", "55", "60"],   # 45-64
    "age_5": ["65", "70", "75", "80"],   # 65+
}
AGE_GROUP_LABELS = {
    "age_1": "under_15",
    "age_2": "15_24",
    "age_3": "25_44",
    "age_4": "45_64",
    "age_5": "65_plus",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worldpop", type=Path, default=DEFAULT_WORLDPOP)
    parser.add_argument("--bands", type=Path, default=DEFAULT_BANDS)
    parser.add_argument("--lsug", type=Path, default=DEFAULT_LSUG)
    parser.add_argument("--fixed-link-boundary", type=Path, default=DEFAULT_FIXED_LINK_BOUNDARY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--ipf-iterations", type=int, default=50)
    parser.add_argument(
        "--strict-cell-centres",
        action="store_true",
        help="Use only raster cell centres inside LSUG polygons. By default missing small LSUGs get their nearest touched positive cell.",
    )
    return parser.parse_args()


def numeric_series(series) -> np.ndarray:
    return (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.strip()
        .replace({"-": "0", "": "0", "nan": "0", "None": "0"})
        .astype(float)
        .to_numpy()
    )


def load_census(path: Path, fixed_link_boundary: Path | None) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)
    needed = ["lsbg", "lsbg_eng", "t_pop", "pop_m", "pop_f", "age_1", "age_2", "age_3", "age_4", "age_5"]
    missing = [col for col in needed if col not in gdf.columns]
    if missing:
        raise ValueError(f"LSUG layer is missing required fields: {missing}")
    for col in ["t_pop", "pop_m", "pop_f", "age_1", "age_2", "age_3", "age_4", "age_5"]:
        gdf[col] = numeric_series(gdf[col])
    gdf["census_sex_sum"] = gdf["pop_m"] + gdf["pop_f"]
    gdf["census_age_sum"] = gdf[["age_1", "age_2", "age_3", "age_4", "age_5"]].sum(axis=1)
    if fixed_link_boundary and fixed_link_boundary.exists():
        boundary = gpd.read_file(fixed_link_boundary).to_crs(gdf.crs).geometry.union_all()
        area = gdf.geometry.area
        intersection_area = gdf.geometry.intersection(boundary).area
        fraction = (intersection_area / area).replace([np.inf, -np.inf], 0).fillna(0).clip(0, 1)
    else:
        fraction = np.ones(len(gdf), dtype="float64")
    gdf["fixed_link_fraction"] = fraction
    for col in ["t_pop", "pop_m", "pop_f", "age_1", "age_2", "age_3", "age_4", "age_5"]:
        gdf[f"target_{col}"] = gdf[col] * gdf["fixed_link_fraction"]
    return gdf


def band_lookup(bands: list[str]) -> tuple[dict[str, int], dict[str, list[int]], list[int], list[int]]:
    lookup = {name: idx for idx, name in enumerate(bands)}
    missing = [name for name in ["population"] if name not in lookup]
    for sex in ["M", "F"]:
        for ages in AGE_GROUPS.values():
            for age in ages:
                name = f"{sex}_{age}"
                if name not in lookup:
                    missing.append(name)
    if missing:
        raise ValueError(f"WorldPop bands are missing required names: {missing}")

    age_group_indices: dict[str, list[int]] = {}
    for group, ages in AGE_GROUPS.items():
        age_group_indices[group] = [lookup[f"M_{age}"] for age in ages] + [lookup[f"F_{age}"] for age in ages]
    male_indices = [idx for name, idx in lookup.items() if name.startswith("M_")]
    female_indices = [idx for name, idx in lookup.items() if name.startswith("F_")]
    return lookup, age_group_indices, male_indices, female_indices


def normalize_targets(total: float, values: np.ndarray) -> np.ndarray:
    values = np.where(np.isfinite(values), values, 0.0).astype("float64")
    values = np.maximum(values, 0.0)
    current = values.sum()
    if total <= 0 or current <= 0:
        return values * 0.0
    return values * (total / current)


def ipf_band_targets(
    source_band_sums: np.ndarray,
    target_total: float,
    target_male: float,
    target_female: float,
    target_age_groups: np.ndarray,
    bands: list[str],
    iterations: int,
) -> np.ndarray:
    matrix = np.array([source_band_sums[1:19], source_band_sums[19:37]], dtype="float64")
    if matrix.sum() <= 0 or target_total <= 0:
        return np.zeros(36, dtype="float64")

    sex_targets = normalize_targets(target_total, np.array([target_male, target_female], dtype="float64"))
    age_targets = normalize_targets(target_total, target_age_groups)
    age_band_positions = {
        "age_1": [0, 1, 2, 3],
        "age_2": [4, 5],
        "age_3": [6, 7, 8, 9],
        "age_4": [10, 11, 12, 13],
        "age_5": [14, 15, 16, 17],
    }

    for _ in range(iterations):
        row_sums = matrix.sum(axis=1)
        for row in range(2):
            if row_sums[row] > 0:
                matrix[row, :] *= sex_targets[row] / row_sums[row]

        for group_idx, group_name in enumerate(["age_1", "age_2", "age_3", "age_4", "age_5"]):
            positions = age_band_positions[group_name]
            current = matrix[:, positions].sum()
            if current > 0:
                matrix[:, positions] *= age_targets[group_idx] / current

    return np.concatenate([matrix[0], matrix[1]])


def calibrate(args: argparse.Namespace) -> dict[str, Any]:
    args.out_dir.mkdir(parents=True, exist_ok=True)
    bands = json.loads(args.bands.read_text(encoding="utf-8"))
    if len(bands) != 37 or bands[0] != "population":
        raise ValueError(f"Expected 37 WorldPop bands starting with population, got {len(bands)}")

    lookup, age_group_indices, male_indices, female_indices = band_lookup(bands)
    census = load_census(args.lsug, args.fixed_link_boundary)

    with rasterio.open(args.worldpop) as src:
        profile = src.profile.copy()
        data = src.read().astype("float32")
        raster_crs = src.crs
        transform = src.transform
        out_shape = (src.height, src.width)
        descriptions = src.descriptions

    if raster_crs is None:
        raise ValueError("WorldPop raster has no CRS")

    census_raster_crs = census.to_crs(raster_crs)
    shapes = ((geom, idx + 1) for idx, geom in enumerate(census_raster_crs.geometry) if geom is not None and not geom.is_empty)
    zone_ids = rasterize(
        shapes=shapes,
        out_shape=out_shape,
        transform=transform,
        fill=0,
        dtype="int32",
        all_touched=False,
    )

    positive_source = data[0] > 0
    filled_missing_lsug_count = 0
    if not args.strict_cell_centres:
        for idx, geom in enumerate(census_raster_crs.geometry):
            if ((zone_ids == idx + 1) & positive_source).any():
                continue
            touched = rasterize(
                shapes=[(geom, 1)],
                out_shape=out_shape,
                transform=transform,
                fill=0,
                dtype="uint8",
                all_touched=True,
            ).astype(bool)
            fill_mask = touched & positive_source
            if fill_mask.any():
                rep = geom.representative_point()
                rows, cols = np.where(fill_mask)
                xs = transform.c + (cols + 0.5) * transform.a + (rows + 0.5) * transform.b
                ys = transform.f + (cols + 0.5) * transform.d + (rows + 0.5) * transform.e
                nearest = int(np.argmin((xs - rep.x) ** 2 + (ys - rep.y) ** 2))
                zone_ids[rows[nearest], cols[nearest]] = idx + 1
                filled_missing_lsug_count += 1

    calibrated = np.zeros_like(data, dtype="float32")
    row_summaries: list[dict[str, Any]] = []

    calibrated_lsug_count = 0
    skipped_no_pixels = 0
    skipped_zero_source = 0
    skipped_zero_census = 0

    for idx, row in census.iterrows():
        mask = (zone_ids == idx + 1) & positive_source
        pixel_count = int(mask.sum())
        target_total = float(row["target_t_pop"])

        if pixel_count == 0:
            skipped_no_pixels += 1
            row_summaries.append({
                "lsbg": row["lsbg"],
                "status": "skipped_no_positive_worldpop_pixels_in_fixed_link_boundary",
                "pixel_count": 0,
                "target_total": target_total,
                "source_census_total": float(row["t_pop"]),
                "fixed_link_fraction": float(row["fixed_link_fraction"]),
            })
            continue
        if target_total <= 0:
            skipped_zero_census += 1
            continue

        source_sums = data[:, mask].sum(axis=1, dtype="float64")
        if source_sums[0] <= 0 or source_sums[1:].sum() <= 0:
            skipped_zero_source += 1
            continue

        target_age_groups = np.array([float(row[f"target_{group}"]) for group in ["age_1", "age_2", "age_3", "age_4", "age_5"]])
        band_targets = ipf_band_targets(
            source_sums,
            target_total,
            float(row["target_pop_m"]),
            float(row["target_pop_f"]),
            target_age_groups,
            bands,
            args.ipf_iterations,
        )

        source_age_sex_sums = source_sums[1:]
        factors = np.divide(
            band_targets,
            source_age_sex_sums,
            out=np.zeros_like(band_targets, dtype="float64"),
            where=source_age_sex_sums > 0,
        )

        for band_offset, factor in enumerate(factors, start=1):
            calibrated[band_offset, mask] = data[band_offset, mask] * np.float32(factor)
        calibrated[0, mask] = calibrated[1:, mask].sum(axis=0)

        calibrated_sums = calibrated[:, mask].sum(axis=1, dtype="float64")
        calibrated_age_groups = {
            AGE_GROUP_LABELS[group]: float(calibrated[indices, :][:, mask].sum(dtype="float64"))
            for group, indices in age_group_indices.items()
        }
        row_summaries.append({
            "lsbg": row["lsbg"],
            "lsbg_eng": row["lsbg_eng"],
            "status": "calibrated",
            "pixel_count": pixel_count,
            "target_total": target_total,
            "source_census_total": float(row["t_pop"]),
            "fixed_link_fraction": float(row["fixed_link_fraction"]),
            "source_population": float(source_sums[0]),
            "calibrated_population": float(calibrated_sums[0]),
            "target_male": float(row["target_pop_m"]),
            "calibrated_male": float(calibrated[male_indices, :][:, mask].sum(dtype="float64")),
            "target_female": float(row["target_pop_f"]),
            "calibrated_female": float(calibrated[female_indices, :][:, mask].sum(dtype="float64")),
            "target_under_15": float(row["target_age_1"]),
            "calibrated_under_15": calibrated_age_groups["under_15"],
            "target_15_24": float(row["target_age_2"]),
            "calibrated_15_24": calibrated_age_groups["15_24"],
            "target_25_44": float(row["target_age_3"]),
            "calibrated_25_44": calibrated_age_groups["25_44"],
            "target_45_64": float(row["target_age_4"]),
            "calibrated_45_64": calibrated_age_groups["45_64"],
            "target_65_plus": float(row["target_age_5"]),
            "calibrated_65_plus": calibrated_age_groups["65_plus"],
            "population_factor": float(target_total / source_sums[0]) if source_sums[0] > 0 else 0.0,
            "min_age_sex_factor": float(factors.min()) if factors.size else 0.0,
            "max_age_sex_factor": float(factors.max()) if factors.size else 0.0,
        })
        calibrated_lsug_count += 1

    uncovered_positive_pixels = int(((zone_ids == 0) & positive_source).sum())
    if uncovered_positive_pixels:
        # Preserve positive cells not covered by LSUG polygons, but report them.
        missing_mask = (zone_ids == 0) & positive_source
        calibrated[:, missing_mask] = data[:, missing_mask]

    profile.update(dtype="float32", count=37, compress="deflate", tiled=False, nodata=0)
    profile.pop("blockxsize", None)
    profile.pop("blockysize", None)

    output_tif = args.out_dir / "worldpop_HKG_2021_census_lsug_calibrated_fixed_link_boundary.tif"
    with rasterio.open(output_tif, "w", **profile) as dst:
        dst.write(calibrated)
        for band_idx, description in enumerate(descriptions or bands, start=1):
            dst.set_band_description(band_idx, description or bands[band_idx - 1])

    qa_csv = args.out_dir / "worldpop_HKG_2021_census_lsug_calibration_qa.csv"
    fieldnames = sorted({key for row in row_summaries for key in row})
    with qa_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(row_summaries)

    summary = {
        "source_worldpop": str(args.worldpop),
        "source_lsug": str(args.lsug),
        "fixed_link_boundary": str(args.fixed_link_boundary),
        "method": "Per-LSUG iterative proportional fitting after area-weighting LSUG Census targets to the fixed-link boundary. Population band is recomputed as the sum of calibrated age-sex bands.",
        "age_group_mapping": {
            "age_1_under_15": ["0", "1", "5", "10"],
            "age_2_15_24": ["15", "20"],
            "age_3_25_44": ["25", "30", "35", "40"],
            "age_4_45_64": ["45", "50", "55", "60"],
            "age_5_65_plus": ["65", "70", "75", "80"],
        },
        "ipf_iterations": int(args.ipf_iterations),
        "rasterize_all_touched": False,
        "fill_missing_lsugs_with_nearest_touched_cell": bool(not args.strict_cell_centres),
        "filled_missing_lsug_count": int(filled_missing_lsug_count),
        "lsug_count": int(len(census)),
        "area_weighted_fixed_link_census_total": float(census["target_t_pop"].sum()),
        "calibrated_lsug_count": int(calibrated_lsug_count),
        "skipped_no_pixels": int(skipped_no_pixels),
        "skipped_zero_source": int(skipped_zero_source),
        "skipped_zero_census": int(skipped_zero_census),
        "uncovered_positive_pixels_preserved": int(uncovered_positive_pixels),
        "output_tif": str(output_tif),
        "qa_csv": str(qa_csv),
        "source_population_sum": float(data[0].sum(dtype="float64")),
        "calibrated_population_sum": float(calibrated[0].sum(dtype="float64")),
        "source_age_sex_sum": float(data[1:].sum(dtype="float64")),
        "calibrated_age_sex_sum": float(calibrated[1:].sum(dtype="float64")),
        "calibrated_male_sum": float(calibrated[male_indices, :, :].sum(dtype="float64")),
        "calibrated_female_sum": float(calibrated[female_indices, :, :].sum(dtype="float64")),
    }
    summary_path = args.out_dir / "worldpop_HKG_2021_census_lsug_calibration_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    summary["summary_json"] = str(summary_path)
    return summary


def main() -> None:
    args = parse_args()
    summary = calibrate(args)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
