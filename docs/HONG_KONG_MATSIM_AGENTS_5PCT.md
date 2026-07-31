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

The active v2 unrouted plans contain 743,614 main legs. MATSim routing expands
PT access, egress, and transfer stages, so the routed population contains
879,050 legs.

## Transit scenario repair and active supply

The v1 compulsory-demand build created a scenario-specific repaired schedule
without overwriting its source public-transport supply:

- 112 repeated-terminal circular routes receive their directly connected final
  terminal-link occurrence.
- 69,867 route-stop occurrences receive route-specific, monotonically ordered
  link assignments.
- The assignment-distance p95 is below 0.001 m. The maximum is 763.63 m and is
  retained in `validation/transit_schedule_closed_route_repairs.csv` for supply
  accuracy review.

This repair was needed for QSim operation because a shared physical stop can be
close to several route links while MATSim requires the stop link to occur in
the correct order in each individual network route. The active v2 run uses the
Ferry Core v1 cap010 supply, which retains those accepted stop/link sequences,
adds 21 core ferry routes, scales all public-transport passenger capacities to
10%, and keeps bus/GMB road PCUs at `0.125/0.075`.

## Outputs

Active v2 demand files:

- `plans_unrouted_5pct_v2.xml.gz`
- `plans_routed_5pct_v2.xml.gz`
- `facilities_5pct_v2.xml.gz`
- `privateVehicles_5pct.xml.gz`
- `config_hong_kong_5pct_v2_activity_modechoice_0it.xml`
- `config_hong_kong_5pct_v2_activity_modechoice_50it.xml`
- `agent_trip_manifest_v2.parquet`
- `resident_discretionary_activity_assignments.parquet`
- `generation_summary.json`

The active supply files are:

```text
data/transit/hongkong/processed/
  matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_ferry_core_v1_cap010/
    network.xml.gz
    transitSchedule_5pct.xml.gz
    transitVehicles_10pct.xml.gz
```

The v1 `validation/` directory retains DCCA population, TCS26 population,
three-area work OD, work mode, school stage, border, facility-link, school
escort, and transit stop-link audits. V2 adds its own TCS all-purpose demand
and plan validation files.

## Taxi and ride audit

The July 2026 taxi audit is documented in
`docs/HONG_KONG_TAXI_INITIAL_PLAN_AUDIT.md`. It reads Transport Department
Tables 2.1S, 2.1, 2.2, and 4.1(a), filters `TTD_PTO_CODE=TAX`, converts
passenger-journey fields from thousand passenger journeys to actual passenger
journeys, and compares the official 5% daily target with the current initial
v2 `ride` legs. It does not overwrite or modify `plans_unrouted_5pct_v2.xml.gz`
or `plans_routed_5pct_v2.xml.gz`.

The current audit outputs are under:

```text
data/taxi/hongkong/processed/taxi_initial_plan_audit_2026_jan_jun/
```

For the available 202601-202604 official records, the 5% taxi target averages
37,285.773 passenger journeys/day. Current v2 initial plans contain 4,614
explicit taxi legs, 3,564 private-car passenger legs, 9,626 school-bus legs,
and 38,556 unspecified `ride` legs. This confirms that `ride` remains an
aggregate MATSim passenger mode rather than a calibrated taxi-operator demand
and fleet model.

The first auxiliary taxi allocation layer is
`data/taxi/hongkong/processed/taxi_initial_plan_allocation_v1/`. It keeps the
4,614 explicit taxi legs, 3,564 private-car passenger legs, and 9,626
school-bus legs fixed. In the base scenario, it assigns complete tours from the
38,556 unspecified `ride` legs so that 32,672 additional legs become taxi and
5,884 remain `other_ride`, giving exactly 37,286 total 5% taxi passenger legs.
Low and high scenarios use the available Jan-Apr minimum and maximum official
controls and also hit their integer targets exactly. This layer is not written
back to the plans XML.

## Commands

Generate the demand package:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\demand_generation\build_hong_kong_matsim_agents_5pct.py
```

Enrich the compulsory v1 population into the active v2 plans:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\demand_generation\enrich_hong_kong_matsim_agents_5pct.py `
  --data-root F:\Matsim\matsim-example-project\data
