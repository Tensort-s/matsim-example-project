# Hong Kong experienced PT timetable and day-2 wrap v1

## Status

This is an opt-in, non-production Candidate5B sensitivity. It implements the
two PT supply corrections deliberately separated from the road work:

1. adapt route-stop timing to experienced vehicle arrival/departure delays
   from the completed Candidate5B iteration-0 run;
2. copy the 00:00--06:00 service window to 24:00--30:00 so late first-board
   and transfer demand has a real second-day service opportunity.

The physical Candidate5B road network, QSim road-supply registry, original
Candidate11 plans, no-signal switch, Taxi PCU 0.05, capacity factors 0.1,
`stuckTime=3600 s`, and `removeStuckVehicles=false` are unchanged.

## Builder and representation

The builder is:

```text
scripts/hong_kong_single_city/transit_supply/
  build_hong_kong_experienced_pt_timetable_candidate.py
```

It reads `VehicleArrivesAtFacility` and `VehicleDepartsAtFacility` events from
the prior frozen run and estimates:

```text
experienced delay(route, stop, 15-minute bin)
  = route-stop delay shape + smoothed route/bin shift
```

Departure observations take precedence over arrival observations. Delay
observations are clipped to -300 through 3,600 seconds, route/bin shifts use a
circular five-bin smoother, missing bins use the nearest observed bin, and
missing stops interpolate along the route. Adjusted stop offsets preserve a
minimum 25% of the original inter-stop running time and are made monotonic.

Every original line, route, stop, departure, and vehicle ID is retained. This
is required by exact Hong Kong fare and route lookup. Only wrapped second-day
departures and vehicles receive a deterministic `__day2` suffix. The launcher
accepts `--transit-schedule-input` and `--transit-vehicles-input` only as an
atomic pair, copies them into the immutable release, records both SHA256
values, and clears/rebuilds ordinary PT passenger routes before QSim.

The corrected immutable candidate is:

```text
/mnt/DiskM/by/hk_stage11_experienced_pt_timetable_20260818_candidate2/
  transitSchedule_experienced_day2_v1.xml.gz
  transitVehicles_experienced_day2_v1.xml.gz
  pt_experienced_delay_by_route_stop.csv
  pt_experienced_15min_shift.csv
  pt_departure_time_changes.csv
  pt_day2_departures.csv
  experienced_pt_timetable_candidate_summary.json
```

It contains 5,873 lines, 10,491 routes, 166,845 original departures, and
163,406 original vehicles. All 10,491 routes have experienced observations.
It adds 3,322 departures and 3,322 vehicles for 24:00--30:00. Output totals
are 170,167 departures and 166,728 vehicles. Duplicate departure IDs and
missing vehicle references are both zero. MATSim's supply reader loads the
candidate successfully. The candidate summary SHA256 is:

```text
abde37feb98dccfb8618cc9fb06dd30a1da9a2b4db09f0ded7e16e568823455f
```

The preserved candidate1 failed static MATSim loading before simulation
because millisecond rounding emitted an invalid `14:47:60.000`. The builder
now rounds total milliseconds before splitting hours/minutes/seconds; the
immutable failed candidate was not overwritten or deleted.

## Matched iteration-0 smoke

Release and run:

```text
/mnt/DiskM/by/
  hk_stage11_candidate11_taxi_dvrp_20260818_candidate5b_pttime1_pcu005_it0_release1/
  hk_stage11_candidate11_taxi_dvrp_20260818_candidate5b_pttime1_pcu005_it0_run1/
```

The run exits 0 in 14:58.15, with zero ERROR/OOM records and maximum RSS
25,208,416 KiB. All 3,322 day-2 drivers start; they produce 59,576
`VehicleDepartsAtFacility` events within 24:00--30:00. Runtime road storage
and flow remain exact to the Candidate5B registry.

| Metric | Candidate5B | PT timing + day 2 | Change |
|---|---:|---:|---:|
| Completed / 743,614 | 705,282 | 716,620 | +11,338 |
| Completion rate | 94.8452% | 96.3699% | +1.5247 pp |
| Raw mean completed time | 44.539 min | 42.927 min | -1.612 min |
| PT completed | 513,201 | 527,212 | +14,011 |
| PT completed mean | 42.833 min | 40.920 min | -1.913 min |
| Waiting before first PT boarding | 17,148 | 10,623 | -6,525 (-38.05%) |
| Unfinished onboard/transfer | 2,608 | 3,409 | +801 (+30.71%) |
| Combined unresolved PT states | 19,756 | 14,032 | -5,724 (-28.97%) |
| All-link blocked seconds | 969,862 | 959,269 | -1.09% |
| Active entities at 30:00 | 24,971 | 20,187 | -4,784 |

