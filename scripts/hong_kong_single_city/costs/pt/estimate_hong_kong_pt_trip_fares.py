"""Estimate one offline fare for every Hong Kong MATSim PT passenger trip.

The production plans serialize each main PT leg as a generic route without the
transit line, route, boarding stop, alighting stop, or transfers. Consequently,
v1 uses an auditable distance-only proxy derived from official adult Octopus
fare observations. It never invents or applies a transfer concession.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd


CANONICAL_SOURCE_ROOT = Path(r"F:\Matsim\matsim-example-project")
MODES = ("bus", "gmb", "train", "light_rail", "ferry")


def repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Estimate official-fare-based costs for every generic PT main leg."
    )
    parser.add_argument("--source-project-root", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    return parser.parse_args()


def choose_source_root(value: Path | None) -> Path:
    if value is not None:
        return value.resolve()
    local = repository_root()
    manifest = (
        local
        / "data/matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice/"
        "agent_trip_manifest_v2.parquet"
    )
    return local if manifest.exists() else CANONICAL_SOURCE_ROOT


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_facilities(path: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rb") as handle:
        for _, element in ET.iterparse(handle, events=("end",)):
            if element.tag.rsplit("}", 1)[-1] == "facility":
                rows.append(
                    {
                        "facility_id": element.attrib["id"],
                        "x": float(element.attrib["x"]),
                        "y": float(element.attrib["y"]),
                    }
                )
                element.clear()
    return pd.DataFrame(rows).drop_duplicates("facility_id")


def closest_curve_values(
    distance_m: np.ndarray, curve: pd.DataFrame, mode: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    subset = curve[curve["mode"].eq(mode)].sort_values("distance_bin_lower_m")
    centers = (
        subset["distance_bin_lower_m"].to_numpy(float)
        + subset["distance_bin_upper_m"].to_numpy(float)
    ) / 2
    indices = np.searchsorted(centers, distance_m, side="left")
    indices = np.clip(indices, 0, len(centers) - 1)
    previous = np.clip(indices - 1, 0, len(centers) - 1)
    use_previous = np.abs(distance_m - centers[previous]) < np.abs(
        distance_m - centers[indices]
    )
    indices = np.where(use_previous, previous, indices)
    median = subset["fare_median_hkd"].to_numpy(float)[indices]
    low = subset["fare_p10_hkd"].to_numpy(float)[indices]
    high = subset["fare_p90_hkd"].to_numpy(float)[indices]
    gap = np.abs(distance_m - centers[indices])
    return median, low, high, gap


def write_sha256s(output_dir: Path) -> None:
    paths = sorted(
        path
        for path in output_dir.iterdir()
        if path.is_file() and path.name != "SHA256SUMS.txt"
    )
    (output_dir / "SHA256SUMS.txt").write_text(
        "\n".join(f"{sha256(path)}  {path.name}" for path in paths) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    source_root = choose_source_root(args.source_project_root)
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else repository_root() / "data/transport_costs/hongkong/pt_fare_v1"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    demand_dir = (
        source_root
        / "data/matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice"
    )
    manifest_path = demand_dir / "agent_trip_manifest_v2.parquet"
    facilities_path = demand_dir / "facilities_5pct_v2.xml.gz"
    curve_path = output_dir / "official_fare_distance_curve.csv"
    for path in (manifest_path, facilities_path, curve_path):
        if not path.exists():
            raise FileNotFoundError(path)

    print("Reading PT trip manifest and activity facilities...", flush=True)
    trips = pd.read_parquet(manifest_path)
    trips = trips[trips["mode"].eq("pt")].copy()
    facilities = read_facilities(facilities_path)
    origin = facilities.add_prefix("origin_")
    destination = facilities.add_prefix("destination_")
    trips = trips.merge(
        origin,
        left_on="origin_facility_id",
        right_on="origin_facility_id",
        how="left",
        validate="many_to_one",
    ).merge(
        destination,
        left_on="destination_facility_id",
        right_on="destination_facility_id",
        how="left",
        validate="many_to_one",
    )
    trips["euclidean_distance_m"] = np.hypot(
        trips["destination_x"] - trips["origin_x"],
        trips["destination_y"] - trips["origin_y"],
    )
    if trips["euclidean_distance_m"].isna().any():
        missing = int(trips["euclidean_distance_m"].isna().sum())
        raise ValueError(f"{missing} PT trips lack a facility-based OD distance")

    curve = pd.read_csv(curve_path)
    distance = trips["euclidean_distance_m"].to_numpy(float)
    mode_medians: list[np.ndarray] = []
    mode_lows: list[np.ndarray] = []
    mode_highs: list[np.ndarray] = []
    mode_gaps: list[np.ndarray] = []
    for mode in MODES:
        median, low, high, gap = closest_curve_values(distance, curve, mode)
        trips[f"{mode}_fare_estimate_hkd"] = np.round(median, 1)
        trips[f"{mode}_distance_bin_gap_m"] = np.round(gap, 1)
        mode_medians.append(median)
        mode_lows.append(low)
        mode_highs.append(high)
        mode_gaps.append(gap)

    # Each mode contributes one vote, so the much larger number of bus fare
    # records does not dominate the generic-PT estimate.
    median_matrix = np.vstack(mode_medians)
    low_matrix = np.vstack(mode_lows)
    high_matrix = np.vstack(mode_highs)
    trips["cost_hkd"] = np.round(np.nanmedian(median_matrix, axis=0), 1)
    trips["fare_uncertainty_low_hkd"] = np.round(
        np.nanmin(low_matrix, axis=0), 1
    )
    trips["fare_uncertainty_high_hkd"] = np.round(
        np.nanmax(high_matrix, axis=0), 1
    )
    trips["nearest_reference_distance_gap_m"] = np.round(
        np.nanmax(np.vstack(mode_gaps), axis=0), 1
    )

    trips["cost_component"] = "pt_base_fare_adult_octopus_distance_proxy"
    trips["cost_source"] = (
        "TD_GTFS_20260720+MTR_OPEN_DATA_20260720_mode_balanced_distance_bin_median"
    )
    trips["cost_effective_date"] = "2026-07-14"
    trips["cost_quality"] = "low_official_fare_distance_proxy_no_itinerary"
    trips["transfer_concession_hkd"] = pd.Series(
        pd.array([pd.NA] * len(trips), dtype="Float64"), index=trips.index
    )
    trips["transfer_concession_status"] = (
        "not_applied_no_serialized_itinerary_or_eligibility"
    )
    trips["transfer_concession_source"] = ""
    trips["fare_passenger_type"] = "adult"
    trips["fare_payment_medium"] = "Octopus"
    trips["estimation_method"] = (
        "median_of_mode_specific_official_fare_distance_bin_medians"
    )

    required_columns = [
        "person_id",
        "leg_sequence",
        "mode",
        "cost_component",
        "cost_hkd",
        "cost_source",
        "cost_effective_date",
        "cost_quality",
    ]
    additional_columns = [
        "origin_facility_id",
        "destination_facility_id",
        "origin_type",
        "destination_type",
        "departure_time_s",
        "population_group",
        "role",
        "is_discretionary",
        "euclidean_distance_m",
        "fare_uncertainty_low_hkd",
        "fare_uncertainty_high_hkd",
        "bus_fare_estimate_hkd",
        "gmb_fare_estimate_hkd",
        "train_fare_estimate_hkd",
        "light_rail_fare_estimate_hkd",
        "ferry_fare_estimate_hkd",
        "nearest_reference_distance_gap_m",
        "transfer_concession_hkd",
        "transfer_concession_status",
        "transfer_concession_source",
        "fare_passenger_type",
        "fare_payment_medium",
        "estimation_method",
    ]
    output = trips[required_columns + additional_columns].sort_values(
        ["person_id", "leg_sequence"]
    )
    output_path = output_dir / "pt_passenger_trip_fare_estimates.parquet"
    output.to_parquet(output_path, index=False, compression="zstd")
    output.head(1000).to_csv(
        output_dir / "pt_passenger_trip_fare_estimates_sample.csv",
        index=False,
        encoding="utf-8",
    )

    validation = {
        "model": "Hong Kong offline public transport fare model v1",
        "input_pt_passenger_trips": int(len(trips)),
        "output_cost_rows": int(len(output)),
        "unique_persons": int(output["person_id"].nunique()),
        "duplicate_person_leg_keys": int(
            output.duplicated(["person_id", "leg_sequence"]).sum()
        ),
        "missing_cost_rows": int(output["cost_hkd"].isna().sum()),
        "negative_cost_rows": int(output["cost_hkd"].lt(0).sum()),
        "all_modes_are_pt": bool(output["mode"].eq("pt").all()),
        "required_columns": required_columns,
        "required_columns_present": all(
            column in output.columns for column in required_columns
        ),
        "transfer_concession_non_null_rows": int(
            output["transfer_concession_hkd"].notna().sum()
        ),
        "transfer_concession_policy": (
            "not applied; no line/route/boarding/alighting/eligibility itinerary "
            "is serialized in the production generic PT legs"
        ),
        "cost_hkd_summary": {
            key: float(value)
            for key, value in output["cost_hkd"]
            .describe(percentiles=[0.1, 0.5, 0.9])
            .to_dict()
            .items()
        },
        "euclidean_distance_m_summary": {
            key: float(value)
            for key, value in output["euclidean_distance_m"]
            .describe(percentiles=[0.1, 0.5, 0.9])
            .to_dict()
            .items()
        },
        "input_sha256": {
            "agent_trip_manifest_v2.parquet": sha256(manifest_path),
            "facilities_5pct_v2.xml.gz": sha256(facilities_path),
            "official_fare_distance_curve.csv": sha256(curve_path),
        },
        "prohibited_matsim_inputs_modified": False,
    }
    if (
        validation["output_cost_rows"] != validation["input_pt_passenger_trips"]
        or validation["duplicate_person_leg_keys"] != 0
        or validation["missing_cost_rows"] != 0
        or validation["negative_cost_rows"] != 0
        or not validation["required_columns_present"]
    ):
        raise AssertionError(json.dumps(validation, indent=2))
    (output_dir / "pt_trip_fare_validation.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_sha256s(output_dir)
    print(json.dumps(validation, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
