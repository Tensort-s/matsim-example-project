from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OSM_DIR = PROJECT_ROOT / "data" / "osm" / "fuzhou_city_23"
PBF_PATH = OSM_DIR / "city_23.osm.pbf"

POI_TAG_COLUMNS = [
    "amenity",
    "shop",
    "office",
    "tourism",
    "leisure",
    "healthcare",
    "craft",
    "industrial",
    "public_transport",
    "railway",
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

WORK_RELATED_LANDUSE = {
    "commercial",
    "retail",
    "industrial",
    "education",
    "institutional",
}

WORK_RELATED_BUILDINGS = {
    "commercial",
    "retail",
    "industrial",
    "office",
    "school",
    "university",
    "college",
    "hospital",
}


def read_layer(layer: str) -> gpd.GeoDataFrame:
    return gpd.read_file(PBF_PATH, layer=layer).to_crs("EPSG:4326")


def existing_columns(gdf: gpd.GeoDataFrame, columns: list[str]) -> list[str]:
    return [column for column in columns if column in gdf.columns]


def non_empty_tag_mask(gdf: gpd.GeoDataFrame, columns: list[str]):
    cols = existing_columns(gdf, columns)
    if not cols:
        return gdf.index == "__never__"
    mask = False
    for column in cols:
        mask = mask | gdf[column].notna()
    return mask


def write_geojson(gdf: gpd.GeoDataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if gdf.empty:
        gdf = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    gdf.to_file(path, driver="GeoJSON")


def main() -> None:
    if not PBF_PATH.exists():
        raise RuntimeError(f"Missing PBF: {PBF_PATH}")

    points = read_layer("points")
    lines = read_layer("lines")
    multipolygons = read_layer("multipolygons")

    poi_parts = []
    for gdf in [points, lines, multipolygons]:
        mask = non_empty_tag_mask(gdf, POI_TAG_COLUMNS)
        selected = gdf.loc[mask].copy()
        if not selected.empty:
            selected["geometry"] = selected.geometry.representative_point()
            poi_parts.append(selected)
    pois = gpd.GeoDataFrame(
        pd.concat(poi_parts, ignore_index=True) if poi_parts else [],
        geometry="geometry",
        crs="EPSG:4326",
    )

    roads = lines.loc[lines.get("highway").notna()].copy() if "highway" in lines.columns else lines.iloc[0:0].copy()

    landuse_mask = False
    if "landuse" in multipolygons.columns:
        landuse_mask = landuse_mask | multipolygons["landuse"].isin(WORK_RELATED_LANDUSE)
    if "building" in multipolygons.columns:
        landuse_mask = landuse_mask | multipolygons["building"].isin(WORK_RELATED_BUILDINGS)
    landuse = multipolygons.loc[landuse_mask].copy() if hasattr(landuse_mask, "any") else multipolygons.iloc[0:0].copy()

    work_mask = False
    for column in existing_columns(pois, ["office", "shop", "industrial", "craft", "healthcare"]):
        work_mask = work_mask | pois[column].notna()
    if "amenity" in pois.columns:
        work_mask = work_mask | pois["amenity"].isin(WORK_RELATED_AMENITIES)
    work_pois = pois.loc[work_mask].copy() if hasattr(work_mask, "any") else pois.iloc[0:0].copy()

    write_geojson(pois, OSM_DIR / "fuzhou_city_23_osm_pois.geojson")
    write_geojson(work_pois, OSM_DIR / "fuzhou_city_23_osm_work_pois.geojson")
    write_geojson(roads, OSM_DIR / "fuzhou_city_23_osm_roads.geojson")
    write_geojson(landuse, OSM_DIR / "fuzhou_city_23_osm_landuse_buildings.geojson")

    summary = {
        "source_pbf": str(PBF_PATH),
        "layers": {
            "points": len(points),
            "lines": len(lines),
            "multipolygons": len(multipolygons),
        },
        "outputs": {
            "pois": len(pois),
            "work_pois": len(work_pois),
            "roads": len(roads),
            "landuse_buildings": len(landuse),
        },
    }
    (OSM_DIR / "pbf_extract_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
