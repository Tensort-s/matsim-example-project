# Hong Kong private-car cost source model v1

## Scope

This document records the canonical private-car cost sources and data-quality
audit for the Hong Kong MATSim model. Stage 3 produced the immutable offline
source release. Stage 8A later authorizes only its hash-locked base
`fuel_or_electricity` component through the runtime contract in
[`HONG_KONG_CAR_ENERGY_RUNTIME.md`](HONG_KONG_CAR_ENERGY_RUNTIME.md).

The workflow does not modify:

- routed or unrouted plans, config, network, facilities, private vehicles,
  transit schedule, or transit vehicles;
- `RunHongKong5Pct.java`;
- `car` or `ride` ASC, `car monetaryDistanceRate`, global
  `marginalUtilityOfMoney`, or `SubtourModeChoice`;
- taxi or public-transport scoring behavior;
- road capacity or any simulation output.

The four cost components remain separate:

1. `fuel_or_electricity`;
2. `toll`;
3. `destination_parking`;
4. `fixed_vehicle_ownership_cost`.

The first three are candidate marginal costs. Fixed ownership cost is one
vehicle-day record per used private car and is never repeated on each leg.

## Canonical release status

The current canonical offline behavioral-cost interface is:

```text
data/transport_costs/hongkong/car_cost_v1/
  unified_marginal_cost_interface_v1/
```

Its release control file is:

```text
data/transport_costs/hongkong/car_cost_v1/
  canonical_car_cost_interface_manifest.json
```

All behavioral-cost integration must resolve the canonical path through that
manifest and read only `unified_marginal_cost_interface_v1`. The locked
source manifest remains an offline release record. Stage 8A does not rewrite
it: the authoritative integrated consumer manifest separately approves only
the base `fuel_or_electricity` component for guarded runtime use. Toll,
destination parking, motorcycles, and fixed ownership remain inactive.

The original top-level `car_leg_cost_estimates_<scenario>.parquet`,
`car_cost_model_validation.json`, and `car_cost_summary_by_*.csv` files remain
in place with their original SHA256 for provenance. They are now explicitly:

```text
superseded_offline_prototype
```

They must not be used as current behavioral totals or as MATSim scoring input.
`car_cost_version_transition_audit.csv` records the status, exact hash,
replacement, and source commit for each file. The supporting top-level source
manifest and rule tables are retained as historical prototype provenance, not
as the canonical combined behavior interface.

The prototype reported 1,008 confirmed charged private-car legs. Subsequent
official toll-facility/network topology mapping, WHC alias resolution, ordered
physical-passage reconstruction, and time-dependent rate application produce
the current canonical candidate:

- 25,858 confirmed charged private-car legs;
- 38,931 confirmed no-charge private-car legs;
- 30,837 physical toll-facility passage events;
- 63,954 complete private-car marginal-cost legs;
- 835 parking-incomplete private-car legs retained as null.

This transition changes version authority only. It does not change any cost
method, energy parameter, toll rate, parking rule, or MATSim input.

## Read-only production inputs

The feature worktree does not contain ignored Hong Kong production data.
Therefore the canonical project data tree is read-only input, while every
script, rule, source snapshot, output, document, and Git change is written only
to the feature worktree.

Read-only inputs:

```text
data/matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice/
  plans_routed_5pct_v2.xml.gz
  plans_unrouted_5pct_v2.xml.gz
  facilities_5pct_v2.xml.gz
  privateVehicles_5pct.xml.gz
  agent_trip_manifest_v2.parquet
  config_hong_kong_5pct_v2_activity_modechoice_50it.xml

data/transit/hongkong/processed/
  matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_ferry_core_v1_cap010/
    network.xml.gz
    transitSchedule_5pct.xml.gz
    transitVehicles_10pct.xml.gz

data/transit/hongkong/RdNet_IRNP.gdb
data/matsim_agents/hongkong/synthetic_households_tcs2022/synthetic_households.parquet
data/worldcommuting_od/hongkong/custom_features/hong_kong_fixed_link_grid/
  CityAndRegionSplit/hong_kong_fixed_link_grid/regions.shp
```

The trip manifest contains 743,614 main legs, including 67,718 `car` legs.
The routed XML maps 64,789 of those legs to `private_car` vehicles and 2,929
to `motorcycle` vehicles. Motorcycle legs remain in the audit so the `car`
count conserves, but private-car costs are not assigned to them.

