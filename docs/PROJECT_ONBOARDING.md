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

For the active multimodal-cost integration, [`agent-lanes.md`](../agent-lanes.md)
is the current persistent-lane registry. The files under
[`docs/agent-worklogs/`](agent-worklogs/) are append-only audit records for
lane handoffs, evidence, decisions, gates, blockers, and allowed next actions.
The stable Supervisor-centered messaging protocol and active authorized task
are in [`docs/integration/INTEGRATION_POLICY.md`](integration/INTEGRATION_POLICY.md)
and [`docs/integration/CURRENT_STAGE.md`](integration/CURRENT_STAGE.md).
The staged Taxi/PT/Car merge contract and current integration evidence are in
[`docs/HONG_KONG_MULTIMODAL_COST_INTEGRATION.md`](HONG_KONG_MULTIMODAL_COST_INTEGRATION.md).

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
docs/HONG_KONG_TAXI_JAVA_SCORING.md
docs/HONG_KONG_TAXI_LOAD_TEST.md
docs/HONG_KONG_TAXI_SMOKE_TEST.md
docs/HONG_KONG_PHYSICAL_TAXI_DVRP_V1.md
docs/HONG_KONG_PT_ITINERARY_AND_STUCK_GOVERNANCE.md
docs/HONG_KONG_PT_FARE_MODEL.md
docs/HONG_KONG_CAR_COST_MODEL.md
docs/HONG_KONG_CAR_TOLL_NETWORK_MAPPING.md
docs/HONG_KONG_PRIVATE_CAR_TOLL_RATE_APPLICATION.md
docs/HONG_KONG_PRIVATE_CAR_PARKING_EVENT_APPLICATION.md
docs/HONG_KONG_PRIVATE_CAR_ENERGY_APPLICATION.md
docs/HONG_KONG_PRIVATE_CAR_FIXED_OWNERSHIP_APPLICATION.md
docs/HONG_KONG_PRIVATE_CAR_UNIFIED_MARGINAL_COST_INTERFACE.md
docs/HONG_KONG_PRIVATE_CAR_SCORING_ADOPTION_DESIGN.md
docs/HONG_KONG_TRAFFIC_SIGNAL_REGISTRY_2026.md
docs/HONG_KONG_TRAFFIC_SIGNAL_MATSIM_ADOPTION_DESIGN.md
docs/HONG_KONG_TRAFFIC_SIGNAL_TOD_ALL_EXPRESSED_V3.md
docs/HONG_KONG_NO_SIGNAL_ROAD_RUNTIME_AUDIT.md
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

School-bus evidence acquisition and the territory-wide, explicitly inferred
candidate are documented in
`docs/HONG_KONG_SCHOOL_BUS_ROUTE_ACQUISITION.md`. The current v3 candidate
applies an estimated 81.9007% non-tertiary school-bus share to the TCS 2022
HBS SPB aggregate, selects schools with an explicit stage/funding/MTR-distance
probability model, permits zero service, and locks 76 first-party route
identities before generating residual proxy routes. The unfiltered SPB v1 and
all-campus non-tertiary v2 remain historical comparisons; their output
directories are intentionally not copied into the current integration
worktree. All inferred loads,
pickup grid points, times, geometry, and capacities are `proxy_not_adopted`;
they do not replace active PT supply or teleported `school_bus` legs.
The separate v4 derivative road-routes the 2,308 inferred chains on the active
MATSim `car` layer after deterministic proxy pickup-order improvement, leaves
all 76 locked first-party geometries null, and writes a static comparison map.
It has no straight disconnected fallback, but 933 routes contain at least one
undirected-topology fallback and 268 paths exceed 100 km; it therefore remains
manual-review geometry outside production. No interactive map is generated,
and v3 times are not recalculated after reordering.
The v5 constrained derivative makes the 3,439-vehicle ceiling and 60/75-minute
stage limits hard. It retains exactly 3,363 time-valid inferred routes plus 76
locked geometry-null identities, covers 34,151 of 84,099 proxy students, and
leaves 49,948 explicitly unserved. Freed vehicle slots are filled with 3,028
direct one-pickup recovery routes selected by load and verified on the road
network. This is a partial-demand sensitivity candidate, not production
supply; the locked identities still lack geometry for time validation.