Across 693,388 trip IDs completed in both runs, the candidate is 1.746
minutes faster. Among same-mode common trips, PT is 2.136 minutes faster, Car
0.036 minutes faster, Taxi 0.093 minutes slower, and Walk/Car passenger are
unchanged. The new schedule changes the routed main mode for some common trip
IDs: 4,454 move from Walk to PT and 1,701 from PT to Walk. This is a real
schedule-availability response, so the audit reports an explicit transition
matrix rather than rejecting mode changes.

The increase in onboard/transfer-at-horizon is not hidden. The accepted gate
uses the sum of waiting-before-board and onboard/transfer because added
second-day service can legitimately move a passenger between those states;
the sum must fall at least 25%, while both components remain separately
reported. It falls 28.97%, so this is a net reduction rather than only a state
transfer. The corrected v2 acceptance summary passes all technical and smoke
performance gates but remains non-production:

```text
.../pt_timing_smoke_acceptance_v2/
  experienced_pt_timetable_smoke_summary.json

SHA256:
3b217ac25b5b272c75a87c1746bf64ba2b585d08e62db6c83b1cf808396584cc
```

## Candidate5B plus Candidate11 signals follow-up

A second frozen iteration-0 test holds the Candidate5B physical network and
road-supply registry, Candidate11 safe-boundary TOD signal XML, original
selected demand, 15,500-vehicle Taxi fleet, Taxi PCU 0.05, and QSim settings
fixed. It replaces only the PT schedule/vehicles with the experienced-time
candidate and invokes `--clear-pt-routes`, so ordinary PT temporal itineraries
in the plans are rebuilt against the corrected service. Activity times and
selected main modes are not directly shifted by the calibration.

```text
/mnt/DiskM/by/
  hk_stage11_candidate11_taxi_dvrp_20260818_candidate5b_signal_pttime1_pcu005_it0_release1/
  hk_stage11_candidate11_taxi_dvrp_20260818_candidate5b_signal_pttime1_pcu005_it0_run1/
```

The run exits zero in 18:02.68 with no ERROR/OOM record. Relative to the
matched Candidate5B plus Candidate11-signals run with the original PT supply:

| Metric | Original PT time | Calibrated PT time | Change |
|---|---:|---:|---:|
| Completed / 743,614 | 722,568 | 732,075 | +9,507 |
| Completion rate | 97.1698% | 98.4483% | +1.2785 pp |
| Raw mean completed time | 46.213 min | 44.570 min | -1.642 min |
| Common-trip mean change | -- | -- | -1.809 min |
| PT completed | 527,346 | 539,594 | +12,248 |
| PT completed mean | 44.417 min | 42.463 min | -1.954 min |
| Waiting before first PT boarding | 10,547 | 5,592 | -4,955 |
| Unfinished onboard/transfer | 0 | 152 | +152 |
| Combined unresolved PT states | 10,547 | 5,744 | -45.54% |
| Active entities at 30:00 | 10,913 | 6,900 | -4,013 |
| All-link blocked seconds | 1,039,023 | 1,049,139 | +0.974% |

All 3,322 second-day drivers execute and produce 62,011 facility departures
within 24:00--30:00. Taxi accounting remains conserved (43,798 submitted =
43,791 completed + 2 waiting + 0 onboard + 5 rejected), and Candidate5B
storage/flow values remain exact at runtime. The signal system, group, and
control file paths are identical to the prior signal run.

The passenger-level performance gate passes. A subsequent event-to-schedule
audit resolves the apparent increase from 9 to 850 regular-PT road-state
`stuckAndAbort` events: all 850 occur exactly at the 30:00 QSim shutdown, 843
belong to wrapped second-day services, and 840 of those 843 have scheduled
terminal times after 30:00. Only three wrapped services were scheduled to end
before the horizon, by 8.9--56.4 seconds. Original-service road-state aborts
fall from 9 to 7. The 850 count is therefore a horizon-censoring diagnostic,
not evidence of 850 pre-horizon road timeouts. Passenger waiting/onboard states
remain real incomplete outcomes and are not removed from completion accounting.

Machine-readable acceptance output:

```text
...candidate5b_signal_pttime1_pcu005_it0_run1/
  signal_pt_timing_acceptance_v3/experienced_pt_timetable_smoke_summary.json

SHA256:
097a4a18323044e5089263be6a683f770004361b33a596a0da49907d9e579b93
```

The first full audit output is preserved as immutable source evidence. Its
zero-denominator onboard/transfer ratio was emitted as non-standard JSON
`Infinity` because the baseline count was zero and the candidate count was
152. Acceptance v3 reuses the simulation and full event audit without rerun,
serializes that undefined ratio as JSON `null`, records both source hashes,
and leaves every count, gate, and interpretation unchanged.

The follow-up planned-main-mode denominator audit reads the actual iteration-0
routed plans rather than dividing mode totals by all trips. Completion is Car
99.7357%, Car passenger 100%, PT 98.0384%, Taxi 99.5273%, and Walk 99.9439%.
It also records 16,019 planned-PT trips completed as pure Walk after routing
and one planned-Taxi zero-distance Walk fallback. The machine output is
`mode_completion_by_planned_mode_v1.json`, SHA256
`282f787222b56339555b7aa89670cbd90be652e6b22a10bfab981e2f590eee10`.

