# Hong Kong multimodal-cost integration policy

## Canonical prospective authority

This policy and [Protocol 09](stage-briefs/CONTROL_PROTOCOL_09_LEAN_STAGE_END_REVIEW.md)
are the self-contained prospective governance contract for the persistent Hong
Kong multimodal-cost integration. Lane identities and write scopes are in
[`agent-lanes.md`](../../agent-lanes.md), compact current facts are in
[`CURRENT_STAGE.md`](CURRENT_STAGE.md), and a current-stage Supervisor exact
execution contract supplies the authorized delta. These are the only
prospective control-plane sources.

Protocols 05–08 and earlier briefs remain historical audit and rationale only.
They have no prospective authority for dispatch, state, review cadence,
diagnosis ownership, execution, or authorization. All still-valid safeguards
from those documents are normalized directly below; no lane needs to consult
an old protocol to act prospectively.

## Lean evidence and reporting

- Stable rules are read from the canonical repository files, not repeated in
  each message. A stage dispatch contains stage/task ID, exact input SHA,
  objective, allowlist, Hard Gates, evidence, stop conditions, handoff target,
  and any exact execution contract.
- Evidence is cited as `path#field` or `path#section`. Machine results live in
  committed JSON/CSV or durable server evidence; long logs, manifests, binary
  inventories, and historical handoffs are not copied into prompts/worklogs.
- Routine output has one decision, at most five findings, at most five
  diagnostics, one next action, and one compact handoff. Diagnostics and
  Trends do not fail a stage unless evidence ties them to a named Hard Gate.
- Historical evidence and guards remain preserved. A superseded guard cannot
  control the current architecture; its replacement and equivalent protection
  are cited by path.
- A validator PASS is not a Stage PASS. Executor and Runner self-checks do not
  replace independent Reviewer review.

## Lane authority

| Lane | Prospective authority and boundary |
|---|---|
| `INT-SUPERVISOR` | Sole owner of objectives, Hard Gates, formal dispatch, diagnosis-owner selection, Runner authorization, Reviewer dispatch, gate decisions, escalation, and stage progression. Aggregates all lane handoffs. |
| `INT-EXECUTOR` | Sole integration Git writer, limited to `F:/Matsim/worktrees/hk-cost-integration` and `integration/hk-multimodal-cost-v1`; implements repository changes, validates locally, performs bounded local diagnosis, commits and pushes, then reports only to Supervisor. |
| `INT-RUNNER` | On an exact Supervisor authorization only, builds, bundles, releases, runs, and performs bounded read-only server diagnosis under `/mnt/DiskM/by`; writes no Git state and never repairs, self-reruns, dispatches, or authorizes. |
| `INT-REVIEWER` | Read-only independent stage-end Reviewer or explicitly dispatched targeted Reviewer; reports findings only to Supervisor and never writes, dispatches, gates, repairs, or authorizes. |
| User | Decides research, economic, behavioral, cost-policy, missing-data, demand/capacity, calibration, and other material semantic choices. |

Hub-and-spoke messaging is mandatory. Executor, Runner, and Reviewer report
only to Supervisor and do not direct one another. A non-Supervisor message is
evidence, not authorization. Git worklogs are append-only audit, not a dispatch
or notification mechanism. `BLOCKED`, Reviewer `PASS`, and stage closure never
authorize repair, rerun, Runner, a next stage, or a protected-branch action.

## Default stage flow and formal states

```text
Supervisor objective + Hard Gates + activation review_base_sha
  -> Executor implementation, internal correction, executor_self_check, push
  -> Supervisor pre-run gate
  -> exact Runner authorization and execution evidence, when required
  -> one final candidate
  -> one independent stage-end Reviewer review
  -> Supervisor PASS_CLOSED or BLOCKED
```

There is no repair-by-repair, evidence-binding, closure, or intermediate review
by default. The only formal Stage states are `READY`, `RUNNING`, `BLOCKED`, and
`PASS_CLOSED`. Diagnosis, repair, dispatch, handoff, and review labels are
append-only worklog events, not canonical long-lived Stage states.

## Exact identity, immutability, and nonrecursive closure

- Every task starts from an exact pushed input SHA. Runner may execute only the
  exact Supervisor-authorized pushed SHA.