The current read-only Car scoring snapshot remains unchanged:

| Parameter | Value |
|---|---:|
| constant | -0.5 |
| marginalUtilityOfTraveling | -6 util/h |
| monetaryDistanceRate | -0.0007/m |

Stage 8A does not assign an economic meaning to that distance rate and does
not modify it. The new Car energy component requires the standard Car
`monetaryDistanceRate` to be exactly zero at factory creation and fails closed
otherwise. This is an activation precondition, not a config change or a claim
that the existing snapshot is HKD/fuel.

## Sources and provenance

Pinned source files are under:

```text
data/transport_costs/hongkong/car_cost_v1/source_snapshots/
```

`car_cost_source_manifest.json` records publisher, URL, retrieval date,
effective date, local source file, byte size, and SHA256. The principal sources
are:

- Consumer Council Oil Price Watch, 2026-07-28 10:47 snapshot;
- Hong Kong Government reply citing EMSD private-car energy consumption;
- Government 2026 CLP and HK Electric average net tariff announcement;
- Transport Department December 2025 licensed vehicles by fuel type;
- Transport Department road-tunnel, harbour-crossing, and Tai Lam toll pages;
- the official `RdNet_IRNP.gdb` `TUN_BRIDGE_TOLL` and
  `TUN_BRIDGE_TV_TOLL` tables;
- Transport Department government-car-park, parking-meter, and March 2026
  parking fee schedules;
- Hong Kong Housing Authority 2026 car-park fees;
- Transport Department 2026 vehicle licence fee schedule.

The GDB is a directory. Its audit digest is computed over sorted relative file
names and bytes; the precise method and result are recorded in the source
manifest.

## Fuel and electricity

The MATSim vehicle file distinguishes `private_car` and `motorcycle`, but does
not contain a private-car powertrain. Version 1 therefore applies a
representative licensed-fleet average and does not fabricate a petrol or
electric label for individual vehicles.

Transport Department December 2025 licensed private cars:

| Fuel group | Licensed vehicles | Share |
|---|---:|---:|
| Petrol | 432,752 | 73.984% |
| Diesel | 10,338 | 1.768% |
| Electric | 141,771 | 24.238% |
| Other | 53 | 0.009% |
| Total | 584,914 | 100% |

Diesel and other non-electric private cars are included in a transparent
combustion proxy because version 1 has no per-vehicle fuel type or diesel price.
This is a limitation, not a reconstructed vehicle attribute.

The Consumer Council standard-petrol snapshot gives a minimum walk-in price of
HKD 22.67/L, median walk-in price of HKD 25.67/L, and maximum listed pump
price of HKD 32.67/L. The 2026 average net electricity tariffs are
HKD 1.406/kWh for CLP and HKD 1.633/kWh for HK Electric; the base value is a
2.9-million/0.6-million customer-weighted mean.

The government energy source gives 11.6 L/100 km for the dominant
1,501–2,500 cc petrol class and 20 kWh/100 km for the most common electric
private-car model. Low and high use explicit ±20% consumption sensitivity.

| Scenario | Petrol HKD/L | Electricity HKD/kWh | Petrol L/100 km | EV kWh/100 km | Fleet-average HKD/km |
|---|---:|---:|---:|---:|---:|
| low | 22.67 | 1.4060 | 9.28 | 16.0 | 1.648390 |
| base | 25.67 | 1.4449 | 11.60 | 20.0 | 2.326026 |
| high | 32.67 | 1.6330 | 13.92 | 24.0 | 3.540398 |

## Tolls

The official GDB private-car tables identify nine tolled facilities:

- Aberdeen Tunnel;
- Lion Rock Tunnel;
- Shing Mun Tunnels;
- Tate's Cairn Tunnel;
- Tsing Sha Control Area;
- Cross-Harbour Tunnel;
- Eastern Harbour Crossing;
- Western Harbour Crossing;
- Tai Lam Tunnel.

The routed car legs contain complete link sequences. The official
`FEATURE_ID_1` and `FEATURE_ID_2` values map directly to MATSim
`road_<ROUTE_ID>_...` link IDs. A charge is confirmed only when a route contains
one of those feature IDs. Complete routes without an official feature are
`confirmed_no_charge`; no cross-harbour or cross-zone inference is used.

