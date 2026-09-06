# Hong Kong current status and handoff

## 2026-09-06: GradeV6 Walk 20–30 minute slope run completed

For the requested interpretation of congestion, identity-specific boarding
counts/shares and completed-trip durations against TCS, see
[GradeV6 audit results and analysis](HONG_KONG_GRADEV6_AUDIT_RESULTS.md).
The report preserves all five identity groups, separates event counts from
completed main trips, and documents the TCS and censoring scope limitations.

**FULL-SCOPE AUDIT COMPLETED — 2026-09-06 11:38:27 +08:** verified at 12:09.
All four follow-up stages finished and full_audit_exit_code.txt is 0;
analysis1/status.json reports **COMPLETED_WITH_FINDINGS**. Total elapsed time
from base launch was about 13 minutes. This supersedes the startup record below.
All 385,820 persons and 719,048 completed trips were identified; planned-trip
denominator is 750,967. No unknown boarding vehicles or unknown completed-trip
persons; Taxi boardings match completed requests in every identity group.
Selected pairs: 15,249 (7,896 ride-along, 7,353 home escort), zero pairing errors
or duplicate passenger demands. Flow/storage implementation mismatches are zero.

Outstanding model findings: PT event audit records 15,777 unfinished waiting
legs and 363 unfinished aboard legs (censored observations, not unique-person
counts), plus final-iteration stuck events. No event-state parsing anomalies
were detected. Taxi requests: 84,296 completed, 11 still waiting. Road blocked
inflow is 82,422 link-seconds on 311 links, versus GradeV5 77,436 on 305 links;
final-iteration turn-warning occurrences 44 versus 40. These occurrence counts
are not unique failed vehicles. Audit completion does not mean model validation
passed without findings. Local compact copies are under
`tmp/gradev6_full_audit_results/`; full summary is `summary.json`.

**Historical audit startup — 2026-09-06 11:25:29 +08:** the base audit ran in
`/mnt/DiskI/by/hk_stage11_candidate11_taxi_dvrp_20260906_gradev6_walk030_cap052_t32_audit1`,
worker PID 145852. At 11:31 it had parsed 719,048 completed main trips and
was streaming boarding events. The follow-up worker PID 146418 started at
11:30:52 and automatically waits for base exit code 0 before executing
identity/TCS/version comparison, trip/Taxi/road summaries, exact selected
driver/passenger pairing checks, and PT event waiting/stuck/censoring analysis.
It is a real background pipeline, not a pending intention.

Follow-up source: `scripts/hong_kong_single_city/run/audit_hong_kong_gradev6_followup.py`;
local/server SHA256 match:
`15190719a7c5675693b4bf516e1a6ba8fb3b47f23c324737c3030857fdb5a670`.
Python --help/syntax check passed; all follow-up stages subsequently exited 0.
All source simulation files are read-only; new writes stay inside this audit1.
Base completion uses `exit_code.txt`; full follow-up completion uses
`full_audit_exit_code.txt`, `full_audit_finished_at.txt`, `full_audit_job.json`
and `analysis1/status.json`. Do not confuse base completion with full completion.
Detailed outputs are in `analysis1`; findings and known limits are retained,
including no matched-OD counterfactuals, no inferred denial-event counts from
long waits, and no claim of complete vehicle occupancy/spacetime continuity.
Finishing the audit does not imply calibration acceptance or zero defects.
Initial estimated elapsed time: 30–60 minutes, subject to I/O and findings.

**COMPLETED — verified 2026-09-06 11:20 +08:** all 32 iterations (0–31)
finished. Worker finished at **10:31:28 +08**, exit_code.txt and time exit
status both 0; worker/Java PIDs have exited. Elapsed time **8 h 58 min 40 s**,
zero swaps. Final average executed score is 23.421020378325736; the scoring
function changed, so the increase over GradeV5 is not an independent quality metric.

