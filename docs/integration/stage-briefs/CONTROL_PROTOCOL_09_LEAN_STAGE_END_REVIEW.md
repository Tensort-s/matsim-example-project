# CONTROL-PROTOCOL-09 — canonical lean stage-end governance

## Consolidation candidate

- Task ID: `CONTROL-PROTOCOL-09-CANONICAL-CONSOLIDATION-AND-FAILURE-OWNERSHIP`
- Exact input/parent SHA: `16398c7883945bc82cdf521b727c6ef502273e79`
- Writer: `INT-EXECUTOR` only
- Gate/dispatch owner: `INT-SUPERVISOR`
- Review: one Supervisor-dispatched stage-end review after exact-SHA verification
- Runner authorized: `false`
- Stage 9 execution authorized: `false`
- Stage 10 or later authorized: `false`

This governance-only candidate makes Protocol 09 self-contained. Prospective
canonical sources are [`agent-lanes.md`](../../../agent-lanes.md),
[`INTEGRATION_POLICY.md`](../INTEGRATION_POLICY.md),
[`CURRENT_STAGE.md`](../CURRENT_STAGE.md), this brief, and the Supervisor exact
execution contract. Protocols 05–08 are historical audit/rationale with
prospective authority `NONE`; no rule below depends on consulting them.

## Lane authority and default stage flow

- `INT-SUPERVISOR` alone defines objectives/Hard Gates, selects diagnosis owner,
  dispatches Executor/Runner/Reviewer, authorizes Runner, decides gates and
  stages, aggregates handoffs, and escalates.
- `INT-EXECUTOR` alone writes the integration worktree/branch, implements repository
  work, validates locally, performs bounded local diagnosis, commits/pushes,
  and reports only to Supervisor.
- `INT-RUNNER` only under exact Supervisor authorization builds, bundles, releases,
  runs, and performs bounded server read diagnosis. Runner writes no Git,
  repairs nothing, and never implicitly reruns or authorizes.
- `INT-REVIEWER` is read-only for one independent stage-end review or one explicitly
  dispatched narrow targeted review; Reviewer never dispatches, gates, repairs,
  closes, writes, or authorizes.
- User decides research, economic, behavioral, cost, missing-data, demand,
  capacity, and other material policy semantics.

```text
Supervisor objective + Hard Gates + review_base_sha
  -> Executor implementation + internal correction + self-check + candidate
  -> Supervisor pre-run gate
  -> explicitly authorized Runner execution contract + final evidence
  -> one final candidate
  -> one independent stage-end review
  -> Supervisor PASS_CLOSED or BLOCKED
```

There is no repair-by-repair or intermediate review by default. Only `READY`,
`RUNNING`, `BLOCKED`, and `PASS_CLOSED` are formal Stage states; diagnosis,
repair, handoff, and review labels are worklog events.

## Identity, non-overwrite, and close behavior

- Every task uses an exact pushed input SHA; Runner uses only the exact
  Supervisor-authorized pushed SHA.
- Source/artifact/bundle/release/run identities and SHA continuity are recorded.
  Failed directories are immutable and never reused, overwritten, or cleaned.
- Identical failed commit/bundle/config/input/command/runtime identity is never
  rerun unchanged. A replacement requires a relevant changed hypothesis plus
  new staging, release, and run identities; a new directory alone is not enough.
- Reviewer PASS and closure never authorize Runner or another stage.
- Reviewer PASS is consumed in real time by Supervisor. Verdict-only and
  closure-only commits are prohibited, as is creating a protocol solely to
  close another protocol.
- Real-time hub-and-spoke messages are the handoff mechanism. Worklogs are
  append-only audit, not execution authority.

## Executor internal repair and self-check

Executor may internally fix ordinary local technical defects before its one
push only inside the original objective/allowlist, with no weakened/deleted/
relaxed gate/test/validator, no semantic or scope change, no protected/destructive
action, no server run, and no unresolved ambiguity. Repository/local defects
belong to Executor unless Supervisor selects a different single owner.

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

## Supervisor pre-run gate

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

Runner is permitted only by a separate exact instruction with
`decision=AUTHORIZE_RUN`, all required positive fields true, and
`semantic_issue_present=false`.

## Exact Runner execution contract

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

Priority is Supervisor exact contract, current stage brief, Protocol 09, then
lane experience. An explicit conflict is `CONTRACT_CONFLICT` and stops for
Supervisor. One unambiguous repository rule fills an omitted detail.

Hong Kong Maven uses `./mvnw --version` and
`./mvnw -DskipTests package` from the verified build root. The only deployment
artifact is `<build_root>/matsim-example-project-0.0.1-SNAPSHOT.jar`, the root
Shade JAR. `target/` thin JAR, glob/first-match selection, and size guessing are
forbidden. Required classes and built/bundle/release SHA continuity fail closed.
Runner proceeds through preflight, build, artifact validation, bundle, release,
runtime preflight, run, and structured evidence, checking identity, inputs,
toolchain, classes, iterations, outputs, finite values, diagnostics, and coverage.

## Contract-preserving preflight correction

This correction exists only when all seven eligibility gates are true:

```yaml
contract_preserving_preflight_correction:
  build_started: false
  bundle_created: false
  release_created: false
  smoke_started: false
  existing_state_modified: false
  canonical_replacement_command_exists: true
  task_semantics_changed: false
```

Only wrapper command, approved Java absolute path, required working directory,
or canonical resolver may be corrected. Identity, tools, `PATH`, JDK, config,
inputs, build parameters, and state cannot change. It occurs before build only,
records original/replacement command, canonical basis, and zero-mutation proof,
creates no new identity, and is not a formal retry.

## Failure routing and unique diagnosis owner

| Classification/boundary | Owner/action |
|---|---|
| `INFORMATIONAL` | Safely correct or record inside current scope; no automatic blocker. |
| `TECHNICAL` repository/local | Supervisor dispatches Executor bounded diagnosis/repair. |
| `TECHNICAL` server `PRECONDITION/BUILD/BUNDLE/DEPLOYMENT/RUNTIME` | Runner stops and performs bounded read-only diagnosis; no repair/rerun. |
| Cross-boundary, ambiguous identity/evidence/access, `CONTRACT_CONFLICT` | Supervisor selects one diagnosis owner. |
| `SEMANTIC` research/economic/behavioral/cost/missing-data/demand/capacity | Escalate to User. |

Reviewer may identify missing evidence but never generates or repairs it. There
is no duplicate Executor+Runner diagnosis. After execution begins, failure
stops immediately and records:

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

## Diagnosis confidence and budgets

`KNOWN` requires all five conditions true:

```yaml
diagnosis_confidence:
  exact_failure_identity_matched: true
  direct_failure_condition_observed: true
  causal_chain_demonstrated: true
  material_alternatives_checked: true
  repair_hypothesis_testable: true
  root_cause_status: KNOWN
```

The first exception, stack trace, or correlation is only partial evidence.
Incomplete causal proof, unchecked alternatives, an unmeasurable repair, or
budget exhaustion is `PARTIAL`; symptom-only or equally plausible causes are
`UNKNOWN`. Supervisor never upgrades without new evidence. `KNOWN` ordinary
technical defects yield a bounded Executor repair. `PARTIAL/UNKNOWN` yield a
new bounded diagnosis task naming missing evidence, new scope/budget, and why
it can change the conclusion; identical scope/commands are not repeated.

```yaml
diagnosis_budget:
  wall_clock_minutes_max: 30
  shell_commands_max: 30
  filesystem_roots_max: 6
  evidence_output_mb_max: 30
  full_server_recursive_scan_allowed: false
  existing_state_mutation_allowed: false
```

Runner reads only failed release/run, directly referenced staging/build,
manifest, and command/classpath/config/input paths. No full `/mnt/DiskM/by`
scan, large evidence copy, installation, environment/Git/command change,
mutation, cleanup, or rerun is allowed. Exhaustion produces
`STOP_AND_REPORT_MISSING_EVIDENCE` with budget usage and missing evidence.

Supervisor server-read verification is non-authorizing evidence checking under
exact named `/mnt/DiskM/by` roots only: 15 minutes, 20 commands, four roots,
10 MB returned text, no recursive root scan, mutation, execution, installation,
cleanup, process control, or path escape. Repository policy does not itself
grant SSH/platform capability. Exhaustion requires a new bounded diagnosis.

## Stage-end and targeted review

Supervisor locks `review_base_sha` at activation; final candidate becomes
`review_head_sha`.

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

Review covers the full substantive delta, Executor/Runner self-checks, final
evidence, Hard Gates, diagnostics, generator trustworthiness, coverage debt,
and model/cost invariants. Reviewer never dispatches, writes, closes, gates,
authorizes, or manufactures evidence.

Default is `NO_INTERMEDIATE_REVIEW`; at most one narrow targeted review may be
Supervisor-dispatched for semantic change, weakened/removed gate, validator or
evidence-generator change, destructive/protected operation, unresolved
architecture, Supervisor scope uncertainty, or an unreviewed high-risk change
before a high-cost formal run. It never replaces stage-end review or authorizes
progress. A second high-risk issue requires stage split or escalation, never a
silent skip.

## Evidence and historical boundary

Hard Gate, Diagnostic, and Trend are reported separately. Evidence uses
`path#field`/`path#section`; long machine output remains in structured/durable
evidence. Routine lane output has one decision, at most five findings, five
diagnostics, one next action, and one compact handoff.

Protocols 05–08 remain byte-preserved below their prominent
`DEPRECATED_NON_CANONICAL` banners. Their prospective authority is `NONE`.
They cannot dispatch, define current state/review cadence/diagnosis ownership,
or authorize action. Their valid protections are directly normalized here.

## Candidate hard gates and stop conditions

The candidate requires exact parent/branch, governance-only allowlist,
append-only worklogs, resolved links, parsable structured blocks,
`git diff --check`, no conflict markers, protected refs, clean pushed identity,
and local/tracking/remote equality. Stop on any runtime/model/config/input,
cost-semantic, server, Runner, Stage 9/10, protected-ref, destructive-Git, or
historical-worklog rewrite.

After push, Executor reports only to Supervisor. Supervisor verifies the exact
SHA and dispatches one stage-end review. This candidate itself authorizes no
Reviewer contact, Runner, Stage 9, Stage 10, or server action.
