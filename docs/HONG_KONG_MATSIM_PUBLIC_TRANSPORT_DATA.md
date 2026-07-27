# Hong Kong MATSim public-transport data

## Purpose

This workflow uses the interfaces listed in
`data/transit/hongkong/raw/source_tables/hk_public_transport_api_catalog.csv`
to supplement the
existing Transport Department GTFS, route/fare MDB files, and MTR route lists.
Formal downloaded products are stored in:

```text
data/transit/hongkong/API_Supplements/
```

The downloader is:

```text
scripts/hong_kong_single_city/data_acquisition/download_hong_kong_public_transport_api_data.py
```

## Important geometry distinction

The Transport Department routes-and-fares files named `JSON_BUS.json` and
`JSON_GMB.json` are GeoJSON, but their features are en-route stop `Point`
records. They are not bus trajectories. They remain useful for route IDs,
stop order, names, fares, journey time, and WGS84 stop coordinates.

Actual route polylines come from two CSDI ArcGIS FeatureServer layers:

- `FB_ROUTE_LINE`: franchised bus routes.
- `GMB_ROUTE_LINE`: green minibus routes.

The downloader retrieves these layers in stable `OBJECTID` pages and writes
WGS84 GeoJSON. CSDI's full franchised-bus GeoJSON is about 1.55 GB because its
road vertices are extremely dense. The saved research layer uses a
`0.00001`-degree, approximately 1.1 m, server-side simplification and six
decimal places. This retains road-level geometry while reducing the file to
about 26 MB.

## Downloaded products

```text
API_Supplements/
  geometry/
    franchised_bus_routes.geojson
    green_minibus_routes.geojson
  static/
    routes_fares_route_stop_points/
    operator/
  normalized/
    gmb_headways.csv
    route_geometry_coverage.csv
  realtime_snapshots/<UTC timestamp>/
    mtr_next_train.jsonl
    light_rail_next_train.jsonl
  metadata/
    hk_public_transport_api_catalog.csv
    download_manifest.csv
    api_supplement_summary.json
```

Current QA results:

| Product | Result |
|---|---:|
| Franchised-bus CSDI polylines | 2,251 route patterns |
| GMB CSDI polylines | 1,160 route patterns |
| Bus route-stop Point records | 56,056 records / 2,358 patterns |
| GMB route-stop Point records | 13,100 records / 1,161 patterns |
| GMB route details requested | 569 route codes |
| GMB route variants | 778 |
| GMB directions | 1,161 |
| GMB headway periods | 4,888 |
| MTR next-train snapshot | 120/120 line-station requests succeeded |
| Light Rail next-train snapshot | 68/68 stations succeeded |

The CSDI bus geometry matches 2,246 of 2,358 current bus route-stop patterns,
or 95.25%. There are 112 route-stop patterns without matching CSDI geometry
and five CSDI geometries without current route-stop data. GMB geometry matches
1,160 of 1,161 patterns, or 99.91%; route pattern `2011556-1` is the one current
GMB pattern without geometry. The row-level audit is
`normalized/route_geometry_coverage.csv`.

## Commands

Full static download plus one railway real-time snapshot:

```powershell
.\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\data_acquisition\download_hong_kong_public_transport_api_data.py `
  --catalog F:\Matsim\matsim-example-project\data\transit\hongkong\raw\source_tables\hk_public_transport_api_catalog.csv `
  --data-root F:\Matsim\matsim-example-project\data `
  --skip-gtfs
```

`--skip-gtfs` is appropriate while the existing
`data/transit/hongkong/PublicTransportGTFS/gtfs.zip` is retained. Omit the flag
when a fresh GTFS snapshot is required.

Append only a new MTR and Light Rail snapshot without re-requesting static
operator data:

```powershell
.\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\data_acquisition\download_hong_kong_public_transport_api_data.py `
  --data-root F:\Matsim\matsim-example-project\data `
  --realtime-only
```

Rebuild route-geometry coverage and refresh all manifest hashes offline:

```powershell
.\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\data_acquisition\download_hong_kong_public_transport_api_data.py `
  --data-root F:\Matsim\matsim-example-project\data `
  --qa-only
