#!/usr/bin/env python3
"""Map Hong Kong TPDM design flows to RdNet/MATSim road links.

This is a decision-support workflow. It does not edit any MATSim network.
Official TPDM design flows are kept separate from observed traffic lower
bounds so that inferred demand is not silently presented as design capacity.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


DEFAULT_PROJECT_ROOT = Path(r"F:\Matsim\matsim-example-project")
TPDM_URL = "https://www.td.gov.hk/filemanager/en/content_5055/V2_03_2026.pdf"
TPDM_EDITION = "March 2026"
TPDM_TABLE = "Volume 2, Chapter 2, Table 2.4.1.1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument("--road-calibration-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--detector-quantile",
        type=float,
        default=0.99,
        help="One-day 15-minute detector quantile retained as a stress diagnostic.",
    )
    return parser.parse_args()


def finite_max(*values: Any) -> float:
    valid = [float(value) for value in values if pd.notna(value) and math.isfinite(float(value))]
    return max(valid) if valid else math.nan


def reference_table() -> pd.DataFrame:
    """Return a machine-readable transcription of TPDM Table 2.4.1.1."""
    rows = [
        ("expressway_trunk", "dual", 2, 7.3, "one_direction", 3000),
        ("expressway_trunk", "dual", 3, 11.0, "one_direction", 4700),
        ("expressway_trunk", "dual", 4, 14.6, "one_direction", 6300),
        ("primary_distributor", "two_lane", 2, 7.3, "both_directions", 2000),
        ("primary_distributor", "two_lane", 2, 10.0, "both_directions", 2400),
        ("primary_distributor", "undivided_four_lane", 4, 13.5, "one_direction", 2400),
        ("primary_distributor", "undivided_four_lane", 4, 14.6, "one_direction", 2600),
        ("primary_distributor", "dual", 2, 6.75, "one_direction", 2600),
        ("primary_distributor", "dual", 2, 7.3, "one_direction", 2800),
        ("primary_distributor", "dual", 3, 11.0, "one_direction", 4200),
        ("district_distributor", "two_lane", 2, 6.75, "both_directions", 1400),
        ("district_distributor", "two_lane", 2, 7.3, "both_directions", 1700),
        ("district_distributor", "two_lane", 2, 10.0, "both_directions", 2200),
        ("district_distributor", "undivided_four_lane", 4, 13.5, "one_direction", 1900),
        ("district_distributor", "undivided_four_lane", 4, 14.6, "one_direction", 2000),
        ("local_road", "two_lane", 2, math.nan, "both_directions", 800),
    ]
    columns = [
        "tpdm_road_family",
        "tpdm_carriageway",
        "total_lanes",
        "carriageway_width_m",
        "published_flow_basis",
        "published_design_flow_vph",
    ]
    result = pd.DataFrame(rows, columns=columns)
    result["source_edition"] = TPDM_EDITION
    result["source_table"] = TPDM_TABLE
    result["source_url"] = TPDM_URL
    result["heavy_vehicle_share_included"] = 0.15
    return result


def infer_tpdm_family(road_type: str) -> tuple[str, str]:
    if road_type in {"EX", "UT", "RT"}:
        return "expressway_trunk", "direct_road_class_mapping"
    if road_type == "PD":
        return "primary_distributor", "direct_road_class_mapping"
    if road_type == "DD":
        return "district_distributor", "direct_road_class_mapping"
    if road_type == "LD":
        return "local_road", "local_distributor_to_local_road"
    if road_type == "RR":
        return "local_road", "rural_road_to_local_road_provisional"
    return "unmapped", "unmapped"


def infer_cross_section(travel_direction: int, per_direction_lanes: int) -> tuple[str, str]:
    if travel_direction == 1 and per_direction_lanes == 1:
        return "two_lane", "bidirectional_centerline_one_lane_each_direction"
    if travel_direction == 1 and per_direction_lanes == 2:
        return "undivided_four_lane", "bidirectional_centerline_two_lanes_each_direction"
    if travel_direction == 3:
        return "dual", "one_way_centerline_assumed_separate_carriageway"
    return "nonstandard_undivided", "lane_count_not_covered_by_tpdm_table"


def tpdm_directional_capacity(
    family: str,
    cross_section: str,
    lanes: int,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "tpdm_capacity_low_vph": math.nan,
        "tpdm_capacity_reference_vph": math.nan,
        "tpdm_capacity_high_vph": math.nan,
        "tpdm_match_status": "no_official_table_value",
        "tpdm_value_basis": "",
    }
    if family == "expressway_trunk" and cross_section == "dual":
        exact = {2: 3000.0, 3: 4700.0, 4: 6300.0}
        if lanes in exact:
            value = exact[lanes]
            result.update(
                tpdm_capacity_low_vph=value,
                tpdm_capacity_reference_vph=value,
                tpdm_capacity_high_vph=value,
                tpdm_match_status="exact",
                tpdm_value_basis=f"dual_{lanes}_lane_one_direction",
            )
        elif lanes >= 1:
            value = 1500.0 * lanes if lanes == 1 else 1575.0 * lanes
            result.update(
                tpdm_capacity_low_vph=value,
                tpdm_capacity_reference_vph=value,
                tpdm_capacity_high_vph=value,
                tpdm_match_status="lane_extrapolation",
                tpdm_value_basis="extrapolated_from_dual_2_or_4_lane",
            )
    elif family == "primary_distributor":
        if cross_section == "two_lane":
            result.update(
                tpdm_capacity_low_vph=1000.0,
                tpdm_capacity_reference_vph=1000.0,
                tpdm_capacity_high_vph=1200.0,
                tpdm_match_status="width_range",
                tpdm_value_basis="published_two_way_flow_split_equally_by_direction",
            )
        elif cross_section == "undivided_four_lane":
            result.update(
                tpdm_capacity_low_vph=2400.0,
                tpdm_capacity_reference_vph=2500.0,
                tpdm_capacity_high_vph=2600.0,
                tpdm_match_status="width_range",
                tpdm_value_basis="published_one_direction_13.5_to_14.6m",
            )
        elif cross_section == "dual":
            if lanes == 2:
                result.update(
                    tpdm_capacity_low_vph=2600.0,
                    tpdm_capacity_reference_vph=2800.0,
                    tpdm_capacity_high_vph=2800.0,
                    tpdm_match_status="width_range",
                    tpdm_value_basis="published_dual_2_lane_6.75_to_7.3m",
                )
            elif lanes == 3:
                result.update(
                    tpdm_capacity_low_vph=4200.0,
                    tpdm_capacity_reference_vph=4200.0,
                    tpdm_capacity_high_vph=4200.0,
                    tpdm_match_status="exact",
                    tpdm_value_basis="published_dual_3_lane_one_direction",
                )
            elif lanes >= 1:
                value = 1400.0 * lanes
                result.update(
                    tpdm_capacity_low_vph=value,
                    tpdm_capacity_reference_vph=value,
                    tpdm_capacity_high_vph=value,
                    tpdm_match_status="lane_extrapolation",
                    tpdm_value_basis="extrapolated_from_primary_dual_2_or_3_lane",
                )
    elif family == "district_distributor":
        if cross_section == "two_lane":
            result.update(
                tpdm_capacity_low_vph=700.0,
                tpdm_capacity_reference_vph=850.0,
                tpdm_capacity_high_vph=1100.0,
                tpdm_match_status="width_range",
                tpdm_value_basis="published_two_way_flow_split_equally_by_direction",
            )
        elif cross_section == "undivided_four_lane":
            result.update(
                tpdm_capacity_low_vph=1900.0,
                tpdm_capacity_reference_vph=1950.0,
                tpdm_capacity_high_vph=2000.0,
                tpdm_match_status="width_range",
                tpdm_value_basis="published_one_direction_13.5_to_14.6m",
            )
    elif family == "local_road" and cross_section == "two_lane":
        result.update(
            tpdm_capacity_low_vph=400.0,
            tpdm_capacity_reference_vph=400.0,
            tpdm_capacity_high_vph=400.0,
            tpdm_match_status="exact_local_guidance",
            tpdm_value_basis="published_800_vph_two_way_split_equally_by_direction",
        )
    return result


def build_detector_flow_bounds(
    calibration_dir: Path,
    quantile: float,
) -> pd.DataFrame:
    windows = pd.read_csv(calibration_dir / "traffic_detector_15min_windows.csv")
    detector_stats = pd.read_csv(
        calibration_dir / "traffic_detector_lane_capacity_estimates.csv"
    )
    matches = pd.read_csv(calibration_dir / "traffic_detector_route_crosswalk.csv")
    detector_stats = detector_stats.loc[
        detector_stats["lane_count_reliable"].astype(str).str.lower().eq("true"),
        ["detector_id", "modal_lanes"],
    ]
    data = (
        windows.merge(detector_stats, on="detector_id", how="inner")
        .merge(
            matches[
                [
                    "AID_ID_Number",
                    "route_id",
                    "matched_direction",
                    "match_status",
                ]
            ].rename(columns={"AID_ID_Number": "detector_id"}),
            on="detector_id",
            how="inner",
        )
    )
    data = data.loc[
        data["match_status"].eq("matched") & data["observed_seconds"].ge(450.0)
    ].copy()
    data["window_start"] = pd.to_datetime(data["window_start"])
    data["detector_total_flow_vph"] = (
        data["flow_rate_vphpl"] * data["modal_lanes"]
    )
    data["estimated_window_volume"] = (
        data["detector_total_flow_vph"] * data["observed_seconds"] / 3600.0
    )
    hourly_frames: list[pd.DataFrame] = []
    for detector_id, frame in data.groupby("detector_id"):
        frame = frame.sort_values("window_start").drop_duplicates("window_start")
        frame = frame.set_index("window_start")
        full_index = pd.date_range(frame.index.min(), frame.index.max(), freq="15min")
        frame = frame.reindex(full_index)
        rolling_count = frame["detector_total_flow_vph"].notna().rolling(4).sum()
        rolling_seconds = frame["observed_seconds"].fillna(0).rolling(4).sum()
        rolling_volume = frame["estimated_window_volume"].fillna(0).rolling(4).sum()
        frame["rolling_hour_coverage"] = rolling_seconds / 3600.0
        frame["rolling_hour_flow_vph"] = (
            rolling_volume * 3600.0 / rolling_seconds.replace(0, np.nan)
        )
        frame.loc[
            rolling_count.lt(4) | frame["rolling_hour_coverage"].lt(0.75),
            "rolling_hour_flow_vph",
        ] = np.nan
        frame["detector_id"] = detector_id
        hourly_frames.append(
            frame[
                ["detector_id", "rolling_hour_coverage", "rolling_hour_flow_vph"]
            ].reset_index(names="hour_end")
        )
    hourly = pd.concat(hourly_frames, ignore_index=True)
    hourly = hourly.dropna(subset=["rolling_hour_flow_vph"])
    hourly = hourly.merge(
        data[
            [
                "detector_id",
                "route_id",
                "matched_direction",
            ]
        ].drop_duplicates("detector_id"),
        on="detector_id",
        how="left",
    )
    rows: list[dict[str, Any]] = []
    for (route_id, direction), frame in data.groupby(
        ["route_id", "matched_direction"]
    ):
        values = frame["detector_total_flow_vph"].dropna()
        route_hourly = hourly.loc[
            hourly["route_id"].eq(route_id)
            & hourly["matched_direction"].eq(direction)
        ]
        peak_index = (
            route_hourly["rolling_hour_flow_vph"].idxmax()
            if not route_hourly.empty
            else None
        )
        rows.append(
            {
                "route_id": int(route_id),
                "direction": str(direction),
                "detector_windows": int(len(values)),
                "detector_count": int(frame["detector_id"].nunique()),
                "detector_15min_flow_q95_vph": float(values.quantile(0.95)),
                "detector_15min_flow_stress_vph": float(values.quantile(quantile)),
                "detector_15min_flow_max_vph": float(values.max()),
                "detector_peak_hour_windows": int(len(route_hourly)),
                "detector_flow_floor_vph": (
                    float(route_hourly.loc[peak_index, "rolling_hour_flow_vph"])
                    if peak_index is not None
                    else math.nan
                ),
                "detector_peak_hour_coverage": (
                    float(route_hourly.loc[peak_index, "rolling_hour_coverage"])
                    if peak_index is not None
                    else math.nan
                ),
                "detector_min_window_coverage": float(
                    frame["observed_seconds"].min() / 900.0
                ),
            }
        )
    return pd.DataFrame(rows)


def build_detailed_atc_bounds(calibration_dir: Path) -> pd.DataFrame:
    details = pd.read_csv(calibration_dir / "atc_directional_details_2024.csv")
    matches = pd.read_csv(calibration_dir / "atc_direction_route_crosswalk.csv")
    data = details.merge(
        matches[
            ["station_no", "direction", "route_id", "matched_direction", "match_status"]
        ],
        on=["station_no", "direction"],
        how="inner",
    )
    data = data.loc[data["match_status"].eq("matched")].copy()
    data["detailed_atc_peak_vph"] = data[
        ["weekday_am_peak_flow", "weekday_pm_peak_flow"]
    ].max(axis=1)
    result = (
        data.groupby(["route_id", "matched_direction"], as_index=False)
        .agg(
            detailed_atc_peak_vph=("detailed_atc_peak_vph", "max"),
            detailed_atc_station_count=("station_no", "nunique"),
        )
        .rename(columns={"matched_direction": "direction"})
    )
    result["route_id"] = result["route_id"].astype(int)
    return result


def map_route_directions(
    calibration_dir: Path,
    detector_quantile: float,
) -> pd.DataFrame:
    attributes = pd.read_csv(calibration_dir / "road_route_direction_attributes.csv")
    detector = build_detector_flow_bounds(calibration_dir, detector_quantile)
    detailed = build_detailed_atc_bounds(calibration_dir)
    result = attributes.merge(detector, on=["route_id", "direction"], how="left")
    result = result.merge(detailed, on=["route_id", "direction"], how="left")

    family = result["road_type"].map(infer_tpdm_family)
    result["tpdm_road_family"] = family.map(lambda value: value[0])
    result["tpdm_family_mapping_basis"] = family.map(lambda value: value[1])
    sections = [
        infer_cross_section(int(row.travel_direction), int(row.permlanes))
        for row in result.itertuples()
    ]
    result["tpdm_carriageway"] = [value[0] for value in sections]
    result["cross_section_inference"] = [value[1] for value in sections]
    capacities = pd.DataFrame(
        [
            tpdm_directional_capacity(
                row.tpdm_road_family, row.tpdm_carriageway, int(row.permlanes)
            )
            for row in result.itertuples()
        ]
    )
    result = pd.concat([result.reset_index(drop=True), capacities], axis=1)

    direct_bounds = []
    annual_bounds = []
    stress_bounds = []
    for row in result.itertuples():
        direct = finite_max(
            row.detector_flow_floor_vph, row.detailed_atc_peak_vph
        )
        annual = (
            float(row.atc_peak_flow_vph)
            if "atc_aadt_inferred" in str(row.lane_source)
            and pd.notna(row.atc_peak_flow_vph)
            else math.nan
        )
        stress = finite_max(
            row.detector_15min_flow_stress_vph, row.detailed_atc_peak_vph
        )
        direct_bounds.append(direct)
        annual_bounds.append(annual)
        stress_bounds.append(stress)
    result["direct_flow_lower_bound_vph"] = direct_bounds
    result["annual_aadt_soft_lower_bound_vph"] = annual_bounds
    result["stress_observed_max_vph"] = stress_bounds
    result["combined_flow_lower_bound_vph"] = [
        finite_max(direct, annual)
        for direct, annual in zip(direct_bounds, annual_bounds, strict=True)
    ]

    result["tpdm_minus_direct_floor_vph"] = (
        result["tpdm_capacity_reference_vph"]
        - result["direct_flow_lower_bound_vph"]
    )
    result["tpdm_minus_combined_floor_vph"] = (
        result["tpdm_capacity_reference_vph"]
        - result["combined_flow_lower_bound_vph"]
    )
    result["direct_floor_test"] = np.select(
        [
            result["tpdm_capacity_reference_vph"].isna(),
            result["direct_flow_lower_bound_vph"].isna(),
            result["tpdm_minus_direct_floor_vph"].ge(0),
        ],
        ["no_tpdm_value", "no_direct_flow_evidence", "pass"],
        default="fail",
    )
    result["combined_floor_test"] = np.select(
        [
            result["tpdm_capacity_reference_vph"].isna(),
            result["combined_flow_lower_bound_vph"].isna(),
            result["tpdm_minus_combined_floor_vph"].ge(0),
        ],
        ["no_tpdm_value", "no_flow_evidence", "pass"],
        default="fail",
    )
    result["review_capacity_vph"] = result[
        ["tpdm_capacity_reference_vph", "combined_flow_lower_bound_vph"]
    ].max(axis=1, skipna=True)
    result.loc[
        result["tpdm_capacity_reference_vph"].isna(), "review_capacity_vph"
    ] = np.nan
    result["review_capacity_source"] = np.select(
        [
            result["tpdm_capacity_reference_vph"].isna(),
            result["combined_floor_test"].eq("fail"),
        ],
        [
            "no_tpdm_candidate",
            "tpdm_raised_to_observed_or_aadt_flow_floor",
        ],
        default="tpdm_reference",
    )
    result["review_vs_current_capacity_ratio"] = (
        result["review_capacity_vph"] / result["capacity_vph"]
    )
    result["adoption_status"] = np.select(
        [
            result["tpdm_capacity_reference_vph"].isna(),
            result["tpdm_match_status"].eq("lane_extrapolation"),
            result["direct_floor_test"].eq("fail"),
            result["combined_floor_test"].eq("fail"),
        ],
        [
            "manual_cross_section_review",
            "review_extrapolated_lane_count",
            "review_direct_flow_exceeds_tpdm",
            "review_aadt_soft_floor_exceeds_tpdm",
        ],
        default="candidate_for_review",
    )
    return result


def map_matsim_links(
    calibration_dir: Path,
    route_mapping: pd.DataFrame,
) -> pd.DataFrame:
    links = pd.read_csv(calibration_dir / "matsim_link_attributes.csv")
    keep = [
        "route_id",
        "direction",
        "tpdm_road_family",
        "tpdm_carriageway",
        "cross_section_inference",
        "tpdm_match_status",
        "tpdm_value_basis",
        "tpdm_capacity_low_vph",
        "tpdm_capacity_reference_vph",
        "tpdm_capacity_high_vph",
        "direct_flow_lower_bound_vph",
        "annual_aadt_soft_lower_bound_vph",
        "combined_flow_lower_bound_vph",
        "direct_floor_test",
        "combined_floor_test",
        "review_capacity_vph",
        "review_capacity_source",
        "adoption_status",
    ]
    return links.merge(route_mapping[keep], on=["route_id", "direction"], how="left")


def write_plot(mapping: pd.DataFrame, path: Path) -> None:
    status_order = [
        "exact",
        "exact_local_guidance",
        "width_range",
        "lane_extrapolation",
        "no_official_table_value",
    ]
    status = mapping["tpdm_match_status"].value_counts().reindex(status_order).fillna(0)
    failures = (
        mapping.assign(
            direct_fail=mapping["direct_floor_test"].eq("fail"),
            combined_fail=mapping["combined_floor_test"].eq("fail"),
        )
        .groupby("road_type")[["direct_fail", "combined_fail"]]
        .sum()
        .reindex(["EX", "UT", "PD", "DD", "LD", "RT", "RR"])
        .fillna(0)
    )
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    axes[0].bar(status.index, status.values, color=["#287271", "#2a9d8f", "#e9c46a", "#f4a261", "#6c757d"])
    axes[0].set_title("TPDM mapping coverage")
    axes[0].set_ylabel("RdNet route-directions")
    axes[0].tick_params(axis="x", rotation=25)
    failures.plot.bar(ax=axes[1], color=["#d1495b", "#edae49"])
    axes[1].set_title("TPDM reference below traffic lower bound")
    axes[1].set_ylabel("RdNet route-directions")
    axes[1].set_xlabel("Road type")
    axes[1].legend(["Direct detector/ATC", "Including AADT soft floor"])
    axes[1].tick_params(axis="x", rotation=0)
    fig.suptitle("Hong Kong TPDM capacity mapping decision support")
    fig.tight_layout()
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def json_number(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not math.isfinite(float(value)) else float(value)
    return value


def main() -> None:
    args = parse_args()
    if not 0.5 <= args.detector_quantile <= 1.0:
        raise SystemExit("--detector-quantile must be between 0.5 and 1.0")
    project_root = args.project_root.resolve()
    calibration_dir = (
        args.road_calibration_dir.resolve()
        if args.road_calibration_dir
        else project_root
        / "data"
        / "transit"
        / "hongkong"
        / "processed"
        / "road_speed_capacity_2026_v1"
    )
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else project_root
        / "data"
        / "transit"
        / "hongkong"
        / "processed"
        / "road_tpdm_capacity_mapping_2026_v1"
    )
    required = [
        "road_route_direction_attributes.csv",
        "matsim_link_attributes.csv",
        "traffic_detector_15min_windows.csv",
        "traffic_detector_lane_capacity_estimates.csv",
        "traffic_detector_route_crosswalk.csv",
        "atc_directional_details_2024.csv",
        "atc_direction_route_crosswalk.csv",
    ]
    missing = [name for name in required if not (calibration_dir / name).exists()]
    if missing:
        raise SystemExit(f"Missing calibration inputs: {missing}")
    output_dir.mkdir(parents=True, exist_ok=True)

    reference = reference_table()
    mapping = map_route_directions(calibration_dir, args.detector_quantile)
    links = map_matsim_links(calibration_dir, mapping)
    exceptions = mapping.loc[
        mapping["adoption_status"].ne("candidate_for_review")
    ].copy()
    by_type = (
        mapping.groupby("road_type", as_index=False)
        .agg(
            route_directions=("route_id", "size"),
            tpdm_mapped=("tpdm_capacity_reference_vph", "count"),
            direct_flow_evidence=("direct_flow_lower_bound_vph", "count"),
            combined_flow_evidence=("combined_flow_lower_bound_vph", "count"),
            direct_floor_failures=("direct_floor_test", lambda x: int((x == "fail").sum())),
            combined_floor_failures=(
                "combined_floor_test",
                lambda x: int((x == "fail").sum()),
            ),
            current_capacity_median_vph=("capacity_vph", "median"),
            tpdm_reference_median_vph=("tpdm_capacity_reference_vph", "median"),
            review_capacity_median_vph=("review_capacity_vph", "median"),
        )
    )

    reference.to_csv(output_dir / "tpdm_design_flow_reference.csv", index=False)
    mapping.to_csv(output_dir / "rdnet_route_direction_tpdm_mapping.csv", index=False)
    links.to_csv(output_dir / "matsim_link_tpdm_mapping.csv", index=False)
    exceptions.to_csv(output_dir / "tpdm_flow_floor_and_mapping_exceptions.csv", index=False)
    by_type.to_csv(output_dir / "tpdm_mapping_summary_by_road_type.csv", index=False)
    write_plot(mapping, output_dir / "tpdm_capacity_mapping_qa.png")

    direct_evidence = mapping["direct_flow_lower_bound_vph"].notna()
    combined_evidence = mapping["combined_flow_lower_bound_vph"].notna()
    mapped = mapping["tpdm_capacity_reference_vph"].notna()
    summary = {
        "purpose": "Decision support only; no MATSim network was modified.",
        "tpdm": {
            "edition": TPDM_EDITION,
            "table": TPDM_TABLE,
            "url": TPDM_URL,
            "heavy_vehicle_share_included": 0.15,
        },
        "detector_peak_hour_minimum_coverage": 0.75,
        "detector_15min_stress_quantile": args.detector_quantile,
        "route_directions": len(mapping),
        "matsim_road_links": len(links),
        "tpdm_mapped_route_directions": int(mapped.sum()),
        "tpdm_mapping_share": float(mapped.mean()),
        "direct_flow_evidence_route_directions": int(direct_evidence.sum()),
        "combined_flow_evidence_route_directions": int(combined_evidence.sum()),
        "direct_floor_failures": int(mapping["direct_floor_test"].eq("fail").sum()),
        "combined_floor_failures": int(
            mapping["combined_floor_test"].eq("fail").sum()
        ),
        "adoption_status": mapping["adoption_status"].value_counts().to_dict(),
        "tpdm_match_status": mapping["tpdm_match_status"].value_counts().to_dict(),
        "important_limitations": [
            "RdNet has no carriageway width field; width-dependent TPDM values remain ranges.",
            "TRAVEL_DIRECTION=3 is treated as a separate one-way/dual carriageway.",
            "Two-way TPDM flows are split equally between MATSim directions.",
            "AADT-derived peak flow is a soft lower bound, not a direct hourly observation.",
            "No heavy-vehicle adjustment is applied because the normalized directional inputs do not contain a reliable heavy-vehicle share.",
            "Junction and signal capacity constraints are not represented by this link table.",
        ],
        "outputs": {
            "reference": "tpdm_design_flow_reference.csv",
            "route_direction_mapping": "rdnet_route_direction_tpdm_mapping.csv",
            "matsim_link_mapping": "matsim_link_tpdm_mapping.csv",
            "exceptions": "tpdm_flow_floor_and_mapping_exceptions.csv",
            "by_road_type": "tpdm_mapping_summary_by_road_type.csv",
            "plot": "tpdm_capacity_mapping_qa.png",
        },
    }
    with (output_dir / "tpdm_capacity_mapping_summary.json").open(
        "w", encoding="utf-8"
    ) as stream:
        json.dump(summary, stream, indent=2, ensure_ascii=True, default=json_number)
    print(json.dumps(summary, indent=2, ensure_ascii=True, default=json_number))


if __name__ == "__main__":
    main()
