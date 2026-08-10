# Hong Kong final modeling workflow

## Purpose and authority

This document is the concise source of truth for the adopted Hong Kong
fixed-link OD and MATSim workflow. It identifies the production inputs,
scripts, outputs, simulation parameters, and visualization. Topic-specific
documents retain detailed methodology and QA.

Use this precedence when documents disagree:

1. `AGENTS.md` for repository operating rules.
2. `cities/hongkong/city.yaml` and `runs/hongkong/run_manifest.json` for
   adopted paths and run identity.
3. This document for the end-to-end workflow.
4. Topic-specific documentation for methods and limitations.
5. Historical scripts and outputs only for provenance or sensitivity analysis.

## Current production scenario

| Item | Adopted value |
|---|---|
| Model boundary | Hong Kong fixed-link boundary |
| CRS | `EPSG:32650` |
| Spatial units | 1,585 grids |
| Nominal cell size | `920.658900389797 m` |
| Calibrated population | 7,352,309 |
| Resident representation | 5% |
| Total simulated agents | 385,820 |
| Work OD | Hong Kong Census-projected WEDAN OD |
| School OD | DCCA-constrained student-school assignment |
| Border/visitor demand | PT-accessibility V2 |
| Plans | v2 multi-activity and mode-choice plans |
| PT supply | Ferry Core v1 |
| PT passenger capacity | 10% of full-scale references |
| Bus/GMB road PCU | 5% of full-scale PCU |
| Road flow capacity factor | `0.1` |
| Road storage capacity factor | `0.1` |
| MATSim iterations | 50 |
| Final local visualization | `formal_50it_ptfixed_ferry_activity_simwrapper` |

## End-to-end adopted workflow

### 1. Boundary and spatial units

Purpose:

- build the fixed-link Hong Kong model boundary;
- exclude disconnected islands without modeled fixed road links;
- generate the 1,585 regular grid regions.

Key scripts:

```text
scripts/hong_kong_single_city/data_preparation/prepare_hong_kong_boundary.py
scripts/hong_kong_single_city/feature_engineering/build_hong_kong_fixed_link_grid.py
```

Production outputs:

```text
data/boundary/hongkong/processed/hong_kong_fixed_link_boundary_wgs84.geojson
data/boundary/hongkong/processed/hong_kong_fixed_link_boundary.geojson
data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/
  CityAndRegionSplit/hong_kong_fixed_link_grid/regions.shp
```

Details: `docs/HONG_KONG_BOUNDARY_PREPARATION.md` and
`docs/HONG_KONG_FIXED_LINK_GRID.md`.

### 2. Population, imagery, POI, and distance features

Adopted inputs:

- LSUG-calibrated WorldPop age/sex raster;
- Esri World Imagery;
- integrated iGeoCom plus OSM POIs;
- centroid Euclidean grid distance matrix.

Key scripts:

```text
scripts/hong_kong_single_city/data_preparation/calibrate_hong_kong_worldpop_to_lsug.py
scripts/hong_kong_single_city/data_preparation/merge_hong_kong_igeocom_osm_pois.py
scripts/hong_kong_single_city/feature_engineering/build_hong_kong_population_features.py
scripts/hong_kong_single_city/feature_engineering/build_hong_kong_integrated_pois_features.py
scripts/hong_kong_single_city/feature_engineering/build_hong_kong_remoteclip_imgfeat.py
scripts/hong_kong_single_city/feature_engineering/build_hong_kong_grid_dis_matrix.py
```

WEDAN node features have dimensions:

```text
worldpop.npy: (1585, 2)
demos.npy:    (1585, 36)
pois.npy:     (1585, 34)
imgfeat.npy:  (1585, 1024)
dis.npy:      (1585, 1585)
```

### 3. Work OD

The adopted model freezes the WEDAN checkpoint, removes the historical Fuzhou
feature scaler and Fuzhou OD quantile mapping, uses Hong Kong `local_minmax`
features, ensembles seeds `666/667/668`, and fits the 18-parameter LSUGx3
calibration layer with 18-district spatial holdout validation.

Production matrices:

```text
data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/
  CommutingODFlows/hong_kong_fixed_link_grid/hk_scaler_calibration_v1/final/
    generation_hk_generalized.npy
    generation_hk_census_projected.npy
```

`generation_hk_census_projected.npy` is the production fixed-work OD used by
the MATSim demand workflow. `generation_hk_generalized.npy` is retained for
generalization and sensitivity analysis.

Details: `docs/HONG_KONG_WEDAN_INPUTS_AND_INFERENCE.md`.

