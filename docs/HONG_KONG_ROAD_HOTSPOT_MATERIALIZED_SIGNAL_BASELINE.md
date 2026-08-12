# Hong Kong road-hotspot V1 materialized signal baseline

Status: `candidate11_equivalent_inputs_runtime_validated_signal_performance_not_adopted`.

## Scope

This workflow materializes only the two bounded road-hotspot repairs already
validated by no-signal run62. It does not include run68 private-Car origin
anchor changes, proxy facilities, U-turn restrictions, household-plan changes,
or ordinary mode innovation. The candidate remains opt-in and does not replace
the production Hong Kong inputs, `city.yaml`, or run manifest.

The exact source is the run62 release input:

```text
/mnt/DiskM/by/hk_stage11_road_hotspot_repair_20260810_release62/input/
```

The final order-preserving independent candidate is:

```text
/mnt/DiskM/by/hk_road_hotspot_v1_materialized_20260813_candidate11/
```

Its immutable runtime-input SHA256 values are:

```text
network           7fd409368c5dbd8695cb4c0ef916229602f2918b88056ae05b441b532b6103cb
plans             393dd8967d84c69fe974d33a0945eda3fa6eccd0a42b1f3744016542d61cf855
transit schedule  a6faacd2c2f806842b21b8a9bf25ffcf444970ccc143e10b9b0062dca8a92ed1
transit vehicles  1bc60f48ab5a4dbadf64eb1d3ce856183611fa574da3924000f9323961f290a2
```

It contains independent network, plans, transit schedule, and transit vehicle
files plus SHA256 provenance, an explicit repair specification, and machine-
readable validation. Source facilities are read only: the four affected
activity-link references are written into the candidate plans, while production
facilities remain unchanged.

## Materialized mutation

The bounded order-preserving materializer implements the exact replacement
paths defined by the same `HongKongRoadHotspotRepairV1` used in run62, then a
MATSim Java validator loads the complete scenario. It performs only:

```text
road_261323_0_f -> road_105124_0_f
road_261308_0_f -> road_285290_0_f -> road_283946_0_f
```

The two restricted links become walk-only, matching run62's ordering in which
physical Walk is enabled before the runtime repair removes through-motor modes.
This ordering is part of the equivalence contract. An earlier candidate4
applied the repair before Walk was enabled and serialized the links with
`restricted_access`; its run2 then exposed 47,589 instead of 47,591 road links
and is retained only as a failed diagnostic. No server file or historical run
was overwritten or deleted.

Candidate11 changes 6,355 population routes, 111 transit routes, 109 transit
stop references, and four activity link references. It preserves 81,205 nodes,
120,411 links, 385,820 persons, 5,873 transit lines, 166,845 departures, and
163,406 transit vehicles. Static checks find zero forbidden route/activity
references, missing links, non-contiguous routes, missing stop links, out-of-
order stops, or motor-enabled restricted links. Both restricted links are
exactly walk-only. The transit-vehicle file is copied byte-for-byte.

Candidate11's four runtime XML files are byte-for-byte identical to the
runtime-tested candidate8 files. Candidate11 only strengthens provenance: its
manifest records the run62 source hashes, explicit replacement paths, and a
two-step state transition from bounded rewrite to passed full-scenario Java
reference validation. Its stop-link mapping reference is the independently
Java-materialized candidate5 schedule, not candidate8 itself. The launcher
accepts only the final `validated` and
`java_reference_validation=passed` state.

`MaterializeHongKongRoadHotspotRepairV1` refuses an existing output directory.
The Stage-11 launcher likewise refuses existing release/run roots, rejects a
candidate that includes run68 repairs, validates every recorded reference
check, and prevents simultaneous materialized and runtime hotspot repair.

## Signal rebuild boundary

The already completed candidate5 Stage 1/1.5 and Stage 2 build proved the
static modelling chain, but candidate5's all-entity MATSim XML serialization
changed source iteration order. Those tables are diagnostic only. Stage 1/1.5
and Stage 2 were rebuilt once more from candidate8 after its no-signal
equivalence gate passed.
The ignored, reproducible local outputs are:

```text
data/transit/hongkong/processed/
  hong_kong_traffic_signals_2026_v3_tpdm_proxy_stage1_road_hotspot_v1_candidate8/
  hong_kong_traffic_signals_2026_v3_tod_proxy_top100_road_hotspot_v1_candidate8/
```

Stage 1/1.5 retains 2,054 registry groups and reports 23 completely
unexpressed groups, 101 topology-review groups, 205 shared physical-path
signatures, 38 unresolved shared paths, and 86 movement rows excluded from q
because those shared paths remain unresolved. It does not activate any U-turn.

