# Stage 8B — Car confirmed toll runtime component

| Field | Value |
|---|---|
| Exact input | `5cc8aaaca0f5d5e073fff2792a29ed929c372139` |
| Owner | `INT-EXECUTOR` only |
| Authority | `INT-SUPERVISOR` |
| Runner | not authorized |
| Status | `PENDING_INDEPENDENT_REVIEW_AND_SUPERVISOR_STAGE_8B_GATE` |

## Objective

Add only canonical confirmed base toll beside the accepted Car energy
component, with one Car mode owner, explicit provenance, exact route evidence,
and exactly-once scoring.

## Authorized result

- hash-locked toll component, identification, and physical-event sources;
- distinct confirmed charge, confirmed no-charge, unresolved, and motorcycle
  behavior;
- exact key, distance, full-link-count, facility-link, fingerprint, ordinal,
  and callback guards;
- one `car_marginal_cost_v1` owner containing energy and toll subcomponents;
- focused tests, deterministic evidence, relevant documentation, and
  append-only worklogs.

## Boundaries

No toll inference or new rate/policy; no unresolved zero; no destination
parking, fixed ownership, motorcycle-as-private-car, config, plan, supply,
demand, capacity, city metadata, run manifest, Runner, MATSim/server run,
Stage 8C/9+, master, or protected-feature change.

## Evidence

- [`../../../data/transport_costs/hongkong/integration_stage8b_validation_v1/stage8b_car_confirmed_toll_runtime_validation.json`](../../../data/transport_costs/hongkong/integration_stage8b_validation_v1/stage8b_car_confirmed_toll_runtime_validation.json)
- [`../../../data/transport_costs/hongkong/integration_stage8b_validation_v1/toll_runtime_confirmation_matrix.csv`](../../../data/transport_costs/hongkong/integration_stage8b_validation_v1/toll_runtime_confirmation_matrix.csv)
- [`../../HONG_KONG_CAR_TOLL_RUNTIME.md`](../../HONG_KONG_CAR_TOLL_RUNTIME.md)

## Next action

Executor pushes one exact result and reports only to Supervisor. Supervisor
verifies and dispatches Reviewer. Executor does not begin Stage 8C/9 or
contact Reviewer.
