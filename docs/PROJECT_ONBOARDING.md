# Project onboarding for future Codex sessions

This document is the first project overview to read after the repository-level
`AGENTS.md`. It records the current Fuzhou and Hong Kong workflows after the
multi-city data layout migration.

Project rule for future work: whenever new code, scripts, configs, data products, or modeling features are added,
update the most relevant Markdown document in the same change; if no suitable document exists, create a new one and
link it from this onboarding file or another appropriate index.

Markdown encoding rule: all project-owned Markdown files are UTF-8. On Windows, if Chinese text appears garbled in a
terminal, read files explicitly as UTF-8 instead of assuming the document is corrupt:

```powershell
Get-Content -Encoding UTF8 .\docs\PROJECT_ONBOARDING.md
```

For Python-based readers, always use `encoding="utf-8"` when opening project Markdown files.

## PowerShell operating rules

The integrated terminal and the Codex agent command runner are separate shell environments. The integrated/manual
terminal is expected to use PowerShell 7.6.3.

Recommended PowerShell 7 profile (`$PROFILE`) encoding snippet:

```powershell
chcp 65001 > $null
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
```

Operational defaults:

- Prefer explicit project interpreters over bare `python`:
  - `.venv_geo311\Scripts\python.exe` for GIS, data processing, MATSim preprocessing, PDF, SimWrapper, and Kepler.
  - `.venv_wedan\Scripts\python.exe` only for WEDAN / WorldCommuting-OD / RemoteCLIP.
- Prefer `rg -F -- "literal text"` for simple searches.
- For complex searches involving Chinese text, backslashes, quotes, or many alternatives, use `Select-String -SimpleMatch`
  or a small Python script instead of a long PowerShell regex.
- If Maven Wrapper needs `C:\Users\Yu Boyang\.m2\wrapper\dists`, or Git needs `C:\Users\Yu Boyang\.ssh\config`, Codex may
  need elevated permission. Do not assume Maven or SSH is broken just because the sandbox cannot read those paths.
- If Codex agent command execution reports `CreateProcessAsUserW failed: 5` while launching
  `C:\Users\Yu Boyang\AppData\Local\Microsoft\WindowsApps\pwsh.exe`, it is the WindowsApps app-execution alias being
  blocked by the sandbox. That is a Codex runner issue, not an integrated-terminal issue.
- Turning off the `pwsh.exe` App Execution Alias can restore Codex shell startup by letting the runner fall back to a
  different shell, but it may also remove `pwsh` from PATH for manual terminals.

## Current project shape

- Project root: `F:\Matsim\matsim-example-project`
- Java/MATSim build: Maven project, Java 25, core build file `pom.xml`
- Geospatial Python environment: `.venv_geo311`
- WEDAN/ML environment: `.venv_wedan`
- City packages: `cities/fuzhou/city.yaml` and `cities/hongkong/city.yaml`
- Fuzhou final run: `runs/fuzhou/outputs/waitpenalty-metroprefer-from-cont20-reroute50`
- Hong Kong final local visualization:
  `runs/hongkong/outputs/formal_50it_ptfixed_ferry_activity_simwrapper`

The Hong Kong workflow is operational through OD generation, road and public
transport supply, 5% multi-activity agents, a completed 50-iteration
simulation, and SimWrapper/particle visualization. Treat these files as its
entry-point source of truth:

```text
docs/HONG_KONG_FINAL_WORKFLOW.md
cities/hongkong/city.yaml
runs/hongkong/run_manifest.json
scripts/hong_kong_single_city/README.md
```

Detailed provenance documents include:

