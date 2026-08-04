# Current integration stage

This is the canonical compact state record. Stable rules are in
[`INTEGRATION_POLICY.md`](INTEGRATION_POLICY.md); lane identity and write scope
are in [`agent-lanes.md`](../../agent-lanes.md). It records the latest valid
Supervisor gate, not a queue of historical worklog events.

```yaml
atomic_gate_transition:
  transition_id: "AGT-20260804-CONTROL-PROTOCOL-08"
  transition_kind: "GOVERNANCE_ONLY_NO_TASK_CLOSURE"
  exact_input_sha: "4c61a02e562830e248ce7178132e8609f53decde"
  closed_task:
    task_id: null
    previous_status: null
    final_status: null
    reviewed_output_sha: null
    reviewer_verdict: null
    reviewer_verdict_reference: null
    supervisor_gate: "GOVERNANCE_TRANSITION_ONLY__NO_STAGE9_GATE"
  preserved_pending_task:
    task_id: "STAGE9-JOINT-SHORT-SMOKE-RUN8-EVIDENCE"
    status: "AWAITING_INDEPENDENT_REVIEW"
    source_sha: "4c61a02e562830e248ce7178132e8609f53decde"
    evidence_root: "/mnt/DiskM/by/hk_stage9_4c61a0_staging8"
    overall_stage_9_pass_declared: false
  blocker:
    blocker_id: null
    previous_status: null
    final_status: null
  next_active_task:
    task_id: "CONTROL-PROTOCOL-08-EXECUTION-CONTRACT-AND-SUPERVISOR-SERVER-READ"
    status: "PENDING_INDEPENDENT_REVIEW"
    owner: "INT-EXECUTOR"
  owner: "INT-SUPERVISOR"
  repository_writer: "INT-EXECUTOR"
  runner_authorized: false
  stage_9_authorized: false
  stage_9_execution_authorized: false
  stage_10_or_later_authorized: false
  canonical_state_updated: true
  audit_records_appended:
    - "docs/agent-worklogs/integration-supervisor.md#entry-42--protocol-08-governance-dispatch"
    - "docs/agent-worklogs/integration-executor.md#entry-39--protocol-08-execution-contract-and-server-read-policy"
  verdict_only_followup_commit_allowed: false

last_closed_task:
  task_id: "CONTROL-PROTOCOL-06-POST-FAILURE-DIAGNOSIS-AUTO-DISPATCH"
  task_status: "PASS_CLOSED"
  reviewed_output_sha: "e12f81b27c8a70f373654ca46dac1cb7ef17bb5e"
  reviewer_verdict: "PASS"
  supervisor_gate: "PASS_CLOSED"

stage9_run8_evidence:
  source_sha: "4c61a02e562830e248ce7178132e8609f53decde"
  evidence_root: "/mnt/DiskM/by/hk_stage9_4c61a0_staging8"
  review_status: "AWAITING_INDEPENDENT_REVIEW"
  overall_stage_9_pass_declared: false
  evidence_mutated_by_protocol_08: false
  future_runner_authorized: false
  stage_9_execution_authorized: false
  stage_10_or_later_authorized: false
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
  task_id: "CONTROL-PROTOCOL-08-EXECUTION-CONTRACT-AND-SUPERVISOR-SERVER-READ"
  status: "PENDING_INDEPENDENT_REVIEW"
  owner: "INT-EXECUTOR"
  brief: "docs/integration/stage-briefs/CONTROL_PROTOCOL_08_EXECUTION_CONTRACT_AND_SUPERVISOR_SERVER_READ.md"

active_blocker: null

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

protocol_08:
  canonical_source: "docs/integration/stage-briefs/CONTROL_PROTOCOL_08_EXECUTION_CONTRACT_AND_SUPERVISOR_SERVER_READ.md"
  status: "PENDING_INDEPENDENT_REVIEW"
  execution_contract_fields:
    - "source_sha"
    - "working_directory"
    - "java_command"
    - "tool_version_commands"
    - "build_command"
    - "artifact_resolver"
    - "bundle_command"
    - "release_root"
    - "run_command"
    - "required_preconditions"
    - "hard_gates"
    - "diagnostics_only"
    - "forbidden_fallbacks"
  contract_priority: "SUPERVISOR_EXACT > STAGE_BRIEF > REPOSITORY_CANONICAL > RUNNER_EXPERIENCE"
  explicit_conflict_action: "CONTRACT_CONFLICT"
  preflight_correction_requires_zero_started_or_modified_state: true
  canonical_maven_wrapper_required: true
  system_maven_required: false
  supervisor_server_read_policy_defined: true
  supervisor_server_read_actual_capability_granted_by_docs: false
  supervisor_server_read_external_capability_status: "PENDING_UNLESS_VERIFIABLY_PRESENT"
  supervisor_server_read_budget:
    wall_clock_minutes_max: 15
    commands_max: 20
    filesystem_roots_max: 4
    returned_text_mb_max: 10
    full_root_recursive_scan_allowed: false
    state_mutation_allowed: false

execution_authority:
  authority_source: "INT-SUPERVISOR"
  runner_authorized: false
  stage_9_authorized: false
  stage_9_execution_authorized: false
  bounded_repair_authorized: false
  governance_transition_authorized: true
  protocol_08_commit_accessed_server: false
  protocol_08_commit_built_or_uploaded_bundle: false
  protocol_08_commit_started_smoke: false
  supervisor_server_read_actual_capability_granted: false
  formal_50it_authorized: false
  stage_10_or_later_authorized: false

control_transition_review:
  task_id: "CONTROL-PROTOCOL-08-EXECUTION-CONTRACT-AND-SUPERVISOR-SERVER-READ"
  status: "PENDING_ONE_FINAL_READ_ONLY_REVIEW"
  one_final_review_only: true
  pass_followup_commit_allowed: false
```

## Canonical interpretation

Protocol 08 is the active governance task pending one independent review. It
defines complete Runner execution contracts, narrowly gated preflight
correction, boundary-aware failure classification and bounded Supervisor
server-read verification. The server-read policy is not platform permission;
actual SSH/tool capability remains external and pending unless verified.

Run8 evidence under `/mnt/DiskM/by/hk_stage9_4c61a0_staging8` is preserved as
`AWAITING_INDEPENDENT_REVIEW`. This transition declares no overall Stage 9
PASS and performs no server evidence review.

Runner and Stage 9 execution remain unauthorized. No server,
bundle, release, smoke, formal 50-iteration, calibration, Stage 10 or later
work is authorized.

## Next action

Executor pushes this one bounded governance transition commit and reports only to
Supervisor. Supervisor verifies its exact SHA, parent and scope before one
read-only review. No follow-up run, Stage 9 gate or Stage 10 action is allowed
without a later explicit Supervisor decision.
