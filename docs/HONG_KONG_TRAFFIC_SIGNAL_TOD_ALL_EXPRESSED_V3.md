# Hong Kong all-expressed 15-minute TOD traffic-signal candidate

Status: `all_expressed_tod_15min_runtime_validated_performance_gate_failed_not_adopted`.

## Scope and baseline

This Stage-2 expansion is built from the road-hotspot materialized signal
baseline used by signal run8. Its Stage-1/1.5 input is:

```text
data/transit/hongkong/processed/
  hong_kong_traffic_signals_2026_v3_tpdm_proxy_stage1_road_hotspot_v1_candidate8/
```

The rebuildable all-expressed output is:

```text
data/transit/hongkong/processed/
  hong_kong_traffic_signals_2026_v3_tod_proxy_all_expressed_road_hotspot_v1_candidate8/
```

The dedicated build entry point is:

```text
scripts/hong_kong_single_city/transit_supply/
  build_hong_kong_traffic_signal_tod_proxy_all_expressed.py
```

It does not add run68 Car-origin repairs, parking, U-turn restrictions,
household-plan changes, or ordinary innovation. Signal activation remains an
explicit opt-in and the no-signal road-hotspot baseline remains available.
Production `city.yaml`, the run manifest, and production inputs are unchanged.

## Uniform activation rule

Stage 1 contains exactly 2,054 registry groups:

- 1,930 are `network_expression_status=expressed`;
- 101 remain `review`;
- 23 remain `unexpressed`.

Every expressed group is passed through the same safety rule. A group is
activated only if at least one non-U-turn movement remains after the registry-
overlap exclusion. This produces 1,929 active signal systems. The single
explicit exclusion is `TS_OSM_0185`: every movement is removed by the U-turn
or overlap safety filter, so a non-empty MATSim signal system cannot be built
without reactivating an unsafe reference. It is retained in
`junction_activation_exclusions.csv`, not silently discarded.

The eight public-diagram examples (`TS_K005`, `TS_K006`, `TS_K008`,
`TS_K024`, `TS_K025`, `TS_K101`, `TS_K118`, and `TS_K201`) receive no special
selection, stage, timing, or priority rule. Diagram membership is provenance
only. Static validation confirms all eight are included and
`diagram_special_treatment_count=0`.

Approaches retaining executable movements are clustered by the same
unoriented-bearing rule used by the Top-100 candidate. This uniformly supports
one through five inferred axes. One-axis systems receive one vehicular stage;
they are not evidence of a competing cross direction. Five-axis systems use
five sequential proxy stages. No protected right-turn stage is inferred
without lane-to-movement evidence.

## Timing and capacity

Each active system has 96 non-overlapping fixed 15-minute plans. Within a bin,
cycle and green splits remain unchanged. The rules are unchanged from run8:

- planned route-propagated movement demand is converted to TPDM PCU/h;
- each stage uses its critical approach flow ratio;
- cycles are selected from 60, 75, 90, and 100 seconds;
- minimum green is 7 seconds;
- controller clearance is 6 seconds, corresponding to the audited 5-second
  event intergreen with 3-second amber and 2-second red+amber semantics;
- adjacent 15-minute bins may move by at most one cycle grade;
- controlled final approaches use the TPDM saturation proxy to avoid applying
  practical-capacity loss and signal `g/C` twice;
- offsets remain zero and pedestrian phases remain absent.

## Static result

The generated candidate contains:

| Item | Count |
|---|---:|
| Expressed registry groups considered | 1,930 |
| Active signal systems | 1,929 |
| Explicit activation exclusions | 1 |
| Plans | 185,184 |
| Signal groups/stages | 3,742 |
| Executable signal movement boundaries | 8,010 |
| Controlled approaches with capacity treatment | 5,570 |
| Group windows | 359,232 |

Stage counts are 480 one-stage, 1,124 two-stage, 288 three-stage, 35
four-stage, and 2 five-stage systems. Cycle counts are 173,071 at 60 seconds,
3,477 at 75 seconds, 2,693 at 90 seconds, and 5,943 at 100 seconds. Of the
185,184 plans, 5,401 use the capped oversaturated proxy.

The Python and MATSim XML validators report zero:

- missing or non-adjacent controlled turns;
- active U-turns;
- missing plan-to-group references;
- adjacent cycle-grade violations;
- diagram-specific treatment.

The candidate network preserves node/link IDs and topology. It changes only
the 5,570 audited controlled-approach capacities. MATSim compilation writes
`signal_systems.xml`, `signal_groups.xml`, `signal_control.xml`,
`amber_times.xml`, and `intergreen_times.xml` successfully.

## Frozen runtime gate: release9/run9

The authorized full candidate was uploaded without overwriting prior results:

```text
/mnt/DiskM/by/hk_traffic_signals_tod_all_expressed_road_hotspot_20260813_payload1
/mnt/DiskM/by/hk_stage11_road_hotspot_all_expressed_signals_20260813_release9
/mnt/DiskM/by/hk_stage11_road_hotspot_all_expressed_signals_20260813_run9
```

