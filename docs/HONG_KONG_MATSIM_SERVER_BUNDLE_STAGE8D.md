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
  extracted files reconstruct the exact tree named by that commit object.

Snapshot identity is dynamic: no source commit, tree, file count or inventory
hash is hardcoded in the control script. The formal Supervisor/Runner command
supplies the full exact source SHA. The Git-backed create command embeds the
raw Git commit object in the manifest, then derives its tree and complete
path/mode/blob/size/SHA256 inventory from that Git object. Verification
recomputes the Git commit-object SHA, requires equality with the supplied
exact SHA, requires the manifest/tree inventory to reconstruct the commit's
`tree` header, and checks the out-of-band manifest SHA256, archive SHA256,
extraction contents and absence of `.git`. Snapshot creation disables
host-specific `core.autocrlf`/`core.eol` conversion so archive members remain
the canonical Git blob bytes whose hashes reconstruct that tree.
Only generated `target/` build output may coexist with the exact extracted
tracked files. The script also rejects stale v1 or pre-Ferry input paths. A
release root is mandatory and must be a new path below `/mnt/DiskM/by/`.

### Committed full-tree validation evidence

The bounded evidence rework independently re-hashed and re-verified the full
local snapshot created from source commit
`c9fc2410fd329c9aceef16b3b7ce627bb74dedb6`. This was a local validation
artifact only; it was not transferred, deployed or executed.

| Field | Verified value |
|---|---|
| Git tree | `3114228a02931c2d7b43a18c971649653d9ceb66` |
| Tracked files | `7620` |
| Git blob inventory SHA256 | `e4f95f66f6d2ce27de4827125c09e42c990f69e954321d223f7320ac77d05324` |
| Full inventory SHA256 | `12cd617340b3f37a936d3d21e633d8378282a7422ba18532e15f4882224349f8` |
| Archive SHA256 | `34209c954c598a1d374f48d3b18bc4925a2d764ce197104063c0cb2ed78477eb` |
| Manifest SHA256 | `c5e9ed1ac0c59c99fb9ac385404a2317367f4484ca31ea83f04c6006f904cb7b` |
| Archive size | `1155952640` bytes |
| Manifest size | `2487564` bytes |
| Verification | commit object/tree/blob inventory/archive/manifest pass; `.git` absent |

Exact creation command:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  scripts/hong_kong_single_city/run/prepare_hong_kong_matsim_server_bundle.py `
  create-source-snapshot `
  --source-commit-sha c9fc2410fd329c9aceef16b3b7ce627bb74dedb6 `
  --snapshot-path "C:\Users\Yu Boyang\AppData\Local\Temp\hk-stage8d-dynamic-c9fc-blobbytes-20260731\source-c9fc.tar" `
  --snapshot-manifest "C:\Users\Yu Boyang\AppData\Local\Temp\hk-stage8d-dynamic-c9fc-blobbytes-20260731\source-c9fc.manifest.json"
```

Exact verification command:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  scripts/hong_kong_single_city/run/prepare_hong_kong_matsim_server_bundle.py `
  verify-source-snapshot `
  --source-commit-sha c9fc2410fd329c9aceef16b3b7ce627bb74dedb6 `
  --source-snapshot "C:\Users\Yu Boyang\AppData\Local\Temp\hk-stage8d-dynamic-c9fc-blobbytes-20260731\source-c9fc.tar" `
  --source-snapshot-manifest "C:\Users\Yu Boyang\AppData\Local\Temp\hk-stage8d-dynamic-c9fc-blobbytes-20260731\source-c9fc.manifest.json" `
  --source-snapshot-manifest-sha256 c5e9ed1ac0c59c99fb9ac385404a2317367f4484ca31ea83f04c6006f904cb7b
```

Snapshot creation internally runs `git archive` with
`core.autocrlf=false` and `core.eol=lf`; verification still treats each Git
blob SHA1 and the reconstructed commit tree as the authority.

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

## External locked-input pack

The seven production inputs are intentionally outside the tracked source
snapshot. A later Supervisor-authorized Runner must transfer them as a
separate new pack; an existing server data root, v1/pre-Ferry path or older
bundle is never a fallback. The compact pack layout is exactly the seven
`config/` and `input/` relative paths in the table above.

Create the pack and sidecar manifest locally from the canonical data root:

```powershell
F:\Matsim\matsim-example-project\.venv_geo311\Scripts\python.exe `
  scripts/hong_kong_single_city/run/prepare_hong_kong_matsim_server_bundle.py `
  create-locked-input-pack `
  --source-commit-sha <supervisor-authorized-exact-source-sha> `
  --source-data-root F:\Matsim\matsim-example-project\data `
  --pack-root <new-local-locked-input-pack-root> `
  --pack-manifest <new-local-locked-input-pack-manifest.json>
Get-FileHash -Algorithm SHA256 `
  -LiteralPath <new-local-locked-input-pack-manifest.json>
```

The manifest records the formal source SHA, seven relative paths, expected
and observed SHA256, sizes, original source paths, creation command and the
fact that input bytes were not modified. Transfer the pack directory and
manifest only into new server paths below `/mnt/DiskM/by/`, record the
manifest SHA256 out of band, preserve the manifest-bound pack-root basename,
then verify before invoking `build-bundle`:

```bash
python3 <reviewed-external-control-script> verify-locked-input-pack \
  --source-commit-sha <same-supervisor-authorized-exact-source-sha> \
  --pack-root /mnt/DiskM/by/<new-locked-input-pack-root> \
  --pack-manifest /mnt/DiskM/by/<new-locked-input-pack-manifest.json> \
  --pack-manifest-sha256 <recorded-pack-manifest-sha256>
```

Verification rejects a wrong formal SHA or manifest hash; any missing, extra,
symlinked, stale-v1, pre-Ferry or byte-mismatched file; and any inventory
other than the exact seven locked paths. The actual verified root, manifest
path and manifest SHA are carried into deployment metadata, and the sidecar
is copied into the prepared bundle for provenance.

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
  --source-commit-sha <supervisor-authorized-exact-source-sha> `
  --snapshot-path <new-source-snapshot.tar> `
  --snapshot-manifest <new-source-snapshot-manifest.json>
```

The command prints the archive and manifest SHA256 values. A later authorized
Runner records those values before transfer, copies the reviewed control
script, archive and manifest to new paths below `/mnt/DiskM/by/`, and verifies
the archive before extraction:

The control script must come from the exact pushed dynamic-identity output
reviewed after this rework and remain outside the extracted source root for
the pre-extraction check. No prior commit is an implicit fallback.

```bash
python3 <reviewed-external-control-script> verify-source-snapshot \
  --source-commit-sha <supervisor-authorized-exact-source-sha> \
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
  --source-commit-sha <supervisor-authorized-exact-source-sha> \
  --source-root <verified-source-root> \
  --source-snapshot <transferred-source-snapshot.tar> \
  --source-snapshot-manifest <transferred-source-manifest.json> \
  --source-snapshot-manifest-sha256 <recorded-manifest-sha256> \
  --data-root-mode external_locked_input_pack \
  --data-root /mnt/DiskM/by/<new-locked-input-pack-root> \
  --locked-input-pack-manifest /mnt/DiskM/by/<new-locked-input-pack-manifest.json> \
  --locked-input-pack-manifest-sha256 <recorded-pack-manifest-sha256> \
  <remaining-JAR-JDK-input-and-new-output-arguments>
```

The JAR must contain the current Taxi fare, five-layer PT fare, Car energy,
confirmed toll, resolved parking, combined Car owner and multimodal scoring
factory classes. Missing classes fail closed; an older server JAR is never a
fallback.

## Deployment manifest

The preparation script creates a sidecar deployment manifest after the bundle
is complete. It records:

- exact source commit, verified Git commit object and checkout-or-snapshot
  identity contract;
- source identity mode, exact tree and snapshot/archive/manifest hashes when
  snapshot mode is used;
- build and prepare commands plus Java, Maven and MATSim versions;
- shaded-JAR SHA256 and required runtime-class inventory;
- all seven locked input hashes and source config path;
- data-root mode, verified external pack root, source SHA, sidecar path and
  sidecar SHA256, exact verification command/result, plus a bundled copy of
  the locked-input manifest;
- approved JDK archive SHA256;
- release root, staging path, bundle path, bundle SHA256, size and file count;
- timestamps and explicit `server_upload_performed=false` /
  `server_run_performed=false` flags.

All staging, bundle and manifest paths must be new. A new directory alone is
not a changed run identity and does not authorize upload or execution.

## Stage 8D rework evidence

The committed static validation is
`data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_bundle_preparation_rework_validation.json`.
The compact server-side Runner evidence is
[`stage8d_server_bundle_evidence.json`](../data/transport_costs/hongkong/integration_stage8d_rework_validation_v1/stage8d_server_bundle_evidence.json).
The exact output SHA is supplied in the Executor handoff because a commit
cannot contain its own SHA.

### Runner server-bundle result for source 674a6025

Runner reached `FUSELAB01` through `by@100.103.8.34`, verified the exact
source snapshot and seven-file external pack, built the shaded JAR with Linux
Java 25.0.3/Maven 3.9.8, prepared the bundle and verified the 21-file release
inventory. Key artifact hashes are recorded by field in the compact evidence
JSON:

- `source_snapshot`: archive `e2c000f…`, manifest `1162d2d…`, tree
  `59f213b…`, 7,620 entries, with exact archive, manifest, extracted-root
  and reviewed-script paths;
- `external_locked_input_pack`: manifest `b79f399…`, seven locked hashes,
  with exact pack-root and manifest paths;
- `isolated_build`: exit 0, `1:19.48`, peak RSS `1036196` KB, JAR
  `b9afb03…` with required Taxi/PT/Car/multimodal classes, exact build-root
  and JAR paths;
- `bundle`: `/mnt/DiskM/by/hk_stage8d_674a6025_staging_isolated2/bundle_corrected.tar`,
  SHA256 `ee821d3…`, deployment manifest `ad3bc6d…`;
- `release`: `/mnt/DiskM/by/hk_multimodal_cost_674a6025_stage8d_build2`,
  21 files, `sha256sum -c` passed and no stale/pre-Ferry matches;
- `upload`: independent `upload_evidence.json` SHA256 `987d099…` records
  `server_upload_performed=true` while the prepared deployment manifest
  remains non-uploading and non-running. The JSON records the exact deployment
  manifest and upload-evidence paths.

Runner discovered these paths read-only under `/mnt/DiskM/by`; Executor did
not access the server or infer any path.

This was preparation/upload evidence only. No MATSim/QSim/Stage 9 run,
iteration, event, cost or score was produced.
