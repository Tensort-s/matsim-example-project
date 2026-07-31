# Current integration stage

This is the canonical compact active-task record. Stable rules are in
[`INTEGRATION_POLICY.md`](INTEGRATION_POLICY.md); lane identity and write
scope are in [`agent-lanes.md`](../../agent-lanes.md).

| Field | Value |
|---|---|
| task_id | `Stage 8C - Car resolved destination parking runtime component` |
| status | `PENDING_INDEPENDENT_REVIEW_AND_SUPERVISOR_STAGE_8C_GATE` |
| exact_input_sha | `4ab83c79959bf4ccaa7d36cd6567b61cd84494b0` |
| control_protocol_01_status | `PASS_CLOSED` |
| stage_8b_status | `PASS_CLOSED` |
| authorized_owner | `INT-EXECUTOR` only |
| authority_source | `INT-SUPERVISOR` only |
| runner_authorized | `false` |
| stage_9_authorized | `false` |
| brief | [`stage-briefs/STAGE_08C_CAR_DESTINATION_PARKING_RUNTIME.md`](stage-briefs/STAGE_08C_CAR_DESTINATION_PARKING_RUNTIME.md) |
| validation | [`../../data/transport_costs/hongkong/integration_stage8c_validation_v1/stage8c_car_destination_parking_runtime_validation.json`](../../data/transport_costs/hongkong/integration_stage8c_validation_v1/stage8c_car_destination_parking_runtime_validation.json) |

## Objective

Add only hash-locked resolved base destination parking beside accepted energy
and confirmed toll while preserving Taxi/PT, explicit legal-zero/null
boundaries, inactive fixed ownership, and out-of-scope motorcycles.

## Authorized delta

- hash-locked canonical base parking, rule, and event sources;
- resolved-charge, documented home-zero, unresolved and motorcycle separation;
- one Car owner with energy, toll and destination-parking subcomponents;
- deterministic destination, source-time, route, duplicate and finite tests;
- relevant Car/integration documentation, evidence and append-only worklogs.

## Forbidden delta

New parking tariff/location/duration inference; nearest or candidate fallback;
motorcycle-as-private-car fallback; fixed ownership in scoring; a new
rate/currency/utility interpretation; unresolved zero fill; MATSim
configuration, plans, network, schedule,
vehicles, facilities, demand, supply, capacity, city metadata or run manifest;
Runner/server/Hong Kong MATSim execution; Stage 9+; and master or
protected-feature changes.

## Evidence references

- Runtime policy: `docs/HONG_KONG_CAR_PARKING_RUNTIME.md`
- Structured implementation evidence:
  `data/transport_costs/hongkong/integration_stage8c_validation_v1/stage8c_car_destination_parking_runtime_validation.json`
- Resolution matrix:
  `data/transport_costs/hongkong/integration_stage8c_validation_v1/parking_runtime_resolution_matrix.csv`

## Next action

Executor reports the exact pushed SHA and compact handoff only to Supervisor
and stops. Supervisor verifies and, if appropriate, dispatches Reviewer.
Runner and Stage 9 remain unauthorized.
