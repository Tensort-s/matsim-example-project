# Hong Kong traffic-signal MATSim adoption design 2026 v2

## Status

This document is the implementation design for converting the adopted
`hong_kong_traffic_signal_registry_2026_v1` location registry into auditable
MATSim signal-control inputs. It does **not** adopt traffic signals into the
production scenario and does not change the active network, config, plans,
public-transport supply, scoring, or Stage 11 results.

The v1 location count remains 2,054. The present design changes what must be
built for each location: a junction point and a list of incoming links are not
enough to represent traffic-signal operation safely.

## Evidence used

The operational design is based on two locally archived references:

- Transport Department, *Transport Planning and Design Manual, Volume 4 –
  Road Traffic Signals*, March 2026;
- the public one-page example *Signal timing and sequence F 02*, containing
  AM/PM stage sequences and durations for eight Kowloon junctions.

The source copies and their provenance-only manifest are stored under:

```text
data/transit/hongkong/raw/traffic_signals_2026/source_documents/
```

SHA256 values in the manifest preserve provenance only. They are not build,
input-selection, simulation, or acceptance gates.

## Why the earlier direct-link proposal is insufficient

The location registry currently lists 8,288 candidate incoming Car links. A
naive conversion would give each incoming link one red/green signal and infer
one generic cycle. That would create four material errors:

1. one approach may contain left, ahead, and right movements with different
   permissions, so the controlled object must be a `fromLink -> toLink`
   movement rather than only a `fromLink`;
2. a stage is not synonymous with a traffic stream's green phase, and the
   published stage duration cannot be copied verbatim as pure green time;
3. amber, red/amber, all-red clearance, pedestrian clearance, and conflicting
   movements must be represented explicitly;
4. present approach-link capacities may already reflect signal-constrained
   observed discharge, so applying red/green control on top can count the same
   capacity loss twice.

Consequently, location-only records are never activated automatically. A
junction becomes simulation-ready only after its movement topology, conflict
matrix, signal groups, controller plan, and capacity treatment pass the gates
below.

## What the two references establish

### Transport Department control rules

The default signal sequence is:

```text
red -> red+amber -> green -> amber -> red
```

The design defaults are 3 seconds of amber and 2 seconds of red+amber. The
intergreen between two conflicting streams therefore has a base value of 5
seconds before any additional all-red clearance. The required intergreen is
increased with conflict-point clearance distance. The manual's ahead-movement
table maps 9, 10–18, 19–27, 28–36, 37–46, 47–54, 55–64, and 65–74 metres to
5 through 12 seconds. Its turning-movement table maps 9, 10–13, 14–20, 21–27,
28–34, 35–40, 41–45, and 46–50 metres to the same 5 through 12 seconds.

A normal traffic green is at least 5 seconds; a justified early cut-off or
late start may be as short as 3 seconds. A pedestrian phase must not be
replaced by a convenient extended all-red. Pedestrian full-green time is
normally at least 5 seconds, followed by adequate clearance. A walking speed
of 1.2 m/s is the ordinary design value and 0.9 m/s is required where elderly,
disabled, or heavy pedestrian demand is material.

For an approach lane, the design saturation-flow starting values are:

```text
nearside or single lane:  S = 1940 + 100 * (W - 3.25)
other lane:               S = 2080 + 100 * (W - 3.25)
```

where `S` is pcu/hour/lane and `W` is lane width in metres. Uphill gradient
reduces `S` by 42 pcu/hour for every 1% gradient; downhill gradient receives
no automatic increase. The design calculation uses Transport Department PCU
factors—1.0 for car/taxi/LGV, 0.4 motorcycle, 1.75 HGV, 2.0 through bus/coach,
1.5 public light bus, and 0.2 pedal cycle—independently of any deliberately
scaled QSim vehicle PCU.

The principal fixed-time calculations are:

```text
capacity:                    Q = g*S/C
critical flow ratio:         y = q/S
optimum cycle:               Co = (1.5*L + 5)/(1 - Y)
minimum cycle:               Cm = L/(1 - Y)
practical cycle:             Cp = 0.9*L/(0.9 - Y)
critical-stage green split:  g = y*(C - L)/Y
```

