# Stage 10 — Deterministic multimodal cost coverage

| Field | Value |
|---|---|
| Task | `STAGE10-DETERMINISTIC-MULTIMODAL-COST-COVERAGE` |
| Exact input SHA | `48686c03f46372e4aed2bc9bd1bdeb1796a34fbe` |
| Owner | `INT-EXECUTOR` for implementation and local tests |
| Runner authorization | `false` |
| Stage 11+ authorization | `false` |

## Objective

Create one small, deterministic test person whose selected plan contains a
real `mode=taxi,routingMode=taxi` leg, a real PT leg, and a real
`mode=car,routingMode=car` leg. Exercise the canonical composable scoring
factory and prove that each declared fee is applied exactly once. This stage
does not run MATSim, use a production population, or change model semantics.

## Directed fixture contract

The fixture identity is `stage10-directed-multimodal-cost-v1` and the fixed
person is `stage10-directed-001`. Its three legs and predeclared expected
values are recorded in
[`stage10_directed_multimodal_cost_coverage_validation.json`](../../../data/transport_costs/hongkong/integration_stage10_validation_v1/stage10_directed_multimodal_cost_coverage_validation.json).

| Leg | Actual mode/routing mode | Expected fee (HKD) | Expected custom score |
|---|---|---:|---:|
| Taxi | `taxi/taxi`, urban taxi, 2,500 m | 35.3 | -1.765 |
| PT | `pt/pt`, MTR domestic fixture route | 4.9 | -9.8 |
| Car | `car/car`, private car, 1,000 m | 2.5 | -5.0 |

Taxi is intentionally constructed in the selected plan; `mode_detail` or
random population sampling is never used as a proxy for an experienced leg.
The PT and Car records use the existing locked fare and energy interfaces in
test-only catalog fixtures. Fixed ownership is excluded from the Car leg.

## Hard gates

1. Fixture identity and ordering are deterministic and reproducible; no random
   sampling or production inputs/configuration are read.
2. The same bounded selected plan contains one Taxi, one PT and one Car leg,
   each with its canonical routing mode; Taxi→ride is not introduced.
3. Every expected fee is declared before scoring and matches the observed
   component charge and score. The total expected fee is 42.7 HKD and the
   custom score is -16.565 with marginal utility of money 2.0 for PT/Car and
   the established Taxi utility 0.05.
4. Only the leg callback charges. Money-event, generic-event and trip callbacks
   are inert; replaying any of the three experienced legs fails closed.
5. Scores and explanations contain no NaN/Infinity; unresolved values are not
   converted into numeric zero; fixed vehicle ownership remains excluded.
6. The canonical Taxi native route/fare path and PT/Car interfaces are used
   unchanged. No production Java/Python model, cost policy, ASC, demand,
   capacity, plan, supply, config, locked input, bundle, release or server
   state is modified.
7. Maven focused tests, negative duplicate-charge assertions, JSON/link/diff/
   conflict/protected-ref/worktree checks pass. Runner and Stage 11 remain
   unauthorized.

## Evidence and stop condition

The durable result is the structured validation JSON above. The Executor may
perform ordinary local corrections within this test-only allowlist, but stops
and reports `BLOCKED` if satisfying the contract would require changing
production runtime/model or cost semantics. A substantive candidate is pushed
once for the single Protocol 09 stage-end review; this brief itself does not
authorize Runner or a MATSim execution.

```yaml
stage_id: "STAGE10-DETERMINISTIC-MULTIMODAL-COST-COVERAGE"
input_sha: "48686c03f46372e4aed2bc9bd1bdeb1796a34fbe"
fixture_id: "stage10-directed-multimodal-cost-v1"
status: "RUNNING"
runner_authorized: false
stage11_or_later_authorized: false
next_action: "Executor pushes candidate and stops for one independent Stage-end review"
```
