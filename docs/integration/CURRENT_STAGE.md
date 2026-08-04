# Current integration stage

This file contains compact current facts only. Prospective governance is in
[`INTEGRATION_POLICY.md`](INTEGRATION_POLICY.md), lane authority is in
[`agent-lanes.md`](../../agent-lanes.md), and the canonical review/diagnosis/
execution contract is self-contained in
[`CONTROL_PROTOCOL_09_LEAN_STAGE_END_REVIEW.md`](stage-briefs/CONTROL_PROTOCOL_09_LEAN_STAGE_END_REVIEW.md).
Detailed history remains in Git, structured evidence, historical stage briefs,
and append-only worklogs.

```yaml
stage:
  stage_id: "STAGE9-JOINT-SHORT-SMOKE"
  formal_state: "PASS_CLOSED"
  source_sha: "4c61a02e562830e248ce7178132e8609f53decde"
  closure_control_sha: "e9bc965721b7842c7bfaaeb549ee08de038454c4"
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
  owner: "INT-SUPERVISOR"
  evidence:
    taxi_leg_count: 0
    taxi_routing_mode_count: 0
    mode_detail_taxi_person_count: 47
    money_or_cost_event_count: 0
    taxi_fare_exercised: false
    exactly_once_exercised: false
  interpretation:
    mode_detail_taxi_equals_taxi_leg: false
    statement: "modeDetail=taxi persons do not establish executed Taxi legs or routingMode=taxi behavior."
  implication: "Run8 does not establish Taxi runtime fare, money-event or exactly-once behavioral coverage."
  closure_criteria:
    taxi_leg_count: ">0"
    taxi_routing_mode_count: ">0"
    taxi_fare_or_money_event_count: ">0"
    exactly_once_validation: "PASS"
    independent_stage_end_review: "PASS"
  required_before:
    - "any claim that a later candidate exercised Taxi runtime fare and exactly-once behavior"
    - "any freeze or formal-run gate whose stated acceptance requires Taxi runtime coverage"

review_policy:
  default: "STAGE_END_ONLY"
  intermediate_review_default: "NO_INTERMEDIATE_REVIEW"
  targeted_review_max_per_stage: 1
  targeted_review_exception: "ONE_NARROW_HIGH_RISK_QUESTION"
  targeted_review_replaces_stage_end_review: false
  executor_self_check_replaces_reviewer: false
  runner_self_check_replaces_reviewer: false
  canonical_protocol: "docs/integration/stage-briefs/CONTROL_PROTOCOL_09_LEAN_STAGE_END_REVIEW.md"

protocol_09_revision_candidate:
  task_id: "CONTROL-PROTOCOL-09-CANONICAL-CONSOLIDATION-AND-FAILURE-OWNERSHIP"
  exact_input_sha: "16398c7883945bc82cdf521b727c6ef502273e79"
  status: "READY_FOR_SINGLE_STAGE_END_REVIEW"
  substantive_delta: "self-contained canonical governance, failure ownership, and deprecation of Protocols 05-08"

authority:
  supervisor_is_sole_dispatch_and_gate_owner: true
  executor_is_sole_git_writer: true
  reviewer_is_read_only: true
  runner_has_no_git_writes: true
  runner_authorized: false
  stage_9_execution_authorized: false
  stage_10_or_later_authorized: false
  user_controls_research_economic_behavioral_policy_semantics: true

next_action: "AWAITING_USER_OR_SUPERVISOR_STAGE10_DECISION"
```

Stage 9 remains `PASS_CLOSED`; Protocol 09 consolidation does not reopen or run
it. Taxi coverage debt remains explicit and non-blocking for the closed smoke,
while preventing unsupported future coverage claims. No Runner, Stage 9,
Stage 10, server, bundle, release, or run action is authorized.
