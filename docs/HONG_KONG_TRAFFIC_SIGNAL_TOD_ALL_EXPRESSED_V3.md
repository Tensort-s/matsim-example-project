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

## Candidate9 corrective rebuild

Candidate9 is a local, rebuildable successor to the failed run9 payload. It
does not overwrite candidate8 or adopt signals into production. Its output is:

```text
data/transit/hongkong/processed/
  hong_kong_traffic_signals_2026_v3_tod_proxy_all_expressed_road_hotspot_v1_candidate9/
```

The corrective build makes three bounded changes before generating TOD plans:

1. Each physical incoming link receives one signal-system owner. Registry
   identities are preferred over pure OSM identities; ties use Stage-1
   confidence, peak demand, daily demand, then stable ID. This resolves all 11
   run9 cross-system incoming-link overlaps. The displaced movements remain in
   `cross_system_control_ownership_audit.csv`.
2. A system with fewer than two modeled vehicle stages is not compiled. This
   removes the 480 run9 one-stage systems without introducing an always-red or
   periodic-clearance penalty. Ownership resolution additionally leaves
   `TS_K562`, `TS_K732`, and `TS_OSM_0107` with one stage, so they are also
   deactivated; `TS_OSM_0178` and `TS_OSM_0056` lose their only controlled
   approaches. The complete disposition is in
   `junction_deactivation_audit.csv`.
3. The 25 highest run9 controlled-approach delay systems are explicitly
   reviewed through the tracked
   `cities/hongkong/traffic_signal_priority_junction_overrides_v1.csv` file.
   Seven overfragmented geometry proxies use a bounded 40-degree axis
   tolerance: `TS_H182`, `TS_K019`, `TS_NT689`, `TS_K484`, `TS_NT659`,
   `TS_H222`, and `TS_K010`. Sixteen retain their safer existing two-axis
   structure for later timing calibration; `TS_NT401` and `TS_NT542` are
   deactivated as one-stage systems.

`TS_H182` changes from five singleton stages to three stages. Its maximum
15-minute critical-flow-ratio sum falls from 1.56 to 1.25 and its capped
oversaturated bins fall from 52 to 29. The change is still a geometry proxy,
not an observed lane-level phase plan.

The rebuilt package contains 1,445 active systems, 3,243 groups, 6,941
executable movement boundaries, 138,720 plans, and 4,719 capacity-treated
approaches. Python validation and MATSim compilation pass with zero active
single-stage systems, cross-system controlled links, missing or non-adjacent
turns, U-turns, plan/group reference failures, or topology/ID changes. The
eight public-diagram junctions still receive no special treatment.

Candidate9 has not yet had a frozen runtime A/B test. It remains an explicit
opt-in candidate and does not change `city.yaml`, the run manifest, or the
no-signal baseline. A new server release/run must use new paths and compare
against release7/run7 before any adoption decision.

## Candidate10 short-block corridor offsets

Candidate10 is a local, rebuildable derivative of candidate9. Its output is:

```text
data/transit/hongkong/processed/
  hong_kong_traffic_signals_2026_v3_tod_proxy_all_expressed_road_hotspot_v1_candidate10_corridor/
```

The builder is
`scripts/hong_kong_single_city/transit_supply/coordinate_hong_kong_traffic_signal_corridors.py`.
It follows each candidate9 executable `ahead` movement from stop line to stop
line through the road topology. A directed connection is retained only when
the continuation is unique, changes direction by no more than 25 degrees, and
reaches the next signal in 5--250 metres. A corridor needs at least three
systems, a linear non-branching topology, end-to-end ahead-group continuity,
and at least four valuable 15-minute bins. A valuable bin requires mean
directional demand of at least 400 PCU/h, every block at least 100 PCU/h, a
1.25 directional dominance ratio, equal cycles, and no internal 100-second or
oversaturated system. Isolated single bins are removed.

The all-network search finds 1,128 directed signal connections and 40 linear
corridors with modeled demand value. Fourteen pass all implementation gates;
six are excluded because they share a system with a higher-value corridor,
and twenty fail the fixed-offset safety/alignment gate. The implemented set
contains 47 distinct systems and 350 valuable corridor/time-bin combinations.
No implemented system belongs to two corridors.