Iteration-31 main-mode shares (modestats): Car 12.0149%, Car passenger 2.0306%,
PT 66.5888%, Taxi 11.4744%, Walk 7.8913%. Compared with GradeV5 final Walk
7.1115%, Walk rises 0.7798 pp; PT falls 0.5199 pp and Taxi falls 0.1628 pp.
These are not TCS boarding shares.

Read-only streaming of final trips.csv gives 719,048 completed rows versus
718,859 under GradeV5. Means in minutes (GradeV5 → GradeV6): all completed
trips including Walk 52.1949 → 52.0862; mechanised 54.4159 → 54.5234;
actual PT 57.5406 → 57.8071; Taxi 77.3927 → 77.0576; Walk 23.7729 → 24.3052.
PT wait 25.3424 → 25.4686; completed-Taxi wait 57.6845 → 57.1621.
Actual-PT classification includes school bus routed as pt; do not mix these
means with planned-main-mode identity summaries. Completion denominators and
person composition can change; these are not matched-person causal estimates.
The pure-walk relaxation changes allocation but does not materially reduce
overall completed-trip time. Group/TCS, road and household audits for GradeV6
have not been completed by this snapshot. Raw compact result and reproduction:
`tmp/gradev6_result_snapshot.json`, `tmp/gradev6_result_snapshot.py`.

The user requested a new 32-iteration run with the pure-walk marginal penalty
between 20 and 30 minutes reduced from 1.15 to 0.30 util/min. GradeV6 preserves
the other slopes (0.10, 0.15, 5.15 util/min), PT/Taxi waiting -12 util/h,
real PCE, flow/storage 0.52, 32 threads and the same neutral initial plans.
Its continuous walk formula is
`2 - 0.10*t - 0.05*max(t-10,0) - 0.15*max(t-20,0) - 4.85*max(t-30,0)`.

Started **2026-09-06 01:32:48 +08**, worker PID **71404**, Java PID **71406**:
`/mnt/DiskI/by/hk_stage11_candidate11_taxi_dvrp_20260906_gradev6_walk030_cap052_t32_run1`.
At 01:34 the live Java process was preparing persons/routes (historical startup
observation, superseded by completion above). Source commit `3a84e9b779c2bcc0dc3952257fc59289b59a5505`, JAR SHA256
`7006fa76ec5396c1f18ba314e11d9dd5851797cba86c5ef0b08dc49dd0dbe0a3`.
18 Java and 41 Python checks passed. Server payload checks and prelaunch
GradeV5 parameter comparison passed; all 24 non-JAR SHA256 metadata fields
match GradeV5. New payload/release/run/operations directories are separate;
all server writes remain under the session-authorized `/mnt/DiskI/by`.
See the [GradeV6 implementation and launch record](../tmp/hk-wait12-walk20-real-pce/docs/HONG_KONG_GRADEV6_WALK030.md).
This remains an independent sensitivity, not a production adoption.

## 2026-09-05 follow-up: GradeV5 implementation

**BASIC AUDIT COMPLETED — 2026-09-05 23:33:37 +08:00:** final-iteration population/main-trip/
physical-boarding/Taxi-reconciliation audit finished with exit code 0 in
`/mnt/DiskI/by/hk_stage11_candidate11_taxi_dvrp_20260905_gradev5_cap052_t32_audit1`,
elapsed 328.19 seconds; worker PID `62085` has exited. Source simulation files are read-only. This first stage
does not yet complete PT wait decomposition, road/turn-warning, household-pairing
or GradeV4 comparison analysis. See audit_job.json and audit_stdout_stderr.log.
The job JSON's starting-state label is historical; completion is established by
exit_code.txt, finished_at.txt and the completed result files.

