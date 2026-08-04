# Stage 11 — Joint stability at 5 and 10 iterations

## Candidate identity and authority

| Field | Value |
|---|---|
| Task ID | `STAGE11-JOINT-STABILITY-5-10-ITERATIONS` |
| Exact input / review base | `3ed98c4b8b34491a3c6f9fdf3517812323baed76` |
| Runtime/model baseline | `3ed98c4b8b34491a3c6f9fdf3517812323baed76` |
| Repair task | `STAGE11-REPAIR-CANONICAL-LOCKED-HASH-002` |
| Exact repair input / required parent | `68110deb400482a67c66b71e714a5725b7a12fef` |
| Active blocker | `STAGE11-RUNNER-INPUT-HASH-LITERAL-002` (`REPAIR_DISPATCHED`) |
| Candidate owner | `INT-EXECUTOR` |
| Runner authorized by this candidate | `false` |
| Stage 12 or later authorized | `false` |

The first candidate synchronized the realtime Stage 10 `PASS_CLOSED` decision
and defined the two-run contract. The first 5-iteration attempt
`joint_stability_5it_c6a0cdc8_run1` then stopped on a known ordinary technical
contract defect: an invalid controller-regex boundary and a malformed probe
path made config derivation non-deterministic and left incomplete process
evidence. This bounded repair replaces regex editing with a self-validating XML
contract, requires verified numeric PID capture, and allocates two new run
identities. It does not treat the incomplete attempt as Stage 11 evidence.

The replacement attempt `joint_stability_5it_68110deb_repair1_run2` then stopped
at input preflight because its Runner command hand-transcribed the facilities
SHA without the final `e`; the canonical pack manifest remained correct. This
is a known ordinary technical execution-contract defect, not input corruption
or semantic change. The current bounded repair makes the checked-in seven-row
registry the only source of expected paths and hashes and forbids handwritten
hash literals.

This repair candidate does not contact the server, build, bundle, release,
run, calibrate, or authorize Runner. After one Protocol 09 stage-end review,
Supervisor may issue a separate exact-SHA Runner contract.

The later Runner `source_sha` is the exact pushed repair candidate selected by
Supervisor. That repair candidate must have sole parent `68110deb…`; its
allowlisted contract/control-plane delta must leave the runtime/model tree
semantically unchanged, while the adopted runtime/model baseline remains
traceable to `3ed98c4…`. A commit cannot embed its own SHA, so the exact repair
SHA and eight-character token are late-bound only by the subsequent Supervisor
contract.

## Stage 10 closure consumed

Stage 10 `STAGE10-DETERMINISTIC-MULTIMODAL-COST-COVERAGE` is `PASS_CLOSED` at
exact reviewed output `3ed98c4b8b34491a3c6f9fdf3517812323baed76`.
Its fixed selected plan directly exercised one Taxi, one PT and one Car leg.
Directly observed costs were Taxi `35.3` HKD, PT `4.9` HKD, and Car `2.5` HKD,
total `42.7` HKD. Duplicate Taxi/PT/Car leg callbacks failed closed. This
directed component proof remains separate from Stage 11 production-run
coverage and is cited at
`data/transport_costs/hongkong/integration_stage10_validation_v1/stage10_directed_multimodal_cost_coverage_validation.json`.

## Objective and non-objectives

Run exactly two new Hong Kong joint-model identities, one completing
iterations `0..5` and one completing `0..10`, to establish technical stability,
output completeness, and comparable trends. Stage 11 does not tune ASC,
utility, fare/cost parameters, demand, capacity, supply, route choice,
replanning policy, or missing-data treatment. It is not calibration and does
not authorize Stage 12.

## Superseded and replacement run identities

The following failed or allocated `c6a0cdc8` identities are immutable evidence
and are `BLOCKED_SUPERSEDED_BY_REPAIR`; neither their directories nor partial
outputs may be reused, overwritten, cleaned, or treated as replacement runs:

- `joint_stability_5it_c6a0cdc8_run1`, staging
  `/mnt/DiskM/by/hk_stage11_c6a0cdc8_5it_staging1`, release
  `/mnt/DiskM/by/hk_multimodal_cost_c6a0cdc8_stage11_5it_release1`, run root
  `/mnt/DiskM/by/hk_stage11_c6a0cdc8_5it_run1`;
- `joint_stability_10it_c6a0cdc8_run1`, staging
  `/mnt/DiskM/by/hk_stage11_c6a0cdc8_10it_staging1`, release
  `/mnt/DiskM/by/hk_multimodal_cost_c6a0cdc8_stage11_10it_release1`, run root
  `/mnt/DiskM/by/hk_stage11_c6a0cdc8_10it_run1`;
