"""Build WorldOD/WEDAN-style `pois.npy` for the Greenspace Fuzhou grid.

This script aggregates locally downloaded OSM POI points to the custom
Greenspace Fuzhou grid. The output follows the 34 POI category order described
in the WorldCommuting-OD paper:

finance, toilets, transport, cinema and theatre, health, service, education,
government, religion, accommodation, bar, cafe, fast food, ice cream,
food court, restaurant, beauty shop, clothes shop, boutique, bicycle shop,
retail, supermarket, houseware shop, sport, transit station, kindergarten,
office, recycling, travel agency, tourism, livelihood shop, residential,
dormitory, garden.

Rows are aligned with `regions.shp` row order.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import pathlib
from collections import Counter
from typing import Any

_RASTERIO_SPEC = importlib.util.find_spec("rasterio")
if _RASTERIO_SPEC and _RASTERIO_SPEC.origin:
    _RASTERIO_DIR = pathlib.Path(_RASTERIO_SPEC.origin).resolve().parent
    os.environ["PROJ_DATA"] = str(_RASTERIO_DIR / "proj_data")
    os.environ["PROJ_LIB"] = str(_RASTERIO_DIR / "proj_data")
    os.environ["GDAL_DATA"] = str(_RASTERIO_DIR / "gdal_data")

import geopandas as gpd
import numpy as np
import pandas as pd


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_GRID = (
    PROJECT_ROOT
    / "data"
    / "worldcommuting_od"
    / "custom_features"
    / "fuzhou_city_23_greenspace_grid"
    / "CityAndRegionSplit"
    / "fuzhou_city_23_greenspace_grid"
    / "regions.shp"
)
DEFAULT_POIS = PROJECT_ROOT / "data" / "osm" / "fuzhou_city_23" / "fuzhou_city_23_osm_pois.geojson"
DEFAULT_NFEAT_DIR = (
    PROJECT_ROOT
    / "data"
    / "worldcommuting_od"
    / "custom_features"
    / "fuzhou_city_23_greenspace_grid"
    / "GeneratingCodeData"
    / "data"
    / "global_cities"
    / "fuzhou_city_23_greenspace_grid"
    / "nfeat"
)

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate OSM POIs to Greenspace Fuzhou grid and write pois.npy.")
    parser.add_argument("--grid", default=str(DEFAULT_GRID), help="Greenspace Fuzhou grid regions.shp.")
    parser.add_argument("--pois", default=str(DEFAULT_POIS), help="OSM POI GeoJSON.")
    parser.add_argument("--out-dir", default=str(DEFAULT_NFEAT_DIR), help="Output nfeat directory.")
    parser.add_argument(
        "--multi-label",
        action="store_true",
        help="Count a POI in every matching category. Default assigns one primary category by priority.",
    )
    return parser.parse_args()


def text_value(row: pd.Series, key: str) -> str:
    value = row.get(key, "")
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    return str(value).strip().lower()


def has_tag(row: pd.Series, key: str, values: set[str] | None = None) -> bool:
    value = text_value(row, key)
    if not value:
        return False
    return True if values is None else value in values


def other_tags(row: pd.Series) -> str:
    return text_value(row, "other_tags")


def contains_other(row: pd.Series, *needles: str) -> bool:
    tags = other_tags(row)
    return any(needle.lower() in tags for needle in needles)


def matched_categories(row: pd.Series) -> list[str]:
    """Return matching POI categories in priority order.

    The priority is chosen to keep specific categories before broad fallbacks
    such as office, retail, service, tourism, and transport.
    """

    amenity = text_value(row, "amenity")
    shop = text_value(row, "shop")
    office = text_value(row, "office")
    tourism = text_value(row, "tourism")
    leisure = text_value(row, "leisure")
    healthcare = text_value(row, "healthcare")
    building = text_value(row, "building")
    landuse = text_value(row, "landuse")
    highway = text_value(row, "highway")
    railway = text_value(row, "railway")
    public_transport = text_value(row, "public_transport")
    sport = text_value(row, "sport")

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
    add(
        "transit station",
        highway in {"bus_stop", "platform"} or public_transport in {"platform", "station", "stop_position"} or amenity == "bus_station" or railway in {"station", "halt", "subway_entrance", "tram_stop", "buffer_stop"},
    )
    add(
        "transport",
        amenity in {"parking", "fuel", "taxi", "car_rental", "car_sharing", "bicycle_rental", "charging_station", "vehicle_inspection"}
        or shop in {"car", "car_repair", "motorcycle", "tyres", "ticket"}
        or railway in {"level_crossing"}
        or contains_other(row, '"parking"', '"aeroway"', '"ferry"'),
    )
    add("office", bool(office) or building in {"office", "commercial"} or landuse == "commercial")
    add("recycling", amenity in {"recycling", "waste_disposal", "waste_basket"})
    add("travel agency", shop == "travel_agency" or office == "travel_agent" or contains_other(row, "travel_agency", "travel_agent"))
    add("tourism", bool(tourism) and tourism not in {"hotel", "hostel", "guest_house", "motel", "apartment", "gallery"})
    add(
        "livelihood shop",
        shop in {
            "convenience",
            "bakery",
            "butcher",
            "greengrocer",
            "seafood",
            "beverages",
            "alcohol",
            "tea",
            "coffee",
            "chemist",
            "florist",
            "laundry",
            "dry_cleaning",
            "copyshop",
            "mobile_phone",
            "optician",
            "books",
            "stationery",
            "gift",
            "variety_store",
            "pet",
            "tobacco",
        },
    )
    add("residential", building in {"residential", "apartments", "house", "detached", "terrace"} or landuse == "residential")
    add("dormitory", building == "dormitory" or amenity == "dormitory")
    add("garden", leisure in {"garden", "park"} or landuse in {"recreation_ground", "village_green"} or tourism == "picnic_site")
    add(
        "service",
        amenity in {
            "post_office",
            "post_box",
            "shelter",
            "community_centre",
            "social_facility",
            "public_building",
            "telephone",
            "internet_cafe",
            "marketplace",
            "drinking_water",
            "bench",
            "fountain",
        }
        or shop in {"yes", "mall", "general", "retail", "trade", "kiosk"}
        or contains_other(row, "service"),
    )
    add(
        "retail",
        bool(shop)
        and shop
        not in {
            "beauty",
            "hairdresser",
            "cosmetics",
            "massage",
            "perfumery",
            "tattoo",
            "clothes",
            "shoes",
            "fashion",
            "jewelry",
            "bag",
            "fabric",
            "tailor",
            "boutique",
            "bicycle",
            "supermarket",
            "wholesale",
            "department_store",
            "furniture",
            "houseware",
            "kitchen",
            "interior_decoration",
            "doityourself",
            "hardware",
            "appliance",
            "electronics",
            "lighting",
            "bed",
            "sports",
            "car",
            "car_repair",
            "motorcycle",
            "tyres",
            "ticket",
            "travel_agency",
            "convenience",
            "bakery",
            "butcher",
            "greengrocer",
            "seafood",
            "beverages",
            "alcohol",
            "tea",
            "coffee",
            "chemist",
            "florist",
            "laundry",
            "dry_cleaning",
            "copyshop",
            "mobile_phone",
            "optician",
            "books",
            "stationery",
            "gift",
            "variety_store",
            "pet",
            "tobacco",
        },
    )

    return matches


def build_pois(grid: gpd.GeoDataFrame, pois: gpd.GeoDataFrame, multi_label: bool) -> tuple[np.ndarray, pd.DataFrame, dict[str, Any]]:
    grid = grid.reset_index(drop=True).copy()
    grid["grid_index"] = np.arange(len(grid), dtype=int)
    pois = pois[pois.geometry.notna() & ~pois.geometry.is_empty].copy()
    pois = pois.to_crs(grid.crs)

    categorized_rows = []
    unmatched = []
    for idx, row in pois.iterrows():
        categories = matched_categories(row)
        if not categories:
            unmatched.append(idx)
            continue
        if not multi_label:
            categories = categories[:1]
        categorized_rows.append({"poi_index": idx, "categories": categories, "geometry": row.geometry})

    if categorized_rows:
        cat = gpd.GeoDataFrame(categorized_rows, geometry="geometry", crs=grid.crs)
        joined = gpd.sjoin(cat, grid[["grid_index", "locations", "geometry"]], how="inner", predicate="within")
    else:
        joined = gpd.GeoDataFrame(columns=["poi_index", "categories", "grid_index", "locations"], geometry=[], crs=grid.crs)

    features = np.zeros((len(grid), len(POI_CATEGORIES)), dtype=np.int64)
    records = []
    category_to_col = {name: i for i, name in enumerate(POI_CATEGORIES)}
    for _, row in joined.iterrows():
        grid_index = int(row["grid_index"])
        for category in row["categories"]:
            col = category_to_col[category]
            features[grid_index, col] += 1
            records.append(
                {
                    "grid_index": grid_index,
                    "locations": row["locations"],
                    "poi_index": int(row["poi_index"]),
                    "category": category,
                    "category_index": col,
                }
            )

    assignments = pd.DataFrame(records)
    summary = {
        "input_pois": int(len(pois)),
        "categorized_pois": int(len(categorized_rows)),
        "unmatched_pois": int(len(unmatched)),
        "joined_pois_or_assignments": int(len(assignments)),
        "multi_label": bool(multi_label),
        "category_sums": {cat: int(features[:, i].sum()) for i, cat in enumerate(POI_CATEGORIES)},
        "nonzero_grid_count": int(np.count_nonzero(features.sum(axis=1) > 0)),
        "total_count": int(features.sum()),
        "top_unmatched_tags": {},
    }

    # Quick audit of common unmatched tag combinations.
    unmatched_counter = Counter()
    for idx in unmatched:
        row = pois.loc[idx]
        key = "|".join(
            f"{col}={text_value(row, col)}"
            for col in ["amenity", "shop", "office", "tourism", "leisure", "highway", "railway", "building", "landuse"]
            if text_value(row, col)
        )
        if key:
            unmatched_counter[key] += 1
    summary["top_unmatched_tags"] = dict(unmatched_counter.most_common(30))
    return features, assignments, summary


def main() -> None:
    args = parse_args()
    grid_path = pathlib.Path(args.grid)
    pois_path = pathlib.Path(args.pois)
    out_dir = pathlib.Path(args.out_dir)
    for path in [grid_path, pois_path]:
        if not path.exists():
            raise FileNotFoundError(path)

    grid = gpd.read_file(grid_path)
    pois = gpd.read_file(pois_path)
    features, assignments, summary = build_pois(grid, pois, args.multi_label)

    out_dir.mkdir(parents=True, exist_ok=True)
    pois_npy = out_dir / "pois.npy"
    np.save(pois_npy, features)

    categories_path = out_dir / "poi_categories.json"
    categories_path.write_text(json.dumps(POI_CATEGORIES, indent=2, ensure_ascii=False), encoding="utf-8")

    mapping_path = out_dir / "poi_mapping_policy.json"
    mapping_policy = {
        "category_order": POI_CATEGORIES,
        "assignment_mode": "multi-label" if args.multi_label else "single primary category by priority",
        "source": "OSM tags from fuzhou_city_23_osm_pois.geojson",
        "note": "Mapping approximates the 34 OpenPOIMap-derived WorldCommuting-OD categories using available OSM tags. Specific categories are prioritized before broad fallbacks.",
    }
    mapping_path.write_text(json.dumps(mapping_policy, indent=2, ensure_ascii=False), encoding="utf-8")

    assignments_path = out_dir / "poi_grid_assignments.csv"
    assignments.to_csv(assignments_path, index=False, encoding="utf-8-sig")

    category_table = pd.DataFrame(
        {
            "category_index": np.arange(len(POI_CATEGORIES), dtype=int),
            "category": POI_CATEGORIES,
            "count": [summary["category_sums"][cat] for cat in POI_CATEGORIES],
            "nonzero_grids": [int(np.count_nonzero(features[:, i] > 0)) for i in range(len(POI_CATEGORIES))],
        }
    )
    category_csv = out_dir / "poi_category_counts.csv"
    category_table.to_csv(category_csv, index=False, encoding="utf-8-sig")

    summary.update(
        {
            "grid": str(grid_path),
            "pois": str(pois_path),
            "output": str(pois_npy),
            "shape": list(features.shape),
            "dtype": str(features.dtype),
            "categories": str(categories_path),
            "mapping_policy": str(mapping_path),
            "assignments": str(assignments_path),
            "category_counts": str(category_csv),
            "row_order": "Rows follow regions.shp row order.",
        }
    )
    summary_path = out_dir / "pois_generation_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote: {pois_npy} shape={features.shape}")
    print(f"Wrote: {categories_path}")
    print(f"Wrote: {assignments_path}")
    print(f"Wrote: {category_csv}")
    print(f"Wrote: {summary_path}")
    print(f"Total POI count in pois.npy: {int(features.sum())}")
    print(f"Nonzero grids: {summary['nonzero_grid_count']}/{features.shape[0]}")


if __name__ == "__main__":
    main()
