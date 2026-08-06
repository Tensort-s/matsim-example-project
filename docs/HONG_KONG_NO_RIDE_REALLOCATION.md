# Hong Kong no-`ride` passenger-mode reallocation

## Status

This document records the adopted Stage 11 demand candidate created on
2026-08-05/06. It is a technical-integration input and does not replace the
current adopted 50-iteration production scenario or its SimWrapper output.

The candidate removes the aggregate MATSim `ride` mode and conserves the
original 56,360 point-to-point passenger legs as:

| Explicit mode | 5% legs | Eligibility rule |
|---|---:|---|
| `taxi` | 44,000 | Licensed taxi and ride-hailing are combined and use the same Taxi mode and fare scorer. |
| `car_passenger` | 2,734 | 2,490 student legs plus 244 fixed-worker legs; every final person belongs to a household with at least one private vehicle. |
| `school_bus` | 9,626 | Students only. |
| `ride` | 0 | Removed from plans, routing, scoring, and the mode-choice set. |

The identity is exact: `44,000 + 2,734 + 9,626 = 56,360`.

## Student-to-student exchange

The compulsory baseline contained 1,245 students and 2,490 legs labelled
`private_vehicle`, but 956 of those students had
`household_private_vehicle_count=0`. The 2,490-leg student control is retained
without allowing a no-car household to use `car_passenger`:

- the 289 already eligible students and their 578 legs remain passenger trips;
- 956 no-car students move to PT or walk;
- 956 students from car-owning households move from PT or walk to
  `car_passenger`;
- each displaced student inherits the paired donor's original PT/walk mode, so
  aggregate PT and walk main-trip totals are unchanged;
- 955 pairs match the same school stage and home TCS zone;
- the one remaining special-school pair uses the nearest same-stage donor from
  another TCS zone.

The transferred donor modes comprise 425 PT students/850 legs and 531 walking
students/1,062 legs. Pair-level provenance is in
`data/taxi/hongkong/processed/taxi_44000_no_ride_student_swap_v1/student_mode_swap_pairs.csv`.

## Adult passenger selection

The original compulsory population contains 537 fixed workers/1,074 legs
encoded as `private_car_passenger_van` with `matsim_mode=ride`; all 537 belong
to car-owning households. A deterministic, stratified selection retains 122
complete return tours/244 legs as `car_passenger`. The other 415 tours/830
legs become Taxi. Selection strata use home TCS zone, sex, and Census age
band; the random generator seed is `20260805`.

No discretionary adult `ride` tour is used to replace a student trip.

## Household real-driver candidate audit

A read-only candidate audit now tests whether each of the 2,734
`car_passenger` legs can be associated with a real driver already present in
the final Stage 11 plans. A real driver is a different member of the same
household who has an assigned five-seat `private_car`, an existing routed
`mode=car` leg, and a matching route `vehicleRefId`. Motorcycle legs are
excluded. The audit does not create a binding, modify a plan, or create a new
escort tour.

The screening levels are deliberately separate:

- **household driver exists:** at least one such real driver exists somewhere
  in the current household plans, irrespective of trip compatibility;
- **direct existing leg:** departure and arrival are each within 15 minutes,
  and both origin and destination are within 500 m;
- **detour screen:** departure is within 30 minutes, origin is within 500 m,
  and a coordinate-based passenger drop-off adds no more than 5 km and no
  more than 1.5 times the driver's direct straight-line distance.

The detour result is only a candidate screen. It is not a network-routed
joint plan and does not prove driver acceptance, schedule feasibility, or
vehicle-capacity feasibility.

Overall result:

| Result | Legs | Share of 2,734 |
|---|---:|---:|
| Same-household real driver exists in current plans | 2,254 | 82.4433% |
| Directly compatible existing Car leg | 280 | 10.2414% |
| Additional detour-screen candidate | 104 | 3.8040% |
| Direct or detour-screen compatible | 384 | 14.0454% |
| Real driver exists but no compatible existing leg | 1,870 | 68.3980% |
| No real driver in the current plans | 480 | 17.5567% |