```text
docs/HONG_KONG_BOUNDARY_PREPARATION.md
docs/HONG_KONG_WORLDPOP_PREPARATION.md
docs/HONG_KONG_ESRI_WORLD_IMAGERY.md
docs/HONG_KONG_FIXED_LINK_GRID.md
docs/HONG_KONG_OSM_POIS.md
docs/HONG_KONG_INTEGRATED_POIS.md
docs/HONG_KONG_WEDAN_INPUTS_AND_INFERENCE.md
docs/HONG_KONG_STUDENT_SCHOOL_OD.md
docs/HONG_KONG_MATSIM_PUBLIC_TRANSPORT_DATA.md
docs/HONG_KONG_MATSIM_AGENTS_5PCT.md
docs/HONG_KONG_TAXI_INITIAL_PLAN_AUDIT.md
docs/HONG_KONG_TAXI_FARE_MODEL.md
docs/HONG_KONG_TAXI_UTILITY_DESIGN.md
docs/HONG_KONG_CAR_COST_MODEL.md
```

When a historical command or path conflicts with the Hong Kong final workflow,
city metadata, or run manifest, use the final workflow and metadata. Historical
files remain for provenance and sensitivity comparison.

External Hong Kong source files formerly read from `D:\Program Files` are now
archived inside the main project data tree:

```text
data/tourism/hongkong/raw/
data/transit/hongkong/raw/source_tables/
data/taxi/hongkong/raw/monthly_traffic_transport_digest_2026/
data/boundary/hongkong/2021_Population_Census_Statistics_and_Boundar_SHP/source_documents/
data/gee/hongkong/worldpop_age_sex/source_documents/
```

Each listed directory includes `SOURCE_MANIFEST.csv` with original paths,
sizes, and SHA256 values. New scripts must use these project-local copies by
default; the retained D-drive copies are not workflow dependencies.

Hong Kong WEDAN validation uses the 2021 Summary Results tables 7.8 and 7.9,
official `NewTown_2021.shp`, and LSUG workplace totals. The current recommended
OD workflow freezes the WEDAN checkpoint, uses Hong Kong `local_minmax`
features, ensembles seeds `666/667/668`, and applies an 18-parameter LSUGx3
calibration layer selected by 18-district spatial holdout. New outputs do not
use the historical Fuzhou feature scaler or Fuzhou OD quantile mapping.

The 2022 student-school workflow uses DCCA Census study-place categories,
official New Town geometry, EDB school programs and enrollment margins,
calibrated school-age population, and TCS mechanized HBS constraints. Its
canonical assignment is in expected students; daily HBS and boarding-equivalent
outputs use different units. Read `docs/HONG_KONG_STUDENT_SCHOOL_OD.md` before
using these matrices for MATSim demand.

Hong Kong public-transport route geometry is now map-matched to the official
TNM road network and OSM rail links. The formal MATSim base network,
route-link sequences, stop snaps, QA, preview, and hashes are under
`data/transit/hongkong/processed/transit_route_link_mapmatching_2026_v2/`.
Read `docs/HONG_KONG_MATSIM_PUBLIC_TRANSPORT_DATA.md` before creating
`transitSchedule.xml.gz`. The 129 v2 manual-review directions were explicitly
approved for assembly on 2026-07-22 without erasing their original QA status.
The approved route inventory, route-compatible facilities, nearest-road access
anchors, connector geometries, QA, and hashes are under
`data/transit/hongkong/processed/transit_schedule_assembly_inputs_2026/`.
The no-ferry base road and typical-weekday public-transport MATSim inputs are
retained under
`data/transit/hongkong/processed/matsim_road_pt_supply_2026_typical_weekday/`.
Its `network.xml.gz`, `transitSchedule.xml.gz`, and `transitVehicles.xml.gz`
load successfully in MATSim 2026.0, but this directory is a build dependency
and baseline rather than the active simulation supply.

The active mixed-traffic 5% supply with Ferry Core v1 is under
`data/transit/hongkong/processed/matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_ferry_core_v1_cap010/`.
It adds 21 core ferry routes as dedicated water links and keeps the 20
island-access routes excluded. All transit passenger capacities use 10% of
their full-scale references, while bus/GMB PCUs remain at 5%. See
`docs/HONG_KONG_MATSIM_PUBLIC_TRANSPORT_DATA.md` for route selection, schedule,
capacity proxy, and QA details.

