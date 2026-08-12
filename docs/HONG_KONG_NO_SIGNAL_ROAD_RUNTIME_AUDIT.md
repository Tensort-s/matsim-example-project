# Hong Kong no-signal road runtime audit (run57)

## Status and decision boundary

Traffic-signal adoption is frozen while the existing road supply and fixed
routes are audited. This does not revert or delete the opt-in signal pilot:
`RunHongKong5Pct` still requires the explicit `--traffic-signals` flag, and
ordinary runs without that flag remain unchanged. The final audit uses the
no-signal Stage 11 run57 baseline and does not adopt a new production run.

The final server result is:

```text
/mnt/DiskM/by/hk_road_network_audit_20260810_run57_v3/
```

The v1 and v2 directories are retained as audit-method development history.
V2 removed false Bus/GMB path-discontinuity reports across non-road transit
links. V3 additionally applies MATSim start-link semantics to trip-distance
diagnostics and records each link's trip-start share. No hash is used as an
input-selection or acceptance gate.

The focused top-50%-delay neighbourhood audit is retained at:

```text
/mnt/DiskM/by/hk_road_hotspot_audit_20260810_run57_v2/
```

It selects the minimum 31 links reaching 50.0124% of road delay, then joins
their exact parallel links, immediate road neighbours, observed vehicle
transitions, hybrid lane/capacity provenance, and a QSim storage proxy. The
entry point is `audit_hong_kong_road_hotspot_neighborhoods.py`; it is an audit,
not an automatic network editor.

## Baseline and scope

The audit reads, without modifying:

```text
/mnt/DiskM/by/hk_stage11_student_school_mode_20260809_run57/
  config_stage11_student_school_mode_it0_it1.xml
  output/output_links.csv.zst
  output/ITERS/it.1/1.events.xml.zst
```

Run57 has `flowCapacityFactor=0.1`, `storageCapacityFactor=0.1`,
`stuckTime=600`, `removeStuckVehicles=true`, and a 30:00 horizon. Resident,
visitor, and mainland-Hong-Kong-resident `ReRoute`, `SubtourModeChoice`, and
`TimeAllocationMutator` weights are all zero. The result therefore diagnoses
the fixed initial routes and supply; it is not a route-choice equilibrium.
Ordinary PT runtime capacity is unlimited in run57 for mechanical isolation,
so this audit is not an adopted PT-capacity validation.

Road findings include private Car, road Bus, GMB, and physical school-bus
vehicles. The audit explicitly excludes 12,892 ordinary PT-passenger stuck
events, including passengers left waiting after missed service. It also keeps
the 30:00 terminal bucket separate from an ordinary clock hour.

The audited road layer uses `EPSG:32650`. Link lengths are metres, travel
times are seconds, nominal link capacities are vehicles/hour before the QSim
capacity factor, and delay totals are vehicle-hours. The peak vehicle-count /
effective-capacity field is diagnostic only because the audit does not
reconstruct the vehicle-type PCU factors.

## Network structure

- The Car layer has 47,591 directed links and 27,262 nodes.
- Its largest strongly connected component contains 26,655 nodes (97.7735%).
  There are 581 components, 239 directed sink nodes, 276 directed source
  nodes, and 650 links outside the largest component.
- Only 55 outside-component links are traversed in iteration 1: 13,816
  traversals, 28.806 vehicle-hours of delay, and 6 road-vehicle stuck events.
  Disconnected edge fragments require repair, but they are not the principal
  cause of the run57-wide congestion.
- 42,592 road links are traversed and 4,999 are not. An untraversed link is an
  audit candidate, not automatically an error.
- 5,797 links are shorter than 10 m, including 1,233 shorter than 5 m. These
  are not automatically invalid, but short connectors in stuck clusters need
  explicit storage/spillback review under `storageCapacityFactor=0.1`.

Among the 31 leading-delay links, 10 have at least one downstream link shorter
than 10 m and 19 have at least one downstream storage proxy below one Car.
MATSim's queue implementation computes link storage from length, effective
lanes, effective cell size, and `storageCapacityFactor`, then also considers
the flow buffer. A positive fractional storage value can still accept one Car
before blocking; it is not a zero-vehicle link. Most flagged short connectors
also sit at real merge/diverge nodes, so contracting them would erase valid
turn choices. No city-wide length floor, capacity increase, or storage-factor
override is adopted. Their spillback is re-audited after the bounded routing
repair; only persistent connector-specific anomalies may be changed later.

