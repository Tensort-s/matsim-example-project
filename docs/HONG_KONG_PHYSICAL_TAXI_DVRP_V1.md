# Hong Kong physical Taxi DVRP v1 candidate

## Status and modelling boundary

This document defines the opt-in physical Taxi/DVRP v1 candidate developed on
branch `codex/hk-taxi-dvrp-v1`. It is not an adopted production input, final
simulation, or replacement for the current Hong Kong production scenario. The
low-cost `run25` technical experiment and the full-population fixed-plan A/B
gate have completed successfully. The formal 50-QSim run4 is active. No result below promotes Candidate11 signals or this Taxi fleet into
`current_model` or `current_final_run`.

The candidate replaces the earlier person-local PCU-1 Taxi proxy with a finite,
reusable operator fleet. It uses MATSim's Taxi/DVRP execution path: a passenger
submits a request, the minimum-wait dispatcher assigns an available vehicle,
and that vehicle returns to service after drop-off. Passenger demand is not
represented by one private Taxi vehicle per person.

## Fleet definition

The model-day fleet is exactly 15,500 vehicles, deliberately not multiplied by
the 5% resident sample rate. This is a user-specified supply experiment against
the 5% demand scenario, not an inference that the vehicle fleet should scale
with simulated residents.

| Taxi type | Vehicles |
|---|---:|
| Urban | 13,083 |
| New Territories | 2,353 |
| Lantau | 64 |
| Total | 15,500 |

Each vehicle has passenger capacity 4. The first technical and A/B gates use
PCU 1.0. Lower PCU values are sensitivity fallbacks only if the predefined
congestion gate requires them; they are not silently substituted.

Vehicle start links are sampled with a fixed seed from feasible Car links.
The spatial prior combines the frozen baseline's aggregated TCS26 Taxi origins
with driveable lane-kilometres. PT-only links, traffic-signal internal
connectors, and dead ends are excluded. This is an inferred initial-location
model, not an observed vehicle trace or depot roster.

Each Taxi receives one continuous 18-hour service window. Start times are
staggered from 00:00 through 10:00 so active supply is lower overnight and
rises toward the daytime/evening peak; service may continue through 28:00.
This approximates an aggregate `Nactive(t)` profile and does not assert that
all 15,500 vehicles operate simultaneously or that real drivers work one
uninterrupted shift.

## Dispatch and passenger service

- official MATSim Taxi/DVRP modules;
- minimum-wait assignment;
- dispatcher reoptimisation every 30 seconds;
- pickup service time 60 seconds;
- drop-off service time 30 seconds;
- completed vehicles remain in the fleet and may serve another request;
- supply shortage is retained as long waiting or unserved demand;
- `removeStuckVehicles=false` and `stuckTime=3600 s` preserve DVRP vehicle
  state rather than removing fleet vehicles mid-service.

Passenger waiting time is

```text
PassengerPickedUp - PassengerRequestSubmitted
```

At the simulation horizon, requests are audited as completed, waiting,
onboard, or rejected/invalid. The conservation identity is

```text
submitted = completed + waiting + onboard + rejected/invalid
```

## Taxi utility

The per-trip constant remains `-9`. Taxi time outside the request-to-pickup
waiting interval is penalised at `-6 util/h`; waiting receives a total penalty
of `-12 util/h`. Fares use `-0.10 util/HKD` for adults and
`-0.15 util/HKD` for `day_school_student` and `tertiary_student` roles. Thus
the conceptual experienced utility is:

```text
adult:   -9 - 6 * non_wait_taxi_time_h - 12 * wait_time_h - 0.10 * fare_HKD
student: -9 - 6 * non_wait_taxi_time_h - 12 * wait_time_h - 0.15 * fare_HKD
```

The wait term is based on request and pickup events. It is not a distance proxy
and is not inferred from a planned Taxi leg duration.

## Fleet and run preparation

The fleet builder is:

```text
scripts/hong_kong_single_city/demand_generation/build_hong_kong_taxi_dvrp_fleet.py
```

