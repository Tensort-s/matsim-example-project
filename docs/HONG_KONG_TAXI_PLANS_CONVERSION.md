# Hong Kong taxi base plans conversion v1

> Historical base conversion. This v1 artifact intentionally retained
> `routingMode=ride`. The adopted next-stage derivative and independent Taxi
> router are documented in
> [HONG_KONG_TAXI_NATIVE_ROUTING.md](HONG_KONG_TAXI_NATIVE_ROUTING.md).

## Scope

This stage creates a new, non-overwriting routed plans derivative for the Hong
Kong taxi behavioural pilot. It uses the validated routed main-trip mapping to
change exactly 37,286 base passenger legs from `ride` to `taxi` and writes the
existing distance-only fare as typed leg metadata.

This is a plans metadata conversion only. It does not create or run a MATSim
configuration, add custom scoring, choose an ASC, route plans, simulate a
fleet, or run MATSim.

## Read-only inputs

The large source plans are read through an explicit data root:

```text
--matsim-root F:\Matsim\matsim-example-project
```

The conversion uses:

```text
data/matsim_agents/hongkong/
  typical_weekday_5pct_v2_activity_modechoice/
    plans_routed_5pct_v2.xml.gz
    plans_unrouted_5pct_v2.xml.gz

data/taxi/hongkong/processed/
  taxi_routed_main_leg_mapping_audit_v1/
  taxi_fare_model_v1/
  taxi_initial_plan_allocation_v1/
  taxi_utility_bridge_v1/
```

The routed mapping must already report 37,286 unique `ride` legs, no ambiguous
or missing mappings, valid fare/bridge route extraction, and no downstream
rebuild requirement. The unrouted file is rescanned to cross-check each target
main-trip index and both main-activity signatures.

## Target definition

The base target is:

| Component | Legs |
|---|---:|
| V1 explicit taxi | 4,614 |
| Base allocated taxi | 32,672 |
| Total converted | 37,286 |

The conversion excludes private-car passenger, school-bus, base
`other_ride`, low-only, and high-only selections. A routed target is accepted
only when its person, main-trip index, mapped routed raw leg sequence, origin
main-activity signature, and destination main-activity signature all agree.

## Written leg fields

For every accepted target:

```text
mode: ride -> taxi
```

The existing leg attributes, including `routingMode=ride`, remain unchanged
in this historical v1 artifact. This is not the current native-routing
contract.
The following typed attributes are appended:

| Name | Java class | Value |
|---|---|---|
| `hkTaxiFareBaselineHkd` | `java.lang.Double` | Exact base distance-only fare |
| `hkTaxiType` | `java.lang.String` | Existing taxi type, including `unresolved` |
| `hkTaxiFareScope` | `java.lang.String` | `distance_only_v1` |
| `hkTaxiFareModelVersion` | `java.lang.String` | `hong_kong_taxi_fare_model_v1` |
| `hkTaxiClassificationSource` | `java.lang.String` | Existing classification source |
| `hkTaxiMainTripIndex` | `java.lang.Integer` | Validated main-trip index |

No ASC, fare utility, utility coefficient, fare-share factor, legacy ride
score, marginal utility of money, or other scoring-layer value is written to
plans.

## Output placement

The repository's existing `.gitignore` excludes `/data/matsim_agents/`, and
the routed source plans are approximately 80.7 MB compressed. In accordance
with the large-derived-file rule, the new plans are written outside both Git
worktrees to the explicit new path:

```text
F:\Matsim\derived\hongkong\taxi_behavioral_pilot_v1\
  plans_routed_5pct_taxi_base.xml.gz
```

The file is first written to a temporary sibling, fully reread and validated,
and then atomically moved to the final path. The audit JSON records its
absolute path, byte size, and SHA256. The plans file itself is not pushed.
Git LFS is not enabled, and `.gitignore` and `.gitattributes` are not changed.

Repository audit outputs:

```text
data/taxi/hongkong/processed/taxi_plans_conversion_v1/
  taxi_plans_conversion_leg_audit.csv
  taxi_plans_conversion_mode_summary.csv
  taxi_plans_conversion_validation.json
```

## Validation

The output is completely reparsed. Ordered route-attribute and route-text
hashes cover all 879,050 routes; normalized activity signatures cover all
1,264,870 activities. A whole-population normalized structure hash restores
the 37,286 target output modes to `ride` and removes only the six newly
authorized taxi attributes before comparison, so any other change to persons,
plans, activities, legs, times, routes, attributes, stages, or order fails the
conversion.

The validation status is computed from `all(required_checks.values())`.
`validated` is written only when every check passes; otherwise the script
writes `failed`, lists the failed checks, and exits nonzero.

The completed base conversion has:

| Metric | Result |
|---|---:|
| Target / converted | 37,286 / 37,286 |
| Missing / duplicate / unexpected | 0 / 0 / 0 |
| Explicit / base allocated | 4,614 / 32,672 |
| Unique taxi persons / tours | 15,439 / 15,485 |
| Urban / New Territories / Lantau / unresolved | 31,037 / 3,654 / 62 / 2,533 |
| Fare mean / median | 109.865609 / 98.3 HKD |
| Fare P10 / P90 | 29.0 / 222.5 HKD |
| Fare minimum / maximum | 24.0 / 491.7 HKD |

Before conversion the routed modes are `car=67,718`, `pt=557,104`,
`ride=56,360`, `walk=197,868`, and `taxi=0`. Afterwards they are
`car=67,718`, `pt=557,104`, `ride=19,074`, `taxi=37,286`, and
`walk=197,868`.

Persons, plans, activities, legs, and routes remain respectively 385,820,
385,820, 1,264,870, 879,050, and 879,050. Route-attribute, route-text, and
activity-signature mismatch counts are all zero, and the normalized complete
plans structure matches.

The derived plans artifact is:

```text
size:   82,100,567 bytes
SHA256: f4631ab00c6f5027160314f7357e32d969b7588192008c17ac79bf0b3208ce27
```

## Reproduction command

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\demand_generation\convert_hong_kong_taxi_behavioral_plans.py `
  --matsim-root F:\Matsim\matsim-example-project `
  --output-plans F:\Matsim\derived\hongkong\taxi_behavioral_pilot_v1\plans_routed_5pct_taxi_base.xml.gz
```

The command does not invoke MATSim, QSim, routing, custom Java scoring, an ASC
test, or fleet simulation.
