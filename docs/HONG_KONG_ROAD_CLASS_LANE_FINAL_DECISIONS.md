# Hong Kong final road-class and lane decisions

## Purpose

This workflow resolves the OSM enrichment review queue using fixed evidence
priorities. It produces final road-class and lane decisions without changing
road capacity.

## Road-class hierarchy

```text
ATC direct
> unanimous ST_CODE ATC corridor
> high-confidence OSM/ATC probability model
> existing speed/route/default fallback
```

- ATC-direct and unanimous corridor classes are always preserved.
- The OSM model is used only for existing low-confidence fallback classes and
  only when the enrichment model already passed the `0.80` probability and
  `0.25` margin thresholds.
- OSM `*_link` ways inherit a class only from a reliable same-`ST_CODE`
  parent.
- Low-confidence model disagreements and links without a reliable parent keep
  the existing fallback class.

## Lane hierarchy

```text
stable detector modal lanes
> OSM lanes:forward/backward
> OSM one-way lanes
> even OSM two-way total split
> existing ATC/AADT/corridor/default estimate
```

This hierarchy is deterministic. When reliable OSM lane evidence exists it
overrides ATC-flow-inferred, AADT-inferred, corridor-propagated, and default
lanes, even for a large difference. Stable detector lane counts are always
preserved. Odd two-way OSM totals without directional tags remain unusable and
fall through to the existing estimate.

## Capacity and network handling

- `capacity` and `freespeed` remain unchanged.
- The formal network is not overwritten.
- A separate candidate network changes only `permlanes`, preserving every link
  ID, topology, mode, speed, and capacity.
- The corrected route-direction CSV is the appropriate class/lane input for a
  future capacity decision.

## Run

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\finalize_hong_kong_road_class_lane_decisions.py `
  --project-root F:\Matsim\matsim-example-project
```

## Outputs

Outputs are written to:

`data/transit/hongkong/processed/road_class_lane_final_decisions_2026_v1/`

- `road_type_final_decisions.csv`
- `lane_count_final_decisions.csv`
- `road_route_direction_attributes_corrected.csv`
- `matsim_link_class_lane_decisions.csv`
- `network_class_lane_corrected_capacity_unchanged.xml.gz`
- `final_road_class_lane_decision_maps.png`
- `final_decision_summary.json`

## 2026 v1 result

The completed deterministic run contains:

- 36,395 road routes and 47,923 route directions.
- 742 final road-class changes; all 13,136 routes backed by direct ATC or
  unanimous same-`ST_CODE` corridor evidence were preserved.
- 11,930 route-direction lane changes.
- All 456 stable detector lane decisions were preserved.
- 28,606 route directions used OSM lane evidence:
  3,029 directional-tag, 16,188 one-way, and 9,389 even two-way split
  decisions.
- 11,919 MATSim road links changed `permlanes`.

The candidate and formal networks have the same 116,874 link IDs in the same
order. A line-by-line comparison confirmed zero changes to capacity,
freespeed, modes, topology, and all XML content other than the 11,919
`permlanes` attributes.

This result closes the class/lane review queue through deterministic fallback:
weak or conflicting secondary evidence keeps the existing estimate. It does
not claim that every fallback value became observed data, and it does not
select a final capacity scheme.

## ATC flow guard v2

The v2 workflow resolves every lane-count disagreement between direct ATC
peak-flow evidence and an adopted OSM lane record:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\resolve_hong_kong_atc_osm_lane_conflicts.py `
  --project-root F:\Matsim\matsim-example-project
```

The decision uses the calibration workflow's physical ceiling of
`2,300 veh/h/lane`. OSM remains the preferred physical lane record when the
direct ATC peak flow can pass through it without exceeding that ceiling.
Otherwise, the ATC-derived lane candidate is restored. AADT-derived flows are
not treated as direct observations.

The completed run found 167 disagreements, all backed by direct 2024 ATC
peak-hour flow. It retained 162 OSM records and restored five ATC lane
decisions. The maximum selected flow fell from `4,860` to
`1,980 veh/h/lane`. Outputs are written to:

`data/transit/hongkong/processed/road_class_lane_final_decisions_2026_v2_atc_flow_guard/`

The v1 result remains as provenance. The v2 candidate network supersedes v1
for subsequent capacity selection and MATSim supply assembly, but still does
not overwrite the formal network or change capacity.
