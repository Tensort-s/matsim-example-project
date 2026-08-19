# Hong Kong bounded road-continuity explicit-storage candidate

## Status

This is an immutable, **non-adopted** QSim road-supply sensitivity candidate.
It uses the completed TPDM-three-candidate, no-signal, physical-Taxi PCU 0.05
iteration-0 runtime audit to repair only the selected same-street dominant
continuations. Candidate2 keeps the physical MATSim network byte-identical to
TPDM3 and supplies explicit QSim storage capacities through a separate
registry. No PT terminal placement, Taxi/private-car starting direction,
signal plan, node, link ID, mode, topology, physical length, physical lane
count, free speed, or flow capacity is changed.

Candidate1, which increased link length and lane count to obtain storage, is
retained for provenance but is superseded and must not be adopted. Its virtual
length changed free-flow travel time and route distance. Candidate2 removes
that coupling.

## Source evidence

Source TPDM-three-candidate network:

```text
/mnt/DiskM/by/hk_stage11_road_hotspot_tpdm_v4_three_candidate_20260816_candidate2/
  network_tpdm_v4_three_candidate.xml.gz
SHA256: 2cc70f0e4c7a3966c698935bafcadbab65db3f13407e58442e7c13413d257979
```

Runtime neighborhood audit:

```text
/mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260816_tpdm3_pcu005_it0_run1/
  road_hotspot_neighborhood_tpdm3_v1/hotspot_links.csv
  SHA256: 486233d2eed91e6157088481597a9c0a377276506d4318ac62e4a49878868ccf
  road_hotspot_neighborhood_tpdm3_v1/hotspot_neighbors.csv
  SHA256: 67eae8e31cfd6c8ea3af76cece0ef2823eb53b17504b42f3a9cae88ab0381950
```

The source run uses `storageCapacityFactor=0.1`; the diagnostic effective cell
size is 7.5 m.

## Exact selection boundary

A hotspot-to-downstream relationship is included only when all of the
following hold:

1. the observed dominant downstream share is at least 0.90;
2. the normalized English street name is identical on both links;
3. blank and `-99` street names are excluded;
4. the downstream link has at least one of:
   - length below 10 m;
   - fewer lanes than the hotspot link;
   - diagnostic storage below one vehicle, calculated as
     `length * lanes * 0.1 / 7.5`.

The frozen selection contains 116 relationships and 114 unique downstream
links. `road_57636_0_f` and `road_7747_0_f` are each selected by two upstream
hotspots. The issue counts overlap:

| Relationship flag | Count |
|---|---:|
| Downstream length below 10 m | 52 |
| Downstream lane drop | 54 |
| Downstream storage below one vehicle | 102 |

The 116 upstream hotspot rows account for 42,484.063725 vehicle-hours of
delay. Because two target links are repeated and issue categories overlap,
that number is a prioritization diagnostic rather than additive benefit.

## Candidate2 storage formula

For each of the 114 unique target links, let `x` be the maximum selected
upstream continuity lane count. The requested direct QSim storage is:

```text
S_x = x PCU
S_default_physical = physical_length_m * physical_lanes
                     * storageCapacityFactor / effectiveCellSize_m
S_buffer = flow_capacity_vph * flowCapacityFactor
           * qsimTimeStep_s / 3600
S_freeflow-flow = (physical_length_m / freespeed_m_s)
                  * flow_capacity_vph * flowCapacityFactor / 3600

storage_capacity_qsim_pcu =
    max(S_x, S_default_physical, S_buffer, S_freeflow-flow)
```

The first-version design basis is fixed and validated at startup:

```text
storageCapacityFactor = 0.1
flowCapacityFactor = 0.1
effectiveCellSize = 7.5 m
qsimTimeStep = 1 s
Taxi PCU = 0.05
```

The formula therefore uses `x` as the requested lower bound, while preserving
larger physical/default or queue-safety requirements. A registry value below
the recomputed requirement is a fatal startup error; QSim is not allowed to
silently increase it.

Flow and storage are independent. `flow_capacity_vph` is copied from TPDM3 and
has no override in this candidate. Links outside the selected 114 retain the
standard MATSim queue construction and storage calculation.

## Candidate3 all-road lane floor

Candidate3 applies the same independent-storage mechanism to every physical
road link. It does not widen or lengthen any road. For the frozen 114
continuity targets, `x` remains the maximum of the downstream physical lane
count and the selected upstream continuity lane counts. For every other road
link, `x` is its own physical lane count. The formula is unchanged:

```text
storage_capacity_qsim_pcu =
    max(x, S_default_physical, S_buffer, S_freeflow-flow)
```

The accepted generated artifacts are:

```text
/mnt/DiskM/by/hk_stage11_all_road_explicit_storage_20260817_candidate3_v2/
  network_tpdm3_physical_all_road_explicit_storage_v3.xml.gz
  road_supply_parameters_v3.csv
  road_storage_capacity_v3.csv
  continuity_candidate_relationships_v3.csv
  road_supply_candidate3_summary.json

physical network SHA256:
2cc70f0e4c7a3966c698935bafcadbab65db3f13407e58442e7c13413d257979

road-supply registry SHA256:
d158aebb713834a20b8662176cdc5e9e057c26a8cd27dd42c396b2203d1dac86
```

