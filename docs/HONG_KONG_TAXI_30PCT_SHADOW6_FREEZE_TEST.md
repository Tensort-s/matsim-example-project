# Hong Kong Taxi 30% fleet and shadow-six frozen test

## Scope

This is an opt-in iteration-0 technical sensitivity test. It does not replace
the adopted Hong Kong production scenario or the completed physical-Taxi
50-iteration result. Its purpose is to test operational supply sampling while
keeping the behavioral Taxi demand and the full-fleet-equivalent road load
auditable.

## Frozen demand and operational expansion

The behavioral source is the original Candidate11 selected-plan population:

```text
/mnt/DiskM/by/hk_stage11_candidate10_corridor_signals_20260813_release11/
  input/plans_routed_selective_5pct_taxi_44000_no_ride.xml.gz
```

It contains 385,820 persons and exactly 44,000 selected Taxi legs. The
iteration-0 request audit from the completed Candidate5B formal run records
43,796 requests that were actually submitted; the remaining 204 Taxi legs were
not reached before the simulation horizon. Five operational-only one-trip
shadow passengers are created for each of those 43,796 submitted parent
requests. The resulting frozen population therefore contains:

| Item | Count |
|---|---:|
| Original persons | 385,820 |
| Original Taxi legs | 44,000 |
| Baseline-submitted parent requests | 43,796 |
| Operational-only shadow persons/legs | 218,980 |
| Output persons | 604,800 |
| Output Taxi legs | 262,980 |

Shadow persons carry `hkTaxiOperationalShadow=true` and
`expansionWeight=0.0`. They are excluded from behavioral demand, mode-share,
and score statistics. Their departure is deterministically sampled inside the
same 15-minute bucket as the parent. Origin and destination inherit the
parent's validated car links exactly; adjacent-link perturbation is prohibited
because adjacency does not guarantee reachability in a directed road graph.

The builder is:

```text
scripts/hong_kong_single_city/demand_generation/
  build_hong_kong_taxi_shadow_population.py
```

## Fleet and road-load equivalence

The operating fleet is 30% of 15,500 vehicles:

| Taxi type | Vehicles |
|---|---:|
| Urban | 3,925 |
| New Territories | 706 |
| Lantau | 19 |
| Total | 4,650 |

Every vehicle keeps capacity 4, the deterministic 18-hour service-window
approximation, and the established start-link sampling method. Actual vehicle
PCU is `1/6`. The launcher validates the road-supply basis using:

```text
actual Taxi PCU * operational fleet share
= (1/6) * 0.30
= 0.05 full-fleet-equivalent PCU
```

This preserves the Candidate5B registry's Taxi road-load basis while testing a
smaller explicit dispatcher fleet against six operational tasks per submitted
behavioral request.

## Fixed simulation configuration

- Candidate5B network and all-link explicit storage registry;
- Candidate11 traffic signals;
- calibrated experienced day-2 PT schedule and vehicles;
- PT routes rebuilt against that calibrated schedule;
- QSim 00:00--30:00;
- `stuckTime=3600 s`, `removeStuckVehicles=false`;
- 16 global and QSim threads;
- iteration 0 only;
- selected plans fixed, with no route, mode, time, household, or student joint
  innovation.

## Acceptance metrics

The primary service targets are mean wait 5--7 minutes, median wait 3--5
minutes, p90 no more than 10 minutes, p95 no more than 15 minutes, and an
unserved share below 0.5%. Request accounting must conserve exactly. Results
must be reported separately for all operational requests, original behavioral
passengers, and shadow passengers.

## Immutable attempts

All attempts are retained under `/mnt/DiskM/by`:

- `run1`: exited before QSim because the Java fleet-loader PCU whitelist had
  not yet included exact `1/6`;
- `run2`: exited before QSim because operational-only persons lacked the
  legacy per-person vehicle map expected by Walk bookkeeping;
- `run3`: reached QSim 06:11, then exposed that an adjacent car link can be
  unreachable in the directed graph; the error-path scorer also rejected the
  custom shadow activity type;
- `run4`: completed corrected attempt, using parent OD links and the existing
  `home` activity type. It reached 30:00 and exited with code 0.

No failed directory is overwritten or deleted.

## Run4 result and decision

The successful immutable run is:

```text
/mnt/DiskM/by/
  hk_stage11_candidate11_taxi_dvrp_20260822_freeze44k_shadow6_30pct_run4
```

Its release JAR SHA256 is
`076168a513b40b830e35bfa866ef53c8883494bd03aeac025fa98856c59db531`.
The run used 16 threads, took 19 minutes 25 seconds wall time, peaked at
23,722,096 KiB RSS, completed iteration 0 through QSim 30:00, and exited 0.
There was no fatal Java, OOM, XML, route, link, signal, or reference error.

Request accounting conserves exactly:

```text
244,716 submitted
= 35,331 completed
+ 205,199 waiting
+ 4,152 onboard
+ 34 rejected
```

The table below uses pickup wait only for requests that actually reached a
vehicle. This is the comparable service-time measure, but it is optimistic
under heavy censoring because the longest-waiting requests remain unpicked.

| Group | Submitted | Picked up | Completed | Mean wait | Median | P90 | P95 | Not picked by 30:00 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| All | 244,716 | 39,483 | 35,331 | 62.1 min | 29.0 min | 172.3 min | 215.2 min | 83.87% |
| Original behavioral | 25,736 | 6,977 | 6,951 | 21.1 min | 13.3 min | 41.7 min | 70.8 min | 72.89% |
| Operational shadow | 218,980 | 32,506 | 28,380 | 70.9 min | 46.8 min | 184.6 min | 223.8 min | 85.16% |

Only 25,736 of the 43,796 baseline-submitted original requests were reached in
this run. Earlier trips in the original multi-trip chains were delayed or
unfinished, while every one-trip shadow request was submitted independently.
Consequently, the run submitted 5.59 times the frozen baseline request count,
not exactly six times, and 9.51 times its own reached original requests. This
is an explicit limitation of the one-trip shadow approximation.

All 4,650 fleet vehicles were used. They completed 35,331 services, or 7.60
per fleet vehicle. Empty VKT was 274,064 km and occupied VKT was 467,510 km,
for an empty-distance share of 36.96%. Completed occupied trips averaged 18.7
minutes. At the horizon 4,152 passengers were still onboard; their median
elapsed onboard time was about 18.24 hours, which is evidence of persistent
network blockage, not ordinary Taxi ride duration.

The all-link storage audit corroborates that blockage. Relative to formal
iteration 49, links with blocked inflow increased from 646 to 1,586 and the
sum of blocked-inflow seconds increased from 44,764 to 15,385,599. More
importantly, the formal iteration-0 run using the same original plans recorded
1,039,026 blocked-inflow seconds, so the frozen sensitivity remains 14.8 times
higher without relying on a comparison to already-adapted iteration-49 plans.
The experiment's `1/6` vehicle PCU is mathematically equivalent at the
fleet-stock level to `15,500 * 0.05`, but the sixfold service demand also
expands occupied and empty Taxi movement. It is therefore not road-load-
equivalent at the VKT level. Larger per-vehicle PCU chunks and a 36.96%
empty-VKT share further amplify queue and signal effects.

This experiment is **technically validated but rejected as a calibrated Taxi
scenario**. It misses every wait and unserved target. It must not replace the
adopted formal run or be used as behavioral mode-share evidence; the 218,980
shadow persons have zero behavioral expansion weight but MATSim's default raw
mode statistics still count them unless explicitly filtered.