The immutable horizon attribution is stored under:

```text
/mnt/DiskM/by/hk_stage11_candidate5b_signal_pt_stuck_audit_20260819_v1/
  analysis_v2/pt_horizon_stuck_summary.json
  analysis_v2/candidate_pt_horizon_stuck.csv
```

The joined events are dispersed across 572 routes and 723 road links; the
largest route count is seven and the largest link count is nine. This further
rules out a single PT road-network hotspot as the explanation. Formal 30-hour
runs must report pre-horizon road stuck, horizon-censored PT vehicles, and
unfinished passengers as three separate outcomes.

## Active 50-QSim sensitivity

The first formal Candidate5B plus Candidate11 signals plus calibrated-PT
attempt started on 2026-08-19 using the original no-experienced-Taxi-score
Candidate11 plans, 15,500 physical Taxi vehicles at PCU 0.05, 16 threads,
`stuckTime=3600 s`, retained stuck vehicles, and a fixed 00:00--30:00 QSim
horizon. Innovation ends after iteration 34; protected joint selection occurs
before QSim 5, 15, 25, and 35.

```text
/mnt/DiskM/by/
  hk_stage11_candidate11_taxi_dvrp_20260819_candidate5b_signal_pttime1_formal50_payload1/
  hk_stage11_candidate11_taxi_dvrp_20260819_candidate5b_signal_pttime1_formal50_release1/
  hk_stage11_candidate11_taxi_dvrp_20260819_candidate5b_signal_pttime1_formal50_run1/
```

The first shaded JAR SHA256 is
`5c56c5c3c817adceee051b5ea081f30eeb5535c01d30595f2733f0e5e52fd8b9`.
Run1 completed iterations 0--8 and failed during iteration 9. MATSim 2026.0's
default teleportation engine concurrently mutated a plain `PriorityQueue` and
visualization `LinkedHashMap` under the 16-thread QSim. The queue comparator
encountered a transient null heap slot and raised a `NullPointerException`.
MATSim completed unexpected-shutdown callbacks, but its non-daemon memory
observer kept the JVM PID alive; the old heartbeat's process-only liveness
rule therefore misclassified the failed simulation as running. After exact
PID/command verification the residual process was terminated; run1 is
preserved with exit code 143.

Run2 started on 2026-08-20 in new immutable directories:

```text
/mnt/DiskM/by/
  hk_stage11_candidate11_taxi_dvrp_20260820_candidate5b_signal_pttime1_formal50_payload2/
  hk_stage11_candidate11_taxi_dvrp_20260820_candidate5b_signal_pttime1_formal50_release2/
  hk_stage11_candidate11_taxi_dvrp_20260820_candidate5b_signal_pttime1_formal50_run2/
```

Its shaded JAR SHA256 is
`6911ffcea769dde3a14aab9ffa8e9eef4fb0e7e690279d7050879c5257cd86de`.
Run2 completed iterations 0--4 and the iteration-5 protected joint selection,
then stalled near QSim 15:00. A saved `jcmd Thread.print -l` reported one
Java-level deadlock: the main thread held the teleportation-engine monitor
while waiting for the QSim state monitor, and an events worker held the QSim
state monitor while entering the teleportation engine. The coarse
whole-method synchronization added after run1 had made the two mutable
collections safe but inverted these locks. The exact run2 JVM was terminated
after its PID, command, process tree, and deadlock were verified; the immutable
run is retained with exit code 143 and the thread dump at
`heartbeat_thread_dump_20260820T0249.txt`.

Run3 started in new immutable `payload3`, `release3`, and `run3` directories.
Its shaded JAR SHA256 is
`fb9457792d15efe98e695522755c50888dda1fa9eed85e1923d1ba42f3728897`.
The engine now protects only its internal queue and map with a dedicated lock,
and releases that lock before emitting events or calling QSim callbacks. A
direct lock-inversion regression, the focused Taxi tests, and the complete
181-test Maven suite pass. The heartbeat also treats an explicit JVM deadlock
as an interruption even when the PID remains alive. Run3 is the active
sensitivity and is not an adopted production run.

## Limitations and next gate

The timing model is calibrated from one Candidate5B iteration-0 realization,
not official observed stop timestamps. More than three million raw stop-delay
events hit the conservative clipping bounds; the fitted departure shifts are
nevertheless small for most services, but this tail needs route-level review.
The candidate also uses one new vehicle for every wrapped departure rather
than a verified next-day vehicle block. The active 50-QSim sensitivity tests
timing stability and PT route-choice feedback. Production adoption still
requires review of vehicle-block realism and passenger outcomes; scheduled
second-day vehicle tails at 30:00 remain explicitly right-censored rather than
being interpreted as road stuck.
