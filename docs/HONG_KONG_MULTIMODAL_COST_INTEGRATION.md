# Hong Kong multimodal-cost integration

## Authority and current status

This document records the staged integration of the Hong Kong Taxi, public
transport, and private-car cost work. The lane registry and gate protocol are
in [`agent-lanes.md`](../agent-lanes.md); append-only decisions and evidence
handoffs are under [`docs/agent-worklogs/`](agent-worklogs/).

Stage 0 passed independent exact-SHA review at:

```text
476f25254a99e4b9c47d5b439a6e7b658a412f80
```

Stage 1 explicitly merges the locked Taxi source:

```text
integration first parent:
  476f25254a99e4b9c47d5b439a6e7b658a412f80
Taxi second parent:
  aa0d4794fa3af8458c906db1614fd418893e4bd4
```

The Stage 1 result remains pending independent exact-SHA review and Supervisor
gating. The locked PT and Car sources are not part of Stage 1:

```text
PT:
  0b0ce90375b9e3d0c055fa46c5a3b96bfc3a5103
Car:
  fc906efd3afb98e027cc6cca44060dec9e32aa46
```

## Stage 1 scope

Stage 1 imports the Taxi population metadata conversion, native passenger
routing, standard PrepareForSim lifecycle, Guice modules, route-based fare
scoring, deterministic audits, compact historical evidence, tests, scripts,
and Taxi documentation through a real non-fast-forward Git merge.

Stage 1 does not:

- merge or cherry-pick PT or Car;
- add PT or Car scoring;
- run MATSim locally or remotely;
- rerun the historical standalone Taxi smoke;
- calibrate Taxi ASC or mode share;
- change demand, capacity, monetary utility, or fare policy;
- add an explicit Taxi fleet, driver, dispatch, pickup, DVRP, or vehicle
  scheduling model.

`cities/hongkong/city.yaml` and `runs/hongkong/run_manifest.json` remain
unchanged because Stage 1 does not adopt a new production input, config,
output, or final run.

## Canonical Taxi runtime contract

### Native passenger mode

Taxi has an independent external identity:

```text
mode=taxi
routingMode=taxi
```

`HongKongTaxiRoutingModule` binds mode `taxi` to
`HongKongTaxiRouting`. The implementation delegates only the passenger
distance and travel-time calculation to MATSim's teleported `ride` routing,
then returns a Taxi leg with both identities set to `taxi`. Taxi is absent
from QSim main modes and network routing modes. Conversion or fallback to a
`ride` leg is a hard failure.

### Standard PrepareForSim

The production path uses MATSim 2026.0's bound
`org.matsim.core.controler.PrepareForSimImpl`. Source PT generic routes are
cleared as required by the adopted Hong Kong startup contract; the Controler
installs SwissRailRaptor and the Taxi routing module; standard PrepareForSim
prepares complete plans. The historical custom one-shot PT rebuild is not the
production path and its legacy guards do not control this canonical contract.

The Taxi lifecycle test verifies:

```text
standard PrepareForSim updates the selected-plan Taxi route
-> the scoring factory is requested
-> the ordinal fare schedule reads the prepared route
-> the route-fare calculator charges the current distance
```

### Guice and scoring skeleton

`RunHongKongTaxiBehavioralPilot` installs
`HongKongTaxiRoutingModule` and `HongKongTaxiScoringModule`. The scoring module
binds the canonical `HongKongTaxiScoringFunctionFactory`, which wraps the
standard MATSim scoring delegate and adds one Taxi fare contribution.

At scoring-function creation, the factory reads each selected-plan Taxi leg's
current prepared route, calculates the distance fare, and builds an immutable
ordinal `HongKongTaxiPersonFareSchedule`. Event-reconstructed experienced Taxi
legs consume that schedule in order. Extra or unconsumed entries fail.

The custom fare contribution is:

```text
-0.05 util/HKD * calculated route fare HKD
```

