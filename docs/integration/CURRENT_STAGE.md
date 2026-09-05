# Current integration stage

This file contains compact current facts only. Prospective governance is in
[`INTEGRATION_POLICY.md`](INTEGRATION_POLICY.md), lane authority is in
[`agent-lanes.md`](../../agent-lanes.md), and detailed history remains in Git,
structured evidence, historical briefs and append-only worklogs.

```yaml
snapshot:
  reconciled_on: "2026-09-05"
  branch: "integration/hk-multimodal-cost-v1"
  repository_baseline_sha: "ef54d52"
  scope: "Canonical facts on this integration branch; work on other branches or in uncommitted candidate files is not implicitly adopted."

stage:
  stage_id: "STAGE11-JOINT-STABILITY-5-10-ITERATIONS"
  formal_state: "PASS_CLOSED"
  closure_commit: "de146a603ee203777d41f52150d832bbac5884d1"
  closure_scope: "Technical multimodal scoring, household/student joint selection and physical non-Taxi execution validation; not production equilibrium or calibration."
  brief: "docs/integration/stage-briefs/STAGE_11_JOINT_STABILITY_5_10_ITERATIONS.md"
  historical_execution_contract: "data/transport_costs/hongkong/integration_stage11_contract_v1/stage11_joint_stability_execution_contract.json"
  historical_contract_note: "The contract preserves the pre-run BLOCKED repair state and is audit history, not the current control-plane state."

closure_evidence:
  fixed_canonical_10_iteration_run:
    status: "PASS_COMPLETED_ITERATIONS_0_THROUGH_10_TAXI_RUNTIME_NOT_COVERED"
    exit_code: 0
    evidence: "data/transport_costs/hongkong/integration_stage11_contract_v1/stage11_direct_10it_fixed_plans_20260805_success.json"
  taxi_native_44000_10_iteration_run:
    status: "SUCCESS"
    exit_code: 0
    iterations_completed: "0..10"
    taxi_legs: 44000
    ride_legs: 0
    evidence: "data/taxi/hongkong/processed/taxi_44000_no_ride_student_swap_v1/stage11_no_ride_10it_20260806_success.json"
  physical_nontaxi_gate:
    status: "VALIDATED_WITH_NETWORK_STUCK_LIMITATIONS"
    run: "/mnt/DiskM/by/hk_stage11_student_school_mode_20260809_run57"
    iterations_completed: "0..1"
    exit_code: 0
    household_bindings_selected: 4003
    household_bindings_completed: 3895
    school_bus_departures: 1002
    school_bus_boardings: 1002
    school_bus_alightings: 1001
    terminal_onboard_school_bus_students: 1
    evidence:
      - "runs/hongkong/run_manifest.json#stage11_physical_nontaxi_walk_timing_repair_iterations_0_1_run57"
      - "/mnt/DiskM/by/hk_stage11_student_school_mode_20260809_run57/physical_nontaxi_audit.json"
      - "/mnt/DiskM/by/hk_stage11_student_school_mode_20260809_run57/student_school_mode_choice_audit.json"

known_limitations:
  - "The first fixed-canonical run did not execute Taxi legs; the later Taxi-native 44,000-leg run supplies that runtime coverage."
  - "Run57 disables ordinary PT seat constraints and freezes ordinary innovation, so it is a mechanical gate rather than PT-capacity or equilibrium evidence."
  - "One correctly boarded school-bus passenger remains aboard a traffic-stuck vehicle at the 30:00 horizon."
  - "Taxi remains the only directly teleported main mode in run57."

production_baseline:
  current_final_run: "formal_50it_ptfixed_ferry_activity"
  manifest: "runs/hongkong/run_manifest.json"
  stage11_replaces_current_final_run: false
  reason: "Stage 11 outputs are technical validation and sensitivity runs, not adopted production outputs."

experiment_tracking:
  registry: "runs/hongkong/experiment_registry.csv"
  registry_scope: "Major immutable technical fixes and calibration experiments since Stage 11; repeated startup-only failures are linked through supersedes instead of receiving separate rows."
  latest_successful_experiment: "CAL-GV4-PV32332-JOINTRELAX-TAXIWAIT-PCE0195-01"
  latest_success_definition: "Latest experiment to complete its declared technical execution and audit; this is not a production-baseline or calibration-pass designation."
  gradev2_run2:
    status: "TECHNICAL_SUCCESS_CALIBRATION_REJECTED_NOT_ADOPTED"
    source_git_sha: "6884cc53e16bd20a4faa09547c1d5eb59d34a2ec"
    implementation_git_sha: "3e6a3781fe63d49fc67cc4eb305fe6104664fc67"
    audit_git_sha: "8b7db746931e8ba739dc76bfda57f6d95b0212a5"
    jar_sha256: "024a899bd51d33dfc41cc99abc4b59b251342ad78488c3cef22e85e36a1ec10b"
    prepared_plans_sha256: "fbc084d7f7af7eb2f5be400f443b566ed70269dfb49eae59a5190253747dabdd"
    payload: "/mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260826_gradev2_payload2"
    release: "/mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260826_gradev2_release2"
    run: "/mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260826_gradev2_run2"
    audit: "/mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260826_gradev2_audit1"
    iterations_completed: "0..21"
    exit_code: 0
    joint_selection_iterations: [5, 15]
    taxi_request_completion_pct: 99.9971
    school_bus_trips: 8792
    taxi_share_pct: 9.2994
    walk_share_pct: 5.0203
    walk_mean_minutes: 21.329
    total_completion_pct: 99.0717
    parser_caveat: "The d2_summary.json D2 scoring labels are inherited from the reused parser; run_metadata.json and the startup HK_SCORING_GRADE record are authoritative for GradeV2."
  candidate12_assessment: "NOT_READY"
  candidate12_name_reserved: false
  candidate12_reason: "CAL-GV2-02 is a scoring and selector calibration experiment layered on Candidate5B road supply and Candidate11 signals, and it still fails Taxi-share, Walk and total-completion gates."
  production_baseline_changed: false

latest_external_sensitivity:
  status: "TECHNICAL_SUCCESS_SENSITIVITY_NOT_ADOPTED"
  experiment: "CAL-GV4-PV32332-JOINTRELAX-TAXIWAIT-PCE0195-01"
  source_git_sha: "5a2a82cc8c96e639597c84b2c9fde4ce7f1bcca8"
  jar_sha256: "0aeefaa6381035b5fc92dc314d15b9b09d45de1033b716f9ea0c0975bd892423"
  run: "/mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260904_gradev4_pv32332_jointrelax_taxiwait_pce0195_run2"
  audit: "/mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260904_gradev4_pv32332_jointrelax_taxiwait_pce0195_audit3"
  authoritative_analysis: "analysis3"
  iterations_completed: "0..31"
  exit_code: 0
  production_adopted: false
  branch_boundary: "The server run belongs to a separate Taxi DVRP development history and used the Candidate11 traffic-signal path; this integration branch does not implicitly contain or adopt that implementation."
  handoff: "docs/HONG_KONG_CURRENT_STATUS_AND_HANDOFF.md"

post_stage11_work:
  traffic_signal_pilots:
    status: "MECHANICALLY_VALIDATED_NOT_ADOPTED"
    implementation_commits:
      - "caf2187a3230aed640dddebbc6371b568483e7ae"
      - "2b5ab0256345914f872b28afb7b3e0ae050b0cf3"
    boundary: "The eight-junction AM/PM pilot worsened production-performance indicators; diagram-inferred v2 has no runtime adoption."
    evidence: "docs/HONG_KONG_TRAFFIC_SIGNAL_MATSIM_ADOPTION_DESIGN.md"
  bounded_road_repairs:
    status: "SENSITIVITY_VALIDATED_NOT_ADOPTED"
    implementation_commit: "2b5ab0256345914f872b28afb7b3e0ae050b0cf3"
    boundary: "Opt-in repaired-network runs remain diagnostic and do not replace the current production network or run manifest."
    evidence: "docs/HONG_KONG_NO_SIGNAL_ROAD_RUNTIME_AUDIT.md"

active_control_plane:
  active_task: null
  active_blocker: null
  runner_authorized: false
  stage12_or_later_authorized: false
  calibration_authorized: false
  production_adoption_authorized: false

next_action: "Use docs/HONG_KONG_CURRENT_STATUS_AND_HANDOFF.md as the new-conversation entry point. Before another server run or production adoption, explicitly choose whether and how to integrate the separate Taxi-branch implementation; do not infer adoption from successful sensitivity evidence."
```

Stage 11 is closed as a technical validation stage. The old canonical-hash
failure and its replacement identities remain immutable history, not active
blockers. The adopted 50-iteration production baseline is unchanged, and the
later traffic-signal and road-repair work remains opt-in sensitivity evidence.
The later GradeV4/PV32,332/JointRelax/TaxiWait/PCE experiment is also recorded
as external sensitivity evidence only; its implementation is not silently
adopted by this branch.
