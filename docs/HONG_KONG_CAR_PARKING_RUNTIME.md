# Hong Kong resolved destination-parking runtime

## Stage 8C scope

Stage 8C adds the canonical resolved destination-parking subcomponent beside
the accepted Car energy and confirmed-toll subcomponents:

```text
car -> car_marginal_cost_v1
       - car_fuel_or_electricity_v1
       - car_confirmed_toll_v1
       - car_destination_parking_v1
```

There remains exactly one top-level owner for mode `car`. Fixed vehicle
ownership is accounting-only, motorcycles remain out of scope, and an
unresolved destination-parking record contributes no fabricated numeric cost.

## Canonical source identity

`HongKongCarParkingCostCatalog` verifies the exact SHA256 of the canonical Car
manifest, base unified component table, component registry, base parking
candidate, parking rule repository and all-scenario parking-event table. Only
the locked `base` destination-parking values are loaded. Runtime does not add
or reinterpret a tariff, duration, location, currency or economic rule.

The locked source describes resolved values as
`official_rate_bounded_zone_activity_proxy`. This limitation is preserved as
source provenance: destination facility is not claimed to be an observed
parking facility. Runtime requires the exact audited destination identity and
source timing; it performs no nearest-location, facility-candidate, road-class
or distance inference.

## Resolution and null policy

| Canonical status | Rows | Runtime behavior |
|---|---:|---|
| `resolved_proxy_charge` | 35,564 | charge the canonical finite positive value exactly once |
| `resolved_home_marginal_zero_fixed_separate` | 28,390 | consume the documented legal zero; fixed costs stay separate |
| unresolved private car | 835 | retain null and the exact source reason; no charge or zero fill |
| motorcycle out of scope | 2,929 | retain null and never treat as private car |

The 835 unresolved rows comprise 466 vehicle-time overlaps, 269 next-departure
facility mismatches, 98 missing destination zones and 2 missing next
non-home departures. Resolved base parking totals 2,624,827 HKD; its
mean/median/p90/max are 41.04242111517653 / 32 / 110 / 210 HKD. These are
offline source distributions, not simulation results.

## Identity and duplicate guards

Every selected prepared Car leg must match the canonical `person_id +
leg_sequence`, destination facility and activity type, source departure and
travel times, applicable next-departure time, route fingerprint and
destination fingerprint. Missing, reordered, changed, ambiguous, duplicate or
non-finite input fails closed.

Only `handleLeg` may apply a resolved positive parking value. Selected-plan
ordinals are consumed exactly once; money, event, trip and external-score
callbacks are inert. The energy and toll scorers retain their existing exact
once guards. Standard Car `monetaryDistanceRate` must already be zero and is
neither mutated nor reinterpreted.

## Evidence

- `data/transport_costs/hongkong/integration_stage8c_validation_v1/stage8c_car_destination_parking_runtime_validation.json`
- `data/transport_costs/hongkong/integration_stage8c_validation_v1/parking_runtime_resolution_matrix.csv`
- `data/transport_costs/hongkong/integrated_multimodal_cost_source_interface_manifest_v1.json`

Stage 8C runs deterministic tests and release validators only. It changes no
production config, plans, network, supply, demand, capacity, city metadata,
run manifest or server output, and performs no Hong Kong scenario run.
