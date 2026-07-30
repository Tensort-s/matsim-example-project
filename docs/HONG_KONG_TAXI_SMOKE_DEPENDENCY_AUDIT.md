# Hong Kong Taxi smoke dependency attribution audit v1

## Purpose

This is a read-only attribution workflow for the failed fixed-plan Taxi smoke
at checkpoint `2bb935d3cf395bd88cad1c54fdd5436ebca7672c`. It does not repair
PT routes, Taxi scoring, plans, network supply, or simulation parameters.

The failed smoke stopped in iteration 0 with 30,230 Taxi departures and
arrivals, 7,056 expected Taxi departures missing, 12,387 whole-model stuck
events, and no Taxi stuck event. The run log also contains repeated
`pt-leg has no TransitRoute` messages. A shared person ID is not treated as
causal evidence by itself: plan order, mapped PT leg position, Taxi ordinal,
scheduled departure time, and observed events are evaluated together.

## Read-only implementation

`HongKongTaxiSmokeDependencyAudit` accepts every input as an explicit command
line path. It:

1. loads the original and Taxi plans through MATSim 2026.0;
2. classifies the actual runtime route object of every selected-plan PT leg;
3. uniquely matches PT legs by person, plan-element position, and neighboring
   activity signature;
4. compares mode, routing mode, route class/content, travel fields, transit
   IDs, and leg attributes;
5. parses the complete failed run log and maps each per-person removal
   occurrence to that person's ordered invalid PT legs;
6. reads the existing iteration 0 events without creating a Controler or QSim;
7. reconciles expected Taxi ordinals with departure/arrival events;
8. assigns every missing Taxi departure to one mutually exclusive category;
9. audits stuck mode, hour, link, Taxi-person, PT-removal, and before-Taxi
   intersections;
10. checks all input SHA256 values before and after.

MATSim 2026 `TransitAgentImpl.getDesiredAccessStopId()` explicitly requires
the current route to implement `TransitPassengerRoute`. A generic route is
logged and the agent is removed. This audit therefore uses Java runtime
`instanceof TransitPassengerRoute`, not XML text, as the legal-route test.

## PT matching contract

The cross-file key is:

```text
person_id
+ selected plan
+ plan-element index
+ previous/next activity signature
```

Plan element order is used instead of a raw cross-file leg sequence. Route
class, description, start/end link, distance, travel time, transit stop/line/
route IDs, routing mode, and attributes are then compared field by field. Any
missing, extra, or activity-signature-ambiguous PT leg makes the audit fail.

## Missing Taxi attribution priority

Categories are mutually exclusive:

1. `multiple_blockers`
2. `invalid_pt_before_taxi_agent_removed`
3. `car_stuck_before_taxi`
4. `walk_stuck_before_taxi`
5. `null_mode_stuck_before_taxi`
6. `other_mode_stuck_before_taxi`
7. `invalid_pt_before_taxi_without_observed_removal`
8. `taxi_departure_missing_without_observed_upstream_blocker`
9. `unavailable_evidence`

A PT removal is applicable only when its mapped selected-plan PT element is
before the missing Taxi element. A stuck event is applicable only when its
event time is no later than the Taxi leg's defined expected departure time.

## Baseline comparison boundary

Historical formal-run logs and events exist on FUSELAB01, but the preliminary
inventory did not find a verified checkpoint plus complete input-SHA manifest
for those outputs. They are therefore not treated as a strictly comparable
runtime baseline. No new baseline Controler is run.

## Outputs

Successful remote execution writes compact products under:

```text
data/taxi/hongkong/processed/taxi_smoke_dependency_audit_v1/
```

Expected files include:

- `taxi_smoke_dependency_validation.json`
- `pt_route_runtime_type_summary.csv`
- `pt_route_conversion_comparison.csv`
- `pt_removal_person_counts.csv`
- `expected_taxi_leg_audit.csv`
- `missing_taxi_departure_attribution.csv`
- `stuck_event_summary.csv`
- `representative_failure_examples.csv`

The failed smoke logs, events, plans, and other large simulation products stay
on the server and are never committed.

## Validated execution

The audit was run on FUSELAB01 from detached checkpoint
`6d4038e01dfb7a68e6a6e9989ae7b5de7a552f66` in:

```text
/mnt/DiskM/by/hk_taxi_behavioral_pilot_v1/
dependency_audit_v1_6d4038e_a2
```

The runtime was Java 25.0.3, Maven 3.9.8, and MATSim 2026.0. The read-only
audit took 2 minutes 49 seconds, used 8,214,820 KiB maximum resident memory,
and exited 0. Its validation status is `validated`; all 26 required checks
passed. The recorded run flags confirm that no Controler, QSim, routing,
replanning, ASC experiment, or fleet run occurred.

All inputs had identical SHA256 values before and after:

| Input | SHA256 |
|---|---|
| base formal config | `662268c6aa81042d40096326d75736fe86f9594404f040180d185de84224a7b4` |
| original routed plans | `c73ee48e792e7aebd55b7a2691664ae7f3f4f27d307aef2a6bf58263b3aaafea` |
| Taxi plans | `f4631ab00c6f5027160314f7357e32d969b7588192008c17ac79bf0b3208ce27` |
| network | `dfc696442913a6d16a1ca1be7e5a332ec5762012190ed43a38f05493905ddc95` |
| transit schedule | `eb92e6c7b3c2746313be92b8c88d51bc645d1db3c6605d1f4b472f27c9896aed` |
| transit vehicles | `16a6b89f77d3827ded06641869bf4e4c5168fb718356c1fe04e9f9249fdd7429` |
| facilities | `74775533a7022b248d37197dbc94d27f239239aca386df75c7a391cc277ef10e` |
| private vehicles | `5a48b2afe404afaa6864a465c527277605a276e54cd879d3971261186938c994` |
| iteration 0 events | `f29dc764341bb7e481a9f55ed0831e3a7a958a31c9a8fbdec6844de0a6675cf5` |
| failed run log | `7b0b85f1c1132dd208e0366b7d690d3c920c12f39b96e359bf7f9f173b5a69ea` |
| failed-smoke validation | `2eec227ceb01792c01f3dad034f5a86cc905feb78876389c0eab2b852b30f772` |
| load-test validation | `114a97f53e0f4bc2d4bdcda103a7c07580fe0e9820a147858eb36d873afdf595` |

## PT route and conversion findings

Both the original and Taxi plans contain exactly 557,104 selected-plan PT
legs. MATSim 2026.0 deserialized every one as
`org.matsim.core.population.routes.GenericRouteImpl`; zero implement
`TransitPassengerRoute`, and zero are
`DefaultTransitPassengerRoute` or another legal transit-passenger route.
Consequently, all 557,104 lack accessible access-stop, egress-stop, line, and
transit-route IDs in the runtime interface.

The stable cross-file comparison matched all 557,104 PT legs, with zero
missing, extra, or ambiguous rows. All 557,104 were completely identical:
route-type changes, route-content changes, leg-attribute changes, mode
changes, and routing-mode changes were each zero. The Taxi conversion
therefore did not create or alter the PT route objects; the same
startup-intermediate representation is already present in the original
routed plans.

The complete run log contains 237,950 `pt-leg has no TransitRoute` lines,
237,950 unique persons, and 237,950 uniquely mapped PT legs. It also contains
237,950 `pt-agent doesn't know...` lines for the identical person set and
per-person counts. Every logged runtime class is `GenericRouteImpl`; all log
rows map uniquely to selected-plan PT elements. The first error is log line
286 for `hk_person_02893021`. Its complete five-element selected-plan context
is retained in `representative_failure_examples.csv`.

## Baseline startup-contract reconciliation

The route objects above are invalid if sent directly to QSim, but they are
not evidence that the adopted baseline lacked real PT simulation. The formal
baseline worker command includes:

```text
--simulate --clear-pt-routes
```

`RunHongKong5Pct` scans every person, every plan, and every plan element;
only a non-null route on `mode=pt` is set to null. The `Controler` then
installs `SwissRailRaptorModule`, allowing PrepareForSim/Raptor to construct
schedule-backed transit-passenger routes before QSim. The baseline log records
exactly 557,104 cleared PT routes.