## Runtime congestion and stuck vehicles

Iteration 1 contains 23,872,693 road-link leave events. Among the 27,541
links with at least 100 traversals, 3,655 (13.27%) have mean travel time above
1.5 times free flow and 1,810 (6.57%) exceed twice free flow. Total audited
road delay is 62,669.620 vehicle-hours. It is highly concentrated: the top
link contributes 12.69%, the top 10 contribute 34.90%, and only 31 links are
needed to reach half of all delay.

Road-vehicle stuck events are separate from passenger waiting:

| Vehicle class | Trips | Road stuck | Share of trips |
|---|---:|---:|---:|
| Private Car | 66,203 | 1,175 | 1.775% |
| Bus | 69,585 | 578 | 0.831% |
| GMB | 81,030 | 547 | 0.675% |
| School bus | 10,309 | 7 | 0.068% |
| **Total** | **227,127** | **2,307** | **1.016%** |

Stuck events increase sharply between 18:00 and 23:00. Events collected in
hour 30 are unresolved vehicles removed or classified at the simulation
horizon and must not be interpreted as a normal late-night peak.

The five largest-delay links are:

| Link | From -> to node coordinates | Traversals | Mean/free-flow | Delay (veh-h) | Road stuck | Starts on link |
|---|---|---:|---:|---:|---:|---:|
| `road_261323_0_f` | 209582.17,2469234.01 -> 209501.20,2468967.99 | 5,386 | 369.45 | 7,952.43 | 173 | 5 (0.093%) |
| `road_261308_0_f` | 213008.69,2477099.85 -> 212876.23,2477226.69 | 2,935 | 295.57 | 3,217.38 | 1 | 0 |
| `road_57795_0_f` | 203167.32,2476295.18 -> 203312.89,2476206.98 | 2,301 | 228.31 | 1,794.37 | 3 | 0 |
| `road_103772_0_f` | 210027.96,2473506.54 -> 210325.19,2473446.96 | 3,363 | 114.48 | 1,670.18 | 10 | 7 (0.208%) |
| `road_57349_0_f` | 204567.89,2475560.71 -> 204440.06,2475201.50 | 3,202 | 62.29 | 1,496.66 | 1 | 0 |

The very low start shares prove that the leading hotspots are through-traffic
queues, not artifacts caused by many agents being inserted on the same link.
Their hourly profiles also show persistent breakdown rather than one extreme
observation: `road_261323_0_f` deteriorates in the morning, briefly recovers,
then collapses again after 17:00 and remains severely delayed through hour 25;
`road_261308_0_f` collapses after hour 16; `road_57795_0_f` remains impaired
from hour 8; and `road_103772_0_f` is near free flow through hour 17 before a
sharp evening breakdown.

One priority topology/routing case is the pair between nodes
209582.17,2469234.01 and 209501.20,2468967.99. `road_261323_0_f` is a
1-lane, 70 km/h, 1,750 veh/h link and receives 5,386 traversals, while the
parallel `road_105124_0_f` is a 3-lane, 59.5 km/h, 5,150 veh/h link and
receives only 910 traversals with a mean/free-flow ratio of 1.04. The frozen
routes prefer the slightly faster low-capacity link and cannot redistribute
after congestion appears. Before changing either link, source geometry and
road function must establish whether these are legitimate separated lanes,
an incorrect duplicate, or an incomplete lane-choice representation.

The source follow-up resolves this pair sufficiently for a bounded mechanical
test. The official road centreline contains two distinct same-direction
features, rather than one accidentally duplicated geometry. However,
`road_261323_0_f` matches OSM way 42293618, classified as a one-lane service
road with `motor_vehicle=destination`, whereas `road_105124_0_f` matches the
three-lane Cross-Harbour-Tunnel trunk. Existing frozen routes select the
slightly faster restricted service link. Repair V1 therefore removes normal
through-motor modes from `road_261323_0_f`, maps its four activity references
to the exact same-endpoint trunk link, and substitutes `road_105124_0_f` only
where an existing NetworkRoute contains the restricted link.

