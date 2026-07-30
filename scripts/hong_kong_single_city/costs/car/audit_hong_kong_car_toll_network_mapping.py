#!/usr/bin/env python3
"""Audit official Hong Kong toll features against the adopted MATSim network."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyogrio
from lxml import etree
from pyproj import Transformer
from shapely.geometry import LineString, Point


REPO_ROOT = Path(__file__).resolve().parents[4]
CAR_COST_ROOT = REPO_ROOT / "data/transport_costs/hongkong/car_cost_v1"
DEFAULT_OUTPUT = CAR_COST_ROOT / "toll_network_mapping_v1"
PREVIOUS_AUDIT_ROOT = CAR_COST_ROOT / "input_feasibility"
ROAD_LINK_RE = re.compile(r"^road_(\d+)_(\d+)_([fr])$")
DIRECT_ID_GEOMETRY_TOLERANCE_M = 100.0
OFFICIAL_RD_GEOMETRY_TOLERANCE_M = 100.0

RAW_TO_CANONICAL = {
    "Aberdeen Tunnel": ("aberdeen_tunnel", "Aberdeen Tunnel"),
    "Lion Rock Tunnel": ("lion_rock_tunnel", "Lion Rock Tunnel"),
    "Shing Mun Tunnels": ("shing_mun_tunnels", "Shing Mun Tunnels"),
    "Tate's Cairn Tunnel": ("tates_cairn_tunnel", "Tate's Cairn Tunnel"),
    "Tsing Sha Control Area (Eagle's Nest Tunnel and Sha Tin Heights Tunnel)": (
        "tsing_sha_control_area",
        "Tsing Sha Control Area (Eagle's Nest Tunnel and Sha Tin Heights Tunnel)",
    ),
    "Cross Harbour Tunnel": ("cross_harbour_tunnel", "Cross Harbour Tunnel"),
    "Eastern Harbour Crossing": (
        "eastern_harbour_crossing",
        "Eastern Harbour Crossing",
    ),
    "Western Harbour Crossing": (
        "western_harbour_crossing",
        "Western Harbour Crossing",
    ),
    "Western Harbour Crossing (Backup Toll Point)": (
        "western_harbour_crossing",
        "Western Harbour Crossing",
    ),
    "Tai Lam Tunnel": ("tai_lam_tunnel", "Tai Lam Tunnel"),
}

LEG_STATUSES = {
    "confirmed_charge_facility_identified",
    "confirmed_no_charge_all_facilities_covered",
    "ambiguous_multiple_facility_mapping",
    "unresolved_official_feature_mapping",
    "unresolved_alias_relationship",
    "unresolved_direction_mapping",
    "out_of_scope_motorcycle",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-project-root",
        type=Path,
        required=True,
        help="Canonical project root, read only.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def tag_name(element: Any) -> str:
    return str(element.tag).rsplit("}", 1)[-1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_directory(path: Path) -> str:
    digest = hashlib.sha256()
    for child in sorted(item for item in path.rglob("*") if item.is_file()):
        relative = child.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        with child.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def shapefile_sidecars(path: Path) -> list[Path]:
    return sorted(
        child
        for child in path.parent.glob(f"{path.stem}.*")
        if child.is_file()
    )


def sha256_file_bundle(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for child in sorted(paths, key=lambda item: item.name):
        name = child.name.encode("utf-8")
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        with child.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def parse_time_s(value: object) -> float:
    if value is None or value == "":
        return float("nan")
    if isinstance(value, (int, float)):
        return float(value)
    parts = str(value).split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    return float(value)


def iso_value(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    return str(value)


def canonical_for(raw_name: str) -> tuple[str, str]:
    if raw_name not in RAW_TO_CANONICAL:
        raise ValueError(f"Unexpected official toll facility: {raw_name}")
    return RAW_TO_CANONICAL[raw_name]


def input_paths(input_root: Path) -> dict[str, Path]:
    v2 = (
        input_root
        / "data/matsim_agents/hongkong/"
        "typical_weekday_5pct_v2_activity_modechoice"
    )
    network_root = (
        input_root
        / "data/transit/hongkong/processed/"
        "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_"
        "ferry_core_v1_cap010"
    )
    paths = {
        "plans_routed": v2 / "plans_routed_5pct_v2.xml.gz",
        "network": network_root / "network.xml.gz",
        "road_gdb": input_root / "data/transit/hongkong/RdNet_IRNP.gdb",
        "previous_feasibility": (
            PREVIOUS_AUDIT_ROOT / "car_leg_input_feasibility.parquet"
        ),
        "previous_validation": (
            PREVIOUS_AUDIT_ROOT / "car_cost_feasibility_validation.json"
        ),
        "toll_rules": CAR_COST_ROOT / "car_toll_rules.csv",
        "source_manifest": CAR_COST_ROOT / "car_cost_source_manifest.json",
        "snapshot_toll_rates": (
            CAR_COST_ROOT / "source_snapshots/td_toll_rates.html"
        ),
        "snapshot_harbour_tvt": (
            CAR_COST_ROOT / "source_snapshots/td_harbour_tvt.html"
        ),
        "snapshot_tai_lam_tvt": (
            CAR_COST_ROOT / "source_snapshots/td_tai_lam_tvt.html"
        ),
        "cost_low": CAR_COST_ROOT / "car_leg_cost_estimates_low.parquet",
        "cost_base": CAR_COST_ROOT / "car_leg_cost_estimates_base.parquet",
        "cost_high": CAR_COST_ROOT / "car_leg_cost_estimates_high.parquet",
        "fixed_link_grid_shp": (
            input_root
            / "data/worldcommuting_od/hongkong/custom_features/"
            "hong_kong_fixed_link_grid/CityAndRegionSplit/"
            "hong_kong_fixed_link_grid/regions.shp"
        ),
    }
    missing = [key for key, path in paths.items() if not path.exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing required read-only toll audit inputs: {missing}"
        )
    return paths


def protected_hashes(paths: dict[str, Path]) -> dict[str, str]:
    result = {}
    for key, path in paths.items():
        if key == "fixed_link_grid_shp":
            result["fixed_link_grid_bundle"] = sha256_file_bundle(
                shapefile_sidecars(path)
            )
        elif path.is_dir():
            result[key] = sha256_directory(path)
        else:
            result[key] = sha256_file(path)
    return result


def parse_network(
    path: Path,
) -> tuple[
    dict[str, tuple[float, float]],
    dict[str, dict[str, Any]],
    dict[int, list[str]],
]:
    nodes: dict[str, tuple[float, float]] = {}
    links: dict[str, dict[str, Any]] = {}
    by_route_id: dict[int, list[str]] = defaultdict(list)
    with gzip.open(path, "rb") as handle:
        for _, element in ET.iterparse(handle, events=("end",)):
            name = tag_name(element)
            if name == "node":
                nodes[element.attrib["id"]] = (
                    float(element.attrib["x"]),
                    float(element.attrib["y"]),
                )
            elif name == "link":
                link_id = element.attrib["id"]
                match = ROAD_LINK_RE.match(link_id)
                row = {
                    "id": link_id,
                    "from": element.attrib["from"],
                    "to": element.attrib["to"],
                    "length": float(element.attrib.get("length", "nan")),
                    "modes": element.attrib.get("modes", ""),
                    "route_id": int(match.group(1)) if match else None,
                    "segment": int(match.group(2)) if match else None,
                    "direction": match.group(3) if match else "",
                }
                links[link_id] = row
                if match:
                    by_route_id[int(match.group(1))].append(link_id)
            element.clear()
    return nodes, links, dict(by_route_id)


def network_link_geometry(
    link_id: str,
    nodes: dict[str, tuple[float, float]],
    links: dict[str, dict[str, Any]],
) -> LineString:
    link = links[link_id]
    return LineString([nodes[link["from"]], nodes[link["to"]]])


def load_official_pc_rows(
    gdb_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    tables = []
    for layer in ("TUN_BRIDGE_TOLL", "TUN_BRIDGE_TV_TOLL"):
        frame = pyogrio.read_dataframe(
            gdb_path, layer=layer, read_geometry=False
        )
        frame = frame.loc[
            frame["VEHICLE_CLASS_DESCRIPTION"]
            .astype(str)
            .str.upper()
            .eq("PC")
        ].copy()
        frame["source_layer"] = layer
        frame["rule_type"] = (
            "flat" if layer == "TUN_BRIDGE_TOLL" else "time_varying"
        )
        tables.append(frame)
    official = pd.concat(tables, ignore_index=True, sort=False)
    traffic = pyogrio.read_dataframe(gdb_path, layer="TRAFFIC_FEATURES")
    centerline = pyogrio.read_dataframe(gdb_path, layer="CENTERLINE")
    return official, traffic, centerline


def feature_role(raw_name: str, role: int, feature_id: int) -> str:
    if "Backup Toll Point" in raw_name:
        if feature_id == 151858:
            return "backup_southbound_alias_feature"
        if feature_id == 2684:
            return "shared_primary_backup_feature"
    return f"official_feature_{role}_direction_unlabelled"


def build_official_inventory(
    official: pd.DataFrame, gdb_sha256: str
) -> pd.DataFrame:
    rows = []
    for source_row in official.itertuples(index=False):
        raw_name = str(source_row.TUNNEL_BRIDGE_NAME)
        canonical_id, official_name = canonical_for(raw_name)
        for role in (1, 2):
            feature_id = int(getattr(source_row, f"FEATURE_ID_{role}"))
            rows.append(
                {
                    "canonical_facility_id": canonical_id,
                    "official_facility_name": official_name,
                    "official_facility_name_raw": raw_name,
                    "official_facility_name_chinese_raw": str(
                        source_row.TUNNEL_BRIDGE_CHINESE_NAME
                    ),
                    "feature_id": feature_id,
                    "feature_role_or_direction": feature_role(
                        raw_name, role, feature_id
                    ),
                    "source_layer": str(source_row.source_layer),
                    "effective_date": iso_value(source_row.EFFECTIVE_DATE),
                    "rule_type": str(source_row.rule_type),
                    "day_of_week": str(
                        getattr(source_row, "DAY_OF_WEEK", "") or ""
                    ),
                    "start_time": str(
                        getattr(source_row, "START_TIME", "") or ""
                    ),
                    "end_time": str(
                        getattr(source_row, "END_TIME", "") or ""
                    ),
                    "gazetted_toll": (
                        float(source_row.GAZETTED_TOLL)
                        if pd.notna(source_row.GAZETTED_TOLL)
                        else np.nan
                    ),
                    "concession_toll": (
                        float(getattr(source_row, "CONCESSION_TOLL"))
                        if hasattr(source_row, "CONCESSION_TOLL")
                        and pd.notna(getattr(source_row, "CONCESSION_TOLL"))
                        else np.nan
                    ),
                    "remarks": str(source_row.REMARKS or ""),
                    "last_updated_date": iso_value(
                        source_row.LAST_UPDATED_DATE
                    ),
                    "source_sha256": gdb_sha256,
                }
            )
    return pd.DataFrame(rows)


def normalized_schedule(frame: pd.DataFrame) -> pd.DataFrame:
    fields = [
        "DAY_OF_WEEK",
        "START_TIME",
        "END_TIME",
        "GAZETTED_TOLL",
        "EFFECTIVE_DATE",
        "REMARKS",
        "LAST_UPDATED_DATE",
    ]
    existing = [field for field in fields if field in frame.columns]
    return (
        frame[existing]
        .fillna("")
        .astype(str)
        .drop_duplicates()
        .sort_values(existing)
        .reset_index(drop=True)
    )


def official_road_ids(traffic_row: pd.Series) -> list[int]:
    return [
        int(traffic_row[f"RD_ID_{index}"])
        for index in range(1, 10)
        if pd.notna(traffic_row.get(f"RD_ID_{index}"))
    ]


def road_names_for_ids(
    centerline: pd.DataFrame, route_ids: set[int]
) -> list[str]:
    names = centerline.loc[
        centerline["ROUTE_ID"].isin(route_ids), "STREET_ENAME"
    ]
    return sorted({str(value) for value in names.dropna()})


def resolve_alias(
    official: pd.DataFrame,
    traffic: pd.DataFrame,
    centerline: pd.DataFrame,
) -> pd.DataFrame:
    primary = official.loc[
        official["TUNNEL_BRIDGE_NAME"].eq("Western Harbour Crossing")
    ]
    backup = official.loc[
        official["TUNNEL_BRIDGE_NAME"].eq(
            "Western Harbour Crossing (Backup Toll Point)"
        )
    ]
    primary_schedule = normalized_schedule(primary)
    backup_schedule = normalized_schedule(backup)
    schedule_equal = primary_schedule.equals(backup_schedule)
    effective_equal = set(primary["EFFECTIVE_DATE"].astype(str)) == set(
        backup["EFFECTIVE_DATE"].astype(str)
    )
    update_equal = set(primary["LAST_UPDATED_DATE"].astype(str)) == set(
        backup["LAST_UPDATED_DATE"].astype(str)
    )
    shared_features = sorted(
        set(primary[["FEATURE_ID_1", "FEATURE_ID_2"]].stack().astype(int))
        & set(backup[["FEATURE_ID_1", "FEATURE_ID_2"]].stack().astype(int))
    )
    traffic_index = traffic.set_index("FEATURE_ID")
    main_point = traffic_index.loc[2684].geometry
    backup_point = traffic_index.loc[151858].geometry
    point_distance = float(main_point.distance(backup_point))
    main_roads = set(official_road_ids(traffic_index.loc[2684]))
    backup_roads = set(official_road_ids(traffic_index.loc[151858]))
    road_names = road_names_for_ids(
        centerline, main_roads | backup_roads
    )
    backup_remark = str(traffic_index.loc[151858].REMARKS or "")
    explicit_backup = "backup toll point" in backup_remark.lower()
    same_official_road = all(
        "WESTERN HARBOUR CROSSING" in name.upper() for name in road_names
    )
    resolved = bool(
        schedule_equal
        and effective_equal
        and update_equal
        and shared_features == [2684]
        and explicit_backup
        and same_official_road
    )
    status = (
        "canonical_alias_same_physical_facility"
        if resolved
        else "unresolved_alias_relationship"
    )
    return pd.DataFrame(
        [
            {
                "canonical_facility_id": "western_harbour_crossing",
                "primary_official_name": "Western Harbour Crossing",
                "backup_official_name": (
                    "Western Harbour Crossing (Backup Toll Point)"
                ),
                "primary_feature_ids": "2684|2685",
                "backup_feature_ids": "151858|2684",
                "shared_feature_ids": "|".join(map(str, shared_features)),
                "schedule_rows_primary": int(len(primary_schedule)),
                "schedule_rows_backup": int(len(backup_schedule)),
                "schedule_and_rate_equal": schedule_equal,
                "effective_date_equal": effective_equal,
                "last_updated_date_equal": update_equal,
                "remarks_equal": set(primary["REMARKS"].fillna("").astype(str))
                == set(backup["REMARKS"].fillna("").astype(str)),
                "traffic_feature_backup_remark": backup_remark,
                "official_feature_point_distance_m": point_distance,
                "official_road_route_ids": "|".join(
                    map(str, sorted(main_roads | backup_roads))
                ),
                "official_road_names": "|".join(road_names),
                "alias_status": status,
                "charge_once_per_route_passage": resolved,
                "alias_evidence": (
                    "Exact 78-row weekday/weekend schedule, rate, effective-date "
                    "and update-date equality; shared feature 2684; TRAFFIC_FEATURES "
                    "remark explicitly identifies 151858 as WHC(SB) Backup toll "
                    "point; linked official CENTERLINE roads are both Western "
                    "Harbour Crossing."
                ),
            }
        ]
    )


def unique_feature_metadata(
    inventory: pd.DataFrame,
) -> dict[int, dict[str, Any]]:
    result = {}
    for feature_id, group in inventory.groupby("feature_id"):
        canonical = sorted(set(group["canonical_facility_id"]))
        if len(canonical) != 1:
            raise ValueError(
                f"Feature {feature_id} maps to unrelated canonical facilities"
            )
        result[int(feature_id)] = {
            "canonical_facility_id": canonical[0],
            "official_facility_name": "|".join(
                sorted(set(group["official_facility_name"]))
            ),
            "official_facility_name_raw": "|".join(
                sorted(set(group["official_facility_name_raw"]))
            ),
            "feature_role_or_direction": "|".join(
                sorted(set(group["feature_role_or_direction"]))
            ),
            "effective_date": "|".join(
                sorted(set(group["effective_date"]))
            ),
        }
    return result


def build_mapping(
    inventory: pd.DataFrame,
    traffic: pd.DataFrame,
    centerline: pd.DataFrame,
    alias_status: str,
    nodes: dict[str, tuple[float, float]],
    links: dict[str, dict[str, Any]],
    links_by_route: dict[int, list[str]],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    feature_meta = unique_feature_metadata(inventory)
    traffic_index = traffic.set_index("FEATURE_ID")
    transformer = Transformer.from_crs(2326, 32650, always_xy=True)
    rows = []
    feature_audit = {}
    for feature_id, metadata in sorted(feature_meta.items()):
        if feature_id not in traffic_index.index:
            rows.append(
                {
                    "canonical_facility_id": metadata[
                        "canonical_facility_id"
                    ],
                    "official_feature_id": feature_id,
                    "matsim_link_id": "",
                    "matsim_link_direction": "",
                    "mapping_method": "U_no_official_traffic_feature",
                    "mapping_quality": "U",
                    "geometry_distance_m": np.nan,
                    "topology_evidence": "",
                    "alias_status": alias_status
                    if metadata["canonical_facility_id"]
                    == "western_harbour_crossing"
                    else "not_applicable",
                    "mapping_status": "unresolved",
                    "unresolved_reason": (
                        "Official feature absent from TRAFFIC_FEATURES"
                    ),
                    "evidence_source": "RdNet_IRNP.gdb",
                    "effective_date": metadata["effective_date"],
                }
            )
            continue

        traffic_row = traffic_index.loc[feature_id]
        official_point = Point(
            *transformer.transform(
                traffic_row.geometry.x, traffic_row.geometry.y
            )
        )
        direct_candidates = []
        for link_id in links_by_route.get(feature_id, []):
            distance = network_link_geometry(
                link_id, nodes, links
            ).distance(official_point)
            direct_candidates.append((link_id, float(distance)))

        rd_ids = official_road_ids(traffic_row)
        b_candidates = []
        for route_id in rd_ids:
            for link_id in links_by_route.get(route_id, []):
                distance = float(
                    network_link_geometry(
                        link_id, nodes, links
                    ).distance(official_point)
                )
                if distance <= OFFICIAL_RD_GEOMETRY_TOLERANCE_M:
                    b_candidates.append((link_id, route_id, distance))

        direct_valid = [
            (link_id, distance)
            for link_id, distance in direct_candidates
            if distance <= DIRECT_ID_GEOMETRY_TOLERANCE_M
        ]
        mapping_quality = "A" if direct_valid else "B" if b_candidates else "U"
        if direct_valid:
            mapped = [
                (link_id, feature_id, distance)
                for link_id, distance in direct_valid
            ]
            method = "A_exact_feature_id_and_spatially_coincident_network_route_id"
        elif b_candidates:
            mapped = b_candidates
            method = "B_official_TRAFFIC_FEATURES_RD_ID_to_network_ROUTE_ID"
        else:
            mapped = []
            method = "U_no_unique_official_topology_mapping"

        official_names = road_names_for_ids(centerline, set(rd_ids))
        feature_audit[str(feature_id)] = {
            "canonical_facility_id": metadata["canonical_facility_id"],
            "official_rd_ids": rd_ids,
            "official_road_names": official_names,
            "same_numeric_network_links": [
                {
                    "link_id": link_id,
                    "geometry_distance_m": distance,
                    "accepted_as_A": distance
                    <= DIRECT_ID_GEOMETRY_TOLERANCE_M,
                }
                for link_id, distance in direct_candidates
            ],
            "mapping_quality": mapping_quality,
            "mapped_links": [item[0] for item in mapped],
        }
        if mapped:
            for link_id, route_id, distance in mapped:
                link = links[link_id]
                rows.append(
                    {
                        "canonical_facility_id": metadata[
                            "canonical_facility_id"
                        ],
                        "official_feature_id": feature_id,
                        "official_feature_role_or_direction": metadata[
                            "feature_role_or_direction"
                        ],
                        "official_facility_name_raw": metadata[
                            "official_facility_name_raw"
                        ],
                        "official_traffic_feature_road_ids": "|".join(
                            map(str, rd_ids)
                        ),
                        "matsim_link_id": link_id,
                        "matsim_link_direction": link["direction"],
                        "mapping_method": method,
                        "mapping_quality": mapping_quality,
                        "geometry_distance_m": distance,
                        "topology_evidence": (
                            f"Official TRAFFIC_FEATURES FEATURE_ID={feature_id} "
                            f"references RD_ID={route_id}; adopted network link "
                            f"uses road_{route_id}_* and is within "
                            f"{distance:.3f} m of the transformed official point."
                        ),
                        "alias_status": (
                            alias_status
                            if metadata["canonical_facility_id"]
                            == "western_harbour_crossing"
                            else "not_applicable"
                        ),
                        "mapping_status": "mapped",
                        "unresolved_reason": "",
                        "evidence_source": (
                            "RdNet_IRNP.gdb:TRAFFIC_FEATURES|CENTERLINE;"
                            "adopted_network.xml.gz"
                        ),
                        "effective_date": metadata["effective_date"],
                        "network_link_exists": link_id in links,
                        "network_link_from_node": link["from"],
                        "network_link_to_node": link["to"],
                        "official_road_names": "|".join(official_names),
                        "same_numeric_link_candidates_rejected": "|".join(
                            f"{candidate}@{candidate_distance:.3f}m"
                            for candidate, candidate_distance in direct_candidates
                            if candidate_distance
                            > DIRECT_ID_GEOMETRY_TOLERANCE_M
                        ),
                    }
                )
        else:
            rows.append(
                {
                    "canonical_facility_id": metadata[
                        "canonical_facility_id"
                    ],
                    "official_feature_id": feature_id,
                    "official_feature_role_or_direction": metadata[
                        "feature_role_or_direction"
                    ],
                    "official_facility_name_raw": metadata[
                        "official_facility_name_raw"
                    ],
                    "official_traffic_feature_road_ids": "|".join(
                        map(str, rd_ids)
                    ),
                    "matsim_link_id": "",
                    "matsim_link_direction": "",
                    "mapping_method": method,
                    "mapping_quality": "U",
                    "geometry_distance_m": np.nan,
                    "topology_evidence": "",
                    "alias_status": (
                        alias_status
                        if metadata["canonical_facility_id"]
                        == "western_harbour_crossing"
                        else "not_applicable"
                    ),
                    "mapping_status": "unresolved",
                    "unresolved_reason": (
                        "No official RD_ID network link within mapping tolerance"
                    ),
                    "evidence_source": (
                        "RdNet_IRNP.gdb:TRAFFIC_FEATURES|CENTERLINE;"
                        "adopted_network.xml.gz"
                    ),
                    "effective_date": metadata["effective_date"],
                    "network_link_exists": False,
                    "network_link_from_node": "",
                    "network_link_to_node": "",
                    "official_road_names": "|".join(official_names),
                    "same_numeric_link_candidates_rejected": "|".join(
                        f"{candidate}@{candidate_distance:.3f}m"
                        for candidate, candidate_distance in direct_candidates
                    ),
                }
            )
    return pd.DataFrame(rows), feature_audit


def selected_plan(person: Any) -> Any | None:
    plans = [child for child in person if tag_name(child) == "plan"]
    if not plans:
        return None
    selected = [
        plan
        for plan in plans
        if plan.attrib.get("selected", "yes").lower() in {"yes", "true", "1"}
    ]
    return selected[0] if selected else plans[0]


def car_legs_in_plan(plan: Any) -> list[tuple[int, Any]]:
    main_activity_index = -1
    result = []
    for child in plan:
        name = tag_name(child)
        if name == "activity":
            activity_type = child.attrib.get("type", "")
            if not activity_type.endswith("interaction"):
                main_activity_index += 1
        elif name == "leg" and child.attrib.get("mode") == "car":
            result.append((main_activity_index, child))
    return result


def reconstruct_links(route: Any | None) -> tuple[list[str], list[str]]:
    if route is None:
        return [], []
    start = route.attrib.get("start_link", "")
    end = route.attrib.get("end_link", "")
    text_links = (route.text or "").split()
    intermediate = list(text_links)
    if intermediate and intermediate[0] == start:
        intermediate = intermediate[1:]
    if intermediate and intermediate[-1] == end:
        intermediate = intermediate[:-1]
    full = [start] if start else []
    full.extend(intermediate)
    if end and (not full or full[-1] != end):
        full.append(end)
    return full, text_links


def mapping_indices(
    link_ids: list[str],
    link_mapping: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    matches = []
    for index, link_id in enumerate(link_ids):
        for record in link_mapping.get(link_id, []):
            matches.append({"index": index, "link_id": link_id, **record})
    return matches


def facility_direction_coverage(
    inventory: pd.DataFrame, mapping: pd.DataFrame
) -> dict[str, dict[str, Any]]:
    primary = inventory.loc[
        ~inventory["official_facility_name_raw"].str.contains(
            "Backup Toll Point", case=False, na=False
        )
    ]
    expected = {
        facility: set(group["feature_id"].astype(int))
        for facility, group in primary.groupby("canonical_facility_id")
    }
    mapped_features = {
        facility: set(
            group.loc[group["mapping_status"].eq("mapped"), "official_feature_id"]
            .astype(int)
            .tolist()
        )
        for facility, group in mapping.groupby("canonical_facility_id")
    }
    result = {}
    for facility, feature_ids in sorted(expected.items()):
        mapped = feature_ids & mapped_features.get(facility, set())
        result[facility] = {
            "expected_primary_official_features": sorted(feature_ids),
            "mapped_primary_official_features": sorted(mapped),
            "missing_primary_official_features": sorted(feature_ids - mapped),
            "direction_coverage_fraction": (
                len(mapped) / len(feature_ids) if feature_ids else 0.0
            ),
            "direction_semantics": (
                "Official feature 1/2 roles covered. MATSim f/r is retained as "
                "link orientation and is not relabelled as a compass direction."
            ),
        }
    return result


def parse_leg_matches(
    plans_path: Path,
    needed_keys: set[tuple[str, int]],
    links: dict[str, dict[str, Any]],
    link_mapping: dict[str, list[dict[str, Any]]],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows = []
    seen: set[tuple[str, int]] = set()
    duplicate_keys = 0
    with gzip.open(plans_path, "rb") as handle:
        context = etree.iterparse(
            handle, events=("end",), tag="person", huge_tree=True
        )
        for _, person in context:
            person_id = str(person.attrib.get("id", ""))
            plan = selected_plan(person)
            if plan is not None:
                for sequence, leg in car_legs_in_plan(plan):
                    key = (person_id, sequence)
                    duplicate_keys += int(key in seen)
                    seen.add(key)
                    if key not in needed_keys:
                        continue
                    route = next(
                        (child for child in leg if tag_name(child) == "route"),
                        None,
                    )
                    full_links, text_links = reconstruct_links(route)
                    full_matches = mapping_indices(full_links, link_mapping)
                    text_matches = mapping_indices(text_links, link_mapping)
                    full_facilities = sorted(
                        {
                            str(match["canonical_facility_id"])
                            for match in full_matches
                        }
                    )
                    text_facilities = {
                        str(match["canonical_facility_id"])
                        for match in text_matches
                    }
                    added_facilities = sorted(
                        set(full_facilities) - text_facilities
                    )
                    unrelated_by_link = {
                        link_id: sorted(
                            {
                                str(match["canonical_facility_id"])
                                for match in full_matches
                                if match["link_id"] == link_id
                            }
                        )
                        for link_id in {
                            str(match["link_id"]) for match in full_matches
                        }
                    }
                    unrelated_by_link = {
                        link_id: facilities
                        for link_id, facilities in unrelated_by_link.items()
                        if len(facilities) > 1
                    }
                    all_links_exist = bool(full_links) and all(
                        link_id in links for link_id in full_links
                    )
                    non_contiguous = 0
                    if all_links_exist:
                        non_contiguous = sum(
                            links[left]["to"] != links[right]["from"]
                            for left, right in zip(
                                full_links, full_links[1:]
                            )
                        )
                    feature_ids = sorted(
                        {
                            int(match["official_feature_id"])
                            for match in full_matches
                        }
                    )
                    mapped_links = list(
                        dict.fromkeys(
                            str(match["link_id"]) for match in full_matches
                        )
                    )
                    directions = sorted(
                        {
                            str(match["matsim_link_direction"])
                            for match in full_matches
                        }
                    )
                    methods = sorted(
                        {str(match["mapping_method"]) for match in full_matches}
                    )
                    qualities = sorted(
                        {str(match["mapping_quality"]) for match in full_matches}
                    )
                    western_features = set(feature_ids) & {2684, 2685, 151858}
                    rows.append(
                        {
                            "person_id": person_id,
                            "leg_sequence": int(sequence),
                            "full_link_count_reparsed": int(len(full_links)),
                            "all_links_exist_reparsed": bool(all_links_exist),
                            "non_contiguous_link_pair_count_reparsed": int(
                                non_contiguous
                            ),
                            "canonical_facility_id": "|".join(
                                full_facilities
                            ),
                            "official_feature_ids": "|".join(
                                map(str, feature_ids)
                            ),
                            "matched_matsim_link_ids": "|".join(mapped_links),
                            "facility_direction": "|".join(directions),
                            "mapping_method": "|".join(methods),
                            "mapping_quality": "|".join(qualities),
                            "raw_mapping_match_count": int(len(full_matches)),
                            "physical_facility_event_count": int(
                                len(full_facilities)
                            ),
                            "unrelated_facility_mapping_links": json.dumps(
                                unrelated_by_link, sort_keys=True
                            ),
                            "start_end_added_facilities": "|".join(
                                added_facilities
                            ),
                            "alias_candidate_feature_count": int(
                                len(western_features)
                            ),
                            "alias_duplicate_candidate": bool(
                                len(western_features) > 1
                            ),
                            "departure_time_s_reparsed": parse_time_s(
                                leg.attrib.get("dep_time")
                            ),
                            "route_travel_time_s_reparsed": parse_time_s(
                                route.attrib.get("trav_time")
                                if route is not None
                                else leg.attrib.get("trav_time")
                            ),
                        }
                    )
            person.clear()
            parent = person.getparent()
            if parent is not None:
                while person.getprevious() is not None:
                    del parent[0]
    return pd.DataFrame(rows), {
        "routed_car_key_count": int(len(seen)),
        "routed_car_duplicate_key_count": int(duplicate_keys),
    }


def current_toll_by_leg(
    base_path: Path, toll_rules_path: Path
) -> pd.DataFrame:
    rules = (
        pd.read_csv(
            toll_rules_path,
            usecols=["toll_facility_id", "toll_facility_name"],
        )
        .drop_duplicates("toll_facility_id")
        .set_index("toll_facility_id")["toll_facility_name"]
        .to_dict()
    )
    name_to_canonical = {
        official_name: canonical_id
        for canonical_id, official_name in RAW_TO_CANONICAL.values()
    }
    frame = pd.read_parquet(
        base_path,
        columns=[
            "person_id",
            "leg_sequence",
            "cost_component",
            "vehicle_class",
            "toll_status",
            "toll_facilities",
        ],
    )
    toll = frame.loc[frame["cost_component"].eq("toll")].copy()
    toll["current_canonical_facility_id"] = [
        "|".join(
            sorted(
                {
                    name_to_canonical.get(
                        str(rules.get(token, token)), str(token)
                    )
                    for token in filter(None, str(value).split("|"))
                }
            )
        )
        for value in toll["toll_facilities"].fillna("")
    ]
    return toll[
        [
            "person_id",
            "leg_sequence",
            "toll_status",
            "current_canonical_facility_id",
        ]
    ].rename(columns={"toll_status": "current_car_cost_v1_toll_status"})


def identify_legs(
    previous: pd.DataFrame,
    reparsed: pd.DataFrame,
    coverage: dict[str, dict[str, Any]],
    alias_status: str,
    current: pd.DataFrame,
) -> pd.DataFrame:
    frame = previous[
        [
            "person_id",
            "leg_sequence",
            "vehicle_ref_id",
            "vehicle_class",
            "route_status",
            "full_link_count",
            "all_links_exist",
            "route_topology_contiguous",
            "toll_passage_time_estimable",
        ]
    ].merge(
        reparsed,
        on=["person_id", "leg_sequence"],
        how="left",
        validate="one_to_one",
    )
    all_directions_covered = all(
        math.isclose(
            float(record["direction_coverage_fraction"]), 1.0
        )
        for record in coverage.values()
    )
    statuses = []
    reasons = []
    alias_values = []
    for row in frame.itertuples(index=False):
        facilities = set(filter(None, str(row.canonical_facility_id).split("|")))
        unrelated = json.loads(row.unrelated_facility_mapping_links or "{}")
        structural_ready = bool(
            row.all_links_exist_reparsed
            and int(row.non_contiguous_link_pair_count_reparsed) == 0
            and int(row.full_link_count_reparsed) > 0
        )
        if row.vehicle_class == "motorcycle":
            status = "out_of_scope_motorcycle"
            reason = "MATSim car-mode leg uses motorcycle vehicle class."
        elif row.vehicle_class != "private_car":
            status = "unresolved_official_feature_mapping"
            reason = "Vehicle class is not a recognized private car."
        elif not structural_ready:
            status = "unresolved_official_feature_mapping"
            reason = "Route is incomplete, contains unknown links, or is non-contiguous."
        elif unrelated:
            status = "ambiguous_multiple_facility_mapping"
            reason = "At least one network link maps to unrelated canonical facilities."
        elif (
            "western_harbour_crossing" in facilities
            and alias_status != "canonical_alias_same_physical_facility"
        ):
            status = "unresolved_alias_relationship"
            reason = "Western Harbour Crossing primary/backup relationship unresolved."
        elif facilities:
            status = "confirmed_charge_facility_identified"
            reason = ""
        elif not all_directions_covered:
            status = "unresolved_direction_mapping"
            reason = "At least one canonical facility official direction role is unmapped."
        else:
            status = "confirmed_no_charge_all_facilities_covered"
            reason = ""
        statuses.append(status)
        reasons.append(reason)
        alias_values.append(
            alias_status
            if "western_harbour_crossing" in facilities
            else "not_applicable"
        )
    frame["toll_identification_status"] = statuses
    frame["unresolved_reason"] = reasons
    frame["alias_resolution"] = alias_values
    frame["passage_time_estimable"] = frame[
        "toll_passage_time_estimable"
    ].fillna(False)
    frame["route_status"] = np.where(
        frame["all_links_exist_reparsed"].fillna(False)
        & frame["non_contiguous_link_pair_count_reparsed"].fillna(1).eq(0),
        "route_ready_for_toll_mapping_audit",
        "unresolved_route_structure",
    )
    frame["full_link_count"] = frame["full_link_count_reparsed"].astype(int)
    frame = frame.merge(
        current,
        on=["person_id", "leg_sequence"],
        how="left",
        validate="one_to_one",
    )
    missing_current_status = pd.Series(
        np.where(
            frame["vehicle_class"].eq("motorcycle"),
            "out_of_scope_motorcycle",
            "missing",
        ),
        index=frame.index,
    )
    frame["current_car_cost_v1_toll_status"] = frame[
        "current_car_cost_v1_toll_status"
    ].where(
        frame["current_car_cost_v1_toll_status"].notna(),
        missing_current_status,
    )
    frame["current_canonical_facility_id"] = frame[
        "current_canonical_facility_id"
    ].fillna("")
    new_simple = np.select(
        [
            frame["toll_identification_status"].eq(
                "confirmed_charge_facility_identified"
            ),
            frame["toll_identification_status"].eq(
                "confirmed_no_charge_all_facilities_covered"
            ),
            frame["toll_identification_status"].eq(
                "out_of_scope_motorcycle"
            ),
        ],
        ["confirmed_charge", "confirmed_no_charge", "out_of_scope_motorcycle"],
        default="unresolved",
    )
    current_simple = np.select(
        [
            frame["current_car_cost_v1_toll_status"].eq("confirmed_charge"),
            frame["current_car_cost_v1_toll_status"].eq(
                "confirmed_no_charge"
            ),
            frame["current_car_cost_v1_toll_status"].eq(
                "out_of_scope_motorcycle"
            ),
        ],
        ["confirmed_charge", "confirmed_no_charge", "out_of_scope_motorcycle"],
        default="unresolved",
    )
    frame["differs_from_current_car_cost_v1"] = (
        new_simple != current_simple
    ) | (
        frame["canonical_facility_id"].fillna("")
        != frame["current_canonical_facility_id"].fillna("")
    )
    columns = [
        "person_id",
        "leg_sequence",
        "vehicle_ref_id",
        "vehicle_class",
        "route_status",
        "full_link_count",
        "toll_identification_status",
        "canonical_facility_id",
        "official_feature_ids",
        "matched_matsim_link_ids",
        "facility_direction",
        "mapping_method",
        "mapping_quality",
        "alias_resolution",
        "passage_time_estimable",
        "unresolved_reason",
        "raw_mapping_match_count",
        "physical_facility_event_count",
        "alias_candidate_feature_count",
        "alias_duplicate_candidate",
        "start_end_added_facilities",
        "current_car_cost_v1_toll_status",
        "current_canonical_facility_id",
        "differs_from_current_car_cost_v1",
    ]
    return frame[columns].sort_values(
        ["person_id", "leg_sequence"]
    ).reset_index(drop=True)


def required_repairs() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "repair_id": "TOLLNET-R01",
                "severity": "critical",
                "component": "feature_mapping",
                "finding": (
                    "The prototype interprets seven same-number toll-feature/"
                    "network-route IDs as direct matches, but their geometries "
                    "are separated by kilometres and belong to different ID domains."
                ),
                "required_change": (
                    "Replace same-number matching with the audited official "
                    "TRAFFIC_FEATURES FEATURE_ID -> RD_ID -> network ROUTE_ID table."
                ),
            },
            {
                "repair_id": "TOLLNET-R02",
                "severity": "critical",
                "component": "toll_output",
                "finding": (
                    "Existing confirmed-charge and confirmed-no-charge labels "
                    "were produced from the rejected same-number mapping."
                ),
                "required_change": (
                    "Regenerate toll identification and later monetary outputs "
                    "from toll_facility_network_mapping.csv."
                ),
            },
            {
                "repair_id": "TOLLNET-R03",
                "severity": "high",
                "component": "alias",
                "finding": (
                    "Western Harbour Crossing primary and backup feature sets "
                    "must be retained but deduplicated as one physical facility."
                ),
                "required_change": (
                    "Apply canonical_alias_same_physical_facility and charge no "
                    "more than once per route passage."
                ),
            },
            {
                "repair_id": "TOLLNET-R04",
                "severity": "high",
                "component": "direction",
                "finding": (
                    "MATSim f/r expresses link orientation, not an official "
                    "compass-direction label."
                ),
                "required_change": (
                    "Retain official feature 1/2 roles and f/r orientation "
                    "without inventing northbound/southbound labels."
                ),
            },
            {
                "repair_id": "TOLLNET-R05",
                "severity": "high",
                "component": "provenance",
                "finding": (
                    "Existing toll-rule provenance contains personal absolute paths."
                ),
                "required_change": (
                    "Use repository-relative paths plus input_root_role when the "
                    "toll monetary output is repaired."
                ),
            },
        ]
    )


def main() -> None:
    args = parse_args()
    input_root = args.input_project_root.resolve()
    paths = input_paths(input_root)
    hashes_before = protected_hashes(paths)

    nodes, links, links_by_route = parse_network(paths["network"])
    official, traffic, centerline = load_official_pc_rows(paths["road_gdb"])
    gdb_sha = hashes_before["road_gdb"]
    inventory = build_official_inventory(official, gdb_sha)
    alias = resolve_alias(official, traffic, centerline)
    alias_status = str(alias.iloc[0]["alias_status"])
    mapping, feature_audit = build_mapping(
        inventory,
        traffic,
        centerline,
        alias_status,
        nodes,
        links,
        links_by_route,
    )
    coverage = facility_direction_coverage(inventory, mapping)

    previous = pd.read_parquet(paths["previous_feasibility"])
    needed_keys = set(
        zip(
            previous["person_id"].astype(str),
            previous["leg_sequence"].astype(int),
            strict=False,
        )
    )
    link_mapping: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in mapping.loc[mapping["mapping_status"].eq("mapped")].itertuples(
        index=False
    ):
        link_mapping[str(row.matsim_link_id)].append(
            {
                "canonical_facility_id": str(row.canonical_facility_id),
                "official_feature_id": int(row.official_feature_id),
                "matsim_link_direction": str(row.matsim_link_direction),
                "mapping_method": str(row.mapping_method),
                "mapping_quality": str(row.mapping_quality),
            }
        )
    reparsed, route_parse = parse_leg_matches(
        paths["plans_routed"],
        needed_keys,
        links,
        dict(link_mapping),
    )
    current = current_toll_by_leg(paths["cost_base"], paths["toll_rules"])
    legs = identify_legs(
        previous, reparsed, coverage, alias_status, current
    )

    feature_grade = (
        mapping.groupby("official_feature_id")["mapping_quality"]
        .first()
        .value_counts()
        .to_dict()
    )
    feature_grade_counts = {
        grade: int(feature_grade.get(grade, 0)) for grade in ("A", "B", "C", "U")
    }
    direct_same_id_features = sorted(
        int(feature_id)
        for feature_id, record in feature_audit.items()
        if record["same_numeric_network_links"]
    )
    original_unmapped = sorted(
        set(int(value) for value in feature_audit) - set(direct_same_id_features)
    )
    original_unmapped_resolution = {
        str(feature_id): {
            "mapping_quality": feature_audit[str(feature_id)]["mapping_quality"],
            "official_rd_ids": feature_audit[str(feature_id)]["official_rd_ids"],
            "mapped_links": feature_audit[str(feature_id)]["mapped_links"],
        }
        for feature_id in original_unmapped
    }
    if len(direct_same_id_features) != 7 or len(original_unmapped) != 12:
        raise ValueError(
            "Expected seven previous same-number candidates and twelve "
            f"previously unmapped features, got {len(direct_same_id_features)} "
            f"and {len(original_unmapped)}"
        )

    status_counts = {
        str(key): int(value)
        for key, value in legs["toll_identification_status"]
        .value_counts()
        .items()
    }
    facility_hit_counts = Counter()
    feature_hit_counts = Counter()
    direction_hit_counts = Counter()
    mapped_link_hit_counts = Counter()
    for row in legs.loc[
        legs["vehicle_class"].eq("private_car")
    ].itertuples(index=False):
        facility_hit_counts.update(
            filter(None, str(row.canonical_facility_id).split("|"))
        )
        feature_hit_counts.update(
            filter(None, str(row.official_feature_ids).split("|"))
        )
        row_links = list(
            filter(None, str(row.matched_matsim_link_ids).split("|"))
        )
        mapped_link_hit_counts.update(row_links)
        row_facility_directions = {
            (
                str(record["canonical_facility_id"]),
                str(record["matsim_link_direction"]),
            )
            for link_id in row_links
            for record in link_mapping.get(link_id, [])
        }
        for facility, direction in row_facility_directions:
            direction_hit_counts[f"{facility}:{direction}"] += 1

    mapped_links = set(
        mapping.loc[
            mapping["mapping_status"].eq("mapped"), "matsim_link_id"
        ].astype(str)
    )
    unused_mapped_links = sorted(
        mapped_links - set(mapped_link_hit_counts)
    )
    same_link_unrelated = {
        link_id: sorted(
            {
                str(record["canonical_facility_id"])
                for record in records
            }
        )
        for link_id, records in link_mapping.items()
        if len(
            {
                str(record["canonical_facility_id"])
                for record in records
            }
        )
        > 1
    }
    current_no_charge = legs[
        "current_car_cost_v1_toll_status"
    ].eq("confirmed_no_charge")
    downgraded_no_charge = int(
        (
            current_no_charge
            & legs["toll_identification_status"].str.startswith(
                ("unresolved", "ambiguous")
            )
        ).sum()
    )
    alias_duplicate_candidates = int(
        legs["alias_duplicate_candidate"].sum()
    )
    duplicate_physical_charge_candidates = int(
        (
            legs["raw_mapping_match_count"].gt(
                legs["physical_facility_event_count"]
            )
        ).sum()
    )
    physical_event_rows = [
        (str(row.person_id), int(row.leg_sequence), facility)
        for row in legs.itertuples(index=False)
        for facility in set(
            filter(None, str(row.canonical_facility_id).split("|"))
        )
    ]
    physical_event_frame = pd.DataFrame(
        physical_event_rows,
        columns=["person_id", "leg_sequence", "canonical_facility_id"],
    )
    duplicate_physical_charge_rows_emitted = int(
        physical_event_frame.duplicated(
            ["person_id", "leg_sequence", "canonical_facility_id"]
        ).sum()
    )
    route_legs_with_multiple_physical_facilities = int(
        legs["physical_facility_event_count"].gt(1).sum()
    )
    new_status_simple = legs["toll_identification_status"].replace(
        {
            "confirmed_charge_facility_identified": "confirmed_charge",
            "confirmed_no_charge_all_facilities_covered": (
                "confirmed_no_charge"
            ),
        }
    )
    current_vs_new_status_crosstab = {
        str(current_status): {
            str(new_status): int(count)
            for new_status, count in new_counts.items()
        }
        for current_status, new_counts in pd.crosstab(
            legs["current_car_cost_v1_toll_status"],
            new_status_simple,
        ).to_dict(orient="index").items()
    }

    grid_sidecars = shapefile_sidecars(paths["fixed_link_grid_shp"])
    hashes_after = protected_hashes(paths)
    if hashes_before != hashes_after:
        raise RuntimeError("Protected inputs changed during toll mapping audit")

    all_features_mapped = feature_grade_counts["U"] == 0
    all_facilities_covered = all(
        math.isclose(record["direction_coverage_fraction"], 1.0)
        for record in coverage.values()
    )
    alias_resolved = alias_status == "canonical_alias_same_physical_facility"
    route_keys_valid = bool(
        len(legs) == 67718
        and not legs.duplicated(["person_id", "leg_sequence"]).any()
        and set(
            zip(
                legs["person_id"],
                legs["leg_sequence"],
                strict=False,
            )
        )
        == needed_keys
    )
    existing_cost_hashes_unchanged = all(
        hashes_before[key] == hashes_after[key]
        for key in ("cost_low", "cost_base", "cost_high")
    )
    next_stage_eligible = bool(
        all_features_mapped
        and all_facilities_covered
        and alias_resolved
        and route_keys_valid
        and existing_cost_hashes_unchanged
        and not same_link_unrelated
    )

    validation = {
        "audit": "Hong Kong private car toll facility-network mapping audit v1",
        "input_root_role": "canonical_project_read_only",
        "toll_amounts_calculated": False,
        "toll_monetary_estimation_not_authorised": True,
        "official_private_car_pc_source_rows": {
            str(key): int(value)
            for key, value in official["source_layer"].value_counts().items()
        },
        "canonical_facility_count": int(
            inventory["canonical_facility_id"].nunique()
        ),
        "official_raw_facility_name_count": int(
            inventory["official_facility_name_raw"].nunique()
        ),
        "official_feature_count": int(inventory["feature_id"].nunique()),
        "mapping_quality_feature_counts": feature_grade_counts,
        "feature_mapping_audit": feature_audit,
        "same_numeric_feature_route_id_collision_count": int(
            len(direct_same_id_features)
        ),
        "same_numeric_feature_route_id_collisions": direct_same_id_features,
        "original_twelve_unmapped_feature_ids": original_unmapped,
        "original_twelve_unmapped_resolution": original_unmapped_resolution,
        "alias_resolution": alias.iloc[0].to_dict(),
        "facility_direction_coverage": coverage,
        "all_canonical_facility_directions_covered": all_facilities_covered,
        "mapped_links_exist_in_network": bool(
            mapping.loc[mapping["mapping_status"].eq("mapped"), "network_link_exists"].all()
        ),
        "mapped_link_direction_suffix_valid": bool(
            mapping.loc[
                mapping["mapping_status"].eq("mapped"),
                "matsim_link_direction",
            ].isin(["f", "r"]).all()
        ),
        "same_network_link_maps_unrelated_facilities": same_link_unrelated,
        "mapped_links_unused_by_any_car_route": unused_mapped_links,
        "mapped_link_private_car_hit_counts": dict(
            sorted(mapped_link_hit_counts.items())
        ),
        "route_parse": route_parse,
        "car_leg_count": int(len(legs)),
        "car_leg_key_unique": bool(
            not legs.duplicated(["person_id", "leg_sequence"]).any()
        ),
        "car_leg_keys_match_previous_audit": route_keys_valid,
        "private_car_leg_count": int(
            legs["vehicle_class"].eq("private_car").sum()
        ),
        "motorcycle_leg_count": int(
            legs["vehicle_class"].eq("motorcycle").sum()
        ),
        "toll_identification_status_counts": status_counts,
        "canonical_facility_private_car_hit_counts": {
            facility: int(facility_hit_counts.get(facility, 0))
            for facility in sorted(coverage)
        },
        "official_feature_private_car_hit_counts": {
            str(feature_id): int(feature_hit_counts.get(str(feature_id), 0))
            for feature_id in sorted(int(value) for value in feature_audit)
        },
        "facility_direction_private_car_hit_counts": dict(
            sorted(direction_hit_counts.items())
        ),
        "start_end_added_facility_hit_legs": int(
            legs["start_end_added_facilities"].ne("").sum()
        ),
        "alias_duplicate_candidate_leg_count": alias_duplicate_candidates,
        "route_legs_with_multiple_raw_candidates_after_physical_dedup": (
            duplicate_physical_charge_candidates
        ),
        "route_legs_with_multiple_physical_facilities": (
            route_legs_with_multiple_physical_facilities
        ),
        "duplicate_physical_toll_charge_rows_emitted": (
            duplicate_physical_charge_rows_emitted
        ),
        "current_vs_new_status_crosstab": current_vs_new_status_crosstab,
        "legs_different_from_current_car_cost_v1": int(
            legs["differs_from_current_car_cost_v1"].sum()
        ),
        "current_confirmed_no_charge_downgraded_to_unresolved": (
            downgraded_no_charge
        ),
        "protected_hashes_before": hashes_before,
        "protected_hashes_after": hashes_after,
        "protected_inputs_unchanged": hashes_before == hashes_after,
        "existing_low_base_high_parquet_hashes_unchanged": (
            existing_cost_hashes_unchanged
        ),
        "fixed_link_grid_shapefile_bundle": {
            "combined_sha256": hashes_before["fixed_link_grid_bundle"],
            "sidecars": [
                {
                    "name": child.name,
                    "size_bytes": child.stat().st_size,
                    "sha256": sha256_file(child),
                }
                for child in grid_sidecars
            ],
        },
        "eligible_for_next_rate_application_and_output_repair_stage": (
            next_stage_eligible
        ),
        "next_stage_condition": (
            "Mapping and alias evidence are complete, but no monetary result is "
            "authorised in this audit. A separate repair stage must apply rates "
            "and rebuild outputs from this mapping."
        ),
    }

    repairs = required_repairs()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    inventory.to_csv(
        args.output_dir / "official_toll_feature_inventory.csv",
        index=False,
        encoding="utf-8",
    )
    alias.to_csv(
        args.output_dir / "toll_feature_alias_resolution.csv",
        index=False,
        encoding="utf-8",
    )
    mapping.to_csv(
        args.output_dir / "toll_facility_network_mapping.csv",
        index=False,
        encoding="utf-8",
    )
    legs.to_parquet(
        args.output_dir / "car_leg_toll_identification.parquet",
        index=False,
        compression="zstd",
    )
    repairs.to_csv(
        args.output_dir / "toll_mapping_required_repairs.csv",
        index=False,
        encoding="utf-8",
    )
    (args.output_dir / "toll_network_mapping_validation.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "official_feature_count": validation[
                    "official_feature_count"
                ],
                "mapping_quality_feature_counts": feature_grade_counts,
                "alias_status": alias_status,
                "status_counts": status_counts,
                "legs_different_from_current": validation[
                    "legs_different_from_current_car_cost_v1"
                ],
                "protected_inputs_unchanged": True,
                "next_stage_eligible": next_stage_eligible,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