The downstream v6 adoption-ready candidate is under
`data/transit/hongkong/processed/matsim_road_pt_school_bus_supply_2026_v6_adoption_ready/`.
It merges all 3,439 v5 identities into the Ferry Core network and schedule,
creates 6,878 morning/afternoon physical routes and departures, and retains
unscaled 19/27/28/50-seat passenger capacities. All 76 first-party identities
receive campus-OD-supported proxy pickups and road geometry; identity is
first-party evidence, while stops, order, time and geometry remain inferred.
All routes pass structural, capacity and 60/75-minute checks and load in MATSim
2026.0. The 2,420 reverse-direction proxy links and two topology connectors are
explicit review items. A bounded Stage 11 allocation and physical-run gate now
exists without seat-capacity competition. Server run31 exits zero: all 884
selected physical school-bus trips board the correct v6 vehicle, with no
ordinary-PT substitution or source-capacity exceedance; three remain aboard
traffic-stuck buses at the 30:00 horizon. V6 is still not current production.

The follow-on no-innovation gate integrates physical ordinary PT, physical
school bus, QNetwork Car, real-driver `car_passenger`, and capacity-free
network Walk in one run; Taxi remains the sole teleported main mode. Ordinary
PT routing cannot see school-bus routes, but TransitQSim retains the full
schedule. This is a technical stability gate only: ordinary ReRoute,
SubtourModeChoice and TimeAllocationMutator remain disabled, and the later
innovation phase is intentionally outside the current scope.

The capacity-constrained first attempt (server run51) is retained as a failed
stress result: physical PT and Walk events were produced, but 60,585 PT
passenger legs remained waiting to board at 30:00 and two bound
`car_passenger` legs were inadvertently teleported after plan preparation.
The binding route is now made stable and post-selection unbound departures
fail closed. An optional unlimited ordinary-PT runtime-capacity switch is used
only to isolate physical execution; it does not alter or validate the adopted
10% PT capacity supply.

The isolated mechanical result is server run56. It exits zero and its physical
audit passes: Taxi accounts for all 64,115 direct main-mode teleport arrivals,
while Car, PT, school bus, Walk and bound `car_passenger` execute physically.
The strict student audit does not pass, however. Of 1,002 final school-bus
choices, 952 depart and 876 board/alight; 76 selected students are stuck, with
no wrong vehicle, ordinary-PT substitution, or seat-capacity rejection. This
is caused by physical Walk accumulating QSim second-rounding at every link:
all 76 miss their first vehicle, and 50 later selected school-bus legs then
cannot depart. Run57 schedules links from continuous due times instead. It
exits zero with 1,002/1,002 school-bus departures and boardings, no wrong
vehicle, PT substitution, or capacity rejection, and a passing physical audit.
One boarded student remains aboard a traffic-stuck vehicle at 30:00, so the
student audit is `validated_with_network_stuck_limitations`. The adopted PT
files remain unchanged, ordinary plan innovation remains frozen, and the later
innovation phase has not started.

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
The subsequent Stage 11 candidate removes aggregate `ride`, combines licensed
Taxi and ride-hailing into exactly 44,000 Taxi legs, and uses a student-to-
student exchange to enforce household-car eligibility for all 2,490 student
`car_passenger` legs. Its exact counts, selective routing repair, limitations,
and artifacts are in `docs/HONG_KONG_NO_RIDE_REALLOCATION.md`. This candidate
does not yet replace the adopted 50-iteration production run.
The bounded 139-household maximum-utility selector and its real pickup/drop-off
waypoint contract are documented in
`docs/HONG_KONG_HOUSEHOLD_MAX_UTILITY_SELECTOR.md`. It compares only the
existing bound and unbound alternatives, creates no new joint trip, and is a
one-iteration technical pilot rather than production demand.
Its validated real-mode successor replaces released candidate
`car_passenger` trips with maximum-utility physical PT or routed Taxi, keeps
passenger Car unavailable without a released or additional household vehicle,
and leaves the other 2,456 passenger abstractions unchanged.
The 2026-08-07 bounded endogenous successor expands this to 384 single-leg
candidates in 240 households, while still reusing only existing driver Car
legs. It selected 288 physical bindings and 96 PT/Taxi releases; 42 people
used different bound/unbound choices by direction. The iteration-0 independent
audit passed, but the result is not an adopted production equilibrium.
The subsequent all-household candidate extension is documented in
`docs/HONG_KONG_ALL_HOUSEHOLD_JOINT_PLAN_INNOVATION.md`. Its current v3
registry screens 9,289 passenger-driver pairs in 5,789 car households,
preserves the original selected plans through iteration 0, allows complete
driver-day Car switches, and releases every unbound original `car_passenger`
trip to routed PT, Taxi, or Walk. `school_bus` remains explicitly closed in
this phase. The iterations 0-1 run13 technical gate selected and classified
2,124 physical joint trips and passed its independent audit; it is not the
adopted production equilibrium.
The real routed taxi base plans have a separate full-scenario, no-simulation
load gate in `docs/HONG_KONG_TAXI_LOAD_TEST.md`. It validates typed
taxi leg attributes, routes, fare-only scoring, and scoring-factory creation
without creating a Controler, QSim, iteration, behavioural calibration, or
taxi fleet.
The subsequent fixed-ASC, iterations 0-1 technical integration gate is
defined in `docs/HONG_KONG_TAXI_SMOKE_TEST.md`. It freezes replanning and
routing, keeps Taxi outside QSim main modes, verifies the live custom scoring
factory, and audits each QSim iteration without introducing a Taxi/DVRP fleet.
The pre-PT-scoring itinerary and stuck governance contract is in
`docs/HONG_KONG_PT_ITINERARY_AND_STUCK_GOVERNANCE.md`. It adds a read-only
prepared-itinerary legality audit and fail-closed event taxonomy without
changing PT fares, plans, supply, demand, capacity, or active scoring.
The subsequent five-layer runtime consumer is documented in
`docs/HONG_KONG_PT_FARE_RUNTIME.md`. It uses exact prepared PT segment
references and hash-locked domestic MTR, Light Rail, GMB, Ferry, and strict
Bus Core rules; unresolved fares stay null, transfer concessions remain
unmodelled, Taxi remains equivalent, and Car remains offline through Stage 7.

