# Current integration stage

This is the canonical compact active-task record. Stable rules are in
[`INTEGRATION_POLICY.md`](INTEGRATION_POLICY.md); lane identity and write
scope are in [`agent-lanes.md`](../../agent-lanes.md).

| Field | Value |
|---|---|
| task_id | `Stage 8D - Runner evidence path correction` |
| status | `PENDING_INDEPENDENT_REVIEW_AND_SUPERVISOR_STAGE_8D_GATE` |
| exact_input_sha | `9b1ea88680423694d6f09bccc7473acc1452b373` |
| control_protocol_01_status | `PASS_CLOSED` |
| stage_8c_source_status | `PUSHED_AT_INPUT_SHA` |
| authorized_owner | `INT-EXECUTOR` only |
| authority_source | `INT-SUPERVISOR` only |
| runner_authorized | `false` |
| runner_stage_8d_result | `PASS_EVIDENCE_TRANSFERRED_NO_RUN` |
| stage_9_authorized | `false` |
| brief | [`stage-briefs/STAGE_08D_SERVER_BUNDLE_PREPARATION_REWORK.md`](stage-briefs/STAGE_08D_SERVER_BUNDLE_PREPARATION_REWORK.md) |
| validation | [`../../data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_bundle_preparation_rework_validation.json`](../../data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_bundle_preparation_rework_validation.json) |
| server_evidence | [`../../data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_server_bundle_evidence.json`](../../data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_server_bundle_evidence.json) |

## Objective

Replace the three previously null artifact-location fields and add the exact
read-only-discovered source, pack, build, JAR, deployment-manifest and upload
evidence paths supplied by Runner through Supervisor. Preserve every reviewed
hash and the explicit no-MATSim/QSim/Stage 9 run boundary.

## Authorized delta

- path-only corrections to the compact Stage 8D server-bundle evidence JSON;
- deployment-document/current-stage/brief evidence references;
- faithful append-only Supervisor, Runner and Executor worklog entries;
- no copied server logs, JAR, source snapshot, input pack or bundle.

## Forbidden delta

Java/model logic, fare or cost semantics, economic parameters, MATSim input
configuration, plans, network, schedule, vehicles, facilities, demand,
supply, capacity, city metadata or run manifest; JDK download/fabrication;
new server access/build/upload/run or production source/input transfer;
Runner action; Stage 9 retry;
master or protected feature changes; Git metadata creation on the server.

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
