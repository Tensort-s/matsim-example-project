#!/usr/bin/env python3
"""Build Hong Kong taxi utility-conversion scenario diagnostics.

This is an offline design layer. It does not modify MATSim plans, configs,
facilities, vehicles, networks, or simulation outputs.
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
WINDOWS_ROOT = Path(r"F:\Matsim\matsim-example-project")
PROJECT_ROOT = WINDOWS_ROOT if WINDOWS_ROOT.exists() else ROOT
DATA_ROOT = PROJECT_ROOT / "data"

FARE_DIR = DATA_ROOT / "taxi/hongkong/processed/taxi_fare_model_v1"
OUT_DIR = DATA_ROOT / "taxi/hongkong/processed/taxi_utility_design_v1"
V2_DIR = DATA_ROOT / "matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice"
NETWORK_PATH = (
    DATA_ROOT
    / "transit/hongkong/processed/"
    "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_ferry_core_v1_cap010/network.xml.gz"
)

FARE_UTILITY_COEFFICIENTS = [0.03, 0.05, 0.075, 0.10]
FARE_SHARE_FACTORS = [1.0, 0.75, 0.5]
ASC_VALUES = list(range(-3, 9))
TAXI_TRAVEL_UTILITY_PER_HR = -6.0
EFFECTIVE_TIME_UTILITY_PER_HR = -12.0
GLOBAL_MARGINAL_UTILITY_OF_MONEY = 1.0
CENTRAL_FARE_UTILITY_PER_HKD = 0.05
CENTRAL_FARE_SHARE_FACTOR = 1.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fare-dir", type=Path, default=FARE_DIR)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--v2-dir", type=Path, default=V2_DIR)
    parser.add_argument("--network-path", type=Path, default=NETWORK_PATH)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def protected_paths(v2_dir: Path, network_path: Path) -> dict[str, Path]:
    return {
        "plans_unrouted_5pct_v2.xml.gz": v2_dir / "plans_unrouted_5pct_v2.xml.gz",
        "plans_routed_5pct_v2.xml.gz": v2_dir / "plans_routed_5pct_v2.xml.gz",
        "config_hong_kong_5pct_v2_activity_modechoice_50it.xml": v2_dir
        / "config_hong_kong_5pct_v2_activity_modechoice_50it.xml",
        "facilities_5pct_v2.xml.gz": v2_dir / "facilities_5pct_v2.xml.gz",
        "privateVehicles_5pct.xml.gz": v2_dir / "privateVehicles_5pct.xml.gz",
        "network.xml.gz": network_path,
    }


def input_paths(fare_dir: Path) -> dict[str, Path]:
    return {
        "taxi_leg_fare_estimates_base.parquet": fare_dir / "taxi_leg_fare_estimates_base.parquet",
        "taxi_leg_fare_estimates_low.parquet": fare_dir / "taxi_leg_fare_estimates_low.parquet",
        "taxi_leg_fare_estimates_high.parquet": fare_dir / "taxi_leg_fare_estimates_high.parquet",
        "taxi_fare_model_validation.json": fare_dir / "taxi_fare_model_validation.json",
    }


def hash_existing(paths: dict[str, Path]) -> dict[str, str]:
    return {name: sha256(path) for name, path in paths.items() if path.exists()}


def git_status_matsim_agents() -> str:
    result = subprocess.run(
        ["git", "status", "--short", "--", "data/matsim_agents/hongkong"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def parse_scoring(config_path: Path) -> dict[str, object]:
    root = ET.parse(config_path).getroot()
    scoring = root.find("./module[@name='scoring']")
    if scoring is None:
        raise ValueError(f"No scoring module in {config_path}")
    mode_params: dict[str, dict[str, str]] = {}
    global_params = {param.attrib["name"]: param.attrib.get("value", "") for param in scoring.findall("./param")}
    for parameter_set in scoring.findall("./parameterset"):
        if parameter_set.attrib.get("type") != "modeParams":
            continue
        params = {param.attrib["name"]: param.attrib.get("value", "") for param in parameter_set.findall("./param")}
        mode = params.get("mode")
        if mode:
            mode_params[mode] = params
    return {
        "config_path": config_path.as_posix(),
        "global_scoring_params": global_params,
        "global_marginal_utility_of_money_assumed": GLOBAL_MARGINAL_UTILITY_OF_MONEY,
        "global_marginal_utility_of_money_note": (
            "No taxi fare conversion uses global marginalUtilityOfMoney; "
            "taxi_fare_utility_per_hkd is scenario-specific."
        ),
        "mode_params": mode_params,
    }


def summary_stats(values: pd.Series, prefix: str = "") -> dict[str, float]:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    return {
        f"{prefix}mean": float(clean.mean()),
        f"{prefix}median": float(clean.median()),
        f"{prefix}p10": float(clean.quantile(0.10)),
        f"{prefix}p25": float(clean.quantile(0.25)),
        f"{prefix}p75": float(clean.quantile(0.75)),
        f"{prefix}p90": float(clean.quantile(0.90)),
        f"{prefix}p95": float(clean.quantile(0.95)),
    }


def scenario_id(fare_utility: float, fare_share: float) -> str:
    fare_text = str(fare_utility).replace(".", "p")
    share_text = str(fare_share).replace(".", "p")
    return f"farecoef_{fare_text}_share_{share_text}"


def build_parameter_scenarios(base: pd.DataFrame) -> pd.DataFrame:
    rows = []
    fare = base["total_fare_distance_only_hkd"]
    travel_hours = base["actual_travel_time_s"] / 3600.0
    direct_time = TAXI_TRAVEL_UTILITY_PER_HR * travel_hours
    effective_time = EFFECTIVE_TIME_UTILITY_PER_HR * travel_hours
    for fare_utility in FARE_UTILITY_COEFFICIENTS:
        for fare_share in FARE_SHARE_FACTORS:
            fare_util = -fare_utility * fare * fare_share
            total_before_asc = direct_time + fare_util
            rows.append(
                {
                    "scenario_id": scenario_id(fare_utility, fare_share),
                    "taxi_fare_utility_per_hkd": fare_utility,
                    "fare_share_factor": fare_share,
                    "marginal_utility_of_traveling_util_hr": TAXI_TRAVEL_UTILITY_PER_HR,
                    "effective_time_diagnostic_util_hr": EFFECTIVE_TIME_UTILITY_PER_HR,
                    "implied_vot_hkd_hr": 12.0 / fare_utility,
                    "is_recommended_center": bool(
                        fare_utility == CENTRAL_FARE_UTILITY_PER_HKD
                        and fare_share == CENTRAL_FARE_SHARE_FACTOR
                    ),
                    **summary_stats(fare_util, "taxi_fare_utility_"),
                    **summary_stats(direct_time, "direct_travel_time_utility_"),
                    **summary_stats(effective_time, "approx_effective_time_utility_"),
                    **summary_stats(total_before_asc, "total_leg_utility_before_asc_"),
                }
            )
    return pd.DataFrame(rows)


def build_leg_audit(base: pd.DataFrame) -> pd.DataFrame:
    id_columns = [
        "scenario",
        "person_id",
        "tour_id",
        "leg_sequence",
        "classification_source",
        "taxi_type",
        "departure_time_s",
        "route_distance_m",
        "actual_travel_time_s",
        "total_fare_distance_only_hkd",
        "population_group",
        "role",
        "activity_purpose",
    ]
    present = [column for column in id_columns if column in base.columns]
    base_ids = base[present].copy()
    base_ids = base_ids.rename(columns={"total_fare_distance_only_hkd": "fare_baseline_hkd"})
    base_ids["travel_time_hours"] = base_ids["actual_travel_time_s"] / 3600.0
    direct_time = TAXI_TRAVEL_UTILITY_PER_HR * base_ids["travel_time_hours"]
    effective_time = EFFECTIVE_TIME_UTILITY_PER_HR * base_ids["travel_time_hours"]
    frames = []
    for fare_utility in FARE_UTILITY_COEFFICIENTS:
        for fare_share in FARE_SHARE_FACTORS:
            frame = base_ids.copy()
            frame["scenario_id"] = scenario_id(fare_utility, fare_share)
            frame["taxi_fare_utility_per_hkd"] = fare_utility
            frame["fare_share_factor"] = fare_share
            frame["marginal_utility_of_traveling_util_hr"] = TAXI_TRAVEL_UTILITY_PER_HR
            frame["taxi_fare_utility"] = -fare_utility * frame["fare_baseline_hkd"] * fare_share
            frame["direct_travel_time_utility"] = direct_time
            frame["approximate_effective_time_utility"] = effective_time
            frame["total_leg_utility_before_asc"] = frame["taxi_fare_utility"] + frame["direct_travel_time_utility"]
            frame["fare_to_direct_time_utility_ratio"] = (
                frame["taxi_fare_utility"].abs() / frame["direct_travel_time_utility"].abs().replace(0, np.nan)
            )
            frame["fare_to_effective_time_utility_ratio"] = (
                frame["taxi_fare_utility"].abs()
                / frame["approximate_effective_time_utility"].abs().replace(0, np.nan)
            )
            frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def build_utility_summary(leg_audit: pd.DataFrame) -> pd.DataFrame:
    rows = []
    metrics = [
        "taxi_fare_utility",
        "direct_travel_time_utility",
        "approximate_effective_time_utility",
        "total_leg_utility_before_asc",
        "fare_to_direct_time_utility_ratio",
        "fare_to_effective_time_utility_ratio",
    ]
    for scenario, group in leg_audit.groupby("scenario_id", sort=True):
        row = {
            "scenario_id": scenario,
            "taxi_fare_utility_per_hkd": float(group["taxi_fare_utility_per_hkd"].iloc[0]),
            "fare_share_factor": float(group["fare_share_factor"].iloc[0]),
            "implied_vot_hkd_hr": 12.0 / float(group["taxi_fare_utility_per_hkd"].iloc[0]),
            "legs": int(len(group)),
        }
        for metric in metrics:
            row.update(summary_stats(group[metric], f"{metric}_"))
        rows.append(row)
    return pd.DataFrame(rows)


def build_asc_grid(summary: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, scenario in summary.iterrows():
        for asc in ASC_VALUES:
            rows.append(
                {
                    "scenario_id": scenario["scenario_id"],
                    "taxi_fare_utility_per_hkd": scenario["taxi_fare_utility_per_hkd"],
                    "fare_share_factor": scenario["fare_share_factor"],
                    "taxi_asc": asc,
                    "mean_total_leg_utility_with_asc": scenario["total_leg_utility_before_asc_mean"] + asc,
                    "median_total_leg_utility_with_asc": scenario["total_leg_utility_before_asc_median"] + asc,
                    "p10_total_leg_utility_with_asc": scenario["total_leg_utility_before_asc_p10"] + asc,
                    "p90_total_leg_utility_with_asc": scenario["total_leg_utility_before_asc_p90"] + asc,
                    "asc_search_note": (
                        "Offline utility offset only; final mode share cannot be inferred without MATSim replanning."
                    ),
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    args = parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    input_file_paths = input_paths(args.fare_dir)
    protected_file_paths = protected_paths(args.v2_dir, args.network_path)
    hashes_before = {
        "fare_inputs": hash_existing(input_file_paths),
        "protected_matsim_inputs": hash_existing(protected_file_paths),
    }
    git_before = git_status_matsim_agents()

    base = pd.read_parquet(args.fare_dir / "taxi_leg_fare_estimates_base.parquet")
    low = pd.read_parquet(args.fare_dir / "taxi_leg_fare_estimates_low.parquet", columns=["scenario"])
    high = pd.read_parquet(args.fare_dir / "taxi_leg_fare_estimates_high.parquet", columns=["scenario"])
    fare_validation = json.loads(
        (args.fare_dir / "taxi_fare_model_validation.json").read_text(encoding="utf-8")
    )
    scoring = parse_scoring(args.v2_dir / "config_hong_kong_5pct_v2_activity_modechoice_50it.xml")

    parameter_scenarios = build_parameter_scenarios(base)
    leg_audit = build_leg_audit(base)
    utility_summary = build_utility_summary(leg_audit)
    asc_grid = build_asc_grid(utility_summary)

    parameter_scenarios.to_csv(
        args.out_dir / "taxi_utility_parameter_scenarios.csv",
        index=False,
        encoding="utf-8-sig",
    )
    leg_audit.to_parquet(args.out_dir / "taxi_leg_utility_audit_base.parquet", index=False)
    utility_summary.to_csv(args.out_dir / "taxi_utility_summary.csv", index=False, encoding="utf-8-sig")
    asc_grid.to_csv(args.out_dir / "taxi_asc_search_grid.csv", index=False, encoding="utf-8-sig")

    hashes_after = {
        "fare_inputs": hash_existing(input_file_paths),
        "protected_matsim_inputs": hash_existing(protected_file_paths),
    }
    git_after = git_status_matsim_agents()

    center = utility_summary.loc[
        utility_summary["taxi_fare_utility_per_hkd"].eq(CENTRAL_FARE_UTILITY_PER_HKD)
        & utility_summary["fare_share_factor"].eq(CENTRAL_FARE_SHARE_FACTOR)
    ].iloc[0]
    validation = {
        "scenario_family": "hong_kong_taxi_utility_design_v1",
        "base_fare_legs": int(len(base)),
        "low_fare_legs": int(len(low)),
        "high_fare_legs": int(len(high)),
        "base_fare_legs_match_fare_validation": int(len(base))
        == int(fare_validation["base_total_taxi_passenger_legs"]),
        "parameter_scenario_count": int(len(parameter_scenarios)),
        "leg_audit_rows": int(len(leg_audit)),
        "asc_grid_rows": int(len(asc_grid)),
        "global_marginal_utility_of_money_retained": GLOBAL_MARGINAL_UTILITY_OF_MONEY,
        "existing_mode_scoring_unchanged_by_design": True,
        "taxi_travel_utility_per_hr": TAXI_TRAVEL_UTILITY_PER_HR,
        "effective_time_diagnostic_utility_per_hr": EFFECTIVE_TIME_UTILITY_PER_HR,
        "fare_utility_coefficients_tested": FARE_UTILITY_COEFFICIENTS,
        "fare_share_factors_tested": FARE_SHARE_FACTORS,
        "asc_values_tested": ASC_VALUES,
        "recommended_center_scenario": {
            "taxi_fare_utility_per_hkd": CENTRAL_FARE_UTILITY_PER_HKD,
            "fare_share_factor": CENTRAL_FARE_SHARE_FACTOR,
            "taxi_asc": "to_be_calibrated_in_MATSim_iterations",
            "implied_vot_hkd_hr": float(center["implied_vot_hkd_hr"]),
            "median_total_leg_utility_before_asc": float(
                center["total_leg_utility_before_asc_median"]
            ),
            "p90_total_leg_utility_before_asc": float(center["total_leg_utility_before_asc_p90"]),
        },
        "current_config_scoring_snapshot": scoring,
        "identification_warning": (
            "Fare coefficient and ASC cannot be identified from the same taxi total target alone; "
            "fix the fare coefficient first, then calibrate ASC against final MATSim taxi legs."
        ),
        "no_mode_share_claim": (
            "ASC grid is an offline utility-offset table and is not a mode-share prediction."
        ),
        "excluded_components_v1": [
            "pickup_waiting",
            "meter_waiting_fare",
            "tunnel_surcharge",
            "booking_fee",
            "dynamic_pricing",
            "fleet_supply_constraint",
        ],
        "input_hashes_before": hashes_before,
        "input_hashes_after": hashes_after,
        "input_hashes_unchanged": hashes_before == hashes_after,
        "git_status_before_data_matsim_agents_hongkong": git_before,
        "git_status_after_data_matsim_agents_hongkong": git_after,
        "git_status_data_matsim_agents_hongkong_unchanged_and_empty": git_before == "" and git_after == "",
        "non_modification_statement": (
            "No existing Hong Kong MATSim plans, configs, networks, facilities, vehicles, or outputs are modified."
        ),
        "outputs": [
            "taxi_utility_parameter_scenarios.csv",
            "taxi_leg_utility_audit_base.parquet",
            "taxi_utility_summary.csv",
            "taxi_asc_search_grid.csv",
            "taxi_utility_design_validation.json",
        ],
    }
    (args.out_dir / "taxi_utility_design_validation.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "out_dir": args.out_dir.as_posix(),
                "parameter_scenarios": len(parameter_scenarios),
                "leg_audit_rows": len(leg_audit),
                "asc_grid_rows": len(asc_grid),
                "input_hashes_unchanged": hashes_before == hashes_after,
                "matsim_agents_git_status_empty_before_after": git_before == "" and git_after == "",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
