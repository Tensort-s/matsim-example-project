# Hong Kong traffic-signal V3 — Top-100 time-of-day proxy

Status: `top100_tod_15min_proxy_candidate_not_adopted`

## Purpose and scope

This bounded Stage-2 MVP creates a basic runnable signal network for the 100
highest-demand safely expressible registry junctions. It deliberately does not
claim official timing recovery or lane-level precision. Every junction has 96
non-overlapping 15-minute MATSim plans; there is no AM plan reused all day.
The stage template stays fixed during the day, while cycle and green duration
are fixed within each 15-minute bin and may change only at its boundary.

The candidate is opt-in. It changes neither `city.yaml`, the run manifest, nor
the current production network. Its separate candidate network changes only
the 391 controlled final-approach capacities to the Stage-1 TPDM saturation
proxy so that practical junction capacity is not counted once in the network
and again through `g/C`. Node and link IDs and topology remain unchanged.

## Selection and topology boundary

The builder ranks Stage-1.5 junctions by maximum 15-minute planned TPDM PCU/h,
then daily PCU and stable junction ID. Eligibility requires `expressed`, no
unresolved shared-registry path, planned demand, and two to four inferred road
axes. This avoids one-axis sites with no competing vehicular phase and
five-plus-axis sites that are too ambiguous for this MVP. The rank-100 cutoff
is 5,444 TPDM PCU/h.

Full physical movements remain the Stage-1 unit. For MATSim execution they are
collapsed only where necessary to the stable adjacent boundary
`fromLink -> first internal link` (or direct exit). The result has 566 signals
over 391 approach links. All controlled link pairs exist, are adjacent, and
contain no U-turn. No network ID depends on CSV row order.

## Stage proxy

Approach bearings are treated as unoriented axes: opposite approaches within
25 degrees share a stage; different axes are exclusive. The result is 241
stages/groups: 66 junctions have two stages, 27 have three, and seven have
four. This is explicitly `geometry_inferred_opposing_approach_axis`, not an
observed conflict matrix. A protected-right stage is not fabricated without
lane-to-movement evidence. Pedestrian stages are absent.

## Demand, cycle, and green allocation

Input demand is the Stage-1 planned demand produced by free-flow propagation
of routed private-car plans and road-transit schedules. It is a simulation
demand proxy, not congestion-realised throughput or an iterated equilibrium
arrival profile. Each approach profile uses
`max(raw, 0.25 previous + 0.5 current + 0.25 next)` so smoothing cannot reduce
the design value. Arrivals after 24:00 are folded modulo 24 hours because the
MATSim controller repeats plans daily; 156,026 TPDM PCU are recorded as folded
rather than discarded.

For every stage and bin, the critical flow ratio is the maximum approach
`q/S`. Webster's cycle proxy uses total critical ratio and six seconds of
controller clearance per stage. Supported cycles are 60, 75, 90, and 100
seconds; each divides exactly into a 900-second plan window. Adjacent bins may
change by at most one cycle grade, and smoothing may only raise a recommended
cycle. Available green is allocated by stage critical ratio with a seven-second
minimum; green plus six-second clearances exactly fills every cycle.

There are 9,600 plans and 23,136 group windows. Cycle counts are 6,012 at 60
seconds, 635 at 75, 583 at 90, and 2,370 at 100. Of the plans, 2,237 are marked
`oversaturated_proxy_cycle_capped`; this remains visible instead of hiding
overload behind an unbounded cycle. All offsets are zero, so coordination is
not claimed.

The class audit retains separate private-car, Bus, GMB, school-bus, Taxi, and
other-road-vehicle rows for each stage/bin. Taxi remains explicitly
`missing_from_physical_network`.

## Outputs and commands

Ignored rebuildable output:

```text
data/transit/hongkong/processed/hong_kong_traffic_signals_2026_v3_tod_proxy_top100/
```

Key outputs are `selected_junctions.csv`, `stage_templates.csv`,
`executable_signal_movements.csv`, `approach_conflict_proxy.csv`,
`tod_plan_assignments.csv`, `tod_group_windows.csv`,
`vehicle_class_stage_demand_15min.csv`, `capacity_deconvolution_audit.csv`,
the candidate network, five MATSim signal XML files under `matsim/`, and JSON
build/validation summaries.

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_traffic_signal_tod_proxy_top100.py

.\mvnw.cmd -q `
  '-Dexec.mainClass=org.matsim.project.hongkong.signals.BuildHongKongTrafficSignalTodTop100' `
  '-Dexec.args=data/transit/hongkong/processed/hong_kong_traffic_signals_2026_v3_tod_proxy_top100 data/transit/hongkong/processed/hong_kong_traffic_signals_2026_v3_tod_proxy_top100/network_signal_capacity_deconvolved.xml.gz data/transit/hongkong/processed/hong_kong_traffic_signals_2026_v3_tod_proxy_top100/matsim' `
  org.codehaus.mojo:exec-maven-plugin:3.5.0:java

F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\validate_hong_kong_traffic_signal_tod_proxy_top100.py
```

Static validation passes all 100 systems, 9,600 plans, 566 controlled turns,
241 groups, and 23,136 group windows with zero missing/non-adjacent links,
active U-turns, missing group references, or adjacent-cycle-grade violations.

## Adoption boundary and next gate

This is a basic proxy and not yet a validated operating signal network.
Limitations are inferred approach-axis compatibility, missing pedestrian
control, zero coordination offsets, capped oversaturated timing, and planned
rather than iterated arrival demand. The generic Stage-11 launcher accepts the
explicit `--period tod` payload, but no upload or simulation has been launched.
The next safe step is a new one-iteration no-signal/TOD A/B gate with ordinary
innovation frozen, followed by per-junction queues, stuck events, controlled
entries, and private-car/Bus/GMB/school-bus outcome audits. Production adoption
requires a separate decision after that gate.