**IDENTITY/TCS RESULTS — 2026-09-06:** five population groups have boarding
shares and completed-trip durations. The additional expanded-trip-weighted
duration comparison is now complete: household-resident mechanised trips
52.72 versus TCS 42 minutes; private vehicle + Taxi 43.96 versus 31;
PT + school bus excluding Taxi 56.17 versus 45; overnight visitors 66.50
versus 41. Visitor reference data are from the 2023 survey, with overnight
reference coverage limited to hotels/guesthouses. See the
[GradeV5 identity/TCS results and scope limitations](HONG_KONG_GRADEV5_TCS_IDENTITY_RESULTS.md).
This completes this specific comparison, not the full audit. Later tables in
this handoff describing PCE 0.195 remain historical GradeV4 results.

**GRADE COMPARISON / PT CSV DIAGNOSTIC — 2026-09-06:** both iteration-31
trips/legs outputs have now been streamed read-only. Overall TCS-adjusted MTR
boarding share is 27.779% (GradeV4) versus 27.549% (GradeV5); household MTR
27.219% versus 26.955%. Mean completed trip time falls 54.381 to 52.195 minutes
(including walk); actual-PT trip mean falls 59.483 to 57.541, with reported
waiting 28.078 to 25.342. GradeV5 MTR legs wait 2.672 minutes on average,
but MTR + bus/GMB itineraries wait 50.832 minutes across their whole trip.
This supports examining feeder/transfer chains; it is not an OD-matched
causal comparison or a completed event-level waiting/denied-boarding audit.
Waiting, pure-walk and road-capacity changes were simultaneous, so the
independent waiting-coefficient effect is unidentified. Detailed evidence
and reproducible local scripts are linked in the identity/TCS results above.

**COMPLETED — verified 2026-09-05 23:20 +08:00:** the GradeV5 DiskI run1
completed all 32 iterations (0–31). Iteration 31 ended at 22:09:06; the worker
finished at **22:10:24**, with both `exit_code.txt` and `/usr/bin/time` reporting
**0**. Elapsed time from launch was approximately **6 h 22 min 04 s**. Final
average executed score is **22.93594451796484** (iteration 27: 22.474752296551372).
Maximum resident set size was 70,313,260 KiB (about 67.1 GiB), with zero swaps.
The Java process has exited. This supersedes the running status below.
Population/boarding/completion results are now available as linked above;
PT/Taxi-wait decomposition and road-warning audits remain pending.
Successful execution is not production adoption or proof of convergence.

**RUNNING — 2026-09-05 15:48:20 +08:00:** after the user confirmed DiskM
was remounted and requested execution, all required source inputs were read
from DiskM and copied/hash-verified into DiskI (651 files). Real PCE conversion
passed for all 86,417 road links. The new run is now started at
`/mnt/DiskI/by/hk_stage11_candidate11_taxi_dvrp_20260905_gradev5_cap052_t32_run1`,
worker PID `9862`, source commit `fbd747e129013977e1a441a2e6a24046deccc4e3`.
Its metadata verifies GradeV5, 32 global/QSim threads, iterations 0–31,
flow/storage 0.52, and Taxi PCE 1. The Java process (PID `9864`) passed initial
input/road-registry validation and entered iteration 0 QSim; at around 15:56,
simulation time reached 09:00 with lost=0. Two brief SSH connection timeouts
were followed by successful reconnection and continuous simulation logs. No completion or
production adoption is claimed. This supersedes the earlier missing-input
status preserved below. All runtime paths and writes remain within DiskI/by.

**Latest location update:** the user authorized this run only inside
`/mnt/DiskI/by`. The directory is accessible and was initially empty. The
new payload
`/mnt/DiskI/by/hk_stage11_candidate11_taxi_dvrp_20260905_gradev5_cap052_t32_payload1`
now contains the validated JAR, launcher/conversion scripts, source-change
snapshot, and hash-matched network/Taxi-wait crosswalk. All 25 payload files
passed server SHA256/size checks. No simulation has started: the latest full
plans, facilities, supply registry, joint catalog and runtime input bundle
are missing. Local backup searches did not find a complete matching set.
See the candidate record linked below for exact missing inputs and path guards.
This supersedes the previous plan to deploy on DiskM; no server access outside
DiskI/by was performed in this latest task. Python regression/path tests: 41 pass.

