"""Build the offline Hong Kong public-transport fare catalog v1.

The script is read-only with respect to MATSim inputs. It inventories the
production transit schedule, normalizes official adult Octopus fares, and
matches official route/station identifiers to MATSim transit routes.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd


CANONICAL_SOURCE_ROOT = Path(r"F:\Matsim\matsim-example-project")
MODEL_EFFECTIVE_DATE = "2026-07-14"
SOURCE_DOWNLOAD_DATE = "2026-07-20"
TD_DATASET_URL = "https://data.gov.hk/en-data/dataset/hk-td-tis_11-pt-headway-en"
TD_GTFS_URL = "https://static.data.gov.hk/td/pt-headway-en/gtfs.zip"
TD_ROUTE_FARE_DATASET_URL = (
    "https://data.gov.hk/en-data/dataset/hk-td-tis_23-routes-fares-geojson"
)
MTR_DATASET_URL = (
    "https://data.gov.hk/en-data/dataset/"
    "mtr-data-routes-fares-barrier-free-facilities"
)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build official fare normalization and schedule matching for Hong Kong PT."
    )
    parser.add_argument(
        "--source-project-root",
        type=Path,
        default=None,
        help=(
            "Project root containing the ignored production data. Defaults to the current "
            "worktree when inputs exist, otherwise the canonical F-drive project."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Defaults to data/transport_costs/hongkong/pt_fare_v1 in this worktree.",
    )
    return parser.parse_args()


def choose_source_root(value: Path | None) -> Path:
    if value is not None:
        return value.resolve()
    local = repository_root()
    relative = (
        "data/transit/hongkong/processed/"
        "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_"
        "ferry_core_v1_cap010/transitSchedule_5pct.xml.gz"
    )
    if (local / relative).exists():
        return local
    return CANONICAL_SOURCE_ROOT


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def haversine_m(
    lon1: pd.Series, lat1: pd.Series, lon2: pd.Series, lat2: pd.Series
) -> np.ndarray:
    lon1r = np.radians(pd.to_numeric(lon1, errors="coerce").to_numpy(float))
    lat1r = np.radians(pd.to_numeric(lat1, errors="coerce").to_numpy(float))
    lon2r = np.radians(pd.to_numeric(lon2, errors="coerce").to_numpy(float))
    lat2r = np.radians(pd.to_numeric(lat2, errors="coerce").to_numpy(float))
    dlon = lon2r - lon1r
    dlat = lat2r - lat1r
    value = np.sin(dlat / 2) ** 2 + np.cos(lat1r) * np.cos(lat2r) * np.sin(
        dlon / 2
    ) ** 2
    return 6_371_008.8 * 2 * np.arcsin(np.minimum(1.0, np.sqrt(value)))


def read_schedule(schedule_path: Path) -> tuple[pd.DataFrame, dict[str, dict[str, Any]]]:
    with gzip.open(schedule_path, "rb") as handle:
        root = ET.parse(handle).getroot()

    facilities: dict[str, dict[str, Any]] = {}
    stops_parent = next((x for x in root if local_name(x.tag) == "transitStops"), None)
    if stops_parent is not None:
        for element in stops_parent:
            if local_name(element.tag) != "stopFacility":
                continue
            facilities[element.attrib["id"]] = {
                "name": element.attrib.get("name", ""),
                "x": float(element.attrib["x"]),
                "y": float(element.attrib["y"]),
                "link_ref_id": element.attrib.get("linkRefId", ""),
            }

    rows: list[dict[str, Any]] = []
    for line in root:
        if local_name(line.tag) != "transitLine":
            continue
        line_id = line.attrib["id"]
        line_name = line.attrib.get("name", "")
        for route in line:
            if local_name(route.tag) != "transitRoute":
                continue
            mode = ""
            stop_refs: list[str] = []
            departure_times: list[str] = []
            for child in route:
                child_tag = local_name(child.tag)
                if child_tag == "transportMode":
                    mode = (child.text or "").strip()
                elif child_tag == "routeProfile":
                    stop_refs = [
                        stop.attrib["refId"]
                        for stop in child
                        if local_name(stop.tag) == "stop"
                    ]
                elif child_tag == "departures":
                    departure_times = [
                        departure.attrib.get("departureTime", "")
                        for departure in child
                        if local_name(departure.tag) == "departure"
                    ]
            rows.append(
                {
                    "matsim_line_id": line_id,
                    "matsim_line_name": line_name,
                    "matsim_route_id": route.attrib["id"],
                    "transport_mode": mode,
                    "stop_count": len(stop_refs),
                    "departure_count": len(departure_times),
                    "first_departure": min(departure_times, default=""),
                    "last_departure": max(departure_times, default=""),
                    "first_stop_ref_id": stop_refs[0] if stop_refs else "",
                    "last_stop_ref_id": stop_refs[-1] if stop_refs else "",
                    "stop_ref_ids_json": json.dumps(stop_refs, ensure_ascii=False),
                }
            )
    return pd.DataFrame(rows), facilities


def official_route_id(mode: str, line_id: str, route_id: str) -> str:
    patterns = {
        "bus": r"^bus_(\d+)_",
        "gmb": r"^gmb_(\d+)_",
        "ferry": r"^ferry_(\d+)_",
    }
    if mode in patterns:
        match = re.match(patterns[mode], route_id)
        if match:
            return match.group(1)
    if mode == "train":
        match = re.match(r"^line_mtr_(.+)$", line_id)
        return match.group(1) if match else ""
    if mode == "light_rail":
        match = re.match(r"^line_lrt_(.+)$", line_id)
        return match.group(1) if match else ""
    return ""


def official_route_sequence(mode: str, route_id: str) -> str:
    if mode in {"bus", "gmb"}:
        match = re.match(r"^(?:bus|gmb)_\d+_([^_]+)", route_id)
        return match.group(1) if match else ""
    if mode == "light_rail":
        match = re.match(r"^lrt_[^_]+_([^_]+)", route_id)
        return match.group(1) if match else ""
    if mode == "train":
        match = re.match(r"^mtr_[^_]+_([^_]+)", route_id)
        return match.group(1) if match else ""
    return ""


def extract_road_stop_id(mode: str, facility_id: str) -> str:
    match = re.match(rf"^pt_{re.escape(mode)}_(\d+)_", facility_id)
    return match.group(1) if match else ""


def identify_station_code(facility_id: str, known_codes: set[str]) -> str:
    candidates = [
        code
        for code in known_codes
        if re.search(rf"(?:^|_){re.escape(code)}(?:_|$)", facility_id)
    ]
    return max(candidates, key=len) if candidates else ""


def read_gtfs(gtfs_path: Path) -> dict[str, pd.DataFrame]:
    names = ("agency.txt", "routes.txt", "stops.txt", "fare_attributes.txt", "fare_rules.txt")
    with zipfile.ZipFile(gtfs_path) as archive:
        return {
            name: pd.read_csv(archive.open(name), dtype=str, keep_default_na=False)
            for name in names
        }


def normalize_gtfs_fares(
    tables: dict[str, pd.DataFrame], schedule_route_ids: set[str]
) -> pd.DataFrame:
    fares = tables["fare_rules.txt"].merge(
        tables["fare_attributes.txt"], on="fare_id", how="left", validate="one_to_one"
    )
    routes = tables["routes.txt"][
        ["route_id", "route_short_name", "route_long_name", "route_type"]
    ]
    fares = fares.merge(routes, on="route_id", how="left", validate="many_to_one")
    stops = tables["stops.txt"][
        ["stop_id", "stop_name", "stop_lat", "stop_lon"]
    ].copy()
    origin = stops.add_prefix("origin_")
    destination = stops.add_prefix("destination_")
    fares = fares.merge(
        origin,
        left_on="origin_id",
        right_on="origin_stop_id",
        how="left",
        validate="many_to_one",
    ).merge(
        destination,
        left_on="destination_id",
        right_on="destination_stop_id",
        how="left",
        validate="many_to_one",
    )
    agency = fares["agency_id"].fillna("")
    fares["mode"] = np.select(
        [agency.eq("FERRY"), agency.eq("GMB"), agency.isin(["TRAM", "PTRAM"])],
        ["ferry", "gmb", "out_of_scope_tram"],
        default="bus",
    )
    fares["adult_octopus_fare_hkd"] = pd.to_numeric(fares["price"], errors="coerce")
    fares["euclidean_distance_m"] = haversine_m(
        fares["origin_stop_lon"],
        fares["origin_stop_lat"],
        fares["destination_stop_lon"],
        fares["destination_stop_lat"],
    )
    normalized = pd.DataFrame(
        {
            "mode": fares["mode"],
            "operator": fares["agency_id"],
            "official_route_id": fares["route_id"],
            "official_route_sequence": "",
            "origin_stop_id": fares["origin_id"],
            "destination_stop_id": fares["destination_id"],
            "origin_name": fares["origin_stop_name"],
            "destination_name": fares["destination_stop_name"],
            "adult_octopus_fare_hkd": fares["adult_octopus_fare_hkd"],
            "currency": fares["currency_type"],
            "fare_basis": "official_route_stop_od",
            "source_id": "td_gtfs_20260720",
            "source_effective_date": MODEL_EFFECTIVE_DATE,
            "source_download_date": SOURCE_DOWNLOAD_DATE,
            "in_schedule_scope": fares["route_id"].isin(schedule_route_ids),
            "euclidean_distance_m": fares["euclidean_distance_m"],
        }
    )
    return normalized[normalized["mode"] != "out_of_scope_tram"].reset_index(drop=True)


def projected_station_coordinates(
    facilities: dict[str, dict[str, Any]], station_codes: set[str], prefix: str
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for facility_id, values in facilities.items():
        if not facility_id.startswith(prefix):
            continue
        code = identify_station_code(facility_id, station_codes)
        if code:
            rows.append({"station_code": code, "x": values["x"], "y": values["y"]})
    if not rows:
        return pd.DataFrame(columns=["station_code", "x", "y"])
    return (
        pd.DataFrame(rows)
        .groupby("station_code", as_index=False)
        .agg(x=("x", "median"), y=("y", "median"))
    )


def normalize_mtr_fares(
    mtr_dir: Path, facilities: dict[str, dict[str, Any]]
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    station_lines = pd.read_csv(mtr_dir / "mtr_lines_and_stations.csv", dtype=str)
    station_lines = station_lines.rename(
        columns={
            "Line Code": "line_code",
            "Station Code": "station_code",
            "Station ID": "station_id",
            "English Name": "station_name",
        }
    )
    mtr_station_lookup = (
        station_lines[["line_code", "station_code", "station_id", "station_name"]]
        .dropna(subset=["station_code", "station_id"])
        .astype(str)
        .drop_duplicates()
        .groupby(["station_code", "station_id", "station_name"], as_index=False)
        .agg(line_codes=("line_code", lambda values: ";".join(sorted(set(values)))))
    )
    mtr_coords = projected_station_coordinates(
        facilities, set(mtr_station_lookup["station_code"]), "pt_mtr_"
    )
    mtr_station_lookup = mtr_station_lookup.merge(
        mtr_coords, on="station_code", how="left", validate="many_to_one"
    )

    lrt_lines = pd.read_csv(mtr_dir / "light_rail_routes_and_stops.csv", dtype=str)
    lrt_lines = lrt_lines.rename(
        columns={
            "Stop Code": "station_code",
            "Stop ID": "station_id",
            "English Name": "station_name",
        }
    )
    lrt_station_lookup = (
        lrt_lines[["station_code", "station_id", "station_name"]]
        .dropna(subset=["station_code", "station_id"])
        .astype(str)
        .drop_duplicates()
    )
    lrt_coords = projected_station_coordinates(
        facilities, set(lrt_station_lookup["station_code"]), "pt_lrt_"
    )
    lrt_station_lookup = lrt_station_lookup.merge(
        lrt_coords, on="station_code", how="left", validate="many_to_one"
    )

    def matrix(
        path: Path,
        mode: str,
        origin_id: str,
        destination_id: str,
        fare_column: str,
        station_lookup: pd.DataFrame,
        source_id: str,
        effective_date: str,
    ) -> pd.DataFrame:
        frame = pd.read_csv(path, dtype=str)
        frame["origin_stop_id"] = frame[origin_id].astype(str)
        frame["destination_stop_id"] = frame[destination_id].astype(str)
        origin = station_lookup.add_prefix("origin_")
        destination = station_lookup.add_prefix("destination_")
        frame = frame.merge(
            origin,
            left_on="origin_stop_id",
            right_on="origin_station_id",
            how="left",
            validate="many_to_one",
        ).merge(
            destination,
            left_on="destination_stop_id",
            right_on="destination_station_id",
            how="left",
            validate="many_to_one",
        )
        frame["euclidean_distance_m"] = np.hypot(
            pd.to_numeric(frame["destination_x"], errors="coerce")
            - pd.to_numeric(frame["origin_x"], errors="coerce"),
            pd.to_numeric(frame["destination_y"], errors="coerce")
            - pd.to_numeric(frame["origin_y"], errors="coerce"),
        )
        return pd.DataFrame(
            {
                "mode": mode,
                "operator": "MTR",
                "official_route_id": "",
                "official_route_sequence": "",
                "origin_stop_id": frame["origin_stop_id"],
                "destination_stop_id": frame["destination_stop_id"],
                "origin_name": frame["origin_station_name"],
                "destination_name": frame["destination_station_name"],
                "adult_octopus_fare_hkd": pd.to_numeric(
                    frame[fare_column], errors="coerce"
                ),
                "currency": "HKD",
                "fare_basis": "official_station_od",
                "source_id": source_id,
                "source_effective_date": effective_date,
                "source_download_date": SOURCE_DOWNLOAD_DATE,
                "in_schedule_scope": True,
                "euclidean_distance_m": frame["euclidean_distance_m"],
            }
        )

    domestic = matrix(
        mtr_dir / "mtr_lines_fares.csv",
        "train",
        "SRC_STATION_ID",
        "DEST_STATION_ID",
        "OCT_ADT_FARE",
        mtr_station_lookup,
        "mtr_domestic_fares_20260720",
        "2024-06-30",
    )
    airport = matrix(
        mtr_dir / "airport_express_fares.csv",
        "train",
        "ST_FROM_ID",
        "ST_TO_ID",
        "OCT_ADT_FARE",
        mtr_station_lookup,
        "mtr_airport_express_fares_20260720",
        "2025-06-22",
    )
    light_rail = matrix(
        mtr_dir / "light_rail_fares.csv",
        "light_rail",
        "from_station_id",
        "to_station_id",
        "fare_octo_adult",
        lrt_station_lookup,
        "mtr_light_rail_fares_20260720",
        "2024-06-30",
    )
    return (
        pd.concat([domestic, airport, light_rail], ignore_index=True),
        mtr_station_lookup,
        lrt_station_lookup,
    )


def read_route_full_fares(api_dir: Path) -> pd.DataFrame:
    specifications = [
        ("bus", "bus_route_stop_points.json", "td_bus_route_fares_20260720"),
        ("gmb", "gmb_route_stop_points.json", "td_gmb_route_fares_20260720"),
        ("ferry", "ferry_route_stop_points.json", "td_ferry_route_fares_20260720"),
    ]
    rows: list[dict[str, Any]] = []
    for mode, filename, source_id in specifications:
        with (api_dir / filename).open("r", encoding="utf-8-sig") as handle:
            features = json.load(handle).get("features", [])
        for feature in features:
            properties = feature.get("properties") or {}
            fare = properties.get("fullFare")
            if fare in (None, ""):
                continue
            rows.append(
                {
                    "mode": mode,
                    "operator": str(properties.get("companyCode", "")),
                    "official_route_id": str(properties.get("routeId", "")),
                    "official_route_sequence": str(properties.get("routeSeq", "")),
                    "route_name": str(properties.get("routeNameE", "")),
                    "adult_octopus_fare_hkd": float(fare),
                    "source_record_last_update": str(
                        properties.get("lastUpdateDate", "")
                    )[:10],
                    "source_id": source_id,
                }
            )
    return pd.DataFrame(rows).drop_duplicates(
        ["mode", "operator", "official_route_id", "official_route_sequence"]
    )


def make_source_manifest(source_root: Path, paths: dict[str, Path]) -> pd.DataFrame:
    metadata = {
        "td_gtfs": {
            "mode_scope": "franchised_bus;gmb;ferry;other_bus",
            "source_url": TD_GTFS_URL,
            "source_dataset_url": TD_DATASET_URL,
            "effective_date": MODEL_EFFECTIVE_DATE,
            "effective_date_basis": "TD data revision cut-off date",
            "effective_date_status": "local_source_proven",
            "download_date": SOURCE_DOWNLOAD_DATE,
            "download_date_basis": "local snapshot creation date",
            "official": True,
        },
        "td_bus_route_fares": {
            "mode_scope": "franchised_bus;other_bus",
            "source_url": (
                "https://static.data.gov.hk/td/routes-fares-geojson/JSON_BUS.json"
            ),
            "source_dataset_url": TD_ROUTE_FARE_DATASET_URL,
            "effective_date": MODEL_EFFECTIVE_DATE,
            "effective_date_basis": "TD data revision cut-off date",
            "effective_date_status": "local_source_proven",
            "download_date": SOURCE_DOWNLOAD_DATE,
            "download_date_basis": "API download manifest",
            "official": True,
        },
        "td_gmb_route_fares": {
            "mode_scope": "gmb",
            "source_url": (
                "https://static.data.gov.hk/td/routes-fares-geojson/JSON_GMB.json"
            ),
            "source_dataset_url": TD_ROUTE_FARE_DATASET_URL,
            "effective_date": MODEL_EFFECTIVE_DATE,
            "effective_date_basis": "TD data revision cut-off date",
            "effective_date_status": "local_source_proven",
            "download_date": SOURCE_DOWNLOAD_DATE,
            "download_date_basis": "API download manifest",
            "official": True,
        },
        "td_ferry_route_fares": {
            "mode_scope": "ferry",
            "source_url": (
                "https://static.data.gov.hk/td/routes-fares-geojson/JSON_FERRY.json"
            ),
            "source_dataset_url": TD_ROUTE_FARE_DATASET_URL,
            "effective_date": MODEL_EFFECTIVE_DATE,
            "effective_date_basis": "TD data revision cut-off date",
            "effective_date_status": "local_source_proven",
            "download_date": SOURCE_DOWNLOAD_DATE,
            "download_date_basis": "API download manifest",
            "official": True,
        },
        "mtr_domestic_fares": {
            "mode_scope": "mtr",
            "source_url": "https://opendata.mtr.com.hk/data/mtr_lines_fares.csv",
            "source_dataset_url": MTR_DATASET_URL,
            "effective_date": "2024-06-30",
            "effective_date_basis": (
                "adult controlled fares effective 2024-06-30 and frozen in "
                "2025/26 and 2026/27"
            ),
            "effective_date_status": (
                "external_official_reference_not_locally_archived"
            ),
            "download_date": SOURCE_DOWNLOAD_DATE,
            "download_date_basis": "local snapshot creation date",
            "official": True,
        },
        "mtr_airport_express_fares": {
            "mode_scope": "mtr_airport_express",
            "source_url": "https://opendata.mtr.com.hk/data/airport_express_fares.csv",
            "source_dataset_url": MTR_DATASET_URL,
            "effective_date": "2025-06-22",
            "effective_date_basis": "MTR announced Airport Express fare effective date",
            "effective_date_status": (
                "external_official_reference_not_locally_archived"
            ),
            "download_date": SOURCE_DOWNLOAD_DATE,
            "download_date_basis": "local snapshot creation date",
            "official": True,
        },
        "mtr_light_rail_fares": {
            "mode_scope": "light_rail",
            "source_url": "https://opendata.mtr.com.hk/data/light_rail_fares.csv",
            "source_dataset_url": MTR_DATASET_URL,
            "effective_date": "2024-06-30",
            "effective_date_basis": (
                "adult controlled fares effective 2024-06-30 and frozen in "
                "2025/26 and 2026/27"
            ),
            "effective_date_status": (
                "external_official_reference_not_locally_archived"
            ),
            "download_date": SOURCE_DOWNLOAD_DATE,
            "download_date_basis": "local snapshot creation date",
            "official": True,
        },
        "production_transit_schedule": {
            "mode_scope": "model_input",
            "source_url": "project_input",
            "source_dataset_url": "project_input",
            "effective_date": "2026-07-22",
            "effective_date_basis": "representative MATSim service date",
            "effective_date_status": "project_input_proven",
            "download_date": "",
            "download_date_basis": "not applicable",
            "official": False,
        },
        "approved_route_inventory": {
            "mode_scope": "model_input",
            "source_url": "project_input",
            "source_dataset_url": "project_input",
            "effective_date": "2026-07-22",
            "effective_date_basis": "route assembly approval date",
            "effective_date_status": "project_input_proven",
            "download_date": "",
            "download_date_basis": "not applicable",
            "official": False,
        },
        "ferry_stop_facilities": {
            "mode_scope": "model_input",
            "source_url": "project_input",
            "source_dataset_url": "project_input",
            "effective_date": "2026-07-22",
            "effective_date_basis": "production supply build",
            "effective_date_status": "project_input_proven",
            "download_date": "",
            "download_date_basis": "not applicable",
            "official": False,
        },
        "mtr_line_station_patterns": {
            "mode_scope": "mtr_route_direction_mapping",
            "source_url": (
                "https://opendata.mtr.com.hk/data/mtr_lines_and_stations.csv"
            ),
            "source_dataset_url": MTR_DATASET_URL,
            "effective_date": "",
            "effective_date_basis": "not a fare-effective-date source",
            "effective_date_status": "not_applicable",
            "download_date": SOURCE_DOWNLOAD_DATE,
            "download_date_basis": "local snapshot creation date",
            "official": True,
        },
        "mtr_light_rail_stop_patterns": {
            "mode_scope": "light_rail_route_direction_mapping",
            "source_url": (
                "https://opendata.mtr.com.hk/data/"
                "light_rail_routes_and_stops.csv"
            ),
            "source_dataset_url": MTR_DATASET_URL,
            "effective_date": "",
            "effective_date_basis": "not a fare-effective-date source",
            "effective_date_status": "not_applicable",
            "download_date": SOURCE_DOWNLOAD_DATE,
            "download_date_basis": "local snapshot creation date",
            "official": True,
        },
        "td_route_fare_revision_date": {
            "mode_scope": "td_fare_effective_date_evidence",
            "source_url": (
                "https://static.data.gov.hk/td/routes-fares-geojson/"
                "DATA_LAST_UPDATED_DATE.csv"
            ),
            "source_dataset_url": TD_ROUTE_FARE_DATASET_URL,
            "effective_date": MODEL_EFFECTIVE_DATE,
            "effective_date_basis": "locally archived TD revision cut-off file",
            "effective_date_status": "local_source_proven",
            "download_date": SOURCE_DOWNLOAD_DATE,
            "download_date_basis": "API download manifest",
            "official": True,
        },
    }
    rows: list[dict[str, Any]] = []
    for source_id, path in paths.items():
        details = metadata[source_id]
        rows.append(
            {
                "source_id": source_id,
                **details,
                "repository_relative_path": path.resolve()
                .relative_to(source_root.resolve())
                .as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    return pd.DataFrame(rows)


def attach_inventory_metadata(
    inventory: pd.DataFrame,
    approved_path: Path,
    gtfs_routes: pd.DataFrame,
    mtr_station_lookup: pd.DataFrame,
    lrt_station_lookup: pd.DataFrame,
    ferry_stops_path: Path,
) -> pd.DataFrame:
    inventory = inventory.copy()
    inventory["official_route_id"] = [
        official_route_id(mode, line_id, route_id)
        for mode, line_id, route_id in inventory[
            ["transport_mode", "matsim_line_id", "matsim_route_id"]
        ].itertuples(index=False, name=None)
    ]
    inventory["official_route_sequence"] = [
        official_route_sequence(mode, route_id)
        for mode, route_id in inventory[
            ["transport_mode", "matsim_route_id"]
        ].itertuples(index=False, name=None)
    ]

    approved = pd.read_csv(approved_path, dtype=str, keep_default_na=False)
    approved = approved[
        ["route_key", "company_code", "route_name", "approval_status"]
    ].rename(columns={"route_key": "matsim_route_id"})
    inventory = inventory.merge(
        approved, on="matsim_route_id", how="left", validate="one_to_one"
    )
    gtfs_meta = gtfs_routes[
        ["route_id", "agency_id", "route_short_name", "route_long_name"]
    ].rename(columns={"route_id": "official_route_id"})
    inventory = inventory.merge(
        gtfs_meta, on="official_route_id", how="left", validate="many_to_one"
    )
    inventory["operator"] = inventory["company_code"].fillna("")
    inventory.loc[inventory["operator"].eq(""), "operator"] = inventory[
        "agency_id"
    ].fillna("")
    inventory.loc[
        inventory["transport_mode"].isin(["train", "light_rail"]), "operator"
    ] = "MTR"

    mtr_codes = set(mtr_station_lookup["station_code"])
    lrt_codes = set(lrt_station_lookup["station_code"])
    ferry_stops = pd.read_csv(ferry_stops_path, dtype=str).set_index("facility_id")[
        "stop_id"
    ].to_dict()

    official_stop_lists: list[list[str]] = []
    for mode, encoded, line_code in inventory[
        ["transport_mode", "stop_ref_ids_json", "official_route_id"]
    ].itertuples(index=False, name=None):
        refs = json.loads(encoded)
        if mode in {"bus", "gmb"}:
            stops = [extract_road_stop_id(mode, item) for item in refs]
        elif mode == "ferry":
            stops = [str(ferry_stops.get(item, "")) for item in refs]
        elif mode == "train":
            stops = [identify_station_code(item, mtr_codes) for item in refs]
            code_line_to_id: dict[tuple[str, str], str] = {}
            code_fallback_to_id: dict[str, str] = {}
            for station in mtr_station_lookup.to_dict("records"):
                code_fallback_to_id.setdefault(
                    station["station_code"], str(station["station_id"])
                )
                for station_line in str(station["line_codes"]).split(";"):
                    code_line_to_id[(station_line, station["station_code"])] = str(
                        station["station_id"]
                    )
            stops = [
                code_line_to_id.get(
                    (str(line_code), item), code_fallback_to_id.get(item, "")
                )
                for item in stops
            ]
        elif mode == "light_rail":
            stops = [identify_station_code(item, lrt_codes) for item in refs]
            code_to_id = lrt_station_lookup.set_index("station_code")[
                "station_id"
            ].to_dict()
            stops = [str(code_to_id.get(item, "")) for item in stops]
        else:
            stops = ["" for _ in refs]
        official_stop_lists.append(stops)
    inventory["official_stop_ids_json"] = [
        json.dumps(stops, ensure_ascii=False) for stops in official_stop_lists
    ]
    inventory["official_stop_id_coverage"] = [
        sum(bool(item) for item in stops) / len(stops) if stops else 0.0
        for stops in official_stop_lists
    ]
    return inventory


def build_official_direction_patterns(api_dir: Path, mtr_dir: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    ferry_path = api_dir / "ferry_route_stop_points.json"
    with ferry_path.open("r", encoding="utf-8-sig") as handle:
        ferry_features = json.load(handle).get("features", [])
    ferry_rows = []
    for feature in ferry_features:
        properties = feature.get("properties") or {}
        if properties.get("routeId") in (None, ""):
            continue
        ferry_rows.append(
            {
                "official_line_id": str(properties["routeId"]),
                "official_direction": str(properties.get("routeSeq", "")),
                "sequence": int(properties.get("stopSeq", 0)),
                "official_stop_id": str(properties.get("stopId", "")),
            }
        )
    ferry = pd.DataFrame(ferry_rows)
    for (line_id, direction), group in ferry.groupby(
        ["official_line_id", "official_direction"]
    ):
        stops = group.sort_values("sequence")["official_stop_id"].tolist()
        rows.append(
            {
                "transport_mode": "ferry",
                "official_line_id": line_id,
                "official_direction": direction,
                "official_stop_count": len(stops),
                "official_stop_ids_json": json.dumps(stops),
                "pattern_source_id": "td_ferry_route_fares",
            }
        )

    specifications = [
        (
            "train",
            mtr_dir / "mtr_lines_and_stations.csv",
            "Line Code",
            "Direction",
            "Station ID",
            "Sequence",
            "mtr_line_station_patterns",
        ),
        (
            "light_rail",
            mtr_dir / "light_rail_routes_and_stops.csv",
            "Line Code",
            "Direction",
            "Stop ID",
            "Sequence",
            "mtr_light_rail_stop_patterns",
        ),
    ]
    for (
        mode,
        path,
        line_column,
        direction_column,
        stop_column,
        sequence_column,
        source_id,
    ) in specifications:
        frame = pd.read_csv(path, dtype=str)
        frame[sequence_column] = pd.to_numeric(frame[sequence_column], errors="raise")
        for (line_id, direction), group in frame.groupby(
            [line_column, direction_column]
        ):
            stops = (
                group.sort_values(sequence_column)[stop_column].astype(str).tolist()
            )
            rows.append(
                {
                    "transport_mode": mode,
                    "official_line_id": str(line_id),
                    "official_direction": str(direction),
                    "official_stop_count": len(stops),
                    "official_stop_ids_json": json.dumps(stops),
                    "pattern_source_id": source_id,
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["transport_mode", "official_line_id", "official_direction"]
    )


def contiguous_subsequence(candidate: list[str], sequence: list[str]) -> bool:
    if not candidate or len(candidate) > len(sequence):
        return False
    return any(
        sequence[index : index + len(candidate)] == candidate
        for index in range(len(sequence) - len(candidate) + 1)
    )


def required_forward_pairs(stops: list[str]) -> set[tuple[str, str]]:
    return {
        (stops[i], stops[j])
        for i in range(len(stops))
        for j in range(i + 1, len(stops))
        if stops[i] and stops[j] and stops[i] != stops[j]
    }


def build_route_matches(
    inventory: pd.DataFrame,
    normalized: pd.DataFrame,
    full_fares: pd.DataFrame,
    direction_patterns: pd.DataFrame,
) -> pd.DataFrame:
    fares = normalized.copy()
    for column in ("mode", "official_route_id", "origin_stop_id", "destination_stop_id"):
        fares[column] = fares[column].fillna("").astype(str)

    road_pair_lookup: dict[tuple[str, str], set[tuple[str, str]]] = {}
    road_source_lookup: dict[tuple[str, str], list[str]] = {}
    for (mode, route_id), group in fares[
        fares["mode"].isin(["bus", "gmb", "ferry"])
        & fares["official_route_id"].ne("")
    ].groupby(["mode", "official_route_id"]):
        road_pair_lookup[(mode, route_id)] = set(
            zip(group["origin_stop_id"], group["destination_stop_id"])
        )
        road_source_lookup[(mode, route_id)] = sorted(
            set(group["source_id"].astype(str))
        )

    rail_pair_lookup: dict[str, set[tuple[str, str]]] = {
        "train_domestic": set(
            zip(
                fares.loc[
                    fares["source_id"].eq("mtr_domestic_fares_20260720"),
                    "origin_stop_id",
                ],
                fares.loc[
                    fares["source_id"].eq("mtr_domestic_fares_20260720"),
                    "destination_stop_id",
                ],
            )
        ),
        "train_airport_express": set(
            zip(
                fares.loc[
                    fares["source_id"].eq(
                        "mtr_airport_express_fares_20260720"
                    ),
                    "origin_stop_id",
                ],
                fares.loc[
                    fares["source_id"].eq(
                        "mtr_airport_express_fares_20260720"
                    ),
                    "destination_stop_id",
                ],
            )
        ),
        "light_rail": set(
            zip(
                fares.loc[fares["mode"].eq("light_rail"), "origin_stop_id"],
                fares.loc[fares["mode"].eq("light_rail"), "destination_stop_id"],
            )
        ),
    }
    full_count_lookup = (
        full_fares.groupby(
            ["mode", "official_route_id", "official_route_sequence"]
        )
        .size()
        .to_dict()
    )
    pattern_lookup: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for pattern in direction_patterns.to_dict("records"):
        pattern_lookup.setdefault(
            (pattern["transport_mode"], str(pattern["official_line_id"])), []
        ).append(pattern)

    rows: list[dict[str, Any]] = []
    for record in inventory.to_dict("records"):
        mode = str(record["transport_mode"])
        route_id = str(record["official_route_id"])
        route_sequence = str(record["official_route_sequence"])
        stops = [
            str(item)
            for item in json.loads(record["official_stop_ids_json"])
            if str(item)
        ]
        scheduled_stop_count = int(record["stop_count"])
        mapped_stop_count = len(stops)
        stop_coverage = (
            mapped_stop_count / scheduled_stop_count if scheduled_stop_count else 0.0
        )
        required_pairs = required_forward_pairs(stops)
        full_fare_record_count = int(
            full_count_lookup.get((mode, route_id, route_sequence), 0)
        )
        official_line_id = route_id
        official_direction = ""
        candidate_count = 0
        route_identifier_status = "unresolved"
        direction_status = "unresolved"
        fare_scope = ""
        mapping_status = "unresolved"
        mapping_quality = "U"
        matching_method = ""
        unresolved_reason = ""
        candidate_method = "none"
        direction_edge_coverage = 0.0

        if mode in {"bus", "gmb", "ferry"}:
            official_pairs = road_pair_lookup.get((mode, route_id), set())
        elif mode == "train":
            fare_scope = (
                "airport_express_station_od"
                if route_id == "AEL"
                else "domestic_mtr_station_od"
            )
            official_pairs = rail_pair_lookup[
                "train_airport_express"
                if route_id == "AEL"
                else "train_domestic"
            ]
        elif mode == "light_rail":
            fare_scope = "light_rail_station_od"
            official_pairs = rail_pair_lookup["light_rail"]
        else:
            official_pairs = set()

        matched_pairs = required_pairs & official_pairs
        forward_coverage = (
            len(matched_pairs) / len(required_pairs) if required_pairs else 0.0
        )
        official_od_pair_count = len(official_pairs)

        if mode in {"bus", "gmb"}:
            fare_scope = "route_stop_od"
            candidate_count = int(bool(official_pairs))
            route_identifier_status = (
                "matched_official_route_id"
                if candidate_count == 1
                else "official_route_id_without_fare_candidate"
            )
            direction_status = "direction_not_encoded"
            matching_method = "route_id_plus_schedule_forward_stop_pair_coverage"
            if (
                candidate_count == 1
                and stop_coverage == 1.0
                and forward_coverage == 1.0
            ):
                mapping_status = "partial"
                mapping_quality = "B"
                unresolved_reason = "direction_not_encoded_in_official_fare_rules"
            elif candidate_count == 1:
                mapping_status = "partial"
                mapping_quality = "C"
                unresolved_reason = "incomplete_stop_or_forward_od_pair_coverage"
            else:
                mapping_status = "unresolved"
                mapping_quality = "U"
                unresolved_reason = (
                    "official_route_fare_and_stop_evidence_missing"
                )
        elif mode in {"ferry", "train", "light_rail"}:
            if mode == "ferry":
                fare_scope = "route_stop_od_with_official_direction_pattern"
            line_patterns = pattern_lookup.get((mode, official_line_id), [])
            exact_candidates = [
                pattern
                for pattern in line_patterns
                if json.loads(pattern["official_stop_ids_json"]) == stops
            ]
            subsequence_candidates = [
                pattern
                for pattern in line_patterns
                if contiguous_subsequence(
                    stops, json.loads(pattern["official_stop_ids_json"])
                )
            ]
            if exact_candidates:
                candidates = exact_candidates
                candidate_method = "exact_official_stop_sequence"
            elif mode != "ferry" and subsequence_candidates:
                candidates = subsequence_candidates
                candidate_method = "schedule_contiguous_subsequence"
            elif mode != "ferry":
                scheduled_edges = set(zip(stops, stops[1:]))
                candidates = []
                for pattern in line_patterns:
                    pattern_stops = json.loads(pattern["official_stop_ids_json"])
                    pattern_edges = set(zip(pattern_stops, pattern_stops[1:]))
                    if scheduled_edges & pattern_edges:
                        candidates.append(pattern)
                candidate_method = (
                    "multiple_explicit_direction_edge_composition"
                    if len(candidates) > 1
                    else "partial_direction_edge_evidence"
                )
            else:
                candidates = []
                candidate_method = "no_exact_official_ferry_stop_pattern"

            candidate_count = len(candidates)
            route_identifier_status = (
                "matched_official_line_id"
                if line_patterns
                else "official_line_id_without_direction_pattern"
            )
            official_direction = ";".join(
                sorted(
                    {
                        str(pattern["official_direction"])
                        for pattern in candidates
                    }
                )
            )
            scheduled_edges = set(zip(stops, stops[1:]))
            candidate_edges: set[tuple[str, str]] = set()
            for pattern in candidates:
                pattern_stops = json.loads(pattern["official_stop_ids_json"])
                candidate_edges.update(zip(pattern_stops, pattern_stops[1:]))
            direction_edge_coverage = (
                len(scheduled_edges & candidate_edges) / len(scheduled_edges)
                if scheduled_edges
                else 0.0
            )

            if candidate_method == "exact_official_stop_sequence":
                direction_status = "explicit_direction_exact"
                matching_method = "line_direction_and_exact_schedule_stop_sequence"
                if (
                    candidate_count == 1
                    and stop_coverage == 1.0
                    and forward_coverage == 1.0
                ):
                    mapping_status = "exact"
                    mapping_quality = "A"
                else:
                    mapping_status = "partial"
                    mapping_quality = "C"
                    unresolved_reason = (
                        "explicit_direction_but_incomplete_forward_od_pair_coverage"
                    )
            elif candidate_method == "schedule_contiguous_subsequence":
                direction_status = "explicit_direction_short_turn"
                matching_method = "line_direction_and_schedule_stop_subsequence"
                mapping_status = "partial"
                mapping_quality = (
                    "B"
                    if candidate_count == 1
                    and stop_coverage == 1.0
                    and forward_coverage == 1.0
                    else "C"
                )
                unresolved_reason = (
                    "schedule_short_turn_not_separate_official_direction"
                )
            elif (
                candidate_count > 1
                and direction_edge_coverage == 1.0
                and stop_coverage == 1.0
                and forward_coverage == 1.0
            ):
                direction_status = "explicit_multi_direction_composite"
                matching_method = "line_plus_multiple_official_direction_segments"
                mapping_status = "one_to_many_explicit"
                mapping_quality = "B"
            elif candidate_count > 1:
                direction_status = "multiple_direction_candidates_not_disambiguated"
                matching_method = "line_plus_partial_direction_edge_overlap"
                mapping_status = "ambiguous"
                mapping_quality = "D"
                unresolved_reason = "multiple_direction_candidates_not_disambiguated"
            elif official_pairs and forward_coverage == 1.0:
                direction_status = "direction_pattern_not_available"
                matching_method = "line_or_route_id_plus_forward_stop_pair_coverage"
                mapping_status = "partial"
                mapping_quality = "C"
                unresolved_reason = "official_direction_stop_pattern_not_available"
            else:
                direction_status = "unresolved"
                matching_method = "no_verifiable_line_direction_stop_sequence_match"
                mapping_status = "unresolved"
                mapping_quality = "U"
                unresolved_reason = "insufficient_line_direction_or_fare_evidence"
        else:
            route_identifier_status = "not_applicable"
            direction_status = "not_applicable"
            fare_scope = "not_applicable"
            mapping_status = "not_applicable"
            mapping_quality = "U"
            matching_method = "mode_not_in_v1_scope"

        evidence = json.dumps(
            {
                "candidate_method": candidate_method,
                "direction_edge_coverage": round(direction_edge_coverage, 6),
                "fare_source_ids": (
                    road_source_lookup.get((mode, route_id), [])
                    if mode in {"bus", "gmb", "ferry"}
                    else ["mtr_airport_express_fares_20260720"]
                    if mode == "train" and route_id == "AEL"
                    else ["mtr_domestic_fares_20260720"]
                    if mode == "train"
                    else ["mtr_light_rail_fares_20260720"]
                    if mode == "light_rail"
                    else []
                ),
                "official_stop_ids": stops,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        rows.append(
            {
                "matsim_line_id": record["matsim_line_id"],
                "matsim_route_id": record["matsim_route_id"],
                "transport_mode": mode,
                "operator": str(record.get("operator", "")),
                "official_route_id": route_id,
                "official_route_sequence": route_sequence,
                "official_line_id": official_line_id,
                "official_direction": official_direction,
                "scheduled_stop_count": scheduled_stop_count,
                "mapped_stop_count": mapped_stop_count,
                "stop_id_coverage": round(stop_coverage, 6),
                "candidate_count": candidate_count,
                "candidate_cardinality": (
                    "none"
                    if candidate_count == 0
                    else "one"
                    if candidate_count == 1
                    else "multiple"
                ),
                "route_identifier_status": route_identifier_status,
                "direction_status": direction_status,
                "fare_scope": fare_scope,
                "official_od_pair_count": official_od_pair_count,
                "required_forward_pair_count": len(required_pairs),
                "matched_forward_pair_count": len(matched_pairs),
                "forward_pair_coverage": round(forward_coverage, 6),
                "full_fare_record_count": full_fare_record_count,
                "mapping_status": mapping_status,
                "mapping_quality": mapping_quality,
                "matching_method": matching_method,
                "evidence": evidence,
                "unresolved_reason": unresolved_reason,
            }
        )
    return pd.DataFrame(rows)


def write_sha256s(output_dir: Path) -> None:
    paths = sorted(
        path
        for path in output_dir.iterdir()
        if path.is_file() and path.name != "SHA256SUMS.txt"
    )
    lines = [f"{sha256(path)}  {path.name}" for path in paths]
    (output_dir / "SHA256SUMS.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def main() -> None:
    args = parse_args()
    source_root = choose_source_root(args.source_project_root)
    output_dir = (
        args.output_dir.resolve()
        if args.output_dir
        else repository_root()
        / "data/transport_costs/hongkong/pt_fare_v1"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    supply_dir = source_root / (
        "data/transit/hongkong/processed/"
        "matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_"
        "ferry_core_v1_cap010"
    )
    assembly_dir = source_root / (
        "data/transit/hongkong/processed/transit_schedule_assembly_inputs_2026"
    )
    gtfs_path = source_root / "data/transit/hongkong/PublicTransportGTFS/gtfs.zip"
    mtr_dir = source_root / "data/transit/hongkong/MTR"
    api_dir = source_root / (
        "data/transit/hongkong/API_Supplements/static/"
        "routes_fares_route_stop_points"
    )
    schedule_path = supply_dir / "transitSchedule_5pct.xml.gz"
    approved_path = assembly_dir / "approved_route_directions.csv"
    ferry_stops_path = supply_dir / "ferry_stop_facilities.csv"

    required = [
        schedule_path,
        approved_path,
        ferry_stops_path,
        gtfs_path,
        mtr_dir / "mtr_lines_fares.csv",
        mtr_dir / "airport_express_fares.csv",
        mtr_dir / "light_rail_fares.csv",
        mtr_dir / "mtr_lines_and_stations.csv",
        mtr_dir / "light_rail_routes_and_stops.csv",
        api_dir / "routes_fares_last_updated.csv",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Required inputs are missing: {missing}")

    print("Reading production transit schedule...", flush=True)
    inventory, facilities = read_schedule(schedule_path)
    gtfs = read_gtfs(gtfs_path)
    mtr_fares, mtr_stations, lrt_stations = normalize_mtr_fares(
        mtr_dir, facilities
    )
    inventory = attach_inventory_metadata(
        inventory,
        approved_path,
        gtfs["routes.txt"],
        mtr_stations,
        lrt_stations,
        ferry_stops_path,
    )
    schedule_route_ids = set(inventory["official_route_id"].astype(str))

    print("Normalizing official GTFS and MTR fare matrices...", flush=True)
    gtfs_fares = normalize_gtfs_fares(gtfs, schedule_route_ids)
    normalized = pd.concat([gtfs_fares, mtr_fares], ignore_index=True)
    normalized["adult_octopus_fare_hkd"] = pd.to_numeric(
        normalized["adult_octopus_fare_hkd"], errors="coerce"
    )
    full_fares = read_route_full_fares(api_dir)
    direction_patterns = build_official_direction_patterns(api_dir, mtr_dir)
    route_matches = build_route_matches(
        inventory, normalized, full_fares, direction_patterns
    )

    source_paths = {
        "td_gtfs": gtfs_path,
        "td_bus_route_fares": api_dir / "bus_route_stop_points.json",
        "td_gmb_route_fares": api_dir / "gmb_route_stop_points.json",
        "td_ferry_route_fares": api_dir / "ferry_route_stop_points.json",
        "mtr_domestic_fares": mtr_dir / "mtr_lines_fares.csv",
        "mtr_airport_express_fares": mtr_dir / "airport_express_fares.csv",
        "mtr_light_rail_fares": mtr_dir / "light_rail_fares.csv",
        "mtr_line_station_patterns": mtr_dir / "mtr_lines_and_stations.csv",
        "mtr_light_rail_stop_patterns": (
            mtr_dir / "light_rail_routes_and_stops.csv"
        ),
        "td_route_fare_revision_date": api_dir / "routes_fares_last_updated.csv",
        "production_transit_schedule": schedule_path,
        "approved_route_inventory": approved_path,
        "ferry_stop_facilities": ferry_stops_path,
    }
    source_manifest = make_source_manifest(source_root, source_paths)

    inventory.drop(columns=["stop_ref_ids_json"]).to_csv(
        output_dir / "transit_schedule_inventory.csv", index=False, encoding="utf-8"
    )
    (
        inventory.groupby(["transport_mode", "operator"], dropna=False, as_index=False)
        .agg(
            transit_lines=("matsim_line_id", "nunique"),
            transit_routes=("matsim_route_id", "nunique"),
            departures=("departure_count", "sum"),
            stop_occurrences=("stop_count", "sum"),
        )
        .sort_values(["transport_mode", "operator"])
        .to_csv(
            output_dir / "transit_schedule_inventory_summary.csv",
            index=False,
            encoding="utf-8",
        )
    )
    normalized.to_parquet(
        output_dir / "official_fares_normalized.parquet",
        index=False,
        compression="zstd",
    )
    full_fares.to_csv(
        output_dir / "official_route_full_fares.csv", index=False, encoding="utf-8"
    )
    route_matches.to_csv(
        output_dir / "route_to_official_fare_match.csv",
        index=False,
        encoding="utf-8",
    )
    direction_patterns.to_csv(
        output_dir / "official_direction_stop_patterns.csv",
        index=False,
        encoding="utf-8",
    )
    source_manifest.to_csv(
        output_dir / "fare_source_manifest.csv", index=False, encoding="utf-8"
    )

    mode_counts = (
        inventory.groupby("transport_mode")["matsim_route_id"].nunique().to_dict()
    )
    mapping_status_counts = route_matches["mapping_status"].value_counts().to_dict()
    mapping_quality_counts = route_matches["mapping_quality"].value_counts().to_dict()
    forward_by_mode = {}
    for mode, group in route_matches.groupby("transport_mode"):
        required_total = int(group["required_forward_pair_count"].sum())
        matched_total = int(group["matched_forward_pair_count"].sum())
        forward_by_mode[mode] = {
            "required_forward_pairs": required_total,
            "matched_forward_pairs": matched_total,
            "weighted_forward_pair_coverage": (
                matched_total / required_total if required_total else 0.0
            ),
        }
    summary = {
        "model": "Hong Kong offline public transport fare model v1",
        "model_role": "route_matching_and_trip_chargeability_audit",
        "created_date": "2026-07-28",
        "source_download_date": SOURCE_DOWNLOAD_DATE,
        "schedule": {
            "transit_lines": int(inventory["matsim_line_id"].nunique()),
            "transit_routes": int(len(inventory)),
            "departures": int(inventory["departure_count"].sum()),
            "routes_by_mode": {key: int(value) for key, value in mode_counts.items()},
        },
        "fares": {
            "normalized_records": int(len(normalized)),
            "route_full_fare_records": int(len(full_fares)),
            "official_direction_patterns": int(len(direction_patterns)),
        },
        "route_matches": {
            "mapping_status": {
                key: int(value) for key, value in mapping_status_counts.items()
            },
            "mapping_quality": {
                key: int(value) for key, value in mapping_quality_counts.items()
            },
            "forward_pair_coverage_by_mode": forward_by_mode,
        },
        "passenger_fare_basis": "adult Octopus",
        "transfer_concessions": "not modelled; retained as separate null/status fields",
        "trip_fare_policy": (
            "cost_hkd remains null unless a production passenger trip contains "
            "a uniquely chargeable itinerary"
        ),
    }
    (output_dir / "pt_fare_model_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    legacy_curve = output_dir / "official_fare_distance_curve.csv"
    if legacy_curve.exists():
        legacy_curve.unlink()
    write_sha256s(output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
