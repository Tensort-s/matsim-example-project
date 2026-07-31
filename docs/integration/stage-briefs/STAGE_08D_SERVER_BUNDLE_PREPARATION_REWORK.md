# Stage 8D — Exact-tree source-snapshot bounded rework

| Field | Value |
|---|---|
| Exact input | `3a56bcd14db3c6f815bbc5ac77901c24947b3ae4` |
| Owner | `INT-EXECUTOR` only |
| Authority | `INT-SUPERVISOR` |
| Runner | not authorized |
| Status | `PENDING_INDEPENDENT_REVIEW_AND_SUPERVISOR_STAGE_8D_GATE` |

## Objective

Add a source-snapshot identity mode after a Runner proved that the permitted
server has no exact-SHA checkout. The new mode must transfer and build the
locked `3a56bcd…` runtime without creating server Git metadata and without
repeating the failed checkout-identity hypothesis.

## Authorized result

- exact seven-file input inventory and SHA256 fail-closed checks;
- stale v1/pre-Ferry path rejection;
- original exact clean Git-checkout guard retained unchanged;
- `git archive` snapshot locked to source commit
  `3a56bcd14db3c6f815bbc5ac77901c24947b3ae4` and tree
  `d3d57d61f39ba9d3377a915fc28ad9eeaff0deb9`;
- out-of-band manifest SHA, archive SHA and 7,620-entry
  path/mode/blob/size/SHA256 verification before and after extraction;
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
