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
- `docs/HONG_KONG_TPDM_V4_THREE_CANDIDATE_NETWORK.md`

The TPDM Volume 4 three-candidate network is an immutable, non-adopted
sensitivity candidate built from the road-hotspot V1 materialized network. It
raises the summed physical-road link-capacity diagnostic by 40.3407% while
preserving topology and every non-capacity link field. It has not replaced the
production supply. A no-signal, physical-Taxi PCU-0.05 iteration-0 smoke raises
completion from 70.5359% to 74.7509% against the otherwise matched old-network
run, but multi-iteration and signal-enabled validation remain open.

The subsequent bounded road-continuity candidate is documented in
`docs/HONG_KONG_ROAD_CONTINUITY_116_CANDIDATE.md`. It is generated from that
TPDM3 smoke's hotspot audit for 114 unique downstream links and 116 frozen
same-street dominant relationships. The adopted design for the experiment is
Candidate2: physical network bytes and all flow capacities remain TPDM3, while
an optional QSim registry directly overrides storage on only those 114 links.
Candidate1's length/lane change is superseded because it altered physical
distance and free-flow time. Candidate2's matched no-signal physical-Taxi
PCU-0.05 iteration-0 smoke exits 0 and raises completion from 74.7509% to
75.6400%; it has not replaced production supply.
Candidate3 is the broader, still non-adopted sensitivity: it applies an
independent lower bound of at least one PCU per physical lane to all 86,417
road links, while retaining the frozen continuity `x` on the 114 targets.
The TPDM3 physical network and all flow capacities remain byte-for-byte and
numerically unchanged. Its matched smoke is recorded in the dedicated road
continuity candidate document: exit 0, 76.3236% completion versus 75.6400% for
Candidate2 and 74.7509% for TPDM3 default storage. It is technically feasible
but has not replaced the adopted production supply.
Candidate4 is a bounded response to the Candidate3 blocked-inflow audit. A
short same-street lane-drop connector is changed only if the entire impaired
chain can be followed to a recovered cross-section; otherwise the seed is
rejected and no chain segment is selected. The 90-seed build accepts 39
complete chains covering 57 links and rejects 51 atomically. All accepted
links receive both a QSim-only TPDM Volume 4 flow floor and storage recomputed
with that flow, while the scenario network remains byte-identical. The
retrospective audit identifies eight Candidate2/3 chains that had stopped one
segment early and now includes each missing segment. Candidate4 is an
optional, non-adopted sensitivity and does not change the production supply.
Its matched smoke exits 0 and reaches 76.4148% completion, only 0.0912
percentage points above Candidate3. Requested/actual storage and flow match,
but common completed trips are 0.704 minutes slower and network-wide blocked
seconds rise 0.5412%; it therefore passes technical rather than performance
adoption.
Candidate5A is a more aggressive QSim-only response. It retains the identical
physical network, gives all 3,134 blocked links a finite 30-second flow buffer,
and expands 365 representation-review seeds through local short/deficient
branches and cycles. The resulting 231 components cover 1,609 links. Its
matched frozen iteration-0 smoke exits 0 and reaches 89.6187% completion;
blocked seconds fall 67.5237% versus Candidate4 and common completed trips are
9.609 minutes faster. The initial Stage A gate passes, but a subsequent cause
audit identifies 552 residual links blocked for at least six hours.
Candidate5B therefore rebuilds complete local chains around those links,
merging core chains before attaching a non-merging entry/exit boundary layer.
Its corrected build has 14 components and 2,507 unique links, with Stage B
flow and 60-second storage floors applied to the complete chain. The matched
smoke exits 0, reaches 94.8452% completion, cuts blocked seconds 96.1449%
versus Candidate5A, and is 3.267 minutes faster on common completed trips.
All road gates pass. The combined gate remains false only because PT waiting
before first boarding falls 18.55% rather than the required 50%; Candidate5C
is not run because further road expansion would confound the experienced PT
timing/next-day-service problem. Both stages remain non-adopted sensitivities.
The separate experienced-PT candidate now fits a route-stop delay shape plus
smoothed 15-minute route shift from Candidate5B events, preserves every
original line/route/stop ID, and adds 3,322 deterministic `__day2` departures
and vehicles for 24:00--30:00. Its matched iteration-0 smoke exits 0 and raises
completion to 96.3699%; waiting before first boarding falls 38.05% and the
combined waiting/onboard unresolved PT state falls 28.97%. All day-2 drivers
execute, while road blocked seconds fall 1.09%. This passes the corrected
smoke gate but remains non-production pending repeat-seed and short
multi-iteration stability checks; see
`HONG_KONG_EXPERIENCED_PT_TIMETABLE_V1.md`.

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