The private-car offline cost workspace is under
`data/transport_costs/hongkong/car_cost_v1/` and documented in
`docs/HONG_KONG_CAR_COST_MODEL.md`. Its authoritative release pointer is
`canonical_car_cost_interface_manifest.json`, and the current canonical
offline behavioral-cost interface is exclusively
`unified_marginal_cost_interface_v1/`. The original top-level leg estimates,
validation, and summaries are preserved with their original hashes but marked
`superseded_offline_prototype`: their 1,008 charged legs predate the current
facility-network mapping and physical passage-event reconstruction. The
canonical candidate has 25,858 charged legs, 38,931 confirmed no-charge legs,
and 30,837 physical passage events. Future integration must not read the old
top-level leg totals. Neither version approves or modifies active MATSim
scoring, plans, config, network, facilities, vehicles, or simulation outputs.
The follow-up toll facility-network audit is documented in
`docs/HONG_KONG_CAR_TOLL_NETWORK_MAPPING.md`. It rejects cross-domain
same-number ID collisions, resolves all 19 official toll features through the
official road topology, and produces non-monetary per-leg toll identification
for a later output-repair stage.
The standalone private-car toll candidate built from that mapping is documented
in `docs/HONG_KONG_PRIVATE_CAR_TOLL_RATE_APPLICATION.md`. It constructs ordered
physical passage events, estimates non-observed passage times, and applies
official `PC` flat or typical-workday time-varying rates without changing
MATSim scoring or the existing unified car-cost outputs.
The standalone destination-parking candidate is documented in
`docs/HONG_KONG_PRIVATE_CAR_PARKING_EVENT_APPLICATION.md`. It reconstructs
physical parking events from complete private-vehicle daily chains, preserves
absolute model-day time, and applies low/base/high official-rate-bounded
zone/activity proxies without changing MATSim scoring, toll candidates, or the
existing unified car-cost outputs.
The standalone private-car energy candidate is documented in
`docs/HONG_KONG_PRIVATE_CAR_ENERGY_APPLICATION.md`. It independently
reconstructs source parameters and route distances, applies one explicitly
non-individual representative licensed-fleet proxy, and audits zero-distance
routes without combining energy with tolls, parking, fixed ownership cost, or
MATSim scoring.
The standalone fixed-ownership candidate is documented in
`docs/HONG_KONG_PRIVATE_CAR_FIXED_OWNERSHIP_APPLICATION.md`. It independently
rebuilds the 21,020 used-private-car set, audits official licence and monthly
parking source categories, and writes one partial fixed-cost record per
vehicle and scenario, never per leg. It does not combine the result with
energy, tolls, destination parking, unified car costs, or MATSim scoring.
The unified offline marginal-cost interface is documented in
`docs/HONG_KONG_PRIVATE_CAR_UNIFIED_MARGINAL_COST_INTERFACE.md`. It joins the
three independently audited trip-conditional components by strict canonical
leg identity, retains unresolved and out-of-scope costs as null, and publishes
low/base/high complete-leg totals for audit only. Fixed ownership remains a
separate accounting sidecar. The interface does not approve or modify MATSim
scoring or joint mode-choice calibration.
The subsequent scoring-adoption design and double-counting audit is documented
in `docs/HONG_KONG_PRIVATE_CAR_SCORING_ADOPTION_DESIGN.md`. It finds that the
existing 0.7 currency/km distance term cannot be called HKD or fuel without new
provenance, rejects static iteration-time leg lookup, and defines future
experienced-event and baseline-replay contracts. The design is reviewable but
blocked; it implements no scoring and keeps fixed ownership permanently outside
the current daily behavioral model. That blocked status is historical Stage 3
design evidence; it does not control the later, more narrowly guarded Stage 8A
authorization.
The Stage 8A scoped runtime consumer is documented in
`docs/HONG_KONG_CAR_ENERGY_RUNTIME.md`. It consumes only the hash-locked base
`fuel_or_electricity` rows from the canonical interface, requires exact source
and prepared-route identity, and charges each resolved private-car ordinal
once. Toll, destination parking, motorcycles, and fixed ownership remain
inactive. A nonzero standard Car `monetaryDistanceRate` fails closed without
mutation or economic reinterpretation; no production config or scenario run
is changed.
The Stage 8B confirmed-toll consumer is documented in
`docs/HONG_KONG_CAR_TOLL_RUNTIME.md`. One Car owner composes the unchanged
energy scorer with confirmed base toll only. Confirmed charges retain exact
source and physical facility-link evidence; confirmed no-charge is the only
toll zero. Missing, ambiguous, unconfirmed, changed-route, or non-finite
records fail closed without distance, road-class, route-presence, or candidate
fallback. Parking, fixed ownership, motorcycles, config, and scenario runs
remain outside Stage 8B.
The Stage 8C resolved destination-parking consumer is documented in
`docs/HONG_KONG_CAR_PARKING_RUNTIME.md`. It adds only hash-locked resolved
base destination parking beside energy and confirmed toll. Exact destination,
activity, source-time and route identity are required; the 835 unresolved
private-car rows remain explicit null, 2,929 motorcycles remain out of scope,
and fixed ownership stays outside per-leg scoring. No nearest-location,
candidate, distance or zero-fill inference is introduced.
The exact-SHA server bundle preparation contract is documented in
`docs/HONG_KONG_MATSIM_SERVER_BUNDLE_STAGE8D.md`. It locks the current v2
demand and Ferry Core inputs by SHA256, rejects historical v1/pre-Ferry
defaults, requires a clean exact source SHA and current Taxi/PT/Car JAR class
inventory, and defines a later Supervisor-authorized Linux JDK 25 build and
deployment-manifest interface. It does not authorize server access or a run.
The later optional dynamic private-car runtime is documented in
`docs/HONG_KONG_DYNAMIC_CAR_COST_RUNTIME.md`. It removes the fixed-leg lookup
for candidate and experienced Car routes, uses one shared link energy/toll
rule for routing and scoring, and settles destination parking from experienced
vehicle dwell. Its one-cycle Stage 11 validation is not the adopted production
run; the static Stage 8 runtime remains available as a historical baseline.

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
The separate TPDM Volume 4 three-candidate network experiment is documented in
`docs/HONG_KONG_TPDM_V4_THREE_CANDIDATE_NETWORK.md`. It retains the existing
two-candidate maximum and applies `max(existing, TPDM)` only to physical road
links. It is a non-adopted capacity sensitivity candidate, not the current
production network.
The bounded downstream road-continuity experiment derived from that TPDM3
smoke is documented in `docs/HONG_KONG_ROAD_CONTINUITY_116_CANDIDATE.md`.
It freezes 116 same-street dominant relationships (114 unique downstream
links). Candidate1's virtual-length method is retained only as superseded
provenance. Candidate2 preserves the TPDM3 network byte-for-byte and supplies
114 direct QSim storage capacities through a full road-supply registry, with
`x` continuity lanes as the PCU lower bound and explicit queue-safety floors.
Flow capacity remains independent and unchanged. Candidate2 remains a
non-adopted sensitivity. Its matched no-signal, physical-Taxi PCU-0.05 smoke
completed with exit code 0: completion rises from 74.7509% to 75.6400%, and
the 552,044 trip IDs completed in both cases are 1.210 minutes faster on
average. See the candidate document for the completed-set composition effect
and per-link storage audit.
Candidate3 extends the same explicit-storage lower-bound formula to all 86,417
physical road links: the 114 continuity targets retain their frozen upstream
lane floor, while every other link uses its physical lane count as `x`.
Physical network bytes and every flow capacity remain unchanged. Candidate3
increases effective storage by 18.1603% relative to Candidate2. Its matched
iteration-0 smoke exits 0 and raises completion from 75.6400% to 76.3236%; the
558,734 trips completed in both versions are 2.352 minutes faster on average.
It passes technical acceptance but remains a non-adopted sensitivity pending
calibration and multi-iteration validation.
Candidate4 responds to the Candidate3 blocked-inflow audit without changing
the physical network. It applies an all-or-nothing full-chain rule to short,
same-street lane-drop connectors and gives only complete, unambiguous chains
both a QSim-only TPDM Volume 4 flow floor and storage recalculated from that
flow. Of 90 seeds, 39 complete chains select 57 unique link segments and 51
ambiguous chains are rejected with zero partial selection. A retrospective
audit finds and completes all eight truncated chains in the prior candidate,
including `road_104307_0_r -> road_104308_0_f`. The physical network SHA stays
`2cc70f...7979`. Its matched smoke exits 0 and raises completion only from
76.3236% to 76.4148% versus Candidate3; common completed trips are 0.704
minutes slower and network-wide blocked seconds rise 0.5412%. Candidate4
passes structural/runtime QA but remains non-adopted because the performance
case is mixed.
Candidate5A is the deliberately aggressive follow-up. It gives all 3,134
blocked links a finite 30-second flow buffer and expands all 365
representation-review seeds across local short/deficient connector branches
and cycles. The 365 seeds merge to 231 components covering 1,609 links; 834
links gain QSim flow relative to Candidate4 and 3,656 gain storage. The
physical network remains byte-identical. Its matched iteration-0 smoke exits
0, raises completion to 89.6187%, reduces all-link blocked seconds by 67.5237%
versus Candidate4, and makes the 566,742 common completed trips 9.609 minutes
faster. Stage A passes its initial gate. A later cause audit nevertheless
found 552 residual links blocked for at least six hours. At the user's request
Candidate5B rebuilds their complete
local core chains before attaching a non-merging entry/exit boundary layer.
The corrected build has 14 components covering 2,507 unique links and applies
both the Stage B flow target and 60-second storage floor across each complete
chain. Its matched smoke exits 0, reaches 94.8452% completion, and reduces
blocked seconds 96.1449% versus Candidate5A. The road gates pass, but the
combined gate does not: PT passengers waiting before first boarding fall only
18.55%, showing that the remaining bottleneck is experienced PT timing and
next-day service rather than road supply. Candidate5C is not run. Candidate5A
and Candidate5B remain opt-in, non-production sensitivities; see
`HONG_KONG_ROAD_CONTINUITY_116_CANDIDATE.md`.
The follow-up experienced-PT/day-2 candidate preserves all original
line/route/stop IDs, calibrates route-stop and 15-minute timing from the
Candidate5B frozen events, and adds 3,322 departures for 24:00--30:00. Its
matched smoke exits 0, raises completion from 94.8452% to 96.3699%, and cuts
combined unresolved PT states by 28.97%. It passes the smoke gate but is not
adopted without repeat-seed and multi-iteration validation; see
`HONG_KONG_EXPERIENCED_PT_TIMETABLE_V1.md`.
The v1 demand build created a route-specific stop-link schedule copy under
`data/matsim_agents/hongkong/typical_weekday_5pct_v1/`; v2 uses the active
Ferry Core v1 cap010 supply instead. Representative vehicle
types, inferred rail consists, and one-vehicle-per-departure assumptions should
still be replaced when route-specific fleet allocation and vehicle blocks are
available.

