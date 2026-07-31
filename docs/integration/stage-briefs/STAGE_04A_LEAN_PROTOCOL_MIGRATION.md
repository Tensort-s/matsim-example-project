# Stage 4A — Lean multi-agent protocol migration

Stable rules: [`../INTEGRATION_POLICY.md`](../INTEGRATION_POLICY.md)

Lane authority: [`../../../agent-lanes.md`](../../../agent-lanes.md)

```yaml
stage_id: "Stage 4A - Lean multi-agent protocol migration"
exact_input_sha: "75988d2645f55a36fb6271ff49d887c1b5143c1b"
authorized_owner: "INT-EXECUTOR"
handoff_target: "INT-REVIEWER and INT-SUPERVISOR"
```

## Objective

Move stable protocol into canonical repository files so future cross-session
commands contain only current-stage deltas and evidence references.

## Allowed scope

- Create the policy, current-stage record, this brief and the brief index.
- Link all four new paths from `agent-lanes.md`.
- Append compact entries to existing worklogs without changing historical
  bytes/content.
- Correct stale stage-status wording in integration documentation.

## Hard gates

1. The delta is governance/documentation only.
2. Historical worklog content is unchanged; new records are append-only.
3. Lane authority and write scopes are unchanged.
4. Taxi/PT/Car semantics, Java/Python model logic, MATSim config/plans/supply,
   runtime/scoring, inputs and outputs are unchanged.
5. Stage 3 SHA `75988d2645f55a36fb6271ff49d887c1b5143c1b`
   remains traceable.
6. `agent-lanes.md` links every new path.
7. The compact worklog schema, lane budgets and evidence-by-reference rules
   are documented.
8. `git diff --check` passes.
9. The final branch is clean and local/tracking/remote refs equal the pushed
   Stage 4A SHA.
10. Protected master and Taxi/PT/Car feature refs remain unchanged.

Diagnostics cover only non-blocking readability, link, wording or migration
ambiguity. A diagnostic fails this stage only when it breaks a hard gate.

## Evidence required

- Exact input/output SHAs and changed-path list.
- Historical worklog prefix hashes/lengths before and after append.
- `agent-lanes.md` links to all four new paths.
- Policy/schema references by path and section.
- Diff check, clean status, ref equality and protected-ref checks.

## Stop condition

Stop if completion would require a model/runtime/config/input/output change,
closed-history rewrite, lane-authority change, MATSim/server execution, Runner
authorization, master/feature modification, or substantive Stage 4 work.

## Handoff

Push the exact governance-only result, send one compact handoff with
`hard_gate_status=PENDING_INDEPENDENT_REVIEW_AND_SUPERVISOR_STAGE_4A_GATE`,
then stop.