- Source, artifact, bundle, release, and run identities and SHA continuity are
  recorded end to end. Failed staging/release/run directories remain immutable
  and are never overwritten, cleaned, or reused.
- An identical failed commit/bundle/config/input/command/runtime identity is
  never rerun unchanged. A new run requires a relevant changed hypothesis and
  new staging, release, and run identities; a new directory alone is not a
  changed hypothesis.
- Reviewer PASS is consumed in real time by Supervisor. No commit may exist
  solely or primarily to record a verdict, closure, prior closure, or final
  review result. A protocol is never created solely to close another protocol.
- A substantive transition may update canonical state and audit together, but
  PASS produces no verdict-only or closure-only follow-up commit.

## Executor internal correction and self-check

Executor may correct an ordinary local technical defect before its single
candidate push only when it stays within the original objective and allowlist,
weakens/deletes/relaxes no Hard Gate/test/validator, changes no model/cost/
economic/behavioral/missing-data semantic, expands no scope, performs no server
run, touches no protected ref, and leaves no unresolved ambiguity. Otherwise
Executor stops and reports to Supervisor.

```yaml
executor_self_check:
  stage_id: string
  exact_input_sha: full_sha
  branch: integration/hk-multimodal-cost-v1
  worktree: F:/Matsim/worktrees/hk-cost-integration
  changed_paths: []
  compile: {required: boolean, command: string_or_null, result: string}
  tests: {required: boolean, commands: [], result: string}
  negative_tests: {required: boolean, commands: [], result: string}
  validators: {commands: [], result: string}
  diff_check: PASS_or_FAIL
  conflict_check: PASS_or_FAIL
  protected_refs: PASS_or_FAIL
  semantic_contract: UNCHANGED_or_explained
  unresolved_items: []
executor_post_push:
  output_sha: full_sha
  parent_sha: full_sha
  local_tracking_remote_equal: boolean
  ahead: 0
  behind: 0
  worktree_clean: boolean
```

Repository/local implementation, test, packaging-contract, or evidence-
generator defects belong to Executor unless Supervisor selects another owner
for a cross-boundary diagnosis. Executor never diagnoses the same failure in
parallel with Runner.

## Supervisor pre-run gate

Before any Runner authorization, Supervisor records:

```yaml
supervisor_pre_run_gate:
  candidate_sha_verified: true_or_false
  executor_self_check_received: true_or_false
  required_checks_passed: true_or_false
  unresolved_items_empty: true_or_false
  semantic_issue_present: true_or_false
  execution_contract_complete: true_or_false
  new_run_identity_reserved: true_or_false
  decision: AUTHORIZE_RUN | BLOCK
```

Only `AUTHORIZE_RUN` with all required positive fields true and
`semantic_issue_present=false` permits the exact separately named Runner task.

## Runner execution contract

Every Runner authorization instantiates all fields:

```yaml
execution_contract:
  source_sha: full_sha
  working_directory: absolute_path
  java_command: absolute_or_canonical_command
  tool_version_commands: []
  build_command: command
  artifact_resolver: deterministic_rule
  bundle_command: command
  release_root: new_absolute_path
  run_command: command
  required_preconditions: []
  hard_gates: []
  diagnostics_only: []
  forbidden_fallbacks: []
```

Priority is Supervisor exact contract, then current stage brief, then this
Protocol 09 policy, then lane experience. Explicit inconsistency is
`CONTRACT_CONFLICT`: stop and report to Supervisor. A Supervisor omission with
one unambiguous Protocol 09 rule uses that canonical rule.

The Hong Kong Maven commands are exactly `./mvnw --version` and
`./mvnw -DskipTests package`, executed from the verified snapshot build root.
The deployment artifact is the canonical root Shade JAR
`<build_root>/matsim-example-project-0.0.1-SNAPSHOT.jar`. The `target/` thin
JAR, glob/first-match selection, and size guessing are forbidden. Required
project, MATSim, Guice, Raptor, and DuckDB classes and SHA continuity through
bundle/release are fail-closed preconditions.

Runner sequence is preflight, build, artifact validation, bundle, release,
runtime preflight, run, and final structured evidence. Runner self-checks
source/inputs/toolchain, root Shade JAR, bundle/release/run identities, hashes,
class loading, iterations, outputs, finite values, diagnostics, and coverage.

