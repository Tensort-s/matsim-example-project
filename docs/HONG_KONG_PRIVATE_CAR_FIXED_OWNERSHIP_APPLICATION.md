# Hong Kong private-car fixed-ownership vehicle-day application v1

## Scope and status

This stage creates an independent, offline
`fixed_vehicle_ownership_cost` low/base/high candidate for Hong Kong private
cars. The result is a `partial_fixed_vehicle_ownership_proxy`, not complete
total cost of ownership.

Each scenario contains exactly one record per private car used on the modeled
typical weekday. The record has:

```text
leg_sequence=-1
record_scope=vehicle_day_fixed_cost_not_leg
owner_observed=false
```

The candidate is not attached to any of the 64,789 private-car legs. It does
not modify MATSim scoring, plans, config, network, facilities, vehicles,
energy, toll, parking, or the existing unified car-cost outputs.

The validation result is:

```text
publishable_candidate=true
blocked=false
```

Publication must retain the representative-category, partial-cost, and
non-observed-owner qualifications below.

## Locked inputs and protection

The build starts from commit
`b6264a366eaab5be9bc0b470db991ee49785317f`. Canonical large inputs are
read-only runtime roles:

- routed V2 plans;
- private vehicles;
- V2 trip manifest;
- full synthetic-household table.

Repository inputs include:

- the car input-feasibility outputs;
- `car_cost_source_manifest.json`;
- all frozen source snapshots;
- the old and independently audited energy parameter tables;
- the complete energy, toll-network, toll-rate, and parking candidates;
- the existing unified car-cost files.

`fixed_ownership_application_input_hashes.json` stores repository-relative
paths and before/after SHA256 values. It omits the local absolute canonical
root. All canonical inputs, all existing files under `car_cost_v1`, and all
source snapshots remained byte-identical. Every snapshot hash also agrees
with `car_cost_source_manifest.json`.

## Independent vehicle-day charging object

The script parses the selected routed plan for each manifest `car` leg and
reads `vehicleRefId` directly from the route. It resolves vehicle class from
`privateVehicles_5pct.xml.gz` and does not use the old fixed-cost rows to
construct the charging set.

| Audit item | Result |
| --- | ---: |
| Routed `car` legs | 67,718 |
| Private-car legs | 64,789 |
| Motorcycle legs, out of scope | 2,929 |
| Missing `vehicleRefId` | 0 |
| Unique used private cars | 21,020 |
| Vehicles used by multiple persons | 0 |
| Vehicles linked to multiple households | 0 |
| Vehicle-person-household mapping coverage | 100% |
| Duplicate vehicle-days before scenario expansion | 0 |

The plan user and household are assignment relationships. They are not
observed legal ownership:

```text
owner_observed=false
person_id_semantics=unique_plan_user_not_legal_owner_claim
```

The independent vehicle-chain diagnostic finds 466 time-overlap events
affecting 457 vehicles and 321 next-departure facility mismatches affecting
108 vehicles. These defects create zero extra fixed-cost records. The charging
key remains the unique `vehicle_ref_id`, once per scenario.

## Exact frozen-source audit

### Annual vehicle licence

Source:

```text
data/transport_costs/hongkong/car_cost_v1/source_snapshots/
  td_vehicle_licence_fees_2026.pdf
SHA256:
  5964b65bacd37dc59965934de46688665e3f3de5ef3dd2b02fe02b94d60f8303
Publisher:
  Transport Department
Location:
  PDF page 2, Vehicle Licence table, Annual Fee column
Frozen schedule effective date:
  2026-03-01
```

The PDF explicitly states that electric licence renewals taking effect from
1 March 2026 use the displayed structure. The frozen source manifest pins the
schedule to 1 March 2026.

| Scenario | Combustion proxy category | HKD/year | Electric category | HKD/year |
| --- | --- | ---: | --- | ---: |
| low | Petrol, not exceeding 1,500cc | 5,074 | Not exceeding 75kW | 1,614 |
| base | Petrol, over 1,500cc through 2,500cc | 7,498 | Over 125kW through 175kW | 2,614 |
| high | Petrol, over 2,500cc through 3,500cc | 9,929 | Over 225kW | 5,114 |

These are official category fees but analyst scenario selections. The MATSim
vehicle file has neither engine displacement nor rated power, so no individual
vehicle is assigned one of these categories. The combustion fleet group also
contains licensed diesel and other non-electric cars; the petrol fee tier is
therefore an explicit representative proxy, not a claim that all combustion
cars are petrol cars.

### Residential-parking proxy

Base source:

```text
data/transport_costs/hongkong/car_cost_v1/source_snapshots/
  housing_authority_carpark_fees_2026.pdf
SHA256:
  ed158acfeadbf37b4fe175266d1c88c7af3c368baf57152ec0f9b09fba0c588b
Publisher:
  Hong Kong Housing Authority
Location:
  PDF page 5, Annex; Region A Hong Kong and Kowloon; occupancy at least
  90%; Private Car; Full Time; Covered; monthly charge
Effective period:
  2026-01-01 through 2026-12-31
Value:
  HKD 3,310/month
```

High source:

```text
data/transport_costs/hongkong/car_cost_v1/source_snapshots/
  td_parking_fees_2026.pdf
SHA256:
  313351664ee878c8a634f82d644cfa58d14246565049386cfb3ba129f806d660
Publisher:
  Transport Department
Location:
  PDF page 1; Star Ferry government public car park; Private Car/Van;
  Monthly/Quarterly Rate; monthly non-reserved
Effective date:
  2026-03-01
Value:
  HKD 4,850/month
```

