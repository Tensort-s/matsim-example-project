#!/usr/bin/env python3
"""Build unchanged physical network plus an explicit QSim storage registry."""

from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import shutil
from typing import Any

from build_hong_kong_road_continuity_candidate import (
    read_csv,
    read_network_links,
    select_relationships,
    sha256,
    write_csv,
)


ROAD_MODES = frozenset({"car", "bus", "gmb", "school_bus", "school_bus_vehicle"})
CANDIDATE2_VERSION = "hk_road_supply_v2_explicit_storage_candidate2"
CANDIDATE3_VERSION = "hk_road_supply_v3_all_road_lane_floor_candidate3"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-network", type=Path, required=True)
    parser.add_argument("--hotspot-links", type=Path, required=True)
    parser.add_argument("--hotspot-neighbors", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--storage-scope", choices=("continuity", "all-roads"),
        default="continuity",
        help="Override only continuity targets (Candidate2) or every physical road link (Candidate3).",
    )
    parser.add_argument("--expected-candidate-relationships", type=int, default=116)
    parser.add_argument("--expected-unique-links", type=int, default=114)
    parser.add_argument("--expected-road-links", type=int)
    parser.add_argument("--dominant-downstream-share", type=float, default=0.9)
    parser.add_argument("--short-length-m", type=float, default=10.0)
    parser.add_argument("--storage-factor", type=float, default=0.1)
    parser.add_argument("--flow-factor", type=float, default=0.1)
    parser.add_argument("--effective-cell-size-m", type=float, default=7.5)
    parser.add_argument("--qsim-time-step-s", type=float, default=1.0)
    parser.add_argument("--taxi-pcu", type=float, default=0.05)
    return parser.parse_args()


def truth(value: bool) -> str:
    return "true" if value else "false"


def modes(item: dict[str, str]) -> set[str]:
    return {value.strip() for value in item.get("modes", "").split(",") if value.strip()}


def requested_storage(
    item: dict[str, str], x: float, storage_factor: float,
    flow_factor: float, cell_size: float, time_step: float,
) -> dict[str, float]:
    length = float(item["length"])
    lanes = float(item["permlanes"])
    freespeed = float(item["freespeed"])
    flow_vph = float(item["capacity"])
    flow_per_second = flow_vph / 3600.0
    default_storage = length * lanes * storage_factor / cell_size
    buffer_safety = flow_per_second * time_step * flow_factor
    freeflow_safety = length / freespeed * flow_per_second * flow_factor
    safety = max(buffer_safety, freeflow_safety)
    final = max(float(x), default_storage, safety)
    return {
        "default_storage": default_storage,
        "buffer_safety": buffer_safety,
        "freeflow_safety": freeflow_safety,
        "safety": safety,
        "final": final,
    }


