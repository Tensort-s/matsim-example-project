# Current integration stage

This is the canonical compact active-task record. Stable rules are in
[`INTEGRATION_POLICY.md`](INTEGRATION_POLICY.md); lane identity and write
scope are in [`agent-lanes.md`](../../agent-lanes.md).

| Field | Value |
|---|---|
| task_id | `Stage 8D - Dynamic exact-SHA snapshot identity rework` |
| status | `PENDING_INDEPENDENT_REVIEW_AND_SUPERVISOR_STAGE_8D_GATE` |
| exact_input_sha | `c9fc2410fd329c9aceef16b3b7ce627bb74dedb6` |
| control_protocol_01_status | `PASS_CLOSED` |
| stage_8c_source_status | `PUSHED_AT_INPUT_SHA` |
| authorized_owner | `INT-EXECUTOR` only |
| authority_source | `INT-SUPERVISOR` only |
| runner_authorized | `false` |
| stage_9_authorized | `false` |
| brief | [`stage-briefs/STAGE_08D_SERVER_BUNDLE_PREPARATION_REWORK.md`](stage-briefs/STAGE_08D_SERVER_BUNDLE_PREPARATION_REWORK.md) |
| validation | [`../../data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_bundle_preparation_rework_validation.json`](../../data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_bundle_preparation_rework_validation.json) |

## Objective

Remove prior-commit self-locking from Git-metadata-free snapshot identity. The
formal exact SHA is supplied at execution time; its Git commit object, tree,
blob inventory, archive and extracted files must verify as one identity while
the original exact-clean-Git guard remains strict.

## Authorized delta

- exact seven-file current input inventory and SHA256 checks;
- stale v1/pre-Ferry path rejection;
- exact clean Git checkout or dynamic exact-SHA snapshot source identity;
- Git commit-object hash and commit-tree reconstruction;
- snapshot archive/manifest/file integrity and tamper rejection;
- unchanged Taxi/PT/Car fat-JAR inventory checks;
- external deployment manifest and Linux JDK 25 build interface;
- deployment documentation, evidence and append-only worklogs.

## Forbidden delta

Java/model logic, fare or cost semantics, economic parameters, MATSim input
configuration, plans, network, schedule, vehicles, facilities, demand,
supply, capacity, city metadata or run manifest; JDK download/fabrication;
server access/build/upload/run or source transfer; Runner; Stage 9 retry;
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
