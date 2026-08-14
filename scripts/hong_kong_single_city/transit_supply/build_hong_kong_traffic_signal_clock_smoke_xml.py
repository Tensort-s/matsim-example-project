#!/usr/bin/env python3
"""Subset compiled signal XML to the 47 Candidate11 corridor systems."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lxml import etree as ET

from build_hong_kong_traffic_signal_corridor_safe_boundaries import DEFAULT_OUTPUT
from build_hong_kong_traffic_signal_pilot_v1 import read_csv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT / "signal_clock_smoke_matsim")
    return parser.parse_args()


def local_name(element: ET._Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def subset(source: Path, output: Path, systems: set[str]) -> int:
    tree = ET.parse(source)
    root = tree.getroot()
    count = 0
    for child in list(root):
        if local_name(child) != "signalSystem":
            continue
        if child.attrib.get("id", child.attrib.get("refId")) not in systems:
            root.remove(child)
        else:
            count += 1
    output.parent.mkdir(parents=True, exist_ok=True)
    tree.write(
        output, encoding="UTF-8", xml_declaration=True,
        standalone=True, pretty_print=True,
    )
    return count


def main() -> None:
    args = parse_args()
    candidate = args.candidate_dir.resolve()
    registry = read_csv(candidate / "signal_corridor_registry.csv")
    systems = {
        system for row in registry if row["status"] == "implemented"
        for system in row["signal_system_ids"].split("|")
    }
    if len(systems) != 47:
        raise AssertionError(f"Expected 47 corridor systems; found {len(systems)}")
    counts = {}
    for name in ("signal_systems.xml", "signal_groups.xml", "signal_control.xml", "intergreen_times.xml"):
        counts[name] = subset(candidate / "matsim" / name, args.output_dir / name, systems)
        if counts[name] != len(systems):
            raise AssertionError(f"{name} retained {counts[name]} systems")
    amber = ET.parse(candidate / "matsim" / "amber_times.xml")
    amber.write(
        args.output_dir / "amber_times.xml", encoding="UTF-8", xml_declaration=True,
        standalone=True, pretty_print=True,
    )
    print(json.dumps({
        "status": "pass", "signal_system_count": len(systems),
        "output_dir": str(args.output_dir.resolve()), "xml_system_counts": counts,
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
