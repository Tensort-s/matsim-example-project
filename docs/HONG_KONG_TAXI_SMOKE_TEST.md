# Hong Kong Taxi two-iteration technical smoke test v1

## Purpose and boundary

This gate runs the real Hong Kong Taxi base plans for exactly MATSim
iterations 0 and 1 with fixed `ASC=-9`. It verifies QSim and custom Taxi
scoring integration. It is not demand calibration, does not test alternative
ASCs, and must not use the unchanged count of 37,286 Taxi legs as evidence
that the ASC is behaviourally appropriate.

Taxi remains a passenger/teleported behavioural mode with
`mode=taxi` and `routingMode=ride`. It is not added to QSim main modes. No
Taxi contrib, DVRP fleet, request, dispatch, pickup, or drop-off model is
installed.

## Runner and fixed configuration

The independent entry point is:

```text
org.matsim.project.hongkong.taxi.RunHongKongTaxiBehavioralPilot
```

It accepts:

```text
<base-config> <taxi-plans> <output-directory>
<smoke-validation-json> <checkpoint-sha>
```

Only the in-memory config is changed. The runner sets:

```text
firstIteration = 0
lastIteration = 1
ASC = -9
taxi marginalUtilityOfTraveling = -6 util/hour
taxi marginalUtilityOfDistance = 0
taxi monetaryDistanceRate = 0
taxi dailyMonetaryConstant = 0
taxi dailyUtilityConstant = 0
```

It clears every replanning strategy and disables experienced-plan
memorization. Before the `Controler` is created it applies the same PT
startup contract as the adopted Hong Kong baseline:

```text
scan every person / every plan / every plan element
clear route only where mode=pt and route != null
install SwissRailRaptorModule
allow PrepareForSim / SwissRailRaptor to rebuild PT routes
```

The run identity records this operation explicitly:

```text
pt_startup_route_clear = true
pt_startup_route_rebuild = true
pt_startup_routing_scope = pt_only_before_iteration_0
routing_run = true
routing_scope = deterministic_pt_startup_rebuild_only
behavioral_replanning = false
strategy_settings_count = 0
mode_choice = false
taxi_routing = false
taxi_mode_conversion = false
asc_calibration = false
fleet_model = false
```

PT startup route preparation is not behavioural replanning. Persons,
selected main activities, Taxi legs, car/ride/other non-PT main legs, and
behavioural choices remain fixed. Only PT routes and the necessary PT stage
routing structure may be prepared before iteration 0. No strategy reroutes
PT between iterations.

Existing non-Taxi scoring modes, QSim main modes, road capacity factors, PT
inputs, facilities, and private vehicles are snapshotted and must remain
unchanged. The output policy is `failIfDirectoryExists`; iteration plans and
events are retained for both iterations.

## Runtime and output guards

`HongKongTaxiSmokeRuntimeGuard` reads the factory from the live Controler
services at startup. The exact required class is:

```text
org.matsim.project.hongkong.taxi.HongKongTaxiScoringFunctionFactory
```

It also verifies the installed central fare parameters, zero Taxi distance
terms, absence of Taxi from QSim main modes, empty replanning strategies, and
absence of MATSim Taxi/DVRP bindings.

Before QSim in iteration 0, the guard requires exactly 557,104 selected-plan
PT legs, all represented by schedule-backed `TransitPassengerRoute`
instances. Null routes, `GenericRouteImpl`, missing access/egress stops,
missing line/route IDs, and references absent from the loaded schedule are
fatal. The same audit is repeated before iteration 1; its complete PT route
fingerprint must equal iteration 0, proving that the one-shot startup rebuild
was not repeated or changed between iterations.

Before PT clearing, all 37,286 selected-plan Taxi legs receive a strict
fingerprint containing person ID, Taxi ordinal, main-trip index, mode,
routing mode, six typed Taxi attributes, and the complete Taxi route. The
fingerprint is checked immediately after clearing and before both QSim
iterations. Any missing, extra, duplicate, reordered, retyped, rerouted, or
otherwise changed Taxi leg stops the run before it can be accepted.

During each QSim iteration the guard independently pairs Taxi departures and
arrivals by person and trip order. It rejects any unmatched event, invalid
Taxi travel time, Taxi or whole-model stuck event, Taxi network-vehicle
traffic event, Taxi/DVRP request/pickup/drop-off/fleet event, or Taxi-fare
`PersonMoneyEvent`. A violation throws at the end of the current iteration
and prevents continuation.

After `Controler.run()`, `HongKongTaxiSmokeOutputAudit` reads iteration 0,
iteration 1, and final output plans. It permits the verified PT route/stage
preparation but requires identical persons, selected main activities, all
non-PT main legs, strict Taxi fingerprints, Taxi type/classification counts,
fare sum, main-trip-index sum, and `routingMode=ride`. Iteration 0 and 1
outputs must be identical to one another. Every selected-plan score,
including every Taxi person score, must be finite. The runtime log must
contain zero `pt-leg has no TransitRoute`, unknown transit-stop, fare schedule
mismatch, and Taxi attribute-validation errors.

## Earlier failure and current validation status

The first remote `ASC=-9` two-iteration attempt stopped during iteration 0.
The custom fare scorer received an experienced Taxi leg without
`hkTaxiFareBaselineHkd`. This was a scoring data-interface defect:
MATSim 2026.0 `EventsToLegs` reconstructs experienced legs from events and
does not copy source-plan custom attributes.

That scoring interface was corrected first: at scoring-function creation,
each person's selected-plan Taxi metadata is validated and copied into an
immutable ordered fare schedule; attribute-free experienced Taxi legs consume
it by zero-based Taxi ordinal.

The next failed attempt exposed a separate startup mismatch. All 557,104 PT
legs in both the original and Taxi plans deserialize as non-null
`GenericRouteImpl`. The adopted baseline never sent those objects directly to
QSim: `RunHongKong5Pct --simulate --clear-pt-routes` cleared them and installed
SwissRailRaptor. The Taxi smoke installed SwissRailRaptor but omitted the
clear, so the existing generic routes blocked rebuilding. It observed only
30,230 of 37,286 Taxi departures; 7,024 of the 7,056 missing Taxi departures
followed a preceding invalid-PT agent removal.

The current checkpoint aligns only this PT startup preparation. `ASC=-9`
remains a technical-smoke placeholder, not a calibration result. Taxi fare,
time, distance, and ASC terms; PT/car costs; QSim capacity factors; input
plans and supply files remain unchanged.

The checkpoint implementation must pass local compile, the applicable Taxi
tests, and `git diff --check`, then be pushed before a new server run. The
server must use a new directory below:

```text
/mnt/DiskM/by/hk_taxi_behavioral_pilot_v1/
```

The formal scenario and the validated load-test directory remain read-only.
All seven input SHA256 values must match
`taxi_scenario_load_validation.json` before the Controler starts.

At the code-checkpoint stage the PT-prepared smoke has not yet been rerun.
The next formal action is exactly one fresh, detached-checkpoint,
two-iteration run on FUSELAB01. Failure is fail-closed and must not trigger an
automatic rerun; compact validation outputs are committed only if every
startup, PT, Taxi, event, score, input-integrity, and runtime-log check passes.
