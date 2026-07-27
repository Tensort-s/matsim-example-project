# Hong Kong 5% MATSim agents and plans

## Scope

The active multi-activity population is
`typical_weekday_5pct_v2_activity_modechoice`. It preserves the calibrated
work, school, escort, and border activities from `typical_weekday_5pct_v1`,
then adds resident shopping, dining, leisure, social, medical, and personal
business tours. The v1 directory remains an immutable compulsory-trip
baseline.

The active output is:

```text
data/matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice/
```

The resident control is the fixed-link calibrated WorldPop total of 7,352,309.
The sample contains exactly 367,615 residents: 363,275 whole-household members
and 4,340 collective/non-household residents. External demand adds 14,735
visitor-day agents and 3,470 Mainland-resident Hong Kong agents, for 385,820
agents in total. Each agent has an expansion weight of 20.

## V2 discretionary demand and mode choice

TCS 2022 reports 12,363,000 mechanized resident trips on a weekday. At 5% this
is 618,150 trips. The retained v1 internal compulsory plans contain 354,362
mechanized legs after excluding usual-resident border movements, so v2 adds
263,788 rather than stacking the complete HBO and NHB controls on top of the
existing demand.

The residual is split in the TCS ratio into 222,302 HBO legs and 41,486 NHB+EB
legs. This produces 111,151 resident discretionary tours:

- 69,665 `home -> activity -> home` tours;
- 41,486 `home -> activity -> activity -> home` tours.

TCS Appendix A.2 controls the 26-zone home-end and activity-end margins.
Integrated iGeoCom+OSM POIs provide exact destinations. HBO production WAPE is
zero, HBO attraction WAPE is below 0.005%, and feasible NHB production and
attraction margins match exactly. A 170-trip inconsistency in SENT is shifted
and recorded because that zone's scaled NHB endpoints exceed its available HBO
activity endpoints under the two-stop representation.

The initial discretionary-leg mode shares use Appendix A.3 HBO boardings:
`pt=71.34%`, `car=18.80%`, and `ride=9.86%`. All initial car tours have a
designated household driver and explicit vehicle. The formal config enables:

- `SubtourModeChoice` for `car,pt,walk,ride`;
- `car` as a chain-based mode;
- `considerCarAvailability=true`;
- `TimeAllocationMutator` with a 30-minute range;
- `ReRoute`, with innovation disabled after iteration 40.

Workers and students receive mainly evening/after-school tours. `home_only`,
`work_home`, and older residents receive daytime tours and make up the majority
of added activity participants. Activity purpose shares are transparent
role/age priors because the published TCS provides total HBO/NHB controls, not
a complete resident purpose split.

## Demand construction

- Whole households are balanced by DCCA, household size, vehicle ownership,
  income, and housing type. Household membership and vehicle relationships are
  retained.
- Home coordinates are sampled from positive calibrated WorldPop raster cells
  inside each grid. Collective residents use the residual between WorldPop and
  synthetic household population.
- Fixed-work destinations use `generation_hk_census_projected.npy`. Sampling is
  integerized hierarchically: origin-grid totals, 18 destination districts,
  then destination grids. This avoids district-share distortion from directly
  rounding a sparse 1,585 by 1,585 matrix.
- Census Table 7.9 controls commute modes. Walk commuters are restored to the
  home grid while an equal amount is removed from the same destination
  district, preserving district OD totals.
- Day-school students use the DCCA-constrained EDB school assignment and actual
  school coordinates. Tertiary students use the residual full-time-student
  controls and education POIs.
- Private-car work trips are assigned preferentially to designated household
  drivers. School escort chains are retained only when the driver has an
  explicit private vehicle.
- Hong Kong usual-resident border events replace the resident's ordinary plan.
  Visitor and Mainland-resident chains come from the PT-accessibility V2 border
  model and remain separate from the resident population control.

The unrouted plans contain 479,826 main legs. MATSim routing expands PT access,
egress, and transfer stages, so the routed population contains 516,074 legs.

## Transit scenario repair

The source public-transport supply is not overwritten. A scenario-specific
`transitSchedule_5pct.xml.gz` is written alongside the plans:

- 112 repeated-terminal circular routes receive their directly connected final
  terminal-link occurrence.
- 69,867 route-stop occurrences receive route-specific, monotonically ordered
  link assignments.
- The assignment-distance p95 is below 0.001 m. The maximum is 763.63 m and is
  retained in `validation/transit_schedule_closed_route_repairs.csv` for supply
  accuracy review.

This repair is needed for QSim operation because a shared physical stop can be
close to several route links while MATSim requires the stop link to occur in
the correct order in each individual network route.

## Outputs

Core files:

- `plans_unrouted_5pct.xml.gz`
- `plans_routed_5pct.xml.gz`
- `facilities_5pct.xml.gz`
- `privateVehicles_5pct.xml.gz`
- `transitSchedule_5pct.xml.gz`
- `transitVehicles_5pct.xml.gz`
- `config_hong_kong_5pct.xml`
- `sampled_agents.parquet`
- `agent_trip_manifest.parquet`
- `household_vehicle_assignment.csv`
- `generation_summary.json`

The `validation/` directory contains DCCA population, TCS26 population,
three-area work OD, work mode, school stage, border, facility-link, school
escort, and transit stop-link audits plus `agents_validation_summary.png`.

## Commands

Generate the demand package:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\demand_generation\build_hong_kong_matsim_agents_5pct.py
```

Route the complete population without running QSim:

```powershell
$env:MAVEN_OPTS="-Xmx12g"
mvn -q "-Dmaven.test.skip=true" exec:java `
  "-Dexec.mainClass=org.matsim.project.RunHongKong5Pct" `
  "-Dexec.args=<config_hong_kong_5pct.xml> <plans_routed_5pct.xml.gz>"
```

Append `--simulate` to the Java arguments to run QSim instead of the route-only
Mobsim. The active configs use `flowCapacityFactor=0.1` and
`storageCapacityFactor=0.1`. The resident/visitor population remains a 5%
sample, so this intentionally provides twice the road capacity implied by a
strict demand-proportional 5% scale. PT departures remain complete while
vehicle capacities are scaled to 5% with a minimum total capacity of one.

## Mixed road-PT with scaled PCU

The active supply is generated with:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_mixed_road_pt_pcu_scaled_supply.py `
  --data-root F:\Matsim\matsim-example-project\data `
  --pcu-factor 0.05
```

Bus and GMB retain their original mixed-road link sequences and therefore
interact with private cars. Their complete service timetable is also retained.
To prevent a full bus fleet from being combined with a 5% population sample,
only road-PT passenger-car equivalents are multiplied by `0.05`: all 11 bus
types change from `2.5` to `0.125`, and the GMB type changes from `1.5` to
`0.075`. Passenger capacities, vehicle dimensions, routes, stops, departures,
and all rail vehicle types remain unchanged.

Formal outputs:

```text
data/transit/hongkong/processed/
  matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_v1/
    network.xml.gz
    transitSchedule_5pct.xml.gz
    transitVehicles_5pct.xml.gz
    road_pt_vehicle_pcu_scaling_audit.csv
    mixed_road_pt_pcu_scaled_supply_summary.json
```

The active zero-iteration load configuration is
`config_hong_kong_5pct.xml`; `config_hong_kong_5pct_50it.xml` is the formal
50-iteration configuration. The dedicated-road-PT alternative is preserved as
`config_hong_kong_5pct_010_dedicated_bus_baseline.xml`, and the original
mixed-link 0.05-capacity configuration as
`config_hong_kong_5pct_005_mixed_baseline.xml`.

## Validation status

- 385,820 people load successfully in MATSim 2026.0.
- The active mixed network loads with 116,874 links, 3,574 transit routes, and
  158,131 departures.
- Twelve road-PT vehicle types and 150,670 bus/GMB departure vehicles use the
  0.05 PCU multiplier; no rail or other vehicle type changed.
- Unrouted plans: 0 bad activity/leg sequences and 0 missing facilities.
- Routed plans: 385,820 people, 516,074 legs, and 0 missing route elements.
- DCCA population WAPE: 3.09%.
- Three-area work OD WAPE: 0.196%.
- Work-mode WAPE: 1.97%.
- A 0.1% smoke scenario completed the full 00:00-30:00 QSim with the road and
  repaired public-transport supply.

The remaining 763.63 m maximum stop-to-route assignment and all inferred PT
timetable/capacity assumptions remain supply-quality limitations. `ride`
represents taxi, private passenger, and school-bus demand without explicit
operator vehicles. V2 purpose shares and post-replanning mode shares require
calibration against future disaggregate resident trip records.

## Laboratory server deployment

The append-only server bundle is prepared with
`scripts/hong_kong_single_city/run/prepare_hong_kong_matsim_server_bundle.py`.
The deployed release is restricted to:

```text
/mnt/DiskM/by/hk_matsim_5pct_mixed_pcu005_v1/
```

It contains a portable Temurin JDK 25, the fat JAR, checksummed inputs,
server-specific configs, a deterministic 7,716-person smoke population, and
separate smoke/formal launchers. `HOME`, `TMPDIR`, Java preferences, logs, and
all MATSim outputs are redirected below the release root. Launchers fail if
their target run directory already exists; no server files are deleted or
overwritten.

The server smoke test used the complete 158,131-departure PT timetable and
finished the 00:00-30:00 QSim with exit code 0, maximum `lost=0`, no stuck or
aborted vehicles, 112.87 seconds wall time, and 12,437,284 KiB peak RSS. The
formal 50-iteration launcher is present but has not been run. It retains
events/plans every 10 iterations and uses
`overwriteFiles=failIfDirectoryExists`.