```

## MATSim use

- Use `franchised_bus_routes.geojson` and `green_minibus_routes.geojson` as
  route-shape constraints when map-matching transit routes to the directed
  road network.
- Join CSDI geometry to route-stop data using `ROUTE_ID + ROUTE_SEQ`.
- Use `gmb_headways.csv` to create time-period service frequencies. Frequencies
  and `frequency_upper` are minutes, not departure timestamps.
- Use the existing headway GTFS for service calendars, stop sequences, fare
  metadata, and frequency-based departures for the modes it covers.
- Use railway next-train JSONL only as a timestamped observation for checking
  frequency, platform direction, and disruption status. It is not a daily
  schedule.
- For bus patterns without CSDI geometry, infer paths from ordered stops and
  the road network and retain an `inferred_geometry` flag. Do not label simple
  stop-to-stop chords as observed trajectories.

## Route-to-link map matching

The complete route-to-link workflow is:

```text
scripts/hong_kong_single_city/transit_supply/
  map_match_hong_kong_transit_routes.py
```

Run it from the project root:

```powershell
.\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\map_match_hong_kong_transit_routes.py
```

Road links are built from the Transport Department TNM `CENTERLINE` layer in
`EPSG:32650`. `TRAVEL_DIR=1` is treated as bidirectional and
`TRAVEL_DIR=3` as the digitized one-way direction. Active OSM `rail`,
`subway`, `light_rail`, and `tram` ways are extracted from the local Hong Kong
PBF. OSM route relations select and order the rail links for all 24 MTR and 22
Light Rail directions.

For buses and GMB, CSDI is the primary trajectory source. The QA-passed AMap
combined layer fills CSDI gaps. Nineteen remaining directions use ordered
official stops and shortest paths on the TNM graph; these are explicitly
labelled `ordered_official_stops`, not observed trajectories.

The v2 matcher samples road trajectories every 100 m and solves a candidate
sequence using dynamic programming. Candidate links are searched within 120 m,
then 250 m where needed. Normal route corridors are limited to 300 m; tunnel,
bridge, and cross-harbour sections may use an 800 m corridor. TNM direction is
strict in the first pass. Direction exceptions require continuous trajectory
and ordered-stop evidence, and topology connectors longer than 300 m are not
automatically accepted. Repeated links are penalized unless the source
trajectory and stop order demonstrate a repeated occurrence.

Stop QA has two independent distances:

- `coverage_distance_m`: shortest distance from an official stop to any link
  in the matched route.
- `assignment_distance_m`: distance to the final order-consistent route-link
  occurrence selected by dynamic programming.

Open routes require non-decreasing link occurrence indices. Circular routes
may rotate the link sequence and wrap at most once. GMB 69A is extended from
the final trajectory-supported segment to Wong Chuk Hang using ordered stops
and legal TNM links; it remains in manual review because the extended path does
not yet pass all bidirectional geometry-distance thresholds.

The no-ferry base outputs are under:

```text
data/transit/hongkong/processed/transit_route_link_mapmatching_2026_v2/
  network/hong_kong_transit_base_network.xml.gz
  route_link_sequences.csv
  stop_link_snaps.csv
  route_map_matching_qa.csv
  route_link_continuity_errors.csv
  accepted_routes.csv
  needs_manual_review.csv
  map_matching_v1_v2_comparison.csv
  matched_route_geometries_wgs84.geojson
  inferred_ordered_stop_routes_wgs84.geojson
  map_matching_preview.png
  map_matching_summary.json
  SHA256SUMS.txt
```

Final v2 QA covers 3,570 route directions: 2,363 bus, 1,161 GMB, 24 MTR, and
22 Light Rail. All directions have route-link output, all 554,617 sequence rows
reference links in the MATSim network, and the adjacent-link continuity error
count is zero. The resulting network contains 80,051 nodes and 116,871 links.

The v1 high-length-ratio queue falls from 58 road directions to 3, and no
accepted v2 road direction has a reference-length ratio above 1.5. All 145 old
`partial_external` directions have official-stop coverage within 250 m in v2;
142 pass all acceptance criteria, while 3 remain under review for other QA
reasons. The stricter v2 coverage test identifies 48 different route
directions with at least one official stop farther than 250 m from the matched
route. These are retained as real coverage candidates rather than being mixed
with the old stop-order assignment warnings.

Automatic acceptance requires a reference-length ratio no greater than 1.5,
`source_to_matched_p95_m <= 50`, `matched_to_source_p95_m <= 100`, all official
stops within 250 m, no disconnected link gaps, ordered stop assignment, no
more than 5 percent repeated-link length for non-circular routes, and no
connector longer than 300 m. The complete run accepts 3,441 directions and
retains 129 in `needs_manual_review.csv`. The accepted and review files, rather
than the presence of a route-link sequence alone, determine which routes may
feed a later MATSim schedule.

`matched_to_trajectory_length_ratio` uses the service-trace reference after
ordered-stop reconstruction where the raw CSDI geometry overlaps or repeats.
`matched_to_raw_source_length_ratio` preserves the unmodified source-geometry
comparison for audit and is not used by itself to accept a route.

Generate the repair and manual-review maps with:

```powershell
.\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\analysis_visualization\visualize_hong_kong_transit_map_matching_anomalies.py
```

The v2 `qa_visualizations/` directory contains the v1/v2 comparison, remaining
review overview and ranking, accepted repair overview, a seven-page route
atlas, a CSV inventory, and a JSON summary. The v1 directory without the `_v2`
suffix is retained only as the historical comparison baseline.

## User-approved routes and stop facilities

The remaining 129 manual-review directions were explicitly approved for model
assembly on 2026-07-22. This is an approval override, not a change to their
original map-matching measurements. The original `acceptance_status`, metrics,
and review reasons remain in the v2 QA files and are copied to the approved
route inventory for traceability.

Build the approved inventory and stop facilities with:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\prepare_hong_kong_transit_schedule_assembly_inputs.py `
  --data-root F:\Matsim\matsim-example-project\data
