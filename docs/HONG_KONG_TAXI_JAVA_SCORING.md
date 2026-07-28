# Hong Kong Java custom taxi fare scoring v1

## Scope and status

This component adds the fare-only utility contribution for the Hong Kong Taxi
behavioural pilot. It is deliberately separate from existing runners and
configs: the module is available for a future pilot runner, but this stage
does not install it into `RunHongKong5Pct` or any other runner.

The implementation targets:

```text
Java:   25
MATSim: 2026.0
JUnit:  6.0.3
```

The MATSim scoring, factory, config, and module signatures were checked from
the locally resolved `matsim-2026.0.jar` before implementation. No dependency
or `pom.xml` change was required.

## Plans data interface

The scorer reads only the typed attributes already embedded in each
`mode=taxi` leg:

| Attribute | Runtime type | Validation |
|---|---|---|
| `hkTaxiFareBaselineHkd` | `Double`/`Number` | finite and non-negative |
| `hkTaxiType` | `String` | non-blank; `unresolved` is accepted |
| `hkTaxiFareScope` | `String` | exactly `distance_only_v1` |
| `hkTaxiFareModelVersion` | `String` | exactly `hong_kong_taxi_fare_model_v1` |
| `hkTaxiClassificationSource` | `String` | non-blank |
| `hkTaxiMainTripIndex` | `Integer` | non-negative |

All names are defined once in `HongKongTaxiLegAttributes`. MATSim exposes leg
attributes as a map, so one runtime name has at most one value. Every required
name must be present; an explicit null is also rejected.

No CSV or Parquet fare lookup is performed at runtime. A missing fare is not
treated as zero, and route distance is never used to reconstruct a fare.

## Fare formula

Central v1 parameters:

```text
fare_utility_per_hkd = 0.05 util/HKD
fare_share_factor    = 1.0
```

For a leg whose actual mode is `taxi`:

```text
fare_score =
  -fare_utility_per_hkd
  * hkTaxiFareBaselineHkd
  * fare_share_factor

fare_score = -0.05 * fare_hkd
```

There is no intermediate rounding:

| Fare | Contribution |
|---:|---:|
| 24.0 HKD | -1.2 util |
| 98.3 HKD | -4.915 util |
| 100.0 HKD | -5.0 util |
| 491.7 HKD | -24.585 util |

The component does not multiply by global `marginalUtilityOfMoney`. The
coefficient is already in `util/HKD`; sending the fare through
`PersonMoneyEvent` or standard `MoneyScoring` would risk applying the global
money coefficient a second time. The custom scorer therefore creates no
money event and forwards existing standard money calls only to the standard
delegate.

## Responsibility boundary

`HongKongTaxiFareScoring` implements the MATSim 2026.0
`SumScoringFunction.LegScoring` interface and accumulates only fare
disutility. It does not score:

- taxi ASC or constant;
- travel time or route distance;
- the legacy `ride` constant or distance rate;
- waiting, tunnel, booking, or dynamic-pricing costs;
- fleet supply, pickup delay, or operator behaviour.

`HongKongTaxiScoringFunction` wraps the complete standard scoring function.
Activity, leg, trip, money, arbitrary score, stuck, event, finish, and score
explanation calls are forwarded to the delegate. A taxi leg is also sent once
to the independent fare component:

```text
total score =
  standard MATSim score
  + custom taxi fare score
```

The standard taxi mode scoring is responsible for the finite ASC/constant and
travel-time utility. When this custom module is installed, the taxi mode must
have:

```text
marginalUtilityOfDistance = 0
monetaryDistanceRate      = 0
```

The factory rejects a missing taxi mode, nonzero distance term, or non-finite
related scoring value. A finite taxi constant is intentionally unrestricted
so later ASC tests can vary it without changing this component.

## Mode and routing mode

Fare eligibility is based only on:

```java
"taxi".equals(leg.getMode())
```

`routingMode` is neither read nor changed. The current converted plans retain
`mode=taxi` with `routingMode=ride`; a unit test confirms that such a leg is
charged exactly once. Conversely, a non-taxi leg receives zero custom fare
score even if its routing mode is `taxi`.

This verifies scoring compatibility only. Routing/load compatibility remains
for a later, separately authorized pilot stage.

## Error handling

Every invalid taxi attribute throws immediately. The exception includes:

```text
person_id
leg_mode
attribute name
actual value
actual runtime type
expected value/type
```

The reader does not default, coerce string fares, relabel `unresolved`, or
silently repair metadata. Non-taxi legs need no taxi attributes and return
zero custom contribution.

## Java structure

```text
src/main/java/org/matsim/project/hongkong/taxi/
  HongKongTaxiScoringParameters.java
  HongKongTaxiLegAttributes.java
  HongKongTaxiFareScoring.java
  HongKongTaxiScoringFunction.java
  HongKongTaxiScoringFunctionFactory.java
  HongKongTaxiScoringModule.java
```

The factory uses MATSim 2026.0
`CharyparNagelScoringFunctionFactory(Scenario)` as its standard delegate and
creates fresh fare-scoring state for each person. The standalone module binds
the custom factory but is not installed anywhere in this change.

## Unit tests

Tests use only small synthetic persons, legs, plans, events, trips, delegates,
and configs:

```text
src/test/java/org/matsim/project/hongkong/taxi/
  HongKongTaxiFareScoringTest.java
  HongKongTaxiScoringFunctionTest.java
  HongKongTaxiScoringConfigGuardTest.java
```

Coverage includes:

- all four known fare examples and multiple-leg summation;
- idempotent `getScore()` and no extra charge from `finish()`;
- `mode=taxi` plus `routingMode=ride`;
- non-taxi mode exclusion and accepted `unresolved` taxi type;
- each missing attribute, wrong fare type, negative/non-finite fare, wrong
  scope/version, invalid main-trip index, and blank classification metadata;
- standard activity, leg, trip, money, score, stuck, event, finish, and
  explanation forwarding;
- exact delegate-plus-fare total and person-local state;
- independence from global `marginalUtilityOfMoney`;
- safe config acceptance, missing taxi mode rejection, finite arbitrary ASC,
  nonzero taxi distance-term rejection, and non-finite parameter rejection.

Validation commands:

```powershell
mvn -DskipTests compile

mvn `
  "-Dtest=HongKongTaxiFareScoringTest,HongKongTaxiScoringFunctionTest,HongKongTaxiScoringConfigGuardTest" `
  test
```

The completed exact test run reports:

```text
Tests run: 31
Failures:  0
Errors:    0
Skipped:   0
```

No 82 MB plans file is loaded by the tests. No MATSim Controler, QSim,
routing, load test, custom runner, ASC experiment, or fleet simulation was
run. No config, runner, plans, fare audit, network, facility, vehicle, fleet,
or `pom.xml` file was modified.
