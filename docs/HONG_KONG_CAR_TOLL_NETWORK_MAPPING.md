# Hong Kong private-car toll facility-network mapping audit v1

## Scope

This audit resolves official Hong Kong private-car toll features to links in
the adopted MATSim road network and applies that mapping to every routed car
leg. It is an identification audit only:

- it does not calculate or change any toll amount;
- it does not modify the existing low/base/high cost Parquet files;
- it does not modify plans, config, network, facilities, vehicles, scoring, or
  simulation outputs;
- motorcycle legs remain explicitly out of scope.

The machine-readable outputs are under
`data/transport_costs/hongkong/car_cost_v1/toll_network_mapping_v1/`. The
reproducible builder is
`scripts/hong_kong_single_city/costs/car/audit_hong_kong_car_toll_network_mapping.py`.

## Read-only evidence

The audit uses the routed Hong Kong V2 plans, adopted road network, the
Transport Department `RdNet_IRNP.gdb`, the previous car-cost feasibility
table, current toll rules and source snapshots, and the existing low/base/high
car-cost outputs. The official private-car class is `PC`.

The official toll inventory contains:

| Item | Count |
|---|---:|
| canonical physical facilities | 9 |
| raw official facility names | 10 |
| unique official toll feature IDs | 19 |
| `TUN_BRIDGE_TOLL` private-car rows | 5 |
| `TUN_BRIDGE_TV_TOLL` private-car rows | 278 |

Each inventory row retains its source layer, effective date, time rule, toll
fields, remarks, last-update date, and source SHA256. These rates are recorded
as source evidence but are not applied in this audit.

## Mapping method and evidence grades

The authoritative mapping chain is:

```text
official TRAFFIC_FEATURES FEATURE_ID
  -> official TRAFFIC_FEATURES RD_ID_*
  -> official CENTERLINE ROUTE_ID and road name
  -> adopted MATSim road_<ROUTE_ID>_* link
```

The official toll point and adopted network-link geometry are also compared.
All accepted mappings are within 71.6 m of their official points.

The evidence grades are:

- **A**: a feature and network link share an ID in a demonstrated common ID
  domain, with geometry and topology confirmation;
- **B**: an explicit official crosswalk or topology chain resolves the
  feature to an adopted network link, with geometry confirmation;
- **C**: a geometry/name inference without an explicit official topology
  crosswalk;
- **U**: unresolved or ambiguous.

The final feature counts are **A=0, B=19, C=0, U=0**.

## Rejected same-number matches

The prototype treated seven equal-looking toll `FEATURE_ID` and network
`ROUTE_ID` values as direct matches. They are values from different ID domains.
Geometry proves that the same-number links are unrelated:

| Official feature ID | Distance to same-number network link (m) |
|---:|---:|
| 1824 | 10,674.7 |
| 1886 | 13,076.7 |
| 2040 | 10,893.0 |
| 2684 | 10,889.2 |
| 4288 | 16,325.6 |
| 4289 | 18,593.3 |
| 7804 | 3,844.8 |

These seven candidates are rejected, not graded A. Their replacement mappings
use the official `FEATURE_ID -> RD_ID -> ROUTE_ID` chain and are graded B.
This is the principal reason the current toll identification differs from the
prototype.

## Resolution of the previously unmapped features

All twelve features previously lacking a direct same-number candidate are now
resolved with grade B:

| Feature | Official road IDs | Adopted MATSim links |
|---:|---|---|
| 1822 | 56944 | `road_56944_0_f` |
| 1884 | 59208 | `road_59208_0_f` |
| 2685 | 105993, 285417 | `road_105993_0_f`, `road_285417_0_f` |
| 150338 | 261324 | `road_261324_0_f` |
| 150339 | 105137 | `road_105137_0_f` |
| 150340 | 261326, 295709, 295713, 295712 | matching `road_*` links |
| 150498 | 3375 | `road_3375_0_f` |
| 150499 | 64427 | `road_64427_0_f` |
| 151058 | 261309, 283947 | matching `road_*` links |
| 151078 | 261312, 261310 | matching `road_*` links |
| 151118 | 261327, 283967, 295708 | matching `road_*` links |
| 151858 | 2485 | `road_2485_0_f` |

The complete, row-level evidence is in
`toll_facility_network_mapping.csv`; the compact table above is not a
replacement for that file.

## Western Harbour Crossing alias

The official source contains both `Western Harbour Crossing` and `Western
Harbour Crossing (Backup Toll Point)`. They are treated as aliases of one
physical facility because:

- the primary and backup entries have identical 78-row weekday/weekend
  schedules and rates;
- effective and last-update dates and remarks agree;
- feature 2684 is shared;
- the official traffic-feature remark identifies 151858 as
  `WHC(SB) Backup toll point`;
- official road IDs 2485 and 3345 are both named `WESTERN HARBOUR CROSSING`;
- the two official feature points are about 106.7 m apart.

