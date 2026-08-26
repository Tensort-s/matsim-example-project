# Hong Kong Walk and Taxi scoring factorial V1

## Status and scope

This is an opt-in calibration experiment. It does not replace the adopted
Candidate5B + Candidate11-signal + calibrated-PT + physical-Taxi scenario.
All four arms start from the original Candidate11 population (385,820 people,
743,614 main trips, 44,000 Taxi legs) and therefore contain no iteration-49
scores or person-local Taxi proxy scores.

Fixed supply is Candidate5B, Candidate11 signals, the calibrated day-2 PT
schedule, 15,500 physical Taxi vehicles at 0.05 PCU, QSim 00:00--30:00,
`stuckTime=3600`, and `removeStuckVehicles=false`. No shadow requests are used.

## Scoring arms

| Arm | Taxi score | Walk score |
|---|---|---|
| A0 | formal-50 V1 | legacy V1 |
| A1 | calibration V2 | legacy V1 |
| A2 | formal-50 V1 | calibration V2 |
| A3 | calibration V2 | calibration V2 |

Taxi calibration V2 is uniform across Hong Kong:

```text
U_taxi = -9 - 6 T_in_vehicle,h - 18 T_wait,h - beta_fare fare_HKD
beta_fare = 0.12 adult; 0.18 student
```

Walk calibration V2 is applied once per main-mode Walk trip. PT access and
egress Walk legs are excluded:

```text
U_walk = U_walk,base
       - 0.15
       - 3.278342 max(0, T_walk,h - 10/60)
       - 9.0      max(0, T_walk,h - 15/60)
```

Legacy V1 remains unchanged: no constant and a single 3.278342 util/h hinge
above ten cumulative Walk minutes per main trip.

## Execution design

Phase 1 runs frozen iteration 0 for A0 and A3. The selected plans and mode
shares must be identical; only scores may differ. Phase 2 runs A0--A3 for
iterations 0--9 with a common seed. Ordinary residents/visitors use
`ChangeExpBeta` (weight 0.8) plus mode-only `SubtourModeChoice` (weight 0.2)
through iteration 5; iterations 6--9 retain only `ChangeExpBeta`. Route and
departure-time innovation are disabled. Household
and student people are assigned the protected subpopulation once and remain
frozen; no joint selector runs during the factorial screen.
Selected plans and trips are written every screening iteration so iterations
7--9 can be audited directly; events retain the ten-iteration interval.

The launcher profiles are `score-factorial-frozen-it0` and
`score-factorial-10`, with required `--scoring-arm=a0|a1|a2|a3`. Every attempt
uses new immutable payload, release, and run directories.

After all four arms exit successfully,
`audit_hong_kong_walk_taxi_scoring_factorial.py` reads each iteration's plans,
completed trips, compact Taxi request audit, and score statistics. It writes a
single JSON report plus long-form iteration metrics and initial-to-final mode
transition matrices. Durations and completion rates are grouped by the planned
main mode, so PT-to-Walk fallback trips cannot silently inflate the Walk result;
the actual-mode mismatch counts remain explicit.

The Java startup contract validates this screening topology separately from
the maximum-utility joint-selector topology: the protected subpopulation must
contain only `KeepLastSelected` at weight 1; the unpriced-border no-car
subpopulation must contain only `ChangeExpBeta` at weight 1; every other
subpopulation must contain exactly `ChangeExpBeta` at 0.8 and
`SubtourModeChoice` at 0.2, with the latter disabled after iteration 5.

The first Phase-2 A0 attempt (`scorefactorial10_a0_run1`) is a preserved
technical failure. It exited before scenario loading because the new
protection-only flag still invoked the older maximum-utility-selector
validation. The dedicated topology validation above is the minimal correction;
no scoring, plans, supply, seed, or QSim setting changed.

## Acceptance targets

- Walk: 10.5--12.0% of planned main trips, mean completed duration 12--15 min,
  60--68% at or below 10 min, 12--18% above 15 min, completion at least 99.5%.
