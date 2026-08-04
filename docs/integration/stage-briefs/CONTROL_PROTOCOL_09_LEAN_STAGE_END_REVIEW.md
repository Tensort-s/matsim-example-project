# CONTROL-PROTOCOL-09 — lean stage-end review

## Candidate identity

- Task ID: `CONTROL-PROTOCOL-09-LEAN-STAGE-END-REVIEW`
- Exact input/parent SHA: `e9bc965721b7842c7bfaaeb549ee08de038454c4`
- Owner/writer: `INT-EXECUTOR`
- Gate/dispatch owner: `INT-SUPERVISOR`
- Reviewer: read-only, one stage-end review after Supervisor SHA verification
- Runner authorized: `false`
- Stage 10 or later authorized: `false`

This candidate changes governance documentation only. It does not run Stage 9
or Stage 10, touch server state, or change implementation, model, cost,
configuration or input semantics. Stable policy is in
[`INTEGRATION_POLICY.md`](../INTEGRATION_POLICY.md); compact current facts are
in [`CURRENT_STAGE.md`](../CURRENT_STAGE.md).

## Default stage loop

```text
Supervisor objective + Hard Gates
  -> Executor implementation + executor_self_check
  -> Runner build/deploy/run + runner_self_check + final structured evidence
     only when explicitly authorized
  -> one independent Reviewer stage_end_review
  -> Supervisor PASS_CLOSED or BLOCKED
```

Supervisor remains the sole dispatcher and gate owner. Executor is the sole
Git writer. Runner writes no Git state and cannot self-authorize. Reviewer is
read-only. User direction is required for research, economic, behavioral,
missing-data and cost-policy semantics. Executor and Runner self-checks never
replace independent review.

## Executor internal correction and self-check

Executor may correct an ordinary technical defect internally before the one
candidate push only when all of these remain true:

- the correction stays inside the original objective and path allowlist;
- no Hard Gate is weakened and no validator/test is deleted or relaxed;
- no model, cost, economic or behavioral semantic changes;
- no scope expansion, protected-ref/destructive action or server run;
- unresolved ambiguity is reported rather than guessed.

There is no intermediate or repair-by-repair review for such corrections.
Before push, Executor records:

```yaml
executor_self_check:
  stage_id: string
  exact_input_sha: full_sha
  branch: integration/hk-multimodal-cost-v1
  worktree: F:/Matsim/worktrees/hk-cost-integration
  changed_paths: []
  compile: {required: true_or_false, command: string_or_null, result: string}
  tests: {required: true_or_false, commands: [], result: string}
  negative_tests: {required: true_or_false, commands: [], result: string}
  validators: {commands: [], result: string}
  diff_check: PASS_or_FAIL
  conflict_check: PASS_or_FAIL
  protected_refs: PASS_or_FAIL
  semantic_contract: UNCHANGED_or_explained
  unresolved_items: []
```

After push, the handoff adds exact output SHA, parent, local/tracking/remote
equality, ahead/behind `0/0`, and clean worktree.

## Runner execution contract and self-check

Runner acts only under an exact Supervisor authorization and follows:

```text
preflight -> build -> artifact validation -> bundle -> release
-> runtime preflight -> run -> final structured evidence
```

Runner evidence verifies source SHA, locked inputs, toolchain, root Shade JAR,
bundle/release/run identity, SHA continuity, class loading, requested iteration
completion, output completeness, non-finite values, diagnostics and coverage.
It includes `runner_self_check` and cites durable evidence by path/field.

```yaml
runner_self_check:
  source_sha: full_sha
  locked_inputs: {result: PASS_or_FAIL, evidence_refs: []}
  toolchain: {result: PASS_or_FAIL, versions: {}, evidence_refs: []}
  root_shade_jar: {result: PASS_or_FAIL, sha256: string_or_null, evidence_refs: []}
  bundle: {result: PASS_or_FAIL, identity: string_or_null, sha256: string_or_null}
  release: {result: PASS_or_FAIL, identity: string_or_null, evidence_refs: []}
  run_identity: string_or_null
  sha_continuity: PASS_or_FAIL
  class_loading: PASS_or_FAIL
  iteration_completion: PASS_or_FAIL
  output_completeness: PASS_or_FAIL
  nonfinite_values: {count: number, result: PASS_or_FAIL}
  diagnostics: []
  coverage_limitations: []
  unresolved_items: []
```

