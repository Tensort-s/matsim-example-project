# Stage 8A — Car fuel-or-electricity runtime component

| Field | Value |
|---|---|
| Exact input | `d8fda87eda176f46dd00763709f56b530383476f` |
| Owner | `INT-EXECUTOR` only |
| Authority | `INT-SUPERVISOR` |
| Runner | not authorized |
| Status | `PENDING_INDEPENDENT_REVIEW_AND_SUPERVISOR_STAGE_8A_GATE` |

## Objective

Activate only the canonical base-scenario Car `fuel_or_electricity` marginal
component in the composable scoring architecture. Preserve Taxi and PT,
exclude fixed ownership and motorcycles, and leave toll and destination
parking inactive.

## Authorized result

- SHA-locked canonical base energy catalog;
- exact `person_id + leg_sequence`, route-distance and fingerprint matching;
- exactly-once `handleLeg` charging with inert money/event/trip callbacks;
- fail-closed missing/unresolved/non-finite behavior;
- explicit zero standard Car distance-rate precondition;
- focused tests, deterministic evidence, relevant documentation and
  append-only worklogs.

## Boundaries

No toll or destination-parking activation; no motorcycle-as-private-car
fallback; no fixed ownership leg cost; no new rate, currency, fare, utility,
ASC, calibration, imputation, config, plan, supply, demand, capacity, city
metadata, run manifest, Runner, MATSim/server run, Stage 8B/8C/9+, master, or
protected-feature change.

## Evidence

- [`../../../data/transport_costs/hongkong/integration_stage8a_validation_v1/stage8a_car_energy_runtime_validation.json`](../../../data/transport_costs/hongkong/integration_stage8a_validation_v1/stage8a_car_energy_runtime_validation.json)
- [`../../../data/transport_costs/hongkong/integration_stage8a_validation_v1/car_energy_runtime_boundary_matrix.csv`](../../../data/transport_costs/hongkong/integration_stage8a_validation_v1/car_energy_runtime_boundary_matrix.csv)
- [`../../HONG_KONG_CAR_ENERGY_RUNTIME.md`](../../HONG_KONG_CAR_ENERGY_RUNTIME.md)

## Next action

Executor pushes one exact result and reports only to Supervisor. Supervisor
verifies and dispatches Reviewer. Executor does not begin Stage 8B/8C/9 or
contact Reviewer.