### 4. Student-school OD

The adopted student demand uses DCCA study-place flows, official school
locations, Education Bureau enrollment margins, calibrated school-age
population, New Town geometry, and TCS 2022 mechanized HBS controls.

Production directory:

```text
data/school/hongkong/processed/student_school_od_2022/
```

Canonical assignment:

```text
student_school_assignment_od.parquet
```

Student counts, daily HBS trips, and boarding-equivalent outputs are different
units and must not be interchanged.

Details: `docs/HONG_KONG_STUDENT_SCHOOL_OD.md`.

### 5. Border and visitor demand

The adopted version preserves Immigration Department control-point margins and
uses HKTB 2026 Q1 purpose structure, CBTS/TCS priors, hotel structure, POIs,
and six-period MATSim public-transport generalized-time skims. Later activity
choices depend on accommodation or the preceding activity, not repeatedly on
distance from the arrival control point.

Production directory:

```text
data/tourism/hongkong/processed/
  arrival_departure_od_2026_typical_weekday_pt_access_v2/
```

Key outputs include:

```text
arrival_bcp_to_grid.npy
departure_grid_to_bcp.npy
visitor_internal_grid_od.npy
synthetic_visitor_tours.parquet
resident_border_events.parquet
pt_generalized_time_skims.npz
```

Details: `docs/HONG_KONG_ARRIVAL_DEPARTURE_OD.md`.

### 6. Synthetic households and vehicles

Full-scale synthetic households combine Census household/person marginals with
TCS 2022 private-vehicle controls. The 5% demand workflow samples whole
households while retaining household membership, vehicle ownership, and
designated-driver relationships.

Production directory:

```text
data/matsim_agents/hongkong/synthetic_households_tcs2022/
```

Details: `docs/HONG_KONG_SYNTHETIC_HOUSEHOLDS.md`.

### 7. Road and public-transport supply

Road speeds, lanes, and capacities use the 2026 second-generation road network,
the 2026-07-22 detector data, 2019-2024 ATC evidence, TPDM capacity references,
and OSM class/lane evidence. The MATSim network stores full-scale link
attributes.

The adopted PT supply retains bus and GMB on the road network, uses 5% bus/GMB
PCUs, includes MTR and Light Rail, and adds the 21 accepted Ferry Core v1
routes. All PT passenger capacities use 10% of full-scale references.

Production supply:

```text
data/transit/hongkong/processed/
  matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_ferry_core_v1_cap010/
    network.xml.gz
    transitSchedule_5pct.xml.gz
    transitVehicles_10pct.xml.gz
```

Supply QA:

```text
nodes:          81,205
links:         117,989
transit routes: 3,613
departures:    159,967
vehicle types:      28
```

Route continuity and reference QA have zero errors.

Details:

- `docs/HONG_KONG_ROAD_SPEED_CAPACITY.md`
- `docs/HONG_KONG_MATSIM_PUBLIC_TRANSPORT_DATA.md`
- `docs/HONG_KONG_ROAD_CLASS_LANE_FINAL_DECISIONS.md`

### 8. MATSim agents and plans

The v1 directory is the compulsory work, school, escort, and border baseline.
The adopted v2 workflow adds TCS-controlled shopping, dining, leisure, social,
medical, and personal-business tours and enables household-aware mode choice.

Production directory:

```text
data/matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice/
```

Production inputs:

```text
plans_routed_5pct_v2.xml.gz
facilities_5pct_v2.xml.gz
privateVehicles_5pct.xml.gz
config_hong_kong_5pct_v2_activity_modechoice_50it.xml
```

The population contains 385,820 agents. The v2 unrouted plans contain 743,614
main legs; the routed plans contain 879,050 legs after PT access, transfer, and
egress expansion.

Details: `docs/HONG_KONG_MATSIM_AGENTS_5PCT.md`.

### 9. Offline private-car cost audit

The read-only private-car cost model v1 estimates low/base/high:

- representative fleet-average fuel or electricity cost;
- private-car tolls confirmed from complete route link sequences and official
  GDB toll feature IDs;
- TCS-zone, activity, arrival-time, and duration-based destination parking;
- one partial fixed vehicle-day ownership record per used private car.

Production audit directory:

```text
data/transport_costs/hongkong/car_cost_v1/
```

