# Stage 8C — Car resolved destination-parking runtime component

| Field | Value |
|---|---|
| Exact input | `4ab83c79959bf4ccaa7d36cd6567b61cd84494b0` |
| Owner | `INT-EXECUTOR` only |
| Authority | `INT-SUPERVISOR` |
| Runner | not authorized |
| Status | `PENDING_INDEPENDENT_REVIEW_AND_SUPERVISOR_STAGE_8C_GATE` |

## Objective

Add only canonical resolved base destination parking beside accepted Car
energy and confirmed toll, with exact destination/source identity, explicit
quality, null-preserving unresolved handling and exactly-once scoring.

## Authorized result

- hash-locked base destination-parking component, candidate, rules and event
  sources;
- distinct resolved charge, documented home marginal zero, unresolved and
  motorcycle behavior;
- exact key, destination, activity, time, route, fingerprint, ordinal and
  callback guards;
- one `car_marginal_cost_v1` owner containing energy, toll and parking;
- focused tests, deterministic evidence, relevant documentation and
  append-only worklogs.

## Boundaries

No new parking tariff, duration, location or economic interpretation; no
unresolved zero or nearest/candidate/distance inference; no fixed ownership,
motorcycle-as-private-car, config, plan, supply, demand, capacity, city
metadata, run manifest, Runner, MATSim/server run, Stage 9+, master or
protected-feature change.

## Evidence

- [`../../../data/transport_costs/hongkong/integration_stage8c_validation_v1/stage8c_car_destination_parking_runtime_validation.json`](../../../data/transport_costs/hongkong/integration_stage8c_validation_v1/stage8c_car_destination_parking_runtime_validation.json)
- [`../../../data/transport_costs/hongkong/integration_stage8c_validation_v1/parking_runtime_resolution_matrix.csv`](../../../data/transport_costs/hongkong/integration_stage8c_validation_v1/parking_runtime_resolution_matrix.csv)
- [`../../HONG_KONG_CAR_PARKING_RUNTIME.md`](../../HONG_KONG_CAR_PARKING_RUNTIME.md)

## Next action

Executor pushes one exact result and reports only to Supervisor. Supervisor
verifies and dispatches Reviewer. Executor does not begin Stage 9 or contact
Reviewer.
