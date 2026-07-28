# Hong Kong taxi fare model and offline fare audit v1

This document records the first offline Hong Kong taxi fare model. It estimates
taxi passenger payments for the taxi passenger-leg allocation layer only. It
does not modify any MATSim plans, configs, facilities, vehicles, network files,
Java runners, modes, activities, OD, departure times, road capacities, or
scoring parameters.

## Inputs

Classification input:

```text
data/taxi/hongkong/processed/taxi_initial_plan_allocation_v1/
```

MATSim read-only inputs:

```text
data/matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice/
  plans_unrouted_5pct_v2.xml.gz
  plans_routed_5pct_v2.xml.gz
  agent_trip_manifest_v2.parquet
  facilities_5pct_v2.xml.gz

data/transit/hongkong/processed/
  matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_ferry_core_v1_cap010/
    network.xml.gz
```

Official source snapshots are archived under:

```text
data/taxi/hongkong/raw/official_fare_sources_2026/
```

Sources:

- Transport Department taxi fare page:
  `https://www.td.gov.hk/en/transport_in_hong_kong/public_transport/taxi/taxi_fare_of_hong_kong/index.html`
- Transport Department taxi operating-area page:
  `https://www.td.gov.hk/en/transport_in_hong_kong/public_transport/taxi/details_of_taxi_operating_areas_/`
- Transport Department road tunnel toll page:
  `https://www.td.gov.hk/en/transport_in_hong_kong/tunnels_and_bridges_n/toll_matters/toll_rates_of_road_tunnels_and_lantau_link/index.html`
- Road Harbour Crossing time-varying toll page:
  `https://www.td.gov.hk/en/transport_in_hong_kong/tunnels_and_bridges_n/tvt/index.html`
- Tai Lam Tunnel toll page:
  `https://www.td.gov.hk/en/transport_in_hong_kong/tunnels_and_bridges_n/tlt/index.html`

`source_manifest.json` records URL, local source-file path, download date, file
size, and SHA256.

## Fare rules

The machine-readable rules are:

```text
data/taxi/hongkong/processed/taxi_fare_model_v1/
  taxi_fare_rules.csv
  taxi_tunnel_surcharge_rules.csv
  taxi_type_assignment_rules.md
```

The meter rules use the Transport Department taxi fare table effective from
2024-07-14. The first 2 km or part thereof are covered by flagfall. Subsequent
distance is charged with the official discrete 200 m or part thereof jump
rules using `ceil(chargeable_distance_m / 200)`. A trip exactly within the
first 2 km receives no extra distance increment.

The fare fields are in HKD. `booking_fee_hkd`, `baggage_fee_hkd`, and
`other_surcharge_hkd` are zero in this first audit because the current inputs
do not identify telephone/platform bookings, baggage, pets, or other
surcharges. Tips and ride-hailing dynamic pricing are not modelled.

Tunnel surcharge rules distinguish taxi passenger surcharge from private
vehicle road toll. Because the routed `ride` legs contain generic MATSim route
distance and travel time but no complete link sequence, v1 does not apply any
tunnel surcharge. Possible cross-harbour OD legs are marked as ambiguous rather
than treated as confirmed tunnel use.

## Taxi type assignment

The offline type assignment uses service-area logic, not fleet-share random
allocation:

- all known zones in North Lantau-compatible zone 22: `lantau_taxi`;
- all known zones in New Territories zones 14-21 and 23-25:
  `new_territories_taxi`;
- urban/Hong Kong Island/Kowloon/Tsuen Wan/Kwai Chung/Tsing Yi zones 1-13, or
  ordinary urban-New Territories tours: `urban_taxi`;
- unresolved zones, SWNT zone 26, or mixed Lantau/non-Lantau evidence:
  `unresolved`.

The same taxi type is applied to all taxi legs in a selected tour. Unresolved
legs retain `taxi_type=unresolved` and include fare ranges under all three
taxi fare tables.

## Distance and congestion

Distance priority:

1. `route_distance_m` from `plans_routed_5pct_v2.xml.gz` generic route
   attributes.
2. If unavailable, no final fare distance is substituted from straight-line
   distance in v1.

The output also records `euclidean_distance_m`, `distance_source`,
`route_available`, and `distance_ratio`.

Congestion proxy is unavailable in v1. The routed `ride` legs have generic
travel times, but not a QSim-congested link sequence paired with a reliable
freeflow travel-time calculation. Therefore `fare_waiting_hkd=0`, and
`total_fare_congestion_proxy_hkd` equals the distance-only total. This is
recorded explicitly with
`congestion_proxy_status=unavailable_generic_route_not_qsim_congested_or_no_link_freeflow`.

## Outputs

Output directory:

```text
data/taxi/hongkong/processed/taxi_fare_model_v1/
```

Main per-leg files:

- `taxi_leg_fare_estimates_low.parquet`
- `taxi_leg_fare_estimates_base.parquet`
- `taxi_leg_fare_estimates_high.parquet`

Summary files:

- `taxi_fare_summary_by_type.csv`
- `taxi_fare_summary_by_time.csv`
- `taxi_fare_summary_by_distance.csv`
- `taxi_fare_summary_by_purpose.csv`
- `taxi_fare_summary_by_tcs26_od.csv`
- `taxi_fare_summary_by_population_group.csv`
- `taxi_fare_summary_by_person.csv`

Validation:

- `taxi_fare_model_validation.json`

## Current validation status

The completed run produced:

| Scenario | Taxi passenger legs |
|---|---:|
| low | 34,257 |
| base | 37,286 |
| high | 42,510 |

Base checks:

- explicit taxi retained: 4,614 legs;
- base added taxi legs: 32,672;
- non-taxi candidate legs not charged: 5,884;
- private-car passenger and school-bus legs are not charged;
- same-tour taxi classification is consistent;
- no negative fares;
- assigned-type fares are never below the corresponding flagfall;
- route distance unavailable share: 0;
- congestion proxy unavailable share: 1.0;
- taxi type unresolved share: 0.067934;
- confirmed tolled-tunnel surcharge share: 0, because no link sequence is
  available to confirm tunnel use;
- plans, facilities, and network SHA256 hashes are unchanged;
- `git status --short -- data/matsim_agents/hongkong` is empty before and
  after the run.

## Commands

Build rules and source manifest:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\build_hong_kong_taxi_fare_model.py
```

Estimate low/base/high fares:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\estimate_hong_kong_taxi_leg_fares.py
```

## Limitations

This is an offline audit layer, not a MATSim behavioural model. Fare values are
not written into MATSim scoring, and `ride` legs are not converted to `taxi`.
Tunnel charges are not applied without confirmed route link sequences. The
congestion proxy is unavailable until a reliable congested travel time and
freeflow link-time comparison exists for taxi passenger legs.

The first follow-on taxi utility-conversion design is documented in
`docs/HONG_KONG_TAXI_UTILITY_DESIGN.md`. It tests taxi-specific fare utility
coefficients and ASC search values offline without modifying the active MATSim
config.
