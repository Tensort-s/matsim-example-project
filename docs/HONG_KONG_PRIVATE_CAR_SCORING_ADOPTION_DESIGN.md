# Hong Kong private-car MATSim scoring adoption design v1

> Historical Stage 3 design evidence. Stage 8A supersedes its blanket
> runtime-blocked conclusion only for hash-locked base energy, and Stage 8B
> separately supersedes it only for hash-locked confirmed base toll. Exact
> person/leg, route-distance, fingerprint, ordinal, physical facility-link,
> and zero-standard-distance-rate guards replace the unguarded lookup risk.
> The historical findings remain controlling for destination parking, fixed
> ownership, motorcycles, arbitrary iterations, and any ambiguous, inferred,
> unresolved, unguarded, or parallel interface. See
> `docs/HONG_KONG_CAR_ENERGY_RUNTIME.md` and
> `docs/HONG_KONG_CAR_TOLL_RUNTIME.md`.

## Decision

This is a **design candidate for review**, not a scoring implementation or an
adoption approval. The audit is built from locked commit
`ee8187222dff0af1682255d9edb07994761183aa`.

The result is:

```text
design_candidate = true
blocked = true
matsim_scoring_modified = false
scoring_implementation_approved = false
scoring_adoption_approved = false
joint_mode_choice_calibration_approved = false
car_monetaryDistanceRate_modified = false
marginalUtilityOfMoney_modified = false
fixed_vehicle_ownership_behavioral_inclusion = false
runtime_static_leg_cost_lookup_approved = false
baseline_replay_only = true
```

No MATSim config, Java scoring module, plan, network, facility, vehicle, or
simulation output was changed. No `PersonMoneyEvent` was generated and MATSim
was not run.

The design is blocked because the current distance-money currency and economic
meaning are not documented, the structurally preferred design is not currently
authorized, 835 parking events remain unresolved and non-random, no runtime
module exists, and the required baseline replay has not passed.

## Audited inputs

The design uses only:

- the current production config and `RunHongKong5Pct`;
- MATSim 2026.0 scoring and event contracts;
- `unified_marginal_cost_interface_v1`;
- `energy_application_v1`;
- `toll_network_mapping_v1`;
- `toll_rate_application_v1`;
- `parking_event_application_v1`;
- the fixed-ownership candidate solely to verify permanent behavioral
  exclusion.

The historical top-level
`car_leg_cost_estimates_<scenario>.parquet` files are not design inputs.

Canonical plans, config, network, facilities, vehicles, transit supply,
`src/main/java`, `pom.xml`, the five cost candidates, and selected Taxi/PT core
files were SHA256-frozen before and after the audit. All hashes were unchanged.
Full repository-relative paths and values are in
`scoring_adoption_design_input_hashes.json`. The canonical read-only project
root is deliberately omitted from outputs.

## Current effective scoring

Values below come from the actual production config. Parameters absent from
the config use the audited MATSim 2026.0 `ScoringConfigGroup` effective
defaults.

| Parameter | Effective value | Source |
| --- | ---: | --- |
| car constant | -0.5 util/trip | explicit config |
| car marginal utility of traveling | -6 util/h | explicit config |
| car monetary distance rate | -0.0007 currency/m | explicit config |
| marginal utility of money | +1.0 util/currency | MATSim 2026.0 default |
| performing utility | +6 util/h | MATSim 2026.0 default |
| ordinary waiting utility | -0.0 util/h | MATSim 2026.0 default |
| PT waiting utility | -6 util/h | fallback to configured PT travel utility |
| late arrival utility | -18 util/h | MATSim 2026.0 default |
| early departure utility | -0.0 util/h | MATSim 2026.0 default |
| utility of line switch | -1 util/switch | MATSim 2026.0 default |

The distance term is applied by
`CharyparNagelLegScoring.calcTravelDistScore`:

```text
route.distance_m
  × monetaryDistanceRate_currency_per_m
  × marginalUtilityOfMoney_util_per_currency
```

The distance source is `experiencedLeg.getRoute().getDistance()`. It is not a
manifest lookup and it is not a money event. A NaN route distance fails fast.

The existing distance rate therefore implies:

```text
0.7 currency/km
-0.7 util/km
```

Across 64,789 private-car legs it has a mean absolute value of
10.878 currency/leg and a mean utility contribution of -10.878 util/leg.

### Currency and economic meaning

The positive sign and value of `marginalUtilityOfMoney` are confirmed. The
currency itself is not: the config has no HKD declaration and no provenance
showing that `monetaryDistanceRate` represents fuel rather than another
variable cost or a calibrated generalized-cost proxy.

Consequently:

- the existing value must be called `currency/km`, not `HKD/km`;
- `existing_distance_money_hkd_per_km` is null;
- direct subtraction from audited HKD energy is not authorized;
- the design is mandatorily blocked.

The audited representative energy rates are 1.648390, 2.326026, and 3.540398
HKD/km for low, base, and high. If, counterfactually, the existing currency
were proven to be HKD with compatible distance and economic semantics, it
would be below all three energy rates by 0.948390, 1.626026, and 2.840398
HKD/km. This counterfactual is not a finding that the old rate is fuel.

### Car and motorcycle

All 2,929 motorcycles also use MATSim mode `car`. They therefore share the
current car mode scoring parameters, including the existing distance term.
Every future private-car event component must filter on vehicle class;
motorcycle private-car cost event count must be zero.

### Existing money events

The production config activates no road-pricing, toll, or parking module.
`RunHongKong5Pct` adds SwissRailRaptor and, only without `--simulate`, a no-op
Mobsim. The repository Java source contains no private-car `PersonMoneyEvent`,
`LinkEnterEvent` toll handler, parking handler, or custom car scoring module.
The road-pricing dependency exists in `pom.xml` but is not activated.

There is no production event log at the configured output path, so empirical
event-type confirmation is deferred to the future replay. Structurally, no
current private-car monetary-event emitter is configured.

## Double-counting alternatives

All totals in this section use the 63,954 complete private-car legs.
Because the current currency is unverified, totals involving the 0.7
currency/km term are explicitly counterfactual “if currency is compatible
HKD,” not adopted HKD totals.

| Design | Energy treatment | Config change | Runtime events feasible | Current authorization | Decision |
| --- | --- | --- | --- | --- | --- |
| A | retain old distance term; add toll and parking only | no | yes | no implementation approval | reject |
| B | retain old term; add audited energy minus old term | no | yes | no implementation approval | reject until semantics verified |
| C | add full energy, toll, parking; neutralize old term | yes | yes | explicitly unauthorized | future structural recommendation only |

### A: old distance term plus toll and parking

This does not explicitly add energy twice, but it silently treats an
undocumented 0.7 currency/km term as a substitute for audited energy. If the
currency and meaning were compatible, it would understate every positive
energy rate. If they are not compatible, the direction of bias is unknown.

### B: residual energy

The formula would be:

```text
residual_energy =
  audited_energy - existing_distance_money
```

It algebraically avoids duplication only if currency, distance convention,
and economic meaning are compatible. They are not currently verified.
`max(0, residual)` is not used and is prohibited. B remains rejected.

### C: full dynamic marginal costs and a neutralized old distance term

C is the cleanest future structure: experienced energy, toll, and parking
would be charged once, while the existing distance-money component would be
neutralized. Current instructions prohibit changing
`car monetaryDistanceRate`; therefore C is not authorized and was not
implemented.

Counterfactual complete-leg totals are:

| Scenario | A if old currency were compatible HKD | B if fully compatible | C after authorized neutralization |
| --- | ---: | ---: | ---: |
| low | 2,246,360.70 | 3,178,496.28 | 3,178,496.28 |
| base | 4,050,634.70 | 5,648,792.21 | 5,648,792.21 |
| high | 4,806,637.70 | 7,598,354.11 | 7,598,354.11 |

Keeping the old term and also adding full energy would add 688,002.70
currency over the complete set if currencies were comparable. That
unrequested fourth variant is an explicit double-charge and is rejected.

## Unique recommendation

Adopt no scoring scheme now. Keep scoring adoption blocked.

After the currency and economic meaning are documented, all 835 parking
records are repaired, the runtime design is separately approved, and the
baseline replay passes, seek explicit authorization for dynamic design C and
then perform a separately approved joint calibration. A and B should not be
used as shortcuts.

