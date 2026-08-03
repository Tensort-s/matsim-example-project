# Current integration stage

This is the canonical compact state record. Stable rules are in
[`INTEGRATION_POLICY.md`](INTEGRATION_POLICY.md); lane identity and write scope
are in [`agent-lanes.md`](../../agent-lanes.md). It records the latest valid
Supervisor gate, not a queue of historical worklog events.

```yaml
atomic_gate_transition:
  transition_id: "AGT-20260803-STAGE9-MODE-PRESERVATION-007"
  exact_input_sha: "f182b24c2b1bffdb216248d50e579275001d1b1b"
  closed_task:
    task_id: "STAGE9-JOINT-SHORT-SMOKE"
    previous_status: "AUTHORIZED_PRE_MAVEN_ATTEMPT"
    final_status: "BLOCKED_SUPERSEDED_BY_REPAIR"
    reviewed_output_sha: "f182b24c2b1bffdb216248d50e579275001d1b1b"
    reviewer_verdict: "BLOCKED"
    reviewer_verdict_reference: "/mnt/DiskM/by/hk_stage9_f182b2_staging6/evidence/diagnosis_stage9_wrapper_mode.json"
    verdict_source: "INT-RUNNER failure diagnosis accepted by INT-SUPERVISOR"
    supervisor_gate: "BLOCKED_SUPERSEDED_BY_REPAIR"
  superseded_task:
    task_id: "STAGE9-JOINT-SHORT-SMOKE"
    previous_status: "AUTHORIZED_PRE_MAVEN_ATTEMPT"
    final_status: "BLOCKED_SUPERSEDED_BY_REPAIR"
    source_sha: "f182b24c2b1bffdb216248d50e579275001d1b1b"
    staging_root: "/mnt/DiskM/by/hk_stage9_f182b2_staging6"
    reserved_run_identity: "smoke_qsim_v1_f182b2_run6"
  blocker:
    blocker_id: "STAGE9-RUNNER-WORKDIR-MODE-001"
    previous_status: "OPEN"
    final_status: "REPAIR_DISPATCHED"
  next_active_task:
    task_id: "STAGE9-REPAIR-MODE-PRESERVATION-007"
    status: "ACTIVE"
    owner: "INT-EXECUTOR"
  owner: "INT-SUPERVISOR"
  repository_writer: "INT-EXECUTOR"
  runner_authorized: false
  stage_9_authorized: false
  stage_9_execution_authorized: false
  stage_10_or_later_authorized: false
  canonical_state_updated: true
  audit_records_appended:
    - "docs/agent-worklogs/integration-supervisor.md#entry-40--stage-9-mode-preservation-repair-dispatch"
    - "docs/agent-worklogs/integration-executor.md#entry-37--stage-9-mode-preservation-contract"
  verdict_only_followup_commit_allowed: false

last_closed_task:
  task_id: "CONTROL-PROTOCOL-06-POST-FAILURE-DIAGNOSIS-AUTO-DISPATCH"
  task_status: "PASS_CLOSED"
  reviewed_output_sha: "e12f81b27c8a70f373654ca46dac1cb7ef17bb5e"
  reviewer_verdict: "PASS"
  supervisor_gate: "PASS_CLOSED"

superseded_stage9_task:
  task_id: "STAGE9-JOINT-SHORT-SMOKE"
  status: "BLOCKED_SUPERSEDED_BY_REPAIR"
  source_sha: "f182b24c2b1bffdb216248d50e579275001d1b1b"
  staging_root: "/mnt/DiskM/by/hk_stage9_f182b2_staging6"
  reserved_run_identity: "smoke_qsim_v1_f182b2_run6"
  failure: "source snapshot/archive extraction changed mvnw from Git 100755 to extracted 0775; strict pre-Maven guard stopped"
  package_performed: false
  bundle_performed: false
  upload_performed: false
  smoke_performed: false
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
  task_id: "STAGE9-REPAIR-MODE-PRESERVATION-007"
  status: "ACTIVE"
  owner: "INT-EXECUTOR"
  brief: "docs/integration/stage-briefs/STAGE_09_REPAIR_MODE_PRESERVATION_007.md"

active_blocker:
  blocker_id: "STAGE9-RUNNER-WORKDIR-MODE-001"
  status: "REPAIR_DISPATCHED"
  failure_identity:
    source_sha: "f182b24c2b1bffdb216248d50e579275001d1b1b"
    staging_root: "/mnt/DiskM/by/hk_stage9_f182b2_staging6"
    reserved_run_identity: "smoke_qsim_v1_f182b2_run6"
    git_tree_mode: "100755"
    extracted_mode: "0775"
    failure: "strict pre-Maven mode guard stopped before build"
  root_cause: "The source snapshot/archive extraction path changed mvnw from Git mode 100755 to extracted runtime mode 0775 instead of the required 0755."
  diagnosis_confidence:
    exact_failure_identity_matched: true
    direct_failure_condition_observed: true
    causal_chain_demonstrated: true
    material_alternatives_checked: true
    repair_hypothesis_testable: true
    root_cause_status: "KNOWN"
  changed_hypothesis_required_for_retry: "The archive-to-source_root-to-build_root path must preserve the Git executable mapping as exact archive/runtime mode 0755 and prove type, mode and byte identity before Maven; 0775 fails closed."
  repair_task_id: "STAGE9-REPAIR-MODE-PRESERVATION-007"
  repair_owner: "INT-EXECUTOR"
  replacement_identity_required:
    - "new pushed repair SHA"
    - "new normalized snapshot archive and staging root; never reuse /mnt/DiskM/by/hk_stage9_f182b2_staging6"
    - "new bundle and release identity"
    - "new run identity; never reuse smoke_qsim_v1_f182b2_run6"
  superseded_run_identity:
    source_sha: "f182b24c2b1bffdb216248d50e579275001d1b1b"
    staging_root: "/mnt/DiskM/by/hk_stage9_f182b2_staging6"
    reserved_run_identity: "smoke_qsim_v1_f182b2_run6"
  diagnosis_evidence: "/mnt/DiskM/by/hk_stage9_f182b2_staging6/evidence/diagnosis_stage9_wrapper_mode.json"
  runner_authorized: false

protocol_06:
  status: "PASS_CLOSED"
  reviewed_output_sha: "e12f81b27c8a70f373654ca46dac1cb7ef17bb5e"
  reviewer_verdict: "PASS"
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

protocol_07:
  canonical_source: "docs/integration/stage-briefs/CONTROL_PROTOCOL_07_DIAGNOSIS_CONFIDENCE_AND_BUDGET.md"
  worked_example: "docs/integration/stage-briefs/CONTROL_PROTOCOL_07_DIAGNOSIS_CONFIDENCE_AND_BUDGET.md#worked-example-thin-jar-evidence-chain"
  known_requires_all_confidence_gates: true
  exception_or_stack_trace_alone_proves_known: false
  supervisor_may_promote_without_new_evidence: false
  diagnosis_budget:
    wall_clock_minutes_max: 30
    shell_commands_max: 30
    filesystem_roots_max: 6
    evidence_output_mb_max: 30
    full_server_recursive_scan_allowed: false
    existing_state_mutation_allowed: false
  budget_exhaustion_action: "STOP_AND_REPORT_MISSING_EVIDENCE"
  partial_or_unknown_direct_repair_allowed: false
  automatic_dispatch_authorizes_runner_or_retry: false

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
  bounded_repair_authorized: true
  repair_commit_accessed_server: false
  repair_commit_built_or_uploaded_bundle: false
  repair_commit_started_smoke: false
  formal_50it_authorized: false
  stage_10_or_later_authorized: false

control_transition_review:
  task_id: "STAGE9-REPAIR-MODE-PRESERVATION-007"
  status: "PENDING_ONE_FINAL_READ_ONLY_REVIEW"
  one_final_review_only: true
  pass_followup_commit_allowed: false
```

## Canonical interpretation

Protocol 07 classified the staging6 wrapper-mode mismatch as a `KNOWN`
ordinary technical defect. The failed Stage 9 attempt is
`BLOCKED_SUPERSEDED_BY_REPAIR`; package, bundle, upload and smoke did not run.
The active bounded repair defines only the immutable source-snapshot mode and
identity-continuity contract: Git `100755` maps to archive/runtime `0755`, and
the observed raw archive mode `0775` fails closed. Earlier failure evidence
remains preserved in append-only worklogs.

Runner and Stage 9 execution remain unauthorized. No server,
bundle, release, smoke, formal 50-iteration, calibration, Stage 10 or later
work is authorized.

## Next action

Executor pushes this one bounded governance repair commit and reports only to
Supervisor. Supervisor verifies its exact SHA, parent and scope before one
read-only review. Any later Stage 9 attempt requires a separate authorization,
a newly normalized and verified snapshot archive, and new source, staging,
bundle, release and run identities.
