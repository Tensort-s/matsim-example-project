# Hong Kong TPDM Volume 4 three-candidate road-capacity network

## Status

This is a generated, full-scale **non-adopted candidate**. It preserves the
road-hotspot V1 materialized topology and all non-capacity link attributes,
then adds an independent TPDM Volume 4 saturation-flow candidate to the two
capacity candidates already represented by each source-link capacity. It has
not replaced the production network. One full-population iteration-0 smoke is
documented below; multi-iteration and signal-enabled validation remain open.

## Immutable inputs and outputs

Source network:

```text
/mnt/DiskM/by/hk_stage11_road_hotspot_materialized_20260813_release7/input/network.xml.gz
SHA256: 7fd409368c5dbd8695cb4c0ef916229602f2918b88056ae05b441b532b6103cb
```

Accepted generated candidate:

```text
/mnt/DiskM/by/hk_stage11_road_hotspot_tpdm_v4_three_candidate_20260816_candidate2/
  network_tpdm_v4_three_candidate.xml.gz
  capacity_link_audit.csv
  tpdm_v4_three_candidate_summary.json

network SHA256: 2cc70f0e4c7a3966c698935bafcadbab65db3f13407e58442e7c13413d257979
```

The earlier immutable `candidate1` is retained. `candidate2` contains the same
network bytes and adds the final split audit used below.

## Formula and units

The source capacity is treated as the already-selected maximum of the two
existing candidates. For every physical road link, the independent TPDM
candidate uses a 3.25 m representative lane width because the network has no
complete, reliable link-level lane-width field:

```text
S_nearside_or_sole = 1940 + 100 * (W - 3.25)
S_other            = 2080 + 100 * (W - 3.25)

S_TPDM(N, W) = S_nearside_or_sole(W) + (N - 1) * S_other(W)

C_new = ceil_to_50(max(C_existing_two_candidate_max, S_TPDM))
```

At `W = 3.25 m`, the raw TPDM directional candidates for one through seven
lanes are 1,940, 4,020, 6,100, 8,180, 10,260, 12,340, and 14,420 pcu/h. After
rounding upward to 50 pcu/h, they are 1,950, 4,050, 6,100, 8,200, 10,300,
12,350, and 14,450 pcu/h.

The network remains full-scale. MATSim `flowCapacityFactor=0.1` and
`storageCapacityFactor=0.1` remain runtime sampling controls and are not baked
into the XML capacities.

## Capacity comparison

The physical-road scope is any link that permits `car`, `bus`, `gmb`, or
`school_bus`. It contains 47,589 car-permitting links and 38,828 transit-only
road links.

| Scope | Links | Changed | Old sum (pcu/h) | New sum (pcu/h) | Increase | Increase rate |
|---|---:|---:|---:|---:|---:|---:|
| All physical roads | 86,417 | 86,077 | 153,384,950 | 215,261,500 | 61,876,550 | 40.3407% |
| Car-permitting roads | 47,589 | 47,249 | 83,495,200 | 139,546,900 | 56,051,700 | 67.1316% |
| Transit-only roads | 38,828 | 38,828 | 69,889,750 | 75,714,600 | 5,824,850 | 8.3343% |

The link-sum is a reproducible network-change diagnostic, not a claim that
these serial and parallel links collectively provide that much territory-wide
throughput. The car-road percentage is much larger because most transit-only
links were already close to the one-lane TPDM floor.

Per directional lane count:

| Lanes | Links | Old mean | New mean | Increase rate |
|---:|---:|---:|---:|---:|
| 1 | 69,612 | 1,506.26 | 1,950.00 | 29.4599% |
| 2 | 12,418 | 2,309.14 | 4,050.02 | 75.3912% |
| 3 | 3,382 | 4,068.95 | 6,100.00 | 49.9157% |
| 4 | 870 | 5,793.16 | 8,200.00 | 41.5462% |
| 5 | 112 | 7,578.13 | 10,300.00 | 35.9175% |
| 6 | 12 | 9,279.17 | 12,350.00 | 33.0938% |
| 7 | 11 | 8,650.00 | 14,450.00 | 67.0520% |

