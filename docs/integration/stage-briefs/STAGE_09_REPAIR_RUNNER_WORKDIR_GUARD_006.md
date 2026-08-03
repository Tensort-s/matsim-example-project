# Stage 9 repair — Runner workdir guard 006

## Control identity

- Task ID: `STAGE9-REPAIR-RUNNER-WORKDIR-GUARD-006`
- Blocker ID: `STAGE9-RUNNER-WORKDIR-001`
- Exact input SHA: `e58861e4f79eb5aa18c8ac286d0173987bcef237`
- Repair owner: `INT-EXECUTOR`
- Gate owner: `INT-SUPERVISOR`
- Runner authorized: `false`
- Stage 9 execution authorized: `false`
- Stage 10 or later authorized: `false`

Stable rules are in [`INTEGRATION_POLICY.md`](../INTEGRATION_POLICY.md), and
canonical state is in [`CURRENT_STAGE.md`](../CURRENT_STAGE.md).

## Failure identity and Protocol 07 diagnosis

The superseded attempt used source SHA
`e58861e4f79eb5aa18c8ac286d0173987bcef237` and staging root
`/mnt/DiskM/by/hk_stage9_e58861_staging5`. Its snapshot contained executable
wrapper `build_root/mvnw`, but Runner invoked `./mvnw --version` from remote
default directory `/home/by`. Bash therefore resolved `/home/by/mvnw` and
reported `No such file or directory` before any package, bundle, upload or
smoke action.

Diagnosis evidence is
`/mnt/DiskM/by/hk_stage9_e58861_staging5/evidence/diagnosis_stage9_workdir_omission.json`.
Under Protocol 07 all five confidence gates are true: exact failure identity
matched, wrong cwd and existing build-root wrapper observed directly, relative
path resolution explains the failure, missing/non-executable wrapper and
JDK/config/input causes are excluded, and the bounded cwd/wrapper preflight is
deterministically testable.

The attempt is `BLOCKED_SUPERSEDED_BY_REPAIR`. Staging5 and every prior
staging/release/run identity remain untouched and forbidden for reuse.

## Canonical command and cwd guard

The next separately authorized Runner command must supply a new absolute
snapshot build root below `/mnt/DiskM/by`. Before either Maven command it must
execute this contract:

```bash
BUILD_ROOT='/mnt/DiskM/by/<new-stage9-staging>/build_root'
EXPECTED_WRAPPER_SHA256='7e6e5d26712efd78140f2f63dafe8d17028f6c5c97ac1f746a043110b7a1d9ad'

case "$BUILD_ROOT" in
  /mnt/DiskM/by/*/build_root) ;;
  *) printf '%s\n' "Unsafe or non-absolute build root: $BUILD_ROOT" >&2; exit 121 ;;
esac
cd -- "$BUILD_ROOT" || exit 122
ACTUAL_CWD="$(pwd -P)"
RESOLVED_BUILD_ROOT="$(readlink -f -- "$BUILD_ROOT")"
test "$ACTUAL_CWD" = "$RESOLVED_BUILD_ROOT" || exit 123
WRAPPER="$RESOLVED_BUILD_ROOT/mvnw"
test -f "$WRAPPER" && test ! -L "$WRAPPER" && test -x "$WRAPPER" || exit 124
WRAPPER_SHA256="$(sha256sum "$WRAPPER")"
WRAPPER_SHA256="${WRAPPER_SHA256%% *}"
test "$WRAPPER_SHA256" = "$EXPECTED_WRAPPER_SHA256" || exit 125
WRAPPER_MODE="$(stat -c '%a' "$WRAPPER")"
test "$WRAPPER_MODE" = '755' || exit 126
printf 'pwd=%s\nwrapper_path=%s\nwrapper_sha256=%s\nwrapper_mode=%s\n' \
  "$ACTUAL_CWD" "$WRAPPER" "$WRAPPER_SHA256" "$WRAPPER_MODE"
./mvnw --version
./mvnw -DskipTests package
```

The `cd` and preflight block is inseparable from both Maven invocations. The
wrapper must be `./mvnw` after the verified `cd`; `/home/by`, an inherited
shell cwd, a relative build-root argument or any arbitrary directory fails
closed. Preflight evidence records `pwd`, wrapper absolute path, SHA256, mode
and the exact command before a build begins.

## Deterministic guard evidence

Exact-tree evidence records `mvnw` as Git mode `100755`, Git blob
`19529ddf8c6eaa08c5c75ff80652d21ce4b72f8c`, SHA256
`7e6e5d26712efd78140f2f63dafe8d17028f6c5c97ac1f746a043110b7a1d9ad`,
and 10,665 bytes. The deterministic contract validation proves:

- cwd `/home/by` resolves `./mvnw` outside build root and is rejected;
- the exact absolute snapshot `build_root` plus matching wrapper identity is
  accepted;
- absent, non-executable, symlinked, wrong-SHA, wrong-mode or cwd-mismatched
  wrappers fail before Maven;
- `./mvnw --version` precedes `./mvnw -DskipTests package`, and neither command
  was executed during this repair.

Structured evidence is
[`stage9_runner_workdir_guard_validation.json`](../../../data/transport_costs/hongkong/integration_stage9_repair_006_validation_v1/stage9_runner_workdir_guard_validation.json).

## Replacement identity and stop conditions

A later attempt requires a reviewed new repair SHA and new staging, bundle,
release and run identities. It must not reuse staging5 or any earlier identity.
This repair changes no Java/model runtime, bundle-preparation script, MATSim
configuration/input, JDK, server/release/run state or protected ref.

Stop on a non-absolute or mismatched cwd, wrapper identity/mode failure,
request to run Maven or access the server during this repair, model/config
change, Runner authorization, Stage 9 retry, Stage 10 work, historical-worklog
rewrite, or verdict-only/closure-only follow-up commit.