At Tate's Cairn, `road_261308_0_f` matches an OSM service feature marked
`motor_vehicle=no`, while an immediate short legal same-endpoint path exists:
`road_285290_0_f -> road_283946_0_f`. Repair V1 applies that substitution.
Its downstream `road_283947_0_f` has similar OSM service tagging, but the
current road graph provides no short same-endpoint alternative: a first
diagnostic preflight found only an approximately 52-link loop. It is therefore
not restricted in V1. That result is evidence of unresolved local topology or
source alignment, not authority to impose a large detour.

Repair V1 is opt-in through `--road-hotspot-repair-v1`. It does not enable
`ReRoute`, `SubtourModeChoice`, or `TimeAllocationMutator`; it changes only
population and transit NetworkRoutes that actually reference the two audited
links. Walk remains permitted where already enabled. A route is accepted only
when the replacement is endpoint-contiguous. The real-scenario preflight for
run62 repaired 6,355 population routes and 111 transit routes, remapped 109
transit-stop facilities and four activities, then confirmed that the stop
sequence remains present in every changed transit vehicle route. It uses:

```text
road_261323_0_f -> road_105124_0_f
road_261308_0_f -> road_285290_0_f -> road_283946_0_f
```

This is a sensitivity candidate, not yet a production network adoption.

## Bounded repair validation (run62)

The completed no-signal, no-ordinary-innovation sensitivity is:

```text
/mnt/DiskM/by/hk_stage11_road_hotspot_repair_20260810_release62/
/mnt/DiskM/by/hk_stage11_road_hotspot_repair_20260810_run62/
/mnt/DiskM/by/hk_road_network_audit_20260810_run62_v1/
/mnt/DiskM/by/hk_road_hotspot_audit_20260810_run62_v2/
```

Run62 exited zero after iterations 0 and 1. It retained no traffic signals,
`KeepLastSelected=1`, and zero ordinary `ReRoute`, `SubtourModeChoice`, and
`TimeAllocationMutator` weights. The household/student maximum-utility choice
already present in run57 still runs between iterations; iteration 1 is the
paired physical result. Ordinary PT runtime capacity remains unlimited, as in
run57, so neither run is a production PT-capacity validation.

Compared with the run57 iteration-1 event audit:

| Metric | run57 | run62 | Change |
|---|---:|---:|---:|
| Road delay (vehicle-hours) | 62,669.620 | 52,809.005 | -15.73% |
| Road-vehicle stuck | 2,307 | 1,897 | -17.77% |
| Private-Car stuck | 1,175 | 884 | -24.77% |
| Bus stuck | 578 | 559 | -3.29% |
| GMB stuck | 547 | 452 | -17.37% |
| School-bus stuck | 7 | 2 | -71.43% |
| QSim lost at 30:00 | 3,129 | 3,056 | -2.33% |
| Links >=100 traversals with mean/free-flow >1.5 | 3,655 | 3,633 | -22 links |
| Links >=100 traversals with mean/free-flow >2 | 1,810 | 1,792 | -18 links |

The original 31 links' combined delay falls from 31,342.587 to 18,838.012
vehicle-hours (-39.90%). The minimum set reaching half of total delay grows
from 31 links to 48 links, with 24 links shared between the two sets. Delay is
therefore lower and less concentrated, not merely hidden on one replacement
link.

The Cross-Harbour-Tunnel three-link neighbourhood (`road_261323_0_f`,
`road_105124_0_f`, `road_261324_0_f`) falls from 7,959.57 to 401.93
vehicle-hours (-94.95%). `road_105124_0_f` now carries 6,435 traversals and
314.67 vehicle-hours of delay; its two-lane downstream `road_261324_0_f`
adds 87.26 hours. Both have storage proxies above five Cars, so the residual
queue is a 3-to-2-lane downstream-flow issue, not a short-connector storage
failure.

The six-link Tate's Cairn neighbourhood falls from 3,252.57 to 1,680.87
vehicle-hours (-48.32%), but `road_283946_0_f` becomes the fourth-largest
candidate hotspot with 1,649.21 vehicle-hours. All 3,454 observed exits split
between two one-lane links: 1,860 to `road_283947_0_f` and 1,594 to
`road_62825_0_f`. Their storage proxies are 1.78 and 2.02 Cars and neither is
shorter than 130 m. The remaining queue is therefore a three-lane-to-two-
one-lane fork/capacity/source-alignment question. V1 must not respond by
inflating short-link storage or by closing `road_283947_0_f`; its legal
alternative remains unresolved.

