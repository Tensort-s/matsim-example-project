# CONTROL-PROTOCOL-01 — Hub-and-spoke lane messaging

Stable operating rules and compact reporting limits are defined in
[`../INTEGRATION_POLICY.md`](../INTEGRATION_POLICY.md). This brief records the
authorized control-plane-only migration.

## Identity and objective

- Exact input: `9235ccb62dbea43a2f321e4fba2aee6e5629bce0`
- Owner: `INT-EXECUTOR` only
- Stage 5: formally `PASS_CLOSED`
- Objective: make Supervisor the sole message aggregator, dispatch authority,
  gate authority and stage-progression center.

## Protocol

1. Executor, Reviewer and Runner exchange no execution authority with one
   another; each returns its complete handoff only to Supervisor.
2. Supervisor alone dispatches implementation, review, rework and run tasks.
3. A non-Supervisor direct message cannot authorize a write, repair, run,
   review dispatch, or next stage.
4. Real-time messages perform handoff and notification. Git worklogs only
   preserve append-only audit history.
5. `BLOCKED` is a finding for Supervisor, not repair authority. `PASS` is a
   verdict for Supervisor, not progression authority.
6. A verdict is appended during the next authorized write; no recursive
   log-only commit/review cycle is created.

## Allowed paths

- `agent-lanes.md`
- `docs/integration/`
- `docs/PROJECT_ONBOARDING.md`
- narrowly scoped control-status wording in
  `docs/HONG_KONG_MULTIMODAL_COST_INTEGRATION.md`
- append-only files under `docs/agent-worklogs/`

## Hard gates

- Exact input and governance/documentation-only delta.
- Lane IDs, authority boundaries and write scopes unchanged.
- Hub-and-spoke authority, non-Supervisor rule, real-time/audit distinction,
  and no-recursive-review rule documented.
- Stage 5 Reviewer PASS and Supervisor closure preserved append-only.
- Historical worklog prefixes unchanged.
- All control-plane links resolve; `git diff --check` passes.
- Clean pushed local/tracking/remote identity; protected refs unchanged.
- No Runner, Stage 6, model, runtime, config or input change.

## Stop condition

Executor makes one focused commit, pushes it, reports only to Supervisor, and
stops. Supervisor owns verification and Reviewer dispatch. Stage 6 and Runner
remain unauthorized.
