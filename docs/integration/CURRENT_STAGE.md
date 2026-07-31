# Current integration stage

This is the canonical compact active-task record. Stable rules are in
[`INTEGRATION_POLICY.md`](INTEGRATION_POLICY.md); lane identity and write
scope are in [`agent-lanes.md`](../../agent-lanes.md).

| Field | Value |
|---|---|
| task_id | `Stage 8A - Car fuel_or_electricity runtime component` |
| status | `PENDING_INDEPENDENT_REVIEW_AND_SUPERVISOR_STAGE_8A_GATE` |
| exact_input_sha | `d8fda87eda176f46dd00763709f56b530383476f` |
| control_protocol_01_status | `PASS_CLOSED` |
| stage_7_status | `PASS_CLOSED` |
| authorized_owner | `INT-EXECUTOR` only |
| authority_source | `INT-SUPERVISOR` only |
| runner_authorized | `false` |
| stage_8b_8c_or_9_authorized | `false` |
| brief | [`stage-briefs/STAGE_08A_CAR_ENERGY_RUNTIME.md`](stage-briefs/STAGE_08A_CAR_ENERGY_RUNTIME.md) |
| validation | [`../../data/transport_costs/hongkong/integration_stage8a_validation_v1/stage8a_car_energy_runtime_validation.json`](../../data/transport_costs/hongkong/integration_stage8a_validation_v1/stage8a_car_energy_runtime_validation.json) |

## Objective

Activate only the hash-locked canonical base Car `fuel_or_electricity`
component while preserving Taxi/PT behavior, explicit null/out-of-scope
motorcycles, and inactive toll, parking and fixed ownership.

## Authorized delta

- hash-locked canonical base Car energy catalog;
- exact selected-plan source-key, route-distance and fingerprint guards;
- one Car energy component/factory in the combined Guice composition;
- deterministic duplicate, null, motorcycle, fixed-exclusion and finite tests;
- relevant Car/integration documentation, evidence and append-only worklogs.

## Forbidden delta

Toll or destination-parking runtime; motorcycle-as-private-car fallback;
fixed ownership in scoring; a new rate/currency/utility interpretation;
unresolved zero fill; MATSim configuration, plans, network, schedule,
vehicles, facilities, demand, supply, capacity, city metadata or run manifest;
Runner/server/Hong Kong MATSim execution; Stage 8B/8C/9+; and master or
protected-feature changes.

## Evidence references

- Runtime policy: `docs/HONG_KONG_CAR_ENERGY_RUNTIME.md`
- Structured implementation evidence:
  `data/transport_costs/hongkong/integration_stage8a_validation_v1/stage8a_car_energy_runtime_validation.json`
- Runtime boundary matrix:
  `data/transport_costs/hongkong/integration_stage8a_validation_v1/car_energy_runtime_boundary_matrix.csv`

## Next action

Executor reports the exact pushed SHA and compact handoff only to Supervisor
and stops. Supervisor verifies and, if appropriate, dispatches Reviewer.
Runner and Stage 8B/8C/9 remain unauthorized.
