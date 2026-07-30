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
- 886,532 normalized source-fare records retained under mode-specific
  passenger/payment semantics;
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

| Fare source | Date semantic retained | Evidence status | Download date |
|---|---:|---|---:|
| TD GTFS bus/GMB/ferry stop-OD fares | revision cut-off 2026-07-14; route-fare effective date not encoded | `local_source_proven` | 2026-07-20 |
| TD bus/GMB/ferry route full fares | revision cut-off 2026-07-14; route-fare effective date not encoded | `local_source_proven` | 2026-07-20 |
| MTR domestic station OD | 2024-06-30 | `external_official_reference_not_locally_archived` | 2026-07-20 |
| Airport Express station OD | 2025-06-22 | `external_official_reference_not_locally_archived` | 2026-07-20 |
| Light Rail station OD | 2024-06-30 | `external_official_reference_not_locally_archived` | 2026-07-20 |

The retained TD revision cut-off file locally proves the source snapshot
cut-off, not a route-specific fare effective date. The MTR effective dates
are retained from the official references below, but those
press-release files are not locally archived; the manifest states that
limitation instead of presenting the dates as locally proven.

Official references:

- [TD headway information GTFS](https://data.gov.hk/en-data/dataset/hk-td-tis_11-pt-headway-en)
- [TD routes and fares](https://data.gov.hk/en-data/dataset/hk-td-tis_23-routes-fares-geojson)
- [MTR routes, fares, and station data](https://data.gov.hk/en-data/dataset/mtr-data-routes-fares-barrier-free-facilities)
- [MTR 2025/26 fare freeze](https://www.mtr.com.hk/archive/corporate/en/press_release/PR-25-018-E.pdf)
- [MTR 2026/27 fare freeze](https://www.mtr.com.hk/archive/corporate/en/press_release/PR-26-023-E.pdf)
- [Airport Express fares effective 2025-06-22](https://www.mtr.com.hk/archive/corporate/en/press_release/PR-25-032-E.pdf)

There is no global passenger-fare basis. MTR and Light Rail rules are adult
Octopus. GMB, Ferry, and strict Bus GTFS amounts do not encode a common
passenger/payment basis. Bus simulation candidates assume a generic passenger
only for coverage and retain B/C/D quality plus anomaly provenance. No
mode-specific amount is assigned to a production passenger trip unless an
approved future integration supplies sufficient itinerary and eligibility
evidence.

## Canonical PT fare interface registry

The canonical release entry points for
`integration/hk-multimodal-cost-v1` are:

```text
data/transport_costs/hongkong/pt_fare_v1/
  canonical_pt_fare_interface_manifest.json
  pt_fare_layer_registry.csv
  pt_fare_release_validation.json
```

The registry replaces the ambiguous practice of treating the older top-level
normalized catalog as one cross-mode fare interface. That catalog remains a
historical source-normalization and cross-check layer. Each mode now has an
explicit audit path, strict rule path, simulation-candidate path, quote
interface, passenger/payment/date semantics, unresolved policy, quality range,
approval state, and path-level SHA256 map.

| Mode | Canonical strict layer | Future simulation candidate | Fare semantics |
|---|---|---|---|
| MTR | `mtr_station_od_v1` | same strict layer | adult Octopus; domestic and Airport Express separate |
| Light Rail | `light_rail_station_od_v1` | same strict layer | adult Octopus base fare |
| GMB | `gmb_fare_v1` | same strict layer | published amount; passenger/payment basis unspecified; duplicate/conflict unresolved |
| Ferry | `ferry_fare_v1` | same strict layer | published amount; passenger/payment/class/vessel/day applicability unspecified |
| Bus | `bus_fare_v1` | `bus_fare_simulation_v1` | strict Bus Core remains separate from B/C/D coverage assumptions |

`bus_fare_v1` is canonical for strict source-backed Bus rules: 754,133 active
rules, covering 0.9772790300466783 of all 771,666 Bus forward ODs.
`bus_fare_simulation_v1` is canonical only as a future coverage-first
simulation candidate: 771,666 rules, 100% OD coverage, B=764,969, C=4,074,
D=2,623, 18,170 OD assumptions, and 20,533 anomaly rows after including all
2,363 route fallbacks. It is not a statement that all Bus simulation values
are official adult Octopus fares and it never overwrites Bus Core.

The production boundary remains:

```text
production_pt_leg_count = 557104
priced_production_pt_leg_count = 0
unresolved_production_pt_leg_count = 557104
matsim_scoring_approved = false
joint_mode_choice_calibration_approved = false
```

The generic PT legs lack actual mode, line, route, boarding stop, alighting
stop, and transfer chain. Distance medians, cross-mode aggregation,
nearest-neighbour values, and route `fullFare` substitution are prohibited.
Future pricing requires a runtime or post-routing explicit PT itinerary.

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

- **Top-level Bus and GMB baseline:** an equal route ID and GTFS
  `fare_rules` alone prove no direction, so the protected top-level audit
  conservatively retains these routes as `direction_not_encoded/partial/B`.
  The later mode-specific GMB and bus audits do not edit that historical
  baseline. They independently add Bus/GMB JSON `routeId + routeSeq +
  stopSeq` full-pattern evidence and upgrade only routes having a unique
  complete stop-sequence match. Forward-pair coverage alone never performs
  that upgrade.
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

## MTR adult Octopus station-OD rules v1

`mtr_station_od_v1/` is a pure offline rule and query layer for future inputs
that explicitly provide an MTR boarding station and alighting station. It is
not production passenger-trip pricing. It does not read the production plans,
and the existing 557,104 generic PT audit rows remain unresolved with null
`cost_hkd`.

The only supported combination is:

```text
actual_transport_mode = train
passenger_type = adult
payment_medium = Octopus
```

The two rule scopes are strictly separate:

```text
domestic_mtr_station_od
airport_express_station_od
```

Domestic records never fill an Airport Express request, and Airport Express
records never fill a domestic request. Ordered OD keys are used exactly as
published. The query does not substitute the reverse direction, sum fares
along a path, interpolate by distance, select a nearest record, or fill a
missing fare with zero.

### Direct raw-source construction

The builder rereads these original official CSVs rather than copying the
normalized Parquet:

```text
data/transit/hongkong/MTR/mtr_lines_fares.csv
data/transit/hongkong/MTR/airport_express_fares.csv
data/transit/hongkong/MTR/mtr_lines_and_stations.csv
```

Every available fare has a stable original CSV line identifier,
repository-relative source path, and source SHA256. The builder independently
cross-checks all 9,216 domestic records and all 14 published Airport Express
records against `official_fares_normalized.parquet`.

Current rule counts are:

| Scope | Total schedule/rule universe | Available | Conflicting | Missing |
|---|---:|---:|---:|---:|
| Domestic MTR | 9,216 | 9,216 | 0 | 0 |
| Airport Express | 20 | 14 | 0 | 6 |

The domestic source is a complete 96 by 96 ordered matrix. It contains 100
officially explicit zero-fare rows: 96 same-station records and four linked
station records. These are source values, not missing-value imputation.
Unresolved rows never receive zero.

The six Airport Express ordered pairs absent from the official CSV are:

```text
44 -> 45  Hong Kong -> Kowloon
44 -> 46  Hong Kong -> Tsing Yi
45 -> 44  Kowloon -> Hong Kong
45 -> 46  Kowloon -> Tsing Yi
46 -> 44  Tsing Yi -> Hong Kong
46 -> 45  Tsing Yi -> Kowloon
```

They remain null and are listed in `mtr_unresolved_od_pairs.csv`. A reverse
record, domestic record, or path sum is not used to fill them.

### Station and route readiness audit

`mtr_station_crosswalk.csv` contains 101 distinct official station IDs. Exact
mapping requires an official line code and station-code token in the schedule
facility ID; names and coordinates are not used.

| Station mapping | Count |
|---|---:|
| `exact` | 100 |
| `ambiguous` | 0 |
| `unresolved` | 1 |

The unresolved station is Racecourse (`station_id=70`), which is present in
the domestic fare matrix but absent from the retained official
line-and-station pattern and production schedule.

`mtr_schedule_route_fare_readiness.csv` has one row for each of the 30 train
routes. Readiness means that a fare can be queried if explicit boarding and
alighting station IDs are later supplied; it does not mean a production
passenger trip has been matched.

| Route field | Status | Count |
|---|---|---:|
| Mapping | `exact` | 22 |
| Mapping | `one_to_many_explicit` | 2 |
| Mapping | `partial` | 6 |
| Fare readiness | `ready` | 28 |
| Fare readiness | `partial_missing_official_od` | 2 |

The two TKL branch compositions remain
`one_to_many_explicit`; short turns remain distinct. The two Airport Express
directions are partially ready because each has 7 of 10 required forward OD
pairs.

### Offline query interface

Use `quote_hong_kong_mtr_station_od_fares.py` with a CSV containing:

```text
quote_id
actual_transport_mode
fare_network_scope
boarding_station_id
alighting_station_id
passenger_type
payment_medium
travel_date
```

A fare is returned only for one uniquely available official ordered OD rule
with supported scope, mode, passenger type, payment medium, station IDs, and
travel date. All other requests retain null `cost_hkd`, quality `U`, and a
machine-readable unresolved reason.

Although the OD record itself is exact, current MTR effective-date evidence
remains `external_official_reference_not_locally_archived`. Consequently an
available quote has maximum `cost_quality=B`, not A. Domestic MTR retains
effective date `2024-06-30`; Airport Express retains `2025-06-22`.

The 16-case fixture covers available domestic and Airport Express fares,
independent reverse lookup, unknown and missing stations, missing and
conflicting scope, the known Airport Express gap, unsupported passenger and
payment categories, generic or missing mode, same-station absence, and a
transfer-concession request. All 16 expected rows are generated by the query
engine and independently reproduced by the validator.

The validator also closes the TD date-evidence gap: it directly parses
`routes_fares_last_updated.csv`, obtains `2026-07-14`, and checks that date
against all five relevant TD manifest rows. It does not compare a hard-coded
date to another hard-coded date.

## Light Rail adult Octopus station-OD rules v1

`light_rail_station_od_v1/` is a separate pure offline rule and query layer
for explicit ordered Light Rail stop IDs. Its only supported request
combination is:

```text
actual_transport_mode = light_rail
fare_network_scope = light_rail_station_od
passenger_type = adult
payment_medium = Octopus
```

This scope is distinct from `domestic_mtr_station_od` and
`airport_express_station_od`. No amount crosses those scope boundaries.

### Official ordered stop-OD matrix

The builder directly rereads and hashes:

```text
data/transit/hongkong/MTR/light_rail_fares.csv
data/transit/hongkong/MTR/light_rail_routes_and_stops.csv
```

It then cross-checks every available amount against
`official_fares_normalized.parquet`; the Parquet is not used as a substitute
for the raw CSV.

The official source contains 68 stops and a complete unique 68 by 68 ordered
matrix:

| Record status | Count |
|---|---:|
| Raw ordered OD records | 4,624 |
| `available` | 4,624 |
| `ambiguous` | 0 |
| `unresolved` | 0 |
| Official explicit zero fares | 68 |

All 68 zero amounts are explicit same-stop source records with their own CSV
line identifiers. They are not missing-value fills. Conversely, any future
missing or conflicting record must retain null `cost_hkd`; the rules never
select a reverse record, minimum, median, first candidate, nearest distance,
path sum, MTR amount, Airport Express amount, or full-route fare.

`light_rail_fare_conflicts.csv` and
`light_rail_unresolved_od_pairs.csv` are currently empty because the raw
matrix is complete and unique. Both files retain their full schema so future
source changes cannot silently drop these audit categories.

### Stop crosswalk and route readiness

`light_rail_stop_crosswalk.csv` maps all 68 official stops exactly. Mapping
uses only official stop ID/code pairs and exact code tokens in schedule
facility IDs. It does not use fuzzy names or coordinate nearest neighbours.

| Stop mapping | Count |
|---|---:|
| `exact` | 68 |
| `ambiguous` | 0 |
| `unresolved` | 0 |

Stops shared by several Light Rail routes remain one official stop and are not
treated as ambiguous.

`light_rail_schedule_route_fare_readiness.csv` independently regenerates
distinct, different-stop forward pairs from the production schedule order and
checks them against the raw fare CSV:

| Route audit field | Status | Count |
|---|---|---:|
| Mapping | `exact` | 15 |
| Mapping | `partial` | 3 |
| Mapping | `one_to_many_explicit` | 2 |
| Quality | `A` | 15 |
| Quality | `B` | 5 |
| Fare readiness | `ready` | 20 |
| Pattern | `exact_direction` | 15 |
| Pattern | `short_turn` | 3 |
| Pattern | `loop_multi_direction_composite` | 2 |

All 3,603 required different-stop forward pairs have an official ordered fare,
for coverage 1.0. Full fare readiness does not upgrade the three short turns
from `partial/B`, and the 705/706 loops remain
`one_to_many_explicit/B` composites rather than ordinary one-direction
routes. Readiness means only that an explicit stop pair can be quoted; it does
not identify a production passenger itinerary.

### Offline query boundary

`quote_hong_kong_light_rail_station_od_fares.py` returns a fare only for a
unique available official ordered OD record. Every returned amount is labelled:

```text
fare_amount_role =
  base_adult_octopus_fare_before_unmodelled_concessions
```

The Light Rail effective date remains `2024-06-30`, with evidence status
`external_official_reference_not_locally_archived`. Therefore exact available
quotes have maximum `cost_quality=B`. This status is not upgraded merely
because the fare CSV itself is official.

The 19-case fixture covers normal and reverse ordered OD records, a distinct
raw record for each direction, an official zero fare, unknown/missing stops,
missing/wrong scope, generic or missing mode, unsupported passenger/payment
categories, a transfer-concession request, a pre-effective travel date, and
an invalid date. The official matrix contains no missing same-stop, unresolved,
or ambiguous OD case; those three source categories are explicitly marked not
applicable rather than fabricated for the fixture.

Transfer-concession requests may receive the available base fare, but
`transfer_concession_hkd` remains null and
`transfer_concession_status=not_modelled`. The result must not be described as
the final discounted amount.

This layer does not read or price the 557,104 generic production PT legs. They
still lack actual mode and boarding/alighting stops, remain unresolved with
null `cost_hkd`, and cannot call this query interface. No Light Rail fare has
entered MATSim plans, config, scoring, network, schedule, vehicles, Java
runners, ASC, or marginal utility of money.

## Ferry Core v1 published-fare rules

`ferry_fare_v1/` is a direct raw-source audit and offline quote layer for the
39 Ferry Core v1 MATSim routes. It rereads TD GTFS
`fare_attributes.txt`/`fare_rules.txt`, the TD Ferry route-stop JSON,
`ferry_stop_facilities.csv`, and the production schedule. Existing normalized
fare and crosswalk outputs are cross-checked but are not used in place of the
raw sources.

### What the official fields do and do not prove

The GTFS snapshot contains 285 Ferry fare-attribute rows and 258 Ferry
route-stop-OD fare-rule rows. All 258 OD keys and amounts are unique; there
are no conflicting amounts and no explicit zero fares. The remaining 27 fare
attributes have no `fare_rules` row, hence no machine-verifiable boarding or
alighting stop, and remain separately unresolved.

The official source proves:

- `route_id` and ordered `origin_id -> destination_id`;
- numeric published `price`, currency `HKD`, and source-record identity;
- GTFS `transfers=0`, meaning no transfer is permitted on that fare record;
- JSON `routeId + routeSeq + stopSeq` direction patterns where present;
- a JSON route-direction `fullFare` reference.

It does **not** state that GTFS `price` is an adult fare, does not distinguish
cash from Octopus, and does not encode passenger type, deck/seat/cabin class,
ordinary versus high-speed vessel, weekday/weekend/public holiday, or time
period. `payment_method=0` is not treated as a payment-medium identifier.
`serviceMode` and `specialType` codes are retained for audit but are not
translated into vessel or fare conditions because the local source provides
no code dictionary. These dimensions are therefore
`unspecified_in_source`, never “adult Octopus” by assumption.

The offline query accepts only input value `unspecified` for each of those
source-unspecified dimensions. Returned amounts are labelled:

```text
published_fare_hkd
published_fare_passenger_and_payment_basis_unspecified
```

`published_fare_hkd` is copied exactly from raw GTFS `price`. The active Ferry
rule schema contains no `adult_base_fare_hkd` alias. A published amount is not
the same as an actual passenger fare: it must not be presented as adult,
child, Octopus, cash, class-specific, vessel-specific, or date-applicable.

### Mapping quality versus cost applicability

`mapping_quality` describes only route, official direction, and ordered-OD
evidence. `cost_quality` separately describes whether that published amount
is suitable as a cost component under the incomplete source conditions:

| Rule evidence | Mapping quality | Cost quality | Rule count |
|---|---:|---:|---:|
| Exact JSON direction and unique ordered GTFS OD | A | B | 48 |
| Direction not encoded; unique route and ordered GTFS OD | C | C | 12 |

No available Ferry query has `cost_quality=A`. Cost quality B does not mean
that an adult actually owes the amount; it means only that an official
published amount is traceable under an exact route-direction-OD mapping while
passenger, payment, class, vessel, day, and effective-period applicability
remain incomplete. Every available rule therefore carries:

```text
cost_applicability_status =
  published_amount_only_passenger_payment_class_vessel_day_and_effective_period_unspecified
```

### Stop, route, direction, and ordered-OD evidence

The explicit Ferry Core facility table contains 87 MATSim stop facilities
mapping to 31 distinct official stop IDs. Every mapping has cardinality one
and every mapped stop is present in GTFS. Of the 87 facility records, 74 also
appear in Ferry JSON and are `exact/A`; 13 use four official GTFS stop IDs
absent from Ferry JSON and are retained as `partial_source_coverage/B`. No
fuzzy name or coordinate-nearest mapping is used.

The 39 route audit rows remain:

| Route audit field | Status | Count |
|---|---|---:|
| Mapping | `exact` | 34 |
| Mapping | `partial` | 5 |
| Quality | `A` | 34 |
| Quality | `C` | 5 |
| Fare readiness | exact direction, source conditions unspecified | 34 |
| Fare readiness | direction not encoded, unique ordered OD | 5 |

The 34 exact routes reproduce the complete official JSON direction stop
pattern and retain explicit `routeSeq`. The five partial routes are not
upgraded: their route IDs and GTFS ordered OD fares exist, but the official
JSON direction pattern does not. Their query direction must be
`unspecified`; route-ID or route hash text is not direction evidence.

All 60 distinct schedule forward pairs are independently regenerated from
schedule stop order and match a unique raw GTFS rule, for coverage 60/60.
That gives 48 available `exact_route_direction_stop_od` rules and 12
available `route_stop_od_direction_not_encoded` rules. Pair coverage does not
make passenger, payment, class, vessel, or day conditions complete.

### Time, `fullFare`, and query boundaries

The TD date `2026-07-14` is retained only as:

```text
source_revision_cutoff_date = 2026-07-14
source_download_date = 2026-07-20
cost_effective_date = null
cost_effective_date_status =
  not_encoded_in_source_revision_cutoff_only
```

It is not used as a lower or upper bound for travel-date eligibility. Ferry v1
is a source-snapshot query, not a historical or future fare calculator. The
only supported temporal request is
`temporal_basis=source_snapshot_only` with an empty `travel_date`. Any nonempty
travel date remains unresolved because the route-specific effective period is
not encoded.

The JSON contains 102 unique route-direction `fullFare` references. Across
the 240 GTFS rules whose route-direction pattern can be compared to JSON, 121
prices equal `fullFare` and 119 differ. Thus the two fields are not rowwise
equivalent and `fullFare` is not evidence of a flat fare.

All 102 values remain in `ferry_route_full_fare_reference.csv` with
`eligible_for_default_quote=false`. None enters the 60 available OD rules.
The query never substitutes a reverse OD, interpolates by distance, sums a
path, chooses among candidates, aggregates prices, falls back to `fullFare`,
or fills a missing amount with zero.

The 22-case fixture includes exact and opposite-direction independently
published ODs, reverse OD within the wrong direction, partial/C with
unspecified and prohibited concrete direction, unknown route/stops,
MATSim/official route mismatch, route/OD mismatch, adult, Octopus, cash,
class, vessel and day requests, missing/wrong temporal basis, nonempty travel
date, `fullFare` non-fallback, transfer request, and generic `pt` mode. Four
requests return a published amount component; all others remain unresolved.

A transfer-concession request may still return that published component, but
`transfer_concession_hkd` stays null and
`transfer_concession_status=not_modelled`. `cost_hkd` is therefore neither a
final discounted fare nor proof of the actual passenger payment. The source
has no real conflicting fare, missing current forward pair, or zero-fare
case, so those states remain not applicable rather than being fabricated.

The interface does not read production plans. The 557,104 generic production
PT legs still lack mode/route/direction/stop evidence, remain unresolved, and
cannot call these rules. Nothing in this Ferry layer has entered MATSim
scoring or changed plans, config, Java, network, schedule, vehicles,
facilities, MTR, or Light Rail outputs.

## GMB Core v1 published-fare rules

`gmb_fare_v1/` is the raw-source audit and source-snapshot query layer for all
778 GMB lines and 1,161 GMB routes in the production schedule. It directly
rereads TD GTFS, the TD GMB route-stop JSON, the TD revision cut-off file, and
the production schedule. The schedule contains 81,081 GMB departures, 13,100
stop occurrences/facilities, 4,760 distinct official stop IDs, and 97,521
distinct different-stop forward pairs.

### Source semantics and direction evidence

The retained GTFS has 98,269 GMB fare attributes and 98,269 fare rules, with
no orphan rule. It proves a `route_id`, ordered
`origin_id -> destination_id`, published numeric `price`, currency, and source
record identity. It does not identify the passenger as adult or child, cash
or Octopus payment, a service-day or time-period condition, a transfer
concession, a route sequence, or a direction. Consequently active amounts use
only:

```text
published_fare_hkd
fare_amount_role =
  published_fare_passenger_and_payment_basis_unspecified
passenger_type = unspecified_in_source
payment_medium = unspecified_in_source
service_class = unspecified_in_source
day_type = unspecified_in_source
time_period = unspecified_in_source
```

The GMB JSON separately proves `routeId`, `routeSeq`, `stopSeq`, `stopId`, and
`fullFare`. It does not provide a per-stop or per-section fare, passenger or
payment conditions, a transfer rule, or a fare-effective date. The audit does
not interpret `routeSeq` merely because its name resembles a direction
field. Instead, all 1,161 complete MATSim stop sequences independently match
exactly one complete official `routeId + routeSeq` stop pattern
(`candidate_count=1`). That complete-structure result permits exact direction
mapping for this snapshot. MATSim route suffixes, hashes, line names, and
terminal-name guesses are never evidence.

All 97,521 required forward pairs happen to have one or more GTFS candidates,
but 100% pair coverage alone does not prove a direction. Direction is exact
only because the separate full-sequence JSON test is unique. The stop
crosswalk is also evidence-only: all 13,100 facilities map by an explicitly
encoded official stop ID, and that ID exists in both GTFS and GMB JSON. No
fuzzy-name or coordinate-nearest match is used.

### Active rule and quality boundaries

The route readiness table has exactly one row per MATSim GMB route. All 1,161
are `exact/A` on route/direction mapping. Of these, 1,092 have unique source
records for every required pair; 69 contain at least one conflicting or
duplicate source record and are only partly fare-ready.

At rule level, 96,866 forward pairs have exactly one raw GTFS candidate and
are `available`. Another 361 have multiple candidates with different amounts
and are `ambiguous`; 294 have multiple identical source records and remain
`unresolved_duplicate_identical`. Duplicate records are not silently
collapsed or resolved by taking the first row. All 97,521 rules retain
`mapping_quality=A`, while cost quality is independently split into 96,866
`B` and 655 `U`. Every available raw amount is traceable to its GTFS fare-rule
and fare-attribute record, for a trace rate of 1.0.

The 16 explicit raw zero-price records are retained as official zero amounts;
zero is never used to fill a missing value. The builder and query do not use
reverse-OD substitution, interpolation, nearest distance, path or segment
sums, cross-route amounts, min/max/median/mean selection, fare-ID parsing, or
missing-value fill.

Every available amount carries:

```text
cost_applicability_status =
  published_amount_only_passenger_payment_and_effective_period_unspecified
```

Thus `cost_quality=B` means a traceable official published amount under an
exact route-direction-OD mapping. It does not mean the amount is an adult
fare, an Octopus or cash fare, or the passenger's actual payable fare.

### Time, `fullFare`, fixture, and integration boundary

The two retained dates have deliberately different meanings:

```text
source_revision_cutoff_date = 2026-07-14
source_download_date = 2026-07-20
cost_effective_date = null
cost_effective_date_status =
  not_encoded_in_source_revision_cutoff_only
```

The revision cut-off is not a fare-effective date and is not interpreted as
open-ended validity. The query supports only
`temporal_basis=source_snapshot_only` with an empty `travel_date`; any
nonempty date remains unresolved.

The JSON supplies 1,161 route-sequence `fullFare` references. Across 98,182
comparable raw GTFS candidate-record comparisons for unique ordered stop pairs,
57,362 prices equal the corresponding JSON `fullFare` and 40,820 differ. These
counts are independently recomputed and every reference row has
`eligible_for_default_quote=false`.
Amount equality does not establish semantic equivalence. No `fullFare` enters
active OD rules, replaces a missing OD, fills a sectional fare, or implies an
unconditional flat fare.

The 24-case fixture independently exercises available and reverse-direction
records, a raw zero fare, a real conflicting pair, a real identical-duplicate
pair, route/direction/stop mismatches, unsupported passenger/payment/day/time
requests, temporal failures, `fullFare` non-fallback, transfer requests, and
generic `pt`. Four cases return a published component. There is no legal
partial-direction route, missing required pair, or orphan record in this
snapshot, so those source categories are marked not applicable rather than
fabricated. A transfer request may retain an independently available
published component, but `transfer_concession_hkd` is null and
`transfer_concession_status=not_modelled`.

Production integration is intentionally absent. The existing 557,104 generic
PT legs lack actual mode, route, direction, and stop evidence, remain
null/unresolved, and cannot call the GMB query. No GMB fare has entered MATSim
plans, config, Java, scoring, network, schedule, vehicles, facilities, PT ASC,
or marginal utility of money. Franchised bus and transfer-concession modelling
remain outside this stage.

## Franchised-bus scope and fare-readiness audit v1

`bus_scope_direction_audit_v1/` is an operator-scope, official-direction, and
ordered-OD candidate audit. It deliberately does not create active bus fare
rules, a bus quote interface, passenger `cost_hkd`, transfer concessions, or
MATSim scoring integration.

### `transportMode=bus` and official operator scope

The production schedule contains 1,614 bus lines, 2,363 routes, 69,589
departures, 56,066 stop occurrences/facilities, 4,479 distinct explicit
official stop IDs, and 771,666 distinct different-stop forward pairs.
`transportMode=bus` is a MATSim vehicle/service mode and does not mean every
route is a franchised-bus service.

The official CSDI `FB_ROUTE_LINE` franchised-bus geometry layer supplies the
operator-code scope evidence. Its codes are KMB, CTB, LWB, NLB, KMB+CTB, and
LWB+CTB. The complete plus-delimited codes and both component operators are
retained for jointly operated routes. Exact Bus JSON pattern matching gives
this schedule distribution:

| Official operator | Routes | Audit scope |
|---|---:|---|
| KMB | 1,152 | confirmed franchised operator |
| CTB | 672 | confirmed franchised operator |
| KMB+CTB | 187 | confirmed franchised operator, joint expression retained |
| LWB | 149 | confirmed franchised operator |
| NLB | 92 | confirmed franchised operator |
| LWB+CTB | 3 | confirmed franchised operator, joint expression retained |
| LRTFeeder | 45 | other bus service |
| XB | 27 | other bus service |
| DB | 18 | other bus service |
| PI | 13 | other bus service |
| no matched official operator | 5 | operator scope unresolved |

This operator-level test yields 2,255 routes belonging to a confirmed
franchised operator, 103 routes belonging to other bus operators, and five
operator-unresolved routes. It does not by itself confirm any concrete route.
Official GTFS agency names identify LRTFeeder as MTR Bus, DB and PI as
resident services, and XB as a crossing-boundary coach service; they are not
silently promoted into the franchised core.

Route-level evidence is a separate exact-key test. A route is
`confirmed_franchised_route` only when:

1. its complete schedule stop sequence uniquely matches an official Bus JSON
   `companyCode + routeId + routeSeq + stopSeq` pattern; and
2. the exact normalized `(COMPANY_CODE, ROUTE_ID, ROUTE_SEQ)` key occurs in
   the official CSDI franchised-bus geometry.

Operator code alone, route name, terminals, geometry proximity, and the
MATSim suffix cannot satisfy the second test. Each audit row retains the CSDI
feature index and `OBJECTID`; same-key multiplicity would be retained rather
than reduced to the first feature.

Of the 2,255 operator-confirmed JSON routes, 2,246 have an exact CSDI route
key and nine remain `franchise_route_scope_unresolved`, for a route-key match
rate of 0.996008869. The missing CSDI keys are:

```text
CTB|1000690|1
CTB|1000691|1
CTB|1000692|1
CTB|1000693|1
CTB|1000695|1
CTB|1000695|2
KMB|8263|1
LWB|1000697|1
LWB|1000698|1
```

These nine retain exact JSON directions but are not route-level confirmed.

The five unresolved schedule proxy routes remain:

```text
bus_1000004_1
bus_1000004_2
bus_1000611_1
bus_8780_1
bus_8780_2
```

They have no exact retained Bus JSON operator/stop pattern. CSDI happens to
contain those five route keys, but a CSDI key alone does not satisfy the
required JSON full-pattern condition. Their ten proxy facilities likewise
contain no official stop ID, so no operator, direction, stop, or fare
evidence is invented.

### Stop and official-direction evidence

Of the 56,066 used bus facilities, 56,056 explicitly encode an official stop
ID that exists in both GTFS and Bus JSON and are `exact/A`; the ten proxy
facilities are `unresolved/U`. No fuzzy-name, coordinate-nearest, terminal-name,
or road-link-location matching is used.

For 2,358 routes, the complete MATSim stop sequence uniquely equals one
official `routeId + routeSeq + stopSeq` Bus JSON pattern with a consistent
complete operator code. These routes are direction `exact/A`. The five proxy
routes remain `unresolved/U`. The MATSim `_1/_2` suffix is recorded but never
used as direction evidence.

As with GMB, pair coverage and direction evidence are different tests.
Finding a GTFS candidate for every ordered stop pair does not establish
direction. Direction is exact here only because of the separate unique
complete-pattern comparison.

The evidence layers must therefore be read independently:

- operator-level franchise evidence identifies an official operator class;
- route-level franchise evidence requires an exact CSDI route key;
- direction evidence requires a unique complete Bus JSON stop pattern;
- OD evidence reports raw GTFS candidate cardinality and amounts;
- the audit itself creates no active fare rule; the following Bus Core v1
  stage consumes only the route-confirmed, exact-direction, unique-candidate
  subset under its separately validated applicability rules.

### Ordered-OD candidates are not passenger costs

All 771,666 required forward pairs have one or more direct raw GTFS
route/origin/destination candidates:

| Candidate status | Ordered pairs |
|---|---:|
| `unique_candidate` | 767,043 |
| `duplicate_identical` | 2,000 |
| `conflicting_amounts` | 2,623 |
| `missing` | 0 |

The same unchanged classification split by route-level scope is:

| Route-level scope | Routes | Required pairs | Unique | Duplicate | Conflict | Missing |
|---|---:|---:|---:|---:|---:|---:|
| `confirmed_franchised_route` | 2,246 | 758,563 | 754,133 | 1,827 | 2,603 | 0 |
| `franchise_route_scope_unresolved` | 9 | 2,108 | 2,074 | 34 | 0 | 0 |
| `other_bus_service` | 103 | 10,995 | 10,836 | 139 | 20 | 0 |
| `operator_scope_unresolved` | 5 | 0 | 0 | 0 | 0 | 0 |

Within the 2,246 route-level confirmed routes, 1,881 have only unique OD
candidates. Another 365 have at least one duplicate or conflicting pair and
are not fully ready; candidate uniqueness is not upgraded into an active fare
rule.

Each candidate retains its `fare_id`, raw `fare_rules.txt` and
`fare_attributes.txt` line numbers, published price, currency, route and
ordered OD, source path, and GTFS SHA256. The 647 explicit raw zero-price
candidate records remain distinguishable from missing data.

No candidate is selected as a passenger charge. The audit Parquet has no
`cost_hkd`; `unique_candidate` means only one raw record exists. Duplicate
records are not collapsed and conflicting amounts are not resolved by minimum,
maximum, mean, median, or first row. The audit also prohibits reverse-OD
substitution, distance interpolation, nearest records, segment/path sums,
cross-route/operator amounts, fare-ID text recovery, `fullFare` fallback, and
missing-value fill.

Only a record that is both route-level confirmed and uniquely represented by
one raw OD candidate is eligible for the following Bus Core v1 formal
published-amount layer. This audit itself does not create that rule or a query
interface.

For all 2,363 routes, fare readiness is:

| Fare readiness | Routes |
|---|---:|
| `ready_all_pairs_unique` | 1,881 |
| `partial_conflicting_amounts` | 251 |
| `partial_duplicate_records` | 114 |
| `franchise_route_scope_unresolved` | 9 |
| `other_bus_service_not_in_franchised_core` | 103 |
| `operator_scope_unresolved` | 5 |

Conflict status takes precedence over duplicate status, so a small number of
conflicting pairs cannot be hidden by otherwise high coverage.

### Source semantics, `fullFare`, and integration boundary

GTFS proves a published numeric amount, currency, route ID, and ordered
origin/destination. It does not prove adult/child, cash/Octopus, ticket type,
sectional/full-fare applicability, direction, route sequence, day/time, or a
route-specific fare-effective period. Bus JSON proves operator,
`routeId + routeSeq + stopSeq + stopId`, and a route-sequence `fullFare`
reference; it does not encode per-stop/section fares or unconditional
flat-fare applicability. Existing `adult_octopus_fare_hkd` column names are
not treated as source evidence.

All 2,358 JSON `fullFare` rows have
`eligible_for_default_quote=false`. Across 776,455 comparable raw GTFS
candidate records, 496,351 amounts equal their JSON `fullFare` and 280,104
differ. Equality does not prove the same fare semantics, and `fullFare` never
enters OD candidate classification or fills sectional fares.

The TD date remains only:

```text
source_revision_cutoff_date = 2026-07-14
source_download_date = 2026-07-20
cost_effective_date = null
cost_effective_date_status =
  not_encoded_in_source_revision_cutoff_only
```

No travel-date eligibility is performed. The 557,104 generic production PT
legs still lack bus itinerary evidence and remain null/unresolved. This stage
does not change plans, config, Java, network, schedule, vehicles, facilities,
PT ASC, marginal utility of money, or MATSim scoring.

## Franchised-bus Core v1 published-amount rules

`bus_fare_v1/` is the machine-readable offline rule and strict snapshot-query
layer built on the preceding read-only scope/direction audit. Bus Core v1
covers only `confirmed_franchised_route` records whose complete MATSim stop
sequence uniquely matches an official Bus JSON `routeId + routeSeq` direction,
whose exact `COMPANY_CODE + ROUTE_ID + ROUTE_SEQ` key exists in CSDI, and whose
forward ordered stop OD has exactly one raw GTFS candidate with one distinct
amount.

The resulting active universe contains 754,133 rules across 2,246 confirmed
franchised routes. This is 99.416001044% of the 758,563 forward pairs in those
routes and 97.727903005% of all 771,666 bus-mode forward pairs. Every active
rule directly retains its unique `fare_id`, raw `fare_rules.txt` and
`fare_attributes.txt` line numbers, source SHA256, route/direction, and ordered
boarding/alighting stop IDs. The active rules include 637 explicit unique raw
zero-price records; these are not missing-value fills.

An active amount is only the retained GTFS published numeric amount. The source
does not identify an adult, child, cash, Octopus, service-class, day-type,
time-period, or ticket-product basis. Consequently all five applicability
dimensions are `unspecified_in_source`, the available mapping is `exact/A`,
and `cost_quality=B`; Bus Core v1 never creates `cost_quality=A`. The query
returns the same amount as `published_fare_hkd` and `cost_hkd` only when the
request explicitly uses `unspecified` for those dimensions, supplies no travel
date, requests `source_snapshot_only`, requests no transfer concession, and
exactly matches the active line, route, official route/direction, and ordered
stops.

The complete 17,533 non-active forward pairs remain machine-readable and
unquoteable:

| Exclusion reason | Ordered pairs |
|---|---:|
| confirmed-route identical duplicate records | 1,827 |
| confirmed-route conflicting amounts | 2,603 |
| nine franchise-route-scope-unresolved routes | 2,108 |
| 103 other-bus-service routes | 10,995 |

The identical duplicates are not collapsed. Conflicts are not resolved by
minimum, maximum, average, median, or first record. The nine CSDI route-scope
gaps are excluded even though 2,074 of their pairs have a unique GTFS
candidate. The five known unmatched proxy routes remain separately listed as
operator-scope unresolved; their schedules contain no valid different-stop
forward pairs. Together, active plus excluded/unresolved remains the complete
771,666-pair universe.

All 2,358 JSON `fullFare` values remain reference-only with
`eligible_for_default_quote=false`. They cannot fill a missing OD, replace a
sectional amount, resolve duplicates/conflicts, or act as query fallback.
Reverse-OD substitution is also prohibited: an opposite-direction trip is
quoteable only through its own independently matched route and forward OD.

The source revision cut-off `2026-07-14` is provenance, not a fare effective
date. `cost_effective_date` therefore remains null and a nonempty
`travel_date` is rejected. Transfer-concession amounts remain null with status
`not_modelled`. These published-amount rules have not been applied to the
557,104 generic production PT legs, which remain null/unresolved/U, and have
not entered plans, config, Java, network, schedule, vehicles, PT ASC, marginal
utility of money, or MATSim scoring.

## Bus simulation coverage layer v1

`bus_fare_simulation_v1/` is a separate coverage-first modelling layer. It
does not alter the official audit or Bus Core v1 and must not be interpreted
as a replacement for either. Its purpose is to give every one of the 771,666
required bus forward ODs a reproducible non-null model amount and to give all
2,363 scheduled bus routes a route-level fallback for later simulation work.

The layer keeps two amount fields distinct:

- `official_published_fare_hkd` is populated only for a unique raw GTFS OD
  amount, including scope-relaxed unique records;
- `model_fare_hkd`, copied to `cost_hkd`, is the coverage-first value and may
  be an identical-duplicate consensus, a selected conflicting candidate, or
  a route fallback.

The 771,666 OD rules resolve as follows:

| Resolution method | Rules | Quality |
|---|---:|---|
| confirmed Bus Core direct unique GTFS OD | 754,133 | B |
| other-bus-service direct unique GTFS OD | 10,836 | B |
| CSDI-route-scope-unresolved direct unique GTFS OD | 2,074 | C |
| identical raw-candidate consensus | 2,000 | C |
| terminal OD candidate matching JSON `fullFare` | 4 | D |
| unique modal raw candidate | 59 | D |
| median-nearest existing candidate, tie higher | 2,560 | D |

Thus the quality distribution is B=764,969, C=4,074, and D=2,623. No
simulation assumption receives quality A. Conflict resolution never averages
amounts or creates a value outside the actual candidate set. It first checks
whether an official-direction terminal OD has exactly one candidate amount
equal to JSON `fullFare`, then uses a unique raw-record mode, and finally
selects the actual candidate nearest the median position of distinct amounts,
choosing the higher amount on an equal-distance tie. Candidate values,
frequencies, min/max/spread, record IDs, selected amount, and rationale remain
auditable.

The original 637 active unique zero rules remain exactly zero. Ten raw zero
records form five all-zero identical-duplicate groups, producing five
additional zero consensus rules. All 642 resulting zero rules carry
`explicit_raw_zero_fare`, an anomaly flag, and audit priority 3. Route,
operator, distance, and stop-count fallback never creates a zero value.

All 2,358 routes with an exact Bus JSON direction use their unique positive
JSON `fullFare` only as a quality-D route fallback, never as an OD official
amount. The five operator-scope-unresolved proxy routes use the final
distance/stop-count cohort fallback:

| MATSim route | Model fallback (HKD) | Level and method |
|---|---:|---|
| `bus_1000004_1` | 21.3 | 5, all-bus distance/stop cohort |
| `bus_1000004_2` | 16.5 | 5, all-bus distance/stop cohort |
| `bus_1000611_1` | 21.3 | 5, all-bus distance/stop cohort |
| `bus_8780_1` | 35.0 | 5, all-bus distance/stop cohort |
| `bus_8780_2` | 35.0 | 5, all-bus distance/stop cohort |

The query layer always prefers an exact line/route/direction/forward-OD rule.
For a known route with an unmatched, reversed, or otherwise unavailable OD,
it returns that route's fallback and marks `fallback_used=true`; only a
completely unknown route remains unresolved. Passenger/payment/class
specification, a travel date, or a requested transfer concession does not make
the coverage-first amount null. Instead, the response explicitly states:

```text
transfer_concession_status = not_modelled_ignored_for_v1
eligibility_status = not_modelled_generic_passenger_assumed
temporal_status =
  source_snapshot_applied_without_route_specific_effective_date
```

The anomaly table contains 18,170 anomalous OD rules plus all 2,363 route
fallbacks. Its priority counts are 1=1,995, 2=12,910, 3=642, 4=2,623, and
5=2,363; priority 0 contains the 753,496 direct unique nonzero confirmed OD
rules outside the anomaly table. These values support audit ordering, not a
claim that assumptions are official fares.

The four layers remain distinct:

1. the official audit preserves raw scope, direction, candidates, duplicates,
   conflicts, and unresolved evidence;
2. Bus Core v1 publishes only strict unique confirmed-route snapshot rules;
3. the simulation layer assigns clearly labelled model values for 100% bus
   coverage;
4. MATSim scoring integration is not implemented.

The production 557,104 generic PT audit rows remain null/unresolved/U.
Eligibility, resident or cross-boundary qualification, adult/child,
cash/Octopus, special-service entitlement, transfer concessions, and
route-specific effective dates remain unmodelled.

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
  canonical_pt_fare_interface_manifest.json
  pt_fare_layer_registry.csv
  pt_fare_release_validation.json
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
  mtr_station_od_v1/
    README.md
    mtr_station_crosswalk.csv
    mtr_station_od_fare_rules.parquet
    mtr_station_od_fare_rules_sample.csv
    mtr_unresolved_od_pairs.csv
    mtr_schedule_route_fare_readiness.csv
    mtr_fare_query_fixture_input.csv
    mtr_fare_query_fixture_output.csv
    mtr_station_od_summary.json
    mtr_station_od_validation.json
    SHA256SUMS.txt
  light_rail_station_od_v1/
    README.md
    light_rail_stop_crosswalk.csv
    light_rail_station_od_fare_rules.parquet
    light_rail_station_od_fare_rules_sample.csv
    light_rail_fare_conflicts.csv
    light_rail_unresolved_od_pairs.csv
    light_rail_schedule_route_fare_readiness.csv
    light_rail_fare_query_fixture_input.csv
    light_rail_fare_query_fixture_output.csv
    light_rail_station_od_summary.json
    light_rail_station_od_validation.json
    mtr_station_od_v1_protected_hashes.csv
    SHA256SUMS.txt
  ferry_fare_v1/
    README.md
    ferry_source_schema_audit.csv
    ferry_fare_semantics_summary.json
    ferry_stop_crosswalk.csv
    ferry_route_direction_fare_readiness.csv
    ferry_fare_rules.parquet
    ferry_fare_rules_sample.csv
    ferry_fare_conflicts.csv
    ferry_unresolved_fare_rules.csv
    ferry_route_full_fare_reference.csv
    ferry_fare_query_fixture_input.csv
    ferry_fare_query_fixture_output.csv
    ferry_fare_summary.json
    ferry_fare_validation.json
    prior_mode_protected_hashes.csv
    SHA256SUMS.txt
  gmb_fare_v1/
    README.md
    gmb_source_schema_audit.csv
    gmb_fare_semantics_summary.json
    gmb_stop_crosswalk.csv
    gmb_direction_evidence_audit.csv
    gmb_route_direction_fare_readiness.csv
    gmb_fare_rules.parquet
    gmb_fare_rules_sample.csv
    gmb_fare_conflicts.csv
    gmb_unresolved_fare_rules.csv
    gmb_route_full_fare_reference.csv
    gmb_fare_query_fixture_input.csv
    gmb_fare_query_fixture_output.csv
    gmb_fare_summary.json
    gmb_fare_validation.json
    prior_mode_protected_hashes.csv
    SHA256SUMS.txt
  bus_scope_direction_audit_v1/
    README.md
    bus_source_schema_audit.csv
    bus_fare_semantics_summary.json
    bus_operator_scope_audit.csv
    bus_route_scope_audit.csv
    bus_route_franchise_scope_evidence.csv
    bus_route_scope_candidate_crosstab.csv
    bus_scope_candidate_summary.json
    bus_stop_crosswalk.csv
    bus_direction_evidence_audit.csv
    bus_route_direction_readiness.csv
    bus_od_fare_candidate_audit.parquet
    bus_od_fare_candidate_audit_sample.csv
    bus_od_conflicts.parquet
    bus_od_conflicts_sample.csv
    bus_od_duplicate_records.parquet
    bus_od_duplicate_records_sample.csv
    bus_missing_required_pairs.csv
    bus_route_full_fare_reference.csv
    bus_scope_direction_summary.json
    bus_scope_direction_validation.json
    prior_mode_protected_hashes.csv
    SHA256SUMS.txt
  bus_fare_v1/
    README.md
    bus_fare_rules.parquet
    bus_fare_rules_sample.csv
    bus_unresolved_fare_rules.parquet
    bus_unresolved_fare_rules_sample.csv
    bus_fare_conflicts.parquet
    bus_fare_conflicts_sample.csv
    bus_fare_duplicate_records.parquet
    bus_fare_duplicate_records_sample.csv
    bus_excluded_scope_pairs.parquet
    bus_excluded_scope_pairs_sample.csv
    bus_unresolved_routes.csv
    bus_route_direction_fare_readiness.csv
    bus_route_full_fare_reference.csv
    bus_fare_semantics_summary.json
    bus_fare_summary.json
    bus_fare_query_fixture_input.csv
    bus_fare_query_fixture_output.csv
    bus_fare_validation.json
    protected_hashes.csv
    SHA256SUMS.txt
  bus_fare_simulation_v1/
    README.md
    SHA256SUMS.txt
    bus_simulation_fare_rules.parquet
    bus_simulation_fare_rules_sample.csv
    bus_simulation_fare_anomalies.parquet
    bus_simulation_fare_anomalies_sample.csv
    bus_route_fallback_fares.csv
    bus_fare_resolution_method_summary.csv
    bus_fare_resolution_quality_summary.csv
    bus_simulation_query_fixture_input.csv
    bus_simulation_query_fixture_output.csv
    bus_simulation_fare_summary.json
    bus_simulation_fare_validation.json
    protected_hashes.csv
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

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\build_hong_kong_mtr_station_od_fares.py `
  --source-project-root F:\Matsim\matsim-example-project

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\quote_hong_kong_mtr_station_od_fares.py `
  --input .\data\transport_costs\hongkong\pt_fare_v1\mtr_station_od_v1\mtr_fare_query_fixture_input.csv `
  --output .\data\transport_costs\hongkong\pt_fare_v1\mtr_station_od_v1\mtr_fare_query_fixture_output.csv

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\validate_hong_kong_mtr_station_od_fares.py `
  --source-project-root F:\Matsim\matsim-example-project

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\build_hong_kong_light_rail_station_od_fares.py `
  --source-project-root F:\Matsim\matsim-example-project

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\quote_hong_kong_light_rail_station_od_fares.py `
  --input .\data\transport_costs\hongkong\pt_fare_v1\light_rail_station_od_v1\light_rail_fare_query_fixture_input.csv `
  --output .\data\transport_costs\hongkong\pt_fare_v1\light_rail_station_od_v1\light_rail_fare_query_fixture_output.csv

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\validate_hong_kong_light_rail_station_od_fares.py `
  --source-project-root F:\Matsim\matsim-example-project

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\build_hong_kong_ferry_fares.py `
  --source-project-root F:\Matsim\matsim-example-project

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\quote_hong_kong_ferry_fares.py `
  --input .\data\transport_costs\hongkong\pt_fare_v1\ferry_fare_v1\ferry_fare_query_fixture_input.csv `
  --output .\data\transport_costs\hongkong\pt_fare_v1\ferry_fare_v1\ferry_fare_query_fixture_output.csv

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\validate_hong_kong_ferry_fares.py `
  --source-project-root F:\Matsim\matsim-example-project

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\build_hong_kong_gmb_fares.py `
  --source-project-root F:\Matsim\matsim-example-project

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\quote_hong_kong_gmb_fares.py `
  --input .\data\transport_costs\hongkong\pt_fare_v1\gmb_fare_v1\gmb_fare_query_fixture_input.csv `
  --output .\data\transport_costs\hongkong\pt_fare_v1\gmb_fare_v1\gmb_fare_query_fixture_output.csv

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\validate_hong_kong_gmb_fares.py `
  --source-project-root F:\Matsim\matsim-example-project

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\audit_hong_kong_bus_fare_readiness.py `
  --source-project-root F:\Matsim\matsim-example-project

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\validate_hong_kong_bus_fare_readiness.py `
  --source-project-root F:\Matsim\matsim-example-project

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\build_hong_kong_bus_fares.py `
  --source-project-root F:\Matsim\matsim-example-project

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\quote_hong_kong_bus_fares.py `
  --input .\data\transport_costs\hongkong\pt_fare_v1\bus_fare_v1\bus_fare_query_fixture_input.csv `
  --output .\data\transport_costs\hongkong\pt_fare_v1\bus_fare_v1\bus_fare_query_fixture_output.csv

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\validate_hong_kong_bus_fares.py `
  --source-project-root F:\Matsim\matsim-example-project

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\build_hong_kong_bus_simulation_fares.py `
  --source-project-root F:\Matsim\matsim-example-project

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\quote_hong_kong_bus_simulation_fares.py `
  --input .\data\transport_costs\hongkong\pt_fare_v1\bus_fare_simulation_v1\bus_simulation_query_fixture_input.csv `
  --output .\data\transport_costs\hongkong\pt_fare_v1\bus_fare_simulation_v1\bus_simulation_query_fixture_output.csv

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\pt\validate_hong_kong_bus_simulation_fares.py `
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
- GMB route IDs and 100% forward-OD coverage do not themselves prove
  direction. GMB Core v1's exact direction mapping rests on a separate unique
  match of every complete schedule stop sequence to an official
  `routeId + routeSeq` JSON pattern.
- GMB GTFS `price` does not identify passenger/payment conditions or a fare
  effective period. Its 1,161 JSON `fullFare` values are reference-only and
  never fill sectional or unresolved OD fares.
- GMB's 361 conflicting and 294 identical-duplicate pairs remain
  non-quoteable. A duplicate identical amount is not treated as a unique
  official record.
- Franchised-bus Core v1 remains separate from GMB Core v1; neither mode's
  rules may be used as fallback for the other.
- The bus readiness audit finds 2,255 routes in the confirmed franchised
  operator scope, but only 2,246 have an exact CSDI route-level key; nine
  remain route-scope unresolved and are excluded from Bus Core v1.
  Duplicate and conflicting GTFS candidates remain unresolved and
  unquoteable.
- `transportMode=bus` also contains 103 officially identified other-bus
  service routes and five unresolved proxy routes. These are not promoted
  into the franchised core.
- Bus GTFS `price` does not identify an adult, Octopus, cash, service-class,
  day/time, or fare-effective-period basis. Bus Core v1 therefore quotes only
  strict source-snapshot published amounts with all those dimensions
  unspecified; it models neither transfer concessions nor JSON `fullFare`
  fallback.
- The bus simulation layer deliberately relaxes those applicability gates for
  coverage. Duplicate consensus, conflict selection, scope-relaxed values,
  and route fallback are model assumptions with B/C/D quality and anomaly
  metadata; they are not unique official passenger fares.
- The coverage-first query's route fallback is suitable only for keeping a
  later model executable when an exact OD is unavailable. It must not be used
  to claim an observed fare, eligibility, concession, or historical
  travel-date validity.
- Five Ferry Core patterns lack an exact official direction stop pattern in
  the retained TD source.
- Ferry GTFS `price` does not identify adult, cash/Octopus, class, vessel, or
  day type. Ferry v1 can quote only the published amount with those
  dimensions explicitly requested as `unspecified`; JSON `fullFare` remains
  reference-only.
- Ferry v1 has no route-specific fare effective date. Its query is limited to
  the retained source snapshot and rejects nonempty travel dates.
- Airport Express lacks six required forward station-OD fare pairs; MTR
  station-OD v1 preserves them as explicit unresolved rules.
- Transfer concessions and passenger eligibility are unmodelled.
- MTR station-OD v1 supports only adult Octopus and requires actual mode plus
  explicit boarding and alighting station IDs. It cannot be applied to the
  current generic production PT legs.
- Light Rail station-OD v1 similarly supports only adult Octopus base fares
  for explicit ordered Light Rail stop IDs. It excludes transfer concessions
  and remains separate from the two MTR fare scopes.
- This audit must not be connected to MATSim scoring until a separate,
  explicitly approved integration stage supplies verifiable itineraries and
  fare rules.
