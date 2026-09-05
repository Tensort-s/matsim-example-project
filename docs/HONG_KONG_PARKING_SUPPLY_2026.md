# Hong Kong unified parking supply candidate 2026

## Status and runtime boundary

`data/transport_costs/hongkong/parking_supply_2026_v1/`
contains the first unified real-facility private-car parking supply candidate.
Its canonical table is `hong_kong_parking_supply.csv`. It is **not** adopted
by MATSim routing, facilities, parking settlement, mode choice, or scoring.
The existing TCS-zone, activity, arrival-time, and duration-based parking
proxy remains the active Stage 11 rule.

Traffic signals are closed for this worktree. The historical opt-in signal
pilots remain reproducible, but no signal controller, signal-system file, or
signal-enabled config is part of this parking task. The worktree continues to
cover Car activity-link direction, start and internal U-turns, routing proxy
facilities, dynamic parking coverage, future real parking facilities, and
joint Car route/energy/toll/parking scoring.

## Official sources and observation dates

The 12 August 2026 snapshot combines:

1. Transport Department metered-space static data, whose internal data date
   is 11 August 2026;
2. the corresponding meter occupancy feed, used only to mark whether a space
   has a live feed;
3. the Government Data One-stop car-park information API;
4. the private-car vacancy API, used only to classify live-feed coverage;
5. the Transport Department page for government car parks managed by TD,
   last updated 30 June 2026; and
6. the two official data specifications that define meter codes and parking
   vacancy fields.

The source files are preserved under
`source_snapshots/2026-08-12/`. `SOURCE_MANIFEST.csv` records URLs,
publishers, retrieval date, local paths, SHA256 values, and roles. Hashes
identify the immutable source snapshot; they do not make a changing live-feed
value into static capacity evidence.

## Unit of observation and de-duplication

The table has one row per selectable parking facility candidate:

- one off-street row per official `park_Id`; and
- one on-street row per official meter `PoleId`, with all private-car spaces
  attached to that pole aggregated into its capacity.

The car-park API contains no `metered` car-park rows, so it does not duplicate
the meter-pole layer. Ten TD-managed private-car parks are matched exactly to
their existing API name and enrich that row with official capacity and
current hourly rates. Wong Tai Sin Car Park and two other records with explicit
heavy-vehicle-only evidence are excluded from the private-car supply. The
excluded IDs are explicit, reviewable constants in the builder; facility
eligibility is not inferred from a broad free-text pattern.

The meter specification states that IDs above 90000 are internal tests. The
builder excludes those 28 rows. Vehicle type `A` is retained for private cars;
coach and goods-vehicle spaces are excluded. Static data may still include a
meter awaiting commissioning, so the capacity status preserves that caveat.

## Current build

| Measure | Result |
|---|---:|
| Unified facility rows | 10,025 |
| Meter poles | 9,456 |
| Meter spaces eligible for private cars | 17,558 |
| Off-street facilities | 569 |
| TD-managed parks supplemented | 10 |
| Known private-car capacity | 25,040 |
| Off-street facilities with unknown capacity | 533 |
| Facilities assigned to TCS zones 1--26 | 10,023 |
| Facilities outside the adopted TCS grid | 2 |
| Nearest Car link within 100 m | 9,969 |

The two unresolved TCS records are Hong Kong-Zhuhai-Macao Bridge Hong Kong
Port car parks 4 and 5. They are kept as `tcs_zone=-1`; no nearest-zone or
default-zone fallback is applied.

## Schema and semantics

The 47-column CSV separates five concerns:

- identity and location: stable supply ID, official source ID, name, address,
  WGS84 coordinates, EPSG:32650 coordinates, and TCS zone;
- capacity: private-car capacity and its quality/source, plus EV, disabled,
  and unloading fields where structured data exist;
- pricing: structured JSON tariff rules, normalized minimum/maximum hourly
  rates, meter maximum stay, TD-managed hourly/day/night/quarterly rules, and
  preserved official free text;
- availability: whether an actual-count, binary, closed-state, or space-level
  live feed exists; the retrieved vacancy number itself is deliberately not
  copied into static supply; and
- network adoption: nearest current Car link and distance as an audit
  candidate, plus an explicit non-adoption status.

For off-street records, missing `privateCar.space` remains blank and has
`capacity_status=unknown_not_zero`. Current API `OPEN` or `CLOSED` is stored as
an observation, not a permanent eligibility filter. For meters, operating
periods are tariff periods, not proof that parking is prohibited outside those
hours.

## Car-link direction and future adoption

The nearest-link fields do not define a parking entrance. A short geometric
distance can still select the wrong carriageway, an elevated road, a tunnel
mainline, or the wrong direction. Every row therefore has
`routing_adoption_status=not_adopted_requires_entrance_direction_validation`.

Before real facilities replace the current parking proxy, each adopted
facility needs one or more validated access/egress connectors. Selection must
jointly consider the arriving Car route, the next departure of the same
vehicle, walking access to the activity, legal turns, road class, toll entry,
and household joint-ride waypoints. This is the same continuity requirement
used by the bounded activity-link direction repair. A facility must not be
adopted merely because its nearest link is close.

The future runtime sequence is:

1. validate entrance and exit links and their directions;
2. create parking/routing proxy facilities without changing canonical
   activity identity;
3. choose a feasible parking facility during routing with availability and
   capacity handled as time-varying state;
4. calculate route energy and toll with the same candidate route used by the
   router;
5. settle parking from the chosen facility's tariff and experienced dwell;
6. preserve the existing TCS/activity proxy as an explicit fallback only for
   destinations without an adopted real facility.

## Reproduction and QA

Run with the project geospatial interpreter:

```powershell
& 'F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe' `
  scripts\hong_kong_single_city\costs\car\build_hong_kong_parking_supply.py `
  --refresh-sources `
  --input-project-root 'F:\Matsim\matsim-example-project'
```

`build_summary.json` records row conservation and semantic checks. The
builder verifies unique IDs, Hong Kong coordinate bounds, non-negative known
capacities, official source URLs, meter-space conservation, exact matching of
all ten TD-managed private-car parks, TCS assignment, and availability of a
Car network. It does not compare input/output hashes.

## Static visualization

`visualization/hong_kong_parking_supply_static.png` maps all 10,025 candidate
facilities against the 18 District Council boundaries. Coral markers are
meter poles and scale with spaces per pole. Blue filled markers are off-street
facilities with known capacity and scale by that capacity; blue hollow markers
are official off-street records whose capacity is unknown. The map does not
show or validate parking entrances, exits, or nearest Car links.
