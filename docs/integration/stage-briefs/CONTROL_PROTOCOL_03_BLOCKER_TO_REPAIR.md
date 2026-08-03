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
  status: OPEN | DIAGNOSIS_DISPATCHED | REPAIR_DISPATCHED | UNDER_REVIEW | CLOSED | ESCALATED_TO_USER
  failure_identity: commit_bundle_config_input_command_runtime_identity
  root_cause: known_cause_or_unknown
  changed_hypothesis_required_for_retry: one_testable_change
  diagnosis_task_id: null_or_unique_task_id
  repair_task_id: null_or_unique_task_id
  repair_owner: null_or_lane_id
  replacement_identity_required: [commit, bundle, config, input, command, runtime_environment, dependency_closure]
  superseded_run_identity: exact_failed_identity
  missing_dispatch_escalation:
    emitted: false
    emitted_at: null_or_ISO-8601
    escalation_id: null_or_stable_unique_id
```

Supervisor creates or confirms `blocker_id` at the first accepted `BLOCKED`.
Canonical form is `STAGE-DOMAIN-ROOT_CAUSE-SEQUENCE`: uppercase, fixed field
order, spaces/slashes/underscores normalized to one hyphen, repeated separators
collapsed, and sequence zero-padded. The active-stage blocker record controls.
Heartbeat dedup keys are canonical `blocker_id` plus failure identity.

Timestamps, directories, log paths, attempt labels, case and separator changes
are non-substantive and reuse the ID. A diagnosis that refines `UNKNOWN` inside
the same observed causal class also keeps the ID. A new ID is created only for
a substantively different causal class or failure identity; a repaired
replacement candidate stays attached to the original blocker unless it fails
in a substantively different way.

The first record is `OPEN`. Unknown cause moves to `DIAGNOSIS_DISPATCHED` only
after Supervisor issues a formal diagnosis brief. Diagnosis never directly
authorizes rerun; Supervisor must issue a distinct repair task to enter
`REPAIR_DISPATCHED`. Known cause may move directly to `REPAIR_DISPATCHED`.
Executor push leaves the blocker `REPAIR_DISPATCHED` pending verification.
After Supervisor verifies exact output SHA/parent and dispatches Reviewer,
Supervisor records `UNDER_REVIEW`. Reviewer returns PASS/BLOCKED and evidence
only; Reviewer cannot close. Only Supervisor records `CLOSED`. A policy-owned
blocker becomes `ESCALATED_TO_USER`.

## Reviewer required transition

For a known, executable and verifiable technical repair:

```yaml
next_action_summary: Supervisor must create the bounded repair stage
required_transition:
  action: CREATE_REPAIR_STAGE
  blocker_id: stable_unique_id
  owner: INT-SUPERVISOR
  repair_owner: INT-EXECUTOR
  runner_authorized: false
```

For an unknown root cause, `action` is `CREATE_DIAGNOSIS_STAGE`. Reviewer sends
this structure only to Supervisor. It requests the mandatory control-plane
transition but does not authorize Executor or Runner. For technical `BLOCKED`,
this structure overrides ordinary CONTROL-PROTOCOL-02 short-action semantics.
It must not contradict `next_action_summary`.

## Heartbeat handling

- Same canonical `blocker_id` and identity with `DIAGNOSIS_DISPATCHED`,
  `REPAIR_DISPATCHED` or `UNDER_REVIEW`: silent dedup; do not report or dispatch
  the same action again.
- First repeat of `OPEN` with no diagnosis/repair task: emit
  `MISSING_REPAIR_DISPATCH`, set `missing_dispatch_escalation.emitted: true`,
  persist `emitted_at` and a stable `escalation_id` in the append-only worklog.
- Further identical `OPEN` heartbeats are silent because the persisted emitted
  flag proves the escalation already occurred. Formal dispatch records a state
  event but does not reset the exactly-once fields.
- Only a substantive root-cause or failure-identity change, or a formal
  dispatch, permits a new audit event. Cosmetic identity changes do not.

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

Executor submission records the pushed repair SHA as pending Supervisor
verification while status remains `REPAIR_DISPATCHED`. Only Supervisor can
move it to `UNDER_REVIEW`, after verifying exact SHA/parent and dispatching the
read-only Reviewer. Only Supervisor can later record `CLOSED`.

## Worked example — complete non-authorizing transition

This is a protocol example only. It does not instantiate a current Stage 9
blocker, create a JDK repair task, describe current server state, authorize a
retry, or authorize Runner.

### 1. OPEN and exactly-once escalation

Supervisor accepts a technical Stage 9 `BLOCKED` with unknown detailed cause,
creates the stable ID using the observed runtime/dependency causal class, and
records:

```yaml
blocker_id: STAGE9-RUNTIME-DEPENDENCY-001
status: OPEN
failure_identity:
  stage: Stage 9 joint short smoke
  source_commit: exact_sha_from_the_failed_authorization
  bundle: exact_bundle_sha_from_the_failed_authorization
  config: exact_config_sha_from_the_failed_authorization
  input: exact_input_manifest_sha_from_the_failed_authorization
  command: exact_launcher_command_from_the_failed_authorization
  runtime_environment: exact_environment_from_the_failed_authorization
