# Hong Kong Esri World Imagery preparation

This document records the Esri World Imagery product downloaded for Hong Kong
WEDAN / RemoteCLIP feature generation.

## Source and boundary

Imagery source:

```text
Esri World Imagery XYZ tiles
https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}
```

Boundary:

```text
data/boundary/hongkong/processed/hong_kong_fixed_link_boundary_wgs84.geojson
```

This is the fixed-link Hong Kong model boundary prepared from the 2021 Census
District Council polygons. It excludes disconnected outlying islands without
road, bridge, tunnel, or dam access. See:

```text
docs/HONG_KONG_BOUNDARY_PREPARATION.md
```

## Script

Canonical script:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\data_acquisition\download_hong_kong_esri_world_imagery.py
```

Dry-run tile coverage check:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\data_acquisition\download_hong_kong_esri_world_imagery.py --dry-run
```

The default zoom is `z14`, matching the current Fuzhou imagery workflow. At
Hong Kong's latitude this gives about `9.55 m/pixel` in Web Mercator and about
`8.83 m/pixel` after reprojection to EPSG:32650.

## Output data

Main directory:

```text
data/imagery/hongkong/esri_world_imagery/fixed_link_boundary/
```

Key outputs:

```text
tiles/14/*/*.jpg
tile_manifest_z14.json
hong_kong_fixed_link_esri_world_imagery_z14_mosaic_epsg3857.tif
hong_kong_fixed_link_esri_world_imagery_z14_clip_epsg3857.tif
hong_kong_fixed_link_esri_world_imagery_z14_clip_epsg32650.tif
hong_kong_fixed_link_esri_world_imagery_z14_preview.png
hong_kong_fixed_link_esri_world_imagery_z14_metadata.json
```

The EPSG:32650 clipped file is the preferred image input for local GIS and
RemoteCLIP region-crop feature extraction.

## Current QA

Current checked run:

```text
zoom:                         14
downloaded or cached tiles:   513
tile x range:                 13372 - 13398
tile y range:                 7137 - 7155
boundary lon/lat bounds:      113.8391616, 22.1941236, 114.4056738, 22.5619403
```

Mosaic:

```text
CRS:          EPSG:3857
size:         6912 x 4864
```

Boundary-clipped Web Mercator image:

```text
CRS:          EPSG:3857
size:         6601 x 4635
resolution:   9.5546 m
```

Boundary-clipped projected image:

```text
CRS:          EPSG:32650
size:         6701 x 4743
resolution:   8.8287 m
```

The preview image has been visually checked and shows nonblank Esri imagery
inside the fixed-link Hong Kong boundary, with nodata outside the boundary.

## Notes for WEDAN

For Hong Kong WEDAN feature generation, use the projected clipped image:

```text
data/imagery/hongkong/esri_world_imagery/fixed_link_boundary/hong_kong_fixed_link_esri_world_imagery_z14_clip_epsg32650.tif
```

The next step is to define the Hong Kong `regions.shp` used by WEDAN, then crop
this image by each region and extract RemoteCLIP image embeddings in the same
order as the region file.

Respect Esri/ArcGIS terms of use when redistributing the raw or derived imagery.