All 86,417 physical road links have explicit storage overrides and zero links
have flow-capacity overrides. There are 69,612 one-lane, 12,418 two-lane,
3,382 three-lane, 870 four-lane, 112 five-lane, 12 six-lane, and 11 seven-lane
physical links. The 114 continuity floors shift the final `x` distribution to
69,586/12,408/3,400/884/116/12/11 respectively.

Relative to Candidate2's effective storage (114 explicit targets plus normal
MATSim storage elsewhere), Candidate3 increases 37,054 links and leaves
49,363 unchanged. The network-wide effective-storage sum increases from
143,273.081242 to 169,291.861427 PCU, an increase of 26,018.780185 PCU or
18.1603%. This aggregate is queue space, not simultaneous traffic demand and
not a flow-capacity increase.

The first immutable generated directory without the `_v2` suffix is retained
for provenance. Its capacities were correct, but its JSON summary subtracted
the all-road override count from the continuity-relationship count and thus
reported a negative duplicate count. The `_v2` directory fixes only that
summary calculation and correctly records 116 relationships, 114 unique
continuity targets, and two duplicate-target relationships.

## Candidate4 full connector-chain flow/storage candidate

The Candidate3 runtime audit found that a storage-only repair can still leave
an internal connector chain constrained by its original one-lane flow
capacity. It also found cases where Candidate2 selected only the first short
segment. The clearest example is Chatham Road South:

```text
road_104225_0_f (3 lanes)
  -> road_104307_0_r (5.690 m, 1 lane)
  -> road_104308_0_f (5.666 m, 1 lane)
  -> recovered 3-lane link
```

Candidate2/3 gave the first connector a three-PCU continuity storage floor,
but did not include `road_104308_0_f` and changed no flow capacities.
Candidate4 treats a short connector chain atomically. Starting from a
same-street lane-drop seed, it follows either an observed dominant downstream
movement of at least 0.90 or a unique same-street topological continuation.
Every impaired segment is included until both physical length is at least
10 m and physical lanes have recovered to the upstream lane floor. A cycle,
missing link, ambiguous continuation, street-name mismatch, or unrecovered
maximum depth rejects the whole seed and selects zero segments.

For an accepted connector-chain segment with upstream continuity floor `x`,
the QSim-only flow capacity is:

```text
C_nearside(W) = 1940 + 100 * (W - 3.25)
C_other(W)    = 2080 + 100 * (W - 3.25)
C_TPDM4(x,W)  = C_nearside(W) + (x - 1) * C_other(W)

C_QSim_vph = max(C_physical_vph, round_up(C_TPDM4(x, 3.25), 50))
```

Storage is then recomputed using that QSim flow value:

```text
S_QSim = max(x, S_default_physical, S_buffer,
             S_freeflow-flow_using_C_QSim)
```

The scenario network remains byte-identical to TPDM3. Length, physical lane
count, free speed, route distance, free-flow time, and the scenario-network
link capacity remain unchanged. The flow adapter exists only inside QSim and
is checked against the registry at queue construction.

Generated immutable candidate:

```text
/mnt/DiskM/by/hk_stage11_connector_chain_flow_storage_20260817_candidate4/
  network_tpdm3_physical_connector_chain_v4.xml.gz
  road_supply_parameters_v4.csv
  road_storage_capacity_v4.csv
  road_flow_capacity_v4.csv
  connector_chain_relationships_v4.csv
  connector_chain_rejected_seeds_v4.csv
  previous_candidate_chain_completion_audit_v4.csv
  road_supply_candidate4_summary.json

physical network SHA256:
2cc70f0e4c7a3966c698935bafcadbab65db3f13407e58442e7c13413d257979

road-supply registry SHA256:
962c204cdce4339dbadf3b1825a05b6d102e2e6106e74a085adaec06bd9b1e33
```

There are 90 deduplicated seeds. Thirty-nine have a complete, unambiguous
chain and select 57 unique segments; 51 are rejected atomically. All 57
selected segments receive both a flow review and storage recomputation.
The QSim flow increase sums to 151,700 veh/h over those links, with individual
increases of 2,050--6,250 veh/h. This is a bounded internal-connector
sensitivity, not an assertion that the physical roads were widened.

The retrospective audit covers the 54 Candidate2 relationships that had a
physical lane drop and therefore an unhandled flow mismatch. It finds eight
previously truncated chains; all eight are now completed. They add the
following missing segments:

```text
road_104270_0_r, road_104308_0_f, road_104273_0_f, road_104295_0_f,
road_104866_0_f, road_104868_0_r, road_8683_0_r, road_264684_0_f
```

