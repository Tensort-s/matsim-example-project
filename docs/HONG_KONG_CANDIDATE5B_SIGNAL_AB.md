# Hong Kong Candidate5B signal A/B

## Status

This is a frozen iteration-0 sensitivity comparison, not an adopted production
scenario. It holds the selected plans, physical network, QSim-only road-supply
registry, transit supply, finite Taxi fleet, Taxi PCU, simulation horizon, and
stuck policy fixed. The sole modeled treatment is Candidate11 movement-level
time-of-day traffic signals.

The first signal attempt (`...candidate5b_signal_pcu005_it0_run1`) is retained
as invalid failure evidence. MATSim's signals QSim module replaced the
Candidate5B `QNetworkFactory`, so none of the 86,417 explicit storage queues
was built. The combined factory now preserves signal turn acceptance while
also applying exact per-link QSim storage and flow. A focused signal-plus-road
supply integration test passes before the corrected server run.

## Frozen contract

| Item | Both arms |
|---|---|
| Plans | `plans_routed_selective_5pct_taxi_44000_no_ride.xml.gz`, SHA256 `393dd896...855` |
| Persons / planned main trips | 385,820 / 743,614 |
| Physical network | Candidate5B `network_tpdm3_physical_candidate5b.xml.gz`, SHA256 `2cc70f0e...7979` |
| Road supply | Candidate5B registry, 86,417 storage overrides and 3,097 QSim-flow overrides |
| Transit supply | original Candidate10/Candidate11 runtime schedule and vehicles |
| Taxi | 15,500 reusable DVRP vehicles, PCU 0.05 |
| QSim | iteration 0, 16 threads, 00:00--30:00, `stuckTime=3600`, `removeStuckVehicles=false` |

The no-signal arm is:

```text
/mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260818_candidate5b2_pcu005_it0_run1
```

The corrected signal arm is:

```text
/mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260818_candidate5b_signal_pcu005_it0_run2
```

It uses Candidate11 safe-boundary TOD control: 1,445 systems, 3,243 groups,
and 6,941 controlled movements. Static network/signal compatibility has zero
missing or invalid references. Runtime records 22,781,520 state changes; all
1,445 systems and all 3,243 groups execute through 108,000 seconds.

## Results

| Metric | No signals | Candidate11 signals | Change |
|---|---:|---:|---:|
| Completed trips | 705,282 | 722,568 | +17,286 |
| Completion rate | 94.8452% | 97.1698% | +2.3246 pp |
| Raw mean time of completed trips | 44.539 min | 46.213 min | +1.674 min |
| Mean change on 704,685 trips completed in both | -- | -- | +1.835 min |
| Active agents at 30:00 | 24,971 | 10,913 | -14,058 |
| QSim lost | not used as trip denominator | 5 | descriptive only |

The mode rows below describe completed trips. The selected input plan is the
same in both arms, so changes in completed-mode share are execution effects,
not iteration-0 mode choice.

| Main mode | Completed, no signal | Completed, signal | Change | Mean time change | Same-trip mean change |
|---|---:|---:|---:|---:|---:|
| Car | 66,654 | 67,418 | +764 | +5.267 min | +5.334 min |
| Car passenger | 2,734 | 2,734 | 0 | 0 | 0 |
| PT | 513,201 | 527,346 | +14,145 | +1.583 min | +1.625 min |
| Taxi | 41,588 | 43,665 | +2,077 | +2.703 min | +2.511 min |
| Walk | 81,105 | 81,405 | +300 | -0.146 min | 0 |

Signals therefore improve horizon completion but impose additional travel
time on already-completing network trips. The raw mean is not interpreted in
isolation: the signal arm completes 17,883 trips that the no-signal arm does
not, while only 597 trips complete exclusively without signals. Those newly
completed signal-arm trips average 40.439 minutes.

## Mechanism and technical QA

The result is consistent with signal metering reducing destructive spillback
at the aggressive Candidate5B flow overrides:

- PT waiting before first boarding falls from 17,148 to 10,547;
- unresolved onboard/transfer PT states fall from 2,608 to zero;
- private-car stuck states fall from 315 to 1;
- regular-PT-vehicle stuck states fall from 2,374 to 9;
- Taxi-vehicle stuck states fall from 1,090 to zero;
- blocked seconds on the 3,097 flow-override links fall 76.35%.

Network-wide blocked seconds increase 7.13% and blocked links increase from
714 to 1,288. This is not contradictory: red phases create bounded queues on
more approaches, while the most damaging high-flow connector chains cease
blocking for hours. The `road_104307_0_r -> road_104308_0_f` example has zero
blocked-inflow seconds under signals, versus 1,319 and 2,814 seconds without
signals.

Taxi requests remain conserved in both arms. Signals increase completed Taxi
requests from 41,588 to 43,665 and reduce horizon backlog from 1,096 to 7, but
waits rise (p50 37 to 41 seconds; p90 122 to 170; p99 516 to 684). Empty VKT
share is nearly unchanged at 4.53% versus 4.59%.

The corrected run exits zero. Requested and actual storage differ by at most
`1.64e-13` PCU, QSim-flow difference is zero, signal references are complete,
all signal systems/groups execute, and Taxi accounting conserves requests.
This is a technical and iteration-0 performance pass, but it does not by
itself adopt signals or prove multi-iteration stability.

Machine-readable comparison output is:

```text
...candidate5b_signal_pcu005_it0_run2/
  candidate5b_signal_ab_acceptance_v1/
```

## PT-time calibration follow-up

The signal plan is intentionally unchanged in the next frozen test. Rebuilding
ordinary PT itineraries against the experienced-time/day-2 supply raises
completion from 97.1698% to 98.4483% and lowers the common-completed-trip mean
by 1.809 minutes. Combined unresolved PT passenger states fall 45.54%, while
all-link blocked seconds rise 0.974%. Regular PT vehicle stuck events at the
30:00 horizon rise from 9 to 850, so this is a passed passenger-performance
test but not a production adoption. Full provenance and limitations are in
`HONG_KONG_EXPERIENCED_PT_TIMETABLE_V1.md`.
