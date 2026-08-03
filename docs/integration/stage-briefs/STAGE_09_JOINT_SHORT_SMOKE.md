# Stage 9 — Joint short smoke

| Field | Value |
|---|---|
| Activation task | `STAGE9-ACTIVATE-ATOMIC-GATE` |
| Runtime task | `STAGE9-JOINT-SHORT-SMOKE` |
| Activation input | `9c66fa772cf128fdcf208a5e3171bd7fbd3444d5` |
| Runtime owner | `INT-RUNNER` after a separate Supervisor instruction only |
| Current Runner authorization | `false` |
| Formal 50-iteration / Stage 10+ | unauthorized |

## Objective

Run exactly one new Hong Kong joint short smoke from the exact pushed Stage 9
activation SHA using a newly built and uploaded release produced by the
repaired bundle contract. Demonstrate startup, dependency closure and one
short iteration boundary without calibration or a formal run.

This activation commit does not build, upload or run anything. Supervisor must
later issue a separate run instruction naming the exact activation SHA,
replacement bundle/release/run identity and command before Runner acts.

## Runtime identity and boundaries

The separately authorized Runner must:

- use the exact pushed activation SHA as source identity and prove that
  `339ef046c55faf3e727a19d32234612bd6974241` is its ancestor;
- build a new bundle, upload to a new release root and create a new run
  directory; never reuse the superseded source/release/run identity rooted at
  `/mnt/DiskM/by/hk_multimodal_cost_674a6025_stage8d_build2`;
- use the approved Linux JDK `25.0.3`, verify its archive hash, materialize
  `runtime/jdk-25/bin/java`, and pass executable/version preflight;
- use exactly the seven locked v2/Ferry Core files: production config, routed
  v2 plans, v2 facilities, network, private vehicles, Ferry Core transit
  schedule and 10% transit vehicles;
- execute only `scripts/run_smoke.sh` with
  `config/config_smoke_qsim.xml` and `lastIteration=0`;
  `config/config_formal_50it.xml`, calibration and Stage 10+ are forbidden;
- operate only below `by@100.103.8.34:/mnt/DiskM/by`, use new append-only
  directories, and never delete or overwrite prior evidence.

The canonical seven-file paths and hashes are referenced from
`data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_server_bundle_evidence.json#external_locked_input_pack.locked_input_sha256`.
The repaired dependency contract is documented at
`docs/integration/stage-briefs/STAGE_08D_R1_JDK_RUNTIME_CLOSURE.md`.

## Invariants and hard gates

1. Source checkout/snapshot, build, bundle and runtime identities equal the
   separately authorized activation SHA; the repaired SHA is an ancestor.
2. Bundle SHA, release root and run directory are new and traceable. The old
   `674a6025` release/run identity is rejected rather than reused.
3. The approved JDK archive hash passes before extraction;
   `runtime/jdk-25/bin/java` exists, is executable and reports Java `25.0.3`.
4. All seven v2/Ferry Core input hashes match the locked manifest. Missing,
   stale v1, pre-Ferry or mismatched inputs fail closed.
5. Only the prepared smoke configuration runs; its effective
   `controller.lastIteration=0`. Formal 50-iteration configuration is absent
   from the command.
6. The new shaded JAR contains the current Taxi, PT, Car and multimodal runtime
   classes; release checksum and launcher dependency preflights pass.
7. The smoke process exits zero, reaches the required iteration-0 completion
   boundary, and leaves complete traceable output/log evidence without fatal
   or uncaught runtime errors.
8. Taxi remains native; PT and Car canonical components remain unique and
   exactly-once. Missing/unresolved cost stays explicit, fixed ownership stays
   excluded, and monetary/score results are finite with no duplicate charge.
9. No model, cost policy, economic parameter, demand, capacity, config/input,
   network, schedule, vehicle, facility or calibration semantic is changed.
10. Protected refs remain unchanged; no destructive action, formal run,
    Stage 10+ action or implicit rerun occurs.

Any nonzero or incomplete run is `BLOCKED`; selecting another directory alone
does not authorize a retry. Supervisor must consume the failure identity and
dispatch diagnosis/repair under the canonical blocker protocol.

## Diagnostics and trends

Diagnostics record build/bundle/upload duration, Java/Maven/MATSim versions,
peak memory, PrepareForSim/QSim timing, warnings, event and component counts,
unresolved/fail-closed counts, stuck causes and duplicate-suppression counts.
They do not fail automatically unless they violate a named hard gate.

One `lastIteration=0` smoke supplies no calibration or behavioral trend. Its
timings and coverage are a technical baseline only; no mode-share, score,
cost-distribution or convergence conclusion is authorized.

## Required evidence

Runner returns only to Supervisor:

- exact activation source SHA, parent/ancestry proof and protected-ref checks;
- source snapshot/tree/inventory hashes when snapshot mode is used;
- build command/result plus Java, Maven and MATSim versions;
- new JAR, JDK archive, bundle, deployment-manifest and upload-evidence hashes;
- new release root, run directory, exact launcher command and process identity;
- all seven config/input paths and SHA256 values;
- runtime-JDK executable/version preflight and release checksum results;
- effective smoke config proof including `lastIteration=0` and no formal config;
- exit/completion state, output/log paths and hashes, plus compact Hard Gate,
  Diagnostic and Trend results;
- explicit statements that no formal 50-iteration, calibration or Stage 10+
  work occurred.

## Stop conditions

Stop before or during execution on source/ancestor, artifact, JDK, config or
input hash mismatch; missing runtime dependency; reused release/run identity;
nonzero/incomplete smoke; policy/model ambiguity; economic or missing-data
interpretation; protected-ref change; destructive action; server path outside
the permitted root; or any need for formal 50-iteration, calibration or Stage
10+ work. Report the exact failure identity to Supervisor without retrying.

## Activation next action

Executor pushes this atomic activation and stops. Supervisor performs one
final read-only review. Only after consuming that verdict may Supervisor issue
a separate exact-SHA Runner instruction. This brief alone does not authorize
Runner.