For the example above, both `road_104307_0_r` and `road_104308_0_f` now use
`x=3`, QSim flow 6,100 veh/h, and storage recalculated from the same flow
basis; their physical flow capacity remains 1,950 veh/h in the network XML.
Of the 54 prior lane-drop seeds, 28 pass the complete-chain gate and 26 are
rejected because the next same-street link is not unique. Rejected seeds
receive no partial flow or storage-chain extension; Candidate3's general
all-road `x` floor remains their unchanged baseline.

## Candidate2 generated artifacts

```text
/mnt/DiskM/by/hk_stage11_road_continuity_explicit_storage_20260816_candidate2/
  network_tpdm3_physical_explicit_storage_v2.xml.gz
  road_supply_parameters_v2.csv
  road_storage_capacity_v2.csv
  continuity_candidate_relationships_v2.csv
  road_supply_candidate2_summary.json

physical network SHA256:
2cc70f0e4c7a3966c698935bafcadbab65db3f13407e58442e7c13413d257979

road-supply registry SHA256:
5be2791486dc9fbc477c202897351ac370fe5f5c29fec633c90e3cb16f947d69
```

The output network is byte-identical to the TPDM3 source network. The registry
contains all 86,417 physical road links, while the storage override table has
exactly 114 rows and the relationship table retains all 116 relationships.

The `x` distribution is 10 one-lane, 50 two-lane, 30 three-lane, 19 four-lane,
and 5 five-lane targets, totalling 301 PCU. Of the 114 links, 107 receive
exactly `x`; seven retain a larger physical/default safety value. Total direct
storage is 393.573933 PCU, with a range of 1.0 to 78.561760 PCU. There are zero
flow-capacity overrides.

## Runtime implementation and audit

MATSim 2026 does not expose a public per-link storage setter on
`QueueWithBuffer`. The Hong Kong module therefore installs a QSim-only network
factory. For each overridden queue it derives an internal effective-lane
adapter whose standard queue formula yields the exact registered PCU value.
Candidate4 additionally supplies a QSim-only link-capacity adapter for the 57
accepted chain segments. The scenario network and all routing/scoring/fare
inputs remain physical and unchanged. No reflection and no MATSim-core source
modification are used.

Startup validation checks the network SHA, every physical field in the full
registry, every registered override ID, the design-basis configuration, and
the exact formula. Both the 114-link Candidate2 registry and the 86,417-link
Candidate3 registry are supported without a hard-coded runtime count.
Queue construction and time-variant recalculation assert that actual storage
equals requested storage and actual per-step QSim flow equals the registered
value. Each iteration writes requested/actual storage, requested/actual flow,
peak occupied PCU, and blocked-inflow seconds/checks for every overridden
link.

The runtime switch is:

```text
--road-supply-registry=<road_supply_parameters_v2_v3_or_v4.csv>
```

Omitting the switch restores the unchanged TPDM3 network and standard MATSim
storage behavior.

## No-signal physical-Taxi smoke

The accepted immutable smoke is:

```text
/mnt/DiskM/by/
  hk_stage11_candidate11_taxi_dvrp_20260816_explicit_storage_x_pcu005_it0_release2/
  hk_stage11_candidate11_taxi_dvrp_20260816_explicit_storage_x_pcu005_it0_run2/

JAR SHA256:
1e94ea11f3c8fd3f2c132750f3d373bcc760212e747f78cb47c3a2ff720813f8
```

The run uses the original Candidate11 plans with no inherited Taxi proxy
scores, no signals, 15,500 physical DVRP taxis at PCU 0.05, 16 QSim threads,
`stuckTime=3600 s`, `removeStuckVehicles=false`, capacity factors 0.1, and only
iteration 0. It completes with exit code 0 and five QSim-lost agents.

The matched control is the same TPDM3 network, plans, fleet, JAR-generation
workflow, and QSim settings without the explicit-storage registry:

```text
/mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260816_tpdm3_pcu005_it0_run1/
```

| Completed-trip metric | TPDM3 default storage | Candidate2 explicit storage | Change |
|---|---:|---:|---:|
| Completed trips / 743,614 | 555,858 | 562,470 | +6,612 |
| Completion rate | 74.7509% | 75.6400% | +0.8892 pp |
| Mean time, completed trips | 54.350 min | 56.516 min | +2.165 min |
| QSim-lost agents | 5 | 5 | 0 |

The raw completed-trip mean rises because the completed set changes. Among
the 552,044 trip IDs completed in both runs, Candidate2 is 1.210 minutes
faster on average: Car is 3.710 minutes faster, PT 0.866 minutes faster, and
Taxi 7.060 minutes faster. Candidate2 newly completes 10,426 long trips
(300.296-minute mean) while 3,814 control-only completions have a
232.111-minute mean. The net gain is therefore accompanied by the admission
of long, previously incomplete trips; it is not evidence that common trips
became slower.

Completed-trip outcomes by main mode are:

| Mode | TPDM3 completed | Candidate2 completed | Candidate2 share of completed | Mean min TPDM3 | Mean min Candidate2 |
|---|---:|---:|---:|---:|---:|
| Car | 36,108 | 37,395 | 6.6484% | 34.475 | 37.919 |
| Car passenger | 2,734 | 2,734 | 0.4861% | 8.056 | 8.056 |
| PT | 411,861 | 416,365 | 74.0244% | 50.870 | 53.465 |
| Taxi | 25,839 | 26,591 | 4.7275% | 34.582 | 37.007 |
| Walk | 79,316 | 79,385 | 14.1136% | 89.510 | 89.484 |

The planned selected-mode shares remain unchanged because the plans are
identical: Car 9.1066%, Car passenger 0.3677%, PT 73.5453%, Taxi 5.9169%, and
Walk 11.0635%. The table above uses completed trips only and must not be read
as a selected-plan mode-share change.

Taxi requests conserve exactly:

```text
34,692 submitted = 26,591 completed + 1,019 waiting
                   + 7,077 onboard + 5 rejected
```

Taxi wait p50/p90/p95/p99 is 42/184/663/54,725 seconds. Empty VKT is
24,488.823 km, occupied VKT is 369,917.035 km, and the empty VKT ratio is
6.2090%.

The per-iteration storage audit contains exactly 114 rows. Requested and
actual storage differ by at most `8.88e-16` PCU, so there is no material
silent expansion. The requested sum/range is 393.573933 PCU and 1.0 to
78.561760 PCU. Of the targets, 108 experience at least one blocked-inflow
second; this confirms Candidate2 is a bounded storage intervention rather than
an unlimited queue. Those per-link blocked seconds are diagnostic counters and
must not be added as person-delay benefit.

The first immutable run attempt is retained as `...it0_run1`. It stopped at
07:49 because the initial audit enumerated MATSim's non-thread-safe internal
vehicle collection while 16 QSim workers modified it. The accepted run2 audit
uses a synchronized PCU counter updated only at queue entry/exit interfaces;
the queue itself and its traffic behavior are not locked or traversed by the
audit.

## Candidate3 all-road no-signal smoke

The accepted immutable Candidate3 smoke is:

```text
/mnt/DiskM/by/
  hk_stage11_candidate11_taxi_dvrp_20260817_all_road_x_pcu005_it0_release1/
  hk_stage11_candidate11_taxi_dvrp_20260817_all_road_x_pcu005_it0_run1/

JAR SHA256:
6be65147b938fde8cdbd57e07a99a872a9e1384744cbc46c514d75e68fd6f3f9
```

It uses the same original Candidate11 plans, no signals, fleet, Taxi PCU 0.05,
capacity factors, 16 threads, 30-hour QSim horizon, stuck policy, and
iteration-0 boundary as Candidate2 and the TPDM3 control. It exits 0 after
13:16.65, completes iteration 0, has zero ERROR log lines and no OOM, and
retains the same five known equal-origin/destination-link Taxi rejections as
QSim-lost agents.

| Completed-trip metric | TPDM3 default | Candidate2, 114 links | Candidate3, all roads | Candidate3 vs Candidate2 |
|---|---:|---:|---:|---:|
| Completed trips / 743,614 | 555,858 | 562,470 | 567,553 | +5,083 |
| Completion rate | 74.7509% | 75.6400% | 76.3236% | +0.6836 pp |
| Mean time, completed trips | 54.350 min | 56.516 min | 55.072 min | -1.444 min |
| QSim-lost agents | 5 | 5 | 5 | 0 |

Candidate3 improves completion by 11,695 trips or 1.5727 percentage points
relative to TPDM3. Its raw completed-trip mean is 0.721 minutes above TPDM3
because the completed set admits additional long trips. Among the 553,140
trip IDs completed in both TPDM3 and Candidate3, Candidate3 is 3.174 minutes
faster: Car is 6.855 minutes faster, PT 2.920 minutes faster, and Taxi 12.168
minutes faster. Relative to Candidate2, the 558,734 common trips are 2.352
minutes faster: Car 3.306, PT 2.521, and Taxi 5.685 minutes faster.

Candidate3 newly completes 8,819 trips relative to Candidate2, averaging
229.207 minutes, while 3,736 Candidate2-only completed trips average 331.851
minutes. This completed-set replacement is why the aggregate mean and the
common-trip mean must both be reported.

| Mode | Candidate3 completed | Share of completed | Mean completed time |
|---|---:|---:|---:|
| Car | 38,093 | 6.7118% | 37.442 min |
| Car passenger | 2,734 | 0.4817% | 8.056 min |
| PT | 420,106 | 74.0206% | 51.734 min |
| Taxi | 27,186 | 4.7900% | 35.507 min |
| Walk | 79,434 | 13.9959% | 89.493 min |

The selected-plan mode shares remain identical across the matched smokes:
Car 9.1066%, Car passenger 0.3677%, PT 73.5453%, Taxi 5.9169%, and Walk
11.0635%. Candidate3 therefore changes road execution, not iteration-0 mode
selection.

Taxi requests conserve exactly:

```text
35,067 submitted = 27,186 completed + 975 waiting
                   + 6,901 onboard + 5 rejected
```

Taxi wait p50/p90/p95/p99 is 41/173/595/53,408 seconds. Empty VKT is
24,351.073 km, occupied VKT is 378,657.101 km, and the empty VKT ratio is
6.0423%.

The explicit-storage audit contains exactly 86,417 rows. Requested and actual
storage sums are both 169,291.861427 PCU; maximum absolute numerical
difference is `2.84e-14` PCU. All requested capacities are at least one PCU,
the range is 1.0 to 270.209227 PCU, and 3,134 links record at least one
blocked-inflow second. Candidate3 is therefore finite and binding rather than
an unlimited-queue implementation.

Candidate3 passes this technical smoke but remains a sensitivity, not the
production road supply. A universal one-PCU-per-lane floor is a broad modeling
assumption that can mask genuinely short physical storage or topology errors;
it requires calibration and multi-iteration validation before adoption.

## Candidate4 full-chain no-signal smoke

The immutable matched run is:

```text
/mnt/DiskM/by/
  hk_stage11_candidate11_taxi_dvrp_20260817_connector_chain_pcu005_it0_release1/
  hk_stage11_candidate11_taxi_dvrp_20260817_connector_chain_pcu005_it0_run1/

JAR SHA256:
cc8c3da75b3a49e8476f9673d2aeb7178b5e5958d28f8a74b42c3b4fa0fa61fa

acceptance audit:
  .../connector_chain_smoke_acceptance_v2/
    connector_chain_smoke_acceptance_summary.json
```

It uses the same original Candidate11 plans, no signals, physical Taxi fleet
at PCU 0.05, 16 threads, `stuckTime=3600 s`,
`removeStuckVehicles=false`, capacity factors 0.1, and iteration-0 boundary.
It completes iteration 0, shuts down normally, and exits 0 with the same five
known equal-origin/destination-link Taxi rejections/lost agents.

| Completed-trip metric | TPDM3 | Candidate3 | Candidate4 | C4 vs C3 |
|---|---:|---:|---:|---:|
| Completed / 743,614 | 555,858 | 567,553 | 568,231 | +678 |
| Completion rate | 74.7509% | 76.3236% | 76.4148% | +0.0912 pp |
| Raw mean, completed trips | 54.350 min | 55.072 min | 56.655 min | +1.583 min |
| QSim-lost agents | 5 | 5 | 5 | 0 |

The raw mean again reflects a changed completed set, but Candidate4 is also
slower on the 563,403 trip IDs completed in both Candidate3 and Candidate4:
`+0.704 min` overall, including Car `+0.585`, PT `+0.311`, and Taxi
`+9.159 min`. Candidate4 adds 4,828 completions averaging 298.709 minutes and
loses 4,150 Candidate3 completions averaging 217.220 minutes. Relative to the
TPDM3 control, however, the 553,097 common trips remain 2.075 minutes faster.

Completed Candidate4 outcomes by main mode are:

| Mode | Completed | Share of completed | Mean completed time |
|---|---:|---:|---:|
| Car | 38,027 | 6.6922% | 39.339 min |
| Car passenger | 2,734 | 0.4811% | 8.056 min |
| PT | 421,040 | 74.0966% | 53.203 min |
| Taxi | 26,986 | 4.7491% | 43.246 min |
| Walk | 79,444 | 13.9809% | 89.468 min |

The planned selected-mode shares are unchanged because all four smokes start
from the same plans. These are completed-trip composition shares, not a new
iteration-0 mode choice.

All 86,417 runtime supply rows match the registry. Maximum storage difference
is `2.84e-14 PCU`, and maximum flow difference over all 57 flow overrides is
exactly zero PCU per step. Blocked-link count falls from 3,134 to 3,105. On
the 57 target links, cumulative blocked-inflow seconds fall 0.9697%; 36 links
improve, 20 worsen, and one is unchanged. Network-wide cumulative blocked
seconds nevertheless rise 0.5412%, showing that releasing an internal
connector can move queues downstream rather than remove them.

For the Chatham Road South example, both chain segments use QSim flow
6,100 veh/h and exact three-PCU storage. `road_104307_0_r` blocked seconds fall
from 61,968 to 61,518, while `road_104308_0_f` rises from 62,912 to 63,149.
This confirms complete implementation but not removal of the broader corridor
bottleneck.

Taxi requests conserve exactly:

```text
34,998 submitted = 26,987 completed + 990 waiting
                   + 7,016 onboard + 5 rejected
```

Taxi wait p50/p90/p95/p99 is 42/194/719/53,590 seconds. Empty VKT is
27,294.499 km, occupied VKT is 374,661.539 km, and the empty VKT ratio is
6.7904%.

Candidate4 therefore passes structural and technical acceptance, including
the full-chain and flow-capacity requirements, but does **not** pass a clear
performance-adoption test against Candidate3. Its completion gain is only
0.0912 percentage points while common-trip time and network-wide blocking
worsen. It remains an opt-in diagnostic sensitivity and does not replace
Candidate3 or the production road supply.