`C` is cycle time, `g` effective green, `L` total lost time, and `Y` the sum
of critical flow ratios. With a 3-second amber and the manual's 2-second lost
time convention, effective green is normally one second longer than displayed
green. These equations provide an auditable starting plan, not observed
controller truth. New installations generally use cycles no longer than 90
seconds; 120 seconds may be used for capacity assessment. A longer cycle in
an observed existing plan is retained as observed evidence, not generalized
to the rest of Hong Kong.

### Public eight-junction example

The example provides stage diagrams plus AM and PM stage durations. Each row's
durations sum to its stated cycle, but the sheet does not provide plan
activation windows, offsets, detector logic, amber/all-red decomposition, or a
machine-readable mapping from each diagram arrow to network links. It is
therefore partial controller evidence, not a complete controller program.

All eight locations match high-confidence v1 registry groups:

| Junction | Registry ID | Cycle (s) | AM stage durations (s) | PM stage durations (s) |
|---|---:|---:|---|---|
| Nathan Road / Jordan Road | `TS_K006` | 130 | A64 B34 C32 | A64 B34 C32 |
| Nathan Road / Gascoigne Road / Kansu Street | `TS_K008` | 120 | A39 B41 C40 | A35 B44 C41 |
| Nathan Road / Austin Road | `TS_K005` | 130 | A37 B47 C46 | A33 B51 C46 |
| Austin Road / Cox's Road / Pine Tree Hill Road | `TS_K118` | 130 | A52 B26 C21 D31 | A54 B23 C22 D31 |
| Austin Road / Chatham Road South / Cheong Wan Road | `TS_K024` | 130 | A34 B39 C44 D13 | A32 B44 C39 D15 |
| Jordan Road / Gascoigne Road / Queen Elizabeth Hospital Road | `TS_K101` | 130 | A27 B18 C64 D21 | A27 B18 C64 D21 |
| Jordan Road / Cox's Road | `TS_K201` | 130 | A33 B46 C20 D31 | A33 B46 C20 D31 |
| Gascoigne Road / Wylie Road | `TS_K025` | 130 | A37 B55 C38 | A29 B68 C33 |

The 120-second row proves that proximity alone does not justify placing all
eight junctions in one 130-second coordination group. The example's AM and PM
plans are digitized as separate observed-partial records. They are not used as
a full-day plan until activation periods and offsets are obtained or an
explicitly labelled sensitivity assumption is approved.

## Revised data model

### Layer 0: physical location registry

Retain the current 2,054 v1 groups, evidence classes, confidence labels, and
candidate network links. The 263 official-geometry-only clusters remain a
review layer and are not promoted merely to approach an aggregate count.

### Layer 1: movements and conflicts

For every candidate junction:

1. enumerate each road-legal `fromLink -> toLink` movement through the
   junction;
2. classify left, ahead, right, U-turn, bus-only, and pedestrian movements;
3. use mapped turn restrictions, road access, lane tags, and junction geometry
   to remove illegal movements;
4. construct a geometric conflict matrix, then review ambiguous merges,
   crossings, and protected/permitted turns;
5. bind separate MATSim lane IDs only where a turn pocket or separately queued
   approach must preserve storage and spillback. Where lane geometry is not
   defensible, use MATSim turning-move restrictions on a shared incoming link.

A signal can therefore control one incoming link but permit only specified
outgoing links. Compatible movements form a signal group; mutually conflicting
movements can never be green simultaneously.

### Layer 2: controller and timing evidence

Every plan carries one of four evidence classes:

1. `observed_complete`: controller stages, transitions, activation periods,
   and offsets are available;
2. `observed_partial`: some official/public stage or timing evidence exists,
   as for the eight-junction example;
3. `tpdm_calculated_proxy`: topology, demand, and TPDM calculations support an
   explicitly inferred fixed-time plan;
4. `location_only`: no plan is built and the junction remains inactive.

