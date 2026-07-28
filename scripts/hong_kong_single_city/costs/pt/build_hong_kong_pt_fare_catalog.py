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
            "download_date": "",
            "download_date_basis": "not applicable",
            "official": False,
        },
    }
    rows: list[dict[str, Any]] = []
    for source_id, path in paths.items():
        details = metadata[source_id]
        rows.append(
            {
                "source_id": source_id,
                **details,
                "local_path": str(path.resolve()),
                "project_relative_path": path.resolve().relative_to(source_root.resolve()).as_posix(),
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


def build_route_matches(
    inventory: pd.DataFrame,
    normalized: pd.DataFrame,
    full_fares: pd.DataFrame,
) -> pd.DataFrame:
    road = normalized[
        normalized["official_route_id"].ne("")
        & normalized["adult_octopus_fare_hkd"].notna()
    ]
    road_stats = (
        road.groupby(["mode", "official_route_id"], as_index=False)
        .agg(
            official_od_fare_records=("adult_octopus_fare_hkd", "size"),
            fare_min_hkd=("adult_octopus_fare_hkd", "min"),
            fare_max_hkd=("adult_octopus_fare_hkd", "max"),
        )
        .set_index(["mode", "official_route_id"])
        .to_dict("index")
    )
    full_stats = (
        full_fares.groupby(
            ["mode", "official_route_id", "official_route_sequence"], as_index=False
        )
        .agg(
            official_full_fare_hkd=("adult_octopus_fare_hkd", "median"),
            route_full_fare_source_records=("adult_octopus_fare_hkd", "size"),
        )
        .set_index(["mode", "official_route_id", "official_route_sequence"])
        .to_dict("index")
    )
    station_fares = {
        mode: set(
            zip(
                normalized.loc[normalized["mode"].eq(mode), "origin_stop_id"].astype(str),
                normalized.loc[
                    normalized["mode"].eq(mode), "destination_stop_id"
                ].astype(str),
            )
        )
        for mode in ("train", "light_rail")
    }
    station_price = {
        mode: normalized[normalized["mode"].eq(mode)]
        .groupby(["origin_stop_id", "destination_stop_id"])[
            "adult_octopus_fare_hkd"
        ]
        .median()
        .to_dict()
        for mode in ("train", "light_rail")
    }

    rows: list[dict[str, Any]] = []
    for record in inventory.to_dict("records"):
        mode = record["transport_mode"]
        route_id = str(record["official_route_id"])
        route_seq = str(record["official_route_sequence"])
        values: dict[str, Any] = {
            "official_od_fare_records": 0,
            "fare_min_hkd": np.nan,
            "fare_max_hkd": np.nan,
            "official_full_fare_hkd": np.nan,
            "route_full_fare_source_records": 0,
        }
        if mode in {"bus", "gmb", "ferry"}:
            values.update(road_stats.get((mode, route_id), {}))
            values.update(full_stats.get((mode, route_id, route_seq), {}))
            if values["official_od_fare_records"] > 0:
                method = "exact_official_route_id_with_stop_od_fares"
                quality = "high_route_match"
            elif values["route_full_fare_source_records"] > 0:
                method = "exact_official_route_id_and_direction_full_fare"
                quality = "medium_route_full_fare_only"
            else:
                method = "exact_route_identifier_but_no_fare_record"
                quality = "unmatched_fare"
        elif mode in {"train", "light_rail"}:
            stops = [item for item in json.loads(record["official_stop_ids_json"]) if item]
            pairs = [(a, b) for a in stops for b in stops if a != b]
            prices = [
                station_price[mode][pair]
                for pair in pairs
                if pair in station_fares[mode]
                and pd.notna(station_price[mode].get(pair))
            ]
            values["official_od_fare_records"] = len(prices)
            values["fare_min_hkd"] = min(prices) if prices else np.nan
            values["fare_max_hkd"] = max(prices) if prices else np.nan
            if prices:
                method = "matsim_station_code_to_official_station_od_matrix"
                quality = "high_station_match"
            else:
                method = "rail_line_identifier_but_no_station_od_fare"
                quality = "unmatched_fare"
        else:
            method = "mode_out_of_scope"
            quality = "out_of_scope"
        rows.append(
            {
                "matsim_line_id": record["matsim_line_id"],
                "matsim_route_id": record["matsim_route_id"],
                "transport_mode": mode,
                "operator": record["operator"],
                "official_route_id": route_id,
                "official_route_sequence": route_seq,
                "official_route_name": (
                    record.get("route_name")
                    or record.get("route_short_name")
                    or record.get("matsim_line_name")
                ),
                "stop_count": record["stop_count"],
                "official_stop_id_coverage": record["official_stop_id_coverage"],
                "fare_match_method": method,
                "fare_match_quality": quality,
                **values,
                "transfer_concession_status": "not_modelled_separate_field",
            }
        )
    return pd.DataFrame(rows)


def build_distance_curve(normalized: pd.DataFrame) -> pd.DataFrame:
    reference = normalized[
        normalized["mode"].isin(["bus", "gmb", "ferry", "train", "light_rail"])
        & normalized["adult_octopus_fare_hkd"].gt(0)
        & normalized["euclidean_distance_m"].notna()
    ].copy()
    reference["distance_bin_lower_m"] = (
        np.floor(reference["euclidean_distance_m"] / 1000) * 1000
    ).astype(int)
    result = (
        reference.groupby(["mode", "distance_bin_lower_m"], as_index=False)
        .agg(
            sample_count=("adult_octopus_fare_hkd", "size"),
            fare_median_hkd=("adult_octopus_fare_hkd", "median"),
            fare_p10_hkd=("adult_octopus_fare_hkd", lambda x: x.quantile(0.10)),
            fare_p90_hkd=("adult_octopus_fare_hkd", lambda x: x.quantile(0.90)),
            fare_min_hkd=("adult_octopus_fare_hkd", "min"),
            fare_max_hkd=("adult_octopus_fare_hkd", "max"),
        )
        .sort_values(["mode", "distance_bin_lower_m"])
    )
    result["distance_bin_upper_m"] = result["distance_bin_lower_m"] + 1000
    result["distance_measure"] = "straight_line_od_distance"
    result["fare_measure"] = "adult_octopus"
    return result[
        [
            "mode",
            "distance_bin_lower_m",
            "distance_bin_upper_m",
            "sample_count",
            "fare_median_hkd",
            "fare_p10_hkd",
            "fare_p90_hkd",
            "fare_min_hkd",
            "fare_max_hkd",
            "distance_measure",
            "fare_measure",
        ]
    ]


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
    route_matches = build_route_matches(inventory, normalized, full_fares)
    distance_curve = build_distance_curve(normalized)

    source_paths = {
        "td_gtfs": gtfs_path,
        "td_bus_route_fares": api_dir / "bus_route_stop_points.json",
        "td_gmb_route_fares": api_dir / "gmb_route_stop_points.json",
        "td_ferry_route_fares": api_dir / "ferry_route_stop_points.json",
        "mtr_domestic_fares": mtr_dir / "mtr_lines_fares.csv",
        "mtr_airport_express_fares": mtr_dir / "airport_express_fares.csv",
        "mtr_light_rail_fares": mtr_dir / "light_rail_fares.csv",
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
    distance_curve.to_csv(
        output_dir / "official_fare_distance_curve.csv",
        index=False,
        encoding="utf-8",
    )
    source_manifest.to_csv(
        output_dir / "fare_source_manifest.csv", index=False, encoding="utf-8"
    )

    mode_counts = (
        inventory.groupby("transport_mode")["matsim_route_id"].nunique().to_dict()
    )
    match_counts = route_matches["fare_match_quality"].value_counts().to_dict()
    summary = {
        "model": "Hong Kong offline public transport fare model v1",
        "created_date": "2026-07-28",
        "model_effective_date": MODEL_EFFECTIVE_DATE,
        "source_download_date": SOURCE_DOWNLOAD_DATE,
        "source_project_root": str(source_root),
        "output_directory": str(output_dir),
        "schedule": {
            "transit_lines": int(inventory["matsim_line_id"].nunique()),
            "transit_routes": int(len(inventory)),
            "departures": int(inventory["departure_count"].sum()),
            "routes_by_mode": {key: int(value) for key, value in mode_counts.items()},
        },
        "fares": {
            "normalized_records": int(len(normalized)),
            "route_full_fare_records": int(len(full_fares)),
            "distance_curve_records": int(len(distance_curve)),
        },
        "route_matches": {key: int(value) for key, value in match_counts.items()},
        "passenger_fare_basis": "adult Octopus",
        "transfer_concessions": "not modelled; retained as separate null/status fields",
        "prohibited_matsim_inputs_modified": False,
    }
    (output_dir / "pt_fare_model_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_sha256s(output_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
