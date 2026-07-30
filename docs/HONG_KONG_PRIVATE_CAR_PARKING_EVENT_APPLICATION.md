# Hong Kong private-car physical parking-event application v1

## Scope and status

This candidate reconstructs destination-parking events from complete
private-vehicle daily chains, then applies the audited Hong Kong parking proxy
rules in low, base, and high scenarios. It is an offline, standalone candidate:
it does not change MATSim scoring, plans, config, network, facilities, vehicles,
the unified car-cost outputs, or either toll candidate.

The result is publishable as an
`official_rate_bounded_zone_activity_proxy`. It is not a claim that a MATSim
destination facility is an observed car park or that its exact tariff is
known.

## Locked inputs and provenance

The build is tied to source commit
`44f15a95a1a00aeaac7c9163a344d15caf787497`. Large canonical inputs are read
from a separately supplied, read-only project root:

- `data/matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice/plans_routed_5pct_v2.xml.gz`;
- `data/matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice/facilities_5pct_v2.xml.gz`;
- `data/matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice/privateVehicles_5pct.xml.gz`;
- `data/matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice/agent_trip_manifest_v2.parquet`.

The audited TCS-zone and activity mapping comes from
`data/transport_costs/hongkong/car_cost_v1/input_feasibility/`. Price rules
come from
`data/transport_costs/hongkong/car_cost_v1/car_parking_cost_rules.csv`, whose
official source snapshots and SHA256 values are retained under the same
car-cost directory.

`parking_event_input_hashes.json` records repository-relative roles and
before/after hashes. All canonical inputs, all pre-existing car-cost files,
`toll_network_mapping_v1`, and `toll_rate_application_v1` remained byte
identical.

## Physical vehicle-chain reconstruction

The script selects all routed car arrivals and joins the trip manifest,
vehicle inventory, facilities, and feasibility audit by audited identifiers.
It then sorts actual movements by:

1. `vehicle_ref_id`;
2. absolute `departure_time_s`;
3. `person_id`;
4. `leg_sequence`.

Parking starts at the routed leg arrival and ends at the same vehicle's next
departure. Absolute MATSim model-day seconds are preserved when constructing
the chain. Modulo 24 hours is used only to choose a day or night hourly rate,
never to infer event order or duration.

The stable physical key hashes the vehicle, destination facility, arrival
time, and next-departure time (or an explicit terminal marker). Person and leg
identifiers are retained for traceability but are deliberately excluded from
the physical identity. Duplicate diagnostics are computed on the raw arrivals
before scenario expansion or any possible de-duplication:

| Audit item | Count |
| --- | ---: |
| Raw car arrivals | 67,718 |
| Private-car physical events | 64,789 |
| Motorcycle arrivals, out of scope | 2,929 |
| Used private cars | 21,020 |
| Duplicate physical keys | 0 |
| Legs mapped to a shared physical key | 0 |
| Excess leg mappings | 0 |

The output does not merge or drop an event. Each scenario contains 67,718
leg-level rows, including explicit unresolved private-car and out-of-scope
motorcycle records.

## Vehicle-chain quality

Chain defects take precedence over zero-cost rules:

| Diagnostic | Count |
| --- | ---: |
| Arrival later than same vehicle's next departure | 466 |
| Next departure facility differs from parked destination | 321 |
| Both diagnostics | 52 |
| Union of chain-defective events | 735 |
| Terminal home events | 21,018 |
| Terminal non-home events | 2 |
| Valid events crossing midnight | 1,359 |
| Cross-midnight base events switching day/night rate | 1,007 |

The earlier feasibility benchmark reported 267 unresolved vehicle-chain
records because its status precedence applied the home marginal-zero rule
before exposing home-chain defects. The physical-event rebuild reports the
full union of 735, revealing 468 additional home-arrival chain defects. This is
an explained audit improvement, not a changed input count.

The two terminal non-home arrivals have no supported duration and remain null.
Terminal home arrivals may resolve to zero marginal cost because residential
parking is explicitly outside the per-arrival marginal charge.

## Pricing logic