The current Hong Kong typical-weekday 5% multi-activity population is under
`data/matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice/`.
It retains the 385,820-agent v1 work, school, and border population, then fills
the TCS 2022 all-purpose mechanized-trip residual with 263,788 shopping,
dining, leisure, social, medical, and personal-business legs. Its config
enables household-vehicle-aware `SubtourModeChoice`, time mutation, and
rerouting. The v1 directory remains the compulsory-demand baseline. Both v2
unrouted and fully routed plans are available.
Read `docs/HONG_KONG_MATSIM_AGENTS_5PCT.md` before changing population,
capacity-factor, transit-capacity, or route-specific stop-link assumptions.
The current `ride` mode is audited against 2026 Transport Department taxi
controls in `docs/HONG_KONG_TAXI_INITIAL_PLAN_AUDIT.md`; that audit is
read-only and does not modify the adopted v2 plans.

The first private-car offline cost and data-quality audit is under
`data/transport_costs/hongkong/car_cost_v1/` and documented in
`docs/HONG_KONG_CAR_COST_MODEL.md`. It separates representative fleet energy,
confirmed link-level private-car tolls, destination-parking proxies, and one
fixed vehicle-day ownership record. It does not modify the active car scoring,
plans, config, network, facilities, vehicles, or simulation outputs.

The final local SimWrapper project for this configuration is:

```text
runs/hongkong/outputs/formal_50it_ptfixed_ferry_activity_simwrapper/
```

The pre-Ferry and compulsory-plan projects remain comparison baselines.

Current Hong Kong OD products:

```text
Generalized spatial prediction:
data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/CommutingODFlows/hong_kong_fixed_link_grid/hk_scaler_calibration_v1/final/generation_hk_generalized.npy

2021 Census-constrained demand:
data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/CommutingODFlows/hong_kong_fixed_link_grid/hk_scaler_calibration_v1/final/generation_hk_census_projected.npy
```

Formal experiments run only on `by@100.103.8.34:/home/by/OD/HK`, with one GPU
visible and a 10 GiB PyTorch memory limit. SSH, CUDA, DGL, available GPU memory,
or OOM failures must stop the experiment; CPU fallback is forbidden. Detailed
methods, validation metrics, and commands are in
`docs/HONG_KONG_WEDAN_INPUTS_AND_INFERENCE.md`.

## Python environment selection

Use this rule before running any Python script:

| Task | Environment |
|---|---|
| GIS processing, GeoJSON/Shapefile, OSM, GEE, AMap, raster, population feature, CSV/GeoJSON QA | `.venv_geo311` |
| MATSim agents/routes generation, transit supply preprocessing, SimWrapper/Kepler post-processing | `.venv_geo311` |
| PDF text extraction and literature-support processing | `.venv_geo311` |
| WEDAN / WorldCommuting-OD inference | `.venv_wedan` |
| RemoteCLIP image feature extraction | `.venv_wedan` |
| Java MATSim simulation, Maven build, SimWrapper Java runner | Java/Maven, not Python |

When uncertain, use `.venv_geo311` unless the task imports PyTorch, DGL, WEDAN, or RemoteCLIP.

The `data/` first-level domains are stable. City-specific data live one layer below:

```text
data/osm/fuzhou/
data/gee/fuzhou/
data/imagery/fuzhou/
data/worldcommuting_od/fuzhou/
data/matsim_agents/fuzhou/
data/matsim_routes/fuzhou/
data/transit/fuzhou/
```

Shared non-city assets use `_shared`, for example `data/models/_shared/` and
`data/worldcommuting_od/_shared/GeneratingCodeData/`.

## Active Fuzhou model inputs

The active model is a 2% population sample with car / public transit / walk mode choice. Private car ownership is
calibrated to 19.7%. Public transit is represented by bus-priority links and metro links.

Key active inputs:

```text
Boundary:
data/osm/fuzhou/city_23/fuzhou_city_23_boundary.geojson

Demand:
data/matsim_routes/fuzhou/greenspace_grid_multi_activity_2pct_carown197_pt/mode_choice_plans_car_pt_walk_2pct_carown197.xml.gz
data/matsim_routes/fuzhou/greenspace_grid_multi_activity_2pct_carown197_pt/private_car_vehicles_2pct_carown197.xml.gz

Transit supply:
data/transit/fuzhou/transit_matsim_integrated_20260709_bus_priority_transferwait_metro40/network_with_car_busprio_metro.xml.gz
data/transit/fuzhou/transit_matsim_integrated_20260709_bus_priority_transferwait_metro40/transitSchedule.xml.gz
data/transit/fuzhou/transit_matsim_integrated_20260709_bus_priority_transferwait_metro40/transitVehicles.xml.gz

Final config:
scenarios/fuzhou/config-transit-mode-choice-2pct-waitpenalty-metroprefer-from-cont20-reroute50.xml
```

The retained run chain is recorded in `runs/fuzhou/run_manifest.json`.

## Data and model workflow

1. **City boundary and base geodata**
   - Greenspace city id: `23`
   - Boundary and OSM derivatives are under `data/osm/fuzhou/city_23/`.
   - WorldPop/GEE rasters are under `data/gee/fuzhou/city_23/`.

2. **WEDAN OD features**
   - WEDAN repository/code assets are under `data/worldcommuting_od/_shared/GeneratingCodeData/`.
   - Fuzhou feature products are under `data/worldcommuting_od/fuzhou/custom_features/`.
   - Key products include `generation.npy`, `regions.shp`, population features, POI features, image features, and
     `dis.npy`.

3. **Synthetic population and mode-choice demand**
   - Multi-activity agents are generated from WorldPop age/sex structure, WEDAN work OD, POI attraction, and activity
     templates.
   - The active routed/mode-choice demand is under
     `data/matsim_routes/fuzhou/greenspace_grid_multi_activity_2pct_carown197_pt/`.

4. **Transit supply**
   - Final AMap bus stop/line data: `data/transit/fuzhou/bus_amap_stop_line_final_20260709/`
   - Final bus timetable data: `data/transit/fuzhou/bus_timetable_final_20260709/`
   - Final metro data: `data/transit/fuzhou/metro_final_20260709/`
   - Unified coordinates: `data/transit/fuzhou/transit_coordinates_unified_20260709/`
   - Active integrated MATSim transit supply:
     `data/transit/fuzhou/transit_matsim_integrated_20260709_bus_priority_transferwait_metro40/`

5. **Simulation and outputs**
   - Active configs are in `scenarios/fuzhou/`; older configs are in `scenarios/fuzhou/archive/`.
   - Final retained outputs are in `runs/fuzhou/outputs/`.
   - Final logs are in `runs/fuzhou/logs/`.

6. **Visualization and analysis**
   - SimWrapper opener: `scripts/fuzhou_single_city/analysis_visualization/Open-SimWrapper.ps1`
   - Hourly traffic map builder: `scripts/fuzhou_single_city/analysis_visualization/build_simwrapper_hourly_traffic_map.py`
   - Kepler particle flow builder: `scripts/fuzhou_single_city/analysis_visualization/build_kepler_city_particle_flow.py`

## Common commands

Build:

```powershell
cd F:\Matsim\matsim-example-project
.\mvnw.cmd clean package -DskipTests
```

Re-run the current final Fuzhou continuation:

```powershell
.\scripts\fuzhou_single_city\run\run_waitpenalty_from_cont20_reroute50.cmd
```

Refresh SimWrapper dashboards:

```powershell
.\scripts\fuzhou_single_city\analysis_visualization\Open-SimWrapper.ps1 -SkipOpen
```

Open SimWrapper manually and select:

```text
F:\Matsim\matsim-example-project\runs\fuzhou\outputs\waitpenalty-metroprefer-from-cont20-reroute50
```

## How to treat legacy documents

