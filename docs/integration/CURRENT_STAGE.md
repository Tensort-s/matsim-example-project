# Current integration stage

This is the canonical compact active-task record. Stable rules are in
[`INTEGRATION_POLICY.md`](INTEGRATION_POLICY.md); lane identity and write
scope are in [`agent-lanes.md`](../../agent-lanes.md).

| Field | Value |
|---|---|
| task_id | `Stage 8D - Exact-SHA server bundle preparation rework` |
| status | `PENDING_INDEPENDENT_REVIEW_AND_SUPERVISOR_STAGE_8D_GATE` |
| exact_input_sha | `67f812ab544b9842c65c4da9073ee8e58d10bc31` |
| control_protocol_01_status | `PASS_CLOSED` |
| stage_8c_source_status | `PUSHED_AT_INPUT_SHA` |
| authorized_owner | `INT-EXECUTOR` only |
| authority_source | `INT-SUPERVISOR` only |
| runner_authorized | `false` |
| stage_9_authorized | `false` |
| brief | [`stage-briefs/STAGE_08D_SERVER_BUNDLE_PREPARATION_REWORK.md`](stage-briefs/STAGE_08D_SERVER_BUNDLE_PREPARATION_REWORK.md) |
| validation | [`../../data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_bundle_preparation_rework_validation.json`](../../data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_bundle_preparation_rework_validation.json) |

## Objective

Correct only the server bundle preparation path so a later separately
authorized Runner can build and package the exact pushed runtime with the
locked v2 demand and Ferry Core inputs.

## Authorized delta

- exact seven-file current input inventory and SHA256 checks;
- stale v1/pre-Ferry path rejection;
- exact clean source-SHA and Taxi/PT/Car fat-JAR inventory checks;
- external deployment manifest and Linux JDK 25 build interface;
- deployment documentation, evidence and append-only worklogs.

## Forbidden delta

Java/model logic, fare or cost semantics, economic parameters, MATSim input
configuration, plans, network, schedule, vehicles, facilities, demand,
supply, capacity, city metadata or run manifest; JDK download/fabrication;
server access/build/upload/run; Runner; Stage 9 retry; master or protected
feature changes.

## Evidence references

- Deployment contract: `docs/HONG_KONG_MATSIM_SERVER_BUNDLE_STAGE8D.md`
- Structured implementation evidence:
  `data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_bundle_preparation_rework_validation.json`
- Preparation entry point:
  `scripts/hong_kong_single_city/run/prepare_hong_kong_matsim_server_bundle.py`

## Next action

Executor reports the exact pushed SHA and compact handoff only to Supervisor
and stops. Supervisor verifies and, if appropriate, dispatches Reviewer.
Runner and Stage 9 remain unauthorized.
