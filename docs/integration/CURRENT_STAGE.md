# Current integration stage

This is the canonical compact state record. Stable rules are in
[`INTEGRATION_POLICY.md`](INTEGRATION_POLICY.md); lane identity and write scope
are in [`agent-lanes.md`](../../agent-lanes.md). It records the latest valid
Supervisor gate, not a queue of historical worklog events.

```yaml
atomic_gate_transition:
  transition_id: "AGT-20260803-STAGE9-JDK-LEGAL-SYMLINK-004"
  exact_input_sha: "7796154241518e4fb13b29f345b20bef0d91e9a2"
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
    previous_status: "AUTHORIZED_RUN_IDENTITY_BLOCKED_BEFORE_UPLOAD"
    final_status: "BLOCKED_SUPERSEDED_BY_REPAIR"
    source_sha: "7796154241518e4fb13b29f345b20bef0d91e9a2"
  blocker:
    blocker_id: "STAGE9-JDK-LEGAL-REGULAR-CONTRACT-002"
    previous_status: "OPEN"
    final_status: "REPAIR_DISPATCHED"
  next_active_task:
    task_id: "STAGE9-REPAIR-JDK-LEGAL-SYMLINK-004"
    status: "ACTIVE"
    owner: "INT-EXECUTOR"
  owner: "INT-SUPERVISOR"
  repository_writer: "INT-EXECUTOR"
  runner_authorized: false
  stage_9_authorized: true
  stage_9_execution_authorized: false
  canonical_state_updated: true
  audit_records_appended:
    - "docs/agent-worklogs/integration-supervisor.md#entry-35--stage-9-diagnosed-jdk-legal-symlink-repair-dispatch"
    - "docs/agent-worklogs/integration-executor.md#entry-32--stage-9-diagnosed-jdk-legal-symlink-repair"
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
  source_sha: "7796154241518e4fb13b29f345b20bef0d91e9a2"
  brief: "docs/integration/stage-briefs/STAGE_09_JOINT_SHORT_SMOKE.md"

active_blocker:
  blocker_id: "STAGE9-JDK-LEGAL-REGULAR-CONTRACT-002"
  status: "REPAIR_DISPATCHED"
  failure_identity:
    stage: "Stage 9 joint short smoke"
    source_sha: "7796154241518e4fb13b29f345b20bef0d91e9a2"
    prior_failure_identity: "STAGE9-JDK-LEGAL-MEMBER-CONTRACT-001"
    approved_jdk_archive_sha256: "69264a7a211bf5029830d07bc3370f879769d62ebc5b5488e90c9343a2da0e1f"
    preparation_script_sha256: "382be155f44429e183182c02b1917ab82704bb1865c4ec6c3d4ca921cc201609"
    failing_member: "jdk-25.0.3+9/legal/jdk.jshell/ADDITIONAL_LICENSE_INFO"
    raw_member_type: "b'2'"
    linkname: "../java.base/ADDITIONAL_LICENSE_INFO"
    staging_root: "/mnt/DiskM/by/hk_stage9_77961542_staging2"
    release_produced: false
    bundle_produced: false
    matsim_process_started: false
  root_cause: "The approved archive uses a legal/* symbolic link to a regular legal metadata member; the prior contract supported only regular files, directories and hard links."
  changed_hypothesis_required_for_retry: "Resolve only relative legal/* symbolic links whose normalized target remains under legal/ in the same trusted JDK root, require a direct non-executable regular target, and materialize target bytes as an ordinary file."
  repair_task_id: "STAGE9-REPAIR-JDK-LEGAL-SYMLINK-004"
  repair_owner: "INT-EXECUTOR"
  replacement_identity_required:
    - "new pushed repair source SHA"
    - "new staging root; never reuse /mnt/DiskM/by/hk_stage9_77961542_staging2"
    - "new release root; never reuse release2 or any prior release identity"
    - "new run identity under separate Supervisor authorization"
  superseded_run_identity:
    source_sha: "7796154241518e4fb13b29f345b20bef0d91e9a2"
    staging_root: "/mnt/DiskM/by/hk_stage9_77961542_staging2"
    release_identity: "release2 was not produced and must not be reused"
    run_identity: "Stage 9 attempt blocked before upload/run"
  diagnosis_evidence:
    path: "/mnt/DiskM/by/hk_stage9_77961542_diag1/diagnosis.json"
    sha256: "a86521620e00c917150f10c037f13b741e924782e13d95a9108408d181cc80f1"
  runner_authorized: false

active_task:
  task_id: "STAGE9-REPAIR-JDK-LEGAL-SYMLINK-004"
  status: "ACTIVE"
  owner: "INT-EXECUTOR"
  brief: "docs/integration/stage-briefs/STAGE_09_REPAIR_JDK_LEGAL_SYMLINK_004.md"

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
  task_id: "STAGE9-REPAIR-JDK-LEGAL-SYMLINK-004"
  status: "PENDING_ONE_FINAL_READ_ONLY_REVIEW"
  one_final_review_only: true
  pass_followup_commit_allowed: false
```

## Canonical interpretation

The Stage 9 identity at source `7796154...` is blocked before bundle creation,
upload or execution and is superseded by this diagnosed JDK legal-symlink
repair. The approved JDK archive and preparation-script identities remain hash
locked. The repaired contract copies only a safely resolved direct regular
`legal/*` target to an ordinary file; it never emits a symbolic link.

Runner and Stage 9 execution are unauthorized during this repair. No bundle,
release, upload, smoke, formal 50-iteration, calibration, Stage 10 or later
work is authorized.

## Next action

Executor pushes one bounded repair commit and reports only to Supervisor.
Supervisor verifies its exact SHA, parent and scope before one read-only review.
Any later Stage 9 attempt requires a separate authorization plus new source,
staging, release and run identities.
