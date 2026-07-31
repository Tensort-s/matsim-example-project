# Current integration stage

This is the canonical compact active-stage record. Stable rules are in
[`INTEGRATION_POLICY.md`](INTEGRATION_POLICY.md); lane authority is in
[`agent-lanes.md`](../../agent-lanes.md).

| Field | Value |
|---|---|
| stage_id | `Stage 4A - Lean multi-agent protocol migration` |
| status | `PENDING_INDEPENDENT_REVIEW_AND_SUPERVISOR_STAGE_4A_GATE` |
| exact_input_sha | `75988d2645f55a36fb6271ff49d887c1b5143c1b` |
| result_ref | `integration/hk-multimodal-cost-v1` HEAD; exact pushed SHA is returned in the Executor handoff |
| authorized_owner | `INT-EXECUTOR` only |
| runner_authorized | `false` |
| substantive_stage_4_authorized | `false` |
| brief | [`stage-briefs/STAGE_04A_LEAN_PROTOCOL_MIGRATION.md`](stage-briefs/STAGE_04A_LEAN_PROTOCOL_MIGRATION.md) |

## Objective

Move stable integration rules into canonical repository files so future
cross-session commands carry only current-stage deltas and reference evidence
by path and field.

## Authorized delta

- `docs/integration/INTEGRATION_POLICY.md`
- `docs/integration/CURRENT_STAGE.md`
- `docs/integration/stage-briefs/STAGE_04A_LEAN_PROTOCOL_MIGRATION.md`
- `docs/integration/stage-briefs/README.md`
- `agent-lanes.md` links and canonical-source declaration
- append-only compact entries in existing worklogs
- stale stage-status wording in integration documentation

## Forbidden delta

Taxi, PT or Car implementation/data semantics; Java/Python model logic;
MATSim config, plans, supply, runtime, scoring, inputs or outputs; server or
MATSim execution; Runner authorization; master/feature modification; and the
substantive Stage 4 completeness audit.

## Evidence references

- Stage 3 exact result:
  `data/transport_costs/hongkong/integration_stage3_validation_v1/stage3_car_merge_validation.json`
- Stage 4A hard gates:
  `docs/integration/stage-briefs/STAGE_04A_LEAN_PROTOCOL_MIGRATION.md#hard-gates`
- Historical-prefix verification and exact pushed SHA: compact Executor
  handoff for this stage

## Next action

INT-REVIEWER reviews the exact pushed Stage 4A SHA; INT-SUPERVISOR then decides
the gate. No substantive Stage 4 or Runner action begins from this file.