In the new 48-link half-delay set, 12 hotspots have a downstream link shorter
than 10 m and 28 have at least one downstream storage proxy below one Car.
The corresponding ten short-downstream hotspots from run57 decline in
aggregate from 6,509.66 to 5,555.96 vehicle-hours (-14.65%), although individual
locations move in both directions. This gives no evidence for a uniform
minimum length or storage multiplier. The next connector work must be
location-specific, beginning with persistent same-street junction chains such
as `road_57795_0_f -> road_57357_0_r`, rather than modifying all 5,797 links
shorter than 10 m.

Historical attempts are retained but invalid for outcome analysis. Run60 was
stopped before QSim after the proposed restriction of `road_283947_0_f`
produced an approximately 52-link detour. Run61 reached iteration 0 but failed
because 109 transit-stop facilities still referenced the old links. Run62
synchronises those facilities, validates their order in every changed transit
route before QSim, and is the first successful bounded-repair result.

## Path diagnostics

After non-road transit gaps are handled explicitly, road-link endpoint
adjacency mismatches are zero for every vehicle class. The earlier large
Bus/GMB mismatch counts were audit false positives and are not network
failures.

Private Car has 16,860 adjacent reverse-link transitions. Of these, 15,055
(89.3%) occur immediately after departure and only 1,805 occur internally.
There are 16,264 trips with at least one such transition, 24.57% of 66,203
Car trips. This pattern points first to activity `linkId` direction, start-link
selection, and missing U-turn legality—not a general long-path routing loop.

The V3 distance audit excludes the non-traversed geometric length of MATSim's
start link and measures the straight-line origin from its downstream node.
It leaves 11,441 private-Car trips (17.28%) with network/euclidean distance
above 2, 1,911 (2.89%) above 3, 384 (0.58%) above 5, and 64 (0.10%) above 10.
These are review candidates rather than proven errors because coastline,
tunnels, bridges, one-way streets, and activity snapping can legitimately
produce high ratios. Private-Car repeated-link loops affect 857 trips (1.29%).

Bus and GMB repeated links and internal turnbacks must be checked against
their scheduled route shapes and terminal loops, rather than treated as
private-Car errors. School buses have 1,260 internal reverse transitions in
535 trips and repeated links in 365 trips; these are a focused supply-review
set, especially where proxy pickup chains or reverse-direction connectors are
involved.

## Private-Car activity-link direction repair candidate

The run62 network changes the current comparison baseline slightly: its
iteration-1 event stream contains 15,078 private-Car initial reverse
transitions and 1,765 internal transitions. The new event-level source is:

```text
/mnt/DiskM/by/hk_road_network_audit_20260810_run62_v2/
  initial_private_car_uturn_events.csv
```

It contains 15,078 unique `person_id + private_car_trip_ordinal` keys across
10,802 persons. The lightweight independent extractor reproduces all 15,078
rows from 66,342 private-Car traffic sessions at:

```text
/mnt/DiskM/by/hk_car_origin_uturn_observations_20260810_run62_v1/
```

The bounded repair is opt-in through
`--car-origin-anchor-observations=<csv>`. For each observed start-link/reverse-
link pair it resolves the selected iteration-1 Car leg, checks that the two
links are exact network reverses, and evaluates both anchors with the same
production `TripRouter`, experienced Car `TravelTime`, and dynamic
energy/toll rules used by ordinary Car routing. For a middle activity whose
preceding leg is also Car, both the arrival and departure routes are rebuilt.
Only the first Car leg of the day may instead change its departure anchor
alone. A later Car leg with a non-Car immediate predecessor still depends on
the vehicle parked by an earlier, non-adjacent Car arrival; it is therefore
retained as `nonadjacent_prior_car_continuity_guarded` rather than treated as
an independent new vehicle. The preceding mode remains in the candidate
audit so that this continuity decision is explicit.

Automatic application is intentionally narrower than candidate discovery.
The reverse-direction link must allow Car, lie within 150 m of the activity,
be below the 80 km/h expressway-entry threshold, have no mapped toll-facility
identity, and not be one of the already proven restricted service links. Its
complete departure route must remove the initial reversal, the preceding Car
arrival must not acquire a terminal reversal, and the unpenalised joint
generalised cost may not increase by more than 300 seconds. Ranking includes
walking access, preceding-arrival and next-departure Car time, energy/toll
money converted with the configured Car time/money utilities, plus a 1,800-
second structural penalty for an immediate reversal. The output audit records
both complete-route time/distance/cost fields and every rejection reason.

