# Hong Kong private-car unified marginal-cost interface v1

## Status and scope

This document describes the publishable **offline candidate** built from the
independently audited Hong Kong private-car energy, toll, and destination
parking applications. The candidate was built from source commit
`f3fa7b6ad510929d087da29df32d5f2be375e5eb` on 2026-07-29.

The interface does not alter MATSim scoring, plans, config, network,
facilities, vehicles, mode choice, or any simulation output. In particular:

- `candidate_output_only = true`;
- `matsim_scoring_modified = false`;
- `scoring_adoption_approved = false`;
- `joint_mode_choice_calibration_approved = false`;
- `fixed_vehicle_ownership_behavioral_inclusion = false`.

The current decision horizon is daily travel and mode choice with exogenous
vehicle ownership. The only trip-conditional marginal components represented
in the behavioral interface are:

1. `fuel_or_electricity`;
2. `toll`;
3. `destination_parking`.

Fixed vehicle ownership is a sunk cost at this decision horizon. It is
referenced through an accounting sidecar, never copied to a leg, never assigned
to the first or last vehicle use, and never summed into a behavioral marginal
total.

## Inputs and frozen provenance

The three marginal components come from:

- `energy_application_v1`, bundle SHA256
  `0335c56a62a9ecae9af3035bce5d183b148ee156f0ca6b41dd04b3c48e7c370c`;
- `toll_rate_application_v1`, bundle SHA256
  `43d095651bfa8b9ed988ab8fd4c784caf51f2633a22aa4641e103214ea530c19`,
  based on `toll_network_mapping_v1`, bundle SHA256
  `b430c3a776014fcf9843084efb3020be3cbd6e8003813d632099de4d131f8a44`;
- `parking_event_application_v1`, bundle SHA256
  `15971e677ae47b53e58f5028be9e8e505655f468c4464fcc3af337353632ba70`.

The fixed-cost accounting reference points to
`fixed_ownership_application_v1`, bundle SHA256
`a3944de62ff52da0f3e49e1f23df3e9e699ef08d667cd239b0480bdc31722115`.

All five bundles were hashed before and after the build and were unchanged.
The routed and unrouted plans, private vehicles, facilities, trip manifest,
config, network, transit schedule, and transit vehicles were also hashed
before and after. Their paths and full SHA256 values are recorded in
`unified_marginal_cost_input_hashes.json`; all nine hashes were unchanged.
The absolute location of the read-only canonical project is deliberately not
stored in the output.

The component candidates must each have a publishable, unblocked validation
record. No source candidate is repaired or rewritten by this interface build.

## Canonical leg identity and join contract

The canonical population consists of 67,718 car-mode legs:

- 64,789 private-car legs;
- 2,929 motorcycle legs, which are outside this model's scope.

The canonical key is:

```text
person_id + leg_sequence + scenario
```

Within one scenario, `person_id + leg_sequence` must be unique and the key set
must exactly equal the canonical 67,718-leg set. Each source table is joined
one-to-one. `mode`, `vehicle_ref_id`, and `vehicle_class` must agree with the
trip manifest, feasibility inventory, and private-vehicle XML wherever the
source candidate carries those fields.

The toll leg candidate does not itself carry `vehicle_ref_id` or
`vehicle_class`. Those two fields are enriched only after the toll key set and
mode have matched the canonical identity exactly. This limitation is retained
as non-blocking repair `UNIFIED-R01`.

## Output contract

The output directory is:

```text
data/transport_costs/hongkong/car_cost_v1/
  unified_marginal_cost_interface_v1/
```

For each of `low`, `base`, and `high`, the long component table contains
203,154 rows: 67,718 legs times exactly three marginal components. Across all
scenarios the long interface therefore contains 609,462 component records.
Each scenario also has one 67,718-row leg summary.

The long-table contract retains identity, scenario, component cost, status,
source, effective date, quality, source snapshot hash, route distance,
distance band, destination activity group, and explicit behavioral boundary
flags. The summary contract places the three component values and statuses
side by side and calculates:

```text
behavioral_marginal_cost_hkd =
  fuel_or_electricity_hkd
  + toll_hkd
  + destination_parking_hkd
```

This formula is applied only when all three required components are resolved
and the vehicle class is `private_car`. The total is null for incomplete
private-car legs and for all motorcycles.

`low`, `base`, and `high` preserve the independently audited scenario
semantics of each source component. They are sensitivity bounds, not observed
leg-specific uncertainty intervals.

## Null, unresolved, and legal-zero policy

Unresolved and out-of-scope records are never filled with zero:

- all 2,929 motorcycles have null component costs and a null marginal total;
- 835 private-car legs with unresolved parking retain a null parking cost and
  a null marginal total;
- the resolved energy and toll values on those 835 legs remain available in
  the long table but are not presented as a complete behavioral total.

Zero is legal only when its source status explicitly supports zero:

- energy: 33 `resolved_zero_distance_energy_zero` legs;
- toll: 38,931 `confirmed_no_charge` legs;
- parking: 28,390
  `resolved_home_marginal_zero_fixed_separate` legs in every scenario;
- low parking only: a further 8,605
  `resolved_work_subscription_assumed_prepaid` legs.

The base and high work-parking scenarios apply their audited non-zero
alternatives. No unresolved or out-of-scope record has a numeric zero.

## Coverage and unresolved evidence

Within the 64,789 private-car legs:

- toll identification is 100.000%: 25,858 confirmed charged passages and
  38,931 confirmed no-charge legs;
