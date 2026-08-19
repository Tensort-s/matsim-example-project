#!/usr/bin/env python3
"""Build an all-road storage registry plus bounded full connector-chain flow overrides.

The physical MATSim network is copied byte-for-byte.  A connector seed is
accepted only when the complete same-street chain can be followed until the
physical lane count and link length recover.  Ambiguous or truncated chains
are rejected as a whole, so the candidate cannot silently repair only the
first segment of an internal connector chain.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import json
import math
from pathlib import Path
import re
import shutil
from typing import Any

from build_hong_kong_explicit_storage_candidate import requested_storage
from build_hong_kong_road_continuity_candidate import (
    read_csv,
    read_network_links,
    round_up,
    sha256,
    tpdm_v4_capacity,
    write_csv,
)


ROAD_MODES = frozenset({"car", "bus", "gmb", "school_bus", "school_bus_vehicle"})
VERSION = "hk_road_supply_v4_full_connector_chain_flow_storage_candidate4"
ROAD_ID = re.compile(r"^road_(\d+)_\d+_([fr])$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-network", type=Path, required=True)
    parser.add_argument("--candidate3-registry", type=Path, required=True)
    parser.add_argument("--blocked-link-audit", type=Path, required=True)
    parser.add_argument("--previous-relationships", type=Path, required=True)
    parser.add_argument("--route-directions", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--dominant-share", type=float, default=0.9)
    parser.add_argument("--persistent-seconds", type=float, default=21600.0)
    parser.add_argument("--short-length-m", type=float, default=10.0)
    parser.add_argument("--max-chain-segments", type=int, default=12)
    parser.add_argument("--lane-width-m", type=float, default=3.25)
    parser.add_argument("--capacity-rounding-vph", type=float, default=50.0)
    parser.add_argument("--storage-factor", type=float, default=0.1)
    parser.add_argument("--flow-factor", type=float, default=0.1)
    parser.add_argument("--effective-cell-size-m", type=float, default=7.5)
    parser.add_argument("--qsim-time-step-s", type=float, default=1.0)
    parser.add_argument("--taxi-pcu", type=float, default=0.05)
    return parser.parse_args()


def truth(value: bool) -> str:
    return "true" if value else "false"


def enabled(value: str) -> bool:
    return value.strip().lower() == "true"


def write_optional_csv(
    path: Path, rows: list[dict[str, Any]], fieldnames: list[str]
) -> None:
    """Write an audit even when it has zero data rows."""
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def normalized(value: str) -> str:
    value = " ".join(value.strip().upper().split())
    return "" if value in {"", "-99"} else value


def link_modes(item: dict[str, str]) -> set[str]:
    return {token.strip() for token in item.get("modes", "").split(",") if token.strip()}


def route_street_names(path: Path) -> dict[tuple[str, str], str]:
    result: dict[tuple[str, str], str] = {}
    for row in read_csv(path):
        key = (row["route_id"], row["direction"].lower())
        name = normalized(row.get("street_ename", ""))
        previous = result.get(key, "")
        if previous and name and previous != name:
            raise ValueError(f"Conflicting route street names for {key}: {previous}, {name}")
        if name:
            result[key] = name
    return result


def street_name(link_id: str, route_names: dict[tuple[str, str], str]) -> str:
    match = ROAD_ID.match(link_id)
    if not match:
        return ""
    return route_names.get((match.group(1), match.group(2)), "")


def choose_next(
    current: str,
    chain_street: str,
    links: dict[str, dict[str, str]],
    outgoing: dict[str, list[str]],
    audit: dict[str, dict[str, str]],
    route_names: dict[tuple[str, str], str],
    dominant_share: float,
) -> tuple[str | None, str]:
    row = audit.get(current)
    if row:
        candidate = row.get("dominant_downstream_link", "")
        share = float(row.get("dominant_downstream_share", "0") or 0)
        if candidate in links and share >= dominant_share:
            candidate_street = street_name(candidate, route_names)
            if candidate_street == chain_street:
                return candidate, "observed_dominant"
    candidates = [
        link_id for link_id in outgoing.get(links[current]["to"], [])
        if street_name(link_id, route_names) == chain_street
    ]
    if len(candidates) == 1:
        return candidates[0], "unique_same_street_topology"
    return None, "no_unique_same_street_continuation"


def trace_chain(
    seed: dict[str, Any],
    links: dict[str, dict[str, str]],
    outgoing: dict[str, list[str]],
    audit: dict[str, dict[str, str]],
    route_names: dict[tuple[str, str], str],
    dominant_share: float,
    short_length: float,
    max_segments: int,
) -> dict[str, Any]:
    root = seed["upstream_link"]
    first = seed["downstream_link"]
    root_lanes = float(links[root]["permlanes"])
    chain_street = normalized(seed["street_ename"]) or street_name(root, route_names)
    if not chain_street or street_name(first, route_names) != chain_street:
        return {**seed, "accepted": False, "termination": "street_name_unavailable_or_mismatch", "segments": []}
    segments: list[dict[str, Any]] = []
    seen: set[str] = set()
    current = first
    for order in range(max_segments):
        if current in seen:
            return {**seed, "accepted": False, "termination": "cycle_before_recovery", "segments": []}
        seen.add(current)
        item = links.get(current)
        if item is None:
            return {**seed, "accepted": False, "termination": "missing_network_link", "segments": []}
        length = float(item["length"])
        lanes = float(item["permlanes"])
        impaired = length < short_length or lanes < root_lanes
        if not impaired:
            return {**seed, "accepted": True, "termination": "recovered_normal_cross_section", "segments": segments}
        segments.append({
            "segment_order": order,
            "link_id": current,
            "physical_length_m": length,
            "physical_lanes": lanes,
            "target_lane_floor_x": root_lanes,
        })
        next_link, basis = choose_next(
            current, chain_street, links, outgoing, audit, route_names, dominant_share
        )
        segments[-1]["next_link_basis"] = basis
        segments[-1]["next_link"] = next_link or ""
        if next_link is None:
            return {**seed, "accepted": False, "termination": basis, "segments": []}
        current = next_link
    return {**seed, "accepted": False, "termination": "max_chain_segments_before_recovery", "segments": []}


def build_seeds(
    blocked_rows: list[dict[str, str]], previous_rows: list[dict[str, str]],
    links: dict[str, dict[str, str]], persistent_seconds: float,
    short_length: float,
) -> list[dict[str, Any]]:
    seeds: dict[tuple[str, str], dict[str, Any]] = {}
    for row in previous_rows:
        key = (row["upstream_link"], row["downstream_link"])
        upstream_lanes = float(links[key[0]]["permlanes"])
        downstream = links[key[1]]
        downstream_lanes = float(downstream["permlanes"])
        if upstream_lanes <= downstream_lanes:
            continue
        seeds[key] = {
            "seed_source": "candidate2_previous_lane_drop",
            "upstream_link": key[0], "downstream_link": key[1],
            "street_ename": row["street_ename"],
            "source_delay_vehicle_hours": float(row.get("hotspot_delay_vehicle_hours", "0") or 0),
            "source_blocked_seconds": "",
            "requires_full_connector_chain": float(downstream["length"]) < short_length,
        }
    for row in blocked_rows:
        if not (
            enabled(row.get("representation_review_candidate", "false"))
            and enabled(row.get("dominant_downstream_lane_drop", "false"))
            and enabled(row.get("dominant_downstream_length_lt_10m", "false"))
            and float(row.get("blocked_inflow_seconds", "0") or 0) >= persistent_seconds
        ):
            continue
        key = (row["link_id"], row["dominant_downstream_link"])
        source = seeds.get(key)
        if source:
            source["seed_source"] += "|candidate3_persistent_short_lane_drop"
            source["source_blocked_seconds"] = row["blocked_inflow_seconds"]
            continue
        seeds[key] = {
            "seed_source": "candidate3_persistent_short_lane_drop",
            "upstream_link": key[0], "downstream_link": key[1],
            "street_ename": row["street_ename"],
            "source_delay_vehicle_hours": float(row.get("delay_vehicle_hours", "0") or 0),
            "source_blocked_seconds": row["blocked_inflow_seconds"],
            "requires_full_connector_chain": True,
        }
    return sorted(seeds.values(), key=lambda row: (row["upstream_link"], row["downstream_link"]))


def main() -> int:
    args = parse_args()
    for path in (
        args.input_network, args.candidate3_registry, args.blocked_link_audit,
        args.previous_relationships, args.route_directions,
    ):
        if not path.is_file():
            raise FileNotFoundError(path)
    if args.output_dir.exists():
        raise FileExistsError(f"Output directory must be new: {args.output_dir}")
    links = read_network_links(args.input_network)
    road_links = {
        link_id: item for link_id, item in links.items()
        if link_modes(item) & ROAD_MODES
    }
    outgoing: dict[str, list[str]] = defaultdict(list)
    for link_id, item in road_links.items():
        outgoing[item["from"]].append(link_id)
    for values in outgoing.values():
        values.sort()
    blocked_rows = read_csv(args.blocked_link_audit)
    blocked_audit = {row["link_id"]: row for row in blocked_rows}
    previous_rows = read_csv(args.previous_relationships)
    routes = route_street_names(args.route_directions)
    seeds = build_seeds(
        blocked_rows, previous_rows, road_links,
        args.persistent_seconds, args.short_length_m,
    )
    traced: list[dict[str, Any]] = []
    for seed in seeds:
        if seed["requires_full_connector_chain"]:
            traced.append(trace_chain(
                seed, road_links, outgoing, blocked_audit, routes,
                args.dominant_share, args.short_length_m, args.max_chain_segments,
            ))
        else:
            traced.append({**seed, "accepted": True,
                           "termination": "accepted_previous_nonshort_lane_drop",
                           "segments": [{
                               "segment_order": 0, "link_id": seed["downstream_link"],
                               "physical_length_m": float(road_links[seed["downstream_link"]]["length"]),
                               "physical_lanes": float(road_links[seed["downstream_link"]]["permlanes"]),
                               "target_lane_floor_x": float(road_links[seed["upstream_link"]]["permlanes"]),
                               "next_link_basis": "not_applicable_nonshort", "next_link": "",
                           }]})

    accepted = [row for row in traced if row["accepted"]]
    rejected = [row for row in traced if not row["accepted"]]
    selected: dict[str, dict[str, Any]] = {}
    relationship_rows: list[dict[str, Any]] = []
    for chain in accepted:
        chain_id = f"{chain['upstream_link']}->{chain['downstream_link']}"
        for segment in chain["segments"]:
            link_id = segment["link_id"]
            target = selected.setdefault(link_id, {
                "target_lane_floor_x": 0.0, "chain_ids": set(), "seed_sources": set(),
            })
            target["target_lane_floor_x"] = max(
                target["target_lane_floor_x"], segment["target_lane_floor_x"]
            )
            target["chain_ids"].add(chain_id)
            target["seed_sources"].update(chain["seed_source"].split("|"))
            relationship_rows.append({
                "chain_id": chain_id,
                "seed_source": chain["seed_source"],
                "upstream_link": chain["upstream_link"],
                "initial_downstream_link": chain["downstream_link"],
                "street_ename": normalized(chain["street_ename"]),
                "segment_order": segment["segment_order"],
                "segment_link": link_id,
                "physical_length_m": segment["physical_length_m"],
                "physical_lanes": segment["physical_lanes"],
                "target_lane_floor_x": segment["target_lane_floor_x"],
                "next_link": segment["next_link"],
                "next_link_basis": segment["next_link_basis"],
                "chain_termination": chain["termination"],
                "full_chain_complete": "true",
            })

    source_registry = read_csv(args.candidate3_registry)
    source_by_id = {row["link_id"]: row for row in source_registry}
    if set(source_by_id) != set(road_links):
        raise RuntimeError("Candidate3 registry road-link IDs do not match the physical network")
    network_sha = sha256(args.input_network)
    if {row["source_network_sha256"] for row in source_registry} != {network_sha}:
        raise RuntimeError("Candidate3 registry source-network SHA mismatch")
    registry: list[dict[str, Any]] = []
    storage_rows: list[dict[str, Any]] = []
    flow_rows: list[dict[str, Any]] = []
    for link_id in sorted(road_links):
        item = road_links[link_id]
        old = source_by_id[link_id]
        physical_flow = float(item["capacity"])
        old_x = float(old["storage_lane_floor_x_pcu"])
        target = selected.get(link_id)
        x = max(old_x, target["target_lane_floor_x"] if target else old_x)
        target_flow = round_up(
            max(physical_flow, tpdm_v4_capacity(int(round(x)), args.lane_width_m)),
            args.capacity_rounding_vph,
        ) if target else physical_flow
        flow_override = target_flow > physical_flow + 1e-9
        storage = requested_storage(
            {**item, "capacity": str(target_flow)}, x, args.storage_factor,
            args.flow_factor, args.effective_cell_size_m, args.qsim_time_step_s,
        )
        chain_ids = "|".join(sorted(target["chain_ids"])) if target else ""
        prior_ids = old.get("continuity_relationship_ids", "")
        all_ids = "|".join(filter(None, (prior_ids, chain_ids)))
        registry.append({
            "link_id": link_id,
            "physical_length_m": item["length"],
            "physical_lanes": item["permlanes"],
            "freespeed_m_s": item["freespeed"],
            "physical_flow_capacity_vph": f"{physical_flow:.12f}",
            "flow_capacity_vph": f"{target_flow:.12f}",
            "flow_capacity_source": (
                "full_connector_chain_tpdm_v4_lane_floor" if flow_override
                else old["flow_capacity_source"]
            ),
            "flow_capacity_override": truth(flow_override),
            "storage_capacity_qsim_pcu": f"{storage['final']:.12f}",
            "storage_capacity_source": (
                "all_road_x_plus_full_connector_chain_flow_safety" if target
                else old["storage_capacity_source"]
            ),
            "storage_capacity_override": "true",
            "continuity_candidate": truth(enabled(old["continuity_candidate"]) or bool(target)),
            "storage_lane_floor_x_pcu": f"{x:.12g}",
            "continuity_lane_floor_x_pcu": (
                f"{x:.12g}" if enabled(old["continuity_candidate"]) or target else ""
            ),
            "continuity_relationship_ids": all_ids,
            "parameter_version": VERSION,
            "source_network_sha256": network_sha,
        })
        storage_rows.append({
            "link_id": link_id,
            "storage_lane_floor_x_pcu": f"{x:.12g}",
            "physical_default_storage_qsim_pcu": f"{storage['default_storage']:.12f}",
            "buffer_safety_storage_qsim_pcu": f"{storage['buffer_safety']:.12f}",
            "freeflow_flow_safety_storage_qsim_pcu": f"{storage['freeflow_safety']:.12f}",
            "storage_capacity_qsim_pcu": f"{storage['final']:.12f}",
            "flow_capacity_basis_vph": f"{target_flow:.12f}",
            "chain_relationship_ids": chain_ids,
            "parameter_version": VERSION,
        })
        if flow_override:
            flow_rows.append({
                "link_id": link_id,
                "physical_flow_capacity_vph": f"{physical_flow:.12f}",
                "qsim_flow_capacity_vph": f"{target_flow:.12f}",
                "flow_capacity_delta_vph": f"{target_flow - physical_flow:.12f}",
                "target_lane_floor_x": f"{x:.12g}",
                "physical_lanes": item["permlanes"],
                "chain_relationship_ids": chain_ids,
                "parameter_version": VERSION,
            })

    args.output_dir.mkdir(parents=True)
    network_output = args.output_dir / "network_tpdm3_physical_connector_chain_v4.xml.gz"
    shutil.copyfile(args.input_network, network_output)
    registry_path = args.output_dir / "road_supply_parameters_v4.csv"
    storage_path = args.output_dir / "road_storage_capacity_v4.csv"
    flow_path = args.output_dir / "road_flow_capacity_v4.csv"
    chain_path = args.output_dir / "connector_chain_relationships_v4.csv"
    rejected_path = args.output_dir / "connector_chain_rejected_seeds_v4.csv"
    previous_audit_path = args.output_dir / "previous_candidate_chain_completion_audit_v4.csv"
    write_csv(registry_path, registry)
    write_csv(storage_path, storage_rows)
    write_optional_csv(
        flow_path, flow_rows,
        [
            "link_id", "physical_flow_capacity_vph", "qsim_flow_capacity_vph",
            "flow_capacity_delta_vph", "target_lane_floor_x", "physical_lanes",
            "chain_relationship_ids", "parameter_version",
        ],
    )
    write_optional_csv(
        chain_path, relationship_rows,
        [
            "chain_id", "seed_source", "upstream_link", "initial_downstream_link",
            "street_ename", "segment_order", "segment_link", "physical_length_m",
            "physical_lanes", "target_lane_floor_x", "next_link", "next_link_basis",
            "chain_termination", "full_chain_complete",
        ],
    )
    rejected_rows = [{
        "seed_source": row["seed_source"], "upstream_link": row["upstream_link"],
        "downstream_link": row["downstream_link"], "street_ename": row["street_ename"],
        "termination": row["termination"], "selected_segments": 0,
    } for row in rejected]
    write_optional_csv(
        rejected_path, rejected_rows,
        [
            "seed_source", "upstream_link", "downstream_link", "street_ename",
            "termination", "selected_segments",
        ],
    )
    previous_audit_rows = []
    for row in traced:
        if "candidate2_previous_lane_drop" not in row["seed_source"]:
            continue
        missing = [segment["link_id"] for segment in row["segments"][1:]] if row["accepted"] else []
        previous_audit_rows.append({
            "upstream_link": row["upstream_link"],
            "previous_target_link": row["downstream_link"],
            "street_ename": row["street_ename"],
            "previous_flow_capacity_unhandled": "true",
            "previous_chain_was_incomplete": truth(bool(missing)),
            "missing_chain_segments_now_added": "|".join(missing),
            "candidate4_chain_accepted": truth(row["accepted"]),
            "candidate4_termination": row["termination"],
        })
    write_optional_csv(
        previous_audit_path, previous_audit_rows,
        [
            "upstream_link", "previous_target_link", "street_ename",
            "previous_flow_capacity_unhandled", "previous_chain_was_incomplete",
            "missing_chain_segments_now_added", "candidate4_chain_accepted",
            "candidate4_termination",
        ],
    )

    if sha256(network_output) != network_sha:
        raise RuntimeError("Candidate4 physical network is not byte-identical to TPDM3")
    if any(row["full_chain_complete"] != "true" for row in relationship_rows):
        raise RuntimeError("A selected connector-chain segment is not complete")
    previous_104307 = [
        row for row in previous_audit_rows if row["previous_target_link"] == "road_104307_0_r"
    ]
    summary = {
        "status": "candidate_generated_not_adopted",
        "parameter_version": VERSION,
        "selection": {
            "seed_count": len(seeds),
            "accepted_seed_count": len(accepted),
            "rejected_seed_count": len(rejected),
            "selected_full_chain_segments": len(selected),
            "flow_override_links": len(flow_rows),
            "previous_lane_drop_seed_count": sum(
                "candidate2_previous_lane_drop" in row["seed_source"] for row in traced
            ),
            "previous_incomplete_chains_detected": sum(
                row["previous_chain_was_incomplete"] == "true" for row in previous_audit_rows
            ),
            "road_104307_chain_audit": previous_104307,
        },
        "formulas": {
            "flow_capacity_vph": "max(physical_flow_capacity_vph,round_up(TPDM_V4(x),50))",
            "tpdm_v4_x": "1940+100*(W-3.25) + (x-1)*(2080+100*(W-3.25)); W=3.25m",
            "storage_capacity_qsim_pcu": "max(x,physical_default,buffer_safety,freeflow_flow_safety_using_overridden_flow)",
        },
        "qa": {
            "physical_network_byte_identical": True,
            "source_network_sha256": network_sha,
            "output_network_sha256": sha256(network_output),
            "road_registry_rows": len(registry),
            "all_roads_storage_overridden": all(row["storage_capacity_override"] == "true" for row in registry),
            "no_flow_capacity_reduction": all(
                float(row["flow_capacity_vph"]) >= float(row["physical_flow_capacity_vph"])
                for row in registry
            ),
            "selected_chains_end_only_at_safe_termination": all(
                row["termination"] in {
                    "recovered_normal_cross_section", "accepted_previous_nonshort_lane_drop"
                } for row in accepted
            ),
            "rejected_chains_have_zero_selected_segments": all(not row["segments"] for row in rejected),
        },
        "inputs": {
            "network": str(args.input_network), "network_sha256": network_sha,
            "candidate3_registry": str(args.candidate3_registry),
            "candidate3_registry_sha256": sha256(args.candidate3_registry),
            "blocked_link_audit": str(args.blocked_link_audit),
            "blocked_link_audit_sha256": sha256(args.blocked_link_audit),
            "previous_relationships": str(args.previous_relationships),
            "previous_relationships_sha256": sha256(args.previous_relationships),
            "route_directions": str(args.route_directions),
            "route_directions_sha256": sha256(args.route_directions),
        },
        "outputs": {
            "network": str(network_output),
            "road_supply_parameters": str(registry_path),
            "road_storage_capacity": str(storage_path),
            "road_flow_capacity": str(flow_path),
            "connector_chains": str(chain_path),
            "rejected_seeds": str(rejected_path),
            "previous_candidate_chain_audit": str(previous_audit_path),
        },
        "limitations": [
            "Candidate4 changes QSim flow/storage only and does not assert physical widening.",
            "Long links and ambiguous connector chains are not auto-expanded beyond previously accepted relationships.",
            "A matched no-signal physical-Taxi PCU 0.05 iteration-0 smoke must be run separately.",
        ],
    }
    summary_path = args.output_dir / "road_supply_candidate4_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
