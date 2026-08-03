# CONTROL-PROTOCOL-07 — Diagnosis confidence and budget

## Control identity

- Task ID: `CONTROL-PROTOCOL-07-DIAGNOSIS-CONFIDENCE-AND-BUDGET`
- Exact input SHA: `e12f81b27c8a70f373654ca46dac1cb7ef17bb5e`
- Gate owner: `INT-SUPERVISOR`
- Repository writer: `INT-EXECUTOR`
- Runner authorized: `false`
- Stage 9 execution authorized: `false`
- Stage 10 or later authorized: `false`

Stable authority remains canonical in
[`INTEGRATION_POLICY.md`](../INTEGRATION_POLICY.md), and current state is in
[`CURRENT_STAGE.md`](../CURRENT_STAGE.md).

## Consumed Protocol 06 gate

This atomic transition consumes Reviewer `PASS` for exact Protocol 06 SHA
`e12f81b27c8a70f373654ca46dac1cb7ef17bb5e` and closes
`CONTROL-PROTOCOL-06-POST-FAILURE-DIAGNOSIS-AUTO-DISPATCH` as `PASS_CLOSED`.
This is not a closure-only commit: the same transition adds the prospective
machine-checkable confidence and resource-budget contract below.

## Machine-checkable diagnosis confidence

Every post-failure Runner handoff includes:

```yaml
diagnosis_confidence:
  exact_failure_identity_matched: true | false
  direct_failure_condition_observed: true | false
  causal_chain_demonstrated: true | false
  material_alternatives_checked: true | false
  repair_hypothesis_testable: true | false
  root_cause_status: KNOWN | PARTIAL | UNKNOWN
```

`KNOWN` is valid only when all five Boolean evidence conditions are `true`.
The inspected artifacts must match the authorized failed identity; the failing
condition must be observed directly; evidence must demonstrate how it caused
the error; material alternative explanations must be checked; and a bounded
repair hypothesis must have an explicit verification metric. A first
exception, stack trace, log correlation or symptom alone never proves
`KNOWN`.

`PARTIAL` applies when a highly plausible cause lacks a complete causal chain,
material alternatives remain, the repair hypothesis lacks a decisive metric,
or the diagnosis budget expires before sufficient evidence is obtained.

`UNKNOWN` applies when no verifiable direct cause is found, only symptoms can
be described, or multiple material explanations remain equally plausible.
Supervisor may not promote `PARTIAL` or `UNKNOWN` to `KNOWN` without new
evidence satisfying every Boolean gate.

## Default read-only diagnosis budget

Every automatic `POST_FAILURE_READ_ONLY_DIAGNOSIS` starts with:

```yaml
diagnosis_budget:
  wall_clock_minutes_max: 30
  shell_commands_max: 30
  filesystem_roots_max: 6
  evidence_output_mb_max: 30
  full_server_recursive_scan_allowed: false
  existing_state_mutation_allowed: false
```

Inspection is limited to the failed release/run directories, staging/build
directories directly referenced by that identity, paths named by the
deployment manifest, and the current command/classpath/config/input paths.
Runner may not recursively scan all of `/mnt/DiskM/by`, copy large archives,
JARs, inputs or outputs as evidence, install tools, mutate/move/delete/clean
existing files, change a command and rerun, or alter Git or the server
environment.

Evidence is kept compact: paths, SHA256, sizes, permissions, short log
excerpts, member-inventory summaries and structured JSON. Full large logs or
binary copies require a later separately authorized diagnosis task.

## Budget-result and dispatch contract

The Runner handoff also includes:

```yaml
diagnosis_budget_result:
  elapsed_minutes: number
  commands_used: number
  roots_inspected: number
  evidence_output_bytes: number
  budget_exhausted: true | false
  missing_evidence: []
```

Runner stops when any budget limit is reached and does not enlarge scope. The
Supervisor dispatch is:

- `KNOWN` with all five gates true: bounded Executor repair.
- `PARTIAL`: a more specific bounded diagnosis task.
- `UNKNOWN`: a bounded diagnosis task that narrows the problem or changes the
  evidence source.
- Research or policy question: `ESCALATED_TO_USER`.

For each `PARTIAL`/`UNKNOWN` result Supervisor may create exactly one new
diagnosis task. It names a new task ID, missing evidence, new scope and budget,
and why that evidence could change the conclusion. It must not repeat the same
diagnostic commands and scope. No automatic dispatch authorizes Runner, a
retry or Stage 9 execution.

## Worked example: thin-JAR evidence chain

1. `NoClassDefFoundError` alone yields `PARTIAL`, not `KNOWN`.
2. Read-only inspection proves the deployed JAR lacks
   `AbstractModule.class`.
3. The exact build-root Shade JAR contains that class.
4. Bundle/release SHA and path evidence proves `target/` thin JAR was copied.
5. JDK, configuration and locked inputs are checked and excluded as material
   alternatives.
6. The bounded hypothesis—select the root Shade JAR—has decisive JAR-SHA and
   class-loading-preflight metrics.
7. Only after all five confidence gates are true does status become `KNOWN`.

## Hard gates and stop conditions

Only governance, canonical current state, indexes and append-only worklogs may
change. No bundle preparation or validator code, model/cost semantics, MATSim
configuration/input, server/bundle/release/run state, Runner authorization,
Stage 9 execution or Stage 10 work is permitted.

Stop on subjective promotion to `KNOWN`, unbounded diagnosis, budget expansion
without a new task, repeated diagnostic identity, historical-worklog rewrite,
runtime/server mutation, or a verdict-only/closure-only follow-up commit.
