# Hong Kong single-city scripts

These scripts are the Hong Kong-specific workflow scripts. Hong Kong should be
handled as an official-data-first city workflow rather than a direct copy of
the Fuzhou AMap/OSM-heavy workflow.

## Directory guide

- `data_preparation/`
  Boundary and other city-level geospatial preparation products.

- `data_acquisition/`
  Downloading or collecting public source data such as WorldPop and official
  Hong Kong open datasets.

- `feature_engineering/`
  WEDAN-compatible regions, raster/vector feature aggregation, image features,
  and distance matrices.

- `analysis_visualization/`
  Diagnostic maps and comparison tables for checking intermediate products.

## Current scripts

Prepare the fixed-link administrative boundary:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\data_preparation\prepare_hong_kong_boundary.py
```

Download and clip WorldPop population plus age/sex rasters:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\data_acquisition\download_hong_kong_age_sex_population_from_worldpop.py
```

Download and clip Esri World Imagery for the fixed-link model boundary:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\data_acquisition\download_hong_kong_esri_world_imagery.py
```

Download and extract OSM POIs for the fixed-link model boundary:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\data_acquisition\download_hong_kong_osm_pois.py
```

Calibrate the clipped WorldPop raster to 2021 Census Large Subunit Group totals:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\data_preparation\calibrate_hong_kong_worldpop_to_lsug.py
```

Merge 2026 iGeoCom and OSM POIs into a modeling-ready integrated POI layer:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\data_preparation\merge_hong_kong_igeocom_osm_pois.py
```

Build the WEDAN-compatible fixed-link regular grid:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\feature_engineering\build_hong_kong_fixed_link_grid.py
```

Build the fixed-link grid centroid distance matrix:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\feature_engineering\build_hong_kong_grid_dis_matrix.py
```

Build WEDAN population and age/sex features:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\feature_engineering\build_hong_kong_population_features.py
```

Build WEDAN POI features from the integrated iGeoCom + OSM POI layer:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\feature_engineering\build_hong_kong_integrated_pois_features.py
```

Build WEDAN RemoteCLIP image features from Esri imagery:

```powershell
.\.venv_wedan\Scripts\python.exe .\scripts\hong_kong_single_city\feature_engineering\build_hong_kong_remoteclip_imgfeat.py --batch-size 16 --device cpu
```

Prepare the compact LSUG calibration inputs locally:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\feature_engineering\prepare_hong_kong_lsug_calibration_inputs.py
```

Run the formal Hong Kong WEDAN scaler experiment on the laboratory server.
The runner requires CUDA, exposes one GPU only, enforces a 10 GiB limit, and
stops instead of falling back to CPU:

```bash
cd /home/by/OD/HK
env DGLDEFAULTDIR=/home/by/OD/HK/.cache/dgl DGLBACKEND=pytorch \
  /home/by/OD/HK/.venv_wedan_gpu/bin/python \
  scripts/hong_kong_single_city/feature_engineering/run_hong_kong_wedan_scaler_experiments.py \
  --physical-gpu-id 3 --gpu-memory-limit-gib 10
```

Fit and cross-validate the 18-parameter LSUG calibration layer after all nine
scaler/seed runs are complete:

```bash
cd /home/by/OD/HK
env CUDA_VISIBLE_DEVICES=3 DGLDEFAULTDIR=/home/by/OD/HK/.cache/dgl DGLBACKEND=pytorch \
  /home/by/OD/HK/.venv_wedan_gpu/bin/python \
  scripts/hong_kong_single_city/feature_engineering/train_hong_kong_lsug_calibrator.py \
  --gpu-memory-limit-gib 10
```

The single-run entry point now requires `--feature-scaling` and `--seed`. It
saves signed normalized output and a positive rank-preserving base score; it
does not read Fuzhou feature scalers or apply Fuzhou OD quantile mapping.

Extract 2021 Census commute tables 7.8 and 7.9 from the Census summary PDF:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\data_preparation\extract_hong_kong_2021_census_commute_tables.py
```

Validate Hong Kong WEDAN OD against the 2021 Census fixed-workplace commute
tables and infer the global flow unit:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\feature_engineering\validate_hong_kong_wedan_od_with_census_commute.py
```

Measure LSUG/grid population mixing, LSUG commute-flow reconstruction loss,
and compare the current grid with diagnostic 750 m and 700 m candidates:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\feature_engineering\analyze_hong_kong_lsug_grid_resolution.py
```

Visualize raw WorldPop, calibrated WorldPop, and district-level Census targets:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\analysis_visualization\visualize_worldpop_calibration.py
```

Visualize WEDAN OD flows on the Hong Kong fixed-link boundary:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\analysis_visualization\visualize_hong_kong_wedan_od_flows.py --top-k 800 --html-top-k 300
```

The old `scripts/hongkong/...` path is kept only as a compatibility wrapper.
