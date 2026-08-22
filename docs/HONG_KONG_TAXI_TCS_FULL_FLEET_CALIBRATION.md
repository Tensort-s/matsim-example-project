# Hong Kong TCS passenger-to-hire full-fleet calibration

## Purpose and adoption status

This is a frozen iteration-0 technical calibration of physical Taxi supply and
operational demand. It restores the complete 15,500-vehicle scenario fleet and
converts the official Taxi passenger-journey control to an estimated number of
vehicle hires. It is a sensitivity experiment, not an adopted behavioral
population or production run.

## Demand control

The local official control file reports Taxi **passenger journeys**, not Taxi
vehicle hires. The January-April 2026 median is 723,763 passenger journeys per
day. The central conversion uses a provisional mean party occupancy of 1.25:

```text
723,763 passenger journeys / 1.25 passengers per hire
= 579,011 estimated vehicle hires per day
```

The 1.25 occupancy is an explicit calibration assumption; it is not labeled as
an observed TCS occupancy statistic. Planned sensitivities are 1.15 and 1.35
passengers per hire only if the central wait distribution falls outside the
acceptance window.

The frozen Candidate11 source contains 44,000 selected Taxi legs. A preceding
validated physical-Taxi iteration submitted 43,796 of them; the remaining 204
were not reached within that run. Deterministic integerization assigns each of
the 43,796 reachable parent legs a total of 13 or 14 operational hires:

- 34,133 parents receive 13 total hires;
- 9,663 parents receive 14 total hires;
- the exact parent-plus-operational target is 579,011;
- 535,215 zero-weight operational passengers are appended;
- the resulting input has 921,035 persons and 579,215 Taxi legs, including the
  204 original but previously unreached Taxi legs.

## Parent-trigger contract

Operational passengers do not submit at their plan time independently. The
QSim gate holds each operational Taxi departure until its matching behavioral
parent actually emits `PassengerRequestSubmitted`. It then releases replicas
over a deterministic 0-899 second interval. If the parent request never
submits, none of its operational replicas submits. Event callbacks only enqueue
work; QSim state transitions occur in the engine step outside application
locks.

Operational passengers carry `expansionWeight=0` and
`hkTaxiOperationalShadow=true`. Taxi wait scoring does not emit score events
for these passengers. They remain in MATSim's population until all lifecycle
writers finish, because removing them after QSim invalidates experienced-plan
records. A separate filtered behavior audit is authoritative; raw default
MATSim mode/score statistics include the operational carriers and must not be
used. Taxi request and fleet audits retain them and distinguish behavioral
from operational submissions.

## Frozen supply and simulation

- fleet: 15,500 vehicles (Urban 13,083; New Territories 2,353; Lantau 64);
- vehicle PCU: 0.05;
- vehicle capacity: four passengers;
- service windows: the established single-window 18-hour approximation;
- optimizer: official MATSim Taxi/DVRP minimum-wait rule, 30-second
  reoptimization, 60-second pickup and 30-second dropoff;
- road supply: Candidate5B network plus the full-link explicit road-supply
  registry;
- signals: Candidate11;
- PT: calibrated schedule/vehicles with PT routes cleared and rebuilt;
- QSim: 00:00-30:00, 16 threads, `stuckTime=3600`,
  `removeStuckVehicles=false`;
- behavior: iteration 0 only, selected mode/route/time frozen, no innovation.

## Acceptance window

The service calibration targets are modeling targets, not claimed TCS waiting
observations:

- served mean wait: 5-7 minutes;
- served median wait: 3-5 minutes;
- p90 wait no more than 10 minutes;
- p95 wait no more than 15 minutes;
- not-picked share below 0.5%;
- no time-of-day pickup blackout;
- road-trip completion no more than two percentage points below the matching
  frozen baseline and no persistent two-hour gridlock.

## Central run

The immutable central attempts are:

