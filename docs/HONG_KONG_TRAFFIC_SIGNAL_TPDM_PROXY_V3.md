# Hong Kong territory-wide traffic-signal TPDM proxy V3

Status: `territory_wide_tpdm_proxy_stage1_candidate_not_adopted`

Network-expression reconciliation status:
`stage1_5_network_expression_reconciled_candidate_not_adopted`.

Stage 1 creates only a physical movement registry, planned movement/approach
demand `q` in 15-minute bins, and an approach-level TPDM saturation-flow proxy
`S`. It does **not** create stages, cycles, green splits, offsets, time-of-day
controllers, or MATSim signal-control XML. It neither enables signals nor
modifies the production network or no-signal baseline.

## Inputs and rebuild

The candidate uses the canonical 2,054-group registry, the current school-bus
V6 road/PT network and schedule, routed 5% V2 selected plans, and the existing
road workflow's observed detector/ATC crosswalks. All paths are CLI parameters.
Resolved paths are written to `stage1_metadata.json`; hashes are provenance
only, not model inputs or acceptance gates.

The ignored, rebuildable output directory is:

```text
data/transit/hongkong/processed/hong_kong_traffic_signals_2026_v3_tpdm_proxy_stage1/
```

Rebuild from the repository root:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_traffic_signal_tpdm_proxy_stage1.py
```

The builder exposes `--registry-dir`, `--network`, `--plans`,
`--transit-schedule`, `--road-audit-dir`, `--output-dir`, and explicit path
enumeration guardrails.

## Physical movement algorithm

The builder reuses the pilot network parser, bearings, and
`internal_nodes_for_junction` micro-node recovery. For each registry group it
rebuilds the physical cluster, finds car-capable links entering from outside,
and walks simple internal car paths until their first outside exit. Each row is
the full `fromLink -> internal link sequence -> exitLink` path and separately
records its MATSim first internal connector.

Movement IDs derive from semantic junction/link/path fields plus a stable short
digest, never from CSV row number or enumeration order. Walks are capped at 12
internal links and 2,048 paths per approach; the completed candidate hit no
truncation guard.

One first connector fans out to multiple exits at 3,789 boundaries. Stage 1
preserves every physical alternative and never assumes they later share a
signal group.

The territory-wide audit also detects registry groups whose recovered clusters
overlap enough to produce the same complete physical path. Those movement rows
remain visible as registry/topology QA, but are explicitly excluded from q
matching: the builder neither assigns a vehicle arbitrarily to one group nor
double-counts it at both groups. The original Stage-1 build found 198 shared
path signatures affecting 411 movement rows.

### Stage 1.5 reconciliation

Stage 1.5 corrects a QA interpretation: a first connector reaching multiple
exits is expected when complete physical movement paths are retained. It warns
against grouping signals by first connector, but is not itself a failed network
expression. Explicit alternative internal paths are likewise retained as
Stage-2 grouping/lane-evidence questions rather than automatic topology review.

For shared complete paths, exactly one q owner is selected only when evidence
is unique: first an exclusive registry controlled-link candidate, then an
exclusive original stopline seed, then a unique official controller reference,
then a junction centroid within 30 m and at least 10 m nearer than the next
candidate. Non-owner rows stay visible but are
excluded to prevent double counting. Of 205 shared signatures after seed
recovery, 167 have a unique owner and 38 remain unresolved; 258 duplicate or
non-owner movement rows remain excluded.

For groups without mapped seeds, the registry's already-recorded primary node
is reused only within 60 m and at road-node degree two or greater. The recovery
is `geometry_inferred` and changes no network ID. Fifteen of 37 no-seed groups
recover; 22 remain unresolved.

### Geometry classification

| Rule | Threshold |
|---|---:|
| ahead | absolute angle at most 30 degrees |
| ambiguous ahead/turn | greater than 30 and less than 45 degrees |
| left/right | absolute angle at least 45 and less than 135 degrees |
| ambiguous turn/U-turn | 135 to less than 150 degrees |
| U-turn | absolute angle at least 150 degrees |

Positive angle is left and negative angle is right in the projected-network
bearing convention. Boundary uncertainty remains `ambiguous` rather than being
force-classified.

### Legal evidence and U-turns

Directed topology and car mode encode one-way and coarse access feasibility.
Available derived files do not preserve enough source OSM restriction,
`turn:lanes`, or lane-to-movement evidence for territory-wide turn permission.
Therefore non-U-turn topology is normally `legal_status=unresolved`; TS_K006
paths matching the audited diagram boundary are
`supported_by_published_diagram`. All U-turns are `u_turn_candidate`,
`excluded_no_positive_evidence`, and `not_activated`.

The reconciled candidate contains 17,006 paths, including 4,437 excluded
U-turns and 12,557 unresolved non-U-turn legal movements. The larger U-turn
count corrects an enumeration-order defect: a reverse exit returning to the
approach origin is now recorded before internal-loop visited-node filtering.
Every recovered U-turn remains excluded from q.

## Planned demand q and scaling

Demand is desired free-flow arrival, not congestion-realised throughput. Each
routed vehicle path is matched against the full movement sequence. Arrival
time is departure plus cumulative network free-flow link time and is grouped
into 15-minute bins as `freeflow_route_propagation`.

The build reads 67,718 selected private-car legs and complete road-transit
departures: 69,589 bus, 81,081 GMB, and 6,878 school-bus proxy departures.

| Vehicle class | Supply/demand scale | Expansion | TPDM PCU |
|---|---|---:|---:|
| private car | 5% whole-person sample | 20 | 1.0 |
| motorcycle | no routed physical class | 1 | 0.4 |
| bus | full operational timetable | 1 | 2.0 |
| GMB | full operational timetable | 1 | 1.5 |
| school bus | full-supply V6 proxy | 1 | 2.0 |
| taxi | physical road QVehicle missing | 1 | 1.0 |
| other road vehicle | no supported source | 1 | 1.0 unused proxy |

QSim's reduced bus/GMB PCU is a simulation-mechanics choice and is not a TPDM
design PCU. Generic `ride` routes have no physical link sequence. The input has
4,747 sampled taxi-labelled passenger legs, or 94,940 population-scale
passenger-leg equivalents, but this is neither vehicle demand nor occupancy
evidence. No taxi movement flow is fabricated.

The q tables preserve raw count, class expansion, full-scale vehicle count,
TPDM PCU factor/count, and hourly equivalent. Zero-demand combinations are not
materialised as dense rows.

## Observed approach-flow anchors

Only detector volume and ATC directional AM/PM flow are used. Detector Q90,
hybrid capacity, and calibrated MATSim capacity are never treated as observed
demand. Detector observations join by road route/direction; per-lane flow is
multiplied by network approach lanes and remains a corridor-direction proxy.
Coverage below 450 observed seconds stays visible but does not replace model
q. ATC uses the direction-level crosswalk, not the station-only crosswalk.

`approach_flow_anchor_audit.csv` retains raw model q, observed q, anchored q,
coverage, source IDs, difference, confidence, and action. There are 111
accepted anchored approaches: 24 have detector comparisons and 88 have ATC
comparisons, with possible overlap. Observed totals are not silently allocated
to vehicle classes or movements.

## TPDM saturation flow S

Current MATSim capacity is comparison data only and is never used as S:

```text
S_nearside = 1940 + 100 * (W - 3.25)
S_other    = 2080 + 100 * (W - 3.25)
S_approach = S_nearside + (N - 1) * S_other
```

Lane count comes from the road-capacity workflow/network. Every approach uses
`W=3.25 m` as `default_tpdm_reference`. Reliable approach gradient is absent,
so adjustment is zero with `unavailable_no_adjustment`; the TPDM uphill
reduction of 42 pcu/h/lane per percent is recorded but not applied. Downhill
never gets an automatic increase.

The 5,907 approach proxies range from 1,940 to 14,420 pcu/h, median 4,020.
Network-capacity/S ratios range from 0.393443 to 1.005155, median 0.572139; this
comparison modifies no link. S is not split among movements because
lane-to-movement mapping is absent.

## Coverage, outputs, and validation

Of 2,054 groups, the reconciled build recovers approaches for 2,032 and any
movement for 2,031. There are 2,030 groups with a non-U-turn design movement,
23 unexpressed groups, and one group with only an excluded U-turn. After the
fan-out correction, 1,930 are expressed, 101 have genuine shared-path topology
review, and 23 are unexpressed. Confidence is 1,785 high, 145 medium, and 124
review.

Topology outputs are `signal_movements.csv`, `signal_approaches.csv`,
`movement_topology_exceptions.csv`, `u_turn_candidates.csv`, and
`junction_network_expression_audit.csv`. Demand outputs are
`vehicle_class_demand_scaling.csv`, `movement_demand_15min.csv`,
`approach_demand_15min.csv`, `junction_demand_15min.csv`, and
`approach_flow_anchor_audit.csv`. S and QA outputs are
`approach_saturation_flow.csv`, `saturation_flow_assumption_audit.csv`,
`stage1_qa_summary.json`, `stage1_coverage_by_confidence.csv`, and
`stage1_metadata.json`. Stage 1.5 adds `junction_seed_recovery_audit.csv`,
`shared_physical_path_ownership_audit.csv`, and
`junction_network_repair_action_audit.csv`.

The eight diagram examples are validation only. All recover movements; their
connector fan-out remains a Stage-2 grouping warning, not a Stage-1 expression
failure. TS_K006 is a hard regression: all four V2
`fromLink -> first connector -> reachable exits` sets match exactly; mismatch
stops the builder rather than changing V2 truth.

## Limitations and Stage 2 prerequisites

Current topology supports an auditable movement candidate, but blocks automatic
territory-wide stage generation. Blockers are unresolved turn legality,
missing turn lanes and lane-to-movement mapping, 38 unresolved shared paths, 23
unexpressed groups, one U-turn-only group, missing pedestrian clearance paths,
and incomplete timing evidence. Taxi physical routes and reliable gradients
are also absent.

The repair audit identifies nine candidate link splits. Implementing them
would be a common-topology change requiring stable replacement IDs and updates
to plans, PT schedules, link attributes, and downstream references. Thirteen
locations first require source/network-coverage review; one needs outbound car
access or one-way review; one may be a cul-de-sac or non-junction signal. No
such network change is made in Stage 1.5.

Before Stage 2, resolve legal turns/lane groups, review fan-out and unexpressed
groups, validate the seven deferred diagrams at movement level, and establish
critical-lane demand evidence. Overlapping registry clusters must also be
reconciled before movement demand can cover their shared paths. Only then
should conflicts, stages, cycles,
green splits, offsets, or controllers be considered. Stage 1 stops here.

The explicitly authorised bounded continuation is now documented in
`HONG_KONG_TRAFFIC_SIGNAL_TOD_TOP100_V3.md`. It does not change Stage 1 truth:
it consumes the reconciled topology/q/S tables and produces a separate,
opt-in 100-junction by 96-bin proxy candidate.
