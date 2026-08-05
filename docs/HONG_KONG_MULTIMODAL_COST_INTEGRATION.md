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

Stage 2 passed independent exact-SHA review at:

```text
6902501e956bc9bede52de26e1e8ad9bf2b457d6
```

Stage 3 explicitly merges the locked offline Car source:

```text
integration first parent:
  6902501e956bc9bede52de26e1e8ad9bf2b457d6
Car second parent:
  fc906efd3afb98e027cc6cca44060dec9e32aa46
```

The exact Stage 3 integration result entering the governance-only Stage 4A
migration is:

```text
75988d2645f55a36fb6271ff49d887c1b5143c1b
```

Current stage status and stable cross-session rules are maintained in
[`docs/integration/CURRENT_STAGE.md`](integration/CURRENT_STAGE.md) and
[`docs/integration/INTEGRATION_POLICY.md`](integration/INTEGRATION_POLICY.md).

Stage 4A passed independent exact-SHA review at `3cbe393ec262550ab27bc13635614b8f0440c958`.
Stage 4 passed independent exact-SHA review at
`191befd0c93027c5584857333a29746de8b432f0`. Its sole authoritative integrated
registry is:

```text
data/transport_costs/hongkong/
  integrated_multimodal_cost_source_interface_manifest_v1.json
```

That registry points to exactly three current interfaces: the active native
Taxi runtime/route-fare path, the five-layer PT fare interface, and the Car
`unified_marginal_cost_interface_v1`. Historical, candidate, accounting,
design-only and superseded artifacts remain preserved but cannot act as
parallel canonical interfaces.

Stage 5 migrates only the canonical Taxi route-fare runtime to the composable
scoring factory recorded in that registry. The active component registry has
exactly one entry, `taxi_route_fare_v1`, and exactly one mode owner,
`taxi -> taxi_route_fare_v1`. PT and Car remain offline-only and contribute no
runtime scoring component.

Stage 5 passed independent exact-SHA review and was formally closed at:

```text
9235ccb62dbea43a2f321e4fba2aee6e5629bce0
```

CONTROL-PROTOCOL-01 passed independent exact-SHA review and was formally
closed at `d9f6c10e506e7c43a9d44d7d3cb772e5e9b8b41a`. The Supervisor-centered
hub-and-spoke protocol in
[`docs/integration/INTEGRATION_POLICY.md`](integration/INTEGRATION_POLICY.md)
remains active: real-time messages carry handoffs, while worklogs are
append-only audit and do not authorize execution.

Stage 6 adds the read-only PT itinerary and stuck-governance layer documented
in
[`docs/HONG_KONG_PT_ITINERARY_AND_STUCK_GOVERNANCE.md`](HONG_KONG_PT_ITINERARY_AND_STUCK_GOVERNANCE.md).
It validates prepared-plan legality before QSim and classifies later PT/walk
stuck events without pricing PT, changing the transit schedule, or inferring
capacity/supply causes. Stage 6 passed independent exact-SHA review and was
formally closed at:

```text
176484d2be98664d280375c1d595c953d7d3163d
```

Stage 7 activates the strict five-layer PT fare runtime described in
[`docs/HONG_KONG_PT_FARE_RUNTIME.md`](HONG_KONG_PT_FARE_RUNTIME.md). The
combined composition has exactly two active components and unique mode
owners:

```text
pt   -> pt_fare_layered_v1
taxi -> taxi_route_fare_v1
```

The runtime reads hash-locked domestic MTR, Light Rail, GMB, Ferry, and Bus
Core rules only after an explicit prepared itinerary exists. Generic source
PT rows remain null/unresolved, transfer concessions remain unmodelled, Bus
simulation candidates remain inactive, and Car remains offline in Stage 7.
Stage 7 passed independent exact-SHA review and was formally closed at:

```text
d8fda87eda176f46dd00763709f56b530383476f
```

Stage 8A then activates only the hash-locked base Car
`fuel_or_electricity` component. The current unique composition is:

```text
car  -> car_fuel_or_electricity_v1
pt   -> pt_fare_layered_v1
taxi -> taxi_route_fare_v1
```