No city-wide default cycle is allowed. A TPDM proxy is calculated separately
for its demand period using critical approach flows, saturation flow, lost
time, pedestrian requirements, and clearance distances. Stage omission or
demand-responsive behavior is not fabricated from fixed-time evidence.

### Layer 3: MATSim compiler outputs

Implementation will add the MATSim signals contrib dependency at the same
version as core MATSim and generate:

- `signalSystems.xml`: movement-level signals, link IDs, optional lane IDs,
  and allowed outgoing links;
- `signalGroups.xml`: compatible movements;
- `signalControl.xml`: cycle, offset, plan start/end, and group onset/drop;
- `amberTimes.xml`: explicit amber/red+amber rules;
- `intergreenTimes.xml`: movement-pair clearance intervals;
- `conflictingDirections.xml`: the independently generated conflict matrix;
- CSV/GeoJSON audit tables linking every generated object back to its registry
  group, evidence, geometry, and source assumption.

The runner will load `SignalsDataLoader`, configure the signals contrib, and
use conflict-direction plus turn-restriction intersection logic. QA runs use
an exception—not a warning—when incompatible movements are simultaneously
green.

### Layer 4: capacity treatment

The current road capacities combine detector and ATC evidence and may describe
practical, signal-constrained discharge rather than unconstrained saturation
flow. Before activating any junction, create an approach-level audit with:

- current MATSim capacity and provenance;
- detector position and distance from stop line;
- TPDM lane-width/gradient saturation estimate;
- observed or assumed `g/C`;
- implied capacity `g*S/C`;
- selected treatment and uncertainty label.

For the first pilot, only the final controlled approach link is assigned a
defensible saturation discharge `S`; signal timing then supplies `g/C`.
Upstream calibrated capacities remain unchanged. A detector-derived capacity
that already averages red and green is not reused as `S`. The no-signal
baseline is retained for paired comparison.

Transport Department design PCUs are used only to calculate timing demand and
saturation. Existing QSim bus/GMB PCU scaling remains a separate mechanical
simulation choice and is not silently substituted into the design equations.

## Adoption and validation sequence

### Gate A — static compiler QA

- every controlled link, outgoing movement, lane, and signal group exists;
- every movement belongs to exactly one audited control state;
- no prohibited turn is generated;
- all conflict pairs have a valid intergreen and never overlap in green;
- amber is 3 seconds and red+amber is 2 seconds unless a junction-specific
  observed exception is documented;
- green plus transition/lost intervals reconciles exactly to the cycle;
- pedestrian clearance satisfies the selected 1.2 or 0.9 m/s rule;
- location-only and unresolved registry records generate no active signal.

### Gate B — one-junction mechanical micro-test

Run one representative multi-stage junction for one no-innovation iteration.
Audit signal state-change events, movement legality, queues, link exits,
gridlock, and cycle reconciliation. This gate tests the compiler and runtime
wiring, not demand calibration.

### Gate C — eight-junction observed-partial pilot

Build the eight mapped example junctions. Run AM and PM as separate peak-window
sensitivity cases because the source does not state activation windows or
offsets. Do not infer a common coordination plan from proximity. Compare:

- simulated stage changes against the digitized durations;
- approach discharge and queue profiles against `g*S/C`;
- Car, Bus, GMB, and school-bus travel time and stuck counts;
- ordinary-PT arrival deviations, missed boardings, and passenger waits;
- results with and without approach-capacity deconvolution.

Ordinary `ReRoute`, `SubtourModeChoice`, and `TimeAllocationMutator` remain
frozen so demand response cannot hide a supply defect.

### Gate D — integrated physical-mode test

After the eight-junction mechanics pass, run one no-innovation iteration with
the current physical Car, ordinary PT, school bus, Walk, and bound household
travel. Taxi remains the only permitted direct teleported main mode. Compare
against the immediately preceding no-signal run using identical plans and
random seed.

### Gate E — spatial expansion