This is an auxiliary offline audit. It does not change
`car monetaryDistanceRate`, global money utility, mode choice, or any
production MATSim input. The independently rebuilt energy, toll, and parking
candidates are exposed through a strict, null-preserving unified marginal-cost
interface; fixed ownership remains an accounting-only sidecar. Neither this
interface nor the underlying candidates approve MATSim scoring adoption. The
follow-up event-level scoring design is also blocked: the existing distance
money term has unverified currency/economic semantics, 835 parking events are
non-randomly unresolved, and no baseline replay has been approved or run.
Details: `docs/HONG_KONG_CAR_COST_MODEL.md` and
`docs/HONG_KONG_PRIVATE_CAR_UNIFIED_MARGINAL_COST_INTERFACE.md`, plus the
design-only audit in
`docs/HONG_KONG_PRIVATE_CAR_SCORING_ADOPTION_DESIGN.md`.

### 10. Final simulation and visualization

Adopted simulation parameters:

```text
iterations:                     50
flowCapacityFactor:             0.1
storageCapacityFactor:          0.1
transit passenger capacity:     0.1
bus/GMB PCU factor:             0.05
QSim period:                    00:00-30:00
threads:                        8
```

The complete raw final output remains on the laboratory server:

```text
/mnt/DiskM/by/hk_matsim_5pct_ptfixed_ferry_activity_v1/
  runs/formal_50it_v1/output
```

The final compact local SimWrapper project is:

```text
runs/hongkong/outputs/formal_50it_ptfixed_ferry_activity_simwrapper/
```

The detailed corrected particle animation is:

```text
runs/hongkong/outputs/formal_50it_ptfixed_ferry_activity_simwrapper/
  particle-flow-detailed-road-corrected/
```

Run identity and comparison projects are recorded in
`runs/hongkong/run_manifest.json`.

## Historical products not used by default

| Historical product | Current role |
|---|---|
| Fuzhou-scaled Hong Kong `generation.npy` | Historical WEDAN comparison only |
| Census global-unit and early area-scaled matrices | Diagnostic unit inference |
| `generation_hk_generalized.npy` | Sensitivity/generalization, not production MATSim work demand |
| Euclidean border OD V1 | Historical border-demand baseline |
| `matsim_road_pt_supply_2026_typical_weekday` | No-ferry upstream base supply |
| `matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_v1` | Ferry-builder upstream dependency |
| `typical_weekday_5pct_v1` | Compulsory-demand baseline and v2 input |
| `formal_50it_v2_simwrapper` | Earlier pre-Ferry comparison |
| `formal_50it_ptfixed_baseline_simwrapper` | PT-rerouted baseline comparison |

Do not delete these products when cleaning documentation. They preserve
provenance and support sensitivity checks, but they must not be presented as
the adopted final scenario.

## Reproduction order

For a clean rebuild, follow this dependency order:

1. boundary, WorldPop calibration, imagery, POI integration, and grid;
2. WEDAN node features and distance matrix;
3. Hong Kong scaler experiments and LSUG calibration;
4. student-school and PT-accessibility V2 border demand;
5. synthetic households and vehicles;
6. calibrated road network and map-matched PT supply;
7. Ferry Core v1 and 10% PT vehicle capacities;
8. v1 compulsory agents, then v2 activity enrichment;
9. MATSim route/load validation;
10. formal 50-iteration simulation and SimWrapper export.

Do not rerun expensive or quota-limited acquisition merely because processed
outputs exist. Verify source manifests and determine whether the requested
change actually invalidates an upstream stage.

## Multimodal-cost Stage 11 technical validation

The 2026-08-05 fixed-canonical-plan joint-scoring-stack run completed
iterations `0..10` with exit code `0` at
`/mnt/DiskM/by/hk_stage11_direct_10it_fixed_plans_20260805_run9`. It is a
technical cost-integration stability product, not a replacement for the
adopted 50-iteration production run or local final visualization above. The
static canonical Car costs require fixed route/mode/time plans in this test;
dynamic cost-aware replanning remains future work. See
`docs/integration/stage-briefs/STAGE_11_JOINT_STABILITY_5_10_ITERATIONS.md`.
The run used `plans_routed_5pct_v2.xml.gz`, which contains zero actual
`mode=taxi` legs; Taxi-assigned demand remains encoded as `ride`. It exercised
live Car and PT paths but only configured/injected the Taxi scorer. It must
not be cited as full simultaneous Taxi/PT/Car runtime coverage.

