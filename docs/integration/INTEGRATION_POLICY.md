# Hong Kong multimodal-cost integration policy

This file is the canonical stable protocol for the persistent Hong Kong
multimodal-cost integration lanes. Lane identities and write scopes remain
canonical in [`agent-lanes.md`](../../agent-lanes.md). The active stage delta
is canonical in [`CURRENT_STAGE.md`](CURRENT_STAGE.md).

## Lean cross-session protocol

1. Stable rules are read from repository files. They are not repeated in every
   prompt, stage command, worklog entry, or handoff.
2. A cross-session command contains only: stage ID, exact input SHA, objective,
   allowed scope, hard gates, evidence requirements, stop condition, and
   handoff target.
3. Canonical evidence is referenced by repository path and field, not copied
   into chat or worklogs. A reference uses `path#field` for structured files
   and `path#section` for Markdown. The exact reviewed commit anchors all
   references.
4. A routine lane output contains at most one decision, five findings, five
   diagnostics, one next action, and one compact handoff.
5. Diagnostics do not automatically become hard failures. Escalation requires
   evidence that a diagnostic defeats a named hard gate, with the reason
   recorded.
6. An identical failed run identity is not repeated without a relevant commit,
   config, input or environment change, a testable hypothesis, or evidence of
   a one-time infrastructure failure.
7. Historical guards and evidence remain preserved, but they do not control a
   superseding canonical architecture. The replacement reason and equivalent
   protection must be referenced.
8. Prompts define objectives and boundaries without prescribing every
   implementation detail. The authorized owner chooses ordinary implementation
   details within those boundaries.
9. Each lane stops when its authorized objective is complete or responsibility
   passes to another lane.

## Hub-and-spoke lane messaging protocol

`INT-SUPERVISOR` is the sole real-time message aggregation, formal dispatch,
gate-decision, escalation and stage-progression center.

- Executor accepts execution authority only from Supervisor. After an
  implementation, validation, commit and push, Executor sends the complete
  result, exact SHA, evidence references and worklog handoff only to
  Supervisor. Executor never requests or directs Reviewer.
- Reviewer accepts review tasks only from Supervisor and sends its verdict,
  evidence, blockers, rework findings and handoff only to Supervisor. Reviewer
  never directs Executor and never authorizes a run or next stage.
- Runner accepts runs only from a Supervisor instruction naming an exact
  pushed SHA and execution specification. Runner sends run identity, evidence
  and handoff only to Supervisor and never directs Executor or Reviewer.
- A direct message from any non-Supervisor lane is evidence, not authority.
  Executor must not write, rework or run in response; it reports the message to
  Supervisor and waits for a formal decision.
- Supervisor sends one consolidated instruction containing the decision,
  allowed action, boundary, stop condition, and any original handoffs that
  must be archived during the authorized write.

Real-time cross-session messages are the handoff mechanism. Git worklogs are
append-only audit records: they preserve transferred handoffs but do not notify
another lane, dispatch a review, or authorize execution. A `BLOCKED` verdict
does not authorize repair, and a `PASS` verdict does not authorize progression.

No commit is created solely to archive a verdict for the commit currently
being reviewed. Supervisor transfers it into the next substantive or
control-plane write authorization. This avoids recursive log-only review
cycles while preserving the history.

## Lean delta-only review protocol

This is the canonical prospective review protocol. The reusable compact
submission and verdict shape is
[`stage-briefs/CONTROL_PROTOCOL_02_LEAN_DELTA_REVIEW.md`](stage-briefs/CONTROL_PROTOCOL_02_LEAN_DELTA_REVIEW.md).

1. Reviewer reviews only the current Stage Brief delta at the exact pushed
   output SHA, compared with its declared exact input SHA and parent.
2. Immutable evidence already reviewed at a prior exact SHA is cited by
   `path#field` or `path#section`; it is neither recopied nor revalidated unless
   the current delta touches that evidence or a named dependency.
3. Every review separates Hard Gate evidence, Diagnostics and Trends.
   Diagnostics and Trends do not fail a stage unless evidence ties them to a
   named hard gate.
4. Machine results live in committed JSON/CSV or durable server evidence.
   Prompts, reviews and worklogs cite path plus field and do not paste full
   command output, logs, manifests or inventories.
