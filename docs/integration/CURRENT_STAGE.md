# Current integration stage

This is the canonical compact active-stage record. Stable rules are in
[`INTEGRATION_POLICY.md`](INTEGRATION_POLICY.md); lane authority is in
[`agent-lanes.md`](../../agent-lanes.md).

| Field | Value |
|---|---|
| stage_id | `Stage 4 - Completeness and integration-boundary audit` |
| status | `PENDING_INDEPENDENT_REVIEW_AND_SUPERVISOR_STAGE_4_GATE` |
| exact_input_sha | `3cbe393ec262550ab27bc13635614b8f0440c958` |
| result_ref | `integration/hk-multimodal-cost-v1` HEAD; exact pushed SHA is returned in the Executor handoff |
| authorized_owner | `INT-EXECUTOR` only |
| runner_authorized | `false` |
| stage_5_authorized | `false` |
| brief | [`stage-briefs/STAGE_04_COMPLETENESS_BOUNDARY_AUDIT.md`](stage-briefs/STAGE_04_COMPLETENESS_BOUNDARY_AUDIT.md) |
| authoritative_manifest | [`../../data/transport_costs/hongkong/integrated_multimodal_cost_source_interface_manifest_v1.json`](../../data/transport_costs/hongkong/integrated_multimodal_cost_source_interface_manifest_v1.json) |

## Objective

Audit the Taxi/PT/Car integration boundary and publish one authoritative
integrated source/interface manifest before PT or Car runtime/scoring work.

## Authorized delta

- `data/transport_costs/hongkong/integrated_multimodal_cost_source_interface_manifest_v1.json`
- `docs/integration/CURRENT_STAGE.md`
- `docs/integration/stage-briefs/STAGE_04_COMPLETENESS_BOUNDARY_AUDIT.md`
- `docs/integration/stage-briefs/README.md`
- append-only compact entries in existing worklogs
- narrowly scoped integration-boundary status/documentation wording

## Forbidden delta

Taxi, PT or Car implementation/data semantics; Java/Python model logic;
MATSim config, plans, supply, runtime, scoring, inputs or outputs; server or
MATSim execution; Runner authorization; master/feature modification; and Stage
5 implementation.

## Evidence references

- Integrated source/interface contract:
  `data/transport_costs/hongkong/integrated_multimodal_cost_source_interface_manifest_v1.json`
- Stage 4 hard gates:
  `docs/integration/stage-briefs/STAGE_04_COMPLETENESS_BOUNDARY_AUDIT.md#hard-gates`
- Exact commands, append-only prefix verification and pushed identity: compact
  Executor handoff for this stage.

## Next action

INT-EXECUTOR completes deterministic validation, pushes one focused Stage 4
result, and stops. INT-REVIEWER then reviews that exact SHA. No Stage 5 or
Runner action begins from this file.
