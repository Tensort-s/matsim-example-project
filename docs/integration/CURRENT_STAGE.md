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
  stage_id: "STAGE10-DETERMINISTIC-MULTIMODAL-COST-COVERAGE"
  formal_state: "RUNNING"
  source_sha: "48686c03f46372e4aed2bc9bd1bdeb1796a34fbe"
  closure_control_sha: null
  run_identity: null
  reviewer_verdict: null
  evidence:
    directed_validation: "data/transport_costs/hongkong/integration_stage10_validation_v1/stage10_directed_multimodal_cost_coverage_validation.json"
    stage_brief: "docs/integration/stage-briefs/STAGE_10_DETERMINISTIC_MULTIMODAL_COST_COVERAGE.md"

active_task:
  task_id: "STAGE10-DETERMINISTIC-MULTIMODAL-COST-COVERAGE"
  owner: "INT-EXECUTOR"
  objective: "Deterministically trigger Taxi, PT and Car costs in one bounded test subset and prove exactly-once charging."
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

stage10_coverage:
  fixture_id: "stage10-directed-multimodal-cost-v1"
  person_id: "stage10-directed-001"
  taxi_legs: 1
  pt_legs: 1
  car_legs: 1
  expected_total_fee_hkd: 42.7
  exactly_once_negative_test: "duplicate taxi/PT/Car experienced legs fail closed"

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
  stage10_implementation_authorized: true
  stage11_or_later_authorized: false
  stage_9_execution_authorized: false
  user_controls_research_economic_behavioral_policy_semantics: true

next_action: "Executor pushes the deterministic candidate and stops for one Protocol 09 stage-end review"
```

Stage 9 remains `PASS_CLOSED`; Stage 10 is now `RUNNING` as a test-only,
deterministic coverage task. No Runner, server, bundle, release, or Stage 11
action is authorized.