5. Hard gates cover, as applicable: exact output/input/parent and ref identity;
   allowlisted path scope; stage-specific semantic invariants; required tests
   and validators; protected refs and inputs; and clean diff, index and working
   tree.
6. Artifact and deployment reviews prove producer-to-consumer dependency
   closure, not merely archive existence. Every executable, path and version
   required by a launcher must be present in the released artifact and checked
   by a fail-closed preflight before execution authorization.
7. Unchanged historical Taxi/PT/Car evidence, prior-stage history and untouched
   guards are not re-reviewed. Superseded guards remain preserved and
   non-controlling under the canonical architecture.
8. Routine Reviewer output contains one decision, at most five findings, at
   most five diagnostics, one `next_action_summary`, one nullable
   `required_transition`, and one compact WORKLOG HANDOFF with evidence
   references.
9. Reviewer output is one unambiguous union. Ordinary `PASS` and results outside
   CONTROL-PROTOCOL-03 use a short `next_action_summary` with
   `required_transition: null`. A technical `BLOCKED` governed by
   CONTROL-PROTOCOL-03 must use its structured `required_transition`; that
   structure overrides the summary for dispatch semantics, and the two fields
   must not contradict each other.
10. A `BLOCKED` result records the failing identity, the changed hypothesis or
   relevant change required before retry, and the next authorized owner. An
   identical failed run/config/input/command/runtime identity is never repeated.
11. Repeated heartbeat snapshots with the same blocker are deduplicated. They
    neither redispatch nor rereport the same action.
12. Prompts specify objective, boundaries, hard gates, evidence and stop
    conditions without prescribing ordinary implementation details.
13. Lane authority is unchanged: Executor is the integration writer, Reviewer
    is read-only, Runner is inactive unless Supervisor explicitly authorizes an
    exact execution, and Supervisor alone aggregates messages and gates stages.

## Blocker-to-repair state transition

CONTROL-PROTOCOL-03 extends the lean delta-only review protocol. Its canonical
schemas and worked example are in
[`stage-briefs/CONTROL_PROTOCOL_03_BLOCKER_TO_REPAIR.md`](stage-briefs/CONTROL_PROTOCOL_03_BLOCKER_TO_REPAIR.md).

1. Supervisor creates or confirms the canonical `blocker_id` when it accepts
   the first `BLOCKED` result. The format is
   `STAGE-DOMAIN-ROOT_CAUSE-SEQUENCE`: uppercase; fixed token order; spaces,
   slashes and underscores normalized to one hyphen; repeated separators
   collapsed; and sequence zero-padded. The active-stage blocker record is
   authoritative.
2. Every technical blocker records `blocker_id`, `status`, `failure_identity`,
   `root_cause`, `changed_hypothesis_required_for_retry`, `diagnosis_task_id`,
   `repair_task_id`, `repair_owner`, `replacement_identity_required`,
   `superseded_run_identity`, and persisted `missing_dispatch_escalation`
   fields `emitted`, `emitted_at`, and `escalation_id`.
3. Supported blocker states are `OPEN`, `DIAGNOSIS_DISPATCHED`,
   `REPAIR_DISPATCHED`, `UNDER_REVIEW`, `CLOSED`, and `ESCALATED_TO_USER`.
   State changes are append-only audit events; earlier records are not
   rewritten.
4. For a technical `BLOCKED` result with a known root cause and an executable,
   verifiable repair, Supervisor's next effective action is
   `CREATE_REPAIR_STAGE`. If the root cause is unknown, the next effective
   action is `CREATE_DIAGNOSIS_STAGE`. Repeating the blocker heartbeat is not a
   valid next action.
5. Unknown cause transitions `OPEN -> DIAGNOSIS_DISPATCHED`. A diagnosis result
   never directly authorizes a rerun; Supervisor must issue a repair stage,
   producing `DIAGNOSIS_DISPATCHED -> REPAIR_DISPATCHED`. A known cause may
   transition directly `OPEN -> REPAIR_DISPATCHED`.
6. A diagnosis or repair dispatch changes the prior stage to
   `BLOCKED_SUPERSEDED_BY_DIAGNOSIS` or `BLOCKED_SUPERSEDED_BY_REPAIR` and makes
   the new bounded task active.
