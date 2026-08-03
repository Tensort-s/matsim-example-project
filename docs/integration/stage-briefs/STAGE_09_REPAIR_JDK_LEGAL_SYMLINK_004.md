# Stage 9 repair — diagnosed JDK legal symlink

## Control identity

- Task ID: `STAGE9-REPAIR-JDK-LEGAL-SYMLINK-004`
- Blocker ID: `STAGE9-JDK-LEGAL-REGULAR-CONTRACT-002`
- Exact input SHA: `7796154241518e4fb13b29f345b20bef0d91e9a2`
- Repair owner: `INT-EXECUTOR`
- Gate owner: `INT-SUPERVISOR`
- Runner authorized: `false`
- Stage 9 execution authorized: `false`

Stable rules are in [`INTEGRATION_POLICY.md`](../INTEGRATION_POLICY.md), and
canonical task state is in [`CURRENT_STAGE.md`](../CURRENT_STAGE.md).

## Diagnosed failure and objective

Read-only diagnosis proved that the approved archive member
`jdk-25.0.3+9/legal/jdk.jshell/ADDITIONAL_LICENSE_INFO` is a symbolic link:
type `b'2'`, mode `0777`, size `0`, no PAX headers, and target
`../java.base/ADDITIONAL_LICENSE_INFO`. The exact preparation script and JDK
archive hashes matched the authorized identities. Durable server diagnosis is
`/mnt/DiskM/by/hk_stage9_77961542_diag1/diagnosis.json` with SHA256
`a86521620e00c917150f10c037f13b741e924782e13d95a9108408d181cc80f1`.

The objective is to materialize this bounded legal metadata reference as an
ordinary file without weakening archive-path or runtime dependency closure.
No bundle, release, smoke or MATSim process was produced by the failed attempt.

## Allowed implementation

- Update only JDK archive validation/materialization and its deterministic
  validator.
- Add compact validation evidence.
- Update this brief, the brief index, canonical current state, and append-only
  Supervisor/Executor worklogs.

No Java model/runtime, MATSim config or input, Taxi/PT/Car cost semantics,
server state, Runner action, Stage 9 execution, or Stage 10 work is allowed.

## Safe symlink contract

A symbolic link is accepted only when its member path is below `legal/`, its
link name is relative, and normalization from the link member's parent remains
below `legal/` in the one validated JDK root. Its normalized target must be an
existing direct, non-executable regular `legal/*` archive member. Target bytes
are copied to a newly created ordinary output file; no symlink is emitted.

The diagnosed `../java.base/...` contains an internal parent step but
normalizes from `legal/jdk.jshell/` to `legal/java.base/`; parent steps that
escape `legal/` or the archive root remain invalid.

The contract rejects absolute targets, unsafe traversal, non-legal links or
targets, missing targets, link chains, directories/devices, executable legal
targets, unsafe hard links, duplicate collisions, and unexpected roots.
`runtime/jdk-25/bin/java` remains a regular executable and must report Java
`25.0.3` after exact archive-hash verification.

## Hard gates and evidence

- Parent/input, branch, protected refs and approved JDK SHA are exact.
- The diagnosed type/mode/size/link target fixture is accepted and copied as
  an ordinary file.
- Adversarial symlink, special-member, hardlink, collision, Java executable
  and version guards pass deterministically.
- The existing source-snapshot, seven-input, stale-input and bundle contract
  validator remains passing.
- Changed paths stay within preparation, validation, evidence, documentation
  and append-only worklogs.
- Python/JSON/link/diff/conflict checks and clean ref identity pass.

Evidence:

- [`stage9_jdk_legal_symlink_repair_validation.json`](../../../data/transport_costs/hongkong/integration_stage9_repair_004_validation_v1/stage9_jdk_legal_symlink_repair_validation.json)
- [`validate_hong_kong_matsim_runtime_jdk_contract.py`](../../../scripts/hong_kong_single_city/run/validate_hong_kong_matsim_runtime_jdk_contract.py)

## Replacement identity and stop conditions

The partial staging directory
`/mnt/DiskM/by/hk_stage9_77961542_staging2` remains preserved and must not be
reused or cleaned. Any later attempt requires a reviewed new source SHA, new
staging root, new release root and new run identity under separate Supervisor
authorization.

Stop on any archive hash/type ambiguity, unsafe target, model/config/input or
server change, protected-ref drift, Runner request, or Stage 10 work.
