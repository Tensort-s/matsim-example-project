# Current integration stage

This is the canonical compact state record. Stable rules are in
[`INTEGRATION_POLICY.md`](INTEGRATION_POLICY.md); lane identity and write scope
are in [`agent-lanes.md`](../../agent-lanes.md). It records the latest valid
Supervisor gate, not a queue of historical worklog events.

```yaml
atomic_gate_transition:
  transition_id: "AGT-20260803-STAGE9-ACTIVATE-001"
  exact_input_sha: "9c66fa772cf128fdcf208a5e3171bd7fbd3444d5"
  closed_task:
    task_id: "STAGE8D-R1-JDK-RUNTIME-CLOSURE"
    previous_status: "PASS_CLOSED"
    final_status: "PASS_CLOSED"
    reviewed_output_sha: "339ef046c55faf3e727a19d32234612bd6974241"
    reviewer_verdict: "PASS"
    reviewer_verdict_reference: "docs/agent-worklogs/integration-reviewer.md#entry-16--stage-8d-r1-exact-sha-review"
    supervisor_gate: "PASS_CLOSED"
  blocker:
    blocker_id: "STAGE9-RUNTIME-JDK-MISSING-001"
    previous_status: "CLOSED"
    final_status: "CLOSED"
  next_active_task:
    task_id: "STAGE9-JOINT-SHORT-SMOKE"
    status: "ACTIVATED_AWAITING_SEPARATE_RUNNER_INSTRUCTION"
    owner: "INT-RUNNER"
  owner: "INT-SUPERVISOR"
  repository_writer: "INT-EXECUTOR"
  runner_authorized: false
  stage_9_authorized: true
  canonical_state_updated: true
  audit_records_appended:
    - "docs/agent-worklogs/integration-supervisor.md#entry-33--stage-9-activation-atomic-transition"
    - "docs/agent-worklogs/integration-executor.md#entry-30--stage-9-activation-atomic-transition"
  verdict_only_followup_commit_allowed: false

last_closed_task:
  task_id: "STAGE8D-R1-JDK-RUNTIME-CLOSURE"
  blocker_id: "STAGE9-RUNTIME-JDK-MISSING-001"
  blocker_status: "CLOSED"
  repair_status: "PASS_CLOSED"
  repair_sha: "339ef046c55faf3e727a19d32234612bd6974241"
  closure_evidence_sha: "c12a80fe8bca7a945eaaf39d00149fb3dd7838d4"
  superseded_stage_9_status: "BLOCKED_SUPERSEDED_BY_REPAIR"

active_task:
  task_id: "STAGE9-JOINT-SHORT-SMOKE"
  status: "ACTIVATED_AWAITING_SEPARATE_RUNNER_INSTRUCTION"
  owner: "INT-RUNNER"
  brief: "docs/integration/stage-briefs/STAGE_09_JOINT_SHORT_SMOKE.md"

runtime_identity_contract:
  source_commit: "EXACT_PUSHED_ACTIVATION_SHA_FROM_SEPARATE_SUPERVISOR_RUN_INSTRUCTION"
  required_ancestor: "339ef046c55faf3e727a19d32234612bd6974241"
  superseded_release_root: "/mnt/DiskM/by/hk_multimodal_cost_674a6025_stage8d_build2"
  reuse_superseded_release_or_run: false
  new_bundle_release_run_identity_required: true

execution_authority:
  authority_source: "INT-SUPERVISOR"
  runner_authorized: false
  runner_authorization_condition: "separate exact-SHA Supervisor Stage 9 run instruction"
  stage_9_authorized: true
  activation_commit_built_bundle: false
  activation_commit_uploaded_bundle: false
  activation_commit_started_smoke: false
  formal_50it_authorized: false
  stage_10_or_later_authorized: false

control_transition_review:
  task_id: "STAGE9-ACTIVATE-ATOMIC-GATE"
  status: "PENDING_ONE_FINAL_READ_ONLY_REVIEW"
  one_final_review_only: true
  pass_followup_commit_allowed: false
```

## Canonical interpretation

Stage 9 is activated as the next task, but Runner execution remains blocked
until Supervisor issues a separate instruction naming the exact pushed
activation SHA and run identity. The repaired JDK task and blocker remain
closed. The original Stage 9 release/run identity remains superseded and may
not be reused.

This activation commit performs no build, upload or smoke. It authorizes no
formal 50-iteration, calibration, Stage 10 or later work.

## Next action

Supervisor verifies the activation commit's exact SHA, parent and scope, then
dispatches one final read-only Reviewer review. After consuming the verdict,
Supervisor may issue a separate exact-SHA Stage 9 Runner instruction. Executor
stops; no verdict-only or closure-only follow-up commit is allowed.