The historical `hkTaxiFareBaselineHkd` field is comparison-only and is not a
runtime charge source. Taxi monetary distance rate and marginal utility of
distance are zero. The custom scorer emits no Taxi fare `PersonMoneyEvent`;
money and arbitrary event handling is forwarded only to the standard
delegate. These boundaries prevent a second Taxi fare path.

Fare calculation rejects negative or non-finite route distance. Tests require
finite fares and scores and exact parity with the versioned fare rules.
`unresolved` Taxi classification retains its label and uses the explicit Urban
Taxi fallback; it is not filled with zero.

## Historical evidence boundary

The accepted full-scenario preparation evidence remains historical:

```text
Taxi legs before/after PrepareForSim: 37,286 / 37,286
mode=taxi,routingMode=taxi:           37,286
Taxi converted to ride:                    0
route-fare calculation failures:           0
```

The retained historical two-iteration attempt did not complete:

```text
planned Taxi legs:       37,286
departures:              35,088
arrivals:                35,087
Taxi stuck:                   1
upstream-blocked legs:    2,198
```

The 2,198 non-departures were primarily associated with preceding PT or walk
execution becoming stuck. This is not a completed two-iteration result and not
a calibration result. `ASC=-9` remains a technical placeholder only.

## Stage 1 verification boundary

Stage 1 verification is local and deterministic. It compiles the canonical
Maven project and runs the existing test suite, including the Taxi routing,
PrepareForSim lifecycle, Guice/scoring, fare parity, duplicate-charge, finite
value, configuration-guard, smoke-contract, and Python native-routing tests.
It performs no QSim, Controler run, or server run.

Verification results:

| Check | Result |
|---|---|
| `.\mvnw.cmd -DskipTests compile` | `BUILD SUCCESS`; exit 0; 12.286 s |
| `.\mvnw.cmd test` | `BUILD SUCCESS`; 61 tests; 0 failures/errors/skips; 77 s |
| Taxi Java tests within the Maven suite | 60 tests across 10 Taxi test classes |
| Existing generic Maven regression | 1 test |
| Python native-routing test | 2 tests; `OK`; exit 0 |
| Four imported Python command interfaces | all `--help` exit 0 |
| Imported structured JSON | 9 files parsed; 0 failures |

`RunMatsimWithoutApplicationTest` is the existing small generic repository
regression included by the mandatory full Maven suite. No Hong Kong scenario,
standalone Taxi smoke, remote run, or formal simulation was launched.

The local deterministic tests protect:

- Taxi `mode=taxi,routingMode=taxi` after direct and whole-plan routing;
- Taxi absence from QSim main/network modes and absence of a fleet/DVRP
  configuration;
- the bound standard `PrepareForSimImpl` and the route-before-fare lifecycle;
- complete ordinal fare consumption and failures for extra or missing
  experienced Taxi legs;
- route-change sensitivity and immutable schedule snapshots;
- no duplicate fare from money/event/trip interfaces or Taxi distance terms;
- finite scoring inputs and rejection of non-finite or negative route values;
- Guice factory creation, isolation, selected-plan scope, and standard scoring
  call forwarding.

The compact Stage 1 validation record is:

```text
data/taxi/hongkong/processed/taxi_integration_stage1_validation_v1/
  stage1_taxi_merge_validation.json
```

Exact post-commit ancestry, pushed SHA, protected refs, and local/tracking/
remote equality are recorded in the Stage 1 `INT-EXECUTOR` handoff because a
commit cannot contain its own SHA.

Non-blocking diagnostics include Maven's deprecated `${parent.version}`
expression, deprecated MATSim scoring APIs, Java 25 native-access/Unsafe
warnings, Guice line-number inspection using an ASM version that does not
understand class-file major version 69, and synthetic-fixture configuration
warnings. Guice injection and all tests still pass; none of these diagnostics
changes the Taxi runtime contract.