All supported hourly activities are billed by each started 3,600-second unit.
The rate for a unit is selected using that unit's clock time, so an event can
cross the 07:00/23:00 day-period boundaries or midnight and receive different
unit rates. Scenario-specific daily caps are applied after unit charges.

- `home`: temporary destination charge is zero; residential monthly or owned
  parking remains a separate fixed cost.
- `work`, low: a prepaid subscription is assumed, so the marginal event charge
  is zero and the monthly value is retained only as an excluded fixed-cost
  field.
- `work`, base: the scenario's day-pass proxy applies.
- `work`, high: started-hour billing applies, subject to its minimum charge and
  daily cap.
- `education`, `shopping`, `leisure`, and
  `medical_personal_business`: started-hour day/night proxy with the applicable
  cap.
- Missing destination zones, invalid chains, and unsupported durations remain
  unresolved with null cost.
- Motorcycles remain out of scope with null cost.

No residential fixed parking or monthly work subscription is repeated on a
leg, and unresolved/out-of-scope records are not converted to zero.

## Results

Each scenario resolves 63,954 private-car arrivals, leaves 835 private-car
arrivals unresolved, and retains 2,929 motorcycle arrivals as out of scope.
Resolved-only distributions are:

| Scenario | Total (HKD) | Mean | Median | P90 |
| --- | ---: | ---: | ---: | ---: |
| low | 838,964 | 13.118 | 0 | 38 |
| base | 2,624,827 | 41.042 | 32 | 110 |
| high | 3,363,957 | 52.600 | 42 | 192 |

Resolved-only totals by destination activity are:

| Activity | Low (HKD) | Base (HKD) | High (HKD) |
| --- | ---: | ---: | ---: |
| home | 0 | 0 | 0 |
| work | 0 | 1,374,350 | 1,867,269 |
| education | 2,902 | 4,366 | 5,293 |
| shopping | 205,490 | 306,845 | 367,361 |
| leisure | 539,928 | 804,077 | 962,382 |
| medical/personal business | 90,644 | 135,189 | 161,652 |

Resolved-only totals by zone group are:

| Zone group | Low (HKD) | Base (HKD) | High (HKD) |
| --- | ---: | ---: | ---: |
| Hong Kong Island | 234,298 | 916,111 | 1,026,760 |
| Kowloon urban | 388,272 | 1,059,400 | 1,359,359 |
| New Territories/Lantau | 216,394 | 649,316 | 977,838 |

The main unresolved sources are the 735 vehicle-chain defects, 98 missing
destination zones, and two terminal non-home events without a duration. Chain
overlap and facility mismatch are non-mutually-exclusive input diagnostics;
their union, rather than their arithmetic sum, is used in totals.

## Outputs

`data/transport_costs/hongkong/car_cost_v1/parking_event_application_v1/`
contains:

- `car_parking_events.parquet`: scenario-expanded physical event audit;
- `car_leg_parking_cost_estimates_low.parquet`;
- `car_leg_parking_cost_estimates_base.parquet`;
- `car_leg_parking_cost_estimates_high.parquet`;
- `parking_event_application_validation.json`;
- `parking_event_application_summary.csv`;
- `parking_event_required_repairs.csv`;
- `parking_event_input_hashes.json`;
- `parking_cost_rules_repository_relative.csv`.

Event-to-leg aggregation is exact in all scenarios. The separate leg files
provide one row per original car leg and preserve null costs and explicit
statuses.

## Reproduction and validation

Run from the feature-worktree root with the project geospatial Python:

```powershell
<python-geo311> scripts/hong_kong_single_city/costs/car/apply_hong_kong_private_car_parking_costs.py `
  --input-project-root <canonical-project-root>
```

The validation asserts raw and scenario row counts, key uniqueness, exact
event-to-leg aggregation, non-negative resolved costs, null unresolved costs,
`low <= base <= high`, home/fixed-cost boundaries, cross-midnight handling,
and before/after protected-file hashes. The output is suitable for offline
sensitivity analysis; adopting it into MATSim monetary scoring requires a
separate decision and implementation.