Run9 uses release7/run7 as its unchanged road-hotspot baseline, iterations
0--1, a 30:00 horizon, `KeepLastSelected` only, physical non-Taxi modes,
unlimited ordinary PT capacity, and explicit `--traffic-signals`. The process
completed with exit code 0. Its signal-event audit observed all 1,929 systems
and all 3,742 groups, with 26,345,537 state-change events and zero missing
groups, conflicting simultaneous greens, intergreen, amber, red+amber, or
cycle-duration violations. The 1,929 terminal truncations are expected at the
30:00 event-stream boundary and are not counted as violations.

Of 5,570 controlled approaches, 5,482 carried traffic. They recorded 4,335,036
entries: 1,229,282 private Car, 1,972,793 Bus, 1,075,621 GMB, and 57,340
school-bus. Relative to run7 on the same approach set, entries changed by
-18,692 Car, -2,199 Bus, -447 GMB, and +100 school-bus.

The frozen physical-mode audit passed. The student audit also passed: all
1,003 selected school-bus legs depart, board, alight, and arrive; it reports
no plan-mode mismatch, bad route, wrong vehicle, stuck selected student, or
terminal load. The performance gate nevertheless did not pass:

| Metric, iteration 1 | run7 no signal | run8 Top-100 | run9 all expressed |
|---|---:|---:|---:|
| Total road delay (veh-h) | 52,383.98 | 59,167.95 | 73,950.69 |
| Road-vehicle stuck | 1,959 | 2,028 | 2,276 |
| Private Car stuck | 967 | 950 | 1,124 |
| Bus stuck | 536 | 575 | 666 |
| GMB stuck | 453 | 500 | 483 |
| School-bus stuck | 3 | 3 | 3 |
| Links with >=100 traversals and mean ratio >2 | 1,788 | 2,192 | 4,773 |

Run9 road delay is 41.17% above run7 and 24.99% above run8; road-vehicle
stuck is 16.18% above run7 and 12.23% above run8. The result proves that the
uniform all-expressed signal XML is mechanically executable, but not that its
uniform proxy timing is acceptable. It remains an opt-in sensitivity and must
not replace the production network, `city.yaml`, or run manifest. The next
iteration should calibrate or selectively deactivate the worst run9 signal-
induced delay locations, with particular attention to Bus performance, rather
than expanding scope further.

The full road audit is retained at:

```text
/mnt/DiskM/by/hk_road_network_audit_20260813_all_expressed_signal_run9_v1
```

The signal runtime auditor was also changed from repeated suffix scans to
binary-search lookup of the next state transition. This preserves the audit
semantics while avoiding quadratic post-processing at territory-wide scale.

## Stuck-time sensitivity: release10a/run10a

A controlled sensitivity changes only QSim `stuckTime` from 600 to 3,600
seconds. `removeStuckVehicles=true`, the 30:00 horizon, network, plans,
transit supply, signal XML, frozen innovation, and all other run settings are
unchanged. Network and signal-control SHA256 values match run9. The new paths
are:

```text
/mnt/DiskM/by/hk_stage11_road_hotspot_all_expressed_signals_stuck3600_20260813_release10a
/mnt/DiskM/by/hk_stage11_road_hotspot_all_expressed_signals_stuck3600_20260813_run10a
```

An earlier release10 creation attempt used release9 as a launcher base and
stopped before any run when the existing `traffic_signals_tod` directory made
the fail-closed copy operation refuse an overwrite. Its partial release
directory is retained for provenance; no run10 directory or MATSim result was
created. Release10a correctly rebuilds from release7 plus the same validated
payload used by run9.

Run10a exits zero, but the higher threshold worsens road blocking:

| Iteration-1 metric | run9, 600 s | run10a, 3,600 s | Change |
|---|---:|---:|---:|
| Road-vehicle `stuckAndAbort` | 2,276 | 13,552 | +495.43% |
| Before 30:00 | 2,231 | 2,034 | -8.83% |
| At the 30:00 terminal bucket | 45 | 11,518 | +11,473 |
| Private Car stuck | 1,124 | 4,624 | +311.39% |
| Bus stuck | 666 | 5,132 | +670.57% |
| GMB stuck | 483 | 3,796 | +685.92% |
| School-bus stuck | 3 | 0 | -3 |
| Total road delay (veh-h) | 73,950.69 | 136,771.83 | +84.95% |
| Road-link traversals | 23,843,160 | 22,507,755 | -5.60% |
| Links with >=100 traversals and mean ratio >2 | 4,773 | 5,276 | +10.54% |

The threshold postpones some ordinary aborts, but blocked vehicles remain on
the network longer and propagate queues. At 30:00 MATSim emits
`stuckAndAbort` for the remaining road vehicles, producing 11,518 terminal-
bucket events. Consequently the lower pre-terminal count is not an operational
improvement. `stuckTime=3600` is rejected for this scenario; run9's 600-second
setting remains the reference sensitivity, without implying that run9 itself
passes the signal performance gate.

The road auditor now finalizes an active vehicle when its road
`stuckAndAbort` is seen and labels only vehicles still active after the event
stream as `terminal_active`. This prevents an aborted trip from also being
reported as unfinished. Recomputed run9 and run10a summaries are retained at:

```text
/mnt/DiskM/by/hk_road_network_audit_20260813_all_expressed_signal_run9_terminal_v2
/mnt/DiskM/by/hk_road_network_audit_20260813_all_expressed_signal_stuck3600_run10a_terminal_v2
```
