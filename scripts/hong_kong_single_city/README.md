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

School-bus source acquisition and the Census-adjusted, school-probability,
first-party-locked non-production proxy builder are documented in
`docs/HONG_KONG_SCHOOL_BUS_ROUTE_ACQUISITION.md`. They must not be confused
with the ordinary public-bus/GMB downloader or the active MATSim PT supply.
The v4 road-geometry preparation and static comparison can be rebuilt with:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\map_match_hong_kong_school_bus_proxy_routes.py
```

It uses the active MATSim `car` road layer, does not generate an interactive
map, and remains a manual-review candidate rather than adopted supply.

Build the partial-demand v5 candidate with the hard 3,439-vehicle ceiling and
60/75-minute stage limits using:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_school_bus_time_split_fleet_cap.py
```

The builder deletes remaining over-limit inferred routes and may recover
feasible pickup grids as direct routes; it does not force territory-wide
student coverage.

Build and validate the v6 road-running MATSim supply candidate with:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_school_bus_adoption_ready_supply.py

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\audit_hong_kong_school_bus_adoption_ready_supply.py
```

V6 preserves all v5 passenger capacities, reconstructs proxy road geometry for
the 76 first-party identities, and emits a merged network, schedule and vehicle
bundle. It is ready for student-plan assignment and a physical test but remains
outside current production; consult the acquisition document for provenance
and road-direction repair limitations.

Regenerate mode candidates for every day-school student, independently by
direction and without using the old mode as a filter or rank term, then audit
all physical supply references with:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\demand_generation\prepare_hong_kong_school_mode_candidate_registry.py

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\demand_generation\audit_hong_kong_school_mode_candidate_registry.py
```

This emits an unselected registry only. PT and Taxi are regenerated for every
school trip, Walk is distance-screened, and `car_passenger` remains the
responsibility of the real-driver household joint-plan catalogue.

The first Stage 11 application uses the deterministic cross-mode launcher and
independent plan/event audit below. The pilot deliberately does not constrain
school-bus seats: source capacities remain unchanged in v6, while runtime
school-bus vehicle types receive 1,000,000 seats so every eligible and willing
student can board.

The runtime preserves MATSim's normal routing order: it runs the stock
`PrepareForMobsim` first, restores only selected route-specific school-bus
trip slices, and then creates QSim agents. Moving that restoration before the
stock preparation or into a QSim engine causes mixed household/student plans
to cache a regular-PT substitute and is not equivalent.

The accepted server result is
`/mnt/DiskM/by/hk_stage11_student_school_mode_20260808_run31`: 884/884 selected
school-bus departures board the correct physical vehicle, with no ordinary-PT
substitution or source-capacity exceedance. Three remain aboard at the 30:00
horizon because their vehicles are traffic-stuck, so the independent audit
status is `validated_with_network_stuck_limitations`.

The same launcher also supports the no-innovation physical non-Taxi gate. With
`--physical-nontaxi-modes`, ordinary PT is rerouted by SwissRailRaptor against
a read-only schedule view that excludes every `school_bus` route, while the
full schedule remains available to TransitQSim and exact school-bus
candidates. Walk receives a capacity-free road-network route and custom link
progression at 1.34 m/s; its bookkeeping vehicles have PCU 0 and never enter
QNetwork. Car and bound `car_passenger` retain their physical implementations,
and Taxi is the only teleported main mode. ReRoute, SubtourModeChoice and
TimeAllocationMutator remain at weight zero throughout this gate.

The launcher passes `--unlimited-ordinary-pt-capacity` for this bounded
mechanical gate. The switch expands ordinary PT runtime seats only; it never
rewrites the adopted 10% vehicle file. This isolation was added after run51
showed 60,585 PT passenger legs still waiting before first boarding at the
30:00 horizon. A passing capacity-free run therefore validates event-level
physical execution, not PT seat calibration. Selected `car_passenger` legs
also carry a stable pre-`PrepareForMobsim` route, and any unbound departure
after the one-shot household selection now fails closed instead of silently
using MATSim's teleporter.

