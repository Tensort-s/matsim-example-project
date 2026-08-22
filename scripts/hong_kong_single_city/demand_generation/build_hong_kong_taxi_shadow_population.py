"""Build a frozen Hong Kong population with operational-only Taxi shadow requests.

The original selected plans are copied byte-for-byte.  For every selected Taxi
leg that submitted a request in the frozen baseline audit, ``shadow_copies``
one-trip synthetic passengers are appended.  Their departure time is
deterministically resampled inside the parent's 15-minute bucket, while their
origin/destination inherit the parent's already validated car links.  Shadows
are tagged and must be excluded from behavioral demand,
mode-share, and score statistics.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import random
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator, Sequence
from xml.sax.saxutils import quoteattr


SHADOW_ATTRIBUTE = "hkTaxiOperationalShadow"
PARENT_ATTRIBUTE = "hkTaxiShadowParentPersonId"
PARENT_LEG_ATTRIBUTE = "hkTaxiShadowParentLegIndex"
REPLICA_ATTRIBUTE = "hkTaxiShadowReplica"
DEFAULT_SEED = 20260822
DEFAULT_SHADOW_COPIES = 5
BUCKET_SECONDS = 15 * 60


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


@contextmanager
def open_binary(path: Path) -> Iterator[BinaryIO]:
    suffix = path.suffix.lower()
    if suffix == ".gz":
        with gzip.open(path, "rb") as handle:
            yield handle
        return
    if suffix != ".zst":
        with path.open("rb") as handle:
            yield handle
        return
    executable = shutil.which("zstdcat")
    if executable is None:
        raise RuntimeError("Reading .zst requires zstdcat")
    process = subprocess.Popen(
        [executable, str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    assert process.stdout is not None
    try:
        yield process.stdout
    finally:
        process.stdout.close()
    stderr = process.stderr.read().decode("utf-8", "replace") if process.stderr else ""
    code = process.wait()
    if code:
        raise RuntimeError(f"zstdcat failed for {path}: {stderr.strip()}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_time(raw: str | None) -> float:
    if raw is None or not raw.strip():
        raise ValueError("Taxi leg lacks a departure time")
    text = raw.strip()
    if ":" not in text:
        value = float(text)
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"Invalid departure time: {raw}")
        return value
    parts = text.split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid departure time: {raw}")
    hours, minutes, seconds = map(float, parts)
    value = hours * 3600 + minutes * 60 + seconds
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"Invalid departure time: {raw}")
    return value


def format_time(seconds: float) -> str:
    rounded = int(round(seconds))
    hours, remainder = divmod(rounded, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def split_modes(raw: str) -> set[str]:
    return {value for value in re.split(r"[,;\s]+", raw.strip()) if value}


@dataclass(frozen=True)
class Link:
    link_id: str
    from_node: str
    to_node: str
    x: float
    y: float


def parse_car_links(network: Path) -> tuple[dict[str, Link], dict[str, list[str]]]:
    nodes: dict[str, tuple[float, float]] = {}
    links: dict[str, Link] = {}
    incident: dict[str, list[str]] = defaultdict(list)
    with open_binary(network) as handle:
        for event, element in ET.iterparse(handle, events=("start", "end")):
            tag = local_name(element.tag)
            if event == "start" and tag == "node":
                nodes[element.attrib["id"]] = (
                    float(element.attrib["x"]), float(element.attrib["y"])
                )
            elif event == "end" and tag == "link":
                modes = split_modes(element.get("modes", ""))
                if "car" in modes:
                    link_id = element.attrib["id"]
                    from_node = element.attrib["from"]
                    to_node = element.attrib["to"]
                    from_xy = nodes[from_node]
                    to_xy = nodes[to_node]
                    links[link_id] = Link(
                        link_id, from_node, to_node,
                        (from_xy[0] + to_xy[0]) / 2,
                        (from_xy[1] + to_xy[1]) / 2,
                    )
                    incident[from_node].append(link_id)
                    incident[to_node].append(link_id)
                element.clear()
            elif event == "end" and tag == "node":
                element.clear()
    if not links:
        raise ValueError("Network contains no car links")
    return links, {node: sorted(set(values)) for node, values in incident.items()}


def stable_rng(seed: int, *tokens: object) -> random.Random:
    digest = hashlib.sha256(
        (str(seed) + "|" + "|".join(map(str, tokens))).encode("utf-8")
    ).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def nearby_candidates(
    link_id: str,
    links: dict[str, Link],
    incident: dict[str, list[str]],
) -> list[str]:
    link = links.get(link_id)
    if link is None:
        raise ValueError(f"Taxi activity references non-car link: {link_id}")
    candidates = set(incident.get(link.from_node, ())) | set(incident.get(link.to_node, ()))
    candidates.add(link_id)
    # Bound the perturbation so adjacent grade-separated or unusually long
    # connector chains cannot move a request into another district.
    bounded = [
        candidate for candidate in candidates
        if math.hypot(links[candidate].x - link.x, links[candidate].y - link.y) <= 300.0
    ]
    return sorted(bounded or [link_id])


@dataclass(frozen=True)
class ParentTaxiLeg:
    person_id: str
    leg_index: int
    departure_s: float
    origin_link: str
    destination_link: str
    travel_time: str
    distance_m: float


def selected_plan(person: ET.Element) -> ET.Element:
    plans = [child for child in person if local_name(child.tag) == "plan"]
    selected = [plan for plan in plans if plan.get("selected") == "yes"]
    if len(selected) != 1:
        raise ValueError(
            f"Person {person.get('id')} must have exactly one selected plan; found {len(selected)}"
        )
    return selected[0]


def extract_taxi_legs(plans: Path) -> tuple[list[ParentTaxiLeg], int]:
    result: list[ParentTaxiLeg] = []
    persons = 0
    with open_binary(plans) as handle:
        for event, element in ET.iterparse(handle, events=("end",)):
            if local_name(element.tag) != "person":
                continue
            persons += 1
            person_id = element.attrib["id"]
            children = list(selected_plan(element))
            leg_index = 0
            for index, child in enumerate(children):
                if local_name(child.tag) != "leg":
                    continue
                if child.get("mode") == "taxi":
                    if index == 0 or index + 1 >= len(children):
                        raise ValueError(f"Taxi leg is not activity-bounded: {person_id}")
                    origin = children[index - 1]
                    destination = children[index + 1]
                    if local_name(origin.tag) != "activity" or local_name(destination.tag) != "activity":
                        raise ValueError(f"Taxi leg is not activity-bounded: {person_id}")
                    route = next(
                        (item for item in child if local_name(item.tag) == "route"), None
                    )
                    if route is None:
                        raise ValueError(f"Taxi leg lacks route: {person_id}")
                    result.append(ParentTaxiLeg(
                        person_id=person_id,
                        leg_index=leg_index,
                        departure_s=parse_time(child.get("dep_time") or origin.get("end_time")),
                        origin_link=origin.attrib["link"],
                        destination_link=destination.attrib["link"],
                        travel_time=child.get("trav_time") or route.get("trav_time") or "00:00:00",
                        distance_m=float(route.get("distance", "0")),
                    ))
                leg_index += 1
            element.clear()
    return result, persons


def submitted_requests_by_person(audit_path: Path) -> Counter[str]:
    """Count baseline requests by passenger; every audit row was submitted."""
    counts: Counter[str] = Counter()
    with open_binary(audit_path) as binary:
        with io.TextIOWrapper(binary, encoding="utf-8", newline="") as text:
            reader = csv.DictReader(text)
            if reader.fieldnames is None or "person_ids" not in reader.fieldnames:
                raise ValueError("Taxi request audit lacks person_ids column")
            for row_number, row in enumerate(reader, start=2):
                raw = (row.get("person_ids") or "").strip()
                if not raw:
                    raise ValueError(f"Taxi request audit row {row_number} lacks person_ids")
                for person_id in (value.strip() for value in re.split(r"[|;]", raw)):
                    if person_id:
                        counts[person_id] += 1
    if not counts:
        raise ValueError("Taxi request audit contains no submitted requests")
    return counts


def retain_submitted_parent_legs(
    parents: Sequence[ParentTaxiLeg],
    submitted: Counter[str],
) -> tuple[list[ParentTaxiLeg], int]:
    legs_by_person: dict[str, list[ParentTaxiLeg]] = defaultdict(list)
    for parent in parents:
        legs_by_person[parent.person_id].append(parent)
    unknown = sorted(set(submitted) - set(legs_by_person))
    if unknown:
        raise ValueError(
            "Submitted Taxi audit references persons without selected Taxi legs: "
            + ", ".join(unknown[:5])
        )
    retained: list[ParentTaxiLeg] = []
    for person_id, legs in legs_by_person.items():
        requested = submitted.get(person_id, 0)
        if requested > len(legs):
            raise ValueError(
                f"Taxi audit has {requested} requests for {person_id}, but plans have "
                f"only {len(legs)} selected Taxi legs"
            )
        retained.extend(legs[:requested])
    retained.sort(key=lambda leg: (leg.person_id, leg.leg_index))
    return retained, sum(submitted.values())


def attribute(name: str, class_name: str, value: str) -> str:
    return (
        f'<attribute name={quoteattr(name)} class={quoteattr(class_name)}>'
        f"{value}</attribute>"
    )


def shadow_xml(
    parent: ParentTaxiLeg,
    replica: int,
    origin_link: str,
    destination_link: str,
    departure_s: float,
) -> str:
    person_id = f"hk_taxi_shadow_{parent.person_id}_{parent.leg_index}_{replica}"
    attrs = "".join([
        attribute(SHADOW_ATTRIBUTE, "java.lang.Boolean", "true"),
        attribute(PARENT_ATTRIBUTE, "java.lang.String", parent.person_id),
        attribute(PARENT_LEG_ATTRIBUTE, "java.lang.Integer", str(parent.leg_index)),
        attribute(REPLICA_ATTRIBUTE, "java.lang.Integer", str(replica)),
        attribute("role", "java.lang.String", "taxi_operational_shadow"),
        attribute("subpopulation", "java.lang.String", "resident"),
        attribute("expansionWeight", "java.lang.Double", "0.0"),
    ])
    leg_attrs = "".join([
        attribute("routingMode", "java.lang.String", "taxi"),
        attribute("hkTaxiClassificationSource", "java.lang.String", "freeze44k_shadow6_30pct_v1"),
        attribute(SHADOW_ATTRIBUTE, "java.lang.Boolean", "true"),
    ])
    return (
        f"<person id={quoteattr(person_id)}><attributes>{attrs}</attributes>"
        '<plan score="0.0" selected="yes">'
        f'<activity type="home" link={quoteattr(origin_link)} '
        f'end_time={quoteattr(format_time(departure_s))}/>'
        f'<leg mode="taxi" dep_time={quoteattr(format_time(departure_s))} '
        f'trav_time={quoteattr(parent.travel_time)}><attributes>{leg_attrs}</attributes>'
        f'<route type="generic" start_link={quoteattr(origin_link)} '
        f'end_link={quoteattr(destination_link)} trav_time={quoteattr(parent.travel_time)} '
        f'distance={quoteattr(str(parent.distance_m))}/></leg>'
        f'<activity type="home" link={quoteattr(destination_link)}/>'
        "</plan></person>\n"
    )


def write_population(
    source: Path,
    destination: Path,
    shadows: Sequence[str],
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(destination)
    closing = b"</population>"
    with open_binary(source) as reader, destination.open("xb") as raw_writer:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_writer, mtime=0) as writer:
            pending = b""
            found = False
            while True:
                block = reader.read(8 * 1024 * 1024)
                if not block:
                    break
                pending += block
                position = pending.find(closing)
                if position >= 0:
                    writer.write(pending[:position])
                    tail = pending[position + len(closing):]
                    if tail.strip():
                        raise ValueError("Unexpected content after population closing tag")
                    found = True
                    break
                keep = max(0, len(pending) - len(closing) + 1)
                writer.write(pending[:keep])
                pending = pending[keep:]
            if not found:
                raise ValueError("Population closing tag not found")
            for value in shadows:
                writer.write(value.encode("utf-8"))
            writer.write(closing + b"\n")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plans", type=Path, required=True)
    parser.add_argument("--network", type=Path, required=True)
    parser.add_argument("--submitted-request-audit", type=Path, required=True)
    parser.add_argument("--output-plans", type=Path, required=True)
    parser.add_argument("--output-audit", type=Path, required=True)
    parser.add_argument("--shadow-copies", type=int, default=DEFAULT_SHADOW_COPIES)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict:
    if args.shadow_copies < 1:
        raise ValueError("--shadow-copies must be positive")
    if (
        not args.plans.is_file()
        or not args.network.is_file()
        or not args.submitted_request_audit.is_file()
    ):
        raise FileNotFoundError("Plans/network/submitted-request-audit input missing")
    links, incident = parse_car_links(args.network)
    all_parents, original_persons = extract_taxi_legs(args.plans)
    submitted = submitted_requests_by_person(args.submitted_request_audit)
    parents, submitted_request_rows = retain_submitted_parent_legs(all_parents, submitted)
    shadows: list[str] = []
    counters: Counter[str] = Counter()
    for parent in parents:
        # Parent links have already survived the physical-Taxi baseline.  A
        # merely adjacent link is not necessarily reachable on a directed road
        # graph, so spatial perturbation is deliberately prohibited here.
        nearby_candidates(parent.origin_link, links, incident)
        nearby_candidates(parent.destination_link, links, incident)
        bucket_start = math.floor(parent.departure_s / BUCKET_SECONDS) * BUCKET_SECONDS
        for replica in range(1, args.shadow_copies + 1):
            rng = stable_rng(args.seed, parent.person_id, parent.leg_index, replica)
            origin = parent.origin_link
            destination = parent.destination_link
            departure = bucket_start + rng.randint(0, BUCKET_SECONDS - 1)
            if origin == parent.origin_link:
                counters["origin_unchanged"] += 1
            else:
                counters["origin_perturbed"] += 1
            if destination == parent.destination_link:
                counters["destination_unchanged"] += 1
            else:
                counters["destination_perturbed"] += 1
            shadows.append(shadow_xml(parent, replica, origin, destination, departure))
    write_population(args.plans, args.output_plans, shadows)
    audit = {
        "status": "validated",
        "created_by": "build_hong_kong_taxi_shadow_population.py",
        "inputs": {
            "plans": str(args.plans.resolve()),
            "plans_sha256": sha256(args.plans),
            "network": str(args.network.resolve()),
            "network_sha256": sha256(args.network),
            "submitted_request_audit": str(args.submitted_request_audit.resolve()),
            "submitted_request_audit_sha256": sha256(args.submitted_request_audit),
        },
        "parameters": {
            "shadow_copies_per_parent_taxi_leg": args.shadow_copies,
            "operational_multiplier": args.shadow_copies + 1,
            "seed": args.seed,
            "time_bucket_seconds": BUCKET_SECONDS,
            "spatial_perturbation_m": 0.0,
        },
        "counts": {
            "original_persons": original_persons,
            "original_taxi_legs": len(all_parents),
            "submitted_parent_taxi_legs": len(parents),
            "baseline_submitted_request_rows": submitted_request_rows,
            "unreached_parent_taxi_legs": len(all_parents) - len(parents),
            "shadow_persons": len(shadows),
            "output_persons": original_persons + len(shadows),
            "output_taxi_legs": len(all_parents) + len(shadows),
            **dict(sorted(counters.items())),
        },
        "outputs": {
            "plans": str(args.output_plans.resolve()),
            "plans_sha256": sha256(args.output_plans),
        },
        "contracts": {
            "original_population_bytes_preserved_before_closing_tag": True,
            "shadow_expansion_weight_zero": True,
            "shadow_behavioral_statistics_excluded": True,
            "shadow_departure_preserves_parent_15min_bucket": True,
            "shadow_od_inherits_parent_validated_links": True,
            "shadows_only_for_baseline_submitted_parent_requests": True,
        },
    }
    args.output_audit.parent.mkdir(parents=True, exist_ok=True)
    args.output_audit.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return audit


def main() -> None:
    audit = run(parse_args())
    print(json.dumps(audit["counts"], sort_keys=True))


if __name__ == "__main__":
    main()
