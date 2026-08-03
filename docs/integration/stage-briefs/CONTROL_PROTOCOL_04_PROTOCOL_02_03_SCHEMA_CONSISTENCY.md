# CONTROL-PROTOCOL-04 — Protocol 02/03 schema consistency

| Field | Value |
|---|---|
| Task ID | `CONTROL-PROTOCOL-04_PROTOCOL_02_03_SCHEMA_CONSISTENCY` |
| Exact input | `fb06546f806819020ad40e751dad26cabfa718af` |
| Owner | `INT-EXECUTOR` only |
| Reviewer | read-only exact-SHA review |
| Runner | unauthorized |

## Objective

Synchronize CONTROL-PROTOCOL-02 Reviewer output with CONTROL-PROTOCOL-03
blocker transitions and close five governance gaps without instantiating a
blocker, repair, run or Stage 9 change.

## Canonical corrections

1. Reviewer output is a union of `next_action_summary` and nullable
   `required_transition`. Ordinary PASS/non-Protocol-03 results set the latter
   to null. Technical Protocol-03 BLOCKED results require the structured
   transition, which controls dispatch and must not contradict the summary.
2. `DIAGNOSIS_DISPATCHED` is a first-class state. Unknown cause follows
   `OPEN -> DIAGNOSIS_DISPATCHED`; diagnosis cannot rerun and Supervisor must
   create a repair before `REPAIR_DISPATCHED`.
3. `MISSING_REPAIR_DISPATCH` is exactly once through persisted `emitted`,
   `emitted_at`, and `escalation_id`; identical repeats deduplicate.
4. Supervisor creates/confirms canonical blocker IDs at the first accepted
   BLOCKED. Normalized non-substantive changes reuse the ID; substantively new
   cause/failure classes receive a new ID.
5. Executor push remains `REPAIR_DISPATCHED`. Supervisor verifies exact
   SHA/parent and dispatches Reviewer before setting `UNDER_REVIEW`; only
   Supervisor sets `CLOSED`.

## Canonical sources

- Reviewer union:
  [`CONTROL_PROTOCOL_02_LEAN_DELTA_REVIEW.md`](CONTROL_PROTOCOL_02_LEAN_DELTA_REVIEW.md)
- Blocker record, state machine and complete non-authorizing example:
  [`CONTROL_PROTOCOL_03_BLOCKER_TO_REPAIR.md`](CONTROL_PROTOCOL_03_BLOCKER_TO_REPAIR.md)
- Stable rules:
  [`INTEGRATION_POLICY.md`](../INTEGRATION_POLICY.md)

## Hard gates

- exact input/parent/output and protected refs;
- governance-only allowlisted paths;
- no contradictory text action and structured transition;
- diagnosis and repair transitions are explicit;
- exactly-once escalation fields are persisted;
- canonical blocker creation/dedup authority is Supervisor-only;
- `UNDER_REVIEW` and `CLOSED` transitions are Supervisor-only;
- historical worklogs remain prefix-identical with append-only additions;
- `CURRENT_STAGE.md`, Stage 9 and Runner authorization remain unchanged;
- links, `git diff --check`, conflict markers and final ref/clean checks pass.

## Stop conditions

Stop on any runtime/model/config/input/bundle/server change, blocker/JDK repair
instantiation, Stage 9 or Runner authorization, historical worklog rewrite,
protected-ref change or schema ambiguity.

## Next action

Executor pushes one focused governance commit and reports only to Supervisor.
Supervisor may dispatch read-only exact-SHA review. This brief does not contact
Reviewer, create a repair task, or authorize Runner or Stage 9.