Changing an activity `linkId` alone would not survive a later MATSim
`ReRoute`, because the stock router prefers the activity facility's link. A
successful repair therefore creates a person/activity-specific routing
facility on the chosen link when the activity already has a canonical
facility. Dynamic parking canonicalises that proxy back to the original
facility identity, so destination TCS zone, duration, and charge remain
unchanged in meaning. If the source activity originally has no facility, the
repair preserves that null facility identity and changes only its explicit
`linkId`; creating a synthetic parking identity would be incorrect and is not
needed because MATSim already routes such activities from their link.

Household joint travel is a hard guard, not a soft penalty. The selected joint
driver route contains physical pickup/drop-off waypoints that are absent from
the driver's activity chain, and the household binding catalog restores that
exact waypoint route after ordinary route preparation. Any active driver or
passenger leg on either side of the shared activity anchor is labelled
`joint_binding_guarded` and is not rewritten. This preserves passenger
boarding/alighting links, driver leg/vehicle identity, waypoint order, and the
3,956 active run62 bindings; it also prevents the endpoint of a physically
bound passenger arrival from moving. A future joint-aware direction repair
must rebuild only the origin-to-first-waypoint segment and then replace the
binding's stored route atomically; the generic repair is not authorised to do
that.

The hard guard covers bindings active in the current one-shot household
selection. Dormant candidate rows are not mutated and cannot become active
later in this fixed-selector validation. Before enabling repeated household
candidate generation or selection in future iterations, origin-anchor repair
must either precede candidate construction or trigger an anchor-aware rebuild
of every affected waypoint route. Activating a stale dormant waypoint route
after its driver's anchor has changed is outside the v1 guarantee.

The first validation attempt is retained as a failed mechanical diagnostic:

```text
/mnt/DiskM/by/hk_stage11_car_origin_anchor_repair_20260810_release63/
/mnt/DiskM/by/hk_stage11_car_origin_anchor_repair_20260810_run63/
```

Run63 completed without changing any route: all 15,078 observations received
`preceding_leg_is_not_car`. The cause was an implementation error that treated
every new Car tour after an earlier non-Car trip as an intermediate parked-Car
activity. It therefore provides no effectiveness evidence and is not an
accepted sensitivity result. The corrected code treats a non-Car predecessor
as a new Car tour, reroutes only the Car departure, records the predecessor
mode, and additionally guards active passenger legs sharing that activity.
The first corrected attempt uses new directories and does not overwrite run63:

```text
/mnt/DiskM/by/hk_stage11_car_origin_anchor_repair_20260810_release64/
/mnt/DiskM/by/hk_stage11_car_origin_anchor_repair_20260810_run64/
```

Run64 retains the run62 road-hotspot repair, no traffic signals, unlimited
ordinary-PT capacity for the existing mechanical gate, and zero ordinary
`ReRoute`, `SubtourModeChoice`, and `TimeAllocationMutator` weights. Iteration
0 preserves the baseline plans; household/student deterministic selection and
the guarded anchor repair occur before the physical iteration 1.

Run64 completed with exit code 0 and preserved the same 3,956 active bindings,
including 981 observations rejected as `joint_binding_guarded`. It nevertheless
applied zero repairs: 13,261 otherwise accepted candidates failed only during
installation because their source activities correctly had no facility, while
the implementation incorrectly required a canonical parking facility for
every departure anchor. These activities are not parking destinations at that
point. The fix preserves their null facility and changes only their explicit
link, which is MATSim's routing identity for a facility-free activity; it does
not invent a TCS zone or parking charge. Run64 is therefore also diagnostic,
not an effectiveness result. The replacement run is:

```text
/mnt/DiskM/by/hk_stage11_car_origin_anchor_repair_20260810_release65/
/mnt/DiskM/by/hk_stage11_car_origin_anchor_repair_20260810_run65/
```

Run65 completed with exit code 0 and was the first attempt to apply real
changes. It repaired 1,708 direct Car departures, preserved all 3,956 active
household bindings, and reduced iteration-1 lost agents from the paired
iteration-0 value of 5,890 to 3,270. Another 11,553 candidates begin after a
physical Walk access leg at a MATSim `car interaction` stage. Run65 left those
unchanged because interaction activities reject custom attributes. Changing
only the Car leg would also leave the physical Walk route ending on the old
link, so a simple attribute suppression is not a valid fix.

