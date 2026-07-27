# Hong Kong MATSim road speed and capacity calibration

## Purpose

This workflow replaces the legacy uniform road assumptions (`50 km/h`,
`1 lane`, and `1,800 veh/h`) with link attributes estimated from the 2026
second-generation road network, the 2026-07-22 detector snapshot, and the
2019-2024 Annual Traffic Census (ATC).

The resulting MATSim network stores full-scale supply. The 5% scenario must
continue to use:

```text
flowCapacityFactor = 0.05
storageCapacityFactor = 0.05
```

The network capacity is not multiplied by 0.05 before it is written.

## Inputs

- `data/transit/hongkong/RdNet_IRNP.gdb`
  - `CENTERLINE`: road geometry, route ID, street code and travel direction.
  - `SPEED_LIMIT`: legal speed limits.
- `data/transit/hongkong/TrafficFlow/TrafficDataofRoads20260722/`
  - 4,524 processed speed segment IDs.
  - 760 raw lane detectors, with 30-second speed, volume and occupancy.
  - 807 detector locations.
- `data/transit/hongkong/TrafficFlow/ATC_IRNP.gdb`
  - 1,694 station points and 356 directional station lines.
- `data/transit/hongkong/TrafficFlow/ATC/AnnualTrafficCensusTrafficData_202602/`
  - station AADT for 2019-2024.
  - 191 detailed 2024 station workbooks.
- Calibrated no-ferry base road/PT supply, retained upstream of the active
  Ferry Core v1 scenario:
  `data/transit/hongkong/processed/matsim_road_pt_supply_2026_typical_weekday/`

The geospatial environment requires `xlrd>=2.0.1` to read the official legacy
`.xls` files.

## Method

### Free-flow speed

`SPEED_LIMIT` is the legal ceiling. Roads without an explicit limit use
`50 km/h`. Invalid, non-positive, and implausibly high observations are removed.
For a route with at least 50 valid observations:

```text
freespeed = min(speed_limit, max(observed_speed_q85, 0.85 * speed_limit))
```

Otherwise the legal limit is used. Hourly observed speeds are saved only as
calibration targets; they are not written as time-dependent forced speeds.

### Lanes

The source hierarchy is:

1. Stable detector lane-count mode.
2. Detailed directional ATC peak flow.
3. ATC AADT with road-type peak and direction factors.
4. Propagation along the same TNM `ST_CODE` corridor.
5. Road-type defaults.

The final range is one to six lanes per direction.

### Capacity

Raw 30-second observations are aggregated to 15-minute windows. Windows need
at least 50% temporal coverage and 80% valid lanes. Within 5-40% occupancy,
flow is binned in five-percentage-point bands. The largest band Q90 is the
detector practical capacity and is clipped to `900-2,300 veh/h/lane`.

Detector estimates are shrunk toward the road-type prior:

```text
w = min(0.8, n / (n + 40))
capacity_per_lane = w * detector_estimate + (1 - w) * road_type_prior
```

If a supported ATC peak exceeds 95% of the inferred directional capacity,
lanes are incremented up to six. Remaining exceedances are written to the
manual-review table.

## Run

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\calibrate_hong_kong_road_speed_capacity.py `
  --project-root F:\Matsim\matsim-example-project `
  --update-formal-network
```

Without `--update-formal-network`, the script writes and validates a candidate
but does not replace the formal network.

The public-transport supply builder now automatically reapplies
`road_route_direction_attributes.csv` when it exists. Use
`--without-road-calibration` only to reproduce the historical uniform network.

## Outputs

Calibration outputs are under:

`data/transit/hongkong/processed/road_speed_capacity_2026_v1/`

Important files:

- `network_calibrated_candidate.xml.gz`
- `road_route_direction_attributes.csv`
- `matsim_link_attributes.csv`
- `traffic_detector_route_crosswalk.csv`
- `traffic_detector_lane_capacity_estimates.csv`
- `traffic_detector_15min_windows.csv`
- `atc_station_route_crosswalk.csv`
- `atc_directional_details_2024.csv`
- `hourly_observed_speed_profiles.csv`
- `capacity_model_parameters.json`
- `road_speed_lane_capacity_maps.png`
- `road_attribute_distributions.png`
- `qa/input_data_validation.json`
- `qa/network_candidate_validation.json`
- `road_speed_capacity_summary.json`

The original formal network is retained as:

`network_uniform_capacity_baseline.xml.gz`

in the formal road/PT supply directory, with a SHA256 sidecar.

## Completed-run QA

- 1,694/1,694 2024 ATC records join the ATC station layer.
- 191/191 detailed workbooks parse without error.
- Directional detailed AADT sums agree with the annual source.
- 760 detectors are present; 749 contain at least one valid observation.
- Raw lane-record validity is 97.75%.
- 4,505 of 4,524 legacy speed IDs match 2026 `ROUTE_ID`; the 19 unmatched IDs
  remain in the audit and are not spatially forced onto new roads.
- The candidate and baseline both contain 80,051 nodes and 116,874 links.
- Link IDs, from/to nodes, modes and all transit route-link references match.
- 47,591 original TNM road links receive calibrated attributes.
- MATSim loads 3,574 transit routes and 158,131 departures with the calibrated
  network.
- A full 385,820-agent iteration-0 initialization completes.

Completed-run directional route attributes:

- free-flow speed: mean `51.24 km/h`, range `30-110 km/h`
- lanes: 1=`34,530`, 2=`10,055`, 3=`2,482`, 4=`674`, 5=`167`, 6=`15`
- capacity: median `1,200 veh/h`, mean `1,664.60 veh/h`, maximum `7,204 veh/h`

High-confidence direct detector/ATC evidence covers 771 route directions;
8,651 use corridor or AADT evidence and 38,501 retain low-confidence
road-type defaults. These confidence levels should be used when prioritizing
future count collection and calibration.

## Interpretation

`freespeed` is uncongested supply, not the observed daytime mean. Congestion
must emerge from MATSim demand and capacity. AADT and the single observation
day are checks and local priors, not a complete long-run capacity measurement.
Bus-only lanes, turning lanes, incidents and time-dependent controls remain
outside this aggregated first version.

## TPDM design-flow comparison

An independent decision-support workflow maps the official March 2026 TPDM
design-flow table to RdNet route directions and tests the result against direct
detector/ATC flow lower bounds and an AADT-derived soft lower bound. It does not
modify the calibrated or formal network.

See `docs/HONG_KONG_TPDM_CAPACITY_MAPPING.md`.

## OSM class and lane candidates

The local Hong Kong OSM PBF can be used as secondary evidence to correct
low-confidence road classes and fill directional lanes. The independent
workflow protects ATC and detector evidence and does not modify capacity or the
formal network.

See `docs/HONG_KONG_OSM_ROAD_CLASS_LANE_ENRICHMENT.md`.