The separate offline public-transport fare audit is documented in
`docs/HONG_KONG_PT_FARE_MODEL.md` and stored under
`data/transport_costs/hongkong/pt_fare_v1/`. It inventories all 3,613 active
transit routes, preserves official TD and MTR sources under mode-specific fare
semantics, matches official route/station identifiers to MATSim, and audits
whether every generic PT passenger main leg is chargeable. The canonical
machine-readable entry points are
`canonical_pt_fare_interface_manifest.json`, `pt_fare_layer_registry.csv`, and
`pt_fare_release_validation.json`. There is no global adult-Octopus basis:
MTR and Light Rail are adult Octopus, whereas GMB, Ferry, and strict Bus
amounts have source-specific published-amount semantics with passenger/payment
basis unspecified. Bus Core and the B/C/D coverage-first Bus simulation
candidate remain separate layers.

The former cross-mode distance-median trip estimate from commit `c7be4a` is
withdrawn. Current generic PT legs lack actual mode, line, route, direction,
boarding/alighting stop, and transfer evidence, so all 557,104 `cost_hkd`
values remain null with quality `U`; unresolved is not a zero fare. A future
integration requires a runtime or post-routing explicit PT itinerary and is
not approved for MATSim scoring or joint mode-choice calibration. The audit
does not modify the adopted MATSim plans, config, scoring, network, schedule,
vehicles, or runner. Transfer concessions remain explicit null fields. The separate
`mtr_station_od_v1/` layer provides auditable adult Octopus quotes only for
future inputs with explicit `train` mode, domestic-versus-Airport-Express
scope, and ordered boarding/alighting station IDs. It does not price the
current generic PT legs; six Airport Express station pairs remain unresolved.
The sibling `light_rail_station_od_v1/` layer supplies adult Octopus base
fares only for explicit ordered Light Rail stop IDs. Its complete 68 by 68
official matrix is kept separate from both MTR scopes; loop and short-turn
route states remain explicit, and transfer concessions are not modelled.