The stage-aware repair atomically rebuilds the physical Walk access route,
moves the interaction link, and rebuilds the following Car route. It writes no
custom attributes on interaction activities and retains the same household
driver/passenger guard across both adjacent legs. The replacement validation
is:

```text
/mnt/DiskM/by/hk_stage11_car_origin_anchor_repair_20260810_release66/
/mnt/DiskM/by/hk_stage11_car_origin_anchor_repair_20260810_run66/
```

Run66 reached 13,259 high-confidence applications and preserved all 3,956
bindings, but failed before iteration-1 QSim. The rebuilt access leg correctly
retained `mode=walk`, but the installer incorrectly changed its `routingMode`
from the enclosing main mode `car` to `walk`. MATSim therefore rejected the
mixed `walk/car` routing modes inside one trip. The final correction replaces
only the Walk `NetworkRoute` and travel time while preserving its existing
`routingMode=car`. Run66 output is explicitly invalid. Its replacement uses:

```text
/mnt/DiskM/by/hk_stage11_car_origin_anchor_repair_20260810_release67/
/mnt/DiskM/by/hk_stage11_car_origin_anchor_repair_20260810_run67/
```

Run67 applied all 13,259 filtered candidates and completed physical QSim, but
reported 8,207 dynamic-parking link mismatches. These are real vehicle-chain
violations, not proxy-facility audit noise: a later Car tour can follow an
immediately preceding Walk/PT trip while the vehicle remains parked at the
link reached by an earlier, non-adjacent Car leg. Moving only the later origin
would teleport the parked vehicle across carriageways. Run67 is therefore not
accepted despite its lower lost-agent count.

The bounded v1 automation is narrowed to the intended continuity rule: the
first Car leg of the day may optimise departure alone; an immediately adjacent
previous Car leg is jointly rerouted; a later Car leg with only a non-adjacent
prior Car receives `nonadjacent_prior_car_continuity_guarded`. Resolving the
latter requires a future multi-activity vehicle-chain anchor change rather
than a local departure edit. The replacement validation is:

```text
/mnt/DiskM/by/hk_stage11_car_origin_anchor_repair_20260810_release68/
/mnt/DiskM/by/hk_stage11_car_origin_anchor_repair_20260810_run68/
```

Run68 evaluates all 15,078 observations after the existing household selector
has activated the same 3,956 physical bindings. It applies 4,633 first-day-Car
high-confidence repairs, guards 981 observations that touch an active joint
binding, and retains 9,200 later Car departures as
`nonadjacent_prior_car_continuity_guarded`. A further 261 observations are
already resolved by the current production router and three fail the bounded
300-second joint-cost gate; no route evaluation fails. The two-iteration run
then completes with exit code 0. Iteration 1 reports 2,856 lost agents versus
the paired fixed-plan iteration-0 baseline of 5,890, and dynamic parking keeps
`parkingFacilityMismatches=0` across 42,615 parking events. All 3,956 active
joint bindings are classified: 3,849 board, 3,833 alight and complete, five
drivers are stuck before pickup, and 61 bindings reach simulation end before
pickup. This is slightly better than run67's 3,830 completions while removing
all 8,207 parking-continuity errors from that rejected run. The complete road-
event comparison is retained at:

```text
/mnt/DiskM/by/hk_road_network_audit_20260810_run68_v1/
```

| fixed-supply iteration-1 metric | run62 | run68 | change |
| --- | ---: | ---: | ---: |
| Private-Car initial reverse transitions | 15,078 | 10,435 | -4,643 (-30.8%) |
| Private-Car internal reverse transitions | 1,765 | 1,759 | -6 |
| Private-Car trips with distance/direct ratio >2 | 11,418 | 11,204 | -214 |
| Private-Car trips with distance/direct ratio >3 | 1,901 | 1,893 | -8 |
| Private-Car trips with repeated links | 842 | 837 | -5 |
| Private-Car adjacency mismatches | 0 | 0 | 0 |
| Private-Car unfinished trips | 884 | 917 | +33 |
| All road-vehicle stuck events | 1,897 | 1,770 | -127 (-6.7%) |
| Total road delay, vehicle-hours | 52,809.005 | 48,459.486 | -4,349.520 (-8.2%) |
| All-agent QSim lost | 3,056 | 2,856 | -200 |
| Active household bindings | 3,956 | 3,956 | 0 |
| Completed physical household bindings | 3,850 | 3,833 | -17 |
| Dynamic parking facility mismatches | 0 | 0 | 0 |

