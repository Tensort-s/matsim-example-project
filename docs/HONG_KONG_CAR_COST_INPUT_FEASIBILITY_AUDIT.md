# Hong Kong private-car cost input feasibility audit

## Status and scope

This document records the independent input-feasibility audit for the Hong
Kong private-car offline cost model. It does not validate the monetary values
in `car_cost_v1`, and it does not calculate or regenerate low, base, or high
costs.

The current `car_cost_v1` results remain a prototype pending the repairs listed
below. No MATSim plans, config, network, facilities, vehicles, scoring
parameters, source snapshots, cost rules, or cost Parquet files were changed by
this audit.

The audit reads the production inputs from the canonical project as
`canonical_project_read_only`. Submitted artifacts retain repository-relative
paths only; they do not persist the local input-root path.

## Reproducible command

Use the project geospatial Python environment:

```powershell
& <geo-python> scripts/hong_kong_single_city/costs/car/audit_hong_kong_car_cost_inputs.py `
  --input-project-root <canonical-project-root>
```

The script stops before creating outputs if any required canonical input is
missing. It calculates SHA256 values before and after the audit and fails if an
input or an existing cost Parquet changes.

## Audited inputs

The machine-readable inventory is:

```text
data/transport_costs/hongkong/car_cost_v1/input_feasibility/
  car_cost_input_file_inventory.json
```

It covers:

- routed and unrouted V2 plans;
- V2 facilities, private vehicles, trip manifest, and config;
- the adopted road/PT network;
- the official `RdNet_IRNP.gdb`;
- synthetic-household grid-to-TCS information;
- the 1,585 fixed-link grid polygons.

For every item the inventory records its repository-relative path, existence,
file or directory size, SHA256, Git state, format, and the tables, layers, XML
elements, and fields actually read.

## Car-leg and key reconciliation

All headline counts were recalculated from the canonical inputs rather than
copied from `car_cost_model_validation.json`.

| Metric | Recalculated | Prior expected value | Difference |
| --- | ---: | ---: | ---: |
| Manifest main legs | 743,614 | 743,614 | 0 |
| Manifest `mode=car` main legs | 67,718 | 67,718 | 0 |
| Private-car legs | 64,789 | 64,789 | 0 |
| Motorcycle car-mode legs | 2,929 | 2,929 | 0 |
| Unknown vehicle-class legs | 0 | not specified | — |
| Used private cars | 21,020 | 21,020 | 0 |

`person_id + leg_sequence` is unique in both the manifest car subset and the
routed plans. The manifest, routed-plan, and unrouted-plan car key sets are
identical. No routed car leg lacks `vehicleRefId`, and every reference resolves
in `privateVehicles_5pct.xml.gz`.

Each used private car is assigned to one person and one household in the
inspected plans. A vehicle is used for 2 to 5 legs, with a median of 3 and P90
of 5. The person-level `assignedVehicleId` agrees with the routed
`vehicleRefId` for all 64,789 private-car legs. These are assignment
relationships, not observed legal vehicle ownership.

## Energy-input feasibility

### Route distance

All 64,789 private-car legs have a finite, non-negative route distance. MATSim
route distance and network length are treated as metres under the scenario's
`EPSG:32650` convention.

| Statistic | Route distance |
| --- | ---: |
| NaN | 0 |
| Negative | 0 |
| Zero | 33 |
| Minimum | 0 m |
| Median | 12,408.222 m |
| P90 | 32,861.891 m |
| Maximum | 80,574.911 m |

Energy readiness is therefore:

| Status | Legs |
| --- | ---: |
| `ready_distance_only` | 64,789 |
| `unresolved_route_distance` | 0 |
| `out_of_scope_motorcycle` | 2,929 |
| `unresolved_vehicle_class` | 0 |

### Vehicle powertrain

The private-vehicle file identifies only the MATSim vehicle class and generic
vehicle-type properties such as capacity, dimensions, PCE, and network mode.
Neither it nor the routed vehicle reference contains individual:

- powertrain;
- fuel type;
- engine size;
- vehicle age.

The individual powertrain identification rate is therefore **0%**, and the
formal conclusion is `individual powertrain unavailable`. A representative
fleet average can only be considered as a documented future proxy. This audit
does not calculate an energy cost.

## Route and toll-input feasibility

### Full-route reconstruction

For every routed car leg the audit normalizes the route text and constructs:

```text
full_link_sequence =
  [start_link] + normalized_intermediate_links + [end_link]