The subsequent no-`ride` candidate completed iterations `0..10` with exit
code `0` at
`/mnt/DiskM/by/hk_stage11_taxi_44000_no_ride_20260806_run14`, reusing the
single release
`/mnt/DiskM/by/hk_multimodal_cost_stage11_taxi_44000_no_ride_20260806_release11`.
Its final plans contain Taxi `44,000`, `car_passenger` `2,734`, `school_bus`
`9,626`, and `ride` `0` legs. All 11 iterations retained fixed mode shares;
the log contains zero errors, exceptions, scoring-schedule mismatches, or PT
route removals. Iteration 0 experienced 43,966 Taxi, 557,188 PT, and 60,793
Car legs, so the Taxi/PT/Car stack and the composed Car energy/toll/parking
owner all received live callbacks. Positive charge incidence by individual
Car subcomponent remains uninstrumented. This is a bounded technical
validation with route/mode/time innovation frozen, not a new calibrated or
adopted 50-iteration production run. Allocation, eligibility, routing repair,
and provisional passenger-mode scoring are documented in
`docs/HONG_KONG_NO_RIDE_REALLOCATION.md`.

The subsequent read-only household candidate audit finds a real
same-household private-car driver somewhere in the current plans for 2,254 of
the 2,734 `car_passenger` legs, but only 280 legs directly match an existing
Car leg and only 139 people have a complete same-driver return tour. The 139
complete pairs exactly reproduce the legacy accepted school-escort pairs.
Household car ownership alone must not be interpreted as an executable joint
trip.

A subsequent iteration-0-only physical pilot at
`/mnt/DiskM/by/hk_stage11_school_escort_physical_20260806_run4` bound those 139
students' 278 legs to the identified drivers' actual private-car QVehicles,
with all innovation strategies frozen. It exited `0` and passed the event
audit: 273 legs completed physically, 135 students completed both legs, no
bound leg teleported, and all 278 outcomes were classified. One bound leg was
stuck while onboard, three return pickups failed after the driver became
stuck on the approach, and one subsequent leg was skipped following the prior
failure. This validates the physical event mechanism, not a household joint
selector; the other 2,456 `car_passenger` legs remain teleported.

The next isolated run at
`/mnt/DiskM/by/hk_stage11_school_escort_joint_reroute_20260806_run4` completed
`it.0`, applied one fixed-binding `JointReRoute`, and physically validated the
result in `it.1`. Of 278 driver legs, 208 changed link sequence and 70 remained
unchanged; all passenger/driver leg keys, vehicles, and route endpoints were
preserved. The final iteration completed 274 physical passenger legs, retained
135 complete student round trips, generated zero bound teleported arrivals,
and classified the other four outcomes as one onboard stuck and three
driver-stuck-before-pickup cases. The fixed-route multimodal-cost module was
intentionally excluded because its Car energy/toll/parking tables cannot price
new routes. This is binding-under-rerouting evidence, not cost-aware replanning
evidence.

The dynamic-cost successor at
`/mnt/DiskM/by/hk_stage11_dynamic_car_joint_reroute_20260806_run4` enabled the
complete Taxi/PT/Car scoring stack during the same two-QSim, one-JointReRoute
cycle. Energy and toll were calculated from arbitrary candidate links by the
same rule later applied to actual link entries; destination parking used the
actual facility and vehicle dwell. It exited `0` and passed all joint audit
checks. Of 278 bound driver legs, 202 changed route and 76 remained unchanged,
with zero binding identity failures. Iteration 1 recorded 5,812,513 priced Car
link entries, 26,034 toll entries, 36,791 nonterminal parking settlements,
positive HKD totals for all three components, and zero parking-facility
mismatches. Final scores were finite and mode totals were unchanged. The final
physical classification was 273 completed legs, one onboard stuck, and four
driver-stuck-before-pickup cases, with zero bound teleportation. See
`docs/HONG_KONG_DYNAMIC_CAR_COST_RUNTIME.md`. This is still a bounded technical
pilot with ordinary route/mode/time innovation frozen, not the adopted
50-iteration production result.

The subsequent deterministic household-selector pilot at
`/mnt/DiskM/by/hk_stage11_household_max_utility_20260806_run3` compared exactly
the bound and unbound alternatives for the same 139 complete school-escort
pairs. It generated no new pair and used neither choice probabilities nor a
driver participation constraint. Passenger utility was limited to
`-1.5 - 6 * travel_time_hours`; every bound route explicitly passed the real
pickup and drop-off links. The selector chose 64 bound and 75 unbound
households, including 33 forced unbound by hard schedule infeasibility. The
run exited `0`. Its independent event audit passed: 127 of 128 active bound
legs completed at exact vehicle-link waypoints, the remaining passenger was
stuck onboard, no bound leg teleported, no unbound candidate boarded a
vehicle, and all active bindings were classified without residual state. See
`docs/HONG_KONG_HOUSEHOLD_MAX_UTILITY_SELECTOR.md`. This is a one-iteration
mechanism validation, not endogenous joint-trip generation or equilibrium.

