#!/usr/bin/env python3
"""Finalize Hong Kong road classes and lanes using a fixed evidence hierarchy.

Road capacity is intentionally unchanged. The script writes final decision
tables and a candidate MATSim network with corrected ``permlanes`` only; it
never replaces the formal network.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import re
from pathlib import Path
from typing import Any

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


DEFAULT_PROJECT_ROOT = Path(r"F:\Matsim\matsim-example-project")
PROTECTED_ROAD_SOURCES = {"atc_direct", "st_code_corridor"}
OSM_LANE_PRIORITY = {
    "directional_tags_available": 1,
    "oneway_explicit_or_implicit": 2,
    "even_total_split": 3,
}
CLASS_COLORS = {
    "EX": "#d1495b",
    "UT": "#f28e2b",
    "PD": "#edc948",
    "DD": "#59a14f",
    "LD": "#4e79a7",
    "RT": "#9c755f",
    "RR": "#79706e",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument("--enrichment-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--skip-network", action="store_true")
    parser.add_argument("--skip-plots", action="store_true")
    return parser.parse_args()


def replace_attribute(line: str, attribute: str, value: float) -> str:
    pattern = rf'({attribute}=")[^"]*(")'
    return re.sub(pattern, rf"\g<1>{value:.6f}\g<2>", line, count=1)


def extract_attribute(line: str, attribute: str) -> str:
    match = re.search(rf'{attribute}="([^"]+)"', line)
    return match.group(1) if match else ""


def finalize_road_types(candidates: pd.DataFrame) -> pd.DataFrame:
    result = candidates.copy()
    result["final_road_type"] = result["road_type"]
    result["final_road_type_source"] = result["road_type_source"]
    result["final_road_type_confidence"] = "low"
    result["road_type_decision_reason"] = "existing_fallback_retained"

    atc = result["road_type_source"].eq("atc_direct")
    corridor = result["road_type_source"].eq("st_code_corridor")
    result.loc[atc, "final_road_type_confidence"] = "official_direct"
    result.loc[atc, "road_type_decision_reason"] = "atc_direct_priority_1"
    result.loc[corridor, "final_road_type_confidence"] = "official_propagated"
    result.loc[
        corridor, "road_type_decision_reason"
    ] = "unanimous_st_code_atc_corridor_priority_2"

    osm_model = result["candidate_road_type_source"].eq(
        "osm_atc_probability_model"
    )
    osm_parent = result["candidate_road_type_source"].eq(
        "osm_link_inherited_from_st_code_parent"
    )
    result.loc[osm_model, "final_road_type"] = result.loc[
        osm_model, "candidate_road_type"
    ]
    result.loc[
        osm_model, "final_road_type_source"
    ] = "osm_atc_probability_model"
    result.loc[osm_model, "final_road_type_confidence"] = "high_secondary"
    result.loc[
        osm_model, "road_type_decision_reason"
    ] = "high_confidence_osm_model_priority_3"

    result.loc[osm_parent, "final_road_type"] = result.loc[
        osm_parent, "candidate_road_type"
    ]
    result.loc[
        osm_parent, "final_road_type_source"
    ] = "osm_link_inherited_from_st_code_parent"
    result.loc[osm_parent, "final_road_type_confidence"] = "medium_secondary"
    result.loc[
        osm_parent, "road_type_decision_reason"
    ] = "osm_link_parent_inheritance_priority_3"

    # Protected official classes always win, even if a future candidate table
    # accidentally carries a different candidate value.
    protected = result["road_type_source"].isin(PROTECTED_ROAD_SOURCES)
    result.loc[protected, "final_road_type"] = result.loc[
        protected, "road_type"
    ]
    result.loc[protected, "final_road_type_source"] = result.loc[
        protected, "road_type_source"
    ]
    result["road_type_changed"] = result["final_road_type"].ne(
        result["road_type"]
    )
    result["road_type_decision_status"] = np.where(
        result["road_type_changed"], "final_change", "final_preserve"
    )
    return result


def finalize_lanes(candidates: pd.DataFrame) -> pd.DataFrame:
    result = candidates.copy()
    result["final_permlanes"] = result["permlanes"].astype(int)
    result["final_lane_source"] = result["lane_source"]
    result["final_lane_confidence"] = "existing_estimate"
    result["lane_decision_reason"] = "no_usable_osm_lane_keep_existing"

    detector = result["lane_source"].str.startswith(
        "detector_modal", na=False
    )
    result.loc[detector, "final_lane_confidence"] = "official_detector"
    result.loc[
        detector, "lane_decision_reason"
    ] = "stable_detector_modal_priority_1"

    usable_osm = (
        ~detector
        & result["spatial_match"].fillna(False)
        & result["osm_directional_lanes"].notna()
        & result["osm_lane_consensus"].ge(2.0 / 3.0)
        & result["osm_lane_basis"].isin(OSM_LANE_PRIORITY)
    )
    result.loc[usable_osm, "final_permlanes"] = (
        result.loc[usable_osm, "osm_directional_lanes"].round().astype(int)
    )
    result.loc[usable_osm, "final_lane_source"] = result.loc[
        usable_osm, "osm_lane_basis"
    ].map(
        {
            "directional_tags_available": "osm_directional_lanes",
            "oneway_explicit_or_implicit": "osm_oneway_lanes",
            "even_total_split": "osm_even_total_split",
        }
    )
    result.loc[
        usable_osm
        & result["osm_lane_basis"].eq("directional_tags_available"),
        "final_lane_confidence",
    ] = "high_secondary"
    result.loc[
        usable_osm
        & result["osm_lane_basis"].eq("directional_tags_available"),
        "lane_decision_reason",
    ] = "osm_directional_tags_priority_2"
    result.loc[
        usable_osm
        & result["osm_lane_basis"].eq("oneway_explicit_or_implicit"),
        "final_lane_confidence",
    ] = "high_secondary"
    result.loc[
        usable_osm
        & result["osm_lane_basis"].eq("oneway_explicit_or_implicit"),
        "lane_decision_reason",
    ] = "osm_oneway_lanes_priority_3"
    result.loc[
        usable_osm
        & result["osm_lane_basis"].eq("even_total_split"),
        "final_lane_confidence",
    ] = "medium_secondary"
    result.loc[
        usable_osm
        & result["osm_lane_basis"].eq("even_total_split"),
        "lane_decision_reason",
    ] = "osm_even_two_way_split_priority_4"

    if not result["final_permlanes"].between(1, 8).all():
        invalid = result.loc[
            ~result["final_permlanes"].between(1, 8),
            ["route_id", "direction", "final_permlanes"],
        ]
        raise RuntimeError(f"Invalid final lane decisions:\n{invalid.head()}")
    result["lane_changed"] = result["final_permlanes"].ne(
        result["permlanes"]
    )
    result["lane_decision_status"] = np.where(
        result["lane_changed"], "final_change", "final_preserve"
    )
    return result


def build_corrected_route_attributes(
    current: pd.DataFrame,
    road_decisions: pd.DataFrame,
    lane_decisions: pd.DataFrame,
) -> pd.DataFrame:
    road_columns = [
        "route_id",
        "final_road_type",
        "final_road_type_source",
        "final_road_type_confidence",
        "road_type_decision_reason",
    ]
    lane_columns = [
        "route_id",
        "direction",
        "final_permlanes",
        "final_lane_source",
        "final_lane_confidence",
        "lane_decision_reason",
    ]
    result = (
        current.merge(
            road_decisions[road_columns], on="route_id", how="left"
        )
        .merge(
            lane_decisions[lane_columns],
            on=["route_id", "direction"],
            how="left",
        )
    )
    result = result.rename(
        columns={
            "road_type": "previous_road_type",
            "road_type_source": "previous_road_type_source",
            "permlanes": "previous_permlanes",
            "lane_source": "previous_lane_source",
        }
    )
    result["road_type"] = result["final_road_type"]
    result["road_type_source"] = result["final_road_type_source"]
    result["permlanes"] = result["final_permlanes"].astype(int)
    result["lane_source"] = result["final_lane_source"]
    result["capacity_unchanged"] = True
    return result


def build_link_decisions(
    calibration_dir: Path,
    lane_decisions: pd.DataFrame,
) -> pd.DataFrame:
    links = pd.read_csv(calibration_dir / "matsim_link_attributes.csv")
    keep = [
        "route_id",
        "direction",
        "permlanes",
        "final_permlanes",
        "final_lane_source",
        "final_lane_confidence",
        "lane_decision_reason",
    ]
    result = links.merge(
        lane_decisions[keep],
        on=["route_id", "direction"],
        how="left",
    )
    result["link_lane_changed"] = result["final_permlanes"].ne(
        result["new_permlanes"]
    )
    result["final_capacity_vph"] = result["new_capacity_vph"]
    result["capacity_unchanged"] = True
    return result


def write_lane_corrected_network(
    source: Path,
    destination: Path,
    link_decisions: pd.DataFrame,
) -> dict[str, Any]:
    lookup = (
        link_decisions.set_index("link_id")["final_permlanes"].astype(float).to_dict()
    )
    expected_capacity = (
        link_decisions.set_index("link_id")["new_capacity_vph"].astype(float).to_dict()
    )
    seen: set[str] = set()
    total_links = road_links = changed_links = 0
    capacity_mismatches: list[dict[str, Any]] = []
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
            if link_id not in lookup:
                writer.write(line)
                continue
            road_links += 1
            seen.add(link_id)
            old_lanes = safe_float(extract_attribute(line, "permlanes"))
            capacity = safe_float(extract_attribute(line, "capacity"))
            target_lanes = lookup[link_id]
            if not math.isclose(
                capacity,
                expected_capacity[link_id],
                rel_tol=0.0,
                abs_tol=1e-5,
            ):
                capacity_mismatches.append(
                    {
                        "link_id": link_id,
                        "network_capacity": capacity,
                        "expected_capacity": expected_capacity[link_id],
                    }
                )
            if not math.isclose(old_lanes, target_lanes, abs_tol=1e-9):
                line = replace_attribute(line, "permlanes", target_lanes)
                changed_links += 1
            writer.write(line)
    missing = sorted(set(lookup) - seen)
    if missing:
        raise RuntimeError(f"{len(missing)} road links were not found in network")
    if capacity_mismatches:
        raise RuntimeError(
            "Formal network capacities differ from calibration link table: "
            f"{capacity_mismatches[:5]}"
        )
    return {
        "source_network": str(source),
        "candidate_network": str(destination),
        "total_links": total_links,
        "road_links": road_links,
        "changed_road_links": changed_links,
        "capacity_mismatches": 0,
    }


def safe_float(value: Any, default: float = math.nan) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def write_plots(
    road_gdb: Path,
    roads: pd.DataFrame,
    lanes: pd.DataFrame,
    output_dir: Path,
) -> None:
    geometry = gpd.read_file(road_gdb, layer="CENTERLINE").to_crs("EPSG:2326")
    geometry["route_id"] = pd.to_numeric(geometry["ROUTE_ID"]).astype(int)
    geometry = geometry.drop_duplicates("route_id")
    road_changes = geometry[["route_id", "geometry"]].merge(
        roads.loc[
            roads["road_type_changed"],
            ["route_id", "final_road_type"],
        ],
        on="route_id",
        how="inner",
    )
    lane_change_by_route = (
        lanes.loc[lanes["lane_changed"]]
        .groupby("route_id", as_index=False)
        .agg(
            final_lane_change=(
                "final_permlanes",
                lambda values: int(values.max()),
            ),
            previous_lanes=("permlanes", "max"),
        )
    )
    lane_change_by_route["lane_delta"] = (
        lane_change_by_route["final_lane_change"]
        - lane_change_by_route["previous_lanes"]
    )
    lane_changes = geometry[["route_id", "geometry"]].merge(
        lane_change_by_route, on="route_id", how="inner"
    )
    fig, axes = plt.subplots(1, 2, figsize=(15, 7))
    geometry.plot(ax=axes[0], color="#dddddd", linewidth=0.15)
    for road_type, color in CLASS_COLORS.items():
        subset = road_changes.loc[
            road_changes["final_road_type"].eq(road_type)
        ]
        if not subset.empty:
            subset.plot(
                ax=axes[0],
                color=color,
                linewidth=0.8,
                label=road_type,
            )
    axes[0].set_title("Final road-class changes")
    axes[0].legend()
    axes[0].set_axis_off()
    geometry.plot(ax=axes[1], color="#dddddd", linewidth=0.15)
    if not lane_changes.empty:
        lane_changes.plot(
            ax=axes[1],
            column="lane_delta",
            cmap="coolwarm",
            vmin=-5,
            vmax=5,
            linewidth=0.8,
            legend=True,
        )
    axes[1].set_title("Final directional-lane changes")
    axes[1].set_axis_off()
    fig.tight_layout()
    fig.savefig(output_dir / "final_road_class_lane_decision_maps.png", dpi=180)
    plt.close(fig)


def json_default(value: Any) -> Any:
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    raise TypeError(f"Cannot serialize {type(value)}")


def main() -> None:
    args = parse_args()
    project_root = args.project_root.resolve()
    transit_root = project_root / "data" / "transit" / "hongkong"
    calibration_dir = (
        transit_root / "processed" / "road_speed_capacity_2026_v1"
    )
    enrichment_dir = (
        args.enrichment_dir.resolve()
        if args.enrichment_dir
        else transit_root
        / "processed"
        / "road_osm_class_lane_enrichment_2026_v1"
    )
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else transit_root
        / "processed"
        / "road_class_lane_final_decisions_2026_v1"
    )
    supply_dir = (
        transit_root
        / "processed"
        / "matsim_road_pt_supply_2026_typical_weekday"
    )
    source_network = supply_dir / "network.xml.gz"
    road_gdb = transit_root / "RdNet_IRNP.gdb"
    required = [
        enrichment_dir / "road_type_candidates.csv",
        enrichment_dir / "lane_count_candidates.csv",
        calibration_dir / "road_route_direction_attributes.csv",
        calibration_dir / "matsim_link_attributes.csv",
        source_network,
        road_gdb,
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit(f"Missing required inputs: {missing}")
    output_dir.mkdir(parents=True, exist_ok=True)

    road_candidates = pd.read_csv(
        enrichment_dir / "road_type_candidates.csv", low_memory=False
    )
    lane_candidates = pd.read_csv(
        enrichment_dir / "lane_count_candidates.csv", low_memory=False
    )
    current_attributes = pd.read_csv(
        calibration_dir / "road_route_direction_attributes.csv"
    )
    roads = finalize_road_types(road_candidates)
    lanes = finalize_lanes(lane_candidates)
    corrected = build_corrected_route_attributes(
        current_attributes, roads, lanes
    )
    links = build_link_decisions(calibration_dir, lanes)

    roads.to_csv(output_dir / "road_type_final_decisions.csv", index=False)
    lanes.to_csv(output_dir / "lane_count_final_decisions.csv", index=False)
    corrected.to_csv(
        output_dir / "road_route_direction_attributes_corrected.csv",
        index=False,
    )
    links.to_csv(output_dir / "matsim_link_class_lane_decisions.csv", index=False)

    network_summary: dict[str, Any] = {"skipped": True}
    candidate_network = (
        output_dir / "network_class_lane_corrected_capacity_unchanged.xml.gz"
    )
    if not args.skip_network:
        network_summary = write_lane_corrected_network(
            source_network, candidate_network, links
        )
    if not args.skip_plots:
        write_plots(road_gdb, roads, lanes, output_dir)

    protected = roads["road_type_source"].isin(PROTECTED_ROAD_SOURCES)
    detector = lanes["lane_source"].str.startswith("detector_modal", na=False)
    usable_osm = (
        ~detector
        & lanes["spatial_match"].fillna(False)
        & lanes["osm_directional_lanes"].notna()
        & lanes["osm_lane_consensus"].ge(2.0 / 3.0)
        & lanes["osm_lane_basis"].isin(OSM_LANE_PRIORITY)
    )
    summary = {
        "purpose": "Final class/lane decisions; road capacity remains unchanged.",
        "road_type_hierarchy": [
            "atc_direct",
            "unanimous_st_code_atc_corridor",
            "high_confidence_osm_atc_probability_model",
            "existing_speed_route_default_fallback",
        ],
        "lane_hierarchy": [
            "stable_detector_modal",
            "osm_lanes_forward_backward",
            "osm_oneway_lanes",
            "osm_even_two_way_total_split",
            "existing_atc_aadt_corridor_default",
        ],
        "counts": {
            "routes": len(roads),
            "route_directions": len(lanes),
            "final_road_type_changes": int(roads["road_type_changed"].sum()),
            "final_lane_changes": int(lanes["lane_changed"].sum()),
            "official_or_corridor_road_types_preserved": int(protected.sum()),
            "detector_lanes_preserved": int(detector.sum()),
            "osm_lane_decisions": int(usable_osm.sum()),
            "matsim_road_link_lane_changes": int(
                links["link_lane_changed"].sum()
            ),
        },
        "road_type_change_matrix": pd.crosstab(
            roads.loc[roads["road_type_changed"], "road_type"],
            roads.loc[roads["road_type_changed"], "final_road_type"],
        ).to_dict(),
        "road_type_final_source": roads[
            "final_road_type_source"
        ].value_counts().to_dict(),
        "lane_final_source": lanes["final_lane_source"].value_counts().to_dict(),
        "lane_change_distribution": lanes.loc[
            lanes["lane_changed"], "final_permlanes"
        ]
        .sub(lanes.loc[lanes["lane_changed"], "permlanes"])
        .value_counts()
        .sort_index()
        .to_dict(),
        "network": network_summary,
        "invariants": {
            "protected_road_types_unchanged": bool(
                roads.loc[protected, "final_road_type"]
                .eq(roads.loc[protected, "road_type"])
                .all()
            ),
            "detector_lanes_unchanged": bool(
                lanes.loc[detector, "final_permlanes"]
                .eq(lanes.loc[detector, "permlanes"])
                .all()
            ),
            "usable_osm_lanes_applied": bool(
                lanes.loc[usable_osm, "final_permlanes"]
                .eq(
                    lanes.loc[usable_osm, "osm_directional_lanes"]
                    .round()
                    .astype(int)
                )
                .all()
            ),
            "capacities_unchanged": bool(
                links["final_capacity_vph"]
                .eq(links["new_capacity_vph"])
                .all()
            ),
        },
        "outputs": {
            "road_types": "road_type_final_decisions.csv",
            "lanes": "lane_count_final_decisions.csv",
            "corrected_route_attributes": "road_route_direction_attributes_corrected.csv",
            "matsim_links": "matsim_link_class_lane_decisions.csv",
            "candidate_network": candidate_network.name
            if not args.skip_network
            else None,
            "map": "final_road_class_lane_decision_maps.png"
            if not args.skip_plots
            else None,
        },
    }
    if not all(summary["invariants"].values()):
        raise RuntimeError(f"Final decision invariants failed: {summary['invariants']}")
    with (output_dir / "final_decision_summary.json").open(
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
