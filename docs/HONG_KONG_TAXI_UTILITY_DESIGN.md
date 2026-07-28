# Hong Kong taxi utility design v1

This document records the first offline taxi utility-conversion and parameter
scenario design for the Hong Kong MATSim model. It is a diagnostic layer only:
it does not modify any existing MATSim plans, configs, facilities, vehicles,
networks, Java runners, simulation outputs, modes, or scoring parameters.

## Inputs

Taxi fare audit input:

```text
data/taxi/hongkong/processed/taxi_fare_model_v1/
  taxi_leg_fare_estimates_base.parquet
  taxi_leg_fare_estimates_low.parquet
  taxi_leg_fare_estimates_high.parquet
  taxi_fare_model_validation.json
```

Read-only MATSim scoring input:

```text
data/matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice/
  config_hong_kong_5pct_v2_activity_modechoice_50it.xml
```

The current v2 config keeps the existing main modes:

| Mode | Constant | Travel utility | Monetary term |
|---|---:|---:|---:|
| car | -0.5 | -6 util/h | -0.0007 per m |
| pt | 0 | -6 util/h | none |
| walk | 0 | -6 util/h | none |
| ride | -1.5 | -6 util/h | -0.0015 per m |

Version 1 does not change these values and keeps the global monetary utility
assumption at `marginalUtilityOfMoney=1.0`. Taxi fare is not converted with
that global value.

## Utility formula

The diagnostic taxi utility is:

```text
taxi_utility =
  taxi_asc
  + marginal_utility_of_traveling * travel_time_hours
  - taxi_fare_utility_per_hkd * fare_baseline_hkd * fare_share_factor
```

Parameters:

- `marginal_utility_of_traveling = -6.0 util/h`;
- `taxi_fare_utility_per_hkd` is taxi-specific and separate from global money
  utility;
- `fare_share_factor` represents how much of the estimated passenger fare is
  internalized by the modeled passenger;
- `taxi_asc` is not fixed in this offline step.

Excluded in v1:

- pickup waiting;
- meter waiting fare;
- tunnel surcharge;
- booking fee;
- dynamic pricing;
- fleet supply constraint.

The output also includes
`approximate_effective_time_utility = -12 util/h * travel_time_hours` as a
diagnostic comparator only. It is not a proposed scoring setting.

## Parameter scenarios

The design tests four taxi fare coefficients:

```text
0.03, 0.05, 0.075, 0.10 util/HKD
```

and three fare-share factors:

```text
1.0, 0.75, 0.5
```

This gives 12 parameter scenarios. The implied value of time diagnostic is:

```text
implied_vot_hkd_hr = 12 / taxi_fare_utility_per_hkd
```

| Fare coefficient | Implied VOT |
|---:|---:|
| 0.03 util/HKD | 400 HKD/h |
| 0.05 util/HKD | 240 HKD/h |
| 0.075 util/HKD | 160 HKD/h |
| 0.10 util/HKD | 120 HKD/h |

The recommended center scenario for future MATSim calibration is:

```text
taxi_fare_utility_per_hkd = 0.05
fare_share_factor = 1.0
taxi_asc = to be calibrated in MATSim iterations
```

For that center scenario, the base-leg diagnostics are:

| Metric | Value |
|---|---:|
| implied VOT | 240 HKD/h |
| median taxi fare utility | -4.915 |
| median direct travel-time utility | -0.878 |
| median total utility before ASC | -5.807 |
| P90 total utility before ASC | -1.682 |
| median fare/direct-time utility ratio | 5.437 |
| median fare/effective-time utility ratio | 2.718 |

## ASC search

The ASC grid tests:

```text
taxi_asc = -3, -2, ..., +8
```

For each fare coefficient and fare-share combination, the grid reports the
mean, median, P10, and P90 utility offset after adding ASC. This is an offline
utility-offset table only. It is not a mode-share prediction.

Fare coefficient and ASC cannot be identified from the same aggregate taxi
total target alone. The intended calibration order is:

1. fix the fare coefficient using behavioural judgement, external evidence, or
   a separate price-sensitivity target;
2. run MATSim with taxi as a behavioural pilot mode;
3. calibrate `taxi_asc` against final MATSim taxi legs and validation metrics.

## Outputs

Output directory:

```text
data/taxi/hongkong/processed/taxi_utility_design_v1/
```

Files:

- `taxi_utility_parameter_scenarios.csv`: 12 fare coefficient and fare-share
  combinations, implied VOT, and summary utility statistics.
- `taxi_leg_utility_audit_base.parquet`: leg-level utility components for all
  37,286 base taxi passenger legs under all 12 scenarios.
- `taxi_utility_summary.csv`: scenario-level mean, median, P10, P25, P75, P90,
  and P95 for fare utility, time utility, total utility, and utility ratios.
- `taxi_asc_search_grid.csv`: ASC values from -3 to +8 for each scenario.
- `taxi_utility_design_validation.json`: input hashes, config scoring snapshot,
  protected-file hashes, git status, and validation flags.

## Command

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\build_hong_kong_taxi_utility_design.py
```

## Validation status

The current run produced:

- base fare legs: 37,286;
- parameter scenarios: 12;
- leg audit rows: 447,432;
- ASC grid rows: 144;
- input fare parquet and validation JSON SHA256 unchanged;
- protected plans, config, facilities, vehicles, and network SHA256 unchanged;
- `git status --short -- data/matsim_agents/hongkong` empty before and after.

This is a taxi behavioural pilot design, not an explicit taxi operating-fleet
model. Tunnel and waiting costs remain excluded until the next fare-model
version can identify reliable tunnel routes and waiting-time evidence. Do not
write HKD directly into MATSim scoring as `1 HKD = 1 util`.
