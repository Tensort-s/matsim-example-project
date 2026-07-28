#!/usr/bin/env python3
"""Bridge legacy MATSim ride scores to the proposed Hong Kong taxi utility.

This is an offline audit only. It reads the existing base taxi passenger-leg
fare audit and utility design, then derives the taxi ASC that would preserve
each leg's legacy ride score. It does not modify or run MATSim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
CANONICAL_ROOT = Path(r"F:\Matsim\matsim-example-project")

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
RIDE_DISTANCE_UTILITY_PER_M = -0.0015
TAXI_FARE_UTILITY_PER_HKD = 0.05
TAXI_FARE_SHARE_FACTOR = 1.0
DEFAULT_ASC_CANDIDATES = [-12.0, -9.0, -6.0]
QUANTILES = {
    "p10": 0.10,
    "p25": 0.25,
    "median": 0.50,
    "p75": 0.75,
    "p90": 0.90,
    "p95": 0.95,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fare-dir", type=Path, default=FARE_DIR)
    parser.add_argument("--utility-dir", type=Path, default=UTILITY_DIR)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--matsim-root", type=Path)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_matsim_root(explicit_root: Path | None) -> Path:
    if explicit_root is not None:
        root = explicit_root.resolve()
    elif (ROOT / V2_RELATIVE).exists():
        root = ROOT
    elif (CANONICAL_ROOT / V2_RELATIVE).exists():
        root = CANONICAL_ROOT
    else:
        raise FileNotFoundError(
            "Could not locate the Hong Kong v2 MATSim input directory under "
            f"{ROOT} or {CANONICAL_ROOT}"
        )
    return root


def protected_paths(matsim_root: Path) -> dict[str, Path]:
    v2_dir = matsim_root / V2_RELATIVE
    return {
        "plans_unrouted_5pct_v2.xml.gz": v2_dir
        / "plans_unrouted_5pct_v2.xml.gz",
        "plans_routed_5pct_v2.xml.gz": v2_dir / "plans_routed_5pct_v2.xml.gz",
        "config_hong_kong_5pct_v2_activity_modechoice_50it.xml": v2_dir
        / "config_hong_kong_5pct_v2_activity_modechoice_50it.xml",
        "facilities_5pct_v2.xml.gz": v2_dir / "facilities_5pct_v2.xml.gz",
        "privateVehicles_5pct.xml.gz": v2_dir / "privateVehicles_5pct.xml.gz",
        "network.xml.gz": matsim_root / NETWORK_RELATIVE,
    }


def require_files(paths: dict[str, Path]) -> None:
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError("Required files are missing:\n" + "\n".join(missing))


def hash_paths(paths: dict[str, Path]) -> dict[str, str]:
    return {name: sha256(path) for name, path in paths.items()}


def protected_git_status() -> str:
    pathspecs = [
        "data/matsim_agents/hongkong",
        "data/transit/hongkong",
        "scenarios",
        "src",
    ]
    result = subprocess.run(
        ["git", "status", "--short", "--", *pathspecs],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def parse_ride_scoring(config_path: Path) -> dict[str, float]:
    root = ET.parse(config_path).getroot()
    for parameter_set in root.findall(
        "./module[@name='scoring']/parameterset[@type='modeParams']"
    ):
        params = {
            param.attrib["name"]: param.attrib.get("value", "")
            for param in parameter_set.findall("./param")
        }
        if params.get("mode") == "ride":
            return {
                "constant": float(params["constant"]),
                "marginalUtilityOfTraveling_util_hr": float(
                    params["marginalUtilityOfTraveling_util_hr"]
                ),
                "monetaryDistanceRate": float(params["monetaryDistanceRate"]),
            }
    raise ValueError(f"No ride mode scoring parameters found in {config_path}")


def summary_stats(values: pd.Series) -> dict[str, float]:
    clean = pd.to_numeric(values, errors="coerce")
    if clean.isna().any() or not np.isfinite(clean.to_numpy()).all():
        raise ValueError(f"Non-finite values found in {values.name}")
    result = {
        "mean": float(clean.mean()),
        "median": float(clean.median()),
    }
    for label, quantile in QUANTILES.items():
        if label != "median":
            result[label] = float(clean.quantile(quantile))
    return result


def build_leg_audit(base: pd.DataFrame) -> pd.DataFrame:
    required = [
        *LEG_KEY,
        "scenario",
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
    audit = base[[column for column in identity_columns if column in base.columns]].copy()
    audit = audit.rename(
        columns={"total_fare_distance_only_hkd": "fare_baseline_hkd"}
    )
    audit["travel_time_hours"] = audit["actual_travel_time_s"] / 3600.0

    audit["old_ride_constant_utility"] = RIDE_CONSTANT
    audit["old_ride_travel_time_utility"] = (
        TRAVEL_UTILITY_PER_HOUR * audit["travel_time_hours"]
    )
    audit["old_ride_distance_utility"] = (
        RIDE_DISTANCE_UTILITY_PER_M * audit["route_distance_m"]
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
        audit["old_ride_score"] - audit["new_taxi_score_before_asc"]
    )
    return audit


def build_summary(audit: pd.DataFrame) -> pd.DataFrame:
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
    rows = []
    for metric, unit in metrics:
        rows.append(
            {
                "metric": metric,
                "unit": unit,
                "legs": int(len(audit)),
                **summary_stats(audit[metric]),
            }
        )
    return pd.DataFrame(rows)


def percentile_rank(values: pd.Series, candidate: float) -> float:
    return float((values <= candidate).mean())


def choose_candidates(audit: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    stats = summary_stats(audit["asc_equivalent"])
    median = stats["median"]
    default_brackets_median = min(DEFAULT_ASC_CANDIDATES) <= median <= max(
        DEFAULT_ASC_CANDIDATES
    )
    default_center_near_median = abs(DEFAULT_ASC_CANDIDATES[1] - median) <= 1.5

    if default_brackets_median and default_center_near_median:
        candidates = DEFAULT_ASC_CANDIDATES
        decision = "retain_default_candidates"
        reason = (
            "Observed median ASC-equivalent is bracketed by -12/-9/-6 and is "
            "within 1.5 util of the -9 center; -12 is also close to the mean."
        )
    else:
        center = float(3.0 * round(median / 3.0))
        candidates = [center - 3.0, center, center + 3.0]
        decision = "recenter_on_observed_median"
        reason = (
            "Default candidates did not bracket the observed median closely; "
            "the coarse grid was recentered to the nearest 3-util value."
        )

    labels = ["lower_asc", "center_asc", "upper_asc"]
    rows = []
    for order, (label, candidate) in enumerate(zip(labels, candidates), start=1):
        rows.append(
            {
                "test_round": 1,
                "candidate_order": order,
                "candidate_label": label,
                "taxi_asc": candidate,
                "asc_equivalent_percentile_rank": percentile_rank(
                    audit["asc_equivalent"], candidate
                ),
                "offset_from_asc_equivalent_mean": candidate - stats["mean"],
                "offset_from_asc_equivalent_median": candidate - median,
                "selection_decision": decision,
                "selection_reason": reason,
            }
        )
    metadata = {
        "decision": decision,
        "reason": reason,
        "default_candidates": DEFAULT_ASC_CANDIDATES,
        "selected_candidates": candidates,
        "default_brackets_observed_median": default_brackets_median,
        "default_center_within_1p5_util_of_observed_median": default_center_near_median,
    }
    return pd.DataFrame(rows), metadata


def utility_design_crosscheck(
    audit: pd.DataFrame, utility_audit_path: Path
) -> dict[str, object]:
    utility = pd.read_parquet(utility_audit_path)
    center = utility.loc[
        utility["taxi_fare_utility_per_hkd"].eq(TAXI_FARE_UTILITY_PER_HKD)
        & utility["fare_share_factor"].eq(TAXI_FARE_SHARE_FACTOR)
    ].copy()
    if len(center) != EXPECTED_LEGS:
        raise ValueError(
            f"Expected {EXPECTED_LEGS} center utility rows, found {len(center)}"
        )
    if center.duplicated(LEG_KEY).any():
        raise ValueError("Duplicate leg keys in the center utility design scenario")

    comparison = audit[
        LEG_KEY + ["new_taxi_score_before_asc", "new_taxi_fare_utility"]
    ].merge(
        center[
            LEG_KEY + ["total_leg_utility_before_asc", "taxi_fare_utility"]
        ],
        on=LEG_KEY,
        how="outer",
        validate="one_to_one",
        indicator=True,
    )
    matched = comparison["_merge"].eq("both")
    score_difference = (
        comparison.loc[matched, "new_taxi_score_before_asc"]
        - comparison.loc[matched, "total_leg_utility_before_asc"]
    ).abs()
    fare_difference = (
        comparison.loc[matched, "new_taxi_fare_utility"]
        - comparison.loc[matched, "taxi_fare_utility"]
    ).abs()
    return {
        "center_scenario_id": "farecoef_0p05_share_1p0",
        "center_rows": int(len(center)),
        "joined_rows": int(len(comparison)),
        "all_leg_keys_matched": bool(matched.all()),
        "max_abs_new_score_difference": float(score_difference.max()),
        "max_abs_fare_utility_difference": float(fare_difference.max()),
        "scores_match_within_1e_12": bool(
            matched.all()
            and score_difference.max() <= 1e-12
            and fare_difference.max() <= 1e-12
        ),
    }


def main() -> None:
    args = parse_args()
    matsim_root = resolve_matsim_root(args.matsim_root)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    source_paths = {
        "taxi_leg_fare_estimates_base.parquet": args.fare_dir
        / "taxi_leg_fare_estimates_base.parquet",
        "taxi_fare_model_validation.json": args.fare_dir
        / "taxi_fare_model_validation.json",
        "taxi_leg_utility_audit_base.parquet": args.utility_dir
        / "taxi_leg_utility_audit_base.parquet",
        "taxi_utility_design_validation.json": args.utility_dir
        / "taxi_utility_design_validation.json",
    }
    protected_file_paths = protected_paths(matsim_root)
    require_files(source_paths)
    require_files(protected_file_paths)

    source_hashes_before = hash_paths(source_paths)
    protected_hashes_before = hash_paths(protected_file_paths)
    protected_status_before = protected_git_status()

    base = pd.read_parquet(source_paths["taxi_leg_fare_estimates_base.parquet"])
    fare_validation = json.loads(
        source_paths["taxi_fare_model_validation.json"].read_text(encoding="utf-8")
    )
    utility_validation = json.loads(
        source_paths["taxi_utility_design_validation.json"].read_text(
            encoding="utf-8"
        )
    )
    ride_scoring = parse_ride_scoring(
        protected_file_paths[
            "config_hong_kong_5pct_v2_activity_modechoice_50it.xml"
        ]
    )

    if len(base) != EXPECTED_LEGS:
        raise ValueError(f"Expected {EXPECTED_LEGS} base legs, found {len(base)}")
    if not base["scenario"].eq("base").all():
        raise ValueError("The fare input contains non-base scenario rows")
    if base.duplicated(LEG_KEY).any():
        raise ValueError("Duplicate leg keys in the base fare input")

    audit = build_leg_audit(base)
    numeric_columns = [
        "route_distance_m",
        "actual_travel_time_s",
        "fare_baseline_hkd",
        "old_ride_score",
        "new_taxi_score_before_asc",
        "asc_equivalent",
    ]
    numeric_values = audit[numeric_columns].to_numpy(dtype=float)
    if not np.isfinite(numeric_values).all():
        raise ValueError("Non-finite values found in the bridge audit")
    if (audit[["route_distance_m", "actual_travel_time_s", "fare_baseline_hkd"]] < 0).any().any():
        raise ValueError("Negative distance, travel time, or fare found")

    summary = build_summary(audit)
    candidates, candidate_metadata = choose_candidates(audit)
    utility_crosscheck = utility_design_crosscheck(
        audit, source_paths["taxi_leg_utility_audit_base.parquet"]
    )

    audit_path = args.out_dir / "old_ride_vs_new_taxi_leg_audit.parquet"
    summary_path = args.out_dir / "old_ride_vs_new_taxi_summary.csv"
    candidates_path = args.out_dir / "taxi_asc_initial_candidates.csv"
    validation_path = args.out_dir / "taxi_utility_bridge_validation.json"

    audit.to_parquet(audit_path, index=False)
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    candidates.to_csv(candidates_path, index=False, encoding="utf-8-sig")

    source_hashes_after = hash_paths(source_paths)
    protected_hashes_after = hash_paths(protected_file_paths)
    protected_status_after = protected_git_status()
    asc_stats = summary_stats(audit["asc_equivalent"])
    time_cancellation_residual = (
        audit["asc_equivalent"]
        - (
            RIDE_CONSTANT
            + audit["old_ride_distance_utility"]
            - audit["new_taxi_fare_utility"]
        )
    ).abs()

    validation = {
        "scenario_family": "hong_kong_taxi_utility_bridge_v1",
        "status": "validated",
        "base_taxi_passenger_legs": int(len(audit)),
        "expected_base_taxi_passenger_legs": EXPECTED_LEGS,
        "leg_key": LEG_KEY,
        "formula": {
            "old_ride_score": (
                "-1.5 + (-6.0 * travel_time_hours) "
                "+ (-0.0015 * route_distance_m)"
            ),
            "new_taxi_score_before_asc": (
                "(-6.0 * travel_time_hours) "
                "+ (-0.05 * fare_baseline_hkd)"
            ),
            "asc_equivalent": (
                "old_ride_score - new_taxi_score_before_asc"
            ),
            "fare_sign_note": (
                "The positive 0.05 util/HKD coefficient is applied as a "
                "negative fare disutility, consistent with taxi utility "
                "design v1."
            ),
        },
        "parameters": {
            "ride_constant": RIDE_CONSTANT,
            "travel_utility_per_hour": TRAVEL_UTILITY_PER_HOUR,
            "ride_distance_utility_per_m": RIDE_DISTANCE_UTILITY_PER_M,
            "taxi_fare_utility_per_hkd": TAXI_FARE_UTILITY_PER_HKD,
            "taxi_fare_share_factor": TAXI_FARE_SHARE_FACTOR,
        },
        "observed_ride_scoring_from_config": ride_scoring,
        "ride_scoring_matches_bridge_parameters": bool(
            ride_scoring["constant"] == RIDE_CONSTANT
            and ride_scoring["marginalUtilityOfTraveling_util_hr"]
            == TRAVEL_UTILITY_PER_HOUR
            and ride_scoring["monetaryDistanceRate"]
            == RIDE_DISTANCE_UTILITY_PER_M
        ),
        "asc_equivalent_statistics": asc_stats,
        "candidate_selection": candidate_metadata,
        "checks": {
            "row_count_ok": len(audit) == EXPECTED_LEGS,
            "all_scenarios_are_base": bool(audit["scenario"].eq("base").all()),
            "unique_leg_keys": not audit.duplicated(LEG_KEY).any(),
            "all_required_numeric_values_finite": bool(
                np.isfinite(numeric_values).all()
            ),
            "distance_time_and_fare_nonnegative": bool(
                not (
                    audit[
                        [
                            "route_distance_m",
                            "actual_travel_time_s",
                            "fare_baseline_hkd",
                        ]
                    ]
                    < 0
                )
                .any()
                .any()
            ),
            "fare_validation_row_count_matches": int(
                fare_validation["base_total_taxi_passenger_legs"]
            )
            == len(audit),
            "utility_design_validation_row_count_matches": int(
                utility_validation["base_fare_legs"]
            )
            == len(audit),
            "shared_travel_time_component_cancels": bool(
                time_cancellation_residual.max() <= 1e-12
            ),
            "max_abs_time_cancellation_residual": float(
                time_cancellation_residual.max()
            ),
            "utility_design_center_crosscheck": utility_crosscheck,
        },
        "input_roots": {
            "worktree_root": ROOT.as_posix(),
            "matsim_protected_input_root": matsim_root.as_posix(),
        },
        "input_paths": {
            name: path.as_posix() for name, path in source_paths.items()
        },
        "protected_matsim_input_paths": {
            name: path.as_posix() for name, path in protected_file_paths.items()
        },
        "input_hashes_before": source_hashes_before,
        "input_hashes_after": source_hashes_after,
        "input_hashes_unchanged": source_hashes_before == source_hashes_after,
        "protected_matsim_hashes_before": protected_hashes_before,
        "protected_matsim_hashes_after": protected_hashes_after,
        "protected_matsim_hashes_unchanged": (
            protected_hashes_before == protected_hashes_after
        ),
        "protected_worktree_git_status_before": protected_status_before,
        "protected_worktree_git_status_after": protected_status_after,
        "protected_worktree_git_status_unchanged_and_empty": (
            protected_status_before == "" and protected_status_after == ""
        ),
        "output_hashes": {
            audit_path.name: sha256(audit_path),
            summary_path.name: sha256(summary_path),
            candidates_path.name: sha256(candidates_path),
        },
        "non_modification_statement": (
            "No MATSim plans, configs, networks, facilities, vehicles, Java "
            "files, modes, or simulation outputs were modified, and MATSim "
            "was not run."
        ),
        "outputs": [
            audit_path.name,
            summary_path.name,
            candidates_path.name,
            validation_path.name,
        ],
    }
    validation_path.write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "output_directory": args.out_dir.as_posix(),
                "legs": len(audit),
                "asc_equivalent": asc_stats,
                "selected_candidates": candidate_metadata["selected_candidates"],
                "utility_design_scores_match": utility_crosscheck[
                    "scores_match_within_1e_12"
                ],
                "protected_matsim_hashes_unchanged": (
                    protected_hashes_before == protected_hashes_after
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
