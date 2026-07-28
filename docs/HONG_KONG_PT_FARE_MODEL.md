# Hong Kong offline public-transport fare model v1

## Purpose and boundary

This workflow is an offline fare collection, normalization, matching, and
audit layer for the adopted Hong Kong public-transport supply and passenger
trips. It covers MTR (including Airport Express), franchised bus, green minibus
(GMB), Ferry Core v1, and Light Rail. Other bus operators found in the
production schedule are retained as separately labelled inventory rows.

It does **not** write fares into MATSim. No plans, config, Java runner, scoring,
network, `transitSchedule`, or transit-vehicle file is modified. The model
outputs can support later analysis, but they are not an adopted simulation
input.

Output directory:

```text
data/transport_costs/hongkong/pt_fare_v1/
```

Scripts:

```text
scripts/hong_kong_single_city/costs/pt/
  build_hong_kong_pt_fare_catalog.py
  estimate_hong_kong_pt_trip_fares.py
```

## Read-only MATSim and demand inputs

The catalog inventories the active Ferry Core v1 supply:

```text
data/transit/hongkong/processed/
  matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_ferry_core_v1_cap010/
    transitSchedule_5pct.xml.gz
    ferry_stop_facilities.csv

data/transit/hongkong/processed/transit_schedule_assembly_inputs_2026/
  approved_route_directions.csv
```

The passenger-trip estimator reads:

```text
data/matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice/
  agent_trip_manifest_v2.parquet
  facilities_5pct_v2.xml.gz
```

These ignored production inputs are present in the canonical F-drive project.
The scripts first look in the current worktree and otherwise use
`F:\Matsim\matsim-example-project`; `--source-project-root` can override this
choice.

## Official fare sources and dates

`fare_source_manifest.csv` is the machine-readable authority for local path,
source URL, dataset URL, effective-date basis, download-date basis, byte size,
and SHA256. The official inputs are:

| Scope | Official file | Effective date used | Download date |
|---|---|---:|---:|
| Bus, GMB, ferry stop-OD fares | TD headway GTFS `gtfs.zip` | 2026-07-14 | 2026-07-20 |
| Bus route full fare | TD `JSON_BUS.json` | 2026-07-14 | 2026-07-20 |
| GMB route full fare | TD `JSON_GMB.json` | 2026-07-14 | 2026-07-20 |
| Ferry route full fare | TD `JSON_FERRY.json` | 2026-07-14 | 2026-07-20 |
| MTR domestic station OD | MTR `mtr_lines_fares.csv` | 2024-06-30 | 2026-07-20 |
| Airport Express station OD | MTR `airport_express_fares.csv` | 2025-06-22 | 2026-07-20 |
| Light Rail station OD | MTR `light_rail_fares.csv` | 2024-06-30 | 2026-07-20 |

The TD effective date is the official route-and-fare revision cut-off date in
the retained snapshot. The domestic MTR and Light Rail adult controlled fares
became effective on 2024-06-30 and remained unchanged in both 2025/26 and
2026/27. Airport Express fares changed on 2025-06-22.

Official pages:

- [TD headway information GTFS](https://data.gov.hk/en-data/dataset/hk-td-tis_11-pt-headway-en)
- [TD routes and fares of public transport](https://data.gov.hk/en-data/dataset/hk-td-tis_23-routes-fares-geojson)
- [MTR routes, fares and barrier-free facilities](https://data.gov.hk/en-data/dataset/mtr-data-routes-fares-barrier-free-facilities)
- [MTR 2025/26 fare freeze](https://www.mtr.com.hk/archive/corporate/en/press_release/PR-25-018-E.pdf)
- [MTR 2026/27 fare freeze](https://www.mtr.com.hk/archive/corporate/en/press_release/PR-26-023-E.pdf)
- [Airport Express fares effective 2025-06-22](https://www.mtr.com.hk/archive/corporate/en/press_release/PR-25-032-E.pdf)

The normalized fare basis is adult Octopus. Child, student, elderly, JoyYou,
disability, single-ticket, first-class, pass, group-ticket, promotional, and
eligibility-dependent prices remain in the original official files but are not
selected as the v1 trip estimate.

## Production schedule inventory

The inventory reproduces the production supply totals:

| `transportMode` | Lines | Routes | Departures |
|---|---:|---:|---:|
| `bus` | 1,614 | 2,363 | 69,589 |
| `gmb` | 778 | 1,161 | 81,081 |
| `train` | 10 | 30 | 5,370 |
| `light_rail` | 11 | 20 | 2,091 |
| `ferry` | 21 | 39 | 1,836 |
| **Total** | **2,434** | **3,613** | **159,967** |

Bus operators retained in the detailed inventory are `CTB`, `KMB`, `LWB`,
joint KMB/Citybus or LWB/Citybus services, `NLB`, `LRTFeeder`, `DB`, `PI`, and
`XB`, plus five directions whose production source has no operator code. The
complete operator-by-mode table is
`transit_schedule_inventory_summary.csv`; every MATSim line and route is in
`transit_schedule_inventory.csv`.

## Official-to-MATSim matching

The matching keys are evidence already retained in the production schedule:

- bus and GMB: MATSim route ID to TD official `route_id + route_seq`, followed
  by official stop IDs embedded in route-profile facility IDs;
- ferry: MATSim line ID to TD route ID and
  `ferry_stop_facilities.csv` to official stop IDs;
- MTR: MATSim line code and station codes to the MTR station-ID OD matrix;
- Light Rail: MATSim route number and station codes to the Light Rail
  station-ID OD matrix.

The completed match has:

- 3,558 bus/GMB/ferry route directions with an exact official route match and
  stop-OD fare records;
- 50 MTR/Light Rail route directions with matched official station-OD fares;
- 5 bus directions with a production route identifier but no official fare
  record.

The unmatched directions are `bus_1000004_1`, `bus_1000004_2`,
`bus_1000611_1`, `bus_8780_1`, and `bus_8780_2`. Their operator and route names
are also absent in the adopted route inventory. They remain explicitly
`unmatched_fare`; no fare is fabricated. The row-level audit is
`route_to_official_fare_match.csv`.

## Fare normalization

`official_fares_normalized.parquet` contains 886,532 official adult Octopus
fare observations. Each row retains:

- mode and operator;
- official route/direction where the source defines one;
- origin and destination stop/station identifiers and names;
- fare in HKD and fare basis;
- source identifier, effective date, and download date;
- production-schedule scope flag;
- straight-line OD distance used only by the v1 proxy curve.

`official_route_full_fares.csv` separately retains 3,621 direction-level TD
full fares. It is a fallback and audit field, not a substitute for a missing
stop-OD fare.

## Passenger-trip estimate

The routed v2 plans serialize each main `pt` leg as one MATSim `generic` route.
They retain total route time and distance but not the chosen transit line,
route, boarding station, alighting station, or transfer sequence. Therefore a
route-exact passenger payment cannot be recovered from the local plans.

V1 uses this explicit fallback:

1. Join each PT main leg to its origin and destination activity facilities.
2. Calculate projected straight-line OD distance in `EPSG:32650`.
3. For each mode independently, select the nearest populated 1 km distance bin
   in `official_fare_distance_curve.csv`.
4. Take the median official adult Octopus fare within that mode and bin.
5. Use the unweighted median across the five mode estimates as `cost_hkd`.
   Equal mode weighting prevents the much larger bus fare table from dominating
   the generic-PT value.
6. Retain all five mode candidates and a broad official-data uncertainty
   interval in the output.

This is a low-quality distance proxy, not a claim about the service actually
boarded. The quality field is:

```text
low_official_fare_distance_proxy_no_itinerary
```

The six zero-distance PT records are retained and flagged by their distance;
they are not silently removed or reclassified.

### Required unified fields

`pt_passenger_trip_fare_estimates.parquet` has one row per PT passenger main
leg and begins with the required schema:

```text
person_id
leg_sequence
mode
cost_component
cost_hkd
cost_source
cost_effective_date
cost_quality
```

Here `mode=pt` because the serialized trip does not reveal the boarded submode.
Additional fields retain facilities, purpose, population group, distance,
mode-specific estimates, uncertainty, passenger/payment assumptions, and the
transfer-concession status.

## Transfer concessions

Complex transfer discounts are not applied. The output fields are:

```text
transfer_concession_hkd = null
transfer_concession_status =
  not_applied_no_serialized_itinerary_or_eligibility
transfer_concession_source = ""
```

This covers MTR-GMB discounts, operator-specific bus interchange schemes,
Airport Express connections, passes, and other eligibility- or sequence-based
benefits. A later itinerary-aware version may populate these fields from
official rules, but v1 must not infer them from distance.

## Outputs

```text
data/transport_costs/hongkong/pt_fare_v1/
  README.md
  fare_source_manifest.csv
  official_fares_normalized.parquet
  official_route_full_fares.csv
  transit_schedule_inventory.csv
  transit_schedule_inventory_summary.csv
  route_to_official_fare_match.csv
  official_fare_distance_curve.csv
  pt_passenger_trip_fare_estimates.parquet
  pt_passenger_trip_fare_estimates_sample.csv
  pt_fare_model_summary.json
  pt_trip_fare_validation.json
  SHA256SUMS.txt
```

## Validation result

The completed run has:

- 557,104 input PT passenger trips and 557,104 output cost rows;
- 238,008 unique persons;
- zero duplicate `person_id + leg_sequence` keys;
- zero missing or negative `cost_hkd` values;
- zero non-null transfer concessions;
- median estimated fare HKD 11.7;
- 10th and 90th percentile estimated fares HKD 7.0 and HKD 23.8;
- input hashes recorded in `pt_trip_fare_validation.json`;
- all output hashes recorded in `SHA256SUMS.txt`.

## Commands

From the feature worktree:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\build_hong_kong_pt_fare_catalog.py `
  --source-project-root F:\Matsim\matsim-example-project

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\estimate_hong_kong_pt_trip_fares.py `
  --source-project-root F:\Matsim\matsim-example-project
```

Both scripts overwrite only named files in the v1 output directory. They do
not alter any MATSim source input.

## Limitations

- The trip estimate is distance-only because the local generic PT routes do
  not serialize actual transit itineraries.
- Adult Octopus is a modelling reference, not the known passenger category or
  payment medium.
- The base estimate is mode-balanced and does not infer the boarded mode.
- A straight-line OD bin is not equivalent to network or in-vehicle distance.
- The uncertainty range is descriptive of official fare observations, not a
  statistical confidence interval.
- Five production bus directions lack an official fare record and stay
  unmatched in the route catalog.
- Fare changes after the retained source snapshots require a new versioned
  download and rebuild.