The immutable full-fleet artifact used by the candidate is:

```text
/mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260815_payload1/
  build/fleet15500/hong_kong_taxi_fleet.xml.gz
```

The smoke-population preparer and profile-aware launcher are:

```text
scripts/hong_kong_single_city/run/prepare_hong_kong_taxi_dvrp_smoke_plans.py
scripts/hong_kong_single_city/run/launch_hong_kong_candidate11_taxi_dvrp_50qsim.py
```

All server attempts use new immutable payload, release, and run directories
under `/mnt/DiskM/by`. Failed attempts are preserved; they are not deleted,
overwritten, or re-labelled as passing evidence.

## Low-cost technical result

The accepted 0.5% technical experiment is:

```text
/mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260815_smoke0p5_run25
```

It completed iteration 0 with exit code 0. Its Taxi request accounting is:

| State at horizon | Requests |
|---|---:|
| Submitted | 2,717 |
| Completed | 1,417 |
| Waiting | 531 |
| Onboard | 767 |
| Rejected/invalid | 2 |

These values conserve exactly: `2,717 = 1,417 + 531 + 767 + 2`.
The request-to-pickup wait distribution has median 583 seconds and p90
75,444 seconds. The empty-distance share is 0.2292, and QSim reports 223 lost
agents. The long p90 and large horizon backlog are retained supply/demand
feedback, not evidence of calibrated service quality. In particular, exit
code 0 proves technical execution and accounting, not adequate fleet supply,
acceptable congestion, or behavioural equilibrium.

Earlier smoke attempts remain immutable failure evidence. They exposed and
then bounded configuration, route-preparation, empty-plan, school-bus catalog,
physical-mode, and request-scoring integration defects. Only run25 is the
accepted low-cost technical result described here.

## Full-population fixed-plan A/B gate

The exact frozen selected-plan input contains 385,820 people, one selected plan
per person and 118,854 Taxi legs. Its SHA256 is
`92c2fa254b8eb2f2d93de20d4d68ec1f9d1fba12b975246f2b0e8b2d7d1ab753`.
The same input completed iterations 0--1 in both immutable gates:

```text
proxy:    /mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260815_gate_proxy_run5
physical: /mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260815_gate_pcu1_run2
```

At iteration 1 the proxy gate has QSim lost 0, Walk stuck 221 and mean leg
duration 1,577 seconds. The physical PCU-1 gate has QSim lost 18, Walk stuck
379 and mean leg duration 1,688 seconds. Its Taxi accounting conserves exactly:
64,814 submitted equals 14,144 completed plus 42,463 waiting, 8,189 onboard
and 18 rejected/invalid. Median wait is 49,311 seconds, p90 is 76,636 seconds;
all 15,500 fleet vehicles are used, with 0.9125 completed services per fleet
vehicle. Empty VKT is 122,754.924 km, occupied VKT 291,299.978 km, and the
empty-distance share is 0.29647.

Relative to the same-input proxy, the physical fleet adds only 18 QSim-lost
agents and 158 Walk-stuck agents. This passes the predefined congestion gate,
so PCU 1.0 is retained as the highest passing value. No TPDM capacity candidate
and no lower-PCU sensitivity are activated. The long waits and large unserved
backlog are intended finite-supply feedback, not a reason to lower road PCU.

Had the congestion gate failed for at least two hours, the next candidates
would have been, in order:

1. a separate TPDM non-signal bottleneck-capacity candidate that never changes
   signal-controlled links and takes the higher of existing and TPDM capacity;
2. Taxi PCU sensitivities 0.75, 0.50, 0.25, then 0.10.

A later user-authorised diagnostic extends the explicit sensitivity set to
PCU 0.05. It is not silently substituted for the PCU-1 formal run.

The highest PCU passing the technical gate is used. If 0.10 also fails, the
formal run may still proceed at 0.10 but must carry an explicit failed-
congestion-gate label and PCU sensitivity report.

## No-signal run7-network fixed-plan iteration-0 check

The immutable no-signal comparison is:

```text
failed config-only attempt:
  /mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260815_nosignal_run7_it0_run1
accepted run:
  /mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260815_nosignal_run7_it0_run2
release:
  /mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260815_nosignal_run7_it0_release2
```

Run2 completed iteration 0 with exit code 0. It uses the run7 road-hotspot
network, SHA256
`7fd409368c5dbd8695cb4c0ef916229602f2918b88056ae05b441b532b6103cb`,
the same 385,820-person frozen selected plans and 15,500-vehicle fleet as the
physical gate, Taxi PCU 1.0, 16 global/QSim threads, and
`useSignalsystems=false`. The Java command omits `--traffic-signals`. Run1 is
retained as failure evidence: it used the wrong case for the MATSim
`useSignalsystems` parameter and exited during config parsing before QSim.

Of 743,614 selected trips, 401,964 completed by the 30-hour horizon, or
54.0555%. Selected-plan mode shares and completed-trip results are:

| Main mode | Selected trips | Selected share | Completed | Completion | Mean completed trip time |
|---|---:|---:|---:|---:|---:|
| Car | 40,576 | 5.4566% | 3,253 | 8.0171% | 162.85 min |
| Car passenger | 1,635 | 0.2199% | 1,555 | 95.1070% | 50.81 min |
| PT | 318,884 | 42.8830% | 136,194 | 42.7096% | 82.85 min |
| Taxi | 118,854 | 15.9833% | 11,974 | 10.0745% | 112.30 min |
| Walk | 263,665 | 35.4572% | 248,988 | 94.4335% | 129.87 min |

Mean times above are computed only from rows that exist in `0.trips.csv.zst`;
they are full completed-trip durations and have strong survivor bias. They do
not assign a zero duration to unfinished trips. For completed Taxi requests,
the event-audited mean request-to-pickup wait is 9.44 minutes and mean
pickup-to-drop-off time is 100.23 minutes; the 112.30-minute trip mean also
contains access/egress components.

Taxi accounting conserves exactly: 62,598 submitted equals 11,974 completed
plus 42,656 waiting, 7,950 onboard and 18 rejected/invalid. Only 62,598 of the
118,854 selected Taxi trips reached request submission because unfinished
earlier trips prevent later daily trips from starting. Removing signals does
not restore the old run7 completion level; the finite fleet, its empty and
occupied traffic, and the inherited selected demand remain the dominant
constraints in this one-QSim diagnostic. The result is a technical
comparison, not an equilibrium or an adopted no-signal model.

## Original-plan, no-signal, PCU-0.05 iteration-0 smoke

The accepted joint-correction smoke is:

```text
payload: /mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260815_nosignal_run7_original_pcu005_it0_payload3
release: /mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260815_nosignal_run7_original_pcu005_it0_release3
run:     /mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260815_nosignal_run7_original_pcu005_it0_run3
JAR:     9efb79d4db9a52a3a96227438a390c0659c7cbd6bbcd0e5ccb46b294632d8536
```

It uses the same run7-network SHA as the preceding no-signal check, disables
signals, keeps the 15,500-vehicle fleet, changes Taxi road weight to PCU 0.05,
and returns to the original Candidate11 plans with SHA256
`393dd8967d84c69fe974d33a0945eda3fa6eccd0a42b1f3744016542d61cf855`.
Those plans contain 44,000 initial Taxi candidate legs but no run14b
experienced proxy scores. Ordinary replanning before QSim 0 selects 43,999
Taxi trips. No protected household/student joint-selection target falls in
the one-QSim 0--0 window.

Run3 completed with exit code 0, normal shutdown, no OOM, five QSim-lost
agents, and five rejected equal-origin/destination-link Taxi requests. Its
selected-plan and completed-trip audit is:

| Main mode | Selected trips | Selected share | Completed | Completion | Mean completed trip time |
|---|---:|---:|---:|---:|---:|
| Car | 67,718 | 9.1066% | 29,743 | 43.9219% | 43.89 min |
| Car passenger | 2,734 | 0.3677% | 2,734 | 100.0000% | 8.06 min |
| PT | 546,893 | 73.5453% | 390,615 | 71.4244% | 55.94 min |
| Taxi | 43,999 | 5.9169% | 22,327 | 50.7443% | 43.48 min |
| Walk | 82,270 | 11.0635% | 79,096 | 96.1420% | 89.47 min |