The machine status is `canonical_alias_same_physical_facility`, with
`charge_once_per_route_passage=true`. The raw alias evidence is preserved, but
one passage cannot create two physical toll events.

## Direction coverage

Both official feature roles are mapped for every canonical facility:
Aberdeen, Cross Harbour, Eastern Harbour, Lion Rock, Shing Mun, Tai Lam,
Tate's Cairn, Tsing Sha, and Western Harbour. Direction-role coverage is
therefore 100% for all nine facilities.

The MATSim suffixes `f` and `r` are retained as link orientations only. They
are not relabelled as northbound, southbound, eastbound, or westbound without
official evidence. Six mapped orientation alternatives are not used by any
current routed car leg; this is recorded as observed route coverage, not
removed from the mapping.

## Per-leg identification results

The output has one unique row for each of the **67,718** routed car legs:

| Identification status | Legs |
|---|---:|
| confirmed charge, facility identified | 25,858 |
| confirmed no charge, all facilities covered | 38,931 |
| out-of-scope motorcycle | 2,929 |
| ambiguous or unresolved | 0 |

Confirmed private-car passage counts by canonical facility are:

| Facility | Legs |
|---|---:|
| Aberdeen Tunnel | 2,235 |
| Cross Harbour Tunnel | 7,214 |
| Eastern Harbour Crossing | 3,984 |
| Lion Rock Tunnel | 2,919 |
| Shing Mun Tunnels | 1,759 |
| Tai Lam Tunnel | 3,944 |
| Tate's Cairn Tunnel | 2,832 |
| Tsing Sha Control Area | 1,393 |
| Western Harbour Crossing | 4,557 |

A leg may legitimately traverse more than one different physical toll
facility: 4,786 legs do so. Alias and raw-candidate deduplication is separate:
2,024 legs contain a Western backup/primary alias candidate, 2,132 legs have
more raw mapping matches than deduplicated physical events, and **zero**
duplicate physical toll-event rows are emitted. Explicitly adding route start
and end links creates zero additional facility hits.

## Comparison with the prototype

Among the 64,789 private-car legs, the old and audited simplified statuses are:

| Prototype status | Audited charge | Audited no charge |
|---|---:|---:|
| confirmed charge | 759 | 249 |
| confirmed no charge | 25,099 | 38,682 |

All 2,929 motorcycle rows remain out of scope. Including status and canonical
facility identity, **27,220** legs differ from the current car-cost v1
identification. No prior confirmed-no-charge leg is downgraded to unresolved;
it is either confirmed under the complete mapping or reclassified as a
confirmed facility passage.

This audit does not repair the monetary cost outputs. It establishes the
mapping needed for a separate rate-application and output-rebuild stage.

## Outputs

- `official_toll_feature_inventory.csv`: normalized official private-car
  facility, feature, schedule, rate, and provenance rows;
- `toll_feature_alias_resolution.csv`: Western Harbour primary/backup evidence
  and charge-once rule;
- `toll_facility_network_mapping.csv`: feature-to-network mapping and evidence;
- `car_leg_toll_identification.parquet`: full-route, per-leg facility
  identification without monetary fields;
- `toll_network_mapping_validation.json`: counts, coverage, comparison,
  protected hashes, and next-stage gate;
- `toll_mapping_required_repairs.csv`: explicit repairs required before
  monetary toll outputs are rebuilt.

## Required repairs and next-stage gate

Before rebuilding monetary toll results:

1. replace all same-number feature/link matching with the audited official
   topology crosswalk;
2. regenerate both charge and no-charge labels from the new mapping;
3. canonicalize Western Harbour primary/backup records and charge once per
   route passage;
4. retain official feature roles and MATSim `f/r` orientation without
   inventing compass directions;
5. replace personal absolute provenance paths with repository-relative paths
   and an explicit input-root role.

The validation gate reports
`eligible_for_next_rate_application_and_output_repair_stage=true`, while also
reporting `toll_amounts_calculated=false`. Eligibility means the mapping and
alias evidence are complete; it does not authorize or imply a monetary result.

## Reproducibility and integrity

Run the audit from the feature worktree with the project geospatial Python:

```powershell
<geo-python> -B scripts/hong_kong_single_city/costs/car/audit_hong_kong_car_toll_network_mapping.py `
  --input-project-root <canonical-project-root>
```

The script reads its canonical inputs without modification and writes only the
mapping-audit directory. Validation confirms:

- all 19 official features are mapped and all mapped links exist;
- no network link maps to unrelated canonical facilities;
- all 67,718 leg keys match the previous feasibility audit;
- protected input hashes are unchanged;
- existing low/base/high cost Parquet hashes are unchanged;
- the fixed-link grid is protected as a full same-stem sidecar bundle,
  including `.shp`, `.dbf`, `.shx`, and `.prj`.

The fixed-link-grid bundle SHA256 is
`b816d1ab0666a2851bdd7359afe07437a80672c81ba6c72b85924537793738cb`.