Car toll, destination parking, motorcycles, and fixed ownership remain
inactive. Exact source-key, route-distance, route-fingerprint, ordinal and
callback guards fail closed. A nonzero standard Car
`monetaryDistanceRate` is rejected without mutation or reinterpretation, so
the energy component cannot double count the unverified distance monetary
term. The full scoped contract is in
[`docs/HONG_KONG_CAR_ENERGY_RUNTIME.md`](HONG_KONG_CAR_ENERGY_RUNTIME.md).

Stage 8A passed independent exact-SHA review and was formally closed at:

```text
5cc8aaaca0f5d5e073fff2792a29ed929c372139
```

Stage 8B preserves energy and adds only confirmed base toll inside one Car
mode owner:

```text
car -> car_marginal_cost_v1
       - car_fuel_or_electricity_v1
       - car_confirmed_toll_v1
```

Confirmed toll is keyed to exact canonical person/leg, route distance,
full-link count, physical facility-link evidence, and route fingerprint.
Confirmed no-charge is a legal zero; missing, ambiguous, unconfirmed, or
unresolved toll stays null and fails closed. No distance, road-class,
route-presence, or candidate fallback is active. See
[`docs/HONG_KONG_CAR_TOLL_RUNTIME.md`](HONG_KONG_CAR_TOLL_RUNTIME.md).

Stages 7, 8A, and 8B change no production config, plans, supply, demand,
capacity, ASC, monetary utility, city metadata, or run manifest; no Runner or
MATSim/server run is authorized.

Stage 8B passed independent exact-SHA review and was formally closed at:

```text
4ab83c79959bf4ccaa7d36cd6567b61cd84494b0
```

Stage 8C preserves energy and confirmed toll and adds only resolved base
destination parking inside the same Car mode owner:

```text
car -> car_marginal_cost_v1
       - car_fuel_or_electricity_v1
       - car_confirmed_toll_v1
       - car_destination_parking_v1
```

The runtime requires exact audited destination facility, activity, source
times and route identity. It retains 835 unresolved private-car parking rows
as null and 2,929 motorcycles as out of scope; documented home marginal zero
does not activate fixed ownership. No nearest-location, candidate, distance,
road-class or zero-fill inference is active. See
[`docs/HONG_KONG_CAR_PARKING_RUNTIME.md`](HONG_KONG_CAR_PARKING_RUNTIME.md).

Stages 7 through 8C change no production config, plans, supply, demand,
capacity, ASC, monetary utility, city metadata, or run manifest; no Runner or
MATSim/server run is authorized.

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
now binds the canonical `HongKongMultimodalScoringFunctionFactory`, which
wraps the standard MATSim scoring delegate and composes a deterministic set of
uniquely identified and uniquely mode-owning components.

The Taxi-only `HongKongTaxiFareScoringComponentFactory` is the sole registered
component. At scoring-function creation it reads each selected-plan Taxi leg's
current prepared route, calculates the distance fare, and builds an immutable
ordinal `HongKongTaxiPersonFareSchedule`. Event-reconstructed experienced Taxi
legs consume that schedule in order. Extra or unconsumed entries fail.

The former `HongKongTaxiScoringFunctionFactory` and
`HongKongTaxiScoringFunction` remain preserved as the pre-Stage-5 equivalence
and historical load-audit baseline. They are not bound by the canonical
runtime module and do not control the current architecture. An exact
implementation test exercises the full scoring callback surface through both
wrappers and requires identical score, callback counts, and explanation.

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

## Stage 5 Taxi-only scoring composition

Stage 5 changes architecture, not Taxi economics. The route-fare calculator,
fare utility `-0.05 util/HKD`, technical placeholder `ASC=-9`, zero standard
Taxi distance terms, native routing, standard PrepareForSim lifecycle, and
ordinal fail-closed charge path are unchanged.

Composition guards reject duplicate component IDs, duplicate mode ownership,
and factory/component ID mismatch. The production runtime guard and
PrepareForSim validator also require exactly:

```text
active components:  [taxi_route_fare_v1]
active mode owners: {taxi: taxi_route_fare_v1}
```

No PT/Car component, money-event fare, static cost lookup, fixed ownership,
imputation, or silent-zero path is introduced. The compact Stage 5 evidence is:

```text
data/taxi/hongkong/processed/
  taxi_scoring_composition_stage5_validation_v1/
    stage5_taxi_scoring_composition_validation.json
```

