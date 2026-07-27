#!/usr/bin/env python3
"""Build a TPDM, observed-flow, and corrected-lane hybrid road capacity."""

from __future__ import annotations

import argparse
import gzip
import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from build_hong_kong_tpdm_capacity_mapping import (
    build_detailed_atc_bounds,
    build_detector_flow_bounds,
    infer_cross_section,
    infer_tpdm_family,
    tpdm_directional_capacity,
)


DEFAULT_PROJECT_ROOT = Path(r"F:\Matsim\matsim-example-project")
ROAD_TYPE_ORDER = ["EX", "UT", "PD", "DD", "LD", "RT", "RR"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument("--decision-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--observed-vc-target",
        type=float,
        default=0.95,
        help="Maximum intended v/c for observation-derived capacity floors.",
    )
    parser.add_argument(
        "--capacity-rounding-vph",
        type=float,
        default=50.0,
    )
    return parser.parse_args()


def finite_max(*values: Any) -> float:
    valid = [
        float(value)
        for value in values
        if pd.notna(value) and math.isfinite(float(value))
    ]
    return max(valid) if valid else math.nan


def extract_attribute(line: str, attribute: str) -> str:
    match = re.search(rf'{attribute}="([^"]+)"', line)
    return match.group(1) if match else ""


def replace_attribute(line: str, attribute: str, value: float) -> str:
    return re.sub(
        rf'({attribute}=")[^"]*(")',
        rf"\g<1>{value:.6f}\g<2>",
        line,
        count=1,
    )


def safe_float(value: Any, default: float = math.nan) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def json_default(value: Any) -> Any:
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    raise TypeError(f"Cannot serialize {type(value)}")


def build_class_empirical_anchors(
    routes: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for road_type in ROAD_TYPE_ORDER:
        frame = routes.loc[routes["final_road_type"].eq(road_type)]
        atc = (
            frame["detailed_atc_peak_vph"] / frame["final_permlanes"]
        ).dropna()
        detector = (
            frame["detector_15min_flow_q95_vph"]
            / frame["final_permlanes"]
        ).dropna()
        atc_p95 = float(atc.quantile(0.95)) if len(atc) else math.nan
        detector_p95 = (
            float(detector.quantile(0.95)) if len(detector) else math.nan
        )
        anchor = finite_max(atc_p95, detector_p95)
        rows.append(
            {
                "final_road_type": road_type,
                "atc_route_directions": int(len(atc)),
                "atc_peak_vphpl_p95": atc_p95,
                "detector_route_directions": int(len(detector)),
                "detector_15min_q95_vphpl_p95": detector_p95,
                "empirical_vphpl_anchor": anchor,
                "anchor_basis": (
                    "max_atc_peak_and_detector_15min_q95_p95"
                    if math.isfinite(atc_p95)
                    and math.isfinite(detector_p95)
                    else "single_available_observed_source"
                ),
            }
        )
    anchors = pd.DataFrame(rows)
    if anchors["empirical_vphpl_anchor"].isna().any():
        raise RuntimeError("One or more road types lack an empirical anchor.")
    return anchors


def add_tpdm_mapping(routes: pd.DataFrame) -> pd.DataFrame:
    result = routes.copy()
    families = result["final_road_type"].map(infer_tpdm_family)
    result["tpdm_road_family"] = families.map(lambda value: value[0])
    result["tpdm_family_mapping_basis"] = families.map(lambda value: value[1])
    cross_sections = [
        infer_cross_section(
            int(row.travel_direction), int(row.final_permlanes)
        )
        for row in result.itertuples()
    ]
    result["tpdm_carriageway"] = [
        value[0] for value in cross_sections
    ]
    result["cross_section_inference"] = [
        value[1] for value in cross_sections
    ]
    capacities = pd.DataFrame(
        [
            tpdm_directional_capacity(
                row.tpdm_road_family,
                row.tpdm_carriageway,
                int(row.final_permlanes),
            )
            for row in result.itertuples()
        ]
    )
    return pd.concat(
        [result.reset_index(drop=True), capacities.reset_index(drop=True)],
        axis=1,
    )


def choose_hybrid_capacity(
    routes: pd.DataFrame,
    anchors: pd.DataFrame,
    observed_vc_target: float,
    rounding_vph: float,
) -> pd.DataFrame:
    result = routes.merge(
        anchors[
            ["final_road_type", "empirical_vphpl_anchor"]
        ],
        on="final_road_type",
        how="left",
        validate="many_to_one",
    )
    result["detector_flow_lower_bound_vph"] = result[
        "detector_flow_floor_vph"
    ]
    detector_fallback = (
        result["detector_flow_lower_bound_vph"].isna()
        & result["detector_15min_flow_q95_vph"].notna()
    )
    result.loc[
        detector_fallback, "detector_flow_lower_bound_vph"
    ] = result.loc[
        detector_fallback, "detector_15min_flow_q95_vph"
    ]
    result["detector_flow_lower_bound_basis"] = np.select(
        [
            result["detector_flow_floor_vph"].notna(),
            detector_fallback,
        ],
        [
            "coverage_qualified_rolling_peak_hour",
            "coverage_normalized_15min_q95_fallback",
        ],
        default="no_detector_flow",
    )
    result["direct_observed_flow_lower_bound_vph"] = [
        finite_max(detector, atc)
        for detector, atc in zip(
            result["detector_flow_lower_bound_vph"],
            result["detailed_atc_peak_vph"],
            strict=True,
        )
    ]
    result["class_lane_empirical_floor_vph"] = (
        result["final_permlanes"]
        * result["empirical_vphpl_anchor"]
    )
    result["class_lane_empirical_with_headroom_vph"] = (
        result["class_lane_empirical_floor_vph"]
        / observed_vc_target
    )
    result["direct_observed_with_headroom_vph"] = (
        result["direct_observed_flow_lower_bound_vph"]
        / observed_vc_target
    )
    components = result[
        [
            "tpdm_capacity_reference_vph",
            "class_lane_empirical_with_headroom_vph",
            "direct_observed_with_headroom_vph",
        ]
    ]
    result["hybrid_capacity_raw_vph"] = components.max(
        axis=1, skipna=True
    )
    if result["hybrid_capacity_raw_vph"].isna().any():
        raise RuntimeError("Hybrid capacity is missing for one or more routes.")
    result["hybrid_capacity_vph"] = (
        np.ceil(result["hybrid_capacity_raw_vph"] / rounding_vph)
        * rounding_vph
    )

    labels = {
        "tpdm_capacity_reference_vph": "tpdm_cross_section",
        "class_lane_empirical_with_headroom_vph": (
            "class_lane_observed_p95"
        ),
        "direct_observed_with_headroom_vph": (
            "direct_atc_or_detector_flow"
        ),
    }
    winners: list[str] = []
    for row in result.itertuples():
        raw = float(row.hybrid_capacity_raw_vph)
        values = {
            column: safe_float(getattr(row, column))
            for column in labels
        }
        winning = [
            labels[column]
            for column, value in values.items()
            if math.isfinite(value)
            and math.isclose(value, raw, rel_tol=0.0, abs_tol=1e-7)
        ]
        winners.append("+".join(winning))
    result["hybrid_capacity_controlling_source"] = winners
    result["hybrid_capacity_per_lane_vphpl"] = (
        result["hybrid_capacity_vph"] / result["final_permlanes"]
    )
    result["direct_observed_vc_at_hybrid"] = (
        result["direct_observed_flow_lower_bound_vph"]
        / result["hybrid_capacity_vph"]
    )
    return result


def build_link_table(
    calibration_dir: Path,
    routes: pd.DataFrame,
) -> pd.DataFrame:
    links = pd.read_csv(calibration_dir / "matsim_link_attributes.csv")
    keep = [
        "route_id",
        "direction",
        "final_road_type",
        "final_permlanes",
        "tpdm_capacity_reference_vph",
        "tpdm_match_status",
        "empirical_vphpl_anchor",
        "direct_observed_flow_lower_bound_vph",
        "detector_flow_lower_bound_basis",
        "hybrid_capacity_vph",
        "hybrid_capacity_per_lane_vphpl",
        "hybrid_capacity_controlling_source",
    ]
    result = links.merge(
        routes[keep],
        on=["route_id", "direction"],
        how="left",
        validate="many_to_one",
    )
    if result[
        ["final_permlanes", "hybrid_capacity_vph"]
    ].isna().any().any():
        raise RuntimeError("One or more MATSim road links lack hybrid values.")
    result["lane_changed_from_formal"] = result["final_permlanes"].ne(
        result["new_permlanes"]
    )
    result["capacity_changed_from_formal"] = result[
        "hybrid_capacity_vph"
    ].ne(result["new_capacity_vph"])
    return result


def write_candidate_network(
    source: Path,
    destination: Path,
    links: pd.DataFrame,
) -> dict[str, Any]:
    lane_lookup = (
        links.set_index("link_id")["final_permlanes"].astype(float).to_dict()
    )
    capacity_lookup = (
        links.set_index("link_id")["hybrid_capacity_vph"]
        .astype(float)
        .to_dict()
    )
    seen: set[str] = set()
    total_links = road_links = lane_changes = capacity_changes = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(source, "rt", encoding="utf-8") as reader, gzip.open(
        destination, "wt", encoding="utf-8", newline="\n"
    ) as writer:
        for line in reader:
            if "<link " not in line:
                writer.write(line)
                continue
            total_links += 1
            link_id = extract_attribute(line, "id")
            if link_id not in lane_lookup:
                writer.write(line)
                continue
            road_links += 1
            seen.add(link_id)
            old_lanes = safe_float(extract_attribute(line, "permlanes"))
            old_capacity = safe_float(extract_attribute(line, "capacity"))
            new_lanes = lane_lookup[link_id]
            new_capacity = capacity_lookup[link_id]
            if not math.isclose(old_lanes, new_lanes, abs_tol=1e-9):
                line = replace_attribute(line, "permlanes", new_lanes)
                lane_changes += 1
            if not math.isclose(old_capacity, new_capacity, abs_tol=1e-9):
                line = replace_attribute(line, "capacity", new_capacity)
                capacity_changes += 1
            writer.write(line)
    missing = sorted(set(lane_lookup) - seen)
    if missing:
        raise RuntimeError(
            f"{len(missing)} road links were not found in the source network."
        )
    return {
        "source_network": str(source),
        "candidate_network": str(destination),
        "total_links": total_links,
        "road_links": road_links,
        "lane_changes": lane_changes,
        "capacity_changes": capacity_changes,
    }


def summarize_by_road_type(routes: pd.DataFrame) -> pd.DataFrame:
    result = (
        routes.groupby("final_road_type", as_index=False)
        .agg(
            route_directions=("route_id", "size"),
            median_lanes=("final_permlanes", "median"),
            empirical_vphpl_anchor=("empirical_vphpl_anchor", "first"),
            tpdm_mapped=("tpdm_capacity_reference_vph", "count"),
            direct_observed=("direct_observed_flow_lower_bound_vph", "count"),
            old_capacity_median_vph=("capacity_vph", "median"),
            hybrid_capacity_p05_vph=(
                "hybrid_capacity_vph",
                lambda values: float(values.quantile(0.05)),
            ),
            hybrid_capacity_median_vph=("hybrid_capacity_vph", "median"),
            hybrid_capacity_p95_vph=(
                "hybrid_capacity_vph",
                lambda values: float(values.quantile(0.95)),
            ),
            hybrid_capacity_max_vph=("hybrid_capacity_vph", "max"),
        )
    )
    order = {value: index for index, value in enumerate(ROAD_TYPE_ORDER)}
    result["_order"] = result["final_road_type"].map(order)
    return result.sort_values("_order").drop(columns="_order")


def main() -> None:
    args = parse_args()
    if not 0 < args.observed_vc_target <= 1:
        raise SystemExit("--observed-vc-target must be in (0, 1].")
    if args.capacity_rounding_vph <= 0:
        raise SystemExit("--capacity-rounding-vph must be positive.")

    project_root = args.project_root.resolve()
    transit_root = project_root / "data/transit/hongkong"
    calibration_dir = (
        transit_root / "processed/road_speed_capacity_2026_v1"
    )
    decision_dir = (
        args.decision_dir.resolve()
        if args.decision_dir
        else transit_root
        / "processed/road_class_lane_final_decisions_2026_v2_atc_flow_guard"
    )
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else transit_root
        / "processed/road_capacity_hybrid_tpdm_flow_2026_v1"
    )
    supply_dir = (
        transit_root
        / "processed/matsim_road_pt_supply_2026_typical_weekday"
    )
    required = [
        decision_dir / "road_route_direction_attributes_corrected.csv",
        calibration_dir / "traffic_detector_15min_windows.csv",
        calibration_dir / "atc_directional_details_2024.csv",
        calibration_dir / "matsim_link_attributes.csv",
        supply_dir / "network.xml.gz",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit(f"Missing required inputs: {missing}")
    output_dir.mkdir(parents=True, exist_ok=True)

    routes = pd.read_csv(
        decision_dir / "road_route_direction_attributes_corrected.csv",
        low_memory=False,
    )
    detector = build_detector_flow_bounds(calibration_dir, 0.99)
    atc = build_detailed_atc_bounds(calibration_dir)
    routes = routes.merge(
        detector, on=["route_id", "direction"], how="left"
    ).merge(atc, on=["route_id", "direction"], how="left")
    routes = add_tpdm_mapping(routes)
    anchors = build_class_empirical_anchors(routes)
    routes = choose_hybrid_capacity(
        routes,
        anchors,
        args.observed_vc_target,
        args.capacity_rounding_vph,
    )
    links = build_link_table(calibration_dir, routes)
    by_type = summarize_by_road_type(routes)

    routes.to_csv(
        output_dir / "hybrid_capacity_route_directions.csv", index=False
    )
    links.to_csv(
        output_dir / "hybrid_capacity_matsim_links.csv", index=False
    )
    anchors.to_csv(
        output_dir / "class_empirical_flow_anchors.csv", index=False
    )
    by_type.to_csv(
        output_dir / "hybrid_capacity_by_road_type.csv", index=False
    )
    direct = routes.loc[
        routes["direct_observed_flow_lower_bound_vph"].notna(),
        [
            "route_id",
            "direction",
            "street_ename",
            "final_road_type",
            "final_permlanes",
            "detailed_atc_peak_vph",
            "detector_flow_lower_bound_vph",
            "detector_flow_lower_bound_basis",
            "direct_observed_flow_lower_bound_vph",
            "hybrid_capacity_vph",
            "direct_observed_vc_at_hybrid",
        ],
    ]
    direct.to_csv(
        output_dir / "direct_flow_lower_bound_validation.csv", index=False
    )

    candidate_network = output_dir / "network_hybrid_capacity.xml.gz"
    network = write_candidate_network(
        supply_dir / "network.xml.gz",
        candidate_network,
        links,
    )
    direct_vc = routes["direct_observed_vc_at_hybrid"].dropna()
    summary = {
        "method": (
            "max(TPDM cross-section reference, corrected lanes times class "
            "observed per-lane P95 / target v/c, direct ATC or detector flow "
            "lower bound / target v/c), rounded upward."
        ),
        "observed_vc_target": args.observed_vc_target,
        "capacity_rounding_vph": args.capacity_rounding_vph,
        "counts": {
            "route_directions": int(len(routes)),
            "matsim_road_links": int(len(links)),
            "tpdm_mapped_route_directions": int(
                routes["tpdm_capacity_reference_vph"].notna().sum()
            ),
            "direct_atc_route_directions": int(
                routes["detailed_atc_peak_vph"].notna().sum()
            ),
            "detector_route_directions": int(
                routes["detector_flow_lower_bound_vph"].notna().sum()
            ),
            "coverage_qualified_detector_peak_hours": int(
                routes["detector_flow_floor_vph"].notna().sum()
            ),
            "detector_15min_q95_fallbacks": int(
                routes["detector_flow_lower_bound_basis"]
                .eq("coverage_normalized_15min_q95_fallback")
                .sum()
            ),
        },
        "controlling_source": routes[
            "hybrid_capacity_controlling_source"
        ].value_counts().to_dict(),
        "capacity_distribution_vph": {
            "min": float(routes["hybrid_capacity_vph"].min()),
            "median": float(routes["hybrid_capacity_vph"].median()),
            "mean": float(routes["hybrid_capacity_vph"].mean()),
            "p95": float(routes["hybrid_capacity_vph"].quantile(0.95)),
            "max": float(routes["hybrid_capacity_vph"].max()),
        },
        "direct_observed_vc": {
            "count": int(len(direct_vc)),
            "max": float(direct_vc.max()),
            "p95": float(direct_vc.quantile(0.95)),
        },
        "network": network,
        "invariants": {
            "all_capacities_positive": bool(
                routes["hybrid_capacity_vph"].gt(0).all()
            ),
            "all_lanes_between_1_and_8": bool(
                routes["final_permlanes"].between(1, 8).all()
            ),
            "all_direct_observed_vc_at_or_below_target": bool(
                direct_vc.le(args.observed_vc_target + 1e-12).all()
            ),
            "no_capacity_pre_scaling": True,
        },
        "outputs": {
            "routes": "hybrid_capacity_route_directions.csv",
            "links": "hybrid_capacity_matsim_links.csv",
            "class_anchors": "class_empirical_flow_anchors.csv",
            "by_road_type": "hybrid_capacity_by_road_type.csv",
            "direct_validation": "direct_flow_lower_bound_validation.csv",
            "candidate_network": candidate_network.name,
        },
    }
    if not all(summary["invariants"].values()):
        raise RuntimeError(
            f"Hybrid capacity invariants failed: {summary['invariants']}"
        )
    with (output_dir / "hybrid_capacity_summary.json").open(
        "w", encoding="utf-8"
    ) as stream:
        json.dump(
            summary,
            stream,
            ensure_ascii=True,
            indent=2,
            default=json_default,
        )
    print(json.dumps(summary, indent=2, default=json_default))


if __name__ == "__main__":
    main()