The event audit independently reconstructs 4,643 fewer realised initial
reversals, close to but not assumed from the 4,633 plan-level applications.
It finds no new path discontinuity and effectively leaves internal reversals
unchanged, so the bounded origin repair is not masking them. The network-wide
delay and stuck totals improve, but the private-Car component alone has 33
more unfinished trips; Bus and GMB stuck reductions account for the aggregate
gain. Household routes are not directly rewritten, but changed background
traffic has a small indirect effect: completed bindings fall by 17 (0.43% of
all bindings) relative to run62. Run68 is accepted as the bounded v1
sensitivity implementation, not as proof that all remaining origin anchors or
internal turns are correct and not yet as a production-manifest adoption.

The 1,765 run62 internal private-Car reversals are not suitable for a blanket
turn ban. They are distributed across 1,267 link pairs; the largest pair has
only 12 events. The leading examples are ordinary 50 km/h two-way local-
distributor segments, including Lo Wu Station Road, where a terminal or access
turnback remains plausible. The directed-node triage at
`/mnt/DiskM/by/hk_private_car_internal_uturn_structure_20260810_run62_v1/`
classifies 784 events as forced reverse-only dead-end/missing-connector cases,
529 as low-choice terminal/access contexts, and only 452 as junctions with two
or more alternative outgoing Car links. The first group cannot be solved by a
turn ban because it would make the route infeasible; the last group is only an
evidence-review universe, not a proven-illegal set. No internal
`DisallowedNextLinks` restriction is adopted without OSM restriction,
median/junction geometry, or official road-layout evidence. Internal
restrictions are re-audited after the origin-anchor result at
`/mnt/DiskM/by/hk_private_car_internal_uturn_structure_20260810_run68_v1/`.
The remaining 1,759 events across 1,261 pairs classify as 783 forced-reverse,
526 low-choice terminal/access, and 450 multiple-alternative junction events.
These differ from run62 by only one, three, and two events respectively. The
stability confirms that the origin fix did not silently transform internal
turns. The current network export has geometry and directed degree but no OSM
restriction or official junction-layout field, so even the 450
multiple-alternative events are an evidence-review universe rather than
proven illegal turns. No `DisallowedNextLinks` restriction is adopted in v1;
doing so now would violate the source-evidence gate and risks making the 783
forced-reverse paths infeasible.

## Repair order before traffic signals or ordinary innovation

1. Audit the 31 links contributing half the delay and their immediate
   upstream/downstream storage. Start with parallel-link allocation around
   `road_261323_0_f`, then the persistent 203xxx/2475xxx--2476xxx and
   210xxx/2473xxx clusters. Compare against source road class, direction,
   lanes, connector length, turns, and detector-derived capacity before any
   edit.
2. Audit short connectors inside stuck clusters. Do not apply a city-wide
   minimum length or capacity; merge or adjust only links shown to be
   topological artifacts or unrealistic queue-storage boundaries.
3. Repair activity-to-road direction and turn legality for the 15,055 initial
   Car reverse transitions. Re-route only the affected fixed routes after the
   underlying link assignment or restriction is corrected.
4. Review internal Bus/GMB/school-bus reverse and repeated-link cases against
   route terminals and waypoint order. Preserve legitimate terminal loops.
5. Inspect the 650 outside-largest-component links, prioritising the 55 used
   links and six stuck events; leave unused isolated service geometry as an
   explicit low-priority category unless it is expected to carry demand.
6. Re-run one identical no-signal, no-innovation iteration. Acceptance should
   require lower hotspot delay/stuck without new path discontinuity or school-
   bus boarding regression.
7. Only after the fixed-supply gate passes, enable ordinary `ReRoute` alone in
   a separate comparison. Keep mode choice and time mutation frozen so route
   adaptation is identifiable. Traffic signals remain frozen until this
   no-signal road baseline is stable.

## Reproduction

The streaming, standard-library audit entry point is:

```text
scripts/hong_kong_single_city/analysis_visualization/
  audit_hong_kong_road_network_runtime.py
```

It emits full link runtime metrics, static anomalies, road stuck hotspots and
hourly counts, per-class top path candidates, initial/internal reverse-link
pairs, top link rankings, and hourly profiles. Its output directory must be
new, so prior attempts cannot be silently overwritten.
