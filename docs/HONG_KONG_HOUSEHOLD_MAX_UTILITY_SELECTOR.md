# Hong Kong household maximum-utility selector pilot

## Scope and status

This document records the Stage 11 household-selector technical pilot created
on 2026-08-06. It is not the adopted 50-iteration Hong Kong production run.
It operates only on the 139 already audited, complete school-escort pairs and
does not search for or create a new passenger-driver pairing.

For each of those households the current real-mode successor constructs exactly
two household alternatives:

- **unbound:** retain the original driver Car routes, route each released
  passenger trip independently by physical PT and Taxi, and use the
  higher-utility available mode for that trip;
- **bound:** replace the two referenced driver Car routes with routes that
  explicitly pass the passenger origin-link pickup and destination-link
  drop-off waypoints, and execute the passenger legs in those private-car
  QVehicles.

The binding input therefore records both `passenger_pickup_link` and
`passenger_dropoff_link` for all 278 candidate legs. A bound passenger may
board only when the assigned vehicle is on the pickup link during the exact
referenced driver leg, and may alight only when that vehicle enters the
drop-off link. Passing the same link during another driver trip is ignored.

## Deterministic comparison

The selector runs once at controller startup, before iteration 0. It uses no
choice probability and no driver participation or acceptance constraint. It
chooses the bound household bundle when its utility is at least the unbound
bundle utility and the two waypoint routes satisfy the driver's hard schedule
feasibility condition. A route that reaches the next driver Car departure too
late is physically infeasible and remains unbound even if its unconstrained
utility difference is positive.

The household utility is the sum over both outbound and return passenger and
driver legs. In the bound alternative, the passenger contribution is
deliberately limited to the authorized base willingness and travel-time cost:

```text
S_car_passenger_leg = -1.5 - 6 * travel_time_hours
```

It has no distance term and no monetary-distance term. In the bound candidate,
passenger travel time includes waiting from the passenger's planned departure
until the vehicle reaches pickup, followed by in-vehicle time to the real
drop-off waypoint.

The successor no longer scores or executes the unbound alternative as
teleported `car_passenger`. For every released trip it constructs a direct
SwissRailRaptor physical PT itinerary and a routed Taxi itinerary, evaluates
both with the same standard mode/time/distance coefficients and fare rules
used by simulation, and installs the higher-utility available itinerary. A PT
candidate is unavailable if Raptor cannot return a physical
`TransitPassengerRoute`; Taxi is then the fallback. PT fare segments use the
runtime fare catalog, while Taxi uses the route-distance fare calculator and
the existing Taxi scoring rule. PT wins an exact utility tie.

Passenger Car is deliberately absent from the released-mode choice. The
driver retains the household Car in this pilot, and no second physical vehicle
is assigned. A future passenger Car candidate must first prove that the driver
has released the vehicle or that an additional household vehicle is explicitly
unused.

The driver contribution is evaluated using the current dynamic Car rules:

```text
S_car_leg = -0.5 - 6 * travel_time_hours
            - energy_hkd - toll_hkd - parking_hkd
```

Candidate routing and experienced scoring share the same link energy and toll
rules. Parking is associated with the actual downstream main-activity
facility and the interval until the vehicle's next Car departure (or the QSim
end for terminal parking).

## Innovation policy

The pilot runs exactly one QSim, iteration 0. Ordinary `ReRoute`,
`SubtourModeChoice`, and `TimeAllocationMutator` strategy weights are zero.
The selector itself is the sole pre-simulation plan choice. It keeps the
existing candidate identities fixed and cannot generate a previously absent
joint trip.

## Reproducible components

