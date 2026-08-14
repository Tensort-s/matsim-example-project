#!/usr/bin/env python3
"""Build a signal-reference-only network for zero-demand clock testing."""

from __future__ import annotations

import argparse
import gzip
from pathlib import Path

from lxml import etree as ET

from build_hong_kong_traffic_signal_corridor_safe_boundaries import DEFAULT_OUTPUT
from build_hong_kong_traffic_signal_pilot_v1 import read_csv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT / "signal_clock_smoke_network.xml.gz")
    return parser.parse_args()


def local_name(element: ET._Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def build(args: argparse.Namespace) -> dict[str, int | str]:
    candidate = args.candidate_dir.resolve()
    registry = read_csv(candidate / "signal_corridor_registry.csv")
    corridor_systems = {
        system for row in registry if row["status"] == "implemented"
        for system in row["signal_system_ids"].split("|")
    }
    rows = [
        row for row in read_csv(candidate / "executable_signal_movements.csv")
        if row["signal_system_id"] in corridor_systems
    ]
    required_links = {row[field] for row in rows for field in ("from_link_id", "to_link_id")}
    source = candidate / "network_signal_capacity_deconvolved.xml.gz"
    with gzip.open(source, "rb") as stream:
        tree = ET.parse(stream)
    root = tree.getroot()
    nodes_element = next(child for child in root if local_name(child) == "nodes")
    links_element = next(child for child in root if local_name(child) == "links")
    retained_nodes: set[str] = set()
    retained_links = 0
    for link in list(links_element):
        if local_name(link) != "link":
            continue
        if link.attrib["id"] not in required_links:
            links_element.remove(link)
            continue
        retained_links += 1
        retained_nodes.update((link.attrib["from"], link.attrib["to"]))
    missing_links = required_links.difference(
        link.attrib["id"] for link in links_element if local_name(link) == "link"
    )
    if missing_links:
        raise AssertionError(f"Smoke network is missing {len(missing_links)} signal-referenced links")
    retained_node_count = 0
    for node in list(nodes_element):
        if local_name(node) != "node":
            continue
        if node.attrib["id"] not in retained_nodes:
            nodes_element.remove(node)
        else:
            retained_node_count += 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    doctype = tree.docinfo.doctype or '<!DOCTYPE network SYSTEM "http://www.matsim.org/files/dtd/network_v2.dtd">'
    with gzip.open(args.output, "wb") as stream:
        tree.write(stream, encoding="UTF-8", xml_declaration=True, doctype=doctype)
    summary = {
        "status": "pass",
        "source_network": str(source),
        "output_network": str(args.output.resolve()),
        "signal_movement_count": len(rows),
        "signal_system_count": len(corridor_systems),
        "required_link_count": len(required_links),
        "retained_link_count": retained_links,
        "retained_node_count": retained_node_count,
    }
    return summary


def main() -> None:
    import json
    print(json.dumps(build(parse_args()), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
