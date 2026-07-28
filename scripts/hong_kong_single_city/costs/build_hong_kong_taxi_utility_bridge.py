#!/usr/bin/env python3
"""Validate the legacy MATSim ride-to-taxi utility bridge.

This offline audit reads the existing base taxi fare and utility-design
products, derives the taxi ASC that would preserve each leg's legacy ride
score, and applies explicit validation stop gates. It does not modify or run
MATSim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]

FARE_DIR = ROOT / "data/taxi/hongkong/processed/taxi_fare_model_v1"
UTILITY_DIR = ROOT / "data/taxi/hongkong/processed/taxi_utility_design_v1"
OUT_DIR = ROOT / "data/taxi/hongkong/processed/taxi_utility_bridge_v1"

V2_RELATIVE = Path(
    "data/matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice"
)
NETWORK_RELATIVE = Path(
    "data/transit/hongkong/processed/"
    "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_"
    "ferry_core_v1_cap010/network.xml.gz"
)

EXPECTED_LEGS = 37_286
LEG_KEY = ["person_id", "tour_id", "leg_sequence"]
RIDE_CONSTANT = -1.5
TRAVEL_UTILITY_PER_HOUR = -6.0
RIDE_MONETARY_DISTANCE_RATE_PER_M = -0.0015
EXPECTED_EFFECTIVE_GLOBAL_MARGINAL_UTILITY_OF_MONEY = 1.0
TAXI_FARE_UTILITY_PER_HKD = 0.05
TAXI_FARE_SHARE_FACTOR = 1.0
PROVISIONAL_ASC_CANDIDATES = [-12.0, -9.0, -6.0]
ERROR_TOLERANCE = 1e-12

QUANTILES = {
    "p10": 0.10,
    "p25": 0.25,
    "median": 0.50,
    "p75": 0.75,
    "p90": 0.90,
    "p95": 0.95,
}

WORKTREE_PROTECTED_PATHS = [
    "data/matsim_agents/hongkong",
    "data/transit/hongkong",
    "data/taxi/hongkong/processed/taxi_fare_model_v1",
    "data/taxi/hongkong/processed/taxi_utility_design_v1",
    "scenarios",
    "src",
]

EXTERNAL_PROTECTED_PATHS = [
    "data/matsim_agents/hongkong",
    "data/transit/hongkong",
    "scenarios",
    "src",
]

ALLOWED_REPOSITORY_PATHS = {
    "scripts/hong_kong_single_city/costs/"
    "build_hong_kong_taxi_utility_bridge.py",
    "data/taxi/hongkong/processed/taxi_utility_bridge_v1/"
    "old_ride_vs_new_taxi_leg_audit.parquet",
    "data/taxi/hongkong/processed/taxi_utility_bridge_v1/"
    "old_ride_vs_new_taxi_summary.csv",
    "data/taxi/hongkong/processed/taxi_utility_bridge_v1/"
    "taxi_asc_initial_candidates.csv",
    "data/taxi/hongkong/processed/taxi_utility_bridge_v1/"
    "taxi_utility_bridge_validation.json",
    "data/taxi/hongkong/processed/taxi_utility_bridge_v1/"
    "old_ride_vs_new_taxi_grouped_summary.csv",
    "data/taxi/hongkong/processed/taxi_utility_bridge_v1/"
    "taxi_asc_candidate_residual_diagnostics.csv",
    "docs/HONG_KONG_TAXI_UTILITY_DESIGN.md",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fare-dir", type=Path, default=FARE_DIR)
    parser.add_argument("--utility-dir", type=Path, default=UTILITY_DIR)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument(
        "--matsim-root",
        type=Path,
        default=None,
        help=(
            "Explicit read-only project root containing the protected Hong "
            "Kong MATSim inputs. The default is the current worktree root; "
            "there is no automatic fallback to another checkout."
        ),
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_paths(paths: dict[str, Path]) -> dict[str, str]:
    return {name: sha256(path) for name, path in paths.items()}


def require_files(paths: dict[str, Path], context: str) -> None:
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            f"Missing required {context} files:\n"
            + "\n".join(missing)
        )


def resolve_matsim_root(
    explicit_root: Path | None,
) -> tuple[Path, bool, str | None]:
    was_explicit = explicit_root is not None
    root = explicit_root.resolve() if was_explicit else ROOT
    explicit_text = root.as_posix() if was_explicit else None

    required_probe = root / V2_RELATIVE
    if not required_probe.is_dir() and not was_explicit:
        raise FileNotFoundError(
            "The current worktree does not contain the required Hong Kong "
            f"MATSim inputs under {required_probe}. Re-run with an explicit "
            "--matsim-root <path>. No other checkout is selected "
            "automatically."
        )
    return root, was_explicit, explicit_text


def source_paths(fare_dir: Path, utility_dir: Path) -> dict[str, Path]:
    return {
        "taxi_leg_fare_estimates_base.parquet": fare_dir
        / "taxi_leg_fare_estimates_base.parquet",
        "taxi_fare_model_validation.json": fare_dir
        / "taxi_fare_model_validation.json",
        "taxi_leg_utility_audit_base.parquet": utility_dir
        / "taxi_leg_utility_audit_base.parquet",
        "taxi_utility_design_validation.json": utility_dir
        / "taxi_utility_design_validation.json",
    }


def protected_paths(matsim_root: Path) -> dict[str, Path]:
    v2_dir = matsim_root / V2_RELATIVE
    return {
        "plans_unrouted_5pct_v2.xml.gz": v2_dir
        / "plans_unrouted_5pct_v2.xml.gz",
        "plans_routed_5pct_v2.xml.gz": v2_dir
        / "plans_routed_5pct_v2.xml.gz",
        "config_hong_kong_5pct_v2_activity_modechoice_50it.xml": v2_dir
        / "config_hong_kong_5pct_v2_activity_modechoice_50it.xml",
        "facilities_5pct_v2.xml.gz": v2_dir / "facilities_5pct_v2.xml.gz",
        "privateVehicles_5pct.xml.gz": v2_dir
        / "privateVehicles_5pct.xml.gz",
        "network.xml.gz": matsim_root / NETWORK_RELATIVE,
    }


def git_repository_root(path: Path) -> Path:
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return Path(result.stdout.strip()).resolve()


def git_status_for_paths(repository_root: Path, pathspecs: list[str]) -> str:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repository_root),
            "status",
            "--short",
            "--",
            *pathspecs,
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def repository_changed_paths(repository_root: Path) -> list[str]:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repository_root),
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "-z",
        ],
        check=True,
        capture_output=True,
    )
    entries = result.stdout.decode("utf-8").split("\0")
    paths: list[str] = []
    for entry in entries:
        if not entry:
            continue
        if len(entry) < 4:
            paths.append(entry)
            continue
        paths.append(entry[3:].replace("\\", "/"))
    return sorted(set(paths))


def parse_scoring(
    config_path: Path,
    utility_validation: dict[str, Any],
) -> tuple[dict[str, float], float, dict[str, Any]]:
    root = ET.parse(config_path).getroot()
    scoring = root.find("./module[@name='scoring']")
    if scoring is None:
        raise ValueError(f"No scoring module in {config_path}")

    global_params = {
        param.attrib["name"]: param.attrib.get("value", "")
        for param in scoring.findall("./param")
    }
    ride_params: dict[str, str] | None = None
    for parameter_set in scoring.findall(
        "./parameterset[@type='modeParams']"
    ):
        params = {
            param.attrib["name"]: param.attrib.get("value", "")
            for param in parameter_set.findall("./param")
        }
        if params.get("mode") == "ride":
            ride_params = params
            break
    if ride_params is None:
        raise ValueError(f"No ride mode scoring parameters found in {config_path}")

    ride_scoring = {
        "constant": float(ride_params["constant"]),
        "marginalUtilityOfTraveling_util_hr": float(
            ride_params["marginalUtilityOfTraveling_util_hr"]
        ),
        "monetaryDistanceRate": float(
            ride_params["monetaryDistanceRate"]
        ),
    }

    config_mum_text = global_params.get("marginalUtilityOfMoney")
    if config_mum_text not in (None, ""):
        effective_mum = float(config_mum_text)
        source = {
            "source_type": "explicit_config_parameter",
            "source_path": config_path.as_posix(),
            "source_field": (
                "scoring.param[marginalUtilityOfMoney]"
            ),
            "config_parameter_present": True,
        }
    else:
        retained_mum = utility_validation.get(
            "global_marginal_utility_of_money_retained"
        )
        if retained_mum is None:
            raise ValueError(
                "The config has no explicit marginalUtilityOfMoney and the "
                "utility-design validation does not record a retained value."
            )
        effective_mum = float(retained_mum)
        source = {
            "source_type": (
                "retained_utility_design_value_with_no_config_override"
            ),
            "source_path": (
                "data/taxi/hongkong/processed/taxi_utility_design_v1/"
                "taxi_utility_design_validation.json"
            ),
            "source_field": (
                "global_marginal_utility_of_money_retained"
            ),
            "config_parameter_present": False,
            "config_path_checked": config_path.as_posix(),
        }
    source["effective_value"] = effective_mum
    return ride_scoring, effective_mum, source


def clean_numeric(values: pd.Series) -> pd.Series:
    clean = pd.to_numeric(values, errors="coerce")
    if clean.isna().any() or not np.isfinite(clean.to_numpy()).all():
        raise ValueError(f"Non-finite values found in {values.name}")
    return clean


def summary_stats(
    values: pd.Series,
    *,
    include_min_max: bool = False,
) -> dict[str, float]:
    clean = clean_numeric(values)
    result = {
        "mean": float(clean.mean()),
        "median": float(clean.median()),
    }
    for label, quantile in QUANTILES.items():
        if label != "median":
            result[label] = float(clean.quantile(quantile))
    if include_min_max:
        result["min"] = float(clean.min())
        result["max"] = float(clean.max())
    return result


def build_leg_audit(
    base: pd.DataFrame,
    effective_global_mum: float,
) -> pd.DataFrame:
    required = [
        *LEG_KEY,
        "scenario",
        "taxi_type",
        "departure_time_s",
        "route_distance_m",
        "actual_travel_time_s",
        "total_fare_distance_only_hkd",
    ]
    missing = [column for column in required if column not in base.columns]
    if missing:
        raise ValueError(f"Missing base fare columns: {missing}")

    identity_columns = [
        "scenario",
        "person_id",
        "tour_id",
        "leg_sequence",
        "classification_source",
        "taxi_type",
        "departure_time_s",
        "population_group",
        "role",
        "activity_purpose",
        "route_distance_m",
        "actual_travel_time_s",
        "total_fare_distance_only_hkd",
    ]
    audit = base[
        [column for column in identity_columns if column in base.columns]
    ].copy()
    audit = audit.rename(
        columns={"total_fare_distance_only_hkd": "fare_baseline_hkd"}
    )
    audit["travel_time_hours"] = audit["actual_travel_time_s"] / 3600.0

    audit["effective_global_marginal_utility_of_money"] = (
        effective_global_mum
    )
    audit["old_ride_constant_utility"] = RIDE_CONSTANT
    audit["old_ride_travel_time_utility"] = (
        TRAVEL_UTILITY_PER_HOUR * audit["travel_time_hours"]
    )
    audit["old_ride_distance_utility"] = (
        RIDE_MONETARY_DISTANCE_RATE_PER_M
        * audit["effective_global_marginal_utility_of_money"]
        * audit["route_distance_m"]
    )
    audit["old_ride_score"] = (
        audit["old_ride_constant_utility"]
        + audit["old_ride_travel_time_utility"]
        + audit["old_ride_distance_utility"]
    )

    audit["new_taxi_travel_time_utility"] = (
        TRAVEL_UTILITY_PER_HOUR * audit["travel_time_hours"]
    )
    audit["new_taxi_fare_utility"] = (
        -TAXI_FARE_UTILITY_PER_HKD
        * audit["fare_baseline_hkd"]
        * TAXI_FARE_SHARE_FACTOR
    )
    audit["new_taxi_score_before_asc"] = (
        audit["new_taxi_travel_time_utility"]
        + audit["new_taxi_fare_utility"]
    )
    audit["asc_equivalent"] = (
        audit["old_ride_score"]
        - audit["new_taxi_score_before_asc"]
    )
    audit["asc_equivalent_simplified"] = (
        RIDE_CONSTANT
        + RIDE_MONETARY_DISTANCE_RATE_PER_M
        * audit["effective_global_marginal_utility_of_money"]
        * audit["route_distance_m"]
        + TAXI_FARE_UTILITY_PER_HKD
        * audit["fare_baseline_hkd"]
        * TAXI_FARE_SHARE_FACTOR
    )
    audit["equivalence_error"] = (
        audit["new_taxi_score_before_asc"]
        + audit["asc_equivalent"]
        - audit["old_ride_score"]
    )
    audit["simplified_formula_error"] = (
        audit["asc_equivalent"]
        - audit["asc_equivalent_simplified"]
    )
    audit["time_utility_cancellation_error"] = (
        audit["old_ride_travel_time_utility"]
        - audit["new_taxi_travel_time_utility"]
    )

    distance_edges = [
        0.0,
        2_000.0,
        5_000.0,
        10_000.0,
        20_000.0,
        30_000.0,
        np.inf,
    ]
    distance_labels = [
        "0–2 km",
        "2–5 km",
        "5–10 km",
        "10–20 km",
        "20–30 km",
        ">30 km",
    ]
    audit["route_distance_bin"] = pd.cut(
        audit["route_distance_m"],
        bins=distance_edges,
        labels=distance_labels,
        right=False,
        include_lowest=True,
    )

    seconds_in_day = audit["departure_time_s"] % 86_400.0
    departure_hour = seconds_in_day / 3600.0
    audit["departure_time_period"] = pd.cut(
        departure_hour,
        bins=[0.0, 7.0, 10.0, 16.0, 20.0, 24.0],
        labels=[
            "00:00–06:59",
            "07:00–09:59",
            "10:00–15:59",
            "16:00–19:59",
            "20:00–23:59",
        ],
        right=False,
        include_lowest=True,
    )
    return audit


def overall_diagnostics(audit: pd.DataFrame) -> dict[str, float]:
    asc = audit["asc_equivalent"]
    return {
        "asc_equivalent_min": float(asc.min()),
        "asc_equivalent_max": float(asc.max()),
        "corr_asc_equivalent_route_distance_m": float(
            asc.corr(audit["route_distance_m"])
        ),
        "corr_asc_equivalent_fare_baseline_hkd": float(
            asc.corr(audit["fare_baseline_hkd"])
        ),
        "asc_equivalent_lt_minus3_share": float((asc < -3.0).mean()),
        "asc_equivalent_minus3_to_plus8_share": float(
            ((asc >= -3.0) & (asc <= 8.0)).mean()
        ),
        "asc_equivalent_gt_plus8_share": float((asc > 8.0).mean()),
        "asc_equivalent_lt_minus12_share": float((asc < -12.0).mean()),
        "asc_equivalent_minus12_to_minus6_share": float(
            ((asc >= -12.0) & (asc <= -6.0)).mean()
        ),
        "asc_equivalent_gt_minus6_share": float((asc > -6.0).mean()),
    }


def build_summary(
    audit: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, float]]:
    metrics = [
        ("route_distance_m", "m"),
        ("actual_travel_time_s", "s"),
        ("travel_time_hours", "h"),
        ("fare_baseline_hkd", "HKD"),
        ("old_ride_constant_utility", "util"),
        ("old_ride_travel_time_utility", "util"),
        ("old_ride_distance_utility", "util"),
        ("old_ride_score", "util"),
        ("new_taxi_travel_time_utility", "util"),
        ("new_taxi_fare_utility", "util"),
        ("new_taxi_score_before_asc", "util"),
        ("asc_equivalent", "util"),
    ]
    rows: list[dict[str, Any]] = []
    for metric, unit in metrics:
        rows.append(
            {
                "metric": metric,
                "unit": unit,
                "legs": int(len(audit)),
                **summary_stats(
                    audit[metric],
                    include_min_max=True,
                ),
                "value": np.nan,
            }
        )

    diagnostics = overall_diagnostics(audit)
    diagnostic_units = {
        "asc_equivalent_min": "util",
        "asc_equivalent_max": "util",
        "corr_asc_equivalent_route_distance_m": "correlation",
        "corr_asc_equivalent_fare_baseline_hkd": "correlation",
        "asc_equivalent_lt_minus3_share": "share",
        "asc_equivalent_minus3_to_plus8_share": "share",
        "asc_equivalent_gt_plus8_share": "share",
        "asc_equivalent_lt_minus12_share": "share",
        "asc_equivalent_minus12_to_minus6_share": "share",
        "asc_equivalent_gt_minus6_share": "share",
    }
    for metric, value in diagnostics.items():
        rows.append(
            {
                "metric": metric,
                "unit": diagnostic_units[metric],
                "legs": int(len(audit)),
                "mean": np.nan,
                "median": np.nan,
                "p10": np.nan,
                "p25": np.nan,
                "p75": np.nan,
                "p90": np.nan,
                "p95": np.nan,
                "min": np.nan,
                "max": np.nan,
                "value": value,
            }
        )
    column_order = [
        "metric",
        "unit",
        "legs",
        "mean",
        "median",
        "p10",
        "p25",
        "p75",
        "p90",
        "p95",
        "min",
        "max",
        "value",
    ]
    return pd.DataFrame(rows)[column_order], diagnostics


def grouped_summary_row(
    group: pd.DataFrame,
    grouping_dimension: str,
    group_value: str,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "grouping_dimension": grouping_dimension,
        "group_value": group_value,
        "leg_count": int(len(group)),
        "route_distance_m_mean": float(group["route_distance_m"].mean()),
        "route_distance_m_median": float(
            group["route_distance_m"].median()
        ),
        "fare_baseline_hkd_mean": float(
            group["fare_baseline_hkd"].mean()
        ),
        "fare_baseline_hkd_median": float(
            group["fare_baseline_hkd"].median()
        ),
    }
    for metric in ["old_ride_score", "new_taxi_score_before_asc"]:
        stats = summary_stats(group[metric])
        for statistic in ["mean", "median", "p10", "p90"]:
            row[f"{metric}_{statistic}"] = stats[statistic]
    asc_stats = summary_stats(group["asc_equivalent"])
    for statistic in ["mean", "median", "p10", "p25", "p75", "p90"]:
        row[f"asc_equivalent_{statistic}"] = asc_stats[statistic]
    return row


def build_grouped_summary(
    audit: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, int]]:
    rows = [grouped_summary_row(audit, "overall", "overall")]
    dimensions = [
        ("taxi_type", "taxi_type"),
        ("route_distance_bin", "route_distance_bin"),
        ("departure_time_period", "departure_time_period"),
    ]
    for grouping_dimension, column in dimensions:
        grouped = audit.groupby(
            column,
            dropna=False,
            observed=True,
            sort=True,
        )
        for group_value, group in grouped:
            label = (
                "<missing>"
                if pd.isna(group_value)
                else str(group_value)
            )
            rows.append(
                grouped_summary_row(
                    group,
                    grouping_dimension,
                    label,
                )
            )
    summary = pd.DataFrame(rows)
    count_checks = {
        dimension: int(
            summary.loc[
                summary["grouping_dimension"].eq(dimension),
                "leg_count",
            ].sum()
        )
        for dimension in [
            "overall",
            "taxi_type",
            "route_distance_bin",
            "departure_time_period",
        ]
    }
    return summary, count_checks


def percentile_rank(values: pd.Series, candidate: float) -> float:
    return float((values <= candidate).mean())


def build_initial_candidates(
    audit: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    asc_stats = summary_stats(
        audit["asc_equivalent"],
        include_min_max=True,
    )
    labels = [
        "more_negative_asc",
        "center_asc",
        "less_negative_asc",
    ]
    reason = (
        "-12 is close to the observed mean, -9 is close to the observed "
        "median, and -6 supplies a less-negative coarse test. The "
        "distribution is wide, so these remain provisional technical "
        "candidates rather than calibrated ASCs."
    )
    rows = []
    for order, (label, candidate) in enumerate(
        zip(labels, PROVISIONAL_ASC_CANDIDATES),
        start=1,
    ):
        rows.append(
            {
                "test_round": 1,
                "candidate_order": order,
                "candidate_label": label,
                "taxi_asc": candidate,
                "candidate_status": "provisional_technical_candidate",
                "asc_equivalent_percentile_rank": percentile_rank(
                    audit["asc_equivalent"],
                    candidate,
                ),
                "offset_from_asc_equivalent_mean": (
                    candidate - asc_stats["mean"]
                ),
                "offset_from_asc_equivalent_median": (
                    candidate - asc_stats["median"]
                ),
                "selection_decision": (
                    "retain_for_future_smoke_or_coarse_tests"
                ),
                "selection_reason": reason,
            }
        )
    metadata = {
        "status": "provisional_technical_candidates",
        "selected_candidates": PROVISIONAL_ASC_CANDIDATES,
        "labels": labels,
        "reason": reason,
        "minus12_close_to_mean": abs(
            -12.0 - asc_stats["mean"]
        )
        <= 1.0,
        "minus9_close_to_median": abs(
            -9.0 - asc_stats["median"]
        )
        <= 1.0,
        "single_asc_cannot_preserve_all_leg_utilities": True,
    }
    return pd.DataFrame(rows), metadata


def build_residual_diagnostics(
    audit: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    asc = audit["asc_equivalent"]
    asc_stats = summary_stats(asc, include_min_max=True)
    candidate_sources: dict[float, list[str]] = {}

    for candidate in range(-3, 9):
        candidate_sources.setdefault(float(candidate), []).append(
            "historical_grid_minus3_to_plus8"
        )
    for candidate in PROVISIONAL_ASC_CANDIDATES:
        candidate_sources.setdefault(candidate, []).append(
            "provisional_minus12_minus9_minus6"
        )

    anchors = {
        float(math.floor(asc_stats["p10"])): (
            "distribution_anchor_floor_p10"
        ),
        float(round(asc_stats["median"])): (
            "distribution_anchor_round_p50"
        ),
        float(math.ceil(asc_stats["p90"])): (
            "distribution_anchor_ceil_p90"
        ),
    }
    for candidate, source in anchors.items():
        candidate_sources.setdefault(candidate, []).append(source)

    provisional_labels = {
        -12.0: "more_negative_asc",
        -9.0: "center_asc",
        -6.0: "less_negative_asc",
    }
    rows = []
    for candidate in sorted(candidate_sources):
        residual = candidate - asc
        absolute = residual.abs()
        rows.append(
            {
                "candidate_asc": candidate,
                "candidate_source": ";".join(
                    candidate_sources[candidate]
                ),
                "candidate_label": provisional_labels.get(candidate, ""),
                "candidate_status": (
                    "provisional_technical_candidate"
                    if candidate in provisional_labels
                    else "diagnostic_only"
                ),
                "residual_mean": float(residual.mean()),
                "residual_median": float(residual.median()),
                "residual_p10": float(residual.quantile(0.10)),
                "residual_p90": float(residual.quantile(0.90)),
                "residual_mean_absolute": float(absolute.mean()),
                "residual_median_absolute": float(absolute.median()),
                "residual_rmse": float(
                    np.sqrt(np.mean(np.square(residual)))
                ),
                "residual_abs_le_1_util_share": float(
                    (absolute <= 1.0).mean()
                ),
                "residual_abs_le_3_util_share": float(
                    (absolute <= 3.0).mean()
                ),
                "asc_equivalent_percentile_rank": percentile_rank(
                    asc,
                    candidate,
                ),
            }
        )
    diagnostics = pd.DataFrame(rows)
    anchor_metadata = {
        "floor_p10": float(math.floor(asc_stats["p10"])),
        "round_p50": float(round(asc_stats["median"])),
        "ceil_p90": float(math.ceil(asc_stats["p90"])),
    }
    return diagnostics, anchor_metadata


def utility_design_crosscheck(
    audit: pd.DataFrame,
    utility_audit_path: Path,
) -> dict[str, Any]:
    utility = pd.read_parquet(utility_audit_path)
    center = utility.loc[
        utility["taxi_fare_utility_per_hkd"].eq(
            TAXI_FARE_UTILITY_PER_HKD
        )
        & utility["fare_share_factor"].eq(
            TAXI_FARE_SHARE_FACTOR
        )
    ].copy()
    center_unique = not center.duplicated(LEG_KEY).any()
    comparison = audit[
        LEG_KEY
        + [
            "new_taxi_score_before_asc",
            "new_taxi_fare_utility",
        ]
    ].merge(
        center[
            LEG_KEY
            + [
                "total_leg_utility_before_asc",
                "taxi_fare_utility",
            ]
        ],
        on=LEG_KEY,
        how="outer",
        validate="one_to_one" if center_unique else "one_to_many",
        indicator=True,
    )
    matched = comparison["_merge"].eq("both")
    score_difference = (
        comparison.loc[matched, "new_taxi_score_before_asc"]
        - comparison.loc[
            matched,
            "total_leg_utility_before_asc",
        ]
    ).abs()
    fare_difference = (
        comparison.loc[matched, "new_taxi_fare_utility"]
        - comparison.loc[matched, "taxi_fare_utility"]
    ).abs()
    max_score_difference = (
        float(score_difference.max())
        if not score_difference.empty
        else float("inf")
    )
    max_fare_difference = (
        float(fare_difference.max())
        if not fare_difference.empty
        else float("inf")
    )
    all_leg_keys_matched = bool(
        center_unique
        and len(center) == len(audit)
        and len(comparison) == len(audit)
        and matched.all()
    )
    return {
        "center_scenario_id": "farecoef_0p05_share_1p0",
        "center_rows": int(len(center)),
        "center_leg_keys_unique": center_unique,
        "joined_rows": int(len(comparison)),
        "all_leg_keys_matched": all_leg_keys_matched,
        "max_abs_new_score_difference": max_score_difference,
        "max_abs_fare_utility_difference": max_fare_difference,
        "scores_match_within_1e_12": bool(
            all_leg_keys_matched
            and max_score_difference <= ERROR_TOLERANCE
            and max_fare_difference <= ERROR_TOLERANCE
        ),
    }


def output_paths(out_dir: Path) -> dict[str, Path]:
    return {
        "old_ride_vs_new_taxi_leg_audit.parquet": out_dir
        / "old_ride_vs_new_taxi_leg_audit.parquet",
        "old_ride_vs_new_taxi_summary.csv": out_dir
        / "old_ride_vs_new_taxi_summary.csv",
        "taxi_asc_initial_candidates.csv": out_dir
        / "taxi_asc_initial_candidates.csv",
        "taxi_utility_bridge_validation.json": out_dir
        / "taxi_utility_bridge_validation.json",
        "old_ride_vs_new_taxi_grouped_summary.csv": out_dir
        / "old_ride_vs_new_taxi_grouped_summary.csv",
        "taxi_asc_candidate_residual_diagnostics.csv": out_dir
        / "taxi_asc_candidate_residual_diagnostics.csv",
    }


def write_validation(path: Path, validation: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    matsim_root, matsim_root_was_explicit, explicit_matsim_root = (
        resolve_matsim_root(args.matsim_root)
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)

    inputs = source_paths(args.fare_dir, args.utility_dir)
    protected = protected_paths(matsim_root)
    outputs = output_paths(args.out_dir)
    require_files(inputs, "taxi source")
    require_files(protected, "protected MATSim")

    worktree_git_root = git_repository_root(ROOT)
    external_git_root = git_repository_root(matsim_root)
    worktree_status_before = git_status_for_paths(
        worktree_git_root,
        WORKTREE_PROTECTED_PATHS,
    )
    external_status_before = git_status_for_paths(
        external_git_root,
        EXTERNAL_PROTECTED_PATHS,
    )
    if worktree_status_before:
        raise RuntimeError(
            "Current worktree protected paths are not clean:\n"
            + worktree_status_before
        )
    if external_status_before:
        raise RuntimeError(
            "Explicit MATSim root protected paths are not clean:\n"
            + external_status_before
        )

    input_hashes_before = hash_paths(inputs)
    protected_hashes_before = hash_paths(protected)

    base = pd.read_parquet(
        inputs["taxi_leg_fare_estimates_base.parquet"]
    )
    fare_validation = json.loads(
        inputs["taxi_fare_model_validation.json"].read_text(
            encoding="utf-8"
        )
    )
    utility_validation = json.loads(
        inputs["taxi_utility_design_validation.json"].read_text(
            encoding="utf-8"
        )
    )
    ride_scoring, effective_global_mum, mum_source = parse_scoring(
        protected[
            "config_hong_kong_5pct_v2_activity_modechoice_50it.xml"
        ],
        utility_validation,
    )

    audit = build_leg_audit(base, effective_global_mum)
    summary, diagnostics = build_summary(audit)
    grouped_summary, grouped_count_sums = build_grouped_summary(audit)
    candidates, candidate_metadata = build_initial_candidates(audit)
    residual_diagnostics, residual_anchor_metadata = (
        build_residual_diagnostics(audit)
    )
    utility_crosscheck = utility_design_crosscheck(
        audit,
        inputs["taxi_leg_utility_audit_base.parquet"],
    )

    audit.to_parquet(
        outputs["old_ride_vs_new_taxi_leg_audit.parquet"],
        index=False,
    )
    summary.to_csv(
        outputs["old_ride_vs_new_taxi_summary.csv"],
        index=False,
        encoding="utf-8-sig",
    )
    candidates.to_csv(
        outputs["taxi_asc_initial_candidates.csv"],
        index=False,
        encoding="utf-8-sig",
    )
    grouped_summary.to_csv(
        outputs["old_ride_vs_new_taxi_grouped_summary.csv"],
        index=False,
        encoding="utf-8-sig",
    )
    residual_diagnostics.to_csv(
        outputs["taxi_asc_candidate_residual_diagnostics.csv"],
        index=False,
        encoding="utf-8-sig",
    )
    write_validation(
        outputs["taxi_utility_bridge_validation.json"],
        {"status": "pending_validation_completion"},
    )

    numeric_columns = [
        "route_distance_m",
        "actual_travel_time_s",
        "fare_baseline_hkd",
        "effective_global_marginal_utility_of_money",
        "old_ride_score",
        "new_taxi_score_before_asc",
        "asc_equivalent",
        "asc_equivalent_simplified",
        "equivalence_error",
        "simplified_formula_error",
        "time_utility_cancellation_error",
    ]
    numeric_values = audit[numeric_columns].to_numpy(dtype=float)
    nonnegative_values = audit[
        [
            "route_distance_m",
            "actual_travel_time_s",
            "fare_baseline_hkd",
        ]
    ]
    max_errors = {
        "max_abs_equivalence_error": float(
            audit["equivalence_error"].abs().max()
        ),
        "max_abs_simplified_formula_error": float(
            audit["simplified_formula_error"].abs().max()
        ),
        "max_abs_time_utility_cancellation_error": float(
            audit["time_utility_cancellation_error"].abs().max()
        ),
    }

    input_hashes_after = hash_paths(inputs)
    protected_hashes_after = hash_paths(protected)
    worktree_status_after = git_status_for_paths(
        worktree_git_root,
        WORKTREE_PROTECTED_PATHS,
    )
    external_status_after = git_status_for_paths(
        external_git_root,
        EXTERNAL_PROTECTED_PATHS,
    )
    changed_paths = repository_changed_paths(worktree_git_root)
    unexpected_changed_paths = sorted(
        set(changed_paths) - ALLOWED_REPOSITORY_PATHS
    )
    outputs_exist_and_nonempty = all(
        path.is_file() and path.stat().st_size > 0
        for path in outputs.values()
    )
    grouped_counts_match = all(
        count == EXPECTED_LEGS
        for count in grouped_count_sums.values()
    )

    ride_scoring_matches = bool(
        ride_scoring["constant"] == RIDE_CONSTANT
        and ride_scoring[
            "marginalUtilityOfTraveling_util_hr"
        ]
        == TRAVEL_UTILITY_PER_HOUR
        and ride_scoring["monetaryDistanceRate"]
        == RIDE_MONETARY_DISTANCE_RATE_PER_M
    )
    required_checks = {
        "row_count_ok": len(audit) == EXPECTED_LEGS,
        "all_scenarios_are_base": bool(
            audit["scenario"].eq("base").all()
        ),
        "unique_leg_keys": not audit.duplicated(LEG_KEY).any(),
        "all_required_values_finite": bool(
            np.isfinite(numeric_values).all()
        ),
        "distance_time_fare_nonnegative": bool(
            not (nonnegative_values < 0).any().any()
        ),
        "fare_validation_row_count_matches": int(
            fare_validation["base_total_taxi_passenger_legs"]
        )
        == len(audit),
        "utility_design_validation_row_count_matches": int(
            utility_validation["base_fare_legs"]
        )
        == len(audit),
        "ride_scoring_matches_bridge_parameters": ride_scoring_matches,
        "effective_global_marginal_utility_of_money_is_1p0": bool(
            effective_global_mum
            == EXPECTED_EFFECTIVE_GLOBAL_MARGINAL_UTILITY_OF_MONEY
        ),
        "utility_design_all_leg_keys_matched": bool(
            utility_crosscheck["all_leg_keys_matched"]
        ),
        "utility_design_scores_match_within_1e_12": bool(
            utility_crosscheck["scores_match_within_1e_12"]
        ),
        "equivalence_error_within_1e_12": bool(
            max_errors["max_abs_equivalence_error"]
            <= ERROR_TOLERANCE
        ),
        "simplified_formula_error_within_1e_12": bool(
            max_errors["max_abs_simplified_formula_error"]
            <= ERROR_TOLERANCE
        ),
        "time_cancellation_error_within_1e_12": bool(
            max_errors[
                "max_abs_time_utility_cancellation_error"
            ]
            <= ERROR_TOLERANCE
        ),
        "input_hashes_unchanged": (
            input_hashes_before == input_hashes_after
        ),
        "protected_matsim_hashes_unchanged": (
            protected_hashes_before == protected_hashes_after
        ),
        "worktree_protected_status_empty_before_after": bool(
            worktree_status_before == ""
            and worktree_status_after == ""
        ),
        "external_matsim_root_protected_status_empty_before_after": bool(
            external_status_before == ""
            and external_status_after == ""
        ),
        "grouped_counts_match": grouped_counts_match,
        "outputs_exist_and_nonempty": outputs_exist_and_nonempty,
        "only_allowed_repository_paths_changed": (
            len(unexpected_changed_paths) == 0
        ),
    }
    all_checks_passed = all(required_checks.values())
    failed_required_checks = [
        name
        for name, passed in required_checks.items()
        if not passed
    ]

    asc_stats = summary_stats(
        audit["asc_equivalent"],
        include_min_max=True,
    )
    provisional_residuals = residual_diagnostics.loc[
        residual_diagnostics["candidate_asc"].isin(
            PROVISIONAL_ASC_CANDIDATES
        )
    ].copy()
    provisional_residual_records = provisional_residuals[
        [
            "candidate_asc",
            "candidate_label",
            "residual_mean_absolute",
            "residual_median_absolute",
            "residual_rmse",
            "residual_abs_le_1_util_share",
            "residual_abs_le_3_util_share",
            "asc_equivalent_percentile_rank",
        ]
    ].to_dict(orient="records")

    output_hashes = {
        name: sha256(path)
        for name, path in outputs.items()
        if name != "taxi_utility_bridge_validation.json"
    }
    validation: dict[str, Any] = {
        "scenario_family": "hong_kong_taxi_utility_bridge_v1",
        "validation_stage": "old_ride_new_taxi_bridge_validation_closure",
        "status": "validated" if all_checks_passed else "failed",
        "all_checks_passed": all_checks_passed,
        "failed_required_checks": failed_required_checks,
        "required_checks": required_checks,
        "base_taxi_passenger_legs": int(len(audit)),
        "expected_base_taxi_passenger_legs": EXPECTED_LEGS,
        "leg_key": LEG_KEY,
        "formula": {
            "travel_time_hours": (
                "actual_travel_time_s / 3600"
            ),
            "old_ride_score": (
                "-1.5 + (-6.0 * travel_time_hours) + "
                "(-0.0015 * "
                "effective_global_marginal_utility_of_money * "
                "route_distance_m)"
            ),
            "new_taxi_fare_utility": (
                "-0.05 * fare_baseline_hkd * 1.0"
            ),
            "new_taxi_score_before_asc": (
                "(-6.0 * travel_time_hours) + "
                "new_taxi_fare_utility"
            ),
            "asc_equivalent": (
                "old_ride_score - new_taxi_score_before_asc"
            ),
            "asc_equivalent_simplified": (
                "-1.5 - 0.0015 * "
                "effective_global_marginal_utility_of_money * "
                "route_distance_m + 0.05 * fare_baseline_hkd"
            ),
            "global_money_note": (
                "The legacy ride monetaryDistanceRate is a MATSim "
                "monetary-distance term and is multiplied by the effective "
                "global marginalUtilityOfMoney. The custom taxi fare "
                "coefficient is already in util/HKD and is not multiplied "
                "by global marginalUtilityOfMoney."
            ),
        },
        "parameters": {
            "ride_constant": RIDE_CONSTANT,
            "travel_utility_per_hour": TRAVEL_UTILITY_PER_HOUR,
            "ride_monetary_distance_rate_per_m": (
                RIDE_MONETARY_DISTANCE_RATE_PER_M
            ),
            "effective_global_marginal_utility_of_money": (
                effective_global_mum
            ),
            "taxi_fare_utility_per_hkd": (
                TAXI_FARE_UTILITY_PER_HKD
            ),
            "taxi_fare_share_factor": TAXI_FARE_SHARE_FACTOR,
        },
        "effective_global_marginal_utility_of_money_source": mum_source,
        "observed_ride_scoring_from_config": ride_scoring,
        "formula_error_max_abs": max_errors,
        "asc_equivalent_statistics": asc_stats,
        "overall_diagnostics": diagnostics,
        "candidate_selection": candidate_metadata,
        "residual_distribution_anchors": residual_anchor_metadata,
        "provisional_candidate_residual_diagnostics": (
            provisional_residual_records
        ),
        "grouped_summary": {
            "grouping_dimensions": [
                "overall",
                "taxi_type",
                "route_distance_bin",
                "departure_time_period",
            ],
            "distance_bins": [
                "0–2 km",
                "2–5 km",
                "5–10 km",
                "10–20 km",
                "20–30 km",
                ">30 km",
            ],
            "distance_bin_rule": (
                "left-closed, right-open; final bin has no upper bound"
            ),
            "departure_time_periods": [
                "00:00–06:59",
                "07:00–09:59",
                "10:00–15:59",
                "16:00–19:59",
                "20:00–23:59",
            ],
            "departure_time_rule": (
                "departure_time_s modulo 86400, left-closed "
                "hour intervals"
            ),
            "leg_count_sums_by_dimension": grouped_count_sums,
        },
        "utility_design_center_crosscheck": utility_crosscheck,
        "roots": {
            "worktree_root": ROOT.as_posix(),
            "worktree_git_repository_root": (
                worktree_git_root.as_posix()
            ),
            "explicit_matsim_root": explicit_matsim_root,
            "matsim_root_was_explicit": matsim_root_was_explicit,
            "resolved_matsim_root": matsim_root.as_posix(),
            "external_matsim_git_repository_root": (
                external_git_root.as_posix()
            ),
        },
        "input_paths": {
            name: path.as_posix()
            for name, path in inputs.items()
        },
        "protected_matsim_input_paths": {
            name: path.as_posix()
            for name, path in protected.items()
        },
        "input_hashes_before": input_hashes_before,
        "input_hashes_after": input_hashes_after,
        "protected_matsim_hashes_before": protected_hashes_before,
        "protected_matsim_hashes_after": protected_hashes_after,
        "git_protection": {
            "worktree_protected_pathspecs": (
                WORKTREE_PROTECTED_PATHS
            ),
            "worktree_protected_status_before": (
                worktree_status_before
            ),
            "worktree_protected_status_after": (
                worktree_status_after
            ),
            "external_matsim_root_protected_pathspecs": (
                EXTERNAL_PROTECTED_PATHS
            ),
            "external_matsim_root_protected_status_before": (
                external_status_before
            ),
            "external_matsim_root_protected_status_after": (
                external_status_after
            ),
            "repository_changed_paths": changed_paths,
            "allowed_repository_paths": sorted(
                ALLOWED_REPOSITORY_PATHS
            ),
            "unexpected_changed_paths": unexpected_changed_paths,
        },
        "output_hashes": output_hashes,
        "non_modification_statement": (
            "No MATSim plans, configs, networks, facilities, vehicles, "
            "Java files, modes, or simulation outputs were modified. "
            "No MATSim, QSim, Controler, smoke test, or mode-share "
            "calibration was run."
        ),
        "outputs": list(outputs),
    }
    write_validation(
        outputs["taxi_utility_bridge_validation.json"],
        validation,
    )

    print(
        json.dumps(
            {
                "status": validation["status"],
                "all_checks_passed": all_checks_passed,
                "failed_required_checks": failed_required_checks,
                "legs": len(audit),
                "formula_error_max_abs": max_errors,
                "asc_equivalent_statistics": asc_stats,
                "explicit_matsim_root": explicit_matsim_root,
                "matsim_root_was_explicit": (
                    matsim_root_was_explicit
                ),
                "grouped_count_sums": grouped_count_sums,
                "unexpected_changed_paths": (
                    unexpected_changed_paths
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if not all_checks_passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
