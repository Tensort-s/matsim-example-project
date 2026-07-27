# Project operating guide

## Project overview

This repository is a multi-city MATSim and OD-modeling workspace. It currently
contains mature Fuzhou and Hong Kong workflows spanning source-data
preparation, geospatial feature engineering, OD estimation, synthetic
population and activity-plan generation, road and public-transport supply,
MATSim simulation, QA, and visualization.

The canonical local project root is:

```text
F:\Matsim\matsim-example-project
```

The F-drive `master` worktree is the authoritative project. Codex-created
worktrees under `C:\Users\Yu Boyang\.codex\worktrees\` are feature worktrees,
not the main project unless explicitly merged.

Read these files before making substantial changes:

1. `docs/PROJECT_ONBOARDING.md`
2. For Hong Kong: `docs/HONG_KONG_FINAL_WORKFLOW.md`
3. `cities/<city>/city.yaml`
4. `runs/<city>/run_manifest.json`
5. The topic-specific Markdown document for the affected workflow

## Main objectives

The main research objective is to build a reusable urban OD and traffic-flow
modeling system that can be transferred between cities while retaining local
data fidelity. The system should:

- integrate official statistics, open GIS, population, POI, imagery, road,
  transit, and survey data;
- estimate work, school, visitor, border, and other activity demand;
- produce auditable OD matrices and synthetic MATSim agents/plans;
- construct calibrated road and multimodal public-transport supply;
- support reproducible MATSim simulation, validation, and visualization;
- separate reusable modeling logic from city-specific data assumptions;
- clearly distinguish observed data, inferred parameters, calibrated outputs,
  synthetic demand, and historical comparison products.

## Working environment

- OS and shell: Windows, PowerShell
- Java/MATSim: Java 25, Maven project, `pom.xml`
- Geospatial/data environment:
  `.venv_geo311\Scripts\python.exe`
- WEDAN/RemoteCLIP environment:
  `.venv_wedan\Scripts\python.exe`
- Fuzhou metadata: `cities/fuzhou/city.yaml`
- Hong Kong metadata: `cities/hongkong/city.yaml`
- Shared WEDAN code:
  `data/worldcommuting_od/_shared/GeneratingCodeData/`

Use explicit project interpreters instead of bare `python`.

Formal Hong Kong WEDAN GPU work uses:

```text
by@100.103.8.34:/home/by/OD/HK
```

It must use one GPU, no more than 10 GiB GPU memory, and no automatic CPU
fallback. SSH, CUDA, DGL, GPU-memory, or OOM failures must stop and be reported.

Formal Hong Kong MATSim server work uses only:

```text
by@100.103.8.34:/mnt/DiskM/by
```

Do not use `sudo`, do not operate outside the permitted root, and do not delete
server files. New attempts must use new directories rather than overwriting or
cleaning previous runs.

## PowerShell rules

- Use PowerShell syntax, not Bash syntax.
- Prefer `rg` or `rg --files` for repository searches.
- Use `Get-ChildItem -LiteralPath`, `Get-Content -LiteralPath`, and
  `Test-Path -LiteralPath` for paths containing spaces or non-ASCII text.
- Prefer one logical command per invocation. Avoid long command chains and
  shell-dependent quoting.
- Use absolute paths when operating outside the active worktree.
- The integrated terminal and Codex command runner are separate processes.
  Do not assume they share environment variables, current directories, or
  activated virtual environments.
- If the Codex runner cannot start the WindowsApps `pwsh.exe` alias, use the
  available Windows PowerShell executable or another verified PowerShell
  installation. Treat `CreateProcessAsUserW failed: 5` as a runner/alias
  problem, not automatically as a project failure.
- Do not use destructive commands such as recursive deletion, `git reset
  --hard`, or checkout-based file replacement unless explicitly requested and
  the target has been verified.

## Encoding rules

- Project-owned Markdown, CSV, JSON, YAML, and Python source files use UTF-8.
- Read Chinese Markdown explicitly when terminal encoding is uncertain:

```powershell
Get-Content -Encoding UTF8 -LiteralPath .\docs\PROJECT_ONBOARDING.md
```

- Python readers and writers must specify `encoding="utf-8"`.
- Configure PowerShell output for UTF-8 when working interactively:

```powershell
chcp 65001 > $null
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
```

- Garbled terminal output is not proof that a file is corrupt. Verify the
  encoding before rewriting it.

## Data and provenance rules

- Keep raw source data, large rasters, model outputs, caches, and simulation
  results out of Git unless a small control file is intentionally tracked.
- Source files must live under the appropriate project `data/` subtree, not
  depend on `D:\Program Files` or another external download directory.
- Preserve source filenames where practical and maintain `SOURCE_MANIFEST.csv`
  or equivalent SHA256 provenance records.
- Never fabricate missing official data. Mark inferred fields, proxy
  capacities, synthetic demand, and fallback geometry explicitly.
- Do not silently replace observed constraints with modeled values.
- Do not overwrite user-edited Word documents such as `docs/已有数据.docx` and
  `docs/需求清单.docx`. These two manual documents are intentionally tracked
  by Git; read and preserve their formatting and wording.

## Documentation requirements

Every meaningful change must update documentation in the same task:

- update the most relevant existing Markdown file;
- create a new Markdown file when no suitable document exists;
- link new workflow documents from `docs/PROJECT_ONBOARDING.md` or the relevant
  index;
- update `docs/HONG_KONG_FINAL_WORKFLOW.md`, `cities/hongkong/city.yaml`, or
  `runs/hongkong/run_manifest.json` whenever an adopted Hong Kong input,
  configuration, output, or final run changes;
- label old versions as historical baselines rather than deleting provenance;
- record units, CRS, dimensions, assumptions, source dates, validation
  metrics, and known limitations.

Documentation must distinguish:

- current production inputs and outputs;
- upstream build dependencies;
- historical or sensitivity versions;
- local compact visualizations versus complete server simulation outputs.

## Git and worktree rules

- Check `git status`, branch, and worktree location before editing.
- The canonical `master` is checked out at
  `F:\Matsim\matsim-example-project`.
- Do not assume a Codex C-drive worktree modifies `master`.
- Never revert unrelated user changes or untracked files.
- Stage and commit only files belonging to the current task.
- Do not push to GitHub unless requested.
- Keep manual documents and ignored data in place when switching branches or
  worktrees.

## Hong Kong production invariants

Unless a later adopted document explicitly supersedes them, the current Hong
Kong production scenario uses:

- CRS `EPSG:32650`;
- 1,585 fixed-link grids at 920.658900389797 m nominal cell size;
- Census-projected Hong Kong WEDAN work OD;
- DCCA-constrained student-school OD;
- PT-accessibility V2 border and visitor demand;
- 5% resident representation and 385,820 total agents;
- v2 multi-activity, mode-choice plans;
- Ferry Core v1 public-transport supply;
- 10% public-transport passenger capacity;
- bus/GMB road PCU factors of 5%;
- `flowCapacityFactor=0.1`;
- `storageCapacityFactor=0.1`;
- 50 MATSim iterations;
- `formal_50it_ptfixed_ferry_activity_simwrapper` as the final local
  visualization.

## Minimum verification

Scale verification to the change, but normally include:

- Python syntax or `--help` checks for modified scripts;
- JSON/YAML/XML parsing where relevant;
- matrix shape, finite-value, non-negativity, symmetry, and conservation QA;
- MATSim network/schedule/vehicle/reference checks for supply changes;
- `git diff --check`;
- confirmation that documented paths exist;
- a concise update to the relevant Markdown documentation.
