# CONTROL-PROTOCOL-05 — Atomic gate transition and non-recursive closure

| Field | Value |
|---|---|
| Task ID | `CONTROL-PROTOCOL-05-ATOMIC-GATE-TRANSITION` |
| Exact input | `c12a80fe8bca7a945eaaf39d00149fb3dd7838d4` |
| Owner | `INT-EXECUTOR` only |
| Reviewer | one final read-only exact-SHA review |
| Runner | unauthorized |

## Objective

Reconcile canonical current state with the already closed Stage 8D-R1 repair
and make atomic, non-recursive gate transitions the prospective governance
contract for stages, repairs, diagnoses, blockers, supersessions and
activations.

## Atomic transition

This commit performs one substantive control-plane transition:

- closes `STAGE8D-R1-JDK-RUNTIME-CLOSURE` canonically as `PASS_CLOSED` at
  repair SHA `339ef046c55faf3e727a19d32234612bd6974241`;
- preserves closure-evidence SHA
  `c12a80fe8bca7a945eaaf39d00149fb3dd7838d4`;
- moves blocker `STAGE9-RUNTIME-JDK-MISSING-001` from the stale canonical
  `REPAIR_DISPATCHED` state, through the already recorded `UNDER_REVIEW`
  dispatch, to `CLOSED`;
- preserves the original Stage 9 as `BLOCKED_SUPERSEDED_BY_REPAIR`;
- establishes explicit idle state with no active task or owner;
- keeps Runner and Stage 9 unauthorized and records that no new bundle,
  upload or smoke run occurred.

The authoritative machine-readable instance is the fenced YAML record in
[`CURRENT_STAGE.md`](../CURRENT_STAGE.md). Its schema is canonical in
[`INTEGRATION_POLICY.md#atomic-gate-transition-and-non-recursive-closure`](../INTEGRATION_POLICY.md#atomic-gate-transition-and-non-recursive-closure).

## Hard gates

- exact input and parent are `c12a80fe8bca7a945eaaf39d00149fb3dd7838d4`;
- current state, closed task, blocker, next idle task, authority and evidence
  are synchronized in one commit;
- `CURRENT_STAGE.md` contains no stale active Executor repair;
- `verdict_only_followup_commit_allowed=false` and one final review only;
- worklog history is prefix-identical with append-only additions;
- governance/control-plane paths only; no runtime, model, config, input,
  bundle, release, server or run delta;
- Runner and Stage 9 remain unauthorized;
- links, YAML, diff, conflict, clean-ref and protected-ref checks pass.

## Review and terminal behavior

Supervisor verifies the pushed exact SHA/parent/scope and dispatches exactly
one read-only review. Reviewer returns `PASS` or `BLOCKED` only to Supervisor.
Supervisor consumes that verdict in the real-time workflow and stops.

A `PASS` must not produce a commit that records the PASS, acknowledges this
closure, closes Protocol 05, or asks for another review. A future repository
write requires a new substantive Supervisor authorization. `CLOSED`, idle and
Reviewer `PASS` never authorize Runner, bundle upload, server execution or
Stage 9.

## Stop conditions

Stop on canonical-state/schema inconsistency, stale active task, missing
authority or evidence field, historical worklog rewrite, runtime/model/config/
input/bundle/server change, Runner or Stage 9 authorization, destructive Git,
or protected-ref change.
