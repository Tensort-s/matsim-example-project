# Project onboarding for future Codex sessions

This document is the first file to read when reopening the project in a new session. It records the current Fuzhou
MATSim workflow after the multi-city data layout migration.

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
- City package: `cities/fuzhou/city.yaml`
- Current final run: `runs/fuzhou/outputs/waitpenalty-metroprefer-from-cont20-reroute50`

Hong Kong preparation is in progress under `scripts/hong_kong_single_city/` and
`data/*/hongkong/`. Current provenance docs include:

```text
docs/HONG_KONG_BOUNDARY_PREPARATION.md
docs/HONG_KONG_WORLDPOP_PREPARATION.md
docs/HONG_KONG_ESRI_WORLD_IMAGERY.md
docs/HONG_KONG_FIXED_LINK_GRID.md
docs/HONG_KONG_OSM_POIS.md
docs/HONG_KONG_INTEGRATED_POIS.md
docs/HONG_KONG_WEDAN_INPUTS_AND_INFERENCE.md
docs/HONG_KONG_STUDENT_SCHOOL_OD.md
```

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
use this onboarding document and `cities/fuzhou/city.yaml` as the source of truth.
# Hong Kong arrival/departure demand

The 2026 typical-weekday border and visitor-demand workflow is documented in
`docs/HONG_KONG_ARRIVAL_DEPARTURE_OD.md`. Its formal data products live under
`data/tourism/hongkong/processed/arrival_departure_od_2026_typical_weekday/`.
