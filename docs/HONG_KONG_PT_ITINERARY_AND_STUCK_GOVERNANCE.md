# Hong Kong PT itinerary and stuck governance

## Status and boundary

Stage 6 adds a deterministic, read-only legality audit for prepared Hong Kong
PT itineraries and a fail-closed taxonomy for later PT/walk stuck events. It
does not route or rewrite plans, change the transit schedule, price a PT leg,
activate PT scoring, infer a fare, or run the Hong Kong scenario.

The implementation entry point is:

```text
org.matsim.project.hongkong.pt.HongKongPtItineraryAudit
```

The Taxi smoke runtime guard invokes this audit after standard
`PrepareForSimImpl` has created schedule-backed passenger routes and before
QSim. The guard keeps the audit for event-linked stuck classification. Taxi
routing, Taxi fare scoring, the Stage 5 composable scoring registry, and Taxi
fail-closed fare consumption are unchanged.

The committed Stage 6 validation record and taxonomy are:

```text
data/transport_costs/hongkong/integration_stage6_validation_v1/
  stage6_pt_itinerary_stuck_governance_validation.json
  stuck_root_cause_taxonomy.csv
```

They are implementation and historical-evidence records pending independent
exact-SHA review. They are not a production-population run result.

## Legal prepared-itinerary contract

The auditor reads each selected-plan main trip whose physical mode or routing
mode is PT. A legal trip must satisfy all of these conditions:

- trip elements alternate legs and recognized stage activities;
- each leg has `routingMode=pt`;
- physical leg modes are PT or a recognized walk-family mode;
- every PT leg has a non-null `TransitPassengerRoute`;
- access stop, egress stop, line, and transit route exist in the schedule;
- access and egress occur on the referenced route in that order;
- boarding is allowed at access and alighting at egress;
- stop offsets, schedule departures, route distances, and travel times are
  finite and nonnegative;
- at least one referenced service can be boarded at or after the deterministic
  ready time;
- access, egress, and transfer walk routes connect exactly through the
  adjacent main/stage activity and stop link IDs.

Missing route, time, link, or schedule data is an explicit audit reason. It is
never replaced with zero, a nearest stop, a reverse route, a distance proxy,
or another inferred itinerary. The audit sorts persons and reasons and emits a
SHA256 fingerprint so repeated reads of the same prepared population and
schedule are deterministic.

## Stuck attribution

The runtime guard retains the prepared-itinerary profile by person. A later
`PersonStuckEvent` is classified as:

- invalid PT or PT/walk itinerary, with the first sorted proven audit reason;
- legal PT or PT/walk itinerary with runtime cause unresolved;
- PT stuck without an audited PT trip;
- walk stuck outside the audited PT-trip scope; or
- a non-PT/walk stuck outside Stage 6 scope.

The original event reason is retained separately. A legal itinerary does not
authorize an inferred capacity, supply, demand, fare, transfer-concession, or
missing-data conclusion. Such a conclusion needs new event-linked evidence
from a separately authorized exact-SHA execution.

## Historical evidence classification

The first Taxi dependency run exposed 557,104 generic PT routes. It produced
237,950 PT route-removal log lines and blocked 7,024 later Taxi departures.
That failure remains historical and is superseded by the standard
PrepareForSim contract; it is not evidence about the current prepared
itinerary path.

The later offline PrepareForSim validation rebuilt all 557,104 source PT legs
into 1,092,811 schedule-backed `DefaultTransitPassengerRoute` segments with
zero null/generic routes and zero missing schedule references. That record
proved basic route-reference legality but did not audit stop order, boarding/
alighting permission, walk continuity, service availability, or event-linked
stuck causes.

The historical incomplete two-iteration attempt recorded 86,245 total stuck
events, including 79,045 PT stuck events. It also recorded 2,198 downstream
Taxi legs that did not depart; their last stuck modes were PT for 2,156 and
walk for 32, with one Taxi and nine without a stuck event. Fatal route/stop/
line/unknown-mode errors were zero. This proves upstream PT/walk blocking but
does not identify the precise runtime cause under the new Stage 6 taxonomy.
The cause remains unresolved; Stage 6 did not rerun that identity.

Canonical historical fields are referenced in
`stage6_pt_itinerary_stuck_governance_validation.json#historical_evidence`.
The incomplete iteration remains historical evidence, not a completed or
calibrated run.

## Deterministic validation

`HongKongPtItineraryAuditTest` covers:

- legal access–PT–egress continuity and read-only determinism;
- an explicit legal transfer walk and a broken transfer link;
- wrong stop order, forbidden boarding, and no later service;
- missing links, link discontinuity, and non-finite values;
- separation of non-PT walk stuck events from the PT itinerary scope.

The focused PT/Taxi guard tests and complete Maven suite pass. The durable
counts and commands are in
`stage6_pt_itinerary_stuck_governance_validation.json#regression_validation`.
No Hong Kong MATSim scenario, server task, Runner action, calibration, or
trend run was performed.

## Configuration and offline fare disposition

The canonical five-layer PT fare release remains
`offline_interfaces_validated_not_integrated_with_scoring`; generic production
PT legs remain unresolved/null in the offline fare layer. Car remains
offline-only. Stage 6 does not change `cities/hongkong/city.yaml`,
`runs/hongkong/run_manifest.json`, plans, network, schedule, vehicles,
facilities, demand, capacity, monetary utility, ASC, or transfer concessions.