Stage 2 selects the same demand cutoff of 5,444 TPDM PCU/h and creates 100
systems by 96 fixed 15-minute plans: 9,600 plans, 241 groups, 566 signals, and
23,136 group windows. All 391 controlled approaches use the TPDM saturation
proxy in the separate capacity-deconvolved network. Static validation reports
zero missing or non-adjacent controlled turns, active U-turns, missing plan-
group references, and adjacent-cycle-grade violations. Signal activation
remains explicit; the candidate is not a production default.

## Runtime gate

The paired order is mandatory:

1. run the materialized candidate with signals disabled and ordinary
   innovation frozen;
2. establish equivalence to run62 on the same two-link treatment;
3. only after equivalence passes, run the candidate8 Top-100 TOD signal
   treatment from that no-signal release;
4. compare road delay, stuck vehicles, lost agents, controlled-approach use,
   signal mechanics, and private-Car, Bus, GMB, and school-bus outcomes.

The current strict no-signal paths are:

```text
/mnt/DiskM/by/hk_stage11_road_hotspot_materialized_20260813_release7/
/mnt/DiskM/by/hk_stage11_road_hotspot_materialized_20260813_run7/
```

Release7 deliberately uses the exact run62 application JAR SHA256
`614413eb5ab140dfa8ef67a70b81de9a8aa342b4f91de187bf490fb3223dc4df`.
This holds code constant so the only intended difference is pre-materialized
versus runtime mutation. Candidate8 also preserves the source network-link,
person, transit-line, route, and departure order by changing only the bounded
XML fields. An earlier release3/run3 used the current branch JAR;
different `RunHongKong5Pct` and repair class hashes made it invalid as strict
equivalence evidence. It was stopped, labelled
`invalid_diagnostic_mixed_jar_version_not_equivalence_evidence`, and retained.

Release5/run5 held the JAR constant but used candidate5's full MATSim writer
output. Its iteration-0 trajectory matched run3 rather than run62, showing
that entity reserialization was still a confounder; it was stopped and retained
as `invalid_diagnostic_full_xml_reserialization_changed_runtime_order`.

Run7 exits zero and passes the physical and student audits. Its static road
graph measures exactly match run62. The common road auditor reports 52,383.978
versus 52,809.005 vehicle-hours of delay (-0.80%) and 1,959 versus 1,897 road-
vehicle stuck events (+3.27%). Iteration-0 lost agents are 5,863 versus 5,890
(-0.46%). These are accepted as practical stochastic equivalence under the
multithreaded QSim, not claimed as byte-identical event reproduction. Run7's
class stuck counts are private Car 967, Bus 536, GMB 453, and school bus 3;
the run62 counts are 884, 559, 452, and 2 respectively. All differences remain
visible rather than being rounded away.

After this gate, candidate8 Stage 1/1.5 and Top-100 TOD files were rebuilt and
passed static validation. The completed paired signal treatment is at:

```text
/mnt/DiskM/by/hk_stage11_road_hotspot_tod_signals_20260813_release8/
/mnt/DiskM/by/hk_stage11_road_hotspot_tod_signals_20260813_run8/
```

Run8 uses release7 as its base, the exact run62 JAR, frozen ordinary
innovation, and explicit `--traffic-signals`. Its only intended treatment is
the validated capacity-deconvolved network plus the 100-by-96 TOD controller.
It exits zero. The iteration-1 event audit observes all 100 systems and 241
groups, 1,538,308 state changes, and zero missing-group, conflicting-green,
intergreen, amber, red-amber, or within-bin cycle violations. Of 391 controlled
approaches, 385 carry traffic. Controlled-approach entries fall from 482,606
to 481,109 (-0.31%): private Car -955, Bus -260, GMB -302, and school bus +20.

The paired road audit gives the performance decision. Total road delay rises
from 52,383.978 to 59,167.950 vehicle-hours (+12.95%), while road-vehicle
stuck rises from 1,959 to 2,028 (+3.52%). Private-Car stuck falls from 967 to
950 (-1.76%), but Bus rises from 536 to 575 (+7.28%), GMB from 453 to 500
(+10.38%), and school bus remains 3. The physical-mode audit passes every
check. The student audit also passes: all 1,001 selected school-bus legs have
departure, boarding, alighting, and arrival events, with no wrong vehicle,
stuck selected student, terminal load, or capacity violation.

Therefore the road-hotspot materialization is accepted as a reproducible
signal-development baseline, but this Top-100-by-96 controller is only a
mechanically valid sensitivity. It fails the performance-adoption gate,
remains explicitly switchable, and does not alter production inputs,
`city.yaml`, or the run manifest.