The user subsequently specified **flow/storage factors 0.52, global/QSim
threads 32, and 32 QSim iterations (0–31)**. The candidate now implements these
settings, with explicit storage/floors scaled by 5.2 (+1.4% supply versus exact
PCE normalization). The server run is authorized but has NOT started:
read-only `ls` and `df` checks now report `Input/output error` for the entire
permitted root `/mnt/DiskM/by`, not only the previous release directory.
The server filesystem must become accessible before deployment can proceed.

The requested common PT/Taxi waiting coefficient (−12 util/h), 10–20/20–30
minute walking brackets, and restoration of real road PCE with equivalent
flow/storage scaling are implemented in the separate worktree
`F:/Matsim/worktrees/hk-cost-integration/tmp/hk-wait12-walk20-real-pce`, branch
`codex/hk-wait12-walk20-real-pce`, based on experiment source `5a2a82c`.
See the [candidate implementation and validation record](../tmp/hk-wait12-walk20-real-pce/docs/HONG_KONG_GRADEV5_WAIT_WALK_REAL_PCE.md).
This is a local worktree link and requires that worktree to be present.

Code and local tests are complete. The latest server `release2` input directory
returned `Input/output error` during read-only access, so real full-network
derived inputs and a new simulation are still pending. No production adoption,
server deployment, or integration/master merge has occurred. Existing results
below remain the previous experiment results.

## Purpose and authority

This is the first Hong Kong status file to read in a new Codex conversation.
It records the state verified on 5 September 2026 and separates three things
which must not be conflated:

1. the adopted production baseline in `cities/hongkong/city.yaml` and
   `runs/hongkong/run_manifest.json`;
2. the latest completed server sensitivity experiment; and
3. code and data currently present on this integration branch.

`docs/HONG_KONG_FINAL_WORKFLOW.md` remains the end-to-end authority for the
adopted workflow. Server paths below are immutable evidence under
`by@100.103.8.34:/mnt/DiskM/by`; they are not local Git artifacts.

## Current adopted production baseline

The production baseline is still `formal_50it_ptfixed_ferry_activity`. It uses
the Ferry Core v1 supply, 10% PT passenger capacities, 5% Bus/GMB road PCU,
road flow/storage factors of 0.1, the v2 multi-activity plans, and 50 MATSim
iterations. None of the GradeV4, Parking V2, 32,332-private-vehicle,
JointRelax, Taxi-wait-prediction, or balanced-PCE experiments below has been
adopted as the production output.

## Latest completed sensitivity

The latest technically successful experiment is:

```text
experiment = CAL-GV4-PV32332-JOINTRELAX-TAXIWAIT-PCE0195-01
plans      = PLAN-PV32332-DEMAND30-A4-FEASIBLE-01
profile    = score-gradev4-pv32332-jointrelax-taxiwait-pce0195-32
run        = /mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260904_gradev4_pv32332_jointrelax_taxiwait_pce0195_run2
audit      = /mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260904_gradev4_pv32332_jointrelax_taxiwait_pce0195_audit3
analysis   = audit3/analysis3
```

The run completed iterations 0--31 with exit code 0. `audit3/analysis3` is the
authoritative audit; `analysis1` and `analysis2` are retained construction
drafts and must not be cited.