## Hong Kong traffic signals

The conservative 2026 location fusion and its MATSim adoption boundary are
documented in `docs/HONG_KONG_TRAFFIC_SIGNAL_REGISTRY_2026.md`. The subsequent
movement-, conflict-, timing-, pedestrian-, and capacity-aware implementation
design is in `docs/HONG_KONG_TRAFFIC_SIGNAL_MATSIM_ADOPTION_DESIGN.md`. The
2,054-location registry is adoption-ready only as a spatial registry; traffic
signals are not enabled in the production scenario. They are available only
through the explicit Stage 11 `--traffic-signals` pilot path documented in the
adoption design. The former eight-junction `pilot_v1` is retained only as a
historical mechanical baseline: its conflict-graph stage colouring was not a
transcription of the published arrows. The independent
`pilot_v2_diagram_inferred` audit initially activates only `TS_K006` with 4
non-U-turn movement signals and 3 diagram-derived groups; 7 examples remain
deferred. The generic launcher can accept v2 only when it is explicitly staged
as the signal payload; no v2 runtime or production adoption exists. The
territory-wide Stage-1 movement registry, planned 15-minute demand `q`,
observed approach-flow comparisons, and approach TPDM saturation proxy `S` are
documented in `docs/HONG_KONG_TRAFFIC_SIGNAL_TPDM_PROXY_V3.md`. Its status is
`territory_wide_tpdm_proxy_stage1_candidate_not_adopted`; it creates no stage,
timing, controller, signal XML, or production configuration change.
The bounded Stage 1.5 reconciliation reclassifies connector fan-out as a later
grouping issue, assigns shared paths only with unique evidence, and recovers
safe registry primary-node seeds without changing the network. Its status is
`stage1_5_network_expression_reconciled_candidate_not_adopted`; remaining
common-topology repairs are audit-only. City-wide
traffic-signal expansion is currently frozen while the
fixed-route run57 road topology, congestion, stuck vehicles, and path
anomalies are reviewed in
`docs/HONG_KONG_NO_SIGNAL_ROAD_RUNTIME_AUDIT.md`; ordinary PT passengers left
waiting at stops are explicitly outside that road audit.