The real-mode successor at
`/mnt/DiskM/by/hk_stage11_household_real_mode_20260806_run10` removes
teleported `car_passenger` from the unbound alternative for those same 139
candidate households. Each released passenger trip chooses maximum utility
between a SwissRailRaptor physical PT itinerary and a routed, fare-scored Taxi
itinerary; passenger Car is unavailable while the driver retains the household
vehicle and no unused second vehicle is explicit. The run selected 104 bound
and 35 unbound households. Its 70 released trips became 24 PT and 46 Taxi,
with zero released Car. The independent audit passed all checks, including
physical PT routes, Taxi fare attributes, exact completed binding waypoints,
mode-count conservation, finite scores, frozen ordinary innovation, and live
dynamic Car energy/toll/parking scoring. Of 208 active binding legs, 202
completed; the six non-completions were explicitly classified as three onboard
stuck, one driver-stuck-before-pickup, and two simulation-horizon-before-pickup
outcomes. This remains a one-iteration mechanism pilot; the other 2,456
`car_passenger` legs remain teleported.

The bounded endogenous successor at
`/mnt/DiskM/by/hk_stage11_endogenous_household_joint_20260807_run2` expands
the registry to 384 individually selectable passenger legs in 240 households.
It preserves all 278 legacy legs and adds 106 candidates that reuse an
existing compatible same-household driver Car leg; it does not create a new
driver tour. Outbound and return are separate decision units, so one may stay
bound while the other is released. The selector chose 288 bound and 96
released legs, including 51 newly activated physical joint legs. The released
legs became 50 physical PT and 46 routed Taxi trips, with zero released Car.
Forty-two people selected a mixed bound/unbound round trip. The independent
audit passed all checks: all 288 active departures were observed and
classified, 279 completed at exact vehicle waypoints, no bound leg teleported,
no driver-leg/vehicle resource was reused, dynamic Car costs were live, and
ordinary innovation remained frozen. This is still an iteration-0 mechanism
validation, not a calibrated equilibrium or general joint-tour generator.

The all-car-household technical successor at
`/mnt/DiskM/by/hk_stage11_all_household_joint_20260807_run13` screens every
eligible trip in car-owning households rather than only the 384-entry bounded
registry. Its v3 registry contains 9,289 passenger-driver pairs in 5,789
households and excludes pickup/drop-off pairs resolving to one network link.
After an unchanged iteration 0, the maximum-utility selector chose 2,124
physical joint trips, all reusing existing driver Car trips, and released the
remaining original `car_passenger` trips to PT, Taxi, or Walk. The independent
audit classified all 2,124 bindings and passed every check with exit code 0.
Ordinary route/mode/time innovation remained frozen. This validates broad
candidate generation, atomic household composites, dynamic multimodal costs,
and physical waypoint execution; it is not the adopted 50-iteration output or
a calibrated equilibrium.

## Traffic-signal location registry candidate

The adoption-ready location registry under
`data/transit/hongkong/processed/hong_kong_traffic_signal_registry_2026_v1/`
fuses 5,540 OSM `highway=traffic_signals` observations with 37,167 official
Transport Department Traffic Aids point features and the active MATSim Car
network. It resolves the OSM observations to 2,054 conservative physical
signal-location groups; 1,969 have both official and OSM evidence. This is 26
locations (1.282%) above the independent mid-2025 official aggregate of about
2,028 signalised junctions. The official total is a validation benchmark, not
a count-fitting target.

The registry also supplies 8,288 incoming Car-link control candidates for
2,016 groups, but it contains no phase, cycle, green split or coordination
timing. It therefore does not yet modify the active MATSim network/config or
Stage 11 runs. The 263 official-geometry-only clusters remain a separate review
table and are excluded from the default registry to avoid double-counting
large junctions. See `docs/HONG_KONG_TRAFFIC_SIGNAL_REGISTRY_2026.md`.

The follow-on adoption design in
`docs/HONG_KONG_TRAFFIC_SIGNAL_MATSIM_ADOPTION_DESIGN.md` applies the March
2026 Transport Department signal-design rules and digitizes a public
eight-junction AM/PM example as an observed-partial pilot. It replaces direct
incoming-link activation with movement groups, conflicts, explicit transition
and pedestrian clearance, time-of-day evidence classes, and capacity
deconvolution. This remains outside the adopted production supply. It is now
available through an explicit Stage 11 `--traffic-signals` pilot path, so
ordinary production runs without that flag remain unchanged.

