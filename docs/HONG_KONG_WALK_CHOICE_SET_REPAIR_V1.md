# Hong Kong Walk choice-set repair V1

## Status and scope

This is an experimental, auditable preparation stage for the post-D2 Walk
calibration. It does not change road supply, public transport, Taxi supply,
PCU, demand scale, signals, or the 30-hour QSim boundary. It is not an adopted
production input and must be tested in a new immutable release/run.

The stage addresses a structural defect observed in D2: Walk V4 reduced the
Walk share but could not remove very long Walk choices held in frozen
household/student plans. It also ensures that ordinary people receive actual
short physical-network Walk alternatives instead of relying on unconstrained
mode mutation.

## Universal feasibility policy

All thresholds use the production physical Walk router and its 1.34 m/s link
travel-time rule. They do not vary by district or trip purpose:

- network Walk time `<= 15 min`: normal feasible alternative;
- `15 < time <= 30 min`: retained but not proactively added;
- `> 30 min`: removed from the selected choice only when a complete PT
  replacement can be routed;
- unreachable Walk or unavailable PT: no fabricated route; record the case in
  the unresolved audit.

`HongKongWalkChoiceSetRepair` applies the policy. It routes every selected Walk
and every ordinary non-Walk OD whose straight-line lower bound can still be no
longer than 15 minutes. A non-Walk OD whose lower bound already exceeds 15
minutes is safely marked `not_short_by_straight_line_lower_bound` without an
unnecessary network search. The audit records time/distance when routed, class,
action, protected status, person, trip index, and home-tour index.

Before routing, the preparation command enables Walk on every Car-capable road
link in memory through the same shared helper used by the formal QSim. This is
required for parity with the production physical-Walk graph and does not write
or modify the adopted Candidate5B network file.

## Atomic frozen-plan repair

Protected people are defined by the same household candidate registry used by
the score-calibration runs, plus every selected plan containing main-mode
`car_passenger`. If any selected Walk in a protected home-based tour exceeds
30 minutes, every main-mode Walk in that entire outbound/return tour is first
routed to PT in memory. The plan is changed only if all replacements succeed.
If one route fails, the complete tour is left unchanged and the long Walk is
written to `unresolved.csv`.

The repair does not touch household Car/driver/passenger legs, vehicle IDs,
joint-binding attributes, or school-bus legs. This preserves household
resource consistency while avoiding one-direction-only student changes.

For ordinary people, an individually selected Walk over 30 minutes is changed
to PT only after its PT route succeeds. Failures also remain unchanged and are
audited.

## Short-Walk candidate supplementation

For each ordinary selected non-Walk trip whose physical-network Walk route is
no longer than 15 minutes, the stage adds a scored-plan alternative containing
that already-routed Walk trip. At most four alternatives are added per person,
so the initial selected plan plus candidates fits the standard five-plan
memory. Protected people receive no alternative plan and remain frozen.

The follow-up run must use launcher profile
`score-calibration-walk-repair-22`. This profile:

- requires the prepared plans through `--plans-input`;
- preserves the D2 formula through `--scoring-arm d2`;
- keeps ordinary `ChangeExpBeta` and `SubtourModeChoice` through iteration 9;
- keeps `walk` in unconstrained `SubtourModeChoice`; the preparation stage
  repairs and supplements the initial choice set but is not a hard runtime
  feasibility cap, so later innovation may regenerate a long Walk and the
  final audit must measure that outcome explicitly;
- keeps protected household/student people out of ordinary individual
  replanning, while enabling the dedicated joint selector at iterations 5 and
  15. These are the iteration-0--21 members of the formal 50-run schedule
  5/15/25/35;
- evaluates household bindings and student alternatives together at each
  dedicated window. The same selector considers routed PT, Taxi, Walk and the
  `school_bus_plan_candidates_5pct_v6` physical school-bus candidates, so a
  separate unsynchronised school-bus selector is not installed.

The selected-plan Taxi count remains the 44,000-demand invariant. The launcher
separately records the total Taxi-leg count across plan memory, which may be
higher because a short-Walk alternative is a complete plan copy.

## Immutable preparation command

Build the repository-root shaded JAR, then run:

```text
java -cp matsim-example-project-0.0.1-SNAPSHOT.jar \
  org.matsim.project.hongkong.walk.PrepareHongKongWalkChoiceSetPlans \
  <config.xml> <input-plans.xml.gz> <household-candidates.csv> \
  <output-plans.xml.gz> <walk_choice_set_audit.csv> <unresolved.csv> \
  <controller-output-directory> 4
```

Every output path and the controller directory must be absent. Server work is
restricted to `/mnt/DiskM/by`, and a retry must use a new immutable directory.

Before a 22-iteration test is launched, acceptance of the preparation stage
requires:

- person count conserved;
- exactly 44,000 selected Taxi legs conserved;
- no change to household Car/passenger/driver binding counts;
- zero selected Walk trips above 30 minutes except explicitly unresolved
  no-alternative cases;
- every added Walk alternative has a physical network route and time no longer
  than 900 seconds;
- audit and unresolved outputs present and internally consistent.

The simulation audit must additionally verify that the selector actually ran
at iterations 5 and 15, report its household bindings and independent
PT/Taxi/Walk/school-bus choices, and separately count any over-30-minute Walk
trips regenerated by ordinary innovation after the initial repair.
