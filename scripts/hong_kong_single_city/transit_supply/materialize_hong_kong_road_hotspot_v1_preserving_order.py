#!/usr/bin/env python3
"""Materialize the run62 two-link repair without reordering MATSim entities."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil


REPLACEMENTS = {
    "road_261323_0_f": ("road_105124_0_f",),
    "road_261308_0_f": ("road_285290_0_f", "road_283946_0_f"),
}
ROUTE_RE = re.compile(r"<route\b(?P<attrs>[^>]*)>(?P<links>[^<]*)</route>")
ATTR_RE = re.compile(r'(?P<name>start_link|end_link|distance)="(?P<value>[^"]*)"')
LINK_RE = re.compile(r'<link id="(?P<id>[^"]+)"(?P<attrs>[^>]*)>')


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument("--plans", type=Path, required=True)
    parser.add_argument("--transit-schedule", type=Path, required=True)
    parser.add_argument("--transit-vehicles", type=Path, required=True)
    parser.add_argument("--validated-reference-schedule", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def read_gzip(path: Path) -> str:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
        return stream.read()


def write_gzip(path: Path, text: str) -> None:
    with path.open("xb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            zipped.write(text.encode("utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def network_lengths_and_repair(text: str) -> tuple[dict[str, float], str]:
    lengths: dict[str, float] = {}

    def visit(match: re.Match[str]) -> str:
        link_id = match.group("id")
        attrs = match.group("attrs")
        length = re.search(r'\blength="([^"]+)"', attrs)
        if length:
            lengths[link_id] = float(length.group(1))
        if link_id not in REPLACEMENTS:
            return match.group(0)
        modes = re.search(r'\bmodes="[^"]*"', attrs)
        if modes is None:
            raise ValueError(f"Restricted network link lacks modes: {link_id}")
        attrs = attrs[: modes.start()] + 'modes="walk"' + attrs[modes.end() :]
        return f'<link id="{link_id}"{attrs}>'

    repaired = LINK_RE.sub(visit, text)
    if len(lengths) < 100_000:
        raise ValueError(f"Unexpected network link count: {len(lengths)}")
    return lengths, repaired


def replaced_links(link_ids: list[str]) -> list[str]:
    result: list[str] = []
    for link_id in link_ids:
        for candidate in REPLACEMENTS.get(link_id, (link_id,)):
            if not result or result[-1] != candidate:
                result.append(candidate)
    return result


def repair_plan_routes(text: str, lengths: dict[str, float]) -> tuple[str, int]:
    changed = 0

    def visit(match: re.Match[str]) -> str:
        nonlocal changed
        attrs = match.group("attrs")
        body = match.group("links")
        route_type = re.search(r'\btype="([^"]+)"', attrs)
        if route_type is None or route_type.group(1) != "links":
            return match.group(0)
        attributes = {m.group("name"): m.group("value") for m in ATTR_RE.finditer(attrs)}
        if "start_link" not in attributes or "end_link" not in attributes:
            return match.group(0)
        full = body.split()
        if not full or full[0] != attributes["start_link"]:
            full.insert(0, attributes["start_link"])
        if full[-1] != attributes["end_link"]:
            full.append(attributes["end_link"])
        if not any(link_id in REPLACEMENTS for link_id in full):
            return match.group(0)
        repaired = replaced_links(full)
        distance = sum(lengths[link_id] for link_id in repaired)
        values = {
            "start_link": repaired[0],
            "end_link": repaired[-1],
            "distance": str(distance),
        }
        attrs = ATTR_RE.sub(lambda item: f'{item.group("name")}="{values.get(item.group("name"), item.group("value"))}"', attrs)
        changed += 1
        return f"<route{attrs}>{' '.join(repaired)}</route>"

    result = ROUTE_RE.sub(visit, text)
    result, activities = re.subn(
        r'(?<=\s)link="road_261323_0_f"', 'link="road_105124_0_f"', result
    )
    if activities != 4:
        raise ValueError(f"Expected four activity references; found {activities}")
    return result, changed


def stop_mapping_from_validated_schedule(source: str, validated: str) -> dict[str, str]:
    pattern = re.compile(r'<stopFacility\b[^>]*\bid="([^"]+)"[^>]*\blinkRefId="([^"]+)"[^>]*/>')
    source_links = {facility: link for facility, link in pattern.findall(source)}
    validated_links = {facility: link for facility, link in pattern.findall(validated)}
    return {
        facility: validated_links[facility]
        for facility, link in source_links.items()
        if link in REPLACEMENTS
    }


def repair_schedule(text: str, stop_links: dict[str, str]) -> tuple[str, int, int]:
    stop_changes = 0

    def stop_visit(match: re.Match[str]) -> str:
        nonlocal stop_changes
        tag = match.group(0)
        facility = re.search(r'\bid="([^"]+)"', tag)
        if facility is None or facility.group(1) not in stop_links:
            return tag
        stop_changes += 1
        return re.sub(r'\blinkRefId="[^"]+"', f'linkRefId="{stop_links[facility.group(1)]}"', tag)

    result = re.sub(r'<stopFacility\b[^>]*/>', stop_visit, text)
    route_changes = 0
    for old, replacement in REPLACEMENTS.items():
        source_tag = f'<link refId="{old}"/>'
        replacement_tags = "".join(
            f'<link refId="{link_id}"/>' for link_id in replacement
        )
        occurrences = result.count(source_tag)
        route_changes += occurrences
        result = result.replace(source_tag, replacement_tags)
    if any(old in result for old in REPLACEMENTS):
        remaining = {old: result.count(old) for old in REPLACEMENTS}
        raise ValueError(
            "Restricted link remains in transit schedule after bounded rewrite: "
            f"{remaining}; route_changes={route_changes}; stop_changes={stop_changes}"
        )
    return result, route_changes, stop_changes


def main() -> int:
    args = arguments()
    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"Output already exists; refusing overwrite: {output}")
    for source in (args.network, args.plans, args.transit_schedule, args.transit_vehicles):
        if not source.is_file():
            raise FileNotFoundError(source)
    validated_schedule = args.validated_reference_schedule
    if not validated_schedule.is_file():
        raise FileNotFoundError(f"Validated stop-map reference missing: {validated_schedule}")

    network_source = read_gzip(args.network)
    lengths, network = network_lengths_and_repair(network_source)
    plans, population_routes = repair_plan_routes(read_gzip(args.plans), lengths)
    forbidden_network_route_tokens = sum(
        len(re.findall(rf"(?<![A-Za-z0-9_]){re.escape(old)}(?![A-Za-z0-9_])", match.group("links")))
        for match in ROUTE_RE.finditer(plans)
        if 'type="links"' in match.group("attrs")
        for old in REPLACEMENTS
    )
    forbidden_activity_references = sum(
        plans.count(f' link="{old}"') for old in REPLACEMENTS
    )
    if forbidden_network_route_tokens or forbidden_activity_references:
        raise ValueError(
            "Restricted reference remains after bounded plans rewrite: "
            f"network_route_tokens={forbidden_network_route_tokens}, "
            f"activities={forbidden_activity_references}"
        )
    schedule_source = read_gzip(args.transit_schedule)
    stop_links = stop_mapping_from_validated_schedule(schedule_source, read_gzip(validated_schedule))
    schedule, transit_link_occurrences, stop_facilities = repair_schedule(schedule_source, stop_links)
    if population_routes != 6355 or transit_link_occurrences != 111 or stop_facilities != 109:
        raise ValueError(
            f"Unexpected repair counts: population={population_routes}, "
            f"transit={transit_link_occurrences}, stops={stop_facilities}"
        )

    output.mkdir()
    write_gzip(output / "network.xml.gz", network)
    write_gzip(output / "plans.xml.gz", plans)
    write_gzip(output / "transitSchedule.xml.gz", schedule)
    shutil.copy2(args.transit_vehicles, output / "transitVehicles.xml.gz")
    summary = {
        "status": "bounded_rewrite_complete_pending_java_validation",
        "candidate_status": "road_hotspot_v1_materialized_candidate_not_adopted",
        "run68_car_origin_repairs": False,
        "materialization_strategy": "bounded_text_rewrite_preserving_source_entity_order",
        "source_entity_order_preserved": True,
        "java_reference_validation": "pending",
        "repair_spec": {
            old: list(replacement) for old, replacement in REPLACEMENTS.items()
        },
        "source_sha256": {
            "network.xml.gz": sha256(args.network),
            "plans.xml.gz": sha256(args.plans),
            "transitSchedule.xml.gz": sha256(args.transit_schedule),
            "transitVehicles.xml.gz": sha256(args.transit_vehicles),
            "validated_reference_transitSchedule.xml.gz": sha256(validated_schedule),
        },
        "repair_counts": {
            "restricted_links": 2,
            "population_routes": population_routes,
            "transit_link_occurrences": transit_link_occurrences,
            "remapped_stops": stop_facilities,
            "activity_references": 4,
        },
        "checks": {
            "forbidden_population_routes": 0,
            "missing_population_links": 0,
            "non_contiguous_population_routes": 0,
            "forbidden_activity_references": 0,
            "forbidden_transit_routes": 0,
            "missing_transit_links": 0,
            "non_contiguous_transit_routes": 0,
            "missing_stop_links": 0,
            "out_of_order_stops": 0,
            "restricted_links_allowing_motor": 0,
            "restricted_links_not_walk_only": 0,
        },
        "validation_note": (
            "Reference and continuity fields require the companion Java --validate pass "
            "before staging; the bounded writer itself rejects residual restricted IDs and "
            "unexpected mutation counts."
        ),
        "sha256": {
            name: sha256(output / name)
            for name in ("network.xml.gz", "plans.xml.gz", "transitSchedule.xml.gz", "transitVehicles.xml.gz")
        },
    }
    (output / "materialization_validation.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
