# CONTROL-PROTOCOL-08 — execution contract and Supervisor server read

> **Status:** `DEPRECATED_NON_CANONICAL`
> **Prospective authority:** `NONE`
> **Canonical replacement:** [Protocol 09](CONTROL_PROTOCOL_09_LEAN_STAGE_END_REVIEW.md)
> **Use:** historical audit and rationale only. Do not use this document for
> dispatch, current state, review cadence, diagnosis ownership, execution, or
> authorization.

## Control identity

- Task ID: `CONTROL-PROTOCOL-08-EXECUTION-CONTRACT-AND-SUPERVISOR-SERVER-READ`
- Exact input SHA: `4c61a02e562830e248ce7178132e8609f53decde`
- Owner/writer: `INT-EXECUTOR`
- Gate owner: `INT-SUPERVISOR`
- Runner authorized: `false`
- Stage 9 execution authorized: `false`
- Stage 10 or later authorized: `false`

This is one governance-only atomic transition. Stable policy is in
[`INTEGRATION_POLICY.md`](../INTEGRATION_POLICY.md); canonical current state is
in [`CURRENT_STAGE.md`](../CURRENT_STAGE.md).

## Execution-contract template

Every future Runner dispatch must instantiate every field:

```yaml
execution_contract:
  source_sha: full_pushed_sha
  working_directory: /mnt/DiskM/by/exact_authorized_root
  java_command: /mnt/DiskM/by/exact_authorized_root/runtime/jdk-25/bin/java
  tool_version_commands:
    - "./mvnw --version"
    - "<approved-java-absolute-path> -version"
  build_command: "./mvnw -DskipTests package"
  artifact_resolver: "<build_root>/matsim-example-project-0.0.1-SNAPSHOT.jar"
  bundle_command: exact_supervisor_authorized_command
  release_root: /mnt/DiskM/by/new_exact_release_root
  run_command: exact_supervisor_authorized_command
  required_preconditions: []
  hard_gates: []
  diagnostics_only: []
  forbidden_fallbacks: []
```

Priority is Supervisor exact contract > current stage brief > repository
canonical contract > Runner general experience. Explicit disagreement is
`CONTRACT_CONFLICT`. A Supervisor omission uses one uniquely applicable
repository rule by path; multiple rules or ambiguity stop rather than guess.

For Hong Kong, system Maven is not a prerequisite. Commands are
`./mvnw --version` then `./mvnw -DskipTests package` from the exact build root.
Artifact discovery uses only the root Shade JAR. The `target/` thin JAR, JAR
globs, first match and size-based selection are forbidden.

## Contract-preserving preflight correction

This state is available only before any build or material output:

```yaml
contract_preserving_preflight_correction:
  eligibility:
    build_started: false
    bundle_created: false
    release_created: false
    smoke_started: false
    existing_state_modified: false
    canonical_replacement_command_exists: true
    task_semantics_changed: false
  correction:
    original_command: exact_original
    replacement_command: exact_canonical_replacement
    canonical_basis: repository_path_or_supervisor_field
    correction_type: wrapper_command | approved_java_absolute_path | required_working_directory | canonical_artifact_resolver
    same_staging_release_run_identity: true
    zero_mutation_proof: evidence_reference
```

All eligibility fields must pass. The correction may address only the four
named technical forms. It cannot install or substitute tools/JDKs, alter
`PATH`, config, input or build parameters, modify state, choose a new identity,
or occur after build, bundle, release or smoke starts. Otherwise it is a
failure/diagnosis routed to Supervisor, not a correction.

## Failure classification and routing

| class | boundary | routing |
|---|---|---|
| `INFORMATIONAL_PROBE` | optional observation with no named precondition | diagnostic unless a hard gate is demonstrably defeated |
| `REQUIRED_PRECONDITION` | exact identity, path, executable, version, hash or command prerequisite | stop identity; classify root cause |
| `BUILD` | compilation/package/dependency production | stop; ordinary known defect to bounded repair, partial/unknown to diagnosis |
| `BUNDLE` | artifact selection, bundle content or manifest closure | same technical routing |
| `DEPLOYMENT` | upload/release/checksum/executable materialization | same technical routing |
| `RUNTIME` | launcher, classpath, startup or iteration hard gate | same technical routing |
| `MODEL_SEMANTIC` | research/economic/behavioral/cost/missing-data meaning | `ESCALATED_TO_USER` |

A nonzero shell probe is not automatically a Stage blocker. Classification is
based on whether the probe is informational or a named required precondition.
No classification authorizes retry.

## Supervisor server read verification

`SUPERVISOR_SERVER_READ_VERIFICATION` is a bounded policy capability for
evidence checking only. Documentation does not grant actual SSH/platform/tool
access; absent or unverified access remains an external pending capability.

Allowed roots are exact paths below `/mnt/DiskM/by` named by Runner or current
canonical state: staging, release, run and evidence roots, plus paths linked by
their manifests. Allowed operations are `ls`, `stat`, bounded `find`,
`cat/head/tail/grep`, `sha256sum`, `jar tf`, `tar tf`, `unzip -l`, and bounded
JSON/YAML/XML/log reads. Root-wide recursion is forbidden.

Prohibited operations include every create/write/chmod/copy/move/delete/clean
action; Maven, Java, bundle or MATSim invocation; tool installation,
environment mutation or process control; access outside `/mnt/DiskM/by`; and
lane, retry, run or stage authorization.

```yaml
supervisor_server_read_budget:
  wall_clock_minutes_max: 15
  commands_max: 20
  filesystem_roots_max: 4
  returned_text_mb_max: 10
  full_root_recursive_scan_allowed: false
  state_mutation_allowed: false

supervisor_server_read_verification:
  source_sha: full_pushed_sha
  exact_roots: []
  checks: []
  findings: []
  budget_used:
    elapsed_minutes: number
    commands_used: number
    roots_inspected: number
    returned_text_bytes: number
    budget_exhausted: true | false
    missing_evidence: []
  state_modified: false
  build_or_run_started: false
  handoff_to: INT-SUPERVISOR
```

Budget exhaustion stops. A larger scope requires a new bounded diagnosis task.

## Current transition boundary

Run8 evidence exists below
`/mnt/DiskM/by/hk_stage9_4c61a0_staging8` and remains
`AWAITING_INDEPENDENT_REVIEW`. This transition makes no Stage 9 final PASS
claim. It performs no server read, build, bundle, deployment or run and grants
no actual server-read capability. Future Runner, Stage 9 execution and Stage
10 or later remain unauthorized.

Hard gates are exact input/parent identity, governance-only allowlist,
append-only worklogs, resolved links, structured YAML validity, diff/conflict
checks, protected refs and clean pushed identity. Stop on any runtime/model,
config/input, server, bundle or authorization change.
