# CONTROL-PROTOCOL-02 — Lean delta-only review template

The canonical rules are
[`INTEGRATION_POLICY.md#lean-delta-only-review-protocol`](../INTEGRATION_POLICY.md#lean-delta-only-review-protocol).
This template carries only the current review delta. It does not authorize
implementation, repair, a run or stage progression.

```yaml
review_dispatch:
  stage_id: string
  stage_brief: path#section
  exact_input_sha: full_git_sha
  exact_output_sha: full_git_sha
  expected_parent: full_git_sha
  delta_range: exact_input_sha..exact_output_sha
  allowed_paths: [path_or_pattern]
  hard_gates:
    identity_and_refs: [exact_checks]
    allowlisted_scope: [checks]
    stage_semantics: [invariants]
    required_tests_and_validators: [path#field]
    protected_refs_and_inputs: [checks]
    diff_index_worktree: [checks]
    producer_consumer_closure: [launcher_requirement#artifact_field]
  evidence:
    hard_gate: [path#field]
    diagnostic: [path#field]
    trend: [path#field]
  stop_conditions: [current_delta_blockers]
  handoff_target: INT-SUPERVISOR
```

Reviewer returns only:

```yaml
WORKLOG_HANDOFF:
  timestamp: ISO-8601
  session_id: actual_session_id
  stage_id: string
  input_sha: full_git_sha
  reviewed_output_sha: full_git_sha
  decision: PASS_or_BLOCKED
  findings: []       # maximum 5
  diagnostics: []    # maximum 5
  evidence_refs: []  # path#field or path#section
  blockers: []
  failure_identity: null_or_run_config_input_command_runtime_identity
  changed_hypothesis_required_for_retry: null_or_one_testable_change
  hard_gate_status: PASS_or_BLOCKED
  next_authorized_owner: INT-SUPERVISOR
  handoff_to: INT-SUPERVISOR
  next_action: one_action
```

Immutable earlier evidence is referenced, not copied. Untouched historical
Taxi/PT/Car evidence and guards are out of delta. For artifact or deployment
work, a PASS requires fail-closed proof that the released artifact contains
every executable, path and version required by its launcher. Duplicate
heartbeats with the same blocker produce no new dispatch.

CONTROL-PROTOCOL-02 changes no lane authority. Stage 9 remains blocked and
unauthorized by this governance document.