| Provenance item | Value |
|---|---|
| Source Git commit | `5a2a82cc8c96e639597c84b2c9fde4ce7f1bcca8` |
| Shaded JAR SHA256 | `0aeefaa6381035b5fc92dc314d15b9b09d45de1033b716f9ea0c0975bd892423` |
| Prepared plans SHA256 | `e14e93be85ade9e081a9b26a3530fd68d133fabab5b0d1dc93df135cbe4a8552` |
| Facilities SHA256 | `3431caa6f3fc0f7b62e9225ee6b4f68ef82a5b6611d6dd2764f240a9f935f503` |
| Private vehicles SHA256 | `ffd4d86caaf3dcc65d368ba9e9b5b2cbb93237cc62908db440c75c2ce5a6851c` |
| Transit vehicles SHA256 | `1a3ecc73653bc91525ce2baf420f2d5cff859c17a4b632b2f08e3a74ee84b285` |
| Candidate catalog SHA256 | `a9ad8b460a9127408d615c4cdf6e43eb09c54078e48ab2b084c976dc3ae5f737` |
| Run metadata SHA256 | `c8a810ea79f13d9bc9bf77a386511cde52b6948f61d5f3a57b1a7f0bcbc964f2` |
| Audit manifest SHA256 | `25bd07d7405c25eb539c657b48e286e42abed0490296af3c16152b230ea9c674` |
| Authoritative analysis SHA256 | `917ecd8f19fc535014e761a9766938869b84a9ae1c37f6b154bcd2cd0055e3ca` |

### Experiment contract

- 385,820 people and 32,332 bound private vehicles: 28,571
  `private_car` plus 3,761 `motorcycle`;
- GradeV4 scoring, Parking V2, non-school-bus BusCap20, 3,100 physical Taxi
  DVRP vehicles, 16 threads, and a 30:00 QSim horizon;
- ordinary innovation in iterations 0--19, selection only in 20--31, and
  atomic household joint selection in 5, 15, and 25;
- relaxed household policy `unified-pv32332-home-escort-v2-relaxed`;
- Taxi-wait forecast policy `previous-iteration-tcs26-30min-v1`, using exactly
  iterations 4, 14, and 24 for selections 5, 15, and 25;
- road flow and storage factors remain 0.1, while road occupancy uses
  `private_car=0.195`, `Taxi=0.195`, `motorcycle=0.078`, full-size
  `Bus=0.39`, and `GMB=0.2925`.

The run used the Candidate11 traffic-signal path. This is an important branch
boundary: traffic-signal work is closed in the current Car-focused integration
worktree, while the server sensitivity came from the separate Taxi DVRP
development history. Do not infer that the current branch contains or adopts
the complete runtime implementation identified by the source commit above.

### Iteration-31 outcome

Main-mode shares use one complete activity-to-activity trip per denominator.
They are not TCS boarding shares.

| Main mode | Share | Planned trips | Completed trips | Completion | Completed mean duration |
|---|---:|---:|---:|---:|---:|
| Car | 12.080% | 106,720 | 103,292 | 96.788% | 20.74 min |
| Car passenger | 2.127% | not separately exposed by the trip summary | not separately exposed by the trip summary | see atomic-pair audit | see group audit |
| PT | 67.460% | 506,725 | 476,479 | 94.031% | 59.57 min |
| Taxi | 11.994% | 90,197 | 88,085 | 97.658% | 82.54 min |
| Walk | 6.339% | 38,647 | 37,685 | 97.511% | 19.11 min |

School bus is classified separately in the trip audit: 8,916 planned, 8,905
completed, 99.877% completion, and 37.64 minutes mean duration. Average
executed score reached 22.586 in iteration 31; the last five values rise from
22.069 to 22.586, so the run is much more stable than the original congested
JointRelax attempt but still shows modest score movement at the endpoint.

The final selected set has 15,978 valid atomic household pairs: 8,387
ride-along and 7,591 home-escort. All candidate IDs are known and every active
candidate has one driver and one passenger selected as a pair. The candidate
catalog contains 47,649 rows, 14,555 households, and 41,071 passenger demands.

### Road and Taxi result

Balanced PCE removes the pathological road state of the original JointRelax
configuration, but it does not solve Taxi calibration:

- iteration-31 blocked inflow is 58,829 seconds on 320 links and 21,219 agents
  remain active at 30:00;
- relative to the original JointRelax run, blocked inflow falls 99.836% and
  terminal active agents fall by 63,038;
- Taxi request conservation is exact: 87,997 behavioral submissions equal
  87,986 completed plus 11 waiting, with zero onboard and zero operational
  shadow requests;
