# INT-EXECUTOR append-only worklog

This file is an append-only audit record. Never edit or delete an earlier
entry. Corrections, session replacements, and superseding decisions must be
appended as new entries.

## Session history

- Current session: `019fb38f-c992-74f1-9894-c6009784a697`

## Entry 1 — Stage 0 registration and initialization

```yaml
timestamp: "2026-07-30T23:10:41+08:00"
session_id: "019fb38f-c992-74f1-9894-c6009784a697"
stage_id: "Stage 0"
input_commit_sha: "a3d6445cfd79a74b6fd6bd01e547d7df8055a64d"
source_branch_shas:
  taxi: "aa0d4794fa3af8458c906db1614fd418893e4bd4"
  pt: "0b0ce90375b9e3d0c055fa46c5a3b96bfc3a5103"
  car: "fc906efd3afb98e027cc6cca44060dec9e32aa46"
actions_or_observations:
  - "Accepted the INT-EXECUTOR lane as the sole integration worktree and branch writer."
  - "Verified the worktree path, integration branch, baseline HEAD, baseline ancestry, and initially clean status."
  - "Read AGENTS.md, docs/PROJECT_ONBOARDING.md, docs/HONG_KONG_FINAL_WORKFLOW.md, cities/hongkong/city.yaml, runs/hongkong/run_manifest.json, and relevant locked-feature workflow documents before writing."
  - "Received all four actual lane IDs and faithfully transcribed the three external lane Stage 0 handoffs."
  - "Created the lane registry, append-only worklogs, and minimal onboarding entry points."
  - "Did not merge Taxi, PT, or Car and did not begin Stage 1."
evidence_paths:
  - "agent-lanes.md"
  - "docs/agent-worklogs/integration-supervisor.md"
  - "docs/agent-worklogs/integration-executor.md"
  - "docs/agent-worklogs/integration-runner.md"
  - "docs/agent-worklogs/integration-reviewer.md"
  - "docs/PROJECT_ONBOARDING.md"
decisions:
  - "Stage 0 changes are limited to the agent control plane and the minimal onboarding links."
  - "cities/hongkong/city.yaml and runs/hongkong/run_manifest.json remain unchanged because no adopted Hong Kong input, configuration, output, or final run changed."
  - "No feature merge or Stage 1 action is authorized by this initialization."
hard_gate_status: "PENDING_STAGE_0_COMMIT_PUSH_AND_INDEPENDENT_REVIEW"
diagnostic_findings:
  - "The local Taxi feature worktree shown by git worktree list is not used as source authority; the locked remote Taxi commit SHA remains aa0d4794fa3af8458c906db1614fd418893e4bd4."
blockers:
  - "Independent Reviewer and Supervisor decisions require the exact pushed initialization commit SHA."
handoff_to: "INT-SUPERVISOR and INT-REVIEWER"
next_allowed_action: "Commit and push only the verified Stage 0 initialization, report the exact pushed SHA, then wait for independent review and a formal Supervisor Stage 1 brief."
```

## Entry 2 — Stage 1 explicit Taxi merge and runtime preservation