```

Formal outputs are under:

```text
data/transit/hongkong/processed/transit_schedule_assembly_inputs_2026/
  approved_route_directions.csv
  approved_route_link_sequences.csv
  transit_stop_facilities.csv
  route_stop_facility_assignments.csv
  stop_nearest_road_access_snaps.csv
  rail_station_nearest_road_access_snaps.csv
  rail_station_road_access_connectors.geojson
  schedule_assembly_input_qa.csv
  schedule_assembly_input_summary.json
  SHA256SUMS.txt
```

All 3,570 route directions are approved and all 69,841 stop occurrences have a
valid route-stop facility assignment. A physical stop may have more than one
facility where different route directions require different compatible links.
Bus and GMB facilities are projected onto the nearest compatible road link in
their route. MTR and Light Rail platform facilities remain on compatible rail
links; changing their `linkRefId` to a road link would invalidate the MATSim
transit route. Therefore every rail station also receives a separate nearest-
road access anchor and a straight access-connector geometry.

Every one of the 9,404 physical stops has a nearest-road record. Forty-four
stops are more than 250 m from the current TNM road layer, principally remote,
cross-border, or incompletely covered locations; they remain included under
the user approval, and their access distance is retained for downstream QA.
The largest nearest-road distance is about 882 m. These records must not be
interpreted as survey-grade pedestrian entrances.

## MATSim road and public-transport supply

The road and public-transport side of the typical-weekday scenario is assembled
with:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_matsim_road_pt_supply.py `
  --data-root F:\Matsim\matsim-example-project\data
```

Formal outputs are under:

```text
data/transit/hongkong/processed/matsim_road_pt_supply_2026_typical_weekday/
  network.xml.gz
  transitSchedule.xml.gz
  transitVehicles.xml.gz
  config-road-pt-template.xml
  road_departure_manifest.csv
  road_route_stop_offsets.csv
  road_service_generation_audit.csv
  rail_variant_route_audit.csv
  rail_variant_stop_facilities.csv
  departure_vehicle_assignments.csv
  endpoint_proxy_stop_audit.csv
  matsim_supply_qa.csv
  matsim_java_load_validation.txt
  matsim_road_pt_supply_summary.json
  SHA256SUMS.txt
