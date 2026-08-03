# Stage 8D-R1 — JDK runtime dependency closure

| Field | Value |
|---|---|
| Task ID | `STAGE8D-R1-JDK-RUNTIME-CLOSURE` |
| Blocker ID | `STAGE9-RUNTIME-JDK-MISSING-001` |
| Exact input | `5f40aee6e1988b11fa1a35836065bef99b130191` |
| Owner | `INT-EXECUTOR` only |
| Authority | `INT-SUPERVISOR` |
| Runner authorized | `false` |
| Stage 9 status | `BLOCKED_SUPERSEDED_BY_REPAIR` |

## Objective

Close the known producer-to-consumer dependency gap: a new bundle must
materialize the approved Linux JDK archive at `runtime/jdk-25`, and both bundle
preparation and the launcher must fail closed unless `bin/java` is executable
and reports exactly Java `25.0.3`.

## Authorized implementation

- verify the approved archive SHA256 before creating the runtime target;
- accept one safe JDK 25 archive root containing an executable `bin/java`;
- extract only regular files/directories into a new `runtime/jdk-25` target;
- reject traversal, absolute paths, links, devices, collisions, stale roots,
  missing executables, pre-existing targets and wrong versions;
- preserve runtime executable modes in the final tar and inspect the produced
  tar for the launcher-required member;
- record archive, extraction, executable and version results in deployment
  metadata and the deployment manifest;
- repeat executable/version checks in the worker before MATSim starts.

The approved archive remains hash-locked to
`69264a7a211bf5029830d07bc3370f879769d62ebc5b5488e90c9343a2da0e1f`.
This repair does not download or substitute a JDK.

## Hard boundaries

No Java model, MATSim config/input, cost semantics, economic parameters,
server state, upload, Runner action or Stage 9 execution changes. The original
release/run identity is superseded and cannot be retried unchanged. A later
bundle/release requires separate Supervisor authorization and a replacement
identity.

## Evidence

- [`stage8d_r1_jdk_runtime_closure_validation.json`](../../../data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_r1_jdk_runtime_closure_validation.json)
- [`prepare_hong_kong_matsim_server_bundle.py`](../../../scripts/hong_kong_single_city/run/prepare_hong_kong_matsim_server_bundle.py)
- [`validate_hong_kong_matsim_runtime_jdk_contract.py`](../../../scripts/hong_kong_single_city/run/validate_hong_kong_matsim_runtime_jdk_contract.py)
- [`HONG_KONG_MATSIM_SERVER_BUNDLE_STAGE8D.md`](../../HONG_KONG_MATSIM_SERVER_BUNDLE_STAGE8D.md)

The deterministic fixture covers the success path and nine fail-closed cases.
Because Windows does not preserve Linux executable bits, only the fixture's
post-extraction executable predicate is injected; production execution retains
the real filesystem mode check, while archive and bundle tar executable modes
are always validated directly.

## Next action

Executor pushes one focused repair commit and reports only to Supervisor.
Supervisor verifies exact SHA/parent before dispatching Reviewer. Runner and
Stage 9 remain unauthorized.
