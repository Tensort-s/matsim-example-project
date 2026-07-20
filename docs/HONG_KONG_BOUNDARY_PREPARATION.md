# Hong Kong boundary preparation

This document records the first Hong Kong modeling data product: a fixed-link
administrative boundary derived from the 2021 Population Census district
boundary shapefile.

## Source

```text
data/boundary/hongkong/2021_Population_Census_Statistics_and_Boundar_SHP/DC_21C_converted.shp
```

The source layer contains 18 District Council records and uses Hong Kong 1980
Grid:

```text
EPSG:2326
```

## Processing script

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\data_preparation\prepare_hong_kong_boundary.py
```

The script dissolves the district boundaries, splits the result into physical
land components, and classifies components by whether they have fixed road,
bridge, tunnel, or dam access to the road network.

## Retained fixed-link components

The retained model boundary includes:

- Mainland / New Territories / Kowloon contiguous landmass
- Lantau
- Hong Kong Island
- Chek Lap Kok airport island
- Tsing Yi
- High Island
- Ap Lei Chau
- Ma Wan

Disconnected outlying islands such as Lamma, Cheung Chau, Peng Chau, Po Toi,
Tap Mun, and other small islands are retained in the component inventory but
excluded from the dissolved traffic-model boundary.

This is a boundary-only fixed-link classification. When an official Hong Kong
road centreline or bridge/tunnel inventory is added, the fixed-link whitelist
should be checked against that network layer.

## Outputs

```text
data/boundary/hongkong/processed/hong_kong_fixed_link_boundary.geojson
data/boundary/hongkong/processed/hong_kong_fixed_link_boundary_wgs84.geojson
data/boundary/hongkong/processed/hong_kong_fixed_link_boundary_wgs84_simplified.geojson
data/boundary/hongkong/processed/hong_kong_boundary_components.geojson
data/boundary/hongkong/processed/hong_kong_fixed_link_boundary.gpkg
data/boundary/hongkong/processed/hong_kong_boundary_preparation_summary.json
data/boundary/hongkong/processed/hong_kong_fixed_link_boundary_preview.png
```

Current QA summary:

```text
source components:    217
retained components:  8
excluded components:  209
retained area:        1060.145 km2
excluded area:        50.143 km2
```

Use `hong_kong_fixed_link_boundary.geojson` for Hong Kong 1980 Grid workflows
and `hong_kong_fixed_link_boundary_wgs84.geojson` for web maps or APIs that
expect longitude/latitude.
