# Hong Kong taxi routed main-leg mapping audit v1

## Scope

This audit resolves the indexing question raised before taxi plans conversion:
MATSim routing expands some trips with stage activities and access/egress
legs, so `person_id + raw leg_sequence` is not generally a valid cross-file
identity. The audit establishes a main-trip mapping for the 37,286 base taxi
passenger legs and tests whether the existing fare and utility-bridge route
extraction was affected.

This stage is read-only with respect to existing plans, fare products, bridge
products, configs, networks, and Java code. It does not create a taxi mode,
convert plans, rebuild fares, change ASC candidates, or run MATSim.

## Inputs

The large MATSim inputs were supplied explicitly with:

```text
--matsim-root F:\Matsim\matsim-example-project
```

Plans:

```text
data/matsim_agents/hongkong/
  typical_weekday_5pct_v2_activity_modechoice/
    plans_unrouted_5pct_v2.xml.gz
    plans_routed_5pct_v2.xml.gz
    agent_trip_manifest_v2.parquet

data/matsim_agents/hongkong/typical_weekday_5pct_v1/
  agent_trip_manifest.parquet
```

Taxi inputs:

```text
data/taxi/hongkong/processed/taxi_initial_plan_allocation_v1/
data/taxi/hongkong/processed/taxi_fare_model_v1/
data/taxi/hongkong/processed/taxi_utility_bridge_v1/
```

The source plan hashes match the allocation, fare, and bridge validations:

| Input | SHA256 |
|---|---|
| `plans_unrouted_5pct_v2.xml.gz` | `5b463376f89bf607c0980d2e84e096f6424c76b6dc5697669aa1f9880de6a0f7` |
| `plans_routed_5pct_v2.xml.gz` | `c73ee48e792e7aebd55b7a2691664ae7f3f4f27d307aef2a6bf58263b3aaafea` |
| `agent_trip_manifest_v2.parquet` | `944fe88b0c0b8a4e2e981782805cdb292d903f113a4cf4588155a66315ca525f` |
| `agent_trip_manifest.parquet` | `1f332577994b188ad1022fc3398ec1c8ab40b99523ac9297a1fbfcfc66c77ddd` |

All source hashes remained unchanged during the audit.

## Routed expansion

The plans were rescanned from the gzip XML rather than accepting previously
reported counts:

| Metric | Unrouted | Routed | Difference |
|---|---:|---:|---:|
| Persons | 385,820 | 385,820 | 0 |
| Plans | 385,820 | 385,820 | 0 |
| Activities | 1,129,434 | 1,264,870 | +135,436 |
| Legs | 743,614 | 879,050 | +135,436 |
| Routes | 0 | 879,050 | +879,050 |
| `pt` legs | 557,104 | 557,104 | 0 |
| `walk` legs | 62,432 | 197,868 | +135,436 |
| `car` legs | 67,718 | 67,718 | 0 |
| `ride` legs | 56,360 | 56,360 | 0 |

The routed route-type inventory is:

| Route type | Count |
|---|---:|
| `generic` | 811,332 |
| `links` | 67,718 |

Both files contain exactly one plan for every person; there are no multi-plan
persons and no unresolved selected plans. The person sets are identical,
although their XML file order differs.

## Stage activity identification

The only routed-only activity type is:

| Stage activity type | Unrouted | Routed | Difference |
|---|---:|---:|---:|
| `car interaction` | 0 | 135,436 | +135,436 |

It is classified as a stage activity because it is routed-only, uses the
MATSim `interaction` naming convention, occurs inside routed trip groups, and
removing all occurrences restores every person's unrouted main-activity
signature sequence. No unknown routed-only activity type was found.

The 135,436 `car interaction` activities and 135,436 additional `walk` legs
come from car access/egress expansion. The example expectation of
`pt interaction` does not apply to these actual files.

## Main activities and main trips

A main activity is any activity present in the unrouted activity inventory.
`car interaction` is excluded as a stage activity. A main-activity identity
signature contains:

```text
type + facility + link + x + y
```

Coordinates are compared numerically, so serialization-only differences such
as `2466498.580` versus `2466498.58` are equal. Activity type, facility, link,
and order remain exact string comparisons.

After removing stage activities:

- person sets match exactly;
- all 385,820 main-activity signature sequences match;
- facility, link, and numeric coordinate identities match;
- no ambiguous stage structure remains.

For each person, `main_trip_index` is the zero-based ordinal between adjacent
main activities. The unrouted structure was verified to alternate:

```text
main activity -> leg -> main activity
```

for every person. Therefore `unrouted leg_sequence == main_trip_index` is
validated for this source, rather than assumed.

The routed plan is grouped between the same adjacent main-activity signatures.
The audit then requires exactly one `mode="ride"` leg inside the corresponding
routed main-trip group. It never selects a leg by similarity.

## Taxi key-set cross-check

The authoritative base taxi set is:

| Component | Unique legs |
|---|---:|
| V1 explicit taxi | 4,614 |
| Base allocated taxi | 32,672 |
| Total | 37,286 |

