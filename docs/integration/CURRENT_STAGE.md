# Current integration stage

This is the canonical compact state record. Stable rules are in
[`INTEGRATION_POLICY.md`](INTEGRATION_POLICY.md); lane identity and write scope
are in [`agent-lanes.md`](../../agent-lanes.md). It records the latest valid
Supervisor gate, not a queue of historical worklog events.

```yaml
atomic_gate_transition:
  transition_id: "AGT-20260803-STAGE9-JDK-LEGAL-REPAIR-001"
  exact_input_sha: "fe6a216c91a3d871fee0d58672868127fc2482a0"
  closed_task:
    task_id: "STAGE8D-R1-JDK-RUNTIME-CLOSURE"
    previous_status: "PASS_CLOSED"
    final_status: "PASS_CLOSED"
    reviewed_output_sha: "339ef046c55faf3e727a19d32234612bd6974241"
    reviewer_verdict: "PASS"
    reviewer_verdict_reference: "docs/agent-worklogs/integration-reviewer.md#entry-16--stage-8d-r1-exact-sha-review"
    supervisor_gate: "PASS_CLOSED"
  superseded_task:
    task_id: "STAGE9-JOINT-SHORT-SMOKE"
    previous_status: "ACTIVATED_AWAITING_SEPARATE_RUNNER_INSTRUCTION"
    final_status: "BLOCKED_SUPERSEDED_BY_REPAIR"
    source_sha: "fe6a216c91a3d871fee0d58672868127fc2482a0"
  blocker:
    blocker_id: "STAGE9-JDK-LEGAL-MEMBER-CONTRACT-001"
    previous_status: "OPEN"
    final_status: "REPAIR_DISPATCHED"
  next_active_task:
    task_id: "STAGE9-REPAIR-JDK-ARCHIVE-MEMBERS-001"
    status: "ACTIVE"
    owner: "INT-EXECUTOR"
  owner: "INT-SUPERVISOR"
  repository_writer: "INT-EXECUTOR"
  runner_authorized: false
  stage_9_authorized: true
  stage_9_execution_authorized: false
  canonical_state_updated: true
  audit_records_appended:
    - "docs/agent-worklogs/integration-supervisor.md#entry-34--stage-9-jdk-legal-member-repair-dispatch"
    - "docs/agent-worklogs/integration-executor.md#entry-31--stage-9-jdk-legal-member-repair"
  verdict_only_followup_commit_allowed: false

last_closed_task:
  task_id: "STAGE8D-R1-JDK-RUNTIME-CLOSURE"
  blocker_id: "STAGE9-RUNTIME-JDK-MISSING-001"
  blocker_status: "CLOSED"
  repair_status: "PASS_CLOSED"
  repair_sha: "339ef046c55faf3e727a19d32234612bd6974241"
  closure_evidence_sha: "c12a80fe8bca7a945eaaf39d00149fb3dd7838d4"
  superseded_stage_9_status: "BLOCKED_SUPERSEDED_BY_REPAIR"

superseded_stage9_task:
  task_id: "STAGE9-JOINT-SHORT-SMOKE"
  status: "BLOCKED_SUPERSEDED_BY_REPAIR"
  source_sha: "fe6a216c91a3d871fee0d58672868127fc2482a0"
  brief: "docs/integration/stage-briefs/STAGE_09_JOINT_SHORT_SMOKE.md"

active_blocker:
  blocker_id: "STAGE9-JDK-LEGAL-MEMBER-CONTRACT-001"
  status: "REPAIR_DISPATCHED"
  failure_identity:
    stage: "Stage 9 joint short smoke"
    source_sha: "fe6a216c91a3d871fee0d58672868127fc2482a0"
    approved_jdk_archive_sha256: "69264a7a211bf5029830d07bc3370f879769d62ebc5b5488e90c9343a2da0e1f"
    failing_member: "legal/jdk.jshell/ADDITIONAL_LICENSE_INFO"
    operation: "JDK archive layout validation before runtime materialization"
    staging_root: "/mnt/DiskM/by/hk_stage9_fe6a216_staging1"
    release_root: "/mnt/DiskM/by/hk_multimodal_cost_fe6a216_stage9_release1"
    bundle_produced: false
    matsim_process_started: false
  root_cause: "The approved JDK archive contains legal metadata hard-link members, but the extraction contract rejected every non-file/non-directory member before materializing runtime/jdk-25."
  changed_hypothesis_required_for_retry: "Safely accept only approved legal/* metadata hard links whose direct regular-file targets remain inside the same legal subtree, while preserving all archive and runtime executable guards."
  repair_task_id: "STAGE9-REPAIR-JDK-ARCHIVE-MEMBERS-001"
  repair_owner: "INT-EXECUTOR"
  replacement_identity_required:
    - "new pushed repair source SHA"
    - "new staging directory; do not reuse /mnt/DiskM/by/hk_stage9_fe6a216_staging1"
    - "new release root; do not reuse /mnt/DiskM/by/hk_multimodal_cost_fe6a216_stage9_release1"
    - "new run identity under a separate Supervisor Runner authorization"
  superseded_run_identity:
    staging_root: "/mnt/DiskM/by/hk_stage9_fe6a216_staging1"
    release_root: "/mnt/DiskM/by/hk_multimodal_cost_fe6a216_stage9_release1"
    run_identity: "Stage 9 attempt at source fe6a216c91a3d871fee0d58672868127fc2482a0"
  runner_authorized: false

active_task:
  task_id: "STAGE9-REPAIR-JDK-ARCHIVE-MEMBERS-001"
  status: "ACTIVE"
  owner: "INT-EXECUTOR"
  brief: "docs/integration/stage-briefs/STAGE_09_REPAIR_JDK_ARCHIVE_MEMBERS_001.md"

execution_authority:
  authority_source: "INT-SUPERVISOR"
  runner_authorized: false
  stage_9_authorized: true
  stage_9_execution_authorized: false
  bounded_repair_authorized: true
  repair_commit_accessed_server: false
  repair_commit_built_or_uploaded_bundle: false
  repair_commit_started_smoke: false
  formal_50it_authorized: false
  stage_10_or_later_authorized: false

control_transition_review:
  task_id: "STAGE9-REPAIR-JDK-ARCHIVE-MEMBERS-001"
  status: "PENDING_ONE_FINAL_READ_ONLY_REVIEW"
  one_final_review_only: true
  pass_followup_commit_allowed: false
```

## Canonical interpretation

The initial Stage 9 execution identity is blocked before bundle creation and
superseded by the active bounded JDK archive-member repair. The approved JDK
archive remains hash locked. This task changes only its safe materialization
contract: a `legal/*` hard link may be copied as a regular metadata file only
when its direct, non-executable regular-file target is also under `legal/*`.

Runner and Stage 9 execution are unauthorized during this repair. No bundle,
release, upload, smoke, formal 50-iteration, calibration, Stage 10 or later
work is authorized.

## Next action

Executor pushes the single bounded repair commit and reports only to
Supervisor. Supervisor verifies its exact SHA, parent and scope before one
read-only review. Any later Runner attempt requires a separate authorization
and a new source, staging, release and run identity.
