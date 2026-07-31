# Current integration stage

This is the canonical compact active-stage record. Stable rules are in
[`INTEGRATION_POLICY.md`](INTEGRATION_POLICY.md); lane authority is in
[`agent-lanes.md`](../../agent-lanes.md).

| Field | Value |
|---|---|
| stage_id | `Stage 5 - Composable multimodal scoring architecture (Taxi-only migration)` |
| status | `PENDING_INDEPENDENT_REVIEW_AND_SUPERVISOR_STAGE_5_GATE` |
| exact_input_sha | `191befd0c93027c5584857333a29746de8b432f0` |
| result_ref | `integration/hk-multimodal-cost-v1` HEAD; exact pushed SHA is returned in the Executor handoff |
| authorized_owner | `INT-EXECUTOR` only |
| active_scoring_modes | `taxi` only |
| pt_car_runtime_or_scoring | `false` |
| runner_authorized | `false` |
| stage_6_authorized | `false` |
| brief | [`stage-briefs/STAGE_05_COMPOSABLE_SCORING_TAXI_MIGRATION.md`](stage-briefs/STAGE_05_COMPOSABLE_SCORING_TAXI_MIGRATION.md) |
| authoritative_manifest | [`../../data/transport_costs/hongkong/integrated_multimodal_cost_source_interface_manifest_v1.json`](../../data/transport_costs/hongkong/integrated_multimodal_cost_source_interface_manifest_v1.json) |
| validation | [`../../data/taxi/hongkong/processed/taxi_scoring_composition_stage5_validation_v1/stage5_taxi_scoring_composition_validation.json`](../../data/taxi/hongkong/processed/taxi_scoring_composition_stage5_validation_v1/stage5_taxi_scoring_composition_validation.json) |

## Objective

Establish one composable Hong Kong scoring factory and migrate only the
already-canonical Taxi route-fare scorer, with exact implementation-level
equivalence to the pre-Stage-5 wrapper.

## Authorized delta

- generic scoring component/factory/composition interfaces and Guice wiring;
- the Taxi component adapter and canonical Taxi module binding;
- focused deterministic implementation tests;
- the integrated manifest, Stage 5 validation, relevant Markdown, and
  append-only compact worklog entries.

## Forbidden delta

PT or Car runtime/scoring; economic or behavioral policy; fare assumptions;
ASC/calibration; monetary utility; demand, capacity, supply, plans, inputs,
runtime configuration or outputs; MATSim/server runs; Runner authorization;
master merge; and Stage 6 or later work.

## Evidence references

- Unique composition and active-mode ownership:
  `data/transport_costs/hongkong/integrated_multimodal_cost_source_interface_manifest_v1.json#canonical_scoring_composition`
- Taxi equivalence and deterministic checks:
  `data/taxi/hongkong/processed/taxi_scoring_composition_stage5_validation_v1/stage5_taxi_scoring_composition_validation.json`
- Exact pushed identity and protected-ref checks: compact Executor handoff.

## Next action

INT-REVIEWER reviews the exact pushed Stage 5 SHA. INT-EXECUTOR stops; no
Stage 6 or Runner action starts without a later formal Supervisor decision.