The successor Top-100 time-of-day sensitivity at
`/mnt/DiskM/by/hk_stage11_traffic_signals_tod_top100_20260812_run1` uses 96
fixed 15-minute plans per system and keeps ordinary innovation frozen. The
full-population iterations 0--1 run exits zero. Its iteration-1 audit observes
100 systems, 241 groups and 1,538,332 state changes with zero signal-reference,
conflicting-green, intergreen, transition-duration, or within-bin cycle
violations. Run57 is the strict no-signal control; run62 is excluded because
it enables the road-hotspot repair. Against run57, road delay rises from
62,669.620 to 67,462.307 vehicle-hours (+7.65%) and road-vehicle stuck rises
from 2,307 to 2,384 (+3.34%), although GMB and school-bus stuck improve. This
is a successful mechanical gate but a failed performance-adoption gate. The
candidate remains opt-in; the production supply, city metadata, and run
manifest are unchanged. Full class results and comparison boundaries are in
`docs/HONG_KONG_TRAFFIC_SIGNAL_TOD_TOP100_V3.md`.

The eight-junction package above is now a historical `pilot_v1` mechanical
baseline because its conflict-graph colouring did not read the Stage A/B/C/D
arrows as movement evidence. The independent
`hong_kong_traffic_signals_2026_pilot_v2_diagram_inferred` package corrects
that modelling boundary. It audits all eight source diagrams but initially
compiles only `TS_K006` (Nathan Road / Jordan Road), the sole example where a
high-confidence diagram interpretation is also faithfully enforceable by the
current first-connector topology. Its 4 non-U-turn movement signals form 3
diagram-derived groups over the observed `64/34/32` AM and PM stages; only 4
approach capacities change. The other 7 intersections are explicitly deferred
for clearer movement evidence or lane-level connector reconstruction. Static
AM/PM validation passes. The generic signal launcher can now read v2's own
build summary when v2 is deliberately staged as its payload, but no v2 runtime
has been launched; it does not change the adopted network, city metadata, or
run manifest.

Traffic-signal expansion is now frozen without reverting the opt-in pilot.
The fixed-plan, no-signal run57 iteration-1 road audit is documented in
`docs/HONG_KONG_NO_SIGNAL_ROAD_RUNTIME_AUDIT.md`. It excludes 12,892 ordinary
PT-passenger stuck/waiting events and separately identifies 2,307 road-vehicle
stuck events, 62,669.620 vehicle-hours of road delay, a 97.7735% largest road
strong-component node share, and concentrated path/topology candidates. The
active production supply and run manifest remain unchanged; the next road
work is fixed-supply repair and a paired no-signal/no-innovation rerun, not
signal expansion or combined behavioural innovation.

That first paired sensitivity is now complete as run62. The opt-in
`--road-hotspot-repair-v1` redirects only two audited service-road shortcuts
and synchronises affected population routes, transit vehicle routes, stops,
and activities. Against run57, iteration-1 road delay falls 15.73% and road-
vehicle stuck falls 17.77%. This result is not adopted into the production
network: a residual 1,649.21 vehicle-hour queue remains at the Tate's Cairn
three-lane-to-two-one-lane fork, and persistent short-connector locations need
individual topology/source review. Full paths and metrics remain in
`docs/HONG_KONG_NO_SIGNAL_ROAD_RUNTIME_AUDIT.md`; the run manifest and current
production supply are unchanged.