```yaml
timestamp: "2026-07-30T23:32:12+08:00"
session_id: "019fb38f-c992-74f1-9894-c6009784a697"
stage_id: "Stage 1"
input_commit_sha: "476f25254a99e4b9c47d5b439a6e7b658a412f80"
source_branch_shas:
  taxi: "aa0d4794fa3af8458c906db1614fd418893e4bd4"
  pt: "0b0ce90375b9e3d0c055fa46c5a3b96bfc3a5103"
  car: "fc906efd3afb98e027cc6cca44060dec9e32aa46"
actions_or_observations:
  - "Verified the canonical input, clean integration worktree, branch, tracking ref, and all locked remote refs."
  - "Executed an explicit git merge --no-ff --no-commit of the locked Taxi SHA."
  - "The automatic merge completed with zero conflicts; no manual source conflict resolution was required."
  - "Verified the merged Taxi code, tests, data, scripts, and Taxi topic documentation exactly match the locked Taxi source."
  - "Preserved all Stage 0 control-plane files and append-only history."
  - "Faithfully appended the Reviewer Stage 0 PASS and Supervisor Stage 0 closure / Stage 1 authorization handoffs."
  - "Added the Stage 1 integration contract and compact validation record."
  - "Ran the explicit Maven compile successfully."
  - "Ran the complete Maven suite: 61 tests, including 60 Taxi tests, with zero failures, errors, or skips."
  - "Ran two Python native-routing tests successfully and checked four Python command interfaces with --help."
  - "Parsed all nine imported JSON validation files successfully."
  - "Did not merge PT or Car, change model or fare policy, calibrate ASC, add a Taxi fleet, run a Hong Kong scenario, rerun the standalone Taxi smoke, or authorize Runner."
evidence_paths:
  - "docs/HONG_KONG_MULTIMODAL_COST_INTEGRATION.md"
  - "data/taxi/hongkong/processed/taxi_integration_stage1_validation_v1/stage1_taxi_merge_validation.json"
  - "target/surefire-reports/"
  - "data/taxi/hongkong/processed/taxi_native_routing_v1/taxi_native_routing_validation.json"
  - "data/taxi/hongkong/processed/taxi_prepare_for_sim_validation_v1/taxi_prepare_for_sim_validation.json"
  - "data/taxi/hongkong/processed/taxi_route_fare_scoring_v1/taxi_route_fare_parity_validation.json"
  - "data/taxi/hongkong/processed/taxi_two_iteration_smoke_validation_v1/taxi_two_iteration_smoke_conditional_validation.json"
  - "docs/agent-worklogs/integration-supervisor.md"
  - "docs/agent-worklogs/integration-executor.md"
  - "docs/agent-worklogs/integration-reviewer.md"
decisions:
  - "The locked Taxi feature is integrated without altering its canonical runtime implementation."
  - "Standard PrepareForSimImpl, native Taxi mode/routingMode, Guice modules, and the single route-fare path remain the Stage 1 contract."
  - "The historical incomplete two-iteration result and ASC=-9 placeholder status remain explicit."
  - "cities/hongkong/city.yaml and runs/hongkong/run_manifest.json remain unchanged because no production input, config, output, or final run changed."
hard_gate_status: "PENDING_INDEPENDENT_REVIEW_AND_SUPERVISOR_STAGE_1_GATE"
diagnostic_findings:
  - "Maven reports a deprecated ${parent.version} expression."
  - "MATSim scoring APIs and several Java dependencies emit deprecation/native-access warnings."
  - "Guice line-number inspection reports unsupported class-file major version 69, but injection and all tests pass."
  - "Synthetic test fixtures emit non-fatal configuration, routing-randomness, storage-capacity, and attribute-converter warnings."
blockers:
  - "The exact merge commit must be created, pushed, and independently reviewed before Stage 1 can pass."
handoff_to: "INT-SUPERVISOR and INT-REVIEWER after the exact Stage 1 merge commit is pushed"
next_allowed_action: "Complete final scope, structure, diff, and merge-topology checks; create and push the Stage 1 merge commit; then wait for independent review. No Runner action."
```

## Entry 3 — Stage 2 canonical offline PT fare layer

