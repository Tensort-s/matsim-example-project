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
configuration contains no `ride` mode parameter. `SubtourModeChoice` offers
only `car,pt,walk`, because standard MATSim availability rules cannot enforce
the household and student restrictions of the two passenger modes.

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
  prepare_hong_kong_no_ride_reallocation.py
  merge_hong_kong_no_ride_selective_routes.py
scripts/hong_kong_single_city/run/
  launch_hong_kong_stage11_direct_10it.py
```

Compact tracked audit:

```text
data/taxi/hongkong/processed/taxi_44000_no_ride_student_swap_v1/
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

Failed route/run attempts are retained in their versioned server directories;
none was overwritten or deleted.