Non-blocking diagnostics include Maven's deprecated `${parent.version}`
expression, deprecated MATSim scoring APIs, Java 25 native-access/Unsafe
warnings, Guice line-number inspection using an ASM version that does not
understand class-file major version 69, and synthetic-fixture configuration
warnings. Guice injection and all tests still pass; none of these diagnostics
changes the Taxi runtime contract.

## Stage 7 strict PT fare scoring composition

`HongKongMultimodalCostScoringModule` supersedes the Taxi-only module as the
canonical combined composition without deleting the Taxi-only equivalence and
historical-smoke path. `HongKongPtFareRuntimeCatalog` validates ten source
hashes, loads the five strict layer tables, and maps schedule facilities only
through exact canonical crosswalks.

`HongKongPtPersonFareSchedule` snapshots selected prepared PT legs, chained
segments, ordinals and route fingerprints. `HongKongPtFareScoring` charges
each resolved segment once from `handleLeg`; it emits no money event and
ignores money/event/trip callbacks. Extra, missing, reordered, or changed
route callbacks fail closed. Unresolved fare remains null with an explicit
reason and no inferred fare contribution.

The existing MATSim `marginalUtilityOfMoney` is reused without mutation.
Standard PT `monetaryDistanceRate` must already be zero; a nonzero value is
rejected rather than changed. Exact counts, layer qualities, representative
quotes, duplicate probes, and regression commands are recorded in:

```text
data/transport_costs/hongkong/integration_stage7_validation_v1/
  stage7_pt_fare_runtime_validation.json
  pt_runtime_layer_quality_fallback_matrix.csv
```

## Stage 8A Car fuel-or-electricity composition

`HongKongCarEnergyCostCatalog` verifies the exact canonical manifest,
component-table and registry hashes and loads only the `base`
`fuel_or_electricity` rows. It loads zero toll, parking or fixed-ownership
runtime rows. The source has 64,789 resolved private-car rows, 2,929
motorcycle null/out-of-scope rows, and 33 legal zero-distance energy rows.
There is no individual powertrain field; the already-published representative
licensed-fleet average is retained without a fabricated electric/petrol split.

`HongKongCarEnergyPersonSchedule` maps selected prepared Car legs by exact
`person_id + leg_sequence`, ignores interaction activities when deriving the
source sequence, and requires mode/routingMode, route distance, and route
fingerprint agreement. `HongKongCarEnergyScoring` charges a resolved ordinal
once from `handleLeg`; money/event/trip callbacks are inert. Missing,
unresolved, reordered, duplicate, changed-route, or non-finite input fails
closed.

Standard Car `monetaryDistanceRate` must already equal zero. The factory
rejects a nonzero value and neither mutates nor interprets it. Fixed ownership
remains an accounting sidecar, toll and destination parking remain future
sub-stages, and motorcycle source cost remains null/out-of-scope.

Structured Stage 8A evidence is:

```text
data/transport_costs/hongkong/integration_stage8a_validation_v1/
  stage8a_car_energy_runtime_validation.json
  car_energy_runtime_boundary_matrix.csv
```

## Stage 8B confirmed Car toll composition

`HongKongCarTollCostCatalog` verifies the canonical base component, toll
candidate, toll-identification, and physical passage-event hashes. It admits
only 25,858 confirmed charged legs and 38,931 confirmed full-route no-charge
legs; 2,929 motorcycles remain null/out-of-scope and canonical private-car
unresolved count is zero. The charged legs contain 30,837 physical passage
events and total 751,760 HKD.

`HongKongCarTollPersonSchedule` requires an exact source key, prepared
NetworkRoute, distance, full-link count, facility-link sequence inside the
audited source span, and callback fingerprint. `HongKongCarTollScoring`
charges only from `handleLeg` and keeps all other callback paths inert.

`HongKongCarMarginalCostScoringComponentFactory` is the single Car mode owner
and exposes the accepted energy and toll IDs as internal subcomponents. This
preserves the duplicate-mode-owner guard instead of registering two parallel
Car owners. Parking and fixed ownership remain inactive.

Structured Stage 8B evidence is:

```text
data/transport_costs/hongkong/integration_stage8b_validation_v1/
  stage8b_car_confirmed_toll_runtime_validation.json
  toll_runtime_confirmation_matrix.csv
```

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