The three road-harbour crossings and Tai Lam use the official two-minute
time-varying private-car schedules. Approximate toll passage time is:

```text
route departure
+ routed travel time * (matched link position + 0.5) / route link count
```

Base uses that time. Low and high are the minimum and maximum official toll
within ±10 minutes, representing passage-time interpolation uncertainty. Flat
tolls do not vary across scenarios. HKeToll is a payment mechanism and does not
add a separate modeled fee.

The audit applies private-car road tolls only. Taxi passenger tunnel
surcharges are not read or mixed into this model.

## Destination parking

Destination parking uses:

- destination facility;
- destination TCS zone;
- destination activity type;
- routed arrival time;
- time until the same vehicle next departs from the same facility.

TCS zones are grouped into Hong Kong Island (1–4), Kowloon/urban (5–13),
and New Territories/Lantau (14–26). Official 2026 public car-park, meter,
pass, and subscription prices bound the proxy. The result is not an observed
price for the destination facility.

Activity treatment:

| Activity | Treatment |
|---|---|
| home | temporary return-home cost is zero; residential parking remains fixed |
| work low | monthly subscription, zero marginal leg cost |
| work base | representative day pass |
| work high | hourly charge, at least the base day pass, capped at the high day bound |
| education | zone/time/duration hourly proxy |
| shopping | zone/time/duration hourly proxy |
| dining, leisure, social, VFR | zone/time/duration hourly proxy |
| medical, personal business | zone/time/duration hourly proxy |
| visitor accommodation | representative night pass |
| border | unresolved |
| other/unmatched | unresolved |

Hourly rules charge each started hour using the day or night rate at that
hour. One car arrival creates one `parking_session_id`. No session is charged
twice. A missing duration is not replaced by free parking; high work
sensitivity alone can use its documented upper-bound day cost.

## Fixed ownership cost

Fixed ownership cost is a partial daily proxy containing:

- official annual vehicle licence, fleet-share weighted between combustion
  and electric assumptions;
- residential monthly parking in base and high.

It excludes depreciation, finance, insurance, and maintenance because the
current synthetic vehicles contain no value, age, financing, or policy data.

| Scenario | Daily fixed cost per used private car |
|---|---:|
| low | HKD 11.603748 |
| base | HKD 126.121150 |
| high | HKD 183.457381 |

There are 21,020 used private cars. Each scenario contains exactly one fixed
record per used vehicle with `leg_sequence=-1` and
`record_scope=vehicle_day_fixed_cost_not_leg`. These values are excluded from
all leg marginal totals.

## Historical prototype output interface

The files in this section describe the initial top-level output contract from
commit `797f103e4cb12fbcc83a8cf9669bdbb1feb13b48`. They are preserved but
superseded. See **Canonical release status** above for the current authority.

Output directory:

```text
data/transport_costs/hongkong/car_cost_v1/
```

Rules and provenance:

- `car_cost_source_manifest.json`
- `car_energy_cost_parameters.csv`
- `car_toll_rules.csv`
- `car_parking_cost_rules.csv`

Long-form per-leg/fixed-cost outputs:

- `car_leg_cost_estimates_low.parquet`
- `car_leg_cost_estimates_base.parquet`
- `car_leg_cost_estimates_high.parquet`

Summaries and validation:

- `car_cost_summary_by_component.csv`
- `car_cost_summary_by_distance.csv`
- `car_cost_summary_by_destination.csv`
- `car_cost_summary_by_activity.csv`
- `car_cost_model_validation.json`

The Parquet files contain the required fields:

```text
person_id
leg_sequence
mode
route_distance_m
destination_facility_id
destination_tcs_zone
destination_activity_type
arrival_time_s
parking_duration_s
cost_component
cost_hkd
cost_source
cost_effective_date
cost_quality
scenario
```

They also record vehicle class, representative powertrain treatment,
origin facility/zone, parking session, toll facility/link/status,
record scope, and unresolved reason.

## Historical prototype results (superseded)

### Prototype component distributions

Statistics below are over the applicable private-car leg or used-vehicle
records. A zero toll is a confirmed no-charge route, not missing data.

