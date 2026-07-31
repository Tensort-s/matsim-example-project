# Stage 5 — Composable multimodal scoring architecture (Taxi-only migration)

Stable operating rules and compact reporting limits are defined in
[`../INTEGRATION_POLICY.md`](../INTEGRATION_POLICY.md). This brief records only
the Stage 5 delta.

## Identity and objective

- Exact input: `191befd0c93027c5584857333a29746de8b432f0`
- Owner: `INT-EXECUTOR` only
- Objective: introduce a composable scoring architecture, migrate only the
  canonical Taxi route-fare scorer, and prove exact behavioral/scoring
  equivalence with its pre-Stage-5 wrapper.

## Authorized scope

- Generic scoring component, component-factory, composition and Guice seams.
- One Taxi route-fare adapter using the existing ordinal schedule and scorer.
- Implementation tests for unique ownership, fail-closed composition,
  lifecycle ordering, fare equivalence and duplicate prevention.
- Relevant manifest, validation, documentation and append-only worklogs.

PT and Car remain offline-only. No runtime fare lookup or component exists for
either mode.

## Hard gates

1. Exact input ancestry, protected refs and one clean pushed result.
2. One unique combined scoring factory with exactly one active component:
   `taxi_route_fare_v1`, owning only mode `taxi`.
3. Native `mode=taxi`/`routingMode=taxi`, standard `PrepareForSimImpl`, and
   route-before-fare lifecycle remain intact; Taxi-to-ride remains zero.
4. Pre/post Taxi score, callback forwarding and explanation are exactly
   equivalent; route fare and ordinal consumption remain fail-closed.
5. Money/event/trip callbacks, repeated score reads and standard distance
   terms cannot duplicate the Taxi fare; non-finite inputs/results fail.
6. PT and Car runtime/scoring stay inactive and unreferenced by the scoring
   component registry.
7. No economic policy, fare assumption, ASC/calibration, monetary utility,
   demand, capacity, supply, plan, input or runtime-configuration change.
8. Maven compile, focused tests, complete tests, native-routing tests and
   structured validation pass.
9. Worklogs are append-only; `city.yaml` and `run_manifest.json` are unchanged.
10. `git diff --check`, final cleanliness, ref equality and protected refs pass.

## Evidence

- Integrated composition:
  [`../../../data/transport_costs/hongkong/integrated_multimodal_cost_source_interface_manifest_v1.json`](../../../data/transport_costs/hongkong/integrated_multimodal_cost_source_interface_manifest_v1.json)
  field `canonical_scoring_composition`.
- Taxi equivalence and command record:
  [`../../../data/taxi/hongkong/processed/taxi_scoring_composition_stage5_validation_v1/stage5_taxi_scoring_composition_validation.json`](../../../data/taxi/hongkong/processed/taxi_scoring_composition_stage5_validation_v1/stage5_taxi_scoring_composition_validation.json).
- Exact pushed SHA and ref checks: compact Executor handoff.

## Diagnostics

Record test duration, warnings, component counts and bounded test-driven
corrections. A diagnostic fails the stage only when it breaks a hard gate.

## Stop condition

After one focused push, INT-EXECUTOR hands the exact SHA to INT-REVIEWER and
INT-SUPERVISOR and stops. No Runner, MATSim/server run, Stage 6+, or master
merge is authorized.
