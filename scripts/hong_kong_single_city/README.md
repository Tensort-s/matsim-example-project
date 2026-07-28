# Hong Kong single-city scripts

These scripts are the Hong Kong-specific workflow scripts. Hong Kong should be
handled as an official-data-first city workflow rather than a direct copy of
the Fuzhou AMap/OSM-heavy workflow.

For the adopted end-to-end sequence and the distinction between production,
upstream baseline, and historical outputs, read
`docs/HONG_KONG_FINAL_WORKFLOW.md` before running individual scripts.

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

- `transit_supply/`
  Route-to-link map matching and MATSim public-transport supply assembly.

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

Download official CSDI bus/GMB route polylines, operator static data, detailed
GMB headways, and timestamped MTR/Light Rail next-train snapshots:

```powershell
.\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\data_acquisition\download_hong_kong_public_transport_api_data.py `
  --catalog F:\Matsim\matsim-example-project\data\transit\hongkong\raw\source_tables\hk_public_transport_api_catalog.csv `
  --data-root F:\Matsim\matsim-example-project\data `
  --skip-gtfs
```

See `docs/HONG_KONG_MATSIM_PUBLIC_TRANSPORT_DATA.md` for the Point/polyline
distinction, route-geometry coverage, MATSim use, and remaining data gaps.

Prepare the official missing-route target inventory and collect supplementary
bus, GMB, MTR, and Light Rail data from AMap:

```powershell
.\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\data_acquisition\fetch_hong_kong_transit_from_amap.py `
  --data-root F:\Matsim\matsim-example-project\data `
  --prepare-only

$env:AMAP_WEB_KEY="<AMap Web Service key>"
.\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\data_acquisition\fetch_hong_kong_transit_from_amap.py `
  --data-root F:\Matsim\matsim-example-project\data
```

The collector caches keyword responses, converts GCJ-02 coordinates to WGS84,
and only promotes sufficiently strong official-to-AMap matches.

Complete the remaining routes by querying only their 55 known official stop
locations, then using AMap stop IDs to discover and fetch line IDs:

```powershell
.\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\data_acquisition\fetch_hong_kong_transit_via_amap_stop_ids.py `
  --data-root F:\Matsim\matsim-example-project\data `
  --stage prepare

$env:AMAP_WEB_KEY="<AMap Web Service key>"
.\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\data_acquisition\fetch_hong_kong_transit_via_amap_stop_ids.py `
  --data-root F:\Matsim\matsim-example-project\data
```

This targeted workflow does not use `place/polygon`. Its QA-passed combined
route layer is under `data/transit/hongkong/AMap_Targeted_StopID_Supplements/`.
The older `AMap_StopID_Supplements/` citywide experiment is diagnostic only.

Map-match all CSDI/QA-passed AMap trajectories and ordered-stop fallback
routes to TNM road or OSM rail links, and write the MATSim base network:

```powershell
.\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\map_match_hong_kong_transit_routes.py
```

Formal v2 output is under
`data/transit/hongkong/processed/transit_route_link_mapmatching_2026_v2/`.
Read `docs/HONG_KONG_MATSIM_PUBLIC_TRANSPORT_DATA.md` for source priority,
direction assumptions, connector semantics, QA thresholds, and remaining
schedule/vehicle gaps.

Generate the v1/v2 comparison, remaining-review maps, accepted-repair map, and
manual-review route atlas:

```powershell
.\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\analysis_visualization\visualize_hong_kong_transit_map_matching_anomalies.py
```

The original automatic QA remains available in `accepted_routes.csv` and
`needs_manual_review.csv`. After the explicit project decision to accept every
remaining review route, prepare the schedule-assembly route and stop inputs:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\prepare_hong_kong_transit_schedule_assembly_inputs.py `
  --data-root F:\Matsim\matsim-example-project\data
```

The output is under `processed/transit_schedule_assembly_inputs_2026/`.
Bus/GMB facilities use route-compatible road links. MTR and Light Rail
platform facilities remain on route-compatible rail links, while separate
nearest-road access anchors and connector geometries are provided for walking
access. The original QA status is retained in the approved route table.

Assemble the road network, complete typical-weekday public-transport schedule,
and transit vehicles for MATSim (population plans are intentionally excluded):

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_matsim_road_pt_supply.py `
  --data-root F:\Matsim\matsim-example-project\data
