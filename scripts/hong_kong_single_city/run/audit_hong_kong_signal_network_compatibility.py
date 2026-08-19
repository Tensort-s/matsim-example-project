#!/usr/bin/env python3
"""Audit signal/link/group/control references against an arbitrary HK network."""

from __future__ import annotations

import argparse
from collections import defaultdict
import gzip
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument("--signal-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse(path: Path) -> ET.Element:
    if path.suffix.lower() == ".gz":
        with gzip.open(path, "rb") as handle:
            return ET.parse(handle).getroot()
    return ET.parse(path).getroot()


def main() -> int:
    args = parse_args()
    files = {
        "systems": args.signal_root / "signal_systems.xml",
        "groups": args.signal_root / "signal_groups.xml",
        "control": args.signal_root / "signal_control.xml",
        "amber": args.signal_root / "amber_times.xml",
        "intergreen": args.signal_root / "intergreen_times.xml",
    }
    for path in (args.network, *files.values()):
        if not path.is_file():
            raise FileNotFoundError(path)
    if args.output.exists():
        raise FileExistsError(args.output)

    network = parse(args.network)
    links: dict[str, tuple[str, str]] = {}
    for element in network.iter():
        if local(element.tag) == "link" and element.get("id"):
            links[element.get("id", "")] = (
                element.get("from", ""), element.get("to", "")
            )

    systems_root = parse(files["systems"])
    signals_by_system: dict[str, set[str]] = defaultdict(set)
    missing_links: set[str] = set()
    invalid_turn_topology: list[dict[str, str]] = []
    turning_moves = 0
    for system in systems_root:
        if local(system.tag) != "signalSystem":
            continue
        system_id = system.get("id", "")
        for signal in system.iter():
            if local(signal.tag) != "signal":
                continue
            signal_id = signal.get("id", "")
            signals_by_system[system_id].add(signal_id)
            incoming = signal.get("linkIdRef", "")
            if incoming not in links:
                missing_links.add(incoming)
            for target in signal.iter():
                if local(target.tag) != "toLink":
                    continue
                outgoing = target.get("refId", "")
                turning_moves += 1
                if outgoing not in links:
                    missing_links.add(outgoing)
                elif incoming in links and links[incoming][1] != links[outgoing][0]:
                    invalid_turn_topology.append({
                        "system_id": system_id,
                        "signal_id": signal_id,
                        "incoming_link": incoming,
                        "outgoing_link": outgoing,
                    })

    groups_root = parse(files["groups"])
    groups_by_system: dict[str, set[str]] = defaultdict(set)
    missing_signal_refs: list[dict[str, str]] = []
    signal_group_memberships = 0
    for system in groups_root:
        if local(system.tag) != "signalSystem":
            continue
        system_id = system.get("refId", "")
        for group in system:
            if local(group.tag) != "signalGroup":
                continue
            group_id = group.get("id", "")
            groups_by_system[system_id].add(group_id)
            for signal in group:
                if local(signal.tag) != "signal":
                    continue
                signal_group_memberships += 1
                signal_id = signal.get("refId", "")
                if signal_id not in signals_by_system.get(system_id, set()):
                    missing_signal_refs.append({
                        "system_id": system_id,
                        "group_id": group_id,
                        "signal_id": signal_id,
                    })

    control_root = parse(files["control"])
    missing_control_systems: set[str] = set()
    missing_control_groups: list[dict[str, str]] = []
    plans = 0
    settings = 0
    for system in control_root:
        if local(system.tag) != "signalSystem":
            continue
        system_id = system.get("refId", "")
        if system_id not in signals_by_system:
            missing_control_systems.add(system_id)
        for element in system.iter():
            name = local(element.tag)
            if name == "signalPlan":
                plans += 1
            elif name == "signalGroupSettings":
                settings += 1
                group_id = element.get("refId", "")
                if group_id not in groups_by_system.get(system_id, set()):
                    missing_control_groups.append({
                        "system_id": system_id,
                        "group_id": group_id,
                    })

    systems = set(signals_by_system)
    group_systems = set(groups_by_system)
    missing_group_systems = sorted(group_systems - systems)
    systems_without_groups = sorted(systems - group_systems)
    passed = not any((
        missing_links,
        invalid_turn_topology,
        missing_signal_refs,
        missing_control_systems,
        missing_control_groups,
        missing_group_systems,
        systems_without_groups,
    ))
    result = {
        "status": "pass" if passed else "fail",
        "network_links": len(links),
        "signal_systems": len(systems),
        "signals": sum(map(len, signals_by_system.values())),
        "turning_moves": turning_moves,
        "signal_groups": sum(map(len, groups_by_system.values())),
        "signal_group_memberships": signal_group_memberships,
        "control_plans": plans,
        "control_group_settings": settings,
        "missing_link_references": sorted(missing_links),
        "invalid_turn_topology": invalid_turn_topology,
        "missing_signal_references": missing_signal_refs,
        "missing_control_systems": sorted(missing_control_systems),
        "missing_control_groups": missing_control_groups,
        "missing_group_systems": missing_group_systems,
        "systems_without_groups": systems_without_groups,
        "inputs": {
            "network": str(args.network),
            "signal_root": str(args.signal_root),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not passed:
        raise SystemExit(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