Expand first to 50–100 high-confidence junctions in one coherent corridor or
area, then to the full reviewed registry. A junction is included only when its
movement topology and plan evidence satisfy the relevant gate. Coverage count
is never allowed to override safety or provenance.

Only after signal mechanics, physical PT completion, road stuck behavior, and
capacity treatment are stable should ordinary ReRoute be enabled. Mode-choice
and time-allocation innovation follow in separate runs so their effects remain
identifiable.

## Acceptance criteria

The first adopted signal supply must meet all of the following:

- zero conflicting-green or intergreen violations;
- zero references to missing road links, lanes, groups, or plans;
- zero signal controls on non-road or passenger-only links;
- exact cycle accounting for every active plan;
- full provenance for every observed value and an explicit inferred label for
  every calculated value;
- no unexplained double application of signal capacity loss;
- event-level evidence of amber, all-red where required, and legal discharge;
- no regression in the existing school-bus correct-boarding invariant;
- PT waits, vehicle stuck counts, approach queues, and journey times reported
  by mode and junction, rather than summarized only as a successful exit code.

## Historical pilot v1

The versioned `hong_kong_traffic_signals_2026_pilot_v1` package implemented
the vehicle-control portion of Gates A--D. Its builder recovers each physical
junction as a connected micro-node cluster, identifies 32 final approach
links, enumerates 62 explicit `fromLink -> toLink` movements, and uses a
bounded conflict-graph colouring step to assign those movements to the
observed number of stages. A build fails if the observed stage count cannot
represent the blocking conflicts safely. The resulting pilot has 8 signal
systems, 26 signal groups and zero blocking same-stage conflicts.

Both AM and PM controls are compiled independently. They use the public stage
durations, 3-second amber, 2-second red+amber, a minimum 5-second intergreen,
zero inferred offset, and an all-day sensitivity window. MATSim applies amber
after the configured dropping time and red+amber before the configured onset,
so the compiler uses a 6-second controller onset gap: `6 + 2 - 3 = 5` seconds
at the emitted red-to-green event level. The validator checks this derived
runtime interval rather than accepting the XML intergreen value alone. The
latter offset and activation-window assumptions are
clearly labelled sensitivity assumptions because the public source does not
provide offsets or activation periods. These files remain
`observed_partial_timing_with_geometry_inferred_movement_mapping`, not complete
observed controllers.

Capacity deconvolution changes only the 32 controlled final approaches. Their
pilot capacities are TPDM lane-count saturation proxies using a 3.25 m lane
width and no unobserved gradient adjustment. All other links and every node
remain byte-value equivalent at the parsed network-attribute level. Signal
timing supplies the green-ratio loss. The validator does not use SHA as an
input or acceptance gate.

The active MATSim road network represents these physical junctions with
multiple short nodes and links. MATSim's `conflictingDirections` data model
maps one signal system to one network node, so the pilot deliberately does not
fabricate a single-node runtime conflict file. Cross-node blocking conflicts
are separated by fixed stages and independently audited. Opposing permitted
turns are labelled as yield proxies requiring later controller/topology review.

Pedestrian crossings are also not silently fabricated. The package includes
one audit row per junction, retains the 1.2 and 0.9 m/s TPDM clearance rules,
and marks crossing geometry, demand logic, and pedestrian stages as missing
production-adoption blockers. Physical Walk therefore remains outside this
vehicle-signal pilot's controlled pedestrian phases.

Pilot v1 is retained as a historical mechanical-integration baseline, but its
movement-to-stage mapping is no longer an acceptable diagram interpretation.
It assigned network movements to the observed number of stages with conflict-
graph colouring. That proves a conflict-free colouring exists; it does not
prove that Stage A/B/C/D releases the arrows drawn in the source diagram. It
also emitted direct reverse connectors as U-turn movements even though the
example diagrams do not draw those U-turns. No new signal run should use v1
as movement truth.

Implementation entry points are:

```text
scripts/hong_kong_single_city/transit_supply/build_hong_kong_traffic_signal_pilot_v1.py
src/main/java/org/matsim/project/hongkong/signals/BuildHongKongTrafficSignalPilot.java
scripts/hong_kong_single_city/transit_supply/validate_hong_kong_traffic_signal_pilot_v1.py
scripts/hong_kong_single_city/run/launch_hong_kong_traffic_signal_pilot.py
scripts/hong_kong_single_city/analysis_visualization/audit_hong_kong_traffic_signal_run.py
```

## Pilot v2: diagram-inferred high-confidence release

`hong_kong_traffic_signals_2026_pilot_v2_diagram_inferred` replaces graph
colouring with an explicit diagram registry. Published arrows are transcribed
as permitted vehicle movements, and a junction is executable only when the
current MATSim first-connector topology can enforce the same boundary. The
registry separately records diagram confidence, network-expression
confidence, activation status, and deferral reason. This first v2 release
audits all eight examples but activates only `TS_K006`, Nathan Road / Jordan
Road:

- Stage A releases both Jordan Road approaches and their shown non-U-turn
  movements;
- Stage B releases the Nathan Road northbound approach and its shown non-U-turn
  movements;
- Stage C releases the Nathan Road southbound approach and its shown non-U-turn
  movements;
- four direct reverse connectors are excluded because no U-turn is drawn.

At this junction, the diagram phases are complete approach bundles in the
current micro-node network. Four `fromLink -> first internal connector`
signals therefore represent all `ahead|left|right` exits without claiming
lane-level precision. They form three signal groups. Both AM and PM use the
observed 130-second `64/34/32` split, 3-second amber, 2-second red+amber and a
5-second event-level intergreen. Only the four final approach capacities are
deconvolved.

The other seven examples are not silently approximated. `TS_K005` and
`TS_K201` have high-confidence diagram features, including protected turns or
greens continuing across adjacent stages, but their present first connectors
also admit movements that the diagram withholds. `TS_K008`, `TS_K118`,
`TS_K024`, `TS_K101`, and `TS_K025` need clearer arrow evidence, additional
approach recovery, or lane-level connector reconstruction. They remain in
`diagram_stage_inference.csv` and `deferred_junctions.csv`, but cannot enter
the compiled signal files.

The v2 compiler reads `signal_group_stage_windows.csv`, rather than assuming
one group per stage. A group may therefore remain green through contiguous
stages such as `B|C`, and a stage may contain no vehicle group when later
evidence identifies a pedestrian-only or all-red stage. The current first
release does not need either case, but the representation no longer prevents
them. Static validation passes for one system, four signals, three groups,
four capacity-only network changes, no active U-turn, no blocking shared-green
pair, and a minimum 5-second event-level intergreen in both periods.

Implementation entry points are:

```text
scripts/hong_kong_single_city/transit_supply/build_hong_kong_traffic_signal_pilot_v2_diagram_inferred.py
src/main/java/org/matsim/project/hongkong/signals/BuildHongKongTrafficSignalPilotV2.java
scripts/hong_kong_single_city/transit_supply/validate_hong_kong_traffic_signal_pilot_v2_diagram_inferred.py
```

This is an independent, ignored rebuildable pilot. It does not replace the
production network and does not change `city.yaml` or the run manifest. The
generic `--traffic-signals` launcher now reads the staged pilot's build summary
instead of hard-coding v1 counts, so a payload explicitly staged as
`traffic_signal_pilot` can select v2 without mislabelling it. No v2 runtime has
yet been launched; adoption still requires an explicit v2 payload and a
one-iteration gate.

`RunHongKong5Pct` exposes an explicit `--traffic-signals` opt-in. Runs without
that flag remain unchanged. Signal runs load the MATSim signals contrib and
disable QSim fast capacity update because that approximation is unsupported by
the signals engine. The launcher also fixes this value in the generated config
and keeps ordinary plan innovation frozen.

The first server attempt exposed two MATSim integration constraints before
any result was accepted. QSim's fast capacity update is incompatible with the
signals engine and is now disabled explicitly. A following attempt showed
that a 5-second configured onset gap produces only 4 seconds between the
previous red event and the next green event when 3-second amber and 2-second
red+amber are enabled. The compiler conversion above and the new event-level
static assertion close that off-by-one semantic gap; failed attempt outputs
remain historical diagnostics and are not validation results.

