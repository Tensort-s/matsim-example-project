# Hong Kong exact-SHA server bundle contract

## Stage 8D rework boundary

This is a deployment/provenance contract only. It changes no Java runtime,
MATSim configuration input, plan, network, transit schedule, vehicle,
facility, fare, cost or behavioral semantic. No server access, upload, build
or run is authorized by this repository change.

The active preparation entry point is:

```text
scripts/hong_kong_single_city/run/prepare_hong_kong_matsim_server_bundle.py
```

The script accepts two source-identity modes with equivalent fail-closed
strength:

- `git`: the original clean checkout whose `HEAD` equals the requested SHA;
- `snapshot`: a Git-metadata-free `git archive` whose sidecar manifest and
  extracted files reconstruct the locked Git tree exactly.

Snapshot mode is locked to source commit
`6ce087af803da1a4b21717c1e0073ce4a04c608a` and tree
`137f00cb10394ce6ff9df657aff8e2de72fb0073`. Its deterministic 7,620-file
Git blob inventory SHA256 is
`616c9a46eec91f103a03bb27d1d6b045135238d81f8db45eafcf7e8c1228d5d5`.
The prior snapshot source `3a56bcd14db3c6f815bbc5ac77901c24947b3ae4`
is an explicit rejected identity, not a fallback. The current contract verifies
the out-of-band
manifest SHA256, archive SHA256, 7,620-entry path/mode/blob/size/SHA256
inventory, reconstructed Git tree, extraction contents and absence of `.git`.
Only generated `target/` build output may coexist with the exact extracted
tracked files. The script also rejects stale v1 or pre-Ferry input paths. A
release root is mandatory and must be a new path below `/mnt/DiskM/by/`.

## Locked current inputs

| Role | Repository-relative path below `data/` | SHA256 |
|---|---|---|
| config template | `matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice/config_hong_kong_5pct_v2_activity_modechoice_50it.xml` | `75f9c8e82b6fee4141d3544c931309ca23abce76fe6d170c840acb007e1b115c` |
| plans | `matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice/plans_routed_5pct_v2.xml.gz` | `c73ee48e792e7aebd55b7a2691664ae7f3f4f27d307aef2a6bf58263b3aaafea` |
| facilities | `matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice/facilities_5pct_v2.xml.gz` | `74775533a7022b248d37197dbc94d27f239239aca386df75c7a391cc277ef10e` |
| private vehicles | `matsim_agents/hongkong/typical_weekday_5pct_v2_activity_modechoice/privateVehicles_5pct.xml.gz` | `5a48b2afe404afaa6864a465c527277605a276e54cd879d3971261186938c994` |
| network | `transit/hongkong/processed/matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_ferry_core_v1_cap010/network.xml.gz` | `dfc696442913a6d16a1ca1be7e5a332ec5762012190ed43a38f05493905ddc95` |
| transit schedule | `transit/hongkong/processed/matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_ferry_core_v1_cap010/transitSchedule_5pct.xml.gz` | `eb92e6c7b3c2746313be92b8c88d51bc645d1db3c6605d1f4b472f27c9896aed` |
| transit vehicles | `transit/hongkong/processed/matsim_road_pt_supply_2026_hybrid_capacity_mixed_bus_pcu005_ferry_core_v1_cap010/transitVehicles_10pct.xml.gz` | `16a6b89f77d3827ded06641869bf4e4c5168fb718356c1fe04e9f9249fdd7429` |

The source config is hash-verified before server-path adaptation. Formal
replanning, scoring, QSim, demand and capacity values are preserved. The
derived smoke config may change only the plans path, output path, iteration
limit and output intervals needed for that separately authorized smoke run.

## Linux JDK 25 build interface

A later Runner instruction must identify an already-approved Linux JDK 25 and
an approved bundle JDK archive. Neither may be downloaded or invented by this
workflow.

### Git-metadata-free source snapshot

