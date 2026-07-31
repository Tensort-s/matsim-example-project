# Stage 6 — Legal PT itinerary and PT/walk stuck governance

Stable rules and hub-and-spoke messaging are in
[`../INTEGRATION_POLICY.md`](../INTEGRATION_POLICY.md).

| Field | Value |
|---|---|
| exact input | `d9f6c10e506e7c43a9d44d7d3cb772e5e9b8b41a` |
| owner | `INT-EXECUTOR` only |
| status | `PENDING_INDEPENDENT_REVIEW_AND_SUPERVISOR_STAGE_6_GATE` |
| Runner | not authorized |

## Objective

Add deterministic, read-only prepared-PT itinerary legality checks and
event-linked PT/walk stuck classification without activating PT/Car scoring or
changing Taxi behavior, fares, inputs, supply, demand, capacity, or policy.

## Authorized implementation

- `HongKongPtItineraryAudit` validates sequence, schedule references, stop
  order and permissions, service availability, finite/nonnegative values, and
  access/egress/transfer continuity.
- `HongKongTaxiSmokeRuntimeGuard` runs that read-only audit before QSim and
  records its classification beside any future stuck event.
- Focused fixtures, structured validation evidence, topic documentation, and
  append-only worklogs are included.

## Evidence

- [`../../HONG_KONG_PT_ITINERARY_AND_STUCK_GOVERNANCE.md`](../../HONG_KONG_PT_ITINERARY_AND_STUCK_GOVERNANCE.md)
- [`../../../data/transport_costs/hongkong/integration_stage6_validation_v1/stage6_pt_itinerary_stuck_governance_validation.json`](../../../data/transport_costs/hongkong/integration_stage6_validation_v1/stage6_pt_itinerary_stuck_governance_validation.json)
- [`../../../data/transport_costs/hongkong/integration_stage6_validation_v1/stuck_root_cause_taxonomy.csv`](../../../data/transport_costs/hongkong/integration_stage6_validation_v1/stuck_root_cause_taxonomy.csv)
- `src/test/java/org/matsim/project/hongkong/pt/HongKongPtItineraryAuditTest.java`

No production Hong Kong scenario or server run was authorized. Historical
79,045 PT stuck events remain runtime-cause unresolved; they are not inferred
to be a capacity, supply, fare, or itinerary failure.

## Stop

After one focused push, Executor reports only to Supervisor and stops.
Reviewer dispatch, Runner action, Stage 7, and any PT runtime scoring require a
new Supervisor authorization.
