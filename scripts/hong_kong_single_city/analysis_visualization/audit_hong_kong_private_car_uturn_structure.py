#!/usr/bin/env python3
"""Classify private-Car reverse pairs by local directed-network structure.

The output is an evidence triage, not a turn-restriction generator.  In
particular, a junction-choice reversal is not called illegal unless separate
OSM/official geometry evidence establishes that conclusion.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path

from audit_hong_kong_road_network_runtime import read_links


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--links", type=Path, required=True)
    parser.add_argument("--uturn-pairs", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def structural_class(alternative_outgoing_links: int) -> str:
    if alternative_outgoing_links == 0:
        return "forced_reverse_only_dead_end_or_missing_connector"
    if alternative_outgoing_links == 1:
        return "low_choice_terminal_or_access_context"
    return "junction_with_multiple_alternatives_requires_turn_evidence"


def base_route_id(link_id: str) -> str:
    if link_id.endswith(("_f", "_r")):
        return link_id[:-2]
    return link_id


def main() -> int:
    args = parse_args()
    if args.output_dir.exists():
        raise FileExistsError(args.output_dir)
    args.output_dir.mkdir(parents=True)
    links = read_links(args.links)
    outgoing: dict[str, list[str]] = defaultdict(list)
    incoming: dict[str, list[str]] = defaultdict(list)
    for link in links.values():
        if "car" not in link.modes:
            continue
        outgoing[link.from_node].append(link.link_id)
        incoming[link.to_node].append(link.link_id)

    rows: list[dict[str, object]] = []
    with args.uturn_pairs.open("r", encoding="utf-8-sig", newline="") as handle:
        for source in csv.DictReader(handle):
            if source["vehicle_class"] != "private_car" or source["position"] != "internal":
                continue
            first = links[source["from_link"]]
            second = links[source["to_link"]]
            exact_reverse = (
                first.from_node == second.to_node
                and first.to_node == second.from_node
            )
            alternatives = [
                link_id for link_id in outgoing[first.to_node]
                if link_id != second.link_id
            ]
            rows.append(
                {
                    **source,
                    "turn_node": first.to_node,
                    "exact_reverse_geometry": exact_reverse,
                    "same_base_route_id": (
                        base_route_id(first.link_id) == base_route_id(second.link_id)
                    ),
                    "from_length_m": first.length_m,
                    "to_length_m": second.length_m,
                    "turn_node_car_in_degree": len(incoming[first.to_node]),
                    "turn_node_car_out_degree": len(outgoing[first.to_node]),
                    "alternative_outgoing_car_links": len(alternatives),
                    "alternative_outgoing_link_ids": "|".join(sorted(alternatives)),
                    "structural_class": structural_class(len(alternatives)),
                    "restriction_decision": "no_restriction_without_external_turn_evidence",
                }
            )

    fields = list(rows[0]) if rows else []
    with (args.output_dir / "private_car_internal_uturn_structure.csv").open(
        "x", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    pair_counts: Counter[str] = Counter()
    event_counts: Counter[str] = Counter()
    for row in rows:
        category = str(row["structural_class"])
        pair_counts[category] += 1
        event_counts[category] += int(row["count"])
    summary = {
        "status": "audited",
        "private_car_internal_pairs": len(rows),
        "private_car_internal_events": sum(int(row["count"]) for row in rows),
        "pair_counts_by_structural_class": dict(pair_counts),
        "event_counts_by_structural_class": dict(event_counts),
        "same_base_route_pairs": sum(bool(row["same_base_route_id"]) for row in rows),
        "same_base_route_events": sum(
            int(row["count"]) for row in rows if row["same_base_route_id"]
        ),
        "restriction_policy": (
            "structural classification alone does not authorize DisallowedNextLinks; "
            "require OSM restriction, median/junction geometry, or official layout"
        ),
        "output": "private_car_internal_uturn_structure.csv",
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
