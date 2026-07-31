# Stage 7 — PT fare runtime layered integration

| Field | Value |
|---|---|
| Exact input | `176484d2be98664d280375c1d595c953d7d3163d` |
| Owner | `INT-EXECUTOR` only |
| Authority | `INT-SUPERVISOR` |
| Runner | not authorized |
| Status | `PENDING_INDEPENDENT_REVIEW_AND_SUPERVISOR_STAGE_7_GATE` |

## Objective

Activate one canonical `pt` scoring component over the five approved strict
fare layers for explicit prepared itineraries, preserve Taxi equivalence, and
keep Car offline.

## Authorized result

- exact SHA-locked Parquet/crosswalk runtime catalog;
- domestic MTR, Light Rail, GMB, Ferry, and Bus Core lookups;
- selected-plan ordinal and route-fingerprint consumption;
- chained-segment ordering, explicit unresolved/null evidence, and inert
  money/event/trip callbacks;
- combined Taxi + PT Guice composition, tests, evidence, documentation and
  append-only worklogs.

## Boundaries

No Bus simulation candidate, Airport Express cross-scope use, transfer
concession, distance/reverse/path/full-fare fallback, unresolved zero, Car
activation, economic-parameter change, config/plans/supply change, Runner,
MATSim/server run, or Stage 8 work.

## Evidence

- [`../../../data/transport_costs/hongkong/integration_stage7_validation_v1/stage7_pt_fare_runtime_validation.json`](../../../data/transport_costs/hongkong/integration_stage7_validation_v1/stage7_pt_fare_runtime_validation.json)
- [`../../../data/transport_costs/hongkong/integration_stage7_validation_v1/pt_runtime_layer_quality_fallback_matrix.csv`](../../../data/transport_costs/hongkong/integration_stage7_validation_v1/pt_runtime_layer_quality_fallback_matrix.csv)
- [`../../HONG_KONG_PT_FARE_RUNTIME.md`](../../HONG_KONG_PT_FARE_RUNTIME.md)

## Next action

Executor pushes one exact result and reports only to Supervisor. Supervisor
verifies and dispatches Reviewer. Executor does not begin Stage 8 or contact
Reviewer.
