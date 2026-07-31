# Current integration stage

This is the canonical compact active-task record. Stable rules are in
[`INTEGRATION_POLICY.md`](INTEGRATION_POLICY.md); lane identity and write
scope are in [`agent-lanes.md`](../../agent-lanes.md).

| Field | Value |
|---|---|
| task_id | `Stage 6 - Legal PT itinerary and PT/walk stuck governance` |
| status | `PENDING_INDEPENDENT_REVIEW_AND_SUPERVISOR_STAGE_6_GATE` |
| exact_input_sha | `d9f6c10e506e7c43a9d44d7d3cb772e5e9b8b41a` |
| control_protocol_01_status | `PASS_CLOSED` |
| authorized_owner | `INT-EXECUTOR` only |
| authority_source | `INT-SUPERVISOR` only |
| runner_authorized | `false` |
| stage_7_authorized | `false` |
| brief | [`stage-briefs/STAGE_06_PT_ITINERARY_STUCK_GOVERNANCE.md`](stage-briefs/STAGE_06_PT_ITINERARY_STUCK_GOVERNANCE.md) |
| validation | [`../../data/transport_costs/hongkong/integration_stage6_validation_v1/stage6_pt_itinerary_stuck_governance_validation.json`](../../data/transport_costs/hongkong/integration_stage6_validation_v1/stage6_pt_itinerary_stuck_governance_validation.json) |

## Objective

Audit prepared PT itinerary legality and classify future PT/walk stuck events
deterministically without activating PT/Car scoring or changing Taxi behavior,
fare policy, inputs, demand, capacity, or supply.

## Authorized delta

- read-only PT itinerary/stuck audit logic and its Taxi runtime-guard hook;
- focused deterministic tests and structured validation evidence;
- relevant PT/Taxi/integration documentation and compact append-only
  Supervisor-transferred handoffs.

## Forbidden delta

PT or Car scoring/runtime activation; fare/transfer policy; economic
parameters; MATSim configuration, plans, network, schedule, vehicles,
facilities, demand, supply, capacity, city metadata or run manifest;
Runner/server/Hong Kong MATSim execution; Stage 7+; and master or
protected-feature changes.

## Evidence references

- Legality and stuck policy:
  `docs/HONG_KONG_PT_ITINERARY_AND_STUCK_GOVERNANCE.md`
- Structured implementation evidence:
  `data/transport_costs/hongkong/integration_stage6_validation_v1/stage6_pt_itinerary_stuck_governance_validation.json`
- Historical cause boundary:
  `stage6_pt_itinerary_stuck_governance_validation.json#historical_evidence`

## Next action

Executor reports the exact pushed SHA and compact handoff only to Supervisor
and stops. Supervisor verifies and, if appropriate, dispatches Reviewer.
Runner, Stage 7, and PT scoring remain unauthorized.