The first bounded Stage-2 controller candidate is documented in
`docs/HONG_KONG_TRAFFIC_SIGNAL_TOD_TOP100_V3.md`. It selects 100 high-demand,
safely expressible junctions and compiles 96 fixed 15-minute plans per system;
it never applies one AM plan all day. The 9,600-plan candidate and its
capacity-deconvolved network pass static MATSim reference validation. Its
full-population, frozen-innovation runtime at
`/mnt/DiskM/by/hk_stage11_traffic_signals_tod_top100_20260812_run1` also passes
all signal mechanics checks, but relative to no-signal run57 road delay rises
7.65% and road-vehicle stuck rises 3.34%. Its status is therefore
`top100_tod_15min_runtime_validated_performance_not_adopted`; it remains
opt-in and does not change the production network or run manifest.

The follow-on road-hotspot signal baseline is documented in
`docs/HONG_KONG_ROAD_HOTSPOT_MATERIALIZED_SIGNAL_BASELINE.md`. It materializes
only the two run62 repairs into independent network, plans, and transit-schedule
inputs; it explicitly excludes run68 Car-origin work and preserves the two
restricted links as walk-only. The order-preserving candidate11 has runtime
XML files identical to candidate8 and adds mandatory Java validation plus
complete source hashes; the earlier candidate5 also proved the topology and
Top-100-by-96 signal-reference chain but is diagnostic because full XML
reserialization changed runtime entity order. Candidate8's no-signal run7
passes practical equivalence to run62. The paired signal run8 passes all
mechanical and physical-mode checks but increases road delay 12.95% and road-
vehicle stuck 3.52% versus run7. The signal controller is therefore not
adopted and remains opt-in; production metadata is unchanged.

The next static expansion is documented in
`docs/HONG_KONG_TRAFFIC_SIGNAL_TOD_ALL_EXPRESSED_V3.md`. From the same
candidate8 road-hotspot Stage-1 input it applies one uniform geometry/TOD rule
to all 1,930 expressed registry groups. Exactly 1,929 systems are activated;
`TS_OSM_0185` is explicitly excluded because no safe non-U-turn movement
survives the overlap filter. The eight public-diagram examples are ordinary
members of this set and receive no special selection, grouping, or timing.
The 185,184-plan MATSim candidate passes static references and a frozen
release9/run9 runtime gate. All 1,929 systems and 3,742 groups appear with zero
mechanics violations, but iteration-1 road delay is 73,950.69 vehicle-hours
(+41.17% versus no-signal run7) and road-vehicle stuck is 2,276 (+16.18%). It
therefore fails the performance-adoption gate, remains opt-in, and leaves
production metadata unchanged.

