# Fuzhou ride_hailing integration

This version adds a network-based `ride_hailing` mode using MATSim 2026 taxi/DVRP.

## Generated inputs

- Demand with ride-hailing candidates:
  - `data/matsim_routes/fuzhou_city_23_greenspace_grid_multi_activity_2pct_ride_hailing/mode_choice_plans_car_pt_walk_ride_hailing_2pct.xml.gz`
- Taxi/DVRP fleet:
  - `data/ride_hailing/fuzhou_ride_hailing_2pct_20260712/ride_hailing_fleet.xml.gz`
- Fleet QA:
  - `data/ride_hailing/fuzhou_ride_hailing_2pct_20260712/ride_hailing_preparation_summary.json`
  - `data/ride_hailing/fuzhou_ride_hailing_2pct_20260712/ride_hailing_start_links.csv`

The fleet size is computed as:

```text
round(34,709 * population_sample_rate)
```

For the current 2% population this gives 694 vehicles.

## Run commands

For long Windows runs, prefer the documented `.cmd` launch pattern:

```text
docs/WINDOWS_MATSIM_LONG_RUN_LAUNCH.md
```

In short: use a `.cmd` wrapper, Maven's absolute path, quote both `-Dexec.*` arguments, and write stdout/stderr/exit code to `run_logs`.

Smoke test:

```powershell
cd F:\Matsim\matsim-example-project
mvn clean package -DskipTests
mvn exec:java "-Dexec.mainClass=org.matsim.project.RunMatsimModelImplementation" "-Dexec.args=run --config .\scenarios\fuzhou\config-transit-mode-choice-2pct-ride-hailing-smoke.xml"
```

20-iteration continuation:

```powershell
cd F:\Matsim\matsim-example-project
mvn exec:java "-Dexec.mainClass=org.matsim.project.RunMatsimModelImplementation" "-Dexec.args=run --config .\scenarios\fuzhou\config-transit-mode-choice-2pct-ride-hailing-cont20.xml"
```

## Current validation

- `mvn clean package -DskipTests` passes.
- Smoke test reaches `ITERATION 0 ENDS`.
- The generated fleet has 694 vehicles, capacity 4, 8-hour service windows.
- `carAvail=never` agents have zero car candidate plans.
- Every agent has one `ride_hailing` candidate plan.

The smoke command may continue into SimWrapper post-processing after the main simulation has completed; the decisive smoke marker is `ITERATION 0 ENDS` in `output-fuzhou-transit-mode-choice-2pct-ride-hailing-smoke/logfile.log`.
