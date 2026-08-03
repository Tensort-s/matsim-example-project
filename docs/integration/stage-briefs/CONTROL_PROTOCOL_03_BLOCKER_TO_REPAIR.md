# CONTROL-PROTOCOL-03 — Blocker-to-repair state transition

The canonical rules are
[`INTEGRATION_POLICY.md#blocker-to-repair-state-transition`](../INTEGRATION_POLICY.md#blocker-to-repair-state-transition).
This protocol extends the
[`CONTROL-PROTOCOL-02` review template](CONTROL_PROTOCOL_02_LEAN_DELTA_REVIEW.md)
without changing lane authority or authorizing Runner.

## Blocker record

```yaml
blocker:
  blocker_id: stable_unique_id
  status: OPEN | REPAIR_DISPATCHED | UNDER_REVIEW | CLOSED | ESCALATED_TO_USER
  failure_identity: commit_bundle_config_input_command_runtime_identity
  root_cause: known_cause_or_unknown
  changed_hypothesis_required_for_retry: one_testable_change
  repair_task_id: null_or_unique_task_id
  repair_owner: null_or_lane_id
  replacement_identity_required: [commit, bundle, config, input, command, runtime_environment, dependency_closure]
  superseded_run_identity: exact_failed_identity
```

The first record is `OPEN`. Supervisor changes it to `REPAIR_DISPATCHED` only
by issuing a formal repair/diagnosis brief. Executor submission changes it to
`UNDER_REVIEW`. Reviewer reports evidence to Supervisor; only Supervisor gate
closure changes it to `CLOSED`. A non-technical or policy-dependent blocker
becomes `ESCALATED_TO_USER`.

## Reviewer required transition

For a known, executable and verifiable technical repair:

```yaml
next_action:
  required_transition:
    action: CREATE_REPAIR_STAGE
    blocker_id: stable_unique_id
    owner: INT-SUPERVISOR
    repair_owner: INT-EXECUTOR
    runner_authorized: false
```

For an unknown root cause, `action` is `CREATE_DIAGNOSIS_STAGE`. Reviewer sends
this structure only to Supervisor. It requests the mandatory control-plane
transition but does not authorize Executor or Runner.

## Heartbeat handling

- Same `blocker_id` with `REPAIR_DISPATCHED` or `UNDER_REVIEW`: silent dedup;
  do not report or dispatch the same action again.
- Same `blocker_id` with `OPEN` and no `repair_task_id`: emit exactly one
  `MISSING_REPAIR_DISPATCH` escalation to Supervisor. Do not silently dedup.
- A changed failure identity or changed root-cause hypothesis is a new audit
  event; it is not concealed as a heartbeat.

## Repair-stage brief schema

```yaml
repair_stage:
  task_id: new_unique_task_id
  blocker_id: stable_unique_id
  exact_input_sha: full_git_sha
  allowed_paths: [bounded_paths]
  objective: one_executable_verifiable_repair
  hard_gates: [identity, scope, semantic_invariants, tests, protected_refs, cleanliness]
  evidence: [path#field]
  stop_conditions: [bounded_stops]
  replacement_run_identity_requirements:
    changed_dimensions: [commit_or_bundle_or_config_or_input_or_command_or_runtime_or_dependency_closure]
    new_directory_alone_is_sufficient: false
  runner_authorized: false
  handoff_target: INT-SUPERVISOR
```

When this brief exists, the prior stage is recorded as
`BLOCKED_SUPERSEDED_BY_REPAIR` and is no longer active. A separate Supervisor
authorization is required before any replacement run.

## Worked example — Stage 9 runtime JDK missing

This is a protocol example, not a Stage 9 authorization or claim about current
server state.

### 1. OPEN

```yaml
blocker_id: STAGE9-RUNTIME-JDK-MISSING-001
status: OPEN
failure_identity:
  stage: Stage 9 joint short smoke
  source_commit: exact_sha_from_the_failed_authorization
  bundle: exact_bundle_sha_from_the_failed_authorization
  config: exact_config_sha_from_the_failed_authorization
  input: exact_input_manifest_sha_from_the_failed_authorization
  command: exact_launcher_command_from_the_failed_authorization
  runtime_environment: permitted_host_release_with_launcher_required_JDK_missing
root_cause: released artifact lacks the runtime JDK executable/path/version required by its launcher
changed_hypothesis_required_for_retry: add and preflight the launcher-required JDK dependency closure in a new reviewed artifact
repair_task_id: null
repair_owner: null
replacement_identity_required: [commit, bundle, runtime_environment, dependency_closure]
superseded_run_identity: full_failure_identity_above
```

Reviewer returns `CREATE_REPAIR_STAGE` with owner `INT-SUPERVISOR`, repair
owner `INT-EXECUTOR`, and `runner_authorized: false`. Supervisor must not emit
another Stage 9 blocker heartbeat as the next action.

### 2. REPAIR_DISPATCHED

Supervisor issues task `STAGE9R-RUNTIME-JDK-DEPENDENCY-CLOSURE` from an exact
input SHA. Its objective is to place or bind the launcher-required JDK
executable/path/version in the released artifact and prove it through a
fail-closed preflight. The prior Stage 9 status becomes
`BLOCKED_SUPERSEDED_BY_REPAIR`. Runner remains unauthorized.

```yaml
blocker_id: STAGE9-RUNTIME-JDK-MISSING-001
status: REPAIR_DISPATCHED
prior_stage_status: BLOCKED_SUPERSEDED_BY_REPAIR
repair_task_id: STAGE9R-RUNTIME-JDK-DEPENDENCY-CLOSURE
repair_owner: INT-EXECUTOR
runner_authorized: false
```

### 3. UNDER_REVIEW

Executor pushes the bounded repair from the authorized exact parent. The new
identity changes the commit and bundle and records the verified JDK
executable/path/version dependency closure. Config, input and launcher command
may remain byte-identical and are cited as such. Merely choosing a new release
directory would not qualify. Supervisor dispatches exact-SHA review; Runner
remains unauthorized.

```yaml
blocker_id: STAGE9-RUNTIME-JDK-MISSING-001
status: UNDER_REVIEW
replacement_identity:
  commit: new_exact_repair_sha
  bundle: new_exact_bundle_sha256
  dependency_closure: launcher_required_JDK_path_and_version_preflight_passed
runner_authorized: false
```

### 4. CLOSED or escalation

After Reviewer PASS, Supervisor verifies the repair evidence and records
`CLOSED`. Only a separate Supervisor instruction may authorize Runner with the
replacement identity. If the repair instead requires a user-owned policy or
external-authority choice, Supervisor records `ESCALATED_TO_USER`; no retry is
authorized.

```yaml
blocker_id: STAGE9-RUNTIME-JDK-MISSING-001
status: CLOSED
closure_gate: reviewed_dependency_closure_pass
runner_authorized: false
next_action: await_separate_Supervisor_run_authorization
```

CONTROL-PROTOCOL-03 is governance-only. It does not modify or retry Stage 9,
change a server or bundle, or authorize Runner.