## Validation and limitations

- 117,990 links parse successfully; 86,417 are in the physical-road scope.
- 86,077 links are TPDM-controlled and 340 retain the higher existing value.
- No capacity decreases occur and all 31,573 non-road links are unchanged.
- Source and output non-capacity XML content have the identical SHA256
  `a315fec584301f39d9a3909687f5bf902ceae5997921b283924f0c2acdce0426`.
- Node/link IDs, topology, modes, lengths, speeds, lane counts, and attributes
  are unchanged, so existing route and signal references remain structurally
  stable.
- The 3.25 m width is an explicit uniform proxy. This candidate must not be
  interpreted as measured link-level saturation flow.
- Signal-controlled links keep this value as base road supply. Signal timing
  must impose its separate effective loss; the TPDM maximum must not be applied
  again after signal deconvolution.

## Full-population iteration-0 smoke

The first controlled full-population smoke completed successfully under:

```text
release: /mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260816_tpdm3_pcu005_it0_release1
run:     /mnt/DiskM/by/hk_stage11_candidate11_taxi_dvrp_20260816_tpdm3_pcu005_it0_run1
```

It uses the original 385,820-person Candidate11 plans, no signals, the same
15,500-vehicle physical Taxi fleet and application JAR as the preceding run7
road-hotspot control, Taxi PCU 0.05, `stuckTime=3600`, and
`removeStuckVehicles=false`. The only material road-supply change in the pair
is the network capacity XML. Both runs have the same 743,614 selected trips.

| Main mode | Selected | Old completed | New completed | Old completion | New completion | Change | Old mean completed time | New mean completed time |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Car | 67,718 | 29,743 | 36,108 | 43.9219% | 53.3211% | +9.3993 pp | 43.89 min | 34.47 min |
| Car passenger | 2,734 | 2,734 | 2,734 | 100.0000% | 100.0000% | 0.0000 pp | 8.06 min | 8.06 min |
| PT | 546,893 | 390,615 | 411,861 | 71.4244% | 75.3092% | +3.8849 pp | 55.94 min | 50.87 min |
| Taxi | 43,999 | 22,327 | 25,839 | 50.7443% | 58.7263% | +7.9820 pp | 43.48 min | 34.58 min |
| Walk | 82,270 | 79,096 | 79,316 | 96.1420% | 96.4094% | +0.2674 pp | 89.47 min | 89.51 min |
| **All** | **743,614** | **524,515** | **555,858** | **70.5359%** | **74.7509%** | **+4.2150 pp** | **59.54 min** | **54.35 min** |

Mean times use only completed rows from `0.trips.csv.zst`; unfinished trips do
not receive zero time. On the stricter 515,196-trip intersection that completes
in both runs with the same trip ID and main mode, the weighted mean falls from
56.05 to 52.07 minutes, or 7.10%. The matched reductions are 18.14% for Car,
8.54% for PT, and 20.55% for Taxi; walk and car-passenger times are unchanged.
This confirms that the raw mean-time reduction is not solely survivor-set
turnover.

The run exits 0 after iteration 0, records five QSim-lost agents, and has no
OOM or illegal network/route/vehicle/reference error. Taxi accounting conserves
34,332 submitted requests as 25,839 completed, 1,003 waiting, 7,485 onboard,
and five rejected. The candidate materially improves the controlled smoke but
does not remove the finite-fleet/network limitation: completion remains below
the 82.0637% same-JAR teleported-Taxi retained-stuck control. It therefore
remains a tested sensitivity candidate rather than an adopted production
network.

## Reproduction

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\build_hong_kong_tpdm_v4_three_candidate_network.py `
  --input-network <network.xml.gz> `
  --output-dir <new-immutable-directory> `
  --lane-width-m 3.25 `
  --capacity-rounding-vph 50 `
  --flow-capacity-factor 0.1
```
