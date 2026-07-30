# Hong Kong GMB Core v1 offline fare audit

This is a source-snapshot audit and quote layer only. It does not price
production generic PT legs or change MATSim inputs/scoring.

- `97,521` distinct schedule forward pairs are checked directly
  against raw GTFS route/origin/destination records.
- `published_fare_hkd` is neutral: the source does not prove adult, child,
  cash, Octopus, ticket type, or fare effective period.
- all 1,161 schedule routes uniquely match an official JSON
  `routeId+routeSeq+stopSeq` full pattern. Route suffixes are recorded but
  never used as official direction evidence.
- `mapping_quality` is separate from `cost_quality`; available exact-pattern
  records are mapping A and cost B.
- `fullFare` is reference-only and never fills sectional or missing OD fares.
- 98,182
  GTFS candidate-record comparisons contain
  57,362 amounts
  equal to JSON `fullFare` and
  40,820
  different amounts; equality does not establish fare semantics.
- `2026-07-14` is a source revision cut-off, not a fare effective date.
- queries require `temporal_basis=source_snapshot_only` and empty
  `travel_date`.
- transfer concessions remain `not_modelled`; `cost_hkd` is not a final
  discounted fare.
