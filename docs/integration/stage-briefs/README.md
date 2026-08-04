# Integration stage briefs

## Prospective canonical governance

All valid prospective governance rules are normalized into the self-contained
[`CONTROL_PROTOCOL_09_LEAN_STAGE_END_REVIEW.md`](CONTROL_PROTOCOL_09_LEAN_STAGE_END_REVIEW.md).
Together with [`../INTEGRATION_POLICY.md`](../INTEGRATION_POLICY.md),
[`../CURRENT_STAGE.md`](../CURRENT_STAGE.md),
[`../../../agent-lanes.md`](../../../agent-lanes.md), and the Supervisor exact
execution contract, it is the only prospective control-plane source.

Active substantive stage:

- [`STAGE_11_JOINT_STABILITY_5_10_ITERATIONS.md`](STAGE_11_JOINT_STABILITY_5_10_ITERATIONS.md) —
  task `STAGE11-JOINT-STABILITY-5-10-ITERATIONS`, exact input/review base
  `3ed98c4b8b34491a3c6f9fdf3517812323baed76`; control-plane candidate for
  separate 5- and 10-iteration joint stability identities. Runner, server
  execution, calibration, and Stage 12 or later remain unauthorized.

Most recently closed stage:

- [`STAGE_10_DETERMINISTIC_MULTIMODAL_COST_COVERAGE.md`](STAGE_10_DETERMINISTIC_MULTIMODAL_COST_COVERAGE.md) —
  `PASS_CLOSED` at reviewed output
  `3ed98c4b8b34491a3c6f9fdf3517812323baed76`; the directed fixture directly
  observed Taxi/PT/Car costs and exactly-once negative tests. It remains a
  component-level proof, not a production server run.

## Deprecated noncanonical protocols

Protocols 05–08 have status `DEPRECATED_NON_CANONICAL`, prospective authority
`NONE`, and canonical replacement Protocol 09. They remain historical audit and
rationale only. Do not use them for dispatch, state, review cadence, diagnosis
ownership, execution, or authorization.

- [`CONTROL_PROTOCOL_05_ATOMIC_GATE_TRANSITION.md`](CONTROL_PROTOCOL_05_ATOMIC_GATE_TRANSITION.md)
- [`CONTROL_PROTOCOL_06_POST_FAILURE_DIAGNOSIS_AUTO_DISPATCH.md`](CONTROL_PROTOCOL_06_POST_FAILURE_DIAGNOSIS_AUTO_DISPATCH.md)
- [`CONTROL_PROTOCOL_07_DIAGNOSIS_CONFIDENCE_AND_BUDGET.md`](CONTROL_PROTOCOL_07_DIAGNOSIS_CONFIDENCE_AND_BUDGET.md)
- [`CONTROL_PROTOCOL_08_EXECUTION_CONTRACT_AND_SUPERVISOR_SERVER_READ.md`](CONTROL_PROTOCOL_08_EXECUTION_CONTRACT_AND_SUPERVISOR_SERVER_READ.md)

Protocols 01–04 and Stage 4A also remain historical audit evidence; no earlier
brief has prospective authority after Protocol 09 consolidation.

## Historical stage evidence

Closed, blocked, and superseded briefs remain immutable evidence. Important
Stage 9 records include:

- [`STAGE_09_RUN8_EVIDENCE_REVIEW_AND_CLOSURE.md`](STAGE_09_RUN8_EVIDENCE_REVIEW_AND_CLOSURE.md)
- [`STAGE_09_JOINT_SHORT_SMOKE.md`](STAGE_09_JOINT_SHORT_SMOKE.md)
- [`STAGE_09_REPAIR_ARTIFACT_DISCOVERY_010.md`](STAGE_09_REPAIR_ARTIFACT_DISCOVERY_010.md)
- [`STAGE_09_REPAIR_MODE_PRESERVATION_007.md`](STAGE_09_REPAIR_MODE_PRESERVATION_007.md)
- [`STAGE_09_REPAIR_RUNNER_WORKDIR_GUARD_006.md`](STAGE_09_REPAIR_RUNNER_WORKDIR_GUARD_006.md)
- [`STAGE_09_REPAIR_SHADED_JAR_DEPENDENCY_CLOSURE_005.md`](STAGE_09_REPAIR_SHADED_JAR_DEPENDENCY_CLOSURE_005.md)
- [`STAGE_09_REPAIR_JDK_LEGAL_SYMLINK_004.md`](STAGE_09_REPAIR_JDK_LEGAL_SYMLINK_004.md)
- [`STAGE_09_REPAIR_JDK_ARCHIVE_MEMBERS_001.md`](STAGE_09_REPAIR_JDK_ARCHIVE_MEMBERS_001.md)

Earlier closed integration stages remain available in this directory and Git
history. Naming remains `STAGE_<ID>_<SHORT_NAME>.md`; a new substantive stage
brief supplies only its delta against Protocol 09 and updates `CURRENT_STAGE.md`
when authorized. Historical briefs are not rewritten to create new authority.