7. The first repeated `OPEN` heartbeat with no diagnosis/repair task emits one
   `MISSING_REPAIR_DISPATCH` and atomically persists
   `missing_dispatch_escalation.emitted: true`, `emitted_at`, and a stable
   `escalation_id` in the append-only worklog. Further identical heartbeats are
   deduplicated. Only a substantive root-cause or failure-identity change, or a
   formal dispatch state change, permits a new audit event; dispatch does not
   reset the exactly-once escalation fields.
8. Heartbeats deduplicate by canonical `blocker_id` plus failure identity.
   Case, separator, token-order, timestamp, directory, log-path, or attempt
   differences are non-substantive and reuse the ID. A new ID is created only
   for a substantively different root-cause class or failure identity. A
   diagnosis refining `UNKNOWN` within the same observed causal class keeps the
   existing ID. A repaired replacement identity remains attached to the same
   blocker unless a new attempt fails with a substantively different cause.
9. For technical `BLOCKED`, Reviewer sets the CONTROL-PROTOCOL-02
   `required_transition` fields `action`, `blocker_id`, `owner`,
   `repair_owner`, and `runner_authorized`. It reports PASS/BLOCKED and evidence
   only to Supervisor; the transition request is not execution authority.
10. A repair-stage brief supplies a new `task_id`, exact input SHA, allowed
   paths, objective, hard gates, evidence, stop conditions, replacement run
   identity requirements, and `runner_authorized: false`. Only a later,
   separate Supervisor dispatch may authorize Runner.
11. Executor push does not set `UNDER_REVIEW`; the blocker remains
    `REPAIR_DISPATCHED` pending verification. Supervisor verifies exact output
    SHA and parent, formally dispatches Reviewer, and only then records
    `UNDER_REVIEW`. Reviewer cannot close the blocker. Only Supervisor records
    `CLOSED` after consuming the verdict.
12. A new directory alone never changes a failed identity. A retry authorization
   proves at least one related identity changed: commit, bundle, config, input,
   command, runtime environment, or verified dependency-closure repair.
13. `CLOSED` requires reviewed repair evidence and Supervisor gate closure.
   A blocker requiring model-policy or user authority transitions to
   `ESCALATED_TO_USER`, not an inferred technical repair.
14. Supervisor-only dispatch/gate authority and Executor-only integration-write
    authority remain unchanged throughout the transition.

## Atomic gate transition and non-recursive closure

CONTROL-PROTOCOL-05 governs every prospective stage, repair, diagnosis,
blocker, supersession and activation transition. Its canonical transition
brief and schema are in
[`stage-briefs/CONTROL_PROTOCOL_05_ATOMIC_GATE_TRANSITION.md`](stage-briefs/CONTROL_PROTOCOL_05_ATOMIC_GATE_TRANSITION.md).

1. A formal state transition is one bounded atomic commit. In that transaction
   it synchronizes `CURRENT_STAGE.md`, the Supervisor gate, the received
   Reviewer-verdict reference, the Executor transition record, necessary
   brief/index status, the previous task's final state, and the next active
   task or explicit idle state.
2. `CURRENT_STAGE.md` is canonical current state. Worklogs are append-only audit
   history. The current-state file must equal the latest valid committed
   Supervisor gate transition; a mismatch is a hard failure. Audit entries may
   be appended in the atomic commit but never justify a later verdict-only
   archive commit.
3. A commit is prohibited when its sole or primary purpose is Reviewer PASS,
   Supervisor closure, a final-review result, prior-closure acknowledgment, or
   recording that an earlier closure passed. A commit containing a verdict or
   closure must also make the canonical state transition, authorize/start a
   new substantive task, or perform another substantive control-plane
   transition.
4. One-final-review is mandatory: atomic transition commit -> Supervisor exact
   SHA/parent verification -> one Reviewer read-only review -> Reviewer
   `PASS`/`BLOCKED` -> Supervisor consumes the verdict in the real-time
   workflow -> stop. `PASS` creates no follow-up commit and is not re-reviewed.
5. Every atomic transition includes one machine-checkable
   `atomic_gate_transition` record with this minimum schema:

