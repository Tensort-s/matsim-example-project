#!/usr/bin/env python3
"""Fuse TD traffic-light facilities and OSM signal nodes into junctions.

The Transport Department Traffic Aids layer is a facility/CAD-symbol layer,
while OSM ``highway=traffic_signals`` nodes normally represent signal heads,
stop lines, approaches, or crossings.  Neither row count is a junction count.
This builder uses OSM's Hong Kong controller references where available,
spatially groups the remaining observations, verifies them against official
facility points, and maps the result to the active MATSim car network.

No signal cycle, phase, green split, or offset is invented.  The resulting
controlled-link table is an adoption candidate for a later MATSim signals
build, not a timing plan.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence

import geopandas as gpd
import numpy as np
import osmium
import pandas as pd
from lxml import etree as ET
from pyproj import Transformer
from scipy.spatial import cKDTree
from shapely.geometry import Point
from sklearn.cluster import DBSCAN


REPO_ROOT = Path(__file__).resolve().parents[3]
FORMAL_PROJECT_ROOT = Path(
    os.environ.get("MATSIM_PROJECT_ROOT", r"F:\Matsim\matsim-example-project")
)
UPSTREAM_ROOT = FORMAL_PROJECT_ROOT if FORMAL_PROJECT_ROOT.exists() else REPO_ROOT

DEFAULT_TD_POINTS = (
    REPO_ROOT
    / "data/transit/hongkong/raw/traffic_signals_2026"
    / "DTAD_TRAFFIC_LIGHT_PT.gml"
)
DEFAULT_OSM_PBF = (
    UPSTREAM_ROOT
    / "data/osm/hongkong/fixed_link_boundary/hong-kong-latest.osm.pbf"
)
DEFAULT_NETWORK = (
    UPSTREAM_ROOT
    / "data/transit/hongkong/processed"
    / "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_"
    "ferry_core_v1_cap010/network.xml.gz"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "data/transit/hongkong/processed"
    / "hong_kong_traffic_signal_registry_2026_v1"
)

TARGET_CRS = "EPSG:32650"
WGS84 = "EPSG:4326"
OFFICIAL_JUNCTION_BENCHMARK = 2028
OFFICIAL_MATCH_DISTANCE_M = 30.0
REFERENCE_SPLIT_DISTANCE_M = 90.0
UNREFERENCED_ATTACH_DISTANCE_M = 45.0
UNREFERENCED_AMBIGUITY_MARGIN_M = 8.0
UNREFERENCED_CLUSTER_DISTANCE_M = 35.0
NETWORK_NODE_MATCH_DISTANCE_M = 40.0
OFFICIAL_ONLY_CLUSTER_DISTANCE_M = 30.0


def safe_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def write_csv(
    path: Path,
    rows: Iterable[dict[str, Any]],
    fieldnames: Sequence[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def normalize_signal_reference(value: Any) -> str:
    text = safe_text(value).upper().replace(" ", "")
    text = re.sub(r"^REF=", "", text)
    match = re.fullmatch(r"(NT|N|H|K|L)(\d{1,3})", text)
    if not match:
        return ""
    prefix, digits = match.groups()
    if prefix == "N":
        prefix = "NT"
    return f"{prefix}{int(digits):03d}"


class SignalNodeHandler(osmium.SimpleHandler):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[dict[str, Any]] = []

    def node(self, node: osmium.osm.Node) -> None:
        if node.tags.get("highway") != "traffic_signals":
            return
        if not node.location.valid():
            return
        tags = dict(node.tags)
        raw_reference = tags.get("traffic_signals:ref") or tags.get("ref") or ""
        self.rows.append(
            {
                "osm_node_id": str(node.id),
                "longitude": float(node.location.lon),
                "latitude": float(node.location.lat),
                "raw_reference": raw_reference,
                "normalized_reference": normalize_signal_reference(raw_reference),
                "traffic_signals": tags.get("traffic_signals", ""),
                "traffic_signals_direction": tags.get(
                    "traffic_signals:direction", ""
                ),
                "traffic_signals_turn": tags.get("traffic_signals:turn", ""),
                "crossing": tags.get("crossing", ""),
                "junction": tags.get("junction", ""),
                "intersection": tags.get("intersection", ""),
                "all_tags_json": json.dumps(
                    tags, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ),
            }
        )


def read_osm_signal_nodes(path: Path) -> pd.DataFrame:
    handler = SignalNodeHandler()
    handler.apply_file(str(path), locations=False)
    if not handler.rows:
        raise RuntimeError(f"No highway=traffic_signals nodes found in {path}")
    frame = pd.DataFrame(handler.rows)
    transformer = Transformer.from_crs(WGS84, TARGET_CRS, always_xy=True)
    x, y = transformer.transform(
        frame["longitude"].to_numpy(), frame["latitude"].to_numpy()
    )
    frame["x"] = x
    frame["y"] = y
    return frame


def read_td_points(path: Path) -> gpd.GeoDataFrame:
    frame = gpd.read_file(path)
    required = {"OBJECTID", "REFNAME", "FEATUREID", "LAST_UPD_DATE", "geometry"}
    missing = required - set(frame.columns)
    if missing:
        raise RuntimeError(f"TD point layer is missing fields: {sorted(missing)}")
    if frame.crs is None:
        raise RuntimeError("TD point layer has no CRS")
    source_crs = str(frame.crs)
    frame = frame.to_crs(TARGET_CRS)
    frame = frame[frame.geometry.notna() & ~frame.geometry.is_empty].copy()
    frame["td_primary_symbol"] = frame["REFNAME"].astype(str).str.match(
        r"^[SP]\d", na=False
    )
    frame.attrs["source_crs"] = source_crs
    return frame


def split_reference_components(
    osm: pd.DataFrame,
    split_distance_m: float,
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    labels = np.full(len(osm), "", dtype=object)
    conflicts: list[dict[str, Any]] = []
    for reference, indices in osm[osm["normalized_reference"] != ""].groupby(
        "normalized_reference"
    ).groups.items():
        index_array = np.asarray(list(indices), dtype=int)
        coordinates = osm.loc[index_array, ["x", "y"]].to_numpy()
        component_labels = DBSCAN(
            eps=split_distance_m,
            min_samples=1,
            algorithm="kd_tree",
            n_jobs=1,
        ).fit_predict(coordinates)
        components = sorted(set(int(value) for value in component_labels))
        component_order = sorted(
            components,
            key=lambda component: tuple(
                np.mean(coordinates[component_labels == component], axis=0)
            ),
        )
        for ordinal, component in enumerate(component_order, start=1):
            members = index_array[component_labels == component]
            key = f"ref:{reference}"
            if len(component_order) > 1:
                key += f":part{ordinal}"
            labels[members] = key
        if len(component_order) > 1:
            conflicts.append(
                {
                    "normalized_reference": reference,
                    "spatial_component_count": len(component_order),
                    "osm_node_count": len(index_array),
                    "status": "same_reference_split_beyond_threshold",
                }
            )
    return labels, conflicts


def group_osm_nodes(
    osm: pd.DataFrame,
    *,
    reference_split_distance_m: float = REFERENCE_SPLIT_DISTANCE_M,
    attach_distance_m: float = UNREFERENCED_ATTACH_DISTANCE_M,
    ambiguity_margin_m: float = UNREFERENCED_AMBIGUITY_MARGIN_M,
    cluster_distance_m: float = UNREFERENCED_CLUSTER_DISTANCE_M,
) -> tuple[np.ndarray, list[dict[str, Any]], dict[str, int]]:
    labels, conflicts = split_reference_components(
        osm, reference_split_distance_m
    )
    referenced_indices = np.flatnonzero(labels != "")
    unreferenced_indices = np.flatnonzero(labels == "")
    ambiguous_count = 0
    attached_count = 0

    remaining: list[int] = []
    if len(referenced_indices):
        reference_tree = cKDTree(
            osm.loc[referenced_indices, ["x", "y"]].to_numpy()
        )
        query_k = min(16, len(referenced_indices))
        distances, positions = reference_tree.query(
            osm.loc[unreferenced_indices, ["x", "y"]].to_numpy(), k=query_k
        )
        if query_k == 1:
            distances = distances[:, None]
            positions = positions[:, None]

        for source_index, candidate_distances, candidate_positions in zip(
            unreferenced_indices, distances, positions
        ):
            nearest_position = int(candidate_positions[0])
            nearest_group = labels[referenced_indices[nearest_position]]
            nearest_distance = float(candidate_distances[0])
            second_group_distance = math.inf
            for distance, position in zip(candidate_distances[1:], candidate_positions[1:]):
                group = labels[referenced_indices[int(position)]]
                if group != nearest_group:
                    second_group_distance = float(distance)
                    break
            ambiguous = (
                second_group_distance - nearest_distance < ambiguity_margin_m
            )
            if nearest_distance <= attach_distance_m and not ambiguous:
                labels[source_index] = nearest_group
                attached_count += 1
            else:
                remaining.append(int(source_index))
                ambiguous_count += int(
                    nearest_distance <= attach_distance_m and ambiguous
                )
    else:
        remaining = [int(index) for index in unreferenced_indices]

    if remaining:
        remaining_array = np.asarray(remaining, dtype=int)
        cluster_labels = DBSCAN(
            eps=cluster_distance_m,
            min_samples=1,
            algorithm="kd_tree",
            n_jobs=1,
        ).fit_predict(osm.loc[remaining_array, ["x", "y"]].to_numpy())
        clusters: list[tuple[float, float, int]] = []
        for cluster in sorted(set(int(value) for value in cluster_labels)):
            members = remaining_array[cluster_labels == cluster]
            centroid = osm.loc[members, ["x", "y"]].mean().to_numpy()
            clusters.append((float(centroid[0]), float(centroid[1]), cluster))
        for ordinal, (_, _, cluster) in enumerate(sorted(clusters), start=1):
            members = remaining_array[cluster_labels == cluster]
            labels[members] = f"unref:{ordinal:04d}"

    if np.any(labels == ""):
        raise AssertionError("Every OSM signal node must receive a group")
    summary = {
        "normalized_reference_count": int(
            osm.loc[osm["normalized_reference"] != "", "normalized_reference"].nunique()
        ),
        "referenced_component_count": int(
            len(set(labels[osm["normalized_reference"] != ""]))
        ),
        "unreferenced_attached_node_count": attached_count,
        "unreferenced_ambiguous_node_count": ambiguous_count,
        "unreferenced_spatial_cluster_count": int(
            len({value for value in labels if str(value).startswith("unref:")})
        ),
        "osm_junction_group_count": int(len(set(labels))),
    }
    return labels, conflicts, summary


def parse_network(
    path: Path,
) -> tuple[
    dict[str, tuple[float, float]],
    list[dict[str, Any]],
    dict[str, list[str]],
    dict[str, int],
]:
    nodes: dict[str, tuple[float, float]] = {}
    car_links: list[dict[str, Any]] = []
    incoming: defaultdict[str, list[str]] = defaultdict(list)
    neighbours: defaultdict[str, set[str]] = defaultdict(set)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as handle:
        for _, element in ET.iterparse(handle, events=("end",), tag=("node", "link")):
            tag = local_name(element.tag)
            if tag == "node":
                nodes[element.attrib["id"]] = (
                    float(element.attrib["x"]),
                    float(element.attrib["y"]),
                )
            elif tag == "link":
                modes = {
                    value.strip()
                    for value in element.attrib.get("modes", "").split(",")
                    if value.strip()
                }
                if "car" in modes:
                    record = {
                        "link_id": element.attrib["id"],
                        "from_node": element.attrib["from"],
                        "to_node": element.attrib["to"],
                        "length_m": float(element.attrib.get("length", 0.0)),
                        "freespeed_m_s": float(
                            element.attrib.get("freespeed", 0.0)
                        ),
                        "capacity_veh_h": float(
                            element.attrib.get("capacity", 0.0)
                        ),
                        "lanes": float(element.attrib.get("permlanes", 0.0)),
                        "modes": ",".join(sorted(modes)),
                    }
                    car_links.append(record)
                    incoming[record["to_node"]].append(record["link_id"])
                    neighbours[record["from_node"]].add(record["to_node"])
                    neighbours[record["to_node"]].add(record["from_node"])
            element.clear()
            while element.getprevious() is not None:
                del element.getparent()[0]
    road_nodes = {
        node_id: nodes[node_id]
        for node_id in neighbours
        if node_id in nodes
    }
    degrees = {node_id: len(neighbours[node_id]) for node_id in road_nodes}
    return road_nodes, car_links, dict(incoming), degrees


def attach_nearest(
    source_xy: np.ndarray,
    target_ids: Sequence[str],
    target_xy: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    distances, positions = cKDTree(target_xy).query(source_xy)
    identifiers = np.asarray(target_ids, dtype=object)[positions]
    return distances.astype(float), identifiers


def stable_junction_id(group_key: str) -> str:
    if group_key.startswith("ref:"):
        parts = group_key.split(":")
        suffix = ""
        if len(parts) == 3:
            suffix = f"_P{parts[2].replace('part', '')}"
        return f"TS_{parts[1]}{suffix}"
    if group_key.startswith("unref:"):
        return f"TS_OSM_{group_key.split(':')[1]}"
    if group_key.startswith("tdgeom:"):
        return f"TS_TDGEOM_{group_key.split(':')[1]}"
    raise ValueError(group_key)


def choose_primary_network_node(member_rows: pd.DataFrame) -> tuple[str, float]:
    candidates = member_rows[
        member_rows["nearest_network_node_distance_m"]
        <= NETWORK_NODE_MATCH_DISTANCE_M
    ]
    if candidates.empty:
        row = member_rows.loc[
            member_rows["nearest_network_node_distance_m"].idxmin()
        ]
        return safe_text(row["nearest_network_node_id"]), float(
            row["nearest_network_node_distance_m"]
        )
    grouped = candidates.groupby("nearest_network_node_id")[
        "nearest_network_node_distance_m"
    ].agg(["count", "mean"])
    grouped = grouped.sort_values(["count", "mean"], ascending=[False, True])
    node_id = str(grouped.index[0])
    return node_id, float(grouped.iloc[0]["mean"])


def build_junction_rows(
    osm: pd.DataFrame,
    td: gpd.GeoDataFrame,
    group_key_to_junction: dict[str, str],
    network_degrees: dict[str, int],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    inverse_transformer = Transformer.from_crs(
        TARGET_CRS, WGS84, always_xy=True
    )
    td_assignments = td[td["assigned_group_key"] != ""].groupby(
        "assigned_group_key"
    )
    td_counts = td_assignments.size().to_dict()
    td_primary_counts = (
        td[td["assigned_group_key"] != ""]
        .groupby("assigned_group_key")["td_primary_symbol"]
        .sum()
        .astype(int)
        .to_dict()
    )

    for group_key, members in osm.groupby("group_key", sort=True):
        x = float(members["x"].mean())
        y = float(members["y"].mean())
        longitude, latitude = inverse_transformer.transform(x, y)
        primary_node, primary_distance = choose_primary_network_node(members)
        reference_values = sorted(
            value
            for value in set(members["normalized_reference"])
            if value
        )
        official_match_count = int(
            (members["nearest_td_distance_m"] <= OFFICIAL_MATCH_DISTANCE_M).sum()
        )
        match_rate = official_match_count / len(members)
        reference = reference_values[0] if reference_values else ""
        split_reference = ":part" in group_key
        if reference and match_rate >= 0.8 and primary_distance <= 30:
            confidence = "high"
        elif (
            len(members) >= 2
            and match_rate >= 0.8
            and primary_distance <= NETWORK_NODE_MATCH_DISTANCE_M
        ):
            confidence = "high"
        elif official_match_count and primary_distance <= 60:
            confidence = "medium"
        else:
            confidence = "review"
        if split_reference:
            confidence = "review"

        mapped_nodes = sorted(
            set(
                members.loc[
                    members["nearest_network_node_distance_m"]
                    <= NETWORK_NODE_MATCH_DISTANCE_M,
                    "nearest_network_node_id",
                ].astype(str)
            )
        )
        junction_id = group_key_to_junction[group_key]
        rows.append(
            {
                "signal_junction_id": junction_id,
                "group_key": group_key,
                "source_coverage": (
                    "td_osm" if td_counts.get(group_key, 0) else "osm_only"
                ),
                "confidence": confidence,
                "normalized_reference": reference,
                "reference_spatial_split": split_reference,
                "osm_node_count": int(len(members)),
                "td_point_count": int(td_counts.get(group_key, 0)),
                "td_primary_point_count": int(td_primary_counts.get(group_key, 0)),
                "osm_nodes_with_td_match": official_match_count,
                "osm_td_match_rate": round(match_rate, 6),
                "x_epsg32650": round(x, 3),
                "y_epsg32650": round(y, 3),
                "longitude": round(float(longitude), 8),
                "latitude": round(float(latitude), 8),
                "primary_network_node_id": primary_node,
                "primary_network_node_distance_m": round(primary_distance, 3),
                "primary_network_node_degree": int(
                    network_degrees.get(primary_node, 0)
                ),
                "mapped_network_node_count": len(mapped_nodes),
                "mapped_network_node_ids": "|".join(mapped_nodes),
                "osm_node_ids": "|".join(
                    sorted(members["osm_node_id"].astype(str))
                ),
                "timing_status": "missing_not_inferred",
            }
        )
    return rows


def add_td_only_candidates(
    td: gpd.GeoDataFrame,
    road_node_ids: Sequence[str],
    road_node_xy: np.ndarray,
    network_degrees: dict[str, int],
) -> list[dict[str, Any]]:
    candidate_points = td[
        td["td_primary_symbol"]
        & (td["nearest_osm_distance_m"] > OFFICIAL_MATCH_DISTANCE_M)
    ].copy()
    if candidate_points.empty:
        return []
    coordinates = np.column_stack(
        [candidate_points.geometry.x, candidate_points.geometry.y]
    )
    labels = DBSCAN(
        eps=OFFICIAL_ONLY_CLUSTER_DISTANCE_M,
        min_samples=1,
        algorithm="kd_tree",
        n_jobs=1,
    ).fit_predict(coordinates)
    candidate_points["candidate_cluster"] = labels
    inverse_transformer = Transformer.from_crs(
        TARGET_CRS, WGS84, always_xy=True
    )
    rows: list[dict[str, Any]] = []
    clusters: list[tuple[float, float, int]] = []
    for label, members in candidate_points.groupby("candidate_cluster"):
        clusters.append(
            (
                float(members.geometry.x.mean()),
                float(members.geometry.y.mean()),
                int(label),
            )
        )
    road_tree = cKDTree(road_node_xy)
    for ordinal, (x, y, label) in enumerate(sorted(clusters), start=1):
        members = candidate_points[candidate_points["candidate_cluster"] == label]
        rounded_coordinates = {
            (round(point.x, 2), round(point.y, 2)) for point in members.geometry
        }
        distance, position = road_tree.query([[x, y]])
        network_node_id = str(road_node_ids[int(position[0])])
        network_distance = float(distance[0])
        feature_count = int(len(members))
        unique_coordinate_count = len(rounded_coordinates)
        geometry_quality_gate_passed = (
            feature_count >= 3
            and unique_coordinate_count >= 2
            and network_distance <= NETWORK_NODE_MATCH_DISTANCE_M
        )
        longitude, latitude = inverse_transformer.transform(x, y)
        rows.append(
            {
                "candidate_id": f"TD_ONLY_{ordinal:04d}",
                "group_key": f"tdgeom:{ordinal:04d}",
                "geometry_quality_gate_passed": geometry_quality_gate_passed,
                "td_point_count": feature_count,
                "td_unique_coordinate_count": unique_coordinate_count,
                "td_refnames": "|".join(sorted(set(members["REFNAME"].astype(str)))),
                "x_epsg32650": round(x, 3),
                "y_epsg32650": round(y, 3),
                "longitude": round(float(longitude), 8),
                "latitude": round(float(latitude), 8),
                "nearest_osm_distance_m": round(
                    float(members["nearest_osm_distance_m"].min()), 3
                ),
                "primary_network_node_id": network_node_id,
                "primary_network_node_distance_m": round(network_distance, 3),
                "primary_network_node_degree": int(
                    network_degrees.get(network_node_id, 0)
                ),
                "status": (
                    "eligible_for_manual_review"
                    if geometry_quality_gate_passed
                    else "review_td_geometry_only"
                ),
            }
        )
    return rows


def build_controlled_link_rows(
    junction_rows: list[dict[str, Any]],
    osm: pd.DataFrame,
    car_links: list[dict[str, Any]],
    incoming: dict[str, list[str]],
) -> list[dict[str, Any]]:
    links_by_id = {row["link_id"]: row for row in car_links}
    junction_by_group = {row["group_key"]: row for row in junction_rows}
    evidence: defaultdict[tuple[str, str], list[str]] = defaultdict(list)
    for row in osm.itertuples(index=False):
        if row.nearest_network_node_distance_m > NETWORK_NODE_MATCH_DISTANCE_M:
            continue
        for link_id in incoming.get(str(row.nearest_network_node_id), []):
            evidence[(str(row.group_key), link_id)].append(str(row.osm_node_id))

    output: list[dict[str, Any]] = []
    for (group_key, link_id), node_ids in sorted(evidence.items()):
        junction = junction_by_group[group_key]
        link = links_by_id[link_id]
        output.append(
            {
                "signal_junction_id": junction["signal_junction_id"],
                "controlled_link_candidate_id": link_id,
                "from_node": link["from_node"],
                "to_node": link["to_node"],
                "length_m": link["length_m"],
                "freespeed_m_s": link["freespeed_m_s"],
                "capacity_veh_h": link["capacity_veh_h"],
                "lanes": link["lanes"],
                "modes": link["modes"],
                "evidence_osm_node_ids": "|".join(sorted(set(node_ids))),
                "status": "location_supported_timing_missing",
            }
        )
    return output


def percentile(values: np.ndarray, q: float) -> float | None:
    if not len(values):
        return None
    return round(float(np.percentile(values, q)), 3)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--td-points", type=Path, default=DEFAULT_TD_POINTS)
    parser.add_argument("--osm-pbf", type=Path, default=DEFAULT_OSM_PBF)
    parser.add_argument("--network", type=Path, default=DEFAULT_NETWORK)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--include-td-only",
        action="store_true",
        help=(
            "Include TD-geometry-only candidates that pass the mechanical "
            "quality gate. Off by default because the TD layer has no "
            "junction/controller identifier."
        ),
    )
    args = parser.parse_args()

    for path in (args.td_points, args.osm_pbf, args.network):
        if not path.exists():
            raise FileNotFoundError(path)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    print("Reading OSM signal nodes...")
    osm = read_osm_signal_nodes(args.osm_pbf)
    labels, reference_conflicts, grouping_summary = group_osm_nodes(osm)
    osm["group_key"] = labels
    group_key_to_junction = {
        group_key: stable_junction_id(group_key) for group_key in sorted(set(labels))
    }
    osm["signal_junction_id"] = osm["group_key"].map(group_key_to_junction)

    print("Reading official TD traffic-light points...")
    td = read_td_points(args.td_points)
    td_xy = np.column_stack([td.geometry.x, td.geometry.y])
    osm_xy = osm[["x", "y"]].to_numpy()
    td_tree = cKDTree(td_xy)
    osm_td_distances, osm_td_positions = td_tree.query(osm_xy)
    osm["nearest_td_distance_m"] = osm_td_distances
    osm["nearest_td_feature_id"] = td.iloc[osm_td_positions][
        "FEATUREID"
    ].to_numpy()
    osm["nearest_td_refname"] = td.iloc[osm_td_positions]["REFNAME"].to_numpy()

    osm_tree = cKDTree(osm_xy)
    td_osm_distances, td_osm_positions = osm_tree.query(td_xy)
    td["nearest_osm_distance_m"] = td_osm_distances
    td["nearest_osm_node_id"] = osm.iloc[td_osm_positions][
        "osm_node_id"
    ].to_numpy()
    td["assigned_group_key"] = np.where(
        td_osm_distances <= OFFICIAL_MATCH_DISTANCE_M,
        osm.iloc[td_osm_positions]["group_key"].to_numpy(),
        "",
    )
    td["signal_junction_id"] = td["assigned_group_key"].map(
        group_key_to_junction
    ).fillna("")

    print("Reading and indexing active MATSim car network...")
    road_nodes, car_links, incoming, network_degrees = parse_network(args.network)
    road_node_ids = sorted(road_nodes)
    road_node_xy = np.asarray([road_nodes[node_id] for node_id in road_node_ids])
    network_distances, network_ids = attach_nearest(
        osm_xy, road_node_ids, road_node_xy
    )
    osm["nearest_network_node_distance_m"] = network_distances
    osm["nearest_network_node_id"] = network_ids

    junction_rows = build_junction_rows(
        osm, td, group_key_to_junction, network_degrees
    )
    td_only_rows = add_td_only_candidates(
        td, road_node_ids, road_node_xy, network_degrees
    )
    eligible_td_only = [
        row for row in td_only_rows if row["geometry_quality_gate_passed"]
    ]
    promoted_td_only = eligible_td_only if args.include_td_only else []
    for row in promoted_td_only:
        junction_rows.append(
            {
                "signal_junction_id": stable_junction_id(row["group_key"]),
                "group_key": row["group_key"],
                "source_coverage": "td_only",
                "confidence": "medium",
                "normalized_reference": "",
                "reference_spatial_split": False,
                "osm_node_count": 0,
                "td_point_count": row["td_point_count"],
                "td_primary_point_count": row["td_point_count"],
                "osm_nodes_with_td_match": 0,
                "osm_td_match_rate": None,
                "x_epsg32650": row["x_epsg32650"],
                "y_epsg32650": row["y_epsg32650"],
                "longitude": row["longitude"],
                "latitude": row["latitude"],
                "primary_network_node_id": row["primary_network_node_id"],
                "primary_network_node_distance_m": row[
                    "primary_network_node_distance_m"
                ],
                "primary_network_node_degree": row[
                    "primary_network_node_degree"
                ],
                "mapped_network_node_count": 1,
                "mapped_network_node_ids": row["primary_network_node_id"],
                "osm_node_ids": "",
                "timing_status": "missing_not_inferred",
            }
        )
    junction_rows.sort(key=lambda row: row["signal_junction_id"])
    controlled_link_rows = build_controlled_link_rows(
        junction_rows, osm, car_links, incoming
    )
    junctions_with_links = {
        row["signal_junction_id"] for row in controlled_link_rows
    }
    junctions_without_links = [
        row
        for row in junction_rows
        if row["signal_junction_id"] not in junctions_with_links
    ]

    sensitivity: list[dict[str, Any]] = []
    for attach_distance in (35.0, 45.0, 55.0):
        for cluster_distance in (30.0, 35.0, 40.0):
            variant_labels, _, _ = group_osm_nodes(
                osm,
                attach_distance_m=attach_distance,
                cluster_distance_m=cluster_distance,
            )
            sensitivity.append(
                {
                    "attach_distance_m": attach_distance,
                    "cluster_distance_m": cluster_distance,
                    "osm_junction_group_count": len(set(variant_labels)),
                }
            )

    junction_fields = list(junction_rows[0])
    write_csv(
        args.output_dir / "hong_kong_signal_junctions.csv",
        junction_rows,
        junction_fields,
    )
    junction_gdf = gpd.GeoDataFrame(
        junction_rows,
        geometry=[
            Point(row["longitude"], row["latitude"]) for row in junction_rows
        ],
        crs=WGS84,
    )
    junction_gdf.to_file(
        args.output_dir / "hong_kong_signal_junctions.geojson",
        driver="GeoJSON",
    )

    osm_fields = list(osm.columns)
    write_csv(
        args.output_dir / "osm_traffic_signal_nodes.csv",
        osm.to_dict("records"),
        osm_fields,
    )
    td_wgs84 = td.to_crs(WGS84)
    td_rows: list[dict[str, Any]] = []
    for projected, geographic in zip(td.itertuples(), td_wgs84.itertuples()):
        td_rows.append(
            {
                "object_id": projected.OBJECTID,
                "feature_id": projected.FEATUREID,
                "refname": projected.REFNAME,
                "last_update_date": projected.LAST_UPD_DATE,
                "angle": getattr(projected, "ANGLE", None),
                "elevation": getattr(projected, "ELEVATION", None),
                "td_primary_symbol": projected.td_primary_symbol,
                "x_epsg32650": round(projected.geometry.x, 3),
                "y_epsg32650": round(projected.geometry.y, 3),
                "longitude": round(geographic.geometry.x, 8),
                "latitude": round(geographic.geometry.y, 8),
                "nearest_osm_node_id": projected.nearest_osm_node_id,
                "nearest_osm_distance_m": round(
                    projected.nearest_osm_distance_m, 3
                ),
                "signal_junction_id": projected.signal_junction_id,
            }
        )
    write_csv(
        args.output_dir / "td_traffic_light_points.csv",
        td_rows,
        list(td_rows[0]),
    )
    if td_only_rows:
        write_csv(
            args.output_dir / "td_geometry_only_candidates.csv",
            td_only_rows,
            list(td_only_rows[0]),
        )
    if controlled_link_rows:
        write_csv(
            args.output_dir / "signal_controlled_link_candidates.csv",
            controlled_link_rows,
            list(controlled_link_rows[0]),
        )
    if junctions_without_links:
        write_csv(
            args.output_dir / "junctions_without_controlled_link_candidates.csv",
            junctions_without_links,
            junction_fields,
        )
    write_csv(
        args.output_dir / "reference_spatial_conflicts.csv",
        reference_conflicts,
        [
            "normalized_reference",
            "spatial_component_count",
            "osm_node_count",
            "status",
        ],
    )
    write_csv(
        args.output_dir / "grouping_sensitivity.csv",
        sensitivity,
        list(sensitivity[0]),
    )

    confidence_counts = Counter(row["confidence"] for row in junction_rows)
    coverage_counts = Counter(row["source_coverage"] for row in junction_rows)
    registry_count = len(junction_rows)
    summary = {
        "status": "adoption_ready_location_registry_timing_not_available",
        "inputs": {
            "td_traffic_light_point_gml": str(args.td_points),
            "osm_pbf": str(args.osm_pbf),
            "matsim_network": str(args.network),
            "td_point_layer_source_crs": td.attrs.get("source_crs", ""),
            "target_crs": TARGET_CRS,
        },
        "thresholds_m": {
            "official_match": OFFICIAL_MATCH_DISTANCE_M,
            "reference_split": REFERENCE_SPLIT_DISTANCE_M,
            "unreferenced_attach": UNREFERENCED_ATTACH_DISTANCE_M,
            "unreferenced_ambiguity_margin": UNREFERENCED_AMBIGUITY_MARGIN_M,
            "unreferenced_cluster": UNREFERENCED_CLUSTER_DISTANCE_M,
            "network_node_match": NETWORK_NODE_MATCH_DISTANCE_M,
            "official_only_cluster": OFFICIAL_ONLY_CLUSTER_DISTANCE_M,
        },
        "counts": {
            "td_traffic_light_point_features": len(td),
            "td_primary_symbol_features": int(td["td_primary_symbol"].sum()),
            "osm_highway_traffic_signals_nodes": len(osm),
            **grouping_summary,
            "reference_spatial_conflict_count": len(reference_conflicts),
            "td_geometry_only_candidate_count": len(td_only_rows),
            "td_geometry_only_quality_gate_passed_count": len(eligible_td_only),
            "td_geometry_only_promoted_count": len(promoted_td_only),
            "registry_junction_count": registry_count,
            "registry_by_source_coverage": dict(sorted(coverage_counts.items())),
            "registry_by_confidence": dict(sorted(confidence_counts.items())),
            "controlled_link_candidate_count": len(controlled_link_rows),
            "junctions_with_controlled_link_candidates": len(junctions_with_links),
            "junctions_without_controlled_link_candidates": len(
                junctions_without_links
            ),
        },
        "osm_to_td_nearest_distance_m": {
            "p50": percentile(osm_td_distances, 50),
            "p90": percentile(osm_td_distances, 90),
            "p95": percentile(osm_td_distances, 95),
            "p99": percentile(osm_td_distances, 99),
            "within_10m": int((osm_td_distances <= 10).sum()),
            "within_20m": int((osm_td_distances <= 20).sum()),
            "within_30m": int((osm_td_distances <= 30).sum()),
            "within_60m": int((osm_td_distances <= 60).sum()),
        },
        "osm_to_network_node_nearest_distance_m": {
            "p50": percentile(network_distances, 50),
            "p90": percentile(network_distances, 90),
            "p95": percentile(network_distances, 95),
            "p99": percentile(network_distances, 99),
            "within_30m": int((network_distances <= 30).sum()),
            "within_40m": int((network_distances <= 40).sum()),
            "within_60m": int((network_distances <= 60).sum()),
        },
        "official_mid_2025_benchmark": {
            "signalized_junctions": OFFICIAL_JUNCTION_BENCHMARK,
            "registry_minus_benchmark": registry_count
            - OFFICIAL_JUNCTION_BENCHMARK,
            "absolute_percent_difference": round(
                abs(registry_count - OFFICIAL_JUNCTION_BENCHMARK)
                / OFFICIAL_JUNCTION_BENCHMARK
                * 100,
                3,
            ),
            "interpretation": (
                "Independent validation only; the registry is not forced to "
                "equal the published aggregate. Dates, coverage, pedestrian "
                "crossings, and OSM completeness can differ."
            ),
        },
        "grouping_sensitivity": sensitivity,
        "known_limitations": [
            "TD Traffic Aids rows are equipment/CAD-symbol features, not junction records.",
            "OSM traffic-signal nodes are signal heads, approaches, or crossings, not junction records.",
            "No source used here supplies phase sequence, green split, cycle time, or coordination offset.",
            "Controlled MATSim links are location-supported candidates and require movement/phase design before simulation adoption.",
            "TD-geometry-only groups have no controller identifier and are excluded by default pending manual review.",
        ],
    }
    with (args.output_dir / "qa_summary.json").open(
        "w", encoding="utf-8"
    ) as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    print(json.dumps(summary["counts"], ensure_ascii=False, indent=2))
    print(f"Wrote registry to {args.output_dir}")


if __name__ == "__main__":
    main()
