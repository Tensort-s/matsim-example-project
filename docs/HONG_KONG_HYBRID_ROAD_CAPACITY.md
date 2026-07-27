# Hong Kong hybrid road capacity

## Purpose

This candidate combines official TPDM cross-section design flow, corrected
directional lanes, and direct ATC/detector flow lower bounds. It replaces
neither the formal MATSim network nor the historical capacity candidates.

## Method

For each corrected route direction:

```text
class empirical anchor =
    max(
        class P95 of ATC peak-hour flow per lane,
        class P95 of detector 15-minute-Q95 flow per lane
    )

raw capacity =
    max(
        TPDM cross-section reference,
        corrected lanes * class empirical anchor / 0.95,
        direct ATC-or-detector flow lower bound / 0.95
    )

capacity = raw capacity rounded upward to 50 veh/h
```

The direct ATC value is the larger of the published weekday AM and PM
peak-hour flows. No detector direction has 75% coverage for a complete rolling
hour on the available observation day. Detector evidence therefore uses the
coverage-normalized 15-minute Q95 as an explicitly labelled fallback rather
than presenting it as a complete observed hour.

TPDM values remain cross-section-specific. In particular, the `1,950 veh/h`
district-distributor reference applies to the two-lanes-per-direction
undivided four-lane cross-section; a one-lane-per-direction district
distributor uses the TPDM one-direction reference of `850 veh/h`.

## Empirical per-lane anchors

| Road type | ATC P95 | Detector P95 | Selected anchor |
|---|---:|---:|---:|
| EX | 1,813.33 | 1,445.15 | 1,813.33 |
| UT | 1,616.50 | 1,412.04 | 1,616.50 |
| PD | 840.21 | 1,227.92 | 1,227.92 |
| DD | 763.75 | 520.59 | 763.75 |
| LD | 1,077.33 | 916.99 | 1,077.33 |
| RT | 950.25 | 762.01 | 950.25 |
| RR | 752.00 | 598.57 | 752.00 |

All values are `veh/h/lane`.

## Completed result

- 47,923 route directions and 47,591 MATSim road links.
- 27,748 route directions have a TPDM cross-section value.
- 341 directions have direct ATC evidence.
- 452 directions use the detector 15-minute-Q95 fallback.
- Capacity range: `800-11,950 veh/h`.
- Median: `1,150 veh/h`; mean: `1,750.54 veh/h`; P95: `4,200 veh/h`.
- Maximum resulting per-lane capacity: `2,100 veh/h/lane`.
- All 768 directions with direct flow evidence have observed `v/c <= 0.95`.

The controlling component is the class/lane empirical anchor for 41,914
directions, TPDM for 5,990, and direct observed flow for 18; one direction is
an exact tie.

## Run

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_hybrid_road_capacity.py `
  --project-root F:\Matsim\matsim-example-project
```

Outputs:

`data/transit/hongkong/processed/road_capacity_hybrid_tpdm_flow_2026_v1/`

The candidate network stores full-scale capacities. The 5% MATSim scenario
must continue to apply `flowCapacityFactor=0.05` and
`storageCapacityFactor=0.05`; capacities must not be pre-scaled.
