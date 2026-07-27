# Hong Kong synthetic households and private vehicles

## Scope

This workflow creates full-scale synthetic domestic households, household
members, private vehicles, and designated drivers for the Hong Kong fixed-link
model area. It combines 2021 Census household marginals with 2022 Travel
Characteristics Survey (TCS) private-vehicle controls. The records are
synthetic expectations for demand modelling, not reconstructed Census
microdata or observed driving-licence records.

Formal output directory:

```text
data/matsim_agents/hongkong/synthetic_households_tcs2022/
```

## Source roles

- `DCCA_21C.xlsx` supplies 452-area domestic household totals, household-size
  bands, seven income bands, five housing types, average household size, broad
  age bands, and sex totals.
- `dcca_fixed_link_retention.csv` scales partially retained DCCAs by calibrated
  population. Lamma/Po Toi and Cheung Chau have zero retained population and
  receive no synthetic households.
- `dcca_study_area_crosswalk.parquet` locates households on the 1,585 grids and
  assigns the TCS 26 broad districts. Selection weights are grid population
  multiplied by the DCCA share of the grid.
- TCS 2022 Appendix Table A.4 supplies district rates for one, two, and more
  than two private cars; one and two-or-more motorcycles; and households with
  any private vehicle available.
- TCS 2022 Table 4.2 supplies private-vehicle availability rates by housing
  type, monthly household income, and household size.

Official references:

- `https://www.td.gov.hk/filemanager/en/content_5349/tcs2022_eng.pdf`
- `https://www.td.gov.hk/filemanager/en/content_5349/tcs2022app_eng.pdf`

## Synthesis method

Each retained DCCA household total is integerised by largest remainder. Its
household-size, income, and housing marginals are separately controlled to the
same integer total. A shared latent socioeconomic rank induces plausible
positive association between private housing and income without claiming an
observed joint distribution.

Households are located on DCCA-intersecting grids using calibrated population
weights. The selected crosswalk atom determines the TCS broad district,
including the Yau Ma Tei/Mong Kok split, new towns, and four other-NT areas.

The prior private-vehicle score is:

```text
logit(p) = logit(TCS district rate)
         + 0.5 * [housing log-odds effect
                  + income log-odds effect
                  + household-size log-odds effect]
```

The `0.5` shrinkage avoids treating three correlated one-dimensional TCS
tables as independent conditional coefficients. It is configurable. Within
each broad district, weighted rank selection then exactly controls the number
of households with any private vehicle. Private-car and motorcycle household
subtotals and their quantity bands are also integer controlled to Table A.4.
Thus Table 4.2 affects household ranking, while Table A.4 is the hard district
margin.

The published `more than 2` private-car class is represented by three cars and
the `2 or more` motorcycle class by two motorcycles. Vehicle totals are
therefore conservative lower-bound representative counts.

Members are generated from each DCCA's age and sex margins. Every household
receives one adult reference person. Other members receive synthetic
relationship roles from age and within-household position. Vehicles are
assigned to adult members, preferring ages near 45 and rotating across
eligible adults when a household has multiple vehicles. `potential vehicle
access` means an adult lives in a vehicle-available household; it is not an
observed driving licence.

## Outputs

- `synthetic_households.parquet`: household attributes, location, TCS district,
  vehicle prior, and final vehicle counts.
- `synthetic_persons.parquet`: household membership, age, sex, relationship,
  potential vehicle access, and designated-driver fields.
- `synthetic_household_vehicles.parquet`: one record per representative car or
  motorcycle with its designated driver.
- `tcs2022_table_a4_vehicle_controls.csv`: normalized published controls.
- `tcs26_vehicle_validation.csv`: integer targets and realized counts for all
  26 broad districts.
- `tcs2022_table_4_2_household_characteristic_validation.csv`: published and
  synthetic rates by housing, income, and household size.
- `dcca_household_totals_validation.csv`: retained household and member totals.
- `dcca_household_marginal_validation.csv`: long-form DCCA marginal checks.
- `dcca_person_marginal_validation.csv`: DCCA age-band and sex checks after
  household membership and adult-reference assignment.
- `grid_household_population_summary.csv`: grid household, member, and vehicle
  totals for later MATSim population construction.
- `synthetic_household_generation_summary.json`: run parameters and principal
  QA results.

## Current full-scale result

```text
Synthetic households:                         2,660,561
Synthetic household members:                  7,265,494
Households with private vehicles:                460,610
Representative private cars (lower bound):       506,701
Representative motorcycles (lower bound):         37,455
Representative vehicles (lower bound):            544,156
Maximum TCS 26-zone household control error:             0
Maximum DCCA household marginal error:                    0
Maximum DCCA age/sex marginal error:                       0
```

The 26 district vehicle-availability rates differ from the published
percentage targets by at most `0.00175` percentage points after integerisation.
All household, person, vehicle, and designated-driver IDs are unique and all
references resolve.

DCCA household-size bands and the published one-decimal average household size
cannot both be exact in every DCCA. The size bands are treated as the stronger
integer controls; concrete sizes within the `6+` class absorb compatible
differences. The resulting member-count WAPE against rounded DCCA average size
is `0.274%`.

## Run

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\demand_generation\build_hong_kong_synthetic_households.py `
  --data-root F:\Matsim\matsim-example-project\data
```

Use `--sample-rate 0.01` for a weighted development sample. Formal MATSim
demand preparation should use the default full-scale result.
