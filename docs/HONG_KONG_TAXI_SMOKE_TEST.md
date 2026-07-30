# Hong Kong Taxi two-iteration technical smoke test v1

> The two-iteration material below is a historical smoke design and attempt
> record. Its `routingMode=ride`, custom startup rebuild, and
> `taxi_routing=false` statements are superseded by the standard
> PrepareForSim checkpoint recorded next. No two-iteration QSim was run during
> the PrepareForSim restoration stage.

## Standard PrepareForSim checkpoint (2026-07-30)

The formal Taxi runner no longer calls
`HongKongTaxiPtRoutePreparation.rebuildPtTripsAtStartup(...)`. Its current
startup sequence is:

```text
load native Taxi plans
clear the 557,104 source PT Generic routes
create Controler
install SwissRailRaptorModule
install HongKongTaxiRoutingModule
install route-based HongKongTaxiScoringModule
run MATSim's bound PrepareForSimImpl
```

`HongKongTaxiSmokeRuntimeGuard` now verifies that the bound implementation is
`org.matsim.core.controler.PrepareForSimImpl` and that the process-local
custom-rebuild invocation counter remains zero. It accepts route changes made
by default preparation while continuing to require exact Taxi count,
identity, ordinal, attributes, mode, routing mode, and selected-plan sequence.
The iteration-0 prepared Taxi snapshot becomes the exact invariant for any
later iteration.

The dedicated full-scenario validator is:

```text
org.matsim.project.hongkong.taxi.ValidateHongKongTaxiPrepareForSim
```

It calls the Controler injector's bound `PrepareForSim` service directly. It
does not call `Controler.run()`, a Mobsim, or QSim. Its Controler output path is
an attempt-local fresh directory so loading a production config cannot touch
or overwrite a historical run.

Formal server result:

```text
checkpoint:
  27b7acf2f12fff56ea00971c3a84336dfe45f271
server directory:
  /mnt/DiskM/by/hk_taxi_behavioral_pilot_v1/
    prepare_for_sim_27b7acf_attempt5
validation:
  data/taxi/hongkong/processed/taxi_prepare_for_sim_validation_v1/
    taxi_prepare_for_sim_validation.json
status = validated
all_checks_passed = true
process_exit_code = 0
```

The seven base-config, native-plans, network, schedule, transit-vehicle,
facility, and private-vehicle SHA256 gates passed before and after execution.
The detached checkpoint worktree was clean. Java was Temurin 25.0.3, Maven
3.9.8, MATSim 2026.0, and the shaded JAR SHA256 was
`0f2b1e10cf2bdb36e989fe79c96d0456afed6794b07fc863fda1e9b435ccde9c`.

Default `PrepareForSimImpl` used the configured 8 threads. Its measured call
time was 1,065.5668 s; total external Java wall time, including scenario load
and audits, was 18:31.54. Peak RSS was 8,793,352 KiB. The custom rebuild
counter was `0 -> 0`.

PT preparation produced:

| Measure | Count |
|---|---:|
| Source PT main legs | 557,104 |
| Source Generic routes cleared | 557,104 |
| Prepared PT segments | 1,092,811 |
| Legal `DefaultTransitPassengerRoute` | 1,092,811 |
| Null / Generic routes | 0 / 0 |
| Missing or invalid stop/line/route references | 0 |

The prepared segment count is diagnostic, not a source-leg invariant. Standard
whole-plan routing can expand one source PT main leg into access, transit,
transfer, and egress segments.

Taxi preparation produced:

| Measure | Result |
|---|---:|
| Taxi before / after | 37,286 / 37,286 |
| `mode=taxi`, `routingMode=taxi` | 37,286 |
| Taxi converted to ride | 0 |
| Null / invalid Taxi routes | 0 / 0 |
| Taxi route changes | 7,696 |
| Route-fare calculation failures | 0 |
| Calculated route fares | 37,286 |
| Fare sum / mean / median (HKD) | 4,096,449.1 / 109.8656091 / 98.3 |
| Unresolved Urban fallbacks | 2,533 |

The scoring lifecycle audit built a real
`HongKongTaxiScoringFunctionFactory` schedule after default preparation and
confirmed that its fare equals the calculator result for the prepared selected
plan route. The historical `hkTaxiFareBaselineHkd` remained comparison-only.
Capacity, QSim main modes, non-Taxi scoring, Taxi passenger-only boundaries,
and all seven formal inputs remained unchanged.

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
at Controler startup, use the live SwissRailRaptor-backed TripRouter
rebuild only complete trips whose routingMode=pt
allow the later default PrepareForSim scan to verify the prepared plans
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
behavioural choices remain fixed. Only complete `routingMode=pt` trips are
passed to the live PT router, using MATSim `TripStructureUtils` trip/stage
boundaries rather than fixed plan-element indexes. This is necessary because
MATSim 2026.0 `PersonPrepareForSim` otherwise reroutes an entire plan whenever
any leg route is null; that whole-plan path would replace a Taxi trip carrying
`routingMode=ride` with a ride trip. Once the PT-only startup pass has supplied
all PT routes, the default prepare-for-sim scan has no reason to reroute the
plan. No strategy reroutes PT between iterations.

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

