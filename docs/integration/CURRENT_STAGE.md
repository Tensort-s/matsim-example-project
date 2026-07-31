# Current integration stage

This is the canonical compact active-task record. Stable rules are in
[`INTEGRATION_POLICY.md`](INTEGRATION_POLICY.md); lane identity and write
scope are in [`agent-lanes.md`](../../agent-lanes.md).

| Field | Value |
|---|---|
| task_id | `Stage 8B - Car confirmed toll runtime component` |
| status | `PENDING_INDEPENDENT_REVIEW_AND_SUPERVISOR_STAGE_8B_GATE` |
| exact_input_sha | `5cc8aaaca0f5d5e073fff2792a29ed929c372139` |
| control_protocol_01_status | `PASS_CLOSED` |
| stage_8a_status | `PASS_CLOSED` |
| authorized_owner | `INT-EXECUTOR` only |
| authority_source | `INT-SUPERVISOR` only |
| runner_authorized | `false` |
| stage_8c_or_9_authorized | `false` |
| brief | [`stage-briefs/STAGE_08B_CAR_CONFIRMED_TOLL_RUNTIME.md`](stage-briefs/STAGE_08B_CAR_CONFIRMED_TOLL_RUNTIME.md) |
| validation | [`../../data/transport_costs/hongkong/integration_stage8b_validation_v1/stage8b_car_confirmed_toll_runtime_validation.json`](../../data/transport_costs/hongkong/integration_stage8b_validation_v1/stage8b_car_confirmed_toll_runtime_validation.json) |

## Objective

Add only hash-locked confirmed base Car toll beside the accepted energy
subcomponent while preserving Taxi/PT, explicit legal-zero/null boundaries,
and inactive parking, fixed ownership, and motorcycles.

## Authorized delta

- hash-locked canonical base toll, identification, and passage-event sources;
- confirmed-charge/no-charge separation and fail-closed unresolved handling;
- one Car owner with energy and toll subcomponents;
- deterministic source, route, facility-link, duplicate and finite tests;
- relevant Car/integration documentation, evidence and append-only worklogs.

## Forbidden delta

Unconfirmed toll inference; destination-parking runtime;
motorcycle-as-private-car fallback; fixed ownership in scoring; a new
rate/currency/utility interpretation; unresolved zero fill; MATSim
configuration, plans, network, schedule,
vehicles, facilities, demand, supply, capacity, city metadata or run manifest;
Runner/server/Hong Kong MATSim execution; Stage 8C/9+; and master or
protected-feature changes.

## Evidence references

- Runtime policy: `docs/HONG_KONG_CAR_TOLL_RUNTIME.md`
- Structured implementation evidence:
  `data/transport_costs/hongkong/integration_stage8b_validation_v1/stage8b_car_confirmed_toll_runtime_validation.json`
- Confirmation matrix:
  `data/transport_costs/hongkong/integration_stage8b_validation_v1/toll_runtime_confirmation_matrix.csv`

## Next action

Executor reports the exact pushed SHA and compact handoff only to Supervisor
and stops. Supervisor verifies and, if appropriate, dispatches Reviewer.
Runner and Stage 8C/9 remain unauthorized.