- Taxi: 5--7% (centre 5.92%), request completion at least 99%, unpicked at most
  0.5%, median wait 3--5 min, mean wait 5--7 min, p90 at most 10 min, p95 at
  most 15 min, and exact request conservation.
- Overall completion at least 99.5% and no more than 0.2 percentage points below
  A0; no material PT/stuck deterioration.
- For the last three iterations, each target-mode share range must be at most
  0.5 percentage points and mean-duration range at most 5%.

Only if A3 passes the screening gates may a separate 25-iteration confirmation
be launched from the same original plans. That confirmation is not part of the
initial factorial run and must receive its own immutable provenance.

## Incremental V3 screen after the four-arm result

The completed A0--A3 screen did not permit a 25-iteration confirmation. At
iteration 9, A3 retained 12.3064% Taxi and 10.0827% Walk; Walk mean completed
duration was 87.23 minutes and 84.06% of completed planned-Walk trips exceeded
15 minutes. Taxi request conservation and service completion passed, but the
Taxi share remained above the 5--7% target. A3 is therefore reused as the B0
baseline; it is not rerun.

Taxi V3 applies one Hong-Kong-wide formula:

```text
U_taxi = -9.60 - 6 T_in_vehicle,h - 18 T_wait,h - beta_fare fare_HKD
beta_fare = 0.125 adult; 0.1875 student
```

Walk V3 is still applied exactly once per main-mode Walk trip and excludes PT
access/egress Walk:

```text
U_walk = U_walk,base
       + 0.20
       - 3.278342 max(0, T_walk,h - 10/60)
       - 12.0     max(0, T_walk,h - 15/60)
       - 60.0     max(0, T_walk,h - 30/60)
```

The incremental sequence is deliberately gated:

| Arm | Taxi score | Walk score | Execution |
|---|---|---|---|
| B0 | V2 | V2 | reuse completed A3 |
| B1 | V3 | V2 | run first |
| B2 | V2 | V3 | run first, in parallel with B1 when resources allow |
| B3 | V3 | V3 | forbidden until both B1 and B2 pass |

B1 passes on Taxi share 5--7%, request completion at least 99%, unpicked at
most 0.5%, exact conservation, relative overall completion, and last-three
stability. Taxi median/mean wait remain diagnostic rather than score-formula
gates because lower demand with a fixed fleet mechanically shortens wait; fleet
availability and dispatch require a separate supply calibration.

B2 passes on the existing Walk share, duration-band, completion, relative
overall-completion, and stability gates. The script
`audit_hong_kong_walk_taxi_scoring_v3_incremental.py` enforces these component
gates and writes `b3_allowed=false` whenever either arm fails. Only
`b3_allowed=true` authorizes creation of a new immutable B3 attempt.

## Completed V3 audit and PT-aligned Taxi-cost sensitivity

The immutable B1/B2 audit completed successfully as an analysis process but
failed the behavioral gates, so B3 was not launched. B1 ended at 11.4300%
Taxi share. It retained 99.9941% Taxi-request completion and exact request
conservation; completed-request wait was 106.54 s mean, 62 s p50, 248 s p90,
and 371 s p95. B2 ended at 8.7767% Walk share, 84.23 min mean completed Walk
duration, 9.16% at or below ten minutes, and 81.87% above fifteen minutes. The
last-three Walk mean-duration range was 5.234%, also above the 5% stability
gate. These results show that ten iterations were insufficient for a final
calibration and that the V3 score changes were directionally too weak.

The next sensitivity therefore uses a 25-iteration profile. Ordinary
mode-choice innovation is available in iterations 0--9 and disabled after
iteration 9; iterations 10--24 are selection-only. Protected household/student
plans remain frozen. All other demand, network, signals, calibrated PT, Taxi
fleet, PCU, QSim horizon, stuck settings, random seed, and output intervals are
unchanged.

The authorized C1 arm isolates the user's requested Taxi coefficient. Walk
remains at V2, while Taxi uses the same marginal money coefficient and waiting
time coefficient as PT:

```text
U_taxi = -9.60
       - 6 T_in_vehicle,h
       - 6 T_wait,h
       - 1.0 fare_HKD
```