## Contract-preserving preflight correction

`CONTRACT_PRESERVING_PREFLIGHT_CORRECTION` is allowed only when all seven gates
are true:

1. `build_started=false`;
2. `bundle_created=false`;
3. `release_created=false`;
4. `smoke_started=false`;
5. `existing_state_modified=false`;
6. `canonical_replacement_command_exists=true`;
7. `task_semantics_changed=false`.

It may correct only the wrapper command, approved Java absolute path, required
working directory, or canonical artifact resolver. It cannot change identity,
install tools, alter `PATH`, substitute JDK/tool versions, change config/input/
build parameters, mutate state, or occur after build/bundle/release/run begins.
It records original and replacement commands, canonical basis, and zero-
mutation proof. It is not a formal retry and creates no new identity.

## Failure classification and diagnosis ownership

| Failure class/boundary | Required route and owner |
|---|---|
| `INFORMATIONAL` | Correct or record safely within existing scope; it is not automatically a Stage blocker. |
| `TECHNICAL` repository/local | Executor bounded local diagnosis/repair after Supervisor dispatch. |
| `TECHNICAL` server precondition/build/bundle/deployment/runtime | Runner stops and performs bounded read-only diagnosis; Runner never repairs or reruns. |
| Cross-boundary, ambiguous identity/evidence/access, or `CONTRACT_CONFLICT` | Supervisor selects exactly one diagnosis owner and prevents duplicate Executor+Runner diagnosis. |
| `SEMANTIC` research/economic/behavioral/cost/missing-data/demand/capacity | Stop and escalate to User. |

Reviewer may identify missing evidence but never generates or repairs it.
After execution begins, any nonzero exit or Hard Gate failure stops mutation and
retry and enters `POST_FAILURE_READ_ONLY_DIAGNOSIS`.

```yaml
runner_technical_diagnosis:
  task_id: string
  stage_id: string
  source_sha: full_sha
  run_identity: string
  boundary: PRECONDITION | BUILD | BUNDLE | DEPLOYMENT | RUNTIME
  root_cause_status: KNOWN | PARTIAL | UNKNOWN
  root_cause: concise_statement_or_null
  observations: []
  causal_chain: []
  material_alternatives_checked: []
  missing_evidence: []
  repair_hypothesis: bounded_testable_change_or_null
  evidence_refs: []
  state_modified: false
  rerun_performed: false
  recommended_action: CREATE_REPAIR | CREATE_DIAGNOSIS | ESCALATE_TO_USER
  handoff_to: INT-SUPERVISOR
```

`KNOWN` is valid only when all five booleans are true:

```yaml
diagnosis_confidence:
  exact_failure_identity_matched: true
  direct_failure_condition_observed: true
  causal_chain_demonstrated: true
  material_alternatives_checked: true
  repair_hypothesis_testable: true
  root_cause_status: KNOWN
```

A first exception, stack trace, or correlation alone never proves `KNOWN`.
Missing causal proof, alternatives, or a measurable repair yields `PARTIAL`;
symptoms without a verifiable direct cause or equally plausible alternatives
yield `UNKNOWN`. Supervisor cannot upgrade `PARTIAL/UNKNOWN` without new
evidence. `KNOWN` ordinary technical defects lead to a bounded Executor repair;
`PARTIAL/UNKNOWN` lead to a new bounded diagnosis with a new task ID, missing
evidence, changed scope/budget, and why that evidence may change the conclusion.
The same commands and scope are not repeated unchanged.

## Read-only diagnosis budgets

Runner post-failure diagnosis defaults to:

```yaml
diagnosis_budget:
  wall_clock_minutes_max: 30
  shell_commands_max: 30
  filesystem_roots_max: 6
  evidence_output_mb_max: 30
  full_server_recursive_scan_allowed: false
  existing_state_mutation_allowed: false
```

Scope is restricted to the failed release/run roots, directly referenced
staging/build roots, manifest-linked paths, and command/classpath/config/input
paths. It may read bounded metadata, hashes, permissions, concise logs, member
inventories, and structured files. It cannot scan all `/mnt/DiskM/by`, copy
large logs/binaries, install tools, change environment/Git/commands, mutate or
clean state, or rerun. Budget exhaustion requires
`STOP_AND_REPORT_MISSING_EVIDENCE` with elapsed minutes, commands, roots,
evidence bytes, `budget_exhausted=true`, and missing evidence.

