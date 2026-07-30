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

Stage 1 passed independent exact-SHA review at:

```text
d54fdd775064ace1c9f2aa2b6cb96db0e9474975
```

Stage 2 explicitly merges the locked offline PT fare source:

```text
integration first parent:
  d54fdd775064ace1c9f2aa2b6cb96db0e9474975
PT second parent:
  0b0ce90375b9e3d0c055fa46c5a3b96bfc3a5103
```

Stage 2 remains pending independent exact-SHA review and Supervisor gating.
The locked Car source is not part of Stage 2:

```text
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
- launch a Hong Kong MATSim scenario locally or remotely;
- rerun the historical standalone Taxi smoke;
- calibrate Taxi ASC or mode share;
- change demand, capacity, monetary utility, or fare policy;
- add an explicit Taxi fleet, driver, dispatch, pickup, DVRP, or vehicle
  scheduling model.

`cities/hongkong/city.yaml` and `runs/hongkong/run_manifest.json` remain
unchanged because Stage 1 does not adopt a new production input, config,
output, or final run.

## Stage 2 scope

Stage 2 imports the canonical PT fare manifest, five-row interface registry,
mode-specific rule and audit layers, query interfaces, release evidence,
scripts, and PT fare documentation through a real non-fast-forward Git merge.
It remains an offline source/query/release layer:

```text
release_status =
  offline_interfaces_validated_not_integrated_with_scoring
matsim_scoring_approved = false
```

No PT fare is connected to Java scoring, a money event, a runner, a MATSim
config, a plan rewrite, or a supply mutation. The production population's
557,104 generic PT legs still lack the actual mode, line, route, direction,
boarding/alighting stops, and transfer chain needed for a fare quote:

```text
total generic PT legs: 557,104
priced:                       0
unresolved:             557,104
cost_hkd:                  null
```

Unresolved is not zero. Distance medians, nearest-neighbour values,
cross-mode aggregation, reverse-direction substitution, path summation, and
route `fullFare` substitution remain prohibited for these generic legs.
Transfer concessions remain unmodelled.

`cities/hongkong/city.yaml` and `runs/hongkong/run_manifest.json` remain
unchanged because Stage 2 adopts no runtime input, configuration, output, or
run. No MATSim scenario or server task is authorized.

## Canonical offline PT fare contract

The registry contains exactly one row for each of the five distinct mode
interfaces:

| Mode | Canonical semantics and release count |
|---|---|
| MTR | Explicit ordered station OD; adult Octopus; domestic and Airport Express scopes remain separate. Domestic available: 9,216; Airport Express available/unresolved: 14/6. |
| Light Rail | Explicit ordered station OD; adult Octopus base fare before unmodelled concessions; available: 4,624. |
| GMB | Published amount with passenger/payment basis unspecified; required/available/unresolved: 97,521/96,866/655, including 361 conflicts and 294 identical duplicates. |
| Ferry | Published amount with passenger/payment/class/vessel/day/effective-period applicability unspecified; required/available: 60/60. |
| Bus | Bus Core strict rules: 754,133 and coverage 0.9772790300466783; separate simulation candidates: 771,666 with B/C/D counts 764,969/4,074/2,623. |

The bus simulation layer retains 18,170 assumption ODs and 20,533 anomaly
rows including route fallbacks. It is a coverage-first candidate layer, never
overwrites Bus Core, and is not described as universally official
adult-Octopus fare evidence. The top-level normalized catalog remains a
historical normalization/cross-check, not a global quote interface.

### Release-hash integration correction

The locked PT source's five validation-JSON registry hashes were calculated
from pre-commit Windows CRLF bytes, while its Parquet and Python hashes used
canonical source bytes. Git subsequently normalized the JSON to LF, so a
fresh checkout could not satisfy all 16 registered hashes even though the
fare data and semantics were unchanged.

Stage 2 corrects only those five expected/actual JSON hashes to the exact
canonical Git bytes already present in the locked PT commit, updates the
corresponding top-level checksum entries, and adds a read-only cross-platform
release validator:

```text
scripts/hong_kong_single_city/costs/
  validate_hong_kong_pt_fare_release_v1.py
```

The validator requires registered worktree paths to be clean against the Git
index and hashes the canonical index bytes. It independently rereads all
Parquet/CSV/JSON evidence, compiles the 23 locked PT scripts, checks the eight
protected inputs, verifies withdrawn-output absence, and reproduces the
20-check release contract. It does not rebuild or mutate a fare layer.

The older sequential mode validators remain useful historical validators, but
some byte-identical/prior-mode guards hash raw checkout line endings and can
therefore report false failures after another validator rewrites generated
text on Windows. Those historical guards do not control the canonical Stage 2
release; the new validator supplies the equivalent cross-platform integrity
protection without changing fare semantics.

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

Stage 1 verification was local and deterministic. It compiled the canonical
Maven project and ran the existing test suite, including the Taxi routing,
PrepareForSim lifecycle, Guice/scoring, fare parity, duplicate-charge, finite
value, configuration-guard, smoke-contract, and Python native-routing tests.
It launched no Hong Kong QSim, Hong Kong Controler run, or server run. The
mandatory suite did include the small generic repository regression described
below.

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

## Stage 2 verification boundary

Stage 2 validation is offline and deterministic. It does not launch a Hong
Kong MATSim scenario:

| Check | Result |
|---|---|
| Canonical PT release validator | 20/20 checks passed; exit 0 |
| Locked PT Python scripts | 23/23 compiled |
| Canonical query fixtures | 6/6 normalized outputs match |
| Structured release files | 25 JSON parsed; 78 CSV headers read; 16 Parquet readable |
| Registered canonical hashes | 16/16 match |
| Protected MATSim inputs | 8/8 unchanged |
| `.\mvnw.cmd -DskipTests compile` | `BUILD SUCCESS`; exit 0; 31.158 s |
| `.\mvnw.cmd test` | `BUILD SUCCESS`; 61 tests; 0 failures/errors/skips; 44.662 s |

The compact Stage 2 validation record is:

```text
data/transport_costs/hongkong/integration_stage2_validation_v1/
  stage2_pt_merge_validation.json
```

For diagnostic traceability, the historical GMB validator was also invoked
after the earlier historical validators. It passed 21/23 checks but its two
raw-byte guards reported prior-directory/rebuild differences caused by
Windows checkout line endings and validator-generated text rewrites. No
output from that failed attempt is retained. This diagnostic led to the
cross-platform canonical release validator and does not alter or waive any
fare-content, registry, protected-input, unresolved/null, or query-fixture
check.

Stage 2 retains the same non-blocking Maven, Java 25, MATSim, Guice ASM, and
synthetic-fixture warnings documented for Stage 1. No simulation trend is
created; the five-layer counts are an offline release baseline only.