The subsequent run10a sensitivity changes only QSim `stuckTime` from 600 to
3,600 seconds. It is not adopted: iteration-1 road `stuckAndAbort` rises from
2,276 to 13,552 and delay rises from 73,950.69 to 136,771.83 vehicle-hours;
11,518 of the new stuck events occur at the 30:00 terminal bucket. The longer
threshold retains blocked vehicles and propagates queues rather than resolving
the underlying signal/network congestion.

The local candidate9 corrective rebuild retains run9 as a failed historical
baseline. It assigns each incoming link to one signal system, deactivates all
systems with fewer than two modeled vehicle stages, and records bounded
geometry-stage decisions for the 25 worst run9 systems. Static validation
passes for 1,445 active systems, but no new frozen runtime A/B has yet been
completed; production inputs remain unchanged.

The local candidate10 derivative performs an all-network short-block corridor
search and implements 14 of 40 demand-valued candidates after fail-closed
topology, exclusivity, cycle, saturation, alignment and TOD-boundary safety
checks. It changes only fixed daily plan offsets for 33 of 1,445 systems;
cycles, green splits, groups, movements, network and capacity remain identical
to candidate9. Static validation passes, but release11/run11 runtime A/B
rejects it: delay is 71,585.16 vehicle-hours and road-vehicle stuck is 2,422;
47 cycle discontinuities occur in 11 offset systems at 15-minute boundaries.
Candidate10 remains rejected and production inputs are unchanged. Because
Candidate9 has no separate runtime run, the run9-to-run11 delta represents the
combined Candidate9-plus-corridor package rather than an offset-only effect.

Candidate11 repairs the 47 corridor systems' TOD boundary continuity without
a continuous-clock controller; frozen run12 has zero runtime cycle
discontinuities but still fails the road-performance gate. Follow-on opt-in
run13e opens ordinary route, mode and departure-time innovation while keeping
household escort and student-school choices as a protected joint module. It
completes iterations 0--10: 9,411 aligned Car legs change route and 87,173
retained-PT trips change first boarding time, while QSim `lost` falls from
5,993 to 300. The strong shift to Walk makes this an integration/stability
result, not a calibrated or adopted production scenario. Full provenance is
in `docs/HONG_KONG_TRAFFIC_SIGNAL_TOD_ALL_EXPRESSED_V3.md`.

The subsequent opt-in Candidate11 20-QSim Taxi/Walk sensitivity is documented
in `docs/HONG_KONG_CANDIDATE11_OPEN_TAXI_WALK_20QSIM.md`. It opens Taxi to
ordinary mode innovation with an explicit PCU-1 road proxy, introduces
adult/student fare coefficients and cumulative main-trip Walk overtime, and
limits protected household/student mode changes to QSim iterations 5, 10 and
15. Corrected run14b completes QSim iterations 0--19 with exit code 0. It is a
completed sensitivity, not a production input.

The finite-fleet successor is documented in
`docs/HONG_KONG_PHYSICAL_TAXI_DVRP_V1.md`. It replaces 385,820 person-local
Taxi road proxies with an opt-in 15,500-vehicle MATSim Taxi/DVRP fleet: Urban
13,083, New Territories 2,353, and Lantau 64. Vehicles have inferred fixed-
seed start links, one staggered 18-hour service window, capacity four, and an
initial PCU prior of 1.0. Passenger waiting is event-derived and receives a
larger time penalty than in-vehicle Taxi time. The 0.5% run25 smoke gate exits
zero and conserves all 2,717 requests, but its p90 wait is 75,444 seconds and
531 requests are still waiting plus 767 onboard at the horizon. It therefore
proves execution and accounting only. The full 5% fixed-plan A/B gate now exits
zero for both the proxy (`gate_proxy_run5`) and physical PCU-1
(`gate_pcu1_run2`) executions. Physical Taxi adds 18 QSim-lost and 158
Walk-stuck agents relative to the proxy, so PCU 1.0 passes the bounded
congestion gate and no TPDM/lower-PCU candidate is activated. Formal run3
completed iterations 0--4, then exposed a legitimate zero-distance Taxi route
returning no Taxi leg during the QSim-5 protected selection. The selector now
marks that Taxi alternative unavailable instead of dereferencing an empty
result. Formal run4 is a historical pre-Candidate5B attempt. Candidate5B
formal run1 completed iterations 0--8, then failed in iteration 9 when
concurrent access corrupted MATSim 2026.0's plain teleportation
`PriorityQueue`. Its main thread exited, but a non-daemon memory observer left
the Java PID alive and exposed a process-only heartbeat blind spot. The
residual process was terminated after PID/command/thread-state verification
and the immutable failed directory was preserved. Run2 then completed
iterations 0--4 and reached the iteration-5 QSim before a `jcmd` thread dump
confirmed a Java-level lock inversion between the teleportation engine and
QSim state monitor. Its exact process was terminated after evidence capture;
run2 is preserved with exit code 143. Run3 used Candidate5B road supply,
Candidate11 TOD signals, calibrated/day-2 PT, 15,500 physical Taxi vehicles at
PCU 0.05, a 30:00 horizon, and retained stuck vehicles. It uses 16 threads,
ends innovation after iteration 34, and applies protected joint selection at
5, 15, 25, and 35. Run3 uses JAR SHA256
`fb9457792d15efe98e695522755c50888dda1fa9eed85e1923d1ba42f3728897`.
Its teleportation collections use a narrow dedicated lock which is always
released before events or QSim callbacks. Run3 completed iterations 0--42 but
deadlocked in iteration 43 near 18:00 on a second lock cycle: QSim main held
the agent-state monitor while entering the household escort engine, while an
events worker held MATSim's outer per-handler monitor and called back into
QSim. The exact thread dump is preserved in run3 and the verified process was
terminated with exit code 143.

