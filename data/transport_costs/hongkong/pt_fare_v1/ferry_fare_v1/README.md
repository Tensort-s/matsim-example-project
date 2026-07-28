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
- queries therefore accept only `unspecified` for those source-unspecified
  dimensions;
- GTFS route + ordered origin/destination is used without reverse substitution,
  interpolation, path summing, aggregation, or missing-value zero fill;
- JSON `fullFare` is retained only in
  `ferry_route_full_fare_reference.csv`; it is never a default quote;
- transfer concessions are `not_modelled`.

Current build: 39 Ferry routes,
60 required ordered forward pairs,
60 available published-amount rules, and
102 route-direction full-fare references.
