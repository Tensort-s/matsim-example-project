#!/usr/bin/env python3
"""Merge Hong Kong iGeoCom and OSM POIs for modeling-ready POI coverage."""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import pandas as pd

_RASTERIO_SPEC = importlib.util.find_spec("rasterio")
if _RASTERIO_SPEC and _RASTERIO_SPEC.origin:
    _RASTERIO_DIR = Path(_RASTERIO_SPEC.origin).resolve().parent
    _PROJ_DATA = str(_RASTERIO_DIR / "proj_data")
    _GDAL_DATA = str(_RASTERIO_DIR / "gdal_data")
    os.environ["PROJ_DATA"] = _PROJ_DATA
    os.environ["PROJ_LIB"] = _PROJ_DATA
    os.environ["GDAL_DATA"] = _GDAL_DATA

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_IGEOCOM = ROOT / "data/osm/hongkong/iGeoCom_GeoJSON/iGeoCOM_POI.geojson"
DEFAULT_OSM = ROOT / "data/osm/hongkong/fixed_link_boundary/hong_kong_fixed_link_osm_pois.geojson"
DEFAULT_BOUNDARY = ROOT / "data/boundary/hongkong/processed/hong_kong_fixed_link_boundary_wgs84.geojson"
DEFAULT_OUT_DIR = ROOT / "data/osm/hongkong/fixed_link_boundary/integrated_pois"
MODEL_CRS = "EPSG:32650"

POI_CATEGORIES = [
    "finance",
    "toilets",
    "transport",
    "cinema and theatre",
    "health",
    "service",
    "education",
    "government",
    "religion",
    "accommodation",
    "bar",
    "cafe",
    "fast food",
    "ice cream",
    "food court",
    "restaurant",
    "beauty shop",
    "clothes shop",
    "boutique",
    "bicycle shop",
    "retail",
    "supermarket",
    "houseware shop",
    "sport",
    "transit station",
    "kindergarten",
    "office",
    "recycling",
    "travel agency",
    "tourism",
    "livelihood shop",
    "residential",
    "dormitory",
    "garden",
]

OSM_LOW_VALUE_RAILWAY = {
    "switch",
    "rail",
    "subway",
    "crossing",
    "light_rail",
    "signal",
    "construction",
    "proposed",
    "platform_edge",
    "junction",
    "yard",
    "abandoned",
    "railway_crossing",
    "tram_crossing",
    "yes",
}

IGEOCOM_CLASS_CATEGORY = {
    "AMD": "accommodation",
    "AQU": "tourism",
    "BGD": "religion",
    "BUS": "office",
    "CMF": "retail",
    "COM": "service",
    "CUF": "service",
    "GOV": "government",
    "HNC": "health",
    "MUF": "service",
    "PAK": "garden",
    "REM": "religion",
    "RSF": "sport",
    "SCH": "education",
    "TRF": "transport",
    "TRH": "transport",
    "TRS": "transport",
    "UTI": "service",
}

IGEOCOM_TYPE_CATEGORY = {
    "TOI": "toilets",
    "KDG": "kindergarten",
    "PRS": "education",
    "SES": "education",
    "SEC": "education",
    "TEI": "education",
    "VTI": "education",
    "CCC": "kindergarten",
    "HOS": "health",
    "CLI": "health",
    "ELD": "health",
    "POB": "service",
    "POF": "service",
    "FSN": "government",
    "PSN": "government",
    "CST": "government",
    "GOD": "government",
    "GOF": "government",
    "DOF": "government",
    "CPO": "transport",
    "MTA": "transit station",
    "BUS": "transit station",
    "FER": "transit station",
    "LRA": "transit station",
    "HLP": "transport",
    "AER": "transport",
    "HTL": "accommodation",
    "GHS": "accommodation",
    "MAL": "retail",
    "MKT": "retail",
    "CVS": "service",
    "SMK": "service",
    "CHU": "religion",
    "TMP": "religion",
    "MON": "religion",
    "LIB": "education",
    "TTH": "cinema and theatre",
    "EXB": "tourism",
    "PAR": "garden",
    "RGD": "garden",
    "PLG": "sport",
    "SGD": "sport",
    "PAV": "sport",
    "BAS": "sport",
    "TCT": "sport",
    "SPL": "sport",
    "CMC": "service",
    "VOF": "office",
    "FSC": "service",
}