### Integrated AM sensitivity result

The first accepted integrated gate is the AM observed-partial sensitivity at
`/mnt/DiskM/by/hk_stage11_traffic_signals_20260810_run3`, using release
`/mnt/DiskM/by/hk_stage11_traffic_signals_20260810_release3`. It ran the full
385,820-person population through iterations 0 and 1 and exited zero. Ordinary
`ReRoute`, `SubtourModeChoice`, and `TimeAllocationMutator` remained at zero;
the already-adopted household/student maximum-utility selectors remained
active.

Iteration 1 emitted 87,240 signal-state events. All 8 systems and 26 groups
were observed, all 32 controlled approaches carried traffic, and the event
audit found zero missing groups, conflicting green overlaps, intergreen
violations, amber/red+amber duration violations, or cycle violations. Four
yellow events at 29:59:58--30:00:00 are correctly reported as terminal
transition truncations because their red events fall after simulation end.

The physical-mode and student audits also passed. Taxi remained the only
direct teleported main mode, and all 1,002 selected school-bus legs departed,
boarded, alighted, and arrived on their catalogued vehicles with no terminal
load. This is a mechanical integration pass, not a performance-calibration
pass. Relative to no-signal run57, controlled-approach entries fell from
42,694 to 41,231 (-3.43%), person stuck events rose from 14,382 to 16,631
(+15.64%), PT-person stuck rose from 12,892 to 14,995, and Car stuck rose from
2,326 to 2,669. The AM plan was intentionally applied all day because no
activation windows were observed; this performance regression therefore
blocks production adoption and demonstrates why time-of-day plan windows,
offset evidence, downstream PT service repair, and junction-level queue audit
must precede spatial expansion or ordinary innovation.

The separate PM mechanical sensitivity is stored at
`/mnt/DiskM/by/hk_stage11_traffic_signals_20260810_run4`. It ran iteration 0
only and exited zero. Its 87,238 signal-state events likewise covered all 8
systems, 26 groups, and 32 controlled approaches with zero missing-group,
conflicting-green, intergreen, transition-duration, or cycle violations. The
30:00 lost-agent counter was 10,180, compared with 10,074 for AM iteration 0
and 8,738 for no-signal run57 iteration 0. Thus both AM and PM files pass the
runtime-mechanics gate, while neither peak plan is suitable as an all-day
controller. PM was not repeated through iteration 1 because the full
household/student integrated gate and its three downstream audits were already
completed with AM; this PM run isolates the alternative controller timing.

This order deliberately separates physical location recovery, controller
inference, capacity calibration, and behavioral innovation. It permits traffic
signals to explain part of the present early-arrival bias without presuming in
advance that all remaining PT timing or road-stuck errors are signal-related.

## Current freeze and no-signal road audit

The territory-wide pre-controller Stage-1 movement/demand/saturation candidate
is documented separately in
`docs/HONG_KONG_TRAFFIC_SIGNAL_TPDM_PROXY_V3.md`. Its status is
`territory_wide_tpdm_proxy_stage1_candidate_not_adopted`; it deliberately stops
before conflict grouping, stages, cycles, green splits, offsets, controllers,
signal XML, or simulation.

City-wide signal expansion remains frozen after the AM/PM mechanical
sensitivities. The bounded v2 diagram-correction work above does not expand
the active spatial scope beyond one high-confidence test junction.
The pilot implementation and explicit `--traffic-signals` opt-in remain in
place; no-signal runs still omit the feature without reverting code or data.
Before another signal run, the fixed-route no-signal run57 road layer is being
reviewed independently for queue concentration, road-vehicle stuck events,
turn legality, route loops, short-link storage, and disconnected fragments.
The final event-level result and repair order are in
`docs/HONG_KONG_NO_SIGNAL_ROAD_RUNTIME_AUDIT.md`. Ordinary PT passengers left
waiting at stops are explicitly excluded from those road findings.
