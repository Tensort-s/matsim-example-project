from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point


PROJECT_ROOT = Path(__file__).resolve().parents[3]
NETWORK_CRS = "EPSG:32650"
APPROVAL_BASIS = "user_override_accept_all_routes_2026-07-22"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Approve all current route directions and prepare MATSim-compatible "
            "stop facilities plus nearest-road access snaps."
        )
    )
    parser.add_argument("--data-root", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def safe_token(value: Any) -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("_")
    return token or "unknown"


def short_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]


def read_network(
    network_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, LineString]]:
    with gzip.open(network_path, "rt", encoding="utf-8") as handle:
        root = ET.parse(handle).getroot()
    nodes_element = root.find("nodes")
    links_element = root.find("links")
    if nodes_element is None or links_element is None:
        raise ValueError("MATSim network has no nodes or links element")

    node_rows = [
        {
            "node_id": node.attrib["id"],
            "x": float(node.attrib["x"]),
            "y": float(node.attrib["y"]),
        }
        for node in nodes_element
    ]
    nodes = pd.DataFrame(node_rows)
    node_xy = {
        row.node_id: (float(row.x), float(row.y))
        for row in nodes.itertuples(index=False)
    }
    link_rows: list[dict[str, Any]] = []
    geometries: dict[str, LineString] = {}
    for link in links_element:
        link_id = link.attrib["id"]
        from_node = link.attrib["from"]
        to_node = link.attrib["to"]
        geometry = LineString([node_xy[from_node], node_xy[to_node]])
        geometries[link_id] = geometry
        link_rows.append(
            {
                "link_id": link_id,
                "from_node": from_node,
                "to_node": to_node,
                "length_m": float(link.attrib["length"]),
                "modes": link.attrib.get("modes", ""),
                "is_road": link_id.startswith("road_"),
                "is_rail": link_id.startswith("rail_"),
            }
        )
    return nodes, pd.DataFrame(link_rows), geometries


def snap_point_to_line(point: Point, line: LineString) -> Point:
    return line.interpolate(line.project(point))


def build_nearest_road_access(
    stop_occurrences: pd.DataFrame,
    road_links: pd.DataFrame,
    link_geometries: dict[str, LineString],
) -> tuple[pd.DataFrame, gpd.GeoDataFrame]:
    physical = (
        stop_occurrences.sort_values(
            ["mode", "stop_id", "nearest_network_distance_m", "snap_distance_m"]
        )
        .drop_duplicates(["mode", "stop_id"])
        .copy()
        .reset_index(drop=True)
    )
    physical["physical_stop_key"] = (
        physical["mode"].astype(str) + "|" + physical["stop_id"].astype(str)
    )
    points = gpd.GeoDataFrame(
        physical[
            [
                "physical_stop_key",
                "mode",
                "stop_id",
                "stop_name_en",
                "stop_name_zh",
                "x",
                "y",
                "lon",
                "lat",
            ]
        ].copy(),
        geometry=gpd.points_from_xy(physical["x"], physical["y"]),
        crs=NETWORK_CRS,
    )
    road_gdf = gpd.GeoDataFrame(
        road_links[["link_id", "from_node", "to_node", "length_m"]].copy(),
        geometry=[link_geometries[link_id] for link_id in road_links["link_id"]],
        crs=NETWORK_CRS,
    ).rename(columns={"link_id": "nearest_road_link_id"})
    joined = gpd.sjoin_nearest(
        points,
        road_gdf,
        how="left",
        distance_col="nearest_road_distance_m",
    )
    joined = (
        joined.sort_values(
            ["physical_stop_key", "nearest_road_distance_m", "nearest_road_link_id"]
        )
        .drop_duplicates("physical_stop_key")
        .reset_index(drop=True)
    )
    if joined["nearest_road_link_id"].isna().any():
        raise RuntimeError("At least one physical stop could not be snapped to a road")

    snapped_points = []
    for row in joined.itertuples(index=False):
        snapped_points.append(
            snap_point_to_line(
                row.geometry, link_geometries[row.nearest_road_link_id]
            )
        )
    snapped = gpd.GeoDataFrame(
        joined.drop(columns=["geometry", "index_right"]),
        geometry=snapped_points,
        crs=NETWORK_CRS,
    )
    snapped["road_access_x"] = snapped.geometry.x
    snapped["road_access_y"] = snapped.geometry.y
    snapped_wgs84 = snapped.to_crs("EPSG:4326")
    snapped["road_access_lon"] = snapped_wgs84.geometry.x.to_numpy()
    snapped["road_access_lat"] = snapped_wgs84.geometry.y.to_numpy()
    snapped["road_access_id"] = snapped.apply(
        lambda row: (
            f"road_access_{safe_token(row['mode'])}_{safe_token(row['stop_id'])}_"
            f"{short_hash(str(row['nearest_road_link_id']))}"
        ),
        axis=1,
    )
    output_columns = [
        "road_access_id",
        "physical_stop_key",
        "mode",
        "stop_id",
        "stop_name_en",
        "stop_name_zh",
        "x",
        "y",
        "lon",
        "lat",
        "nearest_road_link_id",
        "nearest_road_distance_m",
        "road_access_x",
        "road_access_y",
        "road_access_lon",
        "road_access_lat",
    ]
    return pd.DataFrame(snapped[output_columns]), snapped


