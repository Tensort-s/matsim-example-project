from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import Point


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OSM_DIR = PROJECT_ROOT / "data" / "osm" / "fuzhou_city_23"
BOUNDARY_PATH = OSM_DIR / "fuzhou_city_23_boundary.geojson"
OUTPUT_RAW = OSM_DIR / "raw_overpass_poi_nodes_bbox.json"
OUTPUT_GEOJSON = OSM_DIR / "fuzhou_city_23_osm_poi_nodes.geojson"
OUTPUT_WORK_GEOJSON = OSM_DIR / "fuzhou_city_23_osm_work_poi_nodes.geojson"

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
]

POI_KEYS = [
    "amenity",
    "shop",
    "office",
    "tourism",
    "leisure",
    "healthcare",
    "craft",
    "industrial",
    "public_transport",
]

WORK_RELATED_AMENITIES = {
    "school",
    "university",
    "college",
    "hospital",
    "clinic",
    "doctors",
    "bank",
    "restaurant",
    "cafe",
    "fast_food",
    "marketplace",
    "police",
    "fire_station",
    "post_office",
    "courthouse",
    "townhall",
    "library",
    "theatre",
    "cinema",
}


def load_boundary() -> gpd.GeoDataFrame:
    boundary = gpd.read_file(BOUNDARY_PATH).to_crs("EPSG:4326")
    if len(boundary) != 1:
        raise RuntimeError(f"Expected one boundary feature in {BOUNDARY_PATH}, got {len(boundary)}")
    return boundary


def build_query(bounds: tuple[float, float, float, float]) -> str:
    west, south, east, north = bounds
    bbox = f"{south:.6f},{west:.6f},{north:.6f},{east:.6f}"
    clauses = "\n".join(f'  node["{key}"]({bbox});' for key in POI_KEYS)
    clauses += f'\n  node["railway"~"station|halt|tram_stop|subway_entrance"]({bbox});'
    return f"""
    [out:json][timeout:120];
    (
    {clauses}
    );
    out tags;
    """


def query_overpass(query: str) -> dict[str, Any]:
    if OUTPUT_RAW.exists() and OUTPUT_RAW.stat().st_size > 0:
        return json.loads(OUTPUT_RAW.read_text(encoding="utf-8"))

    last_error: Exception | None = None
    for url in OVERPASS_URLS:
        try:
            response = requests.post(url, data={"data": query}, timeout=180)
            response.raise_for_status()
            payload = response.json()
            OUTPUT_RAW.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            return payload
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(5)
    raise RuntimeError(f"All Overpass endpoints failed: {last_error}")


def elements_to_points(payload: dict[str, Any]) -> gpd.GeoDataFrame:
    rows = []
    for element in payload.get("elements", []):
        if element.get("type") != "node":
            continue
        tags = dict(element.get("tags", {}))
        rows.append(
            {
                "osm_id": element.get("id"),
                **tags,
                "geometry": Point(float(element["lon"]), float(element["lat"])),
            }
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def main() -> None:
    OSM_DIR.mkdir(parents=True, exist_ok=True)
    boundary = load_boundary()
    geom = boundary.iloc[0].geometry
    query = build_query(geom.bounds)
    payload = query_overpass(query)
    pois = elements_to_points(payload)

    if pois.empty:
        clipped = pois
    else:
        clipped = gpd.sjoin(pois, boundary[["geometry"]], predicate="within", how="inner").drop(columns=["index_right"])

    work_mask = pd.Series(False, index=clipped.index)
    for column in ["office", "shop", "industrial", "craft", "healthcare"]:
        if column in clipped.columns:
            work_mask = work_mask | clipped[column].notna()
    if "amenity" in clipped.columns:
        work_mask = work_mask | clipped["amenity"].isin(WORK_RELATED_AMENITIES)
    work_pois = clipped.loc[work_mask].copy()

    clipped.to_file(OUTPUT_GEOJSON, driver="GeoJSON")
    work_pois.to_file(OUTPUT_WORK_GEOJSON, driver="GeoJSON")

    summary = {
        "raw_elements": len(payload.get("elements", [])),
        "poi_nodes_inside_boundary": len(clipped),
        "work_poi_nodes_inside_boundary": len(work_pois),
        "output": str(OUTPUT_GEOJSON),
        "work_output": str(OUTPUT_WORK_GEOJSON),
    }
    (OSM_DIR / "poi_download_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