Supervisor server-read verification is an evidence check, not repository-
granted SSH/platform permission. It is limited to exact `/mnt/DiskM/by` roots
named by Runner/canonical state or manifest, 15 minutes, 20 commands, four
roots, and 10 MB returned text. Bounded `ls/stat/find`, concise text reads,
SHA256, and JAR/TAR/ZIP inventories are allowed; full-root recursion, mutation,
execution, installation, process control, cleanup, path escape, and any lane or
stage authorization are forbidden. Exhaustion stops and reports missing
evidence; expansion needs a new bounded diagnosis task.

## Reviewer stage-end policy

Default is `STAGE_END_ONLY`. At activation, Supervisor locks
`review_base_sha`; the final pushed candidate is `review_head_sha`.

```yaml
stage_end_review:
  reviewed_stage: string
  review_base_sha: full_sha
  review_head_sha: full_sha
  run_source_sha: full_sha_or_null
  reviewed_range: review_base_sha..review_head_sha
  reviewed_run_identity: string_or_null
  decision: PASS | BLOCKED
  findings: []
  coverage_limitations: []
  blockers: []
  evidence_refs: []
  handoff_to: INT-SUPERVISOR
```

The review covers the full substantive delta, Executor/Runner self-checks,
final evidence, stage Hard Gates, diagnostics, evidence-generator
trustworthiness, coverage debt, and model/cost semantic invariants. Reviewer
does not dispatch, write, gate, close, authorize, or replace missing evidence.

Default targeted policy is `NO_INTERMEDIATE_REVIEW`. Supervisor may dispatch
at most one targeted review per stage, answering one narrow question, only for
a model/cost/economic/behavioral semantic change; weakened/removed Hard Gate;
validator/evidence-generator change; destructive/protected-ref operation;
unresolved architecture; Supervisor scope uncertainty; or high-cost formal run
with an unreviewed high-risk change. It neither authorizes progress nor replaces
stage-end review. A second high-risk issue requires stage split or user/Supervisor
escalation; it is never silently skipped.

## Model-policy and protected boundaries

User direction is mandatory before changing monetary utility, ASC range or
target, fare/parking/car-rate economic meaning, transfer policy, non-random
missing-data treatment or imputation, mode definitions, demand/capacity/supply,
calibration objectives, destructive Git, master merge, or choosing between
materially different research interpretations. Master and feature branches
remain protected. No historical evidence is deleted or rewritten.

## Append-only audit schema and output budgets

```yaml
timestamp: ISO-8601
session_id: actual_session_id
stage_id: string
input_sha: full_sha
output_sha_or_status: full_sha_or_pending
decision: one_or_null
findings: []
diagnostics: []
evidence_refs: []
blockers: []
hard_gate_status: string
handoff_to: lane_id
next_action_summary: one_action
```

Corrections append a new entry; historical text is never edited. Routine
cross-session budgets are Supervisor 700 tokens, Executor 800, Runner 600, and
Reviewer 600. Safety stops may exceed them only for new facts needed to explain
the stop.

## Historical noncanonical appendix

The following remain immutable audit/rationale with status
`DEPRECATED_NON_CANONICAL`, prospective authority `NONE`, and canonical
replacement Protocol 09:

- [Protocol 05](stage-briefs/CONTROL_PROTOCOL_05_ATOMIC_GATE_TRANSITION.md)
- [Protocol 06](stage-briefs/CONTROL_PROTOCOL_06_POST_FAILURE_DIAGNOSIS_AUTO_DISPATCH.md)
- [Protocol 07](stage-briefs/CONTROL_PROTOCOL_07_DIAGNOSIS_CONFIDENCE_AND_BUDGET.md)
- [Protocol 08](stage-briefs/CONTROL_PROTOCOL_08_EXECUTION_CONTRACT_AND_SUPERVISOR_SERVER_READ.md)

Do not use those files for prospective dispatch, state, review cadence,
diagnosis ownership, execution, or authorization.