The traffic-signal branch now has a separate materialized form of exactly
these two repairs. Its scope, hashes, walk-only ordering requirement,
Stage-1/1.5 rebuild, Top-100-by-96 rebuild, and mandatory no-signal equivalence
gate are recorded in
`docs/HONG_KONG_ROAD_HOTSPOT_MATERIALIZED_SIGNAL_BASELINE.md`. It deliberately
excludes all run68 Car-origin/proxy-facility changes and does not alter the
production inputs or enable signals by default. The order-preserving no-signal
run7 passes practical equivalence to run62. Its paired signal run8 exits zero
and passes all signal-state, physical-mode, and student-school-bus checks, but
road delay rises 12.95% and road-vehicle stuck rises 3.52% versus run7.
Accordingly this Top-100-by-96 signal controller is mechanically validated but
not adopted; it remains an explicitly switchable sensitivity.

The subsequent all-expressed candidate is documented in
`docs/HONG_KONG_TRAFFIC_SIGNAL_TOD_ALL_EXPRESSED_V3.md`. It uses the same
road-hotspot candidate8 Stage-1 input and the same 96-bin timing rule. Of
1,930 expressed registry groups, 1,929 retain a safe executable non-U-turn
movement; `TS_OSM_0185` is machine-readably excluded rather than reactivating
an overlap-filtered movement. All eight public-diagram examples use the same
uniform geometry and timing rule. The resulting 185,184 plans and 1,929 MATSim
systems pass static validation. Frozen release9/run9 also exits zero and sees
every system and group with zero signal-mechanics violations. It nevertheless
fails the performance gate: road delay is 73,950.69 vehicle-hours (+41.17%
versus run7) and road-vehicle stuck is 2,276 (+16.18%). It remains an opt-in
sensitivity; the production network, city metadata, and run manifest remain
unchanged.

The local candidate9 corrective rebuild keeps candidate8 and run9 as
historical evidence but enforces exclusive incoming-link control, deactivates
all systems without a competing modeled vehicle stage, and applies audited
bounded stage overrides to 7 of the 25 worst run9 systems. It compiles 1,445
active systems and statically validates with zero duplicate controlled links
or active one-stage systems. Candidate9 has not yet passed a frozen runtime
gate, remains opt-in, and does not change production metadata.

Candidate10 adds a fail-closed short-block corridor search on candidate9.
It identifies 40 demand-valued linear corridors and implements fixed daily
offsets for the 14 that pass exclusive-system, cycle, internal-saturation,
TOD-boundary safety and alignment-error gates. These cover 47 systems; only
33 receive non-zero offsets. Cycles, green splits, movements, signal groups,
network and capacity remain unchanged. Static and MATSim XML validation pass,
and a frozen release11/run11 A/B now rejects Candidate10. Although road delay
falls 3.20% versus all-expressed run9, road-vehicle stuck rises 6.41%; versus
no-signal run7, delay remains 36.65% higher and road-vehicle stuck 23.63%
higher. The event audit also finds 47 cycle discontinuities in 11 offset
systems, all at 15-minute plan boundaries. Candidate10 remains historical and
does not change production metadata.

Candidate11 moves each of those 47 corridor systems' complete 96-plan TOD
boundary grid to its fixed daily offset, so every replacement occurs at a
continuous stage-1 phase position without a new controller. The frozen
release12/run12 iterations 0--1 run exits zero. Its event audit observes all
1,445 systems and 3,243 groups with zero cycle discontinuities, conflicting
greens, intergreen, amber, or red+amber violations; Candidate10's 47 boundary
violations are eliminated. The road gate still fails: iteration-1 delay is
72,010.88 vehicle-hours and road-vehicle stuck is 2,390, respectively 37.47%
and 22.00% above no-signal run7. Candidate11 is therefore mechanically
validated but remains an opt-in research candidate; production metadata and
the no-signal baseline remain unchanged.

