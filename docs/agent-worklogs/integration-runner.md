# INT-RUNNER append-only worklog

This file is an append-only audit record. Never edit or delete an earlier
entry. Corrections, session replacements, and superseding decisions must be
appended as new entries.

## Session history

- Current session: `019fb38e-919f-7d92-a376-af88b49d5900`

## Entry 1 — Stage 0 registration

```yaml
timestamp: "2026-07-30 Asia/Shanghai"
session_id: "019fb38e-919f-7d92-a376-af88b49d5900"
stage_id: "Stage 0 registration"
input_commit_sha: "a3d6445cfd79a74b6fd6bd01e547d7df8055a64d"
source_branch_shas:
  taxi: "aa0d4794fa3af8458c906db1614fd418893e4bd4"
  pt: "0b0ce90375b9e3d0c055fa46c5a3b96bfc3a5103"
  car: "fc906efd3afb98e027cc6cca44060dec9e32aa46"
actions_or_observations:
  - "Registered the persistent INT-RUNNER lane with no Git write authority."
evidence_paths:
  - "agent-lanes.md"
decisions:
  - "Runs require a Supervisor-authorized exact pushed SHA and an explicit run specification."
hard_gate_status: "NOT_EVALUATED"
diagnostic_findings: []
blockers:
  - "No Stage 0 run is authorized."
handoff_to: "INT-EXECUTOR"
next_allowed_action: "Wait for a later explicit Supervisor run authorization."
```

## Entry 2 — Stage 0 WORKLOG HANDOFF

Faithfully transcribed from the actual INT-RUNNER handoff:

```yaml
timestamp: "2026-07-30 Asia/Shanghai"
session_id: "019fb38e-919f-7d92-a376-af88b49d5900"
source_thread_id: "019fb38c-07b4-7242-b7a8-aa00594636fe"
lane_id: "INT-RUNNER"
stage_id: 0
registry:
  INT-SUPERVISOR: "019fb38e-0963-7f01-9461-ba84c9aa6378"
  INT-EXECUTOR: "019fb38f-c992-74f1-9894-c6009784a697"
  INT-RUNNER: "019fb38e-919f-7d92-a376-af88b49d5900"
  INT-REVIEWER: "019fb38f-1c8c-7d62-9dc4-7ea5d0b5192e"
project:
  repository: "Tensort-s/matsim-example-project"
  integration_worktree: "F:\\Matsim\\worktrees\\hk-cost-integration"
  integration_branch: "integration/hk-multimodal-cost-v1"
  server_root: "by@100.103.8.34:/mnt/DiskM/by"
input_commit_sha: "a3d6445cfd79a74b6fd6bd01e547d7df8055a64d"
source_branch_shas:
  taxi: "aa0d4794fa3af8458c906db1614fd418893e4bd4"
  pt: "0b0ce90375b9e3d0c055fa46c5a3b96bfc3a5103"
  car: "fc906efd3afb98e027cc6cca44060dec9e32aa46"
merge_order: "Taxi -> PT -> Car"
write_scope: "No Git writes; append-only run and evidence directories only."
actions_or_observations:
  - "Accepted and recorded all Bootstrap registry IDs."
  - "Confirmed zero Git writes."
  - "Confirmed only Supervisor-authorized pushed exact SHA may be run."
  - "Confirmed every attempt must use a new, non-overwriting, traceable directory."
  - "Confirmed unchanged reruns are prohibited."
  - "Confirmed Evidence Handoff must be delivered to INT-EXECUTOR."
  - "No Git operation was performed."
  - "No server task was started."
  - "No local or remote evidence directory was created."
  - "No model, configuration, input, or runtime parameter was changed."
evidence_paths: []
decisions:
  - "Stage 0 remains control-plane only."
  - "INT-RUNNER will not independently initiate a run."
  - "INT-RUNNER will not repair model failures or declare a stage passed."
  - "Reviewer findings do not authorize progression without Supervisor direction."
  - "A failed run cannot be repeated unchanged unless a one-time external infrastructure failure is demonstrated."
hard_gate_status: "NOT_EVALUATED — Stage 0 contains no authorized run"
diagnostic_findings: []
trend_findings: []
blockers:
  - "No later-stage run authorization has been issued by INT-SUPERVISOR."
  - "No exact execution specification has been supplied."
handoff_to: "INT-SUPERVISOR"
next_allowed_action: "Wait for INT-SUPERVISOR to authorize an exact pushed commit SHA and explicit run specification; do not run a server task during Stage 0."
```

## Entry 3 — Hub-and-spoke protocol confirmation

Compact archival transfer of the Runner confirmation received by Supervisor:

```yaml
timestamp: "2026-07-31T14:36:00+08:00"
session_id: "019fb38e-919f-7d92-a376-af88b49d5900"
stage_id: "CONTROL-PROTOCOL-01 confirmation"
input_sha: "9235ccb62dbea43a2f321e4fba2aee6e5629bce0"
output_sha_or_status: "NO_RUN__NO_GIT_CHANGE"
decision: "Run only an exact Supervisor-authorized SHA for a genuinely execution-requiring stage and return run identity, evidence and handoff only to Supervisor."
findings:
  - "Runner does not contact or direct Executor or Reviewer."
  - "Runner remains notLoaded/inactive."
  - "No server, MATSim, smoke or calibration run and no Git change occurred."
  - "The entry timestamp is the Supervisor archival-transfer time; the original confirmation timestamp was not supplied."
diagnostics: []
evidence_refs:
  - "docs/integration/INTEGRATION_POLICY.md#hub-and-spoke-lane-messaging-protocol"
blockers: []
hard_gate_status: "NOT_EVALUATED — no run authorized"
handoff_to: "INT-SUPERVISOR"
next_action: "Wait for an exact Supervisor run authorization; CONTROL-PROTOCOL-01 and Stage 6 require no Runner action."
```

## Entry 4 — Stage 8D exact-SHA server bundle PASS

Compact archival transfer of the Runner facts received through Supervisor:

```yaml
timestamp: "2026-08-01T00:34:47+08:00"
session_id: "019fb38e-919f-7d92-a376-af88b49d5900"
stage_id: "Stage 8D exact-SHA server bundle"
input_sha: "674a60258d8433bd04f868a8a447525561bd3907"
output_sha_or_status: "RUNNER_PASS__BUNDLE_UPLOADED__NO_RUN"
decision: "Report PASS for exact-source verification, external input pack, isolated Linux JDK 25 build, bundle preparation, release inventory and upload evidence only."
findings:
  - "SSH to by@100.103.8.34/FUSELAB01 succeeded; the source snapshot and its 7620-entry tree verified."
  - "The external input pack contained exactly seven locked files and all hashes passed."
  - "The isolated Maven build exited 0; the fat JAR contains required Taxi/PT/Car/multimodal classes and the immutable source root stayed unchanged."
  - "The 21-file release passed sha256sum and stale/pre-Ferry scans; bundle, deployment-manifest and upload-evidence hashes are recorded in compact evidence."
  - "No MATSim/QSim/Stage 9 run, iterations, events, costs or scores occurred."
diagnostics:
  - "Build elapsed 1:19.48 with peak RSS 1036196 KB."
  - "Original Runner timestamp and some server artifact paths were not supplied in the transferred facts; they are not inferred."
evidence_refs:
  - "data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_server_bundle_evidence.json#source_snapshot"
  - "data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_server_bundle_evidence.json#external_locked_input_pack"
  - "data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_server_bundle_evidence.json#isolated_build"
  - "/mnt/DiskM/by/hk_stage8d_674a6025_staging_isolated2/bundle_corrected.tar"
  - "/mnt/DiskM/by/hk_multimodal_cost_674a6025_stage8d_build2"
blockers: []
hard_gate_status: "RUNNER_PASS__PENDING_INDEPENDENT_GIT_EVIDENCE_REVIEW"
handoff_to: "INT-SUPERVISOR"
next_action: "Wait; no additional Runner, MATSim, Stage 9 or server action is authorized by this archival entry."
```

## Entry 5 — Stage 8D read-only evidence path discovery

Compact archival transfer of the Runner path facts received through Supervisor:

```yaml
timestamp: "2026-08-01T00:51:53+08:00"
session_id: "019fb38e-919f-7d92-a376-af88b49d5900"
stage_id: "Stage 8D evidence path discovery"
input_sha: "9b1ea88680423694d6f09bccc7473acc1452b373"
output_sha_or_status: "READ_ONLY_PATHS_VERIFIED__NO_RUN"
decision: "Supply exact existing server paths and matching hashes read-only to correct the compact Git evidence."
findings:
  - "Source archive, manifest, extracted root and reviewed preparation-script paths were verified under hk_stage8d_674a6025_staging_isolated2/source."
  - "The exact external locked-input-pack root and manifest paths were verified with the recorded b79f3994… manifest hash."
  - "The isolated build root and fat-JAR path were verified with the recorded b9afb033… JAR hash."
  - "Bundle, corrected deployment manifest, release root and upload-evidence paths were verified with their previously recorded hashes."
  - "Discovery was read-only; no rebuild, upload, MATSim/QSim/Stage 9 run, iteration, event, cost or score occurred."
diagnostics: []
evidence_refs:
  - "data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_server_bundle_evidence.json#source_snapshot"
  - "data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_server_bundle_evidence.json#external_locked_input_pack"
  - "data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_server_bundle_evidence.json#isolated_build"
  - "data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_server_bundle_evidence.json#bundle"
  - "data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_server_bundle_evidence.json#upload"
blockers: []
hard_gate_status: "RUNNER_PATH_DISCOVERY_TRANSFERRED__PENDING_GIT_EVIDENCE_REVIEW"
handoff_to: "INT-SUPERVISOR"
next_action: "Wait; no additional Runner, MATSim, Stage 9 or server action is authorized."
```
