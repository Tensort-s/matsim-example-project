#!/usr/bin/env python3
"""Audit Hong Kong private-car cost input feasibility without computing costs."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import re
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
from lxml import etree
from shapely.geometry import Point


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "data/transport_costs/hongkong/car_cost_v1/input_feasibility"
)
CAR_COST_ROOT = REPO_ROOT / "data/transport_costs/hongkong/car_cost_v1"
ROAD_LINK_RE = re.compile(r"^road_(\d+)_")
ABSOLUTE_WINDOWS_PATH_RE = re.compile(r"(?i)(?<![a-z])(?:[a-z]:[\\/])")

INPUT_SPECS = {
    "plans_routed": {
        "relative_path": (
            "data/matsim_agents/hongkong/"
            "typical_weekday_5pct_v2_activity_modechoice/"
            "plans_routed_5pct_v2.xml.gz"
        ),
        "format": "MATSim population XML compressed with gzip",
        "actual_reads": {
            "elements": ["person", "attributes", "plan", "activity", "leg", "route"],
            "fields": [
                "person.id",
                "person.attributes.assignedVehicleId",
                "person.attributes.householdId",
                "plan.selected",
                "activity.type",
                "activity.facility",
                "leg.mode",
                "leg.dep_time",
                "leg.trav_time",
                "route.type",
                "route.start_link",
                "route.end_link",
                "route.trav_time",
                "route.distance",
                "route.vehicleRefId",
                "route.text_link_ids",
            ],
        },
    },
    "plans_unrouted": {
        "relative_path": (
            "data/matsim_agents/hongkong/"
            "typical_weekday_5pct_v2_activity_modechoice/"
            "plans_unrouted_5pct_v2.xml.gz"
        ),
        "format": "MATSim population XML compressed with gzip",
        "actual_reads": {
            "elements": ["person", "plan", "activity", "leg"],
            "fields": ["person.id", "plan.selected", "activity.type", "leg.mode"],
        },
    },
    "facilities": {
        "relative_path": (
            "data/matsim_agents/hongkong/"
            "typical_weekday_5pct_v2_activity_modechoice/"
            "facilities_5pct_v2.xml.gz"
        ),
        "format": "MATSim facilities XML compressed with gzip",
        "actual_reads": {
            "elements": ["facility"],
            "fields": ["facility.id", "facility.x", "facility.y", "facility.linkId"],
        },
    },
    "private_vehicles": {
        "relative_path": (
            "data/matsim_agents/hongkong/"
            "typical_weekday_5pct_v2_activity_modechoice/"
            "privateVehicles_5pct.xml.gz"
        ),
        "format": "MATSim vehicle definitions XML compressed with gzip",
        "actual_reads": {
            "elements": [
                "vehicleDefinitions",
                "vehicleType",
                "capacity",
                "length",
                "width",
                "passengerCarEquivalents",
                "networkMode",
                "vehicle",
            ],
            "fields": [
                "vehicleType.id",
                "capacity.seats",
                "capacity.standingRoomInPersons",
                "length.meter",
                "width.meter",
                "passengerCarEquivalents.pce",
                "networkMode.networkMode",
                "vehicle.id",
                "vehicle.type",
            ],
        },
    },
    "trip_manifest": {
        "relative_path": (
            "data/matsim_agents/hongkong/"
            "typical_weekday_5pct_v2_activity_modechoice/"
            "agent_trip_manifest_v2.parquet"
        ),
        "format": "Apache Parquet",
        "actual_reads": {
            "table": "agent_trip_manifest_v2",
            "fields": [
                "person_id",
                "leg_sequence",
                "population_group",
                "role",
                "mode",
                "origin_type",
                "destination_type",
                "origin_facility_id",
                "destination_facility_id",
                "departure_time_s",
                "is_discretionary",
            ],
        },
    },
    "config": {
        "relative_path": (
            "data/matsim_agents/hongkong/"
            "typical_weekday_5pct_v2_activity_modechoice/"
            "config_hong_kong_5pct_v2_activity_modechoice_50it.xml"
        ),
        "format": "MATSim config XML",
        "actual_reads": {
            "elements": ["config", "module", "param", "parameterset"],
            "fields": [
                "module.name",
                "param.name",
                "param.value",
                "parameterset.type",
            ],
        },
    },
    "network": {
        "relative_path": (
            "data/transit/hongkong/processed/"
            "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_"
            "ferry_core_v1_cap010/network.xml.gz"
        ),
        "format": "MATSim network XML compressed with gzip",
        "actual_reads": {
            "elements": ["node", "link"],
            "fields": [
                "node.id",
                "link.id",
                "link.from",
                "link.to",
                "link.length",
                "link.modes",
            ],
        },
    },
    "road_gdb": {
        "relative_path": "data/transit/hongkong/RdNet_IRNP.gdb",
        "format": "Esri File Geodatabase directory",
        "actual_reads": {
            "layers": ["TUN_BRIDGE_TOLL", "TUN_BRIDGE_TV_TOLL"],
            "fields": [
                "TUNNEL_BRIDGE_NAME",
                "TUNNEL_BRIDGE_CHINESE_NAME",
                "FEATURE_ID_1",
                "FEATURE_ID_2",
                "EFFECTIVE_DATE",
                "GAZETTED_TOLL",
                "CONCESSION_TOLL",
                "VEHICLE_CLASS_DESCRIPTION",
                "DAY_OF_WEEK",
                "START_TIME",
                "END_TIME",
                "REMARKS",
                "LAST_UPDATED_DATE",
            ],
        },
    },
    "synthetic_households": {
        "relative_path": (
            "data/matsim_agents/hongkong/synthetic_households_tcs2022/"
            "synthetic_households.parquet"
        ),
        "format": "Apache Parquet",
        "actual_reads": {
            "table": "synthetic_households",
            "fields": [
                "household_id",
                "grid_id",
                "tcs_zone",
                "private_car_count",
                "motorcycle_count",
                "private_vehicle_count",
            ],
        },
    },
    "fixed_link_grid": {
        "relative_path": (
            "data/worldcommuting_od/hongkong/custom_features/"
            "hong_kong_fixed_link_grid/CityAndRegionSplit/"
            "hong_kong_fixed_link_grid/regions.shp"
        ),
        "format": "ESRI Shapefile main geometry file",
        "actual_reads": {
            "layer": "regions",
            "fields": ["grid_id", "geometry"],
        },
    },
}

ENERGY_STATUSES = {
    "ready_distance_only",
    "unresolved_route_distance",
    "out_of_scope_motorcycle",
    "unresolved_vehicle_class",
}
TOLL_STATUSES = {
    "route_ready_for_toll_matching",
    "ambiguous_incomplete_route",
    "unresolved_unknown_network_link",
    "unresolved_non_contiguous_route",
    "unresolved_toll_feature_mapping",
    "out_of_scope_vehicle_class",
}
PARKING_STATUSES = {
    "ready_home_fixed_parking_separate",
    "ready_duration_and_proxy_zone",
    "unresolved_duration",
    "unresolved_destination_zone",
    "unresolved_vehicle_chain",
    "unresolved_activity_type",
    "out_of_scope_vehicle_class",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-project-root",
        type=Path,
        required=True,
        help="Canonical project root; it is read only and is not written to outputs.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def tag_name(element: Any) -> str:
    return str(element.tag).rsplit("}", 1)[-1]


def parse_time_s(value: object) -> float:
    if value is None or value == "":
        return float("nan")
    if isinstance(value, (int, float)):
        return float(value)
    parts = str(value).split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    return float(value)


def finite(value: object) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


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


def path_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def git_path_state(project_root: Path, relative_path: str) -> str:
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relative_path],
        cwd=project_root,
        capture_output=True,
        check=False,
    )
    if tracked.returncode == 0:
        return "git_tracked"
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "--", relative_path],
        cwd=project_root,
        capture_output=True,
        check=False,
    )
    if ignored.returncode == 0:
        return "git_ignored_external_read_only"
    return "git_untracked_external_read_only"


def resolve_required_inputs(input_root: Path) -> dict[str, Path]:
    resolved = {
        key: input_root / str(spec["relative_path"])
        for key, spec in INPUT_SPECS.items()
    }
    missing = [
        str(INPUT_SPECS[key]["relative_path"])
        for key, path in resolved.items()
        if not path.exists()
    ]
    if missing:
        raise FileNotFoundError(
            "Required inputs are missing; no output directory was created: "
            + json.dumps(missing, ensure_ascii=False)
        )
    return resolved


def input_hashes(paths: dict[str, Path]) -> dict[str, str]:
    return {
        key: (
            sha256_file_bundle(shapefile_sidecars(path))
            if key == "fixed_link_grid"
            else sha256_directory(path)
            if path.is_dir()
            else sha256_file(path)
        )
        for key, path in paths.items()
    }


def build_inventory(
    input_root: Path, paths: dict[str, Path], hashes: dict[str, str]
) -> list[dict[str, Any]]:
    rows = []
    for key, spec in INPUT_SPECS.items():
        path = paths[key]
        sidecars = shapefile_sidecars(path) if key == "fixed_link_grid" else []
        rows.append(
            {
                "input_id": key,
                "repository_relative_path": spec["relative_path"],
                "input_root_role": "canonical_project_read_only",
                "exists": path.exists(),
                "path_kind": (
                    "shapefile_bundle"
                    if key == "fixed_link_grid"
                    else "directory"
                    if path.is_dir()
                    else "file"
                ),
                "size_bytes": (
                    sum(child.stat().st_size for child in sidecars)
                    if sidecars
                    else path_size(path)
                ),
                "sha256": hashes[key],
                "sha256_scope": (
                    "sorted_combination_of_all_same_stem_sidecars"
                    if sidecars
                    else "directory_tree"
                    if path.is_dir()
                    else "file"
                ),
                "shapefile_sidecars": [
                    {
                        "name": child.name,
                        "size_bytes": child.stat().st_size,
                        "sha256": sha256_file(child),
                    }
                    for child in sidecars
                ],
                "git_state": git_path_state(
                    input_root, str(spec["relative_path"]).replace("\\", "/")
                ),
                "format": spec["format"],
                "actual_reads": spec["actual_reads"],
            }
        )
    return rows


def parse_network(path: Path) -> tuple[dict[str, tuple[str, str, float]], dict[int, list[str]]]:
    links: dict[str, tuple[str, str, float]] = {}
    feature_links: dict[int, list[str]] = defaultdict(list)
    with gzip.open(path, "rb") as handle:
        for _, element in ET.iterparse(handle, events=("end",)):
            if tag_name(element) == "link":
                link_id = element.attrib.get("id", "")
                links[link_id] = (
                    element.attrib.get("from", ""),
                    element.attrib.get("to", ""),
                    float(element.attrib.get("length", "nan")),
                )
                match = ROAD_LINK_RE.match(link_id)
                if match:
                    feature_links[int(match.group(1))].append(link_id)
            element.clear()
    return links, dict(feature_links)


def parse_vehicle_definitions(
    path: Path,
) -> tuple[dict[str, str], dict[str, dict[str, Any]], set[str], set[str]]:
    vehicle_types: dict[str, dict[str, Any]] = {}
    vehicles: dict[str, str] = {}
    vehicle_attribute_names: set[str] = set()
    vehicle_type_child_names: set[str] = set()
    with gzip.open(path, "rb") as handle:
        tree = ET.parse(handle)
    root = tree.getroot()
    for element in root:
        name = tag_name(element)
        if name == "vehicleType":
            type_id = element.attrib.get("id", "")
            row: dict[str, Any] = {"id": type_id}
            vehicle_attribute_names.update(element.attrib)
            for child in element:
                child_name = tag_name(child)
                vehicle_type_child_names.add(child_name)
                vehicle_attribute_names.update(
                    f"{child_name}.{field}" for field in child.attrib
                )
                row[child_name] = dict(child.attrib)
            vehicle_types[type_id] = row
        elif name == "vehicle":
            vehicle_attribute_names.update(element.attrib)
            vehicles[element.attrib.get("id", "")] = element.attrib.get("type", "")
    return vehicles, vehicle_types, vehicle_attribute_names, vehicle_type_child_names


def load_toll_features(
    path: Path,
) -> tuple[
    dict[int, set[str]],
    dict[str, Any],
    dict[str, list[str]],
]:
    layers = pyogrio.list_layers(path)
    actual_layer_names = [str(row[0]) for row in layers]
    requested = ["TUN_BRIDGE_TOLL", "TUN_BRIDGE_TV_TOLL"]
    missing = [layer for layer in requested if layer not in actual_layer_names]
    if missing:
        raise ValueError(f"Missing toll layers: {missing}")

    feature_to_facilities: dict[int, set[str]] = defaultdict(set)
    layer_fields: dict[str, list[str]] = {}
    private_car_rows = {}
    effective_dates: dict[str, list[str]] = {}
    for layer in requested:
        frame = pyogrio.read_dataframe(path, layer=layer, read_geometry=False)
        layer_fields[layer] = [str(column) for column in frame.columns]
        pc = frame.loc[
            frame["VEHICLE_CLASS_DESCRIPTION"].astype(str).str.upper().eq("PC")
        ].copy()
        private_car_rows[layer] = int(len(pc))
        effective_dates[layer] = sorted(
            {
                str(value)
                for value in pc["EFFECTIVE_DATE"].dropna().astype(str).tolist()
            }
        )
        for row in pc.itertuples(index=False):
            facility = str(row.TUNNEL_BRIDGE_NAME)
            for field in ("FEATURE_ID_1", "FEATURE_ID_2"):
                value = getattr(row, field)
                if pd.notna(value):
                    feature_to_facilities[int(value)].add(facility)

    conflicts = {
        str(feature): sorted(facilities)
        for feature, facilities in feature_to_facilities.items()
        if len(facilities) > 1
    }
    metadata = {
        "actual_layers": actual_layer_names,
        "toll_layers": requested,
        "layer_fields": layer_fields,
        "private_car_rows": private_car_rows,
        "private_car_effective_dates": effective_dates,
        "direction_field_present": any(
            "DIRECTION" in field.upper()
            for fields in layer_fields.values()
            for field in fields
        ),
        "direction_encoding": (
            "No explicit direction field; FEATURE_ID_1 and FEATURE_ID_2 provide "
            "the two official road-feature identifiers."
        ),
        "feature_id_conflicts": conflicts,
    }
    facility_features: dict[str, list[str]] = defaultdict(list)
    for feature, facilities in feature_to_facilities.items():
        for facility in facilities:
            facility_features[facility].append(str(feature))
    return (
        dict(feature_to_facilities),
        metadata,
        {facility: sorted(features, key=int) for facility, features in facility_features.items()},
    )


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


def person_attributes(person: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    for child in person:
        if tag_name(child) != "attributes":
            continue
        for attribute in child:
            if tag_name(attribute) == "attribute":
                result[attribute.attrib.get("name", "")] = attribute.text or ""
        break
    return result


def main_activities_and_legs(plan: Any) -> tuple[list[tuple[int, Any]], list[tuple[int, Any]]]:
    main_activities: list[tuple[int, Any]] = []
    legs: list[tuple[int, Any]] = []
    main_activity_index = -1
    for child_position, child in enumerate(plan):
        name = tag_name(child)
        if name == "activity":
            activity_type = child.attrib.get("type", "")
            if not activity_type.endswith("interaction"):
                main_activity_index += 1
                main_activities.append((child_position, child))
        elif name == "leg":
            legs.append((main_activity_index, child))
    return main_activities, legs


def activity_for_sequence(
    main_activities: list[tuple[int, Any]], sequence: int
) -> tuple[Any | None, Any | None]:
    origin = main_activities[sequence][1] if 0 <= sequence < len(main_activities) else None
    destination = (
        main_activities[sequence + 1][1]
        if 0 <= sequence + 1 < len(main_activities)
        else None
    )
    return origin, destination


def toll_facilities_for_links(
    link_ids: list[str], feature_to_facilities: dict[int, set[str]]
) -> tuple[set[str], set[int]]:
    facilities: set[str] = set()
    conflicted_features: set[int] = set()
    for link_id in link_ids:
        match = ROAD_LINK_RE.match(link_id)
        if not match:
            continue
        feature = int(match.group(1))
        mapped = feature_to_facilities.get(feature, set())
        facilities.update(mapped)
        if len(mapped) > 1:
            conflicted_features.add(feature)
    return facilities, conflicted_features


def parse_routed_car_legs(
    path: Path,
    needed_keys: set[tuple[str, int]],
    network_links: dict[str, tuple[str, str, float]],
    feature_to_facilities: dict[int, set[str]],
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, dict[str, str]]]:
    rows: list[dict[str, Any]] = []
    person_context: dict[str, dict[str, str]] = {}
    duplicate_keys = 0
    seen_keys: set[tuple[str, int]] = set()
    route_text_start_count = 0
    route_text_end_count = 0

    with gzip.open(path, "rb") as handle:
        context = etree.iterparse(
            handle, events=("end",), tag="person", huge_tree=True, recover=False
        )
        for _, person in context:
            person_id = str(person.attrib.get("id", ""))
            plan = selected_plan(person)
            if plan is not None:
                attributes = person_attributes(person)
                main_activities, legs = main_activities_and_legs(plan)
                for sequence, leg in legs:
                    if leg.attrib.get("mode", "") != "car":
                        continue
                    key = (person_id, sequence)
                    if key in seen_keys:
                        duplicate_keys += 1
                    seen_keys.add(key)
                    if key not in needed_keys:
                        continue
                    origin, destination = activity_for_sequence(
                        main_activities, sequence
                    )
                    route = next(
                        (child for child in leg if tag_name(child) == "route"), None
                    )
                    start_link = (
                        route.attrib.get("start_link", "") if route is not None else ""
                    )
                    end_link = (
                        route.attrib.get("end_link", "") if route is not None else ""
                    )
                    route_text_links = (
                        (route.text or "").split() if route is not None else []
                    )
                    if route_text_links and route_text_links[0] == start_link:
                        route_text_start_count += 1
                    if route_text_links and route_text_links[-1] == end_link:
                        route_text_end_count += 1

                    intermediate_links = list(route_text_links)
                    if intermediate_links and intermediate_links[0] == start_link:
                        intermediate_links = intermediate_links[1:]
                    if intermediate_links and intermediate_links[-1] == end_link:
                        intermediate_links = intermediate_links[:-1]
                    full_links: list[str] = []
                    if start_link:
                        full_links.append(start_link)
                    full_links.extend(intermediate_links)
                    if end_link and (not full_links or end_link != full_links[-1]):
                        full_links.append(end_link)

                    unknown_links = [
                        link_id for link_id in full_links if link_id not in network_links
                    ]
                    all_links_exist = bool(full_links) and not unknown_links
                    topology_contiguous = False
                    non_contiguous_pair_count = 0
                    network_distance_sum_m = float("nan")
                    if all_links_exist:
                        non_contiguous_pair_count = sum(
                            network_links[left][1] != network_links[right][0]
                            for left, right in zip(full_links, full_links[1:])
                        )
                        topology_contiguous = non_contiguous_pair_count == 0
                        network_distance_sum_m = float(
                            sum(network_links[link_id][2] for link_id in full_links)
                        )

                    full_tolls, conflict_features = toll_facilities_for_links(
                        full_links, feature_to_facilities
                    )
                    text_tolls, _ = toll_facilities_for_links(
                        route_text_links, feature_to_facilities
                    )
                    added_tolls = full_tolls - text_tolls
                    route_type = (
                        route.attrib.get("type", "") if route is not None else ""
                    )
                    if (
                        route is None
                        or not start_link
                        or not end_link
                        or not full_links
                        or route_type != "links"
                    ):
                        route_status = "ambiguous_incomplete_route"
                    elif unknown_links:
                        route_status = "unresolved_unknown_network_link"
                    elif not topology_contiguous:
                        route_status = "unresolved_non_contiguous_route"
                    elif conflict_features:
                        route_status = "unresolved_toll_feature_mapping"
                    else:
                        route_status = "route_ready_for_toll_matching"

                    departure_time = parse_time_s(leg.attrib.get("dep_time"))
                    route_travel_time = parse_time_s(
                        route.attrib.get("trav_time")
                        if route is not None
                        else leg.attrib.get("trav_time")
                    )
                    if not finite(route_travel_time):
                        route_travel_time = parse_time_s(leg.attrib.get("trav_time"))
                    route_distance = (
                        float(route.attrib["distance"])
                        if route is not None
                        and route.attrib.get("distance") not in (None, "")
                        else float("nan")
                    )
                    person_context[person_id] = {
                        "household_id": attributes.get("householdId", ""),
                        "assigned_vehicle_id": attributes.get(
                            "assignedVehicleId", ""
                        ),
                    }
                    rows.append(
                        {
                            "person_id": person_id,
                            "leg_sequence": int(sequence),
                            "routed_mode": "car",
                            "vehicle_ref_id": (
                                route.attrib.get("vehicleRefId", "")
                                if route is not None
                                else ""
                            ),
                            "route_type": route_type,
                            "route_distance_m": route_distance,
                            "route_start_link": start_link,
                            "route_end_link": end_link,
                            "intermediate_link_count": int(len(intermediate_links)),
                            "full_link_count": int(len(full_links)),
                            "all_links_exist": bool(all_links_exist),
                            "route_topology_contiguous": bool(topology_contiguous),
                            "route_status": route_status,
                            "departure_time_s": departure_time,
                            "route_travel_time_s": route_travel_time,
                            "arrival_time_s": (
                                departure_time + route_travel_time
                                if finite(departure_time)
                                and finite(route_travel_time)
                                else float("nan")
                            ),
                            "origin_facility_id_routed": (
                                origin.attrib.get("facility", "")
                                if origin is not None
                                else ""
                            ),
                            "destination_facility_id_routed": (
                                destination.attrib.get("facility", "")
                                if destination is not None
                                else ""
                            ),
                            "destination_activity_type_routed": (
                                destination.attrib.get("type", "")
                                if destination is not None
                                else ""
                            ),
                            "unknown_network_link_count": int(len(unknown_links)),
                            "non_contiguous_link_pair_count": int(
                                non_contiguous_pair_count
                            ),
                            "repeated_link_occurrence_count": int(
                                len(full_links) - len(set(full_links))
                            ),
                            "immediate_repeated_link_count": int(
                                sum(
                                    left == right
                                    for left, right in zip(full_links, full_links[1:])
                                )
                            ),
                            "network_distance_sum_m": network_distance_sum_m,
                            "toll_facilities_full": "|".join(sorted(full_tolls)),
                            "toll_facilities_route_text": "|".join(
                                sorted(text_tolls)
                            ),
                            "toll_start_end_added_facilities": "|".join(
                                sorted(added_tolls)
                            ),
                            "toll_mapping_conflict_feature_ids": "|".join(
                                str(value) for value in sorted(conflict_features)
                            ),
                            "toll_passage_time_estimable": bool(
                                route_status == "route_ready_for_toll_matching"
                                and finite(departure_time)
                                and finite(route_travel_time)
                            ),
                            "route_text_includes_start_link": bool(
                                route_text_links
                                and route_text_links[0] == start_link
                            ),
                            "route_text_includes_end_link": bool(
                                route_text_links and route_text_links[-1] == end_link
                            ),
                        }
                    )
            person.clear()
            parent = person.getparent()
            if parent is not None:
                while person.getprevious() is not None:
                    del parent[0]

    frame = pd.DataFrame(rows)
    diagnostics = {
        "parsed_routed_car_keys": int(len(seen_keys)),
        "duplicate_routed_car_keys": int(duplicate_keys),
        "route_text_includes_start_link_count": int(route_text_start_count),
        "route_text_includes_end_link_count": int(route_text_end_count),
    }
    return frame, diagnostics, person_context


def parse_unrouted_car_keys(path: Path) -> tuple[set[tuple[str, int]], int]:
    keys: set[tuple[str, int]] = set()
    duplicate_count = 0
    with gzip.open(path, "rb") as handle:
        context = etree.iterparse(
            handle, events=("end",), tag="person", huge_tree=True, recover=False
        )
        for _, person in context:
            person_id = str(person.attrib.get("id", ""))
            plan = selected_plan(person)
            if plan is not None:
                _, legs = main_activities_and_legs(plan)
                for sequence, leg in legs:
                    if leg.attrib.get("mode", "") == "car":
                        key = (person_id, sequence)
                        duplicate_count += int(key in keys)
                        keys.add(key)
            person.clear()
            parent = person.getparent()
            if parent is not None:
                while person.getprevious() is not None:
                    del parent[0]
    return keys, duplicate_count


def parse_facilities(path: Path, needed_ids: set[str]) -> pd.DataFrame:
    rows = []
    with gzip.open(path, "rb") as handle:
        for _, element in ET.iterparse(handle, events=("end",)):
            if tag_name(element) == "facility":
                facility_id = element.attrib.get("id", "")
                if facility_id in needed_ids:
                    rows.append(
                        {
                            "facility_id": facility_id,
                            "facility_x": (
                                float(element.attrib["x"])
                                if element.attrib.get("x")
                                else float("nan")
                            ),
                            "facility_y": (
                                float(element.attrib["y"])
                                if element.attrib.get("y")
                                else float("nan")
                            ),
                            "facility_link_id": element.attrib.get("linkId", ""),
                        }
                    )
            element.clear()
    frame = pd.DataFrame(rows)
    if not frame.empty and frame["facility_id"].duplicated().any():
        raise ValueError("Duplicate facility IDs in facilities input")
    return frame


def grid_to_tcs_lookup(path: Path) -> dict[int, int]:
    frame = pd.read_parquet(path, columns=["grid_id", "tcs_zone"])
    frame = frame.loc[frame["tcs_zone"].between(1, 26)]
    modal = (
        frame.groupby(["grid_id", "tcs_zone"], as_index=False)
        .size()
        .sort_values(
            ["grid_id", "size", "tcs_zone"],
            ascending=[True, False, True],
        )
        .drop_duplicates("grid_id")
    )
    return {
        int(row.grid_id): int(row.tcs_zone)
        for row in modal.itertuples(index=False)
    }


def facility_zone_lookup(
    facilities: pd.DataFrame,
    regions_path: Path,
    grid_to_tcs: dict[int, int],
) -> dict[str, int]:
    result: dict[str, int] = {}
    for facility_id in facilities["facility_id"].astype(str):
        if "_grid_" not in facility_id:
            continue
        suffix = facility_id.rsplit("_grid_", 1)[1]
        if suffix.isdigit() and int(suffix) in grid_to_tcs:
            result[facility_id] = grid_to_tcs[int(suffix)]

    unresolved = facilities.loc[
        ~facilities["facility_id"].astype(str).isin(result)
        & facilities["facility_x"].notna()
        & facilities["facility_y"].notna()
    ].copy()
    if unresolved.empty:
        return result

    regions = gpd.read_file(regions_path)[["grid_id", "geometry"]].copy()
    regions["grid_id"] = regions["grid_id"].astype(int)
    regions["tcs_zone"] = regions["grid_id"].map(grid_to_tcs)
    points = gpd.GeoDataFrame(
        unresolved[["facility_id"]],
        geometry=[
            Point(x, y)
            for x, y in zip(
                unresolved["facility_x"], unresolved["facility_y"]
            )
        ],
        crs=regions.crs,
    )
    joined = gpd.sjoin(
        points,
        regions[["grid_id", "tcs_zone", "geometry"]],
        how="left",
        predicate="within",
    ).sort_values(["facility_id", "grid_id"], na_position="last")
    joined = joined.drop_duplicates("facility_id")
    for row in joined.itertuples(index=False):
        if pd.notna(row.tcs_zone):
            result[str(row.facility_id)] = int(row.tcs_zone)
    return result


def activity_group(activity_type: object) -> str:
    value = "" if pd.isna(activity_type) else str(activity_type).strip()
    if value == "home":
        return "home"
    if value in {"work", "work_mobile", "business"}:
        return "work"
    if value.startswith("school") or value.startswith("education"):
        return "education"
    if value == "shopping":
        return "shopping"
    if value in {
        "dining",
        "leisure",
        "social",
        "vfr",
        "primary_activity",
        "secondary_activity",
    }:
        return "leisure"
    if value in {"medical", "personal_business"}:
        return "medical_personal_business"
    if value == "accommodation":
        return "visitor_accommodation"
    if value in {"border", "external_activity"}:
        return "border"
    if value:
        return "other"
    return ""


def toll_status_for_leg(row: Any) -> str:
    if row.vehicle_class != "private_car":
        return "out_of_scope_vehicle_class"
    return str(row.route_status)


def energy_status_for_leg(row: Any) -> str:
    if row.vehicle_class == "motorcycle":
        return "out_of_scope_motorcycle"
    if row.vehicle_class != "private_car":
        return "unresolved_vehicle_class"
    if (
        not finite(row.route_distance_m)
        or float(row.route_distance_m) < 0
    ):
        return "unresolved_route_distance"
    return "ready_distance_only"


def format_time_key(value: object) -> str:
    return f"{float(value):.3f}" if finite(value) else ""


def attach_vehicle_chain(frame: pd.DataFrame) -> pd.DataFrame:
    ordered = frame.sort_values(
        ["vehicle_ref_id", "departure_time_s", "person_id", "leg_sequence"],
        na_position="last",
    ).copy()
    grouped = ordered.groupby("vehicle_ref_id", sort=False, dropna=False)
    ordered["next_car_departure_time_s"] = grouped["departure_time_s"].shift(-1)
    ordered["next_car_origin_facility_id"] = grouped[
        "origin_facility_id"
    ].shift(-1)
    ordered["next_car_person_id"] = grouped["person_id"].shift(-1)
    ordered["next_car_leg_sequence"] = grouped["leg_sequence"].shift(-1)
    ordered["vehicle_chain_cross_person"] = (
        ordered["next_car_person_id"].notna()
        & ordered["next_car_person_id"].ne(ordered["person_id"])
    )
    ordered["vehicle_chain_time_overlap"] = (
        ordered["next_car_departure_time_s"].notna()
        & ordered["arrival_time_s"].notna()
        & ordered["next_car_departure_time_s"].lt(ordered["arrival_time_s"])
    )
    ordered["vehicle_chain_same_facility"] = (
        ordered["next_car_origin_facility_id"].notna()
        & ordered["next_car_origin_facility_id"].eq(
            ordered["destination_facility_id"]
        )
    )
    valid_duration = (
        ordered["next_car_departure_time_s"].notna()
        & ordered["arrival_time_s"].notna()
        & ~ordered["vehicle_chain_time_overlap"]
        & ordered["vehicle_chain_same_facility"]
    )
    ordered["parking_duration_s"] = np.where(
        valid_duration,
        ordered["next_car_departure_time_s"] - ordered["arrival_time_s"],
        np.nan,
    )
    ordered["parking_crosses_midnight"] = (
        ordered["parking_duration_s"].notna()
        & (
            (ordered["arrival_time_s"] % 86400)
            > (ordered["next_car_departure_time_s"] % 86400)
        )
    )
    ordered["parking_duration_over_24h"] = ordered["parking_duration_s"].gt(
        86400
    )
    ordered["parking_event_key"] = [
        (
            f"vehicle_ref_id={vehicle}|"
            f"destination_facility_id={destination}|"
            f"arrival_time_s={format_time_key(arrival)}|"
            f"next_car_departure_time_s={format_time_key(next_departure)}|"
            f"next_car_origin_facility_id={next_origin}"
        )
        for vehicle, destination, arrival, next_departure, next_origin in zip(
            ordered["vehicle_ref_id"].fillna("").astype(str),
            ordered["destination_facility_id"].fillna("").astype(str),
            ordered["arrival_time_s"],
            ordered["next_car_departure_time_s"],
            ordered["next_car_origin_facility_id"].fillna("").astype(str),
        )
    ]
    return ordered.sort_values(["person_id", "leg_sequence"]).reset_index(drop=True)


def parking_status_for_leg(row: Any) -> str:
    if row.vehicle_class != "private_car":
        return "out_of_scope_vehicle_class"
    if row.destination_activity_group == "":
        return "unresolved_activity_type"
    if row.destination_activity_group == "home":
        return "ready_home_fixed_parking_separate"
    if (
        bool(row.vehicle_chain_cross_person)
        or bool(row.vehicle_chain_time_overlap)
        or (
            pd.notna(row.next_car_departure_time_s)
            and not bool(row.vehicle_chain_same_facility)
        )
    ):
        return "unresolved_vehicle_chain"
    if not finite(row.parking_duration_s) or float(row.parking_duration_s) < 0:
        return "unresolved_duration"
    if pd.isna(row.destination_tcs_zone):
        return "unresolved_destination_zone"
    return "ready_duration_and_proxy_zone"


def status_counts(series: pd.Series, allowed: set[str]) -> dict[str, int]:
    actual = {str(key): int(value) for key, value in series.value_counts().items()}
    unexpected = set(actual) - allowed
    if unexpected:
        raise ValueError(f"Unexpected readiness statuses: {sorted(unexpected)}")
    return {status: int(actual.get(status, 0)) for status in sorted(allowed)}


def add_coverage_row(
    rows: list[dict[str, Any]],
    domain: str,
    metric: str,
    status: str,
    count: int | None = None,
    total: int | None = None,
    value: float | str | None = None,
    unit: str = "",
    notes: str = "",
) -> None:
    rows.append(
        {
            "domain": domain,
            "metric": metric,
            "status": status,
            "count": count,
            "total": total,
            "coverage_fraction": (
                float(count) / float(total)
                if count is not None and total not in (None, 0)
                else np.nan
            ),
            "value": value,
            "unit": unit,
            "notes": notes,
        }
    )


def prototype_audit(
    feasibility: pd.DataFrame,
) -> tuple[dict[str, Any], list[dict[str, str]], dict[str, str]]:
    estimator_path = (
        REPO_ROOT
        / "scripts/hong_kong_single_city/costs/car/"
        "estimate_hong_kong_car_leg_costs.py"
    )
    estimator_text = estimator_path.read_text(encoding="utf-8")
    required_columns = {
        "person_id",
        "leg_sequence",
        "mode",
        "route_distance_m",
        "destination_facility_id",
        "destination_tcs_zone",
        "destination_activity_type",
        "arrival_time_s",
        "parking_duration_s",
        "cost_component",
        "cost_hkd",
        "cost_source",
        "cost_effective_date",
        "cost_quality",
        "scenario",
    }
    scenario_details: dict[str, Any] = {}
    hashes: dict[str, str] = {}
    for scenario in ("low", "base", "high"):
        path = CAR_COST_ROOT / f"car_leg_cost_estimates_{scenario}.parquet"
        hashes[scenario] = sha256_file(path)
        frame = pd.read_parquet(path)
        unresolved = frame["cost_component"].eq("unresolved_cost")
        scenario_details[scenario] = {
            "columns": [str(column) for column in frame.columns],
            "required_columns_present": sorted(required_columns & set(frame.columns)),
            "required_columns_missing": sorted(required_columns - set(frame.columns)),
            "unresolved_rows": int(unresolved.sum()),
            "unresolved_rows_cost_hkd_zero": int(
                (unresolved & frame["cost_hkd"].eq(0)).sum()
            ),
            "unresolved_rows_cost_hkd_null": int(
                (unresolved & frame["cost_hkd"].isna()).sum()
            ),
            "fixed_rows_attached_to_normal_leg": int(
                (
                    frame["cost_component"].eq("fixed_vehicle_ownership_cost")
                    & frame["leg_sequence"].ge(0)
                ).sum()
            ),
        }

    private = feasibility.loc[
        feasibility["vehicle_class"].eq("private_car")
    ].copy()
    incomplete = (
        ~private["toll_readiness"].eq("route_ready_for_toll_matching")
        | ~private["parking_readiness"].isin(
            [
                "ready_home_fixed_parking_separate",
                "ready_duration_and_proxy_zone",
            ]
        )
        | ~private["energy_readiness"].eq("ready_distance_only")
    )
    added_toll = private["toll_start_end_added_facilities"].ne("")
    text_paths = [
        estimator_path,
        CAR_COST_ROOT / "car_cost_source_manifest.json",
        CAR_COST_ROOT / "car_cost_model_validation.json",
        CAR_COST_ROOT / "car_energy_cost_parameters.csv",
        CAR_COST_ROOT / "car_toll_rules.csv",
        CAR_COST_ROOT / "car_parking_cost_rules.csv",
        CAR_COST_ROOT / "car_cost_summary_by_component.csv",
        CAR_COST_ROOT / "car_cost_summary_by_distance.csv",
        CAR_COST_ROOT / "car_cost_summary_by_destination.csv",
        CAR_COST_ROOT / "car_cost_summary_by_activity.csv",
    ]
    absolute_path_files = []
    for path in text_paths:
        if path.exists() and ABSOLUTE_WINDOWS_PATH_RE.search(
            path.read_text(encoding="utf-8", errors="replace")
        ):
            absolute_path_files.append(path.relative_to(REPO_ROOT).as_posix())

    review = {
        "scenario_parquets": scenario_details,
        "incomplete_private_car_marginal_rows_recomputed": int(incomplete.sum()),
        "grouped_summary_filters_marginal_cost_complete": False,
        "incomplete_rows_enter_current_grouped_means_quantiles_totals": True,
        "parking_duplicate_charge_count_is_data_derived": False,
        "parking_duplicate_charge_count_evidence": (
            "The estimator assigns parking_session_id as vehicle/person/leg and "
            "writes parking_duplicate_charge_count as the literal value 0."
        ),
        "estimator_reconstructs_full_route_from_start_intermediate_end": False,
        "estimator_has_complete_link_sequence_checks_network_and_topology": False,
        "start_end_toll_matches_added_by_correct_reconstruction": int(
            added_toll.sum()
        ),
        "files_containing_windows_absolute_paths": absolute_path_files,
    }
    repairs = [
        {
            "repair_id": "CARCOST-R01",
            "severity": "high",
            "component": "route_and_toll",
            "finding": (
                "The estimator treats route text as the complete sequence and does "
                "not explicitly reconstruct start/intermediate/end."
            ),
            "evidence": (
                f"Correct reconstruction adds toll-facility matches for "
                f"{int(added_toll.sum())} private-car legs in the current data; "
                "the present route text happens to include both boundary links."
            ),
            "required_change": (
                "Normalize route text boundaries, reconstruct the full sequence, "
                "then match toll features on that full sequence."
            ),
        },
        {
            "repair_id": "CARCOST-R02",
            "severity": "critical",
            "component": "route_and_toll",
            "finding": (
                "has_complete_link_sequence only tests whether route text is non-empty."
            ),
            "evidence": (
                "It does not test start/end presence, network membership, or "
                "from-node/to-node continuity."
            ),
            "required_change": (
                "Require start/end links, all-link network membership, and topology "
                "continuity before confirming toll matching."
            ),
        },
        {
            "repair_id": "CARCOST-R03",
            "severity": "critical",
            "component": "unresolved_cost",
            "finding": "Unresolved output records use cost_hkd=0.",
            "evidence": json.dumps(
                {
                    scenario: details["unresolved_rows_cost_hkd_zero"]
                    for scenario, details in scenario_details.items()
                },
                sort_keys=True,
            ),
            "required_change": (
                "Store unresolved amount as null and exclude it from resolved totals; "
                "do not encode unknown cost as zero."
            ),
        },
        {
            "repair_id": "CARCOST-R04",
            "severity": "critical",
            "component": "summary_statistics",
            "finding": (
                "Grouped marginal summaries calculate totals, means and quantiles "
                "over all private-car rows without filtering marginal_cost_complete."
            ),
            "evidence": (
                f"{int(incomplete.sum())} private-car marginal rows are incomplete "
                "under the independently reconstructed readiness audit."
            ),
            "required_change": (
                "Publish resolved-only statistics and separate incomplete coverage; "
                "never include incomplete marginal totals in distributions."
            ),
        },
        {
            "repair_id": "CARCOST-R05",
            "severity": "critical",
            "component": "parking",
            "finding": (
                "parking_session_id is a vehicle/person/leg identifier rather than "
                "a physical parking-event key, and duplicate count is hard-coded."
            ),
            "evidence": (
                "Current validation writes parking_duplicate_charge_count=0 without "
                "grouping vehicle, destination, arrival and next vehicle departure."
            ),
            "required_change": (
                "Build a physical parking_event_key, audit duplicate mappings, "
                "facility continuity and vehicle-time overlaps, then derive the count."
            ),
        },
        {
            "repair_id": "CARCOST-R06",
            "severity": "high",
            "component": "provenance",
            "finding": "Submitted prototype artifacts contain a personal absolute path.",
            "evidence": "|".join(absolute_path_files),
            "required_change": (
                "Replace personal paths with repository-relative paths plus "
                "input_root_role metadata."
            ),
        },
        {
            "repair_id": "CARCOST-R07",
            "severity": "high",
            "component": "energy",
            "finding": (
                "No individual vehicle powertrain, fuel type, engine size or vehicle "
                "age field exists in the inspected vehicle inputs."
            ),
            "evidence": "Individual powertrain availability is 0%.",
            "required_change": (
                "Label any fleet-average energy value as a proxy and do not present "
                "it as a per-vehicle observation."
            ),
        },
    ]
    return review, repairs, hashes


def repository_relative_config_value(value: str, input_root: Path) -> str:
    if not ABSOLUTE_WINDOWS_PATH_RE.search(value):
        return value.replace("\\", "/")
    candidate = Path(value)
    try:
        return candidate.relative_to(input_root).as_posix()
    except ValueError:
        return "external_absolute_path_redacted"


def parse_config(path: Path, input_root: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    modules = [element.attrib.get("name", "") for element in root.findall("module")]
    input_params = {}
    for module in root.findall("module"):
        for parameter in module.findall("param"):
            name = parameter.attrib.get("name", "")
            if "input" in name.lower() or "file" in name.lower():
                input_params[f"{module.attrib.get('name', '')}.{name}"] = (
                    repository_relative_config_value(
                        parameter.attrib.get("value", ""), input_root
                    )
                )
    return {
        "modules": modules,
        "input_file_parameters": input_params,
        "model_day_designation": "typical_weekday",
        "exact_calendar_date_available": False,
        "weekday_toll_interpretation": (
            "The scenario is explicitly a typical weekday, but no exact calendar "
            "date is encoded; this audit only marks passage time as estimable."
        ),
    }


def main() -> None:
    args = parse_args()
    input_root = args.input_project_root.resolve()
    paths = resolve_required_inputs(input_root)
    hashes_before = input_hashes(paths)
    inventory = build_inventory(input_root, paths, hashes_before)

    prototype_paths = {
        scenario: CAR_COST_ROOT / f"car_leg_cost_estimates_{scenario}.parquet"
        for scenario in ("low", "base", "high")
    }
    missing_prototype = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in prototype_paths.values()
        if not path.exists()
    ]
    if missing_prototype:
        raise FileNotFoundError(
            f"Prototype outputs required for read-only review are missing: "
            f"{missing_prototype}"
        )
    prototype_hashes_before = {
        scenario: sha256_file(path) for scenario, path in prototype_paths.items()
    }

    manifest = pd.read_parquet(paths["trip_manifest"])
    manifest["person_id"] = manifest["person_id"].astype(str)
    manifest["leg_sequence"] = manifest["leg_sequence"].astype(int)
    manifest_duplicate_keys = int(
        manifest.duplicated(["person_id", "leg_sequence"]).sum()
    )
    car_manifest = manifest.loc[manifest["mode"].eq("car")].copy()
    car_keys = set(
        zip(car_manifest["person_id"], car_manifest["leg_sequence"], strict=False)
    )

    network_links, network_feature_links = parse_network(paths["network"])
    (
        vehicle_classes,
        vehicle_types,
        vehicle_attribute_names,
        vehicle_type_child_names,
    ) = parse_vehicle_definitions(paths["private_vehicles"])
    (
        feature_to_facilities,
        toll_metadata,
        facility_features,
    ) = load_toll_features(paths["road_gdb"])
    toll_metadata["facility_feature_ids"] = facility_features
    official_feature_ids = set(feature_to_facilities)
    mapped_official_features = official_feature_ids & set(network_feature_links)
    toll_metadata["official_feature_id_count"] = int(len(official_feature_ids))
    toll_metadata["official_feature_ids_mapped_to_network_count"] = int(
        len(mapped_official_features)
    )
    toll_metadata["official_feature_id_network_mapping_coverage"] = (
        float(len(mapped_official_features) / len(official_feature_ids))
        if official_feature_ids
        else float("nan")
    )
    toll_metadata["unmapped_official_feature_ids"] = sorted(
        str(value) for value in official_feature_ids - set(network_feature_links)
    )
    toll_metadata["official_features_with_multiple_network_links"] = {
        str(feature): sorted(network_feature_links[feature])
        for feature in sorted(mapped_official_features)
        if len(network_feature_links[feature]) > 1
    }

    routes, route_diagnostics, person_context = parse_routed_car_legs(
        paths["plans_routed"],
        car_keys,
        network_links,
        feature_to_facilities,
    )
    routed_keys = set(
        zip(routes["person_id"], routes["leg_sequence"], strict=False)
    )
    unrouted_keys, unrouted_duplicate_keys = parse_unrouted_car_keys(
        paths["plans_unrouted"]
    )

    needed_facilities = set(
        car_manifest["origin_facility_id"].dropna().astype(str)
    ) | set(car_manifest["destination_facility_id"].dropna().astype(str))
    facilities = parse_facilities(paths["facilities"], needed_facilities)
    zone_lookup = facility_zone_lookup(
        facilities,
        paths["fixed_link_grid"],
        grid_to_tcs_lookup(paths["synthetic_households"]),
    )
    facility_index = facilities.set_index("facility_id")

    feasibility = car_manifest.rename(
        columns={
            "mode": "manifest_mode",
            "origin_type": "origin_activity_type_manifest",
            "destination_type": "destination_activity_type",
            "departure_time_s": "manifest_departure_time_s",
        }
    ).merge(
        routes,
        on=["person_id", "leg_sequence"],
        how="left",
        validate="one_to_one",
    )
    feasibility["vehicle_ref_id"] = feasibility["vehicle_ref_id"].fillna("")
    feasibility["vehicle_class"] = (
        feasibility["vehicle_ref_id"].map(vehicle_classes).fillna("unknown")
    )
    feasibility["household_id"] = feasibility["person_id"].map(
        lambda value: person_context.get(value, {}).get("household_id", "")
    )
    feasibility["assigned_vehicle_id"] = feasibility["person_id"].map(
        lambda value: person_context.get(value, {}).get(
            "assigned_vehicle_id", ""
        )
    )
    feasibility["origin_facility_id"] = feasibility[
        "origin_facility_id"
    ].fillna("")
    feasibility["destination_facility_id"] = feasibility[
        "destination_facility_id"
    ].fillna("")
    feasibility["destination_facility_x"] = feasibility[
        "destination_facility_id"
    ].map(
        facility_index["facility_x"]
        if not facility_index.empty
        else pd.Series(dtype=float)
    )
    feasibility["destination_facility_y"] = feasibility[
        "destination_facility_id"
    ].map(
        facility_index["facility_y"]
        if not facility_index.empty
        else pd.Series(dtype=float)
    )
    feasibility["destination_tcs_zone"] = feasibility[
        "destination_facility_id"
    ].map(zone_lookup)
    feasibility["destination_activity_group"] = feasibility[
        "destination_activity_type"
    ].map(activity_group)
    feasibility["energy_readiness"] = [
        energy_status_for_leg(row)
        for row in feasibility.itertuples(index=False)
    ]
    feasibility["toll_readiness"] = [
        toll_status_for_leg(row)
        for row in feasibility.itertuples(index=False)
    ]
    feasibility = attach_vehicle_chain(feasibility)
    feasibility["parking_readiness"] = [
        parking_status_for_leg(row)
        for row in feasibility.itertuples(index=False)
    ]
    feasibility["unresolved_reason"] = [
        "|".join(
            status
            for status in (energy, toll, parking)
            if status.startswith("unresolved")
            or status.startswith("ambiguous")
            or status.startswith("out_of_scope")
        )
        for energy, toll, parking in zip(
            feasibility["energy_readiness"],
            feasibility["toll_readiness"],
            feasibility["parking_readiness"],
            strict=False,
        )
    ]

    required_output_columns = [
        "person_id",
        "leg_sequence",
        "manifest_mode",
        "routed_mode",
        "vehicle_ref_id",
        "vehicle_class",
        "route_type",
        "route_distance_m",
        "route_start_link",
        "route_end_link",
        "intermediate_link_count",
        "full_link_count",
        "all_links_exist",
        "route_topology_contiguous",
        "route_status",
        "departure_time_s",
        "route_travel_time_s",
        "arrival_time_s",
        "origin_facility_id",
        "destination_facility_id",
        "destination_tcs_zone",
        "destination_activity_type",
        "next_car_departure_time_s",
        "next_car_origin_facility_id",
        "parking_duration_s",
        "parking_event_key",
        "energy_readiness",
        "toll_readiness",
        "parking_readiness",
        "unresolved_reason",
    ]
    extra_output_columns = [
        "household_id",
        "assigned_vehicle_id",
        "origin_activity_type_manifest",
        "manifest_departure_time_s",
        "origin_facility_id_routed",
        "destination_facility_id_routed",
        "destination_activity_type_routed",
        "destination_activity_group",
        "destination_facility_x",
        "destination_facility_y",
        "unknown_network_link_count",
        "non_contiguous_link_pair_count",
        "repeated_link_occurrence_count",
        "immediate_repeated_link_count",
        "network_distance_sum_m",
        "toll_facilities_full",
        "toll_facilities_route_text",
        "toll_start_end_added_facilities",
        "toll_mapping_conflict_feature_ids",
        "toll_passage_time_estimable",
        "route_text_includes_start_link",
        "route_text_includes_end_link",
        "next_car_person_id",
        "next_car_leg_sequence",
        "vehicle_chain_cross_person",
        "vehicle_chain_time_overlap",
        "vehicle_chain_same_facility",
        "parking_crosses_midnight",
        "parking_duration_over_24h",
    ]
    feasibility = feasibility[required_output_columns + extra_output_columns]

    private = feasibility.loc[
        feasibility["vehicle_class"].eq("private_car")
    ].copy()
    motorcycle = feasibility.loc[
        feasibility["vehicle_class"].eq("motorcycle")
    ].copy()
    unknown = feasibility.loc[
        ~feasibility["vehicle_class"].isin(["private_car", "motorcycle"])
    ].copy()

    vehicle_use = private.groupby("vehicle_ref_id").agg(
        person_count=("person_id", "nunique"),
        household_count=("household_id", "nunique"),
        leg_count=("leg_sequence", "size"),
    )
    physical_event_counts = private["parking_event_key"].value_counts()
    duplicate_event_keys = physical_event_counts.loc[
        physical_event_counts.gt(1)
    ]
    toll_full_counts = Counter()
    toll_text_counts = Counter()
    toll_added_counts = Counter()
    for value in private["toll_facilities_full"]:
        toll_full_counts.update(filter(None, str(value).split("|")))
    for value in private["toll_facilities_route_text"]:
        toll_text_counts.update(filter(None, str(value).split("|")))
    for value in private["toll_start_end_added_facilities"]:
        toll_added_counts.update(filter(None, str(value).split("|")))

    energy_counts = status_counts(
        feasibility["energy_readiness"], ENERGY_STATUSES
    )
    toll_counts = status_counts(feasibility["toll_readiness"], TOLL_STATUSES)
    parking_counts = status_counts(
        feasibility["parking_readiness"], PARKING_STATUSES
    )
    activity_count_observed = {
        str(key): int(value)
        for key, value in private[
            "destination_activity_group"
        ].value_counts(dropna=False).items()
    }
    activity_counts = {
        group: int(activity_count_observed.get(group, 0))
        for group in [
            "home",
            "work",
            "education",
            "shopping",
            "leisure",
            "medical_personal_business",
            "border",
            "visitor_accommodation",
            "other",
        ]
    }
    activity_counts["unresolved_blank_activity_type"] = int(
        activity_count_observed.get("", 0)
    )
    non_home_private = private.loc[
        ~private["destination_activity_group"].eq("home")
    ]

    coverage_rows: list[dict[str, Any]] = []
    total_car = len(feasibility)
    total_private = len(private)
    for status, count in energy_counts.items():
        add_coverage_row(
            coverage_rows, "energy", "energy_readiness", status, count, total_car
        )
    for status, count in toll_counts.items():
        add_coverage_row(
            coverage_rows, "toll", "toll_readiness", status, count, total_car
        )
    for status, count in parking_counts.items():
        add_coverage_row(
            coverage_rows,
            "parking",
            "parking_readiness",
            status,
            count,
            total_car,
        )
    for group, count in sorted(activity_counts.items()):
        add_coverage_row(
            coverage_rows,
            "parking",
            "destination_activity_group",
            group,
            count,
            total_private,
        )

    distance = private["route_distance_m"]
    for metric, value in {
        "route_distance_min_m": distance.min(),
        "route_distance_median_m": distance.median(),
        "route_distance_p90_m": distance.quantile(0.9),
        "route_distance_max_m": distance.max(),
    }.items():
        add_coverage_row(
            coverage_rows,
            "energy",
            metric,
            "observed",
            value=float(value),
            unit="m",
        )
    add_coverage_row(
        coverage_rows,
        "energy",
        "individual_powertrain_identifiable",
        "unavailable",
        0,
        total_private,
        notes=(
            "No powertrain, fuel type, engine size or vehicle-age field is "
            "present in privateVehicles or routed vehicle references."
        ),
    )
    add_coverage_row(
        coverage_rows,
        "route",
        "all_links_exist",
        "true",
        int(private["all_links_exist"].fillna(False).sum()),
        total_private,
    )
    add_coverage_row(
        coverage_rows,
        "route",
        "topology_contiguous",
        "true",
        int(private["route_topology_contiguous"].fillna(False).sum()),
        total_private,
    )
    add_coverage_row(
        coverage_rows,
        "parking",
        "duration_available",
        "true",
        int(private["parking_duration_s"].notna().sum()),
        total_private,
    )
    add_coverage_row(
        coverage_rows,
        "parking",
        "duration_available_non_home",
        "true",
        int(non_home_private["parking_duration_s"].notna().sum()),
        int(len(non_home_private)),
        notes=(
            "Home arrivals are excluded because home parking is a separate fixed "
            "parking treatment."
        ),
    )
    add_coverage_row(
        coverage_rows,
        "parking",
        "destination_zone_available",
        "true",
        int(private["destination_tcs_zone"].notna().sum()),
        total_private,
    )
    add_coverage_row(
        coverage_rows,
        "parking",
        "activity_group_available",
        "true",
        int(private["destination_activity_group"].ne("").sum()),
        total_private,
    )

    prototype_review, repairs, prototype_hashes_review = prototype_audit(
        feasibility
    )
    if prototype_hashes_review != prototype_hashes_before:
        raise RuntimeError("Prototype cost Parquet changed during read-only review")
    current_base = pd.read_parquet(
        prototype_paths["base"],
        columns=[
            "cost_component",
            "vehicle_class",
            "toll_facilities",
        ],
    )
    current_toll_counts = Counter()
    toll_rule_names = (
        pd.read_csv(
            CAR_COST_ROOT / "car_toll_rules.csv",
            usecols=["toll_facility_id", "toll_facility_name"],
        )
        .drop_duplicates("toll_facility_id")
        .set_index("toll_facility_id")["toll_facility_name"]
        .astype(str)
        .to_dict()
    )
    current_toll_rows = current_base.loc[
        current_base["cost_component"].eq("toll")
        & current_base["vehicle_class"].eq("private_car")
    ]
    for value in current_toll_rows["toll_facilities"].fillna(""):
        current_toll_counts.update(
            toll_rule_names.get(facility, facility)
            for facility in filter(None, str(value).split("|"))
        )
    all_toll_facilities = sorted(
        set(facility_features)
        | set(toll_full_counts)
        | set(current_toll_counts)
    )
    toll_hit_comparison = {
        facility: {
            "audited_full_route_private_car_legs": int(
                toll_full_counts.get(facility, 0)
            ),
            "current_car_cost_v1_private_car_legs": int(
                current_toll_counts.get(facility, 0)
            ),
            "audited_minus_current": int(
                toll_full_counts.get(facility, 0)
                - current_toll_counts.get(facility, 0)
            ),
        }
        for facility in all_toll_facilities
    }
    requested_toll_diagnostics = {
        facility: toll_hit_comparison[facility]
        for facility in [
            "Cross Harbour Tunnel",
            "Eastern Harbour Crossing",
            "Western Harbour Crossing",
            "Tate's Cairn Tunnel",
            "Aberdeen Tunnel",
            "Tai Lam Tunnel",
        ]
        if facility in toll_hit_comparison
    }
    prototype_review["current_car_cost_v1_toll_facility_hits"] = {
        facility: int(current_toll_counts.get(facility, 0))
        for facility in all_toll_facilities
    }
    config_review = parse_config(paths["config"], input_root)

    expected = {
        "main_legs": 743614,
        "car_legs": 67718,
        "private_car_legs": 64789,
        "motorcycle_car_mode_legs": 2929,
        "used_private_cars": 21020,
    }
    actual = {
        "main_legs": int(len(manifest)),
        "car_legs": int(len(feasibility)),
        "private_car_legs": int(len(private)),
        "motorcycle_car_mode_legs": int(len(motorcycle)),
        "unknown_vehicle_class_legs": int(len(unknown)),
        "used_private_cars": int(private["vehicle_ref_id"].nunique()),
    }
    expected_differences = {
        key: int(actual[key] - value) for key, value in expected.items()
    }

    route_stats = {
        "private_car_routes": total_private,
        "start_link_present": int(private["route_start_link"].ne("").sum()),
        "end_link_present": int(private["route_end_link"].ne("").sum()),
        "all_links_exist": int(private["all_links_exist"].fillna(False).sum()),
        "all_links_exist_fraction": float(
            private["all_links_exist"].fillna(False).mean()
        ),
        "topology_contiguous": int(
            private["route_topology_contiguous"].fillna(False).sum()
        ),
        "topology_contiguous_fraction": float(
            private["route_topology_contiguous"].fillna(False).mean()
        ),
        "unknown_network_link_routes": int(
            private["unknown_network_link_count"].gt(0).sum()
        ),
        "non_contiguous_routes": int(
            private["non_contiguous_link_pair_count"].gt(0).sum()
        ),
        "repeated_link_routes": int(
            private["repeated_link_occurrence_count"].gt(0).sum()
        ),
        "immediate_repeated_link_routes": int(
            private["immediate_repeated_link_count"].gt(0).sum()
        ),
        "departure_time_available": int(private["departure_time_s"].notna().sum()),
        "travel_time_available": int(
            private["route_travel_time_s"].notna().sum()
        ),
        "passage_time_estimable": int(
            private["toll_passage_time_estimable"].fillna(False).sum()
        ),
        "route_text_includes_start_link": int(
            private["route_text_includes_start_link"].fillna(False).sum()
        ),
        "route_text_includes_end_link": int(
            private["route_text_includes_end_link"].fillna(False).sum()
        ),
    }
    distance_stats = {
        "unit": "m",
        "unit_basis": (
            "MATSim route distance and network link lengths use the scenario "
            "coordinate/network metre convention (EPSG:32650)."
        ),
        "present": int(distance.notna().sum()),
        "nan": int(distance.isna().sum()),
        "negative": int(distance.lt(0).sum()),
        "zero": int(distance.eq(0).sum()),
        "min": float(distance.min()),
        "median": float(distance.median()),
        "p90": float(distance.quantile(0.9)),
        "max": float(distance.max()),
    }
    powertrain = {
        "individual_powertrain_available": False,
        "individual_powertrain_identifiable_legs": 0,
        "individual_powertrain_identifiable_fraction": 0.0,
        "vehicle_xml_attribute_names": sorted(vehicle_attribute_names),
        "vehicle_type_child_elements": sorted(vehicle_type_child_names),
        "vehicle_type_definitions": vehicle_types,
        "unavailable_fields": [
            "powertrain",
            "fuel_type",
            "engine_size",
            "vehicle_age",
        ],
        "conclusion": "individual powertrain unavailable",
        "future_proxy_option": (
            "A representative fleet average may be evaluated later, but no "
            "energy cost is computed in this audit."
        ),
    }
    vehicle_chain = {
        "used_private_cars": int(len(vehicle_use)),
        "vehicles_used_by_multiple_people": int(
            vehicle_use["person_count"].gt(1).sum()
        ),
        "vehicles_linked_to_multiple_households": int(
            vehicle_use["household_count"].gt(1).sum()
        ),
        "vehicle_leg_count_min": int(vehicle_use["leg_count"].min()),
        "vehicle_leg_count_median": float(vehicle_use["leg_count"].median()),
        "vehicle_leg_count_p90": float(vehicle_use["leg_count"].quantile(0.9)),
        "vehicle_leg_count_max": int(vehicle_use["leg_count"].max()),
        "cross_person_next_leg_events": int(
            private["vehicle_chain_cross_person"].sum()
        ),
        "vehicle_time_overlap_events": int(
            private["vehicle_chain_time_overlap"].sum()
        ),
        "next_departure_different_facility_events": int(
            (
                private["next_car_departure_time_s"].notna()
                & ~private["vehicle_chain_same_facility"]
            ).sum()
        ),
        "no_next_departure_events": int(
            private["next_car_departure_time_s"].isna().sum()
        ),
        "negative_duration_events": int(private["parking_duration_s"].lt(0).sum()),
        "cross_midnight_events": int(private["parking_crosses_midnight"].sum()),
        "duration_over_24h_events": int(
            private["parking_duration_over_24h"].sum()
        ),
        "duplicate_parking_event_key_count": int(len(duplicate_event_keys)),
        "legs_in_duplicate_parking_event_keys": int(
            duplicate_event_keys.sum() if len(duplicate_event_keys) else 0
        ),
        "excess_leg_mappings_to_parking_events": int(
            (duplicate_event_keys - 1).sum() if len(duplicate_event_keys) else 0
        ),
    }
    fixed_ownership = {
        "record_scope_required": ["vehicle_day", "household_day"],
        "normal_leg_attachment_allowed": False,
        "include_in_leg_marginal_total": False,
        "used_private_vehicle_count": int(len(vehicle_use)),
        "person_household_vehicle_mapping": {
            "route_vehicle_ref_available": int(private["vehicle_ref_id"].ne("").sum()),
            "assigned_vehicle_id_available": int(
                private["assigned_vehicle_id"].ne("").sum()
            ),
            "assigned_vehicle_matches_route_ref": int(
                (
                    private["assigned_vehicle_id"].ne("")
                    & private["assigned_vehicle_id"].eq(
                        private["vehicle_ref_id"]
                    )
                ).sum()
            ),
            "household_id_available": int(private["household_id"].ne("").sum()),
        },
        "observed_vehicle_owner_field_available": False,
        "unavailable_fields": [
            "vehicle_owner",
            "engine",
            "purchase_price",
            "vehicle_age",
            "insurance",
            "maintenance",
            "financing",
        ],
        "proxy_only_future_components": [
            "depreciation",
            "insurance",
            "maintenance",
            "financing",
        ],
        "work_monthly_parking_boundary": (
            "If treated as already paid, work monthly parking belongs in a "
            "vehicle_day or household_day fixed-cost record, never a normal leg."
        ),
    }

    validation = {
        "audit": "Hong Kong private car cost input feasibility audit",
        "costs_computed": False,
        "cost_parameters_or_outputs_modified": False,
        "input_root_role": "canonical_project_read_only",
        "expected_counts_are_comparison_only": expected,
        "actual_counts": actual,
        "actual_minus_expected": expected_differences,
        "manifest_person_leg_key_duplicate_count": manifest_duplicate_keys,
        "car_manifest_person_leg_key_unique": bool(
            not car_manifest.duplicated(["person_id", "leg_sequence"]).any()
        ),
        "routed_person_leg_key_duplicate_count": int(
            route_diagnostics["duplicate_routed_car_keys"]
        ),
        "unrouted_person_leg_key_duplicate_count": int(
            unrouted_duplicate_keys
        ),
        "manifest_car_keys_missing_from_routed": int(
            len(car_keys - routed_keys)
        ),
        "routed_car_keys_missing_from_manifest_car": int(
            len(routed_keys - car_keys)
        ),
        "manifest_car_keys_missing_from_unrouted": int(
            len(car_keys - unrouted_keys)
        ),
        "unrouted_car_keys_missing_from_manifest_car": int(
            len(unrouted_keys - car_keys)
        ),
        "vehicle_ref_id_missing": int(feasibility["vehicle_ref_id"].eq("").sum()),
        "vehicle_ref_id_unresolved_in_private_vehicles": int(len(unknown)),
        "vehicle_use": vehicle_chain,
        "route": route_stats,
        "route_distance": distance_stats,
        "energy_readiness_counts": energy_counts,
        "vehicle_powertrain": powertrain,
        "toll_readiness_counts": toll_counts,
        "toll_geodatabase": toll_metadata,
        "toll_facility_hits_full_route": dict(sorted(toll_full_counts.items())),
        "toll_facility_hits_full_route_all_official_facilities": {
            facility: int(toll_full_counts.get(facility, 0))
            for facility in all_toll_facilities
        },
        "toll_facility_hits_route_text_only": dict(
            sorted(toll_text_counts.items())
        ),
        "toll_facility_hits_added_by_start_end": dict(
            sorted(toll_added_counts.items())
        ),
        "toll_facility_hit_comparison_with_current_car_cost_v1": (
            toll_hit_comparison
        ),
        "requested_toll_facility_diagnostics": requested_toll_diagnostics,
        "start_end_toll_link_omission_found": bool(sum(toll_added_counts.values())),
        "parking_readiness_counts": parking_counts,
        "parking_activity_group_counts_private_car": activity_counts,
        "parking_duration_available_private_car": int(
            private["parking_duration_s"].notna().sum()
        ),
        "parking_duration_coverage_private_car": float(
            private["parking_duration_s"].notna().mean()
        ),
        "parking_duration_available_non_home_private_car": int(
            non_home_private["parking_duration_s"].notna().sum()
        ),
        "parking_duration_coverage_non_home_private_car": float(
            non_home_private["parking_duration_s"].notna().mean()
        ),
        "parking_zone_available_private_car": int(
            private["destination_tcs_zone"].notna().sum()
        ),
        "parking_zone_coverage_private_car": float(
            private["destination_tcs_zone"].notna().mean()
        ),
        "parking_activity_available_private_car": int(
            private["destination_activity_group"].ne("").sum()
        ),
        "parking_activity_coverage_private_car": float(
            private["destination_activity_group"].ne("").mean()
        ),
        "parking_event_audit": vehicle_chain,
        "fixed_vehicle_ownership_boundary": fixed_ownership,
        "model_day": config_review,
        "prototype_read_only_review": prototype_review,
        "required_repairs_count": int(len(repairs)),
        "input_hashes_before": hashes_before,
    }

    hashes_after = input_hashes(paths)
    prototype_hashes_after = {
        scenario: sha256_file(path) for scenario, path in prototype_paths.items()
    }
    validation["input_hashes_after"] = hashes_after
    validation["protected_input_hashes_unchanged"] = (
        hashes_before == hashes_after
    )
    validation["prototype_cost_parquet_hashes_before"] = (
        prototype_hashes_before
    )
    validation["prototype_cost_parquet_hashes_after"] = prototype_hashes_after
    validation["prototype_cost_parquet_hashes_unchanged"] = (
        prototype_hashes_before == prototype_hashes_after
    )

    if hashes_before != hashes_after:
        raise RuntimeError("Canonical input hashes changed during audit")
    if prototype_hashes_before != prototype_hashes_after:
        raise RuntimeError("Prototype cost outputs changed during audit")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    inventory_payload = {
        "audit": "Hong Kong private car cost input feasibility audit",
        "input_root_role": "canonical_project_read_only",
        "absolute_input_root_saved": False,
        "inputs": inventory,
    }
    (args.output_dir / "car_cost_input_file_inventory.json").write_text(
        json.dumps(inventory_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    feasibility.to_parquet(
        args.output_dir / "car_leg_input_feasibility.parquet",
        index=False,
        compression="zstd",
    )
    pd.DataFrame(coverage_rows).to_csv(
        args.output_dir / "car_cost_input_coverage.csv",
        index=False,
        encoding="utf-8",
    )
    pd.DataFrame(repairs).to_csv(
        args.output_dir / "required_repairs.csv",
        index=False,
        encoding="utf-8",
    )
    (args.output_dir / "car_cost_feasibility_validation.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "actual_counts": actual,
                "route_ready_private_car": int(
                    private["toll_readiness"]
                    .eq("route_ready_for_toll_matching")
                    .sum()
                ),
                "route_topology_contiguous_fraction": route_stats[
                    "topology_contiguous_fraction"
                ],
                "powertrain_identifiable_fraction": 0.0,
                "parking_duration_coverage": validation[
                    "parking_duration_coverage_private_car"
                ],
                "parking_zone_coverage": validation[
                    "parking_zone_coverage_private_car"
                ],
                "parking_activity_coverage": validation[
                    "parking_activity_coverage_private_car"
                ],
                "start_end_toll_link_omission_found": validation[
                    "start_end_toll_link_omission_found"
                ],
                "duplicate_parking_event_keys": vehicle_chain[
                    "duplicate_parking_event_key_count"
                ],
                "protected_input_hashes_unchanged": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
