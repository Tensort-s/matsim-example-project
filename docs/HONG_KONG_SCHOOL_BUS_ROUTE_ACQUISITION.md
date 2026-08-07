# Hong Kong school-bus route acquisition and proxy preparation

## Status and scope

This work inventories school transport evidence and prepares a territory-wide
candidate supply for later modelling. It does **not** change the adopted Hong
Kong MATSim run, public-transport schedule, vehicle fleet, PCU calibration, or
the 9,626 existing `school_bus` legs. The generated product is
`proxy_not_adopted`: every generated route, pickup point, time, and geometry is
inferred rather than observed or licensed.

The acquisition boundary is deliberately narrow. Franchised buses, GMB, MTR,
Light Rail, tram, and ferry have already been collected and are not downloaded
again. A public route that happens to serve a school is still ordinary public
transport, not a school-bus route.

## Evidence vocabulary

| Class | Meaning | Permitted use here |
|---|---|---|
| `official_current` | Current government definition, register total, guidance, or location data | Constraint, definition, or inventory evidence |
| `official_historical_survey` | Official observation for an earlier survey year | Calibrated aggregate, with year retained |
| `first_party_current` | Route/service published by its school or operator for a current school year | Route-pattern sample, not territory-wide truth |
| `first_party_historical` | Earlier school/operator route publication | Historical calibration sample |
| `project_observed_and_processed` | Official/operator public-transport inputs already processed by this project | Exclusion pointer only |
| `inferred_proxy` | Model-generated demand, route, stop, time, geometry, capacity, or enrolment | Sensitivity and supply preparation only |

`official` in the source catalogue means a government source. A
`school_first_party` or `operator_first_party` document is authoritative for
that publisher's advertised service, but is not an official Hong Kong-wide
route register.

## Existing project data inventory

| Asset | Location | Classification | What it really supports | Critical limitation |
|---|---|---|---|---|
| EDB school location and information | `data/school/hongkong/SCH_LOC_EDB.csv` | Real, official, current catalogue snapshot | School names, types, addresses and coordinates | No school-bus routes; no official individual-school enrolment field |
| EDB/CSD school programme and aggregate tables, including `tab0103.xlsx` | `data/school/hongkong/` | Real official tables, source year retained | School/programme universe and aggregate margins | Not route observations |
| TCS 2022 HBS tables | `data/school/hongkong/tcs2022/` | Real official historical survey aggregates | Home-based-school trip ends, times and mode boardings | SPB is not school-bus-only and tables do not contain routes |
| TCS HBS SPB boarding constraint | `tcs2022_hbs_mode_boardings_appendix.csv` | Real aggregate converted by project | Official SPB boardings: 315,000; project main-mode-equivalent: 205,368.89708 daily two-way trips | TD footnote includes company, school, resident, tourist, shuttle and cross-boundary bus |
| 2021 Census education/transport tables 5.12 and 5.14 | C&SD Main Results | Real official historical aggregates | School-bus users by education level plus main/supplementary school-bus, residential-coach and other-mode counts | Cross-source share estimate; not a direct TCS SPB breakdown |
| DCCA student-school assignment parquet | `processed/student_school_od_2022/student_school_assignment_od.parquet` | Inferred/synthetic, official-constrained | 1,585-grid origins to 2,023 model campuses by stage | Not an observed household-to-school matrix |
| Campus capacity estimates | `school_campus_capacity_estimates.csv/.geojson` | Inferred/modelled | 800,761-ish expected students and destination constraints | `estimated_students` is not official school-level enrolment |
| Mode-specific `spb.npy` | student-school processed mode OD | Inferred/proxy constrained to TCS | Spatial allocation of aggregate HBS SPB demand | Not observed school-bus routes or passengers |
| 5% MATSim `school_bus` legs | active/candidate agent plans | Synthetic demand | 9,626 teleported legs, or 4,813 round-trip-equivalent students | No route, stop, operator, vehicle, or physical supply |
| School escort private-car pilot | taxi/no-ride candidate audit | Inferred candidate built from synthetic households | 139 paired students and 278 household-car passenger legs | Household private-car escort, not school bus |
| Existing bus/GMB route lines and GTFS/API tables | `data/transit/hongkong/` | Real official/operator data plus processed/inferred timetable details | Ordinary public transport supply | Explicitly excluded from this acquisition |
| Existing MATSim PT supply | active Ferry Core v1 supply directory | Processed production supply | Regular bus/GMB/rail/ferry network and schedules | Contains no school-bus operators or routes |

