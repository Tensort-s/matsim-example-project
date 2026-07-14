from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import geopandas as gpd
import requests
from shapely.geometry import LineString, Point, Polygon, mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BOUNDARY_PATH = Path(
    r"F:\GreenspaceExposureMeasurement\resources_by_function\raw\boundaries"
    r"\uban_boundary\urban_boundary_selected\urban_boundary_merge.shp"
)
CITY_ID = 23
OUTPUT_DIR = PROJECT_ROOT / "data" / "osm" / "fuzhou_city_23"
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
]


def load_city_boundary() -> gpd.GeoDataFrame:
    gdf = gpd.read_file(BOUNDARY_PATH)
    city = gdf[gdf["ORIG_FID"] == CITY_ID].copy()
    if city.empty:
        raise RuntimeError(f"Could not find ORIG_FID={CITY_ID} in {BOUNDARY_PATH}")
    return city.to_crs("EPSG:4326")


def overpass_polygon_string(geometry) -> str:
    polygon = geometry
    if polygon.geom_type == "MultiPolygon":
        polygon = max(polygon.geoms, key=lambda geom: geom.area)
    if polygon.geom_type != "Polygon":
        raise RuntimeError(f"Unsupported boundary geometry: {polygon.geom_type}")

    coords = list(polygon.exterior.coords)
    # Overpass poly expects "lat lon lat lon ..."; keep precision modest to avoid huge queries.
    return " ".join(f"{lat:.6f} {lon:.6f}" for lon, lat in coords)


def query_overpass(query: str, output_path: Path) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists() and output_path.stat().st_size > 0:
        return json.loads(output_path.read_text(encoding="utf-8"))

    last_error: Exception | None = None
    for url in OVERPASS_URLS:
        try:
            response = requests.post(url, data={"data": query}, timeout=240)
            response.raise_for_status()
            payload = response.json()
            output_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            return payload
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(5)

    raise RuntimeError(f"All Overpass endpoints failed: {last_error}")


def element_tags(element: dict[str, Any]) -> dict[str, Any]:
    tags = dict(element.get("tags", {}))
    tags["osm_type"] = element.get("type")
    tags["osm_id"] = element.get("id")
    return tags


def point_from_element(element: dict[str, Any]) -> Point | None:
    if "lat" in element and "lon" in element:
        return Point(float(element["lon"]), float(element["lat"]))
    center = element.get("center")
    if center and "lat" in center and "lon" in center:
        return Point(float(center["lon"]), float(center["lat"]))
    return None


def line_from_way(element: dict[str, Any]) -> LineString | None:
    geometry = element.get("geometry")
    if not geometry:
        return None
    coords = [(float(item["lon"]), float(item["lat"])) for item in geometry]
    if len(coords) < 2:
        return None
    return LineString(coords)


def polygon_from_way_or_relation(element: dict[str, Any]):
    geometry = element.get("geometry")
    if not geometry:
        return point_from_element(element)
    coords = [(float(item["lon"]), float(item["lat"])) for item in geometry]
    if len(coords) >= 4 and coords[0] == coords[-1]:
        return Polygon(coords)
    if len(coords) >= 2:
        return LineString(coords)
    return point_from_element(element)


def pois_to_geojson(payload: dict[str, Any], output_path: Path) -> None:
    rows = []
    for element in payload.get("elements", []):
        geom = point_from_element(element)
        if geom is None:
            continue
        tags = element_tags(element)
        rows.append({**tags, "geometry": geom})
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    gdf.to_file(output_path, driver="GeoJSON")


def roads_to_geojson(payload: dict[str, Any], output_path: Path) -> None:
    rows = []
    for element in payload.get("elements", []):
        if element.get("type") != "way":
            continue
        geom = line_from_way(element)
        if geom is None:
            continue
        tags = element_tags(element)
        rows.append({**tags, "geometry": geom})
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    gdf.to_file(output_path, driver="GeoJSON")


def landuse_to_geojson(payload: dict[str, Any], output_path: Path) -> None:
    rows = []
    for element in payload.get("elements", []):
        geom = polygon_from_way_or_relation(element)
        if geom is None:
            continue
        tags = element_tags(element)
        rows.append({**tags, "geometry": geom})
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    gdf.to_file(output_path, driver="GeoJSON")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    boundary = load_city_boundary()
    boundary_geojson = OUTPUT_DIR / "fuzhou_city_23_boundary.geojson"
    boundary.to_file(boundary_geojson, driver="GeoJSON")

    geometry = boundary.iloc[0].geometry
    poly = overpass_polygon_string(geometry)
    bounds = tuple(round(value, 6) for value in geometry.bounds)

    metadata = {
        "city_id": CITY_ID,
        "source_boundary": str(BOUNDARY_PATH),
        "boundary_filter": "ORIG_FID == 23",
        "crs": "EPSG:4326",
        "bounds": bounds,
        "centroid": [round(geometry.centroid.x, 6), round(geometry.centroid.y, 6)],
        "overpass_urls": OVERPASS_URLS,
        "outputs": {
            "boundary": "fuzhou_city_23_boundary.geojson",
            "poi_raw": "raw_overpass_pois.json",
            "pois": "fuzhou_city_23_osm_pois.geojson",
            "roads_raw": "raw_overpass_roads.json",
            "roads": "fuzhou_city_23_osm_roads.geojson",
            "landuse_raw": "raw_overpass_landuse.json",
            "landuse": "fuzhou_city_23_osm_landuse.geojson",
        },
    }
    (OUTPUT_DIR / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    poi_query = f"""
    [out:json][timeout:180];
    (
      nwr(poly:"{poly}")["amenity"];
      nwr(poly:"{poly}")["shop"];
      nwr(poly:"{poly}")["office"];
      nwr(poly:"{poly}")["tourism"];
      nwr(poly:"{poly}")["leisure"];
      nwr(poly:"{poly}")["healthcare"];
      nwr(poly:"{poly}")["craft"];
      nwr(poly:"{poly}")["industrial"];
      nwr(poly:"{poly}")["public_transport"];
      nwr(poly:"{poly}")["railway"~"station|halt|tram_stop|subway_entrance"];
    );
    out center tags;
    """

    road_query = f"""
    [out:json][timeout:180];
    (
      way(poly:"{poly}")["highway"];
    );
    out geom tags;
    """

    landuse_query = f"""
    [out:json][timeout:180];
    (
      nwr(poly:"{poly}")["landuse"~"commercial|retail|industrial|residential|education|institutional|office"];
      nwr(poly:"{poly}")["building"~"commercial|retail|industrial|office|school|university|college|hospital|apartments|residential|dormitory"];
    );
    out geom center tags;
    """

    poi_payload = query_overpass(poi_query, OUTPUT_DIR / "raw_overpass_pois.json")
    pois_to_geojson(poi_payload, OUTPUT_DIR / "fuzhou_city_23_osm_pois.geojson")

    road_payload = query_overpass(road_query, OUTPUT_DIR / "raw_overpass_roads.json")
    roads_to_geojson(road_payload, OUTPUT_DIR / "fuzhou_city_23_osm_roads.geojson")

    landuse_payload = query_overpass(landuse_query, OUTPUT_DIR / "raw_overpass_landuse.json")
    landuse_to_geojson(landuse_payload, OUTPUT_DIR / "fuzhou_city_23_osm_landuse.geojson")

    print(f"Saved OSM inputs to: {OUTPUT_DIR}")
    for path in sorted(OUTPUT_DIR.iterdir()):
        if path.is_file():
            print(f"{path.name}\t{path.stat().st_size}")


if __name__ == "__main__":
    main()