`CONTRACT_PRESERVING_PREFLIGHT_CORRECTION` remains allowed only before build,
bundle, release and run, with zero state mutation, one canonical replacement,
unchanged task semantics and no new identity. It is not a formal retry. After
execution starts, a technical failure stops immediately and enters bounded
read-only diagnosis; Runner cannot modify state, repair or rerun.

## Reviewer default: STAGE_END_ONLY

Reviewer receives one final candidate after Supervisor verifies its exact SHA
and parent. No intermediate implementation, repair, protocol, evidence-binding
or closure commit review occurs by default. Review covers the full substantive
delta since the prior `PASS_CLOSED`, the final candidate, Executor and Runner
self-checks, final run evidence, Hard Gates, Diagnostics, coverage limitations,
evidence-generator trustworthiness and model/cost invariants.

```yaml
stage_end_review:
  reviewed_stage: string
  reviewed_candidate_sha: full_sha
  reviewed_run_identity: string_or_null
  decision: PASS | BLOCKED
  findings: []
  coverage_limitations: []
  blockers: []
  evidence_refs: []
  handoff_to: INT-SUPERVISOR
```

Reviewer never writes, dispatches, closes a stage or authorizes Runner, retry
or a next stage. Supervisor consumes `PASS` directly; there is no
verdict-only or closure-only follow-up commit.

## Targeted review exception

Default is `NO_INTERMEDIATE_REVIEW`; at most one targeted review may occur per
stage. Supervisor may dispatch it only for one of these high-risk conditions:

1. model, cost, economic or behavioral semantic change;
2. weakened or removed Hard Gate;
3. validator or evidence-generator change;
4. destructive or protected-ref operation;
5. unresolved architecture;
6. Supervisor scope uncertainty;
7. a high-cost formal run carrying an unreviewed high-risk change.

It answers one narrow question, never replaces stage-end review and never
authorizes progress.

## Failure classes and formal states

Only three failure classes are canonical:

- `INFORMATIONAL`: safely correct or diagnose within scope; no automatic
  blocker.
- `TECHNICAL`: stop, then bounded read-only diagnosis; `KNOWN` produces a
  bounded repair, while `PARTIAL` or `UNKNOWN` produces further diagnosis.
- `SEMANTIC`: escalate to the user before changing research meaning.

Only four formal stage states exist: `READY`, `RUNNING`, `BLOCKED`, and
`PASS_CLOSED`. Diagnosis, repair, review and handoff statuses are append-only
worklog events, not canonical long-lived stage states.

## Consolidation and retained protections

Protocols 05–08 are preserved and marked
`HISTORICAL_DETAIL__CONSOLIDATED_BY_PROTOCOL_09`; they are not deleted. Their
valid protections remain in force: exact source/artifact/bundle/release/run
identity, immutable run directories, no implicit rerun, read-only diagnosis,
`KNOWN/PARTIAL/UNKNOWN`, diagnosis budgets, execution contracts, bounded
Supervisor server reads, semantic escalation and lane boundaries.

A validator PASS is not Stage PASS. A self-check is not independent review.
Evidence-generator trust and coverage limitations remain explicit Hard Gate
inputs.

## Candidate gates and stop conditions

Required checks are exact parent and branch, governance-only allowlist,
append-only worklogs, parsable structured blocks, resolved links,
`git diff --check`, no conflict markers, protected refs, clean pushed identity
and local/tracking/remote equality. Stop on any runtime/model/config/input,
server, Runner, Stage 10, protected-ref, historical-worklog or semantic change.

After push, Executor reports only to Supervisor. Supervisor verifies the exact
candidate SHA and dispatches exactly one stage-end review. This brief itself
does not authorize Reviewer, Runner or Stage 10.
