# Hong Kong TPDM road-capacity mapping

## Purpose

This workflow maps the Hong Kong Transport Department's official design-flow
guidance to the existing RdNet route directions and MATSim road links. It is a
decision-support comparison only. It does not edit the formal
`network.xml.gz`.

Official source:

- Transport Planning and Design Manual, Volume 2, March 2026 edition.
- Chapter 2, Table 2.4.1.1, `Design Flows`.
- <https://www.td.gov.hk/filemanager/en/content_5055/V2_03_2026.pdf>

TPDM defines design flow as the maximum hourly flow that can be accommodated
without unreasonable delay, hazard, or restriction to manoeuvring. The table
is carriageway-specific rather than a universal per-lane capacity table.

## Mapping rules

Road classes are mapped as follows:

| RdNet/ATC class | TPDM family |
|---|---|
| `EX`, `UT`, `RT` | Expressway/trunk road |
| `PD` | Primary distributor |
| `DD` | District distributor |
| `LD` | Local road |
| `RR` | Local road, provisional |

Cross sections are inferred from the current directional lane estimate and
RdNet `TRAVEL_DIRECTION`:

- `TRAVEL_DIRECTION=1`, one lane per direction: two-lane carriageway.
- `TRAVEL_DIRECTION=1`, two lanes per direction: undivided four-lane
  carriageway.
- `TRAVEL_DIRECTION=3`: separate one-way/dual carriageway.
- Other combinations remain manual-review cases.

RdNet has no carriageway-width field. Width-dependent TPDM values are therefore
stored as low/reference/high ranges. Published two-way values are split
equally between the two MATSim directions. This is explicit in the output and
can be replaced later when directional split or width evidence becomes
available.

## Traffic lower-bound test

Three traffic checks are kept separate:

1. The maximum valid 2026-07-22 rolling peak-hour detector flow. A peak hour
   must contain four consecutive 15-minute windows and at least 75% temporal
   coverage.
2. The maximum reported 2024 detailed ATC AM/PM directional peak flow.
3. The AADT-derived directional peak estimate, treated only as a soft lower
   bound.

The direct lower bound is the maximum of items 1 and 2. The combined lower
bound also includes item 3. A TPDM reference fails a lower-bound test when it
is smaller than the corresponding traffic value.

The review-only capacity is:

```text
max(TPDM reference, combined traffic lower bound)
```

This does not claim that observed flow is maximum capacity. It only prevents a
candidate from being lower than flow already carried by the road. The raw TPDM
value and every lower-bound component remain available for review.

Missing detector records do not directly reduce a retained window's rate:
volume is divided by actual observed seconds. The formal comparison uses a
rolling hour because TPDM is an hourly-flow standard. The 15-minute 99th
percentile remains in the CSV only as a short-period stress diagnostic.

## Run

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_tpdm_capacity_mapping.py `
  --project-root F:\Matsim\matsim-example-project
```

## Outputs

The output directory is:

`data/transit/hongkong/processed/road_tpdm_capacity_mapping_2026_v1/`

- `tpdm_design_flow_reference.csv`: transcription of official Table 2.4.1.1.
- `rdnet_route_direction_tpdm_mapping.csv`: one row per RdNet direction.
- `matsim_link_tpdm_mapping.csv`: the same evidence expanded to MATSim links.
- `tpdm_flow_floor_and_mapping_exceptions.csv`: all non-ready cases.
- `tpdm_mapping_summary_by_road_type.csv`: adoption-oriented class summary.
- `tpdm_capacity_mapping_summary.json`: QA counts and limitations.
- `tpdm_capacity_mapping_qa.png`: coverage and lower-bound failures.

## Interpretation limits

- TPDM values include up to 15% heavy vehicles. No heavy-vehicle adjustment is
  currently applied because a reliable directional heavy-vehicle share is not
  present in the normalized inputs.
- TPDM warns that existing junctions, signals, accesses, kerb activities, and
  pedestrian crossings can prevent a link from achieving its nominal design
  flow.
- AADT-derived hourly values are model-based checks, not direct peak-hour
  observations.
- Extrapolated lane counts and provisional `RR -> local road` mappings require
  review before adoption.

## Completed-run results

The completed candidate run contains:

- `47,923` RdNet route directions and `47,591` MATSim road links.
- `27,802` route directions with an exact, width-range, local-guidance, or
  explicitly extrapolated TPDM value (`58.01%`).
- `20,121` route directions without a matching official TPDM cross section.
- `341` route directions with a reliable direct rolling-hour detector or
  detailed ATC lower bound; `220` of these also have a TPDM value.
- `374` route directions with either direct evidence or an AADT-derived soft
  lower bound.
- `12` mapped route directions where the TPDM reference is below the direct
  observed peak-hour flow.

Across all mapped route directions, `21,694` TPDM references are below the
current calibrated capacity and `6,108` are above it. This is dominated by the
official local-road guidance of `800 veh/h` two-way, represented as
`400 veh/h` per MATSim direction. Because most local roads have no direct
hourly count, this value should not be adopted network-wide without additional
review of directional sharing, junction representation, and current road-class
assignments.
