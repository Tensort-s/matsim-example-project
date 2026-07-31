# Stage 8D — Dynamic exact-SHA snapshot identity rework

| Field | Value |
|---|---|
| Exact input | `c9fc2410fd329c9aceef16b3b7ce627bb74dedb6` |
| Owner | `INT-EXECUTOR` only |
| Authority | `INT-SUPERVISOR` |
| Runner | not authorized |
| Status | `PENDING_INDEPENDENT_REVIEW_AND_SUPERVISOR_STAGE_8D_GATE` |

## Objective

Remove the self-lock loop after Runner correctly rejected the hardcoded prior
`6ce087af…` source. The Supervisor/Runner command supplies the exact source
SHA dynamically; Git-backed creation and Git-free verification must prove it
without weakening any existing guard.

## Authorized result

- exact seven-file input inventory and SHA256 fail-closed checks;
- stale v1/pre-Ferry path rejection;
- original exact clean Git-checkout guard retained unchanged;
- no hardcoded expected source commit/tree/count/inventory constant;
- Git-backed create embeds the exact commit object and derives its tree and
  complete deterministic path/mode/blob/size/SHA256 inventory;
- verification recomputes the commit-object SHA, requires equality with the
  formal exact-SHA argument and reconstructs that commit's tree;
- out-of-band manifest SHA and archive/extracted-file verification;
- prior source identity rejected when it does not match the formal exact SHA;
- wrong commit/tree/manifest/archive/file/stale-input rejection;
- current Taxi/PT/Car JAR-class checks;
- sidecar deployment-manifest contract with build, version and bundle
  provenance;
- Linux JDK 25 build interface without downloading or fabricating a JDK;
- documentation, validation evidence and append-only worklogs.

## Boundaries

No Java/model/config/input change, server access, transfer, JDK download,
upload, deployment, Runner, MATSim run, Stage 9 retry, Git metadata creation,
master or feature-ref change.

## Evidence

- [`../../../data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_bundle_preparation_rework_validation.json`](../../../data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_bundle_preparation_rework_validation.json)
- [`../../HONG_KONG_MATSIM_SERVER_BUNDLE_STAGE8D.md`](../../HONG_KONG_MATSIM_SERVER_BUNDLE_STAGE8D.md)
- [`../../../scripts/hong_kong_single_city/run/prepare_hong_kong_matsim_server_bundle.py`](../../../scripts/hong_kong_single_city/run/prepare_hong_kong_matsim_server_bundle.py)

## Next action

Executor pushes one exact control/deployment-preparation result and reports
only to Supervisor. Supervisor verifies and dispatches Reviewer. Runner and
Stage 9 remain unauthorized.