- `joint_stability_5it_68110deb_repair1_run2`, staging
  `/mnt/DiskM/by/hk_stage11_68110deb_5it_repair1_staging2`, release
  `/mnt/DiskM/by/hk_multimodal_cost_68110deb_stage11_5it_repair1_release2`, run
  root `/mnt/DiskM/by/hk_stage11_68110deb_5it_repair1_run2`;
- `joint_stability_10it_68110deb_repair1_run2`, staging
  `/mnt/DiskM/by/hk_stage11_68110deb_10it_repair1_staging2`, release
  `/mnt/DiskM/by/hk_multimodal_cost_68110deb_stage11_10it_repair1_release2`, run
  root `/mnt/DiskM/by/hk_stage11_68110deb_10it_repair1_run2`.

The subsequent Supervisor contract replaces `{REPAIR_SHA}` and `{REPAIR_SHA8}`
with the exact reviewed repair candidate. Every replacement path must be absent
before use.

| Horizon | Staging root | Release root | Run root / identity |
|---|---|---|---|
| 5 | `/mnt/DiskM/by/hk_stage11_{REPAIR_SHA8}_5it_repair2_staging3` | `/mnt/DiskM/by/hk_multimodal_cost_{REPAIR_SHA8}_stage11_5it_repair2_release3` | `/mnt/DiskM/by/hk_stage11_{REPAIR_SHA8}_5it_repair2_run3` / `joint_stability_5it_{REPAIR_SHA8}_repair2_run3` |
| 10 | `/mnt/DiskM/by/hk_stage11_{REPAIR_SHA8}_10it_repair2_staging3` | `/mnt/DiskM/by/hk_multimodal_cost_{REPAIR_SHA8}_stage11_10it_repair2_release3` | `/mnt/DiskM/by/hk_stage11_{REPAIR_SHA8}_10it_repair2_run3` / `joint_stability_10it_{REPAIR_SHA8}_repair2_run3` |

The two identities have separate source-snapshot/build, locked-input-pack,
bundle, deployment-manifest, release, derived-config, output, log, PID/exit,
and evidence paths. They never reuse or overwrite run3, run8, their releases,
any failed staging path, or each other. A failure stops that identity; changing
only a directory never authorizes a retry.

## Locked toolchain and artifact closure

- approved Linux JDK archive SHA256:
  `69264a7a211bf5029830d07bc3370f879769d62ebc5b5488e90c9343a2da0e1f`;
- extracted runtime: `runtime/jdk-25/bin/java`, executable and exactly Java
  `25.0.3`;
- Maven wrapper commands, from the verified build root only:
  `./mvnw --version` and `./mvnw -DskipTests package`;
- expected Maven `3.9.8` and MATSim `2026.0`;
- deployment JAR:
  `<build_root>/matsim-example-project-0.0.1-SNAPSHOT.jar`;
- forbidden artifact: `target/matsim-example-project-0.0.1-SNAPSHOT.jar`, any
  glob/first-match/size-guess selection, or an old server JAR.

The root Shade JAR must contain the canonical Taxi/PT/Car/multimodal classes
and MATSim, Raptor, DuckDB, and Guice dependency classes enumerated in the
structured contract. Built JAR SHA must equal bundled `app/` JAR SHA and final
release `app/` JAR SHA. Release checksum inventory and the Java-only dependency
preflight must pass before config reading or MATSim startup.

## Seven locked v2/Ferry Core inputs

Each run verifies exactly the following pack; no v1, pre-Ferry, five-percent
transit-vehicle, existing server bundle, or unmanifested fallback is allowed.

| Pack path | SHA256 |
|---|---|
| `config/config_hong_kong_5pct_v2_activity_modechoice_50it.xml` | `75f9c8e82b6fee4141d3544c931309ca23abce76fe6d170c840acb007e1b115c` |
| `input/plans_routed_5pct_v2.xml.gz` | `c73ee48e792e7aebd55b7a2691664ae7f3f4f27d307aef2a6bf58263b3aaafea` |
| `input/facilities_5pct_v2.xml.gz` | `74775533a7022b248d37197dbc94d27f239239aca386df75c7a391cc277ef10e` |
| `input/privateVehicles_5pct.xml.gz` | `5a48b2afe404afaa6864a465c527277605a276e54cd879d3971261186938c994` |
| `input/network.xml.gz` | `dfc696442913a6d16a1ca1be7e5a332ec5762012190ed43a38f05493905ddc95` |
| `input/transitSchedule_5pct.xml.gz` | `eb92e6c7b3c2746313be92b8c88d51bc645d1db3c6605d1f4b472f27c9896aed` |
| `input/transitVehicles_10pct.xml.gz` | `16a6b89f77d3827ded06641869bf4e4c5168fb718356c1fe04e9f9249fdd7429` |

