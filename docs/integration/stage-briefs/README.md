# Integration stage briefs

## Prospective canonical governance

All valid prospective governance rules are normalized into the self-contained
[`CONTROL_PROTOCOL_09_LEAN_STAGE_END_REVIEW.md`](CONTROL_PROTOCOL_09_LEAN_STAGE_END_REVIEW.md).
Together with [`../INTEGRATION_POLICY.md`](../INTEGRATION_POLICY.md),
[`../CURRENT_STAGE.md`](../CURRENT_STAGE.md),
[`../../../agent-lanes.md`](../../../agent-lanes.md), and the Supervisor exact
execution contract, it is the only prospective control-plane source.

Current candidate:

- [`CONTROL_PROTOCOL_09_LEAN_STAGE_END_REVIEW.md`](CONTROL_PROTOCOL_09_LEAN_STAGE_END_REVIEW.md) —
  task `CONTROL-PROTOCOL-09-CANONICAL-CONSOLIDATION-AND-FAILURE-OWNERSHIP`,
  exact input `16398c7883945bc82cdf521b727c6ef502273e79`, ready for one
  Supervisor-dispatched stage-end review. Runner, Stage 9 execution, and Stage
  10 or later remain unauthorized.

Active substantive stage:

- [`STAGE_10_DETERMINISTIC_MULTIMODAL_COST_COVERAGE.md`](STAGE_10_DETERMINISTIC_MULTIMODAL_COST_COVERAGE.md) —
  task `STAGE10-DETERMINISTIC-MULTIMODAL-COST-COVERAGE`, exact input
  `48686c03f46372e4aed2bc9bd1bdeb1796a34fbe`; test-only directed Taxi/PT/Car
  coverage. Runner and Stage 11 remain unauthorized.

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
