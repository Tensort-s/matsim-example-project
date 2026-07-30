# Hong Kong native passenger Taxi routing v1

## Scope and status

This stage registers an independent MATSim routing mode for the Hong Kong Taxi
behavioural pilot:

```text
mode=taxi
routingMode=taxi
```

Taxi remains a teleported passenger mode. It is not a QSim network main mode,
is not a network routing mode, and does not install Taxi contrib, DVRP, fleet,
driver, vehicle-dispatch, or vehicle-scheduling components. No Hong Kong
scenario or remote smoke was run in this stage.

The previous `taxi_behavioral_pilot_v1` plans remain an immutable historical
input with `mode=taxi`, `routingMode=ride`. They are not overwritten.

## Routing implementation

`HongKongTaxiRoutingModule` binds routing mode `taxi` to
`HongKongTaxiRouting`. The Taxi router delegates only its distance and travel
time calculation to MATSim 2026.0's existing teleported `ride` routing
module. It does not return the delegated ride leg unchanged. The wrapper:

1. requires a single returned leg;
2. copies the six validated Taxi trip attributes to that leg;
3. sets both `mode` and `routingMode` to `taxi`;
4. requires a non-null route;
5. requires finite, non-negative route distance, route travel time, and leg
   travel time.

This reuse keeps the established passenger ride time/distance algorithm while
giving Taxi an independent external routing identity.

`RunHongKongTaxiBehavioralPilot` calls
`HongKongTaxiRoutingModule.configure(config)` before scenario loading and
installs the routing module on the Controler. The configure guard fails if
Taxi appears in QSim main modes, network routing modes, or as a shadowing
teleported config parameter.

## MATSim trip-attribute bridge

In MATSim 2026.0, standard `PlanRouter` passes a trip's origin main-activity
attributes to `RoutingModule.calcRoute`; it does not pass the replaced source
leg's attributes. The native-routing plans derivative therefore retains all
six Taxi fields on the Taxi leg and also copies them to the origin main
activity:

```text
hkTaxiFareBaselineHkd
hkTaxiType
hkTaxiFareScope
hkTaxiFareModelVersion
hkTaxiClassificationSource
hkTaxiMainTripIndex
```

`HongKongTaxiRouting` currently accepts those six trip attributes and copies
only those six back to the newly routed Taxi leg. This allows standard whole-plan
`PlanRouter` and `PersonPrepareForSim` processing—including a plan that also
contains a null PT route—to preserve Taxi mode, routing mode, and comparison
metadata.

## Versioned conversion

The reproducible converter is:

```text
scripts/hong_kong_single_city/demand_generation/
  prepare_hong_kong_taxi_native_routing.py
```

It reads the old v1 Taxi plans, changes only Taxi `routingMode` plus the
origin-activity trip-attribute bridge, and writes new outputs. Existing inputs
and outputs must not exist at the destination path.

Large local derived outputs:

```text
F:\Matsim\derived\hongkong\taxi_behavioral_pilot_native_routing_v1\
  plans_routed_5pct_taxi_native.xml.gz
  config_hong_kong_taxi_native_routing_v1.xml
```

The config changes the `plans/inputPlansFile` value to:

```text
/mnt/DiskM/by/hk_taxi_behavioral_pilot_v1/native_routing_v1/input/
  plans_routed_5pct_taxi_native.xml.gz
```

It retains `qsim/mainMode=car` and `routing/networkModes=car`; it contains no
DVRP or fleet module. The generated local config is a next-smoke candidate,
not evidence that a remote smoke has run.

Compact tracked validation:

```text
data/taxi/hongkong/processed/taxi_native_routing_v1/
  taxi_native_routing_validation.json
```

Validated artifact identities:

| Artifact | SHA256 |
|---|---|
| Historical v1 Taxi plans input | `f4631ab00c6f5027160314f7357e32d969b7588192008c17ac79bf0b3208ce27` |
| Native-routing Taxi plans | `9100cb58ce268d9f62771039eaa80d4da11bf200ceb8426130ef272c05de8f1f` |
| Historical formal config input | `662268c6aa81042d40096326d75736fe86f9594404f040180d185de84224a7b4` |
| Native-routing config | `f23e999ac5f10ccaf5c8743181268a8d2b9b01ac0021b6b91db0c9357f548369` |

The conversion validated:

- Taxi count `37,286 -> 37,286`;
- mode counts unchanged, including Taxi `37,286`;
- Taxi routing mode `ride=37,286 -> taxi=37,286`;
- 37,286 complete origin-activity Taxi attribute sets;
- identical Taxi OD fingerprint
  `d51118fb5e30a9027144ffe4a61a2f1c1388efcf84a32815737915c0cc5335b8`;
- Taxi absent from QSim main modes and network routing modes;
- no DVRP or fleet config.

## Current route-based fare scoring

Fare scoring now builds an immutable ordinal schedule from each selected-plan
Taxi leg's current route:

```text
fare utility = -0.05 * calculated_route_fare_hkd
ASC = -9
```

`HongKongTaxiRouteContext.from(leg)` exposes:

- `route.distance` in metres;
- `route.travelTime` in seconds;
- `leg.departureTime` in seconds;
- `hkTaxiType`;
- `hkTaxiClassificationSource`.

`HongKongTaxiFareCalculator` uses only distance and Taxi type in fare v1.
Travel time, departure time, and classification source remain available for a
later reviewed fare extension. `hkTaxiFareBaselineHkd` is retained only for
parity comparison and is not read by runtime scoring. See
[HONG_KONG_TAXI_JAVA_SCORING.md](HONG_KONG_TAXI_JAVA_SCORING.md).

## Lightweight verification

`HongKongTaxiRoutingModuleTest` uses a synthetic two-link scenario. It verifies
single-trip routing and standard whole-plan
`PlanRouter`/`PersonPrepareForSim` routing with a null PT route and a Taxi
trip. In both cases Taxi remains `mode=taxi`, `routingMode=taxi`, never
produces a ride leg, retains its fare metadata, and has a legal route,
distance, and travel time.

`test_prepare_hong_kong_taxi_native_routing.py` uses a tiny gzip population and
config to verify count/OD preservation, trip-attribute bridging, and config
passenger-only invariants.