root_cause: UNKNOWN_WITHIN_RUNTIME_DEPENDENCY_CLASS
changed_hypothesis_required_for_retry: diagnose launcher dependency closure
diagnosis_task_id: null
repair_task_id: null
repair_owner: null
replacement_identity_required: [commit, bundle, runtime_environment, dependency_closure]
superseded_run_identity: full_failure_identity_above
missing_dispatch_escalation:
  emitted: false
  emitted_at: null
  escalation_id: null
runner_authorized: false
```

The first repeated OPEN heartbeat with no dispatched task emits exactly once:

```yaml
blocker_id: STAGE9-RUNTIME-DEPENDENCY-001
status: OPEN
missing_dispatch_escalation:
  emitted: true
  emitted_at: exact_ISO-8601_from_the_escalation_event
  escalation_id: MISSING-REPAIR-DISPATCH-STAGE9-RUNTIME-DEPENDENCY-001
heartbeat_result: MISSING_REPAIR_DISPATCH_EMITTED
runner_authorized: false
```

Later identical heartbeats deduplicate silently by the same blocker ID plus
failure identity. They do not emit another escalation or audit entry.

### 2. DIAGNOSIS_DISPATCHED

Supervisor issues the distinct diagnosis task
`STAGE9D-RUNTIME-DEPENDENCY-001`. The prior Stage 9 becomes
`BLOCKED_SUPERSEDED_BY_DIAGNOSIS`; Runner remains false.

```yaml
blocker_id: STAGE9-RUNTIME-DEPENDENCY-001
status: DIAGNOSIS_DISPATCHED
prior_stage_status: BLOCKED_SUPERSEDED_BY_DIAGNOSIS
diagnosis_task_id: STAGE9D-RUNTIME-DEPENDENCY-001
repair_task_id: null
missing_dispatch_escalation:
  emitted: true
  emitted_at: exact_ISO-8601_from_the_escalation_event
  escalation_id: MISSING-REPAIR-DISPATCH-STAGE9-RUNTIME-DEPENDENCY-001
runner_authorized: false
```

Diagnosis finds that the released artifact lacks the runtime JDK
executable/path/version required by its launcher. This refines the same causal
class, so the blocker ID remains stable. Diagnosis never directly authorizes a
rerun.

### 3. REPAIR_DISPATCHED

Supervisor creates the distinct repair task
`STAGE9R-RUNTIME-JDK-DEPENDENCY-CLOSURE-001`; prior Stage 9 is now
`BLOCKED_SUPERSEDED_BY_REPAIR`.

```yaml
blocker_id: STAGE9-RUNTIME-DEPENDENCY-001
status: REPAIR_DISPATCHED
root_cause: launcher-required runtime JDK executable/path/version missing from released artifact
diagnosis_task_id: STAGE9D-RUNTIME-DEPENDENCY-001
repair_task_id: STAGE9R-RUNTIME-JDK-DEPENDENCY-CLOSURE-001
repair_owner: INT-EXECUTOR
prior_stage_status: BLOCKED_SUPERSEDED_BY_REPAIR
runner_authorized: false
```

Executor pushes the bounded repair from the authorized exact parent. The
replacement candidate changes commit/bundle/dependency closure, while config,
input and command may remain byte-identical. A new directory alone is not a
change. Executor reports the SHA, but status remains `REPAIR_DISPATCHED`:

```yaml
blocker_id: STAGE9-RUNTIME-DEPENDENCY-001
status: REPAIR_DISPATCHED
repair_output_sha: new_exact_repair_sha_pending_Supervisor_verification
replacement_identity:
  commit: new_exact_repair_sha
  bundle: new_exact_bundle_sha256
  dependency_closure: launcher_required_JDK_path_and_version_preflight_passed
runner_authorized: false
```

### 4. UNDER_REVIEW

Supervisor verifies the repair output exact SHA and parent, formally dispatches
the read-only Reviewer, and only then records:

```yaml
blocker_id: STAGE9-RUNTIME-DEPENDENCY-001
status: UNDER_REVIEW
review_dispatch_owner: INT-SUPERVISOR
reviewer_authority: PASS_BLOCKED_AND_EVIDENCE_ONLY
runner_authorized: false
```

Reviewer returns PASS/BLOCKED and evidence to Supervisor. Reviewer cannot set
`CLOSED` and cannot authorize a rerun.

### 5. CLOSED

After consuming Reviewer PASS, Supervisor alone records:

```yaml
blocker_id: STAGE9-RUNTIME-DEPENDENCY-001
status: CLOSED
closure_owner: INT-SUPERVISOR
closure_gate: reviewed_dependency_closure_pass
runner_authorized: false
next_action_summary: await separate Supervisor replacement-run authorization
required_transition: null
```

`CLOSED` does not auto-authorize a retry. Runner remains false until a separate
Supervisor instruction names the replacement identity. If diagnosis instead
finds a user-owned policy choice, Supervisor records `ESCALATED_TO_USER` and no
repair or rerun is inferred.

CONTROL-PROTOCOL-03 is governance-only. It does not modify or retry Stage 9,
change a server or bundle, or authorize Runner.
