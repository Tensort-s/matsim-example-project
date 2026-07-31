# Hong Kong Java Taxi route-fare scoring v1

## Scope and status

The passenger/teleported Taxi scoring component now calculates the distance
fare from each Taxi leg in the person's current selected plan. Runtime scoring
no longer uses `hkTaxiFareBaselineHkd` to decide the fare.

This stage did not run a Hong Kong scenario, a remote PT rebuild, a Controler,
QSim, or the two-iteration smoke. It did not change the PrepareForSim flow,
ASC, fare coefficient, PT/Car scoring, capacity, Taxi allocation, supply, or
fleet/DVRP boundary.

## Runtime data path

The canonical `HongKongMultimodalScoringFunctionFactory` creates the standard
MATSim scoring delegate and all registered person-local components. In Stage 5
the registry contains only `HongKongTaxiFareScoringComponentFactory`, with
component ID `taxi_route_fare_v1` and sole mode ownership `taxi`.

Whenever that Taxi component factory creates its component, it:

1. visits that person's current selected plan in plan-element order;
2. calls `HongKongTaxiRouteContext.from(leg)` for every `mode=taxi` leg;
3. calculates a fare from `route.distance` and `hkTaxiType`;
4. stores an immutable `HongKongTaxiPersonFareSchedule` in zero-based Taxi
   ordinal order.

MATSim reconstructs experienced legs from events without guaranteeing custom
source-plan attributes. Therefore the experienced Taxi leg is used only to
verify `mode=taxi`, `routingMode=taxi`, and consume the next schedule entry. It
does not need a route or any custom Taxi attribute.

An extra experienced Taxi leg fails immediately. `finish()` fails when any
selected-plan Taxi fare remains unconsumed.

`hkTaxiFareBaselineHkd` remains in the versioned native-routing plans as a
historical comparison field. It is not read by the scoring factory, schedule,
or fare scorer. A legal routed Taxi leg can be scored when that baseline field
is absent.

## Distance fare formula

`HongKongTaxiFareCalculator` is a pure calculation component. For distance
`d` in metres:

```text
if d <= 2000:
    fare = flagfall
else:
    first_count =
      ceil(max(min(d, first_tier_end_m) - 2000, 0) / 200)
    second_count =
      ceil(max(d - first_tier_end_m, 0) / 200)
    fare =
      flagfall
      + first_count * first_increment_hkd
      + second_count * second_increment_hkd
```

The runtime values are:

| Requested type | Flagfall | First tier end | First increment | Second increment |
|---|---:|---:|---:|---:|
| `urban_taxi` | 29.0 HKD | 9,000 m / 102.5 HKD | 2.1 HKD / 200 m | 1.4 HKD / 200 m |
| `new_territories_taxi` | 25.5 HKD | 8,000 m / 82.5 HKD | 1.9 HKD / 200 m | 1.4 HKD / 200 m |
| `lantau_taxi` | 24.0 HKD | 20,000 m / 195.0 HKD | 1.9 HKD / 200 m | 1.6 HKD / 200 m |

Each 200 m or part thereof is charged by ceiling. Fare arithmetic is performed
as integer tenths of HKD, so the result is retained to 0.1 HKD without binary
floating-point accumulation drift.

`unresolved` keeps its requested classification but applies the Urban Taxi
rule. The calculation result records both requested and applied Taxi type plus
an explicit `unresolvedUrbanFallback=true` flag.

Negative, NaN, or infinite distance is rejected. Waiting time, congestion,
tunnels, booking, baggage, dynamic pricing, travel time, departure time, and
classification source do not enter fare v1.

## Rule provenance and drift guard

The runtime rules represent:

```text
data/taxi/hongkong/processed/taxi_fare_model_v1/taxi_fare_rules.csv
```

Tracked CSV SHA256:

```text
1bf1527702ba5ea2b8f471e78bcfe7a852dc46602b454a3d0115c03f38c6dd7e
```

`HongKongTaxiFareCalculator.requireMatchesRuleCsv(...)` verifies both this
identity and every runtime-relevant CSV field. The unit test and full parity
audit call that guard, preventing an unreviewed Python-table/Java-rule split.

## Utility and double-charge boundary

The custom contribution is:

```text
fare utility = -0.05 util/HKD * calculated_route_fare_hkd * 1.0
```

The following remain fixed:

```text
ASC                              = -9
fareShareFactor                  = 1.0
Taxi monetaryDistanceRate        = 0
Taxi marginalUtilityOfDistance   = 0
```

The scorer emits no `PersonMoneyEvent`. Money events, arbitrary events, and
standard money calls are forwarded only to the standard delegate; they do not
invoke the custom ordinal fare scorer. Config validation rejects nonzero Taxi
distance-money or distance-utility terms.

