# Hong Kong multimodal-cost integration policy

This file is the canonical stable protocol for the persistent Hong Kong
multimodal-cost integration lanes. Lane identities and write scopes remain
canonical in [`agent-lanes.md`](../../agent-lanes.md). The active stage delta
is canonical in [`CURRENT_STAGE.md`](CURRENT_STAGE.md).

## Lean cross-session protocol

1. Stable rules are read from repository files. They are not repeated in every
   prompt, stage command, worklog entry, or handoff.
2. A cross-session command contains only: stage ID, exact input SHA, objective,
   allowed scope, hard gates, evidence requirements, stop condition, and
   handoff target.
3. Canonical evidence is referenced by repository path and field, not copied
   into chat or worklogs. A reference uses `path#field` for structured files
   and `path#section` for Markdown. The exact reviewed commit anchors all
   references.
4. A routine lane output contains at most one decision, five findings, five
   diagnostics, one next action, and one compact handoff.
5. Diagnostics do not automatically become hard failures. Escalation requires
   evidence that a diagnostic defeats a named hard gate, with the reason
   recorded.
6. An identical failed run identity is not repeated without a relevant commit,
   config, input or environment change, a testable hypothesis, or evidence of
   a one-time infrastructure failure.
7. Historical guards and evidence remain preserved, but they do not control a
   superseding canonical architecture. The replacement reason and equivalent
   protection must be referenced.
8. Prompts define objectives and boundaries without prescribing every
   implementation detail. The authorized owner chooses ordinary implementation
   details within those boundaries.
9. Each lane stops when its authorized objective is complete or responsibility
   passes to another lane.

## Hub-and-spoke lane messaging protocol

`INT-SUPERVISOR` is the sole real-time message aggregation, formal dispatch,
gate-decision, escalation and stage-progression center.

- Executor accepts execution authority only from Supervisor. After an
  implementation, validation, commit and push, Executor sends the complete
  result, exact SHA, evidence references and worklog handoff only to
  Supervisor. Executor never requests or directs Reviewer.
- Reviewer accepts review tasks only from Supervisor and sends its verdict,
  evidence, blockers, rework findings and handoff only to Supervisor. Reviewer
  never directs Executor and never authorizes a run or next stage.
- Runner accepts runs only from a Supervisor instruction naming an exact
  pushed SHA and execution specification. Runner sends run identity, evidence
  and handoff only to Supervisor and never directs Executor or Reviewer.
- A direct message from any non-Supervisor lane is evidence, not authority.
  Executor must not write, rework or run in response; it reports the message to
  Supervisor and waits for a formal decision.
- Supervisor sends one consolidated instruction containing the decision,
  allowed action, boundary, stop condition, and any original handoffs that
  must be archived during the authorized write.

Real-time cross-session messages are the handoff mechanism. Git worklogs are
append-only audit records: they preserve transferred handoffs but do not notify
another lane, dispatch a review, or authorize execution. A `BLOCKED` verdict
does not authorize repair, and a `PASS` verdict does not authorize progression.

No commit is created solely to archive a verdict for the commit currently
being reviewed. Supervisor transfers it into the next substantive or
control-plane write authorization. This avoids recursive log-only review
cycles while preserving the history.

## Lean delta-only review protocol

This is the canonical prospective review protocol. The reusable compact
submission and verdict shape is
[`stage-briefs/CONTROL_PROTOCOL_02_LEAN_DELTA_REVIEW.md`](stage-briefs/CONTROL_PROTOCOL_02_LEAN_DELTA_REVIEW.md).

1. Reviewer reviews only the current Stage Brief delta at the exact pushed
   output SHA, compared with its declared exact input SHA and parent.
2. Immutable evidence already reviewed at a prior exact SHA is cited by
   `path#field` or `path#section`; it is neither recopied nor revalidated unless
   the current delta touches that evidence or a named dependency.
3. Every review separates Hard Gate evidence, Diagnostics and Trends.
   Diagnostics and Trends do not fail a stage unless evidence ties them to a
   named hard gate.
4. Machine results live in committed JSON/CSV or durable server evidence.
   Prompts, reviews and worklogs cite path plus field and do not paste full
   command output, logs, manifests or inventories.
5. Hard gates cover, as applicable: exact output/input/parent and ref identity;
   allowlisted path scope; stage-specific semantic invariants; required tests
   and validators; protected refs and inputs; and clean diff, index and working
   tree.
6. Artifact and deployment reviews prove producer-to-consumer dependency
   closure, not merely archive existence. Every executable, path and version
   required by a launcher must be present in the released artifact and checked
   by a fail-closed preflight before execution authorization.
7. Unchanged historical Taxi/PT/Car evidence, prior-stage history and untouched
   guards are not re-reviewed. Superseded guards remain preserved and
   non-controlling under the canonical architecture.
