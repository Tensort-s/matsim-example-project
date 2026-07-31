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