Overall, 524,515 of 743,614 selected trips complete, or 70.5359%. Mean times
are calculated only from completed `0.trips.csv.zst` rows and retain survivor
bias. The average executed person score is -25.7459.

Taxi accounting conserves exactly: 32,368 submitted equals 22,327 completed,
1,387 waiting, 8,649 onboard and 5 rejected. Completed-request mean wait is
2.76 minutes and mean in-vehicle time is 40.51 minutes. The all-request wait
distribution is p50 45 seconds, p90 296 seconds, p95 7,873 seconds and p99
62,227 seconds. Of 15,500 fleet vehicles, 14,089 serve at least one request;
completed services per fleet vehicle are 1.4405. Empty VKT is 24,985.173 km,
occupied VKT 318,072.572 km, and the empty-distance share is 0.07283.

The same original-plan iteration-0 selected mode shares occur in formal run4.
Formal run4 iteration 0, which instead uses the Candidate10/Candidate11
signalled supply and Taxi PCU 1.0, completes 51.8843% overall; mode completion
is 20.0892% Car, 51.7979% PT, 18.9618% Taxi and 94.6384% Walk. The new smoke
therefore improves overall completion by 18.6516 percentage points, but the
comparison changes both Taxi PCU and road/signal supply and cannot attribute
the gain to PCU alone.

Technical acceptance passes: configuration provenance, PCU, signal switch,
network/JAR hashes, request conservation, shutdown and output integrity all
pass. Transport-performance acceptance remains partial: 177,936 agents are
still active at the 30-hour horizon and the 70.5359% trip completion rate is
well below the historical non-DVRP run7 result. This smoke is suitable as
evidence for the next controlled gate, not as a final adopted configuration.

The first launcher payload stopped before release/run creation because its
guard incorrectly interpreted “no proxy score” as zero Taxi candidate legs.
Payload2/release2/run2 then stopped before QSim because a 0--0 smoke was given
formal joint-selection targets 5,15,25,35. Both are retained. Payload3 omits
out-of-window joint-selection targets, preserves formal-50 scheduling, and
adds PCU 0.05 to the explicit Java and launcher allowlists.

## Teleported-Taxi causal controls for the completion loss

Two additional immutable controls isolate the low completion rate without
changing the run7 road-hotspot network, original Candidate11 plans, signal
switch, 16-thread allocation, 30-hour horizon or application JAR. Both retain
all 44,000 selected Taxi legs but execute Taxi as the ordinary teleported mode,
so no Taxi vehicle enters QSim:

```text
new stuck policy, failed selector-contract attempt:
  /mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260816_nosignal_run7_teleported_control_it0_run1
new stuck policy, accepted:
  /mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260816_nosignal_run7_teleported_control_it0_run2
old stuck policy, accepted:
  /mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260816_nosignal_run7_teleported_oldstuck_it0_run1
JAR:
  9efb79d4db9a52a3a96227438a390c0659c7cbd6bbcd0e5ccb46b294632d8536
plans:
  393dd8967d84c69fe974d33a0945eda3fa6eccd0a42b1f3744016542d61cf855
network:
  7fd409368c5dbd8695cb4c0ef916229602f2918b88056ae05b441b532b6103cb
```

The failed control exited before population loading because the command
unnecessarily loaded the household selector alongside `ChangeExpBeta`. The
accepted iteration-0 control omits that inactive selector. The second accepted
control differs from it only in the two historical run7 QSim settings:
`stuckTime=600 s` and `removeStuckVehicles=true`, instead of 3,600 s and
`false`. Both accepted runs exit 0 with normal shutdown.
Run2's metadata field `household_joint_catalog_loaded=true` is a launcher
bookkeeping defect; its recorded Java command correctly contains no household
catalog argument. The launcher now derives that field from the actual
teleported-control contract, and the old-stuck control records `false`.