```

The no-ferry base output is under
`processed/matsim_road_pt_supply_2026_typical_weekday/`. It remains an upstream
build dependency; the active simulation supply is the Ferry Core v1 cap010
directory documented below. Validate the base three core XML files with
MATSim 2026.0 without loading population plans:

```powershell
.\mvnw.cmd -q -DskipTests compile
.\mvnw.cmd -q -DskipTests `
  "-Dexec.mainClass=org.matsim.project.ValidateHongKongTransitSupply" `
  "-Dexec.args=<network.xml.gz> <transitSchedule.xml.gz> <transitVehicles.xml.gz>" `
  exec:java
```

Create the active hybrid-capacity network with bus and GMB retained in mixed
traffic while their PCUs are scaled to the 5% demand representation:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_mixed_road_pt_pcu_scaled_supply.py `
  --data-root F:\Matsim\matsim-example-project\data `
  --pcu-factor 0.05
```

The complete bus/GMB timetable and mixed route-link sequences are retained.
Bus PCU changes from `2.5` to `0.125`; GMB changes from `1.5` to `0.075`.
Passenger capacity, vehicle size, and all rail types remain unchanged. The
active smoke and 50-iteration configs use `flowCapacityFactor=0.1` and
`storageCapacityFactor=0.1`. The dedicated-link script remains available as a
sensitivity alternative but is not the active configuration.

Add the representative-weekday Ferry Core v1 layer to the active 5% mixed
supply:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_ferry_core_supply.py `
  --project-root F:\Matsim\matsim-example-project
```

The script retains every existing road/PT link and appends dedicated
`modes=ferry` water links. Official GTFS controls active routes, stops, and
departures; OSM ferry relations and ways provide geometry. Core eligibility
requires every active route stop to be within 1,200 m of the existing road
network. Formal output is under
`processed/matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_ferry_core_v1_cap010/`.
All public-transport passenger capacities are regenerated from the full-scale
vehicle file at 10%. Bus/GMB road PCUs remain at 5% (`0.125/0.075`) because
passenger capacity and road-space representation are separate parameters.

Audit the 5% plans against the fixed-link boundary:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\demand_generation\audit_hong_kong_island_plans.py `
  --project-root F:\Matsim\matsim-example-project
```

Explicit border activities are retained even when their control point is
outside the fixed-link polygon. Internal activities outside that polygon fail
the audit instead of being silently reassigned.

Prepare the append-only Linux server bundle with:

```powershell
python .\scripts\hong_kong_single_city\run\prepare_hong_kong_matsim_server_bundle.py `
  --fat-jar .\matsim-example-project-0.0.1-SNAPSHOT.jar `
  --jdk-archive <Temurin-JDK-25-Linux-x64.tar.gz> `
  --staging-dir <new-empty-staging-directory> `
  --bundle-path <new-bundle.tar>
```

The server release root is fixed to
`/mnt/DiskM/by/hk_matsim_5pct_mixed_pcu005_v1`. The generated launchers create
new run directories only and use `failIfDirectoryExists`; the formal
50-iteration launcher is not called during deployment.

Build the fixed-link typical-weekday 5% resident, school, work, and border
population together with scenario facilities and private vehicles:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\demand_generation\build_hong_kong_matsim_agents_5pct.py
```

Formal outputs are under
`data/matsim_agents/hongkong/typical_weekday_5pct_v1/`. Route the complete
population without running QSim using:

```powershell
$env:MAVEN_OPTS="-Xmx12g"
mvn -q "-Dmaven.test.skip=true" exec:java `
  "-Dexec.mainClass=org.matsim.project.RunHongKong5Pct" `
  "-Dexec.args=<config_hong_kong_5pct.xml> <plans_routed_5pct.xml.gz>"
```

See `docs/HONG_KONG_MATSIM_AGENTS_5PCT.md` for population controls, activity
chains, hierarchical OD integerization, route-specific stop-link repair,
validation results, and known limitations.

Enrich the retained v1 compulsory plans with TCS 2022-controlled resident
shopping, dining, leisure, social, medical, and personal-business tours, and
enable household-vehicle-aware MATSim mode choice:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\demand_generation\enrich_hong_kong_matsim_agents_5pct.py `
  --data-root F:\Matsim\matsim-example-project\data
```

