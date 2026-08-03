# Stage 9 repair — deterministic artifact discovery 010

## Control identity

- Task ID: `STAGE9-REPAIR-ARTIFACT-DISCOVERY-010`
- Blocker ID: `STAGE9-RUNNER-SHADE-CLOSURE-002`
- Exact input SHA: `3237c8f8e6bacf10feaa9bb515f58612c269f3a3`
- Repair owner: `INT-EXECUTOR`
- Gate owner: `INT-SUPERVISOR`
- Runner authorized: `false`
- Stage 9 execution authorized: `false`
- Stage 10 or later authorized: `false`

Stable rules are in [`INTEGRATION_POLICY.md`](../INTEGRATION_POLICY.md), and
canonical state is in [`CURRENT_STAGE.md`](../CURRENT_STAGE.md).

## Known failure identity

The superseded attempt used source SHA
`3237c8f8e6bacf10feaa9bb515f58612c269f3a3`, staging root
`/mnt/DiskM/by/hk_stage9_3237c8_staging7`, and reserved run identity
`smoke_qsim_v1_3237c8_run7`. Maven wrapper/version and package commands exited
zero from the verified build root. The run never started, and no release,
bundle, upload or smoke action occurred.

Read-only diagnosis at
`/mnt/DiskM/by/hk_stage9_3237c8_staging7/evidence/shade_server_diagnosis_009/diagnosis.json`
proved that the POM-configured root Shade JAR existed at
`build_root/matsim-example-project-0.0.1-SNAPSHOT.jar`: SHA256
`54c65711a2e023cdff7986a840bcb7f81889d6f07233c94f02f50b204f2345c7`,
300,597,135 bytes and 101,152 ZIP entries. Runner discovery scanned only
`build_root/target`, observed the 454,252-byte thin JAR with SHA prefix
`afc0d618`, and incorrectly selected that artifact. This establishes the
ordinary technical root cause as `KNOWN`.

Staging7 and run7 are `BLOCKED_SUPERSEDED_BY_REPAIR`, immutable and forbidden
for reuse.

## POM-driven discovery contract

The deployment filename is derived from the reviewed POM contract and the
canonical resolver constant; it is never discovered through a glob:

```text
BUILD_ROOT/matsim-example-project-0.0.1-SNAPSHOT.jar
```

At the exact input SHA, `pom.xml` SHA256 is
`6eb7ceb996c1222c7e24550ff10c3d68e524fcef9392422d5b4ba51e2b9c4d6e`;
its artifact/version are `matsim-example-project` / `0.0.1-SNAPSHOT`, and the
Shade execution output is
`${project.basedir}/${project.build.finalName}.jar` in the `package` phase.

The future separately authorized Runner must execute the equivalent of this
pre-bundle evidence contract from a new identity:

```bash
BUILD_ROOT='/mnt/DiskM/by/<new-stage9-staging>/build_root'
DEPLOYMENT_JAR="$BUILD_ROOT/matsim-example-project-0.0.1-SNAPSHOT.jar"
TARGET_THIN_JAR="$BUILD_ROOT/target/matsim-example-project-0.0.1-SNAPSHOT.jar"

test -d "$BUILD_ROOT" || exit 141
test -f "$DEPLOYMENT_JAR" && test ! -L "$DEPLOYMENT_JAR" || exit 142
test "$(dirname -- "$DEPLOYMENT_JAR")" = "$BUILD_ROOT" || exit 143
test "$DEPLOYMENT_JAR" != "$TARGET_THIN_JAR" || exit 144

ROOT_STAT="$(stat -c 'type=%F mode=%a size=%s path=%n' "$DEPLOYMENT_JAR")"
ROOT_SHA256="$(sha256sum "$DEPLOYMENT_JAR")"
ROOT_SHA256="${ROOT_SHA256%% *}"
ROOT_ENTRY_COUNT="$("$JAVA_HOME/bin/jar" tf "$DEPLOYMENT_JAR" | wc -l)"
printf '%s\nroot_sha256=%s\nroot_entry_count=%s\n' \
  "$ROOT_STAT" "$ROOT_SHA256" "$ROOT_ENTRY_COUNT"

if test -e "$TARGET_THIN_JAR"; then
  TARGET_STAT="$(stat -c 'type=%F mode=%a size=%s path=%n' "$TARGET_THIN_JAR")"
  TARGET_SHA256="$(sha256sum "$TARGET_THIN_JAR")"
  TARGET_SHA256="${TARGET_SHA256%% *}"
  printf 'target_thin_rejected=true\n%s\ntarget_sha256=%s\n' \
    "$TARGET_STAT" "$TARGET_SHA256"
fi
```

No `target/*.jar`, recursive JAR glob, size-based choice, first-match choice or
arbitrary `--fat-jar` argument is allowed. The root path is inspected first.
An absent, symlinked, non-regular or path-escaped root JAR fails closed even if
the target thin JAR exists.

## Dependency-closure evidence before bundle preparation

The root JAR member inventory must contain the seven canonical Taxi/PT/Car
and multimodal project classes plus these dependency classes:

- `org/matsim/core/controler/AbstractModule.class`
- `org/matsim/core/controler/Controler.class`
- `org/matsim/core/config/ConfigUtils.class`
- `ch/sbb/matsim/routing/pt/raptor/SwissRailRaptorModule.class`
- `org/duckdb/DuckDBDriver.class`
- `com/google/inject/Guice.class`

Evidence records the exact discovery command, absolute root path, regular and
non-symlink status, mode, size, SHA256, entry count, required-class matrix and
explicit target rejection. Missing classes or unreadable ZIP inventory fail
before any bundle command. The canonical implementation remains
`resolve_deployment_jar()` plus `verify_fat_jar()` in
[`prepare_hong_kong_matsim_server_bundle.py`](../../../scripts/hong_kong_single_city/run/prepare_hong_kong_matsim_server_bundle.py),
with its existing deterministic validator
[`validate_hong_kong_matsim_shaded_jar_contract.py`](../../../scripts/hong_kong_single_city/run/validate_hong_kong_matsim_shaded_jar_contract.py).
Neither file changes in this repair.

Structured governance evidence is
[`stage9_artifact_discovery_validation.json`](../../../data/transport_costs/hongkong/integration_stage9_repair_010_validation_v1/stage9_artifact_discovery_validation.json).

## Replacement identity and stop conditions

A later attempt requires a reviewed new repair SHA plus new staging, bundle,
release and run identities. It must not reuse staging7, run7 or an earlier
identity. This repair runs no Maven command, accesses no server and authorizes
no Runner or Stage 9 execution.

Stop on root-path ambiguity, glob-based selection, target thin-JAR selection,
missing dependency class, server/Maven/run request, model/config/input change,
protected-ref change, Stage 10 work, historical-worklog rewrite, or a
verdict-only/closure-only follow-up commit.
