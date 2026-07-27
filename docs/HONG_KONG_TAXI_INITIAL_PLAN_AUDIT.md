# Hong Kong taxi initial-plan audit

This note records the July 2026 audit of Hong Kong taxi demand and fleet
controls against the current 5% MATSim initial plans. It is an audit-only
workflow: it does not overwrite or modify any existing `plans.xml.gz` file.

## Source archive

The downloaded Transport Department Monthly Traffic and Transport Digest files
are archived under:

```text
data/taxi/hongkong/raw/monthly_traffic_transport_digest_2026/
```

Archived files:

- `table21s_eng.csv`: Table 2.1S average daily passenger journeys.
- `table21_eng.csv`: Table 2.1 monthly passenger journeys.
- `table22_eng.csv`: Table 2.2 fleet and passenger-capacity fields.
- `table41a_eng.csv`: Table 4.1(a) vehicle registration/licensing fields.
- `mttd_dataspec_eng.pdf`: field definitions.

The generated `SOURCE_MANIFEST.csv` records original D-drive download paths,
file sizes, and SHA256 hashes.

## Official taxi controls

Rows are filtered with `TTD_PTO_CODE=TAX`. The requested period is January to
June 2026, but the current downloaded Tables 2.1S, 2.1, 2.2, and 4.1(a)
contain TAX rows only for:

```text
202601, 202602, 202603, 202604
```

The missing requested months are:

```text
202605, 202606
```

The audit therefore reports the requested Jan-Jun window but computes current
official means only from the available Jan-Apr records. No May or June taxi
values are imputed.

The control definitions are:

- `AVG_DAILY_PAX` and `PAX` are source values in thousand passenger journeys.
  The audit multiplies both fields by `1000` before comparing to MATSim demand.
- `NO_FLEET` from Table 2.2 is used as month-end operating taxi fleet.
- `PAX_CAP / NO_FLEET` is reported only as an average per-fleet-vehicle
  passenger-capacity check.
- `FIRST_REG` is not used as fleet size.
- Table 4.1(a) `TOTAL_LIC` is summed across Urban, NT, and Lantau taxis for
  licensed taxi counts by type.

For the available Jan-Apr records, the official 5% daily taxi-passenger target
is:

```text
mean: 37,285.773 passenger journeys/day
min:  34,256.780 passenger journeys/day
max:  42,509.991 passenger journeys/day
```

The latest available month is 202604, with `NO_FLEET=17,831` and summed
Table 4.1(a) `TOTAL_LIC=17,831`.

## Current initial-plan ride split

The audit reads:

```text
data/matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice/
  plans_unrouted_5pct_v2.xml.gz
  agent_trip_manifest_v2.parquet
  resident_discretionary_activity_assignments.parquet

data/matsim_agents/hongkong/typical_weekday_5pct_v1/
  agent_trip_manifest.parquet
```

The v2 manifest carries the current leg inventory, while the v1 manifest
provides preserved compulsory-leg `mode_detail`. Because
`resident_discretionary_activity_assignments.parquet` describes the generated
discretionary activity assignment rather than an observed taxi/private-car
operator split, discretionary `ride` legs are classified conservatively as
`unspecified_ride`.

The classification is:

- `mode_detail == taxi`: `taxi`
- `mode_detail in {private_vehicle, private_car_passenger_van}`:
  `private_car_passenger`
- `mode_detail == spb`: `school_bus`
- discretionary `ride`, visitor proxy `ride`, and missing detail:
  `unspecified_ride`

The current 5% unrouted v2 plans contain 56,360 `ride` legs. The XML leg-mode
streaming count matches `agent_trip_manifest_v2.parquet`.

Current 5% ride split:

| Subtype | Legs |
|---|---:|
| Explicit taxi | 4,614 |
| Private-car passenger | 3,564 |
| School bus | 9,626 |
| Unspecified ride | 38,556 |
| Total ride | 56,360 |

Against the available official mean target, explicit taxi has a 5% model gap of
32,671.773 passenger legs/day, or 653,435.460 expanded passenger legs/day at
weight 20. If all unspecified ride legs were reclassified as taxi, the model
would exceed the available official target by 5,884.227 5% legs/day. This means
the current `ride` population contains enough ambiguous volume to cover the
taxi control, but it is not yet classified or operated as an explicit taxi
fleet.

## Outputs and command

The audit command is:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\demand_generation\audit_hong_kong_taxi_initial_plan.py
```

Outputs are under:

```text
data/taxi/hongkong/processed/taxi_initial_plan_audit_2026_jan_jun/
```

Files:

- `taxi_official_daily_control.csv`: official Table 2.1S/2.1/2.2 TAX controls,
  converted from thousand passenger journeys where required.
- `taxi_fleet_by_type.csv`: Table 4.1(a) `TOTAL_LIC` by Urban, NT, and Lantau
  taxi type, with `FIRST_REG` retained only as a reference field.
- `taxi_initial_plan_audit.csv`: current v2 initial-plan `ride` legs split by
  subtype, population group, role, and detail source.
- `taxi_initial_plan_gap_summary.json`: summary of official target, current
  model counts, and gaps.
- `SOURCE_MANIFEST.csv`: raw source-file provenance and hashes.

## Modeling implication

This audit does not define a new Hong Kong MATSim production demand. It shows
that the current generic `ride` mode mixes taxi, private passenger, school-bus,
visitor proxy, and discretionary residual demand. A future taxi extension
should introduce an explicit taxi-demand calibration and an operator/fleet
representation, using Table 2.2 `NO_FLEET` as the operating fleet control and
Table 4.1(a) `TOTAL_LIC` only as licensed-fleet evidence by taxi type.