The first implementation package is
`data/transit/hongkong/processed/hong_kong_traffic_signals_2026_pilot_v1/`.
It compiles separate AM and PM controls for the eight public-example
junctions: 32 controlled final approaches, 62 movement signals, 26 signal
groups, 3-second amber, 2-second red+amber and 5-second minimum intergreen.
Because MATSim inserts amber after dropping and red+amber before green, the
compiled onset gap is 6 seconds and the static validator confirms the emitted
event-level intergreen is 5 seconds.
Only the 32 approach capacities are replaced by TPDM saturation proxies; all
other network links remain unchanged. Static validation passes with zero
blocking same-stage conflicts and no SHA gate. The movement-to-stage mapping,
offsets and full-day activation remain inferred/missing, and pedestrian phases
are explicitly blocked pending crossing geometry. This pilot is not the
adopted production signal supply.

The accepted AM integration sensitivity is stored at
`/mnt/DiskM/by/hk_stage11_traffic_signals_20260810_run3`. It completed
iterations 0--1 with exit code 0. Runtime audit covered 87,240 signal-state
events and found zero missing groups, conflicting greens, intergreen,
amber/red+amber, or cycle violations; all 32 controlled approaches carried
traffic. The existing physical-mode gate remained valid and all 1,002 selected
school-bus legs completed correctly. However, applying the observed-partial AM
plan all day increased person stuck events from 14,382 in no-signal run57 to
16,631 and reduced controlled-approach entries by 3.43%. It is therefore a
successful mechanical test and an unsuccessful production-performance test;
the active production supply and manifest remain unchanged.

The complementary PM mechanical sensitivity at
`/mnt/DiskM/by/hk_stage11_traffic_signals_20260810_run4` completed iteration 0
with exit code 0. Its 87,238 signal-state events also passed all runtime signal
checks across 8 systems, 26 groups, and 32 active approaches. Its 30:00
lost-agent counter was 10,180, versus 10,074 for AM iteration 0 and 8,738 for
no-signal run57 iteration 0. AM and PM controller files are therefore both
mechanically valid, but neither peak plan is adopted as an all-day schedule.

## Known limitations

### School-bus candidate outside production

`data/school/hongkong/processed/school_bus_proxy_routes_2026_v3_school_probability_locked76/`
is a territory-wide modelling-preparation candidate described in
`docs/HONG_KONG_SCHOOL_BUS_ROUTE_ACQUISITION.md`. It is not an adopted
production input. It applies an estimated 81.9007% non-tertiary school-bus
share, derived from 2021 Census education/mode tables, to the TCS 2022 HBS SPB
aggregate. A school-level probability model then allows 722 of 2,023 campuses
to have zero service and locks 76 first-party route identities before creating
2,308 residual proxy routes. The unfiltered 3,217-route v1 and all-campus
2,893-route v2 remain historical comparisons whose output directories are
intentionally not copied into the current integration worktree. EDB campus
enrolment, locked route loads and all residual routes are modelled; restricted/undigitised
first-party stops and geometry are not reproduced. The active PT supply, 9,626
teleported `school_bus` legs, final run, and visualization remain unchanged.

A downstream geometry-only candidate is available at
`data/school/hongkong/processed/school_bus_proxy_routes_2026_v4_road_matched/`.
It preserves v3 route membership, campuses, loads and the 76 geometry-null
locked identities, improves only inferred pickup order, and routes 2,308 proxy
chains on the active MATSim `car` road layer. It produces a static comparison
PNG, not an interactive map. Of 41,458 waypoint segments, 1,165 require an
explicit undirected-topology fallback and none require a straight disconnected
fallback. Median path length is 54.502 km and 268 routes exceed 100 km, so this
is modelling-preparation geometry requiring manual feasibility review, not an
adopted timetable or operational school-bus supply. Legacy v3 times are not
recalculated after the v4 ordering change.

The stricter downstream v5 candidate is under
`data/school/hongkong/processed/school_bus_proxy_routes_2026_v5_time_split_fleet_cap3439/`.
It uses `floor(4,200 × 81.90069599%) = 3,439` as an absolute one-route/one-peak-
vehicle ceiling. Inferred kindergarten/primary routes must be no longer than
60 minutes and secondary/special routes no longer than 75 minutes. Routes that
still fail after the fleet-budgeted first split are removed; unused slots
recover high-load feasible grids as direct one-pickup routes. The result fills
the ceiling with 3,363 time-valid inferred routes and 76 geometry-null locked
records, retains 34,151/84,099 proxy students, and explicitly leaves 49,948
unserved. All inferred routes pass the hard time threshold, with a 73.98-minute
maximum, but locked first-party records remain time-unvalidated. This partial-
demand candidate and its static map are not adopted MATSim supply; no
interactive map is generated.