The independent v2 output is under
`data/matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice/`.
After route-only MATSim preparation, validate the routed population with:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\demand_generation\validate_hong_kong_matsim_agents_5pct_v2.py
```

Visualize the current map-matched MTR and Light Rail routes together with the
deduplicated official stations/stops:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\analysis_visualization\visualize_hong_kong_mtr_lrt_routes_stops.py `
  --data-root F:\Matsim\matsim-example-project\data
```

The combined, MTR-only, and Light-Rail-only PNGs are written to
`processed/mtr_lrt_route_stop_visualization_2026/`.

Infer a typical-weekday MTR and Light Rail origin-departure timetable from the
published average-frequency table and two independent next-train snapshots:

```powershell
.\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_mtr_lrt_approximate_timetable.py `
  --frequency-table F:\Matsim\matsim-example-project\data\transit\hongkong\raw\source_tables\mtr_average_train_frequency_long.csv `
  --snapshot-dir F:\Matsim\matsim-example-project\data\transit\hongkong\API_Supplements\realtime_snapshots\20260720T102416Z `
  --snapshot-dir F:\Matsim\matsim-example-project\data\transit\hongkong\API_Supplements\realtime_snapshots\20260722T034716Z `
  --output-dir F:\Matsim\matsim-example-project\data\transit\hongkong\processed\mtr_lrt_approximate_timetable_2026_weekday
```

The output contains inferred departures at each route origin and an ordered
stop table. It is not an observed station-by-station timetable and does not
by itself contain running-time offsets or MATSim transit-route departures.

Estimate station-to-station running times, dwell times, and cumulative MATSim
stop offsets from the ordered stops, v2 rail geometry, and three snapshots:

```powershell
.\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_mtr_lrt_station_offsets.py `
  --transit-root F:\Matsim\matsim-example-project\data\transit\hongkong `
  --snapshot-dir F:\Matsim\matsim-example-project\data\transit\hongkong\API_Supplements\realtime_snapshots\20260720T102416Z `
  --snapshot-dir F:\Matsim\matsim-example-project\data\transit\hongkong\API_Supplements\realtime_snapshots\20260722T034716Z `
  --snapshot-dir F:\Matsim\matsim-example-project\data\transit\hongkong\API_Supplements\realtime_snapshots\20260722T055352Z
```

The MATSim-ready long table is
`processed/mtr_lrt_approximate_station_times_2026_weekday/matsim_route_stop_offsets.csv`.
It still needs to be assembled with stop facilities, accepted route-link
sequences, departures, and vehicles to form a complete transit schedule.

Normalize the public-transport vehicle-capacity catalog, derive representative
MATSim vehicle types, and assign those types to the current map-matched routes
and approximate MTR/Light Rail departures:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_transit_vehicle_types.py `
  --capacity-csv F:\Matsim\matsim-example-project\data\transit\hongkong\raw\source_tables\hong_kong_public_transport_vehicle_capacity.csv `
  --data-root F:\Matsim\matsim-example-project\data
```

Formal output is under
`processed/public_transport_vehicle_capacities_2025/`. The generated rail
vehicle XML uses one vehicle ID per departure because vehicle blocks and
interlining are not yet available. Bus types are operator fleet-weighted
representatives, and Light Rail defaults to one car until departure-level
consist lengths are collected.

When no additional vehicle-allocation data are available, build the complete
inferred base case instead. This fills the remaining operators with explicit
service proxies, allocates the two Tuen Ma Line fleet variants in their 48:17
trainset ratio, and uses the three Light Rail snapshots to assign one/two-car
consists by line and service period:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_transit_vehicle_types.py `
  --capacity-csv F:\Matsim\matsim-example-project\data\transit\hongkong\raw\source_tables\hong_kong_public_transport_vehicle_capacity.csv `
  --data-root F:\Matsim\matsim-example-project\data `
  --complete-inference
```

The recommended base-case output is
`processed/public_transport_vehicle_capacities_inferred_2026/`. Every inferred
route and departure retains its method and confidence; proxy assignments are
model inputs, not observed vehicle rosters.

Download CSDI immigration control point locations and match them to a daily
passenger traffic CSV date. Use `--insecure` only when the local Python trust
store rejects the Hong Kong government certificate chain:

```powershell
.\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\data_preparation\build_hong_kong_control_point_locations.py `
  --date 16-07-2026 `
  --traffic-csv F:\Matsim\matsim-example-project\data\tourism\hongkong\raw\statistics_on_daily_passenger_traffic.csv `
  --insecure
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