The Candidate11 ordinary-innovation integration gate uses the explicit
`--household-joint-plan-with-ordinary-innovation` option. Ordinary agents have
positive route, subtour-mode and activity-time-plus-reroute strategies, so PT
passengers may change departure time and rebuild their scheduled itinerary.
The 47,867 household escort/joint or student candidate people remain inside
their independent joint-choice modules and use `KeepLastSelected` for ordinary
individual replanning. A full-facility parking-zone candidate adds 182,441
strict Census/DCCA point-within assignments and leaves all 14 `border_*`
anchors unpriced. The 22,578 non-special people with a border activity retain
route and time innovation but cannot generate a new Car mode. Failed run13
through run13c attempts are retained as diagnostics. Run13c proved the
parking-universe fix and completed iteration 1, but a previously released
non-candidate `car_passenger` plan returned from plan memory in iteration 2.
Corrected release15/run13d protects every initial passenger-plan person and is
also retained as a failed diagnostic: iteration 2 can still select a temporary
candidate template. Release16 removes those templates after one-shot joint
selection, and completed run13e is the validated integration result described
below. It remains non-adopted.

A same-input run10a sensitivity raises only `stuckTime` from 600 to 3,600
seconds. It is rejected: road `stuckAndAbort` rises from 2,276 to 13,552 and
road delay from 73,950.69 to 136,771.83 vehicle-hours. Of the run10a stuck
events, 11,518 occur in the 30:00 terminal bucket because vehicles retained
longer in queues are aborted at the simulation horizon. The lower 2,034
pre-terminal count therefore does not represent a network improvement.

A second opt-in sensitivity now addresses private-Car activity-link direction
without enabling ordinary innovation. The run62 event audit exposes 15,078
unique initial reverse transitions as `person_id + private_car_trip_ordinal`
observations. `--car-origin-anchor-observations=<csv>` compares the current and
exact reverse-direction anchors with complete production Car routes, jointly
including the previous Car arrival at middle activities, walking access,
travel time, and the shared dynamic energy/toll rules. Only nearby, non-tolled,
non-expressway high-confidence candidates that remove the departure reversal
without creating an arrival reversal are applied. A per-activity proxy
facility keeps the corrected routing link stable under later `ReRoute`, while
dynamic parking canonicalises it to the original facility/TCS-zone identity.
Active household joint driver and passenger legs on either side of the shared
activity anchor are guarded because their stored NetworkRoutes contain
physical passenger pickup/drop-off waypoints. Run63 and run64 are retained as
invalid zero-application diagnostics: the former exposed an overly strict
new-Car-tour test, and the latter exposed an incorrect facility requirement
for facility-free departure activities. Run65 validates 1,708 direct Car
anchor changes with all 3,956 bindings preserved and lost agents reduced from
5,890 to 3,270. The stage-aware run66 also rebuilds the physical Walk access
leg that feeds a `car interaction` anchor. Run66 exposed and rejects a mixed
stage-leg `routingMode` installation; run67 preserves the enclosing Car trip's
routing mode while replacing the physical Walk NetworkRoute. Run67 then
exposed later-tour parking continuity: a non-adjacent earlier Car arrival must
not be moved independently from the later departure. Run68 restricts automatic
application to the first daily Car leg or a truly adjacent Car-arrival/
departure pair. Detailed
acceptance results are
documented in
`docs/HONG_KONG_NO_SIGNAL_ROAD_RUNTIME_AUDIT.md`. Run68 applies 4,633 bounded
repairs while preserving all 3,956 active household bindings and zero dynamic-
parking facility mismatches. The independent event audit reduces realised
initial private-Car reversals from 15,078 to 10,435 and total road delay by
8.2%, but records 33 more unfinished private-Car trips and 17 fewer completed
joint bindings than run62. It is therefore the accepted bounded-v1
sensitivity implementation, while remaining outside the production network
and run manifest. No internal turn restriction is adopted without an OSM or
official junction-layout evidence source.

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