- right-censor-aware Taxi wait mean/P50/P90/P95 is
  62.84/57.25/126.18/134.25 minutes; 42,597 requests wait at least 60 minutes,
  13,038 at least 120 minutes, and 9 at least 180 minutes.

The one-round iteration-32 replay recorded 45,499 active agents and 881,204
blocked seconds. It reused an old final plan and is directional diagnostic
evidence only, not a converged equilibrium or a replacement for the 32-round
result.

## TCS 2022 comparison contract

The official comparison source is the Transport Department
[Travel Characteristics Survey 2022 Final Report](https://www.td.gov.hk/filemanager/en/content_5349/tcs2022_eng.pdf).
Always distinguish:

- **main-mode share**: one mode per complete activity-to-activity MATSim trip;
- **mechanised main trip**: a complete trip excluding Walk;
- **boarding share**: physical passenger boardings; one trip may board more
  than once; and
- **TCS-adjusted boarding**: repeated MTR boardings inside one modeled main
  trip are collapsed as a paid-area interchange proxy.

For resident-household agents, the model has 1.455 TCS-adjusted boardings per
completed mechanised trip, versus the TCS reference 1.118. Comparing the
iteration-31 resident-household boarding denominator with TCS gives:

| Boarding category | Model | TCS | Difference |
|---|---:|---:|---:|
| Ferry | 0.172% | 0.709% | -0.536 pp |
| Franchised bus | 34.298% | 26.456% | +7.842 pp |
| Light Rail | 1.519% | 3.111% | -1.592 pp |
| MTR | 27.219% | 31.650% | -4.431 pp |
| Private vehicle | 11.234% | 13.977% | -2.743 pp |
| Public light bus | 15.907% | 11.394% | +4.512 pp |
| Special-purpose bus | 1.212% | 5.643% | -4.431 pp |
| Taxi | 8.440% | 6.062% | +2.377 pp |
| Tram | 0.000% | 0.991% | -0.991 pp |

Private vehicle plus Taxi is close in aggregate (19.673% modeled versus
20.039% TCS), but the internal allocation is wrong: too much Taxi and too
little private vehicle. Franchised bus and public light bus are high, while
MTR, special-purpose bus, Light Rail, ferry, and tram are low or absent.

Identity-specific completed-trip durations show that aggregation hides large
differences:

| Population group and mode | Model mean | Closest TCS target | Difference |
|---|---:|---:|---:|
| Resident household, all completed mechanised trips | 54.67 min | 42 min | +12.67 min |
| Resident private vehicle plus Taxi | 46.60 min | 31 min | +15.60 min |
| Resident PT excluding Taxi | 57.91 min | 45 min | +12.91 min |
| Overnight visitor, all completed mechanised trips | 70.41 min | 41 min | +29.41 min |
| Same-day visitor, all completed mechanised trips | 89.31 min | no comparable published mean | not applicable |

The detailed modeled means are resident household: private vehicle 20.74,
PT 58.32, school bus 37.62, Taxi 80.95, and Walk 19.01 minutes; overnight
visitor: PT 60.15, Taxi 94.85, and Walk 21.54 minutes; same-day visitor: PT
85.05, Taxi 102.14, and Walk 12.20 minutes. Visitor boarding shares also remain
far from TCS: overnight Taxi/hired-car is 24.74% versus 12%, and same-day is
18.45% versus 11%. The model has no visitor private-car implementation.

The boarding audit still has declared limitations: a fare-gate event is not
available for exact MTR paid-area transfer recognition; modeled
special-purpose bus is narrower than TCS; and hired cars plus some tourist and
company buses have no exact modeled counterpart.

## Why long-wait Taxi users do not all switch

A read-only final plan-memory diagnostic found that among 42,597 Taxi requests
waiting at least 60 minutes, 9,238 (21.7%) have no non-Taxi alternative in the
effective final plan memory, 8,564 (20.1%) have a stored alternative with a
better whole-day score, and 24,795 (58.2%) have alternatives whose stored
whole-day score is worse. Alternative coverage is 69.7% PT, 27.6% Walk, 3.6%
Car, and 1.6% Car passenger; categories overlap. Only 7.2% of these long-wait
requests belong to agents with `carAvail=always`.

This supports two simultaneous causes: effective alternatives are absent for
some users, especially visitors, while many available alternatives remain
less attractive under the stored score history. These are plan-memory scores
from different iterations, not synchronized counterfactual utilities, so the
diagnostic is directional and should not be promoted to a causal estimate.

## Joint-selection failure prevention

Several earlier immutable attempts failed at joint rounds because facilities,
parking zones, waypoint routes, passenger plans, proxy links, or vehicle IDs
were stale after selection or full private-vehicle reallocation. The fixed
contract is intentionally small:

1. immediately before each joint selection, restore every candidate driver
   and passenger to an unlabelled canonical plan;
2. install only that round's winning driver/passenger plans atomically; and
3. at submission, pre-QSim, iteration end, and shutdown, require every active
   candidate ID to have exactly one selected driver and passenger, with no
   invalid or historical ID left in any selected plan.

For a full vehicle reallocation, a candidate must use the driver's current
immutable `private_car` mapping. An old catalog vehicle ID must never be
executed; motorcycle, no-car, or missing-current-vehicle drivers make that
candidate infeasible. Border and outside-TCS parking must use the immutable
`new_territories_lantau` zone-group override and the same Parking V2 hourly
rates and event cap; do not fabricate a TCS zone.

The relaxed thresholds used by the latest sensitivity are departure-time
difference at most 3,600 seconds, net added geometric distance at most 15 km,
and routed-to-direct distance ratio at most 2.0 for detour ride-along. A home
escort requires the home to be within 5 km of at least one passenger trip end
and a static 25 km/h loop estimate of at most 5,400 seconds; runtime routing
then requires the loop to fit inside the driver's home window and pass utility
selection.

## Current integration-branch work

This integration branch now also contains a separate, non-adopted 2026 parking
supply candidate under
`data/transport_costs/hongkong/parking_supply_2026_v1/`. It unifies 9,456
official private-car meter poles and 569 off-street car parks. Capacities,
tariffs, source snapshots, a static map, and build QA are versioned, while live
vacancy is kept as a dynamic feed reference. Nearest Car links remain
direction-unverified candidates and are not routing or scoring inputs. See
`docs/HONG_KONG_PARKING_SUPPLY_2026.md`.

The same branch records a run68 no-signal road congestion re-audit in
`docs/HONG_KONG_NO_SIGNAL_ROAD_RUNTIME_AUDIT.md`: 48,459.486 road-vehicle
delay hours and 1,770 stuck events, both lower than run62, with the residual
mainly concentrated in evening congestion and a bounded set of local
short-connector, bus-access, and junction-neighbourhood checks.

## Decisions and next safe actions

- Treat the latest PCE 0.195 result as a successful sensitivity, not a new
  production baseline and not Candidate12.
- Do not mix the server experiment's Taxi-branch implementation with this
  integration branch by assumption. Before implementation work, inspect the
  intended worktree, branch, source commit, dirty files, and dependency
  commits, then use an explicit merge or cherry-pick decision.
- If calibration continues, first decide whether the balanced PCE semantics
  are scientifically acceptable. Then target the remaining Taxi wait,
  resident/visitor mode allocation, transfer count, and long PT duration
  errors without changing several mechanisms in one unidentifiable run.
- If the real-facility parking candidate is advanced, entrance/exit direction,
  legal turns, same-vehicle continuity, and runtime availability must pass
  before it replaces the current Parking V2 proxy.
- New server runs require a new immutable payload/release/run/audit chain and
  explicit authorization. Historical directories must not be overwritten,
  moved, deleted, or cited after they have been superseded.