MATSim changes plan objects exactly at 15-minute boundaries and does not reset
the old group state. Candidate10 therefore uses one fixed daily offset per
implemented system rather than jumping offset at a TOD boundary. The 96 TOD
plans still retain their candidate9 cycles and green splits; TOD demand is
used to select the primary coordination direction and valuable periods. Each
fixed offset minimizes error against those valuable bins and must have mean
alignment error no greater than 10 seconds and maximum error no greater than
18 seconds. The daily leader remains at zero. This produces 33 non-zero-offset
systems and 3,168 non-zero-offset plans. Candidate10 applies no offset to the
remaining 1,398 systems.

The implemented blocks are 46.596--245.677 metres long, mean 137.0 metres.
No 5--25 metre storage-critical block passes all topology, demand and safety
gates, so candidate10 does not claim a near-synchronous short-storage repair.
The complete results and exclusions are recorded in:

```text
signal_corridor_registry.csv
signal_corridor_links.csv
tod_corridor_direction_15min.csv
tod_corridor_offsets.csv
corridor_exclusions.csv
```

MATSim XML compilation and the generic signal validator pass. The dedicated
corridor validator confirms that only `offset_s` changes relative to
candidate9: network, capacity, systems, groups, movements, green windows,
cycles and green splits are byte-identical or field-identical as applicable.
It also reports zero out-of-cycle offsets, unsafe TOD plan transitions,
multi-corridor systems, or compiled-XML offset mismatches.

## Candidate10 frozen runtime gate: release11/run11

Candidate10 was tested through iterations 0--1 without overwriting any prior
result:

```text
/mnt/DiskM/by/hk_traffic_signals_candidate10_corridor_20260813_payload1
/mnt/DiskM/by/hk_stage11_candidate10_corridor_signals_20260813_release11
/mnt/DiskM/by/hk_stage11_candidate10_corridor_signals_20260813_run11
/mnt/DiskM/by/hk_road_network_audit_20260813_candidate10_corridor_run11_v4
```

The comparison keeps release7's network/plans/transit supply, the run7 JAR,
iterations 0--1, a 30:00 horizon, `stuckTime=600`, `KeepLastSelected`, physical
non-Taxi modes, and unlimited ordinary PT capacity. Run11 exits zero. The
physical-mode audit passes. The student audit passes its binding and route
checks, but one of 1,003 selected school-bus legs is stuck and does not alight
or arrive, so it is `validated_with_network_stuck_limitations`.

| Iteration-1 metric | run7 no signal | run8 Top-100 | run9 all expressed | run11 Candidate10 |
|---|---:|---:|---:|---:|
| Total road delay (veh-h) | 52,383.98 | 59,167.95 | 73,950.69 | 71,585.16 |
| Road-vehicle stuck | 1,959 | 2,028 | 2,276 | 2,422 |
| Private Car stuck | 967 | 950 | 1,124 | 1,162 |
| Bus stuck | 536 | 575 | 666 | 667 |
| GMB stuck | 453 | 500 | 483 | 585 |
| School-bus stuck | 3 | 3 | 3 | 8 |
| Links with >=100 traversals and mean ratio >2 | 1,788 | 2,192 | 4,773 | 4,816 |

Against run9, Candidate10 lowers delay by 3.20% but raises road-vehicle stuck
by 6.41%. Against no-signal run7, delay remains 36.65% higher and road-vehicle
stuck 23.63% higher. The largest stuck deterioration is GMB (+102 versus
run9), while Bus is essentially unchanged (+1). Run9 predates the Candidate9
ownership/deactivation/stage corrections, and Candidate9 has no separate
runtime run. The run9-to-run11 change therefore measures the combined
Candidate9-plus-corridor package and cannot identify the offset-only causal
effect.

The signal event gate fails for a separate controller reason. All 1,445
systems and 3,243 groups are observed, with zero missing groups, conflicting
simultaneous greens, intergreen, amber, or red+amber violations. However, 47
cycle-duration discontinuities occur in 11 offset systems. Every violation is
at or within one second of a 15-minute plan boundary. Thus the static
Candidate10 assumption that a repeated fixed offset would preserve phase
continuity across MATSim TOD plan replacement is false at runtime. The
controller still restarts/repositions affected programs at plan changes.