```

The current routed plans happen to repeat both `start_link` and `end_link`
inside the route text. The audit removes those boundary duplicates before
constructing the full sequence. This avoids both omission and double inclusion
and remains valid if a later MATSim writer emits intermediate links only.

All 64,789 private-car routes have:

- a start link and end link;
- only link IDs present in the adopted network;
- continuous adjacent `to-node -> from-node` topology;
- departure time and travel time.

Thus the route existence and topology-continuity rates are both **100%**.
Passage time is estimable for all routes, but the audit does not calculate a
toll. The input is a typical weekday scenario with no exact calendar date, so
only weekday passage-time feasibility is asserted.

Repeated links occur on some valid network-continuous routes and are retained
as diagnostics. They are not silently removed.

### Official GDB mapping

The actual toll layers are:

- `TUN_BRIDGE_TOLL`;
- `TUN_BRIDGE_TV_TOLL`.

The audited fields include facility names, `FEATURE_ID_1`,
`FEATURE_ID_2`, `EFFECTIVE_DATE`, private-car class `PC`, toll fields,
time-period fields, remarks, and update dates. The GDB has no explicit
direction field; the two feature-ID columns encode the two official road
features.

Official feature IDs are mapped to MATSim IDs using the numeric component of
`road_<ROUTE_ID>_*`. One material ambiguity is present: feature `2684` maps to
both `Western Harbour Crossing` and
`Western Harbour Crossing (Backup Toll Point)`. The 44 affected private-car
routes are therefore not confirmed as one uniquely named toll facility.

Toll readiness is:

| Status | Legs |
| --- | ---: |
| `route_ready_for_toll_matching` | 64,745 |
| `unresolved_toll_feature_mapping` | 44 |
| `ambiguous_incomplete_route` | 0 |
| `unresolved_unknown_network_link` | 0 |
| `unresolved_non_contiguous_route` | 0 |
| `out_of_scope_vehicle_class` | 2,929 |

### Facility-hit diagnostics

The audit matches facilities without calculating toll amounts.

| Official facility | Audited private-car route hits |
| --- | ---: |
| Lion Rock Tunnel | 72 |
| Shing Mun Tunnels | 412 |
| Tai Lam Tunnel | 422 |
| Tsing Sha Control Area | 59 |
| Western Harbour Crossing | 44 |
| Western Harbour Crossing backup alias | 44 |
| Cross Harbour Tunnel | 0 |
| Eastern Harbour Crossing | 0 |
| Tate's Cairn Tunnel | 0 |
| Aberdeen Tunnel | 0 |

The backup count is an alias conflict on the same feature, not 44 additional
physical passages. After normalizing current prototype rule IDs to official
names, the current `car_cost_v1` hit counts agree with the full-route audit for
the five non-backup names.

Adding explicit start and end links creates **zero** additional toll hits in
this particular routed-plan file because its route text already contains both
boundaries. This does not make the current estimator's implementation safe:
it does not reconstruct the sequence explicitly and its
`has_complete_link_sequence` flag tests only whether route text is non-empty.
OD cross-harbour patterns or geometric screenlines were not used to assign a
tunnel.

## Parking-input feasibility

Each private-car arrival is linked to:

- destination facility ID and coordinates;
- destination TCS zone;
- destination activity and normalized activity group;
- routed departure, travel time, and arrival;
- the same vehicle's next car departure and its origin facility.

The physical parking-event key is:

```text
vehicle_ref_id
destination_facility_id
arrival_time_s
next_car_departure_time_s
next_car_origin_facility_id
```

It is not replaced by `person_id + leg_sequence`.

### Coverage

| Input | Coverage |
| --- | ---: |
| Parking duration, all private-car arrivals | 43,034 / 64,789 = 66.422% |
| Parking duration, non-home arrivals | 35,662 / 35,931 = 99.251% |
| Destination TCS zone | 64,686 / 64,789 = 99.841% |
| Normalized activity group | 64,789 / 64,789 = 100% |

The lower all-arrival duration coverage is expected because the last trip of a
vehicle day normally returns home and has no next departure. Home parking is
kept as a separate fixed-parking treatment and does not require a temporary
parking duration.

Destination activity counts are:

| Activity group | Private-car arrivals |
| --- | ---: |
| Home | 28,858 |
| Work | 8,784 |
| Education | 278 |
| Shopping | 7,946 |
| Leisure | 15,652 |
| Medical/personal business | 3,271 |
| Border | 0 |
| Visitor accommodation | 0 |
| Other | 0 |

Parking readiness is:

| Status | Legs |
| --- | ---: |
| `ready_home_fixed_parking_separate` | 28,858 |
| `ready_duration_and_proxy_zone` | 35,564 |
| `unresolved_vehicle_chain` | 267 |
| `unresolved_destination_zone` | 98 |
| `unresolved_duration` | 2 |
| `unresolved_activity_type` | 0 |
| `out_of_scope_vehicle_class` | 2,929 |

The physical chain audit finds:

- 466 next departures earlier than the prior routed arrival;
- 321 next departures whose origin facility differs from the prior
  destination;
- 21,020 vehicle-final arrivals with no next departure;
- 1,359 valid parking events crossing midnight;
- no negative derived duration;
- no duration longer than 24 hours;
- no vehicle shared across people or households;
- no duplicate `parking_event_key`;

Some time-overlap and facility-chain problems end at home. They remain visible
as physical-chain diagnostics even though home cost readiness is classified as
`ready_home_fixed_parking_separate`.

No unresolved parking amount is written by this audit.

## Fixed vehicle-ownership boundary

The future fixed-cost record scope must be `vehicle_day` or `household_day`.
It must not be attached to an ordinary leg and must not enter a leg marginal
total.

The inputs provide vehicle assignment and household association, but no
observed legal owner, engine, purchase price, age, insurance, maintenance, or
financing fields. Depreciation, insurance, maintenance, and financing can
therefore only be future documented proxies; they must not be fabricated.

If work monthly parking is assumed already paid, it belongs to the separate
vehicle-day or household-day fixed-cost record rather than the work-arrival
leg.

## Required prototype repairs

`required_repairs.csv` records seven required changes. The principal findings
are:

1. Reconstruct the full MATSim route explicitly before toll matching.
2. Replace the shallow route-text check with start/end, network-membership,
   and topology validation.
3. Stop writing unresolved monetary amounts as `cost_hkd=0`; use null and
   exclude them from resolved totals.
4. Exclude incomplete marginal rows from means, quantiles, and totals and
   publish their coverage separately.
5. Replace the leg-derived parking session ID with a physical event key and
   calculate duplicate/chain checks from data rather than hard-coding zero.
6. Remove personal absolute paths from the estimator, source manifest, and
   toll-rule provenance.
7. Keep representative powertrain values explicitly labelled as fleet
   proxies because individual powertrain availability is zero.

The existing three scenario Parquets contain all previously required columns,
but each contains 3,196 `unresolved_cost` rows with `cost_hkd=0`. The current
grouped summary implementation does not filter `marginal_cost_complete`;
411 independently identified incomplete private-car marginal rows can enter
its grouped totals and distributions.

The existing fixed-cost rows are correctly outside ordinary legs, but their
amounts are not validated by this input-feasibility audit.

## Audit outputs

```text
scripts/hong_kong_single_city/costs/car/
  audit_hong_kong_car_cost_inputs.py

data/transport_costs/hongkong/car_cost_v1/input_feasibility/
  car_cost_input_file_inventory.json
  car_leg_input_feasibility.parquet
  car_cost_input_coverage.csv
  car_cost_feasibility_validation.json
  required_repairs.csv

docs/
  HONG_KONG_CAR_COST_INPUT_FEASIBILITY_AUDIT.md
```

`car_cost_feasibility_validation.json` contains recalculated counts, key-set
differences, route/network topology checks, vehicle-use diagnostics,
activity/zone/duration coverage, GDB mapping diagnostics, read-only prototype
review results, and protected SHA256 values before and after execution.