```

The representative service date is Wednesday 2026-07-22. Bus and GMB service
is expanded from the local Transport Department GTFS `trips`, `frequencies`,
`calendar`, and `calendar_dates` tables. Of 3,524 road route directions, 3,415
use GTFS service and 109 use the documented mode fallback: 06:00-23:30 at a
15-minute bus or 12-minute GMB headway. Five approved CSDI directions have no
published route-stop JSON and no GTFS route; each receives two explicitly
labelled endpoint proxy stops so it can remain in the user-approved schedule.

Road stop offsets use the map-matched route distance, 7.0 m/s bus or 8.0 m/s
GMB operating speed, and 20/15 second intermediate dwell assumptions. MTR and
Light Rail use the published-frequency and three-snapshot departure estimates
plus inferred station offsets. Reverse, branch, short, and loop variants are
rebuilt against the rail network; three reverse relation-gap connector links
are added only where needed by those services.

The no-ferry base supply contains 80,051 nodes, 116,874 links, 12,868 facilities,
2,413 transit lines, 3,574 transit routes, 158,131 departures, 25 vehicle
types, and 158,131 vehicle instances. MATSim 2026.0 successfully loads all
three core XML files. Python QA reports zero missing references, route-link
continuity errors, mode/link errors, facility-route errors, vehicle-reference
errors, or duplicate departure IDs.

`config-road-pt-template.xml` intentionally points to
`REPLACE_WITH_HONG_KONG_PLANS.xml.gz`. It is an integration template rather
than a runnable demand scenario until the population-plan stage is complete.

## Base-supply gaps

The XML supply is loadable, but these operating details remain inferred or
unavailable:

1. Tram and high-speed-rail routes are not included. Ferry is added only in
   the active Ferry Core v1 supply below.
2. Transfer pathways and minimum transfer times inside stations/interchanges.
3. Route/departure-specific bus models, MTR fleet variants, and Light Rail
   one-car/two-car consist assignments.
4. Vehicle blocks, depot pull-outs, terminal layovers, reuse, and interlining.
5. Capacity data for cross-boundary coaches, Discovery Bay, Park Island, and
   routes whose operator code is absent.

The current vehicle file therefore uses one vehicle instance per departure.
Population `plans.xml.gz` and demand-mode assignment are intentionally deferred
to the next workflow stage.

## Ferry Core v1

The base supply above remains unchanged. A separate Ferry Core v1 supply adds
the official representative-weekday services whose active stops can connect to
the existing fixed-link land network:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_ferry_core_supply.py `
  --project-root F:\Matsim\matsim-example-project
```

Formal output:

```text
data/transit/hongkong/processed/
  matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_ferry_core_v1_cap010/
```

For `2026-07-22`, the GTFS contains 41 active ferry routes. Twenty-one satisfy
the core rule that every active stop lies within 1,200 m of a current road
node; the other 20 remain excluded until their island-side walking and road
access is represented. The accepted routes produce 39 stop patterns, 1,836
departures, 87 route-specific stop facilities, 1,154 water nodes, and 1,115
water links.

All 48 core sailing segments use matched OSM ferry relations or ferry ways.
There are no direct-line fallbacks and no accepted fallback crossing more than
200 m of fixed-link land. Ferry water and platform links allow only `ferry`;
they do not alter road speed, road capacity, or bus/GMB traffic.

The resulting 5% supply contains 81,205 nodes, 117,989 links, 82,822 transit
facilities, 2,434 lines, 3,613 routes, and 159,967 departures. MATSim 2026
loads the network, schedule, and vehicles successfully. Route continuity,
mode/link compatibility, stop/link references, departure/vehicle references,
and vehicle/type references all have zero errors.

All 25 existing public-transport vehicle types are regenerated from the
full-scale capacity reference at 10%, rather than doubled from previously
rounded 5% values. Three ferry types are instantiated: 48 passengers for the
Star Ferry fleet-average proxy, 30 for the Sun Ferry proxy, and 20 for other
core services. The mapping reserves 40 passengers for HKKF catamarans, but the
HKKF island routes do not pass the Core v1 land-access rule and therefore do
not instantiate that type. Bus/GMB road PCUs remain at the separate 5% factors
of `0.125/0.075`. These ferry values should be treated as capacity sensitivity
assumptions, not route-specific vessel rosters.

The accompanying fixed-link plans audit found no internal activity on an
excluded island. All 3,063 outside-boundary activities are explicit
cross-border activities at `border_8` and are retained. The 1,168 agents whose
source mode is `ferry` or `ferry_vessel` have internal destinations inside the
model boundary and can use Ferry Core when their `pt` routes are replanned.

## AMap supplementary collection

The Hong Kong AMap workflow follows the earlier Fuzhou approach but uses the
official Hong Kong inventory as its discovery source. It does not attempt to
enumerate an entire city using arbitrary numeric keywords.

```text
scripts/hong_kong_single_city/data_acquisition/fetch_hong_kong_transit_from_amap.py
```

The current official target inventory contains 159 direction-level targets:

| Mode | Targets | Reason |
|---|---:|---|
| Bus | 112 | Current route-stop pattern has no matching CSDI geometry |
| GMB | 1 | Route pattern `2011556-1` has no matching CSDI geometry |
| MTR | 24 | Ten lines, including East Rail and Tseung Kwan O branch directions |
| Light Rail | 22 | Eleven route numbers in both directions |

The prepared target and query files are stored under:

```text
data/transit/hongkong/AMap_Supplements/targets/
  official_missing_targets.csv
  amap_query_targets.csv
