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

It clears every replanning strategy, disables experienced-plan
memorization, and records:

```text
replanning_enabled = false
mode_choice_enabled = false
routing_enabled = false
```

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

During each QSim iteration the guard independently pairs Taxi departures and
arrivals by person and trip order. It rejects any unmatched event, invalid
Taxi travel time, Taxi or whole-model stuck event, Taxi network-vehicle
traffic event, Taxi/DVRP request/pickup/drop-off/fleet event, or Taxi-fare
`PersonMoneyEvent`. A violation throws at the end of the current iteration
and prevents continuation.

After `Controler.run()`, `HongKongTaxiSmokeOutputAudit` reads iteration 0,
iteration 1, and final output plans. It requires unchanged population
structure, mode counts, departure/route fingerprint, Taxi metadata
fingerprint, Taxi type and classification counts, fare sum, main-trip-index
sum, and `routingMode=ride`. Every selected-plan score, including every Taxi
person score, must be finite. Events and plans output sizes and SHA256 values
are recorded, but the large files remain only on the server.

## Validation status

The checkpoint implementation must pass local compile, the exact Taxi unit
tests, and `git diff --check`, then be pushed before the server run. The
server must use a new directory below:

```text
/mnt/DiskM/by/hk_taxi_behavioral_pilot_v1/
```

The formal scenario and the validated load-test directory remain read-only.
All seven input SHA256 values must match
`taxi_scenario_load_validation.json` before the Controler starts.

Until the server result is recorded here, this smoke gate is implemented but
not validated.