Map and chart 18-district LSUGx3 share MAE and Cell WAPE for the generalized
and Census-projected OD products:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\analysis_visualization\visualize_hong_kong_district_lsug3_metrics.py
```

Create static Census-projected grid straight-line and 18-district OD flow maps:

```powershell
.\.venv_geo311\Scripts\python.exe .\scripts\hong_kong_single_city\analysis_visualization\visualize_hong_kong_census_od_flow_maps.py
```

Build the 2022 DCCA-constrained student-to-school assignment, TCS mechanized
HBS trips, direction/time matrices, and mode equivalents:

```powershell
.\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\demand_generation\build_hong_kong_student_school_od.py `
  --data-root .\data
```

See `docs/HONG_KONG_STUDENT_SCHOOL_OD.md` for the Census `same` definition,
data units, structural-support reconciliation, outputs, and QA.

Create Top-3,000 residential-grid-centroid to exact-school flow maps and
18-district maps for both expected student assignments and weekday mechanized
home-to-school trips:

```powershell
.\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\analysis_visualization\visualize_hong_kong_student_school_od_flows.py
```

The old `scripts/hongkong/...` path is kept only as a compatibility wrapper.

Prepare, generate, and visualize the 2026 typical-weekday Hong Kong
arrival/departure demand model. Formal data products are written to the F-drive
data root when it is passed explicitly:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\data_preparation\prepare_hong_kong_arrival_departure_inputs.py `
  --data-root F:\Matsim\matsim-example-project\data `
  --hktb-purpose-xlsx "F:\Matsim\matsim-example-project\data\tourism\hongkong\raw\Visitor Arrival by Purpose of Visit 2026Q1.xlsx"

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\demand_generation\build_hong_kong_arrival_departure_od.py `
  --data-root F:\Matsim\matsim-example-project\data

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\analysis_visualization\visualize_hong_kong_arrival_departure_od.py `
  --data-root F:\Matsim\matsim-example-project\data `
  --top-district-flows 100 --top-activity-chains 100
```

See `docs/HONG_KONG_ARRIVAL_DEPARTURE_OD.md` for source roles, units,
validation, outputs, and limitations.

Re-estimate the same border margins with the completed MATSim timetable
network. The V2 workflow replaces checkpoint Euclidean decay with six-period
SwissRailRaptor generalized-time skims and conditions later activities on the
hotel or previous activity instead of the arrival checkpoint:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\demand_generation\build_hong_kong_pt_generalized_time_skims.py `
  --data-root F:\Matsim\matsim-example-project\data

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\demand_generation\build_hong_kong_arrival_departure_od_pt_access_v2.py `
  --data-root F:\Matsim\matsim-example-project\data

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\analysis_visualization\visualize_hong_kong_arrival_departure_od_pt_access_v2.py `
  --data-root F:\Matsim\matsim-example-project\data
```

V1 remains a historical comparison. Formal V2 outputs are under
`arrival_departure_od_2026_typical_weekday_pt_access_v2/`.

Build full-scale DCCA-controlled synthetic households, household members,
private vehicles, and designated drivers. TCS 2022 Table A.4 is the hard
26-district vehicle margin, while Table 4.2 supplies household-level ranking
effects:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\demand_generation\build_hong_kong_synthetic_households.py `
  --data-root F:\Matsim\matsim-example-project\data
```

See `docs/HONG_KONG_SYNTHETIC_HOUSEHOLDS.md` for data roles, integer controls,
vehicle-count interpretation, outputs, and full-scale QA.

Calibrate the Hong Kong MATSim road network with the 2026 TNM road limits and
detectors plus 2019-2024 ATC evidence. This saves the uniform network baseline,
validates the candidate, and then atomically updates the formal road/PT network:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\calibrate_hong_kong_road_speed_capacity.py `
  --project-root F:\Matsim\matsim-example-project `
  --update-formal-network
```

Build the independent TPDM design-flow mapping and traffic lower-bound review
table without modifying the MATSim network:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_tpdm_capacity_mapping.py `
  --project-root F:\Matsim\matsim-example-project
```

Build OSM-supported road-class and directional-lane candidates without
modifying capacity or the formal MATSim network:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\enrich_hong_kong_road_classes_lanes_from_osm.py `
  --project-root F:\Matsim\matsim-example-project
```

Resolve the candidate evidence using the fixed official-first road-class and
detector/OSM lane hierarchies. This writes a capacity-unchanged candidate
network and does not replace the formal network:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\finalize_hong_kong_road_class_lane_decisions.py `
  --project-root F:\Matsim\matsim-example-project
