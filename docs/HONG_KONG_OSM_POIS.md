# Hong Kong OSM POI extraction

This document records the OSM POI data product prepared for Hong Kong WEDAN
feature generation.

## Source and boundary

Source:

```text
Geofabrik Hong Kong OSM PBF
https://download.geofabrik.de/asia/china/hong-kong-latest.osm.pbf
```

Boundary:

```text
data/boundary/hongkong/processed/hong_kong_fixed_link_boundary_wgs84.geojson
```

The boundary is the fixed-link Hong Kong model boundary derived from the 2021
Census District Council polygons. It excludes disconnected outlying islands
without road, bridge, tunnel, or dam access.

## Script

Canonical command:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\data_acquisition\download_hong_kong_osm_pois.py
```

The script downloads the Hong Kong PBF when missing, reads `points`, `lines`,
and `multipolygons` inside the boundary bounding box, filters OSM features with
POI-like tags, converts line and polygon POIs to representative points, and then
keeps only points inside the fixed-link boundary.

POI tag keys:

```text
amenity, shop, office, tourism, leisure, healthcare, craft, industrial,
public_transport, railway
```

## Output data

Main directory:

```text
data/osm/hongkong/fixed_link_boundary/
```

Key outputs:

```text
hong-kong-latest.osm.pbf
hong_kong_fixed_link_osm_pois.geojson
hong_kong_fixed_link_osm_work_pois.geojson
osm_poi_extract_summary.json
```

`hong_kong_fixed_link_osm_pois.geojson` is the main input for later
`pois.npy` aggregation. `hong_kong_fixed_link_osm_work_pois.geojson` is a
work-related subset, useful for checks and exploratory demand modeling.

## Current QA

Current checked run:

```text
PBF size:                      37,271,168 bytes
bbox points:                   117,095
bbox lines:                    223,410
bbox multipolygons:            187,142
point POIs inside boundary:    48,551
line POIs inside boundary:     2,981
polygon POIs inside boundary:  25,103
total POIs:                    76,635
work-related POIs:             18,977
CRS:                           EPSG:4326
geometry type:                 Point
points inside boundary:        76,635 / 76,635
```

Selected non-null tag counts:

```text
amenity:            29,352
shop:                7,596
office:              1,123
tourism:             3,644
leisure:            10,420
healthcare:            821
craft:                  94
industrial:            299
public_transport:   19,023
railway:             7,020
```

Most common `amenity` values include restaurant, shelter, parking space,
parking, toilets, place of worship, school, bench, fast food, post box, cafe,
and bank.

## Notes for WEDAN

This step only prepares raw OSM POI points. The next step is to aggregate
`hong_kong_fixed_link_osm_pois.geojson` to:

```text
data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/GeneratingCodeData/data/global_cities/hong_kong_fixed_link_grid/nfeat/pois.npy
```

Rows must follow the order of:

```text
data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/CityAndRegionSplit/hong_kong_fixed_link_grid/regions.shp
```