From the clean reviewed integration worktree, create new local artifacts with
the reviewed control script. Both output paths must be new and outside the Git
worktree. This reads Git objects but does not modify the worktree, index or
refs:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  .\scripts\hong_kong_single_city\run\prepare_hong_kong_matsim_server_bundle.py `
  create-source-snapshot `
  --source-commit-sha 6ce087af803da1a4b21717c1e0073ce4a04c608a `
  --snapshot-path <new-source-snapshot.tar> `
  --snapshot-manifest <new-source-snapshot-manifest.json>
```

The command prints the archive and manifest SHA256 values. A later authorized
Runner records those values before transfer, copies the reviewed control
script, archive and manifest to new paths below `/mnt/DiskM/by/`, and verifies
the archive before extraction:

The control script must come from the exact pushed lock-anchor output reviewed
after this rework and remain outside the extracted source root. The historical
copy embedded in source commit `6ce087af…` is snapshot content, not the active
verification authority.

```bash
python3 <reviewed-external-control-script> verify-source-snapshot \
  --source-commit-sha 6ce087af803da1a4b21717c1e0073ce4a04c608a \
  --source-snapshot <transferred-source-snapshot.tar> \
  --source-snapshot-manifest <transferred-source-manifest.json> \
  --source-snapshot-manifest-sha256 <recorded-manifest-sha256>
```

Only after that check passes, extract into a new directory:

```bash
test ! -e "<new-extracted-source-root>"
mkdir "<new-extracted-source-root>"
tar --extract --file "<transferred-source-snapshot.tar>" \
  --directory "<new-extracted-source-root>" --no-same-owner
test ! -e "<new-extracted-source-root>/.git"
```

The verification command is then repeated with
`--source-root <new-extracted-source-root>`. Wrong commit, tree, manifest,
archive, member path/mode/blob, extracted content, or an unexpected
non-`target/` file fails closed.

### Server build

For a Git checkout, retain the original exact-HEAD/clean checks. For a source
snapshot, substitute the two successful snapshot verifications above. Then:

```bash
export JAVA_HOME="<approved-existing-linux-jdk-25>"
"$JAVA_HOME/bin/java" -version
cd "<verified-source-root>"
./mvnw -DskipTests package
```

The later bundle preparation call uses the `build-bundle` subcommand. In
snapshot mode it must pass the same source SHA, source root, archive, manifest
and out-of-band manifest SHA256 together with the resulting shaded JAR, the
approved JDK archive, a new release root and new output paths. The bundle
metadata records the complete source-identity result. It also supplies the
observed Java and Maven versions. MATSim is fixed at `2026.0`.

```bash
python3 <reviewed-external-control-script> build-bundle \
  --source-identity-mode snapshot \
  --source-commit-sha 6ce087af803da1a4b21717c1e0073ce4a04c608a \
  --source-root <verified-source-root> \
  --source-snapshot <transferred-source-snapshot.tar> \
  --source-snapshot-manifest <transferred-source-manifest.json> \
  --source-snapshot-manifest-sha256 <recorded-manifest-sha256> \
  <remaining-JAR-JDK-input-and-new-output-arguments>
```

The JAR must contain the current Taxi fare, five-layer PT fare, Car energy,
confirmed toll, resolved parking, combined Car owner and multimodal scoring
factory classes. Missing classes fail closed; an older server JAR is never a
fallback.

## Deployment manifest

The preparation script creates a sidecar deployment manifest after the bundle
is complete. It records:

- exact source commit and checkout-or-snapshot identity contract;
- source identity mode, exact tree and snapshot/archive/manifest hashes when
  snapshot mode is used;
- build and prepare commands plus Java, Maven and MATSim versions;
- shaded-JAR SHA256 and required runtime-class inventory;
- all seven locked input hashes and source config path;
- approved JDK archive SHA256;
- release root, staging path, bundle path, bundle SHA256, size and file count;
- timestamps and explicit `server_upload_performed=false` /
  `server_run_performed=false` flags.

All staging, bundle and manifest paths must be new. A new directory alone is
not a changed run identity and does not authorize upload or execution.

## Stage 8D rework evidence

The committed static validation is
`data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_bundle_preparation_rework_validation.json`.
The exact output SHA is supplied in the Executor handoff because a commit
cannot contain its own SHA.
