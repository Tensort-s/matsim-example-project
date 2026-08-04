# Current integration stage

This is the compact canonical state. Stable governance is in
[`INTEGRATION_POLICY.md`](INTEGRATION_POLICY.md), lane authority is in
[`agent-lanes.md`](../../agent-lanes.md), and historical detail remains in Git
history, [stage briefs](stage-briefs/README.md), structured evidence and
append-only worklogs.

```yaml
stage:
  stage_id: "STAGE9-JOINT-SHORT-SMOKE"
  formal_state: "PASS_CLOSED"
  source_sha: "4c61a02e562830e248ce7178132e8609f53decde"
  final_control_sha: "e9bc965721b7842c7bfaaeb549ee08de038454c4"
  run_identity: "smoke_qsim_v1_4c61a0_run8"
  reviewer_verdict: "PASS"
  evidence:
    binding: "data/transport_costs/hongkong/integration_stage9_run8_evidence_v1/stage9_run8_evidence_binding.json"
    final_audit: "docs/integration/stage-briefs/STAGE_09_RUN8_EVIDENCE_REVIEW_AND_CLOSURE.md"
    server_diagnosis_path: "/mnt/DiskM/by/hk_stage9_4c61a0_staging8/evidence/diagnosis_run8_evidence_verification_011/diagnosis.json"
    server_diagnosis_sha256: "a72234de370376a1c7b3554f68b96e950f233d319889808afd86c2ff78203e46"

active_task: null
active_blocker: null

coverage_debt:
  debt_id: "STAGE9-TAXI-RUNTIME-NOT-EXERCISED"
  status: "OPEN_NON_BLOCKING"
  evidence:
    taxi_leg_count: 0
    taxi_routing_mode_count: 0
    mode_detail_taxi_person_count: 47
    money_or_cost_event_count: 0
    taxi_fare_exercised: false
    exactly_once_exercised: false
  implication: "Run8 does not establish Taxi runtime fare, event or exactly-once behavioral coverage."
  required_before:
    - "any claim that a later candidate has exercised Taxi runtime fare and exactly-once behavior"
    - "any freeze or formal-run gate whose stated acceptance requires that Taxi runtime coverage"

review_policy:
  default: "STAGE_END_ONLY"
  intermediate_review_default: "NO_INTERMEDIATE_REVIEW"
  targeted_review_max_per_stage: 1
  targeted_review_scope: "ONE_NARROW_HIGH_RISK_QUESTION"
  targeted_review_replaces_stage_end_review: false
  executor_self_check_replaces_reviewer: false
  runner_self_check_replaces_reviewer: false
  candidate_protocol: "docs/integration/stage-briefs/CONTROL_PROTOCOL_09_LEAN_STAGE_END_REVIEW.md"

protocol_09_candidate:
  task_id: "CONTROL-PROTOCOL-09-LEAN-STAGE-END-REVIEW"
  exact_input_sha: "e9bc965721b7842c7bfaaeb549ee08de038454c4"
  status: "READY_FOR_SUPERVISOR_SHA_VERIFICATION_AND_STAGE_END_REVIEW"
  substantive_delta: "governance-only stage-end review migration"

authority:
  supervisor_is_sole_dispatch_and_gate_owner: true
  executor_is_sole_git_writer: true
  reviewer_is_read_only: true
  runner_has_no_git_writes: true
  runner_authorized: false
  stage_10_or_later_authorized: false
  user_controls_research_economic_policy_semantics: true

next_action: "AWAITING_USER_OR_SUPERVISOR_STAGE10_DECISION"

historical_protocols:
  protocol_05:
    status: "HISTORICAL_DETAIL__CONSOLIDATED_BY_PROTOCOL_09"
    source: "docs/integration/stage-briefs/CONTROL_PROTOCOL_05_ATOMIC_GATE_TRANSITION.md"
  protocol_06:
    status: "HISTORICAL_DETAIL__CONSOLIDATED_BY_PROTOCOL_09"
    source: "docs/integration/stage-briefs/CONTROL_PROTOCOL_06_POST_FAILURE_DIAGNOSIS_AUTO_DISPATCH.md"
  protocol_07:
    status: "HISTORICAL_DETAIL__CONSOLIDATED_BY_PROTOCOL_09"
    source: "docs/integration/stage-briefs/CONTROL_PROTOCOL_07_DIAGNOSIS_CONFIDENCE_AND_BUDGET.md"
  protocol_08:
    status: "HISTORICAL_DETAIL__CONSOLIDATED_BY_PROTOCOL_09"
    source: "docs/integration/stage-briefs/CONTROL_PROTOCOL_08_EXECUTION_CONTRACT_AND_SUPERVISOR_SERVER_READ.md"

retained_invariants:
  exact_source_artifact_bundle_release_run_traceability: true
  immutable_run_directories: true
  implicit_rerun_allowed: false
  post_failure_diagnosis_read_only: true
  root_cause_statuses: ["KNOWN", "PARTIAL", "UNKNOWN"]
  diagnosis_budget_retained: true
  execution_contract_retained: true
  bounded_supervisor_server_read_retained: true
  semantic_failure_escalates_to_user: true
  validator_pass_equals_stage_pass: false
  self_check_equals_independent_review: false
```

Stage 9 remains `PASS_CLOSED`. The Taxi coverage debt is explicit and
non-blocking for that closed stage; it prevents unsupported future coverage
claims. No Runner, Stage 10 or server action is authorized. Protocol 09 is a
candidate until Supervisor verifies its pushed SHA and dispatches one
stage-end review.
