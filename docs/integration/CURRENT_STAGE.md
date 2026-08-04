# Current integration stage

This is the canonical compact state record. Stable rules are in
[`INTEGRATION_POLICY.md`](INTEGRATION_POLICY.md); lane identity and write scope
are in [`agent-lanes.md`](../../agent-lanes.md). It records the latest valid
Supervisor gate, not a queue of historical worklog events.

```yaml
atomic_gate_transition:
  transition_id: "AGT-20260804-STAGE9-RUN8-EVIDENCE-BINDING-012"
  transition_kind: "SUBSTANTIVE_GOVERNANCE_AND_EVIDENCE_REPAIR"
  exact_input_sha: "b32bef0398ebe44187c088c22e2b5276fa260ac0"
  closed_task:
    task_id: "CONTROL-PROTOCOL-08-EXECUTION-CONTRACT-AND-SUPERVISOR-SERVER-READ"
    previous_status: "PENDING_INDEPENDENT_REVIEW"
    final_status: "PASS_CLOSED"
    reviewed_output_sha: "b32bef0398ebe44187c088c22e2b5276fa260ac0"
    reviewer_verdict: "PASS"
    reviewer_verdict_reference: "INT-SUPERVISOR transferred Protocol 08 PASS in the STAGE9-REPAIR-RUN8-EVIDENCE-BINDING-012 authorization"
    supervisor_gate: "PASS_CLOSED"
  superseded_task:
    task_id: "STAGE9-JOINT-SHORT-SMOKE-RUN8-EVIDENCE"
    previous_status: "AWAITING_INDEPENDENT_REVIEW"
    final_status: "BLOCKED_SUPERSEDED_BY_REPAIR"
    source_sha: "4c61a02e562830e248ce7178132e8609f53decde"
    staging_root: "/mnt/DiskM/by/hk_stage9_4c61a0_staging8"
    release_root: "/mnt/DiskM/by/hk_multimodal_cost_4c61a0_stage9_release8"
    run_identity: "smoke_qsim_v1_4c61a0_run8"
    execution_exit_code: 0
    supersession_scope: "EVIDENCE_REVIEW_ONLY"
  blocker:
    blocker_id: "STAGE9-RUN8-EVIDENCE-UNVERIFIED-001"
    previous_status: "OPEN"
    final_status: "REPAIR_DISPATCHED"
  next_active_task:
    task_id: "STAGE9-REPAIR-RUN8-EVIDENCE-BINDING-012"
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
    - "docs/agent-worklogs/integration-supervisor.md#entry-43--stage-9-run8-evidence-binding-repair-dispatch"
    - "docs/agent-worklogs/integration-executor.md#entry-40--stage-9-run8-evidence-binding"
  verdict_only_followup_commit_allowed: false

last_closed_task:
  task_id: "CONTROL-PROTOCOL-08-EXECUTION-CONTRACT-AND-SUPERVISOR-SERVER-READ"
  task_status: "PASS_CLOSED"
  reviewed_output_sha: "b32bef0398ebe44187c088c22e2b5276fa260ac0"
  reviewer_verdict: "PASS"
  supervisor_gate: "PASS_CLOSED"

stage9_run8_evidence:
  source_sha: "4c61a02e562830e248ce7178132e8609f53decde"
  source_git_tree_sha: "125a329d0d9a9414b89a90dc89a1d81530f2fe30"
  staging_root: "/mnt/DiskM/by/hk_stage9_4c61a0_staging8"
  release_root: "/mnt/DiskM/by/hk_multimodal_cost_4c61a0_stage9_release8"
  run_identity: "smoke_qsim_v1_4c61a0_run8"
  execution_exit_code: 0
  evidence_review_status: "BLOCKED_SUPERSEDED_BY_REPAIR"
  binding_repair_status: "PENDING_INDEPENDENT_REVIEW"
  server_diagnosis_path: "/mnt/DiskM/by/hk_stage9_4c61a0_staging8/evidence/diagnosis_run8_evidence_verification_011/diagnosis.json"
  server_diagnosis_sha256: "a72234de370376a1c7b3554f68b96e950f233d319889808afd86c2ff78203e46"
  pushed_binding: "data/transport_costs/hongkong/integration_stage9_run8_evidence_v1/stage9_run8_evidence_binding.json"
  overall_stage_9_pass_declared: false
  evidence_or_run_mutated_by_binding_repair: false
  future_runner_authorized: false
  stage_9_execution_authorized: false
  stage_10_or_later_authorized: false
  brief: "docs/integration/stage-briefs/STAGE_09_RUN8_EVIDENCE_REVIEW_AND_CLOSURE.md"

preserved_artifact_discovery_repair_010:
  task_id: "STAGE9-REPAIR-ARTIFACT-DISCOVERY-010"
  task_status: "PENDING_INDEPENDENT_REVIEW_AND_SUPERVISOR_STAGE9_REPAIR_GATE"
  blocker_id: "STAGE9-RUNNER-SHADE-CLOSURE-002"
  blocker_status: "REPAIR_DISPATCHED"
  closure_recorded: false
  canonical_contract_unchanged: true
  brief: "docs/integration/stage-briefs/STAGE_09_REPAIR_ARTIFACT_DISCOVERY_010.md"
  evidence: "data/transport_costs/hongkong/integration_stage9_repair_010_validation_v1/stage9_artifact_discovery_validation.json"

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
  task_id: "STAGE9-REPAIR-RUN8-EVIDENCE-BINDING-012"
  status: "PENDING_INDEPENDENT_REVIEW"
  owner: "INT-EXECUTOR"
  brief: "docs/integration/stage-briefs/STAGE_09_RUN8_EVIDENCE_REVIEW_AND_CLOSURE.md"

active_blocker:
  blocker_id: "STAGE9-RUN8-EVIDENCE-UNVERIFIED-001"
  status: "REPAIR_DISPATCHED"
  failure_identity:
    source_sha: "4c61a02e562830e248ce7178132e8609f53decde"
    staging_root: "/mnt/DiskM/by/hk_stage9_4c61a0_staging8"
    release_root: "/mnt/DiskM/by/hk_multimodal_cost_4c61a0_stage9_release8"
    run_identity: "smoke_qsim_v1_4c61a0_run8"
    execution_exit_code: 0
    evidence_failure: "Exact run8 server evidence was not bound to a pushed source-labelled record for independent exact-SHA review."
  root_cause: "The immutable Runner diagnosis existed only at a server path and its compact identity, hard-gate facts, diagnostics and limitations were absent from pushed control-plane evidence."
  changed_hypothesis_required_for_retry: "Bind the immutable diagnosis path and SHA, exact run identity, transferred checks and explicit Taxi-not-exercised limitation in a committed structured summary without rerun or server mutation."
  repair_task_id: "STAGE9-REPAIR-RUN8-EVIDENCE-BINDING-012"
  repair_owner: "INT-EXECUTOR"
  replacement_identity_required:
    - "new pushed evidence-binding SHA"
    - "same immutable run8 source, staging, release and run identity"
    - "one independent exact-SHA review of the pushed binding"
  superseded_run_identity:
    source_sha: "4c61a02e562830e248ce7178132e8609f53decde"
    staging_root: "/mnt/DiskM/by/hk_stage9_4c61a0_staging8"
    release_root: "/mnt/DiskM/by/hk_multimodal_cost_4c61a0_stage9_release8"
    run_identity: "smoke_qsim_v1_4c61a0_run8"
    reuse_or_rerun_allowed: false
  superseded_stage_status: "BLOCKED_SUPERSEDED_BY_REPAIR"
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
  status: "PASS_CLOSED"
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
  status: "PASS_CLOSED"
  reviewed_output_sha: "b32bef0398ebe44187c088c22e2b5276fa260ac0"
  reviewer_verdict: "PASS"
  closure_consumed_by_task: "STAGE9-REPAIR-RUN8-EVIDENCE-BINDING-012"
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
  bounded_repair_authorized: true
  authorized_repair_task: "STAGE9-REPAIR-RUN8-EVIDENCE-BINDING-012"
  governance_transition_authorized: false
  protocol_08_commit_accessed_server: false
  protocol_08_commit_built_or_uploaded_bundle: false
  protocol_08_commit_started_smoke: false
  supervisor_server_read_actual_capability_granted: false
  formal_50it_authorized: false
  stage_10_or_later_authorized: false

control_transition_review:
  task_id: "STAGE9-REPAIR-RUN8-EVIDENCE-BINDING-012"
  status: "PENDING_ONE_FINAL_READ_ONLY_REVIEW"
  one_final_review_only: true
  pass_followup_commit_allowed: false
```