An opt-in Candidate11 integration gate now proves that ordinary innovation
can coexist with the physical household/student modules. Server run
`/mnt/DiskM/by/hk_stage11_candidate11_open_innovation_20260814_run13e`
retains the complete Candidate11 TOD signal system and exact iteration-0
parity, then runs through iteration 10 with ordinary ReRoute,
SubtourModeChoice and time-mutation-plus-rerouting enabled. Household escort,
student mode and school-bus candidates remain a separately selected protected
module; 47,867 involved people use `KeepLastSelected`, while 22,578 people
with unpriced border anchors retain route/time innovation but cannot invent a
Car tour. Temporary one-shot household templates are removed after composite
plans are installed, preventing generic selection of an unbound
`car_passenger` plan.

The run13e audit verifies 9,411 changed Car network routes, 87,173 changed
first PT boarding times and 156,895 changed PT service/vehicle sequences.
QSim `lost` falls from 5,993 to 300 and average executed score rises from
14.8631 to 30.4506. Final Walk share reaches 33.525% while PT falls to
51.149%, so this is a successful mechanics/stability gate but not a calibrated
equilibrium or production adoption. Candidate11's frozen road-performance
rejection remains in force; neither city metadata nor the run manifest is
changed.

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

## Candidate11 open Taxi/Walk 20-QSim sensitivity (completed, non-production)

The explicit, non-production run contract and server provenance are in
`docs/HONG_KONG_CANDIDATE11_OPEN_TAXI_WALK_20QSIM.md`. The accepted immutable
attempt is `release19/run14b`; it preserves the run13e Candidate11 inputs,
uses 16 global/QSim threads, executes QSim 0--19, opens a PCU-1 road-coupled
Taxi proxy to ordinary mode innovation, applies adult/student Taxi fare
coefficients of 0.10/0.15 util/HKD, and applies the 3.278342 util/h Walk
overtime term once per main trip after ten cumulative minutes. Protected
household/student selection enters QSim only at 5, 10 and 15. It entered
and completed all 20 QSim executions with exit code 0. It remains a sensitivity
and passed no production-adoption gate, so the adopted scenario is unchanged.

## Physical Taxi/DVRP v1 candidate (A/B passed; formal run active)

The finite-fleet successor is defined in
`docs/HONG_KONG_PHYSICAL_TAXI_DVRP_V1.md`. It is an opt-in branch candidate,
not an adopted production input. It replaces 385,820 person-local Taxi road
proxies with exactly 15,500 reusable MATSim Taxi/DVRP vehicles: Urban 13,083,
New Territories 2,353, and Lantau 64. The fleet is deliberately not scaled by
the 5% resident sample. Every vehicle has capacity four, a staggered single
18-hour service window, an inferred fixed-seed start link, and PCU 1.0 as the
first-test prior. Start links exclude PT-only links, signal internal
connectors, and dead ends.

The dispatcher uses minimum-wait assignment with 30-second reoptimisation,
60-second pickup and 30-second drop-off. A vehicle remains available after a
completed drop-off. Waiting is measured from request submission to pickup and
receives `-12 util/h`; other Taxi time receives `-6 util/h`. The per-trip
constant is `-9`, with fare coefficients `-0.10 util/HKD` for adults and
`-0.15 util/HKD` for students. `removeStuckVehicles=false` and
`stuckTime=3600 s` preserve DVRP consistency and queue feedback.

