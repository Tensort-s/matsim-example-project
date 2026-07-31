# Current integration stage

This is the canonical compact active-task record. Stable rules are in
[`INTEGRATION_POLICY.md`](INTEGRATION_POLICY.md); lane identity and write
scope are in [`agent-lanes.md`](../../agent-lanes.md).

| Field | Value |
|---|---|
| task_id | `CONTROL-PROTOCOL-01 - Hub-and-spoke lane messaging protocol` |
| status | `PENDING_SUPERVISOR_VERIFICATION_AND_REVIEWER_DISPATCH` |
| exact_input_sha | `9235ccb62dbea43a2f321e4fba2aee6e5629bce0` |
| stage_5_status | `PASS_CLOSED` |
| authorized_owner | `INT-EXECUTOR` only |
| authority_source | `INT-SUPERVISOR` only |
| runner_authorized | `false` |
| stage_6_authorized | `false` |
| brief | [`stage-briefs/CONTROL_PROTOCOL_01_HUB_AND_SPOKE.md`](stage-briefs/CONTROL_PROTOCOL_01_HUB_AND_SPOKE.md) |
| stage_5_validation | [`../../data/taxi/hongkong/processed/taxi_scoring_composition_stage5_validation_v1/stage5_taxi_scoring_composition_validation.json`](../../data/taxi/hongkong/processed/taxi_scoring_composition_stage5_validation_v1/stage5_taxi_scoring_composition_validation.json) |

## Objective

Adopt Supervisor-centered real-time messaging while retaining Git worklogs as
append-only audit evidence. Lane identities and write scopes do not change.

## Authorized delta

- `agent-lanes.md` and integration governance/status/brief Markdown;
- narrow stale control-plane wording in onboarding/integration documentation;
- compact append-only Supervisor-transferred handoffs in all four lane
  worklogs.

## Forbidden delta

Stage 6; Java/Python implementation; model or behavioral semantics; MATSim
configuration, plans, network, schedule, vehicles, facilities, demand, supply,
capacity, city metadata or run manifest; Runner/server/MATSim execution; and
master or protected-feature changes.

## Evidence references

- Messaging authority and audit distinction:
  `docs/integration/INTEGRATION_POLICY.md#hub-and-spoke-lane-messaging-protocol`
- Lane scopes and standard loop:
  `agent-lanes.md#authority-and-evidence-boundary` and
  `agent-lanes.md#standard-stage-loop`
- Stage 5 closure:
  `docs/agent-worklogs/integration-supervisor.md#entry-11--stage-5-gate-closure`

## Next action

After one focused push, Executor reports the exact SHA and compact handoff only
to Supervisor and stops. Supervisor verifies and, if appropriate, dispatches
Reviewer. Stage 6 and Runner remain unauthorized.
