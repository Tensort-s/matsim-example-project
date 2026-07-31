# Stage 8D — Exact-SHA server bundle preparation rework

| Field | Value |
|---|---|
| Exact input | `67f812ab544b9842c65c4da9073ee8e58d10bc31` |
| Owner | `INT-EXECUTOR` only |
| Authority | `INT-SUPERVISOR` |
| Runner | not authorized |
| Status | `PENDING_INDEPENDENT_REVIEW_AND_SUPERVISOR_STAGE_8D_GATE` |

## Objective

Correct only the deployment preparation path so a later authorized Runner can
build and package the exact pushed runtime against the locked v2 demand and
Ferry Core inputs.

## Authorized result

- exact seven-file input inventory and SHA256 fail-closed checks;
- stale v1/pre-Ferry path rejection;
- exact clean source-SHA and current Taxi/PT/Car JAR-class checks;
- sidecar deployment-manifest contract with build, version and bundle
  provenance;
- Linux JDK 25 build interface without downloading or fabricating a JDK;
- documentation, validation evidence and append-only worklogs.

## Boundaries

No Java/model/config/input change, server access, JDK download, upload,
deployment, Runner, MATSim run, Stage 9 retry, master or feature-ref change.

## Evidence

- [`../../../data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_bundle_preparation_rework_validation.json`](../../../data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_bundle_preparation_rework_validation.json)
- [`../../HONG_KONG_MATSIM_SERVER_BUNDLE_STAGE8D.md`](../../HONG_KONG_MATSIM_SERVER_BUNDLE_STAGE8D.md)
- [`../../../scripts/hong_kong_single_city/run/prepare_hong_kong_matsim_server_bundle.py`](../../../scripts/hong_kong_single_city/run/prepare_hong_kong_matsim_server_bundle.py)

## Next action

Executor pushes one exact control/deployment-preparation result and reports
only to Supervisor. Supervisor verifies and dispatches Reviewer. Runner and
Stage 9 remain unauthorized.
