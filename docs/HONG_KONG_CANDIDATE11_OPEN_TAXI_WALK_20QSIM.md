# Hong Kong Candidate11 open Taxi/Walk 20-QSim run

## Status

This is a completed Candidate11 sensitivity run, not an adopted production
result. It preserves the Candidate11 signal/network/plans/transit inputs used
by run13e and changes only the explicitly listed behavioral and operational
settings.  MATSim endpoint semantics make `firstIteration=0` and
`lastIteration=19` exactly 20 QSim executions.

The first complete-input server attempt was:

```text
/mnt/DiskM/by/hk_stage11_candidate11_open_taxi_walk_20260814_payload18
/mnt/DiskM/by/hk_stage11_candidate11_open_taxi_walk_20260814_release18
/mnt/DiskM/by/hk_stage11_candidate11_open_taxi_walk_20260814_run14a
```

It entered iteration 0 at `2026-08-14T15:32:28+08:00`, completed QSim
iterations 0--8, and then failed before completing the next QSim.  A selected
student reached a 15:30 school-bus boarding leg at 18:34:46.  The old physical
PT guard incorrectly used a planned-time +/-3 h window as part of school-bus
identity and terminated the run at 3 h 4 min 46 s lateness.  `run14a` is an
invalid failed result and remains immutable.

The replacement implementation identifies a selected school-bus leg by the
stable `(person_id, candidate_id, boarding_link_id)` tuple.  Actual time is now
used only to count delayed stop arrivals and missed departures, so missing a
scheduled bus remains a simulated lost/waiting outcome rather than a global
exception.  Candidate ID, boarding link, selected-plan snapshot, physical
school-bus stop, and routing mode remain strict fatal consistency guards.

The corrected immutable replacement attempt is:

```text
/mnt/DiskM/by/hk_stage11_candidate11_open_taxi_walk_20260814_payload19
/mnt/DiskM/by/hk_stage11_candidate11_open_taxi_walk_20260814_release19
/mnt/DiskM/by/hk_stage11_candidate11_open_taxi_walk_20260814_run14b
```

It was launched at `2026-08-14T19:47:40+08:00` with JAR SHA256
`9bc184b7df5742beff1177e7960151e2a7162425d98daf9de2c3d392df3e307b`.
The generated config was checked on the server for 16 global/QSim threads,
iterations 0--19, `stuckTime=3600 s`, and experienced-plan output.  This is
now a completed sensitivity attempt: all 20 QSim executions (iterations
0--19) finished with exit code 0 at `2026-08-14T23:37:04+08:00`.
It entered QSim iteration 0 at `2026-08-14T19:55:09+08:00`.  Iteration 0
completed without a fatal error with `lost=33,140` at 30:00, versus 44,257 in
run14a's iteration 0.  No school-bus candidates are active before the first
protected selection window, so its school-bus/missed-departure counts were both
zero as expected.  Agents still active at the 30:00 simulation end remain
separate from lost agents in all subsequent analysis.

The earlier immutable
attempt `release17/run14` exited before iteration 0 because its release copied
the compact release16 PT mirror, which lacks the adopted light-rail station-OD
parquet.  It is retained as failure evidence.  run14a instead copies the full
PT fare catalog from release11 and dynamic Car tables from release16, matching
the actual run13e provenance split.

## Behavioral contract

- ordinary people retain route, mode, and activity-time innovation;
- `taxi` is included in ordinary `SubtourModeChoice` alongside
  `car,pt,walk`;
- protected household/student people use deterministic joint selection only
  before QSim iterations 5, 10, and 15.  MATSim emits `ReplanningStarts`
  before the QSim with the same iteration number; the failed run14a used
  4/9/14 and therefore applied each decision one QSim too early;
- adult Taxi utility is
  `-9 - 6 * taxi_time_h - 0.10 * fare_HKD`;
- student roles `day_school_student` and `tertiary_student` use
  `-9 - 6 * taxi_time_h - 0.15 * fare_HKD`;
- each main trip receives
  `-3.278342 * max(0, cumulative_walk_h - 1/6)` exactly once; cumulative walk
  includes `walk` and `non_network_walk`, including PT/school-bus access,
  transfer, and egress legs;
- Taxi is a road-coupled proxy with one person-local vehicle, PCU 1, Car link
  access, traffic signals, and the Car travel-time field.  It deliberately has
  no fleet matching, empty cruising, or deadheading and must not be interpreted
  as an operational Taxi fleet model.

The historical `centralV1` Taxi coefficient remains available and unchanged;
the new adult/student policy is activated only by
`--all-person-network-taxi-innovation`.  The Walk component likewise requires
the explicit `--walk-overtime-scoring` switch.  The runner requires these two
calibrated switches together.

## Runtime/output contract

- global threads: 16;
- QSim threads: 16;
- `qsim.stuckTime=3600 s`; run14a accidentally inherited the historical
  `600 s` template value and recorded 43,660--79,863 lost agents at 30:00 in
  its completed QSim iterations;
- `createGraphsInterval=10`;
- `legDurationsInterval=10`;
- `legHistogramInterval=10`;
- `writeTripsInterval=10`;
- `writeEventsInterval=10`;
- `writePlansInterval=10`;
- `writeExperiencedPlans=true`;
- output overwrite policy: `failIfDirectoryExists`.

The launcher is
`scripts/hong_kong_single_city/run/launch_hong_kong_candidate11_open_taxi_walk_20qsim.py`.
It refuses paths outside `/mnt/DiskM/by`, refuses an existing release or run
root, and records the complete command and source roots in `run_metadata.json`.

## Verification completed before launch

- complete Maven test suite: pass;
- focused Taxi/Walk/household tests: 21 tests, zero failures;
- Python launcher syntax: pass locally and on the server;
- derived XML parse and exact key-parameter audit: pass;
- shaded JAR SHA256:
  `1be071ef7927e0bd817143eb523d3319ac0a99134bc66c3eb2faacea3c38b0c8`;
- runtime startup: 385,820 people completed `PersonPrepareForSim`, 47,589 Car
  links received Taxi access, 385,820 PCU-1 Taxi proxy vehicles were assigned,
  and iteration 0 began.

The completed output remains a sensitivity result rather than an adopted
production equilibrium.  Its mode share, delay, stuck-agent, score, and
completion trends must therefore be reported with the completed-output audit
rather than inferred from the successful process exit alone.

## Finite-fleet successor

The next opt-in candidate replaces the run14b person-local PCU-1 Taxi proxy
with a finite, reusable 15,500-vehicle MATSim Taxi/DVRP fleet. It is documented
separately in `docs/HONG_KONG_PHYSICAL_TAXI_DVRP_V1.md`. Run14b remains the
historical no-fleet behavioral baseline for that A/B comparison; it is not
retroactively interpreted as fleet dispatch, waiting, deadheading, or vehicle
reuse.

The successor's 0.5% run25 smoke test exits zero and conserves 2,717 requests,
but the full 5% fixed-plan A/B gate and formal 50-QSim run are still in
progress. The physical fleet is therefore a branch candidate, not current
production or a completed replacement for run14b.