## Candidate5A aggressive component regularization

Candidate5 deliberately relaxes the geometry-confidence constraint after the
bounded Candidate4 intervention failed its performance test. It remains a
QSim-only sensitivity: the physical network is copied byte-for-byte, and link
length, free speed, physical lane count, topology, route distance, and the
scenario-network capacity attribute do not change.

Stage A applies two independent rules:

1. every one of the 3,134 Candidate3 blocked links receives
   `S >= max(old, 2*x, 30*q)`, where `x` is its lane-based PCU floor and `q` is
   its QSim flow in PCU/s;
2. all 365 representation-review seeds are expanded through adjacent short or
   lane-deficient branches and cycles within five links and 80 m. Overlapping
   expansions merge into 231 components covering 1,609 unique links. A
   component receives a TPDM flow floor allocated across branches and
   `S >= max(old, 4*x_corridor, 60*q)`.

`storage_floor_pcu` is separate from `storage_lane_floor_x_pcu`, so the larger
finite-time buffer is not misrepresented as a physical lane count. Stages B
and C were pre-specified for links blocked at least 21,600 or 43,200 seconds,
respectively, but are not run because Stage A passes every gate.

Generated immutable inputs:

```text
/mnt/DiskM/by/hk_stage11_aggressive_road_supply_20260817_candidate5a/
  network_tpdm3_physical_candidate5a.xml.gz
  road_supply_parameters_v5a.csv
  road_storage_capacity_v5a.csv
  road_flow_capacity_v5a.csv
  road_component_membership_v5a.csv
  road_supply_candidate5a_summary.json

physical network SHA256:
2cc70f0e4c7a3966c698935bafcadbab65db3f13407e58442e7c13413d257979

registry SHA256:
a718938f64c35a75219a0214cc237ac2d8a4c44c7c62116ad624de1007e63268
```

The build increases QSim flow on 834 links relative to Candidate4; together
with Candidate4's 57 links, 890 registry rows are above their physical flow.
It increases storage on 3,656 links. The registry has all 86,417 road links,
never reduces Candidate4 flow or storage, and records 231 component audits.

The matched immutable smoke is:

```text
/mnt/DiskM/by/
  hk_stage11_candidate11_taxi_dvrp_20260817_candidate5a_pcu005_it0_release1/
  hk_stage11_candidate11_taxi_dvrp_20260817_candidate5a_pcu005_it0_run1/

JAR SHA256:
769639995137a1047f8eb8d457d58bedb4281f7457d3aa59093a0e54f67b7f4e

acceptance audit:
  .../candidate5a_smoke_acceptance_v1/
    candidate5a_smoke_acceptance_summary.json

acceptance summary SHA256:
3c6c187ab9d74d9303292f869a6ef43f90bf61d5e7bc50b2a79abe78b77020b6
```

It uses the same original Candidate11 plans, no signals, 15,500 physical Taxi
vehicles at PCU 0.05, 16 threads, capacity factors 0.1, `stuckTime=3600 s`,
`removeStuckVehicles=false`, and iteration 0 as Candidate3/4. It exits 0.

| Metric | TPDM3 | Candidate3 | Candidate4 | Candidate5A |
|---|---:|---:|---:|---:|
| Completed trips / 743,614 | 555,858 | 567,553 | 568,231 | 666,417 |
| Completion rate | 74.7509% | 76.3236% | 76.4148% | 89.6187% |
| Mean completed-trip time | 54.350 min | 55.072 min | 56.655 min | 48.090 min |
| Blocked links | - | 3,134 | 3,105 | 1,153 |
| All-link blocked seconds | - | 77,049,085 | 77,466,063 | 25,158,130 |

Candidate5A raises completion by 13.2039 percentage points versus Candidate4
and reduces blocked seconds by 67.5237%. Among 566,742 trip IDs completed in
both Candidate4 and Candidate5A, Candidate5A is 9.609 minutes faster on
average. The common-trip changes are -19.351 minutes for Car, -9.562 for PT,
-25.920 for Taxi, and zero for Walk and Car passenger. The result therefore
is not an artifact of only admitting additional long trips.

Taxi requests conserve exactly:

```text
40,966 submitted = 37,657 completed + 220 waiting
                   + 3,084 onboard + 5 rejected
```

Taxi wait p50/p90/p95/p99 is 38/127/209/699 seconds. Empty VKT is 23,994.846
km, occupied VKT is 467,903.142 km, and empty VKT share is 4.8780%.
Requested and actual flow match exactly; requested and actual storage differ
by at most `2.84e-14` PCU. This passes the pre-specified Stage A gates of at
least 80% completion, at least 50% blocked-seconds reduction versus
Candidate3, and no more than +0.5 minutes on common completed trips. It is the
recommended aggressive sensitivity, but is **not adopted as production**:
the relaxed component inference needs at least a repeated iteration-0 seed
check and a short multi-iteration stability run before adoption.

