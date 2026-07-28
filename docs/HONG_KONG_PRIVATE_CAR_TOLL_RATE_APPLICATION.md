# Hong Kong private-car toll rate application by passage event v1

## Scope and status

This stage converts the audited Hong Kong toll facility-network mapping into
physical private-car passage events and applies official `PC` rates. The
outputs are standalone offline candidates under
`data/transport_costs/hongkong/car_cost_v1/toll_rate_application_v1/`.

The stage does not modify:

- MATSim scoring, `car` monetary distance rate, or marginal utility of money;
- plans, config, network, facilities, or vehicles;
- Taxi or PT rules;
- the existing unified car-cost low/base/high Parquet files;
- energy, parking, or fixed vehicle-ownership results.

The validation result is `publishable_candidate=true` within the explicitly
documented typical-workday and estimated-passage-time assumptions. It is not
an authorization to insert money scoring into MATSim or overwrite the unified
car-cost outputs.

## Locked inputs

The rate application is pinned to mapping audit commit
`94e02c8c34a9c9861f9c5d355b1bf6ade0f1ef64`. Before processing, the script
checks exact SHA256 values for:

- `docs/HONG_KONG_CAR_TOLL_NETWORK_MAPPING.md`;
- all six machine-readable inputs under
  `data/transport_costs/hongkong/car_cost_v1/toll_network_mapping_v1/`.

The routed plans and network are read from the canonical project input role.
Their repository-relative role paths and hashes are recorded, but the
canonical root's personal absolute path is deliberately omitted. All existing
files under `car_cost_v1`, except the new output directory, are also hashed
before and after processing.

## Ordered physical passage events

The script
`scripts/hong_kong_single_city/costs/car/apply_hong_kong_private_car_toll_rates.py`
reconstructs every route as:

```text
start_link + ordered route text links + end_link
```

For each private-car leg it then:

1. retains every audited mapped-link hit and its route index;
2. groups adjacent hits into initial spatial match clusters;
3. canonicalizes Western Harbour Crossing primary and backup features;
4. merges multiple clusters only when the full route is topologically
   continuous, official feature roles are complementary, and no feature
   reappears in another cluster;
5. marks any case failing that evidence as
   `repeated_facility_passage_review` with null money;
6. creates a stable event ID from person, leg, facility, and route-index span.

This process never uses equal-looking `FEATURE_ID` and `ROUTE_ID` values and
never reduces a whole leg to `set(canonical_facility_id)`.

### Event construction results

| Metric | Count |
|---|---:|
| raw ordered mapping matches | 34,263 |
| unique route-index/feature matches | 34,263 |
| canonical physical passage events | 30,837 |
| event rows after three-scenario expansion | 92,511 |
| private-car facility records with multiple initial spatial clusters | 2,028 |
| WHC primary/backup alias events merged | 1,924 |
| complementary-feature mapping fragments merged | 104 |
| repeated-facility passage records requiring review | 0 |

The earlier mapping audit's 2,024 WHC alias candidates cover all car-mode
vehicle classes. The 1,924 figure here is the private-car-only event count;
motorcycles are out of scope for rate application.

The 104 non-WHC separated-cluster records all have complementary official
feature roles, no repeated feature, and a topologically continuous complete
route. They are therefore classified as one passage represented by fragmented
mapping evidence. The raw cluster count, route-index gap, gap distance,
features, links, and resolution label remain in the event table. If a future
input violates these criteria, the script does not silently charge once or
twice: it produces an unresolved review record and blocks publication.

Event identity uniqueness is checked directly on
`person_id + leg_sequence + toll_event_id` before scenario expansion. The
expanded table is unique on that identity plus `scenario`.

## Passage-time estimation

Facility passage time is estimated, not observed.

Base passage time allocates the leg's total route travel time according to
cumulative network free-flow travel-time weights:

```text
departure time
  + route travel time
  * free-flow weight before the centre of the event span
  / total route free-flow weight
```

A second estimate uses cumulative link-length weights. The event output keeps
both estimates.

Low/high timing uses a ±600-second analyst sensitivity window around the base
estimate and expands it if needed to include the length-weight estimate. The
window is intended to test whether an estimated passage lies near a
time-varying official rate boundary; it is not a measured timestamp error.

- 529 events cross an actual rate boundary when comparing only the base
  free-flow-weight and length-weight estimates, without the ±10-minute window.
- 3,266 events can face more than one official rate within the full
  ±10-minute sensitivity window.

Invalid departure time, route travel time, link length, free speed, or route
weight would make an event unresolved with null cost. No current private-car
event has such an error.

## Official private-car rates

Only official `PC` rows from the audited Transport Department inventory are
used. Flat facilities retain their official flat rate. Time-varying facilities
use official day-type code `A` as an explicit typical-workday assumption.
Day-type `B` is checked for interval completeness but is not mixed into the
typical-workday candidate.

The plans contain no exact calendar date. Therefore the adopted assumption is:

```text
official_day_type_A_as_typical_workday;
scenario_has_no_calendar_date
```