The 2,734 legs belong to 1,367 people in 1,283 households. Only 139 people
(`10.1683%`) have both legs directly compatible with the same driver. These
139 student-driver pairs exactly reproduce the accepted legacy
`school_escort_assignments.csv`: person IDs and driver IDs both match with
zero discrepancy. One additional student has both legs pass the detour screen
but only with different drivers, so it is not counted as a same-driver return
tour.

Breakdown by allocation source:

| Allocation source | Direct | Detour screen only | Real driver, incompatible | No real driver | Total legs |
|---|---:|---:|---:|---:|---:|
| Original eligible student `private_vehicle` retained | 278 | 20 | 248 | 32 | 578 |
| Car-household student introduced by the 956-person swap | 2 | 81 | 1,571 | 258 | 1,912 |
| Retained adult `private_car_passenger_van` | 0 | 3 | 51 | 190 | 244 |
| **Total** | **280** | **104** | **1,870** | **480** | **2,734** |

This establishes that `household_private_vehicle_count > 0` is a valid
eligibility condition but not evidence of an executable joint trip. Binding
more than the 139 existing complete pairs will require a later joint-plan
builder that changes driver schedules or creates new escort tours. That work
must also perform routed detour, score, simultaneous passenger-capacity, and
driver-participation checks.

## Fixed 139-pair physical pilot

The 139 complete same-driver school-escort candidates were subsequently used
in a bounded physical-QVehicle pilot. The binding catalog contains 278
passenger legs. Each bound `car_passenger` departure waits for the identified
driver's existing private-car vehicle, boards that vehicle, travels with its
actual network movement, and alights when the bound driver Car leg arrives.
The catalog is keyed by passenger/person selected-plan leg index; it does not
create a household selector, change either member's plan, or synthesize a new
escort tour. The maximum implicit access/egress coordinate gap in the fixed
catalog is 378.512 m.

The immutable one-iteration validation is:

```text
release: /mnt/DiskM/by/hk_stage11_school_escort_physical_20260806_release4
run:     /mnt/DiskM/by/hk_stage11_school_escort_physical_20260806_run4
QSim:    iteration 0 only; exit code 0
```

Plan innovation remained frozen: `ChangeExpBeta=1`, with `ReRoute`,
`SubtourModeChoice`, and `TimeAllocationMutator` all at `0`. Event and engine
audits passed. Of 278 bound legs, 273 completed the exact
departure-board-alight-arrival sequence, and all 273 alightings coincided with
the corresponding driver Car arrival. The bound vehicles generated 33,415
`left link` and 33,411 `entered link` events, while bound passenger legs
generated zero teleported arrivals. In person terms, 135 of the 139 students
completed both physical legs.

The five non-completed leg outcomes were fully classified: one passenger was
on board when the driver's vehicle became stuck, three return pickups could
not begin because the driver became stuck on the preceding approach Car leg,
and one later bound leg was skipped after that passenger's earlier bound-leg
failure. The run ended with zero waiting and zero onboard passengers, so the
physical engine did not leave unresolved binding state or fall back to
teleportation. These outcomes show that 139 static complete candidates do not
guarantee 139 dynamically completed round trips under the current congested
network and `stuckTime=600 s` policy.

Only these 278 legs use physical binding. The remaining 2,456
`car_passenger` legs retain the provisional teleported implementation. This
pilot validates event mechanics and failure handling; it does not yet provide
joint household plan selection, endogenous binding/unbinding, rerouting, or
driver acceptance of added escort travel.

### One-cycle binding-preserving JointReRoute

A second isolated pilot applies exactly one `JointReRoute` cycle while keeping
the same 139 passengers, 278 passenger/driver-leg keys, and private-car
vehicle assignments fixed. It first runs `it.0` to obtain network travel
times, reroutes only the 278 referenced driver Car legs, and then runs `it.1`
to validate physical passenger movement. Ordinary `ReRoute`,
`SubtourModeChoice`, and `TimeAllocationMutator` remain at `0`; therefore the
single controlled JointReRoute is the only route innovation.

```text
release: /mnt/DiskM/by/hk_stage11_school_escort_joint_reroute_20260806_release4
run:     /mnt/DiskM/by/hk_stage11_school_escort_joint_reroute_20260806_run4
cycle:   it.0 -> one JointReRoute -> it.1; exit code 0
```