There is no overlap between explicit and allocated keys. Their union exactly
matches both:

- `taxi_leg_fare_estimates_base.parquet`;
- `old_ride_vs_new_taxi_leg_audit.parquet`.

All symmetric differences are zero, and all 37,286 matching v2 manifest legs
have source mode `ride`.

## Mapping result

| Result | Legs |
|---|---:|
| Selected taxi keys | 37,286 |
| Uniquely mapped main trips | 37,286 |
| Uniquely mapped ride legs | 37,286 |
| Ambiguous mappings | 0 |
| Missing mappings | 0 |

Although raw leg sequence cannot be treated as a general cross-file identity,
all 37,286 target taxi legs happen to retain the same raw sequence in these
specific routed plans. The person/main-trip validation proves this result; it
is not inferred from raw sequence alone.

## Existing route extraction impact

| Diagnostic | Matching legs | Share |
|---|---:|---:|
| Raw sequence | 37,286 | 100% |
| Old extracted routed mode is `ride` | 37,286 | 100% |
| Correct mapped mode is `ride` | 37,286 | 100% |
| Route distance | 37,286 | 100% |
| Travel time | 37,286 | 100% |
| Route attributes | 37,286 | 100% |
| Route text hash | 37,286 | 100% |

Distance and travel-time absolute differences are zero at the mean, median,
P10, P25, P75, P90, minimum, and maximum. The old extraction also reproduces
the existing fare parquet's distance and travel time for all 37,286 legs.

## Fare and utility-bridge impact

Corrected distance-only fares were recomputed in the audit directory using the
existing fare rules and taxi types. The existing unresolved rule was
reproduced exactly: an unresolved taxi retains that classification while its
meter-distance fare uses the urban-taxi rule.

| Fare diagnostic | Legs |
|---|---:|
| Corrected fare available | 37,286 |
| Fare unchanged | 37,286 |
| Fare changed | 0 |

Fare differences are zero for every statistic and for every taxi type,
distance band, and classification source.

The corrected ASC-equivalent distribution is unchanged:

| Statistic | Existing | Corrected | Difference |
|---|---:|---:|---:|
| Mean | -12.750181 | -12.750181 | 0 |
| Median | -9.492480 | -9.492480 | 0 |
| P10 | -29.662787 | -29.662787 | 0 |
| P25 | -16.500544 | -16.500544 | 0 |
| P75 | -4.813097 | -4.813097 | 0 |
| P90 | -2.955166 | -2.955166 | 0 |
| Minimum | -73.629401 | -73.629401 | 0 |
| Maximum | -0.050000 | -0.050000 | 0 |

The existing `-12/-9/-6` provisional candidates are not changed by this
audit.

## Outputs

Output directory:

```text
data/taxi/hongkong/processed/
  taxi_routed_main_leg_mapping_audit_v1/
```

Files:

- `routed_activity_type_inventory.csv`;
- `routed_plan_structure_summary.csv`;
- `taxi_unrouted_to_routed_main_leg_mapping.parquet`;
- `taxi_existing_route_extraction_impact.csv`;
- `taxi_routed_main_leg_mapping_validation.json`.

Output hashes, excluding the self-referential validation JSON:

| Output | SHA256 |
|---|---|
| `routed_activity_type_inventory.csv` | `fae2a5c6c3fc273f25b08703d21a361ecc33c583c41b75a9d5256a7baba8687e` |
| `routed_plan_structure_summary.csv` | `71bb9b5ccb27559fe8a0bfda0a7ab9ab262d7570b3582a3d717a9312143016ae` |
| `taxi_unrouted_to_routed_main_leg_mapping.parquet` | `760c2e613f35f03da132f3168770a6b2cac6c2edbc285775b1ce9c2ef7237ac5` |
| `taxi_existing_route_extraction_impact.csv` | `9c42196cbcdd3fa5272e4e99a764f3584ce6a1387f16c3b671b48f9bb603e27e` |

Reproduction command:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\demand_generation\audit_hong_kong_taxi_routed_main_leg_mapping.py `
  --matsim-root F:\Matsim\matsim-example-project
```

## Validation and downstream decision

The final status is:

```text
audit_completed
```

All audit execution checks pass. Input hashes and both Git roots' protected
status are unchanged and clean before and after. The validated conclusions
are:

```text
mapping_rule_valid = true
existing_fare_route_extraction_valid = true
existing_bridge_inputs_valid = true
downstream_action_required = false
```

The routed mapping issue does not require a fare or bridge rebuild. A future,
separately authorized plans-conversion stage may use
`person_id + main_trip_index` and the validated unique routed `ride` leg. This
audit itself does not convert plans and does not start Java custom scoring.

No existing plans, fare or bridge output, config, network, facility, vehicle,
Java file, or simulation output was modified. No MATSim routing, QSim,
Controler, smoke test, fare rebuild, bridge rebuild, or plans conversion was
run.
