# Current integration stage

This file contains compact current facts only. Prospective governance is in
[`INTEGRATION_POLICY.md`](INTEGRATION_POLICY.md), lane authority is in
[`agent-lanes.md`](../../agent-lanes.md), and the self-contained review,
diagnosis and execution rules are in
[`CONTROL_PROTOCOL_09_LEAN_STAGE_END_REVIEW.md`](stage-briefs/CONTROL_PROTOCOL_09_LEAN_STAGE_END_REVIEW.md).
Detailed history remains in Git, structured evidence, historical briefs and
append-only worklogs.

```yaml
stage:
  stage_id: "STAGE11-JOINT-STABILITY-5-10-ITERATIONS"
  formal_state: "READY"
  source_sha: "3ed98c4b8b34491a3c6f9fdf3517812323baed76"
  review_base_sha: "3ed98c4b8b34491a3c6f9fdf3517812323baed76"
  objective: "Prepare two separately authorized, immutable 5- and 10-iteration joint stability identities without calibration or model change."
  brief: "docs/integration/stage-briefs/STAGE_11_JOINT_STABILITY_5_10_ITERATIONS.md"
  structured_contract: "data/transport_costs/hongkong/integration_stage11_contract_v1/stage11_joint_stability_execution_contract.json"

previous_stage:
  stage_id: "STAGE10-DETERMINISTIC-MULTIMODAL-COST-COVERAGE"
  formal_state: "PASS_CLOSED"
  reviewed_output_sha: "3ed98c4b8b34491a3c6f9fdf3517812323baed76"
  reviewer_verdict: "PASS"
  directed_fixture:
    taxi_legs: 1
    taxi_routing_mode_taxi: 1
    pt_legs: 1
    car_legs: 1
    observed_cost_hkd: {taxi: 35.3, pt: 4.9, car: 2.5, total: 42.7}
    exactly_once_negative_tests: "PASS"
  evidence: "data/transport_costs/hongkong/integration_stage10_validation_v1/stage10_directed_multimodal_cost_coverage_validation.json"

active_task:
  task_id: "STAGE11-JOINT-STABILITY-5-10-ITERATIONS"
  owner: "INT-EXECUTOR"
  status: "CONTROL_PLANE_CANDIDATE_PENDING_STAGE_END_REVIEW"
active_blocker: null

planned_run_identities:
  source_binding: "The later Supervisor contract binds the exact reviewed Stage 11 candidate SHA whose sole parent is 3ed98c4b8b34491a3c6f9fdf3517812323baed76."
  five_iteration:
    last_iteration: 5
    identity_pattern: "joint_stability_5it_{authorized_source_sha8}_run1"
    new_staging_release_run_required: true
  ten_iteration:
    last_iteration: 10
    identity_pattern: "joint_stability_10it_{authorized_source_sha8}_run1"
    new_staging_release_run_required: true
  prior_run_or_release_reuse_allowed: false

coverage_contract:
  stage10_directed_multimodal_proof: "PASS_CLOSED"
  stage11_requires_actual_mode_counts: true
  production_taxi_zero_classification: "DIAGNOSTIC_AND_COVERAGE_LIMITATION"
  production_taxi_zero_establishes_taxi_runtime_coverage: false
  fixed_ownership_per_leg_allowed: false
  unresolved_numeric_zero_allowed: false
  duplicate_charge_allowed: false
  nonfinite_money_cost_score_allowed: false

review_policy:
  default: "STAGE_END_ONLY"
  review_base_sha: "3ed98c4b8b34491a3c6f9fdf3517812323baed76"
  targeted_review_default: "NO_INTERMEDIATE_REVIEW"
  executor_self_check_replaces_reviewer: false
  runner_self_check_replaces_reviewer: false
  canonical_protocol: "docs/integration/stage-briefs/CONTROL_PROTOCOL_09_LEAN_STAGE_END_REVIEW.md"

authority:
  supervisor_is_sole_dispatch_and_gate_owner: true
  executor_is_sole_git_writer: true
  reviewer_is_read_only: true
  runner_has_no_git_writes: true
  runner_authorized: false
  stage11_server_execution_authorized: false
  stage12_or_later_authorized: false
  calibration_authorized: false
  server_access_performed_by_executor: false

next_action: "Supervisor verifies the exact candidate then dispatches one Stage-end Reviewer; after Reviewer PASS, Supervisor may issue a separate exact Runner contract."
```

Stage 10 is synchronized as `PASS_CLOSED`; Stage 11 is `READY` only as a
control-plane candidate. No server access, build, bundle, release, run,
calibration, Runner authorization, or Stage 12 action is created here.
