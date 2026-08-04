# Stage 9 run8 final evidence audit and closure

## Control identity

- Task ID: `STAGE9-RUN8-EVIDENCE-REVIEW-AND-CLOSURE`
- Blocker ID: `STAGE9-RUN8-EVIDENCE-UNVERIFIED-001`
- Exact input SHA: `101afd5beb6d1351448aea406608119d2f4ba869`
- Reviewed evidence-binding parent: `b32bef0398ebe44187c088c22e2b5276fa260ac0`
- Reviewer verdict for exact input: `PASS`
- Repair owner/writer: `INT-EXECUTOR`
- Gate owner: `INT-SUPERVISOR`
- Runner authorized: `false`
- Stage 9 execution authorized: `false`
- Stage 10 or later authorized: `false`

This is the final substantive evidence audit and one-time atomic closure. It
consumes the exact-SHA Reviewer PASS, synchronizes the final control state and
does not rerun or modify run8. Stable evidence and review rules remain in
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
zero. The former `BLOCKED_SUPERSEDED_BY_REPAIR` state applied to the incomplete
evidence-review task, not to a claim that MATSim returned nonzero; the reviewed
binding now closes that evidence blocker.

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

Reviewer returned `PASS` for exact pushed binding SHA
`101afd5beb6d1351448aea406608119d2f4ba869`, whose parent is
`b32bef0398ebe44187c088c22e2b5276fa260ac0`. The final audit consumes that
verdict and records Stage 9 as `PASS_CLOSED`.

## Diagnostics and coverage limitations

`stuckAndAbort=74` is Diagnostic, not an automatic Hard Gate: 11 Hong Kong
persons, 11 bus entities and 52 GMB entities, all at 108,000 seconds, with no
cause attribute. Reviewer may escalate it only by tying it to a named Stage 9
hard gate.

The run subset contains zero Taxi legs, zero `routingMode=taxi` legs, 47
persons with `modeDetail=taxi`, and zero money/cost events. Taxi route fare and
exactly-once charging were therefore not exercised. The accepted Stage 9
technical closure does not turn that absence into Taxi behavioral evidence;
no Taxi behavioral-coverage claim is made beyond this run.

## Blocker transition and next gate

The final synchronized state is:

| record | exact reviewed identity | final status |
|---|---|---|
| Protocol 07 | `e58861e4f79eb5aa18c8ac286d0173987bcef237` | `PASS_CLOSED` |
| artifact-discovery repair 010 | `4c61a02e562830e248ce7178132e8609f53decde` | `PASS_CLOSED` |
| blocker `STAGE9-RUNNER-SHADE-CLOSURE-002` | repair 010 | `CLOSED` |
| Protocol 08 | `b32bef0398ebe44187c088c22e2b5276fa260ac0` | `PASS_CLOSED` |
| run8 evidence binding | `101afd5beb6d1351448aea406608119d2f4ba869` | Reviewer `PASS` |
| Stage 9 joint short smoke | `smoke_qsim_v1_4c61a0_run8` | `PASS_CLOSED` |
| blocker `STAGE9-RUN8-EVIDENCE-UNVERIFIED-001` | reviewed binding | `CLOSED` |

`active_task` and `active_blocker` are null. The next state is
`AWAITING_USER_OR_SUPERVISOR_STAGE10_DECISION`. Runner, rerun, future Stage 9
execution and Stage 10 or later remain unauthorized. No verdict-only or
closure-only follow-up commit is permitted.

## Stop conditions

This closure stops after one pushed atomic-transition commit. Stop on identity
mismatch, unsupported hash inference, raw-log fabrication, server access or
mutation, rerun request, runtime/model/config/input change, protected-ref
change, historical-worklog rewrite or any Stage 10 action.