```yaml
timestamp: "2026-07-31T00:15:58+08:00"
session_id: "019fb38f-c992-74f1-9894-c6009784a697"
stage_id: "Stage 2"
input_commit_sha: "d54fdd775064ace1c9f2aa2b6cb96db0e9474975"
source_branch_shas:
  taxi: "aa0d4794fa3af8458c906db1614fd418893e4bd4"
  pt: "0b0ce90375b9e3d0c055fa46c5a3b96bfc3a5103"
  car: "fc906efd3afb98e027cc6cca44060dec9e32aa46"
actions_or_observations:
  - "Verified the canonical Stage 2 input, clean integration worktree, branch, tracking ref, and all locked remote refs."
  - "Executed an explicit git merge --no-ff --no-commit of the locked PT SHA."
  - "Resolved one ordinary docs/PROJECT_ONBOARDING.md conflict by preserving the Stage 0/1 integration and Taxi entries and adding the PT fare-model entry."
  - "Preserved the Stage 1 Taxi implementation, tests, data, runtime contract, and historical evidence without modification."
  - "Faithfully appended the Reviewer Stage 1 PASS and Supervisor Stage 1 closure / Stage 2 authorization handoffs."
  - "Imported the five distinct offline PT fare interfaces without adding PT scoring, money events, plan mutation, supply mutation, calibration, or transfer concessions."
  - "Found that five locked-source registry JSON hashes used pre-commit Windows CRLF bytes and could not match canonical Git bytes in a fresh checkout."
  - "Corrected only those five release-metadata hashes to the exact locked-source Git bytes and synchronized the release record and top-level checksums; no fare artifact content or semantic value changed."
  - "Added a read-only cross-platform canonical release validator that requires clean registered paths and validates canonical Git bytes."
  - "The canonical validator passed all 20 release checks, five registry rows, 16 registered hashes, eight protected inputs, 23 locked PT scripts, and the 557104/0/557104 production boundary."
  - "Recomputed six mode-specific query fixtures; all normalized contents matched the locked fixture outputs."
  - "Parsed 25 JSON files, read 78 CSV headers, and opened all 16 Parquet files with zero failures."
  - "Ran Maven compile successfully and the complete Maven suite: 61 tests with zero failures, errors, or skips."
  - "Did not merge Car, run a Hong Kong MATSim scenario, start a server task, or authorize Runner."
evidence_paths:
  - "docs/HONG_KONG_MULTIMODAL_COST_INTEGRATION.md"
  - "docs/HONG_KONG_PT_FARE_MODEL.md"
  - "data/transport_costs/hongkong/pt_fare_v1/canonical_pt_fare_interface_manifest.json"
  - "data/transport_costs/hongkong/pt_fare_v1/pt_fare_layer_registry.csv"
  - "data/transport_costs/hongkong/pt_fare_v1/pt_fare_release_validation.json"
  - "data/transport_costs/hongkong/integration_stage2_validation_v1/stage2_pt_merge_validation.json"
  - "scripts/hong_kong_single_city/costs/validate_hong_kong_pt_fare_release_v1.py"
  - "target/surefire-reports/"
  - "docs/agent-worklogs/integration-supervisor.md"
  - "docs/agent-worklogs/integration-executor.md"
  - "docs/agent-worklogs/integration-reviewer.md"
decisions:
  - "The canonical PT layer remains offline_interfaces_validated_not_integrated_with_scoring."
  - "Generic production PT remains entirely unresolved/null; unresolved values are not zero or silently selected candidates."
  - "MTR, Light Rail, GMB, Ferry, Bus Core, and Bus simulation semantics and provenance boundaries remain distinct."
  - "The cross-platform release-hash correction is a non-model metadata repair and does not change a fare, fare policy, passenger/payment assumption, or runtime behavior."
  - "Historical raw-byte validators remain evidence but do not override the new canonical release contract when their Windows line-ending guards give a reproducible false positive."
  - "cities/hongkong/city.yaml and runs/hongkong/run_manifest.json remain unchanged because Stage 2 adopts no runtime input, configuration, output, or run."
hard_gate_status: "PENDING_INDEPENDENT_REVIEW_AND_SUPERVISOR_STAGE_2_GATE"
diagnostic_findings:
  - "The historical GMB validator passed 21/23 checks but its prior-directory and byte-identical rebuild guards failed because raw checkout bytes changed with CRLF conversion and earlier validator-generated text rewrites; none of its failed-attempt output is retained."
  - "Maven reports the previously disclosed parent.version, Java 25 native-access/Unsafe, Guice ASM, MATSim, and synthetic-fixture warnings; compile and all tests pass."
  - "MTR and Light Rail historical validators passed before the cross-validator Windows line-ending issue was isolated."
  - "No MATSim behavioral trend is produced or authorized in Stage 2."
blockers:
  - "The exact Stage 2 merge commit must be created, pushed, and independently reviewed before Stage 2 can pass."
handoff_to: "INT-SUPERVISOR and INT-REVIEWER after the exact Stage 2 merge commit is pushed"
next_allowed_action: "Complete final release, source-parity, topology, diff, ref, and cleanliness checks; create and push the Stage 2 merge commit; then wait for independent review. No Runner or Stage 3 action."
```

## Entry 4 — Stage 3 canonical offline Car marginal-cost interface

