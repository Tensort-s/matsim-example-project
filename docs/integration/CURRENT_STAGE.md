# Current integration stage

This is the canonical compact active-task record. Stable rules are in
[`INTEGRATION_POLICY.md`](INTEGRATION_POLICY.md); lane identity and write
scope are in [`agent-lanes.md`](../../agent-lanes.md).

| Field | Value |
|---|---|
| task_id | `Stage 7 - PT fare runtime layered integration` |
| status | `PENDING_INDEPENDENT_REVIEW_AND_SUPERVISOR_STAGE_7_GATE` |
| exact_input_sha | `176484d2be98664d280375c1d595c953d7d3163d` |
| control_protocol_01_status | `PASS_CLOSED` |
| stage_6_status | `PASS_CLOSED` |
| authorized_owner | `INT-EXECUTOR` only |
| authority_source | `INT-SUPERVISOR` only |
| runner_authorized | `false` |
| stage_8_authorized | `false` |
| brief | [`stage-briefs/STAGE_07_PT_FARE_RUNTIME_LAYERED_INTEGRATION.md`](stage-briefs/STAGE_07_PT_FARE_RUNTIME_LAYERED_INTEGRATION.md) |
| validation | [`../../data/transport_costs/hongkong/integration_stage7_validation_v1/stage7_pt_fare_runtime_validation.json`](../../data/transport_costs/hongkong/integration_stage7_validation_v1/stage7_pt_fare_runtime_validation.json) |

## Objective

Activate one strict five-layer PT fare component for explicit prepared
itineraries while preserving Taxi equivalence, unresolved/null policy,
transfer-concession boundaries, and offline Car status.

## Authorized delta

- hash-locked domestic MTR, Light Rail, GMB, Ferry, and Bus Core catalog;
- selected-plan PT fare schedule, component/factory and combined Guice module;
- deterministic null, quality, traceability and duplicate-prevention tests;
- relevant PT/integration documentation, evidence and append-only worklogs.

## Forbidden delta

New fare/transfer/economic assumptions; generic PT fare inference; Bus
simulation candidate or Airport Express cross-scope fallback; Car scoring;
MATSim configuration, plans, network, schedule, vehicles, facilities, demand,
supply, capacity, city metadata or run manifest; Runner/server/Hong Kong
MATSim execution; Stage 8+; and master or protected-feature changes.

## Evidence references

- Runtime policy: `docs/HONG_KONG_PT_FARE_RUNTIME.md`
- Structured implementation evidence:
  `data/transport_costs/hongkong/integration_stage7_validation_v1/stage7_pt_fare_runtime_validation.json`
- Layer quality/fallback matrix:
  `data/transport_costs/hongkong/integration_stage7_validation_v1/pt_runtime_layer_quality_fallback_matrix.csv`

## Next action

Executor reports the exact pushed SHA and compact handoff only to Supervisor
and stops. Supervisor verifies and, if appropriate, dispatches Reviewer.
Runner and Stage 8 remain unauthorized.