At an audited drop-off that is also the driver's destination link, the
physical escort engine accepts `PersonArrival` as the final waypoint because
QNetwork may omit a separate terminal `LinkEnter`. For true intermediate
waypoints, every active binding stores the selected driver's complete detour
and restores it after stock `PrepareForMobsim`; otherwise MATSim can replace it
with a direct activity-to-activity route and silently omit the pickup/drop-off.
Passengers are still removed from the real QVehicle and receive normal
leave/arrival events. A different outstanding drop-off is left pending until
the parallel event queue drains, because its earlier `LinkEnter` callback may
arrive on another handler thread after `PersonArrival`; only a genuinely
unfinished passenger is then classified as onboard at `afterMobsim`.

The completed capacity-isolated gate is
`/mnt/DiskM/by/hk_stage11_student_school_mode_20260808_run56`. The process exits
zero and `physical_nontaxi_audit.json` reports `validated`: all direct
main-mode teleport arrivals are Taxi, and PT, Walk and bound `car_passenger`
have none. `student_school_mode_choice_audit.json` remains `failed`, because
1,002 selected school-bus trips produce only 952 departures and 876
board/alight pairs; 76 selected students are stuck despite zero wrong-vehicle
boards, ordinary-PT substitutions or seat-capacity exceedances. Treat run56 as
a physical-execution gate with unresolved network-completion instability, not
as a capacity, production, or innovation result.

Run56's two apparent deficits have one cause: 76 students miss their first
selected vehicle after per-link QSim rounding makes physical Walk take longer
than its routed time, and 50 later selected school-bus legs consequently never
depart. `HongKongPhysicalWalkEngine` now advances the next link from the prior
continuous due time rather than the integer callback time. The repaired run57
at `/mnt/DiskM/by/hk_stage11_student_school_mode_20260809_run57` records
1,002/1,002 physical school-bus departures and correct boardings. One boarded
student remains aboard a traffic-stuck vehicle at 30:00, so this is
`validated_with_network_stuck_limitations`, not a complete-day or innovation
result.

```text
scripts/hong_kong_single_city/run/launch_hong_kong_student_school_mode_choice_pilot.py
scripts/hong_kong_single_city/run/audit_hong_kong_student_school_mode_choice_pilot.py
scripts/hong_kong_single_city/run/audit_hong_kong_physical_nontaxi_pilot.py
```

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
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\run\prepare_hong_kong_matsim_server_bundle.py `
  build-bundle `
  --source-commit-sha <exact-pushed-sha> `
  --data-root-mode external_locked_input_pack `
  --data-root <verified-new-locked-input-pack-root> `
  --locked-input-pack-manifest <verified-locked-input-pack-manifest.json> `
  --locked-input-pack-manifest-sha256 <recorded-manifest-sha256> `
  --fat-jar .\matsim-example-project-0.0.1-SNAPSHOT.jar `
  --jdk-archive <approved-existing-Temurin-JDK-25-Linux-x64.tar.gz> `
  --release-root /mnt/DiskM/by/<new-exact-sha-release> `
  --staging-dir <new-empty-staging-directory> `
  --bundle-path <new-bundle.tar> `
  --deployment-manifest <new-deployment-manifest.json> `
  --java-version <verified-linux-jdk-25-version> `
  --maven-version <verified-wrapper-version>
