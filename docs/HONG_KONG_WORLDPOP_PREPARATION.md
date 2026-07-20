# Hong Kong WorldPop age-sex population preparation

This document records the Hong Kong WorldPop data product used for future
WEDAN feature generation and synthetic population work.

## Source and boundary

The downloader uses the public WorldPop static GeoTIFF repository for Hong Kong
2020 population and age/sex rasters:

```text
https://data.worldpop.org/GIS/Population/Global_2000_2020/2020/HKG/
https://data.worldpop.org/GIS/AgeSex_structures/Global_2000_2020/2020/HKG/
```

The rasters are clipped to the fixed-link Hong Kong model boundary prepared in:

```text
data/boundary/hongkong/processed/hong_kong_fixed_link_boundary_wgs84.geojson
```

That boundary excludes disconnected outlying islands without fixed road, bridge,
tunnel, or dam access. See `docs/HONG_KONG_BOUNDARY_PREPARATION.md`.

## Script

Canonical script:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\data_acquisition\download_hong_kong_age_sex_population_from_worldpop.py
```

Compatibility wrapper retained for the older path:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hongkong\data_acquisition\download_hongkong_age_sex_population_from_worldpop.py
```

The script downloads the raw WorldPop files when missing and writes a clipped
multi-band GeoTIFF plus metadata files. It does not require Google Earth Engine.

## Output data

Main directory:

```text
data/gee/hongkong/worldpop_age_sex/
```

Key outputs:

```text
raw_worldpop/*.tif
worldpop_HKG_2020_pop_age_sex_hong_kong_fixed_link_boundary.tif
worldpop_HKG_2020_pop_age_sex_hong_kong_fixed_link_boundary.metadata.json
worldpop_age_sex_bands.json
worldpop_age_sex_summary.json
```

The clipped GeoTIFF has 37 bands:

```text
population,
M_0, M_1, M_5, M_10, M_15, M_20, M_25, M_30, M_35, M_40, M_45, M_50, M_55, M_60, M_65, M_70, M_75, M_80,
F_0, F_1, F_5, F_10, F_15, F_20, F_25, F_30, F_35, F_40, F_45, F_50, F_55, F_60, F_65, F_70, F_75, F_80
```

## QA result

Current checked file:

```text
data/gee/hongkong/worldpop_age_sex/worldpop_HKG_2020_pop_age_sex_hong_kong_fixed_link_boundary.tif
```

QA summary:

```text
raw GeoTIFF count:        37
clipped band count:      37
shape:                   37 x 442 x 681
CRS:                     WGS84 lon/lat
nodata:                  0
finite values:           yes
negative values:         0
population sum:          7,251,941.224
male age-sex sum:        3,402,355.173
female age-sex sum:      3,849,586.031
age-sex total mismatch:  0.020 persons
```

The age/sex total mismatch is floating point noise. The population value is for
the fixed-link model boundary, not all Census territory including disconnected
outlying islands.

## Notes for WEDAN

For WEDAN, this raster is an intermediate source. It still needs to be
aggregated to the chosen Hong Kong analysis regions or grid to produce:

```text
nfeat/worldpop.npy
nfeat/demos.npy
```

Recommended next step:

1. Choose or generate `regions.shp` inside the fixed-link boundary.
2. Sum `population` per region for population intensity.
3. Sum and normalize `M_*` / `F_*` bands per region for age/sex structure.
4. Compare regional totals against official 2021 Census tables before using
   the features for OD scale calibration.

## 2021 Census LSUG calibration

The WorldPop raster has also been calibrated against the 2021 Population Census
Large Subunit Group dataset:

```text
data/gee/hongkong/worldpop_age_sex/2021_Population_Census_Statistics_ LargeSubunitGroups/LSUG_21C_converted.shp
```

The data specification used to confirm field meanings is:

```text
D:\Program Files\Simplified Data Specifications (English) Population Distribution_v1.1 (1).pdf
```

The relevant LSUG fields are:

| Field | Meaning |
|---|---|
| `t_pop` | Total population |
| `pop_m` | Male population |
| `pop_f` | Female population |
| `age_1` | Population aged under 15 |
| `age_2` | Population aged 15-24 |
| `age_3` | Population aged 25-44 |
| `age_4` | Population aged 45-64 |
| `age_5` | Population aged 65 and over |

Calibration script:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\data_preparation\calibrate_hong_kong_worldpop_to_lsug.py
```

Method:

1. Read the clipped WorldPop raster and the 2021 Census LSUG polygons.
2. Area-weight each LSUG Census target by its overlap with the fixed-link model
   boundary.
3. Rasterize LSUGs to the WorldPop grid using cell-centre assignment.
4. For small LSUGs with no cell centre, assign the nearest touched positive
   WorldPop cell.
5. Within each LSUG, use iterative proportional fitting to match the available
   Census margins: male/female totals and five broad age groups.
6. Recompute the population band as the sum of calibrated age-sex bands.

WorldPop age bands are mapped to Census age groups as:

| Census group | WorldPop bands |
|---|---|
| `age_1`, under 15 | `0`, `1`, `5`, `10` |
| `age_2`, 15-24 | `15`, `20` |
| `age_3`, 25-44 | `25`, `30`, `35`, `40` |
| `age_4`, 45-64 | `45`, `50`, `55`, `60` |
| `age_5`, 65+ | `65`, `70`, `75`, `80` |

Outputs:

```text
data/gee/hongkong/worldpop_age_sex/census_calibrated/worldpop_HKG_2021_census_lsug_calibrated_fixed_link_boundary.tif
data/gee/hongkong/worldpop_age_sex/census_calibrated/worldpop_HKG_2021_census_lsug_calibration_qa.csv
data/gee/hongkong/worldpop_age_sex/census_calibrated/worldpop_HKG_2021_census_lsug_calibration_summary.json
```

Current QA:

```text
LSUG records:                         1,746
area-weighted fixed-link target:      7,374,262.779
calibrated LSUG records:              1,717
skipped no-positive-pixel LSUGs:      29
skipped weighted target population:   21,954.000
calibrated raster population:         7,352,308.774
calibrated age-sex total:             7,352,308.778
negative values:                      0
uncovered positive pixels:            0
```

For calibrated LSUGs, the maximum absolute mismatch against the area-weighted
Census targets is less than `0.002` persons for total population, male/female
population, and all five age groups. The remaining difference from the
area-weighted fixed-link target comes from 29 very small LSUGs that still have
no positive WorldPop raster cell at the 3-arc-second grid resolution.

## District-level visualization

The raw WorldPop, calibrated WorldPop, and 2021 Census LSUG target populations
can be compared at District Council district level with:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\analysis_visualization\visualize_worldpop_calibration.py
```

This writes:

```text
data/gee/hongkong/worldpop_age_sex/census_calibrated/hong_kong_worldpop_calibration_district_comparison.csv
data/gee/hongkong/worldpop_age_sex/census_calibrated/hong_kong_worldpop_calibration_district_comparison.png
```

Current district-level totals are:

```text
raw WorldPop 2020:              7,251,941.224
census-calibrated WorldPop:     7,352,308.774
2021 Census LSUG target:        7,374,262.779
```

The target is the LSUG population area-weighted to the fixed-link model
boundary and aggregated to District Council districts. The calibrated raster is
lower by about `21,954` people because those 29 no-positive-pixel LSUGs cannot
be represented on the WorldPop grid without inventing new populated raster
cells.

## Related Census file in the same folder

The folder currently also contains:

```text
SSUG_21C.zip
SSUG_21C/SSUG_21C.csv
```

This appears to be a 2021 Census Small Subunit Group table, not a WorldPop
raster source. It is useful for later official-population calibration, but it is
not part of the WorldPop download chain. The CSV is encoded as Big5/CP950, not
UTF-8, so read it explicitly, for example:

```python
pd.read_csv("SSUG_21C.csv", encoding="big5")
```