| Scenario | Component | Median HKD | Mean HKD | P90 HKD |
|---|---|---:|---:|---:|
| low | fuel_or_electricity | 20.454 | 25.615 | 54.169 |
| low | toll | 0 | 0.296 | 0 |
| low | destination_parking | 0 | 13.003 | 38 |
| low | fixed_vehicle_ownership_cost | 11.604 | 11.604 | 11.604 |
| base | fuel_or_electricity | 28.862 | 36.145 | 76.438 |
| base | toll | 0 | 0.303 | 0 |
| base | destination_parking | 32 | 40.921 | 110 |
| base | fixed_vehicle_ownership_cost | 126.121 | 126.121 | 126.121 |
| high | fuel_or_electricity | 43.930 | 55.015 | 116.344 |
| high | toll | 0 | 0.307 | 0 |
| high | destination_parking | 42 | 52.499 | 192 |
| high | fixed_vehicle_ownership_cost | 183.457 | 183.457 | 183.457 |

Private-car marginal totals, excluding fixed ownership cost:

| Scenario | Median HKD | Mean HKD | P90 HKD |
|---|---:|---:|---:|
| low | 36.590 | 38.860 | 70.173 |
| base | 61.640 | 77.199 | 178.424 |
| high | 84.039 | 107.605 | 260.460 |

### Prototype identification and unresolved data

- prototype toll identification among private-car legs: 100%;
- prototype confirmed charged private-car legs: 1,008 (1.556%);
- prototype confirmed no-charge private-car legs: 63,781;
- base parking identification among private-car legs: 99.588%;
- base parking unresolved duration: 164;
- base parking unresolved TCS zone: 103;
- `car` legs using out-of-scope motorcycle vehicles: 2,929.

Base confirmed toll facilities:

| Facility | Charged legs |
|---|---:|
| Tai Lam Tunnel | 421 |
| Shing Mun Tunnels | 412 |
| Lion Rock Tunnel | 71 |
| Tsing Sha Control Area | 59 |
| Western Harbour Crossing | 44 |
| Lion Rock Tunnel plus Tai Lam Tunnel | 1 |

## Historical prototype validation

`car_cost_model_validation.json` confirms:

- 67,718 routed car legs equal the input car-leg count;
- no negative cost;
- energy cost is monotone non-decreasing with route distance;
- one unique parking session per private-car arrival and zero duplicate
  parking charges;
- all home parking records are zero;
- fixed ownership cost has one vehicle-day record per used private car and is
  not attached to legs;
- toll charged, no-charge, ambiguous, and unresolved states are separate;
- every cost component satisfies `low <= base <= high`;
- all pinned source snapshot hashes match the manifest;
- before/after SHA256 is identical for plans, manifest, config, facilities,
  private vehicles, network, transit schedule, and transit vehicles;
- `data/matsim_agents/hongkong` Git status is unchanged and empty.

The scripts pass `py_compile`; repository-level `git diff --check` is part of
the final worktree verification.

## Current behavioral-integration boundary

The initial recommendation below is retained conceptually, but its data source
is now exclusively `unified_marginal_cost_interface_v1`; the old top-level
Parquet totals are prohibited. If a later, separately approved MATSim
implementation is undertaken, its candidate leg-marginal composition is:

1. representative `fuel_or_electricity`;
2. confirmed link-level `toll`;
3. resolved `destination_parking`.

Do not include:

- fixed vehicle ownership cost on every leg;
- unresolved parking as zero;
- motorcycle legs under private-car rules;
- taxi passenger tunnel surcharge;
- a cross-harbour toll inferred only from OD;
- direct HKD-to-utility conversion without an explicitly calibrated monetary
  utility design.

## Commands

The following commands reproduce the superseded initial prototype and are
retained for provenance only. They do not produce the current canonical
interface and must not be used to overwrite the historical files during normal
integration.

Build pinned prototype sources and rules:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\car\build_hong_kong_car_cost_rules.py `
  --input-project-root F:\Matsim\matsim-example-project `
  --output-dir .\data\transport_costs\hongkong\car_cost_v1
```

Use `--refresh-sources` only when intentionally updating the source snapshot
date and reviewing every resulting parameter change.

Estimate prototype costs and run its historical internal validation:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\car\estimate_hong_kong_car_leg_costs.py `
  --input-project-root F:\Matsim\matsim-example-project `
  --output-dir .\data\transport_costs\hongkong\car_cost_v1
```

Generate only the canonical release manifest, transition audit, and release
validation without recalculating costs:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\car\finalize_hong_kong_car_cost_v1_canonical.py `
  --input-project-root F:\Matsim\matsim-example-project
```
