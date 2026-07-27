#!/usr/bin/env python3
"""Resolve Hong Kong ATC-versus-OSM lane conflicts using observed flow."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from finalize_hong_kong_road_class_lane_decisions import (
    build_corrected_route_attributes,
    build_link_decisions,
    write_lane_corrected_network,
)


DEFAULT_PROJECT_ROOT = Path(r"F:\Matsim\matsim-example-project")
DEFAULT_MAX_FLOW_PER_LANE_VPH = 2300.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument("--input-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--max-flow-per-lane-vph",
        type=float,
        default=DEFAULT_MAX_FLOW_PER_LANE_VPH,
    )
    return parser.parse_args()


def json_default(value: Any) -> Any:
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    raise TypeError(f"Cannot serialize {type(value)}")


def resolve_conflicts(
    lanes: pd.DataFrame,
    max_flow_per_lane_vph: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    result = lanes.copy()
    result["permlanes"] = pd.to_numeric(
        result["permlanes"], errors="raise"
    ).astype(int)
    result["final_permlanes"] = pd.to_numeric(
        result["final_permlanes"], errors="raise"
    ).astype(int)
    result["atc_peak_flow_vph"] = pd.to_numeric(
        result["atc_peak_flow_vph"], errors="coerce"
    )

    conflict = (
        result["lane_source"].astype(str).str.startswith("atc_")
        & result["final_lane_source"].astype(str).str.startswith("osm_")
        & result["final_permlanes"].ne(result["permlanes"])
    )
    audit = result.loc[conflict].copy()
    if audit.empty:
        raise RuntimeError("No ATC-versus-OSM lane conflicts were found.")
    if audit["atc_peak_flow_vph"].isna().any():
        missing = audit.loc[
            audit["atc_peak_flow_vph"].isna(),
            ["route_id", "direction", "lane_source", "final_lane_source"],
        ]
        raise RuntimeError(
            "ATC-versus-OSM conflicts lack flow evidence:\n"
            f"{missing.head()}"
        )

    audit["atc_candidate_lanes"] = audit["permlanes"].astype(int)
    audit["osm_candidate_lanes"] = audit["final_permlanes"].astype(int)
    audit["atc_candidate_vphpl"] = (
        audit["atc_peak_flow_vph"] / audit["atc_candidate_lanes"]
    )
    audit["osm_candidate_vphpl"] = (
        audit["atc_peak_flow_vph"] / audit["osm_candidate_lanes"]
    )
    audit["osm_flow_feasible"] = audit["osm_candidate_vphpl"].le(
        max_flow_per_lane_vph
    )
    audit["atc_flow_feasible"] = audit["atc_candidate_vphpl"].le(
        max_flow_per_lane_vph
    )
    audit["selected_lane_basis"] = np.where(
        audit["osm_flow_feasible"],
        "osm_record_flow_feasible",
        "atc_lane_restored_osm_exceeds_flow_ceiling",
    )
    audit["selected_lanes"] = np.where(
        audit["osm_flow_feasible"],
        audit["osm_candidate_lanes"],
        audit["atc_candidate_lanes"],
    ).astype(int)
    audit["selected_vphpl"] = (
        audit["atc_peak_flow_vph"] / audit["selected_lanes"]
    )
    audit["max_flow_per_lane_vph"] = max_flow_per_lane_vph

    if (~audit["atc_flow_feasible"] & ~audit["osm_flow_feasible"]).any():
        impossible = audit.loc[
            ~audit["atc_flow_feasible"] & ~audit["osm_flow_feasible"],
            [
                "route_id",
                "direction",
                "atc_candidate_lanes",
                "osm_candidate_lanes",
                "atc_candidate_vphpl",
                "osm_candidate_vphpl",
            ],
        ]
        raise RuntimeError(
            "Neither ATC nor OSM lane candidate can carry observed flow:\n"
            f"{impossible.head()}"
        )

    restore = audit.loc[~audit["osm_flow_feasible"]]
    restore_index = restore.index
    result.loc[restore_index, "final_permlanes"] = result.loc[
        restore_index, "permlanes"
    ]
    result.loc[
        restore_index, "final_lane_source"
    ] = "atc_direction_peak_flow_guard"
    result.loc[
        restore_index, "final_lane_confidence"
    ] = "official_flow_guard"
    result.loc[
        restore_index, "lane_decision_reason"
    ] = "osm_lane_rejected_atc_peak_exceeds_2300_vphpl"

    result["lane_changed"] = result["final_permlanes"].ne(
        result["permlanes"]
    )
    result["lane_change"] = (
        result["final_permlanes"] - result["permlanes"]
    )
    result["lane_decision_status"] = np.where(
        result["lane_changed"], "final_change", "final_preserve"
    )
    if not result["final_permlanes"].between(1, 8).all():
        raise RuntimeError("Resolved lane counts fall outside 1-8 lanes.")
    audit = audit.sort_values(
        ["osm_flow_feasible", "osm_candidate_vphpl"],
        ascending=[True, False],
    )
    return result, audit


def main() -> None:
    args = parse_args()
    project_root = args.project_root.resolve()
    transit_root = project_root / "data/transit/hongkong"
    calibration_dir = (
        transit_root / "processed/road_speed_capacity_2026_v1"
    )
    supply_dir = (
        transit_root
        / "processed/matsim_road_pt_supply_2026_typical_weekday"
    )
    input_dir = (
        args.input_dir.resolve()
        if args.input_dir
        else transit_root
        / "processed/road_class_lane_final_decisions_2026_v1"
    )
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else transit_root
        / "processed/road_class_lane_final_decisions_2026_v2_atc_flow_guard"
    )
    required = [
        input_dir / "road_type_final_decisions.csv",
        input_dir / "lane_count_final_decisions.csv",
        calibration_dir / "road_route_direction_attributes.csv",
        calibration_dir / "matsim_link_attributes.csv",
        supply_dir / "network.xml.gz",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit(f"Missing required inputs: {missing}")
    output_dir.mkdir(parents=True, exist_ok=True)

    roads = pd.read_csv(
        input_dir / "road_type_final_decisions.csv", low_memory=False
    )
    lanes_v1 = pd.read_csv(
        input_dir / "lane_count_final_decisions.csv", low_memory=False
    )
    current = pd.read_csv(
        calibration_dir / "road_route_direction_attributes.csv",
        low_memory=False,
    )
    lanes, audit = resolve_conflicts(
        lanes_v1, args.max_flow_per_lane_vph
    )
    corrected = build_corrected_route_attributes(current, roads, lanes)
    links = build_link_decisions(calibration_dir, lanes)

    roads.to_csv(output_dir / "road_type_final_decisions.csv", index=False)
    lanes.to_csv(output_dir / "lane_count_final_decisions.csv", index=False)
    corrected.to_csv(
        output_dir / "road_route_direction_attributes_corrected.csv",
        index=False,
    )
    links.to_csv(
        output_dir / "matsim_link_class_lane_decisions.csv", index=False
    )
    audit.to_csv(
        output_dir / "atc_osm_lane_conflict_decisions.csv", index=False
    )
    restored = audit.loc[~audit["osm_flow_feasible"]].copy()
    restored.to_csv(
        output_dir / "atc_lane_restorations_due_to_flow.csv", index=False
    )

    candidate_network = (
        output_dir
        / "network_class_lane_corrected_capacity_unchanged.xml.gz"
    )
    network = write_lane_corrected_network(
        supply_dir / "network.xml.gz",
        candidate_network,
        links,
    )
    selected_vphpl = audit["selected_vphpl"]
    summary = {
        "purpose": (
            "Resolve every ATC-versus-OSM lane-count conflict without manual "
            "review, using direct ATC peak flow as a physical feasibility guard."
        ),
        "flow_ceiling_vphpl": args.max_flow_per_lane_vph,
        "decision_rule": (
            "Keep the OSM lane record when ATC peak flow divided by OSM lanes "
            "is <= the ceiling; otherwise restore the ATC lane candidate."
        ),
        "counts": {
            "atc_osm_conflicts": int(len(audit)),
            "direct_atc_conflicts": int(
                audit["lane_source"].astype(str).str.startswith(
                    "atc_direction_peak"
                ).sum()
            ),
            "aadt_inferred_conflicts": int(
                audit["lane_source"].astype(str).str.startswith(
                    "atc_aadt_inferred"
                ).sum()
            ),
            "osm_retained": int(audit["osm_flow_feasible"].sum()),
            "atc_restored": int((~audit["osm_flow_feasible"]).sum()),
            "final_lane_changes_from_original_supply": int(
                lanes["lane_changed"].sum()
            ),
            "matsim_road_link_lane_changes": int(
                links["link_lane_changed"].sum()
            ),
        },
        "flow_statistics_vphpl": {
            "osm_candidate_q95": float(
                audit["osm_candidate_vphpl"].quantile(0.95)
            ),
            "osm_candidate_max": float(
                audit["osm_candidate_vphpl"].max()
            ),
            "selected_q95": float(selected_vphpl.quantile(0.95)),
            "selected_max": float(selected_vphpl.max()),
        },
        "restored_routes": restored[
            [
                "route_id",
                "direction",
                "street_ename",
                "road_type",
                "atc_peak_flow_vph",
                "atc_candidate_lanes",
                "osm_candidate_lanes",
                "atc_candidate_vphpl",
                "osm_candidate_vphpl",
                "selected_lanes",
            ]
        ].to_dict(orient="records"),
        "network": network,
        "invariants": {
            "all_conflicts_decided": bool(
                audit["selected_lane_basis"].notna().all()
            ),
            "all_selected_flows_within_ceiling": bool(
                audit["selected_vphpl"]
                .le(args.max_flow_per_lane_vph)
                .all()
            ),
            "capacities_unchanged": bool(
                links["final_capacity_vph"].eq(
                    links["new_capacity_vph"]
                ).all()
            ),
            "road_classes_unchanged_from_v1": True,
        },
        "outputs": {
            "lane_decisions": "lane_count_final_decisions.csv",
            "route_attributes": "road_route_direction_attributes_corrected.csv",
            "link_decisions": "matsim_link_class_lane_decisions.csv",
            "conflict_audit": "atc_osm_lane_conflict_decisions.csv",
            "restored_atc": "atc_lane_restorations_due_to_flow.csv",
            "candidate_network": candidate_network.name,
        },
    }
    if not all(summary["invariants"].values()):
        raise RuntimeError(
            f"ATC/OSM resolution invariants failed: {summary['invariants']}"
        )
    with (output_dir / "atc_osm_lane_resolution_summary.json").open(
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
