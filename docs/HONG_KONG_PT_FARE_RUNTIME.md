# Hong Kong layered PT fare runtime

## Authority and status

Stage 7 activates one canonical PT fare scoring component for explicit,
prepared `TransitPassengerRoute` segments. The exact Stage 7 input is
`176484d2be98664d280375c1d595c953d7d3163d`; the result remains pending
independent exact-SHA review and the Supervisor Stage 7 gate.

The source release remains unchanged at:

```text
data/transport_costs/hongkong/pt_fare_v1/
```

Its `canonical_pt_fare_interface_manifest.json` continues to describe the
locked offline source release. Runtime-consumer approval is recorded only in
the authoritative integrated manifest:

```text
data/transport_costs/hongkong/
  integrated_multimodal_cost_source_interface_manifest_v1.json
```

This distinction preserves Stage 2 source evidence without allowing its stale
offline consumer status to control the superseding Stage 7 architecture.

## Canonical composition

The combined scoring entry point is:

```text
org.matsim.project.hongkong.scoring.
  HongKongMultimodalCostScoringModule
```

It installs the standard MATSim delegate and exactly two custom components:

| Mode owner | Component |
|---|---|
| `pt` | `pt_fare_layered_v1` |
| `taxi` | `taxi_route_fare_v1` |

Car is absent. `HongKongTaxiScoringModule` remains the Taxi-only equivalence
and historical-smoke entry point; it does not control the combined Stage 7
composition.

## Five runtime layers

`HongKongPtFareRuntimeCatalog` verifies five Parquet and five exact-crosswalk
SHA-256 identities before loading any rule. It then exposes only:

| Runtime layer | Rule rows | Available / unresolved | Quality | Exact key |
|---|---:|---:|---|---|
| domestic MTR | 9,216 | 9,216 / 0 | B | ordered station OD |
| Light Rail | 4,624 | 4,624 / 0 | B | ordered stop OD |
| GMB | 97,521 | 96,866 / 655 | B/U | line + route + ordered stop OD |
| Ferry | 60 | 60 / 0 | B/C | line + route + ordered stop OD |
| Bus Core | 754,133 | 754,133 / 0 | B | line + route + ordered stop OD |

The 655 GMB unresolved rows remain 361 conflicts and 294 identical
duplicates. No candidate is selected. Airport Express is not a Stage 7
runtime layer; domestic MTR never crosses into that scope. Bus Core never
falls back to `bus_fare_simulation_v1`.

The complete quality/fallback matrix is:

```text
data/transport_costs/hongkong/integration_stage7_validation_v1/
  pt_runtime_layer_quality_fallback_matrix.csv
```

## Request construction and null policy

For each selected prepared PT leg, the runtime schedule reads:

- transit mode from the referenced schedule route;
- exact MATSim line and route IDs;
- exact access and segment-egress facility IDs;
- exact official stop/station IDs from the corresponding canonical
  crosswalk.

Chained routes use the next chained segment's access stop as the current
segment egress. This prevents the MATSim convenience accessor for the final
chain egress from collapsing an intermediate transfer.

If a reference, crosswalk, or exact rule is missing, the segment retains:

```text
cost_hkd = null
cost_quality = U
mapping_status = unresolved
unresolved_reason = <explicit reason>
```

The score remains finite because no numeric fare is fabricated. Available
segments in the same chain retain their independently proven charges; an
incomplete whole-chain total is never represented as complete.

The original 557,104 generic source PT rows remain 0 priced and 557,104
unresolved with null `cost_hkd`. They are not rewritten. Runtime lookup is
possible only after standard PrepareForSim has supplied explicit itinerary
references.

## Charging and duplicate prevention

`HongKongPtPersonFareSchedule` snapshots the selected prepared plan and stores
PT leg ordinals plus route fingerprints. `HongKongPtFareScoring` accepts each
experienced `mode=pt,routingMode=pt` leg once and in that order.

- an extra callback fails closed;
- missing scheduled callbacks fail at `finish()`;
- a route-fingerprint mismatch fails closed;
- each chained segment is quoted once in chain order;
- `addMoney`, event and trip callbacks are inert for this component;
- no `PersonMoneyEvent` is emitted;
- transfer concessions remain null and `not_modelled`.

Resolved fare HKD is converted to score with the existing MATSim
`marginalUtilityOfMoney`. Stage 7 does not change that parameter. The factory
also requires the existing standard PT `monetaryDistanceRate` to be exactly
zero and fails rather than mutating it, preventing a parallel distance-money
charge.

## Explicitly prohibited behavior

The runtime has no distance median, cross-mode aggregation, nearest neighbour,
reverse lookup, path sum, route `fullFare`, Bus simulation-candidate, or
unresolved-to-zero path. It introduces no fare, transfer-concession,
passenger/payment, ASC, calibration, demand, capacity, supply, or Car-cost
assumption.

`cities/hongkong/city.yaml` and `runs/hongkong/run_manifest.json` remain
unchanged because Stage 7 adopts no production config, input, output, or run.
No Hong Kong MATSim/server run occurred.

## Validation

Durable evidence is in:

```text
data/transport_costs/hongkong/integration_stage7_validation_v1/
  stage7_pt_fare_runtime_validation.json
  pt_runtime_layer_quality_fallback_matrix.csv
```

Implementation checks cover exact source hashes/counts, representative quotes
for all five layers, unresolved/null behavior, chained transfers, callback
duplicate prevention, finite scores, zero standard PT monetary-distance
charge, combined Guice registration, Taxi regression, Stage 6 itinerary
regression, and the canonical PT release validator.