```

The active preparation contract is hash-locked to the v2 activity-modechoice
demand and Ferry Core v1 / 10% PT-capacity supply. Source identity may be an
exact clean Git checkout or the Stage 8D exact-tree snapshot described below.
The script rejects legacy v1/pre-Ferry paths, dirty or wrong source checkouts,
wrong snapshot commit/tree/archive/manifest/file content, wrong input hashes,
non-JDK-25 build metadata, and a fat JAR missing the current Taxi/PT/Car
runtime classes. A release root must be supplied explicitly below
`/mnt/DiskM/by/`; it is never inferred from an older deployment. The generated
launchers create new run directories only and use `failIfDirectoryExists`.
Preparing a bundle does not authorize upload or execution.

The seven large v2/Ferry Core inputs are not part of the Git source snapshot.
Generate their separately transferred exact-byte pack and sidecar with:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\run\prepare_hong_kong_matsim_server_bundle.py `
  create-locked-input-pack `
  --source-commit-sha <supervisor-authorized-exact-source-sha> `
  --source-data-root F:\Matsim\matsim-example-project\data `
  --pack-root <new-local-pack-root> `
  --pack-manifest <new-local-pack-manifest.json>
```

A later authorized Runner records the sidecar SHA256, transfers both items to
new server paths and runs `verify-locked-input-pack` with the same exact source
SHA, server pack root, manifest and recorded manifest SHA before
`build-bundle`. The verifier requires exactly seven locked relative paths and
rejects missing, extra, symlinked, stale-v1/pre-Ferry or hash-mismatched files.

Create the Git-metadata-free source artifact from the exact SHA named by the
formal Supervisor/Runner command without changing the current worktree, index
or refs. Both new output paths must be outside the worktree:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\run\prepare_hong_kong_matsim_server_bundle.py `
  create-source-snapshot `
  --source-commit-sha <supervisor-authorized-exact-source-sha> `
  --snapshot-path <new-source-snapshot.tar> `
  --snapshot-manifest <new-source-snapshot-manifest.json>
```

The sidecar embeds the Git commit object and records its derived tree plus
every tracked path, mode, Git blob, size and SHA256. No source SHA/tree/count
or inventory is hardcoded. Verification recomputes the commit-object SHA and
requires it to equal the exact command argument, then reconstructs the commit
tree from canonical Git blob bytes in the archive inventory; snapshot creation
disables host line-ending conversion. A later Runner records the printed
archive and manifest hashes, transfers them only to new server paths, validates before
extraction, extracts into a new Git-free source root and validates that root
again. The `verify-source-snapshot` command performs both validations; omit
`--source-root` before extraction and supply it after extraction.
The pre-extraction verifier used on the server must be the external control
script from the exact reviewed dynamic-identity output commit. No prior source
identity is an implicit fallback.

On the authorized Linux server, after checkout or snapshot identity succeeds,
the exact build command interface is:

```bash
export JAVA_HOME="<approved-existing-linux-jdk-25>"
"$JAVA_HOME/bin/java" -version
cd "<verified-source-root>"
./mvnw -DskipTests package
```

No JDK download or replacement is part of this interface. Missing approved
JDK/archive assets are a stop condition. See
`docs/HONG_KONG_MATSIM_SERVER_BUNDLE_STAGE8D.md` for exact input hashes and
the deployment-manifest contract.

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

Build an immutable three-candidate capacity network by retaining the existing
two-candidate maximum and adding the independent TPDM Volume 4 lane formula:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_tpdm_v4_three_candidate_network.py `
  --input-network <network.xml.gz> `
  --output-dir <new-immutable-directory> `
  --lane-width-m 3.25 `
  --capacity-rounding-vph 50
```

The builder changes only capacities on physical road links and writes a
link-level CSV plus JSON summary. See
`docs/HONG_KONG_TPDM_V4_THREE_CANDIDATE_NETWORK.md`.

The first bounded road-continuity builder is retained only to reproduce the
superseded Candidate1 length/lane sensitivity:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_road_continuity_candidate.py `
  --input-network <network_tpdm_v4_three_candidate.xml.gz> `
  --hotspot-links <hotspot_links.csv> `
  --hotspot-neighbors <hotspot_neighbors.csv> `
  --output-dir <new-immutable-directory>
```

Do not adopt that output: changing `length` also changes physical distance and
free-flow travel time.