The sole machine-readable source of these values is
`canonical_locked_input_registry.rows` in the structured Stage 11 contract.
It contains exactly seven rows keyed uniquely by normalized `pack_path`; roles
are also unique and every SHA must match `^[0-9a-f]{64}$`. The canonical rows
SHA is
`0bc63a4dca7b4ca7b5b5583e55610299848d3597e833560a5186a404200ab659`;
the canonical derived `{path,sha256}` expected-map SHA is
`dc4e8e5fb3bfa882a223fba0e7162a27e4d6fdb820c3922b011d6c325d803ca5`.

Runner reads the registry from the exact Supervisor-authorized source SHA,
validates its schema/set/cardinality/path/hash rules, mechanically derives the
expected map, then compares build-pack, bundle, release and run-config actual
maps. It records registry SHA, expected-map SHA, each actual-map SHA and any
missing/extra/mismatched path. Missing, duplicate, extra, malformed or unequal
rows stop before config derivation or Java. A Runner command may not repeat or
override any individual expected path/hash literal.

The canonical authoritative-data copies were rehashed locally during candidate
validation and matched all seven values. Runner must independently verify its
manifest-bound external pack through this registry contract before each
build/bundle/release.

## Execution contract

The complete machine-readable template is
[`stage11_joint_stability_execution_contract.json`](../../../data/transport_costs/hongkong/integration_stage11_contract_v1/stage11_joint_stability_execution_contract.json).
The subsequent Supervisor dispatch must bind every late-bound path/hash and
must preserve Protocol 09 priority and stop rules.

For each horizon, Runner follows:

```text
exact source snapshot + tree verification
  -> parse exact-source canonical seven-row registry and verify its SHA
  -> derive expected map mechanically; verify pack/bundle/release/run maps
  -> cd verified build_root
  -> ./mvnw --version
  -> ./mvnw -DskipTests package
  -> deterministic root Shade JAR validation
  -> build-bundle into the identity's new staging/bundle/manifest/release
  -> release SHA256SUMS + runtime Java/class-loading preflight
  -> derive one new run-root config with the XML-parser contract below
  -> pass source-SHA/path/reparse/normalized-diff pre-run gate
  -> launch exact Java/JAR/config command once
  -> capture and verify one positive numeric PID at the exact run-root path
  -> wait for terminal exit and capture immutable structured evidence
```

The derived config changes only execution/output controls:

- `controller.firstIteration=0`;
- `controller.lastIteration=5` or `10` for its matching identity;
- `controller.outputDirectory=<new run root>/output`;
- `controller.overwriteFiles=failIfDirectoryExists`;
- output intervals may be `1` for complete per-iteration evidence;
- all other parameters and all seven input references remain unchanged.

Config derivation is never a regular-expression or line-edit operation. Runner
uses Python standard-library `xml.etree.ElementTree` (or a later Supervisor
command implementing exactly the same repository-contained structured
contract), requires exactly one direct `controller` module and exactly one
direct parameter for every allowlisted key, and refuses missing or duplicate
keys. It changes only the seven `value` attributes listed above, writes an
absent UTF-8/LF destination, reparses it, and compares sorted
`module-name/param-name` maps. The normalized JSON diff must contain exactly
the seven allowlisted keys and their contracted before/after values; every
other parameter and every input reference must be value-equivalent.
First-match selection, adding a missing key, and editing another module fail
closed.

Before Java starts, one persisted gate must prove: source config is a regular
non-symlink file whose SHA matches the release manifest; derived config is a
regular non-symlink file and reparses; controller/parameter cardinalities are
exact; normalized changed keys and before/after values match; all seven input
paths exist and hashes match; all non-allowlisted values are unchanged; and
all identity paths are absolute under the new staging/release/run roots. The
exact derivation command, source/derived/diff SHA256 values and effective
controller values are required evidence. Any false or missing field stops
before Java launch.

The run command is the release's exact
`runtime/jdk-25/bin/java`, `-Xms16g -Xmx96g`, the release root Shade JAR,
`org.matsim.project.RunHongKong5Pct`, the derived config, `unused --simulate`,
and `/usr/bin/time -v`, executed once from the new run root. No system Java,
system Maven, `PATH` fallback, altered heap, alternate main class, or command
retry is permitted.

The background Java command may be launched only once. Runner captures the
shell `$!` value immediately and accepts it only when it matches
`^[1-9][0-9]*$` and is greater than one. The PID evidence file is created with
fail-if-exists semantics at the exact absolute new run-root path, contains only
that decimal PID plus LF, and reads back identically; `kill -0` must succeed
immediately after capture or the terminal exit is recorded and the identity
stops. Literal `$!`, `${pid}`, `${PID}`, `pid=$!`, empty/zero/negative/non-
numeric values, relative paths, unexpanded placeholders, and paths outside the
new run root or inside a superseded identity all fail closed.

## Hard Gates