The adult and student fare coefficients are both exactly `-1 util/HKD` in the
score. The launcher accepts their positive magnitudes (`1`) and the Java Taxi
scorer applies the negative sign. This is an intentionally strong upper-bound
sensitivity, not an adopted calibration: the preceding selected Taxi fares
averaged about HKD 140, so the fare term is expected to dominate the modest
reduction in waiting disutility.

For later, separately authorized tests, Walk V4 is defined but is not active in
C1:

```text
U_walk = U_walk,base
       + 2.0
       - 3.278342 max(0, T_walk,h - 10/60)
       - 60.0     max(0, T_walk,h - 15/60)
       - 240.0    max(0, T_walk,h - 30/60)
```

C2 would combine Taxi V2 with Walk V4, while C3 would combine the PT-aligned
Taxi formula with Walk V4. Neither is authorized by the C1 test. C1 acceptance
reports Taxi share against the 5--7% TCS target, exact request conservation,
request completion, wait distribution, overall trip completion, and
last-five-iteration stability; a very low Taxi share is a valid diagnostic
outcome rather than a technical failure.

## Split adult/student fare sensitivity D1

C1 completed all 25 iterations and exited zero. Its iteration-24 Taxi share
was 2.7253%, below the 5--7% TCS target, while the last-five share range was
only 0.0391 percentage points. The `-1 util/HKD` fare coefficient is therefore
a stable but excessive penalty rather than a technical failure. Iteration 21
was already within 0.0117 percentage points of the iteration-24 Taxi share, so
the next bounded sensitivity uses 22 total iterations (0--21): mode-choice
innovation remains available in iterations 0--9 and iterations 10--21 are
selection-only.

The authorized D1 arm keeps Walk V2 and all C1 demand and supply inputs fixed,
but separates adult and student Taxi fare sensitivity:

```text
U_taxi,adult = -9.60 - 6 T_in_vehicle,h - 6 T_wait,h - 0.6 fare_HKD
U_taxi,student = -9.60 - 6 T_in_vehicle,h - 6 T_wait,h - 0.7 fare_HKD
```

The launcher receives positive magnitudes `0.6` and `0.7`; the Java scorer
applies the negative sign. D1 is an opt-in sensitivity, not an adopted
production formula. It uses profile `score-calibration-22` with
`--scoring-arm=d1` and must run in new immutable payload, release, and run
directories. Acceptance uses the same Taxi share, request-service, wait,
completion, and last-five stability outputs as C1, with explicit comparison to
C1, B1, A3, and the TCS target.

## Split fare plus Walk V4 sensitivity D2

D1 completed all 22 iterations and exited zero. Its iteration-21 Taxi share
was 3.4221%, up 0.6967 percentage points from C1 but still below the 5--7%
TCS target. Its last-five Taxi-share range was only 0.0449 percentage points,
so the residual gap is not an iteration-count artifact. D2 therefore keeps
the same 22-iteration schedule and all fixed demand and supply inputs, reduces
the Taxi fare disutility by one further bounded step, and activates the
already unit-tested Walk V4 formula:

```text
U_taxi,adult = -9.60 - 6 T_in_vehicle,h - 6 T_wait,h - 0.5 fare_HKD
U_taxi,student = -9.60 - 6 T_in_vehicle,h - 6 T_wait,h - 0.6 fare_HKD

U_walk = U_walk,base + 2.0
         - 3.278342 max(0, T_walk,h - 10/60)
         - 60.0     max(0, T_walk,h - 15/60)
         - 240.0    max(0, T_walk,h - 30/60)
```

Walk V4 applies only to main-mode Walk trips; PT access/egress walk is not
rewarded. The launcher receives positive Taxi fare magnitudes `0.5` and `0.6`,
while the Java scorer applies their negative sign. D2 is an opt-in sensitivity,
not an adopted production formula. It uses profile `score-calibration-22` with
`--scoring-arm=d2`: iterations 0--9 retain ordinary mode-choice innovation and
iterations 10--21 are selection-only. Acceptance compares D2 with D1, C1, B1,
A3, and the TCS targets, including Walk distribution and Taxi request-service
and wait metrics.