WORK_RELATED_CATEGORIES = {
    "finance",
    "health",
    "education",
    "government",
    "accommodation",
    "bar",
    "cafe",
    "fast food",
    "food court",
    "restaurant",
    "retail",
    "supermarket",
    "houseware shop",
    "kindergarten",
    "office",
    "travel agency",
    "tourism",
    "livelihood shop",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--igeocom", type=Path, default=DEFAULT_IGEOCOM)
    parser.add_argument("--osm", type=Path, default=DEFAULT_OSM)
    parser.add_argument("--boundary", type=Path, default=DEFAULT_BOUNDARY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--named-distance-m", type=float, default=15.0)
    parser.add_argument("--unnamed-distance-m", type=float, default=8.0)
    parser.add_argument("--name-similarity", type=float, default=0.78)
    return parser.parse_args()


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.lower() in {"nan", "none", "null"}:
        return None
    return text


def lower_value(row: pd.Series, key: str) -> str:
    value = clean_text(row.get(key))
    return value.lower() if value else ""


def normalize_name(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "", text, flags=re.UNICODE)
    for token in ("hongkong", "hk", "香港"):
        text = text.replace(token, "")
    return text


def name_similarity(osm_name: str, name_en: str | None, name_zh: str | None) -> float:
    candidates = [normalize_name(name_en), normalize_name(name_zh)]
    osm_norm = normalize_name(osm_name)
    if not osm_norm:
        return 0.0
    scores = []
    for candidate in candidates:
        if not candidate:
            continue
        if osm_norm in candidate or candidate in osm_norm:
            scores.append(1.0)
        else:
            scores.append(SequenceMatcher(None, osm_norm, candidate).ratio())
    return max(scores) if scores else 0.0


def other_tags(row: pd.Series) -> str:
    return lower_value(row, "other_tags")


def contains_other(row: pd.Series, *needles: str) -> bool:
    tags = other_tags(row)
    return any(needle.lower() in tags for needle in needles)


def osm_categories(row: pd.Series) -> list[str]:
    amenity = lower_value(row, "amenity")
    shop = lower_value(row, "shop")
    office = lower_value(row, "office")
    tourism = lower_value(row, "tourism")
    leisure = lower_value(row, "leisure")
    healthcare = lower_value(row, "healthcare")
    building = lower_value(row, "building")
    landuse = lower_value(row, "landuse")
    highway = lower_value(row, "highway")
    railway = lower_value(row, "railway")
    public_transport = lower_value(row, "public_transport")
    sport = lower_value(row, "sport")

    matches: list[str] = []

    def add(category: str, condition: bool) -> None:
        if condition and category not in matches:
            matches.append(category)

    add("finance", amenity in {"bank", "atm", "bureau_de_change"} or office in {"financial", "insurance"})
    add("toilets", amenity == "toilets")
    add("cinema and theatre", amenity in {"cinema", "theatre", "arts_centre"} or tourism == "gallery")
    add("health", bool(healthcare) or amenity in {"hospital", "clinic", "doctors", "dentist", "pharmacy", "veterinary"})
    add("education", amenity in {"school", "college", "university", "library", "music_school", "language_school"} or landuse == "education" or building in {"school", "college", "university"})
    add("kindergarten", amenity == "kindergarten" or building == "kindergarten")
    add("government", office == "government" or amenity in {"townhall", "courthouse", "police", "fire_station", "prison", "ranger_station"})
    add("religion", amenity == "place_of_worship" or landuse == "religious" or building in {"church", "temple", "cathedral", "mosque", "synagogue", "shrine"})
    add("accommodation", tourism in {"hotel", "hostel", "guest_house", "motel", "apartment", "chalet", "camp_site"} or building == "hotel")
    add("bar", amenity in {"bar", "pub", "biergarten", "nightclub"})
    add("cafe", amenity == "cafe")
    add("fast food", amenity == "fast_food")
    add("ice cream", amenity == "ice_cream" or shop == "ice_cream")
    add("food court", amenity == "food_court")
    add("restaurant", amenity == "restaurant")
    add("beauty shop", shop in {"beauty", "hairdresser", "cosmetics", "massage", "perfumery", "tattoo"})
    add("clothes shop", shop in {"clothes", "shoes", "fashion", "jewelry", "bag", "fabric", "tailor"})
    add("boutique", shop == "boutique")
    add("bicycle shop", shop == "bicycle")
    add("supermarket", shop in {"supermarket", "wholesale", "department_store"})
    add("houseware shop", shop in {"furniture", "houseware", "kitchen", "interior_decoration", "doityourself", "hardware", "appliance", "electronics", "lighting", "bed"})
    add("sport", bool(sport) or leisure in {"pitch", "sports_centre", "stadium", "fitness_centre", "fitness_station", "track", "swimming_pool", "sports_hall"} or shop == "sports")
    add("transit station", highway in {"bus_stop", "platform"} or public_transport in {"platform", "station", "stop_position"} or amenity == "bus_station" or railway in {"station", "halt", "subway_entrance", "tram_stop", "buffer_stop", "stop"})
    add("transport", amenity in {"parking", "parking_space", "parking_entrance", "fuel", "taxi", "car_rental", "car_sharing", "bicycle_rental", "bicycle_parking", "charging_station", "vehicle_inspection"} or shop in {"car", "car_repair", "motorcycle", "tyres", "ticket"} or railway in {"level_crossing"} or contains_other(row, '"parking"', '"aeroway"', '"ferry"'))
    add("office", bool(office) or building in {"office", "commercial"} or landuse == "commercial")
    add("recycling", amenity in {"recycling", "waste_disposal", "waste_basket"})
    add("travel agency", shop == "travel_agency" or office == "travel_agent" or contains_other(row, "travel_agency", "travel_agent"))
    add("tourism", bool(tourism) and tourism not in {"hotel", "hostel", "guest_house", "motel", "apartment", "gallery"})
    add("livelihood shop", shop in {"convenience", "bakery", "butcher", "greengrocer", "seafood", "beverages", "alcohol", "tea", "coffee", "chemist", "florist", "laundry", "dry_cleaning", "copyshop", "mobile_phone", "optician", "books", "stationery", "gift", "variety_store", "pet", "tobacco"})
    add("residential", building in {"residential", "apartments", "house", "detached", "terrace"} or landuse == "residential")
    add("dormitory", building == "dormitory" or amenity == "dormitory")
    add("garden", leisure in {"garden", "park"} or landuse in {"recreation_ground", "village_green"} or tourism == "picnic_site")
    add("service", amenity in {"post_office", "post_box", "shelter", "community_centre", "social_facility", "public_building", "telephone", "internet_cafe", "marketplace", "drinking_water", "bench", "fountain"} or shop in {"yes", "mall", "general", "retail", "trade", "kiosk"} or contains_other(row, "service"))
    add("retail", bool(shop) and not matches)
    return matches


def igeocom_category(row: pd.Series) -> str | None:
    typ = lower_value(row, "TYPE").upper()
    cls = lower_value(row, "CLASS").upper()
    return IGEOCOM_TYPE_CATEGORY.get(typ) or IGEOCOM_CLASS_CATEGORY.get(cls)


def is_work_related(category: str | None, cls: str | None = None) -> bool:
    if category in WORK_RELATED_CATEGORIES:
        return True
    return (cls or "").upper() in {"BUS", "COM", "CMF", "GOV", "HNC", "SCH", "AMD"}


def standardize_igeocom(igeo: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    igeo = igeo.to_crs("EPSG:4326")
    igeo = igeo[igeo.geometry.notna() & ~igeo.geometry.is_empty].copy()
    igeo = gpd.sjoin(igeo, boundary[["geometry"]], how="inner", predicate="within").drop(columns=["index_right"])
    rows = []
    for _, row in igeo.iterrows():
        category = igeocom_category(row)
        geonameid = clean_text(row.get("GEONAMEID"))
        rows.append(
            {
                "poi_uid": f"igeocom:{geonameid}",
                "source": "igeocom",
                "source_priority": 1,
                "source_id": geonameid,
                "name_en": clean_text(row.get("ENGLISHNAME")),
                "name_zh": clean_text(row.get("CHINESENAME")),
                "class": clean_text(row.get("CLASS")),
                "type": clean_text(row.get("TYPE")),
                "subcat": clean_text(row.get("SUBCAT")),
                "address_en": clean_text(row.get("E_ADDRESS")),
                "address_zh": clean_text(row.get("C_ADDRESS")),
                "district_en": clean_text(row.get("E_DISTRICT")),
                "district_zh": clean_text(row.get("C_DISTRICT")),
                "phone": clean_text(row.get("TEL_NO")),
                "website": clean_text(row.get("WEB_SITE")),
                "rev_date": clean_text(row.get("REV_DATE")),
                "osm_id": None,
                "osm_name": None,
                "amenity": None,
                "shop": None,
                "office": None,
                "tourism": None,
                "leisure": None,
                "healthcare": None,
                "public_transport": None,
                "railway": None,
                "building": None,
                "landuse": None,
                "other_tags": None,
                "wedan_category": category,
                "is_work_related": is_work_related(category, clean_text(row.get("CLASS"))),
                "geometry": row.geometry,
            }
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def standardize_osm(osm: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    osm = osm.to_crs("EPSG:4326")
    osm = osm[osm.geometry.notna() & ~osm.geometry.is_empty].copy()
    osm = gpd.sjoin(osm, boundary[["geometry"]], how="inner", predicate="within").drop(columns=["index_right"])
    rows = []
    for row_number, (_, row) in enumerate(osm.iterrows()):
        categories = osm_categories(row)
        category = categories[0] if categories else None
        osm_id = clean_text(row.get("osm_id"))
        name = clean_text(row.get("name"))
        rows.append(
            {
                "poi_uid": f"osm:{osm_id or 'missing'}:{row_number}",
                "source": "osm",
                "source_priority": 2,
                "source_id": osm_id,
                "name_en": name,
                "name_zh": None,
                "class": None,
                "type": None,
                "subcat": None,
                "address_en": clean_text(row.get("address")),
                "address_zh": None,
                "district_en": None,
                "district_zh": None,
                "phone": None,
                "website": None,
                "rev_date": None,
                "osm_id": osm_id,
                "osm_name": name,
                "amenity": clean_text(row.get("amenity")),
                "shop": clean_text(row.get("shop")),
                "office": clean_text(row.get("office")),
                "tourism": clean_text(row.get("tourism")),
                "leisure": clean_text(row.get("leisure")),
                "healthcare": clean_text(row.get("healthcare")),
                "public_transport": clean_text(row.get("public_transport")),
                "railway": clean_text(row.get("railway")),
                "building": clean_text(row.get("building")),
                "landuse": clean_text(row.get("landuse")),
                "other_tags": clean_text(row.get("other_tags")),
                "wedan_category": category,
                "is_work_related": is_work_related(category),
                "geometry": row.geometry,
            }
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def osm_filter_reason(row: pd.Series) -> str | None:
    has_name = bool(normalize_name(row.get("osm_name")))
    railway = lower_value(row, "railway")
    public_transport = lower_value(row, "public_transport")
    if not has_name and railway in OSM_LOW_VALUE_RAILWAY and not public_transport:
        return f"unnamed_low_value_railway:{railway}"
    if not has_name and not clean_text(row.get("wedan_category")):
        return "unnamed_unmapped_osm_feature"
    return None


def compatible_unnamed(osm_row: pd.Series, igeo_row: pd.Series) -> bool:
    osm_cat = clean_text(osm_row.get("wedan_category"))
    ig_cat = clean_text(igeo_row.get("wedan_category"))
    osm_amenity = lower_value(osm_row, "amenity")
    ig_type = (clean_text(igeo_row.get("type")) or "").upper()
    ig_class = (clean_text(igeo_row.get("class")) or "").upper()
    if osm_amenity == "post_box" and ig_type == "POB":
        return True
    if osm_cat == "transport" and (ig_type == "CPO" or ig_class in {"TRS", "TRF", "TRH"}):
        return True
    if osm_cat == "transit station" and ig_class in {"TRS", "TRF", "TRH"}:
        return True
    return bool(osm_cat and ig_cat and osm_cat == ig_cat)


def find_duplicates(
    osm_clean: gpd.GeoDataFrame,
    igeo: gpd.GeoDataFrame,
    named_distance_m: float,
    unnamed_distance_m: float,
    similarity_threshold: float,
) -> tuple[set[str], pd.DataFrame]:
    igeo_m = igeo.to_crs(MODEL_CRS).reset_index(drop=True)
    osm_m = osm_clean.to_crs(MODEL_CRS).reset_index(drop=True)
    igeo_sindex = igeo_m.sindex
    duplicates: set[str] = set()
    records: list[dict[str, Any]] = []

    for _, osm_row in osm_m.iterrows():
        osm_uid = str(osm_row["poi_uid"])
        osm_name = clean_text(osm_row.get("osm_name"))
        distance_limit = named_distance_m if normalize_name(osm_name) else unnamed_distance_m
        candidate_idx = list(igeo_sindex.query(osm_row.geometry.buffer(distance_limit), predicate="intersects"))
        best: tuple[float, float, pd.Series, str] | None = None
        for idx in candidate_idx:
            ig_row = igeo_m.iloc[int(idx)]
            distance = float(osm_row.geometry.distance(ig_row.geometry))
            if distance > distance_limit:
                continue
            if normalize_name(osm_name):
                score = name_similarity(str(osm_name), clean_text(ig_row.get("name_en")), clean_text(ig_row.get("name_zh")))
                if score >= similarity_threshold:
                    reason = "nearby_similar_name"
                    rank = score
                else:
                    continue
            elif compatible_unnamed(osm_row, ig_row):
                score = 1.0
                reason = "nearby_compatible_unnamed_category"
                rank = 1.0 - distance / max(distance_limit, 1.0)
            else:
                continue
            if best is None or (rank, -distance) > (best[0], -best[1]):
                best = (rank, distance, ig_row, reason)

        if best:
            rank, distance, ig_row, reason = best
            duplicates.add(osm_uid)
            records.append(
                {
                    "osm_poi_uid": osm_uid,
                    "osm_id": osm_row.get("osm_id"),
                    "osm_name": osm_row.get("osm_name"),
                    "osm_category": osm_row.get("wedan_category"),
                    "matched_poi_uid": ig_row.get("poi_uid"),
                    "matched_geonameid": ig_row.get("source_id"),
                    "matched_name_en": ig_row.get("name_en"),
                    "matched_name_zh": ig_row.get("name_zh"),
                    "matched_type": ig_row.get("type"),
                    "matched_category": ig_row.get("wedan_category"),
                    "distance_m": distance,
                    "name_similarity": rank if reason == "nearby_similar_name" else None,
                    "match_reason": reason,
                }
            )

    return duplicates, pd.DataFrame(records)


def write_preview(integrated: gpd.GeoDataFrame, boundary: gpd.GeoDataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 8), dpi=180)
    boundary.to_crs(MODEL_CRS).boundary.plot(ax=ax, linewidth=0.6, color="#333333")
    sample = integrated.to_crs(MODEL_CRS)
    colors = {"igeocom": "#2a9d8f", "osm": "#e76f51"}
    for source, color in colors.items():
        subset = sample[sample["source"] == source]
        subset.plot(ax=ax, markersize=0.5, color=color, alpha=0.45, label=f"{source} ({len(subset):,})")
    ax.legend(loc="lower left", markerscale=8)
    ax.set_title("Hong Kong integrated POIs: iGeoCom + OSM")
    ax.set_axis_off()
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    args = parse_args()
    for path in [args.igeocom, args.osm, args.boundary]:
        if not path.exists():
            raise FileNotFoundError(path)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    boundary = gpd.read_file(args.boundary).to_crs("EPSG:4326")
    boundary["geometry"] = boundary.geometry.make_valid()
    boundary = boundary[~boundary.geometry.is_empty].copy()

    igeo_raw = gpd.read_file(args.igeocom)
    osm_raw = gpd.read_file(args.osm)
    igeo = standardize_igeocom(igeo_raw, boundary)
    osm = standardize_osm(osm_raw, boundary)

    filter_reasons = osm.apply(osm_filter_reason, axis=1)
    osm_filtered = osm[filter_reasons.notna()].copy()
    osm_filtered["filter_reason"] = filter_reasons[filter_reasons.notna()].to_numpy()
    osm_clean = osm[filter_reasons.isna()].copy()

    duplicate_uids, duplicates = find_duplicates(
        osm_clean,
        igeo,
        args.named_distance_m,
        args.unnamed_distance_m,
        args.name_similarity,
    )
    osm_duplicates = osm_clean[osm_clean["poi_uid"].isin(duplicate_uids)].copy()
    osm_retained = osm_clean[~osm_clean["poi_uid"].isin(duplicate_uids)].copy()
    integrated = gpd.GeoDataFrame(pd.concat([igeo, osm_retained], ignore_index=True), geometry="geometry", crs="EPSG:4326")
    integrated = integrated.sort_values(["source_priority", "poi_uid"]).reset_index(drop=True)

    geojson_path = args.out_dir / "hong_kong_fixed_link_integrated_pois.geojson"
    csv_path = args.out_dir / "hong_kong_fixed_link_integrated_pois.csv"
    duplicates_path = args.out_dir / "hong_kong_fixed_link_integrated_pois_duplicates.csv"
    filtered_path = args.out_dir / "hong_kong_fixed_link_integrated_pois_filtered_osm.geojson"
    preview_path = args.out_dir / "hong_kong_fixed_link_integrated_pois_preview.png"
    summary_path = args.out_dir / "hong_kong_fixed_link_integrated_pois_summary.json"

    integrated.to_file(geojson_path, driver="GeoJSON")
    csv_df = pd.DataFrame(integrated.drop(columns="geometry"))
    csv_df["lon"] = integrated.geometry.x
    csv_df["lat"] = integrated.geometry.y
    csv_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    duplicates.to_csv(duplicates_path, index=False, encoding="utf-8-sig")
    osm_filtered.to_file(filtered_path, driver="GeoJSON")
    write_preview(integrated, boundary, preview_path)

    summary = {
        "inputs": {
            "igeocom": str(args.igeocom),
            "osm": str(args.osm),
            "boundary": str(args.boundary),
        },
        "parameters": {
            "named_distance_m": args.named_distance_m,
            "unnamed_distance_m": args.unnamed_distance_m,
            "name_similarity": args.name_similarity,
        },
        "counts": {
            "igeocom_raw": int(len(igeo_raw)),
            "igeocom_inside_fixed_link": int(len(igeo)),
            "osm_raw": int(len(osm_raw)),
            "osm_inside_fixed_link": int(len(osm)),
            "osm_filtered": int(len(osm_filtered)),
            "osm_duplicate": int(len(osm_duplicates)),
            "osm_retained": int(len(osm_retained)),
            "integrated_total": int(len(integrated)),
            "work_related_total": int(integrated["is_work_related"].sum()),
        },
        "qa": {
            "poi_uid_unique": bool(integrated["poi_uid"].is_unique),
            "geometry_types": integrated.geometry.geom_type.value_counts().to_dict(),
            "crs": str(integrated.crs),
            "osm_accounting_ok": int(len(osm_filtered) + len(osm_duplicates) + len(osm_retained)) == int(len(osm)),
            "igeocom_all_retained": int((integrated["source"] == "igeocom").sum()) == int(len(igeo)),
        },
        "category_counts": integrated["wedan_category"].fillna("unmapped").value_counts().to_dict(),
        "filter_reason_counts": osm_filtered["filter_reason"].value_counts().to_dict() if not osm_filtered.empty else {},
        "duplicate_reason_counts": duplicates["match_reason"].value_counts().to_dict() if not duplicates.empty else {},
        "outputs": {
            "geojson": str(geojson_path),
            "csv": str(csv_path),
            "duplicates": str(duplicates_path),
            "filtered_osm": str(filtered_path),
            "preview": str(preview_path),
        },
        "note": "iGeoCom is retained as the authoritative source; OSM supplements iGeoCom after model-oriented filtering and duplicate auditing.",
    }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