Build Candidate2 from the same frozen TPDM3 runtime audit. It keeps the network
byte-identical and writes a full road-supply registry plus direct QSim storage
overrides for exactly 114 unique downstream links:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_explicit_storage_candidate.py `
  --input-network <network_tpdm_v4_three_candidate.xml.gz> `
  --hotspot-links <hotspot_links.csv> `
  --hotspot-neighbors <hotspot_neighbors.csv> `
  --output-dir <new-immutable-directory>
```

For each selected link the direct capacity is the maximum of continuity lanes
`x` PCU, physical/default storage, the per-step buffer floor, and the
free-flow-flow floor. Flow capacity remains the TPDM3 value and is independently
switchable. Enable the runtime layer with
`--road-supply-registry=<road_supply_parameters_v2.csv>` together with physical
Taxi PCU 0.05. Omitting the switch restores standard MATSim storage. See
`docs/HONG_KONG_ROAD_CONTINUITY_116_CANDIDATE.md`.

To build Candidate3, which gives every physical road link a storage floor of
at least its physical lane count while preserving the 114 frozen continuity
floors, add:

```text
--storage-scope all-roads --expected-road-links 86417
```

Candidate3 writes `road_supply_parameters_v3.csv`. It changes QSim storage
only; link lengths, lane counts, free speeds, topology, IDs, modes, and flow
capacities remain the TPDM3 values. The matched no-signal physical-Taxi PCU
0.05 iteration-0 smoke exits 0 and reaches 76.3236% completion, compared with
75.6400% for the 114-link Candidate2 and 74.7509% for TPDM3 default storage.

Build the bounded Candidate4 full connector-chain flow/storage sensitivity
from Candidate3 and its 3,134-link blocked-inflow audit:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_connector_chain_supply_candidate.py `
  --input-network <network_tpdm_v4_three_candidate.xml.gz> `
  --candidate3-registry <road_supply_parameters_v3.csv> `
  --blocked-link-audit <blocked_link_supply_runtime_audit.csv> `
  --previous-relationships <continuity_candidate_relationships_v3.csv> `
  --route-directions <hybrid_capacity_route_directions.csv> `
  --output-dir <new-immutable-directory>
```

A short lane-drop chain is selected only when every impaired same-street
segment can be traced to a recovered cross-section. Ambiguous or truncated
chains are rejected atomically. Accepted segments receive both a QSim-only
TPDM Volume 4 flow floor based on the upstream continuity lanes and storage
recalculated with that flow. The physical network remains byte-identical;
runtime requested/actual flow and storage are audited separately. See
`docs/HONG_KONG_ROAD_CONTINUITY_116_CANDIDATE.md`.

Build Candidate5 Stage A when the bounded chain intervention is insufficient:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_aggressive_road_supply_candidate.py `
  --stage A `
  --input-network <candidate4-physical-network.xml.gz> `
  --baseline-registry <road_supply_parameters_v4.csv> `
  --source-registry <road_supply_parameters_v4.csv> `
  --runtime-supply-audit <candidate4-explicit-storage-audit.csv> `
  --blocked-link-audit <candidate3-blocked-link-audit.csv> `
  --output-dir <new-immutable-directory>
```

Stage A applies a finite 30-second QSim-flow storage buffer to all 3,134
blocked links and expands every representation-review seed through nearby
short or lane-deficient branches/cycles. It writes an independent
`storage_floor_pcu`, QSim-only flow overrides, and component membership while
copying the physical network byte-for-byte. Stages B/C consume the previous
stage registry and runtime audit, but should be run only if the preceding
stage requires further sensitivity testing. The accepted Stage A smoke reaches
89.6187% completion and reduces blocked seconds 67.5237% versus Candidate4.
A subsequent cause audit nevertheless identified 552 links blocked for at
least six hours, so Stage B was run as an explicitly more aggressive road-only
sensitivity:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_aggressive_road_supply_candidate.py `
  --stage B `
  --input-network <candidate5a-physical-network.xml.gz> `
  --baseline-registry <road_supply_parameters_v4.csv> `
  --source-registry <road_supply_parameters_v5a.csv> `
  --runtime-supply-audit <candidate5a-explicit-storage-audit.csv> `
  --blocked-link-audit <candidate3-blocked-link-audit.csv> `
  --output-dir <new-immutable-directory>
```

