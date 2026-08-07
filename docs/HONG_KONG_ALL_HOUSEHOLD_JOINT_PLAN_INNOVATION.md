# Hong Kong all-household joint-plan innovation

## Scope

This Stage 11 extension gives every screened car-owning household a later
joint-travel alternative without changing the initial selected plans. It
supersedes neither the adopted 50-iteration production run nor the original
44,000 Taxi / 2,734 `car_passenger` / 9,626 `school_bus` demand allocation.

The implementation deliberately separates two moments:

1. iteration 0 runs the original selected plans and original mode totals;
2. in the iteration-1 replanning phase, after MATSim's ordinary replanning
   hook, the custom household selector creates the alternative templates,
   evaluates routed choices, selects a compatible household bundle, and
   supplies physical bindings before iteration-1 QSim.

Ordinary `ReRoute`, `SubtourModeChoice`, and `TimeAllocationMutator` strategies
remain frozen during this technical gate. The household selector is the only
plan-changing mechanism.

## Candidate audit

The current registry is:

```text
data/taxi/hongkong/processed/taxi_44000_no_ride_student_swap_v1/
  household_joint_plan_potential_audit_v3/
    household_joint_plan_potential_candidates.csv
```

The screen starts from households with an adult assigned vehicle holder and a
home-based day. Its main counts are:

| Measure | Count |
|---|---:|
| Car households in scope | 22,235 |
| Eligible driver people | 24,800 |
| Candidate passenger-driver pairs | 9,289 |
| Candidate households | 5,789 |
| Candidate passenger people | 7,210 |
| Reuse an existing driver Car trip | 7,177 |
| Require a complete driver-day Car switch | 2,112 |

Passenger-trip coverage is 657 original `car_passenger`, 6,129 PT, 309 Taxi,
and 1,924 Walk main trips. This is a feasibility screen, not a quota: a trip
may have up to three candidate drivers, and routed schedule feasibility is
checked later. V3 removes 90 passenger trips whose pickup and drop-off resolve
to the same network link; one `LinkEnterEvent` cannot represent distinct
boarding and later alighting on that same link. Historical v1/v2 screens are
retained for provenance.

## Alternative-plan contract

During iteration-1 replanning, the population receives unselected templates:

- one passenger and one driver template for each of the 9,289 joint pairs;
- three release templates (`pt`, `taxi`, and `walk`) for each of the 2,734
  original `car_passenger` main trips;
- no `school_bus` alternative in this phase.

The original selected plan remains selected throughout iteration 0. The
ordinary strategy is `KeepLastSelected`; `ChangeExpBeta` is disabled so the
core replanning lifecycle cannot select a template independently. The custom
selector then builds one routed composite plan per changed person, so driver
and passenger changes are applied atomically.

Each passenger main trip is an independent choice unit. Therefore one
direction may be `car_passenger` while the other direction uses PT, Taxi, or
Walk. A selected joint trip must contain the real passenger pickup and drop-off
network links. An original `car_passenger` trip that is not physically bound
is released to the maximum-utility routed PT, Taxi, or Walk choice. Passenger
Car is not introduced by this mechanism.

## Household selection and vehicle consistency

For passengers, the bound score is the established willingness-plus-time
formula:

```text
S_car_passenger = -1.5 - 6 * travel_time_hours
```

PT and Walk use the configured routed leg utilities; PT also uses the live PT
fare catalog. Taxi uses the adopted formula and routed fare:

```text
S_taxi = -9 - 6 * travel_time_hours - 0.05 * route_based_fare_hkd
```

Driver Car route utility uses the same link-level energy and toll rules and
destination/dwell parking rules as experienced scoring. If the driver already
has the compatible Car trip, only that trip is rerouted through the passenger
waypoints. If the driver was not using Car, every main trip in the complete
home-based day is routed as Car; this prevents the vehicle from appearing at
an impossible location.

The deterministic household selector maximizes aggregate utility without a
choice probability or driver-participation constraint. It enforces:

- one choice per passenger main trip;
- one waypoint passenger per driver main trip in this implementation;
- a full-day vehicle reservation when a candidate requires driver mode switch;
- no competing candidate on that vehicle day when such a switch is selected.

This conservative resource rule can later be extended to multi-passenger
carpools, but no such composite waypoint chain is generated now.

## Implementation

Key Java entry points:

```text
src/main/java/org/matsim/project/RunHongKong5Pct.java
src/main/java/org/matsim/project/hongkong/household/
  HouseholdJointPlanCandidateCatalog.java
  HouseholdJointPlanAlternativeGenerator.java
  HouseholdJointPlanSelector.java
  HouseholdJointPlanInnovationModule.java
```

CLI option:

```text
--household-joint-plan-candidates=<candidate-csv>
```

It requires live multimodal scoring and `--dynamic-car-costs`, and is mutually
exclusive with the historical fixed-binding household pilot options.

Server launch and audit scripts:

```text
scripts/hong_kong_single_city/run/
  launch_hong_kong_all_household_joint_plan_pilot.py
  audit_hong_kong_all_household_joint_plan_pilot.py
```

## Current validation

The validated iterations 0–1 gate is:

```text
/mnt/DiskM/by/hk_stage11_all_household_joint_20260807_release13
/mnt/DiskM/by/hk_stage11_all_household_joint_20260807_run13
/mnt/DiskM/by/hk_stage11_all_household_joint_20260807_run13/
  household_joint_plan_pilot_audit_v3.json
```

The compact local audit is
`data/taxi/hongkong/processed/taxi_44000_no_ride_student_swap_v1/household_joint_plan_potential_audit_v3/all_household_joint_plan_iterations_0_1_run13_success.json`.

The process exited `0`, and the independent audit passed every check. From
9,289 candidate pairs in 5,789 households, exact deterministic selection chose
2,124 joint trips and 7,165 fallbacks. All selected pairs reused an existing
driver Car trip; none of the 2,112 complete driver-day Car-switch candidates
was selected. The selector rejected 3,060 routed schedule-infeasible pairs.

Of the original 2,734 `car_passenger` trips, 267 remained joint and 2,467 were
released: 136 to PT, 261 to Taxi, and 2,070 to Walk. Candidate generation also
introduced joint alternatives for trips originally using PT, Taxi, or Walk,
so final selected-plan leg counts were Car 67,718, `car_passenger` 2,124, PT
556,243, `school_bus` 9,626, Taxi 44,121, and Walk 201,668. PT/Walk totals are
leg counts and include routed stage legs. Generic `ride` remained absent.

The physical engine classified all 2,124 active bindings with no residual
waiting or onboard state: 1,667 completed exact-waypoint rides, 12 passengers
became stuck onboard, 101 drivers became stuck before pickup, 31 later bindings
were skipped after a prior bound failure, 299 were still waiting at the
simulation horizon, and 14 agents never reached their later bound departure
before 30:00. These terminal classifications are failures, not completions.

The retained diagnostic runs document the lifecycle fixes: delayed template
creation, explicit Taxi attributes on both leg and origin activity,
`KeepLastSelected`, selector execution after core replanning, same-link
pickup/drop-off exclusion, and a `(vehicle, waypoint link)` physical-event
index. The last change avoids both concurrent map mutation and the prohibitive
global scan/lock observed in run11.

## Limitations and future extension

- The candidate screen covers 5,789 of 22,235 in-scope car households under
  the present time/detour thresholds; households without a compatible trip
  timing remain unchanged.
- Choice is deterministic and has no calibrated probability or explicit
  driver acceptance constraint.
- Newly selected driver Car days use fixed activity times; infeasible routed
  schedules are rejected rather than time-mutated.
- `school_bus` is intentionally excluded until its physical and scoring model
  is stable. Future inclusion should add it as an explicit release/candidate
  mode rather than reintroducing generic `ride`.
- This two-iteration gate validates mechanics and coupled scoring, not a
  converged household mode-choice equilibrium.