The parquet sum read from its stored numeric precision is 800,760.875 expected
students; previously published summaries computed upstream report
800,761.119571. This sub-person difference is retained as a numeric-precision
fact and is not corrected by overwriting source data.

## Source catalogue

The machine-readable catalogue is generated at:

```text
data/school/hongkong/raw/school_bus_route_sources_2026/source_catalog.csv
```

It records URL, title, provider, validity/publication information, access date,
coverage, evidence class, content class, official status, copyright/licence
restriction, local filename, SHA256, download state, and calibration use. The
access date for this release is 2026-08-06. `SOURCE_MANIFEST.csv` records hashes
for successfully downloaded files.

### Government and regulatory sources

| Source | Date/validity | Coverage and classification | Licence/use note |
|---|---|---|---|
| [TD non-franchised bus overview](https://www.td.gov.hk/en/transport_in_hong_kong/public_transport/non_franchised/index.html) | totals at 2025-12-31; accessed 2026-08-06 | Official Hong Kong totals; no A03 route table | Hong Kong Government copyright; cite for research |
| [TD non-franchised service descriptions](https://www.td.gov.hk/en/transport_in_hong_kong/public_transport/non_franchised/brief_description_of_nfb_services/index.html) | current page | Official definitions of A03 student service and B01 school/private-bus student service | Hong Kong Government copyright |
| [TD Passenger Service Licence application](https://www.td.gov.hk/en/transport_in_hong_kong/public_transport/non_franchised/application_for_passenger_service_licence_psl/index.html?print=1) | current page | Official licensing process; applications require operation/route particulars, but the page is not a public route register | Hong Kong Government copyright |
| [EDB school-bus safety](https://www.edb.gov.hk/en/student-parents/safety/sch-bus-services/index.html) | updated 2026-07 | Official service guidance, no route list | Hong Kong Government copyright |
| [EDB local vehicles for cross-boundary students](https://www.edb.gov.hk/en/student-parents/events-services/programs/localnannybus.html) | 2025/26 list valid to 2026-07; 2026/27 page | Operator/control-point list for Lok Ma Chau and Lo Wu; no stop timetable | Hong Kong Government copyright |
| [TCS 2022 Final Report](https://www.td.gov.hk/filemanager/en/content_5349/tcs2022_eng.pdf) and [appendix](https://www.td.gov.hk/filemanager/en/content_5349/tcs2022app_eng.pdf) | survey year 2022 | Official historical household travel aggregates and SPB definition | Hong Kong Government copyright |
| [2021 Population Census Main Results](https://www.censtatd.gov.hk/en/data/stat_report/product/B1120109/att/B11201092021XXXXB0100.pdf) | census year 2021 | Tables 5.12 and 5.14: full-time students by transport mode and education level | Hong Kong Government copyright |
| [EDB School Location and Information](https://data.gov.hk/en-data/dataset/hk-edb-schinfo-school-location-and-information/resource/cedc9c4f-3090-4700-8703-f544f1429d5d) | monthly; catalogue snapshot dated 2025-05-06 | Official schools/coordinates only | [DATA.GOV.HK terms](https://data.gov.hk/en/terms-and-conditions), attribution required |
| [2013 government reply on school-bus fleet](https://www.info.gov.hk/gia/general/201310/09/P201310090218.htm) | 2013 historical | Official historical fleet categories/counts, not current routes | Historical context only |

### School and operator first-party route samples

| Publisher/source | Date/validity | Coverage | Route content | Use restriction |
|---|---|---|---|---|
| [DGS/DGJS tender](https://www.dgs.edu.hk/api/file?id=1773200619983) | issued 2026-03-09; 2026-09-01–2029-08-31; route basis 2025/26 | 27 routes, about 509 subscribers | Exact ordered stops; max 61 seats | Tender limits disclosure. Internal aggregate calibration only; do not redistribute its route tables |
| [HKTA YYI No.3 Secondary](https://www.hktayy3.edu.hk/CustomPage/33/School_Bus_Route_2526v2.pdf) | 2025/26 | Sai Kung and east Kowloon to Tseung Kwan O | 2 routes, ordered stops, 35/45-minute morning runs | School copyright; no open licence stated |
| [Tsuen Wan Trade Association Primary](https://twtapsweb01.twtaps.edu.hk/twtapsweb/notes/2024-2025_notes/24-205%20Circular%20on%20the%20application%20for%20t%20aking%20school%20bus%20in%202025-2026.pdf) | 2025/26 | Tsing Yi/Kwai Chung/Tsuen Wan/Tsing Lung Tau | 5 broad route/stop-area groups and fares | School copyright; no open licence stated |
| [CCC Kung Lee College](https://www.cccklc.edu.hk/en/site/page?name=School+Bus+Services) | 2025/26 | Hong Kong Island to Tai Hang | 2 routes, 27/28 seats and pickup times | School copyright; no open licence stated |
| [Buddhist Fat Ho Memorial College](https://www.bfhmc.edu.hk/content.php?id=1003&lng=us-en) | published 2025-06-11; 2025/26 | Tung Chung and Mui Wo to Tai O | Pickup places for 2 routes | School site timed out during automated acquisition; URL retained |
| [Mary Rose School](https://www.mrs.edu.hk/cakecms/app/webroot/upload/schoollists/2940/2024-25%20school%20bus%20routes%20and%20fare_eng_original.pdf) | revised 2024-09-05; historical 2024/25 | Special-school routes across HK/Kowloon/NT | Route places and 19/27/28/50-seat examples | Historical school copyright; no open licence stated |
| [Ju Ching Chu Secondary (Tuen Mun)](https://www.jcctm.edu.hk/web/wp-content/uploads/%E5%AE%B6%E9%95%B7%E9%80%9A%E5%91%8A2025-2026_166_%E5%B1%AF%E9%96%80%E7%B7%9A%E6%A0%A1%E5%B7%B4%E7%AC%AC%E4%BA%8C%E9%9A%8E%E6%AE%B5%E7%94%B3%E8%AB%8B.pdf) | issued 2025-11-17; 2025-12–2026-02 | Queen's Hill/Fanling/Sheung Shui/Fu Tai to Tuen Mun | 1 long route, 06:45–08:00 | Certificate-chain failure during automated acquisition; URL retained |
| [Alliance Primary School, Whampoa](https://www.apsw.edu.hk/sites/default/files/files/2526xiao_ba_lu_xian__0.pdf) | 2025/26 | Kowloon and nearby districts | 5 numbered routes (1, 3, 5, 6, 7), visual inbound/outbound stop sequences, no times | School copyright; no open licence stated |
| [ELCHK Lutheran Academy](https://www.fls.edu.hk/%E6%A0%A1%E8%BB%8A/) | 2025/26 | New Territories | Operator and 9 pickup locations | School copyright; no open licence stated |
| [Kwoon Chung / ISF schedule](https://school.kcm.com.hk/ors/download/25-26%20ISF_RT.pdf) | tentative 2025/26 | Multiple ISF corridors | 22 proposed inbound route IDs with operator-published stops and times | Operator copyright; tentative and demand-dependent |

Service pages that give only operators or broad service areas, such as the
[PLK Camões page](https://www.plkctslps.edu.hk/en/content.php?wid=103), are
classified `school_transport_service_no_route`; they are not silently promoted
to actual routes. EDB cross-boundary operator/control-point lists are
`school_or_stop_list_only` for the same reason.

## Proxy construction

The reproducible builder is:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_school_bus_proxy_routes.py `
  --input-root F:\Matsim\matsim-example-project\data `
  --output-dir .\data\school\hongkong\processed\school_bus_proxy_routes_2026_v3_school_probability_locked76 `
  --assumptions .\cities\hongkong\school_bus_proxy_assumptions.yaml `
  --locked-routes .\cities\hongkong\school_bus_first_party_locked_routes.csv
```

The method is intentionally transparent:

1. Begin with the TCS HBS SPB main-mode-equivalent daily two-way trips
   (205,368.89708). Estimate the non-tertiary school-bus share as 81.90069599%
   from 2021 Census tables 5.12 and 5.14. The boarding-compatible denominator
   combines main and supplementary school-bus, residential-coach and `other`
   counts; the post-secondary share observed among main-mode school-bus users
   is applied to total school-bus users. This deliberately excludes all
   residential-coach and Census `other` users from school-bus demand.
2. Divide by two and apply that share to obtain exactly 84,099 integer
   round-trip-equivalent non-tertiary school-bus passengers. The YAML target is
   validated against this formula at runtime.
3. Calculate a school-level probability from dominant stage, funding-sector
   proxy, nearest MTR distance and estimated enrolment. Base probabilities are
   0.60 kindergarten, 0.90 primary, 0.28 secondary and 0.85 special. DSS and
   other-private schools receive +0.15; MTR distance adds 0.00 to 0.18; large
   campuses add 0.05 and very small non-special campuses subtract 0.08. Values
   are clipped to 0.05-0.98 and compared with a SHA256-based deterministic
   campus draw. These are scenario assumptions, not observed school contracts
   or audited budgets.
4. Force every campus represented by the first-party inventory to have
   service. The inventory locks exactly 76 route identities across nine source
   groups: DGS/DGJS 27, ISF 22, Mary Rose 10, Alliance Whampoa 5, Tsuen Wan
   Trade Association Primary 5, HKTA YYI No.3 2, CCC Kung Lee 2, Buddhist Fat
   Ho 2 and Ju Ching Chu Tuen Mun 1. Of these, 10 Mary Rose routes are 2024/25
   historical evidence; DGS is summary-only and ISF is proposed/tentative.
5. Weight the selected campuses' assignment rows by Census-consistent stage
   propensity (kindergarten 0.1870, primary 0.2264, secondary 0.0401 and
   special 0.20), then use deterministic largest remainders with at least one
   passenger per selected campus. This conserves 84,099 exactly while allowing
   non-selected campuses to remain at zero.
6. Assign inferred loads to locked routes first, limited by their public or
   proxy capacity. Subtract those loads from the corresponding campus demand.
   Restricted or undigitised first-party route stops and geometry are left
   null; route identity is not misrepresented as a digitised observed path.
7. Generate proxy routes only from the remaining demand at selected campuses.
8. Represent each proxy pickup by the occupied origin grid's representative point.
   It is not an observed kerbside stop.
9. Cluster proxy pickups per campus with a deterministic angular sweep and a maximum
   proxy load of 50 students. Sampled vehicle sizes support 19, 28, and 50-seat
   capacity classes. The DGS 61-seat tender maximum is evidence but is not used
   because its document has redistribution restrictions.
10. Order inbound pickups far-to-near, then join them to the school with an
   unrouted straight line in EPSG:32650. A 1.25 circuity factor, 25.2 km/h
   average speed, and 45 seconds per pickup produce an inferred runtime clipped
   to the observed sample envelope of 15–75 minutes.
11. Back-calculate morning times from a 07:55 school arrival. Return-departure
   assumptions are 12:30 kindergarten, 15:30 primary, and 16:00
   secondary/special. These are scenario assumptions, not school timetables.
12. Flag proxy routes over 20 km school radius for manual review rather than deleting
   them. The existing assignment's 2.53 km median and 11.32 km p90 distances
   remain the main spatial context; public samples show that longer routes can
   occur.

## Release outputs and QA

The ignored, local data release is:

```text
data/school/hongkong/processed/school_bus_proxy_routes_2026_v3_school_probability_locked76/
```

| File | Purpose |
|---|---|
| `school_bus_proxy_routes.csv` | Route load, capacity, times, length/radius flags and provenance status |
| `school_bus_proxy_stops.csv` | Inferred origin-grid pickup points and loads |
| `school_bus_proxy_route_stop_times.csv` | Inferred morning pickup times |
| `school_bus_proxy_route_geometries.geojson` | WGS84 display geometry; straight-line and unrouted |
| `school_bus_school_probabilities.csv` | School attributes, probability components, deterministic draw, selection and first-party forcing reason |
| `school_bus_locked_first_party_routes.csv` | The 76 locked route identities with inferred loads; no restricted stop-table redistribution |
| `school_bus_proxy_demand_by_campus.csv` | Destination-level allocation and route count |
| `school_bus_proxy_summary.json` | Counts, warnings, and QA booleans |
| `SOURCE_MANIFEST.csv` | SHA256 hashes of derived outputs |

Release `school_bus_proxy_routes_2026_v3_school_probability_locked76` contains:

- an estimated non-tertiary school-bus share of 81.90069599% of TCS HBS SPB;
- 84,099 round-trip-equivalent proxy passengers, exactly conserved;
- 1,301 of 2,023 model campuses selected for service and 722 explicitly zero;
- primary 532/562 selected (94.66%), secondary 164/482 (34.02%), kindergarten
  545/915 (59.56%), and special 60/64 (93.75%);
- exactly 76 locked first-party route identities, all with positive inferred
  load, carrying 491 model passengers in aggregate;
- 2,308 residual inferred proxy routes carrying 83,608 passengers;
- 2,384 total locked-plus-proxy route/peak-vehicle equivalents;
- 41,493 inferred pickup records and 165 proxy routes above 20 km radius;
- no negative route loads, no route load over its proxy vehicle capacity, and
  no unresolved stop-to-route reference; no route serves a campus selected as
  zero.

The earlier `school_bus_proxy_routes_2026_v1` release retained all 102,684 HBS
SPB passengers and produced 3,217 routes; it is the unfiltered upper bound.
Version `school_bus_proxy_routes_2026_v2_non_tertiary` applied the 81.9007%
split but gave 2,017 campuses near-universal service and produced 2,893 routes;
it is the all-campus non-tertiary comparison. Both v1 and v2 are historical
versions and their output directories are intentionally not copied into the
current integration worktree. They remain available in the school-bus
acquisition worktree for provenance; neither is overwritten by v3.

All inbound routes currently target the same 07:55 arrival and the builder
does not interline two schools onto one vehicle. Therefore 2,384 is also the
model's peak vehicle-equivalent requirement. It is not an observed count of
distinct registered or operating vehicles. Staggered school starts and vehicle
reuse could reduce the distinct fleet, while maintenance reserve and service
irregularity could increase it.

The large pickup count follows from retaining sparse grid-to-campus assignment
support. Before MATSim adoption, candidate stops should be consolidated and
snapped to safe road access, routes map-matched to the active TNM network,
operators/fleets and legal A03/B01 status verified, capacities scaled for the
5% scenario, and road PCU and timetable assumptions calibrated. None of those
future steps is implied by this release.

## V4 road-aligned geometry preparation

The v3 straight-line geometry now has a separate, still non-production road-
aligned derivative. It does not replace v3 demand, the 76 locked route
identities, the active PT supply, or the teleported `school_bus` mode:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\map_match_hong_kong_school_bus_proxy_routes.py
```

The output is:

```text
data/school/hongkong/processed/school_bus_proxy_routes_2026_v4_road_matched/
```

The mapper retains each v3 inferred route's campus, pickup membership and
passenger load. Because v3's far-to-near ordering produces large zigzags, it
reorders only inferred pickups with a deterministic farthest-start nearest-
neighbour pass and 2-opt refinement, fixes the school as the final waypoint,
and then snaps the waypoints to the active MATSim `car` road layer. Bus-only
links are excluded: in the active hybrid network they are duplicated public-
transport route layers, not the physical base street graph. Consecutive
waypoints are routed on the directed network; an undirected road-topology
fallback is recorded when the directed graph cannot connect a pair. Two
minimal connections of at most 10 m repair TNM endpoint discontinuities and
are also counted explicitly. No straight disconnected fallback was required.

The output contains 2,308 WGS84 proxy paths and 76 geometry-null locked first-
party records. The 41,458 routed waypoint segments comprise 40,293 directed
segments and 1,165 undirected fallbacks. Median road path length is 54.502 km
(p95 118.317 km), versus a 23.111 km median optimised straight chain; median
road/optimised-straight ratio is 2.220. These lengths remain modelling warning
signals, not evidence that Hong Kong operators run such long routes: 268 paths
exceed 100 km, 195 have a ratio above 3, 15 exceed 5, and five waypoints snap
more than 1 km from a `car` road. They require demand clustering, island/
cross-harbour feasibility and safe-stop review before any supply adoption.

| V4 file | Purpose |
|---|---|
| `school_bus_road_matched_routes.geojson` | Road-aligned proxy paths; locked first-party geometries remain null |
| `school_bus_road_matched_routes.csv` | Route lengths, order method, path quality and fallback counts |
| `school_bus_road_match_segments.csv` | Ordered waypoint pairs, MATSim link IDs and segment-level method |
| `school_bus_route_waypoint_snaps.csv` | Source and snapped coordinates with distance QA |
| `school_bus_road_match_summary.json` | Network, route, fallback, distance and conservation QA |
| `hong_kong_school_bus_road_matched_overview.png` | Territory-wide straight-chain versus road-path comparison |
| `SOURCE_MANIFEST.csv` | SHA256 provenance for inputs and outputs |

The original v3 pickup and arrival times are not recalculated after v4
reordering and are marked as legacy provenance. Operational schedules must be
rebuilt only after manual review and stop consolidation. The static comparison
displays candidate geometry, not observed route traces; no interactive map is
generated.

## V5 hard-time and fleet-ceiling candidate

Version `school_bus_proxy_routes_2026_v5_time_split_fleet_cap3439` applies two
hard supply constraints requested for the modelling-preparation scenario:

- the integer fleet ceiling is `floor(4,200 × 0.819006959927839) = 3,439`;
- kindergarten/primary inferred routes must be at most 60 minutes, while
  secondary/special inferred routes must be at most 75 minutes.

The fleet count uses the conservative rule that every retained morning route
requires one peak vehicle and that all 76 locked first-party identities count
against the ceiling. Starting from v4, 2,030 of 2,308 inferred routes exceed
their stage target. Merely splitting each once would require at least 4,414
locked-plus-proxy vehicles, so full demand coverage and both hard constraints
cannot coexist.

The builder first fills the 3,439 pre-filter ceiling by splitting the 1,055
worst v4 time outliers once. Every inferred result still over its hard limit is
removed. Freed fleet slots then recover the highest-load theoretically feasible
pickup grids as direct one-pickup routes; 6,056 candidates are road-routed and
the best 3,028 time-feasible candidates are retained. No student is silently
reassigned to a different school, and removed demand remains explicitly
unserved.

The final candidate contains exactly 3,439 route/peak-vehicle equivalents:
3,363 inferred road-routed routes plus 76 locked, geometry-null first-party
records. It retains 34,151 of the original 84,099 proxy students (40.6081%),
including 491 model passengers attached to the time-unvalidated locked
identities. The remaining 49,948 students are deliberately outside this
candidate. Among inferred routes, median modelled time is 5.91 minutes, p95 is
43.65 minutes, and the maximum is 73.98 minutes. All 3,363 inferred routes pass
their stage threshold; none exceeds 100 km or uses a straight disconnected
fallback. The unusually low median reflects 3,028 direct one-pickup recovery
routes and must not be interpreted as an observed operating distribution.

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_school_bus_time_split_fleet_cap.py
```

Outputs are under:

```text
data/school/hongkong/processed/school_bus_proxy_routes_2026_v5_time_split_fleet_cap3439/
```

This remains `proxy_not_adopted`. The 76 locked records cannot pass the hard
time test until their permitted stop geometry is available; they remain an
evidence inventory, not validated physical supply. No interactive map is
generated.

## Re-run source acquisition

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\data_acquisition\collect_hong_kong_school_bus_route_sources.py `
  --output-dir .\data\school\hongkong\raw\school_bus_route_sources_2026
```

Use `--catalog-only` when network acquisition is not permitted. A failed
download is recorded with its error and URL; it is never treated as acquired.
Downloaded documents retain publisher copyright. The source catalogue and
hashes support provenance, not republication rights.
