# Current integration stage

This is the canonical compact active-task record. Stable rules are in
[`INTEGRATION_POLICY.md`](INTEGRATION_POLICY.md); lane identity and write
scope are in [`agent-lanes.md`](../../agent-lanes.md).

| Field | Value |
|---|---|
| task_id | `STAGE8D-R1-JDK-RUNTIME-CLOSURE` |
| blocker_id | `STAGE9-RUNTIME-JDK-MISSING-001` |
| blocker_status | `REPAIR_DISPATCHED` |
| status | `PENDING_INDEPENDENT_REVIEW_AND_SUPERVISOR_STAGE_8D_R1_GATE` |
| exact_input_sha | `5f40aee6e1988b11fa1a35836065bef99b130191` |
| control_protocol_01_status | `PASS_CLOSED` |
| stage_8c_source_status | `PUSHED_AT_INPUT_SHA` |
| authorized_owner | `INT-EXECUTOR` only |
| authority_source | `INT-SUPERVISOR` only |
| runner_authorized | `false` |
| superseded_stage_9_status | `BLOCKED_SUPERSEDED_BY_REPAIR` |
| stage_9_authorized | `false` |
| brief | [`stage-briefs/STAGE_08D_R1_JDK_RUNTIME_CLOSURE.md`](stage-briefs/STAGE_08D_R1_JDK_RUNTIME_CLOSURE.md) |
| validation | [`../../data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_r1_jdk_runtime_closure_validation.json`](../../data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_r1_jdk_runtime_closure_validation.json) |
| server_evidence | [`../../data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_server_bundle_evidence.json`](../../data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_server_bundle_evidence.json) |

## Objective

Materialize the approved JDK archive into `runtime/jdk-25`, prove the launcher
executable and exact Java 25.0.3 version, and reject an archive-only or stale
runtime release before any later deployment is accepted.

## Authorized delta

- bundle-preparation runtime-JDK extraction and fail-closed preflight;
- a focused deterministic validator, structured evidence and deployment docs;
- faithful append-only Supervisor and Executor worklog entries;
- no server access, bundle production/upload or MATSim execution.

## Forbidden delta

Java/model logic, fare or cost semantics, economic parameters, MATSim input
configuration, plans, network, schedule, vehicles, facilities, demand,
supply, capacity, city metadata or run manifest; JDK download/fabrication;
server access/build/upload/run or production source/input transfer; Runner
action; Stage 9 retry;
master or protected feature changes; Git metadata creation on the server.

## Evidence references

- Deployment contract: `docs/HONG_KONG_MATSIM_SERVER_BUNDLE_STAGE8D.md`
- Structured implementation evidence:
  `data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_r1_jdk_runtime_closure_validation.json`
- Preparation entry point:
  `scripts/hong_kong_single_city/run/prepare_hong_kong_matsim_server_bundle.py`

## Next action

Executor reports the exact pushed repair SHA and compact handoff only to
Supervisor and stops. The blocker remains `REPAIR_DISPATCHED` pending
Supervisor exact-SHA verification and Reviewer dispatch. Runner and Stage 9
remain unauthorized.
