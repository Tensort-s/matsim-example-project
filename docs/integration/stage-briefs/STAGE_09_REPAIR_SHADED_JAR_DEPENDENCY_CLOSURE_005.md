# Stage 9 repair — shaded-JAR dependency closure

## Control identity

- Task ID: `STAGE9-REPAIR-SHADED-JAR-DEPENDENCY-CLOSURE-005`
- Blocker ID: `STAGE9-RUNTIME-DEPENDENCY-CLASSPATH-001`
- Exact input SHA: `c129c18fe5996ef38740c454f7f0482c4ffe4695`
- Repair owner: `INT-EXECUTOR`
- Gate owner: `INT-SUPERVISOR`
- Runner authorized: `false`
- Stage 9 execution authorized: `false`

Stable rules are in [`INTEGRATION_POLICY.md`](../INTEGRATION_POLICY.md), and
canonical state is in [`CURRENT_STAGE.md`](../CURRENT_STAGE.md).

## Failure identity and objective

The superseded Stage 9 identity used bundle
`0f4ab65801f7e1e6e2cec55e4a9e77c8e95caae1af7a57133fef4430b35dbe45`,
release `/mnt/DiskM/by/hk_multimodal_cost_c129c1_stage9_release3`, and run
`smoke_qsim_v1_c129c1_run3`. It failed with `NoClassDefFoundError` for
`org/matsim/core/controler/AbstractModule`.

Maven produced two same-name artifacts: `target/` held a small thin JAR while
the build-root top level held the roughly 300 MB Maven Shade JAR. The prior
preparation command accepted an arbitrary `--fat-jar` path and copied the thin
artifact. JDK, model, config, inputs and cost semantics were unrelated.

The objective is deterministic Shade artifact selection plus a complete,
fail-closed producer-to-release dependency and SHA contract.

## Deterministic deployment contract

The bundle CLI accepts `--build-root`, not `--fat-jar`. The only deployment
artifact is:

```text
<build_root>/matsim-example-project-0.0.1-SNAPSHOT.jar
```

`<build_root>/target/matsim-example-project-0.0.1-SNAPSHOT.jar` is always
non-deployable. If only that thin artifact exists, preparation stops.

The selected JAR must contain the seven canonical project runtime classes and
these six dependency classes:

- `org/matsim/core/controler/AbstractModule.class`
- `org/matsim/core/controler/Controler.class`
- `org/matsim/core/config/ConfigUtils.class`
- `ch/sbb/matsim/routing/pt/raptor/SwissRailRaptorModule.class`
- `org/duckdb/DuckDBDriver.class`
- `com/google/inject/Guice.class`

The built root JAR, staged/final release `app/` JAR and bundled `app/` JAR must
share one SHA256. Bundle metadata records the chain. The final worker checks
that same SHA before class loading or MATSim startup.

## Runtime class-loading preflight

Preparation generates `scripts/RuntimeDependencyPreflight.java` and invokes it
with the staged release's `runtime/jdk-25/bin/java`; its only classpath entry is
the release app JAR. It calls `Class.forName(..., false, ...)` for all 13
required classes, so it does not initialize them or invoke MATSim. Missing
classes, `NoClassDefFoundError`, any `LinkageError`, nonzero exit, or missing
success marker fails preparation.

The final worker repeats the app-JAR SHA and class-loading checks before the
MATSim main class or config is used.

## Allowed scope and hard gates

Only bundle preparation, deterministic validators/evidence, this brief/index,
canonical state and append-only Supervisor/Executor worklogs may change. No
Java model/runtime implementation, Taxi/PT/Car logic, MATSim config/input,
JDK, server state, Runner execution or Stage 10 work is authorized.

Hard gates require exact identity and protected refs; root Shade selection;
thin-JAR rejection; 13-class inventory; build/release/bundle SHA equality;
fail-closed class loading; passing Python, JSON, YAML, Markdown-link, diff and
conflict checks; and zero worklog-history deletion.

Evidence:

- [`stage9_shaded_jar_dependency_closure_validation.json`](../../../data/transport_costs/hongkong/integration_stage9_repair_005_validation_v1/stage9_shaded_jar_dependency_closure_validation.json)
- [`validate_hong_kong_matsim_shaded_jar_contract.py`](../../../scripts/hong_kong_single_city/run/validate_hong_kong_matsim_shaded_jar_contract.py)

## Replacement identity and stop conditions

Release3 and run3 remain historical and must not be changed or reused. A later
attempt requires a reviewed new source SHA, newly prepared bundle SHA, new
release root and new run identity under separate Supervisor authorization.

Stop on ambiguous artifact selection, missing dependency, SHA drift, class
loading failure, model/config/input or JDK change, server action, protected-ref
drift, Runner request, or Stage 10 work.