```text
scripts/hong_kong_single_city/demand_generation/
  prepare_hong_kong_school_escort_physical_pilot.py
scripts/hong_kong_single_city/run/
  launch_hong_kong_school_escort_physical_pilot.py
  audit_hong_kong_household_max_utility_pilot.py
  audit_hong_kong_household_real_mode_pilot.py
src/main/java/org/matsim/project/hongkong/household/
  HouseholdEscortBindingCatalog.java
  HouseholdEscortMaxUtilitySelector.java
  HouseholdEscortMaxUtilitySelectorModule.java
  HouseholdEscortPhysicalEngine.java
```

## Validated iteration-0 result

The immutable successful run is:

```text
release: /mnt/DiskM/by/hk_stage11_household_max_utility_20260806_release3
run:     /mnt/DiskM/by/hk_stage11_household_max_utility_20260806_run3
QSim:    iteration 0 only; exit code 0
audit:   household_max_utility_1iteration_audit.json
```

The selector generated all 278 waypoint legs and selected 64 households as
bound and 75 as unbound. The latter include 33 whose bound bundle failed the
hard schedule-feasibility condition. The 64 active households produced 128
physical passenger legs: all 128 boarded the assigned QVehicle at the pickup
link, 127 reached and alighted at the drop-off link, and one passenger became
stuck while onboard. Every active binding was classified, with no waiting or
onboard state left after QSim.

The independent event audit passed every check. Each of the 127 completed
legs has an exact same-time vehicle-link event at both pickup and drop-off;
there are zero waypoint failures, zero bound teleportation arrivals, and zero
person-vehicle events among the unbound candidates. All 278 candidate
passenger legs were observed. Output mode counts were conserved, all selected
scores were finite, and the dynamic Car audit recorded live energy, toll, and
parking callbacks with zero parking-facility mismatch.

The compact tracked audit is:

```text
data/taxi/hongkong/processed/taxi_44000_no_ride_student_swap_v1/
  school_escort_physical_pilot_v1/
    household_max_utility_waypoint_1iteration_20260806_success.json
```

Failed server attempts remain in their numbered directories and were not
overwritten or deleted.

## Validated real-mode successor

The successor run is:

```text
release: /mnt/DiskM/by/hk_stage11_household_real_mode_20260806_release10
run:     /mnt/DiskM/by/hk_stage11_household_real_mode_20260806_run10
QSim:    iteration 0 only; exit code 0
audit:   household_real_mode_1iteration_audit_v2.json
```

The selector again evaluated the same 139 audited households and generated no
new pair. It selected 104 households as bound and 35 as unbound. The 70
released passenger trips became 24 physical PT trips and 46 routed Taxi trips;
no released trip contains a Car leg. Twenty-nine PT candidates had no usable
physical Raptor itinerary across the full 278-leg candidate set; Taxi is the
fallback when such a leg belongs to a selected unbound household. Output
counts are 67,718
Car, 2,664 `car_passenger`, 557,375 PT, 9,626 `school_bus`, 44,046 Taxi, and
199,863 walk legs. The Car count is unchanged.

Of the 208 active bound legs, 202 completed with exact pickup and drop-off
vehicle-link events, three passengers became stuck while onboard, one driver
became stuck before pickup, and two passengers were still waiting for their
driver at the configured 30:00 QSim horizon. The latter are explicitly
classified as `simulation_end_before_pickup`, not treated as successful rides
or internal errors. No completed binding missed a waypoint and no bound leg
teleported.

The independent audit passed every check: all 70 released trips carried their
provenance tags; all 24 PT trips contained MATSim `default_pt` physical transit
routes; all 46 Taxi trips contained a routed Taxi leg and the six fare
attributes; released Car remained zero; ordinary innovation remained frozen;
dynamic energy, toll, and parking callbacks were live; and all selected scores
were finite. The tracked compact report is:

```text
data/taxi/hongkong/processed/taxi_44000_no_ride_student_swap_v1/
  school_escort_physical_pilot_v1/
    household_real_mode_waypoint_1iteration_20260806_success.json
```