The household event handler is now a separate forwarding object, so MATSim's
outer event lock is never the engine state lock needed by QSim departures.
The reverse-lock regression, iteration-checkpoint binding restore, launcher
tests, and all 183 Maven tests pass. The recovery profile reads run3's complete
iteration-40 plans, restores exactly 3,378 frozen physical bindings, runs
iterations 41--49, and cannot repeat the 5/15/25/35 joint selection. The first
recovery attempt (`payload4`/`release4`/`run4`) exited before QSim because the
restorer treated two geometrically equivalent catalog candidates as an
ambiguous binding. Selected passenger legs already persist the exact stable
candidate ID, so the corrected restorer requires that ID before checking the
driver, vehicle, and route. Run4 remains preserved with exit code 1; the
successor immutable suffix is `...formal50_resume40_{payload5,release5,run5}`.
Run5 started on 2026-08-20 from commit `af48734` with shaded JAR SHA256
`335ca4ed28227ed31fabb623466485719a0dfbeedca5ed1c9b51263ba708a765`;
it restored all 3,378 bindings but exited with code 1 in iteration 41 because
stock `PrepareForSim` replaced the bound passenger/driver `Leg` objects and
removed their custom identity attributes. The fix adds a one-shot
`BeforeMobsim` refresh which resolves each binding by stable candidate ID,
reattaches it to the prepared leg objects, recomputes leg indices, and restores
the saved driver waypoint route. Replacement-leg and lock-order regressions
and all 183 Maven tests pass. Run5 remains preserved; automation 50 tracks the
successor immutable suffix `...formal50_resume40_{payload6,release6,run6}`.
This is explicitly a checkpoint recovery rather than a bit-identical one-JAR
0--49 run. Run6 uses commit `8b1bf6e`, JAR SHA256
`693bed17d1769d49a50c0c704a4e5fe471e6650d9325f96ca8bf3704e2b233c0`,
completed iterations 41--49, shut down normally, and recorded exit code 0.
Final completion is 742,189 / 743,614 trips (99.8084%); Taxi accounting is
186,161 submitted = 186,144 completed + 17 waiting. There are zero
pre-horizon stuck-and-abort events; all 1,398 aborts occur at the 30:00
boundary. The recovery and accounting gates pass, but the result remains a
non-production sensitivity pending substantive calibration review.

## Candidate5B signal A/B (non-production)

The matched Candidate5B signal A/B keeps the original plans and PT supply,
adds only Candidate11 safe-boundary TOD signals, and exits zero after a
combined signals-plus-explicit-road-supply factory repair. Completion rises
from 94.8452% to 97.1698% (+17,286 trips), while the 704,685 trips completed in
both arms take 1.835 minutes longer on average. Signals cut stuck states and
flow-override-link blocking but create bounded queues on more approaches. See
`HONG_KONG_CANDIDATE5B_SIGNAL_AB.md`.
With those signals held fixed, the experienced PT/day-2 follow-up rebuilds
ordinary PT itineraries and raises completion again to 98.4483%; common trips
become 1.809 minutes faster and unresolved PT passenger states fall 45.54%
relative to the original-PT signal arm. The follow-up schedule attribution
shows that all 850 regular-PT road-state aborts occur exactly at 30:00: 843 are
day-2 vehicles and 840 of those are scheduled to terminate after the horizon,
while original-service road aborts fall from 9 to 7. They are reported as
horizon censoring rather than pre-horizon road stuck; the result remains
non-production pending the active multi-iteration sensitivity. See
`HONG_KONG_EXPERIENCED_PT_TIMETABLE_V1.md`.
