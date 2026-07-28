# Hong Kong taxi scenario load test v1

This document defines the server-side load gate for the Hong Kong taxi
behavioural pilot. The gate has one purpose: prove that the real routed taxi
base plans load with the complete MATSim 2026.0 Hong Kong network, public
transport, facilities, and private vehicles, and that their taxi metadata can
be consumed by the custom fare scorer.

This is not a smoke simulation. The audit never creates a MATSim `Controler`,
QSim, router run, iteration, taxi fleet, or ASC calibration.

## Audit entry point

The read-only Java entry point is:

```text
org.matsim.project.hongkong.taxi.HongKongTaxiScenarioLoadAudit
```

It accepts exactly four positional arguments:

```text
<base-config> <taxi-plans> <validation-json> <checkpoint-sha>
```

The program loads the base config with `ConfigUtils.loadConfig`, changes only
the in-memory plans input and taxi scoring mode, and calls
`ScenarioUtils.loadScenario(config)`. It does not write a config or any
scenario input back to disk.

The in-memory taxi scoring parameters are:

| Parameter | Value |
|---|---:|
| constant | -9 |
| marginal utility of travelling | -6 util/h |
| marginal utility of distance | 0 |
| monetary distance rate | 0 |
| daily monetary constant | 0 |
| daily utility constant | 0 |

All pre-existing non-taxi scoring modes are snapshotted before and after this
override and must remain bit-for-bit equal at the Java `double` value level.

## Inputs and protection boundary

The taxi plans input is:

```text
plans_routed_5pct_taxi_base.xml.gz
```

Its required SHA256 is:

```text
f4631ab00c6f5027160314f7357e32d969b7588192008c17ac79bf0b3208ce27
```

The load uses the complete formal Hong Kong network, transit schedule,
transit vehicles, activity facilities, and private vehicles referenced by the
server base config. The audit records path, byte size, and SHA256 for the base
config and all six scenario inputs before loading and after all checks. Every
snapshot must remain identical.

The formal scenario at
`/mnt/DiskM/by/hk_matsim_5pct_ptfixed_ferry_activity_v1` is a read-only input.
Every new repository checkout, uploaded plans file, log, and result must be
created under a new directory below:

```text
/mnt/DiskM/by/hk_taxi_behavioral_pilot_v1/
```

No work for this gate may use `/home/by/OD/HK`, overwrite an earlier attempt,
or delete server files.

## Required loaded-plan checks

The gate requires these exact loaded totals:

| Item | Expected |
|---|---:|
| persons | 385,820 |
| plans | 385,820 |
| activities | 1,264,870 |
| legs | 879,050 |
| routes | 879,050 |
| taxi legs | 37,286 |
| persons with taxi legs | 15,439 |

The mode totals must be `car=67,718`, `pt=557,104`, `ride=19,074`,
`taxi=37,286`, and `walk=197,868`.

Every taxi leg is passed independently through
`HongKongTaxiLegAttributes.readAndValidate` and
`HongKongTaxiFareScoring.handleLeg`. The six runtime types must be exactly one
`Double`, four `String` values, and one `Integer` with no missing, null,
invalid, or misplaced taxi attributes. Taxi type and classification-source
counts must match the conversion audit.

Every taxi route must exist, have a finite non-negative distance, and have a
defined finite non-negative route travel time. Its `routingMode` must be
`ride`; no other taxi routing mode is accepted.

The baseline fare distribution must have mean `109.86560907579253`, median
`98.3`, P10 `29.0`, P90 `222.5`, minimum `24.0`, and maximum `491.7` HKD.
The summed fare-only score must equal `-0.05 * summed fare` within the recorded
floating-point tolerance.

After loading, the audit constructs
`HongKongTaxiScoringParameters.centralV1()` and a
`HongKongTaxiScoringFunctionFactory`, then creates a scoring function for one
real taxi person and one real non-taxi person. It does not invoke either
scoring lifecycle.

## Server execution gate

Before execution, the remote host must pass hostname, Java, Maven, free disk,
free memory, formal-directory, and required-input checks. The repository must
then be checked out at the exact pushed audit checkpoint. The permitted remote
operations are compile/package, the exact taxi unit-test set, and this load
audit.

The validation JSON is accepted only when every required check is `true`,
`failed_checks` is empty, all input hashes are stable, the process exits zero,
and no `output_events`, `output_plans`, `output_config`, iteration, QSim, or
simulation-output artifact exists.

## Validated server result

Taxi scenario load test v1 was validated on `FUSELAB01` at checkpoint
`fdc36b262d074be128afe35a857ddb0d113ff328`. The isolated server directory was:

```text
/mnt/DiskM/by/hk_taxi_behavioral_pilot_v1/load_test_v1_fdc36b2
```

The server used Eclipse Adoptium Java `25.0.3`, Apache Maven `3.9.16`, and
MATSim `2026.0`. Remote compile and package both exited zero. The four exact
Taxi test classes ran 35 tests with zero failures, errors, or skips.

The pure scenario load used `-Xms8g -Xmx32g`. The audit process exited zero,
the `ScenarioUtils.loadScenario` portion took `27.386192079` seconds, and the
complete audit took `30.566009109` seconds. The external wall-clock
measurement was `31.54` seconds with peak resident memory `5,703,712` KiB.

All required structure and mode totals matched. The loaded population contained
385,820 persons, 385,820 plans, 1,264,870 activities, 879,050 legs, and
879,050 routes. It contained 37,286 Taxi legs across 15,439 persons. All six
Taxi attribute runtime types and all Taxi type, classification-source, route,
and `routingMode=ride` counts matched the adopted expectations. Every missing,
invalid, duplicate, misplaced, or malformed counter was zero.

The observed fare sum was `4,096,449.10000013` HKD and the fare-only score sum
was `-204,822.455000014`, matching `-0.05 * fare sum` within floating-point
tolerance. The scoring factory was constructed successfully and created
scoring functions for one real Taxi person and one real non-Taxi person
without running a scoring lifecycle.

All seven input size/SHA256 snapshots were unchanged before and after the
audit. The repository and result-directory scans found no events, output
plans, output config, iteration, QSim, or simulation-output artifact. No
Controler, QSim, routing, smoke simulation, ASC experiment, or fleet
simulation was run.

The adopted validation record is:

```text
data/taxi/hongkong/processed/taxi_scenario_load_test_v1/taxi_scenario_load_validation.json
```

It records `status=validated`, `all_checks_passed=true`, an empty
`failed_checks` list, and all six required no-run flags as `false`.
