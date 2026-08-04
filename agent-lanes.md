# Hong Kong multimodal-cost integration agent lanes

## Current lane registry

This is the current registry for the persistent Hong Kong MATSim multimodal-cost
integration lanes. When a lane session is replaced, update only its
`current_session_id` here and append the old and new IDs to that lane's worklog
session history. Never delete earlier worklog history.

| lane | purpose | current_session_id | write_scope | worklog |
|---|---|---|---|---|
| INT-SUPERVISOR | Overall architecture, stage planning, gates and escalation | 019fb38e-0963-7f01-9461-ba84c9aa6378 | Read-only; no repository or run-directory writes | docs/agent-worklogs/integration-supervisor.md |
| INT-EXECUTOR | Sole integration worktree writer; merge, implementation, local validation, commit and push | 019fb38f-c992-74f1-9894-c6009784a697 | F:\Matsim\worktrees\hk-cost-integration on integration/hk-multimodal-cost-v1 only | docs/agent-worklogs/integration-executor.md |
| INT-RUNNER | Exact-SHA server runs, smoke, calibration, 50 iterations and evidence capture | 019fb38e-919f-7d92-a376-af88b49d5900 | No Git writes; append-only run and evidence directories only | docs/agent-worklogs/integration-runner.md |
| INT-REVIEWER | Independent pushed-commit and run-evidence review | 019fb38f-1c8c-7d62-9dc4-7ea5d0b5192e | Read-only; no repository or run-directory writes | docs/agent-worklogs/integration-reviewer.md |

## Canonical control-plane sources

Future cross-session messages carry only the active-stage delta. Stable rules
and evidence are read from these canonical paths:

- [Integration policy](docs/integration/INTEGRATION_POLICY.md)
- [Lean delta-only review protocol and template](docs/integration/stage-briefs/CONTROL_PROTOCOL_02_LEAN_DELTA_REVIEW.md)
- [Blocker-to-repair transition protocol](docs/integration/stage-briefs/CONTROL_PROTOCOL_03_BLOCKER_TO_REPAIR.md)
- [Protocol 02/03 schema consistency](docs/integration/stage-briefs/CONTROL_PROTOCOL_04_PROTOCOL_02_03_SCHEMA_CONSISTENCY.md)
- [Atomic gate transition and non-recursive closure](docs/integration/stage-briefs/CONTROL_PROTOCOL_05_ATOMIC_GATE_TRANSITION.md)
- [Post-failure diagnosis and automatic dispatch](docs/integration/stage-briefs/CONTROL_PROTOCOL_06_POST_FAILURE_DIAGNOSIS_AUTO_DISPATCH.md)
- [Diagnosis confidence and resource budget](docs/integration/stage-briefs/CONTROL_PROTOCOL_07_DIAGNOSIS_CONFIDENCE_AND_BUDGET.md)
- [Execution contract and Supervisor server-read verification](docs/integration/stage-briefs/CONTROL_PROTOCOL_08_EXECUTION_CONTRACT_AND_SUPERVISOR_SERVER_READ.md)
- [Current stage](docs/integration/CURRENT_STAGE.md)
- [Hub-and-spoke messaging protocol](docs/integration/stage-briefs/CONTROL_PROTOCOL_01_HUB_AND_SPOKE.md)
- [Stage 4A lean-protocol brief](docs/integration/stage-briefs/STAGE_04A_LEAN_PROTOCOL_MIGRATION.md)
- [Stage-brief index](docs/integration/stage-briefs/README.md)

The policy defines the compact command/worklog schemas, lane-specific output
budgets, evidence-by-reference rules, canonical delta-only review protocol,
mandatory blocker-to-repair transition and their synchronized Reviewer/state
schemas, atomic gate transition and non-recursive closure invariants, plus the
post-failure read-only diagnosis and automatic technical-dispatch rules. The
confidence gates and default resource budget make those diagnoses
machine-checkable and bounded. Protocol 08 defines complete Runner execution
contracts, pre-build contract-preserving corrections, failure routing, and a
bounded read-only Supervisor evidence-verification policy. That policy does
not grant actual SSH/platform capability and does not change any lane's write
scope. The templates apply those rules without changing lane authority. The
current-stage file identifies the latest valid Supervisor gate and active or
explicit idle state.
These links do not change any lane identity, authority or write scope below.

## Authority and evidence boundary

- `INT-EXECUTOR` is the sole writer for
  `F:\Matsim\worktrees\hk-cost-integration` and
  `integration/hk-multimodal-cost-v1`.
- `INT-SUPERVISOR` and `INT-REVIEWER` are read-only. `INT-RUNNER` performs no
  Git writes and may write only to new, append-only run and evidence
  directories after explicit Supervisor authorization.
- Only `INT-SUPERVISOR` aggregates lane messages, dispatches work and reviews,
  decides gates, authorizes runs, and advances stages. Executor, Reviewer and
  Runner send their complete handoffs only to Supervisor; they do not direct
  or authorize one another. A non-Supervisor message never authorizes a write,
  rework, run, review dispatch, or next stage.
- Real-time cross-session messages carry handoffs. Git worklogs are append-only
  audit records and are not notifications or execution authority. `BLOCKED`
  does not authorize repair, and `PASS` does not authorize the next stage.
