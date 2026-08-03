# Current integration stage

This is the canonical compact state record. Stable rules are in
[`INTEGRATION_POLICY.md`](INTEGRATION_POLICY.md); lane identity and write scope
are in [`agent-lanes.md`](../../agent-lanes.md). It records the latest valid
Supervisor gate, not a queue of historical worklog events.

```yaml
atomic_gate_transition:
  transition_id: "AGT-20260803-PROTOCOL06-POST-FAILURE-DISPATCH-001"
  exact_input_sha: "a72f8cac53b5798cc8468c1297db82dd1aed633c"
  closed_task:
    task_id: "STAGE9-REPAIR-SHADED-JAR-DEPENDENCY-CLOSURE-005"
    previous_status: "UNDER_REVIEW"
    final_status: "PASS_CLOSED"
    reviewed_output_sha: "a72f8cac53b5798cc8468c1297db82dd1aed633c"
    reviewer_verdict: "PASS"
    reviewer_verdict_reference: "docs/agent-worklogs/integration-supervisor.md#entry-37--protocol-06-atomic-repair-closure-and-dispatch"
    supervisor_gate: "PASS_CLOSED"
  superseded_task:
    task_id: "STAGE9-JOINT-SHORT-SMOKE"
    previous_status: "RUN_BLOCKED_RUNTIME_DEPENDENCY_MISSING"
    final_status: "BLOCKED_SUPERSEDED_BY_REPAIR"
    source_sha: "c129c18fe5996ef38740c454f7f0482c4ffe4695"
  blocker:
    blocker_id: "STAGE9-RUNTIME-DEPENDENCY-CLASSPATH-001"
    previous_status: "UNDER_REVIEW"
    final_status: "CLOSED"
  next_active_task:
    task_id: "CONTROL-PROTOCOL-06-POST-FAILURE-DIAGNOSIS-AUTO-DISPATCH"
    status: "PENDING_ONE_FINAL_READ_ONLY_REVIEW"
    owner: "INT-SUPERVISOR"
  owner: "INT-SUPERVISOR"
  repository_writer: "INT-EXECUTOR"
  runner_authorized: false
  stage_9_authorized: false
  stage_9_execution_authorized: false
  stage_10_or_later_authorized: false
  canonical_state_updated: true
  audit_records_appended:
    - "docs/agent-worklogs/integration-supervisor.md#entry-37--protocol-06-atomic-repair-closure-and-dispatch"
    - "docs/agent-worklogs/integration-executor.md#entry-34--protocol-06-post-failure-diagnosis-policy"
  verdict_only_followup_commit_allowed: false

last_closed_task:
  task_id: "STAGE9-REPAIR-SHADED-JAR-DEPENDENCY-CLOSURE-005"
  blocker_id: "STAGE9-RUNTIME-DEPENDENCY-CLASSPATH-001"
  blocker_status: "CLOSED"
  repair_status: "PASS_CLOSED"
  repair_sha: "a72f8cac53b5798cc8468c1297db82dd1aed633c"
  reviewer_verdict: "PASS"
  supervisor_gate: "PASS_CLOSED"
  superseded_stage_9_status: "BLOCKED_SUPERSEDED_BY_REPAIR"

superseded_stage9_task:
  task_id: "STAGE9-JOINT-SHORT-SMOKE"
  status: "BLOCKED_SUPERSEDED_BY_REPAIR"
  source_sha: "c129c18fe5996ef38740c454f7f0482c4ffe4695"
  bundle_sha256: "0f4ab65801f7e1e6e2cec55e4a9e77c8e95caae1af7a57133fef4430b35dbe45"
  release_root: "/mnt/DiskM/by/hk_multimodal_cost_c129c1_stage9_release3"
  run_identity: "smoke_qsim_v1_c129c1_run3"
  failure: "NoClassDefFoundError org/matsim/core/controler/AbstractModule"
  brief: "docs/integration/stage-briefs/STAGE_09_JOINT_SHORT_SMOKE.md"

closed_blocker:
  blocker_id: "STAGE9-RUNTIME-DEPENDENCY-CLASSPATH-001"
  status: "CLOSED"
  failure_identity:
    source_sha: "c129c18fe5996ef38740c454f7f0482c4ffe4695"
    bundle_sha256: "0f4ab65801f7e1e6e2cec55e4a9e77c8e95caae1af7a57133fef4430b35dbe45"
    release_root: "/mnt/DiskM/by/hk_multimodal_cost_c129c1_stage9_release3"
    run_identity: "smoke_qsim_v1_c129c1_run3"
    failure: "NoClassDefFoundError org/matsim/core/controler/AbstractModule"
    selected_artifact: "build_root/target/matsim-example-project-0.0.1-SNAPSHOT.jar"
  root_cause: "Maven produced a target/ thin JAR and a build-root Maven Shade fat JAR with the same filename; bundle preparation copied the arbitrary target/ path, leaving MATSim and other dependencies outside the release classpath."
  changed_hypothesis_required_for_retry: "Derive only the build-root top-level Shade JAR, verify project and dependency classes, enforce built/release/bundle SHA equality, and class-load every required class with final release Java before MATSim startup."
  repair_task_id: "STAGE9-REPAIR-SHADED-JAR-DEPENDENCY-CLOSURE-005"
  repair_owner: "INT-EXECUTOR"
  repair_sha: "a72f8cac53b5798cc8468c1297db82dd1aed633c"
  reviewer_verdict: "PASS"
  replacement_identity_required:
    - "new pushed repair source SHA"
    - "new bundle SHA built from the deterministic root Shade JAR"
    - "new release root; never reuse /mnt/DiskM/by/hk_multimodal_cost_c129c1_stage9_release3"
    - "new run identity; never reuse smoke_qsim_v1_c129c1_run3"
  superseded_run_identity:
    source_sha: "c129c18fe5996ef38740c454f7f0482c4ffe4695"
    bundle_sha256: "0f4ab65801f7e1e6e2cec55e4a9e77c8e95caae1af7a57133fef4430b35dbe45"
    release_root: "/mnt/DiskM/by/hk_multimodal_cost_c129c1_stage9_release3"
    run_identity: "smoke_qsim_v1_c129c1_run3"
  runner_authorized: false

active_task:
  task_id: "CONTROL-PROTOCOL-06-POST-FAILURE-DIAGNOSIS-AUTO-DISPATCH"
  status: "PENDING_ONE_FINAL_READ_ONLY_REVIEW"
  owner: "INT-SUPERVISOR"
  brief: "docs/integration/stage-briefs/CONTROL_PROTOCOL_06_POST_FAILURE_DIAGNOSIS_AUTO_DISPATCH.md"

protocol_06:
  canonical_source: "docs/integration/stage-briefs/CONTROL_PROTOCOL_06_POST_FAILURE_DIAGNOSIS_AUTO_DISPATCH.md"
  worked_example: "docs/integration/stage-briefs/CONTROL_PROTOCOL_06_POST_FAILURE_DIAGNOSIS_AUTO_DISPATCH.md#worked-example-thin-jar-failure"
  post_failure_state: "POST_FAILURE_READ_ONLY_DIAGNOSIS"
  root_cause_status_values:
    - "KNOWN"
    - "PARTIAL"
    - "UNKNOWN"
  known_technical_defect_next_action: "CREATE_BOUNDED_EXECUTOR_REPAIR"
  partial_or_unknown_next_action: "CREATE_BOUNDED_READ_ONLY_DIAGNOSIS"
  research_semantic_next_action: "ESCALATED_TO_USER"
  automatic_repair_authorizes_runner: false
  identical_failed_identity_retry_allowed: false

runtime_contract:
  deployment_jar: "<build_root>/matsim-example-project-0.0.1-SNAPSHOT.jar"
  target_thin_jar_allowed: false
  required_project_class_count: 7
  required_dependency_class_count: 6
  built_release_bundle_sha256_must_match: true
  final_release_worker_rechecks_sha256: true
  class_loading_preflight_before_matsim: true

execution_authority:
  authority_source: "INT-SUPERVISOR"
  runner_authorized: false
  stage_9_authorized: false
  stage_9_execution_authorized: false
  bounded_repair_authorized: false
  repair_commit_accessed_server: false
  repair_commit_built_or_uploaded_bundle: false
  repair_commit_started_smoke: false
  formal_50it_authorized: false
  stage_10_or_later_authorized: false

control_transition_review:
  task_id: "CONTROL-PROTOCOL-06-POST-FAILURE-DIAGNOSIS-AUTO-DISPATCH"
  status: "PENDING_ONE_FINAL_READ_ONLY_REVIEW"
  one_final_review_only: true
  pass_followup_commit_allowed: false
```

## Canonical interpretation

The shaded-JAR repair at exact SHA `a72f8ca...` is Reviewer `PASS`, Supervisor
`PASS_CLOSED`, and blocker `STAGE9-RUNTIME-DEPENDENCY-CLASSPATH-001` is
`CLOSED`. Release3/run3 remains historical `BLOCKED_SUPERSEDED_BY_REPAIR`.
Protocol 06 is the active governance transition pending one final read-only
review.

Runner and Stage 9 execution remain unauthorized. No server,
bundle, release, smoke, formal 50-iteration, calibration, Stage 10 or later
work is authorized.

## Next action

Executor pushes this one atomic governance commit and reports only to
Supervisor. Supervisor verifies its exact SHA, parent and scope before one
read-only review. Reviewer `PASS` creates no closure-only follow-up commit.
