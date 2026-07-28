# Hong Kong private-car representative-fleet energy application v1

## Scope and status

This stage creates an independent, offline
`fuel_or_electricity` low/base/high candidate for Hong Kong private-car legs.
It does not combine energy with tolls, parking, or fixed ownership cost and
does not modify MATSim scoring, plans, config, network, facilities, vehicles,
mode choice, or the existing unified car-cost outputs.

The candidate is publishable as a representative licensed-fleet average
proxy. It is not a vehicle-level powertrain model:

```text
individual_powertrain_available=false
individual_powertrain_identifiable_leg_count=0
individual_powertrain_identifiable_fraction=0
vehicle_powertrain=representative_hk_private_car_fleet_average_proxy
proxy_assignment_scope=fleet_average_applied_to_each_private_car_leg
per_vehicle_powertrain_claimed=false
```

No vehicle is randomly classified and no vehicle ID or hash is used to create
a petrol, diesel, or electric label.

## Locked inputs and provenance

The candidate is tied to commit
`a2c6286c8c382222af784ec357e9b14abb77a2c5`. Canonical read-only roles are:

- `data/matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice/plans_routed_5pct_v2.xml.gz`;
- `data/matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice/privateVehicles_5pct.xml.gz`;
- `data/matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice/agent_trip_manifest_v2.parquet`;
- `data/transit/hongkong/processed/matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_ferry_core_v1_cap010/network.xml.gz`.

The four frozen energy snapshots are:

- Consumer Council Oil Price Watch;
- Hong Kong Government private-car energy-consumption reply;
- Hong Kong Government 2026 electricity-tariff announcement;
- Transport Department December 2025 licensed vehicles by fuel type.

Their repository-relative paths, manifest and actual SHA256 values are stored
in `energy_application_input_hashes.json`. All four hashes agree with
`car_cost_source_manifest.json`.

All canonical inputs, existing unified car costs, toll mapping, toll rate
candidate, parking event candidate, and existing source snapshots remained
byte-identical.

## Licensed-fleet proxy

The script reads the `Private Cars` row from official TD workbook sheet
`T4.4` instead of copying the previous final shares:

| Licensed fuel group | Vehicles |
| --- | ---: |
| petrol | 432,752 |
| diesel | 10,338 |
| electric | 141,771 |
| LPG | 0 |
| hydrogen | 0 |
| other | 53 |
| total | 584,914 |

The electric share is the official licensed electric-private-car share:

```text
141771 / 584914 = 0.24237922156077646
```

Petrol, diesel, LPG, hydrogen, and other non-electric cars are combined only
as a combustion cost proxy:

```text
(432752 + 10338 + 0 + 0 + 53) / 584914
= 0.7576207784392236
```

The two shares sum to exactly 1 within floating-point precision. Diesel and
other non-electric cars have not been identified as petrol cars. Because the
MATSim vehicle file has neither individual fuel type nor engine properties and
the frozen candidate lacks separate diesel price/consumption parameters, the
combustion group temporarily uses the petrol cost proxy.

## Prices, consumption, and time semantics

The Consumer Council snapshot was observed at 10:47 HKT on 28 July 2026.
Its five standard-petrol walk-in prices are HKD
`22.67, 25.67, 25.67, 26.67, 31.77` per litre; the listed pump price is HKD
32.67 per litre. Therefore:

- low is the minimum standard-petrol walk-in price, HKD 22.67/L;
- base is the median standard-petrol walk-in price, HKD 25.67/L;
- high is the maximum listed standard-petrol pump price, HKD 32.67/L.