```

There are 351 target-keyword rows and 166 unique keywords. Bus and GMB targets
retain official route IDs, route sequence, stop count, station sequence, and
WGS84 origin/destination coordinates. MTR and Light Rail targets retain the
official line code, direction, and station-name sequence.

Prepare or refresh the target inventory without making an API request:

```powershell
.\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\data_acquisition\fetch_hong_kong_transit_from_amap.py `
  --data-root F:\Matsim\matsim-example-project\data `
  --prepare-only
```

Set a Web Service key for the current PowerShell session, then collect:

```powershell
$env:AMAP_WEB_KEY="<AMap Web Service key>"

.\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\data_acquisition\fetch_hong_kong_transit_from_amap.py `
  --data-root F:\Matsim\matsim-example-project\data
```

For Codex-driven collection on Windows, store it in the current user's
environment so newly launched tools can read it without placing it in a command
line:

```powershell
[Environment]::SetEnvironmentVariable(
  "AMAP_WEB_KEY",
  "<AMap Web Service key>",
  "User"
)
```

The collector checks the process environment first and then the Windows user
environment. It never prints the key.

The key is never written to raw responses, normalized outputs, errors, or the
manifest. Responses are cached by a SHA256-derived keyword filename, so an
interrupted run can resume without spending the quota again. Use `--refresh`
only when a deliberate API refresh is required.

Expected collected outputs include:

```text
AMap_Supplements/
  raw/by_keyword/
  normalized/amap_lines.csv
  normalized/amap_stops_by_line.csv
  normalized/amap_stations.csv
  normalized/amap_service_frequency.csv
  geometry/amap_line_trajectories_gcj02.geojson
  geometry/amap_line_trajectories_wgs84.geojson
  geometry/amap_official_target_matches_wgs84.geojson
  matches/official_amap_route_matches.csv
  matches/unmatched_or_low_confidence_targets.csv
  metadata/amap_fetch_summary.json
  metadata/amap_api_errors.json
  metadata/amap_download_manifest.csv
```

AMap candidate matching uses route name, mode, official station-name overlap,
stop-count similarity, and, for bus/GMB, WGS84 endpoint distance. Only
mode-compatible candidates above the acceptance threshold enter the matched
geometry layer. Lower-scoring results remain in the audit CSV.

AMap returns GCJ-02 coordinates. The workflow retains a GCJ-02 trajectory
layer and generates a separate WGS84 layer using iterative conversion. AMap
operating times, fares, status, company, station order, distance, and parseable
`timedesc` periods are supplementary attributes, not replacements for official
Hong Kong schedules or fare data.

### Targeted stop-ID completion

The line-name run left 28 nominally unmatched targets: one Citybus E18 pattern
and 27 cross-boundary coach patterns. The nominally accepted GMB target was not
part of this query set and was later rejected by spatial QA. The 28 targets'
official stop names, sequences,
and coordinates are already known, so the completion workflow does not repeat
a citywide POI search:

```text
scripts/hong_kong_single_city/data_acquisition/
  fetch_hong_kong_transit_via_amap_stop_ids.py
```

It extracts 169 official stop occurrences and deduplicates them to 55
name-coordinate stops with 52 distinct Chinese names. Each stop is queried by
`place/around` within 300 m using type `150700`; `place/text` is used only when
the around response has no reliable name-distance candidate. Up to three POI
IDs per official stop then feed `bus/stopid`, and evidence-filtered line IDs
feed `bus/lineid?extensions=all`. No `place/polygon`, tile, or fixed-link
boundary clipping is used, so the Huanggang-side stops remain eligible.

Prepare the targeted inventory without API calls, run the resumable collection,
or rebuild matching from cached responses:

```powershell
.\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\data_acquisition\fetch_hong_kong_transit_via_amap_stop_ids.py `
  --data-root F:\Matsim\matsim-example-project\data `
  --stage prepare

$env:AMAP_WEB_KEY="<AMap Web Service key>"
.\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\data_acquisition\fetch_hong_kong_transit_via_amap_stop_ids.py `
  --data-root F:\Matsim\matsim-example-project\data

.\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\data_acquisition\fetch_hong_kong_transit_via_amap_stop_ids.py `
  --data-root F:\Matsim\matsim-example-project\data `
  --stage match
