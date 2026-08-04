# Current integration stage

This is the canonical compact state record. Stable rules are in
[`INTEGRATION_POLICY.md`](INTEGRATION_POLICY.md); lane identity and write scope
are in [`agent-lanes.md`](../../agent-lanes.md). It records the latest valid
Supervisor gate, not a queue of historical worklog events.

```yaml
atomic_gate_transition:
  transition_id: "AGT-20260804-STAGE9-RUN8-FINAL-EVIDENCE-CLOSURE"
  transition_kind: "SUBSTANTIVE_FINAL_EVIDENCE_AUDIT_AND_STAGE_CLOSURE"
  exact_input_sha: "101afd5beb6d1351448aea406608119d2f4ba869"
  closed_task:
    task_id: "STAGE9-REPAIR-RUN8-EVIDENCE-BINDING-012"
    previous_status: "PENDING_INDEPENDENT_REVIEW"
    final_status: "PASS_CLOSED"
    reviewed_output_sha: "101afd5beb6d1351448aea406608119d2f4ba869"
    reviewer_verdict: "PASS"
    reviewer_verdict_reference: "INT-SUPERVISOR transferred exact-SHA Reviewer PASS in the STAGE9-RUN8-EVIDENCE-REVIEW-AND-CLOSURE authorization"
    supervisor_gate: "PASS_CLOSED"
  stage_closure:
    task_id: "STAGE9-JOINT-SHORT-SMOKE"
    previous_status: "BLOCKED_SUPERSEDED_BY_REPAIR"
    final_status: "PASS_CLOSED"
    run_identity: "smoke_qsim_v1_4c61a0_run8"
    reviewed_evidence_sha: "101afd5beb6d1351448aea406608119d2f4ba869"
  blocker:
    blocker_id: "STAGE9-RUN8-EVIDENCE-UNVERIFIED-001"
    previous_status: "REPAIR_DISPATCHED"
    final_status: "CLOSED"
  next_active_task:
    task_id: null
    status: "AWAITING_USER_OR_SUPERVISOR_STAGE10_DECISION"
    owner: null
  owner: "INT-SUPERVISOR"
  repository_writer: "INT-EXECUTOR"
  runner_authorized: false
  stage_9_authorized: false
  stage_9_execution_authorized: false
  stage_10_or_later_authorized: false
  canonical_state_updated: true
  audit_records_appended:
    - "docs/agent-worklogs/integration-supervisor.md#entry-44--stage-9-final-evidence-audit-and-closure"
    - "docs/agent-worklogs/integration-executor.md#entry-41--stage-9-final-evidence-audit-and-closure"
    - "docs/agent-worklogs/integration-reviewer.md#entry-17--stage-9-run8-evidence-binding-exact-sha-review"
  verdict_only_followup_commit_allowed: false

last_closed_task:
  task_id: "STAGE9-JOINT-SHORT-SMOKE"
  task_status: "PASS_CLOSED"
  reviewed_output_sha: "101afd5beb6d1351448aea406608119d2f4ba869"
  reviewer_verdict: "PASS"
  supervisor_gate: "PASS_CLOSED"

stage9_run8_evidence:
  source_sha: "4c61a02e562830e248ce7178132e8609f53decde"
  source_git_tree_sha: "125a329d0d9a9414b89a90dc89a1d81530f2fe30"
  staging_root: "/mnt/DiskM/by/hk_stage9_4c61a0_staging8"
  release_root: "/mnt/DiskM/by/hk_multimodal_cost_4c61a0_stage9_release8"
  run_identity: "smoke_qsim_v1_4c61a0_run8"
  execution_exit_code: 0
  last_iteration: 0
  population_person_count: 7716
  events_count: 48287273
  release_sha256sums_ok: 420
  release_sha256sums_failed: 0
  nonfinite_score_count: 0
  java_version: "25.0.3"
  matsim_version: "2026.0"
  evidence_review_status: "PASS_CLOSED"
  binding_repair_status: "PASS_CLOSED"
  reviewed_binding_sha: "101afd5beb6d1351448aea406608119d2f4ba869"
  reviewer_verdict: "PASS"
  server_diagnosis_path: "/mnt/DiskM/by/hk_stage9_4c61a0_staging8/evidence/diagnosis_run8_evidence_verification_011/diagnosis.json"
  server_diagnosis_sha256: "a72234de370376a1c7b3554f68b96e950f233d319889808afd86c2ff78203e46"
  pushed_binding: "data/transport_costs/hongkong/integration_stage9_run8_evidence_v1/stage9_run8_evidence_binding.json"
  overall_stage_9_pass_declared: true
  stuck_and_abort_diagnostic:
    total: 74
    hong_kong_person: 11
    bus: 11
    gmb: 52
    time_seconds: 108000
    cause_attribute_present: false
    classification: "DIAGNOSTIC_NOT_HARD_GATE"
  taxi_coverage_limitation:
    taxi_leg_count: 0
    taxi_routing_mode_count: 0
    mode_detail_taxi_person_count: 47
    money_or_cost_event_count: 0
    taxi_fare_exercised: false
    exactly_once_exercised: false
    taxi_behavioral_coverage_claimed: false
  evidence_or_run_mutated_by_binding_repair: false
  future_runner_authorized: false
  stage_9_execution_authorized: false
  stage_10_or_later_authorized: false
  brief: "docs/integration/stage-briefs/STAGE_09_RUN8_EVIDENCE_REVIEW_AND_CLOSURE.md"

preserved_artifact_discovery_repair_010:
  task_id: "STAGE9-REPAIR-ARTIFACT-DISCOVERY-010"
  repair_sha: "4c61a02e562830e248ce7178132e8609f53decde"
  task_status: "PASS_CLOSED"
  final_status: "PASS_CLOSED"
  blocker_id: "STAGE9-RUNNER-SHADE-CLOSURE-002"
  blocker_status: "CLOSED"
  closure_recorded: true
  canonical_contract_unchanged: true
  brief: "docs/integration/stage-briefs/STAGE_09_REPAIR_ARTIFACT_DISCOVERY_010.md"
  evidence: "data/transport_costs/hongkong/integration_stage9_repair_010_validation_v1/stage9_artifact_discovery_validation.json"

artifact_discovery_blocker:
  blocker_id: "STAGE9-RUNNER-SHADE-CLOSURE-002"
  final_status: "CLOSED"

stage_9:
  task_id: "STAGE9-JOINT-SHORT-SMOKE"
  run_identity: "smoke_qsim_v1_4c61a0_run8"
  reviewed_evidence_sha: "101afd5beb6d1351448aea406608119d2f4ba869"
  reviewer_verdict: "PASS"
  final_status: "PASS_CLOSED"
  next_state: "AWAITING_USER_OR_SUPERVISOR_STAGE10_DECISION"

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

active_task: null

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
  status: "PASS_CLOSED"
  final_status: "PASS_CLOSED"
  reviewed_sha: "e58861e4f79eb5aa18c8ac286d0173987bcef237"
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
  final_status: "PASS_CLOSED"
  reviewed_sha: "b32bef0398ebe44187c088c22e2b5276fa260ac0"
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
  bounded_repair_authorized: false
  governance_transition_authorized: false
  protocol_08_commit_accessed_server: false
  protocol_08_commit_built_or_uploaded_bundle: false
  protocol_08_commit_started_smoke: false
  supervisor_server_read_actual_capability_granted: false
  formal_50it_authorized: false
  stage_10_or_later_authorized: false

control_transition_review:
  task_id: "STAGE9-RUN8-EVIDENCE-REVIEW-AND-CLOSURE"
  status: "PASS_CONSUMED_AND_ATOMIC_CLOSURE_RECORDED"
  reviewed_sha: "101afd5beb6d1351448aea406608119d2f4ba869"
  reviewer_verdict: "PASS"
  one_final_review_completed: true
  pass_followup_commit_allowed: false

next_state: "AWAITING_USER_OR_SUPERVISOR_STAGE10_DECISION"
```