Each event records the repository-relative rate source, source SHA256,
effective date, matched interval, vehicle class, day-type assumption, and rate
quality. Both day types have zero unreported gaps and zero overlaps after
normalizing official inclusive end seconds to half-open intervals.

Base uses the official rate at the base passage time. Low and high are the
minimum and maximum official rates genuinely possible in the timing
sensitivity interval. No arbitrary percentage multiplier is used. Flat rates
therefore have `low=base=high`.

## Results

All 67,718 car-mode legs remain present:

| Toll status | Legs |
|---|---:|
| confirmed charge | 25,858 |
| confirmed no charge | 38,931 |
| unresolved | 0 |
| out-of-scope motorcycle | 2,929 |

Only complete private-car routes with no audited passage event receive a real
zero. Unresolved and out-of-scope costs are null.

### Facility events and totals

| Facility | Events / charge legs | Low total (HKD) | Base total (HKD) | High total (HKD) | Effective date |
|---|---:|---:|---:|---:|---|
| Aberdeen Tunnel | 2,235 | 17,880 | 17,880 | 17,880 | 2025-09-21 |
| Cross Harbour Tunnel | 7,214 | 210,534 | 215,304 | 219,684 | 2026-07-17 |
| Eastern Harbour Crossing | 3,984 | 118,486 | 121,344 | 123,874 | 2026-07-17 |
| Lion Rock Tunnel | 2,919 | 23,352 | 23,352 | 23,352 | 1999-04-01 |
| Shing Mun Tunnels | 1,759 | 14,072 | 14,072 | 14,072 | 2025-09-21 |
| Tai Lam Tunnel | 3,944 | 120,435 | 125,206 | 129,406 | 2026-07-17 |
| Tate's Cairn Tunnel | 2,832 | 56,640 | 56,640 | 56,640 | 2016-01-01 |
| Tsing Sha Control Area | 1,393 | 11,144 | 11,144 | 11,144 | 2008-03-21 |
| Western Harbour Crossing | 4,557 | 160,278 | 166,818 | 173,012 | 2026-07-17 |
| **All facilities** | **30,837 events** | **732,821** | **751,760** | **769,064** | mixed |

All event counts and charge-leg counts are equal within a facility because the
audited routes contain no sufficiently evidenced repeated passage of the same
physical facility in one leg. A leg can still traverse multiple different
facilities. The mapping invariant is 4,786 such car-mode legs across private
cars and out-of-scope motorcycles; 4,627 are private-car toll-bearing legs.
Their facility events are rated separately before leg aggregation.

### Resolved-only distributions

Resolved-only statistics include all 64,789 private-car legs, including
confirmed no-charge true zeros. They exclude all 2,929 out-of-scope motorcycle
rows and would exclude unresolved rows rather than treating them as zero.

| Scenario | Total (HKD) | Mean (HKD/leg) | Median | P90 |
|---|---:|---:|---:|---:|
| low | 732,821 | 11.311 | 0 | 40 |
| base | 751,760 | 11.603 | 0 | 40 |
| high | 769,064 | 11.870 | 0 | 40 |

Private-car resolved coverage is 100%. Coverage across all car-mode records,
including out-of-scope motorcycles, is 95.675%.

## Outputs

- `car_toll_passage_events.parquet`: one physical passage event per scenario,
  including ordered route positions, match clusters, estimated times, official
  rate interval, provenance, alias handling, status, and cost;
- `car_leg_toll_cost_estimates_low.parquet`;
- `car_leg_toll_cost_estimates_base.parquet`;
- `car_leg_toll_cost_estimates_high.parquet`;
- `toll_rate_application_validation.json`;
- `toll_rate_application_summary.csv`;
- `toll_rate_required_repairs.csv`;
- `toll_rate_input_hashes.json`.

The three leg files each contain exactly one row per car leg. Event-to-leg
aggregation has maximum absolute error HKD 0.00.

## Validation

The generated validation confirms:

- mapping identification matches commit `94e02c8`: 67,718 car legs, 64,789
  private-car legs, 2,929 motorcycles, 25,858 charge legs, 38,931 no-charge
  legs, 4,786 all-car multi-facility legs, 4,627 private-car multi-facility
  legs, and 27,220 legs differing from the old car-cost v1 identification;
- every event has exactly one canonical physical facility;
- WHC alias merging produces no duplicate physical events;
- no repeated-facility event remains unexplained;
- per-event sums equal per-leg toll amounts exactly;
- all non-null amounts satisfy `low <= base <= high`;
- true zeros occur only for `confirmed_no_charge`;
- unresolved and out-of-scope amounts are null;
- official rate schedules have no gaps or overlaps;
- incomplete records are excluded from distributions and totals;
- all locked audit files, canonical plans/network, and existing car-cost
  inputs and outputs have unchanged SHA256 values.

## Reproduction

From the feature worktree:

```powershell
<geo-python> -B scripts/hong_kong_single_city/costs/car/apply_hong_kong_private_car_toll_rates.py `
  --input-project-root <canonical-project-root>
```

The canonical root is a runtime input role. It is intentionally not embedded
as a personal absolute path in committed outputs.
