#!/usr/bin/env python3
"""Summarize observed road flows by corrected road class and lane count."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


DEFAULT_PROJECT_ROOT = Path(r"F:\Matsim\matsim-example-project")
ROAD_TYPE_ORDER = ["EX", "UT", "PD", "DD", "LD", "RT", "RR"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument("--decision-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def grouped_flow_statistics(
    data: pd.DataFrame,
    group_column: str,
    total_flow_column: str,
    per_lane_flow_column: str,
    source_count_column: str,
) -> pd.DataFrame:
    rows: list[dict[str, float | int | str]] = []
    for group_value, frame in data.groupby(group_column, dropna=False):
        total = pd.to_numeric(frame[total_flow_column], errors="coerce")
        per_lane = pd.to_numeric(frame[per_lane_flow_column], errors="coerce")
        valid = total.notna() & np.isfinite(total) & total.gt(0)
        frame = frame.loc[valid]
        total = total.loc[valid]
        per_lane = per_lane.loc[valid]
        if frame.empty:
            continue
        rows.append(
            {
                group_column: group_value,
                "observation_count": int(len(frame)),
                "source_count": int(frame[source_count_column].nunique()),
                "route_direction_count": int(
                    frame[["route_id", "direction"]].drop_duplicates().shape[0]
                ),
                "total_flow_q95_vph": float(total.quantile(0.95)),
                "total_flow_max_vph": float(total.max()),
                "per_lane_flow_q95_vphpl": float(per_lane.quantile(0.95)),
                "per_lane_flow_max_vphpl": float(per_lane.max()),
            }
        )
    return pd.DataFrame(rows)


def load_corrected_attributes(decision_dir: Path) -> pd.DataFrame:
    attributes = pd.read_csv(
        decision_dir / "road_route_direction_attributes_corrected.csv",
        low_memory=False,
    )
    attributes["route_id"] = attributes["route_id"].astype(int)
    attributes["direction"] = attributes["direction"].astype(str)
    attributes["final_permlanes"] = (
        pd.to_numeric(attributes["final_permlanes"], errors="raise").astype(int)
    )
    if attributes.duplicated(["route_id", "direction"]).any():
        raise RuntimeError("Corrected route-direction attributes are not unique.")
    return attributes[
        [
            "route_id",
            "direction",
            "street_ename",
            "final_road_type",
            "final_permlanes",
            "final_road_type_source",
            "final_lane_source",
            "previous_permlanes",
            "previous_lane_source",
            "lane_decision_reason",
        ]
    ]


def build_detector_observations(
    calibration_dir: Path,
    attributes: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, int]]:
    windows = pd.read_csv(calibration_dir / "traffic_detector_15min_windows.csv")
    detectors = pd.read_csv(
        calibration_dir / "traffic_detector_lane_capacity_estimates.csv"
    )
    matches = pd.read_csv(
        calibration_dir / "traffic_detector_route_crosswalk.csv"
    )
    detectors["lane_count_reliable"] = (
        detectors["lane_count_reliable"].astype(str).str.lower().eq("true")
    )
    detectors = detectors.loc[
        detectors["lane_count_reliable"],
        ["detector_id", "modal_lanes"],
    ]
    matches = matches.loc[
        matches["match_status"].eq("matched"),
        ["AID_ID_Number", "route_id", "matched_direction"],
    ].rename(
        columns={
            "AID_ID_Number": "detector_id",
            "matched_direction": "direction",
        }
    )
    data = (
        windows.merge(detectors, on="detector_id", how="inner")
        .merge(matches, on="detector_id", how="inner")
    )
    data = data.loc[data["observed_seconds"].ge(450.0)].copy()
    data["route_id"] = data["route_id"].astype(int)
    data["direction"] = data["direction"].astype(str)
    data["observed_per_lane_flow_vphpl"] = pd.to_numeric(
        data["flow_rate_vphpl"], errors="coerce"
    )
    data["observed_total_flow_vph"] = (
        data["observed_per_lane_flow_vphpl"]
        * pd.to_numeric(data["modal_lanes"], errors="coerce")
    )
    data = data.merge(
        attributes, on=["route_id", "direction"], how="inner", validate="many_to_one"
    )
    data = data.loc[
        np.isfinite(data["observed_total_flow_vph"])
        & data["observed_total_flow_vph"].gt(0)
    ].copy()
    return data, {
        "eligible_windows": int(len(data)),
        "detectors": int(data["detector_id"].nunique()),
        "route_directions": int(
            data[["route_id", "direction"]].drop_duplicates().shape[0]
        ),
    }


def build_atc_observations(
    calibration_dir: Path,
    attributes: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, int]]:
    details = pd.read_csv(
        calibration_dir / "atc_directional_details_2024.csv"
    )
    matches = pd.read_csv(
        calibration_dir / "atc_direction_route_crosswalk.csv"
    )
    data = details.merge(
        matches[
            [
                "station_no",
                "direction",
                "route_id",
                "matched_direction",
                "match_status",
            ]
        ],
        on=["station_no", "direction"],
        how="inner",
        validate="one_to_one",
    )
    data = data.loc[data["match_status"].eq("matched")].copy()
    data["route_id"] = data["route_id"].astype(int)
    data = data.rename(columns={"direction": "atc_direction"})
    data["direction"] = data["matched_direction"].astype(str)
    data["observed_total_flow_vph"] = data[
        ["weekday_am_peak_flow", "weekday_pm_peak_flow"]
    ].apply(pd.to_numeric, errors="coerce").max(axis=1)
    data = data.merge(
        attributes, on=["route_id", "direction"], how="inner", validate="many_to_one"
    )
    data = data.loc[
        np.isfinite(data["observed_total_flow_vph"])
        & data["observed_total_flow_vph"].gt(0)
    ].copy()
    data["observed_per_lane_flow_vphpl"] = (
        data["observed_total_flow_vph"] / data["final_permlanes"]
    )
    data["atc_source_id"] = (
        data["station_no"].astype(str) + ":" + data["atc_direction"].astype(str)
    )
    return data, {
        "station_directions": int(len(data)),
        "stations": int(data["station_no"].nunique()),
        "route_directions": int(
            data[["route_id", "direction"]].drop_duplicates().shape[0]
        ),
    }


def sort_statistics(frame: pd.DataFrame, group_column: str) -> pd.DataFrame:
    if group_column == "final_road_type":
        order = {value: index for index, value in enumerate(ROAD_TYPE_ORDER)}
        frame["_order"] = frame[group_column].map(order).fillna(len(order))
        frame = frame.sort_values(["_order", group_column]).drop(columns="_order")
    else:
        frame = frame.sort_values(group_column)
    return frame.reset_index(drop=True)


def main() -> None:
    args = parse_args()
    project_root = args.project_root.resolve()
    calibration_dir = (
        project_root
        / "data/transit/hongkong/processed/road_speed_capacity_2026_v1"
    )
    default_v2 = (
        project_root
        / "data/transit/hongkong/processed/"
        "road_class_lane_final_decisions_2026_v2_atc_flow_guard"
    )
    decision_dir = (
        args.decision_dir.resolve()
        if args.decision_dir
        else default_v2
    )
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else project_root
        / "data/transit/hongkong/processed/"
        "road_flow_statistics_corrected_2026_v2_atc_flow_guard"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    attributes = load_corrected_attributes(decision_dir)
    detector, detector_counts = build_detector_observations(
        calibration_dir, attributes
    )
    atc, atc_counts = build_atc_observations(calibration_dir, attributes)

    outputs: dict[str, pd.DataFrame] = {}
    for source_name, data, source_column in [
        ("detector_2026_07_22", detector, "detector_id"),
        ("atc_2024_peak_hour", atc, "atc_source_id"),
    ]:
        for group_column, group_name in [
            ("final_road_type", "road_type"),
            ("final_permlanes", "lane_count"),
        ]:
            statistics = grouped_flow_statistics(
                data,
                group_column,
                "observed_total_flow_vph",
                "observed_per_lane_flow_vphpl",
                source_column,
            )
            statistics = sort_statistics(statistics, group_column)
            name = f"{source_name}_flow_by_{group_name}.csv"
            statistics.to_csv(output_dir / name, index=False)
            outputs[name] = statistics

    detector[
        [
            "detector_id",
            "window_start",
            "observed_seconds",
            "route_id",
            "direction",
            "final_road_type",
            "final_permlanes",
            "modal_lanes",
            "final_lane_source",
            "observed_total_flow_vph",
            "observed_per_lane_flow_vphpl",
        ]
    ].to_csv(output_dir / "detector_observations_joined.csv", index=False)
    atc[
        [
            "station_no",
            "atc_direction",
            "route_id",
            "direction",
            "final_road_type",
            "final_permlanes",
            "street_ename",
            "previous_permlanes",
            "previous_lane_source",
            "final_lane_source",
            "lane_decision_reason",
            "weekday_am_peak_flow",
            "weekday_pm_peak_flow",
            "observed_total_flow_vph",
            "observed_per_lane_flow_vphpl",
        ]
    ].rename(
        columns={
            "direction": "matched_direction",
        }
    ).to_csv(output_dir / "atc_peak_observations_joined.csv", index=False)

    atc_conflicts = atc.loc[
        atc["observed_per_lane_flow_vphpl"].gt(2300.0),
        [
            "station_no",
            "atc_direction",
            "route_id",
            "direction",
            "street_ename",
            "final_road_type",
            "previous_permlanes",
            "previous_lane_source",
            "final_permlanes",
            "final_lane_source",
            "lane_decision_reason",
            "observed_total_flow_vph",
            "observed_per_lane_flow_vphpl",
        ],
    ].sort_values("observed_per_lane_flow_vphpl", ascending=False)
    atc_conflicts.to_csv(
        output_dir / "atc_corrected_lane_flow_conflicts_over_2300_vphpl.csv",
        index=False,
    )

    summary = {
        "detector_measure": (
            "2026-07-22 eligible 15-minute detector-window flow, expressed "
            "as directional veh/h using the observed modal lane count."
        ),
        "atc_measure": (
            "2024 detailed ATC station-direction maximum of published "
            "weekday AM and PM peak-hour flow, veh/h."
        ),
        "detector_counts": detector_counts,
        "atc_counts": atc_counts,
        "atc_corrected_lane_conflicts_over_2300_vphpl": int(len(atc_conflicts)),
        "group_statistics": {
            name: frame.to_dict(orient="records") for name, frame in outputs.items()
        },
        "notes": [
            "Detector and ATC distributions are reported separately.",
            "The 95th percentile is calculated across valid observations within each group.",
            "No AADT-derived synthetic peak flow is included.",
            "Road classes and lane counts come from the corrected final decisions.",
        ],
    }
    (output_dir / "corrected_road_flow_statistics_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