The immutable run metadata was produced by the Candidate4-era launcher and
retains the legacy text label `S=max(x,physical_default,safety)`. That label is
not the Candidate5 formula. The authoritative Candidate5 evidence is
`storage_floor_pcu` in the registry plus requested/actual values in the
per-iteration runtime audit. Future launcher metadata uses
`S=max(registry storage floor,physical default,queue safety)`.

## Candidate5B severe-chain regularization

Candidate5B is the next road-only sensitivity after the remaining Candidate5A
blocking audit showed 552 links blocked for at least six hours. It does not
modify PT service timing or add a second-day timetable. Each severe link is a
seed for a bidirectional local graph flood through severe links, inherited
Candidate5A connector components, links shorter than 30 m, and links with a
lane deficit relative to the seed corridor. The flood is bounded to 12 links
and 250 m. Overlapping **core** chains merge first; one ordinary entry/exit
boundary layer is attached only afterwards. Boundary overlap therefore does
not merge otherwise distinct corridors.

For every link in a rebuilt severe component, the Stage B flow target is:

```text
C_B = max(C_5A,
          min(2*C_4,
              max(TPDM(x_corridor), 1.25*C_4, C_boundary_allocated)))
```

and storage is:

```text
S_B = max(S_5A, 4*x_corridor, 60*q_B)
```

where `q_B=C_B*flowCapacityFactor/3600`. The TPDM term and branch allocation
are evaluated for the complete component, not just the original blocked link.
The physical network remains byte-identical, so route distance, free-flow time,
Taxi fare distance, lane count, and topology do not change.

The first server preview attached boundary links before component merging and
incorrectly collapsed the 552 seeds into two large components. That preview is
preserved at `hk_stage11_aggressive_road_supply_20260817_candidate5b` but is
not used by a MATSim run. The corrected immutable input is:

```text
/mnt/DiskM/by/hk_stage11_aggressive_road_supply_20260817_candidate5b2/
  network_tpdm3_physical_candidate5b.xml.gz
  road_supply_parameters_v5b.csv
  road_storage_capacity_v5b.csv
  road_flow_capacity_v5b.csv
  road_component_membership_v5b.csv
  road_supply_candidate5b_summary.json
```

It rebuilds 14 core components covering 2,507 unique links; 26 boundary links
belong to more than one component. Relative to Candidate5A it raises flow on
2,447 links and storage on 2,440 links. In total, 3,097 registry links now
have a QSim-only flow override. The registry still has exactly 86,417 road
links, never reduces Candidate5A flow or storage, and copies the physical
network byte-for-byte. The immutable `candidate5b2` summary was generated just
before the selection labels were clarified, so its legacy
`representation_component_*` fields contain the Stage B severe-component
counts. The repository generator now emits `component_basis`,
`severe_component_count`, and `severe_component_unique_links` explicitly; the
CSV capacities and the smoke inputs are unchanged by that metadata-only fix.

The matched immutable smoke is:

```text
/mnt/DiskM/by/
  hk_stage11_candidate11_taxi_dvrp_20260818_candidate5b2_pcu005_it0_release1/
  hk_stage11_candidate11_taxi_dvrp_20260818_candidate5b2_pcu005_it0_run1/

acceptance audit:
  .../candidate5b_smoke_acceptance_v1/
    candidate5b_smoke_acceptance_summary.json

acceptance SHA256:
  622a3fe05d606b14099dd8deb0f4da50f8072cf3a25dec63c80e201fa945778c
```

It uses the same original Candidate11 plans, no signals, physical Taxi fleet
at PCU 0.05, 16 threads, capacity factors 0.1, `stuckTime=3600 s`,
`removeStuckVehicles=false`, and iteration-0 boundary as Candidate5A. It exits
0 in 13:44.90, has zero ERROR/OOM records, and uses at most 20,650,308 KiB
RSS.

| Metric | Candidate5A | Candidate5B | Change |
|---|---:|---:|---:|
| Completed / 743,614 | 666,417 | 705,282 | +38,865 |
| Completion rate | 89.6187% | 94.8452% | +5.2265 pp |
| Raw mean completed time | 48.090 min | 44.539 min | -3.551 min |
| Blocked links | 1,153 | 714 | -439 |
| All-link blocked seconds | 25,158,130 | 969,862 | -96.1449% |
| PT waiting before first boarding | 21,054 | 17,148 | -18.5523% |
| PT unfinished onboard/transfer | 13,957 | 2,608 | -81.3140% |
| Private-car stuck | 5,891 | 315 | -94.6529% |
| Regular PT vehicles stuck | 15,627 | 2,374 | -84.8083% |
| Physical Taxi vehicles stuck | 3,246 | 1,090 | -66.4202% |
| Active agents at 30:00 | 63,416 | 24,971 | -60.6235% |