- destination parking is resolved for 63,954 legs, or 98.711%;
- 835 legs, or 1.289%, have unresolved parking;
- the complete three-component behavioral set is therefore 63,954 legs.

If motorcycles are retained in the denominator, confirmed in-scope toll
coverage is 95.675% and resolved in-scope parking coverage is 94.442%.

The 835 unresolved parking records comprise:

| Reason | Legs | Share of unresolved |
| --- | ---: | ---: |
| vehicle time overlap | 466 | 55.808% |
| next-departure facility mismatch | 269 | 32.216% |
| missing destination zone | 98 | 11.737% |
| missing next departure for terminal non-home parking | 2 | 0.240% |

These are evidence gaps, not zero-cost observations. Repairing them requires
vehicle-chain, facility, zone, or terminal-duration evidence upstream.

## Cost results

Statistics below use the 63,954 complete private-car legs only for the
behavioral total.

| Scenario | Total HKD | Mean HKD/leg | Median HKD/leg | P90 HKD/leg |
| --- | ---: | ---: | ---: | ---: |
| low | 3,178,496.28 | 49.70 | 44.54 | 94.78 |
| base | 5,648,792.21 | 88.33 | 70.37 | 188.33 |
| high | 7,598,354.11 | 118.81 | 93.97 | 267.65 |

The independently resolved component totals and distributions are:

| Scenario | Component | Resolved legs | Total HKD | Mean | Median | P90 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| low | fuel/electricity | 64,789 | 1,659,564.36 | 25.61 | 20.45 | 54.17 |
| low | toll | 64,789 | 732,821.00 | 11.31 | 0.00 | 40.00 |
| low | parking | 63,954 | 838,964.00 | 13.12 | 0.00 | 38.00 |
| base | fuel/electricity | 64,789 | 2,341,793.95 | 36.14 | 28.86 | 76.44 |
| base | toll | 64,789 | 751,760.00 | 11.60 | 0.00 | 40.00 |
| base | parking | 63,954 | 2,624,827.00 | 41.04 | 32.00 | 110.00 |
| high | fuel/electricity | 64,789 | 3,564,398.11 | 55.02 | 43.93 | 116.34 |
| high | toll | 64,789 | 769,064.00 | 11.87 | 0.00 | 40.00 |
| high | parking | 63,954 | 3,363,957.00 | 52.60 | 42.00 | 192.00 |

Component totals include every resolved in-scope component record. They need
not sum to the complete behavioral total because the latter excludes all
components on the 835 parking-incomplete legs.

## Fixed ownership accounting sidecar

The sidecar covers 21,020 used private vehicles and records scenario accounting
totals of HKD 243,910.78, HKD 2,651,066.58, and HKD 3,856,274.15 for low,
base, and high. It is a partial vehicle-day accounting proxy, not complete
total cost of ownership: owners and unused owned vehicles are not observed.

The sidecar is suitable only for accounting, policy reporting, and future
long-term ownership analysis. It is not incremental when a daily car leg is
chosen and is not eligible for MATSim scoring under the current design.

## Behavioral recommendation

For a future first scoring pilot, the defensible marginal composition is
resolved representative fleet energy plus confirmed private-car toll plus
resolved destination parking. Only the complete private-car set should be used
unless the 835 parking evidence gaps are repaired or an explicitly approved
missing-data design is introduced.

This recommendation is a data-interface boundary, not scoring approval.
Adoption still requires a separate behavioral design, a decision on the
monetary utility and double counting, implementation outside this audit, joint
mode-choice calibration, and simulation validation. Fixed ownership must
remain excluded at the current daily decision horizon.

## Files

The interface contains:

- three `car_leg_marginal_cost_components_<scenario>.parquet` files;
- three `car_leg_marginal_cost_summary_<scenario>.parquet` files;
- `marginal_cost_component_registry.csv`;
- `unified_marginal_cost_summary.csv`;
- `unified_marginal_cost_validation.json`;
- `unified_marginal_cost_input_hashes.json`;
- `unified_marginal_cost_required_repairs.csv`;
- `fixed_ownership_accounting_sidecar_reference.json`.

The builder is:

```text
scripts/hong_kong_single_city/costs/car/
  build_hong_kong_unified_marginal_cost_interface.py
```

Run it from this worktree with the project geospatial Python and an explicit
read-only canonical input root:

```powershell
& "F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe" -B `
  "scripts\hong_kong_single_city\costs\car\build_hong_kong_unified_marginal_cost_interface.py" `
  --input-project-root "F:\Matsim\matsim-example-project"
```

## Validation

The candidate is publishable and unblocked. The build verifies:

- exact per-scenario and all-scenario row counts;
- unique canonical keys and one-to-one component joins;
- canonical mode, vehicle reference, and vehicle class consistency;
- 63,954 complete and 835 incomplete private-car legs in every scenario;
- 2,929 motorcycles remain out of scope with null costs;
- no negative cost and no unresolved/out-of-scope zero;
- exact three-component arithmetic on complete legs;
- null totals on incomplete and out-of-scope legs;
- legal-zero statuses only;
- zero fixed-cost rows in all leg component tables;
- no fixed cost in a leg total;
- no scoring-adoption flag set;
- all source candidate validations remain publishable and unblocked;
- all candidate bundles and protected canonical inputs retain their SHA256.

The builder passes `py_compile`; repository validation additionally runs
`--help`, an independent output audit, `git diff --check`, and a scope check
before publication.