```

Formal outputs are under:

```text
data/transit/hongkong/AMap_Targeted_StopID_Supplements/
  targets/targeted_official_stop_occurrences.csv
  targets/targeted_unique_official_stops.csv
  targets/amap_stop_poi_candidates.csv
  targets/amap_selected_stop_pois.csv
  normalized/amap_stop_to_lines.csv
  normalized/amap_lineid_candidates.csv
  matches/targeted_remaining_route_matches.csv
  matches/historical_linename_spatial_qa.csv
  matches/combined_official_target_matches.csv
  geometry/amap_official_target_matches_combined_wgs84.geojson
  metadata/amap_targeted_stopid_summary.json
  metadata/amap_targeted_stopid_manifest.csv
```

The completed run used 93 place requests, 136 stop-ID requests, and 543
evidence-filtered line-ID requests. It added 13 cross-boundary targets. Spatial
QA also found four false positives in the earlier line-name output: both
Citybus 73X directions had matched a KMB 73X, E28 had matched a Shenzhen E28,
and GMB 117B had matched a Zhuji 117B. The raw historical and unfiltered merged
files remain available for audit, but the QA-passed combined layer contains
140 of 159 targets. Nineteen targets remain unmatched; no straight-line or
synthetic trajectory is substituted.

`data/transit/hongkong/AMap_StopID_Supplements/` contains the interrupted
citywide polygon experiment. It is diagnostic only and must not be used by the
MATSim supply workflow.

## Approximate MTR and Light Rail weekday timetable

The inferred timetable combines the published average-frequency table with two
independent MTR and Light Rail next-train snapshots:

- `20260720T102416Z` (18:24 Hong Kong time) selects evening-peak headways.
- `20260722T034716Z` (11:47 Hong Kong time) selects non-peak headways.
- Morning-peak headways use the midpoint of each published range because no
  morning snapshot is available.

Every snapshot estimate is constrained to the corresponding published range.
Single published values remain exact. For dual values, the option closest to
the snapshot is selected. Missing snapshot observations do not override the
published table. KTL and TCL common-section short turns are derived from the
difference between common-section and full-route frequencies. East Rail and
Tseung Kwan O branch frequencies are jointly balanced so their combined
common-section service remains consistent with the published target.

Run:

```powershell
.\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_mtr_lrt_approximate_timetable.py `
  --frequency-table F:\Matsim\matsim-example-project\data\transit\hongkong\raw\source_tables\mtr_average_train_frequency_long.csv `
  --snapshot-dir F:\Matsim\matsim-example-project\data\transit\hongkong\API_Supplements\realtime_snapshots\20260720T102416Z `
  --snapshot-dir F:\Matsim\matsim-example-project\data\transit\hongkong\API_Supplements\realtime_snapshots\20260722T034716Z `
  --output-dir F:\Matsim\matsim-example-project\data\transit\hongkong\processed\mtr_lrt_approximate_timetable_2026_weekday
```

Formal outputs are under:

```text
data/transit/hongkong/processed/mtr_lrt_approximate_timetable_2026_weekday/
  approximate_route_patterns.csv
  approximate_route_stops.csv
  approximate_service_periods.csv
  common_section_frequency_validation.csv
  approximate_origin_departures.csv
  snapshot_observed_headways.csv
  snapshot_timetable_validation.csv
  approximate_headway_qa.png
  approximate_timetable_summary.json
  SHA256SUMS.txt
```

The current build contains 50 directional route patterns and 7,461 inferred
origin departures. It has 30 MTR patterns and 20 Light Rail patterns, including
explicit MTR branch and common-section variants. All 136 directly constrained
active route-period headways remain inside their published bounds. Eight KTL
and TCL supplemental short-turn periods are rate differences derived from the
published common-section and full-route services, so the common-section range
is not misapplied as their individual bound. The largest common-section target
residual is 0.167 minutes (10 seconds), and the nearest generated departure has
a snapshot MAE of about 0.32 minutes and a 95th-percentile error of about 1.90
minutes. The maximum individual nearest-departure error is 4.03 minutes on an
East Rail branch observation; it is retained in the audit rather than hidden.

This is a typical-weekday frequency realization, not an official full-day
timetable. It provides service windows, origin departure times, and ordered
stops. The station timing workflow below supplies the corresponding approximate
running-time and dwell-time offsets.

## MATSim station running and dwell offsets

The station timing estimator uses three snapshots at Hong Kong local times
18:24, 11:47, and 13:53. For each route pattern and adjacent station pair, it
matches ordered next-train predictions by line, destination, station order,
and a distance-based elapsed-time prior. It then fits line-specific speeds and
shrinks minute-rounded snapshot observations toward the physical model.

Rail-link distance is used only when it passes a station-coordinate circuity
check. This prevents anomalous OSM relation ordering from creating implausible
inter-station distances. Other segments use official station coordinates and
a line-specific circuity factor inferred from reliable link segments. Three
consecutive duplicate source stops were removed while retaining non-consecutive
revisits used by real circular services.

Run:

```powershell
.\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_mtr_lrt_station_offsets.py `
  --transit-root F:\Matsim\matsim-example-project\data\transit\hongkong `
  --snapshot-dir F:\Matsim\matsim-example-project\data\transit\hongkong\API_Supplements\realtime_snapshots\20260720T102416Z `
  --snapshot-dir F:\Matsim\matsim-example-project\data\transit\hongkong\API_Supplements\realtime_snapshots\20260722T034716Z `
  --snapshot-dir F:\Matsim\matsim-example-project\data\transit\hongkong\API_Supplements\realtime_snapshots\20260722T055352Z
