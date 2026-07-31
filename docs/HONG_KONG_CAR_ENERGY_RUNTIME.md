# Hong Kong Car fuel-or-electricity runtime

## Stage 8A scope

Stage 8A originally activated exactly one Car scoring component:

```text
car -> car_fuel_or_electricity_v1
```

Stage 8B preserves that scorer unchanged as a subcomponent of the unique Car
owner and adds confirmed toll:

```text
car -> car_marginal_cost_v1
       - car_fuel_or_electricity_v1
       - car_confirmed_toll_v1
```

The component consumes the `base` `fuel_or_electricity` rows from the
Stage 3 canonical interface:

```text
data/transport_costs/hongkong/car_cost_v1/
  unified_marginal_cost_interface_v1/
    car_leg_marginal_cost_components_base.parquet
```

Stage 8A did not activate toll; Stage 8B activates confirmed toll only through
the separate contract above. Neither stage activates destination parking,
fixed ownership, or motorcycle scoring. They change no MATSim config, plans, network, schedule,
vehicles, facilities, demand, supply, capacity, city metadata, run manifest,
or server output.

## Source and lookup contract

`HongKongCarEnergyCostCatalog` verifies the exact SHA256 of the canonical Car
manifest, base component table, and component registry before loading. Each
runtime quote is keyed by `person_id + leg_sequence`; `leg_sequence` is the
index of the main activity immediately before the Car leg, and interaction
activities do not increment it.

The selected-plan schedule requires:

- `mode=car` and `routingMode=car`;
- a finite, nonnegative prepared route distance;
- an exact canonical person/leg key;
- source and prepared-route distance equality within `1e-6 m`;
- the same selected-plan route fingerprint at the scoring callback.

Missing keys, unresolved rows, changed routes, extra callbacks, missing
callbacks, reordered callbacks, duplicate callbacks, and non-finite values
fail closed. None becomes a numeric zero.

## Canonical base boundary

| Field | Value |
|---|---:|
| Car component rows | 67,718 |
| resolved private-car rows | 64,789 |
| motorcycle out-of-scope/null rows | 2,929 |
| legal zero-distance energy rows | 33 |
| base representative rate | 2.3260259843327393 HKD/km |
| resolved base cost total | 2,341,793.9504491785 HKD |
| resolved mean / median / p90 | 36.14493124526044 / 28.861846791369157 / 76.4376128255154 HKD |

The source has no individual powertrain assignment. Stage 8A therefore uses
only the already-published representative licensed-fleet average; it does not
invent a person-level petrol/electric branch.

## Scoring and duplicate prevention

`HongKongCarEnergyScoring` adds the negative monetary utility exactly once
from `handleLeg`. Money-event, external-event, trip, and arbitrary score
callbacks are inert, and the component emits no `PersonMoneyEvent`.

The standard Car `monetaryDistanceRate` must already be exactly zero when the
component factory is created. A nonzero value is rejected. Stage 8A neither
changes that parameter nor calls the existing `-0.0007/m` snapshot HKD,
fuel, or any other economic quantity. This fail-closed precondition prevents
a second distance monetary term without adopting a new interpretation.

`fixed_vehicle_ownership_cost` remains an accounting sidecar. Toll and
destination parking load zero runtime rows and contribute zero callbacks.
Motorcycle records retain null/out-of-scope source cost; consuming such an
ordinal records exclusion and creates no fabricated private-car charge.

## Composition and evidence

From Stage 8B, the canonical combined component registry still has three
unique mode owners:

```text
car  -> car_marginal_cost_v1
pt   -> pt_fare_layered_v1
taxi -> taxi_route_fare_v1
```

The Car owner records energy and confirmed toll as distinct exactly-once
subcomponents. See `docs/HONG_KONG_CAR_TOLL_RUNTIME.md`.

Taxi and PT component behavior is unchanged. The source release manifest
remains immutable historical/offline provenance; the scoped Stage 8A approval
is recorded only in the authoritative integrated consumer manifest:

- `data/transport_costs/hongkong/integrated_multimodal_cost_source_interface_manifest_v1.json`
- `data/transport_costs/hongkong/integration_stage8a_validation_v1/stage8a_car_energy_runtime_validation.json`
- `data/transport_costs/hongkong/integration_stage8a_validation_v1/car_energy_runtime_boundary_matrix.csv`

Stage 8A performs deterministic compile, unit/integration tests, source
release validation, and structured checks only. No Hong Kong scenario,
Runner, server task, or behavioral calibration is authorized or performed.