Candidate10 therefore fails both the signal-mechanics gate and the road
performance gate. It remains a rejected, opt-in historical sensitivity. It
does not update `city.yaml`, the run manifest, or the production/no-signal
baseline. Any later corridor attempt must avoid 96 independently replaced
offset plans, or implement a controller whose phase clock is explicitly
continuous across TOD timing changes.

## Candidate11 safe TOD boundaries: release12/run12

Candidate11 retains Candidate10's 47 selected corridors, groups, cycle
lengths, green splits and offsets, but moves each corridor system's complete
set of 96 TOD plan boundaries to its fixed daily offset. This makes every plan
replacement occur at the same stage-1 phase position on both sides of the
boundary. Thirty-three systems require a non-zero shift; the maximum shift is
53 seconds. No continuous-clock controller is introduced.

The full frozen iterations 0--1 validation used new, non-overwriting paths:

```text
/mnt/DiskM/by/hk_traffic_signals_candidate11_safe_boundaries_20260813_payload1
/mnt/DiskM/by/hk_stage11_candidate11_safe_boundaries_20260813_release12
/mnt/DiskM/by/hk_stage11_candidate11_safe_boundaries_20260813_run12
/mnt/DiskM/by/hk_road_network_audit_20260814_candidate11_safe_boundaries_run12_v2
```

Run12 retains release11's network, plans, transit supply, cost inputs and
application JAR; only the Candidate11 signal XML changes. It uses a 30:00
horizon, `stuckTime=600`, iterations 0--1, and zero weight for ordinary
`ReRoute`, `SubtourModeChoice`, and `TimeAllocationMutator`. The explicitly
enabled household-joint and student-school selectors remain active between
iterations. Run12 exits zero. Iteration-0/1 QSim `lost` counts are 5,993 and
3,617, versus 5,961 and 3,656 in Candidate10 run11.

The signal event audit passes. All 1,445 systems and 3,243 groups are seen;
there are zero missing groups, blocking simultaneous greens, intergreen,
amber, red+amber, or cycle-duration violations. In particular, Candidate10's
47 runtime cycle discontinuities fall to zero. The 1,418 terminal transition
truncations are states cut off by the configured 30:00 simulation horizon and
are not blocking violations.

| Iteration-1 metric | run7 no signal | run11 Candidate10 | run12 Candidate11 |
|---|---:|---:|---:|
| Total road delay (veh-h) | 52,383.98 | 71,585.16 | 72,010.88 |
| Road-vehicle stuck | 1,959 | 2,422 | 2,390 |
| Private Car stuck | 967 | 1,162 | 1,114 |
| Bus stuck | 536 | 667 | 690 |
| GMB stuck | 453 | 585 | 578 |
| School-bus stuck | 3 | 8 | 8 |
| Links with >=100 traversals and mean ratio >2 | 1,788 | 4,816 | 4,808 |

Relative to Candidate10, Candidate11 raises total road delay by 0.59% and
reduces road-vehicle stuck by 1.32%. Relative to the paired no-signal run7,
delay remains 37.47% higher and road-vehicle stuck 22.00% higher. Candidate11
therefore passes the signal-mechanics/period-continuity gate but fails the road
performance gate. It remains an opt-in research candidate and does not update
`city.yaml`, `run_manifest.json`, or the production/no-signal baseline.

## Candidate11 ordinary-innovation integration gate

The next technical gate keeps the complete Candidate11 signal package and the
same physical household escort, student-school, road, PT and cost inputs, but
opens ordinary individual replanning through a new explicit runner option:

```text
--household-joint-plan-with-ordinary-innovation
```

Without this option, the existing household/student entry point retains its
historical frozen-strategy guard. With it, every ordinary resident, visitor
and mainland-Hong-Kong-resident subpopulation must have positive
`ChangeExpBeta`, `ReRoute`, `SubtourModeChoice`, and
`TimeAllocationMutator_ReRoute` weights. The last strategy mutates activity
times and then reroutes the complete trip, so a PT passenger can choose a new
departure time and rebuild the itinerary against the applicable scheduled
departure rather than retaining a stale boarding route. Private-Car routing
uses the same experienced-link energy and toll rules as scoring.