Direct input/output link-sequence comparison found 208 changed driver routes
and 70 unchanged routes. All 278 output bindings retained the same passenger
leg index, driver leg index, vehicle ID, route start link, and route end link.
In `it.1`, 274 legs completed the exact physical
departure-board-alight-arrival sequence; all 274 alightings matched the
driver's Car arrival, and no bound leg used teleportation. The engine
classified all outcomes as 274 completed, one passenger stuck while onboard,
and three drivers stuck before pickup, with no downstream skipped leg and no
waiting/onboard state left at the end. As in the fixed-route pilot, 135 of 139
students completed both legs.

This run deliberately excludes the custom Taxi/PT/Car multimodal-cost module.
The current Car energy, toll, and parking tables are keyed to the fixed
canonical routes and cannot validly price newly rerouted links. Consequently,
this result proves binding persistence and physical QVehicle execution under
one route-innovation cycle, but it is not evidence that the current static
cost stack supports rerouting. Dynamic route-based Car cost calculation is a
dependency for combining JointReRoute with the full Stage 11 scoring stack.

## Taxi allocation and scoring

Taxi is exactly:

```text
4,614 explicit Taxi legs
+ 38,556 previously unspecified passenger legs
+    830 unretained fixed-worker passenger legs
= 44,000 Taxi legs
```

Ride-hailing is not a separate mode or fare model. All 44,000 legs use the
authorized Taxi score:

```text
S_taxi_leg = -9 - 6 * travel_time_hours - 0.05 * route_based_fare_hkd
```

Every Taxi leg and its origin activity carry the six native-routing Taxi
attributes, including `hkTaxiType`. `hkTaxiFareBaselineHkd` remains a
comparison field; live scoring calculates fare from the routed distance and
Taxi type.

`car_passenger` and `school_bus` are explicit teleported passenger modes. They
temporarily retain the historical `ride` scoring coefficients as independent
compatibility baselines until evidence-based formulas are authorized. The
139-pair physical pilot is the sole exception: its 278 bound
`car_passenger` legs use real private-car QVehicles, while the other 2,456
remain teleported. The configuration contains no `ride` mode parameter.
`SubtourModeChoice` offers only `car,pt,walk`, because standard MATSim
availability rules cannot enforce the household and student restrictions of
the two passenger modes.

The bounded Stage 11 run also freezes plan innovation: `ChangeExpBeta=1`,
while `ReRoute`, `SubtourModeChoice`, and `TimeAllocationMutator` all have
weight `0` for every subpopulation. The static Car energy/toll/parking tables
cannot price a newly generated mode or route.

## Routing repair

Changing 956 student pairs invalidates 3,824 old routes. The first route-only
population therefore contains exactly 3,824 null routes and no other null
route. A Taxi router that delegates to explicit `car_passenger`, plus explicit
walk routing at 1.34 m/s with beeline factor 1.3, removes the historical
dependency on aggregate `ride`.

The transit module must continue to declare the physical in-vehicle modes
`bus,gmb,train,light_rail,ferry`. The generic `pt` label is a routing/main-trip
mode and must not be placed in `transitModes`; doing so makes QSim incorrectly
require a `TransitRoute` on every generic PT main leg. The config generator
now writes and tests this invariant explicitly.

Because the candidate deliberately clears MATSim's default teleported-mode
table before adding only controlled modes, it also restores the baseline
generic-PT router explicitly with `teleportedModeFreespeedFactor=2.0`. Without
that entry, iteration 0 can simulate from existing routes but preparation for
iteration 1 fails with `UnknownModeException: pt`.

MATSim's default prepare-for-sim reroutes an entire plan if any route is null.
That changed unrelated Car routes for affected students and violated the
static Stage 11 Car-cost domain. The final selective merge copies only the
3,824 exchanged main trips from the successful whole-plan route result back
into the pre-route plans. All non-target trips—including every Car and
existing Taxi route—remain from the pre-route population.

Final selective-plan audit:

| Check | Result |
|---|---:|
| persons | 385,820 |
| raw legs | 881,236 |
| Taxi raw legs | 44,000 |
| car-passenger raw legs | 2,734 |
| school-bus raw legs | 9,626 |
| Car raw legs | 67,718 |
| null routes | 0 |
| Taxi legs without `hkTaxiType` | 0 |
| `ride` raw legs | 0 |

