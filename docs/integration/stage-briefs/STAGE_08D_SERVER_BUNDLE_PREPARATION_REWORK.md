# Stage 8D — Runner evidence path correction

| Field | Value |
|---|---|
| Exact input | `9b1ea88680423694d6f09bccc7473acc1452b373` |
| Owner | `INT-EXECUTOR` only |
| Authority | `INT-SUPERVISOR` |
| Runner | completed PASS; no new action authorized |
| Status | `PENDING_INDEPENDENT_REVIEW_AND_SUPERVISOR_STAGE_8D_GATE` |

## Objective

Correct the Reviewer-blocking null artifact paths using only the exact
read-only path discovery transferred from Runner through Supervisor. Preserve
all existing hashes, the prepared-manifest false/false versus independent
upload true distinction, and the no-MATSim/QSim/Stage 9 boundary.

## Authorized result

- exact non-null source archive/manifest/root/script, pack root/manifest,
  build root/JAR, deployment-manifest and upload-evidence paths;
- evidence-by-reference updates in the deployment document, current-stage
  record and this brief;
- append-only Supervisor, Runner and Executor audit entries;
- no server log, JAR, source archive, input pack or bundle copied into Git.

## Boundaries

No Java/model/config/input change; no new server access, transfer, JDK action,
upload, deployment, Runner or MATSim run; no Stage 9 retry, Git metadata
creation, master or feature-ref change.

## Evidence

The authoritative compact server result is
[`stage8d_server_bundle_evidence.json`](../../../data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_server_bundle_evidence.json).
It records every Supervisor-transferred Runner hash and result by field,
including source tree/entry count, seven input hashes, toolchain, build
duration/RSS, JAR/bundle/deployment/upload hashes, exact verified server paths,
release paths and the no-run boundary. Runner performed only read-only path
discovery for this correction; Executor made no server access.

The deterministic pack fixture uses source
`7cb827453c7327d0b3636a7f594091523309309f`, all seven locked files and
sidecar SHA256
`80a763efd0f056fbb155a97cbb68b6a371fbb25cf3c9cf5a7a9017b27e47d3af`.
Two runs reproduced that manifest hash. The valid pack and `build-bundle`
input resolution pass; wrong source/manifest, missing, mismatched, extra and
stale-v1 cases fail closed. The fixture is temporary and no production pack
or server path was created.

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

Executor pushes one focused Runner-evidence result and reports only to
Supervisor. Supervisor verifies and dispatches Reviewer. Runner and Stage 9
remain unauthorized.