```yaml
timestamp: "2026-07-31T00:56:46+08:00"
session_id: "019fb38f-c992-74f1-9894-c6009784a697"
stage_id: "Stage 3"
input_commit_sha: "6902501e956bc9bede52de26e1e8ad9bf2b457d6"
source_branch_shas:
  taxi: "aa0d4794fa3af8458c906db1614fd418893e4bd4"
  pt: "0b0ce90375b9e3d0c055fa46c5a3b96bfc3a5103"
  car: "fc906efd3afb98e027cc6cca44060dec9e32aa46"
actions_or_observations:
  - "Verified the canonical Stage 3 input, clean integration worktree, branch, tracking ref, and all locked remote refs."
  - "Executed an explicit git merge --no-ff --no-commit of the locked Car SHA."
  - "Resolved one ordinary docs/PROJECT_ONBOARDING.md conflict by preserving all Stage 0-2, Taxi and PT entries and adding every locked Car topic-document entry."
  - "Retained all 118 locked Car source paths; 117 index blobs exactly match the locked source and the onboarding combined-resolution blob is the sole documented difference."
  - "Faithfully appended the Reviewer Stage 2 PASS and Supervisor Stage 2 closure / Stage 3 authorization handoffs."
  - "Preserved the complete Car source/audit/provenance bundle while adopting only unified_marginal_cost_interface_v1 as the canonical current offline behavioral-cost interface."
  - "Added a read-only integrated Car release validator; it matched 12 canonical file hashes, the canonical bundle, five candidate bundles, all superseded hashes, and nine protected MATSim input hashes."
  - "Independently audited all low/base/high component and summary Parquet tables: exact keys/counts/formulas, 835 unresolved parking legs, 2929 motorcycle legs, legal zeros, fixed-cost exclusion, finite values, and null preservation all passed."
  - "Parsed 22 Car JSON files, read 33 CSV headers, opened 26 Car Parquet files, and compiled all 12 Car scripts without failure."
  - "Reran the canonical PT release validator: all 20 checks and 16 registered hashes passed."
  - "Ran Maven compile successfully and the complete Maven suite: 61 tests with zero failures, errors, or skips."
  - "Did not add Car scoring, money events, static lookup, Java runtime modules, parking imputation, motorcycle-as-car treatment, fixed ownership behavioral inclusion, calibration, or monetary-rate/utility interpretation."
  - "Did not run a Hong Kong MATSim scenario, start a server task, authorize Runner, or begin Stage 4."
evidence_paths:
  - "docs/HONG_KONG_MULTIMODAL_COST_INTEGRATION.md"
  - "docs/HONG_KONG_CAR_COST_MODEL.md"
  - "docs/HONG_KONG_PRIVATE_CAR_UNIFIED_MARGINAL_COST_INTERFACE.md"
  - "data/transport_costs/hongkong/car_cost_v1/canonical_car_cost_interface_manifest.json"
  - "data/transport_costs/hongkong/car_cost_v1/car_cost_release_validation.json"
  - "data/transport_costs/hongkong/car_cost_v1/unified_marginal_cost_interface_v1/unified_marginal_cost_validation.json"
  - "data/transport_costs/hongkong/car_cost_v1/unified_marginal_cost_interface_v1/marginal_cost_component_registry.csv"
  - "data/transport_costs/hongkong/integration_stage3_validation_v1/stage3_car_merge_validation.json"
  - "scripts/hong_kong_single_city/costs/car/validate_hong_kong_car_cost_release_v1.py"
  - "target/surefire-reports/"
  - "docs/agent-worklogs/integration-supervisor.md"
  - "docs/agent-worklogs/integration-executor.md"
  - "docs/agent-worklogs/integration-reviewer.md"
decisions:
  - "Only unified_marginal_cost_interface_v1 is the canonical current Car behavioral-cost interface, and it remains offline/not scoring-approved."
  - "Fuel/electricity, confirmed toll, and resolved destination parking are the only leg-level marginal components."
  - "Fixed ownership remains a vehicle-day accounting sidecar and is excluded from every leg component and behavioral total."
  - "All 835 unresolved parking legs and all 2929 motorcycle legs remain null/out-of-scope; unresolved is never zero."
  - "Legacy top-level results remain preserved, superseded, and forbidden as behavioral scoring inputs; supporting and design artifacts are not parallel canonical interfaces."
  - "cities/hongkong/city.yaml adopts only the locked Car documentation/read-only offline-audit metadata; runs/hongkong/run_manifest.json remains unchanged."
hard_gate_status: "PENDING_INDEPENDENT_REVIEW_AND_SUPERVISOR_STAGE_3_GATE"
diagnostic_findings:
  - "Maven reports the previously disclosed parent.version, Java 25 native-access/Unsafe, Guice ASM, MATSim, and synthetic-fixture warnings; compile and all tests pass."
  - "Representative-fleet energy, parking proxy, source effective-date, and four non-blocking required-repair limitations remain documented offline diagnostics."
  - "The historical/design-only scoring-adoption risk records remain blocked and do not activate scoring."
  - "No MATSim or behavioral trend is produced or authorized in Stage 3."
blockers:
  - "The exact Stage 3 merge commit must be created, pushed, and independently reviewed before Stage 3 can pass."
handoff_to: "INT-SUPERVISOR and INT-REVIEWER after the exact Stage 3 merge commit is pushed"
next_allowed_action: "Complete final source-parity, topology, diff, ref, structured-file and cleanliness checks; create and push the Stage 3 merge commit; then wait for independent review. No Runner or Stage 4 action."
```

