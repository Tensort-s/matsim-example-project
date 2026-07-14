"""Re-estimate Fuzhou MATSim road link capacity from OSM lane tags.

This script keeps the integrated MATSim network topology untouched: node ids,
link ids, link geometry, routes, and transit schedules remain compatible.  It
only updates ``capacity`` and ``permlanes`` on road links, using OSM lane
metadata when available and highway-type dominant lane defaults otherwise.

Metro pt-only links keep their high capacity. Synthetic bus trajectory links
receive conservative explicit capacities to avoid artificial connector
bottlenecks without creating unrealistic high-capacity local roads.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import re
import shutil
import statistics
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NETWORK = (
    PROJECT_ROOT
    / "data"
    / "transit"
    / "fuzhou_transit_matsim_integrated_20260709"
    / "network_with_car_bus_metro.xml.gz"
)
DEFAULT_OSM_ROADS = PROJECT_ROOT / "data" / "osm" / "fuzhou_city_23" / "fuzhou_city_23_osm_roads.geojson"
DEFAULT_SCHEDULE = (
    PROJECT_ROOT
    / "data"
    / "transit"
    / "fuzhou_transit_matsim_integrated_20260709"
    / "transitSchedule.xml.gz"
)
DEFAULT_VEHICLES = (
    PROJECT_ROOT
    / "data"
    / "transit"
    / "fuzhou_transit_matsim_integrated_20260709_ptcap20"
    / "transitVehicles.xml.gz"
)
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT
    / "data"
    / "transit"
    / "fuzhou_transit_matsim_integrated_20260709_capacity_lanes_v2"
)
DEFAULT_REFERENCE_OUTPUT = PROJECT_ROOT / "output-fuzhou-transit-mode-choice-5pct-roadcap10-reroute-50"


CAR_HIGHWAYS = {
    "motorway",
    "motorway_link",
    "trunk",
    "trunk_link",
    "primary",
    "primary_link",
    "secondary",
    "secondary_link",
    "tertiary",
    "tertiary_link",
    "unclassified",
    "residential",
    "living_street",
    "service",
}

PER_LANE_CAPACITY = {
    "motorway": 2200.0,
    "motorway_link": 1800.0,
    "trunk": 2000.0,
    "trunk_link": 1500.0,
    "primary": 1800.0,
    "primary_link": 1200.0,
    "secondary": 1500.0,
    "secondary_link": 900.0,
    "tertiary": 1200.0,
    "tertiary_link": 700.0,
    "unclassified": 900.0,
    "residential": 700.0,
    "living_street": 300.0,
    "service": 400.0,
}

# Per-direction defaults, chosen from the dominant known lane count by highway
# class in the local Fuzhou OSM extract, with conservative fallbacks for sparse
# classes and links.
DEFAULT_DIRECTION_LANES = {
    "motorway": 3.0,
    "trunk": 3.0,
    "primary": 3.0,
    "secondary": 2.0,
    "tertiary": 1.0,
    "unclassified": 1.0,
    "residential": 1.0,
    "service": 1.0,
    "living_street": 1.0,
    "motorway_link": 1.0,
    "trunk_link": 1.0,
    "primary_link": 1.0,
    "secondary_link": 1.0,
    "tertiary_link": 1.0,
}

LANE_CAP_BY_HIGHWAY = {
    "motorway": 5.0,
    "trunk": 5.0,
    "primary": 4.0,
    "secondary": 4.0,
    "tertiary": 3.0,
    "unclassified": 3.0,
    "residential": 3.0,
    "service": 3.0,
    "living_street": 3.0,
    "motorway_link": 3.0,
    "trunk_link": 3.0,
    "primary_link": 3.0,
    "secondary_link": 3.0,
    "tertiary_link": 3.0,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", type=Path, default=DEFAULT_NETWORK)
    parser.add_argument("--osm-roads", type=Path, default=DEFAULT_OSM_ROADS)
    parser.add_argument("--schedule", type=Path, default=DEFAULT_SCHEDULE)
    parser.add_argument("--vehicles", type=Path, default=DEFAULT_VEHICLES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--reference-output-dir",
        type=Path,
        default=DEFAULT_REFERENCE_OUTPUT,
        help="Optional previous MATSim output used to flag bus-priority candidate bottleneck links.",
    )
    return parser.parse_args()


def ensure_exists(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")


def safe_float(value: object, default: float = math.nan) -> float:
    try:
        if value is None:
            return default
        text = str(value).strip()
        if not text:
            return default
        return float(text)
    except Exception:
        return default


def hstore_tag(value: object, key: str) -> str | None:
    if value is None or pd.isna(value):
        return None
    match = re.search(r'"' + re.escape(key) + r'"\s*=>\s*"([^"]+)"', str(value))
    return match.group(1).strip() if match else None


def numeric_tag(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    match = re.match(r"^(\d+(?:\.\d+)?)$", text)
    if not match:
        return None
    number = float(match.group(1))
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def parse_oneway(row: pd.Series) -> int:
    """Return 1 for forward-only, -1 for reverse-only, 0 for bidirectional."""
    explicit = row.get("oneway_tag")
    text = str(explicit if explicit is not None else "").lower()
    if text == "-1":
        return -1
    if text in {"yes", "true", "1"}:
        return 1
    if text in {"no", "false", "0"}:
        return 0
    other_tags = str(row.get("other_tags") or "").lower()
    if '"oneway"=>"-1"' in other_tags or "oneway=-1" in other_tags:
        return -1
    if (
        '"oneway"=>"yes"' in other_tags
        or '"oneway"=>"true"' in other_tags
        or '"oneway"=>"1"' in other_tags
        or "oneway=yes" in other_tags
        or "oneway=true" in other_tags
    ):
        return 1
    return 0


def load_osm_road_lookup(osm_roads: Path) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    roads = gpd.read_file(osm_roads)
    if roads.crs is None:
        roads = roads.set_crs("EPSG:4326")
    # Match the row filtering and reset_index order used by build_network().
    roads = roads.to_crs("EPSG:32650")
    roads = roads[roads.geometry.notna() & ~roads.geometry.is_empty].copy()
    roads = roads[roads.geometry.geom_type == "LineString"].copy()
    roads["highway"] = roads["highway"].astype(str).str.lower()
    roads = roads[roads["highway"].isin(CAR_HIGHWAYS)].copy().reset_index(drop=True)

    for key in ["lanes", "lanes:forward", "lanes:backward", "oneway"]:
        roads[f"{key}_tag"] = roads["other_tags"].map(lambda x, k=key: hstore_tag(x, k))
    roads["lanes_num"] = roads["lanes_tag"].map(numeric_tag)
    roads["lanes_forward_num"] = roads["lanes:forward_tag"].map(numeric_tag)
    roads["lanes_backward_num"] = roads["lanes:backward_tag"].map(numeric_tag)
    roads["oneway_direction"] = roads.apply(parse_oneway, axis=1)

    lookup: dict[int, dict[str, Any]] = {}
    for idx, row in roads.iterrows():
        lookup[int(idx)] = {
            "highway": row["highway"],
            "lanes": row["lanes_num"],
            "lanes_forward": row["lanes_forward_num"],
            "lanes_backward": row["lanes_backward_num"],
            "oneway_direction": int(row["oneway_direction"]),
            "osm_id": row.get("osm_id"),
            "name": row.get("name"),
            "other_tags": row.get("other_tags"),
        }

    coverage_rows = []
    for highway, sub in roads.groupby("highway"):
        has_any = sub[["lanes_num", "lanes_forward_num", "lanes_backward_num"]].notna().any(axis=1)
        coverage_rows.append(
            {
                "highway": highway,
                "rows": int(len(sub)),
                "with_lanes": int(sub["lanes_num"].notna().sum()),
                "with_forward_backward": int(
                    sub[["lanes_forward_num", "lanes_backward_num"]].notna().any(axis=1).sum()
                ),
                "with_any_lane_info": int(has_any.sum()),
                "coverage_pct": float(has_any.mean() * 100 if len(sub) else 0.0),
            }
        )
    metadata = {
        "osm_road_rows_after_filter": int(len(roads)),
        "lane_coverage_by_highway": sorted(coverage_rows, key=lambda r: (-r["rows"], r["highway"])),
    }
    return lookup, metadata


LINK_ID_RE = re.compile(r"^l_(\d+)_(\d+)_(f|r)$")


def direction_from_link_id(link_id: str) -> str | None:
    match = LINK_ID_RE.match(link_id)
    return match.group(3) if match else None


def road_idx_from_link_id(link_id: str) -> int | None:
    match = LINK_ID_RE.match(link_id)
    return int(match.group(1)) if match else None


def cap_lanes(highway: str, lanes: float) -> float:
    cap = LANE_CAP_BY_HIGHWAY.get(highway, 3.0)
    return min(max(lanes, 1.0), cap)


def positive_number(value: object) -> bool:
    try:
        number = float(value)
        return math.isfinite(number) and number > 0
    except Exception:
        return False


def infer_direction_lanes(road: dict[str, Any], direction: str | None) -> tuple[float, str]:
    highway = str(road.get("highway") or "").lower()
    lanes_forward = road.get("lanes_forward")
    lanes_backward = road.get("lanes_backward")
    lanes_total = road.get("lanes")
    oneway = int(road.get("oneway_direction") or 0)

    if direction == "f" and positive_number(lanes_forward):
        return cap_lanes(highway, float(lanes_forward)), "osm_lanes_forward"
    if direction == "r" and positive_number(lanes_backward):
        return cap_lanes(highway, float(lanes_backward)), "osm_lanes_backward"

    if positive_number(lanes_total):
        lanes_total = float(lanes_total)
        if oneway != 0:
            return cap_lanes(highway, lanes_total), "osm_lanes_oneway_total"
        return cap_lanes(highway, max(1.0, lanes_total / 2.0)), "osm_lanes_bidirectional_half"

    return cap_lanes(highway, DEFAULT_DIRECTION_LANES.get(highway, 1.0)), "dominant_highway_default"


def classify_link(link_id: str, modes: str) -> str:
    if link_id.startswith("metro_link_"):
        return "metro_pt_only"
    if link_id.startswith("syn_bus_connector_"):
        return "synthetic_bus_connector"
    if link_id.startswith("syn_bus_link_"):
        return "synthetic_bus_trajectory"
    if road_idx_from_link_id(link_id) is not None:
        return "osm_road"
    if "car" in {m.strip() for m in modes.split(",")}:
        return "unknown_car_link"
    return "other_pt_or_unknown"


def reestimate_link(link_id: str, attrib: dict[str, str], road_lookup: dict[int, dict[str, Any]]) -> dict[str, Any]:
    old_capacity = safe_float(attrib.get("capacity"))
    old_lanes = safe_float(attrib.get("permlanes"))
    modes = attrib.get("modes", "")
    link_class = classify_link(link_id, modes)

    highway = ""
    inferred_lanes = old_lanes
    per_lane_capacity = math.nan
    new_capacity = old_capacity
    lane_source = "unchanged"
    note = ""

    if link_class == "metro_pt_only":
        new_capacity = old_capacity
        inferred_lanes = old_lanes
        lane_source = "metro_unchanged"
        note = "metro pt-only link capacity preserved"
    elif link_class == "synthetic_bus_trajectory":
        inferred_lanes = 1.0
        new_capacity = 1200.0
        per_lane_capacity = 1200.0
        lane_source = "synthetic_bus_trajectory_default"
    elif link_class == "synthetic_bus_connector":
        inferred_lanes = 1.0
        new_capacity = 1800.0
        per_lane_capacity = 1800.0
        lane_source = "synthetic_bus_connector_default"
    elif link_class == "osm_road":
        road_idx = road_idx_from_link_id(link_id)
        road = road_lookup.get(road_idx) if road_idx is not None else None
        if road is None:
            lane_source = "unmatched_osm_road_id_unchanged"
            note = f"could not match road_idx={road_idx}"
        else:
            highway = str(road["highway"])
            inferred_lanes, lane_source = infer_direction_lanes(road, direction_from_link_id(link_id))
            per_lane_capacity = PER_LANE_CAPACITY.get(highway, 700.0)
            new_capacity = per_lane_capacity * inferred_lanes
    else:
        lane_source = "unknown_link_unchanged"
        note = f"link_class={link_class}"

    if not math.isfinite(new_capacity) or new_capacity <= 0:
        new_capacity = old_capacity
        note = (note + "; " if note else "") + "invalid computed capacity, kept old"
    if not math.isfinite(inferred_lanes) or inferred_lanes <= 0:
        inferred_lanes = old_lanes
        note = (note + "; " if note else "") + "invalid computed lanes, kept old"

    return {
        "link_id": link_id,
        "link_class": link_class,
        "modes": modes,
        "highway": highway,
        "old_capacity": old_capacity,
        "new_capacity": float(new_capacity),
        "old_permlanes": old_lanes,
        "new_permlanes": float(inferred_lanes),
        "capacity_ratio": float(new_capacity / old_capacity) if old_capacity and old_capacity > 0 else math.nan,
        "per_lane_capacity": per_lane_capacity,
        "lane_source": lane_source,
        "note": note,
    }


def write_network(root: ET.Element, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(output_path, "wt", encoding="utf-8", newline="\n") as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n')
        f.write('<!DOCTYPE network SYSTEM "http://www.matsim.org/files/dtd/network_v1.dtd">\n\n')
        f.write(ET.tostring(root, encoding="unicode"))
        f.write("\n")


def describe(values: list[float]) -> dict[str, float | int]:
    clean = [v for v in values if math.isfinite(v)]
    if not clean:
        return {"count": 0}
    clean_sorted = sorted(clean)
    return {
        "count": len(clean),
        "min": min(clean),
        "mean": statistics.fmean(clean),
        "median": statistics.median(clean),
        "p90": clean_sorted[int(0.9 * (len(clean_sorted) - 1))],
        "p95": clean_sorted[int(0.95 * (len(clean_sorted) - 1))],
        "max": max(clean),
    }


def write_distribution_tables(rows: list[dict[str, Any]], output_dir: Path) -> dict[str, Any]:
    df = pd.DataFrame(rows)

    dist_rows = []
    group_cols = ["link_class", "modes"]
    for keys, sub in df.groupby(group_cols, dropna=False):
        key_dict = dict(zip(group_cols, keys))
        for metric in ["capacity", "permlanes"]:
            before = describe(sub[f"old_{metric if metric == 'capacity' else 'permlanes'}"].astype(float).tolist())
            after = describe(sub[f"new_{metric if metric == 'capacity' else 'permlanes'}"].astype(float).tolist())
            dist_rows.append({**key_dict, "metric": metric, "stage": "before", **before})
            dist_rows.append({**key_dict, "metric": metric, "stage": "after", **after})
    dist_path = output_dir / "capacity_distribution_before_after.csv"
    with dist_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "link_class",
                "modes",
                "metric",
                "stage",
                "count",
                "min",
                "mean",
                "median",
                "p90",
                "p95",
                "max",
            ],
        )
        writer.writeheader()
        writer.writerows(dist_rows)

    by_highway = []
    osm_df = df[df["link_class"] == "osm_road"].copy()
    for highway, sub in osm_df.groupby("highway", dropna=False):
        by_highway.append(
            {
                "highway": highway,
                "links": int(len(sub)),
                "old_capacity_mean": float(sub["old_capacity"].mean()),
                "new_capacity_mean": float(sub["new_capacity"].mean()),
                "old_capacity_median": float(sub["old_capacity"].median()),
                "new_capacity_median": float(sub["new_capacity"].median()),
                "old_permlanes_mean": float(sub["old_permlanes"].mean()),
                "new_permlanes_mean": float(sub["new_permlanes"].mean()),
                "dominant_default_rows": int((sub["lane_source"] == "dominant_highway_default").sum()),
                "osm_lane_rows": int(sub["lane_source"].astype(str).str.startswith("osm_").sum()),
            }
        )
    by_highway_path = output_dir / "capacity_reestimate_by_highway.csv"
    pd.DataFrame(by_highway).sort_values("links", ascending=False).to_csv(by_highway_path, index=False)

    return {
        "distribution_csv": str(dist_path),
        "by_highway_csv": str(by_highway_path),
    }


def write_bus_priority_candidates(
    schedule_path: Path,
    reference_output_dir: Path,
    qa_rows: list[dict[str, Any]],
    output_dir: Path,
) -> str | None:
    traffic_path = reference_output_dir / "analysis" / "traffic" / "traffic_stats_by_link_daily.csv"
    if not traffic_path.exists() or not schedule_path.exists():
        return None

    bus_link_counts: Counter[str] = Counter()
    current_line_id: str | None = None
    current_route_id: str | None = None
    in_bus_route = False
    with gzip.open(schedule_path, "rt", encoding="utf-8") as f:
        for event, elem in ET.iterparse(f, events=("start", "end")):
            tag = elem.tag.split("}")[-1]
            if event == "start" and tag == "transitLine":
                current_line_id = elem.attrib.get("id")
            elif event == "start" and tag == "transitRoute":
                current_route_id = elem.attrib.get("id")
                in_bus_route = str(current_line_id or "").startswith("bus_line_") or str(current_route_id or "").startswith("bus_route_")
            elif event == "end" and tag == "link" and in_bus_route:
                ref_id = elem.attrib.get("refId")
                if ref_id:
                    bus_link_counts[ref_id] += 1
            elif event == "end" and tag == "transitRoute":
                current_route_id = None
                in_bus_route = False
                elem.clear()
            elif event == "end" and tag == "transitLine":
                current_line_id = None
                elem.clear()

    if not bus_link_counts:
        return None

    qa_by_link = {row["link_id"]: row for row in qa_rows}
    traffic = pd.read_csv(traffic_path)
    traffic = traffic[traffic["link_id"].isin(bus_link_counts.keys())].copy()
    if traffic.empty:
        return None
    traffic["bus_route_use_count"] = traffic["link_id"].map(bus_link_counts).fillna(0).astype(int)
    traffic["is_bus_priority_candidate"] = (
        (traffic["congestion_index"] < 0.5)
        & (traffic["simulated_traffic_volume"] >= 50)
        & (traffic["bus_route_use_count"] > 0)
    )
    rows = []
    for _, row in traffic[traffic["is_bus_priority_candidate"]].iterrows():
        qa = qa_by_link.get(row["link_id"], {})
        rows.append(
            {
                "link_id": row["link_id"],
                "bus_route_use_count": int(row["bus_route_use_count"]),
                "reference_congestion_index": float(row["congestion_index"]),
                "reference_simulated_traffic_volume": float(row["simulated_traffic_volume"]),
                "reference_avg_speed": float(row["avg_speed"]),
                "link_class": qa.get("link_class", ""),
                "highway": qa.get("highway", ""),
                "old_capacity": qa.get("old_capacity", ""),
                "new_capacity": qa.get("new_capacity", ""),
                "old_permlanes": qa.get("old_permlanes", ""),
                "new_permlanes": qa.get("new_permlanes", ""),
                "lane_source": qa.get("lane_source", ""),
                "candidate_reason": "bus route uses link; previous daily congestion_index < 0.5; previous volume >= 50",
            }
        )
    path = output_dir / "bus_priority_candidate_links.csv"
    pd.DataFrame(rows).sort_values(
        ["reference_congestion_index", "bus_route_use_count"],
        ascending=[True, False],
    ).to_csv(path, index=False)
    return str(path)


def main() -> int:
    args = parse_args()
    ensure_exists(args.network, "integrated network")
    ensure_exists(args.osm_roads, "OSM roads GeoJSON")
    ensure_exists(args.schedule, "transit schedule")
    ensure_exists(args.vehicles, "transit vehicles")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    road_lookup, road_metadata = load_osm_road_lookup(args.osm_roads)

    with gzip.open(args.network, "rt", encoding="utf-8") as f:
        tree = ET.parse(f)
    root = tree.getroot()
    links_el = root.find("links")
    if links_el is None:
        raise ValueError("network has no <links> element")

    qa_rows: list[dict[str, Any]] = []
    for link_el in links_el.findall("link"):
        attrib = dict(link_el.attrib)
        link_id = attrib["id"]
        row = reestimate_link(link_id, attrib, road_lookup)
        link_el.set("capacity", f'{row["new_capacity"]:.3f}')
        link_el.set("permlanes", f'{row["new_permlanes"]:.2f}')
        qa_rows.append(row)

    output_network = args.output_dir / "network_with_car_bus_metro.xml.gz"
    write_network(root, output_network)

    schedule_out = args.output_dir / "transitSchedule.xml.gz"
    vehicles_out = args.output_dir / "transitVehicles.xml.gz"
    shutil.copy2(args.schedule, schedule_out)
    shutil.copy2(args.vehicles, vehicles_out)

    qa_path = args.output_dir / "capacity_reestimate_link_qa.csv"
    fieldnames = [
        "link_id",
        "link_class",
        "modes",
        "highway",
        "old_capacity",
        "new_capacity",
        "old_permlanes",
        "new_permlanes",
        "capacity_ratio",
        "per_lane_capacity",
        "lane_source",
        "note",
    ]
    with qa_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(qa_rows)

    distribution_outputs = write_distribution_tables(qa_rows, args.output_dir)
    bus_priority_candidates = write_bus_priority_candidates(
        args.schedule,
        args.reference_output_dir,
        qa_rows,
        args.output_dir,
    )
    class_counts = Counter(row["link_class"] for row in qa_rows)
    lane_source_counts = Counter(row["lane_source"] for row in qa_rows)
    changed_rows = [
        row
        for row in qa_rows
        if abs(float(row["old_capacity"]) - float(row["new_capacity"])) > 1e-6
        or abs(float(row["old_permlanes"]) - float(row["new_permlanes"])) > 1e-6
    ]
    problematic = [
        row
        for row in qa_rows
        if not math.isfinite(float(row["new_capacity"]))
        or float(row["new_capacity"]) <= 0
        or not math.isfinite(float(row["new_permlanes"]))
        or float(row["new_permlanes"]) <= 0
    ]
    summary = {
        "created_by": "scripts/reestimate_fuzhou_network_capacity_by_lanes.py",
        "inputs": {
            "network": str(args.network),
            "osm_roads": str(args.osm_roads),
            "schedule": str(args.schedule),
            "vehicles": str(args.vehicles),
        },
        "outputs": {
            "network": str(output_network),
            "transitSchedule": str(schedule_out),
            "transitVehicles": str(vehicles_out),
            "qa_csv": str(qa_path),
            **distribution_outputs,
            "bus_priority_candidates_csv": bus_priority_candidates,
        },
        "rules": {
            "default_direction_lanes": DEFAULT_DIRECTION_LANES,
            "per_lane_capacity": PER_LANE_CAPACITY,
            "lane_caps": LANE_CAP_BY_HIGHWAY,
            "synthetic_bus_link_capacity": 1200.0,
            "synthetic_bus_connector_capacity": 1800.0,
            "metro_pt_only_capacity_policy": "unchanged",
            "bus_peak_priority_policy": "not implemented in v1; static MATSim network cannot set time-dependent bus-only link speed by mode",
        },
        "counts": {
            "links_total": len(qa_rows),
            "links_changed": len(changed_rows),
            "problematic_links": len(problematic),
            "link_class_counts": dict(class_counts),
            "lane_source_counts": dict(lane_source_counts),
        },
        "old_capacity": describe([float(row["old_capacity"]) for row in qa_rows]),
        "new_capacity": describe([float(row["new_capacity"]) for row in qa_rows]),
        "old_permlanes": describe([float(row["old_permlanes"]) for row in qa_rows]),
        "new_permlanes": describe([float(row["new_permlanes"]) for row in qa_rows]),
        "osm_metadata": road_metadata,
    }
    summary_path = args.output_dir / "capacity_reestimate_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
