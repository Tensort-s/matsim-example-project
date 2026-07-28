# Hong Kong taxi utility design v1

This document records the first offline taxi utility-conversion and parameter
scenario design for the Hong Kong MATSim model, together with the subsequent
legacy `ride`-to-`taxi` utility bridge correction. These are diagnostic layers
only: they do not modify any existing MATSim plans, configs, facilities,
vehicles, networks, Java runners, simulation outputs, modes, or scoring
parameters.

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

The original offline ASC grid tested:

```text
taxi_asc = -3, -2, ..., +8
```

For each fare coefficient and fare-share combination, the grid reports the
mean, median, P10, and P90 utility offset after adding ASC. This is an offline
utility-offset table only. It is not a mode-share prediction.

This original `-3` to `+8` grid did not bridge against the complete legacy
`ride` score: in particular, it did not account for the existing
`monetaryDistanceRate=-0.0015` distance term. It is therefore retained only as
the historical offline parameter grid and **is no longer the center range for
the first MATSim taxi ASC tests**.

Fare coefficient and ASC cannot be identified from the same aggregate taxi
total target alone. The intended calibration order is:

1. fix the fare coefficient using behavioural judgement, external evidence, or
   a separate price-sensitivity target;
2. run MATSim with taxi as a behavioural pilot mode;
3. calibrate `taxi_asc` against final MATSim taxi legs and validation metrics.

## Legacy ride-to-taxi utility bridge correction

The bridge uses all 37,286 base taxi passenger legs and compares the score each
leg receives under the current `ride` parameters with the proposed central
taxi fare specification:

```text
old_ride_score =
  -1.5
  + (-6.0 * travel_time_hours)
  + (-0.0015 * effective_global_marginal_utility_of_money
     * route_distance_m)

new_taxi_score_before_asc =
  (-6.0 * travel_time_hours)
  + (-0.05 * fare_baseline_hkd)

asc_equivalent =
  old_ride_score - new_taxi_score_before_asc

asc_equivalent_simplified =
  -1.5
  - 0.0015 * effective_global_marginal_utility_of_money
    * route_distance_m
  + 0.05 * fare_baseline_hkd
```

The legacy `ride` `monetaryDistanceRate` is a MATSim monetary-distance term,
so it is multiplied by the effective global `marginalUtilityOfMoney`. The
config contains no explicit override; the adopted utility-design validation
retains the effective value `1.0`, which is recorded with its source in the
bridge validation JSON. The resulting leg scores are numerically unchanged
from the initial bridge. The custom taxi coefficient is already expressed in
`util/HKD` and is **not** multiplied by global `marginalUtilityOfMoney`.

The `0.05 util/HKD` taxi fare coefficient enters as a negative fare
disutility. Both scores use the same `-6 util/h` direct travel-time term, so
that term cancels in `asc_equivalent`; the bridge is driven by the legacy
`ride` constant and distance penalty relative to the new taxi fare penalty.

The observed `asc_equivalent` distribution is:

| Statistic | Utility |
|---|---:|
| Mean | -12.7502 |
| Median | -9.4925 |
| P10 | -29.6628 |
| P25 | -16.5005 |
| P75 | -4.8131 |
| P90 | -2.9552 |
| P95 | -2.1065 |
| Minimum | -73.6294 |
| Maximum | -0.0500 |

The correlation between `asc_equivalent` and route distance is `-0.99945`;
its correlation with the baseline fare is `-0.99149`. This confirms a very
wide, strongly distance-dependent distribution. A single ASC cannot preserve
the old `ride` utility for every leg.

Only `11.5352%` of legs have `asc_equivalent` inside the historical `[-3, 8]`
grid, while `88.4648%` fall below `-3` and none exceed `8`. The historical
grid therefore remains a diagnostic artifact rather than a first-test center.

The actual median lies within 0.5 util of `-9`, while `-12` is close to the
observed mean. The following values are retained only as provisional
technical candidates for a future smoke or coarse test:

```text
ASC = -12
ASC =  -9
ASC =  -6
```

Their empirical percentile ranks in the leg-level bridge distribution are
approximately 39.3%, 52.6%, and 69.3%, respectively. Their leg-level residual
diagnostics, where `residual = candidate_asc - asc_equivalent`, are:

| Provisional ASC | Mean absolute residual | Median absolute residual | RMSE |
|---:|---:|---:|---:|
| -12 | 7.8893 | 6.4527 | 10.7195 |
| -9 | 7.6293 | 5.0624 | 11.3317 |
| -6 | 8.2817 | 4.2011 | 12.6455 |

These large residuals reinforce that none is a calibrated ASC and that
distance-grouped diagnostics are necessary. No taxi mode or ASC mode-share
calibration is created or run by this bridge validation closure.

Bridge output directory:

```text
data/taxi/hongkong/processed/taxi_utility_bridge_v1/
```

Files:

- `old_ride_vs_new_taxi_leg_audit.parquet`: one row per base taxi passenger
  leg, with time, distance, fare, both score decompositions, and
  `asc_equivalent`.
- `old_ride_vs_new_taxi_summary.csv`: mean, median, P10, P25, P75, P90, and
  P95 for input quantities and utility components, plus range, correlation,
  and historical/current candidate-range coverage diagnostics.
- `taxi_asc_initial_candidates.csv`: the three provisional technical ASC
  values, unambiguous more-negative/center/less-negative labels, percentile
  ranks, offsets, and selection rationale.
- `old_ride_vs_new_taxi_grouped_summary.csv`: overall, taxi-type, fixed
  distance-bin, and fixed departure-period bridge summaries. Each independent
  grouping dimension sums to exactly 37,286 legs.
- `taxi_asc_candidate_residual_diagnostics.csv`: deduplicated residual
  diagnostics for the historical `-3` to `+8` grid, provisional
  `-12/-9/-6`, and the `floor(P10)`, `round(P50)`, and `ceil(P90)` anchors.
- `taxi_utility_bridge_validation.json`: formulas, parameters, hashes,
  actual error values, central utility-design cross-check, both Git-root
  protection checks, allowed-path audit, and required validation stop gates.

The script defaults to the current worktree root. It never silently falls back
to another checkout. Because the large protected MATSim inputs are absent from
this worktree, the read-only root must be supplied explicitly:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\costs\build_hong_kong_taxi_utility_bridge.py `
  --matsim-root F:\Matsim\matsim-example-project
```

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

The bridge correction additionally produced:

- exactly 37,286 unique base leg keys;
- no missing, non-finite, or negative distance/time/fare values;
- exact one-to-one agreement with the existing central
  `farecoef_0p05_share_1p0` utility-design rows;
- maximum equivalence, simplified-formula, and time-cancellation errors of
  `1.4211e-14`, `1.4211e-14`, and `0`, all below `1e-12`;
- overall, taxi-type, distance-bin, and departure-period grouped counts each
  sum to 37,286;
- unchanged SHA256 values for the source audits and protected plans, config,
  facilities, vehicles, and network;
- empty protected-path status before and after in both the current worktree
  and the explicitly supplied MATSim-root worktree;
- all required validation checks passed, with no changes outside the allowed
  bridge files;
- no changes to plans, config, network, facilities, vehicles, or Java, and no
  MATSim, QSim, Controler, smoke test, or mode-share calibration run.

This is a taxi behavioural pilot design, not an explicit taxi operating-fleet
model. Tunnel and waiting costs remain excluded until the next fare-model
version can identify reliable tunnel routes and waiting-time evidence. Do not
write HKD directly into MATSim scoring as `1 HKD = 1 util`.