| Execution | Stuck policy | Completed trips | Completion | Active at 30:00 | QSim lost |
|---|---|---:|---:|---:|---:|
| Historical run7 | 600 s, remove | 710,910 | 95.6020% | 14,048 | 5,863 |
| Same current JAR, teleported Taxi | 600 s, remove | 703,285 | 94.5766% | 17,263 | 9,853 |
| Same current JAR, teleported Taxi | 3,600 s, retain | 610,237 | 82.0637% | 110,161 | 0 |
| Same current JAR, physical Taxi PCU 0.05 | 3,600 s, retain | 524,515 | 70.5359% | 177,936 | 5 |

Using only the three same-JAR rows, changing the stuck policy costs 12.5129
percentage points and adding the physical fleet costs a further 11.5277
points. They explain respectively 52.05% and 47.95% of the 24.0407-point
same-JAR loss. The remaining 1.0254-point difference between historical run7
and the same-JAR old-stuck control is a historical runtime/application
difference and is not attributed to the stuck policy.

Mode-specific completion confirms different mechanisms. The stuck-policy
change reduces Car from 90.2168% to 58.5103% and PT from 94.1369% to 81.5183%.
Adding the fleet then reduces Car to 43.9219%, PT to 71.4244% and Taxi from
95.7841% to 50.7443%. Walk changes only from 97.1423% to 96.1420% in the fleet
step. The unfinished-request audit also shows that the Taxi loss is not only
pre-pickup waiting: 8,649 requests are already onboard at the horizon, versus
1,387 still waiting.

Completed-trip means must not be read as congestion-free evidence. Across
all modes the completed-row weighted mean rises from 52.42 minutes under the
old stuck policy, to 53.55 minutes under the retained-stuck control, and to
59.54 minutes with the physical fleet. On identical completed trip keys, the
stuck-policy change increases Car time by 37.32% and PT time by 18.42%. The
fleet step adds another 60.46% for Car, 17.60% for PT and 310.90% for Taxi.
The raw Car mean can fall when long trips disappear from the completed sample;
that is survivor bias, not a travel-time improvement.

The link-event audit locates the network mechanism. Without physical Taxi,
the retained-stuck control already has 241,217.48 road vehicle-hours of delay
and 46,428 road-vehicle stuck events: 19,669 Bus, 15,571 GMB, 10,894 private
Car and 294 school-bus. Adding PCU-0.05 Taxi increases delay to 373,836.23
vehicle-hours (+54.98%), road-vehicle stuck events to 71,682 (+54.39%) and
links with at least 100 traversals and mean travel-time ratio above 2 from
3,116 to 3,912 (+25.55%). It adds 9,920 stuck Taxi-fleet vehicle movements
and also increases Bus, GMB and private-Car stuck counts by 8,333, 3,759 and
3,183 respectively. Road link traversals nevertheless fall by 1.53%, evidence
of gridlock rather than useful added throughput.

The fleet also creates 53,400 road-vehicle movement episodes, including 9,877
initial immediate U-turns; 9,563 of those fleet movements become stuck. For
example `road_8769_0_f` changes from 1.05 million seconds of delay and 730 s
mean traversal time in the teleported control to 18.73 million seconds and
10,356 s with the fleet, with 869 Taxi-fleet traversals on that link. PCU 0.05
is confirmed by the runtime log, but it does not remove discrete vehicles,
empty pickup travel, topology interactions or queue blocking. The completion
loss is therefore a combination of previously hidden network gridlock and a
real fleet-loading/initial-routing amplification, not excessive Taxi PCU
alone.

The immutable link-audit outputs are stored under
`run2/road_runtime_audit_control_v1` for the teleported control and
`run3/road_runtime_audit_causal_v1` for the PCU-0.05 physical run, beneath the
full run roots listed above.