8. Routine Reviewer output contains one decision, at most five findings, at
   most five diagnostics, one `next_action_summary`, one nullable
   `required_transition`, and one compact WORKLOG HANDOFF with evidence
   references.
9. Reviewer output is one unambiguous union. Ordinary `PASS` and results outside
   CONTROL-PROTOCOL-03 use a short `next_action_summary` with
   `required_transition: null`. A technical `BLOCKED` governed by
   CONTROL-PROTOCOL-03 must use its structured `required_transition`; that
   structure overrides the summary for dispatch semantics, and the two fields
   must not contradict each other.
10. A `BLOCKED` result records the failing identity, the changed hypothesis or
   relevant change required before retry, and the next authorized owner. An
   identical failed run/config/input/command/runtime identity is never repeated.
11. Repeated heartbeat snapshots with the same blocker are deduplicated. They
    neither redispatch nor rereport the same action.
12. Prompts specify objective, boundaries, hard gates, evidence and stop
    conditions without prescribing ordinary implementation details.
13. Lane authority is unchanged: Executor is the integration writer, Reviewer
    is read-only, Runner is inactive unless Supervisor explicitly authorizes an
    exact execution, and Supervisor alone aggregates messages and gates stages.

## Blocker-to-repair state transition

CONTROL-PROTOCOL-03 extends the lean delta-only review protocol. Its canonical
schemas and worked example are in
[`stage-briefs/CONTROL_PROTOCOL_03_BLOCKER_TO_REPAIR.md`](stage-briefs/CONTROL_PROTOCOL_03_BLOCKER_TO_REPAIR.md).

1. Supervisor creates or confirms the canonical `blocker_id` when it accepts
   the first `BLOCKED` result. The format is
   `STAGE-DOMAIN-ROOT_CAUSE-SEQUENCE`: uppercase; fixed token order; spaces,
   slashes and underscores normalized to one hyphen; repeated separators
   collapsed; and sequence zero-padded. The active-stage blocker record is
   authoritative.
2. Every technical blocker records `blocker_id`, `status`, `failure_identity`,
   `root_cause`, `changed_hypothesis_required_for_retry`, `diagnosis_task_id`,
   `repair_task_id`, `repair_owner`, `replacement_identity_required`,
   `superseded_run_identity`, and persisted `missing_dispatch_escalation`
   fields `emitted`, `emitted_at`, and `escalation_id`.
3. Supported blocker states are `OPEN`, `DIAGNOSIS_DISPATCHED`,
   `REPAIR_DISPATCHED`, `UNDER_REVIEW`, `CLOSED`, and `ESCALATED_TO_USER`.
   State changes are append-only audit events; earlier records are not
   rewritten.
4. For a technical `BLOCKED` result with a known root cause and an executable,
   verifiable repair, Supervisor's next effective action is
   `CREATE_REPAIR_STAGE`. If the root cause is unknown, the next effective
   action is `CREATE_DIAGNOSIS_STAGE`. Repeating the blocker heartbeat is not a
   valid next action.
5. Unknown cause transitions `OPEN -> DIAGNOSIS_DISPATCHED`. A diagnosis result
   never directly authorizes a rerun; Supervisor must issue a repair stage,
   producing `DIAGNOSIS_DISPATCHED -> REPAIR_DISPATCHED`. A known cause may
   transition directly `OPEN -> REPAIR_DISPATCHED`.
6. A diagnosis or repair dispatch changes the prior stage to
   `BLOCKED_SUPERSEDED_BY_DIAGNOSIS` or `BLOCKED_SUPERSEDED_BY_REPAIR` and makes
   the new bounded task active.
7. The first repeated `OPEN` heartbeat with no diagnosis/repair task emits one
   `MISSING_REPAIR_DISPATCH` and atomically persists
   `missing_dispatch_escalation.emitted: true`, `emitted_at`, and a stable
   `escalation_id` in the append-only worklog. Further identical heartbeats are
   deduplicated. Only a substantive root-cause or failure-identity change, or a
   formal dispatch state change, permits a new audit event; dispatch does not
   reset the exactly-once escalation fields.
8. Heartbeats deduplicate by canonical `blocker_id` plus failure identity.
   Case, separator, token-order, timestamp, directory, log-path, or attempt
   differences are non-substantive and reuse the ID. A new ID is created only
   for a substantively different root-cause class or failure identity. A
   diagnosis refining `UNKNOWN` within the same observed causal class keeps the
   existing ID. A repaired replacement identity remains attached to the same
   blocker unless a new attempt fails with a substantively different cause.
9. For technical `BLOCKED`, Reviewer sets the CONTROL-PROTOCOL-02
   `required_transition` fields `action`, `blocker_id`, `owner`,
   `repair_owner`, and `runner_authorized`. It reports PASS/BLOCKED and evidence
   only to Supervisor; the transition request is not execution authority.