The v6 adoption-ready candidate is under
`data/transit/hongkong/processed/matsim_road_pt_school_bus_supply_2026_v6_adoption_ready/`.
It adds all 3,439 v5 route identities to a copy of the Ferry Core network,
schedule and fleet as 6,878 physical morning/afternoon routes and departures.
Passenger capacities remain unscaled at 19, 27, 28 or 50 seats, and all 34,151
retained proxy students fit. The 76 first-party identities receive one nearby
campus-OD-supported proxy pickup and road path each; their identities are
evidence-backed, but pickup membership, times and geometry remain inferred.
Independent structural QA and MATSim 2026.0 loading pass, and no direction
exceeds its 60/75-minute stage limit. The network nevertheless requires 2,420
explicit reverse-direction proxy links and two short topology connectors;
these are physical MATSim links but not verified legal road-direction evidence.
V6 is ready for demand allocation and a no-innovation physical test, but it
does not yet replace the current production supply or teleported student plans.

The demand-preparation step regenerates candidates for all 36,808
day-school students instead of retaining their old selected mode. Across
73,616 independently screened directions it emits fresh PT and Taxi candidates,
distance-limited Walk candidates, and 15,322 route-specific school-bus rows
covering 14,265 trips. Of the old 9,626 teleported school-bus legs, only 1,837
remain physically eligible, while 12,428 legs from other old modes newly gain a
school-bus option. The catalogue has now been exercised in a bounded Stage 11
iteration-0/1 deterministic-choice gate. That gate intentionally omits seat
capacity competition; source capacities remain provenance for a future
capacity-constrained experiment.

The accepted server gate is
`/mnt/DiskM/by/hk_stage11_student_school_mode_20260808_run31`. It exits zero
with all independent core checks passing. The final student modes are 921
`car_passenger`, 307 PT, 884 physical school bus, 21,269 Taxi and 50,235 Walk.
Every selected school-bus trip boards its exact v6 vehicle; none uses ordinary
PT, none boards the wrong vehicle and none exceeds source capacity (peak load
seven). Three boarded students remain on traffic-stuck buses at the 30:00
horizon, so the result is labelled
`validated_with_network_stuck_limitations`, not a complete-day equilibrium.

The next bounded integration gate keeps the same iteration-0/1 selector but
makes every main mode except Taxi physical. Ordinary PT uses TransitQSim and a
SwissRailRaptor routing view from which all `school_bus` routes are excluded;
the complete schedule remains in QSim for exact school-bus candidates. Walk
uses capacity-free road-network paths at 1.34 m/s through a dedicated engine,
so pedestrians produce link-progression events without consuming road
capacity. Car continues to use QNetwork plus common dynamic energy, toll and
parking rules, while bound `car_passenger` uses the real household driver.
The Raptor access execution mode `non_network_walk` is scored with the Walk
parameters. Ordinary ReRoute, SubtourModeChoice and TimeAllocationMutator stay
frozen; this gate does not implement the later innovation phase.

The first full non-Taxi attempt, server run51, retained the adopted 10% PT
vehicle capacities. It proved physical event production but is a failed
stability gate: 60,585 ordinary-PT passenger legs were still waiting before
their first boarding at the 30:00 horizon, 1,445 were aboard, and two newly
bound `car_passenger` legs fell back to teleportation after stock route
preparation changed their preceding leg indexes. The latter is fixed by giving
every selected passenger binding a stable routed leg before
`PrepareForMobsim` and rejecting any unbound post-selection departure. A
separate explicit `--unlimited-ordinary-pt-capacity` option is available only
for the mechanical physical-execution gate. It changes runtime capacities,
not the adopted 10% supply files, and its result must not be presented as PT
capacity validation.

The physical household engine treats a driver's `PersonArrival` on the audited
drop-off link as the terminal waypoint because QNetwork does not guarantee a
separate final `LinkEnter` callback for a destination link. Run54 showed that
this fallback is insufficient when stock `PrepareForMobsim` replaces a selected
driver detour with a direct activity-origin/activity-destination route: the
intermediate passenger drop-off then is never physically traversed. Every
active binding therefore keeps an immutable copy of the selected
pickup/drop-off waypoint route and restores it after stock route preparation,
before QSim agents are created. The arrival fallback still performs real
vehicle removal and passenger-arrival events only when driver arrival and the
audited drop-off genuinely share a link. A different outstanding drop-off is
not rejected inside the arrival callback: the parallel event manager may
deliver that callback before an earlier vehicle `LinkEnter` reaches this
handler. It is resolved by the delayed link event or classified as genuinely
onboard only after the complete event queue drains in `afterMobsim`.