```

Resolve every adopted OSM lane record that conflicts with direct ATC lane
evidence, using `2,300 veh/h/lane` as the automatic physical flow guard:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\resolve_hong_kong_atc_osm_lane_conflicts.py `
  --project-root F:\Matsim\matsim-example-project
```

Build the full-scale hybrid road-capacity candidate from TPDM cross-section
design flow, direct ATC/detector flow floors, and corrected directional lanes:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_hybrid_road_capacity.py `
  --project-root F:\Matsim\matsim-example-project
```

The environment requires `xlrd>=2.0.1`. The road/PT supply builder
automatically reapplies the generated route-direction attributes on subsequent
rebuilds. See `docs/HONG_KONG_ROAD_SPEED_CAPACITY.md`.

## SimWrapper visualization

Open the compact SimWrapper project for the final Ferry Core v1,
10%-capacity, multi-activity-plan 50-iteration run:

```powershell
.\scripts\hong_kong_single_city\analysis_visualization\Open-HongKong-SimWrapper.ps1
```

The default project directory is:

```text
F:\Matsim\matsim-example-project\runs\hongkong\outputs\formal_50it_ptfixed_ferry_activity_simwrapper
```

It contains overview, trips, daily car traffic, public transit, stuck-agent,
and hourly car-traffic dashboards. The project contains the derived analyses
and network/transit inputs needed by SimWrapper, but does not duplicate the
615 MB final events file.

Validate without opening a browser:

```powershell
.\scripts\hong_kong_single_city\analysis_visualization\Open-HongKong-SimWrapper.ps1 -SkipOpen
```

The two PT-rerouted 50-iteration comparison runs are available as separate
compact projects:

```text
F:\Matsim\matsim-example-project\runs\hongkong\outputs\formal_50it_ptfixed_baseline_simwrapper
F:\Matsim\matsim-example-project\runs\hongkong\outputs\formal_50it_ptfixed_ferry_activity_simwrapper
```

Open either project by passing its directory:

```powershell
.\scripts\hong_kong_single_city\analysis_visualization\Open-HongKong-SimWrapper.ps1 `
  -ProjectDirectory F:\Matsim\matsim-example-project\runs\hongkong\outputs\formal_50it_ptfixed_baseline_simwrapper

.\scripts\hong_kong_single_city\analysis_visualization\Open-HongKong-SimWrapper.ps1 `
  -ProjectDirectory F:\Matsim\matsim-example-project\runs\hongkong\outputs\formal_50it_ptfixed_ferry_activity_simwrapper
```

Both projects contain overview, trip, road-traffic, public-transport passenger,
end-of-day unfinished-agent, and hourly private-car traffic dashboards. The
full event files remain on the server and are not duplicated locally.

## Detailed multimodal particle flow

The Ferry Core v1 and activity-plan run also has a detailed particle animation:

```text
F:\Matsim\matsim-example-project\runs\hongkong\outputs\formal_50it_ptfixed_ferry_activity_simwrapper\particle-flow-detailed-road-corrected
```

Open it through a local HTTP server:

```powershell
.\scripts\hong_kong_single_city\analysis_visualization\Open-Hong-Kong-Detailed-Particle-Flow.ps1
```

The deterministic browser sample distinguishes people, private cars, bus/GMB,
MTR/light rail, and ferries. People are visible only while walking or
transferring; while onboard, the matching vehicle particle represents them.
Access, egress, walking, and ride stages are shown only when a street-graph
route can be reconstructed. Unroutable segments are audited and never drawn as
straight-line fallbacks.

## Offline public-transport fare audit

Build the official adult Octopus fare catalog, production-schedule inventory,
and official-to-MATSim match:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\build_hong_kong_pt_fare_catalog.py `
  --source-project-root F:\Matsim\matsim-example-project
```

Generate one low-quality distance-only estimate for every generic PT passenger
main leg:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\estimate_hong_kong_pt_trip_fares.py `
  --source-project-root F:\Matsim\matsim-example-project
```

Outputs are under `data/transport_costs/hongkong/pt_fare_v1/`. These scripts
are offline read-only consumers of the adopted MATSim inputs. They do not
modify plans, config, scoring, network, transit schedule, vehicles, or Java
runners. See `docs/HONG_KONG_PT_FARE_MODEL.md`.