The failed Taxi smoke installed SwissRailRaptor but did not perform the
required clear. Because all existing generic routes were non-null, they were
not rebuilt and reached QSim unchanged. Its earlier `routing_run=false`
identity was therefore inaccurate: deterministic PT startup rebuilding is a
routing operation, although it is not behavioural replanning.

The corrective smoke contract is explicit: clear exactly 557,104 source
generic PT routes before creating the `Controler`, rebuild them once before
iteration 0, require 557,104 legal schedule-backed
`TransitPassengerRoute` objects before QSim, and require the identical
prepared-route fingerprint before iteration 1. Strict Taxi and non-PT
fingerprints must remain unchanged throughout.

## Taxi departure attribution

The event reconciliation is exact:

| Metric | Count |
|---|---:|
| expected Taxi legs | 37,286 |
| observed Taxi departures | 30,230 |
| observed Taxi arrivals | 30,230 |
| missing Taxi departures | 7,056 |
| duplicate Taxi departures | 0 |
| unexpected Taxi departures | 0 |
| unmatched departures / arrivals | 0 / 0 |

The mutually exclusive missing-leg attribution closes to 7,056:

| Category | Missing legs | Unique persons |
|---|---:|---:|
| `invalid_pt_before_taxi_agent_removed` | 7,024 | 2,926 |
| `taxi_departure_missing_without_observed_upstream_blocker` | 32 | 14 |

For the 7,024 first-category legs, the mapped invalid PT leg is before the
missing Taxi element and its agent removal is observed in the run log. The
remaining 32 legs are not forced into a PT or stuck category: their 14 persons
have no qualifying PT removal or stuck event before the expected Taxi time.
Their final observed `stuckAndAbort` events are all at 108,000 seconds, after
the affected Taxi departure times of 61,200 to 91,800 seconds, so those
end-time events are not evidence of an upstream cause.

## Whole-model stuck findings

Events independently reproduce 12,387 stuck events for 12,387 unique persons:
11,753 `car`, 579 `walk`, and 55 null-mode. The numeric-hour distribution is:

```text
7:1, 8:137, 9:314, 10:432, 11:246, 12:304, 13:356, 14:416,
15:453, 16:581, 17:672, 18:1315, 19:1495, 20:1483, 21:1240,
22:884, 23:487, 24:420, 25:249, 26:118, 27:63, 28:63, 29:5,
30:653
```

The most frequent links have only 60 events each
(`road_102439_0_f` and `road_59920_0_f`), followed by
`road_58563_0_f` (59), `road_164493_0_f` (58), and
`road_102664_0_f` (56). No non-null stuck link is absent from the network.
There are 33 stuck events belonging to persons who have an expected Taxi leg,
but none occurs before an expected Taxi departure; the unique-person
intersection with PT-removal persons is zero. The 653 events at the QSim end
time of 108,000 seconds are reported separately. These observations do not
justify automatically assigning car, walk, or null stuck events to the PT
defect, nor do they isolate network capacity, vehicle, or route-endpoint
causality.

## Interpretation boundary

Strict output-to-output baseline comparison remains unavailable because the
historical formal outputs found on the server lack a verified checkpoint plus
complete input-SHA manifest. No baseline Controler was run for this audit.
Code, bundle, and baseline-log evidence nevertheless establishes the startup
contract directly. The supported conclusion is: original and Taxi plans have
exactly the same PT startup-intermediate objects; Taxi conversion did not
alter them; the failed Taxi runner omitted the baseline-required clear/rebuild
step; and observed pre-Taxi PT agent removals explain 7,024 of 7,056 missing
Taxi departures. Fare-schedule mismatch lines and invalid Taxi attribute
lines are both zero.

This attribution does not authorize PT fare/scoring changes, car-cost changes,
capacity changes, ASC changes, Taxi rerouting, or fleet/DVRP work. The next
validation is one fixed `ASC=-9`, no-replanning two-iteration smoke with only
the aligned PT startup preparation.

The committed compact products contain 37,286 expected Taxi rows, 7,056
missing-attribution rows, 237,950 per-person PT-removal rows, PT summaries,
stuck summaries, representative examples, and the validation JSON. They are
the complete auditable evidence for this checkpoint; the server logs, events,
and plans remain external.