```yaml
atomic_gate_transition:
  transition_id: stable_unique_id
  exact_input_sha: full_git_sha
  closed_task:
    task_id: string
    previous_status: string
    final_status: string
    reviewed_output_sha: full_git_sha
    reviewer_verdict: PASS_or_BLOCKED
    reviewer_verdict_reference: path#entry
    supervisor_gate: string
  blocker:
    blocker_id: string_or_null
    previous_status: string_or_null
    final_status: string_or_null
  next_active_task:
    task_id: string_or_null
    status: string
    owner: lane_id_or_null
  owner: INT-SUPERVISOR
  repository_writer: INT-EXECUTOR
  runner_authorized: false
  stage_9_authorized: false
  canonical_state_updated: true
  audit_records_appended: [path#entry]
  verdict_only_followup_commit_allowed: false
```

6. A closure or supersession commit is invalid unless it updates canonical
   state, prior-task final state, blocker state when applicable, owner and
   authority, next active/idle task, and necessary evidence references in one
   transaction.
7. The no-verdict-only-commit, one-final-review, no-stale-active-task and
   no-auto-run invariants are Hard Gates. A closed/superseded task cannot remain
   active; a `PASS`, `CLOSED` or idle state never authorizes Runner, upload,
   deployment, retry or the next stage.
8. A Reviewer `BLOCKED` on the atomic commit returns to Supervisor under the
   existing blocker-to-repair protocol. It does not authorize Executor rework.
   A Reviewer `PASS` is consumed without a Git write. The next repository
   commit requires a new substantive Supervisor authorization.
9. Historical verdict-only or closure-only commits remain preserved as audit
   history but are superseded as a prospective workflow pattern by this
   protocol.

## Post-failure read-only diagnosis and automatic dispatch

CONTROL-PROTOCOL-06 extends the blocker and atomic-transition protocols. Its
canonical schema and thin-JAR worked example are in
[`stage-briefs/CONTROL_PROTOCOL_06_POST_FAILURE_DIAGNOSIS_AUTO_DISPATCH.md`](stage-briefs/CONTROL_PROTOCOL_06_POST_FAILURE_DIAGNOSIS_AUTO_DISPATCH.md).

1. A nonzero Runner exit or Hard Gate failure immediately stops the run,
   modification and retry and enters `POST_FAILURE_READ_ONLY_DIAGNOSIS`.
   Runner may read stdout/stderr/logs/manifests; inspect JAR/ZIP/TAR members,
   command, classpath, version, path and mode metadata; calculate SHA256 and
   size; compare build/bundle/release/run artifacts; verify locked config/input
   presence and hashes; and write one new append-only evidence JSON under a new
   evidence directory.
2. During diagnosis Runner does not modify, replace, move or delete existing
   files; install software or change the environment; modify Git; change a
   command and rerun; clean failed directories; authorize Executor; or close a
   blocker.
3. The Runner handoff includes `task_id`, `stage_id`, `source_sha`,
   `run_identity`, `root_cause_status` (`KNOWN`, `PARTIAL` or `UNKNOWN`), a
   concise `root_cause`, `evidence_refs`, nullable `repair_hypothesis`,
   `rerun_performed: false`, `existing_state_modified: false`,
   `hard_gate_status`, and `handoff_to: INT-SUPERVISOR`.
4. Supervisor automatically dispatches a `KNOWN` ordinary technical defect as
   a bounded Executor repair. This includes classpath/JAR/dependency/packaging,
   compilation/Guice/path/manifest, hash/mode/deployment/server compatibility,
   log/config-read and other non-research runtime defects. `PARTIAL` or
   `UNKNOWN` creates a bounded read-only diagnosis: Runner owns server-evidence
   work and Executor owns repository-evidence work.
5. Economic or behavioral semantics, cost policy, demand/capacity,
   missing-data treatment or research interpretation is not an automatic
   technical repair and transitions to `ESCALATED_TO_USER`.
6. Automatic repair never authorizes Runner. A repair requires an exact pushed
   SHA and independent Reviewer `PASS`; a replacement run requires a separate
   exact-SHA Supervisor Runner authorization plus a new source, bundle, release
   and run identity. Identical failed identities are never repeated.
