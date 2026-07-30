# Hong Kong franchised-bus scope and fare-readiness audit v1

This is an operator-scope, direction-evidence, and ordered-OD candidate audit.
It creates no bus fare query, passenger cost, transfer rule, or MATSim scoring
integration.

- Schedule: 1,614 lines,
  2,363 routes, 69,589
  departures.
- Operator scope: {'confirmed_franchised_operator': 2255, 'operator_scope_unresolved': 5, 'other_bus_operator': 103}.
- Route-level franchise scope: {'confirmed_franchised_route': 2246, 'operator_scope_unresolved': 5, 'other_bus_service': 103, 'franchise_route_scope_unresolved': 9}.
- A route is confirmed only when its complete Bus JSON pattern and exact
  CSDI `COMPANY_CODE+ROUTE_ID+ROUTE_SEQ` key both exist; operator code alone
  is insufficient.
- Direction is exact only for a unique complete official
  `routeId+routeSeq+stopSeq` match. MATSim suffixes are never evidence.
- Ordered-OD candidate states: {'unique_candidate': 767043, 'conflicting_amounts': 2623, 'duplicate_identical': 2000}.
- Every candidate retains raw GTFS line identifiers, source path, and SHA256.
- No `cost_hkd` or selected production fare exists.
- All 2,358 JSON `fullFare` records are reference-only with
  `eligible_for_default_quote=false`.
- `2026-07-14` is a source revision cut-off, not a fare effective date.