Stage B merges overlapping severe **core** chains before adding a one-link
entry/exit boundary layer, so shared boundaries cannot merge unrelated
corridors. It applies the flow and 60-second storage floors to every link in
the rebuilt chain, not only the severe seed. This remains an opt-in
sensitivity; see
`docs/HONG_KONG_ROAD_CONTINUITY_116_CANDIDATE.md`.

The corrected Candidate5B smoke reaches 94.8452% completion and cuts blocked
seconds 96.1449% versus Candidate5A. It passes every road gate, but the
combined gate remains false because PT passengers waiting before first
boarding fall only 18.55% instead of 50%. Do not proceed automatically to
Stage C: separate experienced PT arrival timing and second-day service first.

That separation is implemented by
`transit_supply/build_hong_kong_experienced_pt_timetable_candidate.py`.
It preserves original PT identifiers, fits a route-stop delay shape and
smoothed 15-minute route shift from a completed frozen events file, and wraps
00:00--06:00 departures into 24:00--30:00 with deterministic `__day2`
departure/vehicle IDs. Supply overrides are passed atomically with
`--transit-schedule-input` and `--transit-vehicles-input`. The matched
Candidate5B smoke reaches 96.3699% completion and reduces combined unresolved
PT states by 28.97%; it remains a non-production sensitivity documented in
`docs/HONG_KONG_EXPERIENCED_PT_TIMETABLE_V1.md`.

## Traffic-signal location registry

Download the Transport Department Traffic Aids traffic-light layers and build
the conservative OSM/official/MATSim-network fusion:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\data_acquisition\download_hong_kong_traffic_signal_data.py

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_traffic_signal_registry.py
```

The output is under
`data/transit/hongkong/processed/hong_kong_traffic_signal_registry_2026_v1/`.
It is a signal-location and candidate-controlled-link registry, not a signal
timing plan and not yet an adopted MATSim signals input. See
`docs/HONG_KONG_TRAFFIC_SIGNAL_REGISTRY_2026.md`.

The MATSim pilot conversion is specified in
`docs/HONG_KONG_TRAFFIC_SIGNAL_MATSIM_ADOPTION_DESIGN.md`. It requires
movement-level turn control, conflict and pedestrian-clearance records,
evidence-labelled time-of-day plans, and an audit preventing signal capacity
from being counted twice. The eight-junction AM/PM timing sheet is a pilot
input only; it is not a city-wide timing template.

Build the eight-junction vehicle-signal pilot on the current physical
school-bus network, compile separate AM/PM MATSim inputs, and validate them:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_traffic_signal_pilot_v1.py `
  --network .\data\transit\hongkong\processed\matsim_road_pt_school_bus_supply_2026_v6_adoption_ready\network.xml.gz

.\mvnw.cmd -q `
  '-Dexec.mainClass=org.matsim.project.hongkong.signals.BuildHongKongTrafficSignalPilot' `
  '-Dexec.args=data/transit/hongkong/processed/hong_kong_traffic_signals_2026_pilot_v1 data/transit/hongkong/processed/hong_kong_traffic_signals_2026_pilot_v1/network_signal_capacity_deconvolved.xml.gz data/transit/hongkong/processed/hong_kong_traffic_signals_2026_pilot_v1/matsim_am am' `
  org.codehaus.mojo:exec-maven-plugin:3.5.0:java

.\mvnw.cmd -q `
  '-Dexec.mainClass=org.matsim.project.hongkong.signals.BuildHongKongTrafficSignalPilot' `
  '-Dexec.args=data/transit/hongkong/processed/hong_kong_traffic_signals_2026_pilot_v1 data/transit/hongkong/processed/hong_kong_traffic_signals_2026_pilot_v1/network_signal_capacity_deconvolved.xml.gz data/transit/hongkong/processed/hong_kong_traffic_signals_2026_pilot_v1/matsim_pm pm' `
  org.codehaus.mojo:exec-maven-plugin:3.5.0:java

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\validate_hong_kong_traffic_signal_pilot_v1.py `
  --source-network .\data\transit\hongkong\processed\matsim_road_pt_school_bus_supply_2026_v6_adoption_ready\network.xml.gz
```

