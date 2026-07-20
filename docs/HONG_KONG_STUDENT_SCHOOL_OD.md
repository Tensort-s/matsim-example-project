# Hong Kong student-school OD for 2022

## Purpose

This pipeline builds a fixed-link Hong Kong student-to-school assignment from
official Census, Education Bureau, TCS 2022, and calibrated population data.
It produces a long-term expected-student assignment and a weekday mechanized
HBS trip matrix. These products have different units and must not be
interchanged.

## Authoritative inputs

- `DCCA_21C.xlsx`: authoritative values for 452 DCCA records and five
  study-place flow fields.
- `DCCA_21C_converted.shp`: DCCA geometry in `EPSG:2326`.
- `DC_21C_converted.shp`: independent 18-district aggregation check.
- `NewTown_2021.shp`: 13 official 2021 New Town boundaries.
- corrected WorldPop age/sex data and the 1,585 fixed-link grids.
- EDB school locations and 2022 stage/sector enrollment statistics.
- TCS 2022 HBS production, attraction, and mechanized mode tables.

The DCCA fields `pls_same`, `pls_diff_hk`, `pls_diff_kln`, `pls_diff_nt`,
and `s_diff_oth` map to `same`, `diff_hk`, `diff_kln`, `diff_nt`, and
`diff_oth`. Their Census total is 1,063,445 full-time students. They constrain
five destination classes from each residential DCCA; they are not a complete
452-by-452 OD matrix.

## Census study areas

The Census study-area geography is separate from the TCS 26-zone geography:

- Hong Kong Island and Kowloon use District Council districts.
- New Territories new-town land uses official New Towns.
- Remaining New Territories land uses the non-new-town part of its district.

A DCCA crossing a study-area boundary is split into DCCA-by-study-area atoms.
Corrected school-age population allocates its mass to atoms and grids.
Fixed-link retention is population weighted, not area weighted.

`same` follows the Census footnote: same district on Hong Kong Island or
Kowloon, same New Town for new-town residents, or the non-new-town part of the
same New Territories district for other residents.

## Assignment model

The origin prior combines calibrated age-band population, DCCA student
intensity, EDB retained stage totals, and TCS resident-student margins. School
programs retain stage, sector, and session distinctions. Individual school
capacity is estimated and is not an official enrollment count.

```text
weight = origin_stage_students
       * school_capacity_prior
       * exp(-distance / stage_distance_scale)
```

Generalized IPF fits every origin-grid-by-stage total, every EDB
stage-by-sector retained total, and every DCCA atom-by-five-category total.
Base distance scales are 2/3/5/8 km for kindergarten, primary, secondary, and
special education. Short and long runs use 0.75 and 1.5 times those scales.

Some atom/category cells have no retained, stage-compatible EDB school. The
model does not invent virtual schools. It transfers only structurally
unsupported mass to the nearest supported category and records every event in
`dcca_flow_support_reconciliation.csv`. The official run reallocates about
1,608 expected students, about 0.20% of retained day-school students. Both the
original scaled and supported targets remain in the validation CSV.

## TCS conversion

The canonical assignment is converted to mechanized weekday HBS trips using:

```text
retained assigned students * 1,162,000 / 1,105,500
```

A separate 26-by-26 block IPF matches TCS production and attraction margins.
This changes daily trip weights, not the long-term school pairing.

Direction and time outputs use 50% per direction, 64% of home-to-school in
07:00-08:00, and 22%/23% of school-to-home in 13:00-14:00/16:00-17:00.
`main_mode_equivalent` approximates mutually exclusive trips.
`boarding_equivalent` represents boardings and may exceed trips. Walk and
cycle are not inferred from the published purpose-composition shares.

## Run

```powershell
.\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\demand_generation\build_hong_kong_student_school_od.py `
  --data-root .\data
```

The script requires `pyarrow` for GeoParquet output.

## Outputs and units

Outputs are under `data/school/hongkong/processed/student_school_od_2022/`.

- `student_school_assignment_od.parquet`: expected students by origin, stage,
  and school program.
- `student_school_assignment_grid_school.npz`: sparse expected-student
  home-grid-to-school matrix.
- `student_school_assignment_grid_od.npy`: expected students on 1,585 grids.
- `schools_2022_capacity_estimates.*` and
  `school_campus_capacity_estimates.*`: estimated assignment totals.
- `hbs_mechanized_home_school_grid_od.npy`: weekday mechanized HBS trips.
- `direction_time_od/`: directional and time-window trip matrices.
- `mode_od/main_mode_equivalent/`: approximate trip-mode matrices.
- `mode_od/boarding_equivalent/`: boarding matrices.
- `dcca_study_flow_constraints.csv`: raw, fixed-link-adjusted,
  day-school-scaled, supported, and modeled DCCA-by-five values.
- `dc18_study_flow_validation.csv` and `tcs26_marginal_validation.csv`:
  higher-level QA.
- `distance_scenario_*.csv`: short/base/long sensitivity results.
- `student_school_od_summary.json` and PNG files: numeric and visual QA.

## Flow maps

Run:

```powershell
.\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\analysis_visualization\visualize_hong_kong_student_school_od_flows.py
```

The `flow_maps/` directory contains two matched map sets:

- `student_assignment` uses expected students and represents long-term
  home-to-school pairing.
- `mechanized_home_to_school` uses weekday daily home-to-school trips after the
  50% direction split and TCS scaling.

Each set includes a top-3,000 home-grid-to-school map, a top-60 directed
18-district map, corresponding flow CSV files, an 18-by-18 matrix, and summary
statistics. The detailed maps start at residential grid centroids and end at
the exact EDB school coordinates; blue points mark the school endpoints.
Mechanized grid flows are distributed among schools in each destination grid
in proportion to the canonical student assignment. District node size encodes
within-district flow, while arrow width encodes directed inter-district flow.
The exact-point outputs are under
`flow_maps/exact_school_points_top3000/`.

## Official-run QA

- 452 DCCAs, 31 Census study areas, and 1,585 grids.
- 3,460 of 3,489 EDB school records retained.
- About 800,761 retained expected day-school students.
- About 841,686 weekday mechanized HBS trips.
- Supported DCCA-by-five target WAPE is numerical zero.
- Unreconciled-target WAPE is about 0.402% because a small number of
  structural-zero cells cannot map to a real compatible school.