## Why the static interface cannot be an iteration lookup

The unified offline interface is:

- the audit truth for the baseline selected routed plan;
- an oracle for a future deterministic replay;
- not a static price table for arbitrary MATSim iterations.

Current replanning includes `ChangeExpBeta`, `ReRoute`,
`SubtourModeChoice`, and `TimeAllocationMutator` through iteration 40.

| Operation | Static identity risk |
| --- | --- |
| ReRoute | distance, link sequence, facilities passed, and passage times change |
| TimeAllocationMutator | departure, toll rate interval, and parking duration change |
| SubtourModeChoice | car can become PT and PT can become car |
| plan copying | the same person can have several plans with no persistent leg ID |
| selected-plan switching | a different copied or mutated plan may execute |
| experienced-plan creation | event-reconstructed legs are the scoring truth |
| stage activity insertion | PT routing can change leg count and order |
| car to PT | static lookup would falsely charge the old car leg |
| PT to car | the new car leg has no original static row |

`person_id + leg_sequence` is therefore not a persistent runtime charging key.
The current strategies do not relocate main activity destinations, and the
person-to-vehicle attribute remains assigned, but neither fact makes old
leg-level prices valid after mode, route, or time changes.

## Future experienced-event contracts

These contracts are design only. No Java implementation exists.

### Energy

Open a private-car traffic session at `VehicleEntersTrafficEvent`, accumulate
actual routed distance from experienced link passages with an explicit
start/end-link convention, and settle once at
`VehicleLeavesTrafficEvent` or the experienced car-leg end.

The charge belongs to the experienced driver. An original car leg changed to
PT produces no energy charge; a new PT-to-car leg is charged from its actual
vehicle session. Motorcycles are filtered out. No energy implementation may
proceed until the distance-money conflict is resolved.

### Toll

Use `VehicleEntersTrafficEvent` to bind vehicle, session, and active driver.
Use `LinkEnterEvent` as the physical charge trigger:

- charge only when an experienced vehicle enters mapped toll links;
- select the rate using actual passage time;
- normalize official features to a canonical facility;
- charge one physical facility passage once;
- treat WHC primary and backup aliases as one passage;
- charge distinct facilities separately;
- follow the experienced route automatically;
- never infer a facility from “cross-harbour” geography;
- never use taxi passenger tunnel surcharges.

The deduplication key is vehicle, traffic session, canonical facility, and
physical passage cluster. `PersonLeavesVehicleEvent` is suitable for cleanup,
not as the toll trigger.

### Destination parking

Use one vehicle state machine:

1. on `VehicleLeavesTrafficEvent` plus arrival/activity evidence, open one
   parking event and save arriving person, time, link/facility, and activity;
2. wait for the next `VehicleEntersTrafficEvent` of the same vehicle;
3. verify chronology and facility consistency;
4. calculate experienced duration and close the event once;
5. charge the saved arriving person, not automatically the next driver.

Charging at arrival is rejected because duration is unknown. Charging all
events at Mobsim end is rejected because it increases state and attribution
risk. The recommended rule is settlement at the same vehicle's next departure.
Mobsim-end settlement is reserved for still-open terminal events under an
explicitly approved terminal non-home and cross-midnight rule.

Home temporary parking remains marginal zero with fixed costs separate. Work
prepaid subscription is zero only in its explicit scenario. Time overlap,
facility mismatch, or missing duration must fail fast, never become zero.

### Fixed ownership

The invariant is permanent for the current daily decision horizon:

```text
runtime scoring events = 0
leg scoring records = 0
PersonMoneyEvent records = 0
behavioral utility contribution = 0
```

The fixed-cost candidate remains an accounting sidecar only.

## Bias in the 835 unresolved parking legs

The 835 records belong to 602 persons, 602 vehicles, and 600 households.

| Reason | Legs |
| --- | ---: |
| vehicle time overlap | 466 |
| next-departure facility mismatch | 269 |
| missing destination zone | 98 |
| terminal non-home missing next departure | 2 |

The missingness is not approximately random:

- education has 46 unresolved of 278 private-car legs, or 16.55%;
- work is 2.04%, home 1.62%, leisure 0.56%, shopping 0.53%, and
  medical/personal business 0.40%;
- over-40-km legs are unresolved at 7.21%, compared with 0.39% for
  0–5 km;
- unresolved mean distance is 28.64 km versus 15.37 km for complete legs;
- unresolved base energy averages HKD 66.63 versus HKD 35.75;
- toll-charge share is 47.66% versus 39.81%.

Activity, distance-band, and energy-distribution tests reject equal
distributions with p-values below `2e-109`. Complete-case mode-choice scoring
would therefore systematically omit longer, higher-energy, activity-
concentrated legs.

The evidence review identifies 133 potential repair candidates: 98 missing-zone
records that may admit a unique facility-coordinate/TCS spatial join and 35
facility mismatches whose existing zone evidence merits physical-site review.
They are not treated as repaired. The other 702 require new evidence or an
explicit modeling rule. Time overlaps cannot be silently reordered, facility
IDs cannot be equated from zone alone, and terminal durations cannot be
invented.

### Required unresolved policy

The unique policy is:

- formal scoring adoption remains blocked until all 835 are resolved under an
  approved evidence/rule contract;
- complete-case execution is allowed only as a technical replay and must not
  affect mode choice;
- sourced stratified or bounded low/base/high missing-cost designs may be
  researched separately but are not adopted here;
- any unresolved physical event in a future runtime module fails fast;
- zero filling is forbidden.

## Baseline replay acceptance

A future implementation must first run iteration 0 with replanning disabled
and the current selected routed plan frozen. The static Parquet interface is
used only as the oracle.

Required counts include:

- 64,789 experienced private-car legs and energy alignments;
- 33 legal zero-distance energy legs;
- 30,837 base toll passage events across 25,858 charged legs;
- 38,931 confirmed no-charge toll legs;
- 64,789 physical parking events;
- 63,954 complete and 835 incomplete parking events;
- zero motorcycle private-car cost events;
- zero fixed-cost runtime, leg-scoring, and money events.

Facility multisets must match exactly, WHC alias duplicates must be zero,
parking keys must be unique, statuses and legal zeros must match, and fixed
cost must remain absent.

Numeric acceptance is:

- energy max absolute error: `1e-6 HKD`;
- toll error within the same official rate interval: `1e-9 HKD`;
- parking error within the same billing bucket: `1e-9 HKD`;
- complete-leg total under identical semantic inputs: `1e-6 HKD`;
- unexplained component or total error: exactly zero.

Experienced congestion may move toll passage time across an official interval
or parking duration across a billing boundary. Raw maximum error must still be
reported. A non-zero difference is acceptable only when exact event-time and
official-rule evidence explains it; the runtime implementation must never
force the static base amount.

## Outputs and reproduction

The design output directory is:

```text
data/transport_costs/hongkong/car_cost_v1/scoring_adoption_design_v1/
```

It contains the ten required inventory, comparison, event-contract, replanning,
unresolved-bias, replay, validation, repair, and input-hash artifacts.

The audit builder is:

```text
scripts/hong_kong_single_city/costs/car/
  audit_hong_kong_car_scoring_adoption_design.py
```

Run from this worktree:

```powershell
& "F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe" -B `
  "scripts\hong_kong_single_city\costs\car\audit_hong_kong_car_scoring_adoption_design.py" `
  --input-project-root "F:\Matsim\matsim-example-project"
```

The script writes repository-relative provenance only. Passing the canonical
root is a local execution detail and is not persisted.

## Required repairs

Nine blocking repairs cover:

1. explicit currency semantics;
2. economic meaning of the existing distance-money rate;
3. separate authorization for a neutralized-distance design;
4. all 835 parking gaps;
5. reviewed experienced-event implementation;
6. a passed baseline replay;
7. planned-versus-experienced time boundary reconciliation;
8. strict motorcycle filtering;
9. a terminal non-home parking rule.

The missing empirical event log is a tenth, non-blocking design-audit finding
that becomes an assertion in the future replay.

Until those conditions are resolved, this artifact remains a valid blocked
design candidate and nothing more.
