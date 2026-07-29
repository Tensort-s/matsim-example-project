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