The government announcement gives 2026 average net tariffs of
HKD 1.406/kWh for CLP and HKD 1.633/kWh for HK Electric, effective
1 January 2026. Base uses rounded official 2025 customer-account weights:
CLP 2.9 million and HK Electric 0.6 million. The supporting official sources
are the [CLP customer-services page](https://www.clpgroup.com/en/about/our-business/assets-and-services/hong-kong/customer-services.html)
and the [HK Electric 2025 annual-report operating summary](https://www.hkelectric.com/documents/en/InvestorRelations/Documents/Financial%20Reports/2025/AR/2025_HKEI_AR_E_04.pdf).

```text
(1.406 × 2,900,000 + 1.633 × 600,000) / 3,500,000
= 1.4449142857142858 HKD/kWh
```

These supporting customer-count links are official web references but are not
part of the original frozen source-snapshot manifest; that status is explicit
in the parameter and repair files.

The government consumption source, published 6 May 2020, reports
11.6 L/100 km for the dominant 1,501–2,500 cc petrol class and
0.2 kWh/km, or 20 kWh/100 km, for the most common electric private-car model.
The 9.28/11.6/13.92 L/100 km and 16/20/24 kWh/100 km values apply
0.8/1.0/1.2 analyst sensitivity factors. The ±20% values are not an official
observed distribution.

Low/base/high change price and consumption together. They are a joint scenario
envelope, not a statistical confidence or probability interval.

The parameter table separately records:

- petrol observation timestamp;
- electricity tariff effective period;
- fleet reference date;
- energy-consumption publication date;
- source snapshot date;
- scenario-assumption status.

`cost_effective_date=2026-07-28` is only the price-candidate reference date. It
does not assert that all component sources took effect on that date.

## Parameter reconstruction

The script independently recomputes:

```text
combustion HKD/km = petrol HKD/L × L/100 km ÷ 100
electric HKD/km   = electricity HKD/kWh × kWh/100 km ÷ 100
fleet HKD/km      = combustion share × combustion HKD/km
                  + electric share × electric HKD/km
leg HKD           = route distance m ÷ 1000 × fleet HKD/km
```

| Scenario | Combustion HKD/km | Electric HKD/km | Weighted combustion | Weighted electric | Fleet average HKD/km |
| --- | ---: | ---: | ---: | ---: | ---: |
| low | 2.103776 | 0.224960 | 1.593864411 | 0.054525630 | 1.648390040 |
| base | 2.977720 | 0.288982857 | 2.255982544 | 0.070043440 | 2.326025984 |
| high | 4.547664 | 0.391920 | 3.445404740 | 0.094993265 | 3.540398004 |

All parameter formula errors are zero. Differences from the frozen parameter
table are no larger than `8.89e-16`, caused only by floating-point
representation.

## Route-distance audit

All 67,718 car legs are retained:

| Vehicle class | Present | NaN | Negative | Zero | Positive |
| --- | ---: | ---: | ---: | ---: | ---: |
| private car | 64,789 | 0 | 0 | 33 | 64,756 |
| motorcycle | 2,929 | 0 | 0 | 4 | 2,925 |
| all car mode | 67,718 | 0 | 0 | 37 | 67,681 |

The trip manifest has no distance field, so manifest-distance comparison is
explicitly unavailable. No value is inferred or filled.

For every route, the script reconstructs start, intermediate, and end links
and sums official network link lengths. In this routed file the MATSim route
distance consistently equals:

```text
complete link-sequence length - start-link length
```

The maximum absolute residual against that convention is
`5.82e-11 m`. Canonical route distance is not replaced.

Raw `route distance - complete link-sequence sum` diagnostics are:

| Statistic | Difference (m) | Relative difference |
| --- | ---: | ---: |
| minimum | -5,066.423 | -1.000000 |
| P10 | -303.844 | -0.041927 |
| median | -83.033 | -0.007214 |
| P90 | -15.855 | -0.001125 |
| P99 | -5.436 | -0.000272 |
| maximum | -1.517 | -0.000049 |

The raw difference is the start-link length excluded by the canonical route
distance convention, not evidence for replacing the route distance.

### Zero-distance classification

All 33 private-car zero-distance legs are classified
`valid_same_link_or_same_location_zero_distance` because each:

- has a complete link sequence;
- contains exactly one link;
- has identical start and end link;
- has no interior link;
- is topologically valid;
- has zero canonical route distance under the audited convention.

They receive `resolved_zero_distance_energy_zero` and HKD 0. No zero-distance
leg contains a non-trivial positive-length interior route. Such a future case
would be `unresolved_zero_distance_inconsistent_route` with null cost.

## Results

Each scenario contains 67,718 rows:

| Status | Count |
| --- | ---: |
| resolved representative fleet average | 64,756 |
| resolved audited zero distance | 33 |
| unresolved | 0 |
| out-of-scope motorcycle | 2,929 |

Resolved-only statistics include the 33 audited true zeros and exclude
motorcycles:

| Scenario | Total HKD | Mean | Median | P90 |
| --- | ---: | ---: | ---: | ---: |
| low | 1,659,564.360 | 25.615 | 20.454 | 54.169 |
| base | 2,341,793.950 | 36.145 | 28.862 | 76.438 |
| high | 3,564,398.113 | 55.015 | 43.930 | 116.344 |

The maximum per-leg formula error is `5.68e-14 HKD`. All non-null costs are
non-negative, satisfy `low <= base <= high`, and increase monotonically with
positive route distance under the common proxy.

## Outputs and reproduction

`data/transport_costs/hongkong/car_cost_v1/energy_application_v1/` contains:

- `energy_parameters_repository_relative.csv`;
- `car_leg_energy_cost_estimates_low.parquet`;
- `car_leg_energy_cost_estimates_base.parquet`;
- `car_leg_energy_cost_estimates_high.parquet`;
- `energy_application_validation.json`;
- `energy_application_summary.csv`;
- `energy_application_required_repairs.csv`;
- `energy_application_input_hashes.json`.

Run from the feature-worktree root:

```powershell
<geo-python> -B scripts/hong_kong_single_city/costs/car/apply_hong_kong_private_car_energy_costs.py `
  --input-project-root <canonical-project-root>
```

The runtime input root is deliberately omitted from committed artifacts.
Adoption into MATSim scoring or combination with toll/parking/fixed cost
requires a separate approved stage.