This remains a one-iteration mechanism test. The 2,456 `car_passenger` legs
outside the 139 audited candidate households remain teleported, and the pilot
does not yet generate new joint trips, add choice probabilities, impose driver
acceptance, or open general replanning.

## Endogenous single-leg candidate successor

The 2026-08-07 successor expands the bounded candidate registry without
creating a new driver tour. It screens the existing 2,734 `car_passenger` legs
against real Car legs made by a different member of the same household. The
adopted registry contains 384 eligible passenger legs belonging to 244 people
in 240 households: the 278 legacy school-escort legs are preserved and 106
additional direct/detour-screened legs are added. Every referenced driver,
private vehicle, driver leg, pickup link, and drop-off link is resolved in the
canonical input plans.

The decision unit is one passenger leg, not a person's round trip. Each of the
384 candidate groups therefore contains exactly one leg and two alternatives:
physical binding to its referenced driver route, or release to the better of
physical PT and routed Taxi. Outbound and return legs are compared separately,
so a person may use `car_passenger` in one direction and PT or Taxi in the
other. A persistent binding key is stored on each selected passenger leg; this
keeps the other bound leg identifiable even when a released PT trip expands
into multiple plan elements and changes runtime leg ordinals.

Within each household, the selector maximizes the sum of leg-level utility
gains subject to exclusive use of each `(vehicle, driver, driver leg)`
resource. Four driver-leg resources have competing passenger candidates in
the registry. The exact subset selector prevents one physical vehicle leg
from being assigned twice. There is still no choice probability or driver
acceptance constraint, and passenger Car remains unavailable after release.
The successor can activate a previously absent joint leg only when the driver
already has a compatible Car leg; it cannot synthesize a driver trip, allocate
an unused second car, or search general equilibrium.

Reproducible additions are:

```text
scripts/hong_kong_single_city/demand_generation/
  prepare_hong_kong_household_joint_candidate_registry.py
scripts/hong_kong_single_city/run/
  audit_hong_kong_endogenous_household_joint_pilot.py
data/taxi/hongkong/processed/taxi_44000_no_ride_student_swap_v1/
  household_joint_candidate_registry_v2/
    household_joint_candidate_bindings.csv
    household_joint_candidate_registry_validation.json
```

`household_joint_candidate_registry_v1` is retained only as a historical
intermediate: it grouped a passenger's outbound and return legs into one
bundle. It was superseded before simulation by v2, which uses one candidate
group per leg and therefore permits different outbound/return decisions. No
validated endogenous run reads v1.

### Validated endogenous result

The immutable one-iteration validation is:

```text
release: /mnt/DiskM/by/hk_stage11_endogenous_household_joint_20260807_release2
run:     /mnt/DiskM/by/hk_stage11_endogenous_household_joint_20260807_run2
QSim:    iteration 0 only; exit code 0
audit:   endogenous_household_joint_1iteration_audit_attempt3.json
```

The selector chose 288 bound legs and 96 released legs. The latter became 50
physical PT trips and 46 routed Taxi trips; no released trip used Car. Among
the 106 newly screened candidates, 51 were activated as new physical joint
legs and 55 were released. Forty-two people independently chose different
states for their outbound and return legs, directly validating mixed
one-direction `car_passenger` plans. The exact household subset selector left
no duplicated driver-leg/vehicle resource.

All 288 active bound departures were observed and classified. Of these, 279
completed with exact same-time vehicle events at both pickup and drop-off,
four passengers became stuck onboard, three drivers became stuck before
pickup, and two passengers remained unpicked at the 30:00 horizon. No bound
leg teleported and no waiting or onboard state remained in the engine. Output
counts were 67,718 Car, 2,638 `car_passenger`, 557,400 PT, 9,626
`school_bus`, 44,046 Taxi, and 199,914 walk legs. Dynamic Car energy, toll,
and parking callbacks were live, all selected scores were finite, and ordinary
route/mode/time innovation remained frozen.