## Canonical interpretation

Reviewer returned `PASS` for exact evidence-binding SHA
`101afd5beb6d1351448aea406608119d2f4ba869`. This substantive final audit
consumes that verdict, closes the run8 evidence blocker and records Stage 9 as
`PASS_CLOSED`; it is not a verdict-only or closure-only transaction.

Protocol 07, artifact-discovery repair 010 and Protocol 08 are
`PASS_CLOSED`; artifact-discovery blocker
`STAGE9-RUNNER-SHADE-CLOSURE-002` is `CLOSED`. Run8 retains its exact source,
staging, release and run identity. Its immutable diagnosis path/SHA, checksum,
iteration, population, event and finite-score evidence remain bound in the
structured audit.

The 74 stuck records remain Diagnostic. Zero Taxi legs and zero money/cost
events mean Taxi fare and exactly-once charging were not exercised. Stage 9
technical closure makes no Taxi behavioral-coverage claim beyond run8.

Runner and Stage 9 execution remain unauthorized. No server,
bundle, release, smoke, formal 50-iteration, calibration, Stage 10 or later
work is authorized.

## Next action

Executor pushes this one final audit/closure transition and reports only to
Supervisor. Then the canonical state is
`AWAITING_USER_OR_SUPERVISOR_STAGE10_DECISION`. No rerun, Runner, future Stage
9 execution or Stage 10 action is allowed without a later explicit decision.