```text
payload: /mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260823_tcs579011_fullfleet_payload1
release: /mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260823_tcs579011_fullfleet_release1
run:     /mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260823_tcs579011_fullfleet_run1
JAR SHA256: d7970f91fa650f016e8be0b73c4a6771934dcfe721359ad9de26e599cdb698b0

payload: /mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260823_tcs579011_fullfleet_payload2
release: /mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260823_tcs579011_fullfleet_release2
run:     /mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260823_tcs579011_fullfleet_run2
JAR SHA256: 09c6b0b0e637abb02bce7261f5cb12df61535e49fc8592c7d1104cc9bb7a5b98
```

Run1 completed QSim through 30:00, then exited 1 because its initial
AfterMobsim filter removed operational persons before MATSim wrote experienced
plans. The failed directory and thread/process evidence are retained. Run2
replaces mutation with the separate filtered audit. It completed iteration 0,
the 30-hour QSim, all lifecycle writers, and shutdown with exit code 0 in
21:02 wall time. Maximum RSS was 29,182,004 KiB.

Run2 conserves all 283,096 submitted requests: 69,507 completed, 11,535 were
onboard, 202,001 were waiting, and 53 were rejected at 30:00. The not-picked
share is 71.3730%. Among completed requests, mean / p50 / p90 / p95 wait is
2,423.4 / 465 / 7,718 / 10,782.7 seconds. The behavioral-only completed subset
has 460.4 / 178 / 743 / 1,142 seconds, but only 6,717 of 25,506 submitted
behavioral requests completed. Requests submitted from 10:00 onward have no
pickup in their submission-hour cohort. All 15,500 vehicles are used, complete
69,507 services (4.484 per vehicle), and have a 32.3335% empty-VKT share.

The parent gate observed 25,506 parent submissions, released 257,456 of
535,081 held shadows, and left 277,625 unreleased. It therefore prevents
independent shadow demand but also preserves the feedback whereby an
uncompleted parent activity chain cannot trigger later demand. The filtered
behavior output contains 385,820 behavioral and 535,215 operational persons;
all behavioral selected plans have finite scores. Excluding operational
persons, 648,796 of 743,614 planned behavioral trips complete (87.2490%),
11.1993 percentage points below the matched 98.4483% frozen baseline.

## High-occupancy sensitivity

Because the central run waits are too long, the one-sided sensitivity uses
1.35 passengers per hire:

```text
723,763 / 1.35 = 536,121 estimated hires

payload: /mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260823_tcs536121_fullfleet_payload1
release: /mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260823_tcs536121_fullfleet_release1
run:     /mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260823_tcs536121_fullfleet_run1
JAR SHA256: 09c6b0b0e637abb02bce7261f5cb12df61535e49fc8592c7d1104cc9bb7a5b98
```

The generated population has 492,325 operational persons, 878,145 total
persons and 536,325 Taxi legs including the same 204 previously unreached
parent legs. The run exits 0 and conserves 265,051 submitted requests: 68,780
completed, 11,208 onboard, 185,014 waiting and 49 rejected. Not-picked is
69.8217%. Completed-request mean / p50 / p90 / p95 wait is 3,284.0 / 508 /
8,629.2 / 14,060.1 seconds. All 15,500 vehicles complete 68,780 services
(4.437 per vehicle); empty-VKT share is 32.8314%. Excluding operational
persons, 642,462 of 743,614 behavioral trips complete (86.3972%).

Both full-fleet cases pass technical execution, request conservation, finite
behavioral scoring, parent-trigger isolation, and no-residual-process checks.
Both fail every aggregate service target and the road/behavior completion
gate. The high-occupancy sensitivity is not monotonic in completed wait or
behavioral completion because deterministic spatial-temporal integerization
changes which parent cohorts receive 12 versus 13 tasks and the congested
dispatcher operates beyond a nonlinear capacity threshold. Neither case is
adopted. The 1.15 sensitivity is not run because it increases demand in the
direction already decisively rejected.
