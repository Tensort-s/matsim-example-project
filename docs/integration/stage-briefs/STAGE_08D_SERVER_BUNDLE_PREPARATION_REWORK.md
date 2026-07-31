# Stage 8D — Full-tree snapshot evidence completeness rework

| Field | Value |
|---|---|
| Exact input | `cb40845886fd1447489ad9d8af52592c704de918` |
| Owner | `INT-EXECUTOR` only |
| Authority | `INT-SUPERVISOR` |
| Runner | not authorized |
| Status | `PENDING_INDEPENDENT_REVIEW_AND_SUPERVISOR_STAGE_8D_GATE` |

## Objective

Close the bounded evidence gate after the dynamic snapshot implementation was
accepted as sound but its full-tree archive and manifest hashes existed only
in the Executor handoff. Reproduce those values from the retained local
`c9fc241…` snapshot and commit the exact commands, hashes and verification
result without changing production logic or deployment state.

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

The committed validation JSON records the independently reproduced full-tree
snapshot evidence for source `c9fc2410fd329c9aceef16b3b7ce627bb74dedb6`:
tree `3114228a02931c2d7b43a18c971649653d9ceb66`, 7,620 tracked
files, blob-inventory SHA256
`e4f95f66f6d2ce27de4827125c09e42c990f69e954321d223f7320ac77d05324`,
archive SHA256
`34209c954c598a1d374f48d3b18bc4925a2d764ce197104063c0cb2ed78477eb`
and manifest SHA256
`c5e9ed1ac0c59c99fb9ac385404a2317367f4484ca31ea83f04c6006f904cb7b`.
The snapshot was local validation evidence only and was not transferred or
deployed.

- [`../../../data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_bundle_preparation_rework_validation.json`](../../../data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_bundle_preparation_rework_validation.json)
- [`../../HONG_KONG_MATSIM_SERVER_BUNDLE_STAGE8D.md`](../../HONG_KONG_MATSIM_SERVER_BUNDLE_STAGE8D.md)
- [`../../../scripts/hong_kong_single_city/run/prepare_hong_kong_matsim_server_bundle.py`](../../../scripts/hong_kong_single_city/run/prepare_hong_kong_matsim_server_bundle.py)

## Next action

Executor pushes one focused evidence-completeness result and reports only to
Supervisor. Supervisor verifies and dispatches Reviewer. Runner and Stage 9
remain unauthorized.