def build_rows(
    links: dict[str, dict[str, str]], relationships: list[dict[str, Any]],
    network_sha: str, storage_factor: float, flow_factor: float,
    cell_size: float, time_step: float, storage_scope: str = "continuity",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if storage_scope not in {"continuity", "all-roads"}:
        raise ValueError(f"Unsupported storage scope: {storage_scope}")
    parameter_version = (
        CANDIDATE3_VERSION if storage_scope == "all-roads" else CANDIDATE2_VERSION
    )
    by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for relation in relationships:
        by_target[relation["downstream_link"]].append(relation)

    registry: list[dict[str, Any]] = []
    storage_rows: list[dict[str, Any]] = []
    for link_id, item in sorted(links.items()):
        if not (modes(item) & ROAD_MODES):
            continue
        target = by_target.get(link_id, [])
        override = bool(target) or storage_scope == "all-roads"
        x = ""
        continuity_x = ""
        relationship_ids = ""
        storage: dict[str, float] | None = None
        if override:
            downstream_lanes = float(item["permlanes"])
            x = downstream_lanes
            if target:
                x = max(
                    downstream_lanes,
                    max(float(row["upstream_lanes"]) for row in target),
                )
                continuity_x = x
            if x <= 0 or not math.isfinite(x):
                raise ValueError(f"Invalid lane-floor x: {link_id}={x}")
            storage = requested_storage(
                item, x, storage_factor, flow_factor, cell_size, time_step
            )
            relationship_ids = "|".join(
                f"{row['upstream_link']}->{row['downstream_link']}" for row in target
            )
            storage_rows.append({
                "link_id": link_id,
                "storage_lane_floor_x_pcu": f"{x:.12g}",
                "continuity_lane_floor_x_pcu": (
                    f"{continuity_x:.12g}" if target else ""
                ),
                "physical_default_storage_qsim_pcu": f"{storage['default_storage']:.12f}",
                "buffer_safety_storage_qsim_pcu": f"{storage['buffer_safety']:.12f}",
                "freeflow_flow_safety_storage_qsim_pcu": f"{storage['freeflow_safety']:.12f}",
                "safety_storage_qsim_pcu": f"{storage['safety']:.12f}",
                "storage_capacity_qsim_pcu": f"{storage['final']:.12f}",
                "storage_capacity_formula": "max(x,physical_default,safety)",
                "continuity_relationship_ids": relationship_ids,
                "parameter_version": parameter_version,
                "source_network_sha256": network_sha,
            })
        registry.append({
            "link_id": link_id,
            "physical_length_m": item["length"],
            "physical_lanes": item["permlanes"],
            "freespeed_m_s": item["freespeed"],
            "flow_capacity_vph": item["capacity"],
            "flow_capacity_source": "tpdm_v4_three_candidate_network",
            "flow_capacity_override": "false",
            "storage_capacity_qsim_pcu": (
                f"{storage['final']:.12f}" if storage else ""
            ),
            "storage_capacity_source": (
                (
                    "all_road_lane_floor_x_with_physical_and_safety_guards"
                    if storage_scope == "all-roads"
                    else "continuity_lane_floor_x_with_physical_and_safety_guards"
                )
                if override else "matsim_default"
            ),
            "storage_capacity_override": truth(override),
            "continuity_candidate": truth(bool(target)),
            "storage_lane_floor_x_pcu": f"{x:.12g}" if override else "",
            "continuity_lane_floor_x_pcu": (
                f"{continuity_x:.12g}" if target else ""
            ),
            "continuity_relationship_ids": relationship_ids,
            "parameter_version": parameter_version,
            "source_network_sha256": network_sha,
        })
    return registry, storage_rows


def main() -> int:
    args = parse_args()
    for path in (args.input_network, args.hotspot_links, args.hotspot_neighbors):
        if not path.is_file():
            raise FileNotFoundError(path)
    if args.output_dir.exists():
        raise FileExistsError(f"Output directory must be new: {args.output_dir}")
    if min(args.storage_factor, args.flow_factor, args.effective_cell_size_m,
           args.qsim_time_step_s, args.taxi_pcu) <= 0:
        raise ValueError("QSim basis values must be positive")

    relationships = select_relationships(
        read_csv(args.hotspot_links), read_csv(args.hotspot_neighbors),
        args.dominant_downstream_share, args.short_length_m,
    )
    if len(relationships) != args.expected_candidate_relationships:
        raise RuntimeError(
            f"Candidate relationship count changed: expected {args.expected_candidate_relationships}, "
            f"got {len(relationships)}"
        )
    links = read_network_links(args.input_network)
    network_sha = sha256(args.input_network)
    registry, storage_rows = build_rows(
        links, relationships, network_sha, args.storage_factor, args.flow_factor,
        args.effective_cell_size_m, args.qsim_time_step_s, args.storage_scope,
    )
    expected_override_links = (
        len(registry) if args.storage_scope == "all-roads" else args.expected_unique_links
    )
    if len(storage_rows) != expected_override_links:
        raise RuntimeError(
            f"Storage-link count changed: expected {expected_override_links}, "
            f"got {len(storage_rows)}"
        )
    if args.expected_road_links is not None and len(registry) != args.expected_road_links:
        raise RuntimeError(
            f"Physical road-link count changed: expected {args.expected_road_links}, "
            f"got {len(registry)}"
        )

    args.output_dir.mkdir(parents=True)
    candidate_number = 3 if args.storage_scope == "all-roads" else 2
    suffix = "v3" if candidate_number == 3 else "v2"
    output_network = args.output_dir / (
        "network_tpdm3_physical_all_road_explicit_storage_v3.xml.gz"
        if candidate_number == 3
        else "network_tpdm3_physical_explicit_storage_v2.xml.gz"
    )
    shutil.copyfile(args.input_network, output_network)
    registry_path = args.output_dir / f"road_supply_parameters_{suffix}.csv"
    storage_path = args.output_dir / f"road_storage_capacity_{suffix}.csv"
    relationships_path = args.output_dir / f"continuity_candidate_relationships_{suffix}.csv"
    write_csv(registry_path, registry)
    write_csv(storage_path, storage_rows)
    write_csv(relationships_path, [{
        **row,
        "relationship_id": f"{row['upstream_link']}->{row['downstream_link']}",
        "issue_short_lt_threshold": truth(row["issue_short_lt_threshold"]),
        "issue_lane_drop": truth(row["issue_lane_drop"]),
        "issue_storage_lt_one_vehicle": truth(row["issue_storage_lt_one_vehicle"]),
    } for row in relationships])

    x_counts: dict[str, int] = defaultdict(int)
    for row in storage_rows:
        x_counts[str(row["storage_lane_floor_x_pcu"])] += 1
    final_values = [float(row["storage_capacity_qsim_pcu"]) for row in storage_rows]
    above_x = sum(
        float(row["storage_capacity_qsim_pcu"])
        > float(row["storage_lane_floor_x_pcu"]) + 1e-9
        for row in storage_rows
    )
    continuity_target_links = len({
        row["downstream_link"] for row in relationships
    })
    summary = {
        "status": "candidate_generated_not_adopted",
        "parameter_version": (
            CANDIDATE3_VERSION if candidate_number == 3 else CANDIDATE2_VERSION
        ),
        "source": {
            "network": str(args.input_network),
            "network_sha256": network_sha,
            "hotspot_links": str(args.hotspot_links),
            "hotspot_links_sha256": sha256(args.hotspot_links),
            "hotspot_neighbors": str(args.hotspot_neighbors),
            "hotspot_neighbors_sha256": sha256(args.hotspot_neighbors),
        },
        "basis": {
            "storage_capacity_factor": args.storage_factor,
            "flow_capacity_factor": args.flow_factor,
            "effective_cell_size_m": args.effective_cell_size_m,
            "qsim_time_step_s": args.qsim_time_step_s,
            "taxi_pcu": args.taxi_pcu,
        },
        "selection": {
            "storage_scope": args.storage_scope,
            "relationships": len(relationships),
            "continuity_target_links": continuity_target_links,
            "unique_override_links": len(storage_rows),
            "duplicate_target_relationships": len(relationships) - continuity_target_links,
            "x_distribution": dict(sorted(x_counts.items(), key=lambda item: float(item[0]))),
        },
        "storage": {
            "formula": "S_final=max(x,S_default_physical,S_buffer,S_freeflow_flow)",
            "sum_x_pcu": sum(float(row["storage_lane_floor_x_pcu"]) for row in storage_rows),
            "sum_final_qsim_pcu": sum(final_values),
            "minimum_final_qsim_pcu": min(final_values),
            "maximum_final_qsim_pcu": max(final_values),
            "links_equal_x": len(storage_rows) - above_x,
            "links_above_x": above_x,
        },
        "network_qa": {
            "source_sha256": network_sha,
            "output_sha256": sha256(output_network),
            "byte_identical": sha256(output_network) == network_sha,
            "physical_length_lane_freespeed_capacity_topology_unchanged": True,
        },
        "registry": {
            "all_physical_road_links": len(registry),
            "storage_override_links": sum(row["storage_capacity_override"] == "true" for row in registry),
            "flow_override_links": sum(row["flow_capacity_override"] == "true" for row in registry),
        },
        "outputs": {
            "network": str(output_network),
            "road_supply_parameters": str(registry_path),
            "road_storage_capacity": str(storage_path),
            "continuity_relationships": str(relationships_path),
        },
        "limitations": [
            f"Candidate{candidate_number} changes QSim storage only; it does not assert observed physical widening.",
            "The registry is valid only for the documented QSim scale and source network SHA.",
            "A matched no-signal physical-Taxi smoke test is required before adoption.",
        ],
    }
    (args.output_dir / f"road_supply_candidate{candidate_number}_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
