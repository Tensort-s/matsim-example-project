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

## Known limitations

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
  Stage 11 candidate removes `ride`, but its Taxi, `car_passenger`, and
  `school_bus` legs remain passenger abstractions without operator fleets.
- Private-car powertrains and destination car parks are not observed at
  vehicle/facility level; the offline car-cost layer therefore uses an
  explicit representative fleet and official-rate-bounded parking proxies.

These limitations must remain visible in publications, validation summaries,
and future model extensions.