10. A repair-stage brief supplies a new `task_id`, exact input SHA, allowed
   paths, objective, hard gates, evidence, stop conditions, replacement run
   identity requirements, and `runner_authorized: false`. Only a later,
   separate Supervisor dispatch may authorize Runner.
11. Executor push does not set `UNDER_REVIEW`; the blocker remains
    `REPAIR_DISPATCHED` pending verification. Supervisor verifies exact output
    SHA and parent, formally dispatches Reviewer, and only then records
    `UNDER_REVIEW`. Reviewer cannot close the blocker. Only Supervisor records
    `CLOSED` after consuming the verdict.
12. A new directory alone never changes a failed identity. A retry authorization
   proves at least one related identity changed: commit, bundle, config, input,
   command, runtime environment, or verified dependency-closure repair.
13. `CLOSED` requires reviewed repair evidence and Supervisor gate closure.
   A blocker requiring model-policy or user authority transitions to
   `ESCALATED_TO_USER`, not an inferred technical repair.
14. Supervisor-only dispatch/gate authority and Executor-only integration-write
    authority remain unchanged throughout the transition.

## Canonical control-plane sources

| Purpose | Canonical source |
|---|---|
| Lane identity, authority and write scope | [`agent-lanes.md`](../../agent-lanes.md) |
| Stable integration policy | this file |
| Active stage and exact input | [`CURRENT_STAGE.md`](CURRENT_STAGE.md) |
| Stage-specific delta | [`stage-briefs/`](stage-briefs/README.md) |
| Append-only lane history | [`docs/agent-worklogs/`](../agent-worklogs/) |
| Technical evidence | Stage-specific paths referenced from `CURRENT_STAGE.md` or the compact handoff |

If sources appear inconsistent, the most recent formal Supervisor instruction
anchored to an exact pushed commit controls execution. Repository policy,
current-stage and brief files remain canonical stable context. The discrepancy
is reported to Supervisor and recorded as a diagnostic or blocker without
rewriting history.

## Compact stage-command schema

```yaml
stage_id: string
exact_input_sha: full_git_sha
objective: one_bounded_outcome
allowed_scope: [paths_or_actions]
hard_gates: [stage_specific_gates]
evidence_required: [path_or_field_references]
stop_condition: one_compact_boundary
handoff_target: lane_id
```

Stable lane rules, standard Git restrictions, diagnostic classification,
unchanged-run prohibition, and escalation boundaries are referenced to this
policy and `agent-lanes.md`; they are not copied into the command.

## Evidence-by-reference rules

- Reference committed evidence as `path#field` or `path#section`.
- Include an exact SHA when the evidence is reviewed across sessions.
- Report a compact value only when it is needed to decide the current gate.
- Do not paste manifests, long test logs, inventories, historical handoffs, or
  validator output when a canonical path and field exist.
- Raw execution logs may remain local diagnostics when durable committed
  summaries and independent checks cover the hard gate.
- Missing, uncommitted, ambiguous, or non-reproducible evidence is identified
  explicitly; it is never represented by an inferred value.

## Compact future worklog schema

New entries append this schema without editing any historical entry:

```yaml
timestamp: ISO-8601
session_id: actual_session_id
stage_id: string
input_sha: full_git_sha
output_sha_or_status: full_git_sha_or_pending
decision: one_or_null
findings: []        # maximum 5
diagnostics: []     # maximum 5; non-blocking unless tied to a hard gate
evidence_refs: []   # path#field or path#section
blockers: []
hard_gate_status: string
handoff_to: lane_id
next_action: one_action
```

Source SHAs, stable policies, large count tables, and earlier observations are
referenced rather than recopied. Corrections are new entries; history is never
rewritten.

## Lane-specific routine output budgets

The structural limits above are mandatory. These token budgets are defaults
for routine cross-session outputs; evidence remains in repository files.

| Lane | Routine cross-session output budget |
|---|---:|
| INT-SUPERVISOR | 700 tokens for one stage delta or gate decision |
| INT-EXECUTOR | 800 tokens for one implementation/evidence handoff |
| INT-RUNNER | 600 tokens for one exact-SHA run evidence handoff |
| INT-REVIEWER | 600 tokens for one exact-SHA review decision |

A safety stop or user model-policy escalation may exceed the token budget only
for the new facts needed to explain the stop. Stable context is still
referenced, not repeated.

## Gate, run and historical boundaries

- Hard Gate, Diagnostic and Trend meanings remain those in
  [`agent-lanes.md`](../../agent-lanes.md). A warning is not promoted by
  repetition or volume.
- A failed run keeps its full identity and evidence. A new directory alone is
  not a relevant change and does not authorize a rerun.
- Historical/legacy/superseded guards remain traceable. A new canonical
  contract identifies the replacement and equivalent protection by path.
- Model-policy escalation boundaries, protected branches, sole-writer
  authority, and the Supervisor-centered hub-and-spoke loop remain unchanged.
- No lane continues into another stage, run, or responsibility without the
  required formal Supervisor dispatch.