## Entry 5 — Stage 4A lean protocol migration

```yaml
timestamp: "2026-07-31T12:33:44+08:00"
session_id: "019fb38f-c992-74f1-9894-c6009784a697"
stage_id: "Stage 4A"
input_sha: "75988d2645f55a36fb6271ff49d887c1b5143c1b"
output_sha_or_status: "exact pushed SHA recorded in the cross-session handoff"
decision: "Adopt the repository policy/current-stage/brief files as the canonical lean control plane without changing lane or model authority."
findings:
  - "Created the stable policy, compact active-stage record, Stage 4A brief, and brief index."
  - "Linked every new path from agent-lanes.md without changing lane IDs or write scopes."
  - "Defined compact commands/worklogs, evidence-by-reference rules, structural caps, and lane token budgets."
  - "Corrected only the stale Stage 2/Car status paragraph in the integration document."
  - "Historical worklog prefixes are verified byte-identical; all changes are append-only."
diagnostics:
  - "Prior prompts and historical worklogs remain verbose evidence; the lean limits apply prospectively."
evidence_refs:
  - "docs/integration/INTEGRATION_POLICY.md#lean-cross-session-protocol"
  - "docs/integration/INTEGRATION_POLICY.md#compact-future-worklog-schema"
  - "docs/integration/INTEGRATION_POLICY.md#lane-specific-routine-output-budgets"
  - "docs/integration/CURRENT_STAGE.md#authorized-delta"
  - "agent-lanes.md#canonical-control-plane-sources"
blockers: []
hard_gate_status: "PENDING_INDEPENDENT_REVIEW_AND_SUPERVISOR_STAGE_4A_GATE"
handoff_to: "INT-REVIEWER and INT-SUPERVISOR"
next_action: "Review the exact pushed Stage 4A SHA; do not begin substantive Stage 4 or authorize Runner."
```

## Entry 6 — Stage 4A continuation after HOLD

```yaml
timestamp: "2026-07-31T13:02:13+08:00"
session_id: "019fb38f-c992-74f1-9894-c6009784a697"
stage_id: "Stage 4A continuation"
input_sha: "75988d2645f55a36fb6271ff49d887c1b5143c1b"
output_sha_or_status: "exact pushed SHA recorded in the cross-session handoff"
decision: "Continue the existing uncommitted governance work without discarding or recreating it, then stop after the Stage 4A push."
findings:
  - "The HOLD arrived after edits but before staging, commit, or push."
  - "Local and remote integration refs remained at the exact Stage 3 input throughout the HOLD."
  - "Existing useful edits were inspected and preserved in place."
  - "Historical worklog prefixes remain byte-identical to the Stage 3 input."
diagnostics: []
evidence_refs:
  - "docs/integration/INTEGRATION_POLICY.md#lean-cross-session-protocol"
  - "agent-lanes.md#canonical-control-plane-sources"
blockers: []
hard_gate_status: "PENDING_INDEPENDENT_REVIEW_AND_SUPERVISOR_STAGE_4A_GATE"
handoff_to: "INT-REVIEWER and INT-SUPERVISOR"
next_action: "Review the exact pushed Stage 4A SHA; do not begin another stage."
```