def build_stop_facilities(
    stop_occurrences: pd.DataFrame,
    link_geometries: dict[str, LineString],
    road_access: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    group_columns = ["mode", "stop_id", "link_id"]
    facilities = (
        stop_occurrences.sort_values(
            group_columns + ["snap_distance_m", "route_key", "stop_seq"]
        )
        .groupby(group_columns, as_index=False, dropna=False)
        .agg(
            stop_name_en=("stop_name_en", "first"),
            stop_name_zh=("stop_name_zh", "first"),
            source_x=("x", "first"),
            source_y=("y", "first"),
            source_lon=("lon", "first"),
            source_lat=("lat", "first"),
            route_direction_count=("route_key", "nunique"),
            stop_occurrence_count=("route_key", "size"),
            assignment_distance_mean_m=("assignment_distance_m", "mean"),
            assignment_distance_max_m=("assignment_distance_m", "max"),
        )
    )
    facilities["facility_id"] = facilities.apply(
        lambda row: (
            f"pt_{safe_token(row['mode'])}_{safe_token(row['stop_id'])}_"
            f"{short_hash(str(row['link_id']))}"
        ),
        axis=1,
    )
    if facilities["facility_id"].duplicated().any():
        raise RuntimeError("Generated duplicate stop facility IDs")

    snapped_points = []
    for row in facilities.itertuples(index=False):
        source_point = Point(float(row.source_x), float(row.source_y))
        snapped_points.append(
            snap_point_to_line(source_point, link_geometries[row.link_id])
        )
    facility_gdf = gpd.GeoDataFrame(
        facilities,
        geometry=snapped_points,
        crs=NETWORK_CRS,
    )
    facility_gdf["x"] = facility_gdf.geometry.x
    facility_gdf["y"] = facility_gdf.geometry.y
    facility_gdf["facility_snap_distance_m"] = facility_gdf.geometry.distance(
        gpd.GeoSeries(
            gpd.points_from_xy(
                facility_gdf["source_x"], facility_gdf["source_y"]
            ),
            crs=NETWORK_CRS,
        )
    )
    facility_wgs84 = facility_gdf.to_crs("EPSG:4326")
    facility_gdf["lon"] = facility_wgs84.geometry.x.to_numpy()
    facility_gdf["lat"] = facility_wgs84.geometry.y.to_numpy()
    facility_gdf["link_ref_id"] = facility_gdf["link_id"]
    facility_gdf["block_lane"] = False
    facility_gdf["facility_role"] = facility_gdf["mode"].map(
        {
            "bus": "road_route_stop",
            "gmb": "road_route_stop",
            "mtr": "rail_platform_with_road_access",
            "lrt": "rail_platform_with_road_access",
        }
    )
    facility_gdf["physical_stop_key"] = (
        facility_gdf["mode"].astype(str)
        + "|"
        + facility_gdf["stop_id"].astype(str)
    )
    road_columns = [
        "physical_stop_key",
        "road_access_id",
        "nearest_road_link_id",
        "nearest_road_distance_m",
        "road_access_x",
        "road_access_y",
        "road_access_lon",
        "road_access_lat",
    ]
    facility_gdf = facility_gdf.merge(
        road_access[road_columns],
        on="physical_stop_key",
        how="left",
        validate="many_to_one",
    )
    facility_gdf["route_link_matches_nearest_road"] = (
        facility_gdf["link_ref_id"] == facility_gdf["nearest_road_link_id"]
    )

    facility_columns = [
        "facility_id",
        "mode",
        "stop_id",
        "stop_name_en",
        "stop_name_zh",
        "facility_role",
        "link_ref_id",
        "block_lane",
        "x",
        "y",
        "lon",
        "lat",
        "source_x",
        "source_y",
        "source_lon",
        "source_lat",
        "facility_snap_distance_m",
        "route_direction_count",
        "stop_occurrence_count",
        "assignment_distance_mean_m",
        "assignment_distance_max_m",
        "road_access_id",
        "nearest_road_link_id",
        "nearest_road_distance_m",
        "road_access_x",
        "road_access_y",
        "road_access_lon",
        "road_access_lat",
        "route_link_matches_nearest_road",
    ]
    facilities_output = pd.DataFrame(facility_gdf[facility_columns])

    assignments = stop_occurrences.merge(
        facilities_output[
            ["facility_id", "mode", "stop_id", "link_ref_id"]
        ],
        left_on=["mode", "stop_id", "link_id"],
        right_on=["mode", "stop_id", "link_ref_id"],
        how="left",
        validate="many_to_one",
    )
    if assignments["facility_id"].isna().any():
        raise RuntimeError("At least one route-stop occurrence lacks a facility")
    assignment_columns = [
        "route_key",
        "mode",
        "route_id",
        "route_seq",
        "company_code",
        "route_name",
        "stop_seq",
        "stop_id",
        "stop_name_en",
        "stop_name_zh",
        "facility_id",
        "link_ref_id",
        "route_link_index",
        "route_link_index_unwrapped",
        "pickup_dropoff_source",
        "await_departure",
        "coverage_distance_m",
        "assignment_distance_m",
        "external_or_uncovered",
    ]
    assignments["pickup_dropoff_source"] = "official_route_stop_data"
    assignments["await_departure"] = False
    return facilities_output, assignments[assignment_columns]


def percentile_summary(values: pd.Series) -> dict[str, float]:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return {
        "count": int(len(numeric)),
        "mean": float(numeric.mean()),
        "p50": float(numeric.quantile(0.50)),
        "p95": float(numeric.quantile(0.95)),
        "max": float(numeric.max()),
    }


def main() -> None:
    args = parse_args()
    transit_root = args.data_root / "transit/hongkong"
    mapmatch_dir = (
        transit_root / "processed/transit_route_link_mapmatching_2026_v2"
    )
    capacity_dir = (
        transit_root / "processed/public_transport_vehicle_capacities_inferred_2026"
    )
    output_dir = args.output_dir or (
        transit_root / "processed/transit_schedule_assembly_inputs_2026"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    qa_path = mapmatch_dir / "route_map_matching_qa.csv"
    sequences_path = mapmatch_dir / "route_link_sequences.csv"
    stop_snaps_path = mapmatch_dir / "stop_link_snaps.csv"
    network_path = mapmatch_dir / "network/hong_kong_transit_base_network.xml.gz"
    capacity_path = capacity_dir / "route_vehicle_type_assignments.csv"
    for path in [
        qa_path,
        sequences_path,
        stop_snaps_path,
        network_path,
        capacity_path,
    ]:
        if not path.exists():
            raise FileNotFoundError(path)

    route_qa = pd.read_csv(
        qa_path, dtype={"route_id": str, "route_seq": str}, low_memory=False
    )
    sequences = pd.read_csv(sequences_path, low_memory=False)
    stops = pd.read_csv(
        stop_snaps_path,
        dtype={"route_id": str, "route_seq": str, "stop_id": str},
        low_memory=False,
    )
    capacities = pd.read_csv(
        capacity_path, dtype={"route_id": str, "route_seq": str}, low_memory=False
    )
    nodes, network_links, link_geometries = read_network(network_path)
    network_link_ids = set(network_links["link_id"])

    approved = route_qa.copy()
    approved = approved.rename(
        columns={"acceptance_status": "original_acceptance_status"}
    )
    approved["approved_for_schedule"] = True
    approved["approval_status"] = "accepted"
    approved["approval_basis"] = APPROVAL_BASIS
    approved["requires_sensitivity_flag"] = approved[
        "original_acceptance_status"
    ].ne("accepted")
    approved = approved.merge(
        capacities[
            [
                "route_key",
                "vehicle_type_id",
                "assignment_method",
                "assignment_confidence",
                "capacity_assignment_status",
            ]
        ].rename(
            columns={
                "assignment_method": "capacity_assignment_method",
                "assignment_confidence": "capacity_assignment_confidence",
            }
        ),
        on="route_key",
        how="left",
        validate="one_to_one",
    )
    if approved["vehicle_type_id"].isna().any():
        raise RuntimeError("At least one approved route has no vehicle type")

    approved_sequences = sequences.merge(
        approved[
            [
                "route_key",
                "approval_status",
                "approval_basis",
                "requires_sensitivity_flag",
            ]
        ],
        on="route_key",
        how="left",
        validate="many_to_one",
    )
    if approved_sequences["approval_status"].isna().any():
        raise RuntimeError("At least one route-link sequence is not approved")

    occurrence_route_links = stops[["route_key", "link_id"]].merge(
        sequences[["route_key", "link_id"]].drop_duplicates(),
        on=["route_key", "link_id"],
        how="left",
        indicator=True,
    )
    route_link_reference_errors = int(
        occurrence_route_links["_merge"].ne("both").sum()
    )
    missing_network_links = sorted(
        (set(sequences["link_id"]) | set(stops["link_id"])) - network_link_ids
    )
    if route_link_reference_errors or missing_network_links:
        raise RuntimeError(
            f"Invalid route/stop links: route errors={route_link_reference_errors}, "
            f"network missing={len(missing_network_links)}"
        )

    road_links = network_links[network_links["is_road"]].copy()
    road_access, road_access_gdf = build_nearest_road_access(
        stops, road_links, link_geometries
    )
    facilities, route_stop_assignments = build_stop_facilities(
        stops, link_geometries, road_access
    )

    rail_access = road_access[road_access["mode"].isin(["mtr", "lrt"])].copy()
    rail_source = gpd.GeoDataFrame(
        rail_access,
        geometry=gpd.points_from_xy(rail_access["x"], rail_access["y"]),
        crs=NETWORK_CRS,
    )
    rail_target = gpd.GeoDataFrame(
        rail_access,
        geometry=gpd.points_from_xy(
            rail_access["road_access_x"], rail_access["road_access_y"]
        ),
        crs=NETWORK_CRS,
    )
    connectors = gpd.GeoDataFrame(
        rail_access.drop(
            columns=[column for column in rail_access.columns if column == "geometry"],
            errors="ignore",
        ),
        geometry=[
            LineString([source.geometry, target.geometry])
            for source, target in zip(
                rail_source.itertuples(index=False),
                rail_target.itertuples(index=False),
            )
        ],
        crs=NETWORK_CRS,
    ).to_crs("EPSG:4326")

    output_files = {
        "approved_routes": output_dir / "approved_route_directions.csv",
        "approved_sequences": output_dir / "approved_route_link_sequences.csv",
        "facilities": output_dir / "transit_stop_facilities.csv",
        "assignments": output_dir / "route_stop_facility_assignments.csv",
        "road_access": output_dir / "stop_nearest_road_access_snaps.csv",
        "rail_access": output_dir / "rail_station_nearest_road_access_snaps.csv",
        "rail_connectors": output_dir / "rail_station_road_access_connectors.geojson",
        "qa": output_dir / "schedule_assembly_input_qa.csv",
        "summary": output_dir / "schedule_assembly_input_summary.json",
    }
    approved.to_csv(output_files["approved_routes"], index=False, encoding="utf-8-sig")
    approved_sequences.to_csv(
        output_files["approved_sequences"], index=False, encoding="utf-8-sig"
    )
    facilities.to_csv(output_files["facilities"], index=False, encoding="utf-8-sig")
    route_stop_assignments.to_csv(
        output_files["assignments"], index=False, encoding="utf-8-sig"
    )
    road_access.to_csv(
        output_files["road_access"], index=False, encoding="utf-8-sig"
    )
    rail_access.to_csv(
        output_files["rail_access"], index=False, encoding="utf-8-sig"
    )
    connectors.to_file(output_files["rail_connectors"], driver="GeoJSON")

    road_stop_modes = facilities["mode"].isin(["bus", "gmb"])
    rail_stop_modes = facilities["mode"].isin(["mtr", "lrt"])
    qa_rows = [
        ("approved_route_directions", len(approved), 3570, len(approved) == 3570),
        ("all_routes_approved", int(approved["approved_for_schedule"].sum()), 3570, bool(approved["approved_for_schedule"].all())),
        ("approved_route_link_rows", len(approved_sequences), 554617, len(approved_sequences) == 554617),
        ("route_stop_occurrences", len(route_stop_assignments), 69841, len(route_stop_assignments) == 69841),
        ("route_stop_link_reference_errors", route_link_reference_errors, 0, route_link_reference_errors == 0),
        ("missing_network_link_references", len(missing_network_links), 0, len(missing_network_links) == 0),
        ("unique_facility_ids", facilities["facility_id"].nunique(), len(facilities), facilities["facility_id"].is_unique),
        ("road_stop_facilities_on_road_links", int(facilities.loc[road_stop_modes, "link_ref_id"].str.startswith("road_").sum()), int(road_stop_modes.sum()), bool(facilities.loc[road_stop_modes, "link_ref_id"].str.startswith("road_").all())),
        ("rail_stop_facilities_on_rail_links", int(facilities.loc[rail_stop_modes, "link_ref_id"].str.startswith("rail_").sum()), int(rail_stop_modes.sum()), bool(facilities.loc[rail_stop_modes, "link_ref_id"].str.startswith("rail_").all())),
        ("physical_stops_with_road_access", len(road_access), int(stops.groupby(["mode", "stop_id"]).ngroups), len(road_access) == stops.groupby(["mode", "stop_id"]).ngroups),
        ("rail_stations_with_road_access", len(rail_access), 165, len(rail_access) == 165),
        ("route_stop_assignments_with_facility", int(route_stop_assignments["facility_id"].notna().sum()), len(route_stop_assignments), bool(route_stop_assignments["facility_id"].notna().all())),
    ]
    qa = pd.DataFrame(qa_rows, columns=["check", "actual", "expected", "passed"])
    qa.to_csv(output_files["qa"], index=False, encoding="utf-8-sig")
    if not qa["passed"].all():
        raise RuntimeError(
            f"Schedule assembly input QA failed:\n{qa.loc[~qa['passed']].to_string(index=False)}"
        )

    original_status_counts = (
        approved["original_acceptance_status"].value_counts().to_dict()
    )
    facility_counts = facilities["mode"].value_counts().sort_index().to_dict()
    physical_stop_counts = (
        road_access["mode"].value_counts().sort_index().to_dict()
    )
    long_road_access = road_access["nearest_road_distance_m"] > 250.0
    road_mode_facilities = facilities["mode"].isin(["bus", "gmb"])
    summary = {
        "approval": {
            "basis": APPROVAL_BASIS,
            "route_directions": len(approved),
            "all_approved": True,
            "original_status_counts": original_status_counts,
            "original_manual_review_routes_now_approved": int(
                approved["requires_sensitivity_flag"].sum()
            ),
            "original_qa_preserved": str(qa_path.resolve()),
        },
        "network": {
            "path": str(network_path.resolve()),
            "crs": NETWORK_CRS,
            "nodes": len(nodes),
            "links": len(network_links),
            "road_links": len(road_links),
        },
        "route_links": {
            "rows": len(approved_sequences),
            "route_link_reference_errors": route_link_reference_errors,
            "missing_network_link_references": len(missing_network_links),
        },
        "stop_facilities": {
            "route_stop_occurrences": len(route_stop_assignments),
            "facility_count": len(facilities),
            "facility_counts_by_mode": facility_counts,
            "physical_stop_counts_by_mode": physical_stop_counts,
            "road_modes_use_route_compatible_road_link": True,
            "rail_modes_use_route_compatible_rail_link": True,
            "facility_snap_distance_by_mode_m": {
                mode: percentile_summary(group["facility_snap_distance_m"])
                for mode, group in facilities.groupby("mode")
            },
        },
        "road_access": {
            "all_physical_stops": len(road_access),
            "rail_physical_stations": len(rail_access),
            "stops_over_250m": int(long_road_access.sum()),
            "stops_over_250m_by_mode": (
                road_access.loc[long_road_access, "mode"]
                .value_counts()
                .sort_index()
                .to_dict()
            ),
            "road_mode_facilities_not_on_global_nearest_road": int(
                (~facilities.loc[
                    road_mode_facilities, "route_link_matches_nearest_road"
                ]).sum()
            ),
            "purpose": (
                "Rail platform facilities stay on rail links; these separate "
                "nearest-road anchors support walk/access connectors."
            ),
            "distance_by_mode_m": {
                mode: percentile_summary(group["nearest_road_distance_m"])
                for mode, group in road_access.groupby("mode")
            },
        },
        "outputs": {key: str(path.resolve()) for key, path in output_files.items()},
    }
    write_json(output_files["summary"], summary)

    manifest_files = sorted(
        path
        for path in output_dir.iterdir()
        if path.is_file() and path.name != "SHA256SUMS.txt"
    )
    (output_dir / "SHA256SUMS.txt").write_text(
        "\n".join(
            f"{sha256_file(path)}  {path.name}" for path in manifest_files
        )
        + "\n",
        encoding="ascii",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