An independent road-supply sensitivity candidate was subsequently generated
under
`/mnt/DiskM/by/hk_stage11_road_hotspot_tpdm_v4_three_candidate_20260816_candidate2`.
It adds the TPDM Volume 4 lane saturation candidate to the existing
two-candidate maximum and raises the summed physical-road capacity diagnostic
by 40.3407%. It was not used by the Taxi runs described above. See
`docs/HONG_KONG_TPDM_V4_THREE_CANDIDATE_NETWORK.md`.

The subsequent full-population iteration-0 smoke uses that network with the
same original plans, no-signal setup, 15,500-vehicle fleet, Taxi PCU 0.05,
`stuckTime=3600`, and retained stuck vehicles as the accepted run7-network
physical-Taxi run3. It is stored under
`/mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260816_tpdm3_pcu005_it0_run1`
and exits 0. Overall completion rises from 70.5359% to 74.7509%, while mean
completed-trip time falls from 59.54 to 54.35 minutes. On 515,196 identical
trip keys completed in both runs, mean time falls by 7.10%. The improvement is
material but remains below the 82.0637% teleported-Taxi retained-stuck control,
so it does not by itself close the physical-fleet completion gap.

The intended formal run executes QSim iterations 0--49 with 16 global/QSim
threads. Ordinary route, mode, and activity-time innovation remains available
through iteration 34; iterations 35--49 keep only `ChangeExpBeta`. Protected
student/household joint choices enter QSim at 5, 15, 25, and 35 and freeze
after 35. Intermediate graphs, duration summaries, histograms, trips, events,
and plans use a 10-iteration interval, with experienced plans enabled and a
compact Taxi audit written each iteration.

The current immutable formal attempt is:

```text
payload: /mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260815_payload32
release: /mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260815_formal50_release4
run:     /mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260815_formal50_run4
JAR:     412a2445f6c4818f2dbe0a8629905f3fa004fd467bc578e021d01c570ba5515e
```

It started on 2026-08-15 with PCU 1.0. Run1 failed before QSim because the
physical fleet and person-local proxy were both enabled; run2 failed before
QSim because legacy generic school-bus plans were misclassified as physical
v6 candidates. Run3 restored the historical initial
behavior: all 9,626 legacy generic school-bus legs fall back to ordinary PT,
while later exact physical candidates retain strict stable-ID checks, but it
exited after iteration 4 when a coincident-origin/destination Taxi alternative
legitimately routed to an empty trip and the protected selector assumed a Taxi
leg must exist. Run4 treats that zero-distance Taxi alternative as unavailable
and lets zero-distance Walk or another real candidate participate. All failed
attempts remain immutable.

Run4 has not yet completed or passed its final accounting, reference,
strategy-schedule, performance, or output-integrity checks. The active
server process was not stopped. The user disabled the 30-minute Heartbeat, so
there is no active automatic monitor or relaunch task.

## Adoption boundary

The operational-sampling sensitivity with a 30% fleet, five shadow requests
per submitted behavioral Taxi request, and full-fleet-equivalent Taxi PCU 0.05
is documented separately in
`docs/HONG_KONG_TAXI_30PCT_SHADOW6_FREEZE_TEST.md`. It remains a frozen
iteration-0 technical experiment and does not alter the adoption boundary.

The subsequent TCS passenger-to-hire experiment restores all 15,500 vehicles,
uses parent-triggered zero-weight operational replicas, and tests 579,011 and
536,121 daily-hire targets. Both runs exit 0 and conserve requests, but retain
69.82%--71.37% not-picked shares and fail the behavioral-completion gate. They
are documented in `docs/HONG_KONG_TAXI_TCS_FULL_FLEET_CALIBRATION.md` and do
not alter the adoption boundary.

Until formal iteration 49 completes successfully:

- this fleet remains opt-in candidate supply;
- PCU 1.0 is the highest value passing the bounded same-input congestion gate,
  not an observed Hong Kong Taxi PCU calibration;
- run25 is a technical smoke result, not a transport-performance result;
- Candidate11 signals remain a non-production research candidate;
- the adopted 50-iteration Ferry Core scenario, city `current_model`, and
  run-manifest `current_final_run` remain unchanged.
