#!/usr/bin/env python3
"""Build a bounded Hong Kong road-continuity repair candidate.

The builder consumes the immutable runtime hotspot-neighborhood audit and
selects only same-street, dominant downstream movements whose downstream link
is short, loses lanes, or has less than one QSim vehicle of storage.  It keeps
all network IDs and topology stable while applying a conservative effective
lane/storage repair to the selected downstream links.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any
import xml.etree.ElementTree as ET


ATTRIBUTE = re.compile(r'([A-Za-z][A-Za-z0-9_]*)="([^"]*)"')
INVALID_STREET_NAMES = frozenset({"", "-99"})
DEFAULT_DOMINANT_SHARE = 0.9
DEFAULT_SHORT_LENGTH_M = 10.0
DEFAULT_STORAGE_FACTOR = 0.1
DEFAULT_EFFECTIVE_CELL_SIZE_M = 7.5
DEFAULT_LANE_WIDTH_M = 3.25
DEFAULT_CAPACITY_ROUNDING_VPH = 50.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-network", type=Path, required=True)
    parser.add_argument("--hotspot-links", type=Path, required=True)
    parser.add_argument("--hotspot-neighbors", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--expected-candidate-relationships", type=int, default=116
    )
    parser.add_argument("--expected-unique-links", type=int, default=114)
    parser.add_argument(
        "--dominant-downstream-share", type=float, default=DEFAULT_DOMINANT_SHARE
    )
    parser.add_argument("--short-length-m", type=float, default=DEFAULT_SHORT_LENGTH_M)
    parser.add_argument("--storage-factor", type=float, default=DEFAULT_STORAGE_FACTOR)
    parser.add_argument(
        "--effective-cell-size-m", type=float,
        default=DEFAULT_EFFECTIVE_CELL_SIZE_M,
    )
    parser.add_argument("--lane-width-m", type=float, default=DEFAULT_LANE_WIDTH_M)
    parser.add_argument(
        "--capacity-rounding-vph", type=float,
        default=DEFAULT_CAPACITY_ROUNDING_VPH,
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def attributes(line: str) -> dict[str, str]:
    return dict(ATTRIBUTE.findall(line))


def normalized_street(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"Refusing to write an empty audit: {path}")
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def is_true(value: bool) -> str:
    return "true" if value else "false"


def select_relationships(
    hotspots: list[dict[str, str]],
    neighbors: list[dict[str, str]],
    dominant_share: float,
    short_length_m: float,
) -> list[dict[str, Any]]:
    neighbor_lookup = {
        (row["hotspot_link"], row["relation"], row["link_id"]): row
        for row in neighbors
    }
    selected: list[dict[str, Any]] = []
    for hotspot in hotspots:
        downstream_id = hotspot["dominant_downstream_link"]
        share_text = hotspot["dominant_downstream_share"]
        share = float(share_text) if share_text else 0.0
        downstream = neighbor_lookup.get(
            (hotspot["link_id"], "downstream", downstream_id)
        )
        if downstream is None or share < dominant_share:
            continue
        upstream_street = normalized_street(hotspot["street_ename"])
        downstream_street = normalized_street(downstream["street_ename"])
        if (
            upstream_street in INVALID_STREET_NAMES
            or upstream_street != downstream_street
        ):
            continue
        upstream_lanes = float(hotspot["lanes"])
        downstream_lanes = float(downstream["lanes"])
        downstream_length = float(downstream["length_m"])
        downstream_storage = float(downstream["storage_proxy_vehicles"])
        short = downstream_length < short_length_m
        lane_drop = downstream_lanes < upstream_lanes
        low_storage = downstream_storage < 1.0
        if not (short or lane_drop or low_storage):
            continue
        selected.append(
            {
                "hotspot_rank": int(hotspot["rank"]),
                "upstream_link": hotspot["link_id"],
                "downstream_link": downstream_id,
                "street_ename": hotspot["street_ename"],
                "dominant_downstream_share": share,
                "upstream_lanes": upstream_lanes,
                "downstream_lanes": downstream_lanes,
                "downstream_length_m": downstream_length,
                "downstream_storage_proxy_vehicles": downstream_storage,
                "hotspot_delay_vehicle_hours": float(
                    hotspot["delay_vehicle_hours"]
                ),
                "issue_short_lt_threshold": short,
                "issue_lane_drop": lane_drop,
                "issue_storage_lt_one_vehicle": low_storage,
            }
        )
    return sorted(
        selected,
        key=lambda row: (row["hotspot_rank"], row["upstream_link"], row["downstream_link"]),
    )


def round_up(value: float, increment: float) -> float:
    return math.ceil((value - 1e-9) / increment) * increment


def tpdm_v4_capacity(lanes: int, lane_width_m: float) -> float:
    nearside = 1940.0 + 100.0 * (lane_width_m - 3.25)
    other = 2080.0 + 100.0 * (lane_width_m - 3.25)
    return nearside + (lanes - 1) * other


def replace_numeric_attribute(line: str, name: str, value: float) -> str:
    return re.sub(
        rf'({re.escape(name)}=")[^"]*(")',
        rf"\g<1>{value:.6f}\g<2>",
        line,
        count=1,
    )


def without_repaired_attributes(line: str) -> bytes:
    normalized = re.sub(r' (?:length|capacity|permlanes)="[^"]*"', "", line)
    return normalized.encode("utf-8")


def build_repairs(
    relationships: list[dict[str, Any]],
    network_links: dict[str, dict[str, str]],
    storage_factor: float,
    effective_cell_size_m: float,
    lane_width_m: float,
    capacity_rounding_vph: float,
) -> dict[str, dict[str, Any]]:
    by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in relationships:
        by_target[row["downstream_link"]].append(row)
    repairs: dict[str, dict[str, Any]] = {}
    for link_id, rows in sorted(by_target.items()):
        if link_id not in network_links:
            raise ValueError(f"Selected downstream link is absent from network: {link_id}")
        item = network_links[link_id]
        old_lanes_float = float(item["permlanes"])
        old_lanes = int(round(old_lanes_float))
        if not math.isclose(old_lanes_float, old_lanes, abs_tol=1e-9):
            raise ValueError(f"Non-integer target lane count: {link_id}={old_lanes_float}")
        upstream_lanes_float = max(float(row["upstream_lanes"]) for row in rows)
        upstream_lanes = int(round(upstream_lanes_float))
        if not math.isclose(upstream_lanes_float, upstream_lanes, abs_tol=1e-9):
            raise ValueError(
                f"Non-integer upstream lane count for {link_id}: {upstream_lanes_float}"
            )
        old_length = float(item["length"])
        old_capacity = float(item["capacity"])
        new_lanes = max(old_lanes, upstream_lanes)
        minimum_storage_length = effective_cell_size_m / (
            storage_factor * new_lanes
        )
        has_low_storage = any(
            bool(row["issue_storage_lt_one_vehicle"]) for row in rows
        )
        new_length = (
            max(old_length, minimum_storage_length)
            if has_low_storage else old_length
        )
        new_capacity = round_up(
            max(old_capacity, tpdm_v4_capacity(new_lanes, lane_width_m)),
            capacity_rounding_vph,
        )
        repairs[link_id] = {
            "link_id": link_id,
            "street_ename": rows[0]["street_ename"],
            "relationship_count": len(rows),
            "upstream_links": "|".join(sorted(row["upstream_link"] for row in rows)),
            "old_length_m": old_length,
            "new_effective_length_m": new_length,
            "length_delta_m": new_length - old_length,
            "old_lanes": old_lanes,
            "new_lanes": new_lanes,
            "lane_delta": new_lanes - old_lanes,
            "old_capacity_vph": old_capacity,
            "new_capacity_vph": new_capacity,
            "capacity_delta_vph": new_capacity - old_capacity,
            "old_storage_proxy_vehicles": (
                old_length * old_lanes * storage_factor / effective_cell_size_m
            ),
            "new_storage_proxy_vehicles": (
                new_length * new_lanes * storage_factor / effective_cell_size_m
            ),
            "issue_short": any(bool(row["issue_short_lt_threshold"]) for row in rows),
            "issue_lane_drop": any(bool(row["issue_lane_drop"]) for row in rows),
            "issue_low_storage": has_low_storage,
        }
    return repairs


def read_network_links(path: Path) -> dict[str, dict[str, str]]:
    links: dict[str, dict[str, str]] = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            if "<link " not in line:
                continue
            item = attributes(line)
            if "id" not in item:
                raise ValueError(f"Malformed network link: {line.rstrip()}")
            links[item["id"]] = item
    return links


def write_network(
    source: Path,
    destination: Path,
    repairs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    source_structure = hashlib.sha256()
    destination_structure = hashlib.sha256()
    changed_ids: set[str] = set()
    total_links = 0
    with gzip.open(source, "rt", encoding="utf-8", newline="") as input_handle:
        with destination.open("xb") as raw_output:
            with gzip.GzipFile(
                filename="", fileobj=raw_output, mode="wb", mtime=0
            ) as compressed:
                for line in input_handle:
                    output_line = line
                    if "<link " in line:
                        total_links += 1
                        item = attributes(line)
                        link_id = item["id"]
                        if link_id in repairs:
                            repair = repairs[link_id]
                            output_line = replace_numeric_attribute(
                                output_line, "length", repair["new_effective_length_m"]
                            )
                            output_line = replace_numeric_attribute(
                                output_line, "capacity", repair["new_capacity_vph"]
                            )
                            output_line = replace_numeric_attribute(
                                output_line, "permlanes", repair["new_lanes"]
                            )
                            changed_ids.add(link_id)
                    source_structure.update(without_repaired_attributes(line))
                    destination_structure.update(
                        without_repaired_attributes(output_line)
                    )
                    compressed.write(output_line.encode("utf-8"))
    if changed_ids != set(repairs):
        missing = sorted(set(repairs) - changed_ids)
        raise RuntimeError(f"Not all selected links were written: {missing}")
    if source_structure.hexdigest() != destination_structure.hexdigest():
        raise RuntimeError("Network content outside length/capacity/permlanes changed")
    with gzip.open(destination, "rb") as handle:
        ET.parse(handle)
    return {
        "total_links": total_links,
        "changed_unique_links": len(changed_ids),
        "changed_link_ids_match_selection": changed_ids == set(repairs),
        "source_nonrepair_sha256": source_structure.hexdigest(),
        "destination_nonrepair_sha256": destination_structure.hexdigest(),
        "xml_parses": True,
    }


def main() -> int:
    args = parse_args()
    for path in (args.input_network, args.hotspot_links, args.hotspot_neighbors):
        if not path.is_file():
            raise FileNotFoundError(path)
    if args.output_dir.exists():
        raise FileExistsError(f"Output directory must be new: {args.output_dir}")
    if not 0 < args.dominant_downstream_share <= 1:
        raise ValueError("--dominant-downstream-share must be in (0, 1]")
    if min(
        args.short_length_m,
        args.storage_factor,
        args.effective_cell_size_m,
        args.lane_width_m,
        args.capacity_rounding_vph,
    ) <= 0:
        raise ValueError("All physical thresholds must be positive")

    hotspots = read_csv(args.hotspot_links)
    neighbors = read_csv(args.hotspot_neighbors)
    relationships = select_relationships(
        hotspots,
        neighbors,
        args.dominant_downstream_share,
        args.short_length_m,
    )
    if len(relationships) != args.expected_candidate_relationships:
        raise RuntimeError(
            "Candidate relationship count changed: "
            f"expected {args.expected_candidate_relationships}, got {len(relationships)}"
        )
    network_links = read_network_links(args.input_network)
    repairs = build_repairs(
        relationships,
        network_links,
        args.storage_factor,
        args.effective_cell_size_m,
        args.lane_width_m,
        args.capacity_rounding_vph,
    )
    if len(repairs) != args.expected_unique_links:
        raise RuntimeError(
            f"Unique repair-link count changed: expected {args.expected_unique_links}, "
            f"got {len(repairs)}"
        )
    unchanged = [
        row["link_id"] for row in repairs.values()
        if math.isclose(row["old_length_m"], row["new_effective_length_m"])
        and row["old_lanes"] == row["new_lanes"]
        and math.isclose(row["old_capacity_vph"], row["new_capacity_vph"])
    ]
    if unchanged:
        raise RuntimeError(f"Selected repair links would remain unchanged: {unchanged}")

    args.output_dir.mkdir(parents=True)
    output_network = args.output_dir / "network_road_continuity_116.xml.gz"
    relationship_csv = args.output_dir / "continuity_candidate_relationships.csv"
    change_csv = args.output_dir / "continuity_link_changes.csv"
    relationship_rows = [
        {
            **row,
            "issue_short_lt_threshold": is_true(row["issue_short_lt_threshold"]),
            "issue_lane_drop": is_true(row["issue_lane_drop"]),
            "issue_storage_lt_one_vehicle": is_true(
                row["issue_storage_lt_one_vehicle"]
            ),
        }
        for row in relationships
    ]
    change_rows = [
        {
            **row,
            "issue_short": is_true(row["issue_short"]),
            "issue_lane_drop": is_true(row["issue_lane_drop"]),
            "issue_low_storage": is_true(row["issue_low_storage"]),
        }
        for row in repairs.values()
    ]
    write_csv(relationship_csv, relationship_rows)
    write_csv(change_csv, change_rows)
    network_qa = write_network(args.input_network, output_network, repairs)

    changed = list(repairs.values())
    summary = {
        "status": "candidate_generated_not_adopted",
        "selection": {
            "candidate_relationships": len(relationships),
            "unique_downstream_links": len(repairs),
            "duplicate_target_relationships": len(relationships) - len(repairs),
            "same_street_required": True,
            "invalid_street_names_excluded": sorted(INVALID_STREET_NAMES),
            "dominant_downstream_share_minimum": args.dominant_downstream_share,
            "qualifying_issue": (
                "downstream length < threshold OR downstream lanes < upstream lanes "
                "OR downstream storage proxy < 1 vehicle"
            ),
            "short_length_threshold_m": args.short_length_m,
            "issue_relationship_counts": {
                "short": sum(row["issue_short_lt_threshold"] for row in relationships),
                "lane_drop": sum(row["issue_lane_drop"] for row in relationships),
                "low_storage": sum(
                    row["issue_storage_lt_one_vehicle"] for row in relationships
                ),
            },
            "hotspot_delay_vehicle_hours_overlapping": sum(
                row["hotspot_delay_vehicle_hours"] for row in relationships
            ),
        },
        "repair_method": {
            "new_lanes": "max(old downstream lanes, selected upstream lanes)",
            "minimum_effective_length_m": (
                "effective_cell_size_m / (storageCapacityFactor * new_lanes) "
                "for selected links with storage proxy < 1"
            ),
            "new_capacity_vph": (
                "ceil_to_rounding(max(old capacity, TPDM_V4(new_lanes)))"
            ),
            "storage_capacity_factor": args.storage_factor,
            "effective_cell_size_m": args.effective_cell_size_m,
            "lane_width_m": args.lane_width_m,
            "capacity_rounding_vph": args.capacity_rounding_vph,
        },
        "source": {
            "network": str(args.input_network),
            "network_sha256": sha256(args.input_network),
            "hotspot_links": str(args.hotspot_links),
            "hotspot_links_sha256": sha256(args.hotspot_links),
            "hotspot_neighbors": str(args.hotspot_neighbors),
            "hotspot_neighbors_sha256": sha256(args.hotspot_neighbors),
        },
        "output": {
            "network": str(output_network),
            "network_sha256": sha256(output_network),
            "candidate_relationships": str(relationship_csv),
            "candidate_relationships_sha256": sha256(relationship_csv),
            "link_changes": str(change_csv),
            "link_changes_sha256": sha256(change_csv),
        },
        "change": {
            "links_with_lane_increase": sum(row["lane_delta"] > 0 for row in changed),
            "links_with_effective_length_increase": sum(
                row["length_delta_m"] > 1e-9 for row in changed
            ),
            "links_with_capacity_increase": sum(
                row["capacity_delta_vph"] > 1e-9 for row in changed
            ),
            "lane_sum_before": sum(row["old_lanes"] for row in changed),
            "lane_sum_after": sum(row["new_lanes"] for row in changed),
            "effective_length_sum_before_m": sum(
                row["old_length_m"] for row in changed
            ),
            "effective_length_sum_after_m": sum(
                row["new_effective_length_m"] for row in changed
            ),
            "capacity_sum_before_vph": sum(
                row["old_capacity_vph"] for row in changed
            ),
            "capacity_sum_after_vph": sum(
                row["new_capacity_vph"] for row in changed
            ),
            "minimum_new_storage_proxy_vehicles": min(
                row["new_storage_proxy_vehicles"] for row in changed
            ),
        },
        "network_qa": network_qa,
        "invariants": {
            "only_selected_unique_links_changed": network_qa[
                "changed_link_ids_match_selection"
            ],
            "only_length_capacity_permlanes_may_change": (
                network_qa["source_nonrepair_sha256"]
                == network_qa["destination_nonrepair_sha256"]
            ),
            "node_link_ids_and_topology_unchanged": True,
            "modes_and_signal_references_not_modified": True,
            "all_repaired_storage_proxies_ge_one": all(
                row["new_storage_proxy_vehicles"] >= 1.0 - 1e-9
                for row in changed
            ),
            "no_lane_reduction": all(row["lane_delta"] >= 0 for row in changed),
            "no_capacity_reduction": all(
                row["capacity_delta_vph"] >= 0 for row in changed
            ),
            "no_effective_length_reduction": all(
                row["length_delta_m"] >= 0 for row in changed
            ),
            "xml_parses": network_qa["xml_parses"],
        },
        "limitations": [
            "This is a runtime-derived sensitivity candidate, not observed lane geometry.",
            "Effective length is a bounded QSim storage proxy and changes free-flow length.",
            "A controlled smoke comparison is required before adoption.",
        ],
    }
    summary_path = args.output_dir / "road_continuity_candidate_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
