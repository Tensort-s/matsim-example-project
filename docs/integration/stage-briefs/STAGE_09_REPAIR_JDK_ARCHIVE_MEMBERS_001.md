# Stage 9 repair — JDK archive legal metadata members

## Control identity

- Task ID: `STAGE9-REPAIR-JDK-ARCHIVE-MEMBERS-001`
- Blocker ID: `STAGE9-JDK-LEGAL-MEMBER-CONTRACT-001`
- Exact input SHA: `fe6a216c91a3d871fee0d58672868127fc2482a0`
- Repair owner: `INT-EXECUTOR`
- Dispatch/gate owner: `INT-SUPERVISOR`
- Runner authorized: `false`
- Stage 9 execution authorized: `false`

Stable governance is defined by
[`INTEGRATION_POLICY.md`](../INTEGRATION_POLICY.md). Canonical task state is in
[`CURRENT_STAGE.md`](../CURRENT_STAGE.md).

## Objective

Repair the bundle preparation contract so the approved Linux JDK 25.0.3
archive can safely materialize required `legal/*` metadata hard links while
retaining every existing archive-safety and runtime dependency-closure guard.
This is a bounded deployment-contract repair, not a Stage 9 run.

## Failure identity and root cause

The Stage 9 attempt using source
`fe6a216c91a3d871fee0d58672868127fc2482a0` stopped before producing a bundle,
release or MATSim process. The hash-locked archive
`69264a7a211bf5029830d07bc3370f879769d62ebc5b5488e90c9343a2da0e1f`
contains `legal/jdk.jshell/ADDITIONAL_LICENSE_INFO` as legal metadata linked to
another archive member. The prior validator rejected every member that was not
a directory or regular file before creating `runtime/jdk-25`.

The superseded identities are:

- staging: `/mnt/DiskM/by/hk_stage9_fe6a216_staging1`;
- release: `/mnt/DiskM/by/hk_multimodal_cost_fe6a216_stage9_release1`;
- run: the stopped Stage 9 attempt at source `fe6a216c...`.

## Allowed implementation

- Update the bundle preparation archive validator/materializer.
- Update its deterministic runtime-JDK contract validator.
- Add compact structured validation evidence.
- Update this brief, its index, canonical current state, and append-only
  Supervisor/Executor worklogs.

No Java model or scoring code, MATSim configuration or input, Taxi/PT/Car
semantics, server state, bundle contents on the server, Runner action, Stage 9
execution, formal run, or Stage 10 work is allowed.

## Bounded archive contract

A hard-link member is accepted only when all of the following hold:

- the link path and its target are relative safe paths under the single
  approved `jdk-25*` archive root;
- both paths are below `legal/`;
- the target is an existing direct regular file, not another link;
- neither the link entry nor target has executable bits;
- extraction copies the target bytes into a new regular file at the legal
  metadata path.

Absolute paths, traversal, backslashes, multiple or unexpected roots,
symbolic links, devices, non-legal hard links, missing targets, hard-link
chains and executable legal metadata continue to fail closed. The archive hash
is verified before extraction. `runtime/jdk-25/bin/java` must remain a regular,
executable file and report exactly Java `25.0.3`.

## Hard gates and evidence

- Exact parent/input, branch and protected refs match the authorization.
- Approved archive SHA remains unchanged.
- Deterministic validation accepts/materializes the representative approved
  legal metadata link and rejects every unsafe class above.
- The existing snapshot, seven locked-input, config-boundary and runtime-class
  bundle validator remains passing.
- Changed paths remain within bundle preparation, validation evidence,
  documentation and append-only worklogs.
- JSON/Python/link checks, `git diff --check`, conflict scan, clean worktree and
  local/tracking/remote equality pass.

Durable evidence:

- [`stage9_jdk_legal_member_repair_validation.json`](../../../data/transport_costs/hongkong/integration_stage9_repair_validation_v1/stage9_jdk_legal_member_repair_validation.json)
- [`validate_hong_kong_matsim_runtime_jdk_contract.py`](../../../scripts/hong_kong_single_city/run/validate_hong_kong_matsim_runtime_jdk_contract.py)

## Replacement identity and stop conditions

Any later retry requires the reviewed repair source SHA plus new staging,
release and run identities. A new directory alone is insufficient; the source
commit and repaired dependency-closure contract must change. The superseded
staging and release paths above must not be reused.

Stop on archive hash drift, unsafe or ambiguous member semantics, missing or
wrong Java executable/version, model/config/input change, server access,
protected-ref change, destructive Git, Runner request, or Stage 10 work.
