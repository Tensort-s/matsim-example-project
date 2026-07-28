# Hong Kong MTR station-OD fare rules v1

This directory contains pure offline adult Octopus rules for explicit ordered
MTR station IDs. `domestic_mtr_station_od` and
`airport_express_station_od` are separate scopes. Missing ordered pairs remain
unresolved; no reverse lookup, distance interpolation, path summation,
cross-scope fallback, or missing-value zero fill is used.

The quote interface does not read production plans. The existing 557,104
generic PT passenger-trip audit rows remain unresolved with null `cost_hkd`.
Transfer concessions are not modelled.

Every available amount is traced to an original official CSV line and source
SHA256. MTR fare effective-date evidence remains
`external_official_reference_not_locally_archived`.
