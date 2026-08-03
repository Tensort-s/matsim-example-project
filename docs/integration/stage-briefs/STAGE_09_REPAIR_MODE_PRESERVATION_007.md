# Stage 9 repair — source-snapshot mode preservation 007

## Control identity

- Task ID: `STAGE9-REPAIR-MODE-PRESERVATION-007`
- Blocker ID: `STAGE9-RUNNER-WORKDIR-MODE-001`
- Exact input SHA: `f182b24c2b1bffdb216248d50e579275001d1b1b`
- Repair owner: `INT-EXECUTOR`
- Gate owner: `INT-SUPERVISOR`
- Runner authorized: `false`
- Stage 9 execution authorized: `false`
- Stage 10 or later authorized: `false`

Stable rules are in [`INTEGRATION_POLICY.md`](../INTEGRATION_POLICY.md), and
canonical state is in [`CURRENT_STAGE.md`](../CURRENT_STAGE.md). Protocol 07
diagnosis confidence and resource budgets remain unchanged.

## Failure identity and diagnosis

The superseded attempt used source SHA
`f182b24c2b1bffdb216248d50e579275001d1b1b`, staging root
`/mnt/DiskM/by/hk_stage9_f182b2_staging6`, and reserved run identity
`smoke_qsim_v1_f182b2_run6`. The run never started. Read-only evidence at
`/mnt/DiskM/by/hk_stage9_f182b2_staging6/evidence/diagnosis_stage9_wrapper_mode.json`
shows that the exact Git tree records `mvnw` as mode `100755`, while the
archive/extraction path produced mode `0775`. The strict pre-Maven guard
therefore stopped before package, bundle, upload or smoke work.

The Protocol 07 diagnosis is `KNOWN`: the exact failure identity and wrapper
were inspected, the mode mismatch was observed directly, the preflight's
`0755` equality guard explains the stop, cwd/path/bytes and later Maven or
MATSim causes were excluded at this boundary, and the mode-continuity repair
hypothesis has deterministic acceptance and rejection criteria.

Staging6, release6 and run6 are `BLOCKED_SUPERSEDED_BY_REPAIR`. They remain
immutable and forbidden for reuse. This repair does not chmod staging6 or any
other existing server path.

## Canonical mode-preservation contract

The source-snapshot producer and later consumer must prove one continuous
wrapper identity before Maven:

| boundary | required type | required mode | required bytes |
| --- | --- | --- | --- |
| exact Git tree | regular blob, not link | `100755` | blob `19529ddf8c6eaa08c5c75ff80652d21ce4b72f8c` |
| accepted normalized snapshot archive | regular member, not link | `0755` | SHA256 `7e6e5d26712efd78140f2f63dafe8d17028f6c5c97ac1f746a043110b7a1d9ad`, 10,665 bytes |
| newly extracted immutable `source_root/mvnw` | regular file, not link, executable | `0755` | same SHA256 and size as accepted archive member |
| newly materialized `build_root/mvnw` | regular file, not link, executable | `0755` | same SHA256 and size as accepted archive member |

Git `100755` maps only to POSIX runtime `0755`. Group-write or other added
permission bits are not an equivalent mapping. Read-only reproduction from
the exact input commit found the unnormalized `git archive` member to be a
regular file with mode `0775`, SHA256
`7e6e5d26712efd78140f2f63dafe8d17028f6c5c97ac1f746a043110b7a1d9ad`, and
10,665 bytes under the reviewed `core.autocrlf=false` / `core.eol=lf`
snapshot command. That raw archive is rejected even though its bytes match.

A future separately authorized artifact-production identity must construct a
new normalized archive from the exact Git object, set the member header mode
to `0755` before the archive is sealed, and record the source SHA, tree entry,
blob identity, member type/mode/size/SHA256 and archive SHA256 in its manifest.
Normalization is an artifact-production operation on a new identity; it is
not a post-extraction chmod, a run-time repair, or permission mutation of an
accepted immutable snapshot. An archive whose `mvnw` member is `0775` or any
mode other than `0755` fails closed and must not be extracted for a build.

## Deterministic read-only pre-Maven checks

Before any Maven command, a later separately authorized Runner must record and
compare all four boundaries:

1. `git ls-tree <exact-source-sha> -- mvnw` is `100755 blob` with the expected
   blob identity.
2. The sealed snapshot archive contains exactly one regular, non-symlink
   `mvnw` member with mode `0755`, expected size and SHA256.
3. Newly extracted `source_root/mvnw` is regular, non-symlink, executable,
   mode `0755`, and byte-identical to the accepted archive member.
4. Newly materialized `build_root/mvnw` has the same type, mode, size and
   SHA256; the absolute-cwd guard from repair 006 also passes.
5. Only after all comparisons pass may `./mvnw --version` and
   `./mvnw -DskipTests package` be considered. Neither command is run here.

Mode `0775` is an explicit negative fixture at the archive, `source_root` and
`build_root` boundaries. Missing, non-executable, symlinked, duplicate,
wrong-size, wrong-SHA or differently moded wrappers also fail closed. The
source snapshot and failed identities are never changed to make a check pass.

Structured evidence is
[`stage9_mode_preservation_validation.json`](../../../data/transport_costs/hongkong/integration_stage9_repair_007_validation_v1/stage9_mode_preservation_validation.json).

## Replacement identity and stop conditions

A later attempt requires a reviewed new repair SHA plus new staging, bundle,
release and run identities. It must not reuse staging6, release6, run6 or any
earlier identity. No Runner or Stage 9 execution is authorized by this repair.

Stop on a Git/tree mismatch, archive member mode other than `0755`, inability
to prove wrapper byte/mode continuity, request to chmod an existing snapshot,
Maven/server/run request, model/config/input change, protected-ref change,
Stage 10 work, historical-worklog rewrite, or verdict-only/closure-only
follow-up commit.
