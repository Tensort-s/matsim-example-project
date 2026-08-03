# CONTROL-PROTOCOL-06 — Post-failure diagnosis and automatic dispatch

## Control identity

- Task ID: `CONTROL-PROTOCOL-06-POST-FAILURE-DIAGNOSIS-AUTO-DISPATCH`
- Exact input SHA: `a72f8cac53b5798cc8468c1297db82dd1aed633c`
- Gate owner: `INT-SUPERVISOR`
- Repository writer: `INT-EXECUTOR`
- Reviewer: read-only, after Supervisor dispatch
- Runner authorized: `false`
- Stage 9 execution authorized: `false`
- Stage 10 or later authorized: `false`

Stable authority and atomic-transition rules remain canonical in
[`INTEGRATION_POLICY.md`](../INTEGRATION_POLICY.md). Current state is in
[`CURRENT_STAGE.md`](../CURRENT_STAGE.md).

## Consumed repair gate

This transition consumes the Supervisor-transferred Reviewer `PASS` for exact
repair SHA `a72f8cac53b5798cc8468c1297db82dd1aed633c` and atomically closes:

- repair task `STAGE9-REPAIR-SHADED-JAR-DEPENDENCY-CLOSURE-005` as
  `PASS_CLOSED`;
- blocker `STAGE9-RUNTIME-DEPENDENCY-CLASSPATH-001` as `CLOSED`.

The release3/run3 failure remains historical
`BLOCKED_SUPERSEDED_BY_REPAIR`. Closure does not authorize Runner, a Stage 9
retry, deployment, upload, server mutation, or Stage 10 work.

## Runner post-failure read-only diagnosis

On any nonzero process exit or Hard Gate failure, Runner immediately stops the
run, modification and retry. The run enters
`POST_FAILURE_READ_ONLY_DIAGNOSIS`. Within a new append-only evidence
directory, Runner may only:

- read stdout, stderr, logs and manifests;
- inspect JAR, ZIP and TAR member inventories;
- inspect commands, classpaths, versions, paths and modes;
- calculate SHA256 and size, compare build/bundle/release/run artifacts, and
  verify locked config/input existence and hashes;
- write a new append-only evidence JSON describing those read-only checks.

Runner must not modify, replace, move or delete existing files; install
software or change the server environment; modify Git; change a command and
rerun it; clean failed directories; authorize Executor; close blockers; or
continue a failed run.

The Runner handoff must contain these fields:

```yaml
task_id: string
stage_id: string
source_sha: full_git_sha
run_identity: structured_identity
root_cause_status: KNOWN | PARTIAL | UNKNOWN
root_cause: concise_statement
evidence_refs: [durable_path_and_field]
repair_hypothesis: bounded_testable_change_or_null
rerun_performed: false
existing_state_modified: false
hard_gate_status: string
handoff_to: INT-SUPERVISOR
```

## Supervisor automatic dispatch

Supervisor consumes the diagnosis handoff and makes exactly one bounded next
dispatch:

- `KNOWN` plus an ordinary technical defect creates a bounded repair task for
  `INT-EXECUTOR`. Ordinary defects include classpath/JAR/dependency/packaging,
  compilation/Guice/path/manifest, hash/mode/deployment/server compatibility,
  log/config-read and other non-research runtime defects.
- `PARTIAL` or `UNKNOWN` creates a bounded read-only diagnosis task. Runner
  owns it only when server evidence is needed; Executor owns it only when
  repository evidence is needed.
- Economic or behavioral semantics, cost policy, demand/capacity,
  missing-data treatment or research interpretation transitions to
  `ESCALATED_TO_USER`.

Automatic repair never authorizes Runner. A repair requires an exact pushed
SHA and independent Reviewer `PASS`. Any replacement run requires a separate
exact-SHA Supervisor Runner instruction and a new source, bundle, release and
run identity. An identical failed identity is never repeated.

Supervisor remains the sole dispatch and gate authority; Executor remains the
sole Git writer; Reviewer remains read-only; Runner is limited to explicitly
authorized execution and post-failure read-only diagnosis. Every lane sends
handoffs only to Supervisor.

## Worked example: thin-JAR failure

1. Runner observes `NoClassDefFoundError` for
   `org/matsim/core/controler/AbstractModule` and stops without retry.
2. `POST_FAILURE_READ_ONLY_DIAGNOSIS` compares artifacts and reports
   `root_cause_status: KNOWN`: the bundle selected the `target/` thin JAR
   instead of the build-root Maven Shade JAR. `rerun_performed` and
   `existing_state_modified` are both `false`.
3. Supervisor automatically dispatches bounded repair
   `STAGE9-REPAIR-SHADED-JAR-DEPENDENCY-CLOSURE-005` to Executor with Runner
   unauthorized.
4. Executor pushes exact repair SHA
   `a72f8cac53b5798cc8468c1297db82dd1aed633c`; Reviewer returns `PASS` to
   Supervisor.
5. This atomic transition closes the repair and blocker. Release3/run3 remains
   `BLOCKED_SUPERSEDED_BY_REPAIR`.
6. No run follows automatically. Only a separate future Supervisor
   authorization naming a new source/bundle/release/run identity may execute.

## Hard gates and stop conditions

This task changes governance, current state, indexes and append-only worklogs
only. It changes no Java/Python runtime implementation, MATSim configuration,
plans, supply, locked inputs, bundle, release, server state, cost semantics or
protected ref.

Stop on any attempt to alter model or research policy, mutate server state,
authorize Runner or Stage 9 execution, begin Stage 10, rewrite worklog history,
repeat a failed identity, or create a closure-only follow-up commit.