### D2 final audit

D2 completed iterations 0--21 and exited zero with complete output and no
fatal runtime marker. The iteration-21 Taxi share was 6.4243%, inside the
5--7% TCS target, and the last-five share range was only 0.1838 percentage
points. Taxi request conservation held: 47,313 requests were submitted,
47,308 completed, two were rejected, and three remained waiting at 30:00.
This gives 99.9894% request completion and 0.0106% unpicked. Mean Taxi wait
was 1.209 minutes, with p50/p90/p95 of 0.667/2.567/3.817 minutes. Service
reliability therefore passed, but p50 and mean wait remained below the
calibration bands of 3--5 and 5--7 minutes.

Walk V4 did not pass its calibration targets. The final Walk share was
7.8510% versus the 10.5--12% target, completed-Walk mean duration was 73.763
minutes versus 12--15 minutes, 10.216% were no longer than 10 minutes versus
60--68%, and 78.896% exceeded 15 minutes versus 12--18%. Its completion rate
was 99.6146%, and the last-five Walk share and mean-duration ranges were only
0.0425 percentage points and 0.512 minutes, respectively. The discrepancy is
therefore stable rather than an insufficient-iteration artifact. Before any
further Walk coefficient change, the main-mode Walk population and duration
construction should be audited because increasing the long-walk penalty
reduced share without removing the very long selected alternatives.

Overall trip completion was 99.0534%, below the 99.5% gate. Of 7,039 final
incomplete trips, 6,381 were PT trips at the 30-hour boundary, compared with
318 Taxi, 225 Walk, and 115 car trips. This overall gate failure is therefore
dominated by PT boundary/right-censor behavior rather than Taxi request
service. Absolute executed-score levels are not welfare-comparable with
A3/B1/C1/D1 because D2 changes the utility scale. D2 remains a sensitivity
result, not an adopted production formula.

The structural steps that follow this audit are specified in
[`HONG_KONG_WALK_CHOICE_SET_REPAIR_V1.md`](HONG_KONG_WALK_CHOICE_SET_REPAIR_V1.md).
They use a universal physical-network 15/30-minute Walk choice-set rule,
atomically repair frozen home-based tours, and add network-routed short-Walk
alternatives before any further coefficient sensitivity.

## Named GradeV1/GradeV2 scoring snapshots

The post-repair experiment replaces independent command-line coefficient
overrides with the single `--scoring-grade=GradeV1|GradeV2` contract.
`GradeV1` is the actual run3 baseline: global marginal utility of money 1.0,
Taxi adult/student fare magnitudes 0.5/0.6, `car_passenger` and `school_bus`
constants -1.5, and the original Walk V4 first slope 3.278342. Historical run3
is labelled `GradeV1/pre-selector-fix`; a new GradeV1 run would use the
corrected joint selector and is therefore not expected to reproduce its Walk
injection defect.

`GradeV2` is the complete new snapshot:

```text
U_car = -0.5 - 6 T_h - 0.28 (energy_HKD + toll_HKD + parking_HKD)
U_pt = -6 T_h - 0.28 fare_HKD
U_taxi,adult = -9.6 - 6 T_wait,h - 6 T_ride,h - 0.28 fare_HKD
U_taxi,student = -9.6 - 6 T_wait,h - 6 T_ride,h - 0.4 fare_HKD
U_car_passenger = -6 T_h
U_school_bus = -6 T_h
U_walk = -6 T_h + 2
         - 3   max(0, T_h - 10/60)
         - 60  max(0, T_h - 15/60)
         - 240 max(0, T_h - 30/60)
```

PT and Car share the global 0.28 money coefficient. Taxi fare remains an
independent adult/student score and the standard Taxi monetary-distance rate
must be zero, preventing a second multiplication by 0.28. Walk V5 is injected
as the same immutable parameter instance into final scoring and
`HouseholdJointPlanSelector`. The V5 constant and hinges apply only when every
leg of the candidate's main trip is Walk. PT and School bus access/egress Walk
continues to score linearly at `-6 util/h`, without the `+2` or any hinge.