## Full native-plans parity audit

`HongKongTaxiRouteFareParityAudit` streamed the population from:

```text
F:\Matsim\derived\hongkong\taxi_behavioral_pilot_native_routing_v1\
  plans_routed_5pct_taxi_native.xml.gz
```

It read no network, schedule, vehicles, or facilities and created no
Controler/QSim.

Compact outputs:

```text
data/taxi/hongkong/processed/taxi_route_fare_scoring_v1/
  taxi_route_fare_parity_by_type.csv
  taxi_route_fare_parity_validation.json
```

Results:

| Requested type | Count | Baseline/calculated mean | Baseline/calculated median | Max abs difference |
|---|---:|---:|---:|---:|
| `urban_taxi` | 31,037 | 104.4621741792 | 96.2 | 0.0 |
| `new_territories_taxi` | 3,654 | 100.2772030651 | 80.6 | 0.0 |
| `lantau_taxi` | 62 | 34.6951612903 | 29.7 | 0.0 |
| `unresolved` → Urban fallback | 2,533 | 191.7459928938 | 213.1 | 0.0 |

All 37,286 fares were bitwise exact and equivalent at `1e-9` HKD; mismatch
count and maximum absolute difference were both zero. Route-context failures
and invalid comparison baselines were also zero.

## Lightweight verification

Synthetic tests cover all three flagfalls, the 2,000 m boundary, partial
increments, every first-tier end, second-tier charging, unresolved fallback,
invalid distances, monotonicity, route-change sensitivity, missing/incorrect
comparison baseline, attribute-free experienced legs, ordinal mismatch
guards, no distance-money/PersonMoneyEvent duplication, factory isolation,
config guards, and native whole-plan routing.

The current runtime route input boundary is:

```text
HongKongTaxiRouteContext
  route.distance
  route.travelTime
  leg.departureTime
  hkTaxiType
  hkTaxiClassificationSource
```

Only `route.distance` and `hkTaxiType` are charged in this version.

## Standard PrepareForSim lifecycle

The formal runner no longer invokes the custom one-shot
`HongKongTaxiPtRoutePreparation.rebuildPtTripsAtStartup(...)`. MATSim 2026.0's
default `PrepareForSimImpl` performs whole-plan preparation in parallel after
the source PT Generic routes are cleared.

`HongKongTaxiPrepareForSimLifecycleTest` proves the ordering on a synthetic
scenario:

```text
default PrepareForSim updates the selected-plan Taxi route
→ HongKongMultimodalScoringFunctionFactory is requested
→ HongKongTaxiFareScoringComponentFactory reads that prepared route
→ HongKongTaxiFareCalculator charges its current distance
```

No delayed schedule refactor was needed. In the MATSim Controler lifecycle,
default PrepareForSim runs before iteration-start and BeforeMobsim scoring
functions are created. The full Hong Kong validation independently confirmed
the same path through the real installed factory: schedule fare matched the
prepared route, all 37,286 route fares calculated, and the historical
`hkTaxiFareBaselineHkd` was not used as runtime fare.

The full validation is recorded in:

```text
data/taxi/hongkong/processed/taxi_prepare_for_sim_validation_v1/
  taxi_prepare_for_sim_validation.json
```

It observed 7,696 reasonable Taxi route changes, but no Taxi count, mode,
routingMode, ordinal, attribute, or selected-plan sequence changes. The next
runtime stage, if separately authorized, must retain the current route-based
fare, passenger-only Taxi boundary, capacity, offline PT/Car boundary, and
no-replanning settings. Stage 5 authorizes no smoke or other MATSim run.

## Stage 5 composable architecture and equivalence

`HongKongTaxiScoringModule` now installs the generic
`HongKongMultimodalScoringModule` and contributes only the Taxi route-fare
component. Component ordering is deterministic. Duplicate component IDs,
duplicate mode owners, and a component whose ID differs from its factory all
fail closed.

The former `HongKongTaxiScoringFunctionFactory` and
`HongKongTaxiScoringFunction` are retained as a noncontrolling pre-Stage-5
equivalence and historical load-audit baseline. The canonical module no longer
binds them. The exact equivalence test applies activity, Taxi/non-Taxi leg,
money, arbitrary event, trip, added-score, stuck, finish, score, and
explanation callbacks to both implementations and requires zero score
tolerance plus identical standard-delegate call counts.

The Stage 5 validation record is:

```text
data/taxi/hongkong/processed/
  taxi_scoring_composition_stage5_validation_v1/
    stage5_taxi_scoring_composition_validation.json
```

PT and Car do not register components. The extension seam is structural only;
it does not approve their runtime costs or select an economic interpretation.
