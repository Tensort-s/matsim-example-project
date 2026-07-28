# Hong Kong offline public-transport fare model v1

## Current status

This workflow is an offline fare-source, route-matching, and passenger-trip
chargeability audit. It covers MTR, franchised bus, GMB, Ferry Core v1, and
Light Rail. It does not write fares into MATSim and does not modify plans,
config, scoring, Java runners, network, `transitSchedule`, vehicles,
facilities, mode constants, ASC values, or marginal utility of money.

Commit `c7be4a` originally generated a numeric fare for every generic PT leg by
looking up distance bands for five different modes and taking their cross-mode
median. That passenger-leg result has been withdrawn. A generic PT leg does
not identify the boarded mode, line, route, direction, boarding stop,
alighting stop, or transfer chain; mixing unrelated modal fares cannot recover
that missing itinerary. The distance curve and unconditional numeric trip
files are no longer active outputs.

The following products from `c7be4a` remain valid and are retained:

- official source URLs, download dates, and SHA256;
- 886,532 normalized official adult Octopus fare records;
- the production `transitSchedule` inventory;
- 3,621 official direction-level full-fare records;
- the five known unmatched bus routes;
- official source descriptions and limitations.

Active outputs are under:

```text
data/transport_costs/hongkong/pt_fare_v1/
```

## Official sources, dates, and portability

`fare_source_manifest.csv` separately records source URL, official dataset
URL, effective date, effective-date evidence status, download date,
repository-relative local path, byte size, and SHA256. It contains no absolute
local path.

| Fare source | Effective date retained | Evidence status | Download date |
|---|---:|---|---:|
| TD GTFS bus/GMB/ferry stop-OD fares | 2026-07-14 | `local_source_proven` | 2026-07-20 |
| TD bus/GMB/ferry route full fares | 2026-07-14 | `local_source_proven` | 2026-07-20 |
| MTR domestic station OD | 2024-06-30 | `external_official_reference_not_locally_archived` | 2026-07-20 |
| Airport Express station OD | 2025-06-22 | `external_official_reference_not_locally_archived` | 2026-07-20 |
| Light Rail station OD | 2024-06-30 | `external_official_reference_not_locally_archived` | 2026-07-20 |

The retained TD revision cut-off file locally proves the TD date. The MTR
effective dates are retained from the official references below, but those
press-release files are not locally archived; the manifest states that
limitation instead of presenting the dates as locally proven.

Official references:

- [TD headway information GTFS](https://data.gov.hk/en-data/dataset/hk-td-tis_11-pt-headway-en)
- [TD routes and fares](https://data.gov.hk/en-data/dataset/hk-td-tis_23-routes-fares-geojson)
- [MTR routes, fares, and station data](https://data.gov.hk/en-data/dataset/mtr-data-routes-fares-barrier-free-facilities)
- [MTR 2025/26 fare freeze](https://www.mtr.com.hk/archive/corporate/en/press_release/PR-25-018-E.pdf)
- [MTR 2026/27 fare freeze](https://www.mtr.com.hk/archive/corporate/en/press_release/PR-26-023-E.pdf)
- [Airport Express fares effective 2025-06-22](https://www.mtr.com.hk/archive/corporate/en/press_release/PR-25-032-E.pdf)

The normalized modelling reference is adult Octopus. It is not assigned to a
passenger trip unless the trip contains sufficient itinerary and eligibility
evidence.

## Production schedule inventory

The audited production schedule contains:

| `transportMode` | Lines | Routes | Departures |
|---|---:|---:|---:|
| `bus` | 1,614 | 2,363 | 69,589 |
| `gmb` | 778 | 1,161 | 81,081 |
| `train` | 10 | 30 | 5,370 |
| `light_rail` | 11 | 20 | 2,091 |
| `ferry` | 21 | 39 | 1,836 |
| **Total** | **2,434** | **3,613** | **159,967** |

`transit_schedule_inventory.csv` retains every MATSim line and route, operator,
mode, stop count, departure count, official identifier, and mapped stop
sequence. `transit_schedule_inventory_summary.csv` aggregates by mode and
operator.

## Corrected route, direction, and stop-order crosswalk

`route_to_official_fare_match.csv` has exactly one row for each of the 3,613
MATSim routes. It distinguishes route-identifier evidence, direction evidence,
station/stop coverage, official fare scope, candidate cardinality, forward
OD-pair coverage, matching method, and unresolved reason.

The matching rules are:

- **Bus and GMB:** an equal route ID proves only the route identifier. TD GTFS
  `fare_rules` has no explicit `route_seq` or direction field, so
  `direction_status=direction_not_encoded`. Schedule stop order is checked
  against every required forward official OD pair. Even with 100% pair
  coverage, these routes are `partial/B`, never `exact/A`.
- **MTR and Light Rail:** the schedule station IDs and order are compared with
  the official line-and-direction patterns. Exact full sequences,
  schedule-only short turns, branches assembled from more than one explicit
  direction segment, and loops are distinguished. Airport Express uses only
  the Airport Express fare matrix; it is not mixed with the domestic matrix.
- **Ferry:** a direction is exact only when route ID, Ferry Core facility to
  official stop mapping, and the complete official direction stop pattern all
  agree. A route ID or hash suffix is not direction evidence.
- **Full-route fares:** retained for audit only. They are never substituted for
  a missing sectional stop-OD fare.

Current mapping counts:

| `mapping_status` | Routes |
|---|---:|
| `exact` | 71 |
| `one_to_many_explicit` | 4 |
| `partial` | 3,533 |
| `ambiguous` | 0 |
| `unresolved` | 5 |

| `mapping_quality` | Routes |
|---|---:|
| `A` | 71 |
| `B` | 3,530 |
| `C` | 7 |
| `D` | 0 |
| `U` | 5 |

The 71 `exact/A` routes comprise 34 ferry, 22 MTR, and 15 Light Rail
directions. The four `one_to_many_explicit/B` routes are the two Light Rail
loops and two TKL branch compositions. Seven `partial/C` routes are two
Airport Express directions with 70% station-OD coverage and five ferry
patterns without an exact official direction stop pattern.

The known unresolved bus routes remain:

```text
bus_1000004_1
bus_1000004_2
bus_1000611_1
bus_8780_1
bus_8780_2
```

They have not gained new machine-verifiable fare or stop evidence.

### Forward-pair coverage

Coverage is calculated from distinct ordered schedule stop pairs with
`i < j`. It is not inferred from names or straight-line distance.

| Mode | Matched / required forward pairs | Weighted coverage |
|---|---:|---:|
| Bus | 771,666 / 771,666 | 1.000000 |
| GMB | 97,521 / 97,521 | 1.000000 |
| Ferry | 60 / 60 | 1.000000 |
| Light Rail | 3,603 / 3,603 | 1.000000 |
| MTR | 2,284 / 2,290 | 0.997380 |

The six missing MTR forward pairs are in the Airport Express matrix. The two
Airport Express directions consequently remain `partial/C` even though their
direction sequences are exact.

## Passenger-trip chargeability audit

The selected production routed plans contain 557,104 PT legs. Independent XML
inspection found:

```text
leg mode:                     pt for all 557,104
route type:                   generic for all 557,104
route attributes:             type, start_link, end_link, trav_time, distance
route text:                   absent for all 557,104
actual transit mode:          absent
line and route ID:            absent
direction:                    absent
boarding and alighting stop:  absent
transfer chain:               absent
```

`pt_passenger_trip_fare_audit.parquet` retains one audit row for every PT
passenger main leg. For all current rows:

```text
cost_hkd = null
cost_quality = U
mapping_status = unresolved
unresolved_reason =
  generic_pt_leg_missing_actual_mode_line_route_boarding_alighting_transfer_chain
```

Unresolved is not a zero fare. No record is deleted, assigned zero, assigned a
full-route fare, assigned the nearest distance bin, or aggregated across
modes. `cost_source`, `cost_effective_date`, and `source_record_id` remain null
because no official fare record was actually selected.

The unified fields are:

```text
person_id
leg_sequence
mode
cost_component
cost_hkd
cost_source
cost_effective_date
cost_quality
mapping_status
unresolved_reason
required_missing_fields
```

The output also retains the serialized generic-route fields and explicit null
columns for actual mode, line, route, direction, boarding stop, alighting
stop, transfer chain, and source record.

## Transfer concessions

Transfer concessions remain unmodelled:

```text
transfer_concession_hkd = null
transfer_concession_status =
  not_modelled_no_serialized_transfer_chain_or_eligibility
```

No MTR-GMB discount, bus interchange, Airport Express connection, pass,
promotion, or eligibility-based concession is inferred.

## Protected-input audit

`protected_input_hashes_baseline.csv` records the pre-change SHA256 of the
active network, schedule, transit vehicles, routed and unrouted plans, config,
facilities, and private vehicles. The independent validator recalculates all
eight hashes and writes `protected_input_hash_comparison.csv`. All eight
before/after hashes are identical.

## Active outputs

```text
data/transport_costs/hongkong/pt_fare_v1/
  README.md
  fare_source_manifest.csv
  official_fares_normalized.parquet
  official_route_full_fares.csv
  official_direction_stop_patterns.csv
  transit_schedule_inventory.csv
  transit_schedule_inventory_summary.csv
  route_to_official_fare_match.csv
  pt_passenger_trip_fare_audit.parquet
  pt_passenger_trip_fare_audit_sample.csv
  production_pt_leg_field_audit.json
  pt_trip_fare_build_audit.json
  pt_fare_model_summary.json
  protected_input_hashes_baseline.csv
  protected_input_hash_comparison.csv
  pt_fare_independent_validation.json
  SHA256SUMS.txt
```

The withdrawn distance curve and unconditional trip-estimate files are absent
from the active directory. Their history remains available in commit
`c7be4a`.

## Reproduction and validation

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\build_hong_kong_pt_fare_catalog.py `
  --source-project-root F:\Matsim\matsim-example-project

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\estimate_hong_kong_pt_trip_fares.py `
  --source-project-root F:\Matsim\matsim-example-project

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\validate_hong_kong_pt_fare_model_v1.py `
  --source-project-root F:\Matsim\matsim-example-project
```

The independent validator does not import builder-calculated validation
booleans. It rereads the detailed outputs, recomputes schedule totals,
candidate/status consistency, exact/A requirements, forward-pair coverage,
trip chargeability, source hashes, protected-input hashes, summary counts,
JSON parsing, CSV schemas, output portability, and output SHA256.

## Limitations and next boundary

- The current production generic PT legs cannot be priced at passenger-trip
  level without an itinerary-bearing output or event reconstruction.
- Bus/GMB route IDs and 100% forward OD coverage do not make their direction
  field explicit in the fare schema.
- Five Ferry Core patterns lack an exact official direction stop pattern in
  the retained TD source.
- Airport Express lacks six required forward station-OD fare pairs.
- Transfer concessions and passenger eligibility are unmodelled.
- This audit must not be connected to MATSim scoring until a separate,
  explicitly approved integration stage supplies verifiable itineraries and
  fare rules.
