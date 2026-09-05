# Hong Kong dynamic private-car cost runtime

## Status and scope

This Stage 11 extension replaces the fixed canonical-leg lookup only when
`--dynamic-car-costs` is explicitly enabled. It is a technical candidate and
does not replace the adopted 50-iteration Hong Kong production run. The
historical fixed-leg scorer remains available when the flag is absent.

The runtime prices three marginal private-car components:

1. route energy from every experienced or candidate network link;
2. mapped tolls from the facility rate applying at link-entry time;
3. destination parking from the experienced facility, arrival time, and the
   next entry of the same driving vehicle into traffic.

Fixed ownership cost remains excluded. Known motorcycle vehicle IDs remain
outside the private-car rule.

## Shared route rule

`HongKongDynamicCarCostRules` is the single source used by both routing and
experienced-event scoring. It reads the adopted base energy rate, mapped toll
links and typical-weekday toll intervals from
`data/transport_costs/hongkong/car_cost_v1/`.

For link `l` entered at time `t`:

```text
energy_hkd(l) = link_length_m / 1000 * 2.3260259843327398
toll_hkd(l,t) = mapped_facility_typical_weekday_rate(t), otherwise 0
```

The Car routing disutility adds
`(energy_hkd + toll_hkd) * marginalUtilityOfMoney` to MATSim's ordinary Car
time/distance disutility. The event scorer calls the same link function for
each actual `LinkEnterEvent` and subtracts the same monetary utility. The
standard Car `monetaryDistanceRate` must remain `0`, preventing a second
distance-money charge.

An arbitrary `NetworkRoute` quote uses its entered intermediate links plus
its end link and advances the clock with the supplied `TravelTime`. The start
link is excluded because the vehicle starts on it rather than generating a
`LinkEnterEvent`. Official whole-second inclusive toll intervals are treated
as continuous `[start, end + 1)` intervals, avoiding fractional-second gaps.

## Dynamic destination parking

The scorer opens a parking interval after an experienced Car arrival and the
corresponding non-interaction `ActivityStartEvent`. It records the actual
destination facility, link, activity type, driver, vehicle, and arrival time.
The interval closes when that same vehicle next enters traffic; its duration
is therefore the experienced vehicle dwell, not a prepared-leg duration.
Terminal parking closes at the configured QSim end time. Home remains zero
under the adopted separate-fixed-parking rule, while other activity/zone
groups retain the adopted hourly, part-hour, pass, minimum, and cap methods.

The separate unified real-facility candidate is documented in
`docs/HONG_KONG_PARKING_SUPPLY_2026.md`. It does not yet replace these rules.
Its official capacities and tariffs may be used only after facility
entrance/exit links have been direction-validated and routing selects the
same facility that experienced-event scoring later settles. Live vacancy is
time-varying state and is not a static capacity field.

The source feasibility table resolves 44,499 destination facilities. Another
47 facilities previously had no TCS zone. They are covered by
`data/transport_costs/hongkong/car_cost_v1/dynamic_runtime_v1/facility_tcs_zone_repairs.csv`.
Each repair is an exact point-within assignment using the adopted Census study
areas, 2021 DCCA geometry, and the existing student-school TCS classifier; no
nearest-zone or default-zone fallback is allowed. At startup, the repair set
must exactly equal the unresolved facility set.

The all-household joint-plan technical gate expands the potential full-day
driver-switch destination universe to 4,007 facilities. Its v3 companion table
contains 1,266 exact facility-zone rows: 47 baseline repairs plus 1,219 new
point-within assignments. Ten border facilities remain explicitly unresolved;
no candidate depending on an unpriced default/nearest zone is admitted. The
table is scoped to that pilot and does not replace the baseline production
repair table.

## Activation and failure policy

`RunHongKong5Pct` accepts `--dynamic-car-costs` only together with
`--multimodal-costs`, `--pt-fare-root`, and `--car-cost-root`. A household
`JointReRoute` plus multimodal costs is rejected unless the dynamic Car flag is
present, because the historical static tables cannot price changed routes.

The loader checks semantics rather than comparing stepwise input/output
hashes: required files and columns must parse, mapped links must exist,
facilities and vehicle classes must be unambiguous, toll mappings must have
rates, and all unresolved parking facilities must have exact spatial repairs.

## One-cycle validation

The server validation at
`/mnt/DiskM/by/hk_stage11_dynamic_car_joint_reroute_20260806_run4` completed
QSim iterations 0 and 1 with exit code `0`. After iteration 0, the fixed 139
household school-escort pairs underwent exactly one `JointReRoute`: 202 of 278
driver legs changed link sequence and 76 were unchanged, with zero binding
identity failures.

Dynamic cost summaries were positive in both iterations:

| Iteration | Link entries | Toll entries | Energy HKD | Toll HKD | Settled nonterminal parking events | Parking HKD | Facility mismatches |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 5,853,771 | 26,399 | 1,930,756.35 | 663,597 | 37,109 | 2,184,806 | 0 |
| 1 | 5,812,513 | 26,034 | 1,919,551.76 | 655,622 | 36,791 | 2,183,060 | 0 |

The final event audit classified all 278 bound legs: 273 completed, one
passenger became stuck while onboard, and four drivers became stuck before
pickup. No bound leg teleported. All 385,820 final plan scores were finite,
and selected mode counts remained Car 67,718, Car passenger 2,734, PT 557,347,
school bus 9,626, Taxi 44,000, and walk 199,811.

The run-level `AfterMobsim` parking summary is emitted before person scorers
finish, so its table reports parking intervals closed by a subsequent vehicle
departure. Terminal intervals are still settled into final person scores at
QSim end but are not included in that log summary.

The auditable local report is
`data/taxi/hongkong/processed/taxi_44000_no_ride_student_swap_v1/school_escort_physical_pilot_v1/school_escort_dynamic_car_joint_reroute_1cycle_20260806_success.json`.
Ordinary ReRoute, mode-choice, and time-allocation innovation remained frozen;
this validates cost-aware route innovation for the fixed binding pilot, not
general household joint-plan selection or long-run equilibrium.
