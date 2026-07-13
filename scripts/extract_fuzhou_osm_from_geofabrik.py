from __future__ import annotations

import json
import re
from pathlib import Path

import geopandas as gpd
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OSM_DIR = PROJECT_ROOT / "data" / "osm" / "fuzhou_city_23"
PBF_PATH = OSM_DIR / "fujian-latest.osm.pbf"
BOUNDARY_PATH = OSM_DIR / "fuzhou_city_23_boundary.geojson"

TAG_KEYS = [
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
    "landuse",
    "building",
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
    "kindergarten",
    "pharmacy",
}

WORK_RELATED_RAILWAY = {"station", "halt", "tram_stop", "subway_entrance"}
WORK_RELATED_LANDUSE = {"commercial", "retail", "industrial", "education", "institutional"}
WORK_RELATED_BUILDINGS = {
    "commercial",
    "retail",
    "industrial",
    "office",
    "school",
    "university",
    "college",
    "hospital",
    "kindergarten",
}


def parse_other_tags(value) -> dict[str, str]:
    if value is None or pd.isna(value):
        return {}
    text = str(value)
    return dict(re.findall(r'"([^"]+)"=>"([^"]*)"', text))


def enrich_tags(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if "other_tags" not in gdf.columns:
        for key in TAG_KEYS:
            if key not in gdf.columns:
                gdf[key] = None
        return gdf

    parsed = gdf["other_tags"].map(parse_other_tags)
    for key in TAG_KEYS:
        if key not in gdf.columns:
            gdf[key] = parsed.map(lambda tags: tags.get(key))
        else:
            gdf[key] = gdf[key].where(gdf[key].notna(), parsed.map(lambda tags: tags.get(key)))
    return gdf


def read_layer(layer: str, boundary: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    bounds = tuple(boundary.total_bounds)
    gdf = gpd.read_file(PBF_PATH, layer=layer, bbox=bounds).to_crs("EPSG:4326")
    if gdf.empty:
        return gdf
    gdf = gdf[gdf.geometry.notna()].copy()
    # Keep only features that intersect the real city boundary, not just the bbox.
    # We deliberately avoid geometric clipping because raw OSM multipolygons can be invalid.
    selected = gpd.sjoin(gdf, boundary[["geometry"]], predicate="intersects", how="inner")
    selected = selected.drop(columns=["index_right"], errors="ignore").copy()
    return enrich_tags(selected)


def non_empty_mask(gdf: gpd.GeoDataFrame, columns: list[str]):
    mask = pd.Series(False, index=gdf.index)
    for column in columns:
        if column in gdf.columns:
            mask = mask | gdf[column].notna()
    return mask


def representative_points(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = gdf.copy()
    if out.empty:
        return out
    out["geometry"] = out.geometry.representative_point()
    return out


def write_geojson(gdf: gpd.GeoDataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(path, driver="GeoJSON")


def main() -> None:
    if not PBF_PATH.exists():
        raise RuntimeError(f"Missing source PBF: {PBF_PATH}")
    boundary = gpd.read_file(BOUNDARY_PATH).to_crs("EPSG:4326")

    points = read_layer("points", boundary)
    lines = read_layer("lines", boundary)
    multipolygons = read_layer("multipolygons", boundary)

    point_pois = points.loc[non_empty_mask(points, POI_KEYS)].copy()
    poly_pois = multipolygons.loc[non_empty_mask(multipolygons, POI_KEYS)].copy()
    line_pois = lines.loc[non_empty_mask(lines, POI_KEYS)].copy()
    pois = gpd.GeoDataFrame(
        pd.concat(
            [representative_points(point_pois), representative_points(poly_pois), representative_points(line_pois)],
            ignore_index=True,
        ),
        geometry="geometry",
        crs="EPSG:4326",
    )

    work_mask = pd.Series(False, index=pois.index)
    for column in ["office", "shop", "industrial", "craft", "healthcare"]:
        if column in pois.columns:
            work_mask = work_mask | pois[column].notna()
    if "amenity" in pois.columns:
        work_mask = work_mask | pois["amenity"].isin(WORK_RELATED_AMENITIES)
    if "railway" in pois.columns:
        work_mask = work_mask | pois["railway"].isin(WORK_RELATED_RAILWAY)
    work_pois = pois.loc[work_mask].copy()

    roads = lines.loc[lines["highway"].notna()].copy() if "highway" in lines.columns else lines.iloc[0:0].copy()

    landuse_mask = pd.Series(False, index=multipolygons.index)
    if "landuse" in multipolygons.columns:
        landuse_mask = landuse_mask | multipolygons["landuse"].isin(WORK_RELATED_LANDUSE)
    if "building" in multipolygons.columns:
        landuse_mask = landuse_mask | multipolygons["building"].isin(WORK_RELATED_BUILDINGS)
    landuse_buildings = multipolygons.loc[landuse_mask].copy()

    write_geojson(pois, OSM_DIR / "fuzhou_city_23_osm_pois.geojson")
    write_geojson(work_pois, OSM_DIR / "fuzhou_city_23_osm_work_pois.geojson")
    write_geojson(roads, OSM_DIR / "fuzhou_city_23_osm_roads.geojson")
    write_geojson(landuse_buildings, OSM_DIR / "fuzhou_city_23_osm_landuse_buildings.geojson")

    summary = {
        "source_pbf": str(PBF_PATH),
        "boundary": str(BOUNDARY_PATH),
        "bbox_layers_after_boundary_clip": {
            "points": len(points),
            "lines": len(lines),
            "multipolygons": len(multipolygons),
        },
        "outputs": {
            "pois": len(pois),
            "work_pois": len(work_pois),
            "roads": len(roads),
            "landuse_buildings": len(landuse_buildings),
        },
    }
    (OSM_DIR / "geofabrik_extract_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