- Protected `master` and feature branches must not be modified or force-pushed.
  No other worktree may be modified. Git merges, rather than manual file copies
  from another worktree, are the only allowed feature-integration mechanism.

## Locked Stage 0 identity

```text
baseline:
  a3d6445cfd79a74b6fd6bd01e547d7df8055a64d
feature/hk-taxi-behavioral-pilot-v1:
  aa0d4794fa3af8458c906db1614fd418893e4bd4
feature/hk-pt-fare-model-v1:
  0b0ce90375b9e3d0c055fa46c5a3b96bfc3a5103
feature/hk-car-cost-model-v1:
  fc906efd3afb98e027cc6cca44060dec9e32aa46
merge order:
  Taxi -> PT -> Car
```

Stage 0 is control-plane initialization only. It authorizes no Taxi, PT, or
Car merge and no Stage 1 implementation, test, or run.

## Gate classifications

### Hard Gate

A Hard Gate includes compilation or mandatory-test failure; unexpected input
hash changes; duplicate charging; unexplained missing charges; Taxi-to-`ride`
conversion; broken `mode` or `routingMode`; unresolved values filled with
zero; fixed ownership charged per leg; non-finite scores; incomplete required
iterations; wrong commit SHA or inputs; a non-unique interface; or a protected
branch change.

### Diagnostic

Diagnostics include PrepareForSim duration, peak memory, PT segment counts,
Taxi route changes, cost means, mode share, fallback use, stuck conditions
that do not make outputs incomplete, warnings, and speed. A diagnostic does
not automatically fail a stage unless it demonstrably defeats the stage
objective and the reason is recorded.

### Trend

Trends include mode share, stuck counts, scores, cost distributions,
replanning, and iteration duration across iterations or experiments.

## Run-identity and historical-evidence rules

- A failed run must not be repeated under an identical run identity with no
  relevant change merely by selecting a new directory. A rerun requires a new
  commit, config, input, environment repair, verifiable hypothesis, or a
  demonstrated one-time infrastructure failure. Record the change, its
  mechanism, and the metric that will verify it.
- Every server attempt uses a new directory. Existing server files and prior
  attempts are never overwritten or deleted.
- Historical commits, documents, guards, and failed-run evidence remain
  available and are labelled historical, legacy, or superseded as applicable.
  A historical guard does not control a new canonical contract. Replacing a
  guard requires a recorded reason and equivalent protection for the new
  architecture.

## Standard stage loop

```text
Supervisor Brief
  -> Executor implement/test/commit/push
  -> Executor sends exact SHA/evidence/handoff to Supervisor
  -> Supervisor dispatches exact-SHA review to Reviewer
  -> Reviewer sends verdict/evidence/blockers/handoff to Supervisor
  -> if BLOCKED: Supervisor decides and issues bounded Executor rework
  -> if PASS and a run is needed: Supervisor authorizes Runner
  -> Runner executes exact SHA and sends Evidence Handoff to Supervisor
  -> Supervisor authorizes any evidence commit to Executor
  -> Executor commits/pushes and reports only to Supervisor
  -> Supervisor dispatches any required re-review
  -> Supervisor advances the stage
```

No lane creates a commit merely to record a verdict that is already under
review. Transferred handoffs are appended during the next otherwise-authorized
write, preventing recursive log-only review cycles.

## Model-policy escalation boundary

Escalate to the user before changing economic or behavioral semantics,
monetary utility, ASC range or target, non-random missing-data treatment or
new imputation, the economic meaning of `car monetaryDistanceRate`, mode
definitions, capacity or demand scale, unsupported fare or parking
assumptions, destructive Git operations, a `master` merge, or choosing between
two materially different research interpretations.

Ordinary merge conflicts, class refactors, Guice bindings, scoring factories,
tests, compilation, server paths, performance, logging, validation formatting,
duplicate-charge prevention, and other non-model implementation defects do not
require user escalation.

## Required stage sequence

The integration must pass these stages in order:

0. control-plane initialization;
1. Taxi runtime;
2. canonical PT offline interface;
3. canonical Car offline interface, using only
   `unified_marginal_cost_interface_v1` with fixed ownership excluded;
4. completeness audit;
5. combined scoring with Taxi migrated first;
6. PT itinerary and stuck resolution;
7. PT runtime;
8. Car runtime, introducing fuel/electricity, confirmed toll, and resolved
   parking independently;
9. joint short smoke;
10. 5- and 10-iteration runs;
11. joint calibration;
12. frozen 50-iteration release candidate;
13. post-run acceptance.

No merge to `master` is allowed without explicit user authorization.

## Accepted Taxi boundary entering integration

Independent Taxi smoke is no longer a merge prerequisite. Native routing is
technically accepted: all 37,286 Taxi legs retain
`mode=taxi,routingMode=taxi`, Taxi-to-`ride` is zero, standard PrepareForSim
completes, and all 37,286 prepared routes have calculable fares. The historical
two-iteration run remains incomplete: iteration 0 recorded 35,088 departures,
35,087 arrivals, one Taxi stuck, and 2,198 later Taxi legs blocked mainly by
upstream PT/walk execution. `ASC=-9` is a placeholder, not a calibration
result. No explicit Taxi fleet is authorized.
