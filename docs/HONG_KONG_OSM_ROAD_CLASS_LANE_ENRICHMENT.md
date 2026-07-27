# Hong Kong OSM road-class and lane enrichment

## Purpose

This workflow uses the local Hong Kong OSM PBF as secondary evidence for
RdNet road functional class and directional lane count. It only creates
candidate and validation tables. It does not edit MATSim network attributes or
capacity.

## Evidence hierarchy

Road class:

```text
ATC direct
> unanimous ST_CODE ATC corridor
> high-confidence OSM/ATC probability model
> existing speed/route/default fallback
```

Lane count:

```text
stable detector modal lanes
> OSM lanes:forward/backward
> OSM one-way lanes
> even OSM two-way total split
> existing ATC/AADT/corridor/default estimate
```

The probability model predicts only `EX/UT/PD/DD/LD`. It does not infer
`RT/RR`, because OSM does not provide a reliable urban/rural functional-class
distinction and the ATC rural training sample is small.

## Spatial matching

Each RdNet route is sampled at 20%, 50%, and 80% of its geometry. OSM
candidates are scored using:

- geometry distance;
- local bearing;
- one-way direction compatibility;
- English-name similarity when available.

A route requires at least two accepted samples, two-thirds highway-class
agreement, median distance no more than 15 m, and median bearing difference no
more than 30 degrees.

OSM `*_link` ways are not independently assigned a road class. They can inherit
a class only from a reliable non-link route with the same `ST_CODE`.

## Road-class model

Official 2024 ATC road types are used as labels. Features are intentionally
small and interpretable:

- OSM `highway` and `oneway`;
- RdNet legal speed and travel direction;
- route-number presence;
- OSM `maxspeed` and directional lane evidence;
- road-name similarity.

Validation uses five-fold `GroupKFold` by `ST_CODE`, so segments from the same
road corridor do not appear in both training and validation. Automatic
assignment requires:

```text
maximum probability >= 0.80
probability margin over second class >= 0.25
```

ATC-direct and ST_CODE-corridor classes remain protected even when OSM
disagrees.

## Lane parsing

- On one-way roads, `lanes` is interpreted as the directional lane count.
- `lanes:forward/backward` is aligned to RdNet digitization direction.
- An even two-way `lanes` total is split equally.
- Odd two-way totals without directional tags are retained only as audit
  evidence.
- Detector-derived lanes are protected.
- OSM differences greater than one lane from detailed ATC evidence, and OSM
  reductions that conflict with a prior `vc_adjustment`, require manual review.
- Any candidate change of three or more directional lanes also requires manual
  review, even when the OSM tags are syntactically valid.

## Run

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\transit_supply\enrich_hong_kong_road_classes_lanes_from_osm.py `
  --project-root F:\Matsim\matsim-example-project
```

## Outputs

Outputs are written to:

`data/transit/hongkong/processed/road_osm_class_lane_enrichment_2026_v1/`

- `osm_motor_road_tags.parquet`
- `osm_rdnet_sample_matches.csv`
- `osm_rdnet_crosswalk.csv`
- `road_type_candidates.csv`
- `lane_count_candidates.csv`
- `default_ld_upgrade_candidates.csv`
- `osm_atc_class_validation.csv`
- `osm_detector_lane_validation.csv`
- `manual_review.csv`
- `road_class_lane_candidates.parquet`
- `enrichment_summary.json`
- `osm_class_lane_enrichment_qa.png`
- `osm_class_lane_candidate_maps.png`

## Completed-run results

The completed run contains:

- `76,533` OSM motor-road ways.
- `36,395` unique RdNet routes and `47,923` legal route directions.
- `35,334` spatially reliable OSM matches (`97.08%`).
- `29,236` route directions with usable OSM lane evidence.
- `742` automatic road-class change candidates, including `408` routes
  previously classified as default-fallback `LD`.
- `11,520` automatic lane-change candidates.
- `6,777` manual-review records, including `370` extreme lane changes moved
  out of automatic adoption.

Five-fold spatially grouped road-class validation:

- all validation records: accuracy `0.644`, balanced accuracy `0.712`, macro
  F1 `0.671`;
- automatic threshold subset: `343` records (`21.5%` coverage), accuracy
  `0.813`;
- threshold-subset precision by predicted class:
  `EX=0.871`, `UT=0.700`, `PD=0.766`, `DD=1.000`, `LD=0.867`.

Detector lane validation:

- `481` reliable detector directions with usable final OSM lane evidence;
- exact agreement `84.2%`;
- agreement within one lane `96.9%`.

These figures support using OSM as candidate evidence. They do not support
unreviewed replacement of every current road class or lane count, especially
for `UT`, link roads, and large lane changes.

The deterministic downstream resolution is documented in
`docs/HONG_KONG_ROAD_CLASS_LANE_FINAL_DECISIONS.md`.