```

Formal outputs are under:

```text
data/transit/hongkong/processed/mtr_lrt_approximate_station_times_2026_weekday/
  snapshot_adjacent_station_observations.csv
  line_speed_parameters.csv
  line_distance_parameters.csv
  adjacent_station_time_estimates.csv
  matsim_route_stop_offsets.csv
  route_runtime_summary.csv
  mapmatched_distance_alignment_qa.csv
  station_coordinate_coverage_qa.csv
  station_timing_qa.png
  station_timing_summary.json
  SHA256SUMS.txt
```

The build covers 50 route patterns, 701 route-stop offsets, and 651 adjacent
route segments. Snapshot evidence covers 607 segments, including 585 observed
in all three snapshots. Confidence is high for 265 segments, medium for 342,
and low for 44 model-filled segments. No segment uses a mode-wide median
distance fallback.

Dwell time is not independently identifiable from the public APIs. The formal
priors are 30 seconds at ordinary MTR stations, 45 seconds at MTR interchanges,
20 seconds at ordinary Light Rail stops, and 30 seconds at major Light Rail
interchanges. Route origins and destinations use zero profile dwell; terminal
turnaround is deferred to vehicle block scheduling. The resulting cumulative
`arrival_offset` and `departure_offset` columns are ready to populate MATSim
`transitRouteStop` records but are not an official MTR operating timetable.

## Vehicle capacities and MATSim vehicle types

The capacity integration workflow reads the supplied 169-row vehicle catalog,
retains its original evidence, and converts only valid per-vehicle/per-car
records into model capacities:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_transit_vehicle_types.py `
  --capacity-csv F:\Matsim\matsim-example-project\data\transit\hongkong\raw\source_tables\hong_kong_public_transport_vehicle_capacity.csv `
  --data-root F:\Matsim\matsim-example-project\data
```

Three rows are deliberately excluded as individual passenger vehicles: the
Airport Express luggage car, a non-passenger tram maintenance car, and the
Star Ferry whole-fleet total. The remaining 166 records are retained in the
normalized catalog. Forty-five rows provide exact seats and standing places;
121 provide only total capacity and therefore carry an explicit provisional
seat/standing method.

Heavy-rail car capacities are combined into line-level whole-train types. The
model uses 8-car urban/Tung Chung/Airport Express trains, 3-car South Island,
4-car Disneyland Resort, 9-car East Rail, and 8-car Tuen Ma formations. These
formations and their evidence are recorded in `matsim_vehicle_types.csv`; the
actual fleet variant used by a particular departure remains unknown. Airport
Express correctly includes one zero-passenger luggage car in its eight-car
formation.

Formal outputs are under:

```text
data/transit/hongkong/processed/public_transport_vehicle_capacities_2025/
  source/hong_kong_public_transport_vehicle_capacity.csv
  normalized_vehicle_capacity_records.csv
  matsim_vehicle_types.csv
  route_vehicle_type_assignments.csv
  mtr_lrt_pattern_vehicle_type_assignments.csv
  mtr_lrt_departure_vehicle_assignments.csv
  transitVehicleTypes.xml.gz
  mtr_lrt_transitVehicles_approximate.xml.gz
  remaining_vehicle_data_gaps.csv
  vehicle_capacity_qa.csv
  vehicle_capacity_integration_summary.json
  SHA256SUMS.txt
```

The current catalog creates 19 representative MATSim types. Capacity is mapped
to 3,507 of 3,570 route directions; the 63 uncovered directions are 27 `XB`,
18 `DB`, 13 `PI`, and five routes without an operator code. All 50 approximate
MTR/Light Rail patterns and 7,461 departures receive a type. Light Rail uses a
one-car default, while a two-car type is retained as an alternative. The rail
vehicle XML creates one unique vehicle per departure so it is immediately
referenceable by a schedule, but it must not be interpreted as a physical
fleet count. Vehicle blocking and reuse remain a later operation.