## Stage 3 canonical offline Car marginal-cost boundary

Stage 3 explicitly merges locked Car source
`fc906efd3afb98e027cc6cca44060dec9e32aa46` into the integration history.
The complete source, audit, component-candidate, fixed-accounting,
scoring-design, source-snapshot, and superseded prototype bundle is retained
for provenance. Exactly one directory is the current behavioral-cost consumer
interface:

```text
data/transport_costs/hongkong/car_cost_v1/
  unified_marginal_cost_interface_v1/
```

Its release status is
`canonical_offline_behavioral_cost_interface_candidate`. It is an offline
candidate, not an adopted MATSim scoring input. The three and only three
leg-level marginal components are:

| Component | Current role | Null/zero rule |
|---|---|---|
| `fuel_or_electricity` | trip-conditional marginal component | motorcycle is null; only resolved zero-distance energy may be zero |
| `toll` | trip-conditional marginal component | motorcycle is null; confirmed no-charge may be zero |
| `destination_parking` | trip-conditional marginal component | 835 unresolved private-car legs stay null; only documented resolved marginal-parking statuses may be zero |

`fixed_vehicle_ownership_cost` is fixed/sunk at the current daily mode-choice
horizon. It remains in a vehicle-day accounting sidecar only and is absent
from component rows, first/last legs, trip totals, and current behavioral
marginal totals. The original top-level Car estimates remain in place with
their original hashes, explicitly classified as
`superseded_offline_prototype`, and are forbidden as behavioral scoring input.
Supporting component candidates and the scoring-adoption audit are likewise
provenance/design inputs, not parallel canonical interfaces.

The canonical offline baseline is:

```text
all Car-mode legs:                         67,718
private-car legs:                          64,789
motorcycle legs (out of scope/null):        2,929
complete private-car legs:                 63,954
parking-unresolved/incomplete legs:           835
toll charged / confirmed no-charge: 25,858 / 38,931
physical toll passage events:              30,837
```

Each low/base/high long component table contains 203,154 rows: 67,718
canonical leg keys for each of the three components. Each corresponding
summary contains 67,718 unique leg keys. Across the three scenarios there are
609,462 component rows. Complete-leg component-sum error is exactly zero;
incomplete totals and every motorcycle component/total are null;
unresolved/out-of-scope numeric-zero count is zero. All fixed-cost and scoring
adoption flags remain false.

The Stage 3 read-only validator is:

```text
scripts/hong_kong_single_city/costs/car/
  validate_hong_kong_car_cost_release_v1.py
```

It does not rebuild or rewrite any cost artifact. It verifies the canonical
bundle and 12 file hashes, five supporting candidate bundle hashes, preserved
legacy hashes, nine production-input hashes, component registry, Parquet keys
and formulas, null/legal-zero rules, motorcycle and fixed-cost exclusion,
structured-file readability, offline-only flags, and Car script compilation.
The durable integrated record is:

```text
data/transport_costs/hongkong/integration_stage3_validation_v1/
  stage3_car_merge_validation.json
```

The merge had one ordinary shared-document conflict in
`docs/PROJECT_ONBOARDING.md`. Resolution retained all existing Taxi/PT and
control-plane entries and added the Car topic-document entries. Of 118 locked
Car source paths, 117 retain the exact source blob; the onboarding file is the
single documented combined-resolution blob.

Stage 3 changes `cities/hongkong/city.yaml` only by adopting the locked
documentation pointer and `read_only_offline_audit_not_active_matsim_scoring`
metadata. It does not change current-model inputs or simulation parameters.
`runs/hongkong/run_manifest.json` is unchanged. Stage 3 introduced no Car
Java module, money event, static leg lookup, MATSim scoring/config/plans/supply
mutation, calibration, monetary-distance-rate interpretation, scenario run,
server run, or Runner action. Stage 8A supersedes only that historical runtime
status for the guarded base energy component, and Stage 8B separately
supersedes it only for confirmed base toll. All other Stage 3 source and
exclusion boundaries remain intact.

Stage 3 deterministic validation results:

| Check | Result |
|---|---|
| Integrated Car read-only validator | exit 0; 12 canonical hashes, 5 candidate bundles, 9 protected inputs |
| Structured Car release files | 22 JSON parsed; 33 CSV headers read; 26 Parquet files readable |
| Car Python scripts | 12/12 compile, including the integrated read-only validator |
| Canonical PT release regression | 20/20 checks passed; 16/16 registered hashes |
| `.\mvnw.cmd -DskipTests compile` | `BUILD SUCCESS`; exit 0; Maven 13.081 s |
| `.\mvnw.cmd test` | `BUILD SUCCESS`; 61 tests; 0 failures/errors/skips; Maven 45.539 s |

The previously documented Maven `${parent.version}`, Java 25 native-access and
Unsafe, Guice ASM, MATSim, and synthetic-fixture warnings remain non-blocking.
No MATSim or behavioral trend is created or authorized in Stage 3.

## Direct joint-scoring runtime entry point

`RunHongKong5Pct` can now install the canonical Taxi/PT/Car scoring
composition for an actual simulation with:

```text
--simulate --multimodal-costs
--pt-fare-root=<pt_fare_v1 directory>
--car-cost-root=<car_cost_v1 directory>
```

Both cost roots are mandatory when joint scoring is enabled. Before loading
the full scenario, the entry point validates that the config already contains
an explicit Taxi scoring mode compatible with custom fare scoring. It does not
choose a Taxi ASC or silently manufacture missing Taxi parameters. The Car
component separately requires standard Car `monetaryDistanceRate=0` so the
custom marginal-cost component is the sole Car monetary-distance owner.

The independent 2026-08-05 Stage 11 attempt used this entry point and one
10-iteration identity. It exited before iteration 0 because its inherited
production config had no Taxi scoring mode set. Exact identity, evidence, and
the no-retry decision are recorded in
[`STAGE_11_JOINT_STABILITY_5_10_ITERATIONS.md`](integration/stage-briefs/STAGE_11_JOINT_STABILITY_5_10_ITERATIONS.md).

After the user authorized the fixed Taxi formula, a replacement identity
successfully passed Taxi config validation, Injector creation, startup, and
`PrepareForSim`, then exposed a separate destination-parking validation bug at
iteration-0 scoring initialization. The source field is the next departure of
the same physical vehicle. The current production data has no cross-person
vehicle use, but the next Car departure can occur after intervening non-Car
trips and therefore must not be equated with the current destination
activity's end time. The local runtime fix preserves person-local
arrival/destination identity checks and leaves the vehicle-chain evidence with
the canonical parking catalog.

The subsequently authorized repair sequence completed one fixed-canonical-plan
Stage 11 identity at
`/mnt/DiskM/by/hk_stage11_direct_10it_fixed_plans_20260805_run9`. MATSim
completed iterations `0..10` and exited `0`. Runtime scoring now consumes
person-local same-mode ordinals without route-fingerprint gates and charges
only the experienced prefix; an untravelled suffix is recorded but not
charged. Scoring functions are created at `BeforeMobsim` so the snapshot is
not stale relative to the plan about to execute.

This completed identity is not full Taxi runtime coverage. Its release
selected `plans_routed_5pct_v2.xml.gz`, which retains Taxi-assigned demand as
`mode=ride`, rather than the separate Taxi-native plans derivative. Both the
final and experienced output plans contain zero `mode=taxi` legs; experienced
counts were Car `55,366`, PT `556,924`, ride `56,326`, walk `172,588`, and
Taxi `0`. The Taxi formula and component were configured and injected but
never received a Taxi-leg callback. The run therefore demonstrates joint
stack completion and live Car/PT paths, not simultaneous live Taxi/PT/Car
charging. A future closure run must package/select the Taxi-native plans and
first prove their compatibility with the static Car/PT cost identities.

Because the accepted Car energy/toll/parking artifacts are static
person/leg/route products, this technical stability identity freezes route,
mode, and time innovation: `ChangeExpBeta=1`, while `ReRoute`,
`SubtourModeChoice`, and `TimeAllocationMutator` are `0`. Dynamic route- and
mode-dependent cost regeneration is not claimed. Exact output metrics,
limitations, immutable paths, and the complete failure-to-repair chain are in
[`STAGE_11_JOINT_STABILITY_5_10_ITERATIONS.md`](integration/stage-briefs/STAGE_11_JOINT_STABILITY_5_10_ITERATIONS.md).