Household joint/escort candidates and student-school-mode candidates cannot be
independently mutated without breaking shared vehicle waypoints or the
separately audited school-mode choice. The runner therefore assigns their
47,867 distinct people to `hk_household_student_protected`, whose only
ordinary strategy is `KeepLastSelected`. The one-shot joint selector remains
active after iteration 0 and installs the same independently evaluated
escort/student candidates. This is a protected candidate module inside an
otherwise open-innovation run, not a claim that these 47,867 people optimize
individual plans independently.

Opening Car mode choice expands the possible parking-destination universe far
beyond the 1,266 exact repairs used by the earlier household driver-switch
gate. The reproducible builder
`scripts/hong_kong_single_city/demand_generation/prepare_hong_kong_open_innovation_parking_zones.py`
audits all 228,220 activity facilities. Of these, 44,499 already have a unique
zone in the Car feasibility table and 1,266 use the accepted repair table. It
adds 182,441 strict point-within Census/DCCA assignments, producing 183,707
repair rows and zero uncovered non-border facilities. New-Town polygons take
deterministic precedence at the five exact polygon overlaps. No nearest-zone
or default-zone fallback is allowed. All 14 `border_*` facilities remain
explicitly unpriced because parking at a cross-boundary model anchor has no
defensible TCS interpretation.

The 22,578 non-special people whose initial plan contains a `border_*`
activity are assigned to `hk_unpriced_border_no_car_mode_innovation`. They
retain `ChangeExpBeta`, `ReRoute`, and `TimeAllocationMutator_ReRoute`, but do
not receive `SubtourModeChoice`; the runner also fails at startup if any such
initial plan already contains Car. Thus PT schedule-time adaptation remains
available while the model cannot invent an unpriced cross-boundary Car tour.

Server provenance is retained under new, non-overwriting paths:

```text
/mnt/DiskM/by/hk_stage11_candidate11_open_innovation_20260814_release13
/mnt/DiskM/by/hk_stage11_candidate11_open_innovation_20260814_run13
/mnt/DiskM/by/hk_stage11_candidate11_open_innovation_20260814_run13a
/mnt/DiskM/by/hk_stage11_candidate11_open_innovation_20260814_release14
/mnt/DiskM/by/hk_stage11_candidate11_open_innovation_20260814_run13b
/mnt/DiskM/by/hk_stage11_candidate11_open_innovation_20260814_run13c
/mnt/DiskM/by/hk_stage11_candidate11_open_innovation_20260814_release15
/mnt/DiskM/by/hk_stage11_candidate11_open_innovation_20260814_run13d
/mnt/DiskM/by/hk_stage11_candidate11_open_innovation_20260814_release16
/mnt/DiskM/by/hk_stage11_candidate11_open_innovation_20260814_run13e
/mnt/DiskM/by/hk_stage11_candidate11_open_innovation_20260814_audit13e_v3
/mnt/DiskM/by/hk_road_network_audit_20260814_candidate11_open_innovation_run13e_v2
```

The first `run13` failed before scenario loading because its rewritten config
lost the MATSim DOCTYPE. `run13a` proved exact iteration-0 parity with frozen
run12 (score, mode shares and QSim `lost=5,993`) and executed 31,931 ordinary
ReRoute, 47,772 SubtourModeChoice and 16,057 time-mutation/reroute strategies,
but stopped in iteration 1 when a newly chosen Car destination lacked a TCS
zone. `run13b` stopped before model loading because the thin Maven JAR was
uploaded instead of the repository-root shaded JAR. These outputs are failed
diagnostics and must not be analyzed as completed simulations. Release14 adds
the full exact facility-zone candidate and corrected shaded JAR. `run13c`
completes iteration 1 and proves that the parking-universe repair works, but
fails at the start of iteration 2 when a previously released, non-candidate
`car_passenger` plan returns from ordinary plan memory. Release15/run13d adds
every person whose initial plan contains `car_passenger` to the protected
union (112 additional people, 47,867 total). Run13d nevertheless fails in
iteration 2 when a temporary unbound `car_passenger` template is selected
from ordinary MATSim plan memory. Subpopulation protection alone is therefore
insufficient: the one-shot choice templates are implementation artifacts, not
admissible plans.