The high value also appears for City Hall monthly parking. It is an official
government public-car-park monthly fee, not an observed residential fee for
each modeled vehicle. It is retained only as an analyst high-sensitivity
proxy.

The frozen `td_government_car_parks.html` is hash-protected but is not the
parameter source for HKD 4,850; the exact value and category are in the
official PDF schedule.

Low uses:

```text
residential_parking_component_excluded_in_low_sensitivity
```

Its HKD 0 monthly component is an analyst exclusion, not a claim that low
scenario owners receive free residential parking.

No work-parking monthly subscription or
`excluded_monthly_rate_hkd` from the parking candidate is imported.

## Licensed-fleet proxy and formulas

The script re-reads the official Transport Department December 2025 workbook,
sheet `T4.4`, rather than copying a prior final share.

| Licensed group | Vehicles |
| --- | ---: |
| Petrol | 432,752 |
| Diesel | 10,338 |
| Electric | 141,771 |
| LPG | 0 |
| Hydrogen | 0 |
| Others | 53 |
| Total | 584,914 |

```text
combustion_proxy_share
  = (432752 + 10338 + 0 + 0 + 53) / 584914
  = 0.7576207784392236

electric_share
  = 141771 / 584914
  = 0.24237922156077646
```

No random, vehicle-ID, or hash-based powertrain allocation is used.

For each scenario:

```text
fleet_weighted_annual_licence_hkd
  = combustion_share * combustion_annual_licence_hkd
  + electric_share * electric_annual_licence_hkd

daily_licence_proxy_hkd
  = fleet_weighted_annual_licence_hkd / 365

daily_residential_parking_proxy_hkd
  = residential_monthly_parking_proxy_hkd * 12 / 365

fixed_vehicle_ownership_cost_hkd_per_vehicle_day
  = daily_licence_proxy_hkd
  + daily_residential_parking_proxy_hkd
```

The 365-day denominator is an annual-cost model-day allocation convention. It
does not mean a licence or monthly parking payment occurs every day.

## Cost boundary

Included:

- annual vehicle licence fee proxy;
- residential monthly parking proxy;
- their sum as `partial_fixed_vehicle_ownership_proxy`.

Excluded:

- depreciation and vehicle purchase price;
- financing and interest;
- insurance;
- maintenance and repair;
- tyres;
- inspection;
- work-parking subscription;
- destination temporary parking;
- fuel or electricity;
- toll.

## Results

| Scenario | Weighted annual licence (HKD) | Daily licence | Daily residential parking | Fixed HKD/vehicle-day | 21,020-vehicle total (HKD) |
| --- | ---: | ---: | ---: | ---: | ---: |
| low | 4,235.367893 | 11.603748 | 0.000000 | 11.603748 | 243,910.775669 |
| base | 6,314.219882 | 17.299233 | 108.821918 | 126.121150 | 2,651,066.580596 |
| high | 8,761.944048 | 24.005326 | 159.452055 | 183.457381 | 3,856,274.147652 |

Because the same representative vehicle-day rate applies to every used
vehicle in a scenario, its mean, median, and P90 are equal to the displayed
per-vehicle-day rate.

## Outputs

`data/transport_costs/hongkong/car_cost_v1/fixed_ownership_application_v1/`
contains:

- `fixed_ownership_parameters_repository_relative.csv`;
- `vehicle_day_fixed_ownership_costs_low.parquet`;
- `vehicle_day_fixed_ownership_costs_base.parquet`;
- `vehicle_day_fixed_ownership_costs_high.parquet`;
- `fixed_ownership_application_validation.json`;
- `fixed_ownership_application_summary.csv`;
- `fixed_ownership_application_required_repairs.csv`;
- `fixed_ownership_application_input_hashes.json`.

Each Parquet contains the plan user and household, vehicle-day identity,
component dates, candidate reference date, fleet shares, licence and parking
subcomponents, allocation semantics, exclusions, quality, and assumption
status.

The required-repairs table records five non-blocking limitations: legal owner
is unobserved, licence tiers are representative, the high parking fee is a
non-residential proxy, the model is partial rather than complete TCO, and low
parking is an exclusion rather than free-parking evidence.

## Validation

The machine-readable validation confirms:

- 67,718 `car` legs, 64,789 private-car legs, and 2,929 out-of-scope
  motorcycle legs;
- 21,020 unique private cars and 21,020 rows per scenario;
- 63,060 scenario-expanded rows;
- no missing vehicle reference, motorcycle record, normal leg sequence, or
  person/normal-leg key collision;
- one record per vehicle and scenario;
- complete vehicle-person-household and synthetic-household mapping;
- `owner_observed=false`;
- no negative cost and `low <= base <= high`;
- exact vehicle-count-times-rate totals;
- exact licence-plus-parking component sums;
- independently reproducible source and cost formulas;
- no parameter copied from the old final CSV;
- all source hashes match the frozen manifest;
- canonical inputs and all existing unified, energy, toll, and parking files
  have identical before/after SHA256 values.

## Reproduction

Run from the feature-worktree root with the project geospatial Python:

```powershell
<python-geo311> -B `
  scripts/hong_kong_single_city/costs/car/apply_hong_kong_private_car_fixed_ownership_costs.py `
  --input-project-root <canonical-project-root>
```

The canonical root is a runtime input role and is deliberately omitted from
committed artifacts. Combining this candidate with marginal energy, toll, or
destination-parking costs, or inserting it into MATSim scoring, requires a
separate approved stage.
