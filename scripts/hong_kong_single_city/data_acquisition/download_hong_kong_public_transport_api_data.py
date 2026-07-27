#!/usr/bin/env python3
"""Download official Hong Kong public-transport API supplements.

The existing Transport Department GTFS and route/fare MDB files provide stop
sequences and headway-based service definitions, but they do not include route
shapes. This downloader adds official CSDI bus/GMB polylines, operator static
snapshots, detailed GMB headways, and timestamped MTR/Light Rail next-train
snapshots. Real-time snapshots are calibration observations, not timetables.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import os
import shutil
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode

import requests


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CATALOG = Path(r"D:\Program Files\hk_public_transport_api_catalog.csv")
DEFAULT_DATA_ROOT = ROOT / "data"
DEFAULT_OUTPUT = Path("transit/hongkong/API_Supplements")

CSDI_LAYERS = {
    "franchised_bus_routes": {
        "dataset_id": "td_rcd_1638844988873_41214",
        "layer_id": 0,
        "expected_layer": "FB_ROUTE_LINE",
    },
    "green_minibus_routes": {
        "dataset_id": "td_rcd_1697082463580_57453",
        "layer_id": 0,
        "expected_layer": "GMB_ROUTE_LINE",
    },
}

ROUTE_POINT_FILES = {
    "bus_route_stop_points": "https://static.data.gov.hk/td/routes-fares-geojson/JSON_BUS.json",
    "gmb_route_stop_points": "https://static.data.gov.hk/td/routes-fares-geojson/JSON_GMB.json",
    "ferry_route_stop_points": "https://static.data.gov.hk/td/routes-fares-geojson/JSON_FERRY.json",
    "peak_tram_route_stop_points": "https://static.data.gov.hk/td/routes-fares-geojson/JSON_PTRAM.json",
    "tram_route_stop_points": "https://static.data.gov.hk/td/routes-fares-geojson/JSON_TRAM.json",
    "routes_fares_last_updated": "https://static.data.gov.hk/td/routes-fares-geojson/DATA_LAST_UPDATED_DATE.csv",
}

OPERATOR_STATIC_FILES = {
    "kmb_routes": "https://data.etabus.gov.hk/v1/transport/kmb/route/",
    "kmb_stops": "https://data.etabus.gov.hk/v1/transport/kmb/stop",
    "kmb_route_stops": "https://data.etabus.gov.hk/v1/transport/kmb/route-stop",
    "citybus_routes": "https://rt.data.gov.hk/v2/transport/citybus/route/CTB",
    "nlb_routes": "https://rt.data.gov.hk/v2/transport/nlb/route.php?action=list",
    "gmb_routes": "https://data.etagmb.gov.hk/route/",
}

GTFS_URL = "https://static.data.gov.hk/td/pt-headway-en/gtfs.zip"
MTR_NEXT_TRAIN_URL = "https://rt.data.gov.hk/v1/transport/mtr/getSchedule.php"
LRT_NEXT_TRAIN_URL = "https://rt.data.gov.hk/v1/transport/mtr/lrt/getSchedule"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--insecure", action="store_true", help="Disable TLS verification only if required locally.")
    parser.add_argument("--skip-gtfs", action="store_true")
    parser.add_argument("--skip-route-point-files", action="store_true")
    parser.add_argument("--skip-gmb-details", action="store_true")
    parser.add_argument("--skip-realtime", action="store_true")
    parser.add_argument(
        "--realtime-only",
        action="store_true",
        help="Append a new MTR/Light Rail snapshot and preserve existing static files and manifest.",
    )
    parser.add_argument(
        "--qa-only",
        action="store_true",
        help="Rebuild route-geometry coverage QA from existing downloaded files without network access.",
    )
    return parser.parse_args()


class Downloader:
    def __init__(self, timeout: float, retries: int, verify: bool) -> None:
        self.timeout = timeout
        self.retries = retries
        self.verify = verify
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "matsim-hong-kong-research/1.0"})

    def get(self, url: str, *, params: dict[str, Any] | None = None) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=self.timeout,
                    verify=self.verify,
                )
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(min(2**attempt, 8))
        raise RuntimeError(f"Failed after {self.retries} attempts: {url}: {last_error}")

    def json(self, url: str, *, params: dict[str, Any] | None = None) -> Any:
        return self.get(url, params=params).json()

    def file(self, url: str, target: Path) -> dict[str, Any]:
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(target.suffix + ".part")
        response = self.get(url)
        with partial.open("wb") as handle:
            handle.write(response.content)
        partial.replace(target)
        return {
            "url": response.url,
            "http_last_modified": response.headers.get("Last-Modified"),
            "http_etag": response.headers.get("ETag"),
        }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def replace_with_retry(source: Path, target: Path, attempts: int = 20) -> None:
    """Replace a file despite short-lived Windows indexer/antivirus locks."""
    last_error: OSError | None = None
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.5 + attempt * 0.1)
    raise RuntimeError(f"Could not replace {target} with {source}: {last_error}")


def add_manifest_entry(
    manifest: list[dict[str, Any]],
    output_root: Path,
    path: Path,
    *,
    role: str,
    source_url: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    row = {
        "relative_path": path.relative_to(output_root).as_posix(),
        "role": role,
        "source_url": source_url,
        "downloaded_at_utc": utc_now(),
        "size_bytes": path.stat().st_size,
        "sha256": sha256(path),
    }
    row.update(metadata or {})
    manifest.append(row)


def inspect_feature_collection(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    features = payload.get("features", [])
    geometry_types = Counter(
        (feature.get("geometry") or {}).get("type", "null") for feature in features
    )
    route_patterns: set[tuple[str, str]] = set()
    for feature in features:
        props = feature.get("properties") or {}
        route_id = props.get("routeId", props.get("ROUTE_ID"))
        route_seq = props.get("routeSeq", props.get("ROUTE_SEQ"))
        if route_id is not None and route_seq is not None:
            route_patterns.add((str(route_id), str(route_seq)))
    return {
        "feature_count": len(features),
        "geometry_types": dict(sorted(geometry_types.items())),
        "route_pattern_count": len(route_patterns),
    }


def download_csdi_layer(
    downloader: Downloader,
    name: str,
    spec: dict[str, Any],
    output_root: Path,
    manifest: list[dict[str, Any]],
) -> dict[str, Any]:
    service = (
        "https://portal.csdi.gov.hk/server/rest/services/common/"
        f"{spec['dataset_id']}/FeatureServer"
    )
    layer_url = f"{service}/{spec['layer_id']}"
    metadata = downloader.json(layer_url, params={"f": "pjson"})
    if metadata.get("name") != spec["expected_layer"]:
        raise ValueError(f"Unexpected CSDI layer for {name}: {metadata.get('name')}")
    if metadata.get("geometryType") != "esriGeometryPolyline":
        raise ValueError(f"CSDI layer {name} is not a polyline layer")

    count_payload = downloader.json(
        f"{layer_url}/query",
        params={"where": "1=1", "returnCountOnly": "true", "f": "json"},
    )
    expected_count = int(count_payload["count"])
    path = output_root / "geometry" / f"{name}.geojson"
    path.parent.mkdir(parents=True, exist_ok=True)
    # Include the PID so an interrupted parent shell cannot leave an orphaned
    # child writing into a later run's temporary file.
    partial = path.with_name(path.name + f".part.{os.getpid()}")
    for candidate in (path,):
        if not candidate.exists():
            continue
        existing_qa = inspect_feature_collection(candidate)
        valid_types = not (
            set(existing_qa["geometry_types"]) - {"LineString", "MultiLineString"}
        )
        if existing_qa["feature_count"] == expected_count and valid_types:
            add_manifest_entry(
                manifest,
                output_root,
                path,
                role="actual_route_geometry",
                source_url=f"{layer_url}/query (paginated ArcGIS REST query; reused complete file)",
            )
            existing_qa.update(
                {
                    "dataset_id": spec["dataset_id"],
                    "layer": metadata.get("name"),
                    "crs": "EPSG:4326",
                    "max_allowable_offset_degrees": 0.00001,
                    "approximate_simplification_metres": 1.1,
                    "coordinate_decimal_places": 6,
                    "path": path.relative_to(output_root).as_posix(),
                    "reused_complete_download": True,
                }
            )
            print(f"Reused complete CSDI geometry: {name}", flush=True)
            return existing_qa
    geometry_types: Counter[str] = Counter()
    route_patterns: set[tuple[str, str]] = set()
    feature_count = 0
    # The full CSDI bus GeoJSON is about 1.55 GB because road vertices are
    # extremely dense. A roughly one-metre simplification preserves road-level
    # map-matching accuracy while making the research snapshot manageable.
    page_size = 250
    max_allowable_offset_degrees = 0.00001
    first_feature = True
    with partial.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write('{"type":"FeatureCollection","name":')
        handle.write(json.dumps(spec["expected_layer"]))
        handle.write(',"features":[\n')
        for offset in range(0, expected_count, page_size):
            query = {
                "where": "1=1",
                "outFields": "*",
                "returnGeometry": "true",
                "outSR": "4326",
                "orderByFields": "OBJECTID ASC",
                "resultOffset": offset,
                "resultRecordCount": page_size,
                "maxAllowableOffset": max_allowable_offset_degrees,
                "geometryPrecision": 6,
                "f": "geojson",
            }
            page = downloader.json(f"{layer_url}/query", params=query)
            features = page.get("features") or []
            if not features:
                raise ValueError(f"Empty CSDI page for {name} at offset {offset}")
            for feature in features:
                if not first_feature:
                    handle.write(",\n")
                handle.write(json.dumps(feature, ensure_ascii=False, separators=(",", ":")))
                first_feature = False
                feature_count += 1
                geometry_types[(feature.get("geometry") or {}).get("type", "null")] += 1
                props = feature.get("properties") or {}
                route_id = props.get("ROUTE_ID")
                route_seq = props.get("ROUTE_SEQ")
                if route_id is not None and route_seq is not None:
                    route_patterns.add((str(route_id), str(route_seq)))
            print(
                f"CSDI {name}: {feature_count}/{expected_count}",
                flush=True,
            )
        handle.write("\n]}\n")
    replace_with_retry(partial, path)
    qa = {
        "feature_count": feature_count,
        "geometry_types": dict(sorted(geometry_types.items())),
        "route_pattern_count": len(route_patterns),
    }
    if feature_count != expected_count:
        raise ValueError(
            f"Incomplete CSDI download for {name}: {feature_count} != {expected_count}"
        )
    if set(qa["geometry_types"]) - {"LineString", "MultiLineString"}:
        raise ValueError(f"Unexpected geometry in {name}: {qa['geometry_types']}")
    add_manifest_entry(
        manifest,
        output_root,
        path,
        role="actual_route_geometry",
        source_url=f"{layer_url}/query (paginated ArcGIS REST query)",
    )
    qa.update(
        {
            "dataset_id": spec["dataset_id"],
            "layer": metadata.get("name"),
            "crs": "EPSG:4326",
            "max_allowable_offset_degrees": max_allowable_offset_degrees,
            "approximate_simplification_metres": 1.1,
            "coordinate_decimal_places": 6,
            "path": path.relative_to(output_root).as_posix(),
        }
    )
    return qa


def download_json_file(
    downloader: Downloader,
    name: str,
    url: str,
    directory: Path,
    output_root: Path,
    manifest: list[dict[str, Any]],
) -> tuple[Path, Any]:
    path = directory / f"{name}.json"
    meta = downloader.file(url, path)
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    add_manifest_entry(
        manifest,
        output_root,
        path,
        role="operator_static_snapshot",
        source_url=url,
        metadata=meta,
    )
    return path, payload


def gmb_route_keys(route_listing: dict[str, Any]) -> list[tuple[str, str]]:
    routes = route_listing.get("data", {}).get("routes", {})
    return sorted(
        (region, str(route_code))
        for region, route_codes in routes.items()
        for route_code in route_codes
    )


def collect_gmb_details(
    downloader: Downloader,
    route_listing: dict[str, Any],
    output_root: Path,
    workers: int,
    manifest: list[dict[str, Any]],
) -> dict[str, Any]:
    keys = gmb_route_keys(route_listing)
    responses: dict[tuple[str, str], dict[str, Any]] = {}

    def fetch(key: tuple[str, str]) -> tuple[tuple[str, str], dict[str, Any]]:
        region, route_code = key
        url = f"https://data.etagmb.gov.hk/route/{region}/{route_code}"
        return key, downloader.json(url)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = [executor.submit(fetch, key) for key in keys]
        for index, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            key, payload = future.result()
            responses[key] = payload
            if index % 100 == 0 or index == len(keys):
                print(f"GMB route details: {index}/{len(keys)}", flush=True)

    raw_path = output_root / "static" / "operator" / "gmb_route_details.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    headway_path = output_root / "normalized" / "gmb_headways.csv"
    headway_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "region",
        "route_code",
        "route_id",
        "description_en",
        "route_seq",
        "origin_en",
        "destination_en",
        "headway_seq",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "public_holiday",
        "start_time",
        "end_time",
        "frequency_min_minutes",
        "frequency_max_minutes",
        "data_timestamp",
    ]
    records = 0
    variants = 0
    directions = 0
    with raw_path.open("w", encoding="utf-8", newline="\n") as raw_handle, headway_path.open(
        "w", encoding="utf-8-sig", newline=""
    ) as csv_handle:
        writer = csv.DictWriter(csv_handle, fieldnames=fieldnames)
        writer.writeheader()
        for region, route_code in keys:
            payload = responses[(region, route_code)]
            raw_handle.write(
                json.dumps(
                    {"region": region, "route_code": route_code, "response": payload},
                    ensure_ascii=False,
                )
                + "\n"
            )
            for variant in payload.get("data") or []:
                variants += 1
                for direction in variant.get("directions") or []:
                    directions += 1
                    for headway in direction.get("headways") or []:
                        weekdays = list(headway.get("weekdays") or []) + [False] * 7
                        writer.writerow(
                            {
                                "region": region,
                                "route_code": route_code,
                                "route_id": variant.get("route_id"),
                                "description_en": variant.get("description_en"),
                                "route_seq": direction.get("route_seq"),
                                "origin_en": direction.get("orig_en"),
                                "destination_en": direction.get("dest_en"),
                                "headway_seq": headway.get("headway_seq"),
                                "monday": weekdays[0],
                                "tuesday": weekdays[1],
                                "wednesday": weekdays[2],
                                "thursday": weekdays[3],
                                "friday": weekdays[4],
                                "saturday": weekdays[5],
                                "sunday": weekdays[6],
                                "public_holiday": headway.get("public_holiday"),
                                "start_time": headway.get("start_time"),
                                "end_time": headway.get("end_time"),
                                "frequency_min_minutes": headway.get("frequency"),
                                "frequency_max_minutes": headway.get("frequency_upper"),
                                "data_timestamp": direction.get("data_timestamp"),
                            }
                        )
                        records += 1

    source = "https://data.etagmb.gov.hk/route/{region}/{route_code}"
    add_manifest_entry(
        manifest,
        output_root,
        raw_path,
        role="gmb_static_route_detail_responses",
        source_url=source,
    )
    add_manifest_entry(
        manifest,
        output_root,
        headway_path,
        role="matsim_headway_input",
        source_url=source,
    )
    return {
        "route_codes_requested": len(keys),
        "route_variants": variants,
        "directions": directions,
        "headway_records": records,
        "headways_path": headway_path.relative_to(output_root).as_posix(),
    }


def read_unique_pairs(path: Path, first: str, second: str) -> list[tuple[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        pairs = {
            (row[first].strip(), row[second].strip())
            for row in csv.DictReader(handle)
            if row.get(first, "").strip() and row.get(second, "").strip()
        }
        return sorted(pairs)


def read_unique_values(path: Path, field: str) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        values = {
            row[field].strip()
            for row in csv.DictReader(handle)
            if row.get(field, "").strip()
        }
        return sorted(values, key=lambda value: int(value))


def write_realtime_jsonl(
    path: Path,
    requests_and_responses: Iterable[tuple[dict[str, str], str, Any]],
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for request_parameters, url, response in requests_and_responses:
            handle.write(
                json.dumps(
                    {
                        "captured_at_utc": utc_now(),
                        "request_parameters": request_parameters,
                        "request_url": url,
                        "response": response,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            count += 1
    return count


def collect_realtime_snapshots(
    downloader: Downloader,
    transit_root: Path,
    output_root: Path,
    workers: int,
    manifest: list[dict[str, Any]],
) -> dict[str, Any]:
    mtr_source = transit_root / "MTR" / "mtr_lines_and_stations.csv"
    lrt_source = transit_root / "MTR" / "light_rail_routes_and_stops.csv"
    if not mtr_source.exists() or not lrt_source.exists():
        raise FileNotFoundError("MTR route/station reference CSV files are required for real-time snapshots")

    mtr_pairs = read_unique_pairs(mtr_source, "Line Code", "Station Code")
    lrt_stops = read_unique_values(lrt_source, "Stop ID")

    def fetch_mtr(pair: tuple[str, str]) -> tuple[dict[str, str], str, Any]:
        line, station = pair
        params = {"line": line, "sta": station}
        response = downloader.get(MTR_NEXT_TRAIN_URL, params=params)
        return params, response.url, response.json()

    def fetch_lrt(stop_id: str) -> tuple[dict[str, str], str, Any]:
        params = {"station_id": stop_id}
        response = downloader.get(LRT_NEXT_TRAIN_URL, params=params)
        return params, response.url, response.json()

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(workers, 4))) as executor:
        mtr_results = list(executor.map(fetch_mtr, mtr_pairs))
        lrt_results = list(executor.map(fetch_lrt, lrt_stops))

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot_dir = output_root / "realtime_snapshots" / stamp
    mtr_path = snapshot_dir / "mtr_next_train.jsonl"
    lrt_path = snapshot_dir / "light_rail_next_train.jsonl"
    mtr_count = write_realtime_jsonl(mtr_path, mtr_results)
    lrt_count = write_realtime_jsonl(lrt_path, lrt_results)
    add_manifest_entry(
        manifest,
        output_root,
        mtr_path,
        role="realtime_calibration_snapshot_not_timetable",
        source_url=MTR_NEXT_TRAIN_URL,
    )
    add_manifest_entry(
        manifest,
        output_root,
        lrt_path,
        role="realtime_calibration_snapshot_not_timetable",
        source_url=LRT_NEXT_TRAIN_URL,
    )
    return {
        "snapshot_timestamp": stamp,
        "mtr_line_station_requests": mtr_count,
        "light_rail_station_requests": lrt_count,
        "mtr_success_responses": sum(int(item[2].get("status") == 1) for item in mtr_results),
        "light_rail_success_responses": sum(int(item[2].get("status") == 1) for item in lrt_results),
    }


def build_geometry_coverage_qa(
    output_root: Path,
    manifest: list[dict[str, Any]],
) -> dict[str, Any]:
    inputs = {
        "bus": (
            output_root / "static/routes_fares_route_stop_points/bus_route_stop_points.json",
            output_root / "geometry/franchised_bus_routes.geojson",
        ),
        "gmb": (
            output_root / "static/routes_fares_route_stop_points/gmb_route_stop_points.json",
            output_root / "geometry/green_minibus_routes.geojson",
        ),
    }
    rows: list[dict[str, Any]] = []
    stats: dict[str, Any] = {}
    for mode, (point_path, geometry_path) in inputs.items():
        points = json.loads(point_path.read_text(encoding="utf-8-sig")).get("features", [])
        geometries = json.loads(geometry_path.read_text(encoding="utf-8-sig")).get("features", [])
        point_patterns: dict[tuple[str, str], dict[str, Any]] = {}
        for feature in points:
            props = feature.get("properties") or {}
            key = (str(props.get("routeId")), str(props.get("routeSeq")))
            record = point_patterns.setdefault(
                key,
                {
                    "company_code": props.get("companyCode"),
                    "route_name": props.get("routeNameE"),
                    "route_stop_point_count": 0,
                },
            )
            record["route_stop_point_count"] += 1
        geometry_patterns = {
            (str((feature.get("properties") or {}).get("ROUTE_ID")),
             str((feature.get("properties") or {}).get("ROUTE_SEQ")))
            for feature in geometries
        }
        all_patterns = sorted(set(point_patterns) | geometry_patterns)
        for route_id, route_seq in all_patterns:
            metadata = point_patterns.get((route_id, route_seq), {})
            rows.append(
                {
                    "mode": mode,
                    "route_id": route_id,
                    "route_seq": route_seq,
                    "company_code": metadata.get("company_code"),
                    "route_name": metadata.get("route_name"),
                    "route_stop_point_count": metadata.get("route_stop_point_count", 0),
                    "has_route_stop_pattern": (route_id, route_seq) in point_patterns,
                    "has_csdi_geometry": (route_id, route_seq) in geometry_patterns,
                }
            )
        matched = len(set(point_patterns) & geometry_patterns)
        stats[mode] = {
            "route_stop_patterns": len(point_patterns),
            "csdi_geometry_patterns": len(geometry_patterns),
            "matched_patterns": matched,
            "route_stop_patterns_missing_geometry": len(set(point_patterns) - geometry_patterns),
            "geometry_patterns_missing_route_stop_data": len(geometry_patterns - set(point_patterns)),
            "route_stop_pattern_geometry_coverage_percent": (
                100.0 * matched / len(point_patterns) if point_patterns else 0.0
            ),
        }

    path = output_root / "normalized" / "route_geometry_coverage.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "mode",
        "route_id",
        "route_seq",
        "company_code",
        "route_name",
        "route_stop_point_count",
        "has_route_stop_pattern",
        "has_csdi_geometry",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    manifest[:] = [
        row for row in manifest if row.get("relative_path") != "normalized/route_geometry_coverage.csv"
    ]
    add_manifest_entry(
        manifest,
        output_root,
        path,
        role="route_geometry_coverage_audit",
        source_url="generated from CSDI geometry and routes-fares route-stop points",
    )
    stats["path"] = path.relative_to(output_root).as_posix()
    return stats


def write_manifest(output_root: Path, manifest: list[dict[str, Any]]) -> None:
    for row in manifest:
        file_path = output_root / row["relative_path"]
        if not file_path.exists():
            raise FileNotFoundError(f"Manifest file is missing: {file_path}")
        row["size_bytes"] = file_path.stat().st_size
        row["sha256"] = sha256(file_path)
    path = output_root / "metadata" / "download_manifest.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "relative_path",
        "role",
        "source_url",
        "downloaded_at_utc",
        "size_bytes",
        "sha256",
        "http_last_modified",
        "http_etag",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(sorted(manifest, key=lambda row: row["relative_path"]))


def load_manifest(output_root: Path) -> list[dict[str, Any]]:
    path = output_root / "metadata" / "download_manifest.csv"
    if not path.exists():
        raise FileNotFoundError(f"Existing manifest required for --realtime-only: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [
            row
            for row in csv.DictReader(handle)
            if row.get("relative_path") != "metadata/api_supplement_summary.json"
        ]


def main() -> None:
    args = parse_args()
    data_root = args.data_root.resolve()
    output_root = args.output if args.output.is_absolute() else data_root / args.output
    output_root = output_root.resolve()
    transit_root = data_root / "transit" / "hongkong"
    output_root.mkdir(parents=True, exist_ok=True)
    if not args.catalog.exists():
        raise FileNotFoundError(f"API catalog not found: {args.catalog}")

    downloader = Downloader(args.timeout, args.retries, verify=not args.insecure)
    manifest: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "generated_at_utc": utc_now(),
        "data_root": str(data_root),
        "output_root": str(output_root),
        "catalog_source": str(args.catalog.resolve()),
        "notes": [
            "CSDI bus and GMB layers are actual official route polylines.",
            "Routes-and-fares JSON feature collections are route-stop Points, not route polylines.",
            "MTR and Light Rail next-train files are one-time calibration snapshots, not full timetables.",
        ],
    }

    if args.realtime_only:
        summary_path = output_root / "metadata" / "api_supplement_summary.json"
        if not summary_path.exists():
            raise FileNotFoundError(
                f"Existing summary required for --realtime-only: {summary_path}"
            )
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["generated_at_utc"] = utc_now()
        manifest = load_manifest(output_root)
        summary["realtime_snapshots"] = collect_realtime_snapshots(
            downloader, transit_root, output_root, args.workers, manifest
        )
        summary["manifest_file_count"] = len(manifest) + 1
        write_json(summary_path, summary)
        add_manifest_entry(
            manifest,
            output_root,
            summary_path,
            role="qa_summary",
            source_url="generated",
        )
        write_manifest(output_root, manifest)
        print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
        return

    if args.qa_only:
        summary_path = output_root / "metadata" / "api_supplement_summary.json"
        if not summary_path.exists():
            raise FileNotFoundError(f"Existing summary required for --qa-only: {summary_path}")
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["generated_at_utc"] = utc_now()
        manifest = load_manifest(output_root)
        summary["route_geometry_coverage"] = build_geometry_coverage_qa(
            output_root, manifest
        )
        summary["manifest_file_count"] = len(manifest) + 1
        write_json(summary_path, summary)
        add_manifest_entry(
            manifest,
            output_root,
            summary_path,
            role="qa_summary",
            source_url="generated",
        )
        write_manifest(output_root, manifest)
        print(json.dumps(summary["route_geometry_coverage"], ensure_ascii=False, indent=2))
        return

    catalog_copy = output_root / "metadata" / "hk_public_transport_api_catalog.csv"
    catalog_copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.catalog, catalog_copy)
    add_manifest_entry(
        manifest,
        output_root,
        catalog_copy,
        role="user_supplied_api_catalog",
        source_url=str(args.catalog.resolve()),
    )

    if not args.skip_gtfs:
        gtfs_path = output_root / "static" / "headway_gtfs" / "gtfs.zip"
        gtfs_meta = downloader.file(GTFS_URL, gtfs_path)
        add_manifest_entry(
            manifest,
            output_root,
            gtfs_path,
            role="headway_gtfs_snapshot",
            source_url=GTFS_URL,
            metadata=gtfs_meta,
        )

    geometry_qa: dict[str, Any] = {}
    for name, spec in CSDI_LAYERS.items():
        print(f"Downloading CSDI geometry: {name}", flush=True)
        geometry_qa[name] = download_csdi_layer(
            downloader, name, spec, output_root, manifest
        )
    summary["geometry"] = geometry_qa

    if not args.skip_route_point_files:
        point_qa: dict[str, Any] = {}
        point_dir = output_root / "static" / "routes_fares_route_stop_points"
        for name, url in ROUTE_POINT_FILES.items():
            suffix = ".csv" if url.lower().endswith(".csv") else ".json"
            path = point_dir / f"{name}{suffix}"
            print(f"Downloading route/fare snapshot: {path.name}", flush=True)
            meta = downloader.file(url, path)
            add_manifest_entry(
                manifest,
                output_root,
                path,
                role="route_stop_points_not_route_geometry",
                source_url=url,
                metadata=meta,
            )
            if suffix == ".json":
                point_qa[name] = inspect_feature_collection(path)
        summary["route_stop_point_files"] = point_qa

    operator_payloads: dict[str, Any] = {}
    operator_dir = output_root / "static" / "operator"
    for name, url in OPERATOR_STATIC_FILES.items():
        print(f"Downloading operator snapshot: {name}", flush=True)
        _, payload = download_json_file(
            downloader, name, url, operator_dir, output_root, manifest
        )
        operator_payloads[name] = payload
    summary["operator_static_snapshots"] = sorted(operator_payloads)

    if not args.skip_gmb_details:
        summary["gmb_headways"] = collect_gmb_details(
            downloader,
            operator_payloads["gmb_routes"],
            output_root,
            args.workers,
            manifest,
        )

    if not args.skip_realtime:
        summary["realtime_snapshots"] = collect_realtime_snapshots(
            downloader, transit_root, output_root, args.workers, manifest
        )

    if not args.skip_route_point_files:
        summary["route_geometry_coverage"] = build_geometry_coverage_qa(
            output_root, manifest
        )

    summary["remaining_matsim_gaps"] = [
        "MTR and Light Rail station coordinates and track polylines",
        "complete rail and non-GMB scheduled departures rather than headway/ETA observations",
        "stop-to-stop running times for services represented only by headways",
        "transfer pathways and minimum transfer times",
        "vehicle type, capacity, fleet and block/interlining assignments",
        "validated map matching from bus/GMB route polylines to directed road-network links",
    ]
    summary["manifest_file_count"] = len(manifest) + 1
    summary_path = output_root / "metadata" / "api_supplement_summary.json"
    write_json(summary_path, summary)
    add_manifest_entry(
        manifest,
        output_root,
        summary_path,
        role="qa_summary",
        source_url="generated",
    )
    write_manifest(output_root, manifest)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