The corresponding immutable server profile is
`score-gradev2-walk-repair-22`. It reuses the accepted prepare7 plans, retains
ordinary innovation in iterations 0--9, switches to selection-only in
iterations 10--21, and runs the household/student/School-bus selector at
iterations 5 and 15. Candidate5B, explicit road supply, Candidate11 signals,
calibrated PT, 15,500 Taxi, PCU 0.05, 16 threads, the 30-hour boundary, and
stuck policy remain fixed. This remains a sensitivity experiment and does not
replace the adopted production configuration unless its audit gates pass.

### GradeV2 final audit

The immutable GradeV2 run2 completed iterations 0--21, exited zero, and
successfully executed both joint-selection rounds at iterations 5 and 15. The
authoritative scoring identity is the run metadata and startup
`HK_SCORING_GRADE` record: global money utility 0.28, independent Taxi adult
and student fare utilities -0.28 and -0.4, zero standard Taxi monetary-distance
rate, zero `car_passenger` and `school_bus` constants, and Walk V5. The reused
D2 audit parser retains historical D2 labels in its JSON, so those labels and
hard-coded D2 coefficient annotations must not be interpreted as the actual
GradeV2 runtime parameters.

At iteration 21 there were 743,614 planned main trips and 736,711 completed
trips, for 99.0717% overall completion. The average executed score was
50.0906, but absolute scores are not welfare-comparable with earlier grades.
After separating physical School bus from the audit parser's broad PT class,
the final main-mode results were:

| Mode | Planned | Share | Completed | Completion | Mean min | Median min | P90 min |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Car | 57,543 | 7.7383% | 57,443 | 99.8262% | 22.885 | 19.167 | 43.117 |
| Car passenger | 5,212 | 0.7009% | 5,104 | 97.9279% | 33.018 | 29.183 | 63.102 |
| PT | 565,583 | 76.0587% | 559,566 | 98.9361% | 42.618 | 36.183 | 74.333 |
| Taxi | 69,152 | 9.2994% | 68,705 | 99.3536% | 19.163 | 16.050 | 33.950 |
| Walk | 37,332 | 5.0203% | 37,109 | 99.4027% | 21.329 | 14.867 | 29.717 |
| School bus | 8,792 | 1.1823% | 8,784 | 99.9090% | 37.275 | 31.600 | 64.445 |

The iteration-15 independent student selector preferred 8,931 School-bus
trips. The later household joint choice overrode 139 of those trips with
physical `car_passenger`, leaving 8,792 final School-bus trips. The physical
handler recorded 8,787 School-bus departures and three missed departures,
consistent with 8,784 completed trips. This meets the 8,000--8,800 diagnostic
volume gate.

Taxi request conservation held for 68,591 submitted requests: 68,589
completed and two remained waiting. Request completion was 99.9971% and the
unpicked share was 0.0029%. Mean/p50/p90/p95 wait times were
1.6226/1.0333/3.5500/5.1000 minutes. Service reliability passed, but the 9.2994%
Taxi share exceeded the 5--7% calibration band and mean/p50 waits remained
below their 5--7 and 3--5 minute realism bands.

Walk V5 plus choice-set repair reduced the final completed-Walk mean from the
roughly 90-minute D1 level to 21.329 minutes, but Walk still failed its
calibration gates: 5.0203% share, 23.4175% at most 10 minutes, and 49.1929%
over 15 minutes, versus respective targets of 10.5--12%, 60--68%, and
12--18%. The last-five Walk share range was only 0.0440 percentage points,
while mean duration continued down from 23.005 to 21.329 minutes.

Of the 6,903 incomplete or right-censored final trips, 6,017 were ordinary PT,
447 Taxi, 223 Walk, 108 Car passenger, 100 Car, and eight School bus. The
overall 99.0717% completion rate therefore failed the 99.5% gate primarily
because of PT boundary censoring. Taxi last-five share and mean-duration ranges
were only 0.1694 percentage points and 0.120 minutes, so their final direction
is stable. GradeV2 remains a completed sensitivity result rather than an
adopted production configuration.
