# Current integration stage

This is the canonical compact active-task record. Stable rules are in
[`INTEGRATION_POLICY.md`](INTEGRATION_POLICY.md); lane identity and write
scope are in [`agent-lanes.md`](../../agent-lanes.md).

| Field | Value |
|---|---|
| task_id | `Stage 8D - External locked-input-pack rework` |
| status | `PENDING_INDEPENDENT_REVIEW_AND_SUPERVISOR_STAGE_8D_GATE` |
| exact_input_sha | `7cb827453c7327d0b3636a7f594091523309309f` |
| control_protocol_01_status | `PASS_CLOSED` |
| stage_8c_source_status | `PUSHED_AT_INPUT_SHA` |
| authorized_owner | `INT-EXECUTOR` only |
| authority_source | `INT-SUPERVISOR` only |
| runner_authorized | `false` |
| stage_9_authorized | `false` |
| brief | [`stage-briefs/STAGE_08D_SERVER_BUNDLE_PREPARATION_REWORK.md`](stage-briefs/STAGE_08D_SERVER_BUNDLE_PREPARATION_REWORK.md) |
| validation | [`../../data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_bundle_preparation_rework_validation.json`](../../data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_bundle_preparation_rework_validation.json) |

## Objective

Support a separately transferred external data root containing exactly the
seven locked v2/Ferry Core inputs. Its source SHA, sidecar manifest SHA,
relative paths and file hashes must verify before bundle staging while source
snapshot and exact-clean-Git contracts remain unchanged.

## Authorized delta

- exact seven-file current input inventory and SHA256 checks;
- stale v1/pre-Ferry path rejection;
- exact clean Git checkout or dynamic exact-SHA snapshot source identity;
- Git commit-object hash and commit-tree reconstruction;
- snapshot archive/manifest/file integrity and tamper rejection;
- external locked-input-pack creation/verification and fail-closed manifest;
- exact seven-path inventory with missing/extra/stale/hash rejection;
- unchanged Taxi/PT/Car fat-JAR inventory checks;
- external deployment manifest and Linux JDK 25 build interface;
- deployment documentation, evidence and append-only worklogs.

## Forbidden delta

Java/model logic, fare or cost semantics, economic parameters, MATSim input
configuration, plans, network, schedule, vehicles, facilities, demand,
supply, capacity, city metadata or run manifest; JDK download/fabrication;
server access/build/upload/run or production source/input transfer; Runner;
Stage 9 retry;
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
