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
