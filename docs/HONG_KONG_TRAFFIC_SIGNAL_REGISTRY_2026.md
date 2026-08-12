# Hong Kong traffic-signal location registry 2026 v1

## Status and scope

`hong_kong_traffic_signal_registry_2026_v1` is the current adoption-ready
**location and network-link candidate registry** for Hong Kong traffic signals.
It is not yet an adopted MATSim signals input and does not alter the active
network, config, public-transport schedule, plans, scoring, or Stage 11 runs.

The registry answers a narrower prerequisite question: how many physical
signal-control locations can be recovered from the 5,540 OSM
`highway=traffic_signals` nodes after comparison with Transport Department
traffic-light facilities and the active MATSim road topology? It deliberately
does not infer signal cycles, phases, green splits, intergreens or coordination
offsets, because neither source contains those operational timing data.

## Sources

### Transport Department Traffic Aids Drawings (2nd generation)

The official monthly dataset is published at:

```text
https://data.gov.hk/en-data/dataset/hk-td-tis_16-traffic-aids-drawings-v2
```

The archived raw files are under:

```text
data/transit/hongkong/raw/traffic_signals_2026/
```

`SOURCE_MANIFEST.csv` records source URLs, sizes and provenance-only SHA256
values. The hashes are not used as build or simulation gates.

The build uses `DTAD_TRAFFIC_LIGHT_PT.gml`. Its native CRS is Hong Kong 1980
Grid, `EPSG:2326`; it contains 37,167 traffic-light point features with fields
such as `REFNAME`, `FEATUREID`, `LAST_UPD_DATE`, `ANGLE` and `ELEVATION`.
The official data dictionary calls these rows **Traffic light point** features.
They are CAD/equipment symbols, not one-record-per-junction observations.

The downloaded line and filled-polygon layers are retained as raw source
material but are not used to count junctions. They are graphical components of
the same traffic-light symbols and do not provide a junction/controller key.

### OpenStreetMap

The OSM source is:

```text
data/osm/hongkong/fixed_link_boundary/hong-kong-latest.osm.pbf
```

It contains 5,540 nodes tagged `highway=traffic_signals`. These are signal
heads, stop-line/approach nodes, pedestrian crossings or intersection nodes;
they are not 5,540 physical junctions. OSM supplies a decisive extra field for
many locations: 1,766 normalized Hong Kong controller/junction references,
such as `H###`, `K###`, `NT###` and `L###`.

### Independent official aggregate

The Transport Department Area Traffic Control page reported approximately
2,028 signalised junctions as of mid-2025. This total is used only as an
independent reasonableness benchmark. It is not converted into synthetic
records and the registry is not forced to equal it.

## Fusion method

All geometry is transformed to `EPSG:32650` for metric matching.

1. Normalize OSM controller references, including `N###` to `NT###` and
   zero-padding short numeric references.
2. Split a repeated reference only when its OSM observations form spatial
   components more than 90 m apart. Such cases remain explicit conflicts.
3. Assign an unreferenced OSM node to the nearest referenced group within
   45 m, except when a different reference is within an 8 m ambiguity margin.
4. Cluster remaining unreferenced OSM nodes at 35 m. This is deliberately
   conservative in dense urban blocks.
5. Match every OSM node to the nearest official traffic-light point. A match
   within 30 m counts as official facility support.
6. Map every OSM node to the nearest active MATSim Car-network node. A match
   within 40 m can contribute incoming-link control candidates.
7. Cluster official primary `S#`/`P#` symbol points that remain more than 30 m
   from all OSM signal nodes. These are written to a separate TD-only review
   table, not automatically added to the canonical registry.

The default choices are supported by a nine-cell sensitivity table. Across
35/45/55 m attachment and 30/35/40 m residual clustering, the OSM-derived
junction count ranges from 2,007 to 2,162. The chosen conservative combination
produces 2,054 groups without using the 2,028 benchmark as a fitting target.

## Result

The v1 registry contains **2,054 physical signal-location groups**:

- 1,969 have both OSM and official Transport Department facility evidence;
- 85 are OSM-only and remain visible for review;
- 1,835 are high confidence, 107 medium confidence and 112 review status;
- 1,766 distinct normalized controller references become 1,778 spatial
  components because 11 repeated references split into distant components;
- 276 residual groups come from unreferenced OSM observations;
- 8,288 candidate incoming MATSim Car links cover 2,016 registry groups.

Of the 5,540 OSM signal nodes, 5,383 (97.17%) are within 30 m of an official
traffic-light point. The median nearest distance is 5.029 m, the 95th
percentile is 15.490 m, and 5,479 nodes (98.90%) are within 40 m of an active
MATSim Car-network node.

The registry exceeds the mid-2025 official aggregate by 26 locations, or
1.282%. This is small enough to support the interpretation that 5,540 is a
facility/approach count rather than a junction count. The remaining difference
must not be “corrected” mechanically: source dates differ, OSM may include
signalised pedestrian crossings or recent changes, and the official web total
is an aggregate rather than a spatial inventory.

The official-only audit contains 263 geometry clusters. A mechanical geometry
and road-proximity gate accepts 172 for manual review, but none is promoted by
default because the official point layer has no controller/junction identifier.
This prevents distant equipment belonging to an already represented large
junction from being double-counted.

## Outputs

The generated directory is ignored by Git and is rebuilt locally:

```text
data/transit/hongkong/processed/hong_kong_traffic_signal_registry_2026_v1/
```

Key files are:

- `hong_kong_signal_junctions.csv` and `.geojson`: canonical location registry;
- `osm_traffic_signal_nodes.csv`: all 5,540 OSM nodes with normalized reference,
  official match, group and MATSim-node mapping;
- `td_traffic_light_points.csv`: all 37,167 official facility points with OSM
  and registry assignments;
- `signal_controlled_link_candidates.csv`: incoming MATSim Car-link candidates;
- `junctions_without_controlled_link_candidates.csv`: 38 groups requiring
  topology or mode-layer review before MATSim adoption;
- `td_geometry_only_candidates.csv`: excluded official-only review clusters;
- `reference_spatial_conflicts.csv`: repeated controller references whose
  geometry splits beyond 90 m;
- `grouping_sensitivity.csv`: threshold sensitivity;
- `qa_summary.json`: counts, distance distributions, benchmark comparison and
  explicit limitations.

## Rebuild

Download or refresh the monthly official source:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\data_acquisition\download_hong_kong_traffic_signal_data.py
```

Build the fused registry:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_traffic_signal_registry.py
```

`--include-td-only` exists only for an explicit sensitivity build. It must not
be used for production adoption until the official-only candidates have been
manually reconciled with controller identities and neighbouring registry
groups.

## MATSim adoption boundary

This v1 product can support selection of signal systems and candidate
controlled incoming links. It cannot yet supply a valid MATSim signal-control
plan. Before enabling signals in QSim, the next stage must define and validate
movement groups, conflicting turns, pedestrian phases, cycle time, green
splits, amber/all-red intervals and time-of-day plans. Any temporary fixed-time
proxy must be explicitly labelled inferred and tested separately from the
location registry.

The revised implementation and validation design is documented in
`docs/HONG_KONG_TRAFFIC_SIGNAL_MATSIM_ADOPTION_DESIGN.md`. It requires
movement-level `fromLink -> toLink` control, conflict and pedestrian-clearance
logic, evidence-classed time-of-day plans, and an approach-capacity audit
before any registry group is activated. The eight-junction public timing
example is retained as an observed-partial pilot; its stage durations are not
treated as pure green times or generalized into a Hong Kong-wide default.

The subsequent territory-wide Stage-1 candidate is documented in
`docs/HONG_KONG_TRAFFIC_SIGNAL_TPDM_PROXY_V3.md`. It uses this unchanged
2,054-group universe to recover physical movements, planned 15-minute demand
`q`, observed approach-flow comparisons, and separately calculated
approach-level TPDM saturation flow `S`. Its status is
`territory_wide_tpdm_proxy_stage1_candidate_not_adopted`; it creates or
activates no signal stages, timing plans, controllers, or MATSim signal XML.
