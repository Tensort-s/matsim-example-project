# Hong Kong fixed-link regular grid

This document records the WEDAN-compatible regular grid generated for the Hong
Kong fixed-link model boundary.

## Source boundary

Boundary file:

```text
data/boundary/hongkong/processed/hong_kong_fixed_link_boundary_wgs84.geojson
```

This boundary is derived from the 2021 Census District Council polygons and
excludes disconnected outlying islands without road, bridge, tunnel, or dam
access. See:

```text
docs/HONG_KONG_BOUNDARY_PREPARATION.md
```

## Script

Canonical command:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\feature_engineering\build_hong_kong_fixed_link_grid.py
```

The default cell size is `920.658900389797 m`, matching the grid scale inferred
from the Fuzhou WorldOD reference regions. Grid generation uses `EPSG:32650`,
the fixed-link boundary lower-left as the origin, and drops clipped fragments
smaller than `1 m2`.

## Output data

Main directory:

```text
data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/
```

Key outputs:

```text
CityAndRegionSplit/hong_kong_fixed_link_grid/regions.shp
CityAndRegionSplit/hong_kong_fixed_link_grid/regions.geojson
CityAndRegionSplit/hong_kong_fixed_link_grid/regions.png
CityAndRegionSplit/hong_kong_fixed_link_grid/grid_generation_summary.json
```

The `regions.shp` fields are compatible with the Fuzhou grid workflow:

```text
grid_id, locations, col, row, area_m2, area_km2, geometry
```

Rows are sorted by `col,row`, and `grid_id` is a contiguous zero-based row
index. The `locations` field uses `{col}-{row}`.

## Current QA

Current checked run:

```text
CRS:                         EPSG:32650
cell size:                   920.658900389797 m
grid count:                  1,585
boundary area:               1,061.581988727 km2
grid area sum:               1,061.581988597 km2
grid minus boundary area:    -0.000000130 km2
empty geometries:            0
invalid geometries:          0
contiguous grid_id:          yes
unique locations:            yes
```

The preview image has been visually checked and shows complete coverage of the
fixed-link Hong Kong boundary, including Hong Kong Island, Kowloon, New
Territories, Lantau, Chek Lap Kok airport, Tsing Yi, Ma Wan, High Island, and
Ap Lei Chau.

## Notes for WEDAN

This step only creates the analysis regions. It does not create:

```text
worldpop.npy
demos.npy
pois.npy
imgfeat.npy
dis.npy
generation.npy
```

Recommended next steps:

1. Aggregate the calibrated Hong Kong WorldPop raster to this `regions.shp` to
   create `worldpop.npy` and `demos.npy`.
2. Crop the Hong Kong Esri World Imagery product by each grid cell and extract
   RemoteCLIP image embeddings.
3. Build POI features and centroid distance matrix with row order matching
   `regions.shp`.

## Distance matrix

The centroid-to-centroid straight-line distance matrix for this grid is
generated with:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\feature_engineering\build_hong_kong_grid_dis_matrix.py
```

Outputs:

```text
data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/GeneratingCodeData/data/global_cities/hong_kong_fixed_link_grid/adj/dis.npy
data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/GeneratingCodeData/data/global_cities/hong_kong_fixed_link_grid/adj/grid_centroids.csv
data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/GeneratingCodeData/data/global_cities/hong_kong_fixed_link_grid/adj/dis_matrix_sample_20x20.csv
data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/GeneratingCodeData/data/global_cities/hong_kong_fixed_link_grid/adj/dis_generation_summary.json
```

Current distance matrix QA:

```text
shape:                       1,585 x 1,585
dtype:                       float32
unit:                        m
distance CRS:                EPSG:32650
min nonzero distance:        38.156 m
max distance:                62,789.617 m
mean non-diagonal distance:  21,520.258 m
symmetric:                   yes
diagonal max abs:            0
finite values:               yes
negative values:             0
```

Rows and columns follow the current `regions.shp` row order.
