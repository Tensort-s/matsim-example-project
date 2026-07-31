# Stage 8D — External locked-input-pack rework

| Field | Value |
|---|---|
| Exact input | `7cb827453c7327d0b3636a7f594091523309309f` |
| Owner | `INT-EXECUTOR` only |
| Authority | `INT-SUPERVISOR` |
| Runner | not authorized |
| Status | `PENDING_INDEPENDENT_REVIEW_AND_SUPERVISOR_STAGE_8D_GATE` |

## Objective

Add a separate, manifest-bound external data root for the seven ignored large
v2/Ferry Core inputs after the exact source snapshot and Linux JDK 25 JAR build
succeeded but the tracked snapshot correctly lacked those input bytes. The
pack must verify before bundle staging without changing any input or runtime
semantic.

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
- `data_root_mode=external_locked_input_pack` beside the preserved canonical
  local data-root mode;
- pack create/verify interfaces with exact source SHA and out-of-band sidecar
  SHA256;
- exact seven-path/hash inventory and rejection of missing, mismatched, extra,
  symlinked or stale-v1/pre-Ferry files;
- verified pack root/manifest/command/result recorded in deployment metadata
  and a manifest copy retained in the bundle.

## Boundaries

No Java/model/config/input change, server access, transfer, JDK download,
upload, deployment, Runner, MATSim run, Stage 9 retry, Git metadata creation,
master or feature-ref change.

## Evidence

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

Executor pushes one focused external-pack contract result and reports only to
Supervisor. Supervisor verifies and dispatches Reviewer. Runner and Stage 9
remain unauthorized.
