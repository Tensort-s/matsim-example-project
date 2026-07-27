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
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\feature_engineering\prepare_hong_kong_lsug_calibration_inputs.py
```

Formal WEDAN inference and LSUG calibration run on the laboratory server under
`/home/by/OD/HK`. They require one CUDA GPU and never fall back to CPU. See the
server commands in `scripts/hong_kong_single_city/README.md`.

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

## LSUG/grid resolution diagnostics

The LSUG layer provides three geographically assignable workplace totals for
each residential LSUG: `plw_hk`, `plw_kln`, and `plw_nt`. The combined
`plw_oth` field is excluded because it includes no fixed workplace, marine,
work at home, and workplaces outside Hong Kong.

Run the population-weighted zoning diagnostic with:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\feature_engineering\analyze_hong_kong_lsug_grid_resolution.py
```

The script rasterizes LSUG and grid membership on the calibrated WorldPop
raster, builds a sparse population crosswalk, allocates observed LSUG flows to
grids, and reconstructs them back to LSUG. The resulting residual measures the
origin-side information lost when each grid is treated as homogeneous.

Current-grid results:

```text
LSUG geometries:                                  1,746
Represented LSUGs:                                1,670
Primary LSUGs with >=90% modeled population:      1,657
Grid cells / populated grid cells:          1,585 / 1,543
Median significant LSUGs per populated grid:          2
P90 significant LSUGs per populated grid:             6
Population-weighted median dominant LSUG share:   28.28%
Population in grids with dominant LSUG <50%:      78.85%
Round-trip worker-weighted destination-share MAE:  3.77 percentage points
Round-trip OD-cell WAPE:                           14.45%
```

Diagnostic candidate comparison:

| Cell size | Grid count | Weighted share MAE | Cell WAPE |
|---:|---:|---:|---:|
| 920.659 m | 1,585 | 3.769 pp | 14.454% |
| 750 m | 2,326 | 3.483 pp | 13.393% |
| 700 m | 2,645 | 3.437 pp | 13.321% |

The 700 m candidate remains below WEDAN's 3,000-node setting but reduces share
MAE by only `0.332` percentage points (`8.8%`) and WAPE by only `1.13`
percentage points. The current 920.659 m grid is therefore retained. LSUG
supervision should be transferred through the population crosswalk rather than
rebuilding all population, POI, image, distance, and OD products at a finer
resolution.

Outputs are under:

```text
data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/census_2021_commute_constraints/lsug_grid_resolution_diagnostics/
```

The diagnostic does not validate the WEDAN feature scalers and cannot identify
destination-grid allocation within Hong Kong Island, Kowloon, or the New
Territories. Those are handled by the scaler comparison and LSUG calibration
workflow below.

## Hong Kong scaler comparison and LSUG calibration

The current formal experiment freezes `model_666_best.pkl` and removes both
the Fuzhou feature scaler and Fuzhou off-diagonal OD quantile mapping. It tests
three Hong Kong feature scalers with seeds `666`, `667`, and `668`; every run
uses 10 DDIM samples and 25 steps. The signed WEDAN output is converted to a
positive, unit-free base score with:

```text
z = clip((raw - offdiag_median) / offdiag_IQR, -8, 8)
base_score = softplus(z)
```

The 18-parameter calibration layer contains 12 residence-area/workplace-area
intercepts and 6 population/working-age slopes. It is trained against the
1,657 LSUGs with at least 90% population coverage. Model selection uses
18-district leave-one-district-out validation and excludes training LSUGs that
share a grid carrying at least 10% of a held-out LSUG's population.

Formal scaler comparison:

| Scaler | Baseline share MAE | Calibrated share MAE | Improvement | Improved districts | Cell WAPE |
|---|---:|---:|---:|---:|---:|
| `local_minmax` | 29.173 pp | 7.508 pp | 74.26% | 18/18 | 30.63% |
| `group_robust` | 30.357 pp | 7.856 pp | 74.12% | 18/18 | 31.00% |
| `feature_robust` | 30.297 pp | 8.000 pp | 73.59% | 18/18 | 32.34% |

`local_minmax` is selected. Its three-seed standard deviation in calibrated
share MAE is `0.0149` percentage points. The historical Fuzhou-quantile result
has a primary-LSUG share MAE of `34.187` percentage points and cell WAPE of
`142.60%`; it is retained only as a baseline and is not used by new outputs.

The separate population-crosswalk-weighted 4-residence-area by
3-workplace-area check also passes the replacement gate:

```text
historical Fuzhou-quantile 4x3 share MAE:  8.970 pp
selected spatial-OOF 4x3 share MAE:        0.258 pp
final generalized 4x3 share MAE:           0.272 pp
```

The 4x3 gate uses the out-of-fold prediction, so it cannot pass merely because
the final calibrator was fitted on all LSUGs.

The selected full-data calibrator produces:

```text
generalized primary-LSUG share MAE:             7.103 pp
generalized primary-LSUG cell WAPE:             28.23%
Census-projected represented-LSUG share MAE:     3.938 pp
Census-projected represented-LSUG cell WAPE:     19.11%
```

The Census-projected latent allocation matches `2,610,596.073` workers before
grid compression. Its remaining round-trip error is caused by LSUG/grid mixing
and is reported rather than hidden.

Outputs:

```text
data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/
  CommutingODFlows/hong_kong_fixed_link_grid/hk_scaler_calibration_v1/
    scaler_runs/{scaler}/seed_{seed}/
      raw_normalized.npy
      positive_base_score.npy
      scaler_metadata.json
      run_summary.json
    final/
      generation_hk_generalized.npy
      generation_hk_census_projected.npy
      calibrator_parameters.json
      lsug_validation_predictions.csv
      district_cv_metrics.csv
      scaler_comparison.csv
      calibration_summary.json
      calibration_diagnostics.png
```

All nine inference runs used physical GPU 3 only. Their maximum recorded
reserved memory was `2.613 GiB`, below the hard `10 GiB` limit. The calibrator
also records `cpu_fallback=false`, `fuzhou_quantile_used_in_new_outputs=false`,
and both LSUGx3 and 4x3 historical-baseline improvement gates.

Use `generation_hk_generalized.npy` when testing spatial generalization without
forcing each LSUG target. Use `generation_hk_census_projected.npy` when a
Census-constrained 2021 fixed-workplace demand is required for downstream
MATSim demand construction.

District-level comparison maps and bars are generated by:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\analysis_visualization\visualize_hong_kong_district_lsug3_metrics.py
```

The comparison uses the same 1,657 primary LSUGs for both methods and writes
two shared-scale choropleth PNGs, one grouped-bar PNG, and the underlying
18-district metric CSV under `final/district_lsug3_metrics/`.

Static flow maps for the Census-projected OD are generated by:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\analysis_visualization\visualize_hong_kong_census_od_flow_maps.py
```

The script writes a top-grid-flow straight-line PNG, an 18-district directed
flow PNG, the district OD matrix, selected-flow audit CSVs, and a summary JSON
under `final/flow_maps/`. Line or arrow width encodes flow; only the largest
links are drawn to keep the static maps legible.