Release16 removes all 26,780 temporary templates immediately after the
one-shot household/student selector installs 42,549 selected composite plans.
The templates remain available during exact candidate evaluation but cannot
be selected by later generic strategies. The targeted Java suite passes, and
run13e exits zero through iteration 10. It preserves exact iteration-0 parity
with run12: average score 14.8630959, identical mode shares and QSim
`lost=5,993`.

At iteration 10 the average executed score is 30.4505981 and `lost=300`, a
94.99% reduction from iteration 0. Final shares are 6.125% Car, 0.520% bound
`car_passenger`, 51.149% PT, 8.681% Taxi and 33.525% Walk. The large
ten-iteration PT-to-Walk shift proves ordinary mode choice is active, but is
also a calibration warning: run13e is an integration/stability gate, not an
adopted behavioral equilibrium.

The iteration-0/10 audit directly verifies every requested innovation path.
Among 28,656 Car legs alignable by person and leg ordinal, 9,411 change their
network-link sequence. Of 343,395 trips retaining PT, 86,798 change main-trip
departure time, 87,173 change first PT boarding time, and 156,895 change the
transit service/vehicle sequence. Common-trip departure offsets have
p05/p50/p95 of -1,110/0/+1,240 seconds. The final plan file contains
1,375,073 plans and zero temporary household-joint templates.

The protected modules remain physical. The selector evaluates 9,289 joint
pairs in 5,789 households, installs 3,865 active bindings and selects 1,018
independent school-bus trips. In iteration 10, 3,764 of 3,865 escort rides
complete; other outcomes are classified as traffic-stuck or beyond the 30:00
horizon. No unbound passenger exception occurs. Dynamic Car costing records
4,422,285 link entries, 16,283 tolled entries and 28,208 parking events with
zero parking-facility mismatches.

The iteration-10 signal event audit remains `validated`: all 1,445 systems
and 3,243 groups appear in 22,781,520 state events, with zero missing groups,
conflicting simultaneous greens, intergreen, amber, red+amber or cycle-time
violations. The listed incomplete transitions are states truncated by the
30:00 simulation horizon, not controller discontinuities.

The separate iteration-10 road audit excludes ordinary PT-passenger and
non-road stuck events. It records 21,479,800 road-link traversals, 19,493.38
vehicle-hours of delay and 126 road-vehicle stuck events: 84 private Car, 29
Bus, 13 GMB and zero school bus. There are 3,539 links with at least 100
traversals and mean travel-time ratio above two. These are run13e absolute
outcomes, not a new signal/no-signal causal A/B; the valid signal adoption
comparison remains the paired frozen run12-versus-run7 gate.

Run13e remains opt-in. It does not update `city.yaml`, `run_manifest.json`, or
the production/no-signal baseline. Candidate11 already failed the paired
frozen road-performance adoption gate; ordinary adaptation does not convert
that earlier causal A/B into signal-performance acceptance.

### Candidate11 open Taxi/Walk 20-QSim follow-on

The follow-on sensitivity keeps the same Candidate11 network, signal XML,
plans, schedule and protected candidate registries. Its active immutable
server attempt is:

```text
/mnt/DiskM/by/hk_stage11_candidate11_open_taxi_walk_20260814_release18
/mnt/DiskM/by/hk_stage11_candidate11_open_taxi_walk_20260814_run14a
```

The first `release17/run14` attempt is retained as a pre-iteration failure:
the compact release16 PT mirror omitted one adopted light-rail fare parquet.
run14a restores the exact provenance split used by run13e: complete PT fares
from release11 and dynamic Car tables from release16. It completed all-person
route preparation and entered iteration 0 on 2026-08-14. Its behavioral and
output contract is recorded in
`docs/HONG_KONG_CANDIDATE11_OPEN_TAXI_WALK_20QSIM.md`; it remains opt-in and
cannot change Candidate11's earlier frozen signal A/B rejection.