The source/clear audit continues to require exactly 557,104 source PT legs and
557,104 cleared `GenericRouteImpl` routes. The prepared raw PT-segment count is
an observed output, not a source-count invariant: one source main PT leg can
expand into multiple access, transit, transfer, and egress elements. Before
QSim in iteration 0, every actual `mode=pt` segment must have a non-null,
non-`GenericRouteImpl`, schedule-backed `TransitPassengerRoute`. Missing
access/egress stops, line/route IDs, or schedule references are fatal. The
same audit is repeated before iteration 1; its raw segment count and complete
PT route fingerprint must equal iteration 0, proving that the one-shot startup
rebuild was not repeated or changed between iterations.

Before PT clearing, all 37,286 selected-plan Taxi legs receive a strict
fingerprint containing person ID, Taxi ordinal, main-trip index, mode,
routing mode, six typed Taxi attributes, and the complete Taxi route. The
fingerprint is checked immediately after clearing and before both QSim
iterations. Any missing, extra, duplicate, reordered, retyped, rerouted, or
otherwise changed Taxi leg stops the run before it can be accepted.

During each QSim iteration the guard independently pairs Taxi departures and
arrivals by person and trip order. Incomplete or unmatched Taxi events,
invalid Taxi travel time, stuck events, Taxi network-vehicle traffic events,
Taxi/DVRP request/pickup/drop-off/fleet events, and Taxi-fare
`PersonMoneyEvent` are recorded in that iteration's audit. They do not throw
at the end of iteration 0, so iteration 1 can provide a complete diagnostic;
the unified validation after both iterations still fails unless all mandatory
Taxi conditions pass. Non-Taxi stuck events are observations and fail this
Taxi gate only when they prevent Taxi execution or make the two-iteration
scenario incomplete or uninterpretable.

Startup configuration/scoring failures, malformed Taxi attributes, invalid
prepared PT references, and any pre-QSim Taxi fingerprint change remain
immediate hard stops. BeforeMobsim stores both the PT and Taxi audit before
applying those hard checks. If a hard check prevents creation of the live
iteration event audit, AfterMobsim records that fact without throwing a
secondary `Missing live event audit` exception, so the first causal error is
retained in the runner validation.

After `Controler.run()`, `HongKongTaxiSmokeOutputAudit` reads iteration 0,
iteration 1, and final output plans. It permits the verified PT route/stage
preparation but requires identical persons, selected main activities, all
non-PT main legs, strict Taxi fingerprints, Taxi type/classification counts,
fare sum, main-trip-index sum, and `routingMode=ride`. Iteration 0 and 1
outputs must be identical to one another. Every selected-plan score,
including every Taxi person score, must be finite. The runtime log must
contain zero `pt-leg has no TransitRoute`, unknown transit-stop, fare schedule
mismatch, Taxi attribute-validation, unknown-mode, and Taxi route-execution
errors.

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

The next PT-prepared attempt reached iteration 0 BeforeMobsim and established
the actual prepared structure before stopping:

```text
source PT legs / cleared routes:          557,104 / 557,104
prepared raw PT segments:                         1,092,811
prepared default TransitPassengerRoute:           1,092,811
null / Generic / missing or invalid references:           0
```

The old guard compared both prepared counts to 557,104, so it rejected a
fully legal expanded PT structure. The same attempt also exposed why a
PT-only startup pass is required: default whole-plan routing preserved only
29,590 of 37,286 Taxi legs, while 7,696 Taxi identities in plans that also
needed PT preparation were replaced by `ride` legs and lost their Taxi
attributes. The revised checkpoint keeps the 557,104 equality only for the
source/clear audit, routes only `routingMode=pt` trips at startup, and retains
the strict 37,286-leg Taxi fingerprint as a hard pre-QSim gate.

The checkpoint implementation must pass local compile, the applicable Taxi
tests, and `git diff --check`, then be pushed before a new server run. The
server must use a new directory below:

```text
/mnt/DiskM/by/hk_taxi_behavioral_pilot_v1/
```

The formal scenario and the validated load-test directory remain read-only.
All seven input SHA256 values must match
`taxi_scenario_load_validation.json` before the Controler starts.

At this revised code-checkpoint stage the PT-only startup implementation has
passed `mvn -DskipTests compile`,
`HongKongTaxiPtRoutePreparationTest`,
`HongKongTaxiSmokeIntegrationTest`, and the added direct regression checks.
It has not yet been exercised in a fresh formal two-iteration run. The next
formal action is a detached-checkpoint run in a new append-only directory on
FUSELAB01. Up to three new Controler attempts are permitted for non-model
implementation defects; every attempt retains its own output. Compact
validation outputs are committed only if every startup, PT, Taxi, event,
score, input-integrity, and runtime-log check passes.