The accepted low-cost server test is
`/mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260815_smoke0p5_run25`.
Iteration 0 exits zero and conserves all requests: 2,717 submitted equals
1,417 completed plus 531 waiting, 767 onboard, and 2 rejected/invalid. Median
wait is 583 seconds, p90 wait is 75,444 seconds, empty-distance share is
0.2292, and QSim lost is 223. These values establish technical execution and
accounting only; the long wait tail and horizon backlog explicitly prevent a
service-quality or supply-adequacy claim.

The full 5% same-selected-plan A/B gate exits zero. Proxy `gate_proxy_run5`
reports iteration-1 QSim lost 0, Walk stuck 221 and mean leg duration 1,577 s;
physical PCU-1 `gate_pcu1_run2` reports 18, 379 and 1,688 s respectively. The
physical Taxi audit conserves 64,814 requests and records median/p90 wait of
49,311/76,636 s plus empty-distance share 0.29647. PCU 1.0 therefore passes
the bounded congestion gate; no TPDM capacity or lower-PCU candidate is used.

Formal `...formal50_run4` is active. The schedule allows ordinary route/mode/time
innovation through iteration 34, uses only `ChangeExpBeta` in 35--49, and
applies protected household/student joint choices before QSim 5, 15, 25, and
35. Run3 completed iterations 0--4 but exited during the QSim-5 protected
selection because a legitimate coincident-facility Taxi route returned no Taxi
leg. Run4 marks that zero-distance Taxi alternative unavailable and retains
the other real choices. Its active 30-minute Heartbeat follows only live-state evidence and may
repair/relaunch only after an actual premature exit. Formal run1 and run2 are
also retained failed attempts; run3 remains immutable failure evidence. Run4
uses payload32 JAR SHA256
`412a2445f6c4818f2dbe0a8629905f3fa004fd467bc578e021d01c570ba5515e`.
No current production path, `current_final_run`, or adopted Candidate11 status
is changed by this candidate metadata.

## TCS full-fleet Taxi calibration sensitivity (rejected)

A later frozen iteration-0 experiment keeps the full 15,500-vehicle fleet and
PCU 0.05, converts the January-April 2026 median 723,763 official passenger
journeys to 579,011 provisional hires at 1.25 passengers per hire, and only
releases operational replicas after their behavioral parent actually submits.
The corrected central run exits 0 and conserves 283,096 submitted requests,
but 71.3730% are not picked up. Completed-request mean/p50/p90/p95 wait is
2,423.4/465/7,718/10,782.7 seconds. Behavioral trip completion is 87.2490%,
versus 98.4483% for the matched frozen baseline.

The one-sided 1.35-passenger sensitivity reduces the target to 536,121 hires
and also exits 0, yet not-picked remains 69.8217%, completed mean wait is
3,284.0 seconds, and behavioral completion is 86.3972%. Both are retained as
technically valid but service-rejected sensitivities; neither changes the
adopted workflow. See `HONG_KONG_TAXI_TCS_FULL_FLEET_CALIBRATION.md`.

## Candidate5B signal A/B (opt-in)

The Candidate5B signal A/B deliberately retains the original transit schedule
and identical selected plans. The corrected signal arm executes all 1,445
Candidate11 systems and 3,243 groups while retaining all 86,417 explicit
road-supply queues. Completion increases from 94.8452% to 97.1698%, but common
completed trips take 1.835 minutes longer. It is an iteration-0 sensitivity,
not an adopted production change; see `HONG_KONG_CANDIDATE5B_SIGNAL_AB.md`.
The subsequent fixed-signal experienced-PT/day-2 test rebuilds ordinary PT
itineraries without changing activity times or signal XML. Completion reaches
98.4483%, common completed trips are 1.809 minutes faster, and combined
unresolved PT passenger states fall 45.54% relative to the original-PT signal
arm. Because regular PT vehicle stuck events at 30:00 rise from 9 to 850, this
also remains an opt-in sensitivity pending vehicle-block/horizon attribution;
see `HONG_KONG_EXPERIENCED_PT_TIMETABLE_V1.md`.
