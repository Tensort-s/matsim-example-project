# Hong Kong WEDAN inputs and OD inference

This document records the Hong Kong fixed-link WEDAN feature preparation and
OD inference workflow. It follows the current Fuzhou custom-grid workflow while
using Hong Kong official-data-first inputs.

## Inputs

Grid:

```text
data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/CityAndRegionSplit/hong_kong_fixed_link_grid/regions.shp
```

Population:

```text
data/gee/hongkong/worldpop_age_sex/census_calibrated/worldpop_HKG_2021_census_lsug_calibrated_fixed_link_boundary.tif
data/gee/hongkong/worldpop_age_sex/worldpop_age_sex_bands.json
```

POI:

```text
data/osm/hongkong/fixed_link_boundary/integrated_pois/hong_kong_fixed_link_integrated_pois.geojson
```

Imagery:

```text
data/imagery/hongkong/esri_world_imagery/fixed_link_boundary/hong_kong_fixed_link_esri_world_imagery_z14_clip_epsg32650.tif
```

Distance matrix:

```text
data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/GeneratingCodeData/data/global_cities/hong_kong_fixed_link_grid/adj/dis.npy
```

## Commands

Run from the project root:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\feature_engineering\build_hong_kong_population_features.py
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\feature_engineering\build_hong_kong_integrated_pois_features.py
.\.venv_wedan\Scripts\python.exe .\scripts\hong_kong_single_city\feature_engineering\build_hong_kong_remoteclip_imgfeat.py --batch-size 16 --device cpu
.\.venv_wedan\Scripts\python.exe .\scripts\hong_kong_single_city\feature_engineering\run_hong_kong_wedan_inference.py --sample-times 10 --ddim-steps 25 --device cpu
```

The WEDAN inference script sets `DGLDEFAULTDIR` to the project-local
`.cache/dgl` directory so DGL does not need to write to the Windows user home.

## Feature outputs

All WEDAN input features are written under:

```text
data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/GeneratingCodeData/data/global_cities/hong_kong_fixed_link_grid/
```

Expected files:

```text
nfeat/worldpop.npy  (1585, 2)
nfeat/demos.npy     (1585, 36)
nfeat/pois.npy      (1585, 34)
nfeat/imgfeat.npy   (1585, 1024)
adj/dis.npy         (1585, 1585)
```

The final node feature dimension used by WEDAN is:

```text
2 + 36 + 34 + 1024 = 1096
```

## OD outputs

The Hong Kong OD prediction is written to:

```text
data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/CommutingODFlows/hong_kong_fixed_link_grid/
```

Expected files:

```text
generation_raw_normalized.npy
generation.npy
generation.csv
generation.png
generation_summary.json
```

Current run:

```text
generation.npy: (1585, 1585)
sample_times:   10
ddim_steps:     25
device:         cpu
sum:            366,113,140 (float64 sum; float32 quick sum may report 366,113,408)
nonzero OD:     2,492,905
max flow:       917
diagonal sum:   0
```

## OD flow visualization

The OD flow map is generated with:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\analysis_visualization\visualize_hong_kong_wedan_od_flows.py --top-k 800 --html-top-k 300
```

Main outputs:

```text
data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/CommutingODFlows/hong_kong_fixed_link_grid/visualization/hong_kong_wedan_od_top_flows.png
data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/CommutingODFlows/hong_kong_fixed_link_grid/visualization/hong_kong_wedan_od_top_flows.geojson
data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/CommutingODFlows/hong_kong_fixed_link_grid/visualization/hong_kong_wedan_od_top_flows.csv
data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/CommutingODFlows/hong_kong_fixed_link_grid/visualization/hong_kong_wedan_od_grid_totals.csv
```

The current static map draws the top `800` OD pairs. These flows range from
`729` to `917` trips and sum to `607,602`; the filter keeps the city-scale map
legible instead of drawing all `2,492,905` nonzero OD pairs.

## Calibration note

The local project contains the WEDAN checkpoint:

```text
data/worldcommuting_od/_shared/GeneratingCodeData/exp/model/US2world/model_666_best.pkl
```

It does not contain the original US training-data scalers used by the released
training script. Therefore the Hong Kong inference script follows the current
Fuzhou custom-grid inference approach:

1. Save `generation_raw_normalized.npy`, the direct model output in normalized
   model space.
2. Save `generation.npy`, a count-like matrix produced by off-diagonal quantile
   mapping to the downloaded WorldOD Fuzhou reference OD distribution.

The calibrated Hong Kong matrix preserves the model's OD ranking structure but
uses the reference Fuzhou OD distribution for numerical scale. If Hong Kong
official commuting totals or an external OD target become available, this step
should be recalibrated.

## 2021 Census commute validation

The 2021 Census Summary Results PDF has been used to extract:

```text
Table 7.9: fixed-workplace working population by main mode of transport and area of residence
Table 7.8: working population by place of work and area of residence
```

Run:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\data_preparation\extract_hong_kong_2021_census_commute_tables.py
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\feature_engineering\validate_hong_kong_wedan_od_with_census_commute.py
```

Main outputs:

```text
data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/census_2021_commute_constraints/table_7_9_commute_mode_by_residence.csv
data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/census_2021_commute_constraints/table_7_8_workplace_by_residence.csv
data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/census_2021_commute_constraints/census_2021_area_od_target_4area.csv
data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/census_2021_commute_constraints/grid_2021_census_4area_assignment.csv
data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/census_2021_commute_constraints/wedan_original_vs_census_area_od_4area.csv
data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/census_2021_commute_constraints/wedan_original_vs_census_origin_margins_4area.csv
data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/census_2021_commute_constraints/wedan_original_vs_census_destination_margins_4area.csv
data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/census_2021_commute_constraints/census_2021_mode_share_by_residence_4area.csv
data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/census_2021_commute_constraints/generation_2021_census_global_unit_scaled.npy
data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/census_2021_commute_constraints/wedan_flow_unit_inference_summary.json
```

Current table QA:

```text
Table 7.9 fixed-workplace total: 2,659,558
MTR local line total:            1,150,100
Bus total:                         663,685
Table 7.8 4-area OD total:       2,659,558
4-area residence margins:        444,210 / 779,073 / 1,294,397 / 141,878
```

The validation keeps the official 4-area Census categories:

```text
Hong Kong Island / Kowloon / New towns / Other areas in the New Territories and Marine
```

Grid areas are assigned with the District Council boundary plus the official
2021 New Town boundary:

```text
data/boundary/hongkong/Boundaries_of_New_Towns_for_2021_Population_C_SHP/NewTown_2021.shp
```

The current grid assignment contains:

```text
Hong Kong Island: 134 grids
Kowloon:           70 grids
New towns:        320 grids
Other NT/Marine: 1061 grids
```

The Census tables are now used for validation and unit inference, not for
silently replacing the model result. Table 7.8 gives the 4-area
residence-to-workplace target shares. Table 7.9 gives the matching fixed
workplace total and residence-area mode split. The inferred global unit is:

```text
1 WEDAN unit = 0.007264306 workers
1 worker     = 137.659 WEDAN units
```

`generation_2021_census_global_unit_scaled.npy` applies only this global unit
factor and preserves WEDAN's original OD proportions. It is useful for magnitude
inspection, but it is not an area-corrected OD.

Current 4-area share validation indicates that the original WEDAN OD spatial
proportions do not match the Census target well:

```text
16-block share MAE:       0.093108
16-block share RMSE:      0.118821
Total variation distance: 0.744861
Jensen-Shannon divergence: 0.346118
```

The largest block error is `other_nt_marine -> other_nt_marine`: after applying
only the global unit, WEDAN implies about `856,109` workers against the Census
target `23,859`. Origin and destination margins show the same issue: WEDAN
overweights `Other NT/Marine` and underweights Hong Kong Island, Kowloon, and
New towns. This supports treating the current WEDAN result as a diagnostic
baseline rather than a final Hong Kong commuting demand.
