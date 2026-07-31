# Stage 4 — Completeness and integration-boundary audit

Stable protocol, lane authority and reporting limits are defined in
[`../INTEGRATION_POLICY.md`](../INTEGRATION_POLICY.md) and
[`../../../agent-lanes.md`](../../../agent-lanes.md).

| Field | Value |
|---|---|
| Exact input | `3cbe393ec262550ab27bc13635614b8f0440c958` |
| Owner | `INT-EXECUTOR` only |
| Runner authorized | `false` |
| Authoritative manifest | [`../../../data/transport_costs/hongkong/integrated_multimodal_cost_source_interface_manifest_v1.json`](../../../data/transport_costs/hongkong/integrated_multimodal_cost_source_interface_manifest_v1.json) |
| Handoff target | `INT-REVIEWER`, then `INT-SUPERVISOR` |

## Objective and allowed delta

Audit the three locked source merges and establish one authoritative integrated
source/interface registry before PT or Car runtime work. The delta is limited
to the manifest, this compact brief, current-stage/control documentation, and
append-only lane worklogs. Deterministic release validators and Maven tests
may run; MATSim scenarios and server tasks may not.

## Hard gates

- Exact input/output identity, clean refs, merge topology and all locked source
  ancestors are proven.
- The integrated manifest is the only authoritative combined registry and
  contains one unique canonical interface for Taxi, PT and Car.
- Taxi remains the unchanged native runtime and single route-fare charge path.
- PT and Car remain offline-only; historical, candidate, accounting,
  design-only and superseded artifacts cannot control the current architecture.
- No implementation, model, configuration, plan, supply, input, output,
  scoring, monetary-utility, ASC, demand, capacity or behavioral semantic
  changes occur.
- Deterministic validators/tests, structured-file/path checks, Markdown links,
  `git diff --check`, final cleanliness and protected-ref checks pass.
- Historical worklogs remain byte-preserved prefixes; new records are appended
  only.

## Diagnostics and stop condition

Warnings, validator duration and preserved duplicate/legacy inventory are
diagnostic unless they demonstrably break a hard gate. Stop on exact-SHA
inconsistency, model-policy ambiguity, imputation or scoring/runtime need,
protected-ref change, destructive Git need, Stage 5 work, or any MATSim/server
run requirement.

## Evidence

Use the authoritative manifest fields, the existing Taxi/PT/Car release
validations referenced there, and the compact Executor handoff. The Executor
pushes one focused commit and stops for independent exact-SHA review.
