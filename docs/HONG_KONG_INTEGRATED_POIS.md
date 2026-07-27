# Hong Kong integrated POIs

This document records the modeling-ready POI layer merged from the 2026
iGeoCom GeoCommunity Database and the extracted OSM POIs.

## Sources

iGeoCom source:

```text
data/osm/hongkong/iGeoCom_GeoJSON/iGeoCOM_POI.geojson
```

OSM source:

```text
data/osm/hongkong/fixed_link_boundary/hong_kong_fixed_link_osm_pois.geojson
```

Boundary:

```text
data/boundary/hongkong/processed/hong_kong_fixed_link_boundary_wgs84.geojson
```

## Script

Canonical command:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\data_preparation\merge_hong_kong_igeocom_osm_pois.py
```

The merge treats iGeoCom as the authoritative source and OSM as a supplemental
source. All fixed-link iGeoCom POIs are retained. OSM POIs are filtered for
modeling relevance, then de-duplicated against nearby iGeoCom points.

## Merge policy

Standardized output fields include:

```text
poi_uid, source, source_priority, source_id,
name_en, name_zh, class, type, subcat,
address_en, address_zh, district_en, district_zh,
phone, website, rev_date,
osm_id, osm_name, amenity, shop, office, tourism, leisure, healthcare,
public_transport, railway, building, landuse, other_tags,
wedan_category, is_work_related, geometry
```

OSM filtering removes unnamed low-value engineering features such as railway
switches, crossings, signals, construction/proposed rail features, and unnamed
unmapped OSM features. Named OSM features and OSM features mapped to useful
modeling categories are retained unless identified as duplicates.

Duplicate rules:

```text
named OSM point:      duplicate if within 15 m of iGeoCom and name similarity >= 0.78
unnamed OSM point:    duplicate if within 8 m of iGeoCom and category is compatible
```

The duplicate audit is written separately; duplicate OSM points are not included
in the final integrated POI layer.

## Output data

Main directory:

```text
data/osm/hongkong/fixed_link_boundary/integrated_pois/
```

Key outputs:

```text
hong_kong_fixed_link_integrated_pois.geojson
hong_kong_fixed_link_integrated_pois.csv
hong_kong_fixed_link_integrated_pois_duplicates.csv
hong_kong_fixed_link_integrated_pois_filtered_osm.geojson
hong_kong_fixed_link_integrated_pois_summary.json
hong_kong_fixed_link_integrated_pois_preview.png
```

`hong_kong_fixed_link_integrated_pois.geojson` is the preferred POI source for
later Hong Kong WEDAN POI feature aggregation.

## Current QA

Current checked run:

```text
iGeoCom raw:                   37,356
iGeoCom inside fixed-link:     36,030
OSM raw inside fixed-link:      76,635
OSM filtered:                   4,411
OSM duplicate:                  8,980
OSM retained:                  63,244
integrated total:              99,274
work-related total:            31,365
CRS:                           EPSG:4326
geometry type:                 Point
points inside fixed-link:      99,274 / 99,274
unique poi_uid:                yes
```

OSM accounting check:

```text
4,411 filtered + 8,980 duplicates + 63,244 retained = 76,635 OSM input POIs
```

Largest WEDAN-style category counts:

```text
transit station:   19,723
service:           16,523
sport:             12,111
transport:         11,033
restaurant:         3,744
tourism:            2,965
religion:           2,893
garden:             2,809
education:          2,719
kindergarten:       2,333
```

## Notes for WEDAN

This step only creates the integrated POI point layer. The next step is to
aggregate `hong_kong_fixed_link_integrated_pois.geojson` to the Hong Kong
`regions.shp` row order and generate:

```text
data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/GeneratingCodeData/data/global_cities/hong_kong_fixed_link_grid/nfeat/pois.npy
```