The generated directory contains 8 junction systems, 62 movement signals, 26
groups, AM/PM controls, capacity and conflict audits, and an explicit
pedestrian-phase blocker table. It is ignored rebuildable data and is not the
adopted production supply. This v1 package is now historical because its stage
membership came from conflict-graph colouring rather than the arrows drawn in
the source diagram. Runtime activation additionally requires the runner's
`--traffic-signals` flag, which still points to this historical v1 package.

Build and validate the bounded diagram-inferred v2 package:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_traffic_signal_pilot_v2_diagram_inferred.py

.\mvnw.cmd -q `
  '-Dexec.mainClass=org.matsim.project.hongkong.signals.BuildHongKongTrafficSignalPilotV2' `
  '-Dexec.args=data/transit/hongkong/processed/hong_kong_traffic_signals_2026_pilot_v2_diagram_inferred data/transit/hongkong/processed/hong_kong_traffic_signals_2026_pilot_v2_diagram_inferred/network_signal_capacity_deconvolved.xml.gz data/transit/hongkong/processed/hong_kong_traffic_signals_2026_pilot_v2_diagram_inferred/matsim_am am' `
  org.codehaus.mojo:exec-maven-plugin:3.5.0:java

.\mvnw.cmd -q `
  '-Dexec.mainClass=org.matsim.project.hongkong.signals.BuildHongKongTrafficSignalPilotV2' `
  '-Dexec.args=data/transit/hongkong/processed/hong_kong_traffic_signals_2026_pilot_v2_diagram_inferred data/transit/hongkong/processed/hong_kong_traffic_signals_2026_pilot_v2_diagram_inferred/network_signal_capacity_deconvolved.xml.gz data/transit/hongkong/processed/hong_kong_traffic_signals_2026_pilot_v2_diagram_inferred/matsim_pm pm' `
  org.codehaus.mojo:exec-maven-plugin:3.5.0:java

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\validate_hong_kong_traffic_signal_pilot_v2_diagram_inferred.py
```

v2 audits all eight diagrams but initially compiles only `TS_K006` (Nathan
Road / Jordan Road): 4 non-U-turn movement signals, 3 diagram-derived groups,
and 4 capacity-deconvolved approaches. The other 7 examples remain explicit
deferred records. The generated package is ignored rebuildable data, has not
yet had a runtime test, and is selected only when it is explicitly staged as
the launcher's `traffic_signal_pilot` payload. The launcher reads the staged
build summary, so v2 runs are not labelled with historical v1 counts.

Build the bounded Top-100, 96-bin time-of-day proxy with
`build_hong_kong_traffic_signal_tod_proxy_top100.py`, compile it with
`BuildHongKongTrafficSignalTodTop100`, and validate it with
`validate_hong_kong_traffic_signal_tod_proxy_top100.py`. Full commands,
assumptions, QA, and the opt-in adoption boundary are in
`docs/HONG_KONG_TRAFFIC_SIGNAL_TOD_TOP100_V3.md`. When explicitly staged as
the `traffic_signal_pilot` payload, the launcher selects its `matsim/` folder
with `--period tod`; AM/PM behavior is unchanged.

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

Generate one chargeability audit row for every generic PT passenger main leg.
Trips without an actual mode, line, route, stops, and transfer chain retain
`cost_hkd=null`:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\estimate_hong_kong_pt_trip_fares.py `
  --source-project-root F:\Matsim\matsim-example-project
