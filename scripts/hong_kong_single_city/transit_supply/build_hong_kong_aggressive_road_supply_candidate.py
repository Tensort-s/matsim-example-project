#!/usr/bin/env python3
"""Build staged Candidate5 QSim-only flow/storage regularization candidates."""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
import csv
import json
import math
from pathlib import Path
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
STAGE_MULTIPLIER = {"A": 1.0, "B": 1.25, "C": 1.5}
STAGE_BLOCKED_THRESHOLD = {"A": 0.0, "B": 21600.0, "C": 43200.0}
VERSION = "hk_road_supply_v5_aggressive_component_regularization"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=sorted(STAGE_MULTIPLIER), required=True)
    parser.add_argument("--input-network", type=Path, required=True)
    parser.add_argument("--baseline-registry", type=Path, required=True)
    parser.add_argument("--source-registry", type=Path, required=True)
    parser.add_argument("--runtime-supply-audit", type=Path, required=True)
    parser.add_argument("--blocked-link-audit", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--short-link-m", type=float, default=30.0)
    parser.add_argument("--component-radius-m", type=float, default=80.0)
    parser.add_argument("--max-component-depth", type=int, default=5)
    parser.add_argument("--severe-component-radius-m", type=float, default=250.0)
    parser.add_argument("--severe-max-component-depth", type=int, default=12)
    parser.add_argument("--capacity-rounding-vph", type=float, default=50.0)
    parser.add_argument("--storage-factor", type=float, default=0.1)
    parser.add_argument("--flow-factor", type=float, default=0.1)
    parser.add_argument("--effective-cell-size-m", type=float, default=7.5)
    parser.add_argument("--qsim-time-step-s", type=float, default=1.0)
    parser.add_argument("--expected-road-links", type=int, default=86417)
    parser.add_argument("--expected-blocked-links", type=int, default=3134)
    parser.add_argument("--expected-representation-seeds", type=int, default=365)
    return parser.parse_args()


def enabled(value: str) -> bool:
    return value.strip().lower() == "true"


def modes(item: dict[str, str]) -> set[str]:
    return {token.strip() for token in item.get("modes", "").split(",") if token.strip()}


def percentile90(values: list[float], fallback: float) -> float:
    if not values:
        return fallback
    ordered = sorted(values)
    return ordered[math.ceil(0.9 * len(ordered)) - 1]


def build_incidence(
    links: dict[str, dict[str, str]],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    incoming: dict[str, list[str]] = defaultdict(list)
    outgoing: dict[str, list[str]] = defaultdict(list)
    for link_id, item in links.items():
        incoming[item["to"]].append(link_id)
        outgoing[item["from"]].append(link_id)
    for values in (*incoming.values(), *outgoing.values()):
        values.sort()
    return incoming, outgoing


def expand_seed_component(
    first_link: str,
    root_lanes: float,
    links: dict[str, dict[str, str]],
    incoming: dict[str, list[str]],
    outgoing: dict[str, list[str]],
    short_link_m: float,
    radius_m: float,
    max_depth: int,
) -> set[str]:
    """Flood all plausible short/deficient connector branches within a local radius."""
    if first_link not in links:
        return set()
    selected: set[str] = set()
    best_distance: dict[str, float] = {first_link: 0.0}
    queue: deque[tuple[str, int, float]] = deque([(first_link, 0, 0.0)])
    while queue:
        link_id, depth, distance = queue.popleft()
        item = links[link_id]
        length = float(item["length"])
        lanes = float(item["permlanes"])
        if depth > 0 and length >= short_link_m and lanes >= root_lanes:
            continue
        selected.add(link_id)
        if depth >= max_depth:
            continue
        adjacent = set(incoming[item["from"]] + outgoing[item["from"]]
                       + incoming[item["to"]] + outgoing[item["to"]])
        adjacent.discard(link_id)
        for other in sorted(adjacent):
            candidate = links[other]
            candidate_length = float(candidate["length"])
            candidate_lanes = float(candidate["permlanes"])
            if candidate_length >= short_link_m and candidate_lanes >= root_lanes:
                continue
            next_distance = distance + candidate_length
            if next_distance > radius_m + 1e-9:
                continue
            if next_distance + 1e-9 >= best_distance.get(other, math.inf):
                continue
            best_distance[other] = next_distance
            queue.append((other, depth + 1, next_distance))
    return selected


def merge_components(seed_components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parent = list(range(len(seed_components)))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    owners: dict[str, int] = {}
    for index, component in enumerate(seed_components):
        for link_id in component["links"]:
            previous = owners.get(link_id)
            if previous is None:
                owners[link_id] = index
                continue
            left, right = root(index), root(previous)
            if left != right:
                parent[right] = left
    merged: dict[int, dict[str, Any]] = {}
    for index, component in enumerate(seed_components):
        target = merged.setdefault(root(index), {"links": set(), "seeds": [], "root_lanes": []})
        target["links"].update(component["links"])
        target["seeds"].append(component["seed"])
        target["root_lanes"].append(component["root_lanes"])
    return sorted(merged.values(), key=lambda item: min(item["links"]))


def stage_a_components(
    blocked_rows: list[dict[str, str]],
    links: dict[str, dict[str, str]],
    incoming: dict[str, list[str]],
    outgoing: dict[str, list[str]],
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    seeds = [row for row in blocked_rows if enabled(row["representation_review_candidate"])]
    if len(seeds) != args.expected_representation_seeds:
        raise RuntimeError(
            f"Expected {args.expected_representation_seeds} representation seeds; found {len(seeds)}"
        )
    expanded = []
    for seed in seeds:
        upstream = seed["link_id"]
        downstream = seed["dominant_downstream_link"]
        root_lanes = float(links[upstream]["permlanes"])
        component_links = expand_seed_component(
            downstream, root_lanes, links, incoming, outgoing,
            args.short_link_m, args.component_radius_m, args.max_component_depth,
        )
        if not component_links:
            raise RuntimeError(f"Representation seed has no component: {upstream}->{downstream}")
        expanded.append({"seed": f"{upstream}->{downstream}", "root_lanes": root_lanes,
                         "links": component_links})
    return merge_components(expanded)


def inherited_components(source_rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in source_rows:
        if not enabled(row.get("candidate5_component", "false")):
            continue
        for component_id in filter(None, row.get("candidate5_component_ids", "").split("|")):
            item = grouped.setdefault(component_id, {"links": set(), "seeds": [], "root_lanes": []})
            item["links"].add(row["link_id"])
            item["root_lanes"].append(float(row["candidate5_corridor_lane_x"]))
    return sorted(grouped.values(), key=lambda item: min(item["links"]))


def severe_runtime_components(
    severe_ids: set[str],
    source_rows: list[dict[str, str]],
    links: dict[str, dict[str, str]],
    incoming: dict[str, list[str]],
    outgoing: dict[str, list[str]],
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    """Rebuild complete local chains around severe links, including boundaries.

    Stage A components are treated as indivisible connector chains.  A severe
    seed expands in both graph directions through severe links, inherited
    component members, short links, and links whose lane count is below the
    seed corridor.  The first ordinary entry/exit links are then included as
    capacity boundaries but are not used to continue the flood.
    """
    source_by_link = {row["link_id"]: row for row in source_rows}
    inherited = inherited_components(source_rows)
    inherited_by_link: dict[str, set[str]] = {}
    for component in inherited:
        members = set(component["links"])
        for link_id in members:
            inherited_by_link[link_id] = members

    expanded: list[dict[str, Any]] = []
    for seed in sorted(severe_ids):
        if seed not in links:
            raise RuntimeError(f"Severe runtime link is absent from network: {seed}")
        root_lanes = max(
            float(links[seed]["permlanes"]),
            float(source_by_link[seed].get("candidate5_corridor_lane_x") or 0.0),
        )
        core: set[str] = set()
        best: dict[str, tuple[int, float]] = {seed: (0, 0.0)}
        queue: deque[tuple[str, int, float]] = deque([(seed, 0, 0.0)])
        while queue:
            link_id, depth, distance = queue.popleft()
            if link_id in core:
                continue
            core.add(link_id)

            inherited_members = inherited_by_link.get(link_id, set())
            for member in sorted(inherited_members):
                if member not in core:
                    queue.appendleft((member, depth, distance))

            if depth >= args.severe_max_component_depth:
                continue
            item = links[link_id]
            adjacent = set(
                incoming[item["from"]] + outgoing[item["from"]]
                + incoming[item["to"]] + outgoing[item["to"]]
            )
            adjacent.discard(link_id)
            for other in sorted(adjacent):
                candidate = links[other]
                candidate_length = float(candidate["length"])
                candidate_lanes = float(candidate["permlanes"])
                traversable = (
                    other in severe_ids
                    or other in inherited_by_link
                    or candidate_length < args.short_link_m
                    or candidate_lanes < root_lanes
                )
                if not traversable:
                    continue
                next_distance = distance + candidate_length
                if next_distance > args.severe_component_radius_m + 1e-9:
                    continue
                state = (depth + 1, next_distance)
                if state >= best.get(other, (10**9, math.inf)):
                    continue
                best[other] = state
                queue.append((other, depth + 1, next_distance))

        expanded.append({
            "seed": seed,
            "root_lanes": root_lanes,
            "links": core,
        })
    merged_core = merge_components(expanded)
    completed: list[dict[str, Any]] = []
    for component in merged_core:
        core = set(component["links"])
        boundary: set[str] = set()
        for link_id in core:
            item = links[link_id]
            boundary.update(other for other in incoming[item["from"]] if other not in core)
            boundary.update(other for other in outgoing[item["to"]] if other not in core)
        completed.append({
            **component,
            "links": core | boundary,
            "core_links": core,
            "boundary_links": boundary,
        })
    return completed


def assign_component_properties(
    components: list[dict[str, Any]],
    links: dict[str, dict[str, str]],
    incoming: dict[str, list[str]],
    outgoing: dict[str, list[str]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    by_link: dict[str, dict[str, Any]] = {}
    component_rows: list[dict[str, Any]] = []
    for index, component in enumerate(components, start=1):
        component_id = f"C5COMP_{index:04d}"
        member_ids = set(component["links"])
        entry = {
            other for link_id in member_ids
            for other in incoming[links[link_id]["from"]] if other not in member_ids
        }
        exit_links = {
            other for link_id in member_ids
            for other in outgoing[links[link_id]["to"]] if other not in member_ids
        }
        internal_max = max(float(links[item]["permlanes"]) for item in member_ids)
        fallback = max(component.get("root_lanes") or [internal_max])
        entry_p90 = percentile90([float(links[item]["permlanes"]) for item in entry], fallback)
        exit_p90 = percentile90([float(links[item]["permlanes"]) for item in exit_links], fallback)
        corridor_x = max(internal_max, min(entry_p90, exit_p90))
        corridor_x = min(7.0, max(1.0, corridor_x))
        corridor_capacity = round_up(tpdm_v4_capacity(int(math.ceil(corridor_x)), 3.25), 50.0)
        for link_id in sorted(member_ids):
            siblings = [item for item in member_ids if links[item]["from"] == links[link_id]["from"]]
            lane_sum = sum(max(1.0, float(links[item]["permlanes"])) for item in siblings)
            branch_share = max(1.0, float(links[link_id]["permlanes"])) / lane_sum
            target = by_link.setdefault(link_id, {
                "component_ids": set(), "corridor_x": 0.0, "flow_floor_vph": 0.0,
            })
            target["component_ids"].add(component_id)
            target["corridor_x"] = max(target["corridor_x"], corridor_x)
            target["flow_floor_vph"] = max(
                target["flow_floor_vph"], corridor_capacity * branch_share,
            )
            component_rows.append({
                "component_id": component_id,
                "link_id": link_id,
                "corridor_lane_x": f"{corridor_x:.12g}",
                "corridor_capacity_vph": f"{corridor_capacity:.12f}",
                "branch_count": len(siblings),
                "branch_share": f"{branch_share:.12f}",
                "allocated_flow_floor_vph": f"{corridor_capacity * branch_share:.12f}",
                "entry_boundary_links": "|".join(sorted(entry)),
                "exit_boundary_links": "|".join(sorted(exit_links)),
                "source_seed_count": len(component.get("seeds", [])),
            })
    return by_link, component_rows


def main() -> int:
    args = parse_args()
    for path in (
        args.input_network, args.baseline_registry, args.source_registry,
        args.runtime_supply_audit, args.blocked_link_audit,
    ):
        if not path.is_file():
            raise FileNotFoundError(path)
    if args.output_dir.exists():
        raise FileExistsError(args.output_dir)
    network_sha = sha256(args.input_network)
    links = {
        link_id: item for link_id, item in read_network_links(args.input_network).items()
        if modes(item) & ROAD_MODES
    }
    if len(links) != args.expected_road_links:
        raise RuntimeError(f"Expected {args.expected_road_links} road links; found {len(links)}")
    incoming, outgoing = build_incidence(links)
    blocked_rows = read_csv(args.blocked_link_audit)
    if len(blocked_rows) != args.expected_blocked_links:
        raise RuntimeError(f"Expected {args.expected_blocked_links} blocked links; found {len(blocked_rows)}")
    blocked_ids = {row["link_id"] for row in blocked_rows}
    source_rows = read_csv(args.source_registry)
    baseline_rows = read_csv(args.baseline_registry)
    source = {row["link_id"]: row for row in source_rows}
    baseline = {row["link_id"]: row for row in baseline_rows}
    if set(source) != set(links) or set(baseline) != set(links):
        raise RuntimeError("Road registry IDs do not match network road links")
    if {row["source_network_sha256"] for row in source_rows} != {network_sha}:
        raise RuntimeError("Source registry network SHA mismatch")
    runtime_rows = read_csv(args.runtime_supply_audit)
    runtime = {row["link_id"]: row for row in runtime_rows}
    if set(runtime) != set(links):
        raise RuntimeError("Runtime supply audit IDs do not match road links")

    severe_threshold = STAGE_BLOCKED_THRESHOLD[args.stage]
    severe_ids = (
        set() if args.stage == "A" else {
            link_id for link_id, row in runtime.items()
            if float(row["blocked_inflow_seconds"]) >= severe_threshold
        }
    )
    components = (
        stage_a_components(blocked_rows, links, incoming, outgoing, args)
        if args.stage == "A" else severe_runtime_components(
            severe_ids, source_rows, links, incoming, outgoing, args
        )
    )
    component_by_link, component_rows = assign_component_properties(
        components, links, incoming, outgoing
    )

    registry: list[dict[str, Any]] = []
    storage_rows: list[dict[str, Any]] = []
    flow_rows: list[dict[str, Any]] = []
    changed_storage = 0
    changed_flow = 0
    for link_id in sorted(links):
        item = links[link_id]
        old = source[link_id]
        base = baseline[link_id]
        physical_flow = float(item["capacity"])
        old_flow = float(old["flow_capacity_vph"])
        base_flow = float(base["flow_capacity_vph"])
        lane_x = float(old.get("storage_lane_floor_x_pcu", item["permlanes"]))
        old_floor = float(old.get("storage_floor_pcu") or lane_x)
        component = component_by_link.get(link_id)
        corridor_x = component["corridor_x"] if component else float(
            old.get("candidate5_corridor_lane_x") or lane_x
        )
        flow_target = old_flow
        reasons: list[str] = []
        if component:
            flow_target = max(flow_target, component["flow_floor_vph"])
            reasons.append("representation_component")
        if component and args.stage != "A":
            multiplier = STAGE_MULTIPLIER[args.stage]
            tpdm = tpdm_v4_capacity(max(1, int(math.ceil(corridor_x))), 3.25)
            staged_target = min(
                2.0 * base_flow,
                max(tpdm, multiplier * base_flow, component["flow_floor_vph"]),
            )
            flow_target = max(flow_target, staged_target)
            reasons.append(f"stage_{args.stage.lower()}_complete_chain_flow")
        if link_id in severe_ids:
            reasons.append(f"blocked_ge_{int(severe_threshold)}s_seed")
        flow_target = round_up(max(physical_flow, flow_target), args.capacity_rounding_vph)
        flow_override = flow_target > physical_flow + 1e-9

        qsim_flow_pcu_s = flow_target * args.flow_factor / 3600.0
        storage_floor = old_floor
        if link_id in blocked_ids or link_id in severe_ids:
            storage_floor = max(storage_floor, 2.0 * lane_x, 30.0 * qsim_flow_pcu_s)
            reasons.append(
                "all_3134_blocked_storage"
                if link_id in blocked_ids else "stage_severe_blocked_storage"
            )
        if component:
            storage_floor = max(storage_floor, 4.0 * corridor_x, 60.0 * qsim_flow_pcu_s)
            reasons.append("representation_component_60s_storage")
        if args.stage == "C" and link_id in severe_ids:
            storage_floor = max(storage_floor, 90.0 * qsim_flow_pcu_s)
            reasons.append("stage_c_90s_storage")
        storage = requested_storage(
            {**item, "capacity": str(flow_target)}, storage_floor,
            args.storage_factor, args.flow_factor,
            args.effective_cell_size_m, args.qsim_time_step_s,
        )
        old_storage = float(old["storage_capacity_qsim_pcu"])
        if flow_target > old_flow + 1e-9:
            changed_flow += 1
        if storage["final"] > old_storage + 1e-9:
            changed_storage += 1
        inherited_ids = set(filter(None, old.get("candidate5_component_ids", "").split("|")))
        if component:
            inherited_ids.update(component["component_ids"])
        component_ids = "|".join(sorted(inherited_ids))
        registry.append({
            "link_id": link_id,
            "physical_length_m": item["length"],
            "physical_lanes": item["permlanes"],
            "freespeed_m_s": item["freespeed"],
            "physical_flow_capacity_vph": f"{physical_flow:.12f}",
            "flow_capacity_vph": f"{flow_target:.12f}",
            "flow_capacity_source": (
                f"candidate5_stage_{args.stage.lower()}_qsim_regularization"
                if flow_target > old_flow + 1e-9 else old["flow_capacity_source"]
            ),
            "flow_capacity_override": str(flow_override).lower(),
            "storage_capacity_qsim_pcu": f"{storage['final']:.12f}",
            "storage_capacity_source": (
                f"candidate5_stage_{args.stage.lower()}_finite_time_buffer"
                if storage["final"] > old_storage + 1e-9 else old["storage_capacity_source"]
            ),
            "storage_capacity_override": "true",
            "storage_floor_pcu": f"{storage_floor:.12f}",
            "continuity_candidate": old["continuity_candidate"],
            "storage_lane_floor_x_pcu": f"{lane_x:.12g}",
            "continuity_lane_floor_x_pcu": old.get("continuity_lane_floor_x_pcu", ""),
            "continuity_relationship_ids": old.get("continuity_relationship_ids", ""),
            "candidate5_component": str(bool(component_ids)).lower(),
            "candidate5_component_ids": component_ids,
            "candidate5_corridor_lane_x": f"{corridor_x:.12g}" if component_ids else "",
            "candidate5_stage": args.stage,
            "candidate5_reason": "|".join(dict.fromkeys(reasons)),
            "parameter_version": f"{VERSION}_stage_{args.stage.lower()}",
            "source_network_sha256": network_sha,
        })
        storage_rows.append({
            "link_id": link_id,
            "old_storage_capacity_qsim_pcu": f"{old_storage:.12f}",
            "storage_floor_pcu": f"{storage_floor:.12f}",
            "storage_capacity_qsim_pcu": f"{storage['final']:.12f}",
            "storage_delta_qsim_pcu": f"{storage['final'] - old_storage:.12f}",
            "flow_capacity_basis_vph": f"{flow_target:.12f}",
            "candidate5_reason": "|".join(dict.fromkeys(reasons)),
        })
        if flow_override:
            flow_rows.append({
                "link_id": link_id,
                "physical_flow_capacity_vph": f"{physical_flow:.12f}",
                "source_qsim_flow_capacity_vph": f"{old_flow:.12f}",
                "qsim_flow_capacity_vph": f"{flow_target:.12f}",
                "stage_flow_delta_vph": f"{flow_target - old_flow:.12f}",
                "total_flow_delta_vph": f"{flow_target - physical_flow:.12f}",
                "candidate5_reason": "|".join(dict.fromkeys(reasons)),
            })

    args.output_dir.mkdir(parents=True)
    network_output = args.output_dir / f"network_tpdm3_physical_candidate5{args.stage.lower()}.xml.gz"
    shutil.copyfile(args.input_network, network_output)
    write_csv(args.output_dir / f"road_supply_parameters_v5{args.stage.lower()}.csv", registry)
    write_csv(args.output_dir / f"road_storage_capacity_v5{args.stage.lower()}.csv", storage_rows)
    write_csv(args.output_dir / f"road_flow_capacity_v5{args.stage.lower()}.csv", flow_rows)
    write_csv(args.output_dir / f"road_component_membership_v5{args.stage.lower()}.csv", component_rows)
    if sha256(network_output) != network_sha:
        raise RuntimeError("Candidate5 physical network bytes changed")
    summary = {
        "status": "candidate_generated_not_adopted",
        "stage": args.stage,
        "parameter_version": f"{VERSION}_stage_{args.stage.lower()}",
        "selection": {
            "blocked_link_scope": len(blocked_ids),
            "representation_seed_count": sum(
                enabled(row["representation_review_candidate"]) for row in blocked_rows
            ),
            "component_basis": (
                "representation_review"
                if args.stage == "A" else "severe_runtime_complete_chain"
            ),
            "component_count": len(components),
            "component_unique_links": len(component_by_link),
            "representation_component_count": len(components) if args.stage == "A" else 0,
            "representation_component_unique_links": (
                len(component_by_link) if args.stage == "A" else 0
            ),
            "severe_component_count": len(components) if args.stage != "A" else 0,
            "severe_component_unique_links": (
                len(component_by_link) if args.stage != "A" else 0
            ),
            "severe_runtime_links": len(severe_ids),
            "stage_flow_increase_links": changed_flow,
            "stage_storage_increase_links": changed_storage,
            "total_flow_override_links": sum(row["flow_capacity_override"] == "true" for row in registry),
        },
        "formulas": {
            "blocked_storage": "max(old_floor,2*x,30*qsim_flow_pcu_s)",
            "component_storage": "max(old_floor,4*x_corridor,60*qsim_flow_pcu_s)",
            "stage_c_severe_storage": "max(previous,90*qsim_flow_pcu_s)",
            "stage_b_flow": "max(Candidate5A,min(2*Candidate4,max(TPDM(xcorr),1.25*Candidate4,boundary_allocated))) on rebuilt severe components",
            "stage_c_flow": "max(previous,min(2*Candidate4,max(TPDM(xcorr),1.50*Candidate4,boundary_allocated))) on rebuilt severe components",
        },
        "qa": {
            "physical_network_byte_identical": True,
            "network_sha256": network_sha,
            "road_registry_rows": len(registry),
            "no_flow_reduction_from_source": all(
                float(row["flow_capacity_vph"]) + 1e-9 >= float(source[row["link_id"]]["flow_capacity_vph"])
                for row in registry
            ),
            "no_storage_reduction_from_source": all(
                float(row["storage_capacity_qsim_pcu"]) + 1e-9
                >= float(source[row["link_id"]]["storage_capacity_qsim_pcu"])
                for row in registry
            ),
        },
        "inputs": {
            "network": str(args.input_network),
            "baseline_registry": str(args.baseline_registry),
            "source_registry": str(args.source_registry),
            "runtime_supply_audit": str(args.runtime_supply_audit),
            "blocked_link_audit": str(args.blocked_link_audit),
        },
    }
    summary_path = args.output_dir / f"road_supply_candidate5{args.stage.lower()}_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
