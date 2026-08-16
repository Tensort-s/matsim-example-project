#!/usr/bin/env python3
"""Add a TPDM Volume 4 saturation-flow floor to an existing HK network.

The source network is treated as the already-adopted maximum of the two
existing capacity candidate schemes.  For every physical road link, this
builder adds the independent TPDM Volume 4 lane saturation candidate and
writes a new immutable network whose capacity is the rounded-up maximum.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable
import xml.etree.ElementTree as ET


DEFAULT_LANE_WIDTH_M = 3.25
DEFAULT_ROUNDING_VPH = 50.0
DEFAULT_FLOW_CAPACITY_FACTOR = 0.1
ROAD_MODES = frozenset({"car", "bus", "gmb", "school_bus"})
ATTRIBUTE = re.compile(r'([A-Za-z][A-Za-z0-9_]*)="([^"]*)"')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-network", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--lane-width-m", type=float, default=DEFAULT_LANE_WIDTH_M,
        help="Common directional lane width used when link-level width is unavailable.",
    )
    parser.add_argument(
        "--capacity-rounding-vph", type=float, default=DEFAULT_ROUNDING_VPH,
    )
    parser.add_argument(
        "--flow-capacity-factor", type=float,
        default=DEFAULT_FLOW_CAPACITY_FACTOR,
        help="Recorded only for the equivalent-QSim delta; network capacities stay full scale.",
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


def replace_capacity(line: str, capacity: float) -> str:
    return re.sub(
        r'(capacity=")[^"]*(")',
        rf"\g<1>{capacity:.6f}\g<2>",
        line,
        count=1,
    )


def round_up(value: float, increment: float) -> float:
    return math.ceil((value - 1e-9) / increment) * increment


def tpdm_v4_capacity(lanes: int, lane_width_m: float) -> tuple[float, float, float]:
    if lanes < 1:
        raise ValueError(f"Directional lane count must be positive: {lanes}")
    nearside = 1940.0 + 100.0 * (lane_width_m - 3.25)
    other = 2080.0 + 100.0 * (lane_width_m - 3.25)
    total = nearside + (lanes - 1) * other
    return nearside, other, total


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def without_capacity(line: str) -> bytes:
    normalized = re.sub(r' capacity="[^"]*"', "", line)
    return normalized.encode("utf-8")


def write_network_and_audit(
    source: Path,
    destination: Path,
    audit_csv: Path,
    lane_width_m: float,
    rounding_vph: float,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    source_structure = hashlib.sha256()
    destination_structure = hashlib.sha256()
    total_links = 0
    physical_road_links = 0
    nonroad_links = 0
    changed_links = 0
    gzip_kwargs = {"filename": "", "mtime": 0}

    with gzip.open(source, "rt", encoding="utf-8", newline="") as input_handle:
        with destination.open("xb") as raw_output:
            with gzip.GzipFile(fileobj=raw_output, mode="wb", **gzip_kwargs) as compressed:
                for line in input_handle:
                    output_line = line
                    if "<link " in line:
                        total_links += 1
                        item = attributes(line)
                        required = {"id", "capacity", "permlanes", "modes"}
                        if not required.issubset(item):
                            raise ValueError(f"Malformed MATSim link line: {line.rstrip()}")
                        modes = frozenset(filter(None, item["modes"].split(",")))
                        is_physical_road = bool(modes & ROAD_MODES)
                        if is_physical_road:
                            physical_road_links += 1
                            lanes_float = float(item["permlanes"])
                            lanes = int(round(lanes_float))
                            if not math.isclose(lanes_float, lanes, abs_tol=1e-9):
                                raise ValueError(
                                    f"TPDM lane formula requires an integer lane count: "
                                    f"{item['id']}={lanes_float}"
                                )
                            old_capacity = float(item["capacity"])
                            if not math.isfinite(old_capacity) or old_capacity <= 0:
                                raise ValueError(
                                    f"Invalid old capacity for {item['id']}: {old_capacity}"
                                )
                            nearside, other, tpdm = tpdm_v4_capacity(
                                lanes, lane_width_m
                            )
                            selected_raw = max(old_capacity, tpdm)
                            new_capacity = round_up(selected_raw, rounding_vph)
                            changed = not math.isclose(
                                old_capacity, new_capacity, abs_tol=1e-7
                            )
                            if changed:
                                changed_links += 1
                                output_line = replace_capacity(line, new_capacity)
                            if math.isclose(old_capacity, tpdm, abs_tol=1e-7):
                                controlling = "existing_two_candidate+tpdm_v4_tie"
                            elif old_capacity > tpdm:
                                controlling = "existing_two_candidate"
                            else:
                                controlling = "tpdm_v4"
                            delta = new_capacity - old_capacity
                            rows.append(
                                {
                                    "link_id": item["id"],
                                    "modes": item["modes"],
                                    "car_allowed": "car" in modes,
                                    "directional_lanes": lanes,
                                    "lane_width_m": lane_width_m,
                                    "old_two_candidate_capacity_vph": old_capacity,
                                    "tpdm_v4_nearside_vph": nearside,
                                    "tpdm_v4_other_lane_vph": other,
                                    "tpdm_v4_capacity_vph": tpdm,
                                    "selected_raw_capacity_vph": selected_raw,
                                    "new_capacity_vph": new_capacity,
                                    "capacity_delta_vph": delta,
                                    "capacity_delta_pct": 100.0 * delta / old_capacity,
                                    "controlling_candidate": controlling,
                                }
                            )
                        else:
                            nonroad_links += 1
                    source_structure.update(without_capacity(line))
                    destination_structure.update(without_capacity(output_line))
                    compressed.write(output_line.encode("utf-8"))

    with audit_csv.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    if source_structure.hexdigest() != destination_structure.hexdigest():
        raise RuntimeError("Network content other than capacity changed.")
    with gzip.open(destination, "rb") as handle:
        ET.parse(handle)
    return {
        "total_links": total_links,
        "physical_road_links": physical_road_links,
        "nonroad_links": nonroad_links,
        "changed_links": changed_links,
        "unchanged_physical_road_links": physical_road_links - changed_links,
        "source_noncapacity_sha256": source_structure.hexdigest(),
        "destination_noncapacity_sha256": destination_structure.hexdigest(),
        "rows": rows,
    }


def group_summary(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    items = list(rows)
    old = [float(row["old_two_candidate_capacity_vph"]) for row in items]
    new = [float(row["new_capacity_vph"]) for row in items]
    deltas = [float(row["capacity_delta_vph"]) for row in items]
    changed = [value for value in deltas if value > 1e-7]
    old_sum = sum(old)
    new_sum = sum(new)
    return {
        "links": len(items),
        "changed_links": len(changed),
        "changed_share": len(changed) / len(items) if items else 0.0,
        "old_capacity_sum_vph": old_sum,
        "new_capacity_sum_vph": new_sum,
        "capacity_sum_delta_vph": new_sum - old_sum,
        "capacity_sum_delta_pct": (
            100.0 * (new_sum - old_sum) / old_sum if old_sum else None
        ),
        "old_capacity_mean_vph": old_sum / len(items) if items else None,
        "new_capacity_mean_vph": new_sum / len(items) if items else None,
        "changed_delta_mean_vph": sum(changed) / len(changed) if changed else 0.0,
        "changed_delta_p50_vph": percentile(changed, 0.50),
        "changed_delta_p95_vph": percentile(changed, 0.95),
        "changed_delta_max_vph": max(changed, default=0.0),
    }


def lane_summary(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    items = list(rows)
    result: dict[str, Any] = {}
    for lanes in sorted({int(row["directional_lanes"]) for row in items}):
        group = [row for row in items if int(row["directional_lanes"]) == lanes]
        old_sum = sum(
            float(row["old_two_candidate_capacity_vph"]) for row in group
        )
        new_sum = sum(float(row["new_capacity_vph"]) for row in group)
        result[str(lanes)] = {
            "links": len(group),
            "tpdm_v4_controlling_links": sum(
                row["controlling_candidate"] == "tpdm_v4" for row in group
            ),
            "changed_links": sum(
                float(row["capacity_delta_vph"]) > 1e-7 for row in group
            ),
            "old_capacity_mean_vph": old_sum / len(group),
            "new_capacity_mean_vph": new_sum / len(group),
            "capacity_sum_delta_pct": 100.0 * (new_sum - old_sum) / old_sum,
        }
    return result


def main() -> int:
    args = parse_args()
    if not args.input_network.is_file():
        raise FileNotFoundError(args.input_network)
    if args.output_dir.exists():
        raise FileExistsError(f"Output directory must not exist: {args.output_dir}")
    if args.lane_width_m <= 0:
        raise ValueError("--lane-width-m must be positive")
    if args.capacity_rounding_vph <= 0:
        raise ValueError("--capacity-rounding-vph must be positive")
    if not 0 < args.flow_capacity_factor <= 1:
        raise ValueError("--flow-capacity-factor must be in (0, 1]")

    args.output_dir.mkdir(parents=True)
    output_network = args.output_dir / "network_tpdm_v4_three_candidate.xml.gz"
    audit_csv = args.output_dir / "capacity_link_audit.csv"
    result = write_network_and_audit(
        args.input_network,
        output_network,
        audit_csv,
        args.lane_width_m,
        args.capacity_rounding_vph,
    )
    rows = result.pop("rows")
    all_summary = group_summary(rows)
    car_summary = group_summary(row for row in rows if row["car_allowed"])
    transit_only_summary = group_summary(
        row for row in rows if not row["car_allowed"]
    )
    summary = {
        "status": "candidate_generated_not_adopted",
        "method": {
            "existing_capacity_interpretation": (
                "source capacity is the maximum of the two existing candidate schemes"
            ),
            "tpdm_v4_nearside_vph": "1940 + 100 * (W - 3.25)",
            "tpdm_v4_other_lane_vph": "2080 + 100 * (W - 3.25)",
            "tpdm_v4_direction_vph": (
                "nearside + (directional_lanes - 1) * other_lane"
            ),
            "new_capacity_vph": (
                "round_up(max(existing_two_candidate_capacity, tpdm_v4_capacity), 50)"
            ),
            "lane_width_m": args.lane_width_m,
            "capacity_rounding_vph": args.capacity_rounding_vph,
            "network_capacity_scale": "full_scale",
            "flow_capacity_factor_for_equivalent_reporting": (
                args.flow_capacity_factor
            ),
        },
        "source": {
            "network": str(args.input_network),
            "network_sha256": sha256(args.input_network),
        },
        "output": {
            "network": str(output_network),
            "network_sha256": sha256(output_network),
            "capacity_link_audit": str(audit_csv),
        },
        "structure_qa": result,
        "capacity_change": {
            "all_physical_road_links": all_summary,
            "car_allowed_links": car_summary,
            "transit_only_road_links": transit_only_summary,
            "qsim_equivalent_capacity_sum_delta_vph": (
                all_summary["capacity_sum_delta_vph"]
                * args.flow_capacity_factor
            ),
            "controlling_candidate_counts": dict(Counter(
                row["controlling_candidate"] for row in rows
            )),
            "by_directional_lanes": lane_summary(rows),
        },
        "invariants": {
            "xml_parses": True,
            "only_capacity_attribute_changed": (
                result["source_noncapacity_sha256"]
                == result["destination_noncapacity_sha256"]
            ),
            "all_new_capacities_ge_old": all(
                row["new_capacity_vph"]
                >= row["old_two_candidate_capacity_vph"]
                for row in rows
            ),
            "nonroad_links_unchanged": True,
            "no_network_capacity_prescaling": True,
        },
    }
    summary_path = args.output_dir / "tpdm_v4_three_candidate_summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