```

Route the complete v2 population without running QSim:

```powershell
$env:MAVEN_OPTS="-Xmx12g"
mvn -q "-Dmaven.test.skip=true" exec:java `
  "-Dexec.mainClass=org.matsim.project.RunHongKong5Pct" `
  "-Dexec.args=<config_hong_kong_5pct_v2_activity_modechoice_0it.xml> <plans_routed_5pct_v2.xml.gz>"
```

Append `--simulate` to the Java arguments to run QSim instead of the route-only
Mobsim. The active configs use `flowCapacityFactor=0.1` and
`storageCapacityFactor=0.1`. The resident/visitor population remains a 5%
sample, so this intentionally provides twice the road capacity implied by a
strict demand-proportional 5% scale. PT departures remain complete while
vehicle passenger capacities are scaled to 10% with a minimum total capacity
of one.

## Mixed road-PT, Ferry Core v1, and scaled PCU

The bus/GMB PCU scaling intermediate is generated with:

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

This intermediate is then extended by Ferry Core v1 and regenerated with 10%
passenger capacities. The active formal outputs are:

```text
data/transit/hongkong/processed/
  matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_ferry_core_v1_cap010/
    network.xml.gz
    transitSchedule_5pct.xml.gz
    transitVehicles_10pct.xml.gz
    ferry_core_supply_summary.json
    transit_vehicle_capacity_10pct_audit.csv
```

The active zero-iteration and formal configurations are
`config_hong_kong_5pct_v2_activity_modechoice_0it.xml` and
`config_hong_kong_5pct_v2_activity_modechoice_50it.xml`. V1, dedicated-road-PT,
and pre-Ferry configurations are retained only as baselines or build
dependencies.

## Validation status

- 385,820 people load successfully in MATSim 2026.0.
- The active Ferry Core network loads with 117,989 links, 3,613 transit routes,
  and 159,967 departures.
- Twelve road-PT vehicle types and 150,670 bus/GMB departure vehicles use the
  0.05 PCU multiplier; no rail or other vehicle type changed.
- Active v2 plans: 385,820 people, 743,614 unrouted legs, 879,050 routed legs,
  0 bad activity/leg sequences, and 0 missing facilities.
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
The active Stage 8D contract supersedes the historical v1/pre-Ferry defaults:
it accepts only the hash-locked v2 activity-modechoice demand and Ferry Core
v1 / 10% PT-capacity supply. The caller must provide a new release root below
`/mnt/DiskM/by/` and an exact pushed source SHA; no historical release root is
an active default.

It contains a portable Temurin JDK 25, the fat JAR, checksummed inputs,
server-specific configs, a deterministic 7,716-person smoke population, and
separate smoke/formal launchers. `HOME`, `TMPDIR`, Java preferences, logs, and
all MATSim outputs are redirected below the release root. Launchers fail if
their target run directory already exists; no server files are deleted or
overwritten.

Before copying anything, the current script verifies either a clean exact Git
SHA or a Git-metadata-free snapshot that reconstructs the locked exact Git
tree. Snapshot proof includes an out-of-band manifest hash, archive hash and a
7,620-file path/mode/blob/size/SHA256 inventory; wrong SHA/tree or tampering
fails closed. It also verifies all seven current input hashes, the approved
JDK archive hash, Linux JDK 25 / Maven / MATSim build metadata, and the
Taxi/PT/Car runtime-class inventory in the fat JAR. It emits an external
deployment manifest containing source identity, JAR, bundle and input hashes.
Server-side snapshot transfer/build, upload and execution require a separate
Supervisor authorization; no JDK is downloaded or fabricated by the
preparation workflow. The current contract is documented in
`docs/HONG_KONG_MATSIM_SERVER_BUNDLE_STAGE8D.md`.

The server smoke test used the complete 158,131-departure PT timetable and
finished the 00:00-30:00 QSim with exit code 0, maximum `lost=0`, no stuck or
aborted vehicles, 112.87 seconds wall time, and 12,437,284 KiB peak RSS. The
formal 50-iteration launcher is present but has not been run. It retains
events/plans every 10 iterations and uses
`overwriteFiles=failIfDirectoryExists`.