PT routing legitimately introduces passenger and access/egress stage legs;
therefore post-routing raw PT/walk leg counts are not the conservation unit.
Main-trip modes and the controlled passenger categories are conserved.

## Stage 11 10-iteration result

The accepted immutable run is:

```text
release reused: /mnt/DiskM/by/hk_multimodal_cost_stage11_taxi_44000_no_ride_20260806_release11
run:            /mnt/DiskM/by/hk_stage11_taxi_44000_no_ride_20260806_run14
```

It completed iterations `0..10`, produced 11 iteration directories and 11
30-hour QSim completion records, and exited `0` at
`2026-08-06T01:44:25+08:00`. The final log contains zero `ERROR` lines, zero
uncaught exceptions, zero Taxi/PT/Car scoring-schedule mismatches, and zero PT
agents removed for a missing `TransitRoute`. Wall time was 34 minutes 38.72
seconds and peak resident memory was 28,397,444 KiB.

Every iteration retained the same selected-plan mode shares. The final plans
contain exactly 44,000 Taxi legs, 2,734 `car_passenger` legs, 9,626
`school_bus` legs, and zero `ride` legs. Iteration 0 experienced 43,966 Taxi,
557,188 PT, 60,793 Car, 2,734 `car_passenger`, and 9,626 `school_bus` legs;
34 Taxi legs were not reached because some plans remained active or lost at
the 30-hour QSim horizon. Average executed score across the 11 iterations had
mean 61.5744800, minimum 61.0881266, maximum 61.8076029, and range 0.7194763.

The successful repeated callbacks provide live simultaneous coverage of the
Taxi fare component, PT fare component, and the composed Car energy, confirmed
toll, and resolved destination-parking components. Exact positive-charge
counts by Car subcomponent are not separately instrumented, so this is a
stability and coverage result rather than a calibration or charge-incidence
report. The candidate remains separate from the adopted 50-iteration
production output.

## Artifacts

Reproducible scripts:

```text
scripts/hong_kong_single_city/demand_generation/
  audit_hong_kong_household_car_passenger_candidates.py
  prepare_hong_kong_school_escort_physical_pilot.py
  prepare_hong_kong_no_ride_reallocation.py
  merge_hong_kong_no_ride_selective_routes.py
scripts/hong_kong_single_city/run/
  audit_hong_kong_school_escort_joint_reroute_pilot.py
  audit_hong_kong_school_escort_physical_pilot.py
  launch_hong_kong_school_escort_physical_pilot.py
  launch_hong_kong_stage11_direct_10it.py
```

Compact tracked audit:

```text
data/taxi/hongkong/processed/taxi_44000_no_ride_student_swap_v1/
  household_car_passenger_candidate_audit_v1/
    car_passenger_candidate_legs.csv
    car_passenger_candidate_people.csv
    household_candidate_validation.json
  school_escort_physical_pilot_v1/
    school_escort_physical_bindings.csv
    school_escort_physical_binding_validation.json
    school_escort_physical_pilot_1iteration_20260806_success.json
    school_escort_joint_reroute_1cycle_20260806_success.json
```

Large local derived artifacts:

```text
F:\Matsim\derived\hongkong\taxi_44000_no_ride_student_swap_v1\
```

Validated server selective plans:

```text
/mnt/DiskM/by/hk_stage11_taxi_44000_no_ride_v1/
  selective_route_merge_attempt6/
    plans_routed_selective_5pct_taxi_44000_no_ride.xml.gz
```

Validated Stage 11 run:

```text
/mnt/DiskM/by/hk_stage11_taxi_44000_no_ride_20260806_run14/
```

Validated one-iteration physical pilot:

```text
/mnt/DiskM/by/hk_stage11_school_escort_physical_20260806_run4/
```

Validated one-cycle JointReRoute pilot:

```text
/mnt/DiskM/by/hk_stage11_school_escort_joint_reroute_20260806_run4/
```

Failed route/run attempts are retained in their versioned server directories;
none was overwritten or deleted.
