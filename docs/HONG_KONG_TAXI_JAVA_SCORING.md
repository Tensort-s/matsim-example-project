# Hong Kong Java custom taxi fare scoring v1

## Scope and status

This component adds the fare-only utility contribution for the Hong Kong Taxi
behavioural pilot. This correction changes only the scoring data interface;
it does not alter the existing pilot runner, module binding, or config.

The implementation targets:

```text
Java:   25
MATSim: 2026.0
JUnit:  6.0.3
```

The MATSim scoring, factory, config, and module signatures were checked from
the locally resolved `matsim-2026.0.jar` before implementation. No dependency
or `pom.xml` change was required.

## Plans-to-experienced-leg data interface

MATSim 2026.0 `EventsToLegs` reconstructs a new experienced leg from events.
That leg does not inherit custom attributes from its source-plan leg.
`ScoringFunctionsForPopulation` then passes the reconstructed leg to
`ScoringFunction.handleLeg`. Consequently, runtime fare scoring must not
expect `hkTaxiFareBaselineHkd` or the other Taxi metadata on the experienced
leg.

Whenever `HongKongTaxiScoringFunctionFactory` creates a scoring function, it
reads only that person's selected source plan. It visits the plan elements in
their actual order and validates every `mode=taxi` source leg through
`HongKongTaxiLegAttributes.readAndValidate(...)`. The validated values are
copied into a person-local immutable `HongKongTaxiPersonFareSchedule`:

| Attribute | Runtime type | Validation |
|---|---|---|
| `hkTaxiFareBaselineHkd` | `java.lang.Double` | finite and non-negative |
| `hkTaxiType` | `java.lang.String` | non-blank; `unresolved` is accepted |
| `hkTaxiFareScope` | `java.lang.String` | exactly `distance_only_v1` |
| `hkTaxiFareModelVersion` | `java.lang.String` | exactly `hong_kong_taxi_fare_model_v1` |
| `hkTaxiClassificationSource` | `java.lang.String` | non-blank |
| `hkTaxiMainTripIndex` | `java.lang.Integer` | non-negative |

All six fields are retained in each immutable schedule record. All names are
defined once in `HongKongTaxiLegAttributes`. MATSim exposes source-leg
attributes as a map, so one runtime name has at most one value. Every required
name must be present; an explicit null is also rejected.

The fare type contract is exact: `Integer`, `Long`, `Float`, `BigDecimal`,
`String`, and every other non-`Double` runtime type are interface errors.
Values are not parsed or converted through `Number.doubleValue()`.

Each new scoring function receives a fresh zero-based consumption cursor.
When an experienced `mode=taxi` leg arrives, the fare scorer validates the
current `routingMode=ride` contract and consumes the next schedule record. It
does not read any custom attribute from the experienced leg. Non-Taxi legs do
not consume the schedule.

An extra experienced Taxi leg fails immediately. `finish()` requires the
consumed experienced-Taxi count to equal the selected-plan Taxi count, so a
missing experienced Taxi leg also fails. No CSV or Parquet fare lookup is
performed at runtime. A missing fare is not treated as zero, and route
distance is never used to reconstruct a fare.

The existing scenario-load audit has a clearly separated source-plan-only
compatibility constructor. That offline path validates the source leg
directly; the runtime scoring factory never uses it.

### Applicability boundary

Matching by `(person, zero-based Taxi ordinal)` is deterministic only for the
current technical scenario:

- selected plans are fixed;
- no strategy or replanning is enabled;
- no rerouting is enabled;
- Taxi leg count and order do not change.

This interface is not suitable for future mode-choice calibration that
creates new Taxi alternatives. Before enabling replanning, fare metadata must
instead be stored with, or deterministically rebuilt for, each generated plan
alternative.

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
`SumScoringFunction.LegScoring` interface. Its runtime path consumes the
person-local fare schedule and accumulates only fare disutility. It does not
score:

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

Fare eligibility is based on the experienced leg's actual mode:

```java
"taxi".equals(leg.getMode())
```

For every experienced Taxi leg, `routingMode` is read and must be exactly
`ride`; it is never changed. A non-Taxi leg receives zero custom fare score
and does not advance the cursor, regardless of its routing mode.

This verifies the scoring data interface only. A successful runtime smoke is
still required for technical integration validation.

## Error handling

Every invalid source-plan Taxi attribute throws while the scoring function's
schedule is created. The exception includes:

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

Schedule mismatches also fail closed. Their error context includes:

```text
person_id
zero-based taxi_ordinal
expected_count
consumed_count
actual_mode
actual_routingMode
```

An exhausted schedule fails in `handleLeg`; an unconsumed tail fails in
`finish()`.

## Java structure

```text
src/main/java/org/matsim/project/hongkong/taxi/
  HongKongTaxiScoringParameters.java
  HongKongTaxiLegAttributes.java
  HongKongTaxiPersonFareSchedule.java
  HongKongTaxiFareScoring.java
  HongKongTaxiScoringFunction.java
  HongKongTaxiScoringFunctionFactory.java
  HongKongTaxiScoringModule.java
```

The factory uses MATSim 2026.0
`CharyparNagelScoringFunctionFactory(Scenario)` as its standard delegate and
creates a fresh immutable schedule and fare-consumption cursor for each
person and each scoring-function creation.

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

- attributed source Taxi legs paired with attribute-free experienced Taxi
  legs, including ordered multi-leg consumption;
- non-Taxi exclusion, accepted `unresolved`, immediate extra-leg failure,
  finish-time missing-leg failure, wrong routing mode, and zero-source failure;
- each missing source attribute; wrong runtime types; negative/non-finite
  fares; wrong scope/version; invalid indices; and blank metadata;
- person isolation and a fresh cursor after scoring-function recreation;
- standard activity, leg, trip, money, score, stuck, event, finish, and
  explanation forwarding, with no fare duplication through other interfaces;
- all four known fare results, exact delegate-plus-fare total, and
  independence from global `marginalUtilityOfMoney`;
- safe config acceptance, missing taxi mode rejection, finite arbitrary ASC,
  nonzero taxi distance-term rejection, and non-finite parameter rejection.

Validation commands:

```powershell
mvn -DskipTests compile

mvn `
  "-Dtest=HongKongTaxiFareScoringTest,HongKongTaxiScoringFunctionTest,HongKongTaxiScoringConfigGuardTest,HongKongTaxiScenarioLoadAuditTest,HongKongTaxiSmokeIntegrationTest" `
  test
```

The final local run used only synthetic JUnit fixtures and reported:

```text
HongKongTaxiFareScoringTest:       22 / 0 / 0 / 0
HongKongTaxiScoringFunctionTest:    7 / 0 / 0 / 0
HongKongTaxiScoringConfigGuardTest: 8 / 0 / 0 / 0
HongKongTaxiScenarioLoadAuditTest:  3 / 0 / 0 / 0
HongKongTaxiSmokeIntegrationTest:   3 / 0 / 0 / 0
Total tests/failures/errors/skipped: 43 / 0 / 0 / 0
```

No 82 MB plans file is loaded by these interface tests. This correction did
not run a MATSim Controler, QSim, routing, scenario load, remote smoke, ASC
experiment, or fleet simulation. No config, runner, plans, fare audit,
network, facility, vehicle, fleet, or `pom.xml` file was modified.