## Canonical interpretation

Protocol 08 is `PASS_CLOSED`. This atomic transition consumes that verdict
while performing the substantive run8 evidence-binding repair; it is not a
closure-only commit. Protocol 07 remains `PASS_CLOSED`.

Runner diagnosis 011 is bound by exact server path and SHA256 to the pushed
structured summary. Run8 keeps its exact source, staging, release and run
identity. Its process exited zero, but the prior evidence-review task is
`BLOCKED_SUPERSEDED_BY_REPAIR` and the binding remains
`PENDING_INDEPENDENT_REVIEW`. The 74 stuck records are Diagnostic. Zero Taxi
legs and zero money/cost events mean Taxi fare and exactly-once charging were
not exercised, so this transition declares no overall Stage 9 PASS.

Artifact-discovery repair 010 and blocker
`STAGE9-RUNNER-SHADE-CLOSURE-002` retain their prior pending/
`REPAIR_DISPATCHED` statuses. This task does not close them.

Runner and Stage 9 execution remain unauthorized. No server,
bundle, release, smoke, formal 50-iteration, calibration, Stage 10 or later
work is authorized.

## Next action

Executor pushes this one bounded evidence/governance repair and reports only
to Supervisor. Supervisor verifies its exact SHA, parent and scope before one
read-only review. No rerun, Stage 9 execution, Stage 9 final gate or Stage 10
action is allowed without a later explicit Supervisor decision.