1. Repair-candidate parent is exact `68110deb…`; branch, ancestry,
   local/tracking/remote refs, protected refs, and clean worktree are proven.
   Later Runner source equals the exact reviewed Stage 11 repair candidate and
   retains runtime/model baseline `3ed98c4…` without semantic change.
2. Both identities independently prove exact source tree, approved Java
   `25.0.3`, Maven wrapper, root Shade JAR/dependency closure, and built →
   bundle → release SHA continuity. The target thin JAR fails closed.
3. Exactly seven unique v2/Ferry Core rows are parsed mechanically from the
   authorized-source canonical registry. Registry and expected-map hashes,
   normalized paths, SHA format and build/bundle/release/run actual-map hashes
   all pass. Missing/duplicate/extra/mismatched rows and handwritten hash
   overrides fail closed before config or Java; historical v1/pre-Ferry inputs
   and fallbacks are absent.
4. Config derivation uses the deterministic XML contract, with exact
   controller/param cardinality and a source-SHA/path/reparse/normalized-diff
   gate completed before Java starts. Regex or line replacement is forbidden.
   Process evidence contains the verified positive numeric PID and exact
   absolute probe paths; literal shell placeholders fail closed.
5. The five-iteration identity exits zero and completes every iteration
   boundary `0..5`; the ten-iteration identity exits zero and completes `0..10`.
   Each has complete logs, events, scores, plans/outputs, exit code, timings,
   config hash, and output inventory evidence.
6. Taxi, PT and Car have one canonical component owner and exactly one charge
   per experienced ordinal. Duplicate callbacks/charges fail closed. Fixed ownership
   never enters a leg; unresolved is never numeric zero; all
   money/cost/score values are finite.
7. Evidence records actual Taxi legs and `routingMode=taxi`, PT legs, and Car
   legs for both runs. A zero production Taxi count is an explicit coverage
   limitation/Diagnostic and cannot be presented as Stage 11 Taxi runtime
   coverage; Stage 10 directed proof remains separate.
8. A structured 5-versus-10 trend table records iteration duration, event
   count, score/cost summaries, stuck/abort, component/charge counts, duplicate
   suppression, non-finite count, and output completeness. Diagnostics/Trends
   do not become Hard Gate failures without a named violated invariant.
9. No Taxi/PT/Car production code, scoring/cost semantic, utility, ASC,
   calibration, demand, capacity, supply, missing-data policy, locked input,
   old server directory, or protected ref changes. Only the allowlisted
   temporary execution-horizon/output config delta is permitted.
10. Executor candidate checks compile, focused and negative exactly-once tests,
   structured validators, links, diff/conflict, allowlist, protected refs,
   clean status and post-push equality with `unresolved_items=[]`.
11. Runner is unauthorized by this candidate. Stage 12 calibration and every
    later stage remain unauthorized.

## Hard Gate evidence versus Diagnostics and Trends

Hard Gate evidence includes identities/hashes, zero exits, iteration-boundary
completion, output inventories, unique component/ordinal charging, finite
values, non-zero-required artifacts, exact locked inputs, and protected refs.

Diagnostics include elapsed build/bundle/release/run time, peak RSS, warnings,
PrepareForSim/QSim timings, stuck/abort causes, zero Taxi production coverage,
component coverage, duplicate-suppression counts, and per-iteration output
sizes. They are recorded without automatic failure unless they defeat a Hard
Gate. Trends compare only the 5- and 10-iteration identities; they are not
calibration, convergence, welfare, or behavioral-policy conclusions.

## Required final Runner evidence

For each identity, the later Runner handoff records exact source/parent/tree,
snapshot and pack manifests, all seven hashes, Java/Maven/MATSim, build/bundle/
release/run commands, root JAR and SHA chain, release checksums, derived config
source/hash/diff, immutable directories, process identity/exit, completed
iterations, outputs/events/scores/costs, component and actual-mode counts,
duplicates/non-finite/unresolved/fixed-ownership checks, diagnostics, and
coverage limitations. It then records the cross-run trend fields defined in
the structured schema and reports only to Supervisor.

## Stop conditions

Stop without retry on any exact-SHA/tree/input/JDK/JAR/config mismatch, reused
or existing path, thin/ambiguous JAR, missing dependency, unauthorized config
delta, nonzero/incomplete iteration, duplicate/non-finite/silent-zero/fixed-leg
charge, semantic/policy ambiguity, protected-ref change, destructive action,
server path outside `/mnt/DiskM/by`, or any request for calibration/Stage 12.
Runner failure enters bounded read-only diagnosis under Protocol 09; no
self-repair or unchanged rerun is authorized.

## Candidate next action

Executor pushes this contract/control-plane repair candidate and reports only
to Supervisor. Supervisor verifies exact SHA/parent and dispatches one
stage-end Reviewer. Only after Reviewer PASS may Supervisor issue a separate
exact Runner contract that binds both replacement identities; this brief
itself starts nothing.