7. Supervisor-only dispatch/gate authority, Executor-only Git write authority,
   Reviewer read-only authority, Runner's explicitly authorized execution and
   read-only diagnosis boundary, and Supervisor-only handoffs remain unchanged.
8. No verdict-only or closure-only follow-up commit is allowed. Any committed
   closure is atomic with a substantive policy, activation, repair, diagnosis
   or other control-plane transition.

## Diagnosis confidence and resource budget

CONTROL-PROTOCOL-07 makes Protocol 06 root-cause status and diagnosis scope
machine-checkable. Its canonical schemas and thin-JAR evidence-chain example
are in
[`stage-briefs/CONTROL_PROTOCOL_07_DIAGNOSIS_CONFIDENCE_AND_BUDGET.md`](stage-briefs/CONTROL_PROTOCOL_07_DIAGNOSIS_CONFIDENCE_AND_BUDGET.md).

Every post-failure handoff records:

```yaml
diagnosis_confidence:
  exact_failure_identity_matched: true | false
  direct_failure_condition_observed: true | false
  causal_chain_demonstrated: true | false
  material_alternatives_checked: true | false
  repair_hypothesis_testable: true | false
  root_cause_status: KNOWN | PARTIAL | UNKNOWN
diagnosis_budget:
  wall_clock_minutes_max: 30
  shell_commands_max: 30
  filesystem_roots_max: 6
  evidence_output_mb_max: 30
  full_server_recursive_scan_allowed: false
  existing_state_mutation_allowed: false
diagnosis_budget_result:
  elapsed_minutes: number
  commands_used: number
  roots_inspected: number
  evidence_output_bytes: number
  budget_exhausted: true | false
  missing_evidence: []
```

1. `KNOWN` requires all five confidence Booleans to be `true`. A first
   exception, stack trace, symptom or correlation is insufficient. The exact
   failure identity, directly observed condition, demonstrated causal chain,
   checked material alternatives and bounded testable repair hypothesis are
   all Hard Gates.
2. `PARTIAL` applies to a plausible but incomplete causal chain, unchecked
   material alternatives, a repair hypothesis without a decisive metric, or
   budget exhaustion before sufficient evidence. `UNKNOWN` applies when no
   verifiable direct cause exists, only symptoms are known, or multiple
   material explanations remain equally plausible.
3. Supervisor cannot promote `PARTIAL` or `UNKNOWN` to `KNOWN` without new
   evidence satisfying all five gates.
4. Inspection is limited to the failed release/run, directly referenced
   staging/build roots, deployment-manifest paths and current
   command/classpath/config/input paths. A recursive scan of all
   `/mnt/DiskM/by` is prohibited.
5. Evidence uses paths, SHA256, size, permissions, short log excerpts, member
   summaries and structured JSON. Large archives, JARs, inputs, outputs or
   complete logs are not copied unless a later diagnosis task explicitly
   authorizes them.
6. Runner stops when any budget limit is reached and reports missing evidence;
   it never enlarges scope itself. `KNOWN` dispatches a bounded Executor
   repair. `PARTIAL` dispatches a more specific bounded diagnosis. `UNKNOWN`
   dispatches a task that narrows the question or changes evidence source.
   Research/policy questions transition to `ESCALATED_TO_USER`.
7. For each `PARTIAL` or `UNKNOWN` result Supervisor may create exactly one
   follow-up diagnosis task. It has a new task ID, explicit missing evidence,
   new scope and budget, and a reason that evidence could change the
   conclusion. The same commands and scope are not repeated.
8. Automatic dispatch never authorizes Runner, retry, Stage 9 execution or a
   later stage. Existing state remains immutable and no closure-only follow-up
   commit is created.

## Execution contract, safe preflight correction and Supervisor server read

CONTROL-PROTOCOL-08 defines the canonical prospective execution contract,
failure routing and bounded Supervisor server-evidence verification. Its full
schema is in
[`stage-briefs/CONTROL_PROTOCOL_08_EXECUTION_CONTRACT_AND_SUPERVISOR_SERVER_READ.md`](stage-briefs/CONTROL_PROTOCOL_08_EXECUTION_CONTRACT_AND_SUPERVISOR_SERVER_READ.md).

Every Runner authorization contains this complete machine-checkable contract:

```yaml
execution_contract:
  source_sha: full_pushed_sha
  working_directory: absolute_path
  java_command: absolute_or_canonical_command
  tool_version_commands: [commands]
  build_command: exact_command
  artifact_resolver: exact_rule_or_command
  bundle_command: exact_command
  release_root: new_absolute_path
  run_command: exact_command
  required_preconditions: [checks]
  hard_gates: [gates]
  diagnostics_only: [checks]
  forbidden_fallbacks: [fallbacks]
```

1. Contract priority is: Supervisor exact contract > current stage brief >
   repository canonical contract > Runner general experience. An explicit
   conflict is `CONTRACT_CONFLICT` and stops execution. When Supervisor omits
   a detail and exactly one repository rule is canonical, Runner uses that
   rule and records its path; ambiguity stops for Supervisor direction.
2. `CONTRACT_PRESERVING_PREFLIGHT_CORRECTION` is allowed only when all fields
   below are true:

```yaml
preflight_correction_gate:
  build_started: false
  bundle_created: false
  release_created: false
  smoke_started: false
  existing_state_modified: false
  canonical_replacement_command_exists: true
  task_semantics_changed: false
```

   It may correct only a wrapper command, the approved Java absolute path, the
   required working directory, or the canonical artifact resolver. It never
   installs software, edits `PATH`, substitutes a tool/JDK, changes config,
   input or build parameters, or acts after build, bundle, release or smoke
   begins. It keeps the same staging/release/run identity and records original
   command, replacement command, canonical basis and zero-mutation proof.
3. The canonical Hong Kong Maven commands are `./mvnw --version` and
   `./mvnw -DskipTests package`; system Maven is not required. The deployment
   artifact is `<build_root>/matsim-example-project-0.0.1-SNAPSHOT.jar`.
   `target/` thin JARs and glob, first-match or size-based selection are
   forbidden.
4. Failures are classified by boundary: `INFORMATIONAL_PROBE`,
   `REQUIRED_PRECONDITION`, `BUILD`, `BUNDLE`, `DEPLOYMENT`, `RUNTIME`, or
   `MODEL_SEMANTIC`. A nonzero informational probe is recorded as a diagnostic
   unless it defeats a named precondition. Required-precondition and later
   technical failures stop the identity. A `KNOWN` ordinary technical defect
   dispatches bounded repair; `PARTIAL`/`UNKNOWN` dispatches bounded diagnosis;
   research, economic, behavioral, cost or missing-data semantics transitions
   to `ESCALATED_TO_USER`.
5. `SUPERVISOR_SERVER_READ_VERIFICATION` is repository policy for bounded
   read-only evidence checks; it does not grant SSH, tool or platform
   capability. Actual access must be independently present and verifiable.
   Scope is limited to exact `/mnt/DiskM/by` staging, release, run and evidence
   roots named by Runner or `CURRENT_STAGE.md`, plus manifest-linked paths.
6. Allowed checks are `ls`, `stat`, bounded `find`, `cat`, `head`, `tail`,
   `grep`, `sha256sum`, `jar tf`, `tar tf`, `unzip -l`, and bounded JSON, YAML,
   XML or log reading. Full-root recursion is prohibited.
7. Supervisor server read never creates, modifies, replaces, chmods, copies,
   moves, deletes or cleans a file; runs Maven, Java, bundle or MATSim; installs
   tools or changes environment; controls processes; accesses outside
   `/mnt/DiskM/by`; or authorizes a lane, run or stage.
8. The default read budget is 15 minutes, 20 commands, four roots and 10 MB of
   returned text, with `full_root_recursive_scan_allowed: false` and
   `state_mutation_allowed: false`. Budget exhaustion stops and reports missing
   evidence. Expansion requires a new bounded diagnosis task.
9. Every verification appends or returns this compact audit record; it never
   creates execution authority:

```yaml
supervisor_server_read_verification:
  source_sha: full_pushed_sha
  exact_roots: [absolute_paths]
  checks: [bounded_read_checks]
  findings: []
  budget_used:
    elapsed_minutes: number
    commands_used: number
    roots_inspected: number
    returned_text_bytes: number
    budget_exhausted: true_or_false
    missing_evidence: []
  state_modified: false
  build_or_run_started: false
  handoff_to: INT-SUPERVISOR
```