```

Run the independent validator:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\validate_hong_kong_pt_fare_model_v1.py `
  --source-project-root F:\Matsim\matsim-example-project
```

Build the separate adult Octopus rule table for explicit ordered domestic MTR
and Airport Express station IDs:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\build_hong_kong_mtr_station_od_fares.py `
  --source-project-root F:\Matsim\matsim-example-project
```

Run the fixed offline query fixture and its independent raw-CSV validator:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\quote_hong_kong_mtr_station_od_fares.py `
  --input .\data\transport_costs\hongkong\pt_fare_v1\mtr_station_od_v1\mtr_fare_query_fixture_input.csv `
  --output .\data\transport_costs\hongkong\pt_fare_v1\mtr_station_od_v1\mtr_fare_query_fixture_output.csv

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\validate_hong_kong_mtr_station_od_fares.py `
  --source-project-root F:\Matsim\matsim-example-project
```

MTR station-OD v1 supports only `train`, adult, Octopus, an explicit fare
scope, and explicit ordered boarding/alighting station IDs. It does not use
reverse-direction substitution, distance interpolation, path summation,
cross-scope fallback, or missing-value zero fill. Airport Express retains six
unresolved ordered pairs, and MTR effective-date evidence remains
`external_official_reference_not_locally_archived`.

Build the separate adult Octopus base-fare rules for explicit ordered Light
Rail stop IDs:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\build_hong_kong_light_rail_station_od_fares.py `
  --source-project-root F:\Matsim\matsim-example-project
```

Run the Light Rail fixture query and independent raw-CSV/schedule validator:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\quote_hong_kong_light_rail_station_od_fares.py `
  --input .\data\transport_costs\hongkong\pt_fare_v1\light_rail_station_od_v1\light_rail_fare_query_fixture_input.csv `
  --output .\data\transport_costs\hongkong\pt_fare_v1\light_rail_station_od_v1\light_rail_fare_query_fixture_output.csv

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\validate_hong_kong_light_rail_station_od_fares.py `
  --source-project-root F:\Matsim\matsim-example-project
```

Light Rail station-OD v1 supports only `light_rail`, adult, Octopus, its
dedicated scope, and explicit ordered stop IDs. The 705/706 loops remain
one-to-many composites, three schedule short turns remain partial, and all
quoted amounts are labelled as base fares before unmodelled concessions.

Outputs are under `data/transport_costs/hongkong/pt_fare_v1/`. These scripts
are offline read-only consumers of the adopted MATSim inputs. They do not
modify plans, config, scoring, network, transit schedule, vehicles, or Java
runners. See `docs/HONG_KONG_PT_FARE_MODEL.md`.

## Candidate5B traffic-signal A/B

Use the `signal-candidate5b-original-it0` launcher profile and
`run/audit_hong_kong_candidate5b_signal_ab.py`. The frozen A/B retains the same
original plans, PT supply, Candidate5B physical network/registry, Taxi fleet,
and Taxi PCU 0.05, and changes only the Candidate11 TOD signal switch. The
corrected signal run exits zero, raises completion from 94.8452% to 97.1698%,
and adds 1.835 minutes to trips completed in both arms. See
`docs/HONG_KONG_CANDIDATE5B_SIGNAL_AB.md`; it is not production-adopted.

Holding those signals fixed and supplying the experienced-time/day-2 PT files
atomically rebuilds ordinary PT itineraries through `--clear-pt-routes`.
The matched iteration-0 follow-up reaches 98.4483% completion, makes common
completed trips 1.809 minutes faster, and cuts combined unresolved PT
passenger states 45.54%. It remains non-production because regular PT vehicle
stuck events at 30:00 rise from 9 to 850; see
`docs/HONG_KONG_EXPERIENCED_PT_TIMETABLE_V1.md`.