The source table does not provide vehicle length, width, access/egress rate,
door operation, or PCE. The XML uses documented mode-level provisional values.
`remaining_vehicle_data_gaps.csv` is the authoritative correction queue for
these physical parameters, route allocation, seat/standing splits, ferry
vessels, accessibility, and scenario-year fleet updates.

### Complete inferred allocation

When no further vehicle data are available, the recommended MATSim base case
is generated with `--complete-inference`. It preserves the evidence catalog
above and replaces every remaining null capacity with a documented proxy:

- `XB`: fleet-weighted capacity of all 291 single-deck buses in the supplied
  catalog, rounded to 70 and treated as seated-only coach capacity.
- `DB`: the NLB island/exurban fleet proxy, 55 seats plus 35 standing places.
- `PI`: the all-operator single-deck proxy, 38 seats plus 32 standing places.
- Five stale/manual-review routes without an operator: the all-bus fleet proxy,
  84 seats plus 45 standing places.

The Tuen Ma Line source car counts form two internally consistent fleets:
48 higher-capacity 8-car trains at 2,652 passengers and 17 lower-capacity
8-car trains at 2,586 passengers. Departures are systematically interleaved in
that 48:17 ratio instead of all receiving the 2,635 weighted mean.

For Light Rail, the snapshots at 2026-07-20 18:24, 2026-07-22 11:47, and
2026-07-22 13:53 Hong Kong time contain 1,652 station-level predictions with a
one/two-car field. Evening and non-peak departures use their direct line-period
shares; morning peak uses the same line's pooled three-snapshot share because
there is no morning snapshot. The observations are station-prediction weighted,
so one physical train may occur at several stations. The resulting deterministic
base case assigns 541 of 2,091 Light Rail departures to one car and 1,550 to
two cars. The largest target-share rounding error is about 1.27 percentage
points.

Run:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_transit_vehicle_types.py `
  --capacity-csv F:\Matsim\matsim-example-project\data\transit\hongkong\raw\source_tables\hong_kong_public_transport_vehicle_capacity.csv `
  --data-root F:\Matsim\matsim-example-project\data `
  --complete-inference
```

The complete output is under
`data/transit/hongkong/processed/public_transport_vehicle_capacities_inferred_2026/`.
It contains 25 MATSim vehicle types, complete capacity assignments for all
3,570 route directions, complete type assignments for 7,461 rail departures,
`lrt_snapshot_consist_evidence.csv`, and route/departure allocation summaries.
This is the final existing-data estimate. Confidence flags should be used for
sensitivity analysis, but null vehicle capacities no longer remain.

## Provenance and integrity

`metadata/download_manifest.csv` records source URL, download timestamp, byte
size, and SHA256 for each retained file. `--qa-only` recomputes all hashes from
the current files. The official source pages are the Hong Kong Transport
Department [routes and fares dataset](https://data.gov.hk/en-data/dataset/hk-td-tis_23-routes-fares-geojson),
the CSDI [Bus Route dataset](https://portal.csdi.gov.hk/csdi-webpage/dataset/td_rcd_1638844988873_41214),
and the CSDI [Dataset API documentation](https://portal.csdi.gov.hk/csdi-webpage/doc/GeoSpatialServices/).
The supplementary line collector follows the official AMap
[bus information query documentation](https://lbs.amap.com/api/webservice/guide/api-advanced/bus-inquiry).

## Road-PT PCU scaling for the 5% scenario

The active Hong Kong scenario retains all bus and GMB services on the existing
mixed road network. Run:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_mixed_road_pt_pcu_scaled_supply.py `
  --data-root F:\Matsim\matsim-example-project\data `
  --pcu-factor 0.05
```

The complete timetable, road links, route sequences, stop references, passenger
capacities, and vehicle dimensions are unchanged. Only PCU is scaled: bus
types change from `2.5` to `0.125`, and GMB from `1.5` to `0.075`. Rail and
Light Rail types remain at their original values. The associated configs use
0.1 for both `flowCapacityFactor` and `storageCapacityFactor`.

The mixed network loads with 116,874 links, 3,574 routes, and 158,131
departures. QA confirms all 150,670 bus/GMB departure vehicles reference one
of the 12 scaled road-PT types, with no changes to non-road vehicle types. The
former dedicated-link supply is retained as a sensitivity alternative and is
not referenced by the active config.