The resulting mechanical gate is server run
`/mnt/DiskM/by/hk_stage11_student_school_mode_20260808_run56`. It completes
iterations 0--1 with exit code zero. Its independent physical audit is
`validated`: Car, ordinary PT, school bus, Walk and bound `car_passenger` all
produce their required physical events, while the 64,115 direct main-mode
teleport arrivals are Taxi only. There are no direct teleported PT, Walk or
`car_passenger` arrivals. In iteration 1, network Walk records 113,612
departures, 113,319 arrivals and 4,088,507 link entries; the household engine
classifies all 4,000 bindings and completes 3,889. This validates the physical
execution wiring, not equilibrium or capacity adequacy.

Run56 deliberately gives ordinary PT unlimited runtime seats to isolate that
wiring; the adopted 10% vehicle file is unchanged. Even without seat rejection,
11,763 PT legs are still waiting before boarding and 1,294 are aboard at the
30:00 horizon across the two iterations, showing remaining traffic/network
completion pressure. The strict student audit therefore remains `failed`:
after household override 1,002 school-bus trips are selected, only 952 reach a
school-bus departure, and 876 board and alight. Seventy-six selected students
are stuck; there is no wrong-vehicle boarding, ordinary-PT substitution, or
source-capacity exceedance, and terminal school-bus load is zero. The missing
events are causally linked rather than two independent groups: all 76 students
miss their first selected vehicle, and 50 of those also have a later selected
school-bus leg which can no longer depart after the first leg aborts.

Event-level diagnosis identifies a Walk clock mismatch. The route scorer sums
continuous per-link travel time, while the first physical Walk engine scheduled
each next link from the integer QSim callback time. This accumulated up to one
extra second per traversed link. One representative passenger was planned to
be ready at 27,486 seconds, reached the stop at 27,497, and missed a school bus
which departed at 27,494. The engine now schedules each link from the previous
continuous due time, so QSim can round only the final arrival once rather than
once per link.

The repaired no-innovation gate is server run
`/mnt/DiskM/by/hk_stage11_student_school_mode_20260809_run57`. It exits zero;
the physical audit remains `validated`, with Taxi alone accounting for all
64,155 direct main-mode teleport arrivals. The student audit records 1,002
selected school-bus legs, 1,002 physical departures and 1,002 correct
boardings: both the 50-leg departure deficit and 76-person missed-boarding set
are eliminated. There are no wrong-vehicle boardings, ordinary-PT
substitutions or source-capacity exceedances. A single correctly boarded
student remains aboard a traffic-stuck school bus at the 30:00 horizon, giving
1,001 alightings/arrivals and the status
`validated_with_network_stuck_limitations`. This residual is a downstream
network-completion advisory, not a recurrence of the boarding defect. Ordinary
plan innovation remains frozen and Step 6 is still not started.

- Work OD is calibrated and Census-projected synthetic demand, not observed
  person-to-person movement.
- DCCA school flows constrain destination classes, not a complete observed
  DCCA-to-school matrix.
- Border-to-activity OD is constrained synthetic demand; no observed
  control-point-to-destination matrix is available.
- Some transit timetables, dwell times, vehicle assignments, and ferry
  capacities are inferred.
- Ferry Core v1 excludes 20 island-access routes whose land access is not yet
  adequately represented.
- Detector and ATC road-flow observations do not cover every road link.
- The adopted 50-iteration production plans still use aggregate `ride` and do
  not create complete taxi, ride-hailing, or school-bus operator fleets. The
  Stage 11 candidate removes `ride`; the earlier household-only iterations
  0--1 gate selected 2,124 physical household joint trips from 9,289 screened
  pairs and released every unbound original `car_passenger` trip to PT, Taxi,
  or Walk. The repaired integrated run57 selector later activates 4,003
  bindings, of which 3,895 complete before the horizon.
  The production-baseline `school_bus` legs remain passenger abstractions. A
  route-specific all-student v6 registry and bounded physical-choice gate now
  exist, but v6 is not yet the adopted production supply; Taxi still has no
  operator fleet.
- Private-car powertrains and destination car parks are not observed at
  vehicle/facility level; the offline car-cost layer therefore uses an
  explicit representative fleet and official-rate-bounded parking proxies.

These limitations must remain visible in publications, validation summaries,
and future model extensions.