10. Supervisor remains sole dispatcher/gate owner, Executor sole Git writer,
    Reviewer read-only, and Runner no-Git and unable to self-authorize. A
    correction, verification, diagnosis or `PASS` does not itself authorize a
    retry or later stage and does not create a verdict-only closure commit.

## Canonical control-plane sources

| Purpose | Canonical source |
|---|---|
| Lane identity, authority and write scope | [`agent-lanes.md`](../../agent-lanes.md) |
| Stable integration policy | this file |
| Active stage and exact input | [`CURRENT_STAGE.md`](CURRENT_STAGE.md) |
| Stage-specific delta | [`stage-briefs/`](stage-briefs/README.md) |
| Append-only lane history | [`docs/agent-worklogs/`](../agent-worklogs/) |
| Technical evidence | Stage-specific paths referenced from `CURRENT_STAGE.md` or the compact handoff |

If sources appear inconsistent, the most recent formal Supervisor instruction
anchored to an exact pushed commit controls execution. Repository policy,
current-stage and brief files remain canonical stable context. The discrepancy
is reported to Supervisor and recorded as a diagnostic or blocker without
rewriting history.

## Compact stage-command schema

```yaml
stage_id: string
exact_input_sha: full_git_sha
objective: one_bounded_outcome
allowed_scope: [paths_or_actions]
hard_gates: [stage_specific_gates]
evidence_required: [path_or_field_references]
stop_condition: one_compact_boundary
handoff_target: lane_id
```

Stable lane rules, standard Git restrictions, diagnostic classification,
unchanged-run prohibition, and escalation boundaries are referenced to this
policy and `agent-lanes.md`; they are not copied into the command.

## Evidence-by-reference rules

- Reference committed evidence as `path#field` or `path#section`.
- Include an exact SHA when the evidence is reviewed across sessions.
- Report a compact value only when it is needed to decide the current gate.
- Do not paste manifests, long test logs, inventories, historical handoffs, or
  validator output when a canonical path and field exist.
- Raw execution logs may remain local diagnostics when durable committed
  summaries and independent checks cover the hard gate.
- Missing, uncommitted, ambiguous, or non-reproducible evidence is identified
  explicitly; it is never represented by an inferred value.

## Compact future worklog schema

New entries append this schema without editing any historical entry:

```yaml
timestamp: ISO-8601
session_id: actual_session_id
stage_id: string
input_sha: full_git_sha
output_sha_or_status: full_git_sha_or_pending
decision: one_or_null
findings: []        # maximum 5
diagnostics: []     # maximum 5; non-blocking unless tied to a hard gate
evidence_refs: []   # path#field or path#section
blockers: []
hard_gate_status: string
handoff_to: lane_id
next_action: one_action
```

Source SHAs, stable policies, large count tables, and earlier observations are
referenced rather than recopied. Corrections are new entries; history is never
rewritten.

## Lane-specific routine output budgets

The structural limits above are mandatory. These token budgets are defaults
for routine cross-session outputs; evidence remains in repository files.

| Lane | Routine cross-session output budget |
|---|---:|
| INT-SUPERVISOR | 700 tokens for one stage delta or gate decision |
| INT-EXECUTOR | 800 tokens for one implementation/evidence handoff |
| INT-RUNNER | 600 tokens for one exact-SHA run evidence handoff |
| INT-REVIEWER | 600 tokens for one exact-SHA review decision |

A safety stop or user model-policy escalation may exceed the token budget only
for the new facts needed to explain the stop. Stable context is still
referenced, not repeated.

## Gate, run and historical boundaries

- Hard Gate, Diagnostic and Trend meanings remain those in
  [`agent-lanes.md`](../../agent-lanes.md). A warning is not promoted by
  repetition or volume.
- A failed run keeps its full identity and evidence. A new directory alone is
  not a relevant change and does not authorize a rerun.
- Historical/legacy/superseded guards remain traceable. A new canonical
  contract identifies the replacement and equivalent protection by path.
- Model-policy escalation boundaries, protected branches, sole-writer
  authority, and the Supervisor-centered hub-and-spoke loop remain unchanged.
- No lane continues into another stage, run, or responsibility without the
  required formal Supervisor dispatch.