Candidate5B is also 3.267 minutes faster across the 665,907 trip IDs completed
in both stages: Car -3.873, PT -3.508, Taxi -6.486, Walk and Car passenger
zero. Requested and actual flow match exactly, while requested/actual storage
differ by at most `1.64e-13 PCU`. The original example chain is now treated
consistently: both `road_104307_0_r` and `road_104308_0_f` use 10,300 veh/h
QSim flow and 20 PCU storage; their blocked seconds fall from 40,549/41,288
in Candidate5A to 1,319/2,814.

Taxi requests conserve exactly:

```text
42,689 submitted = 41,588 completed + 42 waiting
                   + 1,054 onboard + 5 rejected
```

Taxi wait p50/p90/p95/p99 is 37/122/195/516 seconds and empty VKT share is
4.5898%.

All technical gates and the road-performance gates pass: completion exceeds
92%, blocked seconds fall more than 40% versus Candidate5A, common completed
trips are faster, and private-car stuck falls more than 50%. The combined gate
is nevertheless marked **not passed** because PT passengers waiting before
their first boarding fall only 18.55%, short of the deliberately strict 50%
target. Road expansion has already removed most road blocking but cannot fix
nominal-plan versus experienced-arrival drift or missing next-day PT service.
Candidate5C road escalation is therefore not run. The next experiment must
separate experienced PT timing and 24:00--30:00 timetable wrap from road
supply rather than add more road capacity. Candidate5B remains non-production.

That separated experiment is now complete. The experienced-PT/day-2 candidate
keeps this Candidate5B physical network and registry unchanged, adds 3,322
24:00--30:00 PT departures, and raises matched iteration-0 completion to
96.3699%. Combined waiting-before-board plus onboard/transfer unresolved PT
states fall 28.97%, while all-link blocked seconds fall another 1.09%. It is
documented in `HONG_KONG_EXPERIENCED_PT_TIMETABLE_V1.md` and remains an
opt-in sensitivity pending repeat-seed and multi-iteration validation.

## Candidate1 retained provenance

## Generated candidate

```text
/mnt/DiskM/by/hk_stage11_road_continuity_116_20260816_candidate1/
  network_road_continuity_116.xml.gz
  continuity_candidate_relationships.csv
  continuity_link_changes.csv
  road_continuity_candidate_summary.json

network SHA256:
d00cc33e764d2a76526f096cd3aeca7b17f8ef2d23955996deb073bb68d387a9
```

The immutable build-script payload is:

```text
/mnt/DiskM/by/hk_stage11_road_continuity_116_20260816_payload1/
```

## Candidate1 change summary (superseded)

| Metric over 114 unique target links | Before | After | Change |
|---|---:|---:|---:|
| Directional lane sum | 217 | 301 | +84 (+38.7097%) |
| Effective length sum | 5,342.856 m | 7,279.602 m | +1,936.746 m (+36.2493%) |
| Capacity sum | 437,700 veh/h | 612,300 veh/h | +174,600 veh/h (+39.8903%) |

- 53 links receive a lane and capacity increase.
- 100 links receive an effective-storage-length increase.
- The full physical-road TPDM3 capacity sum rises by only about 0.0811%; the
  large percentage above is confined to the 114 selected targets.
- The maximum effective-length increase is 66.919 m. The maximum lane change
  is from one to five lanes and remains a sensitivity assumption requiring
  runtime and geometry review.

## Candidate2/Candidate3 structural and unit QA

- The 117,990-link output network is byte-identical to TPDM3.
- The full registry contains exactly 86,417 physical road links.
- Exactly 114 selected IDs have storage overrides; 116 relationships remain.
- Every requested value satisfies `x`, default physical storage, one-step
  buffer, and free-flow-flow safety lower bounds.
- Network SHA and all registered physical fields are checked at startup.
- Python explicit-storage/Candidate1 tests (4/4), launcher regression tests
  (11/11), the dynamic-count Java QSim integration test, and the
  full Maven suite (179/179) pass.
- Existing plans, transit routes, DVRP fleet links, and signal references keep
  stable network IDs.

## Reproduction

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_explicit_storage_candidate.py `
  --input-network <network_tpdm_v4_three_candidate.xml.gz> `
  --hotspot-links <hotspot_links.csv> `
  --hotspot-neighbors <hotspot_neighbors.csv> `
  --output-dir <new-immutable-directory> `
  --expected-candidate-relationships 116 `
  --expected-unique-links 114
```

## Candidate5B traffic-signal A/B

The subsequent same-plan signal A/B keeps Candidate5B road supply fixed and
activates only Candidate11 safe-boundary TOD signals. After composing the
signals and explicit-storage QSim factories, the corrected run exits zero and
raises completion from 94.8452% to 97.1698%, although common completed trips
take 1.835 minutes longer. Flow-override-link blocked seconds fall 76.35% even
as network-wide blocked seconds rise 7.13%, consistent with signal metering
moving queues away from the most destructive connector bottlenecks. See
`HONG_KONG_CANDIDATE5B_SIGNAL_AB.md`; neither Candidate5B nor signals are
adopted by this sensitivity.