Some files in `docs/` describe older experiments such as car-only 30k agents, early AMap discovery, or ride-hailing
tests. They are provenance documents, not the active workflow. If a command conflicts with this onboarding document,
use the applicable city metadata, run manifest, and final-workflow document as
the source of truth.

## Hong Kong arrival/departure demand

The 2026 typical-weekday border and visitor-demand workflow is documented in
`docs/HONG_KONG_ARRIVAL_DEPARTURE_OD.md`. Its original Euclidean-distance
baseline products live under
`data/tourism/hongkong/processed/arrival_departure_od_2026_typical_weekday/`.

The active spatial version is the separate PT-accessibility V2 under
`data/tourism/hongkong/processed/arrival_departure_od_2026_typical_weekday_pt_access_v2/`.
It uses six-period SwissRailRaptor skims from the Hong Kong MATSim transit
schedule, applies CBTS six-zone incidence only to Mainland same-day visitors,
and conditions later visitor activities on accommodation or the previous
activity. The original Euclidean-distance model remains unchanged as a
historical baseline. See `docs/HONG_KONG_ARRIVAL_DEPARTURE_OD.md`.

## Hong Kong synthetic households and vehicles

The full-scale household layer is documented in
`docs/HONG_KONG_SYNTHETIC_HOUSEHOLDS.md` and stored under
`data/matsim_agents/hongkong/synthetic_households_tcs2022/`. DCCA 2021
household-size, income, housing, age, and sex margins create households and
members on the 1,585 grids. TCS 2022 Table A.4 exactly controls private-vehicle
availability in each of the 26 broad districts; Table 4.2 adjusts household
ranking by housing, income, and household size. Vehicle and designated-driver
records are joined by the current 5% population workflow. The formal plans and
validation outputs are documented in `docs/HONG_KONG_MATSIM_AGENTS_5PCT.md`.

## Hong Kong public transport supply

The official-data-first collection, route map matching, and inferred MTR/Light
Rail timetable workflow is documented in
`docs/HONG_KONG_MATSIM_PUBLIC_TRANSPORT_DATA.md`. The current approximate
weekday rail timetable is under
`data/transit/hongkong/processed/mtr_lrt_approximate_timetable_2026_weekday/`.
Approximate station running/dwell offsets are under
`data/transit/hongkong/processed/mtr_lrt_approximate_station_times_2026_weekday/`.
The normalized capacity catalog, MATSim vehicle-type library, route mappings,
and approximate rail departure vehicles are under
`data/transit/hongkong/processed/public_transport_vehicle_capacities_2025/`.
The complete no-more-data base case is under
`data/transit/hongkong/processed/public_transport_vehicle_capacities_inferred_2026/`;
it is the preferred input because all 3,570 route directions and all 7,461
rail departures have a capacity assignment. Its XB/DB/PI types and full-day
rail consist roster remain explicitly inferred rather than observed.
The no-ferry MATSim base schedule combines stop facilities, accepted link
sequences, departures, offsets, and vehicle references under
`data/transit/hongkong/processed/matsim_road_pt_supply_2026_typical_weekday/`.
The road links in that formal supply are calibrated from the 2026 TNM network,
the 2026-07-22 detector snapshot, and 2019-2024 ATC evidence. The uniform
baseline is retained beside the formal network, while full audit tables and
maps are under `data/transit/hongkong/processed/road_speed_capacity_2026_v1/`.
See `docs/HONG_KONG_ROAD_SPEED_CAPACITY.md`; `.venv_geo311` includes
`xlrd>=2.0.1` for the official ATC `.xls` workbooks.
The v1 demand build created a route-specific stop-link schedule copy under
`data/matsim_agents/hongkong/typical_weekday_5pct_v1/`; v2 uses the active
Ferry Core v1 cap010 supply instead. Representative vehicle
types, inferred rail consists, and one-vehicle-per-departure assumptions should
still be replaced when route-specific fleet allocation and vehicle blocks are
available.
