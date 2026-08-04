# Stage 9 run8 evidence review and closure contract

## Control identity

- Task ID: `STAGE9-REPAIR-RUN8-EVIDENCE-BINDING-012`
- Blocker ID: `STAGE9-RUN8-EVIDENCE-UNVERIFIED-001`
- Exact input SHA: `b32bef0398ebe44187c088c22e2b5276fa260ac0`
- Repair owner/writer: `INT-EXECUTOR`
- Gate owner: `INT-SUPERVISOR`
- Runner authorized: `false`
- Stage 9 execution authorized: `false`
- Stage 10 or later authorized: `false`

This is a bounded evidence/governance repair. It does not rerun or modify
run8. Stable evidence and review rules remain in
[`INTEGRATION_POLICY.md`](../INTEGRATION_POLICY.md), and canonical state is in
[`CURRENT_STAGE.md`](../CURRENT_STAGE.md).

## Preserved run identity

The binding applies only to this immutable identity:

| field | value |
|---|---|
| source SHA | `4c61a02e562830e248ce7178132e8609f53decde` |
| source Git tree | `125a329d0d9a9414b89a90dc89a1d81530f2fe30` |
| staging root | `/mnt/DiskM/by/hk_stage9_4c61a0_staging8` |
| release root | `/mnt/DiskM/by/hk_multimodal_cost_4c61a0_stage9_release8` |
| run identity | `smoke_qsim_v1_4c61a0_run8` |

No new staging, release or run identity is created. The run process exited
zero; `BLOCKED_SUPERSEDED_BY_REPAIR` applies to the incomplete evidence-review
task, not to a claim that MATSim returned nonzero.

## Evidence binding

Runner diagnosis 011 is the immutable server-side attestation:

- path:
  `/mnt/DiskM/by/hk_stage9_4c61a0_staging8/evidence/diagnosis_run8_evidence_verification_011/diagnosis.json`
- SHA256:
  `a72234de370376a1c7b3554f68b96e950f233d319889808afd86c2ff78203e46`

The compact pushed binding is
[`stage9_run8_evidence_binding.json`](../../../data/transport_costs/hongkong/integration_stage9_run8_evidence_v1/stage9_run8_evidence_binding.json).
It records source labels, exact identity, transferred checks and limitations;
it does not copy or fabricate raw server logs. Exact digest strings not
included in the Supervisor-transferred facts remain in the diagnosis JSON and
are bound through its path and SHA rather than guessed.

## Hard Gate evidence

The read-only diagnosis attests that source/tree, the seven-file locked input
pack, root Shade JAR, bundle, release and approved JDK hashes match. The
approved JDK archive SHA256 remains
`69264a7a211bf5029830d07bc3370f879769d62ebc5b5488e90c9343a2da0e1f`;
the seven exact v2/Ferry Core hashes are recorded in the structured binding.

Reported execution facts are:

- release `SHA256SUMS`: 420 OK, zero failed;
- process exit code: 0;
- effective `lastIteration`: 0;
- population: 7,716;
- events: 48,287,273;
- non-finite score count: 0;
- Java: 25.0.3; MATSim: 2026.0.

These are pending independent review. This brief does not declare Stage 9
PASS or close the evidence blocker.

## Diagnostics and coverage limitations

`stuckAndAbort=74` is Diagnostic, not an automatic Hard Gate: 11 Hong Kong
persons, 11 bus entities and 52 GMB entities, all at 108,000 seconds, with no
cause attribute. Reviewer may escalate it only by tying it to a named Stage 9
hard gate.

The run subset contains zero Taxi legs, zero `routingMode=taxi` legs, 47
persons with `modeDetail=taxi`, and zero money/cost events. Taxi route fare and
exactly-once charging were therefore not exercised. This limitation prevents
run8 alone from proving Taxi-specific coverage or overall Stage 9 PASS; it is
not silently reclassified as successful Taxi evidence.

## Blocker transition and next gate

`STAGE9-RUN8-EVIDENCE-UNVERIFIED-001` transitions from `OPEN` to
`REPAIR_DISPATCHED`; the former evidence-review task becomes
`BLOCKED_SUPERSEDED_BY_REPAIR`. This commit supplies the repair and remains
`PENDING_INDEPENDENT_REVIEW`.

Protocol 08 is consumed as `PASS_CLOSED`. Protocol 07 remains `PASS_CLOSED`.
Artifact-discovery repair 010 remains pending its previously recorded gate,
and blocker `STAGE9-RUNNER-SHADE-CLOSURE-002` remains `REPAIR_DISPATCHED`;
neither is closed by this task.

Supervisor verifies the pushed SHA and dispatches one read-only review. No
verdict-only or closure-only follow-up is planned. Runner, rerun, Stage 9
execution and Stage 10 or later remain unauthorized.

## Stop conditions

Stop on identity mismatch, unsupported hash inference, raw-log fabrication,
server access or mutation, rerun request, runtime/model/config/input change,
protected-ref change, historical-worklog rewrite or any Stage 10 action.
