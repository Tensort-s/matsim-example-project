# Current integration stage

This is the canonical compact state record. Stable rules are in
[`INTEGRATION_POLICY.md`](INTEGRATION_POLICY.md); lane identity and write scope
are in [`agent-lanes.md`](../../agent-lanes.md). It records the latest valid
Supervisor gate, not a queue of historical worklog events.

```yaml
atomic_gate_transition:
  transition_id: "AGT-20260803-STAGE9-ARTIFACT-DISCOVERY-010"
  exact_input_sha: "3237c8f8e6bacf10feaa9bb515f58612c269f3a3"
  closed_task:
    task_id: "STAGE9-JOINT-SHORT-SMOKE"
    previous_status: "AUTHORIZED_BUILD_ATTEMPT"
    final_status: "BLOCKED_SUPERSEDED_BY_REPAIR"
    reviewed_output_sha: "3237c8f8e6bacf10feaa9bb515f58612c269f3a3"
    reviewer_verdict: "BLOCKED"
    reviewer_verdict_reference: "/mnt/DiskM/by/hk_stage9_3237c8_staging7/evidence/shade_server_diagnosis_009/diagnosis.json"
    verdict_source: "INT-RUNNER read-only diagnosis accepted by INT-SUPERVISOR"
    supervisor_gate: "BLOCKED_SUPERSEDED_BY_REPAIR"
  superseded_task:
    task_id: "STAGE9-JOINT-SHORT-SMOKE"
    previous_status: "AUTHORIZED_BUILD_ATTEMPT"
    final_status: "BLOCKED_SUPERSEDED_BY_REPAIR"
    source_sha: "3237c8f8e6bacf10feaa9bb515f58612c269f3a3"
    staging_root: "/mnt/DiskM/by/hk_stage9_3237c8_staging7"
    reserved_run_identity: "smoke_qsim_v1_3237c8_run7"
  blocker:
    blocker_id: "STAGE9-RUNNER-SHADE-CLOSURE-002"
    previous_status: "OPEN"
    final_status: "REPAIR_DISPATCHED"
  next_active_task:
    task_id: "STAGE9-REPAIR-ARTIFACT-DISCOVERY-010"
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
    - "docs/agent-worklogs/integration-supervisor.md#entry-41--stage-9-artifact-discovery-repair-dispatch"
    - "docs/agent-worklogs/integration-executor.md#entry-38--stage-9-artifact-discovery-contract"
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
  source_sha: "3237c8f8e6bacf10feaa9bb515f58612c269f3a3"
  staging_root: "/mnt/DiskM/by/hk_stage9_3237c8_staging7"
  reserved_run_identity: "smoke_qsim_v1_3237c8_run7"
  failure: "artifact discovery scanned only build_root/target and selected the thin JAR although the POM-configured root Shade JAR existed"
  package_performed: true
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
  task_id: "STAGE9-REPAIR-ARTIFACT-DISCOVERY-010"
  status: "ACTIVE"
  owner: "INT-EXECUTOR"
  brief: "docs/integration/stage-briefs/STAGE_09_REPAIR_ARTIFACT_DISCOVERY_010.md"

active_blocker:
  blocker_id: "STAGE9-RUNNER-SHADE-CLOSURE-002"
  status: "REPAIR_DISPATCHED"
  failure_identity:
    source_sha: "3237c8f8e6bacf10feaa9bb515f58612c269f3a3"
    staging_root: "/mnt/DiskM/by/hk_stage9_3237c8_staging7"
    reserved_run_identity: "smoke_qsim_v1_3237c8_run7"
    root_shade_jar_sha256: "54c65711a2e023cdff7986a840bcb7f81889d6f07233c94f02f50b204f2345c7"
    root_shade_jar_size_bytes: 300597135
    root_shade_jar_entry_count: 101152
    selected_target_thin_sha256_prefix: "afc0d618"
    failure: "Runner discovery selected target thin JAR and reported missing MATSim/Guice classes"
  root_cause: "Runner artifact discovery scanned only build_root/target and selected the thin JAR even though the POM-configured root Shade JAR existed with dependency closure."
  diagnosis_confidence:
    exact_failure_identity_matched: true
    direct_failure_condition_observed: true
    causal_chain_demonstrated: true
    material_alternatives_checked: true
    repair_hypothesis_testable: true
    root_cause_status: "KNOWN"
  changed_hypothesis_required_for_retry: "Artifact discovery must derive and inspect the exact build-root top-level JAR first, record stat/SHA/member inventory, reject target/ explicitly, and fail closed before bundle on missing dependency closure."
  repair_task_id: "STAGE9-REPAIR-ARTIFACT-DISCOVERY-010"
  repair_owner: "INT-EXECUTOR"
  replacement_identity_required:
    - "new pushed repair SHA"
    - "new staging root; never reuse /mnt/DiskM/by/hk_stage9_3237c8_staging7"
    - "new bundle and release identity"
    - "new run identity; never reuse smoke_qsim_v1_3237c8_run7"
  superseded_run_identity:
    source_sha: "3237c8f8e6bacf10feaa9bb515f58612c269f3a3"
    staging_root: "/mnt/DiskM/by/hk_stage9_3237c8_staging7"
    reserved_run_identity: "smoke_qsim_v1_3237c8_run7"
  diagnosis_evidence: "/mnt/DiskM/by/hk_stage9_3237c8_staging7/evidence/shade_server_diagnosis_009/diagnosis.json"
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

artifact_discovery_contract:
  deployment_relative_path: "matsim-example-project-0.0.1-SNAPSHOT.jar"
  root_path_inspected_first: true
  root_regular_non_symlink_required: true
  root_stat_sha_member_inventory_required: true
  target_thin_relative_path: "target/matsim-example-project-0.0.1-SNAPSHOT.jar"
  target_thin_selection_allowed: false
  glob_or_size_based_selection_allowed: false
  root_absent_or_dependency_incomplete_action: "FAIL_CLOSED_BEFORE_BUNDLE"
  canonical_resolver_unchanged: true

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
  task_id: "STAGE9-REPAIR-ARTIFACT-DISCOVERY-010"
  status: "PENDING_ONE_FINAL_READ_ONLY_REVIEW"
  one_final_review_only: true
  pass_followup_commit_allowed: false
```

## Canonical interpretation

Protocol 07 follow-up diagnosis classified the staging7 artifact-discovery
defect as `KNOWN`. Maven package completed and the root Shade JAR existed, but
Runner scanned only `target/` and selected the thin JAR. The attempt is
`BLOCKED_SUPERSEDED_BY_REPAIR`; bundle, upload and smoke did not run. The
active bounded repair changes only the Runner governance contract: discovery
is POM-driven, inspects the root JAR first, records dependency evidence and
rejects `target/` explicitly. The already-canonical resolver remains unchanged.

Runner and Stage 9 execution remain unauthorized. No server,
bundle, release, smoke, formal 50-iteration, calibration, Stage 10 or later
work is authorized.

## Next action

Executor pushes this one bounded governance repair commit and reports only to
Supervisor. Supervisor verifies its exact SHA, parent and scope before one
read-only review. Any later Stage 9 attempt requires a separate authorization
and new source, staging, bundle, release and run identities.
