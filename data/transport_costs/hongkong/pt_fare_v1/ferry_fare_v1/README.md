# Hong Kong Ferry Core v1 offline fare rules

This directory is an audit and offline quote layer only. It does not change or
price MATSim plans and is not connected to config, scoring, Java, network,
schedule, vehicles, facilities, or transfer concessions.

Direct official inputs are TD GTFS `fare_attributes.txt` / `fare_rules.txt`
and the TD Ferry route-stop GeoJSON snapshot. The production schedule and
`ferry_stop_facilities.csv` are read only to prove the 39 MATSim route and stop
crosswalks.

Key source semantics:

- `price` is a published GTFS amount in HKD, but the source does not identify
  adult/child, cash/Octopus, class, vessel type, weekday, weekend, or holiday.
- the active neutral amount field is `published_fare_hkd`; there is no
  `adult_base_fare_hkd` compatibility alias;
- queries therefore accept only `unspecified` for those source-unspecified
  dimensions;
- `mapping_quality` describes route/direction/OD evidence, while
  `cost_quality` is B for exact-direction published amounts and C where the
  official direction is not encoded. B does not prove an adult payable fare;
- `source_revision_cutoff_date=2026-07-14` describes the local TD snapshot,
  not a route fare effective date. `cost_effective_date` is empty and queries
  require `temporal_basis=source_snapshot_only` with an empty `travel_date`;
- GTFS route + ordered origin/destination is used without reverse substitution,
  interpolation, path summing, aggregation, or missing-value zero fill;
- JSON `fullFare` is retained only in
  `ferry_route_full_fare_reference.csv`; it is never a default quote;
- transfer concessions are `not_modelled`.

`cost_hkd` is only the published base amount component. It is not an actual
passenger fare or final discounted fare.

Current build: 39 Ferry routes,
60 required ordered forward pairs,
60 available published-amount rules, and
102 route-direction full-fare references.
